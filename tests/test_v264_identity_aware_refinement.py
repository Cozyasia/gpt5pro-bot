# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from neyrobot_prod import selfie_v264_dense68_roi_production as v264


class V264IdentityAwareRefinementTests(unittest.TestCase):
    def _good_geometry(self, *, identity: float, face_short: float) -> dict[str, float]:
        return {
            "identity_similarity_cosine": identity,
            "left_eye_error": 0.0110,
            "right_eye_error": 0.0133,
            "interocular_ratio_delta": 0.0076,
            "nose_mouth_axis_delta": 0.0115,
            "inner_face_landmark_nme": 0.0218,
            "eye_asymmetry_delta": 0.0038,
            "target_face_short": face_short,
        }

    def test_large_clean_geometry_still_refines_when_identity_is_suboptimal(self) -> None:
        metrics = self._good_geometry(identity=0.7909, face_short=633.0)
        reasons = v264._visual_refinement_reasons(metrics)
        self.assertTrue(any(item.startswith("identity=") for item in reasons), reasons)
        self.assertFalse(any(item.startswith("eye_error=") for item in reasons), reasons)
        self.assertFalse(any(item.startswith("interocular=") for item in reasons), reasons)

    def test_large_face_above_identity_target_avoids_extra_pass(self) -> None:
        metrics = self._good_geometry(identity=0.842, face_short=633.0)
        self.assertEqual(v264._visual_refinement_reasons(metrics), [])

    def test_medium_face_uses_lower_identity_trigger(self) -> None:
        self.assertTrue(
            any(
                item.startswith("identity=")
                for item in v264._visual_refinement_reasons(
                    self._good_geometry(identity=0.775, face_short=430.0)
                )
            )
        )
        self.assertEqual(
            v264._visual_refinement_reasons(self._good_geometry(identity=0.805, face_short=430.0)),
            [],
        )

    def test_small_face_does_not_double_compute_only_for_identity_score(self) -> None:
        metrics = self._good_geometry(identity=0.700, face_short=330.0)
        self.assertEqual(v264._visual_refinement_reasons(metrics), [])

    def test_strict_candidate_wins_on_real_identity_gain_with_safe_geometry(self) -> None:
        standard = self._good_geometry(identity=0.7909, face_short=633.0)
        strict = dict(
            standard,
            identity_similarity_cosine=0.8215,
            left_eye_error=0.0130,
            right_eye_error=0.0165,
            interocular_ratio_delta=0.0100,
            nose_mouth_axis_delta=0.0130,
            inner_face_landmark_nme=0.0240,
            eye_asymmetry_delta=0.0050,
        )
        self.assertTrue(v264._strict_geometry_safe(standard, strict))
        self.assertTrue(v264._prefer_strict_refinement(standard, strict))

    def test_identity_gain_cannot_win_if_eye_geometry_breaks(self) -> None:
        standard = self._good_geometry(identity=0.7909, face_short=633.0)
        strict = dict(
            standard,
            identity_similarity_cosine=0.8500,
            right_eye_error=0.0600,
            interocular_ratio_delta=0.0450,
        )
        self.assertFalse(v264._strict_geometry_safe(standard, strict))
        self.assertFalse(v264._prefer_strict_refinement(standard, strict))

    def test_geometry_refinement_cannot_trade_away_more_than_two_identity_points(self) -> None:
        standard = dict(
            self._good_geometry(identity=0.8000, face_short=633.0),
            right_eye_error=0.0320,
            interocular_ratio_delta=0.0280,
            inner_face_landmark_nme=0.0360,
            eye_asymmetry_delta=0.0080,
        )
        strict = dict(
            standard,
            identity_similarity_cosine=0.7700,
            right_eye_error=0.0150,
            interocular_ratio_delta=0.0120,
            inner_face_landmark_nme=0.0240,
            eye_asymmetry_delta=0.0040,
        )
        self.assertFalse(v264._prefer_strict_refinement(standard, strict))


if __name__ == "__main__":
    unittest.main()
