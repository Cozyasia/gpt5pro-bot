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

    def test_v251_is_historical_and_does_not_own_v265_transfer(self) -> None:
        package = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        owner = Path("neyrobot_prod/selfie_v265_single_owner.py").read_text(encoding="utf-8")
        transfer_body = owner[owner.index("async def _true_face_transfer_v265"):owner.index("async def _call_google")]
        self.assertIn('PRODUCTION_SELFIE_RUNTIME = "v265"', package)
        self.assertIn("V265_PRODUCTION_ACCEPTED = True", package)
        self.assertNotIn("selfie_v251_v2_identity_detail", package)
        self.assertNotIn("selfie_v251_v2_identity_detail", transfer_body)
        self.assertNotIn("segmind", transfer_body.lower())
        self.assertNotIn("piapi", transfer_body.lower())
        self.assertNotIn("selfie_v264", transfer_body)
        self.assertNotIn("selfie_v262", transfer_body)

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
