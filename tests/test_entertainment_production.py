import asyncio
import types
import unittest
from neyrobot_prod.entertainment.production import BRIEFS, handle_production_brief

class Message:
    def __init__(self):
        self.texts = []
    async def reply_text(self, text):
        self.texts.append(text)

class Query:
    def __init__(self, data):
        self.data = data
        self.message = Message()
    async def answer(self):
        return None

class ProductionTests(unittest.TestCase):
    def click(self, mode):
        q = Query("ent:brief:" + mode)
        context = types.SimpleNamespace(user_data={})
        asyncio.run(handle_production_brief(types.SimpleNamespace(callback_query=q), context))
        return q.message.texts, context.user_data

    def test_all_briefs_have_descriptions(self):
        self.assertEqual(len(BRIEFS), 9)
        for mode in BRIEFS:
            messages, state = self.click(mode)
            self.assertEqual(state["ent_production_mode"], mode)
            self.assertTrue(messages)
            if mode == "video_translation":
                self.assertNotIn("awaiting_video_studio_prompt", state)
            else:
                self.assertTrue(state["awaiting_video_studio_prompt"])
                self.assertEqual(state["video_studio_mode"], "director")

    def test_unknown_brief_does_not_activate_generation(self):
        messages, state = self.click("invalid")
        self.assertTrue(messages)
        self.assertNotIn("awaiting_video_studio_prompt", state)

if __name__ == "__main__":
    unittest.main()
