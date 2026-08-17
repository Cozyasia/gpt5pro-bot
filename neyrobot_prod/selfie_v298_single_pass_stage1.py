# -*- coding: utf-8 -*-
"""V300 bounded Stage-1 for production AI Selfie.

The runtime historically owns a generic 3-attempt composition loop. V299 made each
selfie provider call direct, but a provider-side HTTP 500 was still retried by that
outer loop three times, turning one ~70 s provider failure into ~210 s.

V300 keeps the generic runtime untouched while making selfie Stage-1 production-safe:
- only attempt 1 may contact Gemini;
- later outer attempts fail immediately after a first-attempt provider failure;
- Gemini image models are tried inside ONE request-wide deadline;
- the fast image model is preferred for composition because final user identity is
  applied later by the dedicated FaceSwap stage;
- each model gets a bounded slice and total Stage-1 wall time stays bounded;
- successful compositions are locally reframed around the principal pair and are
  never regenerated merely because the generated camera distance is too wide.
"""
from __future__ import annotations

import asyncio
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

VERSION = "v300-bounded-stage1-no-outer-retry-2026-08-17"
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
        value = float(os.getenv("AI_SELFIE_STAGE1_TOTAL_BUDGET_S") or "70")
    except Exception:
        value = 70.0
    return max(45.0, min(80.0, value))


def _per_model_s() -> float:
    try:
        value = float(os.getenv("AI_SELFIE_STAGE1_MODEL_TIMEOUT_S") or "38")
    except Exception:
        value = 38.0
    return max(25.0, min(45.0, value))


def _image_size() -> str:
    value = str(os.getenv("AI_SELFIE_STAGE1_IMAGE_SIZE") or "1K").strip().upper()
    return value if value in {"1K", "2K"} else "1K"


def _model_order() -> list[str]:
    configured = [str(x).strip() for x in v229._models() if str(x).strip()]
    explicit = str(os.getenv("AI_SELFIE_STAGE1_MODEL") or "").strip()
    if explicit:
        ordered = [explicit] + [m for m in configured if m != explicit]
        return ordered[:2]
    # Composition does not own final user identity; prefer the fast image model.
    flash = [m for m in configured if "flash" in m.lower()]
    other = [m for m in configured if m not in flash]
    ordered = flash + other
    return ordered[:2] if ordered else ["gemini-3.1-flash-image"]


async def _safe_text_v300(message: Any, text: str) -> None:
    value = str(text or "")
    if (
        "Для максимальной чёткости лица кадр нужно сделать ближе" in value
        or "Второй кадр тоже получился слишком дальним" in value
    ):
        _log("AI_SELFIE_V300_UI status=legacy_retry_message_suppressed")
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


async def _direct_gemini_bounded(
    prompt: str,
    labeled_images: list[tuple[str, bytes]],
    stage: str,
    total_budget_s: float,
) -> tuple[bytes, str]:
    import httpx

    key = v229._key()
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY is missing")

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

    started = time.monotonic()
    errors: list[str] = []
    models = _model_order()
    _log(
        "AI_SELFIE_V300_STAGE1 stage=%s status=provider_plan models=%s refs=%s image_size=%s total_budget=%.0fs per_model=%.0fs outer_retry=false",
        stage, ",".join(models), len(prepared), _image_size(), total_budget_s, _per_model_s(),
    )

    for index, model in enumerate(models, start=1):
        elapsed = time.monotonic() - started
        remaining = total_budget_s - elapsed
        if remaining <= 2.0:
            break
        slice_s = min(_per_model_s(), max(2.0, remaining))
        timeout = httpx.Timeout(slice_s, connect=min(10.0, slice_s), read=slice_s, write=min(25.0, slice_s), pool=10.0)
        _log(
            "AI_SELFIE_V300_STAGE1 stage=%s status=provider_enter model=%s index=%s timeout=%.0fs remaining=%.1fs",
            stage, model, index, slice_s, remaining,
        )
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
                response = await asyncio.wait_for(
                    client.post(
                        f"{v229._base_url()}/models/{model}:generateContent",
                        headers=headers,
                        json=payload,
                    ),
                    timeout=slice_s + 1.0,
                )
            if response.status_code >= 400:
                errors.append(f"{model}:HTTP {response.status_code}:{response.text[:220]}")
                _log(
                    "AI_SELFIE_V300_STAGE1 stage=%s status=provider_http_error model=%s http=%s elapsed=%.2fs",
                    stage, model, response.status_code, time.monotonic() - started,
                )
                continue
            output = extractor._extract_final_image(response.json())
            if output and len(output) > 1024:
                _log(
                    "AI_SELFIE_V300_STAGE1 stage=%s status=composition_ready model=%s elapsed=%.2fs bytes=%s",
                    stage, model, time.monotonic() - started, len(output),
                )
                return bytes(output), model
            errors.append(f"{model}:no_final_image")
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            errors.append(f"{model}:timeout:{type(exc).__name__}")
            _log(
                "AI_SELFIE_V300_STAGE1 stage=%s status=provider_timeout model=%s elapsed=%.2fs",
                stage, model, time.monotonic() - started,
            )
        except Exception as exc:
            errors.append(f"{model}:{type(exc).__name__}:{str(exc)[:220]}")
            _log(
                "AI_SELFIE_V300_STAGE1 stage=%s status=provider_exception model=%s error_type=%s error=%s",
                stage, model, type(exc).__name__, str(exc)[:250],
            )

    raise RuntimeError("Gemini composition failed within bounded Stage-1: " + " | ".join(errors[-4:]))


async def _call_google_single_pass(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    attempt = _stage_attempt(stage)
    is_selfie = bool(attempt and v293._is_selfie_prompt(prompt))
    if not is_selfie:
        return await _PUBLIC_GOOGLE_CALL(prompt, labeled_images, stage)

    task = asyncio.current_task()
    if task is not None:
        setattr(task, "_ai_selfie_v300_selfie_job", True)
        cached = getattr(task, "_ai_selfie_v300_composition", None)
        cached_model = getattr(task, "_ai_selfie_v300_model", None)
        if isinstance(cached, (bytes, bytearray)) and len(cached) > 1024:
            _log(
                "AI_SELFIE_V300_STAGE1 stage=%s status=reuse_composition attempt=%s provider_call=false bytes=%s",
                stage, attempt, len(cached),
            )
            return bytes(cached), str(cached_model or "google_gemini_v300_cached")
        first_error = getattr(task, "_ai_selfie_v300_first_error", None)
        if attempt > 1 and first_error:
            _log(
                "AI_SELFIE_V300_STAGE1 stage=%s status=outer_retry_blocked attempt=%s provider_call=false",
                stage, attempt,
            )
            raise RuntimeError(str(first_error))

    budget = _budget_s()
    started = time.monotonic()
    try:
        output, model = await asyncio.wait_for(
            _direct_gemini_bounded(prompt, labeled_images, stage, budget),
            timeout=budget + 2.0,
        )
    except Exception as exc:
        if task is not None:
            setattr(task, "_ai_selfie_v300_first_error", f"{type(exc).__name__}: {str(exc)[:600]}")
        _log(
            "AI_SELFIE_V300_STAGE1 stage=%s status=first_attempt_failed elapsed=%.2fs error_type=%s error=%s outer_retry_will_be_blocked=true",
            stage, time.monotonic() - started, type(exc).__name__, str(exc)[:400],
        )
        raise

    if task is not None:
        setattr(task, "_ai_selfie_v300_composition", bytes(output))
        setattr(task, "_ai_selfie_v300_model", str(model))
    return output, model


def _target_single_pass(composition: bytes, *, scene_image: bool, log: Any):
    task = asyncio.current_task()
    is_selfie = bool(task is not None and getattr(task, "_ai_selfie_v300_selfie_job", False))
    if not is_selfie:
        return _PUBLIC_TARGET(composition, scene_image=scene_image, log=log)
    try:
        base_img, target, metrics = v287._first_pass_target(composition, log)
        metrics = dict(metrics)
        metrics["v300_single_request"] = 1.0
        metrics["v300_regeneration_for_distance"] = 0.0
        log(
            "AI_SELFIE_V300_TARGET status=accepted action=deterministic_principal_pair_reframe face=%s crop=%s dims=%s regeneration=false",
            target.face_box, target.crop_box, getattr(base_img, "size", None),
        )
        return base_img, target, metrics
    except Exception as exc:
        log(
            "AI_SELFIE_V300_TARGET status=principal_pair_failed error_type=%s error=%s action=legacy_target_fallback",
            type(exc).__name__, str(exc)[:500],
        )
        return _PUBLIC_TARGET(composition, scene_image=scene_image, log=log)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    v229._call_google = _call_google_single_pass
    terminal._target = _target_single_pass
    delivery._safe_text = _safe_text_v300
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V300"
    setattr(terminal, "_v299_direct_single_request_stage1", False)
    setattr(terminal, "_v300_bounded_stage1", True)
    setattr(terminal, "_v300_outer_retry_blocked", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V300 bounded Stage-1 installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
