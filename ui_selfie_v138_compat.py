# -*- coding: utf-8 -*-
"""Isolation layer for v138.

v138 changes the live engine/UI only. Historical v135/v136 and v137 module
contracts remain intact for rollback diagnostics and regression tests.
"""
from __future__ import annotations

import contextlib
import os
from typing import Any

import celebrity_selfie_v136 as selfie
import chat_provider_v136 as chats
import ui_hotfix_v137 as ui137
import ui_selfie_v138 as v138

_GROUP = -81000
_BUILDER_FLAG = "_ui_selfie_v138_compat_builder"
_HANDLER_FLAG = "_ui_selfie_v138_compat_handlers"


def _v137_photo_choice_kb(has_cached: bool):
    from telegram import InlineKeyboardMarkup

    rows = []
    if has_cached:
        rows.append([
            ui137._inline_button(
                "Использовать последнее фото",
                "cs126:use_last",
                style="success",
                icon_env="SELFIE_LAST_PHOTO_CUSTOM_EMOJI_ID",
            )
        ])
    rows.append([
        ui137._inline_button(
            "Отмена",
            "cs126:cancel",
            style="danger",
            icon_env="CANCEL_CUSTOM_EMOJI_ID",
        )
    ])
    return InlineKeyboardMarkup(rows)


def _v137_second_angle_kb():
    from telegram import InlineKeyboardMarkup

    return InlineKeyboardMarkup([
        [ui137._inline_button(
            "Добавить второй ракурс", "cs136:add_user_ref",
            style="primary", icon_env="SELFIE_SECOND_ANGLE_CUSTOM_EMOJI_ID",
        )],
        [ui137._inline_button(
            "Продолжить с одним фото", "cs136:continue_one",
            style="success", icon_env="CONTINUE_CUSTOM_EMOJI_ID",
        )],
        [ui137._inline_button(
            "Отмена", "cs126:cancel",
            style="danger", icon_env="CANCEL_CUSTOM_EMOJI_ID",
        )],
    ])


def _v137_chat_provider_markup(provider: str):
    from telegram import InlineKeyboardMarkup

    provider = chats._normal_provider(provider)
    gpt_text = ui137._label("Чат с GPT", "◉", "GPT_BUTTON_CUSTOM_EMOJI_ID")
    gemini_text = ui137._label("Чат с Gemini", "✦", "GEMINI_BUTTON_CUSTOM_EMOJI_ID")
    if provider == "gpt":
        gpt_text = "✅ " + gpt_text
    else:
        gemini_text = "✅ " + gemini_text
    return InlineKeyboardMarkup([
        [ui137._inline_button(
            gpt_text, "chatprov:gpt",
            style="success" if provider == "gpt" else "primary",
            icon_env="GPT_BUTTON_CUSTOM_EMOJI_ID",
        )],
        [ui137._inline_button(
            gemini_text, "chatprov:gemini",
            style="success" if provider == "gemini" else "primary",
            icon_env="GEMINI_BUTTON_CUSTOM_EMOJI_ID",
        )],
        [ui137._inline_button(
            "Очистить историю выбранного чата", "chatprov:clear",
            style="danger", icon_env="CLEAR_HISTORY_CUSTOM_EMOJI_ID",
        )],
    ])


def _safe_install_runtime_patches() -> None:
    os.environ.setdefault("CELEBRITY_V136_MIN_DELIVERY_IDENTITY", "28")
    os.environ.setdefault("CELEBRITY_V138_PREVIEW_IDENTITY_FLOOR", "32")
    os.environ.setdefault("CELEBRITY_V138_VERIFIED_IDENTITY", "58")

    # Live UI only.
    selfie.wizard._photo_choice_kb = v138._photo_choice_kb
    selfie._second_angle_kb = v138._second_angle_kb
    chats._provider_markup = v138._chat_provider_markup

    # Live quality route only. Keep v136's identity-QC function itself intact;
    # the v138 scorer invokes its soft wrapper directly.
    selfie._score_candidate = v138._score_candidate_soft
    selfie._generate = v138._generate
    selfie.engine._generate = v138._generate
    selfie.engine._diag = v138._diag

    current_patch = getattr(chats, "_patch_main_keyboard", None)
    if callable(current_patch) and not getattr(current_patch, "_ui_selfie_v138_safe", False):
        def patched(mod: Any) -> None:
            current_patch(mod)
            v138.patch_main_keyboard(mod)

        setattr(patched, "_ui_selfie_v138_safe", True)
        chats._patch_main_keyboard = patched


def restore_historical_contracts() -> None:
    # v136/v134/v133 rollback modules.
    selfie._identity_detail_qc = v138._ORIGINAL_IDENTITY_QC
    selfie.v134._scene_assessment = v138._ORIGINAL_SCENE_ASSESSMENT

    # v137 public helper behavior remains exactly v137 for its own tests and
    # rollback diagnostics. Live objects above continue using v138 functions.
    ui137._photo_choice_kb = _v137_photo_choice_kb
    ui137._second_angle_kb = _v137_second_angle_kb
    ui137._chat_provider_markup = _v137_chat_provider_markup


async def _continue_callback(update: Any, context: Any) -> None:
    """Own v136 optional-angle callbacks before v137 and all legacy routers."""
    from telegram.ext import ApplicationHandlerStop

    query = getattr(update, "callback_query", None)
    if query is None:
        return
    data = str(getattr(query, "data", "") or "")
    if data not in {"cs136:add_user_ref", "cs136:continue_one"}:
        return
    with contextlib.suppress(Exception):
        await query.answer()

    session = selfie.wizard._session(context)
    if not session or not session.get("user_photo_path"):
        session["owner"] = selfie.VERSION
        session["state"] = "await_user_photo"
        selfie.wizard._data(context)[selfie.wizard._ACTIVE_KEY] = True
        await update.effective_message.reply_text(
            "Сначала пришлите основное селфи через скрепку или камеру Telegram.",
            reply_markup=v138._photo_choice_kb(False),
        )
        raise ApplicationHandlerStop

    session["owner"] = selfie.VERSION
    selfie.wizard._data(context)[selfie.wizard._ACTIVE_KEY] = True
    selfie.wizard._clear_legacy_state(context)
    if data == "cs136:add_user_ref":
        session["state"] = "await_user_photo_2"
        await update.effective_message.reply_text(
            "📎 Пришлите второй ракурс через скрепку или камеру Telegram: лёгкий поворот головы, без фильтров и очков.",
            reply_markup=v138._second_angle_kb(),
        )
        raise ApplicationHandlerStop

    session["state"] = "choose_celebrity"
    await update.effective_message.reply_text(
        "✅ Основное селфи сохранено. Теперь выберите человека из каталога или загрузите его референсы.",
        reply_markup=selfie.wizard._celebrity_menu_kb(),
    )
    raise ApplicationHandlerStop


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, _HANDLER_FLAG, False):
            app.add_handler(
                CallbackQueryHandler(
                    _continue_callback,
                    pattern=r"^cs136:(?:add_user_ref|continue_one)$",
                ),
                group=_GROUP,
            )
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


# Replace the unsafe installer for any later idempotent calls, then re-apply the
# live patches and restore historical module contracts.
v138.install_runtime_patches = _safe_install_runtime_patches
_safe_install_runtime_patches()
restore_historical_contracts()

__all__ = [
    "install_builder_hook", "restore_historical_contracts",
    "_safe_install_runtime_patches", "_continue_callback",
]
