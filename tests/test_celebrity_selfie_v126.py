# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class CelebritySelfieV126Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("celebrity_selfie_v126.py").read_text(encoding="utf-8")
        cls.bootstrap = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")

    def test_known_legacy_callback_names_are_supported_by_the_clean_wizard(self):
        for value in ("act:fun:aiselfie", "pedit:aiselfie", "fun:aiselfie"):
            self.assertIn(value, self.source)

    def test_v126_is_retained_but_its_builder_is_not_installed(self):
        self.assertTrue(Path("celebrity_selfie_v126.py").exists())
        self.assertNotIn("from celebrity_selfie_v126 import install_builder_hook", self.bootstrap)
        self.assertIn("from celebrity_selfie_v133 import install_builder_hook", self.bootstrap)

    def test_plain_telegram_photo_uses_largest_photo_without_filename(self):
        self.assertIn("media = photos[-1] if photos else None", self.source)
        self.assertIn("media.file_id", self.source)
        self.assertNotIn("photos[-1].file_name", self.source)

    def test_telegram_download_has_compatible_fallbacks(self):
        self.assertIn("download_to_memory(out=buffer)", self.source)
        self.assertIn("download_to_memory(out=out)", self.source)
        self.assertIn("download_as_bytearray", self.source)
        self.assertIn("download_to_drive", self.source)

    def test_successful_photo_opens_celebrity_menu_directly(self):
        self.assertIn('session["state"] = "choose_celebrity"', self.source)
        self.assertIn("✅ Селфи получено. Теперь выберите знаменитость", self.source)
        self.assertIn("_celebrity_menu_kb()", self.source)

    def test_catalog_search_prepares_reference_pack_not_name_only_generation(self):
        self.assertIn("engine.search_catalog", self.source)
        self.assertIn("engine._prepare_library_refs", self.source)
        self.assertIn("Подготавливаю библиотечные референсы лица", self.source)

    def test_old_router_modules_are_not_imported(self):
        self.assertNotIn("import celebrity_selfie_v123", self.source)
        self.assertNotIn("import celebrity_selfie_v124", self.source)
        self.assertNotIn("import celebrity_selfie_v125", self.source)

    def test_user_facing_global_oops_and_recovery_cards_are_absent(self):
        self.assertNotIn("Упс, произошла ошибка", self.source)
        self.assertNotIn("Сессия восстановлена", self.source)
        self.assertNotIn("Фото получено. Что сделать?", self.source)

    def test_refinement_remains_available_through_v122_callbacks(self):
        self.assertIn('data.startswith("celeb:")', self.source)
        self.assertIn("await engine._on_callback", self.source)


if __name__ == "__main__":
    unittest.main()
