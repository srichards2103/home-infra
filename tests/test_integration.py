"""Real loopback processes; no host launchd calls, sudo, or installed service users."""

import os
import socket
import subprocess
import sys
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from examples.hello.app import LoopbackServer
from homeinfra import artifacts
from homeinfra.config import InfraError
from homeinfra.deploy import Deployer
from homeinfra.runtime import environment, healthy


class ProcessBackend:
    def __init__(self, layout):
        self.layout = layout
        self.process = None
        self.controller = None

    def stop(self, name):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            self.process = None

    def start(self, name):
        revision = self.controller.current(name)
        service = self.controller.service_at(name, revision)
        release = self.layout.release(name, revision)
        data = self.layout.data(name)
        self.process = subprocess.Popen(
            [service.expand(arg, release, data, revision) for arg in service.command],
            cwd=data,
            env=environment(service, release, data, revision),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def test_real_http_deploy_failure_rollback_and_recovery(tmp_path, layout, service):
    with socket.socket() as allocation:
        allocation.bind(("127.0.0.1", 0))
        port = allocation.getsockname()[1]
    service = replace(
        service,
        environment={"PORT": str(port)},
        health={
            "url": f"http://127.0.0.1:{port}/healthz",
            "timeout": 3,
            "expect": '"release": "{version}"',
        },
    )
    source = Path(__file__).resolve().parents[1] / "examples/hello"
    archive = tmp_path / "hello.tar.gz"
    sha = artifacts.pack(source, archive)
    backend = ProcessBackend(layout)
    deployer = Deployer(layout, backend)
    backend.controller = deployer
    try:
        deployer.deploy(service, archive, "v1", sha)
        assert deployer.status("hello")["healthy"]
        deployer.deploy(service, archive, "v2", sha)
        assert deployer.status("hello")["current"] == "v2"
        broken = replace(service, command=[sys.executable, "-c", "raise SystemExit(1)"])
        with pytest.raises(InfraError, match="New release failed"):
            deployer.deploy(broken, archive, "broken", sha)
        assert deployer.status("hello")["current"] == "v2"
        assert deployer.status("hello")["healthy"]
        deployer.rollback("hello")
        assert deployer.status("hello")["current"] == "v1"
        assert deployer.status("hello")["healthy"]
    finally:
        backend.stop("hello")


@pytest.fixture
def http_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/healthy")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x" * 65537 if self.path == "/large" else b"release-v1")

        def log_message(self, *args):
            pass

    server = LoopbackServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_health_rejects_redirects_large_bodies_and_stale_versions(
    http_server,
    service,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("no_proxy", "")
    for path, revision, expected in [
        ("/healthy", "v1", True),
        ("/redirect", "v1", False),
        ("/large", "v1", False),
        ("/healthy", "v2", False),
    ]:
        configured = replace(
            service, health={"url": http_server + path, "expect": "release-{version}", "timeout": 1}
        )
        assert healthy(configured, tmp_path, tmp_path, revision, wait=False) is expected


def test_zipapp_runs_without_project_or_site_packages(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(repo / "scripts/build_cli.py")], check=True, cwd=repo)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(repo / "dist/homeinfra.pyz"),
            "validate",
            str(repo / "examples/hello/service.json"),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={"PATH": os.defpath},
    )
    assert result.stdout.strip() == "Manifest valid"


def test_remote_ssh_command_quotes_arguments():
    from scripts.deploy_remote import remote_argv

    argv = remote_argv("mini", ["echo", "a b; $(touch never)", "'quoted'"])
    import shlex

    assert argv[:4] == [
        "ssh",
        "--",
        "mini",
        shlex.join(["echo", "a b; $(touch never)", "'quoted'"]),
    ]
    assert shlex.split(argv[-1]) == ["echo", "a b; $(touch never)", "'quoted'"]
