"""Occlusion and projection changes must not masquerade as valid texture maps."""

import unittest
import numpy as np
from neyrobot_prod.v265_canonical_visibility import rasterize, visibility_audit


class VisibilityTests(unittest.TestCase):
    def test_near_surface_owns_overlap_independent_of_submission_order(self):
        p = np.array(
            [[0, 0, 0], [8, 0, 0], [0, 8, 0], [0, 0, 2], [8, 0, 2], [0, 8, 2]],
            dtype=float,
        )
        for tri, winner in [
            (np.array([[0, 1, 2], [3, 4, 5]]), 1),
            (np.array([[3, 4, 5], [0, 1, 2]]), 0),
        ]:
            r = rasterize(p, tri, [0, 0, 8, 8], max_side=8)
            self.assertEqual(r["owner"][1, 1], winner)
            self.assertEqual(r["depth"][1, 1], 2)
            self.assertEqual(r["visible_triangles"].sum(), 1)

    def test_projection_orientation_change_is_not_itself_an_occlusion_failure(self):
        p = np.array([[0, 0, 0], [8, 0, 0], [0, 8, 0]], dtype=float)
        a = rasterize(p, np.array([[0, 1, 2]]), [0, 0, 8, 8], max_side=8)
        b = rasterize(p, np.array([[0, 2, 1]]), [0, 0, 8, 8], max_side=8)
        np.testing.assert_array_equal(a["owner"], b["owner"])

    def test_newly_visible_surface_reports_missing_source_samples(self):
        p = np.array(
            [[0, 0, 0], [8, 0, 0], [0, 8, 0], [0, 0, 2], [8, 0, 2], [0, 8, 2]],
            dtype=float,
        )
        final = p.copy()
        final[:3, 2] = 3
        r = visibility_audit(
            p, p, final, np.array([[0, 1, 2], [3, 4, 5]]), [0, 0, 8, 8], [0, 0, 8, 8]
        )
        self.assertEqual(r["final_visible_without_source_samples"], 1)
        self.assertFalse(r["full_resolution_correspondence_verified"])

    def test_degenerate_and_outside_triangles_have_no_pixels(self):
        p = np.array(
            [[20, 20, 0], [21, 20, 0], [20, 21, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]]
        )
        r = rasterize(p, np.array([[0, 1, 2], [3, 4, 5]]), [0, 0, 8, 8], max_side=8)
        self.assertTrue((r["owner"] == -1).all())
        self.assertEqual(r["degenerate_triangles"], 1)
        with self.assertRaises(ValueError):
            rasterize(p, np.array([[0, 1, 2]]), [0, 0, 8, 8], max_side=4096)
