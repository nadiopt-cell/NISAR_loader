# -*- coding: utf-8 -*-
"""
_FillValue -> NaN mapping on export (WP-8, live acceptance 17.10.2026).

Real GCOV products use _FillValue = NaN; a plain "tile == fill"
comparison is a no-op then (NaN != NaN). Found while checking the
-136-dB tail of a real 2.08 GB granule; the mapping is now an
explicit helper, both fill kinds are locked by tests here.
"""
import numpy as np
import pytest

from nisar_qgis.nisar_core.processing.export import (
    ExportBackend, apply_fill_nodata)


def test_finite_fill_mapped_to_nan():
    tile = np.array([[1.0, 0.0], [3.0, 4.0]], dtype=np.float32)
    out = apply_fill_nodata(tile, 0.0)
    assert np.isnan(out[0, 1])
    assert out[0, 0] == 1.0 and out[1, 0] == 3.0 and out[1, 1] == 4.0


def test_nan_fill_all_nan_pixels_stay_nan():
    tile = np.array([[1.5, np.nan], [0.0, 2.5]], dtype=np.float32)
    out = apply_fill_nodata(tile, np.nan)
    assert np.isnan(out[0, 1])
    assert out[0, 0] == 1.5 and out[1, 0] == 0.0 and out[1, 1] == 2.5


def test_none_and_disabled_are_passthrough():
    tile = np.array([[1.0, 0.0]], dtype=np.float32)
    assert np.array_equal(apply_fill_nodata(tile, None), tile)
    assert np.array_equal(apply_fill_nodata(tile, 0.0, apply_mask=False), tile)


@pytest.mark.skipif(
    not __import__("nisar_qgis.nisar_core.processing.export",
                   fromlist=["GDAL_AVAILABLE"]).GDAL_AVAILABLE,
    reason="osgeo not installed (runs inside QGIS / conda-gdal envs)")
def test_e2e_finite_fill_via_a3(gcov_dual, tmp_path):
    """End-to-end: finite _FillValue pixel -> NaN in the exported GeoTIFF."""
    import h5py
    with h5py.File(str(gcov_dual), "r+") as f:
        hvhv = f["/science/LSAR/GCOV/grids/frequencyA/HVVH"]
        hvhv.attrs.modify("_FillValue", np.float32(0.0))
        data = hvhv[:, :]
        data[5, 5] = 0.0              # one fill pixel in-scene
        hvhv[:, :] = data

    from nisar_qgis.nisar_core.readers.a3_h5py import A3H5PyReader
    reader = A3H5PyReader({})
    handle = reader.open(str(gcov_dual))
    try:
        layer = handle.get_layer("HVHV")
        assert layer.no_data_value == 0.0
        out = str(tmp_path / "hvhv.tif")
        res = ExportBackend({}).export_layer(handle, "HVHV", out)
        assert res.success, res.error_message
    finally:
        reader.close(handle)

    from osgeo import gdal
    ds = gdal.Open(out)
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray()
    assert np.isnan(arr[5, 5])       # the fill pixel became NaN
    assert np.isfinite(arr[5, 6])    # neighbours preserved
    del ds
