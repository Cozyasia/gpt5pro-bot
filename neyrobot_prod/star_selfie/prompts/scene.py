from __future__ import annotations

from ..models import CaptureMode


def build_scene_prompt(character_title: str, scene: str, mode: CaptureMode) -> str:
    identity = (
        "STRICT MULTI-REFERENCE IDENTITY COMPOSITION. Create exactly two adults and no other visible people. "
        "SUBJECT A is the USER and must be placed on the LEFT. The USER BODY reference controls only height, build, "
        "shoulder width, limb proportions and overall silhouette. Completely ignore and do not copy the user's face, haircut, "
        "clothes, colors, accessories, pose, cup, objects or original background from the body reference. Dress SUBJECT A in "
        "new scene-appropriate clothing. Leave SUBJECT A's face clear, frontal enough and unobstructed for a later external face swap. "
        f"SUBJECT B is {character_title} and must be placed on the RIGHT. All CHARACTER references show the same person. "
        "Use every CHARACTER reference together to reconstruct SUBJECT B's exact identity: facial proportions, eyes, nose, mouth, "
        "jaw, beard, hairline, age, body cues and distinctive features. Do not generate a generic lookalike. Do not average, merge, "
        "beautify, rejuvenate or swap the two identities. SUBJECT B must remain recognisable independently of SUBJECT A. "
        "The two faces must be spatially separated and clearly detectable. No duplicate bodies, merged anatomy, text, logos or watermark. "
    )
    if mode is CaptureMode.TRUE_PHONE_SELFIE:
        camera = (
            "TRUE FRONT-CAMERA SELFIE. The output is the direct image from a phone front camera held by one of the two subjects. "
            "Both faces are visible at natural arm's-length perspective. The phone, mirror, selfie stick, photographer and any "
            "third-person viewpoint are invisible. Keep SUBJECT A on image-left and SUBJECT B on image-right. "
        )
    else:
        camera = (
            "THIRD-PERSON PHOTO. Show both subjects naturally, preferably at least three-quarter body. Keep SUBJECT A on image-left "
            "and SUBJECT B on image-right. Clothing for both subjects must be newly designed for the selected scene, not copied from references. "
        )
    return identity + camera + f"SCENE: {scene.strip()}"
