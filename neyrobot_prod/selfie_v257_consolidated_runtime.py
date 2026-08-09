# -*- coding: utf-8 -*-
"""V258 identity-quality runtime built on the consolidated V257 production path.

The existing Telegram UX/storage contract is preserved. Internally there is still
one generation owner and one terminal identity path:

photo 1-2 -> Gemini age/build/body references only
hero refs + scene -> Gemini scene/hero/body composition
strict PERSON A target lock -> one PiAPI swap using photo 3 only
edge-only local integration -> Telegram

V258 tightens the source/target crops used by the single PiAPI pass and rejects
undersized PERSON A faces so Gemini regenerates the composition once instead of
sending a weak target to Face Swap.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
import uuid
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v258-identity-quality-runtime-2026-08-09"
TRACE_PREFIX = "AI_SELFIE_V258"


def _trace(log: Any, trace: str, started: float, stage: str, **fields: Any) -> None:
    suffix = " ".join(f"{k}={v!r}" for k, v in fields.items())
    log(f"{TRACE_PREFIX} trace=%s stage=%s elapsed=%.2fs %s", trace, stage, time.monotonic() - started, suffix)


async def _heartbeat(log: Any, trace: str, started: float, stage_ref: dict[str, str], stop: asyncio.Event) -> None:
    interval = max(5.0, float(os.getenv("AI_SELFIE_LOG_HEARTBEAT_SEC") or "10"))
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            _trace(log, trace, started, "heartbeat", active_stage=stage_ref.get("value", "unknown"))


def _prompt(name: str, scene_text: str, shot_label: str, has_scene_image: bool, retry: bool) -> str:
    scene_rule = (
        "The first image is an AUTHORITATIVE LOCATION REFERENCE. Preserve the same place, architecture, furniture, materials, distinctive objects, windows, doors and spatial layout. You may make only a modest framing/camera-distance adjustment needed to stage the two people naturally. "
        if has_scene_image
        else (f"Create this scene faithfully: {scene_text}. " if scene_text else "Create a natural context appropriate to the selected hero. ")
    )
    retry_rule = (
        "The previous composition was rejected because PERSON A could not be safely isolated at sufficient resolution for terminal Face Swap. Make PERSON A clearly visible on the LEFT, closer to camera, with a substantially larger unobstructed near-frontal head. "
        if retry else ""
    )
    return (
        "Create one natural photorealistic vertical photograph with exactly two principal people. "
        f"SHOT MODE: {shot_label}. {scene_rule}{retry_rule}"
        "PERSON A is the USER BODY PLACEHOLDER and must be clearly on the LEFT. PERSON B must be clearly on the RIGHT. "
        "PERSON A's body, apparent age, height class, build, shoulder width, neck thickness and proportions come only from the two USER AGE/BUILD references. "
        "The USER AGE/BUILD references are NOT identity references. Do not copy or reconstruct their face identity. "
        "PERSON A must have a neutral temporary face, near-frontal, eyes open, mouth relaxed, no glasses, no hand or hair obstruction, with the whole head and jaw visible. "
        "PERSON A's detected face must be large enough for a later local Face Swap: target approximately 300-450 pixels high in the final generated image, never tiny or distant. "
        "Preserve age-appropriate skull, hairstyle, head-to-body ratio and anatomy. If the body references show a child or teenager, never give PERSON A adult facial mass, facial hair, mature neck or mature shoulders. "
        f"PERSON B is {name}. The HERO references are the exclusive identity authority for PERSON B; preserve the hero's recognizable face, age, hairstyle and distinctive features. "
        "Never blend PERSON A and PERSON B. Keep both principal faces separate. Avoid mirrors, portraits, posters, paintings or face-like decorations in the left upper background near PERSON A because the final pipeline must isolate PERSON A safely. "
        "Use realistic smartphone/event photography, natural skin texture, plausible ambient light and ordinary optics. No watermark or interface."
    )


def _v258_source(photo3: bytes, log: Any) -> fs.FaceTarget:
    """Create a face-centric source crop while preserving hair, ears and jaw."""
    detected = fs.source_face_crop(photo3, None)
    img = fs.image(photo3)
    # V257 could expand a large portrait face to the full 3:4 frame. V258 keeps
    # the detected identity dominant in the source presented to Qubico.
    crop_box = fs._expand(detected.face_box, img.size, 1.52, 1.66, 0.02)
    crop_img = img.crop(crop_box)
    raw = fs.jpeg(crop_img, max_side=1100, quality=97)
    fw, fh = detected.face_box[2], detected.face_box[3]
    cw, ch = crop_img.size
    face_w_coverage = fw / float(max(1, cw))
    face_h_coverage = fh / float(max(1, ch))
    result = fs.FaceTarget(
        detected.face_box,
        crop_box,
        raw,
        detected.support,
        detected.eye_count,
        detected.score,
    )
    log(
        "AI_SELFIE_V258_SOURCE face=%s crop=%s support=%s eyes=%s sha=%s dims=%s face_w_coverage=%.3f face_h_coverage=%.3f",
        result.face_box, result.crop_box, result.support, result.eye_count, fs.sha(raw), fs.dims(raw), face_w_coverage, face_h_coverage,
    )
    if face_w_coverage < 0.48 or face_h_coverage < 0.43:
        raise ValueError("photo #3 source crop is not face-centric enough for production Face Swap")
    return result


def _v258_target(composition: bytes, *, scene_image: bool, log: Any) -> tuple[Any, fs.FaceTarget, dict[str, float]]:
    """Use V257 safe localization, then enforce V258 resolution and crop quality."""
    base_img, located, metrics = fs.locate_person_a(composition, scene_image=scene_image, log=None)
    iw, ih = base_img.size
    face_h = int(located.face_box[3])
    ratio = face_h / float(max(1, ih))
    min_px = 280 if scene_image else 260
    min_ratio = 0.115 if scene_image else 0.108
    if face_h < min_px or ratio < min_ratio:
        raise ValueError(
            f"PERSON A face below V258 production resolution: face_h={face_h}px ratio={ratio:.4f} required={min_px}px/{min_ratio:.4f}"
        )

    crop_box = fs._expand(located.face_box, base_img.size, 2.15, 2.45, 0.015)
    crop_img = base_img.crop(crop_box)
    crop_raw = fs.jpeg(crop_img, max_side=1250, quality=97)
    fw, fh = located.face_box[2], located.face_box[3]
    cw, ch = crop_img.size
    metrics = dict(metrics)
    metrics.update({
        "v258_min_px": float(min_px),
        "v258_min_ratio": float(min_ratio),
        "target_face_w_coverage": fw / float(max(1, cw)),
        "target_face_h_coverage": fh / float(max(1, ch)),
    })
    target = fs.FaceTarget(
        located.face_box,
        crop_box,
        crop_raw,
        located.support,
        located.eye_count,
        located.score,
    )
    log(
        "AI_SELFIE_V258_TARGET face=%s crop=%s support=%s eyes=%s score=%.3f sha=%s dims=%s face_w_coverage=%.3f face_h_coverage=%.3f",
        target.face_box, target.crop_box, target.support, target.eye_count, target.score, fs.sha(crop_raw), fs.dims(crop_raw),
        metrics["target_face_w_coverage"], metrics["target_face_h_coverage"],
    )
    return base_img, target, metrics


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
    if not v229._key() or not str(os.getenv("PIAPI_API_KEY") or "").strip():
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

    photo3 = bytes(photos[2])
    body_refs = [
        ("USER AGE/BUILD REFERENCE 1: age, height class, build and body proportions only. NEVER use this image as face identity.", bytes(photos[0])),
        ("USER AGE/BUILD REFERENCE 2: body scale, shoulders, neck, limbs and age only. NEVER use this image as face identity.", bytes(photos[1])),
    ]
    hero_refs = [(f"HERO REFERENCE {idx}: exclusive PERSON B identity", path.read_bytes()) for idx, path in enumerate(hero_paths, 1)]
    has_scene_image = bool(scene_image and len(scene_image) > 1024)
    refs: list[tuple[str, bytes]] = []
    if has_scene_image:
        refs.append(("AUTHORITATIVE LOCATION REFERENCE ONLY: preserve this place. Do not interpret any face-like texture in the location as a person.", bytes(scene_image)))
    refs.extend(body_refs)
    refs.extend(hero_refs)
    result = {"ok": False}

    async def action() -> bool:
        trace = uuid.uuid4().hex[:12]
        started = time.monotonic()
        stage_ref = {"value": "source_prepare"}
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(_heartbeat(v229._log, trace, started, stage_ref, stop))
        try:
            _trace(v229._log, trace, started, "start", version=VERSION, user_id=int(user.id), character=slug, shot=shot_mode, scene_mode=scene_mode, photo3_sha=fs.sha(photo3), photo3_dims=fs.dims(photo3), photo3_bytes=len(photo3))

            source = _v258_source(photo3, v229._log)
            _trace(v229._log, trace, started, "source_ready", face=source.face_box, crop=source.crop_box, source_sha=fs.sha(source.crop_raw), source_dims=fs.dims(source.crop_raw), support=source.support, eyes=source.eye_count)

            await delivery._safe_text(message, "⏳ Этап 1/4: создаю сцену, героя и тело. Лицо пользователя пока не переносится.")
            stage_ref["value"] = "gemini_composition"

            composition = b""
            model = ""
            base_image = None
            target = None
            metrics: dict[str, float] = {}
            last_error: Exception | None = None
            for attempt in range(1, 3):
                try:
                    prompt = _prompt(str(meta["name"]), scene_text, v215._shot_label(shot_mode), has_scene_image, retry=(attempt > 1))
                    composition, model = await v229._call_google(prompt, refs, f"v258_scene_hero_body_attempt_{attempt}")
                    _trace(v229._log, trace, started, "composition_candidate", attempt=attempt, model=model, sha=fs.sha(composition), dims=fs.dims(composition), bytes=len(composition), scene_image=has_scene_image)
                    stage_ref["value"] = "person_a_target_lock"
                    base_image, target, metrics = _v258_target(composition, scene_image=has_scene_image, log=v229._log)
                    _trace(v229._log, trace, started, "target_ready", attempt=attempt, target_face=target.face_box, target_crop=target.crop_box, target_sha=fs.sha(target.crop_raw), target_dims=fs.dims(target.crop_raw), metrics=metrics)
                    break
                except Exception as exc:
                    last_error = exc
                    _trace(v229._log, trace, started, "composition_rejected", attempt=attempt, error_type=type(exc).__name__, error=str(exc)[:700])
                    if attempt == 1:
                        await delivery._safe_text(message, "🔎 Сцена создана, но лицо пользователя недостаточно крупное или безопасное для качественного переноса. Перестраиваю кадр один раз — PiAPI ещё не запускался.")
                        stage_ref["value"] = "gemini_composition_retry"
                        continue
                    raise

            if not composition or base_image is None or target is None:
                raise RuntimeError(f"no safe PERSON A target after composition retry: {last_error!r}")

            await delivery._safe_text(message, "🧬 Этап 2/4: переношу лицо с фото №3 через изолированный PiAPI Face Swap.")
            stage_ref["value"] = "piapi_identity_transfer"
            swapped = await fs.piapi_swap_once(target.crop_raw, source.crop_raw, v229._log, trace=trace)
            if fs.sha(swapped) == fs.sha(target.crop_raw):
                raise RuntimeError("PiAPI returned unchanged target crop")
            _trace(v229._log, trace, started, "piapi_ready", pass1_sha=fs.sha(swapped), pass1_dims=fs.dims(swapped), pass1_bytes=len(swapped), source_sha=fs.sha(source.crop_raw), target_sha=fs.sha(target.crop_raw))

            await delivery._safe_text(message, "🔬 Этап 3/4: закрепляю результат PiAPI в сцене без повторной генерации лица.")
            stage_ref["value"] = "edge_only_integration"
            final = fs.edge_composite(base_image, target, swapped)
            _trace(v229._log, trace, started, "final_ready", composition_sha=fs.sha(composition), piapi_sha=fs.sha(swapped), final_sha=fs.sha(final), final_dims=fs.dims(final), final_bytes=len(final), second_piapi=False, gemini_after_piapi=False, edge_only=True)

            await delivery._safe_text(message, "📤 Этап 4/4: отправляю итог. Сцена, герой и тело сохранены из Gemini; центральное лицо — результат PiAPI.")
            caption = (
                f"🎭 AI-фото с персонажем «{meta['name']}» готово ✅\n"
                "Маршрут V258: Gemini сцена+герой+тело → строгий выбор Person A → face-centric фото №3 → один PiAPI Face Swap → edge-only интеграция.\n"
                "Фото создано ИИ и не подтверждает реальную встречу или поддержку."
            )
            delivered = await delivery._deliver(message, final, caption, prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)))
            result["ok"] = bool(delivered)
            _trace(v229._log, trace, started, "delivery_done", delivered=bool(delivered))
            if delivered:
                await message.reply_text("✅ Что сделать дальше? Фото пользователя, герой, тип кадра и сцена сохранены.", reply_markup=v215._continuation_keyboard(runtime, slug))
            return bool(delivered)
        except Exception as exc:
            _trace(v229._log, trace, started, "failed", active_stage=stage_ref.get("value"), error_type=type(exc).__name__, error=str(exc)[:1200])
            delivery._log_exception(f"V258 trace={trace} identity-quality AI Selfie failed", exc)
            await delivery._safe_text(message, "❌ Не удалось безопасно завершить перенос лица. Черновая сцена не отправлена. " f"Код: {trace}. Причина: {type(exc).__name__}: {str(exc)[:420]}")
            return False
        finally:
            stop.set()
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await heartbeat
            _trace(v229._log, trace, started, "finished", ok=bool(result["ok"]))

    kwargs = {
        "remember_kind": "celebrity_selfie_v258_identity_quality",
        "remember_payload": {
            "character": slug,
            "composition_provider": "google_gemini_direct",
            "identity_provider": "piapi_qubico_single_pass",
            "terminal_face_source": "user_photo_3_face_centric_crop_only",
            "body_references": "user_photo_1_2_only",
            "strict_person_a_target": True,
            "v258_target_min_resolution": True,
            "unsafe_target_fallback": False,
            "second_face_swap": False,
            "gemini_after_piapi": False,
            "edge_only_integration": True,
            "scene_hero_locked": True,
        },
    }
    if delivery._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True
    await runner(update, context, int(user.id), "img", max(0.0, float(getattr(runtime, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)), action, **kwargs)
    return bool(result["ok"])


__all__ = ["VERSION", "TRACE_PREFIX", "generate"]
