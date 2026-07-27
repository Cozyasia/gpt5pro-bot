# -*- coding: utf-8 -*-
"""V225 direct-Google strict identity and uploaded-scene owner.

The V219 flow remains the UI/billing owner. This layer keeps the uploaded scene
as the immutable base image, strengthens the user identity with three originals
plus three detected face crops, and sends the request directly to the official
Gemini Developer API. CometAPI is not used by this selfie route.
"""
from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from typing import Any

VERSION = "v225-selfie-direct-gemini-pro-2026-07-27"
_START = False


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _google_key() -> str:
    return (
        os.environ.get("GEMINI_IMAGE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    ).strip()


def _models() -> list[str]:
    raw = (
        os.environ.get("GEMINI_SELFIE_MODELS")
        or os.environ.get("GEMINI_SELFIE_MODEL")
        or "gemini-3-pro-image,gemini-3.1-flash-image"
    )
    return list(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))


def _base_url() -> str:
    return (os.environ.get("GEMINI_API_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")


def _prompt(name: str, scene: str, aspect: str, shot_mode: str, has_scene_image: bool) -> str:
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215

    if shot_mode == v215.SHOT_THIRD_PERSON:
        shot = (
            "SHOT MODE: THIRD-PERSON JOINT PHOTO. The camera is held by another person. "
            "No phone, selfie stick, interface or foreground hand may appear. "
        )
    else:
        shot = (
            "SHOT MODE: FRONT-CAMERA SELFIE RESULT. The phone is outside the frame. "
            "No visible phone, selfie stick, camera UI or oversized foreground hand. "
        )

    if has_scene_image:
        scene_rule = (
            "BASE SCENE REFERENCE IS THE USER-UPLOADED PHOTOGRAPH AND IS IMMUTABLE. "
            "THIS IS AN IMAGE-EDITING TASK, NOT A NEW-SCENE GENERATION TASK. "
            "Keep the exact same room, architecture, walls, ceiling, windows, doors, curtains, balcony, radiator, "
            "floor, table, chairs, objects, object positions, camera position, lens perspective, crop, framing, "
            "light direction, shadows and color temperature. Do not redesign, enlarge, beautify, restage, replace, "
            "invent or move anything in the environment. The output must look like the same uploaded photograph "
            "with only two people inserted naturally into available space. Never copy any person from the base scene. "
        )
    else:
        scene_rule = f"SCENE REQUEST: {scene or 'a natural real-world environment'}. "

    return (
        f"Create one photorealistic image with exactly two people. Aspect ratio {aspect}. {shot}{scene_rule}"
        "USER IDENTITY IS THE HIGHEST PRIORITY IN THE ENTIRE TASK, ABOVE HERO STYLING. "
        "PERSON A IS THE USER. USER ORIGINAL references are three different original photographs of the same person "
        "and define body build, apparent age, skin tone, hairstyle, hairline and overall proportions. "
        "USER FACE CROP references are three close facial anchors derived from those same originals and are the decisive, "
        "highest-priority evidence for PERSON A's identity. Reproduce the same facial geometry, skull and head shape, "
        "eye shape and spacing, eyelids, eyebrows, nose width and tip, lips, cheeks, jawline, chin, ears, hairline, facial hair, "
        "skin texture, skin tone, apparent age and natural asymmetry. Do not beautify, slim, rejuvenate, masculinize, "
        "feminize, change ethnicity, average the face, or replace PERSON A with a generic lookalike. "
        "PERSON A must be closest to the camera, near frontal or mild three-quarter view, unobstructed and large enough "
        "that the face is clearly recognizable; do not make the user's head tiny in the frame. Preserve the user's real body build. "
        f"PERSON B IS {name}. HERO references are three photographs of that same person and define PERSON B's identity. "
        "PERSON B may stand slightly behind or beside PERSON A so the user's identity remains dominant. "
        "Keep PERSON A and PERSON B separate. Never merge, swap, average, duplicate or transfer facial features. "
        "Exactly two people only. Realistic anatomy, scale, skin texture, lighting and contact shadows. "
        "No text, logos, watermarks or interface elements. The image is fictional AI-generated fan content."
    )


def _prepare_stack(base: Any, runtime: Any, identity: Any, user_images: list[bytes], hero_images: list[bytes], scene_image: bytes | None) -> tuple[list[tuple[str, str]], list[str]]:
    if len(user_images) != 3 or len(hero_images) != 3:
        raise RuntimeError(f"strict stack requires 3 user and 3 hero refs, got {len(user_images)} and {len(hero_images)}")

    prepared: list[tuple[str, str]] = []
    labels: list[str] = []
    ref_no = 1

    if scene_image and len(scene_image) > 1024:
        prepared.append(identity._prepare_original(base, runtime, bytes(scene_image)))
        labels.append(f"REFERENCE {ref_no} — IMMUTABLE BASE SCENE; EDIT THIS EXACT IMAGE; ENVIRONMENT MUST NOT CHANGE")
        ref_no += 1

    for idx, raw in enumerate(user_images, start=1):
        prepared.append(identity._prepare_original(base, runtime, bytes(raw)))
        labels.append(f"REFERENCE {ref_no} — PERSON A / USER ORIGINAL {idx} OF 3: BODY, AGE, HAIR AND PROPORTIONS")
        ref_no += 1
        prepared.append(identity._prepare_face(base, runtime, bytes(raw)))
        labels.append(f"REFERENCE {ref_no} — PERSON A / USER FACE CROP {idx} OF 3: HIGHEST-PRIORITY FACIAL IDENTITY")
        ref_no += 1

    for idx, raw in enumerate(hero_images, start=1):
        prepared.append(identity._prepare_original(base, runtime, bytes(raw)))
        labels.append(f"REFERENCE {ref_no} — PERSON B / HERO IDENTITY PHOTO {idx} OF 3")
        ref_no += 1

    return prepared, labels


def _payload(prompt: str, labels: list[str], prepared: list[tuple[str, str]], aspect: str, image_size: str) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for label, (data, mime) in zip(labels, prepared):
        parts.append({"text": label})
        parts.append({"inline_data": {"mime_type": mime, "data": data}})
    return {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": aspect, "imageSize": image_size},
        },
    }


async def _comet_generate(user_images: list[bytes], slug: str, scene: str, shot_mode: str, scene_image: bytes | None) -> bytes:
    """Compatibility name retained for V219; implementation is direct Google Gemini."""
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as gen
    from neyrobot_prod import selfie_v213_user_identity_lock as identity

    runtime = _runtime()
    if runtime is None:
        raise RuntimeError("runtime module is unavailable")
    refs = base._reference_paths(runtime, slug)
    if len(user_images) != 3 or len(refs) != 3:
        raise RuntimeError(f"user photos={len(user_images)}/3, character refs={len(refs)}/3")

    key = _google_key()
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY is missing")

    hero_images = [path.read_bytes() for path in refs]
    has_scene_image = bool(scene_image and len(scene_image) > 1024)
    prepared, labels = _prepare_stack(base, runtime, identity, user_images, hero_images, scene_image)
    meta = base.CHARACTERS.get(slug) or {}
    name = str(meta.get("name") or slug)
    aspect = base._aspect_ratio()
    image_size = (os.environ.get("GEMINI_SELFIE_IMAGE_SIZE") or base._image_size() or "2K").upper()
    if image_size not in {"1K", "2K", "4K"}:
        image_size = "2K"
    prompt = _prompt(name, scene, aspect, shot_mode, has_scene_image)

    import httpx

    timeout_value = max(300.0, float(os.environ.get("GEMINI_SELFIE_TIMEOUT_S", "300") or 300))
    timeout = httpx.Timeout(timeout_value, connect=40.0, read=timeout_value, write=180.0, pool=40.0)
    headers = {"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
    errors: list[str] = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        for model in _models():
            try:
                response = await client.post(
                    f"{_base_url()}/models/{model}:generateContent",
                    headers=headers,
                    json=_payload(prompt, labels, prepared, aspect, image_size),
                )
                if response.status_code >= 400:
                    errors.append(f"{model}: HTTP {response.status_code}: {response.text[:700]}")
                    continue
                output = gen._extract_final_image(response.json())
                if output:
                    runtime.AI_SELFIE_LAST_PROVIDER = "Google Gemini direct"
                    runtime.AI_SELFIE_LAST_MODEL = model
                    runtime.AI_SELFIE_LAST_IMAGE_SIZE = image_size
                    return output
                errors.append(f"{model}: response contained no final non-thought image")
            except Exception as exc:
                errors.append(f"{model}: {type(exc).__name__}: {exc}")

    raise RuntimeError("Direct Gemini V225 generation failed: " + " | ".join(errors[-6:]))


def patch_runtime() -> bool:
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v218_runtime_owner as v218
    from neyrobot_prod import selfie_v220_runtime_marker as v220

    v219._prompt = _prompt
    v219._prepare_stack = _prepare_stack
    v219._comet_generate = _comet_generate
    v219.VERSION = VERSION
    v218.VERSION = VERSION
    v220.VERSION = VERSION

    runtime = _runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v225-direct-google-scene-first-3-user-3-face-3-hero"
        runtime.AI_SELFIE_PROVIDER = "Google Gemini direct"
        runtime.AI_SELFIE_CONFIGURED = bool(_google_key())
        runtime.AI_SELFIE_MODELS = ",".join(_models())
        runtime.AI_SELFIE_USER_REFERENCES = 3
        runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
        runtime.AI_SELFIE_HERO_REFERENCES = 3
        runtime.AI_SELFIE_SCENE_REFERENCE_POSITION = 1
    return True


def install_async() -> None:
    global _START
    with contextlib.suppress(Exception):
        patch_runtime()
    if _START:
        return
    _START = True

    def worker() -> None:
        for _ in range(216000):
            try:
                patch_runtime()
            except Exception as exc:
                runtime = _runtime()
                logger = getattr(runtime, "log", None) if runtime is not None else None
                with contextlib.suppress(Exception):
                    logger.exception("V225 direct Gemini selfie patch failed: %r", exc)
            time.sleep(0.1)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v225-direct-gemini").start()


def install() -> None:
    install_async()


__all__ = ["VERSION", "_google_key", "_models", "_prompt", "_prepare_stack", "_comet_generate", "patch_runtime", "install_async", "install"]