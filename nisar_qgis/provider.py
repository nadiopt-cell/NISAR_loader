# -*- coding: utf-8 -*-
"""
NISAR Processing Provider — registers all plugin algorithms.
"""
import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon


class NisarProvider(QgsProcessingProvider):
    """Processing provider for NISAR algorithms."""

    def id(self):
        return "nisar"

    def name(self):
        return "NISAR Vegetation"

    def longName(self):
        return "NISAR Vegetation (search, open, vegetation indices, export)"

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__),
                                  "resources", "icon.png")
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QIcon()

    def loadAlgorithms(self):
        from .algorithms import (
            NisarHvDbAlgorithm, NisarCrossRatioAlgorithm,
            NisarRviAlgorithm, NisarExportAlgorithm,
            NisarWindthrowDidAlgorithm,
        )
        for algorithm_class in (NisarHvDbAlgorithm,
                                NisarCrossRatioAlgorithm,
                                NisarRviAlgorithm,
                                NisarExportAlgorithm,
                                NisarWindthrowDidAlgorithm):
            self.addAlgorithm(algorithm_class())
