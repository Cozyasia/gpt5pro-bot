"""Structured offline leisure suggestions. Never invent venue names or opening hours."""
from __future__ import annotations

OPTIONS = {
    "couple": ("❤️ Для пары", ("Приготовьте вместе новое блюдо", "Устройте вечер настольных игр", "Прогуляйтесь по любимому маршруту")),
    "kids": ("👨‍👩‍👧 С детьми", ("Сделайте домашний квест", "Устройте мастер-класс по рисованию", "Посетите ближайший парк, проверив погоду")),
    "friends": ("🥳 Для компании", ("Проведите тематический квиз", "Устройте кулинарный баттл", "Организуйте вечер настольных игр")),
    "home": ("🏠 Дома", ("Устройте домашний кинопоказ", "Попробуйте новый рецепт", "Сделайте творческий проект")),
    "budget": ("💸 Недорого", ("Прогуляйтесь по новому району", "Устройте фотопрогулку", "Посетите бесплатное общественное пространство")),
    "rain": ("🌧 В плохую погоду", ("Сыграйте в настольную игру", "Приготовьте горячий ужин", "Посетите музей, проверив часы работы")),
}

def suggestions(category: str) -> tuple[str, tuple[str, ...]]:
    return OPTIONS[category]

def format_suggestions(category: str) -> str:
    title, ideas = suggestions(category)
    return title + "\n\n" + "\n".join(f"{i}. {idea}" for i, idea in enumerate(ideas, 1)) + "\n\nЭто идеи без проверки местных событий и расписаний."

def keyboard():
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    return M([[B(label, callback_data=f"leisure:{key}")] for key, (label, _) in OPTIONS.items()] +
             [[B("📍 Рядом со мной", callback_data="leisure:nearby")],
              [B("⬅️ Развлечения", callback_data="ent:back:root")]])

async def handle_leisure_menu(update, context):
    q = update.callback_query
    await q.answer()
    await q.message.reply_text("🎉 Чем заняться? Выберите ситуацию — предложу конкретные идеи.", reply_markup=keyboard())

async def handle_leisure_callback(update, context):
    q = update.callback_query
    await q.answer()
    action = (q.data or "").partition(":")[2]
    if action == "nearby":
        await q.message.reply_text("📍 Для подбора реальных мест нужны город и актуальный поиск. Пока могу предложить варианты без привязки к заведениям.", reply_markup=keyboard())
        return
    if action not in OPTIONS:
        await q.message.reply_text("Выберите ситуацию:", reply_markup=keyboard())
        return
    context.user_data["ent_leisure_category"] = action
    await q.message.reply_text(format_suggestions(action), reply_markup=keyboard())
