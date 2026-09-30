# Release notes — v0.3.1 (2026-09-30)

## Контекст

Первый прогон плагина в **реальном QGIS** (3.44.14-Solothurn, conda-forge,
offscreen: `qgis_process` + PyQGIS `QgsApplication`) на реальных гранулах
(GCOV + пара GUNW) выявил шесть дефектов, которые не ловились юнит-тестами
с моками: пять из них — несуществующие/удалённые вызовы QGIS Qt API,
добавленные по памяти. Все шесть исправлены и закрыты регрессионными
тестами; живой прогон полностью зелёный и воспроизводит цифры P3.1.

## Исправления

1. **`createInstance()` отсутствовал у всех 5 Processing-алгоритмов** —
   запуск любого алгоритма из Toolbox или `qgis_process` падал с
   `NotImplementedError: QgsProcessingAlgorithm.createInstance() is
   abstract and must be overridden` (qgis_process при этом молча
   завершался). Fix: метод в `NisarAlgorithmBase` (покрывает hv_db /
   cross_ratio / rvi / export) и в `NisarWindthrowDidAlgorithm`.
2. **`initProcessing()` отсутствовал у плагина** — headless-старт через
   `qgis.utils.startProcessingPlugin()` (путь `qgis_process`) требует
   этот метод вместо `initGui()`; без него «error starting plugin» и
   алгоритмы не регистрируются. Fix: `initProcessing()` +
   рефакторинг `_register_provider()` (идемпотентная регистрация
   провайдера).
3. **`parameterAsNumber()` — несуществующий API** — `windthrow_did`
   падал при чтении `MIN_PIXELS`. Fix: `parameterAsInt()`.
4. **`PREDICTOR=3` для целочисленных растров** — GDAL отказывался
   создавать `windthrow_mask.tif` (Byte): «PREDICTOR=3 is only supported
   with Float16, Float32 or Float64». Rasterio-fallback учитывал это и
   раньше, GDAL-путь — нет. Fix: `ExportBackend._effective_predictor()`
   (int-растры получают PREDICTOR=2).
5. **`QTabWidget.tabData()` — несуществующий API** — `_retranslate()`
   падал при конструировании диалога (у QTabWidget нет tabData/
   setTabData — это методы QTabBar, и данные никогда не
   устанавливались). Fix: ключи вкладок хранятся в `_tab_keys`.
6. **`QgsMessageLog.INFO/WARNING` — удалённые константы** — в QGIS
   ≥3.36 уровни живут в `Qgis.MessageLevel`; старые константы
   отсутствуют в 3.44 (инициализация/выгрузка плагина падали бы в
   свежем QGIS). Fix: новый модуль `qt_compat.py`
   (`LEVEL_INFO/LEVEL_WARNING` c int-fallback для 3.28 LTR).

## Новые тесты (127 → 135 passed + 1 GDAL skip)

- `tests/unit/test_qgis_plugin_api.py` — контракт QGIS API:
  `createInstance` у всех алгоритмов (переопределён нашим кодом,
  возвращает свежий экземпляр того же класса), `initProcessing`
  у плагина (регистрирует провайдера), статические проверки:
  только реальные `parameterAs*` (список снят с живого QGIS 3.44),
  нет удалённых констант `QgsMessageLog`, нет `tabData` у QTabWidget.
  Моки ставятся фикстурой и полностью вычищаются из `sys.modules`.
- `tests/unit/test_export_predictor.py` — PREDICTOR по dtype
  (float → 3, int → 2) + GDAL roundtrip Byte-маски (skip без osgeo).

## Живая валидация (2026-09-30, QGIS 3.44.14 offscreen)

Установка в профиль (`QGIS_CUSTOM_CONFIG_PATH`), `qgis_process plugins
enable nisar_qgis`, `qgis_process list` → все 5 алгоритмов
(`nisar:hv_db`, `nisar:cross_ratio`, `nisar:rvi`, `nisar:export`,
`nisar:windthrow_did`).

- **GCOV** `NISAR_L2_UR_GCOV_031_151_A_011_0005_NADV_A_20260928T155022…`
  (реальный гранул): hv_db / cross_ratio / rvi → GeoTIFF 4248×4167,
  80 м (hv_db: −50.3…−17.8 дБ).
- **GUNW-пара** (шторм `…_023_093_D_058_024…20260620→20260702`,
  контроль `…_024_093_D_058_025…20260702→20260714`), EVENT_DATE
  2026-07-01, absolute-режим:
  - без маски: 783 544 px / 501 468 га / 3 993 объекта, порог
    0.2798 — **побитово совпадает с ре-прогоном P3.1**;
  - с маской леса Hansen GFC-2024-v1.12 (/vsicurl/, онлайн):
    650 317 px / 416 203 га / 3 973 объекта, порог 0.2829;
  - производительность: ядро DiD 13 с, пик RSS 601 МБ; полный прогон
    с маской ≈ 2–3 мин.
- **GUI smoke** (QApplication offscreen): конструирование диалога,
  все 7 вкладок, выгрузка плагина — без ошибок.

## Совместимость

`qgisMinimumVersion=3.28` сохранён: `qt_compat` использует
`Qgis.MessageLevel` на новых QGIS и int-значения на старых.
