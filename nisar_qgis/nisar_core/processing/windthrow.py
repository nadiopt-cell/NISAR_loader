# -*- coding: utf-8 -*-
"""
P3: Windthrow (ветровал) detection with the DiD coherence scheme.

Methodology follows the validated approach of the sentinel1_windthrow
study (see docs/product_notes.md, "Windthrow DiD"):

  dcoh = gamma(control pair) - gamma(storm pair)

where both pairs are 12-day interferometric pairs of the SAME track /
frame / pass direction; the storm pair brackets the storm date, the
control pair covers an adjacent interval without the storm. Inside a
windthrow the storm-pair coherence drops while the control pair keeps
the background level, so dcoh is positive there. The control pair
subtracts both meteorological and phenological background decorrelation
(difference-in-differences).

Detector (per the validated configuration; two threshold modes):
  * ``absolute`` (default, matches the reference PLUGIN v1.2.1 code and
    its delivered detections): threshold = median(bg) + a_coh, with
    a_coh = 0.25 in coherence units (~8-14% false-alarm rate on the
    validated C-band events);
  * ``mad`` (literal wording of the reference ARTICLE §2.3): threshold =
    median(bg) + k * MAD(bg), k = 0.25 (MAD = mean absolute deviation
    from the median) — a low, wide alert-layer threshold;
  * 3x3 median (majority) filtering of the binary detection;
  * minimum object size 6 pixels (~4 ha at 80 m posting).

Background sample must be "forest on the event date" — comparison
forest-to-forest. Forest reconstruction for an event year Y uses Hansen
GFC: treecover2000 >= 30% AND no loss in 2001..Y-1 (candidate forest);
the background additionally excludes pixels lost in year Y.

Metrics (reference polygons vs background): AUC (rank-based, ties
averaged), excess = median(dcoh_ref) - median(dcoh_bg), and
TPR@FPR5% = share of reference pixels above the 95th percentile of the
background sample.

Everything below the export layer is pure NumPy (scipy optional), so it
is fully covered by unit tests on synthetic GUNW pairs.
"""
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable, Any

import numpy as np

from ..models import ProductHandle, ProcessingResult
from ..readers import ReaderRegistry

logger = logging.getLogger("nisar.processing.windthrow")

# ---------------------------------------------------------------------------
# Validated defaults (sentinel1_windthrow study; cross-checked against the
# reference plugin v1.2.1 sources — see docs/product_notes.md, "P3.1 audit")
# ---------------------------------------------------------------------------
DEFAULT_THRESHOLD_MODE = "absolute"  # reference plugin code behaviour
DEFAULT_A_COH = 0.25                  # absolute offset, coherence units
DEFAULT_K_MAD = 0.25                 # MAD multiplier (article wording)
DEFAULT_MIN_PIXELS = 6          # ~4 ha at 80 m posting
DEFAULT_MEDIAN_SIZE = 3
DEFAULT_RING_RADIUS_M = 10000.0  # background ring around the event
DEFAULT_FOREST_FRACTION = 0.5    # forest share to call an 80 m cell forest
DEFAULT_OUTSIDE_FOREST_THRESHOLD = 0.3  # ref-polygon forest share flag
DEFAULT_PRE_COH_FLAG = 0.6       # bare-ground signature guard (ID654 rule)

_GUNW_DT = re.compile(r"\d{8}T\d{6}")


@dataclass
class WindthrowParams:
    """Detector parameters (validated defaults of the source study).

    ``threshold_mode`` selects the adaptive-threshold rule:
      * ``"absolute"`` (default) — median(bg) + ``a_coh``; matches the
        reference plugin v1.2.1 implementation and its delivered
        detections (FPR ~8-14% on the validated events);
      * ``"mad"`` — median(bg) + ``k_mad`` * MAD(bg); the literal
        article wording, a wide low-threshold alert layer.
    """
    threshold_mode: str = DEFAULT_THRESHOLD_MODE
    a_coh: float = DEFAULT_A_COH
    k_mad: float = DEFAULT_K_MAD
    min_pixels: int = DEFAULT_MIN_PIXELS
    median_size: int = DEFAULT_MEDIAN_SIZE
    ring_radius_m: float = DEFAULT_RING_RADIUS_M
    forest_fraction: float = DEFAULT_FOREST_FRACTION
    outside_forest_threshold: float = DEFAULT_OUTSIDE_FOREST_THRESHOLD
    pre_coh_flag: float = DEFAULT_PRE_COH_FLAG

    def __post_init__(self):
        if self.threshold_mode not in ("absolute", "mad"):
            raise ValueError(
                "threshold_mode must be 'absolute' or 'mad', got %r"
                % (self.threshold_mode,))


# ---------------------------------------------------------------------------
# GUNW granule-name parsing (pair identity)
# ---------------------------------------------------------------------------
@dataclass
class GunwPairInfo:
    """Identity of an interferometric pair parsed from the granule name."""
    granule: str = ""
    cycle: Optional[int] = None
    track: Optional[int] = None
    direction: Optional[str] = None      # "A" / "D"
    frame: Optional[int] = None
    pol_code: Optional[str] = None       # SH / SV / DH / DV ...
    ref_start: Optional[datetime] = None
    ref_end: Optional[datetime] = None
    sec_start: Optional[datetime] = None
    sec_end: Optional[datetime] = None


def parse_gunw_pair_info(name_or_path: str) -> GunwPairInfo:
    """Parse track/frame/direction/pair dates from a GUNW granule name.

    Example:
      NISAR_L2_PR_GUNW_023_064_D_059_024_2000_SH_20260618T152753_
      20260618T152829_20260630T152752_20260630T152828_P05023_N_F_J_001
    """
    granule = str(name_or_path).rstrip("/").split("/")[-1]
    info = GunwPairInfo(granule=granule)
    parts = granule.split("_")
    if len(parts) < 10 or "GUNW" not in parts:
        return info
    try:
        gunw_idx = parts.index("GUNW")
        info.cycle = _to_int(parts[gunw_idx + 1])
        info.track = _to_int(parts[gunw_idx + 2])
        info.direction = parts[gunw_idx + 3]
        info.frame = _to_int(parts[gunw_idx + 4])
    except (IndexError, ValueError):
        pass
    # polarization code: the two-letter token right before the timestamps
    stamps = _GUNW_DT.findall(granule)
    if stamps:
        m = re.search(r"_(\d{3,4})_([A-Z]{2})_" + stamps[0], granule)
        if m:
            info.pol_code = m.group(2)
        try:
            info.ref_start = datetime.strptime(stamps[0], "%Y%m%dT%H%M%S")
            info.ref_end = datetime.strptime(stamps[1], "%Y%m%dT%H%M%S")
            info.sec_start = datetime.strptime(stamps[2], "%Y%m%dT%H%M%S")
            info.sec_end = datetime.strptime(stamps[3], "%Y%m%dT%H%M%S")
        except (IndexError, ValueError):
            pass
    return info


def _to_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Pair compatibility (the DiD contract: same geometry, adjacent intervals)
# ---------------------------------------------------------------------------
@dataclass
class PairCompatibility:
    compatible: bool = True
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def check_pair_compatibility(storm: ProductHandle, control: ProductHandle,
                             event_date: Optional[datetime] = None
                             ) -> PairCompatibility:
    """Verify that two GUNW handles can be subtracted pixel-wise.

    Hard requirements (issues -> incompatible):
      * same track, frame, orbit pass direction, look direction;
      * both carry an 80 m coherenceMagnitude layer with a common pol;
      * identical grid shape, (near-)identical transform and same CRS.
    Soft requirements (warnings only):
      * temporal intervals of the two pairs must not overlap (sharing the
        endpoint scene is normal for pre-pre / post-post control);
      * if event_date given: the storm pair brackets it, the control pair
        does not.
    """
    result = PairCompatibility()

    def ident(handle):
        return (handle.metadata.get("identification") or {}) \
            if handle.metadata else {}

    def pair_of(handle):
        return (handle.metadata.get("pair_info") or {}) \
            if handle.metadata else {}

    for handle in (storm, control):
        if handle.product_type is None or handle.product_type.value != "GUNW":
            result.issues.append(
                "%s is not a GUNW product" % Path(handle.source_path).name)
            result.compatible = False
            return result

    si, ci = ident(storm), ident(control)
    for field_name, label in (("trackNumber", "track"),
                              ("frameNumber", "frame"),
                              ("orbitPassDirection", "orbit pass direction"),
                              ("lookDirection", "look direction")):
        a, b = si.get(field_name), ci.get(field_name)
        if a is not None and b is not None and str(a) != str(b):
            result.issues.append(
                "%s mismatch: storm=%s control=%s" % (label, a, b))

    # 80 m coherence layers with a common polarization
    storm_layer = find_coherence_layer(storm)
    control_layer = find_coherence_layer(control)
    if storm_layer is None or control_layer is None:
        result.issues.append(
            "both products need an 80 m coherenceMagnitude layer "
            "(HH or VV)")
        result.compatible = False
        return result
    if storm_layer.metadata.get("pol") != control_layer.metadata.get("pol"):
        result.issues.append(
            "polarization mismatch: %s vs %s"
            % (storm_layer.metadata.get("pol"),
               control_layer.metadata.get("pol")))

    # grid identity
    sg, cg = storm.georef, control.georef
    if sg is None or cg is None or not sg.is_valid or not cg.is_valid:
        result.issues.append("one of the products has no valid georeference")
        result.compatible = False
        return result
    if (sg.width, sg.height) != (cg.width, cg.height):
        result.issues.append(
            "grid shape mismatch: %dx%d vs %dx%d"
            % (sg.width, sg.height, cg.width, cg.height))
    if (sg.crs_authid or sg.crs_wkt) != (cg.crs_authid or cg.crs_wkt):
        result.issues.append("CRS mismatch: %s vs %s"
                             % (sg.crs_authid, cg.crs_authid))
    if sg.width == cg.width and sg.height == cg.height:
        dx = abs(sg.transform[0] - cg.transform[0])
        dy = abs(sg.transform[3] - cg.transform[3])
        px = abs(sg.transform[1])
        if dx > 0.5 * px or dy > 0.5 * px:
            result.issues.append(
                "grid origin shifted by (%.1f, %.1f) m — re-registration "
                "is out of scope; use the same track/frame" % (dx, dy))

    # temporal layout: pair dates from identification (primary) with the
    # granule name as fallback — users may rename files.
    sp = _pair_dates(storm)
    if not sp:
        info = parse_gunw_pair_info(storm.source_path)
        sp = {"ref": info.ref_start, "sec": info.sec_start}
    cp = _pair_dates(control)
    if not cp:
        info = parse_gunw_pair_info(control.source_path)
        cp = {"ref": info.ref_start, "sec": info.sec_start}
    if sp.get("ref") and cp.get("ref") and sp.get("sec") \
            and cp.get("sec"):
        latest_start = max(sp["ref"], cp["ref"])
        earliest_end = min(sp["sec"], cp["sec"])
        overlap_days = (earliest_end - latest_start).total_seconds() / 86400.0
        if overlap_days > 1.0:
            result.warnings.append(
                "pair intervals overlap by %.1f days — control pair must "
                "cover an interval WITHOUT the storm" % overlap_days)
        if event_date is not None:
            if not (sp["ref"] <= event_date <= sp["sec"]):
                result.warnings.append(
                    "event date %s is not bracketed by the storm pair "
                    "(%s .. %s)"
                    % (event_date.date(), sp["ref"].date(),
                       sp["sec"].date()))
            if cp["ref"] <= event_date <= cp["sec"]:
                result.warnings.append(
                    "event date %s falls INSIDE the control pair interval "
                    "— the control pair would contain the storm signal"
                    % event_date.date())

    result.compatible = not result.issues
    return result


def _pair_dates(handle: ProductHandle) -> Dict[str, Any]:
    """(ref, sec) zero-Doppler start times from identification, or {}"""
    ident = (handle.metadata or {}).get("identification") or {}

    def _dt(key):
        raw = str(ident.get(key, ""))
        try:
            return datetime.fromisoformat(raw.split(".")[0])
        except ValueError:
            return None

    ref = _dt("referenceZeroDopplerStartTime")
    sec = _dt("secondaryZeroDopplerStartTime")
    if ref and sec:
        return {"ref": ref, "sec": sec}
    return {}


def find_coherence_layer(handle: ProductHandle, posting: int = 80):
    """First 80 m coherenceMagnitude layer of a GUNW handle (HH preferred)."""
    candidates = [l for l in handle.layers
                  if l.metadata.get("dataset") == "coherenceMagnitude"
                  and l.metadata.get("posting_m") == posting]
    if not candidates:
        return None
    candidates.sort(key=lambda l: (l.metadata.get("pol") != "HH",
                                   l.name))
    return candidates[0]


# ---------------------------------------------------------------------------
# dcoh computation
# ---------------------------------------------------------------------------
@dataclass
class DcohResult:
    dcoh: np.ndarray            # float32, NaN outside valid area
    gamma_storm: np.ndarray     # float32 (NaN invalid)
    gamma_control: np.ndarray   # float32 (NaN invalid)
    valid: np.ndarray           # bool
    layer_name: str
    pol: str
    georef: object              # GeorefInfo of the 80 m grid


def compute_dcoh(storm: ProductHandle, control: ProductHandle,
                 config: Dict = None) -> DcohResult:
    """dcoh = gamma(control) - gamma(storm) on the common 80 m grid."""
    storm_layer = find_coherence_layer(storm)
    control_layer = find_coherence_layer(control)
    if storm_layer is None or control_layer is None:
        raise ValueError("80 m coherenceMagnitude layer missing "
                         "(storm=%s, control=%s)"
                         % (storm_layer is not None,
                            control_layer is not None))

    from .indices import NumpyProcessingBackend  # lazy: keeps import graph flat
    backend = NumpyProcessingBackend(dict(config or {}))
    reader_s = backend._get_reader(storm)
    reader_c = backend._get_reader(control)

    def _read_full(handle, layer, reader):
        """Single-shot full-layer read (80 m GUNW grid is ~80 MB).

        Tiled reading (~324 windowed h5py reads per layer) costs minutes
        on chunked GUNW datasets; one contiguous window is seconds.
        """
        height, width = layer.shape[0], layer.shape[1]
        tile = reader.read_window(handle, layer.name,
                                  (0, 0, width, height))
        if tile.ndim == 3:
            tile = tile[0]
        return tile

    gamma_s = np.asarray(_read_full(storm, storm_layer, reader_s),
                         dtype=np.float32)
    gamma_c = np.asarray(_read_full(control, control_layer, reader_c),
                         dtype=np.float32)

    valid = np.isfinite(gamma_s) & np.isfinite(gamma_c)
    dcoh = gamma_c - gamma_s
    dcoh[~valid] = np.nan

    return DcohResult(
        dcoh=dcoh.astype(np.float32),
        gamma_storm=gamma_s,
        gamma_control=gamma_c,
        valid=valid,
        layer_name=storm_layer.name,
        pol=storm_layer.metadata.get("pol") or "?",
        georef=storm.georef,
    )


# ---------------------------------------------------------------------------
# Forest mask (Hansen GFC reconstruction) — pure NumPy part
# ---------------------------------------------------------------------------
def hansen_forest_mask_year(treecover2000: np.ndarray, lossyear: np.ndarray,
                            year: int,
                            exclude_loss_year: bool = False) -> np.ndarray:
    """Forest-on-event-year mask from Hansen GFC layers.

    Rule (validated in the source study):
      candidate forest @ Y  = treecover2000 >= 30% AND no loss in 2001..Y-1
                              (lossyear == 0 or lossyear >= Y - 2000 + 1)
    With ``exclude_loss_year`` (background variant) pixels lost in year Y
    are additionally excluded — a pixel lost in the storm year may have
    been cut before the event and the background must stay clean forest.

    ``lossyear`` uses 0 = no loss, else (year - 2000).
    """
    tc = np.asarray(treecover2000)
    ly = np.asarray(lossyear)
    if tc.shape != ly.shape:
        raise ValueError("treecover2000 %s and lossyear %s shapes differ"
                         % (tc.shape, ly.shape))
    loss_offset = year - 2000          # lossyear value of year Y
    no_loss_before = (ly == 0) | (ly > loss_offset - 1)  # no loss in ..Y-1
    forest = (tc >= 30) & no_loss_before
    if exclude_loss_year:
        forest &= ~(ly == loss_offset)
    return forest


def resample_fraction(src: np.ndarray, src_xs: np.ndarray,
                      src_ys: np.ndarray, dst_xs: np.ndarray,
                      dst_ys: np.ndarray) -> np.ndarray:
    """Fraction of source pixels (center-in-box) inside each dst pixel.

    Both grids are regular and in the SAME CRS; ``*_xs``/``*_ys`` are
    pixel-center coordinates (ascending x, descending or ascending y).
    Returns an array of shape (len(dst_ys), len(dst_xs)) with values in
    [0, 1] (NaN where no source pixel falls into the box). Fully
    vectorized via 2D prefix sums — no Python loops over pixels.
    """
    src = np.asarray(src, dtype=np.float32)
    sx = np.asarray(src_xs, dtype=np.float64)
    sy = np.asarray(src_ys, dtype=np.float64)
    dx = np.asarray(dst_xs, dtype=np.float64)
    dy = np.asarray(dst_ys, dtype=np.float64)
    if sx.size < 2 or sy.size < 2 or dx.size < 2 or dy.size < 2:
        raise ValueError("degenerate coordinate arrays")

    ddx = abs(dx[1] - dx[0])
    ddy = abs(dy[0] - dy[-1]) / max(dy.size - 1, 1)

    # orient source ascending on both axes (prefix sums assume
    # row 0 = smallest y, col 0 = smallest x)
    if np.all(np.diff(sy) < 0):          # y descending (north-up raster)
        src_asc = src[::-1, :]
    else:
        src_asc = src
    if not np.all(np.diff(sx) > 0):
        src_asc = src_asc[:, ::-1]
    sx_sorted = np.sort(sx)
    sy_sorted = np.sort(sy)
    dy_sorted = np.sort(dy)

    # 2D prefix sums (zero row/col pad for O(1) box sums)
    prefix = np.zeros((src_asc.shape[0] + 1, src_asc.shape[1] + 1),
                      dtype=np.float64)
    prefix[1:, 1:] = np.cumsum(np.cumsum(src_asc, axis=0), axis=1)

    def _ranges(centers: np.ndarray, dst_spacing: float,
                dst: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Half-open [i0, i1) source index range per destination pixel.

        The edges are built from the DESTINATION pixel size — a common
        bug is to pass the source spacing here, which shrinks the
        sampling boxes (verified live on the 30 m -> 80 m case).
        """
        edges = np.concatenate(([dst[0] - dst_spacing / 2.0],
                                (dst[:-1] + dst[1:]) / 2.0,
                                [dst[-1] + dst_spacing / 2.0]))
        lo = np.searchsorted(centers, edges[:-1], side="left")
        hi = np.searchsorted(centers, edges[1:], side="left")
        return lo, hi

    # destination pixel edges use the DESTINATION spacing (ddx, ddy)
    col_lo, col_hi = _ranges(sx_sorted, ddx, dx)
    row_lo, row_hi = _ranges(sy_sorted, ddy, dy_sorted)

    # per-source-row band sums for each destination row (vectorized)
    row_hi = np.asarray(row_hi, dtype=np.intp)
    row_lo = np.asarray(row_lo, dtype=np.intp)
    col_hi = np.asarray(col_hi, dtype=np.intp)
    col_lo = np.asarray(col_lo, dtype=np.intp)
    rdiff = prefix[row_hi, :] - prefix[row_lo, :]        # (R_dst, W_src+1)
    box = rdiff[:, col_hi] - rdiff[:, col_lo]            # (R_dst, C_dst)

    row_counts = (row_hi - row_lo).astype(np.float64)
    col_counts = (col_hi - col_lo).astype(np.float64)
    counts = np.outer(row_counts, col_counts)
    with np.errstate(divide="ignore", invalid="ignore"):
        frac_sorted_rows = box / counts
    frac_sorted_rows[counts == 0] = np.nan

    # restore destination row order (dst y may be descending = north-up)
    if dy[0] > dy[-1]:
        return frac_sorted_rows[::-1, :].astype(np.float32)
    return frac_sorted_rows.astype(np.float32)


# ---------------------------------------------------------------------------
# Background ring
# ---------------------------------------------------------------------------
def ring_background_mask(ref_mask: np.ndarray,
                         radius_px: float) -> np.ndarray:
    """Ring of ``radius_px`` around the reference mask (excludes ref).

    With scipy: exact Euclidean ring. Without scipy: a square
    (box-dilation) approximant via integral images — fast but with
    square corners instead of round.
    """
    ref = np.asarray(ref_mask, dtype=bool)
    try:
        from scipy import ndimage
        dist = ndimage.distance_transform_edt(~ref)
        return (dist > 0) & (dist <= radius_px)
    except ImportError:
        k = int(max(1, radius_px))
        acc = _box_dilate_count(ref, k)
        return (acc > 0) & ~ref


def _box_dilate_count(mask: np.ndarray, k: int) -> np.ndarray:
    """Count of True pixels in the (2k+1)-box around each pixel."""
    m = np.asarray(mask, dtype=np.int32)
    h, w = m.shape
    pad = np.zeros((h + 2 * k, w + 2 * k), dtype=np.int64)
    pad[k:k + h, k:k + w] = m
    c = np.cumsum(np.cumsum(pad, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    s = (2 * k + 1)
    return (c[s:s + h, s:s + w] - c[0:h, s:s + w]
            - c[s:s + h, 0:w] + c[0:h, 0:w]).astype(np.int32)


# ---------------------------------------------------------------------------
# Detector + metrics
# ---------------------------------------------------------------------------
@dataclass
class DetectionResult:
    threshold: float
    median_bg: float
    mad_bg: float
    mask: np.ndarray           # bool, True = windthrow candidate
    n_detected: int
    area_ha: float
    n_objects: int
    object_sizes: List[int]


def _label_components(mask: np.ndarray) -> Tuple[np.ndarray, int]:
    """Connected component labeling (8-connectivity), scipy optional."""
    try:
        from scipy import ndimage
        labels, n = ndimage.label(mask, structure=np.ones((3, 3), int))
        return labels, int(n)
    except ImportError:
        labels = np.zeros(mask.shape, dtype=np.int32)
        current = 0
        from collections import deque
        ys, xs = np.nonzero(mask)
        seen = np.zeros(mask.shape, dtype=bool)
        for y0, x0 in zip(ys.tolist(), xs.tolist()):
            if seen[y0, x0]:
                continue
            current += 1
            queue = deque([(y0, x0)])
            seen[y0, x0] = True
            labels[y0, x0] = current
            while queue:
                y, x = queue.popleft()
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if (0 <= ny < mask.shape[0]
                                and 0 <= nx < mask.shape[1]
                                and mask[ny, nx] and not seen[ny, nx]):
                            seen[ny, nx] = True
                            labels[ny, nx] = current
                            queue.append((ny, nx))
        return labels, current


def _median_binary(mask: np.ndarray, size: int = 3) -> np.ndarray:
    """Median filter of a binary mask (majority vote), edge-safe."""
    if size != 3:  # only 3x3 supported without scipy
        from scipy import ndimage  # noqa: F401  (raises ImportError if absent)
        return ndimage.median_filter(mask.astype(np.uint8), size=size) > 0
    m = mask.astype(np.uint8)
    p = np.pad(m, 1, mode="constant")
    acc = p[1:-1, 1:-1].astype(np.uint8)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            if dy == 1 and dx == 1:
                continue
            acc += p[dy:dy + m.shape[0], dx:dx + m.shape[1]]
    return acc >= 5  # majority of 9


def detect_windthrow(dcoh: np.ndarray, background: np.ndarray,
                     valid: np.ndarray,
                     params: WindthrowParams = None) -> DetectionResult:
    """Adaptive-threshold detection of the DiD raster.

    threshold mode ``absolute``: median(bg) + a_coh (reference plugin
    v1.2.1); mode ``mad``: median(bg) + k_mad * MAD(bg) (article text).
    The binary result is filtered with a 3x3 median and objects smaller
    than ``min_pixels`` removed.
    """
    params = params or WindthrowParams()
    bg_vals = dcoh[background & valid & np.isfinite(dcoh)]
    bg_vals = bg_vals[np.isfinite(bg_vals)]
    if bg_vals.size < 30:
        raise ValueError(
            "background sample too small (%d valid pixels) — the adaptive "
            "threshold is not defined" % bg_vals.size)

    median_bg = float(np.median(bg_vals))
    mad_bg = float(np.mean(np.abs(bg_vals - median_bg)))
    if params.threshold_mode == "mad":
        threshold = median_bg + params.k_mad * mad_bg
    else:  # "absolute" — reference plugin v1.2.1 behaviour
        threshold = median_bg + params.a_coh

    candidate = np.zeros(dcoh.shape, dtype=bool)
    candidate[valid & np.isfinite(dcoh)] = \
        dcoh[valid & np.isfinite(dcoh)] > threshold

    # 3x3 median (majority) filter — removes isolated responses
    candidate = _median_binary(candidate, params.median_size)

    # minimum object size
    labels, n = _label_components(candidate)
    sizes = np.bincount(labels.ravel())[1:] if n else np.array([], int)
    keep = np.zeros(n + 1, dtype=bool)
    keep[1:] = sizes >= params.min_pixels
    mask = keep[labels]

    kept = mask.sum()
    # pixel area: derive from the grid only if known; caller fills area_ha
    return DetectionResult(
        threshold=threshold,
        median_bg=median_bg,
        mad_bg=mad_bg,
        mask=mask,
        n_detected=int(kept),
        area_ha=0.0,
        n_objects=int(keep[1:].sum()),
        object_sizes=[int(s) for s in sizes[keep[1:]]] if n else [],
    )


def windthrow_metrics(dcoh: np.ndarray, ref_mask: np.ndarray,
                      bg_mask: np.ndarray) -> Dict[str, Any]:
    """AUC / excess / TPR@FPR5% of the dcoh raster (ref vs background)."""
    ref = dcoh[ref_mask & np.isfinite(dcoh)]
    bg = dcoh[bg_mask & np.isfinite(dcoh)]
    out: Dict[str, Any] = {"n_ref": int(ref.size), "n_bg": int(bg.size)}
    if ref.size == 0 or bg.size == 0:
        out["auc"] = None
        out["excess"] = None
        out["tpr_fpr05"] = None
        return out

    out["excess"] = float(np.median(ref) - np.median(bg))

    # AUC via Mann-Whitney U with averaged tie ranks
    allv = np.concatenate([ref, bg]).astype(np.float64)
    order = np.argsort(allv, kind="mergesort")
    sortedv = allv[order]
    uniq, inv = np.unique(sortedv, return_inverse=True)
    counts = np.bincount(inv)
    first_rank = np.cumsum(counts) - counts + 1
    avg_rank = first_rank + (counts - 1) / 2.0
    ranks = np.empty(allv.size, dtype=np.float64)
    ranks[order] = avg_rank[inv]
    n_r, n_b = ref.size, bg.size
    u1 = ranks[:n_r].sum() - n_r * (n_r + 1) / 2.0
    out["auc"] = float(u1 / (n_r * n_b))

    t = float(np.quantile(bg, 0.95))
    out["tpr_fpr05"] = float(np.mean(ref >= t))
    return out


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------
def format_metric(value, pattern: str = "%.3f") -> str:
    """Metric text for the report lines: None renders as 'n/a' (WP-5)."""
    if value is None:
        return "n/a"
    try:
        return pattern % value
    except (TypeError, ValueError):
        return str(value)


def run_windthrow_did(storm_path: str, control_path: str,
                      output_dir=None,
                      config: Dict = None,
                      params: WindthrowParams = None,
                      ref_mask: np.ndarray = None,
                      forest_mask: np.ndarray = None,
                      other_damage_mask: np.ndarray = None,
                      event_date: Optional[datetime] = None,
                      progress_callback: Callable = None,
                      is_canceled: Callable = None,
                      export_dcoh: bool = True,
                      export_mask: bool = True,
                      polygonize: bool = False,
                      ) -> ProcessingResult:
    """End-to-end DiD windthrow detection from two GUNW granules.

    Returns a ProcessingResult; ``metadata`` carries the full report
    (also written to ``<output_dir>/windthrow_report.json`` when an
    output directory is given).
    """
    params = params or WindthrowParams()
    warnings: List[str] = []

    def progress(p):
        if progress_callback is not None:
            try:
                progress_callback(int(p))
            except Exception:  # pragma: no cover
                pass

    def canceled():
        return bool(is_canceled is not None and is_canceled())

    # 1. open + compatibility ------------------------------------------------
    progress(2)
    storm = ReaderRegistry.open(storm_path, config=config)
    try:
        control = ReaderRegistry.open(control_path, config=config)
    except Exception:
        ReaderRegistry.close(storm)
        raise
    try:
        compat = check_pair_compatibility(storm, control, event_date)
        warnings.extend(compat.warnings)
        if not compat.compatible:
            return ProcessingResult(
                success=False,
                error_message="Pairs are not compatible: %s"
                              % "; ".join(compat.issues),
                warnings=warnings)

        # 2. dcoh ------------------------------------------------------------
        progress(15)
        dcoh_result = compute_dcoh(storm, control, config)
        dcoh, valid = dcoh_result.dcoh, dcoh_result.valid
        georef = dcoh_result.georef

        height, width = dcoh.shape
        pixel_area_m2 = abs(georef.transform[1]) * abs(georef.transform[5])
        pixel_area_ha = pixel_area_m2 / 1e4

        # 3. masks -----------------------------------------------------------
        progress(40)
        if ref_mask is not None and ref_mask.shape != dcoh.shape:
            return ProcessingResult(
                success=False, error_message=(
                    "reference mask shape %s does not match the grid %s"
                    % (ref_mask.shape, dcoh.shape)))
        ref = np.asarray(ref_mask, dtype=bool) if ref_mask is not None \
            else None
        ref_overlap = int((ref & valid).sum()) if ref is not None else None
        if forest_mask is not None and forest_mask.shape != dcoh.shape:
            return ProcessingResult(
                success=False, error_message=(
                    "forest mask shape %s does not match the grid %s"
                    % (forest_mask.shape, dcoh.shape)))
        forest = np.asarray(forest_mask, dtype=bool) \
            if forest_mask is not None else None
        other = np.asarray(other_damage_mask, dtype=bool) \
            if other_damage_mask is not None else None

        if forest is not None:
            candidate_area = valid & forest
        else:
            candidate_area = valid.copy()
            warnings.append(
                "no forest mask supplied — detection is not restricted "
                "to forest; background may include non-forest pixels")

        if ref is not None and ref_overlap == 0:
            warnings.append(
                "reference polygons do not intersect the valid processing "
                "grid (reference.overlap = 0) - metrics are skipped and "
                "background covers the whole scene instead")
        if ref is not None and ref_overlap > 0:
            spacing_m = abs(georef.transform[1])
            radius_px = (params.ring_radius_m / spacing_m
                         if spacing_m else 125.0)
            background = ring_background_mask(ref, radius_px) & valid
        else:
            background = valid.copy()
            if ref is None:
                warnings.append(
                    "no reference polygons supplied - background covers "
                    "the whole valid scene (threshold is less local)")
        if forest is not None:
            background &= forest
        if other is not None:
            background &= ~other

        # 4. detection ---------------------------------------------------------
        progress(55)
        try:
            detection = detect_windthrow(dcoh, background,
                                         candidate_area, params)
        except ValueError as exc:
            return ProcessingResult(success=False, error_message=str(exc),
                                    warnings=warnings)
        detection.area_ha = detection.n_detected * pixel_area_ha

        # 5. guards + metrics --------------------------------------------------
        progress(70)
        flags: List[str] = []
        metrics: Dict[str, Any] = {}
        forest_fraction = None
        if ref_overlap:
            ref_valid = ref & valid
            if forest is not None:
                forest_fraction = float(
                    (ref_valid & forest).sum() / max(ref_valid.sum(), 1))
                if forest_fraction < params.outside_forest_threshold:
                    flags.append("outside_forest@Y")
            pre_coh = dcoh_result.gamma_storm[ref_valid]
            pre_coh = pre_coh[np.isfinite(pre_coh)]
            if pre_coh.size:
                pre_coh_median = float(np.median(pre_coh))
                if pre_coh_median > params.pre_coh_flag:
                    flags.append(
                        "possible_non_forest_before_storm "
                        "(median storm-pair coherence inside reference "
                        "%.3f > %.2f — bare-ground signature)"
                        % (pre_coh_median, params.pre_coh_flag))
            metrics = windthrow_metrics(dcoh, ref & valid, background)

        # 6. report ------------------------------------------------------------
        sp = parse_gunw_pair_info(storm.source_path)
        cp = parse_gunw_pair_info(control.source_path)
        report = {
            "method": "DiD coherence (gamma_control - gamma_storm)",
            "storm_granule": sp.granule,
            "control_granule": cp.granule,
            "storm_pair": [iso(sp.ref_start), iso(sp.sec_start)],
            "control_pair": [iso(cp.ref_start), iso(cp.sec_start)],
            "event_date": iso(event_date),
            "layer": dcoh_result.layer_name,
            "polarization": dcoh_result.pol,
            "grid": {"width": width, "height": height,
                     "crs": georef.crs_authid,
                     "pixel_size_m": abs(georef.transform[1])},
            "reference": {"overlap": ref_overlap},
            "background": {
                "n_pixels": int(background.sum()),
                "median_dcoh": detection.median_bg,
                "mad_dcoh": detection.mad_bg,
            },
            "threshold": {
                "rule": ("median(bg) + a_coh (absolute, reference plugin)"
                         if params.threshold_mode == "absolute"
                         else "median(bg) + k*MAD(bg) (article wording)"),
                "mode": params.threshold_mode,
                "a_coh": params.a_coh,
                "k": params.k_mad,
                "value": detection.threshold,
            },
            "detection": {
                "pixels": detection.n_detected,
                "area_ha": round(detection.area_ha, 2),
                "objects": detection.n_objects,
                "min_pixels_per_object": params.min_pixels,
                "median_filter": "%dx%d" % (params.median_size,
                                            params.median_size),
            },
            "flags": flags,
            "forest_fraction_of_reference": forest_fraction,
            "metrics": metrics,
            "warnings": warnings,
            "params": asdict(params),
        }

        # 7. exports ------------------------------------------------------------
        output_paths: List[str] = []
        if output_dir is not None:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            from .export import ExportBackend
            exporter = ExportBackend(dict(config or {}))

            if export_dcoh and not canceled():
                p = str(out / "dcoh.tif")
                res = exporter.write_raster(dcoh, georef, p,
                                            dtype="Float32", nodata=np.nan)
                if res.success:
                    output_paths.append(p)
                else:
                    warnings.append("dcoh export failed: %s"
                                    % res.error_message)
            progress(85)
            if export_mask and not canceled():
                p = str(out / "windthrow_mask.tif")
                mdata = np.where(detection.mask, np.uint8(1),
                                 np.uint8(0)).astype(np.uint8)
                res = exporter.write_raster(mdata, georef, p, dtype="Byte",
                                            nodata=255)
                if res.success:
                    output_paths.append(p)
                else:
                    warnings.append("mask export failed: %s"
                                    % res.error_message)
            if polygonize and not canceled():
                p = str(out / "windthrow_detections.gpkg")
                if _polygonize_mask(detection.mask, georef, p):
                    output_paths.append(p)
                else:
                    warnings.append("polygonization unavailable "
                                    "(needs GDAL)")
            report["outputs"] = output_paths
            report_path = out / "windthrow_report.json"
            report_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8")
            output_paths.append(str(report_path))

        if canceled():
            return ProcessingResult(success=False,
                                    error_message="Cancelled by user",
                                    warnings=["Cancelled"])

        progress(100)
        return ProcessingResult(
            success=True,
            output_paths=output_paths,
            warnings=warnings,
            metadata=report,
        )
    finally:
        ReaderRegistry.close(storm)
        ReaderRegistry.close(control)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%dT%H:%M:%S") if dt else None


def _polygonize_mask(mask: np.ndarray, georef, output_path: str) -> bool:
    """Polygonize a boolean mask to GeoPackage (GDAL-only, best effort)."""
    try:
        from osgeo import gdal, ogr, osr
        gdal.UseExceptions()
    except Exception:  # pragma: no cover - environment specific
        return False
    import tempfile
    import os
    tmp = None
    try:
        # write mask to a temp in-memory GTiff
        drv = gdal.GetDriverByName("GTiff")
        tmp_fd, tmp = tempfile.mkstemp(suffix=".tif")
        os.close(tmp_fd)
        ds = drv.Create(tmp, mask.shape[1], mask.shape[0], 1,
                        gdal.GDT_Byte)
        ds.SetGeoTransform(list(georef.transform))
        if georef.crs_wkt:
            ds.SetProjection(georef.crs_wkt)
        elif georef.crs_authid:
            srs = osr.SpatialReference()
            srs.SetFromUserInput(georef.crs_authid)
            ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(255)
        band.WriteArray(np.where(mask, 1, 0).astype(np.uint8))
        band.FlushCache()
        ds.FlushCache()
        del ds

        # polygonize
        src = gdal.Open(tmp)
        srs = osr.SpatialReference()
        srs.SetFromUserInput(georef.crs_authid or "EPSG:4326")
        gpkg_drv = ogr.GetDriverByName("GPKG")
        if gpkg_drv is None:
            return False
        if os.path.exists(output_path):
            os.unlink(output_path)
        dst = gpkg_drv.CreateDataSource(output_path)
        layer = dst.CreateLayer("windthrow", srs, ogr.wkbPolygon)
        layer.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
        gdal.Polygonize(src.GetRasterBand(1), src.GetRasterBand(1), layer,
                        0, [], callback=None)
        layer = None
        dst = None
        src = None
        return True
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("polygonize failed: %s", exc)
        return False
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
