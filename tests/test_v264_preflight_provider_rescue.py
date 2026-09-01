# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path

from neyrobot_prod import selfie_v264_preflight_provider_rescue as preflight


class V264PreflightProviderRescueTests(unittest.TestCase):
    def test_overscale_is_recoverable(self) -> None:
        reason = preflight._recoverable_preflight_reason(
            RuntimeError("V264 invalid similarity scale=6.309")
        )
        self.assertEqual(reason, "V264 invalid similarity scale=6.309")

    def test_small_native_source_is_recoverable(self) -> None:
        reason = preflight._recoverable_preflight_reason(
            RuntimeError("V264 source sampling too small: native_short=108.0")
        )
        self.assertEqual(reason, "V264 source sampling too small: native_short=108.0")

    def test_unrelated_runtime_error_is_not_hidden(self) -> None:
        self.assertIsNone(
            preflight._recoverable_preflight_reason(RuntimeError("unexpected compositor bug"))
        )
        self.assertIsNone(preflight._recoverable_preflight_reason(ValueError("bad value")))

    def test_preflight_rescue_does_not_cap_dense_scale_or_add_routes(self) -> None:
        source = Path("neyrobot_prod/selfie_v264_preflight_provider_rescue.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("dense_scale_cap=false", source)
        self.assertIn("guard._provider_rescue", source)
        self.assertIn("guard._production_gate", source)
        self.assertIn("max_candidates=2", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("PreCheckoutQueryHandler", source)
        self.assertNotIn("add_handler", source)

    def test_package_installs_preflight_after_production_guard(self) -> None:
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        production = package.index("_install_v264_production_guard()")
        preflight_install = package.index("_install_v264_preflight_rescue()")
        self.assertLess(production, preflight_install)
        self.assertIn("overscale_small_source_to_provider", package)

    def test_stage1_scaffold_patches_v242_durable_symbols(self) -> None:
        source = Path("neyrobot_prod/selfie_v264_stage1_scaffold_guard.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("selfie_v242_expression_lock as v242", source)
        self.assertIn("v242._call_google = _call_google", source)
        self.assertIn("v242._stage1_prompt = _stage1_prompt", source)
        self.assertIn("v242.enforce_runtime()", source)
        self.assertIn("durable_v242_binding=true", source)


if __name__ == "__main__":
    unittest.main()
