# -*- coding: utf-8 -*-
"""Unit tests for core data models."""
import pytest

from nisar_qgis.nisar_core.models import (
    DataStatus, ProductType, ProductLevel, Instrument, Polarization,
    LayerInfo, GeorefInfo, ProductHandle, SceneRecord, SearchParameters,
    LayerNotFoundError,
)
from datetime import datetime


def _scene(status=DataStatus.PROVISIONAL):
    return SceneRecord(
        scene_id="NISAR_L2_PR_GCOV_xxx",
        product_type=ProductType.GCOV,
        level=ProductLevel.L2,
        instrument=Instrument.LSAR,
        status=status,
        acquisition_time=datetime(2026, 9, 27),
        footprint_wkt="POLYGON((0 0, 1 0, 1 1, 0 0))",
        size_bytes=123,
        urls={"download": "https://example.org/x.h5"},
        polarizations=[Polarization.HH, Polarization.HV],
        mode="40+5",
    )


def test_scene_status_flags():
    assert _scene(DataStatus.BETA).is_beta
    assert not _scene(DataStatus.BETA).is_provisional
    assert _scene(DataStatus.PROVISIONAL).is_provisional
    assert not _scene(DataStatus.PROVISIONAL).is_beta


def test_scene_short_description():
    desc = _scene().short_description()
    assert "GCOV" in desc and "LSAR" in desc and "PROVISIONAL" in desc


def test_handle_layer_helpers():
    handle = ProductHandle(
        source_path="/tmp/x.h5", reader_backend="A3_h5py",
        product_type=ProductType.GCOV,
        data_status=DataStatus.UNKNOWN)
    handle.layers = [
        LayerInfo(name="HHHH", path="/science/LSAR/GCOV/grids/frequencyA/HHHH",
                  description="HHHH", polarization=Polarization.HHHH),
        LayerInfo(name="HVHV", path="/science/LSAR/GCOV/grids/frequencyA/HVHV",
                  description="HVHV", polarization=Polarization.HVHV),
        LayerInfo(name="mask", path="/science/LSAR/GCOV/grids/frequencyA/mask",
                  description="mask", polarization=None),
    ]
    assert handle.get_layer("HVHV").name == "HVHV"
    assert handle.get_layer("/frequencyA/HHHH").name == "HHHH"
    assert handle.get_layer("frequencyA/HHHH").layer_id == "frequencyA/HHHH"
    # WP-1: missing keys raise instead of silently returning None (F14)
    with pytest.raises(LayerNotFoundError):
        handle.get_layer("nope")
    # partial names must NOT match longer layer names (F14)
    with pytest.raises(LayerNotFoundError):
        handle.get_layer("HH")
    assert handle.available_polarizations() == {Polarization.HHHH,
                                                Polarization.HVHV}
    assert len(handle.layers_with_polarization(Polarization.HVHV)) == 1
    assert handle.list_layers() == handle.layers


def test_search_parameters_defaults():
    params = SearchParameters()
    assert params.product_types == [ProductType.GCOV]
    assert params.instruments == [Instrument.LSAR]
    assert params.max_results == 100


def test_georef_info_defaults():
    georef = GeorefInfo(crs_wkt="", crs_authid="EPSG:32633",
                        transform=[0, 1, 0, 0, 0, -1], width=10, height=5,
                        bbox=(0, 0, 10, 5))
    assert georef.is_valid is True
    assert georef.warnings == []
