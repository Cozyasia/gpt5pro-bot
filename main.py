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
LUMA_DURATION_S  = int((os.environ.get("LUMA_DURATION_S") or "5").strip() or 5)  # 5/9/10s
LUMA_BASE_URL    = (os.environ.get("LUMA_BASE_URL", "https://api.lumalabs.ai/dream-machine/v1").strip().rstrip("/"))
LUMA_CREATE_PATH = "/generations"
LUMA_STATUS_PATH = "/generations/{id}"

# Fallback'и
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

# Runway — базовые значения
RUNWAY_BASE_URL    = (os.environ.get("RUNWAY_BASE_URL", "https://api.runwayml.com").strip().rstrip("/"))
RUNWAY_CREATE_PATH = "/v1/tasks"
RUNWAY_STATUS_PATH = "/v1/tasks/{id}"

# Таймауты и поллинг
LUMA_MAX_WAIT_S     = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)      # 15 мин
RUNWAY_MAX_WAIT_S   = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "1200").strip() or 1200)  # 20 мин
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

# ───────── DB: subscriptions / usage / wallet ─────────
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
    col = {"luma": "luma_usd", "runway": "runway_usd", "img": "img_usd"}.get(engine, None)
    if not col:
        return
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute(f"UPDATE wallet SET {col} = COALESCE({col},0)+? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close()

def _wallet_take(user_id: int, engine: str, usd: float) -> bool:
    col = {"luma": "luma_usd", "runway": "runway_usd", "img": "img_usd"}.get(engine, None)
    if not col:
        return False
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

LIMITS = {
    "free":      {"text_per_day": 5,    "luma_budget_usd": 0.0, "runway_budget_usd": 0.0,  "img_budget_usd": 0.0, "allow_engines": ["gpt"]},
    "start":     {"text_per_day": 200,  "luma_budget_usd": 0.8, "runway_budget_usd": 0.0,  "img_budget_usd": 0.2, "allow_engines": ["gpt","luma","midjourney"]},
    "pro":       {"text_per_day": 1000, "luma_budget_usd": 4.0, "runway_budget_usd": 7.0,  "img_budget_usd": 1.0, "allow_engines": ["gpt","luma","runway","midjourney"]},
    "ultimate":  {"text_per_day": 5000, "luma_budget_usd": 8.0, "runway_budget_usd": 14.0, "img_budget_usd": 2.0, "allow_engines": ["gpt","luma","runway","midjourney"]},
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
    if tier == "free":
        return False, "ASK_SUBSCRIBE"

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
                model=OPENAI_MODEL,
                messages=messages,
                temperature=0.6,
            )
            txt = (resp.choices[0].message.content or "").strip()
            if txt:
                return txt
        except Exception as e:
            last_err = e
            log.warning("OpenAI/Text attempt %s failed: %s", attempt + 1, e)
            await asyncio.sleep(0.7 * (attempt + 1))
    raise RuntimeError(f"OpenAI text error: {last_err}")

async def ask_openai_vision(image_bytes: bytes, question: str = "") -> str:
    """Описание/анализ изображения (без идентификации личностей)."""
    prompt = VISION_SYSTEM_PROMPT
    if question:
        prompt += "\nВопрос: " + question

    last_err = None
    for attempt in range(3):
        try:
            resp = oai_llm.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": question or "Опиши изображение подробно."},
                            {"type": "input_image", "image_data": image_bytes},
                        ],
                    },
                ],
            )
            txt = (resp.choices[0].message.content or "").strip()
            if txt:
                return txt
        except Exception as e:
            last_err = e
            log.warning("OpenAI/Vision attempt %s failed: %s", attempt + 1, e)
            await asyncio.sleep(0.7 * (attempt + 1))
    raise RuntimeError(f"OpenAI vision error: {last_err}")

async def openai_tts_to_ogg(text: str) -> bytes:
    """Генерирует OGG/Opus voice из текста."""
    text = (text or "").strip()
    if not text:
        return b""
    # ограничим длину
    if len(text) > TTS_MAX_CHARS:
        text = text[:TTS_MAX_CHARS] + "…"
    last_err = None
    for attempt in range(3):
        try:
            r = oai_tts.audio.speech.create(
                model=OPENAI_TTS_MODEL,
                voice=OPENAI_TTS_VOICE,
                input=text,
                format="ogg",
            )
            if hasattr(r, "content"):
                return r.content  # bytes
            if hasattr(r, "to_bytes"):
                return r.to_bytes()
        except Exception as e:
            last_err = e
            log.warning("TTS attempt %s failed: %s", attempt + 1, e)
            await asyncio.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"TTS error: {last_err}")

async def openai_stt_from_ogg(ogg_bytes: bytes) -> str:
    """Расшифровка голоса в текст (Whisper)."""
    if not oai_stt:
        return ""
    last_err = None
    for attempt in range(2):
        try:
            with BytesIO(ogg_bytes) as f:
                f.name = "audio.ogg"
                r = oai_stt.audio.transcriptions.create(
                    model=TRANSCRIBE_MODEL,
                    file=f,
                    response_format="text",
                )
            return (r or "").strip()
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.8)
    raise RuntimeError(f"STT error: {last_err}")

async def openai_image_generate(prompt: str, size: str = "1024x1024") -> bytes:
    """Генерация изображения из текста."""
    last_err = None
    for attempt in range(3):
        try:
            r = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size=size)
            b64 = r.data[0].b64_json
            return base64.b64decode(b64)
        except Exception as e:
            last_err = e
            log.warning("Image generate attempt %s failed: %s", attempt + 1, e)
            await asyncio.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"Image generate error: {last_err}")

async def openai_image_edit(image_bytes: bytes, prompt: str, size: str = "1024x1024") -> bytes:
    """Редактирование изображения (например «сделай мультяшным»)."""
    last_err = None
    for attempt in range(3):
        try:
            with BytesIO(image_bytes) as img:
                img.name = "image.png"
                r = oai_img.images.edits(
                    model=IMAGES_MODEL,
                    image=img,
                    prompt=prompt,
                    size=size,
                )
            b64 = r.data[0].b64_json
            return base64.b64decode(b64)
        except Exception as e:
            last_err = e
            log.warning("Image edit attempt %s failed: %s", attempt + 1, e)
            await asyncio.sleep(0.8 * (attempt + 1))
    # если edits недоступны — fallback: просто сгенерировать по описанию
    log.info("Image edits unavailable, fallback to generation.")
    return await openai_image_generate(f"Редактируй фото: {prompt}. Сохрани оригинальные цвета, композицию.", size=size)

# ───────── Luma / Runway video ─────────
_ASPECT_RE = re.compile(r"\b(9[:/]\s*16|16[:/]\s*9|1[:/]\s*1|3[:/]\s*4|4[:/]\s*3)\b")
_DUR_RE    = re.compile(r"\b(\d{1,2})\s*(?:сек|sec|seconds?)\b", re.I)

def _parse_aspect_and_duration(s: str) -> tuple[str,int]:
    aspect = "16:9"
    dur = LUMA_DURATION_S
    m = _ASPECT_RE.search(s.replace(" ", ""))
    if m:
        aspect = m.group(1).replace("/", ":").replace(" ", "")
    m2 = _DUR_RE.search(s)
    if m2:
        dur = max(3, min(20, int(m2.group(1))))
    return aspect, dur

async def luma_create_video(prompt: str, aspect: str, duration_s: int) -> str:
    """Возвращает URL видео (mp4) либо пустую строку."""
    headers = {"Authorization": f"Bearer {LUMA_API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        base = await _pick_luma_base(client)
        create_url = f"{base}{LUMA_CREATE_PATH}"
        r = await client.post(create_url, headers=headers, json={
            "prompt": prompt, "aspect_ratio": aspect, "duration": duration_s
        })
        r.raise_for_status()
        data = r.json()
        task_id = data.get("id") or data.get("generation_id") or data.get("task_id")
        if not task_id:
            raise RuntimeError(f"Luma: no id in response: {data}")
        status_url = f"{base}{LUMA_STATUS_PATH.format(id=task_id)}"

        t0 = time.time()
        while time.time() - t0 < LUMA_MAX_WAIT_S:
            rs = await client.get(status_url, headers=headers)
            if rs.status_code == 404:
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
                continue
            rs.raise_for_status()
            d = rs.json()
            state = (d.get("status") or d.get("state") or "").lower()
            if state in ("completed", "succeeded", "success", "ready"):
                url = d.get("output", {}).get("video") or d.get("assets", {}).get("video") or d.get("video")
                if url:
                    return url
                raise RuntimeError(f"Luma finished without url: {d}")
            if state in ("failed", "error", "cancelled"):
                raise RuntimeError(f"Luma failed: {d}")
            await asyncio.sleep(VIDEO_POLL_DELAY_S)
    return ""

async def runway_create_video(prompt: str, ratio: str, duration_s: int) -> str:
    """Возвращает URL видео (mp4) либо пустую строку."""
    headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": RUNWAY_MODEL,
        "prompt": prompt,
        "ratio": ratio,
        "duration": duration_s,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        create_url = f"{RUNWAY_BASE_URL}{RUNWAY_CREATE_PATH}"
        r = await client.post(create_url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        task_id = data.get("id") or data.get("task_id")
        if not task_id:
            raise RuntimeError(f"Runway: no id in response: {data}")
        status_url = f"{RUNWAY_BASE_URL}{RUNWAY_STATUS_PATH.format(id=task_id)}"

        t0 = time.time()
        while time.time() - t0 < RUNWAY_MAX_WAIT_S:
            rs = await client.get(status_url, headers=headers)
            rs.raise_for_status()
            d = rs.json()
            state = (d.get("status") or d.get("state") or "").lower()
            if state in ("succeeded", "completed", "ready"):
                url = d.get("output", {}).get("video") or d.get("video")
                if url:
                    return url
                raise RuntimeError(f"Runway finished without url: {d}")
            if state in ("failed", "error", "cancelled"):
                raise RuntimeError(f"Runway failed: {d}")
            await asyncio.sleep(VIDEO_POLL_DELAY_S)
    return ""

# ───────── Telegram UI texts ─────────
START_TEXT = (
    "Привет! Я GPT-5 PRO бот.\n\n"
    "• Текст → ответ\n"
    "• Фото → описать/отредактировать (cartoon/ретушь/фон)\n"
    "• «Сделай видео … на 9 секунд 9:16» — запущу генерацию (Luma/Runway)\n\n"
    "Озвучку можно включить командой /voice_on и выключить /voice_off."
)

HELP_TEXT = (
    "Команды:\n"
    "/start — главное меню\n"
    "/engines — быстрые кнопки функций\n"
    "/plans — подписка (ЮKassa или списание с USD-баланса)\n"
    "/balance — кошелёк и бюджеты\n"
    "/voice_on /voice_off — озвучка ответов\n"
)

def _main_kb():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎛 Движки"), KeyboardButton("⭐ Подписка")],
            [KeyboardButton("🧾 Баланс"), KeyboardButton("ℹ️ Помощь")],
        ],
        resize_keyboard=True,
    )

# ───────── State: voice flag in DB (very simple, per user) ─────────
def db_init_flags():
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS flags (user_id INTEGER PRIMARY KEY, tts_enabled INTEGER DEFAULT 0)")
    con.commit(); con.close()

def set_tts_enabled(user_id: int, enabled: bool):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO flags(user_id, tts_enabled) VALUES (?, ?)", (user_id, 1 if enabled else 0))
    con.commit(); con.close()

def get_tts_enabled(user_id: int) -> bool:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT tts_enabled FROM flags WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close()
    return bool(row and row[0])

# ───────── Handlers ─────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(START_TEXT, reply_markup=_main_kb(), disable_web_page_preview=True)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, disable_web_page_preview=True)

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_tts_enabled(update.effective_user.id, True)
    await update.effective_message.reply_text("Озвучка включена. Текст + voice-ответы.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_tts_enabled(update.effective_user.id, False)
    await update.effective_message.reply_text("Озвучка выключена. Будет только текст.")

async def cmd_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼️ Картинка из текста", callback_data="eng:image"),
         InlineKeyboardButton("🖌️ Редактировать фото", callback_data="eng:imgedit")],
        [InlineKeyboardButton("🎬 Видео (Luma)", callback_data="eng:luma"),
         InlineKeyboardButton("🎞️ Видео (Runway)", callback_data="eng:runway")],
    ])
    await update.effective_message.reply_text("Выбери движок:", reply_markup=kb)

# ——— SUBSCRIPTIONS UI ———
def _plans_kb():
    rows = []
    for tier, prices in PLAN_PRICE_TABLE.items():
        rows.append([
            InlineKeyboardButton(f"{tier.upper()} — месяц", callback_data=f"plan:{tier}:month"),
            InlineKeyboardButton("квартал", callback_data=f"plan:{tier}:quarter"),
            InlineKeyboardButton("год", callback_data=f"plan:{tier}:year"),
        ])
    rows.append([InlineKeyboardButton("Пополнить USD-кошелёк", callback_data="wallet:topup")])
    return InlineKeyboardMarkup(rows)

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Выберите тариф и срок. Оплата: ЮKassa или списание из USD-кошелька.",
        reply_markup=_plans_kb()
    )

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    w = _wallet_get(user_id)
    total = _wallet_total_get(user_id)
    lim = _limits_for(user_id)
    until = get_subscription_until(user_id)
    until_str = until.strftime("%Y-%m-%d") if until and until > _utcnow() else "нет активной"
    text = (
        f"💼 Кошелёк:\n"
        f"• Единый USD: {total:.2f} USD\n"
        f"• Luma: {w['luma_usd']:.2f} USD, Runway: {w['runway_usd']:.2f} USD, Images: {w['img_usd']:.2f} USD\n\n"
        f"Подписка: {lim['tier']} (до: {until_str})\n"
        f"Дневной лимит текста: {lim['text_per_day']}, бюджеты — Luma {lim['luma_budget_usd']} USD, Runway {lim['runway_budget_usd']} USD, Images {lim['img_budget_usd']} USD."
    )
    await update.effective_message.reply_text(text)

# ——— CALLBACKS: plans & engines ———
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    await q.answer()

    if data.startswith("eng:"):
        eng = data.split(":", 1)[1]
        if eng == "image":
            await q.edit_message_text("Пришлите текстовое описание картинки. Я сгенерирую изображение.")
            context.user_data["pending_image_gen"] = True
        elif eng == "imgedit":
            await q.edit_message_text("Пришлите фото и подпись, что сделать (напр. «сделай мультяшным»).")
        elif eng == "luma":
            await q.edit_message_text("Напишите: «Сделай видео … на 9 секунд 9:16». Я запущу Luma.")
            context.user_data["default_video_engine"] = "luma"
        elif eng == "runway":
            await q.edit_message_text("Напишите: «Сделай видео … на 9 секунд 9:16». Я запущу Runway.")
            context.user_data["default_video_engine"] = "runway"
        return

    if data.startswith("plan:"):
        # plan:<tier>:<term>
        _, tier, term = data.split(":")
        prices = PLAN_PRICE_TABLE[tier]
        rub = prices[term]
        months = TERM_MONTHS[term]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Оплатить ЮKassa", callback_data=f"buy:y:{tier}:{months}:{rub}")],
            [InlineKeyboardButton("Списать с USD-кошелька", callback_data=f"buy:b:{tier}:{months}:{rub}")],
            [InlineKeyboardButton("Назад к тарифам", callback_data="plans:back")],
        ])
        await q.edit_message_text(
            f"Тариф {tier.upper()}, срок {term} → {rub} ₽.\nВыберите способ оплаты:",
            reply_markup=kb
        )
        return

    if data.startswith("plans:back"):
        await q.edit_message_text("Выберите тариф:", reply_markup=_plans_kb())
        return

    if data.startswith("buy:"):
        # buy:<y|b>:<tier>:<months>:<rub>
        _, mode, tier, months, rub = data.split(":")
        months = int(months); rub = int(rub)
        if mode == "b":
            # списание из единого кошелька (конверсия в USD)
            usd_cost = float(rub) / USD_RUB
            ok = _wallet_total_take(update.effective_user.id, usd_cost)
            if not ok:
                await q.edit_message_text(
                    f"Недостаточно USD. Нужно ~{usd_cost:.2f} USD. Пополните кошелёк и повторите."
                )
                return
            until = activate_subscription_with_tier(update.effective_user.id, tier, months)
            await q.edit_message_text(
                f"✅ Подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')} за счёт USD-кошелька."
            )
            return
        else:
            # ЮKassa invoice
            title = _ascii_label(f"{tier.upper()} {months} мес")
            payload = json.dumps({"tier": tier, "months": months})
            prices = [LabeledPrice(label=title, amount=rub * 100)]
            await context.bot.send_invoice(
                chat_id=update.effective_chat.id,
                title=title,
                description=f"Оформление подписки {tier.upper()} на {months} мес.",
                payload=payload,
                provider_token=PROVIDER_TOKEN,
                currency=CURRENCY,
                prices=prices,
                need_name=False,
                need_phone_number=False,
                need_email=False,
                is_flexible=False,
                start_parameter=f"sub_{tier}_{months}",
            )
            await q.edit_message_text("Счёт выставлен. Завершите оплату в ЮKassa.")
            return

    if data.startswith("wallet:topup"):
        await q.edit_message_text(
            "Пополнение единого USD-кошелька поддерживается через CryptoBot (USDT/TON) и ЮKassa (в рублях) — скоро в мини-приложении. Пока что пополнение вручную: напишите в поддержку @gpt5pro_support."
        )
        return

# ——— Payments: precheckout + success ———
async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    try:
        await query.answer(ok=True)
    except TelegramError as e:
        log.error("PreCheckout error: %s", e)
        await query.answer(ok=False, error_message="Ошибка предавторизации платежа. Попробуйте позже.")

async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    payload = {}
    try:
        payload = json.loads(sp.invoice_payload or "{}")
    except Exception:
        payload = {}
    tier = (payload.get("tier") or "pro").lower()
    months = int(payload.get("months") or 1)
    until = activate_subscription_with_tier(update.effective_user.id, tier, months)
    await update.effective_message.reply_text(
        f"✅ Оплата получена. Подписка {tier.upper()} активна до {until.strftime('%Y-%m-%d')}."
    )

# ───────── Media/text handlers ─────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    text = (msg.text or "").strip()

    # быстрые кнопки
    if text == "ℹ️ Помощь":
        return await cmd_help(update, context)
    if text == "🧾 Баланс":
        return await cmd_balance(update, context)
    if text == "⭐ Подписка":
        return await cmd_plans(update, context)
    if text == "🎛 Движки":
        return await cmd_engines(update, context)

    user = update.effective_user
    ok, left, tier = check_text_and_inc(user.id, user.username)
    if not ok:
        await msg.reply_text("Дневной лимит текста исчерпан. Оформите подписку /plans.")
        return

    # детекция намерений на медиа
    intent, rest = detect_media_intent(text)
    if intent == "image":
        await msg.reply_chat_action(action=ChatAction.UPLOAD_PHOTO)
        try:
            img = await openai_image_generate(rest or "Симпатичная иллюстрация, стиль — современный, без текста.")
            await msg.reply_photo(InputFile(BytesIO(img), filename="image.png"))
        except Exception as e:
            log.exception("image gen failed: %s", e)
            await msg.reply_text(f"Не удалось сгенерировать изображение: {e}")
        return

    if intent == "video":
        await msg.reply_chat_action(action=ChatAction.RECORD_VIDEO)
        engine = context.user_data.get("default_video_engine") or ("luma" if LUMA_API_KEY else "runway")
        aspect, dur = _parse_aspect_and_duration(text)
        prompt = rest or text

        # оценим бюджет и спишем/предложим
        est_cost = 0.8 if engine == "luma" else RUNWAY_UNIT_COST_USD
        allowed, note = _can_spend_or_offer(user.id, user.username, engine if engine in ("luma","runway") else "luma", est_cost)
        if not allowed:
            if note.startswith("ASK_SUBSCRIBE"):
                await msg.reply_text("Для генерации видео нужна активная подписка. Оформите /plans.")
            elif note.startswith("OFFER:"):
                need = float(note.split(":")[1])
                rub = _calc_oneoff_price_rub(engine, need)
                await msg.reply_text(
                    f"Нужно доп. {need:.2f} USD бюджета. Пополните USD-кошелёк или оплатите разово: {rub} ₽."
                )
            return

        try:
            if engine == "luma":
                url = await luma_create_video(prompt, aspect, dur)
            else:
                url = await runway_create_video(prompt, RUNWAY_RATIO, dur)
            if not url:
                raise RuntimeError("Пустой URL от движка.")
            await msg.reply_video(video=url, caption=f"{engine.title()} • {dur}s • {aspect}")
            _register_engine_spend(user.id, "luma" if engine == "luma" else "runway", est_cost)
        except Exception as e:
            log.exception("video failed: %s", e)
            await msg.reply_text(f"Не удалось сгенерировать видео: {e}")
        return

    # обычный текст → LLM
    await msg.reply_chat_action(action=ChatAction.TYPING)
    try:
        answer = await ask_openai_text(text)
        tts_enabled = get_tts_enabled(user.id)
        if tts_enabled:
            try:
                voice = await openai_tts_to_ogg(answer)
                await msg.reply_text(answer)
                if voice:
                    await msg.reply_voice(InputFile(BytesIO(voice), filename="voice.ogg"))
                return
            except Exception as e:
                log.warning("TTS send failed: %s", e)
        await msg.reply_text(answer)
    except Exception as e:
        log.exception("text failed: %s", e)
        await msg.reply_text(f"Ошибка ответа: {e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    caption = (msg.caption or "").strip()
    photo = msg.photo[-1]
    f = await photo.get_file()
    b = await f.download_as_bytearray()

    # если пользователь явно просит изменить — редактируем, иначе просто опишем
    do_edit = True if caption else False
    if not caption:
        # если фото без подписи — опишем и подскажем, что можно редактировать
        try:
            desc = await ask_openai_vision(bytes(b))
        except Exception:
            desc = "Получил фотографию. Могу описать/отредактировать. Напишите подпись, например: «сделай мультяшным»."
        await msg.reply_text(desc + "\n\nЧтобы изменить фото — отправьте подпись, например: «сделай мультяшным».")
        return

    # есть подпись → редактируем
    await msg.reply_chat_action(action=ChatAction.UPLOAD_PHOTO)
    try:
        edited = await openai_image_edit(bytes(b), caption)
        await msg.reply_photo(InputFile(BytesIO(edited), filename="edited.png"), caption="Готово ✅")
        _register_engine_spend(update.effective_user.id, "img", IMG_COST_USD)
    except Exception as e:
        log.exception("img edit failed: %s", e)
        await msg.reply_text(f"Не удалось изменить изображение: {e}")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.effective_message.voice
    vf = await voice.get_file()
    ogg = await vf.download_as_bytearray()
    try:
        text = await openai_stt_from_ogg(bytes(ogg))
    except Exception as e:
        await update.effective_message.reply_text(f"Не удалось распознать речь: {e}")
        return
    # и обработаем как текст
    update.effective_message.text = text or "(пустая расшифровка)"
    await handle_text(update, context)

# ───────── Bootstrapping ─────────
def main():
    # DB
    db_init()
    db_init_usage()
    db_init_flags()

    # HTTP stub (healthz + /premium.html) — только для режима polling,
    # чтобы не конфликтовало с run_webhook на том же порту.
    if not USE_WEBHOOK:
        _start_http_stub()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("engines", cmd_engines))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("voice_on", cmd_voice_on))
    app.add_handler(CommandHandler("voice_off", cmd_voice_off))

    # callbacks
    app.add_handler(CallbackQueryHandler(on_callback))
    # payments
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    # messages
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if USE_WEBHOOK:
        # Запускаем как webhook-сервис на PORT
        webhook_url = f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}"
        log.info("Starting webhook on :%s, url=%s", PORT, webhook_url)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH.lstrip("/"),
            webhook_url=webhook_url,
            secret_token=WEBHOOK_SECRET or None,
        )
    else:
        # Поллинг — стабильно для Render background worker
        log.info("Starting polling…")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
