# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOTFIX_PATH = ROOT / "neyrobot_prod" / "hotfix_v160.py"
HOTFIX = HOTFIX_PATH.read_text(encoding="utf-8")
HOTFIX161 = (ROOT / "neyrobot_prod" / "hotfix_v161.py").read_text(encoding="utf-8")
SITE = (ROOT / "sitecustomize.py").read_text(encoding="utf-8")
VERSIONING = (ROOT / "neyrobot_prod" / "versioning.py").read_text(encoding="utf-8")
DEFAULTS = (ROOT / "neyrobot_prod" / "__init__.py").read_text(encoding="utf-8")
SECRET_LOADER = (ROOT / "secret_loader.py").read_text(encoding="utf-8")


class HotfixV160Tests(unittest.TestCase):
    def test_hotfixes_are_valid_python(self):
        ast.parse(HOTFIX)
        ast.parse(HOTFIX161)
        ast.parse(VERSIONING)
        ast.parse(DEFAULTS)

    def test_v160_remains_the_general_fallback_under_v161(self):
        v160 = "v160-selfie-delivery-rescue-2026-07-24"
        v161 = "v161-roman-hybrid-identity-2026-07-24"
        self.assertIn(v160, HOTFIX)
        self.assertIn(v161, HOTFIX161)
        self.assertIn(v161, VERSIONING)
        self.assertIn(v161, DEFAULTS)
        self.assertIn("neyrobot_prod.hotfix_v161", SITE)
        self.assertIn("from . import hotfix_v160 as previous", HOTFIX161)
        self.assertIn("from neyrobot_prod.versioning import install_early", SECRET_LOADER)
        self.assertIn("from neyrobot_prod.hotfix_v161 import install_early", VERSIONING)
        self.assertIn("from neyrobot_prod.hotfix_v161 import _cmd_version", VERSIONING)
        self.assertNotIn("from neyrobot_prod.hotfix_v160 import install_early", VERSIONING)
        self.assertIn("neyrobot-version-contract-v161", VERSIONING)
        self.assertIn("topup_v159", SITE)

    def test_four_candidate_practical_strict_gates_remain_in_v160(self):
        previous_import = HOTFIX.index("from . import hotfix_v159 as previous")
        for token in (
            'CELEBRITY_V156_CANDIDATES"] = "4"',
            'CELEBRITY_V158_MIN_CELEBRITY_SIMILARITY"] = "70"',
            'CELEBRITY_V156_MIN_QUALITY"] = "62"',
        ):
            self.assertIn(token, HOTFIX)
            self.assertLess(HOTFIX.index(token), previous_import)

    def test_near_threshold_rescue_never_bypasses_hard_structure(self):
        for token in (
            "_HARD_CHECKS",
            "exactly_two_main_adults",
            "real_living_people_not_wax",
            "no_plaque_poster_or_museum_display",
            "one_seamless_scene",
            "scene_match",
            "any(checks.get(key) is not True",
            "user_score >= 60",
            "celebrity_score >= 68",
            "face_quality >= 60",
            "overall_quality >= 60",
            "total >= 68",
        ):
            self.assertIn(token, HOTFIX)

    def test_selfie_failure_card_is_not_followed_by_generic_wallet_error(self):
        self.assertIn('if "celebrity_selfie" in remember_kind', HOTFIX)
        self.assertIn('kwargs["silent_failure"] = True', HOTFIX)
        self.assertIn("celebrity_selfie_duplicate_failure=blocked", HOTFIX)

    def test_v159_payments_and_medical_are_preserved(self):
        self.assertIn("previous.install_early()", HOTFIX)
        self.assertIn("previous._patch_runtime(mod)", HOTFIX)
        self.assertIn("credit_catalog=", HOTFIX)
        self.assertIn("medical_text_route=", HOTFIX)
        self.assertIn("medical_image_route=", HOTFIX)


if __name__ == "__main__":
    unittest.main()
