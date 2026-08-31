# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from neyrobot_prod import selfie_v264_dense68_roi_production as v264
from neyrobot_prod import selfie_v264_identity_core_refinement as core


class V264IdentityCoreRefinementTests(unittest.TestCase):
    def test_bounded_core_changes_deep_interior_but_pixel_locks_outside_and_boundary(self) -> None:
        import cv2

        h = w = 121
        composed = np.full((h, w, 3), 100, dtype=np.uint8)
        corrected = np.full((h, w, 3), 170, dtype=np.uint8)
        target = np.full((h, w, 3), 100, dtype=np.uint8)
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.circle(mask, (60, 60), 45, 255, -1)

        original_match = v264._colour_match_lab_roi_only
        try:
            v264._colour_match_lab_roi_only = lambda source, _target, _mask: source.copy()
            refined, low_strength, pixel_mix, sigma, max_alpha = core._inject_bounded_identity_core(
                composed, corrected, target, mask, 650.0, 29.0
            )
        finally:
            v264._colour_match_lab_roi_only = original_match

        self.assertGreater(low_strength, 0.0)
        self.assertGreater(pixel_mix, 0.0)
        self.assertGreater(sigma, 0.0)
        self.assertGreater(max_alpha, 0.0)
        self.assertGreater(int(refined[60, 60, 0]), 105)
        self.assertTrue(np.array_equal(refined[0, 0], composed[0, 0]))
        # A pixel just inside the anatomical boundary remains exactly on the
        # accepted V264 compositor because the source core starts deeper inside.
        self.assertTrue(np.array_equal(refined[60, 16], composed[60, 16]))

    def test_standard_candidate_is_delegated_without_identity_core(self) -> None:
        sentinel = np.full((32, 32, 3), 77, dtype=np.uint8)
        old_base = core._BASE_COMPOSE
        try:
            core._BASE_COMPOSE = lambda *_args, **_kwargs: (sentinel.copy(), "base", 20.0, 0.38, 0.74)
            out, mode, boundary, structure, detail = core._identity_core_compose_roi(
                sentinel, sentinel, np.full((32, 32), 255, dtype=np.uint8), 500.0, strict=False
            )
        finally:
            core._BASE_COMPOSE = old_base
        self.assertTrue(np.array_equal(out, sentinel))
        self.assertEqual(mode, "base")
        self.assertEqual(boundary, 20.0)
        self.assertEqual(structure, 0.38)
        self.assertEqual(detail, 0.74)

    def test_refinement_keeps_two_attempt_contract_and_no_new_routes(self) -> None:
        v264_source = Path("neyrobot_prod/selfie_v264_dense68_roi_production.py").read_text(encoding="utf-8")
        overlay_source = Path("neyrobot_prod/selfie_v264_identity_core_refinement.py").read_text(encoding="utf-8")
        transfer_body = v264_source[
            v264_source.index("async def _true_face_transfer_v264"):v264_source.index("def enforce_runtime")
        ]
        self.assertEqual(transfer_body.count("_transfer_attempt_roi("), 2)
        self.assertIn("standard_unchanged=true", overlay_source)
        self.assertIn("max_attempts=2", overlay_source)
        self.assertIn("boundary_pixel_lock=true", overlay_source)
        self.assertNotIn("CallbackQueryHandler", overlay_source)
        self.assertNotIn("PreCheckoutQueryHandler", overlay_source)
        self.assertNotIn("add_handler", overlay_source)

    def test_package_installs_identity_core_after_base_v264_with_safe_fallback(self) -> None:
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v264_identity_core_refinement", package)
        self.assertLess(package.index("_install_v264_identity()"), package.index("_install_v264_identity_core()"))
        self.assertIn("fallback=base_v264", package)
        self.assertIn("identity_core=", package)


if __name__ == "__main__":
    unittest.main()
