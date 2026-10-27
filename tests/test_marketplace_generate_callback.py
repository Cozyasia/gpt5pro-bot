import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from neyrobot_prod.marketplace_studio import ProductProject, Output, Marketplace, Stage
from neyrobot_prod.marketplace_telegram import generate_callback, save
from neyrobot_prod.marketplace_generation import prepare_generation
from neyrobot_prod.marketplace_quote import fingerprint


class GenerateCallbackTests(unittest.TestCase):
    def setUp(self):
        self.project = ProductProject(
            output=Output.PHOTOS, marketplace=Marketplace.OZON,
            stage=Stage.APPROVAL, reference_ids=('file-1',),
            brief='Фарфоровая чашка', attributes_confirmed=True)
        self.message = SimpleNamespace(reply_text=AsyncMock())
        self.update = SimpleNamespace(
            callback_query=SimpleNamespace(message=self.message),
            effective_user=SimpleNamespace(id=55),
            effective_chat=SimpleNamespace(id=66))
        self.data = {}
        save(self.data, self.project)
        self.data['mp_quoted_usd_cents'] = 125
        self.data['mp_quote_fingerprint'] = fingerprint(prepare_generation(self.project))
        self.context = SimpleNamespace(user_data=self.data, bot_data={}, bot=AsyncMock())

    def test_feature_disabled_cannot_charge(self):
        with patch.dict('os.environ', {'MARKETPLACE_PAID_GENERATION_ENABLED': '0'}):
            asyncio.run(generate_callback(self.update, self.context, self.project))
        self.assertIn('отключена', self.message.reply_text.await_args.args[0])
        self.context.bot.get_file.assert_not_awaited()

    def test_missing_provider_cannot_charge(self):
        with patch.dict('os.environ', {'MARKETPLACE_PAID_GENERATION_ENABLED': '1'}):
            asyncio.run(generate_callback(self.update, self.context, self.project))
        self.assertIn('не настроен', self.message.reply_text.await_args.args[0])

    def test_success_calls_pipeline_once_and_clears_quote(self):
        self.context.bot_data['marketplace_usd_ledger'] = object()
        self.context.bot_data['marketplace_image_client'] = object()
        with patch.dict('os.environ', {'MARKETPLACE_PAID_GENERATION_ENABLED': '1'}):
            with patch('neyrobot_prod.marketplace_pipeline.generate_and_deliver', new_callable=AsyncMock) as generate:
                asyncio.run(generate_callback(self.update, self.context, self.project))
        generate.assert_awaited_once()
        self.assertEqual(generate.await_args.kwargs['quoted_credits'], 125)
        self.assertNotIn('mp_quoted_usd_cents', self.data)
        self.assertNotIn('mp_generation_job_id', self.data)

    def test_stale_quote_cannot_charge(self):
        self.data['mp_quote_fingerprint'] = 'wrong'
        self.context.bot_data['marketplace_usd_ledger'] = object()
        self.context.bot_data['marketplace_image_client'] = object()
        with patch.dict('os.environ', {'MARKETPLACE_PAID_GENERATION_ENABLED': '1'}):
            with patch('neyrobot_prod.marketplace_pipeline.generate_and_deliver', new_callable=AsyncMock) as generate:
                asyncio.run(generate_callback(self.update, self.context, self.project))
        generate.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
