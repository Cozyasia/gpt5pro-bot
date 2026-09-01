# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path

from neyrobot_prod import selfie_v264_local_strict_quality_recovery as recovery


class V264LocalStrictQualityRecoveryTests(unittest.TestCase):
    def test_second_route_keeps_legacy_valid_failure_local(self) -> None:
        self.assertEqual(
            recovery._second_route(legacy_passed=True, production_passed=False),
            "strict_local_recovery",
        )

    def test_second_route_uses_provider_only_for_legacy_failure(self) -> None:
        self.assertEqual(
            recovery._second_route(legacy_passed=False, production_passed=False),
            "isolated_provider_rescue",
        )

    def test_production_valid_refinement_stays_local(self) -> None:
        self.assertEqual(
            recovery._second_route(legacy_passed=True, production_passed=True),
            "strict_local_refinement",
        )

    def test_overlay_preserves_two_candidate_contract(self) -> None:
        source = Path("neyrobot_prod/selfie_v264_local_strict_quality_recovery.py").read_text(encoding="utf-8")
        body = source[
            source.index("async def _true_face_transfer_v264_quality_recovered"):
            source.index("def install()")
        ]
        self.assertEqual(body.count("v264._transfer_attempt_roi("), 2)
        self.assertEqual(body.count("guard._provider_rescue("), 1)
        self.assertIn("max_attempts=2", source)
        self.assertIn("strict_local_recovery", source)
        self.assertIn("catastrophic_retry=isolated_provider", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("PreCheckoutQueryHandler", source)
        self.assertNotIn("add_handler", source)

    def test_install_order_keeps_preflight_as_outer_safety_wrapper(self) -> None:
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v264_local_strict_quality_recovery", package)
        self.assertLess(
            package.index("_install_v264_production_guard()"),
            package.index("_install_v264_local_quality_recovery()"),
        )
        self.assertLess(
            package.index("_install_v264_local_quality_recovery()"),
            package.index("_install_v264_preflight_rescue()"),
        )


if __name__ == "__main__":
    unittest.main()
