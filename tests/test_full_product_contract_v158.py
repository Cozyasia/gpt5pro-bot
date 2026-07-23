# -*- coding: utf-8 -*-
"""Regression contract for every user-facing Neyro-Bot product area.

The suite is secret-free and prevents an unrelated feature patch from deleting
menus, payment wiring or the production entrypoint.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
RENDER = (ROOT / "render.yaml").read_text(encoding="utf-8")


class FullProductContractV158Tests(unittest.TestCase):
    def assert_tokens(self, source: str, tokens: list[str]) -> None:
        missing = [token for token in tokens if token not in source]
        self.assertFalse(missing, f"Missing product contract tokens: {missing}")

    def test_four_primary_modes_exist(self):
        self.assert_tokens(MAIN, [
            'callback_data="mode:study"',
            'callback_data="mode:work"',
            'callback_data="mode:fun"',
            'callback_data="mode:medicine"',
        ])

    def test_study_mode_is_complete(self):
        self.assert_tokens(MAIN, [
            "act:study:pdf_summary", "act:study:explain", "act:study:tasks",
            "act:study:essay", "act:study:exam_plan", "act:open:voice",
            "act:free", "epub", "docx",
        ])

    def test_work_mode_keeps_documents_logo_watermark_and_exports(self):
        self.assert_tokens(MAIN, [
            "act:work:doc", "act:work:report", "act:work:plan",
            "act:work:idea", "act:work:presentation", "act:work:catalog_pdf",
            "act:work:logo", "act:work:watermark", "PDF + PPTX",
        ])

    def test_entertainment_mode_has_exact_required_fifteen_actions(self):
        required = [
            "act:fun:revive", "act:fun:avatar", "act:fun:photoclip",
            "act:fun:vocalclip", "act:fun:textvideo", "act:fun:aiselfie",
            "act:fun:faceswap", "act:fun:removebg", "act:fun:replacebg",
            "act:fun:reels", "act:fun:film", "act:fun:shorts",
            "act:fun:music", "act:fun:games", "act:fun:ideas",
        ]
        self.assert_tokens(MAIN, required)
        mode_kb_start = MAIN.index("def _mode_kb")
        fun_start = MAIN.index('if key == "fun":', mode_kb_start)
        medicine_start = MAIN.index('if key == "medicine":', fun_start)
        menu = MAIN[fun_start:medicine_start]
        self.assertEqual(15, sum(token in menu for token in required))

    def test_medicine_mode_and_safety_contract_exist(self):
        self.assert_tokens(MAIN, [
            "def medicine_kb", "act:med:extract", "act:med:scan",
            "act:med:conclusion", "act:med:mri", "MEDICAL_DISCLAIMER",
            "не официальный диагноз",
        ])
        for module in (
            "medical_v111_runtime.py", "medical_mode_v116.py",
            "medical_card_v109_patch.py", "medical_card_v109_security.py",
        ):
            self.assertTrue((ROOT / module).is_file(), module)

    def test_photo_tools_and_face_tools_remain_wired(self):
        self.assert_tokens(MAIN, [
            "PHOTOROOM_API_KEY", "PIAPI_API_KEY", "SEGMIND_API_KEY",
            "removebg", "replacebg", "faceswap", "watermark",
        ])

    def test_payment_balance_subscription_and_refund_guards_exist(self):
        self.assert_tokens(MAIN, [
            "_handle_payment_start_payload", "_try_pay_then_do",
            "PreCheckoutQueryHandler", "successful_payment",
            "get_subscription_tier", "credits", "buyinv:", "TARIFF_URL",
            "/webapp/checkout",
        ])

    def test_chat_history_and_four_conversations_remain(self):
        self.assert_tokens(MAIN, [
            "CHAT_MAX_CONVERSATIONS", "min(4", "CHAT_MEMORY_ENABLED",
            "CHAT_HISTORY_PAGE_MESSAGES", "CHAT_HISTORY_PAGE_SIZE",
            "chat:delete:", "_chat_delete",
        ])

    def test_provider_routes_for_text_image_audio_and_video_exist(self):
        self.assert_tokens(MAIN, [
            "OPENAI_API_KEY", "OPENAI_IMAGE_KEY", "OPENAI_TTS_KEY",
            "DEEPGRAM_API_KEY", "COMET_API_KEY", "RUNWAY_API_KEY",
            "SORA_MODEL", "KLING_MODEL", "SUNO_ENABLED",
        ])

    def test_render_runs_the_full_main_application(self):
        self.assertIn("python -u main.py", RENDER)
        self.assertNotIn("neyro_bot_selfie_patch", RENDER)
        self.assertTrue((ROOT / "main.py").stat().st_size > 400_000)


if __name__ == "__main__":
    unittest.main()
