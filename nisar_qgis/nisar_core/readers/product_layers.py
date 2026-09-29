# -*- coding: utf-8 -*-
"""
Known NISAR product layer paths — constants, not guesses.

Source of truth:
  * JPL D-102274 Rev E (2024-11-08), "NISAR Level-2 Geocoded Polarimetric
    Covariance (GCOV) Product Specification", section 5.3 — official ASF
    document: https://nisar.asf.earthdatacloud.nasa.gov/NISAR-SAMPLE-DATA/
    DOCS/NISAR_D-102274_RevE_NASA_SDS_Product_Specification_L2_GCOV_Nov8_2024_w-sigs.pdf
  * NISAR Data User Guide: https://nisar-docs.asf.alaska.edu/gcov

Verified against the official product specification document (NOT yet
against a real .h5 file — see docs/product_notes.md, "verification status").
"""
from typing import Optional

from ..models import Polarization, ProductType

# ---------------------------------------------------------------------------
# Grid group bases (instrument-aware)
# ---------------------------------------------------------------------------
GCOV_GRID_BASE = "/science/{instrument}/GCOV/grids"
GSLC_GRID_BASE = "/science/{instrument}/GSLC/grids"
RSLC_GRID_BASE = "/science/{instrument}/RSLC/grids"

FREQUENCY_GROUPS = ("frequencyA", "frequencyB")

# ---------------------------------------------------------------------------
# GCOV covariance terms (JPL D-102274 §5.3, "Radar Imagery" table)
# Diagonal terms are real-valued Float32; off-diagonal are complex-valued
# and present only for quad-pol acquisitions.
# ---------------------------------------------------------------------------
GCOV_REAL_COVARIANCE_TERMS = (
    "HHHH", "HVHV", "VHVH", "VVVV", "RHRH", "RVRV",
)
GCOV_COMPLEX_COVARIANCE_TERMS = (
    "HHHV", "HHVH", "HHVV", "HVVH", "HVVV", "VHVV", "RHRV",
)
GCOV_ALL_COVARIANCE_TERMS = GCOV_REAL_COVARIANCE_TERMS + GCOV_COMPLEX_COVARIANCE_TERMS

# GSLC/RSLC polarizations (single-pol layers, complex data)
SAR_POL_LAYERS = ("HH", "HV", "VH", "VV")

# ---------------------------------------------------------------------------
# GCOV auxiliary datasets (same grid as the covariance terms)
# ---------------------------------------------------------------------------
GCOV_AUX_LAYERS = (
    "mask",                    # UByte: subswath mask, 0=invalid, 255=outside
    "numberOfLooks",           # Float32
    "rtcGammaToSigmaFactor",   # Float32: gamma0 -> sigma0 factor
)

# Coordinate / projection datasets of a GCOV frequency group
GCOV_COORD_DATASETS = (
    "xCoordinates",            # Float64 (width,)
    "yCoordinates",            # Float64 (length,)
    "xCoordinateSpacing",      # Float64 scalar, meters
    "yCoordinateSpacing",      # Float64 scalar, meters
    "projection",              # UInt32 scalar + attrs (epsg_code, spatial_ref, ...)
    "listOfPolarizations",     # string list
    "listOfCovarianceTerms",   # string list
)

# ---------------------------------------------------------------------------
# Identification group (JPL D-102274 §5.2)
# ---------------------------------------------------------------------------
IDENTIFICATION_PATH = "/science/{instrument}/identification"

IDENTIFICATION_FIELDS = (
    "absoluteOrbitNumber", "trackNumber", "frameNumber", "missionId",
    "processingCenter", "productType", "granuleId", "productDoi",
    "productVersion", "productSpecificationVersion", "lookDirection",
    "orbitPassDirection", "zeroDopplerStartTime", "zeroDopplerEndTime",
    "plannedDatatakeId", "plannedObservationId", "isUrgentObservation",
    "listOfFrequencies", "diagnosticModeFlag", "productLevel", "isGeocoded",
    "boundingPolygon", "processingDateTime", "radarBand", "platformName",
    "instrumentName", "processingType", "isDithered", "isMixedMode",
    "isFullFrame", "compositeReleaseId", "isJointObservation",
)

# CRID of the first fully-calibrated (PROVISIONAL) processing campaign;
# used only as a *hint* for in-file status detection — see product_notes.md.
PROVISIONAL_CRID = "P05023"


# ---------------------------------------------------------------------------
# GUNW (L2 geocoded unwrapped interferogram) — JPL D-102272 Rev E §5.3.
# Interferometric pairs: only co-pol (HH or VV), only frequencyA.
# Two nested grids per product:
#   * unwrappedInterferogram/<pol>/  — 80 m posting: coherenceMagnitude,
#     unwrappedPhase, connectedComponents, ionospherePhaseScreen(+Uncertainty)
#   * wrappedInterferogram/<pol>/    — 20 m posting: coherenceMagnitude,
#     complex wrappedInterferogram
# Group-level coordinate datasets sit directly under the group
# (e.g. .../unwrappedInterferogram/xCoordinates), pixel centers per CF.
# ---------------------------------------------------------------------------
GUNW_GRID_BASE = "/science/{instrument}/GUNW/grids"
GUNW_FREQ = "frequencyA"  # interferometry never uses frequencyB (spec §3.2.4)
GUNW_GROUP_UNWRAPPED = "unwrappedInterferogram"   # 80 m posting
GUNW_GROUP_WRAPPED = "wrappedInterferogram"       # 20 m posting

GUNW_CO_POL_LAYERS = ("HH", "VV")  # cross-pol is never interferometrically
                                   # processed (spec §3.2.4)
GUNW_UNWRAPPED_DATASETS = (
    "coherenceMagnitude", "unwrappedPhase", "connectedComponents",
    "ionospherePhaseScreen", "ionospherePhaseScreenUncertainty",
)
GUNW_WRAPPED_DATASETS = (
    "coherenceMagnitude", "wrappedInterferogram",
)
GUNW_POSTING_BY_GROUP = {
    "unwrappedInterferogram": 80,   # nominal meters
    "wrappedInterferogram": 20,
}

# Identification is product-level (NOT under /GUNW): /science/LSAR/identification.
# GUNW adds reference*/secondary* fields for the interferometric pair.
GUNW_PAIR_IDENTIFICATION_FIELDS = (
    "referenceAbsoluteOrbitNumber", "secondaryAbsoluteOrbitNumber",
    "referenceZeroDopplerStartTime", "referenceZeroDopplerEndTime",
    "secondaryZeroDopplerStartTime", "secondaryZeroDopplerEndTime",
)


def gunw_grid_group(instrument: str = "LSAR",
                    group: str = GUNW_GROUP_UNWRAPPED) -> str:
    """Full HDF5 group path of a GUNW layer group (80 m or 20 m).

    Verified on a real granule (2026-06-18, track 064, PROVISIONAL):
      /science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram
    """
    return "%s/%s/%s" % (GUNW_GRID_BASE.format(instrument=instrument),
                         GUNW_FREQ, group)


def gunw_layer_path(pol: str, dataset: str,
                    instrument: str = "LSAR",
                    group: str = GUNW_GROUP_UNWRAPPED) -> str:
    """Full HDF5 dataset path of a GUNW layer, e.g.
    /science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/HH/coherenceMagnitude
    """
    return "%s/%s/%s" % (gunw_grid_group(instrument, group),
                         pol.upper(), dataset)


# ---------------------------------------------------------------------------
# Layer-name <-> polarization mapping
# ---------------------------------------------------------------------------
_POL_BY_LAYER_NAME = {
    # Real-valued diagonal terms (exact enum members)
    "HHHH": Polarization.HHHH, "HVHV": Polarization.HVHV,
    "VHVH": Polarization.VHVH, "VVVV": Polarization.VVVV,
    # Complex off-diagonal terms that have an enum member
    "HHVV": Polarization.HHVV, "HHHV": Polarization.HHHV,
    # Single-pol layers of GSLC/RSLC
    "HH": Polarization.HH, "HV": Polarization.HV,
    "VH": Polarization.VH, "VV": Polarization.VV,
    # NOTE: complex terms HHVH / HVVH / HVVV / VHVV and compact-pol terms
    # RHRH / RVRV / RHRV intentionally map to None — no matching enum member
    # and no vegetation preset needs them.
}


def polarization_from_layer_name(name: str) -> Optional[Polarization]:
    """Map an HDF5 dataset name (e.g. 'HVHV') to a Polarization enum."""
    if not name:
        return None
    return _POL_BY_LAYER_NAME.get(name.split("/")[-1].upper())


def layer_name_from_polarization(pol: Polarization) -> Optional[str]:
    """Reverse mapping: preferred HDF5 layer name for a polarization."""
    for layer_name, candidate in _POL_BY_LAYER_NAME.items():
        if candidate is pol:
            return layer_name
    return None


def gcov_grid_group(instrument: str = "LSAR", frequency: str = "frequencyA") -> str:
    """Full HDF5 group path of a GCOV frequency group."""
    return "%s/%s" % (GCOV_GRID_BASE.format(instrument=instrument), frequency)


def gcov_layer_path(layer_name: str, instrument: str = "LSAR",
                    frequency: str = "frequencyA") -> str:
    """Full HDF5 dataset path of a GCOV layer."""
    return "%s/%s" % (gcov_grid_group(instrument, frequency), layer_name)


def is_gcov_layer_name(name: str) -> bool:
    """True if *name* is a known GCOV dataset of a frequency group."""
    base = name.split("/")[-1]
    return (base in GCOV_ALL_COVARIANCE_TERMS
            or base in GCOV_AUX_LAYERS
            or base in GCOV_COORD_DATASETS)
