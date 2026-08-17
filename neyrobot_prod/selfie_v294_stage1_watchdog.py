# -*- coding: utf-8 -*-
"""V294 Stage-1 stall guard for AI Selfie.

V293 added a post-composition anatomy validator, but V287 still prepared AGE/BUILD
references synchronously with the multi-detector face-cluster routine before the
Gemini request was even started. On some reference images that CPU path can block
Stage 1 for minutes, so neither the Gemini timeout nor heartbeat can advance.

V294 removes CV work from that pre-request path. AGE/BUILD refs are passed through
unchanged when reasonably sized and only get a cheap PIL/Lanczos size bound when
large. V293's prompt + anatomy/framing gate remain responsible for close framing.
It also adds a hard async watchdog around the full Gemini call once control reaches
an await point, so provider stalls cannot leave Stage 1 open indefinitely.
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

VERSION = "v294-stage1-nonblocking-watchdog-2026-08-17"
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
            # Normal Telegram refs are already compact. Keep their exact bytes: this
            # is both the highest-quality and cheapest path.
            if max(w, h) <= 1600 and len(data) <= 3 * 1024 * 1024:
                _log(
                    "AI_SELFIE_V294_BODY_REF status=native_passthrough dims=%sx%s bytes=%s elapsed=%.3fs cv=false",
                    w, h, len(data), time.monotonic() - started,
                )
                return data

            # Large originals are bounded only for request size/RAM. No detector,
            # no semantic crop, and no second expensive preprocessing pass.
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            src.thumbnail((1600, 1600), resample)
            out = BytesIO()
            src.save(out, "JPEG", quality=97, subsampling=0, optimize=False, progressive=False)
            result = out.getvalue()
            _log(
                "AI_SELFIE_V294_BODY_REF status=bounded_passthrough in=%sx%s out=%s bytes_in=%s bytes_out=%s elapsed=%.3fs cv=false",
                w, h, fs.dims(result), len(data), len(result), time.monotonic() - started,
            )
            return result
        finally:
            src.close()
    except Exception as exc:
        _log(
            "AI_SELFIE_V294_BODY_REF status=raw_fallback error_type=%s error=%s dims=%s bytes=%s elapsed=%.3fs cv=false",
            type(exc).__name__, str(exc)[:260], fs.dims(data), len(data), time.monotonic() - started,
        )
        return data


async def _call_google_watchdog(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    timeout_s = max(90.0, min(420.0, float(os.getenv("AI_SELFIE_STAGE1_TIMEOUT_S") or "300")))
    started = time.monotonic()
    _log(
        "AI_SELFIE_V294_STAGE1 stage=%s status=enter refs=%s timeout=%.0fs",
        stage, len(labeled_images), timeout_s,
    )
    try:
        result = await asyncio.wait_for(
            _ORIGINAL_GOOGLE_CALL(prompt, labeled_images, stage),
            timeout=timeout_s,
        )
        _log(
            "AI_SELFIE_V294_STAGE1 stage=%s status=exit elapsed=%.2fs",
            stage, time.monotonic() - started,
        )
        return result
    except asyncio.TimeoutError as exc:
        _log(
            "AI_SELFIE_V294_STAGE1 stage=%s status=timeout elapsed=%.2fs timeout=%.0fs",
            stage, time.monotonic() - started, timeout_s,
        )
        raise TimeoutError(f"AI Selfie Stage 1 exceeded {timeout_s:.0f}s") from exc


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    # V293 captured V287's wrapper by function reference. That wrapper resolves
    # _upper_body_reference from the V287 module globals at execution time, so
    # replacing this symbol fixes even the already-captured call chain.
    v287._upper_body_reference = _fast_body_reference

    # V294 is the outermost caller: V294 watchdog -> V293 anatomy gate -> V287 refs
    # -> V280 POV gate -> resilient Gemini provider.
    v229._call_google = _call_google_watchdog
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V294"
    setattr(terminal, "_v294_stage1_nonblocking", True)
    setattr(terminal, "_v294_stage1_watchdog", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V294 nonblocking Stage-1 refs + watchdog installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]