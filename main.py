# -*- coding: utf-8 -*-
import os, re, json, time, base64, logging, asyncio, sqlite3, threading, uuid, contextlib
from io import BytesIO
from datetime import datetime, timedelta, timezone
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
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
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

# --- CRYPTOBOT (Crypto Pay API) ---
CRYPTO_PAY_TOKEN     = os.environ.get("CRYPTO_PAY_TOKEN", "").strip()
CRYPTO_PAY_API_TOKEN = CRYPTO_PAY_TOKEN  # синоним для совместимости
CRYPTO_ASSET         = os.environ.get("CRYPTO_ASSET", "USDT").strip()

PLAN_PRICE_USDT = {
    "START":   {"month": 4.99,  "quarter": 12.99, "year": 49.90},
    "PRO":     {"month": 9.99,  "quarter": 27.99, "year": 84.90},
    "ULTIMATE":{"month": 19.99, "quarter": 54.90, "year": 159.90},
}

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
_fallbacks_raw = ",".join([os.environ.get("LUMA_FALLBACKS", ""), os.environ.get("LUMA_FALLBACK_BASE_URL", "")])
LUMA_FALLBACKS: list[str] = []
for u in re.split(r"[;,]\s*", _fallbacks_raw):
    u = (u or "").strip().rstrip("/")
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

PORT = int(os.environ.get("PORT", "10000"))
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

USD_RUB = float(os.environ.get("USD_RUB", "100"))
ONEOFF_MARKUP_DEFAULT = float(os.environ.get("ONEOFF_MARKUP_DEFAULT", "1.0"))
ONEOFF_MARKUP_RUNWAY  = float(os.environ.get("ONEOFF_MARKUP_RUNWAY",  "0.5"))
LUMA_RES_HINT = os.environ.get("LUMA_RES", "720p").lower()
RUNWAY_UNIT_COST_USD = float(os.environ.get("RUNWAY_UNIT_COST_USD", "7.0"))
IMG_COST_USD = float(os.environ.get("IMG_COST_USD", "0.05"))
TON_USD_RATE = float(os.environ.get("TON_USD_RATE", "5.0") or "5.0")  # грубая заглушка

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")
if not OPENAI_API_KEY:
    raise RuntimeError("ENV OPENAI_API_KEY is missing")

# ───────── Безлимиты ─────────
def _parse_ids_csv(s: str) -> set[int]:
    return set(int(x) for x in s.split(",") if x.strip().isdigit())

UNLIM_USER_IDS   = _parse_ids_csv(os.environ.get("UNLIM_USER_IDS",""))
UNLIM_USERNAMES  = set(s.strip().lstrip("@").lower() for s in os.environ.get("UNLIM_USERNAMES","").split(",") if s.strip())
UNLIM_USERNAMES.add("gpt5pro_support")

OWNER_ID           = int(os.environ.get("OWNER_ID","0") or "0")
FORCE_OWNER_UNLIM  = os.environ.get("FORCE_OWNER_UNLIM","1").strip().lower() not in ("0","false","no")

def is_unlimited(user_id: int, username: str | None = None) -> bool:
    if FORCE_OWNER_UNLIM and OWNER_ID and user_id == OWNER_ID: return True
    if user_id in UNLIM_USER_IDS: return True
    if username and username.lower().lstrip("@") in UNLIM_USERNAMES: return True
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
    if not s: return None
    try: s.encode("ascii"); return s
    except Exception: return None

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
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, until_ts INTEGER NOT NULL, tier TEXT)""")
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
    cur.execute("""INSERT INTO subscriptions (user_id, until_ts) VALUES (?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET until_ts=excluded.until_ts""", (user_id, int(until.timestamp())))
    con.commit(); con.close()
    return until

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
        user_id INTEGER, ymd TEXT,
        text_count INTEGER DEFAULT 0,
        luma_usd REAL DEFAULT 0.0, runway_usd REAL DEFAULT 0.0, img_usd REAL DEFAULT 0.0,
        PRIMARY KEY (user_id, ymd)
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS wallet (
        user_id INTEGER PRIMARY KEY,
        luma_usd REAL DEFAULT 0.0, runway_usd REAL DEFAULT 0.0, img_usd REAL DEFAULT 0.0,
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

def _today_ymd() -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%d")

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
    cur.execute("""UPDATE usage_daily SET text_count=?, luma_usd=?, runway_usd=?, img_usd=? WHERE user_id=? AND ymd=?""",
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

# ───────── Лимиты/цены ─────────
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
        _usage_update(user_id, **{f"{engine}_usd": est_cost_usd}) if engine in ("luma","runway","img") else None
        return True, ""
    if engine not in ("luma","runway","img"): return True, ""
    lim = _limits_for(user_id); row = _usage_row(user_id)
    spent = row[f"{engine}_usd"]; budget = lim[f"{engine}_budget_usd"]
    if spent + est_cost_usd <= budget + 1e-9:
        _usage_update(user_id, **{f"{engine}_usd": est_cost_usd}); return True, ""
    need = max(0.0, spent + est_cost_usd - budget)
    if need <= 0: return True, ""
    if _wallet_total_get(user_id) >= need:
        _wallet_total_add(user_id, -need); _usage_update(user_id, **{f"{engine}_usd": est_cost_usd}); return True, ""
    tier = get_subscription_tier(user_id)
    return (False, "ASK_SUBSCRIBE" if tier=="free" else f"OFFER:{need:.2f}")

def _register_engine_spend(user_id: int, engine: str, usd: float):
    if engine in ("luma","runway","img"): _usage_update(user_id, **{f"{engine}_usd": float(usd)})

# ───────── Prompts ─────────
SYSTEM_PROMPT = ("Ты дружелюбный и лаконичный ассистент на русском. Отвечай по сути, структурируй списками/шагами, не выдумывай факты.")
VISION_SYSTEM_PROMPT = ("Ты чётко описываешь содержимое изображений: объекты, текст, схемы, графики. Не идентифицируй личности людей.")

# ───────── Heuristics / intent ─────────
_SMALLTALK_RE = re.compile(r"^(привет|здравствуй|добрый\s*(день|вечер|утро)|хи|hi|hello|как дела|спасибо|пока)\b", re.I)
_NEWSY_RE     = re.compile(r"(когда|дата|выйдет|релиз|новост|курс|цена|прогноз|найди|официал|погода|сегодня|тренд|адрес|телефон)", re.I)
_CAPABILITY_RE= re.compile(r"(мож(ешь|но|ете).{0,16}(анализ|распозн|читать|созда(ва)?т|дела(ть)?).{0,24}(фото|картинк|изображен|pdf|docx|epub|fb2|аудио|книг))", re.I)
_IMG_WORDS = r"(картин\w+|изображен\w+|фото\w*|рисунк\w+|image|picture|img\b|logo|banner|poster)"
_VID_WORDS = r"(видео|ролик\w*|анимаци\w*|shorts?|reels?|clip|video|vid\b)"

def is_smalltalk(text: str) -> bool:
    t = (text or "").strip().lower(); return bool(_SMALLTALK_RE.search(t))
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
    m = re.search(r"\b(ты|вы)?\s*мож(ешь|но|ете)\b", tl); 
    return bool(m and re.search(_CAPABILITY_RE, tl) and not re.search(_CREATE_CMD, tl, re.I))

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
            log.warning("OpenAI chat attempt %d failed: %s", attempt + 1, e)
            await asyncio.sleep(0.8 * (attempt + 1))
    log.error("ask_openai_text failed: %s", last_err)
    return "⚠️ Сейчас не получилось получить ответ от модели. Попробуйте переформулировать запрос или повторить позже."

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

# ───────── STT: transcription (Deepgram → fallback OpenAI) ─────────
async def transcribe_audio(buf: BytesIO, filename_hint: str = "audio.ogg") -> str:
    """
    Приоритет: Deepgram (если есть ключ), затем OpenAI Whisper.
    Возвращает распознанный текст (или пустую строку).
    """
    buf.seek(0)
    data = buf.read()
    buf.seek(0)

    # Deepgram
    if DEEPGRAM_API_KEY:
        try:
            import mimetypes
            mt = mimetypes.guess_type(filename_hint or "audio.ogg")[0] or "audio/ogg"
            headers = {
                "Authorization": f"Token {DEEPGRAM_API_KEY}",
                "Content-Type": mt
            }
            # Прямой upload
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    "https://api.deepgram.com/v1/listen",
                    headers=headers,
                    content=data,
                    params={"punctuate": "true", "language": "ru"}
                )
                r.raise_for_status()
                j = r.json()
                alt = (((j.get("results") or {}).get("channels") or [{}])[0].get("alternatives") or [{}])[0]
                txt = (alt.get("transcript") or "").strip()
                if txt:
                    return txt
        except Exception as e:
            log.warning("Deepgram fail, fallback to OpenAI: %s", e)

    # OpenAI Whisper
    if oai_stt:
        try:
            # SDK OpenAI для speech-to-text (мульти-part form)
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=os.path.splitext(filename_hint)[-1] or ".ogg", delete=False) as tf:
                tf.write(data)
                tmp_path = tf.name
            try:
                with open(tmp_path, "rb") as f:
                    resp = oai_stt.audio.transcriptions.create(
                        model=TRANSCRIBE_MODEL,
                        file=f,
                        response_format="text"
                    )
                if isinstance(resp, str):
                    return resp.strip()
                # Некоторые обертки возвращают объект с полем text
                txt = getattr(resp, "text", "")
                return (txt or "").strip()
            finally:
                with contextlib.suppress(Exception):
                    os.remove(tmp_path)
        except Exception as e:
            log.exception("OpenAI STT error: %s", e)

    return ""

# ───────── Платежи: вспомогательные и заглушки ─────────
def _payload_subscribe(tier: str, months: int) -> str:
    # t=2 — подписка; s=(s|p|u); m=1/3/12
    s = {"start": "s", "pro": "p", "ultimate": "u"}.get((tier or "pro").lower(), "p")
    m = max(1, int(months or 1))
    return f"t=2&s={s}&m={m}"

def _payload_parse(raw: str) -> dict:
    try:
        if raw and raw.strip().startswith("{"):
            return json.loads(raw)
    except Exception:
        pass
    out = {}
    for part in (raw or "").split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out

async def _send_invoice_rub(title: str, desc: str, amount_rub: int, payload: str, update: Update) -> bool:
    """
    Универсальная обёртка для Telegram-инвойса (ЮKassa провайдер).
    Возвращает True, если попытались выслать счёт (даже если Telegram промолчит).
    """
    if not PROVIDER_TOKEN:
        await update.effective_message.reply_text("⚠️ Провайдер ЮKassa не настроен. Обратитесь в поддержку.")
        return False
    try:
        prices = [LabeledPrice(label=_ascii_label(title), amount=int(amount_rub) * 100)]
        await update.effective_message.reply_invoice(
            title=title[:32],
            description=desc[:255],
            payload=payload,
            provider_token=PROVIDER_TOKEN,
            currency=CURRENCY,
            prices=prices,
            max_tip_amount=0,
            allow_sending_without_reply=True,
            need_name=False, need_phone_number=False, need_email=False, need_shipping_address=False,
        )
        return True
    except TelegramError as e:
        log.exception("send_invoice error: %s", e)
        await update.effective_message.reply_text("Не удалось выставить счёт.")
        return False
    except Exception as e:
        log.exception("send_invoice unknown error: %s", e)
        await update.effective_message.reply_text("Не удалось выставить счёт.")
        return False

async def _try_pay_then_do(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    engine: str,                 # 'luma' | 'runway' | 'img'
    est_cost_usd: float,
    coro_callable,               # async функция без аргументов
    remember_kind: str = "",
    remember_payload: dict | None = None,
):
    """
    Проверка лимитов/кошелька → если ок, запускаем coro_callable();
    если нет — предлагаем оплату.
    """
    username = (update.effective_user.username or "")
    ok, offer = _can_spend_or_offer(user_id, username, engine, float(est_cost_usd))
    if ok:
        await coro_callable()
        return

    # Нужна подписка/пополнение
    if offer == "ASK_SUBSCRIBE":
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
                [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")],
            ]
        )
        await update.effective_message.reply_text(
            "Для запуска этой задачи нужна активная подписка или пополненный баланс.",
            reply_markup=kb
        )
        return

    # Разовая покупка RUB по оценке need_usd
    try:
        need_usd = float(str(offer).split(":", 1)[-1])
    except Exception:
        need_usd = float(est_cost_usd or 0.5)
    amount_rub = _calc_oneoff_price_rub(engine, need_usd)
    payload = f"t=1&e={'l' if engine=='luma' else ('r' if engine=='runway' else 'i')}&u={int(round(need_usd*100))}"
    desc = f"Разовое пополнение для {engine.upper()} (≈ ${need_usd:.2f})"
    if await _send_invoice_rub("Разовая покупка", desc, amount_rub, payload, update):
        await update.effective_message.reply_text("После оплаты повторите команду для запуска задачи.")
    else:
        await update.effective_message.reply_text("Не удалось предложить покупку. Попробуйте позже или откройте /plans.")

# ───────── CryptoBot (доп. топап USD) ─────────
async def _crypto_create_invoice(usd_amount: float, asset: str = "USDT", description: str = "Top-up"):
    """
    Создаёт инвойс CryptoBot и возвращает (invoice_id, pay_url, usd_amount, asset)
    """
    if not CRYPTO_PAY_API_TOKEN:
        return None, None, 0.0, asset
    try:
        url = "https://pay.crypt.bot/api/createInvoice"
        headers = {
            "Content-Type": "application/json",
            "Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN,
        }
        data = {
            "asset": asset,
            "amount": float(usd_amount),
            "description": description,
            "allow_anonymous": True,
            "allow_comments": False,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, headers=headers, json=data)
            r.raise_for_status()
            j = r.json()
            if j.get("ok") and j.get("result"):
                inv = j["result"]
                return inv.get("invoice_id"), inv.get("pay_url"), float(usd_amount), asset
    except Exception as e:
        log.warning("CryptoBot create invoice error: %s", e)
    return None, None, 0.0, asset

async def _crypto_get_invoice(invoice_id: str) -> dict | None:
    if not CRYPTO_PAY_API_TOKEN:
        return None
    try:
        url = "https://pay.crypt.bot/api/getInvoices"
        headers = {
            "Content-Type": "application/json",
            "Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(url, headers=headers, json={"invoice_ids": [invoice_id]})
            r.raise_for_status()
            j = r.json()
            if j.get("ok"):
                arr = j.get("result") or []
                for it in arr:
                    if str(it.get("invoice_id")) == str(invoice_id):
                        return it
    except Exception as e:
        log.warning("CryptoBot get invoice error: %s", e)
    return None

async def _poll_crypto_invoice(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_id: int, user_id: int, invoice_id: str, usd_amount: float, tries: int = 25):
    """
    Пассивный поллинг CryptoBot-инвойса; при оплате — зачисляем в единый кошелёк (USD).
    """
    for _ in range(max(3, int(tries))):
        await asyncio.sleep(8.0)
        inv = await _crypto_get_invoice(invoice_id)
        if not inv:
            continue
        st = (inv.get("status") or "").lower()
        if st == "paid":
            if (inv.get("asset") or "").upper() == "TON":
                amt = float(inv.get("amount", 0.0)) * TON_USD_RATE
            else:
                amt = float(inv.get("amount", 0.0))
            _wallet_total_add(user_id, amt)
            with contextlib.suppress(Exception):
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=f"✅ Платёж получен через CryptoBot. Баланс пополнен на ≈ ${amt:.2f}."
                )
            return
        if st in ("cancelled","canceled","rejected","expired"):
            with contextlib.suppress(Exception):
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=f"Статус счёта: {st}"
                )
            return
    # таймаут
    with contextlib.suppress(Exception):
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text="⏳ Проверка оплаты завершена по таймауту. Нажмите «Проверить оплату» или создайте новый счёт."
        )

# ───────── FIX: безопасная версия on_doc_analyze (исправляет отступ) ─────────
# Если у тебя уже есть определение выше — это переопределение заменит некорректную версию.
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
    app.add_handler(CommandHandler("diag_luma_err", cmd_diag_luma_err))
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
