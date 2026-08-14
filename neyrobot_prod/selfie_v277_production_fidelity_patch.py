# -*- coding: utf-8 -*-
"""Production AI Selfie fidelity patch.

Goals:
1) selfie mode must look like the final front-camera image; the phone/camera/holding
   hand must never be visible in-frame;
2) preserve terminal user identity without generative face restoration;
3) keep production latency bounded. The previous 1800px + 4x InSwapper path could
   spend several minutes inside Replicate, making Telegram look frozen.

This module patches selfie_v257_consolidated_runtime in place so the guaranteed
V257 runtime owner continues to own Telegram routing and billing.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal

VERSION = "v278-production-fast-fidelity-2026-08-15"
_ORIGINAL_PROMPT = terminal._prompt
_INSTALLED = False


def _prompt(name: str, scene_text: str, shot_label: str, has_scene_image: bool, attempt: int) -> str:
    base = _ORIGINAL_PROMPT(name, scene_text, shot_label, has_scene_image, attempt)
    is_selfie = "селфи" in str(shot_label or "").lower() or "selfie" in str(shot_label or "").lower()
    if is_selfie:
        camera_rule = (
            " SELFIE CAMERA GEOMETRY — ABSOLUTE REQUIREMENT: the requested image is the FINAL FRAME already captured by the front-facing smartphone camera. "
            "The viewpoint is the phone/front-camera lens itself, not an external camera looking at someone taking a selfie. "
            "NO PHONE OR CAMERA DEVICE MAY APPEAR ANYWHERE IN THE IMAGE. Do not show a smartphone, phone edge, phone back, camera body, selfie stick, mirror reflection of a phone, or a hand/arm holding a phone toward the camera. "
            "Both people look naturally toward the invisible front-camera lens. A forearm may enter frame only if anatomically natural and NOT holding any device. "
            "Treat any visible phone/camera/selfie-stick as a composition failure and regenerate without it."
        )
    else:
        camera_rule = (
            " THIRD-PERSON CAMERA GEOMETRY — ABSOLUTE REQUIREMENT: this is an ordinary photograph taken by another person. "
            "Neither principal person is taking a selfie. NO smartphone, camera body, selfie stick, or hand holding a recording device may appear in-frame."
        )
    return base + camera_rule


def _exact_identity_enabled() -> bool:
    # Keep the expensive PhotoRoom head-overlay path opt-in. V263 already proved
    # that raw InSwapper preserves identity well; enabling another network pass by
    # default only increases latency and can make the bot appear stuck.
    value = str(os.getenv("AI_SELFIE_V277_EXACT_IDENTITY_CORE") or "0").strip().lower()
    return value not in {"0", "false", "off", "no"}


def _has_photoroom() -> bool:
    return bool((os.getenv("PHOTOROOM_API_KEY") or os.getenv("PHOTO_ROOM_API_KEY") or "").strip())


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    """Fast identity-first transfer with a hard Replicate latency budget."""
    raw: bytes | None = None
    provider = ""

    replicate_token = str(os.getenv("REPLICATE_API_TOKEN") or "").strip()
    if replicate_token:
        try:
            from neyrobot_prod import selfie_v252_faceswap_quality_diag as ins

            # 1400px provider inputs were already proven in V263 to retain strong
            # identity while finishing quickly. Upscale=2 avoids the huge 4x compute
            # multiplier; face_upsample improves local detail without CodeFormer.
            provider_target = terminal._supersample(target_crop, min_long_side=1400)
            provider_source = terminal._supersample(source_crop, min_long_side=1400)
            inputs = {
                "upscale": 2,
                "source_img": ins._data_url(provider_source),
                "target_img": ins._data_url(provider_target),
                "face_restore": False,
                "face_upsample": True,
                "source_indexes": "0",
                "target_indexes": "0",
                "background_enhance": False,
                "codeformer_fidelity": 1.0,
            }
            log(
                "AI_SELFIE_V278_IDENTITY trace=%s provider=replicate_inswapper stage=create "
                "target_native=%s target_provider=%s source_native=%s source_provider=%s "
                "upscale=2 face_restore=false face_upsample=true indexes=0 timeout=120s",
                trace, fs.dims(target_crop), fs.dims(provider_target), fs.dims(source_crop), fs.dims(provider_source),
            )
            candidate = await asyncio.wait_for(
                ins._replicate_swap_once(
                    version=ins.REPLICATE_INSWAPPER_VERSION,
                    inputs=inputs,
                    trace=trace,
                    label="v278_prod_inswapper_fast_fidelity",
                ),
                timeout=120.0,
            )
            if len(candidate) >= 1024 and fs.sha(candidate) != fs.sha(provider_target):
                raw = candidate
                provider = "replicate_inswapper_fast_fidelity"
                log(
                    "AI_SELFIE_V278_IDENTITY trace=%s provider=replicate_inswapper stage=success sha=%s dims=%s bytes=%s",
                    trace, fs.sha(raw), fs.dims(raw), len(raw),
                )
            else:
                raise RuntimeError("InSwapper returned unchanged/empty target")
        except asyncio.TimeoutError:
            log(
                "AI_SELFIE_V278_IDENTITY trace=%s provider=replicate_inswapper stage=timeout budget=120s fallback=piapi",
                trace,
            )
        except Exception as exc:
            log(
                "AI_SELFIE_V278_IDENTITY trace=%s provider=replicate_inswapper stage=fallback error_type=%s error=%s",
                trace, type(exc).__name__, str(exc)[:700],
            )

    if raw is None and str(os.getenv("PIAPI_API_KEY") or "").strip():
        # Keep fallback smaller than the old 1700px path so a Replicate timeout does
        # not turn into a second multi-minute wait.
        provider_target = terminal._supersample(target_crop, min_long_side=1250)
        provider_source = terminal._supersample(source_crop, min_long_side=1250)
        candidate = await fs.piapi_swap_once(provider_target, provider_source, log, trace=trace)
        if fs.sha(candidate) == fs.sha(provider_target):
            raise RuntimeError("PiAPI returned unchanged target crop")
        raw = candidate
        provider = "piapi_qubico_fast_fallback"

    if raw is None:
        raise RuntimeError("No Face Swap provider configured or identity providers timed out")

    # Optional exact identity core. Disabled by default for production latency.
    if _exact_identity_enabled() and _has_photoroom():
        try:
            from neyrobot_prod import selfie_v272_photoroom_head_cutout_diag as v276

            source_face = fs.source_face_crop(source_crop, None)
            target_face = fs.source_face_crop(raw, None)
            exact, meta = v276._overlay(
                source_full_raw=source_crop,
                source_face_box=source_face.face_box,
                target_full_raw=raw,
                target_face_box=target_face.face_box,
                baseline_full_raw=raw,
                outer_strength=0.94,
                core_strength=1.0,
            )
            if len(exact) >= 1024 and fs.sha(exact) != fs.sha(raw):
                log(
                    "AI_SELFIE_V278_IDENTITY trace=%s stage=opaque_identity_core status=success "
                    "provider=%s sha=%s dims=%s mode=%s",
                    trace, provider, fs.sha(exact), fs.dims(exact), meta.get("mode"),
                )
                return exact, provider + "+photoroom_opaque_identity_core"
        except Exception as exc:
            log(
                "AI_SELFIE_V278_IDENTITY trace=%s stage=opaque_identity_core status=fallback "
                "provider=%s error_type=%s error=%s",
                trace, provider, type(exc).__name__, str(exc)[:700],
            )

    return raw, provider


def install() -> bool:
    global _INSTALLED
    if _INSTALLED and getattr(terminal, "_v278_production_fast_fidelity", False):
        return True
    terminal._prompt = _prompt
    terminal._identity_swap = _identity_swap
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V278"
    setattr(terminal, "_v278_production_fast_fidelity", True)

    try:
        from neyrobot_prod import selfie_v218_runtime_owner as owner
        owner.VERSION = VERSION
    except Exception:
        pass

    print(f"[neyrobot-prod] V278 production fast fidelity installed version={VERSION}", flush=True)
    _INSTALLED = True
    return True


__all__ = ["VERSION", "install"]
