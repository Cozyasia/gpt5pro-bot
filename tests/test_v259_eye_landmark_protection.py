# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V259EyeLandmarkProtectionTests(unittest.TestCase):
    def test_v259_is_loaded_after_v258_and_before_v260_v261_v262(self) -> None:
        source = Path("neyrobot_prod/selfie_v247_provider_supersample.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v259_eye_landmark_protection", source)
        self.assertIn("selfie_v260_eye_roi_memory_safe", source)
        self.assertIn("selfie_v261_edge_harmonization", source)
        self.assertIn("selfie_v262_landmark_field_compositor", source)
        self.assertLess(source.index("install_v258_inner_face()"), source.index("install_v259_eye_protection()"))
        self.assertLess(source.index("install_v259_eye_protection()"), source.index("install_v260_eye_roi()"))
        self.assertLess(source.index("install_v260_eye_roi()"), source.index("install_v261_edge_harmonization()"))
        self.assertLess(source.index("install_v261_edge_harmonization()"), source.index("install_v262_landmark_field()"))
        self.assertIn("AI_SELFIE_V262_INSTALL", source)

    def test_v259_historical_full_frame_eye_path_remains_documented(self) -> None:
        source = Path("neyrobot_prod/selfie_v259_eye_landmark_protection.py").read_text(encoding="utf-8")
        self.assertIn("projected_pts = _project_points(matrix, source_pts)", source)
        self.assertIn("for eye_index in (0, 1):", source)
        self.assertIn("_EYE_MAX_LOCAL_SHIFT = 36.0", source)
        self.assertIn("shifted_matched = _shift_frame(matched, dx, dy)", source)
        self.assertIn("shifted_raw = _shift_frame(warped, dx, dy)", source)
        self.assertIn("eye_landmark_local_correction=true", source)

    def test_v259_preserves_v258_two_zone_and_lossless_firewall_contracts(self) -> None:
        source = Path("neyrobot_prod/selfie_v259_eye_landmark_protection.py").read_text(encoding="utf-8")
        self.assertIn("v258._core_erode_fraction", source)
        self.assertIn("v258._detail_reinject_for_coverage", source)
        self.assertIn("v256._MAX_REAL_SOURCE_SCALE", source)
        self.assertIn("v256._MIN_NATIVE_FACE_SHORT", source)
        self.assertIn("final[:, firewall_x:] = target[:, firewall_x:]", source)
        self.assertIn("delivery._deliver = v253._deliver_original", source)
        self.assertIn("fallback_v258", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)
        self.assertNotIn("PreCheckoutQueryHandler", source)

    def test_v259_eye_patch_is_historical_and_not_in_v265_execution(self) -> None:
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        engine = Path("neyrobot_prod/dense68_engine_v265.py").read_text(encoding="utf-8")
        owner = Path("neyrobot_prod/selfie_v265_single_owner.py").read_text(encoding="utf-8")
        self.assertIn('PRODUCTION_SELFIE_RUNTIME = "v265"', package)
        self.assertNotIn("selfie_v259_eye_landmark_protection", package)
        self.assertNotIn("selfie_v259_eye_landmark_protection", engine)
        self.assertNotIn("selfie_v259_eye_landmark_protection", owner)
        self.assertNotIn("_shift_frame(", engine)


if __name__ == "__main__":
    unittest.main()
