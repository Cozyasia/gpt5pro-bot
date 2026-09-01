# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V254LandmarkFitSeamlessSourceTests(unittest.TestCase):
    def test_v254_is_loaded_after_v253(self) -> None:
        source = Path("neyrobot_prod/selfie_v247_provider_supersample.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v254_landmark_fit_seamless_source", source)
        self.assertLess(source.index("install_v253_source_pixels()"), source.index("install_v254_source_fit()"))

    def test_v254_uses_geometry_fit_target_mask_and_poisson_boundary(self) -> None:
        source = Path("neyrobot_prod/selfie_v254_landmark_fit_seamless_source.py").read_text(encoding="utf-8")
        self.assertIn("V254 COMPOSITING FIT LOCK", source)
        self.assertIn("cv2.estimateAffinePartial2D", source)
        self.assertIn("cv2.estimateAffine2D", source)
        self.assertIn("candidate_aniso <= 1.14", source)
        self.assertIn("mask=target_face_no_neck", source)
        self.assertIn("cv2.seamlessClone", source)
        self.assertIn("detail_reinject=0.88", source)

    def test_v254_keeps_source_pixels_lossless_delivery_and_hero_firewall(self) -> None:
        source = Path("neyrobot_prod/selfie_v254_landmark_fit_seamless_source.py").read_text(encoding="utf-8")
        self.assertIn("source_pixels=true", source)
        self.assertIn("synthetic_face=false", source)
        self.assertIn("final[:, firewall_x:] = target[:, firewall_x:]", source)
        self.assertIn("delivery._deliver = v253._deliver_original", source)
        self.assertIn('cv2.imencode(".png"', source)

    def test_v254_falls_back_to_proven_v253_not_provider_loop(self) -> None:
        source = Path("neyrobot_prod/selfie_v254_landmark_fit_seamless_source.py").read_text(encoding="utf-8")
        self.assertIn("fallback_v253", source)
        self.assertNotIn("/v1/faceswap", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)

    def test_v254_is_historical_and_v265_owns_current_dense_geometry(self) -> None:
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        engine = Path("neyrobot_prod/dense68_engine_v265.py").read_text(encoding="utf-8")
        self.assertIn('PRODUCTION_SELFIE_RUNTIME = "v265"', package)
        self.assertIn("_similarity_transform(source_pts5, target_pts5)", engine)
        self.assertIn("_landmark_anatomy_mask", engine)
        self.assertIn("cv2.seamlessClone", engine)
        self.assertNotIn("selfie_v254_landmark_fit_seamless_source", package)


if __name__ == "__main__":
    unittest.main()
