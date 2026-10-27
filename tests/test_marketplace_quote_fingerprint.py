import unittest
from dataclasses import replace

from neyrobot_prod.marketplace_generation import prepare_generation
from neyrobot_prod.marketplace_quote import (
    fingerprint, validated_marketplace_quote, validated_quote_cents,
)
from neyrobot_prod.marketplace_pricing import MarketplaceQuote
from neyrobot_prod.marketplace_studio import ProductProject, Stage, Output, Marketplace


class QuoteFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.project = ProductProject(
            output=Output.PHOTOS, marketplace=Marketplace.OZON,
            stage=Stage.APPROVAL, reference_ids=("photo-1",),
            brief="Чашка", attributes_confirmed=True)
        self.request = prepare_generation(self.project)

    def test_same_request_validates(self):
        state = {"mp_quoted_usd_cents": 125, "mp_quote_fingerprint": fingerprint(self.request)}
        self.assertEqual(validated_quote_cents(state, self.request), 125)

    def test_modified_brief_invalidates_price(self):
        state = {"mp_quoted_usd_cents": 125, "mp_quote_fingerprint": fingerprint(self.request)}
        changed = prepare_generation(replace(self.project, brief="Другая чашка"))
        with self.assertRaisesRegex(ValueError, "заново"):
            validated_quote_cents(state, changed)

    def test_changed_references_invalidates_price(self):
        state = {"mp_quoted_usd_cents": 125, "mp_quote_fingerprint": fingerprint(self.request)}
        changed = prepare_generation(replace(self.project, reference_ids=("photo-2",)))
        with self.assertRaises(ValueError):
            validated_quote_cents(state, changed)

    def test_invalid_price_fails_closed(self):
        for amount in (None, 0, True, -1):
            with self.assertRaises(ValueError):
                validated_quote_cents({"mp_quoted_usd_cents": amount,
                                       "mp_quote_fingerprint": fingerprint(self.request)}, self.request)

    def test_full_quote_expires_and_cannot_be_charged(self):
        quote = MarketplaceQuote(125, 125, 0.5, 1.25, 3, 3, 1, "gpt-image-2", "medium")
        state = {
            "mp_quoted_usd_cents": 125,
            "mp_quote_fingerprint": fingerprint(self.request),
            "mp_quote_created_ts": 1000,
            "mp_quote_details": quote.to_dict(),
        }
        self.assertEqual(
            validated_marketplace_quote(state, self.request, now=1100), quote
        )
        with self.assertRaisesRegex(ValueError, "устарела"):
            validated_marketplace_quote(state, self.request, now=2000)


if __name__ == "__main__":
    unittest.main()
