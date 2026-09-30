# -*- coding: utf-8 -*-
"""
A2: GDAL netCDF workaround reader (for GDAL < 3.13 / QGIS 3.28 LTR).

NISAR HDF5 files are CF-compliant, so the GDAL netCDF driver can expose
their subdatasets. Two opening strategies (AGENTS.md §2.3):

  1. ``NETCDF:"<path>.h5"`` prefix (no file modification);
  2. ``.nc`` symlink/copy in the temp dir (fallback, never modifies
     the original file).

NOTE (unverified): whether strategy 1 works with a plain ``.h5`` depends
on the GDAL build; see docs/product_notes.md.
"""
import logging
import os
import shutil
import tempfile
from typing import Tuple, Dict, Any, Optional, List

from .base import BaseReader, ReaderRegistry
from . import gdal_common as GC
from ..models import ProductHandle, DataStatus

logger = logging.getLogger("nisar.readers.a2")


class A2NetCDFWorkaroundReader(BaseReader):
    """GDAL netCDF workaround for older GDAL versions (3.x < 3.13)."""

    BACKEND_ID = "A2_netcdf_workaround"
    BACKEND_NAME = "GDAL netCDF workaround (< 3.13)"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self._temp_files: List[str] = []

    # ------------------------------------------------------------ availability
    @classmethod
    def check_availability(cls) -> Tuple[bool, str]:
        if not GC.GDAL_AVAILABLE:
            return False, "GDAL (osgeo) not available in this Python environment"
        version = GC.gdal_version()
        if version < (3, 0, 0):
            return False, "GDAL %d.%d.%d < 3.0" % version
        if not GC.has_driver("netCDF"):
            return False, "GDAL netCDF driver not available"
        return True, ""

    @classmethod
    def can_open(cls, path: str) -> bool:
        available, _ = cls.check_availability()
        if not available:
            return False
        if not os.path.exists(path) and not str(path).startswith(
                ("/vsicurl/", "/vsis3/", "/vsi")):
            return False
        return True

    # ------------------------------------------------------------------- open
    def open(self, path: str) -> ProductHandle:
        if not GC.GDAL_AVAILABLE:
            raise RuntimeError("GDAL is not available")
        GC.apply_pam_config(self.config)

        ds = None
        used_method = ""

        # Strategy 1: NETCDF: prefix — does not touch the original file.
        try:
            ds = GC.gdal.Open('NETCDF:"%s"' % path, GC.gdal.GA_ReadOnly)
            if ds is not None:
                used_method = "NETCDF: prefix"
        except Exception as exc:
            logger.debug("NETCDF: prefix failed for %s: %s", path, exc)

        # Strategy 2: .nc symlink (or copy when symlinks unavailable).
        if ds is None:
            nc_path = self._create_nc_link(path)
            if nc_path:
                try:
                    ds = GC.gdal.Open(nc_path, GC.gdal.GA_ReadOnly)
                    if ds is not None:
                        used_method = ".nc link (%s)" % nc_path
                except Exception as exc:
                    logger.debug("Open via .nc link failed: %s", exc)

        if ds is None:
            raise RuntimeError(
                "Failed to open %s with the netCDF workaround "
                "(NETCDF: prefix and .nc link both failed)" % path)

        try:
            subds_cache: Dict[str, Any] = {}
            layers = GC.extract_layers_from_dataset(ds, subds_cache)
            georef = GC.georef_from_dataset(ds)

            handle = ProductHandle(
                source_path=path,
                reader_backend=self.BACKEND_ID,
                layers=layers,
                georef=georef,
                metadata={
                    "open_method": used_method,
                    "temp_files": list(self._temp_files),
                },
                product_type=self._guess_product_type(path),
                data_status=DataStatus.UNKNOWN,
            )
            handle._dataset = ds
            handle._subds_cache = subds_cache
            logger.debug("A2 opened %s via %s (%d layers)",
                         path, used_method, len(layers))
            return handle
        except Exception:
            del ds
            self._cleanup_temp()
            raise

    # ---------------------------------------------------------------- helpers
    def _create_nc_link(self, path: str) -> Optional[str]:
        """Symlink (fallback: copy) the .h5 as .nc in the temp dir."""
        if not str(path).lower().endswith((".h5", ".hdf5", ".he5")):
            return None
        temp_dir = self.config.get("temp_dir") or tempfile.gettempdir()
        try:
            os.makedirs(temp_dir, exist_ok=True)
        except OSError:
            temp_dir = tempfile.gettempdir()

        basename = os.path.basename(path)
        nc_name = (basename.rsplit(".", 1)[0]) + ".nc"
        nc_path = os.path.join(str(temp_dir), nc_name)

        try:
            if os.path.lexists(nc_path):
                os.remove(nc_path)
            os.symlink(os.path.abspath(path), nc_path)
            self._temp_files.append(nc_path)
            return nc_path
        except (OSError, NotImplementedError):
            # Windows without symlink rights: copy the file (large!).
            logger.warning(
                "Symlink unavailable — copying %s to %s (this can take a "
                "while for multi-GB products)", basename, nc_path)
            try:
                shutil.copy2(path, nc_path)
                self._temp_files.append(nc_path)
                return nc_path
            except Exception as exc:
                logger.error("Copy fallback failed: %s", exc)
                return None

    def _cleanup_temp(self):
        for f in self._temp_files:
            try:
                if os.path.lexists(f):
                    os.remove(f)
            except OSError:
                pass
        self._temp_files.clear()

    @staticmethod
    def _guess_product_type(path: str) -> Optional[str]:
        upper = os.path.basename(path).upper()
        for product in ("GCOV", "GSLC", "RSLC"):
            if product in upper:
                return product
        return None

    # ---------------------------------------------------------- read/close
    def read_window(self, handle: ProductHandle, layer_name: str,
                    window: Tuple[int, int, int, int]):
        return GC.read_window_cached(handle, layer_name, window)

    def close(self, handle: ProductHandle):
        GC.close_cached(handle)
        temp_files = handle.metadata.get("temp_files", [])
        for f in temp_files:
            try:
                if os.path.lexists(f):
                    os.remove(f)
            except OSError:
                pass
        self._cleanup_temp()


ReaderRegistry.register(A2NetCDFWorkaroundReader)
