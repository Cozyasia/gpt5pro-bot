# -*- coding: utf-8 -*-
"""V295b identity fidelity recovery.

V295's direct affine/source-pixel relock produced a visibly pasted, distorted face:
it preserved source pixels too literally while forcing them into a different head pose,
lighting field and camera geometry. V295b removes that path entirely.

The production rule is now:
- photo #3 remains the identity source;
- use the proven provider face-swap stack to adapt identity to target pose/light;
- never paste or affine-warp source face pixels over the final result;
- keep gaze correction off when the source already has reliable eyes;
- only use the tiny V292 iris correction as a last-resort when eye evidence is weak.
"""
from __future__ import annotations

import contextlib
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v289_native_identity_primary as v289
from neyrobot_prod import selfie_v290_gaze_quality_singleflight as v292

VERSION = "v295b-provider-adapted-identity-no-source-paste-2026-08-17"
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        from neyrobot_prod import selfie_v229_canonical_two_stage as v229
        v229._log(message, *args)


def _source_eye_evidence(source_crop: bytes) -> tuple[bool, str]:
    try:
        face = fs.source_face_crop(source_crop, None)
        eyes = int(getattr(face, "eye_count", 0))
        support = int(getattr(face, "support", 0))
        fw = int(face.face_box[2]); fh = int(face.face_box[3])
        good = bool((eyes >= 1 or support >= 4) and fw >= 220 and fh >= 220)
        return good, f"eyes={eyes} support={support} face={face.face_box}"
    except Exception as exc:
        return False, f"{type(exc).__name__}:{str(exc)[:300]}"


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    """Provider-adapted identity only; no direct source-pixel face transplant."""
    source_good, source_reason = _source_eye_evidence(source_crop)
    log(
        "AI_SELFIE_V295B_IDENTITY trace=%s stage=start source_photo3=true source_eye_evidence=%s detail=%s target=%s source=%s",
        trace, source_good, source_reason, fs.dims(target_crop), fs.dims(source_crop),
    )

    # Call the pre-V289 provider-resilient stack directly. This is the path that
    # produced the visually coherent pre-V295 result (e.g. Replicate InSwapper),
    # while V295's affine re-lock is intentionally bypassed.
    try:
        candidate, provider = await v292._REMOTE_FALLBACK(target_crop, source_crop, log, trace=trace)
        if len(candidate) < 1024 or fs.sha(candidate) == fs.sha(target_crop):
            raise RuntimeError("provider returned unchanged/empty identity image")

        geometry_ok, geometry_reason = v289._geometry_status(target_crop, candidate, log, trace=trace)
        if not geometry_ok:
            raise RuntimeError(f"provider geometry rejected: {geometry_reason}")

        # If the source portrait already has reliable eye evidence, preserve the
        # provider's adapted eyes. It normally keeps gaze coherent with target pose.
        # Do not copy target/generated irises over a good identity result.
        if source_good:
            log(
                "AI_SELFIE_V295B_IDENTITY trace=%s stage=success provider=%s gaze=provider_preserved source_paste=false out=%s",
                trace, provider, fs.dims(candidate),
            )
            return candidate, str(provider) + "+v295b_no_source_paste"

        # Weak-eye fallback only: V292 correction is extremely local and affects
        # iris centers, not eyelids/brows/face geometry.
        corrected = v292._iris_only_camera_gaze(target_crop, candidate, log, trace=trace)
        log(
            "AI_SELFIE_V295B_IDENTITY trace=%s stage=success provider=%s gaze=iris_fallback source_paste=false out=%s",
            trace, provider, fs.dims(corrected),
        )
        return corrected, str(provider) + "+v295b_iris_fallback"
    except Exception as exc:
        log(
            "AI_SELFIE_V295B_IDENTITY trace=%s stage=provider_failed error_type=%s error=%s fallback=v289",
            trace, type(exc).__name__, str(exc)[:700],
        )

    # Emergency fallback only. V289 can still recover a result if the provider stack
    # is unavailable, but we never run the V295 affine/source-pixel relock afterward.
    candidate, provider = await v289._identity_swap(target_crop, source_crop, log, trace=trace)
    if source_good:
        return candidate, str(provider) + "+v295b_emergency"
    candidate = v292._iris_only_camera_gaze(target_crop, candidate, log, trace=trace)
    return candidate, str(provider) + "+v295b_emergency_iris"


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    # Undo V295 monkey-patching of V292 helpers by making terminal identity ownership
    # explicit. We deliberately do not replace V292's source-authoritative core.
    terminal._identity_swap = _identity_swap
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V295B"
    setattr(terminal, "_v295_source_photo3_likeness_lock", False)
    setattr(terminal, "_v295b_provider_adapted_identity", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V295b provider-adapted identity installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
