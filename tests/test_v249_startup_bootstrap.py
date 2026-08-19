# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest


class V249StartupBootstrapTests(unittest.TestCase):
    def test_sitecustomize_is_loaded_at_python_startup(self) -> None:
        self.assertIn(
            "sitecustomize",
            sys.modules,
            "sitecustomize.py was not auto-imported; production selfie overlays would remain inactive",
        )

    def test_final_selfie_builder_owner_is_armed(self) -> None:
        from telegram.ext import ApplicationBuilder

        self.assertTrue(
            getattr(ApplicationBuilder, "_neyrobot_v246_final_builder_lock", False),
            "V246/V247/V248 final builder owner was not installed before main handler registration",
        )


if __name__ == "__main__":
    unittest.main()
