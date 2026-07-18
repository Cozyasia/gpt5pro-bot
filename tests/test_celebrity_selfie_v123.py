# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class CelebritySelfieV123Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("celebrity_selfie_v123.py").read_text(encoding="utf-8")

    def test_exclusive_handlers_are_registered_before_legacy_routers(self):
        self.assertIn("group=-10000", self.source)
        self.assertIn("act:fun:aiselfie|celeb:", self.source)
        self.assertIn("_exclusive_image", self.source)
        self.assertIn("_exclusive_text", self.source)

    def test_legacy_photo_state_is_cleared(self):
        self.assertIn('"photo_flow"', self.source)
        self.assertIn('"awaiting_photo_for"', self.source)
        self.assertIn("_clear_legacy_flows(context)", self.source)

    def test_photo_upload_opens_celebrity_menu_instead_of_photo_workshop(self):
        self.assertIn('session["state"] = "choose_celebrity"', self.source)
        self.assertIn("reply_markup=base._main_menu_kb()", self.source)
        self.assertIn("Фото получено. Что сделать?", self.source)

    def test_direct_named_request_uses_catalog(self):
        self.assertIn("_direct_catalog_match", self.source)
        self.assertIn("base._prepare_library_refs", self.source)
        self.assertIn("селфи с Романом Абрамовичем", self.source)

    def test_callbacks_use_new_messages_not_edits(self):
        self.assertNotIn("edit_message_text", self.source)
        self.assertIn("reply_text", self.source)

    def test_entry_error_is_caught_inside_feature(self):
        self.assertIn("Celebrity Selfie callback failed", self.source)
        self.assertIn("Сессия восстановлена", self.source)


if __name__ == "__main__":
    unittest.main()
