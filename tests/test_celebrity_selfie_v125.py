# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class CelebritySelfieV125HistoricalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("celebrity_selfie_v125.py").read_text(encoding="utf-8")
        cls.bootstrap = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")

    def test_historical_module_remains_compilable_source(self):
        self.assertIn("CallbackQueryHandler(_callback)", self.source)
        self.assertIn("_GROUP = -30000", self.source)

    def test_v125_is_no_longer_registered(self):
        self.assertNotIn("from celebrity_selfie_v125 import install_builder_hook", self.bootstrap)
        self.assertIn("from celebrity_selfie_v130_runtime import install_builder_hook", self.bootstrap)

    def test_historical_download_fallbacks_remain_documented(self):
        self.assertIn("download_to_memory(out=out)", self.source)
        self.assertIn("download_to_memory(out=buffer)", self.source)
        self.assertIn("download_as_bytearray", self.source)
        self.assertIn("download_to_drive", self.source)


if __name__ == "__main__":
    unittest.main()
