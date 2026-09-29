# -*- coding: utf-8 -*-
"""Unit tests for access backends: registries and status detection."""
import pytest

from nisar_qgis.nisar_core.access import (
    AccessRegistry, LocalFileBackend, DownloadProgress,
)
from nisar_qgis.nisar_core.access.base import BaseAccessBackend
from nisar_qgis.nisar_core.models import SearchParameters, DataStatus


def test_registry_contains_all_backends():
    """TZ P0.5 — B1, B2, B3 all registered with availability info."""
    ids = {item["id"] for item in AccessRegistry.list_registered()}
    assert {"B1_local", "B2_asf_search", "B3_earthaccess"}.issubset(ids)
    for item in AccessRegistry.list_registered():
        assert isinstance(item["available"], bool)
        if not item["available"]:
            assert item["reason"]  # pip hint etc.


def test_b1_always_available():
    ok, reason = LocalFileBackend.check_availability()
    assert ok and reason == ""


def test_b1_search_returns_empty():
    backend = LocalFileBackend({})
    assert backend.search(SearchParameters()) == []


def test_optional_dependencies_reported_with_hint():
    """asf_search/earthaccess unavailable -> reason mentions pip install."""
    listed = {item["id"]: item for item in AccessRegistry.list_registered()}
    for backend_id, package in (("B2_asf_search", "asf_search"),
                                ("B3_earthaccess", "earthaccess")):
        item = listed.get(backend_id)
        if item and not item["available"]:
            assert "pip install" in item["reason"]


def test_status_from_collection():
    from nisar_qgis.nisar_core.access.b2_asf_search import \
        _status_from_collection
    assert _status_from_collection(
        "NISAR_L2_GCOV_PROVISIONAL_V1", "") is DataStatus.PROVISIONAL
    assert _status_from_collection(
        "NISAR_L2_GCOV_BETA", "") is DataStatus.BETA
    assert _status_from_collection(
        "", "https://x/NISAR_L2_GCOV_PROVISIONAL_V1/f.h5") is DataStatus.PROVISIONAL
    assert _status_from_collection("whatever", "https://x") is DataStatus.UNKNOWN


def test_select_backend_auto_prefers_online():
    from nisar_qgis.nisar_core.access.b2_asf_search import B2ASFSearchBackend
    from nisar_qgis.nisar_core.access.b3_earthaccess import B3EarthAccessBackend
    if B2ASFSearchBackend is not None and \
            B2ASFSearchBackend.check_availability()[0]:
        assert AccessRegistry.select_backend("auto") is B2ASFSearchBackend
    elif B3EarthAccessBackend is not None and \
            B3EarthAccessBackend.check_availability()[0]:
        assert AccessRegistry.select_backend("auto") is B3EarthAccessBackend
    else:
        assert AccessRegistry.select_backend("auto") is LocalFileBackend


def test_download_progress_dataclass():
    prog = DownloadProgress(scene_id="s", bytes_downloaded=1,
                            total_bytes=2, status="downloading")
    assert prog.error_message == "" and prog.file_path == ""


def test_config_object_accepted():
    """Backends accept dataclass-like configs, not only dicts."""
    class FakeConfig:
        def __init__(self):
            self.download_dir = "/tmp/nisar-test"
            self.tile_size = 256

    backend = LocalFileBackend(FakeConfig())
    assert backend.config["download_dir"] == "/tmp/nisar-test"
    assert backend.config["tile_size"] == 256
