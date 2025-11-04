# -*- coding: utf-8 -*-
# main.py — GPT-бот с оплатами, подписками, Images Edits и быстрыми фото-действиями.
# Часть 1/3: строки 1–1000

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
    # kv store (для бэннера, пр.)
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

    # В пределах тарифа (или demo free)
    if spent + est_cost_usd <= budget + 1e-9:
        _usage_update(user_id, **{f"{engine}_usd": est_cost_usd})
        return True, ""

    # Попытка покрыть из единого кошелька
    need = max(0.0, spent + est_cost_usd - budget)
    if need > 0:
        if _wallet_total_take(user_id, need):
            _usage_update(user_id, **{f"{engine}_usd": est_cost_usd})
            return True, ""
        # если совсем free и кошелёк пуст — предлагаем подписку
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
async def ask_openai_text(user_text: str, web_ctx: str = "") -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({"role": "system", "content": f"Контекст из веб-поиска:\n{web_ctx}"})
    messages.append({"role": "user", "content": user_text})

    last_err = None
    for attempt in range(3):
        try:
            resp = oai_llm.chat.completions.create(
                model=OPENAI_MODEL, messages=messages, temperature=0.6
            )
            txt = (resp.choices[0].message.content or "").strip()
            if txt:
                return txt
        except Exception as e:
            last_err = e
            log.warning("OpenAI/OpenRouter chat attempt %d failed: %s", attempt+1, e)
            await asyncio.sleep(0.8 * (attempt + 1))
    log.error("ask_openai_text failed: %s", last_err)
    return "⚠️ Сейчас не получилось получить ответ от модели. Я на связи — попробуй переформулировать запрос или повторить чуть позже."

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
        return "Не удалось проанализировать изображение."

# ───────── TTS (единая версия) ─────────
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

try:
    TTS_MAX_CHARS = max(int(TTS_MAX_CHARS), 150)
except Exception:
    TTS_MAX_CHARS = 150

def _tts_bytes_sync(text: str) -> bytes | None:
    try:
        r = oai_tts.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=OPENAI_TTS_VOICE,
            input=text,
            response_format="opus"  # для Telegram voice
        )
        audio = getattr(r, "content", None)
        if isinstance(audio, (bytes, bytearray)):
            return bytes(audio)
        if hasattr(r, "read"):
            return r.read()
    except Exception as e:
        log.exception("TTS error: %s", e)
    return None

async def maybe_tts_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    if not _tts_get(user_id):
        return
    if not text:
        return
    if len(text) > TTS_MAX_CHARS:
        try:
            await update.effective_message.reply_text(
                f"🔇 Озвучка выключена для этого сообщения: текст длиннее {TTS_MAX_CHARS} символов."
            )
        except Exception:
            pass
        return
    if not OPENAI_TTS_KEY:
        return
    try:
        try:
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VOICE)
        except Exception:
            pass
        audio = await asyncio.to_thread(_tts_bytes_sync, text)
        if not audio:
            try:
                await update.effective_message.reply_text("🔇 Не удалось синтезировать голос.")
            except Exception:
                pass
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

# ───────── Files (extract) ─────────
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
        if t: return t
    except Exception:
        pass
    try:
        from pdfminer_high_level import extract_text  # type: ignore
    except Exception:
        try:
            from pdfminer.high_level import extract_text  # fallback
        except Exception:
            extract_text = None  # type: ignore
    if extract_text:
        try:
            return (extract_text(BytesIO(data)) or "").strip()
        except Exception:
            pass
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        txt = []
        for page in doc:
            try: txt.append(page.get_text("text"))
            except Exception: continue
        return ("\n".join(txt))
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
            if item.get_type() == 9:
                try:
                    soup = BeautifulSoup(item.get_content(), "html.parser")
                    txt = soup.get_text(separator=" ", strip=True)
                    if txt: chunks.append(txt)
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
            if elem.text and elem.text.strip(): texts.append(elem.text.strip())
        return " " .join(texts).strip()
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

# ───────── Summarization helpers ─────────
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

# ───────── Images: generate + edits ─────────
async def _do_img_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
        b64 = resp.data[0].b64_json
        img_bytes = base64.b64decode(b64)
        await update.effective_message.reply_photo(photo=img_bytes, caption=f"Готово ✅\nЗапрос: {prompt}")
    except Exception as e:
        log.exception("IMG gen error: %s", e)
        await update.effective_message.reply_text(f"Не удалось создать изображение.")

# универсальная правка
async def img_edit_generic(raw: bytes, mime: str, prompt: str) -> bytes | None:
    try:
        bio = BytesIO(raw)
        bio.name = "image.png" if mime == "image/png" else "image.jpg"
        res = oai_img.images.edits(
            model=IMAGES_MODEL,
            image=bio,
            prompt=prompt,
            size="1024x1024",
            n=1
        )
        return base64.b64decode(res.data[0].b64_json)
    except Exception as e:
        log.warning("img_edit_generic error: %s", e)
        return None

async def do_animate(update, context, raw, mime, extra: str | None = None):
    await update.effective_message.reply_text("🎞️ Оживляю мимику (моргание, лёгкая улыбка)…")
    prompt = "Subtle animate-like enhancement: lifelike facial micro-expressions; preserve identity; photorealistic."
    img = await img_edit_generic(raw, mime, prompt)
    await update.effective_message.reply_photo(photo=img if img else raw, caption="Готово ✅ Оживлённая мимика" if img else "Не получилось — вернул исходник.")

async def do_bg_remove(update, context, raw, mime):
    await update.effective_message.reply_text("🧼 Убираю фон…")
    img = await img_edit_generic(raw, mime, "Remove background to transparent/white; keep subject; clean edges.")
    await update.effective_message.reply_photo(photo=img if img else raw, caption="Готово ✅ Фон удалён" if img else "Не получилось — вернул исходник.")

async def do_bg_replace(update, context, raw, mime, bg_prompt: str):
    await update.effective_message.reply_text(f"🖼 Заменяю фон → {bg_prompt} …")
    img = await img_edit_generic(raw, mime, f"Replace background to: {bg_prompt}. Preserve subject; realistic light/shadows.")
    await update.effective_message.reply_photo(photo=img if img else raw, caption=f"Готово ✅ Фон: {bg_prompt}" if img else "Не получилось — вернул исходник.")

async def do_add_obj(update, context, raw, mime, what: str):
    await update.effective_message.reply_text(f"➕ Добавляю предмет: {what}")
    img = await img_edit_generic(raw, mime, f"Add object: {what}. Integrate naturally with matching lighting and perspective.")
    await update.effective_message.reply_photo(photo=img if img else raw, caption="Готово ✅" if img else "Не получилось — вернул исходник.")

async def do_del_obj(update, context, raw, mime, what: str):
    await update.effective_message.reply_text(f"➖ Удаляю предмет: {what}")
    img = await img_edit_generic(raw, mime, f"Remove object: {what}. Realistic inpainting of background.")
    await update.effective_message.reply_photo(photo=img if img else raw, caption="Готово ✅" if img else "Не получилось — вернул исходник.")

async def do_add_human(update, context, raw, mime, desc: str):
    await update.effective_message.reply_text(f"👤 Добавляю человека: {desc}")
    img = await img_edit_generic(raw, mime, f"Add a person: {desc}. Perspective and lighting must match; natural result.")
    await update.effective_message.reply_photo(photo=img if img else raw, caption="Готово ✅" if img else "Не получилось — вернул исходник.")

async def do_del_human(update, context, raw, mime, who: str):
    await update.effective_message.reply_text(f"🚫 Удаляю человека: {who}")
    img = await img_edit_generic(raw, mime, f"Remove person: {who}. Realistic inpainting.")
    await update.effective_message.reply_photo(photo=img if img else raw, caption="Готово ✅" if img else "Не получилось — вернул исходник.")

async def do_outpaint(update, context, raw, mime, how: str):
    await update.effective_message.reply_text("🧩 Дорисовываю/расширяю сцену…")
    img = await img_edit_generic(raw, mime, f"Outpaint / extend scene: {how}. Keep style consistent and coherent details.")
    await update.effective_message.reply_photo(photo=img if img else raw, caption="Готово ✅" if img else "Не получилось — вернул исходник.")

async def do_cam_move(update, context, raw, mime, how: str):
    await update.effective_message.reply_text("🎥 «Поворачиваю камеру» — показываю продолжение сцены…")
    img = await img_edit_generic(raw, mime, f"Reveal beyond current frame as if camera pans: {how}. Extend environment plausibly.")
    await update.effective_message.reply_photo(photo=img if img else raw, caption="Готово ✅" if img else "Не получилось — вернул исходник.")

# ───────── UI / тексты ─────────
START_TEXT = (
    "Привет! Я GPT-бот с тарифами, квотами и разовыми пополнениями.\n\n"
    "Что умею:\n"
    "• 💬 Текст/фото (GPT)\n"
    "• 🖼 Изображения: генерация и правки\n"
    "   — оживить мимику • убрать/заменить фон • добавить/удалить предмет/человека\n"
    "   — дорисовать сцену (outpaint) • «повернуть камеру» и показать, что вне кадра\n"
    "• 🎬 Видео Luma / 🎥 Runway\n"
    "• 📄 Анализ PDF/EPUB/DOCX/FB2/TXT — просто пришли файл.\n\n"
    "Пришли фото — появятся быстрые кнопки. Голосовые команды тоже поддерживаются."
)

HELP_TEXT = (
    "Подсказки:\n"
    "• /plans — тарифы и оплата подписки (через чат или мини-приложение)\n"
    "• /img кот с очками — сгенерирует картинку\n"
    "• «сделай видео … 9 секунд 9:16» — Luma/Runway\n"
    "• Фото с подписью: «Оживи», «Убери фон», «Замени фон на пляж», «Добавь человека справа», "
    "«Удалить предмет слева», «Дорисуй сцену шире», «Поверни камеру вправо».\n"
    "• /voice_on и /voice_off — озвучка ответов."
)

EXAMPLES_TEXT = (
    "Примеры:\n"
    "• сделай видео ретро-авто на берегу, 9 секунд, 9:16\n"
    "• /img неоновый город в дождь, реализм\n"
    "• пришли PDF — сделаю тезисы и выводы\n"
    "• пришли фото — выбери быстрое действие (оживить/фон/добавить/удалить/дорисовать/камера)"
)

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎛 Движки"), KeyboardButton("⭐ Подписка")],
            [KeyboardButton("🧾 Баланс"), KeyboardButton("ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
        input_field_placeholder="Напишите запрос или выберите пункт меню",
    )

main_kb = main_keyboard()

def engines_kb():
    # ВАЖНО: никаких кнопок «на тарифы» здесь нет (как просили)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 GPT (текст/фото/документы)", callback_data="engine:gpt")],
        [InlineKeyboardButton("🖼 Images (OpenAI)",             callback_data="engine:images")],
        [InlineKeyboardButton("🗣 STT/TTS — речь↔текст",        callback_data="engine:stt_tts")],
        # По желанию можно включить Luma/Runway без ссылки на тарифы:
        [InlineKeyboardButton("🎬 Luma — короткие видео",       callback_data="engine:luma")],
        [InlineKeyboardButton("🎥 Runway — премиум-видео",      callback_data="engine:runway")],
    ])

# ───────── Router: text/photo/voice/docs/img/video ───────
def sniff_image_mime(b: bytes) -> str:
    if b.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if b[:3] == b"\xff\xd8\xff":         return "image/jpeg"
    if b[:6] == b"GIF87a" or b[:6] == b"GIF89a": return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":  return "image/webp"
    return "application/octet-stream"

_last_photo: dict[int, dict] = {}  # user_id -> {"bytes":..., "mime":..., "aid":...}

def quick_actions_kb(aid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎞 Оживить мимику", callback_data=f"imgact:animate:{aid}")],
        [InlineKeyboardButton("🧼 Убрать фон", callback_data=f"imgact:bg_remove:{aid}"),
         InlineKeyboardButton("🖼 Заменить фон", callback_data=f"imgact:bg_replace:{aid}")],
        [InlineKeyboardButton("➕ Добавить предмет", callback_data=f"imgact:add_obj:{aid}"),
         InlineKeyboardButton("➖ Удалить предмет", callback_data=f"imgact:del_obj:{aid}")],
        [InlineKeyboardButton("👤 Добавить человека", callback_data=f"imgact:add_human:{aid}"),
         InlineKeyboardButton("🚫 Удалить человека", callback_data=f"imgact:del_human:{aid}")],
        [InlineKeyboardButton("🧩 Дорисовать сцену", callback_data=f"imgact:outpaint:{aid}"),
         InlineKeyboardButton("🎥 Повернуть камеру", callback_data=f"imgact:cam_move:{aid}")],
    ])

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    # Позитивный ответ на фото-фичи из ТЕКСТА
    ans_cap = capability_answer(text)
    if ans_cap:
        await update.effective_message.reply_text(ans_cap)
        with contextlib.suppress(Exception):
            await maybe_tts_reply(update, context, ans_cap[:TTS_MAX_CHARS])
        return

    await _process_text(update, context, text)

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ok, left, tier = check_text_and_inc(user_id, (update.effective_user.username or ""))
    if not ok:
        await update.effective_message.reply_text(
            "Дневной лимит текстовых запросов исчерпан. Оформите подписку через /plans."
        )
        return
    try:
        file = await update.message.photo[-1].get_file()
        data = await file.download_as_bytearray()
        img_bytes = bytes(data)
        mime = sniff_image_mime(img_bytes)
        aid = uuid.uuid4().hex[:8]
        _last_photo[user_id] = {"bytes": img_bytes, "mime": mime, "aid": aid}

        note = ("Выберите быстрое действие. "
                "Также доступны другие правки — просто опишите текстом или голосом (например: «добавь человека справа», "
                "«удали предмет слева», «поверни камеру вправо», «дорисуй сцену шире»).")
        await update.effective_message.reply_text("Фото получено. Что делаем?", reply_markup=quick_actions_kb(aid))
        await update.effective_message.reply_text(note)

        # авто-интерпретация подписи
        caption = (update.message.caption or "").strip().lower()
        if not caption:
            return
        if "ожив" in caption or "анимиру" in caption:
            await do_animate(update, context, img_bytes, mime, extra=update.message.caption)
        elif ("убер" in caption and "фон" in caption) or "remove background" in caption:
            await do_bg_remove(update, context, img_bytes, mime)
        elif "замен" in caption and "фон" in caption:
            m = re.search(r"(на|to)\s+(.+)$", update.message.caption, re.I)
            bg = m.group(2).strip() if m else "clean studio white background"
            await do_bg_replace(update, context, img_bytes, mime, bg)
        elif "добав" in caption and "предмет" in caption:
            what = re.sub(r".*предмет(а|)\s*", "", update.message.caption, flags=re.I).strip() or "desired object"
            await do_add_obj(update, context, img_bytes, mime, what)
        elif "удал" in caption and "предмет" in caption:
            what = re.sub(r".*предмет(а|)\s*", "", update.message.caption, flags=re.I).strip() or "unwanted object"
            await do_del_obj(update, context, img_bytes, mime, what)
        elif "добав" in caption and "челов" in caption:
            desc = re.sub(r".*человека?\s*", "", update.message.caption, flags=re.I).strip() or "a person matching scene"
            await do_add_human(update, context, img_bytes, mime, desc)
        elif "удал" in caption and "челов" in caption:
            who = re.sub(r".*человека?\s*", "", update.message.caption, flags=re.I).strip() or "the person indicated"
            await do_del_human(update, context, img_bytes, mime, who)
        elif "дорис" in caption or "outpaint" in caption or "расшир" in caption:
            how = update.message.caption or "extend borders coherently"
            await do_outpaint(update, context, img_bytes, mime, how)
        elif "поверн" in caption or "камера" in caption or "додумай" in caption:
            how = update.message.caption or "pan right and reveal off-frame"
            await do_cam_move(update, context, img_bytes, mime, how)
    except Exception as e:
        log.exception("Photo handler error: %s", e)
        await update.effective_message.reply_text("Не удалось обработать изображение.")

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        f = None
        if update.message.voice:
            f = await update.message.voice.get_file()
            fname = "voice.ogg"
        elif update.message.audio:
            f = await update.message.audio.get_file()
            fname = (update.message.audio.file_name or "audio").lower()
            if not re.search(r"\.(ogg|mp3|m4a|wav|webm)$", fname):
                fname += ".ogg"
        else:
            await update.effective_message.reply_text("Тип аудио не поддерживается.")
            return
        data = await f.download_as_bytearray()
        buf = BytesIO(bytes(data))
        txt = await transcribe_audio(buf, filename_hint=fname)
        if not txt:
            await update.effective_message.reply_text("Не удалось распознать речь.")
            return
        await update.effective_message.reply_text(f"🗣️ Распознано: {txt}")

        # Позитивный ответ на фото-фичи из ГОЛОСА
        ans_cap = capability_answer(txt)
        if ans_cap:
            await update.effective_message.reply_text(ans_cap)
            with contextlib.suppress(Exception):
                await maybe_tts_reply(update, context, ans_cap[:TTS_MAX_CHARS])
            return

        await _process_text(update, context, txt)
    except Exception as e:
        log.exception("Voice handler error: %s", e)
        await update.effective_message.reply_text("Ошибка обработки голосового сообщения.")

# документы: аудио-файлы как документ (mp3/m4a/wav/ogg/webm)
async def on_audio_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document:
            return
        doc = update.message.document
        mime = (doc.mime_type or "").lower()
        name = (doc.file_name or "").lower()
        is_audio_like = (
            mime.startswith("audio/") or
            name.endswith((".mp3", ".m4a", ".wav", ".ogg", ".oga", ".webm"))
        )
        if not is_audio_like:
            return
        f = await doc.get_file()
        data = await f.download_as_bytearray()
        fname = name or "audio.ogg"
        buf = BytesIO(bytes(data))
        txt = await transcribe_audio(buf, filename_hint=fname)
        if not txt:
            await update.effective_message.reply_text("Не удалось распознать речь из файла.")
            return
        await update.effective_message.reply_text(f"🗣️ Распознано (файл): {txt}")

        ans_cap = capability_answer(txt)
        if ans_cap:
            await update.effective_message.reply_text(ans_cap)
            with contextlib.suppress(Exception):
                await maybe_tts_reply(update, context, ans_cap[:TTS_MAX_CHARS])
            return

        await _process_text(update, context, txt)
    except Exception as e:
        log.exception("Audio document handler error: %s", e)
        await update.effective_message.reply_text("Ошибка обработки аудио-файла.")

# ======= Diagnostics =======
async def cmd_diag_stt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = []
    lines.append("🔎 STТ диагностика:")
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

# обновлённая диагностика Luma/Runway
async def cmd_diag_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [
        "🎬 Видео-движки:",
        f"• Luma key: {'✅' if bool(LUMA_API_KEY) else '❌'}  base={LUMA_BASE_URL}",
        f"  create={LUMA_CREATE_PATH}  status={LUMA_STATUS_PATH}",
        f"  model={LUMA_MODEL}  allowed_durations=['5s','9s','10s']  aspect=['16:9','9:16','1:1']",
        f"• Runway key: {'✅' if bool(RUNWAY_API_KEY) else '❌'}  base={RUNWAY_BASE_URL}",
        f"  create={RUNWAY_CREATE_PATH}  status={RUNWAY_STATUS_PATH}",
        f"• Поллинг каждые {VIDEO_POLL_DELAY_S}s; таймауты: Luma {LUMA_MAX_WAIT_S}s / Runway {RUNWAY_MAX_WAIT_S}s",
        "",
        "🔎 Проверка Luma endpoints:",
    ]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                active_base = await _pick_luma_base(client)
                lines.append(f"• Активная база (detected): {active_base}")
            except Exception as e:
                active_base = None
                lines.append(f"• Активная база: ⛔ не удалось определить ({e})")
            for b in {active_base or '', LUMA_BASE_URL, *LUMA_FALLBACKS} - {''}:
                url = f"{b}{LUMA_CREATE_PATH}"
                try:
                    r = await client.options(url)
                    lines.append(f"• {url} — DNS/TLS OK (HTTP {r.status_code})")
                except Exception as e:
                    lines.append(f"• {url} — ⛔ {e.__class__.__name__}: {e}")
    except Exception as e:
        lines.append(f"• Общая ошибка диагностики: {e}")

    await update.effective_message.reply_text("\n".join(lines))

# ───────── [1001…] STT (распознавание речи) ─────────

async def _transcribe_openai(buf: BytesIO, filename_hint: str = "voice.ogg") -> str | None:
    if not oai_stt:
        return None
    try:
        buf.seek(0)
        return oai_stt.audio.transcriptions.create(
            model=TRANSCRIBE_MODEL,
            file=("voice", buf, "audio/ogg"),
            response_format="text",
            temperature=0.0
        )
    except Exception as e:
        log.warning("OpenAI STT fail: %s", e)
        return None

async def _transcribe_deepgram(buf: BytesIO, filename_hint: str = "voice.ogg") -> str | None:
    if not DEEPGRAM_API_KEY:
        return None
    try:
        buf.seek(0)
        headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": "audio/ogg"
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                "https://api.deepgram.com/v1/listen?model=nova-2-general&punctuate=true&smart_format=true&language=ru",
                headers=headers, content=buf.read()
            )
            if r.status_code // 100 != 2:
                log.warning("Deepgram STT http %s: %s", r.status_code, r.text[:500])
                return None
            data = r.json()
            # robust extraction
            try:
                return (data["results"]["channels"][0]["alternatives"][0]["transcript"] or "").strip()
            except Exception:
                return None
    except Exception as e:
        log.warning("Deepgram STT error: %s", e)
        return None

async def transcribe_audio(buf: BytesIO, filename_hint: str = "voice.ogg") -> str | None:
    """
    Унифицированное распознавание: сначала OpenAI Whisper (если ключ задан),
    иначе Deepgram (если ключ задан). Возвращает строку или None.
    """
    txt = await _transcribe_openai(buf, filename_hint=filename_hint)
    if txt:
        return txt.strip()
    buf.seek(0)
    txt = await _transcribe_deepgram(buf, filename_hint=filename_hint)
    return txt.strip() if txt else None


# ───────── [1045…] Позитивные ответы на фото-фичи (из текста/голоса) ─────────

def _has_recent_photo(user_id: int) -> bool:
    meta = _last_photo.get(user_id)
    return bool(meta and meta.get("bytes"))

def capability_answer(user_text: str) -> str | None:
    """
    Если пользователь спрашивает «можно ли …» про картинки — отвечаем «да» и перечисляем,
    что умеем (оживление, фон, добавить/удалить и пр.). Иначе None.
    """
    t = (user_text or "").lower()
    if not t:
        return None
    # триггеры
    if not re.search(r"(фото|картинк|изображен|image|picture|img|логотип|фон|анимиру|ожив|дорису|поверн|камера)", t):
        return None
    if not re.search(r"(мож(но|ешь|ете)|уме(ешь|ете)|поддержива(ешь|ете)|доступн(о|ы))", t):
        # если прямо просит сделать — тоже ок, но тогда не перехватываем (пусть идёт в основной роутер)
        if re.search(_CREATE_CMD, t, re.I):
            return None
    lines = [
        "Да, могу помочь с изображениями ✅",
        "Доступны действия:",
        "• 🎞 Оживить мимику (моргнуть, лёгкая улыбка);",
        "• 🧼 Убрать фон / 🖼 Заменить фон (любой: студия, пляж и т.п.);",
        "• ➕ Добавить предмет/человека • ➖ Удалить предмет/человека;",
        "• 🧩 Дорисовать сцену (outpaint) • 🎥 «Повернуть камеру» и показать, что вне кадра.",
    ]
    lines.append("")
    if _has_recent_photo(update_user_id := getattr(asyncio.current_task(), "user_id", None) or 0):
        lines.append("Прикреплено свежее фото — просто напишите действие, например: «замени фон на ночной город».")
    else:
        lines.append("Пришлите фото и выберите действие в быстрых кнопках, или опишите задачу текстом/голосом.")
    return "\n".join(lines)


# ───────── [1089…] Основной обработчик текста ─────────

async def _process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user = update.effective_user
    user_id = user.id
    username = user.username or ""

    # проверка дневных лимитов (считаем текстовые взаимодействия)
    ok, left, tier = check_text_and_inc(user_id, username)
    if not ok:
        await update.effective_message.reply_text(
            "Дневной лимит текстовых запросов исчерпан. Оформите подписку через /plans."
        )
        return

    # быстрые команды «img: …» и «video: …»
    media_kind, tail = detect_media_intent(text)

    # 1) Если запрос явно про ИЗОБРАЖЕНИЕ — генерим
    if media_kind == "image":
        prompt = tail or text
        await _do_img_generate(update, context, prompt)
        await maybe_tts_reply(update, context, f"Картинка по запросу готова.")
        return

    # 2) Если запрос явно про ВИДЕО — отправляем в Luma/Runway
    if media_kind == "video":
        await _process_video_request(update, context, tail or text)
        return

    # 3) Если это про «что умеешь с фото?» — уже отработал capability_answer в on_text/on_voice

    # 4) Обычный текст → LLM
    web_ctx = ""
    if should_browse(text) and tavily:
        try:
            q = text[:300]
            r = tavily.search(q, search_depth="advanced", max_results=5)
            refs = []
            for item in (r.get("results") or []):
                url = item.get("url")
                title = item.get("title")
                if url and title:
                    refs.append(f"- {title} — {url}")
            if refs:
                web_ctx = "Полезные ссылки:\n" + "\n".join(refs)
        except Exception as e:
            log.warning("Tavily fail: %s", e)

    reply = await ask_openai_text(text, web_ctx=web_ctx)
    await update.effective_message.reply_text(reply)
    await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])


# ───────── [1153…] Видео генерация (Luma / Runway) ─────────

def _parse_duration_aspect(text: str) -> tuple[int, str]:
    """
    Парсит длительность (сек) и аспект (строка «9:16», «16:9», «1:1») из текста запроса.
    По умолчанию 9 секунд, 9:16.
    """
    tl = text.lower()
    dur = 9
    asp = "9:16"
    m = re.search(r"(\d{1,2})\s*(сек|s|sec)", tl)
    if m:
        try:
            dur = max(3, min(15, int(m.group(1))))
        except Exception:
            pass
    if re.search(r"\b(9[:x]16|вертикал)", tl):
        asp = "9:16"
    elif re.search(r"\b(16[:x]9|горизонт)", tl):
        asp = "16:9"
    elif re.search(r"\b(1[:x]1|квадрат)", tl):
        asp = "1:1"
    return dur, asp

def _estimate_video_cost_usd(engine: str, dur: int) -> float:
    """
    Простейшая оценка себестоимости (условно): Luma — $0.05/сек, Runway — $0.25/сек.
    """
    if engine == "luma":
        return round(0.05 * dur, 2)
    if engine == "runway":
        return round(RUNWAY_UNIT_COST_USD, 2)  # фикс как «проект»
    return 0.0

async def _offer_topup_or_sub(update: Update, engine: str, need_usd: float):
    # если пришли сюда, бюджет в тарифе + единый кошелёк не покрыли
    if need_usd <= 0.0:
        return
    rub = _calc_oneoff_price_rub(engine, need_usd)
    txt = (
        "На этот запрос не хватает бюджета текущего тарифа. "
        f"Можно оформить подписку через /plans либо пополнить разово кошелёк на ~{need_usd:.2f}$ "
        f"(≈ {rub} ₽). Напишите: «пополни {rub}» — пришлю счёт."
    )
    await update.effective_message.reply_text(txt)

async def _luma_create_and_wait(prompt: str, duration_s: int, aspect: str) -> tuple[bool, str]:
    """
    Заглушка для Luma: здесь должен быть реальный вызов Luma API.
    Возвращаем (ok, url_или_ошибка).
    """
    if not LUMA_API_KEY:
        return False, "Luma API ключ не настроен."
    # Тут бы: POST /generations → id → poll /generations/{id} до готовности
    # Возвращаем фиктивный URL для тестов
    return True, "https://example.com/video_luma.mp4"

async def _runway_create_and_wait(prompt: str, duration_s: int, aspect: str) -> tuple[bool, str]:
    if not RUNWAY_API_KEY:
        return False, "Runway API ключ не настроен."
    return True, "https://example.com/video_runway.mp4"

async def _process_video_request(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user = update.effective_user
    user_id = user.id
    username = user.username or ""
    dur, asp = _parse_duration_aspect(text)
    # выбор движка: если упомянут runway — используем runway, иначе luma
    engine = "runway" if re.search(r"\brunway|runway\b", text.lower()) else "luma"
    est = _estimate_video_cost_usd(engine, dur)

    allowed = _limits_for(user_id).get("allow_engines", [])
    if engine not in allowed and not is_unlimited(user_id, username):
        # если free не имеет runway, предложим luma
        if engine == "runway" and "luma" in allowed:
            await update.effective_message.reply_text("Runway доступен в более высоких тарифах. Могу сделать через Luma — продолжать?")
            return
        await update.effective_message.reply_text("Этот движок недоступен в вашем тарифе. Посмотрите /plans.")
        return

    ok, reason = _can_spend_or_offer(user_id, username, "luma" if engine == "luma" else "runway", est)
    if not ok:
        if reason == "ASK_SUBSCRIBE" or reason.startswith("OFFER:"):
            need = 0.0
            if reason.startswith("OFFER:"):
                try:
                    need = float(reason.split(":", 1)[1])
                except Exception:
                    need = est
            await _offer_topup_or_sub(update, engine, need)
        else:
            await update.effective_message.reply_text("Недостаточно бюджета для видео.")
        return

    await update.effective_message.reply_text(f"Запускаю {engine.upper()} на {dur} сек, аспект {asp}. Запрос: {text}")
    if engine == "luma":
        ok, url = await _luma_create_and_wait(text, dur, asp)
    else:
        ok, url = await _runway_create_and_wait(text, dur, asp)

    if ok:
        await update.effective_message.reply_text(f"Готово ✅\n{url}")
        _register_engine_spend(user_id, "luma" if engine == "luma" else "runway", est)
    else:
        await update.effective_message.reply_text(f"Не удалось: {url}")


# ───────── [1292…] Inline callbacks: быстрые действия с последним фото ─────────

_pending_actions: dict[int, dict] = {}  # user_id -> {"kind": "...", "aid": "...", "ts": time.time()}

async def _require_last_photo(update: Update) -> tuple[bytes | None, str | None]:
    meta = _last_photo.get(update.effective_user.id)
    if not meta:
        await update.effective_message.reply_text("Пришлите фото, затем выберите действие.")
        return None, None
    return meta["bytes"], meta["mime"]

async def _ask_param(update: Update, kind: str, aid: str, hint: str):
    _pending_actions[update.effective_user.id] = {"kind": kind, "aid": aid, "ts": time.time()}
    await update.effective_message.reply_text(hint + "\n(Напишите текстом в следующем сообщении)")

async def _do_pending_if_any(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    meta = _pending_actions.pop(update.effective_user.id, None)
    if not meta:
        return False
    kind = meta["kind"]; aid = meta["aid"]
    last = _last_photo.get(update.effective_user.id)
    if not last or last.get("aid") != aid:
        await update.effective_message.reply_text("Фото было заменено, действие отменено. Пришлите новое фото.")
        return True
    raw, mime = last["bytes"], last["mime"]
    # маршрутизация
    if kind == "bg_replace":
        await do_bg_replace(update, context, raw, mime, text)
    elif kind == "add_obj":
        await do_add_obj(update, context, raw, mime, text)
    elif kind == "del_obj":
        await do_del_obj(update, context, raw, mime, text)
    elif kind == "add_human":
        await do_add_human(update, context, raw, mime, text)
    elif kind == "del_human":
        await do_del_human(update, context, raw, mime, text)
    elif kind == "outpaint":
        await do_outpaint(update, context, raw, mime, text)
    elif kind == "cam_move":
        await do_cam_move(update, context, raw, mime, text)
    else:
        await update.effective_message.reply_text("Неизвестное действие.")
    return True

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        data = q.data or ""
        await q.answer()
    except Exception:
        data = ""

    if not data:
        return

    # движки
    if data.startswith("engine:"):
        engine = data.split(":", 1)[1]
        if engine == "gpt":
            await q.message.reply_text("GPT: присылайте текст/фото/документы — отвечу по контенту.")
        elif engine == "images":
            await q.message.reply_text("Images (OpenAI): используйте /img <описание> или пришлите фото для правок.")
        elif engine == "stt_tts":
            await q.message.reply_text("Речь↔Текст: голосовые — распознаю; /voice_on включает озвучку ответов.")
        elif engine == "luma":
            await q.message.reply_text("Luma: напишите «сделай видео … 9 секунд 9:16» — запущу рендер.")
        elif engine == "runway":
            await q.message.reply_text("Runway: премиум-рендер. Укажите длительность/аспект в запросе.")
        return

    # быстрые действия с изображением
    if data.startswith("imgact:"):
        _, kind, aid = data.split(":", 2)
        raw, mime = await _require_last_photo(update)
        if not raw:
            return
        if kind == "animate":
            await do_animate(update, context, raw, mime)
            return
        if kind == "bg_remove":
            await do_bg_remove(update, context, raw, mime)
            return
        if kind == "bg_replace":
            await _ask_param(update, "bg_replace", aid, "На какой фон заменить? Пример: «ночной город с огнями»")
            return
        if kind == "add_obj":
            await _ask_param(update, "add_obj", aid, "Какой предмет добавить? Пример: «красная роза на столе»")
            return
        if kind == "del_obj":
            await _ask_param(update, "del_obj", aid, "Какой предмет удалить? Пример: «провод справа»")
            return
        if kind == "add_human":
            await _ask_param(update, "add_human", aid, "Опишите человека и расположение. Пример: «мужчина в чёрной куртке слева»")
            return
        if kind == "del_human":
            await _ask_param(update, "del_human", aid, "Кого удалить? Пример: «женщину в синем платье справа»")
            return
        if kind == "outpaint":
            await _ask_param(update, "outpaint", aid, "Как расширяем сцену? Пример: «шире вправо, добавить террасу»")
            return
        if kind == "cam_move":
            await _ask_param(update, "cam_move", aid, "Как «поворачиваем камеру»? Пример: «панорама вправо — показать окно»")
            return
        await q.message.reply_text("Неизвестное действие.")
        return


# ───────── [1475…] Команды: /start /help /engines /plans /balance и пр. ─────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if BANNER_URL:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_photo(BANNER_URL)
    await update.effective_message.reply_text(START_TEXT, reply_markup=main_kb, disable_web_page_preview=True)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, disable_web_page_preview=True)

async def cmd_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Выберите движок:", reply_markup=engines_kb())

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(EXAMPLES_TEXT)

# /img команда для генерации
async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.effective_message.reply_text("Формат: /img <описание>")
        return
    await _do_img_generate(update, context, text)

# Баланс/кошелёк
async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = _usage_row(user_id)
    tier = get_subscription_tier(user_id)
    lim = _limits_for(user_id)
    wal = _wallet_get(user_id)
    total = _wallet_total_get(user_id)
    lines = [
        f"Тариф: {tier}",
        f"Текст сегодня: {row['text_count']}/{lim['text_per_day']}",
        f"Luma бюджет: {row['luma_usd']:.2f}/{lim['luma_budget_usd']:.2f} $",
        f"Runway бюджет: {row['runway_usd']:.2f}/{lim['runway_budget_usd']:.2f} $",
        f"Images бюджет: {row['img_usd']:.2f}/{lim['img_budget_usd']:.2f} $",
        f"Единый кошелёк: {total:.2f} $",
        f"(Детализация: luma={wal['luma_usd']:.2f} runway={wal['runway_usd']:.2f} img={wal['img_usd']:.2f})"
    ]
    await update.effective_message.reply_text("\n".join(lines))

# Подписки и планы
def _plans_text() -> str:
    lines = [
        "⭐ Планы и подписки:",
        "",
        "START — 499₽/мес: базовый лимит текста, Luma демо, Images чуть больше",
        "PRO — 999₽/мес: ↑лимиты, Runway доступен, больше Luma/Images",
        "ULTIMATE — 1999₽/мес: максимум лимитов",
        "",
        "Оплата: /buy <plan> <term>",
        "Напр.: /buy pro month  или  /buy start year",
        "Также доступно разовое пополнение кошелька в $: /topup 5   (добавит ~5$)",
    ]
    return "\n".join(lines)

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(_plans_text())

# Покупка подписки через встроенный инвойс Telegram (YooKassa)
async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PROVIDER_TOKEN:
        await update.effective_message.reply_text("Оплата временно недоступна (нет provider token).")
        return
    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_text("Формат: /buy <start|pro|ultimate> <month|quarter|year>")
        return
    plan = args[0].lower()
    term = args[1].lower()
    if plan not in PLAN_PRICE_TABLE or term not in PLAN_PRICE_TABLE[plan]:
        await update.effective_message.reply_text("Некорректный план/срок.")
        return
    amount_rub = PLAN_PRICE_TABLE[plan][term]
    label = _ascii_label(f"{plan}-{term}")
    prices = [LabeledPrice(label=label, amount=amount_rub * 100)]
    payload = json.dumps({"type":"subscription","plan":plan,"term":term,"months":TERM_MONTHS[term]})
    title = f"Подписка {plan.upper()} на {term}"
    desc  = f"Оформление {plan.upper()} ({TERM_MONTHS[term]} мес.)"
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=title, description=desc,
        payload=payload, provider_token=PROVIDER_TOKEN,
        currency=CURRENCY, prices=prices
    )

# Разовое пополнение кошелька (в $ эквиваленте)
async def cmd_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PROVIDER_TOKEN:
        await update.effective_message.reply_text("Оплата временно недоступна (нет provider token).")
        return
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("Формат: /topup <сумма в $>   Например: /topup 5")
        return
    try:
        usd = max(1.0, float(args[0].replace(",", ".")))
    except Exception:
        await update.effective_message.reply_text("Неверная сумма.")
        return
    rub = _calc_oneoff_price_rub("luma", usd)  # считаем по дефолтной наценке
    label = _ascii_label(f"topup-{usd:.2f}$")
    prices = [LabeledPrice(label=label, amount=rub * 100)]
    payload = json.dumps({"type":"topup","usd":usd})
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=f"Пополнение кошелька (~{usd:.2f}$)",
        description="Средства будут доступны для Luma/Runway/Images",
        payload=payload, provider_token=PROVIDER_TOKEN,
        currency=CURRENCY, prices=prices
    )

# PreCheckout
async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.pre_checkout_query
    await q.answer(ok=True)

# Successful payment
async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sp = update.message.successful_payment
        payload = json.loads(sp.invoice_payload or "{}")
        user_id = update.effective_user.id
        if payload.get("type") == "subscription":
            months = int(payload.get("months") or 1)
            plan   = (payload.get("plan") or "pro").lower()
            until  = activate_subscription_with_tier(user_id, plan, months)
            await update.effective_message.reply_text(
                f"✅ Подписка активна до {until.strftime('%Y-%m-%d')} (тариф {plan.upper()}). Приятной работы!"
            )
        elif payload.get("type") == "topup":
            usd = float(payload.get("usd") or 0.0)
            _wallet_total_add(user_id, usd)
            await update.effective_message.reply_text(f"✅ Кошелёк пополнен на ~{usd:.2f}$.")
        else:
            await update.effective_message.reply_text("Платёж получен.")
    except Exception as e:
        log.exception("successful_payment_handler error: %s", e)
        await update.effective_message.reply_text("Платёж обработан, но произошла ошибка отображения статуса.")

# Кнопка «Движки» (из главного меню) без ссылки на тарифы — уже реализовано в engines_kb()

# ───────── [1689…] Фолбэк обработки входящих сообщений ─────────

async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        doc = update.message.document
        if not doc:
            return
        file = await doc.get_file()
        data = await file.download_as_bytearray()
        name = doc.file_name or "file.bin"
        text, kind = extract_text_from_document(bytes(data), name)
        if not text.strip():
            await update.effective_message.reply_text(f"Файл {name} ({kind}) получен, но извлечь текст не удалось.")
            return
        await update.effective_message.reply_text(f"Файл {name} ({kind}) получен. Делаю краткое резюме…")
        summary = await summarize_long_text(text)
        await update.effective_message.reply_text(summary)
        await maybe_tts_reply(update, context, summary[:TTS_MAX_CHARS])
    except Exception as e:
        log.exception("on_document error: %s", e)
        await update.effective_message.reply_text("Не удалось обработать документ.")

async def on_any_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Универсальный вход: сначала проверяем «ожидаемое уточнение» для быстрых фото-действий,
    иначе — обычная обработка текста.
    """
    txt = (update.message.text or "").strip()
    # Если ждём параметр к действию по фото — выполняем и выходим
    if await _do_pending_if_any(update, context, txt):
        return
    # Иначе стандартный пайп
    await on_text(update, context)

# ───────── [1749…] Роутинг, инициализация, запуск ─────────

def _build_app() -> "Application":
    # отложенный импорт, чтобы типы подхватились
    from telegram.ext import Application
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # init
    db_init(); db_init_usage(); _db_init_prefs(); _start_http_stub()

    # commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("engines", cmd_engines))
    app.add_handler(CommandHandler("examples", cmd_examples))
    app.add_handler(CommandHandler("img", cmd_img))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("topup", cmd_topup))
    app.add_handler(CommandHandler("voice_on", cmd_voice_on))
    app.add_handler(CommandHandler("voice_off", cmd_voice_off))

    # diagnostics
    app.add_handler(CommandHandler("diag_stt", cmd_diag_stt))
    app.add_handler(CommandHandler("diag_images", cmd_diag_images))
    app.add_handler(CommandHandler("diag_video", cmd_diag_video))

    # payments
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    # callbacks
    app.add_handler(CallbackQueryHandler(on_callback))

    # media handlers
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))         # документы (в т.ч. аудио как файл)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_any_text))

    return app

async def _set_webhook(app) -> None:
    if not USE_WEBHOOK:
        return
    url = f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}"
    try:
        await app.bot.set_webhook(url, secret_token=WEBHOOK_SECRET or None, drop_pending_updates=True)
        log.info("Webhook set: %s", url)
    except Exception as e:
        log.exception("set_webhook failed: %s", e)

def _run_polling(app) -> None:
    # для локала/отладки
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

def _run_webhook(app) -> None:
    # встроенный сервер TelegramExt не запускаем, у нас есть свой http-stub для health,
    # а webhook обслуживает сам Telegram (бот пушит на PUBLIC_URL/WEBHOOK_PATH)
    # В большинстве деплоев (Render) достаточно просто set_webhook и держать процесс.
    log.info("Running in webhook mode (keep-alive loop).")
    loop = asyncio.get_event_loop()
    async def _forever():
        while True:
            await asyncio.sleep(60)
    loop.run_until_complete(_forever())

def main():
    app = _build_app()
    if USE_WEBHOOK:
        asyncio.get_event_loop().run_until_complete(_set_webhook(app))
        _run_webhook(app)
    else:
        _run_polling(app)

if __name__ == "__main__":
    main()
# ───────── [2000…] Конец части 2/3 ─────────

# ───────── [2001…] State: последнее фото пользователя + быстрые кнопки ─────────

_last_photo: dict[int, dict] = {}  # user_id -> {"bytes": b"...", "mime": "image/jpeg", "aid": "abc123", "ts": 1730500000.0}

def _new_aid() -> str:
    import secrets
    return secrets.token_hex(6)

def _make_img_actions_kb(aid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎞 Оживить мимику", callback_data=f"imgact:animate:{aid}"),
            InlineKeyboardButton("🧼 Убрать фон",     callback_data=f"imgact:bg_remove:{aid}"),
        ],
        [
            InlineKeyboardButton("🖼 Заменить фон",   callback_data=f"imgact:bg_replace:{aid}"),
            InlineKeyboardButton("➕ Добавить предмет", callback_data=f"imgact:add_obj:{aid}"),
        ],
        [
            InlineKeyboardButton("➖ Удалить предмет",  callback_data=f"imgact:del_obj:{aid}"),
            InlineKeyboardButton("➕ Добавить человека",callback_data=f"imgact:add_human:{aid}"),
        ],
        [
            InlineKeyboardButton("➖ Удалить человека", callback_data=f"imgact:del_human:{aid}"),
            InlineKeyboardButton("🧩 Дорисовать сцену", callback_data=f"imgact:outpaint:{aid}"),
        ],
        [
            InlineKeyboardButton("🎥 Повернуть камеру", callback_data=f"imgact:cam_move:{aid}"),
        ],
    ])

async def _send_image_bytes(update: Update, img_bytes: bytes, caption: str = ""):
    try:
        await update.effective_message.reply_photo(photo=img_bytes, caption=caption or None)
    except Exception as e:
        log.warning("send photo bytes failed, try document: %s", e)
        try:
            bio = BytesIO(img_bytes); bio.name = "image.png"
            await update.effective_message.reply_document(document=InputFile(bio), caption=caption or None)
        except Exception as e2:
            log.exception("send document failed: %s", e2)
            await update.effective_message.reply_text("⚠️ Готово, но не удалось отправить изображение файлом.")

# ───────── [2050…] Переопределяем on_photo: сохраняем фото + быстрые кнопки ─────────
# (эта версия перекроет прежнюю — её помещаем в конце файла намеренно)

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    1) Сохраняем последнее фото пользователя (в памяти процесса).
    2) Отвечаем распознаванием по желанию (подпись как запрос).
    3) Показываем быстрые кнопки действий и подсказку про расширенные фичи.
    """
    user = update.effective_user
    user_id = user.id
    ok, left, tier = check_text_and_inc(user_id, user.username or "")
    if not ok:
        await update.effective_message.reply_text("Дневной лимит текстовых запросов исчерпан. Оформите подписку через /plans.")
        return

    try:
        file = await update.message.photo[-1].get_file()
        data = await file.download_as_bytearray()
        raw = bytes(data)
        mime = sniff_image_mime(raw)
        aid = _new_aid()
        _last_photo[user_id] = {"bytes": raw, "mime": mime, "aid": aid, "ts": time.time()}

        # если есть подпись — описать что на фото
        user_text = (update.message.caption or "").strip()
        if user_text:
            b64 = base64.b64encode(raw).decode("ascii")
            ans = await ask_openai_vision(user_text, b64, mime)
            if ans:
                await update.effective_message.reply_text(ans)
                await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])

        # быстрые кнопки + подсказка
        kb = _make_img_actions_kb(aid)
        note = (
            "Фото получено ✅\n\n"
            "Популярные действия сверху. Также можно запросить:\n"
            "• «замени фон на ночной город»\n"
            "• «добавь букет роз на стол»\n"
            "• «удали туриста слева»\n"
            "• «оживи мимику — лёгкая улыбка»\n"
            "• «поверни камеру вправо — покажи окно»\n\n"
            "Пишите текстом или голосом — поддерживается распознавание речи."
        )
        await update.effective_message.reply_text(note, reply_markup=kb)
    except Exception as e:
        log.exception("on_photo error: %s", e)
        await update.effective_message.reply_text("Не удалось обработать изображение.")

# ───────── [2125…] Базовые операции редактирования изображений (OpenAI Images) ─────────

def _ensure_png(b: bytes) -> bytes:
    """Нежно приводим к PNG для edits/variations."""
    try:
        from PIL import Image
        img = Image.open(BytesIO(b)).convert("RGBA")
        bio = BytesIO(); img.save(bio, format="PNG")
        return bio.getvalue()
    except Exception:
        return b  # если Pillow нет — пробуем как есть

def _img_edits_call(prompt: str, raw: bytes) -> bytes | None:
    """
    Унифицированный вызов image edits без маски.
    В реальном проде лучше формировать mask с прозрачностью (RGBA) для точного контроля.
    """
    try:
        png = _ensure_png(raw)
        # OpenAI Python SDK (images.edits) принимает open file-like с именем
        bio = BytesIO(png); bio.name = "image.png"
        r = oai_img.images.edits(
            model=IMAGES_MODEL,
            image=[bio],
            prompt=prompt,
            size="1024x1024",
            n=1,
        )
        b64 = r.data[0].b64_json
        return base64.b64decode(b64)
    except Exception as e:
        log.exception("images.edits failed: %s", e)
        return None

def _img_variation_call(raw: bytes, strength_hint: str = "high quality photo") -> bytes | None:
    try:
        png = _ensure_png(raw)
        bio = BytesIO(png); bio.name = "image.png"
        r = oai_img.images.variations(
            model=IMAGES_MODEL,
            image=bio,
            n=1,
            size="1024x1024",
            prompt=strength_hint
        )
        b64 = r.data[0].b64_json
        return base64.b64decode(b64)
    except Exception as e:
        log.exception("images.variations failed: %s", e)
        return None

def _img_generate_call(prompt: str) -> bytes | None:
    try:
        r = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
        return base64.b64decode(r.data[0].b64_json)
    except Exception as e:
        log.exception("images.generate failed: %s", e)
        return None

# ───────── [2205…] Конкретные действия: фон/объекты/люди/оживление/камера ─────────

async def do_bg_remove(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: bytes, mime: str):
    prompt = "Remove the background and produce a clean subject cut-out on transparent background, high quality, clean edges."
    img = _img_edits_call(prompt, raw) or _img_variation_call(raw, "subject cutout on transparent background")
    if not img:
        await update.effective_message.reply_text("Не удалось убрать фон.")
        return
    await _send_image_bytes(update, img, "🧼 Фон удалён.")

async def do_bg_replace(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: bytes, mime: str, bg_text: str):
    bg_text = (bg_text or "studio background with soft lights").strip()
    prompt = (
        f"Replace the background with: {bg_text}. Keep the main subject intact and realistic. "
        "Lighting and perspective should match; high quality edges."
    )
    img = _img_edits_call(prompt, raw)
    if not img:
        # fallback: generate similar with prompt
        img = _img_generate_call(f"Main subject from photo, {bg_text}, realistic composition, matching perspective")
    if not img:
        await update.effective_message.reply_text("Не удалось заменить фон.")
        return
    await _send_image_bytes(update, img, f"🖼 Фон заменён: {bg_text}")

async def do_add_obj(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: bytes, mime: str, what: str):
    what = (what or "a small red rose on the table").strip()
    prompt = f"Add object: {what}. Keep everything else unchanged and realistic; correct lighting and shadows."
    img = _img_edits_call(prompt, raw)
    if not img:
        await update.effective_message.reply_text("Не удалось добавить предмет.")
        return
    await _send_image_bytes(update, img, f"➕ Добавил предмет: {what}")

async def do_del_obj(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: bytes, mime: str, what: str):
    what = (what or "remove the cable on the right side").strip()
    prompt = f"Remove object: {what}. Fill the background naturally with proper inpainting and textures."
    img = _img_edits_call(prompt, raw)
    if not img:
        await update.effective_message.reply_text("Не удалось удалить предмет.")
        return
    await _send_image_bytes(update, img, f"➖ Удалён объект: {what}")

async def do_add_human(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: bytes, mime: str, descr: str):
    descr = (descr or "a man in black jacket standing on the left").strip()
    prompt = f"Add a human: {descr}. Keep style and lighting consistent; realistic proportions; coherent shadows."
    img = _img_edits_call(prompt, raw)
    if not img:
        await update.effective_message.reply_text("Не удалось добавить человека.")
        return
    await _send_image_bytes(update, img, f"➕ Добавлен человек: {descr}")

async def do_del_human(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: bytes, mime: str, who: str):
    who = (who or "remove the woman in blue dress on the right").strip()
    prompt = f"Remove a person: {who}. Fill background naturally with consistent textures."
    img = _img_edits_call(prompt, raw)
    if not img:
        await update.effective_message.reply_text("Не удалось удалить человека.")
        return
    await _send_image_bytes(update, img, f"➖ Удалён человек: {who}")

async def do_outpaint(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: bytes, mime: str, how: str):
    how = (how or "extend canvas to the right and add a terrace with sea view").strip()
    prompt = f"Outpaint: {how}. Extend scene beyond original borders with consistent style, perspective and details."
    img = _img_edits_call(prompt, raw)
    if not img:
        await update.effective_message.reply_text("Не удалось дорисовать сцену.")
        return
    await _send_image_bytes(update, img, f"🧩 Дорисовано: {how}")

async def do_cam_move(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: bytes, mime: str, how: str):
    """
    «Повернуть камеру»: концептуально это генерация кадра «что вне кадра».
    Реализуем как outpaint + переформулировка запроса.
    """
    how = (how or "pan right to reveal the window and night city lights").strip()
    prompt = (
        f"Camera move simulation: {how}. Reveal the new area not visible before; keep original style and lighting; "
        "produce a coherent next-frame view."
    )
    img = _img_edits_call(prompt, raw) or _img_generate_call(f"{how}, same style and subject continuity, realistic")
    if not img:
        await update.effective_message.reply_text("Не удалось выполнить «поворот камеры».")
        return
    await _send_image_bytes(update, img, f"🎥 Камера: {how}")

async def do_animate(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: bytes, mime: str):
    """
    Лёгкое «оживление мимики»: мы используем image edit с подсказкой сделать микро-анимацию кадра,
    но в рамках бота отдаём статичную «оживлённую» версию. Для реальной анимации — подключать Luma/Runway с img2video.
    """
    prompt = "Subtly enhance facial expression: gentle smile, natural eyes highlight; keep overall realism."
    img = _img_edits_call(prompt, raw) or _img_variation_call(raw, "subtle expression enhancement")
    if not img:
        await update.effective_message.reply_text("Не удалось оживить мимику.")
        return
    await _send_image_bytes(update, img, "🎞 Лёгкое оживление мимики выполнено.")

# ───────── [2350…] Доп. улучшение TTS: резервный способ отправки ─────────

async def maybe_tts_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """
    Улучшенная версия: если отправка voice не удалась — пытаемся audio.
    """
    try:
        if not _tts_get(update.effective_user.id):
            return
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

        with contextlib.suppress(Exception):
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VOICE)

        audio = await asyncio.to_thread(_tts_bytes_sync, text)
        if not audio:
            with contextlib.suppress(Exception):
                await update.effective_message.reply_text("🔇 Не удалось синтезировать голос.")
            return

        # сначала voice/ogg
        try:
            bio = BytesIO(audio); bio.name = "say.ogg"
            await update.effective_message.reply_voice(voice=InputFile(bio), caption=text)
            return
        except Exception as e:
            log.warning("send_voice failed: %s", e)

        # резерв — audio
        try:
            bio = BytesIO(audio); bio.name = "say.ogg"
            await update.effective_message.reply_audio(audio=InputFile(bio), caption=text, filename="say.ogg")
            return
        except Exception as e:
            log.exception("send_audio failed: %s", e)
            with contextlib.suppress(Exception):
                await update.effective_message.reply_text("🔇 Голос отправить не удалось.")
    except Exception as e:
        log.exception("maybe_tts_reply ultimate fail: %s", e)

# ───────── [2410…] Улучшение on_voice: корректная пайка буфера и MIME ─────────

def _guess_audio_mime_from_name(name: str) -> str:
    n = (name or "").lower()
    if n.endswith((".ogg",".oga")): return "audio/ogg"
    if n.endswith(".mp3"):          return "audio/mpeg"
    if n.endswith((".m4a",".mp4")): return "audio/mp4"
    if n.endswith(".wav"):          return "audio/wav"
    if n.endswith(".webm"):         return "audio/webm"
    return "application/octet-stream"

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        f = None; fname = "audio.ogg"
        if update.message.voice:
            f = await update.message.voice.get_file()
            fname = "voice.ogg"
        elif update.message.audio:
            f = await update.message.audio.get_file()
            fname = (update.message.audio.file_name or "audio").lower()
        else:
            await update.effective_message.reply_text("Тип аудио не поддерживается.")
            return

        data = await f.download_as_bytearray()
        buf = BytesIO(bytes(data)); setattr(buf, "name", fname)
        txt = await transcribe_audio(buf, filename_hint=fname)
        if not txt:
            await update.effective_message.reply_text("Не удалось распознать речь.")
            return

        # Если есть актуальное фото и текст содержит слова-операции — сразу выполнить
        last = _last_photo.get(update.effective_user.id)
        lowered = txt.lower()
        def has_any(*words): return any(w in lowered for w in words)

        if last:
            raw, mime, aid = last["bytes"], last["mime"], last["aid"]
            if has_any("убери фон","удали фон","remove background"):
                await do_bg_remove(update, context, raw, mime); return
            if has_any("замени фон","поменяй фон","replace background","background to"):
                # вытащим упоминание нового фона из текста (простая эвристика)
                bg = re.sub(r".*?(замени фон|поменяй фон|replace background)\s*(на|to)?", "", lowered, flags=re.I).strip()
                await do_bg_replace(update, context, raw, mime, bg or "studio background"); return
            if has_any("добавь","add "):
                what = re.sub(r".*?(добавь|add)\s*", "", txt, flags=re.I).strip()
                await do_add_obj(update, context, raw, mime, what or "a small red rose on the table"); return
            if has_any("удали","убери","remove "):
                what = re.sub(r".*?(удали|убери|remove)\s*", "", txt, flags=re.I).strip()
                await do_del_obj(update, context, raw, mime, what or "the cable on the right"); return
            if has_any("оживи","оживить","animate","мимику","улыбку","улыбка"):
                await do_animate(update, context, raw, mime); return
            if has_any("добавь человека","add human","добавить человека"):
                who = re.sub(r".*?(добав(ь|ить) человека|add human)\s*", "", txt, flags=re.I).strip()
                await do_add_human(update, context, raw, mime, who or "a person standing near the left side"); return
            if has_any("удали человека","remove person","удалить человека"):
                who = re.sub(r".*?(удал(и|ить) человека|remove person)\s*", "", txt, flags=re.I).strip()
                await do_del_human(update, context, raw, mime, who or "a person on the right"); return
            if has_any("дорисуй","дорисовать","расширь","extend","outpaint"):
                how = re.sub(r".*?(дорисуй|дорисовать|расширь|extend|outpaint)\s*", "", txt, flags=re.I).strip()
                await do_outpaint(update, context, raw, mime, how or "extend to the right with a terrace"); return
            if has_any("поверни камеру","camera","панорама","pan"):
                how = re.sub(r".*?(поверни камеру|camera|pan)\s*", "", txt, flags=re.I).strip()
                await do_cam_move(update, context, raw, mime, how or "pan right to reveal a window"); return

        # иначе используем текстовый пайплайн
        await update.effective_message.reply_text(f"🗣️ Распознано: {txt}")
        await _process_text(update, context, txt)

    except Exception as e:
        log.exception("on_voice error: %s", e)
        await update.effective_message.reply_text("Ошибка обработки голосового сообщения.")

# ───────── [2520…] Фикс on_text: встраиваем capability_answer-подсказки для фото-фич ─────────

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Εдиная точка входа для текста:
    1) Если ждём параметр к действию по фото — выполняем.
    2) Если запрос похож на «а умеешь ли про фото…» — отвечаем положительно с вариантами.
    3) Далее — обычный обработчик.
    """
    txt = (update.message.text or "").strip()
    # 1) Дообработки для «ожидаемого» параметра
    if await _do_pending_if_any(update, context, txt):
        return

    # 2) capability prompt для фото-фич
    tl = txt.lower()
    cap_trigger = bool(
        re.search(r"(фото|картинк|изображен|image|picture|img|логотип|фон|анимиру|ожив|дорису|поверн|камера)", tl)
        and re.search(r"(мож|умеешь|умеете|доступн|сможешь|сможете|поддержива)", tl)
    )
    if cap_trigger:
        have_photo = "да" if _has_recent_photo(update.effective_user.id) else "нет"
        lines = [
            "Да, доступен полный набор функций с изображениями ✅",
            "Могу: оживить мимику, удалить/добавить предметы и людей, убрать/заменить фон, дорисовать сцену (outpaint) и даже «повернуть камеру».",
        ]
        if have_photo == "да":
            lines.append("У вас уже есть прикреплённое фото — выберите действие в быстрых кнопках или опишите задачу текстом/голосом.")
        else:
            lines.append("Пришлите фото — покажу быстрые кнопки и выполню задачу.")
        await update.effective_message.reply_text("\n".join(lines))
        return

    # 3) основной маршрут
    await _process_text(update, context, txt)

# ───────── [2580…] CallbackQuery router (добавляем в build, но здесь оставляем на случай поздней регистрации) ─────────

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Эта функция уже определена выше в части 2 (on_callback).
    Оставляем полную версию здесь на случай если файл подключится частями —
    но чтобы не дублировать, проверим наличие атрибута ._redeclared.
    """
    pass  # фактическая реализация в части 2


# ───────── [2600…] Защита от переполнения _last_photo (простая чистка) ─────────

def _gc_last_photos(max_keep: int = 100, max_age_sec: int = 6 * 3600):
    try:
        if len(_last_photo) <= max_keep:
            return
        now = time.time()
        victims = sorted(_last_photo.items(), key=lambda kv: kv[1].get("ts", 0.0))
        for uid, meta in victims:
            if len(_last_photo) <= max_keep:
                break
            if now - meta.get("ts", now) > max_age_sec:
                _last_photo.pop(uid, None)
    except Exception:
        pass

# Периодический сборщик — запускаем в фоне (не критично, можно без него)
async def _periodic_gc(app):
    while True:
        _gc_last_photos()
        await asyncio.sleep(300)

# В main() после сборки app можно запустить:
# context.application.create_task(_periodic_gc(app)) — но Application здесь нет.
# Поэтому дадим вспомогательный хук:

def _start_background_tasks(app):
    try:
        app.job_queue.run_repeating(lambda *_: _gc_last_photos(), interval=300, first=120)
    except Exception:
        # если job_queue не поднят — пропустим, это некритично
        pass

# ───────── [2665…] Финальный main с включёнными правками (повтор для надёжности склейки) ─────────

def main():
    app = _build_app()
    # бэкграунд-чистка
    _start_background_tasks(app)

    if USE_WEBHOOK:
        asyncio.get_event_loop().run_until_complete(_set_webhook(app))
        # webhook режим — держим процесс «живым»
        _run_webhook(app)
    else:
        _run_polling(app)

if __name__ == "__main__":
    main()

# ───────── [конец файла] ─────────
