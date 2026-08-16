# -*- coding: utf-8 -*-
"""V283 terminal composition rescue for production AI Selfie.

Keeps the strict native-resolution target floor for attempts 1-2. If Gemini still
returns a slightly-too-distant PERSON A on the final attempt, accept only a bounded
rescue floor and use a tighter face-centric crop. V280 then performs 4x InSwapper
plus the source-native facial core, so the user flow does not fail after spending
three Gemini image calls.
"""
from __future__ import annotations

import contextvars
import re
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v229_canonical_two_stage as v229

VERSION = "v283-terminal-target-rescue-2026-08-16"
_INSTALLED = False
_CURRENT_ATTEMPT: contextvars.ContextVar[int] = contextvars.ContextVar("ai_selfie_composition_attempt", default=0)

_ORIGINAL_GOOGLE_CALL = v229._call_google
_ORIGINAL_TARGET = terminal._target


def _attempt_from_stage(stage: str) -> int:
    match = re.search(r"attempt_(\d+)", str(stage or ""))
    if not match:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


async def _call_google_track_attempt(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    attempt = _attempt_from_stage(stage)
    token = _CURRENT_ATTEMPT.set(attempt)
    try:
        return await _ORIGINAL_GOOGLE_CALL(prompt, labeled_images, stage)
    finally:
        # Keep the attempt visible to the immediately following synchronous _target()
        # call in terminal.generate(). The next Google call overwrites it.
        if attempt <= 0:
            _CURRENT_ATTEMPT.reset(token)


def _rescue_target(composition: bytes, *, scene_image: bool, log: Any):
    attempt = _CURRENT_ATTEMPT.get()
    try:
        return _ORIGINAL_TARGET(composition, scene_image=scene_image, log=log)
    except ValueError as exc:
        message = str(exc)
        if attempt < 3 or "production floor" not in message:
            raise

        base_img, located, metrics = fs.locate_person_a(composition, scene_image=scene_image, log=None)
        _, ih = base_img.size
        face_h = int(located.face_box[3])
        ratio = face_h / float(max(1, ih))

        # Bounded rescue only. Below this there simply are not enough native target
        # pixels for reliable geometry and we prefer a clean failure.
        rescue_px = 220 if not scene_image else 240
        rescue_ratio = 0.095 if not scene_image else 0.105
        if face_h < rescue_px or ratio < rescue_ratio:
            raise

        # Tighter crop gives InSwapper and V280 source-native core more effective
        # pixels without changing the scene geometry or introducing another Gemini pass.
        crop_box = fs._expand(located.face_box, base_img.size, 1.46, 1.68, 0.008)
        crop_img = base_img.crop(crop_box)
        crop_raw = fs.jpeg(crop_img, max_side=1900, quality=100)
        fw, fh = located.face_box[2], located.face_box[3]
        cw, ch = crop_img.size
        metrics = dict(metrics)
        metrics.update({
            "min_px": float(rescue_px),
            "min_ratio": float(rescue_ratio),
            "target_face_w_coverage": fw / float(max(1, cw)),
            "target_face_h_coverage": fh / float(max(1, ch)),
            "v283_terminal_rescue": 1.0,
            "strict_floor_missed": 1.0,
        })
        target = fs.FaceTarget(located.face_box, crop_box, crop_raw, located.support, located.eye_count, located.score)
        log(
            "AI_SELFIE_V283_TARGET_RESCUE attempt=%s face=%s crop=%s face_h=%s ratio=%.4f rescue_floor=%spx/%.4f dims=%s face_w_coverage=%.3f face_h_coverage=%.3f",
            attempt,
            target.face_box,
            target.crop_box,
            face_h,
            ratio,
            rescue_px,
            rescue_ratio,
            fs.dims(crop_raw),
            metrics["target_face_w_coverage"],
            metrics["target_face_h_coverage"],
        )
        return base_img, target, metrics


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    v229._call_google = _call_google_track_attempt
    terminal._target = _rescue_target
    _INSTALLED = True
    print(f"[neyrobot-prod] V283 terminal target rescue installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
