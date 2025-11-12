# -*- coding: utf-8 -*-
"""
GPT-5 ProBot (Render / python-telegram-bot==21.6)

Функции:
• Текст/визион (OpenAI/Router), STT (Deepgram/Whisper), TTS (OpenAI Speech)
• Фото-инструменты: удалить/заменить фон, outpaint, анализ (Vision), раскадровка,
  оживление фото (Runway) + локальный fallback (Ken Burns, OpenCV)
• Видео: Luma / Runway
• Подписки и кошелёк: ЮKassa, CryptoBot, USD-баланс, покупка подписки напрямую через CryptoBot
• Документы: PDF/EPUB/DOCX/FB2/TXT → конспект
"""

import os, re, json, time, base64, logging, asyncio, sqlite3, uuid, contextlib, threading
from io import BytesIO
from datetime import datetime, timedelta, timezone
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

# Опционально для фото-инструментов
try:
    from PIL import Image, ImageFilter
except Exception:
    Image = None; ImageFilter = None

try:
    from rembg import remove as rembg_remove
except Exception:
    rembg_remove = None

# Локальная анимация (fallback)
try:
    import cv2
except Exception:
    cv2 = None

# ───────── LOGGING ─────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("gpt-bot")

# ───────── ENV ─────────
BOT_TOKEN        = (os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
BOT_USERNAME     = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
PUBLIC_URL       = os.getenv("PUBLIC_URL", "").strip()
WEBAPP_URL       = os.getenv("WEBAPP_URL", "").strip()

OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL  = os.getenv("OPENAI_BASE_URL", "").strip()
OPENAI_MODEL     = os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini").strip()

OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "").strip()

USE_WEBHOOK      = os.getenv("USE_WEBHOOK", "1").lower() in ("1","true","yes","on")
WEBHOOK_PATH     = os.getenv("WEBHOOK_PATH", "/tg").strip()
WEBHOOK_SECRET   = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

BANNER_URL       = os.getenv("BANNER_URL", "").strip()
TAVILY_API_KEY   = os.getenv("TAVILY_API_KEY", "").strip()

# STT
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "").strip()
OPENAI_STT_KEY   = os.getenv("OPENAI_STT_KEY", "").strip() or OPENAI_API_KEY
TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1").strip()

# TTS
OPENAI_TTS_KEY       = os.getenv("OPENAI_TTS_KEY", "").strip() or OPENAI_API_KEY
OPENAI_TTS_BASE_URL  = (os.getenv("OPENAI_TTS_BASE_URL", "").strip() or "https://api.openai.com/v1").rstrip("/")
OPENAI_TTS_MODEL     = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip()
OPENAI_TTS_VOICE     = os.getenv("OPENAI_TTS_VOICE", "alloy").strip()
TTS_MAX_CHARS        = int(os.getenv("TTS_MAX_CHARS", "150") or "150")

# Images
OPENAI_IMAGE_KEY    = os.getenv("OPENAI_IMAGE_KEY", "").strip() or OPENAI_API_KEY
IMAGES_BASE_URL     = (os.getenv("OPENAI_IMAGE_BASE_URL", "").strip() or "https://api.openai.com/v1")
IMAGES_MODEL        = "gpt-image-1"

# Luma
LUMA_API_KEY     = os.getenv("LUMA_API_KEY", "").strip()
LUMA_MODEL       = os.getenv("LUMA_MODEL", "ray-2").strip()
LUMA_ASPECT      = os.getenv("LUMA_ASPECT", "16:9").strip()
LUMA_DURATION_S  = int((os.getenv("LUMA_DURATION_S") or "5").strip() or 5)
LUMA_BASE_URL    = (os.getenv("LUMA_BASE_URL", "https://api.lumalabs.ai/dream-machine/v1").strip().rstrip("/"))
LUMA_CREATE_PATH = "/generations"
LUMA_STATUS_PATH = "/generations/{id}"

# Runway
RUNWAY_API_KEY      = os.getenv("RUNWAY_API_KEY", "").strip()
RUNWAY_MODEL        = os.getenv("RUNWAY_MODEL", "gen3a_turbo").strip()
RUNWAY_RATIO        = os.getenv("RUNWAY_RATIO", "720:1280").strip()
RUNWAY_DURATION_S   = int(os.getenv("RUNWAY_DURATION_S", "8") or 8)
RUNWAY_BASE_URL     = (os.getenv("RUNWAY_BASE_URL", "https://api.runwayml.com").strip().rstrip("/"))
RUNWAY_CREATE_PATH  = "/v1/tasks"
RUNWAY_STATUS_PATH  = "/v1/tasks/{id}"

# Таймауты
VIDEO_POLL_DELAY_S  = float((os.getenv("VIDEO_POLL_DELAY_S") or "6.0").strip() or 6.0)
LUMA_MAX_WAIT_S     = int((os.getenv("LUMA_MAX_WAIT_S") or "900").strip() or 900)
RUNWAY_MAX_WAIT_S   = int((os.getenv("RUNWAY_MAX_WAIT_S") or "1200").strip() or 1200)

# Платежи / БД
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN_YOOKASSA", "").strip()
CURRENCY       = "RUB"
DB_PATH        = os.path.abspath(os.getenv("DB_PATH", "subs.db"))

PLAN_PRICE_TABLE = {
    "start":    {"month": 499,  "quarter": 1299, "year": 4490},
    "pro":      {"month": 999,  "quarter": 2799, "year": 8490},
    "ultimate": {"month": 1999, "quarter": 5490, "year": 15990},
}
TERM_MONTHS = {"month": 1, "quarter": 3, "year": 12}
USD_RUB = float(os.getenv("USD_RUB", "100"))
MIN_RUB_FOR_INVOICE = int(os.getenv("MIN_RUB_FOR_INVOICE", "100") or "100")

# CryptoBot
CRYPTO_PAY_API_TOKEN = os.getenv("CRYPTO_PAY_API_TOKEN", "").strip()
CRYPTO_BASE = "https://pay.crypt.bot/api"
TON_USD_RATE = float(os.getenv("TON_USD_RATE", "5.0") or "5.0")  # запасной курс

PORT = int(os.getenv("PORT", "10000") or "10000")

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("https://"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")
if not OPENAI_API_KEY:
    raise RuntimeError("ENV OPENAI_API_KEY missing")

# ───────── Helpers: OpenAI ─────────
from openai import OpenAI
def _ascii_label(s: str | None) -> str:
    s = (s or "").strip() or "Item"
    try:
        s.encode("ascii"); return s[:32]
    except Exception:
        return "Item"

_auto_base = OPENAI_BASE_URL
if not _auto_base and (OPENAI_API_KEY.startswith("sk-or-") or "openrouter" in (OPENAI_BASE_URL or "").lower()):
    _auto_base = "https://openrouter.ai/api/v1"
    log.info("Auto-select OpenRouter base_url for text LLM.")

default_headers = {}
if OPENROUTER_SITE_URL: default_headers["HTTP-Referer"] = OPENROUTER_SITE_URL
if OPENROUTER_APP_NAME: default_headers["X-Title"] = OPENROUTER_APP_NAME

try:
    oai_llm = OpenAI(api_key=OPENAI_API_KEY, base_url=_auto_base or None, default_headers=default_headers or None)
except TypeError:
    oai_llm = OpenAI(api_key=OPENAI_API_KEY, base_url=_auto_base or None)

oai_img = OpenAI(api_key=OPENAI_IMAGE_KEY, base_url=IMAGES_BASE_URL)

SYSTEM_PROMPT = (
    "Ты дружелюбный и лаконичный ассистент на русском. Отвечай по сути, структурируй списками/шагами, не выдумывай факты."
)
VISION_SYSTEM_PROMPT = (
    "Опиши кратко содержимое изображения (объекты, текст). Не идентифицируй людей по имени."
)

def _pick_vision_model() -> str:
    try:
        mv = globals().get("OPENAI_VISION_MODEL")
        return (mv or OPENAI_MODEL).strip()
    except Exception:
        return OPENAI_MODEL

async def ask_openai_text(user_text: str, web_ctx: str = "") -> str:
    user_text = (user_text or "").strip()
    if not user_text: return "Пустой запрос."
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({"role": "system", "content": f"Контекст:\n{web_ctx}"})
    messages.append({"role": "user", "content": user_text})
    last_err = None
    for attempt in range(3):
        try:
            resp = oai_llm.chat.completions.create(model=OPENAI_MODEL, messages=messages, temperature=0.6)
            txt = (resp.choices[0].message.content or "").strip()
            if txt: return txt
        except Exception as e:
            last_err = e; log.warning("OpenAI chat attempt %d failed: %s", attempt+1, e)
            await asyncio.sleep(0.8 * (attempt+1))
    log.error("ask_openai_text failed: %s", last_err)
    return "⚠️ Сейчас не получилось получить ответ от модели. Повтори позже."

async def ask_openai_vision(user_text: str, img_b64: str, mime: str) -> str:
    try:
        prompt = (user_text or "Опиши, что на изображении и какой там текст.").strip()
        resp = oai_llm.chat.completions.create(
            model=_pick_vision_model(),
            messages=[
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}}
                ]}
            ],
            temperature=0.4,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("Vision error: %s", e)
        return "Не удалось проанализировать изображение."

# ───────── DB (subs, usage, wallet, kv, prefs) ─────────
def _utcnow(): return datetime.now(timezone.utc)

def db_init():
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS subscriptions(
        user_id INTEGER PRIMARY KEY, until_ts INTEGER NOT NULL, tier TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS usage_daily(
        user_id INTEGER, ymd TEXT, text_count INTEGER DEFAULT 0,
        luma_usd REAL DEFAULT 0.0, runway_usd REAL DEFAULT 0.0, img_usd REAL DEFAULT 0.0,
        PRIMARY KEY(user_id, ymd))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS wallet(
        user_id INTEGER PRIMARY KEY, luma_usd REAL DEFAULT 0.0,
        runway_usd REAL DEFAULT 0.0, img_usd REAL DEFAULT 0.0, usd REAL DEFAULT 0.0)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS user_prefs(user_id INTEGER PRIMARY KEY, tts_on INTEGER DEFAULT 0)""")
    con.commit(); con.close()

def kv_get(key: str, default: str | None = None) -> str | None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT value FROM kv WHERE key=?", (key,)); row = cur.fetchone(); con.close()
    return (row[0] if row else default)

def kv_set(key: str, value: str):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?,?)", (key, value))
    con.commit(); con.close()

def activate_subscription(user_id: int, months: int = 1):
    now = _utcnow(); until = now + timedelta(days=30*months)
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT until_ts FROM subscriptions WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if row and row[0] and row[0] > int(now.timestamp()):
        current_until = datetime.fromtimestamp(row[0], tz=timezone.utc)
        until = current_until + timedelta(days=30*months)
    cur.execute("""INSERT INTO subscriptions(user_id, until_ts, tier) VALUES(?,?,COALESCE(tier,'pro'))
                   ON CONFLICT(user_id) DO UPDATE SET until_ts=excluded.until_ts""", (user_id, int(until.timestamp())))
    con.commit(); con.close(); return until

def set_subscription_tier(user_id: int, tier: str):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO subscriptions(user_id, until_ts, tier) VALUES(?,?,?)",
                (user_id, int(_utcnow().timestamp()), (tier or "pro")))
    cur.execute("UPDATE subscriptions SET tier=? WHERE user_id=?", ((tier or "pro"), user_id))
    con.commit(); con.close()

def activate_subscription_with_tier(user_id: int, tier: str, months: int):
    until = activate_subscription(user_id, months); set_subscription_tier(user_id, tier); return until

def get_subscription_tier(user_id: int) -> str:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT until_ts, tier FROM subscriptions WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close()
    if not row: return "free"
    until_ts, tier = row[0], (row[1] or "pro")
    if until_ts and datetime.fromtimestamp(until_ts, tz=timezone.utc) > _utcnow():
        return (tier or "pro").lower()
    return "free"

def _today_ymd() -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _usage_row(user_id: int, ymd: str | None = None):
    ymd = ymd or _today_ymd()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO usage_daily(user_id, ymd) VALUES (?,?)", (user_id, ymd)); con.commit()
    cur.execute("SELECT text_count, luma_usd, runway_usd, img_usd FROM usage_daily WHERE user_id=? AND ymd=?",
                (user_id, ymd))
    row = cur.fetchone(); con.close()
    return {"text_count": row[0], "luma_usd": row[1], "runway_usd": row[2], "img_usd": row[3]}

def _usage_update(user_id: int, **delta):
    ymd = _today_ymd()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    row = _usage_row(user_id, ymd)
    cur.execute("""UPDATE usage_daily SET
        text_count=?, luma_usd=?, runway_usd=?, img_usd=? WHERE user_id=? AND ymd=?""",
        (row["text_count"]+delta.get("text_count",0),
         row["luma_usd"]+delta.get("luma_usd",0.0),
         row["runway_usd"]+delta.get("runway_usd",0.0),
         row["img_usd"]+delta.get("img_usd",0.0),
         user_id, ymd))
    con.commit(); con.close()

def _wallet_total_get(user_id: int) -> float:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES (?)", (user_id,)); con.commit()
    cur.execute("SELECT usd FROM wallet WHERE user_id=?", (user_id,)); row = cur.fetchone(); con.close()
    return float(row[0] if row and row[0] is not None else 0.0)

def _wallet_total_add(user_id: int, usd: float):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("UPDATE wallet SET usd = COALESCE(usd,0)+? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close()

def _wallet_total_take(user_id: int, usd: float) -> bool:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT usd FROM wallet WHERE user_id=?", (user_id,))
    row = cur.fetchone(); bal = float(row[0] if row and row[0] is not None else 0.0)
    if bal + 1e-9 < usd: con.close(); return False
    cur.execute("UPDATE wallet SET usd = usd - ? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close(); return True

# ───────── Limits & pricing ─────────
ONEOFF_MARKUP_DEFAULT = float(os.getenv("ONEOFF_MARKUP_DEFAULT", "1.0"))
ONEOFF_MARKUP_RUNWAY  = float(os.getenv("ONEOFF_MARKUP_RUNWAY",  "0.5"))
LUMA_RES_HINT         = os.getenv("LUMA_RES", "720p").lower()
RUNWAY_UNIT_COST_USD  = float(os.getenv("RUNWAY_UNIT_COST_USD", "7.0"))
IMG_COST_USD          = float(os.getenv("IMG_COST_USD", "0.05"))

LIMITS = {
    "free":      {"text_per_day": 5,    "luma_budget_usd": 0.40, "runway_budget_usd": 0.0,  "img_budget_usd": 0.05},
    "start":     {"text_per_day": 200,  "luma_budget_usd": 0.8,  "runway_budget_usd": 0.0,  "img_budget_usd": 0.2},
    "pro":       {"text_per_day": 1000, "luma_budget_usd": 4.0,  "runway_budget_usd": 7.0,  "img_budget_usd": 1.0},
    "ultimate":  {"text_per_day": 5000, "luma_budget_usd": 8.0,  "runway_budget_usd": 14.0, "img_budget_usd": 2.0},
}

OWNER_ID = int(os.getenv("OWNER_ID","0") or "0")
def _limits_for(user_id: int) -> dict:
    tier = get_subscription_tier(user_id)
    d = LIMITS.get(tier, LIMITS["free"]).copy(); d["tier"] = tier; return d

def check_text_and_inc(user_id: int) -> tuple[bool, int, str]:
    lim = _limits_for(user_id); row = _usage_row(user_id); left = max(0, lim["text_per_day"]-row["text_count"])
    if left <= 0: return False, 0, lim["tier"]
    _usage_update(user_id, text_count=1); return True, left-1, lim["tier"]

def _calc_oneoff_price_rub(engine: str, usd_cost: float) -> int:
    markup = ONEOFF_MARKUP_RUNWAY if engine == "runway" else ONEOFF_MARKUP_DEFAULT
    rub = usd_cost * (1.0 + markup) * USD_RUB
    val = int(rub + 0.999)
    return max(MIN_RUB_FOR_INVOICE, val)

# ───────── TTS ─────────
def _tts_bytes_sync(text: str) -> bytes | None:
    try:
        if not OPENAI_TTS_KEY: return None
        if OPENAI_TTS_KEY.startswith("sk-or-"):
            log.error("TTS key looks like OpenRouter (sk-or-...). Provide OpenAI key."); return None
        url = f"{OPENAI_TTS_BASE_URL}/audio/speech"
        payload = {"model": OPENAI_TTS_MODEL, "voice": OPENAI_TTS_VOICE, "input": text, "format": "ogg"}
        headers = {"Authorization": f"Bearer {OPENAI_TTS_KEY}", "Content-Type": "application/json"}
        r = httpx.post(url, headers=headers, json=payload, timeout=60.0); r.raise_for_status()
        return r.content if r.content else None
    except Exception as e:
        log.exception("TTS HTTP error: %s", e); return None

def _tts_get(user_id: int) -> bool:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO user_prefs(user_id, tts_on) VALUES (?,0)", (user_id,)); con.commit()
    cur.execute("SELECT tts_on FROM user_prefs WHERE user_id=?", (user_id,)); row = cur.fetchone(); con.close()
    return bool(row and row[0])

def _tts_set(user_id: int, on: bool):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO user_prefs(user_id, tts_on) VALUES (?,?)", (user_id, 1 if on else 0))
    cur.execute("UPDATE user_prefs SET tts_on=? WHERE user_id=?", (1 if on else 0, user_id))
    con.commit(); con.close()

async def maybe_tts_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    if not _tts_get(update.effective_user.id): return
    text = (text or "").strip()
    if not text: return
    if len(text) > TTS_MAX_CHARS:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text(f"🔇 Озвучка выключена: текст длиннее {TTS_MAX_CHARS} символов.")
        return
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VOICE)
        audio = await asyncio.to_thread(_tts_bytes_sync, text)
        if not audio:
            with contextlib.suppress(Exception): await update.effective_message.reply_text("🔇 Не удалось синтезировать голос.")
            return
        bio = BytesIO(audio); bio.seek(0); bio.name = "say.ogg"
        await update.effective_message.reply_voice(voice=InputFile(bio), caption=text)
    except Exception as e:
        log.exception("maybe_tts_reply error: %s", e)

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, True);  await update.effective_message.reply_text("🔊 Озвучка включена.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, False); await update.effective_message.reply_text("🔈 Озвучка выключена.")

# ───────── STT ─────────
from openai import OpenAI as _OpenAI_STT
OPENAI_STT_MODEL    = (os.getenv("OPENAI_STT_MODEL") or "whisper-1").strip()
OPENAI_STT_KEY      = (os.getenv("OPENAI_STT_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_STT_BASE_URL = (os.getenv("OPENAI_STT_BASE_URL") or "https://api.openai.com/v1").rstrip("/")

def _oai_stt_client(): return _OpenAI_STT(api_key=OPENAI_STT_KEY, base_url=OPENAI_STT_BASE_URL)

def _mime_from_filename(fn: str) -> str:
    fnl = (fn or "").lower()
    if fnl.endswith((".ogg", ".oga")): return "audio/ogg"
    if fnl.endswith(".mp3"):           return "audio/mpeg"
    if fnl.endswith((".m4a", ".mp4")): return "audio/mp4"
    if fnl.endswith(".wav"):           return "audio/wav"
    if fnl.endswith(".webm"):          return "audio/webm"
    return "application/octet-stream"

async def transcribe_audio(buf: BytesIO, filename_hint: str = "audio.ogg") -> str:
    data = buf.getvalue()
    if DEEPGRAM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                params = {"model":"nova-2","language":"ru","smart_format":"true","punctuate":"true"}
                headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": _mime_from_filename(filename_hint)}
                r = await client.post("https://api.deepgram.com/v1/listen", params=params, headers=headers, content=data)
                r.raise_for_status()
                dg = r.json()
                text = (dg.get("results",{}).get("channels",[{}])[0].get("alternatives",[{}])[0].get("transcript","") or "").strip()
                if text: return text
        except Exception as e:
            log.exception("Deepgram STT error: %s", e)
    if OPENAI_STT_KEY:
        try:
            bio = BytesIO(data); bio.seek(0); setattr(bio, "name", filename_hint)
            tr = _oai_stt_client().audio.transcriptions.create(model=OPENAI_STT_MODEL, file=bio)
            return (tr.text or "").strip()
        except Exception as e:
            log.exception("Whisper STT error: %s", e)
    return ""

# ───────── UI / тексты ─────────
def _make_tariff_url(src: str = "subscribe") -> str:
    base = (WEBAPP_URL or f"{PUBLIC_URL.rstrip('/')}/premium.html").strip()
    if src: base += ("&" if "?" in base else "?") + f"src={src}"
    if BOT_USERNAME: base += ("&" if "?" in base else "?") + f"bot={BOT_USERNAME}"
    return base
TARIFF_URL = _make_tariff_url("subscribe")

START_TEXT = (
    "Привет! Я GPT-5 ProBot — мультирежимный бот для учёбы, работы и развлечений.\n\n"
    "Чем полезен:\n"
    "• 💬 GPT: ответы/идеи/планы, работа с фото и документами.\n"
    "• 🗣 Голос: voice/audio → текст; /voice_on — озвучка ответов.\n"
    "• 🖼 Фото-мастерская: удаление/замена фона, outpaint, анализ, раскадровка, оживление.\n"
    "• 🎬 Видео: Luma/Runway по описанию.\n"
    "• ⭐ Подписка, 💳 ЮKassa, 💠 CryptoBot, единый USD-кошелёк.\n\n"
    "Выберите режим или просто напишите запрос."
)

HELP_TEXT = (
    "Подсказки:\n"
    "• Отправьте voice/audio — распознаю и отвечу.\n"
    "• Пришлите фото — появятся быстрые кнопки. В подписи можно написать: «удали фон», «оживи», «раскадровка».\n"
    "• /img <описание> — сгенерирую картинку (OpenAI Images).\n"
    "• «сделай видео … 9 секунд 9:16» — предложу Luma/Runway.\n"
    "• /plans — тарифы; /balance — кошелёк; /engines — выбор движков."
)

def engines_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 GPT", callback_data="engine:gpt"),
         InlineKeyboardButton("🗣 STT/TTS", callback_data="engine:stt_tts")],
        [InlineKeyboardButton("🖼 Images", callback_data="engine:images"),
         InlineKeyboardButton("🎨 Midjourney", callback_data="engine:midjourney")],
        [InlineKeyboardButton("🎬 Luma", callback_data="engine:luma"),
         InlineKeyboardButton("🎥 Runway", callback_data="engine:runway")],
    ])

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Учёба"), KeyboardButton("Работа"), KeyboardButton("Развлечения")],
            [KeyboardButton("🧠 Движки"), KeyboardButton("⭐ Подписка · Помощь"), KeyboardButton("🧾 Баланс")],
        ],
        resize_keyboard=True
    )
main_kb = main_keyboard()

# ───────── Диагностика/баланс/планы ─────────
async def cmd_diag_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tier = get_subscription_tier(user_id); lim = _limits_for(user_id); row = _usage_row(user_id)
    lines = [
        f"👤 Тариф: {tier}",
        f"• Тексты сегодня: {row['text_count']} / {lim['text_per_day']}",
        f"• Luma $: {row['luma_usd']:.2f} / {lim['luma_budget_usd']:.2f}",
        f"• Runway $: {row['runway_usd']:.2f} / {lim['runway_budget_usd']:.2f}",
        f"• Images $: {row['img_usd']:.2f} / {lim['img_budget_usd']:.2f}",
    ]
    await update.effective_message.reply_text("\n".join(lines))

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    total = _wallet_total_get(user_id); row = _usage_row(user_id); lim = _limits_for(user_id)
    msg = (
        "🧾 Кошелёк:\n"
        f"• Единый баланс: ${total:.2f}\n"
        "• Дневные бюджеты по тарифу:\n"
        f"  Luma: ${row['luma_usd']:.2f} / ${lim['luma_budget_usd']:.2f}\n"
        f"  Runway: ${row['runway_usd']:.2f} / ${lim['runway_budget_usd']:.2f}\n"
        f"  Images: ${row['img_usd']:.2f} / ${lim['img_budget_usd']:.2f}\n"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]])
    await update.effective_message.reply_text(msg, reply_markup=kb)

def _plan_rub(tier: str, term: str) -> int:
    tier = (tier or "pro").lower(); term = (term or "month").lower()
    return int(PLAN_PRICE_TABLE.get(tier, PLAN_PRICE_TABLE["pro"]).get(term, PLAN_PRICE_TABLE["pro"]["month"]))

def _plan_payload_and_amount(tier: str, months: int) -> tuple[str,int,str]:
    term = {1:"month",3:"quarter",12:"year"}.get(months, "month")
    amount = _plan_rub(tier, term)
    title = f"Подписка {tier.upper()} ({term})"
    payload = f"sub:{tier}:{months}"
    return payload, amount, title

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["⭐ Тарифы (лимиты в день):",
             "START — тексты 200; Luma $0.8; Images $0.2.",
             "PRO — тексты 1000; Luma $4; Runway $7; Images $1.",
             "ULTIMATE — тексты 5000; Luma $8; Runway $14; Images $2."]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Купить START (ЮKassa)",    callback_data="buyinv:start:1"),
         InlineKeyboardButton("Купить START (CryptoBot)", callback_data="buycrypto:start:1")],
        [InlineKeyboardButton("Купить PRO (ЮKassa)",      callback_data="buyinv:pro:1"),
         InlineKeyboardButton("Купить PRO (CryptoBot)",   callback_data="buycrypto:pro:1")],
        [InlineKeyboardButton("Купить ULTIMATE (ЮKassa)", callback_data="buyinv:ultimate:1"),
         InlineKeyboardButton("Купить ULTIMATE (CryptoBot)", callback_data="buycrypto:ultimate:1")],
        [InlineKeyboardButton("Открыть мини-витрину", web_app=WebAppInfo(url=TARIFF_URL))]
    ])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb)

# ───────── Команды / старт / помощь ─────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_url = kv_get("welcome_url", BANNER_URL)
    if welcome_url:
        with contextlib.suppress(Exception): await update.effective_message.reply_photo(welcome_url)
    await update.effective_message.reply_text(START_TEXT, reply_markup=main_kb, disable_web_page_preview=True)

async def cmd_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Выберите движок:", reply_markup=engines_kb())

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, disable_web_page_preview=True)

# ───────── Invoices: ЮKassa ─────────
async def _send_invoice_rub(title: str, desc: str, amount_rub: int, payload: str, update: Update) -> bool:
    try:
        if not PROVIDER_TOKEN:
            await update.effective_message.reply_text("⚠️ ЮKassa не настроена (PROVIDER_TOKEN отсутствует).")
            return False
        prices = [LabeledPrice(label=_ascii_label(title), amount=int(amount_rub)*100)]
        await update.effective_message.reply_invoice(
            title=title, description=desc[:255], payload=payload,
            provider_token=PROVIDER_TOKEN, currency=CURRENCY, prices=prices,
            need_email=False, need_name=False, need_phone_number=False, need_shipping_address=False, is_flexible=False
        )
        return True
    except Exception as e:
        log.exception("send_invoice error: %s", e)
        with contextlib.suppress(Exception): await update.effective_message.reply_text("Не удалось выставить счёт.")
        return False

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.pre_checkout_query.answer(ok=True)
    except Exception as e:
        log.exception("precheckout error: %s", e)

async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sp = update.message.successful_payment
        payload = sp.invoice_payload or ""
        rub = (sp.total_amount or 0)/100.0
        uid = update.effective_user.id
        if payload.startswith("sub:"):
            _, tier, months = payload.split(":", 2); months = int(months)
            until = activate_subscription_with_tier(uid, tier, months)
            await update.effective_message.reply_text(f"✅ Подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')}.")
            return
        # Иначе — пополнение баланса
        usd = rub / max(1e-9, USD_RUB); _wallet_total_add(uid, usd)
        await update.effective_message.reply_text(f"💳 Пополнено: {rub:.0f} ₽ ≈ ${usd:.2f}.")
    except Exception as e:
        log.exception("successful_payment handler error: %s", e)

# ───────── CryptoBot ─────────
async def _crypto_create_invoice(usd_amount: float, asset: str = "USDT", description: str = "") -> tuple[str|None, str|None, float, str]:
    if not CRYPTO_PAY_API_TOKEN: return None, None, 0.0, asset
    try:
        payload = {"asset": asset, "amount": round(float(usd_amount), 2), "description": description or "Payment"}
        headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{CRYPTO_BASE}/createInvoice", headers=headers, json=payload)
            j = r.json(); ok = j.get("ok") is True
            if not ok: return None, None, 0.0, asset
            res = j.get("result", {})
            return str(res.get("invoice_id")), res.get("pay_url"), float(res.get("amount", usd_amount)), res.get("asset") or asset
    except Exception as e:
        log.exception("crypto create error: %s", e); return None, None, 0.0, asset

async def _crypto_get_invoice(invoice_id: str) -> dict | None:
    if not CRYPTO_PAY_API_TOKEN: return None
    try:
        headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN}
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{CRYPTO_BASE}/getInvoices?invoice_ids={invoice_id}", headers=headers)
            j = r.json(); 
            if not j.get("ok"): return None
            items = (j.get("result", {}) or {}).get("items", [])
            return items[0] if items else None
    except Exception as e:
        log.exception("crypto get error: %s", e); return None

async def _poll_crypto_generic(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, user_id: int, invoice_id: str):
    """
    Универсальный поллинг: если this invoice отмечен как 'sub' в kv, активируем подписку,
    иначе — пополняем баланс.
    """
    try:
        for _ in range(120):  # ~12 мин
            inv = await _crypto_get_invoice(invoice_id)
            st = (inv or {}).get("status", "").lower() if inv else ""
            if st == "paid":
                # Проверим — это подписка?
                meta = kv_get(f"crypto_sub:{invoice_id}", "")
                if meta:
                    try:
                        j = json.loads(meta)
                        tier, months = j.get("tier","pro"), int(j.get("months",1))
                        until = activate_subscription_with_tier(user_id, tier, months)
                        with contextlib.suppress(Exception):
                            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                                text=f"✅ CryptoBot: подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')}.")
                        kv_set(f"crypto_sub:{invoice_id}", "")  # очистим
                        return
                    except Exception:
                        pass
                # Иначе — пополнение единого баланса
                usd_amount = float(inv.get("amount", 0.0) or 0.0)
                asset = (inv.get("asset") or "").upper()
                if asset == "TON":
                    usd_amount *= TON_USD_RATE
                _wallet_total_add(user_id, usd_amount)
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                        text=f"✅ CryptoBot: платёж подтверждён. Баланс пополнен на ${usd_amount:.2f}.")
                return
            if st in ("expired","cancelled","canceled","failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                        text=f"❌ CryptoBot: платёж не завершён (статус: {st}).")
                return
            await asyncio.sleep(6.0)
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                text="⌛ CryptoBot: время ожидания вышло. Нажмите «Проверить оплату» позже.")
    except Exception as e:
        log.exception("crypto poll error: %s", e)

# ───────── Images ─────────
async def _do_img_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
        img_bytes = base64.b64decode(resp.data[0].b64_json)
        await update.effective_message.reply_photo(photo=img_bytes, caption=f"Готово ✅\nЗапрос: {prompt}")
    except Exception as e:
        log.exception("IMG gen error: %s", e)
        await update.effective_message.reply_text("Не удалось создать изображение.")

# ───────── Photo UI ─────────
def photo_quick_actions_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧼 Удалить фон", callback_data="pedit:removebg"),
         InlineKeyboardButton("🖼 Заменить фон", callback_data="pedit:replacebg")],
        [InlineKeyboardButton("🧭 Расширить кадр (outpaint)", callback_data="pedit:outpaint")],
        [InlineKeyboardButton("👁 Анализ (Vision)", callback_data="pedit:vision"),
         InlineKeyboardButton("📽 Раскадровка", callback_data="pedit:story")],
        [InlineKeyboardButton("🎥 Оживить (Runway)", callback_data="pedit:animate")]
    ])

_photo_cache: dict[int, bytes] = {}

def _cache_photo(user_id: int, data: bytes):
    try: _photo_cache[user_id] = data
    except Exception: pass

def _get_cached_photo(user_id: int) -> bytes | None:
    return _photo_cache.get(user_id)

def sniff_image_mime(data: bytes) -> str:
    if not data or len(data) < 12: return "application/octet-stream"
    b = data[:12]
    if b.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if b[0:3] == b"\xff\xd8\xff":         return "image/jpeg"
    if b[0:4] == b"RIFF" and b[8:12]==b"WEBP": return "image/webp"
    return "application/octet-stream"

# Ken Burns fallback (без внешних API)
async def _ken_burns_fallback(update: Update, img_bytes: bytes, seconds: int = 6, fps: int = 24):
    if cv2 is None:
        await update.effective_message.reply_text("Локальная анимация недоступна (нет OpenCV).")
        return
    try:
        import numpy as np
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        h, w, _ = frame.shape
        out_w, out_h = (720, int(720*h/w)) if w>=h else (int(720*w/h), 720)
        total = seconds*fps
        path = "/tmp/anim.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        vw = cv2.VideoWriter(path, fourcc, fps, (out_w, out_h))
        for i in range(total):
            t = i/total
            scale = 1.0 + 0.12*t
            crop_w, crop_h = int(w/scale), int(h/scale)
            x = int((w - crop_w) * t * 0.5)
            y = int((h - crop_h) * (1.0 - t) * 0.5)
            x = max(0, min(w-crop_w, x)); y = max(0, min(h-crop_h, y))
            crop = frame[y:y+crop_h, x:x+crop_w]
            resized = cv2.resize(crop, (out_w, out_h), interpolation=cv2.INTER_CUBIC)
            vw.write(resized)
        vw.release()
        with open(path, "rb") as f:
            bio = BytesIO(f.read()); bio.name = "animate.mp4"
        await update.effective_message.reply_video(InputFile(bio), caption="🎞 Локальная анимация (Ken Burns) ✅")
    except Exception as e:
        log.exception("ken burns error: %s", e)
        await update.effective_message.reply_text("Не удалось сделать локальную анимацию.")

async def _pedit_removebg(update: Update, img_bytes: bytes):
    if rembg_remove is None:
        await update.effective_message.reply_text("rembg не установлен.")
        return
    try:
        out = rembg_remove(img_bytes)
        bio = BytesIO(out); bio.name = "no_bg.png"
        await update.effective_message.reply_document(InputFile(bio), caption="Фон удалён ✅")
    except Exception as e:
        log.exception("removebg error: %s", e)
        await update.effective_message.reply_text("Не удалось удалить фон.")

async def _pedit_replacebg(update: Update, img_bytes: bytes):
    if Image is None:
        await update.effective_message.reply_text("Pillow не установлен."); return
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGBA")
        bg = im.convert("RGB").filter(ImageFilter.GaussianBlur(radius=22)) if ImageFilter else im.convert("RGB")
        bio = BytesIO(); bg.save(bio, format="JPEG", quality=92); bio.seek(0); bio.name = "bg_blur.jpg"
        await update.effective_message.reply_photo(InputFile(bio), caption="Заменил фон на размытый вариант.")
    except Exception as e:
        log.exception("replacebg error: %s", e)
        await update.effective_message.reply_text("Не удалось заменить фон.")

async def _pedit_outpaint(update: Update, img_bytes: bytes):
    if Image is None:
        await update.effective_message.reply_text("Pillow не установлен."); return
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGB")
        pad = max(64, min(256, max(im.size)//6))
        big = Image.new("RGB", (im.width+2*pad, im.height+2*pad))
        bg = im.resize(big.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(radius=24)) if ImageFilter else im.resize(big.size)
        big.paste(bg, (0,0)); big.paste(im, (pad,pad))
        bio = BytesIO(); big.save(bio, format="JPEG", quality=92); bio.seek(0); bio.name = "outpaint.jpg"
        await update.effective_message.reply_photo(InputFile(bio), caption="Outpaint готов ✅")
    except Exception as e:
        log.exception("outpaint error: %s", e)
        await update.effective_message.reply_text("Не удалось сделать outpaint.")

async def _pedit_storyboard(update: Update, img_bytes: bytes):
    try:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        desc = await ask_openai_vision("Опиши ключевые элементы кадра очень кратко.", b64, sniff_image_mime(img_bytes))
        plan = await ask_openai_text(
            "Сделай раскадровку (6 кадров) под 6–10 секундный клип. "
            "Каждый кадр — 1 строка: действие/ракурс/свет. Основа:\n" + (desc or ""))
        await update.effective_message.reply_text("Раскадровка:\n" + plan)
    except Exception as e:
        log.exception("storyboard error: %s", e)
        await update.effective_message.reply_text("Не удалось построить раскадровку.")

async def _pedit_animate_runway(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes, hint: str = ""):
    # Попытаемся через Runway (text2video), сформировав промпт на базе Vision; иначе — локальный Ken Burns.
    try:
        if not RUNWAY_API_KEY:
            await _ken_burns_fallback(update, img_bytes); return
        b64 = base64.b64encode(img_bytes).decode("ascii")
        brief = await ask_openai_vision("Опиши кратко объект/сцену на фото (3–6 слов).", b64, sniff_image_mime(img_bytes))
        additions = (" " + hint.strip()) if hint else ""
        prompt = f"Animate a short cinematic clip of: {brief}. Gentle camera push-in, subtle parallax and motion. High detail.{additions}"
        await update.effective_message.reply_text("⏳ Запускаю анимацию в Runway…")
        # Используем общий раннер Runway:
        await _run_runway_video(update, context, prompt, duration_s=RUNWAY_DURATION_S, aspect="9:16")
    except Exception as e:
        log.exception("runway animate error: %s", e)
        await _ken_burns_fallback(update, img_bytes)

# ───────── Документы → конспект ─────────
def _safe_decode_txt(b: bytes) -> str:
    for enc in ("utf-8","cp1251","latin-1"):
        try: return b.decode(enc)
        except Exception: continue
    return b.decode("utf-8", errors="ignore")

def extract_text_from_document(data: bytes, filename: str) -> tuple[str, str]:
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf"):
            import PyPDF2
            rd = PyPDF2.PdfReader(BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in rd.pages), "PDF"
    except Exception: pass
    try:
        if name.endswith(".epub"):
            from ebooklib import epub; from bs4 import BeautifulSoup
            book = epub.read_epub(BytesIO(data)); chunks=[]
            for item in book.get_items():
                if item.get_type() == 9:
                    soup = BeautifulSoup(item.get_content(), "html.parser")
                    t = soup.get_text(separator=" ", strip=True)
                    if t: chunks.append(t)
            return "\n".join(chunks).strip(), "EPUB"
    except Exception: pass
    try:
        if name.endswith(".docx"):
            import docx; doc = docx.Document(BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs).strip(), "DOCX"
    except Exception: pass
    try:
        if name.endswith(".fb2"):
            import xml.etree.ElementTree as ET
            root = ET.fromstring(data); texts=[]
            for elem in root.iter():
                if elem.text and elem.text.strip(): texts.append(elem.text.strip())
            return " ".join(texts).strip(), "FB2"
    except Exception: pass
    if name.endswith(".txt"): return _safe_decode_txt(data), "TXT"
    return _safe_decode_txt(data), "UNKNOWN"

async def summarize_long_text(full_text: str, query: str | None = None) -> str:
    text = (full_text or "").strip(); max_chunk = 8000
    if len(text) <= max_chunk:
        return await ask_openai_text((f"Цель: {query}\n" if query else "") + "Суммируй кратко по пунктам:\n" + text)
    parts=[]; i=0
    while i < len(text) and len(parts) < 8:
        parts.append(text[i:i+max_chunk]); i += max_chunk
    partials = [await ask_openai_text("Суммируй фрагмент:\n"+p) for p in parts]
    combined = "\n\n".join(f"- Фрагмент {k+1}:\n{v}" for k,v in enumerate(partials))
    return await ask_openai_text("Объедини тезисы (5–10 пунктов, цифры/сроки, вывод):\n"+combined)

# ───────── Видео рендеры ─────────
_ASPECTS = {"9:16", "16:9", "1:1", "4:5", "3:4", "4:3"}

def parse_video_opts(text: str) -> tuple[int,str]:
    tl = (text or "").lower()
    m = re.search(r"(\d+)\s*(?:сек|с)\b", tl)
    duration = max(3, min(20, int(m.group(1)) if m else RUNWAY_DURATION_S))
    asp = None
    for a in _ASPECTS:
        if a in tl: asp = a; break
    return duration, (asp or "16:9")

async def _run_luma_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration_s: int, aspect: str):
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            create_url = f"{LUMA_BASE_URL}{LUMA_CREATE_PATH}"
            headers = {"Authorization": f"Bearer {LUMA_API_KEY}", "Accept":"application/json"}
            payload = {"model":LUMA_MODEL, "prompt":prompt, "duration":f"{duration_s}s", "aspect_ratio":aspect}
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code >= 400:
                await update.effective_message.reply_text(f"⚠️ Luma отклонила задачу ({r.status_code})."); return
            rid = (r.json() or {}).get("id") or (r.json() or {}).get("generation_id")
            if not rid: await update.effective_message.reply_text("⚠️ Luma не вернула id."); return
            await update.effective_message.reply_text("⏳ Luma рендерит…")
            status_url = f"{LUMA_BASE_URL}{LUMA_STATUS_PATH}".format(id=rid); started = time.time()
            while True:
                rs = await client.get(status_url, headers=headers)
                js = {}
                try: js = rs.json()
                except Exception: pass
                st = (js.get("state") or js.get("status") or "").lower()
                if st in ("completed","succeeded","finished","ready"):
                    url = js.get("assets", [{}])[0].get("url") or js.get("output_url")
                    if not url: await update.effective_message.reply_text("⚠️ Готово, но нет ссылки."); return
                    try:
                        v = await client.get(url, timeout=180.0); v.raise_for_status()
                        bio = BytesIO(v.content); bio.name="luma.mp4"
                        await update.effective_message.reply_video(InputFile(bio), caption="🎬 Luma: готово ✅")
                    except Exception:
                        await update.effective_message.reply_text(f"🎬 Luma: готово ✅\n{url}")
                    return
                if st in ("failed","error","canceled","cancelled"):
                    await update.effective_message.reply_text("❌ Luma: ошибка рендера."); return
                if time.time()-started > LUMA_MAX_WAIT_S:
                    await update.effective_message.reply_text("⌛ Luma: время ожидания вышло."); return
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("Luma error: %s", e)
        await update.effective_message.reply_text("❌ Luma: не удалось запустить/получить видео.")

async def _run_runway_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration_s: int, aspect: str):
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            create_url = f"{RUNWAY_BASE_URL}{RUNWAY_CREATE_PATH}"
            headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Accept":"application/json"}
            payload = {"model": RUNWAY_MODEL, "input": {"prompt": prompt, "duration": duration_s, "ratio": aspect.replace(":", "/")}}
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code >= 400:
                await update.effective_message.reply_text(f"⚠️ Runway отклонил задачу ({r.status_code})."); return
            rid = (r.json() or {}).get("id") or (r.json() or {}).get("task_id")
            if not rid: await update.effective_message.reply_text("⚠️ Runway не вернул id задачи."); return
            await update.effective_message.reply_text("⏳ Runway рендерит…")
            status_url = f"{RUNWAY_BASE_URL}{RUNWAY_STATUS_PATH}".format(id=rid); started = time.time()
            while True:
                rs = await client.get(status_url, headers=headers)
                js = {}
                try: js = rs.json()
                except Exception: pass
                st = (js.get("status") or js.get("state") or "").lower()
                if st in ("completed","succeeded","finished","ready"):
                    assets = js.get("output", {}) if isinstance(js.get("output"), dict) else (js.get("assets") or {})
                    url = (assets.get("video") if isinstance(assets, dict) else None) or js.get("video_url") or js.get("output_url")
                    if not url: await update.effective_message.reply_text("⚠️ Готово, но нет ссылки."); return
                    try:
                        v = await client.get(url, timeout=180.0); v.raise_for_status()
                        bio = BytesIO(v.content); bio.name="runway.mp4"
                        await update.effective_message.reply_video(InputFile(bio), caption="🎥 Runway: готово ✅")
                    except Exception:
                        await update.effective_message.reply_text(f"🎥 Runway: готово ✅\n{url}")
                    return
                if st in ("failed","error","canceled","cancelled"):
                    await update.effective_message.reply_text("❌ Runway: ошибка рендера."); return
                if time.time()-started > RUNWAY_MAX_WAIT_S:
                    await update.effective_message.reply_text("⌛ Runway: время ожидания вышло."); return
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("Runway error: %s", e)
        await update.effective_message.reply_text("❌ Runway: не удалось запустить/получить видео.")

# ───────── Команды /img ─────────
async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip() if context.args else ""
    if not prompt:
        await update.effective_message.reply_text("Формат: /img <описание>")
        return
    await _do_img_generate(update, context, prompt)

# ───────── Текст / маршрутизация медиа-намерений ─────────
_CREATE_CMD = r"(сдела(й|йте)|созда(й|йте)|сгенерир(уй|уйте)|render|generate|create|make)"
_IMG_WORDS  = r"(картин\w+|изображен\w+|фото\w*|рисунк\w+|image|picture|img\b)"
_VID_WORDS  = r"(видео|ролик\w*|анимаци\w*|shorts?|reels?|clip|video|vid\b)"

def detect_media_intent(text: str):
    if not text: return (None, "")
    tl = text.strip().lower()

    # Явные префиксы
    if re.search(_CREATE_CMD, tl) and re.search(_VID_WORDS, tl):
        clean = re.sub(_VID_WORDS, "", tl, flags=re.I)
        clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
        return ("video", clean.strip(" ,.-:"))
    if re.search(_CREATE_CMD, tl) and re.search(_IMG_WORDS, tl):
        clean = re.sub(_IMG_WORDS, "", tl, flags=re.I)
        clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
        return ("image", clean.strip(" ,.-:"))
    return (None, "")

# ───────── Text handler ─────────
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    mtype, rest = detect_media_intent(text)
    if mtype == "video":
        duration, aspect = parse_video_opts(text)
        prompt = rest or text
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🎬 Luma (~$0.40)", callback_data=f"choose:luma:{duration}:{aspect}:{uuid.uuid4().hex[:8]}")],
            [InlineKeyboardButton(f"🎥 Runway (~${max(1.0, RUNWAY_UNIT_COST_USD*(duration/max(1,RUNWAY_DURATION_S))):.2f})",
                                  callback_data=f"choose:runway:{duration}:{aspect}:{uuid.uuid4().hex[:8]}")]
        ])
        kv_set(f"video_req:{update.effective_user.id}", json.dumps({"prompt": prompt}))
        await update.effective_message.reply_text(
            f"Что использовать?\nДлительность: {duration} с • Аспект: {aspect}\nЗапрос: «{prompt}»", reply_markup=kb)
        return

    ok, _, _ = check_text_and_inc(update.effective_user.id)
    if not ok:
        await update.effective_message.reply_text("Лимит текстовых запросов на сегодня исчерпан. Оформите ⭐ подписку или попробуйте завтра.")
        return

    reply = await ask_openai_text(text)
    await update.effective_message.reply_text(reply)
    await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])

# ───────── Фото / Документы / Голос ─────────
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ph = update.message.photo[-1]
        f = await ph.get_file()
        data = await f.download_as_bytearray()
        img = bytes(data)
        _cache_photo(update.effective_user.id, img)

        caption = (update.message.caption or "").strip().lower()
        if caption:
            # Понимаем, что просили в подписи
            if "удал" in caption and "фон" in caption:
                await _pedit_removebg(update, img); return
            if ("замен" in caption and "фон" in caption) or "blur" in caption:
                await _pedit_replacebg(update, img); return
            if "outpaint" in caption or "расшир" in caption or "поле" in caption:
                await _pedit_outpaint(update, img); return
            if "анализ" in caption or "текст" in caption or "vision" in caption:
                b64 = base64.b64encode(img).decode("ascii")
                ans = await ask_openai_vision("Опиши фото и текст на нём кратко.", b64, sniff_image_mime(img))
                await update.effective_message.reply_text(ans or "Готово."); return
            if "ожив" in caption or "анимац" in caption or "runway" in caption:
                await _pedit_animate_runway(update, context, img, hint=caption); return

        await update.effective_message.reply_text("Фото получено. Что сделать?", reply_markup=photo_quick_actions_kb())
    except Exception as e:
        log.exception("on_photo error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Не смог обработать фото.")

async def on_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document: return
        doc = update.message.document; mt = (doc.mime_type or "").lower()
        tg_file = await doc.get_file(); data = await tg_file.download_as_bytearray(); raw = bytes(data)

        if mt.startswith("image/"):
            _cache_photo(update.effective_user.id, raw)
            await update.effective_message.reply_text("Изображение получено как документ. Выберите действие:", reply_markup=photo_quick_actions_kb())
            return

        text, kind = extract_text_from_document(raw, doc.file_name or "file")
        if not (text or "").strip():
            await update.effective_message.reply_text(f"Не удалось извлечь текст из {kind}."); return
        goal = (update.message.caption or "").strip() or None
        await update.effective_message.reply_text(f"📄 Извлекаю текст ({kind}), готовлю конспект…")
        summary = await summarize_long_text(text, query=goal)
        await update.effective_message.reply_text(summary or "Готово.")
        await maybe_tts_reply(update, context, (summary or "")[:TTS_MAX_CHARS])
    except Exception as e:
        log.exception("on_doc error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Ошибка при обработке документа.")

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.voice: return
        vf = await update.message.voice.get_file()
        bio = BytesIO(await vf.download_as_bytearray()); bio.seek(0); setattr(bio, "name", "voice.ogg")
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        text = await transcribe_audio(bio, "voice.ogg")
        if not text:
            await update.effective_message.reply_text("Не удалось распознать речь."); return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_voice error: %s", e)
        with contextlib.suppress(Exception): await update.effective_message.reply_text("Ошибка при обработке voice.")

async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.audio: return
        af = await update.message.audio.get_file()
        filename = update.message.audio.file_name or "audio.mp3"
        bio = BytesIO(await af.download_as_bytearray()); bio.seek(0); setattr(bio, "name", filename)
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        text = await transcribe_audio(bio, filename)
        if not text:
            await update.effective_message.reply_text("Не удалось распознать речь из аудио."); return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_audio error: %s", e)
        with contextlib.suppress(Exception): await update.effective_message.reply_text("Ошибка при обработке аудио.")

# ───────── CallbackQuery (оплаты, движки, фото-кнопки) ─────────
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; data = (q.data or "").strip()
    try:
        # Пополнение
        if data == "topup":
            await q.answer()
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("500 ₽",  callback_data="topup:rub:500"),
                 InlineKeyboardButton("1000 ₽", callback_data="topup:rub:1000"),
                 InlineKeyboardButton("2000 ₽", callback_data="topup:rub:2000")],
                [InlineKeyboardButton("Crypto $5",  callback_data="topup:crypto:5"),
                 InlineKeyboardButton("Crypto $10", callback_data="topup:crypto:10"),
                 InlineKeyboardButton("Crypto $20", callback_data="topup:crypto:20")],
            ])
            await q.edit_message_text("Выберите сумму пополнения:", reply_markup=kb); return

        if data.startswith("topup:rub:"):
            await q.answer()
            amount_rub = int((data.split(":")[-1] or "0").strip() or "0")
            ok = await _send_invoice_rub("Пополнение баланса", "Единый кошелёк для перерасходов.", amount_rub, "t=3", update)
            await q.answer("Выставляю счёт…" if ok else "Не удалось выставить счёт", show_alert=not ok)
            return

        if data.startswith("topup:crypto:"):
            await q.answer()
            if not CRYPTO_PAY_API_TOKEN:
                await q.edit_message_text("CryptoBot не настроен."); return
            usd = float((data.split(":")[-1] or 0))
            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(usd, asset="USDT", description="Wallet top-up")
            if not inv_id or not pay_url:
                await q.edit_message_text("Не удалось создать счёт в CryptoBot."); return
            msg = await update.effective_message.reply_text(
                f"Оплатите через CryptoBot: ≈ ${usd_amount:.2f} ({asset}).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить в CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("Проверить оплату", callback_data=f"crypto:check:{inv_id}")]
                ])
            )
            context.application.create_task(_poll_crypto_generic(context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id))
            return

        if data.startswith("crypto:check:"):
            await q.answer()
            inv_id = data.split(":", 2)[-1]
            inv = await _crypto_get_invoice(inv_id)
            if not inv:
                await q.edit_message_text("Не нашёл счёт. Создайте новый."); return
            st = (inv.get("status") or "").lower()
            if st == "paid":
                # Отработаем как в поллинге (активация/баланс)
                meta = kv_get(f"crypto_sub:{inv_id}", "")
                if meta:
                    j = json.loads(meta or "{}")
                    tier, months = j.get("tier", "pro"), int(j.get("months", 1))
                    until = activate_subscription_with_tier(update.effective_user.id, tier, months)
                    await q.edit_message_text(f"✅ Подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')}.")
                    kv_set(f"crypto_sub:{inv_id}", "")
                else:
                    usd_amount = float(inv.get("amount", 0.0) or 0.0)
                    if (inv.get("asset") or "").upper() == "TON":
                        usd_amount *= TON_USD_RATE
                    _wallet_total_add(update.effective_user.id, usd_amount)
                    await q.edit_message_text(f"✅ Баланс пополнен на ${usd_amount:.2f}.")
            elif st == "active":
                await q.answer("Платёж ещё не подтверждён", show_alert=True)
            else:
                await q.edit_message_text(f"Статус счёта: {st}")
            return

        # Подписка — ЮKassa
        if data.startswith("buyinv:"):
            await q.answer()
            _, tier, months = data.split(":", 2); months = int(months)
            payload, amount_rub, title = _plan_payload_and_amount(tier, months)
            ok = await _send_invoice_rub(title, f"Оформление подписки {tier.upper()} на {months} мес.", amount_rub, payload, update)
            if not ok: await q.answer("Не удалось выставить счёт", show_alert=True)
            return

        # Подписка — CryptoBot (напрямую, без кошелька)
        if data.startswith("buycrypto:"):
            await q.answer()
            if not CRYPTO_PAY_API_TOKEN:
                await q.edit_message_text("CryptoBot не настроен."); return
            _, tier, months = data.split(":", 2); months = int(months)
            amount_rub = _plan_rub(tier, {1:"month",3:"quarter",12:"year"}.get(months, "month"))
            usd = float(amount_rub)/max(1e-9, USD_RUB)
            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(usd, asset="USDT", description=f"Subscribe {tier.upper()} x{months}")
            if not inv_id or not pay_url:
                await q.edit_message_text("Не удалось создать счёт в CryptoBot."); return
            # Запомним, что этот инвойс — подписка
            kv_set(f"crypto_sub:{inv_id}", json.dumps({"tier": tier, "months": months}))
            msg = await update.effective_message.reply_text(
                f"Оформление подписки {tier.upper()} на {months} мес. Оплатите через CryptoBot: ≈ ${usd_amount:.2f} ({asset}).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить в CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("Проверить оплату", callback_data=f"crypto:check:{inv_id}")]
                ])
            )
            context.application.create_task(_poll_crypto_generic(context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id))
            return

        # Выбор движка для видео
        if data.startswith("choose:"):
            await q.answer()
            _, engine, duration, aspect, _aid = data.split(":", 4)
            duration = int(duration); aspect = aspect
            meta = kv_get(f"video_req:{update.effective_user.id}", "")
            prompt = (json.loads(meta).get("prompt") if meta else None) or "cinematic clip"
            if engine == "luma":
                await _run_luma_video(update, context, prompt, duration, aspect); return
            else:
                await _run_runway_video(update, context, prompt, duration, aspect); return

        # Фото-кнопки
        if data.startswith("pedit:"):
            await q.answer()
            img = _get_cached_photo(update.effective_user.id)
            if not img:
                await q.edit_message_text("Сначала пришлите фото, затем выберите действие.", reply_markup=photo_quick_actions_kb())
                return
            if data == "pedit:removebg": await _pedit_removebg(update, img); return
            if data == "pedit:replacebg": await _pedit_replacebg(update, img); return
            if data == "pedit:outpaint":  await _pedit_outpaint(update, img); return
            if data == "pedit:story":     await _pedit_storyboard(update, img); return
            if data == "pedit:vision":
                b64 = base64.b64encode(img).decode("ascii")
                ans = await ask_openai_vision("Опиши фото и текст на нём кратко.", b64, sniff_image_mime(img))
                await update.effective_message.reply_text(ans or "Готово."); return
            if data == "pedit:animate":
                await _pedit_animate_runway(update, context, img); return

        # Выбор движков (UI)
        if data == "engine:gpt" or data == "engine:stt_tts" or data == "engine:images":
            await q.edit_message_text("Движок выбран. Отправьте запрос/медиа.")
            return
        if data == "engine:luma" or data == "engine:runway":
            await q.edit_message_text("Напишите: «сделай видео … 9 секунд 9:16» — предложу Luma/Runway.")
            return

        await q.answer("Неизвестная команда", show_alert=True)

    except Exception as e:
        log.exception("on_cb error: %s", e)
    finally:
        with contextlib.suppress(Exception): await q.answer()

# ───────── Хендлеры-кнопки ReplyKeyboard ─────────
async def on_btn_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_engines(update, context)

async def on_btn_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_balance(update, context)

async def on_btn_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_plans(update, context)

# ───────── Регистрация и запуск ─────────
def build_application():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("engines",  cmd_engines))
    app.add_handler(CommandHandler("img",      cmd_img))
    app.add_handler(CommandHandler("plans",    cmd_plans))
    app.add_handler(CommandHandler("balance",  cmd_balance))
    app.add_handler(CommandHandler("diag_limits", cmd_diag_limits))
    app.add_handler(CommandHandler("voice_on", cmd_voice_on))
    app.add_handler(CommandHandler("voice_off",cmd_voice_off))

    # Платежи
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    # Callback'и
    app.add_handler(CallbackQueryHandler(on_cb))

    # Reply-кнопки
    app.add_handler(MessageHandler(filters.Regex(r"^(?:🧠\s*)?Движки$"), on_btn_engines))
    app.add_handler(MessageHandler(filters.Regex(r"^(?:⭐\s*)?Подписка(?:\s*·\s*Помощь)?$"), on_btn_plans))
    app.add_handler(MessageHandler(filters.Regex(r"^(?:💳|🧾)?\s*Баланс$"), on_btn_balance))

    # Медиа
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, on_doc))
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.AUDIO, on_audio))

    # Текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    return app

def main():
    db_init()
    app = build_application()
    if USE_WEBHOOK:
        log.info("🚀 WEBHOOK mode. Public URL: %s  Path: %s  Port: %s", PUBLIC_URL, WEBHOOK_PATH, PORT)
        app.run_webhook(
            listen="0.0.0.0", port=PORT, url_path=WEBHOOK_PATH.lstrip("/"),
            webhook_url=f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}",
            secret_token=(WEBHOOK_SECRET or None),
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        log.info("🚀 POLLING mode.")
        with contextlib.suppress(Exception):
            asyncio.get_event_loop().run_until_complete(app.bot.delete_webhook(drop_pending_updates=True))
        app.run_polling(close_loop=False, allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)

if __name__ == "__main__":
    main()
