# -*- coding: utf-8 -*-
"""Compatibility isolation for the v142 preserve-user live overlay.

The live Telegram engine stays on v142. The historical v139 pipeline callable
and component version remain stable, while v141's public live surfaces point to
compatible v142 dispatchers so existing callback and contract tests continue to
observe one owner.
"""
from __future__ import annotations

from typing import Any

import celebrity_selfie_v139 as v139
import celebrity_selfie_v140 as v140
import celebrity_selfie_v140_hotfix as v140_hotfix
import celebrity_selfie_v141 as v141
import celebrity_selfie_v142 as v142
import ui_selfie_v138 as ui138


async def _historical_v141_generate(update: Any, context: Any, *, refinement: bool = False) -> None:
    """Kept for rollback diagnostics; the live surface uses v142._generate."""
    if refinement:
        await v141._postprocess(update, context, "similarity")
        return
    await v141._ORIGINAL_GENERATE(update, context, refinement=False)
    session = v141._session(context)
    if session.get("state") == "result" and session.get("result_path"):
        v141._snapshot_accepted(session)


def _combined_result_kb(has_selected: bool):
    """v142 UX with the complete v141 callback contract and no user synthesis."""
    from telegram import InlineKeyboardMarkup

    base = v142._ORIGINAL_V141_RESULT_KB(has_selected)
    rows = [
        [ui138._inline_button("Улучшить сходство", "cs141:similarity", primary=True)],
        [ui138._inline_button("Убрать рябь / улучшить качество", "cs141:quality")],
        [ui138._inline_button("Моё лицо сохранено без перерисовки", "cs141:user")],
        [ui138._inline_button("Усилить лицо знаменитости", "cs141:celebrity")],
        [ui138._inline_button("Пересобрать только знаменитость", "cs142:celebrity_rebuild")],
        [ui138._inline_button("Вернуть предыдущий результат", "cs141:undo")],
    ]
    for row in getattr(base, "inline_keyboard", None) or []:
        filtered = []
        for button in row:
            callback = str(getattr(button, "callback_data", "") or "")
            text = " ".join(str(getattr(button, "text", "") or "").casefold().replace("ё", "е").split())
            if callback.startswith("cs141:") or "улучшить" in text or "вернуть предыдущ" in text:
                continue
            filtered.append(button)
        if filtered:
            rows.append(filtered)
    return InlineKeyboardMarkup(rows)


def install() -> None:
    # Preserve the v139 component contract used by rollback tests and diagnostics.
    v139.VERSION = v140_hotfix.V139_COMPONENT_VERSION
    v139._run_two_stage_generation = v140._run_v140_generation

    # v141 remains the public live facade, but delegates generation and keyboard
    # ownership to v142. The callback set remains backward-compatible.
    v139._generate = v142._generate
    v141._generate = v142._generate
    v141._result_kb = _combined_result_kb

    # Reassert v142 only on the live engine/runtime surfaces.
    selfie = v139.selfie
    selfie._run_v142_generation = v142._run_v142_generation
    selfie._generate = v142._generate
    selfie.engine._run_multi_reference_generation = v142._run_compat
    selfie.engine._generate = v142._generate
    selfie.engine._result_kb = _combined_result_kb
    selfie.engine._diag = v142._diag


install()

__all__ = ["install", "_historical_v141_generate", "_combined_result_kb"]
