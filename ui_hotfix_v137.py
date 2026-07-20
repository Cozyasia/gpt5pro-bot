# -*- coding: utf-8 -*-
"""v137 UI/interaction hotfix.

- Dedicated high-priority owner for the optional second-angle callbacks.
- Removes the redundant "upload new selfie" inline button: users attach media
  directly with Telegram's paperclip/camera control.
- Adds brand-like GPT/Gemini labels, modern Telegram button styles and optional
  custom-emoji icons through environment-provided custom emoji IDs.

The project currently pins python-telegram-bot 21.6. Newer Bot API fields are
passed through ``api_kwargs`` so the upgrade is isolated and backward-safe.
"""
from __future__ import annotations

import contextlib
import logging
import os
from typing import Any

import celebrity_selfie_v136 as selfie
import chat_provider_v136 as chats

VERSION = "v137-selfie-callback-brand-buttons-2026-07-20"
_GROUP = -70000
_BUILDER_FLAG = "_ui_hotfix_v137_builder"
_HANDLER_FLAG = "_ui_hotfix_v137_handlers"
log = logging.getLogger("gpt-bot.ui-hotfix-v137")


def _custom_emoji_id(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    return value if value.isdigit() else ""


def _api_kwargs(*, style: str | None = None, icon_env: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if style in {"primary", "success", "danger"}:
        result["style"] = style
    if icon_env:
        icon_id = _custom_emoji_id(icon_env)
        if icon_id:
            result["icon_custom_emoji_id"] = icon_id
    return result


def _label(text: str, fallback_icon: str, icon_env: str) -> str:
    # A real custom emoji is rendered by Telegram before the text. Avoid a
    # duplicate unicode symbol when the owner configured the branded icon ID.
    return text if _custom_emoji_id(icon_env) else f"{fallback_icon} {text}"


def _inline_button(
    text: str,
    callback_data: str,
    *,
    style: str | None = None,
    icon_env: str | None = None,
):
    from telegram import InlineKeyboardButton

    kwargs = _api_kwargs(style=style, icon_env=icon_env)
    return InlineKeyboardButton(
        text=text,
        callback_data=callback_data,
        api_kwargs=kwargs or None,
    )


def _photo_choice_kb(has_cached: bool):
    """No redundant upload button; Telegram's attachment control is the upload."""
    from telegram import InlineKeyboardMarkup

    rows = []
    if has_cached:
        rows.append([
            _inline_button(
                "Использовать последнее фото",
                "cs126:use_last",
                style="success",
                icon_env="SELFIE_LAST_PHOTO_CUSTOM_EMOJI_ID",
            )
        ])
    rows.append([
        _inline_button(
            "Отмена",
            "cs126:cancel",
            style="danger",
            icon_env="CANCEL_CUSTOM_EMOJI_ID",
        )
    ])
    return InlineKeyboardMarkup(rows)


def _second_angle_kb():
    from telegram import InlineKeyboardMarkup

    return InlineKeyboardMarkup([
        [
            _inline_button(
                "Добавить второй ракурс",
                "cs136:add_user_ref",
                style="primary",
                icon_env="SELFIE_SECOND_ANGLE_CUSTOM_EMOJI_ID",
            )
        ],
        [
            _inline_button(
                "Продолжить с одним фото",
                "cs136:continue_one",
                style="success",
                icon_env="CONTINUE_CUSTOM_EMOJI_ID",
            )
        ],
        [
            _inline_button(
                "Отмена",
                "cs126:cancel",
                style="danger",
                icon_env="CANCEL_CUSTOM_EMOJI_ID",
            )
        ],
    ])


def _chat_provider_markup(provider: str):
    from telegram import InlineKeyboardMarkup

    provider = chats._normal_provider(provider)
    gpt_text = _label("Чат с GPT", "◉", "GPT_BUTTON_CUSTOM_EMOJI_ID")
    gemini_text = _label("Чат с Gemini", "✦", "GEMINI_BUTTON_CUSTOM_EMOJI_ID")
    if provider == "gpt":
        gpt_text = "✅ " + gpt_text
    else:
        gemini_text = "✅ " + gemini_text
    return InlineKeyboardMarkup([
        [
            _inline_button(
                gpt_text,
                "chatprov:gpt",
                style="success" if provider == "gpt" else "primary",
                icon_env="GPT_BUTTON_CUSTOM_EMOJI_ID",
            )
        ],
        [
            _inline_button(
                gemini_text,
                "chatprov:gemini",
                style="success" if provider == "gemini" else "primary",
                icon_env="GEMINI_BUTTON_CUSTOM_EMOJI_ID",
            )
        ],
        [
            _inline_button(
                "Очистить историю выбранного чата",
                "chatprov:clear",
                style="danger",
                icon_env="CLEAR_HISTORY_CUSTOM_EMOJI_ID",
            )
        ],
    ])


def _styled_reply_button(button: Any):
    from telegram import KeyboardButton

    text = str(getattr(button, "text", button) or "")
    low = text.casefold()
    style = "primary"
    icon_env = ""
    if "новый чат" in low:
        style, icon_env = "success", "NEW_CHAT_CUSTOM_EMOJI_ID"
    elif "мои чаты" in low:
        style, icon_env = "primary", "CHATS_CUSTOM_EMOJI_ID"
    elif "баланс" in low or "подпис" in low:
        style = "success"
    elif "отмена" in low or "назад" in low:
        style = "danger"
    elif "gpt" in low:
        icon_env = "GPT_BUTTON_CUSTOM_EMOJI_ID"
    elif "gemini" in low:
        icon_env = "GEMINI_BUTTON_CUSTOM_EMOJI_ID"

    # Preserve special request/web-app button fields by leaving them untouched.
    special = any(
        getattr(button, name, None) is not None
        for name in (
            "request_users", "request_chat", "request_contact", "request_location",
            "request_poll", "web_app",
        )
    )
    if special:
        return button
    return KeyboardButton(
        text=text,
        api_kwargs=_api_kwargs(style=style, icon_env=icon_env) or None,
    )


def patch_main_keyboard(mod: Any) -> None:
    try:
        from telegram import ReplyKeyboardMarkup

        markup = getattr(mod, "main_kb", None)
        keyboard = getattr(markup, "keyboard", None)
        if not keyboard:
            return
        rows = [[_styled_reply_button(button) for button in row] for row in keyboard]
        mod.main_kb = ReplyKeyboardMarkup(
            rows,
            resize_keyboard=bool(getattr(markup, "resize_keyboard", True)),
            one_time_keyboard=bool(getattr(markup, "one_time_keyboard", False)),
            selective=bool(getattr(markup, "selective", False)),
            input_field_placeholder=getattr(markup, "input_field_placeholder", None),
            is_persistent=getattr(markup, "is_persistent", None),
        )
    except Exception as exc:
        log.warning("Cannot apply v137 reply keyboard styles: %s", exc)


def install_runtime_patches() -> None:
    selfie.wizard._photo_choice_kb = _photo_choice_kb
    selfie._second_angle_kb = _second_angle_kb
    chats._provider_markup = _chat_provider_markup

    # chat_provider_v136 periodically calls this function. Keep its original
    # insertion logic, then apply styles/custom icons to the finished keyboard.
    original = getattr(chats, "_patch_main_keyboard", None)
    if callable(original) and not getattr(original, "_ui_hotfix_v137", False):
        def patched(mod: Any) -> None:
            original(mod)
            patch_main_keyboard(mod)

        setattr(patched, "_ui_hotfix_v137", True)
        chats._patch_main_keyboard = patched


async def _continue_callback(update: Any, context: Any) -> None:
    """Own cs136 callbacks before every legacy catch-all callback router."""
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
            reply_markup=_photo_choice_kb(False),
        )
        raise ApplicationHandlerStop

    session["owner"] = selfie.VERSION
    selfie.wizard._data(context)[selfie.wizard._ACTIVE_KEY] = True
    selfie.wizard._clear_legacy_state(context)

    if data == "cs136:add_user_ref":
        session["state"] = "await_user_photo_2"
        await update.effective_message.reply_text(
            "📎 Пришлите второй ракурс через скрепку или камеру Telegram: лёгкий поворот головы, без фильтров и очков.",
            reply_markup=_second_angle_kb(),
        )
        raise ApplicationHandlerStop

    # continue_one: never delegate this new callback to v122/v126 legacy
    # routers; that delegation produced the visible "Неизвестная команда" alert.
    session["state"] = "choose_celebrity"
    await update.effective_message.reply_text(
        "✅ Основное селфи сохранено. Теперь выберите человека из каталога или загрузите его референсы.",
        reply_markup=selfie.wizard._celebrity_menu_kb(),
    )
    raise ApplicationHandlerStop


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    await update.effective_message.reply_text(
        f"🎨 UI Hotfix / {VERSION}\n"
        "selfie_upload_button=removed\n"
        "cs136_callback_owner=dedicated_high_priority\n"
        "chat_brand_labels=enabled\n"
        "button_styles=enabled_via_api_kwargs\n"
        f"gpt_custom_icon={'ready' if _custom_emoji_id('GPT_BUTTON_CUSTOM_EMOJI_ID') else 'unicode-fallback'}\n"
        f"gemini_custom_icon={'ready' if _custom_emoji_id('GEMINI_BUTTON_CUSTOM_EMOJI_ID') else 'unicode-fallback'}"
    )
    raise ApplicationHandlerStop


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler
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
            app.add_handler(CommandHandler("diag_ui", _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


install_runtime_patches()

__all__ = [
    "VERSION", "install_runtime_patches", "install_builder_hook",
    "patch_main_keyboard", "_photo_choice_kb", "_second_angle_kb",
    "_chat_provider_markup", "_continue_callback", "_api_kwargs",
]
