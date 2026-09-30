# -*- coding: utf-8 -*-
"""Windthrow DiD core tests: pair parsing, compatibility, detector,
forest-mask rule, resampling, metrics and the end-to-end pipeline on the
synthetic GUNW pair."""
import json
from datetime import datetime

import numpy as np
import pytest

from nisar_qgis.nisar_core.readers import ReaderRegistry
from nisar_qgis.nisar_core.processing.windthrow import (
    WindthrowParams, parse_gunw_pair_info, check_pair_compatibility,
    compute_dcoh, detect_windthrow, hansen_forest_mask_year,
    resample_fraction, ring_background_mask, windthrow_metrics,
    run_windthrow_did, find_coherence_layer,
)
from nisar_qgis.nisar_core.processing.forest_mask import (
    hansen_tile_suffixes, hansen_layer_urls, bbox_from_bounding_polygon,
    DEFAULT_GFC_VERSION,
)

from conftest import (
    GH, GW, GUNW_DAMAGE_ROWS, GUNW_DAMAGE_COLS, make_synthetic_gunw,
)


# ------------------------------------------------------------- pair parsing
def test_parse_gunw_pair_info():
    info = parse_gunw_pair_info(
        "NISAR_L2_PR_GUNW_023_093_D_058_024_2000_SH_20260620T154356_"
        "20260620T154433_20260702T154356_20260702T154432_P05023_N_F_J_001")
    assert info.cycle == 23
    assert info.track == 93
    assert info.direction == "D"
    assert info.frame == 58
    assert info.pol_code == "SH"
    assert info.ref_start == datetime(2026, 6, 20, 15, 43, 56)
    assert info.sec_start == datetime(2026, 7, 2, 15, 43, 56)

    # path form also works
    info2 = parse_gunw_pair_info("/some/dir/NISAR_L2_PR_GUNW_024_093_D_"
                                 "058_025_2000_SH_20260702T154356_"
                                 "20260702T154432_20260714T154355_"
                                 "20260714T154431_P05023_F_F_J_001.h5")
    assert info2.track == 93 and info2.frame == 58
    assert info2.ref_start == datetime(2026, 7, 2, 15, 43, 56)

    # garbage does not crash
    assert parse_gunw_pair_info("not_a_granule").track is None


# ------------------------------------------------------------ compatibility
def _handles(gunw_storm, gunw_control):
    s = ReaderRegistry.open(gunw_storm)
    c = ReaderRegistry.open(gunw_control)
    return s, c


def test_pair_compatible(gunw_storm, gunw_control):
    s, c = _handles(gunw_storm, gunw_control)
    try:
        compat = check_pair_compatibility(
            s, c, datetime(2026, 6, 22))
        assert compat.compatible, compat.issues
        # the synthetic intervals touch at 2026-07-02 (post-post control):
        # no overlap warning expected
        assert compat.warnings == []
    finally:
        ReaderRegistry.close(s)
        ReaderRegistry.close(c)


def test_pair_event_date_warnings(gunw_storm, gunw_control):
    s, c = _handles(gunw_storm, gunw_control)
    try:
        # event outside the storm interval -> warning
        compat = check_pair_compatibility(
            s, c, datetime(2026, 6, 10))
        assert compat.compatible
        assert any("not bracketed" in w for w in compat.warnings)
    finally:
        ReaderRegistry.close(s)
        ReaderRegistry.close(c)


def test_pair_incompatible_track(gunw_storm, tmp_path):
    other = make_synthetic_gunw(tmp_path / "other_track.h5",
                                 kind="control", track=127, frame=58)
    s = ReaderRegistry.open(gunw_storm)
    c = ReaderRegistry.open(other)
    try:
        compat = check_pair_compatibility(s, c)
        assert not compat.compatible
        assert any("track mismatch" in i for i in compat.issues)
    finally:
        ReaderRegistry.close(s)
        ReaderRegistry.close(c)


def test_pair_incompatible_non_gunw(gcov_dual):
    handle = ReaderRegistry.open(gcov_dual)
    try:
        compat = check_pair_compatibility(handle, handle)
        assert not compat.compatible
    finally:
        ReaderRegistry.close(handle)


# ------------------------------------------------------------------- dcoh
def test_compute_dcoh(gunw_storm, gunw_control, gunw_damage_mask):
    s, c = _handles(gunw_storm, gunw_control)
    try:
        result = compute_dcoh(s, c)
        assert result.pol == "HH"
        assert result.dcoh.shape == (GH, GW)
        assert result.valid.all()

        inside = result.dcoh[gunw_damage_mask]
        outside = result.dcoh[~gunw_damage_mask]
        # DiD signal: positive inside the damage
        assert float(np.median(inside)) > 0.25
        assert float(np.median(outside)) < 0.1
        assert float(np.median(inside) - np.median(outside)) > 0.25
    finally:
        ReaderRegistry.close(s)
        ReaderRegistry.close(c)


# --------------------------------------------------------------- detector
def test_detect_windthrow_finds_damage(gunw_storm, gunw_control,
                                       gunw_damage_mask):
    s, c = _handles(gunw_storm, gunw_control)
    try:
        result = compute_dcoh(s, c)
        # background: everything except a margin around the damage
        bg = np.ones_like(gunw_damage_mask)
        r0, r1 = GUNW_DAMAGE_ROWS
        c0, c1 = GUNW_DAMAGE_COLS
        bg[max(r0 - 4, 0):min(r1 + 4, GH), max(c0 - 4, 0):min(c1 + 4, GW)] \
            = False

        detection = detect_windthrow(result.dcoh, bg, result.valid,
                                     WindthrowParams())
        # default "absolute" mode (reference plugin v1.2.1): median + a_coh
        detection_mad = detect_windthrow(
            result.dcoh, bg, result.valid,
            WindthrowParams(threshold_mode="mad", k_mad=0.25))
        # the damage block must be recovered (allowing edge erosion)
        det = detection.mask
        overlap = (det & gunw_damage_mask).sum()
        assert overlap >= 0.6 * gunw_damage_mask.sum()
        # the detection density inside the damage must clearly exceed the
        # density in the far background (the detector is an alert layer:
        # a low threshold is by design — see the source study)
        far = np.zeros_like(bg)
        far[:8, :] = True
        density_in = (det & gunw_damage_mask).sum() / gunw_damage_mask.sum()
        density_far = (det & far).sum() / max(far.sum(), 1)
        assert density_in > 2.0 * density_far
        assert detection.n_objects >= 1
        # threshold rule — default absolute mode (reference plugin)
        bg_vals = result.dcoh[bg]
        expected_abs = float(np.median(bg_vals)) + 0.25
        assert detection.threshold == pytest.approx(expected_abs, abs=1e-6)
        # threshold rule — "mad" mode (article wording)
        expected_mad = float(np.median(bg_vals)) + 0.25 * float(
            np.mean(np.abs(bg_vals - np.median(bg_vals))))
        assert detection_mad.threshold == pytest.approx(expected_mad,
                                                       abs=1e-6)
        assert detection_mad.threshold < detection.threshold
    finally:
        ReaderRegistry.close(s)
        ReaderRegistry.close(c)


def test_detect_windthrow_min_pixels():
    dcoh = np.zeros((40, 40), dtype=np.float32)
    bg = np.ones((40, 40), dtype=bool)
    bg[15:25, 15:25] = False
    # a 5-px speck (below min) and a 30-px block (above min)
    dcoh[18:23, 18:23] = 1.0
    dcoh[5, 5] = 1.0
    valid = np.ones((40, 40), dtype=bool)
    detection = detect_windthrow(dcoh, bg, valid, WindthrowParams())
    assert detection.n_objects == 1


def test_detect_windthrow_too_small_background():
    dcoh = np.zeros((20, 20), dtype=np.float32)
    bg = np.zeros((20, 20), dtype=bool)
    bg[0, 0] = True
    with pytest.raises(ValueError):
        detect_windthrow(dcoh, bg, np.ones((20, 20), dtype=bool))


# ----------------------------------------------------------- forest rule
def test_hansen_forest_mask_year():
    treecover = np.array([[80, 80, 10, 80], [80, 25, 80, 80]],
                         dtype=np.uint8)
    lossyear = np.array([[0, 0, 0, 5], [0, 0, 3, 0]], dtype=np.uint8)
    # event year 2020: no loss in 2001..2019 allowed
    mask = hansen_forest_mask_year(treecover, lossyear, 2020)
    assert mask[0, 0]                      # forest, no loss
    assert mask[0, 1]                      # forest, no loss
    assert not mask[0, 2]                  # treecover < 30
    assert not mask[0, 3]                  # lost in 2005 -> not forest@2019
    assert mask[1, 0]
    assert not mask[1, 1]                  # treecover 25 < 30
    assert not mask[1, 2]                  # lost in 2003
    assert mask[1, 3]

    # loss in the event year itself: candidate keeps, background excludes
    ly = np.array([[0, 20], [0, 0]], dtype=np.uint8)
    tc = np.array([[80, 80], [80, 80]], dtype=np.uint8)
    candidate = hansen_forest_mask_year(tc, ly, 2020)
    background = hansen_forest_mask_year(tc, ly, 2020,
                                          exclude_loss_year=True)
    assert candidate[0, 1]
    assert not background[0, 1]
    assert background[0, 0] and background[1, 1]


# --------------------------------------------------------- resample fraction
def test_resample_fraction_exact_grid():
    # aligned grids: 2 m source -> 4 m destination (2x2 source px each)
    src = np.array([[0, 1, 0, 1],
                    [1, 0, 1, 0],
                    [0, 1, 1, 1],
                    [1, 0, 0, 1]], dtype=np.float32)
    sx = np.array([1.0, 3.0, 5.0, 7.0])
    sy = np.array([8.0, 6.0, 4.0, 2.0])   # descending (north-up raster)
    dx = np.array([2.0, 6.0])             # aligned with the source extent
    dy = np.array([7.0, 3.0])
    frac = resample_fraction(src, sx, sy, dx, dy)
    assert frac.shape == (2, 2)
    # dst(0,0): src rows y in (4,8] = {8,6}, cols x in [0,4) = {1,3}
    assert frac[0, 0] == pytest.approx((0 + 1 + 1 + 0) / 4)
    # dst(0,1): rows {8,6}, cols x in [4,8) = {5,7}
    assert frac[0, 1] == pytest.approx((0 + 1 + 1 + 0) / 4)
    # dst(1,0): rows y in (0,4] = {4,2}, cols {1,3}
    assert frac[1, 0] == pytest.approx((0 + 1 + 1 + 0) / 4)
    # dst(1,1): rows {4,2}, cols {5,7}
    assert frac[1, 1] == pytest.approx((1 + 1 + 0 + 1) / 4)


def test_resample_fraction_uneven():
    # 30 m source into 80 m destination: 8/3 px per cell -> 2 or 3 px
    rng = np.random.default_rng(3)
    src = (rng.random((30, 30)) > 0.5).astype(np.float32)
    sx = 30.0 * (np.arange(30) + 0.5)
    sy = 900.0 - 30.0 * (np.arange(30) + 0.5)
    dx = 80.0 * (np.arange(5) + 0.5)
    dy = np.array([900.0 - 80.0 * (i + 0.5) for i in range(5)])
    frac = resample_fraction(src, sx, sy, dx, dy)
    assert frac.shape == (5, 5)
    assert np.isfinite(frac).all()
    assert float(frac.min()) >= 0.0 and float(frac.max()) <= 1.0


# --------------------------------------------------------------- ring mask
def test_ring_background_mask():
    ref = np.zeros((50, 50), dtype=bool)
    ref[20:30, 20:30] = True
    ring = ring_background_mask(ref, 5.0)
    assert not ring[ref].any()          # excludes the reference itself
    assert ring[24, 24 - 6]             # nearby pixel inside the ring
    assert not ring[24, 24 - 30]        # far away outside


# ---------------------------------------------------------------- metrics
def test_windthrow_metrics_perfect_separation():
    dcoh = np.zeros((10, 10), dtype=np.float32)
    ref = np.zeros((10, 10), dtype=bool)
    ref[2:5, 2:5] = True
    bg = np.zeros((10, 10), dtype=bool)
    bg[6:9, 6:9] = True
    dcoh[ref] = 1.0
    dcoh[bg] = 0.0
    m = windthrow_metrics(dcoh, ref, bg)
    assert m["auc"] == pytest.approx(1.0)
    assert m["excess"] == pytest.approx(1.0)
    assert m["tpr_fpr05"] == pytest.approx(1.0)
    assert m["n_ref"] == 9 and m["n_bg"] == 9


def test_windthrow_metrics_ties():
    dcoh = np.zeros((10, 10), dtype=np.float32)
    ref = np.zeros((10, 10), dtype=bool)
    ref[0:2, 0:5] = True
    bg = np.zeros((10, 10), dtype=bool)
    bg[0:2, 5:10] = True
    # identical distributions -> AUC 0.5, excess 0
    m = windthrow_metrics(dcoh, ref, bg)
    assert m["auc"] == pytest.approx(0.5)
    assert m["excess"] == pytest.approx(0.0)


# ----------------------------------------------------------- forest tiles
def test_hansen_tile_suffixes():
    # verified live naming (bounds checked with rasterio):
    # 60N_060E covers lat 50..60N lon 60..70E; 00N covers -10..0
    assert hansen_tile_suffixes((56.88, 58.35, 63.15, 61.5)) == [
        "60N_050E", "70N_050E", "60N_060E", "70N_060E"]
    assert hansen_tile_suffixes((5.0, -5.0, 15.0, 5.0)) == [
        "00N_000E", "10N_000E", "00N_010E", "10N_010E"]
    assert hansen_tile_suffixes((5.0, -15.0, 5.0, -5.0)) == [
        "10S_000E", "00N_000E"]


def test_hansen_layer_urls():
    urls = hansen_layer_urls("lossyear", (56.88, 58.35, 63.15, 61.5))
    assert urls[0] == ("%s/%s/Hansen_%s_lossyear_60N_050E.tif"
                       % ("https://storage.googleapis.com/"
                          "earthenginepartners-hansen",
                          DEFAULT_GFC_VERSION, DEFAULT_GFC_VERSION))
    with pytest.raises(ValueError):
        hansen_layer_urls("datamask", (0, 0, 1, 1))


def test_bbox_from_bounding_polygon():
    # real-granule form: lon lat elev triples, closed ring
    wkt = ("POLYGON ((58.96 61.49 398.7, 58.74 61.29 299.2, "
           "57.48 60.05 326.2, 58.96 61.49 398.7))")
    assert bbox_from_bounding_polygon(wkt) == pytest.approx(
        (57.48, 60.05, 58.96, 61.49))
    # plain lon-lat pairs, closed ring
    assert bbox_from_bounding_polygon(
        "POLYGON ((1 2, 3 4, 1 2))") == pytest.approx((1, 2, 3, 4))
    assert bbox_from_bounding_polygon("") is None
    assert bbox_from_bounding_polygon("LINESTRING (1 2, 3 4)") is None


# ---------------------------------------------------------------- pipeline
def test_run_windthrow_did_e2e(gunw_storm, gunw_control, tmp_path,
                               gunw_damage_mask):
    result = run_windthrow_did(
        gunw_storm, gunw_control, output_dir=str(tmp_path),
        event_date=datetime(2026, 6, 22),
        ref_mask=gunw_damage_mask,
        progress_callback=None)
    assert result.success, result.error_message

    report = result.metadata
    assert report["method"].startswith("DiD")
    assert report["layer"] == "HH_coherenceMagnitude_80m"
    assert report["grid"]["width"] == GW and report["grid"]["height"] == GH
    assert report["threshold"]["mode"] == "absolute"
    assert report["threshold"]["rule"].startswith("median(bg) + a_coh")
    assert report["threshold"]["a_coh"] == 0.25
    assert report["detection"]["pixels"] > 0
    assert report["detection"]["objects"] >= 1

    # metrics against the known ground truth
    metrics = report["metrics"]
    assert metrics["n_ref"] == int(gunw_damage_mask.sum())
    assert metrics["auc"] > 0.9
    assert metrics["excess"] > 0.25
    assert metrics["tpr_fpr05"] > 0.5

    # warnings: reference-only background (no forest mask given) expected
    assert any("forest mask" in w for w in result.warnings)

    # outputs written
    assert (tmp_path / "dcoh.tif").exists()
    assert (tmp_path / "windthrow_mask.tif").exists()
    report_path = tmp_path / "windthrow_report.json"
    assert report_path.exists()
    loaded = json.loads(report_path.read_text(encoding="utf-8"))
    assert loaded["detection"]["pixels"] == report["detection"]["pixels"]

    # written rasters are georeferenced (rasterio available in CI)
    try:
        import rasterio
        with rasterio.open(tmp_path / "dcoh.tif") as src:
            assert src.width == GW and src.height == GH
            assert src.crs is not None
            assert src.transform.a == pytest.approx(80.0)
        with rasterio.open(tmp_path / "windthrow_mask.tif") as src:
            data = src.read(1)
            assert set(np.unique(data)).issubset({0, 1})
    except ImportError:
        pytest.skip("rasterio not available")


def test_run_windthrow_did_incompatible(gunw_storm, tmp_path):
    other = make_synthetic_gunw(tmp_path / "other.h5", kind="control",
                                 track=64, frame=59)
    result = run_windthrow_did(gunw_storm, other,
                               output_dir=str(tmp_path / "out"))
    assert not result.success
    assert "not compatible" in result.error_message


def test_run_windthrow_did_shape_mismatch(gunw_storm, gunw_control,
                                          tmp_path):
    bad_mask = np.zeros((10, 10), dtype=bool)
    result = run_windthrow_did(gunw_storm, gunw_control,
                               output_dir=str(tmp_path),
                               ref_mask=bad_mask)
    assert not result.success
    assert "shape" in result.error_message


def test_find_coherence_layer_prefers_hh(gunw_storm):
    handle = ReaderRegistry.open(gunw_storm)
    try:
        layer = find_coherence_layer(handle)
        assert layer is not None
        assert layer.metadata["pol"] == "HH"
        assert layer.metadata["posting_m"] == 80
    finally:
        ReaderRegistry.close(handle)


def test_windthrow_params_invalid_mode():
    with pytest.raises(ValueError):
        WindthrowParams(threshold_mode="bogus")


def test_detect_windthrow_absolute_vs_mad_sensitivity():
    """a_coh mode is more conservative than k*MAD on a noisy background."""
    rng = np.random.default_rng(3)
    dcoh = rng.normal(0.0, 0.10, (60, 60)).astype(np.float32)
    dcoh[20:30, 20:30] += 0.40          # damage signal
    bg = np.ones((60, 60), dtype=bool)
    bg[16:34, 16:34] = False
    valid = np.ones((60, 60), dtype=bool)

    det_abs = detect_windthrow(dcoh, bg, valid,
                               WindthrowParams(threshold_mode="absolute"))
    det_mad = detect_windthrow(dcoh, bg, valid,
                               WindthrowParams(threshold_mode="mad"))
    # the absolute threshold sits far above the k*MAD one on this scene
    assert det_abs.threshold > det_mad.threshold
    # ... and flags strictly fewer background pixels
    far = np.ones_like(bg)
    far[16:34, 16:34] = False
    far[:10, :] = False
    assert (det_abs.mask & far).sum() <= (det_mad.mask & far).sum()
