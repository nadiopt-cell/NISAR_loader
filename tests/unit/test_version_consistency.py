# -*- coding: utf-8 -*-
"""WP-12: version consistency (metadata.txt <-> __init__.py <-> build script)."""
import importlib.util
import re
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
METADATA = REPO_ROOT / "nisar_qgis" / "metadata.txt"
INIT = REPO_ROOT / "nisar_qgis" / "__init__.py"


def _metadata_version() -> str:
    for line in METADATA.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("version="):
            return line.split("=", 1)[1].strip()
    raise AssertionError("version= missing in metadata.txt")


def _init_version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"',
                      INIT.read_text(encoding="utf-8"))
    assert match, "__version__ missing in __init__.py"
    return match.group(1)


def _load_build_script():
    spec = importlib.util.spec_from_file_location(
        "scripts_build_zip", REPO_ROOT / "scripts_build_zip.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_metadata_and_init_versions_agree():
    assert _metadata_version() == _init_version()


def test_version_shape():
    version = _metadata_version()
    parts = version.split(".")
    assert len(parts) == 3, "expected MAJOR.MINOR.PATCH, got %r" % version
    for part in parts:
        assert part.isdigit()


def test_metadata_has_required_fields():
    text = METADATA.read_text(encoding="utf-8")
    for field in ("name=", "description=", "about=", "version=",
                  "qgisMinimumVersion=", "author=", "repository=",
                  "homepage=", "tracker=", "icon="):
        assert field in text, "metadata.txt misses %r" % field


def test_build_zip_uses_metadata_version_and_name(tmp_path):
    module = _load_build_script()
    version = _metadata_version()
    assert module.read_version() == version

    zip_path = module.build_zip(version, tmp_path)
    assert zip_path.exists()
    assert zip_path.name == "nisar_qgis_plugin_v%s.zip" % version
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert any(n == "nisar_qgis/metadata.txt" for n in names), names
    assert not any("__pycache__" in n for n in names)
    assert not any(n.endswith(".pyc") for n in names)
