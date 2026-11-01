"""Target detection on synthetic scenes with aircraft-like blobs on a known schedule."""

import datetime as dt
import json

import numpy as np
from shapely.geometry import box

from s1lot.site import Site
from s1lot.targets import TargetParams, detect_targets, repeat_test


def _write(path, t, k, rel_orbit, vv):
    name = f"S1C_IW_GRDH_1SDV_{t:%Y%m%dT%H%M%S}_{t:%Y%m%dT%H%M%S}_{k:06d}_000000_0000"
    np.savez(path / f"{name}.npz", vv=vv.astype(np.float32), vh=(vv / 6).astype(np.float32))
    (path / f"{name}.json").write_text(json.dumps(dict(
        product=name, mission="S1C", start=t.isoformat(), abs_orbit=k, rel_orbit=rel_orbit,
        pass_direction="ascending", incidence=35.0, geoloc_rms_px=0.3)))


def test_positions_and_presence_recovered(tmp_path):
    apron = box(24.950, 60.310, 24.962, 60.316)
    site = Site(name="t", lot=apron, exclude=None, timezone="Europe/Helsinki", elevation_m=None, buffer_m=200)
    g = site.grid()
    apron_px = site.masks()["lot_full"]
    rows, cols = np.nonzero(apron_px)
    r0, c0 = rows.min(), cols.min()
    stands = {"A": (r0 + 10, c0 + 10), "B": (r0 + 30, c0 + 40), "C": (r0 + 50, c0 + 20)}
    rng = np.random.default_rng(3)
    truth = {k: [] for k in stands}
    # a fixed bright structure (e.g. a mast) that must not be detected
    mast = (r0 + 40, c0 + 5)
    t0 = dt.datetime(2026, 1, 1, 16, 0)
    for k in range(60):
        t = t0 + dt.timedelta(days=k * 3)
        vv = 0.01 * rng.gamma(4.4, 1 / 4.4, (g.height, g.width))    # concrete ~ -20 dB
        vv[~apron_px] = 0.05 * rng.gamma(4.4, 1 / 4.4, (~apron_px).sum())
        vv[mast[0] - 1: mast[0] + 1, mast[1] - 1: mast[1] + 1] = 5.0
        for name, (r, c) in stands.items():
            occ = {"A": k % 2 == 0, "B": k % 5 < 3, "C": rng.random() < 0.5}[name]
            truth[name].append(occ)
            if occ:  # ~50 x 40 m aircraft, strong scatterer
                vv[r - 2: r + 3, c - 2: c + 2] = 2.0 * rng.gamma(4.4, 1 / 4.4, (5, 4))
        _write(tmp_path, t, k, 7, vv)
        if k % 4 == 0:  # second satellite, other track, 7 minutes later: same aircraft, new speckle
            twin = vv * rng.gamma(4.4, 1 / 4.4, vv.shape)
            _write(tmp_path, t + dt.timedelta(minutes=7), 1000 + k, 9, twin)

    res = detect_targets(site, tmp_path, TargetParams(min_hits_frac=0.1))
    assert len(res.positions) == 3, res.positions
    # map each true stand to the nearest detected position and compare histories
    for name, (r, c) in stands.items():
        x, y = g.transform @ (c + 0.5, r + 0.5)
        d = np.hypot(res.positions.x - x, res.positions.y - y)
        assert d.min() < 20
        pos = res.positions.position[d.idxmin()]
        main = res.scenes[res.scenes.track == "A007"]["product"]
        got = res.presence.loc[pos, main].values.astype(bool)
        assert (got == np.array(truth[name])).mean() > 0.95, name
    # fixed structure and speckle produce (almost) no false alarms
    assert res.scenes.control_density.median() == 0
    # Sentinel-1 repeat test: near-simultaneous twins agree, distant pairs only by chance
    rt = repeat_test(res)
    assert rt["near_pairs"] == 15
    assert rt["near_kappa"] > 0.8 and rt["matched_near"] > 0.8
    assert rt["lag_curve"][-1]["kappa"] < 0.3
