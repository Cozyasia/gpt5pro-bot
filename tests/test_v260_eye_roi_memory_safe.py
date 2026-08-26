# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V260EyeRoiMemorySafeTests(unittest.TestCase):
    def test_v260_loads_after_v259(self) -> None:
        source = Path("neyrobot_prod/selfie_v247_provider_supersample.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v260_eye_roi_memory_safe", source)
        self.assertLess(source.index("install_v259_eye_protection()"), source.index("install_v260_eye_roi()"))
        self.assertIn("AI_SELFIE_V260_INSTALL", source)

    def test_v260_reuses_proven_v258_base(self) -> None:
        source = Path("neyrobot_prod/selfie_v260_eye_roi_memory_safe.py").read_text(encoding="utf-8")
        self.assertIn("v258._source_pixel_transfer_v258", source)
        self.assertIn("AI_SELFIE_V260_BASE", source)
        self.assertIn("fallback_v258", source)
        self.assertIn("v258._true_face_transfer_v258", source)

    def test_v260_eliminates_full_frame_eye_warps(self) -> None:
        source = Path("neyrobot_prod/selfie_v260_eye_roi_memory_safe.py").read_text(encoding="utf-8")
        self.assertIn("_warp_source_roi", source)
        self.assertIn("local[0, 2] += float(residual[0]) - float(x0)", source)
        self.assertIn("local[1, 2] += float(residual[1]) - float(y0)", source)
        self.assertIn("full_frame_eye_warp=false", source)
        self.assertIn("full_frame_eye_float_blend=false", source)
        self.assertNotIn("_shift_frame(", source)
        self.assertNotIn("shifted_matched", source)
        self.assertNotIn("shifted_raw", source)

    def test_v260_eye_work_is_compact_and_bounded(self) -> None:
        source = Path("neyrobot_prod/selfie_v260_eye_roi_memory_safe.py").read_text(encoding="utf-8")
        self.assertIn("_EYE_MAX_LOCAL_SHIFT = 36.0", source)
        self.assertIn("for eye_index in (0, 1):", source)
        self.assertIn("box = _eye_roi(", source)
        self.assertIn("raw_patch = _warp_source_roi", source)
        self.assertIn("final_roi = final[y0:y1, x0:x1]", source)
        self.assertIn("del target", source)
        self.assertIn("person_b_untouched=true", source)

    def test_v260_preserves_lossless_delivery_and_no_new_handlers(self) -> None:
        source = Path("neyrobot_prod/selfie_v260_eye_roi_memory_safe.py").read_text(encoding="utf-8")
        self.assertIn("delivery._deliver = v253._deliver_original", source)
        self.assertIn("AI_SELFIE_SEND_AS_DOCUMENT = True", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)
        self.assertNotIn("PreCheckoutQueryHandler", source)

    def test_package_version_is_v260(self) -> None:
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v260-eye-roi-memory-safe-2026-08-26"', source)
        self.assertIn("v259-eye-landmark-protection-2026-08-26", source)


if __name__ == "__main__":
    unittest.main()
