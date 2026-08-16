# -*- coding: utf-8 -*-
"""V286 production-safe identity transfer resilience for AI Selfie.

Fixes an important V285 geometry bug: the PiAPI padded retry returned the whole
padded canvas to the normal face-integration pipeline. The caller expects the
identity result to have the same geometry as ``target_crop``; therefore the padded
result was later resized into the original target box and could distort face scale,
features and expression.

V286 rules:
- padded provider retries are always cropped back to the exact original target
  geometry before any source-expression/core processing;
- returned identity images are geometry-validated against the original target;
- a raw source-native affine paste is NOT used as an automatic provider-free
  fallback because it can produce a plausible but wrong face. Production should
  fail cleanly rather than deliver the wrong identity;
- source-native expression/detail core remains allowed only on top of a successful
  remote face-swap baseline with verified geometry.
"""
from __future__ import annotations

import os
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v277_production_fidelity_patch as fidelity

VERSION = "v286-identity-geometry-safe-2026-08-16"
_INSTALLED = False
_ORIGINAL_IDENTITY_SWAP = terminal._identity_swap


def _padded_canvas(raw: bytes, *, factor: float = 1.42) -> tuple[bytes, tuple[int, int, int, int]]:
    """Add detector context while remembering the exact original-image rectangle."""
    from PIL import Image, ImageFilter

    img = fs.image(raw).convert("RGB")
    w, h = img.size
    nw = max(w + 64, int(round(w * factor)))
    nh = max(h + 64, int(round(h * factor)))
    resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    bg = img.resize((nw, nh), resampling)
    bg = bg.filter(ImageFilter.GaussianBlur(max(8.0, min(nw, nh) * 0.025)))
    canvas = bg.copy()
    x = (nw - w) // 2
    y = (nh - h) // 2
    canvas.paste(img, (x, y))
    return fs.jpeg(canvas, max_side=2200, quality=100), (x, y, x + w, y + h)


def _restore_original_geometry(provider_raw: bytes, box: tuple[int, int, int, int], original_dims: tuple[int, int]) -> bytes:
    """Remove V286 detector padding and return exactly the target-crop geometry."""
    from PIL import Image

    img = fs.image(provider_raw).convert("RGB")
    l, t, r, b = box
    # Provider output can be supersampled. Convert the remembered padded-canvas
    # coordinates into provider-output coordinates before removing padding.
    padded_w = max(1, r + l)
    padded_h = max(1, b + t)
    sx = img.width / float(padded_w)
    sy = img.height / float(padded_h)
    pl = max(0, min(img.width - 1, int(round(l * sx))))
    pt = max(0, min(img.height - 1, int(round(t * sy))))
    pr = max(pl + 1, min(img.width, int(round(r * sx))))
    pb = max(pt + 1, min(img.height, int(round(b * sy))))
    crop = img.crop((pl, pt, pr, pb))
    ow, oh = original_dims
    resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    if crop.size != (ow, oh):
        crop = crop.resize((ow, oh), resampling)
    return fs.jpeg(crop, max_side=max(ow, oh), quality=100)


def _local_face_summary(raw: bytes) -> str:
    try:
        target = fs.source_face_crop(raw, None)
        return f"face={target.face_box} crop={target.crop_box} dims={fs.dims(raw)}"
    except Exception as exc:
        return f"local_face_error={type(exc).__name__}:{str(exc)[:180]} dims={fs.dims(raw)}"


def _geometry_ok(reference_raw: bytes, candidate_raw: bytes, log: Any, *, trace: str, stage: str) -> bool:
    """Reject a returned face whose location/scale no longer matches target geometry."""
    try:
        ref = fs.source_face_crop(reference_raw, None)
        cand = fs.source_face_crop(candidate_raw, None)
        rw, rh = fs.image(reference_raw).size
        cw, ch = fs.image(candidate_raw).size
        rx, ry, rfw, rfh = [float(v) for v in ref.face_box]
        cx, cy, cfw, cfh = [float(v) for v in cand.face_box]
        r_center = ((rx + rfw / 2.0) / max(1.0, rw), (ry + rfh / 2.0) / max(1.0, rh))
        c_center = ((cx + cfw / 2.0) / max(1.0, cw), (cy + cfh / 2.0) / max(1.0, ch))
        center_delta = abs(r_center[0] - c_center[0]) + abs(r_center[1] - c_center[1])
        ref_ratio = rfh / max(1.0, rh)
        cand_ratio = cfh / max(1.0, ch)
        scale_ratio = cand_ratio / max(0.001, ref_ratio)
        ok = center_delta <= 0.16 and 0.68 <= scale_ratio <= 1.48
        log(
            "AI_SELFIE_V286_GEOMETRY trace=%s stage=%s status=%s center_delta=%.4f scale_ratio=%.4f ref_face=%s cand_face=%s ref_dims=%s cand_dims=%s",
            trace, stage, "pass" if ok else "reject", center_delta, scale_ratio,
            ref.face_box, cand.face_box, fs.dims(reference_raw), fs.dims(candidate_raw),
        )
        return ok
    except Exception as exc:
        log(
            "AI_SELFIE_V286_GEOMETRY trace=%s stage=%s status=validator_error error_type=%s error=%s",
            trace, stage, type(exc).__name__, str(exc)[:400],
        )
        return False


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    try:
        return await _ORIGINAL_IDENTITY_SWAP(target_crop, source_crop, log, trace=trace)
    except Exception as original_exc:
        message = str(original_exc)
        log(
            "AI_SELFIE_V286_IDENTITY trace=%s stage=primary_failed error_type=%s error=%s target=%s source=%s",
            trace, type(original_exc).__name__, message[:700], _local_face_summary(target_crop), _local_face_summary(source_crop),
        )

        if str(os.getenv("PIAPI_API_KEY") or "").strip():
            try:
                target_native_dims = fs.image(target_crop).size
                padded_target, target_box = _padded_canvas(target_crop, factor=1.42)
                padded_source, _source_box = _padded_canvas(source_crop, factor=1.42)
                provider_target = terminal._supersample(padded_target, min_long_side=1800)
                provider_source = terminal._supersample(padded_source, min_long_side=1800)
                log(
                    "AI_SELFIE_V286_IDENTITY trace=%s stage=piapi_padded_retry target_native=%s target_provider=%s source_native=%s source_provider=%s",
                    trace, fs.dims(padded_target), fs.dims(provider_target), fs.dims(padded_source), fs.dims(provider_source),
                )
                candidate_padded = await fs.piapi_swap_once(provider_target, provider_source, log, trace=trace)
                if len(candidate_padded) < 1024 or fs.sha(candidate_padded) == fs.sha(provider_target):
                    raise RuntimeError("PiAPI padded retry returned unchanged/empty target")

                candidate = _restore_original_geometry(candidate_padded, target_box, target_native_dims)
                log(
                    "AI_SELFIE_V286_IDENTITY trace=%s stage=piapi_unpadded restored_dims=%s sha=%s",
                    trace, fs.dims(candidate), fs.sha(candidate),
                )
                if not _geometry_ok(target_crop, candidate, log, trace=trace, stage="piapi_unpadded"):
                    raise RuntimeError("PiAPI padded retry changed target face geometry beyond production tolerance")

                # Preserve photo-3 expression only after a real provider has established
                # the correct target pose/identity geometry.
                try:
                    exact, meta = fidelity._source_native_face_core(source_crop, candidate, log, trace=trace)
                    if len(exact) >= 1024 and _geometry_ok(target_crop, exact, log, trace=trace, stage="source_core_after_piapi"):
                        log(
                            "AI_SELFIE_V286_IDENTITY trace=%s stage=piapi_padded_success source_core=true mode=%s dims=%s",
                            trace, meta.get("mode"), fs.dims(exact),
                        )
                        return exact, "piapi_qubico_padded_retry_unpadded+source_native_face_core"
                except Exception as core_exc:
                    log(
                        "AI_SELFIE_V286_IDENTITY trace=%s stage=source_core_after_piapi_failed error_type=%s error=%s",
                        trace, type(core_exc).__name__, str(core_exc)[:500],
                    )

                return candidate, "piapi_qubico_padded_retry_unpadded"
            except Exception as retry_exc:
                log(
                    "AI_SELFIE_V286_IDENTITY trace=%s stage=piapi_padded_failed error_type=%s error=%s",
                    trace, type(retry_exc).__name__, str(retry_exc)[:700],
                )

        # V285 used source-native affine mapping directly on the untouched Gemini
        # target when every provider failed. That can look superficially plausible but
        # it is not a production-safe identity transfer. Do not deliver such frames.
        log(
            "AI_SELFIE_V286_IDENTITY trace=%s stage=unsafe_emergency_blocked reason=provider_baseline_required original_error=%s",
            trace, message[:500],
        )
        raise original_exc


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._identity_swap = _identity_swap
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V286"
    setattr(terminal, "_v286_identity_geometry_safe", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V286 identity geometry-safe resilience installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
