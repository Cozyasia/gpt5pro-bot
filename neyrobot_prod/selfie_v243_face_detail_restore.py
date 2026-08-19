# -*- coding: utf-8 -*-
"""V243 source-guided detail restoration for the proven V242 selfie route.

This is deliberately a narrow quality overlay:
- V242 remains responsible for scene, true front-camera framing and expression lock;
- V241/V236 remain responsible for isolated real FaceSwap and native 2K merge;
- photo #3 remains the only user identity/expression authority;
- only PERSON A's swapped face receives source-guided high-frequency detail;
- PERSON B and the rest of the Gemini scene remain pixel-locked.

The goal is to remove the visibly soft/pixelated FaceSwap look without asking a
second generative model to redraw the user's face (which previously changed lips,
expression and identity). We therefore inject only high-frequency information
from the authoritative source face and never replace low-frequency facial shape.
"""
from __future__ import annotations

import contextvars
import io
from typing import Any

from neyrobot_prod import selfie_v241_authoritative_runtime as v241
from neyrobot_prod import selfie_v242_expression_lock as v242

VERSION = "v243-source-guided-face-detail-2026-08-19"

_ORIGINAL_V242_ENFORCE = v242.enforce_runtime
_INSTALLED = False
_SOURCE_FACE: contextvars.ContextVar[bytes | None] = contextvars.ContextVar(
    "v243_authoritative_source_face", default=None
)


def _log(message: str, *args: Any) -> None:
    v241._log(message, *args)


def _select_source_photo(runtime: Any, photos: list[bytes]):
    """Keep V241/V242 deterministic photo #3 selection and remember it per task."""
    selected = v241._select_source_photo(runtime, photos)
    raw = bytes(selected[0] or b"")
    _SOURCE_FACE.set(raw if raw else None)
    _log("AI_SELFIE_V243_SOURCE_CACHE source_photo=%s bytes=%s task_local=true", selected[1], len(raw))
    return selected


def _single_face_box(image: bytes):
    runtime = v241._runtime()
    faces = v241._detect(runtime, bytes(image)) if runtime is not None else []
    if not faces:
        return None
    # For both the source and the isolated PERSON-A crop the largest detected face
    # is the intended face. The crop never contains PERSON B by construction.
    f = max(faces, key=lambda x: int(x.get("w", 0)) * int(x.get("h", 0)))
    x = int(f.get("x", 0)); y = int(f.get("y", 0))
    w = int(f.get("w", 0)); h = int(f.get("h", 0))
    if w < 48 or h < 48:
        return None
    return x, y, w, h


def _expanded_box(box, width: int, height: int, xpad: float = 0.16, ypad_top: float = 0.22, ypad_bottom: float = 0.18):
    x, y, w, h = box
    x0 = max(0, int(round(x - w * xpad)))
    x1 = min(width, int(round(x + w * (1.0 + xpad))))
    y0 = max(0, int(round(y - h * ypad_top)))
    y1 = min(height, int(round(y + h * (1.0 + ypad_bottom))))
    return x0, y0, x1, y1


def _source_guided_detail(swapped_crop: bytes, source: bytes) -> bytes:
    """Restore local facial detail without changing expression/geometry.

    We resize the source face crop onto the already-swapped face only to extract
    high-frequency residuals. The target FaceSwap image supplies all low-frequency
    shape, pose, lighting and expression. An elliptical feather mask keeps the
    operation inside the face and prevents seams/hair/background contamination.
    """
    from PIL import Image, ImageFilter, ImageDraw
    import numpy as np

    target_bytes = bytes(swapped_crop or b"")
    source_bytes = bytes(source or b"")
    if len(target_bytes) < 1024 or len(source_bytes) < 1024:
        return target_bytes

    tbox = _single_face_box(target_bytes)
    sbox = _single_face_box(source_bytes)
    if tbox is None or sbox is None:
        _log("AI_SELFIE_V243_DETAIL status=skip reason=face_detection target=%s source=%s", bool(tbox), bool(sbox))
        return target_bytes

    tim = Image.open(io.BytesIO(target_bytes)).convert("RGB")
    sim = Image.open(io.BytesIO(source_bytes)).convert("RGB")
    tx0, ty0, tx1, ty1 = _expanded_box(tbox, tim.width, tim.height)
    sx0, sy0, sx1, sy1 = _expanded_box(sbox, sim.width, sim.height)
    tw, th = tx1 - tx0, ty1 - ty0
    if tw < 96 or th < 96:
        return target_bytes

    target_face = tim.crop((tx0, ty0, tx1, ty1))
    source_face = sim.crop((sx0, sy0, sx1, sy1)).resize((tw, th), Image.Resampling.LANCZOS)

    # Source contributes DETAIL ONLY. Removing a Gaussian low-frequency layer
    # prevents the source crop from overwriting target face shape, pose or tone.
    source_blur = source_face.filter(ImageFilter.GaussianBlur(radius=max(1.0, min(tw, th) / 260.0)))
    src = np.asarray(source_face, dtype=np.float32)
    low = np.asarray(source_blur, dtype=np.float32)
    tgt = np.asarray(target_face, dtype=np.float32)
    high = src - low

    # Conservative gain: enough to restore eyelashes/lips/skin/hair micro-edges,
    # but not enough to create double contours when alignment differs by a few px.
    detail_gain = 0.52
    restored = np.clip(tgt + high * detail_gain, 0, 255).astype(np.uint8)
    restored_im = Image.fromarray(restored, mode="RGB")
    restored_im = restored_im.filter(ImageFilter.UnsharpMask(radius=0.55, percent=48, threshold=3))

    mask = Image.new("L", (tw, th), 0)
    draw = ImageDraw.Draw(mask)
    # Keep strongest effect in eyes/nose/mouth/cheeks and taper before crop edges.
    inset_x = max(6, int(tw * 0.08))
    inset_y = max(6, int(th * 0.06))
    draw.ellipse((inset_x, inset_y, tw - inset_x, th - inset_y), fill=232)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(8.0, min(tw, th) * 0.055)))
    target_face.paste(restored_im, (0, 0), mask)
    tim.paste(target_face, (tx0, ty0))

    out = io.BytesIO()
    tim.save(out, format="JPEG", quality=100, subsampling=0, optimize=True)
    encoded = out.getvalue()
    _log(
        "AI_SELFIE_V243_DETAIL status=applied target_face=%sx%s source_face=%sx%s gain=%.2f jpeg=100 subsampling=0 bytes=%s",
        tw, th, sx1 - sx0, sy1 - sy0, detail_gain, len(encoded),
    )
    return encoded


def _merge_face_roi(base: bytes, swapped_crop: bytes, box):
    """Enhance PERSON A crop first, then use the proven V241 native-resolution merge."""
    source = _SOURCE_FACE.get()
    enhanced = bytes(swapped_crop or b"")
    if source:
        try:
            enhanced = _source_guided_detail(enhanced, source)
        except Exception as exc:
            _log("AI_SELFIE_V243_DETAIL status=failed_safe error=%s:%s", type(exc).__name__, exc)
            enhanced = bytes(swapped_crop or b"")
    else:
        _log("AI_SELFIE_V243_DETAIL status=skip reason=no_task_local_source")

    # V241 merge preserves the 1856x2304 Gemini scene and never touches PERSON B.
    return v241._merge_face_roi(base, enhanced, box)


def enforce_runtime() -> None:
    """Restore the proven V242 route, then patch only PERSON-A detail handling."""
    from neyrobot_prod import selfie_v219_triref_scene_owner as ui
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    # Preserve every V242 behavioral decision first.
    v242.VERSION = VERSION
    _ORIGINAL_V242_ENFORCE()

    # Narrow quality-only changes.
    transfer._select_source_photo = _select_source_photo
    transfer._merge_left_crop = _merge_face_roi

    transfer.VERSION = VERSION
    google.VERSION = VERSION
    ui.VERSION = VERSION
    v241.VERSION = VERSION
    v242.VERSION = VERSION

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v243-v242-expression-lock-source-guided-detail-native2k-real-faceswap"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini V242 expression lock -> compact isolated Segmind/PiAPI real FaceSwap -> "
            "source-guided PERSON-A high-frequency detail restore -> native 2K merge"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V243_ENFORCE status=ok base=v242 expression_lock=preserved faceswap=real detail=source_high_frequency hero=pixel_locked native2k=true version=%s",
        VERSION,
    )


def install() -> None:
    global _INSTALLED

    # V241 guarded generation calls this module symbol on every generation.
    # Point it at V243 so no late legacy/V241/V242 reassertion can remove detail restore.
    v241.enforce_runtime = enforce_runtime
    v242.enforce_runtime = enforce_runtime
    v241.VERSION = VERSION
    v242.VERSION = VERSION

    # V242 initializes V241's real base generator and all proven plumbing.
    v242.install()
    enforce_runtime()

    if not _INSTALLED:
        _INSTALLED = True
        print("[neyrobot-prod] V243 source-guided PERSON-A face detail restore installed over V242", flush=True)


__all__ = ["VERSION", "install", "enforce_runtime"]
