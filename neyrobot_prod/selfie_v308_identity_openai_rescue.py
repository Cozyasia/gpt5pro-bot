# -*- coding: utf-8 -*-
"""V308 production Stage-2 identity: three-way bounded race with OpenAI rescue.

V307 proved both remote face-swap transports can remain in provider-side processing
for the full 80 s identity SLA. That is not acceptable for production latency.
V308 keeps V304/V305 Stage-1 and target locking untouched, keeps the existing
Replicate and face-aware PiAPI branches, and adds a third independent identity
transport through the already-working OpenAI Images edit endpoint.

The OpenAI branch edits only the verified PERSON-A target crop using photo #3 as
the sole identity reference. The result still passes the same V289 geometry check
before it can win the race, so this is a bounded rescue, not an unchecked fallback.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import gc
import io
import os
import time
from typing import Any

import httpx
from PIL import Image

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v295_identity_fidelity_lock as v299
from neyrobot_prod import selfie_v301_fast_resilient_stage1 as v301
from neyrobot_prod import selfie_v307_identity_race as v307

VERSION = "v308-openai-identity-rescue-race-2026-08-17"
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        from neyrobot_prod import selfie_v229_canonical_two_stage as v229
        v229._log(message, *args)


def _jpeg(raw: bytes, max_side: int = 900, quality: int = 92) -> bytes:
    try:
        with Image.open(io.BytesIO(bytes(raw or b""))) as im:
            im = im.convert("RGB")
            if max(im.size) > max_side:
                im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            im.save(out, "JPEG", quality=quality, optimize=True, progressive=False)
            data = out.getvalue()
            return data if len(data) > 1024 else bytes(raw)
    except Exception:
        return bytes(raw)


async def _openai_identity(target_crop: bytes, source_crop: bytes, *, trace: str):
    key = v301._official_openai_key()
    if not key:
        raise RuntimeError("official OpenAI image key is unavailable")

    target = _jpeg(target_crop, max_side=900, quality=92)
    source = _jpeg(source_crop, max_side=900, quality=94)
    model = str(os.getenv("AI_SELFIE_V308_OPENAI_MODEL") or "gpt-image-1-mini").strip()
    timeout_s = max(22.0, min(42.0, float(os.getenv("AI_SELFIE_V308_OPENAI_TIMEOUT_S") or "34")))
    base_url = str(os.getenv("OPENAI_IMAGES_BASE_URL") or os.getenv("IMAGES_BASE_URL") or "https://api.openai.com/v1").rstrip("/")

    prompt = (
        "Edit IMAGE 1 only. IMAGE 1 is the verified target crop of PERSON A in a finished selfie. "
        "IMAGE 2 is the sole authoritative identity reference for PERSON A. Replace only PERSON A's facial identity "
        "in IMAGE 1 so the person unmistakably looks like the same individual as IMAGE 2. Preserve IMAGE 1 camera angle, "
        "head pose, expression, gaze direction, hair silhouette, ears, neck, clothing, lighting, skin texture, background, "
        "crop and perspective. Do not redesign the face, do not beautify, do not age-shift, do not change body or scene. "
        "Return one photorealistic edited image with the same composition as IMAGE 1."
    )

    files = [
        ("image[]", ("target.jpg", target, "image/jpeg")),
        ("image[]", ("identity.jpg", source, "image/jpeg")),
    ]
    data: dict[str, str] = {
        "model": model,
        "prompt": prompt,
        "size": "auto",
        "quality": "low",
        "background": "opaque",
        "n": "1",
        "output_format": "jpeg",
        "output_compression": "90",
    }
    if "mini" not in model.lower():
        data["input_fidelity"] = "high"

    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    timeout = httpx.Timeout(timeout_s, connect=min(8.0, timeout_s), read=timeout_s, write=min(15.0, timeout_s), pool=8.0)
    started = time.monotonic()
    _log(
        "AI_SELFIE_V308_OPENAI trace=%s stage=enter model=%s target=%s source=%s timeout=%.0fs",
        trace, model, fs.dims(target), fs.dims(source), timeout_s,
    )
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await asyncio.wait_for(
            client.post(f"{base_url}/images/edits", headers=headers, data=data, files=files),
            timeout=timeout_s + 1.0,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI identity edit HTTP {response.status_code}: {response.text[:500]}")
    js = response.json() or {}
    items = js.get("data") or []
    if not items or not isinstance(items[0], dict) or not items[0].get("b64_json"):
        raise RuntimeError("OpenAI identity edit returned no image")
    raw = base64.b64decode(items[0]["b64_json"])
    if len(raw) <= 1024:
        raise RuntimeError("OpenAI identity edit returned invalid image")
    bounded = v299._bounded_jpeg(raw, max_side=1400, quality=97)
    _log(
        "AI_SELFIE_V308_OPENAI trace=%s stage=success elapsed=%.2fs out=%s bytes=%s",
        trace, time.monotonic() - started, fs.dims(bounded), len(bounded),
    )
    return bounded, f"openai_{model}_identity_v308"


async def _provider_race_v308(target_crop: bytes, source_crop: bytes, *, trace: str):
    # The outer V299 wrapper still enforces its SLA. We intentionally finish this
    # race earlier so cleanup/validation never collides with that outer timeout.
    budget = min(58.0, max(38.0, v299._identity_budget() - 12.0))
    started = time.monotonic()
    deadline = started + budget
    tasks: dict[asyncio.Task, str] = {}

    if v301._official_openai_key():
        tasks[asyncio.create_task(_openai_identity(target_crop, source_crop, trace=trace))] = "openai_identity"
    if str(os.getenv("REPLICATE_API_TOKEN") or "").strip():
        tasks[asyncio.create_task(v307._replicate_branch(target_crop, source_crop, trace=trace))] = "replicate"
    if str(os.getenv("PIAPI_API_KEY") or "").strip():
        tasks[asyncio.create_task(v307._piapi_face_aware(target_crop, source_crop, trace=trace))] = "piapi_face_aware"
    if not tasks:
        raise RuntimeError("No identity provider configured")

    _log(
        "AI_SELFIE_V308_IDENTITY trace=%s stage=providers_start mode=three_way_race providers=%s budget=%.0fs",
        trace, ",".join(tasks.values()), budget,
    )
    errors: list[str] = []
    pending = set(tasks)
    try:
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0.5:
                break
            done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                break
            for task in done:
                name = tasks[task]
                try:
                    raw, provider = task.result()
                    raw, provider = await v299._validate_result(target_crop, raw, provider, trace=trace)
                    _log(
                        "AI_SELFIE_V308_IDENTITY trace=%s stage=provider_winner provider=%s elapsed=%.2fs",
                        trace, provider, time.monotonic() - started,
                    )
                    for other in pending:
                        other.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                    return raw, provider
                except Exception as exc:
                    errors.append(f"{name}:{type(exc).__name__}:{str(exc)[:220]}")
                    _log(
                        "AI_SELFIE_V308_IDENTITY trace=%s stage=provider_failed provider=%s error_type=%s error=%s remaining=%.1fs",
                        trace, name, type(exc).__name__, str(exc)[:400], max(0.0, deadline-time.monotonic()),
                    )
                    gc.collect()
        raise TimeoutError("; ".join(errors) or f"identity provider race exceeded {budget:.0f}s")
    finally:
        leftovers = [t for t in tasks if not t.done()]
        for task in leftovers:
            task.cancel()
        if leftovers:
            await asyncio.gather(*leftovers, return_exceptions=True)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    v299._provider_sequential = _provider_race_v308
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V308"
    setattr(terminal, "_v308_openai_identity_rescue", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V308 OpenAI identity rescue race installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
