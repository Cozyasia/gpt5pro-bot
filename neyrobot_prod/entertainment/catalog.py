"""Immutable menu specifications for Entertainment Menu V2."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class MenuButtonSpec:
    text: str
    callback_data: str
    status: str = "active"


@dataclass(frozen=True, slots=True)
class MenuSpec:
    menu_id: str
    title: str
    intro: str
    rows: tuple[tuple[MenuButtonSpec, ...], ...]


def _button(text: str, callback_data: str) -> MenuButtonSpec:
    return MenuButtonSpec(text=text, callback_data=callback_data)


def _soon(text: str, service_id: str) -> MenuButtonSpec:
    return MenuButtonSpec(
        text=f"{text} · Скоро",
        callback_data=f"ent:soon:{service_id}",
        status="soon",
    )


_MENUS: dict[str, MenuSpec] = {
    "root": MenuSpec(
        menu_id="root",
        title="🔥 Развлечения",
        intro=(
            "Создавайте видео, фото, музыку и готовые проекты — "
            "от идеи до результата. Выберите, что хотите получить."
        ),
        rows=(
            (_button("🎬 Нейро Продакшен", "ent:menu:production"),),
            (
                _button("🔥 В тренде", "ent:menu:trends"),
                _button("🎥 Создать видео", "ent:menu:video"),
            ),
            (
                _button("📸 Фото и эффекты", "ent:menu:photo"),
                _button("🎵 Музыка и песня", "fun:music"),
            ),
            (
                _button("🎮 Игры с AI", "fun:quiz"),
                _button("🎉 Чем заняться", "fun:ideas"),
            ),
            (_button("📝 Свой запрос", "fun:free"),),
            (_button("⬅️ Назад", "mode:root"),),
        ),
    ),
    "production": MenuSpec(
        menu_id="production",
        title="🎬 Нейро Продакшен",
        intro="Готовые производственные сценарии — от брифа до результата.",
        rows=(
            (_button("🏡 AI-видеообзор недвижимости", "revideo:start"),),
            (_button("🛍 Товар → рекламный ролик", "ent:brief:product_ad"),),
            (_button("📱 UGC-реклама", "ent:brief:ugc_ad"),),
            (_button("🏠 Реклама недвижимости", "ent:brief:real_estate_ad"),),
            (_button("👤 Экспертное видео", "ent:brief:expert_video"),),
            (_button("💎 Брендовый ролик", "ent:brief:brand_video"),),
            (_button("📦 Серия Reels / Shorts", "ent:brief:reels_series"),),
            (_soon("🌍 Перевести и озвучить видео", "video_translation"),),
            (_button("🧪 3 версии рекламы", "ent:brief:ad_variants"),),
            (_button("🤝 Индивидуальный проект", "ent:brief:custom_project"),),
            (_button("🎛 Режим режиссёра", "fun:video_director"),),
            (_button("⬅️ Назад", "ent:back:root"),),
        ),
    ),
    "trends": MenuSpec(
        menu_id="trends",
        title="🔥 В тренде",
        intro="Популярные быстрые форматы для фото и коротких видео.",
        rows=(
            (_button("✨ Фото оживает", "fun:revive"),),
            (_button("🗣 Фото говорит", "fun:avatar"),),
            (_soon("💃 Фото танцует", "photo_dance"),),
            (_soon("🎞 Я в кино", "in_movie"),),
            (_button("⭐ Селфи со звездой", "fun:aiselfie"),),
            (_soon("🎁 Видео-поздравление", "video_greeting"),),
            (_soon("↔️ До / После", "before_after"),),
            (_button("✈️ Travel Reel", "fun:reels"),),
            (_soon("👗 Сменить образ", "change_outfit"),),
            (_button("⬅️ Назад", "ent:back:root"),),
        ),
    ),
    "video": MenuSpec(
        menu_id="video",
        title="🎥 Создать видео",
        intro="Выберите способ создания — бот откроет подходящий рабочий сценарий.",
        rows=(
            (_button("💬 Видео по тексту или голосу", "fun:textvideo"),),
            (_button("🎤 Клип с вокалом", "fun:vocalclip"),),
            (_button("🖼 Оживить фото", "fun:revive"),),
            (_button("📱 Reels / Shorts", "fun:reels"),),
            (_button("🎬 Мини-фильм", "fun:film"),),
            (_button("📝 Сценарий и раскадровка", "fun:storyboard"),),
            (_button("✨ Авторежиссёр", "fun:video_director"),),
            (_button("✂️ Автомонтаж", "fun:video_montage"),),
            (_soon("➕ Продолжить видео", "continue_video"),),
            (_button("🧠 Выбрать модель", "fun:textvideo"),),
            (_button("✨ Seedance 2.5 · Видео по тексту", "fun:tv_engine_seedance"),),
            (_button("⬅️ Назад", "ent:back:root"),),
        ),
    ),
    "photo": MenuSpec(
        menu_id="photo",
        title="📸 Фото и эффекты",
        intro="Создание и точечное редактирование изображений.",
        rows=(
            (_button("🎨 Создать изображение", "fun:img"),),
            (_button("⭐ Селфи со звездой", "fun:aiselfie"),),
            (_button("🔄 Замена лица", "fun:faceswap"),),
            (_button("🧼 Удалить фон", "fun:removebg"),),
            (_button("🖼 Заменить фон", "fun:replacebg"),),
            (_soon("✨ Ретушь и улучшение", "retouch"),),
            (_soon("🧽 Удалить объект или текст", "remove_object"),),
            (_soon("↔️ Расширить кадр", "outpaint"),),
            (_soon("👗 Сменить образ", "photo_outfit"),),
            (_soon("👁 Что на фото?", "vision"),),
            (_button("⬅️ Назад", "ent:back:root"),),
        ),
    ),
}
_FALSE_VALUES = {"", "0", "false", "no", "off"}


def entertainment_menu_v2_enabled(
    environ: Mapping[str, str] | None = None,
    user_id: int | None = None,
) -> bool:
    source = os.environ if environ is None else environ
    value = str(source.get("ENTERTAINMENT_MENU_V2", "")).strip().lower()
    if value not in _FALSE_VALUES:
        return True

    # Render production has reached its environment-variable limit.  When
    # the flag is absent, enable the shipped menu on Render without requiring
    # another variable.  An explicit false value still disables rollout.
    if "ENTERTAINMENT_MENU_V2" not in source and source.get("RENDER_GIT_COMMIT"):
        return True

    canary = str(
        source.get("ENTERTAINMENT_MENU_V2_OWNER_CANARY", "")
    ).strip().lower()
    if canary in _FALSE_VALUES or user_id is None:
        return False

    try:
        owner_id = int(str(source.get("OWNER_ID", "0")).strip() or "0")
        candidate_id = int(user_id)
    except (TypeError, ValueError):
        return False
    return owner_id > 0 and candidate_id == owner_id


def get_menu(menu_id: str) -> MenuSpec:
    return _MENUS[menu_id]


def iter_menus() -> tuple[MenuSpec, ...]:
    return tuple(_MENUS.values())
