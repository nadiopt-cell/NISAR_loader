# -*- coding: utf-8 -*-
"""
Config manager — the only place where QgsSettings is touched.

Lives in ``nisar_qgis`` (not in ``nisar_core``) so the core stays
importable without QGIS (TZ principle 8). ``PluginConfig`` itself is a
pure dataclass defined in ``nisar_qgis.nisar_core.config``.
"""
from dataclasses import fields
from pathlib import Path
from typing import Optional

from qgis.core import QgsSettings

from .nisar_core.config import (
    PluginConfig, ReaderBackend, AccessBackend, ProcessingBackend,
    ensure_dirs,
)

SETTINGS_PREFIX = "NISARVegetation"


class ConfigManager:
    """Load/save PluginConfig via QgsSettings (QGIS user profile)."""

    def __init__(self):
        self.settings = QgsSettings()
        self._config: Optional[PluginConfig] = None

    # ------------------------------------------------------------------ load
    def load(self) -> PluginConfig:
        """Load config (cached) from QgsSettings."""
        if self._config is not None:
            return self._config

        cfg = PluginConfig()
        g = self._get

        cfg.reader_backend = ReaderBackend(g("reader_backend",
                                             cfg.reader_backend.value))
        cfg.access_backend = AccessBackend(g("access_backend",
                                             cfg.access_backend.value))
        cfg.processing_backend = ProcessingBackend(g("processing_backend",
                                                     cfg.processing_backend.value))

        cfg.cache_dir = Path(g("cache_dir", str(cfg.cache_dir)))
        cfg.download_dir = Path(g("download_dir", str(cfg.download_dir)))
        cfg.temp_dir = Path(g("temp_dir", str(cfg.temp_dir)))

        cfg.download_chunk_size = int(g("download_chunk_size", cfg.download_chunk_size))
        cfg.max_concurrent_downloads = int(g("max_concurrent_downloads", cfg.max_concurrent_downloads))
        cfg.request_timeout = int(g("request_timeout", cfg.request_timeout))
        cfg.verify_ssl = self._to_bool(g("verify_ssl", cfg.verify_ssl))

        cfg.tile_size = int(g("tile_size", cfg.tile_size))
        cfg.max_memory_mb = int(g("max_memory_mb", cfg.max_memory_mb))
        cfg.enable_pam = self._to_bool(g("enable_pam", cfg.enable_pam))
        pam_dir = g("pam_proxy_dir", "")
        cfg.pam_proxy_dir = Path(pam_dir) if pam_dir else None

        cfg.edl_username = g("edl_username", "")
        cfg.use_netrc = self._to_bool(g("use_netrc", cfg.use_netrc))
        cfg.asf_search_page_size = int(g("asf_search_page_size", cfg.asf_search_page_size))

        cfg.language = g("language", cfg.language)
        cfg.show_beta_warnings = self._to_bool(g("show_beta_warnings", cfg.show_beta_warnings))
        cfg.auto_apply_styles = self._to_bool(g("auto_apply_styles", cfg.auto_apply_styles))

        ensure_dirs(cfg)
        self._config = cfg
        return cfg

    # ------------------------------------------------------------------ save
    def save(self, config: PluginConfig) -> None:
        """Persist config to QgsSettings. Passwords are never stored."""
        s = self._set
        s("reader_backend", config.reader_backend.value)
        s("access_backend", config.access_backend.value)
        s("processing_backend", config.processing_backend.value)
        s("cache_dir", str(config.cache_dir))
        s("download_dir", str(config.download_dir))
        s("temp_dir", str(config.temp_dir))
        s("download_chunk_size", config.download_chunk_size)
        s("max_concurrent_downloads", config.max_concurrent_downloads)
        s("request_timeout", config.request_timeout)
        s("verify_ssl", config.verify_ssl)
        s("tile_size", config.tile_size)
        s("max_memory_mb", config.max_memory_mb)
        s("enable_pam", config.enable_pam)
        s("pam_proxy_dir", str(config.pam_proxy_dir) if config.pam_proxy_dir else "")
        s("edl_username", config.edl_username)
        s("use_netrc", config.use_netrc)
        s("asf_search_page_size", config.asf_search_page_size)
        s("language", config.language)
        s("show_beta_warnings", config.show_beta_warnings)
        s("auto_apply_styles", config.auto_apply_styles)
        self._config = config

    # -------------------------------------------------------------- helpers
    def reset_to_defaults(self) -> None:
        """Reset all plugin settings."""
        self.settings.remove(SETTINGS_PREFIX)
        self._config = None

    def _get(self, key: str, default):
        return self.settings.value("%s/%s" % (SETTINGS_PREFIX, key), default)

    def _set(self, key: str, value) -> None:
        self.settings.setValue("%s/%s" % (SETTINGS_PREFIX, key), value)

    @staticmethod
    def _to_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("1", "true", "yes", "t")


# Global instance (GUI layer only)
config_manager = ConfigManager()


def config_as_dict(config: PluginConfig) -> dict:
    """Convert PluginConfig to a plain dict for core backends."""
    result = {}
    for f in fields(config):
        value = getattr(config, f.name)
        if isinstance(value, Path):
            value = str(value)
        elif hasattr(value, "value"):  # enums
            value = value.value
        result[f.name] = value
    return result
