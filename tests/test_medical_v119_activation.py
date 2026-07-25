# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import sys
import types
import unittest

from neyrobot_prod import medical_followup


class Button:
    def __init__(self, text: str, callback_data: str = ""):
        self.text = text
        self.callback_data = callback_data


class Markup:
    def __init__(self, rows):
        self.inline_keyboard = rows


class MedicalActivationTests(unittest.TestCase):
    def setUp(self):
        self.saved = {
            name: sys.modules.get(name)
            for name in (
                "medical_card_v109_patch",
                "medical_v111_runtime",
                "medical_card_v110_patch",
            )
        }

        self.calls = []
        card = types.ModuleType("medical_card_v109_patch")
        card._offer_save = None
        card._init_db = lambda mod: setattr(mod, "card_db_initialized", True)

        runtime = types.ModuleType("medical_v111_runtime")

        async def send_answer(mod, update, context, answer):
            return None

        async def analyze(mod, update, context, value, goal, is_image):
            self.calls.append((value, goal, is_image))

        runtime._send_answer = send_answer
        runtime.analyze = analyze

        card110 = types.ModuleType("medical_card_v110_patch")
        card110._install_medical_routing = lambda mod: setattr(mod, "medical_routing_installed", True)

        sys.modules["medical_card_v109_patch"] = card
        sys.modules["medical_v111_runtime"] = runtime
        sys.modules["medical_card_v110_patch"] = card110

    def tearDown(self):
        for name, module in self.saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    @staticmethod
    def _mod():
        async def legacy(*args, **kwargs):
            return None

        return types.SimpleNamespace(
            BOT_TOKEN="token",
            InlineKeyboardButton=Button,
            InlineKeyboardMarkup=Markup,
            medicine_kb=lambda: Markup([
                [Button("🧪 Анализы", "med:labs")],
                [Button("⬅️ Назад", "med:back")],
            ]),
            _medical_menu_text=lambda track="": "🩺 Медицина",
            _medical_analyze_text=legacy,
            _medical_analyze_image=legacy,
        )

    def test_public_handlers_are_pinned_to_v119(self):
        mod = self._mod()
        self.assertTrue(medical_followup.patch_runtime(mod))
        self.assertTrue(getattr(mod._medical_analyze_text, "_prod_v119_medical", False))
        self.assertTrue(getattr(mod._medical_analyze_image, "_prod_v119_medical", False))
        self.assertTrue(mod.medical_routing_installed)
        self.assertTrue(mod.card_db_initialized)

        asyncio.run(mod._medical_analyze_text(None, None, "pdf text", "анализы"))
        asyncio.run(mod._medical_analyze_image(None, None, b"image", "снимок"))
        self.assertEqual(self.calls, [
            ("pdf text", "анализы", False),
            (b"image", "снимок", True),
        ])

    def test_medical_card_button_is_added_once_before_back(self):
        mod = self._mod()
        self.assertTrue(medical_followup.patch_runtime(mod))
        self.assertTrue(medical_followup.patch_runtime(mod))

        rows = mod.medicine_kb().inline_keyboard
        callbacks = [button.callback_data for row in rows for button in row]
        self.assertEqual(callbacks.count("medcard:open"), 1)
        self.assertLess(callbacks.index("medcard:open"), callbacks.index("med:back"))
        self.assertIn("Медицинская карта:", mod._medical_menu_text())


if __name__ == "__main__":
    unittest.main()
