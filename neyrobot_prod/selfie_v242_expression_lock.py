# -*- coding: utf-8 -*-
"""V242 source-expression lock overlay for AI selfie.

Goals:
- keep V241 as the single generation owner;
- keep photo #3 as the only authoritative user identity/expression source;
- make Gemini reproduce the source facial expression before real FaceSwap;
- prevent late V241 reassertions from silently restoring the weaker prompt;
- preserve the compact isolated FaceSwap path and native 2K output.
"""
from __future__ import annotations

import contextlib
from typing import Any

from neyrobot_prod import selfie_v241_authoritative_runtime as v241

VERSION = "v242-source-expression-lock-2026-08-19"

_ORIGINAL_V241_ENFORCE = v241.enforce_runtime
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    v241._log(message, *args)


def _stage1_prompt(name: str, scene: str, shot_label: str, has_scene_image: bool, source_photo_no: int) -> str:
    scene_rule = (
        "The first reference is the AUTHORITATIVE SCENE BASE. Preserve architecture, furniture, viewpoint, perspective and lighting. "
        if has_scene_image else f"Create this location faithfully: {scene}. "
    )
    is_selfie = "селфи" in str(shot_label).lower() or "selfie" in str(shot_label).lower()
    if is_selfie:
        shot_rule = (
            "TRUE FRONT-CAMERA SELFIE OUTPUT. The viewer IS the front camera. "
            "The capturing phone is behind the image plane and MUST NOT be visible. "
            "NO phone, smartphone, phone edge, phone case, screen, rear camera lenses, selfie stick, mirror-phone reflection, camera UI, foreground device, foreground hand, or foreground arm. "
            "Do not depict the act of taking a selfie; depict only the finished front-camera photograph. "
            "Exactly two people close to the lens at natural arm-length smartphone perspective, heads/shoulders/upper torsos. PERSON A hands and forearms stay outside frame. Both look into the lens. "
        )
    else:
        shot_rule = (
            "THIRD-PERSON JOINT PHOTO taken by another person. No visible phone, selfie stick, foreground device, camera UI or mirror-phone reflection. "
        )

    return (
        "Create ONE photorealistic vertical photograph with EXACTLY TWO principal people and no other visible faces. "
        f"{shot_rule}{scene_rule}"
        f"PERSON A is the USER on the LEFT. Source #{source_photo_no} supplied here is a VERIFIED FACE/EXPRESSION CROP from the authoritative user photo. "
        "EXPRESSION LOCK — this crop is not a loose style reference. Treat it as an immutable facial-expression template. "
        "Before FaceSwap, reproduce PERSON A with the SAME expression geometry as the source: same lip contour, exact lip closure or opening, same upper/lower lip tension, same mouth width, same left/right corner height, same smile amount, same teeth visibility, same jaw opening, same cheek tension, same nasolabial tension, same eyelid opening or squint, same eyebrow height/asymmetry and same gaze direction. "
        "Do NOT beautify, neutralize, exaggerate, symmetrize, reinterpret or replace the expression. Do NOT invent a smile, teeth, pursed lips, raised brows or squint that are not present in the source. "
        "Preserve the source head expression even if body pose, clothing and scene are newly generated. Keep PERSON A near-frontal with only minimal yaw/pitch/roll so the mouth, eyes and brows can remain geometrically faithful. "
        "PERSON A temporary identity is disposable and will be physically replaced by real FaceSwap; expression fidelity matters more than temporary facial resemblance. "
        "Keep PERSON A unobstructed, sharp, large, fully inside the LEFT 48 percent, and cleanly separated from PERSON B. "
        f"PERSON B is {name} on the RIGHT. The three HERO PORTRAIT references belong ONLY to PERSON B and are the sole identity authority for PERSON B. "
        "STRICT IDENTITY FIREWALL: never copy USER face, hair, age, eyes, nose, lips, jaw, skin, expression or clothing identity into PERSON B; never copy PERSON B into PERSON A. "
        "PERSON B stays entirely in the RIGHT 48 percent. Natural anatomy, realistic skin and optics. No text, watermark, duplicate face, merged identity, morphing or hybrid face."
    )


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
                    "AUTHORITATIVE USER FACE + EXPRESSION TEMPLATE #3 — PERSON A ONLY. "
                    "Copy facial-expression geometry exactly: lips, mouth corners, teeth visibility, jaw opening, cheeks, eyelids, eyebrows and gaze. "
                    "Do not infer phone, hand, arm, body pose, clothing or background from this crop.",
                    v241._expression_crop(bytes(raw)),
                ))
            else:
                out.append((label, raw))
        if count != 1:
            raise RuntimeError(f"expected exactly one user source reference, got {count}")
        patched = out
        _log("AI_SELFIE_V242_STAGE1_REFS user_ref=authoritative_expression_template source_photo=3 full_photo_reserved_for_faceswap=true")
    return await v241._google_request(prompt, patched, stage)


def enforce_runtime() -> None:
    """Reassert V241 plumbing, then apply the stronger V242 expression contract."""
    from neyrobot_prod import selfie_v219_triref_scene_owner as ui
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    # Let V241 restore the known-good provider/faceswap bindings first.
    v241.VERSION = VERSION
    _ORIGINAL_V241_ENFORCE()

    # Then replace only the expression-sensitive parts. The real FaceSwap,
    # compact ROI, native-resolution merge, detector and source-photo selection
    # remain the proven V241 implementation.
    transfer._stage1_prompt = _stage1_prompt
    google._call_google = _call_google

    transfer.VERSION = VERSION
    google.VERSION = VERSION
    ui.VERSION = VERSION
    v241.VERSION = VERSION

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v242-front-camera-source-expression-lock-compact-real-faceswap"
        runtime.AI_SELFIE_PROVIDER = "Gemini Pro/Flash exact source-expression composition -> compact isolated Segmind/PiAPI real FaceSwap"
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log("AI_SELFIE_V242_ENFORCE status=ok source=photo3 expression_lock=exact lips_mouth_eyes_brows=true faceswap=v241_compact_real version=%s", VERSION)


def install() -> None:
    global _INSTALLED

    # Critical: V241's guarded generator calls v241.enforce_runtime() on every
    # generation. Replace that module-level symbol so late reassertion executes
    # V242, not the old prompt.
    v241.enforce_runtime = enforce_runtime
    v241.VERSION = VERSION
    v241.install()
    enforce_runtime()

    if not _INSTALLED:
        _INSTALLED = True
        print("[neyrobot-prod] V242 source-expression lock installed over authoritative V241 runtime", flush=True)


__all__ = ["VERSION", "install", "enforce_runtime"]
