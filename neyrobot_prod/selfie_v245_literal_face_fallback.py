# -*- coding: utf-8 -*-
"""V254 deterministic literal photo-3 fallback.

PiAPI remains the preferred terminal face-swap provider. If its Qubico worker
fails, this module performs a local pixel transfer from photo #3 onto the already
isolated one-face target crop. The fallback must never fail merely because Haar/
OpenCV misses a face that is visibly present in an isolated portrait crop.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

VERSION = "v254-literal-photo3-fallback-detector-safe-2026-08-08"
_WRAPPER: Any | None = None
_UPSTREAM: Any | None = None


def _central_face_box(image: Any) -> tuple[int, int, int, int]:
    """Conservative deterministic face box for an already isolated portrait crop."""
    width, height = image.size
    face_w = max(72, int(width * 0.42))
    face_h = max(84, int(face_w * 1.12))
    face_w = min(face_w, width)
    face_h = min(face_h, height)
    cx = width // 2
    cy = int(height * 0.40)
    x = max(0, min(width - face_w, cx - face_w // 2))
    y = max(0, min(height - face_h, cy - face_h // 2))
    return int(x), int(y), int(face_w), int(face_h)


def _largest_face(image: Any, *, role: str, log: Any) -> tuple[int, int, int, int]:
    from neyrobot_prod import selfie_v234_terminal_user_transfer as v237

    faces = list(v237._detect_faces(image) or [])
    if faces:
        box = max(faces, key=lambda item: item[2] * item[3])
        log("AI_SELFIE_V254_LITERAL_FACE role=%s detector=opencv box=%s image=%s", role, box, image.size)
        return box

    # Both inputs to this fallback are already one-person crops. A missed Haar box
    # is therefore not evidence that no face exists; use a bounded central box.
    box = _central_face_box(image)
    log("AI_SELFIE_V254_LITERAL_FACE role=%s detector=deterministic_isolated_crop box=%s image=%s", role, box, image.size)
    return box


def _expand(box: tuple[int, int, int, int], size: tuple[int, int], wf: float, hf: float) -> tuple[int, int, int, int]:
    from neyrobot_prod import selfie_v234_terminal_user_transfer as v237

    return v237._expanded_box(box, size, width_factor=wf, height_factor=hf, y_shift=-0.02)


def literal_face_transfer(target_crop: bytes, face_source: bytes, log: Any) -> bytes:
    """Transfer actual pixels from source face into the isolated target crop."""
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    target = ImageOps.exif_transpose(Image.open(BytesIO(target_crop))).convert("RGB")
    source = ImageOps.exif_transpose(Image.open(BytesIO(face_source))).convert("RGB")

    sf = _largest_face(source, role="source", log=log)
    tf = _largest_face(target, role="target", log=log)
    sbox = _expand(sf, source.size, 1.55, 1.82)
    tbox = _expand(tf, target.size, 1.48, 1.74)

    sl, st, sr, sb = sbox
    tl, tt, tr, tb = tbox
    tw, th = tr - tl, tb - tt
    if tw < 64 or th < 64:
        raise ValueError("literal fallback target region is too small")

    patch = source.crop((sl, st, sr, sb)).resize((tw, th), Image.LANCZOS)
    target_region = target.crop((tl, tt, tr, tb))

    src_arr = cv2.cvtColor(np.asarray(patch), cv2.COLOR_RGB2LAB).astype(np.float32)
    dst_arr = cv2.cvtColor(np.asarray(target_region), cv2.COLOR_RGB2LAB).astype(np.float32)
    for channel in range(3):
        sm, ss = float(src_arr[..., channel].mean()), float(src_arr[..., channel].std())
        dm, ds = float(dst_arr[..., channel].mean()), float(dst_arr[..., channel].std())
        src_arr[..., channel] = (src_arr[..., channel] - sm) * (ds / max(ss, 1.0)) + dm
    src_arr = np.clip(src_arr, 0, 255).astype(np.uint8)
    patch = Image.fromarray(cv2.cvtColor(src_arr, cv2.COLOR_LAB2RGB))

    mask = Image.new("L", (tw, th), 0)
    draw = ImageDraw.Draw(mask)
    mx = max(3, int(tw * 0.10))
    my = max(3, int(th * 0.055))
    draw.ellipse((mx, my, tw - mx, th - my), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(6, int(min(tw, th) * 0.055))))

    merged = Image.composite(patch, target_region, mask)
    output = target.copy()
    output.paste(merged, (tl, tt))
    out = BytesIO()
    output.save(out, "JPEG", quality=96, optimize=True, progressive=False)
    result = out.getvalue()
    log(
        "AI_SELFIE_V254_LOCAL_LITERAL_OK source_face=%s target_face=%s source_box=%s target_box=%s bytes=%s",
        sf, tf, sbox, tbox, len(result),
    )
    return result


def install() -> bool:
    """Bind once, and only repair the binding if another patch actually replaced it."""
    global _WRAPPER, _UPSTREAM
    from neyrobot_prod import selfie_v234_terminal_user_transfer as v237
    from neyrobot_prod import selfie_v243_resilient_piapi_transport as v243

    current = getattr(v237, "_piapi_single_face_swap", None)
    if getattr(current, "_v254_literal_wrapper", False):
        return True

    if _WRAPPER is not None and getattr(_WRAPPER, "_v254_literal_wrapper", False):
        v237._piapi_single_face_swap = _WRAPPER
        v237.VERSION = VERSION
        return True

    v243.install()
    upstream = v243.resilient_piapi_single_face_swap
    _UPSTREAM = upstream

    async def guarded(target_crop: bytes, face_source: bytes, log: Any) -> bytes:
        try:
            return await upstream(target_crop, face_source, log)
        except Exception as exc:
            original_error = f"{type(exc).__name__}: {str(exc)[:1200]}"
            log("AI_SELFIE_V254_PIAPI_FAILED_LOCAL_LITERAL_FALLBACK error=%s", original_error)
            try:
                return literal_face_transfer(target_crop, face_source, log)
            except Exception as fallback_exc:
                log(
                    "AI_SELFIE_V254_LITERAL_FALLBACK_FAILED original=%s fallback=%s: %s",
                    original_error, type(fallback_exc).__name__, str(fallback_exc)[:900],
                )
                raise RuntimeError(
                    f"PiAPI failed ({original_error}); local fallback also failed: "
                    f"{type(fallback_exc).__name__}: {str(fallback_exc)[:500]}"
                ) from fallback_exc

    guarded._v254_literal_wrapper = True  # type: ignore[attr-defined]
    guarded._v254_upstream = upstream  # type: ignore[attr-defined]
    _WRAPPER = guarded
    v237._piapi_single_face_swap = guarded
    v237.VERSION = VERSION
    print(f"[neyrobot-prod] V254 literal photo-3 fallback bound version={VERSION}", flush=True)
    return True


install()

__all__ = ["VERSION", "install", "literal_face_transfer"]
