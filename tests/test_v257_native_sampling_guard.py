# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V257NativeSamplingGuardTests(unittest.TestCase):
    def test_v257_is_loaded_after_v256(self) -> None:
        source = Path("neyrobot_prod/selfie_v247_provider_supersample.py").read_text(encoding="utf-8")
        self.assertIn("selfie_v257_native_sampling_guard", source)
        self.assertLess(source.index("install_v256_large_scale()"), source.index("install_v257_native_sampling()"))

    def test_v257_retires_only_projected_sampling_gate(self) -> None:
        source = Path("neyrobot_prod/selfie_v257_native_sampling_guard.py").read_text(encoding="utf-8")
        self.assertIn("v256._MIN_PROJECTED_FACE_SHORT = 0.0", source)
        self.assertIn("v256._MAX_REAL_SOURCE_SCALE", source)
        self.assertIn("v256._MIN_NATIVE_FACE_SHORT", source)
        self.assertIn("easier 1.50x enlargement", source)
        self.assertIn("_BASE_TRUE_FACE_TRANSFER", source)

    def test_v257_preserves_v255_gate_lossless_delivery_and_handler_architecture(self) -> None:
        source = Path("neyrobot_prod/selfie_v257_native_sampling_guard.py").read_text(encoding="utf-8")
        self.assertIn("delivery._deliver = v253._deliver_original", source)
        self.assertIn("V255 source-face gate", source)
        self.assertIn("PERSON-B firewall", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("add_handler", source)
        self.assertNotIn("/v1/faceswap", source)

    def test_v257_is_historical_and_v265_enforces_native_sampling_directly(self) -> None:
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        engine = Path("neyrobot_prod/dense68_engine_v265.py").read_text(encoding="utf-8")
        self.assertIn('PRODUCTION_SELFIE_RUNTIME = "v265"', package)
        self.assertIn("native_face_short < v256._MIN_NATIVE_FACE_SHORT", engine)
        self.assertIn("scale <= v256._MAX_REAL_SOURCE_SCALE", engine)
        self.assertNotIn("selfie_v257_native_sampling_guard", package)
        self.assertNotIn("selfie_v257_native_sampling_guard", engine)


if __name__ == "__main__":
    unittest.main()
