# -*- coding: utf-8 -*-
"""
Background tasks (QgsTask) — search, download, processing, export.

All heavy work runs here so the GUI stays responsive (TZ principle 4).
Progress/results are delivered to the GUI thread via Qt signals
(queued connections), never by touching widgets from run().
"""
import logging
from pathlib import Path

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import QgsTask, QgsMessageLog

from ..nisar_core.access.base import DownloadProgress
from ..nisar_core.models import SceneRecord, SearchParameters

logger = logging.getLogger("nisar.gui.tasks")


class TaskSignals(QObject):
    """Shared signals for all plugin tasks (emitted from worker threads)."""
    progress = pyqtSignal(int)                       # percent 0..100
    download_progress = pyqtSignal(object)            # DownloadProgress
    finished_ok = pyqtSignal(object)                  # result payload
    finished_error = pyqtSignal(str)                  # error message


class NisarSearchTask(QgsTask):
    """Scene search in a background thread."""

    def __init__(self, params: SearchParameters, backend_class, config):
        super().__init__(self.tr("NISAR scene search"), QgsTask.CanCancel)
        self.params = params
        self.backend_class = backend_class
        self.config = config
        self.signals = TaskSignals()
        self._scenes = []

    def run(self):
        try:
            backend = self.backend_class(self.config)
            self.setProgress(10)
            if self.isCanceled():
                return False
            scenes = backend.search(self.params)
            if self.isCanceled():
                return False
            self._scenes = scenes
            self.setProgress(100)
            return True
        except Exception as exc:
            logger.exception("Search task failed")
            self._error = str(exc)
            return False

    def finished(self, success):
        if success:
            self.signals.finished_ok.emit(self._scenes)
        else:
            msg = getattr(self, "_error", "Search failed")
            QgsMessageLog.logMessage("NISAR search failed: %s" % msg,
                                     "NISAR", level=QgsMessageLog.WARNING)
            self.signals.finished_error.emit(msg)


class NisarDownloadTask(QgsTask):
    """Download of a single scene with progress and cancellation."""

    def __init__(self, scene: SceneRecord, output_dir: Path,
                 backend, config):
        super().__init__(self.tr("Downloading %s" % scene.scene_id[:40]),
                         QgsTask.CanCancel)
        self.scene = scene
        self.output_dir = Path(output_dir)
        self.backend = backend
        self.config = config
        self.signals = TaskSignals()

    def run(self):
        def progress_cb(prog: DownloadProgress):
            if self.isCanceled():
                return
            self.signals.download_progress.emit(prog)
            if prog.total_bytes > 0:
                self.setProgress(int(100.0 * prog.bytes_downloaded
                                     / prog.total_bytes))

        try:
            path = self.backend.download(self.scene, self.output_dir,
                                         progress_callback=progress_cb)
            self._path = str(path)
            self.setProgress(100)
            return True
        except Exception as exc:
            logger.exception("Download task failed")
            self._error = str(exc)
            return False

    def finished(self, success):
        if success:
            QgsMessageLog.logMessage(
                "Downloaded %s -> %s" % (self.scene.scene_id, self._path),
                "NISAR", level=QgsMessageLog.INFO)
            self.signals.finished_ok.emit(
                DownloadProgress(scene_id=self.scene.scene_id,
                                 bytes_downloaded=self.scene.size_bytes,
                                 total_bytes=self.scene.size_bytes,
                                 status="completed",
                                 file_path=self._path))
        else:
            msg = getattr(self, "_error", "Download failed")
            self.signals.finished_error.emit(msg)


class NisarComputeTask(QgsTask):
    """Vegetation index computation, tiled, straight to a GeoTIFF."""

    def __init__(self, handle, index_id: str, output_path, config, cog=False):
        super().__init__(self.tr("NISAR: computing %s" % index_id),
                         QgsTask.CanCancel)
        self.handle = handle
        self.index_id = index_id
        self.output_path = str(output_path)
        self.config = config
        self.cog = cog
        self.signals = TaskSignals()

    def run(self):
        from ..nisar_core.processing.indices import compute_index_to_raster

        def is_canceled():
            return self.isCanceled()

        try:
            result = compute_index_to_raster(
                self.handle, self.index_id, self.output_path,
                config=self.config,
                progress_callback=self.setProgress,
                is_canceled=is_canceled,
                cog=self.cog)
            if not result.success and "Cancelled" in result.warnings:
                return False
            self._result = result
            return bool(result.success)
        except Exception as exc:
            logger.exception("Compute task failed")
            self._error = str(exc)
            return False

    def finished(self, success):
        if success:
            self.signals.finished_ok.emit(self._result)
        else:
            msg = getattr(self, "_error", "Processing failed")
            if getattr(self, "_result", None) and self._result.error_message:
                msg = self._result.error_message
            QgsMessageLog.logMessage("NISAR processing failed: %s" % msg,
                                     "NISAR", level=QgsMessageLog.WARNING)
            self.signals.finished_error.emit(msg)


class NisarExportTask(QgsTask):
    """Layer export to GeoTIFF/COG, tiled."""

    def __init__(self, handle, layer_name: str, output_path, config,
                 cog=False):
        super().__init__(self.tr("NISAR: exporting %s" % layer_name),
                         QgsTask.CanCancel)
        self.handle = handle
        self.layer_name = layer_name
        self.output_path = str(output_path)
        self.config = config
        self.cog = cog
        self.signals = TaskSignals()

    def run(self):
        from ..nisar_core.processing.export import ExportBackend

        try:
            exporter = ExportBackend(dict(self.config or {}, cog=self.cog))
            result = exporter.export_layer(
                self.handle, self.layer_name, self.output_path,
                tile_size=int((self.config or {}).get("tile_size", 512)),
                progress_callback=self.setProgress,
                is_canceled=self.isCanceled)
            self._result = result
            return bool(result.success)
        except Exception as exc:
            logger.exception("Export task failed")
            self._error = str(exc)
            return False

    def finished(self, success):
        if success:
            self.signals.finished_ok.emit(self._result)
        else:
            msg = getattr(self, "_error", "Export failed")
            if getattr(self, "_result", None) and self._result.error_message:
                msg = self._result.error_message
            self.signals.finished_error.emit(msg)
