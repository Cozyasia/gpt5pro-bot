# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class MainCelebritySelfieCallbackContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = Path("main.py").read_text(encoding="utf-8")
        cls.v127 = Path("celebrity_selfie_v127.py").read_text(encoding="utf-8")

    def test_production_menu_uses_fun_aiselfie(self):
        self.assertIn('InlineKeyboardButton("🤳 AI-селфи со звездой", callback_data="fun:aiselfie")', self.main)

    def test_v127_explicitly_intercepts_that_exact_value(self):
        self.assertIn('"fun:aiselfie"', self.v127)
        self.assertIn("ENTRY_CALLBACKS", self.v127)

    def test_actual_main_legacy_keys_are_removed_by_v127(self):
        for key in (
            "awaiting_ai_selfie_photo",
            "awaiting_ai_selfie_prompt",
            "ai_selfie_preset_prompt",
        ):
            self.assertIn(f'"{key}"', self.main)
            self.assertIn(f'"{key}"', self.v127)


if __name__ == "__main__":
    unittest.main()
