# -*- coding: utf-8 -*-
"""
BOT GPT-5 • Luma • Runway • Midjourney • Deepgram
Единый ИИ: тексты, изображения, видео, озвучка, анализ документов.

Совместим: python-telegram-bot==21.6, Python 3.12.x
"""

import os
import re
import io
import sys
import json
import time
import uuid
import base64
import asyncio
import logging
import sqlite3
import contextlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import httpx
from PIL import Image
from io import BytesIO

# Telegram
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton,
    InputFile, ChatAction
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters
)
from telegram.constants import ParseMode

# Docs
from pdfminer.high_level import extract_text as pdf_extract_text
from docx import Document as DocxDocument
from ebooklib import epub

# Image tools
from rembg import remove as rembg_remove

# OpenAI
from openai import OpenAI

# Optional fact-check
with contextlib.suppress(Exception):
    from tavily import TavilyClient

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt5-bot")

# ──────────────────────────────────────────────────────────────────────────────
# ENV
# ──────────────────────────────────────────────────────────────────────────────

BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
BOT_USERNAME = (os.getenv("BOT_USERNAME") or "").strip().lstrip("@")

PUBLIC_URL = (os.getenv("PUBLIC_URL") or "").strip()
WEBAPP_URL = (os.getenv("WEBAPP_URL") or PUBLIC_URL).strip()

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
OPENAI_TTS_VOICE = (os.getenv("OPENAI_TTS_VOICE") or "alloy").strip()
OPENAI_STT_MODEL = (os.getenv("OPENAI_STT_MODEL") or "whisper-1").strip()

LUMA_API_KEY = (os.getenv("LUMA_API_KEY") or "").strip()
LUMA_API_BASE = (os.getenv("LUMA_API_BASE") or "https://api.lumalabs.ai").strip()

RUNWAY_API_KEY = (os.getenv("RUNWAY_API_KEY") or "").strip()
RUNWAY_API_BASE = (os.getenv("RUNWAY_API_BASE") or "https://api.runwayml.com/v1").strip()

CRYPTOBOT_TOKEN = (os.getenv("CRYPTOBOT_TOKEN") or "").strip()
CRYPTOBOT_CURRENCY = (os.getenv("CRYPTOBOT_CURRENCY") or "USDT").strip()
CRYPTOBOT_BASE = (os.getenv("CRYPTOBOT_BASE") or "https://pay.crypt.bot").strip()

TAVILY_API_KEY = (os.getenv("TAVILY_API_KEY") or "").strip()
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID") or "0")

DB_PATH = (os.getenv("DB_PATH") or str(Path(__file__).with_name("bot.db"))).strip()

# ──────────────────────────────────────────────────────────────────────────────
# DB
# ──────────────────────────────────────────────────────────────────────────────

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT, first_name TEXT, last_name TEXT,
            lang TEXT DEFAULT 'ru',
            voice_on INTEGER DEFAULT 0,
            tts_voice TEXT DEFAULT 'alloy',
            default_engine TEXT DEFAULT 'luma',
            credits INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs(
            id TEXT PRIMARY KEY, user_id INTEGER,
            kind TEXT, engine TEXT,
            status TEXT, payload TEXT, result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS payments(
            id TEXT PRIMARY KEY, user_id INTEGER,
            provider TEXT, currency TEXT, amount REAL,
            status TEXT, meta TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()
    log.info("DB ready: %s", DB_PATH)

def upsert_user(u):
    with db() as conn:
        conn.execute("""
            INSERT INTO users(user_id, username, first_name, last_name)
            VALUES(?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
              username=excluded.username,
              first_name=excluded.first_name,
              last_name=excluded.last_name,
              updated_at=CURRENT_TIMESTAMP
        """, (u.id, u.username, u.first_name, u.last_name))
        conn.commit()

def set_user_setting(user_id: int, field: str, value):
    with db() as conn:
        conn.execute(f"UPDATE users SET {field}=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                     (value, user_id))
        conn.commit()

def get_user(user_id: int) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else {}

def add_credits(user_id: int, amount: int):
    with db() as conn:
        conn.execute("UPDATE users SET credits=credits+? WHERE user_id=?", (amount, user_id))
        conn.commit()

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def chat_action(action: ChatAction):
    def deco(fn):
        async def wrap(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
            with contextlib.suppress(Exception):
                await context.bot.send_chat_action(update.effective_chat.id, action)
            return await fn(update, context, *a, **kw)
        return wrap
    return deco

def shorten(s: str, n: int=300) -> str:
    return s if len(s) <= n else s[: n-1] + "…"

def parse_duration_and_ratio(txt: str) -> Tuple[int, str]:
    t = txt.lower().replace("секунд", "s").replace("сек", "s")
    dur = 5
    m = re.search(r"(\d+)\s*s", t)
    if m: dur = int(m.group(1))
    if "9:16" in t: ar = "9:16"
    elif "1:1" in t: ar = "1:1"
    else: ar = "16:9"
    dur = max(2, min(20, dur))
    return dur, ar

def bytes_to_inputfile(data: bytes, name: str) -> InputFile:
    bio = BytesIO(data); bio.name = name
    return InputFile(bio, filename=name)

# ──────────────────────────────────────────────────────────────────────────────
# UI текст/кнопки
# ──────────────────────────────────────────────────────────────────────────────

def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🚀 Начать работу"), KeyboardButton("🎛 Движки")],
            [KeyboardButton("🗂 Возможности"), KeyboardButton("💳 Пополнить")],
            [KeyboardButton("🔊 Озвучка Вкл/Выкл")],
        ],
        resize_keyboard=True
    )

def engines_kb() -> InlineKeyboardMarkup:
    btns = []
    btns.append([InlineKeyboardButton("🎬 Luma", callback_data="engine_luma")]) if LUMA_API_KEY else None
    btns.append([InlineKeyboardButton("🎥 Runway", callback_data="engine_runway")]) if RUNWAY_API_KEY else None
    if not btns:
        btns = [[InlineKeyboardButton("ℹ️ Движков нет (задайте ключи)", callback_data="noop")]]
    return InlineKeyboardMarkup(btns)

def photo_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌀 Оживить фото (Image→Video)", callback_data="act_image2video")],
        [
            InlineKeyboardButton("🪄 Удалить фон", callback_data="act_bg_remove"),
            InlineKeyboardButton("🌅 Заменить фон", callback_data="act_bg_replace"),
        ],
        [
            InlineKeyboardButton("➕ Добавить объект", callback_data="act_add_object"),
            InlineKeyboardButton("➖ Удалить объект", callback_data="act_remove_object"),
        ],
        [
            InlineKeyboardButton("✨ Ретушь/апскейл", callback_data="act_upscale"),
            InlineKeyboardButton("🧑‍🎨 Аватар/логотип", callback_data="act_avatar"),
        ],
    ])

def vr_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("5s • 16:9", callback_data="vr_5_16x9"),
            InlineKeyboardButton("9s • 9:16", callback_data="vr_9_9x16"),
            InlineKeyboardButton("6s • 1:1", callback_data="vr_6_1x1"),
        ]
    ])

HYPE_TEXT = (
    "🔥 Хайповые возможности прямо сейчас\n\n"
    "• 🧟 Оживление старых фото (анимация лица, «говорящие» портреты)\n"
    "• 🖼️ Фотореалистичные арты/логотипы\n"
    "• 🎬 Фото→видео и текст→видео (Luma/Runway)\n"
    "• 👄 Lip-sync / Talking-head\n"
    "• 🧹 Удаление/замена фона, ретушь, апскейл до 4K\n"
    "• 🗣️ Озвучка ответов (TTS), диктовка и распознавание речи (STT)\n"
    "• 📄 Глубокий разбор PDF/таблиц/изображений\n"
    "• 🧠 Агентные сценарии: прочитай → тезисы → презентация → озвучь\n"
    "• 🔎 Факт-чек и аккуратные ссылки (Tavily)\n"
)

START_TEXT = (
    "Привет! Это BOT GPT-5 • Luma • Runway • Midjourney • Deepgram\n\n"
    "Единый ИИ для текстов, изображений, видео, озвучки и документов.\n"
    "Пришли текст, голосовое, фото или PDF/DOCX/EPUB — предложу действия.\n\n"
    "Команды: /modes /engines /voice_on /voice_off /plans /topup /help"
)

MODES_TEXT = (
    "Режимы:\n"
    "• Чат GPT (по умолчанию)\n"
    "• Фото: быстрые действия\n"
    "• Оживить фото → видео (Luma/Runway)\n"
    "• Текст→видео (Luma/Runway)\n"
    "• Анализ PDF/DOCX/EPUB\n"
    "• Факт-чек\n"
)

EXAMPLES_TEXT = (
    "Примеры:\n"
    "• «Сделай видео ретро-авто, 9 секунд, 9:16»\n"
    "• «Оживи эту фотографию: моргание и панорамирование» (пришли фото)\n"
    "• «Удали фон и поставь белый» (пришли фото)\n"
    "• «Прочитай PDF и сделай тезисы на 10 пунктов»\n"
)

PLANS_TEXT = (
    "Тарифы:\n"
    "• Free — базовые функции\n"
    "• PRO — расширенные лимиты + Luma/Runway + TTS/STT буст\n"
    "Пополнение: /topup (CryptoBot)\n"
)

# ──────────────────────────────────────────────────────────────────────────────
# OpenAI helpers (chat, TTS, STT, image edit)
# ──────────────────────────────────────────────────────────────────────────────

def get_openai() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing")
    return OpenAI(api_key=OPENAI_API_KEY)

async def ai_chat(messages: List[Dict[str, str]], model: Optional[str] = None) -> str:
    model = model or OPENAI_MODEL
    client = get_openai()
    try:
        resp = await asyncio.to_thread(client.chat.completions.create, model=model, messages=messages)
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.exception("OpenAI chat error"); return f"❌ Ошибка OpenAI: {e}"

async def ai_tts_ogg(text: str, voice: str) -> bytes:
    client = get_openai()
    try:
        resp = await asyncio.to_thread(
            client.audio.speech.with_streaming_response.create,
            model="gpt-4o-mini-tts",
            voice=voice,
            input=text,
            format="opus",
        )
        out = io.BytesIO()
        with resp as s: s.stream_to_file(out)
        return out.getvalue()
    except Exception:
        log.exception("TTS error"); return b""

async def ai_stt_ogg(data: bytes, model: Optional[str] = None) -> str:
    model = model or OPENAI_STT_MODEL
    client = get_openai()
    try:
        p = "/tmp/in.ogg"
        with open(p, "wb") as f: f.write(data)
        with open(p, "rb") as f:
            resp = await asyncio.to_thread(client.audio.transcriptions.create, model=model, file=f)
        text = getattr(resp, "text", None) or (resp.get("text") if isinstance(resp, dict) else "")
        return (text or "").strip()
    except Exception:
        log.exception("STT error"); return ""

async def ai_image_edit(image_bytes: bytes, prompt: str, mask_bytes: Optional[bytes] = None) -> bytes:
    """OpenAI image edit (best-effort route)."""
    try:
        files = {"image": ("image.png", image_bytes, "image/png")}
        if mask_bytes: files["mask"] = ("mask.png", mask_bytes, "image/png")
        data = {"prompt": prompt, "size": "1024x1024"}
        async with httpx.AsyncClient(timeout=120) as http:
            r = await http.post(
                "https://api.openai.com/v1/images/edits",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                data=data, files=files
            )
            r.raise_for_status()
            js = r.json()
            return base64.b64decode(js["data"][0]["b64_json"])
    except Exception:
        log.exception("image edit error")
        raise

# ──────────────────────────────────────────────────────────────────────────────
# Local image ops
# ──────────────────────────────────────────────────────────────────────────────

def img_from_bytes(b: bytes) -> Image.Image:
    return Image.open(BytesIO(b)).convert("RGBA")

def img_to_png_bytes(im: Image.Image) -> bytes:
    bio = BytesIO(); im.save(bio, format="PNG"); return bio.getvalue()

def remove_bg(image_bytes: bytes) -> bytes:
    return rembg_remove(image_bytes)

def replace_bg(image_bytes: bytes, color=(255,255,255)) -> bytes:
    fg = img_from_bytes(image_bytes)
    bg = Image.new("RGBA", fg.size, color + (255,))
    out = Image.alpha_composite(bg, fg)
    return img_to_png_bytes(out.convert("RGB"))

def upscale_x2(image_bytes: bytes) -> bytes:
    im = img_from_bytes(image_bytes)
    im = im.resize((im.width*2, im.height*2), Image.LANCZOS)
    return img_to_png_bytes(im.convert("RGB"))

# ──────────────────────────────────────────────────────────────────────────────
# Luma / Runway (best-effort, правь эндпоинты под свои ключи/аккаунты)
# ──────────────────────────────────────────────────────────────────────────────

async def luma_text2video(prompt: str, duration_s=5, aspect_ratio="16:9") -> dict:
    if not LUMA_API_KEY: raise RuntimeError("LUMA_API_KEY missing")
    url = f"{LUMA_API_BASE}/v1/dream/text-to-video"
    headers = {"Authorization": f"Bearer {LUMA_API_KEY}"}
    payload = {"prompt": prompt, "duration": duration_s, "aspect_ratio": aspect_ratio}
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(url, headers=headers, json=payload); r.raise_for_status()
        return r.json()

async def luma_image2video(image_bytes: bytes, prompt: str, duration_s=5, aspect_ratio="16:9") -> dict:
    if not LUMA_API_KEY: raise RuntimeError("LUMA_API_KEY missing")
    url = f"{LUMA_API_BASE}/v1/dream/image-to-video"
    headers = {"Authorization": f"Bearer {LUMA_API_KEY}"}
    files = {"image": ("image.png", image_bytes, "image/png")}
    data = {"prompt": prompt, "duration": str(duration_s), "aspect_ratio": aspect_ratio}
    async with httpx.AsyncClient(timeout=120) as http:
        r = await http.post(url, headers=headers, data=data, files=files); r.raise_for_status()
        return r.json()

async def luma_get_job(job_id: str) -> dict:
    url = f"{LUMA_API_BASE}/v1/jobs/{job_id}"
    headers = {"Authorization": f"Bearer {LUMA_API_KEY}"}
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get(url, headers=headers); r.raise_for_status()
        return r.json()

async def runway_text2video(prompt: str, duration_s=5, aspect_ratio="16:9") -> dict:
    if not RUNWAY_API_KEY: raise RuntimeError("RUNWAY_API_KEY missing")
    url = f"{RUNWAY_API_BASE}/gen3/text-to-video"
    headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Content-Type": "application/json"}
    payload = {"prompt": prompt, "duration": duration_s, "aspect_ratio": aspect_ratio}
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(url, headers=headers, json=payload); r.raise_for_status()
        return r.json()

async def runway_image2video(image_bytes: bytes, prompt: str, duration_s=5, aspect_ratio="16:9") -> dict:
    if not RUNWAY_API_KEY: raise RuntimeError("RUNWAY_API_KEY missing")
    url = f"{RUNWAY_API_BASE}/gen3/image-to-video"
    headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}"}
    files = {"image": ("image.png", image_bytes, "image/png")}
    data = {"prompt": prompt, "duration": str(duration_s), "aspect_ratio": aspect_ratio}
    async with httpx.AsyncClient(timeout=120) as http:
        r = await http.post(url, headers=headers, data=data, files=files); r.raise_for_status()
        return r.json()

async def runway_get_job(job_id: str) -> dict:
    url = f"{RUNWAY_API_BASE}/jobs/{job_id}"
    headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}"}
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get(url, headers=headers); r.raise_for_status()
        return r.json()

async def poll_and_send_video(update: Update, context: ContextTypes.DEFAULT_TYPE, engine: str, job_handle: dict, job_db_id: str):
    chat_id = update.effective_chat.id
    getter = luma_get_job if engine == "luma" else runway_get_job
    try:
        for _ in range(60):  # ~5 минут
            await asyncio.sleep(5)
            job_id = job_handle.get("id") or job_handle.get("job_id") or job_db_id
            js = await getter(job_id)
            status = (js.get("status") or js.get("state") or "").lower()
            if status in ("succeeded", "completed", "done"):
                url = js.get("result", {}).get("url") or js.get("output", {}).get("url") or js.get("video_url")
                if not url:
                    assets = js.get("assets") or []
                    if assets and isinstance(assets, list):
                        url = assets[0].get("url")
                if not url:
                    await context.bot.send_message(chat_id, "⚠️ Видео сгенерировано, но ссылка не найдена.")
                    _update_job(job_db_id, "failed", {"reason": "no url", "raw": js}); return
                async with httpx.AsyncClient(timeout=180) as http:
                    r = await http.get(url); r.raise_for_status(); data = r.content
                await context.bot.send_video(chat_id, data, caption="Готово 🎬")
                _update_job(job_db_id, "succeeded", {"video_url": url}); return
            if status in ("failed", "error", "canceled"):
                await context.bot.send_message(chat_id, f"❌ Ошибка {engine.capitalize()} при генерации видео.")
                _update_job(job_db_id, "failed", {"engine_status": status}); return
        await context.bot.send_message(chat_id, "⏳ Долго нет ответа. Попробуйте позже.")
        _update_job(job_db_id, "failed", {"reason": "timeout"})
    except Exception as e:
        log.exception("polling error")
        await context.bot.send_message(chat_id, f"❌ Ошибка при получении результата: {e}")
        _update_job(job_db_id, "failed", {"error": str(e)})

def _enqueue_job(user_id: int, kind: str, engine: str, payload: dict) -> str:
    jid = str(uuid.uuid4())
    with db() as conn:
        conn.execute("INSERT INTO jobs(id, user_id, kind, engine, status, payload) VALUES(?,?,?,?,?,?)",
                     (jid, user_id, kind, engine, "queued", json.dumps(payload, ensure_ascii=False)))
        conn.commit()
    return jid

def _update_job(jid: str, status: str, result: Optional[dict] = None):
    with db() as conn:
        conn.execute("UPDATE jobs SET status=?, result=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (status, json.dumps(result or {}, ensure_ascii=False), jid))
        conn.commit()

# ──────────────────────────────────────────────────────────────────────────────
# CryptoBot
# ──────────────────────────────────────────────────────────────────────────────

async def cryptobot_create_invoice(amount: float, desc: str, currency: str = None) -> dict:
    currency = currency or CRYPTOBOT_CURRENCY
    if not CRYPTOBOT_TOKEN: raise RuntimeError("CRYPTOBOT_TOKEN not set")
    url = f"{CRYPTOBOT_BASE}/api/createInvoice"
    headers = {"Content-Type": "application/json", "Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    payload = {"amount": f"{amount:.2f}", "asset": currency, "description": desc}
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(url, headers=headers, json=payload); r.raise_for_status()
        js = r.json()
        if not js.get("ok"): raise RuntimeError(js)
        return js["result"]

async def cryptobot_get_invoices() -> list:
    if not CRYPTOBOT_TOKEN: return []
    url = f"{CRYPTOBOT_BASE}/api/getInvoices"
    headers = {"Content-Type": "application/json", "Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(url, headers=headers, json={}); r.raise_for_status()
        js = r.json(); return js.get("result", [])

# ──────────────────────────────────────────────────────────────────────────────
# Интенты
# ──────────────────────────────────────────────────────────────────────────────

PHOTO_POSITIVE_PATTERNS = [
    "ожив", "говорящ", "анимируй", "анимировать", "оживи", "оживить",
    "удал", "замен", "фон", "объект", "добав", "дорис", "перемещ",
    "аватар", "логотип", "ретуш", "апскейл", "поверн", "камера",
]

def is_photo_positive(msg: str) -> bool:
    m = (msg or "").lower()
    return any(p in m for p in PHOTO_POSITIVE_PATTERNS)

def looks_like_image2video(msg: str) -> bool:
    m = (msg or "").lower()
    return ("ожив" in m) or ("image2video" in m) or ("сделай видео из фото" in m)

def pick_engine_for(user: dict) -> str:
    if user and user.get("default_engine") in ("luma","runway"):
        if user["default_engine"] == "luma" and LUMA_API_KEY: return "luma"
        if user["default_engine"] == "runway" and RUNWAY_API_KEY: return "runway"
    return "luma" if LUMA_API_KEY else ("runway" if RUNWAY_API_KEY else "none")

# ──────────────────────────────────────────────────────────────────────────────
# Команды
# ──────────────────────────────────────────────────────────────────────────────

@chat_action(ChatAction.TYPING)
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user)
    await update.message.reply_text(START_TEXT, reply_markup=main_kb())

@chat_action(ChatAction.TYPING)
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HYPE_TEXT)

@chat_action(ChatAction.TYPING)
async def cmd_modes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(MODES_TEXT)

@chat_action(ChatAction.TYPING)
async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(EXAMPLES_TEXT)

@chat_action(ChatAction.TYPING)
async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(PLANS_TEXT)

@chat_action(ChatAction.TYPING)
async def cmd_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "✅ Доступность движков:\n"
    text += f"• Luma: {'доступен' if LUMA_API_KEY else 'нет ключа'}\n"
    text += f"• Runway: {'доступен' if RUNWAY_API_KEY else 'нет ключа'}"
    await update.message.reply_text(text, reply_markup=engines_kb())

@chat_action(ChatAction.TYPING)
async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user)
    set_user_setting(update.effective_user.id, "voice_on", 1)
    await update.message.reply_text("🔊 Озвучка включена.")

@chat_action(ChatAction.TYPING)
async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user)
    set_user_setting(update.effective_user.id, "voice_on", 0)
    await update.message.reply_text("🔇 Озвучка выключена.")

@chat_action(ChatAction.TYPING)
async def cmd_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        inv = await cryptobot_create_invoice(5.00, "Пополнение баланса (PRO)")
        pay_url = inv.get("pay_url") or inv.get("bot_invoice_url") or inv.get("mini_app_invoice_url") or ""
        inv_id = str(inv.get("invoice_id") or inv.get("id"))
        with db() as conn:
            conn.execute("INSERT INTO payments(id, user_id, provider, currency, amount, status, meta) VALUES(?,?,?,?,?,?,?)",
                         (inv_id, update.effective_user.id, "cryptobot", CRYPTOBOT_CURRENCY, float(inv.get("amount", 0) or 0), "created", json.dumps(inv)))
            conn.commit()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Оплатить в CryptoBot", url=pay_url)]])
        await update.message.reply_text("Счёт создан. После оплаты вернись — проверю статус.", reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        log.exception("topup error"); await update.message.reply_text(f"Не удалось создать счёт: {e}")

@chat_action(ChatAction.TYPING)
async def cmd_check_invoices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        invs = await cryptobot_get_invoices()
        count = 0
        for inv in invs:
            if inv.get("status") != "paid": continue
            inv_id = str(inv.get("invoice_id") or inv.get("id"))
            with db() as conn:
                row = conn.execute("SELECT status FROM payments WHERE id=?", (inv_id,)).fetchone()
                already = row and row["status"] == "paid"
                if not already:
                    conn.execute("UPDATE payments SET status='paid', updated_at=CURRENT_TIMESTAMP WHERE id=?", (inv_id,))
                    conn.commit()
                    add_credits(update.effective_user.id, 50); count += 1
        await update.message.reply_text(f"Зачислено по {count} опл. счетам. Баланс обновлён.")
    except Exception as e:
        log.exception("invoices error"); await update.message.reply_text(f"Ошибка проверки счетов: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# Текст, голос, фото, документы
# ──────────────────────────────────────────────────────────────────────────────

@chat_action(ChatAction.TYPING)
async def on_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # если ждём описания для инпейнтинга
    if context.user_data.get("await_inpaint_prompt"):
        await on_inpaint_prompt(update, context); return
    await on_text(update, context)

@chat_action(ChatAction.TYPING)
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user)
    txt = (update.message.text or "").strip()
    user = get_user(update.effective_user.id)

    if txt.lower() in ("движки", "🎛 движки"):
        await cmd_engines(update, context); return
    if txt.lower() in ("начать","🚀 начать работу"):
        await update.message.reply_text("Пришли текст/голос/фото/документ — подскажу, что могу сделать.", reply_markup=main_kb()); return
    if txt.lower() in ("🗂 возможности","возможности"):
        await update.message.reply_text(HYPE_TEXT); return
    if txt.lower() in ("🔊 озвучка вкл/выкл",):
        if user.get("voice_on"): await cmd_voice_off(update, context)
        else: await cmd_voice_on(update, context)
        return

    # факт-чек
    if txt.lower().startswith("проверь") or "факт" in txt.lower():
        ans = await fact_check(txt); await update.message.reply_text(ans); return

    # text→video
    if ("сделай видео" in txt.lower()) or (" видео " in f" {txt.lower()} ") and any(r in txt for r in ("9:16","16:9","1:1")):
        dur, ar = parse_duration_and_ratio(txt)
        await update.message.reply_text(f"Видео {dur}s • {ar}\nВыберите движок:", reply_markup=engines_kb())
        context.user_data["pending_text2video"] = {"prompt": txt, "dur": dur, "ar": ar}
        return

    # позитивный ответ на «можешь ли ты … с фото?»
    if any(k in txt.lower() for k in ["можешь","умеешь","можно ли","сможешь"]) and any(p in txt.lower() for p in PHOTO_POSITIVE_PATTERNS):
        await update.message.reply_text(
            "Да, поддерживаю это 👍\nПришли фото — и я предложу быстрые действия: оживить (Image→Video), удалить/заменить фон, добавить/удалить объект, ретушь/апскейл, аватар/логотип."
        )
        return

    # обычный чат
    reply = await ai_chat([
        {"role": "system", "content": "Ты — лаконичный и доброжелательный помощник по ИИ-боту."},
        {"role": "user", "content": txt},
    ])
    await maybe_tts_answer(update, context, reply, user)

async def maybe_tts_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, reply_text: str, user: dict):
    await update.message.reply_text(reply_text)
    if user.get("voice_on"):
        ogg = await ai_tts_ogg(reply_text, user.get("tts_voice") or OPENAI_TTS_VOICE)
        if ogg: await context.bot.send_voice(update.effective_chat.id, ogg)

@chat_action(ChatAction.RECORD_AUDIO)
async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user)
    v = update.message.voice or update.message.audio
    if not v: await update.message.reply_text("Не нашёл аудио."); return
    f = await context.bot.get_file(v.file_id)
    bio = BytesIO(); await f.download_to_memory(bio)
    text = await ai_stt_ogg(bio.getvalue())
    if not text: await update.message.reply_text("Не удалось распознать речь."); return
    await update.message.reply_text(f"🗣️ Распознано: {text}")
    update.message.text = text
    await on_text(update, context)

@chat_action(ChatAction.UPLOAD_PHOTO)
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user)
    photo = update.message.photo[-1] if update.message.photo else None
    if not photo: await update.message.reply_text("Фото не получено."); return
    f = await context.bot.get_file(photo.file_id)
    bio = BytesIO(); await f.download_to_memory(bio)
    img = bio.getvalue()
    cap = update.message.caption or ""

    context.user_data["last_photo"] = img
    context.user_data["last_caption"] = cap

    txt = "Фото получено."
    if cap and is_photo_positive(cap):
        txt += f"\n💡 Из подписи понял: «{shorten(cap, 60)}». Готов выполнить."
    txt += "\nВыбери действие:"
    await update.message.reply_text(txt, reply_markup=photo_actions_kb())

@chat_action(ChatAction.TYPING)
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user)
    doc = update.message.document
    if not doc: await update.message.reply_text("Документ не найден."); return
    f = await context.bot.get_file(doc.file_id)
    bio = BytesIO(); await f.download_to_memory(bio)
    data = bio.getvalue()
    name = (doc.file_name or "").lower()

    text = ""
    try:
        if name.endswith(".pdf"):
            p = "/tmp/in.pdf"; open(p,"wb").write(data); text = pdf_extract_text(p) or ""
        elif name.endswith(".docx"):
            p = "/tmp/in.docx"; open(p,"wb").write(data); d=DocxDocument(p); text="\n".join([p.text for p in d.paragraphs if p.text.strip()])
        elif name.endswith(".epub"):
            p = "/tmp/in.epub"; open(p,"wb").write(data); book = epub.read_epub(p)
            chunks=[]; 
            for item in book.get_items():
                if item.get_type()==epub.ITEM_DOCUMENT:
                    with contextlib.suppress(Exception):
                        chunks.append(item.get_content().decode("utf-8","ignore"))
            import re as _re
            text = _re.sub(r"<[^>]+>","", "\n".join(chunks))
        else:
            await update.message.reply_text("Поддерживаю PDF, DOCX, EPUB."); return
    except Exception:
        log.exception("doc parse"); await update.message.reply_text("Не удалось извлечь текст."); return

    if not text.strip(): await update.message.reply_text("Пустой документ или не распознался."); return

    reply = await ai_chat([
        {"role":"system","content":"Суммируй документ кратко и структурно в 10 пунктов, выдели факты и цифры."},
        {"role":"user","content":text[:12000]},
    ])
    await update.message.reply_text("Тезисы:\n" + reply)

# ──────────────────────────────────────────────────────────────────────────────
# CallbackQuery (движки, действия с фото, выбор VR)
# ──────────────────────────────────────────────────────────────────────────────

@chat_action(ChatAction.TYPING)
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    user = get_user(q.from_user.id)

    # Выбор движка для text→video
    if data in ("engine_luma","engine_runway"):
        engine = "luma" if data == "engine_luma" else "runway"
        pending = context.user_data.get("pending_text2video")
        if not pending:
            await q.edit_message_text("Нет ожидающей задачи. Отправь текст с параметрами и попробуй снова.")
            return
        prompt, dur, ar = pending["prompt"], pending["dur"], pending["ar"]
        await q.edit_message_text(f"Видео {dur}s • {ar}\nДвижок: {engine.capitalize()}\nЗапускаю…")
        try:
            if engine == "luma": js = await luma_text2video(prompt, dur, ar)
            else: js = await runway_text2video(prompt, dur, ar)
            jid = _enqueue_job(q.from_user.id, "text2video", engine, {"prompt":prompt,"dur":dur,"ar":ar})
            _update_job(jid, "running", {"provider_job": js})
            asyncio.create_task(poll_and_send_video(update, context, engine, js, jid))
        except Exception:
            log.exception("text2video")
            await context.bot.send_message(q.message.chat_id, f"❌ Ошибка {engine.capitalize()} при генерации видео.")
        return

    # Выбор длительности/соотношения для image→video
    if data.startswith("vr_"):
        _, d, ar = data.split("_")
        d = int(d)
        ar = ar.replace("16x9","16:9").replace("9x16","9:16").replace("1x1","1:1")
        context.user_data["vr"] = {"dur": d, "ar": ar}
        await q.edit_message_text(f"Видео {d}s • {ar}\nВыберите движок:", reply_markup=engines_kb())
        context.user_data["await_engine_for_image2video"] = True
        return

    # Действия с фото
    if data == "act_bg_remove":
        img = context.user_data.get("last_photo")
        if not img: await q.edit_message_text("Сначала пришли фото."); return
        try:
            out = remove_bg(img)
            await context.bot.send_photo(q.message.chat_id, bytes_to_inputfile(out, "no_bg.png"), caption="Фон удалён.")
        except Exception as e:
            await context.bot.send_message(q.message.chat_id, f"Ошибка удаления фона: {e}")
        return

    if data == "act_bg_replace":
        img = context.user_data.get("last_photo")
        if not img: await q.edit_message_text("Сначала пришли фото."); return
        out = replace_bg(img, (255,255,255))
        await context.bot.send_photo(q.message.chat_id, bytes_to_inputfile(out, "white_bg.png"), caption="Фон заменён на белый.")
        return

    if data == "act_upscale":
        img = context.user_data.get("last_photo")
        if not img: await q.edit_message_text("Сначала пришли фото."); return
        out = upscale_x2(img)
        await context.bot.send_photo(q.message.chat_id, bytes_to_inputfile(out, "upscaled.png"), caption="Апскейл ×2 выполнен.")
        return

    if data in ("act_add_object","act_remove_object","act_avatar"):
        await q.edit_message_text("Опиши, что добавить/удалить (и где). Я применю инпейтинг и пришлю результат.")
        context.user_data["await_inpaint_prompt"] = data
        return

    if data == "act_image2video":
        await q.edit_message_text("Выбери длительность и соотношение сторон:", reply_markup=vr_kb())
        return

@chat_action(ChatAction.TYPING)
async def on_inpaint_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("await_inpaint_prompt")
    if not mode: return
    prompt = update.message.text.strip()
    img = context.user_data.get("last_photo")
    if not img:
        await update.message.reply_text("Сначала пришли фото.")
        context.user_data["await_inpaint_prompt"] = None
        return
    try:
        edited = await ai_image_edit(img, prompt, None)  # без маски — на текстовой подсказке
        await update.message.reply_photo(bytes_to_inputfile(edited,"edited.png"), caption="Готово.")
    except Exception as e:
        await update.message.reply_text(f"Не удалось выполнить правку: {e}")
    finally:
        context.user_data["await_inpaint_prompt"] = None

# ──────────────────────────────────────────────────────────────────────────────
# Факт-чек
# ──────────────────────────────────────────────────────────────────────────────

async def fact_check(question: str) -> str:
    if not TAVILY_API_KEY:
        return "Для факт-чека задай TAVILY_API_KEY."
    try:
        tv = TavilyClient(api_key=TAVILY_API_KEY)
        res = await asyncio.to_thread(tv.search, query=question, max_results=5, search_depth="advanced")
        bullets = []
        for r in res.get("results", []):
            title = r.get("title") or "Источник"
            url = r.get("url") or ""
            bullets.append(f"• {title} — {url}")
        return "Источники:\n" + ("\n".join(bullets) if bullets else "ничего не найдено")
    except Exception as e:
        log.exception("tavily"); return f"Ошибка поиска: {e}"

# ──────────────────────────────────────────────────────────────────────────────
# Сборка и запуск
# ──────────────────────────────────────────────────────────────────────────────

def build_app():
    if not BOT_TOKEN:
        raise RuntimeError("Задай TELEGRAM_BOT_TOKEN / BOT_TOKEN")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("modes", cmd_modes))
    app.add_handler(CommandHandler("examples", cmd_examples))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("engines", cmd_engines))
    app.add_handler(CommandHandler("voice_on", cmd_voice_on))
    app.add_handler(CommandHandler("voice_off", cmd_voice_off))
    app.add_handler(CommandHandler("topup", cmd_topup))
    app.add_handler(CommandHandler("getinvoices", cmd_check_invoices))

    # callbacks
    app.add_handler(CallbackQueryHandler(on_cb))

    # сообщения
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_router))

    return app

def main():
    log.info("Starting bot…")
    db_init()
    app = build_app()
    # polling, на Render как worker
    with contextlib.suppress(Exception):
        asyncio.get_event_loop().run_until_complete(app.bot.delete_webhook(drop_pending_updates=False))
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
