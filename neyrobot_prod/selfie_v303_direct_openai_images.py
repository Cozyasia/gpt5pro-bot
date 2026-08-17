# -*- coding: utf-8 -*-
"""V303 AI Selfie Stage-1: direct OpenAI Images fallback.

Production V302 proved that the rescue chain itself works, but the Responses API
fallback is blocked by the account's gpt-5-mini verification requirement while
both Gemini image models can independently time out.  V303 removes the unrelated
Responses orchestrator from the OpenAI leg and calls the official Images edit
endpoint directly with gpt-image-1 and the compact Stage-1 references.

Chain remains bounded and keeps the established identity-transfer path intact:
    Gemini Flash -> direct OpenAI /v1/images/edits -> Gemini Pro (last resort)
No legacy outer Stage-1 retries are restored.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import time
from typing import Any

from neyrobot_prod import selfie_v229_canonical_two_stage as v229
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v301_fast_resilient_stage1 as v301

VERSION = "v303-direct-openai-images-stage1-2026-08-17"
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        v229._log(message, *args)


def _mime(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG"):
        return "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw.startswith(b"RIFF") and b"WEBP" in raw[:16]:
        return "image/webp"
    return "image/jpeg"


def _direct_timeout_s(requested: float) -> float:
    try:
        configured = float(os.getenv("AI_SELFIE_OPENAI_DIRECT_TIMEOUT_S") or "34")
    except Exception:
        configured = 34.0
    # Preserve enough of V301's remaining Stage-1 budget for a final provider.
    return max(18.0, min(42.0, configured, max(18.0, float(requested) - 8.0)))


async def _direct_openai_edit(
    prompt: str,
    labeled_images: list[tuple[str, bytes]],
    stage: str,
    timeout_s: float,
) -> tuple[bytes, str]:
    import httpx

    key = v301._official_openai_key()
    if not key:
        raise RuntimeError("official OpenAI image key is unavailable")

    refs = v301._select_refs(labeled_images)
    if not refs:
        raise RuntimeError("no Stage-1 references for OpenAI Images edit")

    model = str(os.getenv("AI_SELFIE_OPENAI_IMAGE_MODEL") or "gpt-image-1").strip()
    quality = str(os.getenv("AI_SELFIE_OPENAI_IMAGE_QUALITY") or "low").strip().lower()
    if quality not in {"low", "medium", "high", "auto"}:
        quality = "low"

    labels = "\n".join(f"Reference {i + 1}: {label}" for i, (label, _) in enumerate(refs))
    edit_prompt = (
        prompt
        + "\n\nREFERENCE ORDER:\n"
        + labels
        + "\nUse the references only for the roles stated in their labels. "
          "Create one final photorealistic vertical photograph, not a collage."
    )

    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for idx, (_label, raw) in enumerate(refs):
        data = bytes(raw or b"")
        files.append(("image[]", (f"reference_{idx + 1}.jpg", data, _mime(data))))

    data = {
        "model": model,
        "prompt": edit_prompt,
        "size": "1024x1536",
        "quality": quality,
        "input_fidelity": "high",
        "background": "opaque",
        "n": "1",
    }
    base_url = str(os.getenv("OPENAI_IMAGES_BASE_URL") or os.getenv("IMAGES_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    timeout_s = _direct_timeout_s(timeout_s)
    timeout = httpx.Timeout(timeout_s, connect=min(10.0, timeout_s), read=timeout_s, write=min(20.0, timeout_s), pool=10.0)
    started = time.monotonic()
    _log(
        "AI_SELFIE_V303_STAGE1 stage=%s provider=openai_images status=enter model=%s refs=%s timeout=%.0fs quality=%s endpoint=images_edits",
        stage, model, len(refs), timeout_s, quality,
    )

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        response = await asyncio.wait_for(
            client.post(f"{base_url}/images/edits", headers=headers, data=data, files=files),
            timeout=timeout_s + 1.0,
        )

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
        raise RuntimeError("OpenAI Images edit returned an empty/invalid image")
    _log(
        "AI_SELFIE_V303_STAGE1 stage=%s provider=openai_images status=success elapsed=%.2fs bytes=%s",
        stage, time.monotonic() - started, len(raw),
    )
    return raw, f"openai_{model}_direct"


async def _direct_openai_then_gemini(
    prompt: str,
    labeled_images: list[tuple[str, bytes]],
    stage: str,
    timeout_s: float,
) -> tuple[bytes, str]:
    started = time.monotonic()
    total = max(20.0, float(timeout_s))
    try:
        return await _direct_openai_edit(prompt, labeled_images, stage, total)
    except Exception as exc:
        elapsed = time.monotonic() - started
        remaining = total - elapsed - 0.5
        _log(
            "AI_SELFIE_V303_STAGE1 stage=%s provider=openai_images status=failed rescue=gemini_pro elapsed=%.2fs remaining=%.1fs error_type=%s error=%s",
            stage, elapsed, max(0.0, remaining), type(exc).__name__, str(exc)[:500],
        )
        if remaining < 10.0:
            raise
        return await v301._gemini_pro_fallback(prompt, labeled_images, stage, remaining)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    # V301 resolves this global function at execution time. Installing V303 after
    # V302 therefore cleanly replaces only the OpenAI fallback leg.
    v301._openai_image_fallback = _direct_openai_then_gemini
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V303"
    setattr(terminal, "_v303_direct_openai_images", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V303 direct OpenAI Images Stage-1 installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
