# -*- coding: utf-8 -*-
"""
Base access backend interface — search, download, local files.
"""
import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from pathlib import Path

from ..models import SceneRecord, SearchParameters

logger = logging.getLogger("nisar.access")


class SearchError(RuntimeError):
    """A search backend failed (WP-4, finding F8).

    Search must never fail silently: a total failure raises this error
    with the explanatory text; partial (per-product-type) failures are
    collected in ``backend.search_warnings`` for the GUI to display.
    """


@dataclass
class DownloadProgress:
    """Progress info for downloads."""
    scene_id: str
    bytes_downloaded: int
    total_bytes: int
    status: str  # "starting", "downloading", "completed", "failed", "cancelled"
    error_message: str = ""
    file_path: str = ""


class BaseAccessBackend(ABC):
    """Abstract base class for all access backends."""

    BACKEND_ID: str = "base"
    BACKEND_NAME: str = "Base Access"
    DEPENDENCY_HINT: str = ""  # pip install hint shown to the user

    def __init__(self, config: Dict[str, Any] = None):
        # Accept dicts and dataclass-like config objects.
        if config is None:
            self.config: Dict[str, Any] = {}
        elif isinstance(config, dict):
            self.config = config
        elif hasattr(config, "__dict__"):
            self.config = {k: (str(v) if hasattr(v, "__fspath__") else v)
                           for k, v in vars(config).items()}
        else:
            self.config = {}

    @classmethod
    @abstractmethod
    def check_availability(cls) -> tuple:
        """(available, reason_if_not) on the current system."""

    @abstractmethod
    def search(self, params: SearchParameters) -> List[SceneRecord]:
        """Search for scenes matching parameters."""

    @abstractmethod
    def download(self, scene: SceneRecord, output_dir: Path,
                 progress_callback=None) -> Path:
        """Download a scene to output directory."""

    @abstractmethod
    def get_local_path(self, scene: SceneRecord) -> Optional[Path]:
        """Local path if the scene is already on disk, else None."""


class LocalFileBackend(BaseAccessBackend):
    """B1: local files only — always available, no online search.

    The GUI 'Open' tab is the primary interface for local files; search()
    honestly returns an empty list instead of pretending to search.
    """

    BACKEND_ID = "B1_local"
    BACKEND_NAME = "Local files (no online search)"

    @classmethod
    def check_availability(cls) -> tuple:
        return True, ""

    def search(self, params: SearchParameters) -> List[SceneRecord]:
        logger.info("B1 (local) backend does not perform online search — "
                    "use the Open tab to work with local NISAR files")
        return []

    def download(self, scene: SceneRecord, output_dir: Path,
                 progress_callback=None) -> Path:
        local = self.get_local_path(scene)
        if local:
            return local
        raise RuntimeError(
            "Scene %s not found locally. Use the ASF search backend (B2) "
            "to download it first." % scene.scene_id)

    def get_local_path(self, scene: SceneRecord) -> Optional[Path]:
        download_dir = Path(self.config.get(
            "download_dir", str(Path.home() / "Downloads" / "NISAR")))
        for suffix in (".h5", ".hdf5"):
            path = download_dir / (scene.scene_id + suffix)
            if path.exists():
                return path
        return None


class AccessRegistry:
    """Registry of available access backends."""

    _backends: List[type] = []
    # Preference order for auto-selection: online backends first,
    # local backend as the always-available fallback.
    _priority = ("B2_asf_search", "B3_earthaccess", "B1_local")

    @classmethod
    def register(cls, backend_class: type):
        if backend_class not in cls._backends:
            cls._backends.append(backend_class)
            logger.debug("Registered access backend %s", backend_class.BACKEND_ID)

    @classmethod
    def get_available_backends(cls) -> List[type]:
        available = []
        for backend in cls._backends:
            try:
                avail, _reason = backend.check_availability()
            except Exception:  # pragma: no cover
                avail = False
            if avail:
                available.append(backend)
        return available

    @classmethod
    def select_backend(cls, preferred: str = "auto") -> type:
        available = cls.get_available_backends()

        if preferred and preferred != "auto":
            for backend in available:
                if backend.BACKEND_ID == preferred:
                    return backend
            raise ValueError(
                "Access backend %r is not available. Check that the "
                "required package is installed (e.g. pip install asf_search)."
                % preferred)

        for backend_id in cls._priority:
            for backend in available:
                if backend.BACKEND_ID == backend_id:
                    return backend
        if available:
            return available[0]
        raise RuntimeError("No available access backends")

    @classmethod
    def list_registered(cls) -> List[Dict[str, str]]:
        result = []
        for backend in cls._backends:
            try:
                avail, reason = backend.check_availability()
            except Exception as exc:  # pragma: no cover
                avail, reason = False, str(exc)
            result.append({
                "id": backend.BACKEND_ID,
                "name": backend.BACKEND_NAME,
                "available": avail,
                "reason": reason if not avail else "",
            })
        return result


# Register the always-available local backend.
AccessRegistry.register(LocalFileBackend)
