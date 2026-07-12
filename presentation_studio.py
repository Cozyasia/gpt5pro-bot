# -*- coding: utf-8 -*-
"""Production presentation/catalog wizard for Neyro-Bot GPT 5 Studio.

The module keeps project state in SQLite, accepts uploaded assets, coordinates
AI logo/image generation through callbacks supplied by main.py, and renders the
same approved project into PPTX and PDF.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import math
import os
import re
import shutil
import sqlite3
import textwrap
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from PIL import Image, ImageDraw, ImageFont, ImageOps
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import ContextTypes

log = logging.getLogger("presentation-studio")

JsonDict = dict[str, Any]
LLMCall = Callable[[Update, str], Awaitable[str]]
ImageBatchCall = Callable[[Update, ContextTypes.DEFAULT_TYPE, list[str], str, str], Awaitable[list[bytes] | None]]
PaidRunner = Callable[[Update, ContextTypes.DEFAULT_TYPE, str, str, float, Callable[[], Awaitable[Any]]], Awaitable[Any]]


STYLE_PRESETS: dict[str, JsonDict] = {
    "luxury": {
        "label": "👑 Премиум / luxury",
        "font": "Aptos",
        "title_size": 29,
        "body_size": 17,
        "accent_shape": "line",
        "default_palette": "black_gold",
    },
    "corporate": {
        "label": "💼 Строгий корпоративный",
        "font": "Aptos",
        "title_size": 28,
        "body_size": 17,
        "accent_shape": "bar",
        "default_palette": "blue_gray",
    },
    "minimal": {
        "label": "🧼 Минимализм",
        "font": "Aptos",
        "title_size": 30,
        "body_size": 18,
        "accent_shape": "dot",
        "default_palette": "white_minimal",
    },
    "product": {
        "label": "📦 Коммерческий каталог",
        "font": "Aptos",
        "title_size": 27,
        "body_size": 16,
        "accent_shape": "card",
        "default_palette": "white_blue",
    },
    "real_estate": {
        "label": "🏝 Недвижимость / lifestyle",
        "font": "Aptos",
        "title_size": 29,
        "body_size": 17,
        "accent_shape": "image",
        "default_palette": "sand_green",
    },
}

PALETTE_PRESETS: dict[str, JsonDict] = {
    "black_gold": {"label": "⚫ Чёрно-золотая", "bg": "101215", "surface": "1B1F24", "text": "F7F3EA", "muted": "C7BFAE", "accent": "D6B25E", "accent2": "8E6D2F"},
    "blue_gray": {"label": "🔵 Сине-серая", "bg": "F4F7FB", "surface": "FFFFFF", "text": "14213D", "muted": "5F6B7A", "accent": "2F6BFF", "accent2": "AFC7FF"},
    "white_minimal": {"label": "⚪ Белая минималистичная", "bg": "FFFFFF", "surface": "F5F6F8", "text": "121417", "muted": "6D737C", "accent": "111111", "accent2": "D9DDE3"},
    "white_blue": {"label": "🟦 Светлая коммерческая", "bg": "F7FAFF", "surface": "FFFFFF", "text": "13233A", "muted": "64748B", "accent": "2477FF", "accent2": "D7E7FF"},
    "sand_green": {"label": "🏝 Бежевая / lifestyle", "bg": "F2EEE6", "surface": "FCFAF6", "text": "26352E", "muted": "6B786F", "accent": "4F7A65", "accent2": "CBBE9E"},
    "navy_cyan": {"label": "🌌 Тёмно-синяя", "bg": "0B1220", "surface": "111B2E", "text": "F6FAFF", "muted": "B8C6D9", "accent": "4CC9F0", "accent2": "4361EE"},
}

STATE_LABELS = {
    "awaiting_brief": "ожидает бриф",
    "awaiting_outline_confirmation": "ожидает утверждение структуры",
    "awaiting_outline_revision": "ожидает правки структуры",
    "awaiting_logo_choice": "ожидает решение по логотипу",
    "awaiting_logo_upload": "ожидает загрузку логотипа",
    "awaiting_logo_brief": "ожидает бриф логотипа",
    "awaiting_logo_selection": "ожидает выбор логотипа",
    "awaiting_asset_source": "ожидает выбор изображений",
    "uploading_assets": "идёт загрузка изображений",
    "awaiting_style": "ожидает выбор стиля",
    "awaiting_custom_style": "ожидает описание стиля",
    "awaiting_palette": "ожидает выбор палитры",
    "awaiting_custom_palette": "ожидает описание палитры",
    "awaiting_generation_engine": "ожидает выбор сети",
    "awaiting_generation_confirm": "ожидает подтверждение генерации изображений",
    "awaiting_generation_notes": "ожидает уточнение визуалов",
    "awaiting_final_confirm": "ожидает финальную сборку",
    "rendering": "собирается",
    "done": "готов",
    "cancelled": "отменён",
}


def _now() -> int:
    return int(time.time())


def _safe_json_loads(raw: str | None, default: Any) -> Any:
    try:
        value = json.loads(raw or "")
        return value
    except Exception:
        return default


def _clean_text(value: Any, limit: int = 4000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _safe_filename(value: str, ext: str) -> str:
    base = re.sub(r"[^A-Za-zА-Яа-яЁё0-9_-]+", "_", value or "project").strip("_")[:64] or "project"
    return f"{base}.{ext.lstrip('.')}"


def _hex(value: str) -> str:
    value = re.sub(r"[^0-9A-Fa-f]", "", value or "")[:6]
    return value.upper() if len(value) == 6 else "000000"


def _rgb(value: str) -> tuple[int, int, int]:
    value = _hex(value)
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))


def _contrast(hex_value: str) -> str:
    r, g, b = _rgb(hex_value)
    return "FFFFFF" if (0.299 * r + 0.587 * g + 0.114 * b) < 145 else "111111"


def _extract_json_object(text: str) -> JsonDict | None:
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    candidates = [cleaned]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        candidates.append(cleaned[start:end + 1])
    for candidate in candidates:
        with contextlib.suppress(Exception):
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
    return None


def _guess_title(brief: str, kind: str) -> str:
    brief = _clean_text(brief, 180)
    if not brief:
        return "Презентация" if kind == "presentation" else "Каталог"
    first = re.split(r"[.!?\n]", brief)[0].strip()
    return first[:70] or ("Презентация" if kind == "presentation" else "Каталог")


def _fallback_outline(brief: str, kind: str) -> JsonDict:
    title = _guess_title(brief, kind)
    if kind == "catalog":
        slides = [
            {"title": title, "bullets": ["Краткое позиционирование", "Ключевой визуал"], "visual_prompt": "hero product or service visual", "layout": "cover", "needs_image": True},
            {"title": "О компании", "bullets": ["Кто мы", "Для кого работаем", "Основные компетенции"], "visual_prompt": "brand lifestyle or team scene", "layout": "split", "needs_image": True},
            {"title": "Продукция / услуги", "bullets": ["Основные категории", "Ключевые особенности", "Варианты применения"], "visual_prompt": "clean commercial product collection", "layout": "cards", "needs_image": True},
            {"title": "Карточки предложений", "bullets": ["Название", "Характеристики", "Цена / условия"], "visual_prompt": "premium product card photography", "layout": "product", "needs_image": True},
            {"title": "Преимущества", "bullets": ["Качество", "Сервис", "Гарантии", "Сроки"], "visual_prompt": "abstract premium business visual", "layout": "benefits", "needs_image": False},
            {"title": "Как заказать", "bullets": ["Шаг 1 — заявка", "Шаг 2 — согласование", "Шаг 3 — результат"], "visual_prompt": "simple process visual", "layout": "process", "needs_image": False},
            {"title": "Контакты", "bullets": ["Телефон", "Мессенджер", "Адрес / сайт"], "visual_prompt": "brand background", "layout": "cta", "needs_image": True},
        ]
    else:
        slides = [
            {"title": title, "bullets": ["Главная идея", "Цель презентации"], "visual_prompt": "hero presentation image", "layout": "cover", "needs_image": True},
            {"title": "Контекст и задача", "bullets": ["Исходная ситуация", "Потребность аудитории", "Что предлагаем"], "visual_prompt": "business context visual", "layout": "split", "needs_image": True},
            {"title": "Решение", "bullets": ["Основной продукт / услуга", "Ключевая ценность", "Механика работы"], "visual_prompt": "solution concept visual", "layout": "cards", "needs_image": True},
            {"title": "Преимущества", "bullets": ["Преимущество 1", "Преимущество 2", "Преимущество 3"], "visual_prompt": "premium abstract benefit visual", "layout": "benefits", "needs_image": False},
            {"title": "Примеры / кейсы", "bullets": ["Пример 1", "Пример 2", "Результаты"], "visual_prompt": "case study visual", "layout": "gallery", "needs_image": True},
            {"title": "Условия", "bullets": ["Формат работы", "Сроки", "Стоимость / следующий шаг"], "visual_prompt": "clean commercial visual", "layout": "split", "needs_image": True},
            {"title": "Контакты", "bullets": ["Призыв к действию", "Телефон", "Мессенджер / сайт"], "visual_prompt": "brand CTA background", "layout": "cta", "needs_image": True},
        ]
    return {
        "title": title,
        "subtitle": "Коммерческий проект",
        "summary": _clean_text(brief, 500),
        "audience": "целевая аудитория проекта",
        "slides": slides,
    }


def _normalise_outline(data: JsonDict | None, brief: str, kind: str) -> JsonDict:
    base = _fallback_outline(brief, kind)
    if not isinstance(data, dict):
        return base
    title = _clean_text(data.get("title") or base["title"], 100)
    subtitle = _clean_text(data.get("subtitle") or base.get("subtitle"), 140)
    summary = _clean_text(data.get("summary") or brief, 800)
    audience = _clean_text(data.get("audience") or "", 300)
    slides_raw = data.get("slides")
    slides: list[JsonDict] = []
    if isinstance(slides_raw, list):
        for idx, item in enumerate(slides_raw[:18]):
            if not isinstance(item, dict):
                continue
            ttl = _clean_text(item.get("title") or f"Слайд {idx + 1}", 110)
            bullets_raw = item.get("bullets") or []
            if isinstance(bullets_raw, str):
                bullets_raw = [x.strip(" -•\t") for x in bullets_raw.splitlines() if x.strip()]
            bullets = [_clean_text(x, 240) for x in bullets_raw[:7] if _clean_text(x, 240)] if isinstance(bullets_raw, list) else []
            notes = _clean_text(item.get("notes") or item.get("speaker_notes") or "", 900)
            prompt = _clean_text(item.get("visual_prompt") or item.get("visual") or "", 650)
            layout = _clean_text(item.get("layout") or "split", 30).lower()
            needs_image = bool(item.get("needs_image", bool(prompt) or layout in {"cover", "split", "gallery", "product", "cta"}))
            slides.append({"title": ttl, "bullets": bullets, "notes": notes, "visual_prompt": prompt, "layout": layout, "needs_image": needs_image})
    if len(slides) < 2:
        slides = base["slides"]
    if slides[0].get("layout") != "cover":
        slides[0]["layout"] = "cover"
    if slides[-1].get("layout") not in {"cta", "contact"}:
        slides[-1]["layout"] = "cta"
    return {"title": title, "subtitle": subtitle, "summary": summary, "audience": audience, "slides": slides}


def _outline_prompt(brief: str, kind: str, existing: JsonDict | None = None, revision: str = "") -> str:
    kind_ru = "каталог продукции/услуг" if kind == "catalog" else "деловая презентация"
    current = json.dumps(existing, ensure_ascii=False) if existing else ""
    return (
        "Ты арт-директор, коммерческий редактор и архитектор презентаций. "
        f"Подготовь структуру проекта типа: {kind_ru}. Верни ТОЛЬКО валидный JSON без markdown. "
        "Схема JSON: {title, subtitle, summary, audience, slides:[{title, bullets:[...], notes, visual_prompt, layout, needs_image}]}. "
        "Слайдов 7-14, если пользователь не указал иначе. bullets: 2-6 кратких содержательных пунктов. "
        "layout только из cover, split, cards, product, benefits, process, gallery, quote, cta. "
        "visual_prompt должен описывать подходящее изображение без текста, водяных знаков и логотипов. "
        "Не выдумывай конкретные цены, телефоны, сертификаты и факты, которых нет в брифе; используй аккуратные плейсхолдеры. "
        f"Бриф пользователя:\n{brief}\n"
        + (f"Текущая структура:\n{current}\nЗапрошенные изменения:\n{revision}\n" if existing else "")
    )


def _logo_prompt_variants(brief: str, brand: str) -> list[str]:
    core = _clean_text(brief, 800)
    brand_hint = _clean_text(brand, 80)
    return [
        f"Design a premium vector logo symbol only for brand {brand_hint}. No letters, no words, no mockup, no watermark, clean geometric emblem, timeless luxury, balanced negative space. Brief: {core}",
        f"Design a modern minimal logo mark only for brand {brand_hint}. No text, no letters, abstract monogram-inspired geometry, scalable vector identity, distinctive silhouette, professional. Brief: {core}",
        f"Design an elegant heraldic yet contemporary logo icon only for brand {brand_hint}. No text, no words, refined symmetry, premium identity, simple vector lines, suitable for presentation cover. Brief: {core}",
    ]


def _image_prompts(outline: JsonDict, style_label: str, palette: JsonDict, notes: str, count: int) -> list[tuple[int, str]]:
    slides = outline.get("slides") or []
    visual_candidates: list[tuple[int, str]] = []
    for idx, slide in enumerate(slides):
        if not isinstance(slide, dict) or not slide.get("needs_image"):
            continue
        vp = _clean_text(slide.get("visual_prompt") or slide.get("title"), 600)
        prompt = (
            f"{vp}. Designed for a professional 16:9 business presentation. Style: {style_label}. "
            f"Color direction: accent #{palette.get('accent')}, background #{palette.get('bg')}. "
            "High-end editorial composition, useful negative space for layout, photorealistic or premium illustrative quality as appropriate. "
            "No readable text, no logos, no watermarks, no UI, no mockup frame. "
            f"Additional user direction: {notes or 'none'}"
        )
        visual_candidates.append((idx, prompt))
    return visual_candidates[:max(0, count)]


@dataclass
class StudioConfig:
    db_path: str
    data_dir: str
    max_uploads: int = 60
    max_generated_images: int = 8
    render_cost_usd: float = 0.20


class PresentationStudio:
    def __init__(self, config: StudioConfig, llm_call: LLMCall, image_batch_call: ImageBatchCall, paid_runner: PaidRunner):
        self.cfg = config
        self.llm_call = llm_call
        self.image_batch_call = image_batch_call
        self.paid_runner = paid_runner
        self.data_dir = self._ensure_data_dir(config.data_dir)
        self._init_db()

    def _ensure_data_dir(self, requested: str) -> Path:
        candidates = [Path(requested), Path("/tmp/presentation_studio")]
        for path in candidates:
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe = path / ".write_test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
                return path
            except Exception:
                continue
        raise RuntimeError("No writable directory for presentation studio")

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.cfg.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        con = self._connect(); cur = con.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS presentation_projects (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            state TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            title TEXT,
            brief TEXT,
            outline_json TEXT,
            style_key TEXT,
            style_notes TEXT,
            palette_key TEXT,
            palette_json TEXT,
            asset_mode TEXT,
            generation_engine TEXT,
            generation_notes TEXT,
            logo_asset_id INTEGER,
            created_ts INTEGER NOT NULL,
            updated_ts INTEGER NOT NULL
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS presentation_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            source TEXT NOT NULL,
            file_path TEXT NOT NULL,
            mime TEXT,
            label TEXT,
            slide_index INTEGER,
            selected INTEGER NOT NULL DEFAULT 1,
            prompt TEXT,
            created_ts INTEGER NOT NULL,
            FOREIGN KEY(project_id) REFERENCES presentation_projects(id)
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ps_projects_user ON presentation_projects(user_id, chat_id, status, updated_ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ps_assets_project ON presentation_assets(project_id, kind, selected, id)")
        con.commit(); con.close()

    def _project_dir(self, project_id: str) -> Path:
        path = self.data_dir / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _fetch_project(self, project_id: str) -> JsonDict | None:
        con = self._connect(); cur = con.cursor()
        cur.execute("SELECT * FROM presentation_projects WHERE id=?", (project_id,))
        row = cur.fetchone(); con.close()
        return dict(row) if row else None

    def _active_project(self, user_id: int, chat_id: int) -> JsonDict | None:
        con = self._connect(); cur = con.cursor()
        cur.execute("SELECT * FROM presentation_projects WHERE user_id=? AND chat_id=? AND status='active' ORDER BY updated_ts DESC LIMIT 1", (user_id, chat_id))
        row = cur.fetchone(); con.close()
        return dict(row) if row else None

    def _update_project(self, project_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_ts"] = _now()
        allowed = {"state", "status", "title", "brief", "outline_json", "style_key", "style_notes", "palette_key", "palette_json", "asset_mode", "generation_engine", "generation_notes", "logo_asset_id", "updated_ts"}
        items = [(k, v) for k, v in fields.items() if k in allowed]
        if not items:
            return
        sql = "UPDATE presentation_projects SET " + ", ".join(f"{k}=?" for k, _ in items) + " WHERE id=?"
        con = self._connect(); cur = con.cursor(); cur.execute(sql, [v for _, v in items] + [project_id]); con.commit(); con.close()

    def _create_project(self, user_id: int, chat_id: int, kind: str) -> JsonDict:
        project_id = uuid.uuid4().hex[:12]
        now = _now()
        con = self._connect(); cur = con.cursor()
        cur.execute("UPDATE presentation_projects SET status='cancelled', state='cancelled', updated_ts=? WHERE user_id=? AND chat_id=? AND status='active'", (now, user_id, chat_id))
        cur.execute("""
        INSERT INTO presentation_projects(id,user_id,chat_id,kind,state,status,created_ts,updated_ts)
        VALUES(?,?,?,?,?,'active',?,?)
        """, (project_id, user_id, chat_id, kind, "awaiting_brief", now, now))
        con.commit(); con.close(); self._project_dir(project_id)
        return self._fetch_project(project_id) or {}

    def _assets(self, project_id: str, kinds: Iterable[str] | None = None, selected_only: bool = True) -> list[JsonDict]:
        con = self._connect(); cur = con.cursor()
        sql = "SELECT * FROM presentation_assets WHERE project_id=?"
        params: list[Any] = [project_id]
        if kinds:
            ks = list(kinds)
            sql += f" AND kind IN ({','.join('?' for _ in ks)})"
            params.extend(ks)
        if selected_only:
            sql += " AND selected=1"
        sql += " ORDER BY COALESCE(slide_index,9999), id"
        cur.execute(sql, params); rows = [dict(r) for r in cur.fetchall()]; con.close(); return rows

    def _count_assets(self, project_id: str, kinds: Iterable[str] | None = None) -> int:
        return len(self._assets(project_id, kinds=kinds))

    def _add_asset(self, project_id: str, raw: bytes, kind: str, source: str, mime: str = "image/jpeg", label: str = "", slide_index: int | None = None, prompt: str = "") -> int:
        if not raw:
            raise ValueError("empty asset")
        ext = "png" if "png" in (mime or "").lower() else "jpg"
        file_name = f"{kind}_{uuid.uuid4().hex[:10]}.{ext}"
        path = self._project_dir(project_id) / file_name
        try:
            im = Image.open(io.BytesIO(raw))
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            max_side = 2400
            if max(im.size) > max_side:
                im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            save_format = "PNG" if ext == "png" else "JPEG"
            kwargs = {"optimize": True}
            if save_format == "JPEG":
                if im.mode != "RGB": im = im.convert("RGB")
                kwargs["quality"] = 92
            im.save(path, format=save_format, **kwargs)
        except Exception:
            path.write_bytes(raw)
        con = self._connect(); cur = con.cursor()
        cur.execute("""
        INSERT INTO presentation_assets(project_id,kind,source,file_path,mime,label,slide_index,selected,prompt,created_ts)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """, (project_id, kind, source, str(path), mime, _clean_text(label, 200), slide_index, 1, _clean_text(prompt, 1000), _now()))
        asset_id = int(cur.lastrowid); con.commit(); con.close(); return asset_id

    def _clear_assets(self, project_id: str, kinds: Iterable[str]) -> int:
        assets = self._assets(project_id, kinds=kinds, selected_only=False)
        ids = [a["id"] for a in assets]
        for asset in assets:
            with contextlib.suppress(Exception): Path(asset["file_path"]).unlink(missing_ok=True)
        if ids:
            con = self._connect(); cur = con.cursor(); cur.execute(f"DELETE FROM presentation_assets WHERE id IN ({','.join('?' for _ in ids)})", ids); con.commit(); con.close()
        return len(ids)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str) -> bool:
        kind = "catalog" if kind == "catalog" else "presentation"
        user_id, chat_id = update.effective_user.id, update.effective_chat.id
        current = self._active_project(user_id, chat_id)
        if current:
            await update.effective_message.reply_text(
                f"У вас уже есть незавершённый проект «{current.get('title') or 'Без названия'}» — {STATE_LABELS.get(current.get('state'), current.get('state'))}.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ Продолжить", callback_data=f"ps:resume:{current['id']}")],
                    [InlineKeyboardButton("🆕 Начать новый", callback_data=f"ps:new:{kind}")],
                    [InlineKeyboardButton("❌ Отменить текущий", callback_data=f"ps:cancel:{current['id']}")],
                ]),
            )
            return True
        project = self._create_project(user_id, chat_id, kind)
        context.user_data["presentation_studio_active"] = project["id"]
        await self._ask_brief(update, project)
        return True

    async def _ask_brief(self, update: Update, project: JsonDict) -> None:
        noun = "каталог" if project.get("kind") == "catalog" else "презентацию"
        await update.effective_message.reply_text(
            f"🧩 Создаём {noun} как полноценный дизайнерский проект с итоговыми PDF и PPTX.\n\n"
            "Пришлите текстом или голосом:\n"
            "• тему и цель;\n• продукт, услугу или компанию;\n• целевую аудиторию;\n"
            "• желаемое количество слайдов/страниц;\n• цены, характеристики и контакты;\n"
            "• желаемый стиль, если он уже есть.\n\n"
            "Можно дать все данные одним сообщением. Недостающие детали я аккуратно оформлю как места для заполнения."
        )

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
        project = self._active_project(update.effective_user.id, update.effective_chat.id)
        if not project:
            return False
        if context.user_data.get("presentation_studio_active") != project.get("id"):
            return False
        state = project.get("state")
        text = (text or "").strip()
        if not text:
            return True

        if state == "awaiting_brief":
            await update.effective_message.reply_text("🧠 Анализирую бриф и проектирую структуру…")
            raw = await self.llm_call(update, _outline_prompt(text, project["kind"]))
            outline = _normalise_outline(_extract_json_object(raw), text, project["kind"])
            self._update_project(project["id"], brief=text, title=outline.get("title"), outline_json=json.dumps(outline, ensure_ascii=False), state="awaiting_outline_confirmation")
            await self._send_outline(update, project["id"])
            return True

        if state == "awaiting_outline_revision":
            outline = _safe_json_loads(project.get("outline_json"), _fallback_outline(project.get("brief") or "", project["kind"]))
            await update.effective_message.reply_text("✏️ Вношу правки в структуру…")
            raw = await self.llm_call(update, _outline_prompt(project.get("brief") or "", project["kind"], existing=outline, revision=text))
            revised = _normalise_outline(_extract_json_object(raw), project.get("brief") or "", project["kind"])
            self._update_project(project["id"], outline_json=json.dumps(revised, ensure_ascii=False), title=revised.get("title"), state="awaiting_outline_confirmation")
            await self._send_outline(update, project["id"])
            return True

        if state == "awaiting_logo_brief":
            await self._generate_logo_variants(update, context, project, text)
            return True

        if state == "awaiting_custom_style":
            self._update_project(project["id"], style_key="custom", style_notes=text, state="awaiting_palette")
            await self._ask_palette(update, self._fetch_project(project["id"]) or project)
            return True

        if state == "awaiting_custom_palette":
            palette = await self._palette_from_text(update, text)
            self._update_project(project["id"], palette_key="custom", palette_json=json.dumps(palette, ensure_ascii=False), state="awaiting_palette")
            await self._after_palette(update, context, self._fetch_project(project["id"]) or project)
            return True

        if state == "awaiting_generation_notes":
            self._update_project(project["id"], generation_notes=text, state="awaiting_generation_engine")
            await self._ask_generation_engine(update, self._fetch_project(project["id"]) or project)
            return True

        # During asset upload, captions are stored as labels/notes by the photo handler.
        if state == "uploading_assets":
            self._update_project(project["id"], generation_notes=_clean_text((project.get("generation_notes") or "") + " " + text, 1200))
            await update.effective_message.reply_text("📝 Уточнение к проекту сохранено. Продолжайте загружать фото или нажмите «Завершить загрузку».", reply_markup=self._upload_kb())
            return True

        return False

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE, raw: bytes, mime: str = "image/jpeg", caption: str = "") -> bool:
        project = self._active_project(update.effective_user.id, update.effective_chat.id)
        if not project:
            return False
        if context.user_data.get("presentation_studio_active") != project.get("id"):
            return False
        state = project.get("state")
        if state == "awaiting_logo_upload":
            self._clear_assets(project["id"], ["logo", "logo_variant"])
            asset_id = self._add_asset(project["id"], raw, "logo", "uploaded", mime=mime, label=caption or "Логотип компании")
            self._update_project(project["id"], logo_asset_id=asset_id, state="awaiting_asset_source")
            await update.effective_message.reply_text("✅ Логотип загружен и будет размещён на обложке и ключевых слайдах.", reply_markup=self._asset_source_kb())
            return True
        if state == "uploading_assets":
            current = self._count_assets(project["id"], ["photo", "generated"])
            if current >= self.cfg.max_uploads:
                await update.effective_message.reply_text(f"Достигнут лимит проекта: {self.cfg.max_uploads} изображений.", reply_markup=self._upload_kb())
                return True
            self._add_asset(project["id"], raw, "photo", "uploaded", mime=mime, label=caption)
            total = current + 1
            group_id = getattr(update.effective_message, "media_group_id", None)
            last_group = context.user_data.get("ps_media_group")
            if not group_id or group_id != last_group or total % 5 == 0:
                context.user_data["ps_media_group"] = group_id
                await update.effective_message.reply_text(f"📥 Принято изображений: {total}. Можно отправлять дальше одним альбомом или по одному.", reply_markup=self._upload_kb())
            return True
        return False

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE, raw: bytes, filename: str, mime: str, caption: str = "") -> bool:
        project = self._active_project(update.effective_user.id, update.effective_chat.id)
        if not project:
            return False
        if context.user_data.get("presentation_studio_active") != project.get("id"):
            return False
        state = project.get("state")
        low_name = (filename or "").lower()
        if state in {"awaiting_logo_upload", "uploading_assets"} and (mime.startswith("image/") or low_name.endswith((".png", ".jpg", ".jpeg", ".webp"))):
            return await self.handle_photo(update, context, raw, mime=mime or "image/jpeg", caption=caption)
        if state == "uploading_assets" and low_name.endswith(".zip"):
            count = await asyncio.to_thread(self._extract_zip_assets, project["id"], raw)
            total = self._count_assets(project["id"], ["photo", "generated"])
            await update.effective_message.reply_text(f"📦 Из ZIP добавлено изображений: {count}. Всего в проекте: {total}.", reply_markup=self._upload_kb())
            return True
        return False

    def _extract_zip_assets(self, project_id: str, raw: bytes) -> int:
        added = 0
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for info in zf.infolist():
                    if added >= self.cfg.max_uploads:
                        break
                    if info.is_dir() or info.file_size > 20 * 1024 * 1024:
                        continue
                    ext = Path(info.filename).suffix.lower()
                    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
                        continue
                    blob = zf.read(info)
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    with contextlib.suppress(Exception):
                        self._add_asset(project_id, blob, "photo", "zip", mime=mime, label=Path(info.filename).stem)
                        added += 1
        except Exception as e:
            log.warning("ZIP asset import failed: %s", e)
        return added

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        q = update.callback_query
        data = (q.data or "").strip()
        if not data.startswith("ps:"):
            return False
        await q.answer()
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        user_id, chat_id = q.from_user.id, q.message.chat_id

        if action == "new":
            kind = parts[2] if len(parts) > 2 else "presentation"
            project = self._create_project(user_id, chat_id, kind)
            context.user_data["presentation_studio_active"] = project["id"]
            await self._ask_brief(update, project)
            return True
        if action == "resume":
            project = self._fetch_project(parts[2] if len(parts) > 2 else "")
            if not project or project.get("user_id") != user_id:
                await q.message.reply_text("Проект не найден.")
                return True
            context.user_data["presentation_studio_active"] = project["id"]
            await self._resume_prompt(update, project)
            return True
        if action == "cancel":
            pid = parts[2] if len(parts) > 2 else ""
            project = self._fetch_project(pid)
            if project and project.get("user_id") == user_id:
                self._update_project(pid, status="cancelled", state="cancelled")
                context.user_data.pop("presentation_studio_active", None)
                await q.message.reply_text("Проект отменён. Загруженные файлы сохранены до очистки сервера.")
            return True

        project = self._active_project(user_id, chat_id)
        if not project:
            await q.message.reply_text("Активный проект не найден. Откройте «Работа/Бизнес → Создать презентацию».")
            return True

        pid = project["id"]
        context.user_data["presentation_studio_active"] = pid
        if action == "outline_ok":
            self._update_project(pid, state="awaiting_logo_choice")
            await q.message.reply_text("✅ Структура утверждена. Теперь определимся с логотипом компании.", reply_markup=self._logo_choice_kb())
            return True
        if action == "outline_edit":
            self._update_project(pid, state="awaiting_outline_revision")
            await q.message.reply_text("Опишите, что изменить: добавить/убрать разделы, поменять порядок, число слайдов, акценты или тексты.")
            return True
        if action == "logo_upload":
            self._update_project(pid, state="awaiting_logo_upload")
            await q.message.reply_text("📤 Пришлите логотип как PNG/JPG. Лучше использовать PNG с прозрачным фоном.")
            return True
        if action == "logo_generate":
            self._update_project(pid, state="awaiting_logo_brief")
            await q.message.reply_text(
                "🎨 Опишите логотип текстом или голосом: название компании, сфера, характер бренда, символы, цвета, слоган и где он будет использоваться.\n\n"
                "Я создам 3 разных варианта, после чего вы выберете один."
            )
            return True
        if action == "logo_skip":
            self._update_project(pid, logo_asset_id=None, state="awaiting_asset_source")
            await q.message.reply_text("Продолжаем без логотипа. Теперь выберите, откуда взять изображения.", reply_markup=self._asset_source_kb())
            return True
        if action == "logo_select":
            try: asset_id = int(parts[2])
            except Exception: asset_id = 0
            assets = self._assets(pid, ["logo_variant"], selected_only=False)
            if not any(a["id"] == asset_id for a in assets):
                await q.message.reply_text("Вариант логотипа не найден.")
                return True
            con = self._connect(); cur = con.cursor(); cur.execute("UPDATE presentation_assets SET selected=CASE WHEN id=? THEN 1 ELSE 0 END WHERE project_id=? AND kind='logo_variant'", (asset_id, pid)); con.commit(); con.close()
            self._update_project(pid, logo_asset_id=asset_id, state="awaiting_asset_source")
            await q.message.reply_text("✅ Логотип утверждён. Теперь выберите способ работы с изображениями.", reply_markup=self._asset_source_kb())
            return True
        if action == "asset_upload":
            self._update_project(pid, asset_mode="upload", state="uploading_assets")
            await q.message.reply_text("📤 Отправляйте фотографии по одной, альбомом или ZIP-архивом. Подписи к фото сохраняются как подсказки для размещения.", reply_markup=self._upload_kb())
            return True
        if action == "asset_mixed":
            self._update_project(pid, asset_mode="mixed", state="uploading_assets")
            await q.message.reply_text("📦 Смешанный режим: сначала загрузите свои фото, затем я предложу создать недостающие визуалы.", reply_markup=self._upload_kb())
            return True
        if action == "asset_generate":
            self._update_project(pid, asset_mode="generate", state="awaiting_style")
            await q.message.reply_text("✨ Изображения будут созданы по структуре. Сначала выберите дизайнерский стиль.", reply_markup=self._style_kb())
            return True
        if action == "asset_none":
            self._update_project(pid, asset_mode="none", state="awaiting_style")
            await q.message.reply_text("Продолжаем без фотографий. Дизайн будет построен на типографике, цвете и графических блоках.", reply_markup=self._style_kb())
            return True
        if action == "upload_done":
            total = self._count_assets(pid, ["photo", "generated"])
            if total == 0 and project.get("asset_mode") == "upload":
                await q.message.reply_text("Пока не загружено ни одного изображения. Выберите генерацию или продолжение без изображений.", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✨ Сгенерировать изображения", callback_data="ps:asset_generate")],
                    [InlineKeyboardButton("⏭ Без изображений", callback_data="ps:asset_none")],
                ]))
                return True
            self._update_project(pid, state="awaiting_style")
            await q.message.reply_text(f"✅ Загрузка завершена. В проекте изображений: {total}. Теперь выберите стиль.", reply_markup=self._style_kb())
            return True
        if action == "upload_clear":
            removed = self._clear_assets(pid, ["photo", "generated"])
            await q.message.reply_text(f"🗑 Удалено изображений: {removed}.", reply_markup=self._upload_kb())
            return True
        if action == "style":
            key = parts[2] if len(parts) > 2 else "minimal"
            if key == "custom":
                self._update_project(pid, state="awaiting_custom_style")
                await q.message.reply_text("Опишите свой стиль: настроение, референсы, композицию, типографику и уровень строгости.")
                return True
            if key not in STYLE_PRESETS: key = "minimal"
            self._update_project(pid, style_key=key, style_notes="", state="awaiting_palette")
            await self._ask_palette(update, self._fetch_project(pid) or project)
            return True
        if action == "palette":
            key = parts[2] if len(parts) > 2 else "white_minimal"
            if key == "custom":
                self._update_project(pid, state="awaiting_custom_palette")
                await q.message.reply_text("Укажите фирменные цвета текстом или HEX-кодами. Например: тёмно-синий #0B1F3A, золото #D4AF37, белый.")
                return True
            if key not in PALETTE_PRESETS: key = "white_minimal"
            self._update_project(pid, palette_key=key, palette_json=json.dumps(PALETTE_PRESETS[key], ensure_ascii=False), state="awaiting_palette")
            await self._after_palette(update, context, self._fetch_project(pid) or project)
            return True
        if action == "gen_engine":
            engine = parts[2] if len(parts) > 2 else "auto"
            if engine not in {"auto", "midjourney", "openai"}: engine = "auto"
            self._update_project(pid, generation_engine=engine, state="awaiting_generation_confirm")
            await self._send_generation_plan(update, self._fetch_project(pid) or project)
            return True
        if action == "gen_notes":
            self._update_project(pid, state="awaiting_generation_notes")
            await q.message.reply_text("Опишите дополнительные требования к изображениям: ракурс, атмосфера, локация, люди/без людей, предметы, стиль съёмки.")
            return True
        if action == "gen_confirm":
            await self._generate_project_images(update, context, self._fetch_project(pid) or project)
            return True
        if action == "gen_skip":
            self._update_project(pid, state="awaiting_final_confirm")
            await self._send_final_summary(update, self._fetch_project(pid) or project)
            return True
        if action == "final_edit":
            self._update_project(pid, state="awaiting_outline_revision")
            await q.message.reply_text("Опишите финальные правки к структуре и тексту. После обновления проект снова пройдёт этап утверждения.")
            return True
        if action == "final_render":
            await self._render_and_send(update, context, self._fetch_project(pid) or project)
            return True
        return True

    async def _resume_prompt(self, update: Update, project: JsonDict) -> None:
        state = project.get("state")
        if state == "awaiting_brief":
            await self._ask_brief(update, project)
        elif state == "awaiting_outline_confirmation":
            await self._send_outline(update, project["id"])
        elif state == "awaiting_outline_revision":
            await update.effective_message.reply_text("Опишите изменения структуры.")
        elif state == "awaiting_logo_choice":
            await update.effective_message.reply_text("Выберите действие с логотипом.", reply_markup=self._logo_choice_kb())
        elif state == "awaiting_logo_upload":
            await update.effective_message.reply_text("Пришлите логотип PNG/JPG.")
        elif state == "awaiting_logo_brief":
            await update.effective_message.reply_text("Опишите логотип — я создам 3 варианта.")
        elif state == "awaiting_asset_source":
            await update.effective_message.reply_text("Выберите способ работы с изображениями.", reply_markup=self._asset_source_kb())
        elif state == "uploading_assets":
            await update.effective_message.reply_text(f"Продолжайте загрузку. Сейчас изображений: {self._count_assets(project['id'], ['photo', 'generated'])}.", reply_markup=self._upload_kb())
        elif state in {"awaiting_style", "awaiting_custom_style"}:
            await update.effective_message.reply_text("Выберите стиль проекта.", reply_markup=self._style_kb())
        elif state in {"awaiting_palette", "awaiting_custom_palette"}:
            await self._ask_palette(update, project)
        elif state in {"awaiting_generation_engine", "awaiting_generation_notes"}:
            await self._ask_generation_engine(update, project)
        elif state == "awaiting_generation_confirm":
            await self._send_generation_plan(update, project)
        elif state == "awaiting_final_confirm":
            await self._send_final_summary(update, project)
        elif state == "rendering":
            await update.effective_message.reply_text("Проект был в процессе сборки. Нажмите повторно «Собрать PDF + PPTX».", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Собрать PDF + PPTX", callback_data="ps:final_render")]]))
        else:
            await update.effective_message.reply_text("Проект завершён или отменён.")

    async def _send_outline(self, update: Update, project_id: str) -> None:
        project = self._fetch_project(project_id) or {}
        outline = _safe_json_loads(project.get("outline_json"), {})
        slides = outline.get("slides") or []
        lines = [f"📐 Проект структуры: {outline.get('title') or project.get('title') or 'Без названия'}"]
        if outline.get("subtitle"): lines.append(str(outline["subtitle"]))
        lines.append("")
        for idx, slide in enumerate(slides, start=1):
            bullets = slide.get("bullets") or []
            short = "; ".join(str(x) for x in bullets[:3])
            lines.append(f"{idx}. {slide.get('title') or f'Слайд {idx}'}" + (f" — {short}" if short else ""))
        lines.append("\nПосле утверждения я уточню логотип, фотографии, стиль и палитру, затем соберу готовые PDF и PPTX.")
        await update.effective_message.reply_text("\n".join(lines)[:3900], reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Утвердить структуру", callback_data="ps:outline_ok")],
            [InlineKeyboardButton("✏️ Изменить структуру", callback_data="ps:outline_edit")],
            [InlineKeyboardButton("❌ Отменить проект", callback_data=f"ps:cancel:{project_id}")],
        ]))

    async def _generate_logo_variants(self, update: Update, context: ContextTypes.DEFAULT_TYPE, project: JsonDict, logo_brief: str) -> None:
        outline = _safe_json_loads(project.get("outline_json"), {})
        brand = _clean_text(outline.get("title") or project.get("title") or "Brand", 80)
        prompts = _logo_prompt_variants(logo_brief, brand)
        await update.effective_message.reply_text("🎨 Создаю 3 варианта логотипа. Это может занять несколько минут…")
        images = await self.image_batch_call(update, context, prompts, "openai", "presentation_logo_variants")
        if not images:
            self._update_project(project["id"], state="awaiting_logo_brief")
            await update.effective_message.reply_text(
                "Логотипы не были созданы: генерация не завершилась или не хватило кредитов. "
                "Можно повторить бриф, загрузить свой логотип или продолжить без него.",
                reply_markup=self._logo_choice_kb(),
            )
            return
        while len(images) < 3:
            images.append(self._make_local_logo_variant(brand, logo_brief, len(images)))
        self._clear_assets(project["id"], ["logo", "logo_variant"])
        ids: list[int] = []
        for idx, raw in enumerate(images[:3]):
            normalized = self._normalise_logo(raw, brand, idx)
            ids.append(self._add_asset(project["id"], normalized, "logo_variant", "generated", mime="image/png", label=f"Вариант {idx + 1}", prompt=prompts[idx]))
        self._update_project(project["id"], state="awaiting_logo_selection")
        for idx, asset_id in enumerate(ids):
            asset = next(a for a in self._assets(project["id"], ["logo_variant"], selected_only=False) if a["id"] == asset_id)
            with open(asset["file_path"], "rb") as fh:
                bio = io.BytesIO(fh.read()); bio.name = f"logo_variant_{idx + 1}.png"
            await update.effective_message.reply_photo(photo=InputFile(bio), caption=f"Вариант {idx + 1}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Выбрать вариант {idx + 1}", callback_data=f"ps:logo_select:{asset_id}")]]))
        await update.effective_message.reply_text("Выберите один вариант выше или загрузите свой логотип.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📤 Загрузить другой логотип", callback_data="ps:logo_upload")],[InlineKeyboardButton("⏭ Без логотипа", callback_data="ps:logo_skip")]]))

    def _font_path(self, bold: bool = False) -> str | None:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        ]
        return next((p for p in candidates if os.path.exists(p)), None)

    def _load_font(self, size: int, bold: bool = False) -> ImageFont.ImageFont:
        path = self._font_path(bold)
        if path:
            with contextlib.suppress(Exception): return ImageFont.truetype(path, size)
        return ImageFont.load_default()

    def _make_local_logo_variant(self, brand: str, brief: str, variant: int) -> bytes:
        W = H = 1024
        palettes = [((14, 18, 25), (212, 178, 94), (248, 245, 235)), ((240, 245, 252), (43, 103, 246), (20, 30, 48)), ((22, 45, 38), (183, 151, 91), (244, 239, 224))]
        bg, accent, text = palettes[variant % len(palettes)]
        img = Image.new("RGB", (W, H), bg); d = ImageDraw.Draw(img)
        initials = "".join(w[0] for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", brand)[:3]).upper() or "B"
        if variant == 0:
            d.ellipse((250, 150, 774, 674), outline=accent, width=18)
            d.ellipse((330, 230, 694, 594), outline=accent, width=5)
        elif variant == 1:
            d.rounded_rectangle((235, 145, 789, 699), radius=120, outline=accent, width=20)
            d.polygon([(512, 220), (690, 512), (512, 640), (334, 512)], outline=accent)
        else:
            d.polygon([(512, 140), (790, 300), (730, 650), (512, 760), (294, 650), (234, 300)], outline=accent)
            d.line((350, 520, 674, 520), fill=accent, width=12)
        f_big = self._load_font(180, True); f_brand = self._load_font(58, True); f_small = self._load_font(28, False)
        box = d.textbbox((0, 0), initials, font=f_big); d.text(((W-(box[2]-box[0]))/2, 350-(box[3]-box[1])/2), initials, font=f_big, fill=text)
        clean_brand = brand[:30]
        box = d.textbbox((0, 0), clean_brand, font=f_brand); d.text(((W-(box[2]-box[0]))/2, 795), clean_brand, font=f_brand, fill=text)
        tagline = "PREMIUM BRAND IDENTITY" if variant != 1 else "MODERN BRAND SYSTEM"
        box = d.textbbox((0, 0), tagline, font=f_small); d.text(((W-(box[2]-box[0]))/2, 875), tagline, font=f_small, fill=accent)
        out = io.BytesIO(); img.save(out, format="PNG", optimize=True); return out.getvalue()

    def _normalise_logo(self, raw: bytes, brand: str, variant: int) -> bytes:
        try:
            mark = Image.open(io.BytesIO(raw)).convert("RGB")
            mark = ImageOps.fit(mark, (1024, 760), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (1024, 1024), (248, 248, 248))
            canvas.paste(mark, (0, 0))
            d = ImageDraw.Draw(canvas)
            d.rectangle((0, 760, 1024, 1024), fill=(248, 248, 248))
            f = self._load_font(58, True); small = self._load_font(24, False)
            clean = brand[:32]
            box = d.textbbox((0, 0), clean, font=f); d.text(((1024-(box[2]-box[0]))/2, 805), clean, font=f, fill=(18, 22, 29))
            label = f"LOGO CONCEPT {variant + 1}"
            box = d.textbbox((0, 0), label, font=small); d.text(((1024-(box[2]-box[0]))/2, 905), label, font=small, fill=(90, 96, 108))
            out = io.BytesIO(); canvas.save(out, format="PNG", optimize=True); return out.getvalue()
        except Exception:
            return raw

    async def _palette_from_text(self, update: Update, text: str) -> JsonDict:
        prompt = (
            "Верни только JSON палитры по описанию пользователя: {bg,surface,text,muted,accent,accent2,label}. "
            "Все цвета только HEX без #, ровно 6 символов. Обеспечь хороший контраст текста. Описание: " + text
        )
        raw = await self.llm_call(update, prompt)
        data = _extract_json_object(raw) or {}
        fallback = dict(PALETTE_PRESETS["white_blue"])
        for key in ("bg", "surface", "text", "muted", "accent", "accent2"):
            fallback[key] = _hex(str(data.get(key) or fallback[key]))
        fallback["label"] = _clean_text(data.get("label") or "Пользовательская палитра", 80)
        return fallback

    async def _ask_palette(self, update: Update, project: JsonDict) -> None:
        style_key = project.get("style_key") or "minimal"
        preferred = STYLE_PRESETS.get(style_key, {}).get("default_palette")
        rows: list[list[InlineKeyboardButton]] = []
        if preferred and preferred in PALETTE_PRESETS:
            rows.append([InlineKeyboardButton("⭐ " + PALETTE_PRESETS[preferred]["label"], callback_data=f"ps:palette:{preferred}")])
        for key in ["black_gold", "blue_gray", "white_minimal", "white_blue", "sand_green", "navy_cyan"]:
            if key == preferred: continue
            rows.append([InlineKeyboardButton(PALETTE_PRESETS[key]["label"], callback_data=f"ps:palette:{key}")])
        rows.append([InlineKeyboardButton("🎨 Свои фирменные цвета", callback_data="ps:palette:custom")])
        await update.effective_message.reply_text("🎨 Выберите цветовую палитру. Первый вариант рекомендован для выбранного стиля.", reply_markup=InlineKeyboardMarkup(rows))

    async def _after_palette(self, update: Update, context: ContextTypes.DEFAULT_TYPE, project: JsonDict) -> None:
        asset_mode = project.get("asset_mode") or "none"
        if asset_mode in {"generate", "mixed"}:
            self._update_project(project["id"], state="awaiting_generation_engine")
            await self._ask_generation_engine(update, self._fetch_project(project["id"]) or project)
        else:
            self._update_project(project["id"], state="awaiting_final_confirm")
            await self._send_final_summary(update, self._fetch_project(project["id"]) or project)

    async def _ask_generation_engine(self, update: Update, project: JsonDict) -> None:
        await update.effective_message.reply_text(
            "🖼 Выберите сеть для недостающих визуалов.\n\n"
            "• Авто — Midjourney для атмосферных/luxury сцен, OpenAI/Comet для точных продуктовых изображений.\n"
            "• Midjourney — художественные и премиальные визуалы.\n"
            "• OpenAI/Comet Images — более точное следование ТЗ.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✨ Автоматический выбор", callback_data="ps:gen_engine:auto")],
                [InlineKeyboardButton("🎨 Midjourney", callback_data="ps:gen_engine:midjourney")],
                [InlineKeyboardButton("🖼 OpenAI / Comet Images", callback_data="ps:gen_engine:openai")],
                [InlineKeyboardButton("✏️ Добавить требования к визуалам", callback_data="ps:gen_notes")],
                [InlineKeyboardButton("⏭ Не генерировать", callback_data="ps:gen_skip")],
            ])
        )

    def _generation_plan(self, project: JsonDict) -> list[tuple[int, str]]:
        outline = _safe_json_loads(project.get("outline_json"), {})
        style_key = project.get("style_key") or "minimal"
        style_label = STYLE_PRESETS.get(style_key, {}).get("label") or project.get("style_notes") or style_key
        palette = _safe_json_loads(project.get("palette_json"), PALETTE_PRESETS.get(project.get("palette_key") or "white_minimal"))
        uploaded = self._count_assets(project["id"], ["photo", "generated"])
        visual_slots = sum(1 for s in outline.get("slides", []) if isinstance(s, dict) and s.get("needs_image"))
        missing = max(0, min(self.cfg.max_generated_images, visual_slots - uploaded))
        if project.get("asset_mode") == "generate":
            missing = min(self.cfg.max_generated_images, max(1, visual_slots))
        return _image_prompts(outline, style_label, palette, project.get("generation_notes") or "", missing)

    async def _send_generation_plan(self, update: Update, project: JsonDict) -> None:
        plan = self._generation_plan(project)
        if not plan:
            self._update_project(project["id"], state="awaiting_final_confirm")
            await update.effective_message.reply_text("Собственных изображений достаточно для структуры — дополнительная генерация не требуется.")
            await self._send_final_summary(update, self._fetch_project(project["id"]) or project)
            return
        outline = _safe_json_loads(project.get("outline_json"), {})
        slides = outline.get("slides") or []
        lines = [f"✨ План генерации: {len(plan)} изображений"]
        for idx, (slide_idx, _) in enumerate(plan, 1):
            title = slides[slide_idx].get("title") if slide_idx < len(slides) else f"Слайд {slide_idx + 1}"
            lines.append(f"{idx}. Для слайда «{title}»")
        engine = project.get("generation_engine") or "auto"
        lines.append(f"\nСеть: {engine}. Изображения будут без текста, водяных знаков и чужих логотипов.")
        await update.effective_message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Создать изображения", callback_data="ps:gen_confirm")],
            [InlineKeyboardButton("✏️ Уточнить визуалы", callback_data="ps:gen_notes")],
            [InlineKeyboardButton("⏭ Пропустить", callback_data="ps:gen_skip")],
        ]))

    async def _generate_project_images(self, update: Update, context: ContextTypes.DEFAULT_TYPE, project: JsonDict) -> None:
        plan = self._generation_plan(project)
        if not plan:
            self._update_project(project["id"], state="awaiting_final_confirm")
            await self._send_final_summary(update, self._fetch_project(project["id"]) or project)
            return
        engine = project.get("generation_engine") or "auto"
        prompts = [p for _, p in plan]
        await update.effective_message.reply_text(f"🖼 Создаю {len(prompts)} визуалов. Это может занять несколько минут…")
        images = await self.image_batch_call(update, context, prompts, engine, "presentation_slide_images")
        if not images:
            await update.effective_message.reply_text("Не удалось создать изображения. Можно выбрать другую сеть или продолжить без них.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Выбрать другую сеть", callback_data="ps:gen_notes")],
                [InlineKeyboardButton("⏭ Продолжить без генерации", callback_data="ps:gen_skip")],
            ]))
            return
        for (slide_idx, prompt), raw in zip(plan, images):
            self._add_asset(project["id"], raw, "generated", engine, mime="image/jpeg", label=f"Слайд {slide_idx + 1}", slide_index=slide_idx, prompt=prompt)
        self._update_project(project["id"], state="awaiting_final_confirm")
        await update.effective_message.reply_text(f"✅ Создано изображений: {len(images)}.")
        await self._send_final_summary(update, self._fetch_project(project["id"]) or project)

    async def _send_final_summary(self, update: Update, project: JsonDict) -> None:
        outline = _safe_json_loads(project.get("outline_json"), {})
        style_key = project.get("style_key") or "minimal"
        style_label = STYLE_PRESETS.get(style_key, {}).get("label") or project.get("style_notes") or style_key
        palette = _safe_json_loads(project.get("palette_json"), {})
        logo = "есть" if project.get("logo_asset_id") else "нет"
        uploaded = self._count_assets(project["id"], ["photo"])
        generated = self._count_assets(project["id"], ["generated"])
        slides = len(outline.get("slides") or [])
        await update.effective_message.reply_text(
            "✅ Проект готов к финальной сборке:\n"
            f"• Название: {outline.get('title') or project.get('title')}\n"
            f"• Слайдов/страниц: {slides}\n"
            f"• Стиль: {style_label}\n"
            f"• Палитра: {palette.get('label') or project.get('palette_key') or 'авто'}\n"
            f"• Логотип: {logo}\n"
            f"• Загружено фото: {uploaded}\n"
            f"• Создано изображений: {generated}\n"
            "• Итог: редактируемый PPTX + PDF для отправки клиенту.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Собрать PDF + PPTX", callback_data="ps:final_render")],
                [InlineKeyboardButton("✏️ Изменить структуру", callback_data="ps:final_edit")],
                [InlineKeyboardButton("🖼 Добавить изображения", callback_data="ps:asset_mixed")],
                [InlineKeyboardButton("❌ Отменить", callback_data=f"ps:cancel:{project['id']}")],
            ])
        )

    async def _render_and_send(self, update: Update, context: ContextTypes.DEFAULT_TYPE, project: JsonDict) -> None:
        self._update_project(project["id"], state="rendering")
        await update.effective_message.reply_text("🧱 Собираю дизайнерский макет и экспортирую оба формата…")

        async def action() -> bool:
            paths = await asyncio.to_thread(self._render_project, self._fetch_project(project["id"]) or project)
            pptx_path, pdf_path = paths
            with open(pptx_path, "rb") as fh:
                p1 = io.BytesIO(fh.read()); p1.name = Path(pptx_path).name
            with open(pdf_path, "rb") as fh:
                p2 = io.BytesIO(fh.read()); p2.name = Path(pdf_path).name
            await update.effective_message.reply_document(InputFile(p1), caption="📊 PPTX готов — можно редактировать в PowerPoint.")
            await update.effective_message.reply_document(InputFile(p2), caption="📕 PDF готов — можно отправлять клиенту или печатать.")
            return True

        result = await self.paid_runner(update, context, "img", "presentation_render_pdf_pptx", self.cfg.render_cost_usd, action)
        if result:
            self._update_project(project["id"], state="done", status="done")
            context.user_data.pop("presentation_studio_active", None)
            await update.effective_message.reply_text("✅ Проект полностью готов в двух форматах. Для нового проекта снова откройте раздел «Работа/Бизнес».")
        else:
            self._update_project(project["id"], state="awaiting_final_confirm")

    def _render_project(self, project: JsonDict) -> tuple[str, str]:
        outline = _safe_json_loads(project.get("outline_json"), _fallback_outline(project.get("brief") or "", project.get("kind") or "presentation"))
        style_key = project.get("style_key") or "minimal"
        style = dict(STYLE_PRESETS.get(style_key, STYLE_PRESETS["minimal"]))
        if project.get("style_notes"):
            style["notes"] = project["style_notes"]
        palette = _safe_json_loads(project.get("palette_json"), PALETTE_PRESETS.get(project.get("palette_key") or style.get("default_palette") or "white_minimal", PALETTE_PRESETS["white_minimal"]))
        logo_path = None
        if project.get("logo_asset_id"):
            all_assets = self._assets(project["id"], ["logo", "logo_variant"], selected_only=False)
            logo = next((a for a in all_assets if a["id"] == project.get("logo_asset_id")), None)
            if logo and os.path.exists(logo["file_path"]): logo_path = logo["file_path"]
        visuals = [a for a in self._assets(project["id"], ["photo", "generated"]) if os.path.exists(a["file_path"])]
        project_dir = self._project_dir(project["id"])
        title = _safe_filename(outline.get("title") or project.get("title") or "presentation", "")[:-1]
        pptx_path = str(project_dir / _safe_filename(title, "pptx"))
        pdf_path = str(project_dir / _safe_filename(title, "pdf"))
        self._render_pptx(outline, style, palette, logo_path, visuals, pptx_path)
        self._render_pdf(outline, style, palette, logo_path, visuals, pdf_path)
        return pptx_path, pdf_path

    def _image_for_slide(self, visuals: list[JsonDict], slide_index: int, used_ids: set[int]) -> str | None:
        exact = next((a for a in visuals if a.get("slide_index") == slide_index and a["id"] not in used_ids), None)
        if exact:
            used_ids.add(exact["id"]); return exact["file_path"]
        available = next((a for a in visuals if a["id"] not in used_ids), None)
        if available:
            used_ids.add(available["id"]); return available["file_path"]
        return None

    def _crop_temp(self, source: str, width: int, height: int, project_tag: str) -> str:
        out = self.data_dir / f"crop_{project_tag}_{uuid.uuid4().hex[:8]}.jpg"
        im = Image.open(source).convert("RGB")
        im = ImageOps.fit(im, (width, height), Image.Resampling.LANCZOS)
        im.save(out, "JPEG", quality=92, optimize=True)
        return str(out)

    def _render_pptx(self, outline: JsonDict, style: JsonDict, palette: JsonDict, logo_path: str | None, visuals: list[JsonDict], out_path: str) -> None:
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
        from pptx.util import Inches, Pt

        prs = Presentation(); prs.slide_width = Inches(13.333); prs.slide_height = Inches(7.5)
        blank = prs.slide_layouts[6]
        used: set[int] = set()
        bg = _rgb(palette["bg"]); surface = _rgb(palette["surface"]); text_c = _rgb(palette["text"]); muted = _rgb(palette["muted"]); accent = _rgb(palette["accent"]); accent2 = _rgb(palette["accent2"])

        def add_rect(slide, x, y, w, h, fill, radius=False, line=None):
            shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
            sh = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
            sh.fill.solid(); sh.fill.fore_color.rgb = RGBColor(*fill)
            sh.line.color.rgb = RGBColor(*(line or fill))
            return sh

        def add_text(slide, value, x, y, w, h, size, color, bold=False, align=PP_ALIGN.LEFT, font=None):
            box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
            tf = box.text_frame; tf.clear(); tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.TOP
            p = tf.paragraphs[0]; p.text = str(value or ""); p.alignment = align
            p.font.name = font or style.get("font") or "Aptos"; p.font.size = Pt(size); p.font.bold = bold; p.font.color.rgb = RGBColor(*color)
            return box

        def add_logo(slide):
            if logo_path and os.path.exists(logo_path):
                with contextlib.suppress(Exception): slide.shapes.add_picture(logo_path, Inches(11.8), Inches(0.25), width=Inches(1.15), height=Inches(0.72))

        slides = outline.get("slides") or []
        for idx, item in enumerate(slides):
            slide = prs.slides.add_slide(blank)
            add_rect(slide, 0, 0, 13.333, 7.5, bg)
            layout = str(item.get("layout") or "split")
            image_path = self._image_for_slide(visuals, idx, used) if item.get("needs_image") else None
            title = item.get("title") or f"Слайд {idx + 1}"
            bullets = [str(x) for x in (item.get("bullets") or [])]
            if idx == 0 or layout == "cover":
                if image_path:
                    cropped = self._crop_temp(image_path, 1000, 1200, "pptx")
                    slide.shapes.add_picture(cropped, Inches(7.3), Inches(0), width=Inches(6.033), height=Inches(7.5))
                    add_rect(slide, 7.05, 0, 0.32, 7.5, accent)
                add_text(slide, title, 0.72, 1.1, 6.0, 2.2, 30, text_c, True)
                if outline.get("subtitle"): add_text(slide, outline.get("subtitle"), 0.75, 3.4, 5.7, 0.8, 18, muted)
                if bullets: add_text(slide, " • ".join(bullets[:3]), 0.75, 4.35, 5.9, 1.2, 15, muted)
                add_rect(slide, 0.75, 6.4, 2.3, 0.08, accent)
                add_logo(slide)
                continue
            add_logo(slide)
            add_text(slide, f"{idx + 1:02d}", 0.55, 0.35, 0.55, 0.45, 12, accent, True)
            add_text(slide, title, 1.05, 0.45, 10.5, 0.8, style.get("title_size", 28), text_c, True)
            add_rect(slide, 1.05, 1.33, 1.35, 0.07, accent)
            if image_path:
                image_left = idx % 2 == 0
                img_x = 0.65 if image_left else 7.25
                txt_x = 7.0 if image_left else 0.8
                cropped = self._crop_temp(image_path, 1100, 850, "pptx")
                add_rect(slide, img_x - 0.05, 1.72, 5.45, 4.95, surface, radius=True)
                slide.shapes.add_picture(cropped, Inches(img_x), Inches(1.78), width=Inches(5.35), height=Inches(4.83))
                text_w = 5.35
            else:
                txt_x = 0.85; text_w = 11.6
                # Decorative grid when no image is used.
                for k in range(3):
                    add_rect(slide, 8.8 + k * 1.08, 2.1 + k * 0.75, 0.82, 0.82, accent if k == 0 else accent2, radius=True)
            if layout in {"cards", "benefits", "process", "product"} and len(bullets) >= 3:
                card_count = min(4, len(bullets))
                card_w = text_w if card_count == 1 else (text_w - 0.25 * (card_count - 1)) / min(2, card_count)
                for k, bullet in enumerate(bullets[:card_count]):
                    row, col = divmod(k, 2)
                    x = txt_x + col * (card_w + 0.25); y = 1.82 + row * 2.15
                    add_rect(slide, x, y, card_w, 1.85, surface, radius=True, line=accent2)
                    add_text(slide, str(k + 1), x + 0.22, y + 0.22, 0.45, 0.4, 13, accent, True)
                    add_text(slide, bullet, x + 0.22, y + 0.72, card_w - 0.44, 0.9, 15, text_c, True)
            else:
                y = 1.88
                for bullet in bullets[:6]:
                    add_rect(slide, txt_x, y + 0.05, 0.11, 0.11, accent, radius=True)
                    add_text(slide, bullet, txt_x + 0.28, y - 0.04, text_w - 0.28, 0.72, style.get("body_size", 17), text_c)
                    y += 0.78
            add_text(slide, outline.get("title") or "", 0.75, 7.05, 7.5, 0.24, 8, muted)
            add_text(slide, str(idx + 1), 12.25, 7.0, 0.45, 0.24, 8, muted, align=PP_ALIGN.RIGHT)
        prs.save(out_path)

    def _render_pdf(self, outline: JsonDict, style: JsonDict, palette: JsonDict, logo_path: str | None, visuals: list[JsonDict], out_path: str) -> None:
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas

        page = landscape(A4); W, H = page
        regular, bold = "Helvetica", "Helvetica-Bold"
        fp_reg, fp_bold = self._font_path(False), self._font_path(True)
        if fp_reg and fp_bold:
            with contextlib.suppress(Exception):
                pdfmetrics.registerFont(TTFont("PSDejaVu", fp_reg)); pdfmetrics.registerFont(TTFont("PSDejaVuBold", fp_bold)); regular, bold = "PSDejaVu", "PSDejaVuBold"
        c = canvas.Canvas(out_path, pagesize=page)
        used: set[int] = set()
        bg = _rgb(palette["bg"]); surface = _rgb(palette["surface"]); text_c = _rgb(palette["text"]); muted = _rgb(palette["muted"]); accent = _rgb(palette["accent"]); accent2 = _rgb(palette["accent2"])

        def fill(rgb): c.setFillColorRGB(*(x / 255 for x in rgb))
        def stroke(rgb): c.setStrokeColorRGB(*(x / 255 for x in rgb))
        def draw_wrapped(text, x, y, max_chars, leading, font_name, font_size, color, max_lines=8):
            fill(color); c.setFont(font_name, font_size)
            lines: list[str] = []
            for paragraph in str(text or "").splitlines() or [""]:
                lines.extend(textwrap.wrap(paragraph, width=max_chars, break_long_words=False) or [""])
            for line in lines[:max_lines]:
                c.drawString(x, y, line); y -= leading
            return y

        slides = outline.get("slides") or []
        for idx, item in enumerate(slides):
            fill(bg); c.rect(0, 0, W, H, fill=1, stroke=0)
            image_path = self._image_for_slide(visuals, idx, used) if item.get("needs_image") else None
            title = item.get("title") or f"Слайд {idx + 1}"; bullets = [str(x) for x in (item.get("bullets") or [])]
            if idx == 0 or item.get("layout") == "cover":
                if image_path:
                    crop = self._crop_temp(image_path, 1100, 1200, "pdf")
                    c.drawImage(ImageReader(crop), W * 0.55, 0, width=W * 0.45, height=H, preserveAspectRatio=False, mask='auto')
                    fill(accent); c.rect(W * 0.535, 0, W * 0.015, H, fill=1, stroke=0)
                y = H - 115
                y = draw_wrapped(title, 55, y, 31, 37, bold, 27, text_c, max_lines=4)
                if outline.get("subtitle"): y -= 18; y = draw_wrapped(outline.get("subtitle"), 57, y, 50, 22, regular, 15, muted, max_lines=3)
                if bullets: y -= 15; draw_wrapped(" • ".join(bullets[:3]), 57, y, 62, 18, regular, 11.5, muted, max_lines=5)
            else:
                fill(accent); c.roundRect(38, H - 70, 24, 24, 6, fill=1, stroke=0)
                fill(_rgb(_contrast(palette["accent"]))); c.setFont(bold, 8); c.drawCentredString(50, H - 61, str(idx + 1))
                draw_wrapped(title, 78, H - 58, 58, 28, bold, 23, text_c, max_lines=2)
                fill(accent); c.rect(78, H - 86, 90, 4, fill=1, stroke=0)
                if image_path:
                    image_left = idx % 2 == 0
                    img_x = 38 if image_left else W * 0.56
                    txt_x = W * 0.54 if image_left else 55
                    img_w = W * 0.39; img_h = H * 0.63; img_y = 55
                    crop = self._crop_temp(image_path, 1000, 760, "pdf")
                    fill(surface); c.roundRect(img_x - 4, img_y - 4, img_w + 8, img_h + 8, 12, fill=1, stroke=0)
                    c.drawImage(ImageReader(crop), img_x, img_y, width=img_w, height=img_h, preserveAspectRatio=False, mask='auto')
                    max_chars = 44
                else:
                    txt_x = 58; max_chars = 86
                y = H - 130
                if item.get("layout") in {"cards", "benefits", "process", "product"} and len(bullets) >= 3:
                    for k, bullet in enumerate(bullets[:4]):
                        row, col = divmod(k, 2); card_w = (W * 0.39 if image_path else W * 0.4); card_h = 88
                        x = txt_x + col * (card_w + 14); yy = H - 160 - row * (card_h + 16)
                        fill(surface); stroke(accent2); c.roundRect(x, yy - card_h, card_w, card_h, 10, fill=1, stroke=1)
                        fill(accent); c.setFont(bold, 9); c.drawString(x + 15, yy - 20, str(k + 1))
                        draw_wrapped(bullet, x + 15, yy - 44, 36, 15, bold, 11, text_c, max_lines=3)
                else:
                    for bullet in bullets[:6]:
                        fill(accent); c.circle(txt_x + 3, y + 3, 3.5, fill=1, stroke=0)
                        y = draw_wrapped(bullet, txt_x + 16, y + 8, max_chars, 20, regular, 13, text_c, max_lines=3) - 7
                fill(muted); c.setFont(regular, 7); c.drawString(42, 24, str(outline.get("title") or "")); c.drawRightString(W - 42, 24, str(idx + 1))
            if logo_path and os.path.exists(logo_path):
                with contextlib.suppress(Exception): c.drawImage(ImageReader(logo_path), W - 92, H - 54, width=60, height=38, preserveAspectRatio=True, mask='auto')
            c.showPage()
        c.save()

    @staticmethod
    def _logo_choice_kb() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Загрузить свой логотип", callback_data="ps:logo_upload")],
            [InlineKeyboardButton("✨ Создать 3 варианта логотипа", callback_data="ps:logo_generate")],
            [InlineKeyboardButton("⏭ Продолжить без логотипа", callback_data="ps:logo_skip")],
        ])

    @staticmethod
    def _asset_source_kb() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Загрузить свои фотографии", callback_data="ps:asset_upload")],
            [InlineKeyboardButton("✨ Сгенерировать изображения", callback_data="ps:asset_generate")],
            [InlineKeyboardButton("📦 Смешанный режим", callback_data="ps:asset_mixed")],
            [InlineKeyboardButton("⏭ Продолжить без изображений", callback_data="ps:asset_none")],
        ])

    @staticmethod
    def _upload_kb() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Завершить загрузку", callback_data="ps:upload_done")],
            [InlineKeyboardButton("🗑 Очистить изображения", callback_data="ps:upload_clear")],
        ])

    @staticmethod
    def _style_kb() -> InlineKeyboardMarkup:
        rows = [[InlineKeyboardButton(v["label"], callback_data=f"ps:style:{k}")] for k, v in STYLE_PRESETS.items()]
        rows.append([InlineKeyboardButton("🎨 Свой стиль", callback_data="ps:style:custom")])
        return InlineKeyboardMarkup(rows)
