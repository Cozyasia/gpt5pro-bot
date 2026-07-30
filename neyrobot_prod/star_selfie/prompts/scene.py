from __future__ import annotations

from ..models import CaptureMode


def build_scene_prompt(character_title: str, scene: str, mode: CaptureMode) -> str:
    common = (
        "Create one photorealistic image with exactly two adults: the user and "
        f"{character_title}. Use the supplied character references for identity, clothing cues only when relevant, "
        "and generate a coherent new environment. No extra people, duplicate bodies, merged faces, text, logo or watermark. "
    )
    if mode is CaptureMode.TRUE_PHONE_SELFIE:
        camera = (
            "TRUE FRONT-CAMERA SELFIE: the image is the direct output of a phone front camera held by one of the two people. "
            "Both faces are inside the frame at natural arm's-length perspective. The phone, phone edge, mirror, selfie stick, "
            "photographer and any third-person camera viewpoint must be invisible. Do not depict the scene as someone else photographing them. "
        )
    else:
        camera = (
            "THIRD-PERSON PHOTO: another person or a fixed camera photographs both subjects. Natural full/half-body composition is allowed. "
            "Do not imitate a front-camera selfie perspective. "
        )
    return common + camera + f"Scene: {scene.strip()}"
