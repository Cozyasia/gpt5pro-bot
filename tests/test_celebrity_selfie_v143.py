# -*- coding: utf-8 -*-
import json
import os
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image, ImageDraw

import celebrity_selfie_v143 as v143


def _png(image: Image.Image) -> bytes:
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _valid_person_cutout(width=320, height=420) -> bytes:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((95, 30, 225, 170), fill=(205, 145, 110, 255))
    draw.rounded_rectangle((65, 145, 255, 419), radius=70, fill=(40, 90, 160, 255))
    return _png(image)


def _rectangular_leak(width=320, height=420) -> bytes:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, width - 8, height - 8), fill=(60, 70, 80, 255))
    return _png(image)


def _jpeg(width=800, height=1000) -> bytes:
    image = Image.new("RGB", (width, height), (55, 65, 80))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, height // 2), fill=(145, 155, 170))
    draw.rectangle((width // 2, height // 2, width, height), fill=(80, 95, 115))
    out = BytesIO()
    image.save(out, "JPEG", quality=95)
    return out.getvalue()


class CelebritySelfieV143Tests(unittest.IsolatedAsyncioTestCase):
    def test_version(self):
        self.assertEqual(v143.VERSION, "v143-strict-composite-quality-gate-2026-07-21")

    def test_valid_person_shaped_alpha_passes(self):
        image = v143._validate_cutout(_valid_person_cutout())
        metrics = v143._alpha_metrics(image)
        self.assertGreaterEqual(metrics["transparent_corners"], 2)
        self.assertLess(metrics["bbox_opaque"], 0.84)

    def test_rectangular_source_background_is_rejected(self):
        with self.assertRaises(RuntimeError) as raised:
            v143._validate_cutout(_rectangular_leak())
        self.assertTrue(
            "rectangular" in str(raised.exception).casefold()
            or "background" in str(raised.exception).casefold()
            or "coverage" in str(raised.exception).casefold()
        )

    def test_plate_requires_exactly_one_main_face_on_right(self):
        right = {"x": 500, "y": 180, "w": 150, "h": 170}
        with patch.object(v143, "_main_faces", return_value=[]):
            self.assertIn("exactly one", v143._plate_problem(_jpeg(), "test"))
        with patch.object(v143, "_main_faces", return_value=[right, {"x": 150, "y": 180, "w": 150, "h": 170}]):
            self.assertIn("exactly one", v143._plate_problem(_jpeg(), "test"))
        with patch.object(v143, "_main_faces", return_value=[right]):
            self.assertEqual(v143._plate_problem(_jpeg(), "test"), "")

    def test_final_layout_requires_exactly_two_main_faces(self):
        with patch.object(v143, "_main_faces", return_value=[]):
            self.assertIn("exactly two", v143._final_layout_problem(_jpeg()))
        faces = [
            {"x": 100, "y": 160, "w": 150, "h": 170},
            {"x": 510, "y": 160, "w": 150, "h": 170},
        ]
        with patch.object(v143, "_main_faces", return_value=faces):
            self.assertEqual(v143._final_layout_problem(_jpeg()), "")

    async def test_visual_qc_rejects_rectangular_patch(self):
        payload = {
            "exactly_two_main_people": True,
            "user_identity_matches_source": True,
            "no_rectangular_patch": False,
            "no_source_background_leak": False,
            "coherent_scale": True,
            "coherent_lighting": True,
            "clean_cutout_edges": False,
            "companion_face_visible": True,
            "no_extra_prominent_people": True,
            "scene_matches_request": True,
            "naturalness": 82,
            "reason": "rectangular source background remains visible",
        }
        mod = SimpleNamespace(ask_openai_vision=AsyncMock(return_value=json.dumps(payload)))
        result = await v143._visual_composite_qc(mod, _jpeg(), _jpeg(), "премьера")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["checks"]["no_rectangular_patch"])

    def test_install_disables_legacy_fallback_and_uses_primary_selfie(self):
        old = os.environ.get("CELEBRITY_V143_LEGACY_FALLBACK")
        try:
            os.environ.pop("CELEBRITY_V143_LEGACY_FALLBACK", None)
            v143.install()
            self.assertEqual(os.environ["CELEBRITY_V143_LEGACY_FALLBACK"], "0")
            self.assertEqual(os.environ["CELEBRITY_V142_USER_CUTOUTS"], "1")
            self.assertIs(v143.v139.selfie.engine._run_multi_reference_generation, v143._run_compat)
            self.assertIs(v143.v142._run_v142_generation, v143._run_v143_generation)
        finally:
            if old is None:
                os.environ.pop("CELEBRITY_V143_LEGACY_FALLBACK", None)
            else:
                os.environ["CELEBRITY_V143_LEGACY_FALLBACK"] = old

    def test_source_declares_fail_closed_contract(self):
        source = Path("celebrity_selfie_v143.py").read_text(encoding="utf-8")
        self.assertIn("primary_selfie_only", source)
        self.assertIn("no_rectangular_patch", source)
        self.assertIn("no_source_background_leak", source)
        self.assertIn("exactly two main foreground faces", source)
        self.assertIn('CELEBRITY_V143_LEGACY_FALLBACK", "0"', source)


if __name__ == "__main__":
    unittest.main()
