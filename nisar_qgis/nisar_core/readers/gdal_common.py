# -*- coding: utf-8 -*-
"""
Shared helpers for the GDAL-based readers (A1 native, A2 netCDF workaround).

GDAL is optional: this module imports it lazily and every helper degrades
to a clear error message instead of an ImportError.
"""
import logging
import re
from typing import List, Tuple, Dict, Any

logger = logging.getLogger("nisar.readers.gdal")

try:
    from osgeo import gdal, osr
    gdal.UseExceptions()
    GDAL_AVAILABLE = True
except Exception:  # pragma: no cover - environment specific
    gdal = None
    osr = None
    GDAL_AVAILABLE = False

from . import product_layers as PL

_GDAL_DTYPES = {
    1: "Byte", 2: "UInt16", 3: "Int16", 4: "UInt32", 5: "Int32",
    6: "Float32", 7: "Float64", 8: "CInt16", 9: "CInt32",
    10: "CFloat32", 11: "CFloat64",
}

# Extract the trailing subdataset path segment, e.g.
# 'NETCDF:"/tmp/x.h5"://science/LSAR/GCOV/grids/frequencyA/HHHH' -> 'HHHH'
_LAYER_TAIL = re.compile(r'([^/:]+)\s*$')


def gdal_version() -> Tuple[int, int, int]:
    """GDAL version as (major, minor, patch)."""
    if not GDAL_AVAILABLE:  # pragma: no cover
        return (0, 0, 0)
    num = int(gdal.VersionInfo("VERSION_NUM"))
    return (num // 1000000, (num // 1000) % 1000, num % 1000)


def has_driver(name: str) -> bool:
    if not GDAL_AVAILABLE:  # pragma: no cover
        return False
    try:
        return gdal.GetDriverByName(name) is not None
    except Exception:
        return False


def apply_pam_config(config: Dict[str, Any]) -> None:
    """Do not write .aux.xml next to source files unless explicitly enabled."""
    if not GDAL_AVAILABLE:  # pragma: no cover
        return
    if not config.get("enable_pam", False):
        gdal.SetConfigOption("GDAL_PAM_ENABLED", "NO")
    proxy = config.get("pam_proxy_dir")
    if proxy:
        gdal.SetConfigOption("GDAL_PAM_PROXY_DIR", str(proxy))


def layer_name_from_subdataset(subds_name: str, subds_desc: str = "") -> str:
    """Human-readable layer name for a GDAL subdataset string.

    Known GCOV dataset names are preferred; otherwise a sanitized tail of
    the description/path is used (fallback only, per TZ P1.4).
    """
    for source in (subds_name, subds_desc):
        tail = _LAYER_TAIL.search(source.strip().strip('"'))
        if tail:
            candidate = tail.group(1)
            if candidate in PL.GCOV_ALL_COVARIANCE_TERMS \
                    or candidate in PL.GCOV_AUX_LAYERS \
                    or candidate in PL.SAR_POL_LAYERS:
                return candidate
    # Fallback: keep it readable and unique-ish.
    tail = _LAYER_TAIL.search(subds_name.strip().strip('"'))
    return tail.group(1) if tail else "layer"


def frequency_from_subdataset(subds_name: str) -> str:
    """'frequencyA' / 'frequencyB' if present in the subdataset path."""
    lowered = subds_name.lower()
    for freq in PL.FREQUENCY_GROUPS:
        if freq.lower() in lowered:
            return freq
    return ""


def frequency_letter(freq_label: str):
    """'frequencyA' -> 'A'; anything else -> None (WP-1)."""
    from ..models import frequency_letter_from_label
    return frequency_letter_from_label(freq_label)


def extract_layers_from_dataset(ds, handle_cache: Dict[str, Any],
                                ) -> List[Any]:
    """Build LayerInfo list from a GDAL dataset (subdatasets or bands).

    Returns a list of ``LayerInfo`` objects; opened subdatasets are kept
    in *handle_cache* for reuse by read_window (TZ P1.7).
    """
    from ..models import LayerInfo

    layers: List[LayerInfo] = []
    subdatasets = ds.GetSubDatasets() or []

    for subds_name, subds_desc in subdatasets:
        subds = handle_cache.get(subds_name)
        if subds is None:
            subds = gdal.Open(subds_name, gdal.GA_ReadOnly)
            if subds is None:
                continue
            handle_cache[subds_name] = subds

        name = layer_name_from_subdataset(subds_name, subds_desc)
        freq = frequency_from_subdataset(subds_name)
        band = subds.GetRasterBand(1)

        # WP-1: per-layer georef when GDAL can derive it for this
        # subdataset (NISAR driver >= 3.13); keeps frequencyB exports
        # from inheriting the frequencyA footprint.
        subds_georef = None
        try:
            subds_georef = georef_from_dataset(subds)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("subdataset georef failed for %s: %s", subds_name, exc)

        md = dict(band.GetMetadata() or {})
        units = "unknown"
        for key in ("units", "unit", "UNITS", "UNIT"):
            if key in md:
                units = md[key]
                break
        if name in PL.GCOV_REAL_COVARIANCE_TERMS and units in ("", "unknown", "1"):
            units = "gamma0 (linear power, RTC)"

        nodata = band.GetNoDataValue()

        layers.append(LayerInfo(
            name=name,
            path=subds_name,
            description=(subds_desc or name) + ((" [%s]" % freq) if freq else ""),
            polarization=PL.polarization_from_layer_name(name),
            units=units,
            shape=(subds.RasterYSize, subds.RasterXSize),  # (height, width)
            dtype=_GDAL_DTYPES.get(band.DataType, str(band.DataType)),
            no_data_value=None if nodata is None else float(nodata),
            metadata={"frequency": freq},
            frequency=frequency_letter(freq),
            georef=subds_georef,
        ))

    if not subdatasets and ds.RasterCount > 0:
        for band_idx in range(1, ds.RasterCount + 1):
            band = ds.GetRasterBand(band_idx)
            name = "band_%d" % band_idx
            md = dict(band.GetMetadata() or {})
            layers.append(LayerInfo(
                name=name,
                path="/band_%d" % band_idx,
                description="Band %d" % band_idx,
                polarization=None,
                units=md.get("units", "unknown"),
                shape=(ds.RasterYSize, ds.RasterXSize),
                dtype=_GDAL_DTYPES.get(band.DataType, str(band.DataType)),
                no_data_value=band.GetNoDataValue(),
                metadata={},
            ))
    return layers


def georef_from_dataset(ds) -> "Any":
    """Build GeorefInfo from a GDAL dataset (projection + geotransform)."""
    from ..models import GeorefInfo

    crs_wkt = ds.GetProjection() or ""
    auth_id = ""
    if crs_wkt and osr is not None:
        try:
            srs = osr.SpatialReference()
            srs.ImportFromWkt(crs_wkt)
            code = srs.GetAuthorityCode(None)
            if code:
                auth_id = "%s:%s" % (srs.GetAuthorityName(None) or "EPSG", code)
        except Exception as exc:  # pragma: no cover
            logger.debug("CRS parse failed: %s", exc)

    transform = ds.GetGeoTransform()
    warnings: List[str] = []
    valid = bool(crs_wkt) and transform is not None \
        and tuple(transform) != (0, 1, 0, 0, 0, 1)

    width, height = ds.RasterXSize, ds.RasterYSize
    if not crs_wkt:
        warnings.append("No projection information found")
    if not valid:
        warnings.append("Invalid or missing geotransform")
    if crs_wkt and not auth_id:
        warnings.append("CRS authority code not recognized")

    if transform is not None and valid:
        ulx, xres, xskew, uly, yskew, yres = transform
        lrx = ulx + width * xres + height * xskew
        lry = uly + width * yskew + height * yres
        bbox = (min(ulx, lrx), min(uly, lry), max(ulx, lrx), max(uly, lry))
        transform = list(transform)
    else:
        transform = [0, 1, 0, 0, 0, -1]
        bbox = (0, 0, width, height)

    return GeorefInfo(
        crs_wkt=crs_wkt, crs_authid=auth_id, transform=transform,
        width=width, height=height, bbox=bbox,
        is_valid=valid and not warnings, warnings=warnings)


def read_window_cached(handle, layer_name: str,
                       window: Tuple[int, int, int, int]) -> "Any":
    """Read a window using cached subdatasets of a GDAL-based handle."""
    import numpy as np

    cache = getattr(handle, "_subds_cache", None) or {}

    from ..models import resolve_layer
    target = resolve_layer(handle, layer_name)

    ds = cache.get(target.path)
    if ds is None:
        ds = gdal.Open(target.path, gdal.GA_ReadOnly)
        if ds is None:
            raise RuntimeError("Cannot open subdataset %r" % target.path)
        if not hasattr(handle, "_subds_cache"):
            handle._subds_cache = cache
        cache[target.path] = ds

    xoff, yoff, xsize, ysize = window
    band = ds.GetRasterBand(1)
    data = band.ReadAsArray(xoff, yoff, xsize, ysize)
    return data if data is not None else np.empty((ysize, xsize), np.float32)


def close_cached(handle) -> None:
    """Close all cached subdatasets of a handle."""
    cache = getattr(handle, "_subds_cache", None)
    if cache:
        cache.clear()  # GDAL datasets are refcounted; drop references
    if hasattr(handle, "_subds_cache"):
        handle._subds_cache = {}
    main_ds = getattr(handle, "_dataset", None)
    if main_ds is not None:
        handle._dataset = None
