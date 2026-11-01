# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V250HyperSwapIdentityTests(unittest.TestCase):
    def test_v250_is_historical_and_v265_owns_startup(self) -> None:
        from telegram.ext import ApplicationBuilder

        self.assertFalse(getattr(ApplicationBuilder, "_neyrobot_v250_final_builder_lock", False))
        self.assertTrue(getattr(ApplicationBuilder, "_neyrobot_v265_single_owner_builder_lock", False))

    def test_v250_does_not_register_a_production_owner(self) -> None:
        from telegram.ext import ApplicationBuilder

        app = ApplicationBuilder().token("123456:TESTTOKEN").build()
        handlers = list(app.handlers.get(-1000002, []))
        callbacks = [getattr(h, "callback", None) for h in handlers]
        names = {getattr(cb, "__name__", "") for cb in callbacks if cb is not None}
        self.assertNotIn("_generation_owner", names)

    def test_hyperswap_1c_is_primary_and_v4_is_not_production_provider(self) -> None:
        source = Path("neyrobot_prod/selfie_v250_hyperswap_identity.py").read_text(encoding="utf-8")
        self.assertIn("/v1/hyperswap-image-faceswap-by-facefusion-labs", source)
        self.assertIn('"model_name": "hyperswap_1c"', source)
        self.assertIn('"output_format": "png"', source)
        self.assertIn('"output_quality": 100', source)
        self.assertIn("v4_production=false", source)
        self.assertIn("_BASE_V2_PROVIDER", source)

    def test_historical_runtime_keeps_its_supersample_and_local_merge_contract(self) -> None:
        source = Path("neyrobot_prod/selfie_v250_hyperswap_identity.py").read_text(encoding="utf-8")
        self.assertIn("transfer._left_person_crop = v247._provider_supersample_roi", source)
        self.assertIn("transfer._merge_left_crop = _merge_face_local", source)
        self.assertIn("runtime._segmind_faceswap_v2 = _segmind_hyperswap_1c", source)

    def test_source_is_verified_face_crop_not_full_phone_photo(self) -> None:
        source = Path("neyrobot_prod/selfie_v250_hyperswap_identity.py").read_text(encoding="utf-8")
        self.assertIn("v241._expression_crop", source)
        self.assertIn("full_photo_to_provider=false", source)


if __name__ == "__main__":
    unittest.main()
