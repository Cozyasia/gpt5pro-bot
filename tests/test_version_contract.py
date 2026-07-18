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

    def test_release_version_is_v124(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn(
            'VERSION = "v124-celebrity-selfie-telegram-photo-flow-2026-07-19"',
            source,
        )

    def test_v121_presentation_overlay_is_still_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from presentation_relaxed_v121 import install_builder_hook", source)
        self.assertIn("_install_presentation_relaxed()", source)

    def test_v122_celebrity_selfie_overlay_is_still_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v122 import install_builder_hook", source)
        self.assertIn("_install_celebrity_selfie()", source)
        self.assertIn("_install_celebrity_selfie_runtime()", source)

    def test_v123_exclusive_flow_overlay_is_still_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v123 import install_builder_hook", source)
        self.assertIn("_install_celebrity_selfie_flow()", source)
        self.assertIn("_install_celebrity_selfie_flow_runtime()", source)

    def test_v123_photo_quick_action_bridge_is_still_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v123_pedit import install_builder_hook", source)
        self.assertIn("_install_celebrity_selfie_pedit()", source)

    def test_v124_telegram_photo_flow_is_bootstrapped_last(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v124 import install_builder_hook", source)
        self.assertIn("_install_celebrity_selfie_telegram_photo()", source)
        self.assertGreater(
            source.index("from celebrity_selfie_v124 import install_builder_hook"),
            source.index("from celebrity_selfie_v123_pedit import install_builder_hook"),
        )


if __name__ == "__main__":
    unittest.main()
