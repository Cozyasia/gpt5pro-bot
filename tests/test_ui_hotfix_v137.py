# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from telegram.ext import ApplicationHandlerStop

import ui_hotfix_v137 as ui


class _Message:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kwargs):
        self.sent.append((text, reply_markup))
        return SimpleNamespace()


class _Query:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.answered = 0

    async def answer(self, *args, **kwargs):
        self.answered += 1


class UIHotfixV137Tests(unittest.IsolatedAsyncioTestCase):
    def test_redundant_upload_button_is_removed(self):
        markup = ui._photo_choice_kb(False)
        labels = [button.text for row in markup.inline_keyboard for button in row]
        self.assertEqual(labels, ["Отмена"])
        self.assertNotIn("Загрузить", " ".join(labels))

    def test_cached_photo_keeps_only_use_last_and_cancel(self):
        markup = ui._photo_choice_kb(True)
        labels = [button.text for row in markup.inline_keyboard for button in row]
        self.assertEqual(labels, ["Использовать последнее фото", "Отмена"])

    def test_chat_buttons_have_brand_fallbacks_and_styles(self):
        markup = ui._chat_provider_markup("gpt")
        buttons = [button for row in markup.inline_keyboard for button in row]
        self.assertIn("◉ Чат с GPT", buttons[0].text)
        self.assertIn("✦ Чат с Gemini", buttons[1].text)
        self.assertEqual(buttons[0].api_kwargs.get("style"), "success")
        self.assertEqual(buttons[1].api_kwargs.get("style"), "primary")
        self.assertEqual(buttons[2].api_kwargs.get("style"), "danger")

    def test_optional_custom_emoji_id_is_passed_through(self):
        with patch.dict("os.environ", {"GPT_BUTTON_CUSTOM_EMOJI_ID": "123456789"}, clear=False):
            markup = ui._chat_provider_markup("gpt")
            button = markup.inline_keyboard[0][0]
            self.assertEqual(button.api_kwargs.get("icon_custom_emoji_id"), "123456789")
            self.assertNotIn("◉", button.text)

    async def test_continue_one_is_owned_and_opens_catalog(self):
        message = _Message()
        query = _Query("cs136:continue_one", message)
        update = SimpleNamespace(callback_query=query, effective_message=message)
        context = SimpleNamespace(user_data={})
        session = {"user_photo_path": "/tmp/user.jpg", "state": "await_optional_user_photo"}
        data = {}
        catalog_markup = object()

        with patch.object(ui.selfie.wizard, "_session", return_value=session), \
             patch.object(ui.selfie.wizard, "_data", return_value=data), \
             patch.object(ui.selfie.wizard, "_clear_legacy_state", return_value=None), \
             patch.object(ui.selfie.wizard, "_celebrity_menu_kb", return_value=catalog_markup):
            with self.assertRaises(ApplicationHandlerStop):
                await ui._continue_callback(update, context)

        self.assertEqual(query.answered, 1)
        self.assertEqual(session["state"], "choose_celebrity")
        self.assertEqual(message.sent[-1][1], catalog_markup)
        self.assertNotIn("Неизвестная команда", message.sent[-1][0])

    def test_dedicated_callback_priority_is_before_legacy_router(self):
        self.assertLess(ui._GROUP, -50000)


if __name__ == "__main__":
    unittest.main()
