# -*- coding: utf-8 -*-
"""V264 stage-1 scaffold guard.

Gemini still receives only the verified crop from photo #3, never the full source
photo, but that crop is authoritative for PERSON-A age/head/hair scaffold as well as
expression geometry. The inner facial identity remains disposable because V264 will
replace it, while cranial proportions, jaw, forehead, hairline and age category must
not be re-invented by the scene model.
"""
from __future__ import annotations

from typing import Any

from neyrobot_prod import selfie_v241_authoritative_runtime as v241

VERSION = v241.VERSION
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    v241._log(message, *args)


async def _call_google(prompt: str, refs: list[tuple[str, bytes]], stage: str):
    patched = list(refs or [])
    if str(stage) == "composition_identity_separated":
        out: list[tuple[str, bytes]] = []
        count = 0
        for label, raw in patched:
            label_s = str(label or "")
            if label_s.startswith("USER SOURCE PHOTO"):
                count += 1
                out.append((
                    "USER VERIFIED HEAD/EXPRESSION CROP #3 — PERSON A ONLY. "
                    "AUTHORITATIVE for age category, cranial silhouette, forehead/hairline, hair colour/style, "
                    "jaw/chin/cheek proportions and expression geometry. Inner identity texture will be replaced later. "
                    "Do not infer phone, hand, arm, clothing or background from this crop.",
                    v241._expression_crop(bytes(raw)),
                ))
            else:
                out.append((label, raw))
        if count != 1:
            raise RuntimeError(f"expected exactly one user source reference, got {count}")
        patched = out
        _log(
            "AI_SELFIE_V264_STAGE1_SCAFFOLD ref=head_expression_crop age_lock=true head_shape_lock=true "
            "hair_lock=true full_photo3_reserved_for_faceswap=true"
        )
    return await v241._google_request(prompt, patched, stage)


def _stage1_prompt(name: str, scene: str, shot_label: str, has_scene_image: bool, source_photo_no: int) -> str:
    scene_rule = (
        "The first reference is the AUTHORITATIVE SCENE BASE. Preserve architecture, furniture, viewpoint, perspective and lighting. "
        if has_scene_image else f"Create this location faithfully: {scene}. "
    )
    is_selfie = "селфи" in str(shot_label).lower() or "selfie" in str(shot_label).lower()
    if is_selfie:
        shot_rule = (
            "TRUE FRONT-CAMERA SELFIE RESULT, NOT A THIRD-PERSON PHOTO OF SOMEONE TAKING A SELFIE. "
            "The viewer IS the phone front camera. The capturing device is behind the image plane and must be absent from the picture. "
            "ABSOLUTELY NO phone, smartphone, phone edge, phone case, screen, rear cameras, selfie stick, camera device, mirror-phone reflection, camera UI, foreground hand, foreground arm, or hand holding a device. "
            "Do not illustrate the act of taking a selfie. Show only the resulting front-camera photograph. "
            "Exactly two people close to the lens at natural arm-length wide-angle perspective, heads/shoulders/upper torsos. PERSON A hands and forearms stay outside the frame. Both look toward the lens. "
        )
    else:
        shot_rule = "THIRD-PERSON JOINT PHOTO taken by another person. No visible phone, selfie stick, foreground device, camera UI or mirror-phone reflection. "

    return (
        "Create ONE photorealistic vertical photograph with EXACTLY TWO principal people and no other visible faces. "
        f"{shot_rule}{scene_rule}"
        f"PERSON A is the USER on the LEFT. Source #{source_photo_no} supplied here is a verified HEAD/EXPRESSION crop and is the authoritative PERSON-A scaffold. "
        "AGE/HEAD LOCK: preserve the user's apparent age category exactly. Never adultize a child/teen, never rejuvenate or age an adult, and never beautify the craniofacial scaffold. "
        "Preserve head width/height ratio, skull/forehead silhouette, hairline, hair colour, hair length/style, ear placement, cheek volume, jaw width, chin length and head-to-shoulder proportion from the user crop. "
        "These OUTER HEAD AND AGE PROPORTIONS ARE NOT DISPOSABLE and must survive into the generated scene. "
        "EXPRESSION LOCK: match exact lip closure/opening, mouth width, smile amount, mouth-corner asymmetry, teeth visibility, jaw opening, cheek tension, eyelid opening/squint, eyebrow height and gaze. "
        "FACE GEOMETRY LOCK: preserve normalized interocular distance, eye-line tilt, eye-to-nose distance, nose-to-mouth distance, mouth-corner spacing, nose width/length and lower-face/chin placement. Do not widen, narrow, stretch or stylize the face scaffold. "
        "Only PERSON A's INNER FACIAL IDENTITY TEXTURE is temporary and will be physically replaced later. Do not use that instruction as permission to change age, head shape, hair, jaw or facial proportions. "
        "Keep PERSON A near-frontal, unobstructed, sharp, large, fully inside the LEFT 48 percent, with clean horizontal separation from PERSON B. "
        f"PERSON B is {name} on the RIGHT. The three HERO PORTRAIT references belong ONLY to PERSON B and are the sole identity authority for PERSON B. "
        "STRICT IDENTITY FIREWALL: never copy USER face, hair, age, eyes, nose, lips, jaw, skin, expression or clothing identity into PERSON B; never copy PERSON B into PERSON A. "
        "PERSON B stays entirely in the RIGHT 48 percent. Natural anatomy, realistic skin and optics. No text, watermark, duplicate face, merged identity, morphing or hybrid face."
    )


def install() -> None:
    global _INSTALLED
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    # Patch both the authoritative source module and the already-bound active modules.
    # Later V241 reassertions also use these replaced globals.
    v241._call_google = _call_google
    v241._stage1_prompt = _stage1_prompt
    google._call_google = _call_google
    transfer._stage1_prompt = _stage1_prompt
    _INSTALLED = True
    _log(
        "AI_SELFIE_V264_STAGE1_SCAFFOLD_INSTALL status=ok age_lock=true head_shape_lock=true "
        "hair_lock=true expression_lock=true full_photo_to_gemini=false active_boundary=true"
    )


__all__ = ["VERSION", "install", "_call_google", "_stage1_prompt"]
