"""Turn the per-scene sigma0 chips into parking-activity time series and maps.

Physics: an empty asphalt lot is a smooth surface that reflects C-band radar
away from the sensor, so it looks dark. Parked cars are metal boxes that form
dihedral (double-bounce) and multiple-bounce reflectors with the ground, so a
fuller lot is brighter. Multiple bounces also depolarise, which is why the
cross-polarised channel (VH) is the most sensitive and least weather-dependent
channel for cars. Absolute brightness depends on the viewing geometry, which
differs between orbit tracks, so every comparison is made *within a track*.

Scene-level metric (primary):
* ``lot_<pol>_db``: median sigma0 over the lot pixels (very stable: hundreds of
  pixels, ~0.4 dB scene-to-scene noise);
* ``excess_db``: lot median minus the track's empty baseline (its
  ``baseline_pct`` percentile over time);
* ``activity``: excess scaled so that 0 = the track's empty baseline and
  100 = the 95th percentile of excess over all scenes.

Pixel-level product (secondary, for maps): per track and pixel an empty
baseline (low percentile over time of a speckle-filtered image); a pixel is
*occupied* when it is ``threshold_db`` above it. ``occupied_frac`` per scene
and the per-pixel occupied *frequency* show which parts of the lot fill up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy import stats
from scipy.ndimage import uniform_filter

from .site import Site

DAYTYPE_ORDER = ["Mon-Fri", "Sat", "Sun/holiday"]


def _db(x):
    with np.errstate(divide="ignore", invalid="ignore"):
        return 10 * np.log10(x)


def boxcar(img: np.ndarray, size: int = 3) -> np.ndarray:
    """NaN-aware moving average in linear power (light speckle reduction)."""
    valid = np.isfinite(img)
    s = uniform_filter(np.where(valid, img, 0.0), size, mode="nearest")
    w = uniform_filter(valid.astype(float), size, mode="nearest")
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(w > 0, s / w, np.nan)


def _median_db(img: np.ndarray, mask: np.ndarray) -> float:
    v = img[mask]
    v = v[np.isfinite(v)]
    return float(_db(np.median(v))) if v.size else np.nan


@dataclass
class Analysis:
    scenes: pd.DataFrame                 # one row per acquisition
    baselines: dict[str, np.ndarray]     # track -> per-pixel empty baseline (dB, VV)
    frequency: dict[str, np.ndarray]     # track -> per-pixel occupied frequency (0..1)
    mean_db: dict[str, np.ndarray]       # track -> temporal mean VV (dB)
    masks: dict[str, np.ndarray]
    params: dict

    def summary(self) -> dict:
        df = self.scenes
        out = {"n_scenes": int(len(df)), "n_weather_flagged": int(df.weather_flag.sum()), "first": str(df.local_time.min()), "last": str(df.local_time.max()),
               "tracks": df.groupby("track").size().to_dict(), "params": self.params}
        tab = df.pivot_table(index="daytype", columns="pass_slot", values="activity", aggfunc=["mean", "count"])
        out["activity_by_daytype"] = {f"{a}|{b}|{c}": (None if pd.isna(v) else round(float(v), 2))
                                      for (a, b, c), v in tab.stack(future_stack=True).stack(future_stack=True)
                                      .items()} if not tab.empty else {}
        ev = df[df.pass_slot == "evening"]
        open_ = ev[ev.daytype != "Sun/holiday"].activity.dropna()
        closed = ev[ev.daytype == "Sun/holiday"].activity.dropna()
        if len(open_) >= 3 and len(closed) >= 3:
            u = stats.mannwhitneyu(open_, closed, alternative="greater")
            out["evening_open_vs_closed"] = {
                "open_median": round(float(open_.median()), 1), "closed_median": round(float(closed.median()), 1),
                "n_open": int(len(open_)), "n_closed": int(len(closed)), "mannwhitney_p": float(u.pvalue)}
        return out


def load_chips(chip_dir: str | Path) -> tuple[list[dict], list[dict[str, np.ndarray]]]:
    metas, arrays = [], []
    for jf in sorted(Path(chip_dir).glob("S1*.json")):
        npz = jf.with_suffix(".npz")
        if npz.exists():
            metas.append(json.loads(jf.read_text()))
            with np.load(npz) as z:
                arrays.append({k: z[k] for k in z.files})
    return metas, arrays


def _daytype(local: pd.Timestamp, hol) -> str:
    if hol is not None and local.date() in hol:
        return "Sun/holiday"
    return {5: "Sat", 6: "Sun/holiday"}.get(local.weekday(), "Mon-Fri")


def _holidays(site: Site, years):
    if not site.country:
        return None
    try:
        import holidays
    except ImportError:
        return None
    return holidays.country_holidays(site.country, subdiv=site.subdivision, years=sorted(years))


def scene_table(metas: list[dict], site: Site) -> pd.DataFrame:
    """Scene metadata with local time, track id, pass slot and day type."""
    df = pd.DataFrame(metas)
    df["time_utc"] = pd.to_datetime(df.start, utc=True)
    df["local_time"] = df.time_utc.dt.tz_convert(ZoneInfo(site.timezone))
    df["track"] = [f"{'A' if p.startswith('asc') else 'D'}{r:03d}" for p, r in zip(df.pass_direction, df.rel_orbit)]
    df["pass_slot"] = np.where(df.local_time.dt.hour < 12, "morning", "evening")
    hol = _holidays(site, set(df.local_time.dt.year))
    df["weekday"] = df.local_time.dt.day_name().str[:3]
    df["daytype"] = [_daytype(t, hol) for t in df.local_time]
    df["holiday"] = [(hol.get(t.date()) if hol is not None else None) for t in df.local_time]
    return df


def analyse(site: Site, chip_dir: str | Path, pol: str = "vh", threshold_db: float = 3.0,
            baseline_pct: float = 10.0, boxcar_size: int = 5, min_track_scenes: int = 8,
            weather_flag_db: float = 1.0, exclude_months: tuple[str, ...] = ()) -> Analysis:
    metas, arrays = load_chips(chip_dir)
    if not metas:
        raise RuntimeError(f"no processed scenes in {chip_dir}")
    masks = site.masks()
    lot, ref = masks["lot"], masks["ref"]
    df = scene_table(metas, site)
    if exclude_months:
        keep = (~df.local_time.dt.strftime("%Y-%m").isin(exclude_months)).to_numpy()
        df, arrays = df[keep].reset_index(drop=True), [a for a, k in zip(arrays, keep) if k]
    if pol not in arrays[0]:
        raise ValueError(f"polarisation {pol!r} not available in the processed scenes")

    for p in ("vv", "vh"):
        df[f"lot_{p}_db"] = [_median_db(a[p], lot) if p in a else np.nan for a in arrays]
        df[f"ref_{p}_db"] = [_median_db(a[p], ref) if p in a else np.nan for a in arrays]
    df["contrast_db"] = df[f"lot_{pol}_db"] - df[f"ref_{pol}_db"]

    smooth_db = np.stack([_db(boxcar(a[pol], boxcar_size)) for a in arrays])
    df["excess_db"] = np.nan
    df["occupied_frac"] = np.nan
    df["low_confidence"] = False
    baselines, freq, mean_db = {}, {}, {}
    for track, idx in df.groupby("track").groups.items():
        idx = np.asarray(idx)
        lvl = df.loc[idx, f"lot_{pol}_db"]
        df.loc[idx, "excess_db"] = lvl - np.nanpercentile(lvl, baseline_pct)
        stack = smooth_db[idx]
        base = np.nanpercentile(stack, baseline_pct, axis=0)
        occ = (stack - base) > threshold_db
        baselines[track] = base
        freq[track] = occ.mean(0)
        mean_db[track] = _db(np.nanmean(10 ** (stack / 10), 0))
        df.loc[idx, "occupied_frac"] = occ[:, lot].mean(1)
        df.loc[idx, "low_confidence"] = len(idx) < min_track_scenes

    # Scene-wide changes (rain, frost, snow, soil moisture) show up in the surroundings
    # as well; flag scenes whose reference ring departs from its usual level.
    df["ring_db"] = df[f"ref_{pol}_db"] - df.groupby("track")[f"ref_{pol}_db"].transform("median")
    df["weather_flag"] = df.ring_db.abs() > weather_flag_db

    scale = np.nanpercentile(df.excess_db, 95)
    df["activity"] = 100 * df.excess_db / scale if scale > 0 else np.nan

    # anomalies: compare each scene with scenes of the same pass slot and day type
    grp = df.groupby(["pass_slot", "daytype"]).activity
    df["expected"] = grp.transform("median")
    mad = grp.transform(lambda s: stats.median_abs_deviation(s, scale="normal"))
    spread = np.maximum(mad.fillna(0), 10.0)  # floor in activity points
    df["anomaly_z"] = (df.activity - df.expected) / spread
    df = df.sort_values("time_utc").reset_index(drop=True)

    params = dict(pol=pol, threshold_db=threshold_db, baseline_pct=baseline_pct, boxcar=boxcar_size,
                  activity_scale_db=round(float(scale), 3), weather_flag_db=weather_flag_db,
                  lot_pixels=int(lot.sum()), ref_pixels=int(ref.sum()))
    return Analysis(df, baselines, freq, mean_db, masks, params)
