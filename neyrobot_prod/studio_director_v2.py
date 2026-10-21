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


def director_llm_instructions(storyboard: Storyboard) -> str:
    """Instructions for an existing LLM integration; never send caption text to video generation."""
    return (
        "You are a commercial film director and cinematographer. "
        "Return ONLY valid JSON with keys: scenes, visual_continuity, editorial_notes. "
        "Each scene must have integer start_second and end_second, and strings "
        "action, camera_movement, framing, lighting, visual, transition. "
        "Cover the entire timeline without overlaps or gaps; scene duration must be "
        "supported by the chosen video provider. Do not invent a model capability. "
        "Describe visible physical action and motivated camera movement, not vague mood. "
        "Maintain identity and continuity between scenes. "
        "No captions, written words, labels, watermarks, brands or typography in any visual field. "
        "Do not modify the requested duration or aspect ratio. "
        f"Duration: {storyboard.duration} seconds. Aspect ratio: {storyboard.aspect_ratio}. "
        f"Director constraints: {storyboard.direction_notes} "
        f"Visual brief: {storyboard.visual_prompt}"
    )


def validate_director_plan(plan: dict, storyboard: Storyboard) -> tuple[dict, ...]:
    """Reject incomplete, discontinuous or text-contaminated LLM plans before any paid call."""
    if not isinstance(plan, dict) or not isinstance(plan.get("scenes"), list) or not plan["scenes"]:
        raise ValueError("Director plan requires nonempty scenes")
    cursor = 0
    required = ("action", "camera_movement", "framing", "lighting", "visual", "transition")
    output = []
    for scene in plan["scenes"]:
        if not isinstance(scene, dict):
            raise ValueError("Invalid scene object")
        start, end = scene.get("start_second"), scene.get("end_second")
        if type(start) is not int or type(end) is not int or start != cursor or end <= start:
            raise ValueError("Director scene timeline has gaps, overlaps or invalid durations")
        if end > storyboard.duration:
            raise ValueError("Director scene exceeds requested duration")
        if any(not isinstance(scene.get(key), str) or not scene[key].strip() for key in required):
            raise ValueError("Director scene is missing required cinematography fields")
        if any(re.search(r"(?i)\\b(?:captions?|subtitles?|on.screen text)\\b|титры|субтитры", scene[key]) for key in required):
            raise ValueError("Director visual plan contains caption instructions")
        output.append(scene)
        cursor = end
    if cursor != storyboard.duration:
        raise ValueError("Director scenes do not cover requested duration")
    return tuple(output)
