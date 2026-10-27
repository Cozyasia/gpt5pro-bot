import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from neyrobot_prod.marketplace_studio import ProductProject, Stage, add_references, set_brief
from neyrobot_prod.marketplace_telegram import (STATE_KEY, save, load, receive_transcript, receive_photo, buttons, apply_action)


class MarketplaceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_photo_restores_durable_marketplace_draft_instead_of_falling_through(self):
        from neyrobot_prod.marketplace_telegram import callback, start_project

        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, "subs.db")
            bot_data = {"marketplace_db_path": database}
            user = SimpleNamespace(id=42)
            query_message = SimpleNamespace(reply_text=AsyncMock())
            query = SimpleNamespace(data="", from_user=user, message=query_message)
            first_context = SimpleNamespace(user_data={}, bot_data=bot_data)
            start_project(
                first_context.user_data,
                user_id=user.id,
                db_path=database,
            )

            query.data = "ent:brief:mp:output:infographics"
            await callback(SimpleNamespace(callback_query=query), first_context)
            query.data = "ent:brief:mp:market:yandex"
            await callback(SimpleNamespace(callback_query=query), first_context)

            # Simulate a process restart: PTB's in-memory user_data is empty, while
            # the Render disk and production SQLite database remain available.
            sent = SimpleNamespace(message_id=99)
            photo_message = SimpleNamespace(
                photo=[SimpleNamespace(file_id="porcelain-1")],
                media_group_id="album-1",
                reply_text=AsyncMock(return_value=sent),
            )
            update = SimpleNamespace(
                message=photo_message,
                effective_message=photo_message,
                effective_user=user,
                effective_chat=SimpleNamespace(id=123),
            )
            restarted_context = SimpleNamespace(
                user_data={},
                bot_data=bot_data,
                bot=SimpleNamespace(edit_message_text=AsyncMock()),
            )

            self.assertTrue(await receive_photo(update, restarted_context))
            self.assertEqual(load(restarted_context.user_data).reference_ids, ("porcelain-1",))
            self.assertIn("1/30", photo_message.reply_text.await_args.args[0])

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
