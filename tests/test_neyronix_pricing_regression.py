"""Regression checks for NEYRONIX pricing and confirmation safety.

These tests do not access a wallet, provider, or payment gateway.
"""
from decimal import Decimal
import unittest

from neyronix_pricing import credits_from_usd, public_quote, retail_credits
from neyronix_quotes import make_quote, validate_confirmation, customer_summary


class PricingSafetyTests(unittest.TestCase):
    def test_fractional_rounding_is_upward(self):
        self.assertEqual(retail_credits("0.001"), Decimal("0.1"))
        self.assertEqual(retail_credits("1"), Decimal("15.0"))
        self.assertEqual(retail_credits("1.001"), Decimal("15.1"))

    def test_invalid_provider_costs_fail_closed(self):
        for value in ("NaN", "Infinity", "-1", "invalid"):
            with self.subTest(value=value):
                with self.assertRaises((ValueError, ArithmeticError)):
                    retail_credits(value)

    def test_public_quote_never_exposes_wholesale(self):
        quote = public_quote(model="runway", mode="i2v", duration=5, provider_cost_usd="1")
        self.assertEqual(quote["price_credits"], "15.0")
        self.assertNotIn("provider_cost_usd", quote)
        self.assertNotIn("multiplier", quote)

    def test_confirmation_is_owner_bound_and_expires(self):
        quote = make_quote(user_id=42, engine="runway", feature="i2v",
                           provider_cost_usd="1", now=100)
        self.assertTrue(validate_confirmation(quote, user_id=42, token=quote.token, now=400))
        self.assertFalse(validate_confirmation(quote, user_id=43, token=quote.token, now=101))
        self.assertFalse(validate_confirmation(quote, user_id=42, token=quote.token, now=401))
        self.assertFalse(validate_confirmation(quote, user_id=42, token=quote.token, now=99))

    def test_balance_is_not_mutated_by_quote(self):
        quote = make_quote(user_id=42, engine="runway", feature="i2v",
                           provider_cost_usd="1", now=100)
        first = customer_summary(quote, "20")
        second = customer_summary(quote, "20")
        self.assertEqual(first, second)
        self.assertEqual(first["remaining_credits"], "5.0")

    def test_topup_units_are_not_legacy_ruble_credits(self):
        # Explicitly document the incompatibility; do not silently migrate wallets.
        self.assertEqual(credits_from_usd("1"), Decimal("10"))
        from neyrobot_prod.credit_store_v201 import catalog
        packs = catalog()
        self.assertTrue(packs)
        self.assertNotEqual(packs[0].credits, packs[0].rub)


if __name__ == "__main__":
    unittest.main()
