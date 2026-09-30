# -*- coding: utf-8 -*-
"""
QGIS API contract tests (mocked, no QGIS installation required).

Regression tests for the two entry points QGIS calls outside initGui():

1. ``createInstance()`` — QgsProcessingAlgorithm requires it to be
   overridden; without it, running any algorithm from Processing
   (toolbox or qgis_process) raises
   ``NotImplementedError: QgsProcessingAlgorithm.createInstance() is
   abstract and must be overridden`` (caught live in QGIS 3.44.14 via
   qgis_process, 2026-09-30).

2. ``initProcessing()`` — qgis_process starts plugins through
   ``qgis.utils.startProcessingPlugin()``, which calls
   ``plugin.initProcessing()`` instead of ``initGui()``. A plugin
   without it cannot be used headless.

The mocks are installed in a fixture and fully removed afterwards
(test_config asserts that ``qgis`` stays out of ``sys.modules``).
"""
import sys
import types

import pytest

REPO_ROOT = __file__.replace("/tests/unit/test_qgis_plugin_api.py", "")


# ------------------------------------------------------------------ mocks
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
        if attr in names or not names:
            return _Fake
        raise AttributeError("%s has no attribute %r" % (name, attr))

    mod.__getattr__ = __getattr__  # type: ignore[method-assign]
    sys.modules[name] = mod
    return mod


_QT_WIDGETS = """
QDialog QVBoxLayout QHBoxLayout QTabWidget QWidget QLabel QLineEdit
QPushButton QComboBox QTableWidget QTableWidgetItem QHeaderView
QFileDialog QCheckBox QFormLayout QMessageBox QGroupBox QApplication
QTextBrowser QAction
""".split()
_QT_CORE = "Qt pyqtSignal QObject QSize QCoreApplication QUrl".split()
_QT_GUI = "QIcon QColor QFont QPixmap QDesktopServices".split()
_QGIS_CORE = """
QgsApplication QgsMessageLog QgsTask QgsProject QgsRasterLayer
QgsCoordinateReferenceSystem QgsCoordinateTransform QgsGeometry
QgsRectangle QgsWkbTypes QgsProcessingProvider QgsProcessingAlgorithm
QgsProcessingParameterFile QgsProcessingParameterString
QgsProcessingParameterBoolean QgsProcessingParameterRasterDestination
QgsProcessingParameterVectorLayer QgsProcessingParameterFeatureSource
QgsProcessingParameterNumber QgsProcessingParameterFolderDestination
QgsProcessingParameterEnum QgsProcessingException QgsRasterMinMaxOrigin
QgsLayerMetadata QgsSettings QgsVectorLayer QgsVectorFileWriter
QgsProcessingUtils QgsFields QgsField QgsFeature
""".split()


@pytest.fixture
def qgis_mocks():
    """Install mocked qgis modules; remove them afterwards."""
    saved = {k: v for k, v in sys.modules.items()
             if k == "qgis" or k.startswith("qgis.")}
    for key in list(saved):
        del sys.modules[key]

    _fake_module("qgis", [])
    _fake_module("qgis.PyQt", [])
    _fake_module("qgis.PyQt.QtWidgets", _QT_WIDGETS)
    _fake_module("qgis.PyQt.QtCore", _QT_CORE)
    _fake_module("qgis.PyQt.QtGui", _QT_GUI)
    _fake_module("qgis.core", _QGIS_CORE)
    _fake_module("qgis.gui", ["QgsMessageBar", "QgisInterface",
                              "QgsRubberBand"])
    yield
    # teardown: drop qgis mocks AND nisar_qgis modules imported under them
    for key in list(sys.modules):
        if key == "qgis" or key.startswith("qgis.") \
                or key.startswith("nisar_qgis"):
            del sys.modules[key]
    sys.modules.update(saved)


ALGORITHM_CLASSES = [
    "NisarHvDbAlgorithm",
    "NisarCrossRatioAlgorithm",
    "NisarRviAlgorithm",
    "NisarExportAlgorithm",
    "NisarWindthrowDidAlgorithm",
]


def test_algorithms_override_create_instance(qgis_mocks):
    """Every Processing algorithm must provide a working createInstance().

    QGIS instantiates algorithms for execution via createInstance(); the
    base-class method is abstract and raises NotImplementedError.
    """
    import importlib
    alg_mod = importlib.import_module("nisar_qgis.algorithms")
    for class_name in ALGORITHM_CLASSES:
        cls = getattr(alg_mod, class_name)
        assert "createInstance" in dir(cls), (
            "%s does not expose createInstance()" % class_name)
        # the override must live in our code, not in the (fake) Qt base
        fn = cls.createInstance
        assert getattr(fn, "__module__", "").startswith("nisar_qgis"), (
            "%s.createInstance is not defined by the plugin" % class_name)
        instance = cls()
        clone = instance.createInstance()
        assert clone is not instance, (
            "%s.createInstance must return a fresh instance" % class_name)
        assert type(clone) is cls, (
            "%s.createInstance returned %r" % (class_name, type(clone)))


def test_plugin_provides_init_processing(qgis_mocks):
    """qgis_process (headless) requires plugin.initProcessing().

    qgis.utils.startProcessingPlugin() calls initProcessing() instead of
    initGui() when the plugin is started from qgis_process; without the
    method the plugin errors out and its algorithms never register.
    """
    import importlib
    nisar_pkg = importlib.import_module("nisar_qgis")
    plugin = nisar_pkg.classFactory(_Fake())
    assert hasattr(plugin, "initProcessing"), (
        "plugin must implement initProcessing() for headless QGIS use")
    plugin.initProcessing()
    assert plugin.provider is not None, (
        "initProcessing() must register the Processing provider")


# Verified against the real QGIS 3.44 QgsProcessingAlgorithm API
# (dumped from a live QGIS 3.44.14, 2026-09-30).
_VALID_PARAMETER_AS = frozenset("""
parameterAsAnnotationLayer
parameterAsBool
parameterAsBoolean
parameterAsColor
parameterAsCompatibleSourceLayerPath
parameterAsCompatibleSourceLayerPathAndLayerName
parameterAsConnectionName
parameterAsCrs
parameterAsDatabaseTableName
parameterAsDateTime
parameterAsDouble
parameterAsEnum
parameterAsEnumString
parameterAsEnumStrings
parameterAsEnums
parameterAsExpression
parameterAsExtent
parameterAsExtentCrs
parameterAsExtentGeometry
parameterAsFields
parameterAsFile
parameterAsFileList
parameterAsFileOutput
parameterAsGeometry
parameterAsGeometryCrs
parameterAsInt
parameterAsInts
parameterAsLayer
parameterAsLayerList
parameterAsLayout
parameterAsLayoutItem
parameterAsMatrix
parameterAsMeshLayer
parameterAsOutputLayer
parameterAsPoint
parameterAsPointCloudLayer
parameterAsPointCrs
parameterAsRange
parameterAsRasterLayer
parameterAsSchema
parameterAsSink
parameterAsSource
parameterAsString
parameterAsStrings
parameterAsVectorLayer
""".split())


def test_only_real_parameteras_api_is_used():
    """Static scan: every self.parameterAs*() call must exist in QGIS.

    Guards against hallucinated API names (e.g. parameterAsNumber was
    called in windthrow_algorithms.py and only exploded at runtime in a
    real QGIS — unit tests with mocks cannot catch this).
    """
    import re
    from pathlib import Path
    pkg_root = Path(__file__).resolve().parents[2] / "nisar_qgis"
    bad = []
    for py in sorted(pkg_root.rglob("*.py")):
        text = py.read_text(encoding="utf-8")
        for match in re.finditer(r"\.parameterAs([A-Z]\w*)\(", text):
            name = "parameterAs" + match.group(1)
            if name not in _VALID_PARAMETER_AS:
                bad.append("%s: %s" % (py.name, name))
    assert not bad, (
        "calls to non-existent QGIS API methods: %r" % bad)


def test_no_removed_qgs_messagelog_constants():
    """Static scan: QgsMessageLog.INFO/WARNING/CRITICAL are gone in
    newer QGIS (verified removed in 3.44.14; levels must come from
    qt_compat.LEVEL_* which resolves Qgis.MessageLevel with int
    fallback for older releases)."""
    import re
    from pathlib import Path
    pkg_root = Path(__file__).resolve().parents[2] / "nisar_qgis"
    bad = []
    for py in sorted(pkg_root.rglob("*.py")):
        text = py.read_text(encoding="utf-8")
        for match in re.finditer(
                r"QgsMessageLog\.(INFO|WARNING|CRITICAL)\b", text):
            bad.append("%s: QgsMessageLog.%s" % (py.name, match.group(1)))
    assert not bad, (
        "removed QgsMessageLog level constants still referenced: %r" % bad)


def test_no_qtabwidget_tabdata_calls():
    """Static scan: QTabWidget has no tabData()/setTabData() (those are
    QTabBar methods, and no data was ever set) — caught live in QGIS
    3.44.14 when _retranslate() ran."""
    from pathlib import Path
    pkg_root = Path(__file__).resolve().parents[2] / "nisar_qgis"
    bad = []
    for py in sorted(pkg_root.rglob("*.py")):
        text = py.read_text(encoding="utf-8")
        if ".tabs.tabData(" in text or ".tabs.setTabData(" in text:
            bad.append(py.name)
    assert not bad, "QTabWidget.tabData()/setTabData() referenced: %r" % bad
