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
# ───────── TTS imports ─────────
import contextlib  # уже у тебя выше есть, дублировать НЕ надо, если импорт стоит

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

# ───────── LOGGING ─────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")

# ───────── ENV ─────────
BOT_TOKEN = (os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
BOT_USERNAME     = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
PUBLIC_URL       = os.environ.get("PUBLIC_URL", "").strip()
WEBAPP_URL       = os.environ.get("WEBAPP_URL", "").strip()

OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL  = os.environ.get("OPENAI_BASE_URL", "").strip()        # OpenRouter или свой прокси для текста
OPENAI_MODEL     = os.environ.get("OPENAI_MODEL", "openai/gpt-4o-mini").strip()
# ==== RUNWAY CONFIG ====
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY", "")
RUNWAY_BASE = "https://api.runwayml.com/v1"  # именно api.runwayml.com
# ==== /RUNWAY CONFIG ====

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
# Luma Images (опционально: если нет — используем OpenAI Images как фолбэк)
LUMA_IMG_BASE_URL = os.environ.get("LUMA_IMG_BASE_URL", "").strip().rstrip("/")
LUMA_IMG_MODEL    = os.environ.get("LUMA_IMG_MODEL", "imagine-image-1").strip()

# Фолбэки Luma
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

# Таймауты
LUMA_MAX_WAIT_S     = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)
RUNWAY_MAX_WAIT_S   = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "1200").strip() or 1200)
VIDEO_POLL_DELAY_S  = float((os.environ.get("VIDEO_POLL_DELAY_S") or "6.0").strip() or 6.0)

# ───────── UTILS ---------
_LUMA_ACTIVE_BASE = None  # кэш последнего живого базового URL

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

# Если хотим вебхук, но PUBLIC_URL некорректный — не валимся, просто уходим в polling
# Webhook-only: никаких fallback на polling
if USE_WEBHOOK:
    assert PUBLIC_URL and PUBLIC_URL.startswith("https://"), (
        "PUBLIC_URL обязателен и должен начинаться с https:// для webhook-режима"
    )

# Без ключа тексты работать не будут, но не роняем процесс
if not OPENAI_API_KEY:
    log.warning("OPENAI_API_KEY не задан — текстовые функции будут недоступны до установки ключа.")

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

# Tavily (опционально)
try:
    if TAVILY_API_KEY:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
    else:
        tavily = None
except Exception:
    tavily = None

# ───────── DB: subscriptions / usage / wallet / kv ─────────
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
    # миграции
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

# === ЕДИНЫЙ КОШЕЛЁК (USD) ===
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

# ───────── Лимиты/цены ─────────
USD_RUB = float(os.environ.get("USD_RUB", "100"))
ONEOFF_MARKUP_DEFAULT = float(os.environ.get("ONEOFF_MARKUP_DEFAULT", "1.0"))
ONEOFF_MARKUP_RUNWAY  = float(os.environ.get("ONEOFF_MARKUP_RUNWAY",  "0.5"))
LUMA_RES_HINT = os.environ.get("LUMA_RES", "720p").lower()
RUNWAY_UNIT_COST_USD = float(os.environ.get("RUNWAY_UNIT_COST_USD", "7.0"))
IMG_COST_USD = float(os.environ.get("IMG_COST_USD", "0.05"))

# DEMO: free даёт попробовать ключевые движки
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

    # Попытка покрыть из единого кошелька
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

# ───────── Prompts ─────────
SYSTEM_PROMPT = (
    "Ты дружелюбный и лаконичный ассистент на русском. "
    "Отвечай по сути, структурируй списками/шагами, не выдумывай факты. "
    "Если ссылаешься на источники — в конце дай короткий список ссылок."
)
VISION_SYSTEM_PROMPT = (
    "Ты чётко описываешь содержимое изображений: объекты, текст, схемы, графики. "
    "Не идентифицируй личности людей и не пиши имена, если они не напечатаны на изображении."
)

# ───────── Heuristics / intent ─────────
_SMALLTALK_RE = re.compile(r"^(привет|здравствуй|добрый\s*(день|вечер|утро)|хи|hi|hello|как дела|спасибо|пока)\b", re.I)
_NEWSY_RE     = re.compile(r"(когда|дата|выйдет|релиз|новост|курс|цена|прогноз|найди|официал|погода|сегодня|тренд|адрес|телефон)", re.I)
_CAPABILITY_RE= re.compile(r"(мож(ешь|но|ете).{0,16}(анализ|распозн|читать|созда(ва)?т|дела(ть)?).{0,24}(фото|картинк|изображен|pdf|docx|epub|fb2|аудио|книг))", re.I)

_IMG_WORDS = r"(картин\w+|изображен\w+|фото\w*|рисунк\w+|image|picture|img\b|logo|banner|poster)"
_VID_WORDS = r"(видео|ролик\w*|анимаци\w*|shorts?|reels?|clip|video|vid\b)"

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

_CREATE_CMD = r"(сдела(й|йте)|созда(й|йте)|сгенериру(й|йте)|нарису(й|йте)|render|generate|create|make)"
_PREFIXES_VIDEO = [r"^" + _CREATE_CMD + r"\s+видео", r"^video\b", r"^reels?\b", r"^shorts?\b"]
_PREFIXES_IMAGE = [r"^" + _CREATE_CMD + r"\s+(?:картин\w+|изображен\w+|фото\w+|рисунк\w+)", r"^image\b", r"^picture\b", r"^img\b"]

def _strip_leading(s: str) -> str:
    return s.strip(" \n\t:—–-\"“”'«»,.()[]")

def _after_match(text: str, match) -> str:
    return _strip_leading(text[match.end():])

def _looks_like_capability_question(tl: str) -> bool:
    if "?" in tl and re.search(_CAPABILITY_RE, tl):
        if not re.search(_CREATE_CMD, tl, re.I):
            return True
    m = re.search(r"\b(ты|вы)?\s*мож(ешь|но|ете)\b", tl)
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

# ───────── OpenAI helpers ─────────
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
        return "Пустой запрос."

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({"role": "system", "content": f"Контекст из веб-поиска:\n{web_ctx}"})
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
    return "⚠️ Сейчас не получилось получить ответ от модели. Я на связи — попробуй переформулировать запрос или повторить чуть позже."

async def ask_openai_vision(user_text: str, img_b64: str, mime: str) -> str:
    try:
        prompt = (user_text or "Опиши, что на изображении и какой там текст.").strip()
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
        return "Не удалось проанализировать изображение."


# ───────── Пользовательские настройки (TTS) ─────────
# Храним флаг в отдельной таблице tts_flags в общей БД (DB_PATH).
# Ключевые моменты:
#  - читаем ровно первый столбец (row[0]), а не весь кортеж
#  - ON CONFLICT делает UPSERT по user_id

def _db_conn_tts():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS tts_flags (
            user_id INTEGER PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0
        )
    """)
    return con

def _tts_get(user_id: int) -> bool:
    con = _db_conn_tts()
    row = con.execute("SELECT enabled FROM tts_flags WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return bool(row and row[0])  # читаем именно первый столбец

def _tts_set(user_id: int, enabled: bool) -> None:
    con = _db_conn_tts()
    con.execute("""
        INSERT INTO tts_flags (user_id, enabled)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled
    """, (user_id, 1 if enabled else 0))
    con.commit()
    con.close()

# ───────── Надёжный TTS через REST (OGG/Opus) ─────────
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
            "format": "ogg"  # OGG/Opus для Telegram voice
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
                f"🔇 Озвучка выключена для этого сообщения: текст длиннее {TTS_MAX_CHARS} символов."
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
                await update.effective_message.reply_text("🔇 Не удалось синтезировать голос.")
            return
        bio = BytesIO(audio); bio.seek(0); bio.name = "say.ogg"
        await update.effective_message.reply_voice(voice=InputFile(bio), caption=text)
    except Exception as e:
        log.exception("maybe_tts_reply error: %s", e)

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, True)
    await update.effective_message.reply_text(f"🔊 Озвучка включена. Лимит {TTS_MAX_CHARS} символов на ответ.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, False)
    await update.effective_message.reply_text("🔈 Озвучка выключена.")

# ───────── Speech-to-Text (STT) • OpenAI Whisper/4o-mini-transcribe ─────────
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

# ───────── Хендлер голосовых/аудио ─────────
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
        await msg.reply_text("Не нашёл голосовой файл.")
        return

    # Скачиваем файл из Telegram
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
        log.exception("TG download error: %s", e)
        await msg.reply_text("Не удалось скачать голосовое сообщение.")
        return

        # Транскрибируем
    transcript = await _stt_transcribe_bytes(filename, raw)
    if not transcript:
        await msg.reply_text("Ошибка при обработке voice.")
        return
    transcript = transcript.strip()

    # 🔎 Быстрый ответ на «ты умеешь X?»
    cap = capability_answer(transcript)
    if cap:
        await msg.reply_text(cap)
        return

    # Подтверждаем распознавание (для UX/отладки)
    with contextlib.suppress(Exception):
        await msg.reply_text(f"🗣️ Распознал: {transcript}")

    # Основной ответ модели
    answer = await ask_openai_text(transcript)
    await msg.reply_text(answer)
    await maybe_tts_reply(update, context, answer)

# ───────── Извлечение текста из документов ─────────
def _safe_decode_txt(b: bytes) -> str:
    for enc in ("utf-8","cp1251","latin-1"):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("utf-8", errors="ignore")

### BEGIN PATCH: PDF_EXTRACT
# ВАЖНО: не удаляйте отступы внутри try/except — иначе будет IndentationError.

# Мягкие импорты: если библиотеки нет — переменная станет None, и мы аккуратно обойдёмся без неё.
try:
    from PyPDF2 import PdfReader as _PdfReader
except Exception:
    _PdfReader = None

try:
    from pdfminer.high_level import extract_text as pdfminer_extract_text
except Exception:
    pdfminer_extract_text = None  # будет None, если pdfminer не установлен

try:
    from docx import Document as DocxDocument
except Exception:
    DocxDocument = None

try:
    from ebooklib import epub as _epub
except Exception:
    _epub = None

from io import BytesIO


def _extract_pdf_text(data: bytes) -> str:
    """
    Пытаемся достать текст из PDF:
    1) PyPDF2 (быстро, но не всегда полно)
    2) pdfminer (медленнее, но более надёжно)
    Возвращает строку (может быть пустой).
    """
    # Сначала PyPDF2
    if _PdfReader is not None:
        try:
            pdf = _PdfReader(BytesIO(data))
            texts = []
            for page in pdf.pages:
                try:
                    t = page.extract_text() or ""
                except Exception:
                    t = ""
                if t.strip():
                    texts.append(t)
            if texts:
                return "\n".join(texts)
        except Exception:
            # Падаем в fallback
            pass

    # Затем pdfminer
    if pdfminer_extract_text is not None:
        try:
            txt = pdfminer_extract_text(BytesIO(data)) or ""
            return txt.strip()
        except Exception:
            pass

    # Совсем ничего не вышло
    return ""
### END PATCH: PDF_EXTRACT

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


# ───────── Суммаризация длинных текстов ─────────
async def _summarize_chunk(text: str, query: str | None = None) -> str:
    prefix = "Суммируй кратко по пунктам основное из фрагмента документа на русском:\n"
    if query:
        prefix = (f"Суммируй фрагмент с учётом цели: {query}\n"
                  f"Дай основные тезисы, факты, цифры. Русский язык.\n")
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
    combined = "\n\n".join(f"- Фрагмент {idx+1}:\n{s}" for idx, s in enumerate(partials))
    final_prompt = ("Объедини тезисы по фрагментам в цельное резюме документа: 1) 5–10 главных пунктов; "
                    "2) ключевые цифры/сроки; 3) вывод/рекомендации. Русский язык.\n\n" + combined)
    return await ask_openai_text(final_prompt)


# ======= Анализ документов (PDF/EPUB/DOCX/FB2/TXT) =======
async def on_doc_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document:
            return
        doc = update.message.document
        tg_file = await doc.get_file()
        data = await tg_file.download_as_bytearray()
        text, kind = extract_text_from_document(bytes(data), doc.file_name or "file")
        if not text.strip():
            await update.effective_message.reply_text(f"Не удалось извлечь текст из {kind}.")
            return
        goal = (update.message.caption or "").strip() or None
        await update.effective_message.reply_text(f"📄 Извлекаю текст ({kind}), готовлю конспект…")
        summary = await summarize_long_text(text, query=goal)
        summary = summary or "Готово."
        await update.effective_message.reply_text(summary)
        await maybe_tts_reply(update, context, summary[:TTS_MAX_CHARS])
    except Exception as e:
        log.exception("on_doc_analyze error: %s", e)
    # ничего не бросаем наружу

# ───────── OpenAI Images (генерация картинок) ─────────
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

async def _luma_generate_image_bytes(prompt: str) -> bytes | None:
    if not LUMA_IMG_BASE_URL or not LUMA_API_KEY:
        # фолбэк: OpenAI Images
        try:
            resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
            return base64.b64decode(resp.data[0].b64_json)
        except Exception as e:
            log.exception("OpenAI images fallback error: %s", e)
            return None
    try:
        # Примерный эндпоинт; если у тебя другой — замени path/поля под свой аккаунт.
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
            await update.effective_message.reply_text("Не удалось создать изображение.")
            return
        await update.effective_message.reply_photo(photo=img, caption=f"🖌 Готово ✅\nЗапрос: {prompt}")
    await _try_pay_then_do(update, context, update.effective_user.id, "img", IMG_COST_USD, _go,
                           remember_kind="luma_img", remember_payload={"prompt": prompt})


# ───────── UI / тексты ─────────
START_TEXT = (
    "Привет! Я Нейро-Bot — ⚡️ мультирежимный бот из 7 нейросетей для 🎓 учёбы, 💼 работы и 🔥 развлечений.\n"
    "Я умею работать гибридно: могу сам выбрать лучший движок под задачу или дать тебе выбрать вручную. 🤝🧠\n"
    "\n"
    "✨ Главные режимы:\n"
    "\n"
    "\n"
    "• 🎓 Учёба — объяснения с примерами, пошаговые решения задач, эссе/реферат/доклад, мини-квизы.\n"
    "📚 Также: разбор учебных PDF/электронных книг, шпаргалки и конспекты, конструктор тестов;\n"
    "🎧 тайм-коды по аудиокнигам/лекциям и краткие выжимки. 🧩\n"
    "\n"
    "• 💼 Работа — письма/брифы/документы, аналитика и резюме материалов, ToDo/планы, генератор идей.\n"
    "🛠️ Для архитектора/дизайнера/проектировщика: структурирование ТЗ, чек-листы стадий,\n"
    "🗂️ названия/описания листов, сводные таблицы из текстов, оформление пояснительных записок. 📊\n"
    "\n"
    "• 🔥 Развлечения — фото-мастерская (удаление/замена фона, дорисовка, outpaint), оживление старых фото,\n"
    "🎬 видео по тексту/голосу, идеи и форматы для Reels/Shorts, авто-нарезка из длинных видео\n"
    "(сценарий/тайм-коды), мемы/квизы. 🖼️🪄\n"
    "\n"
    "🧭 Как пользоваться:\n"
    "просто выбери режим кнопкой ниже или напиши запрос — я сам определю задачу и предложу варианты. ✍️✨\n"
    "\n"
    "🧠 Кнопка «Движки»:\n"
    "для точного выбора, какую нейросеть использовать принудительно. 🎯🤖"
)

def engines_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 GPT (текст/фото/документы)", callback_data="engine:gpt")],
        [InlineKeyboardButton("🖼 Images (OpenAI)",             callback_data="engine:images")],
        [InlineKeyboardButton("🎬 Luma — короткие видео",       callback_data="engine:luma")],
        [InlineKeyboardButton("🎥 Runway — премиум-видео",      callback_data="engine:runway")],
        [InlineKeyboardButton("🎨 Midjourney (изображения)",    callback_data="engine:midjourney")],
        [InlineKeyboardButton("🗣 STT/TTS — речь↔текст",        callback_data="engine:stt_tts")],
    ])

# ───────── MODES (Учёба / Работа / Развлечения) ─────────

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackQueryHandler, MessageHandler, filters

# Текст корневого меню режимов
def _modes_root_text() -> str:
    return (
        "Выберите режим работы. В каждом режиме бот использует гибрид движков:\n"
        "• GPT-5 (текст/логика) + Vision (фото) + STT/TTS (голос)\n"
        "• Luma/Runway — видео, Midjourney — изображения\n\n"
        "Можете также просто написать свободный запрос — бот поймёт."
    )

def modes_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎓 Учёба", callback_data="mode:study"),
            InlineKeyboardButton("💼 Работа", callback_data="mode:work"),
            InlineKeyboardButton("🔥 Развлечения", callback_data="mode:fun"),
        ],
    ])

# ── Описание и подменю по режимам
def _mode_desc(key: str) -> str:
    if key == "study":
        return (
            "🎓 *Учёба*\n"
            "Гибрид: GPT-5 для объяснений/конспектов, Vision для фото-задач, "
            "STT/TTS для голосовых, + Midjourney (иллюстрации) и Luma/Runway (учебные ролики).\n\n"
            "Быстрые действия ниже. Можно написать свободный запрос (например: "
            "«сделай конспект из PDF», «объясни интегралы с примерами»)."
        )
    if key == "work":
        return (
            "💼 *Работа*\n"
            "Гибрид: GPT-5 (резюме/письма/аналитика), Vision (таблицы/скрины), "
            "STT/TTS (диктовка/озвучка), + Midjourney (визуалы), Luma/Runway (презентационные ролики).\n\n"
            "Быстрые действия ниже. Можно написать свободный запрос (например: "
            "«адаптируй резюме под вакансию PM», «написать коммерческое предложение»)."
        )
    if key == "fun":
        return (
            "🔥 *Развлечения*\n"
            "Гибрид: GPT-5 (идеи, сценарии), Midjourney (картинки), Luma/Runway (шорты/риелсы), "
            "STT/TTS (озвучка). Всё для быстрых творческих штук.\n\n"
            "Быстрые действия ниже. Можно написать свободный запрос (например: "
            "«сделай сценарий 30-сек шорта про кота-бариста»)."
        )
    return "Режим не найден."

def _mode_kb(key: str) -> InlineKeyboardMarkup:
    if key == "study":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 Конспект из PDF/EPUB/DOCX", callback_data="act:study:pdf_summary")],
            [InlineKeyboardButton("🔍 Объяснение темы",            callback_data="act:study:explain"),
             InlineKeyboardButton("🧮 Решение задач",              callback_data="act:study:tasks")],
            [InlineKeyboardButton("✍️ Эссе/реферат/доклад",       callback_data="act:study:essay"),
             InlineKeyboardButton("📝 План к экзамену",           callback_data="act:study:exam_plan")],
            [
                InlineKeyboardButton("🎬 Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("🎨 Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("🗣 STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("📝 Свободный запрос", callback_data="act:free")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="mode:root")],
        ])

    if key == "work":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Письмо/документ",            callback_data="act:work:doc"),
             InlineKeyboardButton("📊 Аналитика/сводка",           callback_data="act:work:report")],
            [InlineKeyboardButton("🗂 План/ToDo",                  callback_data="act:work:plan"),
             InlineKeyboardButton("💡 Идеи/бриф",                 callback_data="act:work:idea")],
            [
                InlineKeyboardButton("🎬 Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("🎨 Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("🗣 STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("📝 Свободный запрос", callback_data="act:free")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="mode:root")],
        ])

    if key == "fun":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🎭 Идеи для досуга",             callback_data="act:fun:ideas")],
            [InlineKeyboardButton("🎬 Сценарий шорта",              callback_data="act:fun:shorts")],
            [InlineKeyboardButton("🎮 Игры/квиз",                   callback_data="act:fun:games")],
            [
                InlineKeyboardButton("🎬 Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("🎨 Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("🗣 STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("📝 Свободный запрос", callback_data="act:free")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="mode:root")],
        ])

    return modes_root_kb()

# Показать выбранный режим (используется и для callback, и для текста)
async def _send_mode_menu(update, context, key: str):
    text = _mode_desc(key)
    kb = _mode_kb(key)
    # Если пришли из callback — редактируем; если текстом — шлём новым сообщением
    if getattr(update, "callback_query", None):
        q = update.callback_query
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        await q.answer()
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# Обработчик callback по режимам
async def on_mode_cb(update, context):
    q = update.callback_query
    data = (q.data or "").strip()
    uid = q.from_user.id

    # Навигация
    if data == "mode:root":
        await q.edit_message_text(_modes_root_text(), reply_markup=modes_root_kb())
        await q.answer(); return

    if data.startswith("mode:"):
        _, key = data.split(":", 1)
        await _send_mode_menu(update, context, key)
        return

    # Свободный ввод из подменю
    if data == "act:free":
        await q.answer()
        await q.edit_message_text(
            "📝 Напишите свободный запрос ниже текстом или голосом — я подстроюсь.",
            reply_markup=modes_root_kb(),
        )
        return

    # === Учёба
    if data == "act:study:pdf_summary":
        await q.answer()
        _mode_track_set(uid, "pdf_summary")
        await q.edit_message_text(
            "📚 Пришлите PDF/EPUB/DOCX/FB2/TXT — сделаю структурированный конспект.\n"
            "Можно в подписи указать цель (коротко/подробно, язык и т.п.).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:explain":
        await q.answer()
        study_sub_set(uid, "explain")
        _mode_track_set(uid, "explain")
        await q.edit_message_text(
            "🔍 Напишите тему + уровень (школа/вуз/профи). Будет объяснение с примерами.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:tasks":
        await q.answer()
        study_sub_set(uid, "tasks")
        _mode_track_set(uid, "tasks")
        await q.edit_message_text(
            "🧮 Пришлите условие(я) — решу пошагово (формулы, пояснения, итог).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:essay":
        await q.answer()
        study_sub_set(uid, "essay")
        _mode_track_set(uid, "essay")
        await q.edit_message_text(
            "✍️ Тема + требования (объём/стиль/язык) — подготовлю эссе/реферат.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:exam_plan":
        await q.answer()
        study_sub_set(uid, "quiz")
        _mode_track_set(uid, "exam_plan")
        await q.edit_message_text(
            "📝 Укажите предмет и дату экзамена — составлю план подготовки с вехами.",
            reply_markup=_mode_kb("study"),
        )
        return

    # === Работа
    if data == "act:work:doc":
        await q.answer()
        _mode_track_set(uid, "work_doc")
        await q.edit_message_text(
            "📄 Что за документ/адресат/контекст? Сформирую черновик письма/документа.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:report":
        await q.answer()
        _mode_track_set(uid, "work_report")
        await q.edit_message_text(
            "📊 Пришлите текст/файл/ссылку — сделаю аналитическую выжимку.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:plan":
        await q.answer()
        _mode_track_set(uid, "work_plan")
        await q.edit_message_text(
            "🗂 Опишите задачу/сроки — соберу ToDo/план со сроками и приоритетами.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:idea":
        await q.answer()
        _mode_track_set(uid, "work_idea")
        await q.edit_message_text(
            "💡 Расскажите продукт/ЦА/каналы — подготовлю бриф/идеи.",
            reply_markup=_mode_kb("work"),
        )
        return

    # === Развлечения (как было)
    if data == "act:fun:ideas":
        await q.answer()
        await q.edit_message_text(
            "🔥 Выберем формат: дом/улица/город/в поездке. Напишите бюджет/настроение.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:shorts":
        await q.answer()
        await q.edit_message_text(
            "🎬 Тема, длительность (15–30 сек), стиль — сделаю сценарий шорта + подсказки для озвучки.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:games":
        await q.answer()
        await q.edit_message_text(
            "🎮 Тематика квиза/игры? Сгенерирую быструю викторину или мини-игру в чате.",
            reply_markup=_mode_kb("fun"),
        )
        return

    # === Модули (как было)
    if data == "act:open:runway":
        await q.answer()
        await q.edit_message_text(
            "🎬 Модуль Runway: пришлите идею/референс — подготовлю промпт и бюджет.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:mj":
        await q.answer()
        await q.edit_message_text(
            "🎨 Модуль Midjourney: опишите картинку — предложу 3 промпта и сетку стилей.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:voice":
        await q.answer()
        await q.edit_message_text(
            "🗣 Голос: /voice_on — озвучка ответов, /voice_off — выключить. "
            "Можете прислать голосовое — распознаю и отвечу.",
            reply_markup=modes_root_kb(),
        )
        return

    await q.answer()

# Fallback — если пользователь нажмёт «Учёба/Работа/Развлечения» обычной кнопкой/текстом
import re

async def on_mode_text(update, context):
    raw = (update.effective_message.text or "").strip()
    tl = re.sub(r"[^\w\sёЁа-яА-Я]", " ", raw.lower())  # выкидываем эмодзи/знаки
    if "учеб" in tl or "учёб" in tl:
        return await _send_mode_menu(update, context, "study")
    if "работ" in tl:
        return await _send_mode_menu(update, context, "work")
    if "развлеч" in tl or "fun" in tl:
        return await _send_mode_menu(update, context, "fun")
    # иначе ничего не делаем — апдейт поймают другие хендлеры

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎓 Учёба"), KeyboardButton("💼 Работа"), KeyboardButton("🔥 Развлечения")],
            [KeyboardButton("🧠 Движки"), KeyboardButton("⭐ Подписка · Помощь"), KeyboardButton("🧾 Баланс")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
        input_field_placeholder="Выберите режим или напишите запрос…",
    )

main_kb = main_keyboard()

# ВНИМАНИЕ: /start определён в единственном месте ниже по файлу. Здесь ранний дубль удалён.

if "HELP_TEXT" not in globals():
    HELP_TEXT = (
        "Команды: /engines — выбор движка, /plans — тарифы, /balance — кошелёк, "
        "/voice_on /voice_off — озвучка ответов. Задавайте запросы просто текстом или голосом."
    )
if "EXAMPLES_TEXT" not in globals():
    EXAMPLES_TEXT = (
        "Примеры:\n"
        "• Сделай конспект из PDF\n"
        "• Сценарий Reels на 9 сек про кофейню\n"
        "• /img логотип в стиле минимализма"
    )

# ───────── сохранение выбранного режима/подрежима (SQLite kv) ─────────
def _mode_set(user_id: int, mode: str):
    kv_set(f"mode:{user_id}", mode)

def _mode_get(user_id: int) -> str:
    return (kv_get(f"mode:{user_id}", "none") or "none")

def _mode_track_set(user_id: int, track: str):
    kv_set(f"mode_track:{user_id}", track)

def _mode_track_get(user_id: int) -> str:
    return kv_get(f"mode_track:{user_id}", "") or ""

# ───────── Подменю режимов ─────────
def _school_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Объяснение",          callback_data="school:explain"),
         InlineKeyboardButton("🧮 Задачи",              callback_data="school:tasks")],
        [InlineKeyboardButton("✍️ Эссе/реферат/доклад", callback_data="school:essay"),
         InlineKeyboardButton("📝 Экзамен/квиз",        callback_data="school:quiz")],
    ])

def _work_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📧 Письмо/документ",  callback_data="work:doc"),
         InlineKeyboardButton("📊 Аналитика/сводка", callback_data="work:report")],
        [InlineKeyboardButton("🗂 План/ToDo",        callback_data="work:plan"),
         InlineKeyboardButton("💡 Идеи/бриф",       callback_data="work:idea")],
    ])

def _fun_quick_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Оживить фото (анимация)", callback_data="fun:revive")],
        [InlineKeyboardButton("Клип из текста/голоса",    callback_data="fun:clip")],
        [InlineKeyboardButton("Сгенерировать изображение /img", callback_data="fun:img")],
        [InlineKeyboardButton("Раскадровка под Reels",    callback_data="fun:storyboard")],
    ])

def _fun_kb():
    # оставим и старое подменю — не используется сейчас
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 Фото-мастерская", callback_data="fun:photo"),
         InlineKeyboardButton("🎬 Видео-идеи",      callback_data="fun:video")],
        [InlineKeyboardButton("🎲 Квизы/игры",      callback_data="fun:quiz"),
         InlineKeyboardButton("😆 Мемы/шутки",      callback_data="fun:meme")],
    ])


# ───────── Команды/кнопки режимов ─────────
async def cmd_mode_school(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _mode_set(update.effective_user.id, "Учёба")
    _mode_track_set(update.effective_user.id, "")
    # показываем НОВОЕ подменю «Учёба»
    await _send_mode_menu(update, context, "study")

async def cmd_mode_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _mode_set(update.effective_user.id, "Работа")
    _mode_track_set(update.effective_user.id, "")
    # показываем НОВОЕ подменю «Работа»
    await _send_mode_menu(update, context, "work")

async def cmd_mode_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _mode_set(update.effective_user.id, "Развлечения")
    _mode_track_set(update.effective_user.id, "")
    await update.effective_message.reply_text(
        "🔥 Развлечения — быстрые действия:",
        reply_markup=_fun_quick_kb()
    )


# ───────── Коллбэки подрежимов ─────────
async def on_cb_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "")
    try:
        if any(data.startswith(p) for p in ("school:", "work:", "fun:")):
            # базовый трекинг старых веток (photo/video/quiz/meme)
            if data in ("fun:revive","fun:clip","fun:img","fun:storyboard"):
                # эти обрабатываются отдельным хендлером on_cb_fun
                return
            _, track = data.split(":", 1)
            _mode_track_set(update.effective_user.id, track)
            mode = _mode_get(update.effective_user.id)
            await q.edit_message_text(f"{mode} → {track}. Напишите задание/тему — сделаю.")
            return
    finally:
        with contextlib.suppress(Exception):
            await q.answer()

# быстрые действия «Развлечения»
async def on_cb_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "fun:img":
        return await q.edit_message_text("Пришли промпт или используй команду /img <описание> — сгенерирую изображение.")
    if data == "fun:revive":
        return await q.edit_message_text("Загрузи фото (как картинку) и напиши, что оживить/как двигаться. Сделаю анимацию.")
    if data == "fun:clip":
        return await q.edit_message_text("Пришли текст/голос и формат (Reels/Shorts), музыку/стиль — соберу клип (Luma/Runway).")
    if data == "fun:storyboard":
        return await q.edit_message_text("Пришли фото или опиши идею ролика — верну раскадровку под Reels с тайм-кодами.")

# ───────── Старт / Движки / Помощь ─────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_url = kv_get("welcome_url", BANNER_URL)
    if welcome_url:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_photo(welcome_url)
    await update.effective_message.reply_text(START_TEXT, reply_markup=main_kb, disable_web_page_preview=True)

async def cmd_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Выберите движок:", reply_markup=engines_kb())

async def cmd_subs_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Открыть тарифы (WebApp)", web_app=WebAppInfo(url=TARIFF_URL))],
        [InlineKeyboardButton("Оформить PRO на месяц (ЮKassa)", callback_data="buyinv:pro:1")],
    ])
    await update.effective_message.reply_text("⭐ Тарифы и помощь.\n\n" + HELP_TEXT, reply_markup=kb, disable_web_page_preview=True)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, disable_web_page_preview=True)

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(EXAMPLES_TEXT, disable_web_page_preview=True)


# ───────── Диагностика/лимиты ─────────
async def cmd_diag_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tier = get_subscription_tier(user_id)
    lim = _limits_for(user_id)
    row = _usage_row(user_id, _today_ymd())
    lines = [
        f"👤 Тариф: {tier}",
        f"• Тексты сегодня: {row['text_count']} / {lim['text_per_day']}",
        f"• Luma $: {row['luma_usd']:.2f} / {lim['luma_budget_usd']:.2f}",
        f"• Runway $: {row['runway_usd']:.2f} / {lim['runway_budget_usd']:.2f}",
        f"• Images $: {row['img_usd']:.2f} / {lim['img_budget_usd']:.2f}",
    ]
    await update.effective_message.reply_text("\n".join(lines))


# ───────── Capability Q&A ─────────
_CAP_PDF   = re.compile(r"(pdf|документ(ы)?|файл(ы)?)", re.I)
_CAP_EBOOK = re.compile(r"(ebook|e-?book|электронн(ая|ые)\s+книг|epub|fb2|docx|txt|mobi|azw)", re.I)
_CAP_AUDIO = re.compile(r"(аудио ?книг|audiobook|audio ?book|mp3|m4a|wav|ogg|webm|voice)", re.I)
_CAP_IMAGE = re.compile(r"(изображен|картинк|фото|image|picture|img)", re.I)
_CAP_VIDEO = re.compile(r"(видео|ролик|shorts?|reels?|clip)", re.I)

def capability_answer(text: str) -> str | None:
    tl = (text or "").strip().lower()
    if not tl:
        return None
    if (_CAP_PDF.search(tl) or _CAP_EBOOK.search(tl)) and re.search(
        r"(чита(ешь|ете)|читать|анализиру(ешь|ете)|анализировать|распозна(ешь|ете)|распознавать)", tl
    ):
        return (
            "Да. Пришлите файл — извлеку текст и сделаю конспект/ответ по вашей цели.\n"
            "Поддержка: PDF, EPUB, DOCX, FB2, TXT (MOBI/AZW — по возможности)."
        )
    if (_CAP_AUDIO.search(tl) and re.search(r"(чита|анализ|расшиф|транскриб|понима|распозна)", tl)) or "аудио" in tl:
        return (
            "Да. Пришлите аудио (voice/audio/документ): OGG/MP3/M4A/WAV/WEBM. "
            "Распознаю речь (Deepgram/Whisper) и сделаю конспект, тезисы, тайм-коды, Q&A."
        )
    if _CAP_IMAGE.search(tl) and re.search(r"(чита|анализ|понима|видишь)", tl):
        return "Да. Пришлите фото/картинку с подписью — опишу содержимое, текст на изображении, детали."
    if _CAP_IMAGE.search(tl) and re.search(r"(мож(ешь|ете)|созда(ва)?т|дела(ть)?|генерир)", tl):
        return "Да, могу создавать изображения. Запустите: /img <описание>."
    if _CAP_VIDEO.search(tl) and re.search(r"(мож(ешь|ете)|созда(ва)?т|дела(ть)?|сгенерир)", tl):
        return "Да, могу запустить генерацию коротких видео. Напишите: «сделай видео … 9 секунд 9:16»."
    return None


# ───────── Моды/движки для study ─────────
def _uk(user_id: int, name: str) -> str: return f"user:{user_id}:{name}"
def mode_set(user_id: int, mode: str):     kv_set(_uk(user_id, "mode"), (mode or "default"))
def mode_get(user_id: int) -> str:         return kv_get(_uk(user_id, "mode"), "default") or "default"
def engine_set(user_id: int, engine: str): kv_set(_uk(user_id, "engine"), (engine or "gpt"))
def engine_get(user_id: int) -> str:       return kv_get(_uk(user_id, "engine"), "gpt") or "gpt"
def study_sub_set(user_id: int, sub: str): kv_set(_uk(user_id, "study_sub"), (sub or "explain"))
def study_sub_get(user_id: int) -> str:    return kv_get(_uk(user_id, "study_sub"), "explain") or "explain"

def modes_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎓 Учёба", callback_data="mode:set:study"),
         InlineKeyboardButton("🖼 Фото",  callback_data="mode:set:photo")],
        [InlineKeyboardButton("📄 Документы", callback_data="mode:set:docs"),
         InlineKeyboardButton("🎙 Голос",     callback_data="mode:set:voice")],
        [InlineKeyboardButton("🧠 Движки", callback_data="mode:engines")]
    ])

def study_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Объяснение",          callback_data="study:set:explain"),
         InlineKeyboardButton("🧮 Задачи",              callback_data="study:set:tasks")],
        [InlineKeyboardButton("✍️ Эссе/реферат/доклад", callback_data="study:set:essay")],
        [InlineKeyboardButton("📝 Экзамен/квиз",        callback_data="study:set:quiz")]
    ])

async def study_process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    sub = study_sub_get(update.effective_user.id)
    if sub == "explain":
        prompt = f"Объясни простыми словами, с 2–3 примерами и мини-итогом:\n\n{text}"
    elif sub == "tasks":
        prompt = ("Реши задачу(и) пошагово: формулы, пояснения, итоговый ответ. "
                  "Если не хватает данных — уточняющие вопросы в конце.\n\n" + text)
    elif sub == "essay":
        prompt = ("Напиши структурированный текст 400–600 слов (эссе/реферат/доклад): "
                  "введение, 3–5 тезисов с фактами, вывод, список из 3 источников (если уместно).\n\nТема:\n" + text)
    elif sub == "quiz":
        prompt = ("Составь мини-квиз по теме: 10 вопросов, у каждого 4 варианта A–D; "
                  "в конце дай ключ ответов (номер→буква). Тема:\n\n" + text)
    else:
        prompt = text
    ans = await ask_openai_text(prompt)
    await update.effective_message.reply_text(ans)
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])


# ───────── Кнопка приветственной картинки ─────────
async def cmd_set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("Команда доступна только владельцу.")
        return
    if not context.args:
        await update.effective_message.reply_text("Формат: /set_welcome <url_картинки>")
        return
    url = " ".join(context.args).strip()
    kv_set("welcome_url", url)
    await update.effective_message.reply_text("Картинка приветствия обновлена. Отправьте /start для проверки.")

async def cmd_show_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = kv_get("welcome_url", BANNER_URL)
    if url:
        await update.effective_message.reply_photo(url, caption="Текущая картинка приветствия")
    else:
        await update.effective_message.reply_text("Картинка приветствия не задана.")


# ───────── Баланс / пополнение ─────────
async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    w = _wallet_get(user_id)
    total = _wallet_total_get(user_id)
    row = _usage_row(user_id)
    lim = _limits_for(user_id)
    msg = (
        "🧾 Кошелёк:\n"
        f"• Единый баланс: ${total:.2f}\n"
        "  (расходуется на перерасход по Luma/Runway/Images)\n\n"
        "Детализация сегодня / лимиты тарифа:\n"
        f"• Luma: ${row['luma_usd']:.2f} / ${lim['luma_budget_usd']:.2f}\n"
        f"• Runway: ${row['runway_usd']:.2f} / ${lim['runway_budget_usd']:.2f}\n"
        f"• Images: ${row['img_usd']:.2f} / ${lim['img_budget_usd']:.2f}\n"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]])
    await update.effective_message.reply_text(msg, reply_markup=kb)

# ───────── Подписка / тарифы — UI и оплаты (PATCH) ─────────
# Зависимости окружения:
#  - YOOKASSA_PROVIDER_TOKEN  (платёжный токен Telegram Payments от ЮKassa)
#  - YOOKASSA_CURRENCY        (по умолчанию "RUB")
#  - CRYPTO_PAY_API_TOKEN     (https://pay.crypt.bot — токен продавца)
#  - CRYPTO_ASSET             (например "USDT", по умолчанию "USDT")
#  - PRICE_START_RUB, PRICE_PRO_RUB, PRICE_ULT_RUB  (целое число, ₽)
#  - PRICE_START_USD, PRICE_PRO_USD, PRICE_ULT_USD  (число с точкой, $)
#
# Хранилище подписки и кошелька: ИСКЛЮЧИТЕЛЬНО ваша SQLite-БД через
# _wallet_total_get/_wallet_total_add/_wallet_total_take и activate_subscription_with_tier

YOOKASSA_PROVIDER_TOKEN = os.environ.get("YOOKASSA_PROVIDER_TOKEN", "").strip()
YOOKASSA_CURRENCY = (os.environ.get("YOOKASSA_CURRENCY") or "RUB").upper()


# === COMPAT with existing vars/DB in your main.py ===
# 1) ЮKassa: если уже есть PROVIDER_TOKEN (из PROVIDER_TOKEN_YOOKASSA), используем его:
if not YOOKASSA_PROVIDER_TOKEN and 'PROVIDER_TOKEN' in globals() and PROVIDER_TOKEN:
    YOOKASSA_PROVIDER_TOKEN = PROVIDER_TOKEN

# 2) Кошелёк: используем ЕДИНЫЙ USD-кошелёк из вашей БД
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

# 3) Подписка: активируем через функции с БД
def _sub_activate(user_id: int, tier_key: str, months: int = 1) -> str:
    dt = activate_subscription_with_tier(user_id, tier_key, months)
    return dt.isoformat()

def _sub_info_text(user_id: int) -> str:
    tier = get_subscription_tier(user_id)
    dt = get_subscription_until(user_id)
    human_until = dt.strftime("%d.%m.%Y") if dt else ""
    bal = _user_balance_get(user_id)
    line_until = f"\n⏳ Активна до: {human_until}" if tier != "free" and human_until else ""
    return f"🧾 Текущая подписка: {tier.upper() if tier!='free' else 'нет'}{line_until}\n💵 Баланс: ${bal:.2f}"

# Цены — из env с осмысленными дефолтами
PRICE_START_RUB = int(os.environ.get("PRICE_START_RUB", "299"))
PRICE_PRO_RUB = int(os.environ.get("PRICE_PRO_RUB", "899"))
PRICE_ULT_RUB = int(os.environ.get("PRICE_ULT_RUB", "1990"))

PRICE_START_USD = float(os.environ.get("PRICE_START_USD", "3.49"))
PRICE_PRO_USD = float(os.environ.get("PRICE_PRO_USD", "9.99"))
PRICE_ULT_USD = float(os.environ.get("PRICE_ULT_USD", "19.99"))

SUBS_TIERS = {
    "start": {
        "title": "START",
        "rub": PRICE_START_RUB,
        "usd": PRICE_START_USD,
        "features": [
            "💬 GPT-чат и документы (базовые лимиты)",
            "🖼 Фото-мастерская: фон, лёгкая дорисовка",
            "🎧 Озвучка ответов (TTS)",
        ],
    },
    "pro": {
        "title": "PRO",
        "rub": PRICE_PRO_RUB,
        "usd": PRICE_PRO_USD,
        "features": [
            "📚 Глубокий разбор PDF/DOCX/EPUB",
            "🎬 Reels/Shorts по смыслу, видео из фото",
            "🖼 Outpaint и «оживление» старых фото",
        ],
    },
    "ultimate": {
        "title": "ULTIMATE",
        "rub": PRICE_ULT_RUB,
        "usd": PRICE_ULT_USD,
        "features": [
            "🚀 Runway/Luma — премиум-рендеры",
            "🧠 Расширенные лимиты и приоритетная очередь",
            "🛠 PRO-инструменты (архитектура/дизайн)",
        ],
    },
}

def _money_fmt_rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₽"

def _money_fmt_usd(v: float) -> str:
    return f"${v:.2f}"

def _plan_card_text(key: str) -> str:
    p = SUBS_TIERS[key]
    fs = "\n".join("• " + f for f in p["features"])
    return (
        f"⭐ Тариф {p['title']}\n"
        f"Цена: {_money_fmt_rub(p['rub'])} / {_money_fmt_usd(p['usd'])} в мес.\n\n"
        f"{fs}\n"
    )

def _plans_overview_text(user_id: int) -> str:
    parts = [
        "⭐ Подписка и тарифы",
        "Выбери подходящий уровень — доступ откроется сразу после оплаты.",
        _sub_info_text(user_id),
        "— — —",
        _plan_card_text("start"),
        _plan_card_text("pro"),
        _plan_card_text("ultimate"),
        "Выберите тариф кнопкой ниже.",
    ]
    return "\n".join(parts)

def plans_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⭐ START",    callback_data="plan:start"),
            InlineKeyboardButton("🚀 PRO",      callback_data="plan:pro"),
            InlineKeyboardButton("👑 ULTIMATE", callback_data="plan:ultimate"),
        ]
    ])

def plan_pay_kb(plan_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💳 Оплатить — ЮKassa", callback_data=f"pay:yookassa:{plan_key}"),
        ],
        [
            InlineKeyboardButton("💠 Оплатить — CryptoBot", callback_data=f"pay:cryptobot:{plan_key}"),
        ],
        [
            InlineKeyboardButton("🧾 Списать с баланса", callback_data=f"pay:balance:{plan_key}"),
        ],
        [
            InlineKeyboardButton("⬅️ К тарифам", callback_data="plan:root"),
        ]
    ])

# Кнопка «⭐ Подписка · Помощь»
async def on_btn_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = _plans_overview_text(user_id)
    await update.effective_chat.send_message(text, reply_markup=plans_root_kb())

# Обработчик наших колбэков по подписке/оплатам (зарегистрировать ДО общего on_cb!)
async def on_cb_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    user_id = q.from_user.id
    chat_id = q.message.chat.id  # PTB v21+

    # Навигация между тарифами
    if data.startswith("plan:"):
        _, arg = data.split(":", 1)
        if arg == "root":
            await q.edit_message_text(_plans_overview_text(user_id), reply_markup=plans_root_kb())
            await q.answer()
            return
        if arg in SUBS_TIERS:
            await q.edit_message_text(
                _plan_card_text(arg) + "\nВыберите способ оплаты:",
                reply_markup=plan_pay_kb(arg),
            )
            await q.answer()
            return

    # Платежи
    if data.startswith("pay:"):
        # безопасный парсинг
        try:
            _, method, plan_key = data.split(":", 2)
        except ValueError:
            await q.answer("Некорректные данные кнопки.", show_alert=True)
            return

        plan = SUBS_TIERS.get(plan_key)
        if not plan:
            await q.answer("Неизвестный тариф.", show_alert=True)
            return

        # ЮKassa через Telegram Payments
        if method == "yookassa":
            if not YOOKASSA_PROVIDER_TOKEN:
                await q.answer("ЮKassa не подключена (нет YOOKASSA_PROVIDER_TOKEN).", show_alert=True)
                return

            title = f"Подписка {plan['title']} • 1 месяц"
            desc = "Доступ к функциям бота согласно выбранному тарифу. Подписка активируется сразу после оплаты."
            payload = json.dumps({"tier": plan_key, "months": 1})

            # Telegram ожидает сумму в минорных единицах (копейки/центы)
            if YOOKASSA_CURRENCY == "RUB":
                total_minor = int(round(float(plan["rub"]) * 100))
            else:
                total_minor = int(round(float(plan["usd"]) * 100))

            prices = [LabeledPrice(label=f"{plan['title']} 1 мес.", amount=total_minor)]
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
            await q.answer("Счёт выставлен ✅")
            return

        # CryptoBot (Crypto Pay API: создаём инвойс и отдаём ссылку)
        if method == "cryptobot":
            if not CRYPTO_PAY_API_TOKEN:
                await q.answer("CryptoBot не подключён (нет CRYPTO_PAY_API_TOKEN).", show_alert=True)
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
                            "description": f"Subscription {plan['title']} • 1 month",
                            "allow_comments": False,
                            "allow_anonymous": True,
                        },
                    )
                data_j = r.json()
                if not data_j.get("ok"):
                    raise RuntimeError(str(data_j))
                res = data_j["result"]
                pay_url = res["pay_url"]
                inv_id = str(res["invoice_id"])

                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💠 Оплатить в CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("⬅️ К тарифу", callback_data=f"plan:{plan_key}")],
                ])

                msg = await q.edit_message_text(
                    _plan_card_text(plan_key) + "\nОткройте ссылку для оплаты:",
                    reply_markup=kb,
                )

                # фоновый опрос конкретного инвойса до оплаты/отмены
                context.application.create_task(_poll_crypto_sub_invoice(
                    context, chat_id, msg.message_id, user_id, inv_id, plan_key, 1
                ))
                await q.answer()
            except Exception as e:
                await q.answer("Не удалось создать счёт в CryptoBot.", show_alert=True)
                log.exception("CryptoBot invoice error: %s", e)
            return

        # Списание с внутреннего баланса (USD)
        if method == "balance":
            price_usd = float(plan["usd"])
            if not _user_balance_debit(user_id, price_usd):
                await q.answer("Недостаточно средств на внутреннем балансе.", show_alert=True)
                return
            until = _sub_activate(user_id, plan_key, months=1)
            await q.edit_message_text(
                f"✅ Подписка {plan['title']} активирована до {until[:10]}.\n"
                f"💵 Списано: {_money_fmt_usd(price_usd)}. "
                f"Текущий баланс: {_money_fmt_usd(_user_balance_get(user_id))}",
                reply_markup=plans_root_kb(),
            )
            await q.answer()
            return

    # Если колбэк не наш — пропускаем дальше
    await q.answer()
    return


# Если у тебя уже есть on_precheckout / on_successful_payment — оставь их.
# Если нет, можешь использовать эти простые реализации:

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.pre_checkout_query.answer(ok=True)
    except Exception as e:
        log.exception("precheckout error: %s", e)

async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Универсальный обработчик Telegram Payments:
    - Поддерживает payload в двух форматах:
        1) JSON: {"tier":"pro","months":1}
        2) Строка: "sub:pro:1"
    - Иначе трактует как пополнение единого USD-кошелька.
    """
    try:
        sp = update.message.successful_payment
        payload_raw = sp.invoice_payload or ""
        total_minor = sp.total_amount or 0
        rub = total_minor / 100.0
        uid = update.effective_user.id

        # 1) Пытаемся распарсить JSON
        tier, months = None, None
        try:
            if payload_raw.strip().startswith("{"):
                obj = json.loads(payload_raw)
                tier = (obj.get("tier") or "").strip().lower() or None
                months = int(obj.get("months") or 1)
        except Exception:
            pass

        # 2) Пытаемся распарсить строковый формат "sub:tier:months"
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
                f"🎉 Оплата прошла успешно!\n"
                f"✅ Подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')}."
            )
            return

        # Иначе считаем, что это пополнение кошелька в рублях
        usd = rub / max(1e-9, USD_RUB)
        _wallet_total_add(uid, usd)
        await update.effective_message.reply_text(
            f"💳 Пополнение: {rub:.0f} ₽ ≈ ${usd:.2f} зачислено на единый баланс."
        )

    except Exception as e:
        log.exception("successful_payment handler error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("⚠️ Ошибка обработки платежа. Если деньги списались — напишите в поддержку.")

# ---------- Background jobs (фоновые задачи платежей) ----------
from telegram.ext import Application
from typing import Coroutine, Any
import asyncio

_BG_TASKS: list[asyncio.Task] = []

async def _crypto_daemon(application: Application):
    """Фоновый опрос крипто/подписок (пример бесконечного цикла)."""
    log.info("BG[crypto_daemon]: start")
    while True:
        try:
            # TODO: здесь твоя периодическая логика (если понадобится)
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            log.info("BG[crypto_daemon]: cancelled")
            raise
        except Exception as e:
            log.exception("crypto_daemon error: %s", e)
            await asyncio.sleep(5)

async def _yookassa_daemon(application: Application):
    """Фоновый опрос инвойсов YooKassa (если используется)."""
    log.info("BG[yookassa_daemon]: start")
    while True:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            log.info("BG[yookassa_daemon]: cancelled")
            raise
        except Exception as e:
            log.exception("yookassa_daemon error: %s", e)
            await asyncio.sleep(5)

def _create_bg_task(application: Application, coro: Coroutine[Any, Any, Any], name: str):
    """Безопасное создание фоновой задачи в PTB."""
    t = application.create_task(coro)
    try:
        t.set_name(name)
    except Exception:
        pass
    _BG_TASKS.append(t)
    log.info("BG: scheduled %s", name)

def _start_background_jobs(application: Application) -> None:
    """Регистрируем все фоновые задачи (вызывается из _post_init)."""
    _create_bg_task(application, _crypto_daemon(application),   "crypto_daemon")
    _create_bg_task(application, _yookassa_daemon(application), "yookassa_daemon")

async def _post_init(app: Application):
    _start_background_jobs(app)
# ---------------------------------------------------------------

# ⚙️ ВНИМАНИЕ: при создании Application добавь .post_init(_post_init)
# пример:
# application = (
#     ApplicationBuilder()
#     .token(BOT_TOKEN)
#     .post_init(_post_init)   # ← вот это важно
#     .build()
# )
# И не забудь зарегистрировать хендлеры оплаты:
# application.add_handler(PreCheckoutQueryHandler(on_precheckout))
# application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

# ───────── Команда /img ─────────
async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip() if context.args else ""
    if not prompt:
        await update.effective_message.reply_text("Формат: /img <описание>")
        return

    async def _go():
        await _do_img_generate(update, context, prompt)

    user_id = update.effective_user.id
    await _try_pay_then_do(
        update, context, user_id,
        "img", IMG_COST_USD, _go,
        remember_kind="img_generate", remember_payload={"prompt": prompt}
    )


# ───────── Photo quick actions ─────────
def photo_quick_actions_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Оживить фото (Runway)", callback_data="pedit:revive")],
        [InlineKeyboardButton("🧼 Удалить фон",  callback_data="pedit:removebg"),
         InlineKeyboardButton("🖼 Заменить фон", callback_data="pedit:replacebg")],
        [InlineKeyboardButton("🧭 Расширить кадр (outpaint)", callback_data="pedit:outpaint"),
         InlineKeyboardButton("📽 Раскадровка", callback_data="pedit:story")],
        [InlineKeyboardButton("🖌 Картинка по описанию (Luma)", callback_data="pedit:lumaimg")],
        [InlineKeyboardButton("👁 Анализ фото", callback_data="pedit:vision")],
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
        await update.effective_message.reply_text("rembg не установлен. Установите rembg/onnxruntime.")
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
        big.paste(bg, (0, 0)); big.paste(im, (pad, pad))
        bio = BytesIO(); big.save(bio, format="JPEG", quality=92); bio.seek(0); bio.name = "outpaint.jpg"
        await update.effective_message.reply_photo(InputFile(bio), caption="Простой outpaint: расширил полотно с мягкими краями.")
    except Exception as e:
        log.exception("outpaint error: %s", e)
        await update.effective_message.reply_text("Не удалось сделать outpaint.")

async def _pedit_storyboard(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    try:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        desc = await ask_openai_vision("Опиши ключевые элементы кадра очень кратко.", b64, sniff_image_mime(img_bytes))
        plan = await ask_openai_text(
            "Сделай раскадровку (6 кадров) под 6–10 секундный клип. "
            "Каждый кадр — 1 строка: кадр/действие/ракурс/свет. Основа:\n" + (desc or "")
        )
        await update.effective_message.reply_text("Раскадровка:\n" + plan)
    except Exception as e:
        log.exception("storyboard error: %s", e)
        await update.effective_message.reply_text("Не удалось построить раскадровку.")


# ───────── WebApp data (тарифы/пополнения) ─────────
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
            desc = f"Оформление подписки {tier.upper()} на {months} мес."
            await update.effective_message.reply_text(
                f"{desc}\nВыберите способ:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить картой (ЮKassa)", callback_data=f"buyinv:{tier}:{months}")],
                    [InlineKeyboardButton("Списать с баланса (USD)",  callback_data=f"buywallet:{tier}:{months}")],
                ])
            )
            return

        if typ in ("topup_rub", "rub_topup"):
            amount_rub = int(data.get("amount") or 0)
            if amount_rub < MIN_RUB_FOR_INVOICE:
                await update.effective_message.reply_text(f"Минимальная сумма: {MIN_RUB_FOR_INVOICE} ₽")
                return
            await _send_invoice_rub("Пополнение баланса", "Единый кошелёк", amount_rub, "t=3", update)
            return

        if typ in ("topup_crypto", "crypto_topup"):
            if not CRYPTO_PAY_API_TOKEN:
                await update.effective_message.reply_text("CryptoBot не настроен.")
                return
            usd = float(data.get("usd") or 0)
            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(usd, asset="USDT")
            if not inv_id or not pay_url:
                await update.effective_message.reply_text("Не удалось создать счёт в CryptoBot.")
                return
            msg = await update.effective_message.reply_text(
                f"Оплатите через CryptoBot: ≈ ${usd_amount:.2f} ({asset}).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить в CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("Проверить оплату", callback_data=f"crypto:check:{inv_id}")]
                ])
            )
            context.application.create_task(_poll_crypto_invoice(
                context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id, usd_amount
            ))
            return

        await update.effective_message.reply_text("Получены данные из мини-приложения, но команда не распознана.")
    except Exception as e:
        log.exception("on_webapp_data error: %s", e)
        await update.effective_message.reply_text("Ошибка обработки данных мини-приложения.")


# ───────── CallbackQuery (всё остальное) ─────────
_pending_actions = {}

def _new_aid() -> str:
    return uuid.uuid4().hex[:12]

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()
    try:
        # TOPUP меню
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
                await q.edit_message_text(f"Минимальная сумма пополнения: {MIN_RUB_FOR_INVOICE} ₽")
                return
            ok = await _send_invoice_rub("Пополнение баланса", "Единый кошелёк для перерасходов.", amount_rub, "t=3", update)
            await q.answer("Выставляю счёт…" if ok else "Не удалось выставить счёт", show_alert=not ok)
            return

        # TOPUP CRYPTO
        if data.startswith("topup:crypto:"):
            await q.answer()
            if not CRYPTO_PAY_API_TOKEN:
                await q.edit_message_text("Настройте CRYPTO_PAY_API_TOKEN для оплаты через CryptoBot.")
                return
            try:
                usd = float((data.split(":", 2)[-1] or "0").strip() or "0")
            except Exception:
                usd = 0.0
            if usd <= 0.0:
                await q.edit_message_text("Неверная сумма.")
                return
            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(usd, asset="USDT", description="Wallet top-up")
            if not inv_id or not pay_url:
                await q.edit_message_text("Не удалось создать счёт в CryptoBot. Попробуйте позже.")
                return
            msg = await update.effective_message.reply_text(
                f"Оплатите через CryptoBot: ≈ ${usd_amount:.2f} ({asset}).\nПосле оплаты баланс пополнится автоматически.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить в CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("Проверить оплату", callback_data=f"crypto:check:{inv_id}")]
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
                await q.edit_message_text("Не нашёл счёт. Создайте новый.")
                return
            st = (inv.get("status") or "").lower()
            if st == "paid":
                usd_amount = float(inv.get("amount", 0.0))
                if (inv.get("asset") or "").upper() == "TON":
                    usd_amount *= TON_USD_RATE
                _wallet_total_add(update.effective_user.id, usd_amount)
                await q.edit_message_text(f"💳 Оплата получена. Баланс пополнен на ≈ ${usd_amount:.2f}.")
            elif st == "active":
                await q.answer("Платёж ещё не подтверждён", show_alert=True)
            else:
                await q.edit_message_text(f"Статус счёта: {st}")
            return

        # Подписка: выбор способа
        if data.startswith("buy:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            desc = f"Подписка {tier.upper()} на {months} мес."
            await q.edit_message_text(
                f"{desc}\nВыберите способ оплаты:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить картой (ЮKassa)", callback_data=f"buyinv:{tier}:{months}")],
                    [InlineKeyboardButton("Списать с баланса (USD)",  callback_data=f"buywallet:{tier}:{months}")],
                ])
            )
            return

        # Подписка через ЮKassa
        if data.startswith("buyinv:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            payload, amount_rub, title = _plan_payload_and_amount(tier, months)
            desc = f"Оформление подписки {tier.upper()} на {months} мес."
            ok = await _send_invoice_rub(title, desc, amount_rub, payload, update)
            if not ok:
                await q.answer("Не удалось выставить счёт", show_alert=True)
            return

        # Подписка списанием из USD-баланса
        if data.startswith("buywallet:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            amount_rub = _plan_rub(tier, {1: "month", 3: "quarter", 12: "year"}[months])
            need_usd = float(amount_rub) / max(1e-9, USD_RUB)
            if _wallet_total_take(update.effective_user.id, need_usd):
                until = activate_subscription_with_tier(update.effective_user.id, tier, months)
                await q.edit_message_text(
                    f"✅ Подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')}.\n"
                    f"Списано с баланса: ~${need_usd:.2f}."
                )
            else:
                await q.edit_message_text(
                    "Недостаточно средств на едином балансе.\nПополните баланс и повторите.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]])
                )
            return

        # Выбор движка
        if data.startswith("engine:"):
            await q.answer()
            engine = data.split(":", 1)[1]
            username = (update.effective_user.username or "")
            if is_unlimited(update.effective_user.id, username):
                await q.edit_message_text(
                    f"✅ Движок «{engine}» доступен без ограничений.\n"
                    f"Отправьте задачу, например: «сделай видео ретро-авто, 9 секунд, 9:16»."
                )
                return

            if engine in ("gpt", "stt_tts", "midjourney"):
                await q.edit_message_text(
                    f"✅ Выбран «{engine}». Отправьте запрос текстом/фото. "
                    f"Для Luma/Runway/Images действуют дневные бюджеты тарифа."
                )
                return

            est_cost = IMG_COST_USD if engine == "images" else (0.40 if engine == "luma" else max(1.0, RUNWAY_UNIT_COST_USD))
            map_engine = {"images": "img", "luma": "luma", "runway": "runway"}[engine]
            ok, offer = _can_spend_or_offer(update.effective_user.id, username, map_engine, est_cost)

            if ok:
                await q.edit_message_text(
                    "✅ Доступно. " +
                    ("Запустите: /img кот в очках" if engine == "images"
                     else "Напишите: «сделай видео … 9 секунд 9:16» — предложу Luma/Runway.")
                )
                return

            if offer == "ASK_SUBSCRIBE":
                await q.edit_message_text(
                    "Для этого движка нужна активная подписка или единый баланс. Откройте /plans или пополните «🧾 Баланс».",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
                         [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
                    ),
                )
                return

            try:
                need_usd = float(offer.split(":", 1)[-1])
            except Exception:
                need_usd = est_cost
            amount_rub = _calc_oneoff_price_rub(map_engine, need_usd)
            await q.edit_message_text(
                f"Ваш дневной лимит по «{engine}» исчерпан. Разовая покупка ≈ {amount_rub} ₽ "
                f"или пополните баланс в «🧾 Баланс».",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
                        [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")],
                    ]
                ),
            )
            return

        # Режимы / Движки
        if data == "mode:engines":
            await q.answer()
            await q.edit_message_text("Движки:", reply_markup=engines_kb())
            return

        if data.startswith("mode:set:"):
            await q.answer()
            mode = data.split(":")[-1]
            mode_set(update.effective_user.id, mode)
            if mode == "study":
                study_sub_set(update.effective_user.id, "explain")
                await q.edit_message_text("Режим «Учёба» включён. Выберите подрежим:", reply_markup=study_kb())
            elif mode == "photo":
                await q.edit_message_text("Режим «Фото» включён. Пришлите изображение — появятся быстрые кнопки.", reply_markup=photo_quick_actions_kb())
            elif mode == "docs":
                await q.edit_message_text("Режим «Документы». Пришлите PDF/DOCX/EPUB/TXT — сделаю конспект.")
            elif mode == "voice":
                await q.edit_message_text("Режим «Голос». Отправьте voice/audio. Озвучка ответов: /voice_on")
            else:
                await q.edit_message_text(f"Режим «{mode}» активирован.")
            return

        if data.startswith("study:set:"):
            await q.answer()
            sub = data.split(":")[-1]
            study_sub_set(update.effective_user.id, sub)
            await q.edit_message_text(f"Учёба → {sub}. Напишите тему/задание.", reply_markup=study_kb())
            return

        # Photo edits require cached image
        if data.startswith("pedit:"):
            await q.answer()
            img = _get_cached_photo(update.effective_user.id)
            if not img:
                await q.edit_message_text("Сначала пришлите фото, затем выберите действие.", reply_markup=photo_quick_actions_kb())
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
                    await q.edit_message_text("Сначала пришлите фото, затем нажмите «Оживить фото».")
                    return
                dur, asp = parse_video_opts("")  # дефолт из ENV
                async def _go():
                    await _run_runway_animate_photo(update, context, img, prompt="", duration_s=dur, aspect=asp)
                await _try_pay_then_do(update, context, update.effective_user.id, "runway",
                                       max(1.0, RUNWAY_UNIT_COST_USD * (dur / max(1, RUNWAY_DURATION_S))),
                                       _go, remember_kind="revive_photo_btn",
                                       remember_payload={"duration": dur, "aspect": asp})
                return

            if data == "pedit:lumaimg":
                _mode_track_set(update.effective_user.id, "lumaimg_wait_text")
                await q.edit_message_text("Напишите одно предложение — что сгенерировать. Я сделаю картинку (Luma / фолбэк OpenAI).")
                return
            if data == "pedit:vision":
                b64 = base64.b64encode(img).decode("ascii")
                mime = sniff_image_mime(img)
                ans = await ask_openai_vision("Опиши фото и текст на нём кратко.", b64, mime)
                await update.effective_message.reply_text(ans or "Готово.")
                return

        # Подтверждение выбора движка для видео
        if data.startswith("choose:"):
            await q.answer()
            _, engine, aid = data.split(":", 2)
            meta = _pending_actions.pop(aid, None)
            if not meta:
                await q.answer("Задача устарела", show_alert=True)
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

        await q.answer("Неизвестная команда", show_alert=True)

    except Exception as e:
        log.exception("on_cb error: %s", e)
    finally:
        with contextlib.suppress(Exception):
            await q.answer()


# ───────── STT ─────────
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


# ───────── Диагностика движков ─────────
async def cmd_diag_stt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = []
    lines.append("🔎 STT диагностика:")
    lines.append(f"• Deepgram: {'✅ ключ найден' if DEEPGRAM_API_KEY else '❌ нет ключа'}")
    lines.append(f"• OpenAI Whisper: {'✅ клиент активен' if oai_stt else '❌ недоступен'}")
    lines.append(f"• Модель Whisper: {TRANSCRIBE_MODEL}")
    lines.append("• Поддержка форматов: ogg/oga, mp3, m4a/mp4, wav, webm")
    await update.effective_message.reply_text("\n".join(lines))

async def cmd_diag_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key_env  = os.environ.get("OPENAI_IMAGE_KEY", "").strip()
    key_used = key_env or OPENAI_API_KEY
    base     = IMAGES_BASE_URL
    lines = [
        "🧪 Images (OpenAI) диагностика:",
        f"• OPENAI_IMAGE_KEY: {'✅ найден' if key_used else '❌ нет'}",
        f"• BASE_URL: {base}",
        f"• MODEL: {IMAGES_MODEL}",
    ]
    if "openrouter" in (base or "").lower():
        lines.append("⚠️ BASE_URL указывает на OpenRouter — там нет gpt-image-1.")
        lines.append("   Укажи https://api.openai.com/v1 (или свой прокси) в OPENAI_IMAGE_BASE_URL.")
    await update.effective_message.reply_text("\n".join(lines))

async def cmd_diag_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [
        "🎬 Видео-движки:",
        f"• Luma key: {'✅' if bool(LUMA_API_KEY) else '❌'}  base={LUMA_BASE_URL}",
        f"  create={LUMA_CREATE_PATH}  status={LUMA_STATUS_PATH}",
        f"  model={LUMA_MODEL}  allowed_durations=['5s','9s','10s']  aspect=['16:9','9:16','1:1']",
        f"• Runway key: {'✅' if bool(RUNWAY_API_KEY) else '❌'}  base={RUNWAY_BASE_URL}",
        f"  create={RUNWAY_CREATE_PATH}  status={RUNWAY_STATUS_PATH}",
        f"• Поллинг каждые {VIDEO_POLL_DELAY_S:.1f} c",
    ]
    await update.effective_message.reply_text("\n".join(lines))


# ───────── MIME для изображений ─────────
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


# ───────── Парс опций видео ─────────
_ASPECTS = {"9:16", "16:9", "1:1", "4:5", "3:4", "4:3"}

def parse_video_opts(text: str) -> tuple[int, str]:
    tl = (text or "").lower()
    m = re.search(r"(\d+)\s*(?:сек|с)\b", tl)
    duration = int(m.group(1)) if m else LUMA_DURATION_S
    duration = max(3, min(20, duration))
    asp = None
    for a in _ASPECTS:
        if a in tl:
            asp = a; break
    aspect = asp or (LUMA_ASPECT if LUMA_ASPECT in _ASPECTS else "16:9")
    return duration, aspect


# ───────── Luma video ─────────
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
                await update.effective_message.reply_text(f"⚠️ Luma отклонила задачу ({r.status_code}).")
                return
            rid = (r.json() or {}).get("id") or (r.json() or {}).get("generation_id")
            if not rid:
                await update.effective_message.reply_text("⚠️ Luma не вернула id генерации.")
                return

            await update.effective_message.reply_text("⏳ Luma рендерит… Я сообщу, когда видео будет готово.")

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
                        await update.effective_message.reply_text("⚠️ Готово, но нет ссылки на видео.")
                        return
                    try:
                        v = await client.get(url, timeout=120.0)
                        v.raise_for_status()
                        bio = BytesIO(v.content); bio.name = "luma.mp4"
                        await update.effective_message.reply_video(InputFile(bio), caption="🎬 Luma: готово ✅")
                    except Exception:
                        await update.effective_message.reply_text(f"🎬 Luma: готово ✅\n{url}")
                    return
                if st in ("failed", "error", "canceled", "cancelled"):
                    await update.effective_message.reply_text("❌ Luma: ошибка рендера.")
                    return
                if time.time() - started > LUMA_MAX_WAIT_S:
                    await update.effective_message.reply_text("⌛ Luma: время ожидания вышло.")
                    return
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("Luma error: %s", e)
        await update.effective_message.reply_text("❌ Luma: не удалось запустить/получить видео.")

# ==== LUMA CLIENT (PATCH B) ====
import httpx, asyncio

LUMA_API_KEY = os.getenv("LUMA_API_KEY", "")

LUMA_BASE = "https://api.lumalabs.ai/dream-machine/v1"

async def luma_text2video(prompt: str, duration_s: int = 5, aspect_ratio: str = "16:9") -> dict:
    if not LUMA_API_KEY:
        raise RuntimeError("LUMA_API_KEY пустой")

    headers = {
        "Authorization": f"Bearer {LUMA_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "prompt": prompt,
        "duration": duration_s,
        "aspect_ratio": aspect_ratio
    }

    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(f"{LUMA_BASE}/generations", headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        gen_id = data.get("id")
        if not gen_id:
            raise RuntimeError(f"Luma: не пришёл id генерации: {data}")

        for _ in range(120):  # до ~10 минут
            rr = await client.get(f"{LUMA_BASE}/generations/{gen_id}", headers=headers)
            rr.raise_for_status()
            info = rr.json()
            status = info.get("state") or info.get("status")
            if status in ("completed", "succeeded", "complete"):
                return info
            if status in ("failed", "error", "rejected"):
                raise RuntimeError(f"Luma: ошибка/отклонено: {info}")
            await asyncio.sleep(5)

        raise TimeoutError("Luma: не дождались результата")
# ==== /LUMA CLIENT (PATCH B) ====


# ───────── Runway video ─────────
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
                await update.effective_message.reply_text(f"⚠️ Runway отклонил задачу ({r.status_code}).")
                return
            rid = (r.json() or {}).get("id") or (r.json() or {}).get("task_id")
            if not rid:
                await update.effective_message.reply_text("⚠️ Runway не вернул id задачи.")
                return

            await update.effective_message.reply_text("⏳ Runway рендерит… Я сообщу, когда видео будет готово.")

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
                        await update.effective_message.reply_text("⚠️ Готово, но нет ссылки на видео.")
                        return
                    try:
                        v = await client.get(url, timeout=180.0)
                        v.raise_for_status()
                        bio = BytesIO(v.content); bio.name = "runway.mp4"
                        await update.effective_message.reply_video(InputFile(bio), caption="🎥 Runway: готово ✅")
                    except Exception:
                        await update.effective_message.reply_text(f"🎥 Runway: готово ✅\n{url}")
                    return
                if st in ("failed", "error", "canceled", "cancelled"):
                    await update.effective_message.reply_text("❌ Runway: ошибка рендера.")
                    return
                if time.time() - started > RUNWAY_MAX_WAIT_S:
                    await update.effective_message.reply_text("⌛ Runway: время ожидания вышло.")
                    return
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("Runway error: %s", e)
        await update.effective_message.reply_text("❌ Runway: не удалось запустить/получить видео.")

# ───────── Runway: анимация загруженного фото (image→video) ─────────
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
                # ключи init_image / image_data поддерживаются актуальными версиями API
                # если у тебя другой формат — скорректируй поля ниже под свой аккаунт:
                "init_image": f"data:{sniff_image_mime(img_bytes)};base64,{b64}"
            }
        }
        headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{RUNWAY_BASE_URL}{RUNWAY_CREATE_PATH}", headers=headers, json=payload)
            if r.status_code >= 400:
                await update.effective_message.reply_text(f"⚠️ Runway отклонил задачу ({r.status_code}).")
                return
            rid = (r.json() or {}).get("id") or (r.json() or {}).get("task_id")
            if not rid:
                await update.effective_message.reply_text("⚠️ Runway не вернул id задачи.")
                return

            await update.effective_message.reply_text("⏳ Оживляю фото в Runway… Сообщу, когда будет готово.")

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
                        await update.effective_message.reply_text("⚠️ Готово, но нет ссылки на видео.")
                        return
                    try:
                        v = await client.get(url, timeout=180.0)
                        v.raise_for_status()
                        bio = BytesIO(v.content); bio.name = "revive.mp4"
                        await update.effective_message.reply_video(InputFile(bio), caption="✨ Оживил фото (Runway) ✅")
                    except Exception:
                        await update.effective_message.reply_text(f"✨ Оживил фото (Runway) ✅\n{url}")
                    return
                if st in ("failed", "error", "canceled", "cancelled"):
                    await update.effective_message.reply_text("❌ Runway: ошибка рендера.")
                    return
                if time.time() - started > RUNWAY_MAX_WAIT_S:
                    await update.effective_message.reply_text("⌛ Runway: время ожидания вышло.")
                    return
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("Runway revive error: %s", e)
        await update.effective_message.reply_text("❌ Не удалось анимировать фото в Runway.")

# ==== RUNWAY CLIENT (PATCH A) ====
async def runway_text2video(prompt: str, duration_s: int = 5, aspect_ratio: str = "16:9") -> dict:
    """
    Создаёт t2v-генерацию и возвращает финальный объект с ссылкой на видео.
    Поллинг до готовности. Бросает исключение при 4xx/5xx.
    """
    if not RUNWAY_API_KEY:
        raise RuntimeError("RUNWAY_API_KEY пустой")

    headers = {
        "Authorization": f"Bearer {RUNWAY_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "mode": "text_to_video",
        "prompt": prompt,
        "duration": duration_s,
        "aspect_ratio": aspect_ratio
    }

    async with httpx.AsyncClient(timeout=90) as client:
        # старт
        r = await client.post(f"{RUNWAY_BASE}/generations", headers=headers, json=payload)
        if r.status_code == 401:
            raise RuntimeError(f"Runway 401 Unauthorized. Проверь ключ и заголовок Authorization. Ответ: {r.text}")
        r.raise_for_status()
        data = r.json()
        gen_id = data.get("id")
        if not gen_id:
            raise RuntimeError(f"Runway: не пришёл id генерации: {data}")

        # поллинг
        for _ in range(120):  # до ~10 минут
            rr = await client.get(f"{RUNWAY_BASE}/generations/{gen_id}", headers=headers)
            if rr.status_code == 401:
                raise RuntimeError(f"Runway 401 при поллинге. Ответ: {rr.text}")
            rr.raise_for_status()
            info = rr.json()
            status = info.get("status")
            if status in ("completed", "succeeded"):
                return info
            if status in ("failed", "canceled", "rejected"):
                raise RuntimeError(f"Runway: задача отклонена/ошибка: {info}")
            await asyncio.sleep(5)

        raise TimeoutError("Runway: не дождались результата")
# ==== /RUNWAY CLIENT (PATCH A) ====

# -*- coding: utf-8 -*-
"""
Покупки/инвойсы, крипто-платежи, медиа-роутинг и единый CallbackQuery-роутер.
Собрано без дублей, с безопасной регистрацией хендлеров (PTB 21.x).
"""

# ==== IMPORTS & GLOBALS =======================================================
import os
import re
import json
import httpx
import asyncio
import logging
import contextlib
from io import BytesIO

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, WebAppInfo,
)
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, PreCheckoutQueryHandler, filters,
)

log = logging.getLogger(__name__)

# Безопасные дефолты для внешних констант, если не объявлены где-то ещё
try:
    USD_RUB  # type: ignore[name-defined]
except NameError:
    USD_RUB = float(os.environ.get("USD_RUB", "100"))

try:
    TARIFF_URL  # type: ignore[name-defined]
except NameError:
    TARIFF_URL = "https://example.com/tariffs"

# ───── безопасный фолбэк рассчёта разовой цены (если нет вашей реализации) ─────
try:
    _calc_oneoff_price_rub  # type: ignore[name-defined]
except NameError:
    def _calc_oneoff_price_rub(engine: str, need_usd: float) -> int:
        return int(round(float(need_usd) * float(USD_RUB)))

def _ascii_label(s: str) -> str:
    try:
        s = (s or "").strip()
        return s.encode("ascii", "ignore").decode() or "Item"
    except Exception:
        return "Item"

def _pick_first_defined(*names):
    for n in names:
        fn = globals().get(n)
        if callable(fn):
            return fn
    return None


# ==== ПЛАТЁЖИ: ЮKassa / Telegram Payments =====================================
# Ожидается, что PLAN_PRICE_TABLE и токены определены выше в проекте
# PLAN_PRICE_TABLE = {"start":{"month":...,"quarter":...,"year":...}, ...}
def _plan_rub(tier: str, term: str) -> int:
    tier = (tier or "pro").lower()
    term = (term or "month").lower()
    return int(PLAN_PRICE_TABLE.get(tier, PLAN_PRICE_TABLE["pro"]).get(term, PLAN_PRICE_TABLE["pro"]["month"]))  # type: ignore[name-defined]

def _plan_payload_and_amount(tier: str, months: int) -> tuple[str, int, str]:
    term_map = {1: "month", 3: "quarter", 12: "year"}
    term = term_map.get(months, "month")
    amount = _plan_rub(tier, term)
    title = f"Подписка {tier.upper()} ({term})"
    payload = f"sub:{tier}:{months}"
    return payload, amount, title

async def _send_invoice_rub(title: str, desc: str, amount_rub: int, payload: str, update: Update) -> bool:
    try:
        token = (os.environ.get("YOOKASSA_PROVIDER_TOKEN") or os.environ.get("PROVIDER_TOKEN") or "").strip()
        curr  = (os.environ.get("YOOKASSA_CURRENCY") or os.environ.get("CURRENCY") or "RUB").strip()

        if not token:
            await update.effective_message.reply_text("⚠️ ЮKassa не настроена (нет токена).")
            return False

        prices = [LabeledPrice(label=_ascii_label(title), amount=int(amount_rub) * 100)]
        await update.effective_message.reply_invoice(
            title=title[:32] or "Оплата",
            description=(desc or title)[:255],
            payload=payload,
            provider_token=token,
            currency=curr,
            prices=prices,
            need_email=False,
            need_name=False,
            need_phone_number=False,
            need_shipping_address=False,
            is_flexible=False,
        )
        return True
    except Exception as e:
        log.exception("send_invoice error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Не удалось выставить счёт.")
        return False

# Telegram Payments handlers
async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        q = update.pre_checkout_query
        await q.answer(ok=True)
    except Exception as e:
        log.exception("precheckout error: %s", e)

async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sp = update.message.successful_payment  # type: ignore[union-attr]
        payload = (sp.invoice_payload or "")
        total_minor = sp.total_amount or 0
        rub = total_minor / 100.0
        uid = update.effective_user.id

        if payload.startswith("sub:"):
            _, tier, months_s = payload.split(":", 2)
            months = int(months_s)
            until = activate_subscription_with_tier(uid, tier, months)  # type: ignore[name-defined]
            await update.effective_message.reply_text(
                f"✅ Подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')}."
            )
            return

        # Пополнение единого USD-кошелька
        usd = rub / max(1e-9, float(USD_RUB))
        _wallet_total_add(uid, usd)  # type: ignore[name-defined]
        await update.effective_message.reply_text(
            f"💳 Пополнение: {rub:.0f} ₽ ≈ ${usd:.2f} зачислено на единый баланс."
        )
    except Exception as e:
        log.exception("successful_payment handler error: %s", e)


# ==== CRYPTOBOT ================================================================
CRYPTO_PAY_API_TOKEN = os.environ.get("CRYPTO_PAY_API_TOKEN", "").strip()
CRYPTO_BASE = "https://pay.crypt.bot/api"

async def _crypto_create_invoice(usd_amount: float, asset: str = "USDT", description: str = "") -> tuple[str | None, str | None, float, str]:
    if not CRYPTO_PAY_API_TOKEN:
        return None, None, 0.0, asset
    try:
        payload = {"asset": asset, "amount": round(float(usd_amount), 2), "description": description or "Top-up"}
        headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{CRYPTO_BASE}/createInvoice", headers=headers, json=payload)
            j = r.json()
            if not j.get("ok"):
                return None, None, 0.0, asset
            res = (j.get("result") or {})  # type: ignore[assignment]
            return str(res.get("invoice_id")), res.get("pay_url"), float(res.get("amount", usd_amount)), (res.get("asset") or asset)
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

async def _poll_crypto_invoice(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    user_id: int,
    invoice_id: str,
    usd_amount: float,
):
    try:
        for _ in range(120):  # ~12 минут при 6с задержке
            inv = await _crypto_get_invoice(invoice_id)
            st = (inv or {}).get("status", "").lower() if inv else ""
            if st == "paid":
                _wallet_total_add(user_id, float(usd_amount))  # type: ignore[name-defined]
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"✅ CryptoBot: платёж подтверждён. Баланс пополнен на ${float(usd_amount):.2f}.",
                    )
                return
            if st in ("expired", "cancelled", "canceled", "failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"❌ CryptoBot: платёж не завершён (статус: {st}).",
                    )
                return
            await asyncio.sleep(6.0)

        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="⌛ CryptoBot: время ожидания вышло. Нажмите «Проверить оплату» позже.",
            )
    except Exception as e:
        log.exception("crypto poll error: %s", e)

async def _poll_crypto_sub_invoice(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    user_id: int,
    invoice_id: str,
    tier: str,
    months: int,
):
    try:
        for _ in range(120):
            inv = await _crypto_get_invoice(invoice_id)
            st = (inv or {}).get("status", "").lower() if inv else ""
            if st == "paid":
                until = activate_subscription_with_tier(user_id, tier, months)  # type: ignore[name-defined]
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=("✅ CryptoBot: платёж подтверждён.\n"
                              f"Подписка {tier.upper()} активна до {until.strftime('%Y-%m-%d')}."),
                    )
                return
            if st in ("expired", "cancelled", "canceled", "failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"❌ CryptoBot: оплата не завершена (статус: {st}).",
                    )
                return
            await asyncio.sleep(6.0)

        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="⌛ CryptoBot: время ожидания вышло. Нажмите «Проверить оплату» или оплатите заново.",
            )
    except Exception as e:
        log.exception("crypto poll (subscription) error: %s", e)


# ==== ПОПОЛНЕНИЕ / ПРЕДЛОЖЕНИЕ ===============================================
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
    ok, offer = _can_spend_or_offer(user_id, username, engine, est_cost_usd)  # type: ignore[name-defined]
    if ok:
        await coro_func()
        return
    if offer == "ASK_SUBSCRIBE":
        await update.effective_message.reply_text(
            "Для выполнения нужен тариф или единый баланс.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
                 [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
            )
        )
        return
    try:
        need_usd = float(offer.split(":", 1)[-1])
    except Exception:
        need_usd = est_cost_usd
    amount_rub = _calc_oneoff_price_rub(engine, need_usd)
    await update.effective_message.reply_text(
        f"Недостаточно лимита. Разовая покупка ≈ {amount_rub} ₽ или пополните баланс:",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
                [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")],
            ]
        ),
    )


# ==== /plans ==================================================================
async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["⭐ Тарифы:"]
    for tier, terms in PLAN_PRICE_TABLE.items():  # type: ignore[name-defined]
        lines.append(f"— {tier.upper()}: {terms['month']}₽/мес • {terms['quarter']}₽/квартал • {terms['year']}₽/год")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Купить START (1 мес)",    callback_data="buy:start:1"),
         InlineKeyboardButton("Купить PRO (1 мес)",      callback_data="buy:pro:1")],
        [InlineKeyboardButton("Купить ULTIMATE (1 мес)", callback_data="buy:ultimate:1")],
        [InlineKeyboardButton("Открыть мини-витрину",    web_app=WebAppInfo(url=TARIFF_URL))]
    ])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb)


# ==== TEXT ROUTER =============================================================
VIDEO_TRIGGERS        = re.compile(r"(сделай|создай|сгенерируй).*(видео|ролик)|\banimate\b|\bvideo\b", re.IGNORECASE)
PHOTO_ANIMATE_TRIGGERS= re.compile(r"(оживи|оживить|анимируй|оживление).*(фото|фотографию|изображение)", re.IGNORECASE)
IMAGE_TRIGGERS        = re.compile(r"(фото|изображени|картинк|picture|image)", re.IGNORECASE)

async def maybe_image_help(chat_id, text, context):
    if IMAGE_TRIGGERS.search(text or ""):
        msg = (
            "Да, я умею работать с изображениями: оживлять фото (image→video), "
            "удалять/заменять фон, добавлять/удалять объекты, расширять кадр, делать раскадровку.\n\n"
            "Пришли фото или опиши задачу. Для видео предложу движок: Runway или Luma (Kling — скоро)."
        )
        await context.bot.send_message(chat_id, msg)
        return True
    return False

async def smart_router_text(chat_id, text, context):
    if VIDEO_TRIGGERS.search(text):
        return await show_video_engine_picker(chat_id, context, text)
    if PHOTO_ANIMATE_TRIGGERS.search(text):
        return await show_photo_animate_picker(chat_id, context)
    # иначе — обычный GPT
    return await gpt_reply(chat_id, text, context)  # type: ignore[name-defined]

async def show_video_engine_picker(chat_id, context, user_prompt: str):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Runway (t2v)", callback_data=f"v_runway::{user_prompt}")],
        [InlineKeyboardButton("🎥 Luma (t2v)",   callback_data=f"v_luma::{user_prompt}")]
    ])
    await context.bot.send_message(chat_id, "Что использовать для видео?", reply_markup=kb)

async def show_photo_animate_picker(chat_id, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Оживить фото (Runway)", callback_data="photo_anim_runway")],
        [InlineKeyboardButton("🛰 Kling (скоро)",          callback_data="photo_anim_kling_disabled")]
    ])
    await context.bot.send_message(chat_id, "Окей! Выбери движок для анимации фото:", reply_markup=kb)

async def show_engine_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, engine: str):
    await update.effective_chat.send_message(
        f"Отлично, {engine.title()} готов. Напиши описание сцены (или пришли фото для image→video)."
    )

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    # Позитивный ответ о возможностях
    cap_fn = globals().get("capability_answer")
    if callable(cap_fn):
        cap = cap_fn(text)
        if cap:
            await update.effective_message.reply_text(cap)
            return

    # Хелп по изображениям
    if await maybe_image_help(update.effective_chat.id, text, context):
        return

    # Намёк на видео/картинку
    detect_fn = globals().get("detect_media_intent")
    if callable(detect_fn):
        mtype, rest = detect_fn(text)
        if mtype == "video":
            parse_opts = globals().get("parse_video_opts")
            if callable(parse_opts):
                duration, aspect = parse_opts(text)
            else:
                duration, aspect = 5, "16:9"
            prompt = (rest or re.sub(r"\b(\d+\s*(?:сек|с)\b|(?:9:16|16:9|1:1|4:5|3:4|4:3))", "", text, flags=re.I)).strip(" ,.")
            if not prompt:
                await update.effective_message.reply_text("Опишите, что именно снять, напр.: «ретро-авто на берегу, закат».")
                return
            aid_fn = globals().get("_new_aid")
            if callable(aid_fn):
                aid = aid_fn()
                globals().setdefault("_pending_actions", {})[aid] = {"prompt": prompt, "duration": duration, "aspect": aspect}
            est_luma = 0.40
            RUNWAY_UNIT = float(globals().get("RUNWAY_UNIT_COST_USD", 1.0))
            RUNWAY_TIME = max(1, int(globals().get("RUNWAY_DURATION_S", 5)))
            est_runway = max(1.0, RUNWAY_UNIT * (duration / RUNWAY_TIME))
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🎬 Luma (~${est_luma:.2f})",    callback_data=f"v_luma::{prompt}")],
                [InlineKeyboardButton(f"🎥 Runway (~${est_runway:.2f})", callback_data=f"v_runway::{prompt}")],
            ])
            await update.effective_message.reply_text(
                f"Что использовать?\nДлительность: {duration} c • Аспект: {aspect}\nЗапрос: «{prompt}»",
                reply_markup=kb
            )
            return
        if mtype == "image":
            prompt = (rest or re.sub(r"^(img|image|picture)\s*[:\-]\s*", "", text, flags=re.I)).strip()
            if not prompt:
                await update.effective_message.reply_text("Формат: /img <описание изображения>")
                return

            async def _go():
                gen_fn = globals().get("_do_img_generate")
                if callable(gen_fn):
                    await gen_fn(update, context, prompt)

            IMG_COST_USD = float(globals().get("IMG_COST_USD", 0.05))
            await _try_pay_then_do(update, context, update.effective_user.id, "img", IMG_COST_USD, _go)
            return

    # Обычный текст → GPT
    check_fn = globals().get("check_text_and_inc")
    ok = True
    if callable(check_fn):
        ok, _, _ = check_fn(update.effective_user.id, update.effective_user.username or "")
    if not ok:
        await update.effective_message.reply_text(
            "Лимит текстовых запросов на сегодня исчерпан. Оформите ⭐ подписку или попробуйте завтра."
        )
        return

    user_id = update.effective_user.id
    try:
        mode  = globals().get("_mode_get", lambda _uid: "none")(user_id)
        track = globals().get("_mode_track_get", lambda _uid: "")(user_id)
    except Exception:
        mode, track = "none", ""

    text_for_llm = text
    if mode and mode != "none":
        text_for_llm = f"[Режим: {mode}; Подрежим: {track or '-'}]\n{text}"

    if mode == "Учёба" and track and callable(globals().get("study_process_text")):
        await globals()["study_process_text"](update, context, text)  # type: ignore[index]
        return

    reply = await globals()["ask_openai_text"](text_for_llm)  # type: ignore[index]
    await update.effective_message.reply_text(reply)
    tts_fn = globals().get("maybe_tts_reply")
    if callable(tts_fn):
        await tts_fn(update, context, reply[: int(globals().get("TTS_MAX_CHARS", 400))])


# ==== MEDIA HANDLERS ==========================================================
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ph = update.message.photo[-1]  # type: ignore[union-attr]
        f = await ph.get_file()
        data = await f.download_as_bytearray()
        img = bytes(data)
        context.user_data["last_photo_id"] = ph.file_id
        context.user_data["last_photo_bytes"] = img

        cache_fn = globals().get("_cache_photo")
        if callable(cache_fn):
            cache_fn(update.effective_user.id, img)

        caption = (update.message.caption or "").strip()  # type: ignore[union-attr]
        if caption:
            tl = caption.lower()

            # оживить фото → Runway (по умолчанию)
            if any(k in tl for k in ("оживи", "анимиру", "сделай видео", "revive", "animate")):
                parse_opts = globals().get("parse_video_opts")
                dur, asp = (parse_opts(caption) if callable(parse_opts) else (5, "9:16"))
                prompt = re.sub(r"\b(оживи|оживить|анимируй|анимировать|сделай видео|revive|animate)\b", "", caption, flags=re.I).strip(" ,.")

                async def _go():
                    # Пытаемся найти вашу реализацию анимации
                    fn = _pick_first_defined("_run_runway_animate_photo", "runway_animate_photo")
                    if callable(fn):
                        await fn(update, context, img, prompt, dur, asp)

                RUNWAY_UNIT = float(globals().get("RUNWAY_UNIT_COST_USD", 1.0))
                RUNWAY_TIME = max(1, int(globals().get("RUNWAY_DURATION_S", 5)))
                est_cost = max(1.0, RUNWAY_UNIT * (dur / RUNWAY_TIME))
                await _try_pay_then_do(update, context, update.effective_user.id, "runway",
                                       est_cost, _go,
                                       remember_kind="revive_photo",
                                       remember_payload={"duration": dur, "aspect": asp, "prompt": prompt})
                return

            # удалить фон
            if any(k in tl for k in ("удали фон", "removebg", "убрать фон")):
                fn = _pick_first_defined("_pedit_removebg", "remove_bg")
                if callable(fn):
                    await fn(update, context, img)
                else:
                    await update.effective_message.reply_text("Функция удаления фона не подключена.")
                return

            # заменить фон
            if any(k in tl for k in ("замени фон", "replacebg", "размытый фон", "blur")):
                fn = _pick_first_defined("_pedit_replacebg", "replace_bg")
                if callable(fn):
                    await fn(update, context, img)
                else:
                    await update.effective_message.reply_text("Функция замены фона не подключена.")
                return

            # outpaint
            if "outpaint" in tl or "расшир" in tl:
                fn = _pick_first_defined("_pedit_outpaint", "outpaint")
                if callable(fn):
                    await fn(update, context, img)
                else:
                    await update.effective_message.reply_text("Функция расширения кадра не подключена.")
                return

            # раскадровка
            if "раскадров" in tl or "storyboard" in tl:
                fn = _pick_first_defined("_pedit_storyboard", "storyboard_make")
                if callable(fn):
                    await fn(update, context, img)
                else:
                    await update.effective_message.reply_text("Функция раскадровки не подключена.")
                return

            # картинка по описанию (Luma / fallback /img)
            if any(k in tl for k in ("картин", "изображен", "image", "img")) and any(k in tl for k in ("сгенериру", "созда", "сделай")):
                fn = _pick_first_defined("_start_luma_img", "start_luma_img", "cmd_img")
                if callable(fn):
                    await fn(update, context, caption)
                else:
                    await update.effective_message.reply_text("Введи /img и тему картинки, или пришли рефы.")
                return

        # если явной команды в подписи нет — показываем быстрые кнопки
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✨ Оживить фото", callback_data="photo_anim_picker")],
            [InlineKeyboardButton("🧽 Удалить фон", callback_data="photo_bg_remove"),
             InlineKeyboardButton("🖼 Заменить фон", callback_data="photo_bg_replace")],
            [InlineKeyboardButton("🧭 Расширить кадр", callback_data="photo_outpaint"),
             InlineKeyboardButton("🎬 Раскадровка", callback_data="photo_storyboard")],
            [InlineKeyboardButton("🖌 Картинка по описанию (Luma)", callback_data="img_luma"),
             InlineKeyboardButton("👁 Анализ фото", callback_data="img_analyze")]
        ])
        await update.message.reply_text("Фото получено. Что сделать?", reply_markup=kb)
    except Exception as e:
        log.exception("on_photo error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Не смог обработать фото.")

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
            context.user_data["last_photo_bytes"] = raw
            await update.effective_message.reply_text(
                "Изображение получено как документ. Что сделать?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✨ Оживить фото", callback_data="photo_anim_picker")],
                    [InlineKeyboardButton("🧽 Удалить фон", callback_data="photo_bg_remove"),
                     InlineKeyboardButton("🖼 Заменить фон", callback_data="photo_bg_replace")],
                ])
            )
            return

        extract_fn = globals().get("extract_text_from_document")
        if not callable(extract_fn):
            await update.effective_message.reply_text("Парсер документов не подключен.")
            return

        text, kind = extract_fn(raw, doc.file_name or "file")
        if not (text or "").strip():
            await update.effective_message.reply_text(f"Не удалось извлечь текст из {kind}.")
            return

        goal = (update.message.caption or "").strip() or None
        await update.effective_message.reply_text(f"📄 Извлекаю текст ({kind}), готовлю конспект…")
        summary = await globals()["summarize_long_text"](text, query=goal)  # type: ignore[index]
        summary = summary or "Готово."
        await update.effective_message.reply_text(summary)
        tts_fn = globals().get("maybe_tts_reply")
        if callable(tts_fn):
            await tts_fn(update, context, summary[: int(globals().get("TTS_MAX_CHARS", 400))])
    except Exception as e:
        log.exception("on_doc error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Ошибка при обработке документа.")

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.voice:
            return
        vf = await update.message.voice.get_file()
        bio = BytesIO(await vf.download_as_bytearray())
        bio.seek(0)
        setattr(bio, "name", f"voice.ogg")
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        text = await globals()["transcribe_audio"](bio, "voice.ogg")  # type: ignore[index]
        if not text:
            await update.effective_message.reply_text("Не удалось распознать речь.")
            return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_voice error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Ошибка при обработке voice.")

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
        text = await globals()["transcribe_audio"](bio, filename)  # type: ignore[index]
        if not text:
            await update.effective_message.reply_text("Не удалось распознать речь из аудио.")
            return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_audio error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Ошибка при обработке аудио.")


# ==== РЕЖИМЫ и КНОПКИ ========================================================
def mode_keyboard(mode: str) -> InlineKeyboardMarkup:
    if mode == "work":
        rows = [
            [InlineKeyboardButton("📄 Письмо/документ", callback_data="work_doc"),
             InlineKeyboardButton("📊 Аналитика/сводка", callback_data="work_report")],
            [InlineKeyboardButton("📝 План/ToDo", callback_data="work_plan"),
             InlineKeyboardButton("💡 Идеи/бриф", callback_data="work_brief")],
            [InlineKeyboardButton("🎬 Runway", callback_data="engine_runway"),
             InlineKeyboardButton("🎥 Luma", callback_data="engine_luma")],
            [InlineKeyboardButton("↩️ Назад", callback_data="back_home")]
        ]
    elif mode == "study":
        rows = [
            [InlineKeyboardButton("📚 Объяснить тему", callback_data="study_explain"),
             InlineKeyboardButton("🧪 Подготовка к тесту", callback_data="study_quiz")],
            [InlineKeyboardButton("📝 Конспект PDF/скрин", callback_data="study_notes")],
            [InlineKeyboardButton("↩️ Назад", callback_data="back_home")]
        ]
    else:  # fun
        rows = [
            [InlineKeyboardButton("🎨 Midjourney (описание)", callback_data="fun_mj")],
            [InlineKeyboardButton("🎬 Runway", callback_data="engine_runway"),
             InlineKeyboardButton("🎥 Luma", callback_data="engine_luma")],
            [InlineKeyboardButton("↩️ Назад", callback_data="back_home")]
        ]
    return InlineKeyboardMarkup(rows)

async def open_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    context.user_data["mode"] = mode
    text = {
        "work":  "💼 Режим «Работа». Напиши задачу или выбери опцию ниже.",
        "study": "🎓 Режим «Учёба». Напиши тему/задачу или выбери опцию.",
        "fun":   "🔥 Режим «Развлечения». Можно сделать визуалы/видео и т.д."
    }[mode]
    await update.effective_chat.send_message(text, reply_markup=mode_keyboard(mode))

async def on_mode_school_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "🎓 *Учёба*\n"
        "Помогу: конспекты из PDF/EPUB/DOCX/TXT, разбор задач пошагово, эссе/рефераты, мини-квизы.\n\n"
        "_Быстрые действия:_\n"
        "• Разобрать PDF → конспект\n"
        "• Сократить в шпаргалку\n"
        "• Объяснить тему с примерами\n"
        "• План ответа / презентации"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown")

async def on_mode_work_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "💼 *Работа*\n"
        "Письма/брифы/резюме/аналитика, ToDo/планы, сводные таблицы из документов.\n"
        "Для архитектора/дизайнера/проектировщика — структурирование ТЗ, чек-листы стадий, "
        "сводные таблицы листов, пояснительные записки.\n\n"
        "_Гибриды:_ GPT-5 (текст/логика) + Images (иллюстрации) + Luma/Runway (клипы/мокапы).\n\n"
        "_Быстрые действия:_\n"
        "• Сформировать бриф/ТЗ\n"
        "• Свести требования в таблицу\n"
        "• Сгенерировать письмо/резюме\n"
        "• Черновик презентации"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown")

async def on_mode_fun_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "🔥 *Развлечения*\n"
        "Фото-мастерская: удалить/заменить фон, добавить/убрать объект/человека, outpaint, "
        "*оживление старых фото*.\n"
        "Видео: Luma/Runway — клипы под Reels/Shorts; *Reels по смыслу из цельного видео* "
        "(умная нарезка), авто-таймкоды. Мемы/квизы.\n\n"
        "Выбери действие ниже:"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown", reply_markup=_fun_quick_kb())

def _fun_quick_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🎭 Идеи для досуга", callback_data="fun:ideas")],
        [InlineKeyboardButton("🎬 Сценарий шорта", callback_data="fun:storyboard")],
        [InlineKeyboardButton("🎮 Игры/квиз",       callback_data="fun:quiz")],
        [
            InlineKeyboardButton("🪄 Оживить старое фото", callback_data="fun:revive"),
            InlineKeyboardButton("🎬 Reels из длинного видео", callback_data="fun:smartreels"),
        ],
        [
            InlineKeyboardButton("🎥 Runway",      callback_data="fun:clip"),
            InlineKeyboardButton("🎨 Midjourney",  callback_data="fun:img"),
            InlineKeyboardButton("🔊 STT/TTS",     callback_data="fun:speech"),
        ],
        [InlineKeyboardButton("📝 Свободный запрос", callback_data="fun:free")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="fun:back")],
    ]
    return InlineKeyboardMarkup(rows)

async def on_cb_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()
    action = data.split(":", 1)[1] if ":" in data else ""

    async def _try_call(*fn_names, **kwargs):
        fn = _pick_first_defined(*fn_names)
        if callable(fn):
            return await fn(update, context, **kwargs)
        return None

    if action == "revive":
        if await _try_call("revive_old_photo_flow", "do_revive_photo"):
            return
        await q.answer("Оживление фото")
        await q.edit_message_text(
            "🪄 *Оживление старого фото*\n"
            "Пришли/перешли сюда фото и коротко опиши, что нужно оживить "
            "(мигание глаз, лёгкая улыбка, движение фона и т.п.). "
            "Я подготовлю анимацию и верну превью/видео.",
            parse_mode="Markdown",
            reply_markup=_fun_quick_kb()
        )
        return

    if action == "smartreels":
        if await _try_call("smart_reels_from_video", "video_sense_reels"):
            return
        await q.answer("Reels из длинного видео")
        await q.edit_message_text(
            "🎬 *Reels из длинного видео*\n"
            "Пришли длинное видео (или ссылку) + тему/ЦА. "
            "Сделаю умную нарезку (hook → value → CTA), субтитры и таймкоды. "
            "Скажи формат: 9:16 или 1:1.",
            parse_mode="Markdown",
            reply_markup=_fun_quick_kb()
        )
        return

    if action == "clip":
        if await _try_call("start_runway_flow", "luma_make_clip", "runway_make_clip"):
            return
        await q.answer()
        await q.edit_message_text("Запусти /diag_video чтобы проверить ключи Luma/Runway.", reply_markup=_fun_quick_kb())
        return

    if action == "img":
        if await _try_call("cmd_img", "midjourney_flow", "images_make"):
            return
        await q.answer()
        await q.edit_message_text("Введи /img и тему картинки, или пришли рефы.", reply_markup=_fun_quick_kb())
        return

    if action == "storyboard":
        if await _try_call("start_storyboard", "storyboard_make"):
            return
        await q.answer()
        await q.edit_message_text("Напиши тему шорта — накидаю структуру и раскадровку.", reply_markup=_fun_quick_kb())
        return

    if action in {"ideas", "quiz", "speech", "free", "back"}:
        await q.answer()
        await q.edit_message_text(
            "Готов! Напиши задачу или выбери кнопку выше.",
            reply_markup=_fun_quick_kb()
        )
        return

    await q.answer()


# ==== КНОПКИ-ЯРЛЫКИ ==========================================================
async def on_btn_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fn = globals().get("cmd_engines")
    if callable(fn):
        return await fn(update, context)
    return await update.effective_message.reply_text("Движки: Runway, Luma, Images…")

async def on_btn_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fn = globals().get("cmd_balance")
    if callable(fn):
        return await fn(update, context)
    return await update.effective_message.reply_text("Баланс недоступен.")

async def on_btn_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_plans(update, context)

async def on_btn_study(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # сначала пробуем единое меню режимов, далее фоллбек на текст
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


# ==== Позитивный авто-ответ про возможности ==================================
_CAPS_PATTERN = (
    r"(?is)(умеешь|можешь|делаешь|анализируешь|работаешь|поддерживаешь|умеет ли|может ли)"
    r".{0,120}"
    r"(pdf|epub|fb2|docx|txt|книг|книга|изображен|фото|картин|image|jpeg|png|video|видео|mp4|mov|аудио|audio|mp3|wav)"
)

async def on_capabilities_qa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Да, умею работать с файлами и медиа:\n"
        "• 📄 Документы: PDF/EPUB/FB2/DOCX/TXT — конспект, резюме, извлечение таблиц, проверка фактов.\n"
        "• 🖼 Изображения: анализ/описание, улучшение, фон, разметка, мемы, outpaint.\n"
        "• 🎞 Видео: разбор смысла, таймкоды, *Reels из длинного видео*, идеи/скрипт, субтитры.\n"
        "• 🎧 Аудио/книги: транскрипция, тезисы, план.\n\n"
        "_Подсказки:_ просто загрузите файл или пришлите ссылку + короткое ТЗ. "
        "Для фото — можно нажать «🪄 Оживить старое фото», для видео — «🎬 Reels из длинного видео»."
    )
    await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=_fun_quick_kb())


# ==== ЕДИНЫЙ CallbackQuery РОУТЕР (без дублей) ================================
async def cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()
    await q.answer()

    # 0) Режимы
    if data in ("mode_work", "mode_study", "mode_fun"):
        mode = data.split("_", 1)[1]
        # Пытаемся открыть полноценный экран режима, иначе — показать локальное меню
        open_mode_fn = globals().get("open_mode")
        send_mode_menu_fn = globals().get("_send_mode_menu")
        if callable(open_mode_fn):
            return await open_mode_fn(update, context, mode)
        if callable(send_mode_menu_fn):
            return await send_mode_menu_fn(update, context, mode)
        return await q.message.reply_text("Выбери режим ниже…")

    # 0.1) Движки
    if data == "engine_runway":
        fn = globals().get("show_engine_confirm")
        if callable(fn):
            return await fn(update, context, "runway")
        return await q.message.reply_text("Модуль подтверждения Runway не подключён.")
    if data == "engine_luma":
        fn = globals().get("show_engine_confirm")
        if callable(fn):
            return await fn(update, context, "luma")
        return await q.message.reply_text("Модуль подтверждения Luma не подключён.")

    if data == "back_home":
        context.user_data.pop("mode", None)
        return await update.effective_chat.send_message("Выбери режим ниже…")

    # 1) Оплата: подписки
    if data.startswith("buy:"):
        # buy:<tier>:<months>
        try:
            _, tier, months_s = data.split(":", 2)
            months = int(months_s)
            payload, amount, title = _plan_payload_and_amount(tier, months)
            ok = await _send_invoice_rub(
                title, f"Оплата тарифа {tier.upper()} на {months} мес.", amount, payload, update
            )
            if not ok:
                await q.message.reply_text("Не удалось выставить счёт по тарифу.")
        except Exception as e:
            log.exception("buy parse error: %s", e)
            await q.message.reply_text("Некорректные параметры покупки.")
        return

    # 2) Пополнения
    if data == "topup":
        return await _send_topup_menu(update, context)

    if data.startswith("topup:rub:"):
        try:
            rub = int(data.split(":", 2)[-1])
            await _send_invoice_rub(
                "Пополнение баланса", "Единый баланс (RUB→USD)", rub, f"topup:rub:{rub}", update
            )
        except Exception:
            await q.message.reply_text("Некорректная сумма пополнения.")
        return

    if data.startswith("topup:crypto:"):
        try:
            usd = float(data.split(":", 2)[-1])
        except Exception:
            usd = 5.0
        inv_id, pay_url, amt, asset = await _crypto_create_invoice(
            usd, asset="USDT", description="Top-up"
        )
        if not inv_id or not pay_url:
            return await q.message.reply_text("Не удалось создать CryptoBot-инвойс.")
        msg = await q.message.reply_text(
            f"💠 CryptoBot: {asset} ${amt:.2f}\nОплатить: {pay_url}\n\nПосле оплаты я проверю статус автоматически."
        )
        # стартуем опрос
        context.application.create_task(
            _poll_crypto_invoice(
                context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id, amt
            )
        )
        return

    # 3) Фото-меню
    if data == "photo_anim_picker":
        return await show_photo_animate_picker(update.effective_chat.id, context)

    if data == "photo_anim_runway":
        img = context.user_data.get("last_photo_bytes")
        if not img:
            return await q.message.reply_text("Фото не найдено. Пришлите фото ещё раз.")
        async def _go():
            fn = _pick_first_defined("_run_runway_animate_photo", "runway_animate_photo")
            if callable(fn):
                await fn(update, context, img, "", 5, "9:16")
            else:
                await q.message.reply_text("Пайплайн Runway для оживления фото не подключён.")
        RUNWAY_UNIT = float(globals().get("RUNWAY_UNIT_COST_USD", 1.0))
        RUNWAY_TIME = max(1, int(globals().get("RUNWAY_DURATION_S", 5)))
        est_cost = max(1.0, RUNWAY_UNIT * (5 / RUNWAY_TIME))
        await _try_pay_then_do(update, context, update.effective_user.id, "runway", est_cost, _go)
        return

    if data == "photo_bg_remove":
        img = context.user_data.get("last_photo_bytes")
        fn = _pick_first_defined("_pedit_removebg", "remove_bg")
        return await (fn(update, context, img) if callable(fn) and img else q.message.reply_text("Нет фото или нет функции."))

    if data == "photo_bg_replace":
        img = context.user_data.get("last_photo_bytes")
        fn = _pick_first_defined("_pedit_replacebg", "replace_bg")
        return await (fn(update, context, img) if callable(fn) and img else q.message.reply_text("Нет фото или нет функции."))

    if data == "photo_outpaint":
        img = context.user_data.get("last_photo_bytes")
        fn = _pick_first_defined("_pedit_outpaint", "outpaint")
        return await (fn(update, context, img) if callable(fn) and img else q.message.reply_text("Нет фото или нет функции."))

    if data == "photo_storyboard":
        img = context.user_data.get("last_photo_bytes")
        fn = _pick_first_defined("_pedit_storyboard", "storyboard_make")
        return await (fn(update, context, img) if callable(fn) and img else q.message.reply_text("Нет фото или нет функции."))

    if data == "img_luma":
        fn = _pick_first_defined("_start_luma_img", "start_luma_img", "cmd_img")
        if callable(fn):
            return await fn(update, context)
        return await q.message.reply_text("Введи /img и тему картинки, или пришли рефы.")

    if data == "img_analyze":
        fn = _pick_first_defined("analyze_image", "img_analyze")
        if callable(fn):
            return await fn(update, context)
        return await q.message.reply_text("Анализ фото не подключён.")

    # 4) t2v
    if data.startswith("v_runway::"):
        prompt = data.split("::", 1)[1]
        try:
            fn = globals().get("runway_text2video")
            if not callable(fn):
                return await q.message.reply_text("Runway t2v не подключён.")
            info = await fn(prompt, 5, "16:9")
            url = (
                (info.get("assets") or {}).get("video")
                or (info.get("output") or {}).get("video")
                or (info.get("result") or {}).get("video")
            )
            return await q.message.reply_text(f"Готово! Видео (Runway): {url or 'нет ссылки в payload'}")
        except Exception as e:
            return await q.message.reply_text(f"⚠️ Runway: {e}")

    if data.startswith("v_luma::"):
        prompt = data.split("::", 1)[1]
        try:
            fn = globals().get("luma_text2video")
            if not callable(fn):
                return await q.message.reply_text("Luma t2v не подключён.")
            info = await fn(prompt, 5, "16:9")
            url = (
                (info.get("assets") or {}).get("video")
                or (info.get("output") or {}).get("video_url")
            )
            return await q.message.reply_text(f"Готово! Видео (Luma): {url or 'нет ссылки в payload'}")
        except Exception as e:
            return await q.message.reply_text(f"⚠️ Luma: {e}")

    # совместимость: прочие неизвестные колбэки
    return await q.message.reply_text("Ок.")


# ==== ОШИБКИ ==================================================================
async def on_error(update: object, context_: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error: %s", context_.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("Упс, произошла ошибка. Я уже разбираюсь.")
    except Exception:
        pass


# ==== /t2v ТЕСТ КОМАНДА =======================================================
async def t2v_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args) or "retro car driving at night, neon lights"
    try:
        fn = globals().get("runway_text2video")
        if not callable(fn):
            return await update.message.reply_text("Runway t2v не подключён.")  # type: ignore[union-attr]
        info = await fn(prompt, duration_s=5, aspect_ratio="16:9")
        video_url = (
            (info.get("assets") or {}).get("video")
            or (info.get("output") or {}).get("video")
            or (info.get("result") or {}).get("video")
        )
        if video_url:
            await update.message.reply_video(video_url)  # type: ignore[union-attr]
        else:
            await update.message.reply_text(  # type: ignore[union-attr]
                "Runway OK, но не нашёл ссылку в payload:\n" + json.dumps(info, ensure_ascii=False)[:2000]
            )
    except Exception as e:
        await update.message.reply_text(f"Runway error: {e}")  # type: ignore[union-attr]


# ==== СБОРКА APPLICATION (без дублей) =========================================
def build_application() -> "Application":
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в переменных окружения.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды (регистрируем только существующие функции)
    def _maybe_cmd(name: str, fn_name: str):
        fn = globals().get(fn_name)
        if callable(fn):
            app.add_handler(CommandHandler(name, fn))

    for cmd, fn in [
        ("start", "cmd_start"),
        ("help", "cmd_help"),
        ("examples", "cmd_examples"),
        ("engines", "cmd_engines"),
        ("plans", "cmd_plans"),
        ("balance", "cmd_balance"),
        ("set_welcome", "cmd_set_welcome"),
        ("show_welcome", "cmd_show_welcome"),
        ("diag_limits", "cmd_diag_limits"),
        ("diag_stt", "cmd_diag_stt"),
        ("diag_images", "cmd_diag_images"),
        ("diag_video", "cmd_diag_video"),
        ("img", "cmd_img"),
        ("voice_on", "cmd_voice_on"),
        ("voice_off", "cmd_voice_off"),
        ("t2v", "t2v_cmd"),
    ]:
        _maybe_cmd(cmd, fn)

    # Платежи — добавляем обработчики только если функции объявлены
    with contextlib.suppress(Exception):
        if callable(globals().get("on_precheckout")):
            app.add_handler(PreCheckoutQueryHandler(globals()["on_precheckout"]))  # type: ignore[index]
        if callable(globals().get("on_successful_payment")):
            app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, globals()["on_successful_payment"]))  # type: ignore[index]

    # WebApp data
    with contextlib.suppress(Exception):
        if callable(globals().get("on_webapp_data")):
            app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, globals()["on_webapp_data"]))  # type: ignore[index]
        elif hasattr(filters, "WEB_APP_DATA") and callable(globals().get("on_webapp_data")):
            app.add_handler(MessageHandler(filters.WEB_APP_DATA, globals()["on_webapp_data"]))  # type: ignore[index]

    # CallbackQuery: сначала узкие, затем catch-all
    with contextlib.suppress(Exception):
        if callable(globals().get("on_cb_fun")):
            app.add_handler(CallbackQueryHandler(globals()["on_cb_fun"], pattern=r"^fun:[a-z_]+$"))  # type: ignore[index]
    app.add_handler(CallbackQueryHandler(cb_router))  # единый роутер

    # Голос/аудио
    with contextlib.suppress(Exception):
        if callable(globals().get("on_voice")):
            app.add_handler(MessageHandler(filters.VOICE, globals()["on_voice"]))  # type: ignore[index]
        if callable(globals().get("on_audio")):
            app.add_handler(MessageHandler(filters.AUDIO, globals()["on_audio"]))  # type: ignore[index]

    # Текстовые ярлыки (ставим ДО общего текста)
    app.add_handler(MessageHandler(filters.Regex(r"^(?:🧠\s*)?Движки$"), on_btn_engines))
    app.add_handler(MessageHandler(filters.Regex(r"^(?:💳|🧾)?\s*Баланс$"), on_btn_balance))
    app.add_handler(MessageHandler(filters.Regex(r"^(?:⭐️?\s*)?Подписка(?:\s*[·•]\s*Помощь)?$"), on_btn_plans))
    app.add_handler(MessageHandler(filters.Regex(r"^(?:🎓\s*)?Уч[её]ба$"),     on_btn_study))
    app.add_handler(MessageHandler(filters.Regex(r"^(?:💼\s*)?Работа$"),      on_btn_work))
    app.add_handler(MessageHandler(filters.Regex(r"^(?:🔥\s*)?Развлечения$"), on_btn_fun))

    # Позитивный авто-ответ на «а умеешь ли…»
    app.add_handler(MessageHandler(filters.Regex(_CAPS_PATTERN), on_capabilities_qa))

    # Медиа
    with contextlib.suppress(Exception):
        if callable(globals().get("on_photo")):
            app.add_handler(MessageHandler(filters.PHOTO, globals()["on_photo"]))  # type: ignore[index]
        if callable(globals().get("on_doc")):
            app.add_handler(MessageHandler(filters.Document.ALL, globals()["on_doc"]))  # type: ignore[index]

    # видео/гифы — если нужны, добавьте свои обработчики

    # Общий текст — в самом конце
    with contextlib.suppress(Exception):
        if callable(globals().get("on_text")):
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, globals()["on_text"]))  # type: ignore[index]

    # Ошибки
    app.add_error_handler(on_error)

    return app


# ==== main() ==================================================================
def _ensure_event_loop():
    """
    Python 3.12: asyncio.get_event_loop() требует уже установленный loop.
    На воркерах Render его нет — создаём и устанавливаем вручную.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

def main():
    # Инициализация БД/таблиц — не падаем, если модулей нет
    with contextlib.suppress(Exception):
        db_init()  # type: ignore[name-defined]
    with contextlib.suppress(Exception):
        db_init_usage()  # type: ignore[name-defined]
    with contextlib.suppress(Exception):
        _db_init_prefs()  # type: ignore[name-defined]

    app = build_application()

    USE_WEBHOOK    = bool(int(os.environ.get("USE_WEBHOOK", "0")))
    PUBLIC_URL     = os.environ.get("PUBLIC_URL", "")
    WEBHOOK_PATH   = os.environ.get("WEBHOOK_PATH", "/webhook")
    WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
    PORT           = int(os.environ.get("PORT", "8080"))

    if USE_WEBHOOK and PUBLIC_URL:
        log.info("🚀 WEBHOOK mode. Public URL: %s  Path: %s  Port: %s", PUBLIC_URL, WEBHOOK_PATH, PORT)

        # На всякий случай обеспечим наличие event loop и в webhook-режиме
        _ensure_event_loop()

        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH.lstrip("/"),
            webhook_url=f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}",
            secret_token=(WEBHOOK_SECRET or None),
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        log.info("🚀 POLLING mode.")

        # ВАЖНО: не дергаем asyncio.run(delete_webhook(...)) — это создаёт/закрывает отдельный loop
        # и ломает дальнейший запуск. Дадим PTB самому всё сделать через drop_pending_updates.
        _ensure_event_loop()

        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,   # PTB сам удалит webhook и очистит очередь
            # close_loop оставляем по умолчанию (True), чтобы PTB корректно управлял циклом
        )


if __name__ == "__main__":
    main()
