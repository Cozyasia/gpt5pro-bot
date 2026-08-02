from __future__ import annotations

from ..models import CaptureMode


def build_scene_prompt(character_title: str, scene: str, mode: CaptureMode) -> str:
    """Stable legacy identity-first composition.

    The scene model creates the celebrity from the catalogue references. The
    external Face Swap stage is reserved only for the user's face.
    """
    shot = (
        "SHOT MODE: FRONT-CAMERA SELFIE POV. The output is the phone front-camera image itself; "
        "the phone, mirror, photographer and interface must not be visible. "
        if mode is CaptureMode.TRUE_PHONE_SELFIE
        else
        "SHOT MODE: THIRD-PERSON JOINT PHOTO. Another person takes the photograph. Do not show a phone, "
        "selfie stick, camera interface or oversized foreground hand. "
    )
    return (
        f"Create one photorealistic vertical image with exactly two principal people. {shot}"
        f"SCENE REQUEST: {scene.strip() or 'a natural premium real-world environment'}. "
        "IDENTITY ACCURACY IS MORE IMPORTANT THAN STYLE. "
        "PERSON A IS THE USER and must remain on image-left. The USER BODY reference controls only height, body mass, "
        "shoulder width, torso-to-leg ratio, limb thickness and silhouette. Never copy its clothing, haircut, face, pose, "
        "cup, accessories or original background. Generate fresh scene-appropriate wardrobe. Keep PERSON A's face frontal, "
        "large, evenly lit, unobstructed and naturally proportioned because a dedicated external identity-transfer stage will "
        "replace only this face after scene generation. Do not invent strong facial details for PERSON A and do not borrow any "
        "features from PERSON B. "
        f"PERSON B IS {character_title} and must remain on image-right. Every CHARACTER reference depicts the same person. "
        "Use all CHARACTER references jointly as a strict multi-reference identity set. Reconstruct one exact consistent person, "
        "not an averaged or generic lookalike. Preserve craniofacial proportions, forehead, hairline, eye spacing, eyelids, brows, "
        "nose bridge and tip, lips, philtrum, jaw angle, chin, ears, beard contour and density, mature apparent age, body build, "
        "tattoos and habitual expression. Keep natural skin texture and do not make either principal person younger. PERSON B "
        "must already be immediately recognizable in the generated base scene. Do not reserve a placeholder face for PERSON B. "
        "Keep PERSON A and PERSON B separate and fixed left-to-right. Never merge, swap, average, duplicate, beautify, rejuvenate, "
        "change ethnicity or transfer facial features between them. Both faces must be large, sharp, unobstructed, inside the frame "
        "and looking toward the camera. Use realistic anatomy, focal length, skin texture, lighting and scene-consistent clothing. "
        "Background guests may appear only as small softly blurred extras without readable faces. No text, logos, watermarks, fake "
        "poster typography, distorted hands or interface elements."
    )
