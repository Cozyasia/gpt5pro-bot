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

    def test_release_version_is_v129(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn(
            'VERSION = "v129-celebrity-selfie-writable-reference-library-2026-07-19"',
            source,
        )

    def test_v121_presentation_overlay_is_still_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from presentation_relaxed_v121 import install_builder_hook", source)
        self.assertIn("_install_presentation_relaxed()", source)

    def test_v122_runtime_is_kept_but_telegram_builder_is_not_installed(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v122 import install_runtime_async", source)
        self.assertIn("_install_celebrity_library_runtime()", source)
        self.assertNotIn("from celebrity_selfie_v122 import install_builder_hook", source)

    def test_all_historical_selfie_router_hooks_are_disabled(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        for version in ("v123", "v123_pedit", "v124", "v125", "v126", "v127", "v128"):
            self.assertNotIn(f"from celebrity_selfie_{version} import install_builder_hook", source)

    def test_v129_reference_integration_is_the_only_selfie_builder(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v129 import install_builder_hook", source)
        self.assertIn("_install_celebrity_selfie_references()", source)


if __name__ == "__main__":
    unittest.main()
