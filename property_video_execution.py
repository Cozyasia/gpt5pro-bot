"""Paid, durable execution for the property-video wizard."""
from __future__ import annotations

import json
import logging
import math
import os
import asyncio
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

from property_video_billing import (
    _connect,
    claim_assembly,
    job_metadata,
    mark_delivered,
    mark_delivery_unknown,
    record_operation,
    record_result,
    refund_before_submission,
    reserve,
    status,
)
from property_video_pipeline import (
    PropertyVideoError,
    assemble_property_video,
    plan_property_scenes,
    render_scene_to_file,
    resolve_reference_aspect,
    inspect_property_video,
    scene_manifest,
    scene_prompt,
)
from real_estate_pipeline import fetch_telegram_photos
from property_video_director import analyse_reference_photos
from property_video_audio import (
    create_narration_plan,
    mix_property_audio,
    recover_music_track,
    recover_voice_track,
    render_music_track,
    render_voice_track,
    sound_has_music,
    sound_has_voice,
    validate_sound_mode,
)

log = logging.getLogger(__name__)


def is_property_video_owner_free(user_id: int, username: str | None = None) -> bool:
    """Return whether this account may run provider-backed owner tests for free."""
    enabled = os.getenv("PROPERTY_VIDEO_OWNER_FREE_ENABLED", "1").strip().lower()
    if enabled not in ("1", "true", "yes", "on"):
        return False
    try:
        import main as production_main
        unlimited = getattr(production_main, "is_unlimited", None)
        if callable(unlimited) and unlimited(int(user_id), username):
            return True
    except Exception:
        pass
    try:
        owner_id = int(os.getenv("OWNER_ID", "0") or "0")
    except (TypeError, ValueError):
        owner_id = 0
    if not owner_id:
        try:
            import main as production_main
            owner_id = int(getattr(production_main, "OWNER_ID", 0) or 0)
        except Exception:
            owner_id = 0
    return owner_id > 0 and int(user_id) == owner_id


def _provider_cost(engine: str, scenes) -> float:
    engine = engine.lower()
    if engine == "veo":
        per_second = float(os.getenv("VEO_FAST_COST_PER_SECOND_USD", "0.096"))
        return round(len(scenes) * 8 * per_second, 4)
    if engine == "kling":
        five_second = float(os.getenv("KLING_5S_COST_USD", os.getenv("KLING_UNIT_COST_USD", "0.23")))
        return round(sum(max(1, math.ceil(scene.seconds / 5)) * five_second for scene in scenes), 4)
    per_second = float(os.getenv("SEEDANCE_COST_PER_SECOND_USD", "0.10"))
    return round(sum(scene.seconds for scene in scenes) * per_second, 4)


def _retail_price(provider_cost: float) -> float:
    """Use the production pricing functions when main.py is already loaded."""
    try:
        if "main" not in sys.modules:
            raise RuntimeError("production main is not loaded")
        import main as production_main
        fn = getattr(production_main, "_retail_usd", None)
        if callable(fn):
            return float(fn(provider_cost))
    except Exception:
        log.debug("property video price lookup fell back to local guard", exc_info=True)
    multiplier = max(1.0, float(os.getenv("GENERATION_PRICE_MULTIPLIER", "2.0")))
    return round(provider_cost * multiplier, 2)


def _audio_cost(sound_mode: str, duration: int) -> dict:
    mode = validate_sound_mode(sound_mode)
    music = float(os.getenv("PROPERTY_VIDEO_SUNO_COST_USD", os.getenv("SUNO_COST_USD", "0.20"))) if sound_has_music(mode) else 0.0
    voice_per_minute = float(os.getenv(
        "PROPERTY_VIDEO_TTS_COST_PER_MINUTE_USD",
        os.getenv("VEO_24S_TTS_COST_PER_MINUTE_USD", "0.015"),
    ))
    voice = (max(1, int(duration)) / 60.0) * voice_per_minute if sound_has_voice(mode) else 0.0
    return {"music_cost_usd": round(music, 4), "voice_cost_usd": round(voice, 4)}


def quote_for_job(
    engine: str, photo_count: int, duration: int, mode: str = "full", *, sound_mode: str = "none",
) -> dict:
    scenes = plan_property_scenes(photo_count, duration, engine, mode)
    video_cost = _provider_cost(engine, scenes)
    audio = _audio_cost(sound_mode, duration)
    provider_cost = round(video_cost + audio["music_cost_usd"] + audio["voice_cost_usd"], 4)
    retail = _retail_price(provider_cost)
    return {
        "engine": engine,
        "duration": int(duration),
        "scene_count": len(scenes),
        "provider_cost_usd": provider_cost,
        "video_cost_usd": video_cost,
        **audio,
        "retail_usd": retail,
        "scenes": scene_manifest(scenes),
    }


def _require_provider(engine: str, sound_mode: str = "none") -> None:
    if engine == "veo" and not (os.getenv("GEMINI_VIDEO_API_KEY") or os.getenv("GEMINI_API_KEY")):
        raise PropertyVideoError("Google Veo не настроен в Render ENV")
    if engine == "kling" and not (
        os.getenv("COMET_API_KEY") or os.getenv("COMETAPI_KEY") or os.getenv("KLING_API_KEY")
    ):
        raise PropertyVideoError(f"{engine.title()} не настроен в Render ENV")
    if engine == "seedance" and not (os.getenv("COMET_API_KEY") or os.getenv("COMETAPI_KEY")):
        raise PropertyVideoError(f"{engine.title()} не настроен в Render ENV")
    mode = validate_sound_mode(sound_mode)
    if sound_has_music(mode) and not os.getenv("SUNO_API_KEY"):
        raise PropertyVideoError("Suno не настроен в Render ENV")
    if sound_has_voice(mode) and not (os.getenv("OPENAI_TTS_KEY") or os.getenv("OPENAI_API_KEY")):
        raise PropertyVideoError("OpenAI TTS не настроен в Render ENV")


def _root() -> Path:
    root = Path(os.getenv("PROPERTY_VIDEO_ROOT", "/data/real_estate_jobs"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _provider_label(engine: str) -> str:
    return {"kling": "Kling", "veo": "Google Veo", "seedance": "Seedance"}.get(engine, engine)


def _assembly_durations(metadata: dict) -> list[float] | None:
    """Read new per-scene output slots; keep legacy manifests recoverable."""
    scenes = metadata.get("scenes") or []
    if not scenes or not all("output_seconds" in item for item in scenes):
        return None
    return [float(item["output_seconds"]) for item in scenes]


def _assembly_aspect(metadata: dict) -> str:
    value = str(metadata.get("aspect_ratio") or "9:16")
    return value if value in {"9:16", "16:9"} else "9:16"


def _saved_audio_paths(folder: Path, sound_mode: str, metadata: dict) -> tuple[str, str]:
    mode = validate_sound_mode(sound_mode)
    music = folder / "audio" / "music_source.mp3"
    voice = folder / "audio" / "voice_master.wav"
    if sound_has_music(mode) and not (music.is_file() and music.stat().st_size > 0):
        raise PropertyVideoError("saved Suno track is not ready")
    if sound_has_voice(mode) and not (voice.is_file() and voice.stat().st_size > 0):
        try:
            recover_voice_track(
                metadata.get("narration_plan") or {}, _assembly_durations(metadata) or [], str(folder / "audio"),
            )
        except Exception as exc:
            raise PropertyVideoError("saved narration track is not ready") from exc
    return (str(music) if sound_has_music(mode) else "", str(voice) if sound_has_voice(mode) else "")


async def _assemble_saved_job(folder: Path, scene_paths: list[Path], output: Path, metadata: dict) -> None:
    duration = int(metadata["duration"])
    aspect = _assembly_aspect(metadata)
    mode = validate_sound_mode(metadata.get("sound_mode"))
    music_file = folder / "audio" / "music_source.mp3"
    if sound_has_music(mode) and not (music_file.is_file() and music_file.stat().st_size > 0):
        db = os.getenv("DB_PATH", "subs.db")
        with _connect(db) as con:
            row = con.execute(
                "SELECT operation_id FROM property_video_operations WHERE job_id=? AND scene_index=-1",
                (folder.name,),
            ).fetchone()
        if row:
            await recover_music_track(str(row[0]), str(folder / "audio"))
    silent = folder / "property_review_silent.mp4"
    assembly_args = ([str(path) for path in scene_paths], str(silent), duration)
    durations = _assembly_durations(metadata)
    if durations is not None or metadata.get("aspect_ratio"):
        assembly_args = (*assembly_args, durations, aspect)
    await asyncio.to_thread(assemble_property_video, *assembly_args)
    music, voice = _saved_audio_paths(folder, mode, metadata)
    await asyncio.to_thread(
        mix_property_audio, str(silent), str(output), duration,
        music_path=music, voice_path=voice,
    )
    await asyncio.to_thread(
        inspect_property_video, str(output), duration, aspect, expect_audio=mode != "none",
    )


def execution_job(state: dict, db: str) -> tuple[str, tuple | None]:
    """Return a reusable job, replacing only a terminal pre-submit refund."""
    job = str(state.setdefault("job_id", uuid4().hex))
    current = status(db, job)
    if current and current[0] == "refunded":
        job = uuid4().hex
        state["job_id"] = job
        current = None
    return job, current


async def _send_saved(message, path: str, caption: str):
    with open(path, "rb") as handle:
        return await message.reply_video(
            video=handle,
            caption=caption,
            supports_streaming=True,
            write_timeout=180,
            read_timeout=180,
            connect_timeout=30,
            pool_timeout=30,
        )


async def execute(update, context, state, prompt):
    query = update.callback_query
    engine = str(state.get("engine") or "").lower()
    mode = str(state.get("type") or "full").lower()
    duration = int(state.get("duration") or 0)
    sound_mode = str(state.get("sound_mode") or "none")
    photo_ids = list(state.get("photos") or [])
    if engine not in {"kling", "veo", "seedance"} or not photo_ids:
        await query.message.reply_text("Сессия видеообзора неполная. Начните заново.")
        return
    try:
        sound_mode = validate_sound_mode(sound_mode)
        quote = quote_for_job(engine, len(photo_ids), duration, mode, sound_mode=sound_mode)
        _require_provider(engine, sound_mode)
        confirmed_price = float(state.get("quoted_price_usd"))
        if abs(confirmed_price - float(quote["retail_usd"])) > 0.005:
            raise PropertyVideoError("Стоимость изменилась после подтверждения; выполните новый расчёт")
    except Exception as exc:
        state["generating"] = False
        await query.message.reply_text(f"Генерация не запущена: {str(exc)[:500]}. Списаний нет.")
        return

    owner_free = is_property_video_owner_free(
        update.effective_user.id,
        getattr(update.effective_user, "username", None),
    )

    db = os.getenv("DB_PATH", "subs.db")
    job, current = execution_job(state, db)
    if current:
        existing_status, _operation, existing_result, _tx, file_id = current
        if existing_result and Path(existing_result).is_file():
            sent = await _send_saved(query.message, existing_result, f"🏡 Обзор недвижимости · {_provider_label(engine)}")
            mark_delivered(db, job, telegram_file_id=getattr(getattr(sent, "video", None), "file_id", None) or file_id)
            state.clear()
            return
        if existing_status in {"reserved", "submitted", "assembling"}:
            state["generating"] = False
            await query.message.reply_text(
                "Эта задача уже зарегистрирована, но готовый файл ещё не сохранён. "
                "Повторный платный запрос запрещён; дождитесь статуса провайдера или проверьте журнал задачи."
            )
            return
        if existing_status in {"delivered", "refunded"}:
            state["generating"] = False
            await query.message.reply_text(f"Задача уже завершена: {existing_status}.")
            return

    state["generating"] = True
    folder = _root() / job
    folder.mkdir(parents=True, exist_ok=True)
    try:
        photo_paths = await fetch_telegram_photos(context.bot, photo_ids, str(folder / "references"))
    except Exception:
        state["generating"] = False
        await query.message.reply_text("Не удалось получить фотографии из Telegram. Средства не списаны.")
        return

    await query.message.reply_text(
        f"🧭 Режиссёр анализирует {len(photo_paths)} фотографий, типы помещений и маршрут."
    )
    try:
        cached_analysis = state.get("reference_analysis")
        if isinstance(cached_analysis, list) and len(cached_analysis) == len(photo_paths):
            analysis = cached_analysis
        else:
            analysis = await analyse_reference_photos(photo_paths)
        labels = [str(item.get("space") or "unknown") for item in analysis]
        aspect_ratio = resolve_reference_aspect(photo_paths, str(state.get("aspect") or "auto"))
        scenes = plan_property_scenes(len(photo_paths), duration, engine, mode, labels=labels)
        narration_plan = state.get("narration_plan") if sound_has_voice(sound_mode) else None
        if sound_has_voice(sound_mode) and not narration_plan:
            narration_plan = await create_narration_plan(
                analysis, scenes,
                state.get("narration_language", "ru"), state.get("narration_voice", "female"),
                user_id=int(update.effective_user.id), chat_id=int(update.effective_chat.id),
            )
    except Exception as exc:
        state["generating"] = False
        log.exception("property video director failed before provider submission")
        await query.message.reply_text(
            f"Режиссёр не смог подготовить маршрут; генерация провайдера не запускалась. Ошибка: {str(exc)[:300]}"
        )
        return
    metadata = {
        "user_id": int(update.effective_user.id),
        "chat_id": int(update.effective_chat.id),
        "username": getattr(update.effective_user, "username", None),
        "owner_free": bool(owner_free),
        "engine": engine,
        "mode": mode,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "reference_analysis": analysis,
        "sound_mode": sound_mode,
        "narration_language": state.get("narration_language", "ru"),
        "narration_voice": state.get("narration_voice", "female"),
        "narration_plan": narration_plan,
        "provider_cost_usd": quote["provider_cost_usd"],
        "video_cost_usd": quote["video_cost_usd"],
        "music_cost_usd": quote["music_cost_usd"],
        "voice_cost_usd": quote["voice_cost_usd"],
        "scene_count": len(scenes),
        "scenes": scene_manifest(scenes),
    }
    reserved = reserve(
        db, job, update.effective_user.id,
        0 if owner_free else quote["retail_usd"],
        provider_cost_usd=quote["provider_cost_usd"],
        metadata={**metadata, "retail_quote_usd": quote["retail_usd"]},
        owner_bypass=owner_free,
    )
    if reserved == "insufficient":
        state["generating"] = False
        await query.message.reply_text(
            f"Недостаточно кредитов для обзора. Стоимость: ${quote['retail_usd']:.2f}. Средства не списаны."
        )
        return
    if reserved != "reserved":
        state["generating"] = False
        await query.message.reply_text("Задача уже учтена. Повторный платный запрос запрещён.")
        return

    (folder / "plan.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    if owner_free:
        await query.message.reply_text(
            f"🧪 Тестовый режим владельца: {_provider_label(engine)} запускается реально. "
            "Внутренние кредиты не списываются; расход идёт из API-баланса провайдера."
        )
    await query.message.reply_text(
        f"⏳ {_provider_label(engine)}: запускаю {len(scenes)} сцен(ы). "
        f"Формат {aspect_ratio}. Повторно кнопку не нажимайте — задача сохранена в журнале."
    )
    scene_paths: list[str] = []
    try:
        for scene in scenes:
            scene_path = folder / f"scene_{scene.index:02d}.mp4"
            if scene_path.is_file() and scene_path.stat().st_size > 0:
                scene_paths.append(str(scene_path))
                continue

            def _remember(operation: str, scene_index=scene.index, provider=engine):
                try:
                    record_operation(db, job, operation, provider=provider, scene_index=scene_index)
                except Exception:
                    log.exception("property video operation journal failed job=%s scene=%s", job, scene_index)

            await query.message.reply_text(
                f"🎬 Сцена {scene.index + 1}/{len(scenes)} · {scene.output_seconds:g} сек"
            )
            await render_scene_to_file(
                engine,
                photo_paths[scene.photo_index],
                scene_prompt(prompt, scene, len(scenes)),
                scene.seconds,
                str(scene_path),
                on_task_id=_remember,
                last_photo_path=(
                    photo_paths[scene.next_photo_index]
                    if scene.next_photo_index is not None else ""
                ),
                aspect_ratio=aspect_ratio,
            )
            log.info(
                "PROPERTY_VIDEO_SCENE_READY job=%s scene=%s/%s bytes=%s",
                job, scene.index + 1, len(scenes), scene_path.stat().st_size,
            )
            scene_paths.append(str(scene_path))

        audio_folder = folder / "audio"
        music_path = ""
        voice_path = ""
        if sound_has_voice(sound_mode):
            voice_target = audio_folder / "voice_master.wav"
            if voice_target.is_file() and voice_target.stat().st_size > 0:
                voice_path = str(voice_target)
            else:
                await query.message.reply_text("🎙 Создаю и синхронизирую голос диктора по сценам.")

                def _remember_tts(index: int):
                    record_operation(
                        db, job, f"tts-request:{job}:{index}", provider="openai_tts", scene_index=-100-index,
                    )

                voice_path = await render_voice_track(
                    narration_plan or {}, [scene.output_seconds for scene in scenes], str(audio_folder),
                    on_request_start=_remember_tts,
                )
        if sound_has_music(sound_mode):
            music_target = audio_folder / "music_source.mp3"
            if music_target.is_file() and music_target.stat().st_size > 0:
                music_path = str(music_target)
            else:
                await query.message.reply_text("🎵 Suno создаёт спокойную инструментальную музыку для обзора.")

                def _remember_music(operation: str):
                    record_operation(db, job, operation, provider="suno", scene_index=-1)

                record_operation(db, job, f"suno-submit:{job}", provider="suno", scene_index=-1)
                music_path = await render_music_track(
                    update, duration, str(audio_folder), on_task_id=_remember_music,
                )


        output = folder / "property_review.mp4"
        silent_output = folder / "property_review_silent.mp4"
        log.info("PROPERTY_VIDEO_ASSEMBLY_START job=%s scenes=%s", job, len(scene_paths))
        await asyncio.to_thread(
            assemble_property_video,
            scene_paths,
            str(silent_output),
            duration,
            [scene.output_seconds for scene in scenes],
            aspect_ratio,
        )
        await asyncio.to_thread(
            mix_property_audio, str(silent_output), str(output), duration,
            music_path=music_path, voice_path=voice_path,
        )
        quality = await asyncio.to_thread(
            inspect_property_video, str(output), duration, aspect_ratio,
            expect_audio=sound_mode != "none",
        )
        (folder / "quality.json").write_text(
            json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("PROPERTY_VIDEO_QUALITY_OK job=%s metrics=%s", job, quality)
        if not record_result(db, job, str(output)):
            raise PropertyVideoError("Итоговый файл не удалось записать в журнал задачи")
        log.info("PROPERTY_VIDEO_RESULT_READY job=%s bytes=%s", job, output.stat().st_size)
        log.info("PROPERTY_VIDEO_DELIVERY_START job=%s", job)
        try:
            sent = await _send_saved(
                query.message,
                str(output),
                f"🏡 Обзор недвижимости · {_provider_label(engine)} · {duration} сек · {aspect_ratio} · звук: {sound_mode}",
            )
        except Exception as delivery_exc:
            # Telegram may accept a media upload but return no acknowledgement.
            # The generated result remains ready and must never be reported as a
            # provider/generation failure or submitted to the paid provider again.
            if delivery_exc.__class__.__name__ not in {"TimedOut", "NetworkError"}:
                raise
            mark_delivery_unknown(db, job)
            log.warning(
                "PROPERTY_VIDEO_DELIVERY_UNKNOWN job=%s error=%s",
                job, delivery_exc.__class__.__name__,
            )
            state.clear()
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            try:
                await query.message.reply_text(
                    "✅ Видео создано и сохранено. Telegram не подтвердил загрузку вовремя. "
                    "Если файл не появился, отправьте сохранённый результат повторно — нового списания и вызова провайдера не будет.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📥 Получить готовое видео", callback_data="revideo:recover")
                    ]]),
                )
            except Exception:
                log.exception("property video delivery recovery notice failed job=%s", job)
            return
        file_id = getattr(getattr(sent, "video", None), "file_id", None)
        if not mark_delivered(db, job, telegram_file_id=file_id):
            raise PropertyVideoError("Видео доставлено, но платёжный ledger не подтвердил списание")
        log.info("PROPERTY_VIDEO_DELIVERED job=%s file_id=%s", job, bool(file_id))
        state.clear()
    except Exception as exc:
        log.exception("property video job failed job=%s engine=%s", job, engine)
        state["generating"] = False
        # Refund only when no provider task has been journaled. Once an
        # operation is known or a scene was written, keep the reservation for
        # reconciliation and explicitly prohibit automatic paid retries.
        refunded = refund_before_submission(db, job)
        if refunded:
            message = "Запрос отклонён до отправки провайдеру; резерв возвращён."
        else:
            message = "Провайдер уже принял часть задачи или её статус неизвестен; повторная генерация запрещена."
        await query.message.reply_text(f"❌ Обзор не завершён. {message} Ошибка: {str(exc)[:400]}")


async def recover_ready(update, context):
    """Re-deliver the user's latest ready result without another provider call."""
    import sqlite3
    db = os.getenv("DB_PATH", "subs.db")
    uid = int(update.effective_user.id)
    with sqlite3.connect(db) as con:
        rows = con.execute(
            "SELECT job_id,result_path,status FROM property_video_charges WHERE user_id=? AND result_path IS NOT NULL ORDER BY created_at DESC LIMIT 5",
            (uid,),
        ).fetchall()
    for job, result_path, current in rows:
        if result_path and Path(result_path).is_file():
            sent = await _send_saved(update.effective_message, result_path, f"🏡 Повторная доставка готового обзора · {current}")
            mark_delivered(db, job, telegram_file_id=getattr(getattr(sent, "video", None), "file_id", None))
            return
    await update.effective_message.reply_text("Сохранённого готового видеообзора не найдено.")



async def recover_after_restart(application) -> None:
    """Finish locally recoverable jobs after a Render/process restart.

    Provider operations are never re-submitted here. Recovery only assembles
    already downloaded scene MP4s and delivers an existing result.
    """
    db = os.getenv("DB_PATH", "subs.db")
    try:
        with _connect(db) as con:
            rows = con.execute(
                """SELECT job_id,status,result_path,metadata_json
                   FROM property_video_charges
                   WHERE status IN ('submitted','assembling','ready','delivery_unknown')
                   ORDER BY created_at ASC LIMIT 20"""
            ).fetchall()
        log.info("PROPERTY_VIDEO_RECOVERY_SCAN jobs=%s root=%s", len(rows), _root())
    except Exception:
        log.exception("property video restart recovery: database scan failed")
        return

    for job, current_status, result_path, raw_metadata in rows:
        try:
            metadata = json.loads(raw_metadata or "{}")
            chat_id = int(metadata.get("chat_id") or metadata.get("user_id"))
            duration = int(metadata["duration"])
            engine = str(metadata["engine"])
            scene_count = int(metadata["scene_count"])
            folder = _root() / str(job)
            output = Path(result_path) if result_path else folder / "property_review.mp4"

            if current_status in {"ready", "delivery_unknown"} and output.is_file() and output.stat().st_size > 0:
                scene_paths = []
            else:
                scene_paths = [folder / f"scene_{i:02d}.mp4" for i in range(scene_count)]
                if not all(path.is_file() and path.stat().st_size > 0 for path in scene_paths):
                    log.warning(
                        "PROPERTY_VIDEO_RECOVERY_WAIT job=%s status=%s scenes=%s/%s",
                        job, current_status, sum(path.is_file() for path in scene_paths), scene_count,
                    )
                    continue
                if not claim_assembly(db, str(job)) and current_status == "submitted":
                    continue
                await _assemble_saved_job(folder, scene_paths, output, metadata)
                record_result(db, str(job), str(output))

            with output.open("rb") as handle:
                sent = await application.bot.send_video(
                    chat_id=chat_id,
                    video=handle,
                    caption=f"🏡 Обзор недвижимости · {_provider_label(engine)} · {duration} сек",
                    supports_streaming=True,
                    write_timeout=180,
                    read_timeout=180,
                    connect_timeout=30,
                    pool_timeout=30,
                )
            file_id = getattr(getattr(sent, "video", None), "file_id", None)
            if not mark_delivered(db, str(job), telegram_file_id=file_id):
                raise PropertyVideoError("recovery delivery was not committed to the billing ledger")
            log.info("PROPERTY_VIDEO_RECOVERED job=%s engine=%s chat_id=%s", job, engine, chat_id)
        except Exception:
            log.exception("property video restart recovery failed job=%s", job)



    # A deployment can replace an ephemeral SQLite file after provider scenes
    # have already been written to the persistent disk. Owner-test jobs are
    # safe to recover from their durable plan manifest without inventing a
    # retry or charging the user's wallet.
    known_jobs = {str(row[0]) for row in rows}
    for manifest_path in _root().glob("*/plan.json"):
        job = manifest_path.parent.name
        if job in known_jobs or (manifest_path.parent / "recovery_delivered").exists():
            continue
        try:
            metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
            user_id = int(metadata["user_id"])
            chat_id = int(metadata.get("chat_id") or user_id)
            if not metadata.get("owner_free") and not is_property_video_owner_free(user_id, metadata.get("username")):
                continue
            engine = str(metadata["engine"])
            duration = int(metadata["duration"])
            scene_count = int(metadata["scene_count"])
            folder = manifest_path.parent
            scenes = [folder / f"scene_{i:02d}.mp4" for i in range(scene_count)]
            if not all(path.is_file() and path.stat().st_size > 0 for path in scenes):
                continue
            output = folder / "property_review.mp4"
            if not output.is_file() or output.stat().st_size <= 0:
                await _assemble_saved_job(folder, scenes, output, metadata)
            reserve(
                db, job, user_id, 0,
                provider_cost_usd=float(metadata.get("provider_cost_usd", 0) or 0),
                metadata={**metadata, "recovered_orphan": True},
                owner_bypass=True,
            )
            with output.open("rb") as handle:
                await application.bot.send_video(
                    chat_id=chat_id,
                    video=handle,
                    caption=f"🏡 Восстановленный обзор недвижимости · {_provider_label(engine)} · {duration} сек",
                    supports_streaming=True,
                    write_timeout=180,
                    read_timeout=180,
                    connect_timeout=30,
                    pool_timeout=30,
                )
            (folder / "recovery_delivered").write_text("ok\n", encoding="utf-8")
            log.info("PROPERTY_VIDEO_ORPHAN_RECOVERED job=%s engine=%s chat_id=%s", job, engine, chat_id)
        except Exception:
            log.exception("property video orphan recovery failed manifest=%s", manifest_path)
