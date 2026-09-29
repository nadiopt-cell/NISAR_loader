# -*- coding: utf-8 -*-
"""Unit tests for the preview-before-download feature (P2.5).

Covers the pure helpers in nisar_core/access/preview.py and the B2
backend's extraction of the official ASF ``browse`` property (verified
live on 2026-09-29 — see docs/product_notes.md).
"""
from datetime import datetime

from nisar_qgis.nisar_core.access.preview import (
    pick_browse_urls, bbox_from_wkt, human_size, scene_summary_pairs,
)
from nisar_qgis.nisar_core.models import (
    SceneRecord, ProductType, ProductLevel, Instrument, DataStatus,
    Polarization,
)

# Real browse set of NISAR_L2_UR_GCOV_031_151_A_012_4005_DHDH_... (probe,
# 2026-09-29). Host shortened for readability; suffixes are the contract.
_BASE = ("https://nisar.asf.earthdatacloud.nasa.gov/BROWSE/UR_L2_L_GCOV/"
         "G/G")
REAL_BROWSE = [
    _BASE + "_LATLON.png",
    _BASE + "_LATLON_thumbnail.png",
    _BASE + "_NATIVE.png",
    _BASE + "_NATIVE_A_HHHH.png",
    _BASE + "_NATIVE_A_HVHV.png",
    _BASE + "_NATIVE_B_HHHH.png",
    _BASE + "_NATIVE_B_HVHV.png",
]


# ------------------------------------------------------------ pick_browse_urls
def test_pick_browse_urls_full_set():
    out = pick_browse_urls(REAL_BROWSE)
    assert out["thumbnail"] == _BASE + "_LATLON_thumbnail.png"
    assert out["full"] == _BASE + "_LATLON.png"
    assert out["native"] == _BASE + "_NATIVE.png"
    labels = {e["label"] for e in out["native_pol"]}
    assert labels == {"A HHHH", "A HVHV", "B HHHH", "B HVHV"}
    for entry in out["native_pol"]:
        assert entry["band"] in ("A", "B")
        assert entry["pol"] in ("HHHH", "HVHV")
        assert entry["url"].endswith(
            "_NATIVE_%s_%s.png" % (entry["band"], entry["pol"]))
    assert out["all"] == REAL_BROWSE


def test_pick_browse_urls_empty_or_none():
    for empty in ([], None):
        out = pick_browse_urls(empty)
        assert out["thumbnail"] is None
        assert out["full"] is None
        assert out["native"] is None
        assert out["native_pol"] == []
        assert out["all"] == []


def test_pick_browse_urls_without_thumbnail():
    out = pick_browse_urls([_BASE + "_LATLON.png"])
    assert out["thumbnail"] is None
    assert out["full"] == _BASE + "_LATLON.png"


def test_pick_browse_urls_filters_non_png():
    out = pick_browse_urls([
        _BASE + "_LATLON.kml",
        "https://x/README.txt",
        _BASE + "_LATLON_thumbnail.png",
    ])
    assert out["all"] == [_BASE + "_LATLON_thumbnail.png"]
    assert out["thumbnail"] == _BASE + "_LATLON_thumbnail.png"


# ---------------------------------------------------------------- human_size
def test_human_size():
    assert human_size(0) == "—"
    assert human_size(None) == "—"
    assert human_size(-5) == "—"
    assert human_size(9410) == "9.2 KB"
    assert human_size(251658240) == "240.0 MB"
    assert human_size(4768923648) == "4.44 GB"


# -------------------------------------------------------------- bbox_from_wkt
def test_bbox_from_wkt_valid():
    wkt = ("POLYGON((-154.63 20.02, -155.17 22.04, -156.0 21.5,"
           " -155.2 19.9, -154.63 20.02))")
    assert bbox_from_wkt(wkt) == (-156.0, 19.9, -154.63, 22.04)


def test_bbox_from_wkt_invalid():
    assert bbox_from_wkt("") is None
    assert bbox_from_wkt(None) is None
    assert bbox_from_wkt("POINT(1 2)") is None
    assert bbox_from_wkt("POLYGON((bad wkt))") is None


# -------------------------------------------------------- scene_summary_pairs
def _scene(**overrides):
    defaults = dict(
        scene_id="SCENE_001",
        product_type=ProductType.GCOV,
        level=ProductLevel.L2,
        instrument=Instrument.LSAR,
        status=DataStatus.PROVISIONAL,
        acquisition_time=datetime(2026, 9, 28, 15, 50, 56),
        footprint_wkt="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        size_bytes=251658240,
        urls={"download": "https://x/SCENE_001.h5"},
        polarizations=[Polarization.HH, Polarization.HV],
        mode="full",
        orbit_number=6132,
        orbit_direction="ASCENDING",
        frame_id=12,
        metadata={"collectionName": "NISAR_UR_L2", "crid": "P05023",
                  "pathNumber": 151},
    )
    defaults.update(overrides)
    return SceneRecord(**defaults)


def test_scene_summary_pairs_full():
    pairs = dict(scene_summary_pairs(_scene()))
    assert pairs["ui.preview.detail_scene"] == "SCENE_001"
    assert pairs["ui.preview.detail_product"] == "GCOV L2 (LSAR)"
    assert pairs["ui.preview.detail_acquired"] == "2026-09-28 15:50:56"
    assert pairs["ui.preview.detail_status"] == "PROVISIONAL"
    assert pairs["ui.preview.detail_size"] == "240.0 MB"
    assert pairs["ui.preview.detail_pols"] == "HH+HV"
    assert pairs["ui.preview.detail_orbit"] == "#6132 ASCENDING"
    assert pairs["ui.preview.detail_frame"] == "12 / path 151"
    assert pairs["ui.preview.detail_collection"] == "NISAR_UR_L2 (CRID P05023)"
    assert pairs["ui.preview.detail_bbox"] == "0.0000, 0.0000, 1.0000, 1.0000"


def test_scene_summary_pairs_sparse():
    pairs = dict(scene_summary_pairs(_scene(
        acquisition_time=None, size_bytes=0, polarizations=[],
        orbit_number=None, orbit_direction=None, frame_id=None,
        footprint_wkt="", metadata={},
    )))
    assert pairs["ui.preview.detail_acquired"] == "—"
    assert pairs["ui.preview.detail_size"] == "—"
    assert pairs["ui.preview.detail_pols"] == "—"
    assert pairs["ui.preview.detail_orbit"] == "—"
    assert pairs["ui.preview.detail_frame"] == "—"
    assert pairs["ui.preview.detail_collection"] == "—"
    assert pairs["ui.preview.detail_bbox"] == "—"


def test_scene_summary_pairs_dedupes_polarizations():
    """ASF repeats main-band pols in sideBandPolarization (HH+HV+HH+HV)."""
    pairs = dict(scene_summary_pairs(_scene(polarizations=[
        Polarization.HH, Polarization.HV,
        Polarization.HH, Polarization.HV,
    ])))
    assert pairs["ui.preview.detail_pols"] == "HH+HV"


# --------------------------------------------- B2: browse property extraction
class _FakeASFProduct:
    """Minimal stand-in for asf_search.ASFProduct (no network)."""

    def __init__(self, properties, geometry=None):
        self.properties = properties
        self._geometry = geometry

    def geojson(self):
        return {"type": "Feature", "properties": {}, "geometry": self._geometry}


def _props(browse=None, additional=None):
    scene = "NISAR_L2_UR_GCOV_031_151_A_012_4005_DHDH"
    return {
        "sceneName": scene,
        "fileID": scene,
        "startTime": "2026-09-28T15:50:56Z",
        "stopTime": "2026-09-28T15:51:29Z",
        "url": "https://x/%s.h5" % scene,
        "browse": browse or [],
        "additionalUrls": additional or [],
        "s3Urls": [],
        "bytes": {"%s.h5" % scene: {"bytes": 4768923648, "format": "HDF5"}},
        "collectionName": "NISAR_UR_L2",
        "conceptID": "C2887502657-ASF",
        "crid": "P05023",
        "pgeVersion": "R05.02.3",
        "pathNumber": 151,
        "frameNumber": 12,
        "orbit": 6132,
        "flightDirection": "ASCENDING",
        "mainBandPolarization": ["HH", "HV"],
        "sideBandPolarization": ["HH", "HV"],
        "processingLevel": "GCOV",
        "processingDate": "2026-09-29T01:33:56Z",
        "rangeBandwidth": None,
    }


_GEOMETRY = {"type": "Polygon", "coordinates": [[
    (-154.63037, 20.02359), (-155.1707, 22.04285),
    (-156.0, 21.5), (-155.2, 19.9), (-154.63037, 20.02359),
]]}


def _record(properties):
    from nisar_qgis.nisar_core.access.b2_asf_search import B2ASFSearchBackend
    item = _FakeASFProduct(properties, geometry=_GEOMETRY)
    return B2ASFSearchBackend({})._item_to_scene_record(
        item, ProductType.GCOV)


def test_b2_extracts_official_browse_property():
    """The browse PNGs live in props['browse'], not additionalUrls."""
    record = _record(_props(browse=REAL_BROWSE))
    assert record is not None
    assert record.urls["browse_thumbnail"] == _BASE + "_LATLON_thumbnail.png"
    assert record.urls["browse"] == _BASE + "_LATLON_thumbnail.png"
    assert record.urls["browse_full"] == _BASE + "_LATLON.png"
    assert record.urls["browse_native"] == _BASE + "_NATIVE.png"
    assert record.metadata["browse_urls"] == REAL_BROWSE
    assert len(record.metadata["browse_native_pol"]) == 4
    assert record.size_bytes == 4768923648
    assert record.footprint_wkt.startswith("POLYGON")


def test_b2_browse_fallback_in_additional_urls():
    """Old ASF shapes: a PNG quicklook inside additionalUrls still works."""
    png = "https://x/G_LATLON.png"
    record = _record(_props(browse=[], additional=[
        "https://x/G.h5.iso.xml", png]))
    assert record is not None
    assert record.urls.get("browse") == png
    assert "browse_thumbnail" not in record.urls


def test_b2_no_browse_at_all():
    record = _record(_props(browse=[], additional=["https://x/G.h5.iso.xml"]))
    assert record is not None
    assert "browse" not in record.urls
    assert record.metadata["browse_urls"] == []
