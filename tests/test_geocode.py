import numpy as np

from s1lot.geocode import fit_local_mapping, resample
from s1lot.safe import GeoGrid


def _synthetic_grid(lon0=8.0, lat0=50.0):
    lines, pixels = np.meshgrid(np.arange(0, 20000, 1000.0), np.arange(0, 26000, 1300.0), indexing="ij")
    lines, pixels = lines.ravel(), pixels.ravel()
    rng = np.random.default_rng(1)
    height = rng.uniform(80, 400, lines.size)
    # ground: 10 m pixels, rotated 12 deg; height shifts the apparent range position by 1.2 m/m
    x = pixels * 10.0 + 1.2 * height
    y = lines * 10.0
    th = np.radians(12)
    e = x * np.cos(th) - y * np.sin(th)
    n = x * np.sin(th) + y * np.cos(th)
    lat = lat0 + n / 111_195.0
    lon = lon0 + e / (111_195.0 * np.cos(np.radians(lat0)))
    return GeoGrid(lines, pixels, lat, lon, height, np.full(lines.size, 39.0))


def test_fit_recovers_height_dependent_mapping():
    g = _synthetic_grid()
    i = 205
    m = fit_local_mapping(g, g.lon[i], g.lat[i], site_height=g.height[i])
    line, pix = m(g.lon[i], g.lat[i])
    assert abs(line - g.line[i]) < 0.5 and abs(pix - g.pixel[i]) < 0.5
    # ~-0.12 px per metre of height (1.2 m ground shift / 10 m pixels)
    assert abs(m.coef_pixel[-1] / 1000 + 0.12) < 0.01


def test_resample_bilinear_and_nan():
    img = np.arange(16, dtype=float).reshape(4, 4)
    img[0, 0] = np.nan
    out = resample(img, np.array([1.5, 0.2, 10.0]), np.array([1.5, 0.2, 1.0]))
    assert out[0] == 7.5
    assert np.isnan(out[1])  # touches the NaN pixel
    assert np.isnan(out[2])  # outside
