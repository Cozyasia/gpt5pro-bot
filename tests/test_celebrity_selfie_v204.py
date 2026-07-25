# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import os
import tempfile
import types
import unittest

from neyrobot_prod import celebrity_selfie_v204 as v204


class CelebritySelfieV204Tests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(os.environ)
        for key in ("COMET_API_KEY", "COMETAPI_KEY", "GEMINI_IMAGE_API_KEY", "CELEBRITY_SELFIE_DATA_DIR"):
            os.environ.pop(key, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)

    def test_comet_is_preferred_without_google_key(self):
        os.environ["COMET_API_KEY"] = "sk-test"
        self.assertEqual(v204._provider(), "comet")

    def test_payload_contains_exactly_four_reference_images(self):
        images = [(letter, "image/jpeg") for letter in ("a", "b", "c", "d")]
        body = v204._payload(images, "prompt", camel_case=True, compatibility=False, aspect="4:5", size="2K")
        parts = body["contents"][0]["parts"]
        self.assertEqual(sum("inlineData" in part for part in parts), 4)
        self.assertEqual(body["generationConfig"]["imageConfig"]["aspectRatio"], "4:5")

    def test_last_non_thought_image_is_returned(self):
        draft = base64.b64encode(b"d" * 2048).decode()
        final = base64.b64encode(b"f" * 4096).decode()
        data = {
            "candidates": [{
                "content": {"parts": [
                    {"inlineData": {"mimeType": "image/png", "data": draft}, "thought": True},
                    {"inlineData": {"mimeType": "image/png", "data": final}},
                ]}
            }]
        }
        self.assertEqual(v204._extract_final_image(data), b"f" * 4096)

    def test_source_tree_storage_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["CELEBRITY_SELFIE_DATA_DIR"] = "/opt/render/project/src/celebrity_selfie"
            mod = types.SimpleNamespace(DB_PATH=os.path.join(temp_dir, "subs.db"))
            path = v204._storage_root(mod)
            self.assertFalse(str(path).startswith("/opt/render/project/src"))


if __name__ == "__main__":
    unittest.main()
