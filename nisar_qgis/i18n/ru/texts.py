# -*- coding: utf-8 -*-
"""
Internationalization (i18n) for NISAR Plugin — Russian.
"""

I18N_RU = {
    # General UI
    "plugin.name": "NISAR Vegetation",
    "plugin.desc": "Плагин для работы с данными NISAR (мониторинг растительности)",

    # Tabs
    "ui.tab_search": "Поиск",
    "ui.tab_download": "Загрузка",
    "ui.tab_open": "Открыть",
    "ui.tab_process": "Обработка",
    "ui.tab_windthrow": "Ветровалы (DiD)",
    "ui.tab_export": "Экспорт",
    "ui.tab_settings": "Настройки",

    # Windthrow DiD tab (P3)
    "ui.windthrow.title": "Обнаружение ветровалов: DiD когерентности пары GUNW",
    "ui.windthrow.storm": "Штормовая пара GUNW (.h5)",
    "ui.windthrow.storm_placeholder": "пара, накрывающая дату шторма",
    "ui.windthrow.control": "Контрольная пара GUNW (.h5)",
    "ui.windthrow.control_placeholder": "соседний 12-суточный интервал, тот же трек/кадр",
    "ui.windthrow.event_date": "Дата шторма (необязательно)",
    "ui.windthrow.threshold_mode": "Правило порога",
    "ui.windthrow.mode_absolute": "медиана + a (эталонный плагин)",
    "ui.windthrow.mode_mad": "медиана + k·MAD (статья)",
    "ui.windthrow.a_coh": "Смещение a (единицы когерентности)",
    "ui.windthrow.k_mad": "Порог k (медиана + k·MAD)",
    "ui.windthrow.min_pixels": "Минимальный объект (пикселей)",
    "ui.windthrow.forest_mask": "Ограничить лесом Hansen GFC (онлайн-тайлы)",
    "ui.windthrow.polygonize": "Векторизовать детекции (GeoPackage)",
    "ui.windthrow.output_dir": "Каталог результатов",
    "ui.windthrow.run": "Найти ветровалы",
    "ui.windthrow.report_hint": "Здесь появится отчёт после запуска.",
    "ui.windthrow.no_storm": "Выберите гранулу GUNW штормовой пары (.h5)",
    "ui.windthrow.no_control": "Выберите гранулу GUNW контрольной пары (.h5)",
    "ui.windthrow.bad_date": "Неверная дата {value} (ожидается YYYY-MM-DD)",
    "ui.windthrow.bad_params": "Неверные параметры детектора (k и минимальный размер объекта должны быть числами)",
    "ui.windthrow.open_failed": "Не удалось открыть гранулы GUNW: {error}",
    "ui.windthrow.incompatible": "Пары несовместимы: {issues}",
    "ui.windthrow.pair_warning": "⚠ {warning}",
    "ui.windthrow.running": "Выполняется… (чтение когерентности; сборка маски леса может занять несколько минут)",
    "ui.windthrow.done": "Готово",
    "ui.windthrow.failed": "Ошибка: {error}",
    "ui.windthrow.r_method": "Метод",
    "ui.windthrow.r_storm": "Штормовая пара",
    "ui.windthrow.r_control": "Контрольная пара",
    "ui.windthrow.r_layer": "Слой",
    "ui.windthrow.r_background": "Пикселей фона",
    "ui.windthrow.r_threshold": "Порог",
    "ui.windthrow.r_detection": "Обнаружено",
    "ui.windthrow.r_objects": "объектов",
    "ui.windthrow.r_flags": "Флаги",
    "ui.windthrow.r_metrics": "Метрики",

    # Search tab
    "ui.search.title": "Поиск сцен в ASF",
    "ui.search.use_map_extent": "Взять экстент карты",
    "ui.search.aoi_wkt": "AOI (WKT, из экстента карты)",
    "ui.search.start_date": "Начальная дата (YYYY-MM-DD)",
    "ui.search.end_date": "Конечная дата (YYYY-MM-DD)",
    "ui.search.product_type": "Тип продукта",
    "ui.search.button": "Искать",
    "ui.search.stop": "Остановить поиск",
    "ui.search.searching": "Поиск...",
    "ui.search.no_results": "По заданным критериям сцены не найдены.",
    "ui.search.results": "Результаты поиска",
    "ui.search.col_scene": "Идентификатор сцены",
    "ui.search.col_date": "Дата",
    "ui.search.col_status": "Статус",
    "ui.search.col_size": "Размер",
    "ui.search.col_select": "Выбрать",
    "ui.search.backend_unavailable": (
        "Онлайн-поиск недоступен: {reason}.\n\n"
        "Локальные файлы NISAR можно открыть на вкладке «Открыть»."),
    "ui.search.beta_warning": (
        "BETA-продукты не полностью откалиброваны. Для анализа предпочитайте "
        "PROVISIONAL и не смешивайте BETA и PROVISIONAL в одном ряду данных."),
    "ui.search.aoi_hint": "Нажмите «Взять экстент карты», чтобы задать AOI.",

    # Preview panel (P2.5 — preview before download)
    "ui.preview.title": "Превью сцены (до скачивания)",
    "ui.preview.hint": (
        "Выберите строку результата, чтобы увидеть превью сцены: "
        "quicklook-изображение, детали и границы на карте."),
    "ui.preview.loading": "Загрузка quicklook...",
    "ui.preview.unavailable": "Quicklook-изображение недоступно.",
    "ui.preview.failed": "Не удалось загрузить quicklook: {error}",
    "ui.preview.no_footprint": "Границы сцены неизвестны.",
    "ui.preview.zoom": "К границам сцены",
    "ui.preview.open_browse": "Открыть полное изображение",
    "ui.preview.detail_scene": "Сцена",
    "ui.preview.detail_product": "Продукт",
    "ui.preview.detail_acquired": "Съёмка (UTC)",
    "ui.preview.detail_status": "Статус",
    "ui.preview.detail_size": "Размер скачивания",
    "ui.preview.detail_pols": "Поляризации",
    "ui.preview.detail_orbit": "Орбита",
    "ui.preview.detail_frame": "Кадр / трек",
    "ui.preview.detail_collection": "Коллекция",
    "ui.preview.detail_bbox": "Границы (долгота/ширина)",

    # Download tab
    "ui.download.title": "Очередь скачивания",
    "ui.download.button": "Скачать выбранные сцены",
    "ui.download.cancel": "Отменить",
    "ui.download.no_scenes": "Не выбрано ни одной сцены для скачивания.",
    "ui.download.col_scene": "Идентификатор сцены",
    "ui.download.col_progress": "Прогресс",
    "ui.download.col_status": "Статус",
    "ui.download.started": "Скачивание запущено для сцен: {n}.",
    "ui.download.done": "Скачано: {path}",
    "ui.download.failed": "Ошибка скачивания: {error}",
    "ui.download.hint_netrc": (
        "Скачивание с ASF требует Earthdata Login. Настройте ~/.netrc:\n"
        "machine urs.earthdata.nasa.gov\n  login ВАШ_ЛОГИН_EDL\n"
        "  password ВАШ_ПАРОЛЬ_EDL"),

    # Open tab
    "ui.open.title": "Открыть локальный продукт NISAR",
    "ui.open.browse": "Обзор...",
    "ui.open.file_label": "Файл NISAR (.h5)",
    "ui.open.inspect": "Проверить",
    "ui.open.layers": "Слои, найденные в продукте",
    "ui.open.col_layer": "Слой",
    "ui.open.col_pol": "Поляризация",
    "ui.open.col_units": "Единицы",
    "ui.open.col_size": "Размер (пикс.)",
    "ui.open.col_freq": "Частота",
    "ui.open.add_selected": "Добавить выбранные слои в проект",
    "ui.open.no_file": "Сначала выберите файл NISAR (.h5).",
    "ui.open.open_failed": "Не удалось открыть продукт: {error}",
    "ui.open.georef_warning": (
        "Продукт не содержит валидной геопривязки ({reasons}).\n"
        "Слои НЕ размещены на карте. Проверьте файл или обновите QGIS/GDAL."),
    "ui.open.beta_hint": "Статус продукта: {status}",
    "ui.open.added": "Добавлено слоёв: {n} (группа «{group}»).",
    "ui.open.added_collision": "Слой {path} уже запланирован — пропуск.",

    # Processing tab
    "ui.process.title": "Пресеты для растительности",
    "ui.process.col_preset": "Пресет",
    "ui.process.col_available": "Доступен",
    "ui.process.details": "Что это?",
    "ui.process.run": "Вычислить",
    "ui.process.running": "Вычисление...",
    "ui.process.no_product": "Сначала откройте продукт NISAR (вкладка «Открыть»).",
    "ui.process.done": "Вычислено {preset}: {path}",
    "ui.process.failed": "Ошибка обработки: {error}",
    "ui.process.requires": "Требуется: {req}",
    "ui.process.frequency": "Частота решётки",

    # Export tab
    "ui.export.title": "Экспорт",
    "ui.export.path": "Путь к выходному GeoTIFF",
    "ui.export.browse": "Обзор...",
    "ui.export.cog": "Cloud Optimized GeoTIFF (COG)",
    "ui.export.button": "Экспортировать",
    "ui.export.source_layer": "Слой открытого продукта",
    "ui.export.no_product": "Сначала откройте продукт и выберите слой.",
    "ui.export.done": "Экспортировано в {path}",
    "ui.export.failed": "Ошибка экспорта: {error}",

    # Settings tab
    "ui.settings.title": "Настройки",
    "ui.settings.reader_backend": "Бекенд чтения",
    "ui.settings.access_backend": "Бекенд доступа",
    "ui.settings.download_dir": "Папка загрузок",
    "ui.settings.language": "Язык",
    "ui.settings.beta_warnings": "Предупреждать о BETA-продуктах",
    "ui.settings.save": "Сохранить настройки",
    "ui.settings.saved": "Настройки сохранены.",
    "ui.settings.browse": "...",

    # Generic
    "ui.error": "Ошибка",
    "ui.warning": "Предупреждение",
    "ui.info": "Информация",
    "ui.ok": "ОК",
    "ui.status_beta": "БЕТА",
    "ui.status_provisional": "ПРЕДВАРИТЕЛЬНЫЙ (Provisional)",
    "ui.status_validated": "ВАЛИДИРОВАННЫЙ",
    "ui.status_unknown": "НЕИЗВЕСТНО",
    "ui.units": "Единицы: {units}",

    # Preset: HV dB
    "preset.hv_db.name": "HV (кросс-поляризация), дБ",
    "preset.hv_db.hint": "Общий «объём» растительности: чем выше, тем больше рассеивающей биомассы.",
    "preset.hv_db.purpose": "Показывает обратное рассеяние в кросс-поляризации. Оно возникает главным образом при многократном рассеянии в кронах, ветвях и стеблях, поэтому хорошо отражает структуру и объём растительности.",
    "preset.hv_db.when_to_use": "Карты леса и не-леса, сравнение густоты растительности, основа для временных рядов. Хуже подходит для оценки очень высокой биомассы: сигнал со временем перестаёт расти (насыщение).",
    "preset.hv_db.how_to_read": "Выше (менее отрицательные дБ) — больше растительного объёма. Голая почва и вода дают низкие значения.",
    "preset.hv_db.formula": "10 * log10(HVHV)",
    "preset.hv_db.caveats": "Зависит от влажности растительности и почвы, от режима съёмки и угла. Значения из разных орбит и геометрий напрямую не сравнивать.",

    # Preset: Cross-ratio
    "preset.cross_ratio.name": "Cross-ratio (HV/HH)",
    "preset.cross_ratio.hint": "Отношение «объёмного» рассеяния к «поверхностному» — помогает отделить растительность от почвы.",
    "preset.cross_ratio.purpose": "Нормирует HV на HH, частично уменьшая влияние общей яркости сцены и угла падения.",
    "preset.cross_ratio.when_to_use": "Разделение открытых и покрытых растительностью участков, слежение за ростом культур.",
    "preset.cross_ratio.how_to_read": "В дБ — разность HV_dB - HH_dB. Больше — выше доля объёмного рассеяния.",
    "preset.cross_ratio.formula": "10*log10(HVHV/HHHH)",
    "preset.cross_ratio.caveats": "Чувствителен к шуму на слабых сигналах (голая почва, вода). Требует HH и HV одновременно.",

    # Preset: RVI
    "preset.rvi.name": "RVI (Радарный вегетационный индекс)",
    "preset.rvi.hint": "Радарный аналог «индекса зелени»: 0 — почти нет растительности, выше — больше.",
    "preset.rvi.purpose": "Единый безразмерный индекс густоты растительности, менее зависимый от яркости сцены, чем сырое обратное рассеяние.",
    "preset.rvi.when_to_use": "Сезонная динамика культур, сравнение участков, ситуации с облачностью, где оптические индексы недоступны.",
    "preset.rvi.how_to_read": "Обычно принимает значения от 0 до порядка 1; больше — гуще растительный покров.",
    "preset.rvi.formula": "dual-pol: 4*HV / (HH + HV); full-pol: 8*HV / (HH + VV + 2*HV)",
    "preset.rvi.caveats": "Не эквивалентен NDVI и не «измеряет зелень» — реагирует на структуру и влажность. Формула выбирается автоматически по доступным поляризациям.",

    # Preset: Time Series
    "preset.timeseries.name": "Временной ряд по AOI",
    "preset.timeseries.hint": "Как менялся сигнал на вашем участке по датам: сезон, уборка, вырубка.",
    "preset.timeseries.purpose": "Считает статистику выбранного слоя или индекса (среднее, медиана, стандартное отклонение) по полигонам на всех датах и строит график и таблицу.",
    "preset.timeseries.when_to_use": "Фенология культур, поиск даты уборки или посева, слежение за состоянием леса.",
    "preset.timeseries.how_to_read": "Сглаженные сезонные изменения — норма; резкий скачок вниз или вверх — событие (уборка, нарушение, изменение влажности).",
    "preset.timeseries.formula": "Статистический анализ временного ряда",
    "preset.timeseries.caveats": "Не смешивать BETA и PROVISIONAL; сравнивать сцены одной орбиты и геометрии.",

    # Preset: Change Detection
    "preset.change_db.name": "Детектор изменений (дБ)",
    "preset.change_db.hint": "Показывает, где сигнал заметно изменился между двумя датами (например, вырубка).",
    "preset.change_db.purpose": "Разность двух сцен в дБ и бинарная маска по порогу.",
    "preset.change_db.when_to_use": "Быстрый поиск нарушений леса, уборки, затопления после события.",
    "preset.change_db.how_to_read": "Сильное падение HV часто указывает на потерю растительной структуры; рост — на рост или увлажнение.",
    "preset.change_db.formula": "10 * log10(date2 / date1)",
    "preset.change_db.caveats": "Порог задаёт пользователь; сцены должны быть из одной геометрии.",

    # Preset: Speckle Filter
    "preset.speckle.name": "Спекл-фильтр",
    "preset.speckle.hint": "Сглаживает «зернистость» радарного изображения для лучшего вида.",
    "preset.speckle.purpose": "Снижает спекл-шум (медиана или бокс 3x3, 5x5, 7x7).",
    "preset.speckle.when_to_use": "Визуализация и карты для отчётов. Для количественного анализа сначала подумайте, нужен ли он: фильтр размывает детали.",
    "preset.speckle.how_to_read": "Значения остаются в тех же единицах, но теряют мелкие детали.",
    "preset.speckle.formula": "Медианная или равномерная фильтрация",
    "preset.speckle.caveats": "Всегда сохраняется как отдельный слой; исходные научные значения не перезаписываются.",

    # Preset: Pauli RGB
    "preset.pauli_rgb.name": "Pauli RGB (full-pol)",
    "preset.pauli_rgb.hint": "Цветная композиция, где цвет подсказывает механизм рассеяния.",
    "preset.pauli_rgb.purpose": "Комбинирует поляризационные каналы в RGB для быстрого визуального разделения типов поверхности.",
    "preset.pauli_rgb.when_to_use": "Обзорный осмотр сцены: поверхность, двойное отражение (строения, стволы у воды), объёмное рассеяние (кроны).",
    "preset.pauli_rgb.how_to_read": "Соответствие цветов механизмам зависит от выбранной схемы — держите легенду рядом.",
    "preset.pauli_rgb.formula": "RGB-композиция разложения Паули",
    "preset.pauli_rgb.caveats": "Нужен full-pol; это визуализация, а не количественный продукт. Запланировано на следующие версии.",

    # Preset: Freeman-Durden
    "preset.freeman_durden.name": "Фриман–Дюрден (full-pol)",
    "preset.freeman_durden.hint": "Разбивает сигнал на вклад поверхности, двойного отражения и растительности.",
    "preset.freeman_durden.purpose": "Оценивает долю мощности по трём механизмам рассеяния.",
    "preset.freeman_durden.when_to_use": "Разделение лес / поле / вода / застройка, изучение структуры покрова.",
    "preset.freeman_durden.how_to_read": "Три слоя мощности; преобладание объёмной составляющей типично для густой растительности.",
    "preset.freeman_durden.formula": "Трёхкомпонентное разложение Фримана–Дюрдена",
    "preset.freeman_durden.caveats": "Нужен full-pol; известны артефакты (например, отрицательные мощности), которые надо обрабатывать явно. Запланировано на следующие версии.",

    # Preset: H/A/alpha
    "preset.h_a_alpha.name": "H/A/alpha (full-pol)",
    "preset.h_a_alpha.hint": "Классификация «по типу рассеяния» без обучающей выборки.",
    "preset.h_a_alpha.purpose": "Считает энтропию (H), анизотропию (A) и угол α, описывающие степень «хаотичности» и характер рассеяния.",
    "preset.h_a_alpha.when_to_use": "Исследование структуры покрова, вход для классификации.",
    "preset.h_a_alpha.how_to_read": "Высокая энтропия — смесь механизмов (типично для лесов); низкая — доминирует один механизм (например, гладкая поверхность).",
    "preset.h_a_alpha.formula": "Разложение Клауда–Поттье",
    "preset.h_a_alpha.caveats": "Только full-pol; нужна осторожность с интерпретацией без опыта в поляриметрии. Запланировано на следующие версии.",
}
