# -*- coding: utf-8 -*-
"""
Internationalization (i18n) — runtime text loading for the plugin GUI.

Usage:
    from ..i18n import tr, set_language
    set_language("ru")
    label.setText(tr("ui.search"))
"""
from typing import Dict

_LANG = "en"
_TEXTS: Dict[str, Dict[str, str]] = {}


def _load(lang: str) -> Dict[str, str]:
    if lang in _TEXTS:
        return _TEXTS[lang]
    if lang == "ru":
        try:
            from .ru.texts import I18N_RU
            _TEXTS["ru"] = I18N_RU
            return I18N_RU
        except Exception:
            pass
    else:
        try:
            from .en.texts import I18N_EN
            _TEXTS["en"] = I18N_EN
            return I18N_EN
        except Exception:
            pass
    return {}


def set_language(lang: str) -> None:
    """Set active language ('en' or 'ru'). Unknown -> English."""
    global _LANG
    _LANG = "ru" if str(lang).lower().startswith("ru") else "en"
    _load(_LANG)


def get_language() -> str:
    return _LANG


def tr(key: str, default: str = "") -> str:
    """Translate *key*; returns *default* (or the key) when missing."""
    texts = _load(_LANG)
    value = texts.get(key)
    if value:
        return value
    if default:
        return default
    # Fall back to English before giving up.
    if _LANG != "en":
        value = _load("en").get(key)
        if value:
            return value
    return key


def available_texts(lang: str) -> Dict[str, str]:
    """Full dictionary of a language (tests / help generation)."""
    return dict(_load(lang))
