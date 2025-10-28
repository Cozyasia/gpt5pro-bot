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
OPENROUTER_API_KEY  = os.environ.get("OPENROUTER_API_KEY", "").strip()

WEBHOOK_SECRET   = os.environ.get("WEBHOOK_SECRET", "").strip()
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
TTS_MAX_CHARS        = int(os.environ.get("TTS_MAX_CHARS", "50").strip() or "50")

# Images:
OPENAI_IMAGE_KEY    = os.environ.get("OPENAI_IMAGE_KEY", "").strip() or OPENAI_API_KEY
IMAGES_BASE_URL     = (os.environ.get("OPENAI_IMAGE_BASE_URL", "").strip() or "https://api.openai.com/v1")
IMAGES_MODEL        = "gpt-image-1"

# Runway
RUNWAY_API_KEY      = os.environ.get("RUNWAY_API_KEY", "").strip()
RUNWAY_MODEL        = os.environ.get("RUNWAY_MODEL", "veo3").strip()
RUNWAY_RATIO        = os.environ.get("RUNWAY_RATIO", "720:1280").strip()
RUNWAY_DURATION_S   = int(os.environ.get("RUNWAY_DURATION_S", "8"))

# Luma
LUMA_API_KEY     = os.environ.get("LUMA_API_KEY", "").strip()
LUMA_MODEL       = os.environ.get("LUMA_MODEL", "ray-2").strip()
LUMA_ASPECT      = os.environ.get("LUMA_ASPECT", "16:9").strip()
LUMA_DURATION_S  = int(os.environ.get("LUMA_DURATION_S", "6"))

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

PORT = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")
if not OPENAI_API_KEY:
    raise RuntimeError("ENV OPENAI_API_KEY is missing")

# ── Безлимит ──
UNLIM_USER_IDS     = set(int(x) for x in os.environ.get("UNLIM_USER_IDS","").split(",") if x.strip().isdigit())
UNLIM_USERNAMES    = set(s.strip().lstrip("@").lower() for s in os.environ.get("UNLIM_USERNAMES","").split(",") if s.strip())
OWNER_ID           = int(os.environ.get("OWNER_ID","0") or "0")  # владелец = всегда без лимитов
FORCE_OWNER_UNLIM  = os.environ.get("FORCE_OWNER_UNLIM","1").strip() not in ("0","false","False")

def is_unlimited(user_id: int, username: str | None = None) -> bool:
    if FORCE_OWNER_UNLIM and OWNER_ID and user_id == OWNER_ID:
        return True
    if user_id in UNLIM_USER_IDS:
        return True
    if username and username.lower() in UNLIM_USERNAMES:
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

# Текстовый LLM: допускаем OpenRouter как base_url
_auto_base = OPENAI_BASE_URL
if not _auto_base and (OPENAI_API_KEY.startswith("sk-or-") or "openrouter" in OPENAI_BASE_URL.lower()):
    _auto_base = "https://openrouter.ai/api/v1"
    log.info("Auto-select OpenRouter base_url for text LLM.")

default_headers = {}
ref = _ascii_or_none(OPENROUTER_SITE_URL)
ttl = _ascii_or_none(OPENROUTER_APP_NAME)
if ref:
    default_headers["HTTP-Referer"] = ref
if ttl:
    default_headers["X-Title"] = ttl

oai_llm = OpenAI(api_key=OPENAI_API_KEY, base_url=_auto_base or None, default_headers=default_headers or None)
oai_stt = OpenAI(api_key=OPENAI_STT_KEY) if OPENAI_STT_KEY else None
oai_img = OpenAI(api_key=OPENAI_IMAGE_KEY, base_url=IMAGES_BASE_URL)  # картинки — всегда через api.openai.com
oai_tts = OpenAI(api_key=OPENAI_TTS_KEY, base_url=OPENAI_TTS_BASE_URL)

# Tavily
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
        img_usd REAL DEFAULT 0.0
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

# лимиты
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
    return int(rub + 0.999)

def _can_spend_or_offer(user_id: int, engine: str, est_cost_usd: float) -> tuple[bool, str]:
    if engine not in ("luma", "runway", "img"):
        return True, ""
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
_CAPABILITY_RE= re.compile(r"(мож(ешь|но).{0,12}(анализ|распознав).{0,16}(фото|картинк|изображен|видео))", re.I)

_IMG_WORDS = (r"(картин\w+|изображен\w+|фото\w*|рисунк\w+|аватар\w*|логотип\w+|image|picture|img\b|logo|banner|poster)")
_VID_WORDS = (r"(видео|ролик\w*|анимаци\w*|shorts?|reels?|clip|video|vid\b)")
_VERBS     = (r"(сдела\w+|созда\w+|сгенерир\w+|нарис\w+|сформир\w+|make|generate|create|render)")

_PREFIXES_VIDEO = [r"^созда\w*\s+видео", r"^сдела\w*\s+видео", r"^video\b", r"^reels?\b", r"^shorts?\b"]
_PREFIXES_IMAGE = [r"^созда\w*\s+(?:картин\w+|изображен\w+|фото\w*|рисунк\w+)", r"^image\b", r"^picture\b", r"^img\b"]

def _strip_leading(s: str) -> str:
    return s.strip(" \n\t:—–-\"“”'«»,.()[]")
def _after_match(text: str, match) -> str:
    return _strip_leading(text[match.end():])

def detect_media_intent(text: str):
    if not text: return (None, "")
    t = text.strip(); tl = t.lower()

    for p in _PREFIXES_VIDEO:
        m = re.search(p, tl, re.I)
        if m: return ("video", _after_match(t, m))
    for p in _PREFIXES_IMAGE:
        m = re.search(p, tl, re.I)
        if m: return ("image", _after_match(t, m))

    if re.search(r"(можешь|можно|сможешь)", tl) and re.search(_VERBS, tl):
        if re.search(_VID_WORDS, tl):
            tmp = re.sub(r"(ты|вы)?\s*(можешь|можно|сможешь)\s*", "", tl)
            tmp = re.sub(_VID_WORDS, "", tmp); tmp = re.sub(_VERBS, "", tmp)
            return ("video", _strip_leading(tmp))
        if re.search(_IMG_WORDS, tl):
            tmp = re.sub(r"(ты|вы)?\s*(можешь|можно|сможешь)\s*", "", tl)
            tmp = re.sub(_IMG_WORDS, "", tmp); tmp = re.sub(_VERBS, "", tmp)
            return ("image", _strip_leading(tmp))

    if re.search(_VID_WORDS, tl) and re.search(_VERBS, tl):
        tmp = re.sub(_VID_WORDS, "", tl); tmp = re.sub(_VERBS, "", tmp)
        return ("video", _strip_leading(tmp))
    if re.search(_IMG_WORDS, tl) and re.search(_VERBS, tl):
        tmp = re.sub(_IMG_WORDS, "", tl); tmp = re.sub(_VERBS, "", tmp)
        return ("image", _strip_leading(tmp))

    m = re.match(r"^(img|image|picture)\s*[:\-]\s*(.+)$", tl)
    if m: return ("image", _strip_leading(t[m.end(1)+1:]))
    m = re.match(r"^(video|vid|reels?|shorts?)\s*[:\-]\s*(.+)$", tl)
    if m: return ("video", _strip_leading(t[m.end(1)+1:]))
    return (None, "")

def is_smalltalk(text: str) -> bool:
    return bool(_SMALLTALK_RE.search(text.strip()))
def should_browse(text: str) -> bool:
    if is_smalltalk(text): return False
    return bool(_NEWSY_RE.search(text) or "?" in text or len(text) > 80)

# ───────── OpenAI helpers ─────────
async def ask_openai_text(user_text: str, web_ctx: str = "") -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({"role": "system", "content": f"Контекст из веб-поиска:\n{web_ctx}"})
    messages.append({"role": "user", "content": user_text})
    try:
        resp = oai_llm.chat.completions.create(model=OPENAI_MODEL, messages=messages, temperature=0.6)
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("OpenAI chat error: %s", e)
        return "Не удалось получить ответ от модели. Попробуй позже."

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

# ───────── TTS ─────────
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
    if not text or len(text) > TTS_MAX_CHARS or not OPENAI_TTS_KEY:
        return
    try:
        try:
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VOICE)
        except Exception:
            pass
        audio = await asyncio.to_thread(_tts_bytes_sync, text)
        if not audio:
            return
        bio = BytesIO(audio); bio.name = "say.ogg"
        await update.effective_message.reply_voice(voice=InputFile(bio), caption=text)
    except Exception as e:
        log.exception("maybe_tts_reply error: %s", e)

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
    # Сначала Deepgram — быстрее
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
    # Фолбэк — Whisper
    if oai_stt:
        try:
            buf2 = BytesIO(data); buf2.seek(0); setattr(buf2, "name", filename_hint)
            tr = oai_stt.audio.transcriptions.create(model=TRANSCRIBE_MODEL, file=buf2)
            return (tr.text or "").strip()
        except Exception as e:
            log.exception("Whisper STT error: %s", e)
    return ""

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

# ───────── Image/Video low-level ─────────
async def _do_img_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
        b64 = resp.data[0].b64_json
        img_bytes = base64.b64decode(b64)
        await update.effective_message.reply_photo(photo=img_bytes, caption=f"Готово ✅\nЗапрос: {prompt}")
    except Exception as e:
        log.exception("IMG gen error: %s", e)
        await update.effective_message.reply_text(f"Не удалось создать изображение: {e}")

# Runway SDK (опционально)
if RUNWAY_API_KEY:
    os.environ["RUNWAY_API_KEY"] = RUNWAY_API_KEY
RUNWAY_SDK_OK = True; RUNWAY_IMPORT_ERROR = None
try:
    from runwayml import RunwayML
except Exception as _e:
    RUNWAY_SDK_OK = False; RUNWAY_IMPORT_ERROR = _e

def _runway_make_video_sync(prompt: str, duration: int = None) -> bytes:
    if not RUNWAY_API_KEY:
        raise RuntimeError("RUNWAY_API_KEY не задан")
    if not RUNWAY_SDK_OK:
        raise RuntimeError(f"runwayml не установлен/не импортируется: {RUNWAY_IMPORT_ERROR}")
    client = RunwayML(api_key=RUNWAY_API_KEY)
    task = client.text_to_video.create(prompt_text=prompt, model=RUNWAY_MODEL, ratio=RUNWAY_RATIO,
                                       duration=(duration if duration is not None else RUNWAY_DURATION_S))
    task_id = task.id
    time.sleep(1)
    task = client.tasks.retrieve(task_id)
    while task.status not in ["SUCCEEDED","FAILED"]:
        time.sleep(1)
        task = client.tasks.retrieve(task_id)
    if task.status != "SUCCEEDED":
        raise RuntimeError(getattr(task, "error", None) or f"Runway task failed: {task.status}")
    output = getattr(task, "output", None)
    if isinstance(output, list) and output: video_url = output[0]
    elif isinstance(output, dict):         video_url = output.get("url") or output.get("video_url")
    else: raise RuntimeError(f"Runway: нет URL результата: {output}")
    with httpx.Client(timeout=None) as http:
        r = http.get(video_url); r.raise_for_status(); return r.content

# Luma
_ALLOWED_LUMA_DURS = (5, 9, 10)
_DURATION_NUM_RE = re.compile(r"(?P<num>\d+(?:[.,]\d+)?)\s*[-]?\s*(?:s(?:ec(?:onds?)?)?|с|сек(?:\.|унд\w*)?)\b", re.I)
_WORD2NUM_RU = {"один":1,"одна":1,"раз":1,"два":2,"две":2,"три":3,"четыре":4,"пять":5,"шесть":6,"семь":7,"восемь":8,"девять":9,"десять":10}
_WORD2NUM_EN = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10}
_DURATION_WORD_RE = re.compile(rf"(?P<word>{'|'.join(list(_WORD2NUM_RU.keys())+list(_WORD2NUM_EN.keys()))})\s*(?:сек|seconds?)\b", re.I)
_AR_RE = re.compile(r"\b(16:9|9:16|4:3|3:4|1:1|21:9|9:21)\b", re.I)

def _snap_to_luma_allowed(x: int) -> int:
    return min(_ALLOWED_LUMA_DURS, key=lambda a: (abs(a - x), -a))

def parse_video_opts_from_text(text: str, default_duration: int = None, default_ar: str = None):
    duration_req = default_duration if default_duration is not None else LUMA_DURATION_S
    ar = default_ar if default_ar is not None else LUMA_ASPECT
    t = text or ""
    m = _DURATION_NUM_RE.search(t)
    if m:
        secs = int(round(float(m.group("num").replace(",", "."))))
        secs = max(1, min(10, secs)); duration_req = secs
        t = (t[:m.start()] + t[m.end():]).strip()
    else:
        m2 = _duration_word = _DURATION_WORD_RE.search(t)
        if m2:
            secs = _WORD2NUM_RU.get(m2.group("word").lower()) or _WORD2NUM_EN.get(m2.group("word").lower())
            if secs: duration_req = secs
            t = (t[:m2.start()] + t[m2.end():]).strip()
    m = _AR_RE.search(t)
    if m:
        ar = m.group(1); t = _AR_RE.sub("", t, count=1)
    duration_for_luma = _snap_to_luma_allowed(duration_req)
    clean = re.sub(r"\s{2,}", " ", t.replace(" ,", ",")).strip(" ,.;-—")
    return duration_for_luma, ar, clean

def _luma_make_video_sync(prompt: str, duration: int = None, aspect: str = None) -> bytes:
    if not LUMA_API_KEY:
        raise RuntimeError("LUMA_API_KEY не задан")
    dur = duration if duration is not None else LUMA_DURATION_S
    ar  = aspect   if aspect   is not None else LUMA_ASPECT
    headers = {"Authorization": f"Bearer {LUMA_API_KEY}", "Content-Type": "application/json", "Accept": "application/json"}
    create_url = "https://api.lumalabs.ai/dream-machine/v1/generations"
    payload = {"prompt": prompt, "model": LUMA_MODEL, "duration": f"{dur}s", "aspect_ratio": ar}
    with httpx.Client(timeout=None) as http:
        r = http.post(create_url, headers=headers, json=payload); r.raise_for_status()
        gen = r.json(); gen_id = gen.get("id") or gen.get("generation_id")
        if not gen_id: raise RuntimeError(f"Luma: не получили id задачи: {gen}")
        get_url = f"https://api.lumalabs.ai/dream-machine/v1/generations/{gen_id}"
        while True:
            g = http.get(get_url, headers=headers); g.raise_for_status()
            data = g.json(); status = data.get("state") or data.get("status")
            if status in ("completed","succeeded","SUCCEEDED"):
                assets = data.get("assets") or {}
                video_url = assets.get("video") or assets.get("mp4") or assets.get("file")
                if not video_url: raise RuntimeError(f"Luma: нет ссылки на видео в ответе: {data}")
                v = http.get(video_url); v.raise_for_status(); return v.content
            if status in ("failed","error","cancelled","canceled"):
                raise RuntimeError(f"Luma failed: {data.get('failure_reason') or status}")
            time.sleep(2)

# ───────── UI / plans / invoices ───────

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
    "• «🎛 Движки» — выбрать GPT / Luma / Runway / Midjourney\n"
    "• «🧾 Баланс» — кошелёк и пополнение (100/500/1000/5000 ₽)\n"
    "• Прочитать файл? Пришли PDF/EPUB/DOCX/FB2/TXT — сделаю конспект."
)

MODES_TEXT = "Выбери движок для следующего запроса:"
EXAMPLES_TEXT = (
    "Примеры:\n"
    "• сделай видео ретро-авто на берегу, 9:16 на 9 секунд\n"
    "• опиши текст на фото (пришли фото и подпиши запрос)\n"
    "• /img неоновый город в дождь, реализм\n"
    "• пришли PDF — отвечу тезисами и выводами"
)

def _plans_markup():
    kb = [
        [
            InlineKeyboardButton("Start / месяц — 499 ₽", callback_data="plan:start:month"),
            InlineKeyboardButton("Pro / месяц — 999 ₽", callback_data="plan:pro:month"),
        ],
        [
            InlineKeyboardButton("Ultimate / месяц — 1999 ₽", callback_data="plan:ultimate:month"),
        ],
        [
            InlineKeyboardButton("Квартал (экономия)", callback_data="plan_menu:quarter"),
            InlineKeyboardButton("Год (макс выгода)", callback_data="plan_menu:year"),
        ],
        [InlineKeyboardButton("👉 Открыть страницу тарифов", web_app=WebAppInfo(url=TARIFF_URL))],
    ]
    return InlineKeyboardMarkup(kb)

def _plans_markup_term(term: str):
    tbl = PLAN_PRICE_TABLE
    kb = [
        [InlineKeyboardButton(f"Start / {term} — {tbl['start'][term]} ₽", callback_data=f"plan:start:{term}")],
        [InlineKeyboardButton(f"Pro / {term} — {tbl['pro'][term]} ₽", callback_data=f"plan:pro:{term}")],
        [InlineKeyboardButton(f"Ultimate / {term} — {tbl['ultimate'][term]} ₽", callback_data=f"plan:ultimate:{term}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="plan_menu:root")],
    ]
    return InlineKeyboardMarkup(kb)

main_kb = ReplyKeyboardMarkup(
    [
        [KeyboardButton("⭐ Подписка"), KeyboardButton("🎛 Движки")],
        [KeyboardButton("🧾 Баланс"), KeyboardButton("ℹ️ Помощь")],
    ],
    resize_keyboard=True
)

def _topup_engine_markup():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Пополнить Luma", callback_data="topup_engine:luma"),
            InlineKeyboardButton("Пополнить Runway", callback_data="topup_engine:runway"),
        ],
        [InlineKeyboardButton("Пополнить Images", callback_data="topup_engine:img")],
        [InlineKeyboardButton("Закрыть", callback_data="topup_engine:close")],
    ])

def _topup_amount_markup(engine: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("100 ₽",  callback_data=f"topup_amount:{engine}:100"),
            InlineKeyboardButton("500 ₽",  callback_data=f"topup_amount:{engine}:500"),
        ],
        [
            InlineKeyboardButton("1000 ₽", callback_data=f"topup_amount:{engine}:1000"),
            InlineKeyboardButton("5000 ₽", callback_data=f"topup_amount:{engine}:5000"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="topup_menu")],
    ])

# ───────── Commands (UI) ───────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(START_TEXT, reply_markup=main_kb, disable_web_page_preview=True)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT)

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(EXAMPLES_TEXT)

async def cmd_modes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(MODES_TEXT, reply_markup=engines_kb())

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Выбери подписку: ограничения по дневным квотам будут выше, а движки — доступны.",
        reply_markup=_plans_markup(),
    )

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w = _wallet_get(update.effective_user.id)
    await update.effective_message.reply_text(
        f"Кошелёк (USD):\n"
        f"• Luma: {w['luma_usd']:.2f}$\n"
        f"• Runway: {w['runway_usd']:.2f}$\n"
        f"• Images: {w['img_usd']:.2f}$\n\n"
        f"Пополнить баланс на 100/500/1000/5000 ₽:",
        reply_markup=_topup_engine_markup()
    )

# ───────── Callbacks (plans/topup/choose) ───────

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    data = q.data or ""
    try:
        # меню тарифов
        if data.startswith("plan_menu:"):
            _, term = data.split(":", 1)
            if term == "root":
                await q.edit_message_reply_markup(reply_markup=_plans_markup())
            else:
                await q.edit_message_reply_markup(reply_markup=_plans_markup_term(term))
            await q.answer()
            return

        # покупка подписки
        if data.startswith("plan:"):
            _, tier, term = data.split(":")
            months = TERM_MONTHS[term]
            rub = PLAN_PRICE_TABLE[tier][term]
            title = f"Подписка {tier.capitalize()} ({months} мес.)"
            desc = "Оплата подписки через Telegram. Доступ к квотам и движкам согласно тарифу."
            payload = f"SUB:{tier}:{term}:{months}"
            ok = await _send_invoice(context, q.message.chat_id, title, desc, payload, rub)
            await q.answer("Выставлен счёт." if ok else "Ошибка при выставлении счёта", show_alert=not ok)
            return

        # меню пополнения кошелька
        if data == "topup_menu":
            await q.edit_message_reply_markup(reply_markup=_topup_engine_markup())
            await q.answer()
            return
        if data.startswith("topup_engine:"):
            _, eng = data.split(":")
            if eng == "close":
                await q.answer("Закрыто")
                await q.edit_message_reply_markup(reply_markup=None)
                return
            await q.edit_message_reply_markup(reply_markup=_topup_amount_markup(eng))
            await q.answer()
            return
        if data.startswith("topup_amount:"):
            _, eng, rub_s = data.split(":")
            rub = int(rub_s)
            usd = round(rub / USD_RUB, 2)
            title = f"Пополнение кошелька: {_oneoff_human(eng)}"
            desc = f"Зачисление ≈ {usd:.2f}$ для «{_oneoff_human(eng)}»."
            payload = f"WALLET:{eng}:{usd:.2f}"
            ok = await _send_invoice(context, q.message.chat_id, title, desc, payload, rub)
            await q.answer("Выставлен счёт." if ok else "Ошибка при выставлении счёта", show_alert=not ok)
            return

        # выбор движка для задачи (например видео)
        if data.startswith("choose:"):
            _, engine, aid = data.split(":")
            act = _pending_actions.pop(aid, None)
            if not act:
                await q.answer("Задача не найдена", show_alert=True)
                return
            user_id = q.from_user.id
            if engine == "luma":
                est = _estimate_luma_cost_usd(act["duration"], LUMA_RES_HINT)
                async def _go():
                    await _do_luma_generate(update, context, prompt=act["prompt"], duration=act["duration"], aspect=act["aspect"])
                await _try_pay_then_do(update, context, user_id, "luma", est, _go,
                                       remember_kind="luma_generate",
                                       remember_payload={"prompt": act["prompt"], "duration": act["duration"], "aspect": act["aspect"]})
            elif engine == "runway":
                est = RUNWAY_UNIT_COST_USD
                async def _go():
                    await _do_runway_generate(update, context, prompt=act["prompt"], duration=act["duration"])
                await _try_pay_then_do(update, context, user_id, "runway", est, _go,
                                       remember_kind="runway_generate",
                                       remember_payload={"prompt": act["prompt"], "duration": act["duration"]})
            await q.answer("Окей, запускаю")
            return

    except Exception as e:
        log.exception("Callback error: %s", e)
        try:
            await q.answer("Ошибка", show_alert=True)
        except Exception:
            pass

# ───────── Payments ───────

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    try:
        await query.answer(ok=True)
    except Exception as e:
        log.exception("PreCheckout error: %s", e)
        try:
            await query.answer(ok=False, error_message="Не удалось проверить платёж.")
        except Exception:
            pass

async def on_success_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    user_id = update.effective_user.id
    payload = sp.invoice_payload or ""
    try:
        if payload.startswith("SUB:"):
            _, tier, term, months_s = payload.split(":")
            months = int(months_s)
            until = activate_subscription_with_tier(user_id, tier, months)
            await update.message.reply_text(
                f"✅ Подписка {tier.capitalize()} активирована до {until.strftime('%Y-%m-%d')}."
            )
            return
        if payload.startswith("TOPUP:"):
            parts = payload.split(":")
            engine = parts[1]
            usd = float(parts[2])
            aid = parts[3] if len(parts) > 3 else ""
            _wallet_add(user_id, engine, usd)
            await update.message.reply_text(f"✅ Кошелёк пополнен на {usd:.2f}$ для «{_oneoff_human(engine)}».")
            if aid and aid in _pending_actions:
                act = _pending_actions.pop(aid, None)
                if act and act.get("user_id") == user_id and act.get("engine") == engine:
                    _register_engine_spend(user_id, engine, act.get("usd_need", 0.0))
                    kind = act.get("after_kind")
                    payload2 = act.get("after_payload") or {}
                    if kind == "luma_generate":
                        await _do_luma_generate(update, context, **payload2)
                    elif kind == "runway_generate":
                        await _do_runway_generate(update, context, **payload2)
                    elif kind == "img_generate":
                        await _do_img_generate(update, context, **payload2)
            return
        if payload.startswith("WALLET:"):
            _, engine, usd_s = payload.split(":")
            usd = float(usd_s)
            _wallet_add(user_id, engine, usd)
            await update.message.reply_text(f"✅ Зачислено {usd:.2f}$ в кошелёк «{_oneoff_human(engine)}».")
            return
    except Exception as e:
        log.exception("SuccessPayment error: %s", e)
        await update.message.reply_text("Платёж прошёл, но возникла ошибка при активации. Напишите в поддержку.")

# ───────── Diagnostics ───────
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

# ───────── Router: text/photo/voice/docs/img/video ───────
# (предполагается, что все вспомогательные функции и генераторы определены выше в файле)

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

# документы: аудио-файлы как документ
async def on_audio_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Распознаём загруженные аудио-файлы как ДОКУМЕНТ (mp3/m4a/wav/ogg/webm),
       эхо распознавания — перед _process_text."""
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

async def cmd_diag_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = (update.effective_user.username or "")
    tier = get_subscription_tier(uid)
    lim = _limits_for(uid)
    row = _usage_row(uid)
    w = _wallet_get(uid)

    if is_unlimited(uid, uname):
        await update.effective_message.reply_text(
            "♾ Безлимит: включён для этого пользователя (по ID/username).\n"
            "• Тексты: без ограничений\n• Бюджеты: пропускаются\n"
            f"• Кошелёк: Luma {w['luma_usd']:.2f}$, Runway {w['runway_usd']:.2f}$, Images {w['img_usd']:.2f}$"
        )
        return

    txt = (
        "📊 Лимиты и использование:\n"
        f"• Тариф: {tier}\n"
        f"• Текстов сегодня: {row['text_count']} / {lim['text_per_day']}\n"
        f"• Бюджет Luma (день): {lim['luma_budget_usd']:.2f}$, израсходовано: {row['luma_usd']:.2f}$\n"
        f"• Бюджет Runway (день): {lim['runway_budget_usd']:.2f}$, израсходовано: {row['runway_usd']:.2f}$\n"
        f"• Бюджет Images (день): {lim['img_budget_usd']:.2f}$, израсходовано: {row['img_usd']:.2f}$\n"
        f"• Кошелёк: Luma {w['luma_usd']:.2f}$, Runway {w['runway_usd']:.2f}$, Images {w['img_usd']:.2f}$"
    )
    await update.effective_message.reply_text(txt)

# ======= Error handler (важно, чтобы не падали хендлеры) =======
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        log.exception("Unhandled error in handler", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("⚠️ Произошла внутренняя ошибка. Уже чиним.")
    except Exception:
        # избегаем бесконечных исключений
        pass
# ======= REQUIRED GLUE: engines, invoices, media helpers, process_text, doc_analyze, cmd_img =======

_pending_actions: dict[str, dict] = {}

def _oneoff_human(engine: str) -> str:
    return {"luma":"Luma (видео)", "runway":"Runway (видео)", "img":"Images (картинки)"}.get(engine, engine)

def sniff_image_mime(b: bytes) -> str:
    # очень упрощённый сниффер без зависимостей
    if b.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if b[:3] == b"\xff\xd8\xff":         return "image/jpeg"
    if b[:6] == b"GIF87a" or b[:6] == b"GIF89a": return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":  return "image/webp"
    return "application/octet-stream"

def engines_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Видео: Luma", callback_data="plan_menu:root"),
         InlineKeyboardButton("Видео: Runway", callback_data="plan_menu:root")],
        [InlineKeyboardButton("Картинки (OpenAI)", callback_data="plan_menu:root")],
        [InlineKeyboardButton("Открыть страницу тарифов", web_app=WebAppInfo(url=TARIFF_URL))]
    ])

def _new_aid() -> str:
    import secrets
    return secrets.token_hex(8)

def _estimate_luma_cost_usd(duration_sec: int, res_hint: str = "720p") -> float:
    base = 0.50 if duration_sec <= 6 else 0.90  # грубая оценка
    if "1080" in (res_hint or "").lower():
        base *= 1.5
    return round(base, 2)

async def _send_invoice(context: ContextTypes.DEFAULT_TYPE, chat_id: int, title: str, desc: str, payload: str, rub_amount: int) -> bool:
    try:
        if not PROVIDER_TOKEN:
            await context.bot.send_message(chat_id, "⚠️ Платёжный провайдер не настроен (PROVIDER_TOKEN_YOOKASSA).")
            return False
        prices = [LabeledPrice(label=title, amount=int(rub_amount * 100))]
        start_param = ("sp_" + re.sub(r"[^a-zA-Z0-9_]", "_", payload))[:32]
        await context.bot.send_invoice(
            chat_id=chat_id,
            title=title,
            description=desc,
            payload=payload,
            provider_token=PROVIDER_TOKEN,
            currency=CURRENCY,
            prices=prices,
            start_parameter=start_param,
            need_name=False, need_phone_number=False, need_email=False, need_shipping_address=False,
            is_flexible=False
        )
        return True
    except TelegramError as e:
        log.exception("send_invoice error: %s", e)
        return False

async def _try_pay_then_do(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, engine: str, est_cost_usd: float, coro_do, remember_kind: str, remember_payload: dict):
    ok, offer = _can_spend_or_offer(user_id, engine, est_cost_usd)
    if ok:
        return await coro_do()
    # OFFER:сколько_нехватает
    need_usd = est_cost_usd
    if isinstance(offer, str) and offer.startswith("OFFER:"):
        try:
            need_usd = float(offer.split(":", 1)[1])
        except Exception:
            pass
    rub = _calc_oneoff_price_rub(engine, need_usd)
    aid = _new_aid()
    _pending_actions[aid] = {
        "user_id": user_id,
        "engine": engine,
        "usd_need": float(f"{need_usd:.2f}"),
        "after_kind": remember_kind,
        "after_payload": remember_payload,
    }
    title = f"Разовая покупка: {_oneoff_human(engine)}"
    desc = f"Пополним кошелёк на ≈ {need_usd:.2f}$ для выполнения задачи."
    payload = f"TOPUP:{engine}:{need_usd:.2f}:{aid}"
    await update.effective_message.reply_text(
        f"Не хватает дневного бюджета для «{_oneoff_human(engine)}». Выставляю счёт на {rub} ₽."
    )
    await _send_invoice(context, update.effective_chat.id, title, desc, payload, rub)

async def _do_luma_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration: int, aspect: str):
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)
    except Exception:
        pass
    data = await asyncio.to_thread(_luma_make_video_sync, prompt, duration, aspect)
    bio = BytesIO(data); bio.name = "luma.mp4"
    await update.effective_message.reply_video(video=InputFile(bio), caption=f"🎬 Luma • {duration}s • {aspect}\n\n{prompt}")

async def _do_runway_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration: int):
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)
    except Exception:
        pass
    data = await asyncio.to_thread(_runway_make_video_sync, prompt, duration)
    bio = BytesIO(data); bio.name = "runway.mp4"
    await update.effective_message.reply_video(video=InputFile(bio), caption=f"🎥 Runway • {duration}s\n\n{prompt}")

async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = (update.message.text or "").partition(" ")[2].strip()
    if not prompt:
        await update.effective_message.reply_text("Использование: /img <промпт>")
        return
    user_id = update.effective_user.id
    async def _go():
        await _do_img_generate(update, context, prompt)
    await _try_pay_then_do(update, context, user_id, "img", IMG_COST_USD, _go,
                           remember_kind="img_generate",
                           remember_payload={"prompt": prompt})

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

        # медиазадачи (интент)
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

        # Сохраняем одну задачу и используем один AID в обеих кнопках
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
    await update.effective_message.reply_text(ans)
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])
    
# ======= APP INIT =======
def main():
    db_init()
    db_init_usage()
    _start_http_stub()  # важно для Web Service на Render (healthcheck/premium.html)

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # --- гарантированно отключаем вебхук и чистим хвост апдейтов (если раньше был webhook)
    async def _post_init(app_):
        try:
            await app_.bot.delete_webhook(drop_pending_updates=True)
            log.info("Webhook deleted (drop_pending_updates=True)")
        except Exception as e:
            log.exception("delete_webhook failed: %s", e)

    app.post_init = _post_init

    # --- handlers
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

    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_success_payment))

    # Фото -> vision
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))

    # Голос/аудио (voice/audio)
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))

    # Документ с аудио (mp3/m4a/wav/ogg/oga/webm)
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

    # Документы для анализа текста (PDF/EPUB/DOCX/FB2/TXT/MOBI/AZW)
    docs_filter = (
        filters.Document.FileExtension("pdf")  |
        filters.Document.FileExtension("epub") |
        filters.Document.FileExtension("docx") |
        filters.Document.FileExtension("fb2")  |
        filters.Document.FileExtension("txt")  |
        filters.Document.FileExtension("mobi") |
        filters.Document.FileExtension("azw")  |
        filters.Document.FileExtension("azw3")
    )
    app.add_handler(MessageHandler(docs_filter, on_doc_analyze))

    # Обычный текст (последним, чтобы не перехватывать команды)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # Error handler (чтобы не было "No error handlers are registered, logging exception.")
    app.add_error_handler(on_error)

    # drop_pending_updates=True дублируем на всякий
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        stop_signals=None
    )

if __name__ == "__main__":
    main()
