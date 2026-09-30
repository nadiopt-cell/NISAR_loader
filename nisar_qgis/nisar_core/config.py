# -*- coding: utf-8 -*-
"""
Plugin configuration — pure dataclasses, no QGIS imports.

``PluginConfig`` is deliberately QGIS-free so that ``nisar_core`` can be
imported and unit-tested without a running QGIS application.

EDL credentials are NOT stored here: authentication relies on
``~/.netrc`` (see asf_search / earthaccess docs) or QgsAuthManager in
the GUI layer. Storing passwords in settings is forbidden (TZ P0.6).
"""
import os
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class ReaderBackend(Enum):
    AUTO = "auto"
    A1_NATIVE = "A1_native"
    A2_NETCDF_WORKAROUND = "A2_netcdf_workaround"
    A3_H5PY = "A3_h5py"
    A4_EXTERNAL = "A4_external"


class AccessBackend(Enum):
    AUTO = "auto"
    B1_LOCAL = "B1_local"
    B2_ASF_SEARCH = "B2_asf_search"
    B3_EARTHACCESS = "B3_earthaccess"
    B4_STREAM = "B4_stream"
    B5_EXTERNAL_PLUGIN = "B5_external_plugin"


class ProcessingBackend(Enum):
    AUTO = "auto"
    V1_GDAL = "V1_gdal"
    V2_NUMPY = "V2_numpy"
    V3_POLARIMETRY = "V3_polarimetry"
    V4_EXPORT_ONLY = "V4_export_only"


@dataclass
class PluginConfig:
    """Runtime configuration (persisted by nisar_qgis.config_manager)."""
    # Backend selection
    reader_backend: ReaderBackend = ReaderBackend.AUTO
    access_backend: AccessBackend = AccessBackend.AUTO
    processing_backend: ProcessingBackend = ProcessingBackend.AUTO

    # Paths
    cache_dir: Path = field(
        default_factory=lambda: Path.home() / ".cache" / "nisar_qgis")
    download_dir: Path = field(
        default_factory=lambda: Path.home() / "Downloads" / "NISAR")
    temp_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("TEMP", "/tmp")) / "nisar_qgis")

    # Network
    download_chunk_size: int = 8192
    max_concurrent_downloads: int = 2
    request_timeout: int = 300
    verify_ssl: bool = True

    # Processing
    tile_size: int = 512
    max_memory_mb: int = 1500
    enable_pam: bool = False  # GDAL_PAM_ENABLED — avoid .aux.xml next to sources
    pam_proxy_dir: Optional[Path] = None

    # Earthdata / ASF — username only, never a password.
    # Auth itself is done via ~/.netrc or QgsAuthManager.
    edl_username: str = ""
    use_netrc: bool = True
    asf_search_page_size: int = 100

    # UI
    language: str = "en"  # "en" (default) or "ru"
    show_beta_warnings: bool = True
    auto_apply_styles: bool = True


def ensure_dirs(config: PluginConfig) -> None:
    """Create cache/download/temp dirs if they do not exist yet."""
    for p in (config.cache_dir, config.download_dir, config.temp_dir):
        try:
            Path(p).mkdir(parents=True, exist_ok=True)
        except OSError:
            # Non-fatal: read-only home etc. — readers still work.
            pass
