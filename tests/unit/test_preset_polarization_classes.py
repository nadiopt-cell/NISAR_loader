# -*- coding: utf-8 -*-
"""
WP-2: polarization-independent presets (F2) + ProductType contract (F13).

Matrix over polarization sets:
  {HHHH, HVHV}          H-transmit dual-pol     -> MVP presets available
  {VHVH, VVVV}          V-transmit dual-pol     -> MVP presets available
  {HHHH, HVHV, VHVH, VVVV} full-pol             -> + polarimetry presets
  {HHHH}                co-pol only             -> cross-pol presets ARE NOT
  {HVHV}                cross-pol only          -> co-pol presets ARE NOT
"""
import pytest

from nisar_qgis.nisar_core.models import (
    LayerInfo, Polarization, ProductHandle, ProductType, SceneRecord,
    ProductLevel, Instrument, DataStatus,
)
from nisar_qgis.nisar_core.presets import (
    get_preset, polarizations_of,
)


def make_handle(names):
    """ProductHandle from polarization VALUE strings (synthetic layers)."""
    layers = [
        LayerInfo(name=n, path="/grids/frequencyA/%s" % n,
                  description=n,
                  polarization=Polarization(n))
        for n in names
    ]
    return ProductHandle(source_path="synthetic.h5",
                         reader_backend="test", layers=layers)


MVP = ("hv_db", "cross_ratio", "rvi")
FULL_POL_PRESETS = ("pauli_rgb", "freeman_durden", "h_a_alpha")


# ------------------------------------------------- polarization matrix
def test_h_transmit_dual_pol():
    handle = make_handle(("HHHH", "HVHV"))
    for preset_id in MVP:
        ok, reason = get_preset(preset_id).check_availability(handle)
        assert ok, "%s: %s" % (preset_id, reason)


def test_v_transmit_dual_pol_is_fully_supported():
    """F2: VHVH+VVVV granules (real UR clone) must pass, not gray out."""
    handle = make_handle(("VHVH", "VVVV"))
    for preset_id in MVP:
        ok, reason = get_preset(preset_id).check_availability(handle)
        assert ok, "%s: %s" % (preset_id, reason)


def test_full_pol_set():
    handle = make_handle(("HHHH", "HVHV", "VHVH", "VVVV"))
    for preset_id in MVP:
        ok, _ = get_preset(preset_id).check_availability(handle)
        assert ok
    for preset_id in FULL_POL_PRESETS:
        ok, reason = get_preset(preset_id).check_availability(handle)
        assert ok, "%s: %s" % (preset_id, reason)


def test_co_pol_only_lacks_cross_pol():
    handle = make_handle(("HHHH",))
    ok, reason = get_preset("hv_db").check_availability(handle)
    assert not ok and "cross-pol" in reason
    ok, reason = get_preset("rvi").check_availability(handle)
    assert not ok and "cross-pol" in reason


def test_cross_pol_only_lacks_co_pol():
    handle = make_handle(("HVHV",))
    ok, reason = get_preset("hv_db").check_availability(handle)
    assert ok, reason  # cross-pol is all hv_db needs
    ok, reason = get_preset("cross_ratio").check_availability(handle)
    assert not ok and "co-pol" in reason
    ok, reason = get_preset("rvi").check_availability(handle)
    assert not ok and "co-pol" in reason


def test_reason_lists_what_was_found():
    handle = make_handle(("HHHH",))
    ok, reason = get_preset("hv_db").check_availability(handle)
    assert "HHHH" in reason


# --------------------------------------------------- robustness (WP-2)
def test_availability_never_crashes_on_missing_handle():
    for preset_id in MVP + FULL_POL_PRESETS:
        ok, reason = get_preset(preset_id).check_availability(None)
        assert not ok and reason


def test_availability_never_crashes_without_layers():
    handle = ProductHandle(source_path="x.h5", reader_backend="test")
    for preset_id in MVP:
        ok, reason = get_preset(preset_id).check_availability(handle)
        assert not ok and reason


def test_real_v_dual_granule_has_full_preset_coverage(gcov_ur_vdual):
    from nisar_qgis.nisar_core.readers import ReaderRegistry
    handle = ReaderRegistry.open(gcov_ur_vdual)
    try:
        assert polarizations_of(handle) == {"VHVH", "VVVV"}
        for preset_id in MVP:
            ok, reason = get_preset(preset_id).check_availability(handle)
            assert ok, "%s: %s" % (preset_id, reason)
    finally:
        ReaderRegistry.close(handle)


# --------------------------------------------- ProductType contract F13
def test_product_type_values():
    for value in ("GCOV", "GSLC", "RSLC", "GUNW"):
        assert ProductType(value).value == value


def test_handle_coerces_legacy_string_product_type():
    handle = ProductHandle(source_path="x.h5", reader_backend="test",
                           product_type="GCOV")
    assert handle.product_type is ProductType.GCOV


def test_handle_uncoercible_product_type_stays_none():
    handle = ProductHandle(source_path="x.h5", reader_backend="test",
                           product_type="NOT_A_PRODUCT")
    assert handle.product_type is None


def test_scene_record_coerces_string_product_type():
    scene = SceneRecord(
        scene_id="s", product_type="gcov", level=ProductLevel.L2,
        instrument=Instrument.LSAR, status=DataStatus.PROVISIONAL,
        acquisition_time=None, footprint_wkt="POLYGON EMPTY",
        size_bytes=0, urls={}, polarizations=[], mode="dual-pol")
    assert scene.product_type is ProductType.GCOV


def test_a1_guess_returns_product_type_enum():
    a1 = pytest.importorskip(
        "nisar_qgis.nisar_core.readers.a1_native",
        reason="a1 needs the gdal_common import chain")
    guess = a1.A1NativeReader._guess_product_type
    assert guess(
        "/x/NISAR_L2_PR_GCOV_031_134_D_052_4005_DHDH_A_001.h5") \
        is ProductType.GCOV
    assert guess("/x/NISAR_L1_PR_GSLC_001.h5") is ProductType.GSLC
    assert guess("/x/NISAR_L2_PR_GUNW_001.h5") is ProductType.GUNW
    assert guess("/x/something_else.h5") is None


def test_a2_guess_returns_product_type_enum():
    a2 = pytest.importorskip(
        "nisar_qgis.nisar_core.readers.a2_netcdf_workaround",
        reason="a2 needs the gdal_common import chain")
    guess = a2.A2NetCDFWorkaroundReader._guess_product_type
    assert guess("/x/NISAR_L2_PR_GCOV_001.h5") is ProductType.GCOV
    assert guess("/x/unknown.h5") is None
