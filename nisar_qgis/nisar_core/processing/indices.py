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
from typing import Tuple, Optional, Dict, Any, Callable, List

import numpy as np

from ..models import (
    LayerInfo, Polarization, ProductHandle, ProcessingResult,
    resolve_layer, LayerNotFoundError,
)
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


# =====================================================================
# Polarization-generic layer selection.
# Real NISAR GCOV products may transmit H (HHHH+HVHV) or V (VVVV+VHVH)
# depending on the observation mode — verified on a real UR granule
# (frequencyB, listOfPolarizations=[VH, VV]). Vegetation indices only
# need the cross-pol and co-pol layers, whichever orientation they have.
# =====================================================================
CROSS_POL_LAYER_NAMES = ("HVHV", "VHVH")   # cross-pol diagonal terms
CO_POL_LAYER_NAMES = ("HHHH", "VVVV")      # co-pol diagonal terms


def pick_index_layers(handle: ProductHandle, index_id: str,
                      preferred_frequency: Optional[str] = None
                      ) -> Tuple[Dict[str, LayerInfo], Optional[str]]:
    """Pick index inputs from ONE frequency grid (WP-1).

    Vegetation indices must never mix frequencyA and frequencyB layers.
    Returns ``(layers, frequency)``; *frequency* is "A"/"B" (None when the
    product carries no frequency tags). Raises ValueError with an explicit
    message when no single grid provides the needed polarizations.
    """
    def pol_value(layer):
        pol = getattr(layer, "polarization", None)
        return pol.value if pol is not None else None

    science = [l for l in handle.layers
               if pol_value(l) in ("HVHV", "VHVH", "HHHH", "VVVV")]
    by_freq: Dict[Optional[str], List[LayerInfo]] = {}
    for layer in science:
        by_freq.setdefault(layer.frequency, []).append(layer)

    order: List[Optional[str]] = []
    for f in (preferred_frequency, "A", "B", None):
        if f in by_freq and f not in order:
            order.append(f)

    def first(cands, pol_name):
        for layer in cands:
            if pol_value(layer) == pol_name:
                return layer
        return None

    for freq in order:
        cands = by_freq[freq]
        cross = (first(cands, "HVHV") or first(cands, "VHVH"))
        co_h = first(cands, "HHHH")
        co_v = first(cands, "VVVV")
        if index_id == VegetationIndex.HV_DB:
            if cross is not None:
                return {"hv": cross}, freq
        elif index_id == VegetationIndex.CROSS_RATIO:
            co = co_h if co_h is not None else co_v
            if cross is not None and co is not None:
                return {"hv": cross, "hh": co}, freq
        elif index_id == VegetationIndex.RVI:
            co = co_h if co_h is not None else co_v
            if cross is not None and co is not None:
                picked = {"hv": cross, "hh": co}
                if co_h is not None and co_v is not None:
                    picked["vv"] = co_v
                return picked, freq
        else:
            raise ValueError("Unknown index id %r" % index_id)

    avail = "; ".join(
        "%s: [%s]" % (("frequency%s" % f) if f else "no frequency tag",
                      ", ".join(sorted({l.name for l in ls})))
        for f, ls in by_freq.items())
    raise ValueError(
        "Index %r needs all its layers from a single frequency grid, "
        "but no grid has them all. Available: %s" % (index_id, avail))


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
                    preferred_pol: Polarization = None,
                    frequency: Optional[str] = None) -> Optional[LayerInfo]:
        # Exact name, then polarization, then whole last path segment.
        # No substring guessing (WP-1 / F14).
        candidates = [l for l in handle.layers
                      if frequency is None or l.frequency == frequency]
        for layer in candidates:
            if layer.name == preferred_name:
                return layer
        if preferred_pol is not None:
            for layer in candidates:
                if layer.polarization is preferred_pol:
                    return layer
        for layer in candidates:
            if layer.path and \
                    layer.path.rstrip("/").split("/")[-1] == preferred_name:
                return layer
        return None

    def _read_full_tiled(self, handle: ProductHandle, layer: LayerInfo,
                         reader) -> np.ndarray:
        """Read a full layer tile by tile ((height, width) convention).

        Reads go through the unambiguous ``layer_id`` (WP-1), so dual-grid
        products never resolve to the wrong frequency.
        """
        key = layer.layer_id or layer.name
        height, width = layer.shape[0], layer.shape[1]
        full_data = np.full((height, width), np.nan, dtype=np.float32)
        for y in range(0, height, self.tile_size):
            ysize = min(self.tile_size, height - y)
            for x in range(0, width, self.tile_size):
                xsize = min(self.tile_size, width - x)
                tile = reader.read_window(handle, key, (x, y, xsize, ysize))
                if tile.ndim == 3:
                    tile = tile[0]
                full_data[y:y + ysize, x:x + xsize] = tile
        return full_data

    # ----------------------------------------------------------- hv_db
    def compute_hv_db(self, handle: ProductHandle, layer_name: str = "HVHV",
                      window: Optional[Tuple[int, int, int, int]] = None
                      ) -> IndexResult:
        """Cross-pol backscatter in dB: 10*log10(HVHV or VHVH)."""
        reader = self._get_reader(handle)
        # Explicit key wins (unique name/layer_id); otherwise the
        # frequency-consistent cross-pol pick (WP-1).
        try:
            layer = resolve_layer(handle, layer_name)
        except LayerNotFoundError:
            picked, _freq = pick_index_layers(handle, VegetationIndex.HV_DB)
            layer = picked["hv"]

        if window:
            data = np.asarray(
                reader.read_window(handle, layer.layer_id or layer.name,
                                   window), dtype=np.float64)
        else:
            data = np.asarray(self._read_full_tiled(handle, layer, reader),
                              dtype=np.float64)

        db_data = _safe_log10(data).astype(np.float32)
        nodata_mask = ~np.isfinite(db_data)

        return IndexResult(
            data=db_data,
            nodata_mask=nodata_mask,
            units="dB",
            description="Cross-polarization (%s) backscatter in decibels"
                        % layer.name,
            formula_used="10 * log10(%s) [gamma0 linear -> dB]" % layer.name,
        )

    # ----------------------------------------------------------- cross_ratio
    def compute_cross_ratio(self, handle: ProductHandle,
                            hv_layer: str = "HVHV", hh_layer: str = "HHHH",
                            window: Optional[Tuple[int, int, int, int]] = None
                            ) -> IndexResult:
        """Cross/co-pol ratio in dB == cross_dB - co_dB."""
        reader = self._get_reader(handle)
        try:
            cross = resolve_layer(handle, hv_layer)
        except LayerNotFoundError:
            cross = None
        if cross is not None:
            try:
                co = resolve_layer(handle, hh_layer)
            except LayerNotFoundError:
                co = None
            if co is None:
                picked, _freq = pick_index_layers(
                    handle, VegetationIndex.CROSS_RATIO,
                    preferred_frequency=cross.frequency)
                co = picked["hh"]
        else:
            picked, _freq = pick_index_layers(
                handle, VegetationIndex.CROSS_RATIO)
            cross, co = picked["hv"], picked["hh"]
        # WP-1: one frequency grid per index; shapes must match.
        if (cross.frequency and co.frequency
                and cross.frequency != co.frequency):
            raise ValueError(
                "Cross-ratio inputs come from different grids (%s vs %s); "
                "indices never mix frequencyA and frequencyB layers"
                % (cross.layer_id, co.layer_id))
        if cross.shape != co.shape:
            raise ValueError(
                "Cross-ratio input shapes differ (%s vs %s)"
                % (cross.layer_id, co.layer_id))

        if window:
            cross_data = np.asarray(
                reader.read_window(handle, cross.layer_id or cross.name, window),
                dtype=np.float64)
            co_data = np.asarray(
                reader.read_window(handle, co.layer_id or co.name, window),
                dtype=np.float64)
        else:
            cross_data = np.asarray(
                self._read_full_tiled(handle, cross, reader),
                dtype=np.float64)
            co_data = np.asarray(
                self._read_full_tiled(handle, co, reader),
                dtype=np.float64)

        ratio_db = (_safe_log10(cross_data)
                    - _safe_log10(co_data)).astype(np.float32)
        nodata_mask = ~np.isfinite(ratio_db)

        return IndexResult(
            data=ratio_db,
            nodata_mask=nodata_mask,
            units="dB",
            description="Cross/co-pol ratio (%s/%s) in decibels"
                        % (cross.name, co.name),
            formula_used="10*log10(%s) - 10*log10(%s)"
                         % (cross.name, co.name),
        )

    # ----------------------------------------------------------- rvi
    def compute_rvi(self, handle: ProductHandle,
                    window: Optional[Tuple[int, int, int, int]] = None
                    ) -> IndexResult:
        """RVI; formula auto-selected from available polarizations."""
        reader = self._get_reader(handle)
        # WP-1: RVI inputs come from one frequency grid.
        picked, _freq = pick_index_layers(handle, VegetationIndex.RVI)
        cross = picked["hv"]
        co_h, co_v = picked.get("hh"), picked.get("vv")
        full_pol = co_v is not None

        def read(layer):
            key = layer.layer_id or layer.name
            if window:
                return np.asarray(reader.read_window(handle, key, window),
                                  dtype=np.float64)
            return np.asarray(self._read_full_tiled(handle, layer, reader),
                              dtype=np.float64)

        cross_data = read(cross)
        if full_pol:
            # Full-pol: 8*cross / (coH + coV + 2*cross)
            denominator = read(co_h) + read(co_v) + 2.0 * cross_data
            numerator = 8.0 * cross_data
            formula = "8*%s / (%s + %s + 2*%s) [full-pol]" % (
                cross.name, co_h.name, co_v.name, cross.name)
        else:
            co = co_h if co_h is not None else co_v
            if co is None:
                raise ValueError(
                    "RVI needs a co-pol layer (HHHH or VVVV) in addition "
                    "to the cross-pol layer")
            # Dual-pol: 4*cross / (co + cross)
            denominator = read(co) + cross_data
            numerator = 4.0 * cross_data
            formula = "4*%s / (%s + %s) [dual-pol]" % (
                cross.name, co.name, cross.name)

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

    # WP-1: all index inputs come from ONE frequency grid; never mix A/B.
    try:
        layers, frequency = pick_index_layers(
            handle, index_id,
            preferred_frequency=config.get("frequency"))
    except ValueError as exc:
        return ProcessingResult(success=False, error_message=str(exc))

    # Shape agreement inside the picked grid (defensive; lines usually
    # share a grid per frequency).
    shapes = {l.shape for l in layers.values()}
    if len(shapes) > 1:
        return ProcessingResult(
            success=False,
            error_message="%s: input layers have different shapes %s "
                          "(they should share one grid)" % (index_id, shapes))

    georef = handle.georef_for_frequency(frequency)
    if georef is None or not georef.is_valid:
        return ProcessingResult(
            success=False,
            error_message=("Product has no valid georeference for "
                           "frequency%s; refusing to write a geo-referenced "
                           "raster from it"
                           % (frequency if frequency else "?")))

    # Determine formula (displayed to the user; real layer names).
    formula = ""
    if index_id == VegetationIndex.HV_DB:
        formula = "10 * log10(%s)" % layers["hv"].name
    elif index_id == VegetationIndex.CROSS_RATIO:
        formula = "10*log10(%s) - 10*log10(%s)" % (layers["hv"].name,
                                                   layers["hh"].name)
    elif index_id == VegetationIndex.RVI:
        if "vv" in layers:
            formula = "8*%s / (%s + %s + 2*%s) [full-pol]" % (
                layers["hv"].name, layers["hh"].name, layers["vv"].name,
                layers["hv"].name)
        else:
            formula = "4*%s / (%s + %s) [dual-pol]" % (
                layers["hv"].name, layers["hh"].name, layers["hv"].name)

    height, width = layers["hv"].shape
    exporter = ExportBackend(dict(config, cog=cog))
    try:
        ds = exporter.create_dataset(str(output_path), width, height,
                                     "Float32", georef, nodata=np.nan)
    except RuntimeError as exc:
        # e.g. GDAL missing in standalone Python: fail gracefully, never
        # let an environment error escape as an unhandled traceback.
        return ProcessingResult(success=False, error_message=str(exc))
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
        ds = None
    except Exception as exc:
        ds = None
        return ProcessingResult(success=False, error_message=str(exc))

    return ProcessingResult(
        success=True,
        output_paths=[str(output_path)],
        metadata={"index": index_id, "formula": formula,
                  "dtype": "Float32", "tile_size": tile_size,
                  "frequency": frequency},
    )


def _compute_tile(backend: NumpyProcessingBackend, reader, handle: ProductHandle,
                  layers: Dict[str, LayerInfo], index_id: str,
                  window: Tuple[int, int, int, int]) -> np.ndarray:
    """Compute one tile of the requested index (linear gamma0 in)."""
    def read(key):
        layer = layers[key]
        data = np.asarray(
            reader.read_window(handle, layer.layer_id or layer.name, window),
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
