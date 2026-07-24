# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
import base64
from io import BytesIO
from pathlib import Path
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
HOTFIX = (ROOT / "neyrobot_prod" / "hotfix_v161.py").read_text(encoding="utf-8")
SITE = (ROOT / "sitecustomize.py").read_text(encoding="utf-8")
VERSIONING = (ROOT / "neyrobot_prod" / "versioning.py").read_text(encoding="utf-8")
DEFAULTS = (ROOT / "neyrobot_prod" / "__init__.py").read_text(encoding="utf-8")


class HotfixV161Tests(unittest.TestCase):
    def test_v161_files_are_valid_python(self):
        ast.parse(HOTFIX)
        ast.parse(SITE)
        ast.parse(VERSIONING)
        ast.parse(DEFAULTS)

    def test_v161_is_the_explicit_release_owner(self):
        expected = "v161-roman-hybrid-identity-2026-07-24"
        self.assertIn(expected, HOTFIX)
        self.assertIn(expected, VERSIONING)
        self.assertIn(expected, DEFAULTS)
        self.assertIn("neyrobot_prod.hotfix_v161", SITE)
        self.assertIn("from neyrobot_prod.hotfix_v161 import install_early", VERSIONING)
        self.assertIn("from neyrobot_prod.hotfix_v161 import _cmd_version", VERSIONING)
        self.assertIn("neyrobot-version-contract-v161", VERSIONING)

    def test_roman_uses_proven_identity_lock_and_user_pixel_preservation(self):
        for token in (
            "v145._run_v145_generation",
            "v145._celebrity_variants",
            "CELEBRITY_V145_CELEBRITY_PROVIDERS",
            "piapi,openai",
            "v143._plate_problem",
            "user_pixel_preserved",
            '"user_face_regenerated": False',
            "one-person-scene+piapi-celebrity-lock+original-user-pixel-composite",
            "_V156_ORIGINAL_RUN",
            "v161-v160-fallback",
        ):
            self.assertIn(token, HOTFIX)

    def test_pipeline_swap_is_serialised_and_always_restored(self):
        self.assertIn("_PIPELINE_GATE = asyncio.Lock()", HOTFIX)
        self.assertIn("async with _PIPELINE_GATE", HOTFIX)
        self.assertIn("finally:", HOTFIX)
        self.assertIn("v142._make_plate_candidates = old_plates", HOTFIX)
        self.assertIn("v143._celebrity_variants = old_celebrities", HOTFIX)

    def test_full_owner_reference_one_is_complete_and_high_resolution(self):
        directory = ROOT / "celebrity_library" / "fixed_refs" / "ru_roman_abramovich" / "full" / "01"
        encoded = "".join(path.read_text(encoding="ascii") for path in sorted(directory.glob("part_*.txt")))
        raw = base64.b64decode(encoded, validate=True)
        self.assertGreater(len(raw), 20_000)
        self.assertTrue(raw.startswith(b"\xff\xd8\xff"))
        self.assertTrue(raw.endswith(b"\xff\xd9"))
        with Image.open(BytesIO(raw)) as image:
            self.assertGreaterEqual(min(image.size), 400)
            self.assertEqual((512, 435), image.size)

    def test_failure_message_no_longer_claims_sequential_fixation(self):
        self.assertIn("Все созданные варианты были отклонены контролем качества", HOTFIX)
        self.assertNotIn("после последовательной фиксации лиц результат потерял целостность", HOTFIX)

    def test_payments_medicine_and_general_v160_fallback_are_retained(self):
        self.assertIn("from . import hotfix_v160 as previous", HOTFIX)
        self.assertIn("previous.install_early()", HOTFIX)
        self.assertIn("previous._patch_runtime(mod)", HOTFIX)
        self.assertIn("credit_catalog=", HOTFIX)
        self.assertIn("medical_text_route=", HOTFIX)
        self.assertIn("medical_image_route=", HOTFIX)


if __name__ == "__main__":
    unittest.main()
