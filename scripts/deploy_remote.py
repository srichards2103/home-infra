"""Operator-driven SSH delivery; no permanent root credentials or remote build."""

import argparse
import re
import shlex
import subprocess
from pathlib import Path


def remote_argv(host, args, *, tty=False):
    return ["ssh", *(["-t"] if tty else []), "--", host, shlex.join(args)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="SSH config alias or user@host")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*", args.host):
        parser.error("Use a plain SSH hostname, config alias or user@host")
    for file in (args.manifest, args.artifact):
        if not file.is_file():
            parser.error(f"Missing input: {file}")
    from homeinfra.artifacts import digest
    from homeinfra.config import Service, version

    Service.load(args.manifest)
    version(args.version)
    if digest(args.artifact) != args.sha256:
        parser.error("Local artifact SHA-256 does not match the expected digest")
    result = subprocess.run(  # noqa: S603
        remote_argv(args.host, ["mktemp", "-d", "/private/tmp/homeinfra-deploy.XXXXXXXX"]),
        capture_output=True,
        text=True,
        check=True,
    )
    directory = result.stdout.strip()
    if not re.fullmatch(r"/private/tmp/homeinfra-deploy\.[A-Za-z0-9]+", directory):
        parser.error("Unexpected remote temporary directory; refusing upload")
    try:
        for source, filename in (
            (args.manifest, "service.json"),
            (args.artifact, "artifact.tar.gz"),
        ):
            subprocess.run(  # noqa: S603 - validated host and private remote directory
                ["scp", "--", str(source.resolve()), f"{args.host}:{directory}/{filename}"],  # noqa: S607
                check=True,
            )
        subprocess.run(  # noqa: S603 - argv quoted once for the remote SSH shell
            remote_argv(
                args.host,
                [  # noqa: S603
                    "sudo",
                    "/opt/home-infra/bin/homeinfra",
                    "deploy",
                    f"{directory}/service.json",
                    f"{directory}/artifact.tar.gz",
                    "--version",
                    args.version,
                    "--sha256",
                    args.sha256,
                ],
                tty=True,
            ),
            check=True,
        )
    finally:
        # Delete only the exact validated directory created for this invocation.
        subprocess.run(remote_argv(args.host, ["rm", "-rf", "--", directory]), check=False)  # noqa: S603


if __name__ == "__main__":
    main()
