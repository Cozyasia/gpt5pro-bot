# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import types
import unittest


class V249StartupBootstrapTests(unittest.TestCase):
    def test_sitecustomize_is_loaded_at_python_startup(self) -> None:
        self.assertIn(
            "sitecustomize",
            sys.modules,
            "sitecustomize.py was not auto-imported; production selfie overlays would remain inactive",
        )

    def test_final_selfie_builder_owner_is_armed(self) -> None:
        from telegram.ext import ApplicationBuilder

        self.assertTrue(
            getattr(ApplicationBuilder, "_neyrobot_v246_final_builder_lock", False),
            "V246/V247/V248 final builder owner was not installed before main handler registration",
        )

    def test_priority_generation_owner_is_bound_before_legacy_callback(self) -> None:
        from telegram.ext import ApplicationBuilder

        app = ApplicationBuilder().token("123456:TESTTOKEN").build()
        handlers = list(app.handlers.get(-1000001, []))
        callbacks = [getattr(h, "callback", None) for h in handlers]
        names = {getattr(cb, "__name__", "") for cb in callbacks if cb is not None}
        self.assertIn(
            "_generation_owner",
            names,
            "The V245/V246 priority owner is missing, so legacy V236 callbacks could win again",
        )


class V249ProviderReportingTests(unittest.IsolatedAsyncioTestCase):
    async def _run_case(self, marker: str, expected: str) -> None:
        from neyrobot_prod import selfie_v248_faceswap_v4_quality as v249

        old_base = v249._BASE_TRUE_FACE_TRANSFER
        old_log = v249._log
        runtime = types.SimpleNamespace(AI_SELFIE_LAST_FACESWAP_PROVIDER="")

        async def fake_base(rt, stage1, source, source_photo_no):
            rt.AI_SELFIE_LAST_FACESWAP_PROVIDER = marker
            return b"final-image", "segmind_faceswap_v2_isolated"

        try:
            v249._BASE_TRUE_FACE_TRANSFER = fake_base
            v249._log = lambda *args, **kwargs: None
            final, provider = await v249._true_face_transfer_with_actual_provider(
                runtime, b"stage1", b"source", 3
            )
            self.assertEqual(final, b"final-image")
            self.assertEqual(provider, expected)
        finally:
            v249._BASE_TRUE_FACE_TRANSFER = old_base
            v249._log = old_log

    async def test_v4_success_is_not_mislabeled_as_v2(self) -> None:
        await self._run_case(
            "segmind_faceswap_v4_quality_face",
            "segmind_faceswap_v4_quality_face_isolated",
        )

    async def test_v2_fallback_is_reported_as_fallback(self) -> None:
        await self._run_case(
            "segmind_faceswap_v2_fallback",
            "segmind_faceswap_v2_fallback_isolated",
        )


if __name__ == "__main__":
    unittest.main()
