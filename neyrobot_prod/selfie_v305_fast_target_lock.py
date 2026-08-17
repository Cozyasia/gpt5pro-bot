# -*- coding: utf-8 -*-
"""V305 production AI Selfie: fast PERSON-A target lock.

V304 fixed Stage-1 provider latency (~22s in production), but the legacy V287
post-generation target detector still spent ~145s per pass and the outer runtime
repeated the exact same cached composition three times when that detector rejected
it. V305 leaves composition and identity transfer architecture intact, but replaces
that expensive target lock for selfie jobs with a bounded OpenCV detector and
blocks reuse of a composition that already failed target acquisition.

It also defaults V304's composition model to full gpt-image-1 rather than mini;
Stage-1 remains low quality/compact because exact user identity is transferred in
Stage-2, while the stronger model gives substantially more reliable human faces.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v229_canonical_two_stage as v229
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v293_selfie_composition_gate as v293
from neyrobot_prod import selfie_v301_fast_resilient_stage1 as v301

VERSION = "v305-fast-target-lock-full-openai-2026-08-17"
_INSTALLED = False
_PREV_STAGE1 = v229._call_google
_PREV_TARGET = terminal._target


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        v229._log(message, *args)


def _fast_face_boxes(raw: bytes) -> list[tuple[int, int, int, int, int]]:
    """Return face boxes in original-image coordinates, largest/best first."""
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    img = fs.image(raw).convert("RGB")
    iw, ih = img.size
    scale = min(1.0, 700.0 / float(max(1, iw, ih)))
    sw = max(1, int(round(iw * scale)))
    sh = max(1, int(round(ih * scale)))
    arr = np.asarray(img)
    if scale < 0.999:
        arr = cv2.resize(arr, (sw, sh), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    eq = cv2.equalizeHist(gray)
    min_side = max(34, int(min(sw, sh) * 0.055))

    hits: list[tuple[int, int, int, int, int]] = []
    configs = (
        ("haarcascade_frontalface_default.xml", gray, 5, 3),
        ("haarcascade_frontalface_alt2.xml", eq, 4, 2),
    )
    for name, frame, neighbors, support in configs:
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        if cascade.empty():
            continue
        found = cascade.detectMultiScale(
            frame,
            scaleFactor=1.08,
            minNeighbors=neighbors,
            minSize=(min_side, min_side),
        )
        for x, y, w, h in found:
            hits.append((int(x), int(y), int(w), int(h), int(support)))

    # Profile rescue only if frontal cascades miss everything.
    if not hits:
        profile = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
        if not profile.empty():
            for mirrored in (False, True):
                frame = cv2.flip(eq, 1) if mirrored else eq
                found = profile.detectMultiScale(
                    frame,
                    scaleFactor=1.09,
                    minNeighbors=4,
                    minSize=(min_side, min_side),
                )
                for x, y, w, h in found:
                    if mirrored:
                        x = sw - int(x) - int(w)
                    hits.append((int(x), int(y), int(w), int(h), 1))

    if not hits:
        return []

    inv = 1.0 / scale
    boxes: list[tuple[int, int, int, int, int]] = []
    for x, y, w, h, support in hits:
        bx = max(0, int(round(x * inv)))
        by = max(0, int(round(y * inv)))
        bw = max(1, int(round(w * inv)))
        bh = max(1, int(round(h * inv)))
        # Selfie faces should be in the upper ~80% and not tiny texture hits.
        cy = by + bh / 2.0
        if bh < max(48, int(ih * 0.045)) or cy > ih * 0.82:
            continue
        boxes.append((bx, by, bw, bh, support))

    # Merge near-duplicates by IoU-ish center/size proximity.
    merged: list[tuple[int, int, int, int, int]] = []
    for item in sorted(boxes, key=lambda b: b[2] * b[3], reverse=True):
        x, y, w, h, support = item
        cx = x + w / 2.0; cy = y + h / 2.0
        duplicate = False
        for ox, oy, ow, oh, _os in merged:
            ocx = ox + ow / 2.0; ocy = oy + oh / 2.0
            if abs(cx - ocx) < max(w, ow) * 0.28 and abs(cy - ocy) < max(h, oh) * 0.28:
                duplicate = True
                break
        if not duplicate:
            merged.append(item)
    return merged


def _fast_target(composition: bytes, *, scene_image: bool, log: Any):
    task = asyncio.current_task()
    if not (task is not None and getattr(task, "_ai_selfie_v305_job", False)):
        return _PREV_TARGET(composition, scene_image=scene_image, log=log)

    try:
        img = fs.image(composition).convert("RGB")
        iw, ih = img.size
        boxes = _fast_face_boxes(composition)
        if not boxes:
            raise ValueError("V305: no face detected in first composition")

        # PERSON A is the staged user and is expected on the left. If two or more
        # credible faces exist, choose the left member of the principal pair.
        credible = [b for b in boxes if b[2] * b[3] >= max(1, int(iw * ih * 0.0015))]
        if not credible:
            credible = boxes
        principal = sorted(credible, key=lambda b: b[2] * b[3], reverse=True)[:4]
        left_candidates = [b for b in principal if b[0] + b[2] / 2.0 <= iw * 0.66]
        if left_candidates:
            face = max(left_candidates, key=lambda b: b[2] * b[3])
        else:
            face = min(principal, key=lambda b: b[0] + b[2] / 2.0)

        x, y, w, h, support = [int(v) for v in face]
        crop_box = fs._expand((x, y, w, h), img.size, 1.72, 2.02, 0.015)
        crop_raw = fs.jpeg(img.crop(crop_box), max_side=2000, quality=99)
        target = fs.FaceTarget((x, y, w, h), crop_box, crop_raw, max(1, support), 0, float(w * h))
        metrics = {
            "face_w": float(w),
            "face_h": float(h),
            "face_h_ratio": float(h) / float(max(1, ih)),
            "face_area_ratio": float(w * h) / float(max(1, iw * ih)),
            "support": float(max(1, support)),
            "eye_count": 0.0,
            "score": float(w * h),
            "detector_stage": 305.0,
            "strict_clusters": 0.0,
            "wide_clusters": float(len(boxes)),
            "min_px": 0.0,
            "min_ratio": 0.0,
            "target_face_w_coverage": float(w) / float(max(1, crop_box[2] - crop_box[0])),
            "target_face_h_coverage": float(h) / float(max(1, crop_box[3] - crop_box[1])),
            "v305_fast_target": 1.0,
            "v305_no_reframe_retry": 1.0,
        }
        log(
            "AI_SELFIE_V305_TARGET status=accepted face=%s crop=%s dims=%s candidates=%s face_h_ratio=%.3f",
            target.face_box, target.crop_box, fs.dims(crop_raw), len(boxes), metrics["face_h_ratio"],
        )
        return img, target, metrics
    except Exception as exc:
        if task is not None:
            setattr(task, "_ai_selfie_v305_target_failed", str(exc))
        log(
            "AI_SELFIE_V305_TARGET status=failed_fast error_type=%s error=%s no_legacy_detector=true",
            type(exc).__name__, str(exc)[:300],
        )
        raise


async def _stage1_v305(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str):
    attempt = v301._stage_attempt(stage)
    is_selfie = bool(attempt and v293._is_selfie_prompt(prompt))
    task = asyncio.current_task()
    if is_selfie and task is not None:
        setattr(task, "_ai_selfie_v305_job", True)
        failed = getattr(task, "_ai_selfie_v305_target_failed", None)
        if attempt > 1 and failed:
            _log(
                "AI_SELFIE_V305_STAGE1 stage=%s status=blocked_cached_failed_target attempt=%s provider_call=false error=%s",
                stage, attempt, str(failed)[:240],
            )
            raise RuntimeError(f"cached first composition has no usable PERSON A target: {failed}")
    return await _PREV_STAGE1(prompt, labeled_images, stage)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    # Full gpt-image-1 is still used only for compact/low-quality Stage-1. This is
    # intentionally a quality floor for face anatomy, not the final identity path.
    os.environ.setdefault("AI_SELFIE_V304_OPENAI_MODEL", "gpt-image-1")
    v229._call_google = _stage1_v305
    terminal._target = _fast_target
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V305"
    setattr(terminal, "_v305_fast_target_lock", True)
    setattr(terminal, "_v305_full_openai_stage1", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V305 fast target lock installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
