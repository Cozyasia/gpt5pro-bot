"""Read-only Telegram prompt catalog with in-place navigation."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationHandlerStop

from neyrobot_prod.studio_prompt_telegram import (
    category_buttons, template_page, resolve_template_callback,
)
from neyrobot_prod.studio_prompt_library import list_prompt_categories, get_prompt_template


def _keyboard(buttons):
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data)]
                                 for label, data in buttons])


async def cmd_studio_prompts(update, context):
    await update.effective_message.reply_text(
        "🎬 Библиотека промптов GPT5 Studio AI\nВыберите категорию:",
        reply_markup=_keyboard(category_buttons()),
    )


async def _edit(q, text, markup):
    # A callback originates from a bot message; edit instead of posting another menu.
    await q.edit_message_text(text, reply_markup=markup)


async def cb_studio_prompts(update, context):
    q = update.callback_query
    data = q.data or ""
    await q.answer()
    if data == "spl:home":
        await _edit(q, "🎬 Библиотека промптов\nВыберите категорию:", _keyboard(category_buttons()))
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
        nav = []
        if page["previous"]:
            nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=page["previous"]))
        if page["next"]:
            nav.append(InlineKeyboardButton("Далее ➡️", callback_data=page["next"]))
        rows = [[InlineKeyboardButton(label, callback_data=cb)] for label, cb in page["buttons"]]
        if nav:
            rows.append(nav)
        rows.append([InlineKeyboardButton("📚 Категории", callback_data="spl:home")])
        names = {c["id"]: c["title"] for c in list_prompt_categories()}
        await _edit(q,
            f'🎬 {names[page["category"]]}: {page["total"]} шаблонов. Страница {page["page"] + 1}.',
            InlineKeyboardMarkup(rows),
        )
        raise ApplicationHandlerStop
    if data.startswith("spl:p:"):
        item = resolve_template_callback(data)
        if item is None:
            await q.message.reply_text("Шаблон не найден.")
            raise ApplicationHandlerStop
        context.user_data["studio_prompt_selected_id"] = item["id"]
        await _edit(q,
            f'🎬 {item["title"]}\n\n{item["prompt"]}\n\n'
            "Это заготовка. Скопируйте и отредактируйте текст перед запуском генерации.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("✏️ Использовать промпт", callback_data=f'spl:use:{item["id"]}')
            ], [InlineKeyboardButton("📚 Категории", callback_data="spl:home")]]),
        )
        raise ApplicationHandlerStop
    if data.startswith("spl:use:"):
        parts = data.split(":")
        item = get_prompt_template(parts[2]) if len(parts) == 3 else None
        if item is None:
            await q.message.reply_text("Шаблон не найден.")
            raise ApplicationHandlerStop
        context.user_data["studio_prompt_draft"] = item["prompt"]
        await q.message.reply_text(
            "✏️ Промпт подготовлен для редактирования.\n\n"
            + item["prompt"]
            + "\n\nСкопируйте текст, внесите изменения и затем выберите "
              "«Авторежиссёр» в меню бота. Отправка этого текста в режим "
              "Авторежиссёра может запустить платную генерацию; "
              "перед этим проверьте стоимость и настройки."
        )
        raise ApplicationHandlerStop
    await q.message.reply_text("Неизвестная команда каталога.")
    raise ApplicationHandlerStop
