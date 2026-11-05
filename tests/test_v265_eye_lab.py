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

    def test_missing_and_nonfinite_evidence_is_not_pass(self):
        with self.assertRaises(ValueError):
            compare({}, {})
        with self.assertRaises(ValueError):
            compare({"left_band": np.array([1.0])}, {})
        with self.assertRaises(ValueError):
            compare({"left_band": np.array([np.nan])}, {"left_band": np.array([1.0])})


class RecordedSourceAdaptiveCalibrationTests(unittest.TestCase):
    def test_private_rejected_final_fails_without_recognition_veto(self):
        import json
        from pathlib import Path
        from neyrobot_prod.v265_source_fidelity import compare_limits

        report = json.loads(
            Path(
                "docs/engineering/v265-transfer-matrix/fidelity-followup.json"
            ).read_text()
        )
        bad = report["human_rejected_generated"]
        failures = compare_limits(
            bad["morphology"], bad["limits_fitted_only_on_benign_source"]["morphology"]
        )
        for channel in ["nose", "mouth", "central_chin", "lower_face"]:
            self.assertIn(channel, failures)
        self.assertTrue(bad["old_geometry_pass"])
        self.assertEqual(bad["old_production_recognition"], 0.778736)
        self.assertFalse(report["production_ready"])

    def test_original_mixed_holdout_replay_reduces_false_rejects(self):
        import json
        from pathlib import Path

        report = json.loads(
            Path(
                "docs/engineering/v265-transfer-matrix/fidelity-followup.json"
            ).read_text()
        )
        rows = report["legacy_holdout_replay"]
        self.assertEqual(len(rows), 20)
        self.assertTrue(all("error" not in r for r in rows))
        failures = sum(
            bool(r["morphology_exceeded"])
            or any(k.endswith("hog") for k in r["appearance_exceeded"])
            for r in rows
        )
        self.assertLess(failures, 12)
