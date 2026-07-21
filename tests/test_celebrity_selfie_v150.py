# -*- coding: utf-8 -*-
import base64
import os
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import celebrity_selfie_v150 as v150


def _png() -> bytes:
    image = Image.new("RGB", (64, 80), (70, 100, 130))
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


class CelebritySelfieV150Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(v150.VERSION, "v150-comet-scene-failover-2026-07-21")

    def test_provider_order_is_comet_first_without_placeholder(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CELEBRITY_V150_SCENE_PROVIDERS", None)
            self.assertEqual(v150._scene_provider_order(), ["comet", "flux", "gemini"])
            self.assertNotIn("local", v150._scene_provider_order())

    def test_provider_order_deduplicates_and_ignores_unknown(self):
        with patch.dict(os.environ, {"CELEBRITY_V150_SCENE_PROVIDERS": "comet,unknown,comet,gemini"}, clear=False):
            self.assertEqual(v150._scene_provider_order(), ["comet", "gemini"])

    def test_invalid_gemini_key_is_classified_as_auth(self):
        self.assertTrue(v150._looks_auth_error("HTTP 400: API key not valid. Please pass a valid API key."))
        self.assertTrue(v150._looks_auth_error("HTTP 401 unauthorized"))
        self.assertFalse(v150._looks_auth_error("HTTP 500 provider timeout"))

    def test_comet_payload_uses_configured_openai_compatible_endpoint_shape(self):
        with patch.dict(os.environ, {"COMET_IMAGE_GEN_MODEL": "gpt-image-1"}, clear=False):
            variants = v150._comet_payload_variants("empty restaurant", "4:5")
        self.assertGreaterEqual(len(variants), 3)
        for _, payload in variants:
            self.assertEqual(payload["model"], "gpt-image-1")
            self.assertEqual(payload["prompt"], "empty restaurant")
            self.assertEqual(payload["size"], "1024x1536")
            self.assertEqual(payload["n"], 1)

    def test_inline_comet_image_is_extracted(self):
        encoded = base64.b64encode(_png()).decode("ascii")
        raw = v150._inline_image({"data": [{"b64_json": encoded}]})
        self.assertIsNotNone(raw)
        with Image.open(BytesIO(raw)) as image:
            self.assertEqual(image.size, (64, 80))

    def test_url_comet_image_is_extracted(self):
        self.assertEqual(
            v150._image_url({"data": [{"url": "https://example.test/image.png"}]}),
            "https://example.test/image.png",
        )

    def test_install_overrides_background_builder_and_disables_placeholder(self):
        source = Path("celebrity_selfie_v150.py").read_text(encoding="utf-8")
        self.assertIn("v142._make_plate_candidates = _make_background_candidates", source)
        self.assertIn('os.environ["CELEBRITY_V147_LOCAL_BACKGROUND_FALLBACK"] = "0"', source)
        self.assertIn('"comet,flux,gemini"', source)

    def test_sitecustomize_loads_v150_last(self):
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v150 import install_early", source)
        self.assertGreater(source.index("from celebrity_selfie_v150"), source.index("from celebrity_selfie_v149"))

    def test_version_contract_points_to_v150(self):
        source = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v150-comet-scene-failover-2026-07-21"', source)
        self.assertIn("from celebrity_selfie_v150 import install as install_v150", source)
        self.assertIn("release_overlay={'v150' if release_overlay else 'load-error'}", source)


if __name__ == "__main__":
    unittest.main()
