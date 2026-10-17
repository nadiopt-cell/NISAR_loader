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

## Executed headless acceptance (2026-10-17, QGIS 3.44.11 OSGeo4W, plugin v0.4.0)

Environment on this machine: OSGeo4W QGIS 3.44.11 (Qt 5.15.13, Python
3.12.13, GDAL 3.13.0, PROJ 9.8.1), `QT_QPA_PLATFORM=offscreen`,
fresh profile in `QGIS_CUSTOM_CONFIG_PATH`, plugin deployed from
`nisar_qgis_plugin_v0.4.0.zip`, enabled via
`qgis_process plugins enable nisar_qgis` (5 algorithms listed).

Inputs: synthetic products from `conftest.py` factories
(`make_synthetic_gcov`, `make_synthetic_gunw`, the urgent-response
frequencyB clone) - no real granules present on disk at run time.

Results (verified independently with rasterio 1.x on a separate
Python):

- `nisar:hv_db`, `nisar:rvi`, `nisar:cross_ratio` on the dual-pol
  synthetic GCOV -> Float32 GeoTIFF 48x32, EPSG:32633,
  transform (399995.0, 10, 0, 5000005.0, 0, -10), HV dB in
  [-24.0..-1.16], RVI [0.66..1.35], cross-ratio [~-7.01..-2.92] dB;
  No .aux.xml appeared next to the sources (GDAL_PAM honored).
- `nisar:export` on the frequencyB urgent-response clone (VHVH,
  two-frequency item) -> Float32 GeoTIFF, **EPSG:32605** after a fix
  of the synthetic fixture WKT (see below).
- `nisar:windthrow_did` on the synthetic GUNW pair -> dcoh + mask
  (EPSG:32641, 48x64, 80 m), detection 140 px / 1 object with the
  absolute threshold, honest warnings present, report JSON written.
  `storm_pair`/`control_pair` are null by design for synthetic files:
  pair stamps are parsed from the real granule FILE NAME.
- GUI smoke: `NisarMainDialog` builds offscreen, 7 tabs
  (Search / Download / Open / Processing / Windthrow (DiD) / Export /
  Settings), `_push_message_bar` delivers Critical + Warning items
  into a real `QgsMessageBar` (WP-4).
- API checks live in this QGIS:
  - `QgsVectorFileWriter.create(...)` with the plugin's Qt5/Qt6 chain
    (Qt 5.15 -> `QMetaType.Int` == 2) creates a GPKG writer,
    hasError == 0 (WP-5/F13);
  - `QgsSettings` keys `proxy/proxyEnabled|proxyHost|proxyPort|
    proxyType` round-trip correctly (WP-3 `_apply_qgis_proxies`);
  - `geo.bbox_wgs84_from_georef` OSR branch (EPSG:32633 synthetic)
    matches a pyproj 3.7.1 oracle to 7 decimals (WP-5);
  - EDL token set through `ConfigManager` is NOT persisted in
    `QgsSettings` (secrets rule).
- Not exercised here: real-granule acceptance, download/search against
  ASF (needs EDL), STRICT_FOREST live path with reference polygons
  (unit-covered), conda-forge QGIS with a compiled NISAR driver
  (`GetDriverByName("NISAR") is None` in OSGeo4W GDAL 3.13.0 - the
  A1 backend is unavailable there; A2 opens via `NETCDF:` but cannot
  georeference the products; the auto-selection falls back to A3,
  which needs h5py).

### h5py inside the QGIS python (no-install workaround)

OSGeo4W python has no h5py, and installing h5py 3.12+ into it breaks
(`ppocedure-not-found` DLL conflict): GDAL loads the OSGeo HDF5
1.14.6 first, and recent h5py wheels bundle HDF5 2.x. Workaround
verified here: unpack the wheel `h5py-3.11.0-cp312-cp312-win_amd64`
(a version built against HDF5 1.14.2) into any folder and append it
to `PYTHONPATH` AFTER `o4w_env.bat` sets its own value
(a wrapper .bat that re-exports PYTHONPATH makes qgis_process and the
python-eos use A3 transparently). Single warning
"running against HDF5 1.14.6 (built against 1.14.2)" is benign.

### Synthetic-fixture WKT bug found and fixed

The urgent-response fixture WKT placed `AUTHORITY["EPSG","9001"]`
(``UNIT``) OUTSIDE the UNIT brackets, at the PROJCS level, which makes
GDAL 3.13 mis-identify the whole CRS as EPSG:9001 (IGS97 geocentric!)
when the WKT is written to GeoTIFF. Real granules were never affected
(their WKT is well-formed); the dual-polarization synthetic fixture
always was. `conftest.py` is fixed; frequencyB exports now carry
EPSG:32605 end-to-end.
