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
