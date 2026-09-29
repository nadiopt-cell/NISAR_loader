# -*- coding: utf-8 -*-
"""
Access backends package.

B2/B3 need optional pip packages; whatever is missing is simply
unavailable via ``check_availability`` (with a pip hint), never an
ImportError at package import time.
"""
import logging

from .base import (
    BaseAccessBackend, AccessRegistry, LocalFileBackend, DownloadProgress,
)

logger = logging.getLogger("nisar.access")

try:
    from .b2_asf_search import B2ASFSearchBackend
except Exception as _exc:  # pragma: no cover
    B2ASFSearchBackend = None
    logger.debug("B2 (asf_search) not importable: %s", _exc)

try:
    from .b3_earthaccess import B3EarthAccessBackend
except Exception as _exc:  # pragma: no cover
    B3EarthAccessBackend = None
    logger.debug("B3 (earthaccess) not importable: %s", _exc)

__all__ = [
    'BaseAccessBackend', 'AccessRegistry', 'LocalFileBackend',
    'DownloadProgress', 'B2ASFSearchBackend', 'B3EarthAccessBackend',
]
