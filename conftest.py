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
            'PARAMETER["false_northing",0],UNIT["metre",1],'
            'AUTHORITY["EPSG","9001"]],AUTHORITY["EPSG","32605"]]')

        grid.create_dataset("listOfPolarizations",
                            data=np.array(["VH", "VV"], dtype="S2"))
        grid.create_dataset("listOfCovarianceTerms",
                            data=np.array(["VHVH", "VVVV"], dtype="S4"))

    return str(path)
