"""Geometry qualification with known cameras, not human identity acceptance."""

import unittest
import numpy as np
from neyrobot_prod import v265_shape_lab as s


def fixture(yaw=0.0):
    k = np.array([[600.0, 0, 300], [0, 600, 300], [0, 0, 1]])
    cam = (k, np.array([0.08, yaw, 0.04]), np.array([0.0, 0.0, 5.0]))
    return s.project(s.template68(), cam), cam


class ShapeLabTests(unittest.TestCase):
    def test_known_pose_ray_reconstruction(self):
        for yaw in (-0.3, 0, 0.3):
            uv, cam = fixture(yaw)
            estimated = s.camera(uv, (600, 600))
            np.testing.assert_allclose(
                s.lift_residual(uv, estimated), s.template68(), atol=1e-7
            )

    def test_source_residual_projects_under_target_pose(self):
        uv, sc = fixture(-0.15)
        target, tc = fixture(0.25)
        shape = s.template68().copy()
        # Alter jaw identity only, leaving pose-estimation anchors untouched.
        shape[4:13, 0] *= 1.08
        shape[7:10, 1] += 0.035
        source = s.project(shape, sc)
        actual, _ = s.pose_projected_source(source, target, (600, 600), (600, 600))
        expected = s.project(shape, tc)
        np.testing.assert_allclose(actual, expected, atol=3e-5)
        self.assertGreater(np.max(abs(actual - source)), 1.0)

    def test_expression_preserves_width_and_adapts_opening(self):
        p, _ = fixture()
        q = p.copy()
        q[[65, 66, 67, 55, 56, 57, 58, 59], 1] += 3
        q[[61, 62, 63, 49, 50, 51, 52, 53], 1] -= 3
        out = s.expression_mouth(p, q)
        self.assertAlmostEqual(
            np.linalg.norm(out[54] - out[48]), np.linalg.norm(p[54] - p[48]), places=4
        )
        self.assertGreater(
            np.linalg.norm(out[66] - out[62]), np.linalg.norm(p[66] - p[62])
        )
        np.testing.assert_allclose(out[:48], p[:48], atol=2e-5)

    def test_tps_identity_and_exact_correspondence(self):
        p, _ = fixture()
        y, x = np.mgrid[:600, :600]
        im = np.stack([x % 251, y % 251, (x + y) % 251], 2).astype("uint8")
        same, error, _ = s.tps_inverse_roi(im, p, p, (0, 0, 600, 600), 250)
        np.testing.assert_array_equal(same, im)
        q = p.copy()
        q[4:13, 0] += np.linspace(-2, 2, 9)
        _, error, _ = s.tps_inverse_roi(im, p, q, (0, 0, 600, 600), 250)
        self.assertLess(error, 1e-7)

    def test_configuration_sees_interregion_shift(self):
        p, _ = fixture()
        q = p.copy()
        q[48:68, 1] += 6
        before, after = s.configuration(p), s.configuration(q)
        self.assertAlmostEqual(before["mouth_width"], after["mouth_width"])
        self.assertNotAlmostEqual(before["mouth_to_chin"], after["mouth_to_chin"])
        self.assertNotAlmostEqual(before["nose_to_mouth"], after["nose_to_mouth"])

    def test_invalid_evidence_rejected(self):
        p, _ = fixture()
        p[1] = np.nan
        with self.assertRaises(ValueError):
            s.camera(p, (600, 600))
        p, _ = fixture()
        p[48] = p[54]
        with self.assertRaises(ValueError):
            s.expression_mouth(p, p)

    def test_offline_geometry_patch_restores_on_exception(self):
        from neyrobot_prod import dense68_engine_v265 as e
        from neyrobot_prod.v265_transfer_lab import variant

        p, _ = fixture()
        originals = (
            e._dense_deform_local_roi,
            e.v263._desired_identity_geometry,
            e._landmark_anatomy_mask,
        )
        with self.assertRaises(RuntimeError):
            with variant(
                "F_jaw_shape",
                p,
                p,
                p,
                250,
                source_shape=(600, 600),
                target_shape=(600, 600),
            ):
                raise RuntimeError("cancel")
        self.assertEqual(
            originals,
            (
                e._dense_deform_local_roi,
                e.v263._desired_identity_geometry,
                e._landmark_anatomy_mask,
            ),
        )


class EyeProfileTests(unittest.TestCase):
    def test_central_displacement_with_unchanged_landmarks_and_gain(self):
        from tests.test_v265_source_fidelity import points
        from neyrobot_prod.v265_eye_fidelity_lab import descriptors, compare

        p = points()
        y, x = np.mgrid[:400, :320]
        image = np.full((400, 320, 3), 160, np.uint8)
        for cx in (80, 240):
            image[((x - cx) / 26) ** 2 + ((y - 120) / 9) ** 2 < 1] = 220
            image[(x - cx) ** 2 + (y - 120) ** 2 < 36] = 30
        changed = image.copy()
        changed[(x - 80) ** 2 + (y - 120) ** 2 < 36] = 220
        changed[(x - 86) ** 2 + (y - 120) ** 2 < 36] = 30
        base = descriptors(image, p, include_profiles=True)
        moved = compare(base, descriptors(changed, p, include_profiles=True))
        benign = compare(
            base,
            descriptors((image * 0.8 + 12).astype("uint8"), p, include_profiles=True),
        )
        self.assertGreater(moved["left_profile"], benign["left_profile"] + 0.01)
        self.assertLess(moved["right_profile"], 1e-7)


class OrthographicShapeTests(unittest.TestCase):
    def test_known_weak_perspective_shape_and_canvas_translation(self):
        import cv2

        shape = s.template68().copy()
        source_rot = cv2.Rodrigues(np.array([0.1, -0.15, 0.04]))[0]
        target_rot = cv2.Rodrigues(np.array([-0.1, 0.2, -0.08]))[0]
        shape[4:13, 0] *= 1.08
        shape[7:10, 1] += 0.03
        source = 180 * (shape @ source_rot[:2].T) + [400, 600]
        target = 210 * (s.template68() @ target_rot[:2].T) + [250, 300]
        expected = 210 * (shape @ target_rot[:2].T) + [250, 300]
        actual, _ = s.orthographic_projected_source(source, target)
        np.testing.assert_allclose(actual, expected, atol=4e-5)
        shifted, _ = s.orthographic_projected_source(
            source + [1500, 900], target + [-50, 800]
        )
        np.testing.assert_allclose(shifted, actual + [-50, 800], atol=1e-4)
