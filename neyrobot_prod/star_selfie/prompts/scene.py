from __future__ import annotations

from ..models import CaptureMode


def build_scene_prompt(character_title: str, scene: str, mode: CaptureMode) -> str:
    identity = (
        "STRICT TWO-PERSON IDENTITY COMPOSITION. Create exactly two foreground adults. Background people may appear only as small, "
        "out-of-focus extras with no clear faces. SUBJECT A is the USER and must stay on the LEFT. The USER BODY reference controls "
        "only height, body mass, shoulder width, torso-to-leg ratio, limb thickness and silhouette. Never copy the reference clothing, "
        "haircut, face, pose, cup, accessories or background. Dress SUBJECT A appropriately for the selected scene. SUBJECT A must face "
        "the camera within 15 degrees, with both eyes visible, mouth unobstructed, no profile, no strong shadow and a face at least 320 pixels "
        "high in the final 2K image. Keep a natural head shape and neutral placeholder facial features because an external identity-transfer "
        "stage will replace this face exactly. "
        f"SUBJECT B is {character_title} and must stay on the RIGHT. Every CHARACTER reference depicts the same celebrity. Reconstruct the "
        "celebrity from all references without averaging into a generic lookalike: preserve exact craniofacial proportions, eyes, brows, nose, "
        "mouth, jaw, beard pattern, hairline, age, body build, tattoos and other stable identity cues. SUBJECT B must also face the camera within "
        "20 degrees with a large, unobstructed face so a second identity-preservation pass can reinforce the celebrity. Do not merge identities, "
        "beautify, rejuvenate, slim, enlarge, duplicate or stylize either person. Keep the two faces separated horizontally, similar in scale, "
        "fully inside frame and easy for a face detector to index left-to-right as USER=0 and CELEBRITY=1. Photorealistic documentary camera, "
        "real skin texture, realistic anatomy, no text, logos or watermark. "
    )
    if mode is CaptureMode.TRUE_PHONE_SELFIE:
        camera = (
            "TRUE FRONT-CAMERA SELFIE. The image itself is the phone front-camera output; no phone, mirror, photographer or third-person camera "
            "is visible. Both heads and upper torsos fill the frame at arm's length, USER left and CELEBRITY right, both looking into the lens. "
        )
    else:
        camera = (
            "POSED THIRD-PERSON JOINT PHOTO, not a candid conversation. Show both people looking toward the photographer, preferably from knees "
            "or waist up so faces remain large. USER left and CELEBRITY right. Generate new scene-appropriate wardrobe for both people. "
        )
    return identity + camera + f"SCENE: {scene.strip()}"
