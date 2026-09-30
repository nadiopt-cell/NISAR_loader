# -*- coding: utf-8 -*-
"""
Internationalization (i18n) for NISAR Plugin — English (default).
"""

I18N_EN = {
    # General UI
    "plugin.name": "NISAR Vegetation",
    "plugin.desc": "QGIS plugin for NISAR data (vegetation monitoring)",

    # Tabs
    "ui.tab_search": "Search",
    "ui.tab_download": "Download",
    "ui.tab_open": "Open",
    "ui.tab_process": "Processing",
    "ui.tab_windthrow": "Windthrow (DiD)",
    "ui.tab_export": "Export",
    "ui.tab_settings": "Settings",

    # Windthrow DiD tab (P3)
    "ui.windthrow.title": "Windthrow detection: DiD of GUNW pair coherence",
    "ui.windthrow.storm": "Storm pair GUNW (.h5)",
    "ui.windthrow.storm_placeholder": "pair bracketing the storm date",
    "ui.windthrow.control": "Control pair GUNW (.h5)",
    "ui.windthrow.control_placeholder": "adjacent 12-day interval, same track/frame",
    "ui.windthrow.event_date": "Storm date (optional)",
    "ui.windthrow.threshold_mode": "Threshold rule",
    "ui.windthrow.mode_absolute": "median + a (reference plugin)",
    "ui.windthrow.mode_mad": "median + k*MAD (article)",
    "ui.windthrow.a_coh": "Offset a (coherence units)",
    "ui.windthrow.k_mad": "Threshold k (median + k*MAD)",
    "ui.windthrow.min_pixels": "Minimum object (pixels)",
    "ui.windthrow.forest_mask": "Restrict to Hansen GFC forest (online tiles)",
    "ui.windthrow.polygonize": "Vectorize detections (GeoPackage)",
    "ui.windthrow.output_dir": "Output directory",
    "ui.windthrow.run": "Detect windthrow",
    "ui.windthrow.report_hint": "The report appears here after the run.",
    "ui.windthrow.no_storm": "Select the storm pair GUNW granule (.h5)",
    "ui.windthrow.no_control": "Select the control pair GUNW granule (.h5)",
    "ui.windthrow.bad_date": "Invalid date {value} (expected YYYY-MM-DD)",
    "ui.windthrow.bad_params": "Invalid detector parameters (k and minimum object size must be numbers)",
    "ui.windthrow.open_failed": "Cannot open the GUNW granules: {error}",
    "ui.windthrow.incompatible": "The pairs are not compatible: {issues}",
    "ui.windthrow.pair_warning": "⚠ {warning}",
    "ui.windthrow.running": "Running… (reading coherence, building the forest mask may take a few minutes)",
    "ui.windthrow.done": "Done",
    "ui.windthrow.failed": "Failed: {error}",
    "ui.windthrow.r_method": "Method",
    "ui.windthrow.r_storm": "Storm pair",
    "ui.windthrow.r_control": "Control pair",
    "ui.windthrow.r_layer": "Layer",
    "ui.windthrow.r_background": "Background pixels",
    "ui.windthrow.r_threshold": "Threshold",
    "ui.windthrow.r_detection": "Detected",
    "ui.windthrow.r_objects": "objects",
    "ui.windthrow.r_flags": "Flags",
    "ui.windthrow.r_metrics": "Metrics",

    # Search tab
    "ui.search.title": "ASF scene search",
    "ui.search.use_map_extent": "Use current map extent",
    "ui.search.aoi_wkt": "AOI (WKT, from map extent)",
    "ui.search.start_date": "Start date (YYYY-MM-DD)",
    "ui.search.end_date": "End date (YYYY-MM-DD)",
    "ui.search.product_type": "Product type",
    "ui.search.button": "Search",
    "ui.search.stop": "Stop search",
    "ui.search.searching": "Searching...",
    "ui.search.no_results": "No scenes found for the given criteria.",
    "ui.search.results": "Search results",
    "ui.search.col_scene": "Scene ID",
    "ui.search.col_date": "Date",
    "ui.search.col_status": "Status",
    "ui.search.col_size": "Size",
    "ui.search.col_select": "Select",
    "ui.search.backend_unavailable": (
        "Online search is unavailable: {reason}.\n\n"
        "You can still open local NISAR files in the 'Open' tab."),
    "ui.search.beta_warning": (
        "BETA products are not fully calibrated. Prefer PROVISIONAL for "
        "analysis and do not mix BETA and PROVISIONAL in one time series."),
    "ui.search.aoi_hint": "Click 'Use current map extent' to set the AOI.",

    # Preview panel (P2.5 — preview before download)
    "ui.preview.title": "Scene preview (before download)",
    "ui.preview.hint": (
        "Select a result row to preview the scene: quicklook image, "
        "details and footprint on the map."),
    "ui.preview.loading": "Loading quicklook...",
    "ui.preview.unavailable": "No quicklook image available.",
    "ui.preview.failed": "Quicklook failed: {error}",
    "ui.preview.no_footprint": "Footprint unknown for this scene.",
    "ui.preview.zoom": "Zoom to footprint",
    "ui.preview.open_browse": "Open full image",
    "ui.preview.detail_scene": "Scene",
    "ui.preview.detail_product": "Product",
    "ui.preview.detail_acquired": "Acquired (UTC)",
    "ui.preview.detail_status": "Status",
    "ui.preview.detail_size": "Download size",
    "ui.preview.detail_pols": "Polarizations",
    "ui.preview.detail_orbit": "Orbit",
    "ui.preview.detail_frame": "Frame / path",
    "ui.preview.detail_collection": "Collection",
    "ui.preview.detail_bbox": "Footprint bbox (lon/lat)",

    # Download tab
    "ui.download.title": "Download queue",
    "ui.download.button": "Download selected scenes",
    "ui.download.cancel": "Cancel",
    "ui.download.no_scenes": "No scenes selected for download.",
    "ui.download.col_scene": "Scene ID",
    "ui.download.col_progress": "Progress",
    "ui.download.col_status": "Status",
    "ui.download.started": "Download started for {n} scene(s).",
    "ui.download.done": "Downloaded: {path}",
    "ui.download.failed": "Download failed: {error}",
    "ui.download.hint_netrc": (
        "ASF downloads require Earthdata Login. Configure ~/.netrc:\n"
        "machine urs.earthdata.nasa.gov\n  login YOUR_EDL_USER\n"
        "  password YOUR_EDL_PASSWORD"),

    # Open tab
    "ui.open.title": "Open local NISAR product",
    "ui.open.browse": "Browse...",
    "ui.open.file_label": "NISAR file (.h5)",
    "ui.open.inspect": "Inspect",
    "ui.open.layers": "Layers found in the product",
    "ui.open.col_layer": "Layer",
    "ui.open.col_pol": "Polarization",
    "ui.open.col_units": "Units",
    "ui.open.col_size": "Size (px)",
    "ui.open.add_selected": "Add selected layers to project",
    "ui.open.no_file": "Select a NISAR .h5 file first.",
    "ui.open.open_failed": "Could not open the product: {error}",
    "ui.open.georef_warning": (
        "The product has no valid georeference ({reasons}).\n"
        "Layers were NOT positioned on the map. Check the file or update "
        "QGIS/GDAL."),
    "ui.open.beta_hint": "Product status: {status}",
    "ui.open.added": "Added {n} layer(s) to the project group '{group}'.",

    # Processing tab
    "ui.process.title": "Vegetation presets",
    "ui.process.col_preset": "Preset",
    "ui.process.col_available": "Available",
    "ui.process.details": "What is this?",
    "ui.process.run": "Run processing",
    "ui.process.running": "Computing...",
    "ui.process.no_product": "Open a NISAR product first (Open tab).",
    "ui.process.done": "Computed {preset}: {path}",
    "ui.process.failed": "Processing failed: {error}",
    "ui.process.requires": "Requires: {req}",

    # Export tab
    "ui.export.title": "Export",
    "ui.export.path": "Output GeoTIFF path",
    "ui.export.browse": "Browse...",
    "ui.export.cog": "Cloud Optimized GeoTIFF (COG)",
    "ui.export.button": "Export",
    "ui.export.source_layer": "Layer of the opened product",
    "ui.export.no_product": "Open a product and select a layer first.",
    "ui.export.done": "Exported to {path}",
    "ui.export.failed": "Export failed: {error}",

    # Settings tab
    "ui.settings.title": "Settings",
    "ui.settings.reader_backend": "Reader backend",
    "ui.settings.access_backend": "Access backend",
    "ui.settings.download_dir": "Download folder",
    "ui.settings.language": "Language",
    "ui.settings.beta_warnings": "Warn about BETA products",
    "ui.settings.save": "Save settings",
    "ui.settings.saved": "Settings saved.",
    "ui.settings.browse": "...",

    # Generic
    "ui.error": "Error",
    "ui.warning": "Warning",
    "ui.info": "Information",
    "ui.ok": "OK",
    "ui.status_beta": "BETA",
    "ui.status_provisional": "PROVISIONAL",
    "ui.status_validated": "VALIDATED",
    "ui.status_unknown": "UNKNOWN",
    "ui.units": "Units: {units}",

    # Preset: HV dB
    "preset.hv_db.name": "HV (Cross-pol), dB",
    "preset.hv_db.hint": "General vegetation volume: higher values indicate more scattering biomass.",
    "preset.hv_db.purpose": "Shows backscatter in cross-polarization. It arises mainly from multiple scattering in crowns, branches and stems, therefore well reflects vegetation structure and volume.",
    "preset.hv_db.when_to_use": "Forest vs non-forest maps, vegetation density comparison, basis for time series. Less suitable for very high biomass due to saturation.",
    "preset.hv_db.how_to_read": "Higher (less negative dB) means more vegetation volume. Bare soil and water give low values.",
    "preset.hv_db.formula": "10 * log10(HVHV)",
    "preset.hv_db.caveats": "Depends on vegetation and soil moisture, acquisition mode and angle. Do not directly compare values from different orbits/geometries.",

    # Preset: Cross-ratio
    "preset.cross_ratio.name": "Cross-ratio (HV/HH)",
    "preset.cross_ratio.hint": "Ratio of volume scattering to surface scattering — helps separate vegetation from soil.",
    "preset.cross_ratio.purpose": "Normalizes HV by HH, partially reducing the influence of overall scene brightness and incidence angle.",
    "preset.cross_ratio.when_to_use": "Separating open and vegetated areas, monitoring crop growth.",
    "preset.cross_ratio.how_to_read": "In dB — difference HV_dB - HH_dB. Higher values indicate a higher share of volume scattering.",
    "preset.cross_ratio.formula": "10*log10(HVHV/HHHH)",
    "preset.cross_ratio.caveats": "Sensitive to noise on weak signals (bare soil, water). Requires both HH and HV.",

    # Preset: RVI
    "preset.rvi.name": "RVI (Radar Vegetation Index)",
    "preset.rvi.hint": "Radar analog of 'greenness' index: 0 means almost no vegetation, higher is more.",
    "preset.rvi.purpose": "A single dimensionless vegetation density index, less dependent on scene brightness than raw backscatter.",
    "preset.rvi.when_to_use": "Crop seasonal dynamics, site comparison, cloudy situations where optical indices are unavailable.",
    "preset.rvi.how_to_read": "Usually takes values from 0 up to around 1; higher means denser vegetation cover.",
    "preset.rvi.formula": "dual-pol: 4*HV / (HH + HV); full-pol: 8*HV / (HH + VV + 2*HV)",
    "preset.rvi.caveats": "Not equivalent to NDVI and does not 'measure greenness' — reacts to structure and moisture. Formula is auto-selected by available polarizations.",

    # Preset: Time Series
    "preset.timeseries.name": "AOI Time Series",
    "preset.timeseries.hint": "How the signal changed on your area over dates: season, harvest, deforestation.",
    "preset.timeseries.purpose": "Computes statistics of a selected layer or index (mean, median, std) over polygons across dates and builds a graph and table.",
    "preset.timeseries.when_to_use": "Crop phenology, finding harvest or sowing dates, forest monitoring.",
    "preset.timeseries.how_to_read": "Smooth seasonal changes are normal; sharp jumps up or down are events (harvest, disturbance, moisture change).",
    "preset.timeseries.formula": "Time series statistical analysis",
    "preset.timeseries.caveats": "Do not mix BETA and PROVISIONAL; compare scenes from the same orbit and geometry.",

    # Preset: Change Detection
    "preset.change_db.name": "Change Detector (dB)",
    "preset.change_db.hint": "Shows where the signal significantly changed between two dates (e.g., deforestation).",
    "preset.change_db.purpose": "Difference between two scenes in dB and a binary mask based on a threshold.",
    "preset.change_db.when_to_use": "Fast search for forest disturbances, harvest, flooding after an event.",
    "preset.change_db.how_to_read": "Significant drop in HV often indicates loss of vegetation structure; increase — growth or wetting.",
    "preset.change_db.formula": "10 * log10(date2 / date1)",
    "preset.change_db.caveats": "Threshold is set by user; scenes must be from the same geometry.",

    # Preset: Speckle Filter
    "preset.speckle.name": "Speckle Filter",
    "preset.speckle.hint": "Smooths the 'graininess' of radar imagery for better visualization.",
    "preset.speckle.purpose": "Reduces speckle noise (median or box 3x3, 5x5, 7x7).",
    "preset.speckle.when_to_use": "Visualization and report maps. For quantitative analysis, consider if it's needed: the filter blurs details.",
    "preset.speckle.how_to_read": "Values remain in the same units, but lose fine details.",
    "preset.speckle.formula": "Median or uniform filtering",
    "preset.speckle.caveats": "Always saved as a separate layer; original scientific values are not overwritten.",

    # Preset: Pauli RGB
    "preset.pauli_rgb.name": "Pauli RGB (full-pol)",
    "preset.pauli_rgb.hint": "Color composite where color hints at the scattering mechanism.",
    "preset.pauli_rgb.purpose": "Combines polarization channels into RGB for quick visual separation of surface types.",
    "preset.pauli_rgb.when_to_use": "Scene overview: surface, double-bounce (buildings, trunks at water), volume scattering (crowns).",
    "preset.pauli_rgb.how_to_read": "Color-to-mechanism mapping depends on the chosen scheme — keep the legend nearby.",
    "preset.pauli_rgb.formula": "Pauli decomposition RGB composite",
    "preset.pauli_rgb.caveats": "Requires full-pol; this is a visualization, not a quantitative product. Planned for a later version.",

    # Preset: Freeman-Durden
    "preset.freeman_durden.name": "Freeman-Durden (full-pol)",
    "preset.freeman_durden.hint": "Splits the signal into surface, double-bounce and vegetation contributions.",
    "preset.freeman_durden.purpose": "Estimates the power share of three scattering mechanisms.",
    "preset.freeman_durden.when_to_use": "Forest / field / water / built-up separation, cover structure studies.",
    "preset.freeman_durden.how_to_read": "Three power layers; dominance of the volume component is typical for dense vegetation.",
    "preset.freeman_durden.formula": "Freeman-Durden three-component decomposition",
    "preset.freeman_durden.caveats": "Requires full-pol; known artifacts (e.g. negative powers) must be handled explicitly. Planned for a later version.",

    # Preset: H/A/alpha
    "preset.h_a_alpha.name": "H/A/alpha (full-pol)",
    "preset.h_a_alpha.hint": "Unsupervised classification by scattering type.",
    "preset.h_a_alpha.purpose": "Computes entropy (H), anisotropy (A) and alpha angle describing the randomness and type of scattering.",
    "preset.h_a_alpha.when_to_use": "Cover structure research, input for classification.",
    "preset.h_a_alpha.how_to_read": "High entropy — a mix of mechanisms (typical for forests); low — one dominant mechanism (e.g. smooth surface).",
    "preset.h_a_alpha.formula": "Cloude-Pottier decomposition",
    "preset.h_a_alpha.caveats": "Full-pol only; interpret with care without polarimetry experience. Planned for a later version.",
}

