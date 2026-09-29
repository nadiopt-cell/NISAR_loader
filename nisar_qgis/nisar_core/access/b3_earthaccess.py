# -*- coding: utf-8 -*-
"""
B3: earthaccess backend — alternative to asf_search (NASA CMR).

CMR concept IDs: GCOV PROVISIONAL verified via live ASF metadata
(C2854338529-ASF, 2026-09-29); GSLC/RSLC ids are NOT verified — they must
be confirmed in CMR before relying on them (see docs/product_notes.md).

Authentication: ``~/.netrc`` via ``earthaccess``; no passwords stored (TZ P0.6).
"""
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

try:
    import earthaccess
    EARTHACCESS_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    earthaccess = None
    EARTHACCESS_AVAILABLE = False

from .base import BaseAccessBackend, AccessRegistry, DownloadProgress
from ..models import (
    SceneRecord, SearchParameters, DataStatus, ProductType, Instrument,
    ProductLevel, Polarization,
)

logger = logging.getLogger("nisar.access.b3")

# Concept IDs (see module docstring about verification status).
CONCEPT_ID_MAP = {
    ProductType.GCOV: "C2854338529-ASF",   # verified 2026-09-29
    ProductType.GSLC: None,                # NOT verified — do not guess
    ProductType.RSLC: None,                # NOT verified — do not guess
}


class B3EarthAccessBackend(BaseAccessBackend):
    """EarthAccess (CMR) backend for NISAR data."""

    BACKEND_ID = "B3_earthaccess"
    BACKEND_NAME = "EarthAccess (CMR)"
    DEPENDENCY_HINT = "pip install earthaccess"

    @classmethod
    def check_availability(cls) -> tuple:
        if not EARTHACCESS_AVAILABLE:
            return False, "earthaccess not installed (pip install earthaccess)"
        return True, ""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.auth = None
        self._authenticate()

    def _authenticate(self):
        """netrc-based auth only; no credentials are stored by the plugin."""
        if not EARTHACCESS_AVAILABLE:
            return
        try:
            self.auth = earthaccess.login(strategy="netrc")
        except Exception as exc:
            logger.info("EarthAccess netrc login unavailable: %s "
                        "(search still works without auth)", exc)
            self.auth = None

    # ---------------------------------------------------------------- search
    def search(self, params: SearchParameters) -> List[SceneRecord]:
        if not EARTHACCESS_AVAILABLE:
            raise RuntimeError("earthaccess is not available (%s)"
                               % self.DEPENDENCY_HINT)

        results: List[SceneRecord] = []
        for prod_type in params.product_types:
            concept_id = CONCEPT_ID_MAP.get(prod_type)
            if not concept_id:
                logger.warning("No verified CMR concept id for %s — "
                               "skipping (B2/asf_search covers it)", prod_type)
                continue

            try:
                query = earthaccess.DataGranules().concept_id(concept_id)
                if params.start_date or params.end_date:
                    start = params.start_date or params.end_date
                    end = params.end_date or params.start_date
                    query = query.temporal(start, end)
                if params.aoi_wkt:
                    query = query.bounding_box_from_wkt(params.aoi_wkt)
                query = query.page_size(max(1, min(params.max_results or 100, 100)))

                granules = query.get()
            except Exception as exc:
                logger.error("EarthAccess search failed for %s: %s",
                             concept_id, exc)
                continue

            for granule in granules:
                scene = self._granule_to_scene_record(granule, prod_type)
                if scene and self._matches_filters(scene, params):
                    results.append(scene)
        return results

    def _granule_to_scene_record(self, granule: Any,
                                 prod_type: ProductType) -> Optional[SceneRecord]:
        try:
            meta = granule.umm if hasattr(granule, "umm") else {}
            if isinstance(meta, str):  # pragma: no cover
                return None

            scene_id = "unknown"
            identifiers = meta.get("DataGranule", {}).get("Identifiers", [])
            for ident in identifiers:
                if ident.get("IdentifierType") == "ProducerGranuleId":
                    scene_id = str(ident.get("Identifier", "unknown"))
                    break
            if scene_id == "unknown":
                scene_id = str(meta.get("GranuleUR", "unknown"))

            acq_time = granule.time() if hasattr(granule, "time") else None
            from datetime import datetime
            if not acq_time:
                acq_time = datetime.now()

            # Data URLs via earthaccess.
            urls: Dict[str, str] = {}
            try:
                for link in earthaccess.search_results_to_datatree(
                        [granule]).get("data", []):
                    url = link.get("url", "")
                    if url.endswith(".h5"):
                        urls["download"] = url
                        if url.startswith("s3://"):
                            urls["s3"] = url
            except Exception:
                try:
                    for link in granule.dataviz_links() or []:
                        if str(link).endswith(".h5"):
                            urls["download"] = str(link)
                except Exception:
                    pass

            size = 0
            try:
                size = int(granule.size())
            except Exception:
                pass

            status = DataStatus.UNKNOWN
            collection = ""
            try:
                refs = meta.get("CollectionReference", {})
                entry = refs.get("EntryTitle", "")
                short = refs.get("ShortName", "")
                collection = entry or short
                blob = (entry + " " + short).upper()
                if "BETA" in blob:
                    status = DataStatus.BETA
                elif "PROVISIONAL" in blob:
                    status = DataStatus.PROVISIONAL
            except Exception:
                pass

            return SceneRecord(
                scene_id=scene_id,
                product_type=prod_type,
                level=ProductLevel.L2,
                instrument=Instrument.LSAR,
                status=status,
                acquisition_time=acq_time,
                footprint_wkt="",
                size_bytes=size,
                urls=urls,
                polarizations=[],
                mode="unknown",
                metadata={"collection": collection,
                          "concept_id": CONCEPT_ID_MAP.get(prod_type, "")},
            )
        except Exception as exc:
            logger.error("Error parsing earthaccess granule: %s", exc)
            return None

    def _matches_filters(self, scene: SceneRecord, params: SearchParameters) -> bool:
        if params.status_filter and scene.status not in params.status_filter \
                and scene.status is not DataStatus.UNKNOWN:
            return False
        return True

    # -------------------------------------------------------------- download
    def download(self, scene: SceneRecord, output_dir: Path,
                 progress_callback=None) -> Path:
        if not EARTHACCESS_AVAILABLE:
            raise RuntimeError("earthaccess is not available (%s)"
                               % self.DEPENDENCY_HINT)
        url = scene.urls.get("download") or scene.urls.get("s3")
        if not url:
            raise ValueError("No download URL available for %s"
                             % scene.scene_id)

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / (scene.scene_id.split("/")[-1] + ".h5")

        if progress_callback:
            progress_callback(DownloadProgress(
                scene_id=scene.scene_id, bytes_downloaded=0,
                total_bytes=scene.size_bytes, status="downloading"))

        try:
            earthaccess.download([url], str(output_dir))
            if progress_callback:
                progress_callback(DownloadProgress(
                    scene_id=scene.scene_id, bytes_downloaded=scene.size_bytes,
                    total_bytes=scene.size_bytes, status="completed",
                    file_path=str(output_path)))
            return output_path
        except Exception as exc:
            if progress_callback:
                progress_callback(DownloadProgress(
                    scene_id=scene.scene_id, bytes_downloaded=0,
                    total_bytes=scene.size_bytes, status="failed",
                    error_message=str(exc)))
            raise RuntimeError(
                "earthaccess download failed for %s: %s. Hint: check your "
                "~/.netrc Earthdata credentials."
                % (scene.scene_id, exc))

    def get_local_path(self, scene: SceneRecord) -> Optional[Path]:
        download_dir = Path(self.config.get(
            "download_dir", str(Path.home() / "Downloads" / "NISAR")))
        path = download_dir / (scene.scene_id + ".h5")
        return path if path.exists() else None


AccessRegistry.register(B3EarthAccessBackend)
