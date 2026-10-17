# -*- coding: utf-8 -*-
"""
NISAR Processing algorithms (MVP: hv_db, rvi, cross_ratio, export).

Each algorithm is a thin QGIS wrapper around nisar_core: parameters are
validated, the heavy work runs through the tiled core path, and the
result layer gets 2–98% stretch + preset metadata (AGENTS.md §6.0).
"""
import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm, QgsProcessingParameterFile,
    QgsProcessingParameterString, QgsProcessingParameterBoolean,
    QgsProcessingParameterRasterDestination, QgsProcessingException,
    QgsRasterLayer, QgsRasterMinMaxOrigin,
    QgsLayerMetadata,
)

from ..nisar_core.readers import ReaderRegistry
from ..nisar_core.processing.indices import (
    compute_index_to_raster, VegetationIndex,
)
from ..nisar_core.processing.export import ExportBackend
from ..nisar_core.presets import get_preset
from ..i18n import tr


def _config_dict():
    """Plugin config as plain dict for core calls (best effort)."""
    try:
        from ..config_manager import config_manager, config_as_dict
        return config_as_dict(config_manager.load())
    except Exception:
        return {}


class NisarAlgorithmBase(QgsProcessingAlgorithm):
    """Common behaviour for all NISAR algorithms."""

    PRESET_ID = None  # e.g. "hv_db"

    def tr(self, string):
        return QCoreApplication.translate("NisarAlgorithms", string)

    def createInstance(self):
        # required by QGIS Processing (fresh instance for execution);
        # subclasses take no ctor arguments
        return type(self)()

    def group(self):
        return self.tr("NISAR Vegetation")

    def groupId(self):
        return "nisar"

    def _short_help(self) -> str:
        preset = get_preset(self.PRESET_ID) if self.PRESET_ID else None
        if not preset:
            return ""
        parts = []
        for label, key in (("Purpose", preset.purpose_key),
                           ("When to use", preset.when_to_use_key),
                           ("How to read", preset.how_to_read_key),
                           ("Formula", preset.formula_key),
                           ("Caveats", preset.caveats_key)):
            text = tr(key)
            if text and text != key:
                parts.append("%s: %s" % (label, text))
        return "\n\n".join(parts)

    def _open_product(self, parameters, context):
        path = self.parameterAsString(parameters, "INPUT", context)
        if not path or not os.path.isfile(path):
            raise QgsProcessingException(
                "Input NISAR product not found: %r" % path)
        try:
            handle = ReaderRegistry.open(path, preferred="auto",
                                         config=_config_dict())
        except Exception as exc:
            raise QgsProcessingException("Cannot open product: %s" % exc)
        if handle.georef is None or not handle.georef.is_valid:
            raise QgsProcessingException(
                "The product has no valid georeference — refusing to "
                "produce a geo-referenced output (no CRS guessing).")
        return handle

    def _finish_layer(self, output_path: str, name: str, feedback,
                      preset_id=None):
        layer = QgsRasterLayer(output_path, name)
        if not layer.isValid():
            raise QgsProcessingException(
                "Output raster could not be re-opened: %s" % output_path)
        try:
            renderer = layer.renderer()
            if renderer is not None and hasattr(renderer, "setMinMaxOrigin"):
                origin = renderer.minMaxOrigin()
                origin.setLimits(QgsRasterMinMaxOrigin.CumulativeCut)
                origin.setExtent(QgsRasterMinMaxOrigin.WholeRaster)
                renderer.setMinMaxOrigin(origin)
        except Exception:  # pragma: no cover - cosmetic
            pass

        preset = get_preset(preset_id) if preset_id else None
        if preset:
            try:
                meta = QgsLayerMetadata()
                meta.setAbstract("%s\n\n%s" % (tr(preset.purpose_key),
                                               tr(preset.how_to_read_key)))
                layer.setMetadata(meta)
            except Exception:  # pragma: no cover - cosmetic
                pass
        return layer


class NisarHvDbAlgorithm(NisarAlgorithmBase):
    """HV cross-polarization backscatter in dB (preset: hv_db)."""

    PRESET_ID = "hv_db"

    def name(self):
        return "hv_db"

    def displayName(self):
        return self.tr("HV backscatter in dB")

    def shortHelpString(self):
        return self._short_help()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            "INPUT", self.tr("NISAR GCOV product (.h5)"),
            extension="h5"))
        self.addParameter(QgsProcessingParameterRasterDestination(
            "OUTPUT", self.tr("HV dB raster")))

    def processAlgorithm(self, parameters, context, feedback):
        handle = self._open_product(parameters, context)
        output = self.parameterAsOutputLayer(parameters, "OUTPUT", context)

        result = compute_index_to_raster(
            handle, VegetationIndex.HV_DB, output, config=_config_dict(),
            progress_callback=(lambda p: feedback.setProgress(p))
            if feedback else None,
            is_canceled=(lambda: feedback.isCanceled()) if feedback else None)
        if not result.success:
            raise QgsProcessingException(result.error_message)
        ReaderRegistry.close(handle)

        layer = self._finish_layer(output, "NISAR HV dB", feedback, "hv_db")
        return {"OUTPUT": output, "OUTPUT_LAYER": layer}


class NisarCrossRatioAlgorithm(NisarAlgorithmBase):
    """Cross-ratio HV/HH in dB (preset: cross_ratio)."""

    PRESET_ID = "cross_ratio"

    def name(self):
        return "cross_ratio"

    def displayName(self):
        return self.tr("Cross-ratio HV/HH (dB)")

    def shortHelpString(self):
        return self._short_help()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            "INPUT", self.tr("NISAR GCOV product (.h5)"),
            extension="h5"))
        self.addParameter(QgsProcessingParameterRasterDestination(
            "OUTPUT", self.tr("Cross-ratio raster")))

    def processAlgorithm(self, parameters, context, feedback):
        handle = self._open_product(parameters, context)
        output = self.parameterAsOutputLayer(parameters, "OUTPUT", context)

        result = compute_index_to_raster(
            handle, VegetationIndex.CROSS_RATIO, output,
            config=_config_dict(),
            progress_callback=(lambda p: feedback.setProgress(p))
            if feedback else None,
            is_canceled=(lambda: feedback.isCanceled()) if feedback else None)
        if not result.success:
            raise QgsProcessingException(result.error_message)
        ReaderRegistry.close(handle)

        layer = self._finish_layer(output, "NISAR cross-ratio", feedback,
                                   "cross_ratio")
        return {"OUTPUT": output, "OUTPUT_LAYER": layer}


class NisarRviAlgorithm(NisarAlgorithmBase):
    """Radar Vegetation Index (preset: rvi)."""

    PRESET_ID = "rvi"

    def name(self):
        return "rvi"

    def displayName(self):
        return self.tr("RVI (Radar Vegetation Index)")

    def shortHelpString(self):
        return self._short_help()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            "INPUT", self.tr("NISAR GCOV product (.h5)"),
            extension="h5"))
        self.addParameter(QgsProcessingParameterRasterDestination(
            "OUTPUT", self.tr("RVI raster")))

    def processAlgorithm(self, parameters, context, feedback):
        handle = self._open_product(parameters, context)
        output = self.parameterAsOutputLayer(parameters, "OUTPUT", context)

        result = compute_index_to_raster(
            handle, VegetationIndex.RVI, output, config=_config_dict(),
            progress_callback=(lambda p: feedback.setProgress(p))
            if feedback else None,
            is_canceled=(lambda: feedback.isCanceled()) if feedback else None)
        if not result.success:
            raise QgsProcessingException(result.error_message)
        ReaderRegistry.close(handle)

        layer = self._finish_layer(output, "NISAR RVI", feedback, "rvi")
        return {"OUTPUT": output, "OUTPUT_LAYER": layer}


class NisarExportAlgorithm(NisarAlgorithmBase):
    """Export a GCOV layer to Float32 GeoTIFF / COG (preset: export)."""

    PRESET_ID = None

    def name(self):
        return "export"

    def displayName(self):
        return self.tr("Export GCOV layer to GeoTIFF/COG")

    def shortHelpString(self):
        return self.tr(
            "Exports one layer of a NISAR GCOV product to a Float32 "
            "GeoTIFF (optionally COG). The source .h5 file is never "
            "modified. Values keep their original linear gamma-0 units; "
            "dB conversion and stretches are display-only.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            "INPUT", self.tr("NISAR GCOV product (.h5)"),
            extension="h5"))
        self.addParameter(QgsProcessingParameterString(
            "LAYER", self.tr("Layer name (e.g. HVHV)"),
            defaultValue="HVHV"))
        self.addParameter(QgsProcessingParameterBoolean(
            "COG", self.tr("Write Cloud Optimized GeoTIFF (overviews)"),
            defaultValue=False))
        self.addParameter(QgsProcessingParameterRasterDestination(
            "OUTPUT", self.tr("Exported raster")))

    def processAlgorithm(self, parameters, context, feedback):
        handle = self._open_product(parameters, context)
        layer_name = self.parameterAsString(parameters, "LAYER", context)
        output = self.parameterAsOutputLayer(parameters, "OUTPUT", context)
        cog = self.parameterAsBoolean(parameters, "COG", context)

        if not handle.get_layer(layer_name):
            known = ", ".join(l.name for l in handle.layers[:20])
            ReaderRegistry.close(handle)
            raise QgsProcessingException(
                "Layer %r not found in the product. Available: %s"
                % (layer_name, known))

        exporter = ExportBackend(dict(_config_dict(), cog=cog))
        result = exporter.export_layer(
            handle, layer_name, output,
            tile_size=int(_config_dict().get("tile_size", 512)),
            progress_callback=(lambda p: feedback.setProgress(p))
            if feedback else None,
            is_canceled=(lambda: feedback.isCanceled()) if feedback else None)
        if not result.success:
            raise QgsProcessingException(result.error_message)
        ReaderRegistry.close(handle)

        layer = self._finish_layer(output, "NISAR %s" % layer_name, feedback)
        return {"OUTPUT": output, "OUTPUT_LAYER": layer}
