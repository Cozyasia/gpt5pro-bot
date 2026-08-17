# -*- coding: utf-8 -*-
"""V304 production AI Selfie Stage-1.

The V303 path still spent the first ~28s waiting for Gemini Flash before trying
OpenAI, and the direct OpenAI edit request still carried up to five relatively
large references.  For the selfie composition stage we do not need the user's
facial identity (that is transferred later); we need only three visual facts:
location, user age/build, and hero appearance.

V304 therefore makes Stage-1 compact and latency-oriented:
  1. choose exactly one scene, one user-body, and one hero reference;
  2. downscale those references locally before any provider call;
  3. call the direct OpenAI Images edit endpoint first, defaulting to
     gpt-image-1-mini at low quality for composition only;
  4. if that provider fails, use one bounded Gemini Flash fallback;
  5. never restore legacy outer retries.

The established V292/V299 identity-transfer and final integration path remains
unchanged, so photo #3 is still the authoritative user face source.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import os
import time
from typing import Any

from PIL import Image

from neyrobot_prod import selfie_v229_canonical_two_stage as v229
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v293_selfie_composition_gate as v293
from neyrobot_prod import selfie_v301_fast_resilient_stage1 as v301

VERSION = "v304-compact-openai-first-stage1-2026-08-17"
_INSTALLED = False
_PREV_STAGE1 = v229._call_google


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        v229._log(message, *args)


def _attempt(stage: str) -> int:
    return v301._stage_attempt(stage)


def _compact_jpeg(raw: bytes, max_side: int = 768) -> bytes:
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = min(1.0, float(max_side) / float(max(1, w, h)))
            if scale < 0.999:
                im = im.resize((max(1, int(round(w * scale))), max(1, int(round(h * scale)))), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=88, optimize=True, progressive=False)
            data = out.getvalue()
            return data if len(data) > 1024 else bytes(raw)
    except Exception:
        return bytes(raw)


def _compact_refs(labeled_images: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    scene = None
    user = None
    hero = None
    fallback: list[tuple[str, bytes]] = []
    for label, raw in labeled_images:
        item = (str(label), bytes(raw or b""))
        up = str(label).upper()
        if scene is None and ("AUTHORITATIVE LOCATION" in up or "SCENE" in up or "LOCATION" in up):
            scene = item
        elif user is None and ("USER AGE/BUILD" in up or "USER BODY" in up):
            user = item
        elif hero is None and ("HERO" in up or "CELEBRITY" in up or "PERSON B" in up):
            hero = item
        else:
            fallback.append(item)

    chosen: list[tuple[str, bytes]] = []
    for item in (scene, user, hero):
        if item is not None:
            chosen.append(item)
    for item in fallback:
        if len(chosen) >= 3:
            break
        chosen.append(item)
    if not chosen:
        chosen = [(str(l), bytes(r or b"")) for l, r in labeled_images[:3]]

    result: list[tuple[str, bytes]] = []
    for label, raw in chosen[:3]:
        result.append((label, _compact_jpeg(raw)))
    return result


def _timeout_total() -> float:
    try:
        v = float(os.getenv("AI_SELFIE_V304_TOTAL_S") or "55")
    except Exception:
        v = 55.0
    return max(42.0, min(68.0, v))


def _openai_timeout() -> float:
    try:
        v = float(os.getenv("AI_SELFIE_V304_OPENAI_S") or "32")
    except Exception:
        v = 32.0
    return max(20.0, min(40.0, v))


async def _openai_compose(prompt: str, refs: list[tuple[str, bytes]], stage: str, timeout_s: float) -> tuple[bytes, str]:
    import httpx

    key = v301._official_openai_key()
    if not key:
        raise RuntimeError("official OpenAI image key is unavailable")

    model = str(os.getenv("AI_SELFIE_V304_OPENAI_MODEL") or "gpt-image-1-mini").strip()
    labels = "\n".join(f"Reference {i+1}: {label}" for i, (label, _) in enumerate(refs))
    edit_prompt = (
        prompt
        + "\n\nREFERENCE ORDER:\n" + labels
        + "\nThis is a close handheld selfie photographed at arm's length. "
          "Both people must be close to the camera, head-and-shoulders/upper-torso framing, "
          "not a distant full-body scene. Use the user reference only for age/build and clothing; "
          "the user's exact face will be transferred later. Create one final photorealistic vertical photo."
    )

    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for idx, (_label, raw) in enumerate(refs):
        files.append(("image[]", (f"ref_{idx+1}.jpg", raw, "image/jpeg")))

    data: dict[str, str] = {
        "model": model,
        "prompt": edit_prompt,
        "size": "1024x1536",
        "quality": "low",
        "background": "opaque",
        "n": "1",
        "output_format": "jpeg",
        "output_compression": "85",
    }
    # gpt-image-1-mini does not support input_fidelity; full gpt-image-1 does.
    if "mini" not in model.lower():
        data["input_fidelity"] = "high"

    base_url = str(os.getenv("OPENAI_IMAGES_BASE_URL") or os.getenv("IMAGES_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    timeout_s = max(18.0, float(timeout_s))
    timeout = httpx.Timeout(timeout_s, connect=min(8.0, timeout_s), read=timeout_s, write=min(15.0, timeout_s), pool=8.0)
    started = time.monotonic()
    _log("AI_SELFIE_V304_STAGE1 stage=%s provider=openai_images status=enter model=%s refs=%s timeout=%.0fs compact=true", stage, model, len(refs), timeout_s)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        response = await asyncio.wait_for(client.post(f"{base_url}/images/edits", headers=headers, data=data, files=files), timeout=timeout_s + 1.0)
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI Images edit HTTP {response.status_code}: {response.text[:500]}")
    js = response.json() or {}
    items = js.get("data") or []
    if not items or not isinstance(items[0], dict):
        raise RuntimeError("OpenAI Images edit returned no data")
    b64 = items[0].get("b64_json")
    if not b64:
        raise RuntimeError("OpenAI Images edit returned no b64_json")
    raw = base64.b64decode(b64)
    if len(raw) <= 1024:
        raise RuntimeError("OpenAI Images edit returned invalid image")
    _log("AI_SELFIE_V304_STAGE1 stage=%s provider=openai_images status=success elapsed=%.2fs bytes=%s", stage, time.monotonic()-started, len(raw))
    return raw, f"openai_{model}_compact"


async def _call_stage1_v304(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    attempt = _attempt(stage)
    if not (attempt and v293._is_selfie_prompt(prompt)):
        return await _PREV_STAGE1(prompt, labeled_images, stage)

    task = asyncio.current_task()
    if task is not None:
        cached = getattr(task, "_ai_selfie_v304_composition", None)
        model = getattr(task, "_ai_selfie_v304_model", None)
        if isinstance(cached, (bytes, bytearray)) and len(cached) > 1024:
            return bytes(cached), str(model or "v304_cached")
        first_error = getattr(task, "_ai_selfie_v304_first_error", None)
        if attempt > 1 and first_error:
            _log("AI_SELFIE_V304_STAGE1 stage=%s status=outer_retry_blocked attempt=%s", stage, attempt)
            raise RuntimeError(str(first_error))

    refs = _compact_refs(labeled_images)
    total = _timeout_total()
    started = time.monotonic()
    errors: list[str] = []
    _log("AI_SELFIE_V304_STAGE1 stage=%s status=plan refs_in=%s refs_compact=%s total_budget=%.0fs openai_first=true", stage, len(labeled_images), len(refs), total)

    try:
        remaining = total
        try:
            output, model = await _openai_compose(prompt, refs, stage, min(_openai_timeout(), remaining - 10.0))
        except Exception as exc:
            errors.append(f"openai:{type(exc).__name__}:{str(exc)[:240]}")
            _log("AI_SELFIE_V304_STAGE1 stage=%s provider=openai_images status=failed error_type=%s error=%s", stage, type(exc).__name__, str(exc)[:320])
            elapsed = time.monotonic() - started
            remaining = total - elapsed
            if remaining < 12.0:
                raise
            flash_timeout = min(24.0, max(12.0, remaining - 1.0))
            output, model = await v301._gemini_flash_once(prompt, refs, stage, flash_timeout)

        if task is not None:
            setattr(task, "_ai_selfie_v304_composition", bytes(output))
            setattr(task, "_ai_selfie_v304_model", str(model))
        _log("AI_SELFIE_V304_STAGE1 stage=%s status=composition_ready provider=%s elapsed=%.2fs bytes=%s", stage, model, time.monotonic()-started, len(output))
        return output, model
    except Exception as exc:
        errors.append(f"fallback:{type(exc).__name__}:{str(exc)[:260]}")
        message = " | ".join(errors[-2:])
        if task is not None:
            setattr(task, "_ai_selfie_v304_first_error", message)
        _log("AI_SELFIE_V304_STAGE1 stage=%s status=failed elapsed=%.2fs errors=%s outer_retry_blocked=true", stage, time.monotonic()-started, message[:700])
        raise RuntimeError(message) from exc


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    v229._call_google = _call_stage1_v304
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V304"
    setattr(terminal, "_v304_compact_openai_first", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V304 compact OpenAI-first Stage-1 installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
