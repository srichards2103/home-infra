from dataclasses import replace

import pytest

from homeinfra.config import InfraError
from homeinfra.deploy import Deployer, verify_runtime_identity, write_json

from .conftest import read_state


def install(deployer, service, artifact, revision):
    return deployer.deploy(service, artifact[0], revision, artifact[1])


def test_success_noop_and_manual_rollback(deployer, service, artifact):
    assert install(deployer, service, artifact, "v1") == {"changed": True, "current": "v1"}
    events = list(deployer.backend.events)
    assert install(deployer, service, artifact, "v1")["changed"] is False
    assert deployer.backend.events == events
    install(deployer, service, artifact, "v2")
    assert read_state(deployer) == {"current": "v2", "previous": "v1"}
    assert deployer.rollback("hello") == {"current": "v1"}
    assert deployer.status("hello")["healthy"]
    assert not deployer.status("hello")["recovery_required"]


def test_wrong_digest_does_not_touch_running_service(deployer, service, artifact):
    install(deployer, service, artifact, "v1")
    events = list(deployer.backend.events)
    with pytest.raises(InfraError, match="SHA-256 mismatch"):
        deployer.deploy(service, artifact[0], "v2", "0" * 64)
    assert deployer.current("hello") == "v1"
    assert deployer.backend.events == events
    assert not deployer.layout.release("hello", "v2").exists()


def test_existing_release_cannot_change_manifest(deployer, service, artifact):
    install(deployer, service, artifact, "v1")
    with pytest.raises(InfraError, match="different contents or manifest"):
        install(deployer, replace(service, environment={"NEW": "value"}), artifact, "v1")
    assert deployer.current("hello") == "v1"


def test_failed_health_restores_previous_state_and_plist(deployer, service, artifact):
    install(deployer, service, artifact, "v1")
    previous_plist = deployer.layout.plist("hello").read_bytes()
    deployer.probe = lambda _s, _r, _d, revision, **kw: revision != "broken"
    with pytest.raises(InfraError, match="New release failed"):
        install(deployer, service, artifact, "broken")
    assert deployer.current("hello") == "v1"
    assert deployer.backend.running
    assert read_state(deployer) == {"current": "v1", "previous": None}
    assert deployer.layout.plist("hello").read_bytes() == previous_plist
    assert not (deployer.layout.app("hello") / "transaction.json").exists()


def test_first_release_failure_leaves_no_current_job(deployer, service, artifact):
    deployer.probe = lambda *args, **kwargs: False
    with pytest.raises(InfraError, match="New release failed"):
        install(deployer, service, artifact, "broken")
    assert deployer.current("hello") is None
    assert not deployer.backend.running
    assert not deployer.layout.plist("hello").exists()


def test_double_failure_blocks_deployments_until_recovery(deployer, service, artifact):
    install(deployer, service, artifact, "v1")
    deployer.probe = lambda *args, **kwargs: False
    with pytest.raises(InfraError, match="Deployment and rollback failed"):
        install(deployer, service, artifact, "v2")
    assert deployer.status("hello")["recovery_required"]
    with pytest.raises(InfraError, match="interrupted deployment"):
        install(deployer, service, artifact, "v3")
    deployer.probe = lambda *args, **kwargs: True
    assert deployer.recover("hello") == {"changed": True, "current": "v1"}
    assert deployer.recover("hello") == {"changed": False}
    assert read_state(deployer) == {"current": "v1", "previous": None}


def test_recovery_after_interruption_at_target_activation(deployer, service, artifact):
    install(deployer, service, artifact, "v1")
    original_state = read_state(deployer)
    install(deployer, service, artifact, "v2")
    write_json(
        deployer.layout.app("hello") / "transaction.json",
        {"prior": "v1", "target": "v2", "previous_state": original_state},
    )
    assert deployer.recover("hello")["current"] == "v1"
    assert read_state(deployer) == original_state


def test_concurrent_operations_fail_without_mutating(deployer, service, artifact):
    other = Deployer(deployer.layout, deployer.backend, deployer.probe)
    with deployer.locked("hello"):
        with pytest.raises(InfraError, match="deployment lock"):
            install(other, service, artifact, "v1")
    assert not deployer.backend.events


def test_policy_prevents_changing_execution_user(layout, service):
    verify_runtime_identity(layout, service)
    with pytest.raises(InfraError, match="provisioned service account"):
        verify_runtime_identity(layout, replace(service, user="someone_else"))


def test_unhealthy_current_version_is_not_blindly_restarted(deployer, service, artifact):
    install(deployer, service, artifact, "v1")
    events = list(deployer.backend.events)
    deployer.probe = lambda *args, **kwargs: False
    with pytest.raises(InfraError, match="current but unhealthy"):
        install(deployer, service, artifact, "v1")
    assert deployer.backend.events == events


def test_rotate_stops_before_renaming_and_keeps_bounded_history(deployer, service, artifact):
    install(deployer, service, artifact, "v1")
    assert deployer.rotate("hello", max_bytes=2) == {"changed": False}
    log = deployer.layout.log_root / "hello/stdout.log"
    for number in range(4):
        log.write_text(f"stream {number}")
        assert deployer.rotate("hello", max_bytes=2, keep=2)["changed"]
    assert log.with_name("stdout.log.1").read_text() == "stream 3"
    assert log.with_name("stdout.log.2").read_text() == "stream 2"
    assert not log.with_name("stdout.log.3").exists()
    assert deployer.backend.events[-2:] == [("stop", "hello"), ("start", "hello")]


def test_start_failure_attempts_rollback(deployer, service, artifact):
    install(deployer, service, artifact, "v1")
    original_start = deployer.backend.start

    def fail_target(name):
        if deployer.current(name) == "v2":
            raise OSError("simulated launchctl failure")
        original_start(name)

    deployer.backend.start = fail_target
    with pytest.raises(OSError):
        install(deployer, service, artifact, "v2")
    assert deployer.current("hello") == "v1"
    assert deployer.backend.running
