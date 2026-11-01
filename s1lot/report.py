"""Figures, CSV and a self-contained HTML report for an analysed site."""

from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .metrics import DAYTYPE_ORDER, Analysis, boxcar, _db  # noqa: E402
from .site import Site  # noqa: E402

SLOT_COLORS = {"morning": "#4C72B0", "evening": "#DD8452"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
plt.rcParams.update({"figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.25, "font.size": 9})


def _outline(ax, site: Site, **kw):
    geom = site.to_utm(site.lot)
    polys = getattr(geom, "geoms", [geom])
    for p in polys:
        ax.plot(*p.exterior.xy, **{"color": "red", "lw": 1.0, **kw})
        for i in p.interiors:
            ax.plot(*i.xy, **{"color": "red", "lw": 0.6, "ls": "--", **kw})


def _clean_map_axes(ax):
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)


def fig_context(an: Analysis, site: Site, rgb: np.ndarray | None, rgb_name: str | None):
    g = site.grid()
    best = an.scenes.track.value_counts().idxmax()
    n = an.scenes.groupby("track").size()
    freq = sum(an.frequency[t] * n[t] for t in an.frequency) / n.sum()
    panels = (1 if rgb is not None else 0) + 2
    fig, axs = plt.subplots(1, panels, figsize=(4.2 * panels, 4.4))
    i = 0
    if rgb is not None:
        axs[i].imshow(np.clip(rgb.astype(float) * 1.6, 0, 255).astype(np.uint8), extent=g.extent)
        axs[i].set_title(f"Sentinel-2 true colour\n{rgb_name}", fontsize=8)
        i += 1
    lo, hi = np.nanpercentile(an.mean_db[best], [2, 99.5])
    axs[i].imshow(an.mean_db[best], cmap="gray", vmin=lo, vmax=hi, extent=g.extent)
    axs[i].set_title(f"Sentinel-1 {an.params['pol'].upper()} mean backscatter\ntrack {best} ({n[best]} scenes)", fontsize=8)
    i += 1
    shown = np.where(an.masks["lot_full"] | an.masks["ref"], freq, np.nan)
    im = axs[i].imshow(shown * 100, cmap="magma", vmin=0, vmax=max(5, np.nanpercentile(freq[an.masks["lot"]] * 100, 98)),
                       extent=g.extent)
    axs[i].set_title("How often each pixel is 'occupied'\n(% of scenes, all tracks)", fontsize=8)
    fig.colorbar(im, ax=axs[i], fraction=0.046, pad=0.02, label="% of scenes")
    for ax in axs:
        _outline(ax, site)
        _clean_map_axes(ax)
    fig.tight_layout()
    return fig


def fig_timeseries(an: Analysis):
    df = an.scenes
    fig, ax = plt.subplots(figsize=(11, 4))
    for slot, c in SLOT_COLORS.items():
        for closed, mk in ((False, "o"), (True, "o")):
            d = df[(df.pass_slot == slot) & ((df.daytype == "Sun/holiday") == closed)]
            if d.empty:
                continue
            ax.scatter(d.local_time, d.activity, s=22, marker=mk, label=f"{slot} – {'Sun/holiday' if closed else 'Mon–Sat'}",
                       facecolors="none" if closed else c, edgecolors=c, linewidths=1.1, zorder=3)
        d = df[(df.pass_slot == slot) & (df.daytype != "Sun/holiday")].set_index("local_time").activity
        if len(d) >= 6:
            r = d.rolling("30D", center=True, min_periods=3).median()
            ax.plot(r.index, r.values, color=c, lw=1.5, alpha=0.8)
    wf = df[df.weather_flag]
    if not wf.empty:
        ax.scatter(wf.local_time, wf.activity, s=70, marker="x", color="0.35", lw=0.9, zorder=4,
                   label="surroundings changed too (weather?)")
    flagged = df[df.anomaly_z.abs() >= 3]
    for _, r in flagged.iterrows():
        ax.annotate(r.local_time.strftime("%d %b"), (r.local_time, r.activity), fontsize=6.5,
                    xytext=(3, 4), textcoords="offset points", color="0.3")
    ax.set_ylabel("Parking activity index\n(0 = empty baseline, 100 = busy)")
    ax.set_title("Parking activity per Sentinel-1 acquisition (filled: Mon–Sat, hollow: Sun/public holiday; "
                 "lines: 30-day rolling median Mon–Sat)", fontsize=9)
    ax.legend(loc="upper left", fontsize=7.5, ncol=2, frameon=False)
    fig.tight_layout()
    return fig


def fig_weekday(an: Analysis):
    df = an.scenes.copy()
    fig, axs = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
    rng = np.random.default_rng(0)
    for ax, slot in zip(axs, ("morning", "evening")):
        d = df[df.pass_slot == slot]
        if d.empty:
            ax.set_visible(False)
            continue
        hrs = d.local_time.dt.strftime("%H:%M")
        data = [d[d.weekday == w].activity.dropna().values for w in WEEKDAYS]
        ax.boxplot([x if len(x) else [np.nan] for x in data], tick_labels=WEEKDAYS, widths=0.55,
                   showfliers=False, medianprops={"color": "k"})
        for i, x in enumerate(data, 1):
            ax.scatter(i + rng.uniform(-0.15, 0.15, len(x)), x, s=10, color=SLOT_COLORS[slot], alpha=0.7, zorder=3)
        hol = d[d.holiday.notna() & (d.weekday != "Sun")]
        for _, r in hol.iterrows():
            ax.scatter(WEEKDAYS.index(r.weekday) + 1, r.activity, s=40, facecolors="none", edgecolors="k", zorder=4)
        ax.set_title(f"{slot.title()} passes (local time {hrs.min()}–{hrs.max()}), n={len(d)}", fontsize=9)
    axs[0].set_ylabel("Parking activity index")
    fig.suptitle("Weekly pattern (black rings: public holidays)", fontsize=9)
    fig.tight_layout()
    return fig


def fig_monthly(an: Analysis):
    df = an.scenes.copy()
    df["month"] = df.local_time.dt.tz_localize(None).dt.to_period("M")
    groups = {"evening, Mon–Sat": (df.pass_slot == "evening") & (df.daytype != "Sun/holiday"),
              "evening, Sun/holiday": (df.pass_slot == "evening") & (df.daytype == "Sun/holiday"),
              "morning, all days": df.pass_slot == "morning"}
    colors = ["#DD8452", "#8C8C8C", "#4C72B0"]
    fig, ax = plt.subplots(figsize=(11, 3.4))
    months = sorted(df.month.unique())
    x = np.arange(len(months))
    w = 0.27
    for k, ((label, sel), c) in enumerate(zip(groups.items(), colors)):
        m = df[sel].groupby("month").activity.mean().reindex(months)
        ax.bar(x + (k - 1) * w, m.values, w, label=label, color=c)
    ax.set_xticks(x, [m.strftime("%b %y") for m in months])
    ax.set_ylabel("Mean activity index")
    ax.set_title("Monthly mean activity", fontsize=9)
    ax.legend(fontsize=7.5, frameon=False, ncol=3)
    fig.tight_layout()
    return fig


def fig_examples(an: Analysis, site: Site, chip_dir: Path):
    """Emptiest vs busiest acquisition of the most-sampled evening track."""
    df = an.scenes
    ev = df[df.pass_slot == "evening"]
    track = (ev if not ev.empty else df).track.value_counts().idxmax()
    d = df[(df.track == track) & ~df.weather_flag].dropna(subset=["activity"])
    lo, hi = d.loc[d.activity.idxmin()], d.loc[d.activity.idxmax()]
    g = site.grid()
    fig, axs = plt.subplots(1, 3, figsize=(12, 4.2))
    pol = an.params["pol"]
    vmin, vmax = np.nanpercentile(an.mean_db[track], [2, 99.5])
    for ax, r in zip(axs[:2], (lo, hi)):
        with np.load(chip_dir / f"{r['product']}.npz") as z:
            img = _db(boxcar(z[pol], an.params["boxcar"]))
        ax.imshow(img, cmap="gray", vmin=vmin, vmax=vmax, extent=g.extent)
        ax.set_title(f"{r.local_time:%a %d %b %Y %H:%M} – activity {r.activity:.0f}", fontsize=8.5)
    with np.load(chip_dir / f"{hi['product']}.npz") as z:
        diff = _db(boxcar(z[pol], an.params["boxcar"])) - an.baselines[track]
    im = axs[2].imshow(np.where(an.masks["lot_full"] | an.masks["ref"], diff, np.nan), cmap="RdBu_r", vmin=-8, vmax=8,
                       extent=g.extent)
    axs[2].set_title("Busiest minus empty baseline (dB)", fontsize=8.5)
    fig.colorbar(im, ax=axs[2], fraction=0.046, pad=0.02)
    for ax in axs:
        _outline(ax, site)
        _clean_map_axes(ax)
    b = an.params["boxcar"]
    fig.suptitle(f"Track {track}: quietest vs busiest acquisition ({pol.upper()}, {b}×{b} boxcar)", fontsize=9)
    fig.tight_layout()
    return fig


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


CSV_COLUMNS = ["local_time", "time_utc", "weekday", "daytype", "holiday", "pass_slot", "track", "mission", "product",
               "incidence", "activity", "excess_db", "occupied_frac", "contrast_db", "lot_vv_db", "lot_vh_db",
               "ref_vv_db", "ref_vh_db", "expected", "anomaly_z", "ring_db", "weather_flag", "low_confidence", "geoloc_rms_px"]


def write_report(an: Analysis, site: Site, out_dir: str | Path, chip_dir: str | Path,
                 rgb: np.ndarray | None = None, rgb_name: str | None = None) -> Path:
    out_dir, chip_dir = Path(out_dir), Path(chip_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = an.scenes
    df[[c for c in CSV_COLUMNS if c in df]].to_csv(out_dir / "timeseries.csv", index=False, float_format="%.4f")
    summary = an.summary()
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str))

    figs = {"context": fig_context(an, site, rgb, rgb_name), "timeseries": fig_timeseries(an),
            "weekday": fig_weekday(an), "monthly": fig_monthly(an), "examples": fig_examples(an, site, chip_dir)}
    imgs = {}
    for k, f in figs.items():
        b = _png(f)
        (out_dir / f"{k}.png").write_bytes(b)
        imgs[k] = base64.b64encode(b).decode()

    ev = summary.get("evening_open_vs_closed")
    tracks = ", ".join(f"{t} ({n})" for t, n in sorted(summary["tracks"].items()))
    tbl = df.pivot_table(index="pass_slot", columns="daytype", values="activity", aggfunc="median")
    tbl = tbl.reindex(columns=[c for c in DAYTYPE_ORDER if c in tbl.columns])
    cnt = df.pivot_table(index="pass_slot", columns="daytype", values="activity", aggfunc="count")
    rows = "".join(
        f"<tr><th>{html.escape(i)}</th>" + "".join(
            f"<td>{v:.0f} <span class=n>(n={int(cnt.loc[i, c])})</span></td>" if pd.notna(v) else "<td>–</td>"
            for c, v in r.items()) + "</tr>" for i, r in tbl.iterrows())
    pattern_table = (f"<table><tr><th>Median activity</th>{''.join(f'<th>{c}</th>' for c in tbl.columns)}</tr>"
                     f"{rows}</table>")
    anom = df[df.anomaly_z.abs() >= 3].sort_values("anomaly_z", key=np.abs, ascending=False).head(15)
    anom_rows = "".join(
        f"<tr><td>{r.local_time:%a %Y-%m-%d %H:%M}</td><td>{r.track}</td><td>{html.escape(r.daytype)}"
        f"{' – ' + html.escape(str(r.holiday)) if pd.notna(r.holiday) and r.holiday else ''}</td><td>{r.activity:.0f}</td>"
        f"<td>{r.expected:.0f}</td><td>{r.anomaly_z:+.1f}</td>"
        f"<td>{r.ring_db:+.1f} dB{' ⚠ weather?' if r.weather_flag else ''}</td></tr>" for _, r in anom.iterrows())
    validation = ""
    if ev:
        validation = (
            f"<p><b>Check against the opening hours.</b> The store is closed on Sundays and public holidays. On "
            f"evening passes the median activity is <b>{ev['open_median']:.0f}</b> on opening days "
            f"(n={ev['n_open']}) against <b>{ev['closed_median']:.0f}</b> on closed days (n={ev['n_closed']}); "
            f"one-sided Mann–Whitney p = {ev['mannwhitney_p']:.1e}.</p>")
    p = an.params
    doc = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>{html.escape(site.name)} – Sentinel-1 parking activity</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:1150px;margin:2em auto;padding:0 1em;color:#222;line-height:1.45}}
h1{{font-size:1.5em;margin-bottom:.2em}} h2{{font-size:1.15em;margin-top:1.8em;border-bottom:1px solid #ddd}}
img{{max-width:100%}} table{{border-collapse:collapse;margin:.6em 0;font-size:.92em}}
td,th{{border:1px solid #ddd;padding:.3em .7em;text-align:left}} th{{background:#f6f6f6}}
.n{{color:#888;font-size:.85em}} .meta{{color:#666}} code{{background:#f3f3f3;padding:0 .25em}}
</style></head><body>
<h1>{html.escape(site.name)}</h1>
<p class=meta>Sentinel-1 C-band SAR parking-activity monitor · {summary['n_scenes']} acquisitions,
{df.local_time.min():%d %b %Y} – {df.local_time.max():%d %b %Y} · tracks: {tracks}</p>
<h2>Site</h2>
<img src="data:image/png;base64,{imgs['context']}">
<p>Red: lot outline ({p['lot_pixels']} pixels of {site.pixel_size:g} m after a {site.edge_erode_m:g} m edge buffer).
The right panel shows how often each pixel was clearly brighter than its own empty-lot baseline,
which shows which parts of the lot fill up most often.</p>
<h2>Activity over time</h2>
<img src="data:image/png;base64,{imgs['timeseries']}">
{validation}
{pattern_table}
<h2>Weekly pattern</h2>
<img src="data:image/png;base64,{imgs['weekday']}">
<h2>Monthly pattern</h2>
<img src="data:image/png;base64,{imgs['monthly']}">
<h2>Quietest vs busiest acquisition</h2>
<img src="data:image/png;base64,{imgs['examples']}">
<h2>Unusual acquisitions</h2>
<p>Activity that deviates by ≥3 robust standard deviations from acquisitions of the same pass (morning/evening)
and day type. "Surroundings" is the change of the reference ring around the lot. A large value means the whole scene
changed (rain, frost, snow), so treat that row with suspicion. {int(df.weather_flag.sum())} of {len(df)} scenes exceed
±{p['weather_flag_db']:g} dB and are marked × in the time series.</p>
<table><tr><th>Local time</th><th>Track</th><th>Day type</th><th>Activity</th><th>Expected</th><th>z</th><th>Surroundings</th></tr>
{anom_rows or '<tr><td colspan=7>none</td></tr>'}</table>
<h2>Method</h2>
<ul>
<li>Data: Sentinel-1 IW GRD-HD scenes read directly from the public AWS archive (<code>s3://sentinel-s1-l1c</code>);
only a small window around the site is downloaded from each cloud-optimised GeoTIFF.</li>
<li>Radiometry: σ⁰ calibration with the product LUT, thermal noise removed (range × azimuth noise LUT).</li>
<li>Geometry: lon/lat/height → line/pixel fitted to the nearest geolocation tie points (mean residual
{df.geoloc_rms_px.mean():.2f} px), site mapped at {site.elevation_m if site.elevation_m is not None else 'tie-point'} m
ellipsoidal height, bilinear resampling onto a {site.pixel_size:g} m UTM grid.</li>
<li>Activity: per scene, the median {p['pol'].upper()} σ⁰ over the lot. Its <b>excess</b> over the track's empty
baseline ({p['baseline_pct']:g}th percentile of that track's series) removes the effect of viewing geometry. The
<b>activity index</b> is the excess scaled so that 0 = empty baseline and 100 = the 95th percentile of all scenes
({p['activity_scale_db']:.2f} dB). VH (cross-polarised) is used by default because cars produce multiple-bounce,
depolarised echoes while wet or frozen ground changes mainly the co-polarised channel.</li>
<li>Maps: per pixel, a scene counts as "occupied" if the {p['boxcar']}×{p['boxcar']} speckle-filtered σ⁰ is
≥{p['threshold_db']:g} dB above that pixel's empty baseline.</li>
</ul>
<h2>Caveats</h2>
<ul>
<li>Sentinel-1 only sees the site around 06–07 h and 18–19 h local time. This is a sample of activity at those
times, not a daily total.</li>
<li>The index is relative: a fixed number of cars does not always give the same index, because it depends on car
type, layout and wetness. Calibrate it against counts if absolute numbers are needed.</li>
<li>Tracks with fewer than 8 scenes have an unreliable baseline (flagged <code>low_confidence</code> in the CSV).</li>
<li>Snow, standing water and construction change the empty-lot backscatter, so check unusual acquisitions
against these causes.</li>
</ul>
<p class=meta>Data: Copernicus Sentinel-1/-2 (ESA), via AWS Open Data. Lot outline: Overture Maps / © OpenStreetMap contributors.
Full time series: <code>timeseries.csv</code>.</p>
</body></html>"""
    path = out_dir / "report.html"
    path.write_text(doc)
    return path
