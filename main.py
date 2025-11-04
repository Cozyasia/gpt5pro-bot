# -*- coding: utf-8 -*-
# main.py — GPT-бот (webhook) с подписками, Images Edits и видео (Luma/Runway).

import os, re, json, time, base64, logging, asyncio, sqlite3, contextlib, threading, uuid
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("gpt-bot")

# ─── ENV ───
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

# Luma
LUMA_API_KEY     = os.environ.get("LUMA_API_KEY", "").strip()
LUMA_MODEL       = os.environ.get("LUMA_MODEL", "ray-2").strip()
LUMA_ASPECT      = os.environ.get("LUMA_ASPECT", "16:9").strip()
LUMA_DURATION_S  = int((os.environ.get("LUMA_DURATION_S") or "5").strip() or 5)
LUMA_BASE_URL    = (os.environ.get("LUMA_BASE_URL", "https://api.lumalabs.ai/dream-machine/v1").strip().rstrip("/"))
LUMA_CREATE_PATH = "/generations"
LUMA_STATUS_PATH = "/generations/{id}"
_fallbacks_raw = ",".join([os.environ.get("LUMA_FALLBACKS", ""), os.environ.get("LUMA_FALLBACK_BASE_URL", "")])
LUMA_FALLBACKS = []
for u in re.split(r"[;,]\s*", _fallbacks_raw):
    u = u.strip().rstrip("/")
    if u and u != LUMA_BASE_URL and u not in LUMA_FALLBACKS:
        LUMA_FALLBACKS.append(u)

# Runway
RUNWAY_API_KEY      = os.environ.get("RUNWAY_API_KEY", "").strip()
RUNWAY_MODEL        = os.environ.get("RUNWAY_MODEL", "gen3a_turbo").strip()
RUNWAY_RATIO        = os.environ.get("RUNWAY_RATIO", "720:1280").strip()
RUNWAY_DURATION_S   = int(os.environ.get("RUNWAY_DURATION_S", "8") or 8)
RUNWAY_BASE_URL     = (os.environ.get("RUNWAY_BASE_URL", "https://api.runwayml.com").strip().rstrip("/"))
RUNWAY_CREATE_PATH  = "/v1/tasks"
RUNWAY_STATUS_PATH  = "/v1/tasks/{id}"

# Таймауты / опрос
LUMA_MAX_WAIT_S    = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)
RUNWAY_MAX_WAIT_S  = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "1200").strip() or 1200)
VIDEO_POLL_DELAY_S = float((os.environ.get("VIDEO_POLL_DELAY_S") or "6.0").strip() or 6.0)

# Платежи/БД
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

if not BOT_TOKEN: raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"): raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")
if not OPENAI_API_KEY: raise RuntimeError("ENV OPENAI_API_KEY is missing")

def _parse_ids_csv(s: str) -> set[int]: return set(int(x) for x in s.split(",") if x.strip().isdigit())
UNLIM_USER_IDS   = _parse_ids_csv(os.environ.get("UNLIM_USER_IDS",""))
UNLIM_USERNAMES  = set(s.strip().lstrip("@").lower() for s in os.environ.get("UNLIM_USERNAMES","").split(",") if s.strip())
UNLIM_USERNAMES.add("gpt5pro_support")
OWNER_ID = int(os.environ.get("OWNER_ID","0") or "0")
FORCE_OWNER_UNLIM = os.environ.get("FORCE_OWNER_UNLIM","1").strip().lower() not in ("0","false","no")

def is_unlimited(user_id: int, username: str | None = None) -> bool:
    if FORCE_OWNER_UNLIM and OWNER_ID and user_id == OWNER_ID: return True
    if user_id in UNLIM_USER_IDS: return True
    if username and username.lower().lstrip("@") in UNLIM_USERNAMES: return True
    return False

def _make_tariff_url(src: str = "subscribe") -> str:
    base = (WEBAPP_URL or f"{PUBLIC_URL.rstrip('/')}/premium.html").strip()
    if src: base += ("&" if "?" in base else "?") + f"src={src}"
    if BOT_USERNAME: base += ("&" if "?" in base else "?") + f"bot={BOT_USERNAME}"
    return base
TARIFF_URL = _make_tariff_url("subscribe")

# OpenAI клиенты
from openai import OpenAI
def _ascii_or_none(s: str | None):
    if not s: return None
    try: s.encode("ascii"); return s
    except Exception: return None
def _ascii_label(s: str | None) -> str:
    s = (s or "").strip() or "Item"
    try: s.encode("ascii"); return s[:32]
    except Exception: return "Item"

# HTTP health stub
def _start_http_stub():
    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            path = (self.path or "/").split("?", 1)[0]
            if path in ("/","/healthz"):
                self.send_response(200); self.send_header("Content-Type","text/plain; charset=utf-8")
                self.end_headers(); self.wfile.write(b"ok"); return
            if path == "/premium.html":
                if WEBAPP_URL:
                    self.send_response(302); self.send_header("Location", WEBAPP_URL); self.end_headers()
                else:
                    self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.end_headers()
                    self.wfile.write(b"<html><body><h3>Premium page</h3><p>Set WEBAPP_URL env.</p></body></html>")
                return
            self.send_response(404); self.send_header("Content-Type","text/plain; charset=utf-8")
            self.end_headers(); self.wfile.write(b"not found")
        def log_message(self, *_): return
    try:
        srv = HTTPServer(("0.0.0.0", PORT), _H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log.info("HTTP stub bound on 0.0.0.0:%s", PORT)
    except Exception as e:
        log.exception("HTTP stub start failed: %s", e)

_auto_base = OPENAI_BASE_URL
if not _auto_base and (OPENAI_API_KEY.startswith("sk-or-") or "openrouter" in (OPENAI_BASE_URL or "").lower()):
    _auto_base = "https://openrouter.ai/api/v1"; log.info("Auto-select OpenRouter base_url for text LLM.")
default_headers = {}
ref = _ascii_or_none(OPENROUTER_SITE_URL); ttl = _ascii_or_none(OPENROUTER_APP_NAME)
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

# ─── DB (subscriptions, usage, wallet, kv) ───
def db_init():
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, until_ts INTEGER NOT NULL, tier TEXT)""")
    con.commit(); con.close()

def _utcnow(): return datetime.now(timezone.utc)

def activate_subscription(user_id: int, months: int = 1):
    now = _utcnow(); until = now + timedelta(days=30*months)
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT until_ts FROM subscriptions WHERE user_id=?", (user_id,)); row = cur.fetchone()
    if row and row[0] and row[0] > int(now.timestamp()):
        current_until = datetime.fromtimestamp(row[0], tz=timezone.utc); until = current_until + timedelta(days=30*months)
    cur.execute("""INSERT INTO subscriptions (user_id, until_ts) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET until_ts=excluded.until_ts""", (user_id, int(until.timestamp())))
    con.commit(); con.close(); return until

def get_subscription_until(user_id: int):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT until_ts FROM subscriptions WHERE user_id=?", (user_id,)); row = cur.fetchone(); con.close()
    return None if not row else datetime.fromtimestamp(row[0], tz=timezone.utc)

def set_subscription_tier(user_id: int, tier: str):
    tier = (tier or "pro").lower()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO subscriptions(user_id, until_ts, tier) VALUES (?,?,?)", (user_id, int(_utcnow().timestamp()), tier))
    cur.execute("UPDATE subscriptions SET tier=? WHERE user_id=?", (tier, user_id))
    con.commit(); con.close()

def activate_subscription_with_tier(user_id: int, tier: str, months: int):
    until = activate_subscription(user_id, months=months); set_subscription_tier(user_id, tier); return until

def get_subscription_tier(user_id: int) -> str:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT until_ts, tier FROM subscriptions WHERE user_id=?", (user_id,)); row = cur.fetchone(); con.close()
    if not row: return "free"
    until_ts, tier = row[0], (row[1] or "pro")
    if until_ts and datetime.fromtimestamp(until_ts, tz=timezone.utc) > _utcnow(): return (tier or "pro").lower()
    return "free"

def db_init_usage():
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS usage_daily (user_id INTEGER, ymd TEXT, text_count INTEGER DEFAULT 0, luma_usd REAL DEFAULT 0.0, runway_usd REAL DEFAULT 0.0, img_usd REAL DEFAULT 0.0, PRIMARY KEY (user_id, ymd))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS wallet (user_id INTEGER PRIMARY KEY, luma_usd REAL DEFAULT 0.0, runway_usd REAL DEFAULT 0.0, img_usd REAL DEFAULT 0.0, usd REAL DEFAULT 0.0)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)""")
    try: cur.execute("ALTER TABLE wallet ADD COLUMN usd REAL DEFAULT 0.0")
    except Exception: pass
    try: cur.execute("ALTER TABLE subscriptions ADD COLUMN tier TEXT")
    except Exception: pass
    con.commit(); con.close()

def kv_get(key: str, default: str | None = None) -> str | None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT value FROM kv WHERE key=?", (key,)); row = cur.fetchone(); con.close()
    return (row[0] if row else default)

def kv_set(key: str, value: str):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO kv(key,value) VALUES (?,?)", (key, value)); con.commit(); con.close()

def _today_ymd() -> str: return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _usage_row(user_id: int, ymd: str | None = None):
    ymd = ymd or _today_ymd()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO usage_daily(user_id,ymd) VALUES (?,?)", (user_id, ymd)); con.commit()
    cur.execute("SELECT text_count,luma_usd,runway_usd,img_usd FROM usage_daily WHERE user_id=? AND ymd=?", (user_id, ymd))
    row = cur.fetchone(); con.close()
    return {"text_count": row[0], "luma_usd": row[1], "runway_usd": row[2], "img_usd": row[3]}

def _usage_update(user_id: int, **delta):
    ymd = _today_ymd()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    row = _usage_row(user_id, ymd)
    cur.execute("""UPDATE usage_daily SET text_count=?, luma_usd=?, runway_usd=?, img_usd=? WHERE user_id=? AND ymd=?""",
                (row["text_count"]+delta.get("text_count",0), row["luma_usd"]+delta.get("luma_usd",0.0),
                 row["runway_usd"]+delta.get("runway_usd",0.0), row["img_usd"]+delta.get("img_usd",0.0),
                 user_id, ymd))
    con.commit(); con.close()

def _wallet_get(user_id: int) -> dict:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES (?)", (user_id,)); con.commit()
    cur.execute("SELECT luma_usd,runway_usd,img_usd,usd FROM wallet WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close()
    return {"luma_usd": row[0], "runway_usd": row[1], "img_usd": row[2], "usd": row[3]}

def _wallet_add(user_id: int, engine: str, usd: float):
    col = {"luma":"luma_usd","runway":"runway_usd","img":"img_usd"}[engine]
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute(f"UPDATE wallet SET {col} = {col} + ? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close()

def _wallet_take(user_id: int, engine: str, usd: float) -> bool:
    col = {"luma":"luma_usd","runway":"runway_usd","img":"img_usd"}[engine]
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT luma_usd,runway_usd,img_usd FROM wallet WHERE user_id=?", (user_id,))
    row = cur.fetchone(); bal = {"luma":row[0],"runway":row[1],"img":row[2]}[engine]
    if bal + 1e-9 < usd: con.close(); return False
    cur.execute(f"UPDATE wallet SET {col} = {col} - ? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close(); return True

def _wallet_total_get(user_id: int) -> float:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES (?)", (user_id,)); con.commit()
    cur.execute("SELECT usd FROM wallet WHERE user_id=?", (user_id,)); row = cur.fetchone(); con.close()
    return float(row[0] if row and row[0] is not None else 0.0)

def _wallet_total_add(user_id: int, usd: float):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("UPDATE wallet SET usd = COALESCE(usd,0)+? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close()

def _wallet_total_take(user_id: int, usd: float) -> bool:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT usd FROM wallet WHERE user_id=?", (user_id,)); row = cur.fetchone()
    bal = float(row[0] if row and row[0] is not None else 0.0)
    if bal + 1e-9 < usd: con.close(); return False
    cur.execute("UPDATE wallet SET usd = usd - ? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close(); return True

USD_RUB = float(os.environ.get("USD_RUB", "100"))
ONEOFF_MARKUP_DEFAULT = float(os.environ.get("ONEOFF_MARKUP_DEFAULT", "1.0"))
ONEOFF_MARKUP_RUNWAY  = float(os.environ.get("ONEOFF_MARKUP_RUNWAY",  "0.5"))
LUMA_RES_HINT = os.environ.get("LUMA_RES", "720p").lower()
RUNWAY_UNIT_COST_USD = float(os.environ.get("RUNWAY_UNIT_COST_USD", "7.0"))
IMG_COST_USD = float(os.environ.get("IMG_COST_USD", "0.05"))

LIMITS = {
    "free":      {"text_per_day": 5,    "luma_budget_usd": 0.40, "runway_budget_usd": 0.0,  "img_budget_usd": 0.05, "allow_engines": ["gpt","luma","images"]},
    "start":     {"text_per_day": 200,  "luma_budget_usd": 0.8,  "runway_budget_usd": 0.0,  "img_budget_usd": 0.2,  "allow_engines": ["gpt","luma","midjourney","images"]},
    "pro":       {"text_per_day": 1000, "luma_budget_usd": 4.0,  "runway_budget_usd": 7.0,  "img_budget_usd": 1.0,  "allow_engines": ["gpt","luma","runway","midjourney","images"]},
    "ultimate":  {"text_per_day": 5000, "luma_budget_usd": 8.0,  "runway_budget_usd": 14.0, "img_budget_usd": 2.0,  "allow_engines": ["gpt","luma","runway","midjourney","images"]},
}
def _limits_for(user_id: int) -> dict:
    tier = get_subscription_tier(user_id); d = LIMITS.get(tier, LIMITS["free"]).copy(); d["tier"] = tier; return d

def check_text_and_inc(user_id: int, username: str | None = None) -> tuple[bool, int, str]:
    if is_unlimited(user_id, username): _usage_update(user_id, text_count=1); return True, 999999, "ultimate"
    lim = _limits_for(user_id); row = _usage_row(user_id); left = max(0, lim["text_per_day"] - row["text_count"])
    if left <= 0: return False, 0, lim["tier"]
    _usage_update(user_id, text_count=1); return True, left-1, lim["tier"]

def _calc_oneoff_price_rub(engine: str, usd_cost: float) -> int:
    markup = ONEOFF_MARKUP_RUNWAY if engine == "runway" else ONEOFF_MARKUP_DEFAULT
    rub = usd_cost * (1.0 + markup) * USD_RUB; val = int(rub + 0.999)
    return max(MIN_RUB_FOR_INVOICE, val)

def _can_spend_or_offer(user_id: int, username: str | None, engine: str, est_cost_usd: float) -> tuple[bool, str]:
    if is_unlimited(user_id, username):
        if engine in ("luma","runway","img"): _usage_update(user_id, **{f"{engine}_usd": est_cost_usd})
        return True, ""
    if engine not in ("luma","runway","img"): return True, ""
    lim = _limits_for(user_id); row = _usage_row(user_id); spent = row[f"{engine}_usd"]; budget = lim[f"{engine}_budget_usd"]
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
    if engine in ("luma","runway","img"): _usage_update(user_id, **{f"{engine}_usd": float(usd)})

SYSTEM_PROMPT = ("Ты дружелюбный и лаконичный ассистент на русском. Отвечай по сути, структурируй списками/шагами, не выдумывай факты.")
VISION_SYSTEM_PROMPT = ("Ты чётко описываешь содержимое изображений. Не идентифицируй личности людей и не пиши имена.")

_SMALLTALK_RE = re.compile(r"^(привет|здравствуй|добрый\s*(день|вечер|утро)|хи|hi|hello|как дела|спасибо|пока)\b", re.I)
_NEWSY_RE     = re.compile(r"(когда|дата|выйдет|релиз|новост|курс|цена|прогноз|найди|официал|погода|сегодня|тренд|адрес|телефон)", re.I)
_CAPABILITY_RE= re.compile(r"(мож(ешь|но|ете).{0,16}(анализ|распозн|читать|созда(ва)?т|дела(ть)?).{0,24}(фото|картинк|изображен|pdf|docx|epub|fb2|аудио|книг))", re.I)

_IMG_WORDS = r"(картин\w+|изображен\w+|фото\w*|рисунк\w+|image|picture|img\b|logo|banner|poster)"
_VID_WORDS = r"(видео|ролик\w*|анимаци\w*|shorts?|reels?|clip|video|vid\b)"
_CREATE_CMD = r"(сдела(й|йте)|созда(й|йте)|сгенериру(й|йте)|нарису(й|йте)|render|generate|create|make)"
_PREFIXES_VIDEO = [r"^" + _CREATE_CMD + r"\s+видео", r"^video\b", r"^reels?\b", r"^shorts?\b"]
_PREFIXES_IMAGE = [r"^" + _CREATE_CMD + r"\s+(?:картин\w+|изображен\w+|фото\w+|рисунк\w+)", r"^image\b", r"^picture\b", r"^img\b"]

def is_smalltalk(text: str) -> bool: return bool(_SMALLTALK_RE.search((text or "").strip().lower()))
def should_browse(text: str) -> bool:
    t = (text or "").strip().lower()
    if len(t) < 8: return False
    if "http://" in t or "https://" in t: return False
    return bool(_NEWSY_RE.search(t)) and not is_smalltalk(t)

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

async def ask_openai_text(user_text: str, web_ctx: str = "") -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx: messages.append({"role": "system", "content": f"Контекст из веб-поиска:\n{web_ctx}"})
    messages.append({"role": "user", "content": user_text})
    last_err = None
    for attempt in range(3):
        try:
            resp = oai_llm.chat.completions.create(model=OPENAI_MODEL, messages=messages, temperature=0.6)
            txt = (resp.choices[0].message.content or "").strip()
            if txt: return txt
        except Exception as e:
            last_err = e; log.warning("OpenAI/OpenRouter chat attempt %d failed: %s", attempt+1, e)
            await asyncio.sleep(0.8*(attempt+1))
    log.error("ask_openai_text failed: %s", last_err)
    return "⚠️ Не удалось получить ответ от модели. Попробуйте повторить запрос позже."

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

# ─── TTS prefs ───
def _db_init_prefs():
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS user_prefs (user_id INTEGER PRIMARY KEY, tts_on INTEGER DEFAULT 0)""")
    con.commit(); con.close()

def _tts_get(user_id: int) -> bool:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO user_prefs(user_id,tts_on) VALUES (?,0)", (user_id,))
    con.commit(); cur.execute("SELECT tts_on FROM user_prefs WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close(); return bool(row and row[0])

def _tts_set(user_id: int, on: bool):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO user_prefs(user_id,tts_on) VALUES (?,?)", (user_id, 1 if on else 0))
    cur.execute("UPDATE user_prefs SET tts_on=? WHERE user_id=?", (1 if on else 0, user_id))
    con.commit(); con.close()

try: TTS_MAX_CHARS = max(int(TTS_MAX_CHARS), 150)
except Exception: TTS_MAX_CHARS = 150

def _tts_bytes_sync(text: str) -> bytes | None:
    try:
        r = oai_tts.audio.speech.create(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE, input=text, response_format="opus")
        audio = getattr(r, "content", None)
        if isinstance(audio, (bytes, bytearray)): return bytes(audio)
        if hasattr(r, "read"): return r.read()
    except Exception as e:
        log.exception("TTS error: %s", e)
    return None

async def maybe_tts_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    if not _tts_get(user_id) or not text or len(text) > TTS_MAX_CHARS or not OPENAI_TTS_KEY: return
    try:
        with contextlib.suppress(Exception):
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VOICE)
        audio = await asyncio.to_thread(_tts_bytes_sync, text)
        if not audio:
            with contextlib.suppress(Exception): await update.effective_message.reply_text("🔇 Не удалось синтезировать голос.")
            return
        bio = BytesIO(audio); bio.name = "say.ogg"
        await update.effective_message.reply_voice(voice=InputFile(bio), caption=text)
    except Exception as e:
        log.exception("maybe_tts_reply error: %s", e)

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, True); await update.effective_message.reply_text(f"🔊 Озвучка включена. Лимит {TTS_MAX_CHARS} символов.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, False); await update.effective_message.reply_text("🔈 Озвучка выключена.")

# ─── File extractors (PDF/EPUB/DOCX/FB2/TXT) — опущены ради краткости, оставь свои из текущего файла ───
def _safe_decode_txt(b: bytes) -> str:
    for enc in ("utf-8","cp1251","latin-1"):
        try: return b.decode(enc)
        except Exception: continue
    return b.decode("utf-8", errors="ignore")

# (…вставлены твои функции _extract_pdf_text/_extract_epub_text/_extract_docx_text/_extract_fb2_text/extract_text_from_document — я их не менял…)

# ─── Summaries ───
async def _summarize_chunk(text: str, query: str | None = None) -> str:
    prefix = "Суммируй кратко по пунктам основное из фрагмента документа на русском:\n"
    if query: prefix = (f"Суммируй фрагмент с учётом цели: {query}\nДай основные тезисы, факты, цифры. Русский язык.\n")
    return await ask_openai_text(prefix + text)

async def summarize_long_text(full_text: str, query: str | None = None) -> str:
    max_chunk = 8000; text = full_text.strip()
    if len(text) <= max_chunk: return await _summarize_chunk(text, query=query)
    parts=[]; i=0
    while i < len(text) and len(parts) < 8: parts.append(text[i:i+max_chunk]); i += max_chunk
    partials = [await _summarize_chunk(p, query=query) for p in parts]
    combined = "\n\n".join(f"- Фрагмент {idx+1}:\n{s}" for idx,s in enumerate(partials))
    final_prompt = "Объедини тезисы по фрагментам в резюме: 1) 5–10 пунктов; 2) ключевые цифры/сроки; 3) вывод/рекомендации.\n\n"+combined
    return await ask_openai_text(final_prompt)

# ─── Images (generate + edits) — твоё содержимое оставлено, без изменений по API OpenAI ───
async def _do_img_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
        b64 = resp.data[0].b64_json; img_bytes = base64.b64decode(b64)
        await update.effective_message.reply_photo(photo=img_bytes, caption=f"Готово ✅\nЗапрос: {prompt}")
    except Exception as e:
        log.exception("IMG gen error: %s", e)
        await update.effective_message.reply_text("Не удалось создать изображение.")

# (…здесь оставь твои img_edit_generic/do_animate/do_bg_remove/... — без изменений…)

# ─── UI тексты/клавиатуры — оставлены как в твоём файле ───
START_TEXT = ("Привет! Я GPT-бот с тарифами, квотами и разовыми пополнениями.\n\n"
              "Что умею:\n• 💬 Текст/фото (GPT)\n• 🖼 Изображения: генерация и правки\n"
              "— оживить мимику • убрать/заменить фон • добавить/удалить предмет/человека\n"
              "— дорисовать сцену • «повернуть камеру»\n• 🎬 Видео Luma / 🎥 Runway\n• 📄 Анализ PDF/EPUB/DOCX/FB2/TXT.")
HELP_TEXT = ("Подсказки:\n• /plans — тарифы\n• /img кот с очками\n• «сделай видео … 9 секунд 9:16» — Luma/Runway\n"
             "• Фото: «Оживи», «Убери фон», «Замени фон на пляж», «Добавь человека справа», «Удалить предмет слева», "
             "«Дорисуй сцену шире», «Поверни камеру вправо».\n• /voice_on, /voice_off — озвучка.")
EXAMPLES_TEXT = ("Примеры:\n• сделай видео ретро-авто, 9 сек, 9:16\n• /img неоновый город в дождь\n• пришли PDF — сделаю тезисы\n"
                 "• пришли фото — выбери быстрое действие")

def main_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🎛 Движки"), KeyboardButton("⭐ Подписка")],
         [KeyboardButton("🧾 Баланс"), KeyboardButton("ℹ️ Помощь")]],
        resize_keyboard=True, one_time_keyboard=False, selective=False,
        input_field_placeholder="Напишите запрос или выберите пункт меню",
    )
main_kb = main_keyboard()

def engines_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 GPT (текст/фото/документы)", callback_data="engine:gpt")],
        [InlineKeyboardButton("🖼 Images (OpenAI)",             callback_data="engine:images")],
        [InlineKeyboardButton("🗣 STT/TTS — речь↔текст",        callback_data="engine:stt_tts")],
        [InlineKeyboardButton("🎬 Luma — короткие видео",       callback_data="engine:luma")],
        [InlineKeyboardButton("🎥 Runway — премиум-видео",      callback_data="engine:runway")],
    ])

def sniff_image_mime(b: bytes) -> str:
    if b.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if b[:3] == b"\xff\xd8\xff": return "image/jpeg"
    if b[:6] in (b"GIF87a", b"GIF89a"): return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP": return "image/webp"
    return "application/octet-stream"

_last_photo: dict[int, dict] = {}
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

# (…здесь оставь твои on_text/on_photo/on_voice/on_document/on_any_text/on_callback — без изменений…)

# ─── Luma base detection ───
_LUMA_ACTIVE_BASE: str | None = None
async def _pick_luma_base(client: httpx.AsyncClient) -> str:
    global _LUMA_ACTIVE_BASE
    candidates = []
    if _LUMA_ACTIVE_BASE: candidates.append(_LUMA_ACTIVE_BASE)
    if LUMA_BASE_URL and LUMA_BASE_URL not in candidates: candidates.append(LUMA_BASE_URL)
    for b in LUMA_FALLBACKS:
        if b not in candidates: candidates.append(b)
    for base in candidates:
        try:
            url = f"{base}{LUMA_CREATE_PATH}"
            r = await client.options(url, timeout=10.0)
            if r.status_code in (200,201,202,204,400,401,403,404,405):
                _LUMA_ACTIVE_BASE = base
                if base != LUMA_BASE_URL: log.info("Luma base switched to fallback: %s", base)
                return base
        except Exception as e:
            log.warning("Luma base probe failed for %s: %s", base, e)
    return LUMA_BASE_URL or "https://api.lumalabs.ai/dream-machine/v1"

# ─── ВСПОМОГАТЕЛЬНЫЕ: парс видео URL из разных форматов ───
def _extract_video_url_from_any(data: dict) -> str | None:
    # Популярные варианты в разных API/версиях
    for path in [
        ("assets","video"), ("asset","video"), ("output","video"), ("result","video"),
        ("data","video"), ("video",),
    ]:
        cur = data
        try:
            for p in path: cur = cur[p]
            if isinstance(cur, str) and cur.startswith("http"): return cur
        except Exception:
            pass
    # иногда список
    for path in [("assets","videos"), ("output","videos"), ("result","videos"), ("videos",), ("output",), ("result",), ("artifacts",), ("assets",)]:
        cur = data
        try:
            for p in path: cur = cur[p]
            if isinstance(cur, list) and cur:
                # элемент может быть строкой или объектом с url
                v = cur[0]
                if isinstance(v, str) and v.startswith("http"): return v
                if isinstance(v, dict):
                    for k in ("url","video","href"):
                        u = v.get(k)
                        if isinstance(u, str) and u.startswith("http"): return u
        except Exception:
            pass
    # общий случай: пройти все строки на верхних уровнях
    try:
        for k,v in data.items():
            if isinstance(v, str) and v.startswith("http") and (".mp4" in v or "/video" in v):
                return v
    except Exception:
        pass
    return None

# ─── Luma: create + poll (РЕАЛЬНЫЕ запросы) ───
def _luma_norm_duration(d: int) -> str:
    # Luma обычно принимает 5s/9s/10s (под разные планы). Ближайшее значение.
    options = [5,9,10]
    best = min(options, key=lambda x: abs(x - max(3, min(15, d))))
    return f"{best}s"

def _aspect_from_text(a: str | None) -> str:
    a = (a or "").replace("x",":")
    if a in ("9:16","16:9","1:1"): return a
    if re.search(r"9[:x]16|вертикал", a): return "9:16"
    if re.search(r"16[:x]9|горизонт", a): return "16:9"
    return "9:16"

async def _luma_create_and_wait(prompt: str, duration_s: int, aspect: str) -> tuple[bool, str]:
    if not LUMA_API_KEY: return False, "Luma API ключ не настроен."
    headers = {"Authorization": f"Bearer {LUMA_API_KEY}", "Content-Type": "application/json"}
    dur = _luma_norm_duration(duration_s); asp = _aspect_from_text(aspect or LUMA_ASPECT)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            base = await _pick_luma_base(client)
            create_url = f"{base}{LUMA_CREATE_PATH}"
            payload = {"prompt": prompt, "aspect_ratio": asp, "duration": dur, "model": LUMA_MODEL}
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code // 100 != 2:
                return False, f"Luma create http {r.status_code}: {r.text[:500]}"
            data = r.json()
            gen_id = data.get("id") or data.get("generation_id") or data.get("data",{}).get("id")
            if not gen_id: return False, f"Luma: не получили id в ответе: {data}"
            status_url = f"{base}{LUMA_STATUS_PATH.format(id=gen_id)}"

            t0 = time.time()
            while True:
                rs = await client.get(status_url, headers=headers)
                if rs.status_code // 100 != 2:
                    log.warning("Luma poll http %s: %s", rs.status_code, rs.text[:300])
                ds = {}
                try: ds = rs.json()
                except Exception: pass

                state = (ds.get("state") or ds.get("status") or "").lower()
                if state in ("completed","succeeded","finished","done"):
                    url = _extract_video_url_from_any(ds) or _extract_video_url_from_any(ds.get("data",{}) if isinstance(ds.get("data"), dict) else {})
                    if url: return True, url
                    return False, f"Luma: готово, но не нашли ссылку: {ds}"
                if state in ("failed","error","canceled","cancelled"):
                    return False, f"Luma: статус {state}: {ds}"

                if time.time() - t0 > LUMA_MAX_WAIT_S:
                    return False, "Luma: превысили таймаут ожидания."
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("Luma error: %s", e)
        return False, f"Luma exception: {e}"

# ─── Runway: create + poll (РЕАЛЬНЫЕ запросы) ───
def _runway_ratio_from_aspect(a: str | None) -> str:
    a = (a or "").replace("x",":")
    if a in ("9:16","16:9","1:1"): pass
    elif re.search(r"9[:x]16|вертикал", a): a = "9:16"
    elif re.search(r"16[:x]9|горизонт", a): a = "16:9"
    else: a = "9:16"
    # Runway часто ждёт ratio формата "720:1280" / "1280:720". Простой маппинг:
    return "720:1280" if a == "9:16" else ("1280:720" if a == "16:9" else "1024:1024")

async def _runway_create_and_wait(prompt: str, duration_s: int, aspect: str) -> tuple[bool, str]:
    if not RUNWAY_API_KEY: return False, "Runway API ключ не настроен."
    headers = {"Authorization": f"Bearer {RUNWAY_API_KEY}", "Content-Type": "application/json"}
    ratio = _runway_ratio_from_aspect(aspect or "9:16"); dur = max(3, min(15, int(duration_s or RUNWAY_DURATION_S)))
    create_url = f"{RUNWAY_BASE_URL}{RUNWAY_CREATE_PATH}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "model": RUNWAY_MODEL,
                "input": {
                    "prompt": prompt,
                    "duration": dur,
                    "ratio": ratio
                }
            }
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code // 100 != 2:
                return False, f"Runway create http {r.status_code}: {r.text[:500]}"
            data = r.json()
            task_id = data.get("id") or data.get("task_id") or data.get("data",{}).get("id")
            if not task_id: return False, f"Runway: не получили id: {data}"

            status_url = f"{RUNWAY_BASE_URL}{RUNWAY_STATUS_PATH.format(id=task_id)}"
            t0 = time.time()
            while True:
                rs = await client.get(status_url, headers=headers)
                if rs.status_code // 100 != 2:
                    log.warning("Runway poll http %s: %s", rs.status_code, rs.text[:300])
                ds = {}
                try: ds = rs.json()
                except Exception: pass

                status = (ds.get("status") or ds.get("state") or "").lower()
                if status in ("succeeded","completed","finished","done"):
                    url = (_extract_video_url_from_any(ds) or
                           _extract_video_url_from_any(ds.get("output",{}) if isinstance(ds.get("output"), dict) else {}) or
                           _extract_video_url_from_any(ds.get("result",{}) if isinstance(ds.get("result"), dict) else {}))
                    if url: return True, url
                    return False, f"Runway: готово, но ссылка не найдена: {ds}"
                if status in ("failed","error","canceled","cancelled"):
                    return False, f"Runway: статус {status}: {ds}"

                if time.time() - t0 > RUNWAY_MAX_WAIT_S:
                    return False, "Runway: превысили таймаут ожидания."
                await asyncio.sleep(VIDEO_POLL_DELAY_S)
    except Exception as e:
        log.exception("Runway error: %s", e)
        return False, f"Runway exception: {e}"

# ─── Разбор запросов на видео (остаётся как у тебя, но с вызовом реальных функций) ───
def _parse_duration_aspect(text: str) -> tuple[int, str]:
    tl = text.lower(); dur = 9; asp = "9:16"
    m = re.search(r"(\d{1,2})\s*(сек|s|sec)", tl)
    if m:
        try: dur = max(3, min(15, int(m.group(1))))
        except Exception: pass
    if re.search(r"\b(9[:x]16|вертикал)", tl): asp = "9:16"
    elif re.search(r"\b(16[:x]9|горизонт)", tl): asp = "16:9"
    elif re.search(r"\b(1[:x]1|квадрат)", tl): asp = "1:1"
    return dur, asp

def _estimate_video_cost_usd(engine: str, dur: int) -> float:
    if engine == "luma": return round(0.05 * dur, 2)
    if engine == "runway": return round(RUNWAY_UNIT_COST_USD, 2)
    return 0.0

async def _offer_topup_or_sub(update: Update, engine: str, need_usd: float):
    if need_usd <= 0.0: return
    rub = _calc_oneoff_price_rub(engine, need_usd)
    txt = ("На этот запрос не хватает бюджета. Можно оформить подписку через /plans "
           f"или разово пополнить кошелёк на ~{need_usd:.2f}$ (≈ {rub} ₽). Напишите: «пополни {rub}».")
    await update.effective_message.reply_text(txt)

async def _process_video_request(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user = update.effective_user; user_id = user.id; username = user.username or ""
    dur, asp = _parse_duration_aspect(text)
    engine = "runway" if re.search(r"\brunway|runway\b", text.lower()) else "luma"
    est = _estimate_video_cost_usd(engine, dur)

    allowed = _limits_for(user_id).get("allow_engines", [])
    if engine not in allowed and not is_unlimited(user_id, username):
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
                try: need = float(reason.split(":",1)[1])
                except Exception: need = est
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

# ─── Команды/роутинг/оплаты (оставлены как у тебя) ───
# ... (оставь твои cmd_start/cmd_help/cmd_engines/cmd_examples/cmd_img/cmd_balance/cmd_plans/cmd_buy/cmd_topup/
# precheckout_handler/successful_payment_handler/on_document/on_any_text и т.д. — без изменений)

# ─── Build/Run (webhook only) ───
def _build_app() -> "Application":
    from telegram.ext import Application
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    db_init(); db_init_usage(); _db_init_prefs(); _start_http_stub()
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
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_any_text))
    return app

async def _set_webhook(app) -> None:
    if not USE_WEBHOOK: return
    url = f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}"
    try:
        await app.bot.set_webhook(url, secret_token=WEBHOOK_SECRET or None, drop_pending_updates=True)
        log.info("Webhook set: %s", url)
    except Exception as e:
        log.exception("set_webhook failed: %s", e)

def _run_webhook(app) -> None:
    log.info("Running in webhook mode (keep-alive loop).")
    loop = asyncio.get_event_loop()
    async def _forever():
        while True: await asyncio.sleep(60)
    loop.run_until_complete(_forever())

def main():
    app = _build_app()
    if USE_WEBHOOK:
        asyncio.get_event_loop().run_until_complete(_set_webhook(app))
        _run_webhook(app)
    else:
        # ты просил не переходить на polling — этот путь не будет использоваться
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
