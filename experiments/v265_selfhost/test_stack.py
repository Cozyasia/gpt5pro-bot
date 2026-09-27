import tempfile, unittest
from pathlib import Path
import numpy as np
import torch
from .geometry import project_torch, soft_surface, raster, composite, validate_geometry
from .gate import qualify
from experiments.v265_prior.evaluate import cross_view_protocol


class Stack(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.v = np.array(
            [[-0.1, -0.1, 0], [0.1, -0.1, 0], [0.1, 0.1, 0], [-0.1, 0.1, 0]], np.float32
        )
        self.t = np.array([[0, 1, 2], [0, 2, 3]])
        self.K = np.array([[30, 0, 8], [0, 30, 8], [0, 0, 1]], np.float32)
        self.R = np.eye(3, dtype=np.float32)
        self.trans = np.array([0, 0, 1], np.float32)

    def test_camera_gradient(self):
        v = torch.tensor(self.v[None], requires_grad=True)
        xy, z = project_torch(
            v,
            torch.tensor(self.K[None]),
            torch.tensor(self.R[None]),
            torch.tensor(self.trans[None]),
        )
        xy.square().sum().backward()
        self.assertTrue(torch.isfinite(v.grad).all())
        self.assertGreater(v.grad.abs().sum(), 0)

    def test_soft_visibility_gradient_and_occlusion(self):
        v = torch.tensor(
            np.concatenate([self.v, self.v + np.array([0, 0, 0.2], np.float32)])[None],
            requires_grad=True,
        )
        tri = torch.tensor(np.concatenate([self.t, self.t + 4]))
        mask, depth = soft_surface(
            v,
            tri,
            torch.tensor(self.K[None]),
            torch.tensor(self.R[None]),
            torch.tensor(self.trans[None]),
            16,
        )
        (mask.mean() + depth[:, 7:9, 7:9].mean()).backward()
        self.assertTrue(torch.isfinite(v.grad).all())
        self.assertLess(float(depth[0, 8, 8]), 1.02)

    def test_z_buffer_tie_deterministic_and_uv(self):
        v = np.concatenate([self.v, self.v + np.array([0, 0, 0.2], np.float32)])
        tri = np.concatenate([self.t, self.t + 4])
        uv = np.tile([[0, 0], [1, 0], [1, 1], [0, 1]], (2, 1))
        r = raster(v, tri, self.K, self.R, self.trans, 16, uv, np.ones((4, 4, 3)) * 0.5)
        self.assertTrue((r["triangle_id"][r["visibility"]] < 2).all())
        self.assertTrue(np.allclose(r["rgb"][r["visibility"]], 0.5))
        second = raster(
            v, tri, self.K, self.R, self.trans, 16, uv, np.ones((4, 4, 3)) * 0.5
        )
        self.assertTrue(np.array_equal(r["triangle_id"], second["triangle_id"]))

    def test_person_b_neck_and_occlusion_locked(self):
        r = raster(
            self.v,
            self.t,
            self.K,
            self.R,
            self.trans,
            16,
            np.array([[0, 0], [1, 0], [1, 1], [0, 1]]),
            np.ones((4, 4, 3)),
        )
        scene = np.full((16, 16, 3), 55, np.uint8)
        support = np.ones((16, 16), bool)
        protected = np.zeros_like(support)
        protected[:, 8:] = 1
        neck = np.zeros_like(support)
        neck[10:] = 1
        occlusion = np.zeros_like(support)
        occlusion[7] = 1
        out = composite(scene, r, support, protected, neck, occlusion)
        self.assertTrue(
            np.array_equal(
                out[protected | neck | occlusion], scene[protected | neck | occlusion]
            )
        )

    def test_case06_bad_mesh_rejected_before_render(self):
        v = self.v.copy()
        v[:, 0] *= -1
        with self.assertRaisesRegex(ValueError, "BEFORE rendering"):
            validate_geometry(v, self.v, self.t)

    def test_case08_target_expression_cannot_modify_identity(self):
        canonical = self.v.copy()
        expression = np.zeros_like(canonical)
        expression[0, 1] = 0.02
        original = canonical.copy()
        raster(canonical + expression, self.t, self.K, self.R, self.trans, 16)
        self.assertTrue(np.array_equal(canonical, original))

    def test_mock_cannot_pass_quality_gate(self):
        evidence = {
            k: True
            for k in [
                "source_morphology",
                "cross_view_identity",
                "expression_agreement",
                "geometry_validity",
                "visibility_complete",
                "accessory_preserved",
                "appearance_consistent",
            ]
        }
        self.assertFalse(
            qualify(
                evidence, {"mock_only": True, "commercial_training_allowed": False}
            )["machine_prequalified"]
        )

    def test_crossview_rejects_B_identity_contamination(self):
        calls = []

        def inference(source):
            calls.append(source)
            return self.v.copy()

        with self.assertRaisesRegex(ValueError, "same identity"):
            cross_view_protocol(
                inference,
                np.zeros((16, 16, 3)),
                [
                    {
                        "split": "test",
                        "source_identity_id": "A",
                        "target_identity_id": "B",
                        "source_image_sha256": "x",
                        "target_image_sha256": "y",
                    }
                ],
            )
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
