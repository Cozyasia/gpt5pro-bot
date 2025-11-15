# -*- coding: utf-8 -*-
"""
GPT-5 ProBot • main.py (MAXI)
python-telegram-bot==21.6  •  Python 3.12.x

Фичи:
- 💬 GPT (текст), 👁 Vision (фото), 📚 PDF/EPUB/DOCX/FB2/TXT-конспекты
- 🗣 STT (Deepgram/Whisper) + 🎙 TTS (OpenAI Speech OGG/Opus), /voice_on /voice_off
- 🖼 OpenAI Images /img
- 🎬 Luma / 🎥 Runway видео (Reels/Shorts) с бюджетами, fallback’и
- 💳 ЮKassa + 💠 CryptoBot: подписки, разовые пополнения, ЕДИНЫЙ USD-кошелёк
- 🧾 Лимиты/балансы/расходы по Luma/Runway/Images (SQLite)
- ⚙️ «Учёба / Работа / Развлечения», быстрые действия по фото
- 🔗 Deep-link лота из /start <payload>, сохранение в kv
- 🧪 Диагностика движков: /diag_stt /diag_images /diag_video /diag_limits
- 📲 Кнопка «⭐ Подписка» всегда открывает тарифы, а не уходит в чат
"""

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
import contextlib
import uuid

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

# Optional imaging
try:
    from PIL import Image, ImageFilter
except Exception:
    Image = None
    ImageFilter = None
try:
    from rembg import remove as rembg_remove
except Exception:
    rembg_remove = None

# ───── LOGGING ─────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt5pro")

# ───── ENV ─────
BOT_TOKEN   = (os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
BOT_USERNAME= (os.getenv("BOT_USERNAME") or "").strip().lstrip("@")
PUBLIC_URL  = (os.getenv("PUBLIC_URL") or "").strip()
WEBAPP_URL  = (os.getenv("WEBAPP_URL") or "").strip()
USE_WEBHOOK = (os.getenv("USE_WEBHOOK","1").lower() in ("1","true","yes","on"))
WEBHOOK_PATH= (os.getenv("WEBHOOK_PATH") or "/tg").strip()
WEBHOOK_SECRET = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()
PORT        = int(os.getenv("PORT","10000"))

# OpenAI (текст/визион)
from openai import OpenAI
OPENAI_API_KEY  = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "").strip()
OPENAI_MODEL    = (os.getenv("OPENAI_MODEL") or "openai/gpt-4o-mini").strip()
OPENROUTER_SITE_URL = (os.getenv("OPENROUTER_SITE_URL") or "").strip()
OPENROUTER_APP_NAME = (os.getenv("OPENROUTER_APP_NAME") or "").strip()

# Vision override (если нужно)
OPENAI_VISION_MODEL = (os.getenv("OPENAI_VISION_MODEL") or "").strip()

# STT
DEEPGRAM_API_KEY    = (os.getenv("DEEPGRAM_API_KEY") or "").strip()
OPENAI_STT_KEY      = (os.getenv("OPENAI_STT_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_STT_MODEL    = (os.getenv("OPENAI_STT_MODEL") or "whisper-1").strip()
OPENAI_STT_BASE_URL = (os.getenv("OPENAI_STT_BASE_URL") or "https://api.openai.com/v1").strip().rstrip("/")

# TTS
OPENAI_TTS_KEY      = (os.getenv("OPENAI_TTS_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_TTS_BASE_URL = (os.getenv("OPENAI_TTS_BASE_URL") or "https://api.openai.com/v1").strip().rstrip("/")
OPENAI_TTS_MODEL    = (os.getenv("OPENAI_TTS_MODEL") or "gpt-4o-mini-tts").strip()
OPENAI_TTS_VOICE    = (os.getenv("OPENAI_TTS_VOICE") or "alloy").strip()
TTS_MAX_CHARS       = int(os.getenv("TTS_MAX_CHARS","150"))

# Images
OPENAI_IMAGE_KEY    = (os.getenv("OPENAI_IMAGE_KEY") or OPENAI_API_KEY).strip()
IMAGES_BASE_URL     = (os.getenv("OPENAI_IMAGE_BASE_URL") or "https://api.openai.com/v1").strip().rstrip("/")
IMAGES_MODEL        = "gpt-image-1"

# Luma
LUMA_API_KEY     = (os.getenv("LUMA_API_KEY") or "").strip()
LUMA_MODEL       = (os.getenv("LUMA_MODEL") or "ray-2").strip()
LUMA_ASPECT      = (os.getenv("LUMA_ASPECT") or "16:9").strip()
LUMA_DURATION_S  = int(os.getenv("LUMA_DURATION_S","5"))
LUMA_BASE_URL    = (os.getenv("LUMA_BASE_URL") or "https://api.lumalabs.ai/dream-machine/v1").strip().rstrip("/")
LUMA_CREATE_PATH = "/generations"
LUMA_STATUS_PATH = "/generations/{id}"
# Fallbacks
LUMA_FALLBACKS   = [u.strip().rstrip("/") for u in re.split(r"[;,]\s*", os.getenv("LUMA_FALLBACKS","")) if u.strip()]

# Runway
RUNWAY_API_KEY      = (os.getenv("RUNWAY_API_KEY") or "").strip()
RUNWAY_MODEL        = (os.getenv("RUNWAY_MODEL") or "gen3a_turbo").strip()
RUNWAY_RATIO        = (os.getenv("RUNWAY_RATIO") or "720:1280").strip()
RUNWAY_BASE_URL     = (os.getenv("RUNWAY_BASE_URL") or "https://api.runwayml.com").strip().rstrip("/")
RUNWAY_CREATE_PATH  = "/v1/tasks"
RUNWAY_STATUS_PATH  = "/v1/tasks/{id}"

# Тайминги
LUMA_MAX_WAIT_S     = int(os.getenv("LUMA_MAX_WAIT_S","900"))
RUNWAY_MAX_WAIT_S   = int(os.getenv("RUNWAY_MAX_WAIT_S","1200"))
VIDEO_POLL_DELAY_S  = float(os.getenv("VIDEO_POLL_DELAY_S","6.0"))

# Прочее
BANNER_URL     = (os.getenv("BANNER_URL") or "").strip()
TAVILY_API_KEY = (os.getenv("TAVILY_API_KEY") or "").strip()

# Платежи
PROVIDER_TOKEN = (os.getenv("PROVIDER_TOKEN_YOOKASSA") or "").strip()
CURRENCY       = "RUB"
USD_RUB        = float(os.getenv("USD_RUB","100"))
DB_PATH        = os.path.abspath(os.getenv("DB_PATH","subs.db"))

# Цены/лимиты (базовые — от них считаем 1 / 6 / 12 месяцев)
PLAN_PRICE_TABLE = {
    "start":    {"month": 499,  "quarter": 1299, "year": 4490},
    "pro":      {"month": 999,  "quarter": 2799, "year": 8490},
    "ultimate": {"month": 1999, "quarter": 5490, "year": 15990},
}

TERM_MONTHS = {"month": 1, "quarter": 3, "year": 12}
MIN_RUB_FOR_INVOICE      = int(os.getenv("MIN_RUB_FOR_INVOICE","100"))
ONEOFF_MARKUP_DEFAULT    = float(os.getenv("ONEOFF_MARKUP_DEFAULT","1.0"))
ONEOFF_MARKUP_RUNWAY     = float(os.getenv("ONEOFF_MARKUP_RUNWAY","0.5"))
RUNWAY_UNIT_COST_USD     = float(os.getenv("RUNWAY_UNIT_COST_USD","7.0"))
IMG_COST_USD             = float(os.getenv("IMG_COST_USD","0.05"))
LUMA_RES_HINT            = (os.getenv("LUMA_RES","720p") or "720p").lower()

# CryptoBot
CRYPTO_PAY_API_TOKEN = (os.getenv("CRYPTO_PAY_API_TOKEN") or "").strip()
CRYPTO_BASE = "https://pay.crypt.bot/api"
TON_USD_RATE = float(os.getenv("TON_USD_RATE","5.0"))

# Владельцы/безлимит
def _parse_ids_csv(s: str) -> set[int]:
    return set(int(x) for x in s.split(",") if x.strip().isdigit())

UNLIM_USER_IDS  = _parse_ids_csv(os.getenv("UNLIM_USER_IDS",""))
UNLIM_USERNAMES = set(
    s.strip().lstrip("@").lower()
    for s in (os.getenv("UNLIM_USERNAMES","") or "").split(",")
    if s.strip()
)
OWNER_ID         = int(os.getenv("OWNER_ID","0") or "0")
FORCE_OWNER_UNLIM= os.getenv("FORCE_OWNER_UNLIM","1").lower() not in ("0","false","no")

# ───── Валидация базовых переменных ─────
if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("https://"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")
if not OPENAI_API_KEY:
    raise RuntimeError("ENV OPENAI_API_KEY is missing")

# ───── Утилиты ─────
def _utcnow(): return datetime.now(timezone.utc)
def _today_ymd(): return _utcnow().strftime("%Y-%m-%d")

def is_unlimited(uid: int, uname: str|None=None) -> bool:
    # Владелец всегда безлимит (если не отключено)
    if FORCE_OWNER_UNLIM and OWNER_ID and uid == OWNER_ID:
        return True
    if uid in UNLIM_USER_IDS:
        return True
    if uname and uname.lower().lstrip("@") in UNLIM_USERNAMES:
        return True
    return False

def _ascii_label(s: str|None) -> str:
    s = (s or "Item").strip()
    try:
        s.encode("ascii")
        return s[:32]
    except Exception:
        return "Item"

# ───── OpenAI клиенты ─────
default_headers = {}
if OPENROUTER_SITE_URL:
    default_headers["HTTP-Referer"] = OPENROUTER_SITE_URL
if OPENROUTER_APP_NAME:
    default_headers["X-Title"] = OPENROUTER_APP_NAME

_auto_base = OPENAI_BASE_URL
if not _auto_base and (OPENAI_API_KEY.startswith("sk-or-") or "openrouter" in (OPENAI_BASE_URL or "").lower()):
    _auto_base = "https://openrouter.ai/api/v1"
    log.info("OpenRouter base selected for text LLM.")

try:
    oai_llm = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url=_auto_base or None,
        default_headers=default_headers or None,
    )
except TypeError:
    oai_llm = OpenAI(api_key=OPENAI_API_KEY, base_url=_auto_base or None)

oai_img = OpenAI(api_key=OPENAI_IMAGE_KEY, base_url=IMAGES_BASE_URL)

from openai import OpenAI as _OpenAI_STT
def _oai_stt_client():
    return _OpenAI_STT(api_key=OPENAI_STT_KEY, base_url=OPENAI_STT_BASE_URL)

# ───── База данных ─────
def db_init():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER PRIMARY KEY, until_ts INTEGER NOT NULL, tier TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS usage_daily (
        user_id INTEGER, ymd TEXT,
        text_count INTEGER DEFAULT 0,
        luma_usd REAL DEFAULT 0.0, runway_usd REAL DEFAULT 0.0, img_usd REAL DEFAULT 0.0,
        PRIMARY KEY(user_id, ymd))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS wallet (
        user_id INTEGER PRIMARY KEY,
        luma_usd REAL DEFAULT 0.0, runway_usd REAL DEFAULT 0.0,
        img_usd REAL DEFAULT 0.0, usd REAL DEFAULT 0.0)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)""")
    # миграции
    try:
        cur.execute("ALTER TABLE wallet ADD COLUMN usd REAL DEFAULT 0.0")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE subscriptions ADD COLUMN tier TEXT")
    except Exception:
        pass
    con.commit()
    con.close()

def kv_get(key: str, default: str|None=None) -> str|None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT value FROM kv WHERE key=?", (key,))
    row = cur.fetchone()
    con.close()
    return (row[0] if row else default)

def kv_set(key: str, value: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?,?)", (key, value))
    con.commit()
    con.close()

def activate_subscription(uid: int, months: int=1):
    now  = _utcnow()
    until= now + timedelta(days=30*months)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT until_ts FROM subscriptions WHERE user_id=?", (uid,))
    row = cur.fetchone()
    if row and row[0] and row[0] > int(now.timestamp()):
        current_until = datetime.fromtimestamp(row[0], tz=timezone.utc)
        until = current_until + timedelta(days=30*months)
    cur.execute(
        """INSERT INTO subscriptions(user_id, until_ts)
           VALUES(?,?)
           ON CONFLICT(user_id) DO UPDATE SET until_ts=excluded.until_ts""",
        (uid, int(until.timestamp())),
    )
    con.commit()
    con.close()
    return until

def set_subscription_tier(uid: int, tier: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO subscriptions(user_id, until_ts, tier) VALUES (?,?,?)",
        (uid, int(_utcnow().timestamp()), tier),
    )
    cur.execute("UPDATE subscriptions SET tier=? WHERE user_id=?", (tier, uid))
    con.commit()
    con.close()

def activate_subscription_with_tier(uid: int, tier: str, months: int):
    until = activate_subscription(uid, months)
    set_subscription_tier(uid, tier)
    return until

def get_subscription_until(uid: int):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT until_ts FROM subscriptions WHERE user_id=?", (uid,))
    row = cur.fetchone()
    con.close()
    return None if not row else datetime.fromtimestamp(row[0], tz=timezone.utc)

def get_subscription_tier(uid: int) -> str:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT until_ts, tier FROM subscriptions WHERE user_id=?", (uid,))
    row = cur.fetchone()
    con.close()
    if not row:
        return "free"
    until_ts, tier = row[0], (row[1] or "pro")
    if until_ts and datetime.fromtimestamp(until_ts, tz=timezone.utc) > _utcnow():
        return tier.lower()
    return "free"

def _usage_row(uid: int, ymd: str|None=None) -> dict:
    ymd = ymd or _today_ymd()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO usage_daily(user_id, ymd) VALUES(?,?)", (uid, ymd))
    con.commit()
    cur.execute(
        "SELECT text_count, luma_usd, runway_usd, img_usd FROM usage_daily WHERE user_id=? AND ymd=?",
        (uid, ymd),
    )
    row = cur.fetchone()
    con.close()
    return {"text_count": row[0], "luma_usd": row[1], "runway_usd": row[2], "img_usd": row[3]}

def _usage_update(uid: int, **delta):
    ymd = _today_ymd()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    r = _usage_row(uid, ymd)
    cur.execute(
        """UPDATE usage_daily
           SET text_count=?,
               luma_usd=?,
               runway_usd=?,
               img_usd=?
           WHERE user_id=? AND ymd=?""",
        (
            r["text_count"] + delta.get("text_count",0),
            r["luma_usd"] + delta.get("luma_usd",0.0),
            r["runway_usd"] + delta.get("runway_usd",0.0),
            r["img_usd"] + delta.get("img_usd",0.0),
            uid,
            ymd,
        ),
    )
    con.commit()
    con.close()

def _wallet_get(uid: int) -> dict:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES(?)", (uid,))
    con.commit()
    cur.execute("SELECT luma_usd, runway_usd, img_usd, usd FROM wallet WHERE user_id=?", (uid,))
    row = cur.fetchone()
    con.close()
    return {"luma_usd": row[0], "runway_usd": row[1], "img_usd": row[2], "usd": row[3]}

def _wallet_total_get(uid: int) -> float:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES(?)", (uid,))
    con.commit()
    cur.execute("SELECT usd FROM wallet WHERE user_id=?", (uid,))
    row = cur.fetchone()
    con.close()
    return float(row[0] if row and row[0] is not None else 0.0)

def _wallet_total_add(uid: int, usd: float):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("UPDATE wallet SET usd=COALESCE(usd,0)+? WHERE user_id=?", (float(usd), uid))
    con.commit()
    con.close()

def _wallet_total_take(uid: int, usd: float) -> bool:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT usd FROM wallet WHERE user_id=?", (uid,))
    row = cur.fetchone()
    bal = float(row[0] if row and row[0] is not None else 0.0)
    if bal + 1e-9 < usd:
        con.close()
        return False
    cur.execute("UPDATE wallet SET usd=usd-? WHERE user_id=?", (float(usd), uid))
    con.commit()
    con.close()
    return True

# ───── Тарифные лимиты ─────
LIMITS = {
    "free":      {"text_per_day": 5,    "luma_budget_usd": 0.40, "runway_budget_usd": 0.0,  "img_budget_usd": 0.05, "allow_engines": ["gpt","luma","images"]},
    "start":     {"text_per_day": 200,  "luma_budget_usd": 0.8,  "runway_budget_usd": 0.0,  "img_budget_usd": 0.2,  "allow_engines": ["gpt","luma","midjourney","images"]},
    "pro":       {"text_per_day": 1000, "luma_budget_usd": 4.0,  "runway_budget_usd": 7.0,  "img_budget_usd": 1.0,  "allow_engines": ["gpt","luma","runway","midjourney","images"]},
    "ultimate":  {"text_per_day": 5000, "luma_budget_usd": 8.0,  "runway_budget_usd": 14.0, "img_budget_usd": 2.0,  "allow_engines": ["gpt","luma","runway","midjourney","images"]},
}

def _limits_for(uid: int) -> dict:
    tier = get_subscription_tier(uid)
    d = LIMITS.get(tier, LIMITS["free"]).copy()
    d["tier"] = tier
    return d

def check_text_and_inc(uid: int, uname: str|None=None) -> tuple[bool,int,str]:
    if is_unlimited(uid, uname):
        _usage_update(uid, text_count=1)
        return True, 999999, "ultimate"
    lim = _limits_for(uid)
    row = _usage_row(uid)
    left = max(0, lim["text_per_day"] - row["text_count"])
    if left <= 0:
        return False, 0, lim["tier"]
    _usage_update(uid, text_count=1)
    return True, left-1, lim["tier"]

def _calc_oneoff_price_rub(engine: str, usd_cost: float) -> int:
    markup = ONEOFF_MARKUP_RUNWAY if engine=="runway" else ONEOFF_MARKUP_DEFAULT
    rub = usd_cost * (1.0 + markup) * USD_RUB
    val = int(rub + 0.999)
    return max(MIN_RUB_FOR_INVOICE, val)

def _can_spend_or_offer(uid: int, uname: str|None, engine: str, est_cost_usd: float) -> tuple[bool,str]:
    if is_unlimited(uid, uname):
        if engine in ("luma","runway","img"):
            _usage_update(uid, **{f"{engine}_usd": est_cost_usd})
        return True, ""
    if engine not in ("luma","runway","img"):
        return True, ""
    lim = _limits_for(uid)
    row = _usage_row(uid)
    spent = row[f"{engine}_usd"]
    budget = lim[f"{engine}_budget_usd"]
    if spent + est_cost_usd <= budget + 1e-9:
        _usage_update(uid, **{f"{engine}_usd": est_cost_usd})
        return True, ""
    need = max(0.0, spent + est_cost_usd - budget)
    if need > 0:
        if _wallet_total_take(uid, need):
            _usage_update(uid, **{f"{engine}_usd": est_cost_usd})
            return True, ""
        if lim["tier"] == "free":
            return False, "ASK_SUBSCRIBE"
        return False, f"OFFER:{need:.2f}"
    return True, ""

def _register_engine_spend(uid: int, engine: str, usd: float):
    if engine in ("luma","runway","img"):
        _usage_update(uid, **{f"{engine}_usd": float(usd)})

# ───── Системные промпты ─────
SYSTEM_PROMPT = (
    "Ты дружелюбный и лаконичный ассистент. Отвечай по сути, структурируй шагами/списками, не выдумывай факты. "
    "Если уместно — в конце короткий список источников или примеров."
)
VISION_SYSTEM_PROMPT = (
    "Опиши содержимое изображения коротко и точно: объекты, текст, ключевые детали. "
    "Не пытайся идентифицировать личности людей по фото."
)

# ───── Текст / Визион ─────
def _pick_vision_model() -> str:
    m = (OPENAI_VISION_MODEL or OPENAI_MODEL).strip()
    return m

async def ask_openai_text(user_text: str, web_ctx: str="") -> str:
    user_text = (user_text or "").strip()
    if not user_text:
        return "Пустой запрос."
    messages = [{"role":"system","content":SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({"role":"system","content":f"Контекст веб-поиска:\n{web_ctx}"})
    messages.append({"role":"user","content":user_text})
    last_err = None
    for attempt in range(3):
        try:
            resp = oai_llm.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                temperature=0.6,
            )
            txt = (resp.choices[0].message.content or "").strip()
            if txt:
                return txt
        except Exception as e:
            last_err = e
            log.warning("LLM attempt %d failed: %s", attempt+1, e)
            await asyncio.sleep(0.8*(attempt+1))
    log.error("ask_openai_text failed: %s", last_err)
    return "⚠️ Не удалось получить ответ от модели. Попробуйте переформулировать запрос."

async def ask_openai_vision(user_text: str, img_b64: str, mime: str) -> str:
    try:
        prompt = (user_text or "Опиши, что на изображении.").strip()
        model = _pick_vision_model()
        resp = oai_llm.chat.completions.create(
            model=model,
            messages=[
                {"role":"system","content":VISION_SYSTEM_PROMPT},
                {"role":"user","content":[
                    {"type":"text","text":prompt},
                    {"type":"image_url","image_url":{"url":f"data:{mime};base64,{img_b64}"}}
                ]}
            ],
            temperature=0.4,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("Vision error: %s", e)
        return "Не удалось проанализировать изображение."

# ───── Пользовательские настройки (TTS) ─────
def _db_init_prefs():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS user_prefs (
        user_id INTEGER PRIMARY KEY,
        tts_on INTEGER DEFAULT 0,
        lang TEXT)""")
    con.commit()
    con.close()


def _tts_get(uid: int) -> bool:
    try:
        _db_init_prefs()
    except Exception:
        pass
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO user_prefs(user_id, tts_on) VALUES (?,0)", (uid,))
    con.commit()
    cur.execute("SELECT tts_on FROM user_prefs WHERE user_id=?", (uid,))
    row = cur.fetchone()
    con.close()
    return bool(row and row[0])


def _tts_set(uid: int, on: bool):
    try:
        _db_init_prefs()
    except Exception:
        pass
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO user_prefs(user_id, tts_on) VALUES (?,?)",
        (uid, 1 if on else 0),
    )
    cur.execute("UPDATE user_prefs SET tts_on=? WHERE user_id=?", (1 if on else 0, uid))
    con.commit()
    con.close()


# ───── Надёжный TTS REST → OGG ─────
def _tts_bytes_sync(text: str) -> bytes | None:
    try:
        if not OPENAI_TTS_KEY:
            return None
        if OPENAI_TTS_KEY.startswith("sk-or-"):
            log.error("OPENAI_TTS_KEY похож на OpenRouter — нужен реальный OpenAI ключ.")
            return None
        url = f"{OPENAI_TTS_BASE_URL}/audio/speech"
        headers = {"Authorization": f"Bearer {OPENAI_TTS_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": OPENAI_TTS_MODEL,
            "voice": OPENAI_TTS_VOICE,
            "input": text,
            "format": "ogg",
        }
        r = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        r.raise_for_status()
        return r.content if r.content else None
    except Exception as e:
        log.exception("TTS error: %s", e)
        return None


async def maybe_tts_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    uid = update.effective_user.id
    if not _tts_get(uid):
        return
    text = (text or "").strip()
    if not text:
        return
    if len(text) > TTS_MAX_CHARS:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text(
                f"🔇 Озвучка пропущена (>{TTS_MAX_CHARS} симв.)."
            )
        return
    try:
        with contextlib.suppress(Exception):
            await context.bot.send_chat_action(
                update.effective_chat.id, ChatAction.UPLOAD_VOICE
            )
        audio = await asyncio.to_thread(_tts_bytes_sync, text)
        if not audio:
            with contextlib.suppress(Exception):
                await update.effective_message.reply_text(
                    "🔇 Не удалось синтезировать голос."
                )
            return
        bio = BytesIO(audio)
        bio.seek(0)
        bio.name = "say.ogg"
        await update.effective_message.reply_voice(
            voice=InputFile(bio), caption=text
        )
    except Exception as e:
        log.exception("maybe_tts_reply error: %s", e)


async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, True)
    await update.effective_message.reply_text(
        f"🔊 Озвучка включена. Лимит {TTS_MAX_CHARS} символов."
    )


async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, False)
    await update.effective_message.reply_text("🔈 Озвучка выключена.")


# ───── STT ─────
def _mime_from_filename(fn: str) -> str:
    fnl = (fn or "").lower()
    if fnl.endswith((".ogg", ".oga")):
        return "audio/ogg"
    if fnl.endswith(".mp3"):
        return "audio/mpeg"
    if fnl.endswith((".m4a", ".mp4")):
        return "audio/mp4"
    if fnl.endswith(".wav"):
        return "audio/wav"
    if fnl.endswith(".webm"):
        return "audio/webm"
    return "application/octet-stream"


async def stt_deepgram(audio: bytes, filename: str) -> str:
    """
    Распознавание через Deepgram (если задан DEEPGRAM_API_KEY).
    """
    if not DEEPGRAM_API_KEY:
        return ""
    try:
        mime = _mime_from_filename(filename)
        url = "https://api.deepgram.com/v1/listen?model=nova-2-general&smart_format=true"
        headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": mime,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, headers=headers, content=audio)
            r.raise_for_status()
            data = r.json()
        text = (
            data.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
        )
        return text.strip()
    except Exception as e:
        log.exception("stt_deepgram error: %s", e)
        return ""


async def stt_openai(audio: bytes, filename: str) -> str:
    """
    Распознавание через OpenAI Whisper (если есть OPENAI_STT_KEY).
    """
    if not OPENAI_STT_KEY:
        return ""
    try:
        client = _oai_stt_client()
        mime = _mime_from_filename(filename)
        t = client.audio.transcriptions.create(
            model=OPENAI_STT_MODEL,
            file=("audio", audio, mime),
        )
        text = getattr(t, "text", "") or ""
        return text.strip()
    except Exception as e:
        log.exception("stt_openai error: %s", e)
        return ""


async def stt_recognize(audio: bytes, filename: str) -> str:
    """
    Сначала пытаемся Deepgram, потом OpenAI.
    """
    txt = await stt_deepgram(audio, filename)
    if txt:
        return txt
    txt = await stt_openai(audio, filename)
    return txt or ""


# ───── Документы (PDF / DOCX / EPUB / FB2 / TXT) ─────
try:
    import docx
except Exception:
    docx = None

try:
    from pdfminer.high_level import extract_text as pdf_extract_text
except Exception:
    pdf_extract_text = None

try:
    from ebooklib import epub
except Exception:
    epub = None

try:
    import zipfile
except Exception:
    zipfile = None


async def parse_pdf_bytes(data: bytes) -> str:
    if not pdf_extract_text:
        return "Модуль pdfminer.six недоступен, не могу разобрать PDF."
    try:
        with BytesIO(data) as bio:
            text = pdf_extract_text(bio)
        return text[:20000]
    except Exception as e:
        log.exception("parse_pdf_bytes error: %s", e)
        return "Не удалось прочитать PDF."


async def parse_docx_bytes(data: bytes) -> str:
    if not docx:
        return "Модуль python-docx недоступен, не могу разобрать DOCX."
    try:
        with BytesIO(data) as bio:
            document = docx.Document(bio)
        parts = [p.text for p in document.paragraphs if p.text.strip()]
        return "\n".join(parts)[:20000]
    except Exception as e:
        log.exception("parse_docx_bytes error: %s", e)
        return "Не удалось прочитать DOCX."


async def parse_epub_bytes(data: bytes) -> str:
    if not epub:
        return "Модуль ebooklib недоступен, не могу разобрать EPUB."
    try:
        with BytesIO(data) as bio:
            book = epub.read_epub(bio)
        texts = []
        from bs4 import BeautifulSoup
        for item in book.get_items():
            if item.get_type() == epub.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_body_content(), "html.parser")
                texts.append(soup.get_text(separator=" ", strip=True))
        return "\n".join(texts)[:20000]
    except Exception as e:
        log.exception("parse_epub_bytes error: %s", e)
        return "Не удалось прочитать EPUB."


async def parse_fb2_bytes(data: bytes) -> str:
    try:
        import xml.etree.ElementTree as ET
    except Exception:
        return "Не удалось подключить xml-парсер для FB2."
    try:
        if zipfile and zipfile.is_zipfile(BytesIO(data)):
            with zipfile.ZipFile(BytesIO(data)) as z:
                name = next((n for n in z.namelist() if n.lower().endswith(".fb2")), None)
                if not name:
                    return "В архиве FB2 не найден основной файл."
                xml_data = z.read(name)
        else:
            xml_data = data
        root = ET.fromstring(xml_data)
        texts = []
        for elem in root.iter():
            if elem.text and elem.text.strip():
                texts.append(elem.text.strip())
        return " ".join(texts)[:20000]
    except Exception as e:
        log.exception("parse_fb2_bytes error: %s", e)
        return "Не удалось прочитать FB2."


async def summarize_long_text(user_prompt: str, raw_text: str) -> str:
    """
    Краткая выжимка + ответы по документу.
    """
    if not raw_text.strip():
        return "Файл пустой или не удалось извлечь текст."
    context_block = raw_text[:18000]
    q = (
        "У меня есть документ. Сначала дай структурированное краткое содержание, "
        "затем ответь на мой запрос по нему.\n\n"
        f"Документ:\n{context_block}\n\n"
        f"Мой запрос: {user_prompt or 'Просто сделай краткое содержание'}"
    )
    return await ask_openai_text(q)


# ───── Фото / картинки ─────
async def download_file_bytes(bot, file_id: str) -> tuple[bytes, str]:
    f = await bot.get_file(file_id)
    bio = BytesIO()
    await f.download_to_memory(out=bio)
    bio.seek(0)
    filename = getattr(f, "file_path", "") or "file"
    return bio.read(), filename


async def handle_vision_for_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str):
    try:
        data, filename = await download_file_bytes(context.bot, file_id)
        mime = "image/jpeg"
        if filename.lower().endswith(".png"):
            mime = "image/png"
        b64 = base64.b64encode(data).decode("ascii")
        caption = update.effective_message.caption or ""
        txt = await ask_openai_vision(caption, b64, mime)
        await update.effective_message.reply_text(txt or "Не удалось описать изображение.")
        await maybe_tts_reply(update, context, txt)
    except Exception as e:
        log.exception("handle_vision_for_photo error: %s", e)
        await update.effective_message.reply_text("Ошибка при анализе изображения.")


async def handle_rembg_for_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str):
    if rembg_remove is None or Image is None:
        await update.effective_message.reply_text(
            "Библиотека для удаления фона не установлена на сервере."
        )
        return
    try:
        data, _ = await download_file_bytes(context.bot, file_id)
        out = rembg_remove(data)
        bio = BytesIO(out)
        bio.name = "no_bg.png"
        bio.seek(0)
        await update.effective_message.reply_document(
            document=InputFile(bio),
            caption="Фон удалён ✅",
        )
    except Exception as e:
        log.exception("handle_rembg_for_photo error: %s", e)
        await update.effective_message.reply_text("Не удалось удалить фон.")


async def handle_openai_image_from_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    size: str = "1024x1024",
):
    """
    /img - генерация картинки по описанию.
    """
    uid = update.effective_user.id
    uname = update.effective_user.username or ""
    ok, reason = _can_spend_or_offer(uid, uname, "img", IMG_COST_USD)
    if not ok:
        if reason == "ASK_SUBSCRIBE":
            await send_subscribe_offer(update, context, "Для генерации картинок нужна подписка или баланс.")
            return
        if reason.startswith("OFFER:"):
            need = float(reason.split(":", 1)[1])
            rub = _calc_oneoff_price_rub("img", need)
            await send_oneoff_offer(update, context, "img", need, rub)
            return

    try:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_chat_action(ChatAction.UPLOAD_PHOTO)
    except Exception:
        pass

    try:
        res = oai_img.images.generate(
            model=IMAGES_MODEL,
            prompt=prompt,
            size=size,
            n=1,
        )
        b64 = res.data[0].b64_json
        img_bytes = base64.b64decode(b64)
        bio = BytesIO(img_bytes)
        bio.name = "image.png"
        bio.seek(0)
        await update.effective_message.reply_photo(
            photo=InputFile(bio),
            caption="Сгенерировал изображение по твоему описанию ✅",
        )
    except Exception as e:
        log.exception("OpenAI image error: %s", e)
        await update.effective_message.reply_text(
            "Не получилось сгенерировать изображение. Попробуй переформулировать запрос."
        )


# ───── Luma / Runway (видео) ─────
async def luma_create_job(prompt: str) -> str:
    """
    Возвращает generation_id (или пустую строку при ошибке).
    """
    if not LUMA_API_KEY:
        return ""
    try:
        headers = {"Authorization": f"Bearer {LUMA_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "prompt": prompt,
            "model": LUMA_MODEL,
            "aspect_ratio": LUMA_ASPECT,
            "duration": LUMA_DURATION_S,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(LUMA_BASE_URL + LUMA_CREATE_PATH, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        gen_id = data.get("id") or data.get("generation_id") or ""
        return str(gen_id)
    except Exception as e:
        log.exception("luma_create_job error: %s", e)
        return ""


async def luma_wait_result(generation_id: str) -> str:
    """
    Ожидаем готовое видео и возвращаем URL.
    """
    if not generation_id:
        return ""
    headers = {"Authorization": f"Bearer {LUMA_API_KEY}"}
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                if time.time() - started > LUMA_MAX_WAIT_S:
                    return ""
                url = LUMA_BASE_URL + LUMA_STATUS_PATH.format(id=generation_id)
                r = await client.get(url, headers=headers)
                r.raise_for_status()
                data = r.json()
                status = str(data.get("status") or data.get("state") or "").lower()
                if status in ("completed", "succeeded", "success"):
                    assets = data.get("assets") or data.get("output") or {}
                    vid = (
                        assets.get("video")
                        or assets.get("mp4")
                        or (assets.get("videos") or [None])[0]
                    )
                    return str(vid or "")
                if status in ("failed", "error"):
                    return ""
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("luma_wait_result error: %s", e)
        return ""


async def runway_create_job(prompt: str) -> str:
    """
    Создаём задачу в Runway (text-to-video).
    """
    if not RUNWAY_API_KEY:
        return ""
    try:
        headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": RUNWAY_MODEL,
            "input": {
                "prompt": prompt,
                "ratio": RUNWAY_RATIO,
            },
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(RUNWAY_BASE_URL + RUNWAY_CREATE_PATH, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        task_id = data.get("id") or data.get("task_id") or data.get("task", {}).get("id") or ""
        return str(task_id)
    except Exception as e:
        log.exception("runway_create_job error: %s", e)
        return ""


async def runway_wait_result(task_id: str) -> str:
    """
    Ожидаем URL видео от Runway.
    """
    if not task_id:
        return ""
    headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}"}
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                if time.time() - started > RUNWAY_MAX_WAIT_S:
                    return ""
                url = RUNWAY_BASE_URL + RUNWAY_STATUS_PATH.format(id=task_id)
                r = await client.get(url, headers=headers)
                r.raise_for_status()
                data = r.json()
                status = (
                    data.get("status")
                    or data.get("task", {}).get("status")
                    or ""
                ).lower()
                if status in ("succeeded", "completed", "success"):
                    out = data.get("output") or data.get("task", {}).get("output") or {}
                    vid = (
                        out.get("video")
                        or out.get("asset_url")
                        or (out.get("assets") or {}).get("video")
                    )
                    return str(vid or "")
                if status in ("failed", "error"):
                    return ""
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("runway_wait_result error: %s", e)
        return ""


async def start_video_generation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    engine: str,
    prompt: str,
):
    """
    Общий вход: engine in {luma, runway}, text prompt.
    """
    uid = update.effective_user.id
    uname = update.effective_user.username or ""
    est_cost = RUNWAY_UNIT_COST_USD if engine == "runway" else 1.0

    ok, reason = _can_spend_or_offer(uid, uname, "runway" if engine == "runway" else "luma", est_cost)
    if not ok:
        if reason == "ASK_SUBSCRIBE":
            await send_subscribe_offer(update, context, "Для генерации видео нужна подписка или баланс.")
            return
        if reason.startswith("OFFER:"):
            need = float(reason.split(":", 1)[1])
            rub = _calc_oneoff_price_rub("runway" if engine == "runway" else "luma", need)
            await send_oneoff_offer(update, context, engine, need, rub)
            return

    msg = await update.effective_message.reply_text(
        "🎬 Запускаю генерацию видео, это может занять несколько минут..."
    )

    async def job():
        try:
            if engine == "runway":
                task_id = await runway_create_job(prompt)
                if not task_id:
                    await msg.edit_text("Не удалось создать задачу в Runway.")
                    return
                url = await runway_wait_result(task_id)
            else:
                gen_id = await luma_create_job(prompt)
                if not gen_id:
                    await msg.edit_text("Не удалось создать задачу в Luma.")
                    return
                url = await luma_wait_result(gen_id)

            if not url:
                await msg.edit_text("Видео не удалось сгенерировать. Попробуй изменить запрос.")
                return

            try:
                async with httpx.AsyncClient(timeout=600.0) as client:
                    r = await client.get(url)
                    r.raise_for_status()
                    data = r.content
                bio = BytesIO(data)
                bio.name = "video.mp4"
                bio.seek(0)
                await msg.edit_text("Видео готово, отправляю 👇")
                await msg.reply_video(video=InputFile(bio))
            except Exception as e:
                log.exception("send video error: %s", e)
                await msg.edit_text(f"Видео сгенерировано, но не удалось отправить ссылку: {url}")
        except Exception as e:
            log.exception("video job error: %s", e)
            with contextlib.suppress(Exception):
                await msg.edit_text("Произошла ошибка при генерации видео.")

    context.application.create_task(job())


# ───── Баланс / Пополнения / Подписки ─────
def _pretty_until(dt: datetime | None) -> str:
    if not dt:
        return "нет активной подписки"
    return dt.astimezone(timezone.utc).strftime("%d.%m.%Y")


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tier = get_subscription_tier(uid)
    until = get_subscription_until(uid)
    w = _wallet_get(uid)
    msg = (
        f"💰 *Баланс и доступ*\n\n"
        f"Тариф: *{tier.upper()}*\n"
        f"Подписка до: *{_pretty_until(until)}*\n\n"
        f"Виртуальный кошелёк (USD):\n"
        f"• Доступно: *{w['usd']:.2f}*\n"
        f"• Luma расход за день: *{_usage_row(uid)['luma_usd']:.2f}*\n"
        f"• Runway расход за день: *{_usage_row(uid)['runway_usd']:.2f}*\n"
        f"• Images расход за день: *{_usage_row(uid)['img_usd']:.2f}*\n"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Пополнить кошелёк", callback_data="pay:wallet")],
        [InlineKeyboardButton("⭐ Тарифы и подписка", callback_data="plans:open")],
    ])
    await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)


async def send_subscribe_offer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    reason: str = "",
):
    text = "🔔 Достигнут лимит текущего тарифа."
    if reason:
        text += "\n" + reason
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Посмотреть тарифы", callback_data="plans:open")],
    ])
    await update.effective_message.reply_text(text, reply_markup=kb)


async def send_oneoff_offer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    engine: str,
    need_usd: float,
    price_rub: int,
):
    """
    Предложение разовой оплаты для конкретного действия (Runway/Luma/Images).
    """
    text = (
        f"Для этого действия нужно ~{need_usd:.2f} USD бюджета.\n"
        f"Могу выставить счёт на *{price_rub} ₽* и зачислить на кошелёк.\n\n"
        f"После оплаты действие выполнится из кошелька."
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"Оплатить {price_rub} ₽ через Telegram",
                callback_data=f"pay:oneoff:{engine}:{price_rub}:{need_usd:.2f}",
            )
        ],
        [InlineKeyboardButton("⭐ Подписка вместо разовой оплаты", callback_data="plans:open")],
    ])
    await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


# ───── Тарифы ─────
PLAN_HUMAN_NAMES = {
    "start": "START",
    "pro": "PRO",
    "ultimate": "ULTIMATE",
}

PLAN_DESCRIPTIONS = {
    "start": (
        "• До 200 запросов в день\n"
        "• Видео Luma — небольшой дневной бюджет\n"
        "• Картинки, фото-инструменты\n"
        "• Поддержка текста/документов/голоса"
    ),
    "pro": (
        "• До 1000 запросов в день\n"
        "• Luma + Runway с приличным бюджетом\n"
        "• Фото/видео, документы, TTS/STS\n"
        "• Оптимально для активной учёбы/работы"
    ),
    "ultimate": (
        "• До 5000 запросов в день\n"
        "• Максимальные бюджеты Luma/Runway/Images\n"
        "• Приоритетное использование\n"
        "• Для продвинутых и командной работы"
    ),
}


def _build_plans_text(uid: int) -> str:
    tier = get_subscription_tier(uid)
    until = get_subscription_until(uid)
    txt = "⭐ *Подписка и тарифы GPT-5 PRO*\n\n"
    txt += f"Сейчас у тебя тариф: *{tier.upper()}*, до: *{_pretty_until(until)}*\n\n"
    for key in ("start", "pro", "ultimate"):
        prices = PLAN_PRICE_TABLE[key]
        txt += f"*{PLAN_HUMAN_NAMES[key]}* — от *{prices['month']} ₽/мес*\n"
        txt += PLAN_DESCRIPTIONS[key] + "\n\n"
    txt += "Ниже выбери тариф и срок подписки."
    return txt


def _plans_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for plan in ("start", "pro", "ultimate"):
        prices = PLAN_PRICE_TABLE[plan]
        rows.append([
            InlineKeyboardButton(
                f"{PLAN_HUMAN_NAMES[plan]} • 1 мес ({prices['month']} ₽)",
                callback_data=f"plan:{plan}:month",
            )
        ])
        rows.append([
            InlineKeyboardButton(
                f"{PLAN_HUMAN_NAMES[plan]} • 6 мес ({prices['year']//2} ₽)",
                callback_data=f"plan:{plan}:halfyear",
            )
        ])
    rows.append([InlineKeyboardButton("Отмена", callback_data="plans:close")])
    return InlineKeyboardMarkup(rows)


async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = _build_plans_text(uid)
    kb = _plans_keyboard()
    await update.effective_message.reply_text(txt, parse_mode="Markdown", reply_markup=kb)


async def show_plans_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Срабатывает на кнопку '⭐ Подписка' в клавиатуре.
    """
    await cmd_plans(update, context)


async def handle_plans_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "plans:open":
        uid = query.from_user.id
        txt = _build_plans_text(uid)
        kb = _plans_keyboard()
        await query.message.edit_text(txt, parse_mode="Markdown", reply_markup=kb)
        return
    if data == "plans:close":
        with contextlib.suppress(Exception):
            await query.message.delete()
        return
    if not data.startswith("plan:"):
        return

    _, plan, term = data.split(":", 2)
    if term == "month":
        term_key = "month"
        months = 1
    elif term == "halfyear":
        term_key = "year"
        months = 6
    else:
        term_key = "month"
        months = 1

    prices = PLAN_PRICE_TABLE.get(plan)
    if not prices:
        await query.message.reply_text("Не удалось найти такой тариф.")
        return

    amount_rub = prices[term_key]
    title = f"Подписка {PLAN_HUMAN_NAMES[plan]} ({months} мес)"
    description = "Подписка на GPT-5 ProBot."

    if not PROVIDER_TOKEN:
        await query.message.reply_text(
            "Платёжный провайдер не настроен (нет PROVIDER_TOKEN_YOOKASSA). "
            "Обратись к администратору бота."
        )
        return

    prices_tg = [LabeledPrice(label=_ascii_label(title), amount=amount_rub * 100)]
    payload = f"sub:{plan}:{months}"

    with contextlib.suppress(Exception):
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=title,
            description=description,
            provider_token=PROVIDER_TOKEN,
            currency=CURRENCY,
            prices=prices_tg,
            payload=payload,
        )


# ───── Платёжные хендлеры (Telegram / ЮKassa) ─────
async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    try:
        await query.answer(ok=True)
    except TelegramError as e:
        log.exception("precheckout_handler TelegramError: %s", e)
        try:
            await query.answer(ok=False, error_message="Ошибка при обработке платежа.")
        except Exception:
            pass


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    payload = sp.invoice_payload or ""
    uid = update.effective_user.id

    if payload.startswith("sub:"):
        _, plan, months_s = payload.split(":", 2)
        months = int(months_s or "1")
        until = activate_subscription_with_tier(uid, plan, months)
        await update.message.reply_text(
            f"✅ Подписка *{PLAN_HUMAN_NAMES.get(plan, plan)}* активирована до "
            f"*{_pretty_until(until)}*.",
            parse_mode="Markdown",
        )
        return

    if payload.startswith("wallet:"):
        _, usd_s = payload.split(":", 1)
        usd = float(usd_s or "0")
        _wallet_total_add(uid, usd)
        await update.message.reply_text(
            f"💰 Баланс пополнен на {usd:.2f} USD. Спасибо!"
        )
        return

    if payload.startswith("oneoff:"):
        _, engine, usd_s = payload.split(":", 2)
        usd = float(usd_s or "0")
        _wallet_total_add(uid, usd)
        await update.message.reply_text(
            f"✅ Пополнение кошелька на {usd:.2f} USD для {engine}. "
            "Теперь можно повторить запрос."
        )
        return

    await update.message.reply_text("✅ Платёж успешно выполнен.")


async def callback_pay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data == "pay:wallet":
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("500 ₽", callback_data="pay:wallet_amount:500"),
                InlineKeyboardButton("1000 ₽", callback_data="pay:wallet_amount:1000"),
            ],
            [
                InlineKeyboardButton("2000 ₽", callback_data="pay:wallet_amount:2000"),
            ],
        ])
        await query.message.reply_text(
            "Выбери сумму пополнения (переведу в USD по внутреннему курсу).",
            reply_markup=kb,
        )
        return

    if data.startswith("pay:wallet_amount:"):
        if not PROVIDER_TOKEN:
            await query.message.reply_text(
                "Платёжный провайдер не настроен (нет PROVIDER_TOKEN_YOOKASSA)."
            )
            return
        _, _, rub_s = data.split(":", 2)
        rub = int(rub_s or "0")
        usd = rub / USD_RUB
        title = f"Пополнение кошелька {rub} ₽ (~{usd:.2f} USD)"
        prices_tg = [LabeledPrice(label=_ascii_label(title), amount=rub * 100)]
        payload = f"wallet:{usd:.2f}"
        with contextlib.suppress(Exception):
            await context.bot.send_invoice(
                chat_id=query.message.chat_id,
                title=title,
                description="Пополнение виртуального кошелька бота.",
                provider_token=PROVIDER_TOKEN,
                currency=CURRENCY,
                prices=prices_tg,
                payload=payload,
            )
        return

    if data.startswith("pay:oneoff:"):
        parts = data.split(":")
        if len(parts) != 5:
            return
        _, _, engine, rub_s, usd_s = parts
        rub = int(rub_s or "0")
        usd = float(usd_s or "0")
        if not PROVIDER_TOKEN:
            await query.message.reply_text(
                "Платёжный провайдер не настроен (нет PROVIDER_TOKEN_YOOKASSA)."
            )
            return
        title = f"Разовое действие {engine.upper()} · {rub} ₽"
        prices_tg = [LabeledPrice(label=_ascii_label(title), amount=rub * 100)]
        payload = f"oneoff:{engine}:{usd:.2f}"
        with contextlib.suppress(Exception):
            await context.bot.send_invoice(
                chat_id=query.message.chat_id,
                title=title,
                description="Разовое пополнение бюджета для конкретного действия.",
                provider_token=PROVIDER_TOKEN,
                currency=CURRENCY,
                prices=prices_tg,
                payload=payload,
            )
        return


# ───── Режимы: Учёба / Работа / Развлечения ─────
MODE_LABELS = {
    "study": "🎓 Учёба",
    "work": "💼 Работа",
    "fun": "🔥 Развлечения",
    "general": "🤖 Обычный",
}


def get_mode(uid: int) -> str:
    return kv_get(f"mode:{uid}", "general")


def set_mode(uid: int, mode: str):
    if mode not in MODE_LABELS:
        mode = "general"
    kv_set(f"mode:{uid}", mode)


async def handle_mode_button(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    uid = update.effective_user.id
    set_mode(uid, mode)
    label = MODE_LABELS.get(mode, "🤖 Обычный")
    await update.effective_message.reply_text(
        f"Режим работы бота переключён на: *{label}*.",
        parse_mode="Markdown",
    )


# ───── Движки / Нейросети ─────
ENGINE_LABELS = {
    "gpt": "GPT-5 Pro (универсальный)",
    "fast": "Быстрый GPT (дешевле/скорее)",
    "vision": "Vision (фото/картинки)",
    "code": "Кодер / программист",
    "tools": "Фото/Видео-инструменты",
}


def get_engine(uid: int) -> str:
    return kv_get(f"engine:{uid}", "gpt")


def set_engine(uid: int, engine: str):
    if engine not in ENGINE_LABELS:
        engine = "gpt"
    kv_set(f"engine:{uid}", engine)


def engines_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key in ("gpt", "fast", "vision", "code", "tools"):
        rows.append(
            [InlineKeyboardButton(ENGINE_LABELS[key], callback_data=f"engine:{key}")]
        )
    rows.append([InlineKeyboardButton("Закрыть", callback_data="engine:close")])
    return InlineKeyboardMarkup(rows)


async def cmd_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    current = get_engine(uid)
    txt = (
        "🧠 *Движки / Нейросети*\n\n"
        "Выбери, как бот будет вести себя по умолчанию.\n\n"
        f"Текущий профиль: *{ENGINE_LABELS.get(current, 'GPT-5 Pro')}*"
    )
    await update.effective_message.reply_text(
        txt,
        parse_mode="Markdown",
        reply_markup=engines_keyboard(),
    )


async def callback_engine_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "engine:close":
        with contextlib.suppress(Exception):
            await query.message.delete()
        return
    if not data.startswith("engine:"):
        return
    _, eng = data.split(":", 1)
    uid = query.from_user.id
    set_engine(uid, eng)
    txt = f"✅ Движок переключён на: *{ENGINE_LABELS.get(eng, 'GPT-5 Pro')}*."
    with contextlib.suppress(Exception):
        await query.message.edit_text(txt, parse_mode="Markdown")


# ───── Клавиатура ─────
def main_reply_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton("🎓 Учёба"), KeyboardButton("💼 Работа"), KeyboardButton("🔥 Развлечения")],
        [KeyboardButton("🧠 Движки"), KeyboardButton("💰 Баланс"), KeyboardButton("⭐ Подписка")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


# ───── Текст о возможностях бота ─────
CAPABILITIES_TEXT = (
    "Вот что я умею:\n\n"
    "💬 *Текст*\n"
    "• Отвечаю на вопросы, помогаю с идеями, текстами, письмами.\n"
    "• Объясняю сложное простым языком, перевожу, делаю конспекты.\n\n"
    "🎓 *Учёба*\n"
    "• Помогаю разбирать темы, готовиться к экзаменам, делать шпаргалки.\n"
    "• Решаю задачи с пошаговыми объяснениями (без списывания с готовых решений).\n\n"
    "💼 *Работа*\n"
    "• Тексты для бизнеса, презентации, скрипты, аналитика.\n"
    "• Помощь с таблицами, планами, идеями, структурой.\n\n"
    "🖼 *Фото и картинки*\n"
    "• Анализирую изображения (через GPT-Vision).\n"
    "• Могу удалить фон (если библиотека активна).\n"
    "• Генерирую изображения по описанию команды /img.\n\n"
    "📚 *Документы*\n"
    "• PDF, DOCX, EPUB, FB2, TXT — делаю краткое содержание и отвечаю на вопросы по файлу.\n\n"
    "🗣 *Голос*\n"
    "• Принимаю голосовые сообщения, перевожу в текст и отвечаю.\n"
    "• Могу озвучивать ответы (команды /voice_on и /voice_off).\n\n"
    "🎬 *Видео (Luma / Runway)*\n"
    "• Могу запустить генерацию коротких роликов по твоему описанию.\n\n"
    "💳 *Подписка и кошелёк*\n"
    "• Есть уровни тарифов и внутренний USD-кошелёк для доп. действий.\n"
    "• Кнопка «⭐ Подписка» всегда покажет актуальные тарифы и оплату.\n\n"
    "Задавай любой вопрос текстом или голосом — я подберу нужный режим."
)


async def send_capabilities(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        CAPABILITIES_TEXT,
        parse_mode="Markdown",
    )


# ───── /start /help ─────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    args = context.args or []
    lot_id = args[0] if args else ""
    if lot_id:
        kv_set(f"lot:{uid}", lot_id)

    tier = get_subscription_tier(uid)
    until = get_subscription_until(uid)

    txt = (
        f"Привет, {user.first_name or 'друг'}! Я *GPT-5 ProBot* — твой мультифункциональный ассистент.\n\n"
        "Я умею:\n"
        "• Помогать в учёбе, работе и для развлечения\n"
        "• Анализировать фото и документы\n"
        "• Делать голос ↔ текст, озвучивать ответы\n"
        "• Генерировать картинки и запускать видео через нейросети\n\n"
        f"Твой текущий тариф: *{tier.upper()}*, до: *{_pretty_until(until)}*\n"
    )
    if lot_id:
        txt += f"\nЯ зафиксировал номер лота: *{lot_id}* — он попадёт в заявку автоматически.\n"

    txt += "\nИспользуй кнопки ниже, чтобы переключать режимы, смотреть баланс и подписку."

    await update.effective_message.reply_text(
        txt,
        parse_mode="Markdown",
        reply_markup=main_reply_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "/start — перезапустить приветствие\n"
        "/help — эта справка\n"
        "/plans — тарифы и подписка\n"
        "/balance — баланс и лимиты\n"
        "/engines — выбор режима нейросетей\n"
        "/img <описание> — сгенерировать изображение\n"
        "/voice_on — включить озвучку ответов\n"
        "/voice_off — выключить озвучку ответов\n"
        "/video <описание> — запросить генерацию видео\n"
    )
    await update.effective_message.reply_text(txt)


# ───── Диагностика / отладка ─────
async def cmd_diag_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or ""
    lim = _limits_for(uid)
    row = _usage_row(uid)
    msg = (
        "🧪 *Диагностика лимитов*\n\n"
        f"User: `{uid}` @{uname}\n"
        f"Тариф: *{lim['tier']}*\n"
        f"Запросов сегодня: {row['text_count']} / {lim['text_per_day']}\n"
        f"Luma: {row['luma_usd']:.2f} / {lim['luma_budget_usd']:.2f} USD\n"
        f"Runway: {row['runway_usd']:.2f} / {lim['runway_budget_usd']:.2f} USD\n"
        f"Images: {row['img_usd']:.2f} / {lim['img_budget_usd']:.2f} USD\n"
        f"Безлимит? {'Да' if is_unlimited(uid, uname) else 'Нет'}"
    )
    await update.effective_message.reply_text(msg, parse_mode="Markdown")


async def cmd_diag_stt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "STT:\n"
    msg += f"Deepgram: {'ON' if DEEPGRAM_API_KEY else 'off'}\n"
    msg += f"OpenAI STT: {'ON' if OPENAI_STT_KEY else 'off'} (model={OPENAI_STT_MODEL})\n"
    await update.effective_message.reply_text(msg)


async def cmd_diag_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Images:\n"
        f"OPENAI_IMAGE_KEY set: {'yes' if OPENAI_IMAGE_KEY else 'no'}\n"
        f"Base URL: {IMAGES_BASE_URL}\n"
        f"Model: {IMAGES_MODEL}"
    )
    await update.effective_message.reply_text(msg)


async def cmd_diag_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Video engines:\n"
        f"Luma: {'ON' if LUMA_API_KEY else 'off'} (model={LUMA_MODEL}, aspect={LUMA_ASPECT})\n"
        f"Runway: {'ON' if RUNWAY_API_KEY else 'off'} (model={RUNWAY_MODEL}, ratio={RUNWAY_RATIO})\n"
    )
    await update.effective_message.reply_text(msg)


# ───── Обработка текста / голоса / медиа ─────
def _should_show_capabilities(text: str) -> bool:
    t = text.lower()
    triggers = [
        "что ты умеешь",
        "что ты можешь",
        "какие у тебя функции",
        "что ты делаешь",
        "расскажи что ты умеешь",
        "расскажи про свои возможности",
    ]
    return any(p in t for p in triggers)


def _photo_positive_trigger(text: str) -> bool:
    t = text.lower()
    phrases = [
        "оживи фото",
        "оживить фото",
        "сделай из фото видео",
        "можешь оживить фотографию",
        "что ты можешь делать с фото",
        "что можешь сделать с фотографией",
        "умеешь работать с фотографиями",
    ]
    return any(p in t for p in phrases)


async def text_entrypoint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    text = msg.text or msg.caption or ""
    text = text.strip()
    if not text:
        return

    uid = update.effective_user.id
    uname = update.effective_user.username or ""

    # спец-кнопки клавиатуры
    if text == "⭐ Подписка":
        await show_plans_button(update, context)
        return
    if text == "💰 Баланс":
        await cmd_balance(update, context)
        return
    if text == "🧠 Движки":
        await cmd_engines(update, context)
        return
    if text == "🎓 Учёба":
        await handle_mode_button(update, context, "study")
        return
    if text == "💼 Работа":
        await handle_mode_button(update, context, "work")
        return
    if text == "🔥 Развлечения":
        await handle_mode_button(update, context, "fun")
        return

    if _should_show_capabilities(text):
        await send_capabilities(update, context)
        return

    if _photo_positive_trigger(text):
        ans = (
            "Да, я умею работать с фотографиями:\n\n"
            "• Могу оживить фото, подготовив сценарий для видео (Luma/Runway).\n"
            "• Могу убрать или заменить фон.\n"
            "• Могу дорисовать недостающие детали.\n"
            "• Могу проанализировать фото и подсказать идеи.\n\n"
            "Просто загрузь фотографию, а дальше я предложу варианты действий кнопками."
        )
        await msg.reply_text(ans)
        await maybe_tts_reply(update, context, ans)
        return

    ok, left, tier = check_text_and_inc(uid, uname)
    if not ok:
        await send_subscribe_offer(
            update,
            context,
            "Ты исчерпал лимит текстовых запросов на сегодня для текущего тарифа.",
        )
        return

    mode = get_mode(uid)
    engine = get_engine(uid)
    prefix = ""

    if mode == "study":
        prefix += "Сейчас ты работаешь в режиме ПОМОЩНИКа ПО УЧЁБЕ. Объясняй понятно, с примерами и структурой.\n"
    elif mode == "work":
        prefix += "Сейчас ты работаешь в режиме ДЕЛОВОГО АССИСТЕНТА. Пиши по делу, структурировано, без воды.\n"
    elif mode == "fun":
        prefix += (
            "Сейчас ты работаешь в режиме РАЗВЛЕЧЕНИЯ. Можно немного юмора, но при этом сохраняй полезность.\n"
        )

    if engine == "code":
        prefix += "Отвечай как опытный программист, давай готовый код и пояснения.\n"
    elif engine == "vision":
        prefix += (
            "Ты делаешь упор на работу с изображениями. Если пользователь упоминает фото, "
            "советуешь загрузить его и предлагаешь действия.\n"
        )
    elif engine == "fast":
        prefix += "Отвечай более кратко и по существу, экономя токены.\n"

    full_prompt = f"{prefix}\n\n{text}" if prefix else text

    try:
        with contextlib.suppress(Exception):
            await msg.chat.send_action(ChatAction.TYPING)
        answer = await ask_openai_text(full_prompt)
        await msg.reply_text(answer)
        await maybe_tts_reply(update, context, answer)
    except Exception as e:
        log.exception("text_entrypoint error: %s", e)
        await msg.reply_text("Произошла ошибка при обращении к модели.")


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    voice = msg.voice or msg.audio
    if not voice:
        return
    file_id = voice.file_id
    try:
        with contextlib.suppress(Exception):
            await msg.chat.send_action(ChatAction.RECORD_AUDIO)
        data, filename = await download_file_bytes(context.bot, file_id)
        text = await stt_recognize(data, filename)
        if not text:
            await msg.reply_text("Не получилось распознать голос. Попробуй ещё раз.")
            return
        await msg.reply_text(f"🗣 Я услышал:\n\n{text}")
        old_text = msg.text
        msg.text = text
        try:
            await text_entrypoint(update, context)
        finally:
            msg.text = old_text
    except Exception as e:
        log.exception("voice_handler error: %s", e)
        await msg.reply_text("Ошибка обработки голосового сообщения.")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg.photo:
        return
    photo = msg.photo[-1]
    file_id = photo.file_id
    uid = update.effective_user.id

    kv_set(f"photo:{uid}", file_id)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Оживить фото (видео)", callback_data="photo:animate")],
        [InlineKeyboardButton("🧼 Убрать фон", callback_data="photo:rembg")],
        [InlineKeyboardButton("🧠 Проанализировать", callback_data="photo:vision")],
    ])
    await msg.reply_text(
        "Фото получено. Что с ним сделать?",
        reply_markup=kb,
    )


async def callback_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    uid = query.from_user.id
    file_id = kv_get(f"photo:{uid}", "")
    if not file_id:
        await query.message.reply_text("Я не нашёл сохранённое фото. Отправь его ещё раз.")
        return

    if data == "photo:vision":
        fake_update = Update(update.update_id, message=query.message)
        fake_update.effective_message = query.message
        await handle_vision_for_photo(fake_update, context, file_id)
        return

    if data == "photo:rembg":
        fake_update = Update(update.update_id, message=query.message)
        fake_update.effective_message = query.message
        await handle_rembg_for_photo(fake_update, context, file_id)
        return

    if data == "photo:animate":
        await query.message.reply_text(
            "Напиши текстом, как именно нужно оживить это фото (движения, стиль, длительность), "
            "и я запущу генерацию видео через Runway/Luma."
        )
        return


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    doc = msg.document
    if not doc:
        return
    mime = doc.mime_type or ""
    file_name = doc.file_name or ""
    data, _ = await download_file_bytes(context.bot, doc.file_id)

    user_prompt = " ".join(context.args) if context.args else ""

    if mime == "application/pdf" or file_name.lower().endswith(".pdf"):
        raw_text = await parse_pdf_bytes(data)
    elif file_name.lower().endswith(".docx"):
        raw_text = await parse_docx_bytes(data)
    elif file_name.lower().endswith(".epub"):
        raw_text = await parse_epub_bytes(data)
    elif file_name.lower().endswith(".fb2") or file_name.lower().endswith(".fb2.zip"):
        raw_text = await parse_fb2_bytes(data)
    elif mime.startswith("text/") or file_name.lower().endswith(".txt"):
        raw_text = data.decode("utf-8", errors="ignore")[:20000]
    else:
        await msg.reply_text(
            "Пока я умею работать с PDF, DOCX, EPUB, FB2 и TXT. Этот формат не поддерживается."
        )
        return

    with contextlib.suppress(Exception):
        await msg.chat.send_action(ChatAction.TYPING)
    summary = await summarize_long_text(user_prompt, raw_text)
    await msg.reply_text(summary)
    await maybe_tts_reply(update, context, summary)


async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.effective_message.reply_text(
            "Напиши описание после /img, например:\n"
            "/img кот на серфе в стиле неонового киберпанка"
        )
        return
    await handle_openai_image_from_text(update, context, prompt)


async def cmd_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.effective_message.reply_text(
            "Опиши, какое видео нужно, например:\n"
            "/video динамичный ролик про виллу на Самуи, 5 секунд, вертикальный формат"
        )
        return
    engine = "runway" if RUNWAY_API_KEY else "luma"
    await start_video_generation(update, context, engine, prompt)


# ───────── Запуск бота ─────────

def main() -> None:
    # используем уже созданный выше глобальный app
    global app

    if USE_WEBHOOK:
        if not RENDER_EXTERNAL_URL:
            log.error("WEBHOOK режим включён, но RENDER_EXTERNAL_URL не задан")
            raise RuntimeError("RENDER_EXTERNAL_URL is required for webhook mode")

        log.info(
            "Starting via webhook on port %s, path /tg, url=%s/tg",
            PORT,
            RENDER_EXTERNAL_URL,
        )

        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="tg",
            webhook_url=f"{RENDER_EXTERNAL_URL}/tg",
            secret_token=WEBHOOK_SECRET or None,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    else:
        log.info("Starting via polling (no RENDER_EXTERNAL_URL)")
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


if __name__ == "__main__":
    main()
