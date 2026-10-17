# Заметки серии WP (review NISAR_loader_review_and_TZ.md)

Статус фиксировался по результатам прогонов `py -3.11 -m pytest tests/unit`
(standalone Python 3.11, без GDAL) и `ruff check --select=F`.

## WP-12 — минимальный CI, версии, LICENSE (коммит 41c0910)
- Проверено запуском: `scripts_build_zip.py` собирает `nisar_qgis_plugin_v0.3.2.zip`;
  тест согласованности версии ловит расхождение `metadata.txt` <-> `__init__`.
- [ПРОВЕРИТЬ] на CI GitHub (первый запуск matrix 3.10/3.11/3.12 ещё не гонялся).

## WP-1 — корректная модель слоёв для двух частот
- `LayerInfo.frequency` ("A"/"B"), `layer_id` ("frequencyA/HHHH"; для GUNW —
  полный хвост после grids/), собственная `LayerInfo.georef`.
- `resolve_layer`: точный путь -> layer_id -> уникальное имя; неоднозначное
  имя = `AmbiguousLayerError`; частичное ("HH" вместо "HHHH") =
  `LayerNotFoundError`. `path.endswith(name)` не используется.
- Двухчастотная геореф: `_extract_georefs` (A3), per-subdataset georef (GDAL),
  `handle.metadata["georef_by_frequency"]`; `handle.georef` остаётся primary.
- Индексы: `pick_index_layers()` берёт все входы из ОДНОЙ частоты (A -> B ->
  no-tag), ошибка со списком доступных слоёв при смешении; проверка shape.
- Имена выходов: `<base>_<freq>_<name>.tif` (`output_name_with_frequency`).
- GUI: колонка «Частота» в таблице слоёв, комбобокс частоты на вкладке
  Processing (только для двухчастотных файлов), экспорт по `currentData`.
- Силами unit-тестов проверено: 152 passed, 1 skipped (GDAL отсутствует).
  Экспорт частоты B через GDAL (rasterio/GDAL writer) не гонялся здесь —
  интеграционный тест в QGIS (tests/qgis/README.md) — [ПРОВЕРИТЬ].
- Заодно укреплено: `_extract_identification` теперь не падает на
  многозначных полях identification (listOfFrequencies=[A,B] и т. п.) —
  упало при создании двухчастотной фикстуры, исправление в a3_h5py.

## WP-2 — поляризационно-независимые пресеты + ProductType
- `PresetRequirement.cross_pol_required` / `co_pol_required` (HVHV|VHVH /
  HHHH|VVVV); hv_db, cross_ratio, rvi, change_db переведены на классы.
- `check_availability` сравнивает значения поляризаций (строки .value) —
  переживает перезагрузку модулей под qgis-mocks; None-handle/слои —
  гр ацелфульные причины, не исключения.
- Все ридеры возвращают ProductType (a1/a2 `_guess_product_type`, +GUNW);
  `coerce_product_type` + `__post_init__` в ProductHandle/SceneRecord.
- Проверено запуском: 167 passed, 1 skipped; матрица наборов
  {HHHH,HVHV} / {VHVH,VVVV} / full-pol / {HHHH} / {HVHV} — в
  tests/unit/test_preset_polarization_classes.py.

## WP-5 - ветровал: корректность входов/выходов
- `nisar_core/geo.py` (новый, ядро без QGIS): `select_layer_crs` (собственный
  CRS выходного растра всегда победил; georef продукта - только fallback),
  `bbox_wgs84_from_georef` (EPSG:4326 passthrough -> OSR -> pyproj ->
  аналитический обратный UTM), `utm_forward`/`utm_inverse` (схема
  Снайдера, футпойнт-ряд), `utm_zone_from_authid` (EPSG:326xx/327xx).
- Эталоны UTM посчитаны один раз pyproj 3.7.1 (EPSG:32632 Мюнхен,
  32735 Йоханнесбург, 32618 Майами вне ЦМ, 32717 Лима): forward < 5 см,
  обратная < 5e-7 град; допуск ТЗ 0.05 град - tests/unit/test_geo.py.
- `_approx_bbox_wgs84` оставлен alias-ом на реальный transform; старый
  масштабный хак «x/111320» удалён (ошибался на градусы вдали от ЦМ зоны).
- forest_mask: ошибки тайлов не «глотаются»: `_forest_fraction_rasterio`
  возвращает (маска, failed_tiles, n_tiles); предупреждение с точным
  покрытием; откат на GDAL-путь - с ЯВНЫМ предупреждением; параметр
  `strict=False` (в Processing-алгоритме - новый STRICT_FOREST, default
  True: RuntimeError -> QgsProcessingException); при невычислимом WGS84
  bbox strict тоже ругается, permissive возвращает None+warning.
- windthrow: ref-полигоны вне сетки -> прогон завершается без исключения:
  предупреждение «reference.overlap = 0», background = вся валидная сцена,
  metrics = {}; отчёт["reference"]["overlap"]; `format_metric` (None ->
  «n/a») в GUI и алгоритме.
- `_rasterize_reference`: геометрии перпроектируются из CRS источника в CRS
  растра ДО записи GPKG (gdal.Rasterize не перепроектирует); deprecated ctor
  заменён на QgsVectorFileWriter.create() + SaveVectorOptions;
  QVariant.Int -> QMetaType.Type.Int с fallback (Qt5/Qt6). [ПРОВЕРИТЬ]
  точную сигнатуру create() на QGIS 3.28/3.44 в интеграционном прогоне
  (tests/qgis/README.md), включая headless qgis_process.
- `_add_raster_layer` GUI: CRS - через чистую select_layer_crs,
  dcoh.tif сохраняет собственный CRS даже при открытом другом продукте
  (юнит-тест, acceptance ТЗ).
- Состояние: 187 passed, 1 skipped; ruff F чисто. В юнит-окружении GDAL
  и pyproj отсутствуют - аналитический UTM-обратник проверен против
  pyproj-якорей NUMBER-ов в тестах; OSR/pyproj ветки работают в QGIS.

## WP-4 - поиск ASF без тихих отказов
- `SearchError(RuntimeError)` в `nisar_core/access/base.py`; `search()` B2:
  полный провал (нет результатов и все типы упали) -> SearchError с
  собранным текстом; PARTIAL по типам продукта - в `backend.search_warnings`
  (GUI показывает в message bar); парс-упавшая запись тоже предупреждение.
- Полный провал-asf_search недоступен - тоже SearchError (бывш. RuntimeError).
- Лимит: `params.max_results` (GUI теперь берёт `search_max_results` из
  конфига, иначе 100); при получении РОВНО лимита по типу - предупреждение
  «truncated at the configured limit» (ASF может обрезать на границе).
- Окно времени: `asf_time_bounds()` - все времена tz-aware UTC;
  конечная дата включительно (23:59:59 UTC последнего дня).
- `acquisition_time`: нет в метаданных -> None + предупреждение;
  `datetime.now()` больше НЕ подставляется.
- Футпринт MultiPolygon разбирается целиком (WKT MULTIPOLYGON обеих
  частей); `preview.bbox_from_wkt` понимает MULTIPOLYGON (union bbox
  повсеместным частям).
- GUI: NisarSearchTask эмитит (scenes, warnings); `_on_search_done`
  распаковывает и показывает предупреждения в message bar; ошибки поиска
  теперь в message bar (`_push_message_bar`, Qgis.Warning/Critical).
- Приёмка: 9 тестов на моках asf_search (tests/unit/test_asf_search_wp4.py):
  исключение -> SearchError; ровно лимит -> ходе; сцена в последний день
  найдена (end=23:59:59Z); MultiPolygon парсится. Suite: 196 passed,
  1 skipped; ruff F чисто.
