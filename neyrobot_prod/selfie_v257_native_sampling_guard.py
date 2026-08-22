# -*- coding: utf-8 -*-
"""V257: make V256's enlargement guard depend on native source sampling only.

Codex review of V256 identified a gap in the intended 1.45x-1.90x real-source
range.  V256 required both a >=320 px native source-face short side and a
>=520 px *projected* short side.  Projection does not create source samples, so
that second condition could reject an easier 1.50x enlargement while accepting
the same source at a larger 1.90x enlargement.  The rejected case then walked
the V255 -> V252 fallback chain and could reintroduce provider-side pixelation.

V257 is deliberately a narrow successor hotfix:
- retain V256's <=1.90 transform limit and >=320 px native sampling floor;
- retire only the redundant projected-size floor before the V256 compositor runs;
- retain V255 source-face gate + target no-neck intersection, Poisson blending,
  94% real-source interior reinjection, PERSON-B firewall, and V253 lossless
  original-document delivery;
- reuse V256's existing fallback chain for every unrelated failure;
- add no Telegram callback, payment, UX, scene-owner, or provider handler.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v254_landmark_fit_seamless_source as v254
from neyrobot_prod import selfie_v255_source_face_gate as v255
from neyrobot_prod import selfie_v256_large_scale_source_pixels as v256

VERSION = "v257-native-sampling-guard-2026-08-22"
_INSTALLED = False
_BASE_V256_ENFORCE = None
_BASE_TRUE_FACE_TRANSFER = None


def _modules():
    return v256._modules()


def _log(message: str, *args: Any) -> None:
    v253._log(message, *args)


def _retire_projected_sampling_gate() -> None:
    """Keep V256's native-size/scale guards but remove projected-size rejection."""
    v256._MIN_PROJECTED_FACE_SHORT = 0.0


async def _true_face_transfer_v257(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    """Run the proven V256 compositor with native-sampling-only admission."""
    global _BASE_TRUE_FACE_TRANSFER
    if not callable(_BASE_TRUE_FACE_TRANSFER):
        raise RuntimeError("V257 base V256 face-transfer function was not captured")

    _retire_projected_sampling_gate()
    final, method = await _BASE_TRUE_FACE_TRANSFER(runtime, stage1, source, source_photo_no)

    # Relabel only the successful V256 real-source path.  If V256 legitimately
    # fell back to V255/V252 for another reason, preserve that method/provider.
    if method == "opencv_yunet_large_scale_real_source_pixels":
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "opencv_yunet_native_sampling_guard_v257"
        return final, "opencv_yunet_native_sampling_guard_real_source_pixels"
    return final, method


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V256, then own only the final native-sampling admission hotfix."""
    global _BASE_V256_ENFORCE
    if not callable(_BASE_V256_ENFORCE):
        raise RuntimeError("V257 base V256 enforcer was not captured")

    _retire_projected_sampling_gate()
    _BASE_V256_ENFORCE(bind_generate=bind_generate)
    _retire_projected_sampling_gate()

    v241, v245, v246, v247, v249, v250, v251, v252, transfer, google, ui, delivery = _modules()

    transfer._true_face_transfer = _true_face_transfer_v257
    delivery._deliver = v253._deliver_original

    # Historical late enforcers must always return to the final V257 owner.
    v256.enforce_runtime = enforce_runtime
    v255.enforce_runtime = enforce_runtime
    v254.enforce_runtime = enforce_runtime
    v253.enforce_runtime = enforce_runtime
    v252.enforce_runtime = enforce_runtime
    v251.enforce_runtime = enforce_runtime
    v247.enforce_runtime = enforce_runtime
    v246.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    for mod in (
        transfer, google, ui, delivery,
        v241, v245, v246, v247, v249, v250, v251, v252,
        v253, v254, v255, v256,
    ):
        mod.VERSION = VERSION

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.AI_SELFIE_SEND_AS_DOCUMENT = True
        runtime.CELEBRITY_SELFIE_ROUTE = (
            "v257-front-camera-yunet-native-sampling-source-pixels-lossless-document"
        )
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini geometry scaffold -> YuNet landmarks -> native-sampling real source-pixel warp <=1.90 -> "
            "V255 target/source hard face gate -> LAB + Poisson + 94% real source interior -> "
            "native PNG -> V253 original Telegram document; V256/V255 fallback chain retained"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V257_ENFORCE status=ok base=v256 scale_limit=%.2f native_face_short_min=%.1f "
        "projected_gate=false source_gate=v255 no_neck=true detail_reinject=0.94 "
        "provider_primary=false delivery=v253_original_document hero=pixel_locked version=%s",
        v256._MAX_REAL_SOURCE_SCALE, v256._MIN_NATIVE_FACE_SHORT, VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V256_ENFORCE, _BASE_TRUE_FACE_TRANSFER

    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    current = v256.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V256_ENFORCE = current

    _retire_projected_sampling_gate()
    current(bind_generate=True)
    *_, transfer, _, _, _ = _modules()
    _BASE_TRUE_FACE_TRANSFER = transfer._true_face_transfer

    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V257 native-sampling guard hotfix installed over V256", flush=True)


__all__ = [
    "VERSION",
    "install",
    "enforce_runtime",
    "_true_face_transfer_v257",
    "_retire_projected_sampling_gate",
]
