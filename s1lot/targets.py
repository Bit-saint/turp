"""Individual target detection and appearance-over-time tracking.

Large metal objects such as aircraft, trucks or containers are strong radar
reflectors. Against smooth concrete or asphalt, which look dark, they appear
as compact bright blobs. Per orbit track:

1. **Background**: per pixel, a low percentile over time of sigma0 (VV + VH).
   That is the "empty" look of each pixel. Fixed structures (buildings, jet
   bridges, masts) are bright in the background too, so they cancel out.
2. **Detection**: a pixel is a candidate when it is ``ratio_db`` above its
   background *and* brighter than ``min_db`` in absolute terms. Connected
   candidates of at least ``min_pixels`` inside the search area form a target.
3. **Positions**: detections from all scenes are grouped spatially. A
   position that holds targets in at least ``min_hits`` scenes is a recurring
   target position (for example an aircraft stand).
4. **Presence**: for every position and scene, the strongest background ratio
   within ``radius_m`` decides present / absent. Together these give the
   appearance history of each position.

False-alarm control: the same detector runs on a control area where no
target can be. By default that is the dark (natural-surface) part of the
reference ring; better, ``targets.control_area`` names vegetation polygons
(``s1lot.overture.land_cover``). Its detection density per km² is reported
next to the density in the search area.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy import ndimage

from .metrics import _db, load_chips, scene_table
from .site import Site


@dataclass
class TargetParams:
    ratio_db: float = 7.0         # brighter than the empty background by this much
    min_db: float = -2.0          # and at least this bright (VV+VH sigma0, dB)
    min_pixels: int = 2           # connected pixels per target
    background_pct: float = 10.0  # percentile over time = empty background
    search_buffer_m: float = 20.0  # grow the search area (wings/tails overhang polygons)
    cluster_m: float = 40.0       # minimum spacing between recurring positions
    radius_m: float = 25.0        # presence test radius around a position
    min_hits_frac: float = 0.05   # a position needs targets in >= this share of scenes
    label_max_m: float = 120.0    # label a position with the nearest label point within this
    control_max_db: float = -6.0  # control area: natural surfaces only (background darker than this)
    control_exclude_m: float = 60.0  # buffer around `control_exclude` geometries (e.g. taxiways)
    clutter_factor: float = 3.0   # flag scenes whose control density exceeds this x the median

    @classmethod
    def from_site(cls, site: Site) -> "TargetParams":
        cfg = {k: v for k, v in (site.targets or {}).items() if k in cls.__dataclass_fields__}
        return cls(**cfg)


@dataclass
class TargetResult:
    scenes: pd.DataFrame        # one row per scene: counts, false-alarm density
    detections: pd.DataFrame    # one row per detected target
    positions: pd.DataFrame     # recurring positions
    presence: pd.DataFrame      # positions x scenes (bool), columns = product
    score: pd.DataFrame         # positions x scenes, max ratio (dB) within radius
    background: dict = field(default_factory=dict)  # track -> background (dB)
    hits_map: np.ndarray | None = None              # detections per pixel (all scenes)
    search_mask: np.ndarray | None = None
    params: TargetParams | None = None

    def summary(self) -> dict:
        s = self.scenes
        out = {
            "n_scenes": int(len(s)),
            "n_clutter_flagged": int(s.clutter_flag.sum()),
            "n_detections": int(len(self.detections)),
            "n_positions": int(len(self.positions)),
            "targets_per_scene_median": float(s.n_targets.median()),
            "search_density_per_km2": round(float(s.search_density.median()), 2),
            "control_density_per_km2": round(float(s.control_density.median()), 3),
            "params": self.params.__dict__ if self.params else {},
        }
        if len(self.positions):
            out["mean_position_occupancy"] = round(float(self.positions.occupancy.mean()), 3)
        by = s.groupby("pass_slot").n_targets.median()
        out["targets_per_scene_by_pass"] = {k: float(v) for k, v in by.items()}
        return out


def _objects(cand: np.ndarray, power: np.ndarray, ratio_db: np.ndarray, min_pixels: int):
    lab, n = ndimage.label(cand, structure=np.ones((3, 3)))
    if n == 0:
        return lab, []
    idx = np.arange(1, n + 1)
    sizes = ndimage.sum_labels(np.ones_like(power), lab, idx)
    keep = idx[sizes >= min_pixels]
    objs = []
    for i in keep:
        rr, cc = np.nonzero(lab == i)
        w = power[rr, cc]
        objs.append(dict(row=float((rr * w).sum() / w.sum()), col=float((cc * w).sum() / w.sum()),
                         n_px=int(rr.size), peak_db=float(_db(w.max())), sum_db=float(_db(w.sum())),
                         peak_ratio_db=float(np.nanmax(ratio_db[rr, cc]))))
    return lab, objs


def _find_positions(det: pd.DataFrame, hits: np.ndarray, grid, params: TargetParams, n_scenes: int) -> pd.DataFrame:
    """Recurring positions = local maxima of the (smoothed) detection-density map.

    Peak finding keeps neighbouring stands apart, where linking detections into
    chains would merge a whole row of stands into one cluster.
    """
    ps = grid.transform.a
    dens = ndimage.gaussian_filter(hits.astype(float), sigma=max(params.radius_m / ps / 2, 0.8))
    size = int(2 * round(params.cluster_m / ps) + 1)
    peaks = (dens == ndimage.maximum_filter(dens, size=size, mode="constant")) & (dens > 0)
    rr, cc = np.nonzero(peaks)
    order = np.argsort(-dens[rr, cc])
    min_hits = max(2, params.min_hits_frac * n_scenes)
    taken: list[tuple[float, float]] = []
    recs = []
    for k in order:
        x, y = grid.transform @ (cc[k] + 0.5, rr[k] + 0.5)
        if any(np.hypot(x - tx, y - ty) < params.cluster_m for tx, ty in taken):
            continue
        near = np.hypot(det.x - x, det.y - y) <= params.radius_m
        n_hits = det.loc[near, "product"].nunique()
        if n_hits < min_hits:
            continue
        taken.append((x, y))
        recs.append(dict(x=float(det.x[near].median()), y=float(det.y[near].median()), n_hits=int(n_hits),
                         peak_db=float(det.peak_db[near].median()), n_px=float(det.n_px[near].median())))
    pos = pd.DataFrame(recs, columns=["x", "y", "n_hits", "peak_db", "n_px"])
    pos = pos.sort_values(["y", "x"], ascending=[False, True]).reset_index(drop=True)
    pos.insert(0, "position", [f"P{i + 1:02d}" for i in range(len(pos))])
    return pos


def _cluster(points: np.ndarray, radius: float) -> np.ndarray:
    """Single-linkage clustering of 2-D points (labels), via a KD-tree."""
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree

    if len(points) == 0:
        return np.zeros(0, int)
    pairs = cKDTree(points).query_pairs(radius, output_type="ndarray")
    from scipy.sparse import coo_matrix
    m = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(points),) * 2)
    return connected_components(m, directed=False)[1]


def _labels(site: Site) -> list[tuple[str, float, float]]:
    spec = (site.targets or {}).get("labels")
    if not spec:
        return []
    fc = json.loads((site.base_dir / spec).read_text()) if isinstance(spec, str) else spec
    t = Transformer.from_crs(4326, site.crs, always_xy=True)
    out = []
    for f in fc.get("features", []):
        g = f["geometry"]
        if g["type"] != "Point":
            continue
        p = f.get("properties", {})
        name = p.get("ref") or p.get("name")
        if name:
            x, y = t.transform(*g["coordinates"])
            out.append((str(name), x, y))
    return out


def detect_targets(site: Site, chip_dir: str | Path, params: TargetParams | None = None) -> TargetResult:
    params = params or TargetParams.from_site(site)
    metas, arrays = load_chips(chip_dir)
    if not metas:
        raise RuntimeError(f"no processed scenes in {chip_dir}")
    order = np.argsort([m["start"] for m in metas], kind="stable")
    metas, arrays = [metas[i] for i in order], [arrays[i] for i in order]
    df = scene_table(metas, site)
    grid = site.grid()
    ps = site.pixel_size
    lot_utm = site.to_utm(site.lot)
    search = grid.rasterize(lot_utm.buffer(params.search_buffer_m))
    masks = site.masks()
    km2 = ps * ps / 1e6

    power = np.stack([a["vv"] + a.get("vh", 0) for a in arrays]).astype(np.float64)
    ratio = np.full_like(power, np.nan)
    background = {}
    for track, idx in df.groupby("track").groups.items():
        idx = np.asarray(idx)
        bg = np.nanpercentile(power[idx], params.background_pct, axis=0)
        background[track] = _db(bg)
        ratio[idx] = _db(power[idx] / bg)

    # Control area for false alarms: natural surfaces around the search area where no
    # target can be (dark background, away from buildings, roads and `control_exclude`).
    natural = np.nanmedian(np.stack(list(background.values())), axis=0) < params.control_max_db
    area_spec = (site.targets or {}).get("control_area")
    if area_spec:  # e.g. vegetation polygons; anywhere on the grid, away from the search area
        area = grid.rasterize(site.to_utm(site.load_geometry(area_spec)))
        control = area & natural & ~grid.rasterize(lot_utm.buffer(params.control_exclude_m))
    else:
        control = masks["ref"] & ~search & natural
    excl = (site.targets or {}).get("control_exclude")
    if excl:
        control &= ~grid.rasterize(site.to_utm(site.load_geometry(excl)).buffer(params.control_exclude_m))

    det_rows, hits = [], np.zeros(search.shape, int)
    n_targets, search_density, control_density = [], [], []
    for i, row in df.iterrows():
        cand = (ratio[i] >= params.ratio_db) & (_db(power[i]) >= params.min_db)
        lab, objs = _objects(cand & search, power[i], ratio[i], params.min_pixels)
        _, cobjs = _objects(cand & control, power[i], ratio[i], params.min_pixels)
        n_targets.append(len(objs))
        search_density.append(len(objs) / (search.sum() * km2))
        control_density.append(len(cobjs) / max(control.sum() * km2, 1e-9))
        for o in objs:
            hits[int(round(o["row"])), int(round(o["col"]))] += 1
            det_rows.append({"product": row["product"], "local_time": row.local_time, "track": row.track,
                             "pass_slot": row.pass_slot, **o})
    df["n_targets"] = n_targets
    df["search_density"] = search_density
    df["control_density"] = control_density
    med = max(float(np.median(control_density)), 1.0 / max(control.sum() * km2, 1e-9))
    df["clutter_flag"] = df.control_density > params.clutter_factor * med
    det = pd.DataFrame(det_rows)

    # ---- recurring positions ----
    tr = grid.transform
    to_ll = Transformer.from_crs(site.crs, 4326, always_xy=True)
    positions = pd.DataFrame(columns=["position", "x", "y", "lon", "lat", "n_hits"])
    if len(det):
        det["x"], det["y"] = tr @ (det.col.values + 0.5, det.row.values + 0.5)
        det["lon"], det["lat"] = to_ll.transform(det.x.values, det.y.values)
        positions = _find_positions(det, hits, grid, params, len(df))
        if len(positions):
            positions["lon"], positions["lat"] = to_ll.transform(positions.x.values, positions.y.values)
            d = np.hypot(det.x.values[:, None] - positions.x.values[None], det.y.values[:, None] - positions.y.values[None])
            j = d.argmin(1)
            det["position"] = np.where(d[np.arange(len(det)), j] <= params.cluster_m,
                                       positions.position.values[j], None)

    # labels (nearest gate / stand reference)
    labels = _labels(site)
    if labels and len(positions):
        lx = np.array([l[1] for l in labels]); ly = np.array([l[2] for l in labels])
        names, dists = [], []
        for x, y in zip(positions.x, positions.y):
            d = np.hypot(lx - x, ly - y)
            j = int(np.argmin(d))
            names.append(labels[j][0] if d[j] <= params.label_max_m else None)
            dists.append(round(float(d[j])))
        positions["label"], positions["label_dist_m"] = names, dists

    # ---- presence per position and scene ----
    rows_, cols_ = np.mgrid[0:grid.height, 0:grid.width]
    score = pd.DataFrame(index=positions.position if len(positions) else [], columns=df["product"], dtype=float)
    for _, p in positions.iterrows():
        c, r = (~tr) @ (p.x, p.y)
        disk = np.hypot(rows_ + 0.5 - r, cols_ + 0.5 - c) <= params.radius_m / ps
        bright = _db(power[:, disk]) >= params.min_db
        vals = np.where(bright, ratio[:, disk], np.nan)
        with np.errstate(all="ignore"):
            score.loc[p.position] = np.nanmax(np.where(np.isfinite(vals), vals, -99), axis=1)
    presence = score >= params.ratio_db
    if len(positions):
        positions["occupancy"] = presence.mean(axis=1).values
        positions["n_present"] = presence.sum(axis=1).values
        positions["appearances"] = [int(((p.astype(int).diff() == 1).sum()) + int(p.iloc[0]))
                                    for _, p in presence.astype(int).iterrows()]
        for slot in ("morning", "evening"):
            cols = df.loc[df.pass_slot == slot, "product"]
            if len(cols):
                positions[f"occupancy_{slot}"] = presence[cols].mean(axis=1).values
    res = TargetResult(df, det, positions, presence, score, background, hits, search, params)
    res.control_mask = control
    return res


def episodes(presence: pd.DataFrame, times: pd.Series, min_days: float = 10, min_frac: float = 0.75,
             max_gap: int = 1) -> pd.DataFrame:
    """Long stays: runs of presence per position, tolerating ``max_gap`` missed scenes.

    ``times`` gives the acquisition time of each presence column (same order).
    A run is kept if it spans at least ``min_days`` and the target is detected
    in at least ``min_frac`` of the scenes inside it.
    """
    t = pd.Series(pd.to_datetime(times)).reset_index(drop=True)
    recs = []
    for pos, row in presence.iterrows():
        v = row.values.astype(bool)
        i, n = 0, len(v)
        while i < n:
            if not v[i]:
                i += 1
                continue
            last, j = i, i
            while j + 1 < n and v[j + 1: j + 2 + max_gap].any():
                j += 1
                if v[j]:
                    last = j
            frac = v[i:last + 1].mean()
            days = (t[last] - t[i]).total_seconds() / 86400
            if days >= min_days and frac >= min_frac:
                recs.append({"position": pos, "start": t[i], "end": t[last], "days": round(days, 1),
                             "scenes": int(last - i + 1), "detected_frac": round(float(frac), 2)})
            i = last + 1
    return pd.DataFrame(recs, columns=["position", "start", "end", "days", "scenes", "detected_frac"])


# ------------------------------------------------------------------ outputs
def write_target_report(res: TargetResult, site: Site, out_dir: str | Path, chip_dir: str | Path,
                        rgb: np.ndarray | None = None, rgb_name: str | None = None,
                        optical: pd.DataFrame | None = None) -> Path:
    from . import target_report
    return target_report.write(res, site, Path(out_dir), Path(chip_dir), rgb, rgb_name, optical)
