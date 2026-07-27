# -*- coding: utf-8 -*-
"""V222 strict identity and uploaded-scene owner.

The V219 flow remains the UI/billing owner. This layer fixes two production
regressions introduced by V221:
- all three uploaded user photos and all three hero photos are actually sent;
- an uploaded scene is sent first and treated as the immutable base image.
"""
from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from typing import Any

VERSION = "v222-selfie-exact-triref-scene-base-2026-07-27"
_START = False


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


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
            "BASE IMAGE / REFERENCE 1 IS THE USER-UPLOADED SCENE AND IS IMMUTABLE. "
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
        "IDENTITY IS STRICT, NOT APPROXIMATE. "
        "PERSON A IS THE USER. USER REFERENCES are three different original photographs of the same person. "
        "Use all three jointly as authoritative identity evidence. Preserve exact face shape, skull/head proportions, "
        "hairline, hairstyle, eye shape and spacing, eyebrows, nose, lips, cheeks, jaw, chin, ears, skin tone, apparent age, "
        "facial hair, body build and natural asymmetry. Do not beautify, slim, rejuvenate, age, change ethnicity, average, "
        "or replace PERSON A with a generic lookalike. Clothing may follow the most recent user reference unless required by the scene. "
        f"PERSON B IS {name}. HERO REFERENCES are three different original photographs of that same person. "
        "Use all three jointly and preserve distinctive facial structure, age and proportions. "
        "Keep PERSON A and PERSON B separate. Never merge, swap, average, duplicate or transfer facial features. "
        "Exactly two people only. Realistic anatomy, scale, skin texture, lighting and contact shadows. "
        "No text, logos, watermarks or interface elements. The image is fictional AI-generated fan content."
    )


def _prepare_stack(base: Any, runtime: Any, identity: Any, user_images: list[bytes], hero_images: list[bytes], scene_image: bytes | None) -> tuple[list[tuple[str, str]], list[str]]:
    if len(user_images) != 3 or len(hero_images) != 3:
        raise RuntimeError(f"strict stack requires 3 user and 3 hero refs, got {len(user_images)} and {len(hero_images)}")

    raw_stack: list[bytes] = []
    labels: list[str] = []
    if scene_image and len(scene_image) > 1024:
        raw_stack.append(bytes(scene_image))
        labels.append("REFERENCE 1 — IMMUTABLE BASE SCENE; EDIT THIS EXACT IMAGE; ENVIRONMENT MUST NOT CHANGE")

    offset = 2 if raw_stack else 1
    for idx, raw in enumerate(user_images, start=offset):
        raw_stack.append(bytes(raw))
        labels.append(f"REFERENCE {idx} — PERSON A / USER IDENTITY PHOTO {idx - offset + 1} OF 3")
    hero_offset = offset + 3
    for idx, raw in enumerate(hero_images, start=hero_offset):
        raw_stack.append(bytes(raw))
        labels.append(f"REFERENCE {idx} — PERSON B / HERO IDENTITY PHOTO {idx - hero_offset + 1} OF 3")

    prepared = [identity._prepare_original(base, runtime, raw) for raw in raw_stack]
    return prepared, labels


async def _comet_generate(user_images: list[bytes], slug: str, scene: str, shot_mode: str, scene_image: bytes | None) -> bytes:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as gen
    from neyrobot_prod import selfie_v213_user_identity_lock as identity

    runtime = _runtime()
    if runtime is None:
        raise RuntimeError("runtime module is unavailable")
    refs = base._reference_paths(runtime, slug)
    if len(user_images) != 3 or len(refs) != 3:
        raise RuntimeError(f"user photos={len(user_images)}/3, character refs={len(refs)}/3")

    hero_images = [path.read_bytes() for path in refs]
    has_scene_image = bool(scene_image and len(scene_image) > 1024)
    prepared, labels = _prepare_stack(base, runtime, identity, user_images, hero_images, scene_image)
    meta = base.CHARACTERS.get(slug) or {}
    name = str(meta.get("name") or slug)
    prompt = _prompt(name, scene, base._aspect_ratio(), shot_mode, has_scene_image)

    key = gen._comet_key()
    if not key:
        raise RuntimeError("COMET_API_KEY is missing")
    base_url = (os.environ.get("COMET_BASE_URL") or "https://api.cometapi.com").rstrip("/")
    headers = {
        "Authorization": f"Bearer {key}",
        "x-goog-api-key": key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    import httpx
    errors: list[str] = []
    timeout_value = max(300.0, float(os.environ.get("COMET_SELFIE_TIMEOUT_S", "300") or 300))
    timeout = httpx.Timeout(timeout_value, connect=40.0, read=timeout_value, write=180.0, pool=40.0)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        for model in gen._models():
            for camel, compatibility in ((True, False), (False, False), (True, True), (False, True)):
                parts: list[dict[str, Any]] = [{"text": prompt}]
                for label, (data, mime) in zip(labels, prepared):
                    parts.append({"text": label})
                    parts.append(
                        {"inlineData": {"mimeType": mime, "data": data}}
                        if camel else {"inline_data": {"mime_type": mime, "data": data}}
                    )
                config: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
                if not compatibility:
                    config["imageConfig"] = {"aspectRatio": base._aspect_ratio(), "imageSize": base._image_size()}
                try:
                    response = await client.post(
                        f"{base_url}/v1beta/models/{model}:generateContent",
                        headers=headers,
                        json={"contents": [{"role": "user", "parts": parts}], "generationConfig": config},
                    )
                    if response.status_code >= 400:
                        errors.append(f"{model}: HTTP {response.status_code}: {response.text[:350]}")
                        continue
                    output = gen._extract_final_image(response.json())
                    if output:
                        return output
                    errors.append(f"{model}: response contained no final image")
                except Exception as exc:
                    errors.append(f"{model}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Comet V222 generation failed: " + " | ".join(errors[-8:]))


def patch_runtime() -> bool:
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v218_runtime_owner as v218
    from neyrobot_prod import selfie_v220_runtime_marker as v220

    v219._prompt = _prompt
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
        runtime.CELEBRITY_SELFIE_ROUTE = "v222-scene-first-exact-3-user-3-hero"
        runtime.AI_SELFIE_USER_REFERENCES = 3
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
        # Keep this owner above all legacy V218/V219/V220 workers for six hours.
        for _ in range(216000):
            try:
                patch_runtime()
            except Exception as exc:
                runtime = _runtime()
                logger = getattr(runtime, "log", None) if runtime is not None else None
                with contextlib.suppress(Exception):
                    logger.exception("V222 selfie patch failed: %r", exc)
            time.sleep(0.1)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v222-owner").start()


def install() -> None:
    install_async()


__all__ = ["VERSION", "_prompt", "_prepare_stack", "_comet_generate", "patch_runtime", "install_async", "install"]
