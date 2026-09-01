# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path

from neyrobot_prod import versioning


class VersionActiveSelfieRuntimeTests(unittest.TestCase):
    def test_runtime_owner_is_v265_single_owner(self) -> None:
        active, runtime_status = versioning._active_selfie_runtime()
        self.assertEqual(active, "v265")
        self.assertEqual(runtime_status, "68-point dense identity · single-owner ROI-only production")

    def test_public_version_output_has_unambiguous_runtime_marker_and_no_v262_fallback_claim(self) -> None:
        source = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn("Production AI-селфи runtime", source)
        self.assertIn("последний фактический transfer", source)
        self.assertIn("Код/пакет", source)
        self.assertIn("Резервный face-transfer: отсутствует", source)
        self.assertNotIn("только аварийный fallback", source)
        self.assertNotIn("selfie_v262_landmark_field_compositor import install", source)


if __name__ == "__main__":
    unittest.main()
