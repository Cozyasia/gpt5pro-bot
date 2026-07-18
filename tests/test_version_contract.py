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

    def test_release_version_is_v125(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn(
            'VERSION = "v125-celebrity-selfie-single-owner-2026-07-19"',
            source,
        )

    def test_v121_presentation_overlay_is_still_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from presentation_relaxed_v121 import install_builder_hook", source)
        self.assertIn("_install_presentation_relaxed()", source)

    def test_v122_catalog_and_runtime_are_still_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v122 import install_builder_hook", source)
        self.assertIn("_install_celebrity_selfie_base()", source)
        self.assertIn("_install_celebrity_selfie_runtime()", source)

    def test_competing_v123_and_v124_builder_hooks_are_not_installed(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("from celebrity_selfie_v123 import install_builder_hook", source)
        self.assertNotIn("from celebrity_selfie_v123_pedit import install_builder_hook", source)
        self.assertNotIn("from celebrity_selfie_v124 import install_builder_hook", source)

    def test_v125_single_owner_is_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v125 import install_builder_hook", source)
        self.assertIn("_install_celebrity_selfie_single_owner()", source)


if __name__ == "__main__":
    unittest.main()
