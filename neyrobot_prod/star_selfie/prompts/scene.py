from __future__ import annotations

from ..models import CaptureMode


def build_scene_prompt(character_title: str, scene: str, mode: CaptureMode) -> str:
    identity = (
        "STRICT TWO-PERSON IDENTITY COMPOSITION. Create exactly two foreground adults. Background people may appear only as small, "
        "softly blurred extras with no readable faces. SUBJECT A is the USER and must remain on the LEFT. The USER BODY reference controls "
        "only height, body mass, shoulder width, torso-to-leg ratio, limb thickness and silhouette. Never copy clothing, haircut, face, pose, "
        "cup, accessories or background from the body reference. Dress SUBJECT A appropriately for the selected scene. SUBJECT A must face "
        "the camera within 10 degrees, with both eyes fully visible, mouth unobstructed, even soft light, no profile and no motion blur. Keep "
        "natural head proportions and a clean neutral placeholder face because a dedicated identity-transfer stage will replace it. Do not add "
        "skin smoothing, beauty filters, pore exaggeration, plastic skin, painterly texture, sharpening halos or compression-like facial texture. "
        f"SUBJECT B is {character_title} and must remain on the RIGHT. Every CHARACTER reference depicts the same celebrity. Reconstruct one "
        "single exact identity from all references; never average the references into a generic lookalike. Preserve stable craniofacial geometry: "
        "head width and height, forehead, hairline, eye spacing, eyelid shape, brows, nose bridge and tip, philtrum, lips, jaw angle, chin, ears, "
        "beard density and contour, age, body build, tattoos and habitual expression. The celebrity must be immediately recognizable before the "
        "external identity pass. SUBJECT B must face the camera within 12 degrees with both eyes visible and a large unobstructed face. Do not "
        "beautify, rejuvenate, slim, broaden, enlarge, duplicate or stylize either person. Keep the two faces separated horizontally, similar in "
        "scale, fully inside frame and easy for a detector to index left-to-right as USER=0 and CELEBRITY=1. Use realistic focal length, accurate "
        "skin color, fine natural skin texture, crisp eyes and eyelashes, detailed beard hair, realistic anatomy and scene-consistent wardrobe. "
        "No text, logos, watermark, fake poster typography or distorted hands. "
    )
    if mode is CaptureMode.TRUE_PHONE_SELFIE:
        camera = (
            "TRUE FRONT-CAMERA SELFIE. The image itself is the phone front-camera output; no phone, mirror, photographer or third-person camera "
            "is visible. Both heads and upper torsos fill the frame at arm's length, USER left and CELEBRITY right, both looking directly into "
            "the lens. Keep both faces large, equally sharp and in the same focal plane. Use natural front-camera perspective without extreme "
            "wide-angle deformation. "
        )
    else:
        camera = (
            "POSED THIRD-PERSON JOINT PHOTO, not a candid conversation. Both people look directly toward the photographer. Frame from waist or "
            "chest up whenever possible so both faces remain large enough for identity transfer; avoid distant full-body framing unless the scene "
            "strictly requires it. USER left and CELEBRITY right. Generate fresh scene-appropriate wardrobe for both people. Use professional "
            "portrait focus with both faces sharp and the background gently separated. "
        )
    return identity + camera + f"SCENE: {scene.strip()}"
