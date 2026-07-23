# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOTFIX = (ROOT / "neyrobot_prod" / "hotfix_v159.py").read_text(encoding="utf-8")


class HotfixV159Tests(unittest.TestCase):
    def test_hotfix_is_valid_python(self):
        ast.parse(HOTFIX)

    def test_version_contract_is_v159_everywhere(self):
        expected = "v159-payments-selfie-medical-integrity-2026-07-24"
        self.assertIn(expected, HOTFIX)
        self.assertIn(expected, (ROOT / "neyrobot_prod" / "versioning.py").read_text(encoding="utf-8"))
        self.assertIn(expected, (ROOT / "neyrobot_prod" / "__init__.py").read_text(encoding="utf-8"))
        site = (ROOT / "sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("neyrobot_prod.hotfix_v159", site)
        self.assertNotIn("install_celebrity_selfie_v158", site)

    def test_credit_catalog_overrides_stale_render_labels(self):
        for token in (
            'CREDIT_PACK_SMALL_CREDITS"] = "1000"',
            'CREDIT_PACK_MID_CREDITS"] = "3000"',
            'CREDIT_PACK_BIG_CREDITS"] = "7000"',
            '_DEFAULT_PACKAGES: dict[int, int] = {1000: 990, 3000: 2790, 7000: 6290}',
        ):
            self.assertIn(token, HOTFIX)

    def test_server_resolver_rejects_mixed_package_values(self):
        from neyrobot_prod.hotfix_v159 import _resolve_pack

        mod = types.SimpleNamespace(CREDIT_PACKAGES_RUB={1000: 990, 3000: 2790, 7000: 6290})
        self.assertEqual((1000, 990), _resolve_pack(mod, 1000, 990))
        self.assertEqual((3000, 2790), _resolve_pack(mod, 0, 2790))
        self.assertIsNone(_resolve_pack(mod, 1000, 2790))
        self.assertIsNone(_resolve_pack(mod, 300, 2490))

    def test_all_yookassa_credit_methods_are_present(self):
        for method in ("yoo_sbp", "yoo_sberpay", "yoo_tpay", "yoo_mirpay", "yoo_card", "yoo_all"):
            self.assertIn(method, HOTFIX)
        self.assertIn("_yoo_create_credit_payment", HOTFIX)
        self.assertIn("_poll_yoo_credit_payment", HOTFIX)
        self.assertIn("credit:v159:pay:", HOTFIX)
        self.assertIn("topup:rub:", HOTFIX)

    def test_selfie_wizard_owns_callback_and_photo_before_generic_router(self):
        for token in (
            "celebrity_selfie_v124",
            "_selfie_callback",
            "_selfie_image",
            "_selfie_text",
            'group=_GROUP',
            'act:fun:aiselfie(?:_.*)?',
            "После загрузки автоматически откроется каталог знаменитостей",
        ):
            self.assertIn(token, HOTFIX)
        flow = (ROOT / "celebrity_selfie_v124.py").read_text(encoding="utf-8")
        self.assertIn('session["state"] = "choose_celebrity"', flow)
        self.assertIn("base._main_menu_kb()", flow)

    def test_owner_reference_validation_is_patched_before_release_install(self):
        self.assertLess(HOTFIX.index("release._valid_jpeg = _valid_owner_jpeg"), HOTFIX.index("release.install()"))
        self.assertIn("len(raw or b\"\") >= 4_000", HOTFIX)
        self.assertIn("len(paths) != 3", HOTFIX)

    def test_medical_engine_and_card_integrity_remain_protected(self):
        for path in (
            "medical_v111_runtime.py",
            "medical_v111_client.py",
            "medical_v111_reasoning.py",
            "medical_card_v109_patch.py",
            "medical_card_v109_security.py",
            "neyrobot_prod/medical_followup.py",
            "neyrobot_prod/medical_answer_ui.py",
        ):
            self.assertTrue((ROOT / path).is_file(), path)
        followup = (ROOT / "neyrobot_prod" / "medical_followup.py").read_text(encoding="utf-8")
        runtime = (ROOT / "medical_v111_runtime.py").read_text(encoding="utf-8")
        self.assertIn("medical_followup.patch_runtime(mod)", HOTFIX)
        self.assertIn("runtime.analyze", followup)
        self.assertIn("extract_image", runtime)
        self.assertIn("extract_text", runtime)
        self.assertIn("reason_and_audit", runtime)
        self.assertIn("medcard_pending", runtime)


if __name__ == "__main__":
    unittest.main()
