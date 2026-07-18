# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class VersionContractTests(unittest.TestCase):
    def test_sitecustomize_installs_canonical_version_contract(self):
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("from neyrobot_prod.versioning import install_early", source)
        self.assertIn("install_version_contract_early()", source)

    def test_public_version_handler_preempts_legacy_handlers(self):
        source = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn('CommandHandler("version", _cmd_version)', source)
        self.assertIn("group=-1000", source)
        self.assertIn("raise ApplicationHandlerStop", source)
        self.assertIn("mod.PATCH_VERSION = VERSION", source)

    def test_release_version_is_v119_4(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v119.4-production-version-contract-2026-07-18"', source)


if __name__ == "__main__":
    unittest.main()
