# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from neyrobot_prod import dense68_engine_v265 as engine
from neyrobot_prod import selfie_v265_single_owner as v265


class V265SingleOwnerTests(unittest.TestCase):
    def test_render_regression_metrics_pass_without_asymmetry_hard_reject(self) -> None:
        # Exact standard metrics from the 2026-09-01 Render failure. Every true
        # identity/geometry measure is production-grade; only natural eye asymmetry
        # exceeded V264's absolute 0.030 threshold.
        metrics = {
            "target_face_short": 571.0,
            "identity_similarity_cosine": 0.7609,
            "left_eye_error": 0.0102,
            "right_eye_error": 0.0297,
            "interocular_ratio_delta": 0.0256,
            "nose_mouth_axis_delta": 0.0215,
            "inner_face_landmark_nme": 0.0273,
            "eye_asymmetry_delta": 0.0585,
        }
        passed, failures = v265.production_gate(metrics)
        self.assertTrue(passed, failures)
        self.assertEqual(failures, [])

    def test_render_strict_metrics_pass_without_asymmetry_hard_reject(self) -> None:
        metrics = {
            "target_face_short": 571.0,
            "identity_similarity_cosine": 0.7628,
            "left_eye_error": 0.0097,
            "right_eye_error": 0.0256,
            "interocular_ratio_delta": 0.0220,
            "nose_mouth_axis_delta": 0.0228,
            "inner_face_landmark_nme": 0.0271,
            "eye_asymmetry_delta": 0.0373,
        }
        passed, failures = v265.production_gate(metrics)
        self.assertTrue(passed, failures)

    def test_visibly_bad_candidate_is_still_blocked(self) -> None:
        metrics = {
            "target_face_short": 600.0,
            "identity_similarity_cosine": 0.52,
            "left_eye_error": 0.071,
            "right_eye_error": 0.066,
            "interocular_ratio_delta": 0.060,
            "nose_mouth_axis_delta": 0.067,
            "inner_face_landmark_nme": 0.061,
            "eye_asymmetry_delta": 0.010,
        }
        passed, failures = v265.production_gate(metrics)
        self.assertFalse(passed)
        joined = "|".join(failures)
        self.assertIn("identity=", joined)
        self.assertIn("eye_error=", joined)
        self.assertIn("inner_nme=", joined)
        self.assertIn("interocular=", joined)
        self.assertIn("nose_mouth_axis=", joined)

    def test_two_attempt_contract_uses_only_same_local_engine(self) -> None:
        source = inspect.getsource(v265._true_face_transfer_v265)
        self.assertEqual(source.count("engine.transfer_attempt("), 2)
        self.assertEqual(source.count("engine.apply_ocular_lock("), 2)
        self.assertNotIn("provider_rescue", source)
        self.assertNotIn("_true_face_transfer_v262", source)
        self.assertNotIn("Segmind", source)
        self.assertNotIn("PiAPI", source)

    def test_engine_contains_no_old_runtime_or_provider_routes(self) -> None:
        source = Path("neyrobot_prod/dense68_engine_v265.py").read_text(encoding="utf-8")
        self.assertNotIn("selfie_v264_", source)
        self.assertNotIn("selfie_v262_landmark_field_compositor", source)
        self.assertNotIn("provider_rescue", source)
        self.assertNotIn("fallback_v262", source)
        self.assertNotIn("_true_face_transfer_v262", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)

    def test_package_bootstrap_cuts_v247_successor_chain(self) -> None:
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("_install_v265_from_v246_entrypoint", source)
        self.assertNotIn("_install_v248_overlay", source)
        self.assertNotIn("selfie_v264_dense68_roi_production", source)
        self.assertNotIn("install_v247_quality", source)

    def test_delivery_has_no_photo_or_quality_downgrade(self) -> None:
        source = inspect.getsource(v265._deliver_original_only)
        self.assertIn("reply_document", source)
        self.assertNotIn("reply_photo", source)
        self.assertNotIn("_send_photo", source)
        self.assertNotIn("_jpeg", source)

    def test_asymmetry_is_soft_refinement_signal(self) -> None:
        metrics = {
            "target_face_short": 571.0,
            "identity_similarity_cosine": 0.7609,
            "left_eye_error": 0.0102,
            "right_eye_error": 0.0297,
            "interocular_ratio_delta": 0.0256,
            "nose_mouth_axis_delta": 0.0215,
            "inner_face_landmark_nme": 0.0273,
            "eye_asymmetry_delta": 0.0585,
        }
        reasons = engine.visual_refinement_reasons(metrics)
        self.assertTrue(any(reason.startswith("eye_asymmetry=") for reason in reasons))


if __name__ == "__main__":
    unittest.main()
