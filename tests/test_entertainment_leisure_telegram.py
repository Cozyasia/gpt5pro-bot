import asyncio
import sys
import types
import unittest
from unittest.mock import patch

class Button:
    def __init__(self, text, callback_data=None):
        self.text = text
        self.callback_data = callback_data

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
        self.data = data
        self.message = Message()
    async def answer(self):
        return None

class LeisureTelegramTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch.dict(sys.modules, {"telegram": types.SimpleNamespace(
            InlineKeyboardButton=Button, InlineKeyboardMarkup=Markup)})
        self.patch.start()
        from neyrobot_prod.entertainment import leisure
        self.leisure = leisure
        self.ctx = types.SimpleNamespace(user_data={})
    def tearDown(self):
        self.patch.stop()
    def click(self, callback):
        query = Query(callback)
        asyncio.run(self.leisure.handle_leisure_callback(
            types.SimpleNamespace(callback_query=query), self.ctx))
        return query.message.sent[-1]
    def test_full_selection_flow(self):
        self.click("leisure:couple")
        self.click("leisure:interest:creative")
        self.click("leisure:budget:1000")
        text, _ = self.click("leisure:people:2")
        self.assertIn("Участников: 2", text)
        self.assertIn("1000", text)
        self.assertIn("Творчество", text)
    def test_invalid_budget_does_not_mutate(self):
        text, _ = self.click("leisure:budget:-100")
        self.assertIn("Выберите бюджет", text)
        self.assertNotIn("ent_leisure_budget", self.ctx.user_data)
    def test_invalid_party_size_does_not_mutate(self):
        text, _ = self.click("leisure:people:0")
        self.assertIn("Выберите количество", text)
        self.assertNotIn("ent_leisure_participants", self.ctx.user_data)

if __name__ == "__main__":
    unittest.main()
