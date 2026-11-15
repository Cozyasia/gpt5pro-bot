import unittest
from neyronix_legacy_bridge import legacy_credit_quote

class LegacyBridgeTests(unittest.TestCase):
    def test_explicit_conversion_rate_required(self):
        for rate in (0, -1, "NaN", "Infinity", "bad"):
            with self.subTest(rate=rate):
                with self.assertRaises((ValueError, ArithmeticError)):
                    legacy_credit_quote("1", legacy_credits_per_usd=rate)
    def test_quote_is_rounded_up_and_units_explicit(self):
        result=legacy_credit_quote("1", legacy_credits_per_usd="100")
        self.assertEqual(result["retail_usd"], "1.5")
        self.assertEqual(result["price_credits"], "150")
        self.assertEqual(result["unit"], "legacy_credits")
    def test_fractional_provider_cost_does_not_undercharge(self):
        result=legacy_credit_quote("0.001", legacy_credits_per_usd="100")
        self.assertEqual(result["price_credits"], "1")
    def test_no_provider_cost_in_public_payload(self):
        result=legacy_credit_quote("2", legacy_credits_per_usd="100")
        self.assertNotIn("provider_cost_usd",result)
        self.assertNotIn("multiplier",result)
if __name__=="__main__":
    unittest.main()
