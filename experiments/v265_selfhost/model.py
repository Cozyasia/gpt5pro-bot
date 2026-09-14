"""Own random-initialized heads; fixed train-derived native geometry basis."""

import numpy as np
import torch
from torch import nn
from experiments.v265_prior.model import IdentityEncoder, CanonicalDecoder, mesh_losses

VERSION = "selfhost-heads-1"


class Heads(nn.Module):
    def __init__(
        self,
        backbone="mobilenet_v3_small",
        identity_dim=192,
        residual_dim=32,
        uv_size=16,
    ):
        super().__init__()
        self.identity = IdentityEncoder(backbone, identity_dim, residual_dim)
        # Canonical appearance is identity-conditioned; never target-image conditioned.
        self.albedo = nn.Sequential(
            nn.Linear(identity_dim + residual_dim, 128),
            nn.SiLU(),
            nn.Linear(128, 3 * uv_size * uv_size),
            nn.Sigmoid(),
        )
        self.parsing = nn.Sequential(
            nn.Conv2d(3, 16, 3, padding=1),
            nn.SiLU(),
            nn.Conv2d(16, 16, 3, padding=1, groups=16),
            nn.SiLU(),
            nn.Conv2d(16, 15, 1),
        )
        self.uv_size = uv_size

    def forward(self, rgb):
        identity, residual = self.identity(rgb)
        appearance = self.albedo(torch.cat([identity, residual], 1)).reshape(
            -1, 3, self.uv_size, self.uv_size
        )
        return identity, residual, appearance, self.parsing(rgb)


def decoder_from_npz(path):
    with np.load(path, allow_pickle=False) as z:
        kwargs = {
            k: torch.from_numpy(z[k].copy())
            for k in [
                "neutral",
                "identity_basis",
                "residual_basis",
                "expression_basis",
                "triangles",
                "correspondence_ids",
                "correspondence_weights",
            ]
        }
    return CanonicalDecoder(**kwargs)


def validity_losses(pred, gt, triangles, residual, residual_bound=0.003):
    losses = mesh_losses(pred, gt, triangles)
    p = pred[:, triangles]
    g = gt[:, triangles]
    pn = torch.cross(p[:, :, 1] - p[:, :, 0], p[:, :, 2] - p[:, :, 0], dim=-1)
    gn = torch.cross(g[:, :, 1] - g[:, :, 0], g[:, :, 2] - g[:, :, 0], dim=-1)
    cosine = (pn * gn).sum(-1) / (pn.norm(dim=-1) * gn.norm(dim=-1)).clamp_min(1e-12)
    # Log orientation barrier; explicit penalty on invalid side preserves gradients.
    losses["orientation_barrier"] = (
        -torch.log(cosine.clamp_min(0.01)) + 100 * torch.relu(0.01 - cosine)
    ).mean()
    ratio = pn.norm(dim=-1) / gn.norm(dim=-1).clamp_min(1e-12)
    losses["compression"] = torch.relu(0.5 - ratio).square().mean()
    losses["expansion"] = torch.relu(ratio - 2.0).square().mean()
    losses["residual_bound"] = (
        torch.relu(residual.norm(dim=-1) - residual_bound).square().mean()
    )
    return losses
