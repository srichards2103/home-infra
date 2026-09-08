"""Build a portable standard-library zipapp, without packaging development dependencies."""

import shutil
import tempfile
import zipapp
from pathlib import Path

root = Path(__file__).resolve().parents[1]
(root / "dist").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as temporary:
    stage = Path(temporary)
    shutil.copytree(
        root / "src/homeinfra", stage / "homeinfra", ignore=shutil.ignore_patterns("__pycache__")
    )
    zipapp.create_archive(
        stage, root / "dist/homeinfra.pyz", main="homeinfra.cli:main", compressed=True
    )
print("Built dist/homeinfra.pyz")
