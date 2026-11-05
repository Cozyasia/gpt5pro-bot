import unittest
import torch
from experiments.v265_prior.model import IdentityEncoder, CanonicalDecoder, mesh_losses


class DensePlumbing(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(265)
        torch.set_num_threads(1)
        self.n = 620
        neutral = torch.randn(self.n, 3) * 0.01
        t = torch.stack(
            [
                torch.arange(self.n - 2),
                torch.arange(1, self.n - 1),
                torch.arange(2, self.n),
            ],
            1,
        )
        self.decoder = CanonicalDecoder(
            neutral,
            torch.randn(192, self.n, 3) * 1e-5,
            torch.randn(32, self.n, 3) * 1e-5,
            torch.randn(8, self.n, 3) * 1e-4,
            t,
            torch.arange(468),
            torch.tensor([[1.0, 0, 0]]).repeat(468, 1),
        )

    def test_dense_not_capped_at_468(self):
        c = self.decoder(torch.zeros(2, 192), torch.zeros(2, 32))
        self.assertEqual(c.shape, (2, 620, 3))
        self.assertEqual(self.decoder.mediapipe_subset(c).shape, (2, 468, 3))

    def test_both_bases_expression_orthogonal(self):
        for b in [self.decoder.identity_basis, self.decoder.residual_basis]:
            self.assertLess(
                float((b.flatten(1) @ self.decoder.expression_q).abs().max()), 1e-8
            )

    def test_target_cannot_mutate_identity(self):
        c = self.decoder(torch.ones(1, 192), torch.ones(1, 32))
        before = c.clone()
        self.decoder.target(c, torch.ones(1, 8), torch.eye(3)[None], torch.ones(1, 3))
        self.assertTrue(torch.equal(c, before))

    def test_losses_have_finite_gradients(self):
        g = self.decoder.neutral[None]
        p = (g + torch.randn_like(g) * 1e-5).requires_grad_()
        loss = mesh_losses(p, g, self.decoder.triangles)
        sum(loss.values()).backward()
        self.assertTrue(torch.isfinite(p.grad).all())

    def test_backbone_outputs(self):
        for name in ["mobilenet_v3_small", "shufflenet_v2_x0_5"]:
            m = IdentityEncoder(name).eval()
            a, b = m(torch.zeros(1, 3, 224, 224))
            self.assertEqual(a.shape, (1, 192))
            self.assertEqual(b.shape, (1, 32))

    def test_supervised_train_step(self):
        from experiments.v265_prior.train import train_step
        from experiments.v265_prior.model import supervised_losses

        m = IdentityEncoder().train()
        opt = torch.optim.AdamW(m.parameters(), lr=1e-4)
        batch = {
            "rgb": torch.randn(2, 3, 64, 64),
            "paired_rgb": torch.randn(2, 3, 64, 64),
        }

        def supervision(batch, neutral, identity, residual):
            # Only synthetic differentiable stand-ins exercise loss API; no renderer.
            delta = torch.einsum("bk,knc->bnc", residual, self.decoder.residual_basis)
            output = {
                "canonical_residual": delta,
                "silhouette": neutral[:, :10, :2],
                "landmarks": neutral[:, :468],
            }
            target = {
                "neutral": self.decoder.neutral[None].repeat(2, 1, 1),
                "coefficients": torch.zeros_like(identity),
                "canonical_residual": torch.zeros_like(delta),
                "silhouette": torch.zeros_like(output["silhouette"]),
                "landmarks": torch.zeros_like(output["landmarks"]),
            }
            regions = {
                k: torch.arange(i * 10, (i + 1) * 10)
                for i, k in enumerate(
                    ["jaw", "chin", "nose", "mouth", "eyes", "cheeks", "brows"]
                )
            }
            return output, target, regions

        names = [
            "orientation",
            "area",
            "edge",
            "laplacian",
            "arap_like",
            "neutral",
            "coefficients",
            "canonical_residual",
            "silhouette",
            "landmarks",
            "cross_view",
            "expression_orthogonality",
        ] + [
            "identity_" + x
            for x in ["jaw", "chin", "nose", "mouth", "eyes", "cheeks", "brows"]
        ]
        r = train_step(
            m, self.decoder, batch, opt, supervision, {x: 1.0 for x in names}
        )
        self.assertEqual(set(r), set(names))


if __name__ == "__main__":
    unittest.main()
