"""Planning primitives for native-audio Veo multi-scene videos.

No network calls or billing side effects here. Keep single-clip production intact
until orchestration, accounting and FFmpeg integration pass end-to-end tests.
"""
from dataclasses import dataclass
from math import ceil

ALLOWED_DURATIONS = (8, 15, 24, 30, 60)
VEO_SCENE_SECONDS = 8
MAX_SPOKEN_WORDS_PER_SCENE = 16


@dataclass(frozen=True)
class Scene:
    index: int
    generated_seconds: int
    timeline_start: int
    timeline_end: int
    spoken_text: str


def split_spoken_text(script: str, scene_count: int) -> list[str]:
    """Distribute words across scenes, never truncate or silently drop words."""
    words = script.strip().split()
    if not words:
        return [""] * scene_count
    if len(words) > scene_count * MAX_SPOKEN_WORDS_PER_SCENE:
        raise ValueError(
            f"Script is too long for natural speech: max "
            f"{scene_count * MAX_SPOKEN_WORDS_PER_SCENE} words"
        )
    result = []
    offset = 0
    for i in range(scene_count):
        remaining = len(words) - offset
        slots = scene_count - i
        count = ceil(remaining / slots)
        result.append(" ".join(words[offset:offset + count]))
        offset += count
    return result


def plan_video(duration_seconds: int, spoken_script: str) -> list[Scene]:
    if duration_seconds not in ALLOWED_DURATIONS:
        raise ValueError(f"Supported durations: {ALLOWED_DURATIONS}")
    count = ceil(duration_seconds / VEO_SCENE_SECONDS)
    speeches = split_spoken_text(spoken_script, count)
    scenes = []
    for i in range(count):
        start = i * VEO_SCENE_SECONDS
        end = min(duration_seconds, start + VEO_SCENE_SECONDS)
        scenes.append(Scene(i + 1, VEO_SCENE_SECONDS, start, end, speeches[i]))
    assert scenes[-1].timeline_end == duration_seconds
    return scenes


def estimated_provider_cost_usd(duration_seconds: int, per_second_usd: float) -> float:
    """Preflight estimate for generated seconds, excluding retries and editing."""
    if per_second_usd < 0:
        raise ValueError("Price cannot be negative")
    return round(len(plan_video(duration_seconds, "Тест")) * VEO_SCENE_SECONDS * per_second_usd, 4)
