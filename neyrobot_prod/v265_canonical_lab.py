"""Offline L: factorized 3DMM identity/expression, never a runtime fallback.

Parameter separation is an algebraic contract, not evidence that a regressor
has recovered true identity. BFM/weight licensing is separate from code licensing.
No accessory, teeth, or disoccluded skin is hallucinated by this module.
"""

from dataclasses import dataclass
import hashlib
import numpy as np


def finite(value, shape=None):
    a = np.asarray(value, dtype=np.float32)
    if (shape is not None and a.shape != shape) or not np.isfinite(a).all():
        raise ValueError("invalid canonical evidence")
    return a


@dataclass(frozen=True)
class Parameters:
    camera: np.ndarray
    identity: np.ndarray
    expression: np.ndarray

    @classmethod
    def from62(cls, values):
        p = finite(values, (62,))
        return cls(p[:12].reshape(3, 4).copy(), p[12:52].copy(), p[52:].copy())


class CanonicalModel:
    def __init__(self, mean, identity_basis, expression_basis, triangles, landmarks):
        self.mean = finite(mean)
        if self.mean.ndim != 2 or self.mean.shape[1] != 3:
            raise ValueError("expected Vx3 mean")
        n = len(self.mean)
        self.identity_basis = finite(identity_basis, (n, 3, 40))
        self.expression_basis = finite(expression_basis, (n, 3, 10))
        self.triangles = np.asarray(triangles, dtype=np.int32)
        self.landmarks = np.asarray(landmarks, dtype=np.int32)
        if self.triangles.ndim != 2 or self.triangles.shape[1] != 3:
            raise ValueError("expected triangle topology")
        if self.triangles.min() < 0 or self.triangles.max() >= n:
            raise ValueError("invalid topology index")
        if (
            self.landmarks.shape != (68,)
            or self.landmarks.min() < 0
            or self.landmarks.max() >= n
        ):
            raise ValueError("invalid landmark indices")

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as a:
            return cls(
                *(
                    a[k]
                    for k in (
                        "mean",
                        "identity_basis",
                        "expression_basis",
                        "triangles",
                        "landmarks",
                    )
                )
            )

    def neutral(self, identity):
        return self.mean + np.einsum(
            "vck,k->vc", self.identity_basis, finite(identity, (40,))
        )

    def shape(self, identity, expression):
        return self.neutral(identity) + np.einsum(
            "vck,k->vc", self.expression_basis, finite(expression, (10,))
        )

    def retarget(self, source, target):
        # Source camera/expression and target identity deliberately have no path here.
        return self.shape(source.identity, target.expression)

    @property
    def resident_array_bytes(self):
        return sum(
            a.nbytes
            for a in (
                self.mean,
                self.identity_basis,
                self.expression_basis,
                self.triangles,
                self.landmarks,
            )
        )


def identity_digest(model, source):
    return hashlib.sha256(
        model.neutral(source.identity).astype("<f4").tobytes()
    ).hexdigest()


def project(vertices, camera, roi, size=120):
    camera = finite(camera, (3, 4))
    sx, sy, ex, ey = finite(roi, (4,))
    if ex <= sx or ey <= sy:
        raise ValueError("invalid projection ROI")
    p = finite(vertices) @ camera[:, :3].T + camera[:, 3]
    p[:, 0] = (p[:, 0] - 1) * (ex - sx) / size + sx
    p[:, 1] = (size - p[:, 1]) * (ey - sy) / size + sy
    p[:, 2] *= ((ex - sx) + (ey - sy)) / (2 * size)
    return p


def mesh_validity(
    reference,
    candidate,
    triangles,
    *,
    min_scale,
    max_scale,
    max_displacement,
    max_edge_delta
):
    """Compare in the SAME target camera, never confuse view change with inversion.

    Explicit numeric limits are supplied by caller, not production calibration.
    Near edge-on triangles are invalid/unmeasurable, never silently passing.
    Includes 3D orientation and 2D local affine singular values/Jacobian.
    """
    a, b = finite(reference), finite(candidate)
    if a.shape != b.shape or a.ndim != 2 or a.shape[1] != 3:
        raise ValueError("incompatible mesh geometry")
    limits = [min_scale, max_scale, max_displacement, max_edge_delta]
    if (
        not np.isfinite(limits).all()
        or min_scale <= 0
        or max_scale < min_scale
        or min(limits[2:]) <= 0
    ):
        raise ValueError("invalid engineering bounds")
    tri = np.asarray(triangles, dtype=np.int32)
    aa, bb = a[tri], b[tri]
    ea = aa[:, 1:] - aa[:, :1]
    eb = bb[:, 1:] - bb[:, :1]
    na = np.cross(ea[:, 0], ea[:, 1])
    nb = np.cross(eb[:, 0], eb[:, 1])
    orientations = np.einsum("ij,ij->i", na, nb)
    ma, mb = ea[:, :, :2].transpose(0, 2, 1), eb[:, :, :2].transpose(0, 2, 1)
    da, db = np.linalg.det(ma), np.linalg.det(mb)
    measurable = np.abs(da) > 1e-5
    j = mb[measurable] @ np.linalg.inv(ma[measurable])
    sv = np.linalg.svd(j, compute_uv=False)
    displacement = np.linalg.norm(b[:, :2] - a[:, :2], axis=1)
    delta = b - a
    edge_delta = np.linalg.norm(delta[tri[:, 1:]] - delta[tri[:, :1]], axis=2)
    inversion = int(np.count_nonzero(da[measurable] * db[measurable] <= 0))
    out = {
        "triangles": len(tri),
        "projected_inversions": inversion,
        "orientation_3d_reversals": int(np.count_nonzero(orientations <= 0)),
        "edge_on_unmeasurable": int(np.count_nonzero(~measurable)),
        "jacobian_min": float(np.linalg.det(j).min()) if len(j) else None,
        "local_scale_min": float(sv.min()) if len(sv) else None,
        "local_scale_max": float(sv.max()) if len(sv) else None,
        "displacement_max_px": float(displacement.max()),
        "edge_displacement_delta_max": float(edge_delta.max()),
    }
    out["passes_engineering_bounds"] = bool(
        len(j) == len(tri)
        and inversion == 0
        and out["orientation_3d_reversals"] == 0
        and sv.min() >= min_scale
        and sv.max() <= max_scale
        and displacement.max() <= max_displacement
        and edge_delta.max() <= max_edge_delta
    )
    return out


def require_renderable(
    validity, *, accessory_mask_verified, visibility_verified, mouth_texture_compatible
):
    """No geometry or unknown semantic ownership may slip into a compositor."""
    failures = []
    if not validity["passes_engineering_bounds"]:
        failures.append("invalid_geometry")
    if not accessory_mask_verified:
        failures.append("accessory_ownership_unverified")
    if not visibility_verified:
        failures.append("visibility_unverified")
    if not mouth_texture_compatible:
        failures.append("mouth_texture_expression_incompatible")
    if failures:
        raise ValueError(",".join(failures))
