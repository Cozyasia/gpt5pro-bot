# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class CelebritySelfieV128Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("celebrity_selfie_v128.py").read_text(encoding="utf-8")
        cls.bootstrap = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")

    def test_release_version(self):
        self.assertIn(
            'VERSION = "v128-celebrity-selfie-writable-session-single-owner-2026-07-19"',
            self.source,
        )

    def test_real_production_callback_is_exact(self):
        for value in ('"fun:aiselfie"', '"act:fun:aiselfie"', '"pedit:aiselfie"'):
            self.assertIn(value, self.source)

    def test_session_root_has_actual_write_probe_and_tmp_fallback(self):
        self.assertIn("def _probe_writable", self.source)
        self.assertIn("probe.write_bytes", self.source)
        self.assertIn('Path("/tmp/celebrity_selfie_sessions")', self.source)
        self.assertIn("engine._session_root = _writable_session_root", self.source)

    def test_only_one_handler_group_is_installed(self):
        self.assertIn("_GROUP = -2_000_000_000", self.source)
        self.assertNotIn("_BACKUP_GROUP", self.source)
        self.assertNotIn("for group in", self.source)
        self.assertEqual(
            self.source.count("app.add_handler(CallbackQueryHandler(_callback"),
            1,
        )

    def test_callbacks_photos_documents_and_text_are_owned(self):
        self.assertIn("CallbackQueryHandler(_callback", self.source)
        self.assertIn("filters.PHOTO | filters.Document.ALL", self.source)
        self.assertIn("filters.TEXT & ~filters.COMMAND", self.source)

    def test_diagnostic_exposes_storage_and_single_owner(self):
        self.assertIn("single_owner=yes", self.source)
        self.assertIn("session_root=", self.source)
        self.assertIn("session_root_writable=", self.source)

    def test_v128_is_only_registered_builder(self):
        self.assertIn("from celebrity_selfie_v128 import install_builder_hook", self.bootstrap)
        for version in ("v122", "v123", "v123_pedit", "v124", "v125", "v126", "v127"):
            self.assertNotIn(f"from celebrity_selfie_{version} import install_builder_hook", self.bootstrap)


if __name__ == "__main__":
    unittest.main()
