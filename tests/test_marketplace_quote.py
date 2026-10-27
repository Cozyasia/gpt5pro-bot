import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from neyrobot_prod.marketplace_telegram import quote_callback
from neyrobot_prod.marketplace_studio import ProductProject, Stage, Output, Marketplace
from neyrobot_prod.marketplace_pricing import MarketplaceQuote


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
        self.assertNotIn('mp_quoted_usd_cents', self.context.user_data)
        self.assertIn('недоступен', self.reply.await_args.args[0])

    def test_valid_quote_is_saved_without_charge(self):
        service = AsyncMock(return_value=MarketplaceQuote(
            amount_cents=48, credits=48, provider_cost_usd=0.24, retail_usd=0.48,
            provider_image_count=3, delivered_image_count=3,
            selected_reference_count=1, model="gpt-image-2", quality="medium",
        ))
        self.context.bot_data['marketplace_quote_service'] = service
        asyncio.run(quote_callback(self.update, self.context, self.project))
        self.assertEqual(self.context.user_data['mp_quoted_usd_cents'], 48)
        self.assertEqual(self.context.user_data['mp_quote_details']['delivered_image_count'], 3)
        service.assert_awaited_once()
        self.assertIn('$0.48 USD', self.reply.await_args.args[0])
        self.assertIn('3', self.reply.await_args.args[0])

    def test_invalid_quote_does_not_save(self):
        self.context.bot_data['marketplace_quote_service'] = AsyncMock(return_value=True)
        asyncio.run(quote_callback(self.update, self.context, self.project))
        self.assertNotIn('mp_quoted_usd_cents', self.context.user_data)

    def test_more_than_sixteen_images_uses_primary_sixteen_without_rejection(self):
        from dataclasses import replace
        self.context.bot_data['marketplace_quote_service'] = AsyncMock(return_value=MarketplaceQuote(
            amount_cents=48, credits=48, provider_cost_usd=0.24, retail_usd=0.48,
            provider_image_count=3, delivered_image_count=3,
            selected_reference_count=16, model="gpt-image-2", quality="medium",
        ))
        project = replace(self.project, reference_ids=tuple(str(i) for i in range(17)))
        asyncio.run(quote_callback(self.update, self.context, project))
        self.context.bot_data['marketplace_quote_service'].assert_awaited_once()
        self.assertIn('Основных референсов: 16 из 17', self.reply.await_args.args[0])


if __name__ == '__main__':
    unittest.main()
