"""Measurement regressions: numerical invariants, invalid evidence, eye-only drift."""

import unittest
import numpy as np
from neyrobot_prod import v265_source_fidelity as f


def points():
    rng = np.random.default_rng(265)
    p = rng.uniform([60, 80], [260, 350], (68, 2))
    angles = np.linspace(0, 2 * np.pi, 6, endpoint=False)
    for start, x in [(36, 80), (42, 240)]:
        p[start : start + 6] = np.column_stack(
            [x + 25 * np.cos(angles), 120 + 8 * np.sin(angles)]
        )
    return p


class SourceFidelityTests(unittest.TestCase):
    def test_roll_uniform_scale_translation_invariant(self):
        p = points()
        t = 0.31
        m = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]]) * 1.4
        for value in f.morphology(p, p @ m.T + [120, 35]).values():
            self.assertLess(value, 1e-12)

    def test_local_drift_cannot_align_itself_away(self):
        p = points()
        for region in ["nose", "mouth", "outline", "central_chin", "lower_face"]:
            q = p.copy()
            q[list(f.REGIONS[region]), 1] += 20
            self.assertGreater(f.morphology(p, q)[region], 0.1)

    def test_eye_pixels_detect_change_with_identical_landmarks(self):
        p = points()
        y, x = np.mgrid[:400, :320]
        a = np.full((400, 320, 3), 160, np.uint8)
        for cx in [80, 240]:
            a[((x - cx) / 25) ** 2 + ((y - 120) / 8) ** 2 < 1] = 40
        b = a.copy()
        b[((x - 80) / 25) ** 2 + ((y - 120) / 16) ** 2 < 1] = 40
        self.assertEqual(f.morphology(p, p)["eyes"], 0)
        self.assertGreater(f.appearance(a, b, p, p)["eye_left_appearance"], 0.1)
        self.assertLess(f.appearance(a, b, p, p)["eye_right_appearance"], 1e-10)

    def test_gain_bias_does_not_mimic_eye_drift(self):
        p = points()
        rng = np.random.default_rng(0)
        a = rng.integers(30, 180, (400, 320, 3), dtype=np.uint8)
        b = np.clip(a.astype(float) * 0.8 + 12, 0, 255).astype(np.uint8)
        self.assertLess(max(f.appearance(a, b, p, p).values()), 0.05)

    def test_missing_nonfinite_and_degenerate_evidence_is_not_pass(self):
        p = points()
        p[42:48] = p[36:42]
        with self.assertRaises(ValueError):
            f.eye_frame(p)
        with self.assertRaises(ValueError):
            f.compare_limits({"a": float("nan")}, {"a": 1})
        with self.assertRaises(ValueError):
            f.compare_limits({}, {"a": 1})
        with self.assertRaises(ValueError):
            f.measured_limits([])

    def test_threshold_uses_only_observed_calibration_rows(self):
        limits = f.measured_limits(
            [{"nose": 0.01, "mouth": 0.02}, {"nose": 0.03, "mouth": 0.01}]
        )
        self.assertEqual(limits, {"nose": 0.03, "mouth": 0.02})
        self.assertEqual(
            f.compare_limits({"nose": 0.04, "mouth": 0.01}, limits), ["nose"]
        )


class RecordedImageCalibrationTests(unittest.TestCase):
    def test_real_rejected_image_exceeds_independent_public_envelope(self):
        import json
        from pathlib import Path

        report = json.loads(
            Path("tests/fixtures/v265_source_fidelity_audit.json").read_text()
        )
        bad = next(
            c for c in report["cases"] if c["category"] == "human_rejected_generated"
        )
        self.assertAlmostEqual(bad["recognition_cosine"], 0.7857398987, places=6)
        failed = f.compare_limits(bad["metrics"], report["limits"])
        for name in [
            "mouth",
            "nose",
            "central_chin",
            "lower_face",
            "outline",
            "inner_face",
        ]:
            self.assertIn(name, failed)
        self.assertFalse(report["production_ready"])
        # Neither recognition nor measured rejection establishes a deployable gate.
        heldout = [c for c in report["cases"] if c.get("split") == "holdout"]
        self.assertTrue(any(c.get("exceeded") for c in heldout))
        self.assertEqual(report["human_approved_generated_positives"], 0)

    def test_calibration_rows_and_drift_categories_are_preserved(self):
        import json
        from pathlib import Path

        report = json.loads(
            Path("tests/fixtures/v265_source_fidelity_audit.json").read_text()
        )
        training = [c["metrics"] for c in report["cases"] if c.get("split") == "train"]
        self.assertEqual(f.measured_limits(training), report["limits"])
        for m in training:
            self.assertEqual(f.compare_limits(m, report["limits"]), [])
        for region in ["mouth", "nose", "jaw_chin", "lower_face", "eyes", "combined"]:
            cases = [
                c
                for c in report["cases"]
                if c["category"] == "controlled_drift" and c["variant"] == region
            ]
            self.assertEqual(len(cases), 7)
            self.assertTrue(all(c.get("exceeded") or c.get("error") for c in cases))
