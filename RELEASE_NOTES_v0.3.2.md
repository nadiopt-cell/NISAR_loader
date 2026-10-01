# NISAR Vegetation v0.3.2

## Forest-fix: memory-safe Hansen warping (standalone rasterio path)

`forest_mask._forest_fraction_rasterio` now warps each Hansen GFC tile to
the scene grid **in row strips** (~64 MB per strip) instead of one
full-window pass. Previously the full-window `float32` source arrays
(forest + ones, 4 bytes/px each) peaked ~2 GB per tile and OOM-killed any
scene whose WGS84 bbox spans 2+ Hansen tiles (verified live: GUNW
trk 93D fr 058 spans 60N/70N × 050E/060E — 4 tiles; the standalone path
died at 3.6 GB RSS before the fix, completes in-budget after).

Aggregation semantics are unchanged: `Resampling.sum` adds each source
pixel exactly once; accumulation across strips and tiles stays exact, and
`init_dest_nodata=False` still protects the shared accumulators. Live
check on the karpinsk frame: fixed plugin mask vs the independent
NumPy-aggregated mask used for validation — 99.3% pixel-identical
(within the previously documented v2/v3 equivalence), 135 unit tests
still green.

## Windthrow validation — second wave (new Shikhov DB sites)

`validation/windthrow_new_sites/`: live `run_windthrow_did` validation on
4 new site groups (32 events, storm systems of 05.07 and 27.07.2026,
plus the 21.06.2026 Chelyabinsk squall) from the updated Shikhov
windthrow database (vetrovaly_3316, 2026-09-06 edition), selected by
GUNW coverage (data horizon Sept 2026):

| site | pair (storm → control) | AUC | excess | R_px | IoU≥0.5 |
|---|---|---|---|---|---|
| nnov_sukhona (6 events) | trk 99A fr 30, 03–15.07 → 15–27.07 | 0.807 | 0.134 | 0.007 | 0/6 |
| kostroma_108 (22 events) | trk 108D fr 59, 03–15.07 → 15–27.07 | 0.920 | 0.284 | 0.405 | 1/22 |
| kirov_slav (4 events) | trk 41A fr 32, 23.07–16.08 → 16.08–09.09 (24 d) | **0.968** | **0.394** | **0.833** | 0/4 |
| chelyabinsk (2 events) | trk 84A fr 30, 20.06–14.07 → 26.07–19.08 (24 d) | 0.825 | 0.162 | 0.040 | 0/2 |

Highlights: strongest DiD signal of both validation waves (Kirov,
excess 0.394, 24-day baseline-matched pairs); first object-level match
(tornado 4272, 15 ha, IoU 0.559); weak sites correlate with an elevated
control-vs-storm background (median dcoh 0.11–0.17 vs 0.05 on strong
sites), confirming the a_coh ≈ 0.15–0.20 calibration recommendation;
look-geometry matters (events 4282/4283 invisible on trk 99A, overlap
0.32/0.49 on trk 108D). The validation script is regression-verified
against wave 1: karpinsk retest reproduces best IoU 0.1556 for event
4251 to the 4th decimal.

See `validation/windthrow_new_sites/README.md` for the full protocol,
per-site metrics and granule IDs.
