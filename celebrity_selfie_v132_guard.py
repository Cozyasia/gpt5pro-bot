# -*- coding: utf-8 -*-
"""Final job guard for Celebrity Selfie v132.

This module deliberately patches only the Telegram generation transaction. The
image pipeline remains in ``celebrity_selfie_v132``. The guard makes scene and
celebrity snapshots immutable for a running job, rejects duplicate callbacks,
discards stale provider results after any menu change, and never tells the user
that a failed provider task was a successful generation.
"""
from __future__ import annotations

import time
import uuid
from io import BytesIO
from typing import Any

import celebrity_selfie_v132 as base

VERSION = base.VERSION
engine = base.engine


def _current_value(session: dict[str, Any], key: str) -> str:
    return str(session.get(key) or "").strip()


def _same_job_selection(
    session: dict[str, Any],
    generation_id: str,
    scene: str,
    celebrity_name: str,
) -> bool:
    return (
        str(session.get("generation_id") or "") == generation_id
        and _current_value(session, "scene") == scene
        and _current_value(session, "celebrity_name") == celebrity_name
        and str(session.get("generation_scene_snapshot") or "") == scene
        and str(session.get("generation_celebrity_snapshot") or "") == celebrity_name
    )


def _public_failure(exc: Exception) -> str:
    text = str(exc or "").strip()
    lowered = text.casefold()
    if "split-screen" in lowered or "склей" in lowered or "референс" in lowered:
        return "провайдер вернул техническую склейку вместо единой фотографии"
    if "scene" in lowered or "сцен" in lowered or "location" in lowered:
        return "результат не соответствовал выбранной сцене"
    if "piapi" in lowered or "identity" in lowered or "лиц" in lowered:
        return "не удалось надёжно закрепить оба лица"
    if "timeout" in lowered or "время ожидания" in lowered:
        return "один из провайдеров превысил время ожидания"
    return "результат не прошёл обязательную проверку качества"


async def _generate(update: Any, context: Any, *, refinement: bool = False) -> None:
    session = engine._session(context, create=False)
    if not session:
        await update.effective_message.reply_text(
            "Сессия AI-селфи не найдена. Откройте режим «Селфи со звездой» заново."
        )
        return

    now = time.monotonic()
    state = str(session.get("state") or "")
    started = float(session.get("generation_started_monotonic") or 0)
    if state in {"queued", "generating"} and now - started < 900:
        await update.effective_message.reply_text(
            "⏳ Эта генерация уже выполняется. Дождитесь результата: повторное нажатие "
            "не запускает второй запрос."
        )
        return

    user_photo = engine._read_path(session.get("user_photo_path"))
    refs = [
        raw
        for raw in (engine._read_path(path) for path in engine._reference_paths(session))
        if raw
    ]
    if not user_photo:
        session["state"] = "await_user_photo"
        await update.effective_message.reply_text("Пришлите своё селфи ещё раз.")
        return
    if not refs:
        session["state"] = "await_custom_refs"
        await update.effective_message.reply_text("Загрузите 1–4 фото знаменитости.")
        return

    scene = _current_value(session, "scene")
    celebrity_name = _current_value(session, "celebrity_name") or "выбранный человек"
    if not scene:
        session["state"] = "await_scene"
        await update.effective_message.reply_text(
            "Выберите или опишите сцену.", reply_markup=engine._scene_kb()
        )
        return

    previous_result = engine._read_path(session.get("result_path")) if refinement else None
    mod = engine._runtime_module()
    if mod is None:
        await update.effective_message.reply_text(
            "Сервис ещё загружается. Повторите через несколько секунд."
        )
        return

    generation_id = uuid.uuid4().hex
    session["generation_id"] = generation_id
    session["generation_started_monotonic"] = now
    session["generation_scene_snapshot"] = scene
    session["generation_celebrity_snapshot"] = celebrity_name
    session["state"] = "queued"

    async def work() -> bool:
        if not _same_job_selection(session, generation_id, scene, celebrity_name):
            return False
        session["state"] = "generating"
        await update.effective_message.reply_text(
            "⏳ Повторно закрепляю оба исходных лица без изменения сцены…"
            if refinement
            else (
                f"⏳ Создаю одну цельную сцену с {celebrity_name}, затем отдельно закрепляю "
                "оба лица. Технические коллажи и черновики не отправляются; ожидание "
                "обычно 2–6 минут."
            )
        )
        try:
            output = await base._run_validated_generation(
                mod,
                user_photo,
                refs,
                celebrity_name,
                scene,
                previous_result=previous_result,
            )
        except Exception as exc:
            if str(session.get("generation_id") or "") == generation_id:
                session["state"] = "result" if previous_result else "await_scene"
                session["last_generation_error"] = str(exc)[:1600]
                session["last_generation_failed_at"] = time.time()
                session.pop("generation_id", None)
                await update.effective_message.reply_text(
                    "❌ Некачественный результат не был отправлен. "
                    + _public_failure(exc)
                    + ". Выберите сцену ещё раз или повторите позже.",
                    reply_markup=(
                        engine._result_kb(bool(engine._selected_entry(session)))
                        if previous_result
                        else engine._scene_kb()
                    ),
                )
            return False

        # A menu change while providers were working invalidates the result. The
        # old v132 comparison only compared snapshots with local variables; this
        # guard also compares the live session values.
        if not _same_job_selection(session, generation_id, scene, celebrity_name):
            if str(session.get("generation_id") or "") == generation_id:
                session.pop("generation_id", None)
            return False

        result_path = engine._store_image(
            session,
            "result_refined.png" if refinement else "result.png",
            output,
        )
        session["result_path"] = result_path
        session["state"] = "result"
        session["last_generation_ok_at"] = time.time()
        session.pop("generation_id", None)

        from telegram import InputFile

        bio = BytesIO(output)
        bio.name = "celebrity_selfie.png"
        caption = (
            "📸 Проверенное AI-селфи готово ✅\n"
            f"Персона: {celebrity_name}\n"
            "Контроль: единый кадр, выбранная сцена и обязательное закрепление лиц.\n"
            "Пометка: изображение создано ИИ; оно не подтверждает реальную встречу, "
            "поддержку, рекламу или партнёрство."
        )
        markup = engine._result_kb(bool(engine._selected_entry(session)))
        if engine._flag("CELEBRITY_SELFIE_SEND_AS_DOCUMENT", True):
            await update.effective_message.reply_document(
                InputFile(bio), caption=caption, reply_markup=markup
            )
        else:
            await update.effective_message.reply_photo(
                photo=output, caption=caption, reply_markup=markup
            )
        return True

    pay = getattr(mod, "_try_pay_then_do", None)
    if not callable(pay):
        await work()
        return
    cost = float(getattr(mod, "AI_SELFIE_UNIT_COST_USD", 0.15) or 0.15)
    await pay(
        update,
        context,
        update.effective_user.id,
        "img",
        cost,
        work,
        remember_kind=(
            "celebrity_selfie_validated_refine"
            if refinement
            else "celebrity_selfie_validated"
        ),
        remember_payload={
            "celebrity": celebrity_name,
            "scene": scene[:500],
            "refs": len(refs),
            "refinement": refinement,
            "generation_id": generation_id,
            "pipeline": VERSION,
        },
    )


def install() -> None:
    engine._generate = _generate
    base.engine._generate = _generate


install()

__all__ = ["VERSION", "install", "_generate", "_same_job_selection", "_public_failure"]
