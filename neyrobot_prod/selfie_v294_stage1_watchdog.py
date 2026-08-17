# -*- coding: utf-8 -*-
"""V296 Stage-1 production latency guard for AI Selfie.

V294 removed blocking OpenCV preprocessing, but its provider watchdog still allowed
one composition request to occupy 300 seconds (and up to 420 seconds by env). That is
not a production-safe latency budget. V296 keeps the cheap reference path and turns
the watchdog into a strict per-provider-call SLA: 100 seconds by default, configurable
between 60 and 150 seconds. Slow generations fail fast instead of holding a Telegram
request for many minutes.
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

VERSION = "v296-stage1-production-latency-cap-2026-08-17"
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
                    "AI_SELFIE_V296_BODY_REF status=native_passthrough dims=%sx%s bytes=%s elapsed=%.3fs cv=false",
                    w, h, len(data), time.monotonic() - started,
                )
                return data

            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            src.thumbnail((1600, 1600), resample)
            out = BytesIO()
            src.save(out, "JPEG", quality=96, subsampling=0, optimize=False, progressive=False)
            result = out.getvalue()
            _log(
                "AI_SELFIE_V296_BODY_REF status=bounded_passthrough in=%sx%s out=%s bytes_in=%s bytes_out=%s elapsed=%.3fs cv=false",
                w, h, fs.dims(result), len(data), len(result), time.monotonic() - started,
            )
            return result
        finally:
            src.close()
    except Exception as exc:
        _log(
            "AI_SELFIE_V296_BODY_REF status=raw_fallback error_type=%s error=%s dims=%s bytes=%s elapsed=%.3fs cv=false",
            type(exc).__name__, str(exc)[:260], fs.dims(data), len(data), time.monotonic() - started,
        )
        return data


def _provider_timeout() -> float:
    try:
        requested = float(os.getenv("AI_SELFIE_STAGE1_TIMEOUT_S") or "100")
    except Exception:
        requested = 100.0
    return max(60.0, min(150.0, requested))


async def _call_google_watchdog(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    timeout_s = _provider_timeout()
    started = time.monotonic()
    _log(
        "AI_SELFIE_V296_STAGE1 stage=%s status=enter refs=%s timeout=%.0fs production_sla=true",
        stage, len(labeled_images), timeout_s,
    )
    try:
        result = await asyncio.wait_for(
            _ORIGINAL_GOOGLE_CALL(prompt, labeled_images, stage),
            timeout=timeout_s,
        )
        _log(
            "AI_SELFIE_V296_STAGE1 stage=%s status=exit elapsed=%.2fs",
            stage, time.monotonic() - started,
        )
        return result
    except asyncio.TimeoutError as exc:
        elapsed = time.monotonic() - started
        _log(
            "AI_SELFIE_V296_STAGE1 stage=%s status=timeout elapsed=%.2fs timeout=%.0fs fail_fast=true",
            stage, elapsed, timeout_s,
        )
        raise TimeoutError(f"AI Selfie composition provider exceeded production SLA ({timeout_s:.0f}s)") from exc


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    v287._upper_body_reference = _fast_body_reference
    v229._call_google = _call_google_watchdog
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V296"
    setattr(terminal, "_v294_stage1_nonblocking", True)
    setattr(terminal, "_v294_stage1_watchdog", True)
    setattr(terminal, "_v296_stage1_latency_cap", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V296 Stage-1 production latency cap installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
