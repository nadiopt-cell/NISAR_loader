# -*- coding: utf-8 -*-
"""Unit tests for the preset registry and availability checks."""
import pytest

from nisar_qgis.nisar_core.readers import ReaderRegistry
from nisar_qgis.nisar_core.presets import (
    PRESETS, get_preset, list_presets, PresetCategory,
)

EXPECTED_PRESETS = {
    "hv_db", "cross_ratio", "rvi", "timeseries", "change_db", "speckle",
    "pauli_rgb", "freeman_durden", "h_a_alpha",
}

MVP_PRESETS = {"hv_db", "cross_ratio", "rvi"}


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


def test_registry_contains_all_presets():
    assert set(PRESETS.keys()) == EXPECTED_PRESETS


def test_every_preset_has_complete_fields():
    for preset in PRESETS.values():
        assert preset.id
        assert preset.category in PresetCategory
        for key in (preset.name_key, preset.hint_key, preset.purpose_key,
                    preset.when_to_use_key, preset.how_to_read_key,
                    preset.formula_key, preset.caveats_key):
            assert key and key.startswith("preset.")
        assert preset.requirements is not None
        assert preset.output is not None
        assert preset.algorithm_name.startswith("nisar:")


def test_mvp_presets_algorithm_names():
    assert get_preset("hv_db").algorithm_name == "nisar:hv_db"
    assert get_preset("cross_ratio").algorithm_name == "nisar:cross_ratio"
    assert get_preset("rvi").algorithm_name == "nisar:rvi"


def test_list_presets_sorted():
    ids = [p.id for p in list_presets()]
    assert ids == sorted(ids)


# ------------------------------------------------------- availability
def test_hv_db_available_on_dual(dual_handle):
    ok, reason = get_preset("hv_db").check_availability(dual_handle)
    assert ok, reason


def test_cross_ratio_available_on_dual(dual_handle):
    ok, reason = get_preset("cross_ratio").check_availability(dual_handle)
    assert ok, reason


def test_rvi_available_on_dual(dual_handle):
    ok, reason = get_preset("rvi").check_availability(dual_handle)
    assert ok, reason


def test_full_pol_presets_unavailable_on_dual(dual_handle):
    for preset_id in ("pauli_rgb", "freeman_durden", "h_a_alpha"):
        ok, reason = get_preset(preset_id).check_availability(dual_handle)
        assert not ok
        assert reason  # a visible reason, not silence


def test_full_pol_presets_available_on_full(full_handle):
    for preset_id in ("pauli_rgb", "freeman_durden", "h_a_alpha"):
        ok, reason = get_preset(preset_id).check_availability(full_handle)
        assert ok, reason


def test_no_handle():
    ok, reason = get_preset("hv_db").check_availability(None)
    assert not ok and reason


def test_wrong_product_type(dual_handle):
    from nisar_qgis.nisar_core.models import ProductType
    dual_handle.product_type = ProductType.RSLC
    ok, reason = get_preset("hv_db").check_availability(dual_handle)
    assert not ok
    assert "not supported" in reason
