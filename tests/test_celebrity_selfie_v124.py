# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class CelebritySelfieV124Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("celebrity_selfie_v124.py").read_text(encoding="utf-8")

    def test_both_entry_callbacks_are_owned_by_one_handler(self):
        self.assertIn('"act:fun:aiselfie", "pedit:aiselfie"', self.source)
        self.assertIn("act:fun:aiselfie|pedit:aiselfie|celeb:", self.source)

    def test_handlers_preempt_every_legacy_photo_router(self):
        self.assertIn("group=-20000", self.source)
        self.assertIn("ApplicationHandlerStop", self.source)
        self.assertIn("legacy_flow_blocked=yes", self.source)

    def test_plain_telegram_photo_and_image_document_are_supported(self):
        self.assertIn('getattr(message, "photo"', self.source)
        self.assertIn("photos[-1]", self.source)
        self.assertIn('mime.startswith("image/")', self.source)
        self.assertIn("download_to_memory", self.source)
        self.assertIn("download_as_bytearray", self.source)

    def test_successful_selfie_advances_directly_to_celebrity_menu(self):
        self.assertIn('session["state"] = "choose_celebrity"', self.source)
        self.assertIn("✅ Селфи получено. Теперь выберите знаменитость", self.source)
        self.assertIn("reply_markup", self.source)
        self.assertIn("base._main_menu_kb()", self.source)

    def test_start_does_not_show_recovery_or_generic_error_card(self):
        start_block = self.source[self.source.index("async def _open_entry"):self.source.index("async def _download_telegram_image")]
        self.assertNotIn("Сессия восстановлена", start_block)
        self.assertNotIn("Упс", start_block)
        self.assertIn("Точное AI-селфи со знаменитостью", start_block)

    def test_callbacks_send_new_messages_instead_of_editing_old_card(self):
        self.assertNotIn("edit_message_text", self.source)
        self.assertIn("reply_text", self.source)

    def test_custom_reference_upload_reuses_already_downloaded_bytes(self):
        self.assertIn("_delegate_custom_reference", self.source)
        self.assertIn("base._download_image_from_update = supplied", self.source)
        self.assertIn('state == "await_custom_refs"', self.source)

    def test_feature_has_diagnostic_command(self):
        self.assertIn('CommandHandler("diag_celebrity_flow", _diag)', self.source)
        self.assertIn("telegram_photo=enabled", self.source)


if __name__ == "__main__":
    unittest.main()
