import unittest
from neyronix_quotes import make_quote, validate_confirmation, customer_summary


class QuoteTests(unittest.TestCase):
    def test_quote_bound_to_user_and_token(self):
        q = make_quote(user_id=42, engine="runway", feature="i2v", provider_cost_usd="1", now=100)
        self.assertTrue(validate_confirmation(q, user_id=42, token=q.token, now=101))
        self.assertFalse(validate_confirmation(q, user_id=43, token=q.token, now=101))
        self.assertFalse(validate_confirmation(q, user_id=42, token="wrong", now=101))
        self.assertFalse(validate_confirmation(q, user_id=42, token=q.token, now=401))
        self.assertFalse(validate_confirmation(q, user_id=42, token=q.token, now=99))

    def test_customer_summary_is_private(self):
        q = make_quote(user_id=42, engine="runway", feature="i2v", provider_cost_usd="1", metadata={"provider_cost_usd": "1"}, now=100)
        summary = customer_summary(q, "20")
        self.assertEqual(summary["price_credits"], "15.0")
        self.assertEqual(summary["remaining_credits"], "5.0")
        self.assertTrue(summary["can_afford"])
        self.assertNotIn("provider_cost_usd", str(summary))
        self.assertNotIn("metadata", str(summary))

    def test_reject_zero_cost(self):
        with self.assertRaises(ValueError):
            make_quote(user_id=42, engine="runway", feature="i2v", provider_cost_usd="0")


if __name__ == "__main__":
    unittest.main()
