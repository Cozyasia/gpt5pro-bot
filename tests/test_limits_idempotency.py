# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from neyrobot_prod import limits


class DummyRuntime:
    pass


class HeavyGenerationLimitIdempotencyTests(unittest.TestCase):
    def test_overlay_above_existing_limiter_is_not_wrapped_again(self):
        runtime = DummyRuntime()

        async def base(*args, **kwargs):
            return True

        runtime._try_pay_then_do = base
        self.assertTrue(limits.patch_runtime(runtime))
        limited = runtime._try_pay_then_do
        self.assertTrue(getattr(limited, "_prod_v119_limited", False))

        async def v160_overlay(*args, **kwargs):
            return await limited(*args, **kwargs)

        v160_overlay._v160_original = limited  # type: ignore[attr-defined]
        v160_overlay._v160_selfie_failure_dedupe = True  # type: ignore[attr-defined]
        runtime._try_pay_then_do = v160_overlay

        self.assertTrue(limits._wrapper_chain_has_limit(runtime._try_pay_then_do))
        current = runtime._try_pay_then_do
        for _ in range(120):
            self.assertTrue(limits.patch_runtime(runtime))
            self.assertIs(runtime._try_pay_then_do, current)
        self.assertTrue(getattr(current, "_prod_v119_limited", False))


if __name__ == "__main__":
    unittest.main()
