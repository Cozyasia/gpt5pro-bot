import asyncio
import os
import tempfile
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from neyrobot_prod.marketplace_pipeline import generate_and_deliver
from neyrobot_prod.marketplace_pricing import MarketplaceQuote
from neyrobot_prod.marketplace_studio import ProductProject, Stage, Output, Marketplace


class MarketplacePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = ProductProject(
            output=Output.PHOTOS, marketplace=Marketplace.OZON,
            stage=Stage.APPROVAL, reference_ids=("ref",),
            brief="Чашка", attributes_confirmed=True,
        )
        self.bot = AsyncMock()
        self.bot.send_document.return_value = SimpleNamespace(
            document=SimpleNamespace(file_id="telegram-file")
        )
        reservation = SimpleNamespace(
            key="marketplace:20:job-123", newly_reserved=True, status="reserved"
        )
        self.ledger = SimpleNamespace(
            reserve=AsyncMock(return_value=reservation),
            mark_provider_started=AsyncMock(return_value=True),
            mark_provider_failed=AsyncMock(return_value=True),
            record_output=AsyncMock(return_value=True),
            mark_output_delivered=AsyncMock(return_value=True),
            mark_delivery_unknown=AsyncMock(return_value=True),
            status=AsyncMock(),
            commit=AsyncMock(return_value=True),
            release=AsyncMock(return_value=True),
        )
        self.quote = MarketplaceQuote(
            amount_cents=48, credits=48, provider_cost_usd=0.24,
            retail_usd=0.48, provider_image_count=3,
            delivered_image_count=3, selected_reference_count=1,
            model="gpt-image-2", quality="medium",
        )
        self.kwargs = dict(
            project=self.project, bot=self.bot, chat_id=10,
            provider_client=object(), credit_ledger=self.ledger,
            user_id=20, quote=self.quote, quote_accepted=True,
            provider_enabled=True, job_id="job-123",
            artifact_dir=self.temp.name,
        )

    def test_photo_set_generates_three_ordered_files_and_commits_after_delivery(self):
        with patch(
            "neyrobot_prod.marketplace_pipeline.download_reference_images",
            new_callable=AsyncMock,
        ) as download, patch(
            "neyrobot_prod.marketplace_pipeline.generate_product_image",
            side_effect=(b"hero", b"angle", b"detail"),
        ) as provider:
            download.return_value = ("ref",)
            messages = asyncio.run(generate_and_deliver(**self.kwargs))
        self.assertEqual(len(messages), 3)
        self.assertEqual(provider.call_count, 3)
        self.assertEqual(self.bot.send_document.await_count, 3)
        self.assertEqual(self.ledger.record_output.await_count, 3)
        self.assertEqual(self.ledger.mark_output_delivered.await_count, 3)
        self.ledger.commit.assert_awaited_once_with(self.ledger.reserve.return_value)
        self.ledger.release.assert_not_awaited()
        files = sorted(os.listdir(os.path.join(self.temp.name, "job-123")))
        self.assertEqual(files, ["01-main.png", "02-angle.png", "03-detail.png"])

    def test_complete_set_is_four_provider_images_plus_local_russian_infographic(self):
        self.kwargs["project"] = replace(self.project, output=Output.COMPLETE)
        self.kwargs["quote"] = replace(
            self.quote, provider_image_count=4, delivered_image_count=5,
            provider_cost_usd=0.32, amount_cents=64, credits=64, retail_usd=0.64,
        )
        with patch(
            "neyrobot_prod.marketplace_pipeline.download_reference_images",
            new_callable=AsyncMock, return_value=("ref",),
        ), patch(
            "neyrobot_prod.marketplace_pipeline.generate_product_image",
            side_effect=(b"hero", b"angle", b"detail", b"lifestyle"),
        ) as provider, patch(
            "neyrobot_prod.marketplace_pipeline.build_infographic", return_value=b"infographic"
        ) as infographic:
            messages = asyncio.run(generate_and_deliver(**self.kwargs))
        self.assertEqual(provider.call_count, 4)
        infographic.assert_called_once_with(b"hero", "Чашка")
        self.assertEqual(len(messages), 5)

    def test_thirty_references_are_downloaded_and_provider_selects_primary_sixteen(self):
        refs = tuple(f"ref-{index}" for index in range(30))
        self.kwargs["project"] = replace(self.project, reference_ids=refs)
        with patch(
            "neyrobot_prod.marketplace_pipeline.download_reference_images",
            new_callable=AsyncMock, return_value=refs,
        ), patch(
            "neyrobot_prod.marketplace_pipeline.generate_product_image",
            side_effect=(b"one", b"two", b"three"),
        ) as provider:
            asyncio.run(generate_and_deliver(**self.kwargs))
        self.assertEqual(len(provider.call_args_list[0].args[1]), 30)

    def test_failed_delivery_is_recoverable_and_never_commits(self):
        self.bot.send_document.side_effect = RuntimeError("telegram failed")
        with patch(
            "neyrobot_prod.marketplace_pipeline.download_reference_images",
            new_callable=AsyncMock, return_value=("ref",),
        ), patch(
            "neyrobot_prod.marketplace_pipeline.generate_product_image",
            side_effect=(b"one", b"two", b"three"),
        ):
            with self.assertRaisesRegex(RuntimeError, "telegram failed"):
                asyncio.run(generate_and_deliver(**self.kwargs))
        self.ledger.mark_delivery_unknown.assert_awaited_once()
        self.ledger.commit.assert_not_awaited()
        self.ledger.release.assert_not_awaited()

    def test_provider_failure_releases_hold_without_debit(self):
        with patch(
            "neyrobot_prod.marketplace_pipeline.download_reference_images",
            new_callable=AsyncMock, return_value=("ref",),
        ), patch(
            "neyrobot_prod.marketplace_pipeline.generate_product_image",
            side_effect=RuntimeError("provider failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                asyncio.run(generate_and_deliver(**self.kwargs))
        self.ledger.mark_provider_failed.assert_awaited_once()
        self.ledger.commit.assert_not_awaited()

    def test_duplicate_reservation_cannot_trigger_another_provider_call(self):
        self.ledger.reserve.return_value = SimpleNamespace(
            key="marketplace:20:job-123", newly_reserved=False, status="provider_started"
        )
        with patch(
            "neyrobot_prod.marketplace_pipeline.download_reference_images",
            new_callable=AsyncMock, return_value=("ref",),
        ), patch("neyrobot_prod.marketplace_pipeline.generate_product_image") as provider:
            with self.assertRaisesRegex(RuntimeError, "уже существует"):
                asyncio.run(generate_and_deliver(**self.kwargs))
        provider.assert_not_called()

    def test_rejects_unaccepted_quote_and_missing_job_id(self):
        self.kwargs["quote_accepted"] = False
        with self.assertRaises(ValueError):
            asyncio.run(generate_and_deliver(**self.kwargs))
        self.kwargs["quote_accepted"] = True
        self.kwargs["job_id"] = None
        with self.assertRaises(ValueError):
            asyncio.run(generate_and_deliver(**self.kwargs))
        self.ledger.reserve.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
