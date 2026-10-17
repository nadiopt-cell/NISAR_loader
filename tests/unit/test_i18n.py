# -*- coding: utf-8 -*-
"""Unit tests for i18n texts: parity RU/EN, hint lengths, coverage."""

from nisar_qgis.nisar_core.presets import PRESETS

# The i18n package lives under the plugin GUI layer but has no QGIS
# imports — importing it directly keeps pytest QGIS-free.
from nisar_qgis.i18n import tr, set_language, available_texts


EN = available_texts("en")
RU = available_texts("ru")


def test_languages_load():
    assert len(EN) > 60
    assert len(RU) > 60


def test_key_parity():
    """Every key must exist in both languages (TZ P2.8)."""
    en_only = set(EN) - set(RU)
    ru_only = set(RU) - set(EN)
    assert not en_only, "keys missing in RU: %s" % sorted(en_only)
    assert not ru_only, "keys missing in EN: %s" % sorted(ru_only)


def test_all_preset_keys_present():
    for preset in PRESETS.values():
        for key in (preset.name_key, preset.hint_key, preset.purpose_key,
                    preset.when_to_use_key, preset.how_to_read_key,
                    preset.formula_key, preset.caveats_key):
            assert key in EN, "missing EN key: %s" % key
            assert key in RU, "missing RU key: %s" % key


def test_hints_are_short():
    """AGENTS.md §9 — hint <= 100 chars in both languages."""
    for preset in PRESETS.values():
        assert len(EN[preset.hint_key]) <= 100, preset.hint_key
        assert len(RU[preset.hint_key]) <= 100, preset.hint_key


def test_tr_switching():
    set_language("en")
    assert tr("ui.tab_search") == "Search"
    set_language("ru")
    assert tr("ui.tab_search") == "Поиск"
    set_language("en")
    assert tr("ui.tab_search") == "Search"


def test_tr_falls_back_to_key():
    assert tr("no.such.key") == "no.such.key"
    assert tr("no.such.key", "fallback") == "fallback"


def test_status_keys():
    for status in ("beta", "provisional", "validated", "unknown"):
        assert "ui.status_%s" % status in EN
        assert "ui.status_%s" % status in RU
