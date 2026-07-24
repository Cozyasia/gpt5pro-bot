# -*- coding: utf-8 -*-
"""Small idempotent guard for v162's two photo-choice callbacks.

The v124 UI introduced ``celeb:use_cached`` and ``celeb:upload_user`` above the
older v122 callback engine.  v162 owns the earlier handler group, so these two
callbacks must be consumed directly before delegating every other catalog/scene
button to v122.  This module also makes free-text name resolution tolerant of a
full phrase such as ``селфи с Романом Абрамовичем в ресторане``.
"""
from __future__ import annotations

import contextlib
import re
from typing import Any

import celebrity_selfie_v122 as engine
import celebrity_selfie_v124 as wizard
from . import hotfix_v162 as release

_INSTALLED = False
_ORIGINAL_ENTRY = release._entry_callback


def _stop() -> None:
    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop


def _clean_queries(text: str) -> list[str]:
    raw = str(text or "").strip()
    normalized = release._normalise(raw)
    queries: list[str] = [raw]
    cleaned = normalized
    for token in release._SELFIE_WORDS:
        cleaned = cleaned.replace(release._normalise(token), " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:-")
    if cleaned:
        queries.append(cleaned)
    # Name usually follows «с/со» and precedes a scene preposition. Keep this as
    # an additional search query; exact alias verification still happens below.
    match = re.search(r"(?:^|\s)(?:с|со)\s+(.+?)(?:\s+(?:в|на|у|около|рядом)\s+|$)", normalized)
    if match and match.group(1).strip():
        queries.append(match.group(1).strip())
    if "роман" in normalized and "абрамович" in normalized:
        queries.append("Роман Абрамович")
    result: list[str] = []
    for query in queries:
        if query and query not in result:
            result.append(query)
    return result


def _catalog_match(text: str) -> dict[str, Any] | None:
    normalized = release._normalise(text)
    all_candidates: list[dict[str, Any]] = []
    for query in _clean_queries(text):
        with contextlib.suppress(Exception):
            for item in list(engine.search_catalog(query, 16) or []):
                if not any(str(existing.get("id") or "") == str(item.get("id") or "") for existing in all_candidates):
                    all_candidates.append(item)
    for item in all_candidates:
        for value in release._catalog_values(item):
            alias = release._normalise(value)
            if alias and alias in normalized:
                return item
    if len(all_candidates) == 1:
        return all_candidates[0]
    # Explicit Roman fallback is still resolved through the catalog, never by a
    # hard-coded synthetic entry, so the fixed v158/v161 reference route applies.
    if "роман" in normalized and "абрамович" in normalized:
        for item in all_candidates:
            if str(item.get("id") or "") == "ru_roman_abramovich":
                return item
    return None


async def _entry_callback(update: Any, context: Any) -> None:
    data = str(getattr(getattr(update, "callback_query", None), "data", "") or "")
    if data not in {"celeb:use_cached", "celeb:upload_user"}:
        await _ORIGINAL_ENTRY(update, context)
        return

    with contextlib.suppress(Exception):
        await update.callback_query.answer()
    if not release._active(context):
        wizard._start_session(context)

    session = release._session(context)
    if data == "celeb:upload_user":
        if isinstance(session, dict):
            session["state"] = "await_user_photo"
        await update.effective_message.reply_text(
            "📤 Пришлите новое селфи обычной фотографией Telegram или файлом JPG/PNG/WEBP. "
            "После загрузки откроется каталог знаменитостей и персонажей.",
            reply_markup=engine._kb([[('❌ Отмена', 'celeb:cancel')]]),
        )
        _stop()

    raw = wizard._cached_photo(update)
    if not raw:
        if isinstance(session, dict):
            session["state"] = "await_user_photo"
        await update.effective_message.reply_text(
            "Последнее фото не найдено. Пришлите новое селфи.",
            reply_markup=engine._kb([[('❌ Отмена', 'celeb:cancel')]]),
        )
        _stop()
    await wizard._accept_user_photo(update, context, raw)
    await release._resume_pending_after_photo(update, context)
    _stop()


def install() -> bool:
    global _INSTALLED
    release._catalog_match = _catalog_match
    release._entry_callback = _entry_callback
    _INSTALLED = True
    return True


install()

__all__ = ["install", "_catalog_match", "_entry_callback", "_clean_queries"]
