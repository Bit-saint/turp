"""Figures and HTML report for the individual-target analysis."""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402

from .metrics import _db  # noqa: E402
from .report import SLOT_COLORS, WEEKDAYS, _clean_map_axes, _png  # noqa: E402
from .site import Site  # noqa: E402
from .targets import _labels, episodes, repeat_test  # noqa: E402


def _outline(ax, site: Site):
    g = site.to_utm(site.lot)
    for p in getattr(g, "geoms", [g]):
        ax.plot(*p.exterior.xy, color="#00d0ff", lw=0.7)


def _pos_label(p) -> str:
    lab = p.get("label") if hasattr(p, "get") else None
    return f"{p.position}" + (f" ({lab})" if isinstance(lab, str) else "")


def fig_map(res, site, rgb, rgb_name, chip_dir):
    g = site.grid()
    n = 2 if rgb is not None else 1
    fig, axs = plt.subplots(1, n, figsize=(8.5 * n, 7.6))
    axs = np.atleast_1d(axs)
    if rgb is not None:
        axs[0].imshow(np.clip(rgb.astype(float) * 1.5, 0, 255).astype(np.uint8), extent=g.extent)
        axs[0].set_title(f"Sentinel-2 true colour ({rgb_name}) with recurring target positions", fontsize=9)
    track = res.scenes.track.value_counts().idxmax()
    ax = axs[-1]
    ax.imshow(res.background[track], cmap="gray", vmin=-25, vmax=5, extent=g.extent)
    hits = np.ma.masked_less(res.hits_map.astype(float), 1)
    im = ax.imshow(hits, cmap="autumn_r", extent=g.extent, vmin=1, vmax=max(3, np.percentile(hits.compressed(), 98))
                   if hits.count() else 3, interpolation="nearest")
    fig.colorbar(im, ax=ax, fraction=0.04, pad=0.01, label="detections per pixel (all scenes)")
    ax.set_title(f"Sentinel-1 empty background (track {track}, VV+VH) and detection density", fontsize=9)
    for a in axs:
        _outline(a, site)
        for _, p in res.positions.iterrows():
            a.plot(p.x, p.y, "o", ms=9, mfc="none", mec="lime", mew=1.0)
            a.annotate(p.position, (p.x, p.y), xytext=(4, 4), textcoords="offset points", color="lime", fontsize=6.5)
        _clean_map_axes(a)
    fig.tight_layout()
    return fig


def fig_timeline(res):
    pres = res.presence.astype(float)
    scenes = res.scenes.set_index("product").loc[pres.columns]
    order = res.positions.sort_values("occupancy", ascending=False).position
    pres = pres.loc[order]
    # colour: 0 absent, 1 present (morning), 2 present (evening)
    slot = (scenes.pass_slot == "evening").astype(int).values
    img = pres.values * (1 + slot[None, :])
    fig, ax = plt.subplots(figsize=(13, max(3, 0.19 * len(pres) + 1.4)))
    cmap = ListedColormap(["#f3f3f3", SLOT_COLORS["morning"], SLOT_COLORS["evening"]])
    ax.imshow(img, aspect="auto", cmap=cmap, vmin=0, vmax=2, interpolation="nearest")
    labels = [_pos_label(r) for _, r in res.positions.set_index("position").loc[order].reset_index().iterrows()]
    ax.set_yticks(range(len(pres)), labels, fontsize=6.5)
    t = scenes.local_time.reset_index(drop=True)
    months = t.dt.tz_localize(None).dt.to_period("M").astype(str)
    first = ~months.duplicated()
    ax.set_xticks(np.nonzero(first.values)[0], [pd.Period(m).strftime("%b %y") for m in months[first]], fontsize=7)
    ax.grid(False)
    ax.set_xlabel("Sentinel-1 acquisitions in time order (blue: present on a morning pass, orange: present on an "
                  "evening pass, grey: absent)", fontsize=8)
    ax.set_title("Appearance history of every recurring target position, sorted by occupancy", fontsize=9)
    fig.tight_layout()
    return fig


def fig_counts(res):
    s = res.scenes
    fig, axs = plt.subplots(1, 2, figsize=(13, 3.6), gridspec_kw={"width_ratios": [2.3, 1]})
    for slot, c in SLOT_COLORS.items():
        d = s[s.pass_slot == slot]
        axs[0].scatter(d.local_time, d.n_targets, s=12, color=c, label=slot)
        r = d.set_index("local_time").n_targets.rolling("30D", center=True, min_periods=3).median()
        axs[0].plot(r.index, r.values, color=c, lw=1.4)
    axs[0].set_ylabel("targets detected on the aprons")
    axs[0].legend(frameon=False, fontsize=8)
    axs[0].set_title("Targets per scene (lines: 30-day rolling median)", fontsize=9)
    data = [s.search_density.values, s.control_density.values]
    axs[1].boxplot(data, tick_labels=["search area\n(aprons)", "control area\n(vegetation)"], showfliers=False,
                   widths=0.5)
    axs[1].set_ylabel("detections per km² per scene")
    axs[1].set_title("Detection density: search area vs control", fontsize=9)
    fig.tight_layout()
    return fig


def fig_strips(res, site, chip_dir, n_positions=4, n_scenes=14, half_m=110):
    """Image strips: the same small window around a position over consecutive acquisitions."""
    pos = res.positions.copy()
    pos["var"] = pos.occupancy * (1 - pos.occupancy)
    pick = pos.sort_values(["var", "n_hits"], ascending=False).head(n_positions)
    scenes = res.scenes
    track = scenes.track.value_counts().idxmax()
    sel = scenes[scenes.track == track].sort_values("local_time")
    if len(sel) > n_scenes:
        # densest run of acquisitions in the middle of the period
        mid = len(sel) // 2
        sel = sel.iloc[max(0, mid - n_scenes // 2): max(0, mid - n_scenes // 2) + n_scenes]
    g = site.grid()
    hp = int(half_m / site.pixel_size)
    fig, axs = plt.subplots(len(pick), len(sel), figsize=(1.05 * len(sel), 1.25 * len(pick) + 0.6))
    axs = np.atleast_2d(axs)
    imgs = {}
    for prod in sel["product"]:
        with np.load(Path(chip_dir) / f"{prod}.npz") as z:
            imgs[prod] = _db(z["vv"] + z["vh"])
    for i, (_, p) in enumerate(pick.iterrows()):
        c, r = (~g.transform) @ (p.x, p.y)
        r, c = int(r), int(c)
        for j, (_, s) in enumerate(sel.iterrows()):
            ax = axs[i, j]
            win = imgs[s["product"]][max(r - hp, 0): r + hp, max(c - hp, 0): c + hp]
            ax.imshow(win, cmap="gray", vmin=-22, vmax=8)
            present = bool(res.presence.loc[p.position, s["product"]])
            for sp in ax.spines.values():
                sp.set_visible(True); sp.set_color("#DD8452" if present else "#bbbbbb"); sp.set_linewidth(2.2)
            ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
            if i == 0:
                ax.set_title(s.local_time.strftime("%d %b\n%H:%M"), fontsize=6.5)
            if j == 0:
                ax.set_ylabel(_pos_label(p), fontsize=7)
    fig.suptitle(f"Individual positions over consecutive acquisitions of track {track} "
                 f"({2 * half_m} m windows; orange frame = target present)", fontsize=9)
    fig.tight_layout()
    return fig


def fig_weekly(res):
    s = res.scenes
    fig, ax = plt.subplots(figsize=(7, 3.2))
    for k, (slot, c) in enumerate(SLOT_COLORS.items()):
        d = s[s.pass_slot == slot]
        med = d.groupby("weekday").n_targets.median().reindex(WEEKDAYS)
        ax.bar(np.arange(7) + (k - 0.5) * 0.38, med.values, 0.38, color=c, label=slot)
    ax.set_xticks(range(7), WEEKDAYS)
    ax.set_ylabel("median targets per scene")
    ax.legend(frameon=False, fontsize=8)
    ax.set_title("Weekly pattern", fontsize=9)
    fig.tight_layout()
    return fig


def fig_repeat(rt: dict):
    c = pd.DataFrame(rt["lag_curve"])
    fig, ax = plt.subplots(figsize=(7.5, 3.3))
    ax.plot(range(len(c)), c.kappa, "o-", color="#4C72B0")
    for k, r in c.iterrows():
        ax.annotate(f"n={r.scene_pairs}", (k, r.kappa), xytext=(0, 6), textcoords="offset points", ha="center",
                    fontsize=7, color="0.4")
    ax.axhline(0, color="0.5", lw=0.8)
    ax.set_xticks(range(len(c)), c.lag, fontsize=8)
    ax.set_ylabel("presence agreement\n(Cohen's kappa)")
    ax.set_xlabel("time between the two Sentinel-1 images (different tracks)")
    ax.set_title("Sentinel-1 repeat test: 1 = same answer in both images, 0 = chance", fontsize=9)
    fig.tight_layout()
    return fig


def optical_agreement(res, optical: pd.DataFrame, max_gap_h: float = 9.0) -> pd.DataFrame:
    """Pair each optical observation with the S1 morning and evening passes of the same day.

    Only cases where both radar passes agree (present at both or absent at both)
    are scored; an aircraft present before and after the optical image is
    very likely present at the optical time too.
    """
    s = res.scenes[["product", "time_utc", "pass_slot"]]
    recs = []
    for _, o in optical.iterrows():
        t = pd.Timestamp(o.time)
        before = s[(s.time_utc <= t) & (s.time_utc >= t - pd.Timedelta(hours=max_gap_h))]
        after = s[(s.time_utc >= t) & (s.time_utc <= t + pd.Timedelta(hours=max_gap_h))]
        if before.empty or after.empty:
            continue
        a = bool(res.presence.loc[o.position, before.iloc[-1]["product"]])
        b = bool(res.presence.loc[o.position, after.iloc[0]["product"]])
        if a == b:
            recs.append({"position": o.position, "s2": o.s2, "radar": a, "optical": o.present,
                         "brightest": o.brightest})
    return pd.DataFrame(recs)


def label_association(res, site: Site, near_m: float = 80.0, n_random: int = 2000) -> dict | None:
    """Are recurring positions closer to mapped stands/gates than random points of the search area?"""
    from scipy import stats
    labels = _labels(site)
    if not labels or not len(res.positions):
        return None
    lab = np.array([(x, y) for _, x, y in labels])
    g = site.grid()

    def dist(xy):
        return np.min(np.hypot(lab[:, 0][None] - xy[:, 0][:, None], lab[:, 1][None] - xy[:, 1][:, None]), 1)
    rr, cc = np.nonzero(g.rasterize(site.to_utm(site.lot)))
    k = np.random.default_rng(0).choice(len(rr), min(n_random, len(rr)), replace=False)
    rx, ry = g.transform @ (cc[k] + 0.5, rr[k] + 0.5)
    dp, dr = dist(res.positions[["x", "y"]].values), dist(np.c_[rx, ry])
    return {"positions_within": round(float((dp <= near_m).mean()), 3), "random_within": round(float((dr <= near_m).mean()), 3),
            "near_m": near_m, "p": float(stats.mannwhitneyu(dp, dr, alternative="less").pvalue)}


def episode_optical(eps: pd.DataFrame, optical: pd.DataFrame, margin_days: float = 3) -> pd.DataFrame:
    """Optical brightness at a position during a long stay vs outside it."""
    recs = []
    t = pd.to_datetime(optical.time, utc=True)
    for _, e in eps.iterrows():
        o = optical[optical.position == e.position]
        to = t[o.index]
        start, end = (pd.Timestamp(x).tz_localize("UTC") if pd.Timestamp(x).tzinfo is None
                      else pd.Timestamp(x).tz_convert("UTC") for x in (e.start, e.end))
        inside = o[(to >= start) & (to <= end)].brightest
        m = pd.Timedelta(days=margin_days)
        outside = o[(to < start - m) | (to > end + m)].brightest
        if len(inside) and len(outside):
            recs.append({**e.to_dict(), "optical_in": inside.median(), "optical_out": outside.median(),
                         "n_optical_in": len(inside)})
    return pd.DataFrame(recs)


def write(res, site: Site, out_dir: Path, chip_dir: Path, rgb, rgb_name, optical) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    res.scenes.drop(columns=[c for c in ("window", "pols") if c in res.scenes]).to_csv(
        out_dir / "scenes.csv", index=False, float_format="%.4f")
    res.detections.to_csv(out_dir / "detections.csv", index=False, float_format="%.6f")
    res.positions.to_csv(out_dir / "positions.csv", index=False, float_format="%.6f")
    pres = res.presence.astype(int).copy()
    pres.columns = res.scenes.set_index("product").loc[pres.columns].local_time.dt.strftime("%Y-%m-%dT%H:%M")
    pres.to_csv(out_dir / "presence.csv")
    summary = res.summary()
    times = res.scenes.set_index("product").loc[res.presence.columns].local_time
    eps = episodes(res.presence, times)
    eps_opt = episode_optical(eps, optical) if optical is not None and len(optical) and len(eps) else pd.DataFrame()
    if len(eps_opt):
        eps = eps.merge(eps_opt[["position", "start", "optical_in", "optical_out", "n_optical_in"]],
                        on=["position", "start"], how="left")
    eps.to_csv(out_dir / "long_stays.csv", index=False, float_format="%.4f")
    summary["n_long_stays"] = int(len(eps))
    assoc = label_association(res, site)
    if assoc:
        summary["label_association"] = assoc

    rt = repeat_test(res)
    summary["s1_repeat_test"] = {k: v for k, v in rt.items() if k != "near_pair_table"}
    pd.DataFrame(rt["lag_curve"]).to_csv(out_dir / "repeat_lag_curve.csv", index=False)
    if rt.get("near_pair_table"):
        pd.DataFrame(rt["near_pair_table"]).to_csv(out_dir / "repeat_near_pairs.csv", index=False)

    figs = {"repeat": fig_repeat(rt), "map": fig_map(res, site, rgb, rgb_name, chip_dir), "timeline": fig_timeline(res),
            "strips": fig_strips(res, site, chip_dir), "counts": fig_counts(res), "weekly": fig_weekly(res)}
    imgs = {}
    for k, f in figs.items():
        b = _png(f)
        (out_dir / f"{k}.png").write_bytes(b)
        imgs[k] = base64.b64encode(b).decode()

    opt_html = "<p>No cloud-free Sentinel-2 acquisitions were available for a cross-check.</p>"
    if optical is not None and len(optical):
        agree = optical_agreement(res, optical)
        if len(agree):
            ct = pd.crosstab(agree.radar, agree.optical).reindex(index=[True, False], columns=[True, False],
                                                                  fill_value=0)
            acc = float((agree.radar == agree.optical).mean())
            pp = ct.loc[True, True] / max(ct.loc[True].sum(), 1)
            nn = ct.loc[False, False] / max(ct.loc[False].sum(), 1)
            summary["optical_check"] = {"pairs": int(len(agree)), "agreement": round(acc, 3),
                                        "radar_present_optical_present": round(float(pp), 3),
                                        "radar_absent_optical_absent": round(float(nn), 3),
                                        "n_s2_scenes": int(optical.s2.nunique())}
            agree.to_csv(out_dir / "optical_check.csv", index=False)
            opt_html = f"""<p>Sentinel-2 passes around 12:50 local time, between the radar's morning and evening passes.
For every position and every cloud-free Sentinel-2 image ({optical.s2.nunique()} images), the radar passes just before and
after the optical image are compared. Only cases where those two radar passes agree are scored. The optical test asks
whether a white object (min(R,G,B) reflectance ≥ 0.45) lies within 25 m of the position.</p>
<table><tr><th></th><th>optical: present</th><th>optical: absent</th></tr>
<tr><th>radar: present</th><td>{ct.loc[True, True]}</td><td>{ct.loc[True, False]}</td></tr>
<tr><th>radar: absent</th><td>{ct.loc[False, True]}</td><td>{ct.loc[False, False]}</td></tr></table>
<p>When the radar says present, the optical image shows a white object in <b>{pp:.0%}</b> of cases. When the radar
says absent, it shows one in <b>{1 - nn:.0%}</b> of cases. Overall agreement is {acc:.0%} over {len(agree)} pairs, but
this mostly reflects how common "absent at both" is. A clear gap between the two percentages would confirm the
radar detections. A small gap means the check cannot confirm them. Possible reasons: a gate can be occupied by
different aircraft before and after the optical pass, white vehicles and markings also pass the optical test, and
at 10 m a narrow-body fuselage is thinner than a pixel.</p>"""
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str))

    top_eps = eps.sort_values("days", ascending=False).head(15)
    eps_rows = "".join(
        f"<tr><td>{r.position}</td><td>{pd.Timestamp(r.start):%Y-%m-%d}</td><td>{pd.Timestamp(r.end):%Y-%m-%d}</td>"
        f"<td>{r.days:.0f}</td><td>{r.detected_frac:.0%}</td>"
        + (f"<td>{r.optical_in:.2f} / {r.optical_out:.2f}</td>" if "optical_in" in eps and pd.notna(r.optical_in)
           else ("<td>–</td>" if "optical_in" in eps else "")) + "</tr>" for _, r in top_eps.iterrows())
    near_txt = ""
    if rt.get("near_pairs"):
        near_txt = (
            f"<p><b>Near-simultaneous pairs.</b> In {rt['near_pairs']} cases two Sentinel-1 satellites imaged the "
            f"airport a few minutes apart from different orbits. Parked aircraft do not move in that time, so a reliable "
            f"detector would give the same answer in both images. Agreement is kappa = <b>{rt['near_kappa']:.2f}</b>. "
            f"{rt['matched_near']:.0%} of the targets in one image have a target within {rt['match_m']:g} m in the "
            f"other, against {rt['matched_far']:.0%} for images taken days apart (chance level). The underlying "
            f"brightness scores correlate at ρ = {rt['near_score_spearman']:.2f}, against "
            f"{rt.get('far_score_spearman', float('nan')):.2f} for images more than 5 days apart. "
            f"Part of the disagreement is physical: an aircraft's radar echo depends strongly on its orientation "
            f"relative to the radar, and the two images view it from different orbits.</p>")
    rep_html = (f"<h3>Sentinel-1 repeat test</h3>{near_txt}"
                f"<img src=\"data:image/png;base64,{imgs['repeat']}\">"
                "<p>If the detections were speckle, agreement would be about zero at every gap. If they were "
                "fixed structures, it would stay high at every gap. Real objects that come and go give agreement "
                "that is highest at short gaps and falls with time. A daily flight schedule also raises agreement at "
                "the same time of day (14–36 h) above morning-versus-evening pairs (30 min – 14 h).</p>")
    val = [f"<li><b>False alarms.</b> On natural surfaces, where no target can be, the detector finds a median of "
           f"{summary['control_density_per_km2']:.2f} targets per km² per scene, against "
           f"{summary['search_density_per_km2']:.2f} per km² in the search area. If the search area produced false "
           f"alarms at the same rate, about {summary['control_density_per_km2'] / max(summary['search_density_per_km2'], 1e-9):.0%} "
           f"of its detections would be false.</li>"]
    if assoc:
        val.append(f"<li><b>Position vs mapped gates.</b> {assoc['positions_within']:.0%} of recurring positions lie within "
                   f"{assoc['near_m']:g} m of a mapped gate, against {assoc['random_within']:.0%} of random points in the "
                   f"search area (Mann–Whitney p = {assoc['p']:.1e}).</li>")
    if len(eps_opt):
        from scipy import stats
        d = eps_opt.optical_in - eps_opt.optical_out
        pval = stats.wilcoxon(eps_opt.optical_in, eps_opt.optical_out, alternative="greater").pvalue \
            if len(eps_opt) >= 5 else float("nan")
        summary["long_stay_optical"] = {"n": int(len(eps_opt)), "brighter_inside": int((d > 0).sum()), "p": float(pval)}
        val.append(f"<li><b>Long stays vs optical.</b> For a long stay, the object is present at the optical "
                   f"pass time too. In {(d > 0).sum()} of {len(eps_opt)} long stays the position is brighter in Sentinel-2 during the stay "
                   f"than outside it (one-sided Wilcoxon p = {pval:.2f}).</li>")
    val_html = rep_html + "<h3>Other checks</h3><ul>" + "".join(val) + "</ul>"
    p = res.params
    top = res.positions.sort_values("occupancy", ascending=False)
    cols = [c for c in ("occupancy_morning", "occupancy_evening") if c in top]
    pos_rows = "".join(
        f"<tr><td>{r.position}</td><td>{html.escape(str(r.get('label') or ''))}</td><td>{r.lat:.5f}, {r.lon:.5f}</td>"
        f"<td>{r.occupancy:.0%}</td>" + "".join(f"<td>{r[c]:.0%}</td>" for c in cols) +
        f"<td>{r.appearances}</td><td>{r.peak_db:.1f}</td></tr>" for _, r in top.iterrows())
    s = res.scenes
    tracks = ", ".join(f"{t} ({n})" for t, n in sorted(s.groupby("track").size().items()))
    doc = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>{html.escape(site.name)} – Sentinel-1 target tracking</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:1250px;margin:2em auto;padding:0 1em;color:#222;line-height:1.45}}
h1{{font-size:1.5em;margin-bottom:.2em}} h2{{font-size:1.15em;margin-top:1.8em;border-bottom:1px solid #ddd}}
img{{max-width:100%}} table{{border-collapse:collapse;margin:.6em 0;font-size:.9em}}
td,th{{border:1px solid #ddd;padding:.25em .6em;text-align:left}} th{{background:#f6f6f6}}
.meta{{color:#666}} code{{background:#f3f3f3;padding:0 .25em}}
</style></head><body>
<h1>{html.escape(site.name)} – individual targets over time</h1>
<p class=meta>Sentinel-1 IW GRD · {len(s)} acquisitions, {s.local_time.min():%d %b %Y} – {s.local_time.max():%d %b %Y}
· tracks: {tracks}</p>
<p><b>{summary['n_detections']}</b> targets were detected in total, a median of {summary['targets_per_scene_median']:.0f}
per scene. They group into <b>{summary['n_positions']}</b> recurring positions. The median detection density is
{summary['search_density_per_km2']:.1f} per km² on the aprons against {summary['control_density_per_km2']:.2f} per km²
in the surroundings.</p>
<h2>Where targets appear</h2><img src="data:image/png;base64,{imgs['map']}">
<h2>Appearance history per position</h2><img src="data:image/png;base64,{imgs['timeline']}">
<h2>Individual positions, image by image</h2><img src="data:image/png;base64,{imgs['strips']}">
<h2>Counts over time</h2><img src="data:image/png;base64,{imgs['counts']}">
<img src="data:image/png;base64,{imgs['weekly']}">
<h2>Long stays</h2>
<p>A long stay is a position that is occupied continuously for at least 10 days (up to one missed scene allowed,
detected in ≥75% of scenes). Examples are aircraft parked for maintenance or storage. Snow piles and parked
equipment also produce long stays, especially in winter. {len(eps)} long stays were found; the longest are listed
below. Full list: <code>long_stays.csv</code>.</p>
<table><tr><th>Position</th><th>From</th><th>To</th><th>Days</th><th>Detected</th>{'<th>Optical brightness inside / outside</th>' if 'optical_in' in eps else ''}</tr>
{eps_rows}</table>
<h2>Validation</h2>
{val_html}
{('<h3>Optional cross-check with Sentinel-2</h3>' + opt_html) if optical is not None else ''}
<h2>Positions</h2>
<p>"Appearances" counts how many times the position switched from empty to occupied between consecutive
acquisitions. Labels are the nearest gate reference from OpenStreetMap within {p.label_max_m:g} m.</p>
<table><tr><th>Position</th><th>Nearest gate</th><th>Lat, lon</th><th>Occupied</th>
{''.join(f'<th>{c.replace("occupancy_", "Occupied, ")}</th>' for c in cols)}<th>Appearances</th><th>Median peak σ⁰ (dB)</th></tr>
{pos_rows}</table>
<h2>Method</h2><ul>
<li>σ⁰ VV+VH on a {site.pixel_size:g} m grid; per track, the empty background is each pixel's {p.background_pct:g}th
percentile over time. Fixed structures are part of the background and are not detected.</li>
<li>Target pixel: ≥{p.ratio_db:g} dB above background and ≥{p.min_db:g} dB absolute. A target is ≥{p.min_pixels} connected
pixels inside the apron polygons buffered by {p.search_buffer_m:g} m.</li>
<li>Detections from all scenes are linked within {p.cluster_m:g} m. Linked groups present in ≥{p.min_hits_frac:.0%} of
scenes are recurring positions. A position is "present" in a scene if any pixel within {p.radius_m:g} m passes the
pixel test.</li>
<li>False alarms: the same detector runs on a control area where no target can be. That is the vegetation from
<code>targets.control_area</code> if it is set, otherwise dark natural surfaces in the reference ring. Taxiways and
runways are excluded from it.</li></ul>
<h2>Caveats</h2><ul>
<li>At 10 m pixels (about 20 m resolution) the radar shows that a large object is present. It cannot identify the
aircraft type or registration. Two aircraft parked next to each other can merge into one target.</li>
<li>Aircraft at contact gates touch jet bridges and the terminal, so the background there is bright and those
aircraft are harder to detect than on remote stands.</li>
<li>Ground vehicles, de-icing rigs and snow piles also produce targets.</li>
<li>Radar passes happen only around 06–08 h and 18–19 h local time. Aircraft that turn around between passes are
never seen.</li></ul>
<p class=meta>Data: Copernicus Sentinel-1/-2 (ESA) via AWS Open Data; aprons and gates: Overture Maps / © OpenStreetMap
contributors. Files: <code>detections.csv</code>, <code>positions.csv</code>, <code>presence.csv</code>,
<code>scenes.csv</code>, <code>long_stays.csv</code>.</p>
</body></html>"""
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    path = out_dir / "targets.html"
    path.write_text(doc)
    return path
