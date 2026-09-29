# -*- coding: utf-8 -*-
"""
A3: h5py reader — manual NISAR HDF5 reading, zero GDAL dependency.

Structure follows the official product specification
(JPL D-102274 Rev E, section 5; see readers/product_layers.py):
  * covariance layers: /science/LSAR/GCOV/grids/frequencyA/<HHHH|HVHV|...>
  * coordinates:       xCoordinates / yCoordinates (Float64, meters, CF
                       convention = pixel centers)
  * projection:        UInt32 scalar with attrs ``epsg_code`` and
                       ``spatial_ref`` (WKT)
  * identification:    /science/LSAR/identification/... (granuleId,
                       productType, zeroDopplerStartTime, ...)
"""
import logging
import re
from typing import List, Tuple, Dict, Any, Optional

import numpy as np

try:
    import h5py
    H5PY_AVAILABLE = True
except ImportError:  # pragma: no cover - environment specific
    H5PY_AVAILABLE = False

from .base import BaseReader, ReaderRegistry
from . import product_layers as PL
from ..models import (
    ProductHandle, LayerInfo, GeorefInfo, DataStatus, ProductType, Instrument,
)

logger = logging.getLogger("nisar.readers.a3")

# Fallback EPSG extraction from a WKT string (no osgeo dependency needed).
_EPSG_FROM_WKT = re.compile(r'(?i)"?\bID\s*\[\s*"?EPSG"?\s*,\s*(\d+)\s*\]')
_URN_EPSG = re.compile(r'(?i)urn:ogc:def:crs:EPSG::(\d+)')
_AUTH_EPSG = re.compile(
    r'(?i)AUTHORITY\s*\[\s*"EPSG"\s*,\s*"(\d+)"\s*\]')

_INSTRUMENTS = ("LSAR", "SSAR")
_PRODUCTS = ("GCOV", "GSLC", "RSLC")


def _as_text(value) -> str:
    """Best-effort conversion of h5py string values to ``str``."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.bytes_):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray) and value.shape == ():
        return _as_text(value[()])
    if isinstance(value, (np.str_, str)):
        return str(value)
    return str(value)


class A3H5PyReader(BaseReader):
    """Manual HDF5 reading using h5py (no GDAL / rasterio required)."""

    BACKEND_ID = "A3_h5py"
    BACKEND_NAME = "h5py (manual HDF5)"
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
            with h5py.File(path, "r"):
                return True
        except Exception:
            return False

    # ------------------------------------------------------------------ open
    def open(self, path: str) -> ProductHandle:
        """Open a NISAR product and build a backend-independent handle."""
        if not H5PY_AVAILABLE:
            raise RuntimeError("h5py is not installed (pip install h5py)")

        h5 = h5py.File(path, "r")
        try:
            instrument, product = self._detect_product(h5)
            layers = self._extract_layers(h5, instrument, product)
            georef = self._extract_georef(h5, instrument, product)
            identification = self._extract_identification(h5, instrument)
            handle = ProductHandle(
                source_path=path,
                reader_backend=self.BACKEND_ID,
                layers=layers,
                georef=georef,
                metadata={
                    "identification": identification,
                    "data_status": DataStatus.UNKNOWN.value,  # see product_notes.md
                },
                product_type=self._to_product_type(product),
                data_status=DataStatus.UNKNOWN,
            )
            # Keep the open file for windowed reads (closed by close()).
            handle._h5_file = h5
            handle._h5_reader = self
            logger.debug("A3 opened %s (%s/%s, %d layers)",
                         path, instrument, product, len(layers))
            return handle
        except Exception:
            try:
                h5.close()
            except Exception:  # pragma: no cover
                pass
            raise

    # -------------------------------------------------------- structure scan
    def _detect_product(self, h5) -> Tuple[str, str]:
        """Find '<instrument>/<product>' under /science."""
        for instrument in _INSTRUMENTS:
            for product in _PRODUCTS:
                if "/science/%s/%s" % (instrument, product) in h5:
                    return instrument, product
        raise ValueError(
            "No NISAR product group found under /science "
            "(expected /science/LSAR|SSAR/GCOV|GSLC|RSLC)")

    def _extract_layers(self, h5, instrument: str,
                        product: str) -> List[LayerInfo]:
        """List covariance + auxiliary layers of all frequency groups."""
        layers: List[LayerInfo] = []
        base = "/science/%s/%s/grids" % (instrument, product)

        for freq in PL.FREQUENCY_GROUPS:
            group_path = "%s/%s" % (base, freq)
            if group_path not in h5:
                continue
            group = h5[group_path]

            # Preferred order: covariance terms, then auxiliary layers.
            candidates = ([n for n in PL.GCOV_ALL_COVARIANCE_TERMS
                           if n in group]
                          if product == "GCOV"
                          else [n for n in PL.SAR_POL_LAYERS if n in group])
            candidates += [n for n in PL.GCOV_AUX_LAYERS if n in group]

            for name in candidates:
                dataset = group[name]
                if not isinstance(dataset, h5py.Dataset):
                    continue
                layers.append(self._dataset_to_layer_info(
                    dataset, "%s/%s" % (group_path, name), freq))
        return layers

    def _dataset_to_layer_info(self, dataset, path: str,
                               frequency: str) -> LayerInfo:
        shape = dataset.shape  # (length, width) per JPL D-102274 §5.3
        attrs = {k: _as_text(v) if np.ndim(v) == 0 else v
                 for k, v in dataset.attrs.items()}
        name = path.split("/")[-1]

        units = attrs.get("units", "unknown")
        if name in PL.GCOV_REAL_COVARIANCE_TERMS:
            # gamma-0 power, RTC-normalized (product spec §4.1 / user guide)
            units = "gamma0 (linear power, RTC)"

        nodata = None
        fill = attrs.get("_FillValue", None)
        if fill is not None and np.ndim(fill) == 0:
            nodata = float(fill)

        height, width = (shape[0], shape[1]) if len(shape) >= 2 else (shape[0], 1)

        return LayerInfo(
            name=name,
            path=path,
            description="%s (%s)" % (name, frequency),
            polarization=PL.polarization_from_layer_name(name),
            units=units,
            shape=(height, width),  # unified convention: (height, width)
            dtype=str(dataset.dtype),
            no_data_value=nodata,
            metadata={"frequency": frequency},
        )

    # ------------------------------------------------------------- georef
    def _extract_georef(self, h5, instrument: str,
                        product: str) -> Optional[GeorefInfo]:
        """Build GeorefInfo from x/yCoordinates + projection dataset."""
        base = "/science/%s/%s/grids" % (instrument, product)
        warnings: List[str] = []

        for freq in PL.FREQUENCY_GROUPS:
            group_path = "%s/%s" % (base, freq)
            if group_path not in h5:
                continue
            group = h5[group_path]
            if "xCoordinates" not in group or "yCoordinates" not in group:
                warnings.append("%s: x/yCoordinates missing" % group_path)
                continue

            xs = np.asarray(group["xCoordinates"][()], dtype=np.float64).ravel()
            ys = np.asarray(group["yCoordinates"][()], dtype=np.float64).ravel()
            if xs.size < 2 or ys.size < 2:
                warnings.append("%s: degenerate coordinate arrays" % group_path)
                continue

            width, height = int(xs.size), int(ys.size)

            dx = float(group["xCoordinateSpacing"][()]) \
                if "xCoordinateSpacing" in group else float(abs(xs[1] - xs[0]))
            dy = float(group["yCoordinateSpacing"][()]) \
                if "yCoordinateSpacing" in group else float(abs(ys[1] - ys[0]))
            if dx <= 0 or dy <= 0:
                warnings.append("%s: non-positive pixel spacing" % group_path)
                continue

            # CF convention: coordinate variables are pixel centers.
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

        return GeorefInfo(
            crs_wkt="", crs_authid="",
            transform=[0, 1, 0, 0, 0, -1], width=0, height=0,
            bbox=(0, 0, 0, 0), is_valid=False,
            warnings=warnings or ["No frequency grid group found"])

    def _read_projection(self, group) -> Tuple[str, str]:
        """Read WKT and EPSG authid from the ``projection`` dataset."""
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
        for key in PL.IDENTIFICATION_FIELDS:
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
    def _to_product_type(product: str) -> Optional[ProductType]:
        try:
            return ProductType(product.upper())
        except ValueError:
            return None

    # ---------------------------------------------------------- read/close
    def read_window(self, handle: ProductHandle, layer_name: str,
                    window: Tuple[int, int, int, int]) -> np.ndarray:
        """Read a window using a cached open file handle (hyperslab read)."""
        h5 = getattr(handle, "_h5_file", None)
        if h5 is None:
            # Reopen lazily if the handle was transferred.
            h5 = h5py.File(handle.source_path, "r")
            handle._h5_file = h5

        layer = None
        for candidate in handle.layers:
            if candidate.name == layer_name or candidate.path.endswith(layer_name):
                layer = candidate
                break
        if layer is None:
            raise ValueError("Layer %r not found in %s" % (layer_name,
                                                            handle.source_path))

        dataset = h5.get(layer.path)
        if dataset is None:
            raise ValueError("Layer path %r missing in file" % layer.path)

        xoff, yoff, xsize, ysize = window
        if dataset.ndim == 2:
            out = dataset[yoff:yoff + ysize, xoff:xoff + xsize]
        elif dataset.ndim == 3:  # e.g. complex layers stored (len, wid, 2)
            out = dataset[yoff:yoff + ysize, xoff:xoff + xsize, ...]
        else:  # pragma: no cover - not expected for GCOV
            out = dataset[...]
        return np.asarray(out)

    def close(self, handle: ProductHandle):
        h5 = getattr(handle, "_h5_file", None)
        if h5 is not None:
            try:
                h5.close()
            except Exception:  # pragma: no cover
                pass
            handle._h5_file = None


# Register with a priority hint: A3 is the fallback after GDAL backends.
ReaderRegistry.register(A3H5PyReader)
