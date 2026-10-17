# -*- coding: utf-8 -*-
"""WP-5 (finding F6): forest mask never swallows tile errors.

Partial tile failure must yield an explicit warning with the coverage
fraction; strict mode must raise; no fallback without an explicit
warning.
"""
import numpy as np
import pytest
from types import SimpleNamespace

from nisar_qgis.nisar_core.processing import forest_mask as fm


@pytest.fixture()
def georef():
    # EPSG:4326 so no coordinate transform is needed in this unit env
    return SimpleNamespace(bbox=(5.0, 47.0, 7.0, 49.0),
                           crs_authid="EPSG:4326", crs_wkt="")


def test_success_clean_mask_no_warnings(monkeypatch, georef):
    monkeypatch.setattr(fm, "_forest_fraction_rasterio",
                        lambda *a, **k: (np.zeros((3, 3)), [], 1))
    mask, warns = fm.forest_mask_for_grid(georef, year=2024)
    assert mask is not None and warns == []


def test_partial_tile_failure_warns_with_coverage(monkeypatch, georef):
    monkeypatch.setattr(
        fm, "_forest_fraction_rasterio",
        lambda *a, **k: (np.zeros((3, 3)), ["50N_000E"], 2))
    mask, warns = fm.forest_mask_for_grid(georef, year=2024)
    assert mask is not None
    assert len(warns) == 1
    assert "50N_000E" in warns[0]
    assert "50%" in warns[0]
    assert "coverage" in warns[0]


def test_partial_tile_failure_strict_raises(monkeypatch, georef):
    monkeypatch.setattr(
        fm, "_forest_fraction_rasterio",
        lambda *a, **k: (np.zeros((3, 3)), ["50N_000E"], 2))
    with pytest.raises(RuntimeError) as err:
        fm.forest_mask_for_grid(georef, year=2024, strict=True)
    assert "50N_000E" in str(err.value)


def test_total_failure_falls_back_with_explicit_warning(monkeypatch,
                                                        georef):
    def ras_fail(*a, **k):
        raise RuntimeError("rasterio boom")

    def gdal_fail(*a, **k):
        raise RuntimeError("no gdal backend")

    monkeypatch.setattr(fm, "_forest_fraction_rasterio", ras_fail)
    monkeypatch.setattr(fm, "_read_hansen_gdal", gdal_fail)
    mask, warns = fm.forest_mask_for_grid(georef, year=2024)
    assert mask is None
    assert any("rasterio forest path failed" in w for w in warns)
    assert any("Hansen GFC tiles unavailable" in w for w in warns)


def test_total_failure_strict_raises(monkeypatch, georef):
    def ras_fail(*a, **k):
        raise RuntimeError("rasterio boom")

    monkeypatch.setattr(fm, "_forest_fraction_rasterio", ras_fail)

    def gdal_fail(*a, **k):
        raise RuntimeError("no gdal")

    monkeypatch.setattr(fm, "_read_hansen_gdal", gdal_fail)
    with pytest.raises(RuntimeError):
        fm.forest_mask_for_grid(georef, year=2024, strict=True)


def test_unresolvable_bbox_strict_raises(monkeypatch, georef):
    monkeypatch.setattr(fm, "bbox_wgs84_from_georef", lambda g: None)
    mask, warns = fm.forest_mask_for_grid(georef, year=2024)
    assert mask is None and warns
    with pytest.raises(RuntimeError):
        fm.forest_mask_for_grid(georef, year=2024, strict=True)
