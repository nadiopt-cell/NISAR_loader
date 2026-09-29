# -*- coding: utf-8 -*-
"""
Processing backends package.
"""
from .base import ProcessingBackendBase, ProcessingRegistry
from .indices import (
    NumpyProcessingBackend, VegetationIndex, IndexResult,
    compute_hv_db, compute_cross_ratio, compute_rvi,
    compute_index_to_raster,
)
from .export import ExportBackend, export_to_geotiff, GDAL_AVAILABLE

__all__ = [
    'ProcessingBackendBase', 'ProcessingRegistry',
    'NumpyProcessingBackend', 'VegetationIndex', 'IndexResult',
    'compute_hv_db', 'compute_cross_ratio', 'compute_rvi',
    'compute_index_to_raster',
    'ExportBackend', 'export_to_geotiff', 'GDAL_AVAILABLE',
]
