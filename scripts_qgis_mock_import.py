# -*- coding: utf-8 -*-
"""
Smoke-import all QGIS-facing plugin modules with a mocked `qgis` package.

Catches import-time errors (bad names, wrong imports, syntax) without a
running QGIS. Runtime behaviour still needs the manual QGIS acceptance
run (tests/qgis/README.md).
"""
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent


def _mkmodule(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


# ---------------------------------------------------------------- qgis.PyQt
class _FakeMeta(type):
    """Any class attribute resolves to the _Fake class itself."""
    def __getattr__(cls, item):
        return _Fake


class _Fake(metaclass=_FakeMeta):
    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return _Fake()

    def __getattr__(self, item):
        return _Fake()


def _fake_module(name, names):
    mod = types.ModuleType(name)

    def __getattr__(attr):
        if attr in names:
            return _Fake  # the class — usable as base class and callable
        raise AttributeError("%s has no attribute %r" % (name, attr))
    mod.__getattr__ = __getattr__  # type: ignore[method-assign]
    sys.modules[name] = mod
    return mod


_qtwidget_names = """
QDialog QVBoxLayout QHBoxLayout QTabWidget QWidget QLabel QLineEdit
QPushButton QComboBox QTableWidget QTableWidgetItem QHeaderView
QFileDialog QCheckBox QFormLayout QMessageBox QGroupBox QApplication
QTextBrowser QAction
""".split()
_qtcore_names = "Qt pyqtSignal QObject QSize QCoreApplication QUrl".split()
_qtgui_names = "QIcon QColor QFont QPixmap QDesktopServices".split()

_fake_module("qgis", [])
_fake_module("qgis.PyQt", [])
_fake_module("qgis.PyQt.QtWidgets", _qtwidget_names)
_fake_module("qgis.PyQt.QtCore", _qtcore_names)
_fake_module("qgis.PyQt.QtGui", _qtgui_names)

# ----------------------------------------------------------------- qgis.core
_qgis_core_names = """
QgsApplication QgsMessageLog QgsTask QgsProject QgsRasterLayer
QgsCoordinateReferenceSystem QgsCoordinateTransform QgsGeometry
QgsRectangle QgsWkbTypes QgsProcessingProvider QgsProcessingAlgorithm
QgsProcessingParameterFile QgsProcessingParameterString
QgsProcessingParameterBoolean QgsProcessingParameterRasterDestination
QgsProcessingException QgsRasterMinMaxOrigin QgsLayerMetadata QgsSettings
""".split()
_fake_module("qgis.core", _qgis_core_names)
_fake_module("qgis.gui", ["QgsMessageBar", "QgisInterface", "QgsRubberBand"])

sys.path.insert(0, str(REPO))

failures = []
modules = [
    "nisar_qgis.config_manager",
    "nisar_qgis.gui.tasks",
    "nisar_qgis.gui.main_dialog",
    "nisar_qgis.algorithms",
    "nisar_qgis.algorithms.indices_algorithms",
    "nisar_qgis.provider",
    "nisar_qgis.plugin",
]

for mod_name in modules:
    try:
        __import__(mod_name)
        print("OK   ", mod_name)
    except Exception as exc:
        failures.append((mod_name, exc))
        print("FAIL ", mod_name, "->", type(exc).__name__, exc)

# classFactory smoke test (mock iface)
try:
    import nisar_qgis
    plugin = nisar_qgis.classFactory(_Fake())
    print("OK    classFactory ->", type(plugin).__name__)
except Exception as exc:
    failures.append(("classFactory", exc))
    print("FAIL  classFactory ->", type(exc).__name__, exc)

if failures:
    sys.exit(1)
print("\nAll QGIS-facing modules import cleanly with mocks.")
