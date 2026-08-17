# -*- coding: utf-8 -*-
"""V234: stable V232 scene generation + authoritative real FaceSwap.

This module deliberately separates composition from identity. Gemini creates only the
scene/body/pose and is instructed to expose PERSON A in a transfer-friendly pose that
matches the chosen real source photo's head angle and expression. A real FaceSwap then
replaces PERSON A's face. A very-early Telegram callback owner prevents legacy V219
Comet generation handlers from winning the same button press.
"""
from __future__ import annotations

import contextlib
import hashlib
import threading
import time
from typing import Any

VERSION = "v234-v232-scene-authoritative-faceswap-expression-2026-08-17"
_HANDLER_FLAG = "_neyrobot_v234_real_faceswap_handler"
_STARTED = False
_GENERATION_PATTERN = r"^(?:cs201:preset:|cs201:generate_current$|cs201:reuse:repeat$)"


def _runtime() -> Any | None:
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    return v229._runtime()


def _log(message: str, *args: Any) -> None:
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    v229._log(message, *args)


def _face_area(face: dict[str, Any]) -> int:
    try:
        return max(1, int(face.get("w", 0))) * max(1, int(face.get("h", 0)))
    except Exception:
        return 0


def _detect(runtime: Any, image: bytes) -> list[dict[str, Any]]:
    detector = getattr(runtime, "_detect_faces_for_choice", None)
    if not callable(detector):
        return []
    try:
        return [dict(x) for x in (detector(bytes(image)) or [])]
    except Exception:
        return []


def _select_source_photo(runtime: Any, photos: list[bytes]) -> tuple[bytes, int, dict[str, Any] | None]:
    """Pick the strongest clean single-face source. Prefer #3 only on a true tie."""
    candidates: list[tuple[int, int, bytes, dict[str, Any]]] = []
    for idx, raw in enumerate(photos, 1):
        faces = _detect(runtime, bytes(raw))
        if len(faces) == 1:
            candidates.append((_face_area(faces[0]), idx, bytes(raw), faces[0]))
    if candidates:
        _, idx, raw, face = max(candidates, key=lambda item: (item[0], item[1]))
        return raw, idx, face
    raw = bytes(photos[-1])
    faces = _detect(runtime, raw)
    face = max(faces, key=_face_area) if faces else None
    return raw, 3, face


def _select_person_a_face(runtime: Any, image: bytes) -> dict[str, Any]:
    """Choose PERSON A from the two dominant faces; V234 forces PERSON A to the left."""
    faces = _detect(runtime, image)
    if len(faces) < 2:
        raise RuntimeError(f"expected at least 2 faces in composition, detected {len(faces)}")
    principal = sorted(faces, key=_face_area, reverse=True)[:2]
    person_a = min(principal, key=lambda f: (int(f.get("cx", f.get("x", 0))), int(f.get("cy", f.get("y", 0)))))
    _log(
        "AI_SELFIE_V234_TARGET faces=%s selected_display=%s api_index=%s box=%sx%s@%s,%s",
        len(faces), person_a.get("display_index"), person_a.get("api_index"),
        person_a.get("w"), person_a.get("h"), person_a.get("x"), person_a.get("y"),
    )
    return dict(person_a)


def _stage1_prompt(name: str, scene: str, shot_label: str, has_scene_image: bool, source_photo_no: int) -> str:
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    base_prompt = v229._stage1_prompt(name, scene, shot_label, has_scene_image)
    return (
        base_prompt
        + f" AUTHORITATIVE FACE-TRANSFER SOURCE is the specially labelled USER SOURCE PHOTO #{source_photo_no}. "
        + "Do NOT invent a new facial identity for PERSON A. Build PERSON A's body, hair, head placement and lighting, but make the face transfer-friendly. "
        + "PERSON A must be the LEFT principal person and PERSON B the RIGHT principal person. "
        + "Match PERSON A's HEAD ANGLE, FACIAL EXPRESSION, mouth openness/smile, eyebrow state and eye direction as closely as possible to the AUTHORITATIVE FACE-TRANSFER SOURCE. "
        + "Keep PERSON A near-frontal or only a very mild three-quarter angle, upright head, no strong yaw/pitch/roll, no hand or hair covering the face, no glasses added, no extreme grin, no profile. "
        + "PERSON A's face must be large and sharp: target face width at least about 22% of image width and fully inside frame. "
        + "The later stage will physically replace PERSON A's face, therefore pose/expression compatibility is more important than synthesizing PERSON A's facial details. "
        + "Do not place any extra/background face to the left of PERSON A."
    )


async def _true_face_transfer(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int) -> tuple[bytes, str]:
    target_face = _select_person_a_face(runtime, stage1)
    target_index = int(target_face.get("api_index", 0) or 0)

    segmind = getattr(runtime, "_segmind_faceswap_v2", None)
    piapi = getattr(runtime, "_piapi_faceswap", None)
    composite = getattr(runtime, "_faceswap_composite_selected_region", None)
    normalize = getattr(runtime, "_maybe_resize_output_image", None)

    errors: list[str] = []
    swapped: bytes | None = None
    provider = ""
    before_sha = hashlib.sha256(stage1).hexdigest()[:12]

    # Indexed Segmind is authoritative for a two-person image.
    if callable(segmind) and bool(getattr(runtime, "SEGMIND_API_KEY", "")):
        try:
            _log("AI_SELFIE_V234_TRANSFER provider=segmind_v2 target_index=%s source_photo=%s", target_index, source_photo_no)
            candidate = await segmind(stage1, source, target_index=target_index, source_index=0)
            if candidate and len(candidate) > 1024 and hashlib.sha256(bytes(candidate)).hexdigest()[:12] != before_sha:
                swapped = bytes(candidate)
                provider = "segmind_faceswap_v2"
            else:
                errors.append("segmind:no_effect_or_empty")
        except Exception as exc:
            errors.append(f"segmind:{type(exc).__name__}:{exc}")

    # PiAPI is fallback only. Never silently return the synthetic Gemini face.
    if swapped is None and callable(piapi) and bool(getattr(runtime, "PIAPI_API_KEY", "")):
        try:
            _log("AI_SELFIE_V234_TRANSFER provider=piapi target_index=%s source_photo=%s", target_index, source_photo_no)
            candidate = await piapi(stage1, source, quality="fast", target_index=target_index, source_index=0)
            if candidate and len(candidate) > 1024 and hashlib.sha256(bytes(candidate)).hexdigest()[:12] != before_sha:
                swapped = bytes(candidate)
                provider = "piapi_faceswap"
            else:
                errors.append("piapi:no_effect_or_empty")
        except Exception as exc:
            errors.append(f"piapi:{type(exc).__name__}:{exc}")

    if swapped is None:
        raise RuntimeError("real FaceSwap produced no usable face transfer: " + (" | ".join(errors) if errors else "no provider configured"))

    # Preserve the successful Gemini scene and the celebrity exactly; integrate only PERSON A.
    if callable(composite):
        try:
            swapped = bytes(composite(stage1, swapped, target_face))
        except Exception as exc:
            errors.append(f"composite:{type(exc).__name__}:{exc}")
    if callable(normalize):
        with contextlib.suppress(Exception):
            swapped = bytes(normalize(swapped))

    _log(
        "AI_SELFIE_V234_TRANSFER status=success provider=%s source_photo=%s target_index=%s before_sha=%s after_sha=%s bytes=%s",
        provider, source_photo_no, target_index, before_sha, hashlib.sha256(swapped).hexdigest()[:12], len(swapped),
    )
    return swapped, provider


async def generate(update: Any, context: Any, scene: str = "") -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v211_delivery as delivery
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229

    runtime = _runtime()
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
        await delivery._safe_text(message, "❌ Отсутствует GEMINI_IMAGE_API_KEY.")
        return False
    if not (bool(getattr(runtime, "SEGMIND_API_KEY", "")) or bool(getattr(runtime, "PIAPI_API_KEY", ""))):
        await delivery._safe_text(message, "❌ Для реального переноса лица нужен SEGMIND_API_KEY или PIAPI_API_KEY.")
        return False

    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await delivery._safe_text(message, "❌ Платёжный guard генераций не найден. Средства не списаны.")
        return False

    source, source_photo_no, _ = _select_source_photo(runtime, photos)
    result = {"ok": False}
    user_refs, hero_refs = v229._identity_refs(photos, slug)
    has_scene_image = bool(scene_image and len(scene_image) > 1024)
    stage1_refs: list[tuple[str, bytes]] = []
    if has_scene_image:
        stage1_refs.append(("AUTHORITATIVE SCENE BASE: preserve exact location and composition", bytes(scene_image)))
    # Make the exact FaceSwap source explicit to Gemini so expression/head pose is compatible.
    stage1_refs.append((f"AUTHORITATIVE FACE-TRANSFER SOURCE — USER PHOTO #{source_photo_no}: match head angle and expression", source))
    stage1_refs.extend(user_refs)
    stage1_refs.extend(hero_refs)

    async def action() -> bool:
        try:
            await delivery._safe_text(message, f"⏳ Этап 1/2: создаю сцену и ставлю лицо пользователя в позу под прямой перенос. Источник лица — фото №{source_photo_no}.")
            stage1, model1 = await v229._call_google(
                _stage1_prompt(str(meta['name']), scene_text, v215._shot_label(shot_mode), has_scene_image, source_photo_no),
                stage1_refs,
                "composition_for_real_faceswap",
            )
            await delivery._safe_text(message, "🧬 Этап 2/2: выполняю реальный FaceSwap — переношу лицо с исходного фото, а не генерирую его заново.")
            final, provider = await _true_face_transfer(runtime, stage1, source, source_photo_no)

            caption = (
                f"🎭 AI-селфи с персонажем «{meta['name']}» готово ✅\n"
                f"Сцена: Gemini {model1}. Лицо пользователя: реальный FaceSwap ({provider}), источник — фото №{source_photo_no}.\n"
                "Поза и выражение лица в сцене предварительно согласованы с исходным фото; герой и фон сохранены локальным композитингом. "
                "Изображение создано ИИ и не подтверждает реальную встречу или поддержку."
            )
            delivered = await delivery._deliver(message, final, caption, prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)))
            result["ok"] = bool(delivered)
            if delivered:
                await message.reply_text("✅ Что сделать дальше? Три фото пользователя, герой, тип кадра и сцена сохранены.", reply_markup=v215._continuation_keyboard(runtime, slug))
            return bool(delivered)
        except Exception as exc:
            delivery._log_exception("V234 authoritative real face-transfer selfie failed", exc)
            await delivery._safe_text(message, f"❌ Реальный перенос лица не выполнен; синтетическое лицо не отправляю. Причина: {type(exc).__name__}: {str(exc)[:700]}")
            return False

    kwargs = {
        "remember_kind": "celebrity_selfie_v234_authoritative_faceswap",
        "remember_payload": {
            "character": slug, "scene_provider": "google_gemini_direct",
            "identity_provider": "segmind_v2_then_piapi", "stages": 2,
            "source_photo": source_photo_no, "expression_pose_lock": True,
        },
    }
    if delivery._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True
    await runner(update, context, int(user.id), "img", max(0.0, float(getattr(runtime, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)), action, **kwargs)
    return bool(result["ok"])


async def generation_callback(update: Any, context: Any) -> None:
    """Hard owner for the three generation buttons; runs before every legacy callback."""
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219

    query = getattr(update, "callback_query", None)
    if query is None:
        return
    data = str(query.data or "")
    with contextlib.suppress(Exception):
        await query.answer()

    if data.startswith("cs201:preset:"):
        key = data.rsplit(":", 1)[-1]
        preset = base.SCENES.get(key)
        if preset:
            context.user_data["cs215_scene_mode"] = v215.SCENE_PRESET
            context.user_data["cs215_scene_text"] = v215._clean_preset_scene(preset[1])
            context.user_data.pop("cs215_scene_image", None)
            await generate(update, context, context.user_data["cs215_scene_text"])
        else:
            await query.message.reply_text("Выберите готовую сцену:", reply_markup=v215._preset_keyboard(_runtime()))
        raise ApplicationHandlerStop

    if data in {"cs201:generate_current", "cs201:reuse:repeat"}:
        if v219._scene_ready(context):
            await generate(update, context, str(context.user_data.get("cs215_scene_text") or ""))
        else:
            await query.message.reply_text("Сцена ещё не задана.", reply_markup=v215._scene_source_keyboard(_runtime()))
        raise ApplicationHandlerStop


def bind_application(app: Any) -> bool:
    if app is None or not callable(getattr(app, "add_handler", None)):
        return False
    if getattr(app, _HANDLER_FLAG, False):
        return True
    from telegram.ext import CallbackQueryHandler
    # PTB evaluates lower-numbered groups first. This group is intentionally far
    # ahead of every historical selfie owner; ApplicationHandlerStop blocks the rest.
    app.add_handler(CallbackQueryHandler(generation_callback, pattern=_GENERATION_PATTERN), group=-1000000)
    setattr(app, _HANDLER_FLAG, True)
    _log("AI_SELFIE_V234_BIND status=ok group=-1000000")
    return True


def _bind_runtime_apps() -> None:
    runtime = _runtime()
    if runtime is None:
        return
    for value in list(vars(runtime).values()):
        with contextlib.suppress(Exception):
            bind_application(value)


def install() -> None:
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    v229.generate = generate
    v229.VERSION = VERSION
    v219.generate = generate
    with contextlib.suppress(Exception):
        v219.public_callback.__globals__["generate"] = generate
    _bind_runtime_apps()
    _log("[neyrobot-prod] V234 authoritative real FaceSwap overlay installed")


def install_async() -> None:
    global _STARTED
    install()
    if _STARTED:
        return
    _STARTED = True

    def worker() -> None:
        while True:
            try:
                install()
            except Exception as exc:
                _log("AI_SELFIE_V234_OWNER repair failed: %r", exc)
            time.sleep(0.25)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v234-authoritative-faceswap").start()


__all__ = ["VERSION", "generate", "generation_callback", "bind_application", "install", "install_async"]
