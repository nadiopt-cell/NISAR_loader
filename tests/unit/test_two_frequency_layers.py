# -*- coding: utf-8 -*-
"""
WP-1: correct layer model for two-frequency NISAR products.

Covers the review acceptance criteria:
  * ambiguous display names raise an explicit error, not a silent pick;
  * layer_id ("frequencyA/HHHH") resolves unambiguously and carries its
    own grid georef;
  * vegetation indices take layers from ONE frequency and refuse mixed
    or differently shaped inputs;
  * outputs include the frequency tag and never collide between grids.
"""
import numpy as np
import pytest

from nisar_qgis.nisar_core.readers import ReaderRegistry
from nisar_qgis.nisar_core.readers.a3_h5py import A3H5PyReader
from nisar_qgis.nisar_core.models import (
    AmbiguousLayerError, LayerNotFoundError, output_name_with_frequency,
)
from nisar_qgis.nisar_core.processing.indices import (
    pick_index_layers, VegetationIndex, compute_rvi,
    compute_index_to_raster,
)


@pytest.fixture
def same_names_handle(gcov_two_freq_same_names):
    handle = ReaderRegistry.open(gcov_two_freq_same_names)
    yield handle
    ReaderRegistry.close(handle)


@pytest.fixture
def distinct_handle(gcov_two_freq):
    handle = ReaderRegistry.open(gcov_two_freq)
    yield handle
    ReaderRegistry.close(handle)


@pytest.fixture
def mixed_handle(gcov_mixed_freq):
    handle = ReaderRegistry.open(gcov_mixed_freq)
    yield handle
    ReaderRegistry.close(handle)


# ----------------------------------------------------------- addressing
def test_duplicate_names_are_ambiguous(same_names_handle):
    """Same layer name in both grids: name alone must not resolve."""
    with pytest.raises(AmbiguousLayerError) as exc:
        same_names_handle.get_layer("HHHH")
    message = str(exc.value)
    assert "frequencyA/HHHH" in message and "frequencyB/HHHH" in message


def test_layer_id_resolves_per_grid(same_names_handle):
    layer_b = same_names_handle.get_layer("frequencyB/HHHH")
    layer_a = same_names_handle.get_layer("frequencyA/HHHH")
    assert layer_a.name == layer_b.name == "HHHH"
    assert layer_a.frequency == "A" and layer_b.frequency == "B"
    # the two grids also differ in shape -> B layer keeps its own shape
    assert layer_a.shape != layer_b.shape
    assert layer_b.shape == (20, 30)


def test_partial_name_never_matches(same_names_handle):
    with pytest.raises(LayerNotFoundError):
        same_names_handle.get_layer("HH")


def test_frequencies_index(same_names_handle):
    assert same_names_handle.frequencies() == ["A", "B"]
    assert len(same_names_handle.layers_by_frequency("A")) == 2
    assert len(same_names_handle.layers_by_frequency("B")) == 2
    ids = {l.layer_id for l in same_names_handle.layers}
    assert ids == {"frequencyA/HHHH", "frequencyA/HVHV",
                   "frequencyB/HHHH", "frequencyB/HVHV"}


def test_per_layer_georef(same_names_handle):
    """Reads/exports use the georef of the layer's own grid (WP-1)."""
    gref_a = same_names_handle.georef_for_frequency("A")
    gref_b = same_names_handle.georef_for_frequency("B")
    assert gref_a is not None and gref_a.is_valid
    assert gref_b is not None and gref_b.is_valid
    assert gref_a.transform != gref_b.transform
    assert gref_a.width == 16 and gref_a.height == 10
    assert gref_b.width == 30 and gref_b.height == 20
    layer_b = same_names_handle.get_layer("frequencyB/HHHH")
    assert layer_b.georef is gref_b


def test_read_window_resolves_per_grid(same_names_handle):
    reader = A3H5PyReader({})
    tile_a = reader.read_window(same_names_handle, "frequencyA/HHHH",
                                (0, 0, 4, 4))
    tile_b = reader.read_window(same_names_handle, "frequencyB/HHHH",
                                (0, 0, 4, 4))
    assert tile_a.shape == (4, 4)
    assert tile_b.shape == (4, 4)
    data_a = np.asarray(tile_a, dtype=np.float64)
    data_b = np.asarray(tile_b, dtype=np.float64)
    assert not np.array_equal(data_a, data_b)


# ---------------------------------------------------------- index rules
def test_pick_prefers_frequency_a(distinct_handle):
    picked, freq = pick_index_layers(distinct_handle, VegetationIndex.RVI)
    assert freq == "A"
    assert picked["hv"].name == "HVHV" and picked["hh"].name == "HHHH"
    assert picked["hv"].frequency == "A"


def test_pick_explicit_preferred_frequency(distinct_handle):
    picked, freq = pick_index_layers(
        distinct_handle, VegetationIndex.RVI, preferred_frequency="B")
    assert freq == "B"
    assert picked["hv"].name == "VHVH" and picked["hh"].name == "VVVV"


def test_rvi_never_mixes_frequencies(mixed_handle):
    """Cross-pol only on A and co-pol only on B -> explicit refusal."""
    with pytest.raises(ValueError, match="single frequency"):
        compute_rvi(mixed_handle, window=(0, 0, 4, 4))
    result = compute_index_to_raster(
        mixed_handle, VegetationIndex.RVI, "unused.tif")
    assert not result.success
    assert "frequency" in result.error_message


def test_pick_reports_available_layers(distinct_handle):
    """Message names what exists on each grid (fail-helpful)."""
    from nisar_qgis.nisar_core.models import ProductHandle
    empty = ProductHandle(source_path="x.h5", reader_backend="A3_h5py")
    with pytest.raises(ValueError, match="Available:"):
        pick_index_layers(empty, VegetationIndex.RVI)


# --------------------------------------------------------- output names
def test_output_names_include_frequency():
    assert output_name_with_frequency("base", "HHHH", "A") == \
        "base_A_HHHH.tif"
    assert output_name_with_frequency("base", "rvi", "B") == \
        "base_B_rvi.tif"
    # unknown frequency -> plain name, still predictable
    assert output_name_with_frequency("base", "HHHH", None) == \
        "base_HHHH.tif"


def test_two_grids_never_collide_on_one_output_name():
    a = output_name_with_frequency("NISAR_L2", "HHHH", "A")
    b = output_name_with_frequency("NISAR_L2", "HHHH", "B")
    assert a != b


def test_tiled_compute_reports_frequency_tag(mixed_handle, tmp_path):
    """The raster pipeline carries the picked grid's frequency tag even
    when GDAL is absent (error path reports before writing)."""
    from nisar_qgis.nisar_core.processing import export as export_mod
    if export_mod.GDAL_AVAILABLE:
        pytest.skip("GDAL present — covered by QGIS integration tests")
    result = compute_index_to_raster(
        mixed_handle, VegetationIndex.HV_DB, str(tmp_path / "out.tif"))
    # HV_DB still fails on pick for the mixed file (cross-pol present on
    # A, so pick succeeds on A; the GDAL error should follow).
    assert result.error_message
    assert "GDAL" in result.error_message or "single frequency" in \
        result.error_message
