# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V255SourceFaceGateTests(unittest.TestCase):
    def test_v255_is_loaded_after_v254(self) -> None:
        source = Path("neyrobot_prod/selfie_v247_provider_supersample.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v255_source_face_gate", source)
        self.assertLess(source.index("install_v254_source_fit()"), source.index("install_v255_source_gate()"))

    def test_source_face_mask_is_warped_with_pixel_transform_and_intersected(self) -> None:
        source = Path("neyrobot_prod/selfie_v255_source_face_gate.py").read_text(encoding="utf-8")
        self.assertIn("def _source_face_mask", source)
        self.assertIn("warped_source_mask = cv2.warpAffine", source)
        self.assertIn("source_mask,\n        matrix", source)
        self.assertIn("hard_mask = cv2.bitwise_and(target_mask, source_gate)", source)
        self.assertIn("source_gate_coverage", source)
        self.assertIn("coverage < 0.50", source)

    def test_blurred_fallback_and_detail_alpha_cannot_escape_hard_gate(self) -> None:
        source = Path("neyrobot_prod/selfie_v255_source_face_gate.py").read_text(encoding="utf-8")
        self.assertIn("soft = cv2.min(soft, hard_mask)", source)
        self.assertIn("inner = cv2.min(inner, hard_mask)", source)

    def test_v255_preserves_no_neck_detail_poisson_and_hero_firewall(self) -> None:
        source = Path("neyrobot_prod/selfie_v255_source_face_gate.py").read_text(encoding="utf-8")
        self.assertIn("bottom = min(h, int(round(y + fh * 0.885)))", source)
        self.assertIn("cv2.seamlessClone", source)
        self.assertIn("detail_alpha = (inner.astype(np.float32) / 255.0 * 0.88)", source)
        self.assertIn("final[:, firewall_x:] = target[:, firewall_x:]", source)
        self.assertIn("source_pixels=true", source)
        self.assertIn("synthetic_face=false", source)

    def test_v255_reuses_v253_lossless_delivery_and_v254_fallback(self) -> None:
        source = Path("neyrobot_prod/selfie_v255_source_face_gate.py").read_text(encoding="utf-8")
        self.assertIn("delivery._deliver = v253._deliver_original", source)
        self.assertIn("fallback_v254", source)
        self.assertNotIn("/v1/faceswap", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)

    def test_v255_no_neck_contract_is_superseded_by_v265_anatomical_mask(self) -> None:
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        engine = Path("neyrobot_prod/dense68_engine_v265.py").read_text(encoding="utf-8")
        self.assertIn('PRODUCTION_SELFIE_RUNTIME = "v265"', package)
        self.assertIn("No ellipse, neck, hair or full-head source mask", engine)
        self.assertIn("_landmark_anatomy_mask", engine)
        self.assertNotIn("selfie_v255_source_face_gate", package)


if __name__ == "__main__":
    unittest.main()
