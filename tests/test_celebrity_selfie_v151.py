# -*- coding: utf-8 -*-
import os
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import celebrity_selfie_v151 as v151


def _jpeg(size=(800, 1000), color=(75, 95, 120)) -> bytes:
    image = Image.new("RGB", size, color)
    out = BytesIO()
    image.save(out, "JPEG", quality=92)
    return out.getvalue()


class CelebritySelfieV151Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(v151.VERSION, "v151-comet-only-composition-ready-2026-07-21")

    def test_provider_order_is_comet_only_even_if_legacy_env_requests_fallbacks(self):
        with patch.dict(os.environ, {"CELEBRITY_V150_SCENE_PROVIDERS": "gemini,flux,local"}, clear=False):
            self.assertEqual(v151._scene_provider_order(), ["comet"])

    def test_prompt_reserves_two_zones_without_requesting_main_people(self):
        prompt = v151._scene_prompt("Яхта", "4:5", 0)
        self.assertIn("LEFT", prompt)
        self.assertIn("RIGHT", prompt)
        self.assertIn("Do not create either of the two main subjects", prompt)
        self.assertIn("Small distant background guests are allowed", prompt)
        self.assertNotIn("Gemini", prompt)

    def test_composition_gate_accepts_valid_plate_without_faces(self):
        with patch.object(v151.v143, "_main_faces", return_value=[]):
            problem, details = v151._composition_ready_problem(_jpeg())
        self.assertEqual(problem, "")
        self.assertIn("metrics", details)

    def test_composition_gate_rejects_prominent_foreground_face(self):
        face = {"x": 240, "y": 250, "w": 280, "h": 320}
        with patch.object(v151.v143, "_main_faces", return_value=[face]):
            problem, details = v151._composition_ready_problem(_jpeg())
        self.assertIn("prominent foreground face", problem)
        self.assertTrue(details["prominent_faces"])

    def test_install_forces_comet_and_overrides_live_plate_builders(self):
        source = Path("celebrity_selfie_v151.py").read_text(encoding="utf-8")
        self.assertIn('os.environ["CELEBRITY_V150_SCENE_PROVIDERS"] = "comet"', source)
        self.assertIn("v142._make_plate_candidates = _make_background_candidates", source)
        self.assertIn("v150._make_background_candidates = _make_background_candidates", source)
        self.assertIn('"gemini_scene": "disabled"', source)
        self.assertIn('"flux_scene": "disabled"', source)

    def test_sitecustomize_loads_v151_last(self):
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v151 import install_early", source)
        self.assertGreater(source.index("from celebrity_selfie_v151"), source.index("from celebrity_selfie_v150"))

    def test_version_contract_points_to_v151(self):
        source = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v151-comet-only-composition-ready-2026-07-21"', source)
        self.assertIn("from celebrity_selfie_v151 import install as install_v151", source)
        self.assertIn("release_overlay={'v151' if release_overlay else 'load-error'}", source)


if __name__ == "__main__":
    unittest.main()
