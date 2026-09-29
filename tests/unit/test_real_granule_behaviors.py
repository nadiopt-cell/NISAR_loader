# -*- coding: utf-8 -*-
"""
Real-granule behaviours reproduced on synthetic clones (regression guards).

These tests mirror a REAL NISAR GCOV granule downloaded from ASF on
2026-09-30 (NISAR_L2_UR_GCOV_031_151_A_011_0005_NADV_A_..._P05023_F_P_J_
001.h5, 251.7 MB, sha256 7bd1093efa07...):

  * frequencyB grid (not frequencyA) with V-dual-pol (VHVH + VVVV);
  * NEGATIVE yCoordinateSpacing (north-up grid, y descending);
  * identification fields stored as scalar DATASETS (not attributes);
  * compositeReleaseId P05023 -> PROVISIONAL status;
  * vegetation indices must work with the V-transmit orientation.
"""
import numpy as np
import pytest

from nisar_qgis.nisar_core.readers.a3_h5py import A3H5PyReader
from nisar_qgis.nisar_core.models import DataStatus, Polarization
from nisar_qgis.nisar_core.processing.indices import (
    NumpyProcessingBackend, VegetationIndex,
    compute_hv_db, compute_cross_ratio, compute_rvi,
)


@pytest.fixture()
def ur_handle(gcov_ur_vdual):
    reader = A3H5PyReader({})
    handle = reader.open(gcov_ur_vdual)
    yield handle
    reader.close(handle)


# --------------------------------------------------------------- georef
class TestRealGeoref:
    def test_negative_y_spacing_is_valid(self, ur_handle):
        """Real products store signed spacing; georef must still be valid."""
        geo = ur_handle.georef
        assert geo is not None and geo.is_valid, geo.warnings if geo else None

    def test_north_up_transform(self, ur_handle):
        geo = ur_handle.georef
        assert geo.transform[5] < 0          # yres negative = north-up
        assert abs(geo.transform[1] - 10.0) < 1e-9   # |dx| from signed value

    def test_epsg_32605(self, ur_handle):
        assert ur_handle.georef.crs_authid == "EPSG:32605"
        assert "UTM zone 5N" in ur_handle.georef.crs_wkt

    def test_transform_uses_pixel_centers(self, ur_handle):
        # x0 center = 400000 -> GDAL origin 400000 - 10/2 = 399995
        assert abs(ur_handle.georef.transform[0] - 399995.0) < 1e-6
        # y0 center = 5000000 (descending) -> origin 5000000 + 10/2
        assert abs(ur_handle.georef.transform[3] - 5000005.0) < 1e-6


# --------------------------------------------------------------- layers
class TestVDualLayers:
    def test_layers_discovered(self, ur_handle):
        names = {layer.name for layer in ur_handle.layers}
        assert {"VHVH", "VVVV", "mask"} <= names
        assert "HHHH" not in names and "HVHV" not in names

    def test_polarizations_mapped(self, ur_handle):
        pols = {layer.name: layer.polarization for layer in ur_handle.layers}
        assert pols["VHVH"] is Polarization.VHVH
        assert pols["VVVV"] is Polarization.VVVV


# --------------------------------------------------------------- status
class TestRealStatus:
    def test_provisional_from_crid(self, ur_handle):
        assert ur_handle.data_status is DataStatus.PROVISIONAL
        assert ur_handle.metadata["data_status"] == "PROVISIONAL"

    def test_identification_datasets_read(self, ur_handle):
        ident = ur_handle.metadata["identification"]
        assert ident["productType"] == "GCOV"
        assert ident["productLevel"] == "L2"
        assert ident["compositeReleaseId"] == "P05023"
        assert ident["lookDirection"] == "Left"
        assert ident["trackNumber"] == 151

    def test_beta_crid(self, gcov_ur_vdual, tmp_path):
        """CRID B... must map to BETA."""
        import h5py
        path = str(tmp_path / "beta.h5")
        with h5py.File(gcov_ur_vdual, "r") as src, \
                h5py.File(path, "w") as dst:
            src.copy("science", dst)
        with h5py.File(path, "r+") as f:
            f["/science/LSAR/identification/compositeReleaseId"][()] = "B05021"
        handle = A3H5PyReader({}).open(path)
        assert handle.data_status is DataStatus.BETA


# --------------------------------------------------------------- indices
class TestVDualIndices:
    def test_hv_db_uses_vhvh(self, ur_handle):
        result = compute_hv_db(ur_handle)
        assert "VHVH" in result.formula_used
        assert np.isfinite(result.data).any()
        finite = result.data[np.isfinite(result.data)]
        # synthetic VHVH in (0.01^1.2 .. 0.8^1.2) -> dB in (-20, 8)
        assert finite.min() > -25 and finite.max() < 10

    def test_cross_ratio_vhvh_over_vvvv(self, ur_handle):
        result = compute_cross_ratio(ur_handle)
        assert "VHVH" in result.formula_used
        assert "VVVV" in result.formula_used
        # both finite everywhere (synthetic has no NaN)
        assert np.isfinite(result.data).all()

    def test_rvi_dual_pol_v_transmit(self, ur_handle, gcov_ur_vdual):
        result = compute_rvi(ur_handle)
        assert "[dual-pol]" in result.formula_used
        assert "VHVH" in result.formula_used and "VVVV" in result.formula_used
        # NOTE: dual-pol RVI is NOT bounded by 1 — with strong cross-pol
        # it can reach ~2 (real granule: max 3.7). Verify the formula
        # itself instead of a bogus upper bound.
        import h5py
        with h5py.File(gcov_ur_vdual, "r") as f:
            g = f["/science/LSAR/GCOV/grids/frequencyB"]
            cross = np.asarray(g["VHVH"][()], dtype=np.float64)
            co = np.asarray(g["VVVV"][()], dtype=np.float64)
        expected = np.where(
            co + cross > 0, 4.0 * cross / (co + cross), np.nan)
        got = np.asarray(result.data, dtype=np.float64)
        assert np.allclose(got, expected.astype(np.float32), equal_nan=True)
        assert got.min() >= 0.0

    def test_hv_dual_still_works(self, gcov_dual):
        """H-transmit products keep working after the generic rework."""
        reader = A3H5PyReader({})
        handle = reader.open(gcov_dual)
        try:
            result = compute_rvi(handle)
            assert "HVHV" in result.formula_used
            assert "HHHH" in result.formula_used
            assert np.isfinite(result.data).any()
        finally:
            reader.close(handle)

    def test_raster_pipeline_reports_layers(self, ur_handle, tmp_path):
        """compute_index_to_raster fails on missing GDAL with a clear
        message (not an unhandled traceback) — regression guard for the
        production entry point used by GUI/algorithms."""
        from nisar_qgis.nisar_core.processing.indices import (
            compute_index_to_raster)
        result = compute_index_to_raster(
            ur_handle, VegetationIndex.RVI, str(tmp_path / "out.tif"))
        from nisar_qgis.nisar_core.processing.export import GDAL_AVAILABLE
        if GDAL_AVAILABLE:
            assert result.success
        else:
            assert not result.success
            assert "GDAL" in result.error_message
