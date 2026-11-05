import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from neyrobot_prod.studio_quote_store import StudioQuoteStore


class StudioQuoteStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "studio.sqlite3"
        self.store = StudioQuoteStore(self.path)
        self.plan = {"duration_s": 10, "scenes": [{"index": 1, "action": "walk"}]}

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, token="abc"):
        self.store.create(token, 123, 456, self.plan, 42, now=1000)

    def test_restart_preserves_exact_plan_and_price(self):
        self.make()
        result = StudioQuoteStore(self.path).decide("abc", 123, 456, True, now=1100)
        self.assertEqual(result, {"plan": self.plan, "price_credits": 42})

    def test_duplicate_confirm_does_not_reclaim(self):
        self.make()
        self.assertIsNotNone(self.store.decide("abc", 123, 456, True, now=1001))
        self.assertIsNone(self.store.decide("abc", 123, 456, True, now=1002))

    def test_wrong_identity_does_not_consume(self):
        self.make()
        self.assertIsNone(self.store.decide("abc", 999, 456, True, now=1001))
        self.assertIsNone(self.store.decide("abc", 123, 999, True, now=1001))
        self.assertIsNotNone(self.store.decide("abc", 123, 456, True, now=1001))

    def test_cancel_prevents_approval(self):
        self.make()
        self.assertIsNone(self.store.decide("abc", 123, 456, False, now=1001))
        self.assertIsNone(self.store.decide("abc", 123, 456, True, now=1002))

    def test_expiry_prevents_approval(self):
        self.make()
        self.assertIsNone(self.store.decide("abc", 123, 456, True, now=1600))

    def test_parallel_claims_only_one_wins(self):
        self.make()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: StudioQuoteStore(self.path).decide("abc", 123, 456, True, now=1001),
                range(16),
            ))
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_terminal_state_only_once(self):
        self.make()
        self.store.decide("abc", 123, 456, True, now=1001)
        self.assertTrue(self.store.mark("abc", "needs_review", now=1002))
        self.assertFalse(self.store.mark("abc", "completed", now=1003))


if __name__ == "__main__":
    unittest.main()
