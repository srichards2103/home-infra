"""Serialized release transactions with durable recovery metadata."""

import fcntl
import json
import os
import plistlib
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from homeinfra import artifacts
from homeinfra.config import InfraError, Service, name, version
from homeinfra.runtime import Launchd, healthy, render


def atomic_write(path: Path, content: bytes, mode: int = 0o644):
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    temp = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temp.chmod(mode)
        os.replace(temp, path)
        # Persist the rename as well as the file contents.
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temp.unlink(missing_ok=True)


def write_json(path: Path, value):
    atomic_write(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


@dataclass(frozen=True)
class Layout:
    root: Path = Path("/opt/home-infra")
    plists: Path = Path("/Library/LaunchDaemons")
    log_root: Path = Path("/var/log/home-infra")
    python: str = "/opt/homebrew/opt/python@3.13/bin/python3.13"

    def app(self, service_name):
        return self.root / "apps" / name(service_name)

    def release(self, service_name, revision):
        return self.app(service_name) / "releases" / version(revision)

    def data(self, service_name):
        return self.root / "data" / name(service_name)

    def plist(self, service_name):
        return self.plists / f"org.homeinfra.{name(service_name)}.plist"


class Deployer:
    def __init__(self, layout: Layout, backend=None, probe=healthy):
        self.layout = layout
        self.backend = backend or Launchd(layout.plists)
        self.probe = probe

    @contextmanager
    def locked(self, service_name):
        app = self.layout.app(service_name)
        if not app.is_dir() or app.is_symlink():
            raise InfraError(
                "Service is not provisioned; apply its Ansible service definition first"
            )
        with (app / ".deploy.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise InfraError("Another operation holds this service's deployment lock") from exc
            yield app

    def current(self, service_name):
        app = self.layout.app(service_name)
        link = app / "current"
        if not link.is_symlink():
            if link.exists():
                raise InfraError("Current release must be a managed symlink")
            return None
        resolved = link.resolve(strict=True)
        if resolved.parent != (app / "releases").resolve():
            raise InfraError("Current release points outside the managed releases directory")
        return version(resolved.name)

    def service_at(self, service_name, revision):
        service = Service.load(
            self.layout.release(service_name, revision) / ".homeinfra-manifest.json"
        )
        if service.name != service_name:
            raise InfraError("Release manifest does not match the service")
        return service

    def set_current(self, service_name, revision):
        app = self.layout.app(service_name)
        if revision is None:
            (app / "current").unlink(missing_ok=True)
            return
        temporary = app / ".current-next"
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(Path("releases") / revision)
        os.replace(temporary, app / "current")

    def install_plist(self, service: Service, revision):
        layout = self.layout
        atomic_write(
            layout.plist(service.name),
            render(
                service,
                layout.release(service.name, revision),
                layout.data(service.name),
                layout.log_root / service.name,
                layout.root / "bin/homeinfra.pyz",
                layout.python,
            ),
        )

    def check(self, service_name, revision, wait=True):
        return self.probe(
            self.service_at(service_name, revision),
            self.layout.release(service_name, revision),
            self.layout.data(service_name),
            revision,
            wait=wait,
        )

    def restore(self, service_name, prior):
        self.backend.stop(service_name)
        self.set_current(service_name, prior)
        if prior is None:
            self.layout.plist(service_name).unlink(missing_ok=True)
            return
        self.install_plist(self.service_at(service_name, prior), prior)
        self.backend.start(service_name)
        if not self.check(service_name, prior):
            raise InfraError("Previous release failed its recovery health check; journal retained")

    def activate(self, service_name, revision):
        app = self.layout.app(service_name)
        journal = app / "transaction.json"
        if journal.exists():
            raise InfraError("An interrupted deployment needs `homeinfra recover` first")
        prior = self.current(service_name)
        previous_state = (
            json.loads((app / "state.json").read_text()) if (app / "state.json").exists() else {}
        )
        write_json(journal, {"prior": prior, "target": revision, "previous_state": previous_state})
        try:
            self.backend.stop(service_name)
            self.set_current(service_name, revision)
            self.install_plist(self.service_at(service_name, revision), revision)
            self.backend.start(service_name)
            if not self.check(service_name, revision):
                raise InfraError("New release failed its health check")
            write_json(app / "state.json", {"current": revision, "previous": prior})
        except BaseException as original:
            try:
                self.restore(service_name, prior)
                write_json(app / "state.json", previous_state)
            except Exception as recovery_error:
                raise InfraError(
                    "Deployment and rollback failed; run recover and inspect service logs"
                ) from recovery_error
            journal.unlink()
            raise original
        journal.unlink()

    def deploy(self, service: Service, archive: Path, revision: str, expected_digest: str):
        version(revision)
        service.validate()
        if len(expected_digest) != 64 or any(c not in "0123456789abcdef" for c in expected_digest):
            raise InfraError("Expected SHA-256 must be 64 lowercase hex characters")
        with self.locked(service.name) as app:
            if (app / "transaction.json").exists():
                raise InfraError("An interrupted deployment needs `homeinfra recover` first")
            # Copy first, then verify and extract that same snapshot to avoid source-file races.
            with tempfile.TemporaryDirectory(prefix=".stage-", dir=app) as temporary:
                stage = Path(temporary)
                snapshot = stage / "artifact.tar.gz"
                shutil.copyfile(archive, snapshot)
                if artifacts.digest(snapshot) != expected_digest:
                    raise InfraError("Artifact SHA-256 mismatch; running service unchanged")
                destination = self.layout.release(service.name, revision)
                if destination.exists():
                    stored = (destination / ".homeinfra-digest").read_text().strip()
                    existing = self.service_at(service.name, revision)
                    if stored != expected_digest or existing != service:
                        raise InfraError(
                            "Release version already exists with different contents or manifest"
                        )
                    if self.current(service.name) == revision:
                        if not self.check(service.name, revision, wait=False):
                            raise InfraError(
                                "Release is current but unhealthy; inspect logs before restarting"
                            )
                        return {"changed": False, "current": revision}
                else:
                    content = stage / "content"
                    content.mkdir()
                    artifacts.extract(snapshot, content)
                    write_json(content / ".homeinfra-manifest.json", asdict(service))
                    atomic_write(content / ".homeinfra-digest", (expected_digest + "\n").encode())
                    content.chmod(0o755)
                    os.replace(content, destination)
            self.activate(service.name, revision)
            return {"changed": True, "current": revision}

    def rollback(self, service_name, revision=None):
        with self.locked(service_name) as app:
            if revision is None:
                state = json.loads((app / "state.json").read_text())
                revision = state.get("previous")
            if revision is None:
                raise InfraError("There is no previous release")
            self.service_at(service_name, revision)
            if self.current(service_name) == revision:
                raise InfraError("Requested release is already current")
            self.activate(service_name, revision)
            return {"current": revision}

    def recover(self, service_name):
        with self.locked(service_name) as app:
            journal = app / "transaction.json"
            if not journal.exists():
                return {"changed": False}
            state = json.loads(journal.read_text())
            self.restore(service_name, state["prior"])
            write_json(app / "state.json", state["previous_state"])
            journal.unlink()
            return {"changed": True, "current": state["prior"]}

    def status(self, service_name):
        with self.locked(service_name) as app:
            revision = self.current(service_name)
            return {
                "service": service_name,
                "current": revision,
                "recovery_required": (app / "transaction.json").exists(),
                "healthy": self.check(service_name, revision, wait=False) if revision else False,
                "plist_installed": self.layout.plist(service_name).exists(),
            }

    def rotate(self, service_name, max_bytes=10 * 1024**2, keep=5):
        """Stop before renaming open logs; always attempt to restart after rotation."""
        with self.locked(service_name) as app:
            if (app / "transaction.json").exists():
                raise InfraError("An interrupted deployment needs recovery before log rotation")
            revision = self.current(service_name)
            if revision is None:
                raise InfraError("No deployed release")
            paths = [
                self.layout.log_root / service_name / f"{stream}.log"
                for stream in ("stdout", "stderr")
            ]
            if any(path.is_symlink() for path in paths):
                raise InfraError("Log files must not be symlinks")
            if not any(path.exists() and path.stat().st_size >= max_bytes for path in paths):
                return {"changed": False}
            self.backend.stop(service_name)
            try:
                for path in paths:
                    path.with_name(path.name + f".{keep}").unlink(missing_ok=True)
                    for number in range(keep - 1, 0, -1):
                        old = path.with_name(path.name + f".{number}")
                        if old.exists() or old.is_symlink():
                            os.replace(old, path.with_name(path.name + f".{number + 1}"))
                    if path.exists():
                        os.replace(path, path.with_name(path.name + ".1"))
            finally:
                self.backend.start(service_name)
            if not self.check(service_name, revision):
                raise InfraError("Service failed its health check after log rotation")
            return {"changed": True}


def verify_runtime_identity(layout: Layout, service: Service):
    """Provisioning owns the execution identity; deployments cannot replace it."""
    policy = json.loads((layout.app(service.name) / "policy.json").read_text())
    if service.user != policy["user"]:
        raise InfraError("Manifest user differs from the provisioned service account")
    if not layout.data(service.name).is_dir():
        raise InfraError("Service data directory is missing")
    # Parse an existing plist before changes, rather than hiding corrupt configuration.
    if layout.plist(service.name).exists():
        plistlib.loads(layout.plist(service.name).read_bytes())
