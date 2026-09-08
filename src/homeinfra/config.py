"""Strict public service manifests: commands are argv, secrets are file references."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

NAME = re.compile(r"[a-z][a-z0-9-]{0,39}\Z")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
ENV = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
TOKENS = {"release", "data", "version", "name"}


class InfraError(Exception):
    """An actionable configuration or operation failure."""


def name(value: str) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise InfraError(
            "Name must be 1–40 lowercase letters, digits or hyphens, starting with a letter"
        )
    return value


def version(value: str) -> str:
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise InfraError("Invalid release version")
    return value


def template(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise InfraError("Expected a non-empty string without NUL bytes")
    remainder = value
    for token in TOKENS:
        remainder = remainder.replace("{" + token + "}", "")
    if "{" in remainder or "}" in remainder:
        raise InfraError("Only {release}, {data}, {version} and {name} placeholders are supported")
    return value


@dataclass(frozen=True)
class Service:
    name: str
    user: str
    command: list[str]
    health: dict
    environment: dict[str, str] = field(default_factory=dict)
    secret_env_file: str | None = None
    schema_version: int = 1

    @classmethod
    def load(cls, path: Path):
        try:
            raw = json.loads(path.read_text())
            if not isinstance(raw, dict):
                raise InfraError("Manifest must be an object")
            obj = cls(**raw)
            obj.validate()
            return obj
        except (TypeError, ValueError, OSError) as exc:
            raise InfraError(f"Invalid manifest: {path.name}") from exc

    def validate(self):
        name(self.name)
        if self.schema_version != 1:
            raise InfraError("Unsupported manifest schema_version")
        if not isinstance(self.user, str) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", self.user):
            raise InfraError("Invalid service user")
        if self.user in {"root", "daemon", "nobody"}:
            raise InfraError("Use a dedicated, unprivileged service account")
        if not isinstance(self.command, list) or not self.command:
            raise InfraError("command must be a non-empty argv list")
        for arg in self.command:
            template(arg)
        if not self.command[0].startswith(("/", "{release}/")):
            raise InfraError("Command executable must be absolute or inside {release}")
        if not isinstance(self.environment, dict):
            raise InfraError("environment must be an object")
        for key, value in self.environment.items():
            if not ENV.fullmatch(key) or key.startswith("HOMEINFRA_"):
                raise InfraError("Invalid or reserved environment name")
            template(value)
        if self.secret_env_file is not None:
            expected = f"/etc/home-infra/secrets/{self.name}.json"
            if self.secret_env_file != expected:
                raise InfraError(f"secret_env_file must be {expected}")
        if not isinstance(self.health, dict) or set(self.health) - {"url", "timeout", "expect"}:
            raise InfraError("health supports url, timeout and optional expect")
        url = urlsplit(self.health.get("url", ""))
        if url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port:
            raise InfraError("Health URL must use http://127.0.0.1 with an explicit port")
        if url.username or url.password or url.fragment:
            raise InfraError("Invalid health URL")
        timeout = self.health.get("timeout", 30)
        if type(timeout) is not int or not 1 <= timeout <= 300:
            raise InfraError("health.timeout must be an integer from 1 to 300 seconds")
        if "expect" in self.health:
            template(self.health["expect"])

    def expand(self, value: str, release: Path, data: Path, revision: str) -> str:
        return value.format(release=str(release), data=str(data), version=revision, name=self.name)
