import unittest
from neyrobot_prod.veo_multiscene import plan_video
from neyrobot_prod.veo_scene_prompt import scene_prompt

class ScenePromptTests(unittest.TestCase):
    def test_russian_audio_and_graphics_are_separate(self):
        scene = plan_video(8, "Продаёшь криптовалюту через пи ту пи?")[0]
        prompt = scene_prompt(scene, "Presenter in fintech studio", presenter="Dark suit")
        self.assertIn("ru-RU", prompt)
        self.assertIn("No English translation", prompt)
        self.assertIn("Do not generate background text", prompt)
        self.assertIn(scene.spoken_text, prompt)
        self.assertIn("Dark suit", prompt)

    def test_missing_visual_brief(self):
        with self.assertRaises(ValueError):
            scene_prompt(plan_video(8, "Тест")[0], " ")

if __name__ == "__main__":
    unittest.main()
