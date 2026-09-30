# QGIS integration tests

These tests exercise the plugin inside a running QGIS application
(Processing provider registration, dialog construction, layer loading,
export with GDAL). They are **not** part of the plain-pytest suite.

Run them with the QGIS Python interpreter:

```bash
# QGIS 3.28+ with the plugin installed in the profile
qgis_process --version  # sanity check

# from the repo root, using the QGIS python:
/path/to/qgis/python/bin/python -m pytest tests/qgis -v
```

## Executed headless acceptance (2026-09-30, QGIS 3.44.14 offscreen)

Record of a real (non-mocked) run — conda-forge QGIS 3.44.14,
`QT_QPA_PLATFORM=offscreen`, plugin installed into a profile via
`QGIS_CUSTOM_CONFIG_PATH`, started through `qgis_process`
(this path requires the plugin's `initProcessing()`):

```bash
qgis_process plugins enable nisar_qgis      # -> "Enabled nisar_qgis"
qgis_process list                           # -> 5 nisar:* algorithms
qgis_process run nisar:hv_db --INPUT=<GCOV.h5> --OUTPUT=hv_db.tif
qgis_process run nisar:rvi  --INPUT=<GCOV.h5> --OUTPUT=rvi.tif
qgis_process run nisar:cross_ratio --INPUT=<GCOV.h5> --OUTPUT=cr.tif
qgis_process run nisar:windthrow_did \
  --STORM=<GUNW pair 1.h5> --CONTROL=<GUNW pair 2.h5> \
  --EVENT_DATE=2026-07-01 --FOREST_MASK=true --THRESHOLD_MODE=0 \
  --OUTPUT_DIR=<dir> --OUTPUT=<dir>/dcoh.tif
```

Results on real granules (see RELEASE_NOTES_v0.3.1.md for full numbers):
indices -> valid Float32 GeoTIFF 4248x4167 @ 80 m; windthrow DiD
reproduces the P3.1 re-run bit-for-bit without the forest mask
(783 544 px / 501 468 ha / 3 993 objects) and completes with the
online Hansen GFC forest mask (650 317 px / 416 203 ha / 3 973
objects). GUI dialog smoke (7 tabs, offscreen QApplication) also
passed. This run uncovered six API defects fixed in v0.3.1 —
regression tests live in tests/unit/test_qgis_plugin_api.py.

Minimum manual acceptance (TZ §2, MVP):

1. Install the plugin from `nisar_qgis_plugin_v0.3.1.zip`
   (Plugins → Manage and Install Plugins → Install from ZIP).
2. Menu «NISAR Vegetation» / toolbar button opens the dialog.
3. Search tab: set map extent, dates, GCOV → results table appears,
   GUI stays responsive, search can be stopped.
3a. Preview: click a result row → quicklook thumbnail loads (no ~/.netrc
   needed), details show orbit/frame/pols/size, a yellow footprint
   polygon appears on the map canvas; double-click the row (or
   «Zoom to footprint») zooms the map to the scene; «Open full image»
   opens the full-resolution browse PNG in the default viewer.
4. Download tab: select a scene, download (needs ~/.netrc with
   Earthdata credentials).
5. Open tab: inspect the downloaded .h5 → layers HHHH/HVHV appear;
   add them to the project — group «NISAR / …», correct UTM CRS.
   For a GUNW .h5: coherence 80 m / 20 m, phase and mask layers appear
   with correct CRS per grid.
6. Processing tab: run «HV (Cross-pol), dB» and «RVI» — new layers
   appear with metadata and 2–98% stretch.
7. Export tab / Processing Toolbox: nisar:hv_db, nisar:rvi,
   nisar:cross_ratio, nisar:export produce Float32 GeoTIFF/COG.
8. Windthrow (DiD) tab: search GUNW for one track/frame, download the
   storm pair (interval brackets the storm date) and the adjacent
   control pair; fill both paths + storm date → «Detect windthrow»:
   after a couple of minutes (online Hansen GFC tiles) dcoh + mask layers
   are added to the project and the report (threshold, background,
   detection, metrics) appears in the panel. Cross-check in the Toolbox:
   `nisar:windthrow_did` with the same inputs.
9. No tracebacks anywhere; BETA scenes produce a warning.
