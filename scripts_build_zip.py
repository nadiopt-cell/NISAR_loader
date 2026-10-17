# -*- coding: utf-8 -*-
"""Build the QGIS plugin ZIP with the version from metadata.txt in the name.

WP-12: metadata.txt ``version=`` is the single source of truth; this script
derives ``nisar_qgis_plugin_v<version>.zip`` from it and validates that
``nisar_qgis/__init__.py`` matches (single-source agreement).

Usage:  python scripts_build_zip.py
"""
import re
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
PLUGIN_DIR = REPO_ROOT / "nisar_qgis"
EXCLUDE_SUFFIXES = (".pyc", ".aux.xml")
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache"}


def read_version() -> str:
    """Plugin version from metadata.txt (single source of truth)."""
    meta = PLUGIN_DIR / "metadata.txt"
    for line in meta.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("version="):
            return line.split("=", 1)[1]
    raise RuntimeError("version= not found in nisar_qgis/metadata.txt")


def read_init_version() -> str:
    """__version__ from nisar_qgis/__init__.py (must agree with metadata)."""
    init = PLUGIN_DIR / "__init__.py"
    match = re.search(r'__version__\s*=\s*"([^"]+)"',
                      init.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError("__version__ not found in nisar_qgis/__init__.py")
    return match.group(1)


def build_zip(version: str, output_dir: Path = REPO_ROOT) -> Path:
    zip_path = output_dir / ("nisar_qgis_plugin_v%s.zip" % version)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(PLUGIN_DIR.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(PLUGIN_DIR.parent)
            parts = set(rel.parts)
            if parts & EXCLUDE_DIRS:
                continue
            if path.suffix in EXCLUDE_SUFFIXES:
                continue
            zf.write(path, str(rel))
    return zip_path


def main() -> int:
    version = read_version()
    init_version = read_init_version()
    if version != init_version:
        print("ERROR: version mismatch: metadata.txt=%s, __init__.py=%s"
              % (version, init_version), file=sys.stderr)
        return 1
    zip_path = build_zip(version)
    print("Built %s" % zip_path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
