import asyncio
import unittest

from neyrobot_prod.marketplace_generation import GenerationRequest
from neyrobot_prod.marketplace_pricing import MarketplaceQuote, build_marketplace_quote_service
from neyrobot_prod.marketplace_studio import Output


class MarketplacePricingTests(unittest.TestCase):
    def setUp(self):
        self.service = build_marketplace_quote_service(
            retail_usd=lambda provider_cost: round(provider_cost * 2, 2),
            usd_to_credits=lambda usd: usd * 100,
            provider_cost_per_image_usd=0.08,
            model="gpt-image-2",
            quality="medium",
        )

    def quote(self, output, refs=20):
        request = GenerationRequest(
            output=output,
            marketplace="ozon",
            reference_file_ids=tuple(f"photo-{index}" for index in range(refs)),
            brief="Фарфоровый сервиз на шесть персон",
        )
        return asyncio.run(self.service(request=request, user_id=42))

    def test_photos_quote_is_itemized_and_uses_existing_retail_policy(self):
        quote = self.quote(Output.PHOTOS)
        self.assertIsInstance(quote, MarketplaceQuote)
        self.assertEqual(quote.provider_image_count, 3)
        self.assertEqual(quote.delivered_image_count, 3)
        self.assertEqual(quote.selected_reference_count, 16)
        self.assertEqual(quote.provider_cost_usd, 0.24)
        self.assertEqual(quote.retail_usd, 0.48)
        self.assertEqual(quote.amount_cents, 48)
        self.assertEqual(quote.credits, 48)
        self.assertEqual(quote.model, "gpt-image-2")
        self.assertEqual(quote.quality, "medium")

    def test_infographic_and_complete_quotes_match_real_provider_call_counts(self):
        infographic = self.quote(Output.INFOGRAPHICS, refs=4)
        complete = self.quote(Output.COMPLETE, refs=4)
        self.assertEqual((infographic.provider_image_count, infographic.delivered_image_count), (1, 2))
        self.assertEqual((complete.provider_image_count, complete.delivered_image_count), (4, 5))
        self.assertEqual(infographic.amount_cents, 16)
        self.assertEqual(complete.amount_cents, 64)

    def test_video_quote_is_rejected_instead_of_claiming_image_support(self):
        with self.assertRaisesRegex(ValueError, "видеоконвейер"):
            self.quote(Output.VIDEO)


if __name__ == "__main__":
    unittest.main()
