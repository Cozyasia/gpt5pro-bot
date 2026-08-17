# -*- coding: utf-8 -*-
"""V310: provider-only Stage-1 timeout on the proven V292 production path.

The previous V310 wrapped the already wrapped ``v229._call_google`` chain. That
meant V287 reference preparation consumed part of the same timeout budget and
made the effective Gemini provider window much shorter than configured.

This implementation keeps the proven V292/V287/V280 quality path, but makes the
latency boundary explicit:
1. perform the V287 AGE/BUILD upper-body reference preparation first;
2. invoke the V280 fidelity/policy provider path directly;
3. apply the V310 timeout only to the actual provider/policy call;
4. block legacy outer attempts 2/3 only after that provider budget is exhausted.

V309 is not part of this call chain. No prompts, face geometry, jaw geometry,
target selection, identity transfer, InSwapper/PiAPI behavior, source-native
integration, or final compositing are changed here.
"""
from __future__ import annotations

import asyncio
import os

from neyrobot_prod import selfie_v229_canonical_two_stage as v229
from neyrobot_prod import selfie_v277_production_fidelity_patch as v280
from neyrobot_prod import selfie_v287_first_pass_quality as v287

VERSION = "v310b-v292-provider-only-stage1-budget-2026-08-17"
_INSTALLED = False


def _budget_seconds() -> float:
    try:
        value = float(os.getenv("AI_SELFIE_V310_STAGE1_TIMEOUT_S", "180") or 180)
    except Exception:
        value = 180.0
    return max(120.0, min(240.0, value))


def _prepare_v287_refs(labeled_images: list[tuple[str, bytes]], stage: str) -> list[tuple[str, bytes]]:
    """Reproduce V287 composition-reference preparation outside provider timeout."""
    refs: list[tuple[str, bytes]] = []
    for label, raw in labeled_images:
        text = str(label)
        data = bytes(raw or b"")
        if "USER AGE/BUILD REFERENCE" in text:
            data = v287._upper_body_reference(data)
            text += " CAMERA-FRAMING NOTE: ignore the source photo's camera distance; use it only for age/build/proportions."
        refs.append((text, data))
    v229._log(
        "AI_SELFIE_V310_STAGE1 stage=%s status=refs_ready refs=%s timeout_scope=provider_only",
        str(stage or ""),
        len(refs),
    )
    return refs


async def _provider_call(prompt: str, refs: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    """Call the V280 fidelity/policy path directly, bypassing wrapper-on-wrapper latency."""
    return await v280._call_google_with_policy(prompt, refs, stage)


async def _bounded_call(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    task = asyncio.current_task()
    blocked = bool(getattr(task, "_ai_selfie_v310_stage1_timeout", False)) if task is not None else False
    stage_text = str(stage or "")
    is_composition = "scene_hero_body_attempt" in stage_text or stage_text == "composition"

    if not is_composition:
        # Preserve the currently installed chain for unrelated Gemini traffic.
        return await v287._call_google(prompt, labeled_images, stage)

    if blocked:
        v229._log(
            "AI_SELFIE_V310_STAGE1 stage=%s status=outer_retry_blocked provider_call=false",
            stage_text,
        )
        raise TimeoutError("AI Selfie Stage-1 provider budget already exhausted; retry suppressed")

    prep_started = asyncio.get_running_loop().time()
    refs = _prepare_v287_refs(labeled_images, stage_text)
    prep_elapsed = asyncio.get_running_loop().time() - prep_started

    budget = _budget_seconds()
    provider_started = asyncio.get_running_loop().time()
    v229._log(
        "AI_SELFIE_V310_STAGE1 stage=%s status=provider_enter budget=%.0fs refs=%s prep_elapsed=%.2fs",
        stage_text,
        budget,
        len(refs),
        prep_elapsed,
    )
    try:
        result = await asyncio.wait_for(_provider_call(prompt, refs, stage), timeout=budget)
        provider_elapsed = asyncio.get_running_loop().time() - provider_started
        v229._log(
            "AI_SELFIE_V310_STAGE1 stage=%s status=success provider_elapsed=%.2fs prep_elapsed=%.2fs budget=%.0fs",
            stage_text,
            provider_elapsed,
            prep_elapsed,
            budget,
        )
        return result
    except asyncio.TimeoutError as exc:
        if task is not None:
            setattr(task, "_ai_selfie_v310_stage1_timeout", True)
        provider_elapsed = asyncio.get_running_loop().time() - provider_started
        v229._log(
            "AI_SELFIE_V310_STAGE1 stage=%s status=provider_timeout provider_elapsed=%.2fs prep_elapsed=%.2fs budget=%.0fs outer_retries=blocked",
            stage_text,
            provider_elapsed,
            prep_elapsed,
            budget,
        )
        raise TimeoutError(f"AI Selfie Stage-1 provider exceeded production SLA ({budget:.0f}s)") from exc


def install() -> bool:
    global _INSTALLED
    if _INSTALLED and getattr(v229, "_v310_stage1_total_budget", False):
        return True

    v229._call_google = _bounded_call
    setattr(v229, "_v310_stage1_total_budget", True)
    setattr(v229, "_v310_provider_only_budget", True)
    _INSTALLED = True
    print(
        f"[neyrobot-prod] V310b V292 provider-only Stage-1 budget installed version={VERSION} budget={_budget_seconds():.0f}s",
        flush=True,
    )
    return True


__all__ = ["VERSION", "install"]
