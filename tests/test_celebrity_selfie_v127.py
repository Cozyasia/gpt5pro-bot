# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class CelebritySelfieV127Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("celebrity_selfie_v127.py").read_text(encoding="utf-8")
        cls.bootstrap = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")

    def test_real_production_callback_is_explicit(self):
        self.assertIn('"fun:aiselfie"', self.source)
        self.assertIn('"act:fun:aiselfie"', self.source)
        self.assertIn('"pedit:aiselfie"', self.source)

    def test_exact_pattern_handles_current_and_historical_callbacks(self):
        self.assertIn("aiselfie|ai_selfie|ai-selfie", self.source)
        self.assertIn("cs126:.*", self.source)
        self.assertIn("celeb:.*", self.source)

    def test_two_unique_priority_groups_are_installed(self):
        self.assertIn("_PRIMARY_GROUP = -2_000_000_000", self.source)
        self.assertIn("_BACKUP_GROUP = -1_900_000_000", self.source)
        self.assertIn("for group in (_PRIMARY_GROUP, _BACKUP_GROUP)", self.source)

    def test_actual_main_legacy_state_keys_are_cleared(self):
        for key in (
            "awaiting_ai_selfie_photo",
            "awaiting_ai_selfie_prompt",
            "ai_selfie_preset_prompt",
        ):
            self.assertIn(f'"{key}"', self.source)
        self.assertIn("data.pop(key, None)", self.source)

    def test_photo_and_text_are_owned_while_session_is_active(self):
        self.assertIn("MessageHandler(filters.PHOTO | filters.Document.ALL, _image)", self.source)
        self.assertIn("MessageHandler(filters.TEXT & ~filters.COMMAND, _text)", self.source)
        self.assertIn("if not _active(context):", self.source)

    def test_entry_calls_clean_wizard_directly(self):
        self.assertIn("await core._open(update, context)", self.source)
        self.assertIn("_stop()", self.source)

    def test_global_oops_is_suppressed_for_feature_errors(self):
        self.assertIn("app.add_error_handler(_error_handler)", self.source)
        self.assertNotIn("Упс, произошла ошибка", self.source)

    def test_v127_is_only_installed_builder(self):
        self.assertIn("from celebrity_selfie_v127 import install_builder_hook", self.bootstrap)
        for version in ("v122", "v123", "v123_pedit", "v124", "v125", "v126"):
            self.assertNotIn(f"from celebrity_selfie_{version} import install_builder_hook", self.bootstrap)

    def test_diagnostic_reports_exact_integration(self):
        self.assertIn("entry_callback=fun:aiselfie", self.source)
        self.assertIn("exact_pattern=yes", self.source)
        self.assertIn("legacy_keys_present=", self.source)


if __name__ == "__main__":
    unittest.main()
