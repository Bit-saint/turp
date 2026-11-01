"""Find Sentinel-1 GRD scenes covering a site in the public AWS archive.

The ``sentinel-s1-l1c`` bucket (s3://sentinel-s1-l1c, eu-central-1) holds every
GRD product as an unpacked SAFE: ``GRD/{Y}/{M}/{D}/{mode}/{pol}/{product}/``
with a ``productInfo.json`` carrying the footprint. There is no spatial index,
so discovery works in two passes:

1. *Bootstrap*: on a few sample windows of days, check the footprints of every
   product acquired within +-45 min of 06:00 / 18:00 local solar time (when
   Sentinel-1's dawn/dusk orbit crosses the site's longitude). The hits reveal
   the time-of-day of each track that covers the site.
2. *Sweep*: for every day in the period, only check products whose start time
   is within a few minutes of one of those track times.

Listings and footprints are cached on disk, so re-runs and extensions of the
period are cheap.
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import logging
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from shapely.geometry import shape

from .safe import parse_product_name

log = logging.getLogger(__name__)

BUCKET_URL = "https://sentinel-s1-l1c.s3.amazonaws.com"


@dataclass
class Scene:
    product: str
    prefix: str          # key prefix in the bucket, ends with "/"
    mission: str
    start: str           # ISO UTC
    abs_orbit: int
    polarisation: str    # DV, SV, ...

    @property
    def url(self) -> str:
        return f"{BUCKET_URL}/{self.prefix}"

    @property
    def start_dt(self) -> dt.datetime:
        return dt.datetime.fromisoformat(self.start).replace(tzinfo=dt.timezone.utc)


def _tod_seconds(product: str) -> int:
    t = parse_product_name(product)["start"]
    return int(t[9:11]) * 3600 + int(t[11:13]) * 60 + int(t[13:15])


def _circ_diff(a: int, b: int) -> int:
    d = abs(a - b) % 86400
    return min(d, 86400 - d)


class Catalog:
    def __init__(self, cache_dir: str | Path, mode: str = "IW", polarisations=("DV",),
                 workers: int = 16, session: requests.Session | None = None):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self.polarisations = tuple(polarisations)
        self.workers = workers
        self.http = session or requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_maxsize=max(workers, 10))
        self.http.mount("https://", adapter)
        self._fp_path = self.cache / "footprints.json"
        self._fp = json.loads(self._fp_path.read_text()) if self._fp_path.exists() else {}
        self._lock = threading.Lock()

    # ---------------- low level ----------------
    def _get(self, url: str, **kw) -> requests.Response:
        last = None
        for _ in range(4):
            try:
                r = self.http.get(url, timeout=60, **kw)
                if r.status_code == 200:
                    return r
                last = RuntimeError(f"HTTP {r.status_code} for {url}")
            except requests.RequestException as e:  # network hiccup: retry
                last = e
        raise last

    def list_day(self, day: dt.date) -> list[str]:
        """All product prefixes for one day (cached once the day is complete)."""
        cache = self.cache / "listings" / f"{day.isoformat()}.json"
        if cache.exists():
            return json.loads(cache.read_text())
        out: list[str] = []
        for pol in self.polarisations:
            marker = ""
            while True:
                txt = self._get(BUCKET_URL, params={
                    "prefix": f"GRD/{day.year}/{day.month}/{day.day}/{self.mode}/{pol}/",
                    "delimiter": "/", "marker": marker}).text
                ps = re.findall(r"<Prefix>(GRD/[^<]+/S1[^<]+/)</Prefix>", txt)
                out += ps
                if "<IsTruncated>true</IsTruncated>" in txt and ps:
                    marker = ps[-1]
                else:
                    break
        # products keep arriving for ~a day after acquisition; only cache settled days
        if day < dt.date.today() - dt.timedelta(days=3):
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(json.dumps(out))
        return out

    def footprint(self, prefix: str):
        with self._lock:
            if prefix in self._fp:
                return shape(self._fp[prefix])
        geom = self._get(f"{BUCKET_URL}/{prefix}productInfo.json").json()["footprint"]
        with self._lock:
            self._fp[prefix] = geom
        return shape(geom)

    def _save(self):
        with self._lock:
            self._fp_path.write_text(json.dumps(self._fp))

    # ---------------- discovery ----------------
    def _covering(self, prefixes: list[str], geom) -> list[str]:
        def check(p):
            try:
                return p if self.footprint(p).contains(geom) else None
            except Exception as e:  # noqa: BLE001 - one bad product must not stop the run
                log.warning("footprint failed for %s: %s", p, e)
                return None
        with cf.ThreadPoolExecutor(self.workers) as ex:
            hits = [p for p in ex.map(check, prefixes) if p]
        self._save()
        return hits

    def _list_days(self, days: list[dt.date]) -> dict[dt.date, list[str]]:
        with cf.ThreadPoolExecutor(min(self.workers, 8)) as ex:
            return dict(zip(days, ex.map(self.list_day, days)))

    def bootstrap_tracks(self, geom, start: dt.date, end: dt.date, sample_days: int = 12,
                         n_windows: int = 3, window_min: int = 45) -> list[int]:
        """Learn the time-of-day (s, UTC) of every track that covers ``geom``."""
        lon = geom.centroid.x
        solar = -lon / 15 * 3600  # UTC offset of local solar time
        centres = [(6 * 3600 + solar) % 86400, (18 * 3600 + solar) % 86400]
        span = (end - start).days + 1
        starts = sorted({start + dt.timedelta(days=int(i * max(span - sample_days, 0) / max(n_windows - 1, 1)))
                         for i in range(n_windows)})
        days = sorted({s + dt.timedelta(d) for s in starts for d in range(sample_days) if s + dt.timedelta(d) <= end})
        listing = self._list_days(days)
        cands = [p for ps in listing.values() for p in ps
                 if any(_circ_diff(_tod_seconds(p), c) <= window_min * 60 for c in centres)]
        log.info("bootstrap: %d days, %d candidate products", len(days), len(cands))
        hits = self._covering(cands, geom)
        tods = sorted(_tod_seconds(p) for p in hits)
        # cluster times of day (same track repeats within ~1 min)
        tracks: list[list[int]] = []
        for t in tods:
            if tracks and t - tracks[-1][-1] <= 120:
                tracks[-1].append(t)
            else:
                tracks.append([t])
        centres = [int(sum(c) / len(c)) for c in tracks]
        log.info("bootstrap found %d track time(s): %s", len(centres),
                 ", ".join(f"{c // 3600:02d}:{c % 3600 // 60:02d}" for c in centres))
        return centres

    def discover(self, geom, start: dt.date, end: dt.date, track_tods: list[int] | None = None,
                 tolerance_s: int = 120) -> list[Scene]:
        if track_tods is None:
            track_tods = self.bootstrap_tracks(geom, start, end)
        if not track_tods:
            return []
        days = [start + dt.timedelta(d) for d in range((end - start).days + 1)]
        listing = self._list_days(days)
        cands = [p for ps in listing.values() for p in ps
                 if any(_circ_diff(_tod_seconds(p), t) <= tolerance_s for t in track_tods)]
        log.info("sweep: %d days, %d candidate products", len(days), len(cands))
        hits = self._covering(cands, geom)
        scenes = []
        seen_takes = set()
        for p in sorted(hits):
            name = p.rstrip("/").split("/")[-1]
            m = parse_product_name(name)
            # adjacent slices of one datatake can both contain a site lying in their overlap
            if (m["mission"], m["take"]) in seen_takes:
                continue
            seen_takes.add((m["mission"], m["take"]))
            s = m["start"]
            scenes.append(Scene(
                product=name, prefix=p, mission=m["mission"],
                start=f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}",
                abs_orbit=int(m["abs_orbit"]), polarisation=m["pol"]))
        scenes.sort(key=lambda s: s.start)
        return scenes


def save_scenes(scenes: list[Scene], path: str | Path) -> None:
    Path(path).write_text(json.dumps([asdict(s) for s in scenes], indent=1))


def load_scenes(path: str | Path) -> list[Scene]:
    return [Scene(**d) for d in json.loads(Path(path).read_text())]
