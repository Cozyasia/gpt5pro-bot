# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class CelebritySelfieV129Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("celebrity_selfie_v129.py").read_text(encoding="utf-8")
        cls.bootstrap = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")

    def test_release_version(self):
        self.assertIn(
            'VERSION = "v129-celebrity-selfie-writable-reference-library-2026-07-19"',
            self.source,
        )

    def test_reference_root_has_write_probe_and_tmp_fallback(self):
        self.assertIn("def _probe_writable", self.source)
        self.assertIn("probe.write_bytes", self.source)
        self.assertIn('Path("/tmp/celebrity_library")', self.source)
        self.assertIn('"CELEBRITY_LIBRARY_ROOT"', self.source)

    def test_live_v122_library_instance_is_patched(self):
        self.assertIn("engine.LIBRARY.root = _LIBRARY_ROOT", self.source)
        self.assertIn("engine.LIBRARY.ensure_refs = _ensure_refs_writable", self.source)
        self.assertIn("_ORIGINAL_ENSURE_REFS", self.source)

    def test_one_exact_handler_group_owns_full_flow(self):
        self.assertIn("_GROUP = -2_000_000_000", self.source)
        self.assertEqual(self.source.count("app.add_handler(CallbackQueryHandler(_callback"), 1)
        self.assertIn("filters.PHOTO | filters.Document.ALL", self.source)
        self.assertIn("filters.TEXT & ~filters.COMMAND", self.source)

    def test_diagnostic_reports_both_independent_roots(self):
        self.assertIn("session_root_writable=", self.source)
        self.assertIn("library_root=", self.source)
        self.assertIn("library_root_writable=", self.source)
        self.assertIn("reference_flow=enabled", self.source)

    def test_v129_is_historical_and_v131_is_registered(self):
        self.assertNotIn("from celebrity_selfie_v129 import install_builder_hook", self.bootstrap)
        self.assertIn("from celebrity_selfie_v131 import install_builder_hook", self.bootstrap)
        for version in ("v122", "v123", "v123_pedit", "v124", "v125", "v126", "v127", "v128", "v130_runtime"):
            self.assertNotIn(f"from celebrity_selfie_{version} import install_builder_hook", self.bootstrap)


if __name__ == "__main__":
    unittest.main()
