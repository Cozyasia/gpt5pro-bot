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
_CAPABILITY_RE= re.compile(r"(мож(ешь|но|ете).{0,20}(анализ|распозн|читать|созда(ва)?т|дела(ть)?).{0,30}(фото|картинк|изображен|pdf|docx|epub|fb2|аудио|книг))", re.I)

_IMG_WORDS = r"(картин\w+|изображен\w+|фото\w*|рисунк\w+|image|picture|img\b|logo|banner|poster|аватар\w*)"
_VID_WORDS = r"(видео|ролик\w*|анимаци\w*|shorts?|reels?|clip|video|vid\b)"

_CREATE_CMD = r"(сдела(й|йте)|созда(й|йте)|сгенериру(й|йте)|нарису(й|йте)|render|generate|create|make)"

_PREFIXES_VIDEO = [r"^" + _CREATE_CMD + r"\s+видео", r"^video\b", r"^reels?\b", r"^shorts?\b"]
_PREFIXES_IMAGE = [r"^" + _CREATE_CMD + r"\s+(?:картин\w+|изображен\w+|фото\w+|рисунк\w+|аватар\w*)", r"^image\b", r"^picture\b", r"^img\b"]

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
        r = oai_tts.audio.speech.create(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE, input=text, format="opus")
        audio = getattr(r, "content", None)
        if audio is None and hasattr(r, "read"):
            audio = r.read()
        if isinstance(audio, (bytes, bytearray)):
            return bytes(audio)
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

# ───────── Capability Q&A ─────────
_CAP_PDF   = re.compile(r"(pdf|документ(ы)?|файл(ы)?)", re.I)
_CAP_EBOOK = re.compile(r"(ebook|e-?book|электронн(ая|ые)\s+книг|epub|fb2|docx|txt|mobi|azw)", re.I)
_CAP_AUDIO = re.compile(r"(аудио ?книг|audiobook|audio ?book|mp3|m4a|wav|ogg|webm|voice)", re.I)
_CAP_IMAGE = re.compile(r"(изображен|картинк|фото|image|picture|img|аватар)", re.I)
_CAP_VIDEO = re.compile(r"(видео|ролик|shorts?|reels?|clip)", re.I)

def _image_features_text() -> str:
    return (
        "🖼 Что я могу сделать с изображением:\n"
        "• 🔄 Замена фона (включая прозрачный PNG), вырезка объекта.\n"
        "• 🧽 Удаление/добавление объектов, логотипов, надписей.\n"
        "• 👤 Ретушь лица/кожи, отбеливание зубов, сглаживание кожи, корректировка света/теней.\n"
        "• 🎨 Стилезация: мультяшный/аниме/комикс/масло/акварель/карандаш.\n"
        "• 🧯 Восстановление старых/порванных фото, цветизация Ч/Б снимков.\n"
        "• 🔍 Апскейл/резкость (улучшение качества и детализации).\n"
        "• 🧩 Коллажи, превью, постеры, баннеры, аватарки.\n"
        "• 📝 Текст на изображении, мемы, обложки для соцсетей.\n"
        "• 🪄 «Оживление» фото (анимация позы/лица/взгляда, лёгкое движение фона).\n"
        "\nКак прислать:\n"
        "1) Отправь фото с подписью, например: «замени фон на пляж на закате, оставь тень, 1024x1024».\n"
        "2) Если нужно добавить/убрать объекты — перечисли их в подписи.\n"
        "3) Для «оживления» укажи желаемое движение: «поверни голову влево и слегка улыбнись; пусть ветер колышет волосы».\n"
        "4) Если нет исходника — опиши, что сгенерировать: «аватар в стиле пикс-арт, светлая подложка».\n"
    )

def _animate_guide_text() -> str:
    return (
        "✅ Да, могу «оживить» ваши фотографии.\n"
        "Гайд:\n"
        "1) Пришлите фото (лучше портрет/по пояс, лицо ясно видно).\n"
        "2) В подписи укажите, что именно анимировать: поворот/наклон головы, моргание, лёгкая улыбка, "
        "жест рукой, 2–3 шага вперёд/назад, колыхание одежды/волос, панорамное смещение камеры.\n"
        "3) Уточните длительность (5–10 сек) и формат (вертикаль 9:16 или горизонталь 16:9).\n"
        "4) Если хотите менять фон — напишите желаемую сцену (улица Парижа, пляж на закате и т.д.).\n"
        "5) После обработки я пришлю результат. Если потребуется — внесём правки.\n"
        "Также можно написать текстом: «Сделай видео… 9 секунд, 9:16» — предложу Luma/Runway и запущу рендер.\n"
    )

def capability_answer(text: str) -> str | None:
    tl = (text or "").strip().lower()
    if not tl:
        return None

    # Частные вопросы, которые должны давать расширенные ответы
    if "что ты можешь сделать с изображением" in tl or "что можешь сделать с изображением" in tl:
        return _image_features_text()

    if "ты можешь оживить фотограф" in tl or "оживить фото" in tl or "анимировать фото" in tl:
        # Положительный ответ + гайд
        return _animate_guide_text()

    # Общие capability-вопросы
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
            _image_features_text()
            + "\nЗапусти генерацию через команду: /img <описание>.\n"
            "Например: /img неоновый город в дождь, реализм, 1024x1024"
        )
    if _CAP_VIDEO.search(tl) and re.search(r"(мож(ешь|ете)|созда(ва)?т|дела(ть)?|сгенерир)", tl):
        return (
            "Да, могу запускать генерацию коротких видео. Напиши: "
            "«сделай видео … на 9 секунд 9:16». После запроса предложу выбрать Luma или Runway."
        )
    return None

# ───────── Видео: парсинг, очередь, подписи ─────────
_pending_actions: dict[str, dict] = {}

def _new_aid() -> str:
    return uuid.uuid4().hex[:10]

def parse_video_opts_from_text(text: str, default_duration: int, default_ar: str) -> tuple[int, str, str]:
    t = (text or "").lower()
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
    prompt = (text or "").strip()
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
    if len(p) > 500:
        p = p[:497] + "…"
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
                bio = BytesIO(r.content); bio.name = "runway.mp4"
                await update.effective_message.reply_video(
                    video=InputFile(bio),
                    caption=_safe_caption(prompt, "Runway", duration, _norm_ar(ar)),
                )
        except Exception as e:
            log.exception("send runway video failed: %s", e)
            await update.effective_message.reply_text("⚠️ Видео готово, но не удалось отправить файл.")

# ───────── Images (OpenAI) ─────────
async def _do_img_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    """
    Генерация изображения (если функция уже была — замени на эту версию).
    """
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
        b64 = resp.data[0].b64_json
        img_bytes = base64.b64decode(b64)
        await update.effective_message.reply_photo(photo=img_bytes, caption=f"Готово ✅\nЗапрос: {prompt}")
    except Exception as e:
        log.exception("IMG gen error: %s", e)
        await update.effective_message.reply_text("Не удалось создать изображение.")

# ───────── Crypto invoices registry (DB) ─────────
def _db_init_crypto():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS crypto_invoices (
        invoice_id   TEXT PRIMARY KEY,
        user_id      INTEGER NOT NULL,
        kind         TEXT NOT NULL,                 -- 'wallet' | 'subscribe'
        usd_amount   REAL DEFAULT 0.0,
        asset        TEXT,                          -- USDT/TON
        tier         TEXT,                          -- for subscribe
        months       INTEGER,                       -- for subscribe
        created_ts   INTEGER,
        paid_ts      INTEGER,
        status       TEXT                           -- active | paid | expired
    )
    """)
    con.commit(); con.close()

def _crypto_save_invoice(invoice_id: str, user_id: int, kind: str, usd_amount: float, asset: str, tier: str|None=None, months: int|None=None):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO crypto_invoices (invoice_id,user_id,kind,usd_amount,asset,tier,months,created_ts,status)
        VALUES (?,?,?,?,?,?,?, ?, ?)
    """, (invoice_id, user_id, kind, float(usd_amount), asset, tier, months, int(time.time()), "active"))
    con.commit(); con.close()

def _crypto_mark_paid(invoice_id: str):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("UPDATE crypto_invoices SET status='paid', paid_ts=? WHERE invoice_id=?", (int(time.time()), invoice_id))
    con.commit(); con.close()

def _crypto_get_invoice_meta(invoice_id: str) -> dict | None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT invoice_id,user_id,kind,usd_amount,asset,tier,months,status FROM crypto_invoices WHERE invoice_id=?", (invoice_id,))
    row = cur.fetchone(); con.close()
    if not row: return None
    keys = ["invoice_id","user_id","kind","usd_amount","asset","tier","months","status"]
    return {k:v for k,v in zip(keys,row)}

# ───────── Подписки через CryptoBot: расчёт USD и кнопки ─────────
def _plan_usd_amount(tier: str, months: int) -> float:
    """Грубая конвертация из наших RUB цен в USD по курсу USD_RUB."""
    rub = _plan_rub(tier, {1:"month",3:"quarter",12:"year"}[months])
    return round(float(rub) / max(1e-9, USD_RUB), 2)

def _plan_title_desc_crypto(tier: str, months: int) -> tuple[str,str]:
    term_label = {1: "месяц", 3: "квартал", 12: "год"}.get(months, f"{months} мес")
    return (f"Подписка {tier.upper()} • {term_label}",
            f"Оплата подписки {tier.upper()} на {term_label} через CryptoBot.")

# ───────── Обновление текста /plans: добавляем CryptoBot-покупки ─────────
async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["⭐ Тарифы и оформление подписки:"]
    for t in ("start", "pro", "ultimate"):
        p = PLAN_PRICE_TABLE[t]
        lines.append(f"• {t.upper()}: {p['month']}₽/мес • {p['quarter']}₽/квартал • {p['year']}₽/год")
    lines += [
        "",
        _plan_mechanics_text(),
        "💳 Оплата: ЮKassa (RUB) или CryptoBot (USDT/TON).",
    ]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("START — месяц (ЮKassa)",  callback_data="buy:start:1"),
         InlineKeyboardButton("квартал",                  callback_data="buy:start:3"),
         InlineKeyboardButton("год",                      callback_data="buy:start:12")],
        [InlineKeyboardButton("PRO — месяц (ЮKassa)",    callback_data="buy:pro:1"),
         InlineKeyboardButton("квартал",                  callback_data="buy:pro:3"),
         InlineKeyboardButton("год",                      callback_data="buy:pro:12")],
        [InlineKeyboardButton("ULTIMATE — мес (ЮKassa)", callback_data="buy:ultimate:1"),
         InlineKeyboardButton("квартал",                  callback_data="buy:ultimate:3"),
         InlineKeyboardButton("год",                      callback_data="buy:ultimate:12")],
        [InlineKeyboardButton("💠 START — CryptoBot",    callback_data="buyc:start"),
         InlineKeyboardButton("💠 PRO — CryptoBot",      callback_data="buyc:pro"),
         InlineKeyboardButton("💠 ULTIMATE — CryptoBot", callback_data="buyc:ultimate")],
        [InlineKeyboardButton("Открыть страницу тарифов (мини-приложение)", web_app=WebAppInfo(url=TARIFF_URL))],
    ])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb, disable_web_page_preview=True)

# ───────── Кнопочное меню выбора периода для CryptoBot ─────────
def _crypto_sub_periods_kb(tier: str) -> InlineKeyboardMarkup:
    # цены в USD для справки
    usd_m  = _plan_usd_amount(tier, 1)
    usd_q  = _plan_usd_amount(tier, 3)
    usd_y  = _plan_usd_amount(tier, 12)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"1 мес • ≈ ${usd_m}",  callback_data=f"buyc:{tier}:1")],
        [InlineKeyboardButton(f"3 мес • ≈ ${usd_q}",  callback_data=f"buyc:{tier}:3")],
        [InlineKeyboardButton(f"12 мес • ≈ ${usd_y}", callback_data=f"buyc:{tier}:12")],
    ])

# ───────── Генерализованный поллер CryptoBot-инвойсов (кошелёк + подписка) ─────────
async def _poll_crypto_invoice(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, user_id: int, invoice_id: str):
    deadline = time.time() + 900
    while time.time() < deadline:
        await asyncio.sleep(6.0)
        inv = await _crypto_get_invoice(invoice_id)
        if not inv:
            continue
        st = (inv.get("status") or "").lower()  # active, paid, expired
        if st == "paid":
            meta = _crypto_get_invoice_meta(invoice_id)
            _crypto_mark_paid(invoice_id)
            if meta and meta.get("kind") == "subscribe":
                tier   = meta.get("tier") or "pro"
                months = int(meta.get("months") or 1)
                until  = activate_subscription_with_tier(user_id, tier, months)
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=f"💠 Оплата через CryptoBot получена.\n⭐ Подписка {tier.upper()} активна до {until.strftime('%Y-%m-%d')}."
                    )
                return
            # fallback: пополнение единого USD-кошелька
            usd_amount = float(inv.get("amount", 0.0))
            if (inv.get("asset") or "").upper() == "TON":
                usd_amount *= TON_USD_RATE
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
                    text="⏳ Ссылка CryptoBot истекла. Создайте новый счёт."
                )
            return
    with contextlib.suppress(Exception):
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text="⏳ Время ожидания оплаты истекло. Если оплатили — нажмите «Проверить оплату»."
        )

# ───────── Ответы про работу с изображениями / «оживление» ─────────
def image_capabilities_text() -> str:
    return (
        "🖼 Что я могу сделать с изображением:\n"
        "• Замена фона (зелёный/любой фон, вырезка объекта)\n"
        "• Ретушь: уберу шум/блики/дефекты, улучшу резкость\n"
        "• Тонкая правка: осветление/цветокор, кадрирование, масштаб\n"
        "• Удаление/добавление объектов (надписи, предметы, логотипы)\n"
        "• Апскейл (увеличение разрешения) и восстановление старых фото\n"
        "• Стилизация: «рисунок», «комикс», «аниме», «акварель» и др.\n"
        "• Вариации/перекомпозиция по описанию (inpaint/outpaint)\n"
        "• 📽 «Оживление» фото: лёгкая анимация лица, взгляд, улыбка, поворот головы, панорама, небольшой движ\n\n"
        "Как пользоваться:\n"
        "1) Пришлите фото с подписью, например: «замени фон на белый» / «добавь надпись справа».\n"
        "2) Для точной правки напишите конкретные зоны: «убери дату в левом нижнем углу».\n"
        "3) Для стилизации укажите стиль: «сделай комикс-версию».\n"
        "4) Для «оживления» напишите: «оживи фото — лёгкое движение камеры, улыбка».\n"
        "Если задача крупная, я предложу способ оплаты (подписка/кошелёк) и запущу обработку."
    )

def image_animate_guide() -> str:
    return (
        "Да — могу оживить фотографии ✅\n\n"
        "Гайд:\n"
        "1) Пришлите фото (или несколько) в чат.\n"
        "2) В подписи укажите желаемый эффект: «лёгкая анимация лица (улыбка, моргание)», «панорамный сдвиг камеры», «плавный зум», «оживи фон (волны/облака)».\n"
        "3) Если нужно — опишите длительность (5–10 сек) и формат (вертикально 9:16 / горизонтально 16:9).\n"
        "4) Я оценю бюджет (входит в тариф или спишу из кошелька) и запущу рендер. Готовый клип пришлю сюда.\n\n"
        "Подписку можно оплатить через ЮKassa или CryptoBot (USDT/TON) — команда /plans."
    )

# ───────── Обновлённый text-pipeline: ловим вопросы про изображение/оживление ─────────
async def _process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    username = (update.effective_user.username or "")
    ok, left, tier = check_text_and_inc(user_id, username)
    if not ok:
        await update.effective_message.reply_text("Дневной лимит текстовых запросов исчерпан. Оформите подписку через /plans.")
        return

    tnorm = (text or "").strip()
    tl = tnorm.lower()

    # Спец-триггеры (включая случаи после STT «🗣️ Распознано: …»)
    if "что ты можешь сделать с изображением" in tl or "что можешь сделать с изображением" in tl \
       or ("можешь" in tl and "с изображен" in tl and "что" in tl):
        ans = image_capabilities_text()
        await update.effective_message.reply_text(ans)
        await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])
        return

    if ("можешь оживить" in tl and "фотограф" in tl) or ("оживи" in tl and "фото" in tl):
        ans = image_animate_guide()
        await update.effective_message.reply_text(ans)
        await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])
        return

    if is_smalltalk(tnorm):
        ans = await ask_openai_text(tnorm)
        await update.effective_message.reply_text(ans)
        await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])
        return

    cap_ans = capability_answer(tnorm)
    if cap_ans:
        await update.effective_message.reply_text(cap_ans)
        await maybe_tts_reply(update, context, cap_ans[:TTS_MAX_CHARS])
        return

    intent, clean = detect_media_intent(tnorm)

    if intent == "image":
        async def _go():
            await _do_img_generate(update, context, clean or tnorm)
        await _try_pay_then_do(
            update, context, user_id, "img", IMG_COST_USD, _go,
            remember_kind="img_generate",
            remember_payload={"prompt": clean or tnorm}
        )
        return

    if intent == "video":
        dur, ar, prompt = parse_video_opts_from_text(
            clean or tnorm,
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

    # Веб-контекст (опционально)
    web_ctx = ""
    try:
        if tavily and should_browse(tnorm):
            r = tavily.search(query=tnorm, max_results=4)
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

    ans = await ask_openai_text(tnorm, web_ctx=web_ctx)
    if not ans or ans.strip() == "" or "не получилось получить ответ" in (ans or "").lower():
        ans = "⚠️ Сейчас не удалось получить ответ от модели. Я всё равно на связи — попробуй переформулировать запрос или повторить через минуту."
    await update.effective_message.reply_text(ans)
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])

# ───────── Обновлённый on_cb с CryptoBot-подписками и унифицированным поллером ─────────
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
            payload = "t=3"
            ok = await _send_invoice_rub("Пополнение баланса", "Единый кошелёк для перерасходов.", amount_rub, payload, update)
            await q.answer("Выставляю счёт…" if ok else "Не удалось выставить счёт", show_alert=not ok)
            return

        # TOPUP CRYPTO через CryptoBot (кошелёк)
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
            _crypto_save_invoice(inv_id, update.effective_user.id, "wallet", usd_amount, asset)
            msg = await update.effective_message.reply_text(
                f"Оплатите через CryptoBot: ≈ ${usd_amount:.2f} ({asset}).\nПосле оплаты баланс пополнится автоматически.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить в CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("Проверить оплату", callback_data=f"crypto:check:{inv_id}")]
                ])
            )
            context.application.create_task(_poll_crypto_invoice(
                context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id
            ))
            return

        # Проверка CryptoBot инвойса (и для кошелька, и для подписки)
        if data.startswith("crypto:check:"):
            await q.answer()
            inv_id = data.split(":", 2)[-1]
            inv = await _crypto_get_invoice(inv_id)
            if not inv:
                await q.edit_message_text("Не нашёл счёт. Создайте новый.")
                return
            st = (inv.get("status") or "").lower()
            if st == "paid":
                # сработает универсальная логика
                await q.edit_message_text("✅ Платёж подтверждён. Проверяю и активирую…")
                meta = _crypto_get_invoice_meta(inv_id)
                if meta and meta.get("kind") == "subscribe":
                    tier = meta.get("tier") or "pro"
                    months = int(meta.get("months") or 1)
                    until = activate_subscription_with_tier(update.effective_user.id, tier, months)
                    await q.edit_message_text(f"💠 Подписка {tier.upper()} активна до {until.strftime('%Y-%m-%d')}.")
                else:
                    usd_amount = float(inv.get("amount", 0.0))
                    if (inv.get("asset") or "").upper() == "TON":
                        usd_amount *= TON_USD_RATE
                    _wallet_total_add(update.effective_user.id, usd_amount)
                    await q.edit_message_text(f"💳 Баланс пополнен на ≈ ${usd_amount:.2f}.")
            elif st == "active":
                await q.answer("Платёж ещё не подтверждён", show_alert=True)
            else:
                await q.edit_message_text(f"Статус счёта: {st}")
            return

        # ЮKassa подписки (как было)
        if data.startswith("buy:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            payload, amount_rub, title = _plan_payload_and_amount(tier, months)
            desc = f"Оформление подписки {tier.upper()} на {months} мес."
            ok = await _send_invoice_rub(title, desc, amount_rub, payload, update)
            await q.answer("Выставляю счёт…" if ok else "Не удалось выставить счёт", show_alert=not ok)
            return

        # CryptoBot подписки: выбор тарифа, затем периода
        if data.startswith("buyc:") and data.count(":") == 1:
            await q.answer()
            _, tier = data.split(":", 1)
            await q.edit_message_text(
                f"Выберите период подписки {tier.upper()} (CryptoBot):",
                reply_markup=_crypto_sub_periods_kb(tier)
            )
            return

        # CryptoBot подписки: создание инвойса
        if data.startswith("buyc:") and data.count(":") == 2:
            await q.answer()
            if not CRYPTO_PAY_API_TOKEN:
                await q.edit_message_text("CryptoBot не настроен.")
                return
            _, tier, months_s = data.split(":")
            months = int(months_s)
            usd = _plan_usd_amount(tier, months)
            title, desc = _plan_title_desc_crypto(tier, months)
            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(usd, asset="USDT", description=title)
            if not inv_id or not pay_url:
                await q.edit_message_text("Не удалось создать счёт в CryptoBot.")
                return
            _crypto_save_invoice(inv_id, update.effective_user.id, "subscribe", usd_amount, asset, tier=tier, months=months)
            msg = await update.effective_message.reply_text(
                f"{desc}\nСумма: ≈ ${usd_amount:.2f} ({asset}).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить в CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("Проверить оплату", callback_data=f"crypto:check:{inv_id}")]
                ])
            )
            context.application.create_task(_poll_crypto_invoice(
                context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id
            ))
            return

        # Выбор движка для видео
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

        # Переключатели «движков» (доступ/лимиты)
        if data.startswith("engine:"):
            await q.answer()
            engine = data.split(":", 1)[1]  # gpt|images|luma|runway|midjourney|stt_tts
            username = (update.effective_user.username or "")
            if is_unlimited(update.effective_user.id, username):
                await q.edit_message_text(
                    f"✅ Движок «{engine}» доступен без ограничений.\n"
                    f"Отправь задачу, например: «сделай видео ретро-авто, 9 секунд, 9:16»."
                ); return
            if engine in ("gpt", "stt_tts", "midjourney"):
                await q.edit_message_text(
                    f"✅ Выбран «{engine}». Отправь запрос текстом/фото. "
                    f"Для Luma/Runway/Images действуют дневные бюджеты тарифа."
                ); return
            est_cost = IMG_COST_USD if engine == "images" else (0.40 if engine == "luma" else max(1.0, RUNWAY_UNIT_COST_USD))
            map_engine = {"images":"img","luma":"luma","runway":"runway"}[engine]
            ok, offer = _can_spend_or_offer(update.effective_user.id, username, map_engine, est_cost)
            if ok:
                await q.edit_message_text(
                    "✅ Доступно. "
                    + ("Запусти: /img кот в очках" if engine == "images"
                       else "Напиши: «сделай видео … 9 секунд 9:16» — предложу Luma/Runway.")
                ); return
            if offer == "ASK_SUBSCRIBE":
                await q.edit_message_text(
                    "Для этого движка нужна активная подписка или единый баланс. Откройте /plans или пополните «🧾 Баланс».",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
                         [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
                    ),
                ); return
            try:
                need_usd = float(offer.split(":", 1)[-1])
            except Exception:
                need_usd = est_cost
            amount_rub = _calc_oneoff_price_rub(map_engine, need_usd)
            await q.edit_message_text(
                f"Ваш дневной лимит по «{engine}» исчерпан. Разовая покупка ≈ {amount_rub} ₽ "
                f"или пополните баланс в «🧾 Баланс».",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
                     [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
                ),
            ); return

        await q.answer("Неизвестная команда", show_alert=True)

    except Exception as e:
        log.exception("on_cb error: %s", e)
    finally:
        with contextlib.suppress(Exception):
            await q.answer()

# ───────── HELP: патч текста подсказок (добавляем CryptoBot и гайды по изображениям) ─────────
HELP_TEXT = (
    "Подсказки:\n"
    "• /plans — тарифы и оплата подписки (ЮKassa или CryptoBot USDT/TON)\n"
    "• /img кот с очками — сгенерирует картинку (OpenAI Images)\n"
    "• «сделай видео … 9 секунд 9:16» — предложу Luma или Runway\n"
    "• Пришли PDF/EPUB/DOCX/FB2/TXT — извлеку текст и сделаю конспект\n"
    "• Пришли фото с подписью — выполню правки (замена фона, ретушь, надпись и т.д.)\n"
    "• /what_image — полный список функций по изображениям\n"
    "• «оживи фото — 9 секунд 9:16» — сделаю анимированный клип из фото\n"
    "• «🧾 Баланс» — единый кошелёк (USD) для перерасходов по Luma/Runway/Images\n"
    "• /voice_on и /voice_off — озвучка ответов (OGG/Opus)\n"
)

# ───────── Быстрая команда для описания всех возможностей по изображениям ─────────
async def cmd_what_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = image_capabilities_text()
    await update.effective_message.reply_text(ans)
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])

# ───────── Уточнение текста приветствия (необязательный патч) ─────────
START_TEXT = (
    "Привет! Я GPT-бот с тарифами, кошельком и медиа-движками.\n\n"
    "Что умею:\n"
    "• 💬 Текст/фото/документы (GPT)\n"
    "• 🎬 Видео Luma (5/9/10 c, 9:16/16:9)\n"
    "• 🎥 Видео Runway (PRO)\n"
    "• 🖼 Картинки — команда /img <промпт>\n"
    "• 🗣 STT/TTS — распознаю речь и озвучиваю ответы (/voice_on)\n"
    "• 🧾 Баланс — единый USD-кошелёк для перерасходов\n\n"
    "Оплата подписки: ЮKassa или CryptoBot (USDT/TON) — смотри /plans.\n"
    "Для списка возможностей по изображениям набери /what_image."
) 

# ───────── Подробный список возможностей по изображениям ─────────
def image_capabilities_text() -> str:
    return (
        "🖼 Что я могу сделать с изображением, если ты пришлёшь фото:\n"
        "1) Замена фона (белый/прозрачный/любой фон по описанию).\n"
        "2) Ретушь и улучшение качества (шумы, резкость, освещение).\n"
        "3) Удаление/добавление объектов и текста (например, убрать лишние провода, добавить логотип, подпись).\n"
        "4) Стилизация (cartoon/comic/anime/фильм-нуар/акварель и т.д.).\n"
        "5) Цветокоррекция, ч/б → цвет, винтаж и т.п.\n"
        "6) Кроп/ресайз под соцсети (Stories/Reels/аватар/обложка).\n"
        "7) Сборка коллажей/баннеров, подготовка превью.\n"
        "8) «Оживление» фото — короткий клип (5–10 сек), панорама-камера, лёгкое движение, улыбка/поворот головы (где возможно).\n\n"
        "Как запросить: пришли фото и в подписи коротко опиши задачу (пример: «замени фон на белый», «сделай мультипликационный стиль»)."
    )

def animate_guide_text() -> str:
    return (
        "✅ Да, я могу «оживить» фотографию.\n\n"
        "Как сделать:\n"
        "1) Пришли фото одним сообщением и в подписи укажи запрос, например:\n"
        "   • «оживи фото, 9 секунд, 9:16 — лёгкий поворот головы и улыбка»\n"
        "   • «сделай плавный зум-ин и панораму по лицу, 5 секунд, 1:1»\n"
        "2) Я предложу выбрать движок (Luma/Runway) и запущу рендер.\n"
        "3) Получишь готовый короткий клип. Если нужно — уточним и перерендерим.\n\n"
        "Подсказки: длительность 5/9/10 сек; формат 9:16/16:9/1:1. Можно добавить стиль сцены."
    )

# ───────── Специальные триггеры под фразы из распознавания речи ─────────
_RE_ASK_IMAGE_CAPS = re.compile(r"(что|какие)\s+.*(можешь|можно|умеешь).*(с|c)\s*изображен|что.*сделать.*с.*фото", re.I)
_RE_ASK_ANIMATE    = re.compile(r"(можешь|можно|умеешь).*(оживить|анимировать).*(фото|фотографи)", re.I)

def _maybe_special_image_intents(text: str) -> str | None:
    tl = (text or "").strip().lower()
    if not tl:
        return None
    # точные формулировки из ТЗ
    if "что ты можешь сделать с изображением" in tl or _RE_ASK_IMAGE_CAPS.search(tl):
        return image_capabilities_text()
    if "ты можешь оживить фотограф" in tl or _RE_ASK_ANIMATE.search(tl):
        return animate_guide_text()
    return None

# ───────── Быстрая команда для описания всех возможностей по изображениям ─────────
async def cmd_what_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = image_capabilities_text()
    await update.effective_message.reply_text(ans)
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])


# ───────── Команды /start, /help, /img, /plans, /balance и текстовый пайплайн ─────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if BANNER_URL:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_photo(BANNER_URL)
    await update.effective_message.reply_text(START_TEXT, disable_web_page_preview=True)
    await maybe_tts_reply(update, context, START_TEXT[:TTS_MAX_CHARS])

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, disable_web_page_preview=True)

async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Пример: /img кот в очках в стиле ретровейв
    text = (update.effective_message.text or "").strip()
    prompt = re.sub(r"^/img(@[A-Za-z0-9_]+)?\s*", "", text, flags=re.I).strip()
    if not prompt:
        await update.effective_message.reply_text("Напиши после /img что сгенерировать. Пример:\n/img кот в очках, неон, 1024x1024")
        return
    user_id = update.effective_user.id
    username = (update.effective_user.username or "")
    # списываем бюджет/кошелёк при необходимости
    async def _go():
        await _do_img_generate(update, context, prompt)
        _register_engine_spend(user_id, "img", IMG_COST_USD)
    await _try_pay_then_do(update, context, user_id, "img", IMG_COST_USD, _go,
                           remember_kind="img_generate", remember_payload={"prompt": prompt})

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.effective_message.text or ""
    # быстрые спец-фразы из распознавания речи
    special = _maybe_special_image_intents(text)
    if special:
        await update.effective_message.reply_text(special)
        await maybe_tts_reply(update, context, special[:TTS_MAX_CHARS])
        return
    await _process_text(update, context, text)


# ───────── Баланс и пополнения ─────────
def _plan_rub(tier: str, term: str) -> int:
    tier = (tier or "pro").lower()
    term = (term or "month").lower()
    if tier not in PLAN_PRICE_TABLE or term not in PLAN_PRICE_TABLE[tier]:
        return PLAN_PRICE_TABLE["pro"]["month"]
    return int(PLAN_PRICE_TABLE[tier][term])

def _plan_payload_and_amount(tier: str, months: int) -> tuple[str, int, str]:
    # payload для Telegram Payments и сумма в рублях
    term_map = {1: "month", 3: "quarter", 12: "year"}
    term = term_map.get(months, "month")
    amount_rub = _plan_rub(tier, term)
    title = f"Подписка {tier.upper()} • {months} мес"
    payload = f"plan:{tier}:{months}"
    return payload, amount_rub, title

def _calc_oneoff_price_rub(engine: str, need_usd: float) -> int:
    usd = float(max(0.0, need_usd))
    markup = ONEOFF_MARKUP_DEFAULT
    if engine == "runway":
        markup = ONEOFF_MARKUP_RUNWAY
    rub = int(round(usd * USD_RUB * (1.0 + markup)))
    return max(MIN_RUB_FOR_INVOICE, rub)

async def _send_invoice_rub(title: str, desc: str, amount_rub: int, payload: str, update: Update) -> bool:
    if not PROVIDER_TOKEN:
        await update.effective_message.reply_text("Платёж через ЮKassa не настроен (нет PROVIDER_TOKEN_YOOKASSA).")
        return False
    prices = [LabeledPrice(label=_ascii_label(title), amount=int(amount_rub) * 100)]
    try:
        bot = update.get_bot()
        await bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=title[:32],
            description=(desc or title)[:255],
            payload=payload,
            provider_token=PROVIDER_TOKEN,
            currency=CURRENCY,
            prices=prices,
            need_name=False, need_phone_number=False, need_email=False, need_shipping_address=False,
            is_flexible=False,
        )
        return True
    except TelegramError as e:
        log.exception("send_invoice failed: %s", e)
        return False

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Разрешаем все валидные счета
    q = update.pre_checkout_query
    with contextlib.suppress(Exception):
        await q.answer(ok=True)

async def on_success_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.effective_message.successful_payment
    payload = (sp.invoice_payload or "").strip()
    user_id = update.effective_user.id
    if payload.startswith("plan:"):
        # plan:<tier>:<months>
        try:
            _, tier, months_s = payload.split(":")
            months = int(months_s)
        except Exception:
            tier, months = "pro", 1
        until = activate_subscription_with_tier(user_id, tier, months)
        await update.effective_message.reply_text(
            f"✅ Подписка {tier.upper()} активна до {until.strftime('%Y-%m-%d')}."
        )
        return
    # пополнение баланса (RUB → USD)
    try:
        rub = sp.total_amount / 100.0
    except Exception:
        rub = 0.0
    usd = max(0.0, rub / max(1e-9, USD_RUB))
    _wallet_total_add(user_id, usd)
    await update.effective_message.reply_text(
        f"💳 Баланс пополнен на ≈ ${usd:.2f}. Используйте Luma/Runway/Images без задержек."
    )

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w = _wallet_get(update.effective_user.id)
    tot = _wallet_total_get(update.effective_user.id)
    y = _usage_row(update.effective_user.id)
    tier = get_subscription_tier(update.effective_user.id)
    await update.effective_message.reply_text(
        "🧾 Баланс и лимиты:\n"
        f"• Подписка: {tier.upper()}\n"
        f"• Единый кошелёк (USD): {tot:.2f}\n"
        f"• Сегодня потрачено — Luma: ${y['luma_usd']:.2f}, Runway: ${y['runway_usd']:.2f}, Images: ${y['img_usd']:.2f}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Пополнить (RUB)", callback_data="topup")],
            [InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))]
        ])
    )

async def _send_topup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Пополнить 300 ₽", callback_data="topup:rub:300"),
         InlineKeyboardButton("600 ₽",           callback_data="topup:rub:600"),
         InlineKeyboardButton("1500 ₽",          callback_data="topup:rub:1500")],
        [InlineKeyboardButton("CryptoBot $5",  callback_data="topup:crypto:5"),
         InlineKeyboardButton("$10",           callback_data="topup:crypto:10"),
         InlineKeyboardButton("$25",           callback_data="topup:crypto:25")]
    ])
    await update.effective_message.reply_text("Выберите способ пополнения:", reply_markup=kb)


# ───────── Лимиты: учёт текста/движков и офферы оплаты ─────────
def check_text_and_inc(user_id: int, username: str) -> tuple[bool, int, str]:
    tier = get_subscription_tier(user_id)
    if is_unlimited(user_id, username):
        _usage_update(user_id, text_count=1)
        return True, 10**9, "ultimate"
    lim = LIMITS.get(tier, LIMITS["free"])
    row = _usage_row(user_id)
    if row["text_count"] < lim["text_per_day"]:
        _usage_update(user_id, text_count=1)
        return True, lim["text_per_day"] - (row["text_count"] + 1), tier
    return False, 0, tier

def _register_engine_spend(user_id: int, engine: str, usd: float):
    usd = float(max(0.0, usd))
    if engine == "luma":
        _usage_update(user_id, luma_usd=usd)
    elif engine == "runway":
        _usage_update(user_id, runway_usd=usd)
    elif engine == "img":
        _usage_update(user_id, img_usd=usd)

def _can_spend_or_offer(user_id: int, username: str, engine: str, est_cost_usd: float) -> tuple[bool, str | None]:
    if is_unlimited(user_id, username):
        return True, None
    tier = get_subscription_tier(user_id)
    lim = LIMITS.get(tier, LIMITS["free"])
    y = _usage_row(user_id)
    need = float(est_cost_usd)
    # бюджет тарифа
    budget_left = 0.0
    if engine == "luma":
        budget_left = max(0.0, lim["luma_budget_usd"] - y["luma_usd"])
    elif engine == "runway":
        budget_left = max(0.0, lim["runway_budget_usd"] - y["runway_usd"])
    elif engine == "img":
        budget_left = max(0.0, lim["img_budget_usd"] - y["img_usd"])
    if budget_left + 1e-9 >= need:
        return True, None
    # пробуем единый кошелёк
    tot = _wallet_total_get(user_id)
    if tot + 1e-9 >= need:
        return True, None
    # нет денег — оффер
    if tier == "free":
        return False, "ASK_SUBSCRIBE"
    return False, f"NEED_USD:{max(0.0, need - max(budget_left, 0.0) - max(tot, 0.0)):.2f}"

async def _try_pay_then_do(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    engine: str,
    est_cost_usd: float,
    coro_callable,
    remember_kind: str = "",
    remember_payload: dict | None = None,
):
    username = (update.effective_user.username or "")
    ok, offer = _can_spend_or_offer(user_id, username, engine, est_cost_usd)
    if ok:
        # Если не хватает тарифа — сперва списываем из кошелька (при необходимости)
        tot = _wallet_total_get(user_id)
        need = float(est_cost_usd)
        if tot + 1e-9 >= need:
            if _wallet_total_take(user_id, need):
                pass
        await coro_callable()
        return
    # Оффер тарифа/пополнения
    if offer == "ASK_SUBSCRIBE":
        await update.effective_message.reply_text(
            "Для этого действия нужна подписка или единый баланс.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
                 [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
            ),
        )
        return
    # Предложение доплаты
    try:
        need_usd = float(offer.split(":", 1)[-1])
    except Exception:
        need_usd = est_cost_usd
    amount_rub = _calc_oneoff_price_rub(engine, need_usd)
    await update.effective_message.reply_text(
        f"Не хватает бюджета/баланса. Разовая доплата ≈ {amount_rub} ₽ или пополните через CryptoBot.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Оплатить (RUB)", callback_data="topup")],
            [InlineKeyboardButton("💠 CryptoBot $10", callback_data="topup:crypto:10")]
        ])
    )


# ───────── CryptoBot API ─────────
CRYPTO_PAY_API_TOKEN = os.environ.get("CRYPTO_PAY_API_TOKEN", "").strip()
CRYPTO_BASE_URL = "https://pay.crypt.bot/api"
TON_USD_RATE = float(os.environ.get("TON_USD_RATE", "6.0"))

def _crypto_headers():
    return {"Content-Type": "application/json", "Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN}

async def _crypto_create_invoice(usd_amount: float, asset: str = "USDT", description: str = "Payment"):
    if not CRYPTO_PAY_API_TOKEN:
        return None, None, 0.0, asset
    payload = {
        "asset": (asset or "USDT").upper(),
        "amount": f"{float(usd_amount):.2f}",
        "description": description[:1024],
        "allow_comments": False,
        "allow_anonymous": True
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{CRYPTO_BASE_URL}/createInvoice", headers=_crypto_headers(), json=payload)
            r.raise_for_status()
            j = r.json() or {}
            res = j.get("result") or {}
            invoice_id = res.get("invoice_id")
            pay_url = res.get("pay_url")
            amount = float(res.get("amount", payload["amount"]))
            asset  = res.get("asset", asset)
            return invoice_id, pay_url, amount, asset
    except Exception as e:
        log.exception("Crypto createInvoice error: %s", e)
        return None, None, 0.0, asset

async def _crypto_get_invoice(invoice_id: str) -> dict | None:
    if not CRYPTO_PAY_API_TOKEN:
        return None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{CRYPTO_BASE_URL}/getInvoices?invoice_ids={invoice_id}", headers=_crypto_headers())
            r.raise_for_status()
            j = r.json() or {}
            arr = j.get("result") or []
            for it in arr:
                if str(it.get("invoice_id")) == str(invoice_id):
                    return it
            return None
    except Exception as e:
        log.exception("Crypto getInvoices error: %s", e)
        return None


# ───────── Регистрация хэндлеров и запуск ─────────
def main():
    # HTTP stub для Render/healthz
    _start_http_stub()

    # DB
    db_init()
    db_init_usage()
    _db_init_prefs()
    _db_init_crypto()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("img",   cmd_img))
    app.add_handler(CommandHandler("what_image", cmd_what_image))
    app.add_handler(CommandHandler("voice_on",  cmd_voice_on))
    app.add_handler(CommandHandler("voice_off", cmd_voice_off))

    # Платежи
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.StatusUpdate.SUCCESSFUL_PAYMENT, on_success_payment))

    # Callback-кнопки
    app.add_handler(CallbackQueryHandler(on_cb))

    # Текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # Запуск: webhook или polling
    if USE_WEBHOOK:
        # Настраиваем вебхук
        url = f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}"
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            secret_token=(WEBHOOK_SECRET or None),
            webhook_url=url,
            drop_pending_updates=True,
        )
    else:
        app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
