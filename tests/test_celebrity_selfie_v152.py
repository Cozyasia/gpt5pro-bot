# -*- coding: utf-8 -*-
import unittest
from pathlib import Path
from unittest.mock import patch

import celebrity_selfie_v152 as v152


class CelebritySelfieV152Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(v152.VERSION, "v152-empty-comet-plate-contract-2026-07-21")

    def test_comet_background_labels_use_empty_scene_contract(self):
        for label in (
            "v150_background_comet_1",
            "v151_background_comet_3",
            "v152_background_comet_2",
        ):
            self.assertTrue(v152._is_empty_scene_label(label))

    def test_empty_scene_with_zero_faces_is_not_sent_to_legacy_one_face_gate(self):
        with patch.object(v152.v151, "_composition_ready_problem", return_value=("", {"faces": 0})) as composition:
            with patch.object(v152.v147, "_background_aware_plate_problem", return_value="legacy-rejected") as legacy:
                problem = v152._composition_aware_plate_problem(b"plate", "v151_background_comet_3")
        self.assertEqual(problem, "")
        composition.assert_called_once_with(b"plate")
        legacy.assert_not_called()

    def test_historical_one_person_labels_keep_strict_validation(self):
        with patch.object(v152.v147, "_background_aware_plate_problem", return_value="strict-result") as legacy:
            problem = v152._composition_aware_plate_problem(b"plate", "v143_plate_openai_1")
        self.assertEqual(problem, "strict-result")
        legacy.assert_called_once_with(b"plate", "v143_plate_openai_1")

    def test_install_patches_the_exact_v143_orchestrator_symbol(self):
        source = Path("celebrity_selfie_v152.py").read_text(encoding="utf-8")
        self.assertIn("v143._plate_problem = _composition_aware_plate_problem", source)
        self.assertIn("v151.install()", source)
        self.assertIn("legacy_one_face_plate_gate", source)

    def test_sitecustomize_loads_v152_after_v151(self):
        source = Path("sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("from celebrity_selfie_v152 import install_early", source)
        self.assertGreater(source.index("from celebrity_selfie_v152"), source.index("from celebrity_selfie_v151"))

    def test_version_contract_points_to_v152(self):
        source = Path("neyrobot_prod/versioning.py").read_text(encoding="utf-8")
        self.assertIn('VERSION = "v152-empty-comet-plate-contract-2026-07-21"', source)
        self.assertIn("from celebrity_selfie_v152 import install as install_v152", source)
        self.assertIn("release_overlay={'v152' if release_overlay else 'load-error'}", source)


if __name__ == "__main__":
    unittest.main()
