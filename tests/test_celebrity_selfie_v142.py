# -*- coding: utf-8 -*-
import os
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image, ImageDraw

import celebrity_selfie_v140_hotfix as v140_hotfix
import celebrity_selfie_v142 as v142
import celebrity_selfie_v142_compat as compat


def _png_with_subject(width=320, height=420):
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((90, 35, 230, 180), fill=(190, 130, 100, 255))
    draw.rounded_rectangle((55, 155, 265, 410), radius=60, fill=(35, 80, 150, 255))
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _scene(width=800, height=1000):
    image = Image.new("RGB", (width, height), (45, 55, 70))
    draw = ImageDraw.Draw(image)
    draw.rectangle((410, 150, 760, 920), fill=(85, 70, 60))
    out = BytesIO()
    image.save(out, "JPEG", quality=95)
    return out.getvalue()


class CelebritySelfieV142Tests(unittest.IsolatedAsyncioTestCase):
    def test_scene_prompt_reserves_left_side_and_generates_one_right_person(self):
        prompt = v142._scene_prompt("ресторан", "4:5", 0, "neutral light")
        self.assertIn("Exactly ONE anonymous adult", prompt)
        self.assertIn("RIGHT half", prompt)
        self.assertIn("LEFT foreground must remain intentionally empty", prompt)
        self.assertIn("no person, face, body", prompt)

    def test_result_keyboard_removes_user_face_regeneration_action(self):
        markup = v142._result_kb(True)
        texts = [button.text for row in markup.inline_keyboard for button in row]
        joined = " | ".join(texts)
        self.assertIn("Улучшить только лицо знаменитости", joined)
        self.assertIn("Пересобрать только знаменитость", joined)
        self.assertNotIn("Усилить моё лицо", joined)
        self.assertNotIn("Усилить мое лицо", joined)

    async def test_cutout_provider_falls_back_from_photoroom_to_rembg(self):
        debug = {"stages": [], "errors": [], "cutouts": []}
        valid = _png_with_subject()
        with patch.object(v142, "_photoroom_cutout", AsyncMock(side_effect=RuntimeError("temporary"))), \
             patch.object(v142, "_local_rembg_cutout", AsyncMock(return_value=valid)), \
             patch.object(v142, "_largest_face", return_value={"x": 100, "y": 45, "w": 120, "h": 130}):
            result = await v142._prepare_user_cutout(SimpleNamespace(), b"raw", debug, "user1")
        self.assertEqual(result["provider"], "rembg")
        self.assertGreater(result["image"].width, 0)
        self.assertEqual(debug["cutouts"][0]["pixel_policy"], "source_pixels_only")

    def test_local_composite_keeps_source_subject_visible_without_face_generation(self):
        old = {name: os.environ.get(name) for name in (
            "CELEBRITY_V142_MIN_EXPOSURE_MATCH",
            "CELEBRITY_V142_MAX_EXPOSURE_MATCH",
            "CELEBRITY_V142_COLOR_MATCH",
            "CELEBRITY_V142_EDGE_FEATHER_PX",
            "CELEBRITY_V142_SHADOW_OPACITY",
        )}
        os.environ.update({
            "CELEBRITY_V142_MIN_EXPOSURE_MATCH": "1",
            "CELEBRITY_V142_MAX_EXPOSURE_MATCH": "1",
            "CELEBRITY_V142_COLOR_MATCH": "1",
            "CELEBRITY_V142_EDGE_FEATHER_PX": "0",
            "CELEBRITY_V142_SHADOW_OPACITY": "0",
        })
        try:
            cutout = Image.new("RGBA", (260, 420), (0, 0, 0, 0))
            draw = ImageDraw.Draw(cutout)
            draw.ellipse((70, 30, 190, 155), fill=(220, 35, 25, 255))
            draw.rectangle((45, 145, 215, 415), fill=(25, 105, 210, 255))
            info = {
                "image": cutout,
                "face": {"x": 70, "y": 30, "w": 120, "h": 125},
                "provider": "test",
                "label": "user1",
            }
            raw, metadata = v142._composite_user(_scene(), info, 0)
            result = Image.open(BytesIO(raw)).convert("RGB")
            x, y = metadata["position"]
            w, h = metadata["size"]
            pixel = result.getpixel((max(0, x + w // 2), max(0, y + h // 5)))
            self.assertGreater(pixel[0], pixel[1] + 60)
            self.assertGreater(pixel[0], pixel[2] + 60)
            self.assertTrue(metadata["face_geometry_lock"])
            self.assertEqual(metadata["user_pixel_policy"], "source_pixels_preserved_no_generation")
        finally:
            for name, value in old.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_install_patches_only_live_engine_and_disables_generative_cleanup(self):
        v142.install()
        compat.install()
        self.assertIs(v142.v139.selfie.engine._generate, v142._generate)
        self.assertIs(v142.v139.selfie.engine._run_multi_reference_generation, v142._run_compat)
        self.assertIs(v142.v139.selfie.engine._result_kb, compat._combined_result_kb)
        self.assertEqual(v142.v139.VERSION, v140_hotfix.V139_COMPONENT_VERSION)
        self.assertIs(v142.v139._run_two_stage_generation, v142.v140._run_v140_generation)
        self.assertIs(v142.v141._result_kb, compat._combined_result_kb)
        self.assertEqual(os.environ["CELEBRITY_V141_OPENAI_QUALITY_CLEANUP"], "0")
        self.assertEqual(os.environ["CELEBRITY_V142_CUTOUT_PROVIDERS"], "photoroom,rembg")

    async def test_user_face_button_is_intercepted_without_regeneration(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        query = SimpleNamespace(data="cs141:user", answer=AsyncMock())
        update = SimpleNamespace(callback_query=query, effective_message=message)
        with self.assertRaises(Exception) as raised:
            await v142._callback(update, SimpleNamespace())
        # ApplicationHandlerStop is intentionally raised after the explanatory message.
        self.assertTrue(message.reply_text.await_count == 1)
        text = message.reply_text.await_args.args[0]
        self.assertIn("сохранено из исходного селфи", text)
        self.assertNotEqual(type(raised.exception), RuntimeError)


if __name__ == "__main__":
    unittest.main()
