# -*- coding: utf-8 -*-
"""Apply the approved V252 Face Swap quality layer to the active production AI Selfie route.

The guaranteed runtime owner routes production generation through V238, not through
V237.generate. V238 performs two isolated face-swap passes and finishes via its own
``_composite_face_only`` helper. Therefore the quality patch must own that helper
rather than V237._composite_crop.

No extra model call is introduced. The provider result is integrated locally into
the untouched Gemini composition using V252's conservative diff-mask blend.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v234_terminal_user_transfer as terminal
from neyrobot_prod import selfie_v238_observable_double_transfer as active
from neyrobot_prod import selfie_v252_faceswap_quality as quality

VERSION = "v254-production-v238-photorealistic-face-integration-2026-08-08"
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    try:
        rendered = message % args if args else message
    except Exception:
        rendered = f"{message} {args!r}"
    print(f"[neyrobot-prod] {rendered}", flush=True)


def install() -> bool:
    global _INSTALLED

    # Patch the actual V238 final composition hook used by the guaranteed runtime owner.
    current = getattr(active, "_composite_face_only", None)
    if not callable(current):
        return False
    if getattr(current, "_v254_quality_owned", False):
        _INSTALLED = True
        return True

    original = current

    def composite_face_only_with_quality(
        base_image: Any,
        target_crop_box: tuple[int, int, int, int],
        target_face: tuple[int, int, int, int],
        refined_crop_raw: bytes,
    ) -> bytes:
        left, top, right, bottom = target_crop_box
        original_crop = base_image.crop((left, top, right, bottom))
        target_raw = terminal._jpeg(original_crop, max_side=1900, quality=96)

        polished, stats = quality.integrate_faceswap(target_raw, refined_crop_raw, _log)
        _log(
            "AI_SELFIE_V254_QUALITY route=v238 applied=%s changed_ratio=%.4f bbox=%s threshold=%.2f reason=%s",
            stats.applied, stats.changed_ratio, stats.bbox, stats.threshold, stats.reason,
        )
        return original(base_image, target_crop_box, target_face, polished)

    setattr(composite_face_only_with_quality, "_v254_quality_owned", True)
    setattr(composite_face_only_with_quality, "_v254_original", original)
    active._composite_face_only = composite_face_only_with_quality

    # Keep V237's older composition hook patched as a compatibility path for any
    # retained callback that still calls it directly.
    old = getattr(terminal, "_composite_crop", None)
    if callable(old) and not getattr(old, "_v254_quality_owned", False):
        old_original = old

        def composite_crop_with_quality(base_image: Any, crop_box: tuple[int, int, int, int], swapped_raw: bytes) -> bytes:
            left, top, right, bottom = crop_box
            target_crop = base_image.crop((left, top, right, bottom))
            target_raw = terminal._jpeg(target_crop, max_side=1900, quality=96)
            polished, stats = quality.integrate_faceswap(target_raw, swapped_raw, _log)
            _log(
                "AI_SELFIE_V254_QUALITY route=v237 applied=%s changed_ratio=%.4f bbox=%s threshold=%.2f reason=%s",
                stats.applied, stats.changed_ratio, stats.bbox, stats.threshold, stats.reason,
            )
            return old_original(base_image, crop_box, polished)

        setattr(composite_crop_with_quality, "_v254_quality_owned", True)
        setattr(composite_crop_with_quality, "_v254_original", old_original)
        terminal._composite_crop = composite_crop_with_quality

    _INSTALLED = True
    print(f"[neyrobot-prod] V254 production Face Swap quality installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
