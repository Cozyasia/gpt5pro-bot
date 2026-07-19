# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class CelebritySelfieV127HistoricalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("celebrity_selfie_v127.py").read_text(encoding="utf-8")
        cls.bootstrap = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")

    def test_historical_exact_callback_contract_remains_documented(self):
        for value in ('"fun:aiselfie"', '"act:fun:aiselfie"', '"pedit:aiselfie"'):
            self.assertIn(value, self.source)

    def test_historical_module_remains_compilable_source(self):
        self.assertIn("await core._open(update, context)", self.source)
        self.assertIn("await core._image(update, context)", self.source)

    def test_v127_is_no_longer_registered(self):
        self.assertNotIn("from celebrity_selfie_v127 import install_builder_hook", self.bootstrap)
        self.assertIn("from celebrity_selfie_v129 import install_builder_hook", self.bootstrap)


if __name__ == "__main__":
    unittest.main()
