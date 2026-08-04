# -*- coding: utf-8 -*-
"""V234 terminal user-only identity transfer for Celebrity Selfie.

The proven V232/V219 UI, scene selection and hero references remain untouched.
Generation is split into two isolated operations:

1. composition: build the scene, pose, bodies and PERSON B (hero).  User photo #3
   is deliberately excluded from this pass so the renderer cannot blend the
   user's face into the hero;
2. terminal transfer: use the completed composition as the authoritative base
   and photo #3 as the single authoritative source for PERSON A's face.

There is no successful fallback to the composition image.  If the terminal
identity pass fails, the request fails visibly instead of returning a merely
similar generated person.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any

VERSION = "v234-terminal-user-only-transfer-2026-08-05"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(bytes(raw or b"")).hexdigest()[:12]


def _stage1_prompt(name: str, scene: str, shot_label: str, has_scene_image: bool) -> str:
    scene_rule = (
        "The first image is the authoritative scene base. Preserve its exact architecture, "
        "camera, crop, perspective, lighting and object positions. "
        if has_scene_image else f"Create this scene faithfully: {scene}. "
    )
    return (
        "Create one natural photorealistic vertical photograph with exactly two principal people. "
        f"SHOT MODE: {shot_label}. {scene_rule}"
        "PERSON A is the user body placeholder. The user body references define only height, build, "
        "age range, posture and clothing scale. Do not copy their face and do not use their identity "
        "for PERSON B. Keep PERSON A near-frontal or at no more than 20 degrees yaw, with the whole "
        "face visible, unobstructed and large enough for a later identity transfer. "
        f"PERSON B is {name}. The three HERO references are the exclusive identity authority for "
        "PERSON B. Preserve the hero's face, age, hairstyle and distinctive features. Never blend "
        "PERSON A and PERSON B. No profile views. No duplicate people. "
        "Use realistic smartphone or event photography: natural skin texture, ordinary optics, "
        "subtle sensor noise and plausible ambient light. Do not show a phone unless the requested "
        "scene explicitly requires a visible phone. No text, logos, watermark or interface."
    )


def _transfer_prompt(name: str) -> str:
    return (
        "TERMINAL USER FACE TRANSFER. IMAGE 1 is the authoritative completed photograph. IMAGE 2 is "
        "the sole authoritative identity source for PERSON A. Return the same photograph and replace "
        "only PERSON A's facial identity with the exact identity from IMAGE 2. This is not a new "
        "generation and not a beautification. Preserve PERSON A's real eye shape and spacing, nose, "
        "lips, jaw, chin, cheeks, forehead, ears, skin texture, asymmetry and apparent age. Adapt only "
        "lighting and perspective required to seat that face naturally in the target head. "
        "Hard-lock every pixel outside PERSON A's face and immediate hairline/neck blending boundary: "
        "scene, crop, resolution, body, pose, hands, clothes, background, objects and all other people. "
        f"PERSON B is {name}; do not alter PERSON B in any way. Do not transfer the user onto PERSON B. "
        "Exactly two principal people must remain. Do not blur, cover or omit PERSON A's face. Output "
        "one photorealistic image only."
    )


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

    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await delivery._safe_text(message, "❌ Платёжный guard генераций не найден. Средства не списаны.")
        return False

    hero_paths = base._reference_paths(runtime, slug)
    if len(hero_paths) != 3:
        await delivery._safe_text(message, f"❌ Для героя не хватает референсов: {len(hero_paths)}/3.")
        return False

    # Photo #3 is reserved exclusively for the terminal identity transfer.
    body_refs = [
        ("USER BODY REFERENCE 1: body proportions only; ignore facial identity", bytes(photos[0])),
        ("USER BODY REFERENCE 2: body proportions only; ignore facial identity", bytes(photos[1])),
    ]
    hero_refs = [
        (f"HERO REFERENCE {idx}: exclusive PERSON B identity", path.read_bytes())
        for idx, path in enumerate(hero_paths, 1)
    ]
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
                "AI_SELFIE_V234_START user_id=%s character=%s body_refs=2 hero_refs=3 face3_sha=%s crop_sha=%s",
                int(user.id), slug, _sha(face_original), _sha(face_crop),
            )
            await delivery._safe_text(message, "⏳ Этап 1/2: создаю сцену и героя. Фото лица №3 на этом этапе не используется.")
            composition, model1 = await v229._call_google(
                _stage1_prompt(str(meta["name"]), scene_text, v215._shot_label(shot_mode), has_scene_image),
                stage1_refs,
                "v234_scene_and_hero",
            )
            v229._log("AI_SELFIE_V234_COMPOSITION_OK bytes=%s sha=%s model=%s", len(composition), _sha(composition), model1)

            await delivery._safe_text(message, "🧬 Этап 2/2: переношу лицо только с фотографии №3. Сцена и герой заблокированы.")
            transfer_refs = [
                ("IMAGE 1 — AUTHORITATIVE COMPLETED COMPOSITION", composition),
                ("IMAGE 2 — USER PHOTO #3, SOLE FACE IDENTITY SOURCE", face_crop),
            ]
            final, model2 = await v229._call_google(
                _transfer_prompt(str(meta["name"])),
                transfer_refs,
                "v234_terminal_user_face_transfer",
            )
            if not final or len(final) < 1024:
                raise RuntimeError("terminal face transfer returned an empty image")
            if _sha(final) == _sha(composition):
                raise RuntimeError("terminal face transfer returned an unchanged composition")

            v229._log("AI_SELFIE_V234_TRANSFER_OK bytes=%s sha=%s model=%s", len(final), _sha(final), model2)
            caption = (
                f"🎭 AI-фото с персонажем «{meta['name']}» готово ✅\n"
                f"Маршрут: сцена+герой → отдельный перенос лица пользователя с фото №3. "
                f"Модели: {model1} → {model2}.\n"
                "Фото создано ИИ и не подтверждает реальную встречу или поддержку."
            )
            delivered = await delivery._deliver(
                message,
                final,
                caption,
                prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)),
            )
            result["ok"] = bool(delivered)
            if delivered:
                await message.reply_text(
                    "✅ Что сделать дальше? Фото пользователя, герой, тип кадра и сцена сохранены.",
                    reply_markup=v215._continuation_keyboard(runtime, slug),
                )
            return bool(delivered)
        except Exception as exc:
            delivery._log_exception("V234 terminal user face transfer failed", exc)
            await delivery._safe_text(
                message,
                "❌ Не удалось выполнить обязательный перенос лица с фото №3. "
                "Черновая сцена не отправлена, чтобы не выдавать просто похожего человека. "
                f"Причина: {type(exc).__name__}: {str(exc)[:500]}",
            )
            return False

    kwargs = {
        "remember_kind": "celebrity_selfie_v234_terminal_user_transfer",
        "remember_payload": {
            "character": slug,
            "provider": "google_gemini_direct",
            "stages": 2,
            "body_refs": 2,
            "hero_refs": 3,
            "terminal_face_source": "user_photo_3_only",
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
