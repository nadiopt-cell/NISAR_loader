# -*- coding: utf-8 -*-
"""
Export backend creation-option tests.

PREDICTOR regression: PREDICTOR=3 (floating-point predictor) is only
valid for float rasters. The windthrow mask (Byte) export failed with
"Failed to create ... PREDICTOR=3 is only supported with Float16,
Float32 or Float64" in a real QGIS 3.44.14 / GDAL 3.13 run (2026-09-30).
"""
import numpy as np
import pytest

from nisar_qgis.nisar_core.processing.export import ExportBackend
from nisar_qgis.nisar_core.models import GeorefInfo


@pytest.fixture
def georef():
    return GeorefInfo(transform=(400000.0, 80.0, 0.0,
                                 5000000.0, 0.0, -80.0),
                      width=8, height=8, crs_authid="EPSG:32641",
                      crs_wkt="", is_valid=True)


def test_predictor_kept_for_float_rasters():
    be = ExportBackend({})  # default predictor=3 (float data)
    assert be._effective_predictor("Float32") == 3
    assert be._effective_predictor("Float64") == 3
    assert be._effective_predictor("Float16") == 3


def test_predictor_downgraded_for_integer_rasters():
    be = ExportBackend({})  # predictor=3 would be rejected by GDAL
    for dtype in ("Byte", "UInt16", "Int16", "Int32", "UInt32"):
        assert be._effective_predictor(dtype) == 2, dtype


def test_predictor_passthrough_when_not_three():
    be = ExportBackend({"predictor": 1})  # none
    assert be._effective_predictor("Byte") == 1
    assert be._effective_predictor("Float32") == 1
    be = ExportBackend({"predictor": 2})  # horizontal differencing
    assert be._effective_predictor("Byte") == 2
    assert be._effective_predictor("Float32") == 2


@pytest.mark.skipif(
    not __import__("nisar_qgis.nisar_core.processing.export",
                   fromlist=["GDAL_AVAILABLE"]).GDAL_AVAILABLE,
    reason="osgeo not installed (runs inside QGIS / conda-gdal envs)")
def test_byte_mask_export_creates_geotiff(georef, tmp_path):
    """End-to-end: a Byte mask must export without the PREDICTOR error."""
    mask = (np.random.default_rng(0).random((64, 64)) > 0.5).astype(np.uint8)
    out = str(tmp_path / "mask.tif")
    res = ExportBackend({}).write_raster(mask, georef, out, dtype="Byte")
    assert res.success, res.error_message

    from osgeo import gdal
    ds = gdal.Open(out)
    assert ds is not None
    assert ds.RasterXSize == 64 and ds.RasterYSize == 64
    band = ds.GetRasterBand(1)
    assert band.DataType == gdal.GDT_Byte
    del ds
