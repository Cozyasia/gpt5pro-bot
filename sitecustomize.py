# -*- coding: utf-8 -*-
"""Canonical V239 selfie runtime.

Rules:
- one generation owner only: Gemini composition -> isolated real FaceSwap;
- photo #3 is the deterministic user identity/expression source;
- Gemini sees only a verified face/expression crop, never the source phone/hand/body;
- selfie means the RESULT from a front camera, never a third-person shot of a phone;
- if a clean single face cannot be detected, fail closed instead of generating a
  synthetic approximation.
"""
from __future__ import annotations

import contextlib
import io

CANONICAL_SELFIE_VERSION = "v239-single-owner-front-camera-source-expression-2026-08-19"

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
    from neyrobot_prod import selfie_v218_runtime_owner as compat_owner

    # ------------------------------------------------------------------
    # 1) One deterministic source: photo #3.
    # ------------------------------------------------------------------
    def _v239_select_source_photo(runtime, photos):
        if len(photos) != 3 or not bytes(photos[2] or b""):
            raise RuntimeError("photo #3 is required as the authoritative face/expression source")
        raw = bytes(photos[2])
        selfie_transfer._log(
            "AI_SELFIE_V239_SOURCE source_photo=3 authority=identity+expression+faceswap bytes=%s",
            len(raw),
        )
        return raw, 3, None

    selfie_transfer._select_source_photo = _v239_select_source_photo

    # ------------------------------------------------------------------
    # 2) Deterministic face detector. First use the runtime detector; if the
    #    historical helper is broken, use pinned OpenCV 4.x Haar detection.
    # ------------------------------------------------------------------
    _legacy_detect = selfie_transfer._detect

    def _v239_detect(runtime, image):
        data = bytes(image or b"")
        try:
            faces = list(_legacy_detect(runtime, data) or [])
            if faces:
                return [dict(x) for x in faces]
        except Exception:
            pass

        try:
            import cv2
            import numpy as np

            buf = np.frombuffer(data, dtype=np.uint8)
            frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            if frame is None:
                return []
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            cascade = cv2.CascadeClassifier(cascade_path)
            if cascade.empty():
                return []
            h, w = gray.shape[:2]
            min_side = max(40, int(min(w, h) * 0.08))
            found = cascade.detectMultiScale(
                gray,
                scaleFactor=1.08,
                minNeighbors=6,
                minSize=(min_side, min_side),
                flags=cv2.CASCADE_SCALE_IMAGE,
            )
            result = [
                {"x": int(x), "y": int(y), "w": int(fw), "h": int(fh)}
                for (x, y, fw, fh) in found
            ]
            result.sort(key=lambda f: int(f["w"]) * int(f["h"]), reverse=True)
            selfie_transfer._log(
                "AI_SELFIE_V239_DETECT backend=opencv_haar faces=%s cv2=%s",
                len(result), getattr(cv2, "__version__", "unknown"),
            )
            return result
        except Exception as exc:
            selfie_transfer._log(
                "AI_SELFIE_V239_DETECT backend=opencv_haar status=failed error=%s:%s",
                type(exc).__name__, exc,
            )
            return []

    selfie_transfer._detect = _v239_detect

    # ------------------------------------------------------------------
    # 3) Face/expression-only reference for Gemini. NO fallback to original.
    #    If detection is ambiguous, fail closed; do not contaminate Gemini with
    #    a phone, hand, source pose or background.
    # ------------------------------------------------------------------
    def _v239_expression_crop(raw: bytes) -> bytes:
        from PIL import Image

        data = bytes(raw or b"")
        if len(data) < 1024:
            raise RuntimeError("photo #3 is too small for reliable face transfer")

        im = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = im.size
        runtime = selfie_transfer._runtime()
        faces = selfie_transfer._detect(runtime, data) if runtime is not None else []
        if len(faces) != 1:
            raise RuntimeError(
                f"photo #3 must contain exactly one clearly detectable face; detected {len(faces)}"
            )

        f = faces[0]
        x = int(f.get("x", 0)); y = int(f.get("y", 0))
        fw = int(f.get("w", 0)); fh = int(f.get("h", 0))
        if fw < 40 or fh < 40:
            raise RuntimeError("detected face in photo #3 is too small")

        cx = x + fw / 2.0
        cy = y + fh / 2.0
        crop_w = fw * 1.42
        crop_h = fh * 1.55
        x0 = max(0, int(cx - crop_w / 2.0))
        x1 = min(w, int(cx + crop_w / 2.0))
        y0 = max(0, int(cy - crop_h * 0.54))
        y1 = min(h, int(cy + crop_h * 0.46))
        if x1 - x0 < 80 or y1 - y0 < 80:
            raise RuntimeError("verified face crop is too small")

        crop = im.crop((x0, y0, x1, y1))
        if max(crop.size) > 1200:
            crop.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        crop.save(out, format="JPEG", quality=98, subsampling=0, optimize=True)
        encoded = out.getvalue()
        if len(encoded) < 1024:
            raise RuntimeError("verified face crop encoding failed")

        selfie_transfer._log(
            "AI_SELFIE_V239_EXPRESSION_REF status=verified crop=%s,%s,%s,%s dims=%sx%s bytes=%s phone_hand_body_removed=true",
            x0, y0, x1, y1, crop.width, crop.height, len(encoded),
        )
        return encoded

    # Intercept only Gemini Stage 1. Full photo #3 remains untouched for Segmind/PiAPI.
    _google_call = selfie_google._call_google

    async def _v239_call_google(prompt, refs, stage):
        if str(stage) == "composition_identity_separated":
            patched = []
            user_refs = 0
            for label, raw in list(refs or []):
                label_s = str(label or "")
                if label_s.startswith("USER SOURCE PHOTO"):
                    user_refs += 1
                    patched.append((
                        "USER VERIFIED FACE/EXPRESSION CROP #3 — PERSON A ONLY. "
                        "Use facial expression only; do not infer phone, hands, pose, clothing or background.",
                        _v239_expression_crop(bytes(raw)),
                    ))
                else:
                    patched.append((label, raw))
            if user_refs != 1:
                raise RuntimeError(f"expected exactly one user expression reference, got {user_refs}")
            refs = patched
            selfie_transfer._log(
                "AI_SELFIE_V239_STAGE1_REFS user_ref=verified_face_expression_only full_source_reserved_for_faceswap=true",
            )
        return await _google_call(prompt, refs, stage)

    selfie_google._call_google = _v239_call_google

    # ------------------------------------------------------------------
    # 4) Stage-1 composition contract. A selfie is the camera OUTPUT, not a shot
    #    of somebody holding a phone. Target expression must match source #3 so
    #    FaceSwap inherits the same mouth/eyes/cheeks instead of a new smile.
    # ------------------------------------------------------------------
    def _v239_stage1_prompt(name, scene, shot_label, has_scene_image, source_photo_no):
        scene_rule = (
            "The first reference is the AUTHORITATIVE SCENE BASE. Preserve architecture, furniture, viewpoint, perspective and lighting. "
            if has_scene_image else
            f"Create this location faithfully: {scene}. "
        )
        is_selfie = "Селфи" in str(shot_label) or "selfie" in str(shot_label).lower()
        if is_selfie:
            shot_rule = (
                "TRUE FRONT-CAMERA SELFIE OUTPUT. The viewer IS the front camera. "
                "Never show the capturing device because it is behind the image plane. "
                "NO phone, phone edge, phone case, screen, camera, selfie stick, mirror reflection, hand holding a device, foreground hand, or camera UI. "
                "Do not illustrate the act of taking a selfie. Produce only the resulting front-camera photograph. "
                "Frame both people close at arm-length perspective: heads, shoulders and upper torsos only. PERSON A hands and forearms must be outside the frame. "
                "Both people look toward the lens. Use mild natural smartphone wide-angle perspective. "
            )
        else:
            shot_rule = (
                "THIRD-PERSON JOINT PHOTO taken by another person. No phone, selfie stick, mirror-phone reflection, foreground device or camera UI. "
            )

        return (
            "Create ONE photorealistic vertical photograph with EXACTLY TWO principal people and no other visible faces. "
            f"{shot_rule}{scene_rule}"
            f"PERSON A is the USER on the LEFT. USER source #{source_photo_no} supplied to this stage is a VERIFIED FACE/EXPRESSION CROP only. "
            "Its purpose is TARGET EXPRESSION GEOMETRY, not identity generation and not pose. "
            "Match the source expression closely BEFORE FaceSwap: exact lip closure/opening, mouth width, smile amount, mouth-corner asymmetry, teeth visibility, jaw opening, cheek tension, eyelid opening/squint, eyebrow height and gaze. "
            "Do not invent a smile. Do not show teeth unless visible in the source crop. Keep PERSON A near-frontal, unobstructed, sharp, large, and entirely inside the LEFT 48 percent. "
            "PERSON A temporary facial identity is disposable and will be physically replaced by real FaceSwap. "
            f"PERSON B is {name} on the RIGHT. The three HERO PORTRAIT references belong ONLY to PERSON B and are the sole identity authority for PERSON B. "
            "STRICT IDENTITY FIREWALL: never copy USER age, facial geometry, hair, eyes, nose, lips, jaw, skin, expression or clothing identity into PERSON B; never copy PERSON B into PERSON A. "
            "Keep the two heads horizontally separated with visible space. PERSON B stays entirely in the RIGHT 48 percent. "
            "Natural anatomy, realistic skin and optics. No text, watermark, duplicated face, merged identity, morphing or hybrid face."
        )

    selfie_transfer._stage1_prompt = _v239_stage1_prompt

    # ------------------------------------------------------------------
    # 5) Single owner. Disable every legacy repair/generation route permanently.
    # ------------------------------------------------------------------
    def _legacy_noop(*args, **kwargs):
        return True

    with contextlib.suppress(Exception):
        selfie_ui.patch_runtime()
    selfie_ui.patch_runtime = _legacy_noop
    selfie_ui.bind_runtime_apps = lambda *args, **kwargs: 0
    selfie_ui.install_builder_hook = _legacy_noop
    selfie_ui.install_async = lambda *args, **kwargs: None
    selfie_ui.install = lambda *args, **kwargs: None

    compat_owner.VERSION = CANONICAL_SELFIE_VERSION
    with contextlib.suppress(Exception):
        compat_owner.patch_runtime()

    selfie_transfer.VERSION = CANONICAL_SELFIE_VERSION
    selfie_google.VERSION = CANONICAL_SELFIE_VERSION
    selfie_ui.VERSION = CANONICAL_SELFIE_VERSION

    async def _disabled_comet_route(*args, **kwargs):
        raise RuntimeError("Legacy Comet selfie generation is disabled by V239")

    def _force_v239() -> None:
        selfie_google.generate = selfie_transfer.generate
        selfie_ui.generate = selfie_transfer.generate
        with contextlib.suppress(Exception):
            selfie_ui.public_callback.__globals__["generate"] = selfie_transfer.generate
        selfie_ui._comet_generate = _disabled_comet_route
        with contextlib.suppress(Exception):
            selfie_ui.public_callback.__globals__["_comet_generate"] = _disabled_comet_route
        selfie_transfer.install()

    _force_v239()

    _builder_flag = "_neyrobot_v239_single_owner_builder_hooked"
    if not getattr(ApplicationBuilder, _builder_flag, False):
        _original_build = ApplicationBuilder.build

        def _build_with_v239(self, *args, **kwargs):
            app = _original_build(self, *args, **kwargs)
            _force_v239()
            selfie_transfer.bind_application(app)
            _force_v239()
            return app

        ApplicationBuilder.build = _build_with_v239
        setattr(ApplicationBuilder, _builder_flag, True)

    selfie_transfer.install_async()
    _force_v239()

    runtime = selfie_google._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_STORAGE_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_COMMANDS_VERSION = CANONICAL_SELFIE_VERSION
        runtime.SELFIE_ADMIN_VERSION = CANONICAL_SELFIE_VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v239-single-owner-front-camera-verified-expression-then-isolated-real-faceswap"
        runtime.AI_SELFIE_PROVIDER = "Gemini verified face-expression composition + isolated Segmind/PiAPI real FaceSwap"
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    print(
        "[neyrobot-prod] V239 single owner installed: verified expression crop + true front-camera POV + isolated real FaceSwap",
        flush=True,
    )
except Exception as exc:
    print(f"[neyrobot-prod] canonical selfie V239 warning: {type(exc).__name__}: {exc}", flush=True)

# V240 is an internal overlay only: it does not register callbacks or replace the
# V239 single owner. It adds bounded Pro->Flash failover and a compact isolated
# FaceSwap ROI to improve facial detail while preserving source #3 expression.
try:
    from neyrobot_prod.selfie_v240_quality_resilience import install as install_v240_quality
    install_v240_quality()
except Exception as exc:
    print(f"[neyrobot-prod] V240 quality overlay warning: {type(exc).__name__}: {exc}", flush=True)
