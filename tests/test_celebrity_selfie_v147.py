# -*- coding: utf-8 -*-
import os
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import celebrity_selfie_v147 as v147


class CelebritySelfieV147Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(v147.VERSION, "v147-source-pixel-dual-composite-2026-07-21")

    def test_scene_provider_order_excludes_identity_edit_providers(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CELEBRITY_V147_SCENE_PROVIDERS", None)
            self.assertEqual(v147._scene_provider_order(), ["gemini", "flux", "local"])
            self.assertNotIn("piapi", v147._scene_provider_order())
            self.assertNotIn("openai", v147._scene_provider_order())

    def test_background_prompt_requires_zero_people(self):
        prompt = v147._background_prompt("Ресторан", "4:5", 0)
        self.assertIn("ZERO people", prompt)
        self.assertIn("ZERO human faces", prompt)
        self.assertIn("LEFT", prompt)
        self.assertIn("RIGHT", prompt)
        self.assertNotIn("selected PUBLIC PERSON", prompt)

    def test_local_background_is_valid_portrait_jpeg(self):
        raw = v147._local_background("Премьера", "4:5")
        self.assertTrue(raw.startswith(b"\xff\xd8"))
        with Image.open(BytesIO(raw)) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (1024, 1280))
            self.assertGreater(min(image.size), 640)

    def test_background_problem_accepts_generated_fallback(self):
        raw = v147._local_background("Яхта", "4:5")
        self.assertEqual(v147._background_problem(raw), "")
        self.assertEqual(
            v147._background_aware_plate_problem(raw, "v147_background_local_fallback"),
            "",
        )

    def test_source_declares_provider_independent_identity_contract(self):
        source = Path("celebrity_selfie_v147.py").read_text(encoding="utf-8")
        self.assertIn("no-piapi+no-openai-image-edit+source-pixels-only", source)
        self.assertIn("source_pixels_preserved_no_generation_no_face_swap", source)
        self.assertIn("celebrity_pixel_preserved", source)
        self.assertIn("face_swap_used", source)
        self.assertIn("v142._make_plate_candidates = _make_background_candidates", source)
        self.assertIn("v143._build_composite_candidates = _source_pixel_build_composite_candidates", source)

    def test_sitecustomize_loads_v147_last(self):
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v147 import install_early", source)
        self.assertGreater(source.index("from celebrity_selfie_v147"), source.index("from celebrity_selfie_v146"))

    def test_version_contract_points_to_v147(self):
        source = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v147-source-pixel-dual-composite-2026-07-21"', source)
        self.assertIn("from celebrity_selfie_v147 import install as install_v147", source)
        self.assertIn("release_overlay={'v147' if release_overlay else 'load-error'}", source)


if __name__ == "__main__":
    unittest.main()
