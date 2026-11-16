from decimal import Decimal
import unittest
from neyronix_pricing import credits_from_usd, retail_credits, public_quote


class PricingPolicyTests(unittest.TestCase):
    def test_markup(self):
        self.assertEqual(retail_credits("1"), Decimal("200"))
        self.assertEqual(retail_credits("0.10"), Decimal("20"))
        self.assertEqual(retail_credits("0.01"), Decimal("5"))
        self.assertEqual(retail_credits("0"), Decimal("0"))

    def test_wallet_conversion(self):
        self.assertEqual(credits_from_usd("25"), Decimal("2500"))

    def test_public_quote_has_no_internal_cost(self):
        quote = public_quote(model="gen4.5", mode="image-to-video", duration=8, provider_cost_usd="1.2")
        self.assertEqual(quote["price_credits"], "240")
        self.assertNotIn("provider_cost_usd", quote)
        self.assertNotIn("markup", quote)

    def test_invalid_inputs(self):
        for value in ("-1", "NaN", "Infinity"):
            with self.assertRaises(ValueError):
                retail_credits(value)


if __name__ == "__main__":
    unittest.main()
