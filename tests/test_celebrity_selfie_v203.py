# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import types
import unittest


class SelfieV203Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "neyrobot_prod.celebrity_selfie_v203",
            "neyrobot_prod/celebrity_selfie_v203.py",
        )
        cls.module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(cls.module)

    def test_rest_payload_uses_official_camel_case_and_four_images(self):
        package = types.ModuleType("neyrobot_prod")
        base = types.ModuleType("neyrobot_prod.celebrity_selfie")
        base._aspect_ratio = lambda: "4:5"
        base._image_size = lambda: "2K"
        old_package = sys.modules.get("neyrobot_prod")
        old_base = sys.modules.get("neyrobot_prod.celebrity_selfie")
        sys.modules["neyrobot_prod"] = package
        sys.modules["neyrobot_prod.celebrity_selfie"] = base
        try:
            body = self.module.payload(
                "prompt",
                [(value, "image/jpeg") for value in ("a", "b", "c", "d")],
                compatibility=False,
            )
        finally:
            if old_package is not None:
                sys.modules["neyrobot_prod"] = old_package
            else:
                sys.modules.pop("neyrobot_prod", None)
            if old_base is not None:
                sys.modules["neyrobot_prod.celebrity_selfie"] = old_base
            else:
                sys.modules.pop("neyrobot_prod.celebrity_selfie", None)

        parts = body["contents"][0]["parts"]
        self.assertEqual(sum("inlineData" in part for part in parts), 4)
        self.assertFalse(any("inline_data" in part for part in parts))
        self.assertEqual(
            body["generationConfig"]["responseFormat"]["image"]["aspectRatio"],
            "4:5",
        )

    def test_prompt_forbids_generic_character_substitution(self):
        text = self.module.identity_prompt("Роман Абрамович")
        self.assertIn("Роман Абрамович", text)
        self.assertIn("Do not invent a generic substitute", text)
        self.assertIn("References 2, 3 and 4", text)


if __name__ == "__main__":
    unittest.main()
