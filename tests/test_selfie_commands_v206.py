# -*- coding: utf-8 -*-
from __future__ import annotations

import types
import unittest
from pathlib import Path

from telegram.ext import ApplicationBuilder, CommandHandler

from neyrobot_prod import selfie_commands_v206 as v206
from neyrobot_prod import selfie_storage_v205 as v205


class SelfieCommandsV206Tests(unittest.TestCase):
    def test_routes_are_registered_before_legacy_handlers(self):
        self.assertLess(v206.VERSION_HANDLER_GROUP, -1200)
        self.assertLess(v206.COMMAND_HANDLER_GROUP, -1000)
        self.assertLess(v206.RAW_COMMAND_GROUP, -1000)

    def test_sitecustomize_installs_commands_before_main(self):
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("selfie_commands_v206", source)
        self.assertIn("install_selfie_commands()", source)

    def test_guaranteed_main_bootstrap_installs_commands_on_render(self):
        source = Path("secret_loader.py").read_text(encoding="utf-8")
        self.assertIn("_SELFIE_COMMANDS_V206_PATCHED", source)
        self.assertIn("from neyrobot_prod.selfie_commands_v206", source)
        self.assertIn("install_selfie_commands_v206()", source)

    def test_admin_policy_accepts_normal_two_argument_unlimited_checker(self):
        v206._install_authorization_owner()
        runtime = types.SimpleNamespace(
            OWNER_ID=0,
            is_unlimited=lambda uid, username: uid == 777 and username == "owner",
        )
        user = types.SimpleNamespace(id=777, username="owner")
        self.assertTrue(v205._authorized(runtime, user))

    def test_builder_contains_both_service_commands_at_final_priority(self):
        v206.install_builder_hook()
        app = ApplicationBuilder().token("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abc").build()
        handlers = app.handlers.get(v206.COMMAND_HANDLER_GROUP, [])
        commands: set[str] = set()
        for handler in handlers:
            if isinstance(handler, CommandHandler):
                commands.update(handler.commands)
        self.assertIn("selfie_admin", commands)
        self.assertIn("diag_selfie_storage", commands)
        self.assertTrue(getattr(app, "_selfie_commands_v206_bound", False))

    def test_raw_command_fallback_accepts_bot_username_suffix(self):
        self.assertIsNotNone(v206._COMMAND_RE.match("/selfie_admin@NeyroBot"))
        self.assertIsNotNone(v206._COMMAND_RE.match("/diag_selfie_storage"))


if __name__ == "__main__":
    unittest.main()
