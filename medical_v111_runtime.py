# -*- coding: utf-8 -*-
"""Runtime pipeline for the universal medical engine v112."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import traceback
from typing import Any

from medical_v111_client import clean, extract_image, extract_text, log, model_plan, normalize_extraction, plain, split_text, user_tier
from medical_v111_reasoning import card_metadata, reason_and_audit

VERSION = "v112-medical-responses-api-reliability-2026-07-18"


def _capture(context: Any) -> dict:
    value = context.user_data.pop("medcard_source_capture", None) or {}
    return value if isinstance(value, dict) else {}


def _set_pending(context: Any, track: str, goal: str, source_type: str, filename: str,
                 mime: str, raw: bytes, extraction: dict, answer: str, meta: dict) -> None:
    try:
        import medical_card_v109_patch as card
    except Exception:
        return
    pending = card._pending_payload(
        track, goal, source_type, filename, mime, raw,
        json.dumps(extraction, ensure_ascii=False), answer,
    )
    pending["structured"] = extraction
    pending["metadata_hint"] = card_metadata(extraction, answer)
    pending["engine"] = {"version": VERSION, **meta}
    context.user_data["medcard_pending"] = pending


async def _send_answer(mod: Any, update: Any, context: Any, answer: str) -> None:
    final = plain(answer)
    disclaimer = clean(getattr(mod, "MEDICAL_DISCLAIMER", ""), 1000)
    if disclaimer and "справоч" not in final.lower()[-900:]:
        final += "\n\n" + disclaimer
    keyboard = None
    with contextlib.suppress(Exception):
        keyboard = mod.medicine_kb()
    parts = split_text(final)
    for index, part in enumerate(parts):
        kwargs = {"reply_markup": keyboard} if index == len(parts) - 1 and keyboard is not None else {}
        await update.effective_message.reply_text(part, **kwargs)
    with contextlib.suppress(Exception):
        await mod.maybe_tts_reply(update, context, final[: getattr(mod, "TTS_MAX_CHARS", 1000)])


async def _offer_save(mod: Any, update: Any, context: Any) -> None:
    try:
        import medical_card_v109_patch as card
        await card._offer_save(mod, update, context)
    except Exception as exc:
        log(mod, "warning", "medical card offer failed: %r", exc)


async def _legacy_fallback(mod: Any, source: Any, goal: str, track: str, is_image: bool) -> str:
    try:
        import medical_v108_patch as old
        if is_image:
            extracted = await mod.ask_openai_vision(
                old._extraction_prompt(track, goal),
                base64.b64encode(source).decode("ascii"),
                mod.sniff_image_mime(source),
            )
        else:
            extracted = clean(source, 24000)
        return await old._reason(mod, extracted, track, goal, "медицинский материал")
    except Exception:
        return "Не удалось надёжно обработать материал. Пришлите чёткое фото без бликов либо PDF/текст официального заключения."


def _stage_label(stage: str) -> str:
    return {
        "extract": "точного чтения и структурирования документа",
        "reason": "клинического разбора",
        "audit": "независимой проверки ответа",
    }.get(stage, "медицинского анализа")


async def analyze(mod: Any, update: Any, context: Any, source: Any,
                  goal: str | None, is_image: bool) -> None:
    user = update.effective_user
    tier = user_tier(mod, user)
    plan = model_plan(tier)
    track = str(mod._mode_track_get(user.id) or "")
    goal_text = clean(goal, 1200)
    run = {"calls": [], "fallbacks": [], "transports": []}
    stage = "extract"

    await update.effective_message.reply_text(
        "🩺 Универсальный медицинский анализ:\n"
        f"1) точное извлечение — {plan['extract']};\n"
        f"2) клинический разбор — {plan['reason']};\n"
        f"3) независимый аудит — {plan['audit']}."
    )

    try:
        if is_image:
            mime = mod.sniff_image_mime(source)
            extraction = await extract_image(mod, run, source, mime, goal_text, track, plan["extract"])
        else:
            mime = "text/plain"
            extraction = await extract_text(mod, run, clean(source, 60000), goal_text, track, plan["extract"])

        confidence = float(extraction.get("confidence") or 0)
        if extraction.get("image_quality") == "poor" or confidence < 0.45:
            await update.effective_message.reply_text(
                "⚠️ Источник распознан не полностью уверенно. Ограничения будут явно отмечены; для максимальной точности лучше приложить PDF или более чёткое фото."
            )
        else:
            await update.effective_message.reply_text(
                "✅ Факты структурированы. Проверяю клинический смысл, уровень срочности, актуальные рекомендации и точность каждого числа…"
            )

        stage = "reason"
        answer, engine_meta = await reason_and_audit(mod, run, extraction, goal_text, user, plan)
        stage = "audit"

        if run.get("fallbacks"):
            used_models = ", ".join(item.split(":", 1)[-1] for item in run["fallbacks"])
            await update.effective_message.reply_text(
                "ℹ️ Одна из основных моделей была временно недоступна. "
                f"Анализ завершён резервным маршрутом: {used_models}."
            )
    except Exception as exc:
        error_id = hashlib.sha256(f"{type(exc).__name__}|{exc}".encode()).hexdigest()[:8]
        log(mod, "error", "medical v112 failed %s at %s: %r\n%s", error_id, stage, exc, traceback.format_exc())
        await update.effective_message.reply_text(
            f"⚠️ Не удалось завершить этап {_stage_label(stage)} в новом медицинском контуре. "
            "Использую резервный анализатор, чтобы не потерять запрос. "
            f"Код диагностики: {error_id}."
        )
        answer = await _legacy_fallback(mod, source, goal_text, track, is_image)
        extraction = normalize_extraction({"document_type": "other", "document_title": "Медицинский документ", "confidence": 0})
        engine_meta = {"fallback": True, "error_id": error_id, "failed_stage": stage}

    engine_meta["calls"] = run["calls"]
    engine_meta["fallbacks"] = run["fallbacks"]
    engine_meta["transports"] = run["transports"]
    engine_meta["estimated_cost_usd"] = round(sum(item.get("cost_usd", 0) for item in run["calls"]), 6)
    await _send_answer(mod, update, context, answer)

    capture = _capture(context)
    if is_image:
        raw = source
        filename = capture.get("filename") or "medical_photo.jpg"
        stored_mime = capture.get("mime_type") or mime
        source_type = "image"
    else:
        raw = bytes(capture.get("file_bytes") or clean(source).encode("utf-8"))
        filename = capture.get("filename") or "medical_document.txt"
        stored_mime = capture.get("mime_type") or "text/plain"
        source_type = "text"

    _set_pending(context, track, goal_text, source_type, filename, stored_mime,
                 raw, extraction, answer, engine_meta)
    await _offer_save(mod, update, context)
