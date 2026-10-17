# -*- coding: utf-8 -*-
"""WP-5: pure geometry helpers.

CRS selection for map layers (finding F4) and the WGS84 bbox of a
projected grid (finding F9). The UTM anchor pairs were computed once
with pyproj 3.7.1 (EPSG:4326 <-> EPSG:32632/32735/32618/32717); the unit
environment has no GDAL/pyproj, so the tests exercise the analytic
inverse-UTM fallback path of nisar_core.geo.
"""
from types import SimpleNamespace

import pytest

from nisar_qgis.nisar_core.geo import (
    bbox_wgs84_from_georef, select_layer_crs, utm_forward, utm_inverse,
    utm_zone_from_authid,
)

# (zone, south, lat, lon, easting, northing) — pyproj 3.7.1 anchors
ANCHORS = [
    (32, False, 48.1372, 11.5755, 691603.8, 5334757.8),     # Munich, 32N
    (35, True, -26.2041, 28.0473, 604633.1, 7101290.8),    # Johannesburg, 35S
    (18, False, 25.7617, -80.1918, -21073.7, 2859573.6),   # Miami, 18N
    (17, True, -12.0464, -77.0428, 931018.4, 8665205.4),   # Lima, 17S
]
TOL_DEG = 0.05


# ------------------------------------------------------------------- F4
def test_select_layer_crs_valid_raster_keeps_own_crs():
    # dcoh.tif with a valid CRS must keep it even while another product
    # (different CRS) is open — the georef fallback must NOT be applied
    assert select_layer_crs(True, "EPSG:32632", "<WKT>") is None


def test_select_layer_crs_crsless_raster_takes_georef_fallback():
    assert select_layer_crs(False, "EPSG:32632", "") == ("EPSG:32632", "")
    assert select_layer_crs(False, "", "<WKT>") == ("", "<WKT>")


def test_select_layer_crs_nothing_known_returns_none():
    # never guess a CRS (AGENTS.md 3.2)
    assert select_layer_crs(False, "", "") is None


# ------------------------------------------------------------------- F9
def test_forward_matches_pyproj_anchors():
    for zone, south, lat, lon, x, y in ANCHORS:
        fx, fy = utm_forward(lat, lon, zone, south)
        assert fx == pytest.approx(x, abs=1.0)
        assert fy == pytest.approx(y, abs=1.0)


def test_inverse_within_005_deg_of_anchors():
    for zone, south, lat, lon, x, y in ANCHORS:
        la, lo = utm_inverse(x, y, zone, south)
        assert abs(la - lat) <= TOL_DEG
        assert abs(lo - lon) <= TOL_DEG


def test_utm_zone_from_authid():
    assert utm_zone_from_authid("EPSG:32632") == (32, False)
    assert utm_zone_from_authid("epsg:32735") == (35, True)
    assert utm_zone_from_authid("EPSG:26732") is None  # NAD27 not supported
    assert utm_zone_from_authid("EPSG:4326") is None
    assert utm_zone_from_authid("") is None


def _georef(zone, south, lat, lon, half=12000.0):
    x, y = utm_forward(lat, lon, zone, south)
    authid = "EPSG:%d" % (32700 + zone if south else 32600 + zone)
    return SimpleNamespace(bbox=(x - half, y - half, x + half, y + half),
                           crs_authid=authid, crs_wkt="")


@pytest.mark.parametrize("zone,south,lat,lon,x,y", ANCHORS)
def test_bbox_wgs84_center_matches_anchor(zone, south, lat, lon, x, y):
    box = bbox_wgs84_from_georef(_georef(zone, south, lat, lon))
    assert box is not None
    assert abs((box[0] + box[2]) / 2.0 - lon) <= TOL_DEG
    assert abs((box[1] + box[3]) / 2.0 - lat) <= TOL_DEG


def test_bbox_wgs84_4326_passthrough():
    georef = SimpleNamespace(bbox=(5.0, 47.0, 7.0, 49.0),
                             crs_authid="EPSG:4326", crs_wkt="")
    assert bbox_wgs84_from_georef(georef) == (5.0, 47.0, 7.0, 49.0)


def test_bbox_wgs84_unknown_crs_does_not_guess():
    georef = SimpleNamespace(bbox=(500000.0, 5000000.0, 520000.0, 5200000.0),
                             crs_authid="EPSG:3035", crs_wkt="")
    try:
        import pyproj  # noqa: F401
    except ImportError:
        assert bbox_wgs84_from_georef(georef) is None
        return
    # with a transform backend the CRS resolves — still must not guess
    assert bbox_wgs84_from_georef(georef) is not None
