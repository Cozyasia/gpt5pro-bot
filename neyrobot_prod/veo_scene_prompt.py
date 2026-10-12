"""Build concise, consistent prompts for Russian native-audio Veo scenes."""
from __future__ import annotations
from .veo_multiscene import Scene

RUSSIAN_VOICE_RULES = (
    "Native spoken audio in Russian (ru-RU) only. No English translation. "
    "Speak at a natural pace; finish the exact dialogue before the clip ends. "
    "Synchronize lip movements with spoken Russian. "
    "Do not generate background text, logos, subtitles, or UI lettering. "
    "Leave clear visual margins for later overlay graphics."
)


def scene_prompt(scene: Scene, visual_brief: str, *, presenter: str = "") -> str:
    """Visual brief + bounded exact dialogue. Branding is added in post."""
    if not visual_brief.strip():
        raise ValueError("Visual brief required")
    if not scene.spoken_text.strip():
        dialogue = "No spoken dialogue; natural ambient sound only."
    else:
        dialogue = (
            'The presenter says exactly in Russian: "'
            + scene.spoken_text.replace('"', "'")
            + '".'
        )
    continuity = (
        "Keep the same presenter appearance, outfit, lighting, and studio "
        "as the reference. " + presenter.strip()
        if presenter.strip() else ""
    )
    return "\n".join((
        "Premium photorealistic vertical 9:16 commercial scene.",
        visual_brief.strip(),
        continuity,
        RUSSIAN_VOICE_RULES,
        dialogue,
    )).strip()
