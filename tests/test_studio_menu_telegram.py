import json
import sys
import types
import unittest
from unittest.mock import patch

from neyrobot_prod.studio_menu_telegram import studio_navigation_markup


class TelegramHandoffTests(unittest.TestCase):
    def test_valid_route_requires_real_user_button(self):
        class Button:
            def __init__(self, text, callback_data):
                self.text, self.callback_data = text, callback_data

        class Markup:
            def __init__(self, inline_keyboard):
                self.inline_keyboard = inline_keyboard

        telegram = types.SimpleNamespace(InlineKeyboardButton=Button, InlineKeyboardMarkup=Markup)
        with patch.dict(sys.modules, {"telegram": telegram}):
            message, markup = studio_navigation_markup(json.dumps({
                "v": 1, "action": "open_mode", "route": "mode:medicine"
            }))
        self.assertIn("AI-Медицина", message)
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "mode:medicine")

    def test_payment_payload_ignored(self):
        self.assertIsNone(studio_navigation_markup('{"type":"subscribe","tier":"pro"}'))

    def test_arbitrary_route_ignored(self):
        self.assertIsNone(studio_navigation_markup('{"v":1,"action":"open_mode","route":"admin:all"}'))


if __name__ == "__main__":
    unittest.main()
