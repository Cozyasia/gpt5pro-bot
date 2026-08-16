# -*- coding: utf-8 -*-
"""V285 resilient identity transfer for production AI Selfie.

Hardens the V280 identity stage against provider-side `no face found` failures.
Local production detection has already proved that both source and target contain
usable faces before this stage; PiAPI can still reject very tight/cropped faces.
V285 retries PiAPI once on a padded canvas and, if all remote identity providers
fail, uses the existing source-native facial core as a deterministic last-resort
identity path instead of failing the entire paid generation.
"""
from __future__ import annotations

import os
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v277_production_fidelity_patch as fidelity

VERSION = "v285-identity-no-face-resilience-2026-08-16"
_INSTALLED = False
_ORIGINAL_IDENTITY_SWAP = terminal._identity_swap


def _padded_canvas(raw: bytes, *, factor: float = 1.42) -> bytes:
    """Add context around a tight face crop without inventing identity pixels."""
    from PIL import Image, ImageFilter

    img = fs.image(raw).convert("RGB")
    w, h = img.size
    nw = max(w + 64, int(round(w * factor)))
    nh = max(h + 64, int(round(h * factor)))

    # Soft edge-derived background gives provider detectors normal image context
    # while the original crop remains untouched at the centre.
    bg = img.resize((nw, nh), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(max(8.0, min(nw, nh) * 0.025)))
    canvas = bg.copy()
    x = (nw - w) // 2
    y = (nh - h) // 2
    canvas.paste(img, (x, y))
    return fs.jpeg(canvas, max_side=2200, quality=100)


def _local_face_summary(raw: bytes) -> str:
    try:
        target = fs.source_face_crop(raw, None)
        return f"face={target.face_box} crop={target.crop_box} dims={fs.dims(raw)}"
    except Exception as exc:
        return f"local_face_error={type(exc).__name__}:{str(exc)[:180]} dims={fs.dims(raw)}"


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    try:
        return await _ORIGINAL_IDENTITY_SWAP(target_crop, source_crop, log, trace=trace)
    except Exception as original_exc:
        message = str(original_exc)
        log(
            "AI_SELFIE_V285_IDENTITY trace=%s stage=primary_failed error_type=%s error=%s target=%s source=%s",
            trace, type(original_exc).__name__, message[:700], _local_face_summary(target_crop), _local_face_summary(source_crop),
        )

        # Provider-side no-face errors are commonly caused by a very tight crop even
        # when our local detectors see a strong face. Retry PiAPI once with more head/
        # shoulder context before using the deterministic source-native fallback.
        if str(os.getenv("PIAPI_API_KEY") or "").strip():
            try:
                padded_target = _padded_canvas(target_crop, factor=1.42)
                padded_source = _padded_canvas(source_crop, factor=1.42)
                provider_target = terminal._supersample(padded_target, min_long_side=1800)
                provider_source = terminal._supersample(padded_source, min_long_side=1800)
                log(
                    "AI_SELFIE_V285_IDENTITY trace=%s stage=piapi_padded_retry target_native=%s target_provider=%s source_native=%s source_provider=%s",
                    trace, fs.dims(padded_target), fs.dims(provider_target), fs.dims(padded_source), fs.dims(provider_source),
                )
                candidate = await fs.piapi_swap_once(provider_target, provider_source, log, trace=trace)
                if len(candidate) >= 1024 and fs.sha(candidate) != fs.sha(provider_target):
                    try:
                        exact, meta = fidelity._source_native_face_core(source_crop, candidate, log, trace=trace)
                        if len(exact) >= 1024:
                            log(
                                "AI_SELFIE_V285_IDENTITY trace=%s stage=piapi_padded_success source_core=true mode=%s dims=%s",
                                trace, meta.get("mode"), fs.dims(exact),
                            )
                            return exact, "piapi_qubico_padded_retry+source_native_face_core"
                    except Exception as core_exc:
                        log(
                            "AI_SELFIE_V285_IDENTITY trace=%s stage=piapi_padded_core_fallback error_type=%s error=%s",
                            trace, type(core_exc).__name__, str(core_exc)[:500],
                        )
                    return candidate, "piapi_qubico_padded_retry"
            except Exception as retry_exc:
                log(
                    "AI_SELFIE_V285_IDENTITY trace=%s stage=piapi_padded_failed error_type=%s error=%s",
                    trace, type(retry_exc).__name__, str(retry_exc)[:700],
                )

        # Last-resort deterministic identity path. This is not a generic passthrough:
        # V280 maps the user's native photo-3 eyes/nose/mouth/cheeks into the detected
        # target geometry. No extra Gemini call and no additional paid composition.
        try:
            exact, meta = fidelity._source_native_face_core(source_crop, target_crop, log, trace=trace)
            if len(exact) >= 1024 and fs.sha(exact) != fs.sha(target_crop):
                log(
                    "AI_SELFIE_V285_IDENTITY trace=%s stage=source_native_emergency_success mode=%s dims=%s original_error=%s",
                    trace, meta.get("mode"), fs.dims(exact), message[:350],
                )
                return exact, "source_native_face_core_emergency"
        except Exception as core_exc:
            log(
                "AI_SELFIE_V285_IDENTITY trace=%s stage=source_native_emergency_failed error_type=%s error=%s",
                trace, type(core_exc).__name__, str(core_exc)[:700],
            )

        raise original_exc


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._identity_swap = _identity_swap
    setattr(terminal, "_v285_identity_no_face_resilience", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V285 identity no-face resilience installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
