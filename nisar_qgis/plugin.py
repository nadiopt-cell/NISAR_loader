# -*- coding: utf-8 -*-
"""
NISAR Vegetation QGIS Plugin — main entry point (menu, toolbar, dialog).
"""
import os

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication, QgsMessageLog

from .provider import NisarProvider


def _plugin_icon() -> QIcon:
    """Icon stored next to the plugin sources (no compiled Qt resources)."""
    icon_path = os.path.join(os.path.dirname(__file__), "resources", "icon.png")
    if os.path.exists(icon_path):
        return QIcon(icon_path)
    return QIcon()


class NisarPlugin:
    """Main plugin class: registers provider, toolbar and menu."""

    MENU_TITLE = "&NISAR Vegetation"
    TOOLBAR_NAME = "NISAR Vegetation"

    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.dialog = None
        self.toolbar = None
        self.actions = []

    def initGui(self):
        """Initialize GUI: toolbar, menu, processing provider."""
        try:
            self.provider = NisarProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)
        except Exception as exc:  # pragma: no cover - defensive
            QgsMessageLog.logMessage(
                "Failed to register Processing provider: %s" % exc,
                "NISAR", level=QgsMessageLog.WARNING)

        self.toolbar = self.iface.addToolBar(self.TOOLBAR_NAME)
        self.toolbar.setObjectName("NisarVegetationToolbar")

        self.main_action = QAction(_plugin_icon(), "NISAR Vegetation",
                                   self.iface.mainWindow())
        self.main_action.triggered.connect(self.show_dialog)
        self.toolbar.addAction(self.main_action)
        self.iface.addPluginToMenu(self.MENU_TITLE, self.main_action)
        self.actions.append(self.main_action)

        QgsMessageLog.logMessage(
            "NISAR Vegetation plugin loaded (v%s)" % _version(),
            "NISAR", level=QgsMessageLog.INFO)

    def unload(self):
        """Unload plugin: remove provider, toolbar, menu."""
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

        if self.toolbar:
            self.iface.removeToolBar(self.toolbar)
            self.toolbar = None

        for action in self.actions:
            self.iface.removePluginMenu(self.MENU_TITLE, action)
        self.actions.clear()

        if self.dialog:
            self.dialog.close()
            self.dialog = None

        QgsMessageLog.logMessage(
            "NISAR Vegetation plugin unloaded", "NISAR", level=QgsMessageLog.INFO)

    def show_dialog(self):
        """Show (or create) the main plugin dialog."""
        if not self.dialog:
            from .gui.main_dialog import NisarMainDialog
            self.dialog = NisarMainDialog(self.iface)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()


def _version():
    try:
        from . import __version__
        return __version__
    except Exception:  # pragma: no cover
        return "?"
