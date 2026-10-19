# NISAR GCOV — product notes (разведка данных)

**Назначение:** единый источник проверенных фактов о структуре продуктов NISAR
для плагина. Всё, что отмечено ⚠️, ещё не подтверждено на реальном `.h5` файле.

**Дата проверки:** 2026-09-30 (обновлено после валидации на реальном грануле).

## Источники

1. **JPL D-102274 Rev E (2024-11-08), «NASA SDS Product Specification —
   Level-2 Geocoded Polarimetric Covariance (GCOV)», v1.2.1** — официальный
   спецификатор продукта (86 стр.):
   https://nisar.asf.earthdatacloud.nasa.gov/NISAR-SAMPLE-DATA/DOCS/NISAR_D-102274_RevE_NASA_SDS_Product_Specification_L2_GCOV_Nov8_2024_w-sigs.pdf
2. **NISAR Data User Guide** (ASF): https://nisar-docs.asf.alaska.edu/
   (страницы `/gcov`, `/data-format`, `/projections`,
   `/availability-overview`, `/naming-conventions`)
3. **Живой поиск ASF SearchAPI** (анонимно, через `asf_search` 14.0.3):
   реальные метаданные сцен GCOV PROVISIONAL и UR за сентябрь 2026.
4. **Реальный гранул, скачанный с ASF 2026-09-30** (EDL bearer-токен):
   `NISAR_L2_UR_GCOV_031_151_A_011_0005_NADV_A_20260928T155022_20260928T155037_
   P05023_F_P_J_001.h5` — 251 658 240 байт (251.7 МБ),
   sha256 `7bd1093efa07a761d0f47d692cb53e86a4aed7a708711c0708ecab5b32b47854`.
   Все пункты ниже без ⚠️ проверены на этом файле.

## Структура HDF5 (GCOV)

По спецификатору §5.3 и User Guide (/gcov). **Формат: HDF5, внутренняя
структура CF-совместима с netCDF; в корне `/` ничего не хранится.**

```
/science/LSAR/identification/          — идентификация продукта (§5.2)
    granuleId, productType, productVersion, productSpecificationVersion,
    absoluteOrbitNumber, trackNumber, frameNumber, lookDirection,
    orbitPassDirection, zeroDopplerStartTime, zeroDopplerEndTime,
    processingDateTime, processingType, compositeReleaseId,
    isUrgentObservation, isGeocoded, isFullFrame, isMixedMode,
    listOfFrequencies, radarBand, platformName, instrumentName,
    boundingPolygon (WKT, EPSG:4326), productDoi, missionId, ...
/science/LSAR/GCOV/grids/frequencyA/   — основная сетка (band A)
    HHHH, HVHV, VHVH, VVVV            — реальные диагональные члены
                                          (Float32, RTC gamma-0, units=1)
    HHHV, HHVH, HHVV, HVVH, HVVV, VHVV — комплексные внедиагональные
                                          (только quad-pol)
    RHRH, RVRV, RHRV                  — compact-pol (RH)
    mask                              — UByte: 0 = невалидно,
                                         255 = вне охвата, иначе № подсвига
    numberOfLooks                     — Float32, _FillValue=nan
    rtcGammaToSigmaFactor             — Float32 (gamma0 -> sigma0)
    xCoordinates                      — Float64 (frequencyAWidth), метры
    yCoordinates                      — Float64 (frequencyALength), метры
    xCoordinateSpacing, yCoordinateSpacing — Float64 скаляры, метры
    projection                        — UInt32 скаляр + атрибуты:
                                          epsg_code, spatial_ref (WKT),
                                          utm_zone_number, grid_mapping_name, ...
    listOfPolarizations, listOfCovarianceTerms — списки строк
/science/LSAR/GCOV/grids/frequencyB/   — вторая частота (если есть; 80 м)
/science/LSAR/GCOV/metadata/...        — служебные метаданные
```

**Форма всех растровых датасетов:** `(frequencyALength, frequencyAWidth)` —
**(высота, ширина)**, строки = Y (сверху вниз), столбцы = X.
✅ Подтверждено на реальном грануле: `(4167, 4248)` для frequencyB.

✅ **На реальном грануле identification — скалярные ДАТАСЕТЫ** (не атрибуты
группы): `f["/science/LSAR/identification/granuleId"][()]`. Ридер A3 читает
именно так.

✅ **Реальный гранул содержал ТОЛЬКО frequencyB с V-дуал-поляризациями
VHVH + VVVV** (`listOfPolarizations = [VH, VV]`, режим DV). Индексы
растительности считаются по любой ориентации: cross-pol = HVHV **или** VHVH,
co-pol = HHHH **или** VVVV. Слои: VHVH, VVVV, mask, numberOfLooks,
rtcGammaToSigmaFactor, inputDataExceptionMask; каждый ковариационный слой
несёт атрибуты статистики `min_value`/`mean_value`/`max_value`/
`sample_stddev` (пригодно для самопроверки чтения).

⚠️ Расхождение в документации: страница User Guide `/data-format` в примере
пишет `.../frequencyA/HH`, а страница `/gcov` и спецификатор §5.3 —
`HHHH/HVHV/...`. Принято по спецификатору (4-символьные члены ковариации);
подтверждается косвенно именами browse-файлов реальных сцен
(`..._NATIVE_A_HHHH.png`, `..._NATIVE_A_HVHV.png`).

## Единицы значений

* Диагональные члены (HHHH, HVHV, VHVH, VVVV, RHRH, RVRV) —
  **линейная мощность gamma-0, радиометрически скорректированная по рельефу
  (RTC)**; атрибут `units = 1`, `valid_min = 0`, `_FillValue = nan`.
  Использовать как NRB/RTC-продукт.
* dB-продукты плагина считаются как `10*log10(x)` от линейных значений.
* Внедиагональные члены — комплексные; для quad-pol.

**Важно для формул:** RVI и cross-ratio применять ТОЛЬКО к линейным
значениям (не к дБ).

## Геопривязка (CRS)

По User Guide `/projections` (L2-продукты):

| Зона | Проекция |
|---|---|
| 60°N … 60°S | UTM (WGS84): EPSG 32601–32660 (север), 32701–32760 (юг) |
| севернее 60°N | NSIDC Polar Stereographic North, EPSG 3413 |
| южнее 60°S | Antarctic Polar Stereographic, EPSG 3031 |

CRS читается плагином из датасета `projection`: атрибуты `epsg_code`
и `spatial_ref` (WKT). Координатные оси — `xCoordinates`/`yCoordinates`
(CF-конвенция: центры пикселей, атрибут `pixel_coordinate_convention =
"center"`) + spacing. Плагин строит GDAL-геотрансформ
по краям пикселей: `gt = [x0-dx/2, dx, 0, y0+dy/2, 0, -dy]` (для
убывающих Y, типовой случай).

✅ **Проверено на реальном грануле:** `projection` = скаляр UInt32 (значение
32605 = EPSG-код), атрибуты содержат полный WKT + `epsg_code` + параметры
проекции. **`yCoordinateSpacing` ОТРИЦАТЕЛЬНЫЙ** (−80 м для north-up
решётки с убывающими Y) — ридер берёт модуль и определяет ориентацию по
самим координатам. Геотрансформ реального гранула:
`[55440, 80, 0, 2247840, 0, −80]` — совпадает с ручным расчётом по центрам
пикселей.

## Шаг пикселей (bandwidth → spacing, User Guide /gcov, Table 1)

| Полоса (МГц) | GCOV шаг |
|---|---|
| 5 (frequencyB) | 80 м |
| 20 | 20 м |
| 40 | 10 м |
| 77 | 20 м |

## Именование файлов (User Guide /naming-conventions)

`NISAR_<IL>_<PT>_<PROD>_<CYL>_<REL>_<P>_<FRM>_<MODE>_<POLE>_<S>_<Start>_<End>_<CRID>_<A>_<C>_<LOC>_<CTR>.h5`

* `IL`: L = L-band (LSAR), S = S-band (SSAR)
* `PT` (processing type): **PR = Production**, **UR = Urgent Response**,
  OD = Science On-Demand
* `MODE`: полосы primary+secondary (40/20/77/05/00)
* `POLE`: поляризации по полосам: SH=HH, SV=VV, **DH=HH/HV**, DV=VV/VH,
  CL=LH/LV, CR=RH/RV, QP=HH/HV/VV/VH, NA
* примеры (реальные сцены из поиска 2026-09-29):
  * `NISAR_L2_PR_GCOV_031_134_D_052_0005_NASV_A_20260927T115535_..._P05023_N_P_J_001.h5`
    (frequencyB только, VV)
  * `NISAR_L2_UR_GCOV_031_151_A_012_4005_DHDH_A_20260928T155056_..._P05023_F_F_J_001.h5`
    (обе полосы, HH+HV)

## Статусы BETA / PROVISIONAL

По User Guide `/availability-overview`:

* **BETA** — февральский релиз 2026 (съёмки 2025-10-17 … 2026-01-20),
  предкалибровочные продукты, известные проблемы.
* **PROVISIONAL** — публичный релиз с 2026-07-20, съёмки с 2026-06-17,
  полностью откалиброваны; CRID **P05023**. Ранние BETA-данные
  переработаны в PROVISIONAL-коллекцию (подтверждено поиском: сцены за
  2026-01-30 лежат в `NISAR_L2_GCOV_PROVISIONAL_V1`).
* Смешивать BETA и PROVISIONAL в одном временном ряду нельзя.

**Как статус определяется в плагине (поиск, проверено на живом API):**
поле `collectionName`/URL коллекции ASF:
* `NISAR_L2_GCOV_PROVISIONAL_V1` (conceptID `C2854338529-ASF`) → PROVISIONAL
* `UR_L2_L_GCOV` / `NISAR_UR_L2` (conceptID `C2887502657-ASF`) → urgent
  response (обрабатывается как PROVISIONAL-эпоха, CRID P05023)
* коллекции `*_BETA*` → BETA

⚠️ **Внутри самого .h5 явного флага BETA/PROVISIONAL нет**, но после
проверки реального гранула плагин использует честную эвристику по CRID
(`_detect_data_status`): первая буква `compositeReleaseId` —
`B…` → BETA, `P…` → PROVISIONAL, `V…` → VALIDATED; иначе UNKNOWN и
предупреждение в GUI. На грануле-2026-09-28: `P05023` → PROVISIONAL ✅.
Статус из метаданных поиска остаётся приоритетным для скачанных сцен.

## Поиск через asf_search (проверено на живом API)

* Правильный вызов: `asf_search.search(dataset="NISAR",
  processingLevel="GCOV", intersectsWith=WKT, start=..., end=...)`.
  ⚠️ Изначальный код плагина использовал несуществующее имя датасета
  `NISAR_L2_GCOV` — исправлено.
* Поляризации: `properties.mainBandPolarization` /
  `sideBandPolarization` (например `['HH','HV']`).
* Размер: `properties.bytes` — словарь {имя_файла: {bytes, format}};
  брать `.h5`.
* Прочее: `startTime`, `flightDirection`, `frameNumber`, `orbit`,
  `collectionName`, `conceptID`, `crid`, `pgeVersion`, `url`, `s3Urls`,
  `additionalUrls`.
* Скачивание требует Earthdata Login (`~/.netrc`, машина
  `urs.earthdata.nasa.gov`). Анонимно недоступно (проверено: редирект
  на OAuth).
* ✅ **Скачивание проверено на реальном грануле** через производственный код
  плагина (`B2ASFSearchBackend.download` → `asf_search.download_url` с
  авторизованной сессией): 251 658 240 байт, размер совпал байт-в-байт.
  ⚠️ Найден и исправлен баг: `asf_search` 14.x не принимает аргумент
  `filetype` в `download_url` (сломал бы каждое скачивание в продакшене).
* Свежие GCOV-гранулы разных размеров (HEAD-пробы 2026-09-30): частичные
  кадры «_P_» — 250–420 МБ, полные — 0.9–4.8 ГБ. `properties.sizeMB`
  в поиске приходит пустым — размер надёжнее брать через HEAD/`bytes`.
* Хост выдачи NISAR — `nisar.asf.earthdatacloud.nasa.gov` (S3, presigned):
  принимает и сессию netrc/token-редиректы, и прямые Bearer-заголовки.
* ⚠️ Найден и исправлен второй баг того же класса: `asf_search` 14.x
  `search()` не принимает аргумент `session` — поиск в продакшене молча
  возвращал 0 сцен. Сессия теперь прикрепляется к `ASFSearchOptions`
  (проверено на живом API).

## Превью до скачивания (browse-изображения ASF)

Проверено на живом поиске 2026-09-30: у каждого NISAR-гранула есть
официальный набор browse-изображений в отдельном свойстве `properties.browse`
(⚠️ не в `additionalUrls` — там только kml/pdf/qa-сайдкары):

| Файл | Размер | Назначение |
|---|---|---|
| `<granule>_LATLON_thumbnail.png` | ~9 КБ (100×100) | миниатюра для панели превью |
| `<granule>_LATLON.png` | ~3 МБ | полный quicklook в географической проекции |
| `<granule>_NATIVE.png` | ~3.6 МБ | quicklook в проекции продукта |
| `<granule>_NATIVE_<A\|B>_<POL>.png` | 0.6–1.2 МБ | по каждой поляризации отдельно |

* ✅ **Миниатюры скачиваются анонимно** (без Earthdata Login): HTTP 200,
  PNG 9410 байт — панель превью работает даже без настроенного ~/.netrc.
* Footprint: живой поиск возвращает `geometry` Polygon (EPSG:4326, 5 точек)
  через `product.geojson()` — рисуется на канвасе QgsRubberBand'ом.
* У partial-frame гранул («_P_») набор browse меньше (5 URL вместо 7) —
  обработано.
* `mainBandPolarization` и `sideBandPolarization` дублируют друг друга
  (HH+HV+HH+HV) — в превью дедуплицируется в HH+HV.

## Чтение через GDAL

* GDAL ≥ 3.13 — нативный драйвер NISAR; QGIS ≥ 4.2 использует его.
* Старые GDAL: `.h5` без геопривязки; обход — открыть как netCDF
  (`NETCDF:"file.h5"` или симлинк `.nc`). ⚠️ Работоспособность префикса
  `NETCDF:` с `.h5` на целевых версиях GDAL не проверена (нет окружения
  QGIS/GDAL у разработчика на момент написания); код пробует оба пути и
  честно откатывается на A3 (h5py).
* PAM: `GDAL_PAM_ENABLED=NO`, чтобы не писать `.aux.xml` рядом с
  исходником.

## Что проверено, а что нет

| Факт | Статус |
|---|---|
| Пути слоёв `/science/LSAR/GCOV/grids/frequency<A\|B>/<...>` | ✅ по спецификатору + ✅ реальный гранул (frequencyB) |
| Форма (Length, Width) | ✅ спецификатор + ✅ реальный (4167×4248) |
| Единицы: линейная gamma-0 (RTC) | ✅ User Guide + ✅ реальный (mean VVVV=0.053 → −12.7 дБ) |
| `projection` c атрибутами epsg_code/spatial_ref | ✅ спецификатор + ✅ реальный (EPSG:32605 + полный WKT) |
| x/yCoordinates — Float64, метры, CF (центры) | ✅ спецификатор + ✅ реальный (spacing 80 м, конвенция center) |
| mask: 0=invalid, 255=outside | ✅ спецификатор + ✅ реальный (центр массива = 255, 4.1 М валидных пикселей) |
| identification-поля — скалярные датасеты | ✅ реальный гранул (granuleId/productType/CRID/… читаются) |
| frequencyB + V-дуал (VHVH/VVVV) в реальных продуктах | ✅ реальный гранул |
| Отрицательный yCoordinateSpacing (north-up) | ✅ реальный гранул (−80 м) |
| Статусы BETA/PROVISIONAL из коллекций | ✅ живой поиск ASF |
| CRID P05023 → PROVISIONAL | ✅ реальный гранул |
| Поиск `dataset=NISAR&processingLevel=GCOV` | ✅ живой поиск ASF |
| Скачивание с ASF (asf_search + сессия) | ✅ реальный гранул (251.7 МБ, побайтно) |
| Browse-превью ASF: `properties.browse`, 7 URL на гранул | ✅ живой поиск (2026-09-30) |
| Миниатюра quicklook анонимно (без EDL) | ✅ HTTP 200, PNG 9.4 КБ |
| Footprint Polygon (EPSG:4326) из поиска | ✅ живой поиск (bbox −157.5… 19.4…) |
| Поиск с сессией через ASFSearchOptions | ✅ живой поиск (после фикса TypeError) |
| Индексы hv_db/cross_ratio/RVI на реальных данных | ✅ реальный гранул (статистика совпала с attrs до 1e-6) |
| Структура на реальном .h5 файле | ✅ проверено 2026-09-30 |
| `NETCDF:`-префикс с .h5 на GDAL 3.6–3.11 | ⚠️ НЕ проверено |
| RVI формулы | ✅/⚠️ см. ниже |

## Формулы индексов и источники

* **hv_db**: `10 * log10(HVHV)` от линейной gamma-0. Стандартное
  SAR-преобразование.
* **cross_ratio**: `10*log10(HVHV) - 10*log10(HHHH)`. Определение
  cross-ratio (например, интерпретируется в поляриметрической
  литературе о лесах/биомассе).
* **RVI full-pol**: `8·HV / (HH + VV + 2·HV)` — классическая форма для
  квадруполяризационных данных (трассируется к работам Kim & van Zyl /
  Chen et al. 2009, `8σHV/(σHH+σVV+2σHV)`; подтверждена множественными
  современными реализациями: ArcGIS Pro SAR Indices, ESA forum).
  ⚠️ Оригинальная статья: Chen et al. 2009 — рекомендуется сослаться
  точнее перед v1-релизом.
* **RVI dual-pol (HH+HV)**: `4·HV / (HH + HV)` — широко используемая
  адаптация для двухполяризационных данных (для Sentinel-1 VV/VH
  публикуется как `4·VH/(VV+VH)`, напр. Mandal et al. 2020;
  для NISAR DH-режима заменяем co-pol HH; для DV-режима (реальный гранул
  NADV) — VV, формула автоматически `4·VHVH/(VVVV+VHVH)`).
  ✅ На реальном грануле: mean=0.097, p99=0.19 (разреженная растительность
  Аляски — правдоподобно). ⚠️ **Диапазон dual-pol RVI НЕ ограничен 1**:
  на реальных данных max = 3.7 (сильная cross-pol компонента) — не
  трактуйте значения >1 как ошибку.

Плагин показывает пользователю, какая формула RVI применена (dual/full)
и имена реальных слоёв в ней.

## Размеры файлов

Реальные GCOV-сцены из поиска (сентябрь 2026): 240 МБ … 4.8 ГБ
(зависит от числа поляризаций/полос и охвата кадра; ✅ подтверждено
HEAD-пробами 25 гранул 2026-09-30: частичные кадры 251–420 МБ, полные
780 МБ–4.77 ГБ). Рабочая гипотеза плагина «до ~7 ГБ» (AGENTS.md)
подтверждается косвенно.

## Валидация на реальных данных (2026-09-30)

Полный прогон: поиск (200 гранул) → выбор минимального (251.7 МБ) →
скачивание производственным кодом плагина → чтение A3-ридером →
расчёт трёх индексов. Все проверки пройдены; статистика чтения совпала
с заявленной в атрибутах файла (mean VHVH 0.00125704 vs 0.00125704,
mean VVVV 0.053332925 vs 0.053332753 — расхождение < 0.001%).
Юнит-тесты воспроизводят найденные особенности формата в
`tests/unit/test_real_granule_behaviors.py` (80 тестов зелёные).

## GUNW и обнаружение ветровалов (DiD) — P3 (2026-09-30)

### Структура GUNW (проверена на реальных гранулах)

Реальные гранулы (трек 093, кадр 58, PROVISIONAL P05023, ~2.5 ГБ):
`/science/LSAR/GUNW/grids/frequencyA/` содержит **две сетки**:

* `unwrappedInterferogram/HH/` — постинг **80 м**:
  `coherenceMagnitude`, `unwrappedPhase`, `connectedComponents`,
  `ionospherePhaseScreen(Uncertainty)`;
* `wrappedInterferogram/HH/` — постинг **20 м**:
  `coherenceMagnitude` (Float32), `wrappedInterferogram` (complex64,
  `_FillValue` — строка `"(nan+nanj)"`, не парсится во float — ридер
  игнорирует такой nodata);
* координаты лежат на уровне группы (`xCoordinates`, `yCoordinates`,
  `x/yCoordinateSpacing`, `projection`), y — убывание (north-up),
  spacing отрицательный;
* `mask` — **uint32** (в спецификаторе UByte — расхождение с JPL D-102272
  Rev E; реальный продукт главный);
* identification — на уровне продукта (`/science/LSAR/identification`) и
  содержит поля пары: `referenceZeroDopplerStartTime`,
  `secondaryZeroDopplerStartTime`, `reference/secondaryAbsoluteOrbitNumber`;
* `boundingPolygon` — тройки `lon lat elevation` (41 вершина, 123 числа),
  замкнутое кольцо.

Пары: только co-pol (HH или VV), только frequencyA, соседние 12-суточные
сцены (verified: ref 4661→sec 4834; control 4834→5007 — контрольная пара
начинается со сцены, которой заканчивается штормовая).

### Методика DiD (по валидированной методике sentinel1_windthrow)

`dcoh = γ(контрольная пара) − γ(штормовая пара)`; детектор:
порог `медиана(фон) + 0.25·MAD(фон)`, медианный фильтр 3×3, минимальный
объект 6 px. Фон — «лес с лесом»: Hansen GFC@Y−1 (treecover2000 ≥ 30%,
без потерь 2001..Y−1; для фона дополнительно исключаются потери года Y).
Метрики: AUC (ранговый, с усреднением связок), excess, TPR@FPR5%;
флаги `вне_леса@Y` и «безлесный до шторма» (медиана γ шторм-пары
внутри референса > 0.6).

### Hansen GFC (проверено вживую)

* URL: `https://storage.googleapis.com/earthenginepartners-hansen/
  GFC-2024-v1.12/Hansen_GFC-2024-v1.12_<layer>_<suffix>.tif`,
  layer ∈ {treecover2000, lossyear};
* **имя тайла = северная граница**: 60N_060E покрывает 50–60N, 00N —
  −10…0, 10S — −20…−10 (проверено чтением bounds);
* v1.12 = релиз GFC-2024 (lossyear 2001–2024; для событий после 2025
  правило «без потерь до события» насыщается до `lossyear == 0`);
* ⚠️ БАГ, найденный и закрытый: `rasterio.warp.reproject` по умолчанию
  (`init_dest_nodata=True`) обнуляет массив-приёмник перед warp — при
  накоплении нескольких тайлов в общий аккумулятор последний тайл
  затирал предыдущие. Фикс: `init_dest_nodata=False`.

### Пилот на реальном событии: торнадо 22.06.2026, Кушва

Полный конвейер от реальных гранул: пара 093D/f058 (шторм 20.06→02.07 +
контроль 02.07→14.07, сетки идентичны 4446×4446 EPSG:3413, ~15 с на
прогон), маска леса GFC (76.3% сцены), порог 0.060, детекция,
экспорт dcoh/mask/report. Результаты:

* фон (лес): медиана dcoh = +0.034, MAD = 0.105 — штормовая пара
  систематически декоррелирована сильнее контрольной; пиксельный
  порог 0.25·MAD поэтому даёт «широкий» алерт-слой (33% леса) —
  детектор по построению низкопороговый, см. методику;
* след торнадо ~121 м шириной (16.5 км, >200 га по СМИ) — **меньше
  трёх пикселей сетки 80 м**: граница применимости метода по статье
  подтверждена на NISAR (на 80 м след не выделяется);
* на 20-м постинге (wrappedInterferogram) ориентированный согласованный
  фильтр (полоса 24 км × 4–10 px вдоль меридиана 60E) даёт линейную
  аномалию z ≈ 4.2 на расстоянии 1.7 км от Кушвы — согласуется со
  следом, но требует референс-полигонов для подтверждения;
* вывод: для узких следов нужен режим 20 м (в ридере реализован),
  для валидации метрик AUC/excess/TPR нужны референс-полигоны
  (например, Sentinel-2) — конвейер их принимает (`ref_mask`).

### Что проверено в P3

| Факт | Статус |
|---|---|
| Пути GUNW `.../grids/frequencyA/<group>/HH/<dataset>` | ✅ реальный гранул |
| Сетки 80 м и 20 м в одном продукте, per-layer georef | ✅ реальный гранул |
| identification с полями reference*/secondary* | ✅ реальный гранул |
| boundingPolygon тройками lon/lat/elev, замкнутый | ✅ реальный гранул (разбор + тесты) |
| mask uint32 (не UByte, вопреки спеке) | ✅ реальный гранул |
| `_FillValue "(nan+nanj)"` у комплексного слоя | ✅ реальный гранул (ридер игнорирует) |
| Идентичность сеток одной track/frame пары | ✅ обе гранулы (побитовый transform) |
| Поиск `processingLevel=GUNW` (concept C2854335566-ASF) | ✅ живой API (7 сцен, размеры) |
| Полный DiD-конвейер на реальной паре | ✅ 2026-09-30 (~15 с) |
| Маска леса GFC на реальной сцене | ✅ 76.3%, выборочно сверена с прямыми пробами GFC |
| 20-м когерентность + оконное чтение | ✅ реальный гранул (7.3 с на окно 52×52 км) |
| Детекция узкого следа на 80 м | ❌ след < 3 px — граница метода (ожидаемо по статье) |
| AUC/excess/TPR на реальном событии | ⚠️ нужны референс-полигоны (конвейер готов) |
| Регистрация GUNW в A1/A2 (GDAL-ридеры) | ⚠️ не реализовано (A4 хватает для MVP) |

## P3.1 — аудит против эталонного репозитория sar_windthrow (2026-09-30)

Референс (плагин sentinel1_windthrow v1.2.1, 144 теста, закрытый репо,
клон предоставлен автором на время аудита) сверен с нашей реализацией.

### Совпадает (проверено численно/побитово)

| Элемент | Проверка |
|---|---|
| AUC: Mann-Whitney U с усреднением связок | численно идентичен на 5 случайных выборках со связками (diff < 1e-9) |
| Правило эпохи GFC (candidate/background) | побитово при Y ∈ {2015, 2017, 2024, 2025, 2026} — включая насыщение lossyear после 2024 |
| TPR@FPR5% | то же определение (порог = p95 фона, ref ≥ t) |
| excess = median(ref) − median(bg) | идентично |
| min_pixels = 6, 8-связность, отчёт JSON | идентично |
| Фон-кольцо 10 км, исключение «чужих» ветровалов | есть (other_damage_mask); у эталона — вычитание всех полигонов базы |

### Расхождение №1: формула адаптивного порога

- **Текст статьи §2.3**: «медиана фона + 0,25 её среднего абсолютного
  отклонения» → `median + 0.25·MAD`;
- **Код эталонного плагина v1.2.1** (`coh_delta.py`, METHOD.md,
  deliverables GPKG): `median + a_coh`, a_coh = 0.25 **в абсолютных
  единицах когерентности**, откалибровано на FPR ≈ 8 % (ID694) /
  14 % (ID666);
- это РАЗНЫЕ рабочие точки: при MAD фона ≈ 0.1 порог «по статье» ≈
  +0.03, «по коду» ≈ +0.28.

**Решение P3.1**: `WindthrowParams(threshold_mode)`:
- `"absolute"` (дефолт) — median + a_coh, как в эталонном коде и его
  deliverables (сравнимость детекций C-band ↔ L-band);
- `"mad"` — median + k·MAD, буквальная формулировка статьи (широкий
  алерт-слой).
GUI: выбор правила + поле a/k (активно соответствующее); Processing:
`THRESHOLD_MODE` (enum) + `A_COH`; отчёт JSON фиксирует mode/a_coh/k.

### Ре-прогон Кушвы (пара 093D/f058, без маски леса, весь кадр)

| Режим | Порог | Детекция | Доля сцены |
|---|---|---|---|
| absolute | +0.280 | 783 544 px / 501 468 га / 3993 объекта | 7.2 % |
| mad | +0.056 | 4 023 954 px / 2 575 331 га / 14 789 объектов | 33 % |

7.2 % в режиме absolute — согласуется с задокументированным FPR ~8 %
эталона на C-band: рабочая точка воспроизведена.

### Расхождение №2 (мелкое): порядок медианного фильтра

Эталон: медианный фильтр по dcoh (аналоговый, NaN-aware) ДО порога;
наш: порог, затем бинарная мажоритарная фильтрация 3×3. Намерение то же
(подавление изолированных откликов); расхождение зафиксировано, оставлено
как есть (бинарный вариант не требует scipy).

### Оптимизация P3.1: чтение слоёв GUNW

`compute_dcoh` читал слой тайлами (~324 оконных чтений h5py на слой,
222 с на реальной паре) — заменено на одно сплошное окно (79 МБ):
**222 с → 3 с** (×70). Тесты 127/127 зелёные, mock-import OK.

### Расхождения, сознательно НЕ перенесённые

- деградация до `1 − coh` при отсутствии контрольной пары (у эталона) —
  наш конвейер требует обе пары (DiD-семантика);
- burst-пары 20/40/80 м и парсинг GAMMA/ISCE-флейворов — Sentinel-1
  специфика, для GUNW не применима (проверка пар уже есть: track/frame/pol);
- «sane water mask» (отбраковка битых масок по доле воды) — у GUNW маска
  битовая со своим контрактом (бит 2^24 = no-data), проверена отдельно.
### Реальный гранул 2026-10-17 (DHDH, двойная частота) — маска и низкие значения

* Гранула `NISAR_L2_PR_GCOV_023_108_D_059_2005_DHDH_A_20260621T164248_…`
  (2.08 ГБ, PROVISIONAL, CRID P05023): frequencyA 19008x19044 @ 20 м
  **и frequencyB 4752x4761 @ 80 м — обе решётки UTM EPSG:32638**.
  Двух-частотность подтверждена не только на UR-клоне (251.7 МБ,
  2026-09-28), но и на штатном PR-продукте.
* NaN в индексах идёт из самих данных: вне полосы мощность уже NaN в
  продукте (`_FillValue` = NaN), индексы даю NaN честно (56.5% NaN на
  полном кадре). Слой `mask` для этого не нужен.
* **[ПРОВЕРИТЬ] семантика `mask == 0`** («невалидный отсвет» по JPL
  D-102272): 2-й перцентиль HV дБ на реальном кадре = -136 дБ —
  почти-нулевые пиксели ВНУТРИ трассы (эхо-дымки/вода), по `_FillValue`
  они валидны и проходят в дБ-преобразование как легитимные значения.
  Вопрос: нужно ли (опционально) исключать `mask == 0` в индексах и
  экспорте? Плата: в реальных GCOV mask — uint32 (см. примечание выше
  о расхождении со спецификатором), а не UByte. Перед изменением
  сверить с NISAR Data User Guide (nisar-docs.asf.alaska.edu).
* Мельчайший дефект исправлен (17.10.2026): маппинг филла вынесен в
  `export.apply_fill_nodata()` — конечный филл мапится по `==`, NaN-
  филл явно обрабатывается через `np.isnan` (раньше ветка `tile ==
  fill` была no-op при NaN, NaN != NaN). Поведение то же (в реальных
  GCOV данные уже NaN), но теперь оно явное и заперто тестами
  (`tests/unit/test_export_fill.py`, 3 юнит + 1 GDAL-guarded e2e).
