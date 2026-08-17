# -*- coding: utf-8 -*-
"""V297 Stage-1 production latency guard for AI Selfie.

The V296 guard capped EACH composition attempt, not the whole Stage-1 job. Because the
runtime may regenerate up to three times, a nominal 100-second SLA still allowed about
300-350 seconds before failure. V297 changes the budget to one request-wide deadline.

The deadline is stored on the current asyncio task, so every scene_hero_body_attempt
shares the same remaining budget. This keeps retries possible for genuinely broken
anatomy while preventing 3 x timeout multiplication. Combined with the V297 selfie
gate, wide framing is no longer a regeneration reason; V284 deterministically crops it.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
from io import BytesIO
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v229_canonical_two_stage as v229
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v287_first_pass_quality as v287

VERSION = "v297-stage1-total-budget-2026-08-17"
_INSTALLED = False
_ORIGINAL_GOOGLE_CALL = v229._call_google


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        v229._log(message, *args)


def _fast_body_reference(raw: bytes) -> bytes:
    """Bound AGE/BUILD reference size without face detection or OpenCV."""
    data = bytes(raw or b"")
    started = time.monotonic()
    if len(data) < 1024:
        return data
    try:
        from PIL import Image, ImageOps

        src = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
        try:
            w, h = src.size
            if max(w, h) <= 1600 and len(data) <= 3 * 1024 * 1024:
                _log(
                    "AI_SELFIE_V297_BODY_REF status=native_passthrough dims=%sx%s bytes=%s elapsed=%.3fs cv=false",
                    w, h, len(data), time.monotonic() - started,
                )
                return data

            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            src.thumbnail((1600, 1600), resample)
            out = BytesIO()
            src.save(out, "JPEG", quality=96, subsampling=0, optimize=False, progressive=False)
            result = out.getvalue()
            _log(
                "AI_SELFIE_V297_BODY_REF status=bounded_passthrough in=%sx%s out=%s bytes_in=%s bytes_out=%s elapsed=%.3fs cv=false",
                w, h, fs.dims(result), len(data), len(result), time.monotonic() - started,
            )
            return result
        finally:
            src.close()
    except Exception as exc:
        _log(
            "AI_SELFIE_V297_BODY_REF status=raw_fallback error_type=%s error=%s dims=%s bytes=%s elapsed=%.3fs cv=false",
            type(exc).__name__, str(exc)[:260], fs.dims(data), len(data), time.monotonic() - started,
        )
        return data


def _total_budget() -> float:
    try:
        requested = float(os.getenv("AI_SELFIE_STAGE1_TOTAL_BUDGET_S") or os.getenv("AI_SELFIE_STAGE1_TIMEOUT_S") or "120")
    except Exception:
        requested = 120.0
    return max(75.0, min(150.0, requested))


def _is_composition_attempt(stage: str) -> bool:
    return "scene_hero_body_attempt" in str(stage or "")


async def _call_google_watchdog(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    task = asyncio.current_task()
    now = time.monotonic()
    budget_s = _total_budget()

    if task is not None and _is_composition_attempt(stage):
        deadline = getattr(task, "_ai_selfie_stage1_deadline", None)
        if deadline is None:
            deadline = now + budget_s
            with contextlib.suppress(Exception):
                setattr(task, "_ai_selfie_stage1_deadline", deadline)
            _log(
                "AI_SELFIE_V297_STAGE1 stage=%s status=budget_start total_budget=%.0fs request_wide=true",
                stage, budget_s,
            )
        remaining = float(deadline) - now
    else:
        remaining = budget_s

    if remaining <= 1.0:
        _log(
            "AI_SELFIE_V297_STAGE1 stage=%s status=budget_exhausted remaining=%.2fs total_budget=%.0fs",
            stage, remaining, budget_s,
        )
        raise TimeoutError(f"AI Selfie composition exceeded total production budget ({budget_s:.0f}s)")

    # Do not let a single late retry consume beyond the request-wide deadline.
    timeout_s = max(1.0, remaining)
    started = time.monotonic()
    _log(
        "AI_SELFIE_V297_STAGE1 stage=%s status=enter refs=%s remaining=%.2fs total_budget=%.0fs request_wide=true",
        stage, len(labeled_images), timeout_s, budget_s,
    )
    try:
        result = await asyncio.wait_for(
            _ORIGINAL_GOOGLE_CALL(prompt, labeled_images, stage),
            timeout=timeout_s,
        )
        _log(
            "AI_SELFIE_V297_STAGE1 stage=%s status=exit elapsed=%.2fs remaining_after=%.2fs",
            stage, time.monotonic() - started,
            max(0.0, (getattr(task, "_ai_selfie_stage1_deadline", time.monotonic()) - time.monotonic()) if task is not None else 0.0),
        )
        return result
    except asyncio.TimeoutError as exc:
        elapsed = time.monotonic() - started
        _log(
            "AI_SELFIE_V297_STAGE1 stage=%s status=timeout elapsed=%.2fs total_budget=%.0fs request_wide=true fail_fast=true",
            stage, elapsed, budget_s,
        )
        raise TimeoutError(f"AI Selfie composition exceeded total production budget ({budget_s:.0f}s)") from exc


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    v287._upper_body_reference = _fast_body_reference
    v229._call_google = _call_google_watchdog
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V297"
    setattr(terminal, "_v294_stage1_nonblocking", True)
    setattr(terminal, "_v294_stage1_watchdog", True)
    setattr(terminal, "_v296_stage1_latency_cap", True)
    setattr(terminal, "_v297_stage1_total_budget", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V297 Stage-1 request-wide budget installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
