"""End-to-end analysis on synthetic chips with a known opening schedule."""

import datetime as dt
import json

import numpy as np
import pytest
from shapely.geometry import box

from s1lot.metrics import analyse
from s1lot.site import Site


@pytest.fixture
def site():
    lot = box(8.389, 49.967, 8.391, 49.969)
    return Site(name="test", lot=lot, exclude=None, timezone="Europe/Berlin", elevation_m=None,
                buffer_m=150, country=None)


def _write_chips(site, tmp_path):
    g = site.grid()
    lot = site.masks()["lot_full"]
    rng = np.random.default_rng(0)
    start = dt.datetime(2026, 3, 2, 17, 15)
    for k in range(120):
        evening = k % 2 == 0
        t = start + dt.timedelta(days=k // 2 * 3) - (dt.timedelta(hours=11, minutes=40) if not evening else dt.timedelta())
        busy = evening and t.weekday() != 6
        base = np.full((g.height, g.width), 0.02)          # empty asphalt ~ -17 dB
        base[~lot] = 0.08                                  # surroundings ~ -11 dB
        occ = (rng.random(base.shape) < (0.6 if busy else 0.03)) & lot
        mean = np.where(occ, 0.6, base)                    # cars ~ -2 dB
        vv = mean * rng.gamma(4.4, 1 / 4.4, base.shape)    # speckle, ENL 4.4
        name = f"S1C_IW_GRDH_1SDV_{t:%Y%m%dT%H%M%S}_{t:%Y%m%dT%H%M%S}_{k:06d}_000000_0000"
        np.savez(tmp_path / f"{name}.npz", vv=vv.astype(np.float32), vh=(vv / 5).astype(np.float32))
        meta = dict(product=name, mission="S1C", start=t.isoformat(), abs_orbit=k, rel_orbit=15 if evening else 139,
                    pass_direction="ascending" if evening else "descending", incidence=39.0, geoloc_rms_px=0.3)
        (tmp_path / f"{name}.json").write_text(json.dumps(meta))


def test_activity_follows_schedule(site, tmp_path):
    _write_chips(site, tmp_path)
    an = analyse(site, tmp_path)
    df = an.scenes
    ev = df[df.pass_slot == "evening"]
    open_ = ev[ev.daytype != "Sun/holiday"].activity
    closed = ev[ev.daytype == "Sun/holiday"].activity
    morning = df[df.pass_slot == "morning"].activity
    assert open_.median() > 80
    assert closed.median() < 20 and morning.median() < 20
    s = an.summary()
    assert s["evening_open_vs_closed"]["mannwhitney_p"] < 1e-3
    assert set(df.track) == {"A015", "D139"}
