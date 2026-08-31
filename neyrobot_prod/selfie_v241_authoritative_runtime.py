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

import asyncio
import contextlib
import io
import os
import time
from typing import Any

VERSION = "v241-authoritative-selfie-runtime-2026-08-19"

_BASE_GENERATE = None
_BASE_DETECT = None
_INSTALLED = False
_PRO_CIRCUIT_OPEN_UNTIL = 0.0
_PRO_FAILURES = 0


def _log(message: str, *args: Any) -> None:
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    google._log(message, *args)


def _runtime() -> Any | None:
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    return google._runtime()


def _detect(runtime: Any, image: bytes) -> list[dict[str, Any]]:
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


def _model_order() -> list[str]:
    raw = (os.environ.get("GEMINI_SELFIE_MODELS") or "gemini-3-pro-image,gemini-3.1-flash-image").strip()
    models = [x.strip() for x in raw.split(",") if x.strip()]
    return models or ["gemini-3-pro-image", "gemini-3.1-flash-image"]


def _is_transient_status(status: int) -> bool:
    return status in {408, 429, 500, 502, 503, 504}


async def _google_request(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str):
    """Bounded Pro retry with immediate Flash fallback on temporary provider failures."""
    global _PRO_CIRCUIT_OPEN_UNTIL, _PRO_FAILURES

    import httpx
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as extractor
    from neyrobot_prod import selfie_v229_canonical_two_stage as google

    key = google._key()
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY is missing")

    prepared = [(label, *google._prepare(raw)) for label, raw in labeled_images]
    timeout_s = max(60.0, min(120.0, float(os.environ.get("GEMINI_SELFIE_REQUEST_TIMEOUT_S", "90") or 90)))
    timeout = httpx.Timeout(timeout_s, connect=30.0, read=timeout_s, write=90.0, pool=30.0)
    headers = {"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
    errors: list[str] = []

    models = _model_order()
    if _PRO_CIRCUIT_OPEN_UNTIL > time.monotonic():
        models = [m for m in models if "pro" not in m.lower()] + [m for m in models if "pro" in m.lower()]
        _log("AI_SELFIE_V241_CIRCUIT state=open route=%s", ",".join(models))

    _log("AI_SELFIE_V241_STAGE_START stage=%s models=%s refs=%s timeout=%.0fs pro_attempts=1 circuit_seconds=300", stage, ",".join(models), len(labeled_images), timeout_s)

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        for model in models:
            is_pro = "pro" in model.lower()
            if is_pro and _PRO_CIRCUIT_OPEN_UNTIL > time.monotonic():
                continue
            # One bounded Pro attempt preserves preferred quality without a second long stall.
            # A transient failure opens the existing circuit and immediately routes to Flash.
            max_attempts = 1
            for attempt in range(1, max_attempts + 1):
                parts: list[dict[str, Any]] = [{"text": prompt}]
                for label, data, mime in prepared:
                    parts.append({"text": label})
                    parts.append(google._inline(data, mime))
                config = {
                    "responseModalities": ["TEXT", "IMAGE"],
                    "imageConfig": {
                        "aspectRatio": base._aspect_ratio(),
                        "imageSize": os.environ.get("GEMINI_SELFIE_IMAGE_SIZE", "2K"),
                    },
                }
                payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
                started = time.monotonic()
                try:
                    response = await client.post(
                        f"{google._base_url()}/models/{model}:generateContent",
                        headers=headers,
                        json=payload,
                    )
                    elapsed = time.monotonic() - started
                    status = int(response.status_code)
                    _log("AI_SELFIE_V241_PROVIDER stage=%s model=%s attempt=%s status=%s elapsed=%.2fs", stage, model, attempt, status, elapsed)
                    if status >= 400:
                        errors.append(f"{stage}/{model}/attempt{attempt}: HTTP {status}: {response.text[:350]}")
                        if is_pro and _is_transient_status(status):
                            _PRO_FAILURES += 1
                            if attempt < max_attempts:
                                await asyncio.sleep(1.5 * attempt)
                                continue
                            _PRO_CIRCUIT_OPEN_UNTIL = time.monotonic() + 300.0
                        break

                    output = extractor._extract_final_image(response.json())
                    if output and len(output) > 1024:
                        if is_pro:
                            _PRO_FAILURES = 0
                            _PRO_CIRCUIT_OPEN_UNTIL = 0.0
                        runtime = _runtime()
                        if runtime is not None:
                            runtime.AI_SELFIE_LAST_PROVIDER = "google_gemini_direct_v241"
                            runtime.AI_SELFIE_LAST_MODEL = model
                            runtime.AI_SELFIE_LAST_IMAGE_SIZE = os.environ.get("GEMINI_SELFIE_IMAGE_SIZE", "2K")
                            runtime.AI_SELFIE_LAST_STAGE = stage
                        _log("AI_SELFIE_V241_STAGE_SUCCESS stage=%s model=%s attempt=%s refs=%s bytes=%s elapsed=%.2fs", stage, model, attempt, len(labeled_images), len(output), elapsed)
                        return output, model
                    errors.append(f"{stage}/{model}/attempt{attempt}: response contained no final image")
                    break
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    elapsed = time.monotonic() - started
                    errors.append(f"{stage}/{model}/attempt{attempt}: {type(exc).__name__}: {exc}")
                    _log("AI_SELFIE_V241_PROVIDER stage=%s model=%s attempt=%s status=transport_error elapsed=%.2fs", stage, model, attempt, elapsed)
                    if is_pro:
                        _PRO_FAILURES += 1
                        if attempt < max_attempts:
                            await asyncio.sleep(1.5 * attempt)
                            continue
                        _PRO_CIRCUIT_OPEN_UNTIL = time.monotonic() + 300.0
                    break
                except Exception as exc:
                    errors.append(f"{stage}/{model}/attempt{attempt}: {type(exc).__name__}: {exc}")
                    break

    raise RuntimeError("Google Gemini V241 route failed: " + " | ".join(errors[-6:]))


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
    return await _google_request(prompt, patched, stage)


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
        f"PERSON A is the USER on the LEFT. Source #{source_photo_no} supplied here is ONLY a verified face/expression crop. "
        "Match its expression geometry before FaceSwap: exact lip closure/opening, mouth width, smile amount, mouth-corner asymmetry, teeth visibility, jaw opening, cheek tension, eyelid opening/squint, eyebrow height and gaze. "
        "GEOMETRY COMPATIBILITY FOR PERSON A: preserve the verified crop's normalized five-point scaffold and facial proportions — interocular distance relative to face width, eye-line tilt, eye-to-nose distance, nose-to-mouth distance, mouth-corner spacing, nose width/length and lower-face/chin placement. Do not widen, narrow, stretch or stylize the face scaffold. "
        "Never invent a smile or teeth. PERSON A temporary texture/identity is disposable and will be physically replaced, but its landmark geometry must remain source-compatible. "
        "Keep PERSON A near-frontal, unobstructed, sharp, large, fully inside the LEFT 48 percent, with clean separation from PERSON B. "
        f"PERSON B is {name} on the RIGHT. The three HERO PORTRAIT references belong ONLY to PERSON B and are the sole identity authority for PERSON B. "
        "STRICT IDENTITY FIREWALL: never copy USER face, hair, age, eyes, nose, lips, jaw, skin, expression or clothing identity into PERSON B; never copy PERSON B into PERSON A. "
        "PERSON B stays entirely in the RIGHT 48 percent. Natural anatomy, realistic skin and optics. No text, watermark, duplicate face, merged identity, morphing or hybrid face."
    )


def _face_roi_crop(image: bytes):
    """Compact PERSON-A head/shoulder crop to maximize provider pixels per face."""
    from PIL import Image
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    im = Image.open(io.BytesIO(bytes(image))).convert("RGB")
    w, h = im.size
    runtime = _runtime()
    faces = _detect(runtime, bytes(image)) if runtime is not None else []
    candidates = []
    for f in faces:
        try:
            x = int(f.get("x", 0)); y = int(f.get("y", 0))
            fw = int(f.get("w", 0)); fh = int(f.get("h", 0))
            cx = x + fw / 2.0
            if fw >= 48 and fh >= 48 and cx < w * 0.55:
                candidates.append((fw * fh, x, y, fw, fh))
        except Exception:
            continue

    if not candidates:
        raise RuntimeError("V241 could not locate PERSON A face for compact FaceSwap ROI")

    _, x, y, fw, fh = max(candidates, key=lambda t: t[0])
    cx = x + fw / 2.0
    cy = y + fh / 2.0
    roi_w = max(360.0, fw * 2.35)
    roi_h = max(440.0, fh * 2.70)
    x0 = max(0, int(cx - roi_w * 0.50))
    x1 = min(int(w * 0.54), int(cx + roi_w * 0.50))
    y0 = max(0, int(cy - roi_h * 0.43))
    y1 = min(h, int(cy + roi_h * 0.57))
    if x1 - x0 < 300 or y1 - y0 < 360:
        raise RuntimeError("V241 compact FaceSwap ROI is too small")

    crop = im.crop((x0, y0, x1, y1))
    out = io.BytesIO()
    crop.save(out, format="JPEG", quality=100, subsampling=0, optimize=True)
    data = out.getvalue()
    _log("AI_SELFIE_V241_FACE_ROI status=compact box=%s,%s,%s,%s face=%s,%s,%s,%s crop=%sx%s base=%sx%s", x0, y0, x1, y1, x, y, fw, fh, crop.width, crop.height, w, h)
    return data, (x0, y0, x1, y1)


def _merge_face_roi(base: bytes, swapped_crop: bytes, box):
    from PIL import Image, ImageDraw, ImageFilter

    base_im = Image.open(io.BytesIO(bytes(base))).convert("RGB")
    crop_im = Image.open(io.BytesIO(bytes(swapped_crop))).convert("RGB")
    x0, y0, x1, y1 = box
    cw, ch = x1 - x0, y1 - y0
    provider_size = crop_im.size
    if crop_im.size != (cw, ch):
        crop_im = crop_im.resize((cw, ch), Image.Resampling.LANCZOS)
        crop_im = crop_im.filter(ImageFilter.UnsharpMask(radius=0.55, percent=45, threshold=4))

    feather = max(10, min(30, int(min(cw, ch) * 0.03)))
    mask = Image.new("L", (cw, ch), 0)
    draw = ImageDraw.Draw(mask)
    inset = max(8, feather)
    draw.rectangle((inset, inset, max(inset + 1, cw - inset - 1), max(inset + 1, ch - inset - 1)), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))
    base_im.paste(crop_im, (x0, y0), mask)

    out = io.BytesIO()
    base_im.save(out, format="JPEG", quality=98, subsampling=0, optimize=True)
    _log("AI_SELFIE_V241_MERGE provider_crop=%sx%s roi=%sx%s base=%sx%s feather=%s native_resolution=true", provider_size[0], provider_size[1], cw, ch, base_im.width, base_im.height, feather)
    return out.getvalue()


async def _generate_guarded(update: Any, context: Any, scene: str = "") -> bool:
    enforce_runtime()
    if not callable(_BASE_GENERATE):
        raise RuntimeError("V241 base selfie generator is unavailable")
    return await _BASE_GENERATE(update, context, scene)


def enforce_runtime() -> None:
    from neyrobot_prod import selfie_v219_triref_scene_owner as ui
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    transfer._detect = _detect
    transfer._select_source_photo = _select_source_photo
    transfer._stage1_prompt = _stage1_prompt
    transfer._left_person_crop = _face_roi_crop
    transfer._merge_left_crop = _merge_face_roi
    google._call_google = _call_google

    transfer.generate = _generate_guarded
    google.generate = _generate_guarded
    ui.generate = _generate_guarded
    with contextlib.suppress(Exception):
        ui.public_callback.__globals__["generate"] = _generate_guarded

    transfer.VERSION = VERSION
    google.VERSION = VERSION
    ui.VERSION = VERSION

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

    _log("AI_SELFIE_V241_ENFORCE status=ok google_call=v241 prompt=v241 source=photo3 faceswap_roi=compact version=%s", VERSION)


def _install_builder_hook() -> None:
    from telegram.ext import ApplicationBuilder
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    flag = "_neyrobot_v241_authoritative_builder_hooked"
    if getattr(ApplicationBuilder, flag, False):
        return
    original = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original(self, *args, **kwargs)
        enforce_runtime()
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
