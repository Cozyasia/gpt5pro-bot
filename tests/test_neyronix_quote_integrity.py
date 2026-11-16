import unittest
from decimal import Decimal
from neyronix_pricing import public_quote, retail_credits


class QuoteIntegrityTests(unittest.TestCase):
    def test_fractional_credit_is_preserved(self):
        self.assertEqual(retail_credits("0.01"), Decimal("5"))
        self.assertEqual(retail_credits("0.001"), Decimal("5"))

    def test_public_quote_does_not_disclose_internal_pricing(self):
        quote = public_quote(model="gen4_turbo", mode="image-to-video", duration=5, provider_cost_usd="0.70")
        self.assertEqual(quote["price_credits"], "140")
        self.assertEqual(set(quote), {"model", "mode", "duration_seconds", "price_credits"})
        for secret in ("provider_cost_usd", "retail_multiplier", "margin", "profit_usd"):
            self.assertNotIn(secret, str(quote))

    def test_invalid_provider_cost_is_rejected(self):
        for cost in ("NaN", "Infinity", "-0.1"):
            with self.assertRaises(ValueError):
                public_quote(model="m", mode="video", provider_cost_usd=cost)


if __name__ == "__main__":
    unittest.main()
