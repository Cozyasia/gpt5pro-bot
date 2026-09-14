"""Local calibrated geometry: torch soft supervision and numpy deterministic raster."""

import numpy as np

VERSION = "v265-local-geometry-1"


def cross2(a, b):
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def project_np(vertices, K, R, t):
    camera = vertices @ R.T + t
    if not np.isfinite(camera).all() or (camera[:, 2] <= 1e-6).any():
        raise ValueError("invalid/behind-camera surface")
    screen = camera @ K.T
    return screen[:, :2] / screen[:, 2:3], camera[:, 2]


def project_torch(vertices, K, R, t):
    camera = vertices @ R.transpose(-1, -2) + t[:, None]
    screen = camera @ K.transpose(-1, -2)
    return screen[..., :2] / screen[..., 2:3].clamp_min(1e-6), camera[..., 2]


def soft_surface(
    vertices, triangles, K, R, t, size, edge_sigma=0.35, depth_temperature=0.02
):
    """Differentiable soft triangle occupancy + depth visibility. Training only.

    Interior distance is in pixel units. Coverage uses max over triangles, avoiding
    tessellation-dependent alpha accumulation. Soft depth weights model occlusion;
    at depth/triangle ties derivatives are piecewise defined. No hard culling.
    """
    import torch

    xy, z = project_torch(vertices, K, R, t)
    yy, xx = torch.meshgrid(
        torch.arange(size, device=vertices.device, dtype=vertices.dtype) + 0.5,
        torch.arange(size, device=vertices.device, dtype=vertices.dtype) + 0.5,
        indexing="ij",
    )
    pixel = torch.stack([xx, yy], -1).reshape(1, 1, size * size, 2)
    coverage = torch.zeros(
        (len(vertices), size * size), device=vertices.device, dtype=vertices.dtype
    )
    numerator = torch.zeros_like(coverage)
    denominator = torch.zeros_like(coverage)
    zbase = z.min(1).values[:, None].detach()
    for chunk in triangles.split(128):
        p = xy[:, chunk]
        tz = z[:, chunk]
        a, b, c = p.unbind(2)
        area = (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (
            b[..., 1] - a[..., 1]
        ) * (c[..., 0] - a[..., 0])
        sign = torch.where(area >= 0, 1.0, -1.0)
        distances = []
        for start, end in [(a, b), (b, c), (c, a)]:
            edge = end - start
            rel = pixel - start[:, :, None]
            cross = (
                edge[:, :, None, 0] * rel[..., 1] - edge[:, :, None, 1] * rel[..., 0]
            )
            distances.append(
                cross * sign[:, :, None] / edge.norm(dim=-1).clamp_min(1e-8)[:, :, None]
            )
        inside = torch.stack(distances, -1).amin(-1)
        alpha = torch.sigmoid(inside / edge_sigma)
        # Barycentric perspective depth inside; clamp weights outside for stability.
        w0 = (
            (b[:, :, None, 0] - pixel[..., 0]) * (c[:, :, None, 1] - pixel[..., 1])
            - (b[:, :, None, 1] - pixel[..., 1]) * (c[:, :, None, 0] - pixel[..., 0])
        ) / area[:, :, None].where(
            area[:, :, None].abs() > 1e-8, torch.full_like(area[:, :, None], 1e-8)
        )
        w1 = (
            (c[:, :, None, 0] - pixel[..., 0]) * (a[:, :, None, 1] - pixel[..., 1])
            - (c[:, :, None, 1] - pixel[..., 1]) * (a[:, :, None, 0] - pixel[..., 0])
        ) / area[:, :, None].where(
            area[:, :, None].abs() > 1e-8, torch.full_like(area[:, :, None], 1e-8)
        )
        weights = torch.stack([w0, w1, 1 - w0 - w1], -1).clamp_min(0)
        weights = weights / weights.sum(-1, keepdim=True).clamp_min(1e-8)
        depth = 1 / (weights / tz[:, :, None, :].clamp_min(1e-6)).sum(-1).clamp_min(
            1e-6
        )
        weight = alpha * torch.exp(-(depth - zbase[:, None]) / depth_temperature)
        coverage = torch.maximum(coverage, alpha.amax(1))
        numerator = numerator + (weight * depth).sum(1)
        denominator = denominator + weight.sum(1)
    return coverage.reshape(-1, size, size), (
        numerator / denominator.clamp_min(1e-12)
    ).reshape(-1, size, size)


def validate_geometry(
    vertices, reference, triangles, area_bounds=(0.25, 4.0), edge_bounds=(0.5, 2.0)
):
    from experiments.v265_prior.evaluate import topology_metrics

    if not np.isfinite(vertices).all():
        raise ValueError("nonfinite mesh")
    metrics = topology_metrics(vertices, reference, triangles)
    valid = (
        metrics["orientation_failures"] == 0
        and metrics["local_area_ratio"]["min"] >= area_bounds[0]
        and metrics["local_area_ratio"]["max"] <= area_bounds[1]
        and metrics["edge_stretch"]["min"] >= edge_bounds[0]
        and metrics["edge_stretch"]["max"] <= edge_bounds[1]
    )
    if not valid:
        raise ValueError("geometry rejected BEFORE rendering: " + str(metrics))
    return metrics


def raster(
    vertices,
    triangles,
    K,
    R,
    t,
    size,
    uv=None,
    albedo=None,
    vertex_semantic=None,
    illumination=(1.0, 0.0, 0.0),
):
    """Deterministic pixel-center raster, perspective barycentrics, stable z ties.

    Caller MUST validate canonical geometry before this function. Back-facing count
    is diagnostic (two-sided surface raster); occlusion resolved by z-buffer. No
    invalid triangle rescue: projected degeneracy is an explicit rejection.
    """
    xy, z = project_np(vertices, K, R, t)
    depth = np.full((size, size), np.inf)
    tid = np.full((size, size), -1, np.int32)
    bary = np.zeros((size, size, 3))
    back = 0
    edge_on = 0
    for index, tri in enumerate(triangles):
        p = xy[tri]
        a, b, c = p
        area = cross2(b - a, c - a).item()
        if abs(area) < 1e-10:
            edge_on += 1
            continue  # Zero projected area has no visible surface; not canonical failure culling.
        back += int(area < 0)
        x0 = max(0, int(np.floor(p[:, 0].min())))
        x1 = min(size, int(np.ceil(p[:, 0].max())))
        y0 = max(0, int(np.floor(p[:, 1].min())))
        y1 = min(size, int(np.ceil(p[:, 1].max())))
        if x0 >= x1 or y0 >= y1:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        q = np.stack([xx + 0.5, yy + 0.5], -1)
        w0 = cross2(b - q, c - q) / area
        w1 = cross2(c - q, a - q) / area
        weights = np.stack([w0, w1, 1 - w0 - w1], -1)
        inside = (weights >= -1e-9).all(-1)
        inv = weights / z[tri]
        invsum = inv.sum(-1)
        valid = inside & (invsum > 0)
        candidate = 1 / np.maximum(invsum, 1e-12)
        win = valid & (candidate < depth[y0:y1, x0:x1] - 1e-12)
        depth[y0:y1, x0:x1][win] = candidate[win]
        tid[y0:y1, x0:x1][win] = index
        bary[y0:y1, x0:x1][win] = (inv / np.maximum(invsum[..., None], 1e-12))[win]
    visible = tid >= 0
    rgb = np.zeros((size, size, 3), np.float32)
    sem = np.zeros((size, size), np.uint8)
    normals = np.zeros_like(rgb)
    uvmap = np.zeros((size, size, 2), np.float32)
    if visible.any():
        indices = triangles[tid[visible]]
        w = bary[visible]
        n = (
            np.cross(
                vertices[indices[:, 1]] - vertices[indices[:, 0]],
                vertices[indices[:, 2]] - vertices[indices[:, 0]],
            )
            @ R.T
        )
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        normals[visible] = n
        if uv is not None:
            coords = (uv[indices] * w[..., None]).sum(1).clip(0, 1)
            uvmap[visible] = coords
            if albedo is not None:
                # Bilinear UV lookup, stable albedo independent of illumination.
                h, wtex = albedo.shape[:2]
                u = coords[:, 0] * (wtex - 1)
                v = coords[:, 1] * (h - 1)
                x = np.floor(u).astype(int)
                y = np.floor(v).astype(int)
                x2 = np.minimum(x + 1, wtex - 1)
                y2 = np.minimum(y + 1, h - 1)
                fu = (u - x)[:, None]
                fv = (v - y)[:, None]
                color = (albedo[y, x] * (1 - fu) + albedo[y, x2] * fu) * (1 - fv) + (
                    albedo[y2, x] * (1 - fu) + albedo[y2, x2] * fu
                ) * fv
                light = np.clip(
                    illumination[0]
                    + illumination[1] * n[:, 0]
                    + illumination[2] * n[:, 1],
                    0.25,
                    2.0,
                )
                rgb[visible] = np.clip(color * light[:, None], 0, 1)
        if vertex_semantic is not None:
            sem[visible] = vertex_semantic[
                indices[np.arange(len(indices)), bary[visible].argmax(1)]
            ]
    depth[~visible] = 0
    return dict(
        rgb=rgb,
        depth=depth.astype("float32"),
        visibility=visible,
        semantic=sem,
        normals=normals,
        uv=uvmap,
        triangle_id=tid,
        barycentric=bary.astype("float32"),
        diagnostics=dict(
            triangle_count=len(triangles),
            visible_triangles=len(np.unique(tid[visible])),
            back_facing_triangles=back,
            edge_on_triangles=edge_on,
        ),
    )


def composite(scene, render, support, protected, neck, occlusion, alpha=None):
    """Source-owned interior only; boundary alpha cannot expand ownership."""
    result = scene.copy()
    allowed = support & ~protected & ~neck & ~occlusion & render["visibility"]
    a = np.ones(support.shape) if alpha is None else np.asarray(alpha)
    if (
        a.shape != support.shape
        or not np.isfinite(a).all()
        or a.min() < 0
        or a.max() > 1
    ):
        raise ValueError("invalid alpha")
    face = np.rint(render["rgb"] * 255).astype(np.uint8)
    result[allowed] = np.rint(
        face[allowed] * a[allowed, None] + scene[allowed] * (1 - a[allowed, None])
    ).astype(np.uint8)
    if not np.array_equal(result[~allowed], scene[~allowed]):
        raise AssertionError("pixel firewall")
    return result
