import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from neyrobot_prod.marketplace_telegram import quote_callback
from neyrobot_prod.marketplace_studio import ProductProject, Stage, Output, Marketplace


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.project = ProductProject(
            output=Output.PHOTOS, marketplace=Marketplace.OZON,
            stage=Stage.APPROVAL, reference_ids=('ref',),
            brief='Керамическая чашка', attributes_confirmed=True)
        self.reply = AsyncMock()
        self.update = SimpleNamespace(
            callback_query=SimpleNamespace(message=SimpleNamespace(reply_text=self.reply)),
            effective_user=SimpleNamespace(id=42))
        self.context = SimpleNamespace(bot_data={}, user_data={})

    def test_missing_pricing_service_is_fail_closed(self):
        asyncio.run(quote_callback(self.update, self.context, self.project))
        self.assertNotIn('mp_quoted_credits', self.context.user_data)
        self.assertIn('недоступен', self.reply.await_args.args[0])

    def test_valid_quote_is_saved_without_charge(self):
        service = AsyncMock(return_value=7)
        self.context.bot_data['marketplace_quote_service'] = service
        asyncio.run(quote_callback(self.update, self.context, self.project))
        self.assertEqual(self.context.user_data['mp_quoted_credits'], 7)
        service.assert_awaited_once()
        self.assertIn('7 кредитов', self.reply.await_args.args[0])

    def test_invalid_quote_does_not_save(self):
        self.context.bot_data['marketplace_quote_service'] = AsyncMock(return_value=True)
        asyncio.run(quote_callback(self.update, self.context, self.project))
        self.assertNotIn('mp_quoted_credits', self.context.user_data)

    def test_more_than_sixteen_images_does_not_call_pricing(self):
        from dataclasses import replace
        self.context.bot_data['marketplace_quote_service'] = AsyncMock()
        project = replace(self.project, reference_ids=tuple(str(i) for i in range(17)))
        asyncio.run(quote_callback(self.update, self.context, project))
        self.context.bot_data['marketplace_quote_service'].assert_not_awaited()
        self.assertIn('16', self.reply.await_args.args[0])


if __name__ == '__main__':
    unittest.main()
