# -*- coding: utf-8 -*-
import importlib.util
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

MODULE_PATH = Path("celebrity_selfie_v122.py")
SPEC = importlib.util.spec_from_file_location("celebrity_selfie_v122", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class CelebritySelfieV122Tests(unittest.TestCase):
    def test_catalog_has_exactly_20_ru_and_10_us(self):
        entries = mod.CELEBRITIES
        self.assertEqual(30, len(entries))
        self.assertEqual(20, sum(x.get("country") == "ru" for x in entries))
        self.assertEqual(10, sum(x.get("country") == "us" for x in entries))
        self.assertEqual(len(entries), len({x.get("id") for x in entries}))
        self.assertNotIn("Наталья Орейро", {x.get("display_name") for x in entries})

    def test_catalog_search_handles_russian_and_english_aliases(self):
        ru = mod.search_catalog("Роман Абрамович", limit=3)
        en = mod.search_catalog("Roman Abramovich", limit=3)
        self.assertTrue(ru)
        self.assertTrue(en)
        self.assertEqual("ru_roman_abramovich", ru[0]["id"])
        self.assertEqual("ru_roman_abramovich", en[0]["id"])

    def test_license_filter_is_conservative(self):
        for allowed in ("CC BY 4.0", "CC BY-SA 3.0", "CC0 1.0", "Public domain"):
            self.assertTrue(mod.license_allowed(allowed), allowed)
        for blocked in ("All rights reserved", "Fair use", "CC BY-NC 4.0", "CC BY-ND 3.0", ""):
            self.assertFalse(mod.license_allowed(blocked), blocked)

    def test_identity_prompt_keeps_people_separate_and_disclaims_endorsement(self):
        prompt = mod.build_identity_prompt(
            "Роман Абрамович",
            "продажа антиквариата в павильоне на Красной площади",
            4,
            refinement=True,
        )
        self.assertIn("exactly two separate people", prompt)
        self.assertIn("Do not average, merge, blend or swap the two identities", prompt)
        self.assertIn("user's identity reference", prompt)
        self.assertIn("not documentary evidence, endorsement, news or political support", prompt)
        self.assertIn("previous draft", prompt)
        self.assertIn("do not imply that the public figure endorses", prompt)

    def test_materialized_layout_is_alphabetical_and_metadata_backed(self):
        with TemporaryDirectory() as tmp:
            library = mod.CelebrityLibrary(tmp)
            library.materialize_layout()
            roman = mod.BY_ID["ru_roman_abramovich"]
            folder = library.entry_dir(roman)
            self.assertEqual("А", folder.parent.name)
            self.assertTrue((folder / "meta.json").exists())
            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual("pending", meta["reference_status"])
            self.assertEqual("ru_roman_abramovich", meta["catalog_entry"]["id"])

    def test_default_library_root_is_persistent_render_disk(self):
        old = os.environ.pop("CELEBRITY_LIBRARY_ROOT", None)
        try:
            self.assertEqual("/data/celebrity_library", str(mod.CelebrityLibrary().root))
        finally:
            if old is not None:
                os.environ["CELEBRITY_LIBRARY_ROOT"] = old


if __name__ == "__main__":
    unittest.main()
