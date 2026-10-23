"""Offline checks for real-estate video prompt and menu contracts.

Run: python -m unittest tests.test_real_estate_video
"""
import asyncio
import unittest
from types import SimpleNamespace
from real_estate_video import PROMPTS, ENGINES, menu_button, keyboard


class RealEstateVideoTests(unittest.TestCase):
    def test_three_distinct_modes(self):
        self.assertEqual(set(PROMPTS), {"exterior", "interior", "full"})
        self.assertEqual(set(ENGINES), {"kling", "veo", "seedance"})
        self.assertEqual(len(set(PROMPTS.values())), 3)

    def test_architectural_consistency(self):
        for prompt in PROMPTS.values():
            self.assertIn("preserve", prompt.lower())
            self.assertIn("no ", prompt.lower())

    def test_default_prompts_describe_a_walkthrough_not_a_slideshow(self):
        for mode in ("exterior", "interior", "full"):
            prompt = PROMPTS[mode].lower()
            self.assertIn("camera", prompt)
            self.assertIn("continuous", prompt)
            self.assertIn("no static zoom", prompt)

    def test_menu_callback(self):
        self.assertEqual(menu_button().callback_data, "revideo:start")

    def test_keyboard_callbacks(self):
        k = keyboard([[("Экстерьер", "type:exterior")]])
        self.assertEqual(k.inline_keyboard[0][0].callback_data, "revideo:type:exterior")


    def test_photo_upload_feedback_is_at_bottom_and_deduplicated(self):
        from real_estate_video import photo

        class Message:
            def __init__(self, unique_id):
                self.photo = [SimpleNamespace(file_id=f"file-{unique_id}", file_unique_id=unique_id)]
                self.document = None
                self.replies = []

            async def reply_text(self, text, **kwargs):
                self.replies.append((text, kwargs))

        async def run():
            context = SimpleNamespace(user_data={"real_estate_video": {"type": "interior", "photos": []}})
            first = Message("same")
            await photo(SimpleNamespace(message=first), context)
            duplicate = Message("same")
            await photo(SimpleNamespace(message=duplicate), context)
            return context, first, duplicate

        state, first, duplicate = asyncio.run(run())
        self.assertEqual(state.user_data["real_estate_video"]["photos"], ["file-same"])
        self.assertEqual(len(first.replies), 1)
        self.assertEqual(len(duplicate.replies), 0)
        text, kwargs = first.replies[0]
        self.assertIn("1/10", text)
        callbacks = [button.callback_data for row in kwargs["reply_markup"].inline_keyboard for button in row]
        self.assertIn("revideo:photos_done", callbacks)
        self.assertIn("revideo:photos_add", callbacks)

    def test_photo_upload_hides_add_button_at_ten(self):
        from real_estate_video import photo

        class Message:
            def __init__(self, index):
                self.photo = [SimpleNamespace(file_id=f"file-{index}", file_unique_id=f"unique-{index}")]
                self.document = None
                self.replies = []

            async def reply_text(self, text, **kwargs):
                self.replies.append((text, kwargs))

        async def run():
            context = SimpleNamespace(user_data={"real_estate_video": {"type": "full", "photos": []}})
            messages = [Message(i) for i in range(10)]
            for message in messages:
                await photo(SimpleNamespace(message=message), context)
            return messages[-1]

        last = asyncio.run(run())
        text, kwargs = last.replies[0]
        self.assertIn("10/10", text)
        callbacks = [button.callback_data for row in kwargs["reply_markup"].inline_keyboard for button in row]
        self.assertNotIn("revideo:photos_add", callbacks)

if __name__ == "__main__":
    unittest.main()
