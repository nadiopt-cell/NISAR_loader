# -*- coding: utf-8 -*-
"""
Cross-version QGIS API compatibility helpers.

Legacy level constants on QgsMessageLog (INFO / WARNING / CRITICAL)
existed up to ~QGIS 3.28 but were removed in newer releases (verified
missing in QGIS 3.44.14): the levels live in ``Qgis.MessageLevel`` since
QGIS 3.36 (``Qgis.Info`` / ``Qgis.Warning`` before that). Passing the raw
integer also works everywhere, so we resolve the best available form at
import time and fall back to the int values.
"""
try:  # QGIS >= 3.36
    from qgis.core import Qgis
    LEVEL_INFO = Qgis.MessageLevel.Info
    LEVEL_WARNING = Qgis.MessageLevel.Warning
    LEVEL_CRITICAL = Qgis.MessageLevel.Critical
except (AttributeError, ImportError):  # older QGIS / mocked environments
    LEVEL_INFO = 0        # Qgis.Info
    LEVEL_WARNING = 1    # Qgis.Warning
    LEVEL_CRITICAL = 2   # Qgis.Critical
