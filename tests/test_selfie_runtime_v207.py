# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path

from neyrobot_prod import selfie_runtime_v207 as v207


class SelfieRuntimeV207Tests(unittest.TestCase):
    def test_public_version_is_v207(self):
        self.assertEqual(v207.VERSION, "v207-selfie-canonical-runtime-2026-07-25")

    def test_model_policy_activates_v207(self):
        source = Path("model_policy_v115.py").read_text(encoding="utf-8")
        self.assertIn("_install_selfie_runtime_v207()", source)
        self.assertIn("selfie_runtime_v207", source)

    def test_legacy_v203_worker_is_neutralized(self):
        source = Path("neyrobot_prod/selfie_runtime_v207.py").read_text(encoding="utf-8")
        self.assertIn("legacy_v203.patch = no_op_patch", source)
        self.assertIn("generator_v204.patch()", source)

    def test_service_commands_have_visible_error_replies(self):
        source = Path("neyrobot_prod/selfie_runtime_v207.py").read_text(encoding="utf-8")
        self.assertIn("Сервисное меню AI-селфи не открылось", source)
        self.assertIn("Диагностика хранилища не выполнена", source)

    def test_storage_has_persistent_and_safe_fallback_paths(self):
        self.assertEqual(str(v207.PERSISTENT_ROOT), "/data/celebrity_selfie")
        self.assertEqual(str(v207.FALLBACK_ROOT), "/tmp/celebrity_selfie")


if __name__ == "__main__":
    unittest.main()
