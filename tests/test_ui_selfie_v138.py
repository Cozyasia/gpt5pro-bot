# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import KeyboardButton, ReplyKeyboardMarkup

import ui_selfie_v138 as v138


class UISelfieV138Tests(unittest.IsolatedAsyncioTestCase):
    def test_second_angle_palette_is_neutral_plus_one_blue_primary(self):
        markup = v138._second_angle_kb()
        buttons = [button for row in markup.inline_keyboard for button in row]
        self.assertNotIn("style", buttons[0].api_kwargs)
        self.assertEqual(buttons[1].api_kwargs.get("style"), "primary")
        self.assertNotIn("style", buttons[2].api_kwargs)

    def test_chat_palette_uses_blue_only_for_selected_provider(self):
        markup = v138._chat_provider_markup("gpt")
        buttons = [button for row in markup.inline_keyboard for button in row]
        self.assertEqual(buttons[0].api_kwargs.get("style"), "primary")
        self.assertNotIn("style", buttons[1].api_kwargs)
        self.assertNotIn("style", buttons[2].api_kwargs)
        self.assertIn("Чат с GPT", buttons[0].text)
        self.assertIn("Чат с Gemini", buttons[1].text)

    def test_main_keyboard_is_restored_to_neutral_default(self):
        mod = SimpleNamespace(
            main_kb=ReplyKeyboardMarkup(
                [[KeyboardButton("🎓 Учёба"), KeyboardButton("➕ Новый чат")]],
                resize_keyboard=True,
            )
        )
        v138.patch_main_keyboard(mod)
        buttons = [button for row in mod.main_kb.keyboard for button in row]
        self.assertTrue(all("style" not in button.api_kwargs for button in buttons))

    def test_delivery_state_distinguishes_preview_and_verified(self):
        mode, score = v138._delivery_state({"identity_min": 32, "identity_unknown": True})
        self.assertEqual((mode, score), ("preview", 32.0))
        mode, score = v138._delivery_state({"identity_min": 78, "identity_unknown": False})
        self.assertEqual((mode, score), ("verified", 78.0))

    async def test_unavailable_identity_score_becomes_labelled_preview_not_rejection(self):
        soft_result = {
            "user": 0.0,
            "celebrity": 0.0,
            "minimum": 0.0,
            "weighted": 0.0,
            "reason": "vision JSON unavailable",
        }
        with patch.object(v138, "_ORIGINAL_IDENTITY_QC", AsyncMock(return_value=soft_result)), \
             patch.object(v138.selfie.base, "_image_problem", return_value=""):
            result = await v138._identity_detail_qc_soft(object(), b"out", b"user", b"ref")
        self.assertTrue(result["identity_unknown"])
        self.assertGreaterEqual(result["minimum"], 20)
        self.assertIn("preview-qc-soft", result["reason"])

    async def test_real_structural_failure_is_never_softened(self):
        hard_result = {
            "user": 0.0,
            "celebrity": 0.0,
            "minimum": 0.0,
            "weighted": 0.0,
            "reason": "split-screen detected",
        }
        with patch.object(v138, "_ORIGINAL_IDENTITY_QC", AsyncMock(return_value=hard_result)):
            result = await v138._identity_detail_qc_soft(object(), b"out", b"user", b"ref")
        self.assertFalse(result["identity_unknown"])
        self.assertEqual(result["minimum"], 0.0)

    async def test_background_bystanders_do_not_hide_a_valid_two_person_foreground(self):
        assessment = {
            "hard_ok": False,
            "reason": "foreground_people=3",
            "local_score": 72.0,
        }
        with patch.object(v138, "_ORIGINAL_SCENE_ASSESSMENT", AsyncMock(return_value=assessment)):
            result = await v138._scene_assessment_soft(object(), b"raw", "премьера", phase="test")
        self.assertTrue(result["hard_ok"])
        self.assertIn("soft-background-bystanders", result["reason"])

    def test_runtime_thresholds_keep_structural_gates_and_enable_preview(self):
        v138.install_runtime_patches()
        self.assertEqual(v138.os.environ["CELEBRITY_V136_MIN_DELIVERY_IDENTITY"], "28")
        self.assertEqual(v138.os.environ["CELEBRITY_V138_VERIFIED_IDENTITY"], "58")
        self.assertIs(v138.selfie._score_candidate, v138._score_candidate_soft)
        self.assertIs(v138.selfie.engine._generate, v138._generate)


if __name__ == "__main__":
    unittest.main()
