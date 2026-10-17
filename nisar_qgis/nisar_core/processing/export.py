# -*- coding: utf-8 -*-
"""
V4: Export backend — GeoTIFF/COG export with options.

GDAL is imported lazily: unit tests without GDAL still import this module
and only export-related tests are skipped.
"""
import logging
from typing import Optional, Dict, Any

import numpy as np

try:
    from osgeo import gdal, osr
    gdal.UseExceptions()
    GDAL_AVAILABLE = True
except Exception:  # pragma: no cover - environment specific
    gdal = None
    osr = None
    GDAL_AVAILABLE = False

try:  # optional standalone fallback when osgeo is missing (not used
    import rasterio                     # inside QGIS, where osgeo exists)
    from rasterio.transform import Affine
    RASTERIO_AVAILABLE = True
except Exception:  # pragma: no cover - environment specific
    rasterio = None
    RASTERIO_AVAILABLE = False

from ..models import ProductHandle, GeorefInfo, ProcessingResult

logger = logging.getLogger("nisar.processing.export")

_FLOAT_TYPES = ("Float16", "Float32", "Float64")

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

    def _effective_predictor(self, dtype: str) -> int:
        """PREDICTOR usable for this dtype.

        PREDICTOR=3 (floating-point predictor) is only valid for float
        rasters — GDAL refuses to create e.g. a Byte mask with it
        ("PREDICTOR=3 is only supported with Float16, Float32 or
        Float64", caught live in QGIS 3.44.14 / GDAL 3.13). Integer
        rasters fall back to horizontal differencing (2). The rasterio
        fallback path has always done this; now the GDAL path matches.
        """
        if dtype in _FLOAT_TYPES:
            return self.predictor
        return 2 if self.predictor == 3 else self.predictor

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
            "PREDICTOR=%d" % self._effective_predictor(dtype),
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
            ds = None
        except Exception as exc:
            ds = None
            return ProcessingResult(success=False, error_message=str(exc))

        return ProcessingResult(
            success=True,
            output_paths=[str(output_path)],
            metadata={"format": "GeoTIFF", "cog": bool(self.cog),
                      "dtype": dtype})

    # ------------------------------------------------------------- write
    def write_raster(self, data: np.ndarray, georef: GeorefInfo,
                     output_path, dtype: str = "Float32",
                     nodata: Optional[float] = None) -> ProcessingResult:
        """Write one full-band raster from a numpy array.

        Primary path: osgeo.gdal (always available inside QGIS).
        Fallback: rasterio — lets standalone users (and CI without GDAL)
        run the full windthrow pipeline. Neither available → graceful
        failure with an install hint.
        """
        if data.ndim != 2:
            return ProcessingResult(
                success=False,
                error_message="write_raster expects a 2-D array, got %r"
                              % (data.shape,))
        if GDAL_AVAILABLE:
            nd = nodata if nodata is not None else float("nan")
            return self.export_array(np.asarray(data), georef,
                                     str(output_path), nodata=nd,
                                     dtype=dtype)
        if RASTERIO_AVAILABLE:
            return self._write_raster_rasterio(np.asarray(data), georef,
                                               str(output_path), dtype,
                                               nodata)
        return ProcessingResult(
            success=False,
            error_message=("Neither GDAL (osgeo) nor rasterio is available "
                           "for raster export. Inside QGIS GDAL is always "
                           "bundled; standalone: 'pip install gdal' or "
                           "'pip install rasterio'."))

    def _write_raster_rasterio(self, data: np.ndarray, georef: GeorefInfo,
                               output_path: str, dtype: str,
                               nodata: Optional[float]) -> ProcessingResult:
        """rasterio fallback of write_raster (tiled GTiff + overviews)."""
        dtype_map = {"Byte": "uint8", "UInt16": "uint16",
                     "Int16": "int16", "UInt32": "uint32",
                     "Int32": "int32", "Float32": "float32",
                     "Float64": "float64"}
        r_dtype = dtype_map.get(dtype, "float32")
        ulx, xres, _, uly, _, yres = georef.transform
        transform = Affine.from_gdal(ulx, xres, 0.0, uly, 0.0, yres)
        try:
            profile = dict(
                driver="GTiff", width=data.shape[1], height=data.shape[0],
                count=1, dtype=r_dtype,
                transform=transform,
                crs=(georef.crs_wkt or georef.crs_authid or None),
                compress=self.compress, tiled=True,
                blockxsize=self.block_size, blockysize=self.block_size,
                bigtiff="IF_SAFER" if self.big_tiff == "IF_SAFER"
                else self.big_tiff,
            )
            if r_dtype.startswith("float"):
                profile["predictor"] = self.predictor
            with rasterio.open(output_path, "w", **profile) as dst:
                if nodata is not None:
                    dst.nodata = nodata
                dst.write(data.astype(r_dtype), 1)
                if self.cog:
                    try:
                        from rasterio.enums import Resampling
                        dst.build_overviews(
                            [2, 4, 8, 16],
                            resampling=Resampling.average)
                    except Exception:  # pragma: no cover - cosmetic
                        pass
        except Exception as exc:
            return ProcessingResult(success=False,
                                    error_message="rasterio export failed: "
                                                  "%s" % exc)
        return ProcessingResult(
            success=True, output_paths=[output_path],
            metadata={"format": "GeoTIFF", "writer": "rasterio",
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

        # GUNW products carry two grids (80 m / 20 m): a layer may bring
        # its own georef copy in metadata — prefer it over the handle's.
        georef = handle.georef
        try:
            layer_georef = layer.metadata.get("georef")
        except Exception:  # pragma: no cover - defensive
            layer_georef = None
        if layer_georef is not None and getattr(layer_georef, "is_valid", False):
            georef = layer_georef

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
                                     "Float32", georef, nodata=np.nan)
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
            ds = None
        except Exception as exc:
            ds = None
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
