# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path

from neyrobot_prod import versioning


class VersionActiveSelfieRuntimeTests(unittest.TestCase):
    def test_runtime_owner_is_separate_from_package_version(self) -> None:
        active, v263_status = versioning._active_selfie_runtime()
        self.assertEqual(active, "v262")
        self.assertEqual(v263_status, "experimental / not production accepted")

    def test_public_version_output_has_unambiguous_runtime_marker(self) -> None:
        source = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn("Production AI-селфи runtime", source)
        self.assertIn("последний фактический transfer", source)
        self.assertIn("Код/пакет", source)


if __name__ == "__main__":
    unittest.main()
