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
from datetime import datetime, timedelta
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
RUNWAY_MODEL        = os.environ.get("RUNWAY_MODEL", "gen3a_turbo").strip()     # важно: валидная модель Runway
RUNWAY_RATIO        = os.environ.get("RUNWAY_RATIO", "720:1280").strip()
RUNWAY_DURATION_S   = int(os.environ.get("RUNWAY_DURATION_S", "8") or 8)

# Luma — ключ и базовые параметры
LUMA_API_KEY     = os.environ.get("LUMA_API_KEY", "").strip()
LUMA_MODEL       = os.environ.get("LUMA_MODEL", "ray-2").strip()
LUMA_ASPECT      = os.environ.get("LUMA_ASPECT", "16:9").strip()
LUMA_DURATION_S  = int((os.environ.get("LUMA_DURATION_S") or "6").strip() or 6)

# ВАЖНО: рабочий домен Luma — api.lumalabs.ai
LUMA_BASE_URL    = (os.environ.get("LUMA_BASE_URL", "https://api.lumalabs.ai") or "https://api.lumalabs.ai").strip().rstrip("/")

# Можно указать несколько запасных баз (через ; или ,)
# Пример в ENV:  https://api.lumalabs.ai;https://api.luma.ai
_LUMA_FB_RAW     = os.environ.get("LUMA_FALLBACKS", "https://api.lumalabs.ai;https://api.luma.ai")
LUMA_FALLBACKS   = [u.strip().rstrip("/") for u in re.split(r"[;,]\s*", _LUMA_FB_RAW) if u and u.strip()]

# Пути Luma
LUMA_CREATE_PATH = (os.environ.get("LUMA_CREATE_PATH", "/v1/dream") or "/v1/dream").strip()
LUMA_STATUS_PATH = (os.environ.get("LUMA_STATUS_PATH", "/v1/dream/{id}") or "/v1/dream/{id}").strip()

# Runway — базовые значения
RUNWAY_BASE_URL    = (os.environ.get("RUNWAY_BASE_URL", "https://api.runwayml.com") or "https://api.runwayml.com").strip().rstrip("/")
RUNWAY_CREATE_PATH = (os.environ.get("RUNWAY_CREATE_PATH", "/v1/tasks") or "/v1/tasks").strip()
RUNWAY_STATUS_PATH = (os.environ.get("RUNWAY_STATUS_PATH", "/v1/tasks/{id}") or "/v1/tasks/{id}").strip()

# Таймауты и поллинг
LUMA_MAX_WAIT_S     = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)      # 15 мин
RUNWAY_MAX_WAIT_S   = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "1200").strip() or 1200)  # 20 мин
VIDEO_POLL_DELAY_S  = float((os.environ.get("VIDEO_POLL_DELAY_S") or "6.0").strip() or 6.0)

# --------- UTILS ---------
_LUMA_ACTIVE_BASE: str | None = None  # кэш последнего живого базового URL

async def _pick_luma_base(client: httpx.AsyncClient) -> str:
    """
    Возвращает живой базовый URL для Luma.
    Порядок: LUMA_BASE_URL → LUMA_FALLBACKS.
    404 для OPTIONS — норм: DNS/TLS/роут ок, значит базу можно брать.
    """
    global _LUMA_ACTIVE_BASE

    # Если уже нашли живую базу ранее — пробуем её первой
    candidates: list[str] = []
    if _LUMA_ACTIVE_BASE:
        candidates.append(_LUMA_ACTIVE_BASE)

    if LUMA_BASE_URL and LUMA_BASE_URL not in candidates:
        candidates.append(LUMA_BASE_URL)

    for b in LUMA_FALLBACKS:
        if b not in candidates:
            candidates.append(b)

    # Быстрый «прозвон» OPTIONS
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

    # ничего не ответило — вернём основной; пусть упадёт явно
    return candidates[0] if candidates else "https://api.lumalabs.ai"
    
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

# минимальная сумма инвойса (защита от Currency_total_amount_invalid)
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
UNLIM_USERNAMES.add("gpt5pro_support")  # гарантируем безлимит для сервисного аккаунта

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

# HTTP stub для Render Web Service (healthcheck + редирект premium.html)
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
        def log_message(self, *_):  # тише
            return
    try:
        srv = HTTPServer(("0.0.0.0", PORT), _H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log.info("HTTP stub bound on 0.0.0.0:%s", PORT)
    except Exception as e:
        log.exception("HTTP stub start failed: %s", e)

# Текстовый LLM (автовыбор OpenRouter base_url при необходимости)
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

def activate_subscription(user_id: int, months: int = 1):
    now = datetime.utcnow()
    until = now + timedelta(days=30 * months)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT until_ts FROM subscriptions WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row and row[0] and row[0] > int(now.timestamp()):
        current_until = datetime.utcfromtimestamp(row[0])
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
    return None if not row else datetime.utcfromtimestamp(row[0])

def set_subscription_tier(user_id: int, tier: str):
    tier = (tier or "pro").lower()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO subscriptions(user_id, until_ts, tier) VALUES (?, ?, ?)",
                (user_id, int(datetime.utcnow().timestamp()), tier))
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
    if until_ts and datetime.utcfromtimestamp(until_ts) > datetime.utcnow():
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
        img_usd  REAL DEFAULT 0.0
    )""")
    try:
        cur.execute("ALTER TABLE subscriptions ADD COLUMN tier TEXT")
    except Exception:
        pass
    con.commit(); con.close()

def _today_ymd() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")

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
    cur.execute("SELECT luma_usd, runway_usd, img_usd FROM wallet WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close()
    return {"luma_usd": row[0], "runway_usd": row[1], "img_usd": row[2]}

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
    """True/False, left_after, tier"""
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
    return False, f"OFFER:{need:.2f}"

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
                model=OPENAI_MODEL, messages=messages, temperature=0.6, timeout=90_000
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
        from pdfminer.high_level import extract_text
    except Exception:
        extract_text = None
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
        return ("\n".join(txt)).strip()
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

# ───────── Images ─────────
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

# ───────── UI / тексты ─────────
START_TEXT = (
    "Привет! Я GPT-бот с тарифами, квотами и разовыми покупками.\n\n"
    "Что умею:\n"
    "• 💬 Текст/фото (GPT)\n"
    "• 🎬 Видео Luma (5–10 c, 9:16/16:9)\n"
    "• 🎥 Видео Runway (PRO)\n"
    "• 🖼 Картинки — команда /img <промпт>\n"
    "• 📄 Чтение и анализ PDF/EPUB/DOCX/FB2/TXT — просто пришли файл.\n\n"
    "Открой «🎛 Движки», чтобы выбрать, и «⭐ Подписка» — для тарифов."
)

HELP_TEXT = (
    "Подсказки:\n"
    "• /plans — тарифы и оплата подписки\n"
    "• /img кот с очками — сгенерирует картинку\n"
    "• «сделай видео … на 9 секунд 9:16» — Luma/Runway\n"
    "• «🎛 Движки» — выбрать GPT / Luma / Runway / Midjourney / Images / Docs\n"
    "• «🧾 Баланс» — кошелёк и пополнение (100/500/1000/5000 ₽)\n"
    "• Прочитать файл? Пришли PDF/EPUB/DOCX/FB2/TXT — сделаю конспект.\n"
    "• /voice_on и /voice_off — включить/выключить озвучку ответов."
)

EXAMPLES_TEXT = (
    "Примеры:\n"
    "• сделай видео ретро-авто на берегу, 9:16 на 9 секунд\n"
    "• опиши текст на фото (пришли фото и подпиши запрос)\n"
    "• /img неоновый город в дождь, реализм\n"
    "• пришли PDF — отвечу тезисами и выводами"
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 GPT (текст/фото/документы)", callback_data="engine:gpt")],
        [InlineKeyboardButton("🖼 Images (OpenAI)",             callback_data="engine:images")],
        [InlineKeyboardButton("🎬 Luma — короткие видео",       callback_data="engine:luma")],
        [InlineKeyboardButton("🎥 Runway — премиум-видео",      callback_data="engine:runway")],
        [InlineKeyboardButton("🎨 Midjourney (изображения)",    callback_data="engine:midjourney")],
        [InlineKeyboardButton("🗣 STT/TTS — речь↔текст",        callback_data="engine:stt_tts")],
        [InlineKeyboardButton("Открыть страницу тарифов", web_app=WebAppInfo(url=TARIFF_URL))],
    ])

# ───────── Router: text/photo/voice/docs/img/video ───────
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
        await update.effective_message.reply_text(
            "Дневной лимит текстовых запросов исчерпан. Оформите подписку через /plans."
        )
        return
    try:
        file = await update.message.photo[-1].get_file()
        data = await file.download_as_bytearray()
        b64 = base64.b64encode(bytes(data)).decode("ascii")
        mime = sniff_image_mime(bytes(data))
        user_text = (update.message.caption or "").strip()
        ans = await ask_openai_vision(user_text, b64, mime)
        await update.effective_message.reply_text(ans or "Готово.")
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
        await _process_text(update, context, txt)
    except Exception as e:
        log.exception("Audio document handler error: %s", e)
        await update.effective_message.reply_text("Ошибка обработки аудио-файла.")

# ======= Diagnostics =======
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
        f"• Runway key: {'✅' if bool(RUNWAY_API_KEY) else '❌'}  base={RUNWAY_BASE_URL}",
        f"  create={RUNWAY_CREATE_PATH}  status={RUNWAY_STATUS_PATH}",
        f"• Поллинг каждые {VIDEO_POLL_DELAY_S}s; таймауты: Luma {LUMA_MAX_WAIT_S}s / Runway {RUNWAY_MAX_WAIT_S}s",
        "",
        "🔎 Проверка Luma endpoints:",
    ]

    # Собираем уникальный перечень баз: сначала активную (из хелпера), затем объявленную и фоллбеки.
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                active_base = await _pick_luma_base(client)
                lines.append(f"• Активная база (detected): {active_base}")
            except Exception as e:
                active_base = None
                lines.append(f"• Активная база: ⛔ не удалось определить ({e})")

            seen = set()
            bases_to_probe = []

            def _push(b: str):
                b = (b or "").strip().rstrip("/")
                if b and b not in seen:
                    seen.add(b)
                    bases_to_probe.append(b)

            if active_base:
                _push(active_base)
            _push(LUMA_BASE_URL)
            for b in LUMA_FALLBACKS:
                _push(b)

            # Дёшево прозваниваем OPTIONS на create-path (404 считается «живым» DNS/TLS/роут)
            for b in bases_to_probe:
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

    # smalltalk
    if is_smalltalk(text):
        ans = await ask_openai_text(text)
        await update.effective_message.reply_text(ans)
        await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])
        return

    # 1) Вопросы о возможностях — отвечаем твёрдо, но ничего не запускаем
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

# ========= Luma client =========
# страхуемся: если глобальный кэш базы ещё не определён — создаём
try:
    _LUMA_LAST_BASE
except NameError:
    _LUMA_LAST_BASE: str | None = None

async def _luma_create(prompt: str, duration: int, ar: str) -> str | None:
    """
    Создаёт задачу в Luma и возвращает job_id, либо None.
    Порядок баз: detected(_pick_luma_base) → LUMA_BASE_URL → LUMA_FALLBACKS → legacy https://api.luma.ai
    """
    if not LUMA_API_KEY:
        raise RuntimeError("LUMA_API_KEY is missing")

    headers = {
        "Authorization": f"Bearer {LUMA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt,
        "aspect_ratio": _norm_ar(ar),
        "duration": int(duration),
        "model": LUMA_MODEL,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        # 1) определяем «живую» базу и формируем очередь кандидатов без дублей
        candidates: list[str] = []
        seen = set()

        try:
            detected = await _pick_luma_base(client)  # <- твой хелпер авто-детекта базы
            if detected:
                b = detected.rstrip("/")
                if b and b not in seen:
                    candidates.append(b); seen.add(b)
        except Exception as e:
            log.warning("Luma: auto-detect base failed: %s", e)

        for b in [LUMA_BASE_URL]:
            b = (b or "").strip().rstrip("/")
            if b and b not in seen:
                candidates.append(b); seen.add(b)

        for b in LUMA_FALLBACKS:
            b = (b or "").strip().rstrip("/")
            if b and b not in seen:
                candidates.append(b); seen.add(b)

        # финальный «legacy» домен — на всякий случай
        legacy = "https://api.luma.ai"
        if legacy not in seen:
            candidates.append(legacy); seen.add(legacy)

        # 2) пробуем по очереди
        last_text = None
        for base in candidates:
            url = f"{base}{LUMA_CREATE_PATH}"
            try:
                r = await client.post(url, headers=headers, json=payload)
                # 401/403/4xx — полезно увидеть ответ сервера
                last_text = r.text
                r.raise_for_status()

                j = r.json()
                job_id = (
                    j.get("id")
                    or j.get("task_id")
                    or (j.get("data") or {}).get("id")
                )
                if job_id:
                    if base != LUMA_BASE_URL:
                        log.warning("Luma: switched base_url to %s (fallback worked)", base)
                    # запоминаем рабочую базу для последующего поллинга статуса
                    global _LUMA_LAST_BASE
                    _LUMA_LAST_BASE = base
                    return str(job_id)

                log.error("Luma create: no job id in response from %s: %s", base, j)

            except httpx.HTTPStatusError as e:
                log.error("Luma create HTTP %s at %s | body=%s", e.response.status_code, base, last_text)
            except httpx.RequestError as e:
                log.error("Luma create network/http error at %s: %s", base, e)
            except Exception as e:
                log.error("Luma create unexpected error at %s: %s | body=%s", base, e, last_text)

    return None

async def luma_get_status(task_id: str, base_hint: str | None = None) -> dict:
    """
    Возвращает «сырой» JSON статуса задачи Luma.
    Приоритет выбора base:
      1) base_hint (если передали явно)
      2) _LUMA_LAST_BASE (запомненная при создании)
      3) авто-детект через _pick_luma_base(...)
    """
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
            headers={"Authorization": f"Bearer {LUMA_API_KEY}"},
            timeout=20.0,
        )
        r.raise_for_status()
        return r.json()

async def _luma_poll_and_get_url(job_id: str, base_hint: str | None = None) -> tuple[str | None, str]:
    """
    Поллит статус Luma, возвращает (video_url | None, 'completed'|'failed'|'error'|'canceled'|'timeout').
    Использует ту же базу, что и при создании (через base_hint или _LUMA_LAST_BASE).
    """
    start = time.time()
    while time.time() - start < LUMA_MAX_WAIT_S:
        try:
            j = await luma_get_status(job_id, base_hint=base_hint)
        except Exception:
            await asyncio.sleep(VIDEO_POLL_DELAY_S)
            continue

        status = (j.get("status") or j.get("state") or "").lower()
        if status in ("completed", "succeeded", "done", "finished"):
            video_url = (
                j.get("result", {}).get("video_url")
                or j.get("assets", {}).get("video")
                or j.get("output", {}).get("url")
                or j.get("url")
            )
            return (video_url, "completed")
        if status in ("failed", "error", "canceled"):
            return (None, status)

        await asyncio.sleep(VIDEO_POLL_DELAY_S)

    return (None, "timeout")

async def _run_luma_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration: int, ar: str):
    await update.effective_message.reply_text(f"✅ Запускаю Luma: {duration}s • {_norm_ar(ar)}\nЗапрос: {prompt}")
    job_id = await _luma_create(prompt, duration, ar)
    if not job_id:
        await update.effective_message.reply_text("⚠️ Не удалось создать задачу в Luma.")
        return
    await update.effective_message.reply_text("⏳ Luma рендерит… Я пришлю видео как будет готово.")
    url, st = await _luma_poll_and_get_url(job_id, base_hint=_LUMA_LAST_BASE)
    if not url:
        await update.effective_message.reply_text(f"⚠️ Luma вернула статус: {st}.")
        return
    try:
        await update.effective_message.reply_video(video=url, caption=_safe_caption(prompt, "Luma", duration, _norm_ar(ar)))
    except Exception:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                r = await client.get(url)
                r.raise_for_status()
                bio = BytesIO(r.content); bio.name = "luma.mp4"
                await update.effective_message.reply_video(video=InputFile(bio), caption=_safe_caption(prompt, "Luma", duration, _norm_ar(ar)))
        except Exception as e:
            log.exception("send luma video failed: %s", e)
            await update.effective_message.reply_text("⚠️ Видео готово, но не удалось отправить файл.")

# ========= Runway client =========
async def _runway_create(prompt: str, duration: int, ar: str) -> str | None:
    if not RUNWAY_API_KEY:
        raise RuntimeError("RUNWAY_API_KEY is missing")
    url = f"{RUNWAY_BASE_URL}{RUNWAY_CREATE_PATH}"
    payload = {
        "prompt": prompt,
        "ratio": _norm_ar(ar),
        "duration": int(duration),
        "model": RUNWAY_MODEL,
        "type": "text-to-video"
    }
    headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        try:
            r.raise_for_status()
        except Exception:
            log.error("Runway create error %s: %s", r.status_code, r.text)
            return None
        j = r.json()
        task_id = j.get("id") or j.get("task_id") or j.get("data", {}).get("id")
        if not task_id:
            log.error("Runway create: cannot find task id in %s", j)
            return None
        return str(task_id)

async def _runway_poll_and_get_url(task_id: str) -> tuple[str | None, str]:
    url_tpl = f"{RUNWAY_BASE_URL}{RUNWAY_STATUS_PATH}"
    url = url_tpl.replace("{id}", task_id)
    headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}"}
    start = time.time()

    async with httpx.AsyncClient(timeout=60.0) as client:
        while time.time() - start < RUNWAY_MAX_WAIT_S:
            try:
                r = await client.get(url, headers=headers)
                if r.status_code >= 400:
                    log.warning("Runway poll http %s: %s", r.status_code, r.text[:300])
                    await asyncio.sleep(VIDEO_POLL_DELAY_S)
                    continue
                j = r.json()
            except httpx.HTTPError as e:
                log.warning("Runway poll network error: %s", e)
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
                continue
            except Exception as e:
                log.exception("Runway poll unexpected error: %s", e)
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
                continue

            status = (j.get("status") or j.get("state") or "").lower()
            if status in ("completed","succeeded","done","finished"):
                url = (
                    j.get("output", {}).get("url")
                    or j.get("result", {}).get("video")
                    or j.get("assets", {}).get("video")
                    or j.get("url")
                )
                return (url, "completed")
            if status in ("failed","error","canceled"):
                return (None, status)

            await asyncio.sleep(VIDEO_POLL_DELAY_S)

    return (None, "timeout")

async def _run_runway_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration: int, ar: str):
    await update.effective_message.reply_text(f"✅ Запускаю Runway: {duration}s • {_norm_ar(ar)}\nЗапрос: {prompt}")
    task_id = await _runway_create(prompt, duration, ar)
    if not task_id:
        await update.effective_message.reply_text("⚠️ Не удалось создать задачу в Runway.")
        return
    await update.effective_message.reply_text("⏳ Runway рендерит… Я пришлю видео как будет готово.")
    url, st = await _runway_poll_and_get_url(task_id)
    if not url:
        await update.effective_message.reply_text(f"⚠️ Runway вернул статус: {st}.")
        return
    try:
        await update.effective_message.reply_video(video=url, caption=_safe_caption(prompt, "Runway", duration, _norm_ar(ar)))
    except Exception:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                r = await client.get(url)
                r.raise_for_status()
                bio = BytesIO(r.content); bio.name = "runway.mp4"
                await update.effective_message.reply_video(video=InputFile(bio), caption=_safe_caption(prompt, "Runway", duration, _norm_ar(ar)))
        except Exception as e:
            log.exception("send runway video failed: %s", e)
            await update.effective_message.reply_text("⚠️ Видео готово, но не удалось отправить файл.")

# ───────── Telegram Payments: компактные payload и инвойсы ─────────
def _payload_oneoff(engine: str, usd: float) -> str:
    # t=1 (oneoff), e=l/r/i, u=<cents>
    e = {"luma": "l", "runway": "r", "img": "i"}.get(engine, "i")
    cents = int(round(float(usd) * 100))
    return f"t=1;e={e};u={cents}"

def _payload_subscribe(tier: str, months: int) -> str:
    # t=2 (subscribe), s=s/p/u, m=<months>
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
    """
    Ограничения Telegram:
    - title: 1..32 символа
    - description: 1..255 символов
    - payload: 1..128 байт ASCII
    """
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
    # Полный доступ для владельца/сервисного аккаунта
    if is_unlimited(user_id, (update.effective_user.username or "")):
        await coroutine_to_run()
        return

    # Текстовые запросы/прочее — без биллинга
    if engine not in ("luma", "runway", "img"):
        await coroutine_to_run()
        return

    tier = get_subscription_tier(user_id)
    # Если нет подписки — предлагаем подписку вместо разового платежа
    if tier == "free":
        await update.effective_message.reply_text(
            "Для этого действия нужна активная подписка. Открой /plans и оформи тариф. "
            "После исчерпания лимитов я предложу пополнить бюджет."
        )
        return

    ok, offer = _can_spend_or_offer(user_id, (update.effective_user.username or ""), engine, est_cost_usd)
    if ok:
        await coroutine_to_run()
        return

    # Подписка есть, но лимит исчерпан — предлагаем разовое пополнение
    try:
        need_usd = float(offer.split(":", 1)[-1])
    except Exception:
        need_usd = est_cost_usd
    amount_rub = _calc_oneoff_price_rub(engine, need_usd)
    title = f"{engine.UPPER()} пополнение" if hasattr(engine, "UPPER") else f"{engine.upper()} пополнение"
    desc = f"Пополнение бюджета для {engine} на ${need_usd:.2f} (≈ {amount_rub} ₽)."
    payload = _payload_oneoff(engine, need_usd)
    await _send_invoice_rub(title, desc, amount_rub, payload, update)

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.pre_checkout_query.answer(ok=True)
    except Exception as e:
        log.exception("precheckout error: %s", e)

async def on_success_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка успешного платежа Telegram. Поддерживает компактный payload:
      t=1;e=<l|r|i>;u=<cents>   — разовое пополнение кошелька по движку
      t=2;s=<s|p|u>;m=<months>  — подписка (start/pro/ultimate), месяцы
    Также пытается распарсить старый JSON payload на всякий случай.
    """
    try:
        pay = update.message.successful_payment
        raw = pay.invoice_payload or ""
        kv = _payload_parse(raw)
        t = kv.get("t", "")

        # --- One-off topup ---
        if t == "1":
            e = kv.get("e", "i")
            engine = {"l": "luma", "r": "runway", "i": "img"}.get(e, "img")
            cents = int(kv.get("u", "0") or 0)
            usd = cents / 100.0
            _wallet_add(update.effective_user.id, engine, usd)
            await update.effective_message.reply_text("💳 Оплата прошла! Бюджет пополнён, можно запускать задачу снова.")
            return

        # --- Subscribe ---
        if t == "2":
            tier = {"s": "start", "p": "pro", "u": "ultimate"}.get(kv.get("s", "p"), "pro")
            months = int(kv.get("m", "1") or 1)
            until = activate_subscription_with_tier(update.effective_user.id, tier, months)
            await update.effective_message.reply_text(f"⭐ Подписка активна до {until.strftime('%Y-%m-%d')}. Тариф: {tier}.")
            return

        # --- Fallback: старый JSON-payload ---
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

# --- /plans с кнопками «Купить» (инвойсы в чате) + ссылка на мини-приложение ---
def _plan_rub(tier: str, term: str) -> int:
    return int(PLAN_PRICE_TABLE[tier][term])

def _plan_payload_and_amount(tier: str, months: int) -> tuple[str, int, str]:
    term_label = {1: "мес", 3: "квартал", 12: "год"}.get(months, f"{months} мес")
    amount = _plan_rub(tier, {1: "month", 3: "quarter", 12: "year"}[months])
    payload = _payload_subscribe(tier, months)
    title = f"Подписка {tier}/{term_label}"
    return payload, amount, title

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["⭐ Тарифы и оформление подписки:"]
    for t in ("start", "pro", "ultimate"):
        p = PLAN_PRICE_TABLE[t]
        lines.append(f"• {t.UPPER() if hasattr(t,'UPPER') else t.upper()}: {p['month']}₽/мес • {p['quarter']}₽/квартал • {p['year']}₽/год")
    lines.append("")
    lines.append("Выбери подписку кнопкой ниже или открой мини-приложение.")
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
        [InlineKeyboardButton("Открыть страницу тарифов (мини-приложение)", web_app=WebAppInfo(url=TARIFF_URL))],
    ])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb, disable_web_page_preview=True)

# ───────── CallbackQuery / меню ─────────
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()

    try:
        # --- Покупка подписки (кнопки в /plans)
        if data.startswith("buy:"):
            _, tier, months = data.split(":", 2)
            months = int(months)
            payload, amount_rub, title = _plan_payload_and_amount(tier, months)
            desc = f"Оформление подписки {tier.upper()} на {months} мес."
            ok = await _send_invoice_rub(title, desc, amount_rub, payload, update)
            await q.answer("Выставляю счёт…" if ok else "Не удалось выставить счёт", show_alert=not ok)
            return

        # --- Выбор «движка» из меню «Движки»
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
                    f"Для Luma/Runway/Images действуют лимиты тарифа."
                )
                return

            est_cost = IMG_COST_USD if engine == "images" else (0.40 if engine == "luma" else max(1.0, RUNWAY_UNIT_COST_USD))
            map_engine = {"images": "img", "luma": "luma", "runway": "runway"}[engine]
            ok, offer = _can_spend_or_offer(update.effective_user.id, username, map_engine, est_cost)

            if ok:
                await q.edit_message_text(
                    "✅ Доступно. "
                    + ("Запусти: /img кот в очках" if engine == "images"
                       else "Напиши: «сделай видео … 9 секунд 9:16» — выберу Luma/Runway.")
                )
                return

            if offer == "ASK_SUBSCRIBE":
                await q.edit_message_text(
                    "Для этого движка нужна активная подписка. Оформите /plans или откройте мини-приложение.",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("⭐ Перейти к тарифам", web_app=WebAppInfo(url=TARIFF_URL))]]
                    ),
                )
                return

            # Предложение разовой покупки
            try:
                need_usd = float(offer.split(":", 1)[-1])
            except Exception:
                need_usd = est_cost
            amount_rub = _calc_oneoff_price_rub(map_engine, need_usd)
            await q.edit_message_text(
                f"Ваш лимит по «{engine}» исчерпан. Разовая покупка ≈ {amount_rub} ₽ "
                f"или пополните бюджет в /plans.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⭐ Перейти к тарифам", web_app=WebAppInfo(url=TARIFF_URL))]]
                ),
            )
            return

        # --- Выбор движка для уже распарсенного видео (после текста)
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

        # --- Неизвестный коллбэк
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

    if (_CAP_AUDIO.search(tl) and re.search(r"(чита|анализ|расшифр|транскриб|понима|распозна)", tl)) or "аудио" in tl:
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
            "«сделай видео … на 9 секунд 9:16». После запроса предложу выбрать движок Luma или Runway."
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

# ───────── Команды UI ─────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if BANNER_URL:
        try:
            await update.effective_message.reply_photo(BANNER_URL)
        except Exception:
            pass
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
    msg = (
        "🧾 Кошелёк (доллары экв. движков):\n"
        f"• Luma: ${w['luma_usd']:.2f}\n"
        f"• Runway: ${w['runway_usd']:.2f}\n"
        f"• Images: ${w['img_usd']:.2f}\n\n"
        "Чтобы пополнить при превышении бюджета — просто запусти задачу, я предложу счёт."
    )
    await update.effective_message.reply_text(msg)

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
            try:
                await context.bot.send_message(chat_id, "⚠️ Произошла внутренняя ошибка. Уже разбираюсь, попробуй ещё раз.")
            except Exception:
                pass
    except Exception as e:
        log.exception("on_error failed: %s", e)

# ───────── STT ─────────
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
        try:
            await app.bot.delete_webhook(drop_pending_updates=True)
            log.info("Webhook cleanup done (drop_pending_updates=True)")
        except Exception as e:
            log.warning(f"delete_webhook failed: {e}")

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
