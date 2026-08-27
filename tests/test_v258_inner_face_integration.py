# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V258InnerFaceIntegrationTests(unittest.TestCase):
    def test_v258_is_loaded_before_v259_v260_v261(self) -> None:
        source = Path("neyrobot_prod/selfie_v247_provider_supersample.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v258_inner_face_integration", source)
        self.assertLess(source.index("install_v257_native_sampling()"), source.index("install_v258_inner_face()"))
        self.assertIn("selfie_v259_eye_landmark_protection", source)
        self.assertIn("selfie_v260_eye_roi_memory_safe", source)
        self.assertIn("selfie_v261_edge_harmonization", source)
        self.assertLess(source.index("install_v258_inner_face()"), source.index("install_v259_eye_protection()"))
        self.assertLess(source.index("install_v259_eye_protection()"), source.index("install_v260_eye_roi()"))
        self.assertLess(source.index("install_v260_eye_roi()"), source.index("install_v261_edge_harmonization()"))

    def test_v258_uses_two_zone_target_heavy_outer_ring(self) -> None:
        source = Path("neyrobot_prod/selfie_v258_inner_face_integration.py").read_text(encoding="utf-8")
        self.assertIn("core = _elliptic_erode(hard_mask, core_erode_px)", source)
        self.assertIn("integration_support = cv2.GaussianBlur(core", source)
        self.assertIn("poisson.astype(np.float32) * integration_alpha", source)
        self.assertIn("target.astype(np.float32) * (1.0 - integration_alpha)", source)
        self.assertIn("detail_core = _elliptic_erode(core, detail_erode_px)", source)
        self.assertIn("outer_ring_target_heavy=true", source)
        self.assertIn("detail_core_only=true", source)

    def test_v258_adapts_reinject_and_core_for_broad_masks(self) -> None:
        source = Path("neyrobot_prod/selfie_v258_inner_face_integration.py").read_text(encoding="utf-8")
        self.assertIn("_REINJECT_DEFAULT = 0.89", source)
        self.assertIn("_REINJECT_MID = 0.88", source)
        self.assertIn("_REINJECT_HIGH = 0.87", source)
        self.assertIn("_COVERAGE_HIGH = 0.90", source)
        self.assertIn("return 0.075", source)
        self.assertIn("return 0.065", source)
        self.assertIn("return 0.055", source)
        self.assertNotIn("detail_reinject=0.94", source)

    def test_v258_preserves_v255_gate_v257_sampling_firewall_and_lossless_delivery(self) -> None:
        source = Path("neyrobot_prod/selfie_v258_inner_face_integration.py").read_text(encoding="utf-8")
        self.assertIn("v255._warp_source_face_gate", source)
        self.assertIn("v254._target_face_mask", source)
        self.assertIn("v256._MAX_REAL_SOURCE_SCALE", source)
        self.assertIn("v256._MIN_NATIVE_FACE_SHORT", source)
        self.assertIn("projected_gate=false", source)
        self.assertIn("final[:, firewall_x:] = target[:, firewall_x:]", source)
        self.assertIn("delivery._deliver = v253._deliver_original", source)
        self.assertIn("fallback_v257", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)
        self.assertNotIn("PreCheckoutQueryHandler", source)

    def test_v258_is_retained_as_v262_compatibility_base(self) -> None:
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v262-landmark-field-compositor-2026-08-27"', source)
        self.assertIn("v261-edge-harmonization-2026-08-26", source)
        self.assertIn("v260-eye-roi-memory-safe-2026-08-26", source)
        self.assertIn("v259-eye-landmark-protection-2026-08-26", source)
        self.assertIn("v258-inner-face-integration-2026-08-24", source)
        self.assertIn("v257-native-sampling-guard-2026-08-22", source)
        self.assertIn("v255-source-face-gate-lossless-2026-08-22", source)
        self.assertNotIn('VERSION = "v261-edge-harmonization-2026-08-26"', source)


if __name__ == "__main__":
    unittest.main()
