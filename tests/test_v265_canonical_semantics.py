import unittest
import numpy as np
from neyrobot_prod.v265_canonical_semantics import (
    REGIONS,
    accessory_edge_hypothesis,
    accessory_policy,
    completeness_report,
    semantic_region_map,
)


def landmarks():
    p = np.tile([50.0, 50.0], (68, 1))
    a = np.linspace(0, np.pi, 17)
    p[:17] = np.c_[50 - 35 * np.cos(a), 48 + 42 * np.sin(a)]
    p[17:27] = np.c_[np.linspace(25, 75, 10), np.full(10, 32)]
    p[27:36] = np.c_[np.linspace(47, 53, 9), np.linspace(38, 62, 9)]
    for start, cx in ((36, 35), (42, 65)):
        t = np.linspace(0, 2 * np.pi, 6, endpoint=False)
        p[start:start + 6] = np.c_[cx + 8 * np.cos(t), 46 + 3 * np.sin(t)]
    t = np.linspace(0, 2 * np.pi, 20, endpoint=False)
    p[48:68] = np.c_[50 + 16 * np.cos(t), 70 + 6 * np.sin(t)]
    return p


class SemanticOwnershipTests(unittest.TestCase):
    def test_face_support_is_exhaustively_classified(self):
        face = np.ones((100, 100), bool)
        labels = semantic_region_map((100, 100), landmarks(), face)
        names = {REGIONS[i] for i in np.unique(labels)}
        for name in ("forehead", "eyes_eyelids", "nose", "cheeks", "jaw", "chin"):
            self.assertIn(name, names)
        self.assertNotIn("unknown", names)

    def test_glasses_hypothesis_and_explicit_product_policy(self):
        image = np.full((100, 100, 3), 210, np.uint8)
        image[40:52, 25:45] = 40
        image[40:52, 55:75] = 40
        image[45:47, 45:55] = 40
        evidence = accessory_edge_hypothesis(image, landmarks())
        self.assertTrue(evidence["present"])
        self.assertFalse(evidence["segmentation_verified"])
        self.assertEqual(
            accessory_policy(True, False)["action"], "controlled_failure"
        )
        self.assertEqual(
            accessory_policy(False, True)["action"], "retain_target_accessory_layer"
        )

    def test_accessory_working_buffers_are_landmark_bounded(self):
        image = np.full((3072, 2458, 3), 210, np.uint8)
        p = landmarks() + [1200, 500]
        evidence = accessory_edge_hypothesis(image, p)
        x0, y0, x1, y1 = evidence["working_roi"]
        self.assertLess((x1 - x0) * (y1 - y0), image.shape[0] * image.shape[1] // 100)
        self.assertEqual(evidence["mask"].shape, image.shape[:2])

    def test_completeness_names_every_missing_critical_region(self):
        face = np.ones((100, 100), bool)
        labels = semantic_region_map((100, 100), landmarks(), face)
        source = np.ones_like(face)
        expression = np.zeros_like(face)
        source[labels == REGIONS.index("mouth_interior")] = False
        incomplete = completeness_report(labels, source, expression)
        self.assertIn("mouth_interior", incomplete["critical_target_unresolved"])
        self.assertFalse(incomplete["identity_complete"])
        expression[labels == REGIONS.index("mouth_interior")] = True
        complete = completeness_report(labels, source, expression)
        self.assertTrue(complete["identity_complete"])


if __name__ == "__main__":
    unittest.main()
