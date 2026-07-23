# -*- coding: utf-8 -*-
import base64
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "celebrity_library" / "fixed_refs" / "ru_roman_abramovich"
ASSETS = (
    "01_front_current.jpg.b64",
    "02_three_quarter_current.jpg.b64",
    "03_front_warm_current.jpg.b64",
)
BASE64_RUN = re.compile(r"[A-Za-z0-9+/=]{32,}")


def decode_asset(path: Path) -> bytes:
    runs = BASE64_RUN.findall(path.read_text(encoding="ascii"))
    candidates = []
    for value in ("".join(runs), *runs):
        if not value:
            continue
        variants = [value]
        pad_at = value.find("=")
        if pad_at >= 0:
            end = pad_at + 1
            while end < len(value) and value[end] == "=":
                end += 1
            variants.insert(0, value[:end])
        for candidate in variants:
            if candidate not in candidates:
                candidates.append(candidate)
    for candidate in candidates:
        payload = candidate
        if "=" not in payload and len(payload) % 4:
            payload += "=" * (-len(payload) % 4)
        try:
            raw = base64.b64decode(payload, validate=True)
        except Exception:
            continue
        if len(raw) >= 4_000 and raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9"):
            return raw
    raise AssertionError(f"No complete JPEG payload in {path.name}")


class CelebritySelfieV158Tests(unittest.TestCase):
    def test_owner_reference_pack_contains_three_valid_jpegs(self):
        decoded = []
        for filename in ASSETS:
            path = PACK / filename
            self.assertTrue(path.is_file(), filename)
            raw = decode_asset(path)
            self.assertGreater(len(raw), 4_000, filename)
            self.assertTrue(raw.startswith(b"\xff\xd8\xff"), filename)
            self.assertTrue(raw.endswith(b"\xff\xd9"), filename)
            decoded.append(raw)
        self.assertEqual(3, len({item for item in decoded}))

    def test_runtime_decoder_uses_real_b64_files_not_missing_part_directories(self):
        source = (ROOT / "celebrity_selfie_v158.py").read_text(encoding="utf-8")
        hotfix = (ROOT / "neyrobot_prod" / "hotfix_v159.py").read_text(encoding="utf-8")
        self.assertIn("_PACK_FILES", source)
        self.assertIn("01_front_current.jpg.b64", source)
        self.assertIn("_decode_asset_text", source)
        self.assertIn("len(raw or b\"\") >= 4_000", hotfix)
        self.assertLess(hotfix.index("release._valid_jpeg = _valid_owner_jpeg"), hotfix.index("release.install()"))
        self.assertNotIn('source.glob("part_*.txt")', source)

    def test_v158_contract_pins_roman_and_removes_false_callback_error(self):
        source = (ROOT / "celebrity_selfie_v158.py").read_text(encoding="utf-8")
        self.assertIn('ROMAN_ID = "ru_roman_abramovich"', source)
        self.assertIn('identity_reference_policy"] = "repository-fixed-pack-only"', source)
        self.assertIn("_v122_callback_without_false_error", source)
        self.assertIn("ApplicationHandlerStop", source)
        self.assertIn('"fixed_reference_count": len(paths)', source)
        self.assertIn('"state": "await_scene"', source)

    def test_v159_bootstrap_activates_v158_as_renderer_library(self):
        site = (ROOT / "sitecustomize.py").read_text(encoding="utf-8")
        versioning = (ROOT / "neyrobot_prod" / "versioning.py").read_text(encoding="utf-8")
        defaults = (ROOT / "neyrobot_prod" / "__init__.py").read_text(encoding="utf-8")
        hotfix = (ROOT / "neyrobot_prod" / "hotfix_v159.py").read_text(encoding="utf-8")
        for source in (site, versioning, defaults, hotfix):
            self.assertIn("v159", source)
        self.assertIn("neyrobot_prod.hotfix_v159", site)
        self.assertIn("import celebrity_selfie_v158 as release", hotfix)
        self.assertIn("release.install_builder_hook()", hotfix)
        self.assertNotIn("from celebrity_selfie_v157 import install", versioning)


if __name__ == "__main__":
    unittest.main()
