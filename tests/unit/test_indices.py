# -*- coding: utf-8 -*-
"""Unit tests for vegetation index computation (windowed mode)."""
import numpy as np
import pytest

from nisar_qgis.nisar_core.readers import ReaderRegistry
from nisar_qgis.nisar_core.processing.indices import (
    NumpyProcessingBackend, compute_hv_db, compute_cross_ratio, compute_rvi,
    compute_index_to_raster,
)

from conftest import H, W, _arr_hhhh, _arr_hvhv, _arr_vvvv


@pytest.fixture
def dual_handle(gcov_dual):
    handle = ReaderRegistry.open(gcov_dual)
    yield handle
    ReaderRegistry.close(handle)


@pytest.fixture
def full_handle(gcov_full):
    handle = ReaderRegistry.open(gcov_full)
    yield handle
    ReaderRegistry.close(handle)


def test_hv_db_values(dual_handle):
    result = compute_hv_db(dual_handle, window=(0, 0, W, H))
    expected = 10.0 * np.log10(_arr_hvhv().astype(np.float64))
    np.testing.assert_allclose(result.data, expected, rtol=1e-5)
    assert result.units == "dB"
    assert "log10" in result.formula_used


def test_hv_db_zero_protection(dual_handle):
    result = compute_hv_db(dual_handle, window=(0, 0, W, H))
    # no +/-inf anywhere — zeros/negatives become NaN
    assert np.all(np.isfinite(result.data) | np.isnan(result.data))


def test_cross_ratio_values(dual_handle):
    result = compute_cross_ratio(dual_handle, window=(0, 0, W, H))
    expected = (10.0 * np.log10(_arr_hvhv().astype(np.float64))
                - 10.0 * np.log10(_arr_hhhh().astype(np.float64)))
    np.testing.assert_allclose(result.data, expected, rtol=1e-5)


def test_cross_ratio_requires_layers(full_handle):
    # Sanity: works on full-pol too (HHHH+HVHV present).
    result = compute_cross_ratio(full_handle, window=(0, 0, 8, 8))
    assert result.data.shape == (8, 8)


def test_rvi_dual_formula(dual_handle):
    result = compute_rvi(dual_handle, window=(0, 0, W, H))
    hv = _arr_hvhv().astype(np.float64)
    hh = _arr_hhhh().astype(np.float64)
    expected = 4.0 * hv / (hh + hv)
    np.testing.assert_allclose(result.data, expected, rtol=1e-5)
    assert "dual-pol" in result.formula_used


def test_rvi_full_formula(full_handle):
    result = compute_rvi(full_handle, window=(0, 0, W, H))
    hv = _arr_hvhv().astype(np.float64)
    hh = _arr_hhhh().astype(np.float64)
    vv = _arr_vvvv().astype(np.float64)
    expected = 8.0 * hv / (hh + vv + 2.0 * hv)
    np.testing.assert_allclose(result.data, expected, rtol=1e-5)
    assert "full-pol" in result.formula_used


def test_rvi_requires_hv(dual_handle, monkeypatch):
    # Remove HVHV layers -> clear error, no crash.
    monkeypatch.setattr(dual_handle, "layers",
                        [l for l in dual_handle.layers
                         if l.name != "HVHV"])
    with pytest.raises(ValueError):
        compute_rvi(dual_handle, window=(0, 0, 4, 4))


def test_window_reads_are_consistent(dual_handle):
    backend = NumpyProcessingBackend({})
    full = backend.compute_hv_db(dual_handle, window=(0, 0, W, H))
    part = backend.compute_hv_db(dual_handle, window=(8, 4, 10, 12))
    np.testing.assert_allclose(
        part.data, full.data[4:16, 8:18], rtol=1e-5)


def test_tiled_compute_to_raster_needs_gdal(dual_handle, tmp_path):
    """Tiled path requires GDAL for writing — clear error without it."""
    from nisar_qgis.nisar_core.processing import export as export_mod
    if export_mod.GDAL_AVAILABLE:
        pytest.skip("GDAL present — covered by QGIS integration tests")
    result = compute_index_to_raster(
        dual_handle, "hv_db", str(tmp_path / "out.tif"))
    assert not result.success
    assert "GDAL" in result.error_message or "georef" in result.error_message
