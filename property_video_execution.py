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
    scene_manifest,
    scene_prompt,
)
from real_estate_pipeline import fetch_telegram_photos

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


def quote_for_job(engine: str, photo_count: int, duration: int, mode: str = "full") -> dict:
    scenes = plan_property_scenes(photo_count, duration, engine, mode)
    provider_cost = _provider_cost(engine, scenes)
    retail = _retail_price(provider_cost)
    return {
        "engine": engine,
        "duration": int(duration),
        "scene_count": len(scenes),
        "provider_cost_usd": provider_cost,
        "retail_usd": retail,
        "scenes": scene_manifest(scenes),
    }


def _require_provider(engine: str) -> None:
    if engine == "veo" and not (os.getenv("GEMINI_VIDEO_API_KEY") or os.getenv("GEMINI_API_KEY")):
        raise PropertyVideoError("Google Veo не настроен в Render ENV")
    if engine == "kling" and not (
        os.getenv("COMET_API_KEY") or os.getenv("COMETAPI_KEY") or os.getenv("KLING_API_KEY")
    ):
        raise PropertyVideoError(f"{engine.title()} не настроен в Render ENV")
    if engine == "seedance" and not (os.getenv("COMET_API_KEY") or os.getenv("COMETAPI_KEY")):
        raise PropertyVideoError(f"{engine.title()} не настроен в Render ENV")


def _root() -> Path:
    root = Path(os.getenv("PROPERTY_VIDEO_ROOT", "/data/real_estate_jobs"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _provider_label(engine: str) -> str:
    return {"kling": "Kling", "veo": "Google Veo", "seedance": "Seedance"}.get(engine, engine)


async def _send_saved(message, path: str, caption: str):
    with open(path, "rb") as handle:
        return await message.reply_video(video=handle, caption=caption, supports_streaming=True)


async def execute(update, context, state, prompt):
    query = update.callback_query
    engine = str(state.get("engine") or "").lower()
    mode = str(state.get("type") or "full").lower()
    duration = int(state.get("duration") or 0)
    photo_ids = list(state.get("photos") or [])
    if engine not in {"kling", "veo", "seedance"} or not photo_ids:
        await query.message.reply_text("Сессия видеообзора неполная. Начните заново.")
        return
    try:
        quote = quote_for_job(engine, len(photo_ids), duration, mode)
        _require_provider(engine)
    except Exception as exc:
        state["generating"] = False
        await query.message.reply_text(f"Генерация не запущена: {str(exc)[:500]}. Списаний нет.")
        return

    owner_free = is_property_video_owner_free(
        update.effective_user.id,
        getattr(update.effective_user, "username", None),
    )

    job = str(state.setdefault("job_id", uuid4().hex))
    db = os.getenv("DB_PATH", "subs.db")
    current = status(db, job)
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

    scenes = plan_property_scenes(len(photo_paths), duration, engine, mode)
    metadata = {
        "user_id": int(update.effective_user.id),
        "chat_id": int(update.effective_chat.id),
        "username": getattr(update.effective_user, "username", None),
        "owner_free": bool(owner_free),
        "engine": engine,
        "mode": mode,
        "duration": duration,
        "provider_cost_usd": quote["provider_cost_usd"],
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
        "Повторно кнопку не нажимайте — задача сохранена в журнале."
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

            await query.message.reply_text(f"🎬 Сцена {scene.index + 1}/{len(scenes)} · {scene.seconds} сек")
            await render_scene_to_file(
                engine,
                photo_paths[scene.photo_index],
                scene_prompt(prompt, scene, len(scenes)),
                scene.seconds,
                str(scene_path),
                on_task_id=_remember,
            )
            log.info(
                "PROPERTY_VIDEO_SCENE_READY job=%s scene=%s/%s bytes=%s",
                job, scene.index + 1, len(scenes), scene_path.stat().st_size,
            )
            scene_paths.append(str(scene_path))

        output = folder / "property_review.mp4"
        log.info("PROPERTY_VIDEO_ASSEMBLY_START job=%s scenes=%s", job, len(scene_paths))
        await asyncio.to_thread(assemble_property_video, scene_paths, str(output), duration)
        if not record_result(db, job, str(output)):
            raise PropertyVideoError("Итоговый файл не удалось записать в журнал задачи")
        log.info("PROPERTY_VIDEO_RESULT_READY job=%s bytes=%s", job, output.stat().st_size)
        log.info("PROPERTY_VIDEO_DELIVERY_START job=%s", job)
        sent = await _send_saved(query.message, str(output), f"🏡 Обзор недвижимости · {_provider_label(engine)} · {duration} сек")
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
                   WHERE status IN ('submitted','assembling','ready')
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

            if current_status == "ready" and output.is_file() and output.stat().st_size > 0:
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
                await asyncio.to_thread(
                    assemble_property_video,
                    [str(path) for path in scene_paths],
                    str(output),
                    duration,
                )
                record_result(db, str(job), str(output))

            with output.open("rb") as handle:
                sent = await application.bot.send_video(
                    chat_id=chat_id,
                    video=handle,
                    caption=f"🏡 Обзор недвижимости · {_provider_label(engine)} · {duration} сек",
                    supports_streaming=True,
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
                await asyncio.to_thread(assemble_property_video, [str(path) for path in scenes], str(output), duration)
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
                )
            (folder / "recovery_delivered").write_text("ok\n", encoding="utf-8")
            log.info("PROPERTY_VIDEO_ORPHAN_RECOVERED job=%s engine=%s chat_id=%s", job, engine, chat_id)
        except Exception:
            log.exception("property video orphan recovery failed manifest=%s", manifest_path)
