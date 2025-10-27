# -*- coding: utf-8 -*-
import os
import re
import json
import time
import base64
import logging
from io import BytesIO
import asyncio
import sqlite3
from datetime import datetime, timedelta

import httpx
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InputFile,
    LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters,
    PreCheckoutQueryHandler, CallbackQueryHandler
)
from telegram.constants import ChatAction

# -------- LOGGING --------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")

# -------- ENV --------
BOT_TOKEN        = os.environ.get("BOT_TOKEN", "").strip()
BOT_USERNAME     = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
PUBLIC_URL       = os.environ.get("PUBLIC_URL", "").strip()
WEBAPP_URL       = os.environ.get("WEBAPP_URL", "").strip()
OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL  = os.environ.get("OPENAI_BASE_URL", "").strip()
OPENAI_MODEL     = os.environ.get("OPENAI_MODEL", "openai/gpt-4o-mini").strip()

OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "").strip()
OPENROUTER_API_KEY  = os.environ.get("OPENROUTER_API_KEY", "").strip()

WEBHOOK_SECRET   = os.environ.get("WEBHOOK_SECRET", "").strip()
BANNER_URL       = os.environ.get("BANNER_URL", "").strip()
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "").strip()

# STT:
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "").strip()
OPENAI_STT_KEY   = os.environ.get("OPENAI_STT_KEY", "").strip()
TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1").strip()

# Media (Images / Video):
OPENAI_IMAGE_KEY = os.environ.get("OPENAI_IMAGE_KEY", "").strip() or OPENAI_API_KEY

# Runway (параметризовано)
RUNWAY_API_KEY      = os.environ.get("RUNWAY_API_KEY", "").strip()
RUNWAY_MODEL        = os.environ.get("RUNWAY_MODEL", "veo3").strip()
RUNWAY_RATIO        = os.environ.get("RUNWAY_RATIO", "720:1280").strip()
RUNWAY_DURATION_S   = int(os.environ.get("RUNWAY_DURATION_S", "8"))

# Premium whitelist для Runway
PREMIUM_USER_IDS = set(
    int(x) for x in os.environ.get("PREMIUM_USER_IDS", "").split(",") if x.strip().isdigit()
)

# >>> LUMA
LUMA_API_KEY     = os.environ.get("LUMA_API_KEY", "").strip()
LUMA_MODEL       = os.environ.get("LUMA_MODEL", "ray-2").strip()
LUMA_ASPECT      = os.environ.get("LUMA_ASPECT", "16:9").strip()
LUMA_DURATION_S  = int(os.environ.get("LUMA_DURATION_S", "6"))

# ====== PAYMENTS (ЮKassa via Telegram Payments) ======
PROVIDER_TOKEN = os.environ.get("PROVIDER_TOKEN_YOOKASSA", "").strip()
CURRENCY       = "RUB"
DB_PATH        = os.environ.get("DB_PATH", "subs.db")

# --- тарифы и цены (руб) ---
PLAN_PRICE_TABLE = {
    "start":    {"month": 499,  "quarter": 1299, "year": 4490},
    "pro":      {"month": 999,  "quarter": 2799, "year": 8490},
    "ultimate": {"month": 1999, "quarter": 5490, "year": 15990},
}
TERM_MONTHS = {"month": 1, "quarter": 3, "year": 12}

PORT = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")
if not OPENAI_API_KEY:
    raise RuntimeError("ENV OPENAI_API_KEY is missing")

# --------- URL мини-приложения тарифов ---------
def _make_tariff_url(src: str = "subscribe") -> str:
    base = (WEBAPP_URL or f"{PUBLIC_URL.rstrip('/')}/premium.html").strip()
    if src:
        sep = "&" if "?" in base else "?"
        base = f"{base}{sep}src={src}"
    if BOT_USERNAME:
        sep = "&" if "?" in base else "?"
        base = f"{base}{sep}bot={BOT_USERNAME}"
    return base

# URL для кнопки «⭐ Подписка» (из чата)
TARIFF_URL = _make_tariff_url("subscribe")

# -------- OPENAI / Tavily --------
from openai import OpenAI

def _ascii_or_none(s: str | None):
    if not s:
        return None
    try:
        s.encode("ascii")
        return s
    except Exception:
        # в HTTP заголовках можно только ASCII — кириллицу отбрасываем
        return None

_auto_base = OPENAI_BASE_URL
if not _auto_base and OPENAI_API_KEY.startswith("sk-or-"):
    _auto_base = "https://openrouter.ai/api/v1"
    log.info("Auto-select OpenRouter base_url for text LLM.")

# Заголовки только ASCII (иначе httpx кинет ascii/latin1 error)
default_headers = {}
ref = _ascii_or_none(os.environ.get("OPENROUTER_SITE_URL", "").strip())
ttl = _ascii_or_none(os.environ.get("OPENROUTER_APP_NAME", "").strip())
if ref:
    default_headers["HTTP-Referer"] = ref
if ttl:
    default_headers["X-Title"] = ttl

# Текст/визуал (LLM) — как было
oai_llm = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=_auto_base or None,
    default_headers=default_headers or None,
)

oai_stt = OpenAI(api_key=OPENAI_STT_KEY) if OPENAI_STT_KEY else None

# === Images: ВСЕГДА OpenAI (или ваш прокси), т.к. на OpenRouter модели нет ===
# Если хостинг не пускает к api.openai.com — укажите прокси в ENV:
#   OPENAI_IMAGE_BASE_URL=https://<ваш-домен>/v1
IMAGES_BASE_URL = (os.environ.get("OPENAI_IMAGE_BASE_URL", "").strip()
                   or "https://api.openai.com/v1")
IMAGES_MODEL = "gpt-image-1"

oai_img = OpenAI(
    api_key=(os.environ.get("OPENAI_IMAGE_KEY", "").strip() or OPENAI_API_KEY),
    base_url=IMAGES_BASE_URL,
)
# Tavily
try:
    if TAVILY_API_KEY:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
    else:
        tavily = None
except Exception:
    tavily = None

# ================== PAYMENTS: DB & HELPERS ==================
def db_init():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER PRIMARY KEY,
        until_ts INTEGER NOT NULL
    )
    """)
    con.commit()
    con.close()

def activate_subscription(user_id: int, months: int = 1):
    now = datetime.utcnow()
    until = now + timedelta(days=30 * months)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT until_ts FROM subscriptions WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row and row[0] and row[0] > int(now.timestamp()):
        current_until = datetime.utcfromtimestamp(row[0])
        until = current_until + timedelta(days=30 * months)
    cur.execute("""
        INSERT INTO subscriptions (user_id, until_ts)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET until_ts=excluded.until_ts
    """, (user_id, int(until.timestamp())))
    con.commit()
    con.close()
    return until

def get_subscription_until(user_id: int):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT until_ts FROM subscriptions WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    con.close()
    if not row:
        return None
    return datetime.utcfromtimestamp(row[0])

def is_active(user_id: int) -> bool:
    until = get_subscription_until(user_id)
    return bool(until and until > datetime.utcnow())

# -------- PROMPTS --------
SYSTEM_PROMPT = (
    "Ты дружелюбный и лаконичный ассистент на русском. "
    "Отвечай по сути, структурируй списками/шагами, не выдумывай факты. "
    "Если ссылаешься на источники — в конце дай короткий список ссылок."
)
VISION_SYSTEM_PROMPT = (
    "Ты чётко описываешь содержимое изображений: объекты, текст, схемы, графики. "
    "Не идентифицируй личности людей и не пиши имена, если они не напечатаны на изображении."
)

# -------- HEURISTICS --------
_SMALLTALK_RE = re.compile(
    r"^(привет|здравствуй|добрый\s*(день|вечер|утро)|хи|hi|hello|хелло|как дела|спасибо|пока)\b",
    re.IGNORECASE
)
_NEWSY_RE = re.compile(
    r"(когда|дата|выйдет|релиз|новост|курс|цена|прогноз|что такое|кто такой|найди|ссылка|официал|адрес|телефон|"
    r"погода|сегодня|сейчас|штраф|закон|тренд|котировк|обзор|расписани|запуск|update|новая версия)",
    re.IGNORECASE
)
_CAPABILITY_RE = re.compile(
    r"(мож(ешь|но).{0,10}(анализ(ировать)?|распознав(ать|ание)).{0,10}(фото|картинк|изображен|image|picture)|"
    r"анализ(ировать)?.{0,8}(фото|картинк|изображен)|"
    r"(мож(ешь|но).{0,10})?(анализ|работать).{0,6}с.{0,6}видео)",
    re.IGNORECASE
)

# === INTENT (unified) ===
_IMG_WORDS = (
    r"(картин\w+|изображен\w+|фото\w*|фотк\w*|рисунк\w+|арт\w*|аватар\w*|"
    r"логотип\w+|иконк\w+|обложк\w*|постер\w*|баннер\w*|обои\w*|мем\w*|стикер\w*|"
    r"image|picture|img\b|logo|icon|banner|poster|wallpaper|sticker|meme)"
)
_VID_WORDS = (
    r"(видео|видос\w*|ролик\w*|клип\w*|анимаци\w*|шортс\w*|shorts?|"
    r"рилс\w*|reels?|сторис\w*|stories?|clip|video|vid\b)"
)
_VERBS = (
    r"(сдела\w+|созда\w+|сгенерир\w+|нарис\w+|сформир\w+|"
    r"собер\w+|сним\w+|смонтир\w+|хочу|нужно|надо|please|make|generate|create|render|produce)"
)
_PREFIXES_VIDEO = [
    r"^созда\w*\s+видео", r"^сдела\w*\s+видео", r"^сгенерир\w*\s+видео",
    r"^сним\w*\s+видео", r"^смонтир\w*\s+видео",
    r"^video\b", r"^vid\b", r"^reel[s]?\b", r"^shorts?\b", r"^stories?\b"
]
_PREFIXES_IMAGE = [
    r"^созда\w*\s+(?:картин\w+|изображен\w+|фото\w*|рисунк\w+)",
    r"^сдела\w*\s+(?:картин\w+|изображен\w+|фото\w*|рисунк\w+)",
    r"^сгенерир\w*\s+(?:картин\w+|изображен\w+|фото\w*|рисунк\w+)",
    r"^нарис\w*\s+(?:картин\w+|изображен\w+|рисунк\w+)",
    r"^image\b", r"^picture\b", r"^img\b"
]
def _strip_leading(s: str) -> str:
    return s.strip(" \n\t:—–-\"“”'«»,.()[]")
def _after_match(text: str, match) -> str:
    return _strip_leading(text[match.end():])
def detect_media_intent(text: str):
    if not text:
        return None, ""
    t = text.strip()
    tl = t.lower()
    for p in _PREFIXES_VIDEO:
        m = re.search(p, tl, flags=re.IGNORECASE)
        if m:
            return "video", _after_match(t, m)
    for p in _PREFIXES_IMAGE:
        m = re.search(p, tl, flags=re.IGNORECASE)
        if m:
            return "image", _after_match(t, m)
    if re.search(r"(можешь|можно|сможешь)", tl) and re.search(_VERBS, tl):
        if re.search(_VID_WORDS, tl):
            tmp = re.sub(r"(ты|вы)?\s*(можешь|можно|сможешь)\s*", "", tl)
            tmp = re.sub(_VID_WORDS, "", tmp)
            tmp = re.sub(_VERBS, "", tmp)
            return "video", _strip_leading(tmp)
        if re.search(_IMG_WORDS, tl):
            tmp = re.sub(r"(ты|вы)?\s*(можешь|можно|сможешь)\s*", "", tl)
            tmp = re.sub(_IMG_WORDS, "", tmp)
            tmp = re.sub(_VERBS, "", tmp)
            return "image", _strip_leading(tmp)
    if re.search(_VID_WORDS, tl) and re.search(_VERBS, tl):
        tmp = re.sub(_VID_WORDS, "", tl)
        tmp = re.sub(_VERBS, "", tmp)
        return "video", _strip_leading(tmp)
    if re.search(_IMG_WORDS, tl) and re.search(_VERBS, tl):
        tmp = re.sub(_IMG_WORDS, "", tl)
        tmp = re.sub(_VERBS, "", tmp)
        return "image", _strip_leading(tmp)
    m = re.match(r"^(video|vid|reels?|shorts?|stories?)\s*[:\-]\s*(.+)$", tl)
    if m:
        return "video", _strip_leading(t[m.end(1)+1:])
    m = re.match(r"^(img|image|picture)\s*[:\-]\s*(.+)$", tl)
    if m:
        return "image", _strip_leading(t[m.end(1)+1:])
    return None, ""

def is_smalltalk(text: str) -> bool:
    return bool(_SMALLTALK_RE.search(text.strip()))
def should_browse(text: str) -> bool:
    t = text.strip()
    if is_smalltalk(t):
        return False
    return bool(_NEWSY_RE.search(t) or "?" in t or len(t) > 80)
def is_vision_capability_question(text: str) -> bool:
    return bool(_CAPABILITY_RE.search(text))

# === B: ROUTER & HANDLERS ===============================================

OPENROUTER_BASE_URL  = "https://openrouter.ai/api/v1"

def _has_openrouter() -> bool:
    bul = (OPENAI_BASE_URL or "").lower()
    return bool(
        OPENROUTER_API_KEY
        or OPENAI_API_KEY.startswith("sk-or-")
        or ("openrouter" in bul)
    )

async def _ask_text_via_openrouter(user_text: str, web_ctx: str = "") -> str | None:
    if not _has_openrouter():
        return None
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY or OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    # !!! важная правка: только ASCII в заголовках
    ref = _ascii_or_none(os.environ.get("OPENROUTER_SITE_URL", "").strip())
    ttl = _ascii_or_none(os.environ.get("OPENROUTER_APP_NAME", "").strip())
    if ref:
        headers["HTTP-Referer"] = ref
    if ttl:
        headers["X-Title"] = ttl

    model = os.environ.get("OPENROUTER_TEXT_MODEL", "").strip() or "openrouter/auto"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({"role": "system", "content": f"Контекст из веб-поиска:\n{web_ctx}"})
    messages.append({"role": "user", "content": user_text})

    payload = {"model": model, "messages": messages, "temperature": 0.6}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        log.exception("OpenRouter text error: %s", e)
        return None

async def _handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, web_ctx: str = "", sources=None):
    reply = await _ask_text_via_openrouter(text, web_ctx=web_ctx)
    if not reply:
        reply = await ask_openai_text(text, web_ctx=web_ctx)
    if sources:
        reply += "\n\n" + "\n".join([f"[{i+1}] {s.get('title','')} — {s.get('url','')}" for i, s in enumerate(sources)])
    await update.message.reply_text(reply, disable_web_page_preview=False)

async def _handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    await _call_handler_with_prompt(cmd_img, update, context, prompt)

def _video_suggestion_text(prompt: str, dur: int | None = None, ar: str | None = None, is_pro: bool = False) -> str:
    dur_s = f"{dur}s" if dur else f"{LUMA_DURATION_S}s"
    ar_s  = ar or LUMA_ASPECT or "9:16"
    pro_line = "Runway — только на PRO." if not is_pro else "Runway доступен (PRO)."
    p = prompt.strip() or "закат над морем, дрон, тёплые цвета"
    return (
        "🎬 Я не генерирую видео прямо в GPT-режиме, но помогу запустить в подходящем движке:\n\n"
        "• Короткие ролики — **Luma** (экономнее)\n"
        f"• Студийные/длинные — **Runway** ({pro_line})\n\n"
        "Готовые команды:\n"
        f"• Luma: `/video_luma {p} {dur_s} {ar_s}`\n"
        f"• Runway: `/video {p}`\n\n"
        "Или открой «🧭 Меню движков» и выбери Luma/Runway."
    )

def _video_choice_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Luma (короткие клипы)", callback_data="video_choose_luma")],
        [InlineKeyboardButton("🎥 Runway (PRO, студийное)", callback_data="video_choose_runway")],
    ])

async def suggest_video_engines(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, dur: int, ar: str):
    context.user_data["pending_video"] = {"prompt": prompt, "dur": dur, "ar": ar}
    text = (
        "Я сам видео не рендерю в этом режиме. Выбери движок:\n\n"
        "• 🎬 *Luma* — быстрые ролики 3–10s\n"
        "• 🎥 *Runway* — качественно, дороже (PRO)\n\n"
        "Нажми кнопку ниже — запущу генерацию."
    )
    await update.effective_message.reply_text(text, reply_markup=_video_choice_kb(), disable_web_page_preview=True, parse_mode="Markdown")

async def _handle_video_request(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    dur, ar, clean = parse_video_opts_from_text(prompt)
    eng = context.user_data.get("engine")
    if eng == ENGINE_LUMA:
        context.args = [clean]
        await cmd_make_video_luma(update, context); return
    if eng == ENGINE_RUNWAY:
        await _call_handler_with_prompt(cmd_make_video, update, context, clean); return
    is_pro = update.effective_user.id in PREMIUM_USER_IDS
    await update.message.reply_text(_video_suggestion_text(clean, dur, ar, is_pro))

async def on_video_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    stash = context.user_data.get("pending_video") or {}
    prompt = stash.get("prompt", "")
    if not prompt:
        await q.edit_message_text("Не нашёл ваш запрос. Напишите «создай видео …»."); return
    if data == "video_choose_luma":
        context.args = [prompt]
        await cmd_make_video_luma(update, context)
    elif data == "video_choose_runway":
        await _call_handler_with_prompt(cmd_make_video, update, context, prompt)

async def route_and_handle_textlike(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, web_ctx: str = "", sources=None):
    kind, payload = detect_media_intent(text)
    eng = context.user_data.get("engine")
    if kind == "image":
        if eng == ENGINE_MJ:
            mj = f"/imagine prompt: {payload or text} --ar 3:2 --stylize 250 --v 6.0"
            await update.message.reply_text(f"🖼 Midjourney промпт:\n{mj}")
            return
        await _handle_image(update, context, payload or text)
        return
    if kind == "video":
        await _handle_video_request(update, context, payload or text)
        return
    await _handle_text(update, context, text, web_ctx=web_ctx, sources=sources)

# -------- UTILS --------
async def typing(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        await ctx.bot.send_chat_action(chat_id, action=ChatAction.TYPING)
    except Exception:
        pass

def sniff_image_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8"): return "image/jpeg"
    if data.startswith(b"\x89PNG"):  return "image/png"
    if data[:4] == b"RIFF" and b"WEBP" in data[:16]: return "image/webp"
    return "image/jpeg"

def tavily_search(query: str, max_results: int = 5):
    if not tavily: return None, []
    try:
        res = tavily.search(
            query=query, search_depth="advanced", max_results=max_results,
            include_answer=True, include_raw_content=False,
        )
        answer = res.get("answer") or ""
        results = res.get("results") or []
        return answer, results
    except Exception as e:
        log.exception("Tavily error: %s", e)
        return None, []

# -------- OpenAI helpers --------
async def ask_openai_text(user_text: str, web_ctx: str = "") -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({"role": "system", "content": f"Контекст из веб-поиска:\n{web_ctx}"})
    messages.append({"role": "user", "content": user_text})
    try:
        resp = oai_llm.chat.completions.create(
            model=OPENAI_MODEL, messages=messages, temperature=0.6,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("OpenAI chat error: %s", e)
        return "Не удалось получить ответ от модели (лимит/ключ). Попробуй позже."

async def ask_openai_vision(user_text: str, img_b64: str, mime: str) -> str:
    try:
        resp = oai_llm.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": user_text or "Опиши, что на изображении и какой там текст."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}}
                ]}
            ],
            temperature=0.4,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("Vision error: %s", e)
        return "Не удалось проанализировать изображение (лимит/ключ). Попробуй позже."

# -------- STT --------
async def transcribe_audio(buf: BytesIO, filename_hint: str = "audio.ogg") -> str:
    data = buf.getvalue()
    if DEEPGRAM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                params = {"model": "nova-2", "language": "ru", "smart_format": "true", "punctuate": "true"}
                headers = {
                    "Authorization": f"Token {DEEPGRAM_API_KEY}",
                    "Content-Type": "audio/ogg" if filename_hint.endswith(".ogg") else "application/octet-stream",
                }
                r = await client.post("https://api.deepgram.com/v1/listen", params=params, headers=headers, content=data)
                r.raise_for_status()
                dg = r.json()
                text = (dg.get("results",{}).get("channels",[{}])[0].get("alternatives",[{}])[0].get("transcript","")).strip()
                if text: return text
        except Exception as e:
            log.exception("Deepgram STT error: %s", e)
    if oai_stt:
        try:
            buf2 = BytesIO(data); buf2.seek(0); setattr(buf2,"name",filename_hint)
            tr = oai_stt.audio.transcriptions.create(model=TRANSCRIBE_MODEL, file=buf2)
            return (tr.text or "").strip()
        except Exception as e:
            log.exception("Whisper STT error: %s", e)
    return ""

# -------- IMAGES (/img) --------
async def cmd_diag_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key_env = os.environ.get("OPENAI_IMAGE_KEY", "").strip()
    key_used = key_env or OPENAI_API_KEY
    base = IMAGES_BASE_URL
    lines = [
        f"OPENAI_IMAGE_KEY: {'✅ найден' if key_used else '❌ нет'}",
        f"BASE_URL: {base}",
        f"MODEL: {IMAGES_MODEL}",
    ]
    if "openrouter" in base.lower():
        lines.append("⚠️ BASE_URL указывает на OpenRouter — там нет gpt-image-1.")
        lines.append("   Поставь https://api.openai.com/v1 или свой прокси в OPENAI_IMAGE_BASE_URL.")
    await update.message.reply_text("\n".join(lines))
    return


async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip() if context.args else ""
    if not prompt:
        await update.effective_message.reply_text(
            "Напиши так: «/img Земля из космоса, реалистично, 4k»"
        )
        return
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        resp = oai_img.images.generate(
            model=IMAGES_MODEL,
            prompt=prompt,
            size="1024x1024",
            n=1
        )
        b64 = resp.data[0].b64_json
        img_bytes = base64.b64decode(b64)
        await update.effective_message.reply_photo(
            photo=img_bytes,
            caption=f"Готово ✅\nЗапрос: {prompt}"
        )
    except Exception as e:
        msg = str(e)
        log.exception("Images API error: %s", e)
        low = msg.lower()
        hint = []
        hint.append(f"База: {IMAGES_BASE_URL}")
        hint.append(f"Модель: {IMAGES_MODEL}")
        if "unauthorized" in low or "401" in low or "invalid_api_key" in low:
            hint.append("Проверь OPENAI_IMAGE_KEY (или OPENAI_API_KEY): действующий ключ без пробелов.")
        elif "insufficient_quota" in low or "billing" in low or "credit" in low:
            hint.append("Похоже на исчерпанный баланс/квоты в OpenAI.")
        elif "connection" in low or "timed out" in low or "name or service not known" in low:
            hint.append("Сетевая ошибка. Если хостинг блокирует api.openai.com — укажи "
                        "OPENAI_IMAGE_BASE_URL с прокси (напр., Cloudflare Worker).")
        elif "model" in low and "not found" in low:
            hint.append("gpt-image-1 доступна только на OpenAI/прокси, не на OpenRouter.")
        elif "ascii" in low or "latin-1" in low:
            hint.append("В HTTP заголовках только ASCII. Проверь OPENROUTER_APP_NAME / HTTP-Referer.")
        await update.effective_message.reply_text(
            "⚠️ Не удалось создать изображение:\n" + msg + "\n\n" + "\n".join(hint)
        )

# -------- VIDEO (Runway SDK) --------
if RUNWAY_API_KEY:
    os.environ["RUNWAY_API_KEY"] = RUNWAY_API_KEY

# безопасный импорт runwayml
RUNWAY_SDK_OK = True
RUNWAY_IMPORT_ERROR = None
try:
    from runwayml import RunwayML
except Exception as _e:
    RUNWAY_SDK_OK = False
    RUNWAY_IMPORT_ERROR = _e

def _runway_make_video_sync(prompt: str, duration: int = None) -> bytes:
    if not RUNWAY_API_KEY:
        raise RuntimeError("RUNWAY_API_KEY не задан")
    if not RUNWAY_SDK_OK:
        raise RuntimeError(f"runwayml не установлен/не импортируется: {RUNWAY_IMPORT_ERROR}")
    client = RunwayML(api_key=RUNWAY_API_KEY)
    task = client.text_to_video.create(
        prompt_text=prompt,
        model=RUNWAY_MODEL,
        ratio=RUNWAY_RATIO,
        duration=(duration if duration is not None else RUNWAY_DURATION_S),
    )
    task_id = task.id
    time.sleep(1)
    task = client.tasks.retrieve(task_id)
    while task.status not in ["SUCCEEDED", "FAILED"]:
        time.sleep(1)
        task = client.tasks.retrieve(task_id)
    if task.status != "SUCCEEDED":
        raise RuntimeError(getattr(task, "error", None) or f"Runway task failed: {task.status}")
    output = getattr(task, "output", None)
    if isinstance(output, list) and output:
        video_url = output[0]
    elif isinstance(output, dict):
        video_url = output.get("url") or output.get("video_url")
    else:
        raise RuntimeError(f"Runway: не найден URL результата в output: {output}")
    with httpx.Client(timeout=None) as http:
        r = http.get(video_url)
        r.raise_for_status()
        return r.content

async def cmd_make_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in PREMIUM_USER_IDS:
        await update.effective_message.reply_text("⚠️ Runway сейчас доступен на PRO-тарифе.")
        return
    if not RUNWAY_SDK_OK:
        await update.effective_message.reply_text("⚠️ Пакет runwayml не найден. Установите `pip install runwayml` и перезапустите бота.")
        return
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.effective_message.reply_text("Напиши так: /video закат на Самуи, дрон, тёплые цвета")
        return
    await update.effective_message.reply_text(f"🎬 Генерирую видео через Runway… ({RUNWAY_MODEL}, {RUNWAY_RATIO})")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)
    try:
        video_bytes = await asyncio.to_thread(_runway_make_video_sync, prompt, RUNWAY_DURATION_S)
        await update.effective_message.reply_video(video=video_bytes, supports_streaming=True, caption=f"Готово 🎥\n{prompt}")
    except Exception as e:
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg:
            hint = (
                "Похоже, ключ не принимается API (401).\n"
                "Проверь ключ на dev.runwayml.com → API Keys (формат key_...), "
                "ENV RUNWAY_API_KEY и redeploy."
            )
            await update.effective_message.reply_text(f"⚠️ Видео не удалось (401): проверь ключ.\n\n{hint}")
        elif "credit" in msg.lower():
            await update.effective_message.reply_text("⚠️ Недостаточно кредитов Runway.")
        else:
            await update.effective_message.reply_text(f"⚠️ Видео не удалось: {e}")
        log.exception("Runway video error: %s", e)

# >>> LUMA
# === LUMA DURATION PARSER — START =====================================
# Понимаем 1–10 секунд в цифрах/словах и приводим к допустимым Luma значениям.
# Разрешённые длительности Luma на сегодня: 5s, 9s, 10s.
_ALLOWED_LUMA_DURS = (5, 9, 10)

# Число + "сек"/"секунд"/"s"/"sec"/"seconds" (учитываем латинскую s и кириллицу с)
_DURATION_NUM_RE = re.compile(
    r"""
    (?P<prefix>\b(?:на|в|около)?\s*)?                # необязательная приставка "на 6 сек"
    (?P<num>\d+(?:[.,]\d+)?)                         # число (возможна десятичная)
    \s*[-]?\s*
    (?:
        s(?:ec(?:onds?)?)?                           # s / sec / seconds
        |                                             # или русские формы:
        с|сек(?:\.|ун(?:д(?:а|ы|у|ам|ами|ах)?)?)?     # "с" (кирилл.), "сек", "сек.", "секунд", ...
    )
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Слова-числа (ru/en) + единицы времени
_WORD2NUM_RU = {
    "один":1, "одна":1, "раз":1,
    "два":2, "две":2,
    "три":3, "четыре":4, "пять":5, "шесть":6,
    "семь":7, "восемь":8, "девять":9, "десять":10,
}
_WORD2NUM_EN = {
    "one":1, "two":2, "three":3, "four":4, "five":5,
    "six":6, "seven":7, "eight":8, "nine":9, "ten":10,
}
_WORD_RE_SRC = (
    r"(?:"
    + "|".join(sorted(list(_WORD2NUM_RU.keys()) + list(_WORD2NUM_EN.keys()), key=len, reverse=True))
    + r")"
)
_DURATION_WORD_RE = re.compile(
    rf"""
    (?P<prefix>\b(?:на|в|около)?\s*)?     # "на десять секунд"
    (?P<word>{_WORD_RE_SRC})\s*
    (?:
        s(?:ec(?:onds?)?)?
        |с|сек(?:\.|ун(?:д(?:а|ы|у|ам|ами|ах)?)?)?
        |seconds?
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Соотношения сторон как раньше
_AR_RE = re.compile(r"\b(16:9|9:16|4:3|3:4|1:1|21:9|9:21)\b", re.I)

def _snap_to_luma_allowed(x: int) -> int:
    """Берём ближайшее из (5,9,10). При равенстве — вверх."""
    best = min(_ALLOWED_LUMA_DURS, key=lambda a: (abs(a - x), -a))
    return best

def _extract_duration_seconds(t: str) -> tuple[int | None, tuple[int, int] | None]:
    """Пытаемся вытащить длительность (секунды) и вернуть (secs, span) либо (None, None)."""
    tl = t.lower()

    # Вариант: цифры + единицы
    m = _DURATION_NUM_RE.search(tl)
    if m:
        raw = m.group("num").replace(",", ".")
        try:
            secs = float(raw)
            secs = int(round(secs))
            return secs, m.span()
        except Exception:
            pass

    # Вариант: слова-числа + единицы
    m = _DURATION_WORD_RE.search(tl)
    if m:
        w = m.group("word")
        w = w.lower()
        secs = _WORD2NUM_RU.get(w) or _WORD2NUM_EN.get(w)
        if secs:
            return int(secs), m.span()

    return None, None

def parse_video_opts_from_text(text: str, default_duration: int = None, default_ar: str = None):
    """
    Возвращает: (duration_for_luma, aspect_ratio, clean_prompt)
    - duration_for_luma: 5/9/10 (ближайшее к запрошенному 1..10)
    - aspect_ratio: как раньше
    - clean_prompt: исходный текст без кусочка "10 сек"/"пять секунд"/и т.п.
    """
    # Базовые значения, если пользователь не указал
    duration_req = default_duration if default_duration is not None else LUMA_DURATION_S
    ar = default_ar if default_ar is not None else LUMA_ASPECT

    t = text or ""

    # 1) Достаём длительность (в любом виде)
    secs, span = _extract_duration_seconds(t)
    if secs is not None:
        # нормируем 1..10
        secs = max(1, min(10, int(secs)))
        duration_req = secs
        # вырезаем найденный фрагмент, чтобы он не попал в промпт
        start, end = span
        t = (t[:start] + t[end:]).strip()

    # 2) Достаём AR, если есть
    m = _AR_RE.search(t)
    if m:
        ar = m.group(1)
        t = _AR_RE.sub("", t, count=1)

    # 3) Приводим к допустимым длительностям Luma
    duration_for_luma = _snap_to_luma_allowed(duration_req)

    # 4) Чистим пробелы
    clean = re.sub(r"\s{2,}", " ", t.replace(" ,", ",")).strip(" ,.;-—")

    return duration_for_luma, ar, clean
# === LUMA DURATION PARSER — END =======================================

def _luma_make_video_sync(prompt: str, duration: int = None, aspect_ratio: str = None) -> bytes:
    if not LUMA_API_KEY:
        raise RuntimeError("LUMA_API_KEY не задан")
    dur = duration if duration is not None else LUMA_DURATION_S
    ar  = aspect_ratio if aspect_ratio is not None else LUMA_ASPECT
    headers = {
        "Authorization": f"Bearer {LUMA_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    create_url = "https://api.lumalabs.ai/dream-machine/v1/generations"
    payload = {"prompt": prompt, "model": LUMA_MODEL, "duration": f"{dur}s", "aspect_ratio": ar}
    with httpx.Client(timeout=None) as http:
        r = http.post(create_url, headers=headers, json=payload)
        try:
            r.raise_for_status()
        except Exception:
            raise RuntimeError(f"Luma create error: {r.status_code} {r.text}")
        gen = r.json()
        gen_id = gen.get("id") or gen.get("generation_id")
        if not gen_id:
            raise RuntimeError(f"Luma: не получили id задачи: {gen}")
        get_url = f"https://api.lumalabs.ai/dream-machine/v1/generations/{gen_id}"
        while True:
            g = http.get(get_url, headers=headers)
            try:
                g.raise_for_status()
            except Exception:
                raise RuntimeError(f"Luma poll error: {g.status_code} {g.text}")
            data = g.json()
            status = data.get("state") or data.get("status")
            last_msg = data.get("failure_reason") or data.get("message") or ""
            if status in ("completed", "succeeded", "SUCCEEDED"):
                assets = data.get("assets") or {}
                video_url = assets.get("video") or assets.get("mp4") or assets.get("file")
                if not video_url:
                    raise RuntimeError(f"Luma: нет ссылки на видео в ответе: {data}")
                v = http.get(video_url); v.raise_for_status()
                return v.content
            if status in ("failed", "error", "cancelled", "canceled"):
                raise RuntimeError(f"Luma failed: {last_msg or status}")
            time.sleep(2)

async def cmd_make_video_luma(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt_raw = " ".join(context.args).strip() if context.args else (update.message.text or "").strip()
    prompt_raw = re.sub(r"^/video_luma\b", "", prompt_raw, flags=re.I).strip(" -:—")
    dur, ar, prompt = parse_video_opts_from_text(prompt_raw)
    if not prompt:
        await update.effective_message.reply_text("Напиши так: /video_luma закат над морем, 6s, 9:16")
        return
    if not LUMA_API_KEY:
        await update.effective_message.reply_text("🎬 Luma: не задан LUMA_API_KEY.")
        return
    await update.effective_message.reply_text(f"🎬 Генерирую через Luma… (⏱ {dur}s • {ar})")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)
    try:
        video_bytes = await asyncio.to_thread(_luma_make_video_sync, prompt, dur, ar)
        await update.effective_message.reply_video(
            video=video_bytes,
            supports_streaming=True,
            caption=f"Готово 🎥 {dur}s • {ar}\n{prompt}"
        )
    except Exception as e:
        low = str(e).lower()
        hint = ""
        if "401" in low or "403" in low:
            hint = "\n\nПроверь LUMA_API_KEY (Bearer luma-…), проект и лимиты."
        elif "429" in low:
            hint = "\n\nПохоже на rate limit (429). Подожди немного или сократи частоту запросов."
        elif "credit" in low or "quota" in low:
            hint = "\n\nВероятно, закончились кредиты/квота."
        await update.effective_message.reply_text(f"⚠️ Luma: не удалось создать видео: {e}{hint}")
        log.exception("Luma video error: %s", e)

# -------- ENGINE MODES --------
ENGINE_GPT    = "gpt"
ENGINE_GEMINI = "gemini"
ENGINE_LUMA   = "luma"
ENGINE_RUNWAY = "runway"
ENGINE_MJ     = "midjourney"

ENGINE_TITLES = {
    ENGINE_GPT:    "💬 GPT-5 (текст/фото)",
    ENGINE_GEMINI: "🧠 Gemini (текст/мультимодаль)",
    ENGINE_LUMA:   "🎬 Luma (видео/фото)",
    ENGINE_RUNWAY: "🎥 Runway (PRO ~$7/видео)",
    ENGINE_MJ:     "🖼 Midjourney (Discord)",
}

def engines_kb():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(ENGINE_TITLES[ENGINE_GPT])],
            [KeyboardButton(ENGINE_TITLES[ENGINE_GEMINI])],
            [KeyboardButton(ENGINE_TITLES[ENGINE_LUMA])],
            [KeyboardButton(ENGINE_TITLES[ENGINE_RUNWAY])],
            [KeyboardButton(ENGINE_TITLES[ENGINE_MJ])],
            [KeyboardButton("⬅️ Назад")]
        ],
        resize_keyboard=True
    )

def _engine_from_button(text: str):
    for k, v in ENGINE_TITLES.items():
        if v == text:
            return k
    return None

async def open_engines_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["__prev_kb"] = main_kb
    await update.effective_message.reply_text(
        "Выбери движок для работы 👇\n\n"
        "• GPT-5 — ответы и картинки через OpenAI\n"
        "• Gemini — длинные PDF/видео/таблицы (точность по фактам)\n"
        "• Luma — видео/фото (экономнее Runway)\n"
        "• Runway — студийное видео (PRO)\n"
        "• Midjourney — помогу со сборкой промпта для Discord",
        reply_markup=engines_kb()
    )

async def handle_engine_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text == "⬅️ Назад":
        await cmd_start(update, context); return
    eng = _engine_from_button(text)
    if not eng:
        return
    context.user_data["engine"] = eng
    if eng == ENGINE_RUNWAY and update.effective_user.id not in PREMIUM_USER_IDS:
        await update.message.reply_text("⚠️ Runway доступен только на ПРО-тарифе.")
    elif eng == ENGINE_LUMA:
        if not LUMA_API_KEY:
            await update.message.reply_text("🎬 Luma выбрана. API-ключ не задан — пока использую запасные пути. Готов принимать запросы «создай видео…».")
        else:
            await update.message.reply_text("🎬 Luma активна. Пиши «создай видео…» или «сгенерируй фото…».")
    elif eng == ENGINE_MJ:
        await update.message.reply_text("🖼 Midjourney: пришли описание — соберу промпт для Discord.")
    elif eng == ENGINE_GEMINI:
        await update.message.reply_text(
            "🧠 Gemini режим активен. Буду использовать его для длинных документов (PDF/видео/таблицы), "
            "когда это уместно. Если ключи не подключены — отвечу базовым движком."
        )
    else:
        await update.message.reply_text("💬 GPT-5 активирован.")

# -------- STATIC TEXTS --------
START_TEXT = (
    "Привет! Я *Neuro-Bot GPT-5 • Luma • Runway • Midjourney • Deepgram • Gemini*.\n"
    "Пишу тексты, генерирую изображения и видео, понимаю голос и фото. Чем помочь?\n\n"
    "Нажми «🧭 Меню движков», чтобы выбрать движок."
)

MODES_TEXT = (
    "⚙️ *Режимы*\n"
    "• 💬 Универсальный — диалог/тексты\n"
    "• 🧠 Исследователь — факты/источники\n"
    "• ✍️ Редактор — правки/стили\n"
    "• 📊 Аналитик — формулы/таблицы\n"
    "• 🖼️ Визуальный — описание изображений, OCR\n"
    "• 🎙️ Голос — распознаю аудио и отвечаю по содержанию"
)

EXAMPLES_TEXT = (
    "🧩 *Примеры запросов*\n"
    "• «Сделай конспект главы 3 и выдели формулы»\n"
    "• «Проанализируй CSV, найди тренды и сделай краткий вывод»\n"
    "• «Составь письмо клиенту, дружелюбно и по делу»\n"
    "• «Суммируй статью из ссылки и дай источники»\n"
    "• «Опиши текст на фото и извлеки таблицу»"
)

# -------- UI / KEYBOARD --------
main_kb = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🧭 Меню движков")],
        [KeyboardButton("⚙️ Режимы"), KeyboardButton("🧩 Примеры")],
        [KeyboardButton("⭐ Подписка", web_app=WebAppInfo(url=TARIFF_URL))],
    ],
    resize_keyboard=True
)

# -------- LUMA & RUNWAY DIAG --------
async def cmd_diag_luma(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = LUMA_API_KEY
    lines = [f"LUMA_API_KEY: {'✅ найден' if key else '❌ нет'}"]
    if key:
        lines.append(f"Формат: {'ok' if key.startswith('luma-') else 'не начинается с luma-'}")
        lines.append(f"Длина: {len(key)}")
        lines.append(f"MODEL: {LUMA_MODEL}, ASPECT: {LUMA_ASPECT}, DURATION: {LUMA_DURATION_S}s")
    await update.message.reply_text("\n".join(lines))

async def cmd_diag_runway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = RUNWAY_API_KEY
    lines = [f"RUNWAY_API_KEY: {'✅ найден' if key else '❌ нет'}"]
    if key:
        lines.append(f"Формат: {'ok' if key.startswith('key_') else 'не начинается с key_'}")
        lines.append(f"Длина: {len(key)}")
    if RUNWAY_SDK_OK:
        try:
            from runwayml import RunwayML as _R
            _ = _R(api_key=key) if key else None
            lines.append("SDK инициализирован ✅")
        except Exception as e:
            lines.append(f"SDK init error: {e}")
    else:
        lines.append(f"SDK импорт: ❌ ({RUNWAY_IMPORT_ERROR})")
        lines.append("Подсказка: pip install runwayml")
    pro_list = ", ".join(map(str, sorted(PREMIUM_USER_IDS))) or "—"
    lines.append(f"PRO (PREMIUM_USER_IDS): {pro_list}")
    lines.append(f"MODEL: {RUNWAY_MODEL}, RATIO: {RUNWAY_RATIO}, DURATION: {RUNWAY_DURATION_S}s")
    await update.message.reply_text("\n".join(lines))

# ================== PAYMENTS: HELPERS ==================
def _plan_amount_rub(tier: str, term: str) -> int:
    tier = (tier or "").lower()
    term = (term or "").lower()
    return PLAN_PRICE_TABLE.get(tier, PLAN_PRICE_TABLE["pro"]).get(term, PLAN_PRICE_TABLE["pro"]["month"])

def _term_to_months(term: str) -> int:
    return TERM_MONTHS.get((term or "").lower(), 1)

def _receipt_provider_data(*, tier: str, term: str, amount_rub: int) -> dict:
    title_map = {"start": "START", "pro": "PRO", "ultimate": "ULTIMATE"}
    term_map  = {"month": "1 месяц", "quarter": "3 месяца", "year": "12 месяцев"}
    item_desc = f"Подписка {title_map.get(tier, 'PRO')} — {term_map.get(term, '1 месяц')}"
    return {
        "receipt": {
            "items": [{
                "description": item_desc[:128],
                "quantity": 1,
                "amount": {"value": amount_rub, "currency": "RUB"},
                "vat_code": 1,
                "payment_mode": "full_payment",
                "payment_subject": "service"
            }],
            "tax_system_code": 1
        }
    }

# ================== PAYMENTS: HANDLERS ==================
async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton(
            "Открыть тарифы (мини-приложение)",
            web_app=WebAppInfo(url=TARIFF_URL)
        )
    )
    await update.message.reply_text(
        "💳 *Тарифы Neuro-Bot*\nОткрой мини-приложение и нажми «Оформить подписку».",
        reply_markup=kb, disable_web_page_preview=True, parse_mode="Markdown"
    )

async def _send_invoice_safely(msg, user_id: int, *, tier: str, term: str):
    amount_rub = _plan_amount_rub(tier, term)
    prices = [LabeledPrice(label=f"Neuro-Bot {tier.upper()} — {term}", amount=amount_rub * 100)]
    provider_data = _receipt_provider_data(tier=tier, term=term, amount_rub=amount_rub)
    try:
        await msg.reply_invoice(
            title=f"Neuro-Bot {tier.upper()}",
            description=f"Доступ к {tier.upper()} • срок: {term}",
            provider_token=PROVIDER_TOKEN,
            currency=CURRENCY,
            prices=prices,
            payload=f"sub:{tier}:{term}:{user_id}",
            provider_data=provider_data,
            need_email=True,
            send_email_to_provider=True
        )
    except Exception as e:
        log.exception("create invoice error: %s", e)
        text = (
            "⚠️ Не удалось сформировать счёт. Проверьте подключение платежей.\n\n"
            "Частые причины:\n"
            "• Неверный/пустой PROVIDER_TOKEN_YOOKASSA\n"
            "• В BotFather не выбран или неверно выбран провайдер YooKassa\n"
            "• Валюта/сумма не поддерживается провайдером (ожидаем RUB)\n"
            "• Не redeploy после изменения ENV\n\n"
            f"Техническая деталь: {e}"
        )
        await msg.reply_text(text)

def _subscribe_choose_kb(term: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("START", callback_data=f"subscribe_choose:start:{term}")],
        [InlineKeyboardButton("PRO", callback_data=f"subscribe_choose:pro:{term}")],
        [InlineKeyboardButton("ULTIMATE", callback_data=f"subscribe_choose:ultimate:{term}")],
    ]
    return InlineKeyboardMarkup(rows)

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = (query.data or "")
    if data == "subscribe_open":
        await query.message.reply_text("Выберите срок:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("1 месяц", callback_data="subscribe_term:month")],
            [InlineKeyboardButton("3 месяца", callback_data="subscribe_term:quarter")],
            [InlineKeyboardButton("12 месяцев", callback_data="subscribe_term:year")],
        ]))
        return
    if data.startswith("subscribe_term:"):
        term = data.split(":", 1)[1]
        await query.message.reply_text("Выберите тариф:", reply_markup=_subscribe_choose_kb(term))
        return
    if data.startswith("subscribe_choose:"):
        _, tier, term = data.split(":")
        await _send_invoice_safely(query.message, query.from_user.id, tier=tier, term=term)
        return

async def subscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Открыть тарифы (мини-приложение)",
            web_app=WebAppInfo(url=TARIFF_URL)
        )],
        [InlineKeyboardButton("Выставить счёт здесь", callback_data="subscribe_open")]
    ])
    await update.message.reply_text("Как оформить подписку?", reply_markup=kb)

async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    user_id = update.effective_user.id
    payload = sp.invoice_payload or ""
    tier, term = "pro", "month"
    m = re.match(r"^sub:([a-z]+):([a-z]+):(\d+)$", payload)
    if m:
        tier = m.group(1)
        term = m.group(2)
    if sp.currency != CURRENCY:
        await update.message.reply_text("❗️Валюта платежа не совпала, обратитесь в поддержку."); return
    months = _term_to_months(term)
    until = activate_subscription(user_id, months=months)
    await update.message.reply_text(
        f"✅ Оплата получена!\nТариф: {tier.upper()} • Срок: {term} • "
        f"Подписка активна до {until.strftime('%d.%m.%Y %H:%M UTC')}\n\n"
        f"Команда /pro — проверить доступ к ПРО-функции."
    )

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    until = get_subscription_until(update.effective_user.id)
    if not until or until <= datetime.utcnow():
        await update.message.reply_text("Статус: ❌ нет активной подписки.\nКоманда /subscribe — оформить.")
    else:
        days_left = max(0, (until - datetime.utcnow()).days)
        await update.message.reply_text(
            f"Статус: ✅ активна\nДействует до: {until.strftime('%d.%m.%Y %H:%M UTC')} ({days_left} дн.)"
        )

async def pro_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_active(update.effective_user.id):
        await update.message.reply_text("❌ Нужна активная подписка. Введите /subscribe")
        return
    await update.message.reply_text("🎯 ПРО-доступ подтверждён. Тут выполняем PRO-действие...")

async def diag_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = PROVIDER_TOKEN
    lines = [
        f"PROVIDER_TOKEN_YOOKASSA: {'✅ задан' if t else '❌ пуст'}",
        f"Длина: {len(t) if t else 0}",
        "Подсказка: токен берётся в @BotFather → Payments → YooKassa.",
        f"Валюта: {CURRENCY}",
        f"Таблица цен: {PLAN_PRICE_TABLE}",
        f"WEB тарифы: {TARIFF_URL}"
    ]
    await update.message.reply_text("\n".join(lines))

# -------- WEB APP DATA --------
async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ожидаемые payload из мини-аппы:
      {"type":"subscribe","tier":"start|pro|ultimate","plan":"month|quarter|year"}
      {"type":"status"} | {"type":"help"} | {"type":"open_tariff"}
    """
    msg = update.effective_message
    wad = getattr(msg, "web_app_data", None)
    if not wad:
        return
    raw = wad.data or ""
    try:
        payload = json.loads(raw) if raw.strip().startswith("{") else {"type": raw}
    except Exception:
        payload = {"type": str(raw)}
    ptype = (payload.get("type") or "").strip().lower()
    term  = (payload.get("plan") or payload.get("term") or "month").strip().lower()
    tier  = (payload.get("tier") or "").strip().lower()
    log.info("WEB_APP_DATA payload: %s", payload)

    if ptype in ("subscribe", "subscription", "subscribe_click"):
        if tier not in ("start", "pro", "ultimate"):
            await msg.reply_text("Выберите тариф:", reply_markup=_subscribe_choose_kb(term))
        else:
            await _send_invoice_safely(msg, update.effective_user.id, tier=tier, term=term)
        return

    if ptype in ("status", "status_check"):
        await status_cmd(update, context); return

    if ptype in ("open_tariff", "tariff", "plan", "plan_from_webapp"):
        await msg.reply_text(
            "Открыл страницу тарифов. Нажмите «Оформить подписку», чтобы выставить счёт.",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("⭐ Подписка", web_app=WebAppInfo(url=WEBAPP_URL or TARIFF_URL))]],
                resize_keyboard=True
            )
        ); return

    if ptype in ("help_from_webapp", "help", "question"):
        await msg.reply_text(
            "🧑‍💻 *Поддержка Neuro-Bot*\n"
            "Если у вас вопрос, напишите прямо сюда, я помогу.\n\n"
            "📩 Также можно написать напрямую: @gpt5pro_support",
            parse_mode="Markdown",
            disable_web_page_preview=True
        ); return

    await msg.reply_text("Открыл бота. Чем помочь?", reply_markup=main_kb)

# -------- START --------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # deep-link: /start subscribe_<tier>_<term>
    args = context.args or []
    if args:
        payload = args[0]
        if payload.startswith("subscribe"):
            parts = payload.split("_")
            tier = parts[1] if len(parts) > 1 else "pro"
            term = parts[2] if len(parts) > 2 else "month"
            await _send_invoice_safely(
                update.effective_message,
                update.effective_user.id,
                tier=tier,
                term=term
            )
            return

    if BANNER_URL:
        try:
            await update.effective_message.reply_photo(BANNER_URL)
        except Exception:
            pass

    await update.effective_message.reply_text(
        START_TEXT,
        reply_markup=main_kb,
        disable_web_page_preview=True,
        parse_mode="Markdown"
    )

# -------- TEXT HANDLER --------
async def cmd_modes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(MODES_TEXT, parse_mode="Markdown")

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(EXAMPLES_TEXT, parse_mode="Markdown")

async def premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscribe_cmd(update, context)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id
    await typing(context, chat_id)

    if text == "🧭 Меню движков":
        await open_engines_menu(update, context); return
    if text in ENGINE_TITLES.values() or text == "⬅️ Назад":
        await handle_engine_click(update, context); return

    lower = text.lower()
    if lower in ("⚙️ режимы", "режимы", "/modes"):
        await cmd_modes(update, context); return
    if lower in ("🧩 примеры", "примеры", "/examples"):
        await cmd_examples(update, context); return

    if is_vision_capability_question(text):
        await update.message.reply_text(
            "Да — анализирую изображения и помогаю с видео по кадрам, а ещё распознаю голос. ✅\n\n"
            "• Фото/скриншоты: JPG/PNG/WebP (до ~10 МБ)\n"
            "• Видео: пришли 1–3 ключевых кадра (скриншота)"
        ); return

    if is_smalltalk(text):
        reply = await ask_openai_text(text)
        await update.message.reply_text(reply); return

    web_ctx = ""
    sources = []
    if should_browse(text):
        ans, results = tavily_search(text, max_results=5)
        sources = results or []
        ctx_lines = []
        if ans: ctx_lines.append(f"Краткая сводка поиском: {ans}")
        for i, it in enumerate(sources, 1):
            ctx_lines.append(f"[{i}] {it.get('title','')}: {it.get('url','')}")
        web_ctx = "\n".join(ctx_lines)

    # Единая маршрутизация
    await route_and_handle_textlike(update, context, text, web_ctx=web_ctx, sources=sources)

# -------- IMAGE / VOICE / AUDIO / DOC --------
async def _handle_image_bytes(update: Update, context: ContextTypes.DEFAULT_TYPE, data: bytes, user_text: str):
    mime = sniff_image_mime(data)
    img_b64 = base64.b64encode(data).decode("ascii")
    answer = await ask_openai_vision(user_text, img_b64, mime)
    await update.message.reply_text(answer, disable_web_page_preview=True)

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await typing(context, chat_id)
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    buf = BytesIO(); await file.download_to_memory(buf)
    user_text = (update.message.caption or "").strip()
    await _handle_image_bytes(update, context, buf.getvalue(), user_text)

async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await typing(context, chat_id)
    doc = update.message.document
    mime = (doc.mime_type or "").lower()
    if mime.startswith("image/"):
        file = await context.bot.get_file(doc.file_id)
        buf = BytesIO(); await file.download_to_memory(buf)
        user_text = (update.message.caption or "").strip()
        await _handle_image_bytes(update, context, buf.getvalue(), user_text)
    else:
        await update.message.reply_text("Файл получил. Если это PDF/документ — пришли конкретные страницы как изображения или укажи, что извлечь.")

async def _after_transcribed(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    prefix = f"🗣️ Распознал: «{text}»\n\n"
    await update.message.reply_text(prefix)

    web_ctx = ""
    sources = []
    if should_browse(text):
        ans, results = tavily_search(text, max_results=5)
        sources = results or []
        ctx_lines = []
        if ans: ctx_lines.append(f"Краткая сводка поиском: {ans}")
        for i, it in enumerate(sources, 1):
            ctx_lines.append(f"[{i}] {it.get('title','')}: {it.get('url','')}")
        web_ctx = "\n".join(ctx_lines)

    await route_and_handle_textlike(update, context, text, web_ctx=web_ctx, sources=sources)

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await typing(context, chat_id)
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    buf = BytesIO(); await file.download_to_memory(buf)
    text = await transcribe_audio(buf, filename_hint="audio.ogg")
    if not text:
        await update.message.reply_text("Не удалось распознать голос. Попробуй ещё раз."); return
    await _after_transcribed(update, context, text)

async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await typing(context, chat_id)
    audio = update.message.audio
    file = await context.bot.get_file(audio.file_id)
    buf = BytesIO(); await file.download_to_memory(buf)
    filename = (audio.file_name or "audio.mp3")
    text = await transcribe_audio(buf, filename_hint=filename)
    if not text:
        await update.message.reply_text("Не удалось распознать аудио. Попробуй ещё раз."); return
    await _after_transcribed(update, context, text)

async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Да, помогу с видео: пришли 1–3 ключевых кадра (скриншота) — проанализирую по кадрам. 📽️")

# -------- helper --------
async def _call_handler_with_prompt(handler, update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    old_args = getattr(context, "args", None)
    try:
        context.args = [prompt]
        await handler(update, context)
    finally:
        context.args = old_args

# -------- BOOTSTRAP --------
def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Базовые команды/экраны
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("modes", cmd_modes))
    app.add_handler(CommandHandler("examples", cmd_examples))
    app.add_handler(CommandHandler("diag_runway", cmd_diag_runway))
    app.add_handler(CommandHandler("diag_luma", cmd_diag_luma))
    app.add_handler(CommandHandler("diag_payments", diag_payments))
    app.add_handler(CommandHandler("diag_images", cmd_diag_images))
    app.add_handler(CommandHandler("engines", open_engines_menu))

    # Премиум/подписка
    app.add_handler(CommandHandler("plans", plans))
    app.add_handler(CommandHandler("premium", premium_cmd))
    app.add_handler(CallbackQueryHandler(on_cb, pattern=r"^subscribe_(open|term.*|choose.*)$"))
    app.add_handler(CommandHandler("subscribe", subscribe_cmd))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("pro", pro_cmd))

    # WEB APP
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))

    # Изображения/видео
    app.add_handler(CommandHandler("img", cmd_img))
    app.add_handler(CommandHandler("video", cmd_make_video))
    app.add_handler(CommandHandler("video_luma", cmd_make_video_luma))

    # Кнопки выбора видео-движка
    app.add_handler(CallbackQueryHandler(on_video_choice, pattern="^video_choose_(luma|runway)$"))

    # Кнопки меню движков
    engine_buttons_pattern = "(" + "|".join(map(re.escape, list(ENGINE_TITLES.values()) + ["⬅️ Назад", "🧭 Меню движков"])) + ")"
    app.add_handler(MessageHandler(filters.Regex(engine_buttons_pattern), on_text))

    # Остальной текст/медиа
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, on_document))
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.AUDIO, on_audio))
    app.add_handler(MessageHandler(filters.VIDEO, on_video))
    return app

def run_webhook(app):
    url_path = f"webhook/{BOT_TOKEN}"
    webhook_url = f"{PUBLIC_URL.rstrip('/')}/{url_path}"
    log.info("Starting webhook on 0.0.0.0:%s  ->  %s", PORT, webhook_url)
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=url_path,
        webhook_url=webhook_url,
        secret_token=WEBHOOK_SECRET or None,
        drop_pending_updates=True,
    )

def main():
    db_init()
    if not PROVIDER_TOKEN:
        log.warning("⚠️ PROVIDER_TOKEN_YOOKASSA не задан — инвойсы не будут работать.")
    app = build_app()
    run_webhook(app)

# короткие алиасы (для удобства REPL)
cmd_start = cmd_start if 'cmd_start' in globals() else None
cmd_modes = cmd_modes if 'cmd_modes' in globals() else None
cmd_examples = cmd_examples if 'cmd_examples' in globals() else None

if __name__ == "__main__":
    main()
