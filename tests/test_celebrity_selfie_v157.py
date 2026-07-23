# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class CelebritySelfieV157Tests(unittest.TestCase):
    def test_v157_is_valid_python(self):
        ast.parse(_source("celebrity_selfie_v157.py"))

    def test_exclusive_menu_owner_is_restored(self):
        source = _source("celebrity_selfie_v157.py")
        self.assertIn("import celebrity_selfie_v124 as flow", source)
        self.assertIn("flow.install_builder_hook()", source)
        self.assertIn("group\n    # -20000", source.replace("at group", "group"))
        self.assertIn("generic_nano_banana_free_prompt=blocked_during_wizard", source)

    def test_catalog_selection_is_authoritative(self):
        source = _source("celebrity_selfie_v157.py")
        self.assertIn("_lock_selected_person", source)
        self.assertIn('session["selected_celebrity_id"]', source)
        self.assertIn('session["celebrity_name"] = name', source)
        self.assertIn('session["celebrity_selection_locked"] = True', source)

    def test_user_and_scene_renderer_remain_v156(self):
        source = _source("celebrity_selfie_v157.py")
        self.assertIn("_BASE_GENERATE = base._generate", source)
        self.assertIn("user_transfer=v156-unchanged", source)
        self.assertIn("scene_generation=v156-unchanged", source)
        self.assertNotIn("def _comet_gemini_render", source)
        self.assertNotIn("def _normalise_output", source)

    def test_selected_public_identity_dominates_ranking(self):
        source = _source("celebrity_selfie_v157.py")
        self.assertIn("celebrity_score * 0.55", source)
        self.assertIn("CELEBRITY_V157_MIN_CELEBRITY_SIMILARITY", source)
        self.assertIn('"78"', source)
        self.assertIn("exact same individual shown in all PUBLIC FIGURE REFERENCES", source)
        self.assertIn("not merely a person of similar age or style", source)

    def test_startup_and_version_contract_point_to_v157(self):
        expected = "v157-menu-selected-identity-lock-2026-07-23"
        self.assertIn(expected, _source("celebrity_selfie_v157.py"))
        self.assertIn(expected, _source("neyrobot_prod/versioning.py"))
        self.assertIn(expected, _source("neyrobot_prod/__init__.py"))
        site = _source("sitecustomize.py")
        self.assertIn("celebrity_selfie_v157", site)
        self.assertNotIn("install_celebrity_selfie_v156", site)


if __name__ == "__main__":
    unittest.main()
