from __future__ import annotations

from ..models import CaptureMode


def build_scene_prompt(character_title: str, scene: str, mode: CaptureMode) -> str:
    common = (
        "Create one photorealistic image with exactly two adults and no other visible people. "
        "REFERENCE ORDER IS STRICT: the first 3-6 images show only the celebrity; the next image shows the USER'S FULL BODY; "
        "an optional final image is only a scene/composition reference. "
        f"PERSON A is the USER. Preserve PERSON A's sex presentation, approximate height, build, body proportions, shoulders, waist, limbs and posture from the full-body user reference. "
        "Do not copy the face from the full-body reference; render PERSON A with a clear, unobstructed, front-facing face suitable for a later face swap. "
        f"PERSON B is {character_title}. Preserve PERSON B's recognizable identity, age, face, build and characteristic appearance exclusively from the celebrity references. "
        "Never transform PERSON A into the celebrity. Never replace the celebrity with a random companion. "
        "Place PERSON A on the LEFT side of the final image and PERSON B on the RIGHT side, with both faces clearly visible and separated. "
        "Exactly two principal faces, no duplicate bodies, merged faces, extra companions, text, logos or watermark. "
    )
    if mode is CaptureMode.TRUE_PHONE_SELFIE:
        camera = (
            "TRUE FRONT-CAMERA SELFIE: PERSON A and PERSON B are close together in a direct front-camera image at natural arm's-length perspective. "
            "Both faces must remain fully visible. The phone, phone edge, mirror, selfie stick, photographer and third-person viewpoint must be invisible. "
        )
    else:
        camera = (
            "THIRD-PERSON PHOTO: show both subjects naturally, preferably three-quarter or full-body so PERSON A's build is visible. "
            "A fixed camera or event photographer viewpoint is allowed, but no third visible main subject. "
        )
    return common + camera + f"Scene: {scene.strip()}"
