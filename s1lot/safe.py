"""Parse Sentinel-1 GRD annotation and turn DNs into calibrated sigma0.

Only the small pieces of a SAFE product that are needed for a window around
the area of interest are used: the product annotation (geolocation grid,
orbit direction), the calibration LUT and the thermal-noise LUTs.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import numpy as np


def _floats(text: str) -> np.ndarray:
    return np.array(text.split(), dtype=np.float64)


@dataclass
class GeoGrid:
    """Geolocation tie points of a GRD product (line/pixel <-> lat/lon)."""

    line: np.ndarray
    pixel: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    height: np.ndarray
    incidence: np.ndarray

    @classmethod
    def from_annotation(cls, root: ET.Element) -> "GeoGrid":
        pts = root.findall("geolocationGrid/geolocationGridPointList/geolocationGridPoint")
        arr = np.array(
            [
                [float(p.findtext(k)) for k in ("line", "pixel", "latitude", "longitude", "height", "incidenceAngle")]
                for p in pts
            ]
        )
        return cls(*arr.T)


@dataclass
class Annotation:
    mission: str
    pass_direction: str  # "ascending" / "descending"
    start_time: str
    n_lines: int
    n_samples: int
    range_spacing: float
    azimuth_spacing: float
    grid: GeoGrid

    @classmethod
    def parse(cls, xml_text: str | bytes) -> "Annotation":
        root = ET.fromstring(xml_text)
        ii = root.find("imageAnnotation/imageInformation")
        return cls(
            mission=root.findtext("adsHeader/missionId"),
            pass_direction=root.findtext("generalAnnotation/productInformation/pass").lower(),
            start_time=root.findtext("adsHeader/startTime"),
            n_lines=int(ii.findtext("numberOfLines")),
            n_samples=int(ii.findtext("numberOfSamples")),
            range_spacing=float(ii.findtext("rangePixelSpacing")),
            azimuth_spacing=float(ii.findtext("azimuthPixelSpacing")),
            grid=GeoGrid.from_annotation(root),
        )


def _interp_vectors(lines: np.ndarray, pixels: list[np.ndarray], values: list[np.ndarray],
                    out_lines: np.ndarray, out_pixels: np.ndarray) -> np.ndarray:
    """Bilinear interpolation of LUT vectors given at sparse lines.

    Each vector i lives on line ``lines[i]`` and has its own pixel positions.
    First interpolate every vector along pixels, then along lines.
    """
    per_vec = np.stack([np.interp(out_pixels, p, v) for p, v in zip(pixels, values)])  # (nvec, npix)
    out = np.empty((out_lines.size, out_pixels.size))
    idx = np.clip(np.searchsorted(lines, out_lines, side="right") - 1, 0, len(lines) - 2)
    l0, l1 = lines[idx], lines[idx + 1]
    w = np.clip((out_lines - l0) / np.where(l1 > l0, l1 - l0, 1), 0, 1)[:, None]
    out[:] = per_vec[idx] * (1 - w) + per_vec[idx + 1] * w
    return out


@dataclass
class CalibrationLUT:
    lines: np.ndarray
    pixels: list = field(repr=False)
    sigma: list = field(repr=False)

    @classmethod
    def parse(cls, xml_text: str | bytes) -> "CalibrationLUT":
        root = ET.fromstring(xml_text)
        vecs = root.findall("calibrationVectorList/calibrationVector")
        return cls(
            lines=np.array([float(v.findtext("line")) for v in vecs]),
            pixels=[_floats(v.findtext("pixel")) for v in vecs],
            sigma=[_floats(v.findtext("sigmaNought")) for v in vecs],
        )

    def sigma_lut(self, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
        return _interp_vectors(self.lines, self.pixels, self.sigma, rows, cols)


@dataclass
class NoiseLUT:
    """Thermal noise LUT (range vectors x azimuth blocks, IPF >= 2.9)."""

    lines: np.ndarray
    pixels: list = field(repr=False)
    values: list = field(repr=False)
    az_blocks: list = field(default_factory=list, repr=False)

    @classmethod
    def parse(cls, xml_text: str | bytes) -> "NoiseLUT":
        root = ET.fromstring(xml_text)
        rv = root.findall("noiseRangeVectorList/noiseRangeVector")
        if not rv:  # very old products (IPF < 2.9)
            rv = root.findall("noiseVectorList/noiseVector")
            lut_tag = "noiseLut"
        else:
            lut_tag = "noiseRangeLut"
        blocks = []
        for b in root.findall("noiseAzimuthVectorList/noiseAzimuthVector"):
            blocks.append(
                dict(
                    l0=int(b.findtext("firstAzimuthLine")),
                    l1=int(b.findtext("lastAzimuthLine")),
                    p0=int(b.findtext("firstRangeSample")),
                    p1=int(b.findtext("lastRangeSample")),
                    line=_floats(b.findtext("line")),
                    lut=_floats(b.findtext("noiseAzimuthLut")),
                )
            )
        return cls(
            lines=np.array([float(v.findtext("line")) for v in rv]),
            pixels=[_floats(v.findtext("pixel")) for v in rv],
            values=[_floats(v.findtext(lut_tag)) for v in rv],
            az_blocks=blocks,
        )

    def noise(self, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
        out = _interp_vectors(self.lines, self.pixels, self.values, rows, cols)
        if self.az_blocks:
            az = np.ones_like(out)
            for b in self.az_blocks:
                rm = (rows >= b["l0"]) & (rows <= b["l1"])
                cm = (cols >= b["p0"]) & (cols <= b["p1"])
                if rm.any() and cm.any():
                    vals = np.interp(rows[rm], b["line"], b["lut"]) if b["line"].size > 1 else np.full(rm.sum(), b["lut"][0])
                    az[np.ix_(rm, cm)] = vals[:, None]
            out = out * az
        return out


def calibrate(dn: np.ndarray, cal: CalibrationLUT, noise: NoiseLUT | None,
              row0: int, col0: int, floor: float = 1e-5) -> np.ndarray:
    """DN window -> sigma0 (linear), thermal-noise corrected.

    ``row0``/``col0`` are the image coordinates of the window's top-left pixel.
    Pixels that are no-data (DN == 0) become NaN.
    """
    rows = np.arange(dn.shape[0]) + row0
    cols = np.arange(dn.shape[1]) + col0
    power = dn.astype(np.float64) ** 2
    if noise is not None:
        power = power - noise.noise(rows, cols)
    a = cal.sigma_lut(rows, cols)
    s0 = np.maximum(power / a**2, floor)
    s0[dn == 0] = np.nan
    return s0


PRODUCT_RE = re.compile(
    r"(?P<mission>S1[A-D])_(?P<mode>IW|EW|SM)_GRD(?P<res>[HM])_1S(?P<pol>DV|SV|DH|SH)_"
    r"(?P<start>\d{8}T\d{6})_(?P<stop>\d{8}T\d{6})_(?P<abs_orbit>\d{6})_(?P<take>[0-9A-F]{6})_(?P<uid>[0-9A-F]{4})"
)


def parse_product_name(name: str) -> dict:
    m = PRODUCT_RE.search(name)
    if not m:
        raise ValueError(f"not a Sentinel-1 GRD product name: {name}")
    return m.groupdict()


def relative_orbit_from_manifest(xml_text: str | bytes) -> int | None:
    m = re.search(rb'relativeOrbitNumber type="start">(\d+)<' if isinstance(xml_text, bytes)
                  else r'relativeOrbitNumber type="start">(\d+)<', xml_text)
    return int(m.group(1)) if m else None
