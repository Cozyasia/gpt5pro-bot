# -*- coding: utf-8 -*-
import unittest
from pathlib import Path

import celebrity_selfie_v144 as v144


class _Provider:
    @staticmethod
    def _gemini_payload(prompt, refs, *, aspect, image_size):
        return {
            "contents": [{"role": "user", "parts": [{"text": prompt}, *refs]}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "responseFormat": {"image": {"aspectRatio": aspect, "imageSize": image_size}},
            },
        }


class CelebritySelfieV144Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(v144.VERSION, "v144-scene-provider-schema-retry-2026-07-21")

    def test_invalid_or_auto_aspects_are_normalised(self):
        self.assertEqual(v144._normalise_aspect("auto"), "4:5")
        self.assertEqual(v144._normalise_aspect("-"), "4:5")
        self.assertEqual(v144._normalise_aspect("16x9"), "16:9")
        self.assertEqual(v144._normalise_aspect("nonsense"), "4:5")

    def test_gemini_has_three_compatible_schema_attempts(self):
        variants = v144._gemini_payload_variants(_Provider(), "prompt", "auto", "2K")
        self.assertEqual([name for name, _ in variants], [
            "response-format-aspect-size",
            "response-format-aspect",
            "response-modalities-only",
        ])
        full = variants[0][1]["generationConfig"]
        self.assertEqual(full["responseFormat"]["image"]["aspectRatio"], "4:5")
        self.assertEqual(full["responseFormat"]["image"]["imageSize"], "2K")
        self.assertNotIn("responseFormat", variants[-1][1]["generationConfig"])
        self.assertEqual(variants[-1][1]["generationConfig"]["responseModalities"], ["IMAGE"])

    def test_scene_prompts_force_one_right_person_and_empty_left(self):
        prompt = v144._scene_prompt("Красная площадь", "auto", 0, "neutral", rescue=True)
        self.assertIn("EXACTLY ONE adult man", prompt)
        self.assertIn("Place him on the RIGHT", prompt)
        self.assertIn("LEFT 42 percent completely free", prompt)
        self.assertIn("no guards, ceremony, crowd", prompt)
        self.assertIn("Output aspect ratio 4:5", prompt)

    def test_plate_problem_does_not_weaken_normal_v143_gate(self):
        original = v144._ORIGINAL_V143_PLATE_PROBLEM
        try:
            v144._ORIGINAL_V143_PLATE_PROBLEM = lambda raw, label: "scene plate must contain exactly one main foreground face; found 2"
            self.assertIn("found 2", v144._plate_problem(b"not-approved", "plate"))
        finally:
            v144._ORIGINAL_V143_PLATE_PROBLEM = original

    def test_source_declares_provider_safe_contract(self):
        source = Path("celebrity_selfie_v144.py").read_text(encoding="utf-8")
        self.assertIn("response-modalities-only", source)
        self.assertIn("CELEBRITY_V144_STRICT_RESCUE_ROUND", source)
        self.assertIn("CELEBRITY_V144_VISION_ZERO_FACE_RESCUE", source)
        self.assertIn("exactly_one_main_foreground_adult", source)
        self.assertIn("v144_plate_openai_rescue", source)
        self.assertIn("v144_plate_gemini_rescue", source)


if __name__ == "__main__":
    unittest.main()
