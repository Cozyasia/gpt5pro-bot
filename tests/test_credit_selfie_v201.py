# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import tempfile
import types
import unittest

from neyrobot_prod import celebrity_selfie
from neyrobot_prod import credit_store_v201 as credit_store


class Button:
    def __init__(self, text: str, callback_data: str | None = None, url: str | None = None):
        self.text = text
        self.callback_data = callback_data
        self.url = url


class Markup:
    def __init__(self, rows):
        self.inline_keyboard = rows


class CreditAndSelfieV201Tests(unittest.TestCase):
    def setUp(self):
        self.saved_env = dict(os.environ)
        for key in list(os.environ):
            if key.startswith("CREDIT_PACK_") or key == "CELEBRITY_SELFIE_DATA_DIR":
                os.environ.pop(key, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved_env)

    def test_missing_zero_credit_env_is_repaired(self):
        os.environ["CREDIT_PACK_SMALL_CREDITS"] = "100"
        os.environ["CREDIT_PACK_MID_CREDITS"] = "300"
        os.environ["CREDIT_PACK_BIG_CREDITS"] = "700"
        self.assertEqual(
            [(pack.credits, pack.rub) for pack in credit_store.catalog()],
            [(1000, 990), (3000, 2490), (7000, 4990)],
        )
        self.assertEqual(credit_store.resolve_pack(100, 990), (1000, 990))
        self.assertEqual(credit_store.resolve_pack(300, 2490), (3000, 2490))
        self.assertIsNone(credit_store.resolve_pack(100, 2490))

    def test_credit_buttons_use_canonical_numbers(self):
        mod = types.SimpleNamespace(InlineKeyboardButton=Button, InlineKeyboardMarkup=Markup)
        labels = [button.text for row in credit_store.store_keyboard(mod).inline_keyboard for button in row]
        self.assertIn("🪙 1 000 кр. · 990 ₽", labels)
        self.assertIn("🪙 3 000 кр. · 2 490 ₽", labels)
        self.assertIn("🪙 7 000 кр. · 4 990 ₽", labels)

    def test_selfie_payload_contains_user_plus_three_character_refs(self):
        images = [(letter, "image/jpeg") for letter in ("a", "b", "c", "d")]
        body = celebrity_selfie._payload("prompt", images, compatibility=False)
        parts = body["contents"][0]["parts"]
        self.assertEqual(sum(1 for part in parts if "inline_data" in part), 4)

    def test_character_is_enabled_only_after_three_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            os.environ["CELEBRITY_SELFIE_DATA_DIR"] = directory
            mod = types.SimpleNamespace(DB_PATH=os.path.join(directory, "db.sqlite"))
            self.assertFalse(celebrity_selfie._character_ready(mod, "roman_abramovich"))
            root = celebrity_selfie._character_dir(mod, "roman_abramovich")
            for index in range(1, 4):
                (root / f"{index}.jpg").write_bytes(b"x" * 2048)
            self.assertTrue(celebrity_selfie._character_ready(mod, "roman_abramovich"))

    def test_selfie_menu_and_paid_runtime_are_patched(self):
        async def original(*args, **kwargs):
            return True

        mod = types.SimpleNamespace(
            _run_ai_selfie_image=original,
            _ai_selfie_action_kb=lambda prefix="act": Markup([]),
            _ai_selfie_menu_text=lambda: "legacy",
            InlineKeyboardButton=Button,
            InlineKeyboardMarkup=Markup,
        )
        self.assertTrue(celebrity_selfie.patch_runtime(mod))
        self.assertTrue(getattr(mod._run_ai_selfie_image, "_celebrity_selfie_v201", False))
        callbacks = [button.callback_data for row in mod._ai_selfie_action_kb().inline_keyboard for button in row]
        self.assertIn("cs201:photo", callbacks)
        self.assertIn("cs201:last", callbacks)
        self.assertIn("cs201:characters", callbacks)


if __name__ == "__main__":
    unittest.main()
