import unittest
from types import SimpleNamespace
from video_studio import seedance_scene_prompt

class ScenePromptTests(unittest.TestCase):
    def test_caption_timelines_removed_from_every_scene_field(self):
        scene = SimpleNamespace(
            action="Bottle rotates. ТИТРЫ: 0-3 | КРАСОТА В КАЖДОЙ КАПЛЕ",
            visual="Glass bottle on marble\\nТИТРЫ: 3-8 | ПОПРОБУЙТЕ СЕГОДНЯ",
            camera="Slow dolly", dialogue="", sound="", start_state="", end_state=""
        )
        prompt = seedance_scene_prompt(scene, "Cosmetic product.\\nТИТРЫ: 0-3 | TEST")
        self.assertNotIn("ТИТРЫ:", prompt)
        self.assertNotIn("ПОПРОБУЙТЕ", prompt)
        self.assertIn("Glass bottle", prompt)
        self.assertIn("final editing", prompt)

if __name__ == "__main__":
    unittest.main()
