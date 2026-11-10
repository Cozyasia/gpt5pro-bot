# -*- coding: utf-8 -*-
import asyncio
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from neyrobot_prod import selfie_v208_overlay as v208


class SelfieV208OverlayTests(unittest.TestCase):
    def test_country_catalogue_has_ten_names_per_country(self):
        self.assertGreaterEqual(sum(x["country"] == "ru" for x in v208.CHARACTERS.values()), 10)
        self.assertGreaterEqual(sum(x["country"] == "us" for x in v208.CHARACTERS.values()), 10)

    def test_reply_keyboard_modes_are_not_reused_as_scenes(self):
        self.assertEqual(v208._mode("🔥 Развлечения"), ("fun", "Развлечения"))
        self.assertEqual(v208._mode("💼 Работа/Бизнес"), ("work", "Работа/Бизнес"))
        self.assertEqual(v208._mode("🩺 Медицина"), ("medicine", "Медицина"))
        self.assertIsNone(v208._mode("селфи на премьере"))

    def test_root_keyboard_actions_do_not_fall_through_to_unknown_mode(self):
        class Stop(Exception):
            pass

        calls = []

        async def balance(update, context):
            calls.append("balance")

        async def engines(update, context):
            calls.append("engines")

        runtime = SimpleNamespace(cmd_balance=balance, cmd_engines=engines)
        update = SimpleNamespace(
            effective_message=SimpleNamespace(text="🧾 Баланс"),
            effective_user=SimpleNamespace(id=7),
        )
        context = SimpleNamespace(user_data={})
        telegram = types.ModuleType("telegram")
        telegram_ext = types.ModuleType("telegram.ext")
        telegram_ext.ApplicationHandlerStop = Stop
        telegram.ext = telegram_ext
        with patch.dict(sys.modules, {"telegram": telegram, "telegram.ext": telegram_ext}), patch.object(v208, "_runtime", return_value=runtime):
            with self.assertRaises(Stop):
                asyncio.run(v208._mode_router(update, context))
        self.assertEqual(calls, ["balance"])

    def test_two_user_photos_are_collected(self):
        context = SimpleNamespace(user_data={})
        self.assertEqual(v208._append_photo(context, b"a" * 2000), 1)
        self.assertEqual(v208._append_photo(context, b"b" * 2000), 2)
        self.assertEqual(len(v208._photos(context)), 2)


if __name__ == "__main__":
    unittest.main()
