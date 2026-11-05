# -*- coding: utf-8 -*-
"""V263: dense 68-landmark identity lock and quality-gated strict retry.

V262 remains the stable safety/compositing base. V263 changes only PERSON-A's final
identity-transfer owner after Gemini has created the complete two-person scene:
- the V262 PERSON-B pixel firewall, anatomical no-neck mask and lossless document
  delivery remain authoritative;
- MIT-licensed PIPNet 68-point geometry supplies source/target inner-face structure
  while YuNet keeps the proven face selection and global five-point alignment;
- source geometry is the identity authority. Synthetic target geometry contributes
  only bounded pose accommodation, with eyes/nose/mouth strongly source-dominant;
- all 68 points contribute to one compact inverse deformation field. There is no
  independent eye patch or feature-by-feature paste;
- transfer order is structure -> target lighting/colour -> controlled source
  structure/detail, with no broad raw source low-frequency core;
- an MIT-licensed MobileFace embedding plus dense geometric metrics gate delivery.
  A failed standard attempt triggers one stricter source-dominant retry; a result
  that still fails is rejected instead of being sent as a successful selfie.

No callback, payment, scene, hero-reference or Telegram delivery handler is added.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import math
from pathlib import Path
from typing import Any

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v254_landmark_fit_seamless_source as v254
from neyrobot_prod import selfie_v256_large_scale_source_pixels as v256
from neyrobot_prod import selfie_v262_landmark_field_compositor as v262
from neyrobot_prod import selfie_v263_diagnostics as v263diag

VERSION = "v263-dense-identity-lock-2026-08-27"
_INSTALLED = False
_BASE_V262_ENFORCE = None

_PIPNET_URL = "https://github.com/yakhyo/pipnet-onnx/releases/download/weights/pipnet_r18_300w_celeba_68.onnx"
_PIPNET_SHA256 = "63fa56fd4b8f6ccc4b88f2b36e00fa3d8c21a2c4244ab9381e8b432cef35197b"
_PIPNET_PATH = Path("/tmp/neyrobot_models/pipnet_r18_300w_celeba_68.onnx")
_MOBILEFACE_URL = "https://github.com/yakhyo/uniface/releases/download/weights/mobilenetv2.onnx"
_MOBILEFACE_SHA256 = "38b148284dd48cc898d5d4453104252fbdcbacc105fe3f0b80e78954d9d20d89"
_MOBILEFACE_PATH = Path("/tmp/neyrobot_models/mobilenetv2.onnx")
_MODEL_LOCK = asyncio.Lock()

_DENSE_INPUT = 256
_DENSE_COUNT = 68
_OUTLINE = tuple(range(0, 17))
_RIGHT_BROW = tuple(range(17, 22))
_LEFT_BROW = tuple(range(22, 27))
_NOSE = tuple(range(27, 36))
_RIGHT_EYE = tuple(range(36, 42))
_LEFT_EYE = tuple(range(42, 48))
_MOUTH = tuple(range(48, 68))
_CENTRAL_CHIN = (7, 8, 9)
_INNER_FACE = tuple(range(17, 68)) + _CENTRAL_CHIN
_EYES = _RIGHT_EYE + _LEFT_EYE

_STANDARD_TARGET_WEIGHTS = {
    "outline": 0.26, "brow": 0.10, "nose": 0.055,
    "eye": 0.045, "mouth": 0.060, "chin": 0.080,
}
_STRICT_TARGET_WEIGHTS = {
    "outline": 0.14, "brow": 0.035, "nose": 0.018,
    "eye": 0.012, "mouth": 0.020, "chin": 0.030,
}
_STANDARD_MAX_SHIFT_FRACTION = 0.055
_STRICT_MAX_SHIFT_FRACTION = 0.028
_DENSE_SIGMA_FRACTION = 0.046
_DENSE_SIGMA_MIN = 12.0
_DENSE_SIGMA_MAX = 36.0
_STRUCTURE_SIGMA_FINE = 1.30
_STRUCTURE_SIGMA_COARSE = 5.5
_STANDARD_STRUCTURE_STRENGTH = 0.38
_STRICT_STRUCTURE_STRENGTH = 0.58
_STANDARD_DETAIL_STRENGTH = 0.74
_STRICT_DETAIL_STRENGTH = 0.84
_BOUNDARY_FRACTION = 0.045
_BOUNDARY_MIN = 16.0
_BOUNDARY_MAX = 38.0

_IDENTITY_COSINE_MIN = 0.50
_INNER_FACE_NME_MAX = 0.080
_EYE_ERROR_MAX = 0.075
_INTEROCULAR_RATIO_DELTA_MAX = 0.065
_NOSE_MOUTH_AXIS_DELTA_MAX = 0.075
_EYE_ASYMMETRY_MAX = 0.085

_PIPNET_NET = None
_MOBILEFACE_NET = None


def _modules():
    return v262._modules()


def _log(message: str, *args: Any) -> None:
    v253._log(message, *args)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def _ensure_verified_model(path: Path, url: str, digest: str, label: str) -> Path:
    if path.exists():
        with contextlib.suppress(Exception):
            if _sha256_file(path) == digest:
                return path
        with contextlib.suppress(Exception):
            path.unlink()

    async with _MODEL_LOCK:
        if path.exists() and _sha256_file(path) == digest:
            return path
        v241, *_ = _modules()
        runtime = v241._runtime()
        httpx_mod = getattr(runtime, "httpx", None) if runtime is not None else None
        if httpx_mod is None:
            import httpx as httpx_mod
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".download")
        timeout = httpx_mod.Timeout(90.0, connect=25.0, read=90.0, write=30.0, pool=25.0)
        async with httpx_mod.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = bytes(response.content or b"")
        actual = hashlib.sha256(payload).hexdigest()
        if actual != digest:
            raise RuntimeError(f"{label} checksum mismatch: {actual}")
        tmp.write_bytes(payload)
        tmp.replace(path)
        _log("AI_SELFIE_V263_MODEL status=downloaded model=%s bytes=%s sha256=%s", label, len(payload), actual[:16])
        return path


async def _ensure_identity_models() -> tuple[Path, Path]:
    dense = await _ensure_verified_model(_PIPNET_PATH, _PIPNET_URL, _PIPNET_SHA256, "pipnet_68_mit")
    recognition = await _ensure_verified_model(
        _MOBILEFACE_PATH, _MOBILEFACE_URL, _MOBILEFACE_SHA256, "mobileface_v2_mit"
    )
    return dense, recognition


def _pipnet_net(model_path: Path):
    global _PIPNET_NET
    if _PIPNET_NET is None:
        import cv2
        _PIPNET_NET = cv2.dnn.readNetFromONNX(str(model_path))
    return _PIPNET_NET


def _mobileface_net(model_path: Path):
    global _MOBILEFACE_NET
    if _MOBILEFACE_NET is None:
        import cv2
        _MOBILEFACE_NET = cv2.dnn.readNetFromONNX(str(model_path))
    return _MOBILEFACE_NET


def _similarity_transform(source_pts, target_pts):
    """Identity-safe global pose fit: rotation + UNIFORM scale + translation only."""
    import cv2
    import numpy as np
    src = np.asarray(source_pts, dtype=np.float32).reshape(5, 2)
    dst = np.asarray(target_pts, dtype=np.float32).reshape(5, 2)
    matrix, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
    if matrix is None:
        raise RuntimeError("V263 could not estimate identity-safe similarity transform")
    projected = v262._project_points(matrix, src)
    rms = float(np.sqrt(np.mean(np.sum((projected - dst) ** 2, axis=1))))
    return np.asarray(matrix, dtype=np.float32), rms


def _dense_landmarks_68(frame, bbox, model_path: Path, *, label: str):
    """Run MIT PIPNet 300W/CelebA 68-point landmarks in frame coordinates."""
    import cv2
    import numpy as np
    h, w = frame.shape[:2]
    x, y, fw, fh = [float(v) for v in bbox]
    if fw < 80 or fh < 80:
        raise RuntimeError(f"V263 dense {label} face too small: {fw:.0f}x{fh:.0f}")

    x1 = max(0, int(round(x - fw * 0.10)))
    y1 = max(0, int(round(y + fh * 0.10)))
    x2 = min(w - 1, int(round(x + fw + fw * 0.10)))
    y2 = min(h - 1, int(round(y + fh + fh * 0.10)))
    if x2 <= x1 + 32 or y2 <= y1 + 32:
        raise RuntimeError(f"V263 invalid PIPNet crop for {label}")
    crop = frame[y1:y2 + 1, x1:x2 + 1]
    crop_h, crop_w = crop.shape[:2]
    resized = cv2.resize(crop, (_DENSE_INPUT, _DENSE_INPUT), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32)
    mean = np.asarray([0.485, 0.456, 0.406], dtype=np.float32) * 255.0
    std = np.asarray([0.229, 0.224, 0.225], dtype=np.float32) * 255.0
    blob = np.transpose((rgb - mean) / std, (2, 0, 1))[None, ...].astype(np.float32)

    pip_ckpt = v263diag.checkpoint(
        _log, f"pipnet_{label}.before",
        dims=f"frame={w}x{h};crop={crop_w}x{crop_h};input=256x256",
        arrays=(("frame", frame), ("crop", crop), ("resized", resized), ("blob", blob)),
    )
    net = _pipnet_net(model_path)
    net.setInput(blob)
    try:
        cls_map, offset_x, offset_y, _nb_x, _nb_y = net.forward(
            ["cls_map", "offset_x", "offset_y", "nb_x", "nb_y"]
        )
    except Exception:
        outputs = net.forward(net.getUnconnectedOutLayersNames())
        if len(outputs) < 3:
            raise RuntimeError(f"V263 PIPNet returned {len(outputs)} outputs")
        cls_map, offset_x, offset_y = outputs[:3]

    v263diag.checkpoint(
        _log, f"pipnet_{label}.after", started=pip_ckpt,
        dims=f"frame={w}x{h};crop={crop_w}x{crop_h};input=256x256",
        arrays=(("cls_map", cls_map), ("offset_x", offset_x), ("offset_y", offset_y)),
    )
    cls_map = np.asarray(cls_map, dtype=np.float32)
    offset_x = np.asarray(offset_x, dtype=np.float32)
    offset_y = np.asarray(offset_y, dtype=np.float32)
    if cls_map.ndim != 4 or int(cls_map.shape[1]) != _DENSE_COUNT:
        raise RuntimeError(f"V263 PIPNet cls shape invalid: {tuple(cls_map.shape)}")
    feat_h, feat_w = int(cls_map.shape[2]), int(cls_map.shape[3])
    flat = cls_map.reshape(_DENSE_COUNT, feat_h * feat_w)
    ids = np.argmax(flat, axis=1)
    rows = (ids // feat_w).astype(np.float32)
    cols = (ids % feat_w).astype(np.float32)
    ox = np.take_along_axis(offset_x.reshape(_DENSE_COUNT, -1), ids[:, None], axis=1).reshape(-1)
    oy = np.take_along_axis(offset_y.reshape(_DENSE_COUNT, -1), ids[:, None], axis=1).reshape(-1)
    norm_x = (cols + ox) / max(1.0, float(feat_w))
    norm_y = (rows + oy) / max(1.0, float(feat_h))
    dense = np.stack([norm_x * crop_w + x1, norm_y * crop_h + y1], axis=1).astype(np.float32)
    dense[:, 0] = np.clip(dense[:, 0], 0.0, float(max(0, w - 1)))
    dense[:, 1] = np.clip(dense[:, 1], 0.0, float(max(0, h - 1)))
    _log(
        "AI_SELFIE_V263_DENSE_LANDMARKS label=%s geometry_mode=pipnet_68 landmarks=68 "
        "face=%.0f,%.0f,%.0f,%.0f crop=%sx%s input=256x256",
        label, x, y, fw, fh, crop_w, crop_h,
    )
    return dense


def _target_weights(strict: bool):
    import numpy as np
    cfg = _STRICT_TARGET_WEIGHTS if strict else _STANDARD_TARGET_WEIGHTS
    weights = np.full((_DENSE_COUNT,), float(cfg["mouth"]), dtype=np.float32)
    weights[list(_OUTLINE)] = float(cfg["outline"])
    weights[list(_RIGHT_BROW + _LEFT_BROW)] = float(cfg["brow"])
    weights[list(_NOSE)] = float(cfg["nose"])
    weights[list(_EYES)] = float(cfg["eye"])
    weights[list(_MOUTH)] = float(cfg["mouth"])
    weights[list(_CENTRAL_CHIN)] = float(cfg["chin"])
    return weights


def _desired_identity_geometry(projected_source, target_dense, face_min: float, *, strict: bool):
    """Source is identity authority; target contributes only bounded pose adaptation."""
    import numpy as np
    projected = np.asarray(projected_source, dtype=np.float32).reshape(_DENSE_COUNT, 2)
    target = np.asarray(target_dense, dtype=np.float32).reshape(_DENSE_COUNT, 2)
    raw_delta = target - projected
    weights = _target_weights(strict)[:, None]
    shift = raw_delta * weights
    max_fraction = _STRICT_MAX_SHIFT_FRACTION if strict else _STANDARD_MAX_SHIFT_FRACTION
    max_shift = max(4.0, float(face_min) * float(max_fraction))
    norms = np.linalg.norm(shift, axis=1, keepdims=True)
    shift *= np.minimum(1.0, max_shift / np.maximum(norms, 1.0e-6))
    return projected + shift


def _dense_deform_roi(warped, projected_dense, desired_dense, box, face_min: float):
    """One 68-point smooth inverse field; never a per-eye or per-feature patch."""
    import cv2
    import numpy as np
    x0, y0, x1, y1 = [int(v) for v in box]
    roi_w, roi_h = x1 - x0, y1 - y0
    sigma = max(_DENSE_SIGMA_MIN, min(_DENSE_SIGMA_MAX, float(face_min) * _DENSE_SIGMA_FRACTION))
    field_ckpt = v263diag.checkpoint(
        _log, "dense_field.before", dims=f"roi={roi_w}x{roi_h};face_min={float(face_min):.1f}",
        arrays=(("warped", warped), ("projected_dense", projected_dense), ("desired_dense", desired_dense)),
    )
    gx = np.arange(x0, x1, dtype=np.float32)[None, :]
    gy = np.arange(y0, y1, dtype=np.float32)[:, None]
    sum_w = np.zeros((roi_h, roi_w), dtype=np.float32)
    sum_dx = np.zeros((roi_h, roi_w), dtype=np.float32)
    sum_dy = np.zeros((roi_h, roi_w), dtype=np.float32)
    projected = np.asarray(projected_dense, dtype=np.float32).reshape(_DENSE_COUNT, 2)
    desired = np.asarray(desired_dense, dtype=np.float32).reshape(_DENSE_COUNT, 2)
    residuals = desired - projected
    for idx in range(_DENSE_COUNT):
        cx, cy = float(desired[idx, 0]), float(desired[idx, 1])
        dx = (gx - cx) / max(1.0, sigma)
        dy = (gy - cy) / max(1.0, sigma)
        weight = np.exp(-0.5 * (dx * dx + dy * dy)).astype(np.float32, copy=False)
        sum_w += weight
        sum_dx += weight * float(residuals[idx, 0])
        sum_dy += weight * float(residuals[idx, 1])
    inv = 1.0 / np.maximum(sum_w, 1.0e-6)
    support = np.clip(sum_w, 0.0, 1.0)
    disp_x = sum_dx * inv * support
    disp_y = sum_dy * inv * support
    map_x = np.broadcast_to(gx, (roi_h, roi_w)).copy() - disp_x
    map_y = np.broadcast_to(gy, (roi_h, roi_w)).copy() - disp_y
    v263diag.checkpoint(
        _log, "dense_field.after", started=field_ckpt, dims=f"roi={roi_w}x{roi_h}",
        arrays=(("sum_w", sum_w), ("sum_dx", sum_dx), ("sum_dy", sum_dy), ("inv", inv),
                ("support", support), ("disp_x", disp_x), ("disp_y", disp_y),
                ("map_x", map_x), ("map_y", map_y)),
    )
    remap_ckpt = v263diag.checkpoint(
        _log, "remap.before", dims=f"roi={roi_w}x{roi_h}",
        arrays=(("warped", warped), ("map_x", map_x), ("map_y", map_y)),
    )
    corrected = cv2.remap(
        warped, map_x, map_y, interpolation=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    v263diag.checkpoint(
        _log, "remap.after", started=remap_ckpt, dims=f"roi={roi_w}x{roi_h}",
        arrays=(("corrected_roi", corrected), ("map_x", map_x), ("map_y", map_y)),
    )
    return corrected, sigma, residuals


def _structure_first_compose(corrected, target, mask, box, face_min: float, *, strict: bool):
    """Geometry first, target colour second, controlled source structure/detail last."""
    import cv2
    import numpy as np
    compositor_ckpt = v263diag.checkpoint(
        _log, "structure_first_compositor.before",
        dims=f"frame={target.shape[1]}x{target.shape[0]}",
        arrays=(("corrected", corrected), ("target", target), ("mask", mask)),
    )
    colour_ckpt = v263diag.checkpoint(
        _log, "colour_match.before", arrays=(("corrected", corrected), ("target", target), ("mask", mask)),
    )
    matched = v253._colour_match_lab(corrected, target, mask)
    v263diag.checkpoint(
        _log, "colour_match.after", started=colour_ckpt, arrays=(("matched", matched), ("target", target), ("mask", mask)),
    )
    ys, xs = np.where(mask > 80)
    if xs.size == 0 or ys.size == 0:
        raise RuntimeError("V263 identity mask empty")
    center = (
        int(round((int(xs.min()) + int(xs.max())) * 0.5)),
        int(round((int(ys.min()) + int(ys.max())) * 0.5)),
    )
    clone_ckpt = v263diag.checkpoint(
        _log, "seamless_clone.before", arrays=(("matched", matched), ("target", target), ("mask", mask)),
    )
    try:
        integrated = cv2.seamlessClone(matched, target, mask, center, cv2.NORMAL_CLONE)
        v263diag.checkpoint(
            _log, "seamless_clone.after", started=clone_ckpt, arrays=(("integrated", integrated),), note="poisson",
        )
        blend_mode = "poisson_structure_first"
    except Exception as exc:
        _log("AI_SELFIE_V263_POISSON status=fallback reason=%s:%s", type(exc).__name__, str(exc)[:220])
        integrated = target.copy()
        v263diag.checkpoint(
            _log, "seamless_clone.after", started=clone_ckpt, arrays=(("integrated", integrated),), note="fallback",
        )
        blend_mode = "target_plus_controlled_structure"

    x0, y0, x1, y1 = [int(v) for v in box]
    mask_roi = mask[y0:y1, x0:x1]
    binary = (mask_roi > 80).astype(np.uint8)
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    boundary = max(_BOUNDARY_MIN, min(_BOUNDARY_MAX, float(face_min) * _BOUNDARY_FRACTION))
    alpha = v262._smoothstep01(distance / max(1.0, boundary)) * binary.astype(np.float32)
    src = matched[y0:y1, x0:x1].astype(np.float32)
    base = integrated[y0:y1, x0:x1].astype(np.float32)
    fine_low = cv2.GaussianBlur(src, (0, 0), sigmaX=_STRUCTURE_SIGMA_FINE, sigmaY=_STRUCTURE_SIGMA_FINE)
    coarse_low = cv2.GaussianBlur(src, (0, 0), sigmaX=_STRUCTURE_SIGMA_COARSE, sigmaY=_STRUCTURE_SIGMA_COARSE)
    structure = fine_low - coarse_low
    detail = src - fine_low
    structure_strength = _STRICT_STRUCTURE_STRENGTH if strict else _STANDARD_STRUCTURE_STRENGTH
    detail_strength = _STRICT_DETAIL_STRENGTH if strict else _STANDARD_DETAIL_STRENGTH
    composed = np.clip(
        base
        + structure * (alpha * structure_strength)[:, :, None]
        + detail * (alpha * detail_strength)[:, :, None],
        0.0, 255.0,
    ).astype(np.uint8)
    final = integrated
    final[y0:y1, x0:x1] = composed
    v263diag.checkpoint(
        _log, "structure_first_compositor.after", started=compositor_ckpt,
        dims=f"frame={target.shape[1]}x{target.shape[0]};roi={x1-x0}x{y1-y0}",
        arrays=(("matched", matched), ("integrated", integrated), ("src_f32", src), ("base_f32", base),
                ("fine_low", fine_low), ("coarse_low", coarse_low), ("structure", structure),
                ("detail", detail), ("composed", composed), ("final", final)),
    )
    return final, blend_mode, boundary, structure_strength, detail_strength


def _alignment5_from_dense68(dense):
    """Build semantic 5-point alignment from dense geometry, ordered by image x."""
    import numpy as np
    pts = np.asarray(dense, dtype=np.float32).reshape(_DENSE_COUNT, 2)
    eye_a = pts[list(_RIGHT_EYE)].mean(axis=0)
    eye_b = pts[list(_LEFT_EYE)].mean(axis=0)
    eyes = sorted((eye_a, eye_b), key=lambda p: float(p[0]))
    nose = pts[30]
    mouth_a, mouth_b = pts[48], pts[54]
    mouths = sorted((mouth_a, mouth_b), key=lambda p: float(p[0]))
    return np.asarray([eyes[0], eyes[1], nose, mouths[0], mouths[1]], dtype=np.float32)


def _mobileface_embedding(frame, dense68, model_path: Path, *, label: str = "unspecified"):
    import cv2
    import numpy as np
    src5 = _alignment5_from_dense68(dense68)
    template = np.asarray(
        [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
         [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32
    )
    matrix, _ = cv2.estimateAffinePartial2D(src5, template, method=cv2.LMEDS)
    if matrix is None:
        raise RuntimeError("V263 MobileFace alignment failed")
    aligned = cv2.warpAffine(frame, matrix, (112, 112), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    blob = cv2.dnn.blobFromImage(
        aligned, scalefactor=1.0 / 127.5, size=(112, 112),
        mean=(127.5, 127.5, 127.5), swapRB=True, crop=False
    )
    mobile_ckpt = v263diag.checkpoint(
        _log, f"mobileface_{label}.before", dims=f"frame={frame.shape[1]}x{frame.shape[0]};input=112x112",
        arrays=(("frame", frame), ("aligned", aligned), ("blob", blob)),
    )
    net = _mobileface_net(model_path)
    net.setInput(blob)
    raw_feature = net.forward()
    v263diag.checkpoint(
        _log, f"mobileface_{label}.after", started=mobile_ckpt, arrays=(("raw_feature", raw_feature),),
    )
    feature = np.asarray(raw_feature, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(feature))
    if not math.isfinite(norm) or norm < 1.0e-8:
        raise RuntimeError("V263 MobileFace produced invalid embedding")
    return feature / norm


def _eye_shape_asymmetry(points):
    import numpy as np
    pts = np.asarray(points, dtype=np.float32)
    right = pts[list(_RIGHT_EYE)]
    left = pts[list(_LEFT_EYE)]
    def signature(eye):
        width = max(1.0e-6, float(np.ptp(eye[:, 0])))
        height = max(1.0e-6, float(np.ptp(eye[:, 1])))
        return height / width
    return abs(signature(left) - signature(right))


def _quality_metrics(source_embedding, final_embedding, desired_dense, final_dense):
    import numpy as np
    desired = np.asarray(desired_dense, dtype=np.float32).reshape(_DENSE_COUNT, 2)
    final = np.asarray(final_dense, dtype=np.float32).reshape(_DENSE_COUNT, 2)
    right_center_expected = desired[list(_RIGHT_EYE)].mean(axis=0)
    left_center_expected = desired[list(_LEFT_EYE)].mean(axis=0)
    right_center_final = final[list(_RIGHT_EYE)].mean(axis=0)
    left_center_final = final[list(_LEFT_EYE)].mean(axis=0)
    inter_expected = max(1.0, float(np.linalg.norm(left_center_expected - right_center_expected)))
    inter_final = max(1.0, float(np.linalg.norm(left_center_final - right_center_final)))

    def nme(indices):
        idx = list(indices)
        return float(np.mean(np.linalg.norm(final[idx] - desired[idx], axis=1)) / inter_expected)

    left_eye_error = nme(_LEFT_EYE)
    right_eye_error = nme(_RIGHT_EYE)
    inner_nme = nme(_INNER_FACE)
    interocular_delta = abs(inter_final / inter_expected - 1.0)
    nose_expected = desired[list(_NOSE)].mean(axis=0)
    mouth_expected = desired[list(_MOUTH)].mean(axis=0)
    nose_final = final[list(_NOSE)].mean(axis=0)
    mouth_final = final[list(_MOUTH)].mean(axis=0)
    expected_axis = mouth_expected - nose_expected
    final_axis = mouth_final - nose_final
    nose_mouth_axis_delta = float(np.linalg.norm(final_axis - expected_axis) / inter_expected)
    embedding_cosine = float(np.dot(source_embedding, final_embedding))
    eye_asymmetry = abs(_eye_shape_asymmetry(final) - _eye_shape_asymmetry(desired))
    return {
        "identity_similarity_cosine": embedding_cosine,
        "left_eye_error": left_eye_error,
        "right_eye_error": right_eye_error,
        "interocular_ratio_delta": interocular_delta,
        "nose_mouth_axis_delta": nose_mouth_axis_delta,
        "inner_face_landmark_nme": inner_nme,
        "eye_asymmetry_delta": float(eye_asymmetry),
    }


def _quality_gate(metrics: dict[str, float]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    checks = (
        ("identity_similarity_cosine", float(metrics["identity_similarity_cosine"]), _IDENTITY_COSINE_MIN, "min"),
        ("inner_face_landmark_nme", float(metrics["inner_face_landmark_nme"]), _INNER_FACE_NME_MAX, "max"),
        ("left_eye_error", float(metrics["left_eye_error"]), _EYE_ERROR_MAX, "max"),
        ("right_eye_error", float(metrics["right_eye_error"]), _EYE_ERROR_MAX, "max"),
        ("interocular_ratio_delta", float(metrics["interocular_ratio_delta"]), _INTEROCULAR_RATIO_DELTA_MAX, "max"),
        ("nose_mouth_axis_delta", float(metrics["nose_mouth_axis_delta"]), _NOSE_MOUTH_AXIS_DELTA_MAX, "max"),
        ("eye_asymmetry_delta", float(metrics["eye_asymmetry_delta"]), _EYE_ASYMMETRY_MAX, "max"),
    )
    for name, value, threshold, direction in checks:
        if not math.isfinite(value):
            failures.append(f"{name}=nonfinite")
        elif direction == "min" and value < threshold:
            failures.append(f"{name}={value:.4f}<{threshold:.4f}")
        elif direction == "max" and value > threshold:
            failures.append(f"{name}={value:.4f}>{threshold:.4f}")
    return not failures, failures


def _log_quality(metrics: dict[str, float], *, path: str, passed: bool, strict_retry_triggered: bool, strict_retry_success: bool, failures: list[str]):
    _log(
        "AI_SELFIE_V263_IDENTITY_QUALITY status=%s path=%s geometry_mode=pipnet_68 landmarks=68 "
        "identity_similarity_cosine=%.4f left_eye_error=%.4f right_eye_error=%.4f "
        "interocular_ratio_delta=%.4f nose_mouth_axis_delta=%.4f inner_face_landmark_nme=%.4f "
        "eye_asymmetry_delta=%.4f strict_retry_triggered=%s strict_retry_success=%s failures=%s",
        "pass" if passed else "fail", path,
        metrics["identity_similarity_cosine"], metrics["left_eye_error"], metrics["right_eye_error"],
        metrics["interocular_ratio_delta"], metrics["nose_mouth_axis_delta"], metrics["inner_face_landmark_nme"],
        metrics["eye_asymmetry_delta"], str(strict_retry_triggered).lower(), str(strict_retry_success).lower(),
        "none" if not failures else "|".join(failures),
    )


def _transfer_attempt(stage1: bytes, source: bytes, yunet_path: Path, dense_path: Path, recognition_path: Path, *, strict: bool):
    import cv2
    import numpy as np
    target = v253._decode_bgr(stage1)
    source_im = v253._decode_bgr(source)
    th, tw = target.shape[:2]
    attempt_name = "strict" if strict else "standard"
    v263diag.checkpoint(
        _log, f"transfer_{attempt_name}.start", dims=f"target={tw}x{th};source={source_im.shape[1]}x{source_im.shape[0]}",
        arrays=(("target", target), ("source", source_im)),
    )
    firewall_x = max(256, min(tw, int(round(tw * 0.55))))
    source_bbox, source_pts5 = v253._yunet_face(source_im, yunet_path, label="source_photo3_v263")
    target_bbox, target_pts5 = v253._yunet_face(target[:, :firewall_x], yunet_path, label="target_person_a_v263")
    matrix, sim_rms = _similarity_transform(source_pts5, target_pts5)

    linear = np.asarray(matrix[:, :2], dtype=np.float64)
    det = float(np.linalg.det(linear))
    scale = math.sqrt(abs(det)) if det != 0.0 else 0.0
    _, _, sfw, sfh = [float(v) for v in source_bbox]
    _, _, tfw, tfh = [float(v) for v in target_bbox]
    native_face_short = min(sfw, sfh)
    face_min = min(tfw, tfh)
    if not (0.20 <= scale <= v256._MAX_REAL_SOURCE_SCALE):
        raise RuntimeError(f"V263 invalid similarity scale={scale:.3f}")
    if native_face_short < v256._MIN_NATIVE_FACE_SHORT:
        raise RuntimeError(f"V263 source sampling too small: native_short={native_face_short:.1f}")

    src_pip = v263diag.checkpoint(_log, f"{attempt_name}.pipnet_source.before", arrays=(("source", source_im),))
    source_dense = _dense_landmarks_68(source_im, source_bbox, dense_path, label="source_photo3")
    v263diag.checkpoint(_log, f"{attempt_name}.pipnet_source.after", started=src_pip, arrays=(("source_dense", source_dense),))
    tgt_pip = v263diag.checkpoint(_log, f"{attempt_name}.pipnet_target.before", arrays=(("target", target),))
    target_dense = _dense_landmarks_68(target, target_bbox, dense_path, label="target_person_a")
    v263diag.checkpoint(_log, f"{attempt_name}.pipnet_target.after", started=tgt_pip, arrays=(("target_dense", target_dense),))
    projected_dense = v262._project_points(matrix, source_dense)
    desired_dense = _desired_identity_geometry(projected_dense, target_dense, face_min, strict=strict)
    warp_ckpt = v263diag.checkpoint(
        _log, f"{attempt_name}.warp_affine.before", dims=f"output={tw}x{th}", arrays=(("source", source_im), ("matrix", matrix)),
    )
    warped = cv2.warpAffine(
        source_im, matrix, (tw, th), flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    v263diag.checkpoint(
        _log, f"{attempt_name}.warp_affine.after", started=warp_ckpt, dims=f"output={tw}x{th}", arrays=(("warped", warped),),
    )
    mask_ckpt = v263diag.checkpoint(
        _log, f"{attempt_name}.anatomical_mask.before", dims=f"frame={tw}x{th};firewall_x={firewall_x}", arrays=(("target", target),),
    )
    mask = v262._landmark_anatomy_mask(target.shape, target_bbox, target_pts5, firewall_x)
    v263diag.checkpoint(
        _log, f"{attempt_name}.anatomical_mask.after", started=mask_ckpt, arrays=(("mask", mask),),
    )
    mask_pixels = int((mask > 80).sum())
    # Preserve the original 12k guard for normal/large faces, but scale the
    # minimum for legitimately small PERSON-A faces. An absolute 12k floor
    # false-rejected the two-person 136px target despite a valid anatomical hull.
    min_mask_pixels = int(round(min(12000.0, max(3200.0, face_min * face_min * 0.30))))
    if mask_pixels < min_mask_pixels:
        raise RuntimeError(
            f"V263 anatomical identity mask too small: {mask_pixels} < {min_mask_pixels}"
        )
    pad = int(round(max(30.0, min(76.0, face_min * 0.090))))
    box = v262._mask_box(mask, pad=pad, firewall_x=firewall_x)
    x0, y0, x1, y1 = box
    deform_ckpt = v263diag.checkpoint(
        _log, f"{attempt_name}.dense_deform.before", dims=f"roi={x1-x0}x{y1-y0}", arrays=(("warped", warped),),
    )
    corrected_roi, field_sigma, dense_residuals = _dense_deform_roi(
        warped, projected_dense, desired_dense, box, face_min
    )
    v263diag.checkpoint(
        _log, f"{attempt_name}.dense_deform.after", started=deform_ckpt, arrays=(("corrected_roi", corrected_roi), ("dense_residuals", dense_residuals)),
    )
    corrected = warped.copy()
    corrected[y0:y1, x0:x1] = corrected_roi
    compose_ckpt = v263diag.checkpoint(
        _log, f"{attempt_name}.structure_first_compositor.before", arrays=(("corrected", corrected), ("target", target), ("mask", mask)),
    )
    final, blend_mode, boundary, structure_strength, detail_strength = _structure_first_compose(
        corrected, target, mask, box, face_min, strict=strict
    )
    v263diag.checkpoint(
        _log, f"{attempt_name}.structure_first_compositor.after", started=compose_ckpt, arrays=(("final", final),),
    )
    final[:, firewall_x:] = target[:, firewall_x:]

    final_bbox, _final_pts5 = v253._yunet_face(final[:, :firewall_x], yunet_path, label="final_person_a_v263")
    final_dense = _dense_landmarks_68(final, final_bbox, dense_path, label="final_person_a")
    source_embedding = _mobileface_embedding(source_im, source_dense, recognition_path, label="source")
    final_embedding = _mobileface_embedding(final, final_dense, recognition_path, label="final")
    metrics_ckpt = v263diag.checkpoint(
        _log, f"{attempt_name}.metrics.before", arrays=(("source_embedding", source_embedding), ("final_embedding", final_embedding),
                ("desired_dense", desired_dense), ("final_dense", final_dense)),
    )
    metrics = _quality_metrics(source_embedding, final_embedding, desired_dense, final_dense)
    v263diag.checkpoint(_log, f"{attempt_name}.metrics.after", started=metrics_ckpt)

    ok, encoded = cv2.imencode(".png", final, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("V263 OpenCV PNG encode failed")
    output = bytes(encoded.tobytes())
    max_dense_shift = float(np.linalg.norm(dense_residuals, axis=1).max())
    path = "strict" if strict else "standard"
    _log(
        "AI_SELFIE_V263_TRANSFER status=success path=%s method=dense68_identity_field_structure_first "
        "geometry_mode=pipnet_68 landmarks=68 source_face=%.0fx%.0f target_face=%.0fx%.0f "
        "global_transform=similarity similarity_rms=%.2f scale=%.3f native_face_short=%.1f "
        "max_dense_shift=%.2f field_sigma=%.1f mask=landmark_anatomical_hull mask_pixels=%s mask_min_pixels=%s roi=%sx%s "
        "blend=%s structure_first=true structure_strength=%.2f detail_strength=%.2f boundary=%.1f "
        "independent_eye_patch=false raw_low_frequency_reinject=false solid_source_core=false no_neck=true "
        "person_b_untouched=true delivery=v253_original_document output=png bytes=%s source_pixels=true synthetic_face=false",
        path, sfw, sfh, tfw, tfh, sim_rms, scale, native_face_short, max_dense_shift, field_sigma,
        mask_pixels, min_mask_pixels, x1 - x0, y1 - y0, blend_mode, structure_strength, detail_strength, boundary, len(output),
    )
    return output, metrics, desired_dense


async def _true_face_transfer_v263(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    if int(source_photo_no) != 3:
        raise RuntimeError(f"V263 requires authoritative photo #3, got #{source_photo_no}")
    yunet_path = await v253._ensure_yunet_model()
    dense_path, recognition_path = await _ensure_identity_models()

    standard_ckpt = v263diag.checkpoint(_log, "standard_attempt.before", note="strict=false")
    standard, metrics, _ = _transfer_attempt(
        bytes(stage1 or b""), bytes(source or b""), yunet_path, dense_path, recognition_path, strict=False
    )
    v263diag.checkpoint(_log, "standard_attempt.after", started=standard_ckpt, note="strict=false")
    gate_ckpt = v263diag.checkpoint(_log, "standard_quality_gate.before")
    passed, failures = _quality_gate(metrics)
    v263diag.checkpoint(_log, "standard_quality_gate.after", started=gate_ckpt, note="pass" if passed else "fail")
    if passed:
        _log_quality(metrics, path="standard", passed=True, strict_retry_triggered=False, strict_retry_success=False, failures=[])
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_dense68_identity_v263_standard"
        runtime.AI_SELFIE_LAST_IDENTITY_PATH = "standard"
        runtime.AI_SELFIE_LAST_IDENTITY_METRICS = dict(metrics)
        return standard, "opencv_dense68_identity_lock_standard"

    _log_quality(metrics, path="standard", passed=False, strict_retry_triggered=True, strict_retry_success=False, failures=failures)
    _log("AI_SELFIE_V263_STRICT_RETRY strict_retry_triggered=true reason=identity_quality_gate")
    strict_ckpt = v263diag.checkpoint(_log, "strict_retry.before", note="strict=true")
    strict, strict_metrics, _ = _transfer_attempt(
        bytes(stage1 or b""), bytes(source or b""), yunet_path, dense_path, recognition_path, strict=True
    )
    v263diag.checkpoint(_log, "strict_retry.transfer_after", started=strict_ckpt, note="strict=true")
    strict_gate_ckpt = v263diag.checkpoint(_log, "strict_quality_gate.before")
    strict_passed, strict_failures = _quality_gate(strict_metrics)
    v263diag.checkpoint(
        _log, "strict_quality_gate.after", started=strict_gate_ckpt, note="pass" if strict_passed else "fail",
    )
    v263diag.checkpoint(
        _log, "strict_retry.after", started=strict_ckpt, note="pass" if strict_passed else "fail",
    )
    _log_quality(
        strict_metrics, path="strict", passed=strict_passed,
        strict_retry_triggered=True, strict_retry_success=strict_passed, failures=strict_failures,
    )
    runtime.AI_SELFIE_LAST_IDENTITY_PATH = "strict"
    runtime.AI_SELFIE_LAST_IDENTITY_METRICS = dict(strict_metrics)
    if strict_passed:
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_dense68_identity_v263_strict"
        return strict, "opencv_dense68_identity_lock_strict"

    _log(
        "AI_SELFIE_V263_IDENTITY_REJECT status=rejected strict_retry_triggered=true strict_retry_success=false "
        "reason=%s person_b_untouched=true delivery=blocked",
        "|".join(strict_failures) if strict_failures else "quality_gate_unknown",
    )
    raise RuntimeError("V263 identity quality gate rejected final PERSON-A after strict retry")


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V262 safety base, then make V263 the final PERSON-A transfer owner."""
    global _BASE_V262_ENFORCE
    if not callable(_BASE_V262_ENFORCE):
        raise RuntimeError("V263 base V262 enforcer was not captured")
    _BASE_V262_ENFORCE(bind_generate=bind_generate)
    v241, v245, v246, v247, v249, v250, v251, v252, transfer, google, ui, delivery = _modules()
    transfer._true_face_transfer = _true_face_transfer_v263
    delivery._deliver = v253._deliver_original

    from neyrobot_prod import selfie_v254_landmark_fit_seamless_source as v254_mod
    from neyrobot_prod import selfie_v255_source_face_gate as v255
    from neyrobot_prod import selfie_v257_native_sampling_guard as v257
    from neyrobot_prod import selfie_v258_inner_face_integration as v258
    from neyrobot_prod import selfie_v259_eye_landmark_protection as v259
    from neyrobot_prod import selfie_v260_eye_roi_memory_safe as v260
    from neyrobot_prod import selfie_v261_edge_harmonization as v261

    for mod in (v262, v261, v260, v259, v258, v257, v256, v255, v254_mod, v253, v252, v251, v247, v246):
        mod.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)
    for mod in (
        transfer, google, ui, delivery, v241, v245, v246, v247, v249, v250, v251, v252,
        v253, v254_mod, v255, v256, v257, v258, v259, v260, v261, v262,
    ):
        mod.VERSION = VERSION

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.AI_SELFIE_SEND_AS_DOCUMENT = True
        runtime.CELEBRITY_SELFIE_ROUTE = "v263-v262-base-dense68-identity-lock-quality-gate-strict-retry-lossless-document"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini scene/PERSON-B -> V262 safety base -> YuNet identity-safe similarity -> "
            "PIPNet 68-point source-dominant geometry -> anatomical structure-first blend -> "
            "MobileFace+dense identity quality gate -> automatic strict retry -> V253 original document"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V263_ENFORCE status=ok base=v262 landmarks=68 geometry=source_dominant_dense_identity_field "
        "quality_gate=mobileface_plus_dense strict_retry=automatic independent_eye_patch=false "
        "mask=landmark_anatomical_hull source_gate=anatomical_inner_face no_neck=true "
        "person_b=pixel_locked delivery=v253_original_document callback_payment_scene_unchanged=true version=%s",
        VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V262_ENFORCE
    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return
    current = v262.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V262_ENFORCE = current
    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V263 dense68 identity lock + quality-gated strict retry installed", flush=True)


__all__ = [
    "VERSION", "install", "enforce_runtime", "_dense_landmarks_68",
    "_desired_identity_geometry", "_dense_deform_roi", "_quality_metrics",
    "_quality_gate", "_true_face_transfer_v263",
]
