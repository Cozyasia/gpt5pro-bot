# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class MainCelebritySelfieCallbackContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = Path("main.py").read_text(encoding="utf-8")
        cls.v129 = Path("celebrity_selfie_v129.py").read_text(encoding="utf-8")
        cls.v128 = Path("celebrity_selfie_v128.py").read_text(encoding="utf-8")
        cls.v127 = Path("celebrity_selfie_v127.py").read_text(encoding="utf-8")

    def test_production_menu_uses_fun_aiselfie(self):
        self.assertIn('InlineKeyboardButton("🤳 AI-селфи со звездой", callback_data="fun:aiselfie")', self.main)

    def test_v129_explicitly_intercepts_that_exact_value(self):
        self.assertIn('"fun:aiselfie"', self.v129)
        self.assertIn("ENTRY_CALLBACKS", self.v129)

    def test_actual_main_legacy_keys_remain_removed_by_runtime_chain(self):
        for key in (
            "awaiting_ai_selfie_photo",
            "awaiting_ai_selfie_prompt",
            "ai_selfie_preset_prompt",
        ):
            self.assertIn(f'"{key}"', self.main)
            self.assertIn(f'"{key}"', self.v127)
        self.assertIn("core.LEGACY_KEYS.update(previous.EXTRA_LEGACY_KEYS)", self.v128)

    def test_v129_patches_live_reference_library_before_callbacks(self):
        self.assertIn("engine.LIBRARY.root = _LIBRARY_ROOT", self.v129)
        self.assertIn("engine.LIBRARY.ensure_refs = _ensure_refs_writable", self.v129)


if __name__ == "__main__":
    unittest.main()
