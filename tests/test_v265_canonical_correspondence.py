import unittest
import json
import numpy as np
from neyrobot_prod.v265_canonical_correspondence import SourceRays, correspondence


class CorrespondenceTests(unittest.TestCase):
    def test_subpixel_triangle_is_visible_without_source_pixel_sample(self):
        source = np.array([[0.01, 0.01, 0], [0.09, 0.01, 0], [0.01, 0.09, 0]])
        final = np.array([[0, 0, 0], [8, 0, 0], [0, 8, 0]])
        r = correspondence(
            source, final, np.array([[0, 1, 2]]), [0, 0, 8, 8], max_side=8
        )
        self.assertGreater(r["sample_count"], 0)
        self.assertEqual(r["sample_count"], r["mesh_visible_samples"])
        self.assertTrue(np.all(r["source_xy"][r["mesh_visible"]] < 0.1))
        self.assertFalse(r["render_prequalified"])
        json.dumps(
            {k: v for k, v in r.items() if k not in ("source_xy", "mesh_visible")},
            allow_nan=False,
        )

    def test_occluded_source_cannot_supply_newly_visible_target_surface(self):
        source = np.array(
            [[0, 0, 0], [8, 0, 0], [0, 8, 0], [0, 0, 2], [8, 0, 2], [0, 8, 2]]
        )
        final = source.copy()
        final[:3, 2] = 3
        r = correspondence(
            source, final, np.array([[0, 1, 2], [3, 4, 5]]), [0, 0, 8, 8], max_side=8
        )
        self.assertEqual(r["mesh_visible_samples"], 0)
        self.assertGreater(r["mesh_occluded_or_unknown_samples"], 0)

    def test_identity_correspondence_and_depth_interpolation(self):
        p = np.array([[0, 0, 0], [8, 0, 8], [0, 8, 0]])
        rays = SourceRays(p, np.array([[0, 1, 2]]))
        depth, pairs = rays.front_depth([[1, 1], [2, 2], [10, 10]])
        np.testing.assert_allclose(depth[:2], [1, 2])
        self.assertEqual(depth[2], -np.inf)
        self.assertLessEqual(pairs, 128 * 512)
        r = correspondence(p, p, np.array([[0, 1, 2]]), [0, 0, 8, 8], max_side=8)
        np.testing.assert_allclose(r["source_xy"][1, 1], [1.5, 1.5])
        self.assertEqual(r["sample_count"], r["mesh_visible_samples"])

    def test_index_resource_bound_fails_closed(self):
        p = np.array([[0, 0, 0], [8, 0, 0], [0, 8, 0]])
        with self.assertRaisesRegex(ValueError, "resource bound"):
            SourceRays(p, np.array([[0, 1, 2]]), max_links=1)
