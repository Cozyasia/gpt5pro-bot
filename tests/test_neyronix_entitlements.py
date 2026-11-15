import unittest
from neyronix_entitlements import is_included


class EntitlementTests(unittest.TestCase):
    def test_start_economy_chat(self):
        self.assertTrue(is_included(tier="start", feature="economy_chat", used=0, spent_usd="0", estimated_cost_usd="0.005"))
        self.assertFalse(is_included(tier="start", feature="economy_chat", used=100, spent_usd="0", estimated_cost_usd="0.001"))

    def test_per_request_cost_cap(self):
        self.assertFalse(is_included(tier="pro", feature="economy_chat", used=0, spent_usd="0", estimated_cost_usd="1"))

    def test_monthly_cost_cap(self):
        self.assertFalse(is_included(tier="pro", feature="economy_chat", used=2, spent_usd="2.499", estimated_cost_usd="0.005"))

    def test_unknown_and_invalid(self):
        self.assertFalse(is_included(tier="free", feature="economy_chat", used=0, spent_usd=0, estimated_cost_usd="0.001"))
        self.assertFalse(is_included(tier="start", feature="economy_chat", used=0, spent_usd=0, estimated_cost_usd="NaN"))


if __name__ == "__main__":
    unittest.main()
