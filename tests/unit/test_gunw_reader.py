# -*- coding: utf-8 -*-
"""A4 GUNW reader tests on the synthetic pair (layout per real granule)."""
import numpy as np
import pytest

from nisar_qgis.nisar_core.readers import ReaderRegistry
from nisar_qgis.nisar_core.readers.product_layers import (
    gunw_grid_group, gunw_layer_path,
)


@pytest.fixture(scope="module")
def storm_handle(gunw_storm):
    handle = ReaderRegistry.open(gunw_storm)
    yield handle
    ReaderRegistry.close(handle)


def test_gunw_opened_by_a4(storm_handle):
    assert storm_handle.reader_backend == "A4_gunw_h5py"
    assert storm_handle.product_type is not None
    assert storm_handle.product_type.value == "GUNW"
    assert storm_handle.data_status.value == "PROVISIONAL"


def test_gunw_layers(storm_handle):
    names = [layer.name for layer in storm_handle.layers]
    assert "HH_coherenceMagnitude_80m" in names
    assert "HH_unwrappedPhase_80m" in names
    assert "HH_connectedComponents_80m" in names
    assert "HH_coherenceMagnitude_20m" in names
    assert "HH_wrappedInterferogram_20m" in names
    # mask datasets are listed without a pol prefix
    assert any(n.startswith("mask_mask_") for n in names)

    coh = storm_handle.get_layer("HH_coherenceMagnitude_80m")
    assert coh.shape == (64, 48)
    assert coh.polarization is not None and coh.polarization.value == "HH"
    assert coh.metadata["posting_m"] == 80
    assert coh.metadata["dataset"] == "coherenceMagnitude"

    coh20 = storm_handle.get_layer("HH_coherenceMagnitude_20m")
    assert coh20.shape == (64 * 4, 48 * 4)
    assert coh20.metadata["posting_m"] == 20


def test_gunw_georef(storm_handle):
    g = storm_handle.georef
    assert g.is_valid
    assert g.crs_authid == "EPSG:32641"
    assert g.width == 48 and g.height == 64
    assert g.transform[0] == pytest.approx(270000.0 - 40.0)  # ulx = x0 - dx/2
    assert g.transform[1] == pytest.approx(80.0)
    assert g.transform[5] == pytest.approx(-80.0)
    assert g.transform[3] == pytest.approx(1044720.0 + 40.0)


def test_gunw_per_layer_georef(storm_handle):
    coh20 = storm_handle.get_layer("HH_coherenceMagnitude_20m")
    g20 = coh20.metadata.get("georef")
    assert g20 is not None and g20.is_valid
    assert g20.transform[1] == pytest.approx(20.0)
    assert g20.width == 48 * 4


def test_gunw_identification(storm_handle):
    ident = storm_handle.metadata["identification"]
    assert ident["productType"] == "GUNW"
    assert int(ident["trackNumber"]) == 93
    assert int(ident["frameNumber"]) == 58
    assert ident["referenceZeroDopplerStartTime"].startswith("2026-06-20")
    assert ident["secondaryZeroDopplerStartTime"].startswith("2026-07-02")
    assert int(ident["referenceAbsoluteOrbitNumber"]) == 4661
    assert int(ident["secondaryAbsoluteOrbitNumber"]) == 4834

    pair = storm_handle.metadata["pair_info"]
    assert int(pair["trackNumber"]) == 93
    assert int(pair["frameNumber"]) == 58


def test_gunw_read_window(storm_handle):
    reader = storm_handle._h5_reader
    data = reader.read_window(storm_handle, "HH_coherenceMagnitude_80m",
                              (0, 0, 48, 64))
    assert data.shape == (64, 48)
    assert np.isfinite(data).all()
    assert float(data.min()) >= 0.0 and float(data.max()) <= 1.0

    win = reader.read_window(storm_handle, "HH_coherenceMagnitude_80m",
                             (10, 20, 12, 12))
    # the damage block: storm coherence dropped
    assert float(np.median(win)) < 0.45


def test_gunw_control_has_no_damage(gunw_control):
    handle = ReaderRegistry.open(gunw_control)
    try:
        reader = handle._h5_reader
        win = reader.read_window(handle, "HH_coherenceMagnitude_80m",
                                 (10, 20, 12, 12))
        assert float(np.median(win)) > 0.5
    finally:
        ReaderRegistry.close(handle)


def test_product_layers_paths():
    assert gunw_grid_group() == (
        "/science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram")
    assert gunw_layer_path("hh", "coherenceMagnitude") == (
        "/science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/HH/"
        "coherenceMagnitude")
    assert gunw_grid_group(group="wrappedInterferogram") == (
        "/science/LSAR/GUNW/grids/frequencyA/wrappedInterferogram")


def test_gunw_can_open_rejects_gcov(gcov_dual):
    from nisar_qgis.nisar_core.readers import A4GunwH5PyReader
    assert A4GunwH5PyReader.can_open(gcov_dual) is False


def test_registry_lists_a4():
    ids = [b["id"] for b in ReaderRegistry.list_registered()]
    assert "A4_gunw_h5py" in ids
