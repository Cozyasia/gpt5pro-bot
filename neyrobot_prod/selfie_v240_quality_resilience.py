# -*- coding: utf-8 -*-
"""V240 reliability/quality overlay for the canonical V239 selfie owner.

This module deliberately does not own Telegram callbacks. It only patches two
internal boundaries of the already-stable V239 pipeline:

1. Gemini stage-1 routing: Pro gets at most two attempts on transient 5xx/timeout
   failures, then Flash is used immediately. Repeated Pro capacity failures open
   a short in-process circuit breaker so subsequent requests do not waste minutes
   retrying a temporarily unavailable Pro endpoint.
2. Real FaceSwap target: feed the provider a compact, face-centred PERSON-A ROI
   instead of the whole left half of the 2K frame. This increases pixels-per-face
   at the provider's fixed output envelope, while the final merge remains at the
   untouched Gemini 2K resolution and PERSON B is never sent to FaceSwap.

Identity/expression authority is unchanged: source photo #3 remains authoritative.
"""
from __future__ import annotations

import asyncio
import io
import os
import time
from typing import Any

VERSION = "v240-pro-fast-fail-face-roi-2026-08-19"

_PRO_CIRCUIT_OPEN_UNTIL = 0.0
_PRO_FAILURES = 0
_ORIGINAL_LEFT_PERSON_CROP = None


def _log(message: str, *args: Any) -> None:
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    v229._log(message, *args)


def _is_transient_status(status: int) -> bool:
    return status in {408, 429, 500, 502, 503, 504}


def _model_order() -> list[str]:
    raw = (os.environ.get("GEMINI_SELFIE_MODELS") or "gemini-3-pro-image,gemini-3.1-flash-image").strip()
    models = [x.strip() for x in raw.split(",") if x.strip()]
    if not models:
        models = ["gemini-3-pro-image", "gemini-3.1-flash-image"]
    return models


def _verified_expression_crop(raw: bytes) -> bytes:
    """V239-compatible face/expression-only crop. Never pass phone/hand/body to Gemini."""
    from PIL import Image
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    data = bytes(raw or b"")
    if len(data) < 1024:
        raise RuntimeError("photo #3 is too small for reliable expression reference")

    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size
    runtime = transfer._runtime()
    faces = transfer._detect(runtime, data) if runtime is not None else []
    if len(faces) != 1:
        raise RuntimeError(f"photo #3 must contain exactly one clearly detectable face; detected {len(faces)}")

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

    _log(
        "AI_SELFIE_V240_EXPRESSION_REF status=verified crop=%s,%s,%s,%s dims=%sx%s bytes=%s phone_hand_body_removed=true",
        x0, y0, x1, y1, crop.width, crop.height, len(encoded),
    )
    return encoded


def _prepare_stage_refs(labeled_images: list[tuple[str, bytes]], stage: str) -> list[tuple[str, bytes]]:
    refs = list(labeled_images or [])
    if str(stage) != "composition_identity_separated":
        return refs

    patched: list[tuple[str, bytes]] = []
    user_refs = 0
    for label, raw in refs:
        label_s = str(label or "")
        if label_s.startswith("USER SOURCE PHOTO"):
            user_refs += 1
            patched.append((
                "USER VERIFIED FACE/EXPRESSION CROP #3 — PERSON A ONLY. Use facial expression only; do not infer phone, hands, pose, clothing or background.",
                _verified_expression_crop(bytes(raw)),
            ))
        else:
            patched.append((label, bytes(raw)))
    if user_refs != 1:
        raise RuntimeError(f"expected exactly one user expression reference, got {user_refs}")
    _log("AI_SELFIE_V240_STAGE1_REFS user_ref=verified_face_expression_only full_source_reserved_for_faceswap=true")
    return patched


async def _call_google_resilient(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    """Bounded Gemini routing with 503 fast-fail and a short Pro circuit breaker."""
    global _PRO_CIRCUIT_OPEN_UNTIL, _PRO_FAILURES

    import httpx
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as extractor
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229

    key = v229._key()
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY is missing")

    safe_refs = _prepare_stage_refs(labeled_images, stage)
    prepared = [(label, *v229._prepare(raw)) for label, raw in safe_refs]
    request_timeout_s = max(75.0, min(150.0, float(os.environ.get("GEMINI_SELFIE_REQUEST_TIMEOUT_S", "120") or 120)))
    timeout = httpx.Timeout(request_timeout_s, connect=30.0, read=request_timeout_s, write=90.0, pool=30.0)
    headers = {"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
    errors: list[str] = []

    now = time.monotonic()
    models = _model_order()
    if _PRO_CIRCUIT_OPEN_UNTIL > now:
        models = [m for m in models if "pro" not in m.lower()] + [m for m in models if "pro" in m.lower()]
        _log(
            "AI_SELFIE_V240_CIRCUIT state=open remaining=%.1fs route=%s",
            _PRO_CIRCUIT_OPEN_UNTIL - now, ",".join(models),
        )

    _log(
        "AI_SELFIE_V240_STAGE_START stage=%s models=%s refs=%s timeout=%.0fs",
        stage, ",".join(models), len(safe_refs), request_timeout_s,
    )

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        for model in models:
            is_pro = "pro" in model.lower()
            if is_pro and _PRO_CIRCUIT_OPEN_UNTIL > time.monotonic():
                continue

            max_attempts = 2 if is_pro else 1
            for attempt in range(1, max_attempts + 1):
                parts: list[dict[str, Any]] = [{"text": prompt}]
                for label, data, mime in prepared:
                    parts.append({"text": label})
                    parts.append(v229._inline(data, mime))
                config: dict[str, Any] = {
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
                        f"{v229._base_url()}/models/{model}:generateContent",
                        headers=headers,
                        json=payload,
                    )
                    elapsed = time.monotonic() - started
                    status = int(response.status_code)
                    if status >= 400:
                        errors.append(f"{stage}/{model}/attempt{attempt}: HTTP {status}: {response.text[:350]}")
                        _log(
                            "AI_SELFIE_V240_PROVIDER stage=%s model=%s attempt=%s status=%s elapsed=%.2fs",
                            stage, model, attempt, status, elapsed,
                        )
                        if is_pro and _is_transient_status(status):
                            _PRO_FAILURES += 1
                            if attempt < max_attempts:
                                await asyncio.sleep(1.5 * attempt)
                                continue
                            _PRO_CIRCUIT_OPEN_UNTIL = time.monotonic() + 300.0
                            _log("AI_SELFIE_V240_CIRCUIT state=opened duration=300s failures=%s", _PRO_FAILURES)
                        break

                    output = extractor._extract_final_image(response.json())
                    if output and len(output) > 1024:
                        if is_pro:
                            _PRO_FAILURES = 0
                            _PRO_CIRCUIT_OPEN_UNTIL = 0.0
                        runtime = v229._runtime()
                        if runtime is not None:
                            runtime.AI_SELFIE_LAST_PROVIDER = "google_gemini_direct_v240"
                            runtime.AI_SELFIE_LAST_MODEL = model
                            runtime.AI_SELFIE_LAST_IMAGE_SIZE = os.environ.get("GEMINI_SELFIE_IMAGE_SIZE", "2K")
                            runtime.AI_SELFIE_LAST_STAGE = stage
                        _log(
                            "AI_SELFIE_V240_STAGE_SUCCESS stage=%s model=%s attempt=%s refs=%s bytes=%s elapsed=%.2fs",
                            stage, model, attempt, len(safe_refs), len(output), elapsed,
                        )
                        return output, model

                    errors.append(f"{stage}/{model}/attempt{attempt}: response contained no final image")
                    break

                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    elapsed = time.monotonic() - started
                    errors.append(f"{stage}/{model}/attempt{attempt}: {type(exc).__name__}: {exc}")
                    _log(
                        "AI_SELFIE_V240_PROVIDER stage=%s model=%s attempt=%s status=transport_error elapsed=%.2fs error=%s",
                        stage, model, attempt, elapsed, type(exc).__name__,
                    )
                    if is_pro:
                        _PRO_FAILURES += 1
                        if attempt < max_attempts:
                            await asyncio.sleep(1.5 * attempt)
                            continue
                        _PRO_CIRCUIT_OPEN_UNTIL = time.monotonic() + 300.0
                        _log("AI_SELFIE_V240_CIRCUIT state=opened duration=300s failures=%s", _PRO_FAILURES)
                    break
                except Exception as exc:
                    errors.append(f"{stage}/{model}/attempt{attempt}: {type(exc).__name__}: {exc}")
                    break

    raise RuntimeError("Google Gemini V240 route failed: " + " | ".join(errors[-6:]))


def _face_roi_crop(image: bytes) -> tuple[bytes, tuple[int, int, int, int]]:
    """Return a compact PERSON-A head/shoulder ROI to maximize FaceSwap face resolution."""
    from PIL import Image
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    im = Image.open(io.BytesIO(bytes(image))).convert("RGB")
    w, h = im.size
    runtime = transfer._runtime()
    faces = transfer._detect(runtime, bytes(image)) if runtime is not None else []

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
        _log("AI_SELFIE_V240_FACE_ROI status=fallback reason=no_left_face")
        return _ORIGINAL_LEFT_PERSON_CROP(bytes(image))

    _, x, y, fw, fh = max(candidates, key=lambda t: t[0])
    cx = x + fw / 2.0
    cy = y + fh / 2.0

    roi_w = max(360.0, fw * 2.45)
    roi_h = max(440.0, fh * 2.85)
    x0 = max(0, int(cx - roi_w * 0.50))
    x1 = min(int(w * 0.55), int(cx + roi_w * 0.50))
    y0 = max(0, int(cy - roi_h * 0.43))
    y1 = min(h, int(cy + roi_h * 0.57))

    if x1 - x0 < 300 or y1 - y0 < 360:
        _log("AI_SELFIE_V240_FACE_ROI status=fallback reason=roi_too_small")
        return _ORIGINAL_LEFT_PERSON_CROP(bytes(image))

    crop = im.crop((x0, y0, x1, y1))
    out = io.BytesIO()
    crop.save(out, format="JPEG", quality=100, subsampling=0, optimize=True)
    data = out.getvalue()
    _log(
        "AI_SELFIE_V240_FACE_ROI status=compact box=%s,%s,%s,%s face=%s,%s,%s,%s crop=%sx%s base=%sx%s",
        x0, y0, x1, y1, x, y, fw, fh, crop.width, crop.height, w, h,
    )
    return data, (x0, y0, x1, y1)


def _merge_face_roi(base: bytes, swapped_crop: bytes, box: tuple[int, int, int, int]) -> bytes:
    """Merge compact swapped ROI with a real feathered edge, preserving native 2K."""
    from PIL import Image, ImageDraw, ImageFilter

    base_im = Image.open(io.BytesIO(bytes(base))).convert("RGB")
    crop_im = Image.open(io.BytesIO(bytes(swapped_crop))).convert("RGB")
    x0, y0, x1, y1 = box
    cw, ch = x1 - x0, y1 - y0
    provider_size = crop_im.size

    if crop_im.size != (cw, ch):
        crop_im = crop_im.resize((cw, ch), Image.Resampling.LANCZOS)
        crop_im = crop_im.filter(ImageFilter.UnsharpMask(radius=0.65, percent=55, threshold=4))

    feather = max(12, min(34, int(min(cw, ch) * 0.035)))
    mask = Image.new("L", (cw, ch), 0)
    draw = ImageDraw.Draw(mask)
    inset = max(8, feather)
    draw.rectangle((inset, inset, max(inset + 1, cw - inset - 1), max(inset + 1, ch - inset - 1)), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))
    base_im.paste(crop_im, (x0, y0), mask)

    out = io.BytesIO()
    base_im.save(out, format="JPEG", quality=98, subsampling=0, optimize=True)
    _log(
        "AI_SELFIE_V240_MERGE provider_crop=%sx%s roi=%sx%s base=%sx%s feather=%s native_resolution=true",
        provider_size[0], provider_size[1], cw, ch, base_im.width, base_im.height, feather,
    )
    return out.getvalue()


def install() -> None:
    """Install overlay once after V239 has established the canonical owner."""
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    global _ORIGINAL_LEFT_PERSON_CROP

    if getattr(transfer, "_neyrobot_v240_quality_installed", False):
        return

    _ORIGINAL_LEFT_PERSON_CROP = transfer._left_person_crop
    google._call_google = _call_google_resilient
    transfer._left_person_crop = _face_roi_crop
    transfer._merge_left_crop = _merge_face_roi

    google.VERSION = VERSION
    transfer.VERSION = VERSION
    runtime = google._runtime()
    if runtime is not None:
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v240-v239-single-owner-pro-fast-fail-compact-face-roi-isolated-real-faceswap"
        runtime.AI_SELFIE_PROVIDER = "Gemini Pro bounded retry -> Flash fallback + compact isolated Segmind/PiAPI FaceSwap"

    setattr(transfer, "_neyrobot_v240_quality_installed", True)
    print("[neyrobot-prod] V240 quality/resilience overlay installed", flush=True)
