# -*- coding: utf-8 -*-
import base64
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "celebrity_library" / "fixed_refs" / "ru_roman_abramovich"
ASSETS = (
    "01_front_current.jpg.b64",
    "02_three_quarter_current.jpg.b64",
    "03_front_warm_current.jpg.b64",
)


class CelebritySelfieV158Tests(unittest.TestCase):
    def test_owner_reference_pack_contains_three_valid_jpegs(self):
        decoded = []
        for filename in ASSETS:
            path = PACK / filename
            self.assertTrue(path.is_file(), filename)
            raw = base64.b64decode("".join(path.read_text(encoding="ascii").split()), validate=True)
            self.assertGreater(len(raw), 25_000, filename)
            self.assertTrue(raw.startswith(b"\xff\xd8\xff"), filename)
            self.assertTrue(raw.endswith(b"\xff\xd9"), filename)
            decoded.append(raw)
        self.assertEqual(3, len({item for item in decoded}))

    def test_v158_contract_pins_roman_and_removes_false_callback_error(self):
        source = (ROOT / "celebrity_selfie_v158.py").read_text(encoding="utf-8")
        self.assertIn('ROMAN_ID = "ru_roman_abramovich"', source)
        self.assertIn('identity_reference_policy"] = "repository-fixed-pack-only"', source)
        self.assertIn("_v122_callback_without_false_error", source)
        self.assertIn("ApplicationHandlerStop", source)
        self.assertIn('"fixed_reference_count": len(paths)', source)
        self.assertIn('"state": "await_scene"', source)

    def test_production_bootstrap_activates_only_v158(self):
        site = (ROOT / "sitecustomize.py").read_text(encoding="utf-8")
        versioning = (ROOT / "neyrobot_prod" / "versioning.py").read_text(encoding="utf-8")
        defaults = (ROOT / "neyrobot_prod" / "__init__.py").read_text(encoding="utf-8")
        for source in (site, versioning, defaults):
            self.assertIn("v158", source)
        self.assertIn("from celebrity_selfie_v158", site)
        self.assertIn("from celebrity_selfie_v158", versioning)
        self.assertNotIn("from celebrity_selfie_v157 import install", versioning)


if __name__ == "__main__":
    unittest.main()
