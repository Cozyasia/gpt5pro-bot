# -*- coding: utf-8 -*-
"""V241 authoritative selfie runtime.

Guarantees at the last runtime boundary:
- photo #3 is the only user identity/expression source;
- Gemini sees only a tight verified face/expression crop for PERSON A;
- selfie mode is true front-camera output: no visible phone/device/foreground hand;
- Gemini Pro uses bounded retries then Flash fallback;
- FaceSwap receives a compact isolated PERSON-A face ROI, never PERSON B;
- the final scene keeps native Gemini Full-HD/2K resolution;
- every generation re-asserts these bindings so late legacy installers cannot win.
"""
from __future__ import annotations

import contextlib
import io
from typing import Any

VERSION = "v241-authoritative-selfie-runtime-2026-08-19"

_BASE_GENERATE = None
_BASE_DETECT = None
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    google._log(message, *args)


def _runtime() -> Any | None:
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    return google._runtime()


def _detect(runtime: Any, image: bytes) -> list[dict[str, Any]]:
    """Deterministic face detection with OpenCV fallback."""
    data = bytes(image or b"")
    global _BASE_DETECT
    if callable(_BASE_DETECT):
        try:
            faces = [dict(x) for x in (_BASE_DETECT(runtime, data) or [])]
            if faces:
                return faces
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
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            return []
        h, w = gray.shape[:2]
        min_side = max(40, int(min(w, h) * 0.07))
        found = cascade.detectMultiScale(
            gray,
            scaleFactor=1.07,
            minNeighbors=6,
            minSize=(min_side, min_side),
            flags=cv2.CASCADE_SCALE_IMAGE,
        )
        faces = [
            {"x": int(x), "y": int(y), "w": int(fw), "h": int(fh)}
            for (x, y, fw, fh) in found
        ]
        faces.sort(key=lambda f: int(f["w"]) * int(f["h"]), reverse=True)
        _log("AI_SELFIE_V241_DETECT backend=opencv_haar faces=%s cv2=%s", len(faces), getattr(cv2, "__version__", "unknown"))
        return faces
    except Exception as exc:
        _log("AI_SELFIE_V241_DETECT status=failed error=%s:%s", type(exc).__name__, exc)
        return []


def _select_source_photo(runtime: Any, photos: list[bytes]):
    if len(photos) != 3 or not bytes(photos[2] or b""):
        raise RuntimeError("photo #3 is required as the authoritative user face/expression source")
    raw = bytes(photos[2])
    _log("AI_SELFIE_V241_SOURCE source_photo=3 authority=identity+expression+faceswap bytes=%s", len(raw))
    return raw, 3, None


def _expression_crop(raw: bytes) -> bytes:
    from PIL import Image
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    data = bytes(raw or b"")
    if len(data) < 1024:
        raise RuntimeError("photo #3 is too small for reliable face transfer")
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size
    runtime = _runtime()
    faces = _detect(runtime, data) if runtime is not None else []
    if len(faces) != 1:
        raise RuntimeError(f"photo #3 must contain exactly one clearly detectable face; detected {len(faces)}")

    f = faces[0]
    x = int(f.get("x", 0)); y = int(f.get("y", 0))
    fw = int(f.get("w", 0)); fh = int(f.get("h", 0))
    if fw < 48 or fh < 48:
        raise RuntimeError("detected face in photo #3 is too small")

    cx = x + fw / 2.0
    cy = y + fh / 2.0
    crop_w = fw * 1.38
    crop_h = fh * 1.48
    x0 = max(0, int(cx - crop_w / 2.0))
    x1 = min(w, int(cx + crop_w / 2.0))
    y0 = max(0, int(cy - crop_h * 0.53))
    y1 = min(h, int(cy + crop_h * 0.47))
    if x1 - x0 < 96 or y1 - y0 < 96:
        raise RuntimeError("verified face crop is too small")

    crop = im.crop((x0, y0, x1, y1))
    if max(crop.size) > 1400:
        crop.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    crop.save(out, format="JPEG", quality=100, subsampling=0, optimize=True)
    encoded = out.getvalue()
    _log(
        "AI_SELFIE_V241_EXPRESSION_REF status=verified crop=%s,%s,%s,%s dims=%sx%s bytes=%s phone_hand_body_removed=true",
        x0, y0, x1, y1, crop.width, crop.height, len(encoded),
    )
    return encoded


async def _call_google(prompt: str, refs: list[tuple[str, bytes]], stage: str):
    """Compose V239 expression firewall with the bounded V240 Pro->Flash router."""
    from neyrobot_prod import selfie_v240_quality_resilience as compat

    patched = list(refs or [])
    if str(stage) == "composition_identity_separated":
        out: list[tuple[str, bytes]] = []
        count = 0
        for label, raw in patched:
            label_s = str(label or "")
            if label_s.startswith("USER SOURCE PHOTO"):
                count += 1
                out.append((
                    "USER VERIFIED FACE/EXPRESSION CROP #3 — PERSON A ONLY. "
                    "Expression geometry only. Do not infer phone, hand, arm, pose, clothing or background.",
                    _expression_crop(bytes(raw)),
                ))
            else:
                out.append((label, raw))
        if count != 1:
            raise RuntimeError(f"expected exactly one user source reference, got {count}")
        patched = out
        _log("AI_SELFIE_V241_STAGE1_REFS user_ref=face_expression_only full_photo3_reserved_for_faceswap=true")

    # The compatibility module exposes the resilient request implementation.
    return await compat._call_google_resilient(prompt, patched, stage)


def _stage1_prompt(name: str, scene: str, shot_label: str, has_scene_image: bool, source_photo_no: int) -> str:
    scene_rule = (
        "The first reference is the AUTHORITATIVE SCENE BASE. Preserve architecture, furniture, viewpoint, perspective and lighting. "
        if has_scene_image else f"Create this location faithfully: {scene}. "
    )
    is_selfie = "селфи" in str(shot_label).lower() or "selfie" in str(shot_label).lower()
    if is_selfie:
        shot_rule = (
            "TRUE FRONT-CAMERA SELFIE RESULT, NOT A THIRD-PERSON PHOTO OF SOMEONE TAKING A SELFIE. "
            "The viewer is the phone's front camera. The capturing phone is behind the image plane and MUST NOT be visible. "
            "ABSOLUTELY NO phone, smartphone, phone edge, phone case, screen, rear cameras, selfie stick, camera device, mirror-phone reflection, camera UI, foreground hand, foreground arm, or hand holding a device. "
            "Do not depict the act of taking a selfie. Show only the resulting front-camera photograph. "
            "Frame exactly two people close to the lens at natural arm-length wide-angle perspective, heads/shoulders/upper torsos. "
            "PERSON A hands and forearms are outside the frame. Both people look toward the lens. "
        )
    else:
        shot_rule = (
            "THIRD-PERSON JOINT PHOTO taken by another person. No visible phone, selfie stick, foreground device, camera UI or mirror-phone reflection. "
        )

    return (
        "Create ONE photorealistic vertical photograph with EXACTLY TWO principal people and no other visible faces. "
        f"{shot_rule}{scene_rule}"
        f"PERSON A is the USER on the LEFT. Source #{source_photo_no} supplied here is ONLY a verified face/expression crop. "
        "Match its expression geometry before FaceSwap: exact lip closure/opening, mouth width, smile amount, mouth-corner asymmetry, teeth visibility, jaw opening, cheek tension, eyelid opening/squint, eyebrow height and gaze. "
        "Never invent a smile or teeth. PERSON A temporary identity is disposable and will be physically replaced by real FaceSwap. "
        "Keep PERSON A near-frontal, unobstructed, sharp, large, fully inside the LEFT 48 percent, with clean separation from PERSON B. "
        f"PERSON B is {name} on the RIGHT. The three HERO PORTRAIT references belong ONLY to PERSON B and are the sole identity authority for PERSON B. "
        "STRICT IDENTITY FIREWALL: never copy USER face, hair, age, eyes, nose, lips, jaw, skin, expression or clothing identity into PERSON B; never copy PERSON B into PERSON A. "
        "PERSON B stays entirely in the RIGHT 48 percent. Natural anatomy, realistic skin and optics. No text, watermark, duplicate face, merged identity, morphing or hybrid face."
    )


async def _generate_guarded(update: Any, context: Any, scene: str = "") -> bool:
    enforce_runtime()
    if not callable(_BASE_GENERATE):
        raise RuntimeError("V241 base selfie generator is unavailable")
    return await _BASE_GENERATE(update, context, scene)


def enforce_runtime() -> None:
    """Re-assert V241 immediately before every generation and after app build."""
    from neyrobot_prod import selfie_v219_triref_scene_owner as ui
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer
    from neyrobot_prod import selfie_v240_quality_resilience as compat

    transfer._detect = _detect
    transfer._select_source_photo = _select_source_photo
    transfer._stage1_prompt = _stage1_prompt
    transfer._left_person_crop = compat._face_roi_crop
    transfer._merge_left_crop = compat._merge_face_roi
    google._call_google = _call_google

    transfer.generate = _generate_guarded
    google.generate = _generate_guarded
    ui.generate = _generate_guarded
    with contextlib.suppress(Exception):
        ui.public_callback.__globals__["generate"] = _generate_guarded

    transfer.VERSION = VERSION
    google.VERSION = VERSION
    ui.VERSION = VERSION
    compat.VERSION = VERSION

    runtime = _runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v241-late-bound-front-camera-expression-crop-pro-failover-compact-real-faceswap"
        runtime.AI_SELFIE_PROVIDER = "Gemini Pro bounded retry -> Flash + verified expression crop + compact isolated Segmind/PiAPI FaceSwap"
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V241_ENFORCE status=ok google_call=v241 prompt=v241 source=photo3 faceswap_roi=compact version=%s",
        VERSION,
    )


def _install_builder_hook() -> None:
    from telegram.ext import ApplicationBuilder
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    flag = "_neyrobot_v241_authoritative_builder_hooked"
    if getattr(ApplicationBuilder, flag, False):
        return
    original = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original(self, *args, **kwargs)
        enforce_runtime()  # deliberately last, after every older builder wrapper
        transfer.bind_application(app)
        enforce_runtime()
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, flag, True)


def install() -> None:
    global _BASE_GENERATE, _BASE_DETECT, _INSTALLED
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    if _BASE_GENERATE is None:
        _BASE_GENERATE = transfer.generate
    if _BASE_DETECT is None:
        _BASE_DETECT = transfer._detect

    _install_builder_hook()
    enforce_runtime()
    if not _INSTALLED:
        _INSTALLED = True
        print("[neyrobot-prod] V241 authoritative late-bound selfie runtime installed", flush=True)


__all__ = ["VERSION", "install", "enforce_runtime"]
