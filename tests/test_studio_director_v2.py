import unittest
from neyrobot_prod.studio_director_v2 import prepare_storyboard


class StoryboardTests(unittest.TestCase):
    def test_separates_timed_captions(self):
        source = ("Рекламный ролик 8 секунд, вертикальный 9:16.\n"
                  "Лампа на столе, камера облетает продукт.\n"
                  "ТИТРЫ: 0-3 | СВЕТ, КОТОРЫЙ ВДОХНОВЛЯЕТ\n"
                  "ТИТРЫ: 3-8 | СОЗДАЙТЕ СВОЮ АТМОСФЕРУ")
        result = prepare_storyboard(source)
        self.assertEqual(result.duration, 8)
        self.assertEqual(len(result.captions), 2)
        self.assertNotIn("ТИТРЫ:", result.visual_prompt)
        self.assertIn("camera movement", result.direction_notes)

    def test_rejects_caption_outside_duration(self):
        with self.assertRaises(ValueError):
            prepare_storyboard("Лампа.\nТИТРЫ: 3-9 | ТЕСТ", duration=8)

    def test_rejects_invalid_interval(self):
        with self.assertRaises(ValueError):
            prepare_storyboard("Лампа.\nТИТРЫ: 4-4 | ТЕСТ", duration=8)

    def test_no_paid_provider_calls(self):
        result = prepare_storyboard("Камера приближается к лампе.", duration=8)
        self.assertEqual(result.captions, ())
        self.assertEqual(result.aspect_ratio, "9:16")


if __name__ == "__main__":
    unittest.main()
