import numpy as np

from s1lot.safe import CalibrationLUT, NoiseLUT, calibrate, parse_product_name, relative_orbit_from_manifest

CAL = """<calibration><calibrationVectorList count="2">
<calibrationVector><azimuthTime/><line>0</line><pixel count="3">0 10 20</pixel>
<sigmaNought count="3">100 200 300</sigmaNought><betaNought/><gamma/><dn/></calibrationVector>
<calibrationVector><azimuthTime/><line>10</line><pixel count="3">0 10 20</pixel>
<sigmaNought count="3">200 300 400</sigmaNought><betaNought/><gamma/><dn/></calibrationVector>
</calibrationVectorList></calibration>"""

NOISE = """<noise><noiseRangeVectorList count="2">
<noiseRangeVector><azimuthTime/><line>0</line><pixel count="2">0 20</pixel><noiseRangeLut count="2">10 30</noiseRangeLut></noiseRangeVector>
<noiseRangeVector><azimuthTime/><line>10</line><pixel count="2">0 20</pixel><noiseRangeLut count="2">10 30</noiseRangeLut></noiseRangeVector>
</noiseRangeVectorList><noiseAzimuthVectorList count="2">
<noiseAzimuthVector><swath>IW1</swath><firstAzimuthLine>0</firstAzimuthLine><firstRangeSample>0</firstRangeSample>
<lastAzimuthLine>10</lastAzimuthLine><lastRangeSample>9</lastRangeSample><line count="2">0 10</line><noiseAzimuthLut count="2">1 2</noiseAzimuthLut></noiseAzimuthVector>
<noiseAzimuthVector><swath>IW2</swath><firstAzimuthLine>0</firstAzimuthLine><firstRangeSample>10</firstRangeSample>
<lastAzimuthLine>10</lastAzimuthLine><lastRangeSample>20</lastRangeSample><line count="1">0</line><noiseAzimuthLut count="1">0.5</noiseAzimuthLut></noiseAzimuthVector>
</noiseAzimuthVectorList></noise>"""


def test_calibration_lut_bilinear():
    cal = CalibrationLUT.parse(CAL)
    lut = cal.sigma_lut(np.array([0, 5, 10]), np.array([0, 5, 20]))
    np.testing.assert_allclose(lut, [[100, 150, 300], [150, 200, 350], [200, 250, 400]])


def test_noise_range_times_azimuth():
    n = NoiseLUT.parse(NOISE)
    out = n.noise(np.array([0, 5]), np.array([0, 10, 20]))
    # range LUT 10..30 linear in pixel; IW1 (cols 0-9) azimuth 1 -> 1.5, IW2 constant 0.5
    np.testing.assert_allclose(out, [[10, 10, 15], [15, 10, 15]])


def test_calibrate_subtracts_noise_and_masks_nodata():
    cal, n = CalibrationLUT.parse(CAL), NoiseLUT.parse(NOISE)
    dn = np.array([[100, 0], [100, 100]], dtype=np.uint16)
    s0 = calibrate(dn, cal, n, row0=0, col0=0)
    assert np.isnan(s0[0, 1])
    np.testing.assert_allclose(s0[0, 0], (100**2 - 10) / 100**2)
    s0_nonoise = calibrate(dn, cal, None, 0, 0)
    assert s0_nonoise[0, 0] > s0[0, 0]


def test_product_name_and_manifest():
    m = parse_product_name("S1C_IW_GRDH_1SDV_20261004T171522_20261004T171547_009738_013650_48BD")
    assert m["mission"] == "S1C" and m["abs_orbit"] == "009738" and m["pol"] == "DV"
    assert relative_orbit_from_manifest('<x><safe:relativeOrbitNumber type="start">15</safe:relativeOrbitNumber>') == 15
    assert relative_orbit_from_manifest(b'<safe:relativeOrbitNumber type="start">139<') == 139
