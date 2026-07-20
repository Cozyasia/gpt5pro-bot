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

    def test_release_version_is_v142(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn(
            'VERSION = "v142-preserve-user-composite-2026-07-21"',
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

    def test_old_selfie_router_hooks_through_v134_are_disabled(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        for version in (
            "v123", "v123_pedit", "v124", "v125", "v126", "v127", "v128", "v129",
            "v130_runtime", "v131", "v132", "v133", "v134",
        ):
            self.assertNotIn(f"from celebrity_selfie_{version} import install_builder_hook", source)

    def test_v136_wizard_is_kept_for_ui_and_catalog(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v136 import install_builder_hook", source)
        self.assertIn("_install_celebrity_selfie_v136()", source)

    def test_gpt_gemini_selector_is_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from chat_provider_v136 import install_builder_hook", source)
        self.assertIn("_install_chat_provider_builder()", source)
        self.assertIn("_install_chat_provider_async()", source)

    def test_v137_ui_hotfix_is_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from ui_hotfix_v137 import install_builder_hook", source)
        self.assertIn("_install_ui_v137_runtime()", source)
        self.assertIn("_install_ui_v137_builder()", source)

    def test_v138_palette_and_preview_policy_remain_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from ui_selfie_v138 import install_builder_hook", source)
        self.assertIn("_install_v138_safe_runtime()", source)
        self.assertIn("_install_v138_builder()", source)
        self.assertIn("_install_v138_compat_builder()", source)
        self.assertIn("_install_v138_async()", source)

    def test_v139_two_stage_pipeline_remains_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v139 import install_builder_hook", source)
        self.assertIn("_install_v139_runtime()", source)
        self.assertIn("_install_v139_builder()", source)
        self.assertIn("from celebrity_selfie_v139_compat import install", source)
        self.assertGreater(source.index("from celebrity_selfie_v139"), source.index("from ui_selfie_v138"))

    def test_v140_scene_rescue_is_applied_after_v139(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v140 import install", source)
        self.assertIn("_install_v140()", source)
        self.assertGreater(source.index("from celebrity_selfie_v140"), source.index("from celebrity_selfie_v139"))

    def test_v141_accepted_result_refinement_remains_bootstrapped(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v141 import install", source)
        self.assertIn("_install_v141()", source)
        self.assertIn("_install_v141_builder()", source)
        self.assertGreater(source.index("from celebrity_selfie_v141"), source.index("from celebrity_selfie_v140"))

    def test_v142_preserve_user_pipeline_is_applied_last(self):
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v142 import install", source)
        self.assertIn("_install_v142()", source)
        self.assertIn("_install_v142_builder()", source)
        self.assertGreater(source.index("from celebrity_selfie_v142"), source.index("from celebrity_selfie_v141"))
        self.assertIn('CELEBRITY_V142_CUTOUT_PROVIDERS", "photoroom,rembg"', source)
        self.assertIn('CELEBRITY_V142_PRESERVED_USER_SCORE_FLOOR", "94"', source)
        self.assertIn('CELEBRITY_V142_ALLOW_GENERATIVE_CLEANUP", "0"', source)


if __name__ == "__main__":
    unittest.main()
