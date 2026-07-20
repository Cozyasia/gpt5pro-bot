# -*- coding: utf-8 -*-
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import celebrity_selfie_v136 as v136


def constants(fn):
    values = []
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        for value in code.co_consts:
            if hasattr(value, "co_consts"):
                stack.append(value)
            else:
                values.append(str(value))
    return "\n".join(values)


class CelebritySelfieV136Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(v136.VERSION, "v136-celebrity-selfie-multiprovider-targeted-identity-2026-07-20")

    def test_payload_loader_has_integrity_check(self):
        source = Path("celebrity_selfie_v136.py").read_text(encoding="utf-8")
        self.assertIn("_SOURCE_SHA256", source)
        self.assertIn("checksum mismatch", source)
        self.assertTrue(Path("celebrity_selfie_v136_payload/part_01.txt").exists())

    def test_dynamic_aspect_profiles(self):
        with patch.dict(os.environ, {"CELEBRITY_GEMINI_ASPECT": "auto"}, clear=False):
            self.assertEqual(v136._aspect_for_scene("селфи на съемочной площадке"), "3:2")
            self.assertEqual(v136._aspect_for_scene("крупный портрет 1:1"), "1:1")
            self.assertEqual(v136._aspect_for_scene("обычный ресторан"), "4:5")

    def test_best_of_n_and_independent_identity_scores(self):
        text = constants(v136._run_v136_generation) + constants(v136._identity_detail_qc)
        self.assertIn("CELEBRITY_GEMINI_PRO_CANDIDATES", text)
        self.assertIn("CELEBRITY_GEMINI_FLASH_CANDIDATES", text)
        self.assertIn("user_similarity", text)
        self.assertIn("celebrity_similarity", text)
        self.assertIn("identity_min", text)

    def test_high_fidelity_and_targeted_repair_contract(self):
        text = constants(v136._openai_edit) + constants(v136._openai_targeted_repair)
        self.assertIn("input_fidelity", text)
        self.assertIn("high", text)
        self.assertIn("Edit the FIRST image only", text)
        self.assertIn("Do not alter the", text)
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.setdefault("CELEBRITY_NATIVE_PIAPI_REPAIR", "0")', package)

    def test_optional_second_user_angle_is_installed(self):
        text = constants(v136._accept_user_photo_v136) + constants(v136._image_v136)
        self.assertIn("user_photo_2_path", text)
        self.assertIn("await_user_photo_2", text)
        self.assertIs(v136.wizard._accept_user_photo, v136._accept_user_photo_v136)

    def test_flux_is_optional_and_key_gated(self):
        self.assertEqual(v136._bfl_key(), os.environ.get("BFL_API_KEY", ""))
        self.assertIn("flux-2-pro", constants(v136._flux_edit))

    def test_v136_is_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v136 import install_builder_hook", source)
        self.assertIn("_install_celebrity_selfie_v136()", source)


if __name__ == "__main__":
    unittest.main()
