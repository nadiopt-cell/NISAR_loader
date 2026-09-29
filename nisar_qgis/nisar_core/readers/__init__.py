# -*- coding: utf-8 -*-
"""
Reader backends package.

A1/A2 need GDAL (optional), A3 needs h5py (optional). Whatever is missing
is skipped with a log message — ``check_availability`` reports the reason
and a pip install hint (TZ P1 dependencies note).
"""
import logging

from .base import BaseReader, ReaderRegistry
from . import product_layers as product_layers

logger = logging.getLogger("nisar.readers")

try:
    from .a1_native import A1NativeReader
except Exception as _exc:  # pragma: no cover - GDAL optional
    A1NativeReader = None
    logger.debug("A1 (native GDAL) not importable: %s", _exc)

try:
    from .a2_netcdf_workaround import A2NetCDFWorkaroundReader
except Exception as _exc:  # pragma: no cover - GDAL optional
    A2NetCDFWorkaroundReader = None
    logger.debug("A2 (netCDF workaround) not importable: %s", _exc)

try:
    from .a3_h5py import A3H5PyReader
except Exception as _exc:  # pragma: no cover - h5py optional
    A3H5PyReader = None
    logger.debug("A3 (h5py) not importable: %s", _exc)

try:
    from .a4_gunw import A4GunwH5PyReader
except Exception as _exc:  # pragma: no cover - h5py optional
    A4GunwH5PyReader = None
    logger.debug("A4 (h5py GUNW) not importable: %s", _exc)

__all__ = [
    'BaseReader', 'ReaderRegistry', 'product_layers',
    'A1NativeReader', 'A2NetCDFWorkaroundReader', 'A3H5PyReader',
    'A4GunwH5PyReader',
]
