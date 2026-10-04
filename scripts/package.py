"""Build the installable integration package.

Produces ``build/ngbs_icon/`` (a ready-to-copy integration directory) and
``dist/ngbs_icon.zip`` (the same content at the zip root, as HACS ``zip_release``
and manual installation expect). The pyngbsicon library is vendored into
``_vendor/pyngbsicon`` so the package also works on Home Assistant instances that
cannot install it from PyPI; the integration prefers an installed pyngbsicon and
falls back to the vendored copy.

    python3 scripts/package.py [--no-vendor]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from devenv import REPO_ROOT

SOURCE = REPO_ROOT / "custom_components" / "ngbs_icon"
LIBRARY = REPO_ROOT / "lib" / "pyngbsicon" / "src" / "pyngbsicon"
STAGING = REPO_ROOT / "build" / "ngbs_icon"
ZIP_PATH = REPO_ROOT / "dist" / "ngbs_icon.zip"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".mypy_cache")


def build(vendor: bool = True) -> Path:
    """Assemble the staging directory and the zip; return the staging directory."""
    if not SOURCE.is_dir():
        raise SystemExit(f"{SOURCE} does not exist")
    if STAGING.exists():
        shutil.rmtree(STAGING)
    shutil.copytree(SOURCE, STAGING, ignore=IGNORE)
    shutil.rmtree(STAGING / "_vendor", ignore_errors=True)
    if vendor:
        target = STAGING / "_vendor" / "pyngbsicon"
        shutil.copytree(LIBRARY, target, ignore=IGNORE)
        shutil.copy2(REPO_ROOT / "LICENSE", target / "LICENSE")
        (STAGING / "_vendor" / "__init__.py").write_text(
            '"""Vendored copy of the pyngbsicon library (used when it is not installed)."""\n',
            encoding="utf-8",
        )

    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(STAGING.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(STAGING).as_posix())
    return STAGING


def main() -> int:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-vendor", action="store_true", help="do not bundle pyngbsicon"
    )
    args = parser.parse_args()
    staging = build(vendor=not args.no_vendor)
    files = sum(1 for path in staging.rglob("*") if path.is_file())
    print(
        f"{staging.relative_to(REPO_ROOT)}/ ({files} files) -> {ZIP_PATH.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
