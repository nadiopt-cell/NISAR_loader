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
from .windthrow import (
    WindthrowParams, GunwPairInfo, PairCompatibility, DcohResult,
    DetectionResult, parse_gunw_pair_info, check_pair_compatibility,
    find_coherence_layer, compute_dcoh, hansen_forest_mask_year,
    resample_fraction, ring_background_mask, detect_windthrow,
    windthrow_metrics, run_windthrow_did, format_metric,
)

__all__ = [
    'ProcessingBackendBase', 'ProcessingRegistry',
    'NumpyProcessingBackend', 'VegetationIndex', 'IndexResult',
    'compute_hv_db', 'compute_cross_ratio', 'compute_rvi',
    'compute_index_to_raster',
    'ExportBackend', 'export_to_geotiff', 'GDAL_AVAILABLE',
    'WindthrowParams', 'GunwPairInfo', 'PairCompatibility', 'DcohResult',
    'DetectionResult', 'parse_gunw_pair_info', 'check_pair_compatibility',
    'find_coherence_layer', 'compute_dcoh', 'hansen_forest_mask_year',
    'resample_fraction', 'ring_background_mask', 'detect_windthrow',
    'windthrow_metrics', 'run_windthrow_did', 'format_metric',
]
