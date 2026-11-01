"""Optical context: a cloud-free Sentinel-2 true-colour chip on the site grid.

Reads the public Sentinel-2 L2A COG archive (s3://sentinel-cogs) directly: the
MGRS tile is computed from the site location, recent months are listed and the
clearest scene that covers the site is used.
"""

from __future__ import annotations

import datetime as dt
import logging
import re

import numpy as np
import rasterio
import requests
from rasterio.warp import Resampling, reproject

from .site import Site

log = logging.getLogger(__name__)
BASE = "https://sentinel-cogs.s3.us-west-2.amazonaws.com"
_LAT_BANDS = "CDEFGHJKLMNPQRSTUVWX"
_ROW_LETTERS = "ABCDEFGHJKLMNPQRSTUV"


def mgrs_tile(lon: float, lat: float) -> tuple[int, str, str]:
    """(zone, latitude band, 100 km square) of the MGRS tile containing a point."""
    from pyproj import Transformer
    zone = int((lon + 180) // 6) + 1
    band = _LAT_BANDS[int((lat + 80) // 8)]
    e, n = Transformer.from_crs(4326, 32600 + zone if lat >= 0 else 32700 + zone, always_xy=True).transform(lon, lat)
    col_sets = ["ABCDEFGH", "JKLMNPQR", "STUVWXYZ"]
    col = col_sets[(zone - 1) % 3][int(e // 100_000) - 1]
    row_offset = 0 if zone % 2 else 5
    row = _ROW_LETTERS[(int(n // 100_000) + row_offset) % 20]
    return zone, band, col + row


def true_colour(site: Site, months_back: int = 6, max_cloud: float = 20.0,
                today: dt.date | None = None) -> tuple[np.ndarray, str] | None:
    """RGB uint8 array on the site grid, and the scene id; None if nothing clear is found."""
    http = requests.Session()
    zone, band, sq = mgrs_tile(*site.centroid)
    today = today or dt.date.today()
    grid = site.grid()
    lot_mask = site.masks()["lot_full"]
    candidates = []
    for k in range(months_back + 1):
        y, m = divmod(today.year * 12 + today.month - 1 - k, 12)
        prefix = f"sentinel-s2-l2a-cogs/{zone}/{band}/{sq}/{y}/{m + 1}/"
        try:
            txt = http.get(BASE, params={"prefix": prefix, "delimiter": "/"}, timeout=60).text
        except requests.RequestException:
            continue
        for p in re.findall(r"<Prefix>([^<]+_L2A/)</Prefix>", txt):
            name = p.rstrip("/").split("/")[-1]
            try:
                cc = http.get(f"{BASE}/{p}{name}.json", timeout=60).json()["properties"]["eo:cloud_cover"]
            except Exception:  # noqa: BLE001
                continue
            if cc <= max_cloud:
                candidates.append((cc, p, name))
    for cc, p, name in sorted(candidates):
        out = np.zeros((3, grid.height, grid.width), np.uint8)
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
            with rasterio.open(f"/vsicurl/{BASE}/{p}TCI.tif") as ds:
                for b in range(3):
                    reproject(rasterio.band(ds, b + 1), out[b], dst_transform=grid.transform,
                              dst_crs=grid.crs, resampling=Resampling.bilinear)
        rgb = np.moveaxis(out, 0, -1)
        lot_px = rgb[lot_mask]
        # usable if the lot has data and is not saturated (cloud) or black (outside swath)
        if lot_px.size and (lot_px.sum(1) > 0).mean() > 0.99 and np.median(lot_px.mean(1)) < 200:
            log.info("optical context: %s (%.1f%% cloud in tile)", name, cc)
            return rgb, name
    return None
