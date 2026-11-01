"""Sentinel-2 L2A time series on the site grid, for independent cross-checks.

Reads the B02/B03/B04 reflectance and the scene classification (SCL) bands
from the public ``sentinel-cogs`` archive, keeps acquisitions where the search
area is cloud-free, and caches the result per scene.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path

import numpy as np
import rasterio
import requests
from rasterio.warp import Resampling, reproject

from .s2context import BASE, mgrs_tile
from .site import Site

log = logging.getLogger(__name__)
CLOUDY_SCL = (3, 8, 9, 10)  # cloud shadow, cloud medium/high probability, thin cirrus


def _months(start: dt.date, end: dt.date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def s2_series(site: Site, start: dt.date, end: dt.date, cache_dir: str | Path, max_tile_cloud: float = 60.0,
              max_site_cloud: float = 0.02, search_mask: np.ndarray | None = None) -> list[dict]:
    """Cloud-free Sentinel-2 acquisitions: dicts with ``time`` (UTC) and ``refl`` (H, W, 3: R, G, B)."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    http = requests.Session()
    zone, band, sq = mgrs_tile(*site.centroid)
    grid = site.grid()
    mask = search_mask if search_mask is not None else site.masks()["lot_full"]
    out = []
    for y, m in _months(start, end):
        prefix = f"sentinel-s2-l2a-cogs/{zone}/{band}/{sq}/{y}/{m}/"
        txt = http.get(BASE, params={"prefix": prefix, "delimiter": "/"}, timeout=60).text
        for p in re.findall(r"<Prefix>([^<]+_L2A/)</Prefix>", txt):
            name = p.rstrip("/").split("/")[-1]
            f = cache / f"{name}.npz"
            if f.exists():
                z = np.load(f, allow_pickle=False)
                if z["ok"]:
                    out.append({"name": name, "time": dt.datetime.fromisoformat(str(z["time"])), "refl": z["refl"]})
                continue
            try:
                meta = http.get(f"{BASE}/{p}{name}.json", timeout=60).json()
            except Exception:  # noqa: BLE001
                continue
            t = dt.datetime.fromisoformat(meta["properties"]["datetime"].replace("Z", "+00:00"))
            if not (start <= t.date() <= end) or meta["properties"].get("eo:cloud_cover", 100) > max_tile_cloud:
                np.savez(f, ok=False, time=str(t), refl=np.zeros(0))
                continue
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
                scl = np.zeros((grid.height, grid.width), np.uint8)
                with rasterio.open(f"/vsicurl/{BASE}/{p}SCL.tif") as ds:
                    reproject(rasterio.band(ds, 1), scl, dst_transform=grid.transform, dst_crs=grid.crs,
                              resampling=Resampling.nearest)
                cloud = np.isin(scl[mask], CLOUDY_SCL).mean()
                nodata = (scl[mask] == 0).mean()
                if cloud > max_site_cloud or nodata > 0.01:
                    np.savez(f, ok=False, time=str(t), refl=np.zeros(0))
                    continue
                refl = np.zeros((3, grid.height, grid.width), np.float32)
                for k, b in enumerate(("B04", "B03", "B02")):
                    with rasterio.open(f"/vsicurl/{BASE}/{p}{b}.tif") as ds:
                        reproject(rasterio.band(ds, 1), refl[k], dst_transform=grid.transform, dst_crs=grid.crs,
                                  resampling=Resampling.bilinear)
            refl = np.moveaxis(refl / 10000.0, 0, -1)
            np.savez_compressed(f, ok=True, time=str(t), refl=refl)
            log.info("optical: %s cloud-free over the site", name)
            out.append({"name": name, "time": t, "refl": refl})
    return sorted(out, key=lambda d: d["time"])


def optical_presence(series: list[dict], positions, site: Site, radius_m: float = 25.0,
                     white: float = 0.45) -> "pd.DataFrame":
    """Per position and optical scene: is there a bright (white-painted) object?

    Aircraft fuselages are mostly white (reflectance ~0.5-0.8 in the visible)
    while apron concrete is ~0.15-0.35, so the brightest pixel within
    ``radius_m`` of the position is compared with ``white``.
    """
    import pandas as pd

    grid = site.grid()
    rows, cols = np.mgrid[0:grid.height, 0:grid.width]
    recs = []
    for _, p in positions.iterrows():
        c, r = (~grid.transform) @ (p.x, p.y)
        disk = np.hypot(rows + 0.5 - r, cols + 0.5 - c) <= radius_m / site.pixel_size
        for s in series:
            v = s["refl"][disk].min(axis=1)  # min over R,G,B: white is bright in all three
            recs.append({"position": p.position, "s2": s["name"], "time": s["time"],
                         "brightest": float(v.max()), "present": bool(v.max() >= white)})
    return pd.DataFrame(recs)
