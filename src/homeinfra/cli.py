import argparse
import json
import os
import platform
import pwd
import sys
from pathlib import Path

from homeinfra import artifacts, backup
from homeinfra.config import InfraError, Service, name
from homeinfra.deploy import Deployer, Layout, verify_runtime_identity
from homeinfra.runtime import environment, render


def parser():
    result = argparse.ArgumentParser(description="Provisioned macOS service operations")
    sub = result.add_subparsers(dest="action", required=True)
    validate = sub.add_parser(
        "validate", help="Validate a service manifest without changing the host"
    )
    validate.add_argument("manifest", type=Path)
    preview = sub.add_parser("render", help="Print a launchd plist without installing it")
    preview.add_argument("manifest", type=Path)
    preview.add_argument("--version", default="preview")
    package = sub.add_parser(
        "package", help="Package an explicit staging directory; prints SHA-256"
    )
    package.add_argument("source", type=Path)
    package.add_argument("output", type=Path)
    deploy = sub.add_parser("deploy", help="Install a release, health check, roll back on failure")
    deploy.add_argument("manifest", type=Path)
    deploy.add_argument("archive", type=Path)
    deploy.add_argument("--version", required=True)
    deploy.add_argument("--sha256", required=True)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("name", type=name)
    rollback.add_argument("--version")
    for command in ("status", "recover", "rotate"):
        sub.add_parser(command).add_argument("name", type=name)
    run = sub.add_parser("run", help="Internal unprivileged launchd entry point")
    run.add_argument("release", type=Path)
    backups = sub.add_parser("backup")
    backups.add_argument(
        "operation", choices=["init", "run", "check", "snapshots", "restore", "retention-plan"]
    )
    backups.add_argument("config", type=Path)
    backups.add_argument("--destination", type=Path)
    backups.add_argument("--snapshot", default="latest")
    return result


def require_host():
    if platform.system() != "Darwin" or os.geteuid() != 0:
        raise InfraError(
            "Host operations require macOS and sudo; validate/render/package work anywhere"
        )


def main():
    args = parser().parse_args()
    prefix = "/opt/homebrew" if platform.machine() == "arm64" else "/usr/local"
    layout = Layout(python=f"{prefix}/opt/python@3.13/bin/python3.13")
    try:
        if args.action == "validate":
            Service.load(args.manifest)
            print("Manifest valid")
        elif args.action == "package":
            print(artifacts.pack(args.source, args.output))
        elif args.action == "render":
            service = Service.load(args.manifest)
            sys.stdout.buffer.write(
                render(
                    service,
                    layout.release(service.name, args.version),
                    layout.data(service.name),
                    layout.log_root / service.name,
                    layout.root / "bin/homeinfra.pyz",
                    layout.python,
                )
            )
        elif args.action == "run":
            release = args.release.resolve(strict=True)
            service = Service.load(release / ".homeinfra-manifest.json")
            if release != layout.release(service.name, release.name):
                raise InfraError("Service runtime must use a managed release directory")
            if pwd.getpwuid(os.geteuid()).pw_name != service.user:
                raise InfraError("Runtime must execute as the manifest's service user")
            data = layout.data(service.name)
            env = environment(service, release, data, release.name)
            argv = [service.expand(arg, release, data, release.name) for arg in service.command]
            os.chdir(data)
            os.umask(0o077)
            os.execve(argv[0], argv, env)  # noqa: S606
        else:
            require_host()
            if args.action == "backup":
                backup.execute(args.config, args.operation, args.destination, args.snapshot)
                return
            deployer = Deployer(layout)
            if args.action == "deploy":
                service = Service.load(args.manifest)
                verify_runtime_identity(layout, service)
                result = deployer.deploy(service, args.archive, args.version, args.sha256)
            elif args.action == "rollback":
                result = deployer.rollback(args.name, args.version)
            elif args.action == "recover":
                result = deployer.recover(args.name)
            elif args.action == "rotate":
                result = deployer.rotate(args.name)
            else:
                result = deployer.status(args.name)
            print(json.dumps(result, indent=2))
            if args.action == "status" and (not result["healthy"] or result["recovery_required"]):
                raise SystemExit(1)
    except Exception as exc:
        # Subprocess output and secret JSON contents must not leak through exceptions.
        message = (
            str(exc)
            if isinstance(exc, InfraError)
            else f"Operation failed ({type(exc).__name__}); inspect local logs"
        )
        print(message, file=sys.stderr)
        raise SystemExit(1) from None
