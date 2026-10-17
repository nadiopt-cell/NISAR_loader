"""
Core data models — QGIS-independent.
"""
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


@dataclass
class LayerInfo:
    """Information about a subdataset/layer in a product."""
    name: str
    path: str  # HDF5 group path
    description: str
    polarization: Optional[Polarization] = None
    units: str = ""  # e.g., "linear power", "gamma0", "dB"
    shape: tuple = ()
    dtype: str = ""
    no_data_value: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


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

    def get_layer(self, name: str) -> Optional[LayerInfo]:
        for layer in self.layers:
            if layer.name == name or layer.path.endswith(name):
                return layer
        return None

    def layers_with_polarization(self, pol: Polarization) -> List[LayerInfo]:
        """All layers carrying the given polarization."""
        return [l for l in self.layers if l.polarization is pol]

    def available_polarizations(self) -> "set":
        """Set of polarizations available in this product."""
        return {l.polarization for l in self.layers if l.polarization is not None}


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