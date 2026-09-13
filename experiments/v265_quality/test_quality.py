import unittest
import numpy as np
from experiments.v265_quality.factory import surface, anatomy, expression


class FactoryTests(unittest.TestCase):
    def test_separate_controls_and_original_resolution(self):
        for resolution, count in [(0, 2009), (1, 5265)]:
            s = surface(resolution)
            self.assertEqual(len(s["neutral"]), count)
            c = np.linspace(-0.8, 0.8, 24)
            r = np.linspace(-1, 1, 12)
            n = anatomy(s, c, r)
            before = n.copy()
            e = np.ones(8)
            posed = expression(s, n, e)
            np.testing.assert_array_equal(n, before)
            np.testing.assert_allclose(
                posed - n, np.einsum("k,knc->nc", e, s["expression"]), atol=1e-9
            )
            np.testing.assert_allclose(expression(s, n, np.zeros(8)), n)

    def test_residual_orthogonal_bounded(self):
        s = surface()
        r = s["residual"].reshape(12, -1)
        e = s["expression"].reshape(8, -1)
        self.assertLess(float(abs(r @ e.T).max()), 1e-10)
        self.assertLess(
            float(np.linalg.norm(s["residual"], axis=-1).sum(0).max()), 0.003
        )

    def test_all_parameters_act(self):
        s = surface()
        self.assertTrue(
            (np.linalg.norm(s["basis"].reshape(24, -1), axis=1) > 1e-6).all()
        )
        self.assertEqual(len(np.unique(s["regions"])), 7)

    def test_continuous_identity_fields_do_not_fold_stress_meshes(self):
        from experiments.v265_prior.evaluate import topology_metrics

        for level in (0, 1):
            s = surface(level)
            rng = np.random.default_rng(990)
            for _ in range(32):
                n = anatomy(s, rng.uniform(-1, 1, 24), rng.uniform(-1, 1, 12))
                v = expression(s, n, rng.uniform(-1, 1, 8))
                self.assertEqual(
                    topology_metrics(v, s["neutral"], s["triangles"])[
                        "orientation_failures"
                    ],
                    0,
                )

    def test_no_repeated_or_degenerate_triangles(self):
        for resolution in (0, 1):
            s = surface(resolution)
            t = s["triangles"]
            v = s["neutral"][t]
            self.assertEqual(len(np.unique(np.sort(t, axis=1), axis=0)), len(t))
            self.assertGreater(
                np.linalg.norm(
                    np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1
                ).min(),
                1e-8,
            )


if __name__ == "__main__":
    unittest.main()
