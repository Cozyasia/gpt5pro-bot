# -*- coding: utf-8 -*-
"""Progressive disclosure UI for medical answers.

The medical engine still generates and stores the complete audited answer, but the
chat initially receives a compact "30-second" summary. Detailed sections are
opened on demand through inline buttons, which keeps Telegram readable without
losing any clinical context or Medical Card data.
"""
from __future__ import annotations

import contextlib
import hashlib
import re
import time
from typing import Any

VERSION = "v120-medical-progressive-ui-2026-07-18"
_STATE_KEY = "medical_answer_views_v120"
_STATE_TTL = 24 * 3600
_MAX_STATES = 8

STANDARD_DISCLAIMER = (
    "⚠️ Это справочный разбор и подготовка к очной консультации. "
    "Он не является диагнозом, медицинским заключением или назначением лечения."
)


def _clean(text: Any, limit: int = 40000) -> str:
    value = str(text or "").replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{4,}", "\n\n\n", value).strip()
    return value[:limit]


def _normalize_heading(line: str) -> str:
    value = re.sub(r"^[\s#*_`>\-–—•·]+", "", line or "")
    value = re.sub(r"^[^0-9A-Za-zА-Яа-яЁё]+", "", value)
    value = re.sub(r"[*_`]+", "", value)
    value = re.sub(r"\s+", " ", value).strip(" .:;-–—").lower().replace("ё", "е")
    return value


def _heading_key(line: str) -> str | None:
    raw = (line or "").strip()
    if not raw or len(raw) > 150:
        return None
    value = _normalize_heading(raw)
    if not value:
        return None
    checks = (
        ("summary", ("главное за 30", "главное за тридцать", "кратко за 30", "краткий вывод")),
        ("document", ("что точно указано", "что указано в документе", "факты из документа")),
        ("findings", ("разбор каждой", "разбор находок", "значимые находки", "разбор результатов")),
        ("seriousness", ("насколько это серьезно", "оценка серьезности", "уровень риска")),
        ("plan", ("что делать дальше", "рекомендованный план", "план действий", "дальнейшие действия")),
        ("timeline", ("сроки и наблюдение", "сроки наблюдения", "когда повторить")),
        ("urgent", ("когда нужна срочная", "когда обращаться срочно", "неотложная помощь", "срочные признаки")),
        ("doctor", ("что спросить у врача", "вопросы врачу", "вопросы для врача")),
        ("missing", ("каких данных не хватает", "недостающие данные", "для точной оценки не хватает")),
        ("disclaimer", ("важно", "безопасность", "дисклеймер")),
    )
    for key, phrases in checks:
        if any(phrase in value for phrase in phrases):
            return key
    return None


def parse_sections(answer: str) -> dict[str, str]:
    text = _clean(answer)
    sections: dict[str, list[str]] = {}
    current = "preamble"
    sections[current] = []
    for line in text.split("\n"):
        key = _heading_key(line)
        if key:
            current = key
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    result = {key: _clean("\n".join(lines), 30000) for key, lines in sections.items() if _clean("\n".join(lines))}
    if not result.get("summary"):
        source = result.get("preamble") or text
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", source) if p.strip()]
        result["summary"] = _clean("\n\n".join(paragraphs[:3]), 2200)
    return result


def _clip(text: str, limit: int) -> str:
    value = _clean(text, limit + 500)
    if len(value) <= limit:
        return value
    cut = value.rfind("\n", 0, limit)
    if cut < int(limit * 0.65):
        cut = value.rfind(". ", 0, limit)
    if cut < int(limit * 0.65):
        cut = limit
    return value[:cut].rstrip(" .,:;\n") + "…"


def _split(text: str, limit: int = 3800) -> list[str]:
    value = _clean(text)
    if not value:
        return ["Информация для этого раздела отсутствует."]
    parts: list[str] = []
    while len(value) > limit:
        cut = value.rfind("\n\n", 0, limit)
        if cut < int(limit * 0.55):
            cut = value.rfind("\n", 0, limit)
        if cut < int(limit * 0.55):
            cut = value.rfind(". ", 0, limit)
            if cut > 0:
                cut += 1
        if cut < int(limit * 0.55):
            cut = limit
        parts.append(value[:cut].strip())
        value = value[cut:].strip()
    if value:
        parts.append(value)
    return parts or ["Информация для этого раздела отсутствует."]


def _first_sentence(text: str, limit: int = 520) -> str:
    value = _clip(text, limit)
    match = re.search(r"(?<=[.!?])\s", value)
    if match and match.start() > 100:
        return value[: match.start() + 1].strip()
    return value


def _state_bucket(context: Any) -> dict[str, dict[str, Any]]:
    bucket = context.user_data.get(_STATE_KEY)
    if not isinstance(bucket, dict):
        bucket = {}
        context.user_data[_STATE_KEY] = bucket
    now = time.time()
    expired = [token for token, item in bucket.items() if now - float((item or {}).get("created_ts") or 0) > _STATE_TTL]
    for token in expired:
        bucket.pop(token, None)
    if len(bucket) > _MAX_STATES:
        ordered = sorted(bucket.items(), key=lambda pair: float((pair[1] or {}).get("created_ts") or 0))
        for token, _ in ordered[: len(bucket) - _MAX_STATES]:
            bucket.pop(token, None)
    return bucket


def _store(context: Any, answer: str, *, back_callback: str, title: str = "") -> str:
    token = hashlib.sha256(f"{time.time_ns()}|{answer[:2000]}|{back_callback}".encode("utf-8", errors="ignore")).hexdigest()[:10]
    _state_bucket(context)[token] = {
        "answer": _clean(answer, 40000),
        "sections": parse_sections(answer),
        "back_callback": _clean(back_callback, 64) or "medcard:back_med",
        "title": _clean(title, 120),
        "created_ts": time.time(),
    }
    return token


def _get(context: Any, token: str) -> dict[str, Any] | None:
    item = _state_bucket(context).get(str(token or ""))
    return item if isinstance(item, dict) else None


def _button(mod: Any, text: str, data: str):
    return mod.InlineKeyboardButton(text, callback_data=data)


def _keyboard(mod: Any, token: str, back_callback: str):
    return mod.InlineKeyboardMarkup([
        [_button(mod, "🎯 Кратко", f"meddetail:summary:{token}"), _button(mod, "📋 Полный разбор", f"meddetail:full:{token}")],
        [_button(mod, "✅ Что делать", f"meddetail:plan:{token}"), _button(mod, "🗣 Что сказать врачу", f"meddetail:doctor:{token}")],
        [_button(mod, "🔎 Находки", f"meddetail:findings:{token}"), _button(mod, "🚑 Когда срочно", f"meddetail:urgent:{token}")],
        [_button(mod, "⬅️ К документу" if back_callback.startswith("medcard:doc:") else "⬅️ В Медицину", back_callback)],
    ])


def _summary_view(state: dict[str, Any]) -> str:
    sections = state.get("sections") or {}
    summary = _clip(sections.get("summary") or state.get("answer") or "", 2500)
    seriousness = _clip(sections.get("seriousness") or "", 650)
    body = "🎯 ГЛАВНОЕ ЗА 30 СЕКУНД\n\n" + summary
    if seriousness and seriousness.lower() not in summary.lower():
        body += "\n\n⚖️ ОЦЕНКА СЕРЬЁЗНОСТИ\n" + seriousness
    body += "\n\nНиже можно открыть только нужный раздел, не перечитывая весь отчёт.\n\n" + STANDARD_DISCLAIMER
    return _clip(body, 3800)


def _view(state: dict[str, Any], action: str) -> str:
    sections = state.get("sections") or {}
    answer = _clean(state.get("answer") or "")
    if action == "summary":
        return _summary_view(state)
    if action == "full":
        return "📋 ПОЛНЫЙ МЕДИЦИНСКИЙ РАЗБОР\n\n" + answer
    if action == "findings":
        blocks = []
        if sections.get("document"):
            blocks.append("📋 ЧТО УКАЗАНО В ДОКУМЕНТЕ\n\n" + sections["document"])
        if sections.get("findings"):
            blocks.append("🔎 РАЗБОР ЗНАЧИМЫХ НАХОДОК\n\n" + sections["findings"])
        if sections.get("seriousness"):
            blocks.append("⚖️ НАСКОЛЬКО ЭТО СЕРЬЁЗНО\n\n" + sections["seriousness"])
        return "\n\n".join(blocks) or "🔎 Отдельный блок находок в ответе не выделен. Откройте полный разбор."
    if action == "plan":
        blocks = []
        if sections.get("plan"):
            blocks.append("✅ ЧТО ДЕЛАТЬ ДАЛЬШЕ\n\n" + sections["plan"])
        if sections.get("timeline"):
            blocks.append("📅 СРОКИ И НАБЛЮДЕНИЕ\n\n" + sections["timeline"])
        return "\n\n".join(blocks) or "✅ Отдельный план действий в ответе не выделен. Откройте полный разбор."
    if action == "doctor":
        summary = _first_sentence(sections.get("summary") or answer, 600)
        intro = (
            "🗣 ЧТО СКАЗАТЬ ВРАЧУ\n\n"
            "Можно начать приём так:\n"
            f"«У меня есть результаты исследования. Главная находка: {summary} "
            "Помогите уточнить причину, срочность и необходимый план обследования»."
        )
        blocks = [intro]
        if sections.get("doctor"):
            blocks.append("❓ ВОПРОСЫ ВРАЧУ\n\n" + sections["doctor"])
        if sections.get("missing"):
            blocks.append("🧩 ЧТО ВЗЯТЬ С СОБОЙ / ЧЕГО НЕ ХВАТАЕТ\n\n" + sections["missing"])
        return "\n\n".join(blocks)
    if action == "urgent":
        urgent = sections.get("urgent") or ""
        if urgent:
            return "🚑 КОГДА НУЖНА СРОЧНАЯ ПОМОЩЬ\n\n" + urgent + "\n\n" + STANDARD_DISCLAIMER
        return (
            "🚑 Отдельный блок срочных признаков в этом ответе не сформирован. "
            "При резком ухудшении самочувствия, сильной боли, нарушении дыхания или сознания, "
            "обильном кровотечении либо невозможности мочиться обращайтесь за неотложной помощью.\n\n"
            + STANDARD_DISCLAIMER
        )
    return _summary_view(state)


async def _render_callback(mod: Any, q: Any, state: dict[str, Any], action: str, token: str) -> None:
    text = _view(state, action)
    parts = _split(text)
    markup = _keyboard(mod, token, str(state.get("back_callback") or "medcard:back_med"))
    try:
        await q.message.edit_text(parts[0], reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        await q.message.reply_text(parts[0], reply_markup=markup, disable_web_page_preview=True)
    for part in parts[1:]:
        await q.message.reply_text(part, disable_web_page_preview=True)


async def send_compact_answer(
    mod: Any,
    update: Any,
    context: Any,
    answer: str,
    *,
    edit: bool = False,
    back_callback: str = "medcard:back_med",
    title: str = "",
) -> str:
    """Store the complete answer and show its compact progressive-disclosure UI."""
    token = _store(context, answer, back_callback=back_callback, title=title)
    state = _get(context, token) or {}
    text = _summary_view(state)
    markup = _keyboard(mod, token, back_callback)
    if edit and getattr(update, "callback_query", None) is not None:
        q = update.callback_query
        with contextlib.suppress(Exception):
            await q.answer()
        try:
            await q.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            await q.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
    else:
        await update.effective_message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
        with contextlib.suppress(Exception):
            await mod.maybe_tts_reply(update, context, text[: getattr(mod, "TTS_MAX_CHARS", 1000)])
    return token


async def handle_callback(mod: Any, update: Any, context: Any) -> bool:
    q = getattr(update, "callback_query", None)
    data = str(getattr(q, "data", "") or "")
    if not data.startswith("meddetail:"):
        return False
    with contextlib.suppress(Exception):
        await q.answer()
    parts = data.split(":", 2)
    action = parts[1] if len(parts) > 1 else "summary"
    token = parts[2] if len(parts) > 2 else ""
    state = _get(context, token)
    if not state:
        await q.message.edit_text(
            "Срок действия этих кнопок истёк. Откройте сохранённый документ в медицинской карте "
            "или запустите анализ заново."
        )
        return True
    await _render_callback(mod, q, state, action, token)
    return True


_BUILDER_HOOKED = False


def _runtime_module() -> Any | None:
    import sys
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


async def _entry_callback(update: Any, context: Any) -> None:
    mod = _runtime_module()
    if mod is None:
        return
    if await handle_callback(mod, update, context):
        from telegram.ext import ApplicationHandlerStop
        raise ApplicationHandlerStop


def install_early() -> None:
    """Register medical detail callbacks before main builds the PTB Application."""
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, "_medical_answer_ui_v120_hooked", False):
        _BUILDER_HOOKED = True
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, "_medical_answer_ui_v120_handler", False):
            app.add_handler(CallbackQueryHandler(_entry_callback, pattern=r"^meddetail:"), group=-98)
            setattr(app, "_medical_answer_ui_v120_handler", True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, "_medical_answer_ui_v120_hooked", True)
    _BUILDER_HOOKED = True


__all__ = ["VERSION", "parse_sections", "send_compact_answer", "handle_callback", "install_early"]
