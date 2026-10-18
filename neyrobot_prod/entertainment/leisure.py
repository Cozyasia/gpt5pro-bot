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

PREFERENCES = {
    "active": ("🚴 Активно", ("Устройте прогулку с фото-заданиями", "Попробуйте домашнюю тренировку", "Организуйте мини-турнир")),
    "calm": ("🧘 Спокойно", ("Сделайте вечер чтения", "Послушайте новый альбом вместе", "Попробуйте медитацию")),
    "creative": ("🎨 Творчество", ("Снимите короткий фильм на телефон", "Нарисуйте совместную картину", "Сочините историю по очереди")),
}

def personalized(category: str, interest: str, participants: int = 2, budget: int = 0) -> str:
    if participants < 1 or budget < 0:
        raise ValueError("Invalid preferences")
    title, ideas = suggestions(category)
    interest_title, interest_ideas = PREFERENCES[interest]
    return (f"{title} · {interest_title}\nУчастников: {participants}; бюджет: до {budget} ₽\n\n"
            + "\n".join(f"{index}. {idea}" for index, idea in enumerate((*ideas[:2], *interest_ideas[:2]), 1))
            + "\n\nЭто идеи без проверки местных событий и расписаний.")

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
    if action.startswith("interest:"):
        interest = action.partition("interest:")[2]
        category = context.user_data.get("ent_leisure_category", "home")
        if interest not in PREFERENCES:
            await q.message.reply_text("Выберите интерес:", reply_markup=keyboard())
            return
        context.user_data["ent_leisure_interest"] = interest
        await q.message.reply_text(personalized(category, interest), reply_markup=keyboard())
        return
    if action == "nearby":
        await q.message.reply_text("📍 Для подбора реальных мест нужны город и актуальный поиск. Пока могу предложить варианты без привязки к заведениям.", reply_markup=keyboard())
        return
    if action == "menu":
        await q.message.reply_text("Выберите ситуацию:", reply_markup=keyboard())
        return
    if action not in OPTIONS:
        await q.message.reply_text("Выберите ситуацию:", reply_markup=keyboard())
        return
    context.user_data["ent_leisure_category"] = action
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    rows = [[B(label, callback_data=f"leisure:interest:{key}")] for key, (label, _) in PREFERENCES.items()]
    rows.append([B("⬅️ Категории", callback_data="leisure:menu")])
    await q.message.reply_text(format_suggestions(action) + "\n\nВыберите интерес для уточнения:", reply_markup=M(rows))
