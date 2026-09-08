"""Deterministic archives and bounded extraction without links or special files."""

import gzip
import hashlib
import os
import tarfile
from pathlib import Path, PurePosixPath

from homeinfra.config import InfraError

MAX_BYTES = 2 * 1024**3
MAX_FILES = 100_000
RESERVED = {".homeinfra-manifest.json", ".homeinfra-digest"}
EXCLUDED = {".git", ".env", ".venv", "__pycache__", ".DS_Store"}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pack(source: Path, output: Path) -> str:
    source = source.resolve(strict=True)
    if output.resolve().is_relative_to(source):
        raise InfraError("Archive output must be outside its source directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        output.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz,
    ):
        with tarfile.open(fileobj=gz, mode="w") as archive:
            for path in sorted(source.rglob("*")):
                relative = path.relative_to(source)
                if any(part in EXCLUDED or part.startswith(".env.") for part in relative.parts):
                    continue
                if path.is_symlink() or not (path.is_file() or path.is_dir()):
                    raise InfraError(f"Links and special files cannot be packaged: {relative}")
                if any(part in RESERVED for part in relative.parts):
                    raise InfraError("Archive contains reserved deployment metadata")
                if path.is_dir():
                    continue
                info = archive.gettarinfo(str(path), str(relative))
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ""
                info.mode = 0o755 if os.access(path, os.X_OK) else 0o644
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
    return digest(output)


def extract(archive: Path, destination: Path):
    """Destination must be a newly created private staging directory."""
    total = count = 0
    seen = set()
    try:
        with tarfile.open(archive, "r:gz") as source:
            for member in source:
                count += 1
                total += member.size
                if count > MAX_FILES or total > MAX_BYTES or member.size < 0:
                    raise InfraError("Archive exceeds extraction limits")
                relative = PurePosixPath(member.name)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not relative.parts
                    or "\\" in member.name
                    or any(p in RESERVED for p in relative.parts)
                ):
                    raise InfraError("Unsafe archive path")
                if not (member.isfile() or member.isdir()):
                    raise InfraError("Archive contains a link or special file")
                if relative in seen:
                    raise InfraError("Archive contains duplicate paths")
                seen.add(relative)
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o755)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                stream = source.extractfile(member)
                if stream is None:
                    raise InfraError("Archive member cannot be read")
                with stream, target.open("xb") as out:
                    while block := stream.read(1024 * 1024):
                        out.write(block)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    except (tarfile.TarError, OSError) as exc:
        raise InfraError("Invalid artifact archive") from exc
    if not count:
        raise InfraError("Artifact is empty")
    # mkdir's mode is filtered by the invoking administrator's umask. Releases
    # must remain traversable by the separate unprivileged runtime account.
    for path in destination.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)
