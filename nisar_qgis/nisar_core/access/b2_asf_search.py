# -*- coding: utf-8 -*-
"""
B2: ASF Search backend using the ``asf_search`` Python package.

Search API usage verified against the live ASF SearchAPI (2026-09-29):
  * ``dataset='NISAR'`` + ``processingLevel='GCOV'`` (NOT 'NISAR_L2_GCOV');
  * polarizations from ``mainBandPolarization`` / ``sideBandPolarization``;
  * data status from ``collectionName`` (e.g. NISAR_L2_GCOV_PROVISIONAL_V1)
    and the product URL path — see docs/product_notes.md;
  * real CMR concept ids: GCOV PROVISIONAL = C2854338529-ASF,
    UR L2 = C2887502657-ASF.

Authentication: ``~/.netrc`` (Earthdata Login) — no passwords here (TZ P0.6).
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

try:
    import asf_search as asf
    ASF_SEARCH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    asf = None
    ASF_SEARCH_AVAILABLE = False

from .base import BaseAccessBackend, AccessRegistry, DownloadProgress
from .preview import pick_browse_urls
from ..models import (
    SceneRecord, SearchParameters, DataStatus, ProductType, Instrument,
    Polarization, ProductLevel,
)

logger = logging.getLogger("nisar.access.b2")

# ASF 'processingLevel' values per product type (verified via live search).
PROCESSING_LEVEL_MAP = {
    ProductType.GCOV: "GCOV",
    ProductType.GSLC: "GSLC",
    ProductType.RSLC: "RSLC",
    ProductType.GUNW: "GUNW",
}

# CMR concept IDs verified via live search metadata (2026-09-29/30).
CONCEPT_IDS = {
    ProductType.GCOV: "C2854338529-ASF",   # NISAR_L2_GCOV_PROVISIONAL_V1
    ProductType.GSLC: None,                # not verified yet
    ProductType.RSLC: None,                # not verified yet
    ProductType.GUNW: "C2854335566-ASF",   # NISAR_L2_GUNW_PROVISIONAL_V1
}

_POLARIZATION_CODES = {
    "HH": Polarization.HH, "HV": Polarization.HV,
    "VV": Polarization.VV, "VH": Polarization.VH,
}


def _status_from_collection(collection_name: str, url: str) -> DataStatus:
    """Derive BETA/PROVISIONAL from the ASF collection name / URL path.

    Verified: PROVISIONAL products live under
    ``.../NISAR/NISAR_L2_GCOV_PROVISIONAL_V1/...``; urgent-response
    products under ``.../NISAR-UR/UR_L2_L_GCOV/...``. BETA collections
    (February 2026 release) are named ``*_BETA*``.
    """
    blob = ("%s %s" % (collection_name or "", url or "")).upper()
    if "BETA" in blob:
        return DataStatus.BETA
    if "PROVISIONAL" in blob:
        return DataStatus.PROVISIONAL
    if "VALIDATED" in blob:
        return DataStatus.VALIDATED
    return DataStatus.UNKNOWN


class B2ASFSearchBackend(BaseAccessBackend):
    """ASF Search API backend for NISAR L-band data."""

    BACKEND_ID = "B2_asf_search"
    BACKEND_NAME = "ASF Search (asf_search)"
    DEPENDENCY_HINT = "pip install asf_search"

    @classmethod
    def check_availability(cls) -> tuple:
        if not ASF_SEARCH_AVAILABLE:
            return False, ("asf_search not installed (pip install "
                           "asf_search)")
        return True, ""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.session = None
        self._init_session()

    def _init_session(self):
        """ASF session: netrc-based; no passwords are ever stored."""
        if not ASF_SEARCH_AVAILABLE:
            return
        try:
            # asf_search picks up ~/.netrc / environment automatically.
            self.session = asf.ASFSession()
        except Exception as exc:
            logger.warning("ASF session init failed: %s", exc)
            self.session = None

    # ---------------------------------------------------------------- search
    def search(self, params: SearchParameters) -> List[SceneRecord]:
        """Search ASF for NISAR scenes (verified API usage)."""
        if not ASF_SEARCH_AVAILABLE:
            raise RuntimeError("asf_search is not available (%s)" % self.DEPENDENCY_HINT)

        results: List[SceneRecord] = []
        for prod_type in params.product_types:
            level = PROCESSING_LEVEL_MAP.get(prod_type)
            if not level:
                logger.warning("No ASF processing level for %s", prod_type)
                continue

            opts = {
                "dataset": "NISAR",
                "processingLevel": level,
                "maxResults": min(params.max_results or 100,
                                  self.config.get("asf_search_page_size", 100)),
            }
            if params.aoi_wkt:
                opts["intersectsWith"] = params.aoi_wkt
            if params.start_date:
                opts["start"] = params.start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            if params.end_date:
                opts["end"] = params.end_date.strftime("%Y-%m-%dT%H:%M:%SZ")

            try:
                logger.info("ASF search: %s", opts)
                # asf_search 14.x search() has no 'session' kwarg (verified
                # live: TypeError -> zero scenes, silently swallowed).
                # The session is attached to ASFSearchOptions instead.
                if self.session is not None:
                    opts_obj = asf.ASFSearchOptions(**opts)
                    opts_obj.session = self.session
                    search_results = asf.search(opts=opts_obj)
                else:
                    search_results = asf.search(**opts)
            except Exception as exc:
                logger.error("ASF search failed for %s: %s", level, exc)
                continue

            for item in search_results:
                scene = self._item_to_scene_record(item, prod_type)
                if scene and self._matches_filters(scene, params):
                    results.append(scene)

        return results

    def _item_to_scene_record(self, item: Any,
                              prod_type: ProductType) -> Optional[SceneRecord]:
        try:
            props = item.properties

            acq_time_str = props.get("startTime") or props.get("stopTime")
            try:
                acq_time = datetime.fromisoformat(
                    acq_time_str.replace("Z", "+00:00")) if acq_time_str \
                    else datetime.now()
            except ValueError:
                acq_time = datetime.now()

            # Footprint WKT (pure string handling, no GDAL dependency).
            footprint_wkt = ""
            try:
                geo = item.geojson()
                geometry = geo.get("geometry") if geo else None
                if geometry and geometry.get("type") == "Polygon":
                    rings = geometry.get("coordinates") or []
                    if rings:
                        pts = ", ".join("%.6f %.6f" % (x, y)
                                        for x, y in rings[0])
                        footprint_wkt = "POLYGON((%s))" % pts
            except Exception as exc:
                logger.debug("Footprint extraction failed: %s", exc)

            # Polarizations (verified fields).
            pols = []
            for key in ("mainBandPolarization", "sideBandPolarization"):
                for code in props.get(key) or []:
                    if code in _POLARIZATION_CODES:
                        pols.append(_POLARIZATION_CODES[code])

            # Size: prefer the .h5 file size from the bytes mapping.
            size_bytes = 0
            bytes_field = props.get("bytes") or {}
            if isinstance(bytes_field, dict):
                for fname, info in bytes_field.items():
                    if str(fname).lower().endswith(".h5"):
                        size_bytes = int(info.get("bytes", 0) or 0)
                        break
            if not size_bytes:
                try:
                    size_bytes = int(props.get("bytes", 0) or 0)
                except (TypeError, ValueError):
                    size_bytes = 0

            # URLs.
            urls = {}
            url = props.get("url")
            if url:
                urls["download"] = url

            # Official browse/quicklook set: dedicated ``browse`` property
            # (verified live 2026-09-29 — additionalUrls carries only
            # kml/pdf/qa sidecars, never the browse PNGs).
            browse = pick_browse_urls(props.get("browse"))
            if browse["thumbnail"]:
                urls["browse_thumbnail"] = browse["thumbnail"]
                urls["browse"] = browse["thumbnail"]
            if browse["full"]:
                urls["browse_full"] = browse["full"]
            if browse["native"]:
                urls["browse_native"] = browse["native"]
            if not urls.get("browse"):
                # Legacy fallback: a PNG quicklook inside additionalUrls.
                for extra in (props.get("additionalUrls") or []):
                    low = str(extra).lower()
                    if "browse" in low or low.endswith(".png"):
                        urls.setdefault("browse", extra)
                        break
            for extra in (props.get("additionalUrls") or []):
                if "s3://" in str(extra):
                    urls["s3"] = extra
            for s3 in (props.get("s3Urls") or []):
                urls.setdefault("s3", s3)

            status = _status_from_collection(
                props.get("collectionName", ""), url or "")

            scene = SceneRecord(
                scene_id=props.get("sceneName")
                          or props.get("fileID")
                          or "unknown",
                product_type=prod_type,
                level=self._parse_level(props.get("processingLevel", "")),
                instrument=Instrument.LSAR,
                status=status,
                acquisition_time=acq_time,
                footprint_wkt=footprint_wkt,
                size_bytes=size_bytes,
                urls=urls,
                polarizations=pols,
                mode=(props.get("rangeBandwidth")
                      and "+".join(props.get("rangeBandwidth"))) or "unknown",
                orbit_number=self._to_int(props.get("orbit")),
                orbit_direction=(props.get("flightDirection") or "").upper() or None,
                frame_id=self._to_int(props.get("frameNumber")),
                metadata={
                    "collectionName": props.get("collectionName", ""),
                    "conceptID": props.get("conceptID", ""),
                    "fileID": props.get("fileID", ""),
                    "crid": props.get("crid", ""),
                    "pgeVersion": props.get("pgeVersion", ""),
                    "pathNumber": props.get("pathNumber"),
                    "processingDate": props.get("processingDate", ""),
                    # Full browse set for the preview panel (P2.5).
                    "browse_urls": browse["all"],
                    "browse_native_pol": browse["native_pol"],
                },
            )
            return scene
        except Exception as exc:
            logger.error("Error parsing ASF item: %s", exc)
            return None

    @staticmethod
    def _to_int(value) -> Optional[int]:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_level(level_str: str) -> ProductLevel:
        text = (level_str or "").upper()
        if "L1" in text:
            return ProductLevel.L1
        if "L3" in text:
            return ProductLevel.L3
        return ProductLevel.L2  # GCOV default

    def _matches_filters(self, scene: SceneRecord, params: SearchParameters) -> bool:
        if params.polarizations:
            if not any(p in scene.polarizations for p in params.polarizations):
                return False
        # Status filter: UNKNOWN results pass through so the user can see
        # them (and the GUI can warn) rather than silently hiding scenes.
        if params.status_filter and scene.status not in params.status_filter \
                and scene.status is not DataStatus.UNKNOWN:
            return False
        return True

    # -------------------------------------------------------------- download
    def download(self, scene: SceneRecord, output_dir: Path,
                 progress_callback=None) -> Path:
        """Download via asf_search (netrc auth) with progress callbacks."""
        if not ASF_SEARCH_AVAILABLE:
            raise RuntimeError("asf_search is not available (%s)" % self.DEPENDENCY_HINT)

        url = scene.urls.get("download")
        if not url:
            raise ValueError("No download URL for scene %s" % scene.scene_id)

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = url.rstrip("/").split("/")[-1]
        output_path = output_dir / filename

        def report(status, downloaded=0, total=None, error="", path=""):
            if progress_callback:
                progress_callback(DownloadProgress(
                    scene_id=scene.scene_id,
                    bytes_downloaded=downloaded,
                    total_bytes=total if total is not None else scene.size_bytes,
                    status=status,
                    error_message=error,
                    file_path=path,
                ))

        try:
            report("downloading", 0)
            # asf_search's download_url streams via the session; auth is
            # whatever the session carries (netrc / token / cookies).
            asf.download_url(
                url=url, path=str(output_dir), session=self.session,
                filename=filename,
            )
            if not output_path.exists():
                # File name from URL may differ — accept any new .h5.
                candidates = sorted(output_dir.glob("*.h5"),
                                     key=lambda p: p.stat().st_mtime,
                                     reverse=True)
                if candidates:
                    output_path = candidates[0]
            report("completed", scene.size_bytes, scene.size_bytes,
                   path=str(output_path))
            return output_path
        except Exception as exc:
            report("failed", 0, scene.size_bytes, error=str(exc))
            # Hint about credentials only when the failure smells auth-ish;
            # a kwarg/typo error must not send the user chasing .netrc.
            blob = str(exc).lower()
            authy = any(w in blob for w in (
                "401", "403", "unauthorized", "forbidden", "login",
                "credentials", "netrc", "redirect"))
            hint = (" Hint: check your Earthdata credentials (~/.netrc "
                    "with machine urs.earthdata.nasa.gov, or a valid EDL "
                    "token)." if authy else "")
            raise RuntimeError(
                "Download failed for %s: %s.%s" % (scene.scene_id, exc, hint))

    def get_local_path(self, scene: SceneRecord) -> Optional[Path]:
        download_dir = Path(self.config.get(
            "download_dir", str(Path.home() / "Downloads" / "NISAR")))
        base = scene.scene_id
        for candidate in (base, base + ".h5", base.replace(".h5", "")):
            path = download_dir / candidate
            if path.suffix == ".h5" and path.exists():
                return path
        # Fallback: any file starting with the scene id.
        if download_dir.exists():
            for path in download_dir.glob(base + "*.h5"):
                return path
        return None


AccessRegistry.register(B2ASFSearchBackend)
