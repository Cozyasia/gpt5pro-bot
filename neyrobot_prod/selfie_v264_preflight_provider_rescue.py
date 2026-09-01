# -*- coding: utf-8 -*-
"""Recover V264 source-sampling preflight failures with the existing provider rescue.

The dense V264 compositor must never enlarge native source pixels beyond its sampling
budget. That guard is correct, but an overscale/small-source condition is not a fatal
user error: the isolated provider path can operate on a compact source face and is the
intended production rescue. This overlay catches only those two explicit preflight
conditions. All other exceptions keep their existing semantics.

No Telegram handler, payment route, third candidate, or PERSON-B mutation is added.
"""
from __future__ import annotations

from typing import Any, Callable

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v263_dense_identity_lock as v263
from neyrobot_prod import selfie_v264_dense68_roi_production as v264
from neyrobot_prod import selfie_v264_production_quality_rescue as guard

VERSION = v264.VERSION
_INSTALLED = False
_BASE_TRANSFER: Callable[..., Any] | None = None

_RECOVERABLE_MARKERS = (
    "V264 invalid similarity scale=",
    "V264 source sampling too small:",
)


def _log(message: str, *args: Any) -> None:
    v264._log(message, *args)


def _recoverable_preflight_reason(exc: BaseException) -> str | None:
    if not isinstance(exc, RuntimeError):
        return None
    message = str(exc or "")
    if any(marker in message for marker in _RECOVERABLE_MARKERS):
        return message[:300]
    return None


async def _true_face_transfer_preflight_safe(
    runtime: Any,
    stage1: bytes,
    source: bytes,
    source_photo_no: int,
):
    if not callable(_BASE_TRANSFER):
        raise RuntimeError("V264 preflight rescue base transfer is unavailable")

    try:
        return await _BASE_TRANSFER(runtime, stage1, source, source_photo_no)
    except Exception as exc:
        reason = _recoverable_preflight_reason(exc)
        if not reason:
            raise

        _log(
            "AI_SELFIE_V264_PREFLIGHT_RESCUE status=triggered route=isolated_provider "
            "reason=%s dense_source_warp=skipped max_candidates=2",
            reason,
        )

        # The provider rescue is the replacement candidate for a local dense attempt
        # that could not safely begin. Do not cap the dense scale and do not upsample
        # the source into the local compositor merely to satisfy the guard.
        yunet_path = await v253._ensure_yunet_model()
        dense_path, recognition_path = await v263._ensure_identity_models()
        rescue, provider = await guard._provider_rescue(
            runtime, bytes(stage1 or b""), bytes(source or b""), int(source_photo_no)
        )
        metrics = guard._evaluate_candidate(
            rescue,
            bytes(stage1 or b""),
            bytes(source or b""),
            yunet_path,
            dense_path,
            recognition_path,
        )
        passed, failures = guard._production_gate(metrics)
        _log(
            "AI_SELFIE_V264_PRODUCTION_GATE path=preflight_provider_rescue status=%s "
            "provider=%s identity=%.4f worst_eye=%.4f inner_nme=%.4f target_face_short=%.1f failures=%s",
            "pass" if passed else "fail",
            provider,
            float(metrics.get("identity_similarity_cosine", 0.0)),
            max(
                float(metrics.get("left_eye_error", 1.0)),
                float(metrics.get("right_eye_error", 1.0)),
            ),
            float(metrics.get("inner_face_landmark_nme", 1.0)),
            float(metrics.get("target_face_short", 0.0)),
            "none" if not failures else "|".join(failures),
        )
        if not passed:
            _log(
                "AI_SELFIE_V264_PRODUCTION_REJECT status=rejected after=preflight_provider_rescue "
                "delivery=blocked failures=%s",
                "|".join(failures) if failures else "unknown",
            )
            raise RuntimeError(
                "V264 production quality gate rejected PERSON-A after preflight provider rescue"
            ) from exc

        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = provider
        runtime.AI_SELFIE_LAST_IDENTITY_PATH = "v264_preflight_provider_rescue"
        runtime.AI_SELFIE_LAST_IDENTITY_METRICS = dict(metrics)
        return rescue, "provider_isolated_preflight_identity_rescue"


def install() -> None:
    global _INSTALLED, _BASE_TRANSFER
    current = v264._true_face_transfer_v264
    if current is _true_face_transfer_preflight_safe:
        _INSTALLED = True
        return
    if not _INSTALLED:
        _BASE_TRANSFER = current
    elif not callable(_BASE_TRANSFER):
        raise RuntimeError("V264 preflight rescue lost base transfer")

    v264._true_face_transfer_v264 = _true_face_transfer_preflight_safe
    v264.enforce_runtime(bind_generate=True)
    _INSTALLED = True
    _log(
        "AI_SELFIE_V264_PREFLIGHT_RESCUE_INSTALL status=ok recoverable=overscale_or_small_source "
        "route=isolated_provider dense_scale_cap=false max_candidates=2 person_b=pixel_restored"
    )


__all__ = [
    "VERSION",
    "install",
    "_recoverable_preflight_reason",
    "_true_face_transfer_preflight_safe",
]
