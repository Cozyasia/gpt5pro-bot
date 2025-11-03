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
from datetime import datetime, timedelta, timezone
import threading
import uuid
import contextlib
from http.server import HTTPServer, BaseHTTPRequestHandler

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
from telegram.error import TelegramError

# ───────── LOGGING ─────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")

# ───────── ENV ─────────
BOT_TOKEN        = os.environ.get("BOT_TOKEN", "").strip()
BOT_USERNAME     = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
PUBLIC_URL       = os.environ.get("PUBLIC_URL", "").strip()
WEBAPP_URL       = os.environ.get("WEBAPP_URL", "").strip()

OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL  = os.environ.get("OPENAI_BASE_URL", "").strip()        # OpenRouter или свой прокси для текста
OPENAI_MODEL     = os.environ.get("OPENAI_MODEL", "openai/gpt-4o-mini").strip()

OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "").strip()

USE_WEBHOOK      = os.environ.get("USE_WEBHOOK", "1").lower() in ("1","true","yes","on")
WEBHOOK_PATH     = os.environ.get("WEBHOOK_PATH", "/tg").strip()
WEBHOOK_SECRET   = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()

BANNER_URL       = os.environ.get("BANNER_URL", "").strip()
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "").strip()

# STT:
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "").strip()
OPENAI_STT_KEY   = os.environ.get("OPENAI_STT_KEY", "").strip()
TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1").strip()

# TTS:
OPENAI_TTS_KEY       = os.environ.get("OPENAI_TTS_KEY", "").strip() or OPENAI_API_KEY
OPENAI_TTS_BASE_URL  = (os.environ.get("OPENAI_TTS_BASE_URL", "").strip() or "https://api.openai.com/v1")
OPENAI_TTS_MODEL     = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip()
OPENAI_TTS_VOICE     = os.environ.get("OPENAI_TTS_VOICE", "alloy").strip()
TTS_MAX_CHARS        = int(os.environ.get("TTS_MAX_CHARS", "150") or "150")

# Images:
OPENAI_IMAGE_KEY    = os.environ.get("OPENAI_IMAGE_KEY", "").strip() or OPENAI_API_KEY
IMAGES_BASE_URL     = (os.environ.get("OPENAI_IMAGE_BASE_URL", "").strip() or "https://api.openai.com/v1")
IMAGES_MODEL        = "gpt-image-1"

# Runway
RUNWAY_API_KEY      = os.environ.get("RUNWAY_API_KEY", "").strip()
RUNWAY_MODEL        = os.environ.get("RUNWAY_MODEL", "gen3a_turbo").strip()
RUNWAY_RATIO        = os.environ.get("RUNWAY_RATIO", "720:1280").strip()
RUNWAY_DURATION_S   = int(os.environ.get("RUNWAY_DURATION_S", "8") or 8)

# Luma
LUMA_API_KEY     = os.environ.get("LUMA_API_KEY", "").strip()
LUMA_MODEL       = os.environ.get("LUMA_MODEL", "ray-2").strip()
LUMA_ASPECT      = os.environ.get("LUMA_ASPECT", "16:9").strip()
LUMA_DURATION_S  = int((os.environ.get("LUMA_DURATION_S") or "5").strip() or 5)
LUMA_BASE_URL    = (os.environ.get("LUMA_BASE_URL", "https://api.lumalabs.ai/dream-machine/v1").strip().rstrip("/"))
LUMA_CREATE_PATH = "/generations"
LUMA_STATUS_PATH = "/generations/{id}"

# Фолбэки Luma
_fallbacks_raw = ",".join([
    os.environ.get("LUMA_FALLBACKS", ""),
    os.environ.get("LUMA_FALLBACK_BASE_URL", "")
])
LUMA_FALLBACKS: list[str] = []
for u in re.split(r"[;,]\s*", _fallbacks_raw):
    if not u:
        continue
    u = u.strip().rstrip("/")
    if u and u != LUMA_BASE_URL and u not in LUMA_FALLBACKS:
        LUMA_FALLBACKS.append(u)

# Runway endpoints
RUNWAY_BASE_URL    = (os.environ.get("RUNWAY_BASE_URL", "https://api.runwayml.com").strip().rstrip("/"))
RUNWAY_CREATE_PATH = "/v1/tasks"
RUNWAY_STATUS_PATH = "/v1/tasks/{id}"

# Таймауты
LUMA_MAX_WAIT_S     = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)
RUNWAY_MAX_WAIT_S   = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "1200").strip() or 1200)
VIDEO_POLL_DELAY_S  = float((os.environ.get("VIDEO_POLL_DELAY_S") or "6.0").strip() or 6.0)

# ───────── UTILS ---------
_LUMA_ACTIVE_BASE: str | None = None  # кэш последнего живого базового URL

async def _pick_luma_base(client: httpx.AsyncClient) -> str:
    global _LUMA_ACTIVE_BASE
    candidates: list[str] = []
    if _LUMA_ACTIVE_BASE:
        candidates.append(_LUMA_ACTIVE_BASE)
    if LUMA_BASE_URL and LUMA_BASE_URL not in candidates:
        candidates.append(LUMA_BASE_URL)
    for b in LUMA_FALLBACKS:
        if b not in candidates:
            candidates.append(b)
    for base in candidates:
        try:
            url = f"{base}{LUMA_CREATE_PATH}"
            r = await client.options(url, timeout=10.0)
            if r.status_code in (200, 201, 202, 204, 400, 401, 403, 404, 405):
                _LUMA_ACTIVE_BASE = base
                if base != LUMA_BASE_URL:
                    log.info("Luma base switched to fallback: %s", base)
                return base
        except Exception as e:
            log.warning("Luma base probe failed for %s: %s", base, e)
    return LUMA_BASE_URL or "https://api.lumalabs.ai/dream-machine/v1"

# Payments / DB
PROVIDER_TOKEN = os.environ.get("PROVIDER_TOKEN_YOOKASSA", "").strip()
CURRENCY       = "RUB"
DB_PATH        = os.environ.get("DB_PATH", "subs.db")

PLAN_PRICE_TABLE = {
    "start":    {"month": 499,  "quarter": 1299, "year": 4490},
    "pro":      {"month": 999,  "quarter": 2799, "year": 8490},
    "ultimate": {"month": 1999, "quarter": 5490, "year": 15990},
}
TERM_MONTHS = {"month": 1, "quarter": 3, "year": 12}

MIN_RUB_FOR_INVOICE = int(os.environ.get("MIN_RUB_FOR_INVOICE", "100") or "100")

PORT = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")
if not OPENAI_API_KEY:
    raise RuntimeError("ENV OPENAI_API_KEY is missing")
    
# ── Безлимит ──
def _parse_ids_csv(s: str) -> set[int]:
    return set(int(x) for x in s.split(",") if x.strip().isdigit())

UNLIM_USER_IDS   = _parse_ids_csv(os.environ.get("UNLIM_USER_IDS",""))
UNLIM_USERNAMES  = set(s.strip().lstrip("@").lower() for s in os.environ.get("UNLIM_USERNAMES","").split(",") if s.strip())
UNLIM_USERNAMES.add("gpt5pro_support")

OWNER_ID           = int(os.environ.get("OWNER_ID","0") or "0")
FORCE_OWNER_UNLIM  = os.environ.get("FORCE_OWNER_UNLIM","1").strip().lower() not in ("0","false","no")

def is_unlimited(user_id: int, username: str | None = None) -> bool:
    if FORCE_OWNER_UNLIM and OWNER_ID and user_id == OWNER_ID:
        return True
    if user_id in UNLIM_USER_IDS:
        return True
    if username and username.lower().lstrip("@") in UNLIM_USERNAMES:
        return True
    return False

# ── Premium page URL ──
def _make_tariff_url(src: str = "subscribe") -> str:
    base = (WEBAPP_URL or f"{PUBLIC_URL.rstrip('/')}/premium.html").strip()
    if src:
        sep = "&" if "?" in base else "?"
        base = f"{base}{sep}src={src}"
    if BOT_USERNAME:
        sep = "&" if "?" in base else "?"
        base = f"{base}{sep}bot={BOT_USERNAME}"
    return base
TARIFF_URL = _make_tariff_url("subscribe")

# ── OpenAI clients ──
from openai import OpenAI

def _ascii_or_none(s: str | None):
    if not s:
        return None
    try:
        s.encode("ascii")
        return s
    except Exception:
        return None

def _ascii_label(s: str | None) -> str:
    s = (s or "").strip() or "Item"
    try:
        s.encode("ascii")
        return s[:32]
    except Exception:
        return "Item"

# HTTP stub (healthcheck + /premium.html redirect)
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
                if WEBAPP_URL:
                    self.send_response(302)
                    self.send_header("Location", WEBAPP_URL)
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<html><body><h3>Premium page</h3><p>Set WEBAPP_URL env.</p></body></html>")
                return
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"not found")
        def log_message(self, *_):  # silent
            return
    try:
        srv = HTTPServer(("0.0.0.0", PORT), _H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log.info("HTTP stub bound on 0.0.0.0:%s", PORT)
    except Exception as e:
        log.exception("HTTP stub start failed: %s", e)

# Text LLM (OpenRouter base autodetect)
_auto_base = OPENAI_BASE_URL
if not _auto_base and (OPENAI_API_KEY.startswith("sk-or-") or "openrouter" in (OPENAI_BASE_URL or "").lower()):
    _auto_base = "https://openrouter.ai/api/v1"
    log.info("Auto-select OpenRouter base_url for text LLM.")

default_headers = {}
ref = _ascii_or_none(OPENROUTER_SITE_URL)
ttl = _ascii_or_none(OPENROUTER_APP_NAME)
if ref:
    default_headers["HTTP-Referer"] = ref
if ttl:
    default_headers["X-Title"] = ttl

try:
    oai_llm = OpenAI(api_key=OPENAI_API_KEY, base_url=_auto_base or None, default_headers=default_headers or None)
except TypeError:
    oai_llm = OpenAI(api_key=OPENAI_API_KEY, base_url=_auto_base or None)

oai_stt = OpenAI(api_key=OPENAI_STT_KEY) if OPENAI_STT_KEY else None
oai_img = OpenAI(api_key=OPENAI_IMAGE_KEY, base_url=IMAGES_BASE_URL)
oai_tts = OpenAI(api_key=OPENAI_TTS_KEY, base_url=OPENAI_TTS_BASE_URL)

# Tavily (опционально)
try:
    if TAVILY_API_KEY:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
    else:
        tavily = None
except Exception:
    tavily = None

# ───────── DB: subscriptions ─────────
def db_init():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER PRIMARY KEY,
        until_ts INTEGER NOT NULL,
        tier TEXT
    )""")
    con.commit(); con.close()

def _utcnow():
    return datetime.now(timezone.utc)

def activate_subscription(user_id: int, months: int = 1):
    now = _utcnow()
    until = now + timedelta(days=30 * months)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT until_ts FROM subscriptions WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row and row[0] and row[0] > int(now.timestamp()):
        current_until = datetime.fromtimestamp(row[0], tz=timezone.utc)
        until = current_until + timedelta(days=30 * months)
    cur.execute("""
        INSERT INTO subscriptions (user_id, until_ts)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET until_ts=excluded.until_ts
    """, (user_id, int(until.timestamp())))
    con.commit(); con.close()
    return until

def get_subscription_until(user_id: int):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT until_ts FROM subscriptions WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    con.close()
    return None if not row else datetime.fromtimestamp(row[0], tz=timezone.utc)

def set_subscription_tier(user_id: int, tier: str):
    tier = (tier or "pro").lower()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO subscriptions(user_id, until_ts, tier) VALUES (?, ?, ?)",
                (user_id, int(_utcnow().timestamp()), tier))
    cur.execute("UPDATE subscriptions SET tier=? WHERE user_id=?", (tier, user_id))
    con.commit(); con.close()

def activate_subscription_with_tier(user_id: int, tier: str, months: int):
    until = activate_subscription(user_id, months=months)
    set_subscription_tier(user_id, tier)
    return until

def get_subscription_tier(user_id: int) -> str:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT until_ts, tier FROM subscriptions WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close()
    if not row:
        return "free"
    until_ts, tier = row[0], (row[1] or "pro")
    if until_ts and datetime.fromtimestamp(until_ts, tz=timezone.utc) > _utcnow():
        return (tier or "pro").lower()
    return "free"

# ───────── SPEECH (STT + TTS) ─────────

VOICE_PREFS_DB = os.environ.get("VOICE_PREFS_DB", "voice_prefs.db")

def _voice_db_init():
    con = sqlite3.connect(VOICE_PREFS_DB)
    con.execute("CREATE TABLE IF NOT EXISTS voice_prefs(user_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL)")
    con.commit(); con.close()

def _voice_is_enabled(user_id: int) -> bool:
    con = sqlite3.connect(VOICE_PREFS_DB)
    cur = con.cursor()
    cur.execute("SELECT enabled FROM voice_prefs WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    return bool(row and row[0])

def _voice_set(user_id: int, enabled: bool):
    con = sqlite3.connect(VOICE_PREFS_DB)
    cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO voice_prefs(user_id, enabled) VALUES (?, ?)",
                (user_id, 1 if enabled else 0))
    con.commit(); con.close()

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _voice_set(update.effective_user.id, True)
    await update.effective_message.reply_text("🔊 Озвучка включена.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _voice_set(update.effective_user.id, False)
    await update.effective_message.reply_text("🔇 Озвучка выключена.")

# === STT: распознавание речи ===
async def _stt_from_file(file_bytes: bytes, mime: str = "audio/ogg") -> str | None:
    if DEEPGRAM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(
                    "https://api.deepgram.com/v1/listen?model=nova-2&language=ru",
                    headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
                    content=file_bytes
                )
                r.raise_for_status()
                js = r.json()
                return js.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("transcript")
        except Exception as e:
            log.warning("Deepgram STT failed: %s", e)

    if oai_stt:
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".ogg") as f:
                f.write(file_bytes)
                f.flush()
                resp = oai_stt.audio.transcriptions.create(model=TRANSCRIBE_MODEL, file=open(f.name, "rb"))
            return getattr(resp, "text", None)
        except Exception as e:
            log.warning("OpenAI Whisper STT failed: %s", e)
    return None

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        f = await update.message.voice.get_file()
        b = await f.download_as_bytearray()
        await update.effective_chat.send_action(ChatAction.TYPING)
        text = await _stt_from_file(bytes(b))
        if not text:
            await update.effective_message.reply_text("Не удалось распознать речь.")
            return
        await update.effective_message.reply_text(f"🗣️ Распознано: {text}")
        # передаём как обычный запрос
        await on_text(update, context)
    except Exception as e:
        log.exception("voice handler error: %s", e)
        await update.effective_message.reply_text("Ошибка обработки аудио.")

# === TTS: синтез речи ===
def _tts_bytes_sync(text: str) -> bytes | None:
    try:
        # попытка 1 — opus
        r = oai_tts.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=OPENAI_TTS_VOICE,
            input=text,
            format="opus"
        )
        audio = getattr(r, "content", None)
        if audio is None and hasattr(r, "read"):
            audio = r.read()
        if isinstance(audio, (bytes, bytearray)) and len(audio) > 0:
            return bytes(audio)
    except Exception as e:
        log.warning("TTS opus failed: %s", e)
    try:
        # попытка 2 — mp3
        r = oai_tts.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=OPENAI_TTS_VOICE,
            input=text,
            format="mp3"
        )
        audio = getattr(r, "content", None)
        if audio is None and hasattr(r, "read"):
            audio = r.read()
        if isinstance(audio, (bytes, bytearray)) and len(audio) > 0:
            return bytes(audio)
    except Exception as e:
        log.warning("TTS mp3 failed: %s", e)
    try:
        # попытка 3 — wav
        r = oai_tts.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=OPENAI_TTS_VOICE,
            input=text,
            format="wav"
        )
        audio = getattr(r, "content", None)
        if audio is None and hasattr(r, "read"):
            audio = r.read()
        if isinstance(audio, (bytes, bytearray)) and len(audio) > 0:
            return bytes(audio)
    except Exception as e:
        log.exception("TTS wav failed: %s", e)
    return None

async def maybe_tts_reply(update: Update, text: str):
    """Отправка текста и озвучки при включённой функции"""
    if not _voice_is_enabled(update.effective_user.id):
        await update.effective_message.reply_text(text)
        return
    audio = _tts_bytes_sync(text)
    if not audio:
        await update.effective_message.reply_text(text)
        return
    bio = BytesIO(audio)
    if audio[:4] == b'OggS':
        bio.name = "say.ogg"
        await update.effective_message.reply_voice(voice=InputFile(bio), caption=text)
    else:
        bio.name = "say.mp3"
        await update.effective_message.reply_audio(audio=InputFile(bio), caption=text)
# ───────── IMAGES / PHOTO EDIT / ANIMATION ─────────

_last_photo: dict[int, bytes] = {}
_pending_edit: dict[int, dict] = {}

def _safe_caption(prompt: str, engine: str, duration: int, ar: str) -> str:
    return f"🎬 {engine}: {duration}s {ar}\n\n📝 {prompt}"

def _norm_ar(ar: str) -> str:
    ar = str(ar or "").replace("x", ":")
    if ":" not in ar:
        return f"{ar}:1"
    return ar

# получение изображения как bytes
async def _download_photo_as_bytes(update: Update) -> bytes | None:
    photo = update.message.photo[-1] if update.message.photo else None
    if not photo:
        return None
    file = await photo.get_file()
    data = await file.download_as_bytearray()
    return bytes(data)

# ─── базовые кнопки редактирования фото ───
def _photo_edit_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✂️ Убрать фон", callback_data="edit:remove_bg"),
         InlineKeyboardButton("🏖️ Заменить фон", callback_data="edit:replace_bg")],
        [InlineKeyboardButton("✨ Улучшить", callback_data="edit:enhance"),
         InlineKeyboardButton("🎨 Стилизация", callback_data="edit:stylize")],
        [InlineKeyboardButton("🎞️ Оживить фото", callback_data="edit:animate")]
    ])

# получение фото без подписи
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = await _download_photo_as_bytes(update)
        if not data:
            await update.effective_message.reply_text("Не удалось получить фото.")
            return
        user_id = update.effective_user.id
        _last_photo[user_id] = data
        await update.effective_message.reply_text("Что сделать с фото?", reply_markup=_photo_edit_kb())
    except Exception as e:
        log.exception("on_photo failed: %s", e)
        await update.effective_message.reply_text("Ошибка при обработке фото.")

# обработка фото с подписью (оживление / запрос)
async def on_photo_with_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = (update.message.caption or "").lower()
    if not caption:
        return await on_photo(update, context)
    if "ожив" in caption or "аним" in caption:
        data = await _download_photo_as_bytes(update)
        if not data:
            await update.effective_message.reply_text("Не удалось загрузить фото.")
            return
        _last_photo[update.effective_user.id] = data
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎥 Luma", callback_data="choose:luma:anim"),
             InlineKeyboardButton("🎬 Runway", callback_data="choose:runway:anim")]
        ])
        await update.effective_message.reply_text("Выбери движок для оживления:", reply_markup=kb)
    else:
        await update.effective_message.reply_text("📸 Фото получено, но не понял задачу. Что сделать?")

# обработка callback’ов редактирования
async def on_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    data = (q.data or "").split(":")
    if len(data) < 2:
        await q.edit_message_text("Ошибка команды.")
        return
    action = data[1]
    img = _last_photo.get(user_id)
    if not img:
        await q.edit_message_text("Нет сохранённого фото. Отправь заново.")
        return

    # обработка действий
    if action == "remove_bg":
        await q.edit_message_text("Удаляю фон…")
        try:
            resp = oai_img.images.edits(
                model=IMAGES_MODEL,
                image=BytesIO(img),
                prompt="Remove the background, keep subject clear and centered.",
                size="1024x1024",
                n=1
            )
            b64 = resp.data[0].b64_json
            await q.message.reply_photo(base64.b64decode(b64), caption="✅ Фон удалён.")
        except Exception as e:
            log.exception("remove_bg error: %s", e)
            await q.message.reply_text("Не удалось удалить фон.")
        return

    if action == "replace_bg":
        _pending_edit[user_id] = {"action": "replace_bg"}
        await q.edit_message_text("На что заменить фон? Напиши текстом.")
        return

    if action == "enhance":
        await q.edit_message_text("✨ Улучшаю качество…")
        try:
            resp = oai_img.images.edits(
                model=IMAGES_MODEL,
                image=BytesIO(img),
                prompt="Enhance image quality, details, and lighting.",
                size="1024x1024",
                n=1
            )
            b64 = resp.data[0].b64_json
            await q.message.reply_photo(base64.b64decode(b64), caption="✅ Фото улучшено.")
        except Exception as e:
            log.exception("enhance error: %s", e)
            await q.message.reply_text("Не удалось улучшить фото.")
        return

    if action == "stylize":
        await q.edit_message_text("🎨 Применяю стиль мультфильма…")
        try:
            resp = oai_img.images.edits(
                model=IMAGES_MODEL,
                image=BytesIO(img),
                prompt="Make it cartoon style, bright, artistic, colorful.",
                size="1024x1024",
                n=1
            )
            b64 = resp.data[0].b64_json
            await q.message.reply_photo(base64.b64decode(b64), caption="✅ Стилизация завершена.")
        except Exception as e:
            log.exception("stylize error: %s", e)
            await q.message.reply_text("Не удалось стилизовать фото.")
        return

    if action == "animate":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎥 Luma", callback_data="choose:luma:anim"),
             InlineKeyboardButton("🎬 Runway", callback_data="choose:runway:anim")]
        ])
        await q.edit_message_text("Выбери движок для оживления:", reply_markup=kb)
        return

# обработка ввода текста после replace_bg (ожидание текста)
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    pend = _pending_edit.get(user_id)
    if pend and pend.get("action") == "replace_bg":
        _pending_edit.pop(user_id, None)
        img = _last_photo.get(user_id)
        if not img:
            await update.effective_message.reply_text("Нет последнего фото для редактирования.")
            return
        await update.effective_message.reply_text("Меняю фон…")
        try:
            resp = oai_img.images.edits(
                model=IMAGES_MODEL,
                image=BytesIO(img),
                prompt=f"Replace the background to: {text}. Keep the subject intact, clean edges.",
                size="1024x1024",
                n=1
            )
            b64 = resp.data[0].b64_json
            await update.effective_message.reply_photo(photo=base64.b64decode(b64), caption="✅ Готово.")
        except Exception as e:
            log.exception("replace_bg edit error: %s", e)
            await update.effective_message.reply_text("Не удалось заменить фон.")
        return

    # иначе — стандартный текстовый пайплайн
    await _process_text(update, context, text)

# выбор движка (Luma / Runway)
async def on_choose_engine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    data = (q.data or "").split(":")
    if len(data) < 3:
        await q.edit_message_text("Ошибка выбора.")
        return
    engine = data[1]
    mode = data[2]
    img = _last_photo.get(user_id)
    if not img:
        await q.edit_message_text("Нет сохранённого фото.")
        return
    if mode == "anim":
        await q.edit_message_text(f"Создаю видео через {engine}…")
        try:
            if engine == "luma":
                tid = await _luma_create(prompt="Animate this portrait naturally.", image_bytes=img)
                await _luma_poll_and_send(update, context, tid, "Оживление Luma")
            else:
                tid = await _runway_create(prompt="Animate this portrait naturally.", image_bytes=img)
                await _runway_poll_and_send(update, context, tid, "Оживление Runway")
        except Exception as e:
            log.exception("engine animate error: %s", e)
            await q.message.reply_text("Ошибка создания видео.")

# ───────── LUMA/RUNWAY: image-to-video SHIMS (animate photo) ─────────
# Совместимо с уже существующими текстовыми функциями: мы расширяем сигнатуры,
# добавляя поддержку image_bytes. Старые вызовы продолжают работать.

def _b64_data_url(image_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")

async def _send_video_from_url_or_bytes(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str | None, caption: str):
    if not url:
        await update.effective_message.reply_text("⚠️ Видео не получено от движка.")
        return
    try:
        # Сначала пробуем отправить по URL (проще и быстрее для Telegram)
        await update.effective_message.reply_video(video=url, caption=caption)
    except Exception:
        # Если Telegram не принял URL — скачаем и отправим файлом
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                r = await client.get(url)
            r.raise_for_status()
            bio = BytesIO(r.content); bio.name = "video.mp4"
            await update.effective_message.reply_video(video=InputFile(bio), caption=caption)
        except Exception as e:
            log.exception("send video failed: %s", e)
            await update.effective_message.reply_text("⚠️ Видео готово, но не удалось отправить файл.")

# ====== Luma (override: добавляем image_bytes) ======
async def _luma_create(
    prompt: str,
    duration_s: int | None = None,
    ar: str | None = None,
    image_bytes: bytes | None = None
) -> str | None:
    """
    Универсальный create для Luma:
    - текст→видео (как раньше): задаём prompt, duration_s, ar
    - фото→видео (оживление): дополнительно передаём image_bytes
    """
    if not LUMA_API_KEY:
        raise RuntimeError("LUMA_API_KEY is missing")

    # подберём duration/aspect, если не указаны (для обратной совместимости)
    duration_s = int(duration_s or LUMA_DURATION_S or 9)
    ar = _norm_ar(ar or LUMA_ASPECT or "16:9")

    headers = {
        "Authorization": f"Bearer {LUMA_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LUMA_MODEL,
        "prompt": prompt or "Animate this image naturally.",
        "duration": _luma_duration_string(duration_s),  # "5s"/"9s"/"10s"
        "aspect_ratio": ar,
    }
    # Если пришло фото — добавляем data URL (типовой формат для image-to-video API)
    if image_bytes:
        payload["image"] = _b64_data_url(image_bytes)

    last_text = None
    async with httpx.AsyncClient(timeout=120.0) as client:
        # порядок кандидатов (detected → base → fallbacks)
        candidates, seen = [], set()
        global _LUMA_LAST_BASE, _LUMA_LAST_ERR
        try:
            detected = await _pick_luma_base(client)
            if detected:
                b = detected.rstrip("/")
                if b and b not in seen:
                    candidates.append(b); seen.add(b)
        except Exception as e:
            log.warning("Luma: auto-detect base failed: %s", e)
        b = (LUMA_BASE_URL or "").strip().rstrip("/")
        if b and b not in seen: candidates.append(b); seen.add(b)
        for fb in LUMA_FALLBACKS:
            u = (fb or "").strip().rstrip("/")
            if u and u not in seen: candidates.append(u); seen.add(u)

        for base in candidates:
            url = f"{base}{LUMA_CREATE_PATH}"
            try:
                r = await client.post(url, headers=headers, json=payload)
                last_text = r.text
                r.raise_for_status()
                j = r.json()
                job_id = (
                    j.get("id")
                    or j.get("generation_id")
                    or j.get("task_id")
                    or (j.get("data") or {}).get("id")
                )
                if job_id:
                    _LUMA_LAST_BASE = base
                    _LUMA_LAST_ERR = None
                    return str(job_id)
                log.error("Luma create: no job id in response from %s: %s", base, j)
                _LUMA_LAST_ERR = f"no_job_id from {base}: {j}"
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                log.error("Luma create HTTP %s at %s | body=%s", code, base, last_text)
                _LUMA_LAST_ERR = f"HTTP {code} at {base}: {str(last_text)[:600]}"
            except httpx.RequestError as e:
                log.error("Luma create network/http error at %s: %s", base, e)
                _LUMA_LAST_ERR = f"network error at {base}: {e}"
            except Exception as e:
                log.error("Luma create unexpected error at %s: %s | body=%s", base, e, last_text)
                _LUMA_LAST_ERR = f"unexpected at {base}: {e}; body={str(last_text)[:600]}"
    return None

async def _luma_poll_and_send(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    job_id: str,
    caption_title: str,
    prompt: str | None = None,
    duration: int | None = None,
    ar: str | None = None
):
    if not job_id:
        await update.effective_message.reply_text("⚠️ Не удалось создать задачу в Luma.")
        return
    await update.effective_message.reply_text("⏳ Luma рендерит…")
    url, st = await _luma_poll_and_get_url(job_id, base_hint=None)
    if not url:
        await update.effective_message.reply_text(f"⚠️ Luma вернула статус: {st}.")
        return
    cap = _safe_caption(prompt or caption_title, "Luma", int((duration or LUMA_DURATION_S) or 9), _norm_ar(ar or LUMA_ASPECT))
    await _send_video_from_url_or_bytes(update, context, url, cap)

# ====== Runway (override: добавляем image_bytes) ======
async def _runway_create(
    prompt: str,
    duration_s: int | None = None,
    ratio: str | None = None,
    image_bytes: bytes | None = None
) -> str | None:
    """
    Универсальный create для Runway:
    - текст→видео (как раньше): prompt, duration_s, ratio
    - фото→видео (оживление): image_bytes (как init image)
    """
    if not RUNWAY_API_KEY:
        raise RuntimeError("RUNWAY_API_KEY is missing")
    url = f"{RUNWAY_BASE_URL}{RUNWAY_CREATE_PATH}"
    headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Content-Type": "application/json"}

    duration_s = int(duration_s or RUNWAY_DURATION_S or 8)
    ratio = (ratio or RUNWAY_RATIO or "720:1280")

    input_payload = {"prompt": prompt or "Animate this image naturally.", "duration": max(1, duration_s), "ratio": ratio}
    if image_bytes:
        input_payload["image"] = _b64_data_url(image_bytes)

    payload = {"model": RUNWAY_MODEL, "input": input_payload}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, headers=headers, json=payload)
            txt = r.text
            r.raise_for_status()
            j = r.json()
            tid = j.get("id") or (j.get("data") or {}).get("id")
            return str(tid) if tid else None
    except Exception as e:
        log.exception("Runway create error: %s", e)
        return None

async def _runway_poll_and_send(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    task_id: str,
    caption_title: str,
    prompt: str | None = None,
    duration: int | None = None,
    ar: str | None = None
):
    if not task_id:
        await update.effective_message.reply_text("⚠️ Не удалось создать задачу в Runway.")
        return
    await update.effective_message.reply_text("⏳ Runway рендерит…")
    url, st = await _runway_poll_and_get_url(task_id)
    if not url:
        await update.effective_message.reply_text(f"⚠️ Runway вернул статус: {st}.")
        return
    cap = _safe_caption(prompt or caption_title, "Runway", int(duration or RUNWAY_DURATION_S or 8), _norm_ar(ar or "16:9"))
    await _send_video_from_url_or_bytes(update, context, url, cap)

# ───────── COMMANDS / CALLBACKS REGISTRATION ─────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Чат", callback_data="chat"),
         InlineKeyboardButton("📸 Фото", callback_data="photo")],
        [InlineKeyboardButton("🎥 Видео", callback_data="video"),
         InlineKeyboardButton("💳 Подписка", callback_data="plans")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ])
    txt = (
        "👋 *Добро пожаловать в GPT-5 PRO Bot*\n\n"
        "Здесь ты можешь:\n"
        "• генерировать тексты, картинки и видео\n"
        "• оживлять старые фото и делать мультяшные версии\n"
        "• озвучивать ответы голосом\n"
        "• оплачивать подписку через ЮKassa или CryptoBot\n\n"
        "Выбери нужный раздел 👇"
    )
    await update.effective_message.reply_text(txt, reply_markup=kb, parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "ℹ️ *Справка:*\n"
        "Отправь текст — бот ответит.\n"
        "Отправь фото — появятся кнопки редактирования.\n"
        "Скажи голосом — бот распознает и ответит.\n\n"
        "Команды:\n"
        "/voice_on — включить озвучку\n"
        "/voice_off — выключить озвучку\n"
        "/plans — подписка\n"
        "/help — помощь",
        parse_mode="Markdown"
    )

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 ЮKassa", callback_data="pay:yookassa"),
         InlineKeyboardButton("🪙 CryptoBot", callback_data="pay:crypto")],
        [InlineKeyboardButton("📘 Описание тарифов", web_app=WebAppInfo(_make_tariff_url("plans_info")))]
    ])
    text = (
        "💼 *Тарифы GPT-5 PRO:*\n\n"
        "• *Start* — 499 ₽ / мес\n"
        "• *Pro* — 999 ₽ / мес\n"
        "• *Ultimate* — 1999 ₽ / мес\n\n"
        "Выбери способ оплаты 👇"
    )
    await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

# ===== CryptoBot stub ====
async def on_crypto_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    user_id = q.from_user.id
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Оплатить USDT (через CryptoBot)", url="https://t.me/CryptoBot?start=pay")],
        [InlineKeyboardButton("✅ Проверить статус", callback_data=f"crypto:check:{user_id}")]
    ])
    await q.edit_message_text("🪙 Оплата через CryptoBot. После перевода нажми «Проверить статус».", reply_markup=kb)

async def on_crypto_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("✅ Оплата подтверждена (эмуляция). Подписка активирована.")
    activate_subscription_with_tier(q.from_user.id, "pro", 1)

# ===== Unknown Callback handler =====
async def on_unknown_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Команда пока не реализована или устарела.")

# ===== Ошибки / исключения =====
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        log.error("Exception in handler: %s", context.error)
        if update and isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("⚠️ Произошла ошибка. Попробуй позже.")
    except Exception:
        pass

# ===== INIT APP =====
def main():
    db_init(); _voice_db_init(); _start_http_stub()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # --- Команды ---
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("voice_on", cmd_voice_on))
    app.add_handler(CommandHandler("voice_off", cmd_voice_off))

    # --- Медиа ---
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.PHOTO & (~filters.Caption()), on_photo))
    app.add_handler(MessageHandler(filters.PHOTO & filters.Caption(), on_photo_with_caption))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_text))

    # --- Callback’и ---
    app.add_handler(CallbackQueryHandler(on_edit_callback, pattern=r"^edit:"))
    app.add_handler(CallbackQueryHandler(on_choose_engine, pattern=r"^choose:"))
    app.add_handler(CallbackQueryHandler(on_crypto_pay, pattern=r"^pay:crypto"))
    app.add_handler(CallbackQueryHandler(on_crypto_check, pattern=r"^crypto:check"))
    app.add_handler(CallbackQueryHandler(on_unknown_callback))

    app.add_error_handler(on_error)

    # --- Запуск ---
    log.info("Bot started.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

# ───────── HEALTHCHECK / SELFTEST / ENTRY ─────────

def _selftest():
    """Простая самопроверка при старте контейнера"""
    checks = []
    checks.append(("BOT_TOKEN", bool(BOT_TOKEN)))
    checks.append(("OPENAI_API_KEY", bool(OPENAI_API_KEY)))
    checks.append(("OPENAI_IMAGE_KEY", bool(OPENAI_IMAGE_KEY)))
    checks.append(("LUMA_API_KEY", bool(LUMA_API_KEY)))
    checks.append(("RUNWAY_API_KEY", bool(RUNWAY_API_KEY)))
    missing = [n for n, ok in checks if not ok]
    if missing:
        log.warning("⚠️ Missing keys: %s", ", ".join(missing))
    else:
        log.info("✅ All main keys present.")
    return not missing

if __name__ == "__main__":
    log.info("🧠 GPT-5 PRO bot initialization…")
    ok = _selftest()
    if not ok:
        log.warning("Some keys missing — limited functionality.")
    try:
        main()
    except KeyboardInterrupt:
        log.info("🛑 Bot stopped by user.")
    except Exception as e:
        log.exception("Fatal error: %s", e)
