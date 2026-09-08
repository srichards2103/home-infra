import json
import subprocess

import pytest

from homeinfra import backup
from homeinfra.config import InfraError


@pytest.fixture
def config(tmp_path):
    password = tmp_path / "password"
    password.write_text("example-password-only-for-tests")
    password.chmod(0o600)
    data = tmp_path / "data"
    data.mkdir()
    file = tmp_path / "backup.json"
    file.write_text(
        json.dumps(
            {
                "name": "test",
                "repository": "sftp:example.invalid:/backups",
                "password_file": str(password),
                "paths": [str(data)],
                "restic": "/example/bin/restic",
            }
        )
    )
    return file


def test_backup_passes_credentials_by_reference_and_no_shell(config, monkeypatch):
    calls = []
    monkeypatch.setattr(backup.subprocess, "run", lambda *a, **kw: calls.append((a, kw)))
    backup.execute(config, "run")
    (argv,), options = calls[0]
    assert argv[:4] == ["/example/bin/restic", "backup", "--tag", "homeinfra:test"]
    assert "--" in argv
    assert options["check"] is True
    assert "shell" not in options
    assert "example-password-only-for-tests" not in str(calls)
    assert "RESTIC_PASSWORD_FILE" in options["env"]


def test_restore_refuses_existing_destination(config, tmp_path):
    with pytest.raises(InfraError, match="must not exist"):
        backup.execute(config, "restore", tmp_path)


def test_retention_is_dry_run_and_never_prunes(config, monkeypatch):
    calls = []
    monkeypatch.setattr(backup.subprocess, "run", lambda argv, **kw: calls.append(argv))
    backup.execute(config, "retention-plan")
    assert "--dry-run" in calls[0]
    assert "--prune" not in calls[0]


def test_failed_backup_propagates_failure(config, monkeypatch):
    def fail(argv, **kwargs):
        raise subprocess.CalledProcessError(3, argv)

    monkeypatch.setattr(backup.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        backup.execute(config, "run")


def test_restore_uses_tag_and_fresh_destination(config, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(backup.subprocess, "run", lambda argv, **kw: calls.append(argv))
    backup.execute(config, "restore", tmp_path / "new-restore", "abc123")
    assert calls[0][1:] == [
        "restore",
        "abc123",
        "--tag",
        "homeinfra:test",
        "--target",
        str(tmp_path / "new-restore"),
    ]
