import json
import plistlib
from dataclasses import asdict, replace

import pytest

from homeinfra.config import InfraError, Service
from homeinfra.runtime import environment, read_secrets, render


@pytest.mark.parametrize(
    "change",
    [
        {"name": "../escape"},
        {"user": "root"},
        {"schema_version": 2},
        {"command": "echo hi"},
        {"command": ["python", "app.py"]},
        {"command": ["/bin/echo", "{unknown}"]},
        {"environment": {"HOMEINFRA_RELEASE": "fake"}},
        {"health": {"url": "https://example.com:443"}},
        {"health": {"url": "http://localhost:8090"}},
        {"health": {"url": "http://127.0.0.1:8090", "timeout": True}},
        {"secret_env_file": "/tmp/secret.json"},
    ],
)
def test_invalid_manifest(tmp_path, service, change):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(asdict(service) | change))
    with pytest.raises(InfraError):
        Service.load(path)


def test_unknown_manifest_fields_rejected(tmp_path, service):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(asdict(service) | {"typo": "ignored?"}))
    with pytest.raises(InfraError):
        Service.load(path)


def test_plist_escapes_paths_and_has_no_secret_values(layout, service):
    secret_service = replace(service, secret_env_file="/etc/home-infra/secrets/hello.json")
    value = render(
        secret_service,
        layout.root / "a&b",
        layout.data("hello"),
        layout.log_root / "hello",
        layout.root / "bin/homeinfra.pyz",
        layout.python,
    )
    parsed = plistlib.loads(value)
    assert parsed["UserName"] == "hi_hello"
    assert parsed["ProgramArguments"][-1].endswith("a&b")
    assert "EnvironmentVariables" not in parsed
    assert b"secrets" not in value
    assert parsed["KeepAlive"] is True
    assert parsed["Umask"] == 0o077


def test_private_secrets_and_minimal_environment(tmp_path, monkeypatch, layout, service):
    secret = tmp_path / "secrets.json"
    secret.write_text('{"APP_TOKEN":"example-test-value"}')
    secret.chmod(0o600)
    assert read_secrets(secret) == {"APP_TOKEN": "example-test-value"}
    monkeypatch.setenv("UNRELATED_ADMIN_SECRET", "never-inherited")
    configured = replace(service, secret_env_file=str(secret), environment={"DATA": "{data}"})
    env = environment(configured, layout.release("hello", "v1"), layout.data("hello"), "v1")
    assert env["APP_TOKEN"] == "example-test-value"
    assert env["HOMEINFRA_RELEASE"] == "v1"
    assert "UNRELATED_ADMIN_SECRET" not in env
    secret.chmod(0o644)
    with pytest.raises(InfraError, match="0600"):
        read_secrets(secret)


def test_secret_symlink_rejected(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "missing")
    with pytest.raises(InfraError, match="symlink"):
        read_secrets(link)


def test_reserved_environment_secret_rejected(tmp_path):
    secret = tmp_path / "secrets.json"
    secret.write_text('{"HOMEINFRA_RELEASE":"fake"}')
    secret.chmod(0o600)
    with pytest.raises(InfraError):
        read_secrets(secret)
