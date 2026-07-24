# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import secret_loader


class SecretLoaderStorageFallbackTests(unittest.TestCase):
    def test_unwritable_requested_path_is_replaced_with_writable_fallback(self):
        var_name = "NEYROBOT_TEST_STORAGE_DIR"
        previous = os.environ.get(var_name)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                blocker = root / "not-a-directory"
                blocker.write_text("blocked", encoding="utf-8")
                requested = blocker / "child"
                fallback = root / "fallback"
                os.environ[var_name] = str(requested)

                selected = secret_loader._ensure_writable_runtime_dir(
                    var_name,
                    str(requested),
                    str(fallback),
                )

                self.assertEqual(str(fallback), selected)
                self.assertEqual(str(fallback), os.environ[var_name])
                self.assertTrue(fallback.is_dir())
                probe = fallback / "probe.txt"
                probe.write_text("ok", encoding="utf-8")
                self.assertEqual("ok", probe.read_text(encoding="utf-8"))
        finally:
            if previous is None:
                os.environ.pop(var_name, None)
            else:
                os.environ[var_name] = previous

    def test_explicit_bootstrap_contains_celebrity_storage_resolution(self):
        source = Path(secret_loader.__file__).read_text(encoding="utf-8")
        call = source.index('"CELEBRITY_SELFIE_DATA_DIR"')
        bootstrapped = source.index("_BOOTSTRAPPED = True", call)
        self.assertLess(call, bootstrapped)
        self.assertIn('"/tmp/neyrobot/celebrity_selfie"', source)


if __name__ == "__main__":
    unittest.main()
