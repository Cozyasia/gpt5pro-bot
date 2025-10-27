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
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

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

# Premium whitelist для Runway (оставим поддержку)
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

# -------- HTTP STUB (Render Web Service) --------
def _start_http_stub():
    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            path = (self.path or "/").split("?", 1)[0]
            if path in ("/", "/healthz"):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"ok")
                return
            if path == "/premium.html":
                # если задана внешняя страница тарифов — редиректим
                if WEBAPP_URL:
                    self.send_response(302)
                    self.send_header("Location", WEBAPP_URL)
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    html = (
                        "<html><body><h3>Premium page</h3>"
                        "<p>WEBAPP_URL не задан. Установите переменную окружения.</p>"
                        "</body></html>"
                    )
                    self.wfile.write(html.encode("utf-8"))
                return
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"not found")

        # глушим лишние логи
        def log_message(self, *_):
            return

    try:
        srv = HTTPServer(("0.0.0.0", PORT), _H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log.info("HTTP stub bound on 0.0.0.0:%s", PORT)
    except Exception as e:
        log.exception("HTTP stub start failed: %s", e)

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

# Текст/визуал (LLM)
oai_llm = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=_auto_base or None,
    default_headers=default_headers or None,
)

oai_stt = OpenAI(api_key=OPENAI_STT_KEY) if OPENAI_STT_KEY else None

# === Images: ВСЕГДА OpenAI/прокси ===
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
    # мягкая миграция: добавим колонку tier (если нет)
    try:
        cur.execute("ALTER TABLE subscriptions ADD COLUMN tier TEXT")
    except Exception:
        pass
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
    key_env  = os.environ.get("OPENAI_IMAGE_KEY", "").strip()
    key_used = key_env or OPENAI_API_KEY
    base     = IMAGES_BASE_URL
    lines = [
        f"OPENAI_IMAGE_KEY: {'✅ найден' if key_used else '❌ нет'}",
        f"BASE_URL: {base}",
        f"MODEL: {IMAGES_MODEL}",
    ]
    if "openrouter" in base.lower():
        lines.append("⚠️ BASE_URL указывает на OpenRouter — там нет gpt-image-1.")
        lines.append("   Укажи https://api.openai.com/v1 (или свой прокси) в OPENAI_IMAGE_BASE_URL.")
    await update.message.reply_text("\n".join(lines))

async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip() if context.args else ""
    if not prompt:
        await update.effective_message.reply_text("Напиши так: «/img Земля из космоса, реалистично, 4k»")
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
        hint = [f"База: {IMAGES_BASE_URL}", f"Модель: {IMAGES_MODEL}"]
        if "unauthorized" in low or "401" in low or "invalid_api_key" in low:
            hint.append("Проверь OPENAI_IMAGE_KEY (или OPENAI_API_KEY): действующий ключ без пробелов.")
        elif "insufficient_quota" in low or "billing" in low or "credit" in low:
            hint.append("Похоже на исчерпанный баланс/квоты в OpenAI.")
        elif "connection" in low or "timed out" in low or "name or service not known" in low:
            hint.append("Сетевая ошибка. Если хостинг блокирует api.openai.com — укажи OPENAI_IMAGE_BASE_URL.")
        elif "model" in low and "not found" in low:
            hint.append("gpt-image-1 есть только в OpenAI/прокси, не в OpenRouter.")
        elif "ascii" in low or "latin-1" in low:
            hint.append("В HTTP-заголовках только ASCII. Проверь OPENROUTER_APP_NAME/HTTP-Referer.")
        await update.effective_message.reply_text("⚠️ Не удалось создать изображение:\n" + msg + "\n\n" + "\n".join(hint))

# -------- VIDEO (Runway SDK) --------
if RUNWAY_API_KEY:
    os.environ["RUNWAY_API_KEY"] = RUNWAY_API_KEY

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

# >>> LUMA
# === LUMA DURATION PARSER — START =====================================
_ALLOWED_LUMA_DURS = (5, 9, 10)
_DURATION_NUM_RE = re.compile(
    r"""
    (?P<prefix>\b(?:на|в|около)?\s*)?
    (?P<num>\d+(?:[.,]\d+)?)
    \s*[-]?\s*
    (?:
        s(?:ec(?:onds?)?)?
        |с|сек(?:\.|ун(?:д(?:а|ы|у|ам|ами|ах)?)?)?
    )
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)
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
    (?P<prefix>\b(?:на|в|около)?\s*)?
    (?P<word>{_WORD_RE_SRC})\s*
    (?:
        s(?:ec(?:onds?)?)?
        |с|сек(?:\.|ун(?:д(?:а|ы|у|ам|ами|ах)?)?)?
        |seconds?
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
_AR_RE = re.compile(r"\b(16:9|9:16|4:3|3:4|1:1|21:9|9:21)\b", re.I)

def _snap_to_luma_allowed(x: int) -> int:
    best = min(_ALLOWED_LUMA_DURS, key=lambda a: (abs(a - x), -a))
    return best

def _extract_duration_seconds(t: str) -> tuple[int | None, tuple[int, int] | None]:
    tl = t.lower()
    m = _DURATION_NUM_RE.search(tl)
    if m:
        raw = m.group("num").replace(",", ".")
        try:
            secs = float(raw)
            secs = int(round(secs))
            return secs, m.span()
        except Exception:
            pass
    m = _DURATION_WORD_RE.search(tl)
    if m:
        w = m.group("word").lower()
        secs = _WORD2NUM_RU.get(w) or _WORD2NUM_EN.get(w)
        if secs:
            return int(secs), m.span()
    return None, None

def parse_video_opts_from_text(text: str, default_duration: int = None, default_ar: str = None):
    duration_req = default_duration if default_duration is not None else LUMA_DURATION_S
    ar = default_ar if default_ar is not None else LUMA_ASPECT
    t = text or ""
    secs, span = _extract_duration_seconds(t)
    if secs is not None:
        secs = max(1, min(10, int(secs)))
        duration_req = secs
        start, end = span
        t = (t[:start] + t[end:]).strip()
    m = _AR_RE.search(t)
    if m:
        ar = m.group(1)
        t = _AR_RE.sub("", t, count=1)
    duration_for_luma = _snap_to_luma_allowed(duration_req)
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

# === QUOTAS • BILLING • ONE-OFF =======================================
USD_RUB = float(os.environ.get("USD_RUB", "100"))
ONEOFF_MARKUP_DEFAULT = float(os.environ.get("ONEOFF_MARKUP_DEFAULT", "1.0"))
ONEOFF_MARKUP_RUNWAY  = float(os.environ.get("ONEOFF_MARKUP_RUNWAY",  "0.5"))

LUMA_RES_HINT = os.environ.get("LUMA_RES", "720p").lower()
RUNWAY_UNIT_COST_USD = float(os.environ.get("RUNWAY_UNIT_COST_USD", "7.0"))
IMG_COST_USD = float(os.environ.get("IMG_COST_USD", "0.05"))

def _estimate_luma_cost_usd(duration_s: int, res_hint: str | None = None) -> float:
    per_sec_720 = 0.40 / 5.0
    res = (res_hint or LUMA_RES_HINT).lower()
    factor = 1.0
    if res in ("1080p", "1920x1080", "fhd"):
        factor = 2.25
    elif res in ("720p", "1280x720", "hd"):
        factor = 1.0
    else:
        m = re.search(r"(\d+)\D+(\d+)", res)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            mp = (w * h) / 1_000_000.0
            base_mp = 1280 * 720 / 1_000_000.0
            factor = max(0.5, mp / base_mp)
    return round(per_sec_720 * int(duration_s) * factor, 2)

LIMITS = {
    "free":      {"text_per_day": 5,    "luma_budget_usd": 0.0, "runway_budget_usd": 0.0,  "img_budget_usd": 0.0, "allow_engines": ["gpt"]},
    "start":     {"text_per_day": 200,  "luma_budget_usd": 0.8, "runway_budget_usd": 0.0,  "img_budget_usd": 0.2, "allow_engines": ["gpt","luma","midjourney"]},
    "pro":       {"text_per_day": 1000, "luma_budget_usd": 4.0, "runway_budget_usd": 7.0,  "img_budget_usd": 1.0, "allow_engines": ["gpt","luma","runway","midjourney"]},
    "ultimate":  {"text_per_day": 5000, "luma_budget_usd": 8.0, "runway_budget_usd": 14.0, "img_budget_usd": 2.0, "allow_engines": ["gpt","luma","runway","midjourney"]},
}

def _today_ymd() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")

# DB: usage + wallet
def db_init_usage():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS usage_daily (
        user_id INTEGER,
        ymd TEXT,
        text_count INTEGER DEFAULT 0,
        luma_usd  REAL DEFAULT 0.0,
        runway_usd REAL DEFAULT 0.0,
        img_usd REAL DEFAULT 0.0,
        PRIMARY KEY (user_id, ymd)
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS wallet (
        user_id INTEGER PRIMARY KEY,
        luma_usd  REAL DEFAULT 0.0,
        runway_usd REAL DEFAULT 0.0,
        img_usd REAL DEFAULT 0.0
    )""")
    try:
        cur.execute("ALTER TABLE subscriptions ADD COLUMN tier TEXT")
    except Exception:
        pass
    con.commit()
    con.close()

def _usage_row(user_id: int, ymd: str | None = None):
    ymd = ymd or _today_ymd()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO usage_daily(user_id, ymd) VALUES (?,?)", (user_id, ymd))
    con.commit()
    cur.execute("SELECT text_count, luma_usd, runway_usd, img_usd FROM usage_daily WHERE user_id=? AND ymd=?", (user_id, ymd))
    row = cur.fetchone()
    con.close()
    return {"text_count": row[0], "luma_usd": row[1], "runway_usd": row[2], "img_usd": row[3]}

def _usage_update(user_id: int, **delta):
    ymd = _today_ymd()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    row = _usage_row(user_id, ymd)
    cur.execute("""UPDATE usage_daily SET
        text_count=?,
        luma_usd=?,
        runway_usd=?,
        img_usd=?
        WHERE user_id=? AND ymd=?""",
        (row["text_count"] + delta.get("text_count", 0),
         row["luma_usd"]  + delta.get("luma_usd", 0.0),
         row["runway_usd"]+ delta.get("runway_usd", 0.0),
         row["img_usd"]   + delta.get("img_usd", 0.0),
         user_id, ymd))
    con.commit(); con.close()

def _wallet_get(user_id: int) -> dict:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES (?)", (user_id,))
    con.commit()
    cur.execute("SELECT luma_usd, runway_usd, img_usd FROM wallet WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close()
        return {"luma_usd": row[0], "runway_usd": row[1], "img_usd": row[2]}

def _wallet_add(user_id: int, engine: str, usd: float):
    col = {"luma": "luma_usd", "runway": "runway_usd", "img": "img_usd"}.get(engine)
    if not col:
        return
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute(f"UPDATE wallet SET {col} = {col} + ? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close()

def _wallet_take(user_id: int, engine: str, usd: float) -> bool:
    col = {"luma": "luma_usd", "runway": "runway_usd", "img": "img_usd"}.get(engine)
    if not col:
        return False
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT luma_usd, runway_usd, img_usd FROM wallet WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    bal = {"luma": row[0], "runway": row[1], "img": row[2]}[engine]
    if bal + 1e-9 < usd:
        con.close()
        return False
    cur.execute(f"UPDATE wallet SET {col} = {col} - ? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close()
    return True

def get_subscription_tier(user_id: int) -> str:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT until_ts, tier FROM subscriptions WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close()
    if not row:
        return "free"
    until_ts, tier = row[0], (row[1] or "pro")
    if until_ts and datetime.utcfromtimestamp(until_ts) > datetime.utcnow():
        return (tier or "pro").lower()
    return "free"

def _limits_for(user_id: int) -> dict:
    tier = get_subscription_tier(user_id)
    d = LIMITS.get(tier, LIMITS["free"]).copy()
    d["tier"] = tier
    return d

def check_text_and_inc(user_id: int) -> tuple[bool, int, str]:
    lim = _limits_for(user_id)
    row = _usage_row(user_id)
    left = max(0, lim["text_per_day"] - row["text_count"])
    if left <= 0:
        return False, 0, lim["tier"]
    _usage_update(user_id, text_count=1)
    return True, left - 1, lim["tier"]

def _calc_oneoff_price_rub(engine: str, usd_cost: float) -> int:
    markup = ONEOFF_MARKUP_RUNWAY if engine == "runway" else ONEOFF_MARKUP_DEFAULT
    rub = usd_cost * (1.0 + markup) * USD_RUB
    return int(rub + 0.999)  # ceil

def _can_spend_or_offer(user_id: int, engine: str, est_cost_usd: float) -> tuple[bool, str]:
    lim = _limits_for(user_id)
    row = _usage_row(user_id)
    spent = row[f"{engine}_usd"]
    budget = lim[f"{engine}_budget_usd"]

    if spent + est_cost_usd <= budget + 1e-9:
        _usage_update(user_id, **{f"{engine}_usd": est_cost_usd})
        return True, ""

    need = max(0.0, spent + est_cost_usd - budget)
    return False, f"OFFER:{need:.2f}"

def _register_engine_spend(user_id: int, engine: str, usd: float):
    if engine not in ("luma", "runway", "img"):
        return
    _usage_update(user_id, **{f"{engine}_usd": float(usd)})

# ======= UI / TEXTS =======
START_TEXT = (
    "Привет! Я GPT-бот с тарифами, квотами и разовыми покупками.\n\n"
    "Что умею:\n"
    "• 💬 Текст/фото (GPT)\n"
    "• 🎬 Видео Luma (5–10 c, 9:16/16:9)\n"
    "• 🎥 Видео Runway (PRO)\n"
    "• 🖼 Картинки /img <промпт>\n\n"
    "Открой «🎛 Движки», чтобы выбрать, и «⭐ Подписка» — для тарифов."
)
HELP_TEXT = (
    "Подсказки:\n"
    "• /plans — тарифы и оплата подписки\n"
    "• /img кот с очками — сгенерирует картинку\n"
    "• «сделай видео … на 9 секунд 9:16» — Luma\n"
    "• «🎛 Движки» — выбрать GPT / Luma / Runway / Midjourney\n"
    "• «🧾 Баланс» — кошелёк для разовых оплат"
)
MODES_TEXT = "Выбери движок для следующего запроса:"
EXAMPLES_TEXT = (
    "Примеры:\n"
    "• сделай видео ретро-авто на берегу, 9:16 на 9 секунд\n"
    "• опиши текст на фото (пришли фото и подпиши запрос)\n"
    "• /img неоновый город в дождь, реализм\n"
)

main_kb = ReplyKeyboardMarkup(
    [
        [KeyboardButton("⭐ Подписка"), KeyboardButton("🎛 Движки")],
        [KeyboardButton("🧾 Баланс"), KeyboardButton("ℹ️ Помощь")],
    ],
    resize_keyboard=True
)

# ======= ENGINE STATE (in-memory) =======
_user_engine: dict[int, str] = {}  # user_id -> engine key

def _get_engine(user_id: int) -> str:
    return _user_engine.get(user_id, ENGINE_GPT)

def _set_engine(user_id: int, engine: str):
    if engine in ENGINE_TITLES:
        _user_engine[user_id] = engine

# ======= SUBSCRIPTIONS: helpers =======
def set_subscription_tier(user_id: int, tier: str):
    tier = (tier or "pro").lower()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO subscriptions(user_id, until_ts, tier) VALUES (?, ?, ?)",
        (user_id, int(datetime.utcnow().timestamp()), tier),
    )
    cur.execute("UPDATE subscriptions SET tier=? WHERE user_id=?", (tier, user_id))
    con.commit()
    con.close()

def activate_subscription_with_tier(user_id: int, tier: str, months: int):
    until = activate_subscription(user_id, months=months)
    set_subscription_tier(user_id, tier)
    return until

# ======= INVOICE / ONE-OFF =======
def _oneoff_human(engine: str) -> str:
    return {"luma": "Luma (видео)", "runway": "Runway (видео)", "img": "Картинка"}.get(engine, engine)

async def _send_invoice(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    title: str,
    description: str,
    payload: str,
    amount_rub: int,
):
    prices = [LabeledPrice(label=title, amount=int(amount_rub) * 100)]
    photo_url = BANNER_URL if BANNER_URL else None
    await context.bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token=PROVIDER_TOKEN,
        currency=CURRENCY,
        prices=prices,
        photo_url=photo_url,
        need_name=False,
        need_phone_number=False,
        need_email=False,
        need_shipping_address=False,
        is_flexible=False,
        max_tip_amount=0,
    )

_pending_actions: dict[str, dict] = {}  # action_id -> payload

def _new_action_id() -> str:
    return base64.urlsafe_b64encode(os.urandom(9)).decode("ascii").rstrip("=")

async def _offer_oneoff_and_remember(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    engine: str,
    usd_need: float,
    after_kind: str,
    after_payload: dict,
):
    aid = _new_action_id()
    _pending_actions[aid] = {
        "user_id": user_id,
        "engine": engine,
        "usd_need": float(usd_need),
        "after_kind": after_kind,
        "after_payload": after_payload,
        "ts": time.time(),
    }
    rub = _calc_oneoff_price_rub(engine, usd_need)
    title = f"Разовая оплата: {_oneoff_human(engine)}"
    desc = f"Пополнение кошелька на {usd_need:.2f}$ для запуска операции ({_oneoff_human(engine)})."
    payload = f"TOPUP:{engine}:{usd_need:.2f}:{aid}"
    await _send_invoice(context, update.effective_chat.id, title, desc, payload, rub)
    await update.effective_message.reply_text(
        f"⚠️ Не хватает дневного бюджета по «{_oneoff_human(engine)}». "
        f"Выставил счёт на ~{rub} ₽ (≈ {usd_need:.2f}$) — после оплаты продолжу автоматически."
    )

async def _try_pay_then_do(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    engine: str,
    est_cost_usd: float,
    do_coro_factory,  # callable -> coroutine
    remember_kind: str,
    remember_payload: dict,
):
    ok, detail = _can_spend_or_offer(user_id, engine, est_cost_usd)
    if ok:
        await do_coro_factory()
        return

    usd_need = 0.0
    if isinstance(detail, str) and detail.startswith("OFFER:"):
        try:
            usd_need = float(detail.split(":", 1)[1])
        except Exception:
            usd_need = max(0.0, est_cost_usd)

    if usd_need > 0:
        if _wallet_take(user_id, engine, usd_need):
            _register_engine_spend(user_id, engine, usd_need)
            await do_coro_factory()
            return
        await _offer_oneoff_and_remember(
            update, context, user_id, engine, usd_need, remember_kind, remember_payload
        )
        return

    await update.effective_message.reply_text("Не удалось оценить доплату. Попробуй ещё раз.")

# ======= COMMANDS =======
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(START_TEXT, reply_markup=main_kb, disable_web_page_preview=True)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT)

def _plans_markup():
    kb = [
        [
            InlineKeyboardButton("Start / месяц — 499 ₽", callback_data="plan:start:month"),
            InlineKeyboardButton("Pro / месяц — 999 ₽", callback_data="plan:pro:month"),
        ],
        [
            InlineKeyboardButton("Ultimate / месяц — 1999 ₽", callback_data="plan:ultimate:month"),
        ],
        [
            InlineKeyboardButton("Квартал (экономия)", callback_data="plan_menu:quarter"),
            InlineKeyboardButton("Год (макс выгода)", callback_data="plan_menu:year"),
        ],
        [InlineKeyboardButton("👉 Открыть страницу тарифов", web_app=WebAppInfo(url=TARIFF_URL))],
    ]
    return InlineKeyboardMarkup(kb)

def _plans_markup_term(term: str):
    tbl = PLAN_PRICE_TABLE
    kb = [
        [InlineKeyboardButton(f"Start / {term} — {tbl['start'][term]} ₽", callback_data=f"plan:start:{term}")],
        [InlineKeyboardButton(f"Pro / {term} — {tbl['pro'][term]} ₽", callback_data=f"plan:pro:{term}")],
        [InlineKeyboardButton(f"Ultimate / {term} — {tbl['ultimate'][term]} ₽", callback_data=f"plan:ultimate:{term}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="plan_menu:root")],
    ]
    return InlineKeyboardMarkup(kb)

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Выбери подписку: ограничения по дневным квотам будут выше, а движки — доступны.",
        reply_markup=_plans_markup(),
    )

async def cmd_modes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(MODES_TEXT, reply_markup=engines_kb())

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w = _wallet_get(update.effective_user.id)
    await update.effective_message.reply_text(
        f"Кошелёк (USD):\n"
        f"• Luma: {w['luma_usd']:.2f}$\n"
        f"• Runway: {w['runway_usd']:.2f}$\n"
        f"• Images: {w['img_usd']:.2f}$"
    )

# ======= CALLBACKS (PLANS) =======
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    data = q.data or ""
    try:
        if data.startswith("plan_menu:"):
            _, term = data.split(":", 1)
            if term == "root":
                await q.edit_message_reply_markup(reply_markup=_plans_markup())
            else:
                await q.edit_message_reply_markup(reply_markup=_plans_markup_term(term))
            await q.answer()
            return
        if data.startswith("plan:"):
            _, tier, term = data.split(":")
            months = TERM_MONTHS[term]
            rub = PLAN_PRICE_TABLE[tier][term]
            title = f"Подписка {tier.capitalize()} ({months} мес.)"
            desc = "Оплата подписки через Telegram. Доступ к квотам и движкам согласно тарифу."
            payload = f"SUB:{tier}:{term}:{months}"
            await _send_invoice(context, q.message.chat_id, title, desc, payload, rub)
            await q.answer("Выставлен счёт.")
            return
    except Exception as e:
        log.exception("Callback error: %s", e)
        await q.answer("Ошибка", show_alert=True)

# ======= PAYMENTS =======
async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    try:
        await query.answer(ok=True)
    except Exception as e:
        log.exception("PreCheckout error: %s", e)
        try:
            await query.answer(ok=False, error_message="Не удалось проверить платёж.")
        except Exception:
            pass

async def on_success_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    user_id = update.effective_user.id
    payload = sp.invoice_payload or ""
    try:
        if payload.startswith("SUB:"):
            _, tier, term, months_s = payload.split(":")
            months = int(months_s)
            until = activate_subscription_with_tier(user_id, tier, months)
            till_str = until.strftime("%Y-%m-%d")
            await update.message.reply_text(
                f"✅ Подписка {tier.capitalize()} активирована до {till_str}. Приятной работы!"
            )
            return
        if payload.startswith("TOPUP:"):
            parts = payload.split(":")
            engine = parts[1]
            usd = float(parts[2])
            aid = parts[3] if len(parts) > 3 else ""
            _wallet_add(user_id, engine, usd)
            await update.message.reply_text(
                f"✅ Кошелёк пополнен на {usd:.2f}$ для «{_oneoff_human(engine)}»."
            )
            if aid and aid in _pending_actions:
                act = _pending_actions.pop(aid, None)
                if act and act.get("user_id") == user_id and act.get("engine") == engine:
                    kind = act.get("after_kind")
                    payload = act.get("after_payload") or {}
                    _register_engine_spend(user_id, engine, act.get("usd_need", 0.0))
                    if kind == "luma_generate":
                        await _do_luma_generate(update, context, **payload)
                    elif kind == "runway_generate":
                        await _do_runway_generate(update, context, **payload)
                    elif kind == "img_generate":
                        await _do_img_generate(update, context, **payload)
            return
    except Exception as e:
        log.exception("SuccessPayment error: %s", e)
        await update.message.reply_text("Платёж прошёл, но возникла ошибка при активации. Напишите в поддержку.")

# ======= MEDIA / ACTIONS =======
async def _do_img_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
        b64 = resp.data[0].b64_json
        img_bytes = base64.b64decode(b64)
        await update.effective_message.reply_photo(photo=img_bytes, caption=f"Готово ✅\nЗапрос: {prompt}")
    except Exception as e:
        log.exception("IMG gen error: %s", e)
        await update.effective_message.reply_text(f"Не удалось создать изображение: {e}")

async def _do_luma_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration: int, aspect: str):
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)
        vid = await asyncio.to_thread(_luma_make_video_sync, prompt, duration, aspect)
        await update.effective_message.reply_video(video=vid, caption=f"🎬 Luma • {duration}s • {aspect}\nЗапрос: {prompt}")
    except Exception as e:
        log.exception("Luma gen error: %s", e)
        await update.effective_message.reply_text(f"Не удалось собрать видео Luma: {e}")

async def _do_runway_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration: int):
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)
        vid = await asyncio.to_thread(_runway_make_video_sync, prompt, duration)
        await update.effective_message.reply_video(video=vid, caption=f"🎥 Runway • ~{duration}s\nЗапрос: {prompt}")
    except Exception as e:
        log.exception("Runway gen error: %s", e)
        await update.effective_message.reply_text(f"Не удалось собрать видео Runway: {e}")

# ======= MSG HANDLERS =======
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ok, left, tier = check_text_and_inc(user_id)
    if not ok:
        await update.effective_message.reply_text(
            "Дневной лимит текстовых запросов исчерпан. Оформите подписку через /plans."
        )
        return
    try:
        file = await update.message.photo[-1].get_file()
        data = await file.download_as_bytearray()
        b64 = base64.b64encode(bytes(data)).decode("ascii")
        mime = sniff_image_mime(bytes(data))
        user_text = (update.message.caption or "").strip()
        ans = await ask_openai_vision(user_text, b64, mime)
        await update.effective_message.reply_text(ans or "Готово.")
    except Exception as e:
        log.exception("Photo handler error: %s", e)
        await update.effective_message.reply_text("Не удалось обработать изображение.")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id

    if text == "ℹ️ Помощь":
        await cmd_help(update, context); return
    if text == "⭐ Подписка":
        await cmd_plans(update, context); return
    if text == "🎛 Движки":
        await cmd_modes(update, context); return
    if text == "🧾 Баланс":
        await cmd_balance(update, context); return

    eng = _engine_from_button(text)
    if eng:
        _set_engine(user_id, eng)
        await update.effective_message.reply_text(f"✅ Движок установлен: {ENGINE_TITLES[eng]}")
        return
    engine = _get_engine(user_id)

    intent, rest = detect_media_intent(text)
    if intent == "image":
        prompt = rest or "highly detailed photo, 4k"
        est = IMG_COST_USD
        async def _go():
            await _do_img_generate(update, context, prompt=prompt)
        await _try_pay_then_do(
            update, context, user_id, "img", est, _go,
            remember_kind="img_generate", remember_payload={"prompt": prompt}
        )
        return

    if intent == "video":
        dur, ar, clean = parse_video_opts_from_text(rest)
        prompt = clean or "cinematic shot, dramatic lighting, highly detailed, film look"
        if engine == ENGINE_RUNWAY:
            tier = get_subscription_tier(user_id)
            allowed = (engine in LIMITS.get(tier, LIMITS["free"])["allow_engines"]) or (user_id in PREMIUM_USER_IDS)
            if not allowed:
                await update.effective_message.reply_text(
                    "Runway доступен на тарифах Pro/Ultimate или по белому списку. "
                    "Оформите подписку через /plans, либо переключитесь на Luma в «🎛 Движки»."
                )
                return
            est = RUNWAY_UNIT_COST_USD
            async def _go():
                await _do_runway_generate(update, context, prompt=prompt, duration=dur)
            await _try_pay_then_do(
                update, context, user_id, "runway", est, _go,
                remember_kind="runway_generate", remember_payload={"prompt": prompt, "duration": dur}
            )
            return
        else:
            est = _estimate_luma_cost_usd(dur, LUMA_RES_HINT)
            async def _go():
                await _do_luma_generate(update, context, prompt=prompt, duration=dur, aspect=ar)
            await _try_pay_then_do(
                update, context, user_id, "luma", est, _go,
                remember_kind="luma_generate", remember_payload={"prompt": prompt, "duration": dur, "aspect": ar}
            )
            return

    ok, left, tier = check_text_and_inc(user_id)
    if not ok:
        await update.effective_message.reply_text(
            "Дневной лимит текстовых запросов исчерпан. Оформите подписку через /plans."
        )
        return

    web_ctx = ""
    if should_browse(text):
        ans, results = tavily_search(text, max_results=5)
        if ans:
            web_ctx = ans
            if results:
                refs = []
                for r in results[:5]:
                    u = r.get("url"); t = r.get("title") or ""
                    if u:
                        refs.append(f"• {t}: {u}")
                if refs:
                    web_ctx += "\n\nИсточники:\n" + "\n".join(refs)

    reply = await _ask_text_via_openrouter(text, web_ctx=web_ctx)
    if not reply:
        reply = await ask_openai_text(text, web_ctx=web_ctx)
    await update.effective_message.reply_text(reply or "Готово.")

# ======= COMMANDS short =======
async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(EXAMPLES_TEXT)

# ======= APP INIT =======
def main():
    db_init()
    db_init_usage()
    _start_http_stub()  # важно для Web Service на Render

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("modes", cmd_modes))
    app.add_handler(CommandHandler("examples", cmd_examples))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("img", cmd_img))
    app.add_handler(CommandHandler("diag_images", cmd_diag_images))

    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_success_payment))

    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)

if __name__ == "__main__":
    main()
