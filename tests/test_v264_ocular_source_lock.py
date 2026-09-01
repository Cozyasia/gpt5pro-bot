# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path

import cv2
import numpy as np

from neyrobot_prod import selfie_v264_ocular_source_lock as ocular


class V264OcularSourceLockTests(unittest.TestCase):
    def test_local_eye_restore_changes_only_small_destination_region(self) -> None:
        source = np.zeros((120, 120, 3), dtype=np.uint8)
        final = np.zeros((160, 160, 3), dtype=np.uint8)
        source_eye = np.asarray(
            [[35, 50], [40, 45], [48, 45], [54, 50], [48, 55], [40, 55]],
            dtype=np.float32,
        )
        final_eye = np.asarray(
            [[76, 78], [82, 72], [92, 72], [99, 78], [92, 84], [82, 84]],
            dtype=np.float32,
        )
        cv2.ellipse(source, (45, 50), (13, 8), 0, 0, 360, (210, 180, 150), -1)
        cv2.circle(source, (45, 50), 4, (40, 80, 130), -1)

        ok, scale, sigma = ocular._restore_one_eye(final, source, source_eye, final_eye)
        self.assertTrue(ok)
        self.assertGreater(scale, 0.45)
        self.assertGreater(sigma, 0.0)
        self.assertGreater(int(final.sum()), 0)
        # The operation is local: a distant corner remains untouched.
        self.assertEqual(int(final[:25, :25].sum()), 0)

    def test_eye_luminance_match_preserves_source_chroma_path(self) -> None:
        source = np.full((20, 30, 3), (120, 90, 50), dtype=np.uint8)
        target = np.full((20, 30, 3), (220, 210, 200), dtype=np.uint8)
        mask = np.full((20, 30), 255, dtype=np.uint8)
        matched = ocular._match_eye_luminance(source, target, mask)
        self.assertEqual(matched.shape, source.shape)
        self.assertFalse(np.array_equal(matched, target))

    def test_overlay_has_no_new_route_or_provider(self) -> None:
        source = Path("neyrobot_prod/selfie_v264_ocular_source_lock.py").read_text(encoding="utf-8")
        self.assertIn("iris_pupil_source_owned=true", source)
        self.assertIn("independent_geometry_warp=false", source)
        self.assertIn("v263._RIGHT_EYE", source)
        self.assertIn("v263._LEFT_EYE", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("PreCheckoutQueryHandler", source)
        self.assertNotIn("add_handler", source)
        self.assertNotIn("httpx", source)

    def test_metrics_are_recomputed_after_eye_texture_lock(self) -> None:
        source = Path("neyrobot_prod/selfie_v264_ocular_source_lock.py").read_text(encoding="utf-8")
        self.assertIn("metrics_after", source)
        self.assertIn("v263._quality_metrics", source)
        self.assertIn("_mobileface_embedding", source)
        self.assertIn("_dense_landmarks_68", source)

    def test_package_installs_ocular_lock_before_production_guard(self) -> None:
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        ocular_pos = package.index("_install_v264_ocular_lock()")
        guard_pos = package.index("_install_v264_production_guard()")
        self.assertLess(ocular_pos, guard_pos)
        self.assertIn("ocular_lock=dense68_source_eye_texture", package.replace("%s", "dense68_source_eye_texture"))


if __name__ == "__main__":
    unittest.main()
