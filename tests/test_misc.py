from s1lot.catalog import _circ_diff, _tod_seconds
from s1lot.s2context import mgrs_tile


def test_mgrs_tiles():
    assert mgrs_tile(8.39, 49.968) == (32, "U", "MA")      # Rüsselsheim
    assert mgrs_tile(2.785, 48.874) == (31, "U", "DQ")     # east of Paris
    assert mgrs_tile(-122.42, 37.77) == (10, "S", "EG")    # San Francisco


def test_time_of_day_helpers():
    assert _tod_seconds("S1C_IW_GRDH_1SDV_20261004T171522_20261004T171547_009738_013650_48BD") == 17 * 3600 + 15 * 60 + 22
    assert _circ_diff(10, 86390) == 20
