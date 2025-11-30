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
# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ TTS imports в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
import contextlib  # СѓР¶Рµ Сѓ С‚РµР±СЏ РІС‹С€Рµ РµСЃС‚СЊ, РґСѓР±Р»РёСЂРѕРІР°С‚СЊ РќР• РЅР°РґРѕ, РµСЃР»Рё РёРјРїРѕСЂС‚ СЃС‚РѕРёС‚

# Optional PIL / rembg for photo tools
try:
    from PIL import Image, ImageFilter
except Exception:
    Image = None
    ImageFilter = None
try:
    from rembg import remove as rembg_remove
except Exception:
    rembg_remove = None

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ LOGGING в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ ENV в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

def _env_float(name: str, default: float) -> float:
    """
    Р‘РµР·РѕРїР°СЃРЅРѕРµ С‡С‚РµРЅРёРµ float РёР· ENV:
    - РїРѕРґРґРµСЂР¶РёРІР°РµС‚ Рё '4,99', Рё '4.99'
    - РїСЂРё РѕС€РёР±РєРµ РІРѕР·РІСЂР°С‰Р°РµС‚ default
    """
    raw = os.environ.get(name)
    if not raw:
        return float(default)
    raw = raw.replace(",", ".").strip()
    try:
        return float(raw)
    except Exception:
        return float(default)
BOT_TOKEN = (os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
BOT_USERNAME     = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
PUBLIC_URL       = os.environ.get("PUBLIC_URL", "").strip()
WEBAPP_URL       = os.environ.get("WEBAPP_URL", "").strip()

OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL  = os.environ.get("OPENAI_BASE_URL", "").strip()        # OpenRouter РёР»Рё СЃРІРѕР№ РїСЂРѕРєСЃРё РґР»СЏ С‚РµРєСЃС‚Р°
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
# Luma Images (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ: РµСЃР»Рё РЅРµС‚ вЂ” РёСЃРїРѕР»СЊР·СѓРµРј OpenAI Images РєР°Рє С„РѕР»Р±СЌРє)
LUMA_IMG_BASE_URL = os.environ.get("LUMA_IMG_BASE_URL", "").strip().rstrip("/")
LUMA_IMG_MODEL    = os.environ.get("LUMA_IMG_MODEL", "imagine-image-1").strip()

# Р¤РѕР»Р±СЌРєРё Luma
_fallbacks_raw = ",".join([
    os.environ.get("LUMA_FALLBACKS", ""),
    os.environ.get("LUMA_FALLBACK_BASE_URL", "")
])
LUMA_FALLBACKS = []
for u in re.split(r"[;,]\s*", _fallbacks_raw):
    if not u: continue
    u = u.strip().rstrip("/")
    if u and u != LUMA_BASE_URL and u not in LUMA_FALLBACKS:
        LUMA_FALLBACKS.append(u)

# Runway endpoints
RUNWAY_BASE_URL    = (os.environ.get("RUNWAY_BASE_URL", "https://api.runwayml.com").strip().rstrip("/"))
RUNWAY_CREATE_PATH = "/v1/tasks"
RUNWAY_STATUS_PATH = "/v1/tasks/{id}"

# РўР°Р№РјР°СѓС‚С‹
LUMA_MAX_WAIT_S     = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)
RUNWAY_MAX_WAIT_S   = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "1200").strip() or 1200)
VIDEO_POLL_DELAY_S  = float((os.environ.get("VIDEO_POLL_DELAY_S") or "6.0").strip() or 6.0)

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ UTILS ---------
_LUMA_ACTIVE_BASE = None  # РєСЌС€ РїРѕСЃР»РµРґРЅРµРіРѕ Р¶РёРІРѕРіРѕ Р±Р°Р·РѕРІРѕРіРѕ URL

async def _pick_luma_base(client: httpx.AsyncClient) -> str:
    global _LUMA_ACTIVE_BASE
    candidates = []
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
DB_PATH        = os.path.abspath(os.environ.get("DB_PATH", "subs.db"))

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
if not PUBLIC_URL or not PUBLIC_URL.startswith("https://"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")
if not OPENAI_API_KEY:
    raise RuntimeError("ENV OPENAI_API_KEY is missing")

# в”Ђв”Ђ Р‘РµР·Р»РёРјРёС‚ в”Ђв”Ђ
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

# в”Ђв”Ђ Premium page URL в”Ђв”Ђ
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

# в”Ђв”Ђ OpenAI clients в”Ђв”Ђ
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

# Tavily (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ)
try:
    if TAVILY_API_KEY:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
    else:
        tavily = None
except Exception:
    tavily = None

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ DB: subscriptions / usage / wallet / kv в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
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

# usage & wallet
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
        img_usd  REAL DEFAULT 0.0,
        usd REAL DEFAULT 0.0
    )""")
    # kv store
    cur.execute("""CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)""")
    # РјРёРіСЂР°С†РёРё
    try:
        cur.execute("ALTER TABLE wallet ADD COLUMN usd REAL DEFAULT 0.0")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE subscriptions ADD COLUMN tier TEXT")
    except Exception:
        pass
    con.commit(); con.close()

def kv_get(key: str, default: str | None = None) -> str | None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT value FROM kv WHERE key=?", (key,))
    row = cur.fetchone(); con.close()
    return (row[0] if row else default)

def kv_set(key: str, value: str):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?,?)", (key, value))
    con.commit(); con.close()

def _today_ymd() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _usage_row(user_id: int, ymd: str | None = None):
    ymd = ymd or _today_ymd()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO usage_daily(user_id, ymd) VALUES (?,?)", (user_id, ymd))
    con.commit()
    cur.execute("SELECT text_count, luma_usd, runway_usd, img_usd FROM usage_daily WHERE user_id=? AND ymd=?", (user_id, ymd))
    row = cur.fetchone(); con.close()
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
    cur.execute("SELECT luma_usd, runway_usd, img_usd, usd FROM wallet WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close()
    return {"luma_usd": row[0], "runway_usd": row[1], "img_usd": row[2], "usd": row[3]}

def _wallet_add(user_id: int, engine: str, usd: float):
    col = {"luma": "luma_usd", "runway": "runway_usd", "img": "img_usd"}[engine]
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute(f"UPDATE wallet SET {col} = {col} + ? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close()

def _wallet_take(user_id: int, engine: str, usd: float) -> bool:
    col = {"luma": "luma_usd", "runway": "runway_usd", "img": "img_usd"}[engine]
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT luma_usd, runway_usd, img_usd FROM wallet WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    bal = {"luma": row[0], "runway": row[1], "img": row[2]}[engine]
    if bal + 1e-9 < usd:
        con.close(); return False
    cur.execute(f"UPDATE wallet SET {col} = {col} - ? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close()
    return True

# === Р•Р”РРќР«Р™ РљРћРЁР•Р›РЃРљ (USD) ===
def _wallet_total_get(user_id: int) -> float:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES (?)", (user_id,))
    con.commit()
    cur.execute("SELECT usd FROM wallet WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close()
    return float(row[0] if row and row[0] is not None else 0.0)

def _wallet_total_add(user_id: int, usd: float):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("UPDATE wallet SET usd = COALESCE(usd,0)+? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close()

def _wallet_total_take(user_id: int, usd: float) -> bool:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT usd FROM wallet WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    bal = float(row[0] if row and row[0] is not None else 0.0)
    if bal + 1e-9 < usd:
        con.close(); return False
    cur.execute("UPDATE wallet SET usd = usd - ? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close()
    return True

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Р›РёРјРёС‚С‹/С†РµРЅС‹ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
USD_RUB = float(os.environ.get("USD_RUB", "100"))
ONEOFF_MARKUP_DEFAULT = float(os.environ.get("ONEOFF_MARKUP_DEFAULT", "1.0"))
ONEOFF_MARKUP_RUNWAY  = float(os.environ.get("ONEOFF_MARKUP_RUNWAY",  "0.5"))
LUMA_RES_HINT = os.environ.get("LUMA_RES", "720p").lower()
RUNWAY_UNIT_COST_USD = float(os.environ.get("RUNWAY_UNIT_COST_USD", "7.0"))
IMG_COST_USD = float(os.environ.get("IMG_COST_USD", "0.05"))

# DEMO: free РґР°С‘С‚ РїРѕРїСЂРѕР±РѕРІР°С‚СЊ РєР»СЋС‡РµРІС‹Рµ РґРІРёР¶РєРё
LIMITS = {
    "free":      {"text_per_day": 5,    "luma_budget_usd": 0.40, "runway_budget_usd": 0.0,  "img_budget_usd": 0.05, "allow_engines": ["gpt","luma","images"]},
    "start":     {"text_per_day": 200,  "luma_budget_usd": 0.8,  "runway_budget_usd": 0.0,  "img_budget_usd": 0.2,  "allow_engines": ["gpt","luma","midjourney","images"]},
    "pro":       {"text_per_day": 1000, "luma_budget_usd": 4.0,  "runway_budget_usd": 7.0,  "img_budget_usd": 1.0,  "allow_engines": ["gpt","luma","runway","midjourney","images"]},
    "ultimate":  {"text_per_day": 5000, "luma_budget_usd": 8.0,  "runway_budget_usd": 14.0, "img_budget_usd": 2.0,  "allow_engines": ["gpt","luma","runway","midjourney","images"]},
}

def _limits_for(user_id: int) -> dict:
    tier = get_subscription_tier(user_id)
    d = LIMITS.get(tier, LIMITS["free"]).copy()
    d["tier"] = tier
    return d

def check_text_and_inc(user_id: int, username: str | None = None) -> tuple[bool, int, str]:
    if is_unlimited(user_id, username):
        _usage_update(user_id, text_count=1)
        return True, 999999, "ultimate"
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
    val = int(rub + 0.999)
    return max(MIN_RUB_FOR_INVOICE, val)

def _can_spend_or_offer(user_id: int, username: str | None, engine: str, est_cost_usd: float) -> tuple[bool, str]:
    if is_unlimited(user_id, username):
        if engine in ("luma", "runway", "img"):
            _usage_update(user_id, **{f"{engine}_usd": est_cost_usd})
        return True, ""
    if engine not in ("luma", "runway", "img"):
        return True, ""
    tier = get_subscription_tier(user_id)
    lim = _limits_for(user_id)
    row = _usage_row(user_id)
    spent = row[f"{engine}_usd"]; budget = lim[f"{engine}_budget_usd"]

    if spent + est_cost_usd <= budget + 1e-9:
        _usage_update(user_id, **{f"{engine}_usd": est_cost_usd})
        return True, ""

    # РџРѕРїС‹С‚РєР° РїРѕРєСЂС‹С‚СЊ РёР· РµРґРёРЅРѕРіРѕ РєРѕС€РµР»СЊРєР°
    need = max(0.0, spent + est_cost_usd - budget)
    if need > 0:
        if _wallet_total_take(user_id, need):
            _usage_update(user_id, **{f"{engine}_usd": est_cost_usd})
            return True, ""
        if tier == "free":
            return False, "ASK_SUBSCRIBE"
        return False, f"OFFER:{need:.2f}"
    return True, ""

def _register_engine_spend(user_id: int, engine: str, usd: float):
    if engine in ("luma","runway","img"):
        _usage_update(user_id, **{f"{engine}_usd": float(usd)})

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Prompts в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
SYSTEM_PROMPT = (
    "РўС‹ РґСЂСѓР¶РµР»СЋР±РЅС‹Р№ Рё Р»Р°РєРѕРЅРёС‡РЅС‹Р№ Р°СЃСЃРёСЃС‚РµРЅС‚ РЅР° СЂСѓСЃСЃРєРѕРј. "
    "РћС‚РІРµС‡Р°Р№ РїРѕ СЃСѓС‚Рё, СЃС‚СЂСѓРєС‚СѓСЂРёСЂСѓР№ СЃРїРёСЃРєР°РјРё/С€Р°РіР°РјРё, РЅРµ РІС‹РґСѓРјС‹РІР°Р№ С„Р°РєС‚С‹. "
    "Р•СЃР»Рё СЃСЃС‹Р»Р°РµС€СЊСЃСЏ РЅР° РёСЃС‚РѕС‡РЅРёРєРё вЂ” РІ РєРѕРЅС†Рµ РґР°Р№ РєРѕСЂРѕС‚РєРёР№ СЃРїРёСЃРѕРє СЃСЃС‹Р»РѕРє."
)
VISION_SYSTEM_PROMPT = (
    "РўС‹ С‡С‘С‚РєРѕ РѕРїРёСЃС‹РІР°РµС€СЊ СЃРѕРґРµСЂР¶РёРјРѕРµ РёР·РѕР±СЂР°Р¶РµРЅРёР№: РѕР±СЉРµРєС‚С‹, С‚РµРєСЃС‚, СЃС…РµРјС‹, РіСЂР°С„РёРєРё. "
    "РќРµ РёРґРµРЅС‚РёС„РёС†РёСЂСѓР№ Р»РёС‡РЅРѕСЃС‚Рё Р»СЋРґРµР№ Рё РЅРµ РїРёС€Рё РёРјРµРЅР°, РµСЃР»Рё РѕРЅРё РЅРµ РЅР°РїРµС‡Р°С‚Р°РЅС‹ РЅР° РёР·РѕР±СЂР°Р¶РµРЅРёРё."
)

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Heuristics / intent в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
_SMALLTALK_RE = re.compile(r"^(РїСЂРёРІРµС‚|Р·РґСЂР°РІСЃС‚РІСѓР№|РґРѕР±СЂС‹Р№\s*(РґРµРЅСЊ|РІРµС‡РµСЂ|СѓС‚СЂРѕ)|С…Рё|hi|hello|РєР°Рє РґРµР»Р°|СЃРїР°СЃРёР±Рѕ|РїРѕРєР°)\b", re.I)
_NEWSY_RE     = re.compile(r"(РєРѕРіРґР°|РґР°С‚Р°|РІС‹Р№РґРµС‚|СЂРµР»РёР·|РЅРѕРІРѕСЃС‚|РєСѓСЂСЃ|С†РµРЅР°|РїСЂРѕРіРЅРѕР·|РЅР°Р№РґРё|РѕС„РёС†РёР°Р»|РїРѕРіРѕРґР°|СЃРµРіРѕРґРЅСЏ|С‚СЂРµРЅРґ|Р°РґСЂРµСЃ|С‚РµР»РµС„РѕРЅ)", re.I)
_CAPABILITY_RE= re.compile(r"(РјРѕР¶(РµС€СЊ|РЅРѕ|РµС‚Рµ).{0,16}(Р°РЅР°Р»РёР·|СЂР°СЃРїРѕР·РЅ|С‡РёС‚Р°С‚СЊ|СЃРѕР·РґР°(РІР°)?С‚|РґРµР»Р°(С‚СЊ)?).{0,24}(С„РѕС‚Рѕ|РєР°СЂС‚РёРЅРє|РёР·РѕР±СЂР°Р¶РµРЅ|pdf|docx|epub|fb2|Р°СѓРґРёРѕ|РєРЅРёРі))", re.I)

_IMG_WORDS = r"(РєР°СЂС‚РёРЅ\w+|РёР·РѕР±СЂР°Р¶РµРЅ\w+|С„РѕС‚Рѕ\w*|СЂРёСЃСѓРЅРє\w+|image|picture|img\b|logo|banner|poster)"
_VID_WORDS = r"(РІРёРґРµРѕ|СЂРѕР»РёРє\w*|Р°РЅРёРјР°С†Рё\w*|shorts?|reels?|clip|video|vid\b)"

def is_smalltalk(text: str) -> bool:
    t = (text or "").strip().lower()
    return bool(_SMALLTALK_RE.search(t))

def should_browse(text: str) -> bool:
    t = (text or "").strip().lower()
    if len(t) < 8:
        return False
    if "http://" in t or "https://" in t:
        return False
    return bool(_NEWSY_RE.search(t)) and not is_smalltalk(t)

_CREATE_CMD = r"(СЃРґРµР»Р°(Р№|Р№С‚Рµ)|СЃРѕР·РґР°(Р№|Р№С‚Рµ)|СЃРіРµРЅРµСЂРёСЂСѓ(Р№|Р№С‚Рµ)|РЅР°СЂРёСЃСѓ(Р№|Р№С‚Рµ)|render|generate|create|make)"
_PREFIXES_VIDEO = [r"^" + _CREATE_CMD + r"\s+РІРёРґРµРѕ", r"^video\b", r"^reels?\b", r"^shorts?\b"]
_PREFIXES_IMAGE = [r"^" + _CREATE_CMD + r"\s+(?:РєР°СЂС‚РёРЅ\w+|РёР·РѕР±СЂР°Р¶РµРЅ\w+|С„РѕС‚Рѕ\w+|СЂРёСЃСѓРЅРє\w+)", r"^image\b", r"^picture\b", r"^img\b"]

def _strip_leading(s: str) -> str:
    return s.strip(" \n\t:вЂ”вЂ“-\"вЂњвЂќ'В«В»,.()[]")

def _after_match(text: str, match) -> str:
    return _strip_leading(text[match.end():])

def _looks_like_capability_question(tl: str) -> bool:
    if "?" in tl and re.search(_CAPABILITY_RE, tl):
        if not re.search(_CREATE_CMD, tl, re.I):
            return True
    m = re.search(r"\b(С‚С‹|РІС‹)?\s*РјРѕР¶(РµС€СЊ|РЅРѕ|РµС‚Рµ)\b", tl)
    if m and re.search(_CAPABILITY_RE, tl) and not re.search(_CREATE_CMD, tl, re.I):
        return True
    return False

def detect_media_intent(text: str):
    if not text:
        return (None, "")
    t = text.strip()
    tl = t.lower()

    if _looks_like_capability_question(tl):
        return (None, "")

    for p in _PREFIXES_VIDEO:
        m = re.search(p, tl, re.I)
        if m:
            return ("video", _after_match(t, m))
    for p in _PREFIXES_IMAGE:
        m = re.search(p, tl, re.I)
        if m:
            return ("image", _after_match(t, m))

    if re.search(_CREATE_CMD, tl, re.I):
        if re.search(_VID_WORDS, tl, re.I):
            clean = re.sub(_VID_WORDS, "", tl, flags=re.I)
            clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
            return ("video", _strip_leading(clean))
        if re.search(_IMG_WORDS, tl, re.I):
            clean = re.sub(_IMG_WORDS, "", tl, flags=re.I)
            clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
            return ("image", _strip_leading(clean))

    m = re.match(r"^(img|image|picture)\s*[:\-]\s*(.+)$", tl)
    if m:
        return ("image", _strip_leading(t[m.end(1)+1:]))

    m = re.match(r"^(video|vid|reels?|shorts?)\s*[:\-]\s*(.+)$", tl)
    if m:
        return ("video", _strip_leading(t[m.end(1)+1:]))

    return (None, "")

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ OpenAI helpers в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
def _oai_text_client():
    return oai_llm

def _pick_vision_model() -> str:
    try:
        mv = globals().get("OPENAI_VISION_MODEL")
        return (mv or OPENAI_MODEL).strip()
    except Exception:
        return OPENAI_MODEL

async def ask_openai_text(user_text: str, web_ctx: str = "") -> str:
    user_text = (user_text or "").strip()
    if not user_text:
        return "РџСѓСЃС‚РѕР№ Р·Р°РїСЂРѕСЃ."

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({"role": "system", "content": f"РљРѕРЅС‚РµРєСЃС‚ РёР· РІРµР±-РїРѕРёСЃРєР°:\n{web_ctx}"})
    messages.append({"role": "user", "content": user_text})

    last_err = None
    for attempt in range(3):
        try:
            resp = _oai_text_client().chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                temperature=0.6,
            )
            txt = (resp.choices[0].message.content or "").strip()
            if txt:
                return txt
        except Exception as e:
            last_err = e
            log.warning("OpenAI/OpenRouter chat attempt %d failed: %s", attempt + 1, e)
            await asyncio.sleep(0.8 * (attempt + 1))
    log.error("ask_openai_text failed: %s", last_err)
    return "вљ пёЏ РЎРµР№С‡Р°СЃ РЅРµ РїРѕР»СѓС‡РёР»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ РѕС‚РІРµС‚ РѕС‚ РјРѕРґРµР»Рё. РЇ РЅР° СЃРІСЏР·Рё вЂ” РїРѕРїСЂРѕР±СѓР№ РїРµСЂРµС„РѕСЂРјСѓР»РёСЂРѕРІР°С‚СЊ Р·Р°РїСЂРѕСЃ РёР»Рё РїРѕРІС‚РѕСЂРёС‚СЊ С‡СѓС‚СЊ РїРѕР·Р¶Рµ."

async def ask_openai_vision(user_text: str, img_b64: str, mime: str) -> str:
    try:
        prompt = (user_text or "РћРїРёС€Рё, С‡С‚Рѕ РЅР° РёР·РѕР±СЂР°Р¶РµРЅРёРё Рё РєР°РєРѕР№ С‚Р°Рј С‚РµРєСЃС‚.").strip()
        model = _pick_vision_model()
        resp = _oai_text_client().chat.completions.create(
            model=model,
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
        return "РќРµ СѓРґР°Р»РѕСЃСЊ РїСЂРѕР°РЅР°Р»РёР·РёСЂРѕРІР°С‚СЊ РёР·РѕР±СЂР°Р¶РµРЅРёРµ."


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РџРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёРµ РЅР°СЃС‚СЂРѕР№РєРё (TTS) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
def _db_init_prefs():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_prefs (
        user_id INTEGER PRIMARY KEY,
        tts_on  INTEGER DEFAULT 0
    )""")
    con.commit(); con.close()

def _tts_get(user_id: int) -> bool:
    try:
        _db_init_prefs()
    except Exception:
        pass
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO user_prefs(user_id, tts_on) VALUES (?,0)", (user_id,))
    con.commit()
    cur.execute("SELECT tts_on FROM user_prefs WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close()
    return bool(row and row[0])

def _tts_set(user_id: int, on: bool):
    try:
        _db_init_prefs()
    except Exception:
        pass
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO user_prefs(user_id, tts_on) VALUES (?,?)", (user_id, 1 if on else 0))
    cur.execute("UPDATE user_prefs SET tts_on=? WHERE user_id=?", (1 if on else 0, user_id))
    con.commit(); con.close()


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РќР°РґС‘Р¶РЅС‹Р№ TTS С‡РµСЂРµР· REST (OGG/Opus) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
def _tts_bytes_sync(text: str) -> bytes | None:
    try:
        if not OPENAI_TTS_KEY:
            return None
        if OPENAI_TTS_KEY.startswith("sk-or-"):
            log.error("TTS key looks like OpenRouter (sk-or-...). Provide a real OpenAI key in OPENAI_TTS_KEY.")
            return None
        url = f"{OPENAI_TTS_BASE_URL.rstrip('/')}/audio/speech"
        payload = {
            "model": OPENAI_TTS_MODEL,
            "voice": OPENAI_TTS_VOICE,
            "input": text,
            "format": "ogg"  # OGG/Opus РґР»СЏ Telegram voice
        }
        headers = {
            "Authorization": f"Bearer {OPENAI_TTS_KEY}",
            "Content-Type": "application/json"
        }
        r = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        r.raise_for_status()
        data = r.content if r.content else None
        if data:
            log.info("TTS bytes: %s bytes", len(data))
        return data
    except Exception as e:
        log.exception("TTS HTTP error: %s", e)
        return None

async def maybe_tts_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    if not _tts_get(user_id):
        return
    text = (text or "").strip()
    if not text:
        return
    if len(text) > TTS_MAX_CHARS:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text(
                f"рџ”‡ РћР·РІСѓС‡РєР° РІС‹РєР»СЋС‡РµРЅР° РґР»СЏ СЌС‚РѕРіРѕ СЃРѕРѕР±С‰РµРЅРёСЏ: С‚РµРєСЃС‚ РґР»РёРЅРЅРµРµ {TTS_MAX_CHARS} СЃРёРјРІРѕР»РѕРІ."
            )
        return
    if not OPENAI_TTS_KEY:
        return
    try:
        with contextlib.suppress(Exception):
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VOICE)
        audio = await asyncio.to_thread(_tts_bytes_sync, text)
        if not audio:
            with contextlib.suppress(Exception):
                await update.effective_message.reply_text("рџ”‡ РќРµ СѓРґР°Р»РѕСЃСЊ СЃРёРЅС‚РµР·РёСЂРѕРІР°С‚СЊ РіРѕР»РѕСЃ.")
            return
        bio = BytesIO(audio); bio.seek(0); bio.name = "say.ogg"
        await update.effective_message.reply_voice(voice=InputFile(bio), caption=text)
    except Exception as e:
        log.exception("maybe_tts_reply error: %s", e)

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, True)
    await update.effective_message.reply_text(f"рџ”Љ РћР·РІСѓС‡РєР° РІРєР»СЋС‡РµРЅР°. Р›РёРјРёС‚ {TTS_MAX_CHARS} СЃРёРјРІРѕР»РѕРІ РЅР° РѕС‚РІРµС‚.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, False)
    await update.effective_message.reply_text("рџ”€ РћР·РІСѓС‡РєР° РІС‹РєР»СЋС‡РµРЅР°.")

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Speech-to-Text (STT) вЂў OpenAI Whisper/4o-mini-transcribe в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
from openai import OpenAI as _OpenAI_STT

OPENAI_STT_MODEL    = (os.getenv("OPENAI_STT_MODEL") or "whisper-1").strip()
OPENAI_STT_KEY      = (os.getenv("OPENAI_STT_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_STT_BASE_URL = (os.getenv("OPENAI_STT_BASE_URL") or "https://api.openai.com/v1").rstrip("/")

def _oai_stt_client():
    return _OpenAI_STT(api_key=OPENAI_STT_KEY, base_url=OPENAI_STT_BASE_URL)

async def _stt_transcribe_bytes(filename: str, raw: bytes) -> str:
    last_err = None
    for attempt in range(3):
        try:
            bio = BytesIO(raw)
            bio.name = filename
            bio.seek(0)
            resp = _oai_stt_client().audio.transcriptions.create(
                model=OPENAI_STT_MODEL,
                file=bio,
            )
            text = (getattr(resp, "text", "") or "").strip()
            if text:
                return text
        except Exception as e:
            last_err = e
            log.warning("STT attempt %d failed: %s", attempt+1, e)
            await asyncio.sleep(0.8 * (attempt + 1))
    log.error("STT failed: %s", last_err)
    return ""

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РҐРµРЅРґР»РµСЂ РіРѕР»РѕСЃРѕРІС‹С…/Р°СѓРґРёРѕ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
import re
import contextlib
from io import BytesIO
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    voice = getattr(msg, "voice", None)
    audio = getattr(msg, "audio", None)
    media = voice or audio
    if not media:
        await msg.reply_text("РќРµ РЅР°С€С‘Р» РіРѕР»РѕСЃРѕРІРѕР№ С„Р°Р№Р».")
        return

    # РЎРєР°С‡РёРІР°РµРј С„Р°Р№Р» РёР· Telegram
    try:
        with contextlib.suppress(Exception):
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

        tg_file = await context.bot.get_file(media.file_id)
        buf = BytesIO()
        await tg_file.download_to_memory(out=buf)
        raw = buf.getvalue()

        mime = (getattr(media, "mime_type", "") or "").lower()
        if "ogg" in mime or "opus" in mime:
            filename = "voice.ogg"
        elif "webm" in mime:
            filename = "voice.webm"
        elif "wav" in mime:
            filename = "voice.wav"
        elif "mp3" in mime or "mpeg" in mime or "mpga" in mime:
            filename = "voice.mp3"
        else:
            filename = "voice.ogg"

    except Exception as e:
        try:
            log.exception("TG download error: %s", e)  # РµСЃР»Рё log РѕРїСЂРµРґРµР»С‘РЅ РІС‹С€Рµ
        except Exception:
            pass
        await msg.reply_text("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРєР°С‡Р°С‚СЊ РіРѕР»РѕСЃРѕРІРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ.")
        return

    # РўСЂР°РЅСЃРєСЂРёР±РёСЂСѓРµРј
    transcript = await _stt_transcribe_bytes(filename, raw)
    if not transcript:
        await msg.reply_text("РћС€РёР±РєР° РїСЂРё СЂР°СЃРїРѕР·РЅР°РІР°РЅРёРё СЂРµС‡Рё.")
        return

    transcript = transcript.strip()

    # (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ) РїРѕРґС‚РІРµСЂРґРёРј СЂР°СЃРїРѕР·РЅР°РІР°РЅРёРµ РґР»СЏ UX/РѕС‚Р»Р°РґРєРё
    with contextlib.suppress(Exception):
        if transcript:
            await msg.reply_text(f"рџ—ЈпёЏ Р Р°СЃРїРѕР·РЅР°Р»: {transcript}")

    # РџСЂРѕР±СЂР°СЃС‹РІР°РµРј РєР°Рє РѕР±С‹С‡РЅС‹Р№ С‚РµРєСЃС‚ вЂ” РґР°Р»СЊС€Рµ СЃСЂР°Р±РѕС‚Р°РµС‚ on_text СЃРѕ РІСЃРµР№ С‚РІРѕРµР№ РјР°СЂС€СЂСѓС‚РёР·Р°С†РёРµР№
    # (detect_media_intent, РІС‹Р±РѕСЂ Luma/Runway, /img Рё С‚.Рґ.)
    update.message.text = transcript
    await on_text(update, context)

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РР·РІР»РµС‡РµРЅРёРµ С‚РµРєСЃС‚Р° РёР· РґРѕРєСѓРјРµРЅС‚РѕРІ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
def _safe_decode_txt(b: bytes) -> str:
    for enc in ("utf-8","cp1251","latin-1"):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("utf-8", errors="ignore")

def _extract_pdf_text(data: bytes) -> str:
    try:
        import PyPDF2
        rd = PyPDF2.PdfReader(BytesIO(data))
        parts = []
        for p in rd.pages:
            try:
                parts.append(p.extract_text() or "")
            except Exception:
                continue
        t = "\n".join(parts).strip()
        if t:
            return t
    except Exception:
        pass
    try:
        from pdfminer_high_level import extract_text as pdfminer_extract_text  # may not exist
    except Exception:
        pdfminer_extract_text = None  # type: ignore
    if pdfminer_extract_text:
        try:
            return (pdfminer_extract_text(BytesIO(data)) or "").strip()
        except Exception:
            pass
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        txt = []
        for page in doc:
            try:
                txt.append(page.get_text("text"))
            except Exception:
                continue
        return "\n".join(txt)
    except Exception:
        pass
    return ""

def _extract_epub_text(data: bytes) -> str:
    try:
        from ebooklib import epub
        from bs4 import BeautifulSoup
        book = epub.read_epub(BytesIO(data))
        chunks = []
        for item in book.get_items():
            if item.get_type() == 9:  # DOCUMENT
                try:
                    soup = BeautifulSoup(item.get_content(), "html.parser")
                    txt = soup.get_text(separator=" ", strip=True)
                    if txt:
                        chunks.append(txt)
                except Exception:
                    continue
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
            if elem.text and elem.text.strip():
                texts.append(elem.text.strip())
        return " ".join(texts).strip()
    except Exception:
        return ""

def extract_text_from_document(data: bytes, filename: str) -> tuple[str, str]:
    name = (filename or "").lower()
    if name.endswith(".pdf"):  return _extract_pdf_text(data),  "PDF"
    if name.endswith(".epub"): return _extract_epub_text(data), "EPUB"
    if name.endswith(".docx"): return _extract_docx_text(data), "DOCX"
    if name.endswith(".fb2"):  return _extract_fb2_text(data),  "FB2"
    if name.endswith(".txt"):  return _safe_decode_txt(data),    "TXT"
    if name.endswith((".mobi",".azw",".azw3")): return "", "MOBI/AZW"
    decoded = _safe_decode_txt(data)
    return decoded if decoded else "", "UNKNOWN"


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РЎСѓРјРјР°СЂРёР·Р°С†РёСЏ РґР»РёРЅРЅС‹С… С‚РµРєСЃС‚РѕРІ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def _summarize_chunk(text: str, query: str | None = None) -> str:
    prefix = "РЎСѓРјРјРёСЂСѓР№ РєСЂР°С‚РєРѕ РїРѕ РїСѓРЅРєС‚Р°Рј РѕСЃРЅРѕРІРЅРѕРµ РёР· С„СЂР°РіРјРµРЅС‚Р° РґРѕРєСѓРјРµРЅС‚Р° РЅР° СЂСѓСЃСЃРєРѕРј:\n"
    if query:
        prefix = (f"РЎСѓРјРјРёСЂСѓР№ С„СЂР°РіРјРµРЅС‚ СЃ СѓС‡С‘С‚РѕРј С†РµР»Рё: {query}\n"
                  f"Р”Р°Р№ РѕСЃРЅРѕРІРЅС‹Рµ С‚РµР·РёСЃС‹, С„Р°РєС‚С‹, С†РёС„СЂС‹. Р СѓСЃСЃРєРёР№ СЏР·С‹Рє.\n")
    prompt = prefix + text
    return await ask_openai_text(prompt)

async def summarize_long_text(full_text: str, query: str | None = None) -> str:
    max_chunk = 8000
    text = full_text.strip()
    if len(text) <= max_chunk:
        return await _summarize_chunk(text, query=query)
    parts = []
    i = 0
    while i < len(text) and len(parts) < 8:
        parts.append(text[i:i+max_chunk]); i += max_chunk
    partials = [await _summarize_chunk(p, query=query) for p in parts]
    combined = "\n\n".join(f"- Р¤СЂР°РіРјРµРЅС‚ {idx+1}:\n{s}" for idx, s in enumerate(partials))
    final_prompt = ("РћР±СЉРµРґРёРЅРё С‚РµР·РёСЃС‹ РїРѕ С„СЂР°РіРјРµРЅС‚Р°Рј РІ С†РµР»СЊРЅРѕРµ СЂРµР·СЋРјРµ РґРѕРєСѓРјРµРЅС‚Р°: 1) 5вЂ“10 РіР»Р°РІРЅС‹С… РїСѓРЅРєС‚РѕРІ; "
                    "2) РєР»СЋС‡РµРІС‹Рµ С†РёС„СЂС‹/СЃСЂРѕРєРё; 3) РІС‹РІРѕРґ/СЂРµРєРѕРјРµРЅРґР°С†РёРё. Р СѓСЃСЃРєРёР№ СЏР·С‹Рє.\n\n" + combined)
    return await ask_openai_text(final_prompt)


# ======= РђРЅР°Р»РёР· РґРѕРєСѓРјРµРЅС‚РѕРІ (PDF/EPUB/DOCX/FB2/TXT) =======
async def on_doc_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document:
            return
        doc = update.message.document
        tg_file = await doc.get_file()
        data = await tg_file.download_as_bytearray()
        text, kind = extract_text_from_document(bytes(data), doc.file_name or "file")
        if not text.strip():
            await update.effective_message.reply_text(f"РќРµ СѓРґР°Р»РѕСЃСЊ РёР·РІР»РµС‡СЊ С‚РµРєСЃС‚ РёР· {kind}.")
            return
        goal = (update.message.caption or "").strip() or None
        await update.effective_message.reply_text(f"рџ“„ РР·РІР»РµРєР°СЋ С‚РµРєСЃС‚ ({kind}), РіРѕС‚РѕРІР»СЋ РєРѕРЅСЃРїРµРєС‚вЂ¦")
        summary = await summarize_long_text(text, query=goal)
        summary = summary or "Р“РѕС‚РѕРІРѕ."
        await update.effective_message.reply_text(summary)
        await maybe_tts_reply(update, context, summary[:TTS_MAX_CHARS])
    except Exception as e:
        log.exception("on_doc_analyze error: %s", e)
    # РЅРёС‡РµРіРѕ РЅРµ Р±СЂРѕСЃР°РµРј РЅР°СЂСѓР¶Сѓ

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ OpenAI Images (РіРµРЅРµСЂР°С†РёСЏ РєР°СЂС‚РёРЅРѕРє) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def _do_img_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
        b64 = resp.data[0].b64_json
        img_bytes = base64.b64decode(b64)
        await update.effective_message.reply_photo(photo=img_bytes, caption=f"Р“РѕС‚РѕРІРѕ вњ…\nР—Р°РїСЂРѕСЃ: {prompt}")
    except Exception as e:
        log.exception("IMG gen error: %s", e)
        await update.effective_message.reply_text("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕР·РґР°С‚СЊ РёР·РѕР±СЂР°Р¶РµРЅРёРµ.")

async def _luma_generate_image_bytes(prompt: str) -> bytes | None:
    if not LUMA_IMG_BASE_URL or not LUMA_API_KEY:
        # С„РѕР»Р±СЌРє: OpenAI Images
        try:
            resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
            return base64.b64decode(resp.data[0].b64_json)
        except Exception as e:
            log.exception("OpenAI images fallback error: %s", e)
            return None
    try:
        # РџСЂРёРјРµСЂРЅС‹Р№ СЌРЅРґРїРѕРёРЅС‚; РµСЃР»Рё Сѓ С‚РµР±СЏ РґСЂСѓРіРѕР№ вЂ” Р·Р°РјРµРЅРё path/РїРѕР»СЏ РїРѕРґ СЃРІРѕР№ Р°РєРєР°СѓРЅС‚.
        url = f"{LUMA_IMG_BASE_URL}/v1/images"
        headers = {"Authorization": f"Bearer {LUMA_API_KEY}", "Accept": "application/json"}
        payload = {"model": LUMA_IMG_MODEL, "prompt": prompt, "size": "1024x1024"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                return None
            j = r.json() or {}
            b64 = (j.get("data") or [{}])[0].get("b64_json") or j.get("image_base64")
            return base64.b64decode(b64) if b64 else None
    except Exception as e:
        log.exception("Luma image gen error: %s", e)
        return None

async def _start_luma_img(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    async def _go():
        img = await _luma_generate_image_bytes(prompt)
        if not img:
            await update.effective_message.reply_text("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕР·РґР°С‚СЊ РёР·РѕР±СЂР°Р¶РµРЅРёРµ.")
            return
        await update.effective_message.reply_photo(photo=img, caption=f"рџ–Њ Р“РѕС‚РѕРІРѕ вњ…\nР—Р°РїСЂРѕСЃ: {prompt}")
    await _try_pay_then_do(update, context, update.effective_user.id, "img", IMG_COST_USD, _go,
                           remember_kind="luma_img", remember_payload={"prompt": prompt})


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ UI / С‚РµРєСЃС‚С‹ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
START_TEXT = (
    "РџСЂРёРІРµС‚! РЇ РќРµР№СЂРѕ-Bot вЂ” вљЎпёЏ РјСѓР»СЊС‚РёСЂРµР¶РёРјРЅС‹Р№ Р±РѕС‚ РёР· 7 РЅРµР№СЂРѕСЃРµС‚РµР№ РґР»СЏ рџЋ“ СѓС‡С‘Р±С‹, рџ’ј СЂР°Р±РѕС‚С‹ Рё рџ”Ґ СЂР°Р·РІР»РµС‡РµРЅРёР№.\n"
    "РЇ СѓРјРµСЋ СЂР°Р±РѕС‚Р°С‚СЊ РіРёР±СЂРёРґРЅРѕ: РјРѕРіСѓ СЃР°Рј РІС‹Р±СЂР°С‚СЊ Р»СѓС‡С€РёР№ РґРІРёР¶РѕРє РїРѕРґ Р·Р°РґР°С‡Сѓ РёР»Рё РґР°С‚СЊ С‚РµР±Рµ РІС‹Р±СЂР°С‚СЊ РІСЂСѓС‡РЅСѓСЋ. рџ¤ќрџ§ \n"
    "\n"
    "вњЁ Р“Р»Р°РІРЅС‹Рµ СЂРµР¶РёРјС‹:\n"
    "\n"
    "\n"
    "вЂў рџЋ“ РЈС‡С‘Р±Р° вЂ” РѕР±СЉСЏСЃРЅРµРЅРёСЏ СЃ РїСЂРёРјРµСЂР°РјРё, РїРѕС€Р°РіРѕРІС‹Рµ СЂРµС€РµРЅРёСЏ Р·Р°РґР°С‡, СЌСЃСЃРµ/СЂРµС„РµСЂР°С‚/РґРѕРєР»Р°Рґ, РјРёРЅРё-РєРІРёР·С‹.\n"
    "рџ“љ РўР°РєР¶Рµ: СЂР°Р·Р±РѕСЂ СѓС‡РµР±РЅС‹С… PDF/СЌР»РµРєС‚СЂРѕРЅРЅС‹С… РєРЅРёРі, С€РїР°СЂРіР°Р»РєРё Рё РєРѕРЅСЃРїРµРєС‚С‹, РєРѕРЅСЃС‚СЂСѓРєС‚РѕСЂ С‚РµСЃС‚РѕРІ;\n"
    "рџЋ§ С‚Р°Р№Рј-РєРѕРґС‹ РїРѕ Р°СѓРґРёРѕРєРЅРёРіР°Рј/Р»РµРєС†РёСЏРј Рё РєСЂР°С‚РєРёРµ РІС‹Р¶РёРјРєРё. рџ§©\n"
    "\n"
    "вЂў рџ’ј Р Р°Р±РѕС‚Р° вЂ” РїРёСЃСЊРјР°/Р±СЂРёС„С‹/РґРѕРєСѓРјРµРЅС‚С‹, Р°РЅР°Р»РёС‚РёРєР° Рё СЂРµР·СЋРјРµ РјР°С‚РµСЂРёР°Р»РѕРІ, ToDo/РїР»Р°РЅС‹, РіРµРЅРµСЂР°С‚РѕСЂ РёРґРµР№.\n"
    "рџ› пёЏ Р”Р»СЏ Р°СЂС…РёС‚РµРєС‚РѕСЂР°/РґРёР·Р°Р№РЅРµСЂР°/РїСЂРѕРµРєС‚РёСЂРѕРІС‰РёРєР°: СЃС‚СЂСѓРєС‚СѓСЂРёСЂРѕРІР°РЅРёРµ РўР—, С‡РµРє-Р»РёСЃС‚С‹ СЃС‚Р°РґРёР№,\n"
    "рџ—‚пёЏ РЅР°Р·РІР°РЅРёСЏ/РѕРїРёСЃР°РЅРёСЏ Р»РёСЃС‚РѕРІ, СЃРІРѕРґРЅС‹Рµ С‚Р°Р±Р»РёС†С‹ РёР· С‚РµРєСЃС‚РѕРІ, РѕС„РѕСЂРјР»РµРЅРёРµ РїРѕСЏСЃРЅРёС‚РµР»СЊРЅС‹С… Р·Р°РїРёСЃРѕРє. рџ“Љ\n"
    "\n"
    "вЂў рџ”Ґ Р Р°Р·РІР»РµС‡РµРЅРёСЏ вЂ” С„РѕС‚Рѕ-РјР°СЃС‚РµСЂСЃРєР°СЏ (СѓРґР°Р»РµРЅРёРµ/Р·Р°РјРµРЅР° С„РѕРЅР°, РґРѕСЂРёСЃРѕРІРєР°, outpaint), РѕР¶РёРІР»РµРЅРёРµ СЃС‚Р°СЂС‹С… С„РѕС‚Рѕ,\n"
    "рџЋ¬ РІРёРґРµРѕ РїРѕ С‚РµРєСЃС‚Сѓ/РіРѕР»РѕСЃСѓ, РёРґРµРё Рё С„РѕСЂРјР°С‚С‹ РґР»СЏ Reels/Shorts, Р°РІС‚Рѕ-РЅР°СЂРµР·РєР° РёР· РґР»РёРЅРЅС‹С… РІРёРґРµРѕ\n"
    "(СЃС†РµРЅР°СЂРёР№/С‚Р°Р№Рј-РєРѕРґС‹), РјРµРјС‹/РєРІРёР·С‹. рџ–јпёЏрџЄ„\n"
    "\n"
    "рџ§­ РљР°Рє РїРѕР»СЊР·РѕРІР°С‚СЊСЃСЏ:\n"
    "РїСЂРѕСЃС‚Рѕ РІС‹Р±РµСЂРё СЂРµР¶РёРј РєРЅРѕРїРєРѕР№ РЅРёР¶Рµ РёР»Рё РЅР°РїРёС€Рё Р·Р°РїСЂРѕСЃ вЂ” СЏ СЃР°Рј РѕРїСЂРµРґРµР»СЋ Р·Р°РґР°С‡Сѓ Рё РїСЂРµРґР»РѕР¶Сѓ РІР°СЂРёР°РЅС‚С‹. вњЌпёЏвњЁ\n"
    "\n"
    "рџ§  РљРЅРѕРїРєР° В«Р”РІРёР¶РєРёВ»:\n"
    "РґР»СЏ С‚РѕС‡РЅРѕРіРѕ РІС‹Р±РѕСЂР°, РєР°РєСѓСЋ РЅРµР№СЂРѕСЃРµС‚СЊ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РїСЂРёРЅСѓРґРёС‚РµР»СЊРЅРѕ. рџЋЇрџ¤–"
)

def engines_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("рџ’¬ GPT (С‚РµРєСЃС‚/С„РѕС‚Рѕ/РґРѕРєСѓРјРµРЅС‚С‹)", callback_data="engine:gpt")],
        [InlineKeyboardButton("рџ–ј Images (OpenAI)",             callback_data="engine:images")],
        [InlineKeyboardButton("рџЋ¬ Luma вЂ” РєРѕСЂРѕС‚РєРёРµ РІРёРґРµРѕ",       callback_data="engine:luma")],
        [InlineKeyboardButton("рџЋҐ Runway вЂ” РїСЂРµРјРёСѓРј-РІРёРґРµРѕ",      callback_data="engine:runway")],
        [InlineKeyboardButton("рџЋЁ Midjourney (РёР·РѕР±СЂР°Р¶РµРЅРёСЏ)",    callback_data="engine:midjourney")],
        [InlineKeyboardButton("рџ—Ј STT/TTS вЂ” СЂРµС‡СЊв†”С‚РµРєСЃС‚",        callback_data="engine:stt_tts")],
    ])

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ MODES (РЈС‡С‘Р±Р° / Р Р°Р±РѕС‚Р° / Р Р°Р·РІР»РµС‡РµРЅРёСЏ) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackQueryHandler, MessageHandler, filters

# РўРµРєСЃС‚ РєРѕСЂРЅРµРІРѕРіРѕ РјРµРЅСЋ СЂРµР¶РёРјРѕРІ
def _modes_root_text() -> str:
    return (
        "Р’С‹Р±РµСЂРёС‚Рµ СЂРµР¶РёРј СЂР°Р±РѕС‚С‹. Р’ РєР°Р¶РґРѕРј СЂРµР¶РёРјРµ Р±РѕС‚ РёСЃРїРѕР»СЊР·СѓРµС‚ РіРёР±СЂРёРґ РґРІРёР¶РєРѕРІ:\n"
        "вЂў GPT-5 (С‚РµРєСЃС‚/Р»РѕРіРёРєР°) + Vision (С„РѕС‚Рѕ) + STT/TTS (РіРѕР»РѕСЃ)\n"
        "вЂў Luma/Runway вЂ” РІРёРґРµРѕ, Midjourney вЂ” РёР·РѕР±СЂР°Р¶РµРЅРёСЏ\n\n"
        "РњРѕР¶РµС‚Рµ С‚Р°РєР¶Рµ РїСЂРѕСЃС‚Рѕ РЅР°РїРёСЃР°С‚СЊ СЃРІРѕР±РѕРґРЅС‹Р№ Р·Р°РїСЂРѕСЃ вЂ” Р±РѕС‚ РїРѕР№РјС‘С‚."
    )

def modes_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("рџЋ“ РЈС‡С‘Р±Р°", callback_data="mode:study"),
            InlineKeyboardButton("рџ’ј Р Р°Р±РѕС‚Р°", callback_data="mode:work"),
            InlineKeyboardButton("рџ”Ґ Р Р°Р·РІР»РµС‡РµРЅРёСЏ", callback_data="mode:fun"),
        ],
    ])

# в”Ђв”Ђ РћРїРёСЃР°РЅРёРµ Рё РїРѕРґРјРµРЅСЋ РїРѕ СЂРµР¶РёРјР°Рј
def _mode_desc(key: str) -> str:
    if key == "study":
        return (
            "рџЋ“ *РЈС‡С‘Р±Р°*\n"
            "Р“РёР±СЂРёРґ: GPT-5 РґР»СЏ РѕР±СЉСЏСЃРЅРµРЅРёР№/РєРѕРЅСЃРїРµРєС‚РѕРІ, Vision РґР»СЏ С„РѕС‚Рѕ-Р·Р°РґР°С‡, "
            "STT/TTS РґР»СЏ РіРѕР»РѕСЃРѕРІС‹С…, + Midjourney (РёР»Р»СЋСЃС‚СЂР°С†РёРё) Рё Luma/Runway (СѓС‡РµР±РЅС‹Рµ СЂРѕР»РёРєРё).\n\n"
            "Р‘С‹СЃС‚СЂС‹Рµ РґРµР№СЃС‚РІРёСЏ РЅРёР¶Рµ. РњРѕР¶РЅРѕ РЅР°РїРёСЃР°С‚СЊ СЃРІРѕР±РѕРґРЅС‹Р№ Р·Р°РїСЂРѕСЃ (РЅР°РїСЂРёРјРµСЂ: "
            "В«СЃРґРµР»Р°Р№ РєРѕРЅСЃРїРµРєС‚ РёР· PDFВ», В«РѕР±СЉСЏСЃРЅРё РёРЅС‚РµРіСЂР°Р»С‹ СЃ РїСЂРёРјРµСЂР°РјРёВ»)."
        )
    if key == "work":
        return (
            "рџ’ј *Р Р°Р±РѕС‚Р°*\n"
            "Р“РёР±СЂРёРґ: GPT-5 (СЂРµР·СЋРјРµ/РїРёСЃСЊРјР°/Р°РЅР°Р»РёС‚РёРєР°), Vision (С‚Р°Р±Р»РёС†С‹/СЃРєСЂРёРЅС‹), "
            "STT/TTS (РґРёРєС‚РѕРІРєР°/РѕР·РІСѓС‡РєР°), + Midjourney (РІРёР·СѓР°Р»С‹), Luma/Runway (РїСЂРµР·РµРЅС‚Р°С†РёРѕРЅРЅС‹Рµ СЂРѕР»РёРєРё).\n\n"
            "Р‘С‹СЃС‚СЂС‹Рµ РґРµР№СЃС‚РІРёСЏ РЅРёР¶Рµ. РњРѕР¶РЅРѕ РЅР°РїРёСЃР°С‚СЊ СЃРІРѕР±РѕРґРЅС‹Р№ Р·Р°РїСЂРѕСЃ (РЅР°РїСЂРёРјРµСЂ: "
            "В«Р°РґР°РїС‚РёСЂСѓР№ СЂРµР·СЋРјРµ РїРѕРґ РІР°РєР°РЅСЃРёСЋ PMВ», В«РЅР°РїРёСЃР°С‚СЊ РєРѕРјРјРµСЂС‡РµСЃРєРѕРµ РїСЂРµРґР»РѕР¶РµРЅРёРµВ»)."
        )
    if key == "fun":
        return (
            "рџ”Ґ *Р Р°Р·РІР»РµС‡РµРЅРёСЏ*\n"
            "Р“РёР±СЂРёРґ: GPT-5 (РёРґРµРё, СЃС†РµРЅР°СЂРёРё), Midjourney (РєР°СЂС‚РёРЅРєРё), Luma/Runway (С€РѕСЂС‚С‹/СЂРёРµР»СЃС‹), "
            "STT/TTS (РѕР·РІСѓС‡РєР°). Р’СЃС‘ РґР»СЏ Р±С‹СЃС‚СЂС‹С… С‚РІРѕСЂС‡РµСЃРєРёС… С€С‚СѓРє.\n\n"
            "Р‘С‹СЃС‚СЂС‹Рµ РґРµР№СЃС‚РІРёСЏ РЅРёР¶Рµ. РњРѕР¶РЅРѕ РЅР°РїРёСЃР°С‚СЊ СЃРІРѕР±РѕРґРЅС‹Р№ Р·Р°РїСЂРѕСЃ (РЅР°РїСЂРёРјРµСЂ: "
            "В«СЃРґРµР»Р°Р№ СЃС†РµРЅР°СЂРёР№ 30-СЃРµРє С€РѕСЂС‚Р° РїСЂРѕ РєРѕС‚Р°-Р±Р°СЂРёСЃС‚Р°В»)."
        )
    return "Р РµР¶РёРј РЅРµ РЅР°Р№РґРµРЅ."

def _mode_kb(key: str) -> InlineKeyboardMarkup:
    if key == "study":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("рџ“љ РљРѕРЅСЃРїРµРєС‚ РёР· PDF/EPUB/DOCX", callback_data="act:study:pdf_summary")],
            [InlineKeyboardButton("рџ”Ќ РћР±СЉСЏСЃРЅРµРЅРёРµ С‚РµРјС‹",            callback_data="act:study:explain"),
             InlineKeyboardButton("рџ§® Р РµС€РµРЅРёРµ Р·Р°РґР°С‡",              callback_data="act:study:tasks")],
            [InlineKeyboardButton("вњЌпёЏ Р­СЃСЃРµ/СЂРµС„РµСЂР°С‚/РґРѕРєР»Р°Рґ",       callback_data="act:study:essay"),
             InlineKeyboardButton("рџ“ќ РџР»Р°РЅ Рє СЌРєР·Р°РјРµРЅСѓ",           callback_data="act:study:exam_plan")],
            [
                InlineKeyboardButton("рџЋ¬ Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("рџЋЁ Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("рџ—Ј STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("рџ“ќ РЎРІРѕР±РѕРґРЅС‹Р№ Р·Р°РїСЂРѕСЃ", callback_data="act:free")],
            [InlineKeyboardButton("в¬…пёЏ РќР°Р·Р°Рґ", callback_data="mode:root")],
        ])

    if key == "work":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("рџ“„ РџРёСЃСЊРјРѕ/РґРѕРєСѓРјРµРЅС‚",            callback_data="act:work:doc"),
             InlineKeyboardButton("рџ“Љ РђРЅР°Р»РёС‚РёРєР°/СЃРІРѕРґРєР°",           callback_data="act:work:report")],
            [InlineKeyboardButton("рџ—‚ РџР»Р°РЅ/ToDo",                  callback_data="act:work:plan"),
             InlineKeyboardButton("рџ’Ў РРґРµРё/Р±СЂРёС„",                 callback_data="act:work:idea")],
            [
                InlineKeyboardButton("рџЋ¬ Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("рџЋЁ Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("рџ—Ј STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("рџ“ќ РЎРІРѕР±РѕРґРЅС‹Р№ Р·Р°РїСЂРѕСЃ", callback_data="act:free")],
            [InlineKeyboardButton("в¬…пёЏ РќР°Р·Р°Рґ", callback_data="mode:root")],
        ])

    if key == "fun":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("рџЋ­ РРґРµРё РґР»СЏ РґРѕСЃСѓРіР°",             callback_data="act:fun:ideas")],
            [InlineKeyboardButton("рџЋ¬ РЎС†РµРЅР°СЂРёР№ С€РѕСЂС‚Р°",              callback_data="act:fun:shorts")],
            [InlineKeyboardButton("рџЋ® РРіСЂС‹/РєРІРёР·",                   callback_data="act:fun:games")],
            [
                InlineKeyboardButton("рџЋ¬ Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("рџЋЁ Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("рџ—Ј STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("рџ“ќ РЎРІРѕР±РѕРґРЅС‹Р№ Р·Р°РїСЂРѕСЃ", callback_data="act:free")],
            [InlineKeyboardButton("в¬…пёЏ РќР°Р·Р°Рґ", callback_data="mode:root")],
        ])

    return modes_root_kb()

# РџРѕРєР°Р·Р°С‚СЊ РІС‹Р±СЂР°РЅРЅС‹Р№ СЂРµР¶РёРј (РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ Рё РґР»СЏ callback, Рё РґР»СЏ С‚РµРєСЃС‚Р°)
async def _send_mode_menu(update, context, key: str):
    text = _mode_desc(key)
    kb = _mode_kb(key)
    # Р•СЃР»Рё РїСЂРёС€Р»Рё РёР· callback вЂ” СЂРµРґР°РєС‚РёСЂСѓРµРј; РµСЃР»Рё С‚РµРєСЃС‚РѕРј вЂ” С€Р»С‘Рј РЅРѕРІС‹Рј СЃРѕРѕР±С‰РµРЅРёРµРј
    if getattr(update, "callback_query", None):
        q = update.callback_query
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        await q.answer()
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# РћР±СЂР°Р±РѕС‚С‡РёРє callback РїРѕ СЂРµР¶РёРјР°Рј
async def on_mode_cb(update, context):
    q = update.callback_query
    data = (q.data or "").strip()
    uid = q.from_user.id

    # РќР°РІРёРіР°С†РёСЏ
    if data == "mode:root":
        await q.edit_message_text(_modes_root_text(), reply_markup=modes_root_kb())
        await q.answer(); return

    if data.startswith("mode:"):
        _, key = data.split(":", 1)
        await _send_mode_menu(update, context, key)
        return

    # РЎРІРѕР±РѕРґРЅС‹Р№ РІРІРѕРґ РёР· РїРѕРґРјРµРЅСЋ
    if data == "act:free":
        await q.answer()
        await q.edit_message_text(
            "рџ“ќ РќР°РїРёС€РёС‚Рµ СЃРІРѕР±РѕРґРЅС‹Р№ Р·Р°РїСЂРѕСЃ РЅРёР¶Рµ С‚РµРєСЃС‚РѕРј РёР»Рё РіРѕР»РѕСЃРѕРј вЂ” СЏ РїРѕРґСЃС‚СЂРѕСЋСЃСЊ.",
            reply_markup=modes_root_kb(),
        )
        return

    # === РЈС‡С‘Р±Р°
    if data == "act:study:pdf_summary":
        await q.answer()
        _mode_track_set(uid, "pdf_summary")
        await q.edit_message_text(
            "рџ“љ РџСЂРёС€Р»РёС‚Рµ PDF/EPUB/DOCX/FB2/TXT вЂ” СЃРґРµР»Р°СЋ СЃС‚СЂСѓРєС‚СѓСЂРёСЂРѕРІР°РЅРЅС‹Р№ РєРѕРЅСЃРїРµРєС‚.\n"
            "РњРѕР¶РЅРѕ РІ РїРѕРґРїРёСЃРё СѓРєР°Р·Р°С‚СЊ С†РµР»СЊ (РєРѕСЂРѕС‚РєРѕ/РїРѕРґСЂРѕР±РЅРѕ, СЏР·С‹Рє Рё С‚.Рї.).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:explain":
        await q.answer()
        study_sub_set(uid, "explain")
        _mode_track_set(uid, "explain")
        await q.edit_message_text(
            "рџ”Ќ РќР°РїРёС€РёС‚Рµ С‚РµРјСѓ + СѓСЂРѕРІРµРЅСЊ (С€РєРѕР»Р°/РІСѓР·/РїСЂРѕС„Рё). Р‘СѓРґРµС‚ РѕР±СЉСЏСЃРЅРµРЅРёРµ СЃ РїСЂРёРјРµСЂР°РјРё.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:tasks":
        await q.answer()
        study_sub_set(uid, "tasks")
        _mode_track_set(uid, "tasks")
        await q.edit_message_text(
            "рџ§® РџСЂРёС€Р»РёС‚Рµ СѓСЃР»РѕРІРёРµ(СЏ) вЂ” СЂРµС€Сѓ РїРѕС€Р°РіРѕРІРѕ (С„РѕСЂРјСѓР»С‹, РїРѕСЏСЃРЅРµРЅРёСЏ, РёС‚РѕРі).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:essay":
        await q.answer()
        study_sub_set(uid, "essay")
        _mode_track_set(uid, "essay")
        await q.edit_message_text(
            "вњЌпёЏ РўРµРјР° + С‚СЂРµР±РѕРІР°РЅРёСЏ (РѕР±СЉС‘Рј/СЃС‚РёР»СЊ/СЏР·С‹Рє) вЂ” РїРѕРґРіРѕС‚РѕРІР»СЋ СЌСЃСЃРµ/СЂРµС„РµСЂР°С‚.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:exam_plan":
        await q.answer()
        study_sub_set(uid, "quiz")
        _mode_track_set(uid, "exam_plan")
        await q.edit_message_text(
            "рџ“ќ РЈРєР°Р¶РёС‚Рµ РїСЂРµРґРјРµС‚ Рё РґР°С‚Сѓ СЌРєР·Р°РјРµРЅР° вЂ” СЃРѕСЃС‚Р°РІР»СЋ РїР»Р°РЅ РїРѕРґРіРѕС‚РѕРІРєРё СЃ РІРµС…Р°РјРё.",
            reply_markup=_mode_kb("study"),
        )
        return

    # === Р Р°Р±РѕС‚Р°
    if data == "act:work:doc":
        await q.answer()
        _mode_track_set(uid, "work_doc")
        await q.edit_message_text(
            "рџ“„ Р§С‚Рѕ Р·Р° РґРѕРєСѓРјРµРЅС‚/Р°РґСЂРµСЃР°С‚/РєРѕРЅС‚РµРєСЃС‚? РЎС„РѕСЂРјРёСЂСѓСЋ С‡РµСЂРЅРѕРІРёРє РїРёСЃСЊРјР°/РґРѕРєСѓРјРµРЅС‚Р°.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:report":
        await q.answer()
        _mode_track_set(uid, "work_report")
        await q.edit_message_text(
            "рџ“Љ РџСЂРёС€Р»РёС‚Рµ С‚РµРєСЃС‚/С„Р°Р№Р»/СЃСЃС‹Р»РєСѓ вЂ” СЃРґРµР»Р°СЋ Р°РЅР°Р»РёС‚РёС‡РµСЃРєСѓСЋ РІС‹Р¶РёРјРєСѓ.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:plan":
        await q.answer()
        _mode_track_set(uid, "work_plan")
        await q.edit_message_text(
            "рџ—‚ РћРїРёС€РёС‚Рµ Р·Р°РґР°С‡Сѓ/СЃСЂРѕРєРё вЂ” СЃРѕР±РµСЂСѓ ToDo/РїР»Р°РЅ СЃРѕ СЃСЂРѕРєР°РјРё Рё РїСЂРёРѕСЂРёС‚РµС‚Р°РјРё.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:idea":
        await q.answer()
        _mode_track_set(uid, "work_idea")
        await q.edit_message_text(
            "рџ’Ў Р Р°СЃСЃРєР°Р¶РёС‚Рµ РїСЂРѕРґСѓРєС‚/Р¦Рђ/РєР°РЅР°Р»С‹ вЂ” РїРѕРґРіРѕС‚РѕРІР»СЋ Р±СЂРёС„/РёРґРµРё.",
            reply_markup=_mode_kb("work"),
        )
        return

    # === Р Р°Р·РІР»РµС‡РµРЅРёСЏ (РєР°Рє Р±С‹Р»Рѕ)
    if data == "act:fun:ideas":
        await q.answer()
        await q.edit_message_text(
            "рџ”Ґ Р’С‹Р±РµСЂРµРј С„РѕСЂРјР°С‚: РґРѕРј/СѓР»РёС†Р°/РіРѕСЂРѕРґ/РІ РїРѕРµР·РґРєРµ. РќР°РїРёС€РёС‚Рµ Р±СЋРґР¶РµС‚/РЅР°СЃС‚СЂРѕРµРЅРёРµ.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:shorts":
        await q.answer()
        await q.edit_message_text(
            "рџЋ¬ РўРµРјР°, РґР»РёС‚РµР»СЊРЅРѕСЃС‚СЊ (15вЂ“30 СЃРµРє), СЃС‚РёР»СЊ вЂ” СЃРґРµР»Р°СЋ СЃС†РµРЅР°СЂРёР№ С€РѕСЂС‚Р° + РїРѕРґСЃРєР°Р·РєРё РґР»СЏ РѕР·РІСѓС‡РєРё.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:games":
        await q.answer()
        await q.edit_message_text(
            "рџЋ® РўРµРјР°С‚РёРєР° РєРІРёР·Р°/РёРіСЂС‹? РЎРіРµРЅРµСЂРёСЂСѓСЋ Р±С‹СЃС‚СЂСѓСЋ РІРёРєС‚РѕСЂРёРЅСѓ РёР»Рё РјРёРЅРё-РёРіСЂСѓ РІ С‡Р°С‚Рµ.",
            reply_markup=_mode_kb("fun"),
        )
        return

    # === РњРѕРґСѓР»Рё (РєР°Рє Р±С‹Р»Рѕ)
    if data == "act:open:runway":
        await q.answer()
        await q.edit_message_text(
            "рџЋ¬ РњРѕРґСѓР»СЊ Runway: РїСЂРёС€Р»РёС‚Рµ РёРґРµСЋ/СЂРµС„РµСЂРµРЅСЃ вЂ” РїРѕРґРіРѕС‚РѕРІР»СЋ РїСЂРѕРјРїС‚ Рё Р±СЋРґР¶РµС‚.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:mj":
        await q.answer()
        await q.edit_message_text(
            "рџЋЁ РњРѕРґСѓР»СЊ Midjourney: РѕРїРёС€РёС‚Рµ РєР°СЂС‚РёРЅРєСѓ вЂ” РїСЂРµРґР»РѕР¶Сѓ 3 РїСЂРѕРјРїС‚Р° Рё СЃРµС‚РєСѓ СЃС‚РёР»РµР№.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:voice":
        await q.answer()
        await q.edit_message_text(
            "рџ—Ј Р“РѕР»РѕСЃ: /voice_on вЂ” РѕР·РІСѓС‡РєР° РѕС‚РІРµС‚РѕРІ, /voice_off вЂ” РІС‹РєР»СЋС‡РёС‚СЊ. "
            "РњРѕР¶РµС‚Рµ РїСЂРёСЃР»Р°С‚СЊ РіРѕР»РѕСЃРѕРІРѕРµ вЂ” СЂР°СЃРїРѕР·РЅР°СЋ Рё РѕС‚РІРµС‡Сѓ.",
            reply_markup=modes_root_kb(),
        )
        return

    await q.answer()

# Fallback вЂ” РµСЃР»Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅР°Р¶РјС‘С‚ В«РЈС‡С‘Р±Р°/Р Р°Р±РѕС‚Р°/Р Р°Р·РІР»РµС‡РµРЅРёСЏВ» РѕР±С‹С‡РЅРѕР№ РєРЅРѕРїРєРѕР№/С‚РµРєСЃС‚РѕРј
async def on_mode_text(update, context):
    text = (update.effective_message.text or "").strip().lower()
    mapping = {
        "СѓС‡С‘Р±Р°": "study", "СѓС‡РµР±Р°": "study",
        "СЂР°Р±РѕС‚Р°": "work",
        "СЂР°Р·РІР»РµС‡РµРЅРёСЏ": "fun", "СЂР°Р·РІР»РµС‡РµРЅРёРµ": "fun",
    }
    key = mapping.get(text)
    if key:
        await _send_mode_menu(update, context, key)
        
def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("рџЋ“ РЈС‡С‘Р±Р°"), KeyboardButton("рџ’ј Р Р°Р±РѕС‚Р°"), KeyboardButton("рџ”Ґ Р Р°Р·РІР»РµС‡РµРЅРёСЏ")],
            [KeyboardButton("рџ§  Р”РІРёР¶РєРё"), KeyboardButton("в­ђ РџРѕРґРїРёСЃРєР° В· РџРѕРјРѕС‰СЊ"), KeyboardButton("рџ§ѕ Р‘Р°Р»Р°РЅСЃ")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
        input_field_placeholder="Р’С‹Р±РµСЂРёС‚Рµ СЂРµР¶РёРј РёР»Рё РЅР°РїРёС€РёС‚Рµ Р·Р°РїСЂРѕСЃвЂ¦",
    )

main_kb = main_keyboard()

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ /start в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        START_TEXT,
        reply_markup=main_kb,
        disable_web_page_preview=True,
    )

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ СЃРѕС…СЂР°РЅРµРЅРёРµ РІС‹Р±СЂР°РЅРЅРѕРіРѕ СЂРµР¶РёРјР°/РїРѕРґСЂРµР¶РёРјР° (SQLite kv) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
def _mode_set(user_id: int, mode: str):
    kv_set(f"mode:{user_id}", mode)

def _mode_get(user_id: int) -> str:
    return (kv_get(f"mode:{user_id}", "none") or "none")

def _mode_track_set(user_id: int, track: str):
    kv_set(f"mode_track:{user_id}", track)

def _mode_track_get(user_id: int) -> str:
    return kv_get(f"mode_track:{user_id}", "") or ""


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РџРѕРґРјРµРЅСЋ СЂРµР¶РёРјРѕРІ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
def _school_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("рџ”Ћ РћР±СЉСЏСЃРЅРµРЅРёРµ",          callback_data="school:explain"),
         InlineKeyboardButton("рџ§® Р—Р°РґР°С‡Рё",              callback_data="school:tasks")],
        [InlineKeyboardButton("вњЌпёЏ Р­СЃСЃРµ/СЂРµС„РµСЂР°С‚/РґРѕРєР»Р°Рґ", callback_data="school:essay"),
         InlineKeyboardButton("рџ“ќ Р­РєР·Р°РјРµРЅ/РєРІРёР·",        callback_data="school:quiz")],
    ])

def _work_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("рџ“§ РџРёСЃСЊРјРѕ/РґРѕРєСѓРјРµРЅС‚",  callback_data="work:doc"),
         InlineKeyboardButton("рџ“Љ РђРЅР°Р»РёС‚РёРєР°/СЃРІРѕРґРєР°", callback_data="work:report")],
        [InlineKeyboardButton("рџ—‚ РџР»Р°РЅ/ToDo",        callback_data="work:plan"),
         InlineKeyboardButton("рџ’Ў РРґРµРё/Р±СЂРёС„",       callback_data="work:idea")],
    ])

def _fun_quick_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("РћР¶РёРІРёС‚СЊ С„РѕС‚Рѕ (Р°РЅРёРјР°С†РёСЏ)", callback_data="fun:revive")],
        [InlineKeyboardButton("РљР»РёРї РёР· С‚РµРєСЃС‚Р°/РіРѕР»РѕСЃР°",    callback_data="fun:clip")],
        [InlineKeyboardButton("РЎРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ РёР·РѕР±СЂР°Р¶РµРЅРёРµ /img", callback_data="fun:img")],
        [InlineKeyboardButton("Р Р°СЃРєР°РґСЂРѕРІРєР° РїРѕРґ Reels",    callback_data="fun:storyboard")],
    ])

def _fun_kb():
    # РѕСЃС‚Р°РІРёРј Рё СЃС‚Р°СЂРѕРµ РїРѕРґРјРµРЅСЋ вЂ” РЅРµ РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ СЃРµР№С‡Р°СЃ
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("рџ–ј Р¤РѕС‚Рѕ-РјР°СЃС‚РµСЂСЃРєР°СЏ", callback_data="fun:photo"),
         InlineKeyboardButton("рџЋ¬ Р’РёРґРµРѕ-РёРґРµРё",      callback_data="fun:video")],
        [InlineKeyboardButton("рџЋІ РљРІРёР·С‹/РёРіСЂС‹",      callback_data="fun:quiz"),
         InlineKeyboardButton("рџ† РњРµРјС‹/С€СѓС‚РєРё",      callback_data="fun:meme")],
    ])


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РљРѕРјР°РЅРґС‹/РєРЅРѕРїРєРё СЂРµР¶РёРјРѕРІ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def cmd_mode_school(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _mode_set(update.effective_user.id, "РЈС‡С‘Р±Р°")
    _mode_track_set(update.effective_user.id, "")
    # РїРѕРєР°Р·С‹РІР°РµРј РќРћР’РћР• РїРѕРґРјРµРЅСЋ В«РЈС‡С‘Р±Р°В»
    await _send_mode_menu(update, context, "study")

async def cmd_mode_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _mode_set(update.effective_user.id, "Р Р°Р±РѕС‚Р°")
    _mode_track_set(update.effective_user.id, "")
    # РїРѕРєР°Р·С‹РІР°РµРј РќРћР’РћР• РїРѕРґРјРµРЅСЋ В«Р Р°Р±РѕС‚Р°В»
    await _send_mode_menu(update, context, "work")

async def cmd_mode_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _mode_set(update.effective_user.id, "Р Р°Р·РІР»РµС‡РµРЅРёСЏ")
    _mode_track_set(update.effective_user.id, "")
    await update.effective_message.reply_text(
        "рџ”Ґ Р Р°Р·РІР»РµС‡РµРЅРёСЏ вЂ” Р±С‹СЃС‚СЂС‹Рµ РґРµР№СЃС‚РІРёСЏ:",
        reply_markup=_fun_quick_kb()
    )


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РљРѕР»Р»Р±СЌРєРё РїРѕРґСЂРµР¶РёРјРѕРІ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def on_cb_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "")
    try:
        if any(data.startswith(p) for p in ("school:", "work:", "fun:")):
            # Р±Р°Р·РѕРІС‹Р№ С‚СЂРµРєРёРЅРі СЃС‚Р°СЂС‹С… РІРµС‚РѕРє (photo/video/quiz/meme)
            if data in ("fun:revive","fun:clip","fun:img","fun:storyboard"):
                # СЌС‚Рё РѕР±СЂР°Р±Р°С‚С‹РІР°СЋС‚СЃСЏ РѕС‚РґРµР»СЊРЅС‹Рј С…РµРЅРґР»РµСЂРѕРј on_cb_fun
                return
            _, track = data.split(":", 1)
            _mode_track_set(update.effective_user.id, track)
            mode = _mode_get(update.effective_user.id)
            await q.edit_message_text(f"{mode} в†’ {track}. РќР°РїРёС€РёС‚Рµ Р·Р°РґР°РЅРёРµ/С‚РµРјСѓ вЂ” СЃРґРµР»Р°СЋ.")
            return
    finally:
        with contextlib.suppress(Exception):
            await q.answer()

# Р±С‹СЃС‚СЂС‹Рµ РґРµР№СЃС‚РІРёСЏ В«Р Р°Р·РІР»РµС‡РµРЅРёСЏВ»
async def on_cb_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "fun:img":
        return await q.edit_message_text("РџСЂРёС€Р»Рё РїСЂРѕРјРїС‚ РёР»Рё РёСЃРїРѕР»СЊР·СѓР№ РєРѕРјР°РЅРґСѓ /img <РѕРїРёСЃР°РЅРёРµ> вЂ” СЃРіРµРЅРµСЂРёСЂСѓСЋ РёР·РѕР±СЂР°Р¶РµРЅРёРµ.")
    if data == "fun:revive":
        return await q.edit_message_text("Р—Р°РіСЂСѓР·Рё С„РѕС‚Рѕ (РєР°Рє РєР°СЂС‚РёРЅРєСѓ) Рё РЅР°РїРёС€Рё, С‡С‚Рѕ РѕР¶РёРІРёС‚СЊ/РєР°Рє РґРІРёРіР°С‚СЊСЃСЏ. РЎРґРµР»Р°СЋ Р°РЅРёРјР°С†РёСЋ.")
    if data == "fun:clip":
        return await q.edit_message_text("РџСЂРёС€Р»Рё С‚РµРєСЃС‚/РіРѕР»РѕСЃ Рё С„РѕСЂРјР°С‚ (Reels/Shorts), РјСѓР·С‹РєСѓ/СЃС‚РёР»СЊ вЂ” СЃРѕР±РµСЂСѓ РєР»РёРї (Luma/Runway).")
    if data == "fun:storyboard":
        return await q.edit_message_text("РџСЂРёС€Р»Рё С„РѕС‚Рѕ РёР»Рё РѕРїРёС€Рё РёРґРµСЋ СЂРѕР»РёРєР° вЂ” РІРµСЂРЅСѓ СЂР°СЃРєР°РґСЂРѕРІРєСѓ РїРѕРґ Reels СЃ С‚Р°Р№Рј-РєРѕРґР°РјРё.")

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РЎС‚Р°СЂС‚ / Р”РІРёР¶РєРё / РџРѕРјРѕС‰СЊ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_url = kv_get("welcome_url", BANNER_URL)
    if welcome_url:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_photo(welcome_url)
    await update.effective_message.reply_text(START_TEXT, reply_markup=main_kb, disable_web_page_preview=True)

async def cmd_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Р’С‹Р±РµСЂРёС‚Рµ РґРІРёР¶РѕРє:", reply_markup=engines_kb())

async def cmd_subs_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("РћС‚РєСЂС‹С‚СЊ С‚Р°СЂРёС„С‹ (WebApp)", web_app=WebAppInfo(url=TARIFF_URL))],
        [InlineKeyboardButton("РћС„РѕСЂРјРёС‚СЊ PRO РЅР° РјРµСЃСЏС† (Р®Kassa)", callback_data="buyinv:pro:1")],
    ])
    await update.effective_message.reply_text("в­ђ РўР°СЂРёС„С‹ Рё РїРѕРјРѕС‰СЊ.\n\n" + HELP_TEXT, reply_markup=kb, disable_web_page_preview=True)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, disable_web_page_preview=True)

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(EXAMPLES_TEXT, disable_web_page_preview=True)


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Р”РёР°РіРЅРѕСЃС‚РёРєР°/Р»РёРјРёС‚С‹ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def cmd_diag_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tier = get_subscription_tier(user_id)
    lim = _limits_for(user_id)
    row = _usage_row(user_id, _today_ymd())
    lines = [
        f"рџ‘¤ РўР°СЂРёС„: {tier}",
        f"вЂў РўРµРєСЃС‚С‹ СЃРµРіРѕРґРЅСЏ: {row['text_count']} / {lim['text_per_day']}",
        f"вЂў Luma $: {row['luma_usd']:.2f} / {lim['luma_budget_usd']:.2f}",
        f"вЂў Runway $: {row['runway_usd']:.2f} / {lim['runway_budget_usd']:.2f}",
        f"вЂў Images $: {row['img_usd']:.2f} / {lim['img_budget_usd']:.2f}",
    ]
    await update.effective_message.reply_text("\n".join(lines))


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Capability Q&A в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
_CAP_PDF   = re.compile(r"(pdf|РґРѕРєСѓРјРµРЅС‚(С‹)?|С„Р°Р№Р»(С‹)?)", re.I)
_CAP_EBOOK = re.compile(r"(ebook|e-?book|СЌР»РµРєС‚СЂРѕРЅРЅ(Р°СЏ|С‹Рµ)\s+РєРЅРёРі|epub|fb2|docx|txt|mobi|azw)", re.I)
_CAP_AUDIO = re.compile(r"(Р°СѓРґРёРѕ ?РєРЅРёРі|audiobook|audio ?book|mp3|m4a|wav|ogg|webm|voice)", re.I)
_CAP_IMAGE = re.compile(r"(РёР·РѕР±СЂР°Р¶РµРЅ|РєР°СЂС‚РёРЅРє|С„РѕС‚Рѕ|image|picture|img)", re.I)
_CAP_VIDEO = re.compile(r"(РІРёРґРµРѕ|СЂРѕР»РёРє|shorts?|reels?|clip)", re.I)

def capability_answer(text: str) -> str | None:
    tl = (text or "").strip().lower()
    if not tl:
        return None
    if (_CAP_PDF.search(tl) or _CAP_EBOOK.search(tl)) and re.search(
        r"(С‡РёС‚Р°(РµС€СЊ|РµС‚Рµ)|С‡РёС‚Р°С‚СЊ|Р°РЅР°Р»РёР·РёСЂСѓ(РµС€СЊ|РµС‚Рµ)|Р°РЅР°Р»РёР·РёСЂРѕРІР°С‚СЊ|СЂР°СЃРїРѕР·РЅР°(РµС€СЊ|РµС‚Рµ)|СЂР°СЃРїРѕР·РЅР°РІР°С‚СЊ)", tl
    ):
        return (
            "Р”Р°. РџСЂРёС€Р»РёС‚Рµ С„Р°Р№Р» вЂ” РёР·РІР»РµРєСѓ С‚РµРєСЃС‚ Рё СЃРґРµР»Р°СЋ РєРѕРЅСЃРїРµРєС‚/РѕС‚РІРµС‚ РїРѕ РІР°С€РµР№ С†РµР»Рё.\n"
            "РџРѕРґРґРµСЂР¶РєР°: PDF, EPUB, DOCX, FB2, TXT (MOBI/AZW вЂ” РїРѕ РІРѕР·РјРѕР¶РЅРѕСЃС‚Рё)."
        )
    if (_CAP_AUDIO.search(tl) and re.search(r"(С‡РёС‚Р°|Р°РЅР°Р»РёР·|СЂР°СЃС€РёС„|С‚СЂР°РЅСЃРєСЂРёР±|РїРѕРЅРёРјР°|СЂР°СЃРїРѕР·РЅР°)", tl)) or "Р°СѓРґРёРѕ" in tl:
        return (
            "Р”Р°. РџСЂРёС€Р»РёС‚Рµ Р°СѓРґРёРѕ (voice/audio/РґРѕРєСѓРјРµРЅС‚): OGG/MP3/M4A/WAV/WEBM. "
            "Р Р°СЃРїРѕР·РЅР°СЋ СЂРµС‡СЊ (Deepgram/Whisper) Рё СЃРґРµР»Р°СЋ РєРѕРЅСЃРїРµРєС‚, С‚РµР·РёСЃС‹, С‚Р°Р№Рј-РєРѕРґС‹, Q&A."
        )
    if _CAP_IMAGE.search(tl) and re.search(r"(С‡РёС‚Р°|Р°РЅР°Р»РёР·|РїРѕРЅРёРјР°|РІРёРґРёС€СЊ)", tl):
        return "Р”Р°. РџСЂРёС€Р»РёС‚Рµ С„РѕС‚Рѕ/РєР°СЂС‚РёРЅРєСѓ СЃ РїРѕРґРїРёСЃСЊСЋ вЂ” РѕРїРёС€Сѓ СЃРѕРґРµСЂР¶РёРјРѕРµ, С‚РµРєСЃС‚ РЅР° РёР·РѕР±СЂР°Р¶РµРЅРёРё, РґРµС‚Р°Р»Рё."
    if _CAP_IMAGE.search(tl) and re.search(r"(РјРѕР¶(РµС€СЊ|РµС‚Рµ)|СЃРѕР·РґР°(РІР°)?С‚|РґРµР»Р°(С‚СЊ)?|РіРµРЅРµСЂРёСЂ)", tl):
        return "Р”Р°, РјРѕРіСѓ СЃРѕР·РґР°РІР°С‚СЊ РёР·РѕР±СЂР°Р¶РµРЅРёСЏ. Р—Р°РїСѓСЃС‚РёС‚Рµ: /img <РѕРїРёСЃР°РЅРёРµ>."
    if _CAP_VIDEO.search(tl) and re.search(r"(РјРѕР¶(РµС€СЊ|РµС‚Рµ)|СЃРѕР·РґР°(РІР°)?С‚|РґРµР»Р°(С‚СЊ)?|СЃРіРµРЅРµСЂРёСЂ)", tl):
        return "Р”Р°, РјРѕРіСѓ Р·Р°РїСѓСЃС‚РёС‚СЊ РіРµРЅРµСЂР°С†РёСЋ РєРѕСЂРѕС‚РєРёС… РІРёРґРµРѕ. РќР°РїРёС€РёС‚Рµ: В«СЃРґРµР»Р°Р№ РІРёРґРµРѕ вЂ¦ 9 СЃРµРєСѓРЅРґ 9:16В»."
    return None


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РњРѕРґС‹/РґРІРёР¶РєРё РґР»СЏ study в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
def _uk(user_id: int, name: str) -> str: return f"user:{user_id}:{name}"
def mode_set(user_id: int, mode: str):     kv_set(_uk(user_id, "mode"), (mode or "default"))
def mode_get(user_id: int) -> str:         return kv_get(_uk(user_id, "mode"), "default") or "default"
def engine_set(user_id: int, engine: str): kv_set(_uk(user_id, "engine"), (engine or "gpt"))
def engine_get(user_id: int) -> str:       return kv_get(_uk(user_id, "engine"), "gpt") or "gpt"
def study_sub_set(user_id: int, sub: str): kv_set(_uk(user_id, "study_sub"), (sub or "explain"))
def study_sub_get(user_id: int) -> str:    return kv_get(_uk(user_id, "study_sub"), "explain") or "explain"

def modes_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("рџЋ“ РЈС‡С‘Р±Р°", callback_data="mode:set:study"),
         InlineKeyboardButton("рџ–ј Р¤РѕС‚Рѕ",  callback_data="mode:set:photo")],
        [InlineKeyboardButton("рџ“„ Р”РѕРєСѓРјРµРЅС‚С‹", callback_data="mode:set:docs"),
         InlineKeyboardButton("рџЋ™ Р“РѕР»РѕСЃ",     callback_data="mode:set:voice")],
        [InlineKeyboardButton("рџ§  Р”РІРёР¶РєРё", callback_data="mode:engines")]
    ])

def study_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("рџ”Ќ РћР±СЉСЏСЃРЅРµРЅРёРµ",          callback_data="study:set:explain"),
         InlineKeyboardButton("рџ§® Р—Р°РґР°С‡Рё",              callback_data="study:set:tasks")],
        [InlineKeyboardButton("вњЌпёЏ Р­СЃСЃРµ/СЂРµС„РµСЂР°С‚/РґРѕРєР»Р°Рґ", callback_data="study:set:essay")],
        [InlineKeyboardButton("рџ“ќ Р­РєР·Р°РјРµРЅ/РєРІРёР·",        callback_data="study:set:quiz")]
    ])

async def study_process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    sub = study_sub_get(update.effective_user.id)
    if sub == "explain":
        prompt = f"РћР±СЉСЏСЃРЅРё РїСЂРѕСЃС‚С‹РјРё СЃР»РѕРІР°РјРё, СЃ 2вЂ“3 РїСЂРёРјРµСЂР°РјРё Рё РјРёРЅРё-РёС‚РѕРіРѕРј:\n\n{text}"
    elif sub == "tasks":
        prompt = ("Р РµС€Рё Р·Р°РґР°С‡Сѓ(Рё) РїРѕС€Р°РіРѕРІРѕ: С„РѕСЂРјСѓР»С‹, РїРѕСЏСЃРЅРµРЅРёСЏ, РёС‚РѕРіРѕРІС‹Р№ РѕС‚РІРµС‚. "
                  "Р•СЃР»Рё РЅРµ С…РІР°С‚Р°РµС‚ РґР°РЅРЅС‹С… вЂ” СѓС‚РѕС‡РЅСЏСЋС‰РёРµ РІРѕРїСЂРѕСЃС‹ РІ РєРѕРЅС†Рµ.\n\n" + text)
    elif sub == "essay":
        prompt = ("РќР°РїРёС€Рё СЃС‚СЂСѓРєС‚СѓСЂРёСЂРѕРІР°РЅРЅС‹Р№ С‚РµРєСЃС‚ 400вЂ“600 СЃР»РѕРІ (СЌСЃСЃРµ/СЂРµС„РµСЂР°С‚/РґРѕРєР»Р°Рґ): "
                  "РІРІРµРґРµРЅРёРµ, 3вЂ“5 С‚РµР·РёСЃРѕРІ СЃ С„Р°РєС‚Р°РјРё, РІС‹РІРѕРґ, СЃРїРёСЃРѕРє РёР· 3 РёСЃС‚РѕС‡РЅРёРєРѕРІ (РµСЃР»Рё СѓРјРµСЃС‚РЅРѕ).\n\nРўРµРјР°:\n" + text)
    elif sub == "quiz":
        prompt = ("РЎРѕСЃС‚Р°РІСЊ РјРёРЅРё-РєРІРёР· РїРѕ С‚РµРјРµ: 10 РІРѕРїСЂРѕСЃРѕРІ, Сѓ РєР°Р¶РґРѕРіРѕ 4 РІР°СЂРёР°РЅС‚Р° AвЂ“D; "
                  "РІ РєРѕРЅС†Рµ РґР°Р№ РєР»СЋС‡ РѕС‚РІРµС‚РѕРІ (РЅРѕРјРµСЂв†’Р±СѓРєРІР°). РўРµРјР°:\n\n" + text)
    else:
        prompt = text
    ans = await ask_openai_text(prompt)
    await update.effective_message.reply_text(ans)
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РљРЅРѕРїРєР° РїСЂРёРІРµС‚СЃС‚РІРµРЅРЅРѕР№ РєР°СЂС‚РёРЅРєРё в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def cmd_set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("РљРѕРјР°РЅРґР° РґРѕСЃС‚СѓРїРЅР° С‚РѕР»СЊРєРѕ РІР»Р°РґРµР»СЊС†Сѓ.")
        return
    if not context.args:
        await update.effective_message.reply_text("Р¤РѕСЂРјР°С‚: /set_welcome <url_РєР°СЂС‚РёРЅРєРё>")
        return
    url = " ".join(context.args).strip()
    kv_set("welcome_url", url)
    await update.effective_message.reply_text("РљР°СЂС‚РёРЅРєР° РїСЂРёРІРµС‚СЃС‚РІРёСЏ РѕР±РЅРѕРІР»РµРЅР°. РћС‚РїСЂР°РІСЊС‚Рµ /start РґР»СЏ РїСЂРѕРІРµСЂРєРё.")

async def cmd_show_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = kv_get("welcome_url", BANNER_URL)
    if url:
        await update.effective_message.reply_photo(url, caption="РўРµРєСѓС‰Р°СЏ РєР°СЂС‚РёРЅРєР° РїСЂРёРІРµС‚СЃС‚РІРёСЏ")
    else:
        await update.effective_message.reply_text("РљР°СЂС‚РёРЅРєР° РїСЂРёРІРµС‚СЃС‚РІРёСЏ РЅРµ Р·Р°РґР°РЅР°.")


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Р‘Р°Р»Р°РЅСЃ / РїРѕРїРѕР»РЅРµРЅРёРµ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    w = _wallet_get(user_id)
    total = _wallet_total_get(user_id)
    row = _usage_row(user_id)
    lim = _limits_for(user_id)
    msg = (
        "рџ§ѕ РљРѕС€РµР»С‘Рє:\n"
        f"вЂў Р•РґРёРЅС‹Р№ Р±Р°Р»Р°РЅСЃ: ${total:.2f}\n"
        "  (СЂР°СЃС…РѕРґСѓРµС‚СЃСЏ РЅР° РїРµСЂРµСЂР°СЃС…РѕРґ РїРѕ Luma/Runway/Images)\n\n"
        "Р”РµС‚Р°Р»РёР·Р°С†РёСЏ СЃРµРіРѕРґРЅСЏ / Р»РёРјРёС‚С‹ С‚Р°СЂРёС„Р°:\n"
        f"вЂў Luma: ${row['luma_usd']:.2f} / ${lim['luma_budget_usd']:.2f}\n"
        f"вЂў Runway: ${row['runway_usd']:.2f} / ${lim['runway_budget_usd']:.2f}\n"
        f"вЂў Images: ${row['img_usd']:.2f} / ${lim['img_budget_usd']:.2f}\n"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("вћ• РџРѕРїРѕР»РЅРёС‚СЊ Р±Р°Р»Р°РЅСЃ", callback_data="topup")]])
    await update.effective_message.reply_text(msg, reply_markup=kb)

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РџРѕРґРїРёСЃРєР° / С‚Р°СЂРёС„С‹ вЂ” UI Рё РѕРїР»Р°С‚С‹ (PATCH) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
# Р—Р°РІРёСЃРёРјРѕСЃС‚Рё РѕРєСЂСѓР¶РµРЅРёСЏ:
#  - YOOKASSA_PROVIDER_TOKEN  (РїР»Р°С‚С‘Р¶РЅС‹Р№ С‚РѕРєРµРЅ Telegram Payments РѕС‚ Р®Kassa)
#  - YOOKASSA_CURRENCY        (РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ "RUB")
#  - CRYPTO_PAY_API_TOKEN     (https://pay.crypt.bot вЂ” С‚РѕРєРµРЅ РїСЂРѕРґР°РІС†Р°)
#  - CRYPTO_ASSET             (РЅР°РїСЂРёРјРµСЂ "USDT", РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ "USDT")
#  - PRICE_START_RUB, PRICE_PRO_RUB, PRICE_ULT_RUB  (С†РµР»РѕРµ С‡РёСЃР»Рѕ, в‚Ѕ)
#  - PRICE_START_USD, PRICE_PRO_USD, PRICE_ULT_USD  (С‡РёСЃР»Рѕ СЃ С‚РѕС‡РєРѕР№, $)
#
# РҐСЂР°РЅРёР»РёС‰Рµ РїРѕРґРїРёСЃРєРё Рё РєРѕС€РµР»СЊРєР° РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РЅР° kv_*:
#   sub:tier:{user_id}   -> "start" | "pro" | "ultimate"
#   sub:until:{user_id}  -> ISO-СЃС‚СЂРѕРєР° РґР°С‚С‹ РѕРєРѕРЅС‡Р°РЅРёСЏ
#   wallet:usd:{user_id} -> Р±Р°Р»Р°РЅСЃ РІ USD (float)

YOOKASSA_PROVIDER_TOKEN = os.environ.get("YOOKASSA_PROVIDER_TOKEN", "").strip()
YOOKASSA_CURRENCY = (os.environ.get("YOOKASSA_CURRENCY") or "RUB").upper()

CRYPTO_PAY_API_TOKEN = os.environ.get("CRYPTO_PAY_API_TOKEN", "").strip()
CRYPTO_ASSET = (os.environ.get("CRYPTO_ASSET") or "USDT").upper()

# === COMPAT with existing vars/DB in your main.py ===
# 1) Р®Kassa: РµСЃР»Рё СѓР¶Рµ РµСЃС‚СЊ PROVIDER_TOKEN (РёР· PROVIDER_TOKEN_YOOKASSA), РёСЃРїРѕР»СЊР·СѓРµРј РµРіРѕ:
if not YOOKASSA_PROVIDER_TOKEN and 'PROVIDER_TOKEN' in globals() and PROVIDER_TOKEN:
    YOOKASSA_PROVIDER_TOKEN = PROVIDER_TOKEN

# 2) РљРѕС€РµР»С‘Рє: РёСЃРїРѕР»СЊР·СѓРµРј С‚РІРѕР№ РµРґРёРЅС‹Р№ USD-РєРѕС€РµР»С‘Рє (wallet table) РІРјРµСЃС‚Рѕ kv:
def _user_balance_get(user_id: int) -> float:
    return _wallet_total_get(user_id)

def _user_balance_add(user_id: int, delta: float) -> float:
    if delta > 0:
        _wallet_total_add(user_id, delta)
    elif delta < 0:
        _wallet_total_take(user_id, -delta)
    return _wallet_total_get(user_id)

def _user_balance_debit(user_id: int, amount: float) -> bool:
    return _wallet_total_take(user_id, amount)

# 3) РџРѕРґРїРёСЃРєР°: Р°РєС‚РёРІРёСЂСѓРµРј С‡РµСЂРµР· С‚РІРѕРё С„СѓРЅРєС†РёРё СЃ Р‘Р”, Р° РЅРµ kv:
def _sub_activate(user_id: int, tier_key: str, months: int = 1) -> str:
    dt = activate_subscription_with_tier(user_id, tier_key, months)
    return dt.isoformat()

def _sub_info_text(user_id: int) -> str:
    tier = get_subscription_tier(user_id)
    dt = get_subscription_until(user_id)
    human_until = dt.strftime("%d.%m.%Y") if dt else ""
    bal = _user_balance_get(user_id)
    line_until = f"\nвЏі РђРєС‚РёРІРЅР° РґРѕ: {human_until}" if tier != "free" and human_until else ""
    return f"рџ§ѕ РўРµРєСѓС‰Р°СЏ РїРѕРґРїРёСЃРєР°: {tier.upper() if tier!='free' else 'РЅРµС‚'}{line_until}\nрџ’µ Р‘Р°Р»Р°РЅСЃ: ${bal:.2f}"

# Р¦РµРЅС‹ вЂ” РёР· env СЃ РѕСЃРјС‹СЃР»РµРЅРЅС‹РјРё РґРµС„РѕР»С‚Р°РјРё
PRICE_START_RUB = int(os.environ.get("PRICE_START_RUB", "499"))
PRICE_PRO_RUB = int(os.environ.get("PRICE_PRO_RUB", "1299"))
PRICE_ULT_RUB = int(os.environ.get("PRICE_ULT_RUB", "2990"))

PRICE_START_USD = _env_float("PRICE_START_USD", 4.99)
PRICE_PRO_USD   = _env_float("PRICE_PRO_USD", 12.99)
PRICE_ULT_USD   = _env_float("PRICE_ULT_USD", 29.90)

SUBS_TIERS = {
    "start": {
        "title": "START",
        "rub": PRICE_START_RUB,
        "usd": PRICE_START_USD,
        "features": [
            "рџ’¬ GPT-С‡Р°С‚ Рё РґРѕРєСѓРјРµРЅС‚С‹ (Р±Р°Р·РѕРІС‹Рµ Р»РёРјРёС‚С‹)",
            "рџ–ј Р¤РѕС‚Рѕ-РјР°СЃС‚РµСЂСЃРєР°СЏ: С„РѕРЅ, Р»С‘РіРєР°СЏ РґРѕСЂРёСЃРѕРІРєР°",
            "рџЋ§ РћР·РІСѓС‡РєР° РѕС‚РІРµС‚РѕРІ (TTS)",
        ],
    },
    "pro": {
        "title": "PRO",
        "rub": PRICE_PRO_RUB,
        "usd": PRICE_PRO_USD,
        "features": [
            "рџ“љ Р“Р»СѓР±РѕРєРёР№ СЂР°Р·Р±РѕСЂ PDF/DOCX/EPUB",
            "рџЋ¬ Reels/Shorts РїРѕ СЃРјС‹СЃР»Сѓ, РІРёРґРµРѕ РёР· С„РѕС‚Рѕ",
            "рџ–ј Outpaint Рё В«РѕР¶РёРІР»РµРЅРёРµВ» СЃС‚Р°СЂС‹С… С„РѕС‚Рѕ",
        ],
    },
    "ultimate": {
        "title": "ULTIMATE",
        "rub": PRICE_ULT_RUB,
        "usd": PRICE_ULT_USD,
        "features": [
            "рџљЂ Runway/Luma вЂ” РїСЂРµРјРёСѓРј-СЂРµРЅРґРµСЂС‹",
            "рџ§  Р Р°СЃС€РёСЂРµРЅРЅС‹Рµ Р»РёРјРёС‚С‹ Рё РїСЂРёРѕСЂРёС‚РµС‚РЅР°СЏ РѕС‡РµСЂРµРґСЊ",
            "рџ›  PRO-РёРЅСЃС‚СЂСѓРјРµРЅС‚С‹ (Р°СЂС…РёС‚РµРєС‚СѓСЂР°/РґРёР·Р°Р№РЅ)",
        ],
    },
}

def _money_fmt_rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " в‚Ѕ"

def _money_fmt_usd(v: float) -> str:
    return f"${v:.2f}"

def _user_balance_get(user_id: int) -> float:
    # РџС‹С‚Р°РµРјСЃСЏ РІР·СЏС‚СЊ РёР· С‚РІРѕРµРіРѕ РєРѕС€РµР»СЊРєР°, РµСЃР»Рё РµСЃС‚СЊ, РёРЅР°С‡Рµ вЂ” kv
    get_fn = _pick_first_defined("wallet_get_balance", "get_balance", "balance_get")
    if get_fn:
        try:
            return float(get_fn(user_id))
        except Exception:
            pass
    try:
        return float(kv_get(f"wallet:usd:{user_id}", "0") or 0)
    except Exception:
        return 0.0

def _user_balance_add(user_id: int, delta: float) -> float:
    set_fn = _pick_first_defined("wallet_change_balance", "wallet_add_delta")
    if set_fn:
        try:
            return float(set_fn(user_id, delta))
        except Exception:
            pass
    cur = _user_balance_get(user_id)
    newv = round(cur + float(delta), 4)
    kv_set(f"wallet:usd:{user_id}", str(newv))
    return newv

def _user_balance_debit(user_id: int, amount: float) -> bool:
    if amount <= 0:
        return True
    bal = _user_balance_get(user_id)
    if bal + 1e-9 < amount:
        return False
    _user_balance_add(user_id, -amount)
    return True

def _sub_activate(user_id: int, tier_key: str, months: int = 1) -> str:
    until = (datetime.now(timezone.utc) + timedelta(days=30 * months)).isoformat()
    kv_set(f"sub:tier:{user_id}", tier_key)
    kv_set(f"sub:until:{user_id}", until)
    return until

def _sub_info_text(user_id: int) -> str:
    tier = kv_get(f"sub:tier:{user_id}", "") or "РЅРµС‚"
    until = kv_get(f"sub:until:{user_id}", "")
    human_until = ""
    if until:
        try:
            d = datetime.fromisoformat(until)
            human_until = d.strftime("%d.%m.%Y")
        except Exception:
            human_until = until
    bal = _user_balance_get(user_id)
    line_until = f"\nвЏі РђРєС‚РёРІРЅР° РґРѕ: {human_until}" if tier != "РЅРµС‚" and human_until else ""
    return f"рџ§ѕ РўРµРєСѓС‰Р°СЏ РїРѕРґРїРёСЃРєР°: {tier.upper() if tier!='РЅРµС‚' else 'РЅРµС‚'}{line_until}\nрџ’µ Р‘Р°Р»Р°РЅСЃ: {_money_fmt_usd(bal)}"

def _plan_card_text(key: str) -> str:
    p = SUBS_TIERS[key]
    fs = "\n".join("вЂў " + f for f in p["features"])
    return (
        f"в­ђ РўР°СЂРёС„ {p['title']}\n"
        f"Р¦РµРЅР°: {_money_fmt_rub(p['rub'])} / {_money_fmt_usd(p['usd'])} РІ РјРµСЃ.\n\n"
        f"{fs}\n"
    )

def _plans_overview_text(user_id: int) -> str:
    parts = [
        "в­ђ РџРѕРґРїРёСЃРєР° Рё С‚Р°СЂРёС„С‹",
        "Р’С‹Р±РµСЂРё РїРѕРґС…РѕРґСЏС‰РёР№ СѓСЂРѕРІРµРЅСЊ вЂ” РґРѕСЃС‚СѓРї РѕС‚РєСЂРѕРµС‚СЃСЏ СЃСЂР°Р·Сѓ РїРѕСЃР»Рµ РѕРїР»Р°С‚С‹.",
        _sub_info_text(user_id),
        "вЂ” вЂ” вЂ”",
        _plan_card_text("start"),
        _plan_card_text("pro"),
        _plan_card_text("ultimate"),
        "Р’С‹Р±РµСЂРёС‚Рµ С‚Р°СЂРёС„ РєРЅРѕРїРєРѕР№ РЅРёР¶Рµ.",
    ]
    return "\n".join(parts)

def plans_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("в­ђ START",    callback_data="plan:start"),
            InlineKeyboardButton("рџљЂ PRO",      callback_data="plan:pro"),
            InlineKeyboardButton("рџ‘‘ ULTIMATE", callback_data="plan:ultimate"),
        ]
    ])

def plan_pay_kb(plan_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("рџ’і РћРїР»Р°С‚РёС‚СЊ вЂ” Р®Kassa", callback_data=f"pay:yookassa:{plan_key}"),
        ],
        [
            InlineKeyboardButton("рџ’  РћРїР»Р°С‚РёС‚СЊ вЂ” CryptoBot", callback_data=f"pay:cryptobot:{plan_key}"),
        ],
        [
            InlineKeyboardButton("рџ§ѕ РЎРїРёСЃР°С‚СЊ СЃ Р±Р°Р»Р°РЅСЃР°", callback_data=f"pay:balance:{plan_key}"),
        ],
        [
            InlineKeyboardButton("в¬…пёЏ Рљ С‚Р°СЂРёС„Р°Рј", callback_data="plan:root"),
        ]
    ])

# РљРЅРѕРїРєР° В«в­ђ РџРѕРґРїРёСЃРєР° В· РџРѕРјРѕС‰СЊВ»
async def on_btn_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = _plans_overview_text(user_id)
    await update.effective_chat.send_message(text, reply_markup=plans_root_kb())

# РћР±СЂР°Р±РѕС‚С‡РёРє РЅР°С€РёС… РєРѕР»Р±СЌРєРѕРІ РїРѕ РїРѕРґРїРёСЃРєРµ/РѕРїР»Р°С‚Р°Рј (Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°С‚СЊ Р”Рћ РѕР±С‰РµРіРѕ on_cb!)
async def on_cb_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    user_id = q.from_user.id
    chat_id = q.message.chat.id  # FIX: РєРѕСЂСЂРµРєС‚РЅРѕРµ РїРѕР»Рµ РІ PTB v21+

    # РќР°РІРёРіР°С†РёСЏ РјРµР¶РґСѓ С‚Р°СЂРёС„Р°РјРё
    if data.startswith("plan:"):
        _, arg = data.split(":", 1)
        if arg == "root":
            await q.edit_message_text(_plans_overview_text(user_id), reply_markup=plans_root_kb())
            await q.answer()
            return
        if arg in SUBS_TIERS:
            await q.edit_message_text(
                _plan_card_text(arg) + "\nР’С‹Р±РµСЂРёС‚Рµ СЃРїРѕСЃРѕР± РѕРїР»Р°С‚С‹:",
                reply_markup=plan_pay_kb(arg)
            )
            await q.answer()
            return

    # РџР»Р°С‚РµР¶Рё
    if data.startswith("pay:"):
        # Р±РµР·РѕРїР°СЃРЅС‹Р№ РїР°СЂСЃРёРЅРі
        try:
            _, method, plan_key = data.split(":", 2)
        except ValueError:
            await q.answer("РќРµРєРѕСЂСЂРµРєС‚РЅС‹Рµ РґР°РЅРЅС‹Рµ РєРЅРѕРїРєРё.", show_alert=True)
            return

        plan = SUBS_TIERS.get(plan_key)
        if not plan:
            await q.answer("РќРµРёР·РІРµСЃС‚РЅС‹Р№ С‚Р°СЂРёС„.", show_alert=True)
            return

        # Р®Kassa С‡РµСЂРµР· Telegram Payments
        if method == "yookassa":
            if not YOOKASSA_PROVIDER_TOKEN:
                await q.answer("Р®Kassa РЅРµ РїРѕРґРєР»СЋС‡РµРЅР° (РЅРµС‚ YOOKASSA_PROVIDER_TOKEN).", show_alert=True)
                return

            title = f"РџРѕРґРїРёСЃРєР° {plan['title']} вЂў 1 РјРµСЃСЏС†"
            desc = "Р”РѕСЃС‚СѓРї Рє С„СѓРЅРєС†РёСЏРј Р±РѕС‚Р° СЃРѕРіР»Р°СЃРЅРѕ РІС‹Р±СЂР°РЅРЅРѕРјСѓ С‚Р°СЂРёС„Сѓ. РџРѕРґРїРёСЃРєР° Р°РєС‚РёРІРёСЂСѓРµС‚СЃСЏ СЃСЂР°Р·Сѓ РїРѕСЃР»Рµ РѕРїР»Р°С‚С‹."
            payload = json.dumps({"tier": plan_key, "months": 1})

            # Telegram РѕР¶РёРґР°РµС‚ СЃСѓРјРјСѓ РІ РјРёРЅРѕСЂРЅС‹С… РµРґРёРЅРёС†Р°С… (РєРѕРїРµР№РєРё/С†РµРЅС‚С‹)
            if YOOKASSA_CURRENCY == "RUB":
                total_minor = int(round(float(plan["rub"]) * 100))
            else:
                total_minor = int(round(float(plan["usd"]) * 100))

            prices = [LabeledPrice(label=f"{plan['title']} 1 РјРµСЃ.", amount=total_minor)]
            await context.bot.send_invoice(
                chat_id=chat_id,
                title=title,
                description=desc,
                payload=payload,
                provider_token=YOOKASSA_PROVIDER_TOKEN,
                currency=YOOKASSA_CURRENCY,
                prices=prices,
                need_email=True,
                is_flexible=False,
            )
            await q.answer("РЎС‡С‘С‚ РІС‹СЃС‚Р°РІР»РµРЅ вњ…")
            return

        # CryptoBot (Crypto Pay API: СЃРѕР·РґР°С‘Рј РёРЅРІРѕР№СЃ Рё РѕС‚РґР°С‘Рј СЃСЃС‹Р»РєСѓ)
        if method == "cryptobot":  # FIX: РІС‹СЂРѕРІРЅРµРЅ РѕС‚СЃС‚СѓРї
            if not CRYPTO_PAY_API_TOKEN:
                await q.answer("CryptoBot РЅРµ РїРѕРґРєР»СЋС‡С‘РЅ (РЅРµС‚ CRYPTO_PAY_API_TOKEN).", show_alert=True)
                return
            try:
                amount = float(plan["usd"])
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post(
                        "https://pay.crypt.bot/api/createInvoice",
                        headers={"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN},
                        json={
                            "asset": CRYPTO_ASSET,
                            "amount": f"{amount:.2f}",
                            "description": f"Subscription {plan['title']} вЂў 1 month",
                            "allow_comments": False,
                            "allow_anonymous": True,
                        },
                    )
                    data = r.json()
                    if not data.get("ok"):
                        raise RuntimeError(str(data))
                    res = data["result"]
                    pay_url = res["pay_url"]
                    inv_id = str(res["invoice_id"])

                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("рџ’  РћРїР»Р°С‚РёС‚СЊ РІ CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("в¬…пёЏ Рљ С‚Р°СЂРёС„Сѓ", callback_data=f"plan:{plan_key}")],
                ])
                msg = await q.edit_message_text(
                    _plan_card_text(plan_key) + "\nРћС‚РєСЂРѕР№С‚Рµ СЃСЃС‹Р»РєСѓ РґР»СЏ РѕРїР»Р°С‚С‹:",
                    reply_markup=kb
                )
                # Р°РІС‚РѕРїСѓР» СЃС‚Р°С‚СѓСЃР° РёРјРµРЅРЅРѕ РґР»СЏ РџРћР”РџРРЎРљР
                context.application.create_task(_poll_crypto_sub_invoice(
                    context, msg.chat.id, msg.message_id, user_id, inv_id, plan_key, 1  # FIX: msg.chat.id
                ))
                await q.answer()
            except Exception as e:
                await q.answer("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕР·РґР°С‚СЊ СЃС‡С‘С‚ РІ CryptoBot.", show_alert=True)
                log.exception("CryptoBot invoice error: %s", e)
            return

        # РЎРїРёСЃР°РЅРёРµ СЃ РІРЅСѓС‚СЂРµРЅРЅРµРіРѕ Р±Р°Р»Р°РЅСЃР° (USD)
        if method == "balance":
            price_usd = float(plan["usd"])
            if not _user_balance_debit(user_id, price_usd):
                await q.answer("РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ СЃСЂРµРґСЃС‚РІ РЅР° РІРЅСѓС‚СЂРµРЅРЅРµРј Р±Р°Р»Р°РЅСЃРµ.", show_alert=True)
                return
            until = _sub_activate(user_id, plan_key, months=1)
            await q.edit_message_text(
                f"вњ… РџРѕРґРїРёСЃРєР° {plan['title']} Р°РєС‚РёРІРёСЂРѕРІР°РЅР° РґРѕ {until[:10]}.\n"
                f"рџ’µ РЎРїРёСЃР°РЅРѕ: {_money_fmt_usd(price_usd)}. "
                f"РўРµРєСѓС‰РёР№ Р±Р°Р»Р°РЅСЃ: {_money_fmt_usd(_user_balance_get(user_id))}",
                reply_markup=plans_root_kb(),
            )
            await q.answer()
            return

    # Р•СЃР»Рё РєРѕР»Р±СЌРє РЅРµ РЅР°С€ вЂ” РїСЂРѕРїСѓСЃРєР°РµРј РґР°Р»СЊС€Рµ
    await q.answer()
    return


# Р•СЃР»Рё Сѓ С‚РµР±СЏ СѓР¶Рµ РµСЃС‚СЊ on_precheckout / on_successful_payment вЂ” РѕСЃС‚Р°РІСЊ РёС….
# Р•СЃР»Рё РЅРµС‚, РјРѕР¶РµС€СЊ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ СЌС‚Рё РїСЂРѕСЃС‚С‹Рµ СЂРµР°Р»РёР·Р°С†РёРё:

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.pre_checkout_query.answer(ok=True)
    except Exception as e:
        log.exception("precheckout error: %s", e)

async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    РЈРЅРёРІРµСЂСЃР°Р»СЊРЅС‹Р№ РѕР±СЂР°Р±РѕС‚С‡РёРє Telegram Payments:
    - РџРѕРґРґРµСЂР¶РёРІР°РµС‚ payload РІ РґРІСѓС… С„РѕСЂРјР°С‚Р°С…:
        1) JSON: {"tier":"pro","months":1}
        2) РЎС‚СЂРѕРєР°: "sub:pro:1"
    - РРЅР°С‡Рµ С‚СЂР°РєС‚СѓРµС‚ РєР°Рє РїРѕРїРѕР»РЅРµРЅРёРµ РµРґРёРЅРѕРіРѕ USD-РєРѕС€РµР»СЊРєР°.
    """
    try:
        sp = update.message.successful_payment
        payload_raw = sp.invoice_payload or ""
        total_minor = sp.total_amount or 0
        rub = total_minor / 100.0
        uid = update.effective_user.id

        # 1) РџС‹С‚Р°РµРјСЃСЏ СЂР°СЃРїР°СЂСЃРёС‚СЊ JSON
        tier, months = None, None
        try:
            if payload_raw.strip().startswith("{"):
                obj = json.loads(payload_raw)
                tier = (obj.get("tier") or "").strip().lower() or None
                months = int(obj.get("months") or 1)
        except Exception:
            pass

        # 2) РџС‹С‚Р°РµРјСЃСЏ СЂР°СЃРїР°СЂСЃРёС‚СЊ СЃС‚СЂРѕРєРѕРІС‹Р№ С„РѕСЂРјР°С‚ "sub:tier:months"
        if not tier and payload_raw.startswith("sub:"):
            try:
                _, t, m = payload_raw.split(":", 2)
                tier = (t or "pro").strip().lower()
                months = int(m or 1)
            except Exception:
                tier, months = None, None

        if tier and months:
            until = activate_subscription_with_tier(uid, tier, months)
            await update.effective_message.reply_text(
                f"рџЋ‰ РћРїР»Р°С‚Р° РїСЂРѕС€Р»Р° СѓСЃРїРµС€РЅРѕ!\n"
                f"вњ… РџРѕРґРїРёСЃРєР° {tier.upper()} Р°РєС‚РёРІРёСЂРѕРІР°РЅР° РґРѕ {until.strftime('%Y-%m-%d')}."
            )
            return

        # РРЅР°С‡Рµ СЃС‡РёС‚Р°РµРј, С‡С‚Рѕ СЌС‚Рѕ РїРѕРїРѕР»РЅРµРЅРёРµ РєРѕС€РµР»СЊРєР° РІ СЂСѓР±Р»СЏС…
        usd = rub / max(1e-9, USD_RUB)
        _wallet_total_add(uid, usd)
        await update.effective_message.reply_text(
            f"рџ’і РџРѕРїРѕР»РЅРµРЅРёРµ: {rub:.0f} в‚Ѕ в‰€ ${usd:.2f} Р·Р°С‡РёСЃР»РµРЅРѕ РЅР° РµРґРёРЅС‹Р№ Р±Р°Р»Р°РЅСЃ."
        )

    except Exception as e:
        log.exception("successful_payment handler error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("вљ пёЏ РћС€РёР±РєР° РѕР±СЂР°Р±РѕС‚РєРё РїР»Р°С‚РµР¶Р°. Р•СЃР»Рё РґРµРЅСЊРіРё СЃРїРёСЃР°Р»РёСЃСЊ вЂ” РЅР°РїРёС€РёС‚Рµ РІ РїРѕРґРґРµСЂР¶РєСѓ.")
# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РљРѕРЅРµС† PATCH в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        
# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РљРѕРјР°РЅРґР° /img в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip() if context.args else ""
    if not prompt:
        await update.effective_message.reply_text("Р¤РѕСЂРјР°С‚: /img <РѕРїРёСЃР°РЅРёРµ>")
        return

    async def _go():
        await _do_img_generate(update, context, prompt)

    user_id = update.effective_user.id
    await _try_pay_then_do(
        update, context, user_id,
        "img", IMG_COST_USD, _go,
        remember_kind="img_generate", remember_payload={"prompt": prompt}
    )


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Photo quick actions в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
def photo_quick_actions_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("вњЁ РћР¶РёРІРёС‚СЊ С„РѕС‚Рѕ (Runway)", callback_data="pedit:revive")],
        [InlineKeyboardButton("рџ§ј РЈРґР°Р»РёС‚СЊ С„РѕРЅ",  callback_data="pedit:removebg"),
         InlineKeyboardButton("рџ–ј Р—Р°РјРµРЅРёС‚СЊ С„РѕРЅ", callback_data="pedit:replacebg")],
        [InlineKeyboardButton("рџ§­ Р Р°СЃС€РёСЂРёС‚СЊ РєР°РґСЂ (outpaint)", callback_data="pedit:outpaint"),
         InlineKeyboardButton("рџ“Ѕ Р Р°СЃРєР°РґСЂРѕРІРєР°", callback_data="pedit:story")],
        [InlineKeyboardButton("рџ–Њ РљР°СЂС‚РёРЅРєР° РїРѕ РѕРїРёСЃР°РЅРёСЋ (Luma)", callback_data="pedit:lumaimg")],
        [InlineKeyboardButton("рџ‘Ѓ РђРЅР°Р»РёР· С„РѕС‚Рѕ", callback_data="pedit:vision")],
    ])

_photo_cache = {}  # user_id -> bytes

def _cache_photo(user_id: int, data: bytes):
    try:
        _photo_cache[user_id] = data
    except Exception:
        pass

def _get_cached_photo(user_id: int) -> bytes | None:
    return _photo_cache.get(user_id)

async def _pedit_removebg(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    if rembg_remove is None:
        await update.effective_message.reply_text("rembg РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅ. РЈСЃС‚Р°РЅРѕРІРёС‚Рµ rembg/onnxruntime.")
        return
    try:
        out = rembg_remove(img_bytes)
        bio = BytesIO(out); bio.name = "no_bg.png"
        await update.effective_message.reply_document(InputFile(bio), caption="Р¤РѕРЅ СѓРґР°Р»С‘РЅ вњ…")
    except Exception as e:
        log.exception("removebg error: %s", e)
        await update.effective_message.reply_text("РќРµ СѓРґР°Р»РѕСЃСЊ СѓРґР°Р»РёС‚СЊ С„РѕРЅ.")

async def _pedit_replacebg(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    if Image is None:
        await update.effective_message.reply_text("Pillow РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅ.")
        return
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGBA")
        bg = im.convert("RGB").filter(ImageFilter.GaussianBlur(radius=22)) if ImageFilter else im.convert("RGB")
        bio = BytesIO(); bg.save(bio, format="JPEG", quality=92); bio.seek(0); bio.name = "bg_blur.jpg"
        await update.effective_message.reply_photo(InputFile(bio), caption="Р—Р°РјРµРЅРёР» С„РѕРЅ РЅР° СЂР°Р·РјС‹С‚С‹Р№ РІР°СЂРёР°РЅС‚.")
    except Exception as e:
        log.exception("replacebg error: %s", e)
        await update.effective_message.reply_text("РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РјРµРЅРёС‚СЊ С„РѕРЅ.")

async def _pedit_outpaint(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    if Image is None:
        await update.effective_message.reply_text("Pillow РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅ.")
        return
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGB")
        pad = max(64, min(256, max(im.size)//6))
        big = Image.new("RGB", (im.width + 2*pad, im.height + 2*pad))
        bg = im.resize(big.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(radius=24)) if ImageFilter else im.resize(big.size)
        big.paste(bg, (0, 0)); big.paste(im, (pad, pad))
        bio = BytesIO(); big.save(bio, format="JPEG", quality=92); bio.seek(0); bio.name = "outpaint.jpg"
        await update.effective_message.reply_photo(InputFile(bio), caption="РџСЂРѕСЃС‚РѕР№ outpaint: СЂР°СЃС€РёСЂРёР» РїРѕР»РѕС‚РЅРѕ СЃ РјСЏРіРєРёРјРё РєСЂР°СЏРјРё.")
    except Exception as e:
        log.exception("outpaint error: %s", e)
        await update.effective_message.reply_text("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРґРµР»Р°С‚СЊ outpaint.")

async def _pedit_storyboard(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    try:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        desc = await ask_openai_vision("РћРїРёС€Рё РєР»СЋС‡РµРІС‹Рµ СЌР»РµРјРµРЅС‚С‹ РєР°РґСЂР° РѕС‡РµРЅСЊ РєСЂР°С‚РєРѕ.", b64, sniff_image_mime(img_bytes))
        plan = await ask_openai_text(
            "РЎРґРµР»Р°Р№ СЂР°СЃРєР°РґСЂРѕРІРєСѓ (6 РєР°РґСЂРѕРІ) РїРѕРґ 6вЂ“10 СЃРµРєСѓРЅРґРЅС‹Р№ РєР»РёРї. "
            "РљР°Р¶РґС‹Р№ РєР°РґСЂ вЂ” 1 СЃС‚СЂРѕРєР°: РєР°РґСЂ/РґРµР№СЃС‚РІРёРµ/СЂР°РєСѓСЂСЃ/СЃРІРµС‚. РћСЃРЅРѕРІР°:\n" + (desc or "")
        )
        await update.effective_message.reply_text("Р Р°СЃРєР°РґСЂРѕРІРєР°:\РЅ" + plan)
    except Exception as e:
        log.exception("storyboard error: %s", e)
        await update.effective_message.reply_text("РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕСЃС‚СЂРѕРёС‚СЊ СЂР°СЃРєР°РґСЂРѕРІРєСѓ.")


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ WebApp data (С‚Р°СЂРёС„С‹/РїРѕРїРѕР»РЅРµРЅРёСЏ) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def on_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        wad = update.effective_message.web_app_data
        raw = wad.data if wad else ""
        data = {}
        try:
            data = json.loads(raw)
        except Exception:
            for part in (raw or "").split("&"):
                if "=" in part:
                    k, v = part.split("=", 1); data[k] = v

        typ = (data.get("type") or data.get("action") or "").lower()

        if typ in ("subscribe", "buy", "buy_sub", "sub"):
            tier = (data.get("tier") or "pro").lower()
            months = int(data.get("months") or 1)
            desc = f"РћС„РѕСЂРјР»РµРЅРёРµ РїРѕРґРїРёСЃРєРё {tier.upper()} РЅР° {months} РјРµСЃ."
            await update.effective_message.reply_text(
                f"{desc}\nР’С‹Р±РµСЂРёС‚Рµ СЃРїРѕСЃРѕР±:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("РћРїР»Р°С‚РёС‚СЊ РєР°СЂС‚РѕР№ (Р®Kassa)", callback_data=f"buyinv:{tier}:{months}")],
                    [InlineKeyboardButton("РЎРїРёСЃР°С‚СЊ СЃ Р±Р°Р»Р°РЅСЃР° (USD)",  callback_data=f"buywallet:{tier}:{months}")],
                ])
            )
            return

        if typ in ("topup_rub", "rub_topup"):
            amount_rub = int(data.get("amount") or 0)
            if amount_rub < MIN_RUB_FOR_INVOICE:
                await update.effective_message.reply_text(f"РњРёРЅРёРјР°Р»СЊРЅР°СЏ СЃСѓРјРјР°: {MIN_RUB_FOR_INVOICE} в‚Ѕ")
                return
            await _send_invoice_rub("РџРѕРїРѕР»РЅРµРЅРёРµ Р±Р°Р»Р°РЅСЃР°", "Р•РґРёРЅС‹Р№ РєРѕС€РµР»С‘Рє", amount_rub, "t=3", update)
            return

        if typ in ("topup_crypto", "crypto_topup"):
            if not CRYPTO_PAY_API_TOKEN:
                await update.effective_message.reply_text("CryptoBot РЅРµ РЅР°СЃС‚СЂРѕРµРЅ.")
                return
            usd = float(data.get("usd") or 0)
            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(usd, asset="USDT")
            if not inv_id or not pay_url:
                await update.effective_message.reply_text("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕР·РґР°С‚СЊ СЃС‡С‘С‚ РІ CryptoBot.")
                return
            msg = await update.effective_message.reply_text(
                f"РћРїР»Р°С‚РёС‚Рµ С‡РµСЂРµР· CryptoBot: в‰€ ${usd_amount:.2f} ({asset}).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("РћРїР»Р°С‚РёС‚СЊ РІ CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("РџСЂРѕРІРµСЂРёС‚СЊ РѕРїР»Р°С‚Сѓ", callback_data=f"crypto:check:{inv_id}")]
                ])
            )
            context.application.create_task(_poll_crypto_invoice(
                context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id, usd_amount
            ))
            return

        await update.effective_message.reply_text("РџРѕР»СѓС‡РµРЅС‹ РґР°РЅРЅС‹Рµ РёР· РјРёРЅРё-РїСЂРёР»РѕР¶РµРЅРёСЏ, РЅРѕ РєРѕРјР°РЅРґР° РЅРµ СЂР°СЃРїРѕР·РЅР°РЅР°.")
    except Exception as e:
        log.exception("on_webapp_data error: %s", e)
        await update.effective_message.reply_text("РћС€РёР±РєР° РѕР±СЂР°Р±РѕС‚РєРё РґР°РЅРЅС‹С… РјРёРЅРё-РїСЂРёР»РѕР¶РµРЅРёСЏ.")


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ CallbackQuery (РІСЃС‘ РѕСЃС‚Р°Р»СЊРЅРѕРµ) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
_pending_actions = {}

def _new_aid() -> str:
    return uuid.uuid4().hex[:12]

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()
    try:
        # TOPUP РјРµРЅСЋ
        if data == "topup":
            await q.answer()
            await _send_topup_menu(update, context)
            return

        # TOPUP RUB
        if data.startswith("topup:rub:"):
            await q.answer()
            try:
                amount_rub = int((data.split(":", 2)[-1] or "0").strip() or "0")
            except Exception:
                amount_rub = 0
            if amount_rub < MIN_RUB_FOR_INVOICE:
                await q.edit_message_text(f"РњРёРЅРёРјР°Р»СЊРЅР°СЏ СЃСѓРјРјР° РїРѕРїРѕР»РЅРµРЅРёСЏ: {MIN_RUB_FOR_INVOICE} в‚Ѕ")
                return
            ok = await _send_invoice_rub("РџРѕРїРѕР»РЅРµРЅРёРµ Р±Р°Р»Р°РЅСЃР°", "Р•РґРёРЅС‹Р№ РєРѕС€РµР»С‘Рє РґР»СЏ РїРµСЂРµСЂР°СЃС…РѕРґРѕРІ.", amount_rub, "t=3", update)
            await q.answer("Р’С‹СЃС‚Р°РІР»СЏСЋ СЃС‡С‘С‚вЂ¦" if ok else "РќРµ СѓРґР°Р»РѕСЃСЊ РІС‹СЃС‚Р°РІРёС‚СЊ СЃС‡С‘С‚", show_alert=not ok)
            return

        # TOPUP CRYPTO
        if data.startswith("topup:crypto:"):
            await q.answer()
            if not CRYPTO_PAY_API_TOKEN:
                await q.edit_message_text("РќР°СЃС‚СЂРѕР№С‚Рµ CRYPTO_PAY_API_TOKEN РґР»СЏ РѕРїР»Р°С‚С‹ С‡РµСЂРµР· CryptoBot.")
                return
            try:
                usd = float((data.split(":", 2)[-1] or "0").strip() or "0")
            except Exception:
                usd = 0.0
            if usd <= 0.0:
                await q.edit_message_text("РќРµРІРµСЂРЅР°СЏ СЃСѓРјРјР°.")
                return
            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(usd, asset="USDT", description="Wallet top-up")
            if not inv_id or not pay_url:
                await q.edit_message_text("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕР·РґР°С‚СЊ СЃС‡С‘С‚ РІ CryptoBot. РџРѕРїСЂРѕР±СѓР№С‚Рµ РїРѕР·Р¶Рµ.")
                return
            msg = await update.effective_message.reply_text(
                f"РћРїР»Р°С‚РёС‚Рµ С‡РµСЂРµР· CryptoBot: в‰€ ${usd_amount:.2f} ({asset}).\nРџРѕСЃР»Рµ РѕРїР»Р°С‚С‹ Р±Р°Р»Р°РЅСЃ РїРѕРїРѕР»РЅРёС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("РћРїР»Р°С‚РёС‚СЊ РІ CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("РџСЂРѕРІРµСЂРёС‚СЊ РѕРїР»Р°С‚Сѓ", callback_data=f"crypto:check:{inv_id}")]
                ])
            )
            context.application.create_task(_poll_crypto_invoice(
                context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id, usd_amount
            ))
            return

        if data.startswith("crypto:check:"):
            await q.answer()
            inv_id = data.split(":", 2)[-1]
            inv = await _crypto_get_invoice(inv_id)
            if not inv:
                await q.edit_message_text("РќРµ РЅР°С€С‘Р» СЃС‡С‘С‚. РЎРѕР·РґР°Р№С‚Рµ РЅРѕРІС‹Р№.")
                return
            st = (inv.get("status") or "").lower()
            if st == "paid":
                usd_amount = float(inv.get("amount", 0.0))
                if (inv.get("asset") or "").upper() == "TON":
                    usd_amount *= TON_USD_RATE
                _wallet_total_add(update.effective_user.id, usd_amount)
                await q.edit_message_text(f"рџ’і РћРїР»Р°С‚Р° РїРѕР»СѓС‡РµРЅР°. Р‘Р°Р»Р°РЅСЃ РїРѕРїРѕР»РЅРµРЅ РЅР° в‰€ ${usd_amount:.2f}.")
            elif st == "active":
                await q.answer("РџР»Р°С‚С‘Р¶ РµС‰С‘ РЅРµ РїРѕРґС‚РІРµСЂР¶РґС‘РЅ", show_alert=True)
            else:
                await q.edit_message_text(f"РЎС‚Р°С‚СѓСЃ СЃС‡С‘С‚Р°: {st}")
            return

        # РџРѕРґРїРёСЃРєР°: РІС‹Р±РѕСЂ СЃРїРѕСЃРѕР±Р°
        if data.startswith("buy:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            desc = f"РџРѕРґРїРёСЃРєР° {tier.upper()} РЅР° {months} РјРµСЃ."
            await q.edit_message_text(
                f"{desc}\nР’С‹Р±РµСЂРёС‚Рµ СЃРїРѕСЃРѕР± РѕРїР»Р°С‚С‹:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("РћРїР»Р°С‚РёС‚СЊ РєР°СЂС‚РѕР№ (Р®Kassa)", callback_data=f"buyinv:{tier}:{months}")],
                    [InlineKeyboardButton("РЎРїРёСЃР°С‚СЊ СЃ Р±Р°Р»Р°РЅСЃР° (USD)",  callback_data=f"buywallet:{tier}:{months}")],
                ])
            )
            return

        # РџРѕРґРїРёСЃРєР° С‡РµСЂРµР· Р®Kassa
        if data.startswith("buyinv:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            payload, amount_rub, title = _plan_payload_and_amount(tier, months)
            desc = f"РћС„РѕСЂРјР»РµРЅРёРµ РїРѕРґРїРёСЃРєРё {tier.upper()} РЅР° {months} РјРµСЃ."
            ok = await _send_invoice_rub(title, desc, amount_rub, payload, update)
            if not ok:
                await q.answer("РќРµ СѓРґР°Р»РѕСЃСЊ РІС‹СЃС‚Р°РІРёС‚СЊ СЃС‡С‘С‚", show_alert=True)
            return

        # РџРѕРґРїРёСЃРєР° СЃРїРёСЃР°РЅРёРµРј РёР· USD-Р±Р°Р»Р°РЅСЃР°
        if data.startswith("buywallet:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            amount_rub = _plan_rub(tier, {1: "month", 3: "quarter", 12: "year"}[months])
            need_usd = float(amount_rub) / max(1e-9, USD_RUB)
            if _wallet_total_take(update.effective_user.id, need_usd):
                until = activate_subscription_with_tier(update.effective_user.id, tier, months)
                await q.edit_message_text(
                    f"вњ… РџРѕРґРїРёСЃРєР° {tier.upper()} Р°РєС‚РёРІРёСЂРѕРІР°РЅР° РґРѕ {until.strftime('%Y-%m-%d')}.\n"
                    f"РЎРїРёСЃР°РЅРѕ СЃ Р±Р°Р»Р°РЅСЃР°: ~${need_usd:.2f}."
                )
            else:
                await q.edit_message_text(
                    "РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ СЃСЂРµРґСЃС‚РІ РЅР° РµРґРёРЅРѕРј Р±Р°Р»Р°РЅСЃРµ.\nРџРѕРїРѕР»РЅРёС‚Рµ Р±Р°Р»Р°РЅСЃ Рё РїРѕРІС‚РѕСЂРёС‚Рµ.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("вћ• РџРѕРїРѕР»РЅРёС‚СЊ Р±Р°Р»Р°РЅСЃ", callback_data="topup")]])
                )
            return

        # Р’С‹Р±РѕСЂ РґРІРёР¶РєР°
        if data.startswith("engine:"):
            await q.answer()
            engine = data.split(":", 1)[1]
            username = (update.effective_user.username or "")
            if is_unlimited(update.effective_user.id, username):
                await q.edit_message_text(
                    f"вњ… Р”РІРёР¶РѕРє В«{engine}В» РґРѕСЃС‚СѓРїРµРЅ Р±РµР· РѕРіСЂР°РЅРёС‡РµРЅРёР№.\n"
                    f"РћС‚РїСЂР°РІСЊС‚Рµ Р·Р°РґР°С‡Сѓ, РЅР°РїСЂРёРјРµСЂ: В«СЃРґРµР»Р°Р№ РІРёРґРµРѕ СЂРµС‚СЂРѕ-Р°РІС‚Рѕ, 9 СЃРµРєСѓРЅРґ, 9:16В»."
                )
                return

            if engine in ("gpt", "stt_tts", "midjourney"):
                await q.edit_message_text(
                    f"вњ… Р’С‹Р±СЂР°РЅ В«{engine}В». РћС‚РїСЂР°РІСЊС‚Рµ Р·Р°РїСЂРѕСЃ С‚РµРєСЃС‚РѕРј/С„РѕС‚Рѕ. "
                    f"Р”Р»СЏ Luma/Runway/Images РґРµР№СЃС‚РІСѓСЋС‚ РґРЅРµРІРЅС‹Рµ Р±СЋРґР¶РµС‚С‹ С‚Р°СЂРёС„Р°."
                )
                return

            est_cost = IMG_COST_USD if engine == "images" else (0.40 if engine == "luma" else max(1.0, RUNWAY_UNIT_COST_USD))
            map_engine = {"images": "img", "luma": "luma", "runway": "runway"}[engine]
            ok, offer = _can_spend_or_offer(update.effective_user.id, username, map_engine, est_cost)

            if ok:
                await q.edit_message_text(
                    "вњ… Р”РѕСЃС‚СѓРїРЅРѕ. " +
                    ("Р—Р°РїСѓСЃС‚РёС‚Рµ: /img РєРѕС‚ РІ РѕС‡РєР°С…" if engine == "images"
                     else "РќР°РїРёС€РёС‚Рµ: В«СЃРґРµР»Р°Р№ РІРёРґРµРѕ вЂ¦ 9 СЃРµРєСѓРЅРґ 9:16В» вЂ” РїСЂРµРґР»РѕР¶Сѓ Luma/Runway.")
                )
                return

            if offer == "ASK_SUBSCRIBE":
                await q.edit_message_text(
                    "Р”Р»СЏ СЌС‚РѕРіРѕ РґРІРёР¶РєР° РЅСѓР¶РЅР° Р°РєС‚РёРІРЅР°СЏ РїРѕРґРїРёСЃРєР° РёР»Рё РµРґРёРЅС‹Р№ Р±Р°Р»Р°РЅСЃ. РћС‚РєСЂРѕР№С‚Рµ /plans РёР»Рё РїРѕРїРѕР»РЅРёС‚Рµ В«рџ§ѕ Р‘Р°Р»Р°РЅСЃВ».",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("в­ђ РўР°СЂРёС„С‹", web_app=WebAppInfo(url=TARIFF_URL))],
                         [InlineKeyboardButton("вћ• РџРѕРїРѕР»РЅРёС‚СЊ Р±Р°Р»Р°РЅСЃ", callback_data="topup")]]
                    ),
                )
                return

            try:
                need_usd = float(offer.split(":", 1)[-1])
            except Exception:
                need_usd = est_cost
            amount_rub = _calc_oneoff_price_rub(map_engine, need_usd)
            await q.edit_message_text(
                f"Р’Р°С€ РґРЅРµРІРЅРѕР№ Р»РёРјРёС‚ РїРѕ В«{engine}В» РёСЃС‡РµСЂРїР°РЅ. Р Р°Р·РѕРІР°СЏ РїРѕРєСѓРїРєР° в‰€ {amount_rub} в‚Ѕ "
                f"РёР»Рё РїРѕРїРѕР»РЅРёС‚Рµ Р±Р°Р»Р°РЅСЃ РІ В«рџ§ѕ Р‘Р°Р»Р°РЅСЃВ».",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("в­ђ РўР°СЂРёС„С‹", web_app=WebAppInfo(url=TARIFF_URL))],
                        [InlineKeyboardButton("вћ• РџРѕРїРѕР»РЅРёС‚СЊ Р±Р°Р»Р°РЅСЃ", callback_data="topup")],
                    ]
                ),
            )
            return

        # Р РµР¶РёРјС‹ / Р”РІРёР¶РєРё
        if data == "mode:engines":
            await q.answer()
            await q.edit_message_text("Р”РІРёР¶РєРё:", reply_markup=engines_kb())
            return

        if data.startswith("mode:set:"):
            await q.answer()
            mode = data.split(":")[-1]
            mode_set(update.effective_user.id, mode)
            if mode == "study":
                study_sub_set(update.effective_user.id, "explain")
                await q.edit_message_text("Р РµР¶РёРј В«РЈС‡С‘Р±Р°В» РІРєР»СЋС‡С‘РЅ. Р’С‹Р±РµСЂРёС‚Рµ РїРѕРґСЂРµР¶РёРј:", reply_markup=study_kb())
            elif mode == "photo":
                await q.edit_message_text("Р РµР¶РёРј В«Р¤РѕС‚РѕВ» РІРєР»СЋС‡С‘РЅ. РџСЂРёС€Р»РёС‚Рµ РёР·РѕР±СЂР°Р¶РµРЅРёРµ вЂ” РїРѕСЏРІСЏС‚СЃСЏ Р±С‹СЃС‚СЂС‹Рµ РєРЅРѕРїРєРё.", reply_markup=photo_quick_actions_kb())
            elif mode == "docs":
                await q.edit_message_text("Р РµР¶РёРј В«Р”РѕРєСѓРјРµРЅС‚С‹В». РџСЂРёС€Р»РёС‚Рµ PDF/DOCX/EPUB/TXT вЂ” СЃРґРµР»Р°СЋ РєРѕРЅСЃРїРµРєС‚.")
            elif mode == "voice":
                await q.edit_message_text("Р РµР¶РёРј В«Р“РѕР»РѕСЃВ». РћС‚РїСЂР°РІСЊС‚Рµ voice/audio. РћР·РІСѓС‡РєР° РѕС‚РІРµС‚РѕРІ: /voice_on")
            else:
                await q.edit_message_text(f"Р РµР¶РёРј В«{mode}В» Р°РєС‚РёРІРёСЂРѕРІР°РЅ.")
            return

        if data.startswith("study:set:"):
            await q.answer()
            sub = data.split(":")[-1]
            study_sub_set(update.effective_user.id, sub)
            await q.edit_message_text(f"РЈС‡С‘Р±Р° в†’ {sub}. РќР°РїРёС€РёС‚Рµ С‚РµРјСѓ/Р·Р°РґР°РЅРёРµ.", reply_markup=study_kb())
            return

        # Photo edits require cached image
        if data.startswith("pedit:"):
            await q.answer()
            img = _get_cached_photo(update.effective_user.id)
            if not img:
                await q.edit_message_text("РЎРЅР°С‡Р°Р»Р° РїСЂРёС€Р»РёС‚Рµ С„РѕС‚Рѕ, Р·Р°С‚РµРј РІС‹Р±РµСЂРёС‚Рµ РґРµР№СЃС‚РІРёРµ.", reply_markup=photo_quick_actions_kb())
                return
            if data == "pedit:removebg":
                await _pedit_removebg(update, context, img); return
            if data == "pedit:replacebg":
                await _pedit_replacebg(update, context, img); return
            if data == "pedit:outpaint":
                await _pedit_outpaint(update, context, img); return
            if data == "pedit:story":
                await _pedit_storyboard(update, context, img); return
            if data == "pedit:revive":
                img = _get_cached_photo(update.effective_user.id)
                if not img:
                    await q.edit_message_text("РЎРЅР°С‡Р°Р»Р° РїСЂРёС€Р»РёС‚Рµ С„РѕС‚Рѕ, Р·Р°С‚РµРј РЅР°Р¶РјРёС‚Рµ В«РћР¶РёРІРёС‚СЊ С„РѕС‚РѕВ».")
                    return
                dur, asp = parse_video_opts("")  # РґРµС„РѕР»С‚ РёР· ENV
                async def _go():
                    await _run_runway_animate_photo(update, context, img, prompt="", duration_s=dur, aspect=asp)
                await _try_pay_then_do(update, context, update.effective_user.id, "runway",
                                       max(1.0, RUNWAY_UNIT_COST_USD * (dur / max(1, RUNWAY_DURATION_S))),
                                       _go, remember_kind="revive_photo_btn",
                                       remember_payload={"duration": dur, "aspect": asp})
                return

            if data == "pedit:lumaimg":
                _mode_track_set(update.effective_user.id, "lumaimg_wait_text")
                await q.edit_message_text("РќР°РїРёС€РёС‚Рµ РѕРґРЅРѕ РїСЂРµРґР»РѕР¶РµРЅРёРµ вЂ” С‡С‚Рѕ СЃРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ. РЇ СЃРґРµР»Р°СЋ РєР°СЂС‚РёРЅРєСѓ (Luma / С„РѕР»Р±СЌРє OpenAI).")
                return
            if data == "pedit:vision":
                b64 = base64.b64encode(img).decode("ascii")
                mime = sniff_image_mime(img)
                ans = await ask_openai_vision("РћРїРёС€Рё С„РѕС‚Рѕ Рё С‚РµРєСЃС‚ РЅР° РЅС‘Рј РєСЂР°С‚РєРѕ.", b64, mime)
                await update.effective_message.reply_text(ans or "Р“РѕС‚РѕРІРѕ.")
                return

        # РџРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ РІС‹Р±РѕСЂР° РґРІРёР¶РєР° РґР»СЏ РІРёРґРµРѕ
        if data.startswith("choose:"):
            await q.answer()
            _, engine, aid = data.split(":", 2)
            meta = _pending_actions.pop(aid, None)
            if not meta:
                await q.answer("Р—Р°РґР°С‡Р° СѓСЃС‚Р°СЂРµР»Р°", show_alert=True)
                return
            prompt   = meta["prompt"]
            duration = meta["duration"]
            aspect   = meta["aspect"]
            est = 0.40 if engine == "luma" else max(1.0, RUNWAY_UNIT_COST_USD * (duration / max(1, RUNWAY_DURATION_S)))
            map_engine = "luma" if engine == "luma" else "runway"

            async def _start_real_render():
                if engine == "luma":
                    await _run_luma_video(update, context, prompt, duration, aspect)
                    _register_engine_spend(update.effective_user.id, "luma", 0.40)
                else:
                    await _run_runway_video(update, context, prompt, duration, aspect)
                    base = RUNWAY_UNIT_COST_USD or 7.0
                    cost = max(1.0, base * (duration / max(1, RUNWAY_DURATION_S)))
                    _register_engine_spend(update.effective_user.id, "runway", cost)

            await _try_pay_then_do(
                update, context, update.effective_user.id,
                map_engine, est, _start_real_render,
                remember_kind=f"video_{engine}",
                remember_payload={"prompt": prompt, "duration": duration, "aspect": aspect},
            )
            return

        await q.answer("РќРµРёР·РІРµСЃС‚РЅР°СЏ РєРѕРјР°РЅРґР°", show_alert=True)

    except Exception as e:
        log.exception("on_cb error: %s", e)
    finally:
        with contextlib.suppress(Exception):
            await q.answer()


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ STT в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
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
                params = {"model": "nova-2", "language": "ru", "smart_format": "true", "punctuate": "true"}
                headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": _mime_from_filename(filename_hint)}
                r = await client.post("https://api.deepgram.com/v1/listen", params=params, headers=headers, content=data)
                r.raise_for_status()
                dg = r.json()
                text = (dg.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("transcript", "")).strip()
                if text: return text
        except Exception as e:
            log.exception("Deepgram STT error: %s", e)
    if oai_stt:
        try:
            buf2 = BytesIO(data); buf2.seek(0); setattr(buf2, "name", filename_hint)
            tr = oai_stt.audio.transcriptions.create(model=TRANSCRIBE_MODEL, file=buf2)
            return (tr.text or "").strip()
        except Exception as e:
            log.exception("Whisper STT error: %s", e)
    return ""


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Р”РёР°РіРЅРѕСЃС‚РёРєР° РґРІРёР¶РєРѕРІ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def cmd_diag_stt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = []
    lines.append("рџ”Ћ STT РґРёР°РіРЅРѕСЃС‚РёРєР°:")
    lines.append(f"вЂў Deepgram: {'вњ… РєР»СЋС‡ РЅР°Р№РґРµРЅ' if DEEPGRAM_API_KEY else 'вќЊ РЅРµС‚ РєР»СЋС‡Р°'}")
    lines.append(f"вЂў OpenAI Whisper: {'вњ… РєР»РёРµРЅС‚ Р°РєС‚РёРІРµРЅ' if oai_stt else 'вќЊ РЅРµРґРѕСЃС‚СѓРїРµРЅ'}")
    lines.append(f"вЂў РњРѕРґРµР»СЊ Whisper: {TRANSCRIBE_MODEL}")
    lines.append("вЂў РџРѕРґРґРµСЂР¶РєР° С„РѕСЂРјР°С‚РѕРІ: ogg/oga, mp3, m4a/mp4, wav, webm")
    await update.effective_message.reply_text("\n".join(lines))

async def cmd_diag_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key_env  = os.environ.get("OPENAI_IMAGE_KEY", "").strip()
    key_used = key_env or OPENAI_API_KEY
    base     = IMAGES_BASE_URL
    lines = [
        "рџ§Є Images (OpenAI) РґРёР°РіРЅРѕСЃС‚РёРєР°:",
        f"вЂў OPENAI_IMAGE_KEY: {'вњ… РЅР°Р№РґРµРЅ' if key_used else 'вќЊ РЅРµС‚'}",
        f"вЂў BASE_URL: {base}",
        f"вЂў MODEL: {IMAGES_MODEL}",
    ]
    if "openrouter" in (base or "").lower():
        lines.append("вљ пёЏ BASE_URL СѓРєР°Р·С‹РІР°РµС‚ РЅР° OpenRouter вЂ” С‚Р°Рј РЅРµС‚ gpt-image-1.")
        lines.append("   РЈРєР°Р¶Рё https://api.openai.com/v1 (РёР»Рё СЃРІРѕР№ РїСЂРѕРєСЃРё) РІ OPENAI_IMAGE_BASE_URL.")
    await update.effective_message.reply_text("\n".join(lines))

async def cmd_diag_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [
        "рџЋ¬ Р’РёРґРµРѕ-РґРІРёР¶РєРё:",
        f"вЂў Luma key: {'вњ…' if bool(LUMA_API_KEY) else 'вќЊ'}  base={LUMA_BASE_URL}",
        f"  create={LUMA_CREATE_PATH}  status={LUMA_STATUS_PATH}",
        f"  model={LUMA_MODEL}  allowed_durations=['5s','9s','10s']  aspect=['16:9','9:16','1:1']",
        f"вЂў Runway key: {'вњ…' if bool(RUNWAY_API_KEY) else 'вќЊ'}  base={RUNWAY_BASE_URL}",
        f"  create={RUNWAY_CREATE_PATH}  status={RUNWAY_STATUS_PATH}",
        f"вЂў РџРѕР»Р»РёРЅРі РєР°Р¶РґС‹Рµ {VIDEO_POLL_DELAY_S:.1f} c",
    ]
    await update.effective_message.reply_text("\n".join(lines))


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ MIME РґР»СЏ РёР·РѕР±СЂР°Р¶РµРЅРёР№ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
def sniff_image_mime(data: bytes) -> str:
    if not data or len(data) < 12:
        return "application/octet-stream"
    b = data[:12]
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if b[0:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[0:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РџР°СЂСЃ РѕРїС†РёР№ РІРёРґРµРѕ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
_ASPECTS = {"9:16", "16:9", "1:1", "4:5", "3:4", "4:3"}

def parse_video_opts(text: str) -> tuple[int, str]:
    tl = (text or "").lower()
    m = re.search(r"(\d+)\s*(?:СЃРµРє|СЃ)\b", tl)
    duration = int(m.group(1)) if m else LUMA_DURATION_S
    duration = max(3, min(20, duration))
    asp = None
    for a in _ASPECTS:
        if a in tl:
            asp = a; break
    aspect = asp or (LUMA_ASPECT if LUMA_ASPECT in _ASPECTS else "16:9")
    return duration, aspect


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Luma video в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def _run_luma_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration_s: int, aspect: str):
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            base = await _pick_luma_base(client)
            create_url = f"{base}{LUMA_CREATE_PATH}"
            headers = {"Authorization": f"Bearer {LUMA_API_KEY}", "Accept": "application/json"}
            payload = {
                "model": LUMA_MODEL,
                "prompt": prompt,
                "duration": f"{duration_s}s",
                "aspect_ratio": aspect,
            }
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code >= 400:
                await update.effective_message.reply_text(f"вљ пёЏ Luma РѕС‚РєР»РѕРЅРёР»Р° Р·Р°РґР°С‡Сѓ ({r.status_code}).")
                return
            rid = (r.json() or {}).get("id") or (r.json() or {}).get("generation_id")
            if not rid:
                await update.effective_message.reply_text("вљ пёЏ Luma РЅРµ РІРµСЂРЅСѓР»Р° id РіРµРЅРµСЂР°С†РёРё.")
                return

            await update.effective_message.reply_text("вЏі Luma СЂРµРЅРґРµСЂРёС‚вЂ¦ РЇ СЃРѕРѕР±С‰Сѓ, РєРѕРіРґР° РІРёРґРµРѕ Р±СѓРґРµС‚ РіРѕС‚РѕРІРѕ.")

            status_url = f"{base}{LUMA_STATUS_PATH}".format(id=rid)
            started = time.time()
            while True:
                rs = await client.get(status_url, headers=headers)
                js = {}
                try: js = rs.json()
                except Exception: pass
                st = (js.get("state") or js.get("status") or "").lower()
                if st in ("completed", "succeeded", "finished", "ready"):
                    url = js.get("assets", [{}])[0].get("url") or js.get("output_url")
                    if not url:
                        await update.effective_message.reply_text("вљ пёЏ Р“РѕС‚РѕРІРѕ, РЅРѕ РЅРµС‚ СЃСЃС‹Р»РєРё РЅР° РІРёРґРµРѕ.")
                        return
                    try:
                        v = await client.get(url, timeout=120.0)
                        v.raise_for_status()
                        bio = BytesIO(v.content); bio.name = "luma.mp4"
                        await update.effective_message.reply_video(InputFile(bio), caption="рџЋ¬ Luma: РіРѕС‚РѕРІРѕ вњ…")
                    except Exception:
                        await update.effective_message.reply_text(f"рџЋ¬ Luma: РіРѕС‚РѕРІРѕ вњ…\n{url}")
                    return
                if st in ("failed", "error", "canceled", "cancelled"):
                    await update.effective_message.reply_text("вќЊ Luma: РѕС€РёР±РєР° СЂРµРЅРґРµСЂР°.")
                    return
                if time.time() - started > LUMA_MAX_WAIT_S:
                    await update.effective_message.reply_text("вЊ› Luma: РІСЂРµРјСЏ РѕР¶РёРґР°РЅРёСЏ РІС‹С€Р»Рѕ.")
                    return
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("Luma error: %s", e)
        await update.effective_message.reply_text("вќЊ Luma: РЅРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РїСѓСЃС‚РёС‚СЊ/РїРѕР»СѓС‡РёС‚СЊ РІРёРґРµРѕ.")


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Runway video в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def _run_runway_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration_s: int, aspect: str):
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            create_url = f"{RUNWAY_BASE_URL}{RUNWAY_CREATE_PATH}"
            headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Accept": "application/json"}
            payload = {
                "model": RUNWAY_MODEL,
                "input": {
                    "prompt": prompt,
                    "duration": duration_s,
                    "ratio": aspect.replace(":", "/") if ":" in aspect else RUNWAY_RATIO
                }
            }
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code >= 400:
                await update.effective_message.reply_text(f"вљ пёЏ Runway РѕС‚РєР»РѕРЅРёР» Р·Р°РґР°С‡Сѓ ({r.status_code}).")
                return
            rid = (r.json() or {}).get("id") or (r.json() or {}).get("task_id")
            if not rid:
                await update.effective_message.reply_text("вљ пёЏ Runway РЅРµ РІРµСЂРЅСѓР» id Р·Р°РґР°С‡Рё.")
                return

            await update.effective_message.reply_text("вЏі Runway СЂРµРЅРґРµСЂРёС‚вЂ¦ РЇ СЃРѕРѕР±С‰Сѓ, РєРѕРіРґР° РІРёРґРµРѕ Р±СѓРґРµС‚ РіРѕС‚РѕРІРѕ.")

            status_url = f"{RUNWAY_BASE_URL}{RUNWAY_STATUS_PATH}".format(id=rid)
            started = time.time()
            while True:
                rs = await client.get(status_url, headers=headers)
                js = {}
                try: js = rs.json()
                except Exception: pass
                st = (js.get("status") or js.get("state") or "").lower()
                if st in ("completed", "succeeded", "finished", "ready"):
                    assets = js.get("output", {}) if isinstance(js.get("output"), dict) else (js.get("assets") or {})
                    url = (assets.get("video") if isinstance(assets, dict) else None) or js.get("video_url") or js.get("output_url")
                    if not url:
                        await update.effective_message.reply_text("вљ пёЏ Р“РѕС‚РѕРІРѕ, РЅРѕ РЅРµС‚ СЃСЃС‹Р»РєРё РЅР° РІРёРґРµРѕ.")
                        return
                    try:
                        v = await client.get(url, timeout=180.0)
                        v.raise_for_status()
                        bio = BytesIO(v.content); bio.name = "runway.mp4"
                        await update.effective_message.reply_video(InputFile(bio), caption="рџЋҐ Runway: РіРѕС‚РѕРІРѕ вњ…")
                    except Exception:
                        await update.effective_message.reply_text(f"рџЋҐ Runway: РіРѕС‚РѕРІРѕ вњ…\n{url}")
                    return
                if st in ("failed", "error", "canceled", "cancelled"):
                    await update.effective_message.reply_text("вќЊ Runway: РѕС€РёР±РєР° СЂРµРЅРґРµСЂР°.")
                    return
                if time.time() - started > RUNWAY_MAX_WAIT_S:
                    await update.effective_message.reply_text("вЊ› Runway: РІСЂРµРјСЏ РѕР¶РёРґР°РЅРёСЏ РІС‹С€Р»Рѕ.")
                    return
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("Runway error: %s", e)
        await update.effective_message.reply_text("вќЊ Runway: РЅРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РїСѓСЃС‚РёС‚СЊ/РїРѕР»СѓС‡РёС‚СЊ РІРёРґРµРѕ.")

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Runway: Р°РЅРёРјР°С†РёСЏ Р·Р°РіСЂСѓР¶РµРЅРЅРѕРіРѕ С„РѕС‚Рѕ (imageв†’video) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def _run_runway_animate_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes, prompt: str, duration_s: int, aspect: str):
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)
    try:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        ratio = aspect.replace(":", "/") if ":" in aspect else RUNWAY_RATIO
        payload = {
            "model": RUNWAY_MODEL,
            "input": {
                "prompt": (prompt or "animate the input photo with subtle camera motion, lifelike micro-movements").strip(),
                "duration": duration_s,
                "ratio": ratio,
                # РєР»СЋС‡Рё init_image / image_data РїРѕРґРґРµСЂР¶РёРІР°СЋС‚СЃСЏ Р°РєС‚СѓР°Р»СЊРЅС‹РјРё РІРµСЂСЃРёСЏРјРё API
                # РµСЃР»Рё Сѓ С‚РµР±СЏ РґСЂСѓРіРѕР№ С„РѕСЂРјР°С‚ вЂ” СЃРєРѕСЂСЂРµРєС‚РёСЂСѓР№ РїРѕР»СЏ РЅРёР¶Рµ РїРѕРґ СЃРІРѕР№ Р°РєРєР°СѓРЅС‚:
                "init_image": f"data:{sniff_image_mime(img_bytes)};base64,{b64}"
            }
        }
        headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{RUNWAY_BASE_URL}{RUNWAY_CREATE_PATH}", headers=headers, json=payload)
            if r.status_code >= 400:
                await update.effective_message.reply_text(f"вљ пёЏ Runway РѕС‚РєР»РѕРЅРёР» Р·Р°РґР°С‡Сѓ ({r.status_code}).")
                return
            rid = (r.json() or {}).get("id") or (r.json() or {}).get("task_id")
            if not rid:
                await update.effective_message.reply_text("вљ пёЏ Runway РЅРµ РІРµСЂРЅСѓР» id Р·Р°РґР°С‡Рё.")
                return

            await update.effective_message.reply_text("вЏі РћР¶РёРІР»СЏСЋ С„РѕС‚Рѕ РІ RunwayвЂ¦ РЎРѕРѕР±С‰Сѓ, РєРѕРіРґР° Р±СѓРґРµС‚ РіРѕС‚РѕРІРѕ.")

            status_url = f"{RUNWAY_BASE_URL}{RUNWAY_STATUS_PATH}".format(id=rid)
            started = time.time()
            while True:
                rs = await client.get(status_url, headers=headers)
                js = {}
                try: js = rs.json()
                except Exception: pass
                st = (js.get("status") or js.get("state") or "").lower()
                if st in ("completed", "succeeded", "finished", "ready"):
                    assets = js.get("output", {}) if isinstance(js.get("output"), dict) else (js.get("assets") or {})
                    url = (assets.get("video") if isinstance(assets, dict) else None) or js.get("video_url") or js.get("output_url")
                    if not url:
                        await update.effective_message.reply_text("вљ пёЏ Р“РѕС‚РѕРІРѕ, РЅРѕ РЅРµС‚ СЃСЃС‹Р»РєРё РЅР° РІРёРґРµРѕ.")
                        return
                    try:
                        v = await client.get(url, timeout=180.0)
                        v.raise_for_status()
                        bio = BytesIO(v.content); bio.name = "revive.mp4"
                        await update.effective_message.reply_video(InputFile(bio), caption="вњЁ РћР¶РёРІРёР» С„РѕС‚Рѕ (Runway) вњ…")
                    except Exception:
                        await update.effective_message.reply_text(f"вњЁ РћР¶РёРІРёР» С„РѕС‚Рѕ (Runway) вњ…\n{url}")
                    return
                if st in ("failed", "error", "canceled", "cancelled"):
                    await update.effective_message.reply_text("вќЊ Runway: РѕС€РёР±РєР° СЂРµРЅРґРµСЂР°.")
                    return
                if time.time() - started > RUNWAY_MAX_WAIT_S:
                    await update.effective_message.reply_text("вЊ› Runway: РІСЂРµРјСЏ РѕР¶РёРґР°РЅРёСЏ РІС‹С€Р»Рѕ.")
                    return
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("Runway revive error: %s", e)
        await update.effective_message.reply_text("вќЊ РќРµ СѓРґР°Р»РѕСЃСЊ Р°РЅРёРјРёСЂРѕРІР°С‚СЊ С„РѕС‚Рѕ РІ Runway.")

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РџРѕРєСѓРїРєРё/РёРЅРІРѕР№СЃС‹ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
def _plan_rub(tier: str, term: str) -> int:
    tier = (tier or "pro").lower()
    term = (term or "month").lower()
    return int(PLAN_PRICE_TABLE.get(tier, PLAN_PRICE_TABLE["pro"]).get(term, PLAN_PRICE_TABLE["pro"]["month"]))

def _plan_payload_and_amount(tier: str, months: int) -> tuple[str, int, str]:
    term = {1: "month", 3: "quarter", 12: "year"}.get(months, "month")
    amount = _plan_rub(tier, term)
    title = f"РџРѕРґРїРёСЃРєР° {tier.upper()} ({term})"
    payload = f"sub:{tier}:{months}"
    return payload, amount, title

async def _send_invoice_rub(title: str, desc: str, amount_rub: int, payload: str, update: Update) -> bool:
    try:
        # Р±РµСЂС‘Рј С‚РѕРєРµРЅ Рё РІР°Р»СЋС‚Сѓ РёР· РґРІСѓС… РёСЃС‚РѕС‡РЅРёРєРѕРІ (СЃС‚Р°СЂС‹Р№ PROVIDER_TOKEN РР›Р РЅРѕРІС‹Р№ YOOKASSA_PROVIDER_TOKEN)
        token = (PROVIDER_TOKEN or YOOKASSA_PROVIDER_TOKEN)
        curr  = (CURRENCY if (CURRENCY and CURRENCY != "RUB") else YOOKASSA_CURRENCY) or "RUB"

        if not token:
            await update.effective_message.reply_text("вљ пёЏ Р®Kassa РЅРµ РЅР°СЃС‚СЂРѕРµРЅР° (РЅРµС‚ С‚РѕРєРµРЅР°).")
            return False

        prices = [LabeledPrice(label=_ascii_label(title), amount=int(amount_rub) * 100)]

        await update.effective_message.reply_invoice(
            title=title,
            description=desc[:255],
            payload=payload,
            provider_token=token,
            currency=curr,
            prices=prices,
            need_email=False,
            need_name=False,
            need_phone_number=False,
            need_shipping_address=False,
            is_flexible=False
        )
        return True

    except Exception as e:
        log.exception("send_invoice error: %s", e)
        try:
            await update.effective_message.reply_text("РќРµ СѓРґР°Р»РѕСЃСЊ РІС‹СЃС‚Р°РІРёС‚СЊ СЃС‡С‘С‚.")
        except Exception:
            pass
        return False

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        q = update.pre_checkout_query
        await q.answer(ok=True)
    except Exception as e:
        log.exception("precheckout error: %s", e)

async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sp = update.message.successful_payment
        payload = sp.invoice_payload or ""
        total_minor = sp.total_amount or 0
        rub = total_minor / 100.0
        uid = update.effective_user.id

        if payload.startswith("sub:"):
            _, tier, months = payload.split(":", 2)
            months = int(months)
            until = activate_subscription_with_tier(uid, tier, months)
            await update.effective_message.reply_text(f"вњ… РџРѕРґРїРёСЃРєР° {tier.upper()} Р°РєС‚РёРІРёСЂРѕРІР°РЅР° РґРѕ {until.strftime('%Y-%m-%d')}.")
            return

        # Р›СЋР±РѕРµ РёРЅРѕРµ payload вЂ” РїРѕРїРѕР»РЅРµРЅРёРµ РµРґРёРЅРѕРіРѕ РєРѕС€РµР»СЊРєР°
        usd = rub / max(1e-9, USD_RUB)
        _wallet_total_add(uid, usd)
        await update.effective_message.reply_text(f"рџ’і РџРѕРїРѕР»РЅРµРЅРёРµ: {rub:.0f} в‚Ѕ в‰€ ${usd:.2f} Р·Р°С‡РёСЃР»РµРЅРѕ РЅР° РµРґРёРЅС‹Р№ Р±Р°Р»Р°РЅСЃ.")
    except Exception as e:
        log.exception("successful_payment handler error: %s", e)


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ CryptoBot в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
CRYPTO_PAY_API_TOKEN = os.environ.get("CRYPTO_PAY_API_TOKEN", "").strip()
CRYPTO_BASE = "https://pay.crypt.bot/api"
TON_USD_RATE = float(os.environ.get("TON_USD_RATE", "5.0") or "5.0")  # Р·Р°РїР°СЃРЅРѕР№ РєСѓСЂСЃ

async def _crypto_create_invoice(usd_amount: float, asset: str = "USDT", description: str = "") -> tuple[str|None, str|None, float, str]:
    if not CRYPTO_PAY_API_TOKEN:
        return None, None, 0.0, asset
    try:
        payload = {"asset": asset, "amount": round(float(usd_amount), 2), "description": description or "Top-up"}
        headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{CRYPTO_BASE}/createInvoice", headers=headers, json=payload)
            j = r.json()
            ok = j.get("ok") is True
            if not ok:
                return None, None, 0.0, asset
            res = j.get("result", {})
            return str(res.get("invoice_id")), res.get("pay_url"), float(res.get("amount", usd_amount)), res.get("asset") or asset
    except Exception as e:
        log.exception("crypto create error: %s", e)
        return None, None, 0.0, asset

async def _crypto_get_invoice(invoice_id: str) -> dict | None:
    if not CRYPTO_PAY_API_TOKEN:
        return None
    try:
        headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN}
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{CRYPTO_BASE}/getInvoices?invoice_ids={invoice_id}", headers=headers)
            j = r.json()
            if not j.get("ok"):
                return None
            items = (j.get("result", {}) or {}).get("items", [])
            return items[0] if items else None
    except Exception as e:
        log.exception("crypto get error: %s", e)
        return None

async def _poll_crypto_invoice(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, user_id: int, invoice_id: str, usd_amount: float):
    try:
        for _ in range(120):  # ~12 РјРёРЅСѓС‚ РїСЂРё 6СЃ Р·Р°РґРµСЂР¶РєРµ
            inv = await _crypto_get_invoice(invoice_id)
            st = (inv or {}).get("status", "").lower() if inv else ""
            if st == "paid":
                _wallet_total_add(user_id, float(usd_amount))
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                        text=f"вњ… CryptoBot: РїР»Р°С‚С‘Р¶ РїРѕРґС‚РІРµСЂР¶РґС‘РЅ. Р‘Р°Р»Р°РЅСЃ РїРѕРїРѕР»РЅРµРЅ РЅР° ${float(usd_amount):.2f}.")
                return
            if st in ("expired", "cancelled", "canceled", "failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                        text=f"вќЊ CryptoBot: РїР»Р°С‚С‘Р¶ РЅРµ Р·Р°РІРµСЂС€С‘РЅ (СЃС‚Р°С‚СѓСЃ: {st}).")
                return
            await asyncio.sleep(6.0)
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                text="вЊ› CryptoBot: РІСЂРµРјСЏ РѕР¶РёРґР°РЅРёСЏ РІС‹С€Р»Рѕ. РќР°Р¶РјРёС‚Рµ В«РџСЂРѕРІРµСЂРёС‚СЊ РѕРїР»Р°С‚СѓВ» РїРѕР·Р¶Рµ.")
    except Exception as e:
        log.exception("crypto poll error: %s", e)

async def _poll_crypto_sub_invoice(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    user_id: int,
    invoice_id: str,
    tier: str,
    months: int
):
    try:
        for _ in range(120):  # ~12 РјРёРЅСѓС‚ РїСЂРё Р·Р°РґРµСЂР¶РєРµ 6СЃ
            inv = await _crypto_get_invoice(invoice_id)
            st = (inv or {}).get("status", "").lower() if inv else ""
            if st == "paid":
                until = activate_subscription_with_tier(user_id, tier, months)
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=f"вњ… CryptoBot: РїР»Р°С‚С‘Р¶ РїРѕРґС‚РІРµСЂР¶РґС‘РЅ.\n"
                             f"РџРѕРґРїРёСЃРєР° {tier.upper()} Р°РєС‚РёРІРЅР° РґРѕ {until.strftime('%Y-%m-%d')}."
                    )
                return
            if st in ("expired", "cancelled", "canceled", "failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=f"вќЊ CryptoBot: РѕРїР»Р°С‚Р° РЅРµ Р·Р°РІРµСЂС€РµРЅР° (СЃС‚Р°С‚СѓСЃ: {st})."
                    )
                return
            await asyncio.sleep(6.0)

        # РўР°Р№РјР°СѓС‚
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="вЊ› CryptoBot: РІСЂРµРјСЏ РѕР¶РёРґР°РЅРёСЏ РІС‹С€Р»Рѕ. РќР°Р¶РјРёС‚Рµ В«РџСЂРѕРІРµСЂРёС‚СЊ РѕРїР»Р°С‚СѓВ» РёР»Рё РѕРїР»Р°С‚РёС‚Рµ Р·Р°РЅРѕРІРѕ."
            )
    except Exception as e:
        log.exception("crypto poll (subscription) error: %s", e)


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РџСЂРµРґР»РѕР¶РµРЅРёРµ РїРѕРїРѕР»РЅРµРЅРёСЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def _send_topup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("500 в‚Ѕ",  callback_data="topup:rub:500"),
         InlineKeyboardButton("1000 в‚Ѕ", callback_data="topup:rub:1000"),
         InlineKeyboardButton("2000 в‚Ѕ", callback_data="topup:rub:2000")],
        [InlineKeyboardButton("Crypto $5",  callback_data="topup:crypto:5"),
         InlineKeyboardButton("Crypto $10", callback_data="topup:crypto:10"),
         InlineKeyboardButton("Crypto $20", callback_data="topup:crypto:20")],
    ])
    await update.effective_message.reply_text("Р’С‹Р±РµСЂРёС‚Рµ СЃСѓРјРјСѓ РїРѕРїРѕР»РЅРµРЅРёСЏ:", reply_markup=kb)


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РџРѕРїС‹С‚РєР° РѕРїР»Р°С‚РёС‚СЊ в†’ РІС‹РїРѕР»РЅРёС‚СЊ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def _try_pay_then_do(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    engine: str,                # 'luma' | 'runway' | 'img'
    est_cost_usd: float,
    coro_func,                  # async function to run
    remember_kind: str = "",
    remember_payload: dict | None = None
):
    username = (update.effective_user.username or "")
    ok, offer = _can_spend_or_offer(user_id, username, engine, est_cost_usd)
    if ok:
        await coro_func()
        return
    if offer == "ASK_SUBSCRIBE":
        await update.effective_message.reply_text(
            "Р”Р»СЏ РІС‹РїРѕР»РЅРµРЅРёСЏ РЅСѓР¶РµРЅ С‚Р°СЂРёС„ РёР»Рё РµРґРёРЅС‹Р№ Р±Р°Р»Р°РЅСЃ.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("в­ђ РўР°СЂРёС„С‹", web_app=WebAppInfo(url=TARIFF_URL))],
                 [InlineKeyboardButton("вћ• РџРѕРїРѕР»РЅРёС‚СЊ Р±Р°Р»Р°РЅСЃ", callback_data="topup")]]
            )
        )
        return
    try:
        need_usd = float(offer.split(":", 1)[-1])
    except Exception:
        need_usd = est_cost_usd
    amount_rub = _calc_oneoff_price_rub(engine, need_usd)
    await update.effective_message.reply_text(
        f"РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ Р»РёРјРёС‚Р°. Р Р°Р·РѕРІР°СЏ РїРѕРєСѓРїРєР° в‰€ {amount_rub} в‚Ѕ РёР»Рё РїРѕРїРѕР»РЅРёС‚Рµ Р±Р°Р»Р°РЅСЃ:",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("в­ђ РўР°СЂРёС„С‹", web_app=WebAppInfo(url=TARIFF_URL))],
                [InlineKeyboardButton("вћ• РџРѕРїРѕР»РЅРёС‚СЊ Р±Р°Р»Р°РЅСЃ", callback_data="topup")],
            ]
        ),
    )


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ /plans в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["в­ђ РўР°СЂРёС„С‹:"]
    for tier, terms in PLAN_PRICE_TABLE.items():
        lines.append(f"вЂ” {tier.upper()}: "
                     f"{terms['month']}в‚Ѕ/РјРµСЃ вЂў {terms['quarter']}в‚Ѕ/РєРІР°СЂС‚Р°Р» вЂў {terms['year']}в‚Ѕ/РіРѕРґ")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("РљСѓРїРёС‚СЊ START (1 РјРµСЃ)",    callback_data="buy:start:1"),
         InlineKeyboardButton("РљСѓРїРёС‚СЊ PRO (1 РјРµСЃ)",      callback_data="buy:pro:1")],
        [InlineKeyboardButton("РљСѓРїРёС‚СЊ ULTIMATE (1 РјРµСЃ)", callback_data="buy:ultimate:1")],
        [InlineKeyboardButton("РћС‚РєСЂС‹С‚СЊ РјРёРЅРё-РІРёС‚СЂРёРЅСѓ",    web_app=WebAppInfo(url=TARIFF_URL))]
    ])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb)


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РўРµРєСЃС‚РѕРІС‹Р№ РІС…РѕРґ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    # Р’РѕРїСЂРѕСЃС‹ Рѕ РІРѕР·РјРѕР¶РЅРѕСЃС‚СЏС…
    cap = capability_answer(text)
    if cap:
        await update.effective_message.reply_text(cap)
        return

    # РќР°РјС‘Рє РЅР° РІРёРґРµРѕ/РєР°СЂС‚РёРЅРєСѓ
    mtype, rest = detect_media_intent(text)
    if mtype == "video":
        duration, aspect = parse_video_opts(text)
        prompt = rest or re.sub(r"\b(\d+\s*(?:СЃРµРє|СЃ)\b|(?:9:16|16:9|1:1|4:5|3:4|4:3))", "", text, flags=re.I).strip(" ,.")
        if not prompt:
            await update.effective_message.reply_text("РћРїРёС€РёС‚Рµ, С‡С‚Рѕ РёРјРµРЅРЅРѕ СЃРЅСЏС‚СЊ, РЅР°РїСЂ.: В«СЂРµС‚СЂРѕ-Р°РІС‚Рѕ РЅР° Р±РµСЂРµРіСѓ, Р·Р°РєР°С‚В».")
            return
        aid = _new_aid()
        _pending_actions[aid] = {"prompt": prompt, "duration": duration, "aspect": aspect}
        est_luma = 0.40
        est_runway = max(1.0, RUNWAY_UNIT_COST_USD * (duration / max(1, RUNWAY_DURATION_S)))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"рџЋ¬ Luma (~${est_luma:.2f})",     callback_data=f"choose:luma:{aid}")],
            [InlineKeyboardButton(f"рџЋҐ Runway (~${est_runway:.2f})",  callback_data=f"choose:runway:{aid}")],
        ])
        await update.effective_message.reply_text(
            f"Р§С‚Рѕ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ?\nР”Р»РёС‚РµР»СЊРЅРѕСЃС‚СЊ: {duration} c вЂў РђСЃРїРµРєС‚: {aspect}\nР—Р°РїСЂРѕСЃ: В«{prompt}В»",
            reply_markup=kb
        )
        return
    if mtype == "image":
        prompt = rest or re.sub(r"^(img|image|picture)\s*[:\-]\s*", "", text, flags=re.I).strip()
        if not prompt:
            await update.effective_message.reply_text("Р¤РѕСЂРјР°С‚: /img <РѕРїРёСЃР°РЅРёРµ РёР·РѕР±СЂР°Р¶РµРЅРёСЏ>")
            return

        async def _go():
            await _do_img_generate(update, context, prompt)

        await _try_pay_then_do(update, context, update.effective_user.id, "img", IMG_COST_USD, _go)
        return

    # РћР±С‹С‡РЅС‹Р№ С‚РµРєСЃС‚ в†’ GPT
    ok, _, _ = check_text_and_inc(update.effective_user.id, update.effective_user.username or "")
    if not ok:
        await update.effective_message.reply_text(
            "Р›РёРјРёС‚ С‚РµРєСЃС‚РѕРІС‹С… Р·Р°РїСЂРѕСЃРѕРІ РЅР° СЃРµРіРѕРґРЅСЏ РёСЃС‡РµСЂРїР°РЅ. РћС„РѕСЂРјРёС‚Рµ в­ђ РїРѕРґРїРёСЃРєСѓ РёР»Рё РїРѕРїСЂРѕР±СѓР№С‚Рµ Р·Р°РІС‚СЂР°."
        )
        return

    user_id = update.effective_user.id
    try:
        mode  = _mode_get(user_id)
        track = _mode_track_get(user_id)
    except NameError:
        mode, track = "none", ""

    text_for_llm = text
    if mode and mode != "none":
        text_for_llm = f"[Р РµР¶РёРј: {mode}; РџРѕРґСЂРµР¶РёРј: {track or '-'}]\n{text}"

    if mode == "РЈС‡С‘Р±Р°" and track:
        await study_process_text(update, context, text)
        return

    reply = await ask_openai_text(text_for_llm)
    await update.effective_message.reply_text(reply)
    await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Р¤РѕС‚Рѕ / Р”РѕРєСѓРјРµРЅС‚С‹ / Р“РѕР»РѕСЃ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ph = update.message.photo[-1]
        f = await ph.get_file()
        data = await f.download_as_bytearray()
        img = bytes(data)
        _cache_photo(update.effective_user.id, img)

        caption = (update.message.caption or "").strip()
        if caption:
            tl = caption.lower()
            # РѕР¶РёРІРёС‚СЊ С„РѕС‚Рѕ в†’ Runway РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ
            if any(k in tl for k in ("РѕР¶РёРІРё", "Р°РЅРёРјРёСЂСѓ", "СЃРґРµР»Р°Р№ РІРёРґРµРѕ", "revive", "animate")):
                dur, asp = parse_video_opts(caption)
                prompt = re.sub(r"\b(РѕР¶РёРІРё|РѕР¶РёРІРёС‚СЊ|Р°РЅРёРјРёСЂСѓР№|Р°РЅРёРјРёСЂРѕРІР°С‚СЊ|СЃРґРµР»Р°Р№ РІРёРґРµРѕ|revive|animate)\b", "", caption, flags=re.I).strip(" ,.")
                async def _go():
                    await _run_runway_animate_photo(update, context, img, prompt, dur, asp)
                await _try_pay_then_do(update, context, update.effective_user.id, "runway",
                                       max(1.0, RUNWAY_UNIT_COST_USD * (dur / max(1, RUNWAY_DURATION_S))),
                                       _go, remember_kind="revive_photo",
                                       remember_payload={"duration": dur, "aspect": asp, "prompt": prompt})
                return

            # СѓРґР°Р»РёС‚СЊ С„РѕРЅ
            if any(k in tl for k in ("СѓРґР°Р»Рё С„РѕРЅ", "removebg", "СѓР±СЂР°С‚СЊ С„РѕРЅ")):
                await _pedit_removebg(update, context, img); return

            # Р·Р°РјРµРЅРёС‚СЊ С„РѕРЅ
            if any(k in tl for k in ("Р·Р°РјРµРЅРё С„РѕРЅ", "replacebg", "СЂР°Р·РјС‹С‚С‹Р№ С„РѕРЅ", "blur")):
                await _pedit_replacebg(update, context, img); return

            # outpaint
            if "outpaint" in tl or "СЂР°СЃС€РёСЂ" in tl:
                await _pedit_outpaint(update, context, img); return

            # СЂР°СЃРєР°РґСЂРѕРІРєР°
            if "СЂР°СЃРєР°РґСЂРѕРІ" in tl or "storyboard" in tl:
                await _pedit_storyboard(update, context, img); return

            # РєР°СЂС‚РёРЅРєР° РїРѕ РѕРїРёСЃР°РЅРёСЋ (Luma / С„РѕР»Р±СЌРє OpenAI)
            if any(k in tl for k in ("РєР°СЂС‚РёРЅ", "РёР·РѕР±СЂР°Р¶РµРЅ", "image", "img")) and any(k in tl for k in ("СЃРіРµРЅРµСЂРёСЂСѓ", "СЃРѕР·РґР°", "СЃРґРµР»Р°Р№")):
                await _start_luma_img(update, context, caption); return

        # РµСЃР»Рё СЏРІРЅРѕР№ РєРѕРјР°РЅРґС‹ РІ РїРѕРґРїРёСЃРё РЅРµС‚ вЂ” РїРѕРєР°Р·С‹РІР°РµРј Р±С‹СЃС‚СЂС‹Рµ РєРЅРѕРїРєРё
        await update.effective_message.reply_text("Р¤РѕС‚Рѕ РїРѕР»СѓС‡РµРЅРѕ. Р§С‚Рѕ СЃРґРµР»Р°С‚СЊ?",
                                                  reply_markup=photo_quick_actions_kb())
    except Exception as e:
        log.exception("on_photo error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("РќРµ СЃРјРѕРі РѕР±СЂР°Р±РѕС‚Р°С‚СЊ С„РѕС‚Рѕ.")

async def on_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document:
            return
        doc = update.message.document
        mt = (doc.mime_type or "").lower()
        tg_file = await doc.get_file()
        data = await tg_file.download_as_bytearray()
        raw = bytes(data)

        if mt.startswith("image/"):
            _cache_photo(update.effective_user.id, raw)
            await update.effective_message.reply_text("РР·РѕР±СЂР°Р¶РµРЅРёРµ РїРѕР»СѓС‡РµРЅРѕ РєР°Рє РґРѕРєСѓРјРµРЅС‚. Р§С‚Рѕ СЃРґРµР»Р°С‚СЊ?", reply_markup=photo_quick_actions_kb())
            return

        text, kind = extract_text_from_document(raw, doc.file_name or "file")
        if not (text or "").strip():
            await update.effective_message.reply_text(f"РќРµ СѓРґР°Р»РѕСЃСЊ РёР·РІР»РµС‡СЊ С‚РµРєСЃС‚ РёР· {kind}.")
            return

        goal = (update.message.caption or "").strip() or None
        await update.effective_message.reply_text(f"рџ“„ РР·РІР»РµРєР°СЋ С‚РµРєСЃС‚ ({kind}), РіРѕС‚РѕРІР»СЋ РєРѕРЅСЃРїРµРєС‚вЂ¦")
        summary = await summarize_long_text(text, query=goal)
        summary = summary or "Р“РѕС‚РѕРІРѕ."
        await update.effective_message.reply_text(summary)
        await maybe_tts_reply(update, context, summary[:TTS_MAX_CHARS])
    except Exception as e:
        log.exception("on_doc error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("РћС€РёР±РєР° РїСЂРё РѕР±СЂР°Р±РѕС‚РєРµ РґРѕРєСѓРјРµРЅС‚Р°.")

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.voice:
            return
        vf = await update.message.voice.get_file()
        bio = BytesIO(await vf.download_as_bytearray())
        bio.seek(0)
        setattr(bio, "name", f"voice.ogg")
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        text = await transcribe_audio(bio, "voice.ogg")
        if not text:
            await update.effective_message.reply_text("РќРµ СѓРґР°Р»РѕСЃСЊ СЂР°СЃРїРѕР·РЅР°С‚СЊ СЂРµС‡СЊ.")
            return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_voice error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("РћС€РёР±РєР° РїСЂРё РѕР±СЂР°Р±РѕС‚РєРµ voice.")

async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.audio:
            return
        af = await update.message.audio.get_file()
        filename = update.message.audio.file_name or "audio.mp3"
        bio = BytesIO(await af.download_as_bytearray())
        bio.seek(0)
        setattr(bio, "name", filename)
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        text = await transcribe_audio(bio, filename)
        if not text:
            await update.effective_message.reply_text("РќРµ СѓРґР°Р»РѕСЃСЊ СЂР°СЃРїРѕР·РЅР°С‚СЊ СЂРµС‡СЊ РёР· Р°СѓРґРёРѕ.")
            return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_audio error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("РћС€РёР±РєР° РїСЂРё РѕР±СЂР°Р±РѕС‚РєРµ Р°СѓРґРёРѕ.")


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РћР±СЂР°Р±РѕС‚С‡РёРє РѕС€РёР±РѕРє PTB в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def on_error(update: object, context_: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error: %s", context_.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("РЈРїСЃ, РїСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР°. РЇ СѓР¶Рµ СЂР°Р·Р±РёСЂР°СЋСЃСЊ.")
    except Exception:
        pass


# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Р РѕСѓС‚РµСЂС‹ РґР»СЏ С‚РµРєСЃС‚РѕРІС‹С… РєРЅРѕРїРѕРє/СЂРµР¶РёРјРѕРІ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def on_btn_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_engines(update, context)

async def on_btn_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_balance(update, context)

async def on_btn_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = _plans_overview_text(user_id)
    await update.effective_message.reply_text(text, reply_markup=plans_root_kb())

async def on_mode_school_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "рџЋ“ *РЈС‡С‘Р±Р°*\n"
        "РџРѕРјРѕРіСѓ: РєРѕРЅСЃРїРµРєС‚С‹ РёР· PDF/EPUB/DOCX/TXT, СЂР°Р·Р±РѕСЂ Р·Р°РґР°С‡ РїРѕС€Р°РіРѕРІРѕ, СЌСЃСЃРµ/СЂРµС„РµСЂР°С‚С‹, РјРёРЅРё-РєРІРёР·С‹.\n\n"
        "_Р‘С‹СЃС‚СЂС‹Рµ РґРµР№СЃС‚РІРёСЏ:_\n"
        "вЂў Р Р°Р·РѕР±СЂР°С‚СЊ PDF в†’ РєРѕРЅСЃРїРµРєС‚\n"
        "вЂў РЎРѕРєСЂР°С‚РёС‚СЊ РІ С€РїР°СЂРіР°Р»РєСѓ\n"
        "вЂў РћР±СЉСЏСЃРЅРёС‚СЊ С‚РµРјСѓ СЃ РїСЂРёРјРµСЂР°РјРё\n"
        "вЂў РџР»Р°РЅ РѕС‚РІРµС‚Р° / РїСЂРµР·РµРЅС‚Р°С†РёРё"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown")

async def on_mode_work_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "рџ’ј *Р Р°Р±РѕС‚Р°*\n"
        "РџРёСЃСЊРјР°/Р±СЂРёС„С‹/СЂРµР·СЋРјРµ/Р°РЅР°Р»РёС‚РёРєР°, ToDo/РїР»Р°РЅС‹, СЃРІРѕРґРЅС‹Рµ С‚Р°Р±Р»РёС†С‹ РёР· РґРѕРєСѓРјРµРЅС‚РѕРІ.\n"
        "Р”Р»СЏ Р°СЂС…РёС‚РµРєС‚РѕСЂР°/РґРёР·Р°Р№РЅРµСЂР°/РїСЂРѕРµРєС‚РёСЂРѕРІС‰РёРєР° вЂ” СЃС‚СЂСѓРєС‚СѓСЂРёСЂРѕРІР°РЅРёРµ РўР—, С‡РµРє-Р»РёСЃС‚С‹ СЃС‚Р°РґРёР№, "
        "СЃРІРѕРґРЅС‹Рµ С‚Р°Р±Р»РёС†С‹ Р»РёСЃС‚РѕРІ, РїРѕСЏСЃРЅРёС‚РµР»СЊРЅС‹Рµ Р·Р°РїРёСЃРєРё.\n\n"
        "_Р“РёР±СЂРёРґС‹:_ GPT-5 (С‚РµРєСЃС‚/Р»РѕРіРёРєР°) + Images (РёР»Р»СЋСЃС‚СЂР°С†РёРё) + Luma/Runway (РєР»РёРїС‹/РјРѕРєР°РїС‹).\n\n"
        "_Р‘С‹СЃС‚СЂС‹Рµ РґРµР№СЃС‚РІРёСЏ:_\n"
        "вЂў РЎС„РѕСЂРјРёСЂРѕРІР°С‚СЊ Р±СЂРёС„/РўР—\n"
        "вЂў РЎРІРµСЃС‚Рё С‚СЂРµР±РѕРІР°РЅРёСЏ РІ С‚Р°Р±Р»РёС†Сѓ\n"
        "вЂў РЎРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ РїРёСЃСЊРјРѕ/СЂРµР·СЋРјРµ\n"
        "вЂў Р§РµСЂРЅРѕРІРёРє РїСЂРµР·РµРЅС‚Р°С†РёРё"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown")

async def on_mode_fun_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "рџ”Ґ *Р Р°Р·РІР»РµС‡РµРЅРёСЏ*\n"
        "Р¤РѕС‚Рѕ-РјР°СЃС‚РµСЂСЃРєР°СЏ: СѓРґР°Р»РёС‚СЊ/Р·Р°РјРµРЅРёС‚СЊ С„РѕРЅ, РґРѕР±Р°РІРёС‚СЊ/СѓР±СЂР°С‚СЊ РѕР±СЉРµРєС‚/С‡РµР»РѕРІРµРєР°, outpaint, "
        "*РѕР¶РёРІР»РµРЅРёРµ СЃС‚Р°СЂС‹С… С„РѕС‚Рѕ*.\n"
        "Р’РёРґРµРѕ: Luma/Runway вЂ” РєР»РёРїС‹ РїРѕРґ Reels/Shorts; *Reels РїРѕ СЃРјС‹СЃР»Сѓ РёР· С†РµР»СЊРЅРѕРіРѕ РІРёРґРµРѕ* "
        "(СѓРјРЅР°СЏ РЅР°СЂРµР·РєР°), Р°РІС‚Рѕ-С‚Р°Р№РјРєРѕРґС‹. РњРµРјС‹/РєРІРёР·С‹.\n\n"
        "Р’С‹Р±РµСЂРё РґРµР№СЃС‚РІРёРµ РЅРёР¶Рµ:"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown", reply_markup=_fun_quick_kb())

# в”Ђв”Ђв”Ђв”Ђв”Ђ РљР»Р°РІРёР°С‚СѓСЂР° В«Р Р°Р·РІР»РµС‡РµРЅРёСЏВ» СЃ РЅРѕРІС‹РјРё РєРЅРѕРїРєР°РјРё в”Ђв”Ђв”Ђв”Ђв”Ђ
def _fun_quick_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("рџЋ­ РРґРµРё РґР»СЏ РґРѕСЃСѓРіР°", callback_data="fun:ideas")],
        [InlineKeyboardButton("рџЋ¬ РЎС†РµРЅР°СЂРёР№ С€РѕСЂС‚Р°", callback_data="fun:storyboard")],
        [InlineKeyboardButton("рџЋ® РРіСЂС‹/РєРІРёР·",       callback_data="fun:quiz")],
        # РќРѕРІС‹Рµ РєР»СЋС‡РµРІС‹Рµ РєРЅРѕРїРєРё
        [
            InlineKeyboardButton("рџЄ„ РћР¶РёРІРёС‚СЊ СЃС‚Р°СЂРѕРµ С„РѕС‚Рѕ", callback_data="fun:revive"),
            InlineKeyboardButton("рџЋ¬ Reels РёР· РґР»РёРЅРЅРѕРіРѕ РІРёРґРµРѕ", callback_data="fun:smartreels"),
        ],
        [
            InlineKeyboardButton("рџЋҐ Runway",      callback_data="fun:clip"),
            InlineKeyboardButton("рџЋЁ Midjourney",  callback_data="fun:img"),
            InlineKeyboardButton("рџ”Љ STT/TTS",     callback_data="fun:speech"),
        ],
        [InlineKeyboardButton("рџ“ќ РЎРІРѕР±РѕРґРЅС‹Р№ Р·Р°РїСЂРѕСЃ", callback_data="fun:free")],
        [InlineKeyboardButton("в¬…пёЏ РќР°Р·Р°Рґ", callback_data="fun:back")],
    ]
    return InlineKeyboardMarkup(rows)

# в”Ђв”Ђв”Ђв”Ђв”Ђ РћР±СЂР°Р±РѕС‚С‡РёРє Р±С‹СЃС‚СЂС‹С… РґРµР№СЃС‚РІРёР№ В«Р Р°Р·РІР»РµС‡РµРЅРёСЏВ» (fallback-friendly) в”Ђв”Ђв”Ђв”Ђв”Ђ
async def on_cb_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()
    action = data.split(":", 1)[1] if ":" in data else ""

    # РџРѕРјРѕС‰РЅРёРєРё: РµСЃР»Рё РІ РїСЂРѕРµРєС‚Рµ РѕР±СЉСЏРІР»РµРЅС‹ РєРѕРЅРєСЂРµС‚РЅС‹Рµ СЂРµР°Р»РёР·Р°С†РёРё вЂ” РІС‹Р·С‹РІР°РµРј РёС….
    async def _try_call(*fn_names, **kwargs):
        fn = _pick_first_defined(*fn_names)
        if callable(fn):
            return await fn(update, context, **kwargs)
        return None

    if action == "revive":
        # РџС‹С‚Р°РµРјСЃСЏ РґРµСЂРЅСѓС‚СЊ С‚РІРѕР№ СЂРµР°Р»СЊРЅС‹Р№ РїР°Р№РїР»Р°Р№РЅ РґР»СЏ РѕР¶РёРІР»РµРЅРёСЏ С„РѕС‚Рѕ (РµСЃР»Рё РµСЃС‚СЊ)
        if await _try_call("revive_old_photo_flow", "do_revive_photo"):
            return
        # Fallback: РёРЅСЃС‚СЂСѓРєС†РёСЏ
        await q.answer("РћР¶РёРІР»РµРЅРёРµ С„РѕС‚Рѕ")
        await q.edit_message_text(
            "рџЄ„ *РћР¶РёРІР»РµРЅРёРµ СЃС‚Р°СЂРѕРіРѕ С„РѕС‚Рѕ*\n"
            "РџСЂРёС€Р»Рё/РїРµСЂРµС€Р»Рё СЃСЋРґР° С„РѕС‚Рѕ Рё РєРѕСЂРѕС‚РєРѕ РѕРїРёС€Рё, С‡С‚Рѕ РЅСѓР¶РЅРѕ РѕР¶РёРІРёС‚СЊ "
            "(РјРёРіР°РЅРёРµ РіР»Р°Р·, Р»С‘РіРєР°СЏ СѓР»С‹Р±РєР°, РґРІРёР¶РµРЅРёРµ С„РѕРЅР° Рё С‚.Рї.). "
            "РЇ РїРѕРґРіРѕС‚РѕРІР»СЋ Р°РЅРёРјР°С†РёСЋ Рё РІРµСЂРЅСѓ РїСЂРµРІСЊСЋ/РІРёРґРµРѕ.",
            parse_mode="Markdown",
            reply_markup=_fun_quick_kb()
        )
        return

    if action == "smartreels":
        if await _try_call("smart_reels_from_video", "video_sense_reels"):
            return
        await q.answer("Reels РёР· РґР»РёРЅРЅРѕРіРѕ РІРёРґРµРѕ")
        await q.edit_message_text(
            "рџЋ¬ *Reels РёР· РґР»РёРЅРЅРѕРіРѕ РІРёРґРµРѕ*\n"
            "РџСЂРёС€Р»Рё РґР»РёРЅРЅРѕРµ РІРёРґРµРѕ (РёР»Рё СЃСЃС‹Р»РєСѓ) + С‚РµРјСѓ/Р¦Рђ. "
            "РЎРґРµР»Р°СЋ СѓРјРЅСѓСЋ РЅР°СЂРµР·РєСѓ (hook в†’ value в†’ CTA), СЃСѓР±С‚РёС‚СЂС‹ Рё С‚Р°Р№РјРєРѕРґС‹. "
            "РЎРєР°Р¶Рё С„РѕСЂРјР°С‚: 9:16 РёР»Рё 1:1.",
            parse_mode="Markdown",
            reply_markup=_fun_quick_kb()
        )
        return

    if action == "clip":
        if await _try_call("start_runway_flow", "luma_make_clip", "runway_make_clip"):
            return
        await q.answer()
        await q.edit_message_text("Р—Р°РїСѓСЃС‚Рё /diag_video С‡С‚РѕР±С‹ РїСЂРѕРІРµСЂРёС‚СЊ РєР»СЋС‡Рё Luma/Runway.", reply_markup=_fun_quick_kb())
        return

    if action == "img":
        # /img РёР»Рё С‚РІРѕР№ РєР°СЃС‚РѕРј
        if await _try_call("cmd_img", "midjourney_flow", "images_make"):
            return
        await q.answer()
        await q.edit_message_text("Р’РІРµРґРё /img Рё С‚РµРјСѓ РєР°СЂС‚РёРЅРєРё, РёР»Рё РїСЂРёС€Р»Рё СЂРµС„С‹.", reply_markup=_fun_quick_kb())
        return

    if action == "storyboard":
        if await _try_call("start_storyboard", "storyboard_make"):
            return
        await q.answer()
        await q.edit_message_text("РќР°РїРёС€Рё С‚РµРјСѓ С€РѕСЂС‚Р° вЂ” РЅР°РєРёРґР°СЋ СЃС‚СЂСѓРєС‚СѓСЂСѓ Рё СЂР°СЃРєР°РґСЂРѕРІРєСѓ.", reply_markup=_fun_quick_kb())
        return

    if action in {"ideas", "quiz", "speech", "free", "back"}:
        await q.answer()
        await q.edit_message_text(
            "Р“РѕС‚РѕРІ! РќР°РїРёС€Рё Р·Р°РґР°С‡Сѓ РёР»Рё РІС‹Р±РµСЂРё РєРЅРѕРїРєСѓ РІС‹С€Рµ.",
            reply_markup=_fun_quick_kb()
        )
        return

    await q.answer()

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Р РѕСѓС‚РµСЂС‹-РєРЅРѕРїРєРё СЂРµР¶РёРјРѕРІ (РµРґРёРЅР°СЏ С‚РѕС‡РєР° РІС…РѕРґР°) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
async def on_btn_study(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fn = globals().get("_send_mode_menu")
    if callable(fn):
        return await fn(update, context, "study")
    return await on_mode_school_text(update, context)

async def on_btn_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fn = globals().get("_send_mode_menu")
    if callable(fn):
        return await fn(update, context, "work")
    return await on_mode_work_text(update, context)

async def on_btn_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fn = globals().get("_send_mode_menu")
    if callable(fn):
        return await fn(update, context, "fun")
    return await on_mode_fun_text(update, context)

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ РџРѕР·РёС‚РёРІРЅС‹Р№ Р°РІС‚Рѕ-РѕС‚РІРµС‚ РїСЂРѕ РІРѕР·РјРѕР¶РЅРѕСЃС‚Рё (С‚РµРєСЃС‚/РіРѕР»РѕСЃ) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
_CAPS_PATTERN = (
    r"(?is)(СѓРјРµРµС€СЊ|РјРѕР¶РµС€СЊ|РґРµР»Р°РµС€СЊ|Р°РЅР°Р»РёР·РёСЂСѓРµС€СЊ|СЂР°Р±РѕС‚Р°РµС€СЊ|РїРѕРґРґРµСЂР¶РёРІР°РµС€СЊ|СѓРјРµРµС‚ Р»Рё|РјРѕР¶РµС‚ Р»Рё)"
    r".{0,120}"
    r"(pdf|epub|fb2|docx|txt|РєРЅРёРі|РєРЅРёРіР°|РёР·РѕР±СЂР°Р¶РµРЅ|С„РѕС‚Рѕ|РєР°СЂС‚РёРЅ|image|jpeg|png|video|РІРёРґРµРѕ|mp4|mov|Р°СѓРґРёРѕ|audio|mp3|wav)"
)

async def on_capabilities_qa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Р”Р°, СѓРјРµСЋ СЂР°Р±РѕС‚Р°С‚СЊ СЃ С„Р°Р№Р»Р°РјРё Рё РјРµРґРёР°:\n"
        "вЂў рџ“„ Р”РѕРєСѓРјРµРЅС‚С‹: PDF/EPUB/FB2/DOCX/TXT вЂ” РєРѕРЅСЃРїРµРєС‚, СЂРµР·СЋРјРµ, РёР·РІР»РµС‡РµРЅРёРµ С‚Р°Р±Р»РёС†, РїСЂРѕРІРµСЂРєР° С„Р°РєС‚РѕРІ.\n"
        "вЂў рџ–ј РР·РѕР±СЂР°Р¶РµРЅРёСЏ: Р°РЅР°Р»РёР·/РѕРїРёСЃР°РЅРёРµ, СѓР»СѓС‡С€РµРЅРёРµ, С„РѕРЅ, СЂР°Р·РјРµС‚РєР°, РјРµРјС‹, outpaint.\n"
        "вЂў рџЋћ Р’РёРґРµРѕ: СЂР°Р·Р±РѕСЂ СЃРјС‹СЃР»Р°, С‚Р°Р№РјРєРѕРґС‹, *Reels РёР· РґР»РёРЅРЅРѕРіРѕ РІРёРґРµРѕ*, РёРґРµРё/СЃРєСЂРёРїС‚, СЃСѓР±С‚РёС‚СЂС‹.\n"
        "вЂў рџЋ§ РђСѓРґРёРѕ/РєРЅРёРіРё: С‚СЂР°РЅСЃРєСЂРёРїС†РёСЏ, С‚РµР·РёСЃС‹, РїР»Р°РЅ.\n\n"
        "_РџРѕРґСЃРєР°Р·РєРё:_ РїСЂРѕСЃС‚Рѕ Р·Р°РіСЂСѓР·РёС‚Рµ С„Р°Р№Р» РёР»Рё РїСЂРёС€Р»РёС‚Рµ СЃСЃС‹Р»РєСѓ + РєРѕСЂРѕС‚РєРѕРµ РўР—. "
        "Р”Р»СЏ С„РѕС‚Рѕ вЂ” РјРѕР¶РЅРѕ РЅР°Р¶Р°С‚СЊ В«рџЄ„ РћР¶РёРІРёС‚СЊ СЃС‚Р°СЂРѕРµ С„РѕС‚РѕВ», РґР»СЏ РІРёРґРµРѕ вЂ” В«рџЋ¬ Reels РёР· РґР»РёРЅРЅРѕРіРѕ РІРёРґРµРѕВ»."
    )
    await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=_fun_quick_kb())

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅРѕРµ: РІР·СЏС‚СЊ РїРµСЂРІСѓСЋ РѕР±СЉСЏРІР»РµРЅРЅСѓСЋ С„СѓРЅРєС†РёСЋ РїРѕ РёРјРµРЅРё в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
def _pick_first_defined(*names):
    for n in names:
        fn = globals().get(n)
        if callable(fn):
            return fn
    return None

# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ Р РµРіРёСЃС‚СЂР°С†РёСЏ С…РµРЅРґР»РµСЂРѕРІ Рё Р·Р°РїСѓСЃРє в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
def build_application() -> "Application":
    if not BOT_TOKEN:
        raise RuntimeError("РќРµ Р·Р°РґР°РЅ BOT_TOKEN РІ РїРµСЂРµРјРµРЅРЅС‹С… РѕРєСЂСѓР¶РµРЅРёСЏ.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # РљРѕРјР°РЅРґС‹
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

    # РџР»Р°С‚РµР¶Рё
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    # >>> PATCH START вЂ” Handlers wiring (WebApp + callbacks + media + text) >>>

    # Р”Р°РЅРЅС‹Рµ РёР· РјРёРЅРё-РїСЂРёР»РѕР¶РµРЅРёСЏ (WebApp)
    with contextlib.suppress(Exception):
        app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))
    with contextlib.suppress(Exception):
        if hasattr(filters, "WEB_APP_DATA"):
            app.add_handler(MessageHandler(filters.WEB_APP_DATA, on_webapp_data))

    # === РџРђРўР§ 4: РџРѕСЂСЏРґРѕРє callback-С…РµРЅРґР»РµСЂРѕРІ (СѓР·РєРёРµ в†’ РѕР±С‰РёРµ) ===
    # 1) РџРѕРґРїРёСЃРєР°/РѕРїР»Р°С‚С‹
    app.add_handler(CallbackQueryHandler(on_cb_plans, pattern=r"^(?:plan:|pay:)$|^(?:plan:|pay:).+"))

    # 2) Р РµР¶РёРјС‹/РїРѕРґРјРµРЅСЋ (РїРѕРґРґРµСЂР¶РёРј Рё СЃС‚Р°СЂС‹Рµ, Рё РЅРѕРІС‹Рµ РїСЂРµС„РёРєСЃС‹)
    app.add_handler(CallbackQueryHandler(on_cb_mode,  pattern=r"^(?:mode:|act:|school:|work:)"))

    # 3) Р‘С‹СЃС‚СЂС‹Рµ СЂР°Р·РІР»РµС‡РµРЅРёСЏ (Р»СЋР±С‹Рµ fun:...)
    app.add_handler(CallbackQueryHandler(on_cb_fun,   pattern=r"^fun:[a-z_]+$"))

    # 4) РћСЃС‚Р°Р»СЊРЅРѕР№ catch-all (pedit/topup/engine/buy Рё С‚.Рї.)
    # Р Р°Р·РјРµС‰Р°РµРј РІ РїСЂРёРѕСЂРёС‚РµС‚РЅРѕР№ РіСЂСѓРїРїРµ, С‡С‚РѕР±С‹ РєРѕР»Р±СЌРєРё РѕР±СЂР°Р±Р°С‚С‹РІР°Р»РёСЃСЊ СЃСЂР°Р·Сѓ
    app.add_handler(CallbackQueryHandler(on_cb), group=0)

    # Р“РѕР»РѕСЃ/Р°СѓРґРёРѕ вЂ” РѕС‚РЅРѕСЃРёРј Рє РјРµРґРёР°РіСЂСѓРїРїРµ (РёРґС‘С‚ СЂР°РЅСЊС€Рµ РѕР±С‰РµРіРѕ С‚РµРєСЃС‚РѕРІРѕРіРѕ С…РµРЅРґР»РµСЂР°)
    voice_fn = _pick_first_defined("handle_voice", "on_voice", "voice_handler")
    if voice_fn:
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_fn), group=1)

    # === РџРђРўР§ 3: РўРµРєСЃС‚РѕРІС‹Р№ РІС‹Р±РѕСЂ В«РЈС‡С‘Р±Р° / Р Р°Р±РѕС‚Р° / Р Р°Р·РІР»РµС‡РµРЅРёСЏВ» С‡РµСЂРµР· on_mode_text ===
    # РЈР”РђР›Р•РќРћ РєР°Рє РґСѓР±Р»СЊ: С‚РµРєСЃС‚РѕРІС‹Рµ РІР°СЂРёР°РЅС‚С‹ СѓР¶Рµ РїРѕРєСЂС‹С‚С‹ BTN_STUDY/BTN_WORK/BTN_FUN РІС‹С€Рµ.
    # РЎРўРђР’РРњ Р”Рћ РѕСЃС‚Р°Р»СЊРЅС‹С… С‚РµРєСЃС‚РѕРІС‹С… РєРЅРѕРїРѕРє Рё Р”Рћ РѕР±С‰РµРіРѕ С‚РµРєСЃС‚РѕРІРѕРіРѕ С…РµРЅРґР»РµСЂР°
    app.add_handler(MessageHandler(
        filters.TEXT & (
            filters.Regex(r"^рџЋ“ РЈС‡С‘Р±Р°$") |
            filters.Regex(r"^рџ’ј Р Р°Р±РѕС‚Р°$") |
            filters.Regex(r"^рџ”Ґ Р Р°Р·РІР»РµС‡РµРЅРёСЏ$")
        ),
        on_mode_text
    ))

    # РўРµРєСЃС‚РѕРІС‹Рµ РєРЅРѕРїРєРё/СЏСЂР»С‹РєРё (РѕСЃС‚Р°Р»СЊРЅС‹Рµ) вЂ” Р§РРЎРўРћ Р±РµР· РґСѓР±Р»РµР№
    import re

    # РЎС‚СЂРѕРіРёРµ РїР°С‚С‚РµСЂРЅС‹: РѕРґРЅРѕ РЅР°Р·РІР°РЅРёРµ = РѕРґРёРЅ С…РµРЅРґР»РµСЂ (СЌРјРѕРґР·Рё РґРѕРїСѓСЃРєР°РµРј, Р»РёС€РЅРёРµ РїСЂРѕР±РµР»С‹ вЂ” С‚РѕР¶Рµ)
    BTN_ENGINES = re.compile(r"^\s*(?:рџ§ \s*)?Р”РІРёР¶РєРё\s*$")
    BTN_BALANCE = re.compile(r"^\s*(?:рџ’і|рџ§ѕ)?\s*Р‘Р°Р»Р°РЅСЃ\s*$")
    BTN_PLANS   = re.compile(r"^\s*(?:в­ђ\s*)?РџРѕРґРїРёСЃРєР°(?:\s*[В·вЂў]\s*РџРѕРјРѕС‰СЊ)?\s*$")
    BTN_STUDY   = re.compile(r"^\s*(?:рџЋ“\s*)?РЈС‡[РµС‘]Р±Р°\s*$")
    BTN_WORK    = re.compile(r"^\s*(?:рџ’ј\s*)?Р Р°Р±РѕС‚Р°\s*$")
    BTN_FUN     = re.compile(r"^\s*(?:рџ”Ґ\s*)?Р Р°Р·РІР»РµС‡РµРЅРёСЏ\s*$")

    # РљРЅРѕРїРєРё РІ РїСЂРёРѕСЂРёС‚РµС‚РЅРѕР№ РіСЂСѓРїРїРµ (0), С‡С‚РѕР±С‹ РѕРЅРё СЃСЂР°Р±Р°С‚С‹РІР°Р»Рё СЂР°РЅСЊС€Рµ Р»СЋР±С‹С… РѕР±С‰РёС… РѕР±СЂР°Р±РѕС‚С‡РёРєРѕРІ
    app.add_handler(MessageHandler(filters.Regex(BTN_ENGINES), on_btn_engines), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_BALANCE), on_btn_balance), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_PLANS),   on_btn_plans),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_STUDY),   on_btn_study),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_WORK),    on_btn_work),    group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_FUN),     on_btn_fun),     group=0)

    # вћ• РџРѕР·РёС‚РёРІРЅС‹Р№ Р°РІС‚Рѕ-РѕС‚РІРµС‚ РЅР° В«Р° СѓРјРµРµС€СЊ Р»РёвЂ¦В» вЂ” РґРѕ РѕР±С‰РµРіРѕ С‚РµРєСЃС‚Р° (РѕС‚РґРµР»СЊРЅР°СЏ РіСЂСѓРїРїР°, РЅРёР¶Рµ РєРЅРѕРїРѕРє)
    app.add_handler(MessageHandler(filters.Regex(_CAPS_PATTERN), on_capabilities_qa), group=1)

    # РњРµРґРёР° (С„РѕС‚Рѕ/РґРѕРєРё/РІРёРґРµРѕ/РіРёС„) вЂ” С‚РѕР¶Рµ РїРµСЂРµРґ РѕР±С‰РёРј С‚РµРєСЃС‚РѕРј
    photo_fn = _pick_first_defined("handle_photo", "on_photo", "photo_handler", "handle_image_message")
    if photo_fn:
        app.add_handler(MessageHandler(filters.PHOTO, photo_fn), group=1)

    doc_fn = _pick_first_defined("handle_doc", "on_document", "handle_document", "doc_handler")
    if doc_fn:
        app.add_handler(MessageHandler(filters.Document.ALL, doc_fn), group=1)

    video_fn = _pick_first_defined("handle_video", "on_video", "video_handler")
    if video_fn:
        app.add_handler(MessageHandler(filters.VIDEO, video_fn), group=1)

    gif_fn = _pick_first_defined("handle_gif", "on_gif", "animation_handler")
    if gif_fn:
        app.add_handler(MessageHandler(filters.ANIMATION, gif_fn), group=1)

    # >>> PATCH END <<<

    # РћР±С‰РёР№ С‚РµРєСЃС‚ вЂ” РЎРђРњР«Р™ РїРѕСЃР»РµРґРЅРёР№ (РЅРёР¶Рµ РІСЃРµС… С‡Р°СЃС‚РЅС‹С… РєРµР№СЃРѕРІ)
    text_fn = _pick_first_defined("handle_text", "on_text", "text_handler", "default_text_handler")
    if text_fn:
        btn_filters = (filters.Regex(BTN_ENGINES) | filters.Regex(BTN_BALANCE) |
                       filters.Regex(BTN_PLANS)   | filters.Regex(BTN_STUDY)   |
                       filters.Regex(BTN_WORK)    | filters.Regex(BTN_FUN))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~btn_filters, text_fn), group=2)

    # РћС€РёР±РєРё
    err_fn = _pick_first_defined("on_error", "handle_error")
    if err_fn:
        app.add_error_handler(err_fn)

    return app


# === main() СЃ Р±РµР·РѕРїР°СЃРЅРѕР№ РёРЅРёС†РёР°Р»РёР·Р°С†РёРµР№ Р‘Р” (Р±РµР· РёР·РјРµРЅРµРЅРёР№ РїРѕ СЃСѓС‚Рё) ===
def main():
    with contextlib.suppress(Exception):
        db_init()
    with contextlib.suppress(Exception):
        db_init_usage()
    with contextlib.suppress(Exception):
        _db_init_prefs()

    app = build_application()

    if USE_WEBHOOK:
        log.info("рџљЂ WEBHOOK mode. Public URL: %s  Path: %s  Port: %s", PUBLIC_URL, WEBHOOK_PATH, PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH.lstrip("/"),
            webhook_url=f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}",
            secret_token=(WEBHOOK_SECRET or None),
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        log.info("рџљЂ POLLING mode.")
        with contextlib.suppress(Exception):
            asyncio.get_event_loop().run_until_complete(
                app.bot.delete_webhook(drop_pending_updates=True)
            )
        app.run_polling(
            close_loop=False,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
        )


if __name__ == "__main__":
    main()
# === END PATCH ===
