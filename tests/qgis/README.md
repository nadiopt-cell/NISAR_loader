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

Minimum manual acceptance (TZ §2, MVP):

1. Install the plugin from `nisar_qgis_plugin_v0.3.0.zip`
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
