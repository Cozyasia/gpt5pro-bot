# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from celebrity_selfie_mode import CatalogStore, CelebritySelfieConfig, VERSION

ROOT = Path(__file__).resolve().parents[1]


class CleanCelebritySelfieTests(unittest.TestCase):
    def _config(self, data_dir: str) -> CelebritySelfieConfig:
        return CelebritySelfieConfig(
            project_root=str(ROOT),
            data_dir=data_dir,
            seed_dir=str(ROOT / "assets" / "celebrities_seed"),
            admin_ids={1},
            reference_min=3,
            reference_max=6,
            min_user_similarity=90,
            min_character_similarity=90,
        )

    def test_clean_version_and_single_direct_owner(self):
        self.assertIn("v200-celebrity-selfie-clean-rewrite", VERSION)
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        site = (ROOT / "sitecustomize.py").read_text(encoding="utf-8")
        init = (ROOT / "neyrobot_prod" / "__init__.py").read_text(encoding="utf-8")
        versioning = (ROOT / "neyrobot_prod" / "versioning.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_mode import", main)
        self.assertIn("group=-200", main)
        self.assertIn("silent_failure=True", main)
        for source in (site, init, versioning):
            self.assertNotIn("hotfix_v162", source)
            self.assertNotIn("v161_reference_v2", source)
            self.assertNotIn("ui_selfie_v138", source)
        self.assertNotIn("threading.Thread", versioning)

    def test_seed_catalog_contains_real_roman_pack(self):
        catalog_path = ROOT / "assets" / "celebrities_seed" / "catalog.json"
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        roman = data["characters"]["roman_abramovich"]
        self.assertTrue(roman["active"])
        self.assertGreaterEqual(len(roman["refs"]), 3)
        for item in roman["refs"]:
            path = catalog_path.parent / "roman_abramovich" / item["filename"]
            self.assertTrue(path.is_file(), path)
            self.assertEqual(64, len(item["sha256"]))
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                # Repository seeds are intentionally compact; admins can replace
                # them with full-resolution originals through /star_admin.
                self.assertGreaterEqual(min(image.size), 200)

    def test_seed_is_copied_to_persistent_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CatalogStore(self._config(tmp))
            roman = store.get("roman_abramovich")
            self.assertIsNotNone(roman)
            self.assertTrue(roman.active)
            self.assertEqual(3, len(store.ref_paths(roman.slug)))

    def test_admin_catalog_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CatalogStore(self._config(tmp))
            rec = store.create("Тестовый персонаж", 1)
            self.assertFalse(rec.active)
            from io import BytesIO
            for color in ((250, 250, 250), (220, 230, 240), (190, 210, 230)):
                sample = Image.new("RGB", (640, 640), color)
                out = BytesIO(); sample.save(out, format="JPEG", quality=95)
                rec = store.add_reference(rec.slug, out.getvalue())
            self.assertEqual(3, len(rec.refs))
            rec = store.set_active(rec.slug, True)
            self.assertTrue(rec.active)
            self.assertIn(rec.slug, {item.slug for item in store.active()})

    def test_render_yaml_uses_persistent_disk_and_strict_thresholds(self):
        text = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("mountPath: /data", text)
        self.assertIn("CELEBRITY_SELFIE_DATA_DIR", text)
        self.assertIn("CELEBRITY_SELFIE_MIN_USER_SIMILARITY", text)
        self.assertIn("CELEBRITY_SELFIE_MIN_CHARACTER_SIMILARITY", text)
        self.assertIn("value: '90'", text)


if __name__ == "__main__":
    unittest.main()
