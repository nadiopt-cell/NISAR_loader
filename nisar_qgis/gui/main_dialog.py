# -*- coding: utf-8 -*-
"""
Main dialog for the NISAR Vegetation plugin.

Tabs: Search -> Download -> Open -> Processing -> Export -> Settings.
All long operations (search / download / compute / export) run in
QgsTask threads (gui/tasks.py); the GUI thread only updates widgets via
Qt signals.
"""
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from qgis.PyQt.QtCore import Qt, QSize, QUrl
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QCheckBox,
    QFormLayout, QMessageBox, QGroupBox, QApplication, QTextBrowser,
)
from qgis.PyQt.QtGui import QColor, QFont, QPixmap, QDesktopServices
from qgis.core import (
    QgsProject, QgsRasterLayer, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsGeometry, QgsMessageLog, QgsRectangle,
    QgsWkbTypes,
)
from qgis.gui import QgsRubberBand

from ..config_manager import config_manager, config_as_dict
from ..i18n import tr, set_language
from ..nisar_core.config import ReaderBackend, AccessBackend
from ..nisar_core.models import ProductType, DataStatus
from ..nisar_core.readers import ReaderRegistry
from ..nisar_core.presets import PRESETS, get_preset, list_presets
from ..nisar_core.access.preview import scene_summary_pairs
from .tasks import (
    NisarSearchTask, NisarDownloadTask, NisarComputeTask, NisarExportTask,
    NisarPreviewTask, NisarWindthrowTask,
)

logger = logging.getLogger("nisar.gui.dialog")

# Presets implemented in this MVP (NumPy backend); the rest are shown
# disabled with the reason from the registry (AGENTS.md §6.0.5).
MVP_PRESETS = ("hv_db", "cross_ratio", "rvi")

_STATUS_COLORS = {
    DataStatus.BETA: QColor(215, 95, 40),          # orange-red
    DataStatus.PROVISIONAL: QColor(60, 150, 70),   # green
    DataStatus.VALIDATED: QColor(40, 120, 215),    # blue
    DataStatus.UNKNOWN: QColor(130, 130, 130),     # gray
}


def _esc_html(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


class NisarMainDialog(QDialog):
    """Main GUI for the NISAR Vegetation plugin."""

    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self.config = config_manager.load()
        set_language(self.config.language)

        self._handle = None            # current ProductHandle (Open tab)
        self._scenes = []              # last search results
        self._tasks = []               # keep references to running tasks
        self._tr_widgets = []          # (widget, key, attr) retranslation
        self._layer_checkboxes = {}    # row -> QCheckBox
        self._preview_scene = None     # scene shown in the preview panel
        self._preview_task = None      # running thumbnail fetch (P2.5)
        self._footprint_band = None    # QgsRubberBand on the map canvas
        self._preview_extent = None    # footprint bbox in canvas CRS

        self.setWindowTitle(tr("plugin.name"))
        self.resize(980, 640)
        self._build_ui()
        self._retranslate()

    # ================================================================= UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        self.tab_search = self._create_search_tab()
        self.tab_download = self._create_download_tab()
        self.tab_open = self._create_open_tab()
        self.tab_process = self._create_process_tab()
        self.tab_windthrow = self._create_windthrow_tab()
        self.tab_export = self._create_export_tab()
        self.tab_settings = self._create_settings_tab()

        for widget, key in (
                (self.tab_search, "ui.tab_search"),
                (self.tab_download, "ui.tab_download"),
                (self.tab_open, "ui.tab_open"),
                (self.tab_process, "ui.tab_process"),
                (self.tab_windthrow, "ui.tab_windthrow"),
                (self.tab_export, "ui.tab_export"),
                (self.tab_settings, "ui.tab_settings")):
            idx = self.tabs.addTab(widget, key)
            self.tabs.setTabText(idx, tr(key))

        layout.addWidget(self.tabs)

        self.preset_table.itemSelectionChanged.connect(
            self._on_preset_selected)

    # ------------------------------------------------------------- Search
    def _create_search_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)

        filter_panel = QGroupBox()
        filter_layout = QFormLayout(filter_panel)
        self._bind(filter_panel, "ui.search.title", "title")

        self.search_aoi_btn = QPushButton()
        self._bind(self.search_aoi_btn, "ui.search.use_map_extent", "text")
        self.search_aoi_btn.clicked.connect(self._on_aoi_clicked)

        self.search_start = QLineEdit()
        self.search_start.setPlaceholderText("YYYY-MM-DD")
        self.search_end = QLineEdit()
        self.search_end.setPlaceholderText("YYYY-MM-DD")

        self.search_product = QComboBox()
        self.search_product.addItems([p.value for p in ProductType
                                      if p is not ProductType.UNKNOWN])

        self.search_btn = QPushButton()
        self._bind(self.search_btn, "ui.search.button", "text")
        self.search_btn.setStyleSheet("font-weight: bold;")
        self.search_btn.clicked.connect(self._on_search_clicked)

        self.search_hint = QLabel()
        self._bind(self.search_hint, "ui.search.aoi_hint", "text")
        self.search_hint.setWordWrap(True)

        filter_layout.addRow(self.search_aoi_btn)
        filter_layout.addRow(tr("ui.search.start_date"), self.search_start)
        filter_layout.addRow(tr("ui.search.end_date"), self.search_end)
        filter_layout.addRow(tr("ui.search.product_type"), self.search_product)
        filter_layout.addRow(self.search_btn)
        filter_layout.addRow(self.search_hint)

        results_panel = QGroupBox()
        self._bind(results_panel, "ui.search.results", "title")
        results_layout = QVBoxLayout(results_panel)
        self.results_table = QTableWidget(0, 5)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.results_table.itemSelectionChanged.connect(
            self._on_scene_selected)
        self.results_table.cellDoubleClicked.connect(
            self._on_scene_double_clicked)
        results_layout.addWidget(self.results_table, 1)
        results_layout.addWidget(self._create_preview_panel())

        layout.addWidget(filter_panel, 1)
        layout.addWidget(results_panel, 3)
        return widget

    # ------------------------------------------------------------- Preview
    def _create_preview_panel(self) -> QWidget:
        """Quicklook + details + footprint preview before download (P2.5)."""
        panel = QGroupBox()
        self._bind(panel, "ui.preview.title", "title")
        row = QHBoxLayout(panel)

        self.preview_image = QLabel()
        self.preview_image.setMinimumSize(220, 220)
        self.preview_image.setAlignment(Qt.AlignCenter)
        self.preview_image.setWordWrap(True)
        self.preview_image.setStyleSheet("background: #2b2b2b;"
                                         "color: #bbbbbb;")
        self.preview_image.setText(tr("ui.preview.hint"))
        row.addWidget(self.preview_image)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)

        self.preview_details = QTextBrowser()
        self.preview_details.setOpenExternalLinks(False)
        self.preview_details.setMaximumHeight(160)
        side_layout.addWidget(self.preview_details)

        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_zoom_btn = QPushButton()
        self._bind(self.preview_zoom_btn, "ui.preview.zoom", "text")
        self.preview_zoom_btn.clicked.connect(self._on_zoom_to_scene)
        self.preview_zoom_btn.setEnabled(False)
        self.preview_open_browse_btn = QPushButton()
        self._bind(self.preview_open_browse_btn, "ui.preview.open_browse",
                   "text")
        self.preview_open_browse_btn.clicked.connect(self._on_open_browse)
        self.preview_open_browse_btn.setEnabled(False)
        btn_layout.addWidget(self.preview_zoom_btn)
        btn_layout.addWidget(self.preview_open_browse_btn)
        btn_layout.addStretch()
        side_layout.addWidget(btn_row)

        self.preview_status = QLabel("")
        self.preview_status.setWordWrap(True)
        self.preview_status.setStyleSheet("color: #555; font-size: 11px;")
        side_layout.addWidget(self.preview_status)

        row.addWidget(side, 1)
        return panel

    # ----------------------------------------------------------- Download
    def _create_download_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox()
        self._bind(group, "ui.download.title", "title")
        group_layout = QVBoxLayout(group)

        self.download_table = QTableWidget(0, 3)
        self.download_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.download_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        group_layout.addWidget(self.download_table)

        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        self.download_btn = QPushButton()
        self._bind(self.download_btn, "ui.download.button", "text")
        self.download_btn.clicked.connect(self._on_download_clicked)
        self.download_cancel_btn = QPushButton()
        self._bind(self.download_cancel_btn, "ui.download.cancel", "text")
        self.download_cancel_btn.clicked.connect(self._on_cancel_downloads)
        btn_layout.addWidget(self.download_btn)
        btn_layout.addWidget(self.download_cancel_btn)
        btn_layout.addStretch()
        group_layout.addWidget(btn_row)

        self.netrc_hint = QLabel()
        self._bind(self.netrc_hint, "ui.download.hint_netrc", "text")
        self.netrc_hint.setWordWrap(True)
        self.netrc_hint.setStyleSheet("color: #555; font-size: 11px;")
        group_layout.addWidget(self.netrc_hint)

        layout.addWidget(group)
        layout.addStretch()
        return widget

    # --------------------------------------------------------------- Open
    def _create_open_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox()
        self._bind(group, "ui.open.title", "title")
        form = QFormLayout(group)

        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        self.open_path = QLineEdit()
        self.open_browse = QPushButton()
        self._bind(self.open_browse, "ui.open.browse", "text")
        self.open_browse.clicked.connect(self._on_browse_h5)
        path_layout.addWidget(self.open_path, 1)
        path_layout.addWidget(self.open_browse)
        form.addRow(tr("ui.open.file_label"), path_row)

        self.open_inspect_btn = QPushButton()
        self._bind(self.open_inspect_btn, "ui.open.inspect", "text")
        self.open_inspect_btn.clicked.connect(self._on_inspect_clicked)
        form.addRow(self.open_inspect_btn)

        self.open_status = QLabel("")
        self.open_status.setWordWrap(True)
        form.addRow(self.open_status)

        self.layers_table = QTableWidget(0, 5)
        self.layers_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.layers_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.layers_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)

        self.add_layers_btn = QPushButton()
        self._bind(self.add_layers_btn, "ui.open.add_selected", "text")
        self.add_layers_btn.clicked.connect(self._on_add_layers_clicked)
        self.add_layers_btn.setEnabled(False)

        layers_group = QGroupBox()
        self._bind(layers_group, "ui.open.layers", "title")
        layers_layout = QVBoxLayout(layers_group)
        layers_layout.addWidget(self.layers_table)
        layers_layout.addWidget(self.add_layers_btn)

        layout.addWidget(group)
        layout.addWidget(layers_group, 1)
        return widget

    # ---------------------------------------------------------- Processing
    def _create_process_tab(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)

        preset_panel = QGroupBox()
        self._bind(preset_panel, "ui.process.title", "title")
        preset_layout = QVBoxLayout(preset_panel)

        self.preset_table = QTableWidget(0, 2)
        self.preset_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.preset_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preset_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        preset_layout.addWidget(self.preset_table)

        detail_panel = QGroupBox()
        self._bind(detail_panel, "ui.process.details", "title")
        detail_layout = QVBoxLayout(detail_panel)
        self.detail_view = QTextBrowser()
        self.detail_view.setOpenExternalLinks(False)
        detail_layout.addWidget(self.detail_view)

        self.run_process_btn = QPushButton()
        self._bind(self.run_process_btn, "ui.process.run", "text")
        self.run_process_btn.setEnabled(False)
        self.run_process_btn.clicked.connect(self._on_process_clicked)
        detail_layout.addWidget(self.run_process_btn)

        layout.addWidget(preset_panel, 2)
        layout.addWidget(detail_panel, 3)
        return widget

    # ---------------------------------------------------------- Windthrow
    def _create_windthrow_tab(self) -> QWidget:
        """Windthrow DiD tab (P3): storm + control GUNW pair -> dcoh."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox()
        self._bind(group, "ui.windthrow.title", "title")
        form = QFormLayout(group)

        self.wt_storm_path = QLineEdit()
        self.wt_storm_path.setPlaceholderText(
            tr("ui.windthrow.storm_placeholder"))
        wt_storm_btn = QPushButton("…")
        wt_storm_btn.clicked.connect(
            lambda: self._browse_h5_into(self.wt_storm_path))
        storm_row = QHBoxLayout()
        storm_row.addWidget(self.wt_storm_path, 1)
        storm_row.addWidget(wt_storm_btn)
        form.addRow(tr("ui.windthrow.storm"), storm_row)

        self.wt_control_path = QLineEdit()
        self.wt_control_path.setPlaceholderText(
            tr("ui.windthrow.control_placeholder"))
        wt_control_btn = QPushButton("…")
        wt_control_btn.clicked.connect(
            lambda: self._browse_h5_into(self.wt_control_path))
        control_row = QHBoxLayout()
        control_row.addWidget(self.wt_control_path, 1)
        control_row.addWidget(wt_control_btn)
        form.addRow(tr("ui.windthrow.control"), control_row)

        self.wt_event_date = QLineEdit()
        self.wt_event_date.setPlaceholderText("YYYY-MM-DD")
        form.addRow(tr("ui.windthrow.event_date"), self.wt_event_date)

        self.wt_threshold_mode = QComboBox()
        self.wt_threshold_mode.addItem(tr("ui.windthrow.mode_absolute"),
                                       "absolute")
        self.wt_threshold_mode.addItem(tr("ui.windthrow.mode_mad"), "mad")
        form.addRow(tr("ui.windthrow.threshold_mode"),
                    self.wt_threshold_mode)

        self.wt_a_coh = QLineEdit("0.25")
        self.wt_a_coh.setEnabled(False)
        form.addRow(tr("ui.windthrow.a_coh"), self.wt_a_coh)

        self.wt_k_mad = QLineEdit("0.25")
        self.wt_k_mad.setEnabled(False)
        form.addRow(tr("ui.windthrow.k_mad"), self.wt_k_mad)

        def _sync_threshold_fields(mode: str):
            self.wt_a_coh.setEnabled(mode == "absolute")
            self.wt_k_mad.setEnabled(mode == "mad")

        self.wt_threshold_mode.currentIndexChanged.connect(
            lambda _:
            _sync_threshold_fields(
                self.wt_threshold_mode.currentData() or "absolute"))
        _sync_threshold_fields("absolute")

        self.wt_min_pixels = QLineEdit("6")
        form.addRow(tr("ui.windthrow.min_pixels"), self.wt_min_pixels)

        self.wt_forest_chk = QCheckBox()
        self._bind(self.wt_forest_chk, "ui.windthrow.forest_mask", "text")
        self.wt_forest_chk.setChecked(True)
        form.addRow(self.wt_forest_chk)

        self.wt_polygonize_chk = QCheckBox()
        self._bind(self.wt_polygonize_chk, "ui.windthrow.polygonize", "text")
        form.addRow(self.wt_polygonize_chk)

        self.wt_output_dir = QLineEdit()
        wt_dir_btn = QPushButton("…")
        wt_dir_btn.clicked.connect(self._browse_wt_output_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.wt_output_dir, 1)
        dir_row.addWidget(wt_dir_btn)
        form.addRow(tr("ui.windthrow.output_dir"), dir_row)

        self.wt_run_btn = QPushButton()
        self._bind(self.wt_run_btn, "ui.windthrow.run", "text")
        self.wt_run_btn.setStyleSheet("font-weight: bold;")
        self.wt_run_btn.clicked.connect(self._on_windthrow_clicked)
        form.addRow(self.wt_run_btn)

        self.wt_status = QLabel()
        self.wt_status.setWordWrap(True)
        form.addRow(self.wt_status)

        layout.addWidget(group)

        self.wt_report = QTextBrowser()
        self.wt_report.setOpenExternalLinks(False)
        self._bind(self.wt_report, "ui.windthrow.report_hint", "plainText")
        layout.addWidget(self.wt_report, 1)
        return widget

    def _browse_h5_into(self, line_edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("ui.open.file_label"), "",
            "NISAR products (*.h5 *.hdf5 *.he5);;All files (*)")
        if path:
            line_edit.setText(path)

    def _browse_wt_output_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, tr("ui.windthrow.output_dir"))
        if path:
            self.wt_output_dir.setText(path)

    def _on_windthrow_clicked(self):
        from ..nisar_core.processing.windthrow import (
            WindthrowParams, check_pair_compatibility,
        )
        storm = self.wt_storm_path.text().strip()
        control = self.wt_control_path.text().strip()
        if not storm or not os.path.isfile(storm):
            QMessageBox.warning(self, tr("ui.error"),
                                tr("ui.windthrow.no_storm"))
            return
        if not control or not os.path.isfile(control):
            QMessageBox.warning(self, tr("ui.error"),
                                tr("ui.windthrow.no_control"))
            return

        event_date = None
        date_str = self.wt_event_date.text().strip()
        if date_str:
            try:
                event_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
            except ValueError:
                QMessageBox.warning(
                    self, tr("ui.error"),
                    tr("ui.windthrow.bad_date").format(value=date_str))
                return

        # quick pair compatibility pre-check (opens both files briefly)
        try:
            handle_s = ReaderRegistry.open(
                storm, config=config_as_dict(self.config))
            try:
                handle_c = ReaderRegistry.open(
                    control, config=config_as_dict(self.config))
                try:
                    compat = check_pair_compatibility(
                        handle_s, handle_c, event_date)
                finally:
                    ReaderRegistry.close(handle_c)
            finally:
                ReaderRegistry.close(handle_s)
        except Exception as exc:
            QMessageBox.critical(
                self, tr("ui.error"),
                tr("ui.windthrow.open_failed").format(error=exc))
            return
        if not compat.compatible:
            QMessageBox.warning(
                self, tr("ui.warning"),
                tr("ui.windthrow.incompatible").format(
                    issues="; ".join(compat.issues)))
            return
        for warning in compat.warnings:
            self.wt_status.setText(
                tr("ui.windthrow.pair_warning").format(warning=warning))

        try:
            mode = self.wt_threshold_mode.currentData() or "absolute"
            params = WindthrowParams(
                threshold_mode=mode,
                a_coh=float(self.wt_a_coh.text().strip() or 0.25),
                k_mad=float(self.wt_k_mad.text().strip() or 0.25),
                min_pixels=int(self.wt_min_pixels.text().strip() or 6))
        except ValueError:
            QMessageBox.warning(self, tr("ui.error"),
                                tr("ui.windthrow.bad_params"))
            return

        output_dir = self.wt_output_dir.text().strip()
        if not output_dir:
            output_dir = str(Path(self.config.download_dir) / "windthrow")
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        task = NisarWindthrowTask(
            storm, control, output_dir,
            config=config_as_dict(self.config),
            params=params,
            event_date=event_date,
            polygonize=self.wt_polygonize_chk.isChecked(),
            build_forest_mask=self.wt_forest_chk.isChecked())
        task.signals.finished_ok.connect(
            lambda result, t=task: self._on_windthrow_done(t, result))
        task.signals.finished_error.connect(self._on_windthrow_error)
        self._tasks.append(task)
        self.wt_run_btn.setEnabled(False)
        self.wt_status.setText(tr("ui.windthrow.running"))
        self.wt_report.setPlainText("")
        from qgis.core import QgsApplication
        QgsApplication.taskManager().addTask(task)

    def _on_windthrow_done(self, task, result):
        self.wt_run_btn.setEnabled(True)
        if not result.success:
            self._on_windthrow_error(result.error_message or "failed")
            return
        self.wt_status.setText(tr("ui.windthrow.done"))
        report = result.metadata or {}
        self.wt_report.setPlainText(self._format_windthrow_report(report))

        # add outputs to the project
        for path in result.output_paths:
            if path.endswith("dcoh.tif"):
                self._add_raster_layer(path, "NISAR dcoh (DiD)",
                                       "Windthrow")
            elif path.endswith("windthrow_mask.tif"):
                self._add_raster_layer(path, "NISAR windthrow mask",
                                       "Windthrow")
            elif path.endswith(".gpkg"):
                try:
                    from qgis.core import QgsVectorLayer
                    layer = QgsVectorLayer(
                        path, "NISAR windthrow detections", "ogr")
                    if layer.isValid():
                        QgsProject.instance().addMapLayer(layer)
                except Exception:  # pragma: no cover - cosmetic
                    pass

    def _format_windthrow_report(self, report: dict) -> str:
        lines = []
        background = report.get("background") or {}
        threshold = report.get("threshold") or {}
        detection = report.get("detection") or {}
        metrics = report.get("metrics") or {}
        lines.append(tr("ui.windthrow.r_method") +
                     ": %s" % report.get("method", ""))
        lines.append("%s: %s" % (tr("ui.windthrow.r_storm"),
                                 report.get("storm_pair")))
        lines.append("%s: %s" % (tr("ui.windthrow.r_control"),
                                 report.get("control_pair")))
        lines.append("%s: %s | %s" % (
            tr("ui.windthrow.r_layer"), report.get("polarization"),
            report.get("layer")))
        lines.append("%s: %s" % (
            tr("ui.windthrow.r_background"),
            background.get("n_pixels")))
        lines.append("%s: %.4f (%s)" % (
            tr("ui.windthrow.r_threshold"),
            float(threshold.get("value") or 0.0),
            threshold.get("rule")))
        lines.append("%s: %s px | %.1f ha | %s %s" % (
            tr("ui.windthrow.r_detection"),
            detection.get("pixels"),
            float(detection.get("area_ha") or 0.0),
            detection.get("objects"),
            tr("ui.windthrow.r_objects")))
        if report.get("flags"):
            lines.append("%s: %s" % (tr("ui.windthrow.r_flags"),
                                     ", ".join(report["flags"])))
        if metrics:
            lines.append("%s: AUC=%.3f | excess=%.3f | TPR@FPR5%%=%.3f "
                         "(n_ref=%s, n_bg=%s)" % (
                             tr("ui.windthrow.r_metrics"),
                             metrics.get("auc"), metrics.get("excess"),
                             metrics.get("tpr_fpr05"),
                             metrics.get("n_ref"), metrics.get("n_bg")))
        for warning in report.get("warnings") or []:
            lines.append("⚠ %s" % warning)
        return "\n".join(lines)

    def _on_windthrow_error(self, message):
        self.wt_run_btn.setEnabled(True)
        self.wt_status.setText(
            tr("ui.windthrow.failed").format(error=message))
        QMessageBox.warning(self, tr("ui.error"), message)

    # -------------------------------------------------------------- Export
    def _create_export_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox()
        self._bind(group, "ui.export.title", "title")
        form = QFormLayout(group)

        self.export_layer_combo = QComboBox()
        form.addRow(tr("ui.export.source_layer"), self.export_layer_combo)

        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        self.export_path = QLineEdit()
        self.export_browse = QPushButton()
        self._bind(self.export_browse, "ui.export.browse", "text")
        self.export_browse.clicked.connect(self._on_browse_export)
        path_layout.addWidget(self.export_path, 1)
        path_layout.addWidget(self.export_browse)
        form.addRow(tr("ui.export.path"), path_row)

        self.export_cog = QCheckBox()
        self._bind(self.export_cog, "ui.export.cog", "text")
        self.export_cog.setChecked(False)
        form.addRow(self.export_cog)

        self.do_export_btn = QPushButton()
        self._bind(self.do_export_btn, "ui.export.button", "text")
        self.do_export_btn.clicked.connect(self._on_export_clicked)
        self.do_export_btn.setEnabled(False)
        form.addRow(self.do_export_btn)

        layout.addWidget(group)
        layout.addStretch()
        return widget

    # ------------------------------------------------------------ Settings
    def _create_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox()
        self._bind(group, "ui.settings.title", "title")
        form = QFormLayout(group)

        self.set_reader = QComboBox()
        for item in ReaderRegistry.list_registered():
            label = item["name"] if item["available"] else \
                "%s (%s)" % (item["name"], item["reason"])
            self.set_reader.addItem(label, item["id"])
        self.set_reader.insertItem(0, "auto", "auto")
        form.addRow(tr("ui.settings.reader_backend"), self.set_reader)

        self.set_access = QComboBox()
        from ..nisar_core.access import AccessRegistry
        for item in AccessRegistry.list_registered():
            label = item["name"] if item["available"] else \
                "%s (%s)" % (item["name"], item["reason"])
            self.set_access.addItem(label, item["id"])
        self.set_access.insertItem(0, "auto", "auto")
        form.addRow(tr("ui.settings.access_backend"), self.set_access)

        dir_row = QWidget()
        dir_layout = QHBoxLayout(dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        self.set_download_dir = QLineEdit(str(self.config.download_dir))
        self.set_download_dir_btn = QPushButton()
        self._bind(self.set_download_dir_btn, "ui.settings.browse", "text")
        self.set_download_dir_btn.clicked.connect(self._on_browse_download_dir)
        dir_layout.addWidget(self.set_download_dir, 1)
        dir_layout.addWidget(self.set_download_dir_btn)
        form.addRow(tr("ui.settings.download_dir"), dir_row)

        self.set_language = QComboBox()
        self.set_language.addItem("English", "en")
        self.set_language.addItem("Русский", "ru")
        form.addRow(tr("ui.settings.language"), self.set_language)

        self.set_beta_warn = QCheckBox()
        self._bind(self.set_beta_warn, "ui.settings.beta_warnings", "text")
        self.set_beta_warn.setChecked(self.config.show_beta_warnings)
        form.addRow(self.set_beta_warn)

        self.save_settings_btn = QPushButton()
        self._bind(self.save_settings_btn, "ui.settings.save", "text")
        self.save_settings_btn.clicked.connect(self._on_save_settings)
        form.addRow(self.save_settings_btn)

        # current values
        self.set_reader.setCurrentIndex(max(0, self.set_reader.findData(
            self.config.reader_backend.value)))
        self.set_access.setCurrentIndex(max(0, self.set_access.findData(
            self.config.access_backend.value)))
        self.set_language.setCurrentIndex(max(0, self.set_language.findData(
            self.config.language)))

        layout.addWidget(group)
        layout.addStretch()
        return widget

    # ======================================================== retranslate
    def _bind(self, widget, key, attr):
        """Register a widget text for retranslation."""
        self._tr_widgets.append((widget, key, attr))

    def _retranslate(self):
        for i in range(self.tabs.count()):
            key = self.tabs.tabData(i) or self.tabs.tabText(i)
            if str(key).startswith("ui."):
                self.tabs.setTabText(i, tr(str(key)))
        for widget, key, attr in self._tr_widgets:
            try:
                setattr(widget, attr, tr(key))
            except Exception:  # pragma: no cover
                pass
        self._update_table_headers()

    def _update_table_headers(self):
        self.results_table.setHorizontalHeaderLabels([
            tr("ui.search.col_scene"), tr("ui.search.col_date"),
            tr("ui.search.col_status"), tr("ui.search.col_size"),
            tr("ui.search.col_select")])
        self.download_table.setHorizontalHeaderLabels([
            tr("ui.download.col_scene"), tr("ui.download.col_progress"),
            tr("ui.download.col_status")])
        self.layers_table.setHorizontalHeaderLabels([
            tr("ui.open.col_layer"), tr("ui.open.col_pol"),
            tr("ui.open.col_units"), tr("ui.open.col_size"),
            tr("ui.search.col_select")])
        self.preset_table.setHorizontalHeaderLabels([
            tr("ui.process.col_preset"), tr("ui.process.col_available")])

    # ============================================================== Search
    def _on_aoi_clicked(self):
        """Take the current map canvas extent as AOI (WKT, EPSG:4326)."""
        try:
            canvas = self.iface.mapCanvas()
            extent = canvas.extent()
            crs_src = canvas.mapSettings().destinationCrs()
            crs_dst = QgsCoordinateReferenceSystem("EPSG:4326")
            if crs_src != crs_dst:
                transform = QgsCoordinateTransform(
                    crs_src, crs_dst, QgsProject.instance())
                geometry = QgsGeometry.fromRect(extent)
                if not geometry.transform(transform) == 0:
                    raise RuntimeError("coordinate transform failed")
                self._current_aoi_wkt = geometry.asWkt()
            else:
                self._current_aoi_wkt = QgsGeometry.fromRect(extent).asWkt()
            self.search_hint.setText(tr("ui.search.aoi_wkt")
                                     + ": " + self._current_aoi_wkt[:60] + "...")
        except Exception as exc:
            QMessageBox.warning(self, tr("ui.warning"), str(exc))

    def _on_search_clicked(self):
        from ..nisar_core.access import AccessRegistry
        from ..nisar_core.models import SearchParameters

        # Choose an online backend explicitly (auto prefers B2).
        online = [b for b in AccessRegistry.list_registered()
                  if b["id"] in ("B2_asf_search", "B3_earthaccess")
                  and b["available"]]
        if not online:
            reasons = [b["reason"] for b in AccessRegistry.list_registered()
                       if b["id"] in ("B2_asf_search", "B3_earthaccess")]
            QMessageBox.information(
                self, tr("ui.info"),
                tr("ui.search.backend_unavailable").format(
                    reason="; ".join(r for r in reasons if r) or "n/a"))
            return

        params = SearchParameters()
        for field, widget in (("start", self.search_start),
                              ("end", self.search_end)):
            text = widget.text().strip()
            if text:
                try:
                    setattr(params, field + "_date",
                            datetime.strptime(text, "%Y-%m-%d"))
                except ValueError:
                    QMessageBox.warning(
                        self, tr("ui.error"),
                        tr("ui.search.%s_date" % field) +
                        " — YYYY-MM-DD")
                    return

        try:
            params.product_types = [
                ProductType(self.search_product.currentText())]
        except ValueError:
            params.product_types = [ProductType.GCOV]
        params.aoi_wkt = getattr(self, "_current_aoi_wkt", None)
        params.max_results = 100

        preferred = self.config.access_backend.value
        try:
            backend_class = AccessRegistry.select_backend(preferred)
            if backend_class.BACKEND_ID == "B1_local":
                # auto mode with no online backend — should not happen here
                raise RuntimeError("no online backend")
        except Exception:
            backend_class = AccessRegistry.select_backend(
                online[0]["id"])

        self.search_btn.setEnabled(False)
        self.search_btn.setText(tr("ui.search.searching"))
        task = NisarSearchTask(params, backend_class,
                               config_as_dict(self.config))
        task.signals.finished_ok.connect(self._on_search_done)
        task.signals.finished_error.connect(self._on_search_error)
        self._tasks.append(task)
        from qgis.core import QgsApplication
        QgsApplication.taskManager().addTask(task)

    def _on_search_done(self, scenes):
        self.search_btn.setEnabled(True)
        self.search_btn.setText(tr("ui.search.button"))
        self._scenes = list(scenes or [])
        self._clear_preview()

        self.results_table.setRowCount(0)
        beta_found = False
        for scene in self._scenes:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)

            item_id = QTableWidgetItem(scene.scene_id)
            item_id.setToolTip(scene.scene_id)
            self.results_table.setItem(row, 0, item_id)

            date_str = scene.acquisition_time.strftime("%Y-%m-%d") \
                if scene.acquisition_time else ""
            self.results_table.setItem(row, 1, QTableWidgetItem(date_str))

            status_item = QTableWidgetItem(
                tr("ui.status_%s" % scene.status.value.lower()))
            status_item.setForeground(
                _STATUS_COLORS.get(scene.status, QColor(0, 0, 0)))
            font = QFont()
            font.setBold(scene.status is DataStatus.BETA)
            status_item.setFont(font)
            self.results_table.setItem(row, 2, status_item)
            beta_found = beta_found or scene.is_beta

            size_gb = scene.size_bytes / (1024.0 ** 3) if scene.size_bytes else 0
            self.results_table.setItem(
                row, 3, QTableWidgetItem("%.2f GB" % size_gb if size_gb else "—"))

            chk = QCheckBox()
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.results_table.setCellWidget(row, 4, chk_widget)

        if beta_found and self.config.show_beta_warnings:
            QMessageBox.warning(self, tr("ui.warning"),
                                tr("ui.search.beta_warning"))
        if not self._scenes:
            QMessageBox.information(self, tr("ui.info"),
                                    tr("ui.search.no_results"))

    def _on_search_error(self, message):
        self.search_btn.setEnabled(True)
        self.search_btn.setText(tr("ui.search.button"))
        QMessageBox.critical(self, tr("ui.error"), message)

    # ============================================================== Preview
    def _scene_for_row(self, row):
        """SceneRecord for a results-table row (by scene id)."""
        if row < 0 or not self._scenes:
            return None
        item = self.results_table.item(row, 0)
        if item is None:
            return None
        for scene in self._scenes:
            if scene.scene_id == item.text():
                return scene
        return None

    def _on_scene_selected(self):
        items = self.results_table.selectedItems()
        scene = self._scene_for_row(items[0].row()) if items else None
        if scene is None:
            self._clear_preview()
            return
        self._show_scene_preview(scene)

    def _on_scene_double_clicked(self, row, _column):
        self._on_zoom_to_scene()

    def _show_scene_preview(self, scene):
        """Details + footprint + quicklook for the selected scene."""
        self._preview_scene = scene
        rows = []
        for key, value in scene_summary_pairs(scene):
            rows.append("<tr><td><b>%s</b></td><td>%s</td></tr>"
                        % (_esc_html(tr(key)), _esc_html(value)))
        self.preview_details.setHtml(
            "<table width='100%%' cellspacing='4'>%s</table>"
            % "".join(rows))

        self._show_footprint(scene)
        self._load_preview_image(scene)
        self.preview_open_browse_btn.setEnabled(bool(
            scene.urls.get("browse_full") or scene.urls.get("browse")
            or scene.urls.get("browse_native")))

    def _show_footprint(self, scene):
        """Draw the scene footprint (EPSG:4326) on the map canvas."""
        self._clear_footprint_band()
        try:
            if not scene.footprint_wkt:
                return
            geometry = QgsGeometry.fromWkt(scene.footprint_wkt)
            if geometry is None or geometry.isNull():
                return
            canvas = self.iface.mapCanvas()
            src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            dst_crs = canvas.mapSettings().destinationCrs()
            if src_crs != dst_crs:
                transform = QgsCoordinateTransform(
                    src_crs, dst_crs, QgsProject.instance())
                if geometry.transform(transform) != 0:
                    raise RuntimeError("footprint transform failed")
            band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
            band.setFillColor(QColor(255, 200, 0, 40))
            band.setStrokeColor(QColor(255, 160, 0, 220))
            band.setWidth(2)
            band.setToGeometry(geometry, None)
            self._footprint_band = band
            self._preview_extent = QgsRectangle(geometry.boundingBox())
            self.preview_zoom_btn.setEnabled(True)
        except Exception as exc:
            logger.warning("Footprint preview failed: %s", exc)
            self._footprint_band = None
            self._preview_extent = None
            self.preview_zoom_btn.setEnabled(False)

    def _clear_footprint_band(self):
        if self._footprint_band is not None:
            try:
                self._footprint_band.reset()
            except Exception:  # pragma: no cover - cosmetic
                pass
            self._footprint_band = None
        self._preview_extent = None
        self.preview_zoom_btn.setEnabled(False)

    def _load_preview_image(self, scene):
        """Fetch the quicklook thumbnail in the background (P2.5)."""
        if self._preview_task is not None:
            try:
                self._preview_task.cancel()
            except Exception:  # pragma: no cover
                pass
            self._preview_task = None
        url = scene.urls.get("browse_thumbnail") or scene.urls.get("browse")
        if not url:
            self.preview_image.setPixmap(QPixmap())
            self.preview_image.setText(tr("ui.preview.unavailable"))
            self.preview_status.setText("")
            return
        self.preview_image.setPixmap(QPixmap())
        self.preview_image.setText(tr("ui.preview.loading"))
        self.preview_status.setText(tr("ui.preview.loading"))

        task = NisarPreviewTask(url, scene.scene_id)
        task.setProperty("scene_id", scene.scene_id)
        task.signals.finished_ok.connect(
            lambda data, t=task: self._on_preview_loaded(t, data))
        task.signals.finished_error.connect(
            lambda message, t=task: self._on_preview_failed(t, message))
        self._preview_task = task
        self._tasks.append(task)
        from qgis.core import QgsApplication
        QgsApplication.taskManager().addTask(task)

    def _on_preview_loaded(self, task, data):
        if self._preview_task is not None and task is not self._preview_task:
            return  # superseded by a newer selection
        self._preview_task = None
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self._on_preview_failed(task, "cannot decode image")
            return
        self.preview_status.setText("")
        self.preview_image.setText("")
        self.preview_image.setPixmap(pixmap.scaled(
            self.preview_image.size(), Qt.KeepAspectRatio,
            Qt.SmoothTransformation))

    def _on_preview_failed(self, task, message):
        if self._preview_task is not None and task is not self._preview_task:
            return
        self._preview_task = None
        self.preview_image.setText(tr("ui.preview.unavailable"))
        self.preview_status.setText(
            tr("ui.preview.failed").format(error=message))

    def _clear_preview(self):
        self._preview_scene = None
        self._clear_footprint_band()
        if self._preview_task is not None:
            try:
                self._preview_task.cancel()
            except Exception:  # pragma: no cover
                pass
            self._preview_task = None
        self.preview_image.setPixmap(QPixmap())
        self.preview_image.setText(tr("ui.preview.hint"))
        self.preview_details.setHtml("")
        self.preview_status.setText("")
        self.preview_zoom_btn.setEnabled(False)
        self.preview_open_browse_btn.setEnabled(False)

    def _on_zoom_to_scene(self):
        """Zoom the map to the selected scene's footprint."""
        extent = self._preview_extent
        if extent is None:
            return
        try:
            canvas = self.iface.mapCanvas()
            rect = QgsRectangle(extent)
            try:
                rect.scale(1.15)  # a little context around the footprint
            except Exception:  # pragma: no cover - cosmetic
                pass
            canvas.setExtent(rect)
            canvas.refresh()
        except Exception as exc:
            QMessageBox.warning(self, tr("ui.warning"), str(exc))

    def _on_open_browse(self):
        """Open the full-resolution browse image in the default viewer."""
        scene = self._preview_scene
        if not scene:
            return
        url = (scene.urls.get("browse_full") or scene.urls.get("browse")
               or scene.urls.get("browse_native"))
        if not url:
            return
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception as exc:
            QMessageBox.warning(self, tr("ui.warning"), str(exc))

    # ============================================================= Download
    def _on_download_clicked(self):
        from qgis.core import QgsApplication
        from ..nisar_core.access import AccessRegistry

        selected = self._selected_scenes()
        if not selected:
            QMessageBox.information(self, tr("ui.info"),
                                    tr("ui.download.no_scenes"))
            return

        try:
            backend_class = AccessRegistry.select_backend(
                self.config.access_backend.value)
            if backend_class.BACKEND_ID == "B1_local":
                raise ValueError("local backend cannot download")
            backend = backend_class(config_as_dict(self.config))
        except Exception as exc:
            QMessageBox.critical(
                self, tr("ui.error"),
                tr("ui.search.backend_unavailable").format(reason=str(exc)))
            return

        download_dir = Path(self.config.download_dir)
        self.download_table.setRowCount(0)
        for scene in selected:
            row = self.download_table.rowCount()
            self.download_table.insertRow(row)
            self.download_table.setItem(row, 0,
                                        QTableWidgetItem(scene.scene_id))
            self.download_table.setItem(row, 1, QTableWidgetItem("0%"))
            self.download_table.setItem(row, 2, QTableWidgetItem("…"))

            task = NisarDownloadTask(scene, download_dir, backend,
                                     config_as_dict(self.config))
            task.signals.download_progress.connect(
                self._on_download_progress)
            task.signals.finished_ok.connect(self._on_download_done)
            task.signals.finished_error.connect(self._on_download_failed)
            self._tasks.append(task)
            QgsApplication.taskManager().addTask(task)

    def _selected_scenes(self):
        selected = []
        if not self._scenes:
            return selected
        for row in range(self.results_table.rowCount()):
            chk_widget = self.results_table.cellWidget(row, 4)
            if chk_widget:
                chk = chk_widget.findChild(QCheckBox)
                if chk and chk.isChecked():
                    scene_id = self.results_table.item(row, 0).text()
                    for scene in self._scenes:
                        if scene.scene_id == scene_id:
                            selected.append(scene)
                            break
        return selected

    def _on_download_progress(self, progress):
        self._update_download_row(progress.scene_id,
                                  percent=None, status=progress.status)

    def _on_download_done(self, progress):
        self._update_download_row(progress.scene_id, percent="100%",
                                  status=tr("ui.download.done").format(
                                      path=progress.file_path))

    def _on_download_failed(self, message):
        QMessageBox.critical(self, tr("ui.error"),
                             tr("ui.download.failed").format(error=message))

    def _update_download_row(self, scene_id, percent=None, status=None):
        for row in range(self.download_table.rowCount()):
            item = self.download_table.item(row, 0)
            if item and item.text() == scene_id:
                if percent is not None:
                    self.download_table.setItem(row, 1,
                                                QTableWidgetItem(percent))
                if status is not None:
                    self.download_table.setItem(row, 2,
                                                QTableWidgetItem(status))
                return

    def _on_cancel_downloads(self):
        for task in list(self._tasks):
            if isinstance(task, NisarDownloadTask):
                task.cancel()

    # ================================================================== Open
    def _on_browse_h5(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("ui.open.file_label"), "",
            "NISAR products (*.h5 *.hdf5 *.he5);;All files (*)")
        if path:
            self.open_path.setText(path)
            self._on_inspect_clicked()

    def _on_inspect_clicked(self):
        path = self.open_path.text().strip()
        if not path:
            QMessageBox.information(self, tr("ui.info"),
                                    tr("ui.open.no_file"))
            return
        if not os.path.isfile(path):
            QMessageBox.warning(
                self, tr("ui.error"),
                tr("ui.open.open_failed").format(error=path))
            return

        # Close the previous handle.
        if self._handle is not None:
            try:
                ReaderRegistry.close(self._handle)
            except Exception:  # pragma: no cover
                pass
            self._handle = None

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            handle = ReaderRegistry.open(
                path, preferred=self.config.reader_backend.value,
                config=config_as_dict(self.config))
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self.open_status.setText("")
            QMessageBox.critical(
                self, tr("ui.error"),
                tr("ui.open.open_failed").format(error=exc))
            return
        QApplication.restoreOverrideCursor()

        self._handle = handle
        self._populate_layers_table()
        self._populate_preset_table()
        self._populate_export_combo()

        # Identification summary + status hint (P1.5 warning).
        ident = handle.metadata.get("identification", {}) or {}
        reasons = handle.georef.warnings if handle.georef else ["no georef"]
        if handle.georef is None or not handle.georef.is_valid:
            QMessageBox.warning(
                self, tr("ui.warning"),
                tr("ui.open.georef_warning").format(reasons="; ".join(reasons)))
            self.open_status.setText(
                tr("ui.open.georef_warning").format(
                    reasons="; ".join(reasons)))
        else:
            self.open_status.setText(
                "%s | %s | %s | %s | %s×%s | %s" % (
                    ident.get("granuleId", os.path.basename(path))[:60],
                    ident.get("productType", "?"),
                    ident.get("zeroDopplerStartTime", "?"),
                    ident.get("orbitPassDirection", "?"),
                    handle.georef.width, handle.georef.height,
                    handle.georef.crs_authid or "no CRS"))

    def _populate_layers_table(self):
        handle = self._handle
        self.layers_table.setRowCount(0)
        self._layer_checkboxes = {}
        if not handle:
            return
        for layer in handle.layers:
            row = self.layers_table.rowCount()
            self.layers_table.insertRow(row)
            self.layers_table.setItem(row, 0, QTableWidgetItem(layer.name))
            self.layers_table.setItem(row, 1, QTableWidgetItem(
                layer.polarization.value if layer.polarization else "—"))
            self.layers_table.setItem(row, 2, QTableWidgetItem(layer.units))
            self.layers_table.setItem(row, 3, QTableWidgetItem(
                "%d×%d" % (layer.shape[0], layer.shape[1])))
            chk = QCheckBox()
            # Real covariance layers are pre-checked (TZ P2.4: selected
            # layers, not "everything").
            from ..nisar_core.readers.product_layers import (
                GCOV_REAL_COVARIANCE_TERMS)
            chk.setChecked(layer.name in GCOV_REAL_COVARIANCE_TERMS)
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.layers_table.setCellWidget(row, 4, chk_widget)
            self._layer_checkboxes[row] = chk
        self.add_layers_btn.setEnabled(bool(handle.layers))

    def _on_add_layers_clicked(self):
        """Export selected layers to cached GeoTIFF and add to the project."""
        from qgis.core import QgsApplication

        handle = self._handle
        if not handle:
            QMessageBox.information(self, tr("ui.info"),
                                    tr("ui.open.no_file"))
            return
        selected = []
        for row, chk in self._layer_checkboxes.items():
            if chk.isChecked():
                name = self.layers_table.item(row, 0).text()
                layer = handle.get_layer(name)
                if layer:
                    selected.append(layer.name)
        if not selected:
            QMessageBox.information(self, tr("ui.info"),
                                    tr("ui.download.no_scenes"))
            return

        cache_dir = Path(self.config.cache_dir) / "layers"
        cache_dir.mkdir(parents=True, exist_ok=True)
        base = os.path.splitext(os.path.basename(handle.source_path))[0]
        base = re.sub(r"[^A-Za-z0-9_.-]", "_", base)[:60]

        self.add_layers_btn.setEnabled(False)
        for name in selected:
            out_path = cache_dir / ("%s_%s.tif" % (base, name))
            task = NisarExportTask(handle, name, out_path,
                                   config_as_dict(self.config), cog=False)
            task.setProperty("layer_name", name)
            task.setProperty("group_base", base)
            task.signals.finished_ok.connect(
                lambda result, t=task: self._on_layer_exported(t, result))
            task.signals.finished_error.connect(
                lambda message, t=task: self._on_export_error(message))
            self._tasks.append(task)
            QgsApplication.taskManager().addTask(task)

    def _on_layer_exported(self, task, result):
        layer_name = task.property("layer_name") or "layer"
        group_base = task.property("group_base") or "NISAR"
        self.add_layers_btn.setEnabled(True)
        if not result.success or not result.output_paths:
            self._on_export_error(result.error_message or "export failed")
            return
        self._add_raster_layer(result.output_paths[0], layer_name, group_base)

    def _add_raster_layer(self, tif_path: str, layer_name: str,
                          group_base: str):
        """Add a raster layer into the 'NISAR / <granule>' layer group."""
        layer = QgsRasterLayer(tif_path, layer_name)
        if not layer.isValid():
            QMessageBox.warning(self, tr("ui.error"),
                                "Invalid raster layer: %s" % tif_path)
            return

        # Explicit CRS from the product georef (never guessed).
        georef = self._handle.georef if self._handle else None
        if georef is not None:
            crs = None
            if georef.crs_wkt:
                crs = QgsCoordinateReferenceSystem.fromOgcWkt(georef.crs_wkt)
            if (crs is None or not crs.isValid()) and georef.crs_authid:
                crs = QgsCoordinateReferenceSystem(georef.crs_authid)
            if crs is not None and crs.isValid():
                layer.setCrs(crs)

        # 2–98% cumulative-cut stretch for display only (values unchanged).
        try:
            from qgis.core import QgsRasterMinMaxOrigin
            renderer = layer.renderer()
            if renderer is not None and hasattr(renderer, "setMinMaxOrigin"):
                origin = renderer.minMaxOrigin()
                origin.setLimits(QgsRasterMinMaxOrigin.CumulativeCut)
                origin.setExtent(QgsRasterMinMaxOrigin.WholeRaster)
                renderer.setMinMaxOrigin(origin)
        except Exception:  # pragma: no cover - cosmetic only
            pass

        QgsProject.instance().addMapLayer(layer, False)
        root = QgsProject.instance().layerTreeRoot()
        top = root.findGroup("NISAR")
        if top is None:
            top = root.insertGroup(0, "NISAR")
        sub = top.findGroup(group_base)
        if sub is None:
            sub = top.addGroup(group_base)
        sub.addLayer(layer)

    # ============================================================ Processing
    def _populate_preset_table(self):
        handle = self._handle
        self.preset_table.setRowCount(0)
        for preset in list_presets():
            row = self.preset_table.rowCount()
            self.preset_table.insertRow(row)
            name = tr(preset.name_key)
            self.preset_table.setItem(row, 0, QTableWidgetItem(name))
            self.preset_table.item(row, 0).setData(Qt.UserRole, preset.id)

            if preset.id in MVP_PRESETS:
                available, reason = preset.check_availability(handle)
            else:
                available = False
                reason = tr("preset.%s.caveats" % preset.id)
            status = tr("ui.ok") if available else reason
            item = QTableWidgetItem(status[:80])
            if not available:
                item.setForeground(QColor(130, 130, 130))
            self.preset_table.setItem(row, 1, item)

    def _on_preset_selected(self):
        items = self.preset_table.selectedItems()
        if not items:
            self.run_process_btn.setEnabled(False)
            return
        row = items[0].row()
        preset_id_item = self.preset_table.item(row, 0)
        if preset_id_item is None:
            return
        preset_id = preset_id_item.data(Qt.UserRole)
        preset = get_preset(preset_id)
        if not preset:
            self.run_process_btn.setEnabled(False)
            return

        available, reason = (preset.check_availability(self._handle)
                             if preset.id in MVP_PRESETS else (False, ""))

        self.detail_view.setHtml(self._preset_html(preset))
        can_run = preset.id in MVP_PRESETS and available and self._handle
        self.run_process_btn.setEnabled(can_run)
        if preset.id in MVP_PRESETS and not available:
            self.run_process_btn.setToolTip(
                tr("ui.process.requires").format(req=reason))
        else:
            self.run_process_btn.setToolTip("")

    def _preset_html(self, preset) -> str:
        def esc(text):
            return (str(text).replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;"))
        rows = []
        for label, key in (("purpose", preset.purpose_key),
                           ("when to use", preset.when_to_use_key),
                           ("how to read", preset.how_to_read_key),
                           ("formula", preset.formula_key),
                           ("caveats", preset.caveats_key)):
            text = tr(key)
            if key and text:
                rows.append("<b>%s</b>: %s" % (esc(label), esc(text)))
        return "<h3>%s</h3><p>%s</p>" % (
            esc(tr(preset.name_key)), "<br><br>".join(rows))

    def _on_process_clicked(self):
        from qgis.core import QgsApplication

        items = self.preset_table.selectedItems()
        if not items or self._handle is None:
            QMessageBox.information(self, tr("ui.info"),
                                    tr("ui.process.no_product"))
            return
        row = items[0].row()
        preset_id = self.preset_table.item(row, 0).data(Qt.UserRole)
        if preset_id not in MVP_PRESETS:
            return

        cache_dir = Path(self.config.cache_dir) / "indices"
        cache_dir.mkdir(parents=True, exist_ok=True)
        base = re.sub(r"[^A-Za-z0-9_.-]", "_",
                      os.path.splitext(os.path.basename(
                          self._handle.source_path))[0])[:50]
        out_path = cache_dir / ("%s_%s.tif" % (base, preset_id))

        self.run_process_btn.setEnabled(False)
        self.run_process_btn.setText(tr("ui.process.running"))
        task = NisarComputeTask(self._handle, preset_id, out_path,
                                config_as_dict(self.config))
        task.setProperty("preset_id", preset_id)
        task.signals.finished_ok.connect(
            lambda result, t=task: self._on_process_done(t, result))
        task.signals.finished_error.connect(
            lambda message: self._on_process_error(message))
        self._tasks.append(task)
        QgsApplication.taskManager().addTask(task)

    def _on_process_done(self, task, result):
        preset_id = task.property("preset_id") or "index"
        self.run_process_btn.setEnabled(True)
        self.run_process_btn.setText(tr("ui.process.run"))
        if not result.success or not result.output_paths:
            self._on_process_error(result.error_message or "processing failed")
            return
        tif_path = result.output_paths[0]
        preset = get_preset(preset_id)
        layer_name = tr(preset.name_key) if preset else preset_id
        self._add_raster_layer(tif_path, layer_name[:40], "NISAR indices")

        # Record 'how to read' + formula on the layer (AGENTS.md §6.0.4).
        layer = QgsProject.instance().mapLayersByName(layer_name[:40])
        if layer and preset:
            lyr = layer[-1]
            lyr.setCustomProperty("nisar/preset", preset_id)
            lyr.setCustomProperty("nisar/formula",
                                  result.metadata.get("formula", ""))
            lyr.setCustomProperty("nisar/how_to_read", tr(preset.how_to_read_key))
            try:
                from qgis.core import QgsLayerMetadata
                meta = lyr.metadata()
                meta.setAbstract("%s\n\nFormula: %s\n%s" % (
                    tr(preset.purpose_key),
                    result.metadata.get("formula", ""),
                    tr(preset.how_to_read_key)))
                lyr.setMetadata(meta)
            except Exception:  # pragma: no cover - cosmetic
                pass

    def _on_process_error(self, message):
        self.run_process_btn.setEnabled(True)
        self.run_process_btn.setText(tr("ui.process.run"))
        QMessageBox.critical(
            self, tr("ui.error"),
            tr("ui.process.failed").format(error=message))

    # ================================================================ Export
    def _populate_export_combo(self):
        self.export_layer_combo.clear()
        if not self._handle:
            self.do_export_btn.setEnabled(False)
            return
        for layer in self._handle.layers:
            self.export_layer_combo.addItem(layer.name)
        self.do_export_btn.setEnabled(bool(self._handle.layers))

    def _on_browse_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("ui.export.path"), "", "GeoTIFF (*.tif *.tiff)")
        if path:
            self.export_path.setText(path)

    def _on_export_clicked(self):
        from qgis.core import QgsApplication

        if not self._handle:
            QMessageBox.information(self, tr("ui.info"),
                                    tr("ui.export.no_product"))
            return
        layer_name = self.export_layer_combo.currentText()
        out_path = self.export_path.text().strip()
        if not layer_name or not out_path:
            QMessageBox.information(self, tr("ui.info"),
                                    tr("ui.export.no_product"))
            return
        if not out_path.lower().endswith((".tif", ".tiff")):
            out_path += ".tif"
            self.export_path.setText(out_path)

        self.do_export_btn.setEnabled(False)
        task = NisarExportTask(self._handle, layer_name, out_path,
                               config_as_dict(self.config),
                               cog=self.export_cog.isChecked())
        task.signals.finished_ok.connect(self._on_export_done)
        task.signals.finished_error.connect(self._on_export_error)
        self._tasks.append(task)
        QgsApplication.taskManager().addTask(task)

    def _on_export_done(self, result):
        self.do_export_btn.setEnabled(True)
        if not result.success or not result.output_paths:
            self._on_export_error(result.error_message or "export failed")
            return
        QMessageBox.information(
            self, tr("ui.info"),
            tr("ui.export.done").format(path=result.output_paths[0]))

    def _on_export_error(self, message):
        self.do_export_btn.setEnabled(True)
        self.add_layers_btn.setEnabled(True)
        QMessageBox.critical(
            self, tr("ui.error"),
            tr("ui.export.failed").format(error=message))

    # ============================================================== Settings
    def _on_browse_download_dir(self):
        path = QFileDialog.getExistingDirectory(self, tr("ui.settings.download_dir"))
        if path:
            self.set_download_dir.setText(path)

    def _on_save_settings(self):
        cfg = config_manager.load()
        cfg.reader_backend = ReaderBackend(
            self.set_reader.currentData() or "auto")
        cfg.access_backend = AccessBackend(
            self.set_access.currentData() or "auto")
        cfg.download_dir = Path(self.set_download_dir.text().strip()
                                or cfg.download_dir)
        cfg.language = self.set_language.currentData() or "en"
        cfg.show_beta_warnings = self.set_beta_warn.isChecked()
        config_manager.save(cfg)
        self.config = cfg
        set_language(cfg.language)
        self._retranslate()
        QMessageBox.information(self, tr("ui.info"), tr("ui.settings.saved"))

    # ================================================================ close
    def closeEvent(self, event):
        self._clear_footprint_band()
        if self._handle is not None:
            try:
                ReaderRegistry.close(self._handle)
            except Exception:  # pragma: no cover
                pass
            self._handle = None
        for task in list(self._tasks):
            try:
                task.cancel()
            except Exception:  # pragma: no cover
                pass
        self._tasks.clear()
        super().closeEvent(event)
