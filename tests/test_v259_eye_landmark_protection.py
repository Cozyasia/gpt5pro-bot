# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V259EyeLandmarkProtectionTests(unittest.TestCase):
    def test_v259_is_loaded_after_v258(self) -> None:
        source = Path("neyrobot_prod/selfie_v247_provider_supersample.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v259_eye_landmark_protection", source)
        self.assertLess(source.index("install_v258_inner_face()"), source.index("install_v259_eye_protection()"))
        self.assertIn("AI_SELFIE_V259_INSTALL", source)

    def test_v259_corrects_each_eye_from_yunet_landmark_residual(self) -> None:
        source = Path("neyrobot_prod/selfie_v259_eye_landmark_protection.py").read_text(encoding="utf-8")
        self.assertIn("projected_pts = _project_points(matrix, source_pts)", source)
        self.assertIn("for eye_index in (0, 1):", source)
        self.assertIn("target_pts[eye_index]", source)
        self.assertIn("projected_pts[eye_index]", source)
        self.assertIn("_EYE_MAX_LOCAL_SHIFT = 36.0", source)
        self.assertIn("shifted_matched = _shift_frame(matched, dx, dy)", source)
        self.assertIn("shifted_raw = _shift_frame(warped, dx, dy)", source)
        self.assertIn("eye_landmark_local_correction=true", source)

    def test_v259_protects_raw_eye_core_after_lab_poisson(self) -> None:
        source = Path("neyrobot_prod/selfie_v259_eye_landmark_protection.py").read_text(encoding="utf-8")
        self.assertIn("_EYE_SUPPORT_WEIGHT = 0.92", source)
        self.assertIn("_EYE_RAW_CORE_WEIGHT = 0.97", source)
        self.assertIn("_EYE_RAW_MIX = 0.90", source)
        self.assertIn("gate=detail_core", source)
        self.assertIn("ocular_source = np.clip(", source)
        self.assertIn("shifted_raw.astype(np.float32) * _EYE_RAW_MIX", source)
        self.assertIn("eye_masks_hard_gated=true", source)

    def test_v259_preserves_v258_two_zone_and_lossless_firewall_contracts(self) -> None:
        source = Path("neyrobot_prod/selfie_v259_eye_landmark_protection.py").read_text(encoding="utf-8")
        self.assertIn("v258._core_erode_fraction", source)
        self.assertIn("v258._detail_reinject_for_coverage", source)
        self.assertIn("v255._warp_source_face_gate", source)
        self.assertIn("v254._target_face_mask", source)
        self.assertIn("v256._MAX_REAL_SOURCE_SCALE", source)
        self.assertIn("v256._MIN_NATIVE_FACE_SHORT", source)
        self.assertIn("final[:, firewall_x:] = target[:, firewall_x:]", source)
        self.assertIn("delivery._deliver = v253._deliver_original", source)
        self.assertIn("fallback_v258", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)
        self.assertNotIn("PreCheckoutQueryHandler", source)

    def test_package_version_is_v259_with_v258_compatibility_marker(self) -> None:
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v259-eye-landmark-protection-2026-08-26"', source)
        self.assertIn("v258-inner-face-integration-2026-08-24", source)
        self.assertIn("v257-native-sampling-guard-2026-08-22", source)


if __name__ == "__main__":
    unittest.main()
