# -*- coding: utf-8 -*-
import json
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

import celebrity_selfie_v134 as v134


def portrait_bytes(size=(800, 1000), background=(90, 115, 135)):
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    draw.ellipse((175, 150, 365, 365), fill=(215, 175, 145))
    draw.ellipse((445, 160, 635, 375), fill=(205, 160, 130))
    out = BytesIO()
    image.save(out, "JPEG", quality=94)
    return out.getvalue()


class CelebritySelfieV134Tests(unittest.IsolatedAsyncioTestCase):
    def test_version(self):
        self.assertIn("celebrity-selfie", v134.VERSION)

    def test_scene_profiles_prioritise_faces(self):
        red_square = v134._scene_profile("Красная площадь")
        restaurant = v134._scene_profile("современный ресторан")
        generic = v134._scene_profile("офис")
        self.assertIn("One recognisable landmark is sufficient", red_square)
        self.assertIn("faces are more important", red_square)
        self.assertIn("background may be understated", restaurant)
        self.assertIn("prioritise the two faces", generic)

    def test_prompt_is_face_first_and_rescue_is_wider(self):
        prompt = v134._scene_prompt("Роман Абрамович", "Красная площадь", 1)
        rescue = v134._scene_prompt("Роман Абрамович", "Красная площадь", 97)
        self.assertIn("FACE-FIRST PRIORITY", prompt)
        self.assertIn("Identity-ready faces matter more", prompt)
        self.assertIn("RESCUE PASS", rescue)
        self.assertIn("Exactly TWO main adults", rescue)

    def test_background_preservation_is_rank_only_metric(self):
        original = portrait_bytes()
        identical = v134._background_preservation_score(original, original)
        changed = v134._background_preservation_score(original, portrait_bytes(background=(230, 230, 230)))
        self.assertGreater(identical, 98)
        self.assertGreater(identical, changed)

    async def test_low_scene_score_does_not_hard_reject_two_person_frame(self):
        async def vision(*_args, **_kwargs):
            return json.dumps({
                "single_scene": True,
                "split_screen": False,
                "foreground_people": 2,
                "composition_score": 84,
                "face_swap_readiness": 86,
                "scene_score": 8,
                "landmark_visible": False,
                "reason": "background is generic",
            })

        result = await v134._scene_assessment(
            SimpleNamespace(ask_openai_vision=vision),
            portrait_bytes(),
            "Красная площадь",
            phase="test",
        )
        self.assertTrue(result["hard_ok"])
        self.assertEqual(result["scene_score"], 8.0)
        self.assertGreater(result["total_score"], 0)

    async def test_split_screen_remains_hard_rejection(self):
        async def vision(*_args, **_kwargs):
            return json.dumps({
                "single_scene": False,
                "split_screen": True,
                "foreground_people": 2,
                "scene_score": 90,
                "reason": "two panels",
            })

        result = await v134._scene_assessment(
            SimpleNamespace(ask_openai_vision=vision),
            portrait_bytes(),
            "офис",
            phase="test",
        )
        self.assertFalse(result["hard_ok"])

    def test_source_contract_weights_identity_above_scene(self):
        source = Path("celebrity_selfie_v134.py").read_text(encoding="utf-8")
        self.assertIn("identity_score * 0.78", source)
        self.assertIn("scene_score * 0.05", source)
        self.assertIn("background_preservation=rank_only", source)
        self.assertIn('"CELEBRITY_SCENE_RESCUE", True', source)
        self.assertNotIn('if data.get("scene_match") is False', source)

    def test_v134_remains_available_only_as_v135_fallback(self):
        bootstrap = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        v135 = Path("celebrity_selfie_v135.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v135 import install_builder_hook", bootstrap)
        self.assertNotIn("from celebrity_selfie_v134 import install_builder_hook", bootstrap)
        self.assertIn("_LEGACY_RUN = previous._run_face_first_generation", v135)


if __name__ == "__main__":
    unittest.main()
