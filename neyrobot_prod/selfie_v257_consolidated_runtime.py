# -*- coding: utf-8 -*-
"""Production AI selfie runtime with identity-first terminal face transfer.

Architecture:
- photos 1-2 -> age/build/body references only;
- Gemini -> scene, hero and neutral USER placeholder;
- strict PERSON A localization;
- photo 3 -> sole identity source;
- Replicate InSwapper (restore OFF) is preferred for identity preservation;
- PiAPI/Qubico is a production fallback;
- no Gemini call occurs after face transfer;
- provider output is integrated locally with a narrow feathered boundary.

Diagnostic SOURCE/TARGET/RAW documents are opt-in only through
AI_SELFIE_V259_DIAG_USER_IDS and are disabled by default.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
import uuid
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v260-production-identity-first-2026-08-14"
TRACE_PREFIX = "AI_SELFIE_V260"


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


def _diag_enabled(user_id: int) -> bool:
    raw = str(os.getenv("AI_SELFIE_V259_DIAG_USER_IDS") or "").strip()
    if not raw:
        return False
    if raw.lower() in {"*", "all"}:
        return True
    ids: set[int] = set()
    for token in raw.replace(";", ",").split(","):
        try:
            ids.add(int(token.strip()))
        except Exception:
            continue
    return int(user_id) in ids


async def _diag_document(delivery: Any, message: Any, payload: bytes, caption: str, log: Any, trace: str, stage: str) -> None:
    try:
        await delivery._send_document(message, bytes(payload), caption, timeout=240.0)
        log("AI_SELFIE_V260_DIAG trace=%s stage=%s status=sent sha=%s dims=%s bytes=%s", trace, stage, fs.sha(payload), fs.dims(payload), len(payload))
    except Exception as exc:
        log("AI_SELFIE_V260_DIAG trace=%s stage=%s status=failed error_type=%s error=%s", trace, stage, type(exc).__name__, str(exc)[:500])


def _prompt(name: str, scene_text: str, shot_label: str, has_scene_image: bool, retry: bool) -> str:
    scene_rule = (
        "The first image is an AUTHORITATIVE LOCATION REFERENCE. Preserve the same place, architecture, furniture, materials, distinctive objects, windows, doors and spatial layout. You may make only a modest framing/camera-distance adjustment needed to stage the two people naturally. "
        if has_scene_image
        else (f"Create this scene faithfully: {scene_text}. " if scene_text else "Create a natural context appropriate to the selected hero. ")
    )
    retry_rule = (
        "The previous composition was rejected because PERSON A was too small or unsafe for terminal face transfer. Make PERSON A clearly visible on the LEFT, closer to camera, with a substantially larger unobstructed near-frontal head. "
        if retry else ""
    )
    return (
        "Create one ordinary photorealistic vertical smartphone/event photograph with exactly two principal people. "
        f"SHOT MODE: {shot_label}. {scene_rule}{retry_rule}"
        "PERSON A is the USER BODY PLACEHOLDER and must be clearly on the LEFT. PERSON B must be clearly on the RIGHT. "
        "PERSON A's body, apparent age, height class, build, shoulder width, neck thickness and proportions come only from the two USER AGE/BUILD references. "
        "The USER AGE/BUILD references are NOT identity references. Do not copy or reconstruct their face identity. "
        "PERSON A must have a neutral temporary face, near-frontal, eyes open, mouth relaxed, no glasses, no hand or hair obstruction, whole head and jaw visible. "
        "PERSON A's face should be approximately 320-500 pixels high in the final image so a later local face transfer has enough real detail. "
        "Preserve age-appropriate skull, hairstyle, head-to-body ratio and anatomy. If the body references show a child or teenager, never give PERSON A adult facial mass, facial hair, mature neck or mature shoulders. "
        f"PERSON B is {name}. The HERO references are the exclusive identity authority for PERSON B; preserve the hero's recognizable face, age, hairstyle and distinctive features. "
        "Never blend PERSON A and PERSON B. Keep both principal faces separate. Avoid mirrors, portraits, posters, paintings or face-like decorations near PERSON A. "
        "PHOTOGRAPHY QUALITY: this must look like an unretouched real phone/camera photo, not CGI or an AI portrait. Preserve pores, fine skin texture, natural asymmetry, tiny imperfections, realistic hair strands, subtle sensor noise and plausible optical softness. No beauty retouching, no waxy/plastic skin, no airbrushing, no excessive HDR, no illustration, no 3D-render look, no watermark or interface."
    )


def _source(photo3: bytes, log: Any) -> fs.FaceTarget:
    detected = fs.source_face_crop(photo3, None)
    img = fs.image(photo3)
    crop_box = fs._expand(detected.face_box, img.size, 1.42, 1.56, 0.015)
    crop_img = img.crop(crop_box)
    raw = fs.jpeg(crop_img, max_side=1180, quality=98)
    fw, fh = detected.face_box[2], detected.face_box[3]
    cw, ch = crop_img.size
    face_w_coverage = fw / float(max(1, cw))
    face_h_coverage = fh / float(max(1, ch))
    result = fs.FaceTarget(detected.face_box, crop_box, raw, detected.support, detected.eye_count, detected.score)
    log("AI_SELFIE_V260_SOURCE face=%s crop=%s support=%s eyes=%s sha=%s dims=%s face_w_coverage=%.3f face_h_coverage=%.3f", result.face_box, result.crop_box, result.support, result.eye_count, fs.sha(raw), fs.dims(raw), face_w_coverage, face_h_coverage)
    if face_w_coverage < 0.56 or face_h_coverage < 0.50:
        raise ValueError("photo #3 source crop is not face-centric enough for production face transfer")
    return result


def _target(composition: bytes, *, scene_image: bool, log: Any) -> tuple[Any, fs.FaceTarget, dict[str, float]]:
    base_img, located, metrics = fs.locate_person_a(composition, scene_image=scene_image, log=None)
    _, ih = base_img.size
    face_h = int(located.face_box[3])
    ratio = face_h / float(max(1, ih))
    min_px = 270 if scene_image else 220
    min_ratio = 0.110 if scene_image else 0.095
    if face_h < min_px or ratio < min_ratio:
        raise ValueError(f"PERSON A face below production resolution: face_h={face_h}px ratio={ratio:.4f} required={min_px}px/{min_ratio:.4f}")

    # A tighter target crop gives the face-swap backend less generated background
    # to model and more pixels devoted to the identity-bearing face region.
    crop_box = fs._expand(located.face_box, base_img.size, 1.76, 2.02, 0.012)
    crop_img = base_img.crop(crop_box)
    crop_raw = fs.jpeg(crop_img, max_side=1280, quality=98)
    fw, fh = located.face_box[2], located.face_box[3]
    cw, ch = crop_img.size
    metrics = dict(metrics)
    metrics.update({
        "min_px": float(min_px),
        "min_ratio": float(min_ratio),
        "target_face_w_coverage": fw / float(max(1, cw)),
        "target_face_h_coverage": fh / float(max(1, ch)),
    })
    target = fs.FaceTarget(located.face_box, crop_box, crop_raw, located.support, located.eye_count, located.score)
    log("AI_SELFIE_V260_TARGET face=%s crop=%s support=%s eyes=%s score=%.3f sha=%s dims=%s face_w_coverage=%.3f face_h_coverage=%.3f", target.face_box, target.crop_box, target.support, target.eye_count, target.score, fs.sha(crop_raw), fs.dims(crop_raw), metrics["target_face_w_coverage"], metrics["target_face_h_coverage"])
    return base_img, target, metrics


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    """Prefer identity-preserving InSwapper; fall back to PiAPI/Qubico."""
    replicate_token = str(os.getenv("REPLICATE_API_TOKEN") or "").strip()
    if replicate_token:
        try:
            from neyrobot_prod import selfie_v252_faceswap_quality_diag as ins
            inputs = {
                "upscale": 1,
                "source_img": ins._data_url(source_crop),
                "target_img": ins._data_url(target_crop),
                "face_restore": False,
                "face_upsample": False,
                "source_indexes": "-1",
                "target_indexes": "-1",
                "background_enhance": False,
                "codeformer_fidelity": 1.0,
            }
            log("AI_SELFIE_V260_IDENTITY trace=%s provider=replicate_inswapper stage=create target_sha=%s source_sha=%s", trace, fs.sha(target_crop), fs.sha(source_crop))
            raw = await ins._replicate_swap_once(version=ins.REPLICATE_INSWAPPER_VERSION, inputs=inputs, trace=trace, label="v260_prod_inswapper")
            if len(raw) >= 1024 and fs.sha(raw) != fs.sha(target_crop):
                log("AI_SELFIE_V260_IDENTITY trace=%s provider=replicate_inswapper stage=success sha=%s dims=%s bytes=%s", trace, fs.sha(raw), fs.dims(raw), len(raw))
                return raw, "replicate_inswapper_restore_off"
            raise RuntimeError("InSwapper returned unchanged/empty target")
        except Exception as exc:
            log("AI_SELFIE_V260_IDENTITY trace=%s provider=replicate_inswapper stage=fallback error_type=%s error=%s", trace, type(exc).__name__, str(exc)[:700])

    if str(os.getenv("PIAPI_API_KEY") or "").strip():
        raw = await fs.piapi_swap_once(target_crop, source_crop, log, trace=trace)
        if fs.sha(raw) == fs.sha(target_crop):
            raise RuntimeError("PiAPI returned unchanged target crop")
        return raw, "piapi_qubico"

    raise RuntimeError("No Face Swap provider configured (REPLICATE_API_TOKEN or PIAPI_API_KEY)")


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
    if not v229._key() or not (str(os.getenv("REPLICATE_API_TOKEN") or "").strip() or str(os.getenv("PIAPI_API_KEY") or "").strip()):
        await delivery._safe_text(message, "❌ Не настроен сервис переноса лица. Средства не списаны.")
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
        diag = _diag_enabled(int(user.id))
        try:
            _trace(v229._log, trace, started, "start", version=VERSION, user_id=int(user.id), diagnostic=diag, character=slug, shot=shot_mode, scene_mode=scene_mode, photo3_sha=fs.sha(photo3), photo3_dims=fs.dims(photo3), photo3_bytes=len(photo3))
            await delivery._safe_text(message, "✅ Сцена выбрана. Создание AI-фото началось — готовлю композицию и перенос лица. Обычно это занимает несколько минут.")

            source = _source(photo3, v229._log)
            _trace(v229._log, trace, started, "source_ready", face=source.face_box, crop=source.crop_box, source_sha=fs.sha(source.crop_raw), source_dims=fs.dims(source.crop_raw), support=source.support, eyes=source.eye_count)
            if diag:
                await _diag_document(delivery, message, source.crop_raw, f"DIAG SOURCE\ntrace={trace}\nsha={fs.sha(source.crop_raw)} dims={fs.dims(source.crop_raw)}", v229._log, trace, "source")

            await delivery._safe_text(message, "⏳ Этап 1/3: создаю сцену и персонажей.")
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
                    composition, model = await v229._call_google(prompt, refs, f"v260_scene_hero_body_attempt_{attempt}")
                    _trace(v229._log, trace, started, "composition_candidate", attempt=attempt, model=model, sha=fs.sha(composition), dims=fs.dims(composition), bytes=len(composition), scene_image=has_scene_image)
                    stage_ref["value"] = "person_a_target_lock"
                    base_image, target, metrics = _target(composition, scene_image=has_scene_image, log=v229._log)
                    _trace(v229._log, trace, started, "target_ready", attempt=attempt, target_face=target.face_box, target_crop=target.crop_box, target_sha=fs.sha(target.crop_raw), target_dims=fs.dims(target.crop_raw), metrics=metrics)
                    break
                except Exception as exc:
                    last_error = exc
                    _trace(v229._log, trace, started, "composition_rejected", attempt=attempt, error_type=type(exc).__name__, error=str(exc)[:700])
                    if attempt == 1:
                        await delivery._safe_text(message, "🔎 Композицию нужно немного перестроить для качественного переноса лица. Делаю ещё один вариант.")
                        stage_ref["value"] = "gemini_composition_retry"
                        continue
                    raise
            if not composition or base_image is None or target is None:
                raise RuntimeError(f"no safe PERSON A target after composition retry: {last_error!r}")
            if diag:
                await _diag_document(delivery, message, target.crop_raw, f"DIAG TARGET\ntrace={trace}\nsha={fs.sha(target.crop_raw)} dims={fs.dims(target.crop_raw)}", v229._log, trace, "target")

            await delivery._safe_text(message, "🧬 Этап 2/3: переношу лицо с вашей портретной фотографии.")
            stage_ref["value"] = "identity_transfer"
            swapped, identity_provider = await _identity_swap(target.crop_raw, source.crop_raw, v229._log, trace=trace)
            _trace(v229._log, trace, started, "identity_ready", provider=identity_provider, swapped_sha=fs.sha(swapped), swapped_dims=fs.dims(swapped), swapped_bytes=len(swapped), source_sha=fs.sha(source.crop_raw), target_sha=fs.sha(target.crop_raw))
            if diag:
                await _diag_document(delivery, message, swapped, f"DIAG RAW FACE SWAP\nprovider={identity_provider}\ntrace={trace}\nsha={fs.sha(swapped)} dims={fs.dims(swapped)}", v229._log, trace, "faceswap_raw")

            stage_ref["value"] = "integration"
            final = fs.edge_composite(base_image, target, swapped)
            _trace(v229._log, trace, started, "final_ready", composition_sha=fs.sha(composition), swapped_sha=fs.sha(swapped), final_sha=fs.sha(final), final_dims=fs.dims(final), final_bytes=len(final), identity_provider=identity_provider, gemini_after_faceswap=False, edge_only=True)

            await delivery._safe_text(message, "📤 Этап 3/3: готово, отправляю итоговое фото.")
            caption = f"🎭 AI-фото с персонажем «{meta['name']}» готово ✅\nФото создано ИИ и не подтверждает реальную встречу или поддержку."
            delivered = await delivery._deliver(message, final, caption, prefer_document=bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", True)))
            result["ok"] = bool(delivered)
            _trace(v229._log, trace, started, "delivery_done", delivered=bool(delivered), identity_provider=identity_provider)
            if delivered:
                await message.reply_text("✅ Что сделать дальше? Фото пользователя, герой, тип кадра и сцена сохранены.", reply_markup=v215._continuation_keyboard(runtime, slug))
            return bool(delivered)
        except Exception as exc:
            _trace(v229._log, trace, started, "failed", active_stage=stage_ref.get("value"), error_type=type(exc).__name__, error=str(exc)[:1200])
            delivery._log_exception(f"V260 trace={trace} production AI Selfie failed", exc)
            await delivery._safe_text(message, "❌ Не удалось завершить AI-фото. " f"Код: {trace}. Причина: {type(exc).__name__}: {str(exc)[:320]}")
            return False
        finally:
            stop.set()
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await heartbeat
            _trace(v229._log, trace, started, "finished", ok=bool(result["ok"]))

    kwargs = {
        "remember_kind": "celebrity_selfie_v260_production_identity_first",
        "remember_payload": {
            "character": slug,
            "composition_provider": "google_gemini_direct",
            "identity_provider": "replicate_inswapper_restore_off_preferred_piapi_fallback",
            "terminal_face_source": "user_photo_3_face_centric_crop_only",
            "body_references": "user_photo_1_2_only",
            "strict_person_a_target": True,
            "diagnostic_outputs_opt_in": True,
            "unsafe_target_fallback": False,
            "gemini_after_faceswap": False,
            "edge_only_integration": True,
            "scene_hero_locked": True,
        },
    }
    if delivery._runner_accepts_silent_failure(runner):
        kwargs["silent_failure"] = True
    await runner(update, context, int(user.id), "img", max(0.0, float(getattr(runtime, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)), action, **kwargs)
    return bool(result["ok"])


__all__ = ["VERSION", "TRACE_PREFIX", "generate"]
