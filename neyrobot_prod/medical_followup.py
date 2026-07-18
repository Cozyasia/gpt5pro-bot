# -*- coding: utf-8 -*-
"""Guaranteed Medical Engine + Medical Card hand-off.

The previous release patched only ``medical_v111_runtime._offer_save``. In some
startup orders the public handlers were still the older v108 closures, so the
medical answer was sent without creating ``medcard_pending``. This module makes
the official structured engine the single public route and installs one final,
idempotent Medical Card decision for every successful analysis.
"""
from __future__ import annotations

import contextlib
import hashlib
import re
import time
from typing import Any

VERSION = "v119-production-hardening-2026-07-18"
_DEDUPE_TTL = 15 * 60

UPSELL_TEXT = (
    "📁 Персональная медицинская карта\n\n"
    "С тарифом PRO или ULTIMATE после каждого медицинского разбора можно:\n"
    "• сохранять оригиналы анализов, заключений, УЗИ, МРТ и КТ;\n"
    "• хранить распознанные показатели и подробные разборы;\n"
    "• видеть хронологию и динамику по датам;\n"
    "• вести отдельные профили для себя и близких;\n"
    "• искать документы и формировать PDF-сводку для врача.\n\n"
    "Текущий разбор останется в этом чате. Постоянное хранение медицинских "
    "данных включается только после оформления тарифа и отдельного согласия."
)

STANDARD_DISCLAIMER = (
    "⚠️ Важно: это справочный разбор и подготовка вопросов к врачу, а не диагноз, "
    "не медицинское заключение и не замена очной консультации или обследования."
)


def _log(mod: Any, level: str, message: str, *args: Any) -> None:
    logger = getattr(mod, "log", None)
    fn = getattr(logger, level, None) if logger is not None else None
    if callable(fn):
        with contextlib.suppress(Exception):
            fn(message, *args)


def _eligible(card: Any, mod: Any, user: Any) -> bool:
    with contextlib.suppress(Exception):
        if card._eligible(mod, user):
            return True
    uid = int(getattr(user, "id", 0) or 0)
    username = str(getattr(user, "username", "") or "")
    checker = getattr(mod, "is_unlimited", None)
    if callable(checker):
        with contextlib.suppress(Exception):
            if checker(uid, username):
                return True
    return bool(uid and uid == int(getattr(mod, "OWNER_ID", 0) or 0))


def _signature(pending: Any) -> str:
    if not isinstance(pending, dict) or not pending:
        return ""
    digest = hashlib.sha256()
    for key in ("track", "source_type", "filename", "mime_type", "created_ts"):
        digest.update(str(pending.get(key) or "").encode("utf-8", errors="ignore"))
        digest.update(b"\0")
    raw = pending.get("file_bytes") or b""
    if isinstance(raw, bytearray):
        raw = bytes(raw)
    if isinstance(raw, bytes):
        digest.update(str(len(raw)).encode("ascii"))
        digest.update(raw[:65536])
    digest.update(str(pending.get("analysis") or "")[:4096].encode("utf-8", errors="ignore"))
    return digest.hexdigest()[:24]


def _already_sent(context: Any, signature: str) -> bool:
    state = context.user_data.get("medcard_prod_last_offer") or {}
    return bool(
        signature
        and isinstance(state, dict)
        and state.get("signature") == signature
        and time.time() - float(state.get("timestamp") or 0) < _DEDUPE_TTL
    )


def _mark_sent(context: Any, signature: str, kind: str) -> None:
    context.user_data["medcard_prod_last_offer"] = {
        "signature": signature,
        "kind": kind,
        "timestamp": time.time(),
    }
    context.user_data["medcard_offer_last_status"] = kind


def _upsell_kb(card: Any, mod: Any):
    return card._kb(
        mod,
        [
            [("🚀 Подключить PRO", "plan:pro"), ("💎 ULTIMATE", "plan:ultimate")],
            [("ℹ️ Сравнить тарифы", "plan:root")],
            [("⬅️ В Медицину", "medcard:back_med")],
        ],
    )


def dedupe_disclaimer(answer: str) -> str:
    text = str(answer or "").strip()
    if not text:
        return text
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    kept: list[str] = []
    for paragraph in paragraphs:
        low = paragraph.lower().replace("ё", "е")
        is_disclaimer = (
            ("не является диагноз" in low or "не заменяет" in low or "справочн" in low)
            and ("врач" in low or "консультац" in low or "обследован" in low)
        )
        if not is_disclaimer:
            kept.append(paragraph)
    kept.append(STANDARD_DISCLAIMER)
    return "\n\n".join(kept).strip()


async def offer(mod: Any, update: Any, context: Any) -> None:
    """Send exactly one save/create/upgrade decision after a successful analysis."""
    try:
        import medical_card_v109_patch as card
    except Exception as exc:
        _log(mod, "warning", "Medical Card import failed: %r", exc)
        return

    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    pending = context.user_data.get("medcard_pending") or {}
    if user is None or message is None or not isinstance(pending, dict) or not pending:
        _log(mod, "warning", "Medical Card offer skipped because pending payload is absent")
        return

    uid = int(getattr(user, "id", 0) or 0)
    signature = _signature(pending)
    if _already_sent(context, signature):
        return
    entitled = _eligible(card, mod, user)

    try:
        if entitled:
            if card._auto_save(mod, uid) and card._has_consent(mod, uid):
                ok, text, doc_id = await card._save_pending(mod, update, context)
                markup = card._card_main_kb(mod)
                if ok and doc_id:
                    row = card._doc_row(mod, uid, doc_id)
                    if row:
                        markup = card._doc_kb(mod, doc_id, bool(row[9]))
                await message.reply_text(text, reply_markup=markup)
                _mark_sent(context, signature, "auto_saved" if ok else "auto_save_error")
                return

            await message.reply_text(
                "📁 Сохранить оригинал, распознанные данные и этот разбор в медицинскую карту?",
                reply_markup=card._pending_save_kb(mod, uid),
            )
            _mark_sent(context, signature, "entitled_prompt_sent")
            return

        await message.reply_text(
            UPSELL_TEXT,
            reply_markup=_upsell_kb(card, mod),
            disable_web_page_preview=True,
        )
        context.user_data.pop("medcard_pending", None)
        context.user_data.pop("medcard_source_capture", None)
        _mark_sent(context, signature, "upsell_sent")
    except Exception as exc:
        _log(mod, "exception", "Medical Card final decision failed: %r", exc)
        _mark_sent(context, signature, f"error:{type(exc).__name__}")
        with contextlib.suppress(Exception):
            if entitled:
                await message.reply_text(
                    "📁 Медицинская карта доступна вашему аккаунту, но кнопки сохранения не загрузились. "
                    "Откройте «Моя медицинская карта» в меню Медицина и повторите действие."
                )
            else:
                await message.reply_text(UPSELL_TEXT, disable_web_page_preview=True)


def patch_runtime(mod: Any) -> bool:
    """Force the current structured official medical engine onto public handlers."""
    try:
        import medical_card_v109_patch as card
        import medical_v111_runtime as runtime
    except Exception:
        return False

    if not all(hasattr(mod, name) for name in ("_medical_analyze_text", "_medical_analyze_image", "BOT_TOKEN")):
        return False

    runtime._offer_save = offer
    card._offer_save = offer

    original_send = getattr(runtime, "_send_answer", None)
    if callable(original_send) and not getattr(original_send, "_prod_v119_wrapped", False):
        async def send_answer(mod_arg: Any, update: Any, context: Any, answer: str) -> None:
            await original_send(mod_arg, update, context, dedupe_disclaimer(answer))
        send_answer._prod_v119_wrapped = True  # type: ignore[attr-defined]
        send_answer._prod_v119_original = original_send  # type: ignore[attr-defined]
        runtime._send_answer = send_answer

    async def analyze_text(update: Any, context: Any, value: str, goal: str | None = None) -> None:
        await runtime.analyze(mod, update, context, value, goal, False)

    async def analyze_image(update: Any, context: Any, value: bytes, goal: str | None = None) -> None:
        await runtime.analyze(mod, update, context, value, goal, True)

    analyze_text._prod_v119_medical = True  # type: ignore[attr-defined]
    analyze_image._prod_v119_medical = True  # type: ignore[attr-defined]
    mod._medical_analyze_text = analyze_text
    mod._medical_analyze_image = analyze_image
    mod.MEDICAL_ENGINE_VERSION = VERSION
    mod.MEDICAL_CARD_VERSION = VERSION
    mod.MEDICAL_PATCH_VERSION = VERSION
    mod._PROD_MEDICAL_FOLLOWUP_PATCHED = True
    return True


async def diag_medcard(mod: Any, update: Any, context: Any) -> None:
    try:
        import medical_card_v109_patch as card
        user = update.effective_user
        uid = int(user.id)
        entitled = _eligible(card, mod, user)
        consent = bool(card._has_consent(mod, uid)) if entitled else False
        pending = context.user_data.get("medcard_pending") or {}
        await update.effective_message.reply_text(
            "📁 Medical Card diagnostic\n"
            f"version={VERSION}\n"
            f"entitled={'on' if entitled else 'off'}\n"
            f"consent={'on' if consent else 'off'}\n"
            f"pending={'on' if bool(pending) else 'off'}\n"
            f"last_offer={context.user_data.get('medcard_offer_last_status') or '—'}\n"
            f"public_text_handler={'v119' if getattr(mod._medical_analyze_text, '_prod_v119_medical', False) else 'legacy'}\n"
            f"public_image_handler={'v119' if getattr(mod._medical_analyze_image, '_prod_v119_medical', False) else 'legacy'}"
        )
    except Exception as exc:
        await update.effective_message.reply_text(f"Medical Card diagnostic error: {type(exc).__name__}: {exc}")


__all__ = ["VERSION", "offer", "patch_runtime", "diag_medcard", "dedupe_disclaimer"]
