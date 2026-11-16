"""Guard against activating incompatible NEYRONIX credit scales.

This is a static safety test: it does not touch wallets, live config or money.
"""
import ast
import pathlib
import unittest
from decimal import Decimal
from neyronix_pricing import CREDITS_PER_USD, credits_from_usd, retail_credits

ROOT = pathlib.Path(__file__).resolve().parents[1]

class CreditScaleSafetyTests(unittest.TestCase):
    def test_package_scale_and_pricing_scale(self):
        self.assertEqual(CREDITS_PER_USD, Decimal("100"))
        self.assertEqual(credits_from_usd("10"), Decimal("1000"))
        self.assertEqual(retail_credits("0.70"), Decimal("140"))

    def test_new_wallet_scale_must_not_be_enabled_with_old_divisor(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        for name in ("_credits_to_usd", "_usd_to_credits", "_retail_usd"):
            self.assertIn(name, functions)
        # Until migration is deliberately implemented, retain the double opt-in.
        self.assertIn("_NEYRONIX_WALLET_MIGRATION_VERIFIED", source)
        self.assertIn("NEYRONIX_USD_CREDITS_ENABLED = _NEYRONIX_NEW_CREDITS_REQUESTED and _NEYRONIX_WALLET_MIGRATION_VERIFIED", source)
        conversion = ast.get_source_segment(source, functions["_credits_to_usd"])
        self.assertIn("CREDITS_PER_USD", conversion)
        reverse = ast.get_source_segment(source, functions["_usd_to_credits"])
        self.assertIn("CREDITS_PER_USD", reverse)
        retail = ast.get_source_segment(source, functions["_retail_usd"])
        self.assertIn("_credits_to_usd(_retail_credits(provider_cost_usd))", retail)
        # Migration remains gated; new-mode conversion now matches canonical pricing.
        self.assertEqual(Decimal("100"), CREDITS_PER_USD)

if __name__ == "__main__":
    unittest.main()
