import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from neyrobot_prod.marketplace_pipeline import generate_and_deliver
from neyrobot_prod.marketplace_studio import ProductProject, Stage, Output, Marketplace


class MarketplacePipelineTests(unittest.TestCase):
    def setUp(self):
        self.project = ProductProject(
            output=Output.PHOTOS, marketplace=Marketplace.OZON,
            stage=Stage.APPROVAL, reference_ids=("ref",),
            brief="Чашка", attributes_confirmed=True,
        )
        self.bot = AsyncMock()
        self.bot.send_document.return_value = "sent"
        self.ledger = SimpleNamespace(
            reserve=AsyncMock(return_value=SimpleNamespace(id="reservation", newly_reserved=True)),
            commit=AsyncMock(),
            release=AsyncMock(),
        )
        self.kwargs = dict(
            project=self.project, bot=self.bot, chat_id=10,
            provider_client=object(), credit_ledger=self.ledger,
            user_id=20, quoted_credits=5, quote_accepted=True,
            provider_enabled=True, job_id='job-123',
        )

    def test_success_reserves_delivers_commits(self):
        with patch("neyrobot_prod.marketplace_pipeline.download_reference_images", new_callable=AsyncMock) as download, \
             patch("neyrobot_prod.marketplace_pipeline.generate_product_image", return_value=b"png"):
            download.return_value = ("ref",)
            result = asyncio.run(generate_and_deliver(**self.kwargs))
        self.assertEqual(result, "sent")
        self.ledger.reserve.assert_awaited_once()
        self.bot.send_document.assert_awaited_once()
        self.ledger.commit.assert_awaited_once_with(self.ledger.reserve.return_value)
        self.ledger.release.assert_not_awaited()

    def test_refuses_unaccepted_quote_without_provider_call(self):
        self.kwargs["quote_accepted"] = False
        with self.assertRaises(ValueError):
            asyncio.run(generate_and_deliver(**self.kwargs))
        self.ledger.reserve.assert_not_awaited()

    def test_failed_delivery_keeps_reservation_for_reconciliation(self):
        self.bot.send_document.side_effect = RuntimeError("telegram failed")
        with patch("neyrobot_prod.marketplace_pipeline.download_reference_images", new_callable=AsyncMock) as download, \
             patch("neyrobot_prod.marketplace_pipeline.generate_product_image", return_value=b"png"):
            download.return_value = ("ref",)
            with self.assertRaises(RuntimeError):
                asyncio.run(generate_and_deliver(**self.kwargs))
        self.ledger.release.assert_not_awaited()

    def test_duplicate_reservation_cannot_trigger_paid_generation(self):
        self.ledger.reserve.return_value = SimpleNamespace(id='reservation', newly_reserved=False)
        with patch('neyrobot_prod.marketplace_pipeline.download_reference_images', new_callable=AsyncMock) as download, \\
             patch('neyrobot_prod.marketplace_pipeline.generate_product_image') as provider:
            download.return_value = ('ref',)
            with self.assertRaisesRegex(RuntimeError, 'уже существует'):
                asyncio.run(generate_and_deliver(**self.kwargs))
            provider.assert_not_called()
        self.ledger.commit.assert_not_awaited()

    def test_rejects_missing_job_id(self):
        self.kwargs['job_id'] = None
        with self.assertRaises(ValueError):
            asyncio.run(generate_and_deliver(**self.kwargs))
        self.ledger.reserve.assert_not_awaited()

    def test_failed_commit_does_not_refund_delivered_image(self):
        self.ledger.commit.side_effect = RuntimeError("ledger unavailable")
        with patch("neyrobot_prod.marketplace_pipeline.download_reference_images", new_callable=AsyncMock) as download, \
             patch("neyrobot_prod.marketplace_pipeline.generate_product_image", return_value=b"png"):
            download.return_value = ("ref",)
            with self.assertRaises(RuntimeError):
                asyncio.run(generate_and_deliver(**self.kwargs))
        self.ledger.release.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
