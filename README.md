# NISAR Vegetation — QGIS plugin

Поиск, открытие и обработка продуктов NASA NISAR L-диапазона (GCOV) в QGIS:
мониторинг растительности (HV в дБ, cross-ratio, RVI), экспорт в
GeoTIFF/COG.

**Статус:** experimental MVP (v0.2.0). Совместимость: QGIS 3.28 LTR+ и
QGIS 4.x (только `qgis.PyQt`).

## Возможности

| Модуль | Что делает |
|---|---|
| **Search** | Поиск сцен GCOV в ASF DAAC (extent карты, даты) — в фоне, с отменой |
| **Download** | Очередь скачивания с прогрессом (Earthdata Login через `~/.netrc`) |
| **Open** | Инспектор слоёв локального `.h5`, загрузка выбранных слоёв в проект с правильным CRS (группа «NISAR / …») |
| **Processing** | Пресеты: HV (cross-pol) в дБ, cross-ratio HV/HH, RVI (dual/full-pol — формула выбирается автоматически) — тайлово, Float32 |
| **Export** | Экспорт слоёв в GeoTIFF / COG (Float32, значения не искажаются) |
| **Processing Toolbox** | `nisar:hv_db`, `nisar:cross_ratio`, `nisar:rvi`, `nisar:export` |

Плагин предупреждает о BETA-продуктах (не полностью откалиброваны) и не
смешивает их silently с PROVISIONAL.

## Установка

1. QGIS → **Plugins → Manage and Install Plugins → Install from ZIP** →
   выбрать `nisar_qgis_plugin_v0.2.0.zip`.
2. Появится тулбар «NISAR Vegetation» и пункт меню. Processing-алгоритмы —
   в Toolbox под группой «NISAR Vegetation».

### Необязательные Python-пакеты

Плагин работает без них (с честными сообщениями о том, чего не хватает):

```bash
python -m pip install h5py          # резервный читатель HDF5 (A3)
python -m pip install asf_search    # онлайн-поиск и скачивание ASF (B2)
```

### Earthdata Login (для скачивания)

Создайте `~/.netrc` (права 600):

```
machine urs.earthdata.nasa.gov
  login ВАШ_EDL_ЛОГИН
  password ВАШ_EDL_ПАРОЛЬ
```

Плагин **никогда** не хранит пароли в настройках/проекте.

## Быстрый старт (MVP-сценарий)

1. Открыть диалог плагина → вкладка **Search** → «Взять экстент карты» →
   даты → **Search**.
2. Отметить сцену → вкладка **Download** → **Скачать** (нужен `~/.netrc`).
3. Вкладка **Open** → выбрать скачанный `.h5` → в таблице слоёв отметить
   HHHH/HVHV → **Добавить в проект**.
4. Вкладка **Processing** → выбрать пресет (справа — «Что это?»: формула,
   как читать, ограничения) → **Вычислить**.
5. Вкладка **Export** (или `nisar:export` в Toolbox) → GeoTIFF/COG.

## Разработка

```bash
# юнит-тесты ядра — без QGIS и без GDAL
python -m pytest tests/unit -v

# статическая проверка относительных импортов
python scripts_import_check.py
```

Структура:

```
nisar_qgis/            # сам плагин (этот каталог попадает в установочный ZIP)
  nisar_core/          # ядро без QGIS: readers (A1/A2/A3), access (B1/B2/B3),
                       # processing (индексы, экспорт), models, presets, config
  gui/                 # диалог + фоновые QgsTask
  algorithms/          # Processing-алгоритмы
  i18n/                # en (по умолчанию) / ru
  resources/           # icon.png
tests/unit/            # pytest: синтетический GCOV в tmp_path (без бинарников в git)
tests/qgis/            # инструкции по интеграционной проверке в QGIS
docs/product_notes.md  # проверенные факты о структуре GCOV (источники + статус)
AGENTS.md              # исходное задание
```

### Что проверено, а что нет

Подробности — в `docs/product_notes.md` (кратко):

* ✅ пути слоёв/единицы/CRS — по официальному спецификатору
  JPL D-102274 Rev E и nisar-docs.asf.alaska.edu;
* ✅ поиск ASF — на живом SearchAPI (2026-09-29);
* ⚠️ чтение на реальном `.h5` и `NETCDF:`-обход — требуют проверки на
  машине с QGIS (тест-сценарий в `tests/qgis/README.md`).

## Ограничения MVP

* Временные ряды, детектор изменений, спекл-фильтр, поляриметрия —
  зарегистрированы как пресеты, но помечены «позже» (P3, см. AGENTS.md).
* Для локально открытых файлов статус BETA/PROVISIONAL неизвестен —
  в файле нет явного флага (см. product_notes.md).
* QML-стили не поставляются; применяется программная растяжка 2–98%.

## Замечания для мейнтейнера

* В `nisar_qgis/metadata.txt` замените author/email/repository на
  реальные перед публикацией.
* Дополнительная зависимость GDAL используется только для записи
  GeoTIFF внутри QGIS (всегда доступна в QGIS).
