# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import unittest
from pathlib import Path

from neyrobot_prod import selfie_v262_landmark_field_compositor as v262


class V262QualityStabilityTests(unittest.TestCase):
    def test_large_face_residual_guard_is_scale_normalized_but_capped(self) -> None:
        self.assertAlmostEqual(v262._landmark_residual_limit(200.0), 28.0, places=6)
        self.assertAlmostEqual(v262._landmark_residual_limit(736.0), 44.16, places=6)
        self.assertGreater(v262._landmark_residual_limit(736.0), 40.54)
        self.assertAlmostEqual(v262._landmark_residual_limit(1200.0), 48.0, places=6)

    def test_v262_colour_match_is_roi_only(self) -> None:
        source = Path("neyrobot_prod/selfie_v262_landmark_field_compositor.py").read_text(encoding="utf-8")
        self.assertIn("def _colour_match_lab_roi", source)
        self.assertIn("src_roi = warped[y0:y1, x0:x1]", source)
        self.assertIn("tgt_roi = target[y0:y1, x0:x1]", source)
        self.assertNotIn("v253._colour_match_lab(corrected, target, anatomy_mask)", source)

    def test_pro_failover_has_one_bounded_attempt(self) -> None:
        source = Path("neyrobot_prod/selfie_v241_authoritative_runtime.py").read_text(encoding="utf-8")
        self.assertIn('GEMINI_SELFIE_REQUEST_TIMEOUT_S", "90"', source)
        self.assertIn("max_attempts = 1", source)
        self.assertIn("pro_attempts=1", source)
        self.assertIn("_PRO_CIRCUIT_OPEN_UNTIL = time.monotonic() + 300.0", source)

    def test_http_transport_info_logs_are_suppressed(self) -> None:
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn('logging.getLogger("httpx").setLevel(logging.WARNING)', source)
        self.assertIn('logging.getLogger("httpcore").setLevel(logging.WARNING)', source)


if __name__ == "__main__":
    unittest.main()
