# -*- coding: utf-8 -*-
"""
NISAR windthrow DiD algorithm (P3): difference-in-differences coherence
change detection on a GUNW storm/control pair.

Thin QGIS wrapper around nisar_core.processing.windthrow — the heavy
work runs in the tested core module; this layer handles parameters,
optional reference polygons (validation metrics) and the optional
Hansen GFC forest mask.
"""
import os
from datetime import datetime

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm, QgsProcessingParameterFile,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterNumber, QgsProcessingParameterBoolean,
    QgsProcessingParameterString, QgsProcessingParameterFolderDestination,
    QgsProcessingParameterEnum,
    QgsProcessingException, QgsRasterLayer, QgsRasterMinMaxOrigin, QgsProcessingParameterFeatureSource,
)

from ..nisar_core.processing.windthrow import (
    run_windthrow_did, WindthrowParams,
)


def _config_dict():
    try:
        from ..config_manager import config_manager, config_as_dict
        return config_as_dict(config_manager.load())
    except Exception:
        return {}


class NisarWindthrowDidAlgorithm(QgsProcessingAlgorithm):
    """Windthrow detection: DiD of GUNW pair coherence."""

    def tr(self, string):
        return QCoreApplication.translate("NisarAlgorithms", string)

    def createInstance(self):
        # required by QGIS Processing (fresh instance for execution)
        return type(self)()

    def name(self):
        return "windthrow_did"

    def displayName(self):
        return self.tr("Windthrow DiD (GUNW pair)")

    def group(self):
        return self.tr("NISAR Vegetation")

    def groupId(self):
        return "nisar"

    def shortHelpString(self):
        return self._short_help()

    def _short_help(self) -> str:
        return self.tr(
            "Detects windthrow (storm damage) with the difference-in-"
            "differences scheme: dcoh = coherence(control pair) - "
            "coherence(storm pair) of two GUNW granules from the same "
            "track/frame. The storm pair must bracket the storm date; "
            "the control pair covers an adjacent 12-day interval. "
            "Adaptive threshold = median(background) + k * MAD, 3x3 "
            "median filter, minimum object size (defaults follow the "
            "validated sentinel1_windthrow study). Optional reference "
            "polygons enable AUC / excess / TPR@FPR5% metrics; the "
            "optional Hansen GFC forest mask restricts detection and "
            "background to forest-on-event-year (recommended).")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            "STORM", self.tr("Storm pair GUNW granule (.h5)"),
            extension="h5"))
        self.addParameter(QgsProcessingParameterFile(
            "CONTROL", self.tr("Control pair GUNW granule (.h5)"),
            extension="h5"))
        self.addParameter(QgsProcessingParameterString(
            "EVENT_DATE", self.tr("Storm date (YYYY-MM-DD, optional)"),
            defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            "REFERENCE", self.tr(
                "Reference damage polygons (optional, for metrics)"),
            optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            "FOREST_MASK", self.tr(
                "Restrict to Hansen GFC forest (online tiles)"),
            defaultValue=False))
        self.addParameter(QgsProcessingParameterEnum(
            "THRESHOLD_MODE", self.tr("Threshold rule"),
            options=[self.tr("median + a (reference plugin)"),
                     self.tr("median + k*MAD (article)")],
            defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            "A_COH", self.tr("Threshold: offset a (median + a)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.25))
        self.addParameter(QgsProcessingParameterNumber(
            "K_MAD", self.tr("Threshold: k (median + k*MAD)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.25))
        self.addParameter(QgsProcessingParameterNumber(
            "MIN_PIXELS", self.tr("Minimum object size (pixels)"),
            type=QgsProcessingParameterNumber.Integer, defaultValue=6))
        self.addParameter(QgsProcessingParameterFolderDestination(
            "OUTPUT_DIR", self.tr("Output directory (dcoh, mask, report)")))
        self.addParameter(QgsProcessingParameterRasterDestination(
            "OUTPUT", self.tr("dcoh raster")))

    def processAlgorithm(self, parameters, context, feedback):
        storm = self.parameterAsString(parameters, "STORM", context)
        control = self.parameterAsString(parameters, "CONTROL", context)
        for label, path in (("storm", storm), ("control", control)):
            if not path or not os.path.isfile(path):
                raise QgsProcessingException(
                    "Input %s GUNW granule not found: %r" % (label, path))

        event_date = None
        date_str = self.parameterAsString(parameters, "EVENT_DATE", context)
        if date_str:
            try:
                event_date = datetime.strptime(date_str.strip()[:10],
                                               "%Y-%m-%d")
            except ValueError:
                raise QgsProcessingException(
                    "Invalid event date %r (expected YYYY-MM-DD)" % date_str)

        mode_idx = int(self.parameterAsEnum(
            parameters, "THRESHOLD_MODE", context) or 0)
        params = WindthrowParams(
            threshold_mode=("mad" if mode_idx == 1 else "absolute"),
            a_coh=float(self.parameterAsDouble(parameters, "A_COH", context)),
            k_mad=float(self.parameterAsDouble(parameters, "K_MAD", context)),
            min_pixels=int(self.parameterAsInt(
                parameters, "MIN_PIXELS", context) or 6),
        )

        output_dir = self.parameterAsString(parameters, "OUTPUT_DIR", context)
        output = self.parameterAsOutputLayer(parameters, "OUTPUT", context)
        # write into the user-chosen raster destination if provided
        export_dcoh = bool(output and output.lower().endswith(
            (".tif", ".tiff")))
        if not export_dcoh:
            output = None

        ref_mask = None
        ref_source = self.parameterAsSource(parameters, "REFERENCE", context)
        if ref_source is not None:
            ref_mask = self._rasterize_reference(
                ref_source, storm, context, feedback)
            if ref_mask is None:
                feedback.pushWarning(
                    "Reference polygons could not be rasterized onto the "
                    "GUNW grid — metrics skipped")

        forest_mask = None
        if self.parameterAsBoolean(parameters, "FOREST_MASK", context):
            forest_mask = self._build_forest_mask(storm, event_date, feedback)
            if forest_mask is None:
                feedback.pushWarning(
                    "Hansen GFC forest mask unavailable (offline?) — "
                    "running without forest restriction")

        result = run_windthrow_did(
            storm, control,
            output_dir=output_dir or None,
            config=_config_dict(),
            params=params,
            ref_mask=ref_mask,
            forest_mask=forest_mask,
            event_date=event_date,
            progress_callback=(lambda p: feedback.setProgress(p))
            if feedback else None,
            is_canceled=(lambda: feedback.isCanceled()) if feedback else None,
            export_dcoh=export_dcoh,
            export_mask=True,
        )
        if not result.success:
            raise QgsProcessingException(result.error_message)

        if export_dcoh and result.output_paths:
            # run_windthrow_did wrote dcoh.tif into output_dir; move/copy
            # semantics: report the destination path to QGIS
            dcoh_path = [p for p in result.output_paths
                         if p.endswith("dcoh.tif")]
            if dcoh_path and output and output != dcoh_path[0]:
                try:
                    import shutil
                    shutil.move(dcoh_path[0], output)
                except Exception:  # pragma: no cover - cosmetic
                    output = dcoh_path[0]

        report = result.metadata or {}
        for warning in result.warnings:
            feedback.pushWarning(warning)
        metrics = report.get("metrics") or {}
        if metrics:
            feedback.pushInfo(
                "AUC=%.3f excess=%.3f TPR@FPR5%%=%.3f (n_ref=%s, n_bg=%s)"
                % (metrics.get("auc"), metrics.get("excess"),
                   metrics.get("tpr_fpr05"), metrics.get("n_ref"),
                   metrics.get("n_bg")))
        det = report.get("detection") or {}
        feedback.pushInfo(
            "Detected %s px (~%s ha) in %s objects; threshold=%.4f"
            % (det.get("pixels"), det.get("area_ha"), det.get("objects"),
               (report.get("threshold") or {}).get("value")))

        layer = None
        if output:
            layer = QgsRasterLayer(output, "NISAR dcoh")
            if layer.isValid():
                try:
                    renderer = layer.renderer()
                    if renderer is not None and hasattr(
                            renderer, "setMinMaxOrigin"):
                        origin = renderer.minMaxOrigin()
                        origin.setLimits(
                            QgsRasterMinMaxOrigin.CumulativeCut)
                        origin.setExtent(QgsRasterMinMaxOrigin.WholeRaster)
                        renderer.setMinMaxOrigin(origin)
                except Exception:  # pragma: no cover - cosmetic
                    pass
        return {"OUTPUT": output or "", "OUTPUT_DIR": output_dir,
                "REPORT": str(report)}

    # ----------------------------------------------------------------helpers
    def _rasterize_reference(self, source, storm_path, context, feedback):
        """Rasterize reference polygons onto the 80 m GUNW grid (bool).

        Uses a temporary GPKG + GDAL Rasterize with allTouched=True.
        Returns None when anything in the chain is unavailable.
        """
        try:
            from osgeo import gdal
            gdal.UseExceptions()
        except Exception:
            return None
        try:
            from qgis.core import (
                QgsVectorFileWriter, QgsProcessingUtils,
                QgsCoordinateReferenceSystem, QgsFields, QgsField,
                QgsWkbTypes,
            )
            from qgis.PyQt.QtCore import QVariant
        except Exception:
            return None

        try:
            from ..nisar_core.readers import ReaderRegistry
            handle = ReaderRegistry.open(storm_path, config=_config_dict())
            georef = handle.georef
            ReaderRegistry.close(handle)
            if georef is None or not georef.is_valid:
                return None

            gpkg = QgsProcessingUtils.generateTempFilename("ref_polygons.gpkg")
            fields = QgsFields()
            fields.append(QgsField("id", QVariant.Int))
            writer = QgsVectorFileWriter(
                gpkg, "utf-8", fields,
                QgsWkbTypes.Polygon,
                QgsCoordinateReferenceSystem(source.sourceCrs()))
            if writer.hasError():
                return None
            from qgis.core import QgsFeature
            for i, feature in enumerate(source.getFeatures()):
                geom = feature.geometry()
                if geom is None or geom.isEmpty():
                    continue
                if geom.isMultipart():
                    for part in geom.asGeometryCollection() or []:
                        f = QgsFeature(fields)
                        f.setGeometry(part)
                        f.setAttribute("id", i)
                        writer.addFeature(f)
                else:
                    out = QgsFeature(fields)
                    out.setGeometry(geom)
                    out.setAttribute("id", i)
                    writer.addFeature(out)
            del writer

            import tempfile
            import numpy as np
            tmp_fd, tmp_tif = tempfile.mkstemp(suffix=".tif")
            os.close(tmp_fd)
            drv = gdal.GetDriverByName("GTiff")
            ds = drv.Create(tmp_tif, georef.width, georef.height, 1,
                            gdal.GDT_Byte)
            ds.SetGeoTransform(list(georef.transform))
            if georef.crs_wkt:
                ds.SetProjection(georef.crs_wkt)
            elif georef.crs_authid:
                from osgeo import osr
                srs = osr.SpatialReference()
                srs.SetFromUserInput(georef.crs_authid)
                ds.SetProjection(srs.ExportToWkt())
            ds = None
            gdal.Rasterize(tmp_tif, gpkg, bands=[1], burnValues=[1],
                           allTouched=True)
            ds = gdal.Open(tmp_tif)
            mask = np.asarray(ds.ReadAsArray(), dtype=bool)
            ds = None
            for p in (tmp_tif,):
                try:
                    os.unlink(p)
                except OSError:
                    pass
            if mask.shape != (georef.height, georef.width):
                return None
            return mask
        except Exception as exc:  # pragma: no cover - best effort
            feedback.pushWarning("reference rasterization failed: %s" % exc)
            return None

    def _build_forest_mask(self, storm_path, event_date, feedback):
        """Hansen GFC forest mask on the GUNW grid (best effort)."""
        try:
            from ..nisar_core.readers import ReaderRegistry
            from ..nisar_core.processing.forest_mask import (
                forest_mask_for_grid, bbox_from_bounding_polygon,
            )
            handle = ReaderRegistry.open(storm_path, config=_config_dict())
            georef = handle.georef
            ident = handle.metadata.get("identification") or {}
            bbox = bbox_from_bounding_polygon(ident.get("boundingPolygon", ""))
            ReaderRegistry.close(handle)
            year = event_date.year if event_date else \
                datetime.now().year
            mask, warns = forest_mask_for_grid(georef, year=year,
                                               bbox_wgs84=bbox)
            for w in warns:
                feedback.pushWarning(w)
            return mask
        except Exception as exc:  # pragma: no cover - best effort
            feedback.pushWarning("forest mask failed: %s" % exc)
            return None
