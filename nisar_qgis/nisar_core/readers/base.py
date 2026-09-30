# -*- coding: utf-8 -*-
"""
Base reader interface — all backends implement this.
"""
import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Dict, Any

import numpy as np

from ..models import ProductHandle, LayerInfo, GeorefInfo

logger = logging.getLogger("nisar.readers")


class BaseReader(ABC):
    """Abstract base class for all reader backends."""

    BACKEND_ID: str = "base"
    BACKEND_NAME: str = "Base Reader"
    REQUIRES_GDAL_VERSION: Optional[Tuple[int, int, int]] = None
    REQUIRES_DEPENDENCIES: List[str] = []

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    @classmethod
    @abstractmethod
    def can_open(cls, path: str) -> bool:
        """Check if this backend can open the given file."""

    @classmethod
    @abstractmethod
    def check_availability(cls) -> Tuple[bool, str]:
        """(available, reason_if_not) for this backend on the current system."""

    @abstractmethod
    def open(self, path: str) -> ProductHandle:
        """Open a product and return a ProductHandle."""

    @abstractmethod
    def read_window(self, handle: ProductHandle, layer_name: str,
                    window: Tuple[int, int, int, int]) -> np.ndarray:
        """Read a window (xoff, yoff, xsize, ysize) as a numpy array."""

    @abstractmethod
    def close(self, handle: ProductHandle):
        """Close the product handle and release resources."""

    def get_georef(self, handle: ProductHandle) -> Optional[GeorefInfo]:
        return handle.georef

    def get_metadata(self, handle: ProductHandle) -> Dict[str, Any]:
        return handle.metadata

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class ReaderRegistry:
    """Registry of available reader backends with auto-selection."""

    _backends: List[type] = []

    @classmethod
    def register(cls, backend_class: type):
        if backend_class not in cls._backends:
            cls._backends.append(backend_class)
            logger.debug("Registered reader backend %s", backend_class.BACKEND_ID)

    @classmethod
    def unregister(cls, backend_class: type):
        if backend_class in cls._backends:
            cls._backends.remove(backend_class)

    @classmethod
    def get_available_backends(cls) -> List[type]:
        available = []
        for backend in cls._backends:
            try:
                avail, reason = backend.check_availability()
            except Exception as exc:  # pragma: no cover - defensive
                avail, reason = False, "availability check failed: %s" % exc
            if avail:
                available.append(backend)
            else:
                logger.debug("Backend %s unavailable: %s",
                             backend.BACKEND_ID, reason)
        return available

    @classmethod
    def select_backend(cls, path: str, preferred: str = "auto") -> type:
        """Select a backend class for *path* (auto = priority + can_open)."""
        available = cls.get_available_backends()

        if preferred and preferred != "auto":
            for backend in available:
                if backend.BACKEND_ID == preferred:
                    if backend.can_open(path):
                        return backend
                    raise ValueError(
                        "Preferred backend %s cannot open %s" % (preferred, path))
            raise ValueError(
                "Preferred backend %r is not available. Installed backends: %s"
                % (preferred, [b.BACKEND_ID for b in available]))

        for backend in available:
            try:
                if backend.can_open(path):
                    return backend
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("can_open failed for %s: %s",
                             backend.BACKEND_ID, exc)

        raise RuntimeError(
            "No available backend can open %r. Available: %s"
            % (path, [b.BACKEND_ID for b in available]))

    @classmethod
    def open(cls, path: str, preferred: str = "auto",
             config: Dict = None) -> ProductHandle:
        """Select a backend, open *path* and log why the backend was chosen.

        In ``auto`` mode backends are tried in registration (priority) order
        and the first one that opens the file **with a valid georeference**
        wins; otherwise the next backend is tried (AGENTS.md §4.1).
        """
        if preferred and preferred != "auto":
            backend_class = cls.select_backend(path, preferred)
            backend = backend_class(cls._sanitize(config))
            logger.info("Opening %s with reader backend %s (%s) [user choice]",
                        path, backend_class.BACKEND_ID, backend_class.BACKEND_NAME)
            return backend.open(path)

        tried = []
        for backend_class in cls.get_available_backends():
            try:
                if not backend_class.can_open(path):
                    continue
            except Exception as exc:
                logger.debug("can_open failed for %s: %s",
                             backend_class.BACKEND_ID, exc)
                continue
            backend = backend_class(cls._sanitize(config))
            try:
                handle = backend.open(path)
            except Exception as exc:
                tried.append("%s (open failed: %s)" % (backend_class.BACKEND_ID, exc))
                logger.debug("Backend %s failed to open %s: %s",
                             backend_class.BACKEND_ID, path, exc)
                continue
            if handle.georef is not None and handle.georef.is_valid:
                logger.info(
                    "Opening %s with reader backend %s (%s) "
                    "[auto: first backend with valid georeference]",
                    path, backend_class.BACKEND_ID, backend_class.BACKEND_NAME)
                return handle
            # Georef invalid — close and fall through to the next backend.
            tried.append("%s (no valid georeference)" % backend_class.BACKEND_ID)
            try:
                backend.close(handle)
            except Exception:  # pragma: no cover
                pass

        # No backend produced a valid georef: return the best "invalid" open
        # if any succeeded earlier, else raise.
        for backend_class in cls.get_available_backends():
            try:
                if backend_class.can_open(path):
                    backend = backend_class(cls._sanitize(config))
                    handle = backend.open(path)
                    logger.warning(
                        "Opening %s with backend %s: georeference is INVALID "
                        "(tried: %s)", path, backend_class.BACKEND_ID,
                        "; ".join(tried) or "n/a")
                    for warn in (handle.georef.warnings if handle.georef else []):
                        logger.warning("georef: %s", warn)
                    return handle
            except Exception as exc:
                logger.debug("Fallback open failed for %s: %s",
                             backend_class.BACKEND_ID, exc)

        raise RuntimeError(
            "No available backend can open %r (tried: %s). "
            "Tip: install GDAL >= 3.13 or the 'h5py' Python package."
            % (path, "; ".join(tried) or "none"))

    @classmethod
    def close(cls, handle: ProductHandle) -> None:
        """Close a handle using the backend that opened it."""
        backend_id = getattr(handle, "reader_backend", None)
        for backend in cls._backends:
            if backend.BACKEND_ID == backend_id:
                try:
                    backend(cls._sanitize(None)).close(handle)
                except Exception as exc:  # pragma: no cover
                    logger.debug("Close failed for %s: %s", backend_id, exc)
                return
        # Fallback: generic attribute cleanup.
        for attr in ("_h5_file", "_dataset", "_subds_cache"):
            if hasattr(handle, attr):
                setattr(handle, attr, None)

    @classmethod
    def list_registered(cls) -> List[Dict[str, str]]:
        """List all registered backends with their status."""
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

    @staticmethod
    def _sanitize(config) -> Dict[str, Any]:
        """Accept either a plain dict or a dataclass-like config object."""
        if config is None:
            return {}
        if isinstance(config, dict):
            return config
        if hasattr(config, "__dict__"):
            return {k: (str(v) if hasattr(v, "__fspath__") else v)
                    for k, v in vars(config).items()}
        return {}
