# -*- coding: utf-8 -*-
"""Unit tests for known GCOV layer constants (product_layers)."""
from nisar_qgis.nisar_core.readers import product_layers as PL
from nisar_qgis.nisar_core.models import Polarization


def test_covariance_terms_per_spec():
    # JPL D-102274 §5.3: 6 real diagonal + 7 complex off-diagonal terms.
    assert set(PL.GCOV_REAL_COVARIANCE_TERMS) == {
        "HHHH", "HVHV", "VHVH", "VVVV", "RHRH", "RVRV"}
    assert set(PL.GCOV_COMPLEX_COVARIANCE_TERMS) == {
        "HHHV", "HHVH", "HHVV", "HVVH", "HVVV", "VHVV", "RHRV"}
    assert len(PL.GCOV_ALL_COVARIANCE_TERMS) == 13


def test_aux_layers():
    assert set(PL.GCOV_AUX_LAYERS) == {
        "mask", "numberOfLooks", "rtcGammaToSigmaFactor"}


def test_polarization_mapping():
    assert PL.polarization_from_layer_name("HVHV") is Polarization.HVHV
    assert PL.polarization_from_layer_name("hhhh") is Polarization.HHHH
    assert PL.polarization_from_layer_name(
        "/science/LSAR/GCOV/grids/frequencyA/VVVV") is Polarization.VVVV
    assert PL.polarization_from_layer_name("RHRH") is None  # compact pol
    assert PL.polarization_from_layer_name("") is None


def test_layer_name_reverse_mapping():
    assert PL.layer_name_from_polarization(Polarization.HVHV) == "HVHV"
    assert PL.layer_name_from_polarization(Polarization.HHHH) == "HHHH"


def test_path_builders():
    assert PL.gcov_grid_group() == "/science/LSAR/GCOV/grids/frequencyA"
    assert PL.gcov_grid_group("SSAR", "frequencyB") == \
        "/science/SSAR/GCOV/grids/frequencyB"
    assert PL.gcov_layer_path("HVHV") == \
        "/science/LSAR/GCOV/grids/frequencyA/HVHV"


def test_identification_path():
    assert PL.IDENTIFICATION_PATH.format(instrument="LSAR") == \
        "/science/LSAR/identification"
    assert "granuleId" in PL.IDENTIFICATION_FIELDS
    assert "compositeReleaseId" in PL.IDENTIFICATION_FIELDS


def test_is_gcov_layer_name():
    assert PL.is_gcov_layer_name("HHHH")
    assert PL.is_gcov_layer_name("mask")
    assert not PL.is_gcov_layer_name("whatever")
