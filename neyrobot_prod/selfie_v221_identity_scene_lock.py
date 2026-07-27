# -*- coding: utf-8 -*-
"""V221 identity/scene lock for the canonical celebrity selfie runtime.

The V219 flow remains the UI and billing owner. This layer replaces only the
Comet/Gemini generation stage with a structured reference stack:
- 2 full user photos + 1 face crop;
- 2 full hero photos + 1 face crop;
- optional scene image used strictly as layout/environment reference.
"""
from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from io import BytesIO
from typing import Any

VERSION = "v221-selfie-identity-scene-lock-2026-07-27"
_STARTED = False


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _face_crop(raw: bytes, *, max_side: int = 1024) -> bytes:
    """Create a stable central upper-body/face crop without external CV models."""
    try:
        from PIL import Image
        image = Image.open(BytesIO(raw)).convert("RGB")
        width, height = image.size
        if width < 64 or height < 64:
            return bytes(raw)
        crop_w = max(256, int(width * 0.68))
        crop_h = max(256, int(height * 0.68))
        center_x = width // 2
        center_y = int(height * 0.38) if height >= width else height // 2
        left = max(0, min(width - crop_w, center_x - crop_w // 2))
        top = max(0, min(height - crop_h, center_y - crop_h // 2))
        cropped = image.crop((left, top, min(width, left + crop_w), min(height, top + crop_h)))
        if max(cropped.size) > max_side:
            cropped.thumbnail((max_side, max_side), Image.LANCZOS)
        bio = BytesIO()
        cropped.save(bio, format="JPEG", quality=95, optimize=True)
        result = bio.getvalue()
        return result if len(result) > 1024 else bytes(raw)
    except Exception:
        return bytes(raw)


def _prompt(name: str, scene: str, aspect: str, shot_mode: str, has_scene_image: bool) -> str:
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215

    if shot_mode == v215.SHOT_THIRD_PERSON:
        shot = (
            "SHOT MODE: THIRD-PERSON JOINT PHOTO. Another person takes the photograph. "
            "Do not show a phone, selfie stick, camera interface or oversized foreground hand."
        )
    else:
        shot = (
            "SHOT MODE: FRONT-CAMERA SELFIE POV. The image is the front-camera result itself. "
            "The phone must remain outside the frame and must not be visible."
        )

    scene_rule = f"SCENE REQUEST: {scene or 'a natural premium real-world environment'}. "
    if has_scene_image:
        scene_rule += (
            "REFERENCE 7 IS A STRICT LOCATION/LAYOUT ANCHOR ONLY. Reproduce the same room or location: "
            "architecture, wall positions, windows, curtains, furniture, table, chairs, floor, perspective, "
            "camera direction, light direction and atmosphere. Do not replace it with another room. "
            "Ignore and remove identities of any people visible in reference 7. Place only PERSON A and PERSON B. "
        )

    return (
        f"Create one photorealistic vertical image with exactly two people. Aspect ratio {aspect}. {shot} {scene_rule}"
        "IDENTITY ACCURACY IS MORE IMPORTANT THAN STYLE. "
        "PERSON A IS THE USER. REFERENCES 1 AND 2 are full/medium photos of the same user. "
        "REFERENCE 3 is a close identity crop of the same user's face and is the highest-priority facial anchor. "
        "Preserve exact head shape, facial geometry, eye spacing and shape, eyebrows, nose, mouth, cheeks, jawline, "
        "chin, hairline, facial hair, skin tone, apparent age, body build and natural asymmetry. "
        "Do not beautify, slim, rejuvenate, age-shift, change ethnicity, average the face, or replace the user with a generic lookalike. "
        f"PERSON B IS {name}. REFERENCES 4 AND 5 are full/medium photos of that same person. "
        "REFERENCE 6 is a close identity crop of PERSON B's face and is the highest-priority facial anchor for PERSON B. "
        "Preserve PERSON B's exact facial structure, apparent age and distinctive features. "
        "Give PERSON A and PERSON B equal identity priority. Keep them separate; never merge, swap, average, duplicate, "
        "transfer features, or create additional people. Do not change either person's ethnicity. "
        "Use realistic anatomy, skin texture, lighting, perspective and scale. No text, logos, watermarks or interface elements. "
        "The result is fictional AI-generated fan content and is not evidence of a real meeting or endorsement."
    )


def _prepare_stack(base: Any, runtime: Any, identity: Any, user_images: list[bytes], hero_images: list[bytes], scene_image: bytes | None) -> tuple[list[tuple[str, str]], list[str]]:
    user_a = bytes(user_images[0])
    user_b = bytes(user_images[1] if len(user_images) > 1 else user_images[0])
    hero_a = bytes(hero_images[0])
    hero_b = bytes(hero_images[1] if len(hero_images) > 1 else hero_images[0])

    raw_stack = [
        user_a,
        user_b,
        _face_crop(user_a),
        hero_a,
        hero_b,
        _face_crop(hero_a),
    ]
    labels = [
        "REFERENCE 1 — USER FULL/FRONT IDENTITY ANCHOR",
        "REFERENCE 2 — USER SECOND ANGLE IDENTITY ANCHOR",
        "REFERENCE 3 — USER FACE CROP, HIGHEST-PRIORITY FACIAL ANCHOR",
        "REFERENCE 4 — HERO FULL/FRONT IDENTITY ANCHOR",
        "REFERENCE 5 — HERO SECOND ANGLE IDENTITY ANCHOR",
        "REFERENCE 6 — HERO FACE CROP, HIGHEST-PRIORITY FACIAL ANCHOR",
    ]
    if scene_image and len(scene_image) > 1024:
        raw_stack.append(bytes(scene_image))
        labels.append("REFERENCE 7 — LOCATION/LAYOUT ONLY; NEVER USE FOR PERSON IDENTITY")
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
                        if camel
                        else {"inline_data": {"mime_type": mime, "data": data}}
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
    raise RuntimeError("Comet V221 generation failed: " + " | ".join(errors[-8:]))


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
        runtime.CELEBRITY_SELFIE_ROUTE = "v221-identity-crops-scene-layout-lock"
        runtime.AI_SELFIE_USER_REFERENCES = 3
        runtime.AI_SELFIE_HERO_REFERENCES = 3
    return True


def install_async() -> None:
    global _STARTED
    patch_runtime()
    if _STARTED:
        return
    _STARTED = True

    def worker() -> None:
        for _ in range(21600):
            with contextlib.suppress(Exception):
                patch_runtime()
            time.sleep(0.1)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v221-lock").start()


def install() -> None:
    install_async()


__all__ = ["VERSION", "_face_crop", "_prompt", "_prepare_stack", "_comet_generate", "patch_runtime", "install_async", "install"]
