"""Build concise, consistent prompts for Russian native-audio Veo scenes."""
from __future__ import annotations
from .veo_multiscene import Scene
from .video_text_layout import TextPolicy, composition_instructions

RUSSIAN_VOICE_RULES = (
    "Native spoken audio in Russian (ru-RU) only. No English translation. "
    "Speak at a natural pace; finish the exact dialogue before the clip ends. "
    "Synchronize lip movements with spoken Russian. "
    "Follow scene-specific composition and text-placement instructions."
)


def scene_prompt(scene: Scene, visual_brief: str, *, presenter: str = "", text_policy: TextPolicy | None = None) -> str:
    """Visual brief + bounded exact dialogue. Branding is added in post."""
    if not visual_brief.strip():
        raise ValueError("Visual brief required")
    if not scene.spoken_text.strip():
        dialogue = ("If the visual brief calls for spoken narration, speak naturally in Russian only; "
                    "otherwise use natural ambient sound without speech.")
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
        composition_instructions(text_policy or TextPolicy()),
        dialogue,
    )).strip()
