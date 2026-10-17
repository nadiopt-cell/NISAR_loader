# -*- coding: utf-8 -*-
"""
Unit tests for the A3 (h5py) reader on synthetic GCOV products.

Covers TZ P1.6: open, list_layers, georef, read_window — without QGIS,
without GDAL, without real multi-GB files.
"""
import numpy as np
import pytest

from nisar_qgis.nisar_core.readers import ReaderRegistry
from nisar_qgis.nisar_core.readers.a3_h5py import A3H5PyReader
from nisar_qgis.nisar_core.models import ProductType

from conftest import H, W, X0, Y0, DX, DY, _arr_hhhh, _arr_hvhv


@pytest.fixture
def reader():
    return A3H5PyReader({})


def _open(reader, path):
    handle = reader.open(path)
    yield handle
    reader.close(handle)


# ------------------------------------------------------------------ open
def test_open_detects_product(reader, gcov_dual):
    handle = reader.open(gcov_dual)
    try:
        assert handle.reader_backend == "A3_h5py"
        assert handle.product_type == ProductType.GCOV
        assert "granuleId" in handle.metadata["identification"]
        assert handle.metadata["identification"]["productType"] == "GCOV"
        assert handle.metadata["identification"][
            "compositeReleaseId"] == "P05023"
    finally:
        reader.close(handle)


def test_open_missing_product_group(reader, tmp_path):
    import h5py
    path = tmp_path / "not_nisar.h5"
    with h5py.File(str(path), "w"):
        pass
    with pytest.raises(ValueError):
        reader.open(str(path))


# ------------------------------------------------------------ list_layers
def test_list_layers_dual(reader, gcov_dual):
    handle = reader.open(gcov_dual)
    try:
        names = [l.name for l in handle.layers]
        assert "HHHH" in names and "HVHV" in names
        assert "mask" in names and "numberOfLooks" in names
        assert "VVVV" not in names
        # layers are found by name — TZ P1.4 (no subdataset_N names).
        assert all(not n.startswith("subdataset_") for n in names)
        hvhv = handle.get_layer("HVHV")
        assert hvhv.polarization.value == "HVHV"
        assert hvhv.shape == (H, W)  # (height, width) convention
        assert "gamma0" in hvhv.units
        assert np.isnan(hvhv.no_data_value)
    finally:
        reader.close(handle)


def test_list_layers_full_pol(reader, gcov_full):
    handle = reader.open(gcov_full)
    try:
        names = [l.name for l in handle.layers]
        assert {"HHHH", "HVHV", "VVVV"}.issubset(set(names))
    finally:
        reader.close(handle)


# ----------------------------------------------------------------- georef
def test_georef_valid(reader, gcov_dual):
    handle = reader.open(gcov_dual)
    try:
        georef = handle.georef
        assert georef.is_valid
        assert georef.crs_authid == "EPSG:32633"
        assert "UTM" in georef.crs_wkt
        assert georef.width == W and georef.height == H
        # CF pixel centers -> GDAL edges: ul = (x0-dx/2, y0+dy/2)
        assert georef.transform[0] == pytest.approx(X0 - DX / 2)
        assert georef.transform[1] == pytest.approx(DX)
        assert georef.transform[3] == pytest.approx(Y0 + DY / 2)
        assert georef.transform[5] == pytest.approx(-DY)
        # bbox covers the grid extent
        minx, miny, maxx, maxy = georef.bbox
        assert minx == pytest.approx(X0 - DX / 2)
        assert maxx == pytest.approx(X0 + (W - 0.5) * DX)
        assert maxy == pytest.approx(Y0 + DY / 2)
    finally:
        reader.close(handle)


def test_georef_missing_projection(reader, gcov_no_georef):
    handle = reader.open(gcov_no_georef)
    try:
        georef = handle.georef
        assert not georef.is_valid
        assert georef.crs_authid == ""
        assert any("CRS" in w or "authority" in w for w in georef.warnings)
    finally:
        reader.close(handle)


# ------------------------------------------------------------ read_window
def test_read_window_values(reader, gcov_dual):
    handle = reader.open(gcov_dual)
    try:
        window = (10, 5, 8, 6)  # xoff, yoff, xsize, ysize
        data = reader.read_window(handle, "HVHV", window)
        expected = _arr_hvhv()[5:11, 10:18]
        np.testing.assert_allclose(data, expected, rtol=1e-6)
        assert data.shape == (6, 8)
    finally:
        reader.close(handle)


def test_read_window_full_layer(reader, gcov_dual):
    handle = reader.open(gcov_dual)
    try:
        data = reader.read_window(handle, "HHHH", (0, 0, W, H))
        np.testing.assert_allclose(data, _arr_hhhh(), rtol=1e-6)
    finally:
        reader.close(handle)


def test_read_window_unknown_layer(reader, gcov_dual):
    handle = reader.open(gcov_dual)
    try:
        with pytest.raises(ValueError):
            reader.read_window(handle, "NOPE", (0, 0, 4, 4))
    finally:
        reader.close(handle)


def test_read_window_mask(reader, gcov_dual):
    handle = reader.open(gcov_dual)
    try:
        mask = reader.read_window(handle, "mask", (0, 0, W, H))
        assert mask[0, 0] == 255 and mask[1, 1] == 0
        assert mask[2, 2] == 0
    finally:
        reader.close(handle)


# ------------------------------------------------- subdataset/handle cache
def test_handle_keeps_open_file(reader, gcov_dual):
    """TZ P1.7 — repeated read_window must not reopen the file."""
    handle = reader.open(gcov_dual)
    try:
        h5 = getattr(handle, "_h5_file", None)
        assert h5 is not None
        reader.read_window(handle, "HHHH", (0, 0, 4, 4))
        assert handle._h5_file is h5  # same object, not reopened
        reader.read_window(handle, "HVHV", (0, 0, 4, 4))
        assert handle._h5_file is h5
    finally:
        reader.close(handle)
        assert getattr(handle, "_h5_file", "closed") is None


# ------------------------------------------------------------- registry
def test_registry_lists_all_backends():
    """TZ P0.5 — full backend list is registered."""
    listed = {item["id"]: item for item in ReaderRegistry.list_registered()}
    assert {"A1_native", "A2_netcdf_workaround", "A3_h5py"}.issubset(set(listed))
    for item in listed.values():
        assert item["available"] is False or item["reason"] == ""


def test_registry_auto_open_synthetic(gcov_dual):
    """Registry auto-selection opens the synthetic product with valid georef."""
    handle = ReaderRegistry.open(gcov_dual)
    try:
        assert handle.get_layer("HVHV") is not None
        assert handle.georef is not None and handle.georef.is_valid
    finally:
        ReaderRegistry.close(handle)


def test_registry_close_is_idempotent(gcov_dual):
    handle = ReaderRegistry.open(gcov_dual)
    ReaderRegistry.close(handle)
    ReaderRegistry.close(handle)  # no exception
