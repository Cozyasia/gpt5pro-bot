# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chat_provider_v136 as chat


class ChatProviderV136Tests(unittest.TestCase):
    def test_labels_and_callbacks_are_explicit(self):
        source = Path("chat_provider_v136.py").read_text(encoding="utf-8")
        self.assertIn("Чат с GPT", source)
        self.assertIn("Чат с Gemini", source)
        self.assertIn("chatprov:gpt", source)
        self.assertIn("chatprov:gemini", source)
        self.assertIn("💬 Мои чаты", source)

    def test_current_stable_gemini_chat_models_are_defaults(self):
        with patch.dict(os.environ, {
            "GEMINI_CHAT_MODEL": "gemini-3.5-flash",
            "GEMINI_CHAT_FALLBACK_MODEL": "gemini-3.1-flash-lite",
        }, clear=False):
            self.assertEqual(chat._gemini_models(), ["gemini-3.5-flash", "gemini-3.1-flash-lite"])

    def test_provider_is_persistent_and_scoped(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"DB_PATH": f"{tmp}/test.sqlite3"}, clear=False):
            self.assertEqual(chat.set_provider(1, 2, "gemini", "conversation:7"), "gemini")
            self.assertEqual(chat.get_provider(1, 2, "conversation:7"), "gemini")
            self.assertEqual(chat.get_provider(1, 2, "conversation:8"), "gpt")
            self.assertEqual(chat.set_provider(1, 2, "gpt", "conversation:7"), "gpt")
            self.assertEqual(chat.get_provider(1, 2, "conversation:7"), "gpt")

    def test_histories_are_separate_by_provider(self):
        source = Path("chat_provider_v136.py").read_text(encoding="utf-8")
        self.assertIn("chat_provider_messages", source)
        self.assertIn("AND provider=?", source)
        self.assertIn("_history(uid, cid, scope, \"gemini\"", source)
        self.assertIn("_history(user_id, chat_id, scope, \"gpt\"", source)

    def test_runtime_waits_for_official_gpt_router(self):
        source = Path("chat_provider_v136.py").read_text(encoding="utf-8")
        self.assertIn("GENERAL_TEXT_ROUTER_VERSION", source)
        self.assertIn("CHAT_PROVIDER_GEMINI_FALLBACK_GPT", source)


if __name__ == "__main__":
    unittest.main()
