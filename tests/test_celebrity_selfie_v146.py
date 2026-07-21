# -*- coding: utf-8 -*-
import base64
import os
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

import celebrity_selfie_v146 as v146


def _jpeg(width=1200, height=1600, color=(90, 110, 130)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    out = BytesIO()
    image.save(out, "JPEG", quality=95)
    return out.getvalue()


class CelebritySelfieV146Tests(unittest.IsolatedAsyncioTestCase):
    def test_version(self):
        self.assertEqual(v146.VERSION, "v146-local-face-lock-2026-07-21")

    def test_multi_face_swap_is_blocked_by_default(self):
        with patch.dict(
            os.environ,
            {
                "CELEBRITY_V146_PIAPI_MODES": "face-swap,multi-face-swap",
                "CELEBRITY_V146_ALLOW_MULTI_FACE_SWAP": "0",
            },
            clear=False,
        ):
            self.assertEqual(v146._piapi_modes(), ["face-swap"])

    def test_target_face_region_enlarges_detected_right_face(self):
        target = _jpeg()
        face = {"x": 820, "y": 260, "w": 180, "h": 210, "area": 37800}
        with patch.object(v146.v142, "_face_boxes", return_value=[face]):
            region = v146._target_face_region(target)
        left, top, right, bottom = region["bbox"]
        self.assertEqual(region["detector"], "local-face-detector")
        self.assertLessEqual(left, face["x"])
        self.assertLessEqual(top, face["y"])
        self.assertGreaterEqual(right, face["x"] + face["w"])
        self.assertGreaterEqual(bottom, face["y"] + face["h"])
        self.assertEqual(region["provider_crop"].size, (1280, 1280))

    async def test_piapi_uses_local_single_face_crop_and_merges_full_plate(self):
        target = _jpeg(1200, 1600, (80, 90, 100))
        reference = _jpeg(900, 900, (160, 130, 100))
        face = {"x": 810, "y": 250, "w": 190, "h": 220, "area": 41800}
        swapped_crop = _jpeg(1280, 1280, (180, 120, 90))
        task = AsyncMock(return_value=swapped_crop)

        with patch.object(v146.v142, "_face_boxes", return_value=[face]), patch.object(
            v146.v139, "_face_crop", return_value=reference
        ), patch.object(v146.v139.pi_identity, "_piapi_task", task):
            output = await v146._piapi_face_swap_once(
                SimpleNamespace(), target, reference, "face-swap"
            )

        self.assertTrue(output)
        with Image.open(BytesIO(output)) as result:
            self.assertEqual(result.size, (1200, 1600))
        task_type, inputs = task.await_args.args[1], task.await_args.args[2]
        self.assertEqual(task_type, "face-swap")
        self.assertNotIn("swap_faces_index", inputs)
        self.assertNotIn("target_faces_index", inputs)
        for key in ("swap_image", "target_image"):
            self.assertTrue(base64.b64decode(inputs[key]))

    async def test_best_identity_qc_uses_best_reference_not_only_first(self):
        qc = AsyncMock(side_effect=[
            {"score": 28.0, "unknown": False, "reason": "weak angle"},
            {"score": 84.0, "unknown": False, "reason": "good match"},
        ])
        with patch.object(v146.v143, "_single_face_identity_score", qc):
            result = await v146._best_identity_score(
                SimpleNamespace(), _jpeg(), [_jpeg(color=(1, 2, 3)), _jpeg(color=(4, 5, 6))]
            )
        self.assertEqual(result["score"], 84.0)
        self.assertEqual(result["reference_index"], 2)

    def test_scene_prompt_requests_face_large_enough_for_locking(self):
        prompt = v146._scene_prompt("restaurant", "4:5", 0, "warm")
        self.assertIn("7 to 14 percent", prompt)
        self.assertIn("at least 220 pixels tall", prompt)

    def test_release_bootstrap_loads_v146_after_v145(self):
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v146 import install_early", source)
        self.assertGreater(
            source.index("from celebrity_selfie_v146"),
            source.index("from celebrity_selfie_v145"),
        )
        versioning = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v146-local-face-lock-2026-07-21"', versioning)
        self.assertIn("from celebrity_selfie_v146 import install as install_v146", versioning)
        self.assertIn("release_overlay={'v146' if release_overlay else 'load-error'}", versioning)

    def test_source_preserves_user_and_disables_multi_face_fallback(self):
        source = Path("celebrity_selfie_v146.py").read_text(encoding="utf-8")
        self.assertIn("user_face_generation=disabled", source)
        self.assertIn("piapi_multi_face_swap=blocked", source)
        self.assertIn('CELEBRITY_V143_LEGACY_FALLBACK"] = "0"', source)
        self.assertIn("local-face-crop", source)


if __name__ == "__main__":
    unittest.main()
