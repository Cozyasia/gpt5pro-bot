import unittest
import numpy as np
from neyrobot_prod.v265_canonical_texture import sample_owned_texture


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
