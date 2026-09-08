"""OFFLINE 3D-template residual and configuration experiments.

A generic-depth prior cannot recover true identity depth from one photograph.
PnP estimates pose from stable internal landmarks; jaw silhouette correspondence
under yaw remains uncertain. No runtime import, gate or production acceptance.
"""

from pathlib import Path
import json
import cv2
import numpy as np
from .v265_source_fidelity import normalize


def template68():
    raw = np.array(
        json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "tests/fixtures/v265_shape/openseeface_template.json"
            ).read_text()
        )["points70"],
        float,
    )
    p = np.empty((68, 3))
    p[:48] = raw[:48]
    ids = [58, 48, 49, 50, 51, 52, 62, 53, 54, 55, 56, 57]
    p[48:60] = raw[ids]
    p[61:64] = raw[59:62]
    p[65:68] = raw[63:66]
    p[60] = (p[48] + (p[61] + p[67]) * 0.5) * 0.5
    p[64] = (p[54] + (p[63] + p[65]) * 0.5) * 0.5
    return -p


def checked_points(points):
    p = np.asarray(points, float)
    if p.shape != (68, 2) or not np.isfinite(p).all():
        raise ValueError("expected finite 68x2 points")
    if np.linalg.norm(p[42:48].mean(0) - p[36:42].mean(0)) < 1e-6:
        raise ValueError("degenerate eye baseline")
    return p


def camera(points, shape):
    p = checked_points(points)
    h, w = shape[:2]
    if min(h, w) <= 0:
        raise ValueError("invalid image dimensions")
    k = np.array([[max(w, h), 0, w / 2], [0, max(w, h), h / 2], [0, 0, 1]], float)
    # Jaw and moving lips excluded from pose fitting. Nose identity still confounds pose.
    ids = np.array([17, 19, 21, 22, 24, 26, 27, 28, 29, 30, 31, 33, 35, 36, 39, 42, 45])
    ok, r, t = cv2.solvePnP(
        template68()[ids], p[ids], k, np.zeros(4), flags=cv2.SOLVEPNP_EPNP
    )
    if not ok:
        raise ValueError("pose fit unavailable")
    ok, r, t = cv2.solvePnP(
        template68()[ids],
        p[ids],
        k,
        np.zeros(4),
        r,
        t,
        True,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok or t[2, 0] <= 0:
        raise ValueError("invalid pose fit")
    return k, r, t


def project(points, cam):
    k, r, t = cam
    return cv2.projectPoints(np.asarray(points, float), r, t, k, np.zeros(4))[0][
        :, 0, :
    ]


def lift_residual(points, cam):
    """Ray intersection with each prior-depth plane: observed XY retained exactly."""
    k, r, t = cam
    rot = cv2.Rodrigues(r)[0]
    prior = template68()
    xyz = []
    origin = -rot.T @ t[:, 0]
    for uv, z in zip(points, prior[:, 2]):
        ray = rot.T @ np.linalg.solve(k, np.r_[uv, 1.0])
        if abs(ray[2]) < 0.1:
            raise ValueError("unsupported pose/depth-plane intersection")
        distance = (z - origin[2]) / ray[2]
        if distance <= 0:
            raise ValueError("backward reconstruction ray")
        xyz.append(origin + distance * ray)
    return np.array(xyz)


def pose_projected_source(source_points, target_points, source_shape, target_shape):
    sc = camera(source_points, source_shape)
    tc = camera(target_points, target_shape)
    source3 = lift_residual(source_points, sc)
    out = project(source3, tc)
    # Retain target scale/eye-line exactly; nose/mouth/jaw do not fit themselves.
    eye = lambda p: np.array([p[36:42].mean(0), p[42:48].mean(0)])
    a, b = eye(out), eye(target_points)
    u = a[1] - a[0]
    v = b[1] - b[0]
    angle = np.arctan2(v[1], v[0]) - np.arctan2(u[1], u[0])
    rot = (
        np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        * np.linalg.norm(v)
        / np.linalg.norm(u)
    )
    out = (out - a.mean(0)) @ rot.T + b.mean(0)
    return out.astype(np.float32), {
        "source_pose_rvec": sc[1].ravel().tolist(),
        "target_pose_rvec": tc[1].ravel().tolist(),
        "depth": "generic prior, not recovered identity depth",
    }


def expression_mouth(source_projected, target):
    """Keep source width/lip offsets; adapt bounded target opening and corner height.

    This does not claim full action-unit disentanglement. Open source mouths and
    teeth visibility are not synthesizable by a geometric warp alone.
    """
    s = checked_points(source_projected).copy()
    t = checked_points(target)
    width = np.linalg.norm(s[54] - s[48])
    tw = np.linalg.norm(t[54] - t[48])
    if min(width, tw) < 1e-6:
        raise ValueError("degenerate mouth")
    u = (s[54] - s[48]) / width
    v = np.array([-u[1], u[0]])
    if np.dot(s[57] - s[51], v) < 0:
        v = -v
    opening = lambda p: np.linalg.norm(p[66] - p[62]) / np.linalg.norm(p[54] - p[48])
    delta = np.clip(opening(t) - opening(s), -0.12, 0.12) * width
    upper = [49, 50, 51, 52, 53, 61, 62, 63]
    lower = [55, 56, 57, 58, 59, 65, 66, 67]
    s[upper] -= v * delta / 2
    s[lower] += v * delta / 2
    # Corner displacement projected onto local mouth vertical, not mouth width.
    tu = (t[54] - t[48]) / tw
    tv = np.array([-tu[1], tu[0]])
    if np.dot(t[57] - t[51], tv) < 0:
        tv = -tv
    ts = (t[[48, 54]].mean(0) - t[[51, 57]].mean(0)) @ tv / tw
    ss = (s[[48, 54]].mean(0) - s[[51, 57]].mean(0)) @ v / width
    corner = np.clip(ts - ss, -0.08, 0.08) * width
    center = s[[48, 54]].mean(0).copy()
    for i in range(48, 68):
        x = abs((s[i] - center) @ u) / (width / 2)
        s[i] += v * corner * min(1, x * x)
    return s.astype(np.float32)


def configuration(points):
    p = normalize(points)
    mouth = (p[48] + p[54]) / 2
    width = lambda a, b: float(np.linalg.norm(p[a] - p[b]))
    return {
        "jaw_width": width(4, 12),
        "chin_width": width(7, 9),
        "cheek_width": width(2, 14),
        "nose_length": width(27, 33),
        "nose_width": width(31, 35),
        "mouth_width": width(48, 54),
        "nose_to_mouth": float(np.linalg.norm(p[33] - mouth)),
        "mouth_to_chin": float(np.linalg.norm(p[8] - mouth)),
        "eye_to_nose": float(p[33, 1]),
        "face_aspect": width(27, 8) / width(2, 14),
        "jaw_to_chin_width": width(4, 12) / width(7, 9),
        "upper_lip_thickness": width(51, 62),
        "lower_lip_thickness": width(57, 66),
        "jaw_asymmetry": float(
            np.linalg.norm(p[4] - p[8]) - np.linalg.norm(p[12] - p[8])
        ),
        "configuration_signed": (
            p[[4, 8, 12, 27, 33, 48, 54, 51, 57]].ravel()
        ).tolist(),
    }


def tps_inverse_roi(warped, projected, desired, box, face_min):
    """Interpolating TPS inverse map; row blocks bound memory. No eye-only patch."""
    projected = checked_points(projected)
    desired = checked_points(desired)
    x0, y0, x1, y1 = box
    h, w = warped.shape[:2]
    origin = np.array([x0, y0])
    scale = float(face_min)
    if not np.isfinite(scale) or scale <= 0 or (w, h) != (x1 - x0, y1 - y0):
        raise ValueError("invalid ROI or scale")
    boundary = np.array(
        [
            [0, 0],
            [w / 2, 0],
            [w - 1, 0],
            [0, h / 2],
            [w - 1, h / 2],
            [0, h - 1],
            [w / 2, h - 1],
            [w - 1, h - 1],
        ]
    )
    q = np.vstack([np.asarray(desired) - origin, boundary]) / scale
    residual = (
        np.vstack([np.asarray(projected) - np.asarray(desired), np.zeros((8, 2))])
        / scale
    )
    delta = q[:, None, :] - q[None, :, :]
    r2 = (delta * delta).sum(2)
    kernel = r2 * np.log(np.maximum(r2, 1e-12))
    poly = np.c_[np.ones(len(q)), q]
    system = np.block([[kernel, poly], [poly.T, np.zeros((3, 3))]])
    coef = np.linalg.solve(system, np.vstack([residual, np.zeros((3, 2))]))
    fit = kernel @ coef[: len(q)] + poly @ coef[len(q) :]
    error = float(np.max(np.linalg.norm(fit - residual, axis=1)) * scale)
    out = np.empty_like(warped)
    min_det = float("inf")
    for start in range(0, h, 48):
        stop = min(h, start + 48)
        yy, xx = np.mgrid[start:stop, :w].astype(np.float32)
        dx = (
            np.full(xx.shape, coef[-3, 0], np.float32)
            + coef[-2, 0] * xx / scale
            + coef[-1, 0] * yy / scale
        )
        dy = (
            np.full(xx.shape, coef[-3, 1], np.float32)
            + coef[-2, 1] * xx / scale
            + coef[-1, 1] * yy / scale
        )
        for i, (cx, cy) in enumerate(q):
            r2 = (xx / scale - cx) ** 2 + (yy / scale - cy) ** 2
            k = r2 * np.log(np.maximum(r2, 1e-12))
            dx += coef[i, 0] * k
            dy += coef[i, 1] * k
        mx = (xx + dx * scale).astype(np.float32)
        my = (yy + dy * scale).astype(np.float32)
        if stop - start > 1:
            mxy, mxx = np.gradient(mx)
            myy, myx = np.gradient(my)
            min_det = min(min_det, float((mxx * myy - mxy * myx).min()))
        out[start:stop] = cv2.remap(
            warped, mx, my, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT_101
        )
    if min_det <= 0:
        raise ValueError("folded inverse geometry field")
    return out, error, np.asarray(desired) - np.asarray(projected)


def orthographic_camera(points):
    """Scaled-orthographic fit, independent of image canvas/principal point.

    Assumes weak perspective. Does not recover subject-specific depth and does
    not qualify large yaw/occlusion. Internal anchors only, as in the PnP lab.
    """

    p = checked_points(points)
    ids = np.array([17, 19, 21, 22, 24, 26, 27, 28, 29, 30, 31, 33, 35, 36, 39, 42, 45])
    q = template68()[ids]
    design = np.c_[q, np.ones(len(q))]
    affine = np.linalg.lstsq(design, p[ids], rcond=None)[0][:3].T
    u, singular, vh = np.linalg.svd(affine, full_matrices=False)
    axes = u @ vh
    rot = np.vstack([axes, np.cross(axes[0], axes[1])])
    initial_r = cv2.Rodrigues(rot)[0].ravel()
    scale = singular.mean()
    translation = p[ids].mean(0) - scale * (q @ rot[:2].T).mean(0)
    initial = np.r_[initial_r, np.log(scale), translation]

    def residual(parameters):
        r = cv2.Rodrigues(parameters[:3])[0]
        predicted = np.exp(parameters[3]) * (q @ r[:2].T) + parameters[4:]
        return (predicted - p[ids]).ravel()

    # Six-parameter damped Gauss-Newton; avoids importing scipy.optimize into
    # the memory-constrained compositor. Tolerances are numerical, not fidelity gates.
    parameters = initial.copy()
    damping = 1e-3
    for _ in range(100):
        value = residual(parameters)
        cost = float(value @ value)
        jac = np.empty((len(value), 6), float)
        for j in range(3):
            step = parameters.copy()
            step[j] += 1e-6
            jac[:, j] = (residual(step) - value) / 1e-6
        r = cv2.Rodrigues(parameters[:3])[0]
        jac[:, 3] = (np.exp(parameters[3]) * (q @ r[:2].T)).ravel()
        jac[:, 4] = np.tile([1.0, 0.0], len(q))
        jac[:, 5] = np.tile([0.0, 1.0], len(q))
        normal = jac.T @ jac
        gradient = jac.T @ value
        diagonal = np.maximum(np.diag(normal), 1e-12)
        if np.max(np.abs(gradient) / np.sqrt(diagonal)) < 1e-7:
            break
        delta = np.linalg.solve(normal + damping * np.diag(diagonal), -gradient)
        candidate = parameters + delta
        candidate_residual = residual(candidate)
        candidate_cost = float(candidate_residual @ candidate_residual)
        if np.isfinite(candidate_cost) and candidate_cost < cost:
            parameters = candidate
            damping = max(1e-12, damping * 0.25)
            if cost - candidate_cost < 1e-12 * max(1.0, cost):
                break
        else:
            damping = min(1e12, damping * 10)
    if not np.isfinite(parameters).all():
        raise ValueError("orthographic pose unavailable")
    rot = cv2.Rodrigues(parameters[:3])[0]
    return (
        rot,
        float(np.exp(parameters[3])),
        parameters[4:],
        float(np.sqrt(np.mean(residual(parameters) ** 2))),
    )


def orthographic_projected_source(source_points, target_points):
    sr, ss, st, se = orthographic_camera(source_points)
    tr, ts, tt, te = orthographic_camera(target_points)
    if abs(np.linalg.det(sr[:2, :2])) < 1e-6:
        raise ValueError("singular source depth-plane projection")
    depth = template68()[:, 2]
    xy = np.linalg.solve(
        sr[:2, :2],
        ((checked_points(source_points) - st) / ss - depth[:, None] * sr[:2, 2]).T,
    ).T
    source3 = np.c_[xy, depth]
    out = ts * (source3 @ tr[:2].T) + tt
    eyes = lambda p: np.array([p[36:42].mean(0), p[42:48].mean(0)])
    a, b = eyes(out), eyes(target_points)
    u = a[1] - a[0]
    v = b[1] - b[0]
    theta = np.arctan2(v[1], v[0]) - np.arctan2(u[1], u[0])
    rot = (
        np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
        * np.linalg.norm(v)
        / np.linalg.norm(u)
    )
    out = (out - a.mean(0)) @ rot.T + b.mean(0)
    return out.astype(np.float32), {
        "camera": "scaled orthographic generic-depth prior",
        "source_anchor_rmse_px": se,
        "target_anchor_rmse_px": te,
        "source_pose_rvec": cv2.Rodrigues(sr)[0].ravel().tolist(),
        "target_pose_rvec": cv2.Rodrigues(tr)[0].ravel().tolist(),
    }
