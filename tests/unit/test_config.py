# -*- coding: utf-8 -*-
"""Unit tests for configuration: no passwords, sane defaults (TZ P0.6)."""
import dataclasses

from nisar_qgis.nisar_core.config import (
    PluginConfig, ReaderBackend, AccessBackend, ProcessingBackend, ensure_dirs,
)


def test_no_password_field():
    """TZ P0.6 — the config must not contain any password field."""
    field_names = {f.name for f in dataclasses.fields(PluginConfig)}
    assert "edl_password" not in field_names
    assert "password" not in field_names
    assert "edl_token" not in field_names
    cfg = PluginConfig()
    assert not hasattr(cfg, "edl_password")


def test_no_qgis_import_in_core_config():
    """TZ principle 8 — nisar_core.config imports nothing from qgis."""
    import sys
    assert "qgis" not in sys.modules


def test_defaults():
    cfg = PluginConfig()
    assert cfg.reader_backend == ReaderBackend.AUTO
    assert cfg.access_backend == AccessBackend.AUTO
    assert cfg.processing_backend == ProcessingBackend.AUTO
    assert cfg.language == "en"           # default per requirements
    assert cfg.show_beta_warnings is True
    assert cfg.tile_size == 512
    assert cfg.enable_pam is False         # no .aux.xml next to sources


def test_ensure_dirs_writable(tmp_path):
    cfg = PluginConfig(
        cache_dir=tmp_path / "cache",
        download_dir=tmp_path / "dl",
        temp_dir=tmp_path / "tmp")
    ensure_dirs(cfg)
    assert cfg.cache_dir.exists() and cfg.download_dir.exists()
    assert cfg.temp_dir.exists()


def test_enum_roundtrip():
    for value in ("auto", "A1_native", "A2_netcdf_workaround", "A3_h5py"):
        assert ReaderBackend(value).value == value
    for value in ("auto", "B1_local", "B2_asf_search", "B3_earthaccess"):
        assert AccessBackend(value).value == value
