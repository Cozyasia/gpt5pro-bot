# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V253YuNetSourcePixelTests(unittest.TestCase):
    def test_v253_is_loaded_after_v252(self) -> None:
        source = Path("neyrobot_prod/selfie_v247_provider_supersample.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v253_yunet_source_pixels", source)
        self.assertLess(source.index("install_v252_quality()"), source.index("install_v253_source_pixels()"))

    def test_v253_uses_real_source_pixels_and_landmark_similarity(self) -> None:
        source = Path("neyrobot_prod/selfie_v253_yunet_source_pixels.py").read_text(encoding="utf-8")
        self.assertIn("cv2.FaceDetectorYN.create", source)
        self.assertIn("cv2.estimateAffinePartial2D", source)
        self.assertIn("cv2.INTER_LANCZOS4", source)
        self.assertIn("source_pixels=true", source)
        self.assertIn("synthetic_face=false", source)
        self.assertIn("photo #3 remains the sole identity/expression authority", source)

    def test_v253_verifies_official_yunet_model(self) -> None:
        source = Path("neyrobot_prod/selfie_v253_yunet_source_pixels.py").read_text(encoding="utf-8")
        self.assertIn("opencv/opencv_zoo", source)
        self.assertIn("8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4", source)
        self.assertIn("YuNet checksum mismatch", source)

    def test_v253_preserves_hero_firewall_and_png(self) -> None:
        source = Path("neyrobot_prod/selfie_v253_yunet_source_pixels.py").read_text(encoding="utf-8")
        self.assertIn("tw * 0.55", source)
        self.assertIn("warped_mask[:, firewall_x:] = 0", source)
        self.assertIn('cv2.imencode(".png"', source)

    def test_v253_retries_original_document_without_downscale(self) -> None:
        source = Path("neyrobot_prod/selfie_v253_yunet_source_pixels.py").read_text(encoding="utf-8")
        self.assertIn("mode=original_document", source)
        self.assertIn("downscale=false recompress=false", source)
        self.assertIn("for attempt, timeout in enumerate((300.0, 360.0, 420.0), 1)", source)
        self.assertIn("telegram_photo_compression=false", source)

    def test_v253_has_v252_fallback_and_no_new_callback(self) -> None:
        source = Path("neyrobot_prod/selfie_v253_yunet_source_pixels.py").read_text(encoding="utf-8")
        self.assertIn("fallback_v252", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)

    def test_v253_is_retained_only_as_v265_yunet_utility(self) -> None:
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        engine = Path("neyrobot_prod/dense68_engine_v265.py").read_text(encoding="utf-8")
        self.assertIn('PRODUCTION_SELFIE_RUNTIME = "v265"', package)
        self.assertIn("selfie_v253_yunet_source_pixels as v253", engine)
        self.assertNotIn("selfie_v253_yunet_source_pixels", package)


if __name__ == "__main__":
    unittest.main()
