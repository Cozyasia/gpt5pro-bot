# -*- coding: utf-8 -*-
"""V309: hard request-wide timeout for the proven V292 Stage-1 path.

This patch intentionally changes only the composition-provider wait. It does not
change prompts, face detection, target geometry, identity transfer, InSwapper,
PiAPI, source-native face integration, jaw geometry, or final compositing.

If the provider call times out, later legacy composition retries in the same
asyncio task are blocked immediately so one user request cannot spend several
minutes repeating the same stalled provider call.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from neyrobot_prod import selfie_v229_canonical_two_stage as v229

VERSION = "v309-v292-stage1-hard-timeout-2026-08-17"
_INSTALLED = False
_ORIGINAL_CALL = None


def _budget_seconds() -> float:
    try:
        value = float(os.getenv("AI_SELFIE_STAGE1_TIMEOUT_S", "70") or 70)
    except Exception:
        value = 70.0
    return max(30.0, min(120.0, value))


async def _bounded_call(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    global _ORIGINAL_CALL
    original = _ORIGINAL_CALL
    if original is None:
        raise RuntimeError("V309 original Stage-1 provider is unavailable")

    task = asyncio.current_task()
    blocked = bool(getattr(task, "_ai_selfie_v309_stage1_timeout", False)) if task is not None else False
    stage_text = str(stage or "")
    is_composition = "scene_hero_body_attempt" in stage_text or stage_text == "composition"

    if is_composition and blocked:
        v229._log("AI_SELFIE_V309_STAGE1 stage=%s status=outer_retry_blocked provider_call=false", stage_text)
        raise TimeoutError("AI Selfie Stage-1 composition already exceeded production SLA; retry suppressed")

    if not is_composition:
        return await original(prompt, labeled_images, stage)

    budget = _budget_seconds()
    started = asyncio.get_running_loop().time()
    v229._log("AI_SELFIE_V309_STAGE1 stage=%s status=enter budget=%.0fs refs=%s", stage_text, budget, len(labeled_images))
    try:
        result = await asyncio.wait_for(original(prompt, labeled_images, stage), timeout=budget)
        elapsed = asyncio.get_running_loop().time() - started
        v229._log("AI_SELFIE_V309_STAGE1 stage=%s status=success elapsed=%.2fs budget=%.0fs", stage_text, elapsed, budget)
        return result
    except asyncio.TimeoutError as exc:
        if task is not None:
            setattr(task, "_ai_selfie_v309_stage1_timeout", True)
        elapsed = asyncio.get_running_loop().time() - started
        v229._log("AI_SELFIE_V309_STAGE1 stage=%s status=timeout elapsed=%.2fs budget=%.0fs outer_retries=blocked", stage_text, elapsed, budget)
        raise TimeoutError(f"AI Selfie Stage-1 composition exceeded production SLA ({budget:.0f}s)") from exc


def install() -> bool:
    global _INSTALLED, _ORIGINAL_CALL
    if _INSTALLED and getattr(v229, "_v309_stage1_timeout_guard", False):
        return True

    current = v229._call_google
    if current is _bounded_call:
        _INSTALLED = True
        setattr(v229, "_v309_stage1_timeout_guard", True)
        return True

    _ORIGINAL_CALL = current
    v229._call_google = _bounded_call
    setattr(v229, "_v309_stage1_timeout_guard", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V309 V292 Stage-1 hard timeout installed version={VERSION} budget={_budget_seconds():.0f}s", flush=True)
    return True


__all__ = ["VERSION", "install"]
