# -*- coding: utf-8 -*-
"""V256 production terminal identity integration.

PiAPI/Qubico is the identity authority. Gemini remains responsible only for scene,
hero and user-body composition. The previous V254/V252 production hook applied a
conservative diff-mask against the original Gemini placeholder face before the
final oval composite; that could re-introduce Gemini facial geometry and make the
user look merely similar instead of actually face-swapped.

V256 removes that intermediate diff-mask from the production route. The central
face is taken directly from the two-pass PiAPI result and only the outer boundary
is feathered into the untouched Gemini composition. The isolated diagnostic keeps
its own V252 quality integration and is not changed by this module.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v234_terminal_user_transfer as terminal
from neyrobot_prod import selfie_v238_observable_double_transfer as active

VERSION = "v256-exact-piapi-identity-core-2026-08-08"
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    try:
        rendered = message % args if args else message
    except Exception:
        rendered = f"{message} {args!r}"
    print(f"[neyrobot-prod] {rendered}", flush=True)


def _exact_identity_composite(
    base_image: Any,
    target_crop_box: tuple[int, int, int, int],
    target_face: tuple[int, int, int, int],
    refined_crop_raw: bytes,
) -> bytes:
    """Insert the PiAPI result as the identity authority with edge-only blending.

    Important: the center of the face is 100% PiAPI. Only the perimeter is
    feathered so skin tone/light transition does not create a visible cut line.
    No comparison/diff against the Gemini placeholder face is performed.
    """
    from PIL import Image, ImageDraw, ImageFilter

    crop_left, crop_top, crop_right, crop_bottom = target_crop_box
    crop_w = crop_right - crop_left
    crop_h = crop_bottom - crop_top
    if crop_w <= 0 or crop_h <= 0:
        raise ValueError("invalid target crop box")

    refined_crop = terminal._image(refined_crop_raw).resize((crop_w, crop_h), Image.LANCZOS)
    original_crop = base_image.crop(target_crop_box)

    fx, fy, fw, fh = target_face
    local_face = (fx - crop_left, fy - crop_top, fw, fh)

    # Wider/taller than V255: preserve jaw, cheeks, temples and forehead from
    # PiAPI instead of leaking the Gemini placeholder back into the identity.
    face_region = terminal._expanded_box(
        local_face,
        (crop_w, crop_h),
        width_factor=1.82,
        height_factor=2.08,
        y_shift=0.015,
    )
    left, top, right, bottom = face_region
    region_w = right - left
    region_h = bottom - top
    if region_w <= 0 or region_h <= 0:
        raise ValueError("invalid face region")

    provider_region = refined_crop.crop(face_region)
    original_region = original_crop.crop(face_region)

    # Edge-only feathering. The broad inner ellipse is fully opaque, so the
    # actual eyes/nose/mouth/jaw remain the provider's result pixel-for-pixel.
    mask = Image.new("L", (region_w, region_h), 0)
    draw = ImageDraw.Draw(mask)
    mx = max(2, int(region_w * 0.025))
    my = max(2, int(region_h * 0.020))
    draw.ellipse((mx, my, region_w - mx, region_h - my), fill=255)
    blur = max(3, int(min(region_w, region_h) * 0.018))
    mask = mask.filter(ImageFilter.GaussianBlur(blur))

    merged_region = Image.composite(provider_region, original_region, mask)
    merged_crop = original_crop.copy()
    merged_crop.paste(merged_region, (left, top))

    output = base_image.copy()
    output.paste(merged_crop, (crop_left, crop_top))
    return terminal._jpeg(output, max_side=2048, quality=97)


def install() -> bool:
    global _INSTALLED

    current = getattr(active, "_composite_face_only", None)
    if not callable(current):
        return False
    if getattr(current, "_v256_exact_identity_owned", False):
        _INSTALLED = True
        return True

    setattr(_exact_identity_composite, "_v256_exact_identity_owned", True)
    setattr(_exact_identity_composite, "_v256_previous", current)
    active._composite_face_only = _exact_identity_composite

    _INSTALLED = True
    _log(
        "V256 production Face Swap installed version=%s mode=piapi_identity_authority edge_blend_only=true",
        VERSION,
    )
    return True


__all__ = ["VERSION", "install"]
