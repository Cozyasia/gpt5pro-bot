"""Integration-style callback tests with an isolated Telegram transport stub."""
import asyncio
import sys
import types
import unittest
from unittest.mock import patch

class Button:
    def __init__(self, text, callback_data=None):
        self.text, self.callback_data = text, callback_data

class Markup:
    def __init__(self, inline_keyboard):
        self.inline_keyboard = inline_keyboard

class Message:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kwargs):
        self.sent.append((text, kwargs))

class Query:
    def __init__(self, data):
        self.data, self.message = data, Message()
        self.from_user = types.SimpleNamespace(id=12345)
    async def answer(self):
        pass

class TelegramAdapterTests(unittest.TestCase):
    def setUp(self):
        self.patcher = patch.dict(sys.modules, {"telegram": types.SimpleNamespace(InlineKeyboardButton=Button, InlineKeyboardMarkup=Markup)})
        self.patcher.start()
        from neyrobot_prod.entertainment import game_telegram
        self.adapter = game_telegram
        self.context = types.SimpleNamespace(user_data={})
    def tearDown(self):
        self.patcher.stop()
    def click(self, data):
        q = Query(data)
        with patch.dict("os.environ", {"ENTERTAINMENT_MENU_V2": "1"}):
            asyncio.run(self.adapter.handle_game_callback(types.SimpleNamespace(callback_query=q), self.context))
        return q.message.sent[-1]
    def test_three_quizzes_complete_and_replay_same_category(self):
        for game in ("quick_quiz", "movie", "knowledge"):
            self.click("game:start:" + game)
            for index in range(5):
                state = self.context.user_data["ent_game_session"]
                self.assertIsInstance(state, dict)
                from neyrobot_prod.entertainment.games import GAME_BANKS
                correct = GAME_BANKS[game][index].correct
                result, kwargs = self.click("game:answer:" + str(index) + ":" + correct)
                self.assertIn("Верно", result)
                if index < 4:
                    self.click("game:next:" + str(index))
                else:
                    self.click("game:next:" + str(index))
            self.assertTrue(self.context.user_data["ent_game_session"]["finished"])
            self.click("game:start:" + game)
            _, kwargs = self.click("game:answer:0:a")
            buttons = kwargs["reply_markup"].inline_keyboard
            callbacks = [b.callback_data for row in buttons for b in row]
            self.assertIn("game:start:" + game, callbacks)
    def test_stale_next_button_cannot_skip_round(self):
        self.click("game:start:movie")
        self.click("game:answer:0:a")
        self.click("game:next:0")
        message, _ = self.click("game:next:0")
        self.assertIn("Раунд уже изменился", message)
        self.assertEqual(self.context.user_data["ent_game_session"]["round_index"], 1)

    def test_stale_quiz_button_cannot_score_next_round(self):
        self.click("game:start:movie")
        self.click("game:answer:0:a")
        self.click("game:next:0")
        message, _ = self.click("game:answer:0:a")
        self.assertIn("уже завершён", message)
        self.assertEqual(self.context.user_data["ent_game_session"]["round_index"], 1)
        self.assertFalse(self.context.user_data["ent_game_session"]["answered"])

    def test_adventures_are_serializable_and_finish(self):
        for game in ("detective", "story", "roleplay", "couple", "party", "truth_dare"):
            self.click("game:adventure:" + game)
            self.assertIsInstance(self.context.user_data["ent_adventure"], dict)
            self.click("game:choose:0:0")
            self.click("game:choose:1:0")
            self.assertTrue(self.context.user_data["ent_adventure"]["finished"])
    def test_stale_adventure_button_cannot_advance_twice(self):
        self.click("game:adventure:detective")
        self.click("game:choose:0:0")
        message, _ = self.click("game:choose:0:0")
        self.assertIn("устарел", message)
        self.assertEqual(self.context.user_data["ent_adventure"]["node"], 1)

    def test_game_rules_preserve_question(self):
        self.click("game:start:movie")
        _, kwargs = self.click("game:rules")
        buttons = kwargs["reply_markup"].inline_keyboard
        self.assertTrue(any(b.callback_data.startswith("game:answer:") for row in buttons for b in row))

if __name__ == "__main__":
    unittest.main()
