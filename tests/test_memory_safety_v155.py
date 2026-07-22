# -*- coding: utf-8 -*-
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

import celebrity_selfie_v139 as v139
import memory_safety_v155 as guard


class MemorySafetyV155Tests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        guard._GENERATION_GATE = None

    def test_local_rembg_requires_explicit_three_part_opt_in(self):
        with patch.dict(
            os.environ,
            {
                "BG_DISABLE_LOCAL_REMBG": "1",
                "LOCAL_REMBG_ENABLED": "1",
                "CELEBRITY_V142_LOCAL_REMBG_FALLBACK": "1",
            },
            clear=False,
        ):
            self.assertFalse(guard._local_rembg_allowed())

        with patch.dict(
            os.environ,
            {
                "BG_DISABLE_LOCAL_REMBG": "0",
                "LOCAL_REMBG_ENABLED": "1",
                "CELEBRITY_V142_LOCAL_REMBG_FALLBACK": "1",
            },
            clear=False,
        ):
            self.assertTrue(guard._local_rembg_allowed())

    async def test_disabled_local_rembg_fails_before_importing_onnx(self):
        with patch.dict(
            os.environ,
            {
                "BG_DISABLE_LOCAL_REMBG": "1",
                "LOCAL_REMBG_ENABLED": "0",
                "CELEBRITY_V142_LOCAL_REMBG_FALLBACK": "0",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "isolated media worker"):
                await guard._local_rembg_cutout(b"image")

    async def test_soft_limit_rejects_work_before_render_hard_kill(self):
        original = AsyncMock()
        with patch.object(guard, "_ORIGINAL_RUN_V154", original), patch.object(
            guard, "_rss_mb", return_value=1600.0
        ), patch.dict(os.environ, {"MEMORY_SOFT_LIMIT_MB": "1500"}, clear=False):
            with self.assertRaises(v139.PipelineError):
                await guard._run_v154_generation(None, b"photo", [], "name", "scene")
        original.assert_not_awaited()

    async def test_heavy_pipeline_is_serialized_by_default(self):
        active = 0
        peak = 0

        async def fake_run(*args, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return b"ok", {}

        guard._GENERATION_GATE = None
        with patch.object(guard, "_ORIGINAL_RUN_V154", side_effect=fake_run), patch.object(
            guard, "_rss_mb", return_value=100.0
        ), patch.dict(
            os.environ,
            {"MEMORY_SOFT_LIMIT_MB": "0", "CELEBRITY_V154_MAX_CONCURRENCY": "1"},
            clear=False,
        ):
            await asyncio.gather(
                guard._run_v154_generation(None, b"a", [], "one", "scene"),
                guard._run_v154_generation(None, b"b", [], "two", "scene"),
            )
        self.assertEqual(peak, 1)

    def test_rss_probe_is_safe(self):
        self.assertGreaterEqual(guard._rss_mb(), 0.0)


if __name__ == "__main__":
    unittest.main()
