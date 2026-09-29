# -*- coding: utf-8 -*-
"""
P2.5 "Preview before download" — pure helpers (QGIS/Qt-free, testable).

Verified against the live ASF SearchAPI on 2026-09-29 (see
docs/product_notes.md): every NISAR GCOV granule carries official browse
images in the ``browse`` property:

    <granule>_LATLON.png            full quicklook, geographic projection
    <granule>_LATLON_thumbnail.png  small thumbnail (100x100 PNG, ~9 KB)
    <granule>_NATIVE.png            quicklook in the native product CRS
    <granule>_NATIVE_<A|B>_<POL>.png  per-frequency/polarization quicklook

The thumbnails are anonymously downloadable (no Earthdata login needed),
which makes them safe and cheap to fetch *before* the user commits to a
250 MB - 4.5 GB .h5 download.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from ..models import SceneRecord

# Suffix conventions of the ASF NISAR browse set (verified live).
_THUMB_TOKEN = "_thumbnail"
_FULL_TOKEN = "_latlon"
_NATIVE_TOKEN = "_native"
# e.g. "..._NATIVE_B_HVHV.png" -> band "B", polarization "HVHV".
_NATIVE_POL_RE = re.compile(r"_NATIVE_([AB])_([A-Z]{4})\.png$", re.IGNORECASE)


def human_size(n_bytes: Optional[int]) -> str:
    """Human-readable byte size (binary prefixes)."""
    if not n_bytes or n_bytes <= 0:
        return "—"
    if n_bytes >= 1024 ** 3:
        return "%.2f GB" % (n_bytes / 1024.0 ** 3)
    if n_bytes >= 1024 ** 2:
        return "%.1f MB" % (n_bytes / 1024.0 ** 2)
    return "%.1f KB" % (n_bytes / 1024.0)


def pick_browse_urls(browse_list: Optional[List[str]]) -> Dict[str, Any]:
    """Split the ASF ``browse`` property into preview-relevant URLs.

    Returns a dict:
        thumbnail  — smallest image (…_LATLON_thumbnail.png) or None
        full       — full-resolution quicklook (…_LATLON.png) or None
        native     — native-projection quicklook (…_NATIVE.png) or None
        native_pol — [{"band": "A", "pol": "HHHH", "label": "A HHHH",
                       "url": …}, …]
        all        — the filtered .png list as given
    """
    urls = [u for u in (browse_list or []) if str(u).lower().endswith(".png")]
    out: Dict[str, Any] = {
        "thumbnail": None,
        "full": None,
        "native": None,
        "native_pol": [],
        "all": urls,
    }
    for url in urls:
        low = url.lower()
        if _THUMB_TOKEN in low and out["thumbnail"] is None:
            out["thumbnail"] = url
        elif _FULL_TOKEN in low and out["full"] is None:
            out["full"] = url
        elif _NATIVE_POL_RE.search(low):
            match = _NATIVE_POL_RE.search(low)
            band = match.group(1).upper()
            pol = match.group(2).upper()
            out["native_pol"].append({
                "band": band, "pol": pol,
                "label": "%s %s" % (band, pol), "url": url,
            })
        elif _NATIVE_TOKEN in low and out["native"] is None:
            out["native"] = url
    return out


def bbox_from_wkt(wkt: Optional[str]) -> Optional[Tuple[float, float,
                                                         float, float]]:
    """Bounding box (minx, miny, maxx, maxy) of a POLYGON WKT, or None.

    Pure string parsing — no GDAL/QGIS needed. Accepts upper/lowercase
    keywords and extra whitespace.
    """
    if not wkt:
        return None
    text = wkt.strip().upper()
    if not text.startswith("POLYGON"):
        return None
    nums = re.findall(r"(-?\d+\.?\d*(?:[eE][-+]?\d+)?)\s+"
                      r"(-?\d+\.?\d*(?:[eE][-+]?\d+)?)", wkt)
    if not nums:
        return None
    xs = [float(x) for x, _ in nums]
    ys = [float(y) for _, y in nums]
    return (min(xs), min(ys), max(xs), max(ys))


def scene_summary_pairs(scene: SceneRecord) -> List[Tuple[str, str]]:
    """(i18n key, value) pairs for the preview details panel.

    The GUI maps the keys through ``tr()`` so the panel is translated;
    values are pre-formatted here so this function is unit-testable
    without Qt.
    """
    pairs: List[Tuple[str, str]] = [("ui.preview.detail_scene",
                                     scene.scene_id)]
    pairs.append(("ui.preview.detail_product",
                  "%s %s (%s)" % (scene.product_type.value,
                                  scene.level.value,
                                  scene.instrument.value)))
    acq = (scene.acquisition_time.strftime("%Y-%m-%d %H:%M:%S")
           if scene.acquisition_time else "—")
    pairs.append(("ui.preview.detail_acquired", acq))
    pairs.append(("ui.preview.detail_status", scene.status.value))
    pairs.append(("ui.preview.detail_size", human_size(scene.size_bytes)))
    # ASF repeats main-band pols in sideBandPolarization — dedupe,
    # preserve order (HH+HV+HH+HV -> HH+HV).
    seen: List[str] = []
    for pol in scene.polarizations:
        if pol.value not in seen:
            seen.append(pol.value)
    pairs.append(("ui.preview.detail_pols", "+".join(seen) or "—"))

    orbit = "—"
    if scene.orbit_number:
        orbit = "#%s" % scene.orbit_number
        if scene.orbit_direction:
            orbit += " %s" % scene.orbit_direction
    elif scene.orbit_direction:
        orbit = scene.orbit_direction
    pairs.append(("ui.preview.detail_orbit", orbit))

    frame = "—"
    path_number = scene.metadata.get("pathNumber")
    if scene.frame_id:
        frame = str(scene.frame_id)
        if path_number:
            frame += " / path %s" % path_number
    elif path_number:
        frame = "path %s" % path_number
    pairs.append(("ui.preview.detail_frame", frame))

    collection = scene.metadata.get("collectionName") or "—"
    crid = scene.metadata.get("crid")
    if crid:
        collection += " (CRID %s)" % crid
    pairs.append(("ui.preview.detail_collection", collection))

    bbox = bbox_from_wkt(scene.footprint_wkt)
    pairs.append(("ui.preview.detail_bbox",
                  "%.4f, %.4f, %.4f, %.4f" % bbox if bbox else "—"))
    return pairs
