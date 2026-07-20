# -*- coding: utf-8 -*-
from io import BytesIO
from pathlib import Path
import unittest

from PIL import Image, ImageDraw

import celebrity_selfie_v133 as v133


def portrait_bytes(size=(800, 1000)):
    image = Image.new("RGB", size, (90, 115, 135))
    draw = ImageDraw.Draw(image)
    draw.ellipse((175, 150, 365, 365), fill=(215, 175, 145))
    draw.ellipse((445, 160, 635, 375), fill=(205, 160, 130))
    out = BytesIO()
    image.save(out, "JPEG", quality=94)
    return out.getvalue()


class CelebritySelfieV133Tests(unittest.TestCase):
    def test_historical_version_remains_documented(self):
        source = Path("celebrity_selfie_v133.py").read_text(encoding="utf-8")
        self.assertIn(
            'VERSION = "v133-celebrity-selfie-best-of-n-fallback-2026-07-19"',
            source,
        )

    def test_scene_profiles_are_specific(self):
        red_square = v133._scene_profile("Красная площадь")
        restaurant = v133._scene_profile("современный ресторан")
        yacht = v133._scene_profile("селфи на яхте")
        self.assertIn("Saint Basil", red_square)
        self.assertIn("restaurant", restaurant)
        self.assertIn("yacht", yacht)

    def test_scene_prompt_has_one_frame_and_two_people_contract(self):
        prompt = v133._scene_prompt("Роман Абрамович", "Красная площадь", 1)
        self.assertIn("ONE continuous camera frame", prompt)
        self.assertIn("Exactly TWO main adults", prompt)
        self.assertIn("Never create a collage", prompt)
        self.assertIn("No third foreground person", prompt)
        self.assertIn("Saint Basil", prompt)

    def test_local_candidate_score_accepts_portrait_shape(self):
        score = v133._candidate_local_score(portrait_bytes())
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 100)

    def test_failure_keyboard_contains_same_scene_retry(self):
        markup = v133._failure_kb()
        callbacks = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
        ]
        self.assertIn("celeb:retry_scene", callbacks)
        self.assertIn("celeb:preset:red_square", callbacks)
        self.assertIn("celeb:menu", callbacks)

    def test_source_contract_has_best_of_n_and_second_provider(self):
        source = Path("celebrity_selfie_v133.py").read_text(encoding="utf-8")
        self.assertIn('"CELEBRITY_SCENE_CANDIDATES", 3', source)
        self.assertIn('"CELEBRITY_IDENTITY_CANDIDATES", 2', source)
        self.assertIn('base_url + "/images/edits"', source)
        self.assertIn("await asyncio.gather", source)
        self.assertIn("finals.sort", source)

    def test_handled_failure_suppresses_legacy_generic_card(self):
        source = Path("celebrity_selfie_v133.py").read_text(encoding="utf-8")
        self.assertIn("Качественный результат не получен", source)
        self.assertIn("Повторить эту же сцену", source)
        self.assertNotIn("Задача не выполнена. Попробуйте позже.", source)
        self.assertIn("return True", source)

    def test_runtime_bootstrap_moves_forward_to_v135(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v135 import install_builder_hook", source)
        self.assertNotIn("from celebrity_selfie_v133 import install_builder_hook", source)
        self.assertNotIn("from celebrity_selfie_v134 import install_builder_hook", source)
        for version in ("v122", "v126", "v130_runtime", "v131", "v132"):
            self.assertNotIn(f"from celebrity_selfie_{version} import install_builder_hook", source)


if __name__ == "__main__":
    unittest.main()
