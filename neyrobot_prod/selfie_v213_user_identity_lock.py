# -*- coding: utf-8 -*-
"""V213 user-identity lock for Celebrity Selfie.

The five-reference V208 route already labels two user images and three hero
images correctly. Production tests showed an asymmetry, though: hero packs are
usually tight, high-quality portraits while users often upload ordinary
waist-up or full-body photos where the face occupies few pixels. Gemini then
preserves body type, hair and general appearance but invents a generic face.

V213 keeps both original user photos for proportions and appearance, derives a
tight face crop from each one, and sends a balanced seven-reference request:

1. user full photo A
2. user face crop A
3. user full photo B
4. user face crop B
5-7. three hero references

The scene prompt makes the close crops authoritative for facial identity and
the full photos authoritative for body type, hair and apparent age.
"""
from __future__ import annotations

import contextlib
import os
import sys
from io import BytesIO
from typing import Any

VERSION = "v213-selfie-user-identity-lock-2026-07-26"


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _log(label: str, exc: BaseException) -> None:
    runtime = _runtime_module()
    logger = getattr(runtime, "log", None) if runtime is not None else None
    if logger is not None:
        with contextlib.suppress(Exception):
            logger.exception("%s: %s", label, exc)
            return
    print(f"[neyrobot-prod] {label}: {type(exc).__name__}: {exc}")


def _jpeg_bytes(image: Any, *, max_side: int = 1280, quality: int = 95) -> bytes:
    from PIL import Image

    image = image.convert("RGB")
    if max_side > 0 and max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.LANCZOS)
    output = BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=max(80, min(96, int(quality))),
        optimize=True,
        progressive=True,
    )
    return output.getvalue()


def _largest_face_box(image: Any) -> tuple[int, int, int, int] | None:
    """Return the largest OpenCV face box in original-image coordinates."""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        from PIL import Image

        rgb = image.convert("RGB")
        width, height = rgb.size
        scale = min(1.0, 1200.0 / float(max(width, height)))
        detector_image = rgb
        if scale < 1.0:
            detector_image = rgb.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.LANCZOS,
            )
        gray = cv2.cvtColor(np.array(detector_image), cv2.COLOR_RGB2GRAY)
        cascade_path = os.path.join(
            cv2.data.haarcascades,
            "haarcascade_frontalface_default.xml",
        )
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            return None
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.07,
            minNeighbors=5,
            minSize=(48, 48),
        )
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda box: int(box[2]) * int(box[3]))
        inverse = 1.0 / scale
        return (
            int(round(float(x) * inverse)),
            int(round(float(y) * inverse)),
            int(round(float(w) * inverse)),
            int(round(float(h) * inverse)),
        )
    except Exception:
        return None


def _expanded_face_crop(image: Any, box: tuple[int, int, int, int]) -> Any:
    """Include hair, jaw and some shoulders while keeping the face dominant."""
    x, y, w, h = box
    width, height = image.size
    center_x = x + w / 2.0
    center_y = y + h / 2.0 - h * 0.08
    crop_w = max(w * 2.35, h * 1.95)
    crop_h = max(h * 2.75, w * 2.20)

    left = max(0, int(round(center_x - crop_w / 2.0)))
    top = max(0, int(round(center_y - crop_h * 0.43)))
    right = min(width, int(round(center_x + crop_w / 2.0)))
    bottom = min(height, int(round(top + crop_h)))

    if right - left < 128 or bottom - top < 128:
        raise ValueError("detected face crop is too small")
    return image.crop((left, top, right, bottom))


def _fallback_portrait_crop(image: Any) -> Any:
    """Conservative upper-centre fallback used only when face detection fails."""
    width, height = image.size
    if height >= width:
        left = int(width * 0.12)
        right = int(width * 0.88)
        top = 0
        bottom = min(height, int(height * 0.68))
    else:
        left = int(width * 0.20)
        right = int(width * 0.80)
        top = 0
        bottom = min(height, int(height * 0.88))
    return image.crop((left, top, right, bottom))


def _user_face_crop(raw: bytes) -> bytes:
    """Create an identity-dominant portrait reference from an ordinary photo."""
    from PIL import Image, ImageOps

    image = Image.open(BytesIO(bytes(raw or b"")))
    image = ImageOps.exif_transpose(image).convert("RGB")
    box = _largest_face_box(image)
    crop = _expanded_face_crop(image, box) if box is not None else _fallback_portrait_crop(image)
    return _jpeg_bytes(crop, max_side=1024, quality=95)


def _prepare_original(base: Any, runtime: Any, raw: bytes) -> tuple[str, str]:
    return base._prepare_image(runtime, raw)


def _prepare_face(base: Any, runtime: Any, raw: bytes) -> tuple[str, str]:
    crop = _user_face_crop(raw)
    return base._prepare_image(runtime, crop)


def _identity_prompt(name: str, scene: str, aspect: str) -> str:
    return (
        "Create one photorealistic vertical arm's-length smartphone selfie with exactly two people. "
        f"Scene: {scene}. Aspect ratio {aspect}. "
        "IDENTITY PRESERVATION IS THE HIGHEST PRIORITY; scene styling is secondary. "
        "PERSON A IS THE USER. REFERENCES 1 and 3 are two original photos of the SAME USER and define "
        "body proportions, build, apparent age, skin tone, hairstyle, hairline and overall appearance. "
        "REFERENCES 2 and 4 are tight face crops of that SAME USER and are the authoritative identity anchors. "
        "The output face of PERSON A must retain the same facial geometry, eye shape and spacing, eyebrows, nose, "
        "mouth, cheeks, jawline, chin, skin tone, age and natural asymmetry visible in REFERENCES 2 and 4. "
        "Do not beautify, slim, age-shift, gender-shift, change ethnicity, average the face, or replace it with a generic model face. "
        f"PERSON B IS {name}. REFERENCES 5, 6 and 7 are three photos of that SAME second person and define PERSON B's identity. "
        "Keep PERSON A and PERSON B as two separate recognizable identities. Never merge, swap, average, duplicate or substitute faces. "
        "Show PERSON A's face clearly, unobstructed, near frontal or mild three-quarter view, large enough to recognize; "
        "the phone may appear but must not cover the user's face. Preserve realistic body size and proportions from REFERENCES 1 and 3. "
        "Use natural lighting, perspective, skin texture and correct anatomy. No text, logos, watermark or UI. "
        "The result is a fictional AI-generated fan scene, not evidence of a real meeting or endorsement."
    )


async def comet_generate(user_images: list[bytes], slug: str, scene: str) -> bytes:
    """Seven-reference Comet/Gemini generation with explicit role binding."""
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as gen

    runtime = _runtime_module()
    refs = base._reference_paths(runtime, slug)
    if runtime is None:
        raise RuntimeError("runtime module is unavailable")
    if len(user_images) != 2 or len(refs) != 3:
        raise RuntimeError(
            f"user photos={len(user_images)}/2, character refs={len(refs)}/3"
        )

    prepared = [
        _prepare_original(base, runtime, user_images[0]),
        _prepare_face(base, runtime, user_images[0]),
        _prepare_original(base, runtime, user_images[1]),
        _prepare_face(base, runtime, user_images[1]),
    ]
    prepared.extend(
        _prepare_original(base, runtime, path.read_bytes())
        for path in refs
    )

    meta = base.CHARACTERS.get(slug) or {}
    name = str(meta.get("name") or slug)
    prompt = _identity_prompt(name, str(scene or ""), base._aspect_ratio())

    key = gen._comet_key()
    base_url = (os.environ.get("COMET_BASE_URL") or "https://api.cometapi.com").rstrip("/")
    if not key:
        raise RuntimeError("COMET_API_KEY is missing")

    headers = {
        "Authorization": f"Bearer {key}",
        "x-goog-api-key": key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    labels = (
        "REFERENCE 1 — USER ORIGINAL A: BODY, HAIR, AGE AND APPEARANCE",
        "REFERENCE 2 — USER FACE CROP A: PRIMARY USER IDENTITY",
        "REFERENCE 3 — USER ORIGINAL B: BODY, HAIR, AGE AND APPEARANCE",
        "REFERENCE 4 — USER FACE CROP B: PRIMARY USER IDENTITY",
        f"REFERENCE 5 — {name} PORTRAIT A",
        f"REFERENCE 6 — {name} PORTRAIT B",
        f"REFERENCE 7 — {name} PORTRAIT C",
    )

    import httpx

    errors: list[str] = []
    timeout_value = max(
        300.0,
        float(os.environ.get("COMET_SELFIE_TIMEOUT_S", "300") or 300),
    )
    timeout = httpx.Timeout(
        timeout_value,
        connect=40.0,
        read=timeout_value,
        write=180.0,
        pool=40.0,
    )
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        for model in gen._models():
            for camel, compatibility in (
                (True, False),
                (False, False),
                (True, True),
                (False, True),
            ):
                parts: list[dict[str, Any]] = [{"text": prompt}]
                for label, (data, mime) in zip(labels, prepared):
                    parts.append({"text": label})
                    if camel:
                        parts.append(
                            {"inlineData": {"mimeType": mime, "data": data}}
                        )
                    else:
                        parts.append(
                            {"inline_data": {"mime_type": mime, "data": data}}
                        )

                config: dict[str, Any] = {
                    "responseModalities": ["TEXT", "IMAGE"]
                }
                if not compatibility:
                    config["imageConfig"] = {
                        "aspectRatio": base._aspect_ratio(),
                        "imageSize": base._image_size(),
                    }
                payload = {
                    "contents": [{"role": "user", "parts": parts}],
                    "generationConfig": config,
                }
                try:
                    response = await client.post(
                        f"{base_url}/v1beta/models/{model}:generateContent",
                        headers=headers,
                        json=payload,
                    )
                    if response.status_code >= 400:
                        errors.append(
                            f"{model}: HTTP {response.status_code}: "
                            f"{response.text[:350]}"
                        )
                        continue
                    output = gen._extract_final_image(response.json())
                    if output:
                        return output
                    errors.append(f"{model}: response contained no final image")
                except Exception as exc:
                    errors.append(f"{model}: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        "Comet seven-reference identity generation failed: "
        + " | ".join(errors[-8:])
    )


async def diagnostic(update: Any, context: Any) -> None:
    """Show the actual production identity route instead of V208's old 5-ref text."""
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base

    runtime = _runtime_module()
    try:
        if runtime is None:
            return
        root = base._storage_root(runtime)
        lines = [
            "💾 Selfie Identity diagnostic",
            f"version={VERSION}",
            f"storage={root}",
            f"data_is_mount={'on' if os.path.ismount('/data') else 'off'}",
            "persistent_storage=on",
            f"characters={len(base.CHARACTERS)}",
            "generator=v213-comet-seven-reference-user-identity-lock",
            "user_original_references=2",
            "user_face_crop_references=2",
            "hero_references=3",
            "references_per_request=7",
        ]
        for character_slug in base.CHARACTERS:
            lines.append(
                f"{character_slug}={base._character_status(runtime, character_slug)} "
                f"ready={'on' if base._character_ready(runtime, character_slug) else 'off'}"
            )
        await update.effective_message.reply_text("\n".join(lines))
    finally:
        raise ApplicationHandlerStop


def patch_runtime() -> bool:
    """Keep V211 delivery and V210 duplicate guard; replace only identity generation."""
    from neyrobot_prod import celebrity_selfie_v204 as generator_v204
    from neyrobot_prod import selfie_commands_v206 as commands_v206
    from neyrobot_prod import selfie_runtime_v207 as runtime_v207
    from neyrobot_prod import selfie_storage_v205 as storage_v205
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v209_canonical as v209
    from neyrobot_prod import selfie_v210_generation_guard as v210
    from neyrobot_prod import selfie_v211_delivery as v211

    v208._comet_generate = comet_generate
    v208._diag_storage = diagnostic
    storage_v205.diagnostic = diagnostic

    v208.VERSION = VERSION
    v209.VERSION = VERSION
    v210.VERSION = VERSION
    v211.VERSION = VERSION
    generator_v204.VERSION = VERSION
    commands_v206.VERSION = VERSION
    runtime_v207.VERSION = VERSION
    storage_v205.VERSION = VERSION

    runtime = _runtime_module()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = (
            "v213-comet-seven-reference-user-identity-lock"
        )
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_USER_ORIGINAL_REFERENCES = 2
        runtime.SELFIE_USER_FACE_REFERENCES = 2
        runtime.SELFIE_HERO_REFERENCES = 3
    return True


def install_async() -> None:
    patch_runtime()


def install() -> None:
    install_async()


__all__ = [
    "VERSION",
    "comet_generate",
    "diagnostic",
    "patch_runtime",
    "install_async",
    "install",
]
