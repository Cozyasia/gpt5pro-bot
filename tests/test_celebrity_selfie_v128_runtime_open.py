# -*- coding: utf-8 -*-
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace

import celebrity_selfie_v128 as feature


class _Message:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kwargs):
        self.sent.append((text, reply_markup))
        return SimpleNamespace()


class _Context:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}
        self.bot = SimpleNamespace()


class CelebritySelfieRuntimeOpenTests(unittest.TestCase):
    def test_session_root_is_actually_writable(self):
        root = feature._writable_session_root()
        self.assertTrue(Path(root).is_dir())
        probe = Path(root) / ".runtime_test"
        probe.write_bytes(b"ok")
        probe.unlink()

    def test_real_open_builds_session_and_upload_prompt(self):
        message = _Message()
        update = SimpleNamespace(
            effective_message=message,
            effective_user=SimpleNamespace(id=123456),
            effective_chat=SimpleNamespace(id=123456),
        )
        context = _Context()

        original_cached = feature.core._cached_photo
        feature.core._cached_photo = lambda _update: None
        try:
            asyncio.run(feature.core._open(update, context))
        finally:
            feature.core._cached_photo = original_cached

        self.assertEqual(len(message.sent), 1)
        self.assertIn("Точное AI-селфи", message.sent[0][0])
        self.assertIsNotNone(message.sent[0][1])
        session = feature.core._session(context, create=False)
        self.assertEqual(session.get("owner"), feature.VERSION)
        self.assertEqual(session.get("state"), "await_user_photo")
        self.assertTrue(feature.core._active(context))


if __name__ == "__main__":
    unittest.main()
