"""Offline checks for real-estate video prompt and menu contracts.

Run: python -m unittest tests.test_real_estate_video
"""
import unittest
from real_estate_video import PROMPTS, ENGINES, menu_button, keyboard


class RealEstateVideoTests(unittest.TestCase):
    def test_three_distinct_modes(self):
        self.assertEqual(set(PROMPTS), {"exterior", "interior", "full"})
        self.assertEqual(set(ENGINES), {"kling", "veo", "seedance"})
        self.assertEqual(len(set(PROMPTS.values())), 3)

    def test_architectural_consistency(self):
        for prompt in PROMPTS.values():
            self.assertIn("preserve", prompt.lower())
            self.assertIn("no ", prompt.lower())

    def test_menu_callback(self):
        self.assertEqual(menu_button().callback_data, "revideo:start")

    def test_keyboard_callbacks(self):
        k = keyboard([[("Экстерьер", "type:exterior")]])
        self.assertEqual(k.inline_keyboard[0][0].callback_data, "revideo:type:exterior")


if __name__ == "__main__":
    unittest.main()
