# -*- coding: utf-8 -*-
"""
V2: NumPy-based processing backend for vegetation indices.

Two usage modes:
  * **windowed** — ``compute_*`` functions return ``IndexResult`` arrays
    (unit tests, small windows);
  * **tiled to disk** — :func:`compute_index_to_raster` walks the layer in
    tiles and writes a Float32 GeoTIFF directly, keeping peak memory at
    roughly ``tile_size x tile_size x layers x 8 bytes`` (TZ P2.6).

Formulas operate on **linear gamma-0 power** values (GCOV units — see
docs/product_notes.md). dB products are computed as 10*log10(x).
"""
import logging
from dataclasses import dataclass
from typing import Tuple, Optional, Dict, Any, List, Callable

import numpy as np

from ..models import LayerInfo, Polarization, ProductHandle, ProcessingResult
from ..readers import ReaderRegistry

logger = logging.getLogger("nisar.processing.indices")


class VegetationIndex:
    """Known index ids (matches presets.py ids)."""
    HV_DB = "hv_db"
    CROSS_RATIO = "cross_ratio"
    RVI = "rvi"


@dataclass
class IndexResult:
    """Result of an index computation (windowed mode)."""
    data: np.ndarray
    nodata_mask: np.ndarray
    units: str
    description: str
    formula_used: str


# Formulas (documented in docs/product_notes.md):
#   hv_db       : 10 * log10(HVHV)                      [protection at <=0]
#   cross_ratio : 10*log10(HVHV) - 10*log10(HHHH)
#   rvi dual-pol: 4*HV / (HH + HV)      (HH/HV data)
#   rvi full-pol: 8*HV / (HH + VV + 2*HV)  (quad-pol data; Kim & van Zyl
#                 style formulation, see product_notes.md "RVI sources")
_EPS = 1e-10


def _safe_log10(data: np.ndarray) -> np.ndarray:
    """10*log10 with zero/negative/NaN protection; NaN where invalid."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 10.0 * np.log10(np.where(data > 0, data, np.nan))
    out[~np.isfinite(out)] = np.nan
    return out


class NumpyProcessingBackend:
    """NumPy windowed processing for vegetation indices."""

    DEFAULT_TILE_SIZE = 512

    def __init__(self, config: Dict[str, Any] = None):
        if config is None:
            config = {}
        elif not isinstance(config, dict) and hasattr(config, "__dict__"):
            config = vars(config)
        self.config = config or {}
        self.tile_size = int(self.config.get("tile_size", self.DEFAULT_TILE_SIZE))
        self.eps = _EPS

    # ------------------------------------------------------------- helpers
    def _get_reader(self, handle: ProductHandle):
        """Reader instance matching the handle's backend."""
        for backend in ReaderRegistry._backends:
            if backend.BACKEND_ID == handle.reader_backend:
                return backend(self.config)
        available = ReaderRegistry.get_available_backends()
        if not available:
            raise RuntimeError("No reader backend available")
        return available[0](self.config)

    def _find_layer(self, handle: ProductHandle, preferred_name: str,
                    preferred_pol: Polarization = None) -> Optional[LayerInfo]:
        for layer in handle.layers:
            if layer.name == preferred_name:
                return layer
        if preferred_pol is not None:
            for layer in handle.layers:
                if layer.polarization is preferred_pol:
                    return layer
        for layer in handle.layers:
            if preferred_name.lower() in layer.name.lower():
                return layer
        return None

    def _read_full_tiled(self, handle: ProductHandle, layer_name: str,
                         reader) -> np.ndarray:
        """Read a full layer tile by tile ((height, width) convention)."""
        layer = self._find_layer(handle, layer_name)
        if not layer:
            raise ValueError("Layer %r not found" % layer_name)
        height, width = layer.shape[0], layer.shape[1]
        full_data = np.full((height, width), np.nan, dtype=np.float32)
        for y in range(0, height, self.tile_size):
            ysize = min(self.tile_size, height - y)
            for x in range(0, width, self.tile_size):
                xsize = min(self.tile_size, width - x)
                tile = reader.read_window(handle, layer.name, (x, y, xsize, ysize))
                if tile.ndim == 3:
                    tile = tile[0]
                full_data[y:y + ysize, x:x + xsize] = tile
        return full_data

    # ----------------------------------------------------------- hv_db
    def compute_hv_db(self, handle: ProductHandle, layer_name: str = "HVHV",
                      window: Optional[Tuple[int, int, int, int]] = None
                      ) -> IndexResult:
        """HV in dB: 10*log10(HVHV), zero/NaN protected."""
        reader = self._get_reader(handle)
        layer = (self._find_layer(handle, layer_name, Polarization.HVHV)
                 or self._find_layer(handle, layer_name))
        if not layer:
            raise ValueError("HVHV layer not found in product")

        if window:
            data = np.asarray(reader.read_window(handle, layer.name, window),
                              dtype=np.float64)
        else:
            data = np.asarray(self._read_full_tiled(handle, layer.name, reader),
                              dtype=np.float64)

        db_data = _safe_log10(data).astype(np.float32)
        nodata_mask = ~np.isfinite(db_data)

        return IndexResult(
            data=db_data,
            nodata_mask=nodata_mask,
            units="dB",
            description="Cross-polarization HV backscatter in decibels",
            formula_used="10 * log10(HVHV) [gamma0 linear -> dB]",
        )

    # ----------------------------------------------------------- cross_ratio
    def compute_cross_ratio(self, handle: ProductHandle,
                            hv_layer: str = "HVHV", hh_layer: str = "HHHH",
                            window: Optional[Tuple[int, int, int, int]] = None
                            ) -> IndexResult:
        """Cross-ratio HV/HH in dB == HV_dB - HH_dB."""
        reader = self._get_reader(handle)
        hv = (self._find_layer(handle, hv_layer, Polarization.HVHV)
              or self._find_layer(handle, hv_layer))
        hh = (self._find_layer(handle, hh_layer, Polarization.HHHH)
              or self._find_layer(handle, hh_layer))
        if not hv or not hh:
            raise ValueError(
                "Cross-ratio requires HVHV and HHHH layers "
                "(got HV=%s, HH=%s)" % (bool(hv), bool(hh)))

        if window:
            hv_data = np.asarray(reader.read_window(handle, hv.name, window),
                                 dtype=np.float64)
            hh_data = np.asarray(reader.read_window(handle, hh.name, window),
                                 dtype=np.float64)
        else:
            hv_data = np.asarray(self._read_full_tiled(handle, hv.name, reader),
                                 dtype=np.float64)
            hh_data = np.asarray(self._read_full_tiled(handle, hh.name, reader),
                                 dtype=np.float64)

        ratio_db = (_safe_log10(hv_data) - _safe_log10(hh_data)).astype(np.float32)
        nodata_mask = ~np.isfinite(ratio_db)

        return IndexResult(
            data=ratio_db,
            nodata_mask=nodata_mask,
            units="dB",
            description="Cross-ratio HV/HH in decibels",
            formula_used="10*log10(HVHV) - 10*log10(HHHH)",
        )

    # ----------------------------------------------------------- rvi
    def compute_rvi(self, handle: ProductHandle,
                    window: Optional[Tuple[int, int, int, int]] = None
                    ) -> IndexResult:
        """RVI; formula auto-selected from available polarizations."""
        reader = self._get_reader(handle)
        hv = self._find_layer(handle, "HVHV", Polarization.HVHV)
        hh = self._find_layer(handle, "HHHH", Polarization.HHHH)
        vv = self._find_layer(handle, "VVVV", Polarization.VVVV)
        vh = self._find_layer(handle, "VHVH", Polarization.VHVH)

        if not hv:
            raise ValueError("RVI requires an HV layer (HVHV)")
        full_pol = (hh is not None and (vv is not None or vh is not None)
                    and vv is not None)

        def read(layer):
            if window:
                return np.asarray(reader.read_window(handle, layer.name, window),
                                  dtype=np.float64)
            return np.asarray(self._read_full_tiled(handle, layer.name, reader),
                              dtype=np.float64)

        hv_data = read(hv)
        if full_pol and vv is not None:
            co_data = read(vv) if vv is not None else read(hh)
            # Full-pol: 8*HV / (HH + VV + 2*HV)
            denominator = (co_data if hh is None else read(hh)) + co_data \
                + 2.0 * hv_data
            numerator = 8.0 * hv_data
            formula = "8*HV / (HH + VV + 2*HV) [full-pol]"
        elif hh is not None:
            # Dual-pol: 4*HV / (HH + HV)
            denominator = read(hh) + hv_data
            numerator = 4.0 * hv_data
            formula = "4*HV / (HH + HV) [dual-pol]"
        else:
            raise ValueError(
                "RVI needs HH (dual-pol) or HH+VV (full-pol) in addition to HV")

        with np.errstate(divide="ignore", invalid="ignore"):
            rvi = numerator / np.where(denominator > 0, denominator, np.nan)
        rvi[~np.isfinite(rvi)] = np.nan

        return IndexResult(
            data=rvi.astype(np.float32),
            nodata_mask=~np.isfinite(rvi),
            units="unitless (typically 0..1)",
            description="Radar Vegetation Index",
            formula_used=formula,
        )

    # ----------------------------------------------------------- speckle
    def apply_speckle_filter(self, data: np.ndarray, method: str = "median",
                             kernel_size: int = 3) -> np.ndarray:
        """Apply speckle filter to a 2D array (visualization only)."""
        try:
            from scipy import ndimage
        except ImportError:
            raise RuntimeError(
                "Speckle filter requires scipy (pip install scipy)")

        if method == "median":
            return ndimage.median_filter(data, size=kernel_size)
        if method == "box":
            return ndimage.uniform_filter(data, size=kernel_size)
        if method == "lee":
            return self._lee_filter(data, kernel_size)
        raise ValueError("Unknown filter method: %r" % method)

    def _lee_filter(self, data: np.ndarray, kernel_size: int) -> np.ndarray:
        from scipy import ndimage
        mean = ndimage.uniform_filter(data, size=kernel_size)
        mean_sq = ndimage.uniform_filter(data ** 2, size=kernel_size)
        var = np.maximum(mean_sq - mean ** 2, 0.0)
        global_var = float(np.nanvar(data)) or self.eps
        weight = var / (var + global_var + self.eps)
        return mean + weight * (data - mean)


# =====================================================================
# Tiled computation straight to a GDAL raster (needs GDAL for writing)
# =====================================================================

def _tile_windows(height: int, width: int, tile_size: int):
    """Yield (xoff, yoff, xsize, ysize) windows covering the grid."""
    for y in range(0, height, tile_size):
        ysize = min(tile_size, height - y)
        for x in range(0, width, tile_size):
            xsize = min(tile_size, width - x)
            yield x, y, xsize, ysize


def compute_index_to_raster(handle: ProductHandle, index_id: str,
                            output_path, config: Dict = None,
                            progress_callback: Callable = None,
                            is_canceled: Callable = None,
                            cog: bool = False) -> ProcessingResult:
    """Compute *index_id* tile-by-tile and write Float32 GeoTIFF/COG.

    This is the MVP processing entry point used by the GUI and Processing
    algorithms: peak memory stays at a few tiles, the source .h5 is only
    read (never modified), and the output keeps scientific Float32 values.
    """
    from .export import ExportBackend

    config = dict(config or {})
    tile_size = int(config.get("tile_size", 512))
    backend = NumpyProcessingBackend(config)
    reader = backend._get_reader(handle)

    georef = handle.georef
    if georef is None or not georef.is_valid:
        return ProcessingResult(
            success=False,
            error_message=("Product has no valid georeference; refusing to "
                           "write a geo-referenced raster from it"))

    # Collect required layers per index.
    layers: Dict[str, LayerInfo] = {}
    if index_id == VegetationIndex.HV_DB:
        layer = backend._find_layer(handle, "HVHV", Polarization.HVHV)
        if not layer:
            return ProcessingResult(success=False,
                                    error_message="HVHV layer not found")
        layers["hv"] = layer
    elif index_id == VegetationIndex.CROSS_RATIO:
        hv = backend._find_layer(handle, "HVHV", Polarization.HVHV)
        hh = backend._find_layer(handle, "HHHH", Polarization.HHHH)
        if not hv or not hh:
            missing = [n for n, l in (("HVHV", hv), ("HHHH", hh)) if not l]
            return ProcessingResult(
                success=False,
                error_message="Cross-ratio requires HVHV and HHHH "
                              "(missing: %s)" % ", ".join(missing))
        layers["hv"], layers["hh"] = hv, hh
    elif index_id == VegetationIndex.RVI:
        hv = backend._find_layer(handle, "HVHV", Polarization.HVHV)
        hh = backend._find_layer(handle, "HHHH", Polarization.HHHH)
        vv = backend._find_layer(handle, "VVVV", Polarization.VVVV)
        if not hv or not hh:
            return ProcessingResult(
                success=False,
                error_message="RVI requires at least HVHV and HHHH layers")
        layers["hv"], layers["hh"] = hv, hh
        if vv is not None:
            layers["vv"] = vv
    else:
        return ProcessingResult(success=False,
                                error_message="Unknown index id %r" % index_id)

    # Determine formula for RVI (displayed to the user).
    formula = ""
    if index_id == VegetationIndex.HV_DB:
        formula = "10 * log10(HVHV)"
    elif index_id == VegetationIndex.CROSS_RATIO:
        formula = "10*log10(HVHV) - 10*log10(HHHH)"
    elif index_id == VegetationIndex.RVI:
        formula = ("8*HV / (HH + VV + 2*HV) [full-pol]"
                   if "vv" in layers else
                   "4*HV / (HH + HV) [dual-pol]")

    height, width = layers["hv"].shape
    exporter = ExportBackend(dict(config, cog=cog))
    ds = exporter.create_dataset(str(output_path), width, height, "Float32",
                                 georef, nodata=np.nan)
    try:
        if ds is None:
            return ProcessingResult(
                success=False,
                error_message="Failed to create output raster %s" % output_path)

        band = ds.GetRasterBand(1)
        band.SetNoDataValue(float("nan"))

        total_tiles = sum(1 for _ in _tile_windows(height, width, tile_size))
        done = 0
        for xoff, yoff, xsize, ysize in _tile_windows(height, width, tile_size):
            if is_canceled is not None and is_canceled():
                ds.FlushCache()
                del ds
                return ProcessingResult(
                    success=False,
                    error_message="Cancelled by user",
                    warnings=["Cancelled"])

            tile = _compute_tile(backend, reader, handle, layers,
                                 index_id, (xoff, yoff, xsize, ysize))
            band.WriteArray(tile.astype(np.float32), xoff, yoff)

            done += 1
            if progress_callback is not None:
                try:
                    progress_callback(int(100.0 * done / max(total_tiles, 1)))
                except Exception:  # pragma: no cover
                    pass

        band.FlushCache()
        exporter.finalize(ds)
        del ds
    except Exception as exc:
        try:
            del ds
        except Exception:  # pragma: no cover
            pass
        return ProcessingResult(success=False, error_message=str(exc))

    return ProcessingResult(
        success=True,
        output_paths=[str(output_path)],
        metadata={"index": index_id, "formula": formula,
                  "dtype": "Float32", "tile_size": tile_size},
    )


def _compute_tile(backend: NumpyProcessingBackend, reader, handle: ProductHandle,
                  layers: Dict[str, LayerInfo], index_id: str,
                  window: Tuple[int, int, int, int]) -> np.ndarray:
    """Compute one tile of the requested index (linear gamma0 in)."""
    def read(key):
        data = np.asarray(reader.read_window(handle, layers[key].name, window),
                          dtype=np.float64)
        if data.ndim == 3:
            data = data[0]
        return data

    hv = read("hv") if "hv" in layers else None
    hh = read("hh") if "hh" in layers else None
    vv = read("vv") if "vv" in layers else None

    if index_id == VegetationIndex.HV_DB:
        return _safe_log10(hv)
    if index_id == VegetationIndex.CROSS_RATIO:
        return _safe_log10(hv) - _safe_log10(hh)
    if index_id == VegetationIndex.RVI:
        if vv is not None:
            denominator = hh + vv + 2.0 * hv
            return 8.0 * hv / np.where(denominator > 0, denominator, np.nan)
        denominator = hh + hv
        return 4.0 * hv / np.where(denominator > 0, denominator, np.nan)
    raise ValueError("Unknown index %r" % index_id)


# Convenience wrappers (kept for unit tests and Processing algorithms)
def compute_hv_db(handle: ProductHandle, config: Dict = None, **kwargs) -> IndexResult:
    return NumpyProcessingBackend(config or {}).compute_hv_db(handle, **kwargs)


def compute_cross_ratio(handle: ProductHandle, config: Dict = None, **kwargs) -> IndexResult:
    return NumpyProcessingBackend(config or {}).compute_cross_ratio(handle, **kwargs)


def compute_rvi(handle: ProductHandle, config: Dict = None, **kwargs) -> IndexResult:
    return NumpyProcessingBackend(config or {}).compute_rvi(handle, **kwargs)
