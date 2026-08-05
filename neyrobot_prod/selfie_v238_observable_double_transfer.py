# -*- coding: utf-8 -*-
"""V238 observable two-pass terminal identity transfer.

The Gemini composition remains untouched. User identity is applied only after scene/body/hero
generation, in two isolated PiAPI face-swap passes. Every material stage emits a Render-visible
log line with one trace id, elapsed time, dimensions, hashes and crop coordinates.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
import uuid
from io import BytesIO
from typing import Any

from neyrobot_prod import selfie_v234_terminal_user_transfer as v237

VERSION = "v238-observable-double-terminal-face-transfer-2026-08-05"


def _dims(raw: bytes) -> str:
    try:
        return "%sx%s" % v237._image(raw).size
    except Exception:
        return "invalid"


def _trace_log(log: Any, trace: str, started: float, stage: str, **fields: Any) -> None:
    elapsed = time.monotonic() - started
    suffix = " ".join(f"{key}={value!r}" for key, value in fields.items())
    log("AI_SELFIE_V238 trace=%s stage=%s elapsed=%.2fs %s", trace, stage, elapsed, suffix)


async def _heartbeat(log: Any, trace: str, started: float, stage_ref: dict[str, str], stop: asyncio.Event) -> None:
    interval = max(5.0, float(os.getenv("AI_SELFIE_LOG_HEARTBEAT_SEC") or "10"))
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            _trace_log(log, trace, started, "heartbeat", active_stage=stage_ref.get("value", "unknown"))


def _expanded_local_box(box: tuple[int, int, int, int], size: tuple[int, int], wf: float, hf: float, ys: float = 0.0) -> tuple[int, int, int, int]:
    return v237._expanded_box(box, size, width_factor=wf, height_factor=hf, y_shift=ys)


def _single_face_tight_crop(raw: bytes, *, wf: float, hf: float, ys: float = 0.0) -> tuple[Any, tuple[int, int, int, int], bytes, tuple[int, int, int, int]]:
    image = v237._image(raw)
    faces = v237._detect_faces(image)
    if not faces:
        raise ValueError("no frontal face detected for tight terminal pass")
    face = max(faces, key=lambda item: item[2] * item[3])
    box = _expanded_local_box(face, image.size, wf, hf, ys)
    return image, box, v237._jpeg(image.crop(box), max_side=1100), face


def _masked_composite(base: Any, box: tuple[int, int, int, int], overlay_raw: bytes, *, oval: bool = True, blur_ratio: float = 0.035) -> Any:
    from PIL import Image, ImageDraw, ImageFilter

    left, top, right, bottom = box
    width, height = right - left, bottom - top
    overlay = v237._image(overlay_raw).resize((width, height), Image.LANCZOS)
    original = base.crop(box)
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    mx = max(3, int(width * 0.06))
    my = max(3, int(height * 0.045))
    shape = (mx, my, width - mx, height - my)
    if oval:
        draw.ellipse(shape, fill=255)
    else:
        draw.rounded_rectangle(shape, radius=max(12, int(min(width, height) * 0.18)), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(4, int(min(width, height) * blur_ratio))))
    merged = Image.composite(overlay, original, mask)
    output = base.copy()
    output.paste(merged, (left, top))
    return output


def _refine_pass1(pass1_raw: bytes, source_raw: bytes, pass2_raw: bytes, pass1_box: tuple[int, int, int, int]) -> bytes:
    pass1_image = v237._image(pass1_raw)
    merged = _masked_composite(pass1_image, pass1_box, pass2_raw, oval=True, blur_ratio=0.025)
    return v237._jpeg(merged, max_side=1600, quality=97)


def _composite_face_only(base_image: Any, target_crop_box: tuple[int, int, int, int], target_face: tuple[int, int, int, int], refined_crop_raw: bytes) -> bytes:
    from PIL import Image

    crop_left, crop_top, crop_right, crop_bottom = target_crop_box
    crop_w, crop_h = crop_right - crop_left, crop_bottom - crop_top
    refined_crop = v237._image(refined_crop_raw).resize((crop_w, crop_h), Image.LANCZOS)

    fx, fy, fw, fh = target_face
    local_face = (fx - crop_left, fy - crop_top, fw, fh)
    face_region = _expanded_local_box(local_face, (crop_w, crop_h), 1.48, 1.72, 0.02)
    locked_crop = base_image.crop(target_crop_box)
    merged_crop = _masked_composite(locked_crop, face_region, v237._jpeg(refined_crop.crop(face_region), max_side=1000), oval=True, blur_ratio=0.03)

    output = base_image.copy()
    output.paste(merged_crop, (crop_left, crop_top))
    return v237._jpeg(output, max_side=2048, quality=97)


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
    if not v229._key() or not v237._piapi_key():
        await delivery._safe_text(message, "❌ Не настроены обязательные ключи Gemini/PiAPI. Средства не списаны.")
        return False

    runner = getattr(runtime, "_try_pay_then_do", None)
    if not callable(runner):
        await delivery._safe_text(message, "❌ Платёжный guard генераций не найден. Средства не списаны.")
        return False

    hero_paths = base._reference_paths(runtime, slug)
    if len(hero_paths) != 3:
        await delivery._safe_text(message, f"❌ Для героя не хватает референсов: {len(hero_paths)}/3.")
        return False

    face_original = bytes(photos[2])
    body_refs = [
        ("USER AGE/BUILD REFERENCE 1: age, body scale and proportions only; ignore identity", bytes(photos[0])),
        ("USER AGE/BUILD REFERENCE 2: age, shoulders, neck, limbs and build only; ignore identity", bytes(photos[1])),
    ]
    hero_refs = [(f"HERO REFERENCE {idx}: exclusive PERSON B identity", path.read_bytes()) for idx, path in enumerate(hero_paths, 1)]
    has_scene_image = bool(scene_image and len(scene_image) > 1024)
    refs: list[tuple[str, bytes]] = []
    if has_scene_image:
        refs.append(("AUTHORITATIVE SCENE BASE", bytes(scene_image)))
    refs.extend(body_refs)
    refs.extend(hero_refs)
    result = {"ok": False}

    async def action() -> bool:
        trace = uuid.uuid4().hex[:12]
        started = time.monotonic()
        stage_ref = {"value": "initializing"}
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(_heartbeat(v229._log, trace, started, stage_ref, stop))
        try:
            _trace_log(v229._log, trace, started, "start", version=VERSION, user_id=int(user.id), character=slug, shot=shot_mode, scene_mode=scene_mode, photo3_bytes=len(face_original), photo3_dims=_dims(face_original), photo3_sha=v237._sha(face_original))

            stage_ref["value"] = "source_prepare"
            source_crop, source_box = v237._source_face_crop(face_original)
            _, source_tight_box, source_tight, source_tight_face = _single_face_tight_crop(face_original, wf=1.55, hf=1.82, ys=0.0)
            _trace_log(v229._log, trace, started, "source_ready", source_box=source_box, source_crop_dims=_dims(source_crop), source_crop_sha=v237._sha(source_crop), source_tight_box=source_tight_box, source_tight_face=source_tight_face, source_tight_dims=_dims(source_tight), source_tight_sha=v237._sha(source_tight))

            await delivery._safe_text(message, "⏳ Этап 1/4: создаю сцену, героя и тело. Лицо пользователя пока не переносится.")
            stage_ref["value"] = "gemini_composition"
            composition, model1 = await v229._call_google(
                v237._stage1_prompt(str(meta["name"]), scene_text, v215._shot_label(shot_mode), has_scene_image),
                refs,
                "v238_scene_hero_body_locked",
            )
            _trace_log(v229._log, trace, started, "composition_ready", model=model1, bytes=len(composition), dims=_dims(composition), sha=v237._sha(composition))

            stage_ref["value"] = "target_detection"
            base_image, target_box, target_crop, target_face = v237._target_face_crop(composition)
            _trace_log(v229._log, trace, started, "target_locked", all_faces=v237._detect_faces(base_image), target_face=target_face, target_crop_box=target_box, target_crop_dims=_dims(target_crop), target_crop_sha=v237._sha(target_crop))

            await delivery._safe_text(message, "🧬 Этап 2/4: первый изолированный перенос лица с фото №3.")
            stage_ref["value"] = "piapi_pass1"
            pass1 = await v237._piapi_single_face_swap(target_crop, source_crop, v229._log)
            _trace_log(v229._log, trace, started, "pass1_ready", bytes=len(pass1), dims=_dims(pass1), sha=v237._sha(pass1), changed=(v237._sha(pass1) != v237._sha(target_crop)))

            await delivery._safe_text(message, "🔬 Этап 3/4: повторно закрепляю личность на более тесном овале лица.")
            stage_ref["value"] = "pass1_tight_detection"
            _, pass1_tight_box, pass1_tight, pass1_face = _single_face_tight_crop(pass1, wf=1.55, hf=1.82, ys=0.0)
            _trace_log(v229._log, trace, started, "pass2_input_ready", pass1_face=pass1_face, pass1_tight_box=pass1_tight_box, target_dims=_dims(pass1_tight), target_sha=v237._sha(pass1_tight), source_dims=_dims(source_tight), source_sha=v237._sha(source_tight))

            stage_ref["value"] = "piapi_pass2"
            pass2 = await v237._piapi_single_face_swap(pass1_tight, source_tight, v229._log)
            _trace_log(v229._log, trace, started, "pass2_ready", bytes=len(pass2), dims=_dims(pass2), sha=v237._sha(pass2), changed=(v237._sha(pass2) != v237._sha(pass1_tight)))

            stage_ref["value"] = "local_composite"
            refined_crop = _refine_pass1(pass1, source_tight, pass2, pass1_tight_box)
            final = _composite_face_only(base_image, target_box, target_face, refined_crop)
            _trace_log(v229._log, trace, started, "final_ready", composition_sha=v237._sha(composition), pass1_sha=v237._sha(pass1), pass2_sha=v237._sha(pass2), refined_sha=v237._sha(refined_crop), final_sha=v237._sha(final), final_dims=_dims(final), final_bytes=len(final))

            await delivery._safe_text(message, "📤 Этап 4/4: отправляю итог. Сцена и герой сохранены из первой генерации.")
            caption = (
                f"🎭 AI-фото с персонажем «{meta['name']}» готово ✅\n"
                "Маршрут V238: Gemini сцена+герой+тело → PiAPI перенос №1 → тесный PiAPI перенос №2 → локальное овальное наложение в исходную сцену.\n"
                "Фото создано ИИ и не подтверждает реальную встречу или поддержку."
            )
            delivered = await delivery._deliver(message, final, caption, prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)))
            result["ok"] = bool(delivered)
            _trace_log(v229._log, trace, started, "delivery_done", delivered=bool(delivered))
            if delivered:
                await message.reply_text("✅ Что сделать дальше? Фото пользователя, герой, тип кадра и сцена сохранены.", reply_markup=v215._continuation_keyboard(runtime, slug))
            return bool(delivered)
        except Exception as exc:
            _trace_log(v229._log, trace, started, "failed", error_type=type(exc).__name__, error=str(exc)[:900], active_stage=stage_ref.get("value"))
            delivery._log_exception(f"V238 trace={trace} observable double terminal transfer failed", exc)
            await delivery._safe_text(message, "❌ Не удалось завершить обязательный перенос лица. Черновая сцена не отправлена. " f"Код трассировки: {trace}. Причина: {type(exc).__name__}: {str(exc)[:350]}")
            return False
        finally:
            stop.set()
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await heartbeat
            _trace_log(v229._log, trace, started, "finished", ok=bool(result["ok"]))

    kwargs = {
        "remember_kind": "celebrity_selfie_v238_observable_double_terminal_transfer",
        "remember_payload": {
            "character": slug,
            "composition_provider": "google_gemini_direct",
            "identity_provider": "piapi_qubico_two_pass_local_face_swap",
            "stages": 4,
            "terminal_face_source": "user_photo_3_only",
            "scene_hero_locked": True,
            "render_trace_logs": True,
            "heartbeat_logs": True,
            "double_face_swap": True,
            "final_face_only_oval_composite": True,
            "no_composition_fallback": True,
        },
    }
    if delivery._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True
    await runner(update, context, int(user.id), "img", max(0.0, float(getattr(runtime, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)), action, **kwargs)
    return bool(result["ok"])


__all__ = ["VERSION", "generate"]
