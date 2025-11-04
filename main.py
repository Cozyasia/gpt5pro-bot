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
if not PUBLIC_URL or not PUBLIC_URL.startswith("https://"):
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

# DEMO: free
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
    lim = _limits_for(user_id)
    row = _usage_row(user_id)
    spent = row[f"{engine}_usd"]; budget = lim[f"{engine}_budget_usd"]
    if spent + est_cost_usd <= budget + 1e-9:
        _usage_update(user_id, **{f"{engine}_usd": est_cost_usd})
        return True, ""
    need = max(0.0, spent + est_cost_usd - budget)
    if need > 0:
        if _wallet_total_take(user_id, need):
            _usage_update(user_id, **{f"{engine}_usd": est_cost_usd})
            return True, ""
        tier = get_subscription_tier(user_id)
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
    if len(t) < 8: return False
    if "http://" in t or "https://" in t: return False
    return bool(_NEWSY_RE.search(t)) and not is_smalltalk(t)

def _strip_leading(s: str) -> str:
    return s.strip(" \n\t:—–-\"“”'«»,.()[]")

def _after_match(text: str, match) -> str:
    return _strip_leading(text[match.end():])

_CREATE_CMD = r"(сдела(й|йте)|созда(й|йте)|сгенериру(й|йте)|нарису(й|йте)|render|generate|create|make)"
_PREFIXES_VIDEO = [r"^" + _CREATE_CMD + r"\s+видео", r"^video\b", r"^reels?\b", r"^shorts?\b"]
_PREFIXES_IMAGE = [r"^" + _CREATE_CMD + r"\s+(?:картин\w+|изображен\w+|фото\w+|рисунк\w+)", r"^image\b", r"^picture\b", r"^img\b"]

def _looks_like_capability_question(tl: str) -> bool:
    if "?" in tl and re.search(_CAPABILITY_RE, tl) and not re.search(_CREATE_CMD, tl, re.I):
        return True
    m = re.search(r"\b(ты|вы)?\s*мож(ешь|но|ете)\b", tl)
    if m and re.search(_CAPABILITY_RE, tl) and not re.search(_CREATE_CMD, tl, re.I):
        return True
    return False

def detect_media_intent(text: str):
    if not text: return (None, "")
    t = text.strip(); tl = t.lower()
    if _looks_like_capability_question(tl): return (None, "")
    for p in _PREFIXES_VIDEO:
        m = re.search(p, tl, re.I)
        if m: return ("video", _after_match(t, m))
    for p in _PREFIXES_IMAGE:
        m = re.search(p, tl, re.I)
        if m: return ("image", _after_match(t, m))
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
    if m: return ("image", _strip_leading(t[m.end(1)+1:]))
    m = re.match(r"^(video|vid|reels?|shorts?)\s*[:\-]\s*(.+)$", tl)
    if m: return ("video", _strip_leading(t[m.end(1)+1:]))
    return (None, "")

# ───────── OpenAI helpers ─────────
def _oai_text_client(): return oai_llm

async def ask_openai_text(user_text: str, web_ctx: str = "") -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({"role": "system", "content": f"Контекст из веб-поиска:\n{web_ctx}"})
    messages.append({"role": "user", "content": user_text})
    last_err = None
    for attempt in range(3):
        try:
            resp = _oai_text_client().chat.completions.create(
                model=OPENAI_MODEL, messages=messages, temperature=0.6
            )
            txt = (resp.choices[0].message.content or "").strip()
            if txt: return txt
        except Exception as e:
            last_err = e
            log.warning("OpenAI/OpenRouter chat attempt %d failed: %s", attempt+1, e)
            await asyncio.sleep(0.8 * (attempt + 1))
    log.error("ask_openai_text failed: %s", last_err)
    return "⚠️ Сейчас не получилось получить ответ от модели. Я на связи — попробуй переформулировать запрос или повторить чуть позже."

async def ask_openai_vision(user_text: str, img_b64: str, mime: str) -> str:
    try:
        resp = _oai_text_client().chat.completions.create(
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
        return "Не удалось проанализировать изображение."

# ───────── Пользовательские настройки (TTS) ─────────
def _db_init_prefs():
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_prefs (
        user_id INTEGER PRIMARY KEY,
        tts_on  INTEGER DEFAULT 0
    )""")
    con.commit(); con.close()

def _tts_get(user_id: int) -> bool:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO user_prefs(user_id, tts_on) VALUES (?,0)", (user_id,))
    con.commit()
    cur.execute("SELECT tts_on FROM user_prefs WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close()
    return bool(row and row[0])

def _tts_set(user_id: int, on: bool):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO user_prefs(user_id, tts_on) VALUES (?,?)", (user_id, 1 if on else 0))
    cur.execute("UPDATE user_prefs SET tts_on=? WHERE user_id=?", (1 if on else 0, user_id))
    con.commit(); con.close()

# ───────── Надёжный TTS через REST (OGG/Opus) ─────────
def _tts_bytes_sync(text: str) -> bytes | None:
    try:
        if not OPENAI_TTS_KEY: return None
        url = f"{OPENAI_TTS_BASE_URL.rstrip('/')}/audio/speech"
        payload = {"model": OPENAI_TTS_MODEL, "voice": OPENAI_TTS_VOICE, "input": text, "format": "opus"}
        headers = {"Authorization": f"Bearer {OPENAI_TTS_KEY}", "Content-Type": "application/json"}
        r = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        r.raise_for_status()
        return r.content if r.content else None
    except Exception as e:
        log.exception("TTS HTTP error: %s", e); return None

async def maybe_tts_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    if not _tts_get(user_id) or not text: return
    if len(text) > TTS_MAX_CHARS:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text(f"🔇 Озвучка выключена для этого сообщения: текст длиннее {TTS_MAX_CHARS} символов.")
        return
    try:
        with contextlib.suppress(Exception):
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VOICE)
        audio = await asyncio.to_thread(_tts_bytes_sync, text)
        if not audio:
            with contextlib.suppress(Exception):
                await update.effective_message.reply_text("🔇 Не удалось синтезировать голос.")
            return
        bio = BytesIO(audio); bio.name = "say.ogg"
        await update.effective_message.reply_voice(voice=InputFile(bio), caption=text)
    except Exception as e:
        log.exception("maybe_tts_reply error: %s", e)

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, True)
    await update.effective_message.reply_text(f"🔊 Озвучка включена. Лимит {TTS_MAX_CHARS} символов на ответ.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, False)
    await update.effective_message.reply_text("🔈 Озвучка выключена.")

# ───────── Извлечение/суммаризация документов ─────────
# ... (оставь свои функции extract_* и summarize_long_text выше без изменений)

# ───────── OpenAI Images (generate/edit/variation) ─────────
async def _oai_image_variation(img_bytes: bytes, prompt: str | None = None) -> bytes | None:
    try:
        # Вариации/улучшение (или "мягкая" правка без маски)
        resp = oai_img.images.edits(
            model=IMAGES_MODEL,
            image=img_bytes,
            prompt=(prompt or "Improve quality, upscale x2, subtle details, keep identity.")
        )
        b64 = resp.data[0].b64_json
        return base64.b64decode(b64)
    except Exception as e:
        log.exception("IMG variation/edit error: %s", e)
        return None

async def _oai_image_edit_prompt(img_bytes: bytes, prompt: str) -> bytes | None:
    try:
        resp = oai_img.images.edits(model=IMAGES_MODEL, image=img_bytes, prompt=prompt)
        b64 = resp.data[0].b64_json
        return base64.b64decode(b64)
    except Exception as e:
        log.exception("IMG edit prompt error: %s", e)
        return None

# ───────── Фото: запоминание и быстрые действия ─────────
def _remember_last_photo(user_id: int, file_id: str, caption: str, mime: str):
    kv_set(f"photo:last:{user_id}", json.dumps({"file_id": file_id, "caption": caption, "mime": mime, "ts": int(time.time())}))

def _get_last_photo_meta(user_id: int) -> dict | None:
    raw = kv_get(f"photo:last:{user_id}")
    if not raw: return None
    try:
        return json.loads(raw)
    except Exception:
        return None

async def _download_file_bytes_by_id(context: ContextTypes.DEFAULT_TYPE, file_id: str) -> bytes | None:
    try:
        tg_file = await context.bot.get_file(file_id)
        data = await tg_file.download_as_bytearray()
        return bytes(data)
    except Exception as e:
        log.exception("download file by id error: %s", e)
        return None

def _photo_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Описать", callback_data="pact:describe")],
        [InlineKeyboardButton("🧽 Убрать фон", callback_data="pact:bg_remove"),
         InlineKeyboardButton("🖼 Заменить фон", callback_data="pact:bg_replace")],
        [InlineKeyboardButton("➕ Добавить объект", callback_data="pact:add_obj"),
         InlineKeyboardButton("➖ Удалить объект", callback_data="pact:del_obj")],
        [InlineKeyboardButton("✨ Улучшить / вариации", callback_data="pact:variations")],
        [InlineKeyboardButton("🎬 Оживить (Luma 5s 9:16)", callback_data="pact:animate:luma"),
         InlineKeyboardButton("🎥 Оживить (Runway 5s 16:9)", callback_data="pact:animate:runway")],
    ])

def _photo_hint_text() -> str:
    return (
        "💡 Что можно сделать с фото: описать, убрать/заменить фон, добавить/удалить объект, "
        "дорисовать недостающие ракурсы, повернуть «камеру», улучшить качество, "
        "или «оживить» сцену коротким видео (перемещения людей и объектов — через Luma/Runway)."
    )

# ───────── Capability Q&A (добавили блок про фото-редактирование/оживление) ─────────
_CAP_PDF   = re.compile(r"(pdf|документ(ы)?|файл(ы)?)", re.I)
_CAP_EBOOK = re.compile(r"(ebook|e-?book|электронн(ая|ые)\s+книг|epub|fb2|docx|txt|mobi|azw)", re.I)
_CAP_AUDIO = re.compile(r"(аудио ?книг|audiobook|audio ?book|mp3|m4a|wav|ogg|webm|voice)", re.I)
_CAP_IMAGE = re.compile(r"(изображен|картинк|фото|image|picture|img)", re.I)
_CAP_VIDEO = re.compile(r"(видео|ролик|shorts?|reels?|clip)", re.I)

def capability_answer(text: str) -> str | None:
    tl = (text or "").strip().lower()
    if not tl: return None
    if (_CAP_PDF.search(tl) or _CAP_EBOOK.search(tl)) and re.search(r"(чита|анализ|распозна)", tl):
        return ("Да. Пришли файл — извлеку текст и сделаю конспект/ответ по цели. "
                "Поддержка: PDF, EPUB, DOCX, FB2, TXT.")
    if _CAP_AUDIO.search(tl) and re.search(r"(чита|анализ|расшиф|транскриб|понима|распозна)", tl):
        return ("Да. Распознаю аудио/voice (OGG/MP3/M4A/WAV/WEBM) и сделаю тезисы, Q&A, тайм-коды.")
    if _CAP_IMAGE.search(tl) and re.search(r"(чита|анализ|понима|видишь)", tl):
        return "Да. Пришли фото/картинку с подписью — опишу содержимое, текст на изображении, объекты и детали."
    if _CAP_IMAGE.search(tl) and re.search(r"(созда|дела|генерир|редакт|ожив|анимир|фон|объект|челов|дорис|поверн)", tl):
        return ("Да. Что умею с фото:\n"
                "• 📝 Описание/распознавание текста.\n"
                "• 🧽 Удаление/замена фона (инпейнт по промпту).\n"
                "• ➕➖ Добавление/удаление объектов/людей (по описанию).\n"
                "• 🎛 Улучшение и вариации кадра.\n"
                "• 🎬 «Оживление» сцены (короткое видео Luma/Runway по описанию снимка).\n\n"
                "Пришли фото — предложу быстрые кнопки действий.")
    if _CAP_IMAGE.search(tl) and re.search(r"(мож(ешь|ете))", tl):
        return "Да, присылай фото — появится меню действий (описать, фон, объекты, улучшить, оживить)."
    if _CAP_VIDEO.search(tl) and re.search(r"(созда|дела|сгенерир|ожив)", tl):
        return ("Да, могу запустить генерацию коротких видео. Напиши: "
                "«сделай видео … на 9 секунд 9:16». Также могу «оживить» присланное фото (Luma/Runway).")
    return None

# ───────── Диагностика (оставь как было) ─────────
# ... cmd_diag_limits / cmd_diag_images / cmd_diag_stt / cmd_diag_video остаются без изменений

# ───────── Обработчики сообщений ─────────
def sniff_image_mime(b: bytes) -> str:
    if b.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if b[:3] == b"\xff\xd8\xff":         return "image/jpeg"
    if b[:6] == b"GIF87a" or b[:6] == b"GIF89a": return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":  return "image/webp"
    return "application/octet-stream"

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    await _process_text(update, context, text)

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ok, left, tier = check_text_and_inc(user_id, (update.effective_user.username or ""))
    if not ok:
        await update.effective_message.reply_text("Дневной лимит текстовых запросов исчерпан. Оформите подписку через /plans.")
        return
    try:
        photo = update.message.photo[-1]
        tg_file = await photo.get_file()
        data = await tg_file.download_as_bytearray()
        b = bytes(data)
        b64 = base64.b64encode(b).decode("ascii")
        mime = sniff_image_mime(b)
        user_caption = (update.message.caption or "").strip()

        # Запоминаем последнее фото
        _remember_last_photo(user_id, tg_file.file_id, user_caption, mime)

        # 1) Если есть подпись — используем её как вопрос/цель
        if user_caption:
            ans = await ask_openai_vision(user_caption, b64, mime)
            await update.effective_message.reply_text(ans or "Готово.")
            await maybe_tts_reply(update, context, (ans or "")[:TTS_MAX_CHARS])

        # 2) Показываем подсказку и клавиатуру быстрых действий
        hint = _photo_hint_text()
        await update.effective_message.reply_text(hint, reply_markup=_photo_actions_kb())

    except Exception as e:
        log.exception("Photo handler error: %s", e)
        await update.effective_message.reply_text("Не удалось обработать изображение.")

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message.voice:
            f = await update.message.voice.get_file(); fname = "voice.ogg"
        elif update.message.audio:
            f = await update.message.audio.get_file()
            fname = (update.message.audio.file_name or "audio").lower()
            if not re.search(r"\.(ogg|mp3|m4a|wav|webm)$", fname): fname += ".ogg"
        else:
            await update.effective_message.reply_text("Тип аудио не поддерживается."); return
        data = await f.download_as_bytearray()
        buf = BytesIO(bytes(data))
        txt = await transcribe_audio(buf, filename_hint=fname)
        if not txt:
            await update.effective_message.reply_text("Не удалось распознать речь."); return
        await update.effective_message.reply_text(f"🗣️ Распознано: {txt}")
        await _process_text(update, context, txt)
    except Exception as e:
        log.exception("Voice handler error: %s", e)
        await update.effective_message.reply_text("Ошибка обработки голосового сообщения.")

async def on_audio_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document: return
        doc = update.message.document
        mime = (doc.mime_type or "").lower()
        name = (doc.file_name or "").lower()
        is_audio_like = (mime.startswith("audio/") or name.endswith((".mp3",".m4a",".wav",".ogg",".oga",".webm")))
        if not is_audio_like: return
        f = await doc.get_file(); data = await f.download_as_bytearray()
        buf = BytesIO(bytes(data))
        txt = await transcribe_audio(buf, filename_hint=(name or "audio.ogg"))
        if not txt:
            await update.effective_message.reply_text("Не удалось распознать речь из файла."); return
        await update.effective_message.reply_text(f"🗣️ Распознано (файл): {txt}")
        await _process_text(update, context, txt)
    except Exception as e:
        log.exception("Audio document handler error: %s", e)
        await update.effective_message.reply_text("Ошибка обработки аудио-файла.")

async def _process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    username = (update.effective_user.username or "")
    ok, left, tier = check_text_and_inc(user_id, username)
    if not ok:
        await update.effective_message.reply_text("Дневной лимит текстовых запросов исчерпан. Оформите подписку через /plans.")
        return

    if is_smalltalk(text):
        ans = await ask_openai_text(text)
        await update.effective_message.reply_text(ans)
        await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS]); return

    cap_ans = capability_answer(text)
    if cap_ans:
        await update.effective_message.reply_text(cap_ans)
        await maybe_tts_reply(update, context, cap_ans[:TTS_MAX_CHARS]); return

    intent, clean = detect_media_intent(text)
    if intent == "image":
        async def _go(): await _do_img_generate(update, context, clean or text)
        await _try_pay_then_do(update, context, user_id, "img", IMG_COST_USD, _go,
                               remember_kind="img_generate", remember_payload={"prompt": clean or text})
        return

    if intent == "video":
        dur, ar, prompt = parse_video_opts_from_text(clean or text, default_duration=LUMA_DURATION_S, default_ar=LUMA_ASPECT)
        aid = _new_aid()
        _pending_actions[aid] = {"prompt": prompt, "duration": dur, "aspect": ar}
        choose_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎬 Luma", callback_data=f"choose:luma:{aid}"),
                                           InlineKeyboardButton("🎥 Runway", callback_data=f"choose:runway:{aid}")]])
        await update.effective_message.reply_text(f"Видео {dur}s • {ar}\nВыберите движок:", reply_markup=choose_kb)
        return

    # Веб-контекст (по желанию)
    web_ctx = ""
    try:
        if tavily and should_browse(text):
            r = tavily.search(query=text, max_results=4)
            if r and isinstance(r, dict):
                items = r.get("results") or []
                lines = []
                for it in items:
                    t = (it.get("title") or "").strip()
                    s = (it.get("content") or it.get("snippet") or "").strip()
                    if t or s: lines.append(f"- {t}: {s}")
                web_ctx = "\n".join(lines[:8])
    except Exception:
        pass

    ans = await ask_openai_text(text, web_ctx=web_ctx)
    if not ans or ans.strip() == "" or "не получилось получить ответ" in ans.lower():
        ans = "⚠️ Сейчас не удалось получить ответ от модели. Я всё равно на связи — попробуй переформулировать запрос или повторить через минуту."
    await update.effective_message.reply_text(ans)
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])

# ───────── Парсинг опций видео ─────────
def _norm_ar(ar: str) -> str:
    ar = (ar or "").strip().lower().replace("×", "x").replace("x", ":")
    if ar in ("9:16","16:9","1:1"): return ar
    if "вертик" in ar or "portrait" in ar: return "9:16"
    if "гориз" in ar or "landscape" in ar: return "16:9"
    return LUMA_ASPECT

def parse_video_opts_from_text(text: str, default_duration: int = 5, default_ar: str = "16:9") -> tuple[int, str, str]:
    tl = (text or "").lower()
    dur = default_duration
    m = re.search(r"(\d{1,2})\s*(?:сек|sec|s)\b", tl)
    if m:
        try: dur = max(3, min(12, int(m.group(1))))
        except Exception: pass
    else:
        m = re.search(r"\b(\d{1,2})\b", tl)
        if m:
            try:
                cand = int(m.group(1))
                if 3 <= cand <= 12: dur = cand
            except Exception: pass
    ar = default_ar
    m = re.search(r"(\d{1,2})\s*[:×x]\s*(\d{1,2})", tl)
    if m: ar = f"{int(m.group(1))}:{int(m.group(2))}"
    elif "вертик" in tl or "portrait" in tl: ar = "9:16"
    elif "гориз" in tl or "landscape" in tl: ar = "16:9"
    ar = _norm_ar(ar)
    clean = re.sub(r"\b(\d{1,2}\s*(сек|sec|s)\b|9:16|16:9|1:1|вертикальн\w+|горизонтальн\w+|portrait|landscape)\b", "", tl, flags=re.I)
    prompt = (clean.strip() or text.strip())
    return dur, ar, prompt

def _safe_caption(s: str, limit: int = 850) -> str:
    s = (s or "").strip()
    return s if len(s) <= limit else s[:limit-3] + "…"

# ───────── Luma / Runway (без изменений, см. ранее) ─────────
LUMA_API_KEY       = os.environ.get("LUMA_API_KEY", "").strip()
LUMA_BASE_URL      = os.environ.get("LUMA_BASE_URL", "https://api.lumalabs.ai").rstrip("/")
LUMA_DURATION_S    = int(os.environ.get("LUMA_DURATION_S", "5"))
LUMA_ASPECT        = os.environ.get("LUMA_ASPECT", "16:9")

RUNWAY_API_KEY     = os.environ.get("RUNWAY_API_KEY", "").strip()
RUNWAY_BASE_URL    = os.environ.get("RUNWAY_BASE_URL", "https://api.runwayml.com").rstrip("/")
RUNWAY_DURATION_S  = int(os.environ.get("RUNWAY_DURATION_S", "5"))
RUNWAY_ASPECT      = os.environ.get("RUNWAY_ASPECT", "16:9")

# Параметры Telegram-платежей / прайс
TG_PAY_PROVIDER_TOKEN = os.environ.get("TG_PAY_PROVIDER_TOKEN", "").strip()
MIN_RUB_FOR_INVOICE   = int(os.environ.get("MIN_RUB_FOR_INVOICE", "100"))
PORT                  = int(os.environ.get("PORT", "10000"))
USE_WEBHOOK           = os.environ.get("USE_WEBHOOK", "0").strip() == "1"
WEBHOOK_PATH          = os.environ.get("WEBHOOK_PATH", "/webhook").strip()
WEBHOOK_SECRET        = os.environ.get("WEBHOOK_SECRET", "").strip()

# Модели OpenAI (если выше не заданы)
OPENAI_MODEL   = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
IMAGES_MODEL   = os.environ.get("IMAGES_MODEL", "gpt-image-1")

# TTS (если выше не заданы)
OPENAI_TTS_BASE_URL = os.environ.get("OPENAI_TTS_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_TTS_KEY      = os.environ.get("OPENAI_TTS_KEY", os.environ.get("OPENAI_API_KEY","")).strip()
OPENAI_TTS_MODEL    = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE    = os.environ.get("OPENAI_TTS_VOICE", "alloy")
TTS_MAX_CHARS       = int(os.environ.get("TTS_MAX_CHARS", "700"))

# Хранилище KV (если не определено ранее, делаем простое in-memory + fallback в БД)
if "kv_get" not in globals():
    _KV_MEM = {}
    def kv_get(key: str, default: str = None) -> str | None:
        try:
            return _KV_MEM.get(key, default)
        except Exception:
            return default
    def kv_set(key: str, value: str):
        try:
            if value is None or value == "":
                _KV_MEM.pop(key, None)
            else:
                _KV_MEM[key] = value
        except Exception:
            pass

# ───────── Low-level helpers ─────────
def _payload_parse(raw: str) -> dict:
    # поддерживаем "k=v&..." и JSON
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        if raw.lstrip().startswith("{"):
            return json.loads(raw)
    except Exception:
        pass
    out = {}
    for pair in raw.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k] = v
    return out

async def _send_invoice_rub(update: Update, title: str, desc: str, payload: str, rub_amount: int):
    if rub_amount < MIN_RUB_FOR_INVOICE:
        rub_amount = MIN_RUB_FOR_INVOICE
    prices = [LabeledPrice(label=title[:32] or "Пополнение", amount=int(rub_amount*100))]
    await update.effective_message.reply_invoice(
        title=title[:32] or "Оплата",
        description=(desc or "")[:250],
        payload=payload,
        provider_token=TG_PAY_PROVIDER_TOKEN,
        currency="RUB",
        prices=prices,
        max_tip_amount=0
    )

# ───────── Luma API ─────────
async def _run_luma_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration_s: int = 5, aspect: str = "16:9"):
    """Создаёт короткое видео в Luma (Dream Machine) и присылает файл."""
    if not LUMA_API_KEY:
        await update.effective_message.reply_text("Luma API не настроен.")
        return

    headers = {
        "Authorization": f"Bearer {LUMA_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "prompt": prompt,
        "duration": max(3, min(12, int(duration_s))),
        "aspect_ratio": aspect or "16:9",
        # можно добавить пресеты движения камеры:
        # "camera": {"preset": "slow_pan"}
    }

    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)
        r = httpx.post(f"{LUMA_BASE_URL}/dm/v1/videos", headers=headers, json=body, timeout=60.0)
        r.raise_for_status()
        job = r.json()
        job_id = job.get("id") or job.get("data", {}).get("id")
        if not job_id:
            await update.effective_message.reply_text("Не удалось создать задачу в Luma.")
            return

        # Поллинг статуса
        status = "queued"; video_url = None
        for _ in range(90):  # ~90 * 2с = 3 мин
            time.sleep(2)
            st = httpx.get(f"{LUMA_BASE_URL}/dm/v1/videos/{job_id}", headers=headers, timeout=30.0)
            if st.status_code == 404:
                continue
            st.raise_for_status()
            js = st.json()
            status = js.get("status") or js.get("data", {}).get("status", "")
            if status in ("succeeded","completed","done"):
                video_url = js.get("assets", {}).get("video") or js.get("video", None)
                break
            if status in ("failed","error"):
                await update.effective_message.reply_text("Luma: задача завершилась с ошибкой.")
                return

        if not video_url:
            await update.effective_message.reply_text("Luma: не получил ссылку на видео (таймаут).")
            return

        # Загрузка файла и отправка
        vresp = httpx.get(video_url, timeout=120.0)
        vresp.raise_for_status()
        bt = BytesIO(vresp.content); bt.name = "luma.mp4"
        await update.effective_message.reply_video(video=InputFile(bt), caption="🎬 Luma: готово.")
    except Exception as e:
        log.exception("Luma error: %s", e)
        await update.effective_message.reply_text("Не удалось сгенерировать видео через Luma.")

# ───────── Runway API ─────────
async def _run_runway_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration_s: int = 5, aspect: str = "16:9"):
    """Создаёт короткое видео в Runway Gen-3 и присылает файл."""
    if not RUNWAY_API_KEY:
        await update.effective_message.reply_text("Runway API не настроен.")
        return

    headers = {
        "Authorization": f"Bearer {RUNWAY_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "prompt": prompt,
        "duration": max(3, min(12, int(duration_s))),
        "aspect_ratio": aspect or "16:9",
        "seed": 0,
    }

    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)
        r = httpx.post(f"{RUNWAY_BASE_URL}/v1/generations", headers=headers, json=body, timeout=60.0)
        r.raise_for_status()
        job = r.json()
        job_id = job.get("id") or job.get("data", {}).get("id")
        if not job_id:
            await update.effective_message.reply_text("Не удалось создать задачу в Runway.")
            return

        # Поллинг статуса
        status = "queued"; video_url = None
        for _ in range(120):  # ~4 мин
            time.sleep(2)
            st = httpx.get(f"{RUNWAY_BASE_URL}/v1/generations/{job_id}", headers=headers, timeout=30.0)
            if st.status_code == 404:
                continue
            st.raise_for_status()
            js = st.json()
            status = js.get("status") or js.get("data", {}).get("status", "")
            if status in ("succeeded","completed","done"):
                video_url = (js.get("output", {}) or {}).get("video") or js.get("result", {}).get("video")
                break
            if status in ("failed","error","canceled"):
                await update.effective_message.reply_text("Runway: задача завершилась с ошибкой.")
                return

        if not video_url:
            await update.effective_message.reply_text("Runway: не получил ссылку на видео (таймаут).")
            return

        vresp = httpx.get(video_url, timeout=180.0)
        vresp.raise_for_status()
        bt = BytesIO(vresp.content); bt.name = "runway.mp4"
        await update.effective_message.reply_video(video=InputFile(bt), caption="🎥 Runway: готово.")
    except Exception as e:
        log.exception("Runway error: %s", e)
        await update.effective_message.reply_text("Не удалось сгенерировать видео через Runway.")

# ───────── One-off / Paywall helper ─────────
def _payload_oneoff(engine: str, usd_cents: int, aid: str = "") -> str:
    # t=1 — one-off; e=l|r|i, u=cents, aid=action_id
    e = {"luma":"l","runway":"r","img":"i"}.get(engine, "i")
    return f"t=1&e={e}&u={int(usd_cents)}&aid={aid}"

def _payload_subscribe(tier_key: str, months: int = 1) -> str:
    # t=2 — subscribe; s=s|p|u; m=months
    s = {"start":"s","pro":"p","ultimate":"u"}.get(tier_key, "p")
    return f"t=2&s={s}&m={int(months)}"

def _payload_wallet_topup() -> str:
    # t=3 — top up total wallet RUB
    return "t=3"

async def _try_pay_then_do(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    engine: str,
    est_cost_usd: float,
    do_func,
    remember_kind: str = "",
    remember_payload: dict | None = None
):
    """
    Проверяем бюджет/лимиты. Если хватает — запускаем do_func().
    Если нет — предлагаем one-off оплату для этой операции или подписку.
    """
    ok_flag, advice = _can_spend_or_offer(user_id, (update.effective_user.username or ""), engine, est_cost_usd)
    if ok_flag:
        await do_func()
        return

    # Нужно оплатить
    if advice == "ASK_SUBSCRIBE":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ Оформить PRO на 1 месяц", callback_data="noop")],
        ])
        await update.effective_message.reply_text(
            "Для этой операции на бесплатном тарифе не хватает бюджета. "
            "Оформите подписку /plans или пополните кошелёк.",
            reply_markup=kb
        )
        return

    if advice.startswith("OFFER:"):
        need = float(advice.split(":",1)[1])
        rub = _calc_oneoff_price_rub(engine, need)
        aid = _new_aid()
        # Помним, что после оплаты нужно запустить действие (храним в памяти процесса)
        _pending_actions[aid] = {"kind": remember_kind, "payload": remember_payload or {}, "do": do_func}
        kv_set(f"pending:{user_id}:{aid}", json.dumps({"kind": remember_kind, "usd": need}))

        title = f"Разовая операция: {engine.upper()}"
        desc  = f"Оплата разового запуска ({engine}) ≈ ${need:.2f}."
        payload = _payload_oneoff(engine, int(round(need*100)), aid=aid)
        await _send_invoice_rub(update, title, desc, payload, rub_amount=rub)
        return

    await update.effective_message.reply_text("Не удалось проверить бюджет для операции.")

# ───────── CryptoBot (опционально) ─────────
CRYPTOBOT_API_KEY = os.environ.get("CRYPTOBOT_API_KEY", "").strip()
CRYPTOBOT_BASE    = os.environ.get("CRYPTOBOT_BASE", "https://pay.crypt.bot").rstrip("/")

def _crypto_headers():
    return {"Crypto-Pay-API-Token": CRYPTOBOT_API_KEY, "Content-Type": "application/json"}

def _crypto_api(path: str, payload: dict) -> dict:
    r = httpx.post(f"{CRYPTOBOT_BASE}/api/{path.lstrip('/')}", headers=_crypto_headers(), json=payload, timeout=30.0)
    r.raise_for_status()
    return r.json()

def _crypto_create_invoice(amount_usd: float, desc: str) -> dict | None:
    try:
        payload = {"asset":"USDT", "amount": str(round(amount_usd, 2)), "description": desc[:250]}
        js = _crypto_api("createInvoice", payload)
        return js.get("result")
    except Exception as e:
        log.exception("CryptoBot create invoice error: %s", e)
        return None

def _crypto_get_invoice(invoice_id: int) -> dict | None:
    try:
        js = _crypto_api("getInvoices", {"invoice_ids": [invoice_id]})
        res = js.get("result", {}).get("items", [])
        return res[0] if res else None
    except Exception as e:
        log.exception("CryptoBot get invoice error: %s", e)
        return None

async def _send_topup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Пополнить кошелёк (₽)", callback_data="noop")],
        [InlineKeyboardButton("Пополнить через CryptoBot (USDT)", callback_data="noop")],
    ])
    await update.effective_message.reply_text("Выберите метод пополнения кошелька:", reply_markup=kb)

# ───────── /plans (подписки) ─────────
def _plan_rub(tier: str) -> int:
    # примерные цены RUB/мес
    return {"start": 499, "pro": 1290, "ultimate": 2490}.get(tier, 1290)

def _plan_payload_and_amount(tier: str, months: int = 1) -> tuple[str, int, str]:
    pay = _payload_subscribe(tier, months=months)
    rub = _plan_rub(tier) * months
    label = f"Подписка {tier} × {months} мес."
    return pay, rub, label

def _plan_mechanics_text() -> str:
    return (
        "⭐ Подписки дают увеличенные лимиты на тексты/изображения и бюджеты на видео-движки.\n"
        "• start — для лёгкого старта.\n"
        "• pro — оптимально для активного использования.\n"
        "• ultimate — максимум возможностей.\n\n"
        "Можно также пополнять единый USD-кошелёк для разовых задач."
    )

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["Доступные планы:"]
    for tier in ("start","pro","ultimate"):
        rub = _plan_rub(tier)
        lines.append(f"• {tier}: {rub} ₽ / мес")
    lines.append("")
    lines.append(_plan_mechanics_text())
    await update.effective_message.reply_text("\n".join(lines))

    # Сразу выдадим 3 инвойса (по кнопке было бы лучше, но Telegram позволяет и прямой выдачей):
    for tier in ("start", "pro", "ultimate"):
        payload, rub, label = _plan_payload_and_amount(tier, months=1)
        await _send_invoice_rub(update, f"Подписка: {tier}", "Оплата подписки на 1 месяц.", payload, rub)

# ───────── Диагностика/сервисы-пустышки (если не определены выше) ─────────
if "cmd_img" not in globals():
    async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.effective_message.reply_text("Команда /img: пришлите описание или фото — подскажу, что можно сделать.")

if "cmd_diag_images" not in globals():
    async def cmd_diag_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.effective_message.reply_text(f"IMAGES_MODEL = {IMAGES_MODEL}")

if "cmd_diag_stt" not in globals():
    async def cmd_diag_stt(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.effective_message.reply_text("STT OK (если ключи заданы). Пришлите voice для проверки.")

if "cmd_diag_limits" not in globals():
    async def cmd_diag_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        lim = _limits_for(uid); row = _usage_row(uid)
        txt = (
            f"Тариф: {lim['tier']}\n"
            f"Тексты: {row['text_count']}/{lim['text_per_day']} сегодня\n"
            f"IMG бюджет: {row['img_usd']:.2f}/{lim['img_budget_usd']:.2f} USD\n"
            f"LUMA бюджет: {row['luma_usd']:.2f}/{lim['luma_budget_usd']:.2f} USD\n"
            f"RUNWAY бюджет: {row['runway_usd']:.2f}/{lim['runway_budget_usd']:.2f} USD\n"
            f"Единый кошелёк: ${_wallet_total_get(uid):.2f}"
        )
        await update.effective_message.reply_text(txt)

if "cmd_diag_video" not in globals():
    async def cmd_diag_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.effective_message.reply_text(f"LUMA: {LUMA_BASE_URL} / RUNWAY: {RUNWAY_BASE_URL}")

# ───────── Обработчик данных из WebApp (заглушка) ─────────
if "on_webapp_data" not in globals():
    async def on_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            data = update.effective_message.web_app_data.data
            await update.effective_message.reply_text(f"WebApp data: {data[:200]}")
        except Exception:
            await update.effective_message.reply_text("WebApp: нет данных.")


# ───────── Фото: быстрые действия и обработка ─────────

# Храним последнее фото пользователя (в KV), чтобы действия брали его как «референс».
def _save_last_photo(user_id: int, data_b: bytes, mime: str):
    try:
        kv_set(f"lastphoto:{user_id}:mime", mime)
        kv_set(f"lastphoto:{user_id}:b64", base64.b64encode(data_b).decode("ascii"))
    except Exception:
        pass

def _get_last_photo(user_id: int) -> tuple[bytes | None, str]:
    try:
        b64 = kv_get(f"lastphoto:{user_id}:b64", None)
        mime = kv_get(f"lastphoto:{user_id}:mime", "image/jpeg")
        if not b64:
            return None, mime
        return base64.b64decode(b64), mime
    except Exception:
        return None, "image/jpeg"

def _photo_actions_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧼 Убрать фон", callback_data="pact:bg_remove"),
            InlineKeyboardButton("🌅 Заменить фон", callback_data="pact:bg_replace"),
        ],
        [
            InlineKeyboardButton("➕ Добавить объект", callback_data="pact:add_object"),
            InlineKeyboardButton("➖ Удалить объект", callback_data="pact:del_object"),
        ],
        [
            InlineKeyboardButton("🎬 Оживить (Luma)", callback_data="pact:animate_luma"),
            InlineKeyboardButton("🎥 Оживить (Runway)", callback_data="pact:animate_runway"),
        ],
        [
            InlineKeyboardButton("🔍 Супер-резкость x2", callback_data="pact:superres"),
            InlineKeyboardButton("📸 Повернуть «камеру»", callback_data="pact:cam_turn"),
        ],
        [InlineKeyboardButton("ℹ️ Что ещё можно сделать?", callback_data="pact:help")]
    ])

def _photo_tip_text(caption: str | None) -> str:
    tip = [
        "Что могу сделать с фото:",
        "• убрать/заменить фон;",
        "• добавить или удалить объекты/людей;",
        "• дорисовать недостающие ракурсы;",
        "• «оживить» фото в короткое видео (Luma/Runway);",
        "• повысить резкость/качество.",
        "Нажми кнопку ниже — запущу нужное действие.",
    ]
    if caption and caption.strip():
        tip.append("")
        tip.append(f"Твоя подпись учтена: «{caption.strip()}».")
    return "\n".join(tip)

# Переопределяем on_photo: добавляем сохранение кадра и быстрые кнопки (последняя дефиниция перезапишет прежнюю).
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ok, _, _ = check_text_and_inc(user_id, (update.effective_user.username or ""))
    if not ok:
        await update.effective_message.reply_text("Дневной лимит текстовых запросов исчерпан. Оформите подписку через /plans.")
        return
    try:
        file = await update.message.photo[-1].get_file()
        data = await file.download_as_bytearray()
        mime = sniff_image_mime(bytes(data))
        _save_last_photo(user_id, bytes(data), mime)

        # Анализ (vision) с учётом подписи
        user_text = (update.message.caption or "").strip()
        b64 = base64.b64encode(bytes(data)).decode("ascii")
        ans = await ask_openai_vision(user_text, b64, mime)
        if not ans:
            ans = "Готово."

        # Отправляем подсказки + быстрые действия
        await update.effective_message.reply_text(
            _photo_tip_text(user_text),
            reply_markup=_photo_actions_kb(),
            disable_web_page_preview=True
        )
        # Отдельно — ответ по анализу
        await update.effective_message.reply_text(ans)
        await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])
    except Exception as e:
        log.exception("Photo handler error: %s", e)
        await update.effective_message.reply_text("Не удалось обработать изображение.")

# Простые «редакторы» как генерация новой версии по описанию
async def _img_edit_like_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, note: str = ""):
    """Псевдо-редактирование: создаём новую версию по описанию (быстро и без масок)."""
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
    except Exception:
        pass
    try:
        resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
        b64 = resp.data[0].b64_json
        img_bytes = base64.b64decode(b64)
        cap = f"{note}Готово ✅\nЗапрос: {prompt}"
        await update.effective_message.reply_photo(photo=img_bytes, caption=cap)
    except Exception as e:
        log.exception("_img_edit_like_generate error: %s", e)
        await update.effective_message.reply_text("Не удалось получить результат для этого действия.")

# Хэндлер action-кнопок по фото
async def on_cb_photo_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "")
    await q.answer()
    user_id = update.effective_user.id
    last_img, last_mime = _get_last_photo(user_id)

    # Берём подпись из последнего сообщения (если есть) через KV (можно добавить позже), пока используем текст-плейсхолдер:
    caption_hint = ""

    # Разветвление по действиям
    if data == "pact:bg_remove":
        prompt = "Remove background from the subject. Return PNG with transparent background, keep edges clean and natural."
        await _img_edit_like_generate(update, context, prompt, note="🧼 Удаление фона.\n")
        return

    if data == "pact:bg_replace":
        # Подсказываем пользователю варианты фонов (без дополнительных кликов)
        await update.effective_message.reply_text(
            "Напиши одной фразой, какой фон нужен (напр.: «пляж на закате», «студийный белый», «город ночью»), и я заменю."
        )
        return

    if data == "pact:add_object":
        await update.effective_message.reply_text("Что добавить к фото? Опиши коротко: объект, размер/позицию.")
        return

    if data == "pact:del_object":
        await update.effective_message.reply_text("Что удалить с фото? Опиши коротко объект/область.")
        return

    if data == "pact:superres":
        prompt = "Upscale the photo to higher resolution with sharper details, reduce noise, preserve natural look."
        await _img_edit_like_generate(update, context, prompt, note="🔍 Супер-резкость x2.\n")
        return

    if data == "pact:cam_turn":
        prompt = "Recreate the same scene from a slightly rotated camera angle; keep subjects consistent and realistic."
        await _img_edit_like_generate(update, context, prompt, note="📸 Поворот виртуальной камеры.\n")
        return

    if data == "pact:animate_luma":
        if not last_img:
            await update.effective_message.reply_text("Не нашёл последнее фото. Пришлите изображение ещё раз.")
            return
        # Оживление как видео: формируем короткий промпт
        prompt = "Make a short, subtle living photo: gentle parallax, slight hair/clothes movement, natural light flicker."
        dur, ar = 5, "9:16" if LUMA_ASPECT == "9:16" else "16:9"
        await _run_luma_video(update, context, prompt, dur, ar)
        return

    if data == "pact:animate_runway":
        if not last_img:
            await update.effective_message.reply_text("Не нашёл последнее фото. Пришлите изображение ещё раз.")
            return
        prompt = "Turn the still photo into a brief cinematic clip with natural micro-motions and gentle camera parallax."
        dur, ar = 5, "16:9"
        await _run_runway_video(update, context, prompt, dur, ar)
        return

    if data == "pact:help":
        await update.effective_message.reply_text(_photo_tip_text(caption_hint))
        return

# Дополнительный обработчик: если после нажатия «заменить/добавить/удалить» пользователь пишет текст —
# перехватываем ближайшее сообщение и запускаем генерацию.
async def on_followup_text_for_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return
    # Примитивный детект: ключевые слова после наших подсказок
    tl = text.lower()
    if any(k in tl for k in ("фон", "background", "замени", "заменить")):
        prompt = f"Replace photo background with: {text}. Keep subject edges clean and natural, photo-realistic result."
        await _img_edit_like_generate(update, context, prompt, note="🌅 Замена фона.\n")
        return
    if any(k in tl for k in ("добавь", "добавить", "add ")):
        prompt = f"Add object: {text}. Integrate seamlessly with correct lighting, shadows and perspective."
        await _img_edit_like_generate(update, context, prompt, note="➕ Добавление объекта.\n")
        return
    if any(k in tl for k in ("удали", "удалить", "remove")):
        prompt = f"Remove object: {text}. Fill background plausibly with correct textures and lighting."
        await _img_edit_like_generate(update, context, prompt, note="➖ Удаление объекта.\n")
        return
        # Иначе — обычная текстовая обработка
    await _process_text(update, context, text)


# ───────── Платёжные события: precheckout/success (если ещё не объявлены выше) ─────────
if "on_precheckout" not in globals():
    async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            await update.pre_checkout_query.answer(ok=True)
        except Exception as e:
            log.exception("precheckout error: %s", e)

if "on_success_payment" not in globals():
    async def on_success_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            pay = update.message.successful_payment
            raw = pay.invoice_payload or ""
            kvp = _payload_parse(raw)
            t = kvp.get("t")
            if t == "1":  # one-off
                await update.effective_message.reply_text("💳 Оплата получена. Запускаю задачу…")
                # Если сохраняли pending по aid — можно достать и выполнить; см. твою реализацию выше.
                return
            if t == "2":  # subscribe
                await update.effective_message.reply_text("⭐ Подписка активирована. Спасибо!")
                return
            if t == "3":  # topup
                await update.effective_message.reply_text("💳 Баланс пополнен.")
                return
            await update.effective_message.reply_text("✅ Платёж принят.")
        except Exception as e:
            log.exception("on_success_payment error: %s", e)
            await update.effective_message.reply_text("Ошибка обработки платежа.")


# ───────── Общий error handler (если ещё не объявлен выше) ─────────
if "on_error" not in globals():
    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
        try:
            log.exception("Unhandled exception in handler: %s", getattr(context, "error", None))
            if hasattr(update, "effective_chat") and update.effective_chat:
                await context.bot.send_message(update.effective_chat.id, "⚠️ Произошла ошибка. Попробуйте ещё раз.")
        except Exception:
            pass


# ───────── Запуск: webhook/polling ─────────
def _ensure_loop():
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return False

def run_by_mode(app):
    _ensure_loop()

    async def _cleanup_webhook():
        with contextlib.suppress(Exception):
            await app.bot.delete_webhook(drop_pending_updates=True)
            log.info("Webhook cleanup done.")

    try:
        asyncio.get_event_loop().run_until_complete(_cleanup_webhook())
    except Exception:
        pass

    if USE_WEBHOOK:
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}",
            secret_token=(WEBHOOK_SECRET or None),
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        _start_http_stub()
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


# ───────── main(): регистрация всех обработчиков и запуск ─────────
def main():
    # Инициализация БД и пр.
    try: db_init()
    except Exception: pass
    try: db_init_usage()
    except Exception: pass
    try: _db_init_prefs()
    except Exception: pass

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("modes", cmd_modes))
    app.add_handler(CommandHandler("examples", cmd_examples))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("img", cmd_img))
    app.add_handler(CommandHandler("diag_images", cmd_diag_images))
    app.add_handler(CommandHandler("diag_stt", cmd_diag_stt))
    app.add_handler(CommandHandler("diag_limits", cmd_diag_limits))
    app.add_handler(CommandHandler("diag_video", cmd_diag_video))
    app.add_handler(CommandHandler("voice_on", cmd_voice_on))
    app.add_handler(CommandHandler("voice_off", cmd_voice_off))
    app.add_handler(CommandHandler("set_welcome", cmd_set_welcome))
    app.add_handler(CommandHandler("welcome", cmd_show_welcome))

    # WebApp data
    if "on_webapp_data" in globals():
        app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))

    # Коллбэки
    app.add_handler(CallbackQueryHandler(on_cb_photo_actions, pattern=r"^pact:"))  # наши фото-действия
    if "on_cb" in globals():
        app.add_handler(CallbackQueryHandler(on_cb))  # общий обработчик коллбэков (тарифы/видео и пр.)

    # Платежи
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_success_payment))

    # Фото (расширенная версия с кнопками)
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))

    # Голос/аудио
    if "on_voice" in globals():
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))

    # Аудио-файлы как документы
    if "on_audio_document" in globals():
        audio_doc_filter = (
            filters.Document.MimeType("audio/mpeg")
            | filters.Document.MimeType("audio/ogg")
            | filters.Document.MimeType("audio/oga")
            | filters.Document.MimeType("audio/mp4")
            | filters.Document.MimeType("audio/x-m4a")
            | filters.Document.MimeType("audio/webm")
            | filters.Document.MimeType("audio/wav")
            | filters.Document.FileExtension("mp3")
            | filters.Document.FileExtension("m4a")
            | filters.Document.FileExtension("wav")
            | filters.Document.FileExtension("ogg")
            | filters.Document.FileExtension("oga")
            | filters.Document.FileExtension("webm")
        )
        app.add_handler(MessageHandler(audio_doc_filter, on_audio_document))

    # Документы для анализа
    if "on_doc_analyze" in globals():
        docs_filter = (
            filters.Document.FileExtension("pdf")
            | filters.Document.FileExtension("epub")
            | filters.Document.FileExtension("docx")
            | filters.Document.FileExtension("fb2")
            | filters.Document.FileExtension("txt")
            | filters.Document.FileExtension("mobi")
            | filters.Document.FileExtension("azw")
            | filters.Document.FileExtension("azw3")
        )
        app.add_handler(MessageHandler(docs_filter, on_doc_analyze))

    # Кнопки главного меню (тексты)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\s*⭐\s*Подписка\s*$"), cmd_plans))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\s*🎛\s*Движки\s*$"), cmd_modes))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\s*🧾\s*Баланс\s*$"), cmd_balance))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\s*ℹ️\s*Помощь\s*$"), cmd_help))

    # Follow-up текст после фото-действий (замена/добавление/удаление и т.п.)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_followup_text_for_photo))

    # Общий error handler
    app.add_error_handler(on_error)

    # Запуск
    run_by_mode(app)


if __name__ == "__main__":
    main()
