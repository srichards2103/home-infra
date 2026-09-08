"""Explicit restic operations. Backups never implicitly prune or restore live data."""

import json
import stat
import subprocess
from pathlib import Path

from homeinfra.config import InfraError, name
from homeinfra.runtime import read_secrets


def execute(config: Path, operation: str, destination: Path | None = None, snapshot="latest"):
    raw = json.loads(config.read_text())
    allowed = {"name", "repository", "password_file", "paths", "environment_file", "restic"}
    if set(raw) - allowed:
        raise InfraError("Unknown backup configuration field")
    tag = "homeinfra:" + name(raw["name"])
    restic = raw.get("restic", "/opt/homebrew/bin/restic")
    if not Path(restic).is_absolute():
        raise InfraError("restic executable must be absolute")
    password = Path(raw["password_file"])
    if (
        not password.is_absolute()
        or password.is_symlink()
        or not stat.S_ISREG(password.stat().st_mode)
        or password.stat().st_mode & 0o077
    ):
        raise InfraError("Restic password must be a private file, mode 0600 or stricter")
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": "/var/root"}
    if raw.get("environment_file"):
        env.update(read_secrets(Path(raw["environment_file"])))
    env.update(RESTIC_REPOSITORY=raw["repository"], RESTIC_PASSWORD_FILE=str(password))
    argv = [restic]
    if operation == "init":
        argv += ["init"]
    elif operation == "run":
        paths = raw["paths"]
        if not paths or any(not Path(p).is_absolute() or not Path(p).exists() for p in paths):
            raise InfraError("Every backup path must exist and be absolute")
        argv += ["backup", "--tag", tag, "--", *paths]
    elif operation == "check":
        argv += ["check"]
    elif operation == "snapshots":
        argv += ["snapshots", "--tag", tag]
    elif operation == "restore":
        if destination is None or not destination.is_absolute():
            raise InfraError("Restore requires an absolute --destination")
        if destination.exists():
            raise InfraError("Restore destination must not exist; restore into a fresh directory")
        if snapshot.startswith("-"):
            raise InfraError("Invalid snapshot identifier")
        argv += ["restore", snapshot, "--tag", tag, "--target", str(destination)]
    elif operation == "retention-plan":
        argv += [
            "forget",
            "--tag",
            tag,
            "--group-by",
            "host,paths,tags",
            "--keep-daily",
            "7",
            "--keep-weekly",
            "4",
            "--keep-monthly",
            "12",
            "--dry-run",
        ]
    else:
        raise InfraError("Unknown backup operation")
    # Inherit output for restic progress. Credentials are passed only through env/file references.
    subprocess.run(argv, env=env, check=True)  # noqa: S603
