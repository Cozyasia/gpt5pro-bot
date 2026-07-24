# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOTFIX = (ROOT / "neyrobot_prod" / "hotfix_v162.py").read_text(encoding="utf-8")
GUARD = (ROOT / "neyrobot_prod" / "v162_flow_guard.py").read_text(encoding="utf-8")
VERSIONING = (ROOT / "neyrobot_prod" / "versioning.py").read_text(encoding="utf-8")
SITE = (ROOT / "sitecustomize.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


class HotfixV162Tests(unittest.TestCase):
    def test_v162_sources_are_valid_python(self):
        for source in (HOTFIX, GUARD, VERSIONING, SITE):
            ast.parse(source)

    def test_v162_is_explicit_startup_owner(self):
        version = "v162-unified-celebrity-selfie-flow-2026-07-24"
        self.assertIn(version, HOTFIX)
        self.assertIn(version, VERSIONING)
        self.assertIn("neyrobot_prod.hotfix_v162", SITE)
        self.assertIn("neyrobot_prod.v162_flow_guard", SITE)
        self.assertIn("from neyrobot_prod.hotfix_v162 import install_early", VERSIONING)
        self.assertIn("from neyrobot_prod.v162_flow_guard import install", VERSIONING)

    def test_authoritative_route_is_before_v159_and_generic_photo_handlers(self):
        self.assertIn("_GROUP = -2_146_000_000", HOTFIX)
        self.assertIn("act:fun:aiselfie(?:_.*)?", HOTFIX)
        self.assertIn("filters.PHOTO | filters.Document.IMAGE", HOTFIX)
        self.assertIn("filters.TEXT & ~filters.COMMAND", HOTFIX)
        self.assertIn("wizard._accept_user_photo", HOTFIX)
        self.assertIn("session[\"state\"] = \"choose_celebrity\"", HOTFIX)
        self.assertIn("never the generic photo-action menu", HOTFIX)

    def test_photo_choice_callbacks_are_consumed_directly(self):
        self.assertIn('data not in {"celeb:use_cached", "celeb:upload_user"}', GUARD)
        self.assertIn("wizard._cached_photo", GUARD)
        self.assertIn("wizard._accept_user_photo", GUARD)
        self.assertIn("release._resume_pending_after_photo", GUARD)
        self.assertIn("После загрузки откроется каталог знаменитостей и персонажей", GUARD)

    def test_target_is_mandatory_before_scene_or_render(self):
        self.assertIn("def _target_ready", HOTFIX)
        self.assertIn("def _reply_target_required", HOTFIX)
        self.assertIn("Без выбранного человека", HOTFIX)
        self.assertIn("and not _target_ready(session)", HOTFIX)
        self.assertIn("generic_nano_banana_without_target=blocked", HOTFIX)

    def test_menu_and_free_text_share_catalog_reference_preparation(self):
        self.assertIn("def _catalog_match", HOTFIX)
        self.assertIn("engine.search_catalog", HOTFIX)
        self.assertIn("engine._prepare_library_refs", HOTFIX)
        self.assertIn("pending_target_id", HOTFIX)
        self.assertIn("pending_scene", HOTFIX)
        self.assertIn("селфи с Романом Абрамовичем в ресторане", GUARD)
        self.assertIn('queries.append("Роман Абрамович")', GUARD)

    def test_roman_keeps_v161_hybrid_and_owner_references(self):
        self.assertIn("from . import hotfix_v161 as previous", HOTFIX)
        self.assertIn("roman_render=v161-hybrid-identity", HOTFIX)
        self.assertIn("previous._full_reference_paths()", HOTFIX)
        self.assertIn("fixed_roman_reference_count", HOTFIX)

    def test_version_has_one_owner_without_application_handler_stop(self):
        self.assertIn("_remove_duplicate_version_handlers", HOTFIX)
        self.assertIn('app.remove_handler(handler, group=group)', HOTFIX)
        start = HOTFIX.index("async def _cmd_version")
        end = HOTFIX.index("def _patch_version_contract", start)
        command_source = HOTFIX[start:end]
        self.assertNotIn("ApplicationHandlerStop", command_source)
        self.assertIn("version_duplicate_error=blocked", command_source)

    def test_timeout_is_practical_but_generic_route_is_not_primary(self):
        self.assertIn('COMET_IMAGE_EDIT_TIMEOUT_S", "600"', HOTFIX)
        self.assertIn('CELEBRITY_V150_COMET_TIMEOUT_S", "600"', HOTFIX)
        self.assertIn("catalog_reference_policy=automatic-3-or-4-reference-pack", HOTFIX)

    def test_other_product_modes_remain_untouched(self):
        for token in (
            'callback_data="mode:study"', 'callback_data="mode:work"',
            'callback_data="mode:fun"', 'callback_data="mode:medicine"',
            "act:work:logo", "act:work:watermark", "act:med:mri",
            "_handle_payment_start_payload", "successful_payment",
        ):
            self.assertIn(token, MAIN)


if __name__ == "__main__":
    unittest.main()
