# -*- coding: utf-8 -*-
"""V289 deterministic native-identity primary path for AI Selfie.

Production observation behind this patch:
- Gemini composition and the local PERSON A detector are already succeeding;
- target_crop is therefore a locally verified face crop;
- both Replicate/InSwapper and PiAPI/Qubico can still reject that same verified crop
  with provider-side ``no face`` / target-index errors;
- retrying remote detectors adds several minutes without improving identity fidelity.

V289 makes the source-native facial core the *primary* identity transfer whenever
both source and target have strong local face evidence.  This is deterministic and
uses photo #3 pixels directly for the identity-critical facial interior.  It does
not invent landmarks, boxes, expressions or identity.  Remote providers remain a
fallback only when the local geometry gate cannot safely establish the transfer.

This is especially appropriate for the AI Selfie pipeline because the Gemini prompt
already constrains PERSON A to near-frontal/mild-three-quarter geometry compatible
with photo #3, and the final integration still uses the original Gemini head/hair,
body, lighting and scene outside the facial core.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v277_production_fidelity_patch as fidelity

VERSION = "v289-native-identity-primary-2026-08-16"
_INSTALLED = False
_ORIGINAL_IDENTITY_SWAP = terminal._identity_swap


def _face_info(raw: bytes) -> tuple[Any, tuple[int, int], float]:
    face = fs.source_face_crop(raw, None)
    w, h = fs.image(raw).size
    ratio = float(face.face_box[3]) / float(max(1, h))
    return face, (w, h), ratio


def _local_gate(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bool, str]:
    """Require unambiguous, sufficiently resolved local face evidence on both images."""
    try:
        target, tdims, tr = _face_info(target_crop)
        source, sdims, sr = _face_info(source_crop)
        tx, ty, tw, th = [int(v) for v in target.face_box]
        sx, sy, sw, sh = [int(v) for v in source.face_box]

        # Source must contain real detail. Target may be smaller because it is the
        # face-local crop cut from a full-resolution Gemini composition.
        source_ok = sw >= 300 and sh >= 300 and sr >= 0.24
        target_ok = tw >= 110 and th >= 110 and tr >= 0.22
        evidence_ok = (
            (int(getattr(source, "support", 0)) >= 2 or int(getattr(source, "eye_count", 0)) >= 1)
            and (int(getattr(target, "support", 0)) >= 2 or int(getattr(target, "eye_count", 0)) >= 1)
        )
        ok = bool(source_ok and target_ok and evidence_ok)
        reason = (
            f"target_face={target.face_box} target_dims={tdims} target_ratio={tr:.4f} "
            f"source_face={source.face_box} source_dims={sdims} source_ratio={sr:.4f} "
            f"source_ok={source_ok} target_ok={target_ok} evidence_ok={evidence_ok}"
        )
        log("AI_SELFIE_V289_GATE trace=%s status=%s %s", trace, "pass" if ok else "fallback", reason)
        return ok, reason
    except Exception as exc:
        reason = f"{type(exc).__name__}:{str(exc)[:400]}"
        log("AI_SELFIE_V289_GATE trace=%s status=fallback error=%s", trace, reason)
        return False, reason


def _geometry_ok(reference_raw: bytes, candidate_raw: bytes, log: Any, *, trace: str) -> bool:
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
        ok = center_delta <= 0.13 and 0.72 <= scale <= 1.38
        log(
            "AI_SELFIE_V289_GEOMETRY trace=%s status=%s center_delta=%.4f scale_ratio=%.4f ref_face=%s cand_face=%s",
            trace, "pass" if ok else "fallback", center_delta, scale, ref.face_box, cand.face_box,
        )
        return ok
    except Exception as exc:
        log("AI_SELFIE_V289_GEOMETRY trace=%s status=fallback error_type=%s error=%s",
            trace, type(exc).__name__, str(exc)[:400])
        return False


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    safe, _reason = _local_gate(target_crop, source_crop, log, trace=trace)
    if safe:
        try:
            candidate, meta = fidelity._source_native_face_core(source_crop, target_crop, log, trace=trace)
            if len(candidate) < 1024 or fs.sha(candidate) == fs.sha(target_crop):
                raise RuntimeError("source-native primary returned unchanged/empty target")
            if not _geometry_ok(target_crop, candidate, log, trace=trace):
                raise RuntimeError("source-native primary changed target face geometry beyond tolerance")
            log(
                "AI_SELFIE_V289_IDENTITY trace=%s stage=native_primary_success mode=%s target_dims=%s source_dims=%s out_dims=%s sha=%s remote_provider=false expression=photo3",
                trace, meta.get("mode"), fs.dims(target_crop), fs.dims(source_crop), fs.dims(candidate), fs.sha(candidate),
            )
            return candidate, "source_native_face_core_v289_primary"
        except Exception as exc:
            log(
                "AI_SELFIE_V289_IDENTITY trace=%s stage=native_primary_failed error_type=%s error=%s fallback=remote_stack",
                trace, type(exc).__name__, str(exc)[:700],
            )

    # Only now pay for/await remote provider detection. This preserves compatibility
    # for unusual head poses where the deterministic local geometry gate refuses.
    return await _ORIGINAL_IDENTITY_SWAP(target_crop, source_crop, log, trace=trace)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._identity_swap = _identity_swap
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V289"
    setattr(terminal, "_v289_native_identity_primary", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V289 native identity primary installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
