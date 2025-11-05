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
OPENAI_BASE_URL  = os.environ.get("OPENAI_BASE_URL", "").strip()
OPENAI_MODEL     = os.environ.get("OPENAI_MODEL", "openai/gpt-4o-mini").strip()

OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "").strip()

USE_WEBHOOK      = os.environ.get("USE_WEBHOOK", "1").lower() in ("1","true","yes","on")
WEBHOOK_PATH     = os.environ.get("WEBHOOK_PATH", "/tg").strip()
WEBHOOK_SECRET   = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()

BANNER_URL       = os.environ.get("BANNER_URL", "").strip()
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "").strip()

# STT
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "").strip()
OPENAI_STT_KEY   = os.environ.get("OPENAI_STT_KEY", "").strip()
TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1").strip()

# TTS
OPENAI_TTS_KEY       = os.environ.get("OPENAI_TTS_KEY", "").strip() or OPENAI_API_KEY
OPENAI_TTS_BASE_URL  = (os.environ.get("OPENAI_TTS_BASE_URL", "").strip() or "https://api.openai.com/v1")
OPENAI_TTS_MODEL     = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip()
OPENAI_TTS_VOICE     = os.environ.get("OPENAI_TTS_VOICE", "alloy").strip()
TTS_MAX_CHARS        = int(os.environ.get("TTS_MAX_CHARS", "150") or "150")

# Images
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
_LUMA_ACTIVE_BASE: str | None = None

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
            if r.status_code in (200,201,202,204,400,401,403,404,405):
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
        s.encode("ascii"); return s
    except Exception:
        return None
def _ascii_label(s: str | None) -> str:
    s = (s or "").strip() or "Item"
    try:
        s.encode("ascii"); return s[:32]
    except Exception:
        return "Item"

# HTTP stub (healthcheck + /premium.html redirect)
def _start_http_stub():
    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            path = (self.path or "/").split("?", 1)[0]
            if path in ("/", "/healthz"):
                self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers(); self.wfile.write(b"ok"); return
            if path == "/premium.html":
                if WEBAPP_URL:
                    self.send_response(302); self.send_header("Location", WEBAPP_URL); self.end_headers()
                else:
                    self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
                    self.wfile.write(b"<html><body><h3>Premium page</h3><p>Set WEBAPP_URL env.</p></body></html>")
                return
            self.send_response(404); self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers(); self.wfile.write(b"not found")
        def log_message(self, *_): return
    try:
        srv = HTTPServer(("0.0.0.0", PORT), _H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log.info("HTTP stub bound on 0.0.0.0:%s", PORT)
    except Exception as e:
        log.exception("HTTP stub start failed: %s", e)

# Text LLM
_auto_base = OPENAI_BASE_URL
if not _auto_base and (OPENAI_API_KEY.startswith("sk-or-") or "openrouter" in (OPENAI_BASE_URL or "").lower()):
    _auto_base = "https://openrouter.ai/api/v1"
    log.info("Auto-select OpenRouter base_url for text LLM.")

default_headers = {}
ref = _ascii_or_none(OPENROUTER_SITE_URL)
ttl = _ascii_or_none(OPENROUTER_APP_NAME)
if ref: default_headers["HTTP-Referer"] = ref
if ttl: default_headers["X-Title"] = ttl

try:
    oai_llm = OpenAI(api_key=OPENAI_API_KEY, base_url=_auto_base or None, default_headers=default_headers or None)
except TypeError:
    oai_llm = OpenAI(api_key=OPENAI_API_KEY, base_url=_auto_base or None)

oai_stt = OpenAI(api_key=OPENAI_STT_KEY) if OPENAI_STT_KEY else None
oai_img = OpenAI(api_key=OPENAI_IMAGE_KEY, base_url=IMAGES_BASE_URL)

# Tavily (optional)
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
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS subscriptions (
        user_id INTEGER PRIMARY KEY,
        until_ts INTEGER NOT NULL,
        tier TEXT
    )""")
    con.commit(); con.close()

def _utcnow(): return datetime.now(timezone.utc)

def activate_subscription(user_id: int, months: int = 1):
    now = _utcnow(); until = now + timedelta(days=30 * months)
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
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
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT until_ts FROM subscriptions WHERE user_id = ?", (user_id,))
    row = cur.fetchone(); con.close()
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
    if not row: return "free"
    until_ts, tier = row[0], (row[1] or "pro")
    if until_ts and datetime.fromtimestamp(until_ts, tz=timezone.utc) > _utcnow():
        return (tier or "pro").lower()
    return "free"

# usage & wallet
def db_init_usage():
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
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
    cur.execute("""CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)""")
    try: cur.execute("ALTER TABLE wallet ADD COLUMN usd REAL DEFAULT 0.0")
    except Exception: pass
    try: cur.execute("ALTER TABLE subscriptions ADD COLUMN tier TEXT")
    except Exception: pass
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

# DEMO лимиты
LIMITS = {
    "free":      {"text_per_day": 5,    "luma_budget_usd": 0.40, "runway_budget_usd": 0.0,  "img_budget_usd": 0.05, "allow_engines": ["gpt","luma","images"]},
    "start":     {"text_per_day": 200,  "luma_budget_usd": 0.8,  "runway_budget_usd": 0.0,  "img_budget_usd": 0.2,  "allow_engines": ["gpt","luma","midjourney","images"]},
    "pro":       {"text_per_day": 1000, "luma_budget_usd": 4.0,  "runway_budget_usd": 7.0,  "img_budget_usd": 1.0,  "allow_engines": ["gpt","luma","runway","midjourney","images"]},
    "ultimate":  {"text_per_day": 5000, "luma_budget_usd": 8.0,  "runway_budget_usd": 14.0, "img_budget_usd": 2.0,  "allow_engines": ["gpt","luma","runway","midjourney","images"]},
}
def _limits_for(user_id: int) -> dict:
    tier = get_subscription_tier(user_id)
    d = LIMITS.get(tier, LIMITS["free"]).copy(); d["tier"] = tier; return d

def check_text_and_inc(user_id: int, username: str | None = None) -> tuple[bool, int, str]:
    if is_unlimited(user_id, username):
        _usage_update(user_id, text_count=1); return True, 999999, "ultimate"
    lim = _limits_for(user_id); row = _usage_row(user_id)
    left = max(0, lim["text_per_day"] - row["text_count"])
    if left <= 0: return False, 0, lim["tier"]
    _usage_update(user_id, text_count=1); return True, left - 1, lim["tier"]

def _calc_oneoff_price_rub(engine: str, usd_cost: float) -> int:
    markup = ONEOFF_MARKUP_RUNWAY if engine == "runway" else ONEOFF_MARKUP_DEFAULT
    rub = usd_cost * (1.0 + markup) * USD_RUB
    val = int(rub + 0.999)
    return max(MIN_RUB_FOR_INVOICE, val)

def _can_spend_or_offer(user_id: int, username: str | None, engine: str, est_cost_usd: float) -> tuple[bool, str]:
    if is_unlimited(user_id, username):
        if engine in ("luma","runway","img"): _usage_update(user_id, **{f"{engine}_usd": est_cost_usd})
        return True, ""
    if engine not in ("luma","runway","img"): return True, ""
    lim = _limits_for(user_id); row = _usage_row(user_id)
    spent = row[f"{engine}_usd"]; budget = lim[f"{engine}_budget_usd"]
    if spent + est_cost_usd <= budget + 1e-9:
        _usage_update(user_id, **{f"{engine}_usd": est_cost_usd}); return True, ""
    need = max(0.0, spent + est_cost_usd - budget)
    if need > 0:
        if _wallet_total_take(user_id, need):
            _usage_update(user_id, **{f"{engine}_usd": est_cost_usd}); return True, ""
        if lim["tier"] == "free": return False, "ASK_SUBSCRIBE"
        return False, f"OFFER:{need:.2f}"
    return True, ""

def _register_engine_spend(user_id: int, engine: str, usd: float):
    if engine in ("luma","runway","img"):
        _usage_update(user_id, **{f"{engine}_usd": float(usd)})

# ───────── Prompts ─────────
SYSTEM_PROMPT = (
    "Ты дружелюбный и лаконичный ассистент на русском. "
    "Отвечай по сути, структурируй списками/шагами, не выдумывай факты. "
)
VISION_SYSTEM_PROMPT = (
    "Ты чётко описываешь содержимое изображений: объекты, текст, схемы. "
    "Не идентифицируй личности людей."
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

_CREATE_CMD = r"(сдела(й|йте)|созда(й|йте)|сгенериру(й|йте)|нарису(й|йте)|render|generate|create|make)"
_PREFIXES_VIDEO = [r"^" + _CREATE_CMD + r"\s+видео", r"^video\b", r"^reels?\b", r"^shorts?\b"]
_PREFIXES_IMAGE = [r"^" + _CREATE_CMD + r"\s+(?:картин\w+|изображен\w+|фото\w+|рисунк\w+)", r"^image\b", r"^picture\b", r"^img\b"]

def _strip_leading(s: str) -> str: return s.strip(" \n\t:—–-\"“”'«»,.()[]")
def _after_match(text: str, match) -> str: return _strip_leading(text[match.end():])

def _looks_like_capability_question(tl: str) -> bool:
    if "?" in tl and re.search(_CAPABILITY_RE, tl) and not re.search(_CREATE_CMD, tl, re.I): return True
    m = re.search(r"\b(ты|вы)?\s*мож(ешь|но|ете)\b", tl)
    if m and re.search(_CAPABILITY_RE, tl) and not re.search(_CREATE_CMD, tl, re.I): return True
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
            clean = re.sub(_VID_WORDS, "", tl, flags=re.I); clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
            return ("video", _strip_leading(clean))
        if re.search(_IMG_WORDS, tl, re.I):
            clean = re.sub(_IMG_WORDS, "", tl, flags=re.I); clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
            return ("image", _strip_leading(clean))
    m = re.match(r"^(img|image|picture)\s*[:\-]\s*(.+)$", tl)
    if m: return ("image", _strip_leading(t[m.end(1)+1:]))
    m = re.match(r"^(video|vid|reels?|shorts?)\s*[:\-]\s*(.+)$", tl)
    if m: return ("video", _strip_leading(t[m.end(1)+1:]))
    return (None, "")

# ───────── OpenAI helpers ─────────
def _oai_text_client():
    return oai_llm

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

# ───────── Надёжный TTS через REST (OGG/Opus) ─────────
def _tts_bytes_sync(text: str) -> bytes | None:
    try:
        if not OPENAI_TTS_KEY:
            return None
        url = f"{OPENAI_TTS_BASE_URL.rstrip('/')}/audio/speech"
        payload = {
            "model": OPENAI_TTS_MODEL,
            "voice": OPENAI_TTS_VOICE,
            "input": text,
            "format": "opus"
        }
        headers = {
            "Authorization": f"Bearer {OPENAI_TTS_KEY}",
            "Content-Type": "application/json"
        }
        r = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        r.raise_for_status()
        return r.content if r.content else None
    except Exception as e:
        log.exception("TTS HTTP error: %s", e)
        return None

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

# ───────── Извлечение текста из документов ─────────
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
            if item.get_type() == 9:
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
        try:
            await update.effective_message.reply_text("Ошибка при анализе документа.")
        except Exception:
            pass

# ───────── OpenAI Images ─────────
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

# ──────── Images: RemBG и правки с mask ────────
def _ensure_rembg():
    try:
        import rembg  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False

def _rembg_cut_foreground_png(src_bytes: bytes) -> bytes | None:
    try:
        from rembg import remove
        out = remove(src_bytes)
        return out
    except Exception as e:
        log.exception("rembg remove error: %s", e)
        return None

def _rembg_alpha_mask(src_bytes: bytes) -> bytes | None:
    """Строим маску (белое — оставить, чёрное — редактировать) на основе alpha от rembg."""
    try:
        from PIL import Image
        from io import BytesIO as _BIO
        cut = _rembg_cut_foreground_png(src_bytes)
        if not cut:
            return None
        im = Image.open(BytesIO(cut)).convert("RGBA")
        alpha = im.split()[-1]
        # Маска: белое (255) там, где foreground (alpha>0), иначе чёрное
        mask = Image.new("L", im.size, 0)
        mask.paste(255, mask=alpha.point(lambda a: 255 if a > 0 else 0))
        bio = _BIO()
        mask.save(bio, format="PNG")
        return bio.getvalue()
    except Exception as e:
        log.exception("rembg alpha->mask error: %s", e)
        return None

async def _img_edit_keep_subject(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, src_bytes: bytes):
    """Редактируем фон/окружение, сохранив лицо/персону через mask из rembg."""
    try:
        if not _ensure_rembg():
            await update.effective_message.reply_text("Для редактирования с маской требуется rembg. Установите пакет rembg.")
            return
        mask_bytes = _rembg_alpha_mask(src_bytes)
        if not mask_bytes:
            await update.effective_message.reply_text("Не удалось подготовить маску объекта.")
            return
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        img_bio = BytesIO(src_bytes); img_bio.name = "image.png"
        mask_bio = BytesIO(mask_bytes); mask_bio.name = "mask.png"
        resp = oai_img.images.edits(
            model=IMAGES_MODEL,
            prompt=prompt,
            image=img_bio,
            mask=mask_bio,
            size="1024x1024",
            n=1
        )
        b64 = resp.data[0].b64_json
        edited = base64.b64decode(b64)
        await update.effective_message.reply_photo(edited, caption=f"Готово ✅\nИзменение по запросу: {prompt}")
    except Exception as e:
        log.exception("IMG edit error: %s", e)
        await update.effective_message.reply_text("Не удалось отредактировать изображение.")

async def _img_remove_bg(update: Update, context: ContextTypes.DEFAULT_TYPE, src_bytes: bytes):
    if not _ensure_rembg():
        await update.effective_message.reply_text("Для удаления фона требуется rembg. Установите пакет rembg.")
        return
    out = await asyncio.to_thread(_rembg_cut_foreground_png, src_bytes)
    if not out:
        await update.effective_message.reply_text("Не удалось удалить фон.")
        return
    bio = BytesIO(out); bio.name = "cutout.png"
    await update.effective_message.reply_document(document=InputFile(bio), caption="PNG с прозрачным фоном.")

# ───────── Хранилище последнего фото пользователя ─────────
def _kv_last_photo_key(uid: int) -> str:
    return f"last_photo:{uid}"

def _save_last_photo(uid: int, mime: str, b64: str):
    kv_set(_kv_last_photo_key(uid), json.dumps({"mime": mime, "b64": b64}))

def _load_last_photo(uid: int) -> tuple[str|None, bytes|None]:
    raw = kv_get(_kv_last_photo_key(uid), None)
    if not raw:
        return None, None
    try:
        js = json.loads(raw)
        mime = js.get("mime") or "image/png"
        b64 = js.get("b64") or ""
        return mime, base64.b64decode(b64)
    except Exception:
        return None, None

# ───────── UI / тексты ─────────
START_TEXT = (
    "Привет! Я GPT-бот с тарифами, квотами и разовыми пополнениями.\n\n"
    "Что умею:\n"
    "• 💬 Текст/фото (GPT)\n"
    "• 🎬 Видео Luma (5/9/10 c, 9:16/16:9)\n"
    "• 🎥 Видео Runway (PRO)\n"
    "• 🖼 Картинки — команда /img <промпт>\n"
    "• ✂️ Редактирование фото: /photo — удалить фон, изменить фон с mask\n"
    "• 📄 Анализ PDF/EPUB/DOCX/FB2/TXT — просто пришли файл.\n\n"
    "Открой «🎛 Движки», чтобы выбрать, и «⭐ Подписка» — для тарифов."
)
HELP_TEXT = (
    "Подсказки:\n"
    "• /plans — тарифы и оплата подписки (через чат или мини-приложение)\n"
    "• /img кот с очками — сгенерирует картинку\n"
    "• /photo — меню работы с последним фото (удалить фон, редактировать с mask, оживить в видео)\n"
    "• «сделай видео … 9 секунд 9:16» — Luma/Runway\n"
    "• «🧾 Баланс» — кошелёк и пополнение (RUB или CryptoBot USDT/TON)\n"
    "• /voice_on и /voice_off — озвучка ответов."
)
EXAMPLES_TEXT = (
    "Примеры:\n"
    "• сделай видео ретро-авто на берегу, 9 секунд, 9:16\n"
    "• /photo → ✂️ Удалить фон\n"
    "• /photo → 🎨 Изменить фон: «тропический пляж, закат»\n"
    "• /img неоновый город в дождь, реализм\n"
    "• пришли PDF — сделаю тезисы и выводы"
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

# ───────── Меню фото ─────────
def photo_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✂️ Удалить фон (rembg)", callback_data="photo:remove_bg")],
        [InlineKeyboardButton("🎨 Изменить фон (mask)",  callback_data="photo:edit_bg")],
        [InlineKeyboardButton("🎬 Оживить фото — Luma",  callback_data="photo:luma")],
        [InlineKeyboardButton("🎥 Оживить фото — Runway",callback_data="photo:runway")],
    ])

async def cmd_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Выберите действие с последним фото:",
        reply_markup=photo_menu_kb()
    )

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
            "Да, могу создавать и редактировать изображения. "
            "Используй /img для генерации или /photo для работы с последним фото (удалить фон, изменить фон, оживить)."
        )
    if _CAP_VIDEO.search(tl) and re.search(r"(мож(ешь|ете)|созда(ва)?т|дела(ть)?|сгенерир)", tl):
        return (
            "Да, могу запускать генерацию коротких видео. Напиши: "
            "«сделай видео … на 9 секунд 9:16». Также можно оживить присланное фото через /photo."
        )
    return None

# ───────── Диагностика ─────────
async def cmd_diag_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lim = _limits_for(user_id)
    row = _usage_row(user_id, _today_ymd())
    tier = lim["tier"]
    lines = [
        f"👤 Тариф: {tier}",
        f"• Тексты сегодня: {row['text_count']} / {lim['text_per_day']}",
        f"• Luma $: {row['luma_usd']:.2f} / {lim['luma_budget_usd']:.2f}",
        f"• Runway $: {row['runway_usd']:.2f} / {lim['runway_budget_usd']:.2f}",
        f"• Images $: {row['img_usd']:.2f} / {lim['img_budget_usd']:.2f}",
    ]
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
        f"• Поллинг каждые {VIDEO_POLL_DELAY_S}s; таймауты: Luma {LUMA_MAX_WAIT_S}s / Runway {RUNWAY_MAX_WAIT_S}s",
    ]
    await update.effective_message.reply_text("\n".join(lines))

# ───────── Текстовый пайплайн ─────────
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
        file = await update.message.photo[-1].get_file()
        data = await file.download_as_bytearray()
        mime = sniff_image_mime(bytes(data))
        b64 = base64.b64encode(bytes(data)).decode("ascii")
        _save_last_photo(user_id, mime, b64)  # запоминаем последнее фото
        user_text = (update.message.caption or "").strip()
        ans = await ask_openai_vision(user_text, b64, mime)
        await update.effective_message.reply_text((ans or "Готово.") + "\n\n➡️ Для работы с этим фото: /photo")
        await maybe_tts_reply(update, context, (ans or "")[:TTS_MAX_CHARS])
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

# (пере)используем вспомогательные парсеры из твоего файла
def _strip_leading(s: str) -> str:
    return s.strip(" \n\t:—–-\"“”'«»,.()[]")

def _after_match(text: str, match) -> str:
    return _strip_leading(text[match.end():])

_CREATE_CMD = r"(сдела(й|йте)|созда(й|йте)|сгенериру(й|йте)|нарису(й|йте)|render|generate|create|make)"
_IMG_WORDS = r"(картин\w+|изображен\w+|фото\w*|рисунк\w+|image|picture|img\b|logo|banner|poster)"
_VID_WORDS = r"(видео|ролик\w*|анимаци\w*|shorts?|reels?|clip|video|vid\b)"
_PREFIXES_VIDEO = [r"^" + _CREATE_CMD + r"\s+видео", r"^video\b", r"^reels?\b", r"^shorts?\b"]
_PREFIXES_IMAGE = [r"^" + _CREATE_CMD + r"\s+(?:картин\w+|изображен\w+|фото\w+|рисунк\w+)", r"^image\b", r"^picture\b", r"^img\b"]

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

    # Опциональный веб-контекст
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

# ───────── Парсинг опций для видео ─────────
def _norm_ar(ar: str) -> str:
    ar = (ar or "").strip().lower().replace("×", "x").replace("x", ":")
    if ar in ("9:16","16:9","1:1"):
        return ar
    if "вертик" in ar or "portrait" in ar:
        return "9:16"
    if "гориз" in ar or "ландшафт" in ar or "landscape" in ar:
        return "16:9"
    return LUMA_ASPECT

def parse_video_opts_from_text(text: str, default_duration: int = 5, default_ar: str = "16:9") -> tuple[int, str, str]:
    tl = (text or "").lower()
    # duration
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
                if 3 <= cand <= 12:
                    dur = cand
            except Exception:
                pass
    # aspect
    ar = default_ar
    m = re.search(r"(\d{1,2})\s*[:×x]\s*(\d{1,2})", tl)
    if m:
        ar = f"{int(m.group(1))}:{int(m.group(2))}"
    elif "вертик" in tl or "portrait" in tl:
        ar = "9:16"
    elif "гориз" in tl or "landscape" in tl:
        ar = "16:9"
    ar = _norm_ar(ar)
    # prompt
    clean = re.sub(r"\b(\d{1,2}\s*(сек|sec|s)\b|9:16|16:9|1:1|вертикальн\w+|горизонтальн\w+|portrait|landscape)\b", "", tl, flags=re.I)
    prompt = clean.strip()
    if not prompt:
        prompt = text.strip()
    return dur, ar, prompt

def _safe_caption(s: str, limit: int = 850) -> str:
    s = (s or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit-3] + "…"

# ───────── Luma: создание/поллинг/отправка ─────────
async def _run_luma_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration_s: int, aspect: str):
    if not LUMA_API_KEY:
        await update.effective_message.reply_text("Luma не настроен.")
        return
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            base = await _pick_luma_base(client)
            create_url = f"{base}{LUMA_CREATE_PATH}"
            payload = {
                "model": LUMA_MODEL,
                "prompt": prompt,
                "aspect_ratio": aspect,
                "duration": f"{int(duration_s)}s"
            }
            headers = {"Authorization": f"Bearer {LUMA_API_KEY}", "Content-Type": "application/json"}

            r = await client.post(create_url, headers=headers, json=payload)
            r.raise_for_status()
            resp = r.json()

            gen_id = resp.get("id") or resp.get("generation_id") or resp.get("data", {}).get("id")
            if not gen_id:
                await update.effective_message.reply_text("Luma: не получил id задачи.")
                return

            await update.effective_message.reply_text("🎬 Luma: рендер запущен, подожди…")

            # poll
            status_url = f"{base}{LUMA_STATUS_PATH.format(id=gen_id)}"
            started = time.time()
            video_url = None

            while time.time() - started < LUMA_MAX_WAIT_S:
                rs = await client.get(status_url, headers=headers)
                if rs.status_code == 404:
                    await asyncio.sleep(VIDEO_POLL_DELAY_S)
                    continue
                rs.raise_for_status()
                js = rs.json()
                st = (js.get("status") or js.get("state") or "").lower()

                if st in ("completed", "finished", "succeeded", "success", "done"):
                    video_url = (
                        js.get("video")
                        or js.get("video_url")
                        or (js.get("assets", {}) or {}).get("video")
                    )
                    break

                if st in ("failed", "error", "canceled", "cancelled"):
                    await update.effective_message.reply_text(f"❌ Luma ошибка: {st}")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

            if not video_url:
                await update.effective_message.reply_text("⏱️ Luma: таймаут ожидания видео.")
                return

            # download & send
            async with httpx.AsyncClient(timeout=180.0) as dl:
                vid = await dl.get(video_url)
                vid.raise_for_status()
                bio = BytesIO(vid.content)
                bio.name = "luma.mp4"

            caption = _safe_caption(f"Luma • {duration_s}s • {aspect}\n\n{prompt}")
            await update.effective_message.reply_video(video=bio, caption=caption)

    except Exception as e:
        log.exception("Luma error: %s", e)
        await update.effective_message.reply_text("Ошибка Luma при генерации видео.")

# ───────── Runway: helper ─────────
def _runway_ratio_from_ar(ar: str) -> str:
    if ar == "9:16":
        return "720:1280"
    if ar == "16:9":
        return "1280:720"
    if ar == "1:1":
        return "1024:1024"
    return RUNWAY_RATIO

# ───────── Runway: создание/поллинг/отправка ─────────
async def _run_runway_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration_s: int, aspect: str):
    if not RUNWAY_API_KEY:
        await update.effective_message.reply_text("Runway не настроен.")
        return
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            create_url = f"{RUNWAY_BASE_URL}{RUNWAY_CREATE_PATH}"
            payload = {
                "model": RUNWAY_MODEL,
                "input": {
                    "prompt": prompt,
                    "duration": int(duration_s),
                    "ratio": _runway_ratio_from_ar(aspect)
                }
            }
            headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Content-Type": "application/json"}

            r = await client.post(create_url, headers=headers, json=payload)
            r.raise_for_status()
            js = r.json()

            task_id = js.get("id") or js.get("task", {}).get("id") or js.get("data", {}).get("id")
            if not task_id:
                await update.effective_message.reply_text("Runway: не получил id задачи.")
                return

            await update.effective_message.reply_text("🎥 Runway: рендер запущен, подожди…")

            status_url = f"{RUNWAY_BASE_URL}{RUNWAY_STATUS_PATH.format(id=task_id)}"
            started = time.time()
            video_url = None

            while time.time() - started < RUNWAY_MAX_WAIT_S:
                rs = await client.get(status_url, headers=headers)
                rs.raise_for_status()
                st_js = rs.json()
                st = (st_js.get("status") or st_js.get("state") or "").upper()

                if st in ("SUCCEEDED", "COMPLETED", "FINISHED", "SUCCESS"):
                    video_url = (
                        (st_js.get("output") or {}).get("video")
                        or (st_js.get("output") or {}).get("url")
                        or (st_js.get("assets", [{}])[0].get("url") if isinstance(st_js.get("assets"), list) else None)
                    )
                    break

                if st in ("FAILED", "ERROR", "CANCELED", "CANCELLED"):
                    await update.effective_message.reply_text(f"❌ Runway ошибка: {st}")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

            if not video_url:
                await update.effective_message.reply_text("⏱️ Runway: таймаут ожидания видео.")
                return

            # download & send
            async with httpx.AsyncClient(timeout=180.0) as dl:
                vid = await dl.get(video_url)
                vid.raise_for_status()
                bio = BytesIO(vid.content)
                bio.name = "runway.mp4"

            caption = _safe_caption(f"Runway • {duration_s}s • {aspect}\n\n{prompt}")
            await update.effective_message.reply_video(video=bio, caption=caption)

    except Exception as e:
        log.exception("Runway error: %s", e)
        await update.effective_message.reply_text("Ошибка Runway при генерации видео.")

# ───────── Фото-коллбэки (rembg / edits / animate) ─────────
async def _need_last_photo(update: Update) -> tuple[str|None, bytes|None]:
  mime, data = _load_last_photo(update.effective_user.id)
  if not data:
    await update.effective_message.reply_text("Я не нашёл последнее фото. Пришлите изображение и повторите /photo.")
    return None, None
  return mime, data

async def _photo_animate_common(update: Update, context: ContextTypes.DEFAULT_TYPE, engine: str):
  mime, data = await _need_last_photo(update)
  if not data:
    return
  b64 = base64.b64encode(data).decode("ascii")
  # параметры по умолчанию
  dur = LUMA_DURATION_S
  ar  = LUMA_ASPECT
  prompt = "Animate from this photo: gentle camera move, subtle parallax, natural motion."
  # стоимость и запуск
  async def _run():
    if engine == "luma":
      await _run_luma_video(update, context, prompt, dur, ar, init_image_b64=b64, init_mime=mime)
      _register_engine_spend(update.effective_user.id, "luma", 0.40)
    else:
      await _run_runway_video(update, context, prompt, dur, ar, init_image_b64=b64, init_mime=mime)
      base = RUNWAY_UNIT_COST_USD or 7.0
      cost = max(1.0, base * (dur / max(1, RUNWAY_DURATION_S)))
      _register_engine_spend(update.effective_user.id, "runway", cost)
  est = 0.40 if engine == "luma" else max(1.0, RUNWAY_UNIT_COST_USD * (dur / max(1, RUNWAY_DURATION_S)))
  await _try_pay_then_do(update, context, update.effective_user.id, engine, est, _run,
                         remember_kind=f"video_{engine}",
                         remember_payload={"from_photo": True, "duration": dur, "aspect": ar})

async def on_cb_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
  if action == "remove_bg":
    mime, data = await _need_last_photo(update)
    if not data:
      return
    await _img_remove_bg(update, context, data)
    return
  if action == "edit_bg":
    mime, data = await _need_last_photo(update)
    if not data:
      return
    await update.effective_message.reply_text("Опишите, каким должен стать фон/окружение (одной фразой).")
    # Ждём следующий текст от пользователя и делаем правку
    aid = _new_aid()
    _pending_actions[aid] = {"kind": "await_photo_edit_prompt", "img_b64": base64.b64encode(data).decode("ascii")}
    await update.effective_message.reply_text("✍️ Напишите описание и я отредактирую. (Сообщение должно прийти следующим.)")
    kv_set(f"await_edit:{update.effective_user.id}", aid)
    return
  if action == "luma":
    await _photo_animate_common(update, context, "luma")
    return
  if action == "runway":
    await _photo_animate_common(update, context, "runway")
    return

# ───────── Платежи: Telegram Invoices (ЮKassa) и др. ─────────
# (оставляем без изменений из твоего файла: функции _payload_* , _send_invoice_rub, _try_pay_then_do и т.п.)
# --- они уже у тебя реализованы выше по файлу ---

# ───────── CallbackQuery (расширено фото-меню) ─────────
_pending_actions: dict[str, dict] = {}

def _new_aid() -> str:
  return uuid.uuid4().hex[:12]

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
  q = update.callback_query
  data = (q.data or "").strip()
  try:
    # Фото-операции
    if data.startswith("photo:"):
      await q.answer()
      action = data.split(":",1)[1]
      await on_cb_photo(update, context, action)
      return

    # --- ниже оставляем ВСЕ твои коллбэки без изменений (topup/buy/engine/choose/crypto ...) ---
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

    # Покупка подписки: выбор способа
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
             else "Напиши: «сделай видео … 9 секунд 9:16» — предложу Luma/Runway. Или /photo для анимации фото.")
        )
        return

        # Если не ок — либо предложить подписку/пополнение, либо разовую покупку
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
        # Без init-кадра (обычный text->video)
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

# ───────── STT (Deepgram/Whisper) ─────────
def _mime_from_filename(fn: str) -> str:
  fnl = (fn or "").lower()
  if fnl.endswith((".ogg",".oga")): return "audio/ogg"
  if fnl.endswith(".mp3"):          return "audio/mpeg"
  if fnl.endswith((".m4a",".mp4")): return "audio/mp4"
  if fnl.endswith(".wav"):          return "audio/wav"
  if fnl.endswith(".webm"):         return "audio/webm"
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
        text = (dg.get("results",{}).get("channels",[{}])[0].get("alternatives",[{}])[0].get("transcript","")).strip()
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

# ───────── Платежи/инвойсы/кошелёк — БЕЗ ИЗМЕНЕНИЙ (твой код) ─────────
# ... (оставлены все функции _payload_oneoff_topup/_payload_subscribe/_payload_parse/_send_invoice_rub
#     _send_topup_menu/_try_pay_then_do и т.д. — как в твоём рабочем бекапе)

# ───────── Приём результата / ожидание промпта для редактирования фото ─────────
async def on_text_awaiting_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
  """Если пользователь в режиме ожидания промпта для редактирования фото — обработаем и вернём True."""
  aid = kv_get(f"await_edit:{update.effective_user.id}", "")
  if not aid:
    return False
  meta = _pending_actions.pop(aid, None)
  if not meta or meta.get("kind") != "await_photo_edit_prompt":
    kv_set(f"await_edit:{update.effective_user.id}", "")
    return False
  kv_set(f"await_edit:{update.effective_user.id}", "")
  prompt = (update.message.text or "").strip()
  if not prompt:
    await update.effective_message.reply_text("Пустой запрос. Напишите, что нужно изменить на фоне.")
    return True
  img_b64 = meta.get("img_b64") or ""
  if not img_b64:
    await update.effective_message.reply_text("Фото не найдено. Пришлите изображение ещё раз.")
    return True
  src_bytes = base64.b64decode(img_b64)
  async def _go():
    await _img_edit_keep_subject(update, context, prompt, src_bytes)
  # списание за Images
  await _try_pay_then_do(update, context, update.effective_user.id, "img", IMG_COST_USD, _go,
                         remember_kind="img_edit",
                         remember_payload={"prompt": prompt})
  return True

# ───────── Приветствие / меню / команды ─────────
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
    with contextlib.suppress(Exception):
      await update.effective_message.reply_photo(url, caption="Текущая картинка приветствия")
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

# ───────── Запуск (webhook / polling) ─────────
def _start_http_stub():
  class _H(BaseHTTPRequestHandler):
    def do_GET(self):
      path = (self.path or "/").split("?", 1)[0]
      if path in ("/", "/healthz"):
        self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers(); self.wfile.write(b"ok"); return
      if path == "/premium.html":
        if WEBAPP_URL:
          self.send_response(302); self.send_header("Location", WEBAPP_URL); self.end_headers()
        else:
          self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
          self.wfile.write(b"<html><body><h3>Premium page</h3><p>Set WEBAPP_URL env.</p></body></html>")
        return
      self.send_response(404); self.send_header("Content-Type", "text/plain; charset=utf-8")
      self.end_headers(); self.wfile.write(b"not found")
    def log_message(self, *_): return
  try:
    srv = HTTPServer(("0.0.0.0", PORT), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("HTTP stub bound on 0.0.0.0:%s", PORT)
  except Exception as e:
    log.exception("HTTP stub start failed: %s", e)

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

# ───────── Ошибки ─────────
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
        await context.bot.send_message(chat_id, "⚠️ Произошла внутренняя ошибка. Уже разбираюсь, попробуй ещё раз.")
  except Exception as e:
    log.exception("on_error failed: %s", e)

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
  app.add_handler(CommandHandler("photo", cmd_photo))

  # WebApp data
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

  # Перехват «ожидаем промпт для редактирования фото»
  app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: on_text_awaiting_edit(u, c)))

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
