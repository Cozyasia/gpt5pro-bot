"""Production-mode brief intake, shared with the existing video director pipeline.

A selected template opens the already-implemented studio prompt handler rather than
pretending to generate a video or charging a user for an incomplete job.
"""
from __future__ import annotations

from .catalog import entertainment_menu_v2_enabled

BRIEFS = {
    "product_ad": ("🛍 Реклама товара", "Название товара, преимущества, аудитория, призыв к действию и желаемая длительность"),
    "ugc_ad": ("📱 UGC-реклама", "Товар, герой ролика, проблема покупателя, естественная подача и длительность"),
    "real_estate_ad": ("🏠 Реклама недвижимости", "Тип объекта, локация, площадь, преимущества, цена, аудитория и длительность"),
    "expert_video": ("👤 Экспертное видео", "Тема, квалификация эксперта, ключевые тезисы, аудитория и длительность"),
    "brand_video": ("💎 Брендовый ролик", "Название бренда, ценности, стиль, предложение, аудитория и длительность"),
    "reels_series": ("📦 Серия Reels", "Тема, количество роликов, длительность каждого, аудитория и последовательность сюжетов"),
    "video_translation": ("🌍 Перевод и озвучка", "Язык исходного видео, язык перевода, пожелания к голосу; затем пришлите исходное видео"),
    "ad_variants": ("🧪 Варианты рекламы", "Продукт, аудитория, три рекламных угла, целевая длительность и формат"),
    "custom_project": ("🤝 Индивидуальный проект", "Цель проекта, доступные исходные материалы, ожидаемый результат, длительность и ограничения"),
}

async def handle_production_brief(update, context):
    q = update.callback_query
    await q.answer()
    if not entertainment_menu_v2_enabled(user_id=q.from_user.id):
        await q.message.reply_text("Этот раздел пока недоступен.")
        return
    mode = (q.data or "").removeprefix("ent:brief:")
    if mode not in BRIEFS:
        await q.message.reply_text("Неизвестный сценарий. Вернитесь в Нейро Продакшен.")
        return
    title, fields = BRIEFS[mode]
    context.user_data["ent_production_mode"] = mode
    if mode == "video_translation":
        # Do not claim the existing director can translate an uploaded video.
        await q.message.reply_text(
            "🌍 Перевод и озвучка исходного видео пока не подключены к производственному конвейеру. "
            "Автоматическое списание кредитов не выполняется."
        )
        return
    context.user_data["awaiting_video_studio_prompt"] = True
    context.user_data["video_studio_mode"] = "director"
    await q.message.reply_text(
        f"{title}\n\nПришлите бриф одним сообщением: {fields}.\n\n"
        "После получения брифа запустится существующий сценарий авторежиссёра. "
        "Стоимость генерации определяется действующими правилами бота."
    )
