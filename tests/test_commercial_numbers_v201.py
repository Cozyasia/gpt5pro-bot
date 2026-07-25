# -*- coding: utf-8 -*-
from __future__ import annotations

import types
import unittest

from neyrobot_prod import commercial_numbers_v201 as commercial
from neyrobot_prod import credit_store_v201 as store


class CommercialNumbersV201Tests(unittest.TestCase):
    def test_stale_subscription_and_package_values_are_overwritten(self):
        mod = types.SimpleNamespace(
            BOT_TOKEN="token",
            SUBSCRIPTION_CREDITS={"start": 20, "pro": 120, "ultimate": 350},
            SUBS_TIERS={
                "start": {"credits": 20, "features": ["🪙 20 кредитов каждый месяц"]},
                "pro": {"credits": 120, "features": ["🪙 120 кредитов каждый месяц"]},
                "ultimate": {"credits": 350, "features": ["🪙 350 кредитов каждый месяц"]},
            },
        )
        self.assertTrue(commercial.patch_runtime(mod))
        self.assertEqual(mod.SUBSCRIPTION_CREDITS, commercial.CANONICAL_INCLUDED)
        self.assertEqual(mod.SUBS_TIERS["ultimate"]["credits"], 3500)
        self.assertIn("🪙 3500 кредитов каждый месяц", mod.SUBS_TIERS["ultimate"]["features"])
        self.assertEqual(mod.CREDIT_PACKAGES_RUB, {1000: 990, 3000: 2490, 7000: 4990})
        self.assertEqual([(p.credits, p.rub) for p in store.catalog()], [(1000, 990), (3000, 2490), (7000, 4990)])


if __name__ == "__main__":
    unittest.main()
