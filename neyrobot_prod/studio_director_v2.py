"""Deterministic storyboard contract for Studio Director v2.

Pure preprocessing only: no provider calls, no payments and no Telegram side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

_CAPTION = re.compile(r"^\s*(?:ТИТРЫ|ТИТР|CAPTIONS?)\s*:\s*(\d+)\s*[-–—]\s*(\d+)\s*\|\s*(.+)$", re.I)
_DURATION = re.compile(r"(\d+)\s*(?:секунд[а-я]*|сек\.?|seconds?|s)\b", re.I)


@dataclass(frozen=True)
class Caption:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Storyboard:
    duration: int
    aspect_ratio: str
    visual_prompt: str
    captions: tuple[Caption, ...]
    direction_notes: str


def prepare_storyboard(user_text: str, *, duration: int | None = None, aspect_ratio: str = "9:16") -> Storyboard:
    if aspect_ratio not in ("9:16", "16:9", "1:1"):
        raise ValueError("Unsupported aspect ratio")
    lines = str(user_text or "").splitlines()
    visual = []
    captions = []
    for line in lines:
        match = _CAPTION.match(line)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if start >= end:
                raise ValueError("Caption interval must have positive duration")
            captions.append(Caption(start, end, match.group(3).strip()))
        else:
            visual.append(line)
    if duration is None:
        found = _DURATION.search(user_text or "")
        if not found:
            raise ValueError("Explicit duration required")
        duration = int(found.group(1))
    if not 4 <= duration <= 120:
        raise ValueError("Unsupported storyboard duration")
    if any(c.end > duration for c in captions):
        raise ValueError("Caption exceeds requested duration")
    cleaned = "\n".join(visual).strip()
    if not cleaned:
        raise ValueError("Visual prompt is empty")
    notes = (
        "Direct the action in explicit time beats; specify motivated camera movement, "
        "lens/framing, subject motion, lighting transitions and a final hero composition. "
        "Keep the product fully visible inside the safe frame. "
        "No readable text, captions, logos or watermarks in generated frames. "
        "Use original characters and designs; do not imply a provider can bypass its content policy. "
        "Render captions only once during final compositing."
    )
    return Storyboard(duration, aspect_ratio, cleaned, tuple(captions), notes)
