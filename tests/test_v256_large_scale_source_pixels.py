# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V256LargeScaleSourcePixelTests(unittest.TestCase):
    def test_v256_is_loaded_after_v255(self) -> None:
        source = Path("neyrobot_prod/selfie_v247_provider_supersample.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v256_large_scale_source_pixels", source)
        self.assertLess(source.index("install_v255_source_gate()"), source.index("install_v256_large_scale()"))

    def test_v256_keeps_real_source_path_for_observed_1654_scale(self) -> None:
        source = Path("neyrobot_prod/selfie_v256_large_scale_source_pixels.py").read_text(encoding="utf-8")
        self.assertIn("_MAX_REAL_SOURCE_SCALE = 1.90", source)
        self.assertIn("_MIN_NATIVE_FACE_SHORT = 320.0", source)
        self.assertIn("_MIN_PROJECTED_FACE_SHORT = 520.0", source)
        self.assertIn("scale 1.654", source)
        self.assertIn("cv2.INTER_LANCZOS4", source)
        self.assertIn("one_pass_lanczos=true", source)
        self.assertIn("provider_bypassed=true", source)

    def test_v256_reuses_v255_hard_face_gate_and_v253_delivery(self) -> None:
        source = Path("neyrobot_prod/selfie_v256_large_scale_source_pixels.py").read_text(encoding="utf-8")
        self.assertIn("v255._warp_source_face_gate", source)
        self.assertIn("v254._target_face_mask", source)
        self.assertIn("hard_mask = cv2.bitwise_and(target_mask, source_gate)", source)
        self.assertIn("delivery._deliver = v253._deliver_original", source)
        self.assertIn("fallback_v255", source)
        self.assertNotIn("/v1/faceswap", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)

    def test_v256_increases_real_source_interior_without_synthetic_sharpening(self) -> None:
        source = Path("neyrobot_prod/selfie_v256_large_scale_source_pixels.py").read_text(encoding="utf-8")
        self.assertIn("detail_alpha = (inner.astype(np.float32) / 255.0 * 0.94)", source)
        self.assertIn("inner = cv2.min(inner, hard_mask)", source)
        self.assertIn("source_pixels=true", source)
        self.assertIn("synthetic_face=false", source)
        self.assertIn("final[:, firewall_x:] = target[:, firewall_x:]", source)
        self.assertNotIn("detailEnhance", source)
        self.assertNotIn("unsharp", source.lower())

    def test_package_version_is_v256(self) -> None:
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("v256-large-scale-source-pixels-2026-08-22", source)


if __name__ == "__main__":
    unittest.main()
