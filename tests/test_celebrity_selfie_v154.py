# -*- coding: utf-8 -*-
import os
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

import celebrity_selfie_v139 as v139
import celebrity_selfie_v154 as v154


def _jpeg(size=(800, 1000), color=(115, 130, 145)) -> bytes:
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 100, 720, 900), fill=(85, 120, 155))
    out = BytesIO()
    image.save(out, "JPEG", quality=92)
    return out.getvalue()


def _person_cutout(size=(500, 900)) -> Image.Image:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((165, 25, 335, 225), fill=(180, 140, 115, 255))
    draw.rounded_rectangle((95, 185, 405, 895), radius=100, fill=(90, 100, 120, 255))
    return image


class CelebritySelfieV154Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(v154.VERSION, "v154-cpu-rembg-user-face-recovery-2026-07-22")

    def test_cpu_backend_is_isolated_from_web_requirements(self):
        web = Path("requirements.txt").read_text(encoding="utf-8")
        worker = Path("requirements-media-worker.txt").read_text(encoding="utf-8")
        self.assertNotIn("rembg[cpu]", web)
        self.assertIn("rembg[cpu]==2.0.67", worker)

    def test_zero_box_user_source_gets_provisional_region(self):
        error = v139.PipelineError(
            "source_identity",
            "user source must contain exactly one dominant foreground face; found 0",
        )
        with patch.object(v154, "_ORIGINAL_SOURCE_FACE_INFO", side_effect=error):
            with patch.dict(os.environ, {"CELEBRITY_V154_USER_FACE_FALLBACK": "1"}, clear=False):
                result = v154._source_face_info(_jpeg(), "user")
        self.assertEqual(result["face_detection"], "v154-provisional-zero-box-recovery")
        self.assertTrue(result["face"]["fallback"])

    def test_non_zero_face_error_remains_fail_closed(self):
        error = v139.PipelineError("source_identity", "user source contains three dominant faces")
        with patch.object(v154, "_ORIGINAL_SOURCE_FACE_INFO", side_effect=error):
            with self.assertRaises(v139.PipelineError):
                v154._source_face_info(_jpeg(), "user")

    def test_person_silhouette_passes_geometry_gate(self):
        self.assertEqual(v154._human_silhouette_problem(_person_cutout()), "")

    def test_empty_alpha_fails_geometry_gate(self):
        image = Image.new("RGBA", (500, 900), (0, 0, 0, 0))
        self.assertIn("empty", v154._human_silhouette_problem(image))

    def test_corner_repair_clears_two_corners(self):
        image = Image.new("RGBA", (400, 600), (100, 100, 100, 255))
        alpha = image.getchannel("A")
        alpha.paste(0, (0, 0, 36, 54))
        image.putalpha(alpha)
        repaired = v154._clear_least_occupied_corners(image, minimum_clear=2)
        metrics = v154.v143._alpha_metrics(repaired)
        self.assertGreaterEqual(metrics["transparent_corners"], 2)

    def test_install_patches_live_cutout_stack(self):
        source = Path("celebrity_selfie_v154.py").read_text(encoding="utf-8")
        self.assertIn("v142._local_rembg_cutout = _local_rembg_cutout", source)
        self.assertIn("v142._photoroom_cutout = _photoroom_cutout", source)
        self.assertIn("v149._source_face_info = _source_face_info", source)
        self.assertIn("v143._prepare_user_cutout = _prepare_user_cutout", source)

    def test_sitecustomize_applies_memory_policy_after_v154(self):
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v154 import install_early", source)
        self.assertIn("from memory_safety_v155 import install_early", source)
        self.assertGreater(source.index("from memory_safety_v155"), source.index("from celebrity_selfie_v154"))

    def test_version_contract_points_to_v154(self):
        source = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v154-cpu-rembg-user-face-recovery-2026-07-22"', source)
        self.assertIn("from celebrity_selfie_v154 import install as install_v154", source)
        self.assertIn("release_overlay={'v154' if release_overlay else 'load-error'}", source)


if __name__ == "__main__":
    unittest.main()
