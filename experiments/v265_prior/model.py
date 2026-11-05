"""Two untrained encoders; dense identity/residual separate from target controls."""

import torch
from torch import nn
from torchvision.models import mobilenet_v3_small, shufflenet_v2_x0_5


class IdentityEncoder(nn.Module):
    def __init__(
        self, backbone="mobilenet_v3_small", identity_dim=192, residual_dim=32
    ):
        super().__init__()
        self.identity_dim = identity_dim
        if backbone == "mobilenet_v3_small":
            m = mobilenet_v3_small(weights=None)
            self.features = nn.Sequential(
                m.features, nn.AdaptiveAvgPool2d(1), nn.Flatten()
            )
            width = 576
        elif backbone == "shufflenet_v2_x0_5":
            m = shufflenet_v2_x0_5(weights=None)
            m.fc = nn.Identity()
            self.features, width = m, 1024
        else:
            raise ValueError("unsupported encoder")
        self.head = nn.Linear(width, identity_dim + residual_dim)

    def forward(self, rgb):
        c = torch.tanh(self.head(self.features(rgb)))
        return c[:, : self.identity_dim], c[:, self.identity_dim :]


class CanonicalDecoder(nn.Module):
    """Dataset-derived bases must be learned ONLY from the validated training split.

    Identity and residual bases are projected away from supplied expression span.
    This enforces algebraic orthogonality, not semantic disentanglement evidence.
    No restriction on dense native vertex count. Correspondence is output-only.
    """

    def __init__(
        self,
        neutral,
        identity_basis,
        residual_basis,
        expression_basis,
        triangles,
        correspondence_ids,
        correspondence_weights,
    ):
        super().__init__()
        n = neutral.shape[0]
        assert neutral.shape == (n, 3)
        e = expression_basis.reshape(len(expression_basis), -1).T
        u, s, _ = torch.linalg.svd(e, full_matrices=False)
        q = u[:, s > (s.max() * 1e-6)]
        self.register_buffer("expression_q", q)
        for name, value in [
            ("neutral", neutral),
            ("triangles", triangles),
            ("expression_basis", expression_basis),
            ("correspondence_ids", correspondence_ids),
            ("correspondence_weights", correspondence_weights),
        ]:
            self.register_buffer(name, value)
        for name, b in [
            ("identity_basis", identity_basis),
            ("residual_basis", residual_basis),
        ]:
            flat = b.reshape(len(b), -1)
            projected = flat - (flat @ q) @ q.T
            self.register_buffer(name, projected.reshape_as(b))

    def forward(self, identity, residual):
        # Coefficients are bounded by encoder; basis bounds belong to training contract.
        return (
            self.neutral
            + torch.einsum("bk,knc->bnc", identity, self.identity_basis)
            + torch.einsum("bk,knc->bnc", residual, self.residual_basis)
        )

    def target(self, canonical, expression, rotation, translation):
        expressed = canonical + torch.einsum(
            "be,enc->bnc", expression, self.expression_basis
        )
        return expressed @ rotation.transpose(-1, -2) + translation[:, None, :]

    def mediapipe_subset(self, canonical):
        tri = self.triangles[self.correspondence_ids]
        return (canonical[:, tri] * self.correspondence_weights[None, :, :, None]).sum(
            2
        )


def mesh_losses(pred, neutral_gt, triangles):
    """Differentiable topology losses in canonical coordinates, without culling."""
    p, g = pred[:, triangles], neutral_gt[:, triangles]
    pe = torch.stack([p[:, :, 1] - p[:, :, 0], p[:, :, 2] - p[:, :, 0]], dim=-2)
    ge = torch.stack([g[:, :, 1] - g[:, :, 0], g[:, :, 2] - g[:, :, 0]], dim=-2)
    pn, gn = torch.cross(pe[:, :, 0], pe[:, :, 1], dim=-1), torch.cross(
        ge[:, :, 0], ge[:, :, 1], dim=-1
    )
    pa, ga = pn.norm(dim=-1), gn.norm(dim=-1).clamp_min(1e-12)
    cosine = (pn * gn).sum(-1) / (pa.clamp_min(1e-12) * ga)
    # A smooth penalty is not a validity guarantee; evaluation rejects invalid fits.
    orientation = torch.relu(0.05 - cosine).square().mean()
    area = torch.log((pa / ga).clamp_min(1e-8)).square().mean()
    edges = torch.cat(
        [triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]
    )
    edges = torch.unique(edges.sort(1).values, dim=0)
    dp = pred[:, edges[:, 1]] - pred[:, edges[:, 0]]
    dg = neutral_gt[:, edges[:, 1]] - neutral_gt[:, edges[:, 0]]
    edge = (
        torch.log((dp.norm(dim=-1) / dg.norm(dim=-1).clamp_min(1e-12)).clamp_min(1e-8))
        .square()
        .mean()
    )
    delta = pred - neutral_gt
    # Uniform graph Laplacian, O(E) storage rather than dense NxN matrix.
    lap = torch.zeros_like(delta)
    degree = torch.zeros(delta.shape[1], device=delta.device)
    for a, b in [(edges[:, 0], edges[:, 1]), (edges[:, 1], edges[:, 0])]:
        lap.index_add_(1, a, delta[:, b] - delta[:, a])
        degree.index_add_(0, a, torch.ones_like(a, dtype=delta.dtype))
    laplacian = (lap / degree.clamp_min(1)[None, :, None]).square().mean()
    # Rotation-invariant per-triangle Gram matching: ARAP-like metric loss.
    arap = ((pe @ pe.transpose(-1, -2)) - (ge @ ge.transpose(-1, -2))).square().mean()
    return dict(
        orientation=orientation,
        area=area,
        edge=edge,
        laplacian=laplacian,
        arap_like=arap,
    )


def supervised_losses(output, target, triangles, regions, expression_q):
    """Explicit mandatory interfaces: missing supervision is an error, not zero loss."""
    mse = lambda a, b: (a - b).square().mean()
    result = mesh_losses(output["neutral"], target["neutral"], triangles)
    for name in [
        "neutral",
        "coefficients",
        "canonical_residual",
        "silhouette",
        "landmarks",
    ]:
        result[name] = mse(output[name], target[name])
    result["cross_view"] = mse(output["coefficients"], output["paired_coefficients"])
    flat = output["canonical_residual"].flatten(1)
    result["expression_orthogonality"] = (flat @ expression_q).square().mean()
    for name, indices in regions.items():
        if len(indices) == 0:
            raise ValueError("empty critical region " + name)
        result["identity_" + name] = mse(
            output["neutral"][:, indices], target["neutral"][:, indices]
        )
    return result
