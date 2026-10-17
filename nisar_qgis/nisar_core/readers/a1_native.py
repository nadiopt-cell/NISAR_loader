# -*- coding: utf-8 -*-
"""
A1: Native GDAL reader (GDAL >= 3.13, QGIS >= 4.2).

Opens NISAR HDF5 directly via GDAL's built-in NISAR driver.
"""
import logging
import os
from typing import Tuple, Dict, Any, Optional

from .base import BaseReader, ReaderRegistry
from . import gdal_common as GC
from ..models import ProductHandle, DataStatus, ProductType

logger = logging.getLogger("nisar.readers.a1")

REQUIRES_GDAL = (3, 13, 0)


class A1NativeReader(BaseReader):
    """Native GDAL driver for NISAR (GDAL >= 3.13)."""

    BACKEND_ID = "A1_native"
    BACKEND_NAME = "Native GDAL NISAR driver (>= 3.13)"
    REQUIRES_GDAL_VERSION = REQUIRES_GDAL

    @classmethod
    def check_availability(cls) -> Tuple[bool, str]:
        if not GC.GDAL_AVAILABLE:
            return False, "GDAL (osgeo) not available in this Python environment"
        version = GC.gdal_version()
        if version < REQUIRES_GDAL:
            return False, "GDAL %d.%d.%d < 3.13" % version
        if not GC.has_driver("NISAR"):
            return False, "GDAL >= 3.13 but NISAR driver not registered"
        return True, ""

    @classmethod
    def can_open(cls, path: str) -> bool:
        available, _ = cls.check_availability()
        if not available:
            return False
        if not os.path.exists(path) and not str(path).startswith(
                ("/vsicurl/", "/vsis3/", "/vsi")):
            return False
        try:
            ds = GC.gdal.Open(path, GC.gdal.GA_ReadOnly)
        except Exception:
            return False
        if ds is None:
            return False
        del ds
        return True

    def open(self, path: str) -> ProductHandle:
        """Open NISAR product with the native GDAL driver."""
        if not GC.GDAL_AVAILABLE:
            raise RuntimeError("GDAL is not available")
        GC.apply_pam_config(self.config)

        ds = GC.gdal.Open(path, GC.gdal.GA_ReadOnly)
        if ds is None:
            raise RuntimeError("Failed to open %s with native GDAL driver" % path)

        try:
            subds_cache: Dict[str, Any] = {}
            layers = GC.extract_layers_from_dataset(ds, subds_cache)
            georef = GC.georef_from_dataset(ds)

            handle = ProductHandle(
                source_path=path,
                reader_backend=self.BACKEND_ID,
                layers=layers,
                georef=georef,
                metadata={"open_method": "native NISAR driver"},
                product_type=self._guess_product_type(path),
                data_status=DataStatus.UNKNOWN,
            )
            handle._dataset = ds
            handle._subds_cache = subds_cache
            return handle
        except Exception:
            del ds
            raise

    @staticmethod
    def _guess_product_type(path: str) -> Optional[ProductType]:
        """WP-2 (F13): the contract is ProductType, not a raw string."""
        upper = os.path.basename(path).upper()
        for product in ("GCOV", "GSLC", "RSLC", "GUNW"):
            if product in upper:
                return ProductType(product)
        return None

    def read_window(self, handle: ProductHandle, layer_name: str,
                    window: Tuple[int, int, int, int]):
        return GC.read_window_cached(handle, layer_name, window)

    def close(self, handle: ProductHandle):
        GC.close_cached(handle)


ReaderRegistry.register(A1NativeReader)
