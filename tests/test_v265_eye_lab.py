import unittest
import numpy as np
from tests.test_v265_source_fidelity import points
from neyrobot_prod.v265_eye_fidelity_lab import descriptors, compare


class EyeLabTests(unittest.TestCase):
    def test_photometric_change_and_fixed_landmark_aperture(self):
        p = points()
        y, x = np.mgrid[:400, :320]
        a = np.full((400, 320, 3), 150, np.uint8)
        for cx in [80, 240]:
            a[((x - cx) / 25) ** 2 + ((y - 120) / 8) ** 2 < 1] = 50
            a[(x - cx) ** 2 + (y - 120) ** 2 < 25] = 20
        d = descriptors(a, p)
        benign = (a.astype(float) * 0.8 + 10).astype("uint8")
        for k, v in compare(d, descriptors(benign, p)).items():
            self.assertLess(v, 0.025, k)
        b = a.copy()
        b[((x - 80) / 25) ** 2 + ((y - 120) / 16) ** 2 < 1] = 50
        changes = compare(d, descriptors(b, p))
        for method in ["band", "census", "hog"]:
            self.assertGreater(changes["left_" + method], 0.01)
            self.assertLess(changes["right_" + method], 1e-5)

    def test_flat_eye_is_invalid(self):
        with self.assertRaises(ValueError):
            descriptors(np.full((400, 320, 3), 100, np.uint8), points())
