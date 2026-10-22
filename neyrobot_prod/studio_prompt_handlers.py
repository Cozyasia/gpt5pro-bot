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
    if data == "spl:director:preview":
        draft = context.user_data.get("studio_prompt_draft")
        if not draft:
            await q.message.reply_text("Черновик не найден. Выберите промпт заново.")
            raise ApplicationHandlerStop
        import re
        from neyrobot_prod.studio_director_v2 import prepare_storyboard
        match = re.search(r"(?i)(\\d+)\\s*(?:секунд(?:ы|у)?|сек(?:унд)?|с)(?![а-яa-z])", draft)
        duration = max(4, min(30, int(match.group(1)) if match else 20))
        aspect = next((v for v in ("9:16", "16:9", "1:1", "4:5") if v in draft), "9:16")
        try:
            prepare_storyboard(draft, duration=duration, aspect_ratio=aspect)
        except ValueError as exc:
            await q.message.reply_text("❌ Ошибка сценария: " + str(exc)[:500])
            raise ApplicationHandlerStop
        await q.message.reply_text(
            f"🎬 Предварительная проверка пройдена.\\n"
            f"Длительность: {duration} сек. Формат: {aspect}.\\n\\n"
            "Это только проверка сценария, не расчёт стоимости. "
            "Генерация не запущена. Для запуска требуется отдельное "
            "подтверждение после точного расчёта цены.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💳 Ориентир стоимости", callback_data="spl:director:quote")
            ]])
        )
        raise ApplicationHandlerStop
    if data.startswith("spl:use:"):
        parts = data.split(":")
        item = get_prompt_template(parts[2]) if len(parts) == 3 else None
        if item is None:
            await q.message.reply_text("Шаблон не найден.")
            raise ApplicationHandlerStop
        context.user_data["studio_prompt_draft"] = item["prompt"]
        context.user_data["studio_prompt_awaiting_edit"] = True
        await q.message.reply_text(
            "✏️ Отправьте следующим сообщением отредактированный текст промпта. "
            "Я сохраню его как черновик и покажу перед генерацией. "
            "Деньги не списываются. Для отмены отправьте /cancel."
        )
        raise ApplicationHandlerStop
    await q.message.reply_text("Неизвестная команда каталога.")
    raise ApplicationHandlerStop

async def receive_prompt_draft(update, context, text: str) -> bool:
    """Intercept exactly one text edit when the user explicitly chose Use Prompt."""
    if not context.user_data.get("studio_prompt_awaiting_edit"):
        return False
    if text.strip().lower() == "/cancel":
        context.user_data.pop("studio_prompt_awaiting_edit", None)
        context.user_data.pop("studio_prompt_draft", None)
        await update.effective_message.reply_text("Редактирование промпта отменено.")
        return True
    if text.startswith("/"):
        return False
    if not text.strip():
        await update.effective_message.reply_text("Отправьте непустой текст промпта.")
        return True
    if len(text) > 12000:
        await update.effective_message.reply_text("Промпт слишком длинный (максимум 12 000 символов).")
        return True
    context.user_data["studio_prompt_draft"] = text.strip()
    context.user_data.pop("studio_prompt_awaiting_edit", None)
    await update.effective_message.reply_text(
        "🎬 Черновик готов к подготовке Авторежиссёра. Генерация не запущена.\n"
        "Для проверки сценария нажмите кнопку ниже.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎬 Проверить для Авторежиссёра", callback_data="spl:director:preview")
        ]]),
    )
    await update.effective_message.reply_text(
        "✅ Черновик сохранён. Генерация не запущена.\n\n"
        + text.strip()
        + "\n\nДля создания видео откройте «Авторежиссёр» в меню бота "
          "и отправьте этот текст после проверки условий и стоимости."
    )
    return True
