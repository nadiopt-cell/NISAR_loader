# -*- coding: utf-8 -*-
"""
Pure-geometry helpers (QGIS-free), shared by readers/processing/GUI.

WP-5 / review findings F4, F9:

  * an output raster keeps its OWN CRS — a source-product georef may be
    applied only as an explicit fallback when the raster carries none
    (:func:`select_layer_crs`);
  * the WGS84 bbox of a projected grid is computed by a REAL transform
    (OSR when GDAL is present, pyproj when present) with an analytic
    inverse-UTM fallback (southern hemisphere + zone central meridian
    handled exactly) — never by the old ``x / 111320`` scale hack
    (:func:`bbox_wgs84_from_georef`).

Reference anchor pairs in the tests were computed once with pyproj 3.7.1
(EPSG:32632 / 32735 / 32618 / 32717) and parked in
tests/unit/test_geo.py.
"""
import logging
import math
from typing import Optional, Tuple

logger = logging.getLogger("nisar.core.geo")

_A = 6378137.0                      # WGS84 semi-major axis, m
_E2 = 0.0066943799901413165         # first eccentricity squared
_EP2 = _E2 / (1.0 - _E2)
_K0 = 0.9996
_FALSE_E = 500000.0
_FALSE_N_SOUTH = 10000000.0
_H = 1e-6                # radian step for the latitude jacobian
_H_DEG = 1e-4            # degree step for the longitude jacobian


# ---------------------------------------------------------------------------
# F4/WP-5: CRS selection for map layers
# ---------------------------------------------------------------------------
def select_layer_crs(raster_crs_valid: bool,
                     fallback_authid: str = "",
                     fallback_wkt: str = "",
                     ) -> Optional[Tuple[str, str]]:
    """The CRS to apply when adding an output raster to the project.

    The raster's own CRS always wins: ``dcoh.tif`` etc. must keep the
    grid CRS they were written with, even while a *different* product is
    open in the dialog (review finding F4). The source-product georef is
    consulted only for CRS-less outputs. Returns ``(authid, wkt)`` to
    force, or ``None`` to keep the raster's own CRS — also when nothing
    is known (never guess a CRS, AGENTS.md §3.2).
    """
    if raster_crs_valid:
        return None
    if fallback_authid or fallback_wkt:
        return (fallback_authid or "", fallback_wkt or "")
    return None


# ---------------------------------------------------------------------------
# UTM forward / inverse (WGS84, standard Snyder transverse-Mercator series)
# ---------------------------------------------------------------------------
def utm_forward(lat_deg: float, lon_deg: float, zone: int,
                south: bool = False) -> Tuple[float, float]:
    """WGS84 UTM forward projection of one point (x easting, y northing)."""
    lat = math.radians(lat_deg)
    lon0 = math.radians(zone * 6.0 - 183.0)
    dlon = math.radians(lon_deg) - lon0
    sp, cp = math.sin(lat), math.cos(lat)
    tan2 = (sp / cp) ** 2
    N = _A / math.sqrt(1.0 - _E2 * sp * sp)
    C = _EP2 * cp * cp
    A = cp * dlon
    e2, e4, e6 = _E2, _E2 * _E2, _E2 * _E2 * _E2
    M = _A * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * lat
              - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024)
              * math.sin(2 * lat)
              + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * lat)
              - (35 * e6 / 3072) * math.sin(6 * lat))
    x = _K0 * N * (A + (1 - tan2 + C) * A ** 3 / 6
                   + (5 - 18 * tan2 + tan2 * tan2 + 72 * C - 58 * _EP2)
                   * A ** 5 / 120) + _FALSE_E
    y = _K0 * (M + N * (sp / cp) * (A ** 2 / 2
                + (5 - tan2 + 9 * C + 4 * C * C) * A ** 4 / 24
                + (61 - 58 * tan2 + tan2 * tan2 + 600 * C - 330 * _EP2)
                * A ** 6 / 720))
    if south:
        y += _FALSE_N_SOUTH
    return x, y


def _footpoint_lat(M: float) -> float:
    """Footpoint (rectifying) latitude from the meridian arc M (radians)."""
    mu = M / (_A * (1 - _E2 / 4 - 3 * _E2 ** 2 / 64
                    - 5 * _E2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))
    return (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))


def utm_inverse(x: float, y: float, zone: int, south: bool = False,
                ) -> Tuple[float, float]:
    """Analytic inverse UTM (WGS84, Snyder §§8-11/8-25, footpoint scheme).

    Pure math, no dependencies: footpoint latitude from the meridian arc,
    then the standard closed transverse-Mercator inversion (sub-mm for
    UTM openings). Handles the southern hemisphere (EPSG:327xx false
    northing) and the zone central meridian.
    """
    M = (y - (_FALSE_N_SOUTH if south else 0.0)) / _K0
    phi1 = _footpoint_lat(M)
    sp = math.sin(phi1)
    cp = math.cos(phi1)
    tp = sp / cp
    C1 = _EP2 * cp * cp
    T1 = tp * tp
    N1 = _A / math.sqrt(1.0 - _E2 * sp * sp)
    R1 = _A * (1.0 - _E2) / (1.0 - _E2 * sp * sp) ** 1.5
    D = (x - _FALSE_E) / max(N1 * _K0, 1.0)

    phi = phi1 - (N1 * tp / R1) * (
        D * D / 2.0
        - (5.0 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * _EP2)
        * D ** 4 / 24.0
        + (61.0 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * _EP2
           - 3 * C1 * C1) * D ** 6 / 720.0)
    lon = math.radians(zone * 6.0 - 183.0) + (
        D - (1.0 + 2 * T1 + C1) * D ** 3 / 6.0
        + (5.0 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * _EP2
           + 24 * T1 * T1) * D ** 5 / 120.0) / cp

    lon_deg = math.degrees(lon)
    # keep the longitude inside the same 360-degree branch as the zone
    cm = zone * 6 - 183
    while lon_deg - cm > 180.0:
        lon_deg -= 360.0
    while lon_deg - cm < -180.0:
        lon_deg += 360.0
    return math.degrees(phi), lon_deg


def _footpoint_lat(M: float) -> float:
    """Footpoint (rectifying) latitude from the meridian arc M (radians)."""
    mu = M / (_A * (1 - _E2 / 4 - 3 * _E2 ** 2 / 64
                    - 5 * _E2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))
    return (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))


def utm_zone_from_authid(authid: str) -> Optional[Tuple[int, bool]]:
    """(zone, south) from an EPSG:326xx/327xx authid, else None."""
    text = (authid or "").upper().replace("EPSG:", "").replace("EPSG, ", "")
    try:
        code = int(text.split(":")[-1].strip())
    except (ValueError, AttributeError):
        return None
    if 32600 <= code <= 32660:
        return (code - 32600, False)
    if 32700 <= code <= 32760:
        return (code - 32700, True)
    return None


# ---------------------------------------------------------------------------
# F9/WP-5: WGS84 bbox of a projected grid
# ---------------------------------------------------------------------------
def _bbox_corners(georef) -> list:
    """8 points: 4 bbox corners + 4 edge midpoints (zone curvature)."""
    minx, miny, maxx, maxy = georef.bbox
    return [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy),
            ((minx + maxx) / 2.0, miny), ((minx + maxx) / 2.0, maxy),
            (minx, (miny + maxy) / 2.0), (maxx, (miny + maxy) / 2.0)]


def _bbox_via_osr(georef, zone: Optional[int], south: bool) \
        -> Optional[Tuple[float, float, float, float]]:
    try:
        from osgeo import osr
    except Exception:
        return None
    try:
        src = osr.SpatialReference()
        if zone is not None:
            src.ImportFromEPSG(32700 + zone if south else 32600 + zone)
        elif georef.crs_wkt:
            src.ImportFromWkt(georef.crs_wkt)
        elif georef.crs_authid:
            src.SetFromUserInput(georef.crs_authid)
        else:
            return None
        dst = osr.SpatialReference()
        dst.ImportFromEPSG(4326)
        dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        ct = osr.CoordinateTransformation(src, dst)
        pts = ct.TransformPoints(_bbox_corners(georef))
        lons = [float(p[0]) for p in pts]
        lats = [float(p[1]) for p in pts]
        return (min(lons), min(lats), max(lons), max(lats))
    except Exception as exc:
        logger.debug("osr bbox transform failed: %s", exc)
        return None


def _bbox_via_pyproj(georef, zone: Optional[int], south: bool) \
        -> Optional[Tuple[float, float, float, float]]:
    try:
        from pyproj import Transformer
    except Exception:
        return None
    try:
        if zone is not None:
            src = "EPSG:%d" % (32700 + zone if south else 32600 + zone)
        else:
            src = georef.crs_authid or georef.crs_wkt
        if not src:
            return None
        tr = Transformer.from_crs(src, "EPSG:4326", always_xy=True)
        codes = [tr.transform(x, y) for x, y in _bbox_corners(georef)]
        lons = [float(c[0]) for c in codes]
        lats = [float(c[1]) for c in codes]
        return (min(lons), min(lats), max(lons), max(lats))
    except Exception as exc:
        logger.debug("pyproj bbox transform failed: %s", exc)
        return None


def _bbox_via_utm(georef, zone: int, south: bool) \
        -> Tuple[float, float, float, float]:
    lons, lats = [], []
    for px, py in _bbox_corners(georef):
        lat, lon = utm_inverse(px, py, zone, south)
        lons.append(lon)
        lats.append(lat)
    return (min(lons), min(lats), max(lons), max(lats))


def bbox_wgs84_from_georef(georef) -> Optional[Tuple[float, float,
                                                     float, float]]:
    """WGS84 ``(minx, miny, maxx, maxy)`` of a projected grid (F9/WP-5).

    Priority: EPSG:4326 passthrough → OSR/GDAL → pyproj → analytic
    inverse UTM. Returns ``None`` when the CRS is neither EPSG:4326 nor a
    recognized UTM zone (and no transform backend is available) — the
    caller must report that, not guess.
    """
    try:
        minx, miny, maxx, maxy = georef.bbox
    except Exception:
        return None
    authid = (getattr(georef, "crs_authid", "") or "").upper()
    if "4326" in authid:
        return (minx, miny, maxx, maxy)
    zone_south = utm_zone_from_authid(authid)
    if zone_south is None:
        # fall back to scanning the WKT for an EPSG:32xxx authority
        import re as _re
        wkt = getattr(georef, "crs_wkt", "") or ""
        m = _re.search(r'32[67]\d\d\b', wkt or "")
        zone_south = utm_zone_from_authid(m.group(0)) if m else None
    if zone_south is not None:
        zone, south = zone_south
        box = _bbox_via_osr(georef, zone, south)
        if box is not None:
            return box
        box = _bbox_via_pyproj(georef, zone, south)
        if box is not None:
            return box
        return _bbox_via_utm(georef, zone, south)
    # non-UTM CRS: try the transform backends with raw definitions only
    box = _bbox_via_osr(georef, None, False)
    if box is not None:
        return box
    box = _bbox_via_pyproj(georef, None, False)
    if box is not None:
        return box
    return None
