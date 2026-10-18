# -*- coding: utf-8 -*-
"""Static isolation checks; behavioral tests live in test_openai_selfie_terminal."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from neyrobot_prod import openai_selfie_exp_v1 as lane


ROOT = Path(__file__).resolve().parents[1]


class SelfieLaneIsolationTest(unittest.TestCase):
    def test_lane_remains_separate_from_frozen_v265(self):
        source = (ROOT / "neyrobot_prod/openai_selfie_exp_v1.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn('PREFIX = "oaiselfie:"', source)
        self.assertNotIn("dense68_engine_v265", source)
        self.assertNotIn("selfie_v265_single_owner", source)
        self.assertNotIn("cs201:", source)

    def test_existing_direct_edit_route_is_retained(self):
        source = (ROOT / "neyrobot_prod/openai_selfie_exp_v1.py").read_text(encoding="utf-8")
        self.assertIn("https://api.openai.com/v1/images/edits", source)
        self.assertIn('"image[]"', source)
        self.assertIn("OPENAI_API_KEY", source)

    def test_v265_reference_stays_installed_but_out_of_entertainment_menu(self):
        init = (ROOT / "neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        lane = (ROOT / "neyrobot_prod/openai_selfie_exp_v1.py").read_text(encoding="utf-8")
        self.assertIn('PRODUCTION_SELFIE_RUNTIME = "v265"', init)
        self.assertIn("openai_selfie_exp_v1", init)
        self.assertIn('callback_data=PREFIX + "open"', lane)
        self.assertIn('("fun:aiselfie",)', lane)


class SelfieMenuCompatibilityTest(unittest.TestCase):
    def test_menu_wrappers_forward_owner_canary_user_id(self):
        calls = []

        class Button:
            def __init__(self, text, callback_data):
                self.text = text
                self.callback_data = callback_data

        class Markup:
            def __init__(self, rows):
                self.inline_keyboard = rows

        def quick(user_id=None):
            calls.append(("quick", user_id))
            return Markup([[Button("AI selfie", "fun:aiselfie")]])

        def mode(key, user_id=None):
            calls.append(("mode", key, user_id))
            return Markup([[Button("AI selfie", "act:fun:aiselfie")]])

        runtime = SimpleNamespace(
            _fun_quick_kb=quick,
            _mode_kb=mode,
            InlineKeyboardButton=Button,
            InlineKeyboardMarkup=Markup,
        )
        with patch.object(lane, "_runtime", return_value=runtime):
            self.assertTrue(lane._patch_fun_menus())

        quick_markup = runtime._fun_quick_kb(4242)
        mode_markup = runtime._mode_kb("fun", 4242)

        self.assertIn(("quick", 4242), calls)
        self.assertIn(("mode", "fun", 4242), calls)
        self.assertEqual("oaiselfie:open", quick_markup.inline_keyboard[0][0].callback_data)
        self.assertEqual("oaiselfie:open", mode_markup.inline_keyboard[0][0].callback_data)
