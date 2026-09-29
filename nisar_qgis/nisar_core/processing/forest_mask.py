# -*- coding: utf-8 -*-
"""
Hansen Global Forest Change tile access for the windthrow DiD module.

Rule of the epoch (validated in the sentinel1_windthrow study): the
forest mask must be reconstructed for the year BEFORE the event:
    forest @ Y-1  = treecover2000 >= 30% AND no loss in 2001..Y-1
The background variant additionally excludes pixels lost in year Y.

Tile layout: 10deg x 10deg GeoTIFFs on Google Cloud Storage, public,
no authentication, streamed through /vsicurl/ (GDAL) without downloading.
Verified live URL scheme (2026-09-30):
  https://storage.googleapis.com/earthenginepartners-hansen/
  GFC-2024-v1.12/Hansen_GFC-2024-v1.12_treecover2000_50N_060E.tif
(v1.12 = GFC-2024 release; lossyear covers 2001..2024 — for event years
after 2025 the "no loss before event" rule saturates to lossyear == 0.)

The pure-NumPy part of the rule lives in windthrow.hansen_forest_mask_year;
this module only moves pixels (warp 30 m tiles -> scene grid).
"""
import logging
import math
import re
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from ..models import GeorefInfo
from .windthrow import (
    hansen_forest_mask_year, resample_fraction, DEFAULT_FOREST_FRACTION,
)

logger = logging.getLogger("nisar.processing.forest_mask")

GFC_BASE = "https://storage.googleapis.com/earthenginepartners-hansen"
DEFAULT_GFC_VERSION = "GFC-2024-v1.12"
GFC_TILE_DEG = 10.0
GFC_LAYERS = ("treecover2000", "lossyear")


def hansen_tile_suffixes(bbox_wgs84: Tuple[float, float, float, float]
                         ) -> List[str]:
    """Tile suffixes (e.g. '60N_060E') covering a lon/lat bbox.

    Verified live naming (2026-09-30, bounds checked with rasterio):
    a tile is named by its NORTHERN edge — 60N_060E covers lat 50..60N,
    00N_000E covers lat -10..0, 10S_000E covers lat -20..-10; the
    longitude is the tile's WESTERN edge.
    """
    minx, miny, maxx, maxy = bbox_wgs84
    suffixes = []
    lon = int(math.floor(minx / GFC_TILE_DEG)) * GFC_TILE_DEG
    while lon <= maxx:
        ew = "E" if lon >= 0 else "W"
        lon_name = abs(int(lon))
        lat = int(math.floor(miny / GFC_TILE_DEG)) * GFC_TILE_DEG
        while lat <= maxy:
            north_edge = lat + GFC_TILE_DEG
            ns = "N" if north_edge >= 0 else "S"
            suffixes.append("%02d%s_%03d%s"
                            % (abs(int(north_edge)), ns, lon_name, ew))
            lat += GFC_TILE_DEG
        lon += GFC_TILE_DEG
    # dedup, keep order
    return list(dict.fromkeys(suffixes))


def hansen_tile_names(bbox_wgs84: Tuple[float, float, float, float]) -> List[str]:
    """Backwards-compatible tile names (without version prefix)."""
    return hansen_tile_suffixes(bbox_wgs84)


def hansen_layer_urls(layer: str, bbox_wgs84: Tuple[float, float, float, float],
                      version: str = DEFAULT_GFC_VERSION) -> List[str]:
    "/vsicurl/-ready URLs of one GFC layer ('treecover2000'/'lossyear')."""
    if layer not in GFC_LAYERS:
        raise ValueError("unknown GFC layer %r (expected %s)"
                         % (layer, GFC_LAYERS))
    return ["%s/%s/Hansen_%s_%s_%s.tif" % (GFC_BASE, version, version,
                                           layer, suffix)
            for suffix in hansen_tile_suffixes(bbox_wgs84)]


def forest_mask_for_grid(georef: GeorefInfo, year: int,
                         version: str = DEFAULT_GFC_VERSION,
                         forest_fraction: float = DEFAULT_FOREST_FRACTION,
                         exclude_loss_year: bool = False,
                         bbox_wgs84: Optional[Tuple[float, float, float, float]] = None,
                         local_dir: Optional[str] = None,
                         ) -> Tuple[Optional[np.ndarray], List[str]]:
    """Forest-on-year mask on the GUNW 80 m grid (best effort).

    Returns (mask_or_None, warnings). Uses GDAL (osgeo) when available
    (QGIS; article-exact two-step: warp tiles to a 30 m scene grid, then
    aggregate), falls back to rasterio (standalone; direct per-source-
    pixel aggregation onto the 80 m grid — same semantics, less memory).
    Tiles are streamed through /vsicurl/ (URLs) or read from
    ``local_dir`` when a cached copy exists there.

    ``bbox_wgs84`` is best taken from the granule's identification
    ``boundingPolygon`` (WGS84, lon-lat) — see bbox_from_bounding_polygon.
    """
    warnings: List[str] = []
    if bbox_wgs84 is None:
        bbox_wgs84 = _approx_bbox_wgs84(georef)
    if bbox_wgs84 is None:
        return None, ["cannot approximate the scene bbox in WGS84"]

    try:
        mask = _forest_fraction_rasterio(georef, year, bbox_wgs84, version,
                                         local_dir, exclude_loss_year)
        if mask is not None:
            return (mask >= forest_fraction), warnings
    except Exception as exc:
        logger.debug("rasterio forest path failed: %s", exc)

    try:
        treecover, lossyear, src_transform, src_crs = \
            _read_hansen_gdal(bbox_wgs84, georef, version, local_dir)
    except Exception as exc:
        return None, ["Hansen GFC tiles unavailable: %s" % exc]
    if treecover is None or lossyear is None:
        return None, ["Hansen GFC tiles could not be read"]

    forest30 = hansen_forest_mask_year(treecover, lossyear, year,
                                       exclude_loss_year=exclude_loss_year)

    # resample the 30 m mask onto the (80 m) scene grid
    src_w, src_h = forest30.shape[1], forest30.shape[0]
    ulx, xres, _, uly, _, yres = src_transform
    src_xs = ulx + xres * (np.arange(src_w) + 0.5)
    src_ys = uly + yres * (np.arange(src_h) + 0.5)
    dst_xs = _dst_centers(georef.transform[0], georef.transform[1],
                          georef.width)
    dst_ys = _dst_centers(georef.transform[3], georef.transform[5],
                          georef.height)
    fraction = resample_fraction(forest30.astype(np.float32),
                                 src_xs, src_ys, dst_xs, dst_ys)
    mask = np.nan_to_num(fraction, nan=0.0) >= forest_fraction
    return mask, warnings


def _dst_centers(origin: float, spacing: float, count: int) -> np.ndarray:
    return origin + spacing * (np.arange(count) + 0.5)


# ---------------------------------------------------------------------------
# WGS84 bbox helpers
# ---------------------------------------------------------------------------
_NUM = r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?"
_POLYGON_RE = re.compile(
    r"POLYGON\s*\(\s*\(\s*((?:%s[\s,]+)*%s)\s*\)\s*\)" % (_NUM, _NUM),
    re.IGNORECASE)


def bbox_from_bounding_polygon(wkt: str) -> Optional[Tuple[float, float,
                                                             float, float]]:
    """(minx, miny, maxx, maxy) in WGS84 lon/lat from an OGR POLYGON WKT.

    NISAR identification ``boundingPolygon`` stores vertices as
    ``lon lat elevation`` triples (JPL product spec §5.2) — verified on a
    real GUNW granule: 41 vertices, 123 numbers, elevations 50..552 m.
    Plain lon-lat pairs are accepted as well; when the value count is
    ambiguous (divisible by 6) the CLOSED-ring interpretation wins
    (NISAR polygons repeat the first vertex at the end).
    """
    if not wkt:
        return None
    text = str(wkt)
    start = text.upper().find("POLYGON")
    if start < 0:
        return None
    values = [float(v) for v in re.findall(_NUM, text[start:])]
    if not values:
        return None

    def _closed_pairs(vals):
        return (len(vals) >= 8 and len(vals) % 2 == 0
                and vals[0:2] == vals[-2:])

    def _closed_triples(vals):
        return (len(vals) >= 12 and len(vals) % 3 == 0
                and vals[0:3] == vals[-3:])

    if len(values) % 3 == 0 and len(values) % 2 == 0:
        # ambiguous (divisible by 6): prefer the closed interpretation
        if _closed_triples(values) and not _closed_pairs(values):
            lons, lats = values[0::3], values[1::3]
        else:
            lons, lats = values[0::2], values[1::2]
    elif len(values) % 3 == 0:
        lons, lats = values[0::3], values[1::3]
    elif len(values) % 2 == 0:
        lons, lats = values[0::2], values[1::2]
    else:
        return None
    if not lons or not lats:
        return None
    return (min(lons), min(lats), max(lons), max(lats))


def _approx_bbox_wgs84(georef: GeorefInfo) -> Optional[Tuple[float, ...]]:
    """Rough WGS84 bbox of a projected georef (good enough for tiles)."""
    try:
        minx, miny, maxx, maxy = georef.bbox
        authid = (georef.crs_authid or "").upper()
        if "4326" in authid:
            return (minx, miny, maxx, maxy)
        if "326" in authid or "327" in authid:  # UTM: zone from EPSG
            zone = int(authid.split(":")[-1]) % 100
            central = zone * 6 - 183
            # ~111 km per degree; UTM x is relative to 500000
            lon = central + (minx - 500000.0) / 111320.0 / max(
                math.cos(math.radians((miny + maxy) / 2.0)), 0.2)
            lon2 = central + (maxx - 500000.0) / 111320.0 / max(
                math.cos(math.radians((miny + maxy) / 2.0)), 0.2)
            lat = miny / 110540.0
            lat2 = maxy / 110540.0
            return (min(lon, lon2), lat, max(lon, lon2), lat2)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("bbox approximation failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Tile readers: GDAL (QGIS) with rasterio fallback (standalone)
# ---------------------------------------------------------------------------
def _tile_path(layer: str, suffix: str, version: str, local_dir):
    """Local path (when cached) or /vsicurl/ URL of one GFC tile."""
    fname = "Hansen_%s_%s_%s.tif" % (version, layer, suffix)
    if local_dir:
        local = Path(str(local_dir)) / fname
        if local.exists():
            return str(local)
    return "%s/%s/%s" % (GFC_BASE, version, fname)


def _forest_fraction_rasterio(georef: GeorefInfo, year: int, bbox_wgs84,
                               version: str, local_dir,
                               exclude_loss_year: bool):
    """Direct forest-fraction aggregation onto the 80 m grid (rasterio).

    Per tile: read only the intersecting source window, build forest@Y
    with the pure-NumPy rule, then reproject (sum) forest pixels and a
    count raster onto the scene grid; num/den = forest fraction.
    """
    import rasterio
    from rasterio.warp import reproject, Resampling
    from rasterio.windows import from_bounds as win_from_bounds
    from rasterio.transform import from_origin

    height, width = georef.height, georef.width
    num = np.zeros((height, width), dtype=np.float64)
    den = np.zeros((height, width), dtype=np.float64)
    dst_transform = from_origin(georef.transform[0], georef.transform[3],
                                abs(georef.transform[1]),
                                abs(georef.transform[5]))
    dst_crs = georef.crs_wkt or georef.crs_authid
    used_any = False

    for suffix in hansen_tile_suffixes(bbox_wgs84):
        tc_path = _tile_path("treecover2000", suffix, version, local_dir)
        ly_path = _tile_path("lossyear", suffix, version, local_dir)
        try:
            with rasterio.open(tc_path) as tc_src, \
                    rasterio.open(ly_path) as ly_src:
                tb = tc_src.bounds
                ix0 = max(bbox_wgs84[0], tb.left)
                iy0 = max(bbox_wgs84[1], tb.bottom)
                ix1 = min(bbox_wgs84[2], tb.right)
                iy1 = min(bbox_wgs84[3], tb.top)
                if ix0 >= ix1 or iy0 >= iy1:
                    continue
                win = win_from_bounds(ix0, iy0, ix1, iy1,
                                      transform=tc_src.transform)
                win = win.round_offsets().round_lengths()
                tc = tc_src.read(1, window=win)
                ly = ly_src.read(1, window=win)
                src_transform = tc_src.window_transform(win)
                src_crs = tc_src.crs
        except Exception as exc:
            logger.debug("tile %s failed: %s", suffix, exc)
            continue

        forest30 = hansen_forest_mask_year(
            tc, ly, year, exclude_loss_year=exclude_loss_year)
        f32 = forest30.astype(np.float32)
        ones = np.ones_like(f32)
        # init_dest_nodata=False is ESSENTIAL: with the default True every
        # call would zero the shared accumulators and wipe the previous
        # tile's contribution (verified live — the bug produced an
        # all-zero mask).
        reproject(source=f32, destination=num,
                  src_transform=src_transform, src_crs=src_crs,
                  dst_transform=dst_transform, dst_crs=dst_crs,
                  resampling=Resampling.sum, num_threads=2,
                  init_dest_nodata=False)
        reproject(source=ones, destination=den,
                  src_transform=src_transform, src_crs=src_crs,
                  dst_transform=dst_transform, dst_crs=dst_crs,
                  resampling=Resampling.sum, num_threads=2,
                  init_dest_nodata=False)
        used_any = True

    if not used_any:
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        fraction = num / np.where(den > 0, den, np.nan)
    return np.nan_to_num(fraction, nan=0.0)


def _read_hansen_gdal(bbox_wgs84, georef: GeorefInfo, version: str,
                      local_dir=None):
    from osgeo import gdal, osr
    gdal.UseExceptions()
    target = _utm_30m_grid(georef)

    out = {}
    for layer in ("treecover2000", "lossyear"):
        urls = [_tile_path(layer, s, version, local_dir)
                for s in hansen_tile_suffixes(bbox_wgs84)]
        vrt = gdal.BuildVRT("", urls)
        if vrt is None:
            raise RuntimeError("BuildVRT failed for %s" % layer)
        warped = gdal.Warp("", vrt, format="MEM",
                           outputBounds=(target["ulx"], target["lry"],
                                         target["lrx"], target["uly"]),
                           xRes=target["xres"], yRes=target["yres"],
                           dstSRS=georef.crs_wkt or georef.crs_authid,
                           resampleAlg="near", targetAlignedPixels=True)
        vrt = None
        if warped is None:
            raise RuntimeError("Warp failed for %s" % layer)
        band = warped.GetRasterBand(1)
        out[layer] = band.ReadAsArray()
        warped = None
    transform = [target["ulx"], target["xres"], 0,
                 target["uly"], 0, -target["yres"]]
    return out["treecover2000"], out["lossyear"], transform, \
        georef.crs_authid



def _utm_30m_grid(georef: GeorefInfo) -> dict:
    """A 30 m grid covering the scene bbox, aligned to multiples of 30 m."""
    minx, miny, maxx, maxy = georef.bbox
    ulx = math.floor(minx / 30.0) * 30.0
    lry = math.floor(miny / 30.0) * 30.0
    uly = math.ceil(maxy / 30.0) * 30.0
    lrx = math.ceil(maxx / 30.0) * 30.0
    width = int(round((lrx - ulx) / 30.0))
    height = int(round((uly - lry) / 30.0))
    return {"ulx": ulx, "uly": uly, "lrx": lrx, "lry": lry,
            "xres": 30.0, "yres": 30.0, "width": width, "height": height,
            "bounds": (ulx, lry, lrx, uly)}
