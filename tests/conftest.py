import json
import sys

import pytest

from homeinfra import artifacts
from homeinfra.config import Service
from homeinfra.deploy import Deployer, Layout, write_json


class FakeLaunchd:
    def __init__(self):
        self.events = []
        self.running = False

    def stop(self, name):
        self.events.append(("stop", name))
        self.running = False

    def start(self, name):
        self.events.append(("start", name))
        self.running = True


@pytest.fixture
def service():
    return Service(
        "hello",
        "hi_hello",
        [sys.executable, "{release}/app.py"],
        {"url": "http://127.0.0.1:8090/healthz", "timeout": 1, "expect": '"release": "{version}"'},
    )


@pytest.fixture
def layout(tmp_path):
    value = Layout(tmp_path / "root", tmp_path / "plists", tmp_path / "logs", sys.executable)
    (value.app("hello") / "releases").mkdir(parents=True)
    (value.data("hello") / "tmp").mkdir(parents=True)
    (value.log_root / "hello").mkdir(parents=True)
    value.plists.mkdir()
    write_json(value.app("hello") / "policy.json", {"user": "hi_hello"})
    return value


@pytest.fixture
def artifact(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("print('hello')\n")
    archive = tmp_path / "release.tar.gz"
    sha = artifacts.pack(source, archive)
    return archive, sha


@pytest.fixture
def deployer(layout):
    return Deployer(layout, FakeLaunchd(), lambda *args, **kwargs: True)


def read_state(deployer):
    return json.loads((deployer.layout.app("hello") / "state.json").read_text())
