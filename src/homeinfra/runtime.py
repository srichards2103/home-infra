"""Service execution and the launchd boundary. No shell interpolation."""

import json
import os
import plistlib
import stat
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from homeinfra.config import ENV, InfraError, Service


def read_secrets(path: Path) -> dict[str, str]:
    if path.is_symlink():
        raise InfraError("Secret file cannot be a symlink")
    with path.open() as stream:
        mode = os.fstat(stream.fileno()).st_mode
        if not stat.S_ISREG(mode) or stat.S_IMODE(mode) & 0o077:
            raise InfraError("Secret file must be a regular file with mode 0600 or stricter")
        raw = json.load(stream)
    if not isinstance(raw, dict) or any(
        not ENV.fullmatch(k) or k.startswith("HOMEINFRA_") or not isinstance(v, str) or "\x00" in v
        for k, v in raw.items()
    ):
        raise InfraError("Secret file must contain an object of environment strings")
    return raw


def environment(service: Service, release: Path, data: Path, revision: str):
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(data), "TMPDIR": str(data / "tmp")}
    env.update(
        {k: service.expand(v, release, data, revision) for k, v in service.environment.items()}
    )
    if service.secret_env_file:
        env.update(read_secrets(Path(service.secret_env_file)))
    env.update(HOMEINFRA_SERVICE=service.name, HOMEINFRA_RELEASE=revision, HOMEINFRA_DATA=str(data))
    return env


def render(service: Service, release: Path, data: Path, logs: Path, runner: Path, python: str):
    return plistlib.dumps(
        {
            "Label": f"org.homeinfra.{service.name}",
            "ProgramArguments": [python, str(runner), "run", str(release)],
            "UserName": service.user,
            "WorkingDirectory": str(data),
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 10,
            "ExitTimeOut": 20,
            "Umask": 0o077,
            "StandardOutPath": str(logs / "stdout.log"),
            "StandardErrorPath": str(logs / "stderr.log"),
            "ProcessType": "Background",
        },
        sort_keys=True,
    )


class Launchd:
    def __init__(self, plist_directory: Path):
        self.directory = plist_directory

    def stop(self, service_name: str):
        target = f"system/org.homeinfra.{service_name}"
        probe = subprocess.run(["/bin/launchctl", "print", target], capture_output=True)  # noqa: S603
        if probe.returncode:
            return
        subprocess.run(["/bin/launchctl", "bootout", target], check=True, capture_output=True)  # noqa: S603

    def start(self, service_name: str):
        path = self.directory / f"org.homeinfra.{service_name}.plist"
        subprocess.run(  # noqa: S603 - fixed launchctl executable and validated service name
            ["/bin/launchctl", "enable", f"system/org.homeinfra.{service_name}"],
            check=True,
            capture_output=True,
        )
        subprocess.run(  # noqa: S603 - fixed launchctl executable and managed plist path
            ["/bin/launchctl", "bootstrap", "system", str(path)], check=True, capture_output=True
        )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def healthy(
    service: Service, release: Path, data: Path, revision: str, *, wait: bool = True
) -> bool:
    deadline = time.monotonic() + (service.health.get("timeout", 30) if wait else 0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    expected = service.health.get("expect")
    if expected:
        expected = service.expand(expected, release, data, revision)
    while True:
        try:
            with opener.open(service.health["url"], timeout=2) as response:  # noqa: S310
                body = response.read(65537)
                if response.status == 200 and len(body) <= 65536:
                    if expected is None or expected.encode() in body:
                        return True
        except (OSError, urllib.error.URLError):
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)
