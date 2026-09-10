import unittest
import numpy as np
from neyrobot_prod.v265_canonical_texture import (
    composite_owned_texture,
    sample_owned_texture,
)


class TextureTests(unittest.TestCase):
    def test_identity_sampling_has_no_half_pixel_blur(self):
        image = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)
        y, x = np.indices((2, 2))
        xy = np.stack((x + 0.5, y + 0.5), axis=2)
        yes = np.ones((2, 2), bool)
        result = sample_owned_texture(image, xy, yes, yes, yes)
        np.testing.assert_array_equal(result["texture"], image)
        self.assertEqual(result["available_samples"], 4)
        self.assertFalse(result["render_prequalified"])

    def test_bilinear_footprint_cannot_leak_protected_accessory(self):
        image = np.zeros((2, 2, 3), np.uint8)
        image[1, 1] = 255
        source = np.ones((2, 2), bool)
        source[1, 1] = False
        xy = np.array([[[1.0, 1.0]]])
        yes = np.ones((1, 1), bool)
        result = sample_owned_texture(image, xy, yes, source, yes)
        self.assertEqual(result["available_samples"], 0)
        self.assertFalse(result["texture"].any())

    def test_target_firewall_and_occlusion_block_samples(self):
        image = np.full((2, 2, 3), 200, np.uint8)
        xy = np.full((1, 2, 2), 0.5)
        result = sample_owned_texture(
            image,
            xy,
            np.array([[True, False]]),
            np.ones((2, 2), bool),
            np.array([[False, True]]),
        )
        self.assertEqual(result["available_samples"], 0)

    def test_invalid_coordinates_do_not_clamp_to_edge(self):
        image = np.full((2, 2, 3), 200, np.uint8)
        xy = np.array([[[np.nan, 1], [1e30, 1], [-1, 1], [2, 1]]])
        result = sample_owned_texture(
            image,
            xy,
            np.ones((1, 4), bool),
            np.ones((2, 2), bool),
            np.ones((1, 4), bool),
        )
        self.assertEqual(result["available_samples"], 0)

    def test_unknown_ownership_is_not_implicitly_accepted(self):
        with self.assertRaises(ValueError):
            sample_owned_texture(
                np.zeros((2, 2, 3), np.uint8),
                np.zeros((1, 1, 2)),
                np.ones((1, 1), bool),
                None,
                np.ones((1, 1), bool),
            )


class TextureCorrespondenceTests(unittest.TestCase):
    def test_rotated_image_mesh_maps_exact_source_pixels(self):
        from neyrobot_prod.v265_canonical_texture import (
            pixel_centres_to_mesh_boundaries,
        )
        from neyrobot_prod.v265_canonical_correspondence import correspondence

        source = np.array(
            [[-0.5, -0.5, 0], [2.5, -0.5, 0], [2.5, 2.5, 0], [-0.5, 2.5, 0]], np.float32
        )
        final = source.copy()
        final[:, 0] = 2 - source[:, 1]
        final[:, 1] = source[:, 0]
        tri = np.array([[0, 1, 2], [0, 2, 3]])
        mapping = correspondence(
            pixel_centres_to_mesh_boundaries(source),
            pixel_centres_to_mesh_boundaries(final),
            tri,
            [0, 0, 3, 3],
            max_side=3,
        )
        image = np.arange(27, dtype=np.uint8).reshape(3, 3, 3)
        yes = np.ones((3, 3), bool)
        result = sample_owned_texture(
            image, mapping["source_xy"], mapping["mesh_visible"], yes, yes
        )
        np.testing.assert_array_equal(result["texture"], np.rot90(image, -1))
        self.assertEqual(result["available_samples"], 9)
        np.testing.assert_array_equal(source[0], [-0.5, -0.5, 0])


class OwnershipCompositeTests(unittest.TestCase):
    def test_unknown_accessory_and_mouth_pixels_retain_target_bytes(self):
        source = np.full((3, 4, 3), [10, 20, 30], np.uint8)
        target = np.full((3, 4, 3), [200, 210, 220], np.uint8)
        y, x = np.indices((3, 4))
        xy = np.stack((x + 0.5, y + 0.5), axis=2)
        source_owned = np.ones((3, 4), bool)
        target_owned = np.ones((3, 4), bool)
        # Stand-ins for externally established glasses/eye and mouth ownership.
        target_owned[0, 1:3] = False
        target_owned[2, 1:3] = False
        sampled = sample_owned_texture(
            source, xy, np.ones((3, 4), bool), source_owned, target_owned
        )
        result = composite_owned_texture(target, sampled)
        np.testing.assert_array_equal(result["image"][target_owned], source[target_owned])
        np.testing.assert_array_equal(result["image"][~target_owned], target[~target_owned])
        self.assertEqual(result["source_replaced_pixels"], 8)
        self.assertEqual(result["target_retained_pixels"], 4)
        self.assertTrue(result["target_retained_bit_exact"])
        self.assertFalse(result["identity_complete"])

    def test_compositor_rejects_untyped_or_mismatched_evidence(self):
        target = np.zeros((2, 2, 3), np.uint8)
        with self.assertRaises(ValueError):
            composite_owned_texture(target, {})
        with self.assertRaises(ValueError):
            composite_owned_texture(
                target,
                {
                    "texture": target,
                    "available": np.ones((2, 2), np.uint8),
                    "render_prequalified": False,
                },
            )
