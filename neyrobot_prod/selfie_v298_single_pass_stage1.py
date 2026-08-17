# -*- coding: utf-8 -*-
"""V299 truly single-request Stage-1 for production AI Selfie.

V298 removed distance retries at the orchestration layer, but still called the
historical wrapped Gemini chain. That chain contained older policy/compatibility
logic and could remain inside one nominal attempt for ~200 seconds. V299 bypasses
that wrapper stack for selfie composition and performs exactly one direct Gemini
image request with one model, one payload and one transport timeout.

After the image arrives, V287 principal-pair reframing is applied locally. A wide
composition is never regenerated merely because the people are too far away.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import re
import time
from typing import Any

from neyrobot_prod import celebrity_selfie as base
from neyrobot_prod import celebrity_selfie_v204 as extractor
from neyrobot_prod import selfie_v211_delivery as delivery
from neyrobot_prod import selfie_v229_canonical_two_stage as v229
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v287_first_pass_quality as v287
from neyrobot_prod import selfie_v293_selfie_composition_gate as v293

VERSION = "v299-direct-single-request-stage1-2026-08-17"
_INSTALLED = False

_PUBLIC_GOOGLE_CALL = v229._call_google
_PUBLIC_TARGET = terminal._target
_PUBLIC_SAFE_TEXT = delivery._safe_text


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
    try:
        value = float(os.getenv("AI_SELFIE_STAGE1_TOTAL_BUDGET_S") or "80")
    except Exception:
        value = 80.0
    return max(60.0, min(90.0, value))


def _image_size() -> str:
    value = str(os.getenv("AI_SELFIE_STAGE1_IMAGE_SIZE") or "1K").strip().upper()
    return value if value in {"1K", "2K"} else "1K"


async def _safe_text_v299(message: Any, text: str) -> None:
    value = str(text or "")
    if (
        "Для максимальной чёткости лица кадр нужно сделать ближе" in value
        or "Второй кадр тоже получился слишком дальним" in value
    ):
        _log("AI_SELFIE_V299_UI status=legacy_distance_retry_suppressed")
        return
    await _PUBLIC_SAFE_TEXT(message, text)


def _prepare_refs(labeled_images: list[tuple[str, bytes]]) -> list[tuple[str, str, str]]:
    prepared: list[tuple[str, str, str]] = []
    for label, raw in labeled_images:
        data = bytes(raw or b"")
        if "USER AGE/BUILD REFERENCE" in str(label):
            data = v287._upper_body_reference(data)
            label = str(label) + " CAMERA-FRAMING NOTE: ignore source camera distance; use only age/build/proportions."
        encoded, mime = v229._prepare(data)
        prepared.append((str(label), encoded, mime))
    return prepared


async def _direct_gemini_once(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str, timeout_s: float) -> tuple[bytes, str]:
    import httpx

    key = v229._key()
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY is missing")
    models = list(v229._models())
    if not models:
        raise RuntimeError("No Gemini image model configured")
    model = str(models[0])

    # Prepare only once. No compatibility retry and no post-generation vision call.
    prepared = _prepare_refs(labeled_images)
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for label, encoded, mime in prepared:
        parts.append({"text": label})
        parts.append({"inlineData": {"mimeType": mime, "data": encoded}})

    config: dict[str, Any] = {
        "responseModalities": ["TEXT", "IMAGE"],
        "imageConfig": {
            "aspectRatio": base._aspect_ratio(),
            "imageSize": _image_size(),
        },
    }
    payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
    headers = {"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
    transport = httpx.Timeout(timeout_s, connect=min(15.0, timeout_s), read=timeout_s, write=min(45.0, timeout_s), pool=15.0)

    _log(
        "AI_SELFIE_V299_STAGE1 stage=%s status=provider_enter model=%s refs=%s image_size=%s timeout=%.0fs direct=true compatibility_retry=false validator=false",
        stage, model, len(prepared), _image_size(), timeout_s,
    )
    async with httpx.AsyncClient(follow_redirects=True, timeout=transport) as client:
        response = await client.post(
            f"{v229._base_url()}/models/{model}:generateContent",
            headers=headers,
            json=payload,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini composition HTTP {response.status_code}: {response.text[:500]}")
    output = extractor._extract_final_image(response.json())
    if not output or len(output) <= 1024:
        raise RuntimeError("Gemini composition response contained no final image")
    return bytes(output), model


async def _call_google_single_pass(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    attempt = _stage_attempt(stage)
    is_selfie = bool(attempt and v293._is_selfie_prompt(prompt))
    if not is_selfie:
        return await _PUBLIC_GOOGLE_CALL(prompt, labeled_images, stage)

    task = asyncio.current_task()
    if task is not None:
        setattr(task, "_ai_selfie_v299_selfie_job", True)
        cached = getattr(task, "_ai_selfie_v299_composition", None)
        cached_model = getattr(task, "_ai_selfie_v299_model", None)
        if attempt > 1 and isinstance(cached, (bytes, bytearray)) and len(cached) > 1024:
            _log(
                "AI_SELFIE_V299_STAGE1 stage=%s status=reuse_first_composition attempt=%s provider_call=false bytes=%s",
                stage, attempt, len(cached),
            )
            return bytes(cached), str(cached_model or "google_gemini_direct_v299_cached")

    budget = _budget_s()
    started = time.monotonic()
    try:
        output, model = await asyncio.wait_for(
            _direct_gemini_once(prompt, labeled_images, stage, budget),
            timeout=budget + 2.0,
        )
    except asyncio.TimeoutError as exc:
        _log(
            "AI_SELFIE_V299_STAGE1 stage=%s status=timeout elapsed=%.2fs budget=%.0fs direct=true",
            stage, time.monotonic() - started, budget,
        )
        raise TimeoutError(f"AI Selfie composition provider exceeded production budget ({budget:.0f}s)") from exc

    if task is not None:
        setattr(task, "_ai_selfie_v299_composition", bytes(output))
        setattr(task, "_ai_selfie_v299_model", str(model))

    _log(
        "AI_SELFIE_V299_STAGE1 stage=%s status=composition_ready elapsed=%.2fs attempt=%s bytes=%s direct=true validator=false",
        stage, time.monotonic() - started, attempt, len(output),
    )
    return output, model


def _target_single_pass(composition: bytes, *, scene_image: bool, log: Any):
    task = asyncio.current_task()
    is_selfie = bool(task is not None and getattr(task, "_ai_selfie_v299_selfie_job", False))
    if not is_selfie:
        return _PUBLIC_TARGET(composition, scene_image=scene_image, log=log)
    try:
        base_img, target, metrics = v287._first_pass_target(composition, log)
        metrics = dict(metrics)
        metrics["v299_single_request"] = 1.0
        metrics["v299_regeneration_for_distance"] = 0.0
        log(
            "AI_SELFIE_V299_TARGET status=accepted action=deterministic_principal_pair_reframe face=%s crop=%s dims=%s regeneration=false",
            target.face_box, target.crop_box, getattr(base_img, "size", None),
        )
        return base_img, target, metrics
    except Exception as exc:
        log(
            "AI_SELFIE_V299_TARGET status=principal_pair_failed error_type=%s error=%s action=legacy_target_fallback",
            type(exc).__name__, str(exc)[:500],
        )
        return _PUBLIC_TARGET(composition, scene_image=scene_image, log=log)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    v229._call_google = _call_google_single_pass
    terminal._target = _target_single_pass
    delivery._safe_text = _safe_text_v299
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V299"
    setattr(terminal, "_v298_single_pass_stage1", False)
    setattr(terminal, "_v299_direct_single_request_stage1", True)
    setattr(terminal, "_v299_distance_regeneration_disabled", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V299 direct single-request Stage-1 installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
