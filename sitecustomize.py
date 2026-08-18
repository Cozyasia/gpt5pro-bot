# -*- coding: utf-8 -*-
"""Load production runtime before main.py.

V237 keeps the stable V236 isolated real-FaceSwap pipeline and adds two hard rules:
- selfie means FRONT-CAMERA POV, so the phone/camera is outside the finished frame;
- photo #3 is the deterministic user source for both target expression and FaceSwap.
"""
import contextlib

try:
    from neyrobot_prod.bootstrap import install_early
    install_early()
except Exception as exc:
    print(f"[neyrobot-prod] production bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.versioning import install_builder_hook as install_version_owner
    install_version_owner()
except Exception as exc:
    print(f"[neyrobot-prod] version owner warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.celebrity_selfie import install_async as install_celebrity_selfie
    install_celebrity_selfie()
except Exception as exc:
    print(f"[neyrobot-prod] celebrity selfie warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.selfie_commands_v206 import install_async as install_selfie_commands
    install_selfie_commands()
except Exception as exc:
    print(f"[neyrobot-prod] selfie commands warning: {type(exc).__name__}: {exc}")

try:
    from telegram.ext import ApplicationBuilder
    from neyrobot_prod import selfie_v219_triref_scene_owner as selfie_ui
    from neyrobot_prod import selfie_v229_canonical_two_stage as selfie_google
    from neyrobot_prod import selfie_v233_true_face_transfer as selfie_transfer

    CANONICAL_SELFIE_VERSION = "v237-front-camera-pov-source3-expression-lock-2026-08-18"

    # V237 source authority: one and the same original (#3) defines the expression
    # used to build PERSON A and is then sent to the real FaceSwap provider.
    # This avoids silently switching to another upload because of detector heuristics.
    _v236_select_source_photo = selfie_transfer._select_source_photo

    def _v237_select_source_photo(runtime, photos):
        if len(photos) >= 3 and bytes(photos[2] or b""):
            raw = bytes(photos[2])
            selfie_transfer._log(
                "AI_SELFIE_V237_SOURCE source_photo=3 authority=identity+expression+faceswap bytes=%s",
                len(raw),
            )
            return raw, 3, None
        return _v236_select_source_photo(runtime, photos)

    selfie_transfer._select_source_photo = _v237_select_source_photo

    # V237 composition owner. Real FaceSwap transfers identity reliably, but the
    # provider normally follows the TARGET pose/expression. Therefore Gemini must
    # construct PERSON A with the exact source expression BEFORE FaceSwap.
    def _v237_stage1_prompt(name, scene, shot_label, has_scene_image, source_photo_no):
        scene_rule = (
            "The first reference is the AUTHORITATIVE SCENE BASE. Preserve its architecture, furniture, camera viewpoint, perspective and lighting. "
            if has_scene_image else
            f"Create this location faithfully: {scene}. "
        )
        is_selfie = "Селфи" in str(shot_label) or "selfie" in str(shot_label).lower()
        if is_selfie:
            shot_rule = (
                "SHOT MODE IS A TRUE FRONT-CAMERA SELFIE POV. The final image IS the picture captured by the user's phone front camera. "
                "It is NOT a third-person photograph of somebody taking a selfie. The phone/camera is physically outside the captured frame and MUST NOT be visible anywhere. "
                "NO smartphone, phone edge, phone back, camera device, selfie stick, mirror reflection of a phone, camera UI, oversized foreground hand, or hand gripping a device. "
                "Use authentic arm-length front-camera perspective: both people look toward the lens, close natural selfie framing, mild wide-angle smartphone perspective. "
                "A shoulder or small part of an arm may be natural, but there must be NO hand or device between the lens and the people. "
            )
        else:
            shot_rule = (
                "SHOT MODE IS A THIRD-PERSON JOINT PHOTO taken by another person. Do not show any phone, selfie stick, camera interface, mirror-phone reflection, or oversized foreground hand. "
            )
        return (
            "Create ONE photorealistic vertical photograph with EXACTLY TWO principal people and no other visible faces. "
            f"{shot_rule}{scene_rule}"
            f"PERSON A is the USER and must be on the LEFT. USER SOURCE PHOTO #{source_photo_no} belongs ONLY to PERSON A and is the AUTHORITATIVE EXPRESSION SOURCE. "
            "PERSON A must copy the source person's body build, hair, head angle, gaze and natural pose. Most importantly, reproduce the SOURCE FACIAL EXPRESSION BEFORE FaceSwap as exactly as possible. "
            "EXPRESSION LOCK: match the source lip shape and lip closure/opening, mouth width, smile amount, left/right mouth-corner height, teeth visibility, jaw opening, cheek tension, nasolabial tension, eyelid opening, eye squint, eyebrow height/tilt and overall facial muscle state. "
            "Do NOT invent a nicer smile, do NOT change closed lips into a smile, do NOT expose teeth unless the source does, and do NOT alter the mouth asymmetry. "
            "This exact target expression is mandatory because the following real FaceSwap will replace identity while following the target pose/expression. "
            "PERSON A's temporary generated identity is disposable and will be physically replaced; do not beautify, average or redesign the face. "
            "Make PERSON A near-frontal, unobstructed, sharp and sufficiently large for direct transfer. Keep PERSON A clearly inside the LEFT 48 percent of the image. "
            f"PERSON B is {name} and must be on the RIGHT. The three HERO PORTRAIT references belong ONLY to PERSON B and are the sole identity authority for PERSON B. "
            "ABSOLUTE IDENTITY SEPARATION: never copy USER facial geometry, hair, age, jaw, eyes, nose, mouth, skin, expression or clothing identity into PERSON B. "
            "Never copy PERSON B identity into PERSON A. PERSON B must remain unmistakably the hero defined only by the HERO PORTRAIT references. "
            "Keep both heads separated horizontally with visible space. PERSON B must stay entirely in the RIGHT 48 percent. "
            "Natural anatomy, realistic skin and optics. No text, watermark, duplicated face, merged identity, morphing or hybrid face."
        )

    selfie_transfer._stage1_prompt = _v237_stage1_prompt

    # Prepare the proven three-photo UI once, then stop its legacy owner loop.
    selfie_ui.patch_runtime()

    def _legacy_noop(*args, **kwargs):
        return True

    selfie_ui.patch_runtime = _legacy_noop
    selfie_ui.bind_runtime_apps = lambda *args, **kwargs: 0
    selfie_ui.install_builder_hook = _legacy_noop
    selfie_ui.install_async = lambda *args, **kwargs: None
    selfie_ui.install = lambda *args, **kwargs: None

    selfie_transfer.install_async()
    selfie_google.VERSION = CANONICAL_SELFIE_VERSION
    selfie_ui.VERSION = CANONICAL_SELFIE_VERSION

    async def _disabled_comet_route(*args, **kwargs):
        raise RuntimeError("Legacy Comet selfie generation is disabled by V237")

    def _force_v237() -> None:
        selfie_google.generate = selfie_transfer.generate
        selfie_ui.generate = selfie_transfer.generate
        with contextlib.suppress(Exception):
            selfie_ui.public_callback.__globals__["generate"] = selfie_transfer.generate
        selfie_ui._comet_generate = _disabled_comet_route
        with contextlib.suppress(Exception):
            selfie_ui.public_callback.__globals__["_comet_generate"] = _disabled_comet_route
        selfie_transfer.install()

    _force_v237()
    selfie_google.patch_runtime()
    _force_v237()

    _builder_flag = "_neyrobot_v237_authoritative_faceswap_builder_hooked"
    if not getattr(ApplicationBuilder, _builder_flag, False):
        _original_build = ApplicationBuilder.build

        def _build_with_v237(self, *args, **kwargs):
            app = _original_build(self, *args, **kwargs)
            _force_v237()
            selfie_google.bind_application(app)
            selfie_transfer.bind_application(app)
            _force_v237()
            return app

        ApplicationBuilder.build = _build_with_v237
        setattr(ApplicationBuilder, _builder_flag, True)

    selfie_google.install_async()
    _force_v237()

    runtime = selfie_google._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_STORAGE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_COMMANDS_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_ADMIN_VERSION = CANONICAL_SELFIE_VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v237-gemini-expression-locked-scene-then-isolated-real-faceswap"
        runtime.AI_SELFIE_PROVIDER = "Gemini expression-locked composition + Segmind/PiAPI isolated real FaceSwap"
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    print("[neyrobot-prod] V237 true front-camera POV + source #3 expression-lock FaceSwap owner installed", flush=True)
except Exception as exc:
    print(f"[neyrobot-prod] canonical selfie V237 warning: {type(exc).__name__}: {exc}", flush=True)
