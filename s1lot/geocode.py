"""Map a regular UTM grid onto GRD image coordinates and resample.

GRD products are in radar geometry (lines = azimuth, pixels = ground range),
with a sparse geolocation grid of tie points. Around a small site a
second-order polynomial fitted to the nearest tie points maps lon/lat to
line/pixel with sub-pixel accuracy.

The tie points lie on the annotation's coarse terrain model, so their heights
vary; height is therefore a variable of the fit. The site is mapped at its
true ellipsoidal height when known, which removes the foreshortening shift
along range (about dh / tan(incidence)).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pyproj import Geod
from scipy.ndimage import map_coordinates

from .safe import GeoGrid

_GEOD = Geod(ellps="WGS84")


def _design(e: np.ndarray, n: np.ndarray, h: np.ndarray) -> np.ndarray:
    # quadratic in plane coordinates + linear in height (the height term absorbs
    # the range displacement of tie points that sit on different terrain heights)
    return np.stack([np.ones_like(e), e, n, e * e, e * n, n * n, h], axis=-1)


@dataclass
class LocalMapping:
    lon0: float
    lat0: float
    coef_line: np.ndarray
    coef_pixel: np.ndarray
    height: float          # height (m, ellipsoidal) at which the site is mapped
    grid_height: float     # tie-point terrain height near the site
    incidence: float       # incidence angle at the site (deg)
    rms: float             # fit residual at the tie points (pixels)

    def _en(self, lon, lat):
        # local tangent plane in km (equirectangular is plenty for a few tens of km)
        k = np.pi / 180 * 6371.0
        return (np.asarray(lon) - self.lon0) * k * np.cos(np.radians(self.lat0)), (np.asarray(lat) - self.lat0) * k

    def __call__(self, lon, lat, height: float | None = None):
        e, n = self._en(lon, lat)
        h = np.full_like(e, (self.height if height is None else height) / 1000.0)
        d = _design(e, n, h)
        return d @ self.coef_line, d @ self.coef_pixel

    @property
    def range_shift_px(self) -> float:
        """Pixel shift caused by using the site height instead of the tie-point height."""
        return float(self.coef_pixel[-1] * (self.height - self.grid_height) / 1000.0)


def fit_local_mapping(grid: GeoGrid, lon0: float, lat0: float, n_points: int = 24,
                      site_height: float | None = None) -> LocalMapping:
    """Fit lon/lat/height -> line/pixel on the tie points nearest to the site.

    If ``site_height`` (ellipsoidal metres) is None, the site is mapped at the
    distance-weighted height of the surrounding tie points.
    """
    _, _, dist = _GEOD.inv(np.full(grid.lon.size, lon0), np.full(grid.lat.size, lat0), grid.lon, grid.lat)
    idx = np.argsort(dist)[:n_points]
    m = LocalMapping(lon0, lat0, np.zeros(7), np.zeros(7), 0.0, 0.0, 0.0, 0.0)
    e, n = m._en(grid.lon[idx], grid.lat[idx])
    d = _design(e, n, grid.height[idx] / 1000.0)
    cl, *_ = np.linalg.lstsq(d, grid.line[idx], rcond=None)
    cp, *_ = np.linalg.lstsq(d, grid.pixel[idx], rcond=None)
    res = np.hypot(d @ cl - grid.line[idx], d @ cp - grid.pixel[idx])
    w = 1 / np.maximum(dist[idx], 1.0) ** 2
    m.coef_line, m.coef_pixel = cl, cp
    m.rms = float(np.sqrt(np.mean(res**2)))
    m.grid_height = float(np.sum(grid.height[idx] * w) / w.sum())
    m.height = m.grid_height if site_height is None else float(site_height)
    m.incidence = float(np.sum(grid.incidence[idx] * w) / w.sum())
    return m


def resample(image: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """Bilinear resampling of ``image`` at fractional (row, col); NaN outside."""
    valid = np.isfinite(image)
    filled = np.where(valid, image, 0.0)
    out = map_coordinates(filled, [rows, cols], order=1, mode="constant", cval=np.nan)
    wts = map_coordinates(valid.astype(float), [rows, cols], order=1, mode="constant", cval=0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(wts > 0.99, out / np.where(wts > 0, wts, 1), np.nan)
    return out
