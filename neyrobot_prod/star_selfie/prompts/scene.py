from __future__ import annotations

from ..models import CaptureMode


def build_scene_prompt(character_title: str, scene: str, mode: CaptureMode) -> str:
    """Build the V232-quality composition prompt.

    The scene generator must finish the photograph and the celebrity before the
    external FaceSwap stage runs. FaceSwap is not allowed to repair composition
    or the celebrity; it replaces only PERSON A's face in the completed image.
    """
    shot = (
        "SHOT MODE: authentic front-camera selfie. The returned image is the phone photograph itself; do not show the phone, mirror, photographer or interface. Keep both faces close, large and naturally within selfie focal length. "
        if mode is CaptureMode.TRUE_PHONE_SELFIE
        else
        "SHOT MODE: third-person joint photograph made by another photographer. Do not show a phone, selfie stick, camera interface or oversized foreground hand. Use a natural editorial/event focal length. "
    )
    requested_scene = scene.strip() or "a believable premium real-world environment"
    return (
        "Create one finished photorealistic vertical photograph with exactly two principal people. "
        f"{shot}SCENE REQUEST: {requested_scene}. "
        "This is the final composition pass: finish wardrobe, body, pose, hands, lighting, skin, optics, environment and PERSON B identity now. Do not leave a generic celebrity placeholder. "
        "IDENTITY ASSIGNMENT IS FIXED. PERSON A is the user and must remain on image-left. PERSON B is the selected celebrity and must remain on image-right. Never swap, merge, average, duplicate or cross-contaminate their identities. "
        "PERSON A: the body reference controls only height, body mass, shoulder width, torso-to-leg ratio, limb thickness and silhouette. Create fresh scene-appropriate clothing; never copy the reference clothes, cup, pose, accessories or background. The portrait controls apparent age, head scale and hairline only for constructing a clean target head. Keep PERSON A near-frontal or mild three-quarter, evenly lit, unobstructed and large enough for a later exact external face replacement. Do not beautify, slim, rejuvenate or smooth away natural age. "
        f"PERSON B is {character_title}. All PERSON B HERO PORTRAITS depict the same person and form one strict multi-reference identity set. Reconstruct that exact mature person, not a generic lookalike and not a younger version. Preserve head width and height, forehead, hairline, eye spacing and eyelids, eyebrows, nose bridge and tip, philtrum, lips, cheeks, jaw angle, chin, ears, beard contour and density, skin age, body build, tattoos and habitual expression. PERSON B must be immediately recognizable before any post-processing. "
        "Preserve realistic pores, fine lines, beard texture, natural asymmetry and age-appropriate skin. Avoid waxy skin, beauty filters, excessive denoising, plastic faces and artificial eye sharpening. Use realistic anatomy, hands, shadows, depth of field, lens behavior and scene-consistent clothing. "
        "Both principal faces must be sharp, unobstructed and clearly separated. Background guests may be small and softly blurred only. No readable text, fake logos, watermark, poster typography or interface elements. Output one image only."
    )
