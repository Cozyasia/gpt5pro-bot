from __future__ import annotations

from ..models import CaptureMode


def build_scene_prompt(character_title: str, scene: str, mode: CaptureMode) -> str:
    """Identity-first composition with age-accurate hero rendering.

    The scene model creates the hero from the complete catalogue reference set.
    A later external transfer is reserved only for the user's face.
    """
    shot = (
        "SHOT MODE: FRONT-CAMERA SELFIE POV. The output is the phone front-camera image itself; "
        "the phone, mirror, photographer and interface must not be visible. Use a realistic phone lens, natural exposure, "
        "subtle sensor grain and ordinary photographic sharpness rather than a beauty-filtered portrait. "
        if mode is CaptureMode.TRUE_PHONE_SELFIE
        else
        "SHOT MODE: THIRD-PERSON JOINT PHOTO. Another person takes the photograph. Do not show a phone, selfie stick, "
        "camera interface or oversized foreground hand. Use a realistic professional-event photograph with natural lens detail, "
        "subtle sensor grain and no synthetic beauty retouching. "
    )
    return (
        f"Create one highly photorealistic vertical image with exactly two principal people. {shot}"
        f"SCENE REQUEST: {scene.strip() or 'a natural premium real-world environment'}. "
        "IDENTITY, TRUE APPARENT AGE AND REAL PHOTOGRAPHIC TEXTURE ARE MORE IMPORTANT THAN STYLE OR ATTRACTIVENESS. "
        "PERSON A IS THE USER and must remain on image-left. The USER BODY reference controls only true height, body mass, "
        "shoulder width, torso-to-leg ratio, limb thickness, posture and silhouette. Never copy its clothing, haircut, face, pose, "
        "cup, accessories or original background. Generate fresh scene-appropriate wardrobe while preserving the user's actual body build. "
        "Keep PERSON A's face frontal, large, evenly lit, unobstructed and naturally proportioned because a dedicated external identity-transfer "
        "stage will replace only this face after scene generation. Use a neutral anatomically plausible placeholder face for PERSON A. Do not "
        "borrow any features from PERSON B. Do not make PERSON A younger, slimmer, more symmetrical or more conventionally attractive. "
        f"PERSON B IS {character_title} and must remain on image-right. Every CHARACTER reference depicts the same real person at their real "
        "adult age. Use all CHARACTER references jointly as one strict multi-reference identity set. Reconstruct the current mature identity, "
        "not a youthful version, historical version, averaged face or generic lookalike. Infer the stable apparent age from the full reference set "
        "and preserve it exactly. Preserve forehead lines, crow's-feet, under-eye structure, nasolabial folds, cheek volume, jaw softness, neck age, "
        "skin pores, uneven skin texture, beard greying and density, hairline, temples, eye spacing, eyelids, brows, nose bridge and tip, lips, "
        "philtrum, jaw angle, chin, ears, body build, tattoos and habitual expression. PERSON B must already be immediately recognizable in the "
        "generated base scene. Do not reserve a placeholder face for PERSON B and do not expect an external celebrity Face Swap. "
        "ABSOLUTELY NO AGE REDUCTION: no rejuvenation, de-aging, teenage or thirty-year-old interpretation, face slimming, jaw sharpening, enlarged "
        "eyes, lifted brows, wrinkle removal, pore removal, porcelain skin, wax skin, airbrushing, glamour retouching, beauty filter, HDR skin, "
        "plastic texture, CGI texture or excessive denoising. Keep natural asymmetry and ordinary photographic imperfections. "
        "Keep PERSON A and PERSON B separate and fixed left-to-right. Never merge, swap, average, duplicate, change ethnicity or transfer facial "
        "features between them. Both faces must be large, sharp, unobstructed, fully inside the frame and looking toward the camera. Use realistic "
        "anatomy, focal length, depth of field, scene-consistent lighting and clothing. Skin must show fine pores, small tonal variations, beard hairs, "
        "subtle wrinkles and believable camera grain without oversharpening. Background guests may appear only as small softly blurred extras without "
        "readable faces. No text, logos, watermarks, fake poster typography, distorted hands or interface elements."
    )
