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
    LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove, ForceReply
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

# External image tools (optional)
REMOVE_BG_API_KEY   = os.environ.get("REMOVE_BG_API_KEY", "").strip()  # for bg remove/replace

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
    # CryptoBot pending subs
    cur.execute("""
    CREATE TABLE IF NOT EXISTS crypto_subs (
        invoice_id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        tier TEXT NOT NULL,
        months INTEGER NOT NULL,
        usd_amount REAL DEFAULT 0.0,
        created_ts INTEGER NOT NULL,
        done INTEGER DEFAULT 0
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

def _tts_bytes_sync_http(text: str) -> bytes | None:
    """Фолбэк: прямой HTTP на /v1/audio/speech (Opus)."""
    try:
        url = f"{OPENAI_TTS_BASE_URL.rstrip('/')}/audio/speech"
        headers = {
            "Authorization": f"Bearer {OPENAI_TTS_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": OPENAI_TTS_MODEL,
            "voice": OPENAI_TTS_VOICE,
            "input": text,
            "format": "opus"
        }
        r = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        r.raise_for_status()
        return r.content if r.content else None
    except Exception as e:
        log.exception("TTS HTTP fallback error: %s", e)
        return None

def _tts_bytes_sync(text: str) -> bytes | None:
    # сначала SDK...
    try:
        r = oai_tts.audio.speech.create(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE, input=text, format="opus")
        audio = getattr(r, "content", None)
        if audio is None and hasattr(r, "read"):
            audio = r.read()
        if isinstance(audio, (bytes, bytearray)):
            return bytes(audio)
    except Exception as e:
        log.warning("TTS SDK error: %s", e)
    # ...затем HTTP-фолбэк
    return _tts_bytes_sync_http(text)

async def maybe_tts_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    if not _tts_get(user_id):
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

# ───────── Images (gen+edits) ─────────
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

# ======= Simple image edits helpers =======
async def _remove_bg_bytes(img_bytes: bytes) -> bytes | None:
    if not REMOVE_BG_API_KEY:
        return None
    try:
        headers = {"X-Api-Key": REMOVE_BG_API_KEY}
        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {"image_file": ("image.png", img_bytes, "application/octet-stream")}
            data = {"size": "auto", "format": "png"}
            r = await client.post("https://api.remove.bg/v1.0/removebg", headers=headers, data=data, files=files)
            if r.status_code == 200:
                return r.content
            log.warning("remove.bg status=%s, body=%s", r.status_code, r.text[:300])
    except Exception as e:
        log.exception("remove.bg error: %s", e)
    return None

async def _enhance_with_openai(img_bytes: bytes, hint: str = "enhance quality, details, sharpness") -> bytes | None:
    try:
        resp = oai_img.images.edits(
            model=IMAGES_MODEL,
            image=BytesIO(img_bytes),
            prompt=hint,
            size="1024x1024",
            n=1
        )
        b64 = resp.data[0].b64_json
        return base64.b64decode(b64)
    except Exception as e:
        log.exception("image enhance error: %s", e)
        return None

# ───────── UI / тексты ─────────
START_TEXT = (
    "Привет! Я GPT-бот с тарифами, квотами и разовыми пополнениями.\n\n"
    "Что умею:\n"
    "• 💬 Текст/фото (GPT)\n"
    "• 🎬 Видео Luma (5/9/10 c, 9:16/16:9)\n"
    "• 🎥 Видео Runway (PRO)\n"
    "• 🖼 Картинки — команда /img <промпт>\n"
    "• 📄 Анализ PDF/EPUB/DOCX/FB2/TXT — просто пришли файл.\n\n"
    "Открой «🎛 Движки», чтобы выбрать, и «⭐ Подписка» — для тарифов."
)

HELP_TEXT = (
    "Подсказки:\n"
    "• /plans — тарифы и оплата подписки (через чат или мини-приложение)\n"
    "• /img кот с очками — сгенерирует картинку\n"
    "• «сделай видео … 9 секунд 9:16» — Luma/Runway\n"
    "• «🎛 Движки» — выбрать GPT / Luma / Runway / Midjourney / Images / Docs\n"
    "• «🧾 Баланс» — кошелёк и пополнение (RUB или CryptoBot USDT/TON)\n"
    "• /voice_on и /voice_off — озвучка ответов."
)

EXAMPLES_TEXT = (
    "Примеры:\n"
    "• сделай видео ретро-авто на берегу, 9 секунд, 9:16\n"
    "• опиши текст на фото (пришли фото + подпись)\n"
    "• /img неоновый город в дождь, реализм\n"
    "• пришли PDF — сделаю тезисы и выводы"
)

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎛 Движки"), 
             KeyboardButton("⭐ Подписка")],
            [KeyboardButton("🧾 Баланс"), 
             KeyboardButton("ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
        input_field_placeholder="Напишите запрос или выберите пункт меню",
    )

main_kb = main_keyboard()

def engines_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 GPT (текст/фото/документы)", callback_data="engine:gpt")],
        [InlineKeyboardButton("🖼 Images (OpenAI)",             callback_data="engine:images")],
        [InlineKeyboardButton("🎬 Luma — короткие видео",       callback_data="engine:luma")],
        [InlineKeyboardButton("🎥 Runway — премиум-видео",      callback_data="engine:runway")],
        [InlineKeyboardButton("🎨 Midjourney (изображения)",    callback_data="engine:midjourney")],
        [InlineKeyboardButton("🗣 STT/TTS — речь↔текст",        callback_data="engine:stt_tts")],
        # Кнопка «Описание тарифов» убрана по твоей просьбе
    ])

# ───────── Router: text/photo/voice/docs/img/video ───────
def sniff_image_mime(b: bytes) -> str:
    if b.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if b[:3] == b"\xff\xd8\xff":         return "image/jpeg"
    if b[:6] == b"GIF87a" or b[:6] == b"GIF89a": return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":  return "image/webp"
    return "application/octet-stream"

# store last photo per user for edits
_last_photo: dict[int, bytes] = {}
_pending_edit: dict[int, dict] = {}  # user_id -> {"action": "replace_bg", "params":{}}

def _photo_tools_kb():
    rows = [
        [InlineKeyboardButton("✂️ Убрать фон", callback_data="img:remove_bg"),
         InlineKeyboardButton("🏖️ Заменить фон", callback_data="img:replace_bg")],
        [InlineKeyboardButton("✨ Улучшить качество", callback_data="img:enhance"),
         InlineKeyboardButton("🎞 Оживить фото", callback_data="img:animate")],
    ]
    return InlineKeyboardMarkup(rows)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    # обработка «ожидания текста» после кнопок редактирования фото
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
            # gpt-image-1 edits без mask: проксируем «замени фон на ...»
            resp = oai_img.images.edits(
                model=IMAGES_MODEL,
                image=BytesIO(img),
                prompt=f"Replace the background to: {text}. Keep the subject intact, clean edges.",
                size="1024x1024",
                n=1
            )
            b64 = resp.data[0].b64_json
            await update.effective_message.reply_photo(photo=base64.b64decode(b64), caption="Готово ✅")
        except Exception as e:
            log.exception("replace_bg edit error: %s", e)
            await update.effective_message.reply_text("Не удалось заменить фон.")
        return

    # обычная обработка текста
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
        _last_photo[user_id] = bytes(data)
        # если подпись содержит "оживи"
        cap = (update.message.caption or "").lower()
        if "ожив" in cap or "animate" in cap:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎞 Создать короткое видео (Luma)", callback_data="img:animate:luma")],
                [InlineKeyboardButton("🎥 Продвинутое видео (Runway)", callback_data="img:animate:runway")]
            ])
            await update.effective_message.reply_text("Выберите способ оживления:", reply_markup=kb)
            return
        # иначе показать инструменты
        await update.effective_message.reply_text("Что сделать с фото?", reply_markup=_photo_tools_kb())
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
        await _process_text(update, context, txt)
    except Exception as e:
        log.exception("Voice handler error: %s", e)
        await update.effective_message.reply_text("Ошибка обработки голосового сообщения.")

# документы: аудио-файлы как документ (mp3/m4a/wav/ogg/webм)
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

# ======= Core: документы =======
async def on_doc_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        doc = update.message.document
        f = await doc.get_file()
        data = await f.download_as_bytearray()
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
        await update.effective_message.reply_text("Ошибка при анализе документа.")

# ======= Text pipeline =======
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
        await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])
        return

    cap_ans = capability_answer(text)
    if cap_ans:
        await update.effective_message.reply_text(cap_ans)
        await maybe_tts_reply(update, context, cap_ans[:TTS_MAX_CHARS])
        return

    intent, clean = detect_media_intent(text)

    if intent == "image":
        async def _go():
            await _do_img_generate(update, context, clean or text)
        await _try_pay_then_do(
            update, context, user_id, "img", IMG_COST_USD, _go,
            remember_kind="img_generate",
            remember_payload={"prompt": clean or text}
        )
        return

    if intent == "video":
        dur, ar, prompt = parse_video_opts_from_text(
            clean or text,
            default_duration=LUMA_DURATION_S,
            default_ar=LUMA_ASPECT
        )
        aid = _new_aid()
        _pending_actions[aid] = {"prompt": prompt, "duration": dur, "aspect": ar}
        choose_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Luma",   callback_data=f"choose:luma:{aid}"),
             InlineKeyboardButton("🎥 Runway", callback_data=f"choose:runway:{aid}")]
        ])
        await update.effective_message.reply_text(
            f"Видео {dur}s • {ar}\nВыберите движок:",
            reply_markup=choose_kb
        )
        return

    # веб-контекст (опционально)
    web_ctx = ""
    try:
        if tavily and should_browse(text):
            r = tavily.search(query=text, max_results=4)
            if r and isinstance(r, dict):
                items = r.get("results") or r.get("results", [])
                lines = []
                for it in items or []:
                    t = (it.get("title") or "").strip()
                    s = (it.get("content") or it.get("snippet") or "").strip()
                    if t or s:
                        lines.append(f"- {t}: {s}")
                web_ctx = "\n".join(lines[:8])
    except Exception:
        pass

    ans = await ask_openai_text(text, web_ctx=web_ctx)
    if not ans or ans.strip() == "" or "не получилось получить ответ" in ans.lower():
        ans = "⚠️ Сейчас не удалось получить ответ от модели. Я всё равно на связи — попробуй переформулировать запрос или повторить через минуту."
    await update.effective_message.reply_text(ans)
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])

# ───────── Видео и отложенные действия ─────────
_pending_actions: dict[str, dict] = {}

def _new_aid() -> str:
    return uuid.uuid4().hex[:10]

def parse_video_opts_from_text(text: str, default_duration: int, default_ar: str) -> tuple[int, str, str]:
    t = text.lower()
    m = re.search(r"(\d{1,2})\s*(?:сек|с|sec|seconds?)", t)
    duration = int(m.group(1)) if m else default_duration
    duration = max(3, min(12, duration))
    ar = default_ar
    if re.search(r"\b9[:/]\s*16\b", t) or "9:16" in t:
        ar = "9:16"
    elif re.search(r"\b16[:/]\s*9\b", t) or "16:9" in t:
        ar = "16:9"
    elif re.search(r"\b1[:/]\s*1\b", t) or "1:1" in t:
        ar = "1:1"
    prompt = text.strip()
    return duration, ar, prompt

def _norm_ar(ar: str) -> str:
    ar = (ar or "").replace(" ", "").replace("/", ":")
    if ar in ("9:16","16:9","1:1"):
        return ar
    if ar in ("720:1280","1080:1920"): return "9:16"
    if ar in ("1280:720","1920:1080"): return "16:9"
    return "16:9"

def _safe_caption(prompt: str, engine: str, duration: int, ar: str) -> str:
    p = (prompt or "").strip()
    if len(p) > 500: p = p[:497] + "…"
    return f"✅ {engine} • {duration}s • {ar}\nЗапрос: {p}"

# ====== Luma helpers ======
try:
    _LUMA_LAST_BASE
except NameError:
    _LUMA_LAST_BASE: str | None = None
try:
    _LUMA_LAST_ERR
except NameError:
    _LUMA_LAST_ERR: str | None = None

def _luma_duration_string(seconds: int) -> str:
    allowed = [5, 9, 10]
    best = min(allowed, key=lambda x: abs(x - max(1, int(seconds))))
    return f"{best}s"

async def _luma_create(prompt: str, duration_s: int, ar: str) -> str | None:
    if not LUMA_API_KEY:
        raise RuntimeError("LUMA_API_KEY is missing")
    headers = {
        "Authorization": f"Bearer {LUMA_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LUMA_MODEL,
        "prompt": prompt,
        "duration": _luma_duration_string(duration_s),
        "aspect_ratio": _norm_ar(ar),
    }
    last_text = None
    async with httpx.AsyncClient(timeout=120.0) as client:
        candidates, seen = [], set()
        global _LUMA_LAST_ERR
        try:
            detected = await _pick_luma_base(client)
            if detected:
                b = detected.rstrip("/")
                if b and b not in seen:
                    candidates.append(b); seen.add(b)
        except Exception as e:
            log.warning("Luma: auto-detect base failed: %s", e)
        b = (LUMA_BASE_URL or "").strip().rstrip("/")
        if b and b not in seen:
            candidates.append(b); seen.add(b)
        for fb in LUMA_FALLBACKS:
            u = (fb or "").strip().rstrip("/")
            if u and u not in seen:
                candidates.append(u); seen.add(u)
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
                    global _LUMA_LAST_BASE
                    _LUMA_LAST_BASE = base
                    if base != LUMA_BASE_URL:
                        log.warning("Luma: switched base_url to %s (fallback worked)", base)
                    _LUMA_LAST_ERR = None
                    return str(job_id)
                log.error("Luma create: no job id in response from %s: %s", base, j)
                _LUMA_LAST_ERR = f"no_job_id from {base}: {j}"
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                log.error("Luma create HTTP %s at %s | body=%s", code, base, last_text)
                _LUMA_LAST_ERR = f"HTTP {code} at {base}: {last_text[:600]}"
            except httpx.RequestError as e:
                log.error("Luma create network/http error at %s: %s", base, e)
                _LUMA_LAST_ERR = f"network error at {base}: {e}"
            except Exception as e:
                log.error("Luma create unexpected error at %s: %s | body=%s", base, e, last_text)
                _LUMA_LAST_ERR = f"unexpected at {base}: {e}; body={str(last_text)[:600]}"
    return None

async def luma_get_status(task_id: str, base_hint: str | None = None) -> dict:
    if not LUMA_API_KEY:
        raise RuntimeError("LUMA_API_KEY is missing")
    async with httpx.AsyncClient() as client:
        base = (base_hint or _LUMA_LAST_BASE)
        if not base:
            base = await _pick_luma_base(client)
        base = base.rstrip("/")
        url = f"{base}{LUMA_STATUS_PATH}".format(id=task_id)
        r = await client.get(
            url,
            headers={"Authorization": f"Bearer {LUMA_API_KEY}", "Accept": "application/json"},
            timeout=20.0,
        )
        r.raise_for_status()
        return r.json()

async def _luma_poll_and_get_url(job_id: str, base_hint: str | None = None) -> tuple[str | None, str]:
    start = time.time()
    while time.time() - start < LUMA_MAX_WAIT_S:
        try:
            j = await luma_get_status(job_id, base_hint=base_hint)
        except Exception:
            await asyncio.sleep(VIDEO_POLL_DELAY_S)
            continue
        status = (j.get("status") or j.get("state") or "").lower()
        if status in ("queued", "processing", "in_progress", "running", "pending"):
            await asyncio.sleep(VIDEO_POLL_DELAY_S); continue
        if status in ("completed", "succeeded", "done", "finished", "success"):
            video_url = (
                j.get("result", {}).get("video_url")
                or j.get("result", {}).get("video")
                or j.get("assets", {}).get("video")
                or j.get("output", {}).get("url")
                or j.get("url")
                or j.get("video")
            )
            return (video_url, "completed")
        if status in ("failed", "error", "canceled"):
            return (None, status)
        await asyncio.sleep(VIDEO_POLL_DELAY_S)
    return (None, "timeout")

async def _run_luma_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration: int, ar: str):
    await update.effective_message.reply_text(
        f"✅ Запускаю Luma: {duration}s • {_norm_ar(ar)}\nЗапрос: {prompt}"
    )
    job_id = await _luma_create(prompt, duration, ar)
    if not job_id:
        msg = "⚠️ Не удалось создать задачу в Luma."
        if _LUMA_LAST_ERR:
            msg += f"\nПричина: {_LUMA_LAST_ERR}"
        await update.effective_message.reply_text(msg)
        return
    await update.effective_message.reply_text("⏳ Luma рендерит… Я пришлю видео как будет готово.")
    url, st = await _luma_poll_and_get_url(job_id, base_hint=_LUMA_LAST_BASE)
    if not url:
        await update.effective_message.reply_text(f"⚠️ Luma вернула статус: {st}.")
        return
    try:
        await update.effective_message.reply_video(
            video=url,
            caption=_safe_caption(prompt, "Luma", int(_luma_duration_string(duration)[:-1]), _norm_ar(ar)),
        )
    except Exception:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                r = await client.get(url)
                r.raise_for_status()
                bio = BytesIO(r.content); bio.name = "luma.mp4"
                await update.effective_message.reply_video(
                    video=InputFile(bio),
                    caption=_safe_caption(prompt, "Luma", int(_luma_duration_string(duration)[:-1]), _norm_ar(ar)),
                )
        except Exception as e:
            log.exception("send luma video failed: %s", e)
            await update.effective_message.reply_text("⚠️ Видео готово, но не удалось отправить файл.")

# ====== Runway helpers ======
async def _runway_create(prompt: str, duration_s: int, ratio: str) -> str | None:
    if not RUNWAY_API_KEY:
        raise RuntimeError("RUNWAY_API_KEY is missing")
    url = f"{RUNWAY_BASE_URL}{RUNWAY_CREATE_PATH}"
    headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": RUNWAY_MODEL,
        "input": {"prompt": prompt, "duration": max(1, int(duration_s)), "ratio": ratio}
    }
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

async def _runway_status(task_id: str) -> dict | None:
    if not RUNWAY_API_KEY:
        return None
    url = f"{RUNWAY_BASE_URL}{RUNWAY_STATUS_PATH}".format(id=task_id)
    headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.exception("Runway status error: %s", e)
        return None

async def _runway_poll_and_get_url(task_id: str) -> tuple[str | None, str]:
    start = time.time()
    while time.time() - start < RUNWAY_MAX_WAIT_S:
        j = await _runway_status(task_id)
        if not j:
            await asyncio.sleep(VIDEO_POLL_DELAY_S); continue
        status = (j.get("status") or "").upper()
        if status in ("PENDING","RUNNING","IN_PROGRESS","QUEUED"):
            await asyncio.sleep(VIDEO_POLL_DELAY_S); continue
        if status in ("SUCCEEDED","COMPLETED","SUCCESS"):
            out = j.get("output") or {}
            url = None
            if isinstance(out, dict):
                url = out.get("video_url") or (out.get("video") or (out.get("videos") or [None]))[0] if isinstance(out.get("videos"), list) else out.get("url")
            elif isinstance(out, list) and out:
                url = out[0]
            return url, "completed"
        if status in ("FAILED","CANCELED","ERROR"):
            return None, status
        await asyncio.sleep(VIDEO_POLL_DELAY_S)
    return None, "timeout"

async def _run_runway_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration: int, ar: str):
    await update.effective_message.reply_text(
        f"✅ Запускаю Runway: {duration}s • {_norm_ar(ar)}\nЗапрос: {prompt}"
    )
    tid = await _runway_create(prompt, duration, RUNWAY_RATIO)
    if not tid:
        await update.effective_message.reply_text("⚠️ Не удалось создать задачу в Runway.")
        return

    await update.effective_message.reply_text("⏳ Runway рендерит… Пришлю видео, как будет готово.")
    url, st = await _runway_poll_and_get_url(tid)
    if not url:
        await update.effective_message.reply_text(f"⚠️ Runway вернул статус: {st}.")
        return

    # сначала пытаемся отдать по URL (Telegram сам подтянет файл),
    # если не получится — скачиваем и шлём как InputFile
    try:
        await update.effective_message.reply_video(
            video=url,
            caption=_safe_caption(prompt, "Runway", duration, _norm_ar(ar)),
        )
    except Exception:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                r = await client.get(url)
                r.raise_for_status()
                bio = BytesIO(r.content)
                bio.name = "runway.mp4"
                await update.effective_message.reply_video(
                    video=InputFile(bio),
                    caption=_safe_caption(prompt, "Runway", duration, _norm_ar(ar)),
                )
        except Exception as e:
            log.exception("send runway video failed: %s", e)
            await update.effective_message.reply_text("⚠️ Видео готово, но не удалось отправить файл.")

# ───────── Telegram Payments: payload+инвойсы ─────────
def _payload_oneoff(engine: str, usd: float) -> str:
    e = {"luma": "l", "runway": "r", "img": "i"}.get(engine, "i")
    cents = int(round(float(usd) * 100))
    return f"t=1;e={e};u={cents}"

def _payload_subscribe(tier: str, months: int) -> str:
    s = {"start": "s", "pro": "p", "ultimate": "u"}.get((tier or "pro").lower(), "p")
    m = int(months or 1)
    return f"t=2;s={s};m={m}"

def _payload_parse(s: str) -> dict:
    out = {}
    for part in (s or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out

async def _send_invoice_rub(title: str, description: str, amount_rub: int, payload, update: Update):
    if not PROVIDER_TOKEN:
        await update.effective_message.reply_text("Провайдер платежей не настроен.")
        return False
    title = _ascii_label(title)
    description = (description or "")[:255]
    amount_rub = max(1, int(amount_rub))
    if isinstance(payload, dict):
        p_try = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        if len(p_try.encode("ascii", "ignore")) <= 128:
            payload_str = p_try
        else:
            kind = payload.get("t") or payload.get("type")
            if kind == "oneoff_topup":
                payload_str = _payload_oneoff(payload.get("engine", "img"), float(payload.get("usd", 0)))
            elif kind == "subscribe":
                payload_str = _payload_subscribe(payload.get("tier", "pro"), int(payload.get("months", 1)))
            else:
                payload_str = f"t=0;note={int(time.time())}"
    elif isinstance(payload, str):
        payload_str = payload[:128]
    else:
        payload_str = "t=0"

    prices = [LabeledPrice(label=title, amount=amount_rub * 100)]
    try:
        await update.effective_message.reply_invoice(
            title=title,
            description=description,
            payload=payload_str,
            provider_token=PROVIDER_TOKEN,
            currency=CURRENCY,
            prices=prices,
            is_flexible=False,
        )
        return True
    except TelegramError as e:
        log.exception("send_invoice error: %s", e)
        await update.effective_message.reply_text("Не удалось выставить счёт. Оформите подписку через /plans.")
        return False

# ───────── CryptoBot (Crypto Pay API) ─────────
CRYPTO_PAY_API_TOKEN = os.environ.get("CRYPTO_PAY_API_TOKEN","").strip()
CRYPTO_ASSET_DEFAULT = os.environ.get("CRYPTO_ASSET_DEFAULT","USDT").strip().upper()  # USDT или TON
TON_USD_RATE         = float(os.environ.get("TON_USD_RATE","6.0") or "6.0")

async def _crypto_api(method: str, payload: dict) -> dict | None:
    if not CRYPTO_PAY_API_TOKEN:
        return None
    url = f"https://pay.crypt.bot/api/{method}"
    headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(url, headers=headers, json=payload)
            j = r.json()
            if not j.get("ok"):
                log.warning("CryptoPay %s failed: %s", method, j)
            return j
    except Exception as e:
        log.exception("CryptoPay error: %s", e)
        return None

async def _crypto_create_invoice(usd_amount: float, asset: str|None=None, description: str="Wallet top-up") -> tuple[str|None,str|None,float,str|None]:
    asset = (asset or CRYPTO_ASSET_DEFAULT).upper()
    if asset not in ("USDT","TON"):
        asset = "USDT"
    amount_asset = float(usd_amount) if asset=="USDT" else float(usd_amount)/max(1e-9, TON_USD_RATE)
    j = await _crypto_api("createInvoice", {
        "asset": asset,
        "amount": round(amount_asset, 2),
        "description": description,
        "expires_in": 900,  # 15 мин
        "allow_comments": False,
        "allow_anonymous": True
    })
    if not j or not j.get("ok"):
        return None, None, 0.0, None
    res = j.get("result") or {}
    invoice_id = str(res.get("invoice_id"))
    pay_url    = res.get("pay_url")
    return invoice_id, pay_url, float(usd_amount), asset

async def _crypto_get_invoice(invoice_id: str) -> dict | None:
    j = await _crypto_api("getInvoices", {"invoice_ids":[invoice_id]})
    if not j or not j.get("ok"):
        return None
    lst = (j.get("result") or {}).get("items") or []
    return lst[0] if lst else None

async def _poll_crypto_invoice(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, user_id: int, invoice_id: str, usd_amount: float):
    deadline = time.time() + 900
    while time.time() < deadline:
        await asyncio.sleep(6.0)
        inv = await _crypto_get_invoice(invoice_id)
        if not inv:
            continue
        st = (inv.get("status") or "").lower()  # active, paid, expired
        if st == "paid":
            _wallet_total_add(user_id, usd_amount)
            with contextlib.suppress(Exception):
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id,
                    text=f"💳 Оплата через CryptoBot зачислена: ≈ ${usd_amount:.2f}. Баланс пополнен."
                )
            return
        if st == "expired":
            with contextlib.suppress(Exception):
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id,
                    text="⏳ Ссылка CryptoBot истекла. Попробуйте создать новую."
                )
            return
    with contextlib.suppress(Exception):
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text="⏳ Время ожидания оплаты истекло. Если оплатили — нажмите «Проверить оплату»."
        )

# ───────── TopUp / TryPay ─────────
async def _try_pay_then_do(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    engine: str,
    est_cost_usd: float,
    coroutine_to_run,
    remember_kind: str = "",
    remember_payload: dict | None = None,
):
    if is_unlimited(user_id, (update.effective_user.username or "")):
        await coroutine_to_run(); return
    if engine not in ("luma", "runway", "img"):
        await coroutine_to_run(); return

    ok, offer = _can_spend_or_offer(user_id, (update.effective_user.username or ""), engine, est_cost_usd)
    if ok:
        await coroutine_to_run(); return

    if offer == "ASK_SUBSCRIBE":
        await update.effective_message.reply_text(
            "Для этого действия нужна подписка либо единый баланс. Открой /plans или пополни «🧾 Баланс».",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
                 [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
            ),
        )
        return

    try:
        need_usd = float(offer.split(":", 1)[-1])
    except Exception:
        need_usd = est_cost_usd
    amount_rub = _calc_oneoff_price_rub(engine, need_usd)
    title = f"{engine.upper()} пополнение"
    desc = f"Пополнение бюджета для {engine} на ${need_usd:.2f} (≈ {amount_rub} ₽)."
    payload = _payload_oneoff(engine, need_usd)
    await _send_invoice_rub(title, desc, amount_rub, payload, update)

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.pre_checkout_query.answer(ok=True)
    except Exception as e:
        log.exception("precheckout error: %s", e)

async def on_success_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pay = update.message.successful_payment
        raw = pay.invoice_payload or ""
        kv = _payload_parse(raw)
        t = kv.get("t", "")

        if t == "1":
            e = kv.get("e", "i")
            engine = {"l": "luma", "r": "runway", "i": "img"}.get(e, "img")
            cents = int(kv.get("u", "0") or 0)
            usd = cents / 100.0
            _wallet_add(update.effective_user.id, engine, usd)
            await update.effective_message.reply_text("💳 Оплата прошла! Бюджет пополнён, можно запускать задачу снова.")
            return

        if t == "2":
            tier = {"s": "start", "p": "pro", "u": "ultimate"}.get(kv.get("s", "p"), "pro")
            months = int(kv.get("m", "1") or 1)
            until = activate_subscription_with_tier(update.effective_user.id, tier, months)
            await update.effective_message.reply_text(f"⭐ Подписка активна до {until.strftime('%Y-%m-%d')}. Тариф: {tier}.")
            return

        if t == "3":
            try:
                amt_rub = (update.message.successful_payment.total_amount or 0) / 100.0
            except Exception:
                amt_rub = 0.0
            usd = float(amt_rub) / max(1e-9, USD_RUB)
            _wallet_total_add(update.effective_user.id, usd)
            await update.effective_message.reply_text(f"💳 Баланс пополнен на {amt_rub:.2f} ₽ (≈ ${usd:.2f}).")
            return

        # JSON payload (на всякий)
        try:
            payload = json.loads(raw)
            if payload.get("t") == "subscribe":
                until = activate_subscription_with_tier(
                    update.effective_user.id,
                    payload.get("tier", "pro"),
                    int(payload.get("months", 1)),
                )
                await update.effective_message.reply_text(f"⭐ Подписка активна до {until.strftime('%Y-%m-%d')}.")
                return
            if payload.get("t") == "oneoff_topup":
                _wallet_add(update.effective_user.id, payload.get("engine", "img"), float(payload.get("usd", 0)))
                await update.effective_message.reply_text("💳 Оплата прошла! Бюджет пополнён.")
                return
        except Exception:
            pass

        await update.effective_message.reply_text("✅ Платёж принят.")
    except Exception as e:
        log.exception("on_success_payment error: %s", e)
        await update.effective_message.reply_text("Ошибка обработки платежа.")

# --- /plans ---
def _plan_rub(tier: str, term: str) -> int:
    return int(PLAN_PRICE_TABLE[tier][term])

def _plan_payload_and_amount(tier: str, months: int) -> tuple[str, int, str]:
    term_label = {1: "мес", 3: "квартал", 12: "год"}.get(months, f"{months} мес")
    amount = _plan_rub(tier, {1: "month", 3: "quarter", 12: "year"}[months])
    payload = _payload_subscribe(tier, months)
    title = f"Подписка {tier.upper()}/{term_label}"
    return payload, amount, title

def _plan_mechanics_text() -> str:
    return (
        "📋 Как работают лимиты и кошелёк:\n"
        "• FREE — демо: 5 текстов/день, 1× Luma (до $0.40) и 1× картинка (до $0.05).\n"
        "• START — больше текстов + небольшие бюджеты на медиа.\n"
        "• PRO/ULTIMATE — расширенные бюджеты Luma/Runway/Images.\n"
        "• Если исчерпан дневной бюджет по движку, сверхлимит списывается с «Единого кошелька» (USD).\n"
        "• Кошелёк пополняется в рублях (ЮKassa) или в USDT/TON через CryptoBot.\n"
        "• Разовые списания рассчитываются по фактической себестоимости движка с наценкой.\n"
    )

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["⭐ Тарифы и оформление подписки:"]
    for t in ("start", "pro", "ultimate"):
        p = PLAN_PRICE_TABLE[t]
        lines.append(f"• {t.upper()}: {p['month']}₽/мес • {p['quarter']}₽/квартал • {p['year']}₽/год")
    lines.append("")
    lines.append(_plan_mechanics_text())
        kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("START — месяц",  callback_data="buy:start:1"),
         InlineKeyboardButton("квартал",        callback_data="buy:start:3"),
         InlineKeyboardButton("год",            callback_data="buy:start:12")],
        [InlineKeyboardButton("PRO — месяц",    callback_data="buy:pro:1"),
         InlineKeyboardButton("квартал",        callback_data="buy:pro:3"),
         InlineKeyboardButton("год",            callback_data="buy:pro:12")],
        [InlineKeyboardButton("ULTIMATE — мес", callback_data="buy:ultimate:1"),
         InlineKeyboardButton("квартал",        callback_data="buy:ultimate:3"),
         InlineKeyboardButton("год",            callback_data="buy:ultimate:12")],
        # crypto-варианты
        [InlineKeyboardButton("START (Crypto) месяц",  callback_data="buyc:start:1"),
         InlineKeyboardButton("квартал",               callback_data="buyc:start:3"),
         InlineKeyboardButton("год",                   callback_data="buyc:start:12")],
        [InlineKeyboardButton("PRO (Crypto) месяц",    callback_data="buyc:pro:1"),
         InlineKeyboardButton("квартал",               callback_data="buyc:pro:3"),
         InlineKeyboardButton("год",                   callback_data="buyc:pro:12")],
        [InlineKeyboardButton("ULTIMATE (Crypto) мес", callback_data="buyc:ultimate:1"),
         InlineKeyboardButton("квартал",               callback_data="buyc:ultimate:3"),
         InlineKeyboardButton("год",                   callback_data="buyc:ultimate:12")],
        [InlineKeyboardButton("Открыть страницу тарифов (мини-приложение)", web_app=WebAppInfo(url=TARIFF_URL))],
    ])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb, disable_web_page_preview=True)

# ===== Пополнение кошелька =====
def _make_topup_webapp_url(amount: int | None = None):
    base = _make_tariff_url(src="topup")
    if amount:
        sep = "&" if "?" in base else "?"
        base = f"{base}{sep}amount={int(amount)}"
    return base

async def _send_topup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("100 ₽",  callback_data="topup:rub:100"),
            InlineKeyboardButton("500 ₽",  callback_data="topup:rub:500"),
            InlineKeyboardButton("1000 ₽", callback_data="topup:rub:1000"),
            InlineKeyboardButton("5000 ₽", callback_data="topup:rub:5000"),
        ],
        [
            InlineKeyboardButton("CryptoBot USDT $5",  callback_data="topup:crypto:5"),
            InlineKeyboardButton("$10",                 callback_data="topup:crypto:10"),
            InlineKeyboardButton("$25",                 callback_data="topup:crypto:25"),
            InlineKeyboardButton("$50",                 callback_data="topup:crypto:50"),
        ],
    ])
    await update.effective_message.reply_text(
        "Выберите сумму пополнения:\n• ЮKassa (RUB) — счёт в Telegram\n• CryptoBot (USDT/TON) — платёжная ссылка",
        reply_markup=kb
    )

# ───────── CallbackQuery / меню ─────────
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()

    try:
        # TOPUP: меню пополнения
        if data == "topup":
            await q.answer()
            await _send_topup_menu(update, context)
            return

        # TOPUP RUB фиксированной суммой
        if data.startswith("topup:rub:"):
            await q.answer()
            try:
                amount_rub = int((data.split(":", 2)[-1] or "0").strip() or "0")
            except Exception:
                amount_rub = 0
            if amount_rub < MIN_RUB_FOR_INVOICE:
                await q.edit_message_text(f"Минимальная сумма пополнения: {MIN_RUB_FOR_INVOICE} ₽")
                return
        # Покупка подписки через CryptoBot
        if data.startswith("buyc:"):
            await q.answer()
            if not CRYPTO_PAY_API_TOKEN:
                await q.edit_message_text("CryptoBot не настроен. Укажите CRYPTO_PAY_API_TOKEN.")
                return
            _, tier, months = data.split(":", 2)
            months = int(months)
            # цену берем из таблицы и переводим в USD по вашему курсу
            rub = _plan_rub(tier, {1:"month",3:"quarter",12:"year"}[months])
            usd = float(rub) / max(1e-9, USD_RUB)
            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(usd, asset="USDT", description=f"Subscription {tier}/{months}m")
            if not inv_id or not pay_url:
                await q.edit_message_text("Не удалось создать счёт в CryptoBot.")
                return
            msg = await update.effective_message.reply_text(
                f"Оплатите подписку {tier.upper()} на {months} мес: ≈ ${usd_amount:.2f} ({asset}).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить в CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("Проверить оплату", callback_data=f"subcrypto:check:{tier}:{months}:{inv_id}")]
                ])
            )
            # автопуллинг
            async def _poll():
                await _poll_crypto_invoice(context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id, usd_amount)
            context.application.create_task(_poll())
            return

        if data.startswith("subcrypto:check:"):
            await q.answer()
            _, _, tier, months, inv_id = data.split(":", 4)
            inv = await _crypto_get_invoice(inv_id)
            if not inv:
                await q.edit_message_text("Счёт не найден. Создайте новый.")
                return
            st = (inv.get("status") or "").lower()
            if st == "paid":
                until = activate_subscription_with_tier(update.effective_user.id, tier, int(months))
                await q.edit_message_text(f"⭐ Подписка активирована до {until.strftime('%Y-%m-%d')} (Crypto).")
            elif st == "active":
                await q.answer("Платёж ещё не подтверждён", show_alert=True)
            else:
                await q.edit_message_text(f"Статус счёта: {st}")
            return
            payload = "t=3"
            ok = await _send_invoice_rub("Пополнение баланса", "Единый кошелёк для перерасходов.", amount_rub, payload, update)
        # ===== image tools =====
        if data == "img:remove_bg":
            await q.answer()
            uid = update.effective_user.id
            img = _last_photo.get(uid)
            if not img:
                await q.edit_message_text("Нет последнего фото. Пришлите фото ещё раз.")
                return
            await q.edit_message_text("Удаляю фон…")
            out = await _remove_bg_bytes(img)
            if not out:
                await update.effective_message.reply_text("Не удалось удалить фон (проверьте REMOVE_BG_API_KEY).")
                return
            await update.effective_message.reply_document(document=InputFile(BytesIO(out), filename="no_bg.png"), caption="Готово ✅")
            return

        if data == "img:enhance":
            await q.answer()
            uid = update.effective_user.id
            img = _last_photo.get(uid)
            if not img:
                await q.edit_message_text("Нет последнего фото. Пришлите фото ещё раз.")
                return
            await q.edit_message_text("Улучшаю качество…")
            out = await _enhance_with_openai(img)
            if not out:
                await update.effective_message.reply_text("Не удалось улучшить изображение.")
                return
            await update.effective_message.reply_photo(photo=out, caption="Готово ✅")
            return

        if data == "img:replace_bg":
            await q.answer()
            _pending_edit[update.effective_user.id] = {"action": "replace_bg"}
            await q.edit_message_text("Опишите, какой фон нужно поставить (например: «пляж на закате»).")
            return

        if data.startswith("img:animate:"):
            await q.answer()
            engine = data.split(":", 2)[-1]  # luma|runway
            uid = update.effective_user.id
            img = _last_photo.get(uid)
            if not img:
                await q.edit_message_text("Нет последнего фото. Пришлите фото ещё раз.")
                return
            # Соберём промпт из подписи предыдущего сообщения, если была
            base_prompt = "Animate the subject from the photo: natural smile and puts the phone down."
            # Для простоты: используем text-to-video по описанию (без image-input)
            duration, ar, prompt = parse_video_opts_from_text(base_prompt, default_duration=LUMA_DURATION_S, default_ar=LUMA_ASPECT)
            async def _go_luma():
                await _run_luma_video(update, context, prompt, duration, ar)
                _register_engine_spend(uid, "luma", 0.40)
            async def _go_runway():
                await _run_runway_video(update, context, prompt, duration, ar)
                base = RUNWAY_UNIT_COST_USD or 7.0
                _register_engine_spend(uid, "runway", max(1.0, base * (duration / max(1, RUNWAY_DURATION_S))))
            if engine == "luma":
                await _try_pay_then_do(update, context, uid, "luma", 0.40, _go_luma, remember_kind="video_luma", remember_payload={"prompt": prompt, "duration": duration, "aspect": ar})
            else:
                est = max(1.0, RUNWAY_UNIT_COST_USD * (duration / max(1, RUNWAY_DURATION_S)))
                await _try_pay_then_do(update, context, uid, "runway", est, _go_runway, remember_kind="video_runway", remember_payload={"prompt": prompt, "duration": duration, "aspect": ar})
            return
            await q.answer("Выставляю счёт…" if ok else "Не удалось выставить счёт", show_alert=not ok)
            return

        # TOPUP CRYPTO через CryptoBot
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
            # фоновая проверка
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
                usd_amount = float(inv.get("amount", 0.0))  # для USDT = USD
                if (inv.get("asset") or "").upper() == "TON":
                    usd_amount *= TON_USD_RATE
                _wallet_total_add(update.effective_user.id, usd_amount)
                await q.edit_message_text(f"💳 Оплата получена. Баланс пополнен на ≈ ${usd_amount:.2f}.")
            elif st == "active":
                await q.answer("Платёж ещё не подтверждён", show_alert=True)
            else:
                await q.edit_message_text(f"Статус счёта: {st}")
            return

        if data.startswith("buy:"):
            _, tier, months = data.split(":", 2)
            months = int(months)
            payload, amount_rub, title = _plan_payload_and_amount(tier, months)
            desc = f"Оформление подписки {tier.upper()} на {months} мес."
            ok = await _send_invoice_rub(title, desc, amount_rub, payload, update)
            await q.answer("Выставляю счёт…" if ok else "Не удалось выставить счёт", show_alert=not ok)
            return

        if data.startswith("engine:"):
            await q.answer()
            engine = data.split(":", 1)[1]  # gpt|images|luma|runway|midjourney|stt_tts

            username = (update.effective_user.username or "")
            if is_unlimited(update.effective_user.id, username):
                await q.edit_message_text(
                    f"✅ Движок «{engine}» доступен без ограничений.\n"
                    f"Отправь задачу, например: «сделай видео ретро-авто, 9 секунд, 9:16»."
                )
                return

            if engine in ("gpt", "stt_tts", "midjourney"):
                await q.edit_message_text(
                    f"✅ Выбран «{engine}». Отправь запрос текстом/фото. "
                    f"Для Luma/Runway/Images действуют дневные бюджеты тарифа."
                )
                return

            est_cost = IMG_COST_USD if engine == "images" else (0.40 if engine == "luma" else max(1.0, RUNWAY_UNIT_COST_USD))
            map_engine = {"images": "img", "luma": "luma", "runway": "runway"}[engine]
            ok, offer = _can_spend_or_offer(update.effective_user.id, username, map_engine, est_cost)

            if ok:
                await q.edit_message_text(
                    "✅ Доступно. "
                    + ("Запусти: /img кот в очках" if engine == "images"
                       else "Напиши: «сделай видео … 9 секунд 9:16» — предложу Luma/Runway.")
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

        if data.startswith("choose:"):  # choose:<engine>:<aid>
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
            "Да. Пришли файл — я извлеку текст и сделаю краткий конспект/ответ по цели.\n"
            "Поддержка: PDF, EPUB, DOCX, FB2, TXT (MOBI/AZW — по возможности). "
            "Можно добавить подпись к файлу с целью анализа."
        )
    if (_CAP_AUDIO.search(tl) and re.search(r"(чита|анализ|расшиф|транскриб|понима|распозна)", tl)) or "аудио" in tl:
        return (
            "Да. Пришли аудио (voice/audio/документ): OGG/OGA, MP3, M4A/MP4, WAV, WEBM. "
            "Распознаю речь (Deepgram/Whisper) и сделаю конспект, тезисы, тайм-коды, Q&A."
        )
    if _CAP_IMAGE.search(tl) and re.search(r"(чита|анализ|понима|видишь)", tl):
        return "Да. Пришли фото/картинку с подписью — опишу содержимое, текст на изображении, объекты и детали."
    if _CAP_IMAGE.search(tl) and re.search(r"(мож(ешь|ете)|созда(ва)?т|дела(ть)?|генерир)", tl):
        return (
            "Да, могу создавать изображения. Запусти через /img <описание> "
            "или фразой: «Сгенерируй изображение неонового города под дождём»."
        )
    if _CAP_VIDEO.search(tl) and re.search(r"(мож(ешь|ете)|созда(ва)?т|дела(ть)?|сгенерир)", tl):
        return (
            "Да, могу запускать генерацию коротких видео. Напиши: "
            "«сделай видео … на 9 секунд 9:16». После запроса предложу выбрать Luma или Runway."
        )
    return None

# ───────── Diagnostics: лимиты/остатки ─────────
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

# ───────── Команды UI и welcome ─────────
async def cmd_set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("Команда доступна только владельцу.")
        return
    if not context.args:
        await update.effective_message.reply_text("Формат: /set_welcome <url_картинки>")
        return
    url = " ".join(context.args).strip()
    kv_set("welcome_url", url)
    await update.effective_message.reply_text("Картинка приветствия обновлена. Отправь /start для проверки.")

async def cmd_show_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = kv_get("welcome_url", BANNER_URL)
    if url:
        try:
            await update.effective_message.reply_photo(url, caption="Текущая картинка приветствия")
        except Exception:
            await update.effective_message.reply_text("Не удалось отправить изображение, проверь URL.")
    else:
        await update.effective_message.reply_text("Картинка приветствия не задана.")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_url = kv_get("welcome_url", BANNER_URL)
    if welcome_url:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_photo(welcome_url)
    await update.effective_message.reply_text(START_TEXT, reply_markup=main_kb, disable_web_page_preview=True)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, disable_web_page_preview=True)

async def cmd_modes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Выбери движок:", reply_markup=engines_kb())

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(EXAMPLES_TEXT, disable_web_page_preview=True)

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
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")],
    ])
    await update.effective_message.reply_text(msg, reply_markup=kb)

async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args) if context.args else (update.message.text.split(" ", 1)[-1] if " " in update.message.text else "")
    prompt = prompt.strip()
    if not prompt:
        await update.effective_message.reply_text("Формат: /img <описание>")
        return
    async def _go():
        await _do_img_generate(update, context, prompt)
    user_id = update.effective_user.id
    await _try_pay_then_do(update, context, user_id, "img", IMG_COST_USD, _go,
                           remember_kind="img_generate", remember_payload={"prompt": prompt})

# ───────── WebApp: ловим sendData из мини-приложения ─────────
async def on_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        wad = update.effective_message.web_app_data
        raw = wad.data if wad else ""
        data = {}
        try:
            data = json.loads(raw)
        except Exception:
            # поддержка строк вида "type=subscribe&tier=pro&months=3"
            for part in (raw or "").split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    data[k.strip()] = v.strip()

        typ = (data.get("type") or data.get("action") or "").lower()

        if typ in ("subscribe", "buy", "buy_sub", "sub"):
            tier = (data.get("tier") or "pro").lower()
            months = int(data.get("months") or 1)
            payload, amount_rub, title = _plan_payload_and_amount(tier, months)
            desc = f"Оформление подписки {tier.upper()} на {months} мес. (из мини-приложения)"
            await _send_invoice_rub(title, desc, amount_rub, payload, update)
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

# ───────── Error handler ─────────
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        err = getattr(context, "error", None)
        chat_id = None
        try:
            if hasattr(update, "effective_chat") and update.effective_chat:
                chat_id = update.effective_chat.id
            elif hasattr(update, "message") and update.message:
                chat_id = update.message.chat_id
        except Exception:
            pass
        log.exception("Unhandled exception in handler: %s", err)
        if chat_id:
            with contextlib.suppress(Exception):
                await context.bot.send_message(
                    chat_id,
                    "⚠️ Произошла внутренняя ошибка. Уже разбираюсь, попробуй ещё раз."
                )
    except Exception as e:
        log.exception("on_error failed: %s", e)

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
                text = (dg.get("results", {}).get("channels", [{}])[0]
                        .get("alternatives", [{}])[0].get("transcript", "")).strip()
                if text:
                    return text
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

# ───────── Запуск (webhook / polling) ─────────
def run_by_mode(app):
    try:
        asyncio.get_running_loop()
        _have_running_loop = True
    except RuntimeError:
        _have_running_loop = False

    if not _have_running_loop:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    async def _cleanup_webhook():
        with contextlib.suppress(Exception):
            await app.bot.delete_webhook(drop_pending_updates=True)
            log.info("Webhook cleanup done (drop_pending_updates=True)")

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

# ───────── Инициализация бота ─────────
def main():
    db_init()
    db_init_usage()
    _db_init_prefs()

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

    # WebApp data (кнопка «синяя» в мини-приложении)
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))

    # Коллбэки/платежи
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_success_payment))

    # Фото/визион
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))

    # Голос/аудио
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))

    # Аудио как документ
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

    # Кнопки главного меню
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\s*⭐\s*Подписка\s*$"), cmd_plans))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\s*🎛\s*Движки\s*$"), cmd_modes))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\s*🧾\s*Баланс\s*$"), cmd_balance))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\s*ℹ️\s*Помощь\s*$"), cmd_help))

    # Обычный текст — последним
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # Общий error handler
    app.add_error_handler(on_error)

    run_by_mode(app)

if __name__ == "__main__":
    main()
