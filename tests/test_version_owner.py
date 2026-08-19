# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect
import types
import unittest
from pathlib import Path

from telegram.ext import ApplicationHandlerStop

from neyrobot_prod import VERSION
from neyrobot_prod.versioning import VERSION_HANDLER_GROUP, command


class FakeMessage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.calls.append((text, kwargs))


class VersionOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_version_uses_current_package_release_and_stops_legacy_handler(self) -> None:
        message = FakeMessage()
        update = types.SimpleNamespace(effective_message=message)

        with self.assertRaises(ApplicationHandlerStop):
            await command(update, types.SimpleNamespace())

        self.assertEqual(len(message.calls), 1)
        self.assertTrue(VERSION.startswith("v"))
        self.assertIn(VERSION, message.calls[0][0])

    def test_version_handler_has_priority_over_all_legacy_groups(self) -> None:
        self.assertLess(VERSION_HANDLER_GROUP, -100)

    def test_command_reads_package_version_not_mutable_runtime_patch_version(self) -> None:
        source = inspect.getsource(command)
        self.assertIn("{VERSION}", source)
        self.assertNotIn("PATCH_VERSION", source)

    def test_sitecustomize_activates_the_canonical_owner(self) -> None:
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("install_version_owner()", source)


if __name__ == "__main__":
    unittest.main()
