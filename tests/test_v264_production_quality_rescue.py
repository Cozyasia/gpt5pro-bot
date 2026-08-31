# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path

from neyrobot_prod import selfie_v264_production_quality_rescue as guard


class V264ProductionQualityRescueTests(unittest.TestCase):
    def test_known_good_large_face_passes_production_gate(self) -> None:
        metrics = {
            "target_face_short": 633.0,
            "identity_similarity_cosine": 0.7909,
            "left_eye_error": 0.0110,
            "right_eye_error": 0.0133,
            "interocular_ratio_delta": 0.0076,
            "nose_mouth_axis_delta": 0.0115,
            "inner_face_landmark_nme": 0.0218,
            "eye_asymmetry_delta": 0.0038,
        }
        passed, failures = guard._production_gate(metrics)
        self.assertTrue(passed)
        self.assertEqual(failures, [])

    def test_visibly_bad_large_face_is_blocked(self) -> None:
        metrics = {
            "target_face_short": 674.0,
            "identity_similarity_cosine": 0.5470,
            "left_eye_error": 0.0666,
            "right_eye_error": 0.0503,
            "interocular_ratio_delta": 0.0111,
            "nose_mouth_axis_delta": 0.0149,
            "inner_face_landmark_nme": 0.0526,
            "eye_asymmetry_delta": 0.0472,
        }
        passed, failures = guard._production_gate(metrics)
        self.assertFalse(passed)
        joined = "|".join(failures)
        self.assertIn("identity=0.5470<0.6800", joined)
        self.assertIn("eye_error=0.0666>0.0450", joined)
        self.assertIn("inner_nme=0.0526>0.0500", joined)
        self.assertIn("eye_asymmetry=0.0472>0.0300", joined)

    def test_previous_borderline_but_usable_case_is_not_catastrophically_rejected(self) -> None:
        metrics = {
            "target_face_short": 653.0,
            "identity_similarity_cosine": 0.7217,
            "left_eye_error": 0.0359,
            "right_eye_error": 0.0189,
            "interocular_ratio_delta": 0.0203,
            "nose_mouth_axis_delta": 0.0176,
            "inner_face_landmark_nme": 0.0365,
            "eye_asymmetry_delta": 0.0067,
        }
        passed, failures = guard._production_gate(metrics)
        self.assertTrue(passed, failures)

    def test_guard_keeps_two_candidate_contract(self) -> None:
        source = Path("neyrobot_prod/selfie_v264_production_quality_rescue.py").read_text(encoding="utf-8")
        body = source[source.index("async def _true_face_transfer_v264_guarded"):source.index("def install()")]
        self.assertEqual(body.count("v264._transfer_attempt_roi("), 2)
        self.assertIn("Attempt 1: stable production V264 standard", body)
        self.assertIn("Attempt 2 is provider rescue", body)
        self.assertIn("max_attempts=2", source)
        self.assertIn("person_b_restored=true", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("PreCheckoutQueryHandler", source)
        self.assertNotIn("add_handler", source)

    def test_stage1_scaffold_locks_age_head_and_hair(self) -> None:
        source = Path("neyrobot_prod/selfie_v264_stage1_scaffold_guard.py").read_text(encoding="utf-8")
        self.assertIn("AGE/HEAD LOCK", source)
        self.assertIn("Never adultize a child/teen", source)
        self.assertIn("hairline", source)
        self.assertIn("hair colour", source)
        self.assertIn("OUTER HEAD AND AGE PROPORTIONS ARE NOT DISPOSABLE", source)
        self.assertIn("full_photo_to_gemini=false", source)

    def test_package_installs_scaffold_before_production_guard(self) -> None:
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v264_stage1_scaffold_guard", package)
        self.assertIn("selfie_v264_production_quality_rescue", package)
        self.assertLess(package.index("_install_v264_stage1_scaffold()"), package.index("_install_v264_production_guard()"))
        self.assertIn("production_gate_plus_isolated_provider_rescue", package)


if __name__ == "__main__":
    unittest.main()
