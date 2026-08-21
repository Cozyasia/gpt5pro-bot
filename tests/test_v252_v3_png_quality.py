# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V252V3PngQualityTests(unittest.TestCase):
    def test_v252_is_loaded_after_v251(self) -> None:
        source = Path("neyrobot_prod/selfie_v247_provider_supersample.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v251_v2_identity_detail", source)
        self.assertIn("selfie_v252_v3_png_quality", source)
        self.assertLess(source.index("install_v251_identity()"), source.index("install_v252_quality()"))

    def test_v3_uses_lossless_quality_controls(self) -> None:
        source = Path("neyrobot_prod/selfie_v252_v3_png_quality.py").read_text(encoding="utf-8")
        self.assertIn('/v1/faceswap-v3', source)
        self.assertIn('"image_format": "png"', source)
        self.assertIn('"image_quality": 100', source)
        self.assertIn('"interpolation": "Lanczos"', source)
        self.assertIn('"facedetection": "retinaface_resnet50"', source)
        self.assertIn('"face_restore_weight": 0.25', source)

    def test_v252_disables_source_frequency_repair(self) -> None:
        source = Path("neyrobot_prod/selfie_v252_v3_png_quality.py").read_text(encoding="utf-8")
        self.assertIn("source_detail=false", source)
        self.assertNotIn("_source_guided_detail(", source)
        self.assertNotIn("numpy", source)

    def test_v252_reuses_v251_owner_instead_of_registering_new_callback(self) -> None:
        source = Path("neyrobot_prod/selfie_v252_v3_png_quality.py").read_text(encoding="utf-8")
        self.assertIn("v251.enforce_runtime = enforce_runtime", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)

    def test_v252_release_marker_remains_in_v252_module(self) -> None:
        source = Path("neyrobot_prod/selfie_v252_v3_png_quality.py").read_text(encoding="utf-8")
        self.assertIn("v252-v3-png-quality-lock-2026-08-20", source)


if __name__ == "__main__":
    unittest.main()
