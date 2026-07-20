# -*- coding: utf-8 -*-
import base64
import os
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

import celebrity_selfie_v135 as v135


def image_bytes(size=(928, 1152), color=(90, 120, 145)):
    image = Image.new("RGB", size, color)
    out = BytesIO()
    image.save(out, "JPEG", quality=92)
    return out.getvalue()


class CelebritySelfieV135Tests(unittest.IsolatedAsyncioTestCase):
    def test_version_and_quality_first_models(self):
        mod = SimpleNamespace(
            GEMINI_IMAGE_MODEL="gemini-3-pro-image-preview",
            GEMINI_IMAGE_FALLBACK_MODEL="gemini-3.1-flash-image-preview",
        )
        with patch.dict(os.environ, {"CELEBRITY_GEMINI_MODELS": ""}, clear=False):
            models = v135._gemini_models(mod)
        self.assertEqual(models[0], "gemini-3-pro-image")
        self.assertIn("gemini-3.1-flash-image", models)
        self.assertNotIn("gemini-2.5-flash-image", models)
        self.assertEqual(v135.VERSION, "v135-celebrity-selfie-gemini3-native-identity-2026-07-20")

    def test_prompt_requests_two_exact_identities(self):
        prompt = v135._native_prompt("Роман Абрамович", "Красная площадь", 0)
        self.assertIn("exact USER REFERENCE identity", prompt)
        self.assertIn("exact PUBLIC FIGURE REFERENCE identity", prompt)
        self.assertIn("Do not blend identities", prompt)
        self.assertIn("Exactly TWO adults", prompt)
        self.assertIn("No third foreground person", prompt)

    def test_refinement_preserves_the_accepted_scene(self):
        prompt = v135._native_prompt("выбранная персона", "ресторан", 0, refinement=True)
        self.assertIn("Edit the FIRST supplied image only", prompt)
        self.assertIn("Preserve its exact scene", prompt)
        self.assertIn("Replace/refine only the two facial identities", prompt)

    def test_payload_uses_gemini3_image_contract(self):
        refs = [{"text": "ref"}, v135._image_part(image_bytes())]
        payload = v135._gemini_payload("prompt", refs, aspect="4:5", image_size="2K")
        config = payload["generationConfig"]
        self.assertEqual(config["responseModalities"], ["IMAGE"])
        self.assertEqual(config["responseFormat"]["image"]["aspectRatio"], "4:5")
        self.assertEqual(config["responseFormat"]["image"]["imageSize"], "2K")
        self.assertEqual(payload["contents"][0]["parts"][1]["text"], "ref")

    def test_extracts_camel_and_snake_inline_data(self):
        first = image_bytes(color=(10, 20, 30))
        second = image_bytes(color=(40, 50, 60))
        payload = {"candidates": [{"content": {"parts": [
            {"inlineData": {"data": base64.b64encode(first).decode()}},
            {"inline_data": {"data": base64.b64encode(second).decode()}},
        ]}}]}
        self.assertEqual(v135._gemini_images(payload), [first, second])

    async def test_high_identity_candidate_skips_face_swap(self):
        raw = image_bytes()
        score = {"total": 88.0, "identity": 86.0, "scene": 70.0, "label": "native", "reason": "ok", "output": raw}
        mod = SimpleNamespace(
            GEMINI_IMAGE_API_KEY="key",
            GEMINI_IMAGE_MODEL="gemini-3-pro-image",
            GEMINI_IMAGE_FALLBACK_MODEL="gemini-3.1-flash-image",
        )
        with (
            patch.object(v135.impl, "_best_reference", AsyncMock(return_value=raw)),
            patch.object(v135, "_reference_parts", return_value=[]),
            patch.object(v135, "_gemini_generate", AsyncMock(return_value=raw)),
            patch.object(v135, "_score_candidate", AsyncMock(return_value=score)),
            patch.object(v135.base, "_identity_lock", AsyncMock()) as identity_lock,
            patch.dict(os.environ, {"CELEBRITY_NATIVE_EARLY_ACCEPT_SCORE": "74"}, clear=False),
        ):
            output = await v135._run_native_generation(mod, raw, [raw], "персона", "ресторан")
        self.assertEqual(output, raw)
        identity_lock.assert_not_awaited()

    def test_runtime_bootstrap_uses_only_v135_builder(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v135 import install_builder_hook", source)
        self.assertNotIn("from celebrity_selfie_v134 import install_builder_hook", source)

    def test_source_contract_keeps_face_swap_selective(self):
        source = Path("celebrity_selfie_v135.py").read_text(encoding="utf-8")
        self.assertIn("gemini-3-pro-image", source)
        self.assertIn("gemini-3.1-flash-image", source)
        self.assertIn("CELEBRITY_NATIVE_PIAPI_REPAIR", source)
        self.assertIn("return False", source)
        self.assertIn("failed_job_status=false", source)


if __name__ == "__main__":
    unittest.main()
