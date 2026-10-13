"""Universal text placement policy for generated video scenes.

Separate diegetic (in-world) text from editorial overlays without imposing
brand-specific restrictions. Platform safe areas are configurable in post.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

TextMode = Literal["auto", "in_scene", "overlay", "none"]


@dataclass(frozen=True)
class TextPolicy:
    mode: TextMode = "auto"
    platform: str = "generic_vertical"
    preserve_requested_signage: bool = True

    def __post_init__(self):
        if self.mode not in ("auto", "in_scene", "overlay", "none"):
            raise ValueError("Unsupported text mode")


def composition_instructions(policy: TextPolicy) -> str:
    common = (
        "Compose for the requested aspect ratio with all important content "
        "comfortably inside frame bounds; avoid clipping, cropping, or placing "
        "critical text at the extreme edges. Preserve readability."
    )
    if policy.mode == "none":
        return common + " No visible text is requested."
    if policy.mode == "in_scene":
        return common + (
            " Render requested signs, product packaging, labels, and screen "
            "content naturally as part of the scene; preserve exact requested "
            "wording where possible."
        )
    if policy.mode == "overlay":
        return common + (
            " Keep suitable negative space for post-production titles and "
            "subtitles; editorial typography will be composited separately. "
            "Do not suppress explicitly requested physical signage."
        )
    return common + (
        " Preserve requested physical signage, labels, packaging, and on-screen "
        "interface text as scene content. Reserve legible negative space for "
        "editorial titles, pricing, subtitles, and calls to action that may be "
        "added as post-production overlays."
    )
