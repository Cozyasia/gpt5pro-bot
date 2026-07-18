# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class CelebritySelfieV125Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("celebrity_selfie_v125.py").read_text(encoding="utf-8")
        cls.bootstrap = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")

    def test_one_catch_all_callback_owner_is_registered_first(self):
        self.assertIn("CallbackQueryHandler(_callback)", self.source)
        self.assertIn("_GROUP = -30000", self.source)
        self.assertIn("group=_GROUP", self.source)

    def test_both_legacy_entry_names_are_matched_by_marker(self):
        self.assertIn('"aiselfie"', self.source)
        self.assertIn('"ai_selfie"', self.source)
        self.assertIn("_is_entry_callback", self.source)

    def test_competing_builder_hooks_are_disabled(self):
        self.assertNotIn("from celebrity_selfie_v123 import install_builder_hook", self.bootstrap)
        self.assertNotIn("from celebrity_selfie_v123_pedit import install_builder_hook", self.bootstrap)
        self.assertNotIn("from celebrity_selfie_v124 import install_builder_hook", self.bootstrap)
        self.assertIn("from celebrity_selfie_v125 import install_builder_hook", self.bootstrap)

    def test_plain_telegram_photo_uses_largest_size_without_filename(self):
        self.assertIn('photos[-1] if photos else None', self.source)
        self.assertIn("media.file_id", self.source)
        self.assertNotIn("photos[-1].file_name", self.source)

    def test_download_has_four_compatible_fallbacks(self):
        self.assertIn("download_to_memory(out=out)", self.source)
        self.assertIn("download_to_memory(out=buffer)", self.source)
        self.assertIn("download_as_bytearray", self.source)
        self.assertIn("download_to_drive", self.source)

    def test_photo_advances_directly_to_celebrity_selection(self):
        self.assertIn("await core._accept_user_photo", self.source)
        self.assertIn("Теперь выберите знаменитость", Path("celebrity_selfie_v124.py").read_text(encoding="utf-8"))

    def test_navigation_leaves_stale_session_without_blocking_menu(self):
        self.assertIn('"🔥 развлечения"', self.source)
        self.assertIn("_clear_all(context)", self.source)
        self.assertIn("return", self.source)

    def test_diag_stops_older_command_handlers(self):
        diag = self.source[self.source.index("async def _diag"):]
        self.assertIn("single_owner=yes", diag)
        self.assertIn("legacy_v123_handlers=disabled", diag)
        self.assertIn("_stop()", diag)

    def test_no_user_facing_recovery_or_global_oops_text(self):
        self.assertNotIn("Сессия восстановлена", self.source)
        self.assertNotIn("Упс, произошла ошибка", self.source)


if __name__ == "__main__":
    unittest.main()
