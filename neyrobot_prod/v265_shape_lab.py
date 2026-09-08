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


def tps_inverse_roi(
    warped, projected, desired, box, face_min, active_mask=None, domain_box=None
):
    """Interpolating TPS inverse map; row blocks bound memory. No eye-only patch."""
    projected = checked_points(projected)
    desired = checked_points(desired)
    x0, y0, x1, y1 = box
    h, w = warped.shape[:2]
    domain_box = box if domain_box is None else domain_box
    dx0, dy0, dx1, dy1 = domain_box
    dw, dh = dx1 - dx0, dy1 - dy0
    if dw <= 1 or dh <= 1:
        raise ValueError("invalid deformation domain")
    origin = np.array([dx0, dy0])
    roi_origin = np.array([x0, y0])
    scale = float(face_min)
    if not np.isfinite(scale) or scale <= 0 or (w, h) != (x1 - x0, y1 - y0):
        raise ValueError("invalid ROI or scale")
    if active_mask is None:
        active = np.ones((h, w), np.uint8)
    else:
        if np.asarray(active_mask).shape != (h, w) or not np.any(active_mask):
            raise ValueError("invalid active deformation support")
        # Include the finite-difference stencil around every potentially used pixel.
        active = cv2.dilate(
            (np.asarray(active_mask) > 0).astype(np.uint8), np.ones((3, 3), np.uint8)
        )
    boundary = np.array(
        [
            [0, 0],
            [dw / 2, 0],
            [dw - 1, 0],
            [0, dh / 2],
            [dw - 1, dh / 2],
            [0, dh - 1],
            [dw / 2, dh - 1],
            [dw - 1, dh - 1],
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
    folded_pixels = 0
    folded_face_pixels = 0
    folded_active_pixels = 0
    hull = cv2.convexHull(
        np.round(np.vstack([desired[:17], desired[17:27]]) - roi_origin).astype(
            np.int32
        )
    )
    for start in range(0, h, 48):
        stop = min(h, start + 48)
        yy, xx = np.mgrid[start:stop, :w].astype(np.float32)
        domain_x = xx + x0 - dx0
        domain_y = yy + y0 - dy0
        dx = (
            np.full(xx.shape, coef[-3, 0], np.float32)
            + coef[-2, 0] * domain_x / scale
            + coef[-1, 0] * domain_y / scale
        )
        dy = (
            np.full(xx.shape, coef[-3, 1], np.float32)
            + coef[-2, 1] * domain_x / scale
            + coef[-1, 1] * domain_y / scale
        )
        for i, (cx, cy) in enumerate(q):
            r2 = (domain_x / scale - cx) ** 2 + (domain_y / scale - cy) ** 2
            k = r2 * np.log(np.maximum(r2, 1e-12))
            dx += coef[i, 0] * k
            dy += coef[i, 1] * k
        mx = (xx + dx * scale).astype(np.float32)
        my = (yy + dy * scale).astype(np.float32)
        if stop - start > 1:
            mxy, mxx = np.gradient(mx)
            myy, myx = np.gradient(my)
            det = mxx * myy - mxy * myx
            min_det = min(min_det, float(det.min()))
            negative = det <= 0
            folded_pixels += int(negative.sum())
            folded_active_pixels += int((negative & (active[start:stop] > 0)).sum())
            local_hull = hull - np.array([0, start], np.int32)
            face = np.zeros(negative.shape, np.uint8)
            cv2.fillConvexPoly(face, local_hull, 1)
            folded_face_pixels += int((negative & (face > 0)).sum())
        out[start:stop] = cv2.remap(
            warped, mx, my, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT_101
        )
    if min_det <= 0:
        print(
            "TPS_FOLD_DIAGNOSTIC",
            json.dumps(
                {
                    "minimum_jacobian": min_det,
                    "folded_pixels": folded_pixels,
                    "folded_face_hull_pixels": folded_face_pixels,
                    "folded_active_pixels": folded_active_pixels,
                    "roi_pixels": h * w,
                    "maximum_control_error_px": error,
                }
            ),
            flush=True,
        )
    if folded_active_pixels:
        raise ValueError("folded inverse geometry field")
    return out, error, np.asarray(desired) - np.asarray(projected)


def orthographic_camera(points, anchor_ids=None):
    """Scaled-orthographic fit, independent of image canvas/principal point.

    Assumes weak perspective. Does not recover subject-specific depth and does
    not qualify large yaw/occlusion. Internal anchors only, as in the PnP lab.
    """

    p = checked_points(points)
    ids = np.array(
        [17, 19, 21, 22, 24, 26, 27, 28, 29, 30, 31, 33, 35, 36, 39, 42, 45]
        if anchor_ids is None
        else anchor_ids
    )
    if len(ids) < 6 or len(np.unique(ids)) != len(ids):
        raise ValueError("insufficient independent pose anchors")
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


def orthographic_projected_source(source_points, target_points, anchor_ids=None):
    sr, ss, st, se = orthographic_camera(source_points, anchor_ids)
    tr, ts, tt, te = orthographic_camera(target_points, anchor_ids)
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


def projection_jackknife(source_points, target_points):
    """Offline sensitivity estimate; not calibrated landmark uncertainty.

    Leave one internal pose anchor out, retaining every source jaw observation.
    This measures camera-fit sensitivity, not missing subject depth or occlusion.
    No case IDs, human labels or negative examples enter the calculation.
    """
    ids = [17, 19, 21, 22, 24, 26, 27, 28, 29, 30, 31, 33, 35, 36, 39, 42, 45]
    full, info = orthographic_projected_source(source_points, target_points)
    samples = np.array(
        [
            orthographic_projected_source(
                source_points, target_points, ids[:i] + ids[i + 1 :]
            )[0]
            for i in range(len(ids))
        ]
    )
    variance = (len(ids) - 1) * np.mean(
        np.sum((samples - samples.mean(0)) ** 2, axis=2), axis=0
    )
    if not np.isfinite(variance).all():
        raise ValueError("invalid projection sensitivity")
    info["jackknife_variance_px2"] = variance.tolist()
    return full, variance, info


def shrink_shape_residual(base, proposed, variance):
    """Unit signal-to-variance shrinkage, no fitted case-specific coefficient."""
    base, proposed = checked_points(base), checked_points(proposed)
    variance = np.asarray(variance, float)
    if (
        variance.shape != (68,)
        or not np.isfinite(variance).all()
        or (variance < 0).any()
    ):
        raise ValueError("invalid residual variance")
    delta = proposed - base
    signal = np.sum(delta * delta, axis=1)
    weight = np.divide(
        signal, signal + variance, out=np.ones(68), where=(signal + variance) > 0
    )
    return (base + weight[:, None] * delta).astype(np.float32), weight
