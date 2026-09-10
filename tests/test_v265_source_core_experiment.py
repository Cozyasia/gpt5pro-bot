"""Offline compositor ablation invariants, not human/production acceptance."""

import unittest
import cv2
import numpy as np
from neyrobot_prod import dense68_engine_v265 as engine


class SourceCoreExperimentTests(unittest.TestCase):
    def test_identity_operator_and_outside_mask_at_production_roi_size(self):
        h, w = 800, 700
        y, x = np.mgrid[:h, :w]
        a = np.repeat(
            (120 + 30 * np.sin(x / 19) + 20 * np.cos(y / 23))[:, :, None], 3, 2
        ).astype(np.uint8)
        mask = np.zeros((h, w), np.uint8)
        cv2.rectangle(mask, (80, 80), (620, 720), 255, -1)
        b = engine._source_core_compose_roi_experiment(a, a, mask, 600)
        self.assertTrue(np.array_equal(b[mask == 0], a[mask == 0]))
        self.assertLess(np.abs(b.astype(float) - a).max(), 5)

    def test_target_facial_frequency_does_not_survive_in_source_core(self):
        h, w = 400, 400
        y, x = np.mgrid[:h, :w]
        source = np.repeat((120 + 15 * np.sin(y / 20))[:, :, None], 3, 2).astype(
            np.uint8
        )
        target = np.repeat((120 + 35 * np.sin(x / 6))[:, :, None], 3, 2).astype(
            np.uint8
        )
        mask = np.full((h, w), 255, np.uint8)
        mask[:20] = 0
        mask[-20:] = 0
        mask[:, :20] = 0
        mask[:, -20:] = 0
        out = engine._source_core_compose_roi_experiment(source, target, mask, 400)
        source_dx = np.diff(out[80:320, 80:320, 0].astype(float), axis=1)
        self.assertLess(np.sqrt(np.mean(source_dx**2)), 1)
        self.assertGreater(np.std(target[80:320, 80:320, 0].astype(float)), 20)
        self.assertTrue(np.array_equal(out[mask == 0], target[mask == 0]))

    def test_dense_support_stops_at_chin_and_person_b_firewall(self):
        p = np.zeros((68, 2), np.float32)
        angle = np.linspace(0, np.pi, 17)
        p[:17] = np.column_stack([200 - 120 * np.cos(angle), 150 + 180 * np.sin(angle)])
        p[17:27] = np.column_stack([np.linspace(100, 300, 10), np.full(10, 120)])
        mask = engine._dense_anatomy_mask_experiment((500, 600, 3), p, 330)
        self.assertTrue(mask[250, 200] > 0)
        self.assertEqual(mask[331:].max(), 0)
        self.assertEqual(mask[:, 330:].max(), 0)
