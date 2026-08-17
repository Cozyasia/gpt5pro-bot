# -*- coding: utf-8 -*-
"""V298 single-pass Stage-1 for production AI Selfie.

V297 fixed the request-wide timeout, but the core runtime still interpreted every
Stage-1 exception as "the frame is too distant" and could request a second/third
Gemini image. In the latest production trace this consumed the whole 120 s budget
without ever reaching identity transfer.

V298 makes the normal selfie path deterministic:
- one Gemini composition is the authoritative scene candidate;
- the V297 close-selfie prompt remains active;
- the expensive V293 post-generation validator is bypassed for Stage-1 because it
  can reject an otherwise repairable frame and trigger regeneration;
- V287 principal-face geometry is applied immediately to every selfie composition,
  so a wide image is cropped/reframed locally instead of regenerated;
- all composition attempts share a hard provider budget and later attempts reuse the
  first composition instead of buying another image solely for camera distance;
- legacy retry status messages that falsely claim "the frame is too far" are hidden
  because V298 does not perform distance-based regeneration.

No face identity pixels are changed here. V296 provider-race identity remains the
owner of face transfer after the deterministic target has been acquired.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import re
import time
from typing import Any

from neyrobot_prod import selfie_v211_delivery as delivery
from neyrobot_prod import selfie_v229_canonical_two_stage as v229
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v287_first_pass_quality as v287
from neyrobot_prod import selfie_v293_selfie_composition_gate as v293

VERSION = "v298-single-pass-stage1-deterministic-selfie-r2-2026-08-17"
_INSTALLED = False

# State at V298 import time: V297 watchdog is the public Google owner and V287 is
# the deterministic target owner. Keep both for non-selfie/fallback behavior.
_PUBLIC_GOOGLE_CALL = v229._call_google
_PUBLIC_TARGET = terminal._target
_PUBLIC_SAFE_TEXT = delivery._safe_text

# V293 captured the pre-validator chain when it was imported. That chain still
# contains V287 native-input/upper-body reference preparation and the canonical
# Gemini transport, but does not run the extra post-generation validator.
_STAGE1_PROVIDER_CALL = v293._ORIGINAL_GOOGLE_CALL


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        v229._log(message, *args)


def _stage_attempt(stage: str) -> int:
    match = re.search(r"scene_hero_body_attempt_(\d+)", str(stage or ""))
    if not match:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


def _budget_s() -> float:
    # Production cap is intentionally strict. Even if an old Render variable still
    # says 120/150 s, V298 will not let Stage-1 occupy more than 100 s.
    try:
        value = float(os.getenv("AI_SELFIE_STAGE1_TOTAL_BUDGET_S") or "90")
    except Exception:
        value = 90.0
    return max(70.0, min(100.0, value))


async def _safe_text_v298(message: Any, text: str) -> None:
    value = str(text or "")
    # These two strings come from the legacy generic retry loop and are no longer
    # truthful under V298. If deterministic target acquisition somehow fails, the
    # cached first composition is retried locally without another Gemini purchase.
    if (
        "Для максимальной чёткости лица кадр нужно сделать ближе" in value
        or "Второй кадр тоже получился слишком дальним" in value
    ):
        _log("AI_SELFIE_V298_UI status=legacy_distance_retry_suppressed")
        return
    await _PUBLIC_SAFE_TEXT(message, text)


async def _call_google_single_pass(
    prompt: str,
    labeled_images: list[tuple[str, bytes]],
    stage: str,
) -> tuple[bytes, str]:
    attempt = _stage_attempt(stage)
    is_selfie = bool(attempt and v293._is_selfie_prompt(prompt))
    if not is_selfie:
        return await _PUBLIC_GOOGLE_CALL(prompt, labeled_images, stage)

    task = asyncio.current_task()
    now = time.monotonic()
    budget = _budget_s()

    if task is not None:
        setattr(task, "_ai_selfie_v298_selfie_job", True)
        deadline = getattr(task, "_ai_selfie_v298_deadline", None)
        if deadline is None:
            deadline = now + budget
            setattr(task, "_ai_selfie_v298_deadline", deadline)
            _log(
                "AI_SELFIE_V298_STAGE1 stage=%s status=start policy=single_generation+deterministic_reframe budget=%.0fs validator=false",
                stage, budget,
            )

        cached = getattr(task, "_ai_selfie_v298_composition", None)
        cached_model = getattr(task, "_ai_selfie_v298_model", None)
        if attempt > 1 and isinstance(cached, (bytes, bytearray)) and len(cached) > 1024:
            _log(
                "AI_SELFIE_V298_STAGE1 stage=%s status=reuse_first_composition attempt=%s provider_call=false bytes=%s",
                stage, attempt, len(cached),
            )
            return bytes(cached), str(cached_model or "google_gemini_direct_v298_cached")
        remaining = float(deadline) - now
    else:
        remaining = budget

    if remaining <= 1.0:
        _log(
            "AI_SELFIE_V298_STAGE1 stage=%s status=budget_exhausted remaining=%.2fs provider_call=false",
            stage, remaining,
        )
        raise TimeoutError(f"AI Selfie composition exceeded production budget ({budget:.0f}s)")

    started = time.monotonic()
    try:
        output, model = await asyncio.wait_for(
            _STAGE1_PROVIDER_CALL(prompt, labeled_images, stage),
            timeout=max(1.0, remaining),
        )
    except asyncio.TimeoutError as exc:
        _log(
            "AI_SELFIE_V298_STAGE1 stage=%s status=timeout elapsed=%.2fs budget=%.0fs",
            stage, time.monotonic() - started, budget,
        )
        raise TimeoutError(f"AI Selfie composition provider exceeded production budget ({budget:.0f}s)") from exc

    if task is not None:
        setattr(task, "_ai_selfie_v298_composition", bytes(output))
        setattr(task, "_ai_selfie_v298_model", str(model))

    _log(
        "AI_SELFIE_V298_STAGE1 stage=%s status=composition_ready elapsed=%.2fs attempt=%s bytes=%s validator=false",
        stage, time.monotonic() - started, attempt, len(output),
    )
    return output, model


def _target_single_pass(composition: bytes, *, scene_image: bool, log: Any):
    task = asyncio.current_task()
    is_selfie = bool(task is not None and getattr(task, "_ai_selfie_v298_selfie_job", False))
    if not is_selfie:
        return _PUBLIC_TARGET(composition, scene_image=scene_image, log=log)

    # V287's principal-pair method is exactly the deterministic repair needed here:
    # detect the two principal faces, crop around them and restore the native canvas.
    # It does not invent a new person and does not call Gemini again.
    try:
        base_img, target, metrics = v287._first_pass_target(composition, log)
        metrics = dict(metrics)
        metrics["v298_single_pass"] = 1.0
        metrics["v298_regeneration_for_distance"] = 0.0
        log(
            "AI_SELFIE_V298_TARGET status=accepted action=deterministic_principal_pair_reframe face=%s crop=%s dims=%s regeneration=false",
            target.face_box, target.crop_box, getattr(base_img, "size", None),
        )
        return base_img, target, metrics
    except Exception as exc:
        log(
            "AI_SELFIE_V298_TARGET status=principal_pair_failed error_type=%s error=%s action=legacy_target_fallback",
            type(exc).__name__, str(exc)[:500],
        )
        return _PUBLIC_TARGET(composition, scene_image=scene_image, log=log)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    v229._call_google = _call_google_single_pass
    terminal._target = _target_single_pass
    delivery._safe_text = _safe_text_v298
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V298"
    setattr(terminal, "_v298_single_pass_stage1", True)
    setattr(terminal, "_v298_distance_regeneration_disabled", True)
    setattr(terminal, "_v298_stage1_budget_hard_cap", 100)
    _INSTALLED = True
    print(f"[neyrobot-prod] V298 single-pass deterministic Stage-1 installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
