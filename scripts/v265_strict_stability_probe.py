# -*- coding: utf-8 -*-
"""Deterministic production-size V265 standard->strict stability probe.

No Gemini/provider call is used. The script exercises the same local V265 engine,
PIPNet-68, MobileFace, ocular lock, production gate and PNG path at 1856x2304.
It is intended for a 512 MiB CI container so native OpenCV/DNN memory behavior is
close to the Render starter process that restarted during the production verifier.
"""
from __future__ import annotations

import asyncio
import gc
import json
import os
import time
from pathlib import Path
from typing import Any

os.environ["PROD_HARDENING_ENABLED"] = "0"

_FIXTURE_BASE = (
    "https://raw.githubusercontent.com/yakhyo/uniface/"
    "df87c6531f4d1bdad665882d42d658590e724ea4/assets/source"
)
_OUT = Path("/tmp/v265_strict_probe")
_T0 = time.monotonic()
_PHASE = "bootstrap"


def _memory() -> tuple[int, int]:
    rss = hwm = 0
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1]) * 1024
            elif line.startswith("VmHWM:"):
                hwm = int(line.split()[1]) * 1024
    except Exception:
        pass
    return rss, hwm


def _array_summary(value: Any) -> str:
    shape = getattr(value, "shape", None)
    dtype = getattr(value, "dtype", None)
    nbytes = getattr(value, "nbytes", None)
    if shape is None:
        return ""
    return f"shape={tuple(int(v) for v in shape)} dtype={dtype} bytes={int(nbytes or 0)}"


def cp(checkpoint: str, **meta: Any) -> None:
    rss, hwm = _memory()
    payload = {
        "checkpoint": checkpoint,
        "phase": _PHASE,
        "elapsed_s": round(time.monotonic() - _T0, 4),
        "rss_bytes": rss,
        "peak_rss_bytes": hwm,
        **meta,
    }
    print("AI_SELFIE_V265_STRICT_DIAG " + json.dumps(payload, sort_keys=True), flush=True)


async def _download(name: str) -> bytes:
    import httpx
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=25.0), follow_redirects=True) as client:
        response = await client.get(f"{_FIXTURE_BASE}/{name}")
        response.raise_for_status()
        return bytes(response.content)


def _encode_png(frame) -> bytes:
    import cv2
    ok, encoded = cv2.imencode(".png", frame, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise RuntimeError("probe PNG encode failed")
    return bytes(encoded.tobytes())


def _stage1_from_target(target_raw: bytes, yunet_path) -> bytes:
    import cv2
    import numpy as np
    from neyrobot_prod import selfie_v253_yunet_source_pixels as v253

    target_src = v253._decode_bgr(target_raw)
    bbox, _ = v253._yunet_face(target_src, yunet_path, label="strict_probe_target_fixture")
    x, y, fw, fh = [float(v) for v in bbox]
    desired_face_short = 650.0
    scale = desired_face_short / max(1.0, min(fw, fh))
    resized = cv2.resize(
        target_src,
        (max(1, int(round(target_src.shape[1] * scale))), max(1, int(round(target_src.shape[0] * scale)))),
        interpolation=cv2.INTER_LANCZOS4 if scale > 1.0 else cv2.INTER_AREA,
    )
    sx, sy, sfw, sfh = x * scale, y * scale, fw * scale, fh * scale
    canvas = np.full((2304, 1856, 3), 214, dtype=np.uint8)
    firewall_x = int(round(1856 * 0.55))
    desired_cx = firewall_x * 0.50
    desired_cy = 1040.0
    tx = int(round(desired_cx - (sx + sfw * 0.5)))
    ty = int(round(desired_cy - (sy + sfh * 0.5)))

    src_x0 = max(0, -tx)
    src_y0 = max(0, -ty)
    dst_x0 = max(0, tx)
    dst_y0 = max(0, ty)
    src_x1 = min(resized.shape[1], firewall_x - tx)
    src_y1 = min(resized.shape[0], 2304 - ty)
    if src_x1 <= src_x0 or src_y1 <= src_y0:
        raise RuntimeError("probe target placement failed")
    dst_x1 = dst_x0 + (src_x1 - src_x0)
    dst_y1 = dst_y0 + (src_y1 - src_y0)
    canvas[dst_y0:dst_y1, dst_x0:dst_x1] = resized[src_y0:src_y1, src_x0:src_x1]
    canvas[:, firewall_x:] = 186
    raw = _encode_png(canvas)
    cp(
        "fixture_stage1_ready",
        dims="1856x2304",
        target_fixture_face=f"{fw:.0f}x{fh:.0f}",
        target_scale=round(scale, 4),
        target_face_expected_short=round(min(sfw, sfh), 2),
        png_bytes=len(raw),
    )
    return raw


def _install_checkpoints() -> None:
    import cv2
    from neyrobot_prod import dense68_engine_v265 as engine
    from neyrobot_prod import selfie_v263_dense_identity_lock as v263

    original_dense = v263._dense_landmarks_68
    def dense(frame, bbox, model_path, *, label: str):
        x, y, fw, fh = [float(v) for v in bbox]
        h, w = frame.shape[:2]
        x1 = max(0, int(round(x - fw * 0.10)))
        y1 = max(0, int(round(y + fh * 0.10)))
        x2 = min(w - 1, int(round(x + fw + fw * 0.10)))
        y2 = min(h - 1, int(round(y + fh + fh * 0.10)))
        crop_w = max(0, x2 - x1 + 1)
        crop_h = max(0, y2 - y1 + 1)
        cp(
            "pipnet_before",
            label=label,
            frame=_array_summary(frame),
            crop_shape=f"{crop_h}x{crop_w}x3",
            crop_bytes=int(crop_h * crop_w * 3),
        )
        result = original_dense(frame, bbox, model_path, label=label)
        cp("pipnet_after", label=label, result=_array_summary(result))
        return result
    v263._dense_landmarks_68 = dense

    original_mobile = v263._mobileface_embedding
    def mobile(frame, dense68, model_path):
        cp("mobileface_before", frame=_array_summary(frame), dense=_array_summary(dense68))
        result = original_mobile(frame, dense68, model_path)
        cp("mobileface_after", embedding=_array_summary(result))
        return result
    v263._mobileface_embedding = mobile

    original_warp = engine._warp_source_direct_to_roi
    def warp(source_im, matrix, box):
        x0, y0, x1, y1 = [int(v) for v in box]
        cp(
            "warp_before",
            source=_array_summary(source_im),
            roi_shape=f"{y1-y0}x{x1-x0}x3",
            roi_bytes=int((y1-y0) * (x1-x0) * 3),
        )
        result = original_warp(source_im, matrix, box)
        cp("warp_after", result=_array_summary(result))
        return result
    engine._warp_source_direct_to_roi = warp

    original_dense_field = engine._dense_deform_local_roi
    def dense_field(warped_roi, projected_dense, desired_dense, box, face_min):
        h, w = warped_roi.shape[:2]
        # Persistent float32 accumulators/maps plus one transient gaussian weight.
        estimated = int(h * w * 4 * 9 + h * w * 3)
        cp(
            "dense_field_before",
            warped=_array_summary(warped_roi),
            estimated_working_bytes=estimated,
            face_min=round(float(face_min), 3),
        )
        result = original_dense_field(warped_roi, projected_dense, desired_dense, box, face_min)
        cp("dense_field_after", corrected=_array_summary(result[0]), residuals=_array_summary(result[2]))
        return result
    engine._dense_deform_local_roi = dense_field

    original_core = engine._inject_bounded_identity_core
    def core(composed, corrected, target, mask, face_min, boundary):
        cp(
            "identity_core_before",
            composed=_array_summary(composed),
            corrected=_array_summary(corrected),
            target=_array_summary(target),
            mask=_array_summary(mask),
        )
        result = original_core(composed, corrected, target, mask, face_min, boundary)
        cp("identity_core_after", result=_array_summary(result[0]))
        return result
    engine._inject_bounded_identity_core = core

    original_comp = engine._structure_first_compose_roi
    def comp(corrected_roi, target_roi, mask_roi, face_min, *, strict: bool):
        cp(
            "compositor_before",
            strict=bool(strict),
            corrected=_array_summary(corrected_roi),
            target=_array_summary(target_roi),
            mask=_array_summary(mask_roi),
        )
        result = original_comp(corrected_roi, target_roi, mask_roi, face_min, strict=strict)
        cp("compositor_after", strict=bool(strict), result=_array_summary(result[0]))
        return result
    engine._structure_first_compose_roi = comp

    original_remap = cv2.remap
    def remap(*args, **kwargs):
        src = args[0] if args else None
        map_x = args[1] if len(args) > 1 else kwargs.get("map1")
        map_y = args[2] if len(args) > 2 else kwargs.get("map2")
        cp("remap_before", src=_array_summary(src), map_x=_array_summary(map_x), map_y=_array_summary(map_y))
        result = original_remap(*args, **kwargs)
        cp("remap_after", result=_array_summary(result))
        return result
    cv2.remap = remap

    original_clone = cv2.seamlessClone
    def clone(*args, **kwargs):
        cp(
            "seamless_clone_before",
            src=_array_summary(args[0] if len(args) > 0 else None),
            dst=_array_summary(args[1] if len(args) > 1 else None),
            mask=_array_summary(args[2] if len(args) > 2 else None),
        )
        result = original_clone(*args, **kwargs)
        cp("seamless_clone_after", result=_array_summary(result))
        return result
    cv2.seamlessClone = clone

    original_encode = cv2.imencode
    def imencode(*args, **kwargs):
        cp("output_serialization_before", frame=_array_summary(args[1] if len(args) > 1 else None))
        result = original_encode(*args, **kwargs)
        encoded = result[1] if isinstance(result, tuple) and len(result) > 1 else None
        cp("output_serialization_after", encoded=_array_summary(encoded))
        return result
    cv2.imencode = imencode


async def main() -> None:
    global _PHASE
    from neyrobot_prod import dense68_engine_v265 as engine
    from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
    from neyrobot_prod import selfie_v263_dense_identity_lock as v263
    from neyrobot_prod import selfie_v265_single_owner as v265

    _OUT.mkdir(parents=True, exist_ok=True)
    cp("probe_start", pid=os.getpid())
    yunet_path = await v253._ensure_yunet_model()
    dense_path, recognition_path = await v263._ensure_identity_models()
    cp("models_resolved", pipnet=str(dense_path), mobileface=str(recognition_path))

    source = await _download("verify_now_2024.jpg")
    target_fixture = await _download("verify_curie.jpg")
    stage1 = _stage1_from_target(target_fixture, yunet_path)
    (_OUT / "stage1.png").write_bytes(stage1)
    _install_checkpoints()

    _PHASE = "standard_transfer"
    cp("standard_entry")
    standard, standard_metrics, standard_desired = engine.transfer_attempt(
        stage1, source, yunet_path, dense_path, recognition_path, strict=False
    )
    cp("standard_transfer_complete", png_bytes=len(standard))
    _PHASE = "standard_ocular"
    standard, standard_metrics = engine.apply_ocular_lock(
        stage1, standard, source, standard_desired, yunet_path, dense_path, recognition_path, standard_metrics
    )
    standard_ok, standard_failures = v265.production_gate(standard_metrics)
    cp(
        "standard_gate",
        hard_pass=bool(standard_ok),
        failures="|".join(standard_failures) or "none",
        identity=round(float(standard_metrics.get("identity_similarity_cosine", 0.0)), 6),
        inner_nme=round(float(standard_metrics.get("inner_face_landmark_nme", 0.0)), 6),
    )
    if standard_ok:
        raise RuntimeError("probe fixture did not reproduce standard FAIL; choose a harder target fixture")

    # Match production retention: standard PNG + metrics stay alive while strict starts.
    gc.collect()
    pipnet_id_before = id(v263._PIPNET_NET)
    mobile_id_before = id(v263._MOBILEFACE_NET)
    cp(
        "strict_preflight_after_standard",
        standard_png_bytes=len(standard),
        pipnet_object_id=pipnet_id_before,
        mobileface_object_id=mobile_id_before,
    )

    _PHASE = "strict_transfer"
    cp("strict_entry")
    strict, strict_metrics, strict_desired = engine.transfer_attempt(
        stage1, source, yunet_path, dense_path, recognition_path, strict=True
    )
    cp("strict_transfer_complete", png_bytes=len(strict))
    _PHASE = "strict_ocular"
    cp("ocular_field_entry")
    strict, strict_metrics = engine.apply_ocular_lock(
        stage1, strict, source, strict_desired, yunet_path, dense_path, recognition_path, strict_metrics
    )
    cp("ocular_field_complete", png_bytes=len(strict))
    strict_ok, strict_failures = v265.production_gate(strict_metrics)
    cp(
        "strict_gate",
        hard_pass=bool(strict_ok),
        failures="|".join(strict_failures) or "none",
        identity=round(float(strict_metrics.get("identity_similarity_cosine", 0.0)), 6),
        left_eye=round(float(strict_metrics.get("left_eye_error", 0.0)), 6),
        right_eye=round(float(strict_metrics.get("right_eye_error", 0.0)), 6),
        eye_asymmetry=round(float(strict_metrics.get("eye_asymmetry_delta", 0.0)), 6),
        interocular=round(float(strict_metrics.get("interocular_ratio_delta", 0.0)), 6),
        nose_mouth=round(float(strict_metrics.get("nose_mouth_axis_delta", 0.0)), 6),
        inner_nme=round(float(strict_metrics.get("inner_face_landmark_nme", 0.0)), 6),
    )

    if id(v263._PIPNET_NET) != pipnet_id_before or id(v263._MOBILEFACE_NET) != mobile_id_before:
        raise RuntimeError("V265 model object was reloaded between standard and strict")
    if not strict.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("strict output is not PNG")
    (_OUT / "strict_final.png").write_bytes(strict)
    cp(
        "probe_complete",
        strict_png_bytes=len(strict),
        model_reloaded=False,
        process_restart=False,
        same_engine=True,
        hard_gate_reached=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
