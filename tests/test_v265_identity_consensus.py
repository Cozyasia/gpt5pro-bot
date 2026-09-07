# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect
import unittest

from neyrobot_prod.v265_identity_consensus import (
    MorphologyVector,
    SourceSelfEnvelope,
    recognition_consensus_summary,
    source_fidelity_decision,
)

# Non-identifying scalar calibration captured from the visually rejected 2026-09-07
# V265 manual result after normalizing PIPNet-68 by source/candidate eye line.
SOURCE_SELF_ENVELOPE = SourceSelfEnvelope(
    all68=0.0155774602203561,
    inner_face=0.012174027755488306,
    outline=0.030675212953197077,
    mouth=0.015407991606199026,
    central_chin=0.03986960800550141,
)

VISUAL_FAIL_MORPHOLOGY = MorphologyVector(
    all68=0.053860717639106194,
    inner_face=0.0408948255429521,
    outline=0.10960119355573415,
    mouth=0.055732439166699434,
    central_chin=0.13633735676922418,
)


class V265IdentityConsensusAnalysisTests(unittest.TestCase):
    def test_manual_visual_fail_is_rejected_despite_mobileface_pass(self) -> None:
        # Production MobileFace was 0.778736 and the existing landmark-to-desired
        # geometry gate passed. The new source-relative morphology evidence must veto.
        decision = source_fidelity_decision(
            VISUAL_FAIL_MORPHOLOGY,
            SOURCE_SELF_ENVELOPE,
            multiplier=2.0,
        )
        self.assertFalse(decision.passed)
        self.assertIn("all68", decision.failures)
        self.assertIn("inner_face", decision.failures)
        self.assertIn("mouth", decision.failures)
        self.assertIn("central_chin", decision.failures)

    def test_benign_source_repeatability_does_not_false_reject(self) -> None:
        candidate = MorphologyVector(
            all68=SOURCE_SELF_ENVELOPE.all68 * 1.25,
            inner_face=SOURCE_SELF_ENVELOPE.inner_face * 1.25,
            outline=SOURCE_SELF_ENVELOPE.outline * 1.25,
            mouth=SOURCE_SELF_ENVELOPE.mouth * 1.25,
            central_chin=SOURCE_SELF_ENVELOPE.central_chin * 1.25,
        )
        self.assertTrue(
            source_fidelity_decision(
                candidate, SOURCE_SELF_ENVELOPE, multiplier=2.0
            ).passed
        )

    def test_one_regional_excursion_alone_is_not_enough(self) -> None:
        candidate = MorphologyVector(
            all68=SOURCE_SELF_ENVELOPE.all68,
            inner_face=SOURCE_SELF_ENVELOPE.inner_face,
            outline=SOURCE_SELF_ENVELOPE.outline * 2.5,
            mouth=SOURCE_SELF_ENVELOPE.mouth,
            central_chin=SOURCE_SELF_ENVELOPE.central_chin,
        )
        self.assertTrue(
            source_fidelity_decision(
                candidate, SOURCE_SELF_ENVELOPE, multiplier=2.0
            ).passed
        )

    def test_foreign_like_shape_is_rejected(self) -> None:
        foreign = MorphologyVector(
            all68=0.0770086016418923,
            inner_face=0.07954258231421193,
            outline=0.07395772654187584,
            mouth=0.11225082835230807,
            central_chin=0.105331961510219,
        )
        self.assertFalse(
            source_fidelity_decision(
                foreign, SOURCE_SELF_ENVELOPE, multiplier=2.0
            ).passed
        )

    def test_recognition_consensus_is_diagnostic_not_a_hidden_threshold(self) -> None:
        summary = recognition_consensus_summary(
            mobile_pipnet=0.7857398987,
            mobile_yunet=0.7425787449,
            arcface_pipnet=0.7306643724,
            arcface_yunet=0.7093989849,
        )
        self.assertAlmostEqual(summary["consensus_min"], 0.7093989849, places=8)
        self.assertAlmostEqual(
            summary["consensus_mean"],
            (0.7857398987 + 0.7425787449 + 0.7306643724 + 0.7093989849) / 4,
            places=8,
        )
        self.assertEqual(
            set(summary),
            {
                "mobile_pipnet",
                "mobile_yunet",
                "arcface_pipnet",
                "arcface_yunet",
                "consensus_min",
                "consensus_mean",
            },
        )
        for value in (-0.5, 0.0, 0.99):
            scores = recognition_consensus_summary(
                mobile_pipnet=value,
                mobile_yunet=value,
                arcface_pipnet=value,
                arcface_yunet=value,
            )
            self.assertAlmostEqual(scores["consensus_mean"], value)

    def test_invalid_measurements_never_pass(self):
        from dataclasses import replace

        for value in (float("nan"), float("inf"), -0.1):
            self.assertFalse(
                source_fidelity_decision(
                    replace(VISUAL_FAIL_MORPHOLOGY, all68=value), SOURCE_SELF_ENVELOPE
                ).passed
            )
        self.assertFalse(
            source_fidelity_decision(
                VISUAL_FAIL_MORPHOLOGY, replace(SOURCE_SELF_ENVELOPE, mouth=0)
            ).passed
        )
        with self.assertRaises(ValueError):
            source_fidelity_decision(
                VISUAL_FAIL_MORPHOLOGY, SOURCE_SELF_ENVELOPE, multiplier=float("nan")
            )

    def test_analysis_module_does_not_import_or_patch_v265_runtime(self) -> None:
        import neyrobot_prod.v265_identity_consensus as module

        source = inspect.getsource(module)
        self.assertNotIn("install(", source)
        self.assertNotIn("enforce_runtime", source)
        self.assertNotIn("_true_face_transfer", source)
        self.assertNotIn("production_gate =", source)


if __name__ == "__main__":
    unittest.main()
