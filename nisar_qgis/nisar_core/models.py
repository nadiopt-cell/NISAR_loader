# -*- coding: utf-8 -*-
"""
Core data models — QGIS-independent.

Layer addressing (WP-1): every HDF5 layer is addressed by a unique
``LayerInfo.layer_id`` (e.g. ``"frequencyA/HHHH"``, or
``"frequencyA/unwrappedInterferogram/HH/coherenceMagnitude"`` for GUNW).
Display names (``LayerInfo.name``) may repeat between frequency groups —
resolving by name alone raises :class:`AmbiguousLayerError` instead of
silently picking the first match (review finding F1/F14).
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any


class DataStatus(Enum):
    """Product calibration/validation status."""
    BETA = "BETA"
    PROVISIONAL = "PROVISIONAL"
    VALIDATED = "VALIDATED"
    UNKNOWN = "UNKNOWN"


class ProductLevel(Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class ProductType(Enum):
    GCOV = "GCOV"
    GSLC = "GSLC"
    RSLC = "RSLC"
    GUNW = "GUNW"
    UNKNOWN = "UNKNOWN"


class Polarization(Enum):
    HH = "HH"
    VV = "VV"
    HV = "HV"
    VH = "VH"
    HHHH = "HHHH"
    HVHV = "HVHV"
    VHVH = "VHVH"   # JPL D-102274 §5.3 (dual-pol DV mode term)
    VVVV = "VVVV"
    HHVV = "HHVV"
    HHHV = "HHHV"


class Instrument(Enum):
    LSAR = "LSAR"  # L-band
    SSAR = "SSAR"  # S-band


# ================================================================ errors
class LayerNotFoundError(ValueError):
    """No layer matches the requested key (WP-1: explicit, never silent)."""


class AmbiguousLayerError(ValueError):
    """A layer key matches several layers; disambiguate via ``layer_id``."""

    def __init__(self, key: str, candidates: List[str]):
        self.key = key
        self.candidates = list(candidates)
        super().__init__(
            "Layer key %r is ambiguous, matches %d layers with the same "
            "name in different grids/frequencies. Address a specific layer "
            "by its unique identifier: %s"
            % (key, len(self.candidates), ", ".join(self.candidates)))


# =========================================================== helpers
_FREQ_IN_PATH = re.compile(r"/grids/(frequency([AB]))")
_TAIL_IN_PATH = re.compile(r"/grids/([^\"']+)$;?", re.ASCII)
_TAIL_IN_PATH = re.compile(r"/grids/([^\"']+)")


def frequency_letter_from_label(label: Optional[str]) -> Optional[str]:
    """'frequencyA' -> 'A'; already-'A' passes through; None/'' -> None."""
    if not label:
        return None
    label = str(label).strip()
    if label.startswith("frequency") and len(label) >= 10:
        return label[len("frequency"):len("frequency") + 1]
    if label in ("A", "B"):
        return label
    return None


def _derive_layer_id(path: str, frequency: Optional[str],
                     name: str) -> str:
    """Unique layer identifier from the HDF5 group path.

    ``"frequencyA/HHHH"`` for GCOV; full relative tail for GUNW
    (``"frequencyA/unwrappedInterferogram/HH/coherenceMagnitude"``).
    """
    if path:
        match = _TAIL_IN_PATH.search(str(path))
        if match:
            rel = match.group(1).strip("\"'")
            if rel:
                return rel
    if frequency:
        return "%s/%s" % (frequency, name)
    return name


def resolve_layer(handle, key: Optional[str]):
    """Resolve a layer by full path, ``layer_id``, or (unique) name.

    Raises :class:`AmbiguousLayerError` when a name matches several
    layers (different frequencies/grids) and
    :class:`LayerNotFoundError` when nothing matches. No
    ``path.endswith``/substring guessing (F14).
    """
    layers = getattr(handle, "layers", None) or []
    if key is None or not str(key).strip():
        raise LayerNotFoundError("Empty layer key requested")

    key_norm = str(key).strip().lstrip("/")

    # 1. exact HDF5/subdataset path
    for layer in layers:
        if layer.path and layer.path == key:
            return layer

    # 2. exact unique layer_id
    for layer in layers:
        if layer.layer_id == key_norm:
            return layer

    # 3. unique display name
    by_name = [l for l in layers if l.name == key_norm]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise AmbiguousLayerError(
            key_norm, [l.layer_id or l.name for l in by_name])

    # 4. last path segment compared as a whole (no partial suffix)
    matches = [l for l in layers
               if l.path and l.path.rstrip("/").split("/")[-1] == key_norm]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise AmbiguousLayerError(
            key_norm, [l.layer_id or l.name for l in matches])

    available = ", ".join(
        (l.layer_id or l.name) for l in layers[:10]) or "none"
    raise LayerNotFoundError(
        "Layer %r not found in %s (available: %s%s)"
        % (key, getattr(handle, "source_path", "?"), available,
           " ..." if len(layers) > 10 else ""))


def output_name_with_frequency(base: str, name: str,
                               frequency: Optional[str],
                               ext: str = ".tif") -> str:
    """WP-1: '<base>_<frequency>_<name>.tif'; the frequency segment is
    omitted when the product carries no frequency information. Two grids
    of the same product never map to the same output file.
    """
    if frequency in ("A", "B"):
        return "%s_%s_%s%s" % (base, frequency, name, ext)
    return "%s_%s%s" % (base, name, ext)


# =========================================================== dataclasses
@dataclass
class GeorefInfo:
    """Georeferencing information."""
    crs_wkt: str
    crs_authid: str  # e.g., "EPSG:4326"
    transform: List[float]  # GDAL geotransform [ulx, xres, xskew, uly, yskew, yres]
    width: int
    height: int
    bbox: tuple  # (minx, miny, maxx, maxy) in CRS units
    is_valid: bool = True
    warnings: List[str] = field(default_factory=list)


@dataclass
class LayerInfo:
    """Information about a subdataset/layer in a product.

    ``frequency``  — "A" / "B" / None (NISAR grids frequencyA/frequencyB).
    ``layer_id``   — unique key (``"frequencyA/HHHH"``); the definitive
                     addressing field (WP-1). ``name`` stays a display
                     label and may repeat between frequencies.
    ``georef``     — per-layer georeference when the product has several
                     grids (WP-1); ``ProductHandle.georef`` remains the
                     product-level primary grid.
    """
    name: str
    path: str  # HDF5 group path or GDAL subdataset string
    description: str
    polarization: Optional[Polarization] = None
    units: str = ""  # e.g., "linear power", "gamma0", "dB"
    shape: tuple = ()
    dtype: str = ""
    no_data_value: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    frequency: Optional[str] = None
    layer_id: str = ""
    georef: Optional[GeorefInfo] = None

    def __post_init__(self):
        # Back-compat: some readers put the frequency in metadata.
        if self.frequency is None:
            self.frequency = frequency_letter_from_label(
                self.metadata.get("frequency"))
        if self.frequency is None:
            match = _FREQ_IN_PATH.search(str(self.path or ""))
            if match:
                self.frequency = match.group(2)
        if not self.layer_id:
            self.layer_id = _derive_layer_id(
                self.path, self.frequency, self.name)
        # keep the historical metadata key in sync for GUI/i18n use
        if self.frequency:
            self.metadata.setdefault("frequency", "frequency%s"
                                     % self.frequency)


@dataclass
class ProductHandle:
    """Abstract handle to an opened product — backend-independent."""
    source_path: str  # local path, VSI path, or S3 URL
    reader_backend: str  # backend id, e.g. "A1_native", "A3_h5py"
    layers: List[LayerInfo] = field(default_factory=list)
    georef: Optional[GeorefInfo] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    product_type: Optional[ProductType] = None
    data_status: DataStatus = DataStatus.UNKNOWN

    def list_layers(self) -> List[LayerInfo]:
        return self.layers

    def get_layer(self, name: str) -> LayerInfo:
        """Resolve a layer (see :func:`resolve_layer`); raises on
        ambiguity or absence — GUI/keys must catch the ValueError
        subclasses or address layers by ``layer_id`` (WP-1)."""
        return resolve_layer(self, name)

    def layers_by_frequency(self, frequency: Optional[str]) -> List[LayerInfo]:
        """All layers of one frequency grid ("A"/"B")."""
        return [l for l in self.layers if l.frequency == frequency]

    def frequencies(self) -> List[str]:
        """Sorted frequency letters available among layers ("A", "B")."""
        return sorted({l.frequency for l in self.layers
                       if l.frequency})

    def georef_for_frequency(self, frequency: Optional[str]) \
            -> Optional[GeorefInfo]:
        """Per-frequency georef: explicit per-layer copy first, then the
        product-level primary grid (WP-1)."""
        for layer in self.layers_by_frequency(frequency):
            if layer.georef is not None and layer.georef.is_valid:
                return layer.georef
        primary = self.metadata.get("georef_by_frequency", {})
        gref = primary.get(frequency)
        if gref is not None and gref.is_valid:
            return gref
        return self.georef

    def layers_with_polarization(self, pol: Polarization) -> List[LayerInfo]:
        """All layers carrying the given polarization."""
        return [l for l in self.layers if l.polarization is pol]

    def available_polarizations(self) -> "set":
        """Set of polarizations available in this product."""
        return {l.polarization for l in self.layers
                if l.polarization is not None}


@dataclass
class SceneRecord:
    """Unified scene record from any access backend."""
    scene_id: str
    product_type: ProductType
    level: ProductLevel
    instrument: Instrument
    status: DataStatus
    acquisition_time: datetime
    footprint_wkt: str  # Polygon in EPSG:4326
    size_bytes: int
    urls: Dict[str, str]  # e.g., {"download": "...", "s3": "...", "browse": "..."}
    polarizations: List[Polarization]
    mode: str  # e.g., "GCOV", "full-pol", "dual-pol"
    orbit_number: Optional[int] = None
    orbit_direction: Optional[str] = None  # "ASCENDING" / "DESCENDING"
    frame_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_beta(self) -> bool:
        return self.status == DataStatus.BETA

    @property
    def is_provisional(self) -> bool:
        return self.status == DataStatus.PROVISIONAL

    def short_description(self) -> str:
        return f"{self.scene_id} | {self.product_type.value} | {self.instrument.value} | {self.status.value} | {self.acquisition_time.date()}"


@dataclass
class SearchParameters:
    """Parameters for scene search."""
    aoi_wkt: Optional[str] = None  # AOI as WKT polygon (EPSG:4326)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    product_types: List[ProductType] = field(default_factory=lambda: [ProductType.GCOV])
    instruments: List[Instrument] = field(default_factory=lambda: [Instrument.LSAR])
    polarizations: List[Polarization] = field(default_factory=list)
    status_filter: List[DataStatus] = field(default_factory=lambda: [DataStatus.PROVISIONAL, DataStatus.VALIDATED])
    max_results: int = 100
    max_cloud_cover: Optional[float] = None  # Not applicable for SAR, kept for compatibility


@dataclass
class ProcessingResult:
    """Result of a processing operation."""
    success: bool
    output_paths: List[str] = field(default_factory=list)
    error_message: str = ""
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
