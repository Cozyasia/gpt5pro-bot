# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V262LandmarkFieldCompositorTests(unittest.TestCase):
    def test_v262_loads_after_v261_as_final_owner(self) -> None:
        source = Path("neyrobot_prod/selfie_v247_provider_supersample.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v262_landmark_field_compositor", source)
        self.assertLess(
            source.index("install_v261_edge_harmonization()"),
            source.index("install_v262_landmark_field()"),
        )
        self.assertIn("AI_SELFIE_V262_INSTALL", source)

    def test_v262_replaces_independent_eye_patch_with_one_all5_field(self) -> None:
        source = Path("neyrobot_prod/selfie_v262_landmark_field_compositor.py").read_text(encoding="utf-8")
        self.assertIn("projected_pts = _project_points(matrix, source_pts)", source)
        self.assertIn("residuals = np.asarray(target_pts", source)
        self.assertIn("for i in range(5):", source)
        self.assertIn("corrected_roi = cv2.remap(", source)
        self.assertIn("landmark_field=all5", source)
        self.assertIn("independent_eye_patch=false", source)
        self.assertNotIn("v260._source_pixel_transfer_v260", source)
        self.assertNotIn("for eye_index in (0, 1):", source)

    def test_v262_final_mask_is_landmark_hull_not_ellipse(self) -> None:
        source = Path("neyrobot_prod/selfie_v262_landmark_field_compositor.py").read_text(encoding="utf-8")
        self.assertIn("cv2.convexHull", source)
        self.assertIn("cv2.fillConvexPoly", source)
        self.assertIn("mask=landmark_anatomical_hull", source)
        self.assertIn("ellipse_final_mask=false", source)
        self.assertNotIn("cv2.ellipse", source)
        # Descriptive comments may mention the historical V255 gate; forbid an
        # executable call rather than the symbol name itself.
        self.assertNotIn("v255._warp_source_face_gate(", source)
        self.assertNotIn("v254._target_face_mask(", source)

    def test_v262_has_no_broad_raw_source_core(self) -> None:
        source = Path("neyrobot_prod/selfie_v262_landmark_field_compositor.py").read_text(encoding="utf-8")
        self.assertIn("integrated = cv2.seamlessClone", source)
        self.assertIn("source_low = cv2.GaussianBlur", source)
        self.assertIn("detail = matched_roi.astype(np.float32) - source_low.astype(np.float32)", source)
        self.assertIn("source_high_frequency_only=true", source)
        self.assertIn("raw_low_frequency_reinject=false", source)
        self.assertIn("solid_source_core=false", source)
        self.assertNotIn("detail_reinject=0.88", source)
        self.assertNotIn("detail_reinject=0.89", source)

    def test_v262_preserves_sampling_firewall_fallback_and_lossless_delivery(self) -> None:
        source = Path("neyrobot_prod/selfie_v262_landmark_field_compositor.py").read_text(encoding="utf-8")
        self.assertIn("v256._MAX_REAL_SOURCE_SCALE", source)
        self.assertIn("v256._MIN_NATIVE_FACE_SHORT", source)
        self.assertIn("_MAX_LANDMARK_RESIDUAL = 28.0", source)
        self.assertIn("_MAX_LANDMARK_RESIDUAL_FRACTION = 0.060", source)
        self.assertIn("_MAX_LANDMARK_RESIDUAL_CAP = 48.0", source)
        self.assertIn("_landmark_residual_limit(face_min)", source)
        self.assertIn("colour_match=lab_roi", source)
        self.assertNotIn("v253._colour_match_lab(corrected, target, anatomy_mask)", source)
        self.assertIn("final[:, firewall_x:] = target[:, firewall_x:]", source)
        self.assertIn("delivery._deliver = v253._deliver_original", source)
        self.assertIn("fallback_v258", source)
        self.assertIn("AI_SELFIE_SEND_AS_DOCUMENT = True", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)
        self.assertNotIn("PreCheckoutQueryHandler", source)

    def test_package_version_is_v264_and_keeps_historical_successor_markers(self) -> None:
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("v262-landmark-field-compositor-2026-08-27", source)
        self.assertIn("v263-dense-identity-lock-2026-08-27", source)
        self.assertIn('VERSION = "v264-dense68-roi-production-2026-08-31"', source)
        self.assertIn('PRODUCTION_SELFIE_RUNTIME = "v264"', source)
        self.assertIn("v261-edge-harmonization-2026-08-26", source)
        self.assertIn("v260-eye-roi-memory-safe-2026-08-26", source)
        self.assertNotIn('VERSION = "v261-edge-harmonization-2026-08-26"', source)


if __name__ == "__main__":
    unittest.main()
