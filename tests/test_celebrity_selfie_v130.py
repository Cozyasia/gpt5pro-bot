# -*- coding: utf-8 -*-
import asyncio
from io import BytesIO
import os
from pathlib import Path
import unittest

from PIL import Image, ImageDraw

import celebrity_selfie_v130_runtime as runtime
import celebrity_selfie_v130 as v130


def image_bytes(size=(900, 1100), *, detail=True):
    image = Image.new("RGB", size, (135, 115, 105))
    draw = ImageDraw.Draw(image)
    if detail:
        for x in range(0, size[0], 20):
            draw.line((x, 0, size[0] - x // 2, size[1]), fill=(40 + x % 180, 80, 150), width=4)
        draw.ellipse((260, 180, 640, 650), fill=(205, 165, 135), outline=(25, 25, 25), width=8)
        draw.ellipse((350, 330, 390, 370), fill=(0, 0, 0))
        draw.ellipse((510, 330, 550, 370), fill=(0, 0, 0))
    out = BytesIO()
    image.save(out, "JPEG", quality=95)
    return out.getvalue()


class CelebritySelfieV130Tests(unittest.TestCase):
    def test_historical_version_and_catalog_contract(self):
        source = Path("celebrity_selfie_v130.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v130-celebrity-selfie-identity-lock-2026-07-19"', source)
        self.assertEqual(len(v130.RU_IDS), 20)
        self.assertEqual(len(v130.US_IDS), 10)
        self.assertEqual(len(v130.engine.CATALOG.get("celebrities", [])), 30)

    def test_catalog_sources_are_exactly_20_and_10(self):
        ru = [line for line in Path("celebrity_library/catalog_ru_v1.tsv").read_text(encoding="utf-8").splitlines() if line.strip()]
        us = [line for line in Path("celebrity_library/catalog_us_v1.tsv").read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(ru), 20)
        self.assertEqual(len(us), 10)
        self.assertTrue(any(line.startswith("ru_roman_abramovich\t") for line in ru))
        self.assertTrue(any(line.startswith("us_keanu_reeves\t") for line in us))

    def test_quality_metrics_accept_detailed_portrait_and_reject_small_image(self):
        metrics = v130._quality_metrics(image_bytes())
        self.assertEqual(v130._quality_problem(metrics), "")
        small = v130._quality_metrics(image_bytes((240, 240)))
        self.assertIn("малень", v130._quality_problem(small))

    def test_identity_source_pair_has_user_left_and_celebrity_right_panels(self):
        raw = v130._source_pair(image_bytes(), image_bytes(detail=False))
        with Image.open(BytesIO(raw)) as image:
            self.assertEqual(image.size, (1800, 900))

    def test_raw_draft_is_blocked_when_identity_key_is_missing(self):
        old = os.environ.pop("PIAPI_API_KEY", None)
        try:
            with self.assertRaises(RuntimeError) as raised:
                asyncio.run(v130._run_quality_generation(
                    object(), image_bytes(), [image_bytes()], "Test Person", "test scene",
                    previous_result=image_bytes(),
                ))
            self.assertIn("Плохой черновик не отправлен", str(raised.exception))
        finally:
            if old is not None:
                os.environ["PIAPI_API_KEY"] = old

    def test_refinement_uses_previous_scene_without_regenerating_draft(self):
        calls = {"draft": 0, "lock": 0}
        original_draft = v130._ORIGINAL_DRAFT_GENERATOR
        original_lock = v130._identity_lock

        async def forbidden_draft(*args, **kwargs):
            calls["draft"] += 1
            raise AssertionError("draft generator must not run during refinement")

        async def fake_lock(mod, user, ref, target):
            calls["lock"] += 1
            return target

        v130._ORIGINAL_DRAFT_GENERATOR = forbidden_draft
        v130._identity_lock = fake_lock
        try:
            result = asyncio.run(v130._run_quality_generation(
                object(), image_bytes(), [image_bytes()], "Test Person", "same scene",
                previous_result=image_bytes(),
            ))
            self.assertTrue(result)
            self.assertEqual(calls, {"draft": 0, "lock": 1})
        finally:
            v130._ORIGINAL_DRAFT_GENERATOR = original_draft
            v130._identity_lock = original_lock

    def test_piapi_multi_face_contract(self):
        captured = {}
        original_task = v130._piapi_task

        async def fake_task(mod, task_type, inputs):
            captured["task_type"] = task_type
            captured["inputs"] = inputs
            return image_bytes()

        v130._piapi_task = fake_task
        original_face_count = v130._face_count

        async def two_faces(raw):
            return 2

        v130._face_count = two_faces
        try:
            asyncio.run(v130._identity_lock(object(), image_bytes(), image_bytes(), image_bytes()))
        finally:
            v130._piapi_task = original_task
            v130._face_count = original_face_count
        self.assertEqual(captured["task_type"], "multi-face-swap")
        self.assertEqual(captured["inputs"]["swap_faces_index"], "0,1")
        self.assertEqual(captured["inputs"]["target_faces_index"], "0,1")
        self.assertGreater(len(captured["inputs"]["swap_image"]), 1000)

    def test_v130_runtime_is_historical_and_v131_is_registered(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("from celebrity_selfie_v130_runtime import install_builder_hook", source)
        self.assertIn("from celebrity_selfie_v131 import install_builder_hook", source)
        self.assertNotIn("from celebrity_selfie_v129 import install_builder_hook", source)


if __name__ == "__main__":
    unittest.main()
