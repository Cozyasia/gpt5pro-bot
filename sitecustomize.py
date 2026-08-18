# -*- coding: utf-8 -*-
"""Load production runtime before main.py.

V238 keeps the stable V236 isolated real-FaceSwap pipeline and hardens two things:
- selfie means FRONT-CAMERA POV, so no phone/hand/device may appear in frame;
- Gemini receives a face/expression-only crop from photo #3, while real FaceSwap
  still receives the original full photo #3. This prevents source-phone/hand pose
  contamination while preserving the user's real identity and expression source.
"""
import contextlib
import io

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

    CANONICAL_SELFIE_VERSION = "v238-front-camera-expression-crop-source3-2026-08-19"

    # Photo #3 is deterministic authority for user identity/expression/FaceSwap.
    _v236_select_source_photo = selfie_transfer._select_source_photo

    def _v238_select_source_photo(runtime, photos):
        if len(photos) >= 3 and bytes(photos[2] or b""):
            raw = bytes(photos[2])
            selfie_transfer._log(
                "AI_SELFIE_V238_SOURCE source_photo=3 authority=identity+expression+faceswap bytes=%s",
                len(raw),
            )
            return raw, 3, None
        return _v236_select_source_photo(runtime, photos)

    selfie_transfer._select_source_photo = _v238_select_source_photo

    def _v238_expression_crop(raw: bytes) -> bytes:
        """Give Gemini face/expression context without exposing phone/hand/body pose.

        Prefer the existing runtime detector when it is usable. If OpenCV detection
        is unavailable, use a conservative upper-central crop that removes the lower
        part of typical portrait/selfie uploads where phones and hands usually sit.
        The original full photo is NOT modified and is still used by FaceSwap.
        """
        from PIL import Image

        data = bytes(raw or b"")
        if len(data) < 1024:
            return data
        try:
            im = Image.open(io.BytesIO(data)).convert("RGB")
            w, h = im.size
            runtime = selfie_transfer._runtime()
            faces = selfie_transfer._detect(runtime, data) if runtime is not None else []
            if len(faces) == 1:
                f = faces[0]
                x = int(f.get("x", 0)); y = int(f.get("y", 0))
                fw = int(f.get("w", 0)); fh = int(f.get("h", 0))
                if fw > 20 and fh > 20:
                    cx = x + fw / 2.0
                    cy = y + fh / 2.0
                    side = max(fw, fh) * 1.65
                    x0 = max(0, int(cx - side / 2))
                    y0 = max(0, int(cy - side * 0.58))
                    x1 = min(w, int(cx + side / 2))
                    y1 = min(h, int(cy + side * 0.62))
                else:
                    raise ValueError("invalid face box")
            else:
                # Detector-independent fallback: upper-center portrait crop.
                crop_w = int(w * 0.78)
                crop_h = int(h * 0.58)
                x0 = max(0, (w - crop_w) // 2)
                y0 = 0
                x1 = min(w, x0 + crop_w)
                y1 = min(h, crop_h)
            crop = im.crop((x0, y0, x1, y1))
            if max(crop.size) > 1200:
                crop.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            crop.save(out, format="JPEG", quality=96, subsampling=0, optimize=True)
            encoded = out.getvalue()
            selfie_transfer._log(
                "AI_SELFIE_V238_EXPRESSION_REF mode=face_only crop=%s,%s,%s,%s dims=%sx%s bytes=%s phone_body_context_removed=true",
                x0, y0, x1, y1, crop.width, crop.height, len(encoded),
            )
            return encoded if len(encoded) > 1024 else data
        except Exception as exc:
            selfie_transfer._log("AI_SELFIE_V238_EXPRESSION_REF fallback=original error=%s:%s", type(exc).__name__, exc)
            return data

    # Intercept only Stage-1 references. The full source stays untouched inside
    # selfie_transfer.generate and is therefore still passed to Segmind/PiAPI.
    _v236_call_google = selfie_google._call_google

    async def _v238_call_google(prompt, refs, stage):
        if str(stage) == "composition_identity_separated":
            patched = []
            for label, raw in list(refs or []):
                label_s = str(label or "")
                if label_s.startswith("USER SOURCE PHOTO"):
                    patched.append((
                        label_s.replace(
                            "pose/expression/body",
                            "FACE + EXPRESSION ONLY; ignore body, hands, phone, objects and source pose",
                        ),
                        _v238_expression_crop(bytes(raw)),
                    ))
                else:
                    patched.append((label, raw))
            refs = patched
            selfie_transfer._log(
                "AI_SELFIE_V238_STAGE1_REFS stage=%s user_ref=face_expression_only full_source_reserved_for_faceswap=true",
                stage,
            )
        return await _v236_call_google(prompt, refs, stage)

    selfie_google._call_google = _v238_call_google

    def _v238_stage1_prompt(name, scene, shot_label, has_scene_image, source_photo_no):
        scene_rule = (
            "The first reference is the AUTHORITATIVE SCENE BASE. Preserve its architecture, furniture, camera viewpoint, perspective and lighting. "
            if has_scene_image else
            f"Create this location faithfully: {scene}. "
        )
        is_selfie = "Селфи" in str(shot_label) or "selfie" in str(shot_label).lower()
        if is_selfie:
            shot_rule = (
                "SHOT MODE IS TRUE FRONT-CAMERA SELFIE POV. The output itself is the image captured by the front-facing camera. "
                "Therefore the capturing phone is behind the image plane and cannot appear inside its own photograph. "
                "ABSOLUTE COMPOSITION RULE: show only heads, shoulders and upper torsos; both of PERSON A's hands and forearms are OUTSIDE THE FRAME. "
                "ZERO handheld objects. ZERO smartphone. ZERO phone edge/back/case. ZERO selfie stick. ZERO camera device. ZERO mirror reflection. ZERO camera UI. "
                "Do not depict the act of taking a selfie; depict only the resulting selfie photograph. "
                "Use close arm-length front-camera perspective, both people looking toward the lens, mild smartphone wide-angle optics, natural slight perspective distortion. "
            )
        else:
            shot_rule = (
                "SHOT MODE IS A THIRD-PERSON JOINT PHOTO taken by another person. No phone, selfie stick, camera UI, mirror-phone reflection, or foreground device. "
            )
        return (
            "Create ONE photorealistic vertical photograph with EXACTLY TWO principal people and no other visible faces. "
            f"{shot_rule}{scene_rule}"
            f"PERSON A is the USER and must be on the LEFT. USER SOURCE PHOTO #{source_photo_no} is supplied as FACE/EXPRESSION AUTHORITY ONLY. "
            "Ignore and do not reproduce the source background, clothing pose, arm pose, hands, phone, device, accessories or any object held by the source person. "
            "Do not copy the source body pose in selfie mode. Build a new neutral upper-torso selfie pose compatible with a front-camera photograph. "
            "Reproduce the SOURCE FACIAL EXPRESSION before FaceSwap as closely as possible: lip contour, lip closure/opening, mouth width, smile amount, mouth-corner asymmetry, teeth visibility, jaw opening, cheek tension, eyelid opening, squint and eyebrow position. "
            "Do NOT invent a nicer smile; do NOT expose teeth unless present in the source expression. "
            "PERSON A's temporary generated facial identity is disposable and will be physically replaced by real FaceSwap. Keep PERSON A near-frontal, unobstructed, sharp and large enough for transfer, entirely inside the LEFT 48 percent. "
            f"PERSON B is {name} and must be on the RIGHT. The three HERO PORTRAIT references belong ONLY to PERSON B and are the sole identity authority for PERSON B. "
            "ABSOLUTE IDENTITY SEPARATION: never copy USER facial geometry, hair, age, jaw, eyes, nose, mouth, skin, expression or clothing identity into PERSON B. "
            "Never copy PERSON B identity into PERSON A. PERSON B must remain unmistakably the hero defined only by the HERO PORTRAIT references. "
            "Keep both heads separated horizontally with visible space. PERSON B must stay entirely in the RIGHT 48 percent. "
            "Natural anatomy, realistic skin and optics. No text, watermark, duplicated face, merged identity, morphing or hybrid face."
        )

    selfie_transfer._stage1_prompt = _v238_stage1_prompt

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
    selfie_transfer.VERSION = CANONICAL_SELFIE_VERSION

    async def _disabled_comet_route(*args, **kwargs):
        raise RuntimeError("Legacy Comet selfie generation is disabled by V238")

    def _force_v238() -> None:
        selfie_google.generate = selfie_transfer.generate
        selfie_ui.generate = selfie_transfer.generate
        with contextlib.suppress(Exception):
            selfie_ui.public_callback.__globals__["generate"] = selfie_transfer.generate
        selfie_ui._comet_generate = _disabled_comet_route
        with contextlib.suppress(Exception):
            selfie_ui.public_callback.__globals__["_comet_generate"] = _disabled_comet_route
        selfie_transfer.install()

    _force_v238()
    selfie_google.patch_runtime()
    _force_v238()

    # V235 compatibility watchdog is still useful for blocking legacy owners, but
    # its old version markers must not overwrite the current V238 runtime every 250ms.
    with contextlib.suppress(Exception):
        from neyrobot_prod import selfie_v218_runtime_owner as compat_owner
        compat_owner.VERSION = CANONICAL_SELFIE_VERSION
        _compat_patch = compat_owner.patch_runtime

        def _v238_compat_patch():
            ok = _compat_patch()
            mod = compat_owner._runtime()
            if mod is not None:
                mod.CELEBRITY_SELFIE_VERSION = CANONICAL_SELFIE_VERSION
                mod.AI_SELFIE_RUNTIME_VERSION = CANONICAL_SELFIE_VERSION
                mod.SELFIE_STORAGE_VERSION = CANONICAL_SELFIE_VERSION
                mod.SELFIE_COMMANDS_VERSION = CANONICAL_SELFIE_VERSION
                mod.CELEBRITY_SELFIE_ROUTE = "v238-v219-ui-v236-isolated-real-faceswap-expression-crop"
                mod.AI_SELFIE_PROVIDER = "Gemini face-expression-only composition + Segmind/PiAPI isolated real FaceSwap"
            return ok

        compat_owner.patch_runtime = _v238_compat_patch
        _v238_compat_patch()

    _builder_flag = "_neyrobot_v238_authoritative_faceswap_builder_hooked"
    if not getattr(ApplicationBuilder, _builder_flag, False):
        _original_build = ApplicationBuilder.build

        def _build_with_v238(self, *args, **kwargs):
            app = _original_build(self, *args, **kwargs)
            _force_v238()
            selfie_google.bind_application(app)
            selfie_transfer.bind_application(app)
            _force_v238()
            return app

        ApplicationBuilder.build = _build_with_v238
        setattr(ApplicationBuilder, _builder_flag, True)

    selfie_google.install_async()
    _force_v238()

    runtime = selfie_google._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_STORAGE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_COMMANDS_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_ADMIN_VERSION = CANONICAL_SELFIE_VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v238-gemini-face-expression-crop-then-isolated-real-faceswap"
        runtime.AI_SELFIE_PROVIDER = "Gemini face-expression-only composition + Segmind/PiAPI isolated real FaceSwap"
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    print("[neyrobot-prod] V238 front-camera POV + face-expression-only source #3 + isolated FaceSwap installed", flush=True)
except Exception as exc:
    print(f"[neyrobot-prod] canonical selfie V238 warning: {type(exc).__name__}: {exc}", flush=True)
