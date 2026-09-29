# -*- coding: utf-8 -*-
"""
NISAR Vegetation — package initialization for the QGIS-independent core.
"""
import logging

# Single logger for the whole core package. QGIS GUI layer may additionally
# mirror messages into QgsMessageLog (see nisar_qgis/gui/*).
logging.getLogger("nisar").addHandler(logging.NullHandler())

__all__ = ["logging"]
