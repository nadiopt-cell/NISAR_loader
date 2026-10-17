# -*- coding: utf-8 -*-
"""
Processing backend registry.
"""
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List

from ..models import ProcessingResult

logger = logging.getLogger("nisar.processing")


class ProcessingBackendBase(ABC):
    """Abstract base for processing backends."""

    BACKEND_ID: str = "base"
    BACKEND_NAME: str = "Base Processing"

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config if isinstance(config, dict) else (config and vars(config)) or {}

    @classmethod
    @abstractmethod
    def check_availability(cls) -> tuple:
        """(available, reason_if_not) on the current system."""

    @abstractmethod
    def process(self, operation: str, inputs: Dict[str, Any],
                params: Dict[str, Any]) -> ProcessingResult:
        """Generic process method."""


class ProcessingRegistry:
    """Registry of processing backends."""

    _backends: List[type] = []

    @classmethod
    def register(cls, backend_class: type):
        if backend_class not in cls._backends:
            cls._backends.append(backend_class)

    @classmethod
    def get_available_backends(cls) -> List[type]:
        available = []
        for backend in cls._backends:
            try:
                avail, _ = backend.check_availability()
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
            raise ValueError("Processing backend %r is not available" % preferred)
        if available:
            return available[0]
        raise RuntimeError("No available processing backends")

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
