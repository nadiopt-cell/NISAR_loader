# -*- coding: utf-8 -*-
"""
NISAR Vegetation QGIS Plugin — package entry point.

``classFactory`` is called by QGIS when the plugin is loaded.
The heavy imports are done *inside* ``classFactory`` on purpose:
``nisar_qgis.nisar_core`` stays importable without QGIS (pytest, CLI),
because importing this package must not pull in Qt/QGIS.
"""


def classFactory(iface):  # noqa: N802 - required QGIS entry point name
    """Return the plugin instance for the given QGIS iface.

    :param iface: QgisInterface instance provided by QGIS
    """
    from .plugin import NisarPlugin
    return NisarPlugin(iface)


__version__ = "0.3.2"
