# -*- coding: utf-8 -*-
"""V302 AI Selfie Stage-1 fallback rescue.

V301 added OpenAI as a cross-provider fallback after Gemini Flash. Production
showed that an otherwise valid OpenAI key can still be unusable for the selected
Responses orchestrator (for example, organization verification required for
`gpt-5-mini`). V301 treated that OpenAI failure as terminal and never reached the
existing Gemini Pro fallback.

V302 keeps V301's fast source detector and bounded Stage-1, but makes the fallback
chain resilient:
  Gemini Flash -> OpenAI image fallback -> Gemini Pro fallback.
The OpenAI leg receives only a small slice of the existing fallback budget, so an
account/model permission error or a slow OpenAI request cannot consume the whole
Stage-1 deadline. No extra outer composition retries are introduced.
"""
from __future__ import annotations

import contextlib
import time
from typing import Any

from neyrobot_prod import selfie_v229_canonical_two_stage as v229
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v301_fast_resilient_stage1 as v301

VERSION = "v302-openai-failure-rescues-to-gemini-pro-2026-08-17"
_INSTALLED = False
_ORIGINAL_OPENAI_FALLBACK = v301._openai_image_fallback


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        v229._log(message, *args)


async def _openai_then_gemini_pro(
    prompt: str,
    labeled_images: list[tuple[str, bytes]],
    stage: str,
    timeout_s: float,
) -> tuple[bytes, str]:
    """Try OpenAI briefly, then always rescue to Gemini Pro on OpenAI failure."""
    started = time.monotonic()
    total = max(14.0, float(timeout_s))

    # Permission/configuration errors return immediately. If the provider is merely
    # slow, cap this leg so there is still meaningful time left for Gemini Pro.
    openai_slice = min(14.0, max(8.0, total * 0.30))
    try:
        return await _ORIGINAL_OPENAI_FALLBACK(
            prompt,
            labeled_images,
            stage,
            openai_slice,
        )
    except Exception as exc:
        elapsed = time.monotonic() - started
        remaining = max(8.0, total - elapsed - 0.5)
        text = str(exc)
        permission_like = any(
            token in text.lower()
            for token in (
                "organization must be verified",
                "verify organization",
                "permission",
                "not_found_error",
                "model_not_found",
                "http 401",
                "http 403",
                "http 404",
            )
        )
        _log(
            "AI_SELFIE_V302_STAGE1 stage=%s provider=openai status=failed rescue=gemini_pro permission_like=%s elapsed=%.2fs remaining=%.1fs error_type=%s error=%s",
            stage,
            permission_like,
            elapsed,
            remaining,
            type(exc).__name__,
            text[:420],
        )
        return await v301._gemini_pro_fallback(
            prompt,
            labeled_images,
            stage,
            remaining,
        )


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    # _call_stage1_v301 resolves this module global at runtime, so replacing the
    # function is enough; the final v229._call_google owner remains V301.
    v301._openai_image_fallback = _openai_then_gemini_pro
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V302"
    setattr(terminal, "_v302_openai_rescue_to_gemini_pro", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V302 OpenAI fallback rescue installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
