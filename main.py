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
- 📲 Кнопка «⭐ Подписка · Помощь» всегда открывает тарифы, а не уходит в чат
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

# Цены/лимиты
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
UNLIM_USERNAMES = set(s.strip().lstrip("@").lower() for s in (os.getenv("UNLIM_USERNAMES","") or "").split(",") if s.strip())
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
    if FORCE_OWNER_UNLIM and OWNER_ID and uid == OWNER_ID: return True
    if uid in UNLIM_USER_IDS: return True
    if uname and uname.lower().lstrip("@") in UNLIM_USERNAMES: return True
    return False

def _ascii_label(s: str|None) -> str:
    s = (s or "Item").strip()
    try: s.encode("ascii"); return s[:32]
    except Exception: return "Item"

# ───── OpenAI клиенты ─────
default_headers = {}
if OPENROUTER_SITE_URL: default_headers["HTTP-Referer"] = OPENROUTER_SITE_URL
if OPENROUTER_APP_NAME: default_headers["X-Title"] = OPENROUTER_APP_NAME
_auto_base = OPENAI_BASE_URL
if not _auto_base and (OPENAI_API_KEY.startswith("sk-or-") or "openrouter" in (OPENAI_BASE_URL or "").lower()):
    _auto_base = "https://openrouter.ai/api/v1"
    log.info("OpenRouter base selected for text LLM.")

try:
    oai_llm = OpenAI(api_key=OPENAI_API_KEY, base_url=_auto_base or None, default_headers=default_headers or None)
except TypeError:
    oai_llm = OpenAI(api_key=OPENAI_API_KEY, base_url=_auto_base or None)

oai_img = OpenAI(api_key=OPENAI_IMAGE_KEY, base_url=IMAGES_BASE_URL)
from openai import OpenAI as _OpenAI_STT
def _oai_stt_client(): return _OpenAI_STT(api_key=OPENAI_STT_KEY, base_url=OPENAI_STT_BASE_URL)

# ───── База данных ─────
def db_init():
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER PRIMARY KEY, until_ts INTEGER NOT NULL, tier TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS usage_daily (
        user_id INTEGER, ymd TEXT,
        text_count INTEGER DEFAULT 0,
        luma_usd REAL DEFAULT 0.0, runway_usd REAL DEFAULT 0.0, img_usd REAL DEFAULT 0.0,
        PRIMARY KEY(user_id, ymd))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS wallet (
        user_id INTEGER PRIMARY KEY,
        luma_usd REAL DEFAULT 0.0, runway_usd REAL DEFAULT 0.0, img_usd REAL DEFAULT 0.0, usd REAL DEFAULT 0.0)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)""")
    # миграции
    try: cur.execute("ALTER TABLE wallet ADD COLUMN usd REAL DEFAULT 0.0")
    except Exception: pass
    try: cur.execute("ALTER TABLE subscriptions ADD COLUMN tier TEXT")
    except Exception: pass
    con.commit(); con.close()

def kv_get(key: str, default: str|None=None) -> str|None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT value FROM kv WHERE key=?", (key,))
    row = cur.fetchone(); con.close()
    return (row[0] if row else default)

def kv_set(key: str, value: str):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?,?)", (key, value))
    con.commit(); con.close()

def activate_subscription(uid: int, months: int=1):
    now  = _utcnow()
    until= now + timedelta(days=30*months)
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT until_ts FROM subscriptions WHERE user_id=?", (uid,))
    row = cur.fetchone()
    if row and row[0] and row[0] > int(now.timestamp()):
        current_until = datetime.fromtimestamp(row[0], tz=timezone.utc)
        until = current_until + timedelta(days=30*months)
    cur.execute("""INSERT INTO subscriptions(user_id, until_ts) VALUES(?,?)
                   ON CONFLICT(user_id) DO UPDATE SET until_ts=excluded.until_ts""", (uid, int(until.timestamp())))
    con.commit(); con.close()
    return until

def set_subscription_tier(uid: int, tier: str):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO subscriptions(user_id, until_ts, tier) VALUES (?,?,?)", (uid, int(_utcnow().timestamp()), tier))
    cur.execute("UPDATE subscriptions SET tier=? WHERE user_id=?", (tier, uid))
    con.commit(); con.close()

def activate_subscription_with_tier(uid: int, tier: str, months: int):
    until = activate_subscription(uid, months)
    set_subscription_tier(uid, tier)
    return until

def get_subscription_until(uid: int):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT until_ts FROM subscriptions WHERE user_id=?", (uid,))
    row = cur.fetchone(); con.close()
    return None if not row else datetime.fromtimestamp(row[0], tz=timezone.utc)

def get_subscription_tier(uid: int) -> str:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT until_ts, tier FROM subscriptions WHERE user_id=?", (uid,))
    row = cur.fetchone(); con.close()
    if not row: return "free"
    until_ts, tier = row[0], (row[1] or "pro")
    if until_ts and datetime.fromtimestamp(until_ts, tz=timezone.utc) > _utcnow(): return tier.lower()
    return "free"

def _usage_row(uid: int, ymd: str|None=None) -> dict:
    ymd = ymd or _today_ymd()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO usage_daily(user_id, ymd) VALUES(?,?)", (uid, ymd))
    con.commit()
    cur.execute("SELECT text_count, luma_usd, runway_usd, img_usd FROM usage_daily WHERE user_id=? AND ymd=?", (uid, ymd))
    row = cur.fetchone(); con.close()
    return {"text_count": row[0], "luma_usd": row[1], "runway_usd": row[2], "img_usd": row[3]}

def _usage_update(uid: int, **delta):
    ymd = _today_ymd()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    r = _usage_row(uid, ymd)
    cur.execute("""UPDATE usage_daily SET text_count=?, luma_usd=?, runway_usd=?, img_usd=? WHERE user_id=? AND ymd=?""",
                (r["text_count"] + delta.get("text_count",0),
                 r["luma_usd"] + delta.get("luma_usd",0.0),
                 r["runway_usd"] + delta.get("runway_usd",0.0),
                 r["img_usd"] + delta.get("img_usd",0.0), uid, ymd))
    con.commit(); con.close()

def _wallet_get(uid: int) -> dict:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES(?)", (uid,))
    con.commit()
    cur.execute("SELECT luma_usd, runway_usd, img_usd, usd FROM wallet WHERE user_id=?", (uid,))
    row = cur.fetchone(); con.close()
    return {"luma_usd": row[0], "runway_usd": row[1], "img_usd": row[2], "usd": row[3]}

def _wallet_total_get(uid: int) -> float:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES(?)", (uid,))
    con.commit()
    cur.execute("SELECT usd FROM wallet WHERE user_id=?", (uid,))
    row = cur.fetchone(); con.close()
    return float(row[0] if row and row[0] is not None else 0.0)

def _wallet_total_add(uid: int, usd: float):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("UPDATE wallet SET usd=COALESCE(usd,0)+? WHERE user_id=?", (float(usd), uid))
    con.commit(); con.close()

def _wallet_total_take(uid: int, usd: float) -> bool:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT usd FROM wallet WHERE user_id=?", (uid,))
    row = cur.fetchone()
    bal = float(row[0] if row and row[0] is not None else 0.0)
    if bal + 1e-9 < usd:
        con.close(); return False
    cur.execute("UPDATE wallet SET usd=usd-? WHERE user_id=?", (float(usd), uid))
    con.commit(); con.close()
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
    lim = _limits_for(uid); row = _usage_row(uid)
    left = max(0, lim["text_per_day"] - row["text_count"])
    if left <= 0: return False, 0, lim["tier"]
    _usage_update(uid, text_count=1)
    return True, left-1, lim["tier"]

def _calc_oneoff_price_rub(engine: str, usd_cost: float) -> int:
    markup = ONEOFF_MARKUP_RUNWAY if engine=="runway" else ONEOFF_MARKUP_DEFAULT
    rub = usd_cost * (1.0 + markup) * USD_RUB
    val = int(rub + 0.999)
    return max(MIN_RUB_FOR_INVOICE, val)

def _can_spend_or_offer(uid: int, uname: str|None, engine: str, est_cost_usd: float) -> tuple[bool,str]:
    if is_unlimited(uid, uname):
        _usage_update(uid, **({f"{engine}_usd": est_cost_usd} if engine in ("luma","runway","img") else {}))
        return True, ""
    if engine not in ("luma","runway","img"): return True, ""
    lim = _limits_for(uid); row = _usage_row(uid)
    spent = row[f"{engine}_usd"]; budget = lim[f"{engine}_budget_usd"]
    if spent + est_cost_usd <= budget + 1e-9:
        _usage_update(uid, **{f"{engine}_usd": est_cost_usd})
        return True, ""
    need = max(0.0, spent + est_cost_usd - budget)
    if need > 0:
        if _wallet_total_take(uid, need):
            _usage_update(uid, **{f"{engine}_usd": est_cost_usd})
            return True, ""
        if lim["tier"] == "free": return False, "ASK_SUBSCRIBE"
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
    if not user_text: return "Пустой запрос."
    messages = [{"role":"system","content":SYSTEM_PROMPT}]
    if web_ctx: messages.append({"role":"system","content":f"Контекст веб-поиска:\n{web_ctx}"})
    messages.append({"role":"user","content":user_text})
    last_err = None
    for attempt in range(3):
        try:
            resp = oai_llm.chat.completions.create(model=OPENAI_MODEL, messages=messages, temperature=0.6)
            txt = (resp.choices[0].message.content or "").strip()
            if txt: return txt
        except Exception as e:
            last_err = e; log.warning("LLM attempt %d failed: %s", attempt+1, e)
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
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS user_prefs (user_id INTEGER PRIMARY KEY, tts_on INTEGER DEFAULT 0, lang TEXT)""")
    con.commit(); con.close()

def _tts_get(uid: int) -> bool:
    try: _db_init_prefs()
    except Exception: pass
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO user_prefs(user_id, tts_on) VALUES (?,0)", (uid,))
    con.commit()
    cur.execute("SELECT tts_on FROM user_prefs WHERE user_id=?", (uid,))
    row = cur.fetchone(); con.close()
    return bool(row and row[0])

def _tts_set(uid: int, on: bool):
    try: _db_init_prefs()
    except Exception: pass
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO user_prefs(user_id, tts_on) VALUES (?,?)", (uid, 1 if on else 0))
    cur.execute("UPDATE user_prefs SET tts_on=? WHERE user_id=?", (1 if on else 0, uid))
    con.commit(); con.close()

# ───── Надёжный TTS REST → OGG ─────
def _tts_bytes_sync(text: str) -> bytes|None:
    try:
        if not OPENAI_TTS_KEY: return None
        if OPENAI_TTS_KEY.startswith("sk-or-"):
            log.error("OPENAI_TTS_KEY похож на OpenRouter — нужен реальный OpenAI ключ.")
            return None
        url = f"{OPENAI_TTS_BASE_URL}/audio/speech"
        headers = {"Authorization": f"Bearer {OPENAI_TTS_KEY}", "Content-Type": "application/json"}
        payload = {"model": OPENAI_TTS_MODEL, "voice": OPENAI_TTS_VOICE, "input": text, "format": "ogg"}
        r = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        r.raise_for_status()
        return r.content if r.content else None
    except Exception as e:
        log.exception("TTS error: %s", e)
        return None

async def maybe_tts_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    uid = update.effective_user.id
    if not _tts_get(uid): return
    text = (text or "").strip()
    if not text: return
    if len(text) > TTS_MAX_CHARS:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text(f"🔇 Озвучка пропущена (>{TTS_MAX_CHARS} симв.).")
        return
    try:
        with contextlib.suppress(Exception):
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VOICE)
        audio = await asyncio.to_thread(_tts_bytes_sync, text)
        if not audio:
            with contextlib.suppress(Exception):
                await update.effective_message.reply_text("🔇 Не удалось синтезировать голос.")
            return
        bio = BytesIO(audio); bio.seek(0); bio.name = "say.ogg"
        await update.effective_message.reply_voice(voice=InputFile(bio), caption=text)
    except Exception as e:
        log.exception("maybe_tts_reply error: %s", e)

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, True)
    await update.effective_message.reply_text(f"🔊 Озвучка включена. Лимит {TTS_MAX_CHARS} символов.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, False)
    await update.effective_message.reply_text("🔈 Озвучка выключена.")

# ───── STT ─────
def _mime_from_filename(fn: str) -> str:
    fnl = (fn or "").lower()
    if fnl.endswith((".ogg",".oga")): return "audio/ogg"
    if fnl.endswith(".mp3"): return "audio/mpeg"
    if fnl.endswith((".m4a",".mp4")): return "audio/mp4"
    if fnl.endswith(".wav"): return "audio/wav"
    if fnl.endswith(".webm"): return "audio/webm"
    return "application/octet-stream"

async def transcribe_audio(buf: BytesIO, filename_hint: str="audio.ogg") -> str:
    data = buf.getvalue()
    if DEEPGRAM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                params = {"model":"nova-2","language":"ru","smart_format":"true","punctuate":"true"}
                headers= {"Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": _mime_from_filename(filename_hint)}
                r = await client.post("https://api.deepgram.com/v1/listen", params=params, headers=headers, content=data)
                r.raise_for_status()
                dg = r.json()
                text = (dg.get("results",{}).get("channels",[{}])[0].get("alternatives",[{}])[0].get("transcript","") or "").strip()
                if text: return text
        except Exception as e:
            log.exception("Deepgram STT error: %s", e)
    try:
        bio = BytesIO(data); bio.seek(0); setattr(bio,"name",filename_hint)
        tr = _oai_stt_client().audio.transcriptions.create(model=OPENAI_STT_MODEL, file=bio)
        return (tr.text or "").strip()
    except Exception as e:
        log.exception("Whisper STT error: %s", e)
    return ""

# Голосовые хендлеры
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    media = msg.voice or msg.audio
    if not media:
        await msg.reply_text("Голос не найден.")
        return
    try:
        with contextlib.suppress(Exception):
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        tg_file = await context.bot.get_file(media.file_id)
        bio = BytesIO(); await tg_file.download_to_memory(out=bio)
        raw = bio.getvalue()
        mime = (getattr(media,"mime_type","") or "").lower()
        fn = "voice.ogg" if "ogg" in mime or "opus" in mime else ("voice.webm" if "webm" in mime else ("voice.mp3" if "mp3" in mime or "mpeg" in mime else "voice.wav"))
    except Exception as e:
        log.exception("TG download error: %s", e)
        await msg.reply_text("Не удалось скачать голосовое.")
        return
    text = await transcribe_audio(BytesIO(raw), fn)
    if not text:
        await msg.reply_text("Не удалось распознать речь.")
        return
    with contextlib.suppress(Exception):
        await msg.reply_text(f"🗣️ Распознал: {text}")
    answer = await ask_openai_text(text)
    await msg.reply_text(answer)
    await maybe_tts_reply(update, context, answer)

# ───── Извлечение текста из документов ─────
def _safe_decode_txt(b: bytes) -> str:
    for enc in ("utf-8","cp1251","latin-1"):
        try: return b.decode(enc)
        except Exception: continue
    return b.decode("utf-8", errors="ignore")

def _extract_pdf_text(data: bytes) -> str:
    try:
        import PyPDF2
        rd = PyPDF2.PdfReader(BytesIO(data))
        parts = []
        for p in rd.pages:
            try: parts.append(p.extract_text() or "")
            except Exception: continue
        t = "\n".join(parts).strip()
        if t: return t
    except Exception: pass
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract_text
        return (pdfminer_extract_text(BytesIO(data)) or "").strip()
    except Exception: pass
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        txt = []
        for page in doc:
            try: txt.append(page.get_text("text"))
            except Exception: continue
        return "\n".join(txt)
    except Exception: pass
    return ""

def _extract_epub_text(data: bytes) -> str:
    try:
        from ebooklib import epub
        from bs4 import BeautifulSoup
        book = epub.read_epub(BytesIO(data))
        chunks = []
        for item in book.get_items():
            if item.get_type() == 9:
                try:
                    soup = BeautifulSoup(item.get_content(), "html.parser")
                    txt = soup.get_text(separator=" ", strip=True)
                    if txt: chunks.append(txt)
                except Exception: continue
        return "\n".join(chunks).strip()
    except Exception:
        return ""

def _extract_docx_text(data: bytes) -> str:
    try:
        import docx
        doc = docx.Document(BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs).strip()
    except Exception:
        return ""

def _extract_fb2_text(data: bytes) -> str:
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(data)
        texts = []
        for elem in root.iter():
            if elem.text and elem.text.strip(): texts.append(elem.text.strip())
        return " ".join(texts).strip()
    except Exception:
        return ""

def extract_text_from_document(data: bytes, filename: str) -> tuple[str,str]:
    name = (filename or "").lower()
    if name.endswith(".pdf"):  return _extract_pdf_text(data),  "PDF"
    if name.endswith(".epub"): return _extract_epub_text(data), "EPUB"
    if name.endswith(".docx"): return _extract_docx_text(data), "DOCX"
    if name.endswith(".fb2"):  return _extract_fb2_text(data),  "FB2"
    if name.endswith(".txt"):  return _safe_decode_txt(data),    "TXT"
    if name.endswith((".mobi",".azw",".azw3")): return "", "MOBI/AZW"
    decoded = _safe_decode_txt(data)
    return (decoded if decoded else "", "UNKNOWN")

# ───── Суммаризация длинных текстов ─────
async def _summarize_chunk(text: str, query: str|None=None) -> str:
    prefix = "Суммируй кратко по пунктам на русском:\n"
    if query:
        prefix = f"Суммируй с учётом цели: {query}\nДай тезисы/факты/цифры.\n"
    return await ask_openai_text(prefix + text)

async def summarize_long_text(full_text: str, query: str|None=None) -> str:
    max_chunk = 8000
    t = full_text.strip()
    if len(t) <= max_chunk:
        return await _summarize_chunk(t, query=query)
    parts, i = [], 0
    while i < len(t) and len(parts) < 8:
        parts.append(t[i:i+max_chunk]); i += max_chunk
    partials = [await _summarize_chunk(p, query=query) for p in parts]
    combined = "\n\n".join(f"- Фрагмент {idx+1}:\n{s}" for idx, s in enumerate(partials))
    return await ask_openai_text("Объедини тезисы в 5–10 главных пунктов + цифры/сроки + вывод.\n\n" + combined)

async def on_doc_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document: return
        doc = update.message.document
        tgf = await doc.get_file()
        data = await tgf.download_as_bytearray()
        text, kind = extract_text_from_document(bytes(data), doc.file_name or "file")
        if not text.strip():
            await update.effective_message.reply_text(f"Не удалось извлечь текст из {kind}.")
            return
        goal = (update.message.caption or "").strip() or None
        await update.effective_message.reply_text(f"📄 Извлекаю текст ({kind}), готовлю конспект…")
        summary = await summarize_long_text(text, query=goal)
        await update.effective_message.reply_text(summary or "Готово.")
        await maybe_tts_reply(update, context, (summary or "")[:TTS_MAX_CHARS])
    except Exception as e:
        log.exception("on_doc_analyze error: %s", e)

# ───── OpenAI Images ─────
async def _do_img_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
        b64 = resp.data[0].b64_json
        img_bytes = base64.b64decode(b64)
        await update.effective_message.reply_photo(photo=img_bytes, caption=f"Готово ✅\nЗапрос: {prompt}")
    except Exception as e:
        log.exception("IMG gen error: %s", e)
        await update.effective_message.reply_text("Не удалось создать изображение.")

# ───── UI тексты ─────
START_TEXT = (
    "Привет! Я GPT-5 ProBot — мультирежимный бот для учёбы, работы и развлечений.\n\n"
    "• 💬 GPT: вопросы, идеи, планы\n"
    "• 👁 Фото/визион: анализ картинок и текст на них\n"
    "• 📚 Конспекты из PDF/EPUB/DOCX/FB2/TXT\n"
    "• 🖼 /img — генерация изображений\n"
    "• 🎬 Видео Luma / 🎥 Runway (короткие клипы)\n"
    "• 🗣 STT + 🎙 TTS (/voice_on /voice_off)\n"
    "• 💳 ЮKassa / 💠 CryptoBot, единый USD-кошелёк\n\n"
    "Выберите режим на клавиатуре или просто напишите запрос."
)

HELP_TEXT = (
    "Подсказки:\n"
    "• /img «кот в очках, киберпанк» — сгенерирую картинку\n"
    "• «сделай видео … 9 секунд 9:16» — предложу Luma/Runway\n"
    "• Пришлите PDF/EPUB/DOCX/FB2/TXT — извлеку текст и сделаю конспект (цель в подписи)\n"
    "• Озвучка: /voice_on /voice_off (OGG/Opus)\n"
    "• «🧾 Баланс» — единый кошелёк. /plans — цены"
)

EXAMPLES_TEXT = (
    "Примеры:\n\n"
    "🎓 Учёба: объясни метод Тейлора с 2 примерами; мини-квиз на 10 вопросов; конспект главы из PDF\n"
    "💼 Работа: письмо клиенту; бриф на интерьер; ToDo-план на 2 недели; сводка документов\n"
    "🔥 Развлечения: удалить/заменить фон на фото, outpaint; короткое видео для Reels"
)

# ───── Горизонтальное меню «Движки» (твоя правка) ─────
def engines_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💬 GPT",        callback_data="engine:gpt"),
            InlineKeyboardButton("🖼 Images",     callback_data="engine:images"),
            InlineKeyboardButton("🎬 Luma",       callback_data="engine:luma"),
        ],
        [
            InlineKeyboardButton("🎥 Runway",     callback_data="engine:runway"),
            InlineKeyboardButton("🎨 Midjourney", callback_data="engine:midjourney"),
            InlineKeyboardButton("🗣 STT/TTS",    callback_data="engine:stt_tts"),
        ],
    ])

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Учёба"), KeyboardButton("Работа"), KeyboardButton("Развлечения")],
            [KeyboardButton("🧠 Движки"), KeyboardButton("⭐ Подписка · Помощь"), KeyboardButton("🧾 Баланс")],
        ],
        resize_keyboard=True, one_time_keyboard=False, selective=False,
        input_field_placeholder="Выберите режим или напишите запрос…"
    )

main_kb = main_keyboard()

# Режимы и подрежимы
def _mode_set(uid: int, mode: str): kv_set(f"mode:{uid}", mode)
def _mode_get(uid: int) -> str: return kv_get(f"mode:{uid}", "none") or "none"
def _mode_track_set(uid: int, track: str): kv_set(f"mode_track:{uid}", track)
def _mode_track_get(uid: int) -> str: return kv_get(f"mode_track:{uid}", "") or ""

def _school_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Объяснение", callback_data="school:explain"),
         InlineKeyboardButton("🧮 Задачи", callback_data="school:tasks")],
        [InlineKeyboardButton("✍️ Эссе/доклад", callback_data="school:essay"),
         InlineKeyboardButton("📝 Квиз", callback_data="school:quiz")],
    ])

def _work_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📧 Письмо/док", callback_data="work:doc"),
         InlineKeyboardButton("📊 Аналитика", callback_data="work:report")],
        [InlineKeyboardButton("🗂 План/ToDo", callback_data="work:plan"),
         InlineKeyboardButton("💡 Идеи/бриф", callback_data="work:idea")],
    ])

def _fun_quick_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Оживить фото", callback_data="fun:revive"),
         InlineKeyboardButton("Клип (Luma/Runway)", callback_data="fun:clip")],
        [InlineKeyboardButton("Сделать /img", callback_data="fun:img"),
         InlineKeyboardButton("Раскадровка", callback_data="fun:storyboard")],
    ])

def _fun_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 Фото-мастерская", callback_data="fun:photo"),
         InlineKeyboardButton("🎬 Видео-идеи", callback_data="fun:video")],
        [InlineKeyboardButton("🎲 Квизы", callback_data="fun:quiz"),
         InlineKeyboardButton("😆 Мемы", callback_data="fun:meme")],
    ])

# Capability Q&A (позитивные ответы «можешь ли с фото…» — твоя правка)
_CAP_PDF   = re.compile(r"(pdf|документ(ы)?|файл(ы)?)", re.I)
_CAP_EBOOK = re.compile(r"(ebook|электронн|epub|fb2|docx|txt|mobi|azw)", re.I)
_CAP_AUDIO = re.compile(r"(аудио|voice|ogg|mp3|m4a|wav|webm)", re.I)
_CAP_IMAGE = re.compile(r"(изображен|картинк|фото|image|picture|img)", re.I)
_CAP_VIDEO = re.compile(r"(видео|ролик|shorts?|reels?|clip)", re.I)
def capability_answer(text: str) -> str|None:
    tl = (text or "").strip().lower()
    if not tl: return None
    if (_CAP_IMAGE.search(tl) and re.search(r"(мож(ешь|ете)|умеешь|дела(ть)?|генерир|оживи|замени|удали|дорисуй)", tl)):
        return ("Да, работаю с фото: анализ, удаление/замена фона, добавление/удаление объектов, outpaint, «оживление» "
                "и раскадровка. Пришлите изображение и напишите, что сделать.")
    if (_CAP_PDF.search(tl) or _CAP_EBOOK.search(tl)):
        if re.search(r"(читать|анализ|распозна|конспект|суммар)", tl):
            return "Да. Пришли файл — извлеку текст и сделаю конспект/резюме под вашу цель."
    if (_CAP_AUDIO.search(tl)):
        if re.search(r"(распозна|транскриб|понима)", tl):
            return "Да. Пришли voice/audio — распознаю речь и отвечу по сути, могу сделать конспект или Q&A."
    if (_CAP_VIDEO.search(tl)):
        if re.search(r"(сдела(ть)?|генерир|созда(ть)?)", tl):
            return "Да. Напишите: «сделай видео … 9 секунд 9:16» — предложу Luma/Runway."
    return None

# Детект намерений «сделай видео/картинку»
_CREATE_CMD = r"(сдела(й|йте)|созда(й|йте)|сгенериру(й|йте)|нарису(й|йте)|render|generate|create|make)"
_IMG_WORDS  = r"(картин\w+|изображен\w+|фото\w*|рисунк\w+|image|picture|img\b|logo|banner|poster)"
_VID_WORDS  = r"(видео|ролик\w*|анимаци\w*|shorts?|reels?|clip|video|vid\b)"

def detect_media_intent(text: str):
    if not text: return (None, "")
    t = text.strip(); tl = t.lower()
    if "?" in tl and re.search(r"(мож(ешь|ете)|умеешь).*(фото|изображен|видео)", tl):
        return (None, "")
    m = re.search(r"^" + _CREATE_CMD + r"\s+видео", tl, re.I)
    if m: return ("video", t[m.end():].strip(" :,-"))
    m = re.search(r"^" + _CREATE_CMD + r"\s+(?:картин|изображен|фото|рисунк)", tl, re.I)
    if m: return ("image", t[m.end():].strip(" :,-"))
    if re.search(_CREATE_CMD, tl, re.I):
        if re.search(_VID_WORDS, tl, re.I):
            clean = re.sub(_VID_WORDS, "", tl, flags=re.I)
            clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
            return ("video", clean.strip(" :,-"))
        if re.search(_IMG_WORDS, tl, re.I):
            clean = re.sub(_IMG_WORDS, "", tl, flags=re.I)
            clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
            return ("image", clean.strip(" :,-"))
    m = re.match(r"^(img|image|picture)\s*[:\-]\s*(.+)$", tl)
    if m: return ("image", t[m.end(1)+1:].strip())
    m = re.match(r"^(video|vid|reels?|shorts?)\s*[:\-]\s*(.+)$", tl)
    if m: return ("video", t[m.end(1)+1:].strip())
    return (None, "")

# ───── Misc helpers ─────
def sniff_image_mime(data: bytes) -> str:
    if not data or len(data) < 12: return "application/octet-stream"
    b = data[:12]
    if b.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if b[:3] == b"\xff\xd8\xff":          return "image/jpeg"
    if b[:4] == b"RIFF" and b[8:12]==b"WEBP": return "image/webp"
    return "application/octet-stream"

_ASPECTS = {"9:16","16:9","1:1","4:5","3:4","4:3"}
def parse_video_opts(text: str) -> tuple[int,str]:
    tl = (text or "").lower()
    m  = re.search(r"(\d+)\s*(?:сек|с)\b", tl)
    duration = max(3, min(20, int(m.group(1)) if m else LUMA_DURATION_S))
    asp = None
    for a in _ASPECTS:
        if a in tl: asp = a; break
    aspect = asp or (LUMA_ASPECT if LUMA_ASPECT in _ASPECTS else "16:9")
    return duration, aspect

# ───── Luma / Runway ─────
_LUMA_ACTIVE_BASE = None
async def _pick_luma_base(client: httpx.AsyncClient) -> str:
    global _LUMA_ACTIVE_BASE
    candidates = []
    if _LUMA_ACTIVE_BASE: candidates.append(_LUMA_ACTIVE_BASE)
    if LUMA_BASE_URL and LUMA_BASE_URL not in candidates: candidates.append(LUMA_BASE_URL)
    for b in LUMA_FALLBACKS:
        if b not in candidates: candidates.append(b)
    for base in candidates:
        try:
            url = f"{base}{LUMA_CREATE_PATH}"
            r = await client.options(url, timeout=10.0)
            if r.status_code in (200,201,202,204,400,401,403,404,405):
                _LUMA_ACTIVE_BASE = base
                if base != LUMA_BASE_URL: log.info("Luma base switched → %s", base)
                return base
        except Exception as e:
            log.warning("Luma base probe failed for %s: %s", base, e)
    return LUMA_BASE_URL

async def _run_luma_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration_s: int, aspect: str):
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            base = await _pick_luma_base(client)
            create_url = f"{base}{LUMA_CREATE_PATH}"
            headers = {"Authorization": f"Bearer {LUMA_API_KEY}", "Accept": "application/json"}
            payload = {"model": LUMA_MODEL, "prompt": prompt, "duration": f"{duration_s}s", "aspect_ratio": aspect}
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code >= 400:
                await update.effective_message.reply_text(f"⚠️ Luma отклонила задачу ({r.status_code}).")
                return
            rid = (r.json() or {}).get("id") or (r.json() or {}).get("generation_id")
            if not rid:
                await update.effective_message.reply_text("⚠️ Luma не вернула id.")
                return
            await update.effective_message.reply_text("⏳ Luma рендерит… Сообщу, когда готово.")
            status_url = f"{base}{LUMA_STATUS_PATH}".format(id=rid)
            started = time.time()
            while True:
                rs = await client.get(status_url, headers=headers)
                js = {}
                try: js = rs.json()
                except Exception: pass
                st = (js.get("state") or js.get("status") or "").lower()
                if st in ("completed","succeeded","finished","ready"):
                    url = js.get("assets", [{}])[0].get("url") or js.get("output_url")
                    if not url:
                        await update.effective_message.reply_text("⚠️ Готово, но нет ссылки.")
                        return
                    try:
                        v = await client.get(url, timeout=120.0)
                        v.raise_for_status()
                        bio = BytesIO(v.content); bio.name = "luma.mp4"
                        await update.effective_message.reply_video(InputFile(bio), caption="🎬 Luma: готово ✅")
                    except Exception:
                        await update.effective_message.reply_text(f"🎬 Luma: готово ✅\n{url}")
                    return
                if st in ("failed","error","canceled","cancelled"):
                    await update.effective_message.reply_text("❌ Luma: ошибка рендера.")
                    return
                if time.time() - started > LUMA_MAX_WAIT_S:
                    await update.effective_message.reply_text("⌛ Luma: время ожидания вышло.")
                    return
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("Luma error: %s", e)
        await update.effective_message.reply_text("❌ Luma: не удалось.")

async def _run_runway_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration_s: int, aspect: str):
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            create_url = f"{RUNWAY_BASE_URL}{RUNWAY_CREATE_PATH}"
            headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Accept": "application/json"}
            payload = {"model": RUNWAY_MODEL, "input":{"prompt":prompt, "duration":duration_s, "ratio": aspect.replace(":", "/")}}
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code >= 400:
                await update.effective_message.reply_text(f"⚠️ Runway отклонил задачу ({r.status_code}).")
                return
            rid = (r.json() or {}).get("id") or (r.json() or {}).get("task_id")
            if not rid:
                await update.effective_message.reply_text("⚠️ Runway не вернул id.")
                return
            await update.effective_message.reply_text("⏳ Runway рендерит… Сообщу, когда готово.")
            status_url = f"{RUNWAY_BASE_URL}{RUNWAY_STATUS_PATH}".format(id=rid)
            started = time.time()
            while True:
                rs = await client.get(status_url, headers=headers)
                js = {}
                try: js = rs.json()
                except Exception: pass
                st = (js.get("status") or js.get("state") or "").lower()
                if st in ("completed","succeeded","finished","ready"):
                    assets = js.get("output", {}) if isinstance(js.get("output"), dict) else (js.get("assets") or {})
                    url = (assets.get("video") if isinstance(assets, dict) else None) or js.get("video_url") or js.get("output_url")
                    if not url:
                        await update.effective_message.reply_text("⚠️ Готово, но нет ссылки.")
                        return
                    try:
                        v = await client.get(url, timeout=180.0)
                        v.raise_for_status()
                        bio = BytesIO(v.content); bio.name = "runway.mp4"
                        await update.effective_message.reply_video(InputFile(bio), caption="🎥 Runway: готово ✅")
                    except Exception:
                        await update.effective_message.reply_text(f"🎥 Runway: готово ✅\n{url}")
                    return
                if st in ("failed","error","canceled","cancelled"):
                    await update.effective_message.reply_text("❌ Runway: ошибка рендера.")
                    return
                if time.time() - started > RUNWAY_MAX_WAIT_S:
                    await update.effective_message.reply_text("⌛ Runway: время ожидания вышло.")
                    return
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("Runway error: %s", e)
        await update.effective_message.reply_text("❌ Runway: не удалось.")

# ───── Кнопки быстрых действий по фото ─────
def photo_quick_actions_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧼 RemoveBG",  callback_data="pedit:removebg"),
         InlineKeyboardButton("🖼 ReplaceBG", callback_data="pedit:replacebg")],
        [InlineKeyboardButton("🧭 Outpaint",   callback_data="pedit:outpaint"),
         InlineKeyboardButton("📽 Storyboard", callback_data="pedit:story")],
        [InlineKeyboardButton("👁 Vision",     callback_data="pedit:vision")],
    ])

_photo_cache: dict[int, bytes] = {}
def _cache_photo(uid: int, data: bytes):
    try: _photo_cache[uid] = data
    except Exception: pass
def _get_cached_photo(uid: int) -> bytes|None: return _photo_cache.get(uid)

async def _pedit_removebg(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    if rembg_remove is None:
        await update.effective_message.reply_text("rembg не установлен (rembg, onnxruntime).")
        return
    try:
        out = rembg_remove(img_bytes)
        bio = BytesIO(out); bio.name = "no_bg.png"
        await update.effective_message.reply_document(InputFile(bio), caption="Фон удалён ✅")
    except Exception as e:
        log.exception("removebg error: %s", e)
        await update.effective_message.reply_text("Не удалось удалить фон.")

async def _pedit_replacebg(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    if Image is None:
        await update.effective_message.reply_text("Pillow не установлен.")
        return
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGBA")
        bg = im.convert("RGB").filter(ImageFilter.GaussianBlur(radius=22)) if ImageFilter else im.convert("RGB")
        bio = BytesIO(); bg.save(bio, format="JPEG", quality=92); bio.seek(0); bio.name = "bg_blur.jpg"
        await update.effective_message.reply_photo(InputFile(bio), caption="Заменил фон на размытый вариант.")
    except Exception as e:
        log.exception("replacebg error: %s", e)
        await update.effective_message.reply_text("Не удалось заменить фон.")

async def _pedit_outpaint(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    if Image is None:
        await update.effective_message.reply_text("Pillow не установлен.")
        return
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGB")
        pad = max(64, min(256, max(im.size)//6))
        big = Image.new("RGB", (im.width + 2*pad, im.height + 2*pad))
        bg = im.resize(big.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(radius=24)) if ImageFilter else im.resize(big.size)
        big.paste(bg, (0,0)); big.paste(im, (pad,pad))
        bio = BytesIO(); big.save(bio, format="JPEG", quality=92); bio.seek(0); bio.name = "outpaint.jpg"
        await update.effective_message.reply_photo(InputFile(bio), caption="Простой outpaint: расширил полотно.")
    except Exception as e:
        log.exception("outpaint error: %s", e)
        await update.effective_message.reply_text("Не удалось сделать outpaint.")

async def _pedit_storyboard(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    try:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        desc = await ask_openai_vision("Опиши ключевые элементы кадра кратко.", b64, sniff_image_mime(img_bytes))
        plan = await ask_openai_text(
            "Сделай раскадровку на 6 кадров (6–10 сек ролик). "
            "Каждый кадр — 1 строка: действие/ракурс/свет. Основа:\n" + (desc or "")
        )
        await update.effective_message.reply_text("Раскадровка:\n" + plan)
    except Exception as e:
        log.exception("storyboard error: %s", e)
        await update.effective_message.reply_text("Не удалось построить раскадровку.")

# ───── WebApp (витрина тарифов/пополнений) ─────
async def on_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        wad = update.effective_message.web_app_data
        raw = wad.data if wad else ""
        data = {}
        try: data = json.loads(raw)
        except Exception:
            for part in (raw or "").split("&"):
                if "=" in part:
                    k,v = part.split("=",1); data[k]=v
        typ = (data.get("type") or data.get("action") or "").lower()
        if typ in ("subscribe","buy","buy_sub","sub"):
            tier = (data.get("tier") or "pro").lower()
            months = int(data.get("months") or 1)
            desc = f"Оформление подписки {tier.upper()} на {months} мес."
            await update.effective_message.reply_text(
                f"{desc}\nВыберите способ:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить картой (ЮKassa)", callback_data=f"buyinv:{tier}:{months}")],
                    [InlineKeyboardButton("Списать с баланса (USD)",  callback_data=f"buywallet:{tier}:{months}")],
                ])
            )
            return
        if typ in ("topup_rub","rub_topup"):
            amount_rub = int(data.get("amount") or 0)
            if amount_rub < MIN_RUB_FOR_INVOICE:
                await update.effective_message.reply_text(f"Минимум: {MIN_RUB_FOR_INVOICE} ₽"); return
            await _send_invoice_rub("Пополнение баланса", "Единый кошелёк", amount_rub, "t=3", update); return
        if typ in ("topup_crypto","crypto_topup"):
            if not CRYPTO_PAY_API_TOKEN:
                await update.effective_message.reply_text("CryptoBot не настроен."); return
            usd = float(data.get("usd") or 0)
            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(usd, asset="USDT")
            if not inv_id or not pay_url:
                await update.effective_message.reply_text("Не удалось создать счёт в CryptoBot."); return
            msg = await update.effective_message.reply_text(
                f"Оплатите через CryptoBot: ≈ ${usd_amount:.2f} ({asset}).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить в CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("Проверить оплату", callback_data=f"crypto:check:{inv_id}")]
                ])
            )
            context.application.create_task(_poll_crypto_invoice(context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id, usd_amount))
            return
        await update.effective_message.reply_text("Получены данные WebApp, команда не распознана.")
    except Exception as e:
        log.exception("on_webapp_data error: %s", e)
    finally:
        with contextlib.suppress(Exception):
            if update and update.effective_chat:
                await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

# ───── Инвойсы/оплаты ─────
def _plan_rub(tier: str, term: str) -> int:
    tier = (tier or "pro").lower(); term = (term or "month").lower()
    return int(PLAN_PRICE_TABLE.get(tier, PLAN_PRICE_TABLE["pro"]).get(term, PLAN_PRICE_TABLE["pro"]["month"]))

def _plan_payload_and_amount(tier: str, months: int) -> tuple[str,int,str]:
    term = {1:"month",3:"quarter",12:"year"}.get(months,"month")
    amount = _plan_rub(tier, term)
    title  = f"Подписка {tier.upper()} ({term})"
    payload= f"sub:{tier}:{months}"
    return payload, amount, title

async def _send_invoice_rub(title: str, desc: str, amount_rub: int, payload: str, update: Update) -> bool:
    try:
        if not PROVIDER_TOKEN:
            await update.effective_message.reply_text("⚠️ ЮKassa не настроена (PROVIDER_TOKEN).")
            return False
        prices = [LabeledPrice(label=_ascii_label(title), amount=int(amount_rub)*100)]
        await update.effective_message.reply_invoice(
            title=title, description=desc[:255], payload=payload, provider_token=PROVIDER_TOKEN,
            currency=CURRENCY, prices=prices, need_email=False, need_name=False, need_phone_number=False,
            need_shipping_address=False, is_flexible=False
        )
        return True
    except Exception as e:
        log.exception("send_invoice error: %s", e)
        try: await update.effective_message.reply_text("Не удалось выставить счёт.")
        except Exception: pass
        return False

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: await update.pre_checkout_query.answer(ok=True)
    except Exception as e:
        log.exception("precheckout error: %s", e)

async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sp = update.message.successful_payment
        payload = sp.invoice_payload or ""
        rub = (sp.total_amount or 0)/100.0
        uid = update.effective_user.id
        if payload.startswith("sub:"):
            _, tier, months = payload.split(":",2); months = int(months)
            until = activate_subscription_with_tier(uid, tier, months)
            await update.effective_message.reply_text(f"✅ Подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')}.")
            return
        usd = rub / max(1e-9, USD_RUB)
        _wallet_total_add(uid, usd)
        await update.effective_message.reply_text(f"💳 Пополнение: {rub:.0f} ₽ ≈ ${usd:.2f} зачислено.")
    except Exception as e:
        log.exception("successful_payment error: %s", e)

# CryptoBot
async def _crypto_create_invoice(usd_amount: float, asset: str="USDT", description: str="") -> tuple[str|None,str|None,float,str]:
    if not CRYPTO_PAY_API_TOKEN:
        return None, None, 0.0, asset
    try:
        payload = {"asset": asset, "amount": round(float(usd_amount),2), "description": description or "Top-up"}
        headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{CRYPTO_BASE}/createInvoice", headers=headers, json=payload)
            j = r.json()
            if not j.get("ok"): return None, None, 0.0, asset
            res = j.get("result", {})
            return str(res.get("invoice_id")), res.get("pay_url"), float(res.get("amount", usd_amount)), res.get("asset") or asset
    except Exception as e:
        log.exception("crypto create error: %s", e)
        return None, None, 0.0, asset

async def _crypto_get_invoice(invoice_id: str) -> dict|None:
    if not CRYPTO_PAY_API_TOKEN: return None
    try:
        headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN}
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{CRYPTO_BASE}/getInvoices?invoice_ids={invoice_id}", headers=headers)
            j = r.json()
            if not j.get("ok"): return None
            items = (j.get("result", {}) or {}).get("items", [])
            return items[0] if items else None
    except Exception as e:
        log.exception("crypto get error: %s", e)
        return None

async def _poll_crypto_invoice(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, uid: int, invoice_id: str, usd_amount: float):
    try:
        for _ in range(120):
            inv = await _crypto_get_invoice(invoice_id)
            st = (inv or {}).get("status","").lower() if inv else ""
            if st == "paid":
                _wallet_total_add(uid, float(usd_amount))
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=f"✅ CryptoBot: платёж подтверждён. Баланс +${float(usd_amount):.2f}.")
                return
            if st in ("expired","cancelled","canceled","failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=f"❌ CryptoBot: платёж не завершён (статус: {st}).")
                return
            await asyncio.sleep(6.0)
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="⌛ CryptoBot: время ожидания вышло. Нажмите «Проверить оплату» позже.")
    except Exception as e:
        log.exception("crypto poll error: %s", e)

# ───── Тарифы/баланс/диагностика ─────
async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["⭐ Тарифы:"]
    for tier, terms in PLAN_PRICE_TABLE.items():
        lines.append(f"— {tier.upper()}: {terms['month']}₽/мес • {terms['quarter']}₽/квартал • {terms['year']}₽/год")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Купить START (1 мес)", callback_data="buy:start:1"),
         InlineKeyboardButton("Купить PRO (1 мес)",   callback_data="buy:pro:1")],
        [InlineKeyboardButton("Купить ULTIMATE (1 мес)", callback_data="buy:ultimate:1")],
        [InlineKeyboardButton("Открыть мини-витрину", web_app=WebAppInfo(url=(WEBAPP_URL or f"{PUBLIC_URL.rstrip('/')}/premium.html") + ("?src=plans&bot="+BOT_USERNAME if BOT_USERNAME else "")))]
    ])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb)

def _make_tariff_url(src: str="subscribe") -> str:
    base = (WEBAPP_URL or f"{PUBLIC_URL.rstrip('/')}/premium.html").strip()
    if src: base += ("&" if "?" in base else "?") + f"src={src}"
    if BOT_USERNAME: base += ("&" if "?" in base else "?") + f"bot={BOT_USERNAME}"
    return base

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    w = _wallet_get(uid); total = _wallet_total_get(uid)
    row = _usage_row(uid); lim = _limits_for(uid)
    msg = (
        "🧾 Кошелёк:\n"
        f"• Единый баланс: ${total:.2f}\n\n"
        "Сегодня / лимиты:\n"
        f"• Luma: ${row['luma_usd']:.2f} / ${lim['luma_budget_usd']:.2f}\n"
        f"• Runway: ${row['runway_usd']:.2f} / ${lim['runway_budget_usd']:.2f}\n"
        f"• Images: ${row['img_usd']:.2f} / ${lim['img_budget_usd']:.2f}\n"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]])
    await update.effective_message.reply_text(msg, reply_markup=kb)

async def cmd_diag_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tier = get_subscription_tier(uid); lim = _limits_for(uid); row = _usage_row(uid)
    lines = [
        f"👤 Тариф: {tier}",
        f"• Тексты сегодня: {row['text_count']} / {lim['text_per_day']}",
        f"• Luma $: {row['luma_usd']:.2f} / {lim['luma_budget_usd']:.2f}",
        f"• Runway $: {row['runway_usd']:.2f} / {lim['runway_budget_usd']:.2f}",
        f"• Images $: {row['img_usd']:.2f} / {lim['img_budget_usd']:.2f}",
    ]
    await update.effective_message.reply_text("\n".join(lines))

async def cmd_diag_stt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = []
    lines.append("🔎 STT диагностика:")
    lines.append(f"• Deepgram: {'✅ ключ найден' if DEEPGRAM_API_KEY else '❌ нет ключа'}")
    lines.append(f"• OpenAI Whisper: {'✅ активен' if OPENAI_STT_KEY else '❌ нет ключа'}")
    lines.append(f"• Модель: {OPENAI_STT_MODEL}")
    lines.append("• Поддержка форматов: ogg/mp3/m4a/wav/webm")
    await update.effective_message.reply_text("\n".join(lines))

async def cmd_diag_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key_used = (os.getenv("OPENAI_IMAGE_KEY","").strip() or OPENAI_API_KEY)
    base = IMAGES_BASE_URL
    lines = [
        "🧪 Images (OpenAI):",
        f"• KEY: {'✅' if key_used else '❌'}",
        f"• BASE_URL: {base}",
        f"• MODEL: {IMAGES_MODEL}",
    ]
    if "openrouter" in (base or "").lower():
        lines.append("⚠️ Для gpt-image-1 нужен api.openai.com, а не OpenRouter.")
    await update.effective_message.reply_text("\n".join(lines))

async def cmd_diag_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [
        "🎬 Видео-движки:",
        f"• Luma key: {'✅' if bool(LUMA_API_KEY) else '❌'} base={LUMA_BASE_URL}",
        f"• Runway key: {'✅' if bool(RUNWAY_API_KEY) else '❌'} base={RUNWAY_BASE_URL}",
        f"• Поллинг каждые {VIDEO_POLL_DELAY_S:.1f} c",
    ]
    await update.effective_message.reply_text("\n".join(lines))

# ───── Тарифы/топ-ап меню ─────
async def _send_topup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("500 ₽",  callback_data="topup:rub:500"),
         InlineKeyboardButton("1000 ₽", callback_data="topup:rub:1000"),
         InlineKeyboardButton("2000 ₽", callback_data="topup:rub:2000")],
        [InlineKeyboardButton("Crypto $5",  callback_data="topup:crypto:5"),
         InlineKeyboardButton("Crypto $10", callback_data="topup:crypto:10"),
         InlineKeyboardButton("Crypto $20", callback_data="topup:crypto:20")],
    ])
    await update.effective_message.reply_text("Выберите сумму пополнения:", reply_markup=kb)

# ───── Попытка оплатить → выполнить ─────
async def _try_pay_then_do(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int, engine: str, est_cost_usd: float, coro_func, remember_kind: str="", remember_payload: dict|None=None):
    uname = (update.effective_user.username or "")
    ok, offer = _can_spend_or_offer(uid, uname, engine, est_cost_usd)
    if ok:
        await coro_func()
        return
    if offer == "ASK_SUBSCRIBE":
        await update.effective_message.reply_text(
            "Для выполнения нужен тариф или единый баланс.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=_make_tariff_url("need")))],
                 [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
            )
        )
        return
    try: need_usd = float(offer.split(":",1)[-1])
    except Exception: need_usd = est_cost_usd
    amount_rub = _calc_oneoff_price_rub(engine, need_usd)
    await update.effective_message.reply_text(
        f"Недостаточно лимита. Разовая покупка ≈ {amount_rub} ₽ или пополните баланс:",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=_make_tariff_url("oneoff")))],
             [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
        )
    )

# ───── Команды/кнопки ─────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # deep-link лота: /start <payload> → сохраняем
    payload = ""
    try:
        if context.args: payload = " ".join(context.args).strip()
    except Exception: pass
    if payload:
        kv_set(f"lead:{update.effective_user.id}:lot", payload)
    welcome_url = kv_get("welcome_url", BANNER_URL)
    if welcome_url:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_photo(welcome_url)
    await update.effective_message.reply_text(START_TEXT, reply_markup=main_kb, disable_web_page_preview=True)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, disable_web_page_preview=True)

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(EXAMPLES_TEXT, disable_web_page_preview=True)

async def cmd_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Выберите движок:", reply_markup=engines_kb())

async def cmd_subs_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Открыть тарифы (WebApp)", web_app=WebAppInfo(url=_make_tariff_url("help")))],
        [InlineKeyboardButton("Оформить PRO (ЮKassa)", callback_data="buyinv:pro:1")],
    ])
    await update.effective_message.reply_text("⭐ Тарифы и помощь.\n\n" + HELP_TEXT, reply_markup=kb, disable_web_page_preview=True)

async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip() if context.args else ""
    if not prompt:
        await update.effective_message.reply_text("Формат: /img <описание>")
        return
    async def _go(): await _do_img_generate(update, context, prompt)
    await _try_pay_then_do(update, context, update.effective_user.id, "img", IMG_COST_USD, _go, remember_kind="img", remember_payload={"prompt":prompt})

async def cmd_set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("Команда доступна только владельцу."); return
    if not context.args:
        await update.effective_message.reply_text("Формат: /set_welcome <url_картинки>"); return
    url = " ".join(context.args).strip(); kv_set("welcome_url", url)
    await update.effective_message.reply_text("Картинка приветствия обновлена. /show_welcome для проверки.")

async def cmd_show_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = kv_get("welcome_url", BANNER_URL)
    if url:
        await update.effective_message.reply_photo(url, caption="Текущая картинка приветствия")
    else:
        await update.effective_message.reply_text("Картинка приветствия не задана.")

# Режимные команды
async def cmd_mode_school(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _mode_set(update.effective_user.id, "Учёба"); _mode_track_set(update.effective_user.id, "")
    await update.effective_message.reply_text("🎓 Учёба → выберите подрежим или опишите задачу.", reply_markup=_school_kb())

async def cmd_mode_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _mode_set(update.effective_user.id, "Работа"); _mode_track_set(update.effective_user.id, "")
    await update.effective_message.reply_text("💼 Работа → выберите подрежим или опишите задачу.", reply_markup=_work_kb())

async def cmd_mode_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _mode_set(update.effective_user.id, "Развлечения"); _mode_track_set(update.effective_user.id, "")
    await update.effective_message.reply_text("🔥 Развлечения — быстрые действия:", reply_markup=_fun_quick_kb())

# ───── CallbackQuery основной ─────
_pending_actions: dict[str, dict] = {}
def _new_aid() -> str: return uuid.uuid4().hex[:12]

async def on_cb_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; data = (q.data or "")
    try:
        if any(data.startswith(p) for p in ("school:","work:","fun:")):
            if data in ("fun:revive","fun:clip","fun:img","fun:storyboard"): return
            _, track = data.split(":",1)
            _mode_track_set(update.effective_user.id, track)
            mode = _mode_get(update.effective_user.id)
            await q.edit_message_text(f"{mode} → {track}. Напишите задание/тему.")
            return
    finally:
        with contextlib.suppress(Exception): await q.answer()

async def on_cb_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); data = (q.data or "")
    if data == "fun:img":
        return await q.edit_message_text("Пришлите промпт или /img <описание> — сгенерирую изображение.")
    if data == "fun:revive":
        return await q.edit_message_text("Загрузите фото и напишите, что оживить/как двигаться — сделаю анимацию.")
    if data == "fun:clip":
        return await q.edit_message_text("Пришлите текст/голос и формат (Reels/Shorts), музыку/стиль — соберу клип.")
    if data == "fun:storyboard":
        return await q.edit_message_text("Пришлите фото или идею ролика — верну раскадровку (6 кадров).")

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; data = (q.data or "").strip()
    try:
        # Баланс
        if data == "topup":
            await q.answer(); await _send_topup_menu(update, context); return
        if data.startswith("topup:rub:"):
            await q.answer()
            try: amount_rub = int(data.split(":",2)[-1])
            except Exception: amount_rub = 0
            if amount_rub < MIN_RUB_FOR_INVOICE:
                await q.edit_message_text(f"Минимальная сумма: {MIN_RUB_FOR_INVOICE} ₽"); return
            ok = await _send_invoice_rub("Пополнение баланса","Единый кошелёк",amount_rub,"t=3",update)
            await q.answer("Выставляю счёт…" if ok else "Не удалось", show_alert=not ok)
            return
        if data.startswith("topup:crypto:"):
            await q.answer()
            if not CRYPTO_PAY_API_TOKEN:
                await q.edit_message_text("Настройте CRYPTO_PAY_API_TOKEN."); return
            try: usd = float(data.split(":",2)[-1])
            except Exception: usd = 0.0
            if usd <= 0: await q.edit_message_text("Неверная сумма."); return
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
            context.application.create_task(_poll_crypto_invoice(context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id, usd_amount))
            return
        if data.startswith("crypto:check:"):
            await q.answer()
            inv_id = data.split(":",2)[-1]
            inv = await _crypto_get_invoice(inv_id)
            if not inv:
                await q.edit_message_text("Счёт не найден."); return
            st = (inv.get("status") or "").lower()
            if st == "paid":
                usd_amount = float(inv.get("amount",0.0))
                if (inv.get("asset") or "").upper() == "TON": usd_amount *= TON_USD_RATE
                _wallet_total_add(update.effective_user.id, usd_amount)
                await q.edit_message_text(f"💳 Оплата получена. Баланс +${usd_amount:.2f}."); return
            if st == "active": await q.answer("Платёж ещё не подтверждён", show_alert=True); return
            await q.edit_message_text(f"Статус счёта: {st}"); return

        # Подписка
        if data.startswith("buy:"):
            await q.answer()
            _, tier, months = data.split(":",2); months = int(months)
            desc = f"Подписка {tier.upper()} на {months} мес."
            await q.edit_message_text(
                f"{desc}\nВыберите способ оплаты:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить картой (ЮKassa)", callback_data=f"buyinv:{tier}:{months}")],
                    [InlineKeyboardButton("Списать с баланса (USD)",  callback_data=f"buywallet:{tier}:{months}")],
                ])
            ); return
        if data.startswith("buyinv:"):
            await q.answer()
            _, tier, months = data.split(":",2); months = int(months)
            payload, amount_rub, title = _plan_payload_and_amount(tier, months)
            ok = await _send_invoice_rub(title, f"Оформление подписки {tier.upper()} на {months} мес.", amount_rub, payload, update)
            if not ok: await q.answer("Не удалось выставить счёт", show_alert=True)
            return
        if data.startswith("buywallet:"):
            await q.answer()
            _, tier, months = data.split(":",2); months = int(months)
            amount_rub = _plan_rub(tier, {1:"month",3:"quarter",12:"year"}[months])
            need_usd = float(amount_rub) / max(1e-9, USD_RUB)
            if _wallet_total_take(update.effective_user.id, need_usd):
                until = activate_subscription_with_tier(update.effective_user.id, tier, months)
                await q.edit_message_text(f"✅ Подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')}.\nСписано: ~${need_usd:.2f}.")
            else:
                await q.edit_message_text(
                    "Недостаточно средств на едином балансе.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]])
                )
            return

        # Движки
        if data.startswith("engine:"):
            await q.answer()
            engine = data.split(":",1)[1]
            if engine == "midjourney":
                await q.edit_message_text("Midjourney: доступ через внешний бот/аккаунт. Пока не подключено.")
                return
            if engine in ("gpt","stt_tts"):
                await q.edit_message_text(f"✅ Выбран «{engine}». Пишите запрос текстом/голосом.")
                return
            # images/luma/runway — проверка лимитов
            est = IMG_COST_USD if engine=="images" else (0.40 if engine=="luma" else max(1.0, RUNWAY_UNIT_COST_USD))
            map_engine = {"images":"img","luma":"luma","runway":"runway"}[engine]
            ok, offer = _can_spend_or_offer(update.effective_user.id, (update.effective_user.username or ""), map_engine, est)
            if ok:
                await q.edit_message_text(
                    "✅ Доступно. " +
                    ("Запустите: /img кот в очках" if engine=="images" else "Напишите: «сделай видео … 9 секунд 9:16».")
                ); return
            if offer == "ASK_SUBSCRIBE":
                await q.edit_message_text(
                    "Нужна активная подписка или единый баланс.",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=_make_tariff_url("need-engine")))],
                         [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
                    )
                ); return
            try: need_usd = float(offer.split(":",1)[-1])
            except Exception: need_usd = est
            amount_rub = _calc_oneoff_price_rub(map_engine, need_usd)
            await q.edit_message_text(
                f"Дневной лимит исчерпан. Разовая покупка ≈ {amount_rub} ₽ или пополните баланс.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=_make_tariff_url("oneoff-engine")))],
                     [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
                )
            ); return

        # Выбор Luma/Runway после текстового запроса «сделай видео»
        if data.startswith("choose:"):
            await q.answer()
            _, engine, aid = data.split(":",2)
            meta = _pending_actions.pop(aid, None)
            if not meta:
                await q.answer("Задача устарела", show_alert=True); return
            prompt, duration, aspect = meta["prompt"], meta["duration"], meta["aspect"]
            est = 0.40 if engine=="luma" else max(1.0, RUNWAY_UNIT_COST_USD * (duration / max(1, LUMA_DURATION_S)))
            map_engine = "luma" if engine=="luma" else "runway"

            async def _start():
                if engine == "luma":
                    await _run_luma_video(update, context, prompt, duration, aspect)
                    _register_engine_spend(update.effective_user.id, "luma", 0.40)
                else:
                    await _run_runway_video(update, context, prompt, duration, aspect)
                    base = RUNWAY_UNIT_COST_USD or 7.0
                    _register_engine_spend(update.effective_user.id, "runway", max(1.0, base*(duration/max(1,LUMA_DURATION_S))))

            await _try_pay_then_do(update, context, update.effective_user.id, map_engine, est, _start,
                                   remember_kind=f"video_{engine}",
                                   remember_payload={"prompt":prompt,"duration":duration,"aspect":aspect})
            return

        await q.answer("Неизвестная команда", show_alert=True)
    except Exception as e:
        log.exception("on_cb error: %s", e)
    finally:
        with contextlib.suppress(Exception): await q.answer()

# ───── Текстовый поток ─────
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    cap = capability_answer(text)
    if cap:
        await update.effective_message.reply_text(cap); return

    mtype, rest = detect_media_intent(text)
    if mtype == "video":
        duration, aspect = parse_video_opts(text)
        prompt = rest or re.sub(r"\b(\d+\s*(?:сек|с)\b|(?:9:16|16:9|1:1|4:5|3:4|4:3))","",text,flags=re.I).strip(" ,.")
        if not prompt:
            await update.effective_message.reply_text("Опишите, что снять: «ретро-авто на берегу, закат»."); return
        aid = _new_aid()
        _pending_actions[aid] = {"prompt":prompt,"duration":duration,"aspect":aspect}
        est_luma = 0.40
        est_runway = max(1.0, RUNWAY_UNIT_COST_USD * (duration / max(1, LUMA_DURATION_S)))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🎬 Luma (~${est_luma:.2f})",    callback_data=f"choose:luma:{aid}")],
            [InlineKeyboardButton(f"🎥 Runway (~${est_runway:.2f})", callback_data=f"choose:runway:{aid}")],
        ])
        await update.effective_message.reply_text(
            f"Выберите движок:\nДлительность: {duration} c • Аспект: {aspect}\nЗапрос: «{prompt}»",
            reply_markup=kb
        ); return

    if mtype == "image":
        prompt = rest or re.sub(r"^(img|image|picture)\s*[:\-]\s*","",text,flags=re.I).strip()
        if not prompt:
            await update.effective_message.reply_text("Формат: /img <описание изображения>"); return
        async def _go(): await _do_img_generate(update, context, prompt)
        await _try_pay_then_do(update, context, update.effective_user.id, "img", IMG_COST_USD, _go); return

    ok, _, _ = check_text_and_inc(update.effective_user.id, update.effective_user.username or "")
    if not ok:
        await update.effective_message.reply_text("Лимит текстовых запросов на сегодня исчерпан. Оформите ⭐ подписку или попробуйте завтра.")
        return

    # Режимное поведение (Учёба/Работа/Развлечения)
    uid = update.effective_user.id
    mode, track = _mode_get(uid), _mode_track_get(uid)
    if mode == "Учёба" and track:
        if track == "explain":
            prompt = f"Объясни простыми словами (2–3 примера) и мини-итог:\n\n{text}"
        elif track == "tasks":
            prompt = "Реши пошагово: формулы, пояснения, итог. Если не хватает данных — уточняющие вопросы в конце.\n\n" + text
        elif track == "essay":
            prompt = ("Напиши 400–600 слов (эссе/доклад): введение, 3–5 тезисов с фактами, вывод, 3 источника (если уместно).\n\nТема:\n" + text)
        elif track == "quiz":
            prompt = "Составь мини-квиз: 10 вопросов, варианты A–D; в конце дай ключ ответов (номер→буква). Тема:\n\n" + text
        else:
            prompt = text
        ans = await ask_openai_text(prompt)
        await update.effective_message.reply_text(ans)
        await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])
        return

    reply = await ask_openai_text(text)
    await update.effective_message.reply_text(reply)
    await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])

# ───── Медиа ─────
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ph = update.message.photo[-1]
        f = await ph.get_file()
        data = await f.download_as_bytearray()
        _cache_photo(update.effective_user.id, bytes(data))
        await update.effective_message.reply_text("Фото получено. Что сделать?", reply_markup=photo_quick_actions_kb())
    except Exception as e:
        log.exception("on_photo error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Не смог обработать фото.")

async def on_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document: return
        doc = update.message.document
        mt = (doc.mime_type or "").lower()
        tg_file = await doc.get_file()
        data = await tg_file.download_as_bytearray()
        raw = bytes(data)
        if mt.startswith("image/"):
            _cache_photo(update.effective_user.id, raw)
            await update.effective_message.reply_text("Изображение получено как документ. Что сделать?", reply_markup=photo_quick_actions_kb())
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
        bio = BytesIO(await vf.download_as_bytearray()); bio.seek(0); setattr(bio,"name","voice.ogg")
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        text = await transcribe_audio(bio, "voice.ogg")
        if not text:
            await update.effective_message.reply_text("Не удалось распознать речь."); return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_voice error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Ошибка при обработке voice.")

async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.audio: return
        af = await update.message.audio.get_file()
        filename = update.message.audio.file_name or "audio.mp3"
        bio = BytesIO(await af.download_as_bytearray()); bio.seek(0); setattr(bio,"name",filename)
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        text = await transcribe_audio(bio, filename)
        if not text:
            await update.effective_message.reply_text("Не удалось распознать речь из аудио."); return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_audio error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Ошибка при обработке аудио.")

# ───── Ошибки ─────
async def on_error(update: object, context_: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error: %s", context_.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("Упс, произошла ошибка. Я уже разбираюсь.")
    except Exception:
        pass

# ───── Регистрация хендлеров ─────
def build_application():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("help",         cmd_help))
    app.add_handler(CommandHandler("examples",     cmd_examples))
    app.add_handler(CommandHandler("engines",      cmd_engines))
    app.add_handler(CommandHandler("plans",        cmd_plans))
    app.add_handler(CommandHandler("balance",      cmd_balance))
    app.add_handler(CommandHandler("set_welcome",  cmd_set_welcome))
    app.add_handler(CommandHandler("show_welcome", cmd_show_welcome))
    app.add_handler(CommandHandler("diag_limits",  cmd_diag_limits))
    app.add_handler(CommandHandler("diag_stt",     cmd_diag_stt))
    app.add_handler(CommandHandler("diag_images",  cmd_diag_images))
    app.add_handler(CommandHandler("diag_video",   cmd_diag_video))
    app.add_handler(CommandHandler("img",          cmd_img))
    app.add_handler(CommandHandler("voice_on",     cmd_voice_on))
    app.add_handler(CommandHandler("voice_off",    cmd_voice_off))

    # Платежи
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    # WebApp
    with contextlib.suppress(Exception):
        app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))
    with contextlib.suppress(Exception):
        if hasattr(filters, "WEB_APP_DATA"):
            app.add_handler(MessageHandler(filters.WEB_APP_DATA, on_webapp_data))

    # Быстрые действия «Развлечения»
    app.add_handler(CallbackQueryHandler(on_cb_fun, pattern=r"^fun:(?:revive|clip|img|storyboard)$"))
    # Подрежимы
    app.add_handler(CallbackQueryHandler(on_cb_mode, pattern=r"^(school:|work:|fun:)"))
    # Прочие callback
    app.add_handler(CallbackQueryHandler(on_cb))

    # Голос/аудио
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    # Текстовые кнопки (до общего текстового)
    app.add_handler(MessageHandler(filters.Regex(r"^(?:🧠\s*)?Движки$"), cmd_engines))
    app.add_handler(MessageHandler(filters.Regex(r"^(?:⭐️)?\s*Подписка(?:\s*·\s*Помощь)?$"), cmd_plans))
    app.add_handler(MessageHandler(filters.Regex(r"^(?:💳|🧾)?\s*Баланс$"), cmd_balance))
    app.add_handler(MessageHandler(filters.Regex(r"^Уч[её]ба$"), cmd_mode_school))
    app.add_handler(MessageHandler(filters.Regex(r"^Работа$"), cmd_mode_work))
    app.add_handler(MessageHandler(filters.Regex(r"^Развлечения$"), cmd_mode_fun))

    # Медиа
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, on_doc))

    # Текст (в самом конце)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # Ошибки
    app.add_error_handler(on_error)
    return app

def main():
    db_init(); _db_init_prefs()
    app = build_application()
    if USE_WEBHOOK:
        log.info("🚀 WEBHOOK mode. Public URL: %s Path: %s Port: %s", PUBLIC_URL, WEBHOOK_PATH, PORT)
        app.run_webhook(
            listen="0.0.0.0", port=PORT, url_path=WEBHOOK_PATH.lstrip("/"),
            webhook_url=f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}",
            secret_token=(WEBHOOK_SECRET or None), allowed_updates=Update.ALL_TYPES,
        )
    else:
        log.info("🚀 POLLING mode.")
        with contextlib.suppress(Exception):
            asyncio.get_event_loop().run_until_complete(app.bot.delete_webhook(drop_pending_updates=True))
        app.run_polling(close_loop=False, allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)

if __name__ == "__main__":
    main()
