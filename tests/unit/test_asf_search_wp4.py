# -*- coding: utf-8 -*-
"""WP-4 (finding F8): ASF search without silent failures.

Acceptance criteria from the review: mocked asf_search — exception ->
SearchError (not an empty list); exactly-the-limit results -> truncation
warning; a scene acquired on the last day of the range is found (end
date inclusive to 23:59:59 UTC); MultiPolygon footprints are parsed.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import nisar_qgis.nisar_core.access.b2_asf_search as b2
from nisar_qgis.nisar_core.access.preview import bbox_from_wkt
from nisar_qgis.nisar_core.models import SearchParameters, ProductType


class _FakeASF:
    """Stand-in for the asf_search module (monkeypatched into b2)."""

    def __init__(self):
        self.searches = []          # recorded option dicts
        self.queue = []             # per-call: result list or an Exception

    # session/options mirrors of the real module surface
    def ASFSession(self):
        return object()

    def ASFSearchOptions(self, **opts):
        return SimpleNamespace(session=None, opts=opts)

    def search(self, **kwargs):
        obj = kwargs.get("opts")
        self.searches.append(dict(obj.opts) if obj is not None
                             else dict(kwargs))
        what = self.queue.pop(0) if self.queue else []
        if isinstance(what, Exception):
            raise what
        return list(what)


@pytest.fixture()
def fake_asf(monkeypatch):
    fake = _FakeASF()
    monkeypatch.setattr(b2, "asf", fake)
    monkeypatch.setattr(b2, "ASF_SEARCH_AVAILABLE", True)
    return fake


def fake_item(name="A", acq="2026-06-22T12:30:00Z", multipoly=False):
    props = {
        "sceneName": name,
        "mainBandPolarization": ["HH", "HV"],
        "collectionName": "NISAR_L2_GCOV_PROVISIONAL_V1",
        "url": "https://example.org/%s.h5" % name,
        "bytes": {},
    }
    if acq:
        props["startTime"] = acq

    def geojson():
        if multipoly:
            return {"geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]],
                    [[[2.0, 0.0], [3.0, 0.0], [3.0, 1.0], [2.0, 0.0]]],
                ],
            }}
        return {"geometry": {
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]],
        }}

    return SimpleNamespace(properties=props, geojson=geojson)


# -------------------------------------------------------- exception policy
def test_exception_becomes_searcherror_not_empty_list(fake_asf):
    fake_asf.queue = [Exception("API 500: cmr down")]
    backend = b2.B2ASFSearchBackend({})
    with pytest.raises(b2.SearchError) as err:
        backend.search(SearchParameters(max_results=5))
    assert "API 500" in str(err.value)


def test_partial_per_type_errors_collected_and_shown(fake_asf):
    fake_asf.queue = [Exception("API 500"), [fake_item("g1"), fake_item("g2")]]
    backend = b2.B2ASFSearchBackend({})
    params = SearchParameters(
        max_results=10,
        product_types=[ProductType.GCOV, ProductType.GUNW])
    scenes = backend.search(params)
    assert len(scenes) == 2                       # the GUNW half survived
    assert any("API 500" in w for w in backend.search_warnings)


# -------------------------------------------------------------- pagination
def test_exact_limit_warns_truncated(fake_asf):
    fake_asf.queue = [[fake_item("a"), fake_item("b"), fake_item("c")]]
    backend = b2.B2ASFSearchBackend({})
    scenes = backend.search(SearchParameters(max_results=3))
    assert len(scenes) == 3
    assert any("truncated at the configured limit" in w
               for w in backend.search_warnings)
    assert fake_asf.searches[0]["maxResults"] == 3


def test_under_limit_no_warning(fake_asf):
    fake_asf.queue = [[fake_item("a")]]
    backend = b2.B2ASFSearchBackend({})
    backend.search(SearchParameters(max_results=3))
    assert backend.search_warnings == []


# ------------------------------------------------------------ time window
def test_end_date_inclusive_last_day(fake_asf):
    fake_asf.queue = [[fake_item("a")]]
    backend = b2.B2ASFSearchBackend({})
    params = SearchParameters(max_results=3)
    params.start_date = datetime(2026, 6, 10)
    params.end_date = datetime(2026, 6, 22)      # the storm day
    backend.search(params)
    opts = fake_asf.searches[0]
    assert opts["start"] == "2026-06-10T00:00:00Z"
    assert opts["end"] == "2026-06-22T23:59:59Z"


def test_time_bounds_are_tz_aware_utc():
    params = SearchParameters(max_results=3)
    params.start_date = datetime(2026, 6, 10)
    params.end_date = datetime(2026, 6, 22)
    start, end = b2.asf_time_bounds(params)
    assert start.utcoffset() == timedelta(0)
    assert end.utcoffset() == timedelta(0)
    assert start.tzinfo is not None and end.tzinfo is not None


# ----------------------------------------------------- acquisition time
def test_missing_acquisition_time_is_none_with_warning(fake_asf):
    fake_asf.queue = [[fake_item("no_time", acq=None), fake_item("ok")]]
    backend = b2.B2ASFSearchBackend({})
    scenes = backend.search(SearchParameters(max_results=5))
    by_id = {s.scene_id: s for s in scenes}
    assert by_id["no_time"].acquisition_time is None
    assert by_id["ok"].acquisition_time is not None
    assert by_id["ok"].acquisition_time.tzinfo is not None
    assert any("no acquisition time" in w for w in backend.search_warnings)


# --------------------------------------------------------------- footprint
def test_multipolygon_footprint_parsed_over_all_parts(fake_asf):
    fake_asf.queue = [[fake_item("split", multipoly=True)]]
    backend = b2.B2ASFSearchBackend({})
    scenes = backend.search(SearchParameters(max_results=5))
    wkt = scenes[0].footprint_wkt
    assert wkt.upper().startswith("MULTIPOLYGON")
    assert "2.000000 0.000000" in wkt              # 2nd part present
    assert "0.000000 0.000000" in wkt              # 1st part present
    # the AOI/bbox checks span ALL parts (union bbox)
    assert bbox_from_wkt(wkt) == pytest.approx((0.0, 0.0, 3.0, 1.0))


def test_single_polygon_footprint_unchanged(fake_asf):
    fake_asf.queue = [[fake_item("plain")]]
    backend = b2.B2ASFSearchBackend({})
    scenes = backend.search(SearchParameters(max_results=5))
    assert scenes[0].footprint_wkt.startswith("POLYGON")
