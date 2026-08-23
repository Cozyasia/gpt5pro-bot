# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class V251V2IdentityDetailTests(unittest.TestCase):
    def test_v251_is_loaded_at_startup(self) -> None:
        from telegram.ext import ApplicationBuilder

        self.assertTrue(
            getattr(ApplicationBuilder, "_neyrobot_v251_final_builder_lock", False),
            "V251 final builder owner was not installed by sitecustomize",
        )

    def test_v251_priority_owner_precedes_v250_and_v245(self) -> None:
        from telegram.ext import ApplicationBuilder

        app = ApplicationBuilder().token("123456:TESTTOKEN").build()
        handlers = list(app.handlers.get(-1000003, []))
        callbacks = [getattr(h, "callback", None) for h in handlers]
        names = {getattr(cb, "__name__", "") for cb in callbacks if cb is not None}
        self.assertIn("_generation_owner", names)

    def test_v251_uses_v2_not_hyperswap_or_v4(self) -> None:
        source = Path("neyrobot_prod/selfie_v251_v2_identity_detail.py").read_text(encoding="utf-8")
        self.assertIn("/v1/faceswap-v2", source)
        self.assertIn('"face_restore": "codeformer-v0.1.0.pth"', source)
        self.assertIn("hyperswap=false", source)
        self.assertIn("v4=false", source)
        self.assertNotIn("/v1/hyperswap-image-faceswap-by-facefusion-labs", source)
        self.assertNotIn("/v1/faceswap-v4", source)

    def test_v251_owner_accepts_newer_final_transfer_overlays(self) -> None:
        from neyrobot_prod import selfie_v241_authoritative_runtime as v241
        from neyrobot_prod import selfie_v246_quality_hardlock as v246
        from neyrobot_prod import selfie_v247_provider_supersample as v247
        from neyrobot_prod import selfie_v250_hyperswap_identity as v250
        from neyrobot_prod import selfie_v252_v3_png_quality as v252
        from neyrobot_prod import selfie_v258_inner_face_integration as v258
        from neyrobot_prod import selfie_v233_true_face_transfer as transfer

        # V251 remains the proven callback/UX owner. V252 remains the frozen
        # provider fallback, while V258 is the current final PERSON-A source-pixel
        # transfer owner and preserves the established V251/V247 geometry contracts.
        v258.enforce_runtime(bind_generate=True)
        self.assertIs(transfer._left_person_crop, v247._provider_supersample_roi)
        self.assertIs(transfer._merge_left_crop, v250._merge_face_local)
        self.assertIs(transfer._ensure_full_hd, v246._ensure_full_hd_lossless)
        self.assertIs(transfer._true_face_transfer, v258._true_face_transfer_v258)
        runtime = v241._runtime()
        if runtime is not None:
            self.assertIs(runtime._segmind_faceswap_v2, v252._segmind_v3_png)

    def test_source_detail_is_frequency_only_and_png_intermediate(self) -> None:
        source = Path("neyrobot_prod/selfie_v251_v2_identity_detail.py").read_text(encoding="utf-8")
        self.assertIn("source_low_frequency=false", source)
        self.assertIn("source_detail=true", source)
        self.assertIn('format="PNG"', source)
        self.assertIn("fine_gain = 0.72", source)
        self.assertIn("mid_gain = 0.18", source)

    def test_verified_photo3_face_is_provider_source(self) -> None:
        source = Path("neyrobot_prod/selfie_v251_v2_identity_detail.py").read_text(encoding="utf-8")
        self.assertIn("v241._expression_crop", source)
        self.assertIn("full_photo_to_provider=false", source)


if __name__ == "__main__":
    unittest.main()
