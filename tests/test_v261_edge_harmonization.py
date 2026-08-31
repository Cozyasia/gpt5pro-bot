# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V261EdgeHarmonizationTests(unittest.TestCase):
    def test_v261_loads_after_v260_and_before_v262_final_owner(self) -> None:
        source = Path("neyrobot_prod/selfie_v247_provider_supersample.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v261_edge_harmonization", source)
        self.assertIn("selfie_v262_landmark_field_compositor", source)
        self.assertLess(source.index("install_v260_eye_roi()"), source.index("install_v261_edge_harmonization()"))
        self.assertLess(source.index("install_v261_edge_harmonization()"), source.index("install_v262_landmark_field()"))

    def test_v261_uses_distance_to_real_mask_boundary_not_new_ellipse(self) -> None:
        source = Path("neyrobot_prod/selfie_v261_edge_harmonization.py").read_text(encoding="utf-8")
        self.assertIn("cv2.distanceTransform", source)
        self.assertIn("alpha = _smoothstep01(distance / max(1.0, feather_px))", source)
        self.assertIn("target_mask = v254._target_face_mask", source)
        self.assertIn("source_gate = v255._warp_source_face_gate", source)
        self.assertIn("hard_mask = cv2.bitwise_and(target_mask, source_gate)", source)
        self.assertNotIn("cv2.ellipse", source)

    def test_v261_harmonizes_only_low_frequency_edge_tone(self) -> None:
        source = Path("neyrobot_prod/selfie_v261_edge_harmonization.py").read_text(encoding="utf-8")
        self.assertIn("_EDGE_FEATHER_FRACTION = 0.075", source)
        self.assertIn("_TONE_STRENGTH = 0.62", source)
        self.assertIn("target_low = cv2.GaussianBlur", source)
        self.assertIn("final_low = cv2.GaussianBlur", source)
        self.assertIn("delta = target_low.astype(np.float32) - final_low.astype(np.float32)", source)
        self.assertIn("edge_weight = ((1.0 - alpha) ** 0.72)", source)
        self.assertIn("central_source_pixels_untouched=true", source)
        self.assertIn("edge_target_blend=true", source)

    def test_v261_preserves_v260_eyes_firewall_and_lossless_delivery(self) -> None:
        source = Path("neyrobot_prod/selfie_v261_edge_harmonization.py").read_text(encoding="utf-8")
        self.assertIn("v260._source_pixel_transfer_v260", source)
        self.assertIn("fallback_v260", source)
        self.assertIn("final[:, firewall_x:] = target[:, firewall_x:]", source)
        self.assertIn("delivery._deliver = v253._deliver_original", source)
        self.assertIn("AI_SELFIE_SEND_AS_DOCUMENT = True", source)
        self.assertIn("full_frame_float_blend=false", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)
        self.assertNotIn("PreCheckoutQueryHandler", source)

    def test_package_version_advances_to_v264_successor(self) -> None:
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("v261-edge-harmonization-2026-08-26", source)
        self.assertIn("v260-eye-roi-memory-safe-2026-08-26", source)
        self.assertIn("v262-landmark-field-compositor-2026-08-27", source)
        self.assertIn("v263-dense-identity-lock-2026-08-27", source)
        self.assertIn('VERSION = "v264-dense68-roi-production-2026-08-31"', source)
        self.assertIn('PRODUCTION_SELFIE_RUNTIME = "v264"', source)


if __name__ == "__main__":
    unittest.main()
