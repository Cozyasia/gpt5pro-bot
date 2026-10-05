# -*- coding: utf-8 -*-
"""Static isolation checks; behavioral tests live in test_openai_selfie_terminal."""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SelfieLaneIsolationTest(unittest.TestCase):
    def test_lane_remains_separate_from_frozen_v265(self):
        source = (ROOT / "neyrobot_prod/openai_selfie_exp_v1.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn('PREFIX = "oaiselfie:"', source)
        self.assertNotIn("dense68_engine_v265", source)
        self.assertNotIn("selfie_v265_single_owner", source)
        self.assertNotIn("cs201:", source)

    def test_existing_direct_edit_route_is_retained(self):
        source = (ROOT / "neyrobot_prod/openai_selfie_exp_v1.py").read_text(encoding="utf-8")
        self.assertIn("https://api.openai.com/v1/images/edits", source)
        self.assertIn('"image[]"', source)
        self.assertIn("OPENAI_API_KEY", source)

    def test_v265_reference_stays_installed_but_out_of_entertainment_menu(self):
        init = (ROOT / "neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        lane = (ROOT / "neyrobot_prod/openai_selfie_exp_v1.py").read_text(encoding="utf-8")
        self.assertIn('PRODUCTION_SELFIE_RUNTIME = "v265"', init)
        self.assertIn("openai_selfie_exp_v1", init)
        self.assertIn('callback_data=PREFIX + "open"', lane)
        self.assertIn('("fun:aiselfie",)', lane)
