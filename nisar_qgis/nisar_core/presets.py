"""
Preset registry for vegetation monitoring.
Single source of truth for all preset metadata, formulas, and documentation.
Used by GUI, Processing algorithms, and documentation.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
from .models import Polarization, ProductType


class PresetCategory(Enum):
    BACKSCATTER = "backscatter"
    RATIO = "ratio"
    INDEX = "index"
    TIMESERIES = "timeseries"
    CHANGE = "change"
    FILTER = "filter"
    POLARIMETRY = "polarimetry"


@dataclass
class PresetRequirement:
    """Requirements for a preset to be available."""
    required_polarizations: List[Polarization] = field(default_factory=list)
    required_product_types: List[ProductType] = field(default_factory=list)
    full_pol_required: bool = False
    min_layers: int = 1


@dataclass
class PresetOutput:
    """Output specification."""
    dtype: str = "Float32"
    units: str = ""
    default_style: str = ""  # QML file name
    description: str = ""


@dataclass
class PresetInfo:
    """Complete preset definition."""
    # Identity
    id: str
    category: PresetCategory

    # Display (i18n keys - actual text in i18n/)
    name_key: str
    hint_key: str
    purpose_key: str
    when_to_use_key: str
    how_to_read_key: str
    formula_key: str
    caveats_key: str

    # Requirements
    requirements: PresetRequirement

    # Output
    output: PresetOutput

    # Processing
    algorithm_name: str  # Processing algorithm ID
    parameters_schema: Dict[str, Any] = field(default_factory=dict)

    # Availability check
    def check_availability(self, handle) -> tuple:
        """Check if preset can be computed for given product handle.
        Returns (available, reason_if_not_available)."""
        if handle is None:
            return False, "No product opened"

        # Check product type if the handle declares one.
        if (self.requirements.required_product_types
                and getattr(handle, "product_type", None) is not None
                and handle.product_type not in self.requirements.required_product_types):
            wanted = ", ".join(p.value
                               for p in self.requirements.required_product_types)
            return False, ("Product type %s is not supported (requires %s)"
                           % (handle.product_type.value, wanted))

        # Check polarizations
        available_pols = set()
        for layer in handle.layers:
            if layer.polarization:
                available_pols.add(layer.polarization)

        if not available_pols and handle.layers:
            return False, "No polarization layers found in the product"

        missing = []
        for pol in self.requirements.required_polarizations:
            if pol not in available_pols:
                missing.append(pol.value)

        if missing:
            return False, "Missing polarizations: %s" % ", ".join(missing)

        # Check full-pol
        if self.requirements.full_pol_required:
            required_full = {Polarization.HHHH, Polarization.HVHV, Polarization.VVVV}
            if not required_full.issubset(available_pols):
                return False, "Full-pol data required (HHHH, HVHV, VVVV)"

        if len(handle.layers) < self.requirements.min_layers:
            return False, ("At least %d layers required (found %d)"
                           % (self.requirements.min_layers, len(handle.layers)))

        return True, ""


# ============================================================
# PRESET REGISTRY
# ============================================================

PRESETS: Dict[str, PresetInfo] = {}

def register_preset(preset: PresetInfo):
    PRESETS[preset.id] = preset


# ---- 1. HV (Cross-pol) in dB ----
register_preset(PresetInfo(
    id="hv_db",
    category=PresetCategory.BACKSCATTER,
    name_key="preset.hv_db.name",
    hint_key="preset.hv_db.hint",
    purpose_key="preset.hv_db.purpose",
    when_to_use_key="preset.hv_db.when_to_use",
    how_to_read_key="preset.hv_db.how_to_read",
    formula_key="preset.hv_db.formula",
    caveats_key="preset.hv_db.caveats",
    requirements=PresetRequirement(
        required_polarizations=[Polarization.HVHV],
        required_product_types=[ProductType.GCOV],
    ),
    output=PresetOutput(
        dtype="Float32",
        units="dB",
        default_style="hv_db.qml",
        description="HV cross-polarization backscatter in decibels"
    ),
    algorithm_name="nisar:hv_db",
    parameters_schema={
        "layer": {"type": "string", "default": "HVHV"},
        "nodata_threshold": {"type": "number", "default": 0}
    }
))

# ---- 2. Cross-ratio HV/HH ----
register_preset(PresetInfo(
    id="cross_ratio",
    category=PresetCategory.RATIO,
    name_key="preset.cross_ratio.name",
    hint_key="preset.cross_ratio.hint",
    purpose_key="preset.cross_ratio.purpose",
    when_to_use_key="preset.cross_ratio.when_to_use",
    how_to_read_key="preset.cross_ratio.how_to_read",
    formula_key="preset.cross_ratio.formula",
    caveats_key="preset.cross_ratio.caveats",
    requirements=PresetRequirement(
        required_polarizations=[Polarization.HVHV, Polarization.HHHH],
        required_product_types=[ProductType.GCOV],
    ),
    output=PresetOutput(
        dtype="Float32",
        units="dB",
        default_style="cross_ratio.qml",
        description="Cross-ratio HV/HH in decibels"
    ),
    algorithm_name="nisar:cross_ratio",
    parameters_schema={
        "hv_layer": {"type": "string", "default": "HVHV"},
        "hh_layer": {"type": "string", "default": "HHHH"}
    }
))

# ---- 3. RVI (Radar Vegetation Index) ----
register_preset(PresetInfo(
    id="rvi",
    category=PresetCategory.INDEX,
    name_key="preset.rvi.name",
    hint_key="preset.rvi.hint",
    purpose_key="preset.rvi.purpose",
    when_to_use_key="preset.rvi.when_to_use",
    how_to_read_key="preset.rvi.how_to_read",
    formula_key="preset.rvi.formula",
    caveats_key="preset.rvi.caveats",
    requirements=PresetRequirement(
        required_polarizations=[Polarization.HVHV, Polarization.HHHH],
        required_product_types=[ProductType.GCOV],
        # VV optional for full-pol
    ),
    output=PresetOutput(
        dtype="Float32",
        units="unitless (0-1 typical)",
        default_style="rvi.qml",
        description="Radar Vegetation Index (dual or full-pol)"
    ),
    algorithm_name="nisar:rvi",
    parameters_schema={
        "hv_layer": {"type": "string", "default": "HVHV"},
        "hh_layer": {"type": "string", "default": "HHHH"},
        "vv_layer": {"type": "string", "default": "VVVV"},
        "auto_detect_pol": {"type": "boolean", "default": True}
    }
))

# ---- 4. Time Series ----
register_preset(PresetInfo(
    id="timeseries",
    category=PresetCategory.TIMESERIES,
    name_key="preset.timeseries.name",
    hint_key="preset.timeseries.hint",
    purpose_key="preset.timeseries.purpose",
    when_to_use_key="preset.timeseries.when_to_use",
    how_to_read_key="preset.timeseries.how_to_read",
    formula_key="preset.timeseries.formula",
    caveats_key="preset.timeseries.caveats",
    requirements=PresetRequirement(
        required_polarizations=[],  # Depends on selected index
        required_product_types=[ProductType.GCOV],
        min_layers=1,
    ),
    output=PresetOutput(
        dtype="Float32",
        units="varies",
        default_style="",
        description="Time series statistics (CSV + chart)"
    ),
    algorithm_name="nisar:timeseries",
    parameters_schema={
        "aoi_layer": {"type": "vector", "geometry": "polygon"},
        "index": {"type": "enum", "values": ["hv_db", "cross_ratio", "rvi"], "default": "hv_db"},
        "statistics": {"type": "list", "values": ["mean", "median", "std"], "default": ["mean", "median"]},
        "output_csv": {"type": "file", "ext": "csv"},
        "output_chart": {"type": "file", "ext": "png"}
    }
))

# ---- 5. Change Detection ----
register_preset(PresetInfo(
    id="change_db",
    category=PresetCategory.CHANGE,
    name_key="preset.change_db.name",
    hint_key="preset.change_db.hint",
    purpose_key="preset.change_db.purpose",
    when_to_use_key="preset.change_db.when_to_use",
    how_to_read_key="preset.change_db.how_to_read",
    formula_key="preset.change_db.formula",
    caveats_key="preset.change_db.caveats",
    requirements=PresetRequirement(
        required_polarizations=[Polarization.HVHV],
        required_product_types=[ProductType.GCOV],
        min_layers=1,
    ),
    output=PresetOutput(
        dtype="Float32",
        units="dB",
        default_style="change_db.qml",
        description="Backscatter change in dB between two dates"
    ),
    algorithm_name="nisar:change_detection",
    parameters_schema={
        "reference_scene": {"type": "file", "ext": "h5"},
        "comparison_scene": {"type": "file", "ext": "h5"},
        "layer": {"type": "string", "default": "HVHV"},
        "threshold_db": {"type": "number", "default": -3.0},
        "output_mask": {"type": "boolean", "default": True}
    }
))

# ---- 6. Speckle Filter ----
register_preset(PresetInfo(
    id="speckle",
    category=PresetCategory.FILTER,
    name_key="preset.speckle.name",
    hint_key="preset.speckle.hint",
    purpose_key="preset.speckle.purpose",
    when_to_use_key="preset.speckle.when_to_use",
    how_to_read_key="preset.speckle.how_to_read",
    formula_key="preset.speckle.formula",
    caveats_key="preset.speckle.caveats",
    requirements=PresetRequirement(
        required_polarizations=[],
        required_product_types=[ProductType.GCOV, ProductType.GSLC],
        min_layers=1,
    ),
    output=PresetOutput(
        dtype="Float32",
        units="same as input",
        default_style="",
        description="Speckle-filtered layer (separate output)"
    ),
    algorithm_name="nisar:speckle_filter",
    parameters_schema={
        "input_layer": {"type": "raster"},
        "method": {"type": "enum", "values": ["median", "box", "lee"], "default": "median"},
        "kernel_size": {"type": "int", "default": 3, "min": 3, "max": 7},
        "output_separate": {"type": "boolean", "default": True}
    }
))

# ---- 7. Pauli RGB (full-pol, later) ----
register_preset(PresetInfo(
    id="pauli_rgb",
    category=PresetCategory.POLARIMETRY,
    name_key="preset.pauli_rgb.name",
    hint_key="preset.pauli_rgb.hint",
    purpose_key="preset.pauli_rgb.purpose",
    when_to_use_key="preset.pauli_rgb.when_to_use",
    how_to_read_key="preset.pauli_rgb.how_to_read",
    formula_key="preset.pauli_rgb.formula",
    caveats_key="preset.pauli_rgb.caveats",
    requirements=PresetRequirement(
        required_polarizations=[Polarization.HHHH, Polarization.HVHV, Polarization.VVVV],
        required_product_types=[ProductType.GCOV],
        full_pol_required=True,
    ),
    output=PresetOutput(
        dtype="UInt16",
        units="RGB (0-65535)",
        default_style="pauli_rgb.qml",
        description="Pauli decomposition RGB composite"
    ),
    algorithm_name="nisar:pauli_rgb",
    parameters_schema={
        "hhhh_layer": {"type": "string", "default": "HHHH"},
        "hvhv_layer": {"type": "string", "default": "HVHV"},
        "vvvv_layer": {"type": "string", "default": "VVVV"},
        "stretch": {"type": "enum", "values": ["percentile", "minmax", "none"], "default": "percentile"}
    }
))

# ---- 8. Freeman-Durden (full-pol, later) ----
register_preset(PresetInfo(
    id="freeman_durden",
    category=PresetCategory.POLARIMETRY,
    name_key="preset.freeman_durden.name",
    hint_key="preset.freeman_durden.hint",
    purpose_key="preset.freeman_durden.purpose",
    when_to_use_key="preset.freeman_durden.when_to_use",
    how_to_read_key="preset.freeman_durden.how_to_read",
    formula_key="preset.freeman_durden.formula",
    caveats_key="preset.freeman_durden.caveats",
    requirements=PresetRequirement(
        required_polarizations=[Polarization.HHHH, Polarization.HVHV, Polarization.VVVV],
        required_product_types=[ProductType.GCOV],
        full_pol_required=True,
    ),
    output=PresetOutput(
        dtype="Float32",
        units="power",
        default_style="freeman_durden.qml",
        description="Freeman-Durden three-component decomposition"
    ),
    algorithm_name="nisar:freeman_durden",
    parameters_schema={
        "hhhh_layer": {"type": "string", "default": "HHHH"},
        "hvhv_layer": {"type": "string", "default": "HVHV"},
        "vvvv_layer": {"type": "string", "default": "VVVV"},
        "handle_negative": {"type": "enum", "values": ["clip", "preserve", "nan"], "default": "clip"}
    }
))

# ---- 9. H/A/alpha (full-pol, later) ----
register_preset(PresetInfo(
    id="h_a_alpha",
    category=PresetCategory.POLARIMETRY,
    name_key="preset.h_a_alpha.name",
    hint_key="preset.h_a_alpha.hint",
    purpose_key="preset.h_a_alpha.purpose",
    when_to_use_key="preset.h_a_alpha.when_to_use",
    how_to_read_key="preset.h_a_alpha.how_to_read",
    formula_key="preset.h_a_alpha.formula",
    caveats_key="preset.h_a_alpha.caveats",
    requirements=PresetRequirement(
        required_polarizations=[Polarization.HHHH, Polarization.HVHV, Polarization.VVVV],
        required_product_types=[ProductType.GCOV],
        full_pol_required=True,
    ),
    output=PresetOutput(
        dtype="Float32",
        units="H: 0-1, A: 0-1, alpha: 0-90 deg",
        default_style="h_a_alpha.qml",
        description="Cloude-Pottier decomposition (Entropy, Anisotropy, Alpha)"
    ),
    algorithm_name="nisar:h_a_alpha",
    parameters_schema={
        "hhhh_layer": {"type": "string", "default": "HHHH"},
        "hvhv_layer": {"type": "string", "default": "HVHV"},
        "vvvv_layer": {"type": "string", "default": "VVVV"},
    }
))


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_preset(preset_id: str) -> Optional[PresetInfo]:
    """Get preset by ID."""
    return PRESETS.get(preset_id)


def list_presets(category: PresetCategory = None) -> List[PresetInfo]:
    """List all presets, optionally filtered by category."""
    result = list(PRESETS.values())
    if category:
        result = [p for p in result if p.category == category]
    return sorted(result, key=lambda p: p.id)


def get_available_presets(handle) -> List[PresetInfo]:
    """Get presets available for a given product handle."""
    available = []
    for preset in PRESETS.values():
        avail, reason = preset.check_availability(handle)
        if avail:
            available.append(preset)
    return available


def get_preset_categories() -> List[PresetCategory]:
    """Get all categories that have presets."""
    cats = set(p.category for p in PRESETS.values())
    return sorted(cats, key=lambda c: c.value)