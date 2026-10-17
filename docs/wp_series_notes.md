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

## WP-3 - надёжное скачивание (DownloadManager)
- `nisar_core/access/download_manager.py` (ядро, без QGIS), схема проверенного на
  реальных GUNW `validation/windthrow_new_sites/nisar_dl.py`: N параллельных
  HTTP-Range-частей -> `<name>.part<i>` (докачка через append при обрыве/повторе),
  сшивка в `<name>.h5.partial` + fsync + проверка размера + атомарный
  `os.replace` в итоговое имя; обрезанный файл под итоговым именем никогда не
  считается готовым (перекачивается).
- Отмена: `threading.Event` проверяется на каждом блоке; при отмене итогового
  файла нет, part-файлы остаются для докачки; отсановка за блок-границу (<2 с в
  тесте). `DownloadCancelled`/`DownloadError`.
- Конфиг: `max_concurrent_downloads` (очередь, ThreadPool), `request_timeout`,
  `download_chunk_size`, `verify_ssl`, `proxies`, `download_parts`,
  `download_retries`; User-Agent с версией плагина (единый источник версии).
- EDL-токен: config `edl_token` ИЛИ env `EDL_TOKEN` (без путей в коде);
  `validation/.../nisar_dl.py` теперь читает `EDL_TOKEN` вместо жёсткого пути.
  Интеграция с QgsAuthManager - [ПРОВЕРИТЬ] на интеграционном прогоне (нужен
  существующий authcfg; оставлено на следующий шаг приёма).
- B2: `download()` делегирует DownloadManager (Range/докачка/размер), сигнатура
  приняла `cancel_event=`; GET 200 вместо 206 при непустом resume -> явная
  ошибка (Range не поддержан сервером). Прокси QGIS: `_apply_qgis_proxies`
  (QgsSettings proxy/* -> proxies) - [ПРОВЕРИТЬ] ключи настроек в QGIS.
- `get_local_path` строгий: точное имя гранулы, никогда `.part/.partial`,
  совпадение размера при известном ожидаемом; «новейший *.h5»-фолбэк удалён.
- GUI: ошибки пакета - один message-bar отчёт (строка таблицы получает
  `error: причина`, отмена - статус cancelled), в контекстном меню таблицы
  «Повторить скачивание» для упавших; оценка размера + проверка свободного
  места ДО старта (по метаданным, иначе HEAD; пропуск с явным предупреждением).
- Приёмка (tests/unit/test_download_manager.py, локальный HTTP-сервер с Range):
  обрыв -> докачка = sha256-идентичный файл; отмена < 2 с, файла нет, parts
  есть; обрезанный файл перекачивается; максимум 2 активных из 5 при
  max_concurrent=2; estimate/free-space; UA/EDL-заголовки; timeout/verify_ssl/
  proxies доходят до requests; строгий get_local_path. Suite: 205 passed,
  1 skipped; ruff F чисто.

## Post-release CI failures (17.10.2026)

First `ci` runs on the WP series (cdb9c30 / merge 2d8c686) failed:

1. `tests` (3.10-3.12): `test_download_manager.py` failed with
   `DownloadError('requests is not available ...')` - the CI install
   line had no `requests`. Fix: requests added to the install step.
2. `test_run_windthrow_did_e2e`: `dcoh.tif` never appeared because
   neither GDAL nor rasterio is present in CI, so `write_raster`
   failed softly into `warnings` while the run stayed `success=True`.
   Locally it passes because the dev py-3.11 has rasterio. Fix:
   rasterio added to the CI install (GeoTIFF write fallback this
   e2e relies on).
3. `version` job: `No module named pytest` - the job ran the version
   consistency test without installing anything. Fix: install step
   with pytest added.

## Integration run, QGIS 3.44.11 (17.10.2026, post v0.4.0)

Headless acceptance on the merged main (with synthetic GCOV/GUNW
products): all 5 nisar:* algorithms ran via qgis_process;
CRS/dtype/units verified with rasterio; GUI smoke + API probes done
inside the running QGIS python. Full record:
`tests/qgis/README.md`.

[ПРОВЕРИТЬ] closed on this run:
- `QgsVectorFileWriter.create()` with the Qt5/Qt6 chain - works
  (Qt 5.15.13 -> QMetaType.Int; Qt6/QGIS 4.x still untested).
- `QgsSettings proxy/*` key names - round-trip ok in the installed
  QGIS (they are the native QGIS options keys).
- `bbox_wgs84_from_georef` OSR branch - matches pyproj 3.7.1 oracle
  to 7 decimals.
- Two-frequency (frequencyB/UR clone) export - correct EPSG:32605
  after fixing a malformed WKT in the synthetic fixture (real
  granules never hit this - their WKT carries the authority inside
  the UNIT element).

[ПРОВЕРИТЬ] still open:
- IDR driver NISAR in OSGeo4W GDAL 3.13.0: `GetDriverByName("NISAR")`
  is None - A1 backend unavailable there; across-the-board A2 opens
  the products but cannot georeference them (as expected); auto
  falls back to A3 (h5py). Local QGIS must get h5py via the
  PYTHONPATH wheel trick (tests/qgis/README.md) to have a working
  reader at all.
- QgsAuthManager -> EDL wiring (authcfg card in the dialog) remains
  unimplemented by design (WP-3 token comes from config/env); token
  persistence in settings verified ABSENT.
- GUI runtime paths (download queue, retry menu, disk-space bar) are
  construct-only here; live acceptance still needs a real download
  session with EDL credentials.
## Live search/download/open acceptance (17.10.2026, real granule)

First full end-to-end run of the plugin's own access stack with a real
EDL token: B2 search (27 PROVISIONAL GCOV scenes, Kostroma AOI),
DownloadManager (4 range-parallel parts, ~3.5 MB/s, atomic stitch,
exact size match), A3 read of the REAL two-frequency product
(EPSG:32638, A=20 m / B=80 m grids), hv_db + rvi algorithms in QGIS
3.44.11 on the 2 GB real granule (Float32 GeoTIFF, correct CRS), the
ambiguous `HVHV` key honestly refused (F14) on real data, frequencyB
export verified against the 20 m statistics. Record in
`tests/qgis/README.md`. Dependency note: `asf_search` 14.1.0 installed
into the local dev Python for the run (optional plugin dependency,
degrades gracefully without it).

Acceptance item >= 5 GB / peak-RSS still open (this granule is 2 GB).
### Post-live micro-fix (17.10.2026)

`apply_fill_nodata()` in export.py: explicit NaN-fill handling (the
old `tile == fill` branch was a no-op for NaN `_FillValue`), 3 unit +
1 GDAL-guarded e2e test. No scientific values changed; outcome on real
granules identical. CI green on 93fa899 (PR #3).
