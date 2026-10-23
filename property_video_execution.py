"""Paid, durable execution for the property-video wizard."""
from __future__ import annotations

import json
import logging
import math
import os
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from property_video_billing import (
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
    render_scene,
    scene_manifest,
    scene_prompt,
)
from real_estate_pipeline import fetch_telegram_photos

log = logging.getLogger(__name__)


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
    if engine in {"kling", "seedance"} and not (os.getenv("COMET_API_KEY") or os.getenv("COMETAPI_KEY") or os.getenv("KLING_API_KEY")):
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
        "engine": engine,
        "mode": mode,
        "duration": duration,
        "scene_count": len(scenes),
        "scenes": scene_manifest(scenes),
    }
    reserved = reserve(
        db, job, update.effective_user.id, quote["retail_usd"],
        provider_cost_usd=quote["provider_cost_usd"], metadata=metadata,
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
            rendered = await render_scene(
                engine,
                photo_paths[scene.photo_index],
                scene_prompt(prompt, scene, len(scenes)),
                scene.seconds,
                on_task_id=_remember,
            )
            scene_path.write_bytes(rendered)
            scene_paths.append(str(scene_path))

        output = folder / "property_review.mp4"
        await asyncio.to_thread(assemble_property_video, scene_paths, str(output), duration)
        record_result(db, job, str(output))
        sent = await _send_saved(query.message, str(output), f"🏡 Обзор недвижимости · {_provider_label(engine)} · {duration} сек")
        file_id = getattr(getattr(sent, "video", None), "file_id", None)
        if not mark_delivered(db, job, telegram_file_id=file_id):
            raise PropertyVideoError("Видео доставлено, но платёжный ledger не подтвердил списание")
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
