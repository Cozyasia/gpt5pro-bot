# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from neyrobot_prod import selfie_v265_single_owner as v265


def _m(
    *,
    identity: float = 0.780,
    left: float = 0.020,
    right: float = 0.022,
    asym: float = 0.006,
    inter: float = 0.020,
    axis: float = 0.020,
    inner: float = 0.030,
) -> dict[str, float]:
    return {
        "target_face_short": 600.0,
        "identity_similarity_cosine": identity,
        "left_eye_error": left,
        "right_eye_error": right,
        "eye_asymmetry_delta": asym,
        "interocular_ratio_delta": inter,
        "nose_mouth_axis_delta": axis,
        "inner_face_landmark_nme": inner,
    }


class V265MonotonicRefinementTests(unittest.TestCase):
    def test_good_pre_lock_worse_post_lock_keeps_pre(self) -> None:
        pre = _m(identity=0.780, left=0.018, right=0.021, asym=0.006)
        post = _m(identity=0.755, left=0.026, right=0.028, asym=0.020)
        accepted, reasons = v265._ocular_monotonic_decision(pre, post)
        self.assertFalse(accepted)
        self.assertTrue(any(reason.startswith("identity=") for reason in reasons))
        self.assertTrue(any(reason.startswith("left_eye_error=") for reason in reasons))

    def test_good_pre_lock_better_post_lock_selects_post(self) -> None:
        pre = _m(identity=0.760, left=0.025, right=0.027, asym=0.010, inter=0.026, axis=0.026, inner=0.034)
        post = _m(identity=0.790, left=0.020, right=0.021, asym=0.007, inter=0.022, axis=0.022, inner=0.030)
        accepted, reasons = v265._ocular_monotonic_decision(pre, post)
        self.assertTrue(accepted, reasons)
        self.assertIn("identity", reasons)

    def test_standard_pass_strict_worse_keeps_standard(self) -> None:
        standard = _m(identity=0.790, left=0.018, right=0.020, inter=0.018, axis=0.018, inner=0.028)
        strict = _m(identity=0.770, left=0.026, right=0.028, inter=0.026, axis=0.025, inner=0.034)
        standard_hard, _ = v265.production_gate(standard)
        strict_hard, _ = v265.production_gate(strict)
        self.assertTrue(standard_hard)
        self.assertTrue(strict_hard)
        self.assertEqual(
            v265._final_candidate_decision(standard_hard, standard, strict_hard, strict),
            "standard",
        )

    def test_standard_fail_strict_pass_selects_strict(self) -> None:
        standard = _m(axis=0.053)
        strict = _m(identity=0.800, axis=0.030)
        standard_hard, _ = v265.production_gate(standard)
        strict_hard, _ = v265.production_gate(strict)
        self.assertFalse(standard_hard)
        self.assertTrue(strict_hard)
        self.assertEqual(
            v265._final_candidate_decision(standard_hard, standard, strict_hard, strict),
            "strict",
        )

    def test_both_fail_rejects(self) -> None:
        standard = _m(axis=0.053)
        strict = _m(right=0.052, axis=0.056)
        standard_hard, _ = v265.production_gate(standard)
        strict_hard, _ = v265.production_gate(strict)
        self.assertFalse(standard_hard)
        self.assertFalse(strict_hard)
        self.assertEqual(
            v265._final_candidate_decision(standard_hard, standard, strict_hard, strict),
            "reject",
        )

    def test_ocular_refinement_cannot_turn_pass_into_fail_and_be_selected(self) -> None:
        pre = _m(axis=0.049, right=0.049)
        post = _m(identity=0.790, axis=0.051, right=0.051)
        pre_hard, _ = v265.production_gate(pre)
        post_hard, _ = v265.production_gate(post)
        self.assertTrue(pre_hard)
        self.assertFalse(post_hard)
        accepted, reasons = v265._ocular_monotonic_decision(pre, post)
        self.assertFalse(accepted)
        self.assertIn("hard_pass_to_fail", reasons)

    def test_natural_eye_asymmetry_cannot_force_destructive_correction(self) -> None:
        # Eye asymmetry is deliberately not a V265 hard gate. A refinement that makes
        # asymmetry smaller but damages identity/per-eye geometry must still be discarded.
        pre = _m(identity=0.790, left=0.018, right=0.021, asym=0.030)
        post = _m(identity=0.770, left=0.026, right=0.028, asym=0.005)
        pre_hard, failures = v265.production_gate(pre)
        self.assertTrue(pre_hard, failures)
        accepted, reasons = v265._ocular_monotonic_decision(pre, post)
        self.assertFalse(accepted)
        self.assertTrue(any(reason.startswith("identity=") for reason in reasons))

    def test_replay_capture_is_disabled_by_default_and_exact_when_enabled(self) -> None:
        import os
        import tempfile
        from pathlib import Path

        old = os.environ.pop("V265_REPLAY_CAPTURE_DIR", None)
        try:
            self.assertIsNone(v265._capture_replay_inputs(b"stage1-exact", b"source-exact"))
            with tempfile.TemporaryDirectory() as td:
                os.environ["V265_REPLAY_CAPTURE_DIR"] = td
                token = v265._capture_replay_inputs(b"stage1-exact", b"source-exact")
                self.assertTrue(token)
                root = Path(td)
                self.assertEqual((root / f"{token}.stage1.bin").read_bytes(), b"stage1-exact")
                self.assertEqual((root / f"{token}.source_photo3.bin").read_bytes(), b"source-exact")
        finally:
            if old is None:
                os.environ.pop("V265_REPLAY_CAPTURE_DIR", None)
            else:
                os.environ["V265_REPLAY_CAPTURE_DIR"] = old

    def test_metric_block_contract_includes_full_pre_post_fields(self) -> None:
        import inspect

        source = inspect.getsource(v265._metric_block_log)
        for token in (
            "identity_similarity_cosine",
            "left_eye_error",
            "right_eye_error",
            "worst_eye",
            "eye_asymmetry",
            "interocular_ratio_delta",
            "nose_mouth_axis_delta",
            "inner_face_landmark_nme",
            "hard_gate",
            "person_b=pixel_locked",
            "no_neck=true",
            "independent_eye_patch=false",
            "pid=",
            "host=",
        ):
            self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
