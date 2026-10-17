# -*- coding: utf-8 -*-
"""
Pytest configuration — makes ``nisar_qgis`` importable from the repo root
without QGIS (nisar_core is QGIS-free by design).
"""
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

H5PY = pytest.importorskip("h5py", reason="synthetic GCOV needs h5py")

# ---------------------------------------------------------------------------
# Synthetic tiny GCOV product (structure per JPL D-102274 §5.2/§5.3 —
# see docs/product_notes.md). Generated per-test into tmp_path: no binary
# test data is committed to the repository.
# ---------------------------------------------------------------------------
H, W = 32, 48          # height (Length), width (Width)
X0, Y0, DX, DY = 400000.0, 5000000.0, 10.0, 10.0  # UTM, meters
EPSG = 32633

WKT_UTM33N = (
    'PROJCS["WGS 84 / UTM zone 33N",'
    'GEOGCS["WGS 84",'
    'DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563,'
    'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],'
    'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4326"]],'
    'PROJECTION["Transverse_Mercator"],'
    'PARAMETER["latitude_of_origin",0],'
    'PARAMETER["central_meridian",15],'
    'PARAMETER["scale_factor",0.9996],'
    'PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",0],'
    'UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
    'AXIS["Easting",EAST],AXIS["Northing",NORTH],'
    'AUTHORITY["EPSG","32633"]]')


def _arr_hhhh():
    """Deterministic linear gamma-0 powers (0.02 .. ~1.5)."""
    base = np.linspace(0.02, 1.5, H * W, dtype=np.float64)
    return base.reshape(H, W).astype(np.float32)


def _arr_hvhv():
    base = np.linspace(0.01, 0.8, H * W, dtype=np.float64)
    return (base.reshape(H, W) ** 1.2).astype(np.float32)


def _arr_vvvv():
    base = np.linspace(0.03, 1.1, H * W, dtype=np.float64)
    return base.reshape(H, W).astype(np.float32)


def make_synthetic_gcov(path, full_pol=False, with_georef=True):
    """Create a small NISAR GCOV-like HDF5 file."""
    import h5py

    with h5py.File(str(path), "w") as f:
        # --- identification (§5.2) ---
        ident = f.create_group("/science/LSAR/identification")
        ident["granuleId"] = (
            "NISAR_L2_PR_GCOV_031_134_D_052_4005_DHDH_A_"
            "20260927T115535_20260927T115548_P05023_N_P_J_001")
        ident["productType"] = "GCOV"
        ident["productVersion"] = "1.0.11"
        ident["productLevel"] = "L2"
        ident["missionId"] = "NISAR"
        ident["platformName"] = "NISAR"
        ident["instrumentName"] = "L-SAR"
        ident["radarBand"] = "L"
        ident["lookDirection"] = "Right"
        ident["orbitPassDirection"] = "Descending"
        ident["zeroDopplerStartTime"] = "2026-09-27T11:55:35.000000000"
        ident["zeroDopplerEndTime"] = "2026-09-27T11:55:48.000000000"
        ident["absoluteOrbitNumber"] = np.uint32(6132)
        ident["trackNumber"] = np.uint32(134)
        ident["frameNumber"] = np.uint16(52)
        ident["isGeocoded"] = "True"
        ident["isUrgentObservation"] = "False"
        ident["isFullFrame"] = "True"
        ident["isMixedMode"] = "False"
        ident["processingType"] = "Nominal"
        ident["processingCenter"] = "JPL"
        ident["processingDateTime"] = "2026-09-29T01:33:56"
        ident["compositeReleaseId"] = "P05023"
        ident["listOfFrequencies"] = np.array(["A"], dtype="S1")

        # --- grids (§5.3) ---
        grid = f.create_group("/science/LSAR/GCOV/grids/frequencyA")

        def add_cov(name, data):
            ds = grid.create_dataset(name, data=data, dtype="f4")
            ds.attrs["units"] = "1"
            ds.attrs["valid_min"] = np.float32(0.0)
            ds.attrs["_FillValue"] = np.float32("nan")
            ds.attrs["long_name"] = (
                "Geocoded polarimetric covariance term %s" % name)
            ds.attrs["grid_mapping"] = "projection"
            return ds

        add_cov("HHHH", _arr_hhhh())
        add_cov("HVHV", _arr_hvhv())
        if full_pol:
            add_cov("VVVV", _arr_vvvv())

        mask = np.zeros((H, W), dtype=np.uint8)
        mask[0, 0] = 255           # outside area
        mask[1, 1] = 0             # invalid sample
        mds = grid.create_dataset("mask", data=mask, dtype="u1")
        mds.attrs["_FillValue"] = np.uint8(255)
        mds.attrs["valid_min"] = np.uint8(0)
        mds.attrs["grid_mapping"] = "projection"

        nlooks = grid.create_dataset(
            "numberOfLooks", data=np.full((H, W), 16.0, dtype="f4"))
        nlooks.attrs["_FillValue"] = np.float32("nan")
        nlooks.attrs["units"] = "1"
        nlooks.attrs["grid_mapping"] = "projection"

        rtc = grid.create_dataset(
            "rtcGammaToSigmaFactor", data=np.ones((H, W), dtype="f4"))
        rtc.attrs["_FillValue"] = np.float32("nan")
        rtc.attrs["units"] = "1"
        rtc.attrs["grid_mapping"] = "projection"

        # coordinates (CF: pixel centers; Y descending = north-up)
        xs = X0 + DX * np.arange(W, dtype=np.float64)
        ys = Y0 - DY * np.arange(H, dtype=np.float64)
        xds = grid.create_dataset("xCoordinates", data=xs)
        xds.attrs["units"] = "meters"
        xds.attrs["standard_name"] = "projection_x_coordinate"
        yds = grid.create_dataset("yCoordinates", data=ys)
        yds.attrs["units"] = "meters"
        yds.attrs["standard_name"] = "projection_y_coordinate"

        grid.create_dataset("xCoordinateSpacing", data=np.float64(DX))
        grid.create_dataset("yCoordinateSpacing", data=np.float64(DY))

        proj = grid.create_dataset("projection", data=np.uint32(EPSG))
        if with_georef:
            proj.attrs["epsg_code"] = str(EPSG)
            proj.attrs["spatial_ref"] = WKT_UTM33N
            proj.attrs["grid_mapping_name"] = "transverse_mercator"
            proj.attrs["utm_zone_number"] = np.int32(33)
            proj.attrs["semi_major_axis"] = np.float64(6378137.0)
            proj.attrs["inverse_flattening"] = np.float64(298.257223563)

        pols = ["HH", "HV"] + (["VV", "VH"] if full_pol else ["VV", "VH"])
        grid.create_dataset("listOfPolarizations",
                            data=np.array(pols, dtype="S2"))
        grid.create_dataset(
            "listOfCovarianceTerms",
            data=np.array(["HHHH", "HVHV"] +
                          (["VVVV"] if full_pol else []), dtype="S4"))

    return str(path)


@pytest.fixture(scope="session")
def gcov_dual(tmp_path_factory):
    """Dual-pol (HH+HV) synthetic GCOV with valid georef."""
    path = tmp_path_factory.mktemp("gcov") / "dual.h5"
    return make_synthetic_gcov(path, full_pol=False)


@pytest.fixture(scope="session")
def gcov_full(tmp_path_factory):
    """Full-pol synthetic GCOV (adds VVVV)."""
    path = tmp_path_factory.mktemp("gcov") / "full.h5"
    return make_synthetic_gcov(path, full_pol=True)


@pytest.fixture(scope="session")
def gcov_no_georef(tmp_path_factory):
    """Synthetic GCOV without projection attributes."""
    path = tmp_path_factory.mktemp("gcov") / "no_georef.h5"
    return make_synthetic_gcov(path, full_pol=False, with_georef=False)


@pytest.fixture(scope="session")
def gcov_ur_vdual(tmp_path_factory):
    """Realistic urgent-response GCOV clone: frequencyB, V-dual-pol
    (VHVH+VVVV), NEGATIVE yCoordinateSpacing (north-up), CRID P05023 —
    mirrors a real granule verified on 2026-09-28 (see product_notes.md)."""
    import h5py

    path = tmp_path_factory.mktemp("gcov_ur") / "ur_vdual.h5"
    with h5py.File(str(path), "w") as f:
        ident = f.create_group("/science/LSAR/identification")
        ident["granuleId"] = (
            "NISAR_L2_UR_GCOV_031_151_A_011_0005_NADV_A_"
            "20260928T155022_20260928T155037_P05023_F_P_J_001")
        ident["productType"] = "GCOV"
        ident["productVersion"] = "1.0.11"
        ident["productLevel"] = "L2"
        ident["missionId"] = "NISAR"
        ident["platformName"] = "NISAR"
        ident["instrumentName"] = "L-SAR"
        ident["radarBand"] = "L"
        ident["lookDirection"] = "Left"
        ident["orbitPassDirection"] = "Ascending"
        ident["zeroDopplerStartTime"] = "2026-09-28T15:50:22.000000000"
        ident["absoluteOrbitNumber"] = np.uint32(6132)
        ident["trackNumber"] = np.uint32(151)
        ident["frameNumber"] = np.uint16(11)
        ident["isGeocoded"] = "True"
        ident["isUrgentObservation"] = "False"
        ident["isFullFrame"] = "False"
        ident["processingType"] = "Nominal"
        ident["compositeReleaseId"] = "P05023"
        ident["listOfFrequencies"] = np.array(["B"], dtype="S1")

        grid = f.create_group("/science/LSAR/GCOV/grids/frequencyB")

        def add_cov(name, data):
            ds = grid.create_dataset(name, data=data, dtype="f4")
            ds.attrs["units"] = "1"
            ds.attrs["_FillValue"] = np.float32("nan")
            ds.attrs["grid_mapping"] = "projection"
            return ds

        add_cov("VHVH", _arr_hvhv())
        add_cov("VVVV", _arr_vvvv())

        mask = np.zeros((H, W), dtype=np.uint8)
        mask[0, :] = 255
        mask[:, -1] = 255
        mds = grid.create_dataset("mask", data=mask, dtype="u1")
        mds.attrs["_FillValue"] = np.uint8(255)

        # Real-product layout: x ascending, y descending, spacing SIGNED.
        xs = X0 + DX * np.arange(W, dtype=np.float64)
        ys = Y0 - DY * np.arange(H, dtype=np.float64)
        grid.create_dataset("xCoordinates", data=xs)
        grid.create_dataset("yCoordinates", data=ys)
        grid.create_dataset("xCoordinateSpacing", data=np.float64(DX))
        grid.create_dataset("yCoordinateSpacing", data=np.float64(-DY))

        proj = grid.create_dataset("projection", data=np.uint32(32605))
        proj.attrs["epsg_code"] = "32605"
        proj.attrs["spatial_ref"] = (
            'PROJCS["WGS 84 / UTM zone 5N",GEOGCS["WGS 84",'
            'DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
            'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],'
            'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
            'UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]],'
            'PROJECTION["Transverse_Mercator"],'
            'PARAMETER["latitude_of_origin",0],'
            'PARAMETER["central_meridian",-153],'
            'PARAMETER["scale_factor",0.9996],'
            'PARAMETER["false_easting",500000],'
            'PARAMETER["false_northing",0],'
            'UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
            'AUTHORITY["EPSG","32605"]]')

        grid.create_dataset("listOfPolarizations",
                            data=np.array(["VH", "VV"], dtype="S2"))
        grid.create_dataset("listOfCovarianceTerms",
                            data=np.array(["VHVH", "VVVV"], dtype="S4"))

    return str(path)


# ---------------------------------------------------------------------------
# Synthetic GUNW pairs (storm + control) with an injected windthrow.
# Layout verified against a real granule (2026-06-20, track 093, frame 58,
# PROVISIONAL P05023): layers live under
#   /science/LSAR/GUNW/grids/frequencyA/<group>/[<pol>/]<dataset>
# with group-level coordinates; identification is product-level and carries
# reference*/secondary* fields; mask is uint32 in the real product.
# ---------------------------------------------------------------------------
GH, GW = 64, 48                    # 80 m grid: 5.1 x 3.8 km
GX0, GY0, GDX, GDY = 270000.0, 1044720.0, 80.0, 80.0
GUNW_EPSG = 32641

WKT_UTM41N = (
    'PROJCS["WGS 84 / UTM zone 41N",'
    'GEOGCS["WGS 84",'
    'DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563,'
    'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],'
    'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]],'
    'PROJECTION["Transverse_Mercator"],'
    'PARAMETER["latitude_of_origin",0],'
    'PARAMETER["central_meridian",63],'
    'PARAMETER["scale_factor",0.9996],'
    'PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",0],UNIT["metre",1],'
    'AXIS["Easting",EAST],AXIS["Northing",NORTH],'
    'AUTHORITY["EPSG","32641"]])')

# the synthetic windthrow: rows 20..32, cols 10..22 (12x12 px @ 80 m)
GUNW_DAMAGE_ROWS = (20, 32)
GUNW_DAMAGE_COLS = (10, 22)
GUNW_DAMAGE_COH_DROP = 0.35       # storm-pair coherence drop inside damage


def _gunw_noise(seed):
    """Spatially correlated coherence noise (multilooked 80 m layers are
    smooth in reality; iid per-pixel noise would be unrealistically harsh
    for the detector)."""
    rng = np.random.default_rng(seed)
    coarse = rng.normal(0.0, 0.05, (GH // 4, GW // 4))
    fine = np.kron(coarse, np.ones((4, 4)))[:GH, :GW]
    return (fine + rng.normal(0.0, 0.01, (GH, GW))).astype(np.float32)


def _gunw_coherence(kind: str):
    """Coherence of one pair: intact forest ~0.62, damage drop in storm."""
    noise = _gunw_noise(7 if kind == "storm" else 11)
    base = np.full((GH, GW), 0.62, dtype=np.float32)
    data = np.clip(base + noise, 0.02, 0.98)
    if kind == "storm":
        r0, r1 = GUNW_DAMAGE_ROWS
        c0, c1 = GUNW_DAMAGE_COLS
        data[r0:r1, c0:c1] = np.clip(
            data[r0:r1, c0:c1] - GUNW_DAMAGE_COH_DROP, 0.02, 0.98)
    return data


def make_synthetic_gunw(path, kind: str, track: int = 93, frame: int = 58,
                        granule_suffix: str = "STORM" if True else ""):
    """Create a small NISAR GUNW-like HDF5 file (storm or control pair).

    ``kind``: 'storm' (damage inside the interval) or 'control' (intact).
    """
    import h5py

    if kind == "storm":
        granule = ("NISAR_L2_PR_GUNW_023_%03d_D_%03d_024_2000_SH_"
                   "20260620T154356_20260620T154433_20260702T154356_"
                   "20260702T154432_P05023_N_F_J_001" % (track, frame))
        ref_start, ref_end = "2026-06-20T15:43:56.000000000", \
            "2026-06-20T15:44:33.000000000"
        sec_start, sec_end = "2026-07-02T15:43:56.000000000", \
            "2026-07-02T15:44:32.000000000"
        ref_orbit, sec_orbit = np.uint32(4661), np.uint32(4834)
    else:
        granule = ("NISAR_L2_PR_GUNW_024_%03d_D_%03d_025_2000_SH_"
                   "20260702T154356_20260702T154432_20260714T154355_"
                   "20260714T154431_P05023_F_F_J_001" % (track, frame))
        ref_start, ref_end = "2026-07-02T15:43:56.000000000", \
            "2026-07-02T15:44:32.000000000"
        sec_start, sec_end = "2026-07-14T15:43:55.000000000", \
            "2026-07-14T15:44:31.000000000"
        ref_orbit, sec_orbit = np.uint32(4834), np.uint32(5007)

    with h5py.File(str(path), "w") as f:
        ident = f.create_group("/science/LSAR/identification")
        ident["granuleId"] = granule
        ident["productType"] = "GUNW"
        ident["productVersion"] = "1.0.11"
        ident["productLevel"] = "L2"
        ident["missionId"] = "NISAR"
        ident["platformName"] = "NISAR"
        ident["instrumentName"] = "L-SAR"
        ident["radarBand"] = "L"
        ident["lookDirection"] = "Left"
        ident["orbitPassDirection"] = "Descending"
        ident["trackNumber"] = np.uint32(track)
        ident["frameNumber"] = np.uint16(frame)
        ident["isGeocoded"] = "True"
        ident["isUrgentObservation"] = "False"
        ident["isFullFrame"] = "True"
        ident["processingType"] = "Nominal"
        ident["processingCenter"] = "JPL"
        ident["processingDateTime"] = "2026-07-20T01:00:00"
        ident["compositeReleaseId"] = "P05023"
        ident["listOfFrequencies"] = np.array(["A"], dtype="S1")
        ident["referenceAbsoluteOrbitNumber"] = ref_orbit
        ident["secondaryAbsoluteOrbitNumber"] = sec_orbit
        ident["referenceZeroDopplerStartTime"] = ref_start
        ident["referenceZeroDopplerEndTime"] = ref_end
        ident["secondaryZeroDopplerStartTime"] = sec_start
        ident["secondaryZeroDopplerEndTime"] = sec_end
        ident["boundingPolygon"] = (
            "POLYGON ((56.88 58.35 100.0, 63.15 58.35 200.0, "
            "63.15 61.50 300.0, 56.88 61.50 400.0, "
            "56.88 58.35 100.0))")

        base = "/science/LSAR/GUNW/grids/frequencyA"
        unw = f.create_group("%s/unwrappedInterferogram" % base)
        hh = unw.create_group("HH")

        coh = _gunw_coherence(kind)
        ds = hh.create_dataset("coherenceMagnitude", data=coh, dtype="f4")
        ds.attrs["units"] = "1"
        ds.attrs["_FillValue"] = np.float32("nan")
        ds.attrs["grid_mapping"] = "projection"

        phase = hh.create_dataset(
            "unwrappedPhase",
            data=np.zeros((GH, GW), dtype="f4"))
        phase.attrs["_FillValue"] = np.float32("nan")
        comps = hh.create_dataset(
            "connectedComponents",
            data=np.zeros((GH, GW), dtype="u2"))
        comps.attrs["_FillValue"] = np.uint16(65535)

        mask = np.zeros((GH, GW), dtype=np.uint32)
        mask[:2, :] = 1
        mds = unw.create_dataset("mask", data=mask, dtype="u4")
        mds.attrs["_FillValue"] = np.uint32(4294967295)

        # group-level coordinates (CF pixel centers; y descending, north-up)
        xs = GX0 + GDX * np.arange(GW, dtype=np.float64)
        ys = GY0 - GDY * np.arange(GH, dtype=np.float64)
        unw.create_dataset("xCoordinates", data=xs)
        unw.create_dataset("yCoordinates", data=ys)
        unw.create_dataset("xCoordinateSpacing", data=np.float64(GDX))
        unw.create_dataset("yCoordinateSpacing", data=np.float64(-GDY))
        proj = unw.create_dataset("projection", data=np.uint32(GUNW_EPSG))
        proj.attrs["epsg_code"] = str(GUNW_EPSG)
        proj.attrs["spatial_ref"] = WKT_UTM41N
        proj.attrs["grid_mapping_name"] = "transverse_mercator"

        # 20 m wrappedInterferogram grid (4x resolution), incl. coherence
        wrp = f.create_group("%s/wrappedInterferogram" % base)
        whh = wrp.create_group("HH")
        coh20 = np.kron(coh, np.ones((4, 4), dtype=np.float32))
        ds20 = whh.create_dataset("coherenceMagnitude", data=coh20,
                                  dtype="f4")
        ds20.attrs["units"] = "1"
        ds20.attrs["_FillValue"] = np.float32("nan")
        interfero = whh.create_dataset(
            "wrappedInterferogram",
            data=(np.exp(1j * 0.1) * np.ones(coh20.shape,
                                             dtype=np.complex64)))
        interfero.attrs["_FillValue"] = "(nan+nanj)"
        xs20 = GX0 + (GDX / 4) * np.arange(GW * 4, dtype=np.float64)
        ys20 = GY0 - (GDY / 4) * np.arange(GH * 4, dtype=np.float64)
        wrp.create_dataset("xCoordinates", data=xs20)
        wrp.create_dataset("yCoordinates", data=ys20)
        wrp.create_dataset("xCoordinateSpacing", data=np.float64(GDX / 4))
        wrp.create_dataset("yCoordinateSpacing", data=np.float64(-GDY / 4))
        proj20 = wrp.create_dataset("projection", data=np.uint32(GUNW_EPSG))
        proj20.attrs["epsg_code"] = str(GUNW_EPSG)
        proj20.attrs["spatial_ref"] = WKT_UTM41N
        wrp.create_dataset(
            "listOfPolarizations", data=np.array(["HH"], dtype="S2"))

        fa = f.require_group(base)
        fa.create_dataset("centerFrequency", data=np.float64(1.2575e9))
        fa.create_dataset(
            "listOfPolarizations", data=np.array(["HH"], dtype="S2"))

    return str(path)


@pytest.fixture(scope="session")
def gunw_storm(tmp_path_factory):
    path = tmp_path_factory.mktemp("gunw") / "storm.h5"
    return make_synthetic_gunw(path, kind="storm")


@pytest.fixture(scope="session")
def gunw_control(tmp_path_factory):
    path = tmp_path_factory.mktemp("gunw") / "control.h5"
    return make_synthetic_gunw(path, kind="control")


@pytest.fixture()
def gunw_damage_mask():
    """The synthetic windthrow footprint as a bool array."""
    import numpy as np
    m = np.zeros((GH, GW), dtype=bool)
    m[GUNW_DAMAGE_ROWS[0]:GUNW_DAMAGE_ROWS[1],
      GUNW_DAMAGE_COLS[0]:GUNW_DAMAGE_COLS[1]] = True
    return m


# ---------------------------------------------------------------------------
# WP-1: dual-frequency synthetic GCOV (frequencyA + frequencyB tiles).
# Used to verify layer identity (layer_id), per-frequency georef, and the
# "indices never mix frequencies" rule.
# ---------------------------------------------------------------------------

DUAL_H, DUAL_W = 20, 30


def make_synthetic_gcov_two_freq(path, freq_a_layers=("HHHH", "HVHV"),
                   freq_b_layers=("VHVH", "VVVV")):
    """Dual-frequency GCOV; *freq_b_layers* is ("VHVH","VVVV") by default.

    frequencyA: *freq_a_layers* on a smaller 10x16 tile;
    frequencyB: *freq_b_layers* on a 20x30 tile.
    """
    import h5py

    with h5py.File(str(path), "w") as f:
        ident = f.create_group("/science/LSAR/identification")
        ident["granuleId"] = (
            "NISAR_L2_PR_GCOV_031_134_D_052_4005_DHDH_A_"
            "20260927T115535_20260927T115548_P05023_N_P_J_001")
        ident["productType"] = "GCOV"
        ident["productVersion"] = "1.0.11"
        ident["productLevel"] = "L2"
        ident["missionId"] = "NISAR"
        ident["platformName"] = "NISAR"
        ident["instrumentName"] = "L-SAR"
        ident["radarBand"] = "L"
        ident["lookDirection"] = "Right"
        ident["orbitPassDirection"] = "Descending"
        ident["zeroDopplerStartTime"] = "2026-09-27T11:55:35.000000000"
        ident["absoluteOrbitNumber"] = np.uint32(6132)
        ident["trackNumber"] = np.uint32(134)
        ident["frameNumber"] = np.uint16(52)
        ident["isGeocoded"] = "True"
        ident["processingType"] = "Nominal"
        ident["compositeReleaseId"] = "P05023"
        ident["listOfFrequencies"] = np.array(["A", "B"], dtype="S1")

        for freq, names, (fh, fw), (x0, y0, dx, dy), epsg in (
                ("frequencyA", freq_a_layers, (10, 16),
                 (400000.0, 5000000.0, 10.0, 10.0), 32633),
                ("frequencyB", freq_b_layers, (DUAL_H, DUAL_W),
                 (401000.0, 4999500.0, 20.0, -20.0), 32633)):
            grid = f.create_group(
                "/science/LSAR/GCOV/grids/%s" % freq)

            def add_cov(name, data, _grid=grid):
                ds = _grid.create_dataset(name, data=data, dtype="f4")
                ds.attrs["units"] = "1"
                ds.attrs["_FillValue"] = np.float32("nan")
                return ds

            for name in names:
                base = np.linspace(0.02, 1.4, fh * fw, dtype=np.float64)
                add_cov(name, (base ** 1.1).astype(np.float32)
                        .reshape(fh, fw))

            xs = x0 + dx * np.arange(fw, dtype=np.float64)
            ys = y0 + np.abs(dy) * np.arange(fh, dtype=np.float64) * (
                -1 if dy < 0 else 1)
            grid.create_dataset("xCoordinates", data=xs)
            grid.create_dataset("yCoordinates", data=ys)
            grid.create_dataset("xCoordinateSpacing", data=np.float64(dx))
            grid.create_dataset("yCoordinateSpacing", data=np.float64(dy))

            proj = grid.create_dataset("projection", data=np.uint32(epsg))
            proj.attrs["epsg_code"] = str(epsg)
            wkt = WKT_UTM33N.replace("32633", str(epsg))
            proj.attrs["spatial_ref"] = wkt
    return str(path)


@pytest.fixture(scope="session")
def gcov_two_freq(tmp_path_factory):
    """A: HHHH+HVHV; B: VHVH+VVVV (distinct pol sets per grid)."""
    path = tmp_path_factory.mktemp("gcov2f") / "two_freq.h5"
    return make_synthetic_gcov_two_freq(path)


@pytest.fixture(scope="session")
def gcov_two_freq_same_names(tmp_path_factory):
    """A: HHHH+HVHV; B: HHHH+HVHV — ambiguous display names across grids."""
    path = tmp_path_factory.mktemp("gcov2fsame") / "two_freq_same.h5"
    return make_synthetic_gcov_two_freq(
        path, freq_b_layers=("HHHH", "HVHV"))


@pytest.fixture(scope="session")
def gcov_mixed_freq(tmp_path_factory):
    """Cross-pol only on A, co-pol only on B — indices must refuse."""
    path = tmp_path_factory.mktemp("gcovmixed") / "mixed.h5"
    return make_synthetic_gcov_two_freq(
        path, freq_a_layers=("HVHV",), freq_b_layers=("HHHH",))
