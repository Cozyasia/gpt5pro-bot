# -*- coding: utf-8 -*-
"""V236 terminal user-only identity transfer for Celebrity Selfie.

Stage 1 keeps the proven Gemini scene/hero composition, but now treats the
user references as authoritative for apparent age, body scale and proportions.
Stage 2 uses PiAPI's dedicated multi-face-swap endpoint and replaces only
PERSON A with user photo #3.

Required Render variable: PIAPI_API_KEY
Optional variables:
  PIAPI_FACE_SWAP_TARGET_INDEX=0   # PERSON A is forced to the left in stage 1
  PIAPI_FACE_SWAP_TIMEOUT_SEC=150
  PIAPI_FACE_SWAP_POLL_SEC=2
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
from typing import Any

import httpx

VERSION = "v236-age-locked-piapi-terminal-face-swap-2026-08-05"
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
        "PERSON A is the user body placeholder and MUST stand on the LEFT side of the frame. "
        "PERSON B must stand on the RIGHT. Keep a clear horizontal separation between their faces. "
        "The two USER AGE/BUILD references are the authoritative source for PERSON A's apparent age, "
        "height class, body scale, shoulder width, neck thickness, limb proportions and overall build. "
        "Match that apparent age exactly. If the references show a child or teenager, PERSON A MUST remain "
        "a child or teenager of the same apparent age. NEVER age up a minor and NEVER substitute an adult body, "
        "adult skull, adult jaw, adult neck, broad adult shoulders, facial hair, age lines or mature facial mass. "
        "For a minor, use age-appropriate head-to-body ratio, narrow shoulders, slim neck, youthful jaw and limbs. "
        "Do not copy the user's facial identity during stage 1; create only a neutral temporary face with the correct "
        "age geometry so a later deterministic face swap can fit naturally. PERSON A must be near-frontal, at no more "
        "than 15 degrees yaw, with the whole face visible, unobstructed, evenly lit and at least 180 pixels high. "
        "Do not let PERSON B overlap PERSON A's face. Do not make PERSON A older, heavier, taller or more muscular than "
        "the user references. The final composition must visibly read as the same age group as the user references. "
        f"PERSON B is {name}. The three HERO references are the exclusive identity authority for PERSON B. "
        "Preserve the hero's face, age, hairstyle and distinctive features. Never blend PERSON A and PERSON B. "
        "No profile views. No duplicate people. No identity mixing. Use realistic smartphone or event photography: "
        "natural skin texture, ordinary optics, subtle sensor noise and plausible ambient light. Do not show a phone "
        "unless the requested scene explicitly requires a visible phone. No text, logos, watermark or interface."
    )


def _piapi_key() -> str:
    return str(os.getenv("PIAPI_API_KEY") or "").strip()


def _target_index() -> str:
    raw = str(os.getenv("PIAPI_FACE_SWAP_TARGET_INDEX") or "0").strip()
    return raw if raw.isdigit() else "0"


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
                    if isinstance(value, str):
                        return value
    return ""


async def _piapi_face_swap(composition: bytes, face_source: bytes, log: Any) -> bytes:
    key = _piapi_key()
    if not key:
        raise RuntimeError("PIAPI_API_KEY is missing")

    target_index = _target_index()
    timeout_sec = max(30.0, float(os.getenv("PIAPI_FACE_SWAP_TIMEOUT_SEC") or "150"))
    poll_sec = max(1.0, float(os.getenv("PIAPI_FACE_SWAP_POLL_SEC") or "2"))
    headers = {"x-api-key": key, "Content-Type": "application/json"}
    body = {
        "model": "Qubico/image-toolkit",
        "task_type": "multi-face-swap",
        "input": {
            "swap_image": _b64(face_source),
            "target_image": _b64(composition),
            "swap_faces_index": "0",
            "target_faces_index": target_index,
        },
        "config": {"webhook_config": {"endpoint": "", "secret": ""}},
    }

    limits = httpx.Limits(max_connections=5, max_keepalive_connections=2)
    async with httpx.AsyncClient(timeout=httpx.Timeout(35.0), limits=limits) as client:
        response = await client.post(PIAPI_TASK_URL, headers=headers, json=body)
        response.raise_for_status()
        created = response.json()
        data = created.get("data") if isinstance(created, dict) else None
        task_id = str((data or {}).get("task_id") or "").strip()
        if not task_id:
            raise RuntimeError(f"PiAPI did not return task_id: {str(created)[:500]}")
        log("AI_SELFIE_V236_PIAPI_CREATED task_id=%s target_index=%s", task_id, target_index)

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
                log("AI_SELFIE_V236_PIAPI_STATUS task_id=%s status=%s", task_id, status)
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


async def generate(update: Any, context: Any, scene: str = "") -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v211_delivery as delivery
    from neyrobot_prod import selfie_v213_user_identity_lock as identity
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
        (
            "USER AGE/BUILD REFERENCE 1: authoritative apparent age, body scale and proportions only; "
            "if this person is a child or teenager, keep PERSON A the same apparent age; ignore facial identity",
            bytes(photos[0]),
        ),
        (
            "USER AGE/BUILD REFERENCE 2: authoritative apparent age, shoulder width, neck thickness, limb proportions "
            "and build only; never age up a minor; ignore facial identity",
            bytes(photos[1]),
        ),
    ]
    hero_refs = [(f"HERO REFERENCE {idx}: exclusive PERSON B identity", path.read_bytes()) for idx, path in enumerate(hero_paths, 1)]
    face_original = bytes(photos[2])
    face_crop = identity._user_face_crop(face_original)
    has_scene_image = bool(scene_image and len(scene_image) > 1024)

    stage1_refs: list[tuple[str, bytes]] = []
    if has_scene_image:
        stage1_refs.append(("AUTHORITATIVE SCENE BASE", bytes(scene_image)))
    stage1_refs.extend(body_refs)
    stage1_refs.extend(hero_refs)
    result = {"ok": False}

    async def action() -> bool:
        try:
            v229._log(
                "AI_SELFIE_V236_START user_id=%s character=%s age_build_refs=2 hero_refs=3 face3_sha=%s crop_sha=%s target_index=%s",
                int(user.id), slug, _sha(face_original), _sha(face_crop), _target_index(),
            )
            await delivery._safe_text(
                message,
                "⏳ Этап 1/2: создаю сцену, героя и возрастно-точное тело пользователя. Лицо пока не переносится.",
            )
            composition, model1 = await v229._call_google(
                _stage1_prompt(str(meta["name"]), scene_text, v215._shot_label(shot_mode), has_scene_image),
                stage1_refs,
                "v236_age_locked_scene_and_hero",
            )
            v229._log("AI_SELFIE_V236_COMPOSITION_OK bytes=%s sha=%s model=%s", len(composition), _sha(composition), model1)

            await delivery._safe_text(message, "🧬 Этап 2/2: выполняю отдельный face swap с фото №3. Gemini на этом этапе не используется.")
            final = await _piapi_face_swap(composition, face_crop, v229._log)
            if _sha(final) == _sha(composition):
                raise RuntimeError("face swap returned unchanged composition")
            v229._log("AI_SELFIE_V236_FACE_SWAP_OK bytes=%s sha=%s", len(final), _sha(final))

            caption = (
                f"🎭 AI-фото с персонажем «{meta['name']}» готово ✅\n"
                "Маршрут: Gemini сцена+герой+возрастно-точное тело → PiAPI face swap пользователя с фото №3.\n"
                "Фото создано ИИ и не подтверждает реальную встречу или поддержку."
            )
            delivered = await delivery._deliver(message, final, caption, prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)))
            result["ok"] = bool(delivered)
            if delivered:
                await message.reply_text("✅ Что сделать дальше? Фото пользователя, герой, тип кадра и сцена сохранены.", reply_markup=v215._continuation_keyboard(runtime, slug))
            return bool(delivered)
        except Exception as exc:
            delivery._log_exception("V236 age-locked PiAPI terminal face swap failed", exc)
            await delivery._safe_text(
                message,
                "❌ Не удалось выполнить обязательный перенос лица с фото №3. Черновая сцена не отправлена. "
                f"Причина: {type(exc).__name__}: {str(exc)[:500]}",
            )
            return False

    kwargs = {
        "remember_kind": "celebrity_selfie_v236_age_locked_piapi_terminal_face_swap",
        "remember_payload": {
            "character": slug,
            "composition_provider": "google_gemini_direct",
            "identity_provider": "piapi_qubico_multi_face_swap",
            "stages": 2,
            "age_build_refs": 2,
            "hero_refs": 3,
            "terminal_face_source": "user_photo_3_only",
            "target_face_index": _target_index(),
            "minor_age_up_forbidden": True,
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
