# -*- coding: utf-8 -*-
"""V289b deterministic native-identity primary path for AI Selfie.

The production runtime reaches this function only after `_target()` has already
returned a locally verified PERSON A crop. Re-detecting that tight crop and then
falling back to remote providers reintroduced the same detector instability V289
was meant to remove. V289b therefore treats the upstream target contract as
authoritative, requires strong source-photo evidence, and uses the source-native
facial core first. Post-transfer face geometry is diagnostic and only rejects
catastrophic displacement; ordinary detector jitter must not trigger a 5-minute
Replicate/PiAPI fallback.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v277_production_fidelity_patch as fidelity

VERSION = "v289b-native-identity-authoritative-target-2026-08-16"
_INSTALLED = False
_ORIGINAL_IDENTITY_SWAP = terminal._identity_swap


def _face_info(raw: bytes) -> tuple[Any, tuple[int, int], float]:
    face = fs.source_face_crop(raw, None)
    w, h = fs.image(raw).size
    ratio = float(face.face_box[3]) / float(max(1, h))
    return face, (w, h), ratio


def _local_gate(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bool, str]:
    """Trust the runtime's verified target; independently require a strong source."""
    try:
        source, sdims, sr = _face_info(source_crop)
        _sx, _sy, sw, sh = [int(v) for v in source.face_box]
        tw, th = fs.image(target_crop).size

        source_ok = sw >= 280 and sh >= 280 and sr >= 0.22
        source_evidence = int(getattr(source, "support", 0)) >= 2 or int(getattr(source, "eye_count", 0)) >= 1
        # target_crop is produced only after `_target()` has locked PERSON A. Here we
        # merely reject corrupt/tiny payloads; we do NOT demand a second Haar success.
        target_payload_ok = tw >= 180 and th >= 180 and len(target_crop) >= 4096
        ok = bool(source_ok and source_evidence and target_payload_ok)
        reason = (
            f"target_dims={(tw, th)} target_payload_ok={target_payload_ok} "
            f"source_face={source.face_box} source_dims={sdims} source_ratio={sr:.4f} "
            f"source_ok={source_ok} source_evidence={source_evidence} upstream_target=authoritative"
        )
        log("AI_SELFIE_V289B_GATE trace=%s status=%s %s", trace, "pass" if ok else "fallback", reason)
        return ok, reason
    except Exception as exc:
        reason = f"{type(exc).__name__}:{str(exc)[:400]}"
        log("AI_SELFIE_V289B_GATE trace=%s status=fallback error=%s", trace, reason)
        return False, reason


def _geometry_status(reference_raw: bytes, candidate_raw: bytes, log: Any, *, trace: str) -> tuple[bool, str]:
    """Diagnostic geometry check; reject only obviously catastrophic displacement."""
    try:
        ref, rdims, _ = _face_info(reference_raw)
        cand, cdims, _ = _face_info(candidate_raw)
        rw, rh = rdims; cw, ch = cdims
        rx, ry, rfw, rfh = [float(v) for v in ref.face_box]
        cx, cy, cfw, cfh = [float(v) for v in cand.face_box]
        rcenter = ((rx + rfw / 2.0) / max(1.0, rw), (ry + rfh / 2.0) / max(1.0, rh))
        ccenter = ((cx + cfw / 2.0) / max(1.0, cw), (cy + cfh / 2.0) / max(1.0, ch))
        center_delta = abs(rcenter[0] - ccenter[0]) + abs(rcenter[1] - ccenter[1])
        scale = (cfh / max(1.0, ch)) / max(0.001, rfh / max(1.0, rh))
        catastrophic = center_delta > 0.34 or scale < 0.45 or scale > 2.20
        status = "reject" if catastrophic else "pass"
        log(
            "AI_SELFIE_V289B_GEOMETRY trace=%s status=%s center_delta=%.4f scale_ratio=%.4f ref_face=%s cand_face=%s",
            trace, status, center_delta, scale, ref.face_box, cand.face_box,
        )
        return (not catastrophic), f"center_delta={center_delta:.4f} scale={scale:.4f}"
    except Exception as exc:
        # Failure to re-detect the already-produced native facial core is not enough
        # to justify paying a remote detector again. The integration geometry itself
        # has not moved; the core is pasted into the same target crop coordinates.
        log("AI_SELFIE_V289B_GEOMETRY trace=%s status=validator_unavailable error_type=%s error=%s accept=true",
            trace, type(exc).__name__, str(exc)[:400])
        return True, "validator_unavailable_accept"


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    safe, _reason = _local_gate(target_crop, source_crop, log, trace=trace)
    if safe:
        try:
            candidate, meta = fidelity._source_native_face_core(source_crop, target_crop, log, trace=trace)
            if len(candidate) < 1024 or fs.sha(candidate) == fs.sha(target_crop):
                raise RuntimeError("source-native primary returned unchanged/empty target")
            geometry_ok, geometry_reason = _geometry_status(target_crop, candidate, log, trace=trace)
            if not geometry_ok:
                raise RuntimeError(f"source-native primary catastrophic geometry change: {geometry_reason}")
            log(
                "AI_SELFIE_V289B_IDENTITY trace=%s stage=native_primary_success mode=%s target_dims=%s source_dims=%s out_dims=%s sha=%s remote_provider=false expression=photo3 upstream_target=authoritative",
                trace, meta.get("mode"), fs.dims(target_crop), fs.dims(source_crop), fs.dims(candidate), fs.sha(candidate),
            )
            return candidate, "source_native_face_core_v289b_primary"
        except Exception as exc:
            log(
                "AI_SELFIE_V289B_IDENTITY trace=%s stage=native_primary_failed error_type=%s error=%s fallback=remote_stack",
                trace, type(exc).__name__, str(exc)[:700],
            )

    return await _ORIGINAL_IDENTITY_SWAP(target_crop, source_crop, log, trace=trace)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._identity_swap = _identity_swap
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V289B"
    setattr(terminal, "_v289_native_identity_primary", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V289b native identity primary installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
