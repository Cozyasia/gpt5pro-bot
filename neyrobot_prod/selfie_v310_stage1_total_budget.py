# -*- coding: utf-8 -*-
"""V310: bounded Stage-1 budget for the proven V292 production path.

This overlay keeps the V292 quality/identity pipeline intact and changes only
Stage-1 latency control. The budget intentionally covers preprocessing plus the
provider call, because V287 body/reference preparation happens inside the wrapped
V229 call. A previous 70s guard left only a few seconds for Gemini after roughly
one minute of preprocessing; V310 raises the request-wide Stage-1 budget to a
production-safe 180s while still blocking legacy attempts 2/3 after a timeout.

No prompts, face geometry, jaw geometry, target selection, identity transfer,
InSwapper/PiAPI behavior, source-native integration, or final compositing are
changed here.
"""
from __future__ import annotations

import asyncio
import os

from neyrobot_prod import selfie_v229_canonical_two_stage as v229

VERSION = "v310-v292-stage1-total-budget-2026-08-17"
_INSTALLED = False
_ORIGINAL_CALL = None


def _budget_seconds() -> float:
    """Use a new V310-specific knob so an old V309=70 env value cannot regress us."""
    try:
        value = float(os.getenv("AI_SELFIE_V310_STAGE1_TIMEOUT_S", "180") or 180)
    except Exception:
        value = 180.0
    return max(120.0, min(240.0, value))


async def _bounded_call(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    global _ORIGINAL_CALL
    original = _ORIGINAL_CALL
    if original is None:
        raise RuntimeError("V310 original Stage-1 provider is unavailable")

    task = asyncio.current_task()
    blocked = bool(getattr(task, "_ai_selfie_v310_stage1_timeout", False)) if task is not None else False
    stage_text = str(stage or "")
    is_composition = "scene_hero_body_attempt" in stage_text or stage_text == "composition"

    if is_composition and blocked:
        v229._log("AI_SELFIE_V310_STAGE1 stage=%s status=outer_retry_blocked provider_call=false", stage_text)
        raise TimeoutError("AI Selfie Stage-1 composition already exceeded production SLA; retry suppressed")

    if not is_composition:
        return await original(prompt, labeled_images, stage)

    budget = _budget_seconds()
    started = asyncio.get_running_loop().time()
    v229._log(
        "AI_SELFIE_V310_STAGE1 stage=%s status=enter budget=%.0fs refs=%s scope=preprocess_plus_provider",
        stage_text,
        budget,
        len(labeled_images),
    )
    try:
        result = await asyncio.wait_for(original(prompt, labeled_images, stage), timeout=budget)
        elapsed = asyncio.get_running_loop().time() - started
        v229._log(
            "AI_SELFIE_V310_STAGE1 stage=%s status=success elapsed=%.2fs budget=%.0fs",
            stage_text,
            elapsed,
            budget,
        )
        return result
    except asyncio.TimeoutError as exc:
        if task is not None:
            setattr(task, "_ai_selfie_v310_stage1_timeout", True)
        elapsed = asyncio.get_running_loop().time() - started
        v229._log(
            "AI_SELFIE_V310_STAGE1 stage=%s status=timeout elapsed=%.2fs budget=%.0fs outer_retries=blocked",
            stage_text,
            elapsed,
            budget,
        )
        raise TimeoutError(f"AI Selfie Stage-1 composition exceeded production SLA ({budget:.0f}s)") from exc


def install() -> bool:
    global _INSTALLED, _ORIGINAL_CALL
    if _INSTALLED and getattr(v229, "_v310_stage1_total_budget", False):
        return True

    current = v229._call_google
    if current is _bounded_call:
        _INSTALLED = True
        setattr(v229, "_v310_stage1_total_budget", True)
        return True

    _ORIGINAL_CALL = current
    v229._call_google = _bounded_call
    setattr(v229, "_v310_stage1_total_budget", True)
    _INSTALLED = True
    print(
        f"[neyrobot-prod] V310 V292 Stage-1 total budget installed version={VERSION} budget={_budget_seconds():.0f}s",
        flush=True,
    )
    return True


__all__ = ["VERSION", "install"]
