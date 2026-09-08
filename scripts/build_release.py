"""Build controller/example artifacts and a checksum file for CI downloads."""

import runpy
from pathlib import Path

from homeinfra.artifacts import digest, pack

root = Path(__file__).resolve().parents[1]
runpy.run_path(str(root / "scripts/build_cli.py"), run_name="__main__")
pack(root / "examples/hello", root / "dist/hello.tar.gz")
outputs = [root / "dist/homeinfra.pyz", root / "dist/hello.tar.gz"]
(root / "dist/SHA256SUMS").write_text("".join(f"{digest(p)}  {p.name}\n" for p in outputs))
print("Built dist/hello.tar.gz and dist/SHA256SUMS")
