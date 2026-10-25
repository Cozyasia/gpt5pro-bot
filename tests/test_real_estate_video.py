"""Offline checks for real-estate video prompt and menu contracts.

Run: python -m unittest tests.test_real_estate_video
"""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
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
            self.assertIn("20-24mm", prompt)
            self.assertIn("1.6", prompt)

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
                return SimpleNamespace(message_id=777)

        async def run():
            context = SimpleNamespace(
                user_data={"real_estate_video": {"type": "interior", "photos": []}},
                bot=SimpleNamespace(edit_message_text=AsyncMock()),
            )
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
        self.assertIn("1/30", text)
        callbacks = [button.callback_data for row in kwargs["reply_markup"].inline_keyboard for button in row]
        self.assertIn("revideo:photos_done", callbacks)
        self.assertIn("revideo:photos_add", callbacks)

    def test_photo_upload_uses_one_progress_message_and_supports_thirty(self):
        from real_estate_video import photo

        class Message:
            def __init__(self, index):
                self.photo = [SimpleNamespace(file_id=f"file-{index}", file_unique_id=f"unique-{index}")]
                self.document = None
                self.replies = []

            async def reply_text(self, text, **kwargs):
                self.replies.append((text, kwargs))
                return SimpleNamespace(message_id=888)

        async def run():
            bot = SimpleNamespace(edit_message_text=AsyncMock())
            context = SimpleNamespace(user_data={"real_estate_video": {"type": "full", "photos": []}}, bot=bot)
            messages = [Message(i) for i in range(30)]
            for message in messages:
                await photo(SimpleNamespace(message=message), context)
            return messages, bot

        messages, bot = asyncio.run(run())
        self.assertEqual(len(messages[0].replies), 1)
        self.assertTrue(all(not message.replies for message in messages[1:]))
        self.assertEqual(bot.edit_message_text.await_count, 29)
        kwargs = bot.edit_message_text.await_args.kwargs
        self.assertIn("30/30", kwargs["text"])
        callbacks = [button.callback_data for row in kwargs["reply_markup"].inline_keyboard for button in row]
        self.assertNotIn("revideo:photos_add", callbacks)

    def test_saved_video_delivery_uses_media_timeouts(self):
        from property_video_execution import _send_saved

        async def run():
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "result.mp4"
                path.write_bytes(b"video")
                message = SimpleNamespace(reply_video=AsyncMock(return_value=SimpleNamespace(video=None)))
                await _send_saved(message, str(path), "caption")
                return message

        message = asyncio.run(run())
        kwargs = message.reply_video.await_args.kwargs
        self.assertGreaterEqual(kwargs["write_timeout"], 120)
        self.assertGreaterEqual(kwargs["read_timeout"], 120)

if __name__ == "__main__":
    unittest.main()
