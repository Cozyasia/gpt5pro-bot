"""Suno -> Seedance singing clip: provider-neutral job plan.

No provider requests or Telegram handlers are registered here. The caller must
validate actual Comet API capabilities before enabling production execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Stage = Literal["lyrics", "suno", "photo", "seedance", "assemble", "complete"]

@dataclass(frozen=True)
class SingingClipJob:
    user_id: int
    prompt: str
    aspect_ratio: str = "9:16"
    segment_seconds: int = 15
    stage: Stage = "lyrics"
    suno_audio_url: str | None = None
    reference_image_url: str | None = None

    def __post_init__(self) -> None:
        if self.user_id <= 0 or not self.prompt.strip():
            raise ValueError("user_id and prompt are required")
        if self.aspect_ratio not in ("9:16", "16:9", "1:1"):
            raise ValueError("unsupported aspect ratio")
        if self.segment_seconds not in (5, 10, 15):
            raise ValueError("unsupported segment duration")

    def ready_for_video(self) -> bool:
        return bool(self.suno_audio_url and self.reference_image_url)

def seedance_reference_prompt(language: str = "Russian") -> str:
    return (
        "Use the supplied image as the singer identity reference and the supplied "
        "Suno audio excerpt as the timing reference. Photorealistic live singing "
        f"in {language}; natural mouth articulation, expressive face, subtle head "
        "movement and cinematic camera. Preserve identity. No subtitles, text, "
        "new lyrics or generated replacement vocals. Output silent video if "
        "supported; final assembly must use the original Suno audio."
    )

def segment_ranges(duration_seconds: float, segment_seconds: int = 15) -> list[tuple[float, float]]:
    if duration_seconds <= 0 or segment_seconds <= 0:
        raise ValueError("positive duration and segment length required")
    result = []
    start = 0.0
    while start < duration_seconds:
        end = min(duration_seconds, start + segment_seconds)
        result.append((round(start, 3), round(end, 3)))
        start = end
    return result
