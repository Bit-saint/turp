"""Per-scene processing: window read -> calibration -> geocoding onto the site grid."""

from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
from pathlib import Path

import numpy as np
import rasterio
import requests
from rasterio.windows import Window

from .catalog import Scene
from .geocode import fit_local_mapping, resample
from .safe import Annotation, CalibrationLUT, NoiseLUT, calibrate, relative_orbit_from_manifest
from .site import Site

log = logging.getLogger(__name__)

GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tiff,.tif",
    GDAL_HTTP_MAX_RETRY="4",
    GDAL_HTTP_RETRY_DELAY="2",
    VSI_CACHE="FALSE",
)

POLS = {"DV": ("vv", "vh"), "SV": ("vv",), "DH": ("hh", "hv"), "SH": ("hh",)}
MARGIN = 4  # extra image pixels around the window for bilinear resampling


class SceneSkipped(Exception):
    pass


def _fetch(http: requests.Session, url: str) -> bytes:
    for attempt in range(4):
        try:
            r = http.get(url, timeout=120)
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            if attempt == 3:
                raise
    raise AssertionError


def process_scene(scene: Scene, site: Site, out_dir: Path, http: requests.Session | None = None,
                  noise_removal: bool = True) -> dict:
    """Produce ``<out_dir>/<product>.npz`` with sigma0 on the site grid. Returns metadata."""
    http = http or requests.Session()
    out_npz = out_dir / f"{scene.product}.npz"
    out_meta = out_dir / f"{scene.product}.json"
    if out_npz.exists() and out_meta.exists():
        return json.loads(out_meta.read_text())

    grid = site.grid()
    lon, lat = grid.lonlat()
    lon0, lat0 = site.centroid
    rel_orbit = relative_orbit_from_manifest(_fetch(http, scene.url + "manifest.safe"))

    pols = POLS[scene.polarisation]
    bands: dict[str, np.ndarray] = {}
    meta: dict = {}
    for pol in pols:
        ann = Annotation.parse(_fetch(http, f"{scene.url}annotation/iw-{pol}.xml"))
        mapping = fit_local_mapping(ann.grid, lon0, lat0, site_height=site.elevation_m)
        rows, cols = mapping(lon, lat)
        r0 = int(np.floor(np.nanmin(rows))) - MARGIN
        c0 = int(np.floor(np.nanmin(cols))) - MARGIN
        r1 = int(np.ceil(np.nanmax(rows))) + MARGIN
        c1 = int(np.ceil(np.nanmax(cols))) + MARGIN
        if r0 < 0 or c0 < 0 or r1 >= ann.n_lines or c1 >= ann.n_samples:
            raise SceneSkipped("site grid not fully inside the image")
        cal = CalibrationLUT.parse(_fetch(http, f"{scene.url}annotation/calibration/calibration-iw-{pol}.xml"))
        noise = NoiseLUT.parse(_fetch(http, f"{scene.url}annotation/calibration/noise-iw-{pol}.xml")) \
            if noise_removal else None
        with rasterio.Env(**GDAL_ENV):
            with rasterio.open(f"/vsicurl/{scene.url}measurement/iw-{pol}.tiff") as ds:
                dn = ds.read(1, window=Window(c0, r0, c1 - c0 + 1, r1 - r0 + 1))
        s0 = calibrate(dn, cal, noise, r0, c0)
        bands[pol] = resample(s0, rows - r0, cols - c0).astype(np.float32)
        if not meta:
            meta = dict(
                product=scene.product, mission=scene.mission, start=scene.start,
                abs_orbit=scene.abs_orbit, rel_orbit=rel_orbit, pass_direction=ann.pass_direction,
                incidence=round(mapping.incidence, 3), geoloc_rms_px=round(mapping.rms, 4),
                grid_height_m=round(mapping.grid_height, 1), range_shift_px=round(mapping.range_shift_px, 3),
                window=[r0, c0, r1, c1], pols=list(pols),
            )
    lot = site.masks()["lot"]
    nan_frac = float(np.mean(~np.isfinite(bands[pols[0]][lot])))
    meta["lot_nodata_frac"] = round(nan_frac, 4)
    if nan_frac > 0.02:
        raise SceneSkipped(f"{nan_frac:.0%} of the lot is no-data")
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_npz, **bands)
    out_meta.write_text(json.dumps(meta, indent=1))
    return meta


def process_all(scenes: list[Scene], site: Site, out_dir: str | Path, workers: int = 6,
                noise_removal: bool = True, progress=None) -> list[dict]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    skipped_path = out_dir / "skipped.json"
    skipped = json.loads(skipped_path.read_text()) if skipped_path.exists() else {}
    todo = [s for s in scenes if s.product not in skipped]
    results: list[dict] = []

    def run(scene):
        http = requests.Session()
        try:
            return process_scene(scene, site, out_dir, http, noise_removal), None
        except SceneSkipped as e:
            return None, (scene.product, str(e))
        except Exception as e:  # noqa: BLE001 - log and continue with the rest
            log.warning("failed %s: %s", scene.product, e)
            return None, None

    with cf.ThreadPoolExecutor(workers) as ex:
        for i, (meta, skip) in enumerate(ex.map(run, todo), 1):
            if meta:
                results.append(meta)
            if skip:
                skipped[skip[0]] = skip[1]
            if progress:
                progress(i, len(todo))
    skipped_path.write_text(json.dumps(skipped, indent=1))
    return sorted(results, key=lambda m: m["start"])


os.environ.setdefault("GDAL_HTTP_TIMEOUT", "60")
