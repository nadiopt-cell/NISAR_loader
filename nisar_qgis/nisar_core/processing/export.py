# -*- coding: utf-8 -*-
"""
V4: Export backend — GeoTIFF/COG export with options.

GDAL is imported lazily: unit tests without GDAL still import this module
and only export-related tests are skipped.
"""
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import numpy as np

try:
    from osgeo import gdal, osr
    gdal.UseExceptions()
    GDAL_AVAILABLE = True
except Exception:  # pragma: no cover - environment specific
    gdal = None
    osr = None
    GDAL_AVAILABLE = False

from ..models import ProductHandle, GeorefInfo, ProcessingResult

logger = logging.getLogger("nisar.processing.export")

_GDAL_DTYPES = {
    "Byte": gdal.GDT_Byte if GDAL_AVAILABLE else 1,
    "Int16": gdal.GDT_Int16 if GDAL_AVAILABLE else 3,
    "UInt16": gdal.GDT_UInt16 if GDAL_AVAILABLE else 2,
    "Int32": gdal.GDT_Int32 if GDAL_AVAILABLE else 5,
    "UInt32": gdal.GDT_UInt32 if GDAL_AVAILABLE else 4,
    "Float32": gdal.GDT_Float32 if GDAL_AVAILABLE else 6,
    "Float64": gdal.GDT_Float64 if GDAL_AVAILABLE else 7,
}


def _require_gdal():
    if not GDAL_AVAILABLE:
        raise RuntimeError(
            "GDAL (osgeo) is not available in this Python environment. "
            "Inside QGIS it is always bundled; for standalone use install "
            "GDAL, e.g. 'pip install gdal' or use a conda gdal package.")


class ExportBackend:
    """Export arrays / layers to GeoTIFF or COG."""

    def __init__(self, config: Dict[str, Any] = None):
        if config is None:
            config = {}
        elif not isinstance(config, dict) and hasattr(config, "__dict__"):
            config = vars(config)
        self.config = config or {}
        self.compress = self.config.get("compress", "LZW")
        self.tiled = self.config.get("tiled", True)
        self.block_size = int(self.config.get("block_size", 512))
        self.predictor = int(self.config.get("predictor", 3))  # float data
        self.big_tiff = self.config.get("big_tiff", "IF_SAFER")
        self.cog = self.config.get("cog", False)

    # ------------------------------------------------------------- creation
    def create_dataset(self, output_path: str, width: int, height: int,
                       dtype: str, georef: GeorefInfo,
                       nodata: Optional[float] = None):
        """Create a GDAL dataset for tiled writing. Caller writes + finalize."""
        _require_gdal()
        driver = gdal.GetDriverByName("GTiff")
        if driver is None:
            raise RuntimeError("GTiff driver not available")

        co = [
            "COMPRESS=%s" % self.compress,
            "TILED=%s" % ("YES" if self.tiled else "NO"),
            "BLOCKXSIZE=%d" % self.block_size,
            "BLOCKYSIZE=%d" % self.block_size,
            "PREDICTOR=%d" % self.predictor,
            "BIGTIFF=%s" % self.big_tiff,
        ]
        try:
            ds = driver.Create(str(output_path), int(width), int(height),
                               1, _GDAL_DTYPES.get(dtype, gdal.GDT_Float32), co)
        except Exception as exc:
            raise RuntimeError("Failed to create %s: %s" % (output_path, exc))
        if ds is None:
            raise RuntimeError("Failed to create %s" % output_path)

        if georef is not None and georef.is_valid:
            ds.SetGeoTransform(list(georef.transform))
            if georef.crs_wkt:
                ds.SetProjection(georef.crs_wkt)
            elif georef.crs_authid:
                srs = osr.SpatialReference()
                srs.SetFromUserInput(georef.crs_authid)
                ds.SetProjection(srs.ExportToWkt())
        if nodata is not None:
            try:
                ds.GetRasterBand(1).SetNoDataValue(float(nodata))
            except Exception:  # pragma: no cover
                pass
        return ds

    def finalize(self, ds) -> None:
        """Build overviews / convert to COG and flush the dataset."""
        if self.cog:
            try:
                ds.BuildOverviews("AVERAGE", [2, 4, 8, 16, 32])
            except Exception as exc:  # pragma: no cover
                logger.debug("Overview building failed: %s", exc)
        ds.FlushCache()

    # ------------------------------------------------------------- arrays
    def export_array(self, data: np.ndarray, georef: GeorefInfo,
                     output_path, nodata: float = float("nan"),
                     dtype: str = "Float32", options: Dict = None
                     ) -> ProcessingResult:
        """Export a numpy array to GeoTIFF/COG with georeferencing."""
        try:
            _require_gdal()
        except RuntimeError as exc:
            return ProcessingResult(success=False, error_message=str(exc))

        if data.ndim == 2:
            height, width = data.shape
        elif data.ndim == 3:
            height, width = data.shape[-2:]
        else:
            return ProcessingResult(
                success=False,
                error_message="Unsupported array shape %r" % (data.shape,))

        try:
            ds = self.create_dataset(str(output_path), width, height, dtype,
                                     georef, nodata=nodata)
        except RuntimeError as exc:
            return ProcessingResult(success=False, error_message=str(exc))

        try:
            band = ds.GetRasterBand(1)
            if data.ndim == 2:
                band.WriteArray(data)
            else:
                band.WriteArray(data[..., 0] if data.shape[0] != height
                                else data[0])
            self.finalize(ds)
            del ds
        except Exception as exc:
            del ds
            return ProcessingResult(success=False, error_message=str(exc))

        return ProcessingResult(
            success=True,
            output_paths=[str(output_path)],
            metadata={"format": "GeoTIFF", "cog": bool(self.cog),
                      "dtype": dtype})

    # ------------------------------------------------------------- layers
    def export_layer(self, handle: ProductHandle, layer_name: str,
                     output_path, tile_size: int = 512,
                     progress_callback=None, is_canceled=None,
                     apply_mask: bool = True) -> ProcessingResult:
        """Export one product layer tile-by-tile to Float32 GeoTIFF.

        The source .h5 is only read; NaN/„no data“ values stay NaN.
        """
        from ..readers import ReaderRegistry
        from ..processing.indices import _tile_windows

        layer = handle.get_layer(layer_name)
        if not layer:
            return ProcessingResult(
                success=False,
                error_message="Layer %r not found" % layer_name)
        if handle.georef is None or not handle.georef.is_valid:
            return ProcessingResult(
                success=False,
                error_message=("Cannot export %r: the product has no valid "
                               "georeference" % layer_name))

        try:
            _require_gdal()
        except RuntimeError as exc:
            return ProcessingResult(success=False, error_message=str(exc))
        for backend in ReaderRegistry._backends:
            if backend.BACKEND_ID == handle.reader_backend:
                reader = backend(self.config)
                break
        else:  # pragma: no cover
            return ProcessingResult(success=False,
                                    error_message="Reader backend unavailable")

        height, width = layer.shape
        try:
            ds = self.create_dataset(str(output_path), width, height,
                                     "Float32", handle.georef, nodata=np.nan)
        except RuntimeError as exc:
            return ProcessingResult(success=False, error_message=str(exc))

        fill = layer.no_data_value
        total = sum(1 for _ in _tile_windows(height, width, tile_size))
        done = 0
        try:
            band = ds.GetRasterBand(1)
            for xoff, yoff, xsize, ysize in _tile_windows(height, width,
                                                          tile_size):
                if is_canceled is not None and is_canceled():
                    del ds
                    return ProcessingResult(
                        success=False, error_message="Cancelled by user")
                tile = np.asarray(
                    reader.read_window(handle, layer.name,
                                       (xoff, yoff, xsize, ysize)),
                    dtype=np.float32)
                if tile.ndim == 3:
                    tile = tile[0]
                if apply_mask and fill is not None and np.isfinite(fill):
                    tile = np.where(tile == fill, np.nan, tile)
                band.WriteArray(tile, xoff, yoff)
                done += 1
                if progress_callback is not None:
                    try:
                        progress_callback(int(100.0 * done / max(total, 1)))
                    except Exception:  # pragma: no cover
                        pass
            self.finalize(ds)
            del ds
        except Exception as exc:
            try:
                del ds
            except Exception:  # pragma: no cover
                pass
            return ProcessingResult(success=False, error_message=str(exc))

        return ProcessingResult(
            success=True, output_paths=[str(output_path)],
            metadata={"layer": layer.name, "dtype": "Float32"})

    def export_index_result(self, index_result, georef: GeorefInfo,
                            output_path, dtype: str = "Float32"
                            ) -> ProcessingResult:
        """Export an IndexResult to GeoTIFF."""
        return self.export_array(index_result.data, georef, output_path,
                                 nodata=float("nan"), dtype=dtype)


def export_to_geotiff(data: np.ndarray, georef: GeorefInfo, output_path,
                      config: Dict = None, **kwargs) -> ProcessingResult:
    """Convenience function."""
    return ExportBackend(config).export_array(data, georef, output_path,
                                              **kwargs)
