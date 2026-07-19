# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class CelebritySelfieV128HistoricalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("celebrity_selfie_v128.py").read_text(encoding="utf-8")
        cls.bootstrap = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")

    def test_historical_release_version_remains(self):
        self.assertIn(
            'VERSION = "v128-celebrity-selfie-writable-session-single-owner-2026-07-19"',
            self.source,
        )

    def test_session_root_fix_remains_available_to_v129(self):
        self.assertIn("def _probe_writable", self.source)
        self.assertIn("probe.write_bytes", self.source)
        self.assertIn('Path("/tmp/celebrity_selfie_sessions")', self.source)
        self.assertIn("engine._session_root = _writable_session_root", self.source)

    def test_single_owner_routing_remains_in_base_layer(self):
        self.assertIn("_GROUP = -2_000_000_000", self.source)
        self.assertNotIn("_BACKUP_GROUP", self.source)
        self.assertEqual(self.source.count("app.add_handler(CallbackQueryHandler(_callback"), 1)

    def test_v128_builder_is_no_longer_registered(self):
        self.assertNotIn("from celebrity_selfie_v128 import install_builder_hook", self.bootstrap)
        self.assertIn("from celebrity_selfie_v132 import install_builder_hook", self.bootstrap)


if __name__ == "__main__":
    unittest.main()
