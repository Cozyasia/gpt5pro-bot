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
        dialogue = ("No dialogue, no narration, no spoken words in this scene. "
                    "Only subtle ambient sound. Do not repeat speech from any other scene.")
    else:
        dialogue = (
            'The presenter says exactly in Russian: "'
            + scene.spoken_text.replace('"', "'")
            + '". Speak these words ONCE only. No introductions, repetitions, paraphrases, "
              "extra commentary or dialogue from other scenes. Do not restart the advertisement.'
        )
    continuity = (
        "Keep the same presenter appearance, outfit, lighting, and studio "
        "as the reference. " + presenter.strip()
        if presenter.strip() else ""
    )
    visual_beats = (
        "Opening establishing shot; introduce the product context without showing invented interface text.",
        "Detail shot of hands, real environment and product use; maintain visual palette.",
        "Supporting cinematic B-roll with natural motion and no invented UI or lettering.",
        "Closing brand-safe composition with clean negative space for a real CTA overlay.",
    )
    beat = visual_beats[min(scene.index - 1, len(visual_beats) - 1)]
    return "\n".join((
        "Premium photorealistic vertical 9:16 commercial scene.",
        visual_brief.strip(),
        f"Scene {scene.index}, timeline {scene.timeline_start}-{scene.timeline_end}s. {beat}",
        "This is a DIFFERENT consecutive scene of the same advertisement, not a new advertisement. "
        "Never restart the narrative. Do not invent on-screen words, subtitles, logos, "
        "payment-app screens, fake user interfaces or text. Leave typography to postproduction.",
        "If no image reference is supplied, avoid close-ups of a speaking presenter; "
        "prefer hands, wide shots, and B-roll to prevent identity changes between scenes.",
        continuity,
        RUSSIAN_VOICE_RULES,
        composition_instructions(text_policy or TextPolicy()),
        dialogue,
    )).strip()
