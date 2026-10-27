import unittest
from unittest.mock import AsyncMock, SimpleNamespace, patch
from neyrobot_prod.marketplace_studio import ProductProject, Stage, add_references, set_brief
from neyrobot_prod.marketplace_telegram import (STATE_KEY, save, load, receive_transcript, receive_photo, buttons, apply_action)


class MarketplaceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_brief_shows_confirmation_button(self):
        data = {}
        project = ProductProject(stage=Stage.BRIEF, reference_ids=("photo1",))
        save(data, project)
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(message=message)
        context = SimpleNamespace(user_data=data)
        self.assertTrue(await receive_transcript(update, context, "Керамическая чашка"))
        self.assertEqual(load(data).stage, Stage.REVIEW)
        markup = message.reply_text.await_args.kwargs["reply_markup"]
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("ent:brief:mp:confirm", callbacks)

    async def test_album_keeps_single_status_and_updates_count(self):
        data = {}
        save(data, ProductProject(stage=Stage.REFERENCES))
        sent = SimpleNamespace(message_id=42)
        message = SimpleNamespace(photo=[SimpleNamespace(file_id="photo1")], media_group_id="album1", reply_text=AsyncMock(return_value=sent))
        update = SimpleNamespace(message=message, effective_chat=SimpleNamespace(id=123))
        bot = SimpleNamespace(edit_message_text=AsyncMock())
        context = SimpleNamespace(user_data=data, bot=bot)
        self.assertTrue(await receive_photo(update, context))
        message.photo = [SimpleNamespace(file_id="photo2")]
        self.assertTrue(await receive_photo(update, context))
        self.assertEqual(len(load(data).reference_ids), 2)
        self.assertEqual(message.reply_text.await_count, 1)
        self.assertEqual(bot.edit_message_text.await_count, 1)
        self.assertIn("2/30", bot.edit_message_text.await_args.kwargs["text"])
        self.assertIsNotNone(bot.edit_message_text.await_args.kwargs["reply_markup"])

    def test_review_confirmation_and_invalid_stage(self):
        p = set_brief(ProductProject(stage=Stage.BRIEF, reference_ids=("a",)), "Кружка")
        self.assertEqual(apply_action(p, "confirm").stage, Stage.APPROVAL)
        with self.assertRaises(ValueError):
            apply_action(ProductProject(), "confirm")


if __name__ == "__main__":
    unittest.main()
