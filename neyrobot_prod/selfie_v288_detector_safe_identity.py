# -*- coding: utf-8 -*-
"""V288 detector-safe identity transfer for production AI Selfie.

The V287 composition path can now reach identity transfer on the first Gemini
render, but PiAPI may reject the tight face crops with ``no face found``.  The
problem is geometric, not user-photo quality: V264 intentionally made source and
target crops face-centric for detail, while Qubico's detector is more reliable
when a complete head has generous surrounding context.

V288 therefore sends a detector-friendly *canvas* to PiAPI on the first provider
call.  The original high-quality crop is centered unchanged inside a larger
portrait canvas, making the face occupy roughly 22-32% of the provider image.
After face swap, the canvas is cropped back to the exact original target geometry
before normal integration.  No generative re-render and no random target box are
used.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal

VERSION = "v288-detector-safe-identity-2026-08-16"
_INSTALLED = False
_ORIGINAL_IDENTITY_SWAP = terminal._identity_swap


@dataclass(frozen=True)
class CanvasMeta:
    canvas_w: int
    canvas_h: int
    left: int
    top: int
    width: int
    height: int


def _detector_canvas(raw: bytes, *, factor: float = 2.45) -> tuple[bytes, CanvasMeta]:
    """Place the exact crop on a larger detector-friendly portrait canvas."""
    from PIL import Image, ImageFilter

    img = fs.image(raw).convert("RGB")
    w, h = img.size
    # Face-centric crops from V264/V287 are typically ~1.6x-1.9x face size. A 2.45x
    # canvas reduces the apparent face ratio to the range expected by common face
    # detectors without changing a single central identity pixel.
    nw = max(w + 160, int(round(w * factor)))
    nh = max(h + 180, int(round(h * factor)))

    # Build a natural low-frequency surround from the image itself. The untouched
    # crop is pasted back on top, so provider-visible identity pixels remain exact.
    resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    bg = img.resize((nw, nh), resampling)
    bg = bg.filter(ImageFilter.GaussianBlur(max(12.0, min(nw, nh) * 0.035)))
    canvas = bg.copy()
    left = (nw - w) // 2
    top = (nh - h) // 2
    canvas.paste(img, (left, top))

    # Keep the request bounded while retaining enough native detector pixels.
    out = fs.jpeg(canvas, max_side=2200, quality=100)
    # fs.jpeg may downscale a very large canvas, so metadata refers to the encoded
    # canvas geometry, not the pre-encode geometry.
    ew, eh = fs.image(out).size
    sx = ew / float(max(1, nw)); sy = eh / float(max(1, nh))
    meta = CanvasMeta(
        ew, eh,
        int(round(left * sx)), int(round(top * sy)),
        max(1, int(round(w * sx))), max(1, int(round(h * sy))),
    )
    return out, meta


def _crop_back(provider_raw: bytes, meta: CanvasMeta, target_dims: tuple[int, int]) -> bytes:
    """Restore provider output to the exact original target-crop geometry."""
    from PIL import Image

    img = fs.image(provider_raw).convert("RGB")
    sx = img.width / float(max(1, meta.canvas_w))
    sy = img.height / float(max(1, meta.canvas_h))
    left = int(round(meta.left * sx)); top = int(round(meta.top * sy))
    right = int(round((meta.left + meta.width) * sx))
    bottom = int(round((meta.top + meta.height) * sy))
    left = max(0, min(img.width - 2, left)); top = max(0, min(img.height - 2, top))
    right = max(left + 2, min(img.width, right)); bottom = max(top + 2, min(img.height, bottom))
    crop = img.crop((left, top, right, bottom))
    tw, th = target_dims
    resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    if crop.size != (tw, th):
        crop = crop.resize((tw, th), resampling)
    return fs.jpeg(crop, max_side=max(tw, th), quality=100)


def _face_ratio(raw: bytes) -> tuple[float, str]:
    try:
        detected = fs.source_face_crop(raw, None)
        _w, h = fs.image(raw).size
        return detected.face_box[3] / float(max(1, h)), str(detected.face_box)
    except Exception as exc:
        return 0.0, f"detect_error={type(exc).__name__}:{str(exc)[:120]}"


def _geometry_ok(reference_raw: bytes, candidate_raw: bytes, log: Any, *, trace: str) -> bool:
    """Require the swapped face to stay in approximately the original location/scale."""
    try:
        ref = fs.source_face_crop(reference_raw, None)
        cand = fs.source_face_crop(candidate_raw, None)
        rw, rh = fs.image(reference_raw).size
        cw, ch = fs.image(candidate_raw).size
        rx, ry, rfw, rfh = [float(v) for v in ref.face_box]
        cx, cy, cfw, cfh = [float(v) for v in cand.face_box]
        rcx = (rx + rfw / 2.0) / max(1.0, rw); rcy = (ry + rfh / 2.0) / max(1.0, rh)
        ccx = (cx + cfw / 2.0) / max(1.0, cw); ccy = (cy + cfh / 2.0) / max(1.0, ch)
        center_delta = abs(rcx - ccx) + abs(rcy - ccy)
        scale_ratio = (cfh / max(1.0, ch)) / max(0.001, rfh / max(1.0, rh))
        ok = center_delta <= 0.18 and 0.62 <= scale_ratio <= 1.58
        log("AI_SELFIE_V288_GEOMETRY trace=%s status=%s center_delta=%.4f scale_ratio=%.4f ref=%s cand=%s",
            trace, "pass" if ok else "reject", center_delta, scale_ratio, ref.face_box, cand.face_box)
        return ok
    except Exception as exc:
        log("AI_SELFIE_V288_GEOMETRY trace=%s status=validator_error error_type=%s error=%s",
            trace, type(exc).__name__, str(exc)[:300])
        return False


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    """Use detector-safe PiAPI geometry first; retain previous stack as fallback."""
    piapi = str(os.getenv("PIAPI_API_KEY") or "").strip()
    replicate = str(os.getenv("REPLICATE_API_TOKEN") or "").strip()

    # If Replicate is configured, retain the existing InSwapper-first production
    # route. V288 specifically fixes the PiAPI/Qubico no-face path seen in production.
    if replicate:
        try:
            return await _ORIGINAL_IDENTITY_SWAP(target_crop, source_crop, log, trace=trace)
        except Exception as exc:
            log("AI_SELFIE_V288_IDENTITY trace=%s stage=existing_stack_failed error_type=%s error=%s",
                trace, type(exc).__name__, str(exc)[:500])
            if not piapi:
                raise

    if piapi:
        target_dims = fs.image(target_crop).size
        target_canvas, target_meta = _detector_canvas(target_crop, factor=2.45)
        source_canvas, _source_meta = _detector_canvas(source_crop, factor=2.45)
        tr, tface = _face_ratio(target_canvas)
        sr, sface = _face_ratio(source_canvas)
        log(
            "AI_SELFIE_V288_IDENTITY trace=%s stage=detector_canvas target_native=%s target_canvas=%s target_face_ratio=%.4f target_face=%s source_native=%s source_canvas=%s source_face_ratio=%.4f source_face=%s",
            trace, fs.dims(target_crop), fs.dims(target_canvas), tr, tface,
            fs.dims(source_crop), fs.dims(source_canvas), sr, sface,
        )
        try:
            # Do not re-crop before the provider. The canvas itself is the detector
            # normalization and already contains the original high-quality pixels.
            candidate_canvas = await fs.piapi_swap_once(target_canvas, source_canvas, log, trace=trace)
            if len(candidate_canvas) < 1024 or fs.sha(candidate_canvas) == fs.sha(target_canvas):
                raise RuntimeError("PiAPI detector-safe call returned unchanged/empty target")
            candidate = _crop_back(candidate_canvas, target_meta, target_dims)
            if not _geometry_ok(target_crop, candidate, log, trace=trace):
                raise RuntimeError("PiAPI detector-safe result changed face geometry beyond tolerance")
            log("AI_SELFIE_V288_IDENTITY trace=%s stage=detector_safe_success dims=%s sha=%s",
                trace, fs.dims(candidate), fs.sha(candidate))
            return candidate, "piapi_qubico_detector_safe_canvas_v288"
        except Exception as exc:
            log("AI_SELFIE_V288_IDENTITY trace=%s stage=detector_safe_failed error_type=%s error=%s",
                trace, type(exc).__name__, str(exc)[:700])
            # Keep the older stack as a final fallback for transient provider behavior.
            return await _ORIGINAL_IDENTITY_SWAP(target_crop, source_crop, log, trace=trace)

    return await _ORIGINAL_IDENTITY_SWAP(target_crop, source_crop, log, trace=trace)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._identity_swap = _identity_swap
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V288"
    setattr(terminal, "_v288_detector_safe_identity", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V288 detector-safe identity installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
