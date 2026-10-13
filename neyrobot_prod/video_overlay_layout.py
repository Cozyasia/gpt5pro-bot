"""Platform-aware editorial text layout for vertical video.

This module does not censor or remove in-scene signs. It only places editorial
overlays and subtitles inside a configurable safe rectangle.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class SafeArea:
    left: float = 0.08
    top: float = 0.13
    right: float = 0.12
    bottom: float = 0.23

    def __post_init__(self):
        if any(not 0 <= x < 0.5 for x in (self.left, self.top, self.right, self.bottom)):
            raise ValueError("Margins must be fractions between 0 and 0.5")
        if self.left + self.right >= 1 or self.top + self.bottom >= 1:
            raise ValueError("Margins leave no visible area")


@dataclass(frozen=True)
class TextBox:
    x: int
    y: int
    width: int
    height: int
    text: str
    role: str


def safe_rectangle(width: int, height: int, margins: SafeArea = SafeArea()) -> tuple[int, int, int, int]:
    if width <= 0 or height <= 0:
        raise ValueError("Invalid video dimensions")
    x = round(width * margins.left)
    y = round(height * margins.top)
    right = round(width * (1 - margins.right))
    bottom = round(height * (1 - margins.bottom))
    return x, y, right - x, bottom - y


def layout_editorial_text(
    title: str,
    subtitle: str,
    *,
    width: int = 720,
    height: int = 1280,
    margins: SafeArea = SafeArea(),
) -> list[TextBox]:
    """Return candidate rectangles; renderer must measure glyphs and wrap text.

    A blank string is omitted. Real scene content is unaffected. This is not a
    guarantee of non-overlap with moving objects; a vision pass is still needed.
    """
    x, y, w, h = safe_rectangle(width, height, margins)
    boxes: list[TextBox] = []
    if title.strip():
        boxes.append(TextBox(x, y, w, max(1, round(h * 0.22)), title.strip(), "title"))
    if subtitle.strip():
        sh = max(1, round(h * 0.18))
        boxes.append(TextBox(x, y + h - sh, w, sh, subtitle.strip(), "subtitle"))
    return boxes
