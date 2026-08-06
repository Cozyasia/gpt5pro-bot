# -*- coding: utf-8 -*-
"""V245 deterministic literal photo-3 fallback.

PiAPI remains the preferred terminal face-swap provider. If its Qubico worker
returns 5xx/failed after bounded retries, this module performs a local pixel
transfer from photo #3 onto the isolated generated user crop. No Gemini identity
regeneration is used in the fallback.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

VERSION = "v245-literal-photo3-fallback-2026-08-06"
_WRAPPER: Any | None = None
_UPSTREAM: Any | None = None


def _largest_face(image: Any) -> tuple[int, int, int, int]:
    from neyrobot_prod import selfie_v234_terminal_user_transfer as v237

    faces = v237._detect_faces(image)
    if not faces:
        raise ValueError("literal fallback could not detect a face")
    return max(faces, key=lambda item: item[2] * item[3])


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

    sf = _largest_face(source)
    tf = _largest_face(target)
    sbox = _expand(sf, source.size, 1.55, 1.82)
    tbox = _expand(tf, target.size, 1.48, 1.74)

    sl, st, sr, sb = sbox
    tl, tt, tr, tb = tbox
    tw, th = tr - tl, tb - tt
    patch = source.crop((sl, st, sr, sb)).resize((tw, th), Image.LANCZOS)
    target_region = target.crop((tl, tt, tr, tb))

    # Match only coarse luminance/chroma statistics. Facial geometry and texture
    # remain the real pixels from photo #3.
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
        "AI_SELFIE_V245_LOCAL_LITERAL_OK source_face=%s target_face=%s source_box=%s target_box=%s bytes=%s",
        sf, tf, sbox, tbox, len(result),
    )
    return result


def install() -> bool:
    global _WRAPPER, _UPSTREAM
    from neyrobot_prod import selfie_v234_terminal_user_transfer as v237
    from neyrobot_prod import selfie_v243_resilient_piapi_transport as v243

    v243.install()
    upstream = v237._piapi_single_face_swap
    if getattr(upstream, "_v245_literal_wrapper", False):
        return True
    _UPSTREAM = upstream

    async def guarded(target_crop: bytes, face_source: bytes, log: Any) -> bytes:
        try:
            return await upstream(target_crop, face_source, log)
        except Exception as exc:
            log(
                "AI_SELFIE_V245_PIAPI_FAILED_LOCAL_LITERAL_FALLBACK error_type=%s error=%s",
                type(exc).__name__, str(exc)[:900],
            )
            return literal_face_transfer(target_crop, face_source, log)

    guarded._v245_literal_wrapper = True  # type: ignore[attr-defined]
    guarded._v245_upstream = upstream  # type: ignore[attr-defined]
    _WRAPPER = guarded
    v237._piapi_single_face_swap = guarded
    v237.VERSION = VERSION
    print(f"[neyrobot-prod] V245 literal photo-3 fallback bound version={VERSION}", flush=True)
    return True


install()

__all__ = ["VERSION", "install", "literal_face_transfer"]
