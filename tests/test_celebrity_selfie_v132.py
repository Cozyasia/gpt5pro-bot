# -*- coding: utf-8 -*-
import asyncio
import base64
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import time
import unittest

from PIL import Image, ImageDraw

import celebrity_selfie_v132 as v132


def image_bytes(size=(800, 1000), left=(90, 110, 130), right=(150, 120, 95)):
    image = Image.new("RGB", size, left)
    draw = ImageDraw.Draw(image)
    for x in range(size[0]):
        t = x / max(1, size[0] - 1)
        color = tuple(int(left[i] * (1 - t) + right[i] * t) for i in range(3))
        draw.line((x, 0, x, size[1]), fill=color)
    draw.ellipse((size[0] * 0.25, size[1] * 0.16, size[0] * 0.49, size[1] * 0.39), fill=(210, 170, 140))
    draw.ellipse((size[0] * 0.56, size[1] * 0.17, size[0] * 0.80, size[1] * 0.40), fill=(200, 155, 125))
    out = BytesIO()
    image.save(out, "JPEG", quality=94)
    return out.getvalue()


def split_bytes():
    image = Image.new("RGB", (1600, 800), (25, 25, 25))
    left = Image.open(BytesIO(image_bytes((800, 800), (20, 40, 70), (80, 120, 160)))).convert("RGB")
    right = Image.open(BytesIO(image_bytes((800, 800), (230, 220, 180), (110, 80, 45)))).convert("RGB")
    image.paste(left, (0, 0))
    image.paste(right, (800, 0))
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


class _Message:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kwargs):
        self.sent.append((text, reply_markup))


class _Client:
    async def get(self, *args, **kwargs):
        raise AssertionError("download must not be called for base64 output")


class CelebritySelfieV132Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("celebrity_selfie_v132.py").read_text(encoding="utf-8")

    def test_historical_version_remains_documented(self):
        self.assertIn(
            'VERSION = "v132-celebrity-selfie-validated-final-output-2026-07-19"',
            self.source,
        )

    def test_piapi_parser_reads_only_explicit_output(self):
        expected = image_bytes()
        wrong = split_bytes()
        payload = {
            "data": {
                "status": "completed",
                "input": {"target_image": base64.b64encode(wrong).decode("ascii")},
                "output": {"image_base64": base64.b64encode(expected).decode("ascii")},
            }
        }
        result = asyncio.run(v132._extract_piapi_output(payload, _Client()))
        self.assertEqual(result, expected)

    def test_piapi_parser_never_falls_back_to_input_payload(self):
        payload = {
            "data": {
                "status": "completed",
                "input": {"target_image": base64.b64encode(split_bytes()).decode("ascii")},
                "output": None,
            }
        }
        result = asyncio.run(v132._extract_piapi_output(payload, _Client()))
        self.assertIsNone(result)

    def test_split_screen_is_rejected(self):
        problem = v132._image_problem(split_bytes(), stage="test")
        self.assertTrue(problem)
        self.assertTrue("соотношение" in problem or "split-screen" in problem or "склей" in problem)

    def test_normal_portrait_frame_is_accepted_by_local_shape_gate(self):
        problem = v132._image_problem(image_bytes(), stage="test")
        self.assertEqual(problem, "")

    def test_source_pair_is_face_focused_and_ordered(self):
        pair = v132._source_pair(image_bytes(), image_bytes(left=(160, 90, 70), right=(80, 60, 50)))
        with Image.open(BytesIO(pair)) as image:
            self.assertEqual(image.size, (1792, 896))

    def test_historical_scene_prompt_forbids_reference_sheet(self):
        self.assertIn("Create ONE seamless", self.source)
        self.assertIn("not a collage", self.source)
        self.assertIn("vertical divider", self.source)
        self.assertIn("Scene: {scene}", self.source)

    def test_duplicate_generation_click_is_blocked_before_second_job(self):
        message = _Message()
        update = SimpleNamespace(effective_message=message)
        context = SimpleNamespace(user_data={})
        session = v132.engine._session(context)
        session["owner"] = v132.VERSION
        session["state"] = "generating"
        session["generation_started_monotonic"] = time.monotonic()
        asyncio.run(v132._generate(update, context, refinement=False))
        self.assertEqual(len(message.sent), 1)
        self.assertIn("уже выполняется", message.sent[0][0])

    def test_historical_pipeline_never_returns_draft_after_identity_failure(self):
        self.assertIn("technical reference", self.source)
        self.assertIn("never publishes a draft/composite", self.source)
        self.assertIn("Ни один результат не прошёл финальную проверку", self.source)
        self.assertIn("технический черновик не отправлен", self.source)


if __name__ == "__main__":
    unittest.main()
