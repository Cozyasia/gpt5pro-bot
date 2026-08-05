# -*- coding: utf-8 -*-
"""V237 deterministic terminal user-face transfer for Celebrity Selfie.

Architecture:
1. Gemini creates only the scene, hero and age/build-correct user body.
2. The generated PERSON A face is detected locally and cropped into a one-face target.
3. User photo #3 is detected and cropped into a one-face identity source.
4. PiAPI single-face-swap runs only on those two one-face crops.
5. The swapped crop is feather-composited back into the untouched Gemini image.

This removes multi-face index ambiguity and prevents the hero or the whole scene from
being regenerated during identity transfer.

Required Render variable: PIAPI_API_KEY
Optional variables:
  PIAPI_FACE_SWAP_TIMEOUT_SEC=150
  PIAPI_FACE_SWAP_POLL_SEC=2
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
from io import BytesIO
from typing import Any

import httpx

VERSION = "v237-deterministic-cropped-terminal-face-transfer-2026-08-05"
PIAPI_TASK_URL = "https://api.piapi.ai/api/v1/task"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(bytes(raw or b"")).hexdigest()[:12]


def _b64(raw: bytes) -> str:
    return base64.b64encode(bytes(raw)).decode("ascii")


def _stage1_prompt(name: str, scene: str, shot_label: str, has_scene_image: bool) -> str:
    scene_rule = (
        "The first image is the authoritative scene base. Preserve its exact architecture, "
        "camera, crop, perspective, lighting and object positions. "
        if has_scene_image else f"Create this scene faithfully: {scene}. "
    )
    return (
        "Create one natural photorealistic vertical photograph with exactly two principal people. "
        f"SHOT MODE: {shot_label}. {scene_rule}"
        "PERSON A is the user body placeholder and MUST stand clearly on the LEFT side. "
        "PERSON B must stand clearly on the RIGHT side. Their heads must be at approximately the same vertical level, "
        "with no overlap and enough empty space around PERSON A's head for a later local face replacement. "
        "The two USER AGE/BUILD references are authoritative only for PERSON A's apparent age, height class, body scale, "
        "shoulder width, neck thickness, limb proportions and overall build. Match the age exactly. If the references show "
        "a child or teenager, PERSON A MUST remain the same apparent age and must never receive an adult skull, jaw, neck, "
        "shoulders, facial hair, age lines or mature facial mass. Use age-appropriate head-to-body ratio and anatomy. "
        "Do not reproduce the user's identity in this stage. Create a neutral temporary face of the correct age and sex, "
        "near-frontal, no more than 10 degrees yaw, eyes open, mouth relaxed, no glasses, no hand or hair covering the face, "
        "evenly lit, and at least 220 pixels high. PERSON A must be closer to the camera than background people. "
        f"PERSON B is {name}. The three HERO references are the exclusive identity authority for PERSON B. Preserve the hero's "
        "face, age, hairstyle and distinctive features. Never blend PERSON A and PERSON B. No profile views. No duplicate main "
        "people. Use realistic smartphone/event photography, natural skin texture, ordinary optics, subtle sensor noise and "
        "plausible ambient light. Do not show a phone unless explicitly required. No text, logos, watermark or interface."
    )


def _piapi_key() -> str:
    return str(os.getenv("PIAPI_API_KEY") or "").strip()


def _output_url(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return ""
    output = data.get("output")
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("image_url", "image", "url", "output_url"):
            value = output.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        images = output.get("images")
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict):
                for key in ("url", "image_url", "image"):
                    value = first.get(key)
                    if isinstance(value, str) and value.startswith("http"):
                        return value
    return ""


def _image(raw: bytes) -> Any:
    from PIL import Image, ImageOps

    image = Image.open(BytesIO(bytes(raw or b"")))
    return ImageOps.exif_transpose(image).convert("RGB")


def _jpeg(image: Any, *, max_side: int = 1900, quality: int = 96) -> bytes:
    image = image.convert("RGB")
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side))
    out = BytesIO()
    image.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def _detect_faces(image: Any) -> list[tuple[int, int, int, int]]:
    """Detect frontal faces in original-image coordinates, sorted left-to-right."""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        from PIL import Image

        width, height = image.size
        scale = min(1.0, 1400.0 / float(max(width, height)))
        scan = image
        if scale < 1.0:
            scan = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.LANCZOS)
        gray = cv2.cvtColor(np.asarray(scan), cv2.COLOR_RGB2GRAY)
        cascade = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
        if cascade.empty():
            return []
        found = cascade.detectMultiScale(gray, scaleFactor=1.06, minNeighbors=5, minSize=(48, 48))
        inverse = 1.0 / scale
        boxes = [
            (
                int(round(float(x) * inverse)),
                int(round(float(y) * inverse)),
                int(round(float(w) * inverse)),
                int(round(float(h) * inverse)),
            )
            for x, y, w, h in found
        ]
        boxes.sort(key=lambda box: box[0] + box[2] / 2.0)
        return boxes
    except Exception:
        return []


def _expanded_box(
    box: tuple[int, int, int, int],
    image_size: tuple[int, int],
    *,
    width_factor: float,
    height_factor: float,
    y_shift: float,
) -> tuple[int, int, int, int]:
    x, y, w, h = box
    image_w, image_h = image_size
    cx = x + w / 2.0
    cy = y + h / 2.0 + h * y_shift
    crop_w = max(180.0, w * width_factor)
    crop_h = max(220.0, h * height_factor)
    left = max(0, int(round(cx - crop_w / 2.0)))
    top = max(0, int(round(cy - crop_h / 2.0)))
    right = min(image_w, int(round(cx + crop_w / 2.0)))
    bottom = min(image_h, int(round(cy + crop_h / 2.0)))
    if right - left < 128 or bottom - top < 128:
        raise ValueError("face crop is too small")
    return left, top, right, bottom


def _source_face_crop(raw: bytes) -> tuple[bytes, tuple[int, int, int, int]]:
    image = _image(raw)
    faces = _detect_faces(image)
    if not faces:
        raise ValueError("photo #3 has no reliably detected frontal face")
    box = max(faces, key=lambda item: item[2] * item[3])
    if box[2] < 90 or box[3] < 90:
        raise ValueError("photo #3 face is too small")
    crop_box = _expanded_box(box, image.size, width_factor=2.15, height_factor=2.55, y_shift=-0.04)
    return _jpeg(image.crop(crop_box), max_side=1200), box


def _target_face_crop(raw: bytes) -> tuple[Any, tuple[int, int, int, int], bytes, tuple[int, int, int, int]]:
    image = _image(raw)
    faces = _detect_faces(image)
    if len(faces) < 2:
        raise ValueError(f"generated composition must contain two detectable frontal faces; detected={len(faces)}")

    # Stage 1 forces PERSON A to the left. Ignore tiny background detections and choose
    # the left-most substantial main face.
    main = [box for box in faces if box[2] >= 90 and box[3] >= 90]
    if len(main) < 2:
        main = sorted(faces, key=lambda item: item[2] * item[3], reverse=True)[:2]
        main.sort(key=lambda item: item[0] + item[2] / 2.0)
    target_face = main[0]
    if target_face[2] < 80 or target_face[3] < 80:
        raise ValueError("generated user face is too small for reliable transfer")

    crop_box = _expanded_box(target_face, image.size, width_factor=2.55, height_factor=3.05, y_shift=0.02)
    crop = image.crop(crop_box)
    return image, crop_box, _jpeg(crop, max_side=1500), target_face


async def _piapi_single_face_swap(target_crop: bytes, face_source: bytes, log: Any) -> bytes:
    key = _piapi_key()
    if not key:
        raise RuntimeError("PIAPI_API_KEY is missing")

    timeout_sec = max(30.0, float(os.getenv("PIAPI_FACE_SWAP_TIMEOUT_SEC") or "150"))
    poll_sec = max(1.0, float(os.getenv("PIAPI_FACE_SWAP_POLL_SEC") or "2"))
    headers = {"x-api-key": key, "Content-Type": "application/json"}
    body = {
        "model": "Qubico/image-toolkit",
        "task_type": "face-swap",
        "input": {
            "swap_image": _b64(face_source),
            "target_image": _b64(target_crop),
        },
    }

    limits = httpx.Limits(max_connections=5, max_keepalive_connections=2)
    async with httpx.AsyncClient(timeout=httpx.Timeout(35.0), limits=limits, follow_redirects=True) as client:
        response = await client.post(PIAPI_TASK_URL, headers=headers, json=body)
        response.raise_for_status()
        created = response.json()
        data = created.get("data") if isinstance(created, dict) else None
        task_id = str((data or {}).get("task_id") or "").strip()
        if not task_id:
            raise RuntimeError(f"PiAPI did not return task_id: {str(created)[:500]}")
        log("AI_SELFIE_V237_PIAPI_CREATED task_id=%s mode=single-face-cropped", task_id)

        deadline = asyncio.get_running_loop().time() + timeout_sec
        last_status = "pending"
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(poll_sec)
            check = await client.get(f"{PIAPI_TASK_URL}/{task_id}", headers={"x-api-key": key})
            check.raise_for_status()
            payload = check.json()
            pdata = payload.get("data") if isinstance(payload, dict) else None
            status = str((pdata or {}).get("status") or "").lower()
            if status != last_status:
                log("AI_SELFIE_V237_PIAPI_STATUS task_id=%s status=%s", task_id, status)
                last_status = status
            if status in {"completed", "success", "succeeded"}:
                url = _output_url(payload)
                if not url:
                    raise RuntimeError(f"PiAPI completed without image URL: {str(payload)[:800]}")
                image_response = await client.get(url, timeout=45.0)
                image_response.raise_for_status()
                final = bytes(image_response.content)
                if len(final) < 1024:
                    raise RuntimeError("PiAPI returned an empty image")
                return final
            if status in {"failed", "error", "cancelled", "canceled"}:
                error = (pdata or {}).get("error") or (pdata or {}).get("detail") or payload.get("message")
                raise RuntimeError(f"PiAPI face swap failed: {str(error)[:700]}")

    raise TimeoutError(f"PiAPI face swap exceeded {int(timeout_sec)} seconds")


def _composite_crop(base_image: Any, crop_box: tuple[int, int, int, int], swapped_raw: bytes) -> bytes:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    left, top, right, bottom = crop_box
    width, height = right - left, bottom - top
    swapped = _image(swapped_raw).resize((width, height), Image.LANCZOS)
    original_crop = base_image.crop(crop_box)

    # PiAPI should preserve the crop except for the face. A softly feathered rounded
    # rectangle prevents hard seams while keeping the rest of the Gemini image untouched.
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    margin_x = max(8, int(width * 0.035))
    margin_y = max(8, int(height * 0.035))
    radius = max(18, int(min(width, height) * 0.12))
    draw.rounded_rectangle(
        (margin_x, margin_y, width - margin_x, height - margin_y),
        radius=radius,
        fill=255,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(max(8, int(min(width, height) * 0.045))))

    blended_crop = Image.composite(swapped, original_crop, mask)
    output = base_image.copy()
    output.paste(blended_crop, (left, top))
    return _jpeg(output, max_side=2048, quality=96)


async def generate(update: Any, context: Any, scene: str = "") -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v211_delivery as delivery
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229

    runtime = v229._runtime()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None:
        return False

    slug = str(context.user_data.get("cs201_character") or "")
    meta = base.CHARACTERS.get(slug)
    photos = v219._photos(context)
    shot_mode = str(context.user_data.get("cs215_shot_mode") or "")
    scene_mode = str(context.user_data.get("cs215_scene_mode") or "")
    scene_text = str(scene or context.user_data.get("cs215_scene_text") or "").strip()
    scene_image = bytes(context.user_data.get("cs215_scene_image") or b"") if scene_mode == v215.SCENE_IMAGE else None

    if not meta or len(photos) != 3 or shot_mode not in {v215.SHOT_SELFIE, v215.SHOT_THIRD_PERSON} or not v219._scene_ready(context):
        await delivery._safe_text(message, "❌ Не хватает данных: нужны 3 фото пользователя, герой, тип кадра и сцена.")
        return False
    if not v229._key():
        await delivery._safe_text(message, "❌ Отсутствует GEMINI_IMAGE_API_KEY. Средства не списаны.")
        return False
    if not _piapi_key():
        await delivery._safe_text(message, "❌ Отсутствует PIAPI_API_KEY для точного переноса лица. Средства не списаны.")
        return False

    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await delivery._safe_text(message, "❌ Платёжный guard генераций не найден. Средства не списаны.")
        return False

    hero_paths = base._reference_paths(runtime, slug)
    if len(hero_paths) != 3:
        await delivery._safe_text(message, f"❌ Для героя не хватает референсов: {len(hero_paths)}/3.")
        return False

    body_refs = [
        ("USER AGE/BUILD REFERENCE 1: age, body scale and proportions only; ignore identity", bytes(photos[0])),
        ("USER AGE/BUILD REFERENCE 2: age, shoulders, neck, limbs and build only; ignore identity", bytes(photos[1])),
    ]
    hero_refs = [(f"HERO REFERENCE {idx}: exclusive PERSON B identity", path.read_bytes()) for idx, path in enumerate(hero_paths, 1)]
    face_original = bytes(photos[2])
    has_scene_image = bool(scene_image and len(scene_image) > 1024)

    stage1_refs: list[tuple[str, bytes]] = []
    if has_scene_image:
        stage1_refs.append(("AUTHORITATIVE SCENE BASE", bytes(scene_image)))
    stage1_refs.extend(body_refs)
    stage1_refs.extend(hero_refs)
    result = {"ok": False}

    async def action() -> bool:
        try:
            source_crop, source_box = _source_face_crop(face_original)
            v229._log(
                "AI_SELFIE_V237_START user_id=%s character=%s face3_sha=%s source_crop_sha=%s source_box=%s",
                int(user.id), slug, _sha(face_original), _sha(source_crop), source_box,
            )
            await delivery._safe_text(
                message,
                "⏳ Этап 1/3: создаю сцену, героя и тело пользователя. Личность пользователя на этом этапе не генерируется.",
            )
            composition, model1 = await v229._call_google(
                _stage1_prompt(str(meta["name"]), scene_text, v215._shot_label(shot_mode), has_scene_image),
                stage1_refs,
                "v237_scene_hero_body_only",
            )
            v229._log("AI_SELFIE_V237_COMPOSITION_OK bytes=%s sha=%s model=%s", len(composition), _sha(composition), model1)

            await delivery._safe_text(message, "🔎 Этап 2/3: локально выделяю только лицо пользователя слева; герой и сцена блокируются.")
            base_image, target_box, target_crop, target_face = _target_face_crop(composition)
            v229._log(
                "AI_SELFIE_V237_TARGET_LOCKED target_face=%s target_crop=%s target_crop_sha=%s",
                target_face, target_box, _sha(target_crop),
            )

            await delivery._safe_text(message, "🧬 Этап 3/3: переношу лицо с фото №3 на однолицевой фрагмент и возвращаю его в исходную сцену.")
            swapped_crop = await _piapi_single_face_swap(target_crop, source_crop, v229._log)
            if _sha(swapped_crop) == _sha(target_crop):
                raise RuntimeError("face swap returned unchanged target crop")
            final = _composite_crop(base_image, target_box, swapped_crop)
            v229._log(
                "AI_SELFIE_V237_FINAL_OK composition_sha=%s swapped_crop_sha=%s final_sha=%s bytes=%s",
                _sha(composition), _sha(swapped_crop), _sha(final), len(final),
            )

            caption = (
                f"🎭 AI-фото с персонажем «{meta['name']}» готово ✅\n"
                "Маршрут: Gemini сцена+герой+тело → локальная фиксация лица пользователя → PiAPI face swap с фото №3 → возврат фрагмента в нетронутую сцену.\n"
                "Фото создано ИИ и не подтверждает реальную встречу или поддержку."
            )
            delivered = await delivery._deliver(message, final, caption, prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)))
            result["ok"] = bool(delivered)
            if delivered:
                await message.reply_text("✅ Что сделать дальше? Фото пользователя, герой, тип кадра и сцена сохранены.", reply_markup=v215._continuation_keyboard(runtime, slug))
            return bool(delivered)
        except Exception as exc:
            delivery._log_exception("V237 deterministic cropped terminal face transfer failed", exc)
            await delivery._safe_text(
                message,
                "❌ Не удалось выполнить обязательный перенос лица с фото №3. Черновая сцена не отправлена. "
                f"Причина: {type(exc).__name__}: {str(exc)[:500]}",
            )
            return False

    kwargs = {
        "remember_kind": "celebrity_selfie_v237_deterministic_cropped_terminal_face_transfer",
        "remember_payload": {
            "character": slug,
            "composition_provider": "google_gemini_direct",
            "identity_provider": "piapi_qubico_single_face_swap_on_local_crop",
            "stages": 3,
            "age_build_refs": 2,
            "hero_refs": 3,
            "terminal_face_source": "user_photo_3_detected_crop_only",
            "target_selection": "local_left_main_face_crop",
            "hero_and_scene_locked_during_swap": True,
            "multi_face_indexing_disabled": True,
            "no_composition_fallback": True,
        },
    }
    if delivery._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True
    await runner(
        update, context, int(user.id), "img",
        max(0.0, float(getattr(runtime, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)),
        action, **kwargs,
    )
    return bool(result["ok"])


__all__ = ["VERSION", "generate"]
