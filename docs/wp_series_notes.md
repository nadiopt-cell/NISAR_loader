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
