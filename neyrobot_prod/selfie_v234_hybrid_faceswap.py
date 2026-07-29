# -*- coding: utf-8 -*-
"""V234 hybrid Celebrity Selfie owner.

Pipeline:
1. Google Gemini creates the scene, celebrity, user body, clothing and pose.
2. PiAPI Qubico FaceSwap transfers the user's actual source face into a
   deliberately isolated crop containing PERSON A only.
3. Optional PiAPI face enhancement is applied to that crop, then the crop is
   composited back into the unchanged Gemini frame.

The previous production state is preserved on
backup/v233-2026-07-29-before-v234.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import io
import os
import time
from typing import Any

from PIL import Image

from neyrobot_prod import selfie_v233_body_face_transplant as v233

VERSION = "v234-selfie-hybrid-real-faceswap-2026-07-29"


def _runtime() -> Any | None:
    return v233._runtime()


def _log(message: str, *args: Any) -> None:
    v233._log(message, *args)


def _piapi_key() -> str:
    return (os.environ.get("PIAPI_API_KEY") or "").strip()


def _fp(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else "missing"


def _data_uri(raw: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _extract_url(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("http://") or text.startswith("https://") or text.startswith("data:image/"):
            return text
        return None
    if isinstance(value, dict):
        preferred = (
            "image_url", "image", "url", "output_url", "result_url",
            "temporary_url", "download_url",
        )
        for key in preferred:
            found = _extract_url(value.get(key))
            if found:
                return found
        for item in value.values():
            found = _extract_url(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _extract_url(item)
            if found:
                return found
    return None


async def _download_result(client: Any, value: str) -> bytes:
    if value.startswith("data:image/"):
        return base64.b64decode(value.split(",", 1)[1])
    response = await client.get(value)
    response.raise_for_status()
    return bytes(response.content)


async def _piapi_task(task_type: str, input_payload: dict[str, Any], stage: str) -> bytes:
    import httpx

    key = _piapi_key()
    if not key:
        raise RuntimeError("PIAPI_API_KEY is missing")
    base_url = (os.environ.get("PIAPI_BASE_URL") or "https://api.piapi.ai").rstrip("/")
    create_path = os.environ.get("PIAPI_FACE_CREATE_PATH") or "/api/v1/task"
    status_path = os.environ.get("PIAPI_FACE_STATUS_PATH") or "/api/v1/task/{task_id}"
    timeout_s = max(120.0, float(os.environ.get("FACESWAP_TIMEOUT_S", "300") or 300))
    poll_s = max(1.0, float(os.environ.get("FACESWAP_POLL_DELAY_S", "2.5") or 2.5))
    headers = {"x-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
    payload = {
        "model": os.environ.get("PIAPI_FACE_MODEL") or "Qubico/image-toolkit",
        "task_type": task_type,
        "input": input_payload,
    }
    _log("AI_SELFIE_V234_STAGE_START stage=%s provider=PiAPI-Qubico key_fp=%s task=%s", stage, _fp(key), task_type)
    timeout = httpx.Timeout(timeout_s, connect=45.0, read=timeout_s, write=120.0, pool=45.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        created = await client.post(base_url + create_path, headers=headers, json=payload)
        if created.status_code >= 400:
            raise RuntimeError(f"PiAPI create HTTP {created.status_code}: {created.text[:700]}")
        body = created.json()
        data = body.get("data") if isinstance(body, dict) else None
        task_id = (data or {}).get("task_id") if isinstance(data, dict) else None
        if not task_id:
            direct = _extract_url(body)
            if direct:
                return await _download_result(client, direct)
            raise RuntimeError(f"PiAPI returned no task_id: {str(body)[:700]}")
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            await asyncio.sleep(poll_s)
            status = await client.get(base_url + status_path.format(task_id=task_id), headers=headers)
            if status.status_code >= 400:
                raise RuntimeError(f"PiAPI status HTTP {status.status_code}: {status.text[:700]}")
            result = status.json()
            current = str(((result.get("data") or {}).get("status") if isinstance(result, dict) else "") or "").lower()
            if current in {"completed", "success", "succeeded", "finished"}:
                url = _extract_url((result.get("data") or {}).get("output")) or _extract_url(result)
                if not url:
                    raise RuntimeError(f"PiAPI completed without output URL: {str(result)[:900]}")
                output = await _download_result(client, url)
                if len(output) < 1024:
                    raise RuntimeError("PiAPI returned an empty image")
                _log("AI_SELFIE_V234_STAGE_SUCCESS stage=%s task=%s bytes=%s key_fp=%s", stage, task_type, len(output), _fp(key))
                return output
            if current in {"failed", "error", "cancelled", "canceled"}:
                raise RuntimeError(f"PiAPI task failed: {str(result)[:900]}")
        raise RuntimeError(f"PiAPI task timed out after {timeout_s:.0f}s")


def _jpeg(raw: bytes, quality: int = 95) -> bytes:
    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=quality, subsampling=0)
        return output.getvalue()


def _user_crop(base_raw: bytes) -> tuple[bytes, tuple[int, int, int, int], tuple[int, int]]:
    """Crop the left-side PERSON A zone, intentionally excluding PERSON B."""
    with Image.open(io.BytesIO(base_raw)) as image:
        image = image.convert("RGB")
        width, height = image.size
        # Stage 1 is instructed to place PERSON A on the left. Keep enough head,
        # shoulder and surrounding pixels for natural FaceSwap blending while
        # excluding the celebrity on the right.
        left = 0
        top = 0
        right = max(256, int(width * float(os.environ.get("SELFIE_USER_CROP_RIGHT_RATIO", "0.56") or 0.56)))
        bottom = height
        box = (left, top, min(width, right), bottom)
        crop = image.crop(box)
        output = io.BytesIO()
        crop.save(output, format="JPEG", quality=96, subsampling=0)
        return output.getvalue(), box, (width, height)


def _paste_crop(base_raw: bytes, crop_raw: bytes, box: tuple[int, int, int, int]) -> bytes:
    with Image.open(io.BytesIO(base_raw)) as base_image, Image.open(io.BytesIO(crop_raw)) as crop_image:
        base_image = base_image.convert("RGB")
        expected = (box[2] - box[0], box[3] - box[1])
        crop_image = crop_image.convert("RGB").resize(expected, Image.Resampling.LANCZOS)
        base_image.paste(crop_image, (box[0], box[1]))
        output = io.BytesIO()
        base_image.save(output, format="JPEG", quality=96, subsampling=0)
        return output.getvalue()


def _stage1_prompt(name: str, scene: str, shot_label: str, has_scene_image: bool) -> str:
    scene_rule = (
        "The first reference is the authoritative location. Preserve its architecture, furniture, viewpoint, crop, perspective and lighting. "
        if has_scene_image else f"Create the requested scene faithfully: {scene}. "
    )
    return (
        "HYBRID COMPOSITION PASS. Create one photorealistic vertical photograph with exactly two principal people. "
        f"SHOT MODE: {shot_label}. {scene_rule}"
        "MANDATORY LAYOUT: PERSON A (the user) must be on the LEFT side of the image, with the complete head fully inside the left 45 percent of the frame. PERSON B must be on the RIGHT side and must not overlap PERSON A's head. "
        "PERSON A's face must be unobstructed, near-frontal or mild three-quarter, at least 180 pixels high in the final image, with no hand, glasses, hair or shadow covering key facial features. "
        "The FULL-BODY reference is authoritative for PERSON A's height impression, shoulder width, torso volume, waist, arms, posture, body proportions, clothing category and realistic fit. Do not slim, enlarge, athleticize or redesign PERSON A. "
        "The user portraits provide provisional placement identity only; a dedicated deterministic FaceSwap stage will replace PERSON A's face afterward. Keep the head angle natural and compatible with the frontal source portrait. "
        f"PERSON B is {name}; the hero portraits are authoritative. Maximize PERSON B identity fidelity and keep PERSON B entirely outside the left user crop. "
        "Use realistic anatomy, optics, skin texture and lighting. No text, watermark or interface."
    )


async def generate(update: Any, context: Any, scene: str = "") -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v211_delivery as delivery
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219

    runtime = _runtime()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    if runtime is None or user is None or message is None:
        return False

    slug = str(context.user_data.get("cs201_character") or "")
    meta = base.CHARACTERS.get(slug)
    faces = v219._photos(context)
    full_body = v233._full_body(context)
    shot_mode = str(context.user_data.get("cs215_shot_mode") or "")
    scene_mode = str(context.user_data.get("cs215_scene_mode") or "")
    scene_text = str(scene or context.user_data.get("cs215_scene_text") or "").strip()
    scene_image = bytes(context.user_data.get("cs215_scene_image") or b"") if scene_mode == v215.SCENE_IMAGE else None

    if not meta or len(faces) != 3 or shot_mode not in {v215.SHOT_SELFIE, v215.SHOT_THIRD_PERSON} or not v219._scene_ready(context):
        await delivery._safe_text(message, "❌ Не хватает данных: нужны 3 портрета пользователя, фото в полный рост, герой, тип кадра и сцена.")
        return False
    if not full_body:
        await message.reply_text("🧍 Для точного гибридного режима обязательно отдельное фото пользователя в полный рост.", reply_markup=v233._body_button(runtime))
        return False
    if not v233._key():
        await delivery._safe_text(message, "❌ Отсутствует GEMINI_IMAGE_API_KEY.")
        return False
    if not _piapi_key():
        await delivery._safe_text(message, "❌ Отсутствует PIAPI_API_KEY для настоящего переноса лица.")
        return False

    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await delivery._safe_text(message, "❌ Платёжный guard генераций не найден. Средства не списаны.")
        return False

    _face_refs, hero_refs = v233._face_and_hero_refs(faces, slug)
    has_scene_image = bool(scene_image and len(scene_image) > 1024)
    stage1_refs: list[tuple[str, bytes]] = []
    if has_scene_image:
        stage1_refs.append(("AUTHORITATIVE SCENE BASE", bytes(scene_image)))
    stage1_refs.append(("USER FULL-BODY: authoritative body proportions, build, posture and clothing", full_body))
    stage1_refs.extend([(f"USER PORTRAIT {idx}: provisional face placement", raw) for idx, raw in enumerate(faces, 1)])
    stage1_refs.extend(hero_refs)
    result = {"ok": False}

    async def action() -> bool:
        try:
            await delivery._safe_text(message, f"⏳ Этап 1/3: создаю сцену, героя, тело, одежду и позу пользователя. Референсов: {len(stage1_refs)}.")
            stage1, google_model = await v233._call_google(
                _stage1_prompt(str(meta["name"]), scene_text, v215._shot_label(shot_mode), has_scene_image),
                stage1_refs,
                "v234_scene_body_composition",
            )

            await delivery._safe_text(message, "🧬 Этап 2/3: вырезаю область пользователя и переношу на неё лицо из исходного портрета через специализированный FaceSwap. Герой и правая часть кадра не обрабатываются.")
            target_crop, crop_box, _size = _user_crop(stage1)
            source_face = _jpeg(faces[0], 96)
            swapped_crop = await _piapi_task(
                "face-swap",
                {"target_image": _data_uri(target_crop), "swap_image": _data_uri(source_face)},
                "real_user_face_swap",
            )

            final_crop = swapped_crop
            restored = False
            if str(os.environ.get("SELFIE_FACESWAP_RESTORE", "1")).lower() not in {"0", "false", "no", "off"}:
                await delivery._safe_text(message, "🔎 Этап 3/3: восстанавливаю детали перенесённого лица и возвращаю обработанный фрагмент в неизменённый исходный кадр.")
                try:
                    final_crop = await _piapi_task(
                        "upscale",
                        {"image": _data_uri(swapped_crop), "scale": 2, "face_enhance": True},
                        "face_restore",
                    )
                    restored = True
                except Exception as restore_exc:
                    _log("AI_SELFIE_V234_RESTORE_FALLBACK reason=%r", restore_exc)
            else:
                await delivery._safe_text(message, "🔎 Этап 3/3: возвращаю перенесённое лицо в исходный кадр без повторной генерации сцены.")

            final = _paste_crop(stage1, final_crop, crop_box)
            caption = (
                f"🎭 AI-фото с персонажем «{meta['name']}» готово ✅\n"
                f"Маршрут: Google Gemini ({google_model}) → PiAPI FaceSwap → {'Face Restore' if restored else 'точная вставка без restore'}.\n"
                "Тело и одежда: отдельное фото в полный рост. Лицо пользователя перенесено специализированным FaceSwap только в левую область PERSON A; герой и остальная сцена не проходили повторную генерацию. "
                "Изображение создано ИИ и не подтверждает реальную встречу или поддержку."
            )
            delivered = await delivery._deliver(message, final, caption, prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)))
            result["ok"] = bool(delivered)
            if delivered:
                await message.reply_text("✅ Портреты, фото в полный рост, герой, тип кадра и сцена сохранены.", reply_markup=v215._continuation_keyboard(runtime, slug))
            return bool(delivered)
        except Exception as exc:
            delivery._log_exception("V234 hybrid real FaceSwap failed", exc)
            await delivery._safe_text(message, f"❌ Гибридный маршрут не создал изображение. Причина: {type(exc).__name__}: {str(exc)[:700]}")
            return False

    kwargs = {
        "remember_kind": "celebrity_selfie_v234_hybrid_faceswap",
        "remember_payload": {
            "character": slug,
            "provider": "google_gemini_plus_piapi_faceswap",
            "stages": 3,
            "user_portraits": 3,
            "user_full_body": True,
            "hero_refs": 3,
            "scene_image": has_scene_image,
            "real_faceswap": True,
        },
    }
    if delivery._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True
    cost = max(0.0, float(os.environ.get("AI_SELFIE_HYBRID_UNIT_COST_USD", "0.35") or 0.35))
    await runner(update, context, int(user.id), "img", cost, action, **kwargs)
    return bool(result["ok"])


def bind_application(app: Any) -> bool:
    # Reuse V233's full-body media handler and canonical callback handler. The
    # callback resolves v233.generate dynamically, which patch_runtime replaces.
    return v233.bind_application(app)


def patch_runtime() -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v208_overlay as v208
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v217_user_triref as v217
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219

    v233.generate = generate
    base._generate = generate
    v208._generate = generate
    v215.generate = generate
    v217.generate = generate
    v219.generate = generate
    v219.public_callback.__globals__["generate"] = generate
    v219._main_keyboard = v233._patched_main_keyboard

    async def _disabled_comet(*args: Any, **kwargs: Any):
        raise RuntimeError("Legacy Comet selfie route is disabled by V234")
    v219._comet_generate = _disabled_comet

    runtime = _runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v234-google-scene-plus-piapi-real-faceswap-crop-composite"
        runtime.AI_SELFIE_PROVIDER = "Google Gemini + PiAPI FaceSwap"
        runtime.AI_SELFIE_ACTIVE_KEY_ENV = "GEMINI_IMAGE_API_KEY + PIAPI_API_KEY"
        runtime.AI_SELFIE_GENERATION_STAGES = 3
        runtime.AI_SELFIE_USER_FACE_REFERENCES = 3
        runtime.AI_SELFIE_USER_FULL_BODY_REFERENCES = 1
        runtime.AI_SELFIE_HERO_REFERENCES = 3
        runtime.AI_SELFIE_REAL_FACESWAP = True
        for value in list(vars(runtime).values()):
            with contextlib.suppress(Exception):
                bind_application(value)
    return True


def install_async() -> None:
    v233.install_async()
    patch_runtime()


def install() -> None:
    install_async()


__all__ = ["VERSION", "generate", "bind_application", "patch_runtime", "install_async", "install"]
