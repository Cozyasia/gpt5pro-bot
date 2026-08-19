# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V250HyperSwapIdentityTests(unittest.TestCase):
    def test_v250_is_loaded_at_startup(self) -> None:
        from telegram.ext import ApplicationBuilder

        self.assertTrue(
            getattr(ApplicationBuilder, "_neyrobot_v250_final_builder_lock", False),
            "V250 final builder owner was not installed by sitecustomize",
        )

    def test_v250_priority_owner_precedes_v245(self) -> None:
        from telegram.ext import ApplicationBuilder

        app = ApplicationBuilder().token("123456:TESTTOKEN").build()
        handlers = list(app.handlers.get(-1000002, []))
        callbacks = [getattr(h, "callback", None) for h in handlers]
        names = {getattr(cb, "__name__", "") for cb in callbacks if cb is not None}
        self.assertIn("_generation_owner", names)

    def test_hyperswap_1c_is_primary_and_v4_is_not_production_provider(self) -> None:
        source = Path("neyrobot_prod/selfie_v250_hyperswap_identity.py").read_text(encoding="utf-8")
        self.assertIn("/v1/hyperswap-image-faceswap-by-facefusion-labs", source)
        self.assertIn('"model_name": "hyperswap_1c"', source)
        self.assertIn('"output_format": "png"', source)
        self.assertIn('"output_quality": 100', source)
        self.assertIn("v4_production=false", source)
        self.assertIn("_BASE_V2_PROVIDER", source)

    def test_runtime_restores_supersampled_target_and_face_local_merge(self) -> None:
        from neyrobot_prod import selfie_v247_provider_supersample as v247
        from neyrobot_prod import selfie_v250_hyperswap_identity as v250
        from neyrobot_prod import selfie_v233_true_face_transfer as transfer
        from neyrobot_prod import selfie_v241_authoritative_runtime as v241

        v250.enforce_runtime(bind_generate=True)
        self.assertIs(transfer._left_person_crop, v247._provider_supersample_roi)
        self.assertIs(transfer._merge_left_crop, v250._merge_face_local)
        runtime = v241._runtime()
        if runtime is not None:
            self.assertIs(runtime._segmind_faceswap_v2, v250._segmind_hyperswap_1c)

    def test_source_is_verified_face_crop_not_full_phone_photo(self) -> None:
        source = Path("neyrobot_prod/selfie_v250_hyperswap_identity.py").read_text(encoding="utf-8")
        self.assertIn("v241._expression_crop", source)
        self.assertIn("full_photo_to_provider=false", source)


if __name__ == "__main__":
    unittest.main()
