"""Command line interface: ``s1lot find-lots | discover | process | analyse | run``."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

log = logging.getLogger("s1lot")


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _paths(workdir: str | Path) -> dict[str, Path]:
    w = Path(workdir)
    return {"work": w, "cache": w / "cache", "scenes": w / "scenes.json", "chips": w / "chips", "report": w / "report"}


def cmd_find_lots(a):
    from .overture import find_parking, nearby_places
    lots = [l for l in find_parking(a.lon, a.lat, a.radius) if l.area_ha >= a.min_ha]
    for i, l in enumerate(lots[: a.limit]):
        c = l.geometry.centroid
        t = {k: v for k, v in l.tags.items() if v}
        print(f"[{i}] {l.area_ha:6.2f} ha  {c.y:.5f},{c.x:.5f}  {l.name or ''}  {t}")
    if a.places:
        for p in nearby_places(a.lon, a.lat, 300)[:10]:
            print(f"    near: {p['name']} ({p['category']}), {p['address']}  {p['distance_m']} m")
    if a.out is not None and lots:
        sel = lots[a.pick]
        Path(a.out).write_text(json.dumps({"type": "FeatureCollection", "features": [sel.feature()]}, indent=1))
        print(f"wrote lot [{a.pick}] to {a.out}")


def _site(a):
    from .site import Site
    return Site.from_yaml(a.site)


def cmd_discover(a):
    from .catalog import Catalog, save_scenes
    site, p = _site(a), _paths(a.workdir)
    cat = Catalog(p["cache"], workers=a.workers)
    scenes = cat.discover(site.lot, a.start, a.end)
    p["work"].mkdir(parents=True, exist_ok=True)
    save_scenes(scenes, p["scenes"])
    log.info("%d scenes cover the site -> %s", len(scenes), p["scenes"])
    return scenes


def cmd_process(a):
    from .catalog import load_scenes
    from .process import process_all
    site, p = _site(a), _paths(a.workdir)
    scenes = load_scenes(p["scenes"])

    def progress(i, n):
        if i % 10 == 0 or i == n:
            log.info("processed %d/%d", i, n)
    metas = process_all(scenes, site, p["chips"], workers=a.workers, noise_removal=not a.no_noise, progress=progress)
    log.info("%d scenes processed into %s", len(metas), p["chips"])


def cmd_analyse(a):
    from .metrics import analyse
    from .report import write_report
    site, p = _site(a), _paths(a.workdir)
    an = analyse(site, p["chips"], pol=a.pol, threshold_db=a.threshold, baseline_pct=a.baseline_pct)
    rgb = name = None
    if not a.no_optical:
        try:
            from .s2context import true_colour
            res = true_colour(site, today=an.scenes.local_time.max().date())
            if res:
                rgb, name = res
        except Exception as e:  # noqa: BLE001 - optical context is optional
            log.warning("optical context unavailable: %s", e)
    path = write_report(an, site, p["report"], p["chips"], rgb, name)
    log.info("report: %s", path)
    print(json.dumps(an.summary(), indent=1, default=str))


def cmd_run(a):
    cmd_discover(a)
    cmd_process(a)
    cmd_analyse(a)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="s1lot", description="Monitor parking-lot activity with Sentinel-1 SAR.")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("find-lots", help="list mapped parking lots near a point (Overture Maps)")
    f.add_argument("--lon", type=float, required=True)
    f.add_argument("--lat", type=float, required=True)
    f.add_argument("--radius", type=float, default=1000, help="search radius in m")
    f.add_argument("--min-ha", type=float, default=0.5)
    f.add_argument("--limit", type=int, default=20)
    f.add_argument("--places", action="store_true", help="also list named places nearby")
    f.add_argument("--out", help="write the chosen lot to this GeoJSON file")
    f.add_argument("--pick", type=int, default=0, help="index of the lot to write with --out")
    f.set_defaults(func=cmd_find_lots)

    def common(sp, dates=False, workers=8):
        sp.add_argument("site", help="site YAML file")
        sp.add_argument("--workdir", required=True, help="directory for cache, chips and report")
        sp.add_argument("--workers", type=int, default=workers)
        if dates:
            sp.add_argument("--start", type=_date, required=True)
            sp.add_argument("--end", type=_date, required=True)

    def analysis_opts(sp):
        sp.add_argument("--pol", default="vh", choices=["vv", "vh"])
        sp.add_argument("--threshold", type=float, default=3.0, help="dB above baseline = occupied (maps)")
        sp.add_argument("--baseline-pct", type=float, default=10.0, help="percentile used as empty baseline")
        sp.add_argument("--no-optical", action="store_true", help="skip the Sentinel-2 context image")

    d = sub.add_parser("discover", help="find Sentinel-1 scenes covering the site")
    common(d, dates=True, workers=16)
    d.set_defaults(func=cmd_discover)
    pr = sub.add_parser("process", help="calibrate + geocode the discovered scenes")
    common(pr, workers=6)
    pr.add_argument("--no-noise", action="store_true", help="skip thermal noise removal")
    pr.set_defaults(func=cmd_process)
    an = sub.add_parser("analyse", help="compute activity metrics and write the report")
    common(an)
    analysis_opts(an)
    an.set_defaults(func=cmd_analyse)
    r = sub.add_parser("run", help="discover + process + analyse")
    common(r, dates=True, workers=8)
    r.add_argument("--no-noise", action="store_true")
    analysis_opts(r)
    r.set_defaults(func=cmd_run)

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("urllib3", "rasterio"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    a.func(a)


if __name__ == "__main__":
    sys.exit(main())
