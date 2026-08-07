# -*- coding: utf-8 -*-
"""Promote the approved V252 Face Swap quality layer to production AI Selfie.

The production selfie route already isolates PERSON A into a one-face crop, sends
that crop to PiAPI/Qubico, then composites it back into the untouched Gemini scene.
This patch keeps that architecture and changes only the crop integration step:

original target crop + raw PiAPI crop -> V252 diff-mask quality integration ->
existing feathered crop return to the original scene.

No extra model call is added. Gemini is never called after Face Swap. The hero,
body, background and scene remain owned by the original composition.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v234_terminal_user_transfer as terminal
from neyrobot_prod import selfie_v252_faceswap_quality as quality

VERSION = "v253-production-photorealistic-terminal-face-integration-2026-08-08"
_INSTALLED = False


def install() -> bool:
    global _INSTALLED
    current = getattr(terminal, "_composite_crop", None)
    if not callable(current):
        return False
    if getattr(current, "_v253_quality_owned", False):
        _INSTALLED = True
        return True

    original = current

    def composite_with_quality(base_image: Any, crop_box: tuple[int, int, int, int], swapped_raw: bytes) -> bytes:
        left, top, right, bottom = crop_box
        target_crop = base_image.crop((left, top, right, bottom))
        target_raw = terminal._jpeg(target_crop, max_side=1900, quality=96)
        polished, stats = quality.integrate_faceswap(target_raw, swapped_raw, _log)
        _log(
            "AI_SELFIE_V253_QUALITY applied=%s changed_ratio=%.4f bbox=%s threshold=%.2f reason=%s",
            stats.applied, stats.changed_ratio, stats.bbox, stats.threshold, stats.reason,
        )
        return original(base_image, crop_box, polished)

    setattr(composite_with_quality, "_v253_quality_owned", True)
    setattr(composite_with_quality, "_v253_original", original)
    terminal._composite_crop = composite_with_quality
    _INSTALLED = True
    print(f"[neyrobot-prod] V253 production Face Swap quality installed version={VERSION}", flush=True)
    return True


def _log(message: str, *args: Any) -> None:
    try:
        rendered = message % args if args else message
    except Exception:
        rendered = f"{message} {args!r}"
    print(f"[neyrobot-prod] {rendered}", flush=True)


__all__ = ["VERSION", "install"]
