# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path


class RetouchV261BatchTests(unittest.TestCase):
    def test_overlay_registers_no_new_telegram_handlers(self) -> None:
        source = Path("neyrobot_prod/retouch_v261_batch.py").read_text(encoding="utf-8")
        self.assertIn("ApplicationBuilder", source)
        self.assertNotIn("add_handler", source)
        self.assertNotIn("CallbackQueryHandler", source)
        self.assertNotIn("MessageHandler", source)
        self.assertNotIn("CommandHandler", source)
        self.assertIn("no_new_handlers=true", source)

    def test_watermark_action_forces_fresh_upload_and_removes_reply_keyboard(self) -> None:
        source = Path("neyrobot_prod/retouch_v261_batch.py").read_text(encoding="utf-8")
        self.assertIn('str(submode or "") == "work_watermark"', source)
        self.assertIn("cached_photo_bypassed=true", source)
        self.assertIn("_FORCE_FRESH_UNTIL", source)
        self.assertIn("ReplyKeyboardRemove", source)
        self.assertIn("keyboard_removed=true", source)

    def test_batch_accepts_twenty_and_processes_sequentially(self) -> None:
        source = Path("neyrobot_prod/retouch_v261_batch.py").read_text(encoding="utf-8")
        self.assertIn("_MAX_BATCH_IMAGES = 20", source)
        self.assertIn("_BATCH_DEBOUNCE_S = 3.0", source)
        self.assertIn("while True:", source)
        self.assertIn("await original_start(item[\"update\"], context, raw, item[\"instruction\"])", source)
        self.assertIn("sequential=true", source)
        self.assertIn("Принято изображений", source)

    def test_media_group_context_is_bound_by_shared_user_data(self) -> None:
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn('context.user_data.get("_retouch_v261_uid")', source)
        self.assertIn("_BATCH_STATES.get(uid)", source)
        self.assertIn('state["context"] = context', source)
        self.assertNotIn("state.get(\"context\") is context", source)

    def test_delivery_timeout_does_not_create_false_provider_failure(self) -> None:
        source = Path("neyrobot_prod/retouch_v261_batch.py").read_text(encoding="utf-8")
        self.assertIn("_TELEGRAM_SEND_TIMEOUT_S = 180.0", source)
        self.assertIn("read_timeout=_TELEGRAM_SEND_TIMEOUT_S", source)
        self.assertIn("write_timeout=_TELEGRAM_SEND_TIMEOUT_S", source)
        self.assertIn("status=timeout_ambiguous attempt=1", source)
        self.assertIn("suppress_false_provider_error=true", source)
        self.assertIn("return True", source)

    def test_multi_result_batch_offers_safe_zip(self) -> None:
        source = Path("neyrobot_prod/retouch_v261_batch.py").read_text(encoding="utf-8")
        self.assertIn("_ZIP_MAX_BYTES = 45 * 1024 * 1024", source)
        self.assertIn("zipfile.ZipFile", source)
        self.assertIn("compression=zipfile.ZIP_STORED", source)
        self.assertIn('filename="retouched_batch.zip"', source)

    def test_package_arms_retouch_overlay(self) -> None:
        source = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
        self.assertIn("retouch_v261_batch", source)
        self.assertIn("_retouch_v261_module.install()", source)


if __name__ == "__main__":
    unittest.main()
