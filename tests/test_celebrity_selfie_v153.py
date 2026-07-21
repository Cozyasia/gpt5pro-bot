# -*- coding: utf-8 -*-
import os
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

import celebrity_selfie_v139 as v139
import celebrity_selfie_v153 as v153


def _jpeg(size=(800, 1000), color=(110, 125, 140)) -> bytes:
    image = Image.new("RGB", size, color)
    out = BytesIO()
    image.save(out, "JPEG", quality=92)
    return out.getvalue()


def _person_cutout(size=(500, 900)) -> Image.Image:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((165, 25, 335, 225), fill=(180, 140, 115, 255))
    draw.rounded_rectangle((95, 185, 405, 895), radius=100, fill=(90, 100, 120, 255))
    return image


class CelebritySelfieV153Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(v153.VERSION, "v153-reference-detector-miss-recovery-2026-07-21")

    def test_detector_result_remains_primary(self):
        expected = {"face": {"x": 1, "y": 2, "w": 3, "h": 4}, "face_area_ratio": 0.02}
        with patch.object(v153, "_ORIGINAL_SOURCE_FACE_INFO", return_value=expected):
            result = v153._source_face_info(_jpeg(), "celebrity")
        self.assertEqual(result["face"], expected["face"])
        self.assertEqual(result["face_detection"], "local-detector")

    def test_zero_box_celebrity_reference_gets_provisional_region(self):
        error = v139.PipelineError(
            "source_identity",
            "celebrity source must contain exactly one dominant foreground face; found 0",
        )
        with patch.object(v153, "_ORIGINAL_SOURCE_FACE_INFO", side_effect=error):
            with patch.dict(os.environ, {"CELEBRITY_V153_REFERENCE_FACE_FALLBACK": "1"}, clear=False):
                result = v153._source_face_info(_jpeg(), "celebrity")
        self.assertEqual(result["face_detection"], "provisional-zero-box-recovery")
        self.assertTrue(result["face"]["fallback"])

    def test_fallback_never_relaxes_user_source(self):
        error = v139.PipelineError(
            "source_identity",
            "user source must contain exactly one dominant foreground face; found 0",
        )
        with patch.object(v153, "_ORIGINAL_SOURCE_FACE_INFO", side_effect=error):
            with self.assertRaises(v139.PipelineError):
                v153._source_face_info(_jpeg(), "user")

    def test_alpha_silhouette_infers_retained_head(self):
        face, details = v153._infer_face_from_alpha(_person_cutout())
        self.assertTrue(face["fallback"])
        self.assertGreater(details["alpha"], 0.58)
        self.assertLess(face["y"], 260)

    def test_install_patches_live_v149_and_v143_symbols(self):
        source = Path("celebrity_selfie_v153.py").read_text(encoding="utf-8")
        self.assertIn("v149._source_face_info = _source_face_info", source)
        self.assertIn("v143._prepare_user_cutout = _prepare_user_cutout", source)
        self.assertIn("user_reference_fallback", source)

    def test_sitecustomize_loads_v153_after_v152(self):
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v153 import install_early", source)
        self.assertGreater(source.index("from celebrity_selfie_v153"), source.index("from celebrity_selfie_v152"))

    def test_version_contract_points_to_v153(self):
        source = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v153-reference-detector-miss-recovery-2026-07-21"', source)
        self.assertIn("from celebrity_selfie_v153 import install as install_v153", source)
        self.assertIn("release_overlay={'v153' if release_overlay else 'load-error'}", source)


if __name__ == "__main__":
    unittest.main()
