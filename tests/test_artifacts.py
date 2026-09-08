import io
import os
import tarfile

import pytest

from homeinfra import artifacts
from homeinfra.config import InfraError


def malicious(tmp_path, members):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for member in members:
            tar.addfile(member, io.BytesIO(b"x" * member.size) if member.isfile() else None)
    output = tmp_path / "output"
    output.mkdir()
    return archive, output


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "ok/../../escape",
        "x\\evil",
        ".homeinfra-manifest.json",
        "x/.homeinfra-digest",
    ],
)
def test_unsafe_paths_rejected(tmp_path, path):
    archive, output = malicious(tmp_path, [tarfile.TarInfo(path)])
    with pytest.raises(InfraError, match="Unsafe archive path"):
        artifacts.extract(archive, output)
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE]
)
def test_links_and_special_files_rejected(tmp_path, kind):
    member = tarfile.TarInfo("entry")
    member.type = kind
    member.linkname = "/etc/passwd"
    archive, output = malicious(tmp_path, [member])
    with pytest.raises(InfraError, match="link or special"):
        artifacts.extract(archive, output)


def test_duplicate_path_rejected(tmp_path):
    archive, output = malicious(tmp_path, [tarfile.TarInfo("a"), tarfile.TarInfo("./a")])
    with pytest.raises(InfraError, match="duplicate"):
        artifacts.extract(archive, output)


def test_expansion_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "MAX_BYTES", 2)
    member = tarfile.TarInfo("large")
    member.size = 3
    archive, output = malicious(tmp_path, [member])
    with pytest.raises(InfraError, match="limits"):
        artifacts.extract(archive, output)
    assert not (output / "large").exists()


def test_entry_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "MAX_FILES", 1)
    archive, output = malicious(tmp_path, [tarfile.TarInfo("one"), tarfile.TarInfo("two")])
    with pytest.raises(InfraError, match="limits"):
        artifacts.extract(archive, output)


def test_deterministic_archive_excludes_local_secrets_and_preserves_exec(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    app = source / "run"
    app.write_text("#!/bin/sh\nexit 0\n")
    app.chmod(0o755)
    (source / ".env.local").write_text("should never be included")
    (source / ".git").mkdir()
    (source / ".git/config").write_text("local")
    first, second = tmp_path / "one.tar.gz", tmp_path / "two.tar.gz"
    digest = artifacts.pack(source, first)
    os.utime(app, (10000, 10000))
    assert artifacts.pack(source, second) == digest
    destination = tmp_path / "unpacked"
    destination.mkdir()
    artifacts.extract(second, destination)
    assert [p.name for p in destination.iterdir()] == ["run"]
    assert (destination / "run").stat().st_mode & 0o111


def test_pack_refuses_symlink_and_output_inside_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(InfraError, match="outside"):
        artifacts.pack(source, source / "archive.tar.gz")
    (source / "link").symlink_to("/etc/passwd")
    with pytest.raises(InfraError, match="Links"):
        artifacts.pack(source, tmp_path / "archive.tar.gz")


def test_empty_archive_rejected(tmp_path):
    archive, output = malicious(tmp_path, [])
    with pytest.raises(InfraError, match="empty"):
        artifacts.extract(archive, output)


def test_nested_release_directories_ignore_operator_umask(tmp_path):
    member = tarfile.TarInfo("nested/deep/app.py")
    member.size = 1
    archive, output = malicious(tmp_path, [member])
    previous = os.umask(0o077)
    try:
        artifacts.extract(archive, output)
    finally:
        os.umask(previous)
    assert (output / "nested").stat().st_mode & 0o777 == 0o755
    assert (output / "nested/deep").stat().st_mode & 0o777 == 0o755
    assert (output / "nested/deep/app.py").stat().st_mode & 0o777 == 0o644
