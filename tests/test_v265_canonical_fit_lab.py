"""Fit generalization and information isolation; no visual acceptance claims."""

import unittest
import numpy as np
from neyrobot_prod.v265_canonical_lab import CanonicalModel, Parameters, project
from neyrobot_prod.v265_canonical_fit_lab import fit_source_diagnostic, gcv_ridge


class FitTests(unittest.TestCase):
    def fixture(self):
        rng = np.random.default_rng(265)
        model = CanonicalModel(
            rng.normal(size=(68, 3)),
            rng.normal(size=(68, 3, 40)),
            rng.normal(size=(68, 3, 10)),
            [[0, 1, 2]],
            np.arange(68),
        )
        camera = np.c_[np.eye(3), np.zeros(3)].astype(np.float32)
        source = Parameters(camera, np.zeros(40), np.zeros(10))
        truth = Parameters(
            camera, rng.normal(size=40) * 0.05, rng.normal(size=10) * 0.05
        )
        roi = np.array([0, 0, 120, 120])
        obs = project(model.shape(truth.identity, truth.expression), camera, roi)[:, :2]
        return model, source, roi, obs

    def test_heldout_points_do_not_choose_coefficients_or_regularization(self):
        model, source, roi, obs = self.fixture()
        f, a = fit_source_diagnostic(model, source, roi, obs, np.ones(50))
        changed = obs.copy()
        changed[1::2] += 100
        g, b = fit_source_diagnostic(model, source, roi, changed, np.ones(50))
        np.testing.assert_array_equal(f.identity, g.identity)
        np.testing.assert_array_equal(f.expression, g.expression)
        self.assertEqual(a["lambda"], b["lambda"])
        self.assertGreater(b["heldout_after_px"], a["heldout_after_px"])
        self.assertTrue(a["heldout_improved"])
        self.assertFalse(a["identity_expression_separation_proven"])

    def test_ridge_rejects_invalid_or_unobservable_evidence(self):
        for a, y in [
            (np.zeros((4, 2)), np.ones(4)),
            (np.ones((4, 2)), np.ones(3)),
            (np.full((4, 2), np.nan), np.ones(4)),
        ]:
            with self.assertRaises(ValueError):
                gcv_ridge(a, y)

    def test_fit_stays_in_learned_basis_and_fixed_source_camera(self):
        model, source, roi, obs = self.fixture()
        fitted, evidence = fit_source_diagnostic(model, source, roi, obs, np.ones(50))
        np.testing.assert_array_equal(fitted.camera, source.camera)
        self.assertEqual(fitted.identity.shape, (40,))
        self.assertEqual(fitted.expression.shape, (10,))
        self.assertLess(
            evidence["heldout_after_px"], evidence["heldout_before_px"] * 0.01
        )
        self.assertFalse(evidence["production_qualified"])
