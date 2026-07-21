# -*- coding: utf-8 -*-
import base64
import os
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

import celebrity_selfie_v145 as v145


def _jpeg(width=900, height=1200) -> bytes:
    image = Image.new("RGB", (width, height), (90, 110, 130))
    out = BytesIO()
    image.save(out, "JPEG", quality=95)
    return out.getvalue()


class CelebritySelfieV145Tests(unittest.IsolatedAsyncioTestCase):
    def test_version(self):
        self.assertEqual(v145.VERSION, "v145-piapi-celebrity-lock-retry-2026-07-21")

    def test_provider_order_prefers_piapi(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CELEBRITY_V145_CELEBRITY_PROVIDERS", None)
            self.assertEqual(v145._provider_order(), ["piapi", "openai"])

    def test_single_face_request_uses_face_swap_without_indexes(self):
        task_type, inputs = v145._piapi_request("face-swap", b"source", b"target")
        self.assertEqual(task_type, "face-swap")
        self.assertNotIn("swap_faces_index", inputs)
        self.assertNotIn("target_faces_index", inputs)
        self.assertEqual(base64.b64decode(inputs["swap_image"]), b"source")
        self.assertEqual(base64.b64decode(inputs["target_image"]), b"target")

    def test_multi_face_compatibility_fallback_targets_face_zero(self):
        task_type, inputs = v145._piapi_request("multi-face-swap", b"source", b"target")
        self.assertEqual(task_type, "multi-face-swap")
        self.assertEqual(inputs["swap_faces_index"], "0")
        self.assertEqual(inputs["target_faces_index"], "0")

    def test_piapi_images_are_below_provider_limit(self):
        raw = _jpeg(2600, 2300)
        prepared = v145._piapi_ready_image(raw)
        with Image.open(BytesIO(prepared)) as image:
            self.assertLessEqual(max(image.size), 2000)
            self.assertLess(max(image.size), 2048)

    async def test_piapi_face_swap_first_uses_normalized_images(self):
        source = _jpeg(1500, 1500)
        target = _jpeg(2400, 2100)
        task = AsyncMock(return_value=_jpeg(1000, 1200))
        with patch.object(v145.v139, "_face_crop", return_value=source), patch.object(
            v145.v139.pi_identity, "_piapi_task", task
        ):
            output = await v145._piapi_face_swap_once(SimpleNamespace(), target, source, "face-swap")
        self.assertTrue(output)
        task_type, inputs = task.await_args.args[1], task.await_args.args[2]
        self.assertEqual(task_type, "face-swap")
        self.assertNotIn("target_faces_index", inputs)
        for key in ("swap_image", "target_image"):
            with Image.open(BytesIO(base64.b64decode(inputs[key]))) as image:
                self.assertLess(max(image.size), 2048)

    def test_source_declares_fail_closed_identity_contract(self):
        source = Path("celebrity_selfie_v145.py").read_text(encoding="utf-8")
        self.assertIn('"piapi,openai"', source)
        self.assertIn('"face-swap,multi-face-swap"', source)
        self.assertIn("CELEBRITY_V145_PIAPI_MAX_SIDE", source)
        self.assertIn("CELEBRITY_V145_PIAPI_REFERENCE_ATTEMPTS", source)
        self.assertIn("strict celebrity score", source)
        self.assertIn("CELEBRITY_V143_LEGACY_FALLBACK", source)

    def test_sitecustomize_loads_v145_after_version_contract(self):
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v145 import install_early", source)
        self.assertGreater(
            source.index("from celebrity_selfie_v145"),
            source.index("from neyrobot_prod.versioning"),
        )


if __name__ == "__main__":
    unittest.main()
