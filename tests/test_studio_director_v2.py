import unittest
from neyrobot_prod.studio_director_v2 import prepare_storyboard, director_llm_instructions, validate_director_plan


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

    def test_fractional_caption_is_removed_from_visual_prompt(self):
        board = prepare_storyboard(
            "Камера облетает лампу." + chr(10) + "ТИТРЫ: 0,5-3.5 | ТЕКСТ",
            duration=8,
        )
        self.assertEqual(len(board.captions), 1)
        self.assertEqual(board.captions[0].start, 0.5)
        self.assertEqual(board.captions[0].end, 3.5)
        self.assertNotIn("ТИТРЫ:", board.visual_prompt)

    def test_rejects_caption_outside_duration(self):
        with self.assertRaises(ValueError):
            prepare_storyboard("Лампа.\nТИТРЫ: 3-9 | ТЕСТ", duration=8)

    def test_rejects_invalid_interval(self):
        with self.assertRaises(ValueError):
            prepare_storyboard("Лампа.\nТИТРЫ: 4-4 | ТЕСТ", duration=8)

    def test_llm_instructions_exclude_caption_content(self):
        board = prepare_storyboard("Лампа в интерьере.\nТИТРЫ: 0-3 | СВЕТ", duration=8)
        instructions = director_llm_instructions(board)
        self.assertIn("camera movement", instructions)
        self.assertNotIn("СВЕТ", instructions)

    def test_director_plan_timeline(self):
        board = prepare_storyboard("Лампа в интерьере.", duration=8)
        scene = dict(action="Lamp illuminates", camera_movement="Orbit", framing="Medium shot",
                     lighting="Warm", visual="Lamp on desk", transition="Cut")
        first = dict(scene, start_second=0, end_second=3)
        second = dict(scene, start_second=3, end_second=8)
        self.assertEqual(len(validate_director_plan({"scenes": [first, second]}, board)), 2)
        with self.assertRaises(ValueError):
            validate_director_plan({"scenes": [first, dict(second, start_second=4)]}, board)
        with self.assertRaises(ValueError):
            validate_director_plan({"scenes": [dict(first, visual="ТИТРЫ: СВЕТ"), second]}, board)

    def test_no_paid_provider_calls(self):
        result = prepare_storyboard("Камера приближается к лампе.", duration=8)
        self.assertEqual(result.captions, ())
        self.assertEqual(result.aspect_ratio, "9:16")


if __name__ == "__main__":
    unittest.main()
