# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import base64
import os
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from neyrobot_prod import celebrity_selfie


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, encoded: str) -> None:
        self.encoded = encoded

    def json(self) -> dict:
        return {
            "candidates": [{
                "content": {
                    "parts": [{
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": self.encoded,
                        }
                    }]
                }
            }]
        }


class FakeClient:
    calls: list[tuple[str, dict]] = []
    encoded = ""

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url: str, **kwargs):
        self.__class__.calls.append((url, kwargs))
        return FakeResponse(self.__class__.encoded)


class CelebritySelfieTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeClient.calls = []
        raw = b"\x89PNG\r\n\x1a\n" + (b"x" * 256)
        self.raw = raw
        FakeClient.encoded = base64.b64encode(raw).decode("ascii")

    def test_direct_gemini_uses_configured_model_aspect_and_size(self) -> None:
        mod = types.SimpleNamespace(
            _prepare_reference_image_for_gemini=lambda value, max_side: (
                base64.b64encode(value).decode("ascii"),
                "image/jpeg",
            ),
            _ai_selfie_final_prompt=lambda user_prompt, preset_prompt: "BASE PROMPT",
        )
        env = {
            "GEMINI_IMAGE_API_KEY": "test-key",
            "GEMINI_IMAGE_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
            "GEMINI_IMAGE_MODEL": "gemini-3-pro-image",
            "GEMINI_IMAGE_FALLBACK_MODEL": "gemini-3.1-flash-image",
            "AI_SELFIE_DEFAULT_ASPECT": "4:5",
            "AI_SELFIE_IMAGE_SIZE": "2K",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(celebrity_selfie.httpx, "AsyncClient", FakeClient):
            result = asyncio.run(
                celebrity_selfie.generate_direct(
                    mod,
                    b"reference-photo" * 20,
                    "selfie with a famous actor",
                )
            )

        self.assertEqual(result, self.raw)
        self.assertEqual(len(FakeClient.calls), 1)
        url, request = FakeClient.calls[0]
        self.assertTrue(url.endswith("/models/gemini-3-pro-image:generateContent"))
        self.assertEqual(request["headers"]["x-goog-api-key"], "test-key")
        image_config = request["json"]["generationConfig"]["responseFormat"]["image"]
        self.assertEqual(image_config["aspectRatio"], "4:5")
        self.assertEqual(image_config["imageSize"], "2K")
        prompt = request["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("two separate recognizable people", prompt)
        self.assertIn("do not merge", prompt)

    def test_runtime_patch_changes_only_selfie_executor(self) -> None:
        async def original(*args, **kwargs):
            return True

        billing_owner = object()
        mod = types.SimpleNamespace(
            _run_ai_selfie_image=original,
            _start_ai_selfie=billing_owner,
        )
        self.assertTrue(celebrity_selfie.patch_runtime(mod))
        self.assertIsNot(mod._run_ai_selfie_image, original)
        self.assertIs(mod._start_ai_selfie, billing_owner)
        self.assertEqual(mod.AI_SELFIE_RUNTIME_VERSION, celebrity_selfie.VERSION)
        self.assertTrue(getattr(mod._run_ai_selfie_image, "_celebrity_selfie_direct_gemini", False))

    def test_sitecustomize_activates_isolated_selfie_runtime(self) -> None:
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("install_celebrity_selfie()", source)


if __name__ == "__main__":
    unittest.main()
