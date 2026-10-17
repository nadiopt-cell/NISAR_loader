# -*- coding: utf-8 -*-
"""
A4: h5py reader for NISAR L2 GUNW (geocoded unwrapped interferogram).

Structure follows the official product specification
JPL D-102272 Rev E (2024-11-08), section 5 — see readers/product_layers.py:
  * 80 m grid : /science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/
                {HH|VV}/{coherenceMagnitude, unwrappedPhase,
                connectedComponents, ionospherePhaseScreen*}
  * 20 m grid : /science/LSAR/GUNW/grids/frequencyA/wrappedInterferogram/
                {HH|VV}/{coherenceMagnitude, wrappedInterferogram}
  * coordinates sit at the GROUP level (xCoordinates, yCoordinates,
    x/yCoordinateSpacing, projection) — pixel centers per CF 1.7;
  * identification is product-level (/science/LSAR/identification) and
    carries reference*/secondary* pair fields.

The reader is a sibling of A3 (GCOV); both are pure h5py, no GDAL.
``handle.georef`` describes the primary 80 m grid; every LayerInfo
additionally carries its own georef copy in ``metadata['georef']`` because
GUNW products contain two grids with different posting/extent.
"""
import logging
from typing import List, Tuple, Dict, Any, Optional

import numpy as np

try:
    import h5py
    H5PY_AVAILABLE = True
except ImportError:  # pragma: no cover - environment specific
    H5PY_AVAILABLE = False

from .base import BaseReader, ReaderRegistry
from .a3_h5py import _as_text, _EPSG_FROM_WKT, _URN_EPSG, _AUTH_EPSG
from . import product_layers as PL
from ..models import (
    ProductHandle, LayerInfo, GeorefInfo, DataStatus, ProductType,
    Polarization, frequency_letter_from_label, resolve_layer,
)

logger = logging.getLogger("nisar.readers.a4")


class A4GunwH5PyReader(BaseReader):
    """Manual HDF5 reading of GUNW pair products (h5py, no GDAL)."""

    BACKEND_ID = "A4_gunw_h5py"
    BACKEND_NAME = "h5py GUNW (manual HDF5)"
    REQUIRES_DEPENDENCIES = ["h5py"]

    @classmethod
    def check_availability(cls) -> Tuple[bool, str]:
        if not H5PY_AVAILABLE:
            return False, "h5py not installed (pip install h5py)"
        return True, ""

    @classmethod
    def can_open(cls, path: str) -> bool:
        if not H5PY_AVAILABLE:
            return False
        import os
        if not os.path.isfile(path):
            return False
        try:
            with h5py.File(path, "r") as h5:
                for instrument in ("LSAR", "SSAR"):
                    if "/science/%s/GUNW" % instrument in h5:
                        return True
                return False
        except Exception:
            return False

    # ------------------------------------------------------------------ open
    def open(self, path: str) -> ProductHandle:
        if not H5PY_AVAILABLE:
            raise RuntimeError("h5py is not installed (pip install h5py)")

        h5 = h5py.File(path, "r")
        try:
            instrument = self._detect_instrument(h5)
            layers = self._extract_layers(h5, instrument)
            georef, layer_georefs = self._extract_georefs(h5, instrument)
            identification = self._extract_identification(h5, instrument)
            data_status = self._detect_data_status(identification)

            # attach per-group georefs to the layer infos created above
            for layer in layers:
                gref = layer_georefs.get(layer.metadata.get("group"))
                if gref is not None:
                    layer.metadata["georef"] = gref
                    layer.georef = gref  # WP-1: first-class per-layer georef

            handle = ProductHandle(
                source_path=path,
                reader_backend=self.BACKEND_ID,
                layers=layers,
                georef=georef,
                metadata={
                    "identification": identification,
                    "data_status": data_status.value,
                    "pair_info": self._pair_info_dict(identification),
                },
                product_type=ProductType.GUNW,
                data_status=data_status,
            )
            handle._h5_file = h5
            handle._h5_reader = self
            logger.debug("A4 opened %s (%s/GUNW, %d layers)",
                         path, instrument, len(layers))
            return handle
        except Exception:
            try:
                h5.close()
            except Exception:  # pragma: no cover
                pass
            raise

    # ------------------------------------------------------------ structure
    @staticmethod
    def _detect_instrument(h5) -> str:
        for instrument in ("LSAR", "SSAR"):
            if "/science/%s/GUNW" % instrument in h5:
                return instrument
        raise ValueError(
            "No GUNW product group found under /science "
            "(expected /science/LSAR|SSAR/GUNW)")

    def _extract_layers(self, h5, instrument: str) -> List[LayerInfo]:
        layers: List[LayerInfo] = []
        # verified on a real granule: layers live under
        # /science/LSAR/GUNW/grids/frequencyA/<group>/<pol>/<dataset>
        base = "%s/%s" % (PL.GUNW_GRID_BASE.format(instrument=instrument),
                           PL.GUNW_FREQ)

        for group_name, datasets in (
                (PL.GUNW_GROUP_UNWRAPPED, PL.GUNW_UNWRAPPED_DATASETS),
                (PL.GUNW_GROUP_WRAPPED, PL.GUNW_WRAPPED_DATASETS)):
            group_path = "%s/%s" % (base, group_name)
            if group_path not in h5:
                continue
            posting = PL.GUNW_POSTING_BY_GROUP.get(group_name)

            for pol in PL.GUNW_CO_POL_LAYERS:
                pol_path = "%s/%s" % (group_path, pol)
                if pol_path not in h5:
                    continue
                for name in datasets:
                    if name not in h5[pol_path]:
                        continue
                    dataset = h5[pol_path][name]
                    if not isinstance(dataset, h5py.Dataset):
                        continue
                    layers.append(self._dataset_to_layer_info(
                        dataset,
                        "%s/%s" % (pol_path, name),
                        pol, group_name, posting))

            # group-level water/subswath mask (spec §5.3, Table 3-9/3-11)
            if "mask" in h5[group_path]:
                dataset = h5[group_path]["mask"]
                if isinstance(dataset, h5py.Dataset) and dataset.ndim == 2:
                    layers.append(self._dataset_to_layer_info(
                        dataset, "%s/mask" % group_path,
                        None, group_name, posting))
        return layers

    def _dataset_to_layer_info(self, dataset, path: str, pol: Optional[str],
                               group_name: str,
                               posting: Optional[int]) -> LayerInfo:
        shape = dataset.shape  # (length, width)
        attrs = {k: _as_text(v) if np.ndim(v) == 0 else v
                 for k, v in dataset.attrs.items()}
        dataset_name = path.split("/")[-1]

        units = attrs.get("units", "unknown")
        if dataset_name == "coherenceMagnitude":
            units = "1 (coherence 0..1)"

        nodata = None
        fill = attrs.get("_FillValue", None)
        if fill is not None and np.ndim(fill) == 0:
            try:
                nodata = float(fill)
            except (TypeError, ValueError):
                # complex fills like "(nan+nanj)" (wrappedInterferogram)
                # are not representable as a single float — ignore.
                nodata = None

        height, width = (shape[0], shape[1]) if len(shape) >= 2 else (shape[0], 1)

        # Unique, human-friendly layer name: <pol>_<dataset>_<posting>m
        prefix = pol if pol else "mask"
        name = "%s_%s_%dm" % (prefix, dataset_name, posting or 0)

        return LayerInfo(
            name=name,
            path=path,
            description="%s @ %s m grid (%s)" % (dataset_name, posting,
                                                 group_name),
            polarization=(Polarization[pol] if pol else None),
            units=units,
            shape=(height, width),
            dtype=str(dataset.dtype),
            no_data_value=nodata,
            metadata={
                "group": group_name,
                "posting_m": posting,
                "pol": pol,
                "dataset": dataset_name,
            },
            frequency=frequency_letter_from_label(PL.GUNW_FREQ),
        )

    # ------------------------------------------------------------- georef
    def _extract_georefs(self, h5, instrument: str
                         ) -> Tuple[Optional[GeorefInfo], Dict[str, GeorefInfo]]:
        """Georef of the 80 m grid (primary) + per-group georefs."""
        base = "%s/%s" % (PL.GUNW_GRID_BASE.format(instrument=instrument),
                           PL.GUNW_FREQ)
        per_group: Dict[str, GeorefInfo] = {}
        primary: Optional[GeorefInfo] = None

        for group_name in (PL.GUNW_GROUP_UNWRAPPED, PL.GUNW_GROUP_WRAPPED):
            group_path = "%s/%s" % (base, group_name)
            if group_path not in h5:
                continue
            gref = self._georef_from_group(h5[group_path], group_path)
            if gref is not None:
                per_group[group_name] = gref

        primary = per_group.get(PL.GUNW_GROUP_UNWRAPPED) \
            or (next(iter(per_group.values())) if per_group else None)
        if primary is None:
            primary = GeorefInfo(
                crs_wkt="", crs_authid="", transform=[0, 1, 0, 0, 0, -1],
                width=0, height=0, bbox=(0, 0, 0, 0), is_valid=False,
                warnings=["No GUNW grid group with coordinates found"])
        return primary, per_group

    def _georef_from_group(self, group, group_path: str
                           ) -> Optional[GeorefInfo]:
        if "xCoordinates" not in group or "yCoordinates" not in group:
            return None
        xs = np.asarray(group["xCoordinates"][()],
                        dtype=np.float64).ravel()
        ys = np.asarray(group["yCoordinates"][()],
                        dtype=np.float64).ravel()
        if xs.size < 2 or ys.size < 2:
            return None

        width, height = int(xs.size), int(ys.size)
        dx_signed = (float(group["xCoordinateSpacing"][()])
                     if "xCoordinateSpacing" in group
                     else float(xs[1] - xs[0]))
        dy_signed = (float(group["yCoordinateSpacing"][()])
                     if "yCoordinateSpacing" in group
                     else float(ys[0] - ys[-1]) / max(ys.size - 1, 1))
        dx, dy = abs(dx_signed), abs(dy_signed)
        if dx <= 0 or dy <= 0 or not np.isfinite(dx) or not np.isfinite(dy):
            return None

        warnings: List[str] = []
        if xs[0] > xs[-1]:
            warnings.append("%s: descending xCoordinates" % group_path)

        # CF convention: coordinate variables are pixel centers; real
        # products store a negative yCoordinateSpacing for north-up grids.
        y_descending = ys[0] > ys[-1]
        if y_descending:
            transform = [float(xs[0]) - dx / 2.0, dx, 0.0,
                         float(ys[0]) + dy / 2.0, 0.0, -dy]
        else:
            transform = [float(xs[0]) - dx / 2.0, dx, 0.0,
                         float(ys[0]) - dy / 2.0, 0.0, dy]

        crs_wkt, auth_id = self._read_projection(group)
        if not auth_id:
            warnings.append("CRS authority code not recognized")

        ulx, xres, _, uly, _, yres = transform
        lrx = ulx + width * xres
        lry = uly + height * yres
        bbox = (min(ulx, lrx), min(uly, lry), max(ulx, lrx), max(uly, lry))

        return GeorefInfo(
            crs_wkt=crs_wkt,
            crs_authid=auth_id,
            transform=transform,
            width=width,
            height=height,
            bbox=bbox,
            is_valid=bool(crs_wkt or auth_id) and not warnings,
            warnings=warnings,
        )

    def _read_projection(self, group) -> Tuple[str, str]:
        crs_wkt, auth_id = "", ""
        if "projection" in group:
            proj = group["projection"]
            attrs = proj.attrs
            if "spatial_ref" in attrs:
                crs_wkt = _as_text(attrs["spatial_ref"])
            if "epsg_code" in attrs:
                auth_id = "EPSG:%s" % _as_text(attrs["epsg_code"])
        if not auth_id and crs_wkt:
            match = (_URN_EPSG.search(crs_wkt) or _EPSG_FROM_WKT.search(crs_wkt)
                     or _AUTH_EPSG.search(crs_wkt))
            if match:
                auth_id = "EPSG:%s" % match.group(1)
        return crs_wkt, auth_id

    # ------------------------------------------------------- identification
    def _extract_identification(self, h5, instrument: str) -> Dict[str, Any]:
        path = PL.IDENTIFICATION_PATH.format(instrument=instrument)
        result: Dict[str, Any] = {}
        if path not in h5:
            return result
        group = h5[path]
        for key in PL.IDENTIFICATION_FIELDS + PL.GUNW_PAIR_IDENTIFICATION_FIELDS:
            if key not in group:
                continue
            value = group[key][()]
            if isinstance(value, np.ndarray) and value.shape == ():
                value = value[()]
            if isinstance(value, (bytes, np.bytes_, np.str_, str)):
                result[key] = _as_text(value)
            else:
                result[key] = value.item() if hasattr(value, "item") else value
        return result

    @staticmethod
    def _pair_info_dict(identification: Dict[str, Any]) -> Dict[str, Any]:
        """Pair metadata used for DiD compatibility checks."""
        return {
            "trackNumber": identification.get("trackNumber"),
            "frameNumber": identification.get("frameNumber"),
            "orbitPassDirection": identification.get("orbitPassDirection"),
            "lookDirection": identification.get("lookDirection"),
            "referenceZeroDopplerStartTime":
                identification.get("referenceZeroDopplerStartTime"),
            "secondaryZeroDopplerStartTime":
                identification.get("secondaryZeroDopplerStartTime"),
            "granuleId": identification.get("granuleId"),
        }

    @staticmethod
    def _detect_data_status(identification: Dict[str, Any]) -> DataStatus:
        crid = str(identification.get("compositeReleaseId", "")).strip().upper()
        if crid.startswith("B"):
            return DataStatus.BETA
        if crid.startswith("P"):
            return DataStatus.PROVISIONAL
        if crid.startswith("V"):
            return DataStatus.VALIDATED
        blob = ("%s %s" % (identification.get("processingType", ""),
                           identification.get("productVersion", ""))).upper()
        if "BETA" in blob:
            return DataStatus.BETA
        if "PROVISIONAL" in blob or "URGENT" in blob:
            return DataStatus.PROVISIONAL
        if "VALIDATED" in blob:
            return DataStatus.VALIDATED
        return DataStatus.UNKNOWN

    # ---------------------------------------------------------- read/close
    def read_window(self, handle: ProductHandle, layer_name: str,
                    window: Tuple[int, int, int, int]) -> np.ndarray:
        h5 = getattr(handle, "_h5_file", None)
        if h5 is None:
            h5 = h5py.File(handle.source_path, "r")
            handle._h5_file = h5

        layer = resolve_layer(handle, layer_name)

        dataset = h5.get(layer.path)
        if dataset is None:
            raise ValueError("Layer path %r missing in file" % layer.path)

        xoff, yoff, xsize, ysize = window
        out = dataset[yoff:yoff + ysize, xoff:xoff + xsize]
        return np.asarray(out)

    def close(self, handle: ProductHandle):
        h5 = getattr(handle, "_h5_file", None)
        if h5 is not None:
            try:
                h5.close()
            except Exception:  # pragma: no cover
                pass
            handle._h5_file = None


# A4 registers after A3 (registration order = auto-open priority; GUNW
# files are claimed only by this backend — A3/A1 look for GCOV/GSLC/RSLC).
ReaderRegistry.register(A4GunwH5PyReader)
