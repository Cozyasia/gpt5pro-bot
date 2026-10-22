"""Telegram UI for the Studio prompt library. No paid generation."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationHandlerStop

from neyrobot_prod.studio_prompt_telegram import (
    category_buttons, template_page, resolve_template_callback,
)


def _keyboard(buttons):
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data)]
                                 for label, data in buttons])


async def cmd_studio_prompts(update, context):
    await update.effective_message.reply_text(
        "🎬 Библиотека промптов GPT5 Studio AI\nВыберите категорию:",
        reply_markup=_keyboard(category_buttons()),
    )


async def cb_studio_prompts(update, context):
    q = update.callback_query
    data = q.data or ""
    await q.answer()
    if data == "spl:home":
        await q.message.reply_text("🎬 Категории промптов:", reply_markup=_keyboard(category_buttons()))
        raise ApplicationHandlerStop
    if data.startswith("spl:c:"):
        parts = data.split(":")
        if len(parts) != 4:
            await q.message.reply_text("Некорректная страница каталога.")
            raise ApplicationHandlerStop
        try:
            page = template_page(parts[2], int(parts[3]))
        except (ValueError, TypeError):
            await q.message.reply_text("Страница каталога недоступна.")
            raise ApplicationHandlerStop
        buttons = list(page["buttons"])
        nav = []
        if page["previous"]:
            nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=page["previous"]))
        if page["next"]:
            nav.append(InlineKeyboardButton("Далее ➡️", callback_data=page["next"]))
        rows = [[InlineKeyboardButton(label, callback_data=cb)] for label, cb in buttons]
        if nav:
            rows.append(nav)
        rows.append([InlineKeyboardButton("📚 Категории", callback_data="spl:home")])
        await q.message.reply_text(
            f'🎬 {page["category"]}: {page["total"]} шаблонов. Страница {page["page"] + 1}.',
            reply_markup=InlineKeyboardMarkup(rows),
        )
        raise ApplicationHandlerStop
    if data.startswith("spl:p:"):
        item = resolve_template_callback(data)
        if item is None:
            await q.message.reply_text("Шаблон не найден.")
            raise ApplicationHandlerStop
        context.user_data["studio_prompt_selected_id"] = item["id"]
        # Display text without running a provider. User can copy/edit before generation.
        await q.message.reply_text(
            f'🎬 {item["title"]}\n\n{item["prompt"]}\n\n'
            "Это заготовка. Скопируйте и отредактируйте текст перед запуском генерации.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📚 Категории", callback_data="spl:home")
            ]]),
        )
        raise ApplicationHandlerStop
    await q.message.reply_text("Неизвестная команда каталога.")
    raise ApplicationHandlerStop
