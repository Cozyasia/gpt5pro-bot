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
# ───────── TTS imports ─────────
import contextlib  # уже у тебя выше есть, дублировать НЕ надо, если импорт стоит

# Optional PIL / rembg for photo tools
try:
    from PIL import Image, ImageFilter
except Exception:
    Image = None
    ImageFilter = None
try:
    from rembg import remove as rembg_remove
except Exception:
    rembg_remove = None

# ───────── LOGGING ─────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")


# ───────── ENV ─────────

def _env_float(name: str, default: float) -> float:
    """
    Безопасное чтение float из ENV:
    - поддерживает и '4,99', и '4.99'
    - при ошибке возвращает default
    """
    raw = os.environ.get(name)
    if not raw:
        return float(default)
    raw = raw.replace(",", ".").strip()
    try:
        return float(raw)
    except Exception:
        return float(default)


BOT_TOKEN        = (os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
BOT_USERNAME     = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
PUBLIC_URL       = os.environ.get("PUBLIC_URL", "").strip()
WEBAPP_URL       = os.environ.get("WEBAPP_URL", "").strip()

OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL  = os.environ.get("OPENAI_BASE_URL", "").strip()  # OpenRouter или свой прокси для текста
OPENAI_MODEL     = os.environ.get("OPENAI_MODEL", "openai/gpt-4o-mini").strip()

OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "").strip()

USE_WEBHOOK      = os.environ.get("USE_WEBHOOK", "1").lower() in ("1", "true", "yes", "on")
WEBHOOK_PATH     = os.environ.get("WEBHOOK_PATH", "/tg").strip()
WEBHOOK_SECRET   = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()

BANNER_URL       = os.environ.get("BANNER_URL", "").strip()
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "").strip()

# Общий ключ CometAPI (используется и для Kling, и для Runway)
COMETAPI_KEY     = os.environ.get("COMETAPI_KEY", "").strip()

# ВАЖНО: провайдер текста (openai / openrouter и т.п.)
TEXT_PROVIDER    = os.environ.get("TEXT_PROVIDER", "").strip()

# STT:
OPENAI_STT_KEY   = os.environ.get("OPENAI_STT_KEY", "").strip()
TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1").strip()

# TTS:
OPENAI_TTS_KEY       = os.environ.get("OPENAI_TTS_KEY", "").strip() or OPENAI_API_KEY
OPENAI_TTS_BASE_URL  = (os.environ.get("OPENAI_TTS_BASE_URL", "").strip() or "https://api.openai.com/v1")
OPENAI_TTS_MODEL     = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip()
OPENAI_TTS_VOICE     = os.environ.get("OPENAI_TTS_VOICE", "alloy").strip()
TTS_MAX_CHARS        = int((os.environ.get("TTS_MAX_CHARS") or "1000").strip() or "1000")

# Images (фолбэк — OpenAI Images)
OPENAI_IMAGE_KEY    = os.environ.get("OPENAI_IMAGE_KEY", "").strip() or OPENAI_API_KEY
IMAGES_BASE_URL     = (os.environ.get("OPENAI_IMAGE_BASE_URL", "").strip() or "https://api.openai.com/v1")
IMAGES_MODEL        = "gpt-image-1"

# ───────── Runway / CometAPI (унифицированная конфигурация) ─────────

# API-ключ:
# 1) Если RUNWAY_API_KEY указан — используем прямой Runway (рекомендуется для image→video)
# 2) Если нет — используем CometAPI_KEY (совместимость с твоим текущим проектом)
RUNWAY_API_KEY = (os.environ.get("RUNWAY_API_KEY", "").strip() or COMETAPI_KEY)

# Модель (по умолчанию Gen-3a Turbo)
RUNWAY_MODEL = os.environ.get("RUNWAY_MODEL", "gen3a_turbo").strip()

# Рекомендуемый ratio — указываем в виде "1280:720", "720:1280", "960:960"
RUNWAY_RATIO = os.environ.get("RUNWAY_RATIO", "1280:720").strip()

# Длительность video default
RUNWAY_DURATION_S = int((os.environ.get("RUNWAY_DURATION_S") or "5").strip() or "5")

# Максимальное ожидание результата (сек)
RUNWAY_MAX_WAIT_S = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "1200").strip() or "1200")

# База API:
# ВАЖНО: Runway image→video корректно работает ТОЛЬКО через официальную базу:
#   https://api.runwayml.com
# CometAPI остаётся как fallback (через env), но по умолчанию ставим официальный URL
RUNWAY_BASE_URL = (
    os.environ.get("RUNWAY_BASE_URL", "https://api.runwayml.com")
        .strip()
        .rstrip("/")
)

# Эндпоинты Runway (официальные и совместимые)
RUNWAY_IMAGE2VIDEO_PATH = "/v1/image_to_video"      # новый корректный endpoint Runway
RUNWAY_TEXT2VIDEO_PATH  = "/v1/text_to_video"       # универсальный endpoint Runway
RUNWAY_STATUS_PATH      = "/v1/tasks/{id}"          # единый статусный endpoint Runway

# Версия Runway API (обязательно!)
RUNWAY_API_VERSION = os.environ.get("RUNWAY_API_VERSION", "2024-11-06").strip()

# ───────── Luma ─────────

LUMA_API_KEY     = os.environ.get("LUMA_API_KEY", "").strip()

# Всегда гарантируем непустой model/aspect, даже если в ENV пустая строка
_LUMA_MODEL_ENV  = (os.environ.get("LUMA_MODEL") or "").strip()
LUMA_MODEL       = _LUMA_MODEL_ENV or "ray-2"

_LUMA_ASPECT_ENV = (os.environ.get("LUMA_ASPECT") or "").strip()
LUMA_ASPECT      = _LUMA_ASPECT_ENV or "16:9"

LUMA_DURATION_S  = int((os.environ.get("LUMA_DURATION_S") or "5").strip() or 5)

# База уже содержит /dream-machine/v1 → дальше добавляем /generations
LUMA_BASE_URL    = (
    os.environ.get("LUMA_BASE_URL", "https://api.lumalabs.ai/dream-machine/v1")
    .strip()
    .rstrip("/")
)
LUMA_CREATE_PATH = "/generations"
LUMA_STATUS_PATH = "/generations/{id}"

# Максимальный таймаут ожидания Luma
LUMA_MAX_WAIT_S  = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)

# Luma Images (опционально: если нет — используем OpenAI Images как фолбэк)
LUMA_IMG_BASE_URL = os.environ.get("LUMA_IMG_BASE_URL", "").strip().rstrip("/")
LUMA_IMG_MODEL    = os.environ.get("LUMA_IMG_MODEL", "imagine-image-1").strip()

# Фолбэки Luma
_fallbacks_raw = ",".join([
    os.environ.get("LUMA_FALLBACKS", ""),
    os.environ.get("LUMA_FALLBACK_BASE_URL", ""),
])
LUMA_FALLBACKS: list[str] = []
for u in re.split(r"[;,]\s*", _fallbacks_raw):
    if not u:
        continue
    u = u.strip().rstrip("/")
    if u and u != LUMA_BASE_URL and u not in LUMA_FALLBACKS:
        LUMA_FALLBACKS.append(u)

# ───────── Kling (новый видеодвижок через CometAPI) ─────────

KLING_BASE_URL   = os.environ.get("KLING_BASE_URL", "https://api.cometapi.com").strip().rstrip("/")
KLING_MODEL_NAME = os.environ.get("KLING_MODEL_NAME", "kling-v1-6").strip()
KLING_MODE       = os.environ.get("KLING_MODE", "std").strip()
KLING_ASPECT     = os.environ.get("KLING_ASPECT", "9:16").strip()
KLING_DURATION_S = int((os.environ.get("KLING_DURATION_S") or "5").strip() or 5)
KLING_MAX_WAIT_S = int((os.environ.get("KLING_MAX_WAIT_S") or "900").strip() or 900)
KLING_UNIT_COST_USD = float((os.environ.get("KLING_UNIT_COST_USD") or "0.80").replace(",", ".") or "0.80")

# Общий интервал между опросами статуса задач видео
VIDEO_POLL_DELAY_S = _env_float("VIDEO_POLL_DELAY_S", 6.0)

# ───────── КЭШИ / ГЛОБАЛЬНОЕ СОСТОЯНИЕ ─────────

# Последнее фото пользователя для анимации (оживления)
# user_id -> {"bytes": b"...", "url": "https://..."}
_LAST_ANIM_PHOTO: dict[int, dict] = {}
# ───────── Runway через CometAPI ─────────

# Ключ берём из RUNWAY_API_KEY, а если он пустой — используем общий COMETAPI_KEY
RUNWAY_API_KEY     = (os.environ.get("RUNWAY_API_KEY", "").strip() or COMETAPI_KEY)

# Модель Runway, которая идёт через CometAPI
RUNWAY_MODEL       = os.environ.get("RUNWAY_MODEL", "gen3a_turbo").strip()

# Рекомендуемый формат — разрешение, как в новой версии API (см. docs Runway)
# Можно задать "1280:720", "720:1280", "960:960" и т.п.
RUNWAY_RATIO       = os.environ.get("RUNWAY_RATIO", "1280:720").strip()

RUNWAY_DURATION_S  = int((os.environ.get("RUNWAY_DURATION_S") or "5").strip() or 5)
RUNWAY_MAX_WAIT_S  = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "900").strip() or 900)

# База именно CometAPI (а не api.dev.runwayml.com)
RUNWAY_BASE_URL          = (os.environ.get("RUNWAY_BASE_URL", "https://api.cometapi.com").strip().rstrip("/"))

# Эндпоинты Runway через CometAPI
RUNWAY_IMAGE2VIDEO_PATH  = "/runwayml/v1/image_to_video"
RUNWAY_TEXT2VIDEO_PATH   = "/runwayml/v1/text_to_video"
RUNWAY_STATUS_PATH       = "/runwayml/v1/tasks/{id}"

# Версия Runway API — обязательно 2024-11-06 (как в их доке)
RUNWAY_API_VERSION = os.environ.get("RUNWAY_API_VERSION", "2024-11-06").strip()

# ───────── Luma ─────────

LUMA_API_KEY     = os.environ.get("LUMA_API_KEY", "").strip()

# Всегда гарантируем непустой model/aspect, даже если в ENV пустая строка
_LUMA_MODEL_ENV  = (os.environ.get("LUMA_MODEL") or "").strip()
LUMA_MODEL       = _LUMA_MODEL_ENV or "ray-2"

_LUMA_ASPECT_ENV = (os.environ.get("LUMA_ASPECT") or "").strip()
LUMA_ASPECT      = _LUMA_ASPECT_ENV or "16:9"

LUMA_DURATION_S  = int((os.environ.get("LUMA_DURATION_S") or "5").strip() or 5)

# База уже содержит /dream-machine/v1 → дальше добавляем /generations
LUMA_BASE_URL    = (
    os.environ.get("LUMA_BASE_URL", "https://api.lumalabs.ai/dream-machine/v1")
    .strip()
    .rstrip("/")
)
LUMA_CREATE_PATH = "/generations"
LUMA_STATUS_PATH = "/generations/{id}"

# Максимальный таймаут ожидания Luma
LUMA_MAX_WAIT_S  = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)

# Luma Images (опционально: если нет — используем OpenAI Images как фолбэк)
LUMA_IMG_BASE_URL = os.environ.get("LUMA_IMG_BASE_URL", "").strip().rstrip("/")
LUMA_IMG_MODEL    = os.environ.get("LUMA_IMG_MODEL", "imagine-image-1").strip()

# Фолбэки Luma
_fallbacks_raw = ",".join([
    os.environ.get("LUMA_FALLBACKS", ""),
    os.environ.get("LUMA_FALLBACK_BASE_URL", ""),
])
LUMA_FALLBACKS: list[str] = []
for u in re.split(r"[;,]\s*", _fallbacks_raw):
    if not u:
        continue
    u = u.strip().rstrip("/")
    if u and u != LUMA_BASE_URL and u not in LUMA_FALLBACKS:
        LUMA_FALLBACKS.append(u)

# ───────── Kling (новый видеодвижок через CometAPI) ─────────

KLING_BASE_URL   = os.environ.get("KLING_BASE_URL", "https://api.cometapi.com").strip().rstrip("/")
KLING_MODEL_NAME = os.environ.get("KLING_MODEL_NAME", "kling-v1-6").strip()
KLING_MODE       = os.environ.get("KLING_MODE", "std").strip()
KLING_ASPECT     = os.environ.get("KLING_ASPECT", "9:16").strip()
KLING_DURATION_S = int((os.environ.get("KLING_DURATION_S") or "5").strip() or 5)
KLING_MAX_WAIT_S = int((os.environ.get("KLING_MAX_WAIT_S") or "900").strip() or 900)
KLING_UNIT_COST_USD = float((os.environ.get("KLING_UNIT_COST_USD") or "0.80").replace(",", ".") or "0.80")

# Общий интервал между опросами статуса задач видео
VIDEO_POLL_DELAY_S = _env_float("VIDEO_POLL_DELAY_S", 6.0)

# ───────── КЭШИ / ГЛОБАЛЬНОЕ СОСТОЯНИЕ ─────────

# Последнее фото пользователя для анимации (оживления)
# user_id -> {"bytes": b"...", "url": "https://..."}
_LAST_ANIM_PHOTO: dict[int, dict] = {}

# ───────── UTILS ---------
_LUMA_ACTIVE_BASE = None  # кэш последнего живого базового URL

async def _pick_luma_base(client: httpx.AsyncClient) -> str:
    global _LUMA_ACTIVE_BASE
    candidates = []
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
DB_PATH        = os.path.abspath(os.environ.get("DB_PATH", "subs.db"))

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

# =============================
# Language / i18n
# =============================

LANGS: list[str] = ["ru", "be", "uk", "de", "en", "fr", "th"]
LANG_NAMES: dict[str, str] = {
    "ru": "Русский",
    "be": "Белорусский",
    "uk": "Украинский",
    "de": "Deutsch",
    "en": "English",
    "fr": "Français",
    "th": "ไทย",
}

def _lang_key(user_id: int) -> str:
    return f"lang:{user_id}"

def has_lang(user_id: int) -> bool:
    return bool((kv_get(_lang_key(user_id), "") or "").strip())

def get_lang(user_id: int) -> str:
    lang = (kv_get(_lang_key(user_id), "") or "").strip()
    return lang if lang in LANGS else "ru"

def set_lang(user_id: int, lang: str) -> None:
    if lang not in LANGS:
        lang = "ru"
    kv_set(_lang_key(user_id), lang)

# Mini-dictionary (menus/buttons)
I18N: dict[str, dict[str, str]] = {
    "ru": {
        "choose_lang": "🌍 Выберите язык",
        "lang_set": "✅ Язык установлен",
        "menu_title": "Главное меню",
        "btn_engines": "🧠 Движки",
        "btn_sub": "⭐ Подписка • Помощь",
        "btn_wallet": "🧾 Баланс",
        "btn_video": "🎞 Создать видео",
        "btn_photo": "🖼 Оживить фото",
        "btn_help": "❓ Помощь",
        "btn_back": "⬅️ Назад",
    },
    "be": {
        "choose_lang": "🌍 Абярыце мову",
        "lang_set": "✅ Мова ўсталявана",
        "menu_title": "Галоўнае меню",
        "btn_engines": "🧠 Рухавікі",
        "btn_sub": "⭐ Падпіска • Дапамога",
        "btn_wallet": "🧾 Баланс",
        "btn_video": "🎞 Стварыць відэа",
        "btn_photo": "🖼 Ажывіць фота",
        "btn_help": "❓ Дапамога",
        "btn_back": "⬅️ Назад",
    },
    "uk": {
        "choose_lang": "🌍 Оберіть мову",
        "lang_set": "✅ Мову встановлено",
        "menu_title": "Головне меню",
        "btn_engines": "🧠 Рушії",
        "btn_sub": "⭐ Підписка • Допомога",
        "btn_wallet": "🧾 Баланс",
        "btn_video": "🎞 Створити відео",
        "btn_photo": "🖼 Оживити фото",
        "btn_help": "❓ Допомога",
        "btn_back": "⬅️ Назад",
    },
    "de": {
        "choose_lang": "🌍 Sprache wählen",
        "lang_set": "✅ Sprache gesetzt",
        "menu_title": "Hauptmenü",
        "btn_engines": "🧠 Engines",
        "btn_sub": "⭐ Abo • Hilfe",
        "btn_wallet": "🧾 Guthaben",
        "btn_video": "🎞 Video erstellen",
        "btn_photo": "🖼 Foto animieren",
        "btn_help": "❓ Hilfe",
        "btn_back": "⬅️ Zurück",
    },
    "en": {
        "choose_lang": "🌍 Choose language",
        "lang_set": "✅ Language set",
        "menu_title": "Main menu",
        "btn_engines": "🧠 Engines",
        "btn_sub": "⭐ Subscription • Help",
        "btn_wallet": "🧾 Balance",
        "btn_video": "🎞 Create video",
        "btn_photo": "🖼 Animate photo",
        "btn_help": "❓ Help",
        "btn_back": "⬅️ Back",
    },
    "fr": {
        "choose_lang": "🌍 Choisir la langue",
        "lang_set": "✅ Langue définie",
        "menu_title": "Menu principal",
        "btn_engines": "🧠 Moteurs",
        "btn_sub": "⭐ Abonnement • Aide",
        "btn_wallet": "🧾 Solde",
        "btn_video": "🎞 Créer une vidéo",
        "btn_photo": "🖼 Animer une photo",
        "btn_help": "❓ Aide",
        "btn_back": "⬅️ Retour",
    },
    "th": {
        "choose_lang": "🌍 เลือกภาษา",
        "lang_set": "✅ ตั้งค่าภาษาแล้ว",
        "menu_title": "เมนูหลัก",
        "btn_engines": "🧠 เอนจิน",
        "btn_sub": "⭐ สมัครสมาชิก • ช่วยเหลือ",
        "btn_wallet": "🧾 ยอดคงเหลือ",
        "btn_video": "🎞 สร้างวิดีโอ",
        "btn_photo": "🖼 ทำให้รูปเคลื่อนไหว",
        "btn_help": "❓ ช่วยเหลือ",
        "btn_back": "⬅️ กลับ",
    },
}

def t(user_id: int, key: str) -> str:
    lang = get_lang(user_id)
    return (I18N.get(lang) or I18N["ru"]).get(key, key)

def system_prompt_for(lang: str) -> str:
    mapping = {
        "ru": "Отвечай на русском языке.",
        "be": "Адказвай па-беларуску.",
        "uk": "Відповідай українською мовою.",
        "de": "Antworte auf Deutsch.",
        "en": "Answer in English.",
        "fr": "Réponds en français.",
        "th": "ตอบเป็นภาษาไทย",
    }
    return mapping.get(lang, mapping["ru"])

# Extended pack (long UI texts / hints)
I18N_PACK: dict[str, dict[str, str]] = {
    "welcome": {
        "ru": "Привет! Я Нейро‑Bot — ⚡ мультирежимный бот из 7 нейросетей для учёбы, работы и развлечений.",
        "be": "Прывітанне! Я Нейро‑Bot — ⚡ шматрэжымны бот з 7 нейрасетак для вучобы, працы і забаў.",
        "uk": "Привіт! Я Нейро‑Bot — ⚡ мультирежимний бот із 7 нейромереж для навчання, роботи та розваг.",
        "de": "Hallo! Ich bin Neuro‑Bot — ⚡ ein Multimode‑Bot mit 7 KI‑Engines für Lernen, Arbeit und Spaß.",
        "en": "Hi! I’m Neuro‑Bot — ⚡ a multi‑mode bot with 7 AI engines for study, work and fun.",
        "fr": "Salut ! Je suis Neuro‑Bot — ⚡ un bot multi‑modes avec 7 moteurs IA pour étudier, travailler et se divertir.",
        "th": "สวัสดี! ฉันคือ Neuro‑Bot — ⚡ บอทหลายโหมดพร้อมเอนจิน AI 7 ตัว สำหรับเรียน งาน และความบันเทิง",
    },
    "ask_video_prompt": {
        "ru": "🎞 Напиши запрос для видео, например:\n«Сделай видео: закат над морем, 7 сек, 16:9»",
        "be": "🎞 Напішы запыт для відэа, напрыклад:\n«Зрабі відэа: захад сонца над морам, 7 сек, 16:9»",
        "uk": "🎞 Напиши запит для відео, наприклад:\n«Зроби відео: захід над морем, 7 с, 16:9»",
        "de": "🎞 Schreibe einen Prompt für das Video, z.B.:\n„Erstelle ein Video: Sonnenuntergang am Meer, 7s, 16:9“",
        "en": "🎞 Type a video prompt, e.g.:\n“Make a video: sunset over the sea, 7s, 16:9”",
        "fr": "🎞 Écris un prompt pour la vidéo, par ex. :\n« Fais une vidéo : coucher de soleil sur la mer, 7s, 16:9 »",
        "th": "🎞 พิมพ์คำสั่งทำวิดีโอ เช่น:\n“ทำวิดีโอ: พระอาทิตย์ตกเหนือทะเล 7วิ 16:9”",
    },
    "ask_send_photo": {
        "ru": "🖼 Пришли фото, затем выбери «Оживить фото».",
        "be": "🖼 Дашлі фота, затым выберы «Ажывіць фота».",
        "uk": "🖼 Надішли фото, потім обери «Оживити фото».",
        "de": "🖼 Sende ein Foto, dann wähle „Foto animieren“.",
        "en": "🖼 Send a photo, then choose “Animate photo”.",
        "fr": "🖼 Envoyez une photo, puis choisissez « Animer la photo ».",
        "th": "🖼 ส่งรูป จากนั้นเลือก “ทำให้รูปเคลื่อนไหว”",
    },
    "photo_received": {
        "ru": "🖼 Фото получено. Хотите оживить?",
        "be": "🖼 Фота атрымана. Ажывіць?",
        "uk": "🖼 Фото отримано. Оживити?",
        "de": "🖼 Foto erhalten. Animieren?",
        "en": "🖼 Photo received. Animate it?",
        "fr": "🖼 Photo reçue. L’animer ?",
        "th": "🖼 ได้รับรูปแล้ว ต้องการทำให้เคลื่อนไหวไหม?",
    },
    "animate_btn": {
        "ru": "🎬 Оживить фото",
        "be": "🎬 Ажывіць фота",
        "uk": "🎬 Оживити фото",
        "de": "🎬 Foto animieren",
        "en": "🎬 Animate photo",
        "fr": "🎬 Animer la photo",
        "th": "🎬 ทำให้รูปเคลื่อนไหว",
    },
    "choose_engine": {
        "ru": "Выберите движок:",
        "be": "Абярыце рухавік:",
        "uk": "Оберіть рушій:",
        "de": "Wähle die Engine:",
        "en": "Choose engine:",
        "fr": "Choisissez le moteur:",
        "th": "เลือกเอนจิน:",
    },
    "runway_disabled_textvideo": {
        "ru": "⚠️ Runway отключён для видео по тексту/голосу. Выберите Kling, Luma или Sora.",
        "be": "⚠️ Runway адключаны для відэа па тэксце/голасе. Абярыце Kling, Luma або Sora.",
        "uk": "⚠️ Runway вимкнено для відео з тексту/голосу. Оберіть Kling, Luma або Sora.",
        "de": "⚠️ Runway ist für Text/Voice→Video deaktiviert. Wähle Kling, Luma oder Sora.",
        "en": "⚠️ Runway is disabled for text/voice→video. Choose Kling, Luma or Sora.",
        "fr": "⚠️ Runway est désactivé pour texte/voix→vidéo. Choisissez Kling, Luma ou Sora.",
        "th": "⚠️ ปิด Runway สำหรับข้อความ/เสียง→วิดีโอ เลือก Kling, Luma หรือ Sora",
    },
}

def _tr(user_id: int, key: str, **kwargs) -> str:
    lang = get_lang(user_id)
    pack = I18N_PACK.get(key) or {}
    s = pack.get(lang) or pack.get("ru") or key
    if kwargs:
        try:
            return s.format(**kwargs)
        except Exception:
            return s
    return s

def _lang_choose_kb() -> InlineKeyboardMarkup:
    rows = []
    for code in LANGS:
        rows.append([InlineKeyboardButton(LANG_NAMES[code], callback_data=f"lang:{code}")])
    return InlineKeyboardMarkup(rows)



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

# ───────────────── SORA (via Comet / aggregator) ─────────────────
# Variables may be provided later; keep disabled safely by default.
SORA_ENABLED = bool(os.environ.get("SORA_ENABLED", "").strip())
SORA_COMET_BASE_URL = os.environ.get("SORA_COMET_BASE_URL", "").strip()  # e.g. https://api.cometapi.com
SORA_COMET_API_KEY = os.environ.get("SORA_COMET_API_KEY", "").strip()
SORA_MODEL_FREE = os.environ.get("SORA_MODEL_FREE", "sora-2").strip()
SORA_MODEL_PRO = os.environ.get("SORA_MODEL_PRO", "sora-2-pro").strip()
SORA_UNIT_COST_USD = float(os.environ.get("SORA_UNIT_COST_USD", "0.40"))  # fallback estimate per second


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

    ENGINE_BUDGET_GROUP = {
    "luma":   "luma",
    "kling":  "luma",    # <– Kling сидит на том же бюджете
    "runway": "runway",
    "img":    "img",
}

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

# какие движки на какой бюджет садятся
ENGINE_BUDGET_GROUP = {
    "luma": "luma",
    "kling": "luma",   # Kling и Luma делят один бюджет
    "runway": "runway",
    "img": "img",
}


def _can_spend_or_offer(
    user_id: int,
    username: str | None,
    engine: str,
    est_cost_usd: float,
) -> tuple[bool, str]:
    """
    Проверяем, можно ли потратить est_cost_usd на указанный движок.
    Возвращаем (ok, reason):
      ok = True  -> можно, reason = ""
      ok = False -> нельзя, reason = "ASK_SUBSCRIBE" или "OFFER:<usd>"
    """
    group = ENGINE_BUDGET_GROUP.get(engine, engine)

    # безлимитные пользователи
    if is_unlimited(user_id, username):
        if group in ("luma", "runway", "img"):
            _usage_update(user_id, **{f"{group}_usd": est_cost_usd})
        return True, ""

    # если движок не тарифицируемый — просто разрешаем
    if group not in ("luma", "runway", "img"):
        return True, ""

    tier = get_subscription_tier(user_id)
    lim = _limits_for(user_id)
    row = _usage_row(user_id)

    spent = row[f"{group}_usd"]
    budget = lim[f"{group}_budget_usd"]

    # если влезаем в дневной бюджет по группе (luma/runway/img)
    if spent + est_cost_usd <= budget + 1e-9:
        _usage_update(user_id, **{f"{group}_usd": est_cost_usd})
        return True, ""

    # Попытка покрыть из единого кошелька
    need = max(0.0, spent + est_cost_usd - budget)
    if need > 0:
        if _wallet_total_take(user_id, need):
            _usage_update(user_id, **{f"{group}_usd": est_cost_usd})
            return True, ""

        # на фри-тарифе просим оформить подписку
        if tier == "free":
            return False, "ASK_SUBSCRIBE"

        # на платных тарифах показываем предложение докупить лимит
        return False, f"OFFER:{need:.2f}"

    return True, ""


def _register_engine_spend(user_id: int, engine: str, usd: float):
    """
    Регистрируем уже совершённый расход по движку.
    Используется для тех вызовов, где стоимость известна постфактум
    или когда пользователь безлимитный.
    """
    group = ENGINE_BUDGET_GROUP.get(engine, engine)
    if group in ("luma", "runway", "img"):
        _usage_update(user_id, **{f"{group}_usd": float(usd)})
        
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
    """
    Пытаемся понять, просит ли пользователь:
    - сгенерировать ВИДЕО ("video")
    - сгенерировать КАРТИНКУ ("image")
    Возвращаем кортеж (mtype, rest), где:
        mtype ∈ {"video", "image", None}
        rest  — очищенный промпт без служебных слов.
    """
    if not text:
        return (None, "")

    t = text.strip()
    tl = t.lower()

    # Вопросы "что ты умеешь?" и т.п. сразу отбрасываем
    if _looks_like_capability_question(tl):
        return (None, "")

    # 1) Явные паттерны для видео (с учётом новых _PREFIXES_VIDEO)
    for p in _PREFIXES_VIDEO:
        m = re.search(p, tl, re.I)
        if m:
            return ("video", _after_match(t, m))

    # 2) Явные паттерны для картинок (новые _PREFIXES_IMAGE)
    for p in _PREFIXES_IMAGE:
        m = re.search(p, tl, re.I)
        if m:
            return ("image", _after_match(t, m))

    # 3) Общий случай: если есть глагол из _CREATE_CMD
    #    и отдельно слова "видео/ролик" или "картинка/фото/…"
    if re.search(_CREATE_CMD, tl, re.I):
        # --- видео ---
        if re.search(_VID_WORDS, tl, re.I):
            # вырезаем "видео/ролик" и глагол ИЗ ОРИГИНАЛЬНОЙ СТРОКИ t
            clean = re.sub(_VID_WORDS, "", t, flags=re.I)
            clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
            return ("video", _strip_leading(clean))

        # --- картинки ---
        if re.search(_IMG_WORDS, tl, re.I):
            clean = re.sub(_IMG_WORDS, "", t, flags=re.I)
            clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
            return ("image", _strip_leading(clean))

    # 4) Старые короткие форматы "img: ..." / "image: ..." / "picture: ..."
    m = re.match(r"^(img|image|picture)\s*[:\-]\s*(.+)$", tl)
    if m:
        # берём хвост уже из оригинальной строки t
        return ("image", _strip_leading(t[m.end(1) + 1:]))

    # 5) Старые короткие форматы "video: ..." / "reels: ..." / "shorts: ..."
    m = re.match(r"^(video|vid|reels?|shorts?)\s*[:\-]\s*(.+)$", tl)
    if m:
        return ("video", _strip_leading(t[m.end(1) + 1:]))

    # Ничего не нашли — обычный текст
    return (None, "")
# ───────── OpenAI helpers ─────────
def _oai_text_client():
    return oai_llm

def _pick_vision_model() -> str:
    try:
        mv = globals().get("OPENAI_VISION_MODEL")
        return (mv or OPENAI_MODEL).strip()
    except Exception:
        return OPENAI_MODEL

async def ask_openai_text(user_text: str, web_ctx: str = "") -> str:
    """
    Универсальный запрос к LLM:
    - поддерживает OpenRouter (через OPENAI_API_KEY = sk-or-...);
    - принудительно шлёт JSON в UTF-8, чтобы не было ascii-ошибок;
    - логирует HTTP-статус и тело ошибки в Render-логи;
    - делает до 3 попыток с небольшой паузой.
    """
    user_text = (user_text or "").strip()
    if not user_text:
        return "Пустой запрос."

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({
            "role": "system",
            "content": f"Контекст из веб-поиска:\n{web_ctx}",
        })
    messages.append({"role": "user", "content": user_text})

    # ── Базовый URL ─────────────────────────────────────────────────────────
    # Если ключ от OpenRouter или TEXT_PROVIDER=openrouter — шлём на OpenRouter
    provider = (TEXT_PROVIDER or "").strip().lower()
    if OPENAI_API_KEY.startswith("sk-or-") or provider == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
    else:
        base_url = (OPENAI_BASE_URL or "").strip() or "https://api.openai.com/v1"

    # ── Заголовки ───────────────────────────────────────────────────────────
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept-Charset": "utf-8",
    }

    # Служебные заголовки OpenRouter
    if "openrouter.ai" in base_url:
        if OPENROUTER_SITE_URL:
            headers["HTTP-Referer"] = OPENROUTER_SITE_URL
        if OPENROUTER_APP_NAME:
            headers["X-Title"] = OPENROUTER_APP_NAME

    last_err: Exception | None = None

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=90.0,
            ) as client:
                resp = await client.post(
                    "/chat/completions",
                    json={
                        "model": OPENAI_MODEL,
                        "messages": messages,
                        "temperature": 0.6,
                    },
                    headers=headers,
                )

            # Логируем всё, что не 2xx
            if resp.status_code // 100 != 2:
                body_preview = resp.text[:800]
                log.warning(
                    "LLM HTTP %s from %s: %s",
                    resp.status_code,
                    base_url,
                    body_preview,
                )
                resp.raise_for_status()

            data = resp.json()
            txt = (data["choices"][0]["message"]["content"] or "").strip()
            if txt:
                return txt

        except Exception as e:
            last_err = e
            log.warning(
                "OpenAI/OpenRouter chat attempt %d failed: %s",
                attempt + 1,
                e,
            )
            await asyncio.sleep(0.8 * (attempt + 1))

    log.error("ask_openai_text failed after 3 attempts: %s", last_err)
    return (
        "⚠️ Сейчас не получилось получить ответ от модели. "
        "Я на связи — попробуй переформулировать запрос или повторить чуть позже."
    )
    
async def ask_openai_vision(user_text: str, img_b64: str, mime: str) -> str:
    try:
        prompt = (user_text or "Опиши, что на изображении и какой там текст.").strip()
        model = _pick_vision_model()
        resp = _oai_text_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
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
    try:
        _db_init_prefs()
    except Exception:
        pass
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO user_prefs(user_id, tts_on) VALUES (?,0)", (user_id,))
    con.commit()
    cur.execute("SELECT tts_on FROM user_prefs WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close()
    return bool(row and row[0])

def _tts_set(user_id: int, on: bool):
    try:
        _db_init_prefs()
    except Exception:
        pass
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO user_prefs(user_id, tts_on) VALUES (?,?)", (user_id, 1 if on else 0))
    cur.execute("UPDATE user_prefs SET tts_on=? WHERE user_id=?", (1 if on else 0, user_id))
    con.commit(); con.close()


# ───────── Надёжный TTS через REST (OGG/Opus) ─────────
def _tts_bytes_sync(text: str) -> bytes | None:
    try:
        if not OPENAI_TTS_KEY:
            return None
        if OPENAI_TTS_KEY.startswith("sk-or-"):
            log.error("TTS key looks like OpenRouter (sk-or-...). Provide a real OpenAI key in OPENAI_TTS_KEY.")
            return None
        url = f"{OPENAI_TTS_BASE_URL.rstrip('/')}/audio/speech"
        payload = {
            "model": OPENAI_TTS_MODEL,
            "voice": OPENAI_TTS_VOICE,
            "input": text,
            "format": "ogg"  # OGG/Opus для Telegram voice
        }
        headers = {
            "Authorization": f"Bearer {OPENAI_TTS_KEY}",
            "Content-Type": "application/json"
        }
        r = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        r.raise_for_status()
        data = r.content if r.content else None
        if data:
            log.info("TTS bytes: %s bytes", len(data))
        return data
    except Exception as e:
        log.exception("TTS HTTP error: %s", e)
        return None

async def maybe_tts_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    if not _tts_get(user_id):
        return
    text = (text or "").strip()
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
        bio = BytesIO(audio); bio.seek(0); bio.name = "say.ogg"
        await update.effective_message.reply_voice(voice=InputFile(bio), caption=text)
    except Exception as e:
        log.exception("maybe_tts_reply error: %s", e)

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, True)
    await update.effective_message.reply_text(f"🔊 Озвучка включена. Лимит {TTS_MAX_CHARS} символов на ответ.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, False)
    await update.effective_message.reply_text("🔈 Озвучка выключена.")

# ───────── Speech-to-Text (STT) • OpenAI Whisper/4o-mini-transcribe ─────────
from openai import OpenAI as _OpenAI_STT

OPENAI_STT_MODEL    = (os.getenv("OPENAI_STT_MODEL") or "whisper-1").strip()
OPENAI_STT_KEY      = (os.getenv("OPENAI_STT_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_STT_BASE_URL = (os.getenv("OPENAI_STT_BASE_URL") or "https://api.openai.com/v1").rstrip("/")

def _oai_stt_client():
    return _OpenAI_STT(api_key=OPENAI_STT_KEY, base_url=OPENAI_STT_BASE_URL)

async def _stt_transcribe_bytes(filename: str, raw: bytes) -> str:
    last_err = None
    for attempt in range(3):
        try:
            bio = BytesIO(raw)
            bio.name = filename
            bio.seek(0)
            resp = _oai_stt_client().audio.transcriptions.create(
                model=OPENAI_STT_MODEL,
                file=bio,
            )
            text = (getattr(resp, "text", "") or "").strip()
            if text:
                return text
        except Exception as e:
            last_err = e
            log.warning("STT attempt %d failed: %s", attempt+1, e)
            await asyncio.sleep(0.8 * (attempt + 1))
    log.error("STT failed: %s", last_err)
    return ""

# ───────── Хендлер голосовых/аудио ─────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    voice = getattr(msg, "voice", None)
    audio = getattr(msg, "audio", None)
    media = voice or audio
    if not media:
        await msg.reply_text("Не нашёл голосовой файл.")
        return

    # Скачиваем файл
    try:
        with contextlib.suppress(Exception):
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

        tg_file = await context.bot.get_file(media.file_id)
        buf = BytesIO()
        await tg_file.download_to_memory(out=buf)
        raw = buf.getvalue()

        mime = (getattr(media, "mime_type", "") or "").lower()
        if "ogg" in mime or "opus" in mime:
            filename = "voice.ogg"
        elif "webm" in mime:
            filename = "voice.webm"
        elif "wav" in mime:
            filename = "voice.wav"
        elif "mp3" in mime or "mpeg" in mime or "mpga" in mime:
            filename = "voice.mp3"
        else:
            filename = "voice.ogg"

    except Exception as e:
        log.exception("TG download error: %s", e)
        await msg.reply_text("Не удалось скачать голосовое сообщение.")
        return

    # STT
    transcript = await _stt_transcribe_bytes(filename, raw)
    if not transcript:
        await msg.reply_text("Ошибка при распознавании речи.")
        return

    transcript = transcript.strip()

    # Показываем текст для отладки
    with contextlib.suppress(Exception):
        await msg.reply_text(f"🗣️ Распознал: {transcript}")

    # ——— КЛЮЧЕВОЙ МОМЕНТ ———
    # Больше НЕ создаём фейковый Update, не лезем в Message.text — это запрещено в Telegram API
    # Теперь мы используем безопасный прокси-метод, который создаёт временный message-объект
    try:
        await on_text_with_text(update, context, transcript)
    except Exception as e:
        log.exception("Voice->text handler error: %s", e)
        await msg.reply_text("Упс, произошла ошибка. Я уже разбираюсь.")
        
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
        from pdfminer_high_level import extract_text as pdfminer_extract_text  # may not exist
    except Exception:
        pdfminer_extract_text = None  # type: ignore
    if pdfminer_extract_text:
        try:
            return (pdfminer_extract_text(BytesIO(data)) or "").strip()
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
            if item.get_type() == 9:  # DOCUMENT
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
    # ничего не бросаем наружу

# ───────── OpenAI Images (генерация картинок) ─────────
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

async def _luma_generate_image_bytes(prompt: str) -> bytes | None:
    if not LUMA_IMG_BASE_URL or not LUMA_API_KEY:
        # фолбэк: OpenAI Images
        try:
            resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
            return base64.b64decode(resp.data[0].b64_json)
        except Exception as e:
            log.exception("OpenAI images fallback error: %s", e)
            return None
    try:
        # Примерный эндпоинт; если у тебя другой — замени path/поля под свой аккаунт.
        url = f"{LUMA_IMG_BASE_URL}/v1/images"
        headers = {"Authorization": f"Bearer {LUMA_API_KEY}", "Accept": "application/json"}
        payload = {"model": LUMA_IMG_MODEL, "prompt": prompt, "size": "1024x1024"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                return None
            j = r.json() or {}
            b64 = (j.get("data") or [{}])[0].get("b64_json") or j.get("image_base64")
            return base64.b64decode(b64) if b64 else None
    except Exception as e:
        log.exception("Luma image gen error: %s", e)
        return None

async def _start_luma_img(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    async def _go():
        img = await _luma_generate_image_bytes(prompt)
        if not img:
            await update.effective_message.reply_text("Не удалось создать изображение.")
            return
        await update.effective_message.reply_photo(photo=img, caption=f"🖌 Готово ✅\nЗапрос: {prompt}")
    await _try_pay_then_do(update, context, update.effective_user.id, "img", IMG_COST_USD, _go,
                           remember_kind="luma_img", remember_payload={"prompt": prompt})


# ───────── UI / тексты ─────────
START_TEXT = (
    "Привет! Я Нейро-Bot — ⚡️ мультирежимный бот из 7 нейросетей для 🎓 учёбы, 💼 работы и 🔥 развлечений.\n"
    "Я умею работать гибридно: могу сам выбрать лучший движок под задачу или дать тебе выбрать вручную. 🤝🧠\n"
    "\n"
    "✨ Главные режимы:\n"
    "\n"
    "\n"
    "• 🎓 Учёба — объяснения с примерами, пошаговые решения задач, эссе/реферат/доклад, мини-квизы.\n"
    "📚 Также: разбор учебных PDF/электронных книг, шпаргалки и конспекты, конструктор тестов;\n"
    "🎧 тайм-коды по аудиокнигам/лекциям и краткие выжимки. 🧩\n"
    "\n"
    "• 💼 Работа — письма/брифы/документы, аналитика и резюме материалов, ToDo/планы, генератор идей.\n"
    "🛠️ Для архитектора/дизайнера/проектировщика: структурирование ТЗ, чек-листы стадий,\n"
    "🗂️ названия/описания листов, сводные таблицы из текстов, оформление пояснительных записок. 📊\n"
    "\n"
    "• 🔥 Развлечения — фото-мастерская (удаление/замена фона, дорисовка, outpaint), оживление старых фото,\n"
    "🎬 видео по тексту/голосу, идеи и форматы для Reels/Shorts, авто-нарезка из длинных видео\n"
    "(сценарий/тайм-коды), мемы/квизы. 🖼️🪄\n"
    "\n"
    "🧭 Как пользоваться:\n"
    "просто выбери режим кнопкой ниже или напиши запрос — я сам определю задачу и предложу варианты. ✍️✨\n"
    "\n"
    "🧠 Кнопка «Движки»:\n"
    "для точного выбора, какую нейросеть использовать принудительно. 🎯🤖"
)

def engines_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 GPT (текст/фото/документы)", callback_data="engine:gpt")],
        [InlineKeyboardButton("🖼 Images (OpenAI)",             callback_data="engine:images")],
        [InlineKeyboardButton("🎞 Kling — клипы / шорты",      callback_data="engine:kling")],  # NEW
        [InlineKeyboardButton("🎬 Luma — короткие видео",       callback_data="engine:luma")],
        [InlineKeyboardButton("🎥 Runway — премиум-видео",      callback_data="engine:runway")],
        [InlineKeyboardButton("🎨 Midjourney (изображения)",    callback_data="engine:midjourney")],
        [InlineKeyboardButton("🗣 STT/TTS — речь↔текст",        callback_data="engine:stt_tts")],
    ])
# ───────── MODES (Учёба / Работа / Развлечения) ─────────

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackQueryHandler, MessageHandler, filters

# Текст корневого меню режимов
def _modes_root_text() -> str:
    return (
        "Выберите режим работы. В каждом режиме бот использует гибрид движков:\n"
        "• GPT-5 (текст/логика) + Vision (фото) + STT/TTS (голос)\n"
        "• Luma/Runway — видео, Midjourney — изображения\n\n"
        "Можете также просто написать свободный запрос — бот поймёт."
    )

def modes_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎓 Учёба", callback_data="mode:study"),
            InlineKeyboardButton("💼 Работа", callback_data="mode:work"),
            InlineKeyboardButton("🔥 Развлечения", callback_data="mode:fun"),
        ],
    ])

# ── Описание и подменю по режимам
def _mode_desc(key: str) -> str:
    if key == "study":
        return (
            "🎓 *Учёба*\n"
            "Гибрид: GPT-5 для объяснений/конспектов, Vision для фото-задач, "
            "STT/TTS для голосовых, + Midjourney (иллюстрации) и Luma/Runway (учебные ролики).\n\n"
            "Быстрые действия ниже. Можно написать свободный запрос (например: "
            "«сделай конспект из PDF», «объясни интегралы с примерами»)."
        )
    if key == "work":
        return (
            "💼 *Работа*\n"
            "Гибрид: GPT-5 (резюме/письма/аналитика), Vision (таблицы/скрины), "
            "STT/TTS (диктовка/озвучка), + Midjourney (визуалы), Luma/Runway (презентационные ролики).\n\n"
            "Быстрые действия ниже. Можно написать свободный запрос (например: "
            "«адаптируй резюме под вакансию PM», «написать коммерческое предложение»)."
        )
    if key == "fun":
        return (
            "🔥 *Развлечения*\n"
            "Гибрид: GPT-5 (идеи, сценарии), Midjourney (картинки), Luma/Runway (шорты/риелсы), "
            "STT/TTS (озвучка). Всё для быстрых творческих штук.\n\n"
            "Быстрые действия ниже. Можно написать свободный запрос (например: "
            "«сделай сценарий 30-сек шорта про кота-бариста»)."
        )
    return "Режим не найден."

def _mode_kb(key: str) -> InlineKeyboardMarkup:
    if key == "study":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 Конспект из PDF/EPUB/DOCX", callback_data="act:study:pdf_summary")],
            [InlineKeyboardButton("🔍 Объяснение темы",            callback_data="act:study:explain"),
             InlineKeyboardButton("🧮 Решение задач",              callback_data="act:study:tasks")],
            [InlineKeyboardButton("✍️ Эссе/реферат/доклад",       callback_data="act:study:essay"),
             InlineKeyboardButton("📝 План к экзамену",           callback_data="act:study:exam_plan")],
            [
                InlineKeyboardButton("🎬 Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("🎨 Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("🗣 STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("📝 Свободный запрос", callback_data="act:free")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="mode:root")],
        ])

    if key == "work":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Письмо/документ",            callback_data="act:work:doc"),
             InlineKeyboardButton("📊 Аналитика/сводка",           callback_data="act:work:report")],
            [InlineKeyboardButton("🗂 План/ToDo",                  callback_data="act:work:plan"),
             InlineKeyboardButton("💡 Идеи/бриф",                 callback_data="act:work:idea")],
            [
                InlineKeyboardButton("🎬 Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("🎨 Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("🗣 STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("📝 Свободный запрос", callback_data="act:free")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="mode:root")],
        ])

    if key == "fun":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🎭 Идеи для досуга",             callback_data="act:fun:ideas")],
            [InlineKeyboardButton("🎬 Сценарий шорта",              callback_data="act:fun:shorts")],
            [InlineKeyboardButton("🎮 Игры/квиз",                   callback_data="act:fun:games")],
            [
                InlineKeyboardButton("🎬 Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("🎨 Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("🗣 STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("📝 Свободный запрос", callback_data="act:free")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="mode:root")],
        ])

    return modes_root_kb()

# Показать выбранный режим (используется и для callback, и для текста)
async def _send_mode_menu(update, context, key: str):
    text = _mode_desc(key)
    kb = _mode_kb(key)
    # Если пришли из callback — редактируем; если текстом — шлём новым сообщением
    if getattr(update, "callback_query", None):
        q = update.callback_query
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        await q.answer()
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# Обработчик callback по режимам
async def on_mode_cb(update, context):
    q = update.callback_query
    data = (q.data or "").strip()
    uid = q.from_user.id

    # Навигация
    if data == "mode:root":
        await q.edit_message_text(_modes_root_text(), reply_markup=modes_root_kb())
        await q.answer(); return

    if data.startswith("mode:"):
        _, key = data.split(":", 1)
        await _send_mode_menu(update, context, key)
        return

    # Свободный ввод из подменю
    if data == "act:free":
        await q.answer()
        await q.edit_message_text(
            "📝 Напишите свободный запрос ниже текстом или голосом — я подстроюсь.",
            reply_markup=modes_root_kb(),
        )
        return

    # === Учёба
    if data == "act:study:pdf_summary":
        await q.answer()
        _mode_track_set(uid, "pdf_summary")
        await q.edit_message_text(
            "📚 Пришлите PDF/EPUB/DOCX/FB2/TXT — сделаю структурированный конспект.\n"
            "Можно в подписи указать цель (коротко/подробно, язык и т.п.).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:explain":
        await q.answer()
        study_sub_set(uid, "explain")
        _mode_track_set(uid, "explain")
        await q.edit_message_text(
            "🔍 Напишите тему + уровень (школа/вуз/профи). Будет объяснение с примерами.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:tasks":
        await q.answer()
        study_sub_set(uid, "tasks")
        _mode_track_set(uid, "tasks")
        await q.edit_message_text(
            "🧮 Пришлите условие(я) — решу пошагово (формулы, пояснения, итог).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:essay":
        await q.answer()
        study_sub_set(uid, "essay")
        _mode_track_set(uid, "essay")
        await q.edit_message_text(
            "✍️ Тема + требования (объём/стиль/язык) — подготовлю эссе/реферат.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:exam_plan":
        await q.answer()
        study_sub_set(uid, "quiz")
        _mode_track_set(uid, "exam_plan")
        await q.edit_message_text(
            "📝 Укажите предмет и дату экзамена — составлю план подготовки с вехами.",
            reply_markup=_mode_kb("study"),
        )
        return

    # === Работа
    if data == "act:work:doc":
        await q.answer()
        _mode_track_set(uid, "work_doc")
        await q.edit_message_text(
            "📄 Что за документ/адресат/контекст? Сформирую черновик письма/документа.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:report":
        await q.answer()
        _mode_track_set(uid, "work_report")
        await q.edit_message_text(
            "📊 Пришлите текст/файл/ссылку — сделаю аналитическую выжимку.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:plan":
        await q.answer()
        _mode_track_set(uid, "work_plan")
        await q.edit_message_text(
            "🗂 Опишите задачу/сроки — соберу ToDo/план со сроками и приоритетами.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:idea":
        await q.answer()
        _mode_track_set(uid, "work_idea")
        await q.edit_message_text(
            "💡 Расскажите продукт/ЦА/каналы — подготовлю бриф/идеи.",
            reply_markup=_mode_kb("work"),
        )
        return

    # === Развлечения (как было)
    if data == "act:fun:ideas":
        await q.answer()
        await q.edit_message_text(
            "🔥 Выберем формат: дом/улица/город/в поездке. Напишите бюджет/настроение.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:shorts":
        await q.answer()
        await q.edit_message_text(
            "🎬 Тема, длительность (15–30 сек), стиль — сделаю сценарий шорта + подсказки для озвучки.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:games":
        await q.answer()
        await q.edit_message_text(
            "🎮 Тематика квиза/игры? Сгенерирую быструю викторину или мини-игру в чате.",
            reply_markup=_mode_kb("fun"),
        )
        return

    # === Модули (как было)
    if data == "act:open:runway":
        await q.answer()
        await q.edit_message_text(
            "🎬 Модуль Runway: пришлите идею/референс — подготовлю промпт и бюджет.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:mj":
        await q.answer()
        await q.edit_message_text(
            "🎨 Модуль Midjourney: опишите картинку — предложу 3 промпта и сетку стилей.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:voice":
        await q.answer()
        await q.edit_message_text(
            "🗣 Голос: /voice_on — озвучка ответов, /voice_off — выключить. "
            "Можете прислать голосовое — распознаю и отвечу.",
            reply_markup=modes_root_kb(),
        )
        return

    await q.answer()

# Fallback — если пользователь нажмёт «Учёба/Работа/Развлечения» обычной кнопкой/текстом
async def on_mode_text(update, context):
    text = (update.effective_message.text or "").strip().lower()
    mapping = {
        "учёба": "study", "учеба": "study",
        "работа": "work",
        "развлечения": "fun", "развлечение": "fun",
    }
    key = mapping.get(text)
    if key:
        await _send_mode_menu(update, context, key)
        
def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎓 Учёба"), KeyboardButton("💼 Работа"), KeyboardButton("🔥 Развлечения")],
            [KeyboardButton("🧠 Движки"), KeyboardButton("⭐ Подписка · Помощь"), KeyboardButton("🧾 Баланс")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
        input_field_placeholder="Выберите режим или напишите запрос…",
    )

main_kb = main_keyboard()

# ───────── /start ─────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point. First-time users must choose language."""
    uid = update.effective_user.id

    # Force language selection before any other UX.
    if not has_lang(uid):
        await update.effective_message.reply_text(
            t(uid, "choose_lang"),
            reply_markup=_lang_choose_kb(),
        )
        return

    # Existing welcome/menu
    try:
        await update.effective_message.reply_text(
            _tr(uid, "welcome"),
            reply_markup=main_kb,
        )
    except Exception:
        await update.effective_message.reply_text(START_TEXT, reply_markup=main_kb)

async def cmd_mode_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _mode_set(update.effective_user.id, "Работа")
    _mode_track_set(update.effective_user.id, "")
    # показываем НОВОЕ подменю «Работа»
    await _send_mode_menu(update, context, "work")

async def cmd_mode_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _mode_set(update.effective_user.id, "Развлечения")
    _mode_track_set(update.effective_user.id, "")
    await update.effective_message.reply_text(
        "🔥 Развлечения — быстрые действия:",
        reply_markup=_fun_quick_kb()
    )

    # НОВАЯ КНОПКА: Kling
    if data == "fun:kling":
        return await q.edit_message_text(
            "🎞 Kling — быстрые клипы и шорты\n\n"
            "Пришли тему, длительность (обычно 5–10 секунд) и формат (например, 9:16). "
            "Я подготовлю сценарий и запущу генерацию клипа в Kling."
        )

# ───────── Старт / Движки / Помощь ─────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_url = kv_get("welcome_url", BANNER_URL)
    if welcome_url:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_photo(welcome_url)
    await update.effective_message.reply_text(START_TEXT, reply_markup=main_kb, disable_web_page_preview=True)

async def cmd_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Выберите движок:", reply_markup=engines_kb())

async def cmd_subs_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Открыть тарифы (WebApp)", web_app=WebAppInfo(url=TARIFF_URL))],
        [InlineKeyboardButton("Оформить PRO на месяц (ЮKassa)", callback_data="buyinv:pro:1")],
    ])
    await update.effective_message.reply_text("⭐ Тарифы и помощь.\n\n" + HELP_TEXT, reply_markup=kb, disable_web_page_preview=True)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, disable_web_page_preview=True)

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(EXAMPLES_TEXT, disable_web_page_preview=True)


# ───────── Диагностика/лимиты ─────────
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


# ───────── Capability Q&A ─────────
_CAP_PDF   = re.compile(r"(pdf|документ(ы)?|файл(ы)?)", re.I)
_CAP_EBOOK = re.compile(r"(ebook|e-?book|электронн(ая|ые)\s+книг|epub|fb2|docx|txt|mobi|azw)", re.I)
_CAP_AUDIO = re.compile(r"(аудио ?книг|audiobook|audio ?book|mp3|m4a|wav|ogg|webm|voice)", re.I)
_CAP_IMAGE = re.compile(r"(изображен|картинк|фото|image|picture|img)", re.I)
_CAP_VIDEO = re.compile(r"(видео|ролик|shorts?|reels?|clip)", re.I)

def capability_answer(text: str) -> str | None:
    """
    Короткие ответы на вопросы вида:
    - «ты можешь анализировать PDF?»
    - «ты умеешь работать с электронными книгами?»
    - «ты можешь создавать видео?»
    - «ты можешь оживить фотографию?» и т.п.

    Важно: не перехватываем реальные команды
    «сделай видео…», «сгенерируй картинку…» и т.д.
    """

    tl = (text or "").strip().lower()
    if not tl:
        return None

    # --- Оживление старых фото / анимация снимков (ВЫСОКИЙ ПРИОРИТЕТ) ---
    if (
        any(k in tl for k in ("оживи", "оживить", "анимируй", "анимировать"))
        and any(k in tl for k in ("фото", "фотограф", "картин", "изображен", "портрет"))
    ):
        # Персонализированный ответ именно под функцию оживления
        return (
            "🪄 Я умею оживлять фотографии и делать из них короткие анимации.\n\n"
            "Что можно оживить:\n"
            "• лёгкая мимика: моргание глаз, мягкая улыбка;\n"
            "• плавные движения головы и плеч, эффект дыхания;\n"
            "• лёгкое движение или параллакс фона.\n\n"
            "Доступные движки:\n"
            "• Runway — максимально реалистичное премиум-движение;\n"
            "• Kling — отлично передаёт взгляд, мимику и повороты головы;\n"
            "• Luma — плавные художественные анимации.\n\n"
            "Пришли сюда фото (лучше портрет). После загрузки я предложу выбрать движок "
            "и подготовлю превью/видео."
        )

    # --- Документы / файлы ---
    if re.search(r"\b(pdf|docx|epub|fb2|txt|mobi|azw)\b", tl) and "?" in tl:
        return (
            "Да, могу помочь с анализом документов и электронных книг. "
            "Отправь файл (PDF, EPUB, DOCX, FB2, TXT, MOBI/AZW — по возможности) "
            "и напиши, что нужно: конспект, выжимку, план, разбор по пунктам и т.п."
        )

    # --- Аудио / речь ---
    if ("аудио" in tl or "голосов" in tl or "voice" in tl or "speech" in tl) and (
        "?" in tl or "можешь" in tl or "умеешь" in tl
    ):
        return (
            "Да, могу распознавать речь из голосовых и аудио. "
            "Просто пришли голосовое сообщение — я переведу его в текст и отвечу как на обычный запрос."
        )

    # --- Видео (общие возможности, не команды) ---
    if (
        re.search(r"\bвидео\b", tl)
        and "?" in tl
        and re.search(r"\b(мож(ешь|ете)|уме(ешь|ете)|способен)\b", tl)
    ):
        return (
            "Да, могу запускать генерацию коротких видео. "
            "Можно сделать ролик по текстовому описанию или оживить фото. "
            "После того как ты пришлёшь запрос и/или файл, я предложу выбрать движок "
            "(Runway, Kling, Luma — в зависимости от доступных)."
        )

    # --- Картинки / изображения (без /img и генерации по промпту) ---
    if (
        re.search(r"(картинк|изображен|фото|picture|логотип|баннер)", tl)
        and "?" in tl
    ):
        return (
            "Да, могу работать с изображениями: анализ, улучшение качества, удаление или замена фона, "
            "расширение кадра, простая анимация. "
            "Просто пришли сюда фото и коротко опиши, что нужно сделать."
        )

    # Ничего подходящего — пусть обрабатывается основной логикой
    return None

# ───────── Моды/движки для study ─────────
def _uk(user_id: int, name: str) -> str: return f"user:{user_id}:{name}"
def mode_set(user_id: int, mode: str):     kv_set(_uk(user_id, "mode"), (mode or "default"))
def mode_get(user_id: int) -> str:         return kv_get(_uk(user_id, "mode"), "default") or "default"
def engine_set(user_id: int, engine: str): kv_set(_uk(user_id, "engine"), (engine or "gpt"))
def engine_get(user_id: int) -> str:       return kv_get(_uk(user_id, "engine"), "gpt") or "gpt"
def study_sub_set(user_id: int, sub: str): kv_set(_uk(user_id, "study_sub"), (sub or "explain"))
def study_sub_get(user_id: int) -> str:    return kv_get(_uk(user_id, "study_sub"), "explain") or "explain"

def modes_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎓 Учёба", callback_data="mode:set:study"),
         InlineKeyboardButton("🖼 Фото",  callback_data="mode:set:photo")],
        [InlineKeyboardButton("📄 Документы", callback_data="mode:set:docs"),
         InlineKeyboardButton("🎙 Голос",     callback_data="mode:set:voice")],
        [InlineKeyboardButton("🧠 Движки", callback_data="mode:engines")]
    ])

def study_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Объяснение",          callback_data="study:set:explain"),
         InlineKeyboardButton("🧮 Задачи",              callback_data="study:set:tasks")],
        [InlineKeyboardButton("✍️ Эссе/реферат/доклад", callback_data="study:set:essay")],
        [InlineKeyboardButton("📝 Экзамен/квиз",        callback_data="study:set:quiz")]
    ])

async def study_process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    sub = study_sub_get(update.effective_user.id)
    if sub == "explain":
        prompt = f"Объясни простыми словами, с 2–3 примерами и мини-итогом:\n\n{text}"
    elif sub == "tasks":
        prompt = ("Реши задачу(и) пошагово: формулы, пояснения, итоговый ответ. "
                  "Если не хватает данных — уточняющие вопросы в конце.\n\n" + text)
    elif sub == "essay":
        prompt = ("Напиши структурированный текст 400–600 слов (эссе/реферат/доклад): "
                  "введение, 3–5 тезисов с фактами, вывод, список из 3 источников (если уместно).\n\nТема:\n" + text)
    elif sub == "quiz":
        prompt = ("Составь мини-квиз по теме: 10 вопросов, у каждого 4 варианта A–D; "
                  "в конце дай ключ ответов (номер→буква). Тема:\n\n" + text)
    else:
        prompt = text
    ans = await ask_openai_text(prompt)
    await update.effective_message.reply_text(ans)
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])


# ───────── Кнопка приветственной картинки ─────────
async def cmd_set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("Команда доступна только владельцу.")
        return
    if not context.args:
        await update.effective_message.reply_text("Формат: /set_welcome <url_картинки>")
        return
    url = " ".join(context.args).strip()
    kv_set("welcome_url", url)
    await update.effective_message.reply_text("Картинка приветствия обновлена. Отправьте /start для проверки.")

async def cmd_show_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = kv_get("welcome_url", BANNER_URL)
    if url:
        await update.effective_message.reply_photo(url, caption="Текущая картинка приветствия")
    else:
        await update.effective_message.reply_text("Картинка приветствия не задана.")


# ───────── Баланс / пополнение ─────────
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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]])
    await update.effective_message.reply_text(msg, reply_markup=kb)

# ───────── Подписка / тарифы — UI и оплаты (PATCH) ─────────
# Зависимости окружения:
#  - YOOKASSA_PROVIDER_TOKEN  (платёжный токен Telegram Payments от ЮKassa)
#  - YOOKASSA_CURRENCY        (по умолчанию "RUB")
#  - CRYPTO_PAY_API_TOKEN     (https://pay.crypt.bot — токен продавца)
#  - CRYPTO_ASSET             (например "USDT", по умолчанию "USDT")
#  - PRICE_START_RUB, PRICE_PRO_RUB, PRICE_ULT_RUB  (целое число, ₽)
#  - PRICE_START_USD, PRICE_PRO_USD, PRICE_ULT_USD  (число с точкой, $)
#
# Хранилище подписки и кошелька используется на kv_*:
#   sub:tier:{user_id}   -> "start" | "pro" | "ultimate"
#   sub:until:{user_id}  -> ISO-строка даты окончания
#   wallet:usd:{user_id} -> баланс в USD (float)

YOOKASSA_PROVIDER_TOKEN = os.environ.get("YOOKASSA_PROVIDER_TOKEN", "").strip()
YOOKASSA_CURRENCY = (os.environ.get("YOOKASSA_CURRENCY") or "RUB").upper()

CRYPTO_PAY_API_TOKEN = os.environ.get("CRYPTO_PAY_API_TOKEN", "").strip()
CRYPTO_ASSET = (os.environ.get("CRYPTO_ASSET") or "USDT").upper()

# === COMPAT with existing vars/DB in your main.py ===
# 1) ЮKassa: если уже есть PROVIDER_TOKEN (из PROVIDER_TOKEN_YOOKASSA), используем его:
if not YOOKASSA_PROVIDER_TOKEN and 'PROVIDER_TOKEN' in globals() and PROVIDER_TOKEN:
    YOOKASSA_PROVIDER_TOKEN = PROVIDER_TOKEN

# 2) Кошелёк: используем твой единый USD-кошелёк (wallet table) вместо kv:
def _user_balance_get(user_id: int) -> float:
    return _wallet_total_get(user_id)

def _user_balance_add(user_id: int, delta: float) -> float:
    if delta > 0:
        _wallet_total_add(user_id, delta)
    elif delta < 0:
        _wallet_total_take(user_id, -delta)
    return _wallet_total_get(user_id)

def _user_balance_debit(user_id: int, amount: float) -> bool:
    return _wallet_total_take(user_id, amount)

# 3) Подписка: активируем через твои функции с БД, а не kv:
def _sub_activate(user_id: int, tier_key: str, months: int = 1) -> str:
    dt = activate_subscription_with_tier(user_id, tier_key, months)
    return dt.isoformat()

def _sub_info_text(user_id: int) -> str:
    tier = get_subscription_tier(user_id)
    dt = get_subscription_until(user_id)
    human_until = dt.strftime("%d.%m.%Y") if dt else ""
    bal = _user_balance_get(user_id)
    line_until = f"\n⏳ Активна до: {human_until}" if tier != "free" and human_until else ""
    return f"🧾 Текущая подписка: {tier.upper() if tier!='free' else 'нет'}{line_until}\n💵 Баланс: ${bal:.2f}"

# Цены — из env с осмысленными дефолтами
PRICE_START_RUB = int(os.environ.get("PRICE_START_RUB", "499"))
PRICE_PRO_RUB = int(os.environ.get("PRICE_PRO_RUB", "1299"))
PRICE_ULT_RUB = int(os.environ.get("PRICE_ULT_RUB", "2990"))

PRICE_START_USD = _env_float("PRICE_START_USD", 4.99)
PRICE_PRO_USD   = _env_float("PRICE_PRO_USD", 12.99)
PRICE_ULT_USD   = _env_float("PRICE_ULT_USD", 29.90)

SUBS_TIERS = {
    "start": {
        "title": "START",
        "rub": PRICE_START_RUB,
        "usd": PRICE_START_USD,
        "features": [
            "💬 GPT-чат и документы (базовые лимиты)",
            "🖼 Фото-мастерская: фон, лёгкая дорисовка",
            "🎧 Озвучка ответов (TTS)",
        ],
    },
    "pro": {
        "title": "PRO",
        "rub": PRICE_PRO_RUB,
        "usd": PRICE_PRO_USD,
        "features": [
            "📚 Глубокий разбор PDF/DOCX/EPUB",
            "🎬 Reels/Shorts по смыслу, видео из фото",
            "🖼 Outpaint и «оживление» старых фото",
        ],
    },
    "ultimate": {
        "title": "ULTIMATE",
        "rub": PRICE_ULT_RUB,
        "usd": PRICE_ULT_USD,
        "features": [
            "🚀 Runway/Luma — премиум-рендеры",
            "🧠 Расширенные лимиты и приоритетная очередь",
            "🛠 PRO-инструменты (архитектура/дизайн)",
        ],
    },
}

def _money_fmt_rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₽"

def _money_fmt_usd(v: float) -> str:
    return f"${v:.2f}"

def _user_balance_get(user_id: int) -> float:
    # Пытаемся взять из твоего кошелька, если есть, иначе — kv
    get_fn = _pick_first_defined("wallet_get_balance", "get_balance", "balance_get")
    if get_fn:
        try:
            return float(get_fn(user_id))
        except Exception:
            pass
    try:
        return float(kv_get(f"wallet:usd:{user_id}", "0") or 0)
    except Exception:
        return 0.0

def _user_balance_add(user_id: int, delta: float) -> float:
    set_fn = _pick_first_defined("wallet_change_balance", "wallet_add_delta")
    if set_fn:
        try:
            return float(set_fn(user_id, delta))
        except Exception:
            pass
    cur = _user_balance_get(user_id)
    newv = round(cur + float(delta), 4)
    kv_set(f"wallet:usd:{user_id}", str(newv))
    return newv

def _user_balance_debit(user_id: int, amount: float) -> bool:
    if amount <= 0:
        return True
    bal = _user_balance_get(user_id)
    if bal + 1e-9 < amount:
        return False
    _user_balance_add(user_id, -amount)
    return True

def _sub_activate(user_id: int, tier_key: str, months: int = 1) -> str:
    until = (datetime.now(timezone.utc) + timedelta(days=30 * months)).isoformat()
    kv_set(f"sub:tier:{user_id}", tier_key)
    kv_set(f"sub:until:{user_id}", until)
    return until

def _sub_info_text(user_id: int) -> str:
    tier = kv_get(f"sub:tier:{user_id}", "") or "нет"
    until = kv_get(f"sub:until:{user_id}", "")
    human_until = ""
    if until:
        try:
            d = datetime.fromisoformat(until)
            human_until = d.strftime("%d.%m.%Y")
        except Exception:
            human_until = until
    bal = _user_balance_get(user_id)
    line_until = f"\n⏳ Активна до: {human_until}" if tier != "нет" and human_until else ""
    return f"🧾 Текущая подписка: {tier.upper() if tier!='нет' else 'нет'}{line_until}\n💵 Баланс: {_money_fmt_usd(bal)}"

def _plan_card_text(key: str) -> str:
    p = SUBS_TIERS[key]
    fs = "\n".join("• " + f for f in p["features"])
    return (
        f"⭐ Тариф {p['title']}\n"
        f"Цена: {_money_fmt_rub(p['rub'])} / {_money_fmt_usd(p['usd'])} в мес.\n\n"
        f"{fs}\n"
    )

def _plans_overview_text(user_id: int) -> str:
    parts = [
        "⭐ Подписка и тарифы",
        "Выбери подходящий уровень — доступ откроется сразу после оплаты.",
        _sub_info_text(user_id),
        "— — —",
        _plan_card_text("start"),
        _plan_card_text("pro"),
        _plan_card_text("ultimate"),
        "Выберите тариф кнопкой ниже.",
    ]
    return "\n".join(parts)

def plans_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⭐ START",    callback_data="plan:start"),
            InlineKeyboardButton("🚀 PRO",      callback_data="plan:pro"),
            InlineKeyboardButton("👑 ULTIMATE", callback_data="plan:ultimate"),
        ]
    ])

def plan_pay_kb(plan_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💳 Оплатить — ЮKassa", callback_data=f"pay:yookassa:{plan_key}"),
        ],
        [
            InlineKeyboardButton("💠 Оплатить — CryptoBot", callback_data=f"pay:cryptobot:{plan_key}"),
        ],
        [
            InlineKeyboardButton("🧾 Списать с баланса", callback_data=f"pay:balance:{plan_key}"),
        ],
        [
            InlineKeyboardButton("⬅️ К тарифам", callback_data="plan:root"),
        ]
    ])

# Кнопка «⭐ Подписка · Помощь»
async def on_btn_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = _plans_overview_text(user_id)
    await update.effective_chat.send_message(text, reply_markup=plans_root_kb())

# Обработчик наших колбэков по подписке/оплатам (зарегистрировать ДО общего on_cb!)
async def on_cb_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    user_id = q.from_user.id
    chat_id = q.message.chat.id  # FIX: корректное поле в PTB v21+

    # Навигация между тарифами
    if data.startswith("plan:"):
        _, arg = data.split(":", 1)
        if arg == "root":
            await q.edit_message_text(_plans_overview_text(user_id), reply_markup=plans_root_kb())
            await q.answer()
            return
        if arg in SUBS_TIERS:
            await q.edit_message_text(
                _plan_card_text(arg) + "\nВыберите способ оплаты:",
                reply_markup=plan_pay_kb(arg)
            )
            await q.answer()
            return

    # Платежи
    if data.startswith("pay:"):
        # безопасный парсинг
        try:
            _, method, plan_key = data.split(":", 2)
        except ValueError:
            await q.answer("Некорректные данные кнопки.", show_alert=True)
            return

        plan = SUBS_TIERS.get(plan_key)
        if not plan:
            await q.answer("Неизвестный тариф.", show_alert=True)
            return

        # ЮKassa через Telegram Payments
        if method == "yookassa":
            if not YOOKASSA_PROVIDER_TOKEN:
                await q.answer("ЮKassa не подключена (нет YOOKASSA_PROVIDER_TOKEN).", show_alert=True)
                return

            title = f"Подписка {plan['title']} • 1 месяц"
            desc = "Доступ к функциям бота согласно выбранному тарифу. Подписка активируется сразу после оплаты."
            payload = json.dumps({"tier": plan_key, "months": 1})

            # Telegram ожидает сумму в минорных единицах (копейки/центы)
            if YOOKASSA_CURRENCY == "RUB":
                total_minor = int(round(float(plan["rub"]) * 100))
            else:
                total_minor = int(round(float(plan["usd"]) * 100))

            prices = [LabeledPrice(label=f"{plan['title']} 1 мес.", amount=total_minor)]
            await context.bot.send_invoice(
                chat_id=chat_id,
                title=title,
                description=desc,
                payload=payload,
                provider_token=YOOKASSA_PROVIDER_TOKEN,
                currency=YOOKASSA_CURRENCY,
                prices=prices,
                need_email=True,
                is_flexible=False,
            )
            await q.answer("Счёт выставлен ✅")
            return

        # CryptoBot (Crypto Pay API: создаём инвойс и отдаём ссылку)
        if method == "cryptobot":  # FIX: выровнен отступ
            if not CRYPTO_PAY_API_TOKEN:
                await q.answer("CryptoBot не подключён (нет CRYPTO_PAY_API_TOKEN).", show_alert=True)
                return
            try:
                amount = float(plan["usd"])
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post(
                        "https://pay.crypt.bot/api/createInvoice",
                        headers={"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN},
                        json={
                            "asset": CRYPTO_ASSET,
                            "amount": f"{amount:.2f}",
                            "description": f"Subscription {plan['title']} • 1 month",
                            "allow_comments": False,
                            "allow_anonymous": True,
                        },
                    )
                    data = r.json()
                    if not data.get("ok"):
                        raise RuntimeError(str(data))
                    res = data["result"]
                    pay_url = res["pay_url"]
                    inv_id = str(res["invoice_id"])

                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💠 Оплатить в CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("⬅️ К тарифу", callback_data=f"plan:{plan_key}")],
                ])
                msg = await q.edit_message_text(
                    _plan_card_text(plan_key) + "\nОткройте ссылку для оплаты:",
                    reply_markup=kb
                )
                # автопул статуса именно для ПОДПИСКИ
                context.application.create_task(_poll_crypto_sub_invoice(
                    context, msg.chat.id, msg.message_id, user_id, inv_id, plan_key, 1  # FIX: msg.chat.id
                ))
                await q.answer()
            except Exception as e:
                await q.answer("Не удалось создать счёт в CryptoBot.", show_alert=True)
                log.exception("CryptoBot invoice error: %s", e)
            return

        # Списание с внутреннего баланса (USD)
        if method == "balance":
            price_usd = float(plan["usd"])
            if not _user_balance_debit(user_id, price_usd):
                await q.answer("Недостаточно средств на внутреннем балансе.", show_alert=True)
                return
            until = _sub_activate(user_id, plan_key, months=1)
            await q.edit_message_text(
                f"✅ Подписка {plan['title']} активирована до {until[:10]}.\n"
                f"💵 Списано: {_money_fmt_usd(price_usd)}. "
                f"Текущий баланс: {_money_fmt_usd(_user_balance_get(user_id))}",
                reply_markup=plans_root_kb(),
            )
            await q.answer()
            return

    # Если колбэк не наш — пропускаем дальше
    await q.answer()
    return


# Если у тебя уже есть on_precheckout / on_successful_payment — оставь их.
# Если нет, можешь использовать эти простые реализации:

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.pre_checkout_query.answer(ok=True)
    except Exception as e:
        log.exception("precheckout error: %s", e)

async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Универсальный обработчик Telegram Payments:
    - Поддерживает payload в двух форматах:
        1) JSON: {"tier":"pro","months":1}
        2) Строка: "sub:pro:1"
    - Иначе трактует как пополнение единого USD-кошелька.
    """
    try:
        sp = update.message.successful_payment
        payload_raw = sp.invoice_payload or ""
        total_minor = sp.total_amount or 0
        rub = total_minor / 100.0
        uid = update.effective_user.id

        # 1) Пытаемся распарсить JSON
        tier, months = None, None
        try:
            if payload_raw.strip().startswith("{"):
                obj = json.loads(payload_raw)
                tier = (obj.get("tier") or "").strip().lower() or None
                months = int(obj.get("months") or 1)
        except Exception:
            pass

        # 2) Пытаемся распарсить строковый формат "sub:tier:months"
        if not tier and payload_raw.startswith("sub:"):
            try:
                _, t, m = payload_raw.split(":", 2)
                tier = (t or "pro").strip().lower()
                months = int(m or 1)
            except Exception:
                tier, months = None, None

        if tier and months:
            until = activate_subscription_with_tier(uid, tier, months)
            await update.effective_message.reply_text(
                f"🎉 Оплата прошла успешно!\n"
                f"✅ Подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')}."
            )
            return

        # Иначе считаем, что это пополнение кошелька в рублях
        usd = rub / max(1e-9, USD_RUB)
        _wallet_total_add(uid, usd)
        await update.effective_message.reply_text(
            f"💳 Пополнение: {rub:.0f} ₽ ≈ ${usd:.2f} зачислено на единый баланс."
        )

    except Exception as e:
        log.exception("successful_payment handler error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("⚠️ Ошибка обработки платежа. Если деньги списались — напишите в поддержку.")
# ───────── Конец PATCH ─────────
        
# ───────── Команда /img ─────────
async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip() if context.args else ""
    if not prompt:
        await update.effective_message.reply_text("Формат: /img <описание>")
        return

    async def _go():
        await _do_img_generate(update, context, prompt)

    user_id = update.effective_user.id
    await _try_pay_then_do(
        update, context, user_id,
        "img", IMG_COST_USD, _go,
        remember_kind="img_generate", remember_payload={"prompt": prompt}
    )


# ───────── Photo quick actions ─────────
def photo_quick_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Оживить фото", callback_data="pedit:revive")],
        [InlineKeyboardButton("🧼 Удалить фон",  callback_data="pedit:removebg"),
         InlineKeyboardButton("🖼 Заменить фон", callback_data="pedit:replacebg")],
        [InlineKeyboardButton("🧭 Расширить кадр (outpaint)", callback_data="pedit:outpaint"),
         InlineKeyboardButton("📽 Раскадровка", callback_data="pedit:story")],
        [InlineKeyboardButton("🖌 Картинка по описанию (Luma)", callback_data="pedit:lumaimg")],
        [InlineKeyboardButton("👁 Анализ фото", callback_data="pedit:vision")],
    ])


def revive_engine_kb() -> InlineKeyboardMarkup:
    """
    Кнопки выбора движка для оживления фото.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Runway", callback_data="revive_engine:runway")],
        [InlineKeyboardButton("Kling",  callback_data="revive_engine:kling")],
        [InlineKeyboardButton("Luma",   callback_data="revive_engine:luma")],
    ])
_photo_cache = {}  # user_id -> bytes

def _cache_photo(user_id: int, data: bytes):
    try:
        _photo_cache[user_id] = data
    except Exception:
        pass

def _get_cached_photo(user_id: int) -> bytes | None:
    return _photo_cache.get(user_id)

async def _pedit_removebg(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    if rembg_remove is None:
        await update.effective_message.reply_text("rembg не установлен. Установите rembg/onnxruntime.")
        return
    try:
        out = rembg_remove(img_bytes)
        bio = BytesIO(out); bio.name = "no_bg.png"
        await update.effective_message.reply_document(InputFile(bio), caption="Фон удалён ✅")
    except Exception as e:
        log.exception("removebg error: %s", e)
        await update.effective_message.reply_text("Не удалось удалить фон.")

async def _pedit_replacebg(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    if Image is None:
        await update.effective_message.reply_text("Pillow не установлен.")
        return
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGBA")
        bg = im.convert("RGB").filter(ImageFilter.GaussianBlur(radius=22)) if ImageFilter else im.convert("RGB")
        bio = BytesIO(); bg.save(bio, format="JPEG", quality=92); bio.seek(0); bio.name = "bg_blur.jpg"
        await update.effective_message.reply_photo(InputFile(bio), caption="Заменил фон на размытый вариант.")
    except Exception as e:
        log.exception("replacebg error: %s", e)
        await update.effective_message.reply_text("Не удалось заменить фон.")

async def _pedit_outpaint(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    if Image is None:
        await update.effective_message.reply_text("Pillow не установлен.")
        return
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGB")
        pad = max(64, min(256, max(im.size)//6))
        big = Image.new("RGB", (im.width + 2*pad, im.height + 2*pad))
        bg = im.resize(big.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(radius=24)) if ImageFilter else im.resize(big.size)
        big.paste(bg, (0, 0)); big.paste(im, (pad, pad))
        bio = BytesIO(); big.save(bio, format="JPEG", quality=92); bio.seek(0); bio.name = "outpaint.jpg"
        await update.effective_message.reply_photo(InputFile(bio), caption="Простой outpaint: расширил полотно с мягкими краями.")
    except Exception as e:
        log.exception("outpaint error: %s", e)
        await update.effective_message.reply_text("Не удалось сделать outpaint.")

async def _pedit_storyboard(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    try:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        desc = await ask_openai_vision("Опиши ключевые элементы кадра очень кратко.", b64, sniff_image_mime(img_bytes))
        plan = await ask_openai_text(
            "Сделай раскадровку (6 кадров) под 6–10 секундный клип. "
            "Каждый кадр — 1 строка: кадр/действие/ракурс/свет. Основа:\n" + (desc or "")
        )
        await update.effective_message.reply_text("Раскадровка:\н" + plan)
    except Exception as e:
        log.exception("storyboard error: %s", e)
        await update.effective_message.reply_text("Не удалось построить раскадровку.")


# ───────── WebApp data (тарифы/пополнения) ─────────
async def on_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        wad = update.effective_message.web_app_data
        raw = wad.data if wad else ""
        data = {}
        try:
            data = json.loads(raw)
        except Exception:
            for part in (raw or "").split("&"):
                if "=" in part:
                    k, v = part.split("=", 1); data[k] = v

        typ = (data.get("type") or data.get("action") or "").lower()

        if typ in ("subscribe", "buy", "buy_sub", "sub"):
            tier = (data.get("tier") or "pro").lower()
            months = int(data.get("months") or 1)
            desc = f"Оформление подписки {tier.upper()} на {months} мес."
            await update.effective_message.reply_text(
                f"{desc}\nВыберите способ:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить картой (ЮKassa)", callback_data=f"buyinv:{tier}:{months}")],
                    [InlineKeyboardButton("Списать с баланса (USD)",  callback_data=f"buywallet:{tier}:{months}")],
                ])
            )
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


# ───────── CallbackQuery (всё остальное) ─────────

_pending_actions = {}

def _new_aid() -> str:
    return uuid.uuid4().hex[:12]

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()
    
    # Language selection (lang:<code>)
    if data.startswith("lang:"):
        code = data.split(":", 1)[1].strip()
        set_lang(uid, code)
        await q.answer()
        try:
            await q.message.reply_text(t(uid, "lang_set"), reply_markup=main_kb)
        except Exception:
            pass
        # Show main menu after setting language
        try:
            await cmd_start(update, context)
        except Exception:
            pass
        return

try:
        # 🆕 Выбор движка для оживления фото (Runway/Kling/Luma)
        if data.startswith("revive_engine:"):
            await q.answer()
            engine = data.split(":", 1)[1] if ":" in data else ""
            await revive_old_photo_flow(update, context, engine=engine)
            return

        # Photo edit / анимация по inline-кнопкам pedit:...
        if data.startswith("pedit:"):
            await q.answer()
            action = data.split(":", 1)[1] if ":" in data else ""
            user_id = update.effective_user.id

            # Специальный случай: оживление фото → показать выбор движка
            if action == "revive":
                if user_id not in _LAST_ANIM_PHOTO:
                    await q.edit_message_text(
                        "Не нашёл фото в кэше. Пришли фото ещё раз, пожалуйста."
                    )
                    return

                await q.edit_message_text(
                    "Выбери движок для оживления фото:",
                    reply_markup=revive_engine_kb(),
                )
                return

            # Для остальных pedit:* нужен байтовый образ картинки
            img = _get_cached_photo(user_id)
            if not img:
                await q.edit_message_text(
                    "Не нашёл фото в кэше. Пришли фото ещё раз, пожалуйста."
                )
                return

            if action == "removebg":
                await _pedit_removebg(update, context, img)
                return

            if action == "replacebg":
                await _pedit_replacebg(update, context, img)
                return

            if action == "outpaint":
                await _pedit_outpaint(update, context, img)
                return

            if action == "story":
                await _pedit_storyboard(update, context, img)
                return

            if action == "lumaimg":
                await _start_luma_img(update, context, "")
                return

            # неизвестный pedit:* — просто выходим
            return

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
                await q.edit_message_text(
                    f"Минимальная сумма пополнения {MIN_RUB_FOR_INVOICE} ₽."
                )
                return
            title = "Пополнение баланса (карта)"
            desc = f"Пополнение USD-баланса бота на сумму ≈ {amount_rub} ₽"
            payload = f"topup:{amount_rub}"
            ok = await _send_invoice_rub(title, desc, amount_rub, payload, update)
            if not ok:
                await q.answer("Не удалось выставить счёт", show_alert=True)
            return

        # TOPUP CRYPTO: выбор суммы
        if data == "topup:crypto":
            await q.answer()
            await q.edit_message_text(
                "Пополнение через CryptoBot (USDT):\n\n"
                "Выберите сумму пополнения ($):",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("$5",  callback_data="topup:crypto:5"),
                            InlineKeyboardButton("$10", callback_data="topup:crypto:10"),
                            InlineKeyboardButton("$25", callback_data="topup:crypto:25"),
                        ],
                        [
                            InlineKeyboardButton("$50",  callback_data="topup:crypto:50"),
                            InlineKeyboardButton("$100", callback_data="topup:crypto:100"),
                        ],
                        [InlineKeyboardButton("Отмена", callback_data="topup:cancel")],
                    ]
                ),
            )
            return

        # TOPUP CRYPTO: создание инвойса
        if data.startswith("topup:crypto:"):
            await q.answer()
            try:
                usd = float((data.split(":", 2)[-1] or "0").strip() or "0")
            except Exception:
                usd = 0.0
            if usd <= 0.0:
                await q.edit_message_text("Неверная сумма.")
                return

            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(
                usd, asset="USDT", description="Wallet top-up"
            )
            if not inv_id or not pay_url:
                await q.edit_message_text(
                    "Не удалось создать счёт в CryptoBot. Попробуйте позже."
                )
                return

            msg = await update.effective_message.reply_text(
                f"Оплатите через CryptoBot: ≈ ${usd_amount:.2f} ({asset}).\n"
                "После оплаты баланс пополнится автоматически.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("Оплатить в CryptoBot", url=pay_url)],
                        [InlineKeyboardButton("Проверить оплату", callback_data=f"crypto:check:{inv_id}")],
                    ]
                ),
            )
            # запустим фоновый поллинг инвойса
            context.application.create_task(
                _poll_crypto_invoice(
                    context,
                    msg.chat_id,
                    msg.message_id,
                    update.effective_user.id,
                    inv_id,
                    usd_amount,
                )
            )
            return

        # CryptoBot: ручная проверка инвойса
        if data.startswith("crypto:check:"):
            await q.answer()
            inv_id = data.split(":", 2)[-1]
            inv = await _crypto_get_invoice(inv_id)
            status = (inv or {}).get("status", "").lower() if inv else ""
            paid_amount = (inv or {}).get("amount") or 0
            asset = (inv or {}).get("asset") or "USDT"

            if status == "paid":
                await q.edit_message_text(
                    f"✅ Платёж получен: {paid_amount} {asset}.\n"
                    "Баланс будет пополнен в течение минуты."
                )
            elif status == "active":
                await q.edit_message_text("Счёт ещё не оплачен.")
            else:
                await q.edit_message_text("Счёт не активен или истёк.")
            return

        # TOPUP cancel
        if data == "topup:cancel":
            await q.answer()
            await q.edit_message_text("Пополнение отменено.")
            return

        # Подписка: старое меню /plans (если используешь)
        if data == "plans":
            await q.answer()
            await cmd_plans(update, context)
            return

        # Подписка: выбор тарифа и срока
        if data.startswith("buy:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            desc = f"Подписка {tier.upper()} на {months} мес."
            await q.edit_message_text(
                f"{desc}\nВыберите способ оплаты:",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Оплатить картой (ЮKassa)",
                                callback_data=f"buyinv:{tier}:{months}",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "Списать с баланса (USD)",
                                callback_data=f"buywallet:{tier}:{months}",
                            )
                        ],
                    ]
                ),
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
            payload, amount_rub, title = _plan_payload_and_amount(tier, months)
            usd_price = amount_rub / USD_RUB
            bal = _user_balance_get(update.effective_user.id)
            if bal < usd_price:
                need = usd_price - bal
                await q.edit_message_text(
                    f"На балансе недостаточно средств.\n"
                    f"Требуется ещё ≈ ${need:.2f}.\n\n"
                    "Пополните баланс через меню «🧾 Баланс».",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
                    ),
                )
                return
            # списываем и активируем
            _user_balance_debit(update.effective_user.id, usd_price)
            tier_name = payload.split(":", 1)[-1]
            activate_subscription_with_tier(update.effective_user.id, tier_name, months)
            await q.edit_message_text(
                f"✅ Подписка {tier_name.upper()} на {months} мес. оформлена.\n"
                f"Баланс: ${_user_balance_get(update.effective_user.id):.2f}"
            )
            return

        # Баланс: просто открыть меню
        if data == "balance:open":
            await q.answer()
            await cmd_balance(update, context)
            return

        # Оффер на доп.расход (когда не хватило лимита)
        if data.startswith("offer:"):
            await q.answer()
            _, engine, offer = data.split(":", 2)
            user_id = update.effective_user.id
            limits = _limits_for(user_id)
            grp = ENGINE_BUDGET_GROUP.get(engine, engine)

            try:
                need_usd = float(offer.split(":", 1)[-1])
            except Exception:
                need_usd = 0.0

            amount_rub = _calc_oneoff_price_rub(grp, need_usd or 0.0)
            await q.edit_message_text(
                f"Ваш дневной лимит по «{engine}» исчерпан. Разовая покупка ≈ {amount_rub} ₽ "
                "или пополните баланс в «🧾 Баланс».",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
                        [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")],
                    ]
                ),
            )
            return

        # Режимы / Движки
        if data == "mode:engines":
            await q.answer()
            await q.edit_message_text("Движки:", reply_markup=engines_kb())
            return

        if data.startswith("mode:set:"):
            await q.answer()
            _, _, mode = data.split(":", 2)
            _mode_set(update.effective_user.id, mode)
            if mode == "none":
                await q.edit_message_text("Режим выключен.")
            else:
                await q.edit_message_text(
                    f"Режим «{mode}» включён. Напишите задание."
                )
            return

        # Подтверждение выбора движка для видео (Kling / Luma / Runway)
        if data.startswith("choose:"):
            await q.answer()
            _, engine, aid = data.split(":", 2)
            meta = _pending_actions.pop(aid, None)
            if not meta:
                await q.answer("Задача устарела", show_alert=True)
                return

            prompt   = (meta.get("prompt") or "").strip()
            duration = normalize_seconds(int(meta.get("duration") or LUMA_DURATION_S))
            aspect   = normalize_aspect(str(meta.get("aspect") or "16:9"))

            uid = update.effective_user.id
            tier = get_subscription_tier(uid)

            # Runway для text/voice→video отключён (оставляем только Kling/Luma/Sora)
            if engine == "runway":
                await q.message.reply_text("⚠️ Runway отключён для видео по тексту/голосу. Выберите Kling, Luma или Sora.")
                return

            # Estimate
            if engine == "kling":
                est = float(KLING_UNIT_COST_USD or 0.40) * duration
                map_engine = "kling"
            elif engine == "luma":
                est = float(LUMA_UNIT_COST_USD or 0.40) * duration
                map_engine = "luma"
            elif engine == "sora":
                est = float(SORA_UNIT_COST_USD or 0.40) * duration
                map_engine = "sora"
            else:
                await q.answer("Неизвестный движок", show_alert=True)
                return

            async def _start_real_render():
                ok = False
                if engine == "kling":
                    ok = await _run_kling_video(update, context, prompt, duration, aspect)
                    if ok:
                        _register_engine_spend(uid, "kling", est)
                elif engine == "luma":
                    ok = await _run_luma_video(update, context, prompt, duration, aspect)
                    if ok:
                        _register_engine_spend(uid, "luma", est)
                elif engine == "sora":
                    ok = await _run_sora_video(update, context, prompt, duration, aspect, tier=tier)
                    if ok:
                        _register_engine_spend(uid, "sora", est)

                return ok

            await _try_pay_then_do(
                update,
                context,
                uid,
                map_engine,
                est,
                _start_real_render,
                remember_kind=f"video_{engine}",
                remember_payload={"prompt": prompt, "duration": duration, "aspect": aspect},
            )
            return

        # Если не подошла ни одна ветка
        await q.answer("Неизвестная команда", show_alert=True)

    except Exception as e:
        log.exception("on_cb error: %s", e)
    finally:
        with contextlib.suppress(Exception):
            await q.answer()



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
                text = (dg.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("transcript", "")).strip()
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


# ───────── Диагностика движков ─────────
async def cmd_diag_stt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = []
    lines.append("🔎 STT диагностика:")
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
    msg = update.effective_message

    lines = [
        "🎬 Видео-движки:",
        # Luma
        f"• Luma key: {'✅' if bool(LUMA_API_KEY) else '❌'}  base={LUMA_BASE_URL}",
        f"  create={LUMA_CREATE_PATH}  status={LUMA_STATUS_PATH}",
        f"  model={LUMA_MODEL}  durations=['5s','9s','10s']  aspect=['16:9','9:16','1:1']",
        "",
        # Kling через CometAPI
        f"• Kling key (COMETAPI_KEY): {'✅' if bool(COMETAPI_KEY) else '❌'}  base={KLING_BASE_URL}",
        f"  model_name={KLING_MODEL_NAME}  mode={KLING_MODE}  aspect={KLING_ASPECT}  duration={KLING_DURATION_S}s",
        "",
        # Runway (текущий DEV или Comet — неважно, просто показываем конфиг)
        f"• Runway key: {'✅' if bool(RUNWAY_API_KEY) else '❌'}  base={RUNWAY_BASE_URL}",
        f"  text2video={RUNWAY_TEXT2VIDEO_PATH}  image2video={RUNWAY_IMAGE2VIDEO_PATH}",
        f"  api_version={RUNWAY_API_VERSION}",
        "",
        f"• Поллинг каждые {VIDEO_POLL_DELAY_S:.1f} c",
    ]

    await msg.reply_text("\n".join(lines))

# ───────── MIME для изображений ─────────
def sniff_image_mime(data: bytes) -> str:
    if not data or len(data) < 12:
        return "application/octet-stream"
    b = data[:12]
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if b[0:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[0:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"

# ───────── Парс опций видео ─────────
_ASPECTS = {"9:16", "16:9", "1:1", "4:5", "3:4", "4:3"}


def normalize_seconds(seconds: int) -> int:
    """Clamp generation duration to supported range."""
    try:
        s = int(seconds)
    except Exception:
        s = LUMA_DURATION_S
    return max(3, min(20, s))


def normalize_aspect(aspect: str) -> str:
    """Normalize aspect string to supported values."""
    a = (aspect or "").strip().lower().replace(" ", "")
    # common aliases
    if a in ("16x9", "16/9"):
        a = "16:9"
    if a in ("9x16", "9/16"):
        a = "9:16"
    if a in ("1x1", "1/1"):
        a = "1:1"
    if a in ("4x3", "4/3"):
        a = "4:3"
    if a in ("3x4", "3/4"):
        a = "3:4"
    if a in ("21x9", "21/9"):
        a = "21:9"
    if a in _ASPECTS:
        return a
    return "16:9"


def parse_video_opts(text: str) -> tuple[int, str]:
    tl = (text or "").lower()
    m = re.search(r"(\d+)\s*(?:сек|с)\b", tl)
    duration = int(m.group(1)) if m else LUMA_DURATION_S
    duration = max(3, min(20, duration))
    asp = None
    for a in _ASPECTS:
        if a in tl:
            asp = a
            break
    aspect = asp or (LUMA_ASPECT if LUMA_ASPECT in _ASPECTS else "16:9")
    duration = normalize_seconds(duration)
    aspect = normalize_aspect(aspect)
    return duration, aspect


async def _run_kling_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    duration: int,
    aspect: str,
) -> bool:
    """
    Запуск рендера видео в Kling (через CometAPI) и отправка результата
    в Telegram уже как mp4-файла, а не просто ссылкой.
    """
    msg = update.effective_message

    if not COMETAPI_KEY:
        await msg.reply_text("⚠️ Kling через CometAPI не настроен (нет COMETAPI_KEY).")
        return False

    # Нормализуем длительность и аспект
    dur = str(max(1, min(duration, 10)))   # Kling ждёт строку "5" / "10"
    aspect_ratio = aspect.replace(" ", "") # "16:9", "9:16" и т.п.

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            create_url = f"{KLING_BASE_URL}/kling/v1/videos/text2video"

            headers = {
                "Authorization": f"Bearer {COMETAPI_KEY}",  # ключ CometAPI
                "Content-Type": "application/json",
            }

            payload = {
                "prompt": prompt.strip(),
                "model_name": KLING_MODEL_NAME,   # напр. "kling-v1-6"
                "mode": KLING_MODE,              # "std" или "pro"
                "duration": dur,                 # "5" или "10"
                "aspect_ratio": aspect_ratio,    # "16:9", "9:16", "1:1" ...
            }

            log.info("Kling create payload: %r", payload)
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code != 200:
                txt = (r.text or "")[:800]
                log.warning("Kling create error %s: %s", r.status_code, txt)
                await msg.reply_text(
                    f"⚠️ Kling (text→video) отклонил задачу ({r.status_code}).\n"
                    f"Ответ сервера:\n`{txt}`",
                    parse_mode="Markdown",
                )
                return False

            try:
                js = r.json() or {}
            except Exception:
                js = {}

            task_id = js.get("id") or js.get("task_id") or js.get("data", {}).get("task_id")
            if not task_id:
                await msg.reply_text(
                    "⚠️ Kling: не удалось получить task_id из ответа.\n"
                    f"Сырой ответ сервера: {js}"
                )
                return False

            await msg.reply_text("⏳ Kling: задача принята, начинаю рендер видео…")

            # Пулим статус по GET /kling/v1/videos/text2video/{task_id}
            status_url = f"{KLING_BASE_URL}/kling/v1/videos/text2video/{task_id}"
            started = time.time()

            while True:
                if time.time() - started > 600:  # 10 минут
                    await msg.reply_text("⚠️ Kling: превышен лимит ожидания рендера (>10 минут).")
                    return False

                sr = await client.get(status_url, headers=headers)
                if sr.status_code != 200:
                    txt = (sr.text or "")[:500]
                    log.warning("Kling status error %s: %s", sr.status_code, txt)
                    await msg.reply_text(
                        f"⚠️ Kling status error ({sr.status_code}).\n"
                        f"Ответ сервера:\n`{txt}`",
                        parse_mode="Markdown",
                    )
                    return False

                try:
                    sjs = sr.json() or {}
                except Exception:
                    sjs = {}

                status = (sjs.get("status") or sjs.get("state") or "").lower()
                data = sjs.get("data") or {}
                video_url = (
                    data.get("video_url")
                    or data.get("url")
                    or sjs.get("video_url")
                    or sjs.get("url")
                )

                if status in ("succeed", "success", "completed") and video_url:
                    # Качаем готовое видео
                    vr = await client.get(video_url, timeout=300)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(
                            "⚠️ Kling: не удалось скачать готовое видео "
                            f"({vr.status_code})."
                        )
                        return False

                    bio = BytesIO(vr.content)
                    bio.name = "kling_text2video.mp4"
                    await context.bot.send_video(
                        chat_id=msg.chat_id,
                        video=bio,
                        supports_streaming=True,
                    )
                    return True

                if status in ("failed", "error"):
                    err = (
                        data.get("error_message")
                        or data.get("error")
                        or sjs.get("error_message")
                        or sjs.get("error")
                        or str(sjs)[:500]
                    )
                    await msg.reply_text(
                        f"❌ Kling завершился с ошибкой: `{err}`",
                        parse_mode="Markdown",
                    )
                    return False

                # Иначе — ждём дальше
                await asyncio.sleep(5.0)

    except Exception as e:
        log.exception("Kling text2video exception: %s", e)
        await msg.reply_text("❌ Kling: внутренняя ошибка при рендере видео.")
    return False
def _normalize_luma_aspect(aspect: str | None) -> str:
    """
    Luma Dream Machine поддерживает ограниченный набор аспектов.
    Приводим пользовательский аспект к допустимому значению.
    """
    allowed = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"}
    if not aspect:
        a = (LUMA_ASPECT or "16:9").replace(" ", "")
    else:
        a = aspect.replace(" ", "")

    if a in allowed:
        return a

    # Мягкая коррекция «похожих» форматов
    mapping = {
        "4:5": "3:4",
        "5:4": "4:3",
    }
    if a in mapping:
        return mapping[a]

    return "16:9"

# ───────── Покупки/инвойсы ─────────
def _plan_rub(tier: str, term: str) -> int:
    tier = (tier or "pro").lower()
    term = (term or "month").lower()
    return int(PLAN_PRICE_TABLE.get(tier, PLAN_PRICE_TABLE["pro"]).get(term, PLAN_PRICE_TABLE["pro"]["month"]))

def _plan_payload_and_amount(tier: str, months: int) -> tuple[str, int, str]:
    term = {1: "month", 3: "quarter", 12: "year"}.get(months, "month")
    amount = _plan_rub(tier, term)
    title = f"Подписка {tier.upper()} ({term})"
    payload = f"sub:{tier}:{months}"
    return payload, amount, title

async def _send_invoice_rub(title: str, desc: str, amount_rub: int, payload: str, update: Update) -> bool:
    try:
        # берём токен и валюту из двух источников (старый PROVIDER_TOKEN ИЛИ новый YOOKASSA_PROVIDER_TOKEN)
        token = (PROVIDER_TOKEN or YOOKASSA_PROVIDER_TOKEN)
        curr  = (CURRENCY if (CURRENCY and CURRENCY != "RUB") else YOOKASSA_CURRENCY) or "RUB"

        if not token:
            await update.effective_message.reply_text("⚠️ ЮKassa не настроена (нет токена).")
            return False

        prices = [LabeledPrice(label=_ascii_label(title), amount=int(amount_rub) * 100)]

        await update.effective_message.reply_invoice(
            title=title,
            description=desc[:255],
            payload=payload,
            provider_token=token,
            currency=curr,
            prices=prices,
            need_email=False,
            need_name=False,
            need_phone_number=False,
            need_shipping_address=False,
            is_flexible=False
        )
        return True

    except Exception as e:
        log.exception("send_invoice error: %s", e)
        try:
            await update.effective_message.reply_text("Не удалось выставить счёт.")
        except Exception:
            pass
        return False

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        q = update.pre_checkout_query
        await q.answer(ok=True)
    except Exception as e:
        log.exception("precheckout error: %s", e)

async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sp = update.message.successful_payment
        payload = sp.invoice_payload or ""
        total_minor = sp.total_amount or 0
        rub = total_minor / 100.0
        uid = update.effective_user.id

        if payload.startswith("sub:"):
            _, tier, months = payload.split(":", 2)
            months = int(months)
            until = activate_subscription_with_tier(uid, tier, months)
            await update.effective_message.reply_text(f"✅ Подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')}.")
            return

        # Любое иное payload — пополнение единого кошелька
        usd = rub / max(1e-9, USD_RUB)
        _wallet_total_add(uid, usd)
        await update.effective_message.reply_text(f"💳 Пополнение: {rub:.0f} ₽ ≈ ${usd:.2f} зачислено на единый баланс.")
    except Exception as e:
        log.exception("successful_payment handler error: %s", e)


# ───────── CryptoBot ─────────
CRYPTO_PAY_API_TOKEN = os.environ.get("CRYPTO_PAY_API_TOKEN", "").strip()
CRYPTO_BASE = "https://pay.crypt.bot/api"
TON_USD_RATE = float(os.environ.get("TON_USD_RATE", "5.0") or "5.0")  # запасной курс

async def _crypto_create_invoice(usd_amount: float, asset: str = "USDT", description: str = "") -> tuple[str|None, str|None, float, str]:
    if not CRYPTO_PAY_API_TOKEN:
        return None, None, 0.0, asset
    try:
        payload = {"asset": asset, "amount": round(float(usd_amount), 2), "description": description or "Top-up"}
        headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{CRYPTO_BASE}/createInvoice", headers=headers, json=payload)
            j = r.json()
            ok = j.get("ok") is True
            if not ok:
                return None, None, 0.0, asset
            res = j.get("result", {})
            return str(res.get("invoice_id")), res.get("pay_url"), float(res.get("amount", usd_amount)), res.get("asset") or asset
    except Exception as e:
        log.exception("crypto create error: %s", e)
        return None, None, 0.0, asset

async def _crypto_get_invoice(invoice_id: str) -> dict | None:
    if not CRYPTO_PAY_API_TOKEN:
        return None
    try:
        headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN}
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{CRYPTO_BASE}/getInvoices?invoice_ids={invoice_id}", headers=headers)
            j = r.json()
            if not j.get("ok"):
                return None
            items = (j.get("result", {}) or {}).get("items", [])
            return items[0] if items else None
    except Exception as e:
        log.exception("crypto get error: %s", e)
        return None

async def _poll_crypto_invoice(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, user_id: int, invoice_id: str, usd_amount: float):
    try:
        for _ in range(120):  # ~12 минут при 6с задержке
            inv = await _crypto_get_invoice(invoice_id)
            st = (inv or {}).get("status", "").lower() if inv else ""
            if st == "paid":
                _wallet_total_add(user_id, float(usd_amount))
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                        text=f"✅ CryptoBot: платёж подтверждён. Баланс пополнен на ${float(usd_amount):.2f}.")
                return
            if st in ("expired", "cancelled", "canceled", "failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                        text=f"❌ CryptoBot: платёж не завершён (статус: {st}).")
                return
            await asyncio.sleep(6.0)
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                text="⌛ CryptoBot: время ожидания вышло. Нажмите «Проверить оплату» позже.")
    except Exception as e:
        log.exception("crypto poll error: %s", e)

async def _poll_crypto_sub_invoice(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    user_id: int,
    invoice_id: str,
    tier: str,
    months: int
):
    try:
        for _ in range(120):  # ~12 минут при задержке 6с
            inv = await _crypto_get_invoice(invoice_id)
            st = (inv or {}).get("status", "").lower() if inv else ""
            if st == "paid":
                until = activate_subscription_with_tier(user_id, tier, months)
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=f"✅ CryptoBot: платёж подтверждён.\n"
                             f"Подписка {tier.upper()} активна до {until.strftime('%Y-%m-%d')}."
                    )
                return
            if st in ("expired", "cancelled", "canceled", "failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=f"❌ CryptoBot: оплата не завершена (статус: {st})."
                    )
                return
            await asyncio.sleep(6.0)

        # Таймаут
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="⌛ CryptoBot: время ожидания вышло. Нажмите «Проверить оплату» или оплатите заново."
            )
    except Exception as e:
        log.exception("crypto poll (subscription) error: %s", e)


# ───────── Предложение пополнения ─────────
async def _send_topup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("500 ₽",  callback_data="topup:rub:500"),
         InlineKeyboardButton("1000 ₽", callback_data="topup:rub:1000"),
         InlineKeyboardButton("2000 ₽", callback_data="topup:rub:2000")],
        [InlineKeyboardButton("Crypto $5",  callback_data="topup:crypto:5"),
         InlineKeyboardButton("Crypto $10", callback_data="topup:crypto:10"),
         InlineKeyboardButton("Crypto $20", callback_data="topup:crypto:20")],
    ])
    await update.effective_message.reply_text("Выберите сумму пополнения:", reply_markup=kb)


# ───────── Попытка оплатить → выполнить ─────────
async def _try_pay_then_do(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    engine: str,                # 'luma' | 'runway' | 'img'
    est_cost_usd: float,
    coro_func,                  # async function to run
    remember_kind: str = "",
    remember_payload: dict | None = None
):
    username = (update.effective_user.username or "")
    ok, offer = _can_spend_or_offer(user_id, username, engine, est_cost_usd)
    if ok:
        await coro_func()
        return
    if offer == "ASK_SUBSCRIBE":
        await update.effective_message.reply_text(
            "Для выполнения нужен тариф или единый баланс.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
                 [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
            )
        )
        return
    try:
        need_usd = float(offer.split(":", 1)[-1])
    except Exception:
        need_usd = est_cost_usd
    amount_rub = _calc_oneoff_price_rub(engine, need_usd)
    await update.effective_message.reply_text(
        f"Недостаточно лимита. Разовая покупка ≈ {amount_rub} ₽ или пополните баланс:",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
                [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")],
            ]
        ),
    )


# ───────── /plans ─────────
async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["⭐ Тарифы:"]
    for tier, terms in PLAN_PRICE_TABLE.items():
        lines.append(f"— {tier.upper()}: "
                     f"{terms['month']}₽/мес • {terms['quarter']}₽/квартал • {terms['year']}₽/год")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Купить START (1 мес)",    callback_data="buy:start:1"),
         InlineKeyboardButton("Купить PRO (1 мес)",      callback_data="buy:pro:1")],
        [InlineKeyboardButton("Купить ULTIMATE (1 мес)", callback_data="buy:ultimate:1")],
        [InlineKeyboardButton("Открыть мини-витрину",    web_app=WebAppInfo(url=TARIFF_URL))]
    ])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb)


# ───────── Обёртка для передачи произвольного текста (напр. из STT) ─────────
async def on_text_with_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
):
    """
    Обёртка для передачи текста (например, после STT) в on_text,
    без попыток изменить update.message (read-only!).
    """
    text = (text or "").strip()
    if not text:
        await update.effective_message.reply_text("Не удалось распознать текст.")
        return

    await on_text(update, context, manual_text=text)


# ───────── Текстовый вход ─────────
async def on_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    manual_text: str | None = None,
):
    # Если текст передан извне → используем его
    # иначе — обычный текст сообщения
    if manual_text is not None:
        text = manual_text.strip()
    else:
        text = (update.message.text or "").strip()

    # Вопросы о возможностях
    cap = capability_answer(text)
    if cap:
        await update.effective_message.reply_text(cap)
        return

    # Намёк на генерацию видеоролика
    mtype, rest = detect_media_intent(text)
    if mtype == "video":
        # ГАРАНТИРОВАННО задаём prompt для текста и для голоса
        prompt = (rest or text).strip()

        duration, aspect = parse_video_opts(text)

        aid = _new_aid()
        _pending_actions[aid] = {
            "prompt": prompt,
            "duration": duration,
            "aspect": aspect,
        }

        tier = get_subscription_tier(update.effective_user.id)

        est_kling = float(KLING_UNIT_COST_USD or 0.40) * duration
        est_luma  = float(LUMA_UNIT_COST_USD or 0.40) * duration
        est_sora  = float(SORA_UNIT_COST_USD or 0.40) * duration

        rows = []
        rows.append([InlineKeyboardButton(
            f"🎞 Kling (~${est_kling:.2f})",
            callback_data=f"choose:kling:{aid}",
        )])
        rows.append([InlineKeyboardButton(
            f"🎬 Luma (~${est_luma:.2f})",
            callback_data=f"choose:luma:{aid}",
        )])

        # Sora: show Pro label for pro/ultimate tiers
        if SORA_ENABLED:
            if tier in ("pro", "ultimate"):
                rows.append([InlineKeyboardButton("✨ Sora 2 Pro", callback_data=f"choose:sora:{aid}")])
            else:
                rows.append([InlineKeyboardButton("✨ Sora 2", callback_data=f"choose:sora:{aid}")])

        kb = InlineKeyboardMarkup(rows)

        await update.effective_message.reply_text(
            f"Что использовать?\n"
            f"Длительность: {duration} c • Аспект: {aspect}\n"
            f"Запрос: «{prompt}»",
            reply_markup=kb,
        )
        return

    # Намёк на картинку
    if mtype == "image":
        prompt = rest or re.sub(
            r"^(img|image|picture)\s*[:\-]\s*",
            "",
            text,
            flags=re.I,
        ).strip()

        if not prompt:
            await update.effective_message.reply_text(
                "Формат: /img <описание изображения>"
            )
            return

        async def _go():
            await _do_img_generate(update, context, prompt)

        await _try_pay_then_do(
            update,
            context,
            update.effective_user.id,
            "img",
            IMG_COST_USD,
            _go,
        )
        return

    # Обычный текст → GPT
    ok, _, _ = check_text_and_inc(
        update.effective_user.id,
        update.effective_user.username or "",
    )

    if not ok:
        await update.effective_message.reply_text(
            "Лимит текстовых запросов на сегодня исчерпан. "
            "Оформите ⭐ подписку или попробуйте завтра."
        )
        return

    user_id = update.effective_user.id

    # Режимы
    try:
        mode = _mode_get(user_id)
        track = _mode_track_get(user_id)
    except NameError:
        mode, track = "none", ""

    if mode and mode != "none":
        text_for_llm = f"[Режим: {mode}; Подрежим: {track or '-'}]\n{text}"
    else:
        text_for_llm = text

    if mode == "Учёба" and track:
        await study_process_text(update, context, text)
        return

    reply = await ask_openai_text(text_for_llm)
    await update.effective_message.reply_text(reply)
    await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])
    
# ───────── Фото / Документы / Голос ─────────
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.photo:
            return

        ph = update.message.photo[-1]
        f = await ph.get_file()
        data = await f.download_as_bytearray()
        img = bytes(data)

        # --- СТАРЫЙ КЭШ (как раньше) ---
        _cache_photo(update.effective_user.id, img)

        # --- НОВЫЙ КЭШ ДЛЯ ОЖИВЛЕНИЯ / LUMA / KLING ---
        # Сохраняем и bytes, и публичный URL Telegram (подходит для Luma/Comet)
        with contextlib.suppress(Exception):
            _LAST_ANIM_PHOTO[update.effective_user.id] = {
                "bytes": img,
                "url": (f.file_path or "").strip(),   # публичный HTTPS-URL Telegram API
            }

        caption = (update.message.caption or "").strip()
        if caption:
            tl = caption.lower()

            # ── ОЖИВЛЕНИЕ ФОТО (через выбор движка) ──
            if any(k in tl for k in ("оживи", "оживить", "анимиру", "анимировать", "сделай видео", "revive", "animate")):
                dur, asp = parse_video_opts(caption)

                # очищаем prompt от триггер-слов
                prompt = re.sub(
                    r"\b(оживи|оживить|анимируй|анимировать|сделай видео|revive|animate)\b",
                    "",
                    caption,
                    flags=re.I
                ).strip(" ,.")

                # сохраняем входные параметры в user_data (без глобальных pending)
                context.user_data["revive_photo"] = {
                    "duration": int(dur),
                    "aspect": asp,
                    "prompt": prompt,
                }

                # показываем выбор движка
                await update.effective_message.reply_text(
                    "Выбери движок для оживления фото:",
                    reply_markup=revive_engine_kb()
                )
                return

            # ── удалить фон ──
            if any(k in tl for k in ("удали фон", "removebg", "убрать фон")):
                await _pedit_removebg(update, context, img)
                return

            # ── заменить фон ──
            if any(k in tl for k in ("замени фон", "replacebg", "размытый", "blur")):
                await _pedit_replacebg(update, context, img)
                return

            # ── outpaint ──
            if "outpaint" in tl or "расшир" in tl:
                await _pedit_outpaint(update, context, img)
                return

            # ── раскадровка ──
            if "раскадров" in tl or "storyboard" in tl:
                await _pedit_storyboard(update, context, img)
                return

            # ── картинка по описанию (Luma / fallback OpenAI) ──
            if (
                any(k in tl for k in ("картин", "изображен", "image", "img"))
                and any(k in tl for k in ("сгенериру", "созда", "сделай"))
            ):
                await _start_luma_img(update, context, caption)
                return

        # если явной команды нет — быстрые кнопки
        await update.effective_message.reply_text(
            "Фото получено. Что сделать?",
            reply_markup=photo_quick_actions_kb()
        )

    except Exception as e:
        log.exception("on_photo error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Не смог обработать фото.")
            
async def on_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document:
            return

        doc = update.message.document
        mt = (doc.mime_type or "").lower()
        tg_file = await doc.get_file()
        data = await tg_file.download_as_bytearray()
        raw = bytes(data)

        # документ оказался изображением
        if mt.startswith("image/"):
            _cache_photo(update.effective_user.id, raw)

            # --- НОВЫЙ КЭШ ДЛЯ ОЖИВЛЕНИЯ ---
            try:
                _LAST_ANIM_PHOTO[update.effective_user.id] = {
                    "bytes": raw,
                    "url": tg_file.file_path,    # Telegram public URL
                }
            except Exception:
                pass

            await update.effective_message.reply_text(
                "Изображение получено как документ. Что сделать?",
                reply_markup=photo_quick_actions_kb()
            )
            return

        # остальные документы → извлечение текста
        text, kind = extract_text_from_document(raw, doc.file_name or "file")
        if not (text or "").strip():
            await update.effective_message.reply_text(f"Не удалось извлечь текст из {kind}.")
            return

        goal = (update.message.caption or "").strip() or Noneбх
        await update.effective_message.reply_text(f"📄 Извлекаю текст ({kind}), готовлю конспект…")

        summary = await summarize_long_text(text, query=goal)
        summary = summary or "Готово."
        await update.effective_message.reply_text(summary)

        await maybe_tts_reply(update, context, summary[:TTS_MAX_CHARS])

    except Exception as e:
        log.exception("on_doc error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Ошибка при обработке документа.")
            
# ───────── Хелперы для аспектов ─────────

def _runway_aspect_to_ratio(aspect_str: str | None) -> str:
    """
    Переводит "16:9"/"9:16"/"1:1" в допустимые ratio Runway:
    1280:720, 720:1280, 960:960, 1104:832, 832:1104, 1584:672, 1280:768, 768:1280.
    Если пришло уже "1280:720" и т.п. — возвращаем как есть.
    """
    default_ratio = RUNWAY_RATIO or "1280:720"
    mapping = {
        "16:9": "1280:720",
        "9:16": "720:1280",
        "1:1": "960:960",
        "4:3": "1104:832",
        "3:4": "832:1104",
        # широкие форматы можно привязать к самым близким
        "21:9": "1584:672",
        "9:21": "768:1280",
    }
    if not aspect_str:
        return default_ratio
    a = aspect_str.replace(" ", "")
    if a in mapping:
        return mapping[a]
    # если уже похоже на "1280:720"
    if re.match(r"^\d+:\d+$", a):
        return a
    return default_ratio


def _normalize_luma_aspect(aspect: str | None) -> str:
    """
    Luma Dream Machine поддерживает ограниченный набор аспектов.
    Приводим пользовательский аспект к допустимому значению.
    """
    allowed = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"}
    if not aspect:
        a = (LUMA_ASPECT or "16:9").replace(" ", "")
    else:
        a = aspect.replace(" ", "")

    if a in allowed:
        return a

    # Мягкая коррекция «похожих» форматов
    mapping = {
        "4:5": "3:4",
        "5:4": "4:3",
    }
    if a in mapping:
        return mapping[a]

    return "16:9"


# ───────── RUNWAY: IMAGE → VIDEO (CometAPI) ─────────

async def _run_runway_animate_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    image_url: str,
    prompt: str = "",
    duration_s: int = 5,
    aspect: str = "16:9",
):
    """
    Image -> Video через CometAPI (runwayml wrapper).
    Делает create -> poll status -> download mp4 -> send_video
    + уведомление, если считает > 3 минут.
    """
    chat_id = update.effective_chat.id
    msg = update.effective_message

    await context.bot.send_chat_action(chat_id, ChatAction.RECORD_VIDEO)

    # Берём ключ: приоритет COMETAPI_KEY, иначе RUNWAY_API_KEY
    api_key = (COMETAPI_KEY or RUNWAY_API_KEY or "").strip()
    if not api_key:
        await msg.reply_text("⚠️ Runway/Comet: не настроен ключ (COMETAPI_KEY или RUNWAY_API_KEY).")
        return

    # Нормализуем duration
    try:
        duration_val = int(duration_s or RUNWAY_DURATION_S or 5)
    except Exception:
        duration_val = RUNWAY_DURATION_S or 5
    duration_val = max(3, min(20, duration_val))

    ratio = _runway_aspect_to_ratio(aspect)  # у тебя уже есть эта функция/маппинг
    prompt_clean = (prompt or "").strip()

    # Paths (Comet)
    create_path = (RUNWAY_IMAGE2VIDEO_PATH or "/runwayml/v1/image_to_video").strip()
    status_tpl = (RUNWAY_STATUS_PATH or "/runwayml/v1/tasks/{id}").strip()
    create_url = f"{RUNWAY_BASE_URL}{create_path}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload = {
        "model": (RUNWAY_MODEL or "gen3a_turbo"),
        "promptImage": image_url,
        "promptText": prompt_clean,
        "duration": duration_val,
        "ratio": ratio,
        "watermark": False,
    }

    try:
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
            r = await client.post(create_url, headers=headers, json=payload)

            if r.status_code >= 400:
                txt = (r.text or "")[:1200]
                log.warning("Runway/Comet image2video create error %s: %s", r.status_code, txt)
                await msg.reply_text(
                    "⚠️ Runway/Comet image→video отклонил задачу.\n"
                    f"Код: {r.status_code}\n"
                    f"Ответ:\n`{txt}`",
                    parse_mode="Markdown",
                )
                return

            try:
                js = r.json() or {}
            except Exception:
                js = {}

            # Comet: id может лежать глубоко
            task_id = None
            for d in _dicts_bfs(js):
                v = d.get("id") or d.get("task_id") or d.get("taskId")
                if isinstance(v, str) and v.strip():
                    task_id = v.strip()
                    break

            if not task_id:
                await msg.reply_text(
                    f"⚠️ Runway/Comet: не вернул id задачи.\n`{str(js)[:1200]}`",
                    parse_mode="Markdown",
                )
                return

            await msg.reply_text("⏳ Runway: анимирую фото…")

            status_url = f"{RUNWAY_BASE_URL}{status_tpl.format(id=task_id)}"
            started = time.time()
            notified_long_wait = False

            while True:
                rs = await client.get(status_url, headers=headers, timeout=60.0)

                if rs.status_code >= 400:
                    txt = (rs.text or "")[:1200]
                    log.warning("Runway/Comet status error %s: %s", rs.status_code, txt)
                    await msg.reply_text(
                        "⚠️ Runway: ошибка статуса.\n"
                        f"Код: {rs.status_code}\n"
                        f"Ответ:\n`{txt}`",
                        parse_mode="Markdown",
                    )
                    return

                try:
                    sjs = rs.json() or {}
                except Exception:
                    sjs = {}

                status = _pick_status(sjs)

                # Уведомление при долгом ожидании (1 раз)
                elapsed = time.time() - started
                if elapsed > 180 and not notified_long_wait:
                    notified_long_wait = True
                    await msg.reply_text(
                        "⏳ Runway считает дольше обычного.\n"
                        "Я пришлю видео сразу, как оно будет готово."
                    )

                if status in ("succeeded", "success", "completed", "finished", "ready", "done"):
                    video_url = _pick_video_url(sjs)
                    if not video_url:
                        await msg.reply_text(
                            f"⚠️ Runway: задача завершилась, но не найден URL видео.\n`{str(sjs)[:1200]}`",
                            parse_mode="Markdown",
                        )
                        return

                    vr = await client.get(video_url, timeout=300.0)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(f"⚠️ Runway: не удалось скачать видео ({vr.status_code}).")
                        return

                    bio = BytesIO(vr.content)
                    bio.name = "runway_image2video.mp4"
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=bio,
                        supports_streaming=True,
                    )
                    return

                if status in ("failed", "error", "cancelled", "canceled", "rejected"):
                    err = _pick_error(sjs) or str(sjs)[:700]
                    await msg.reply_text(f"❌ Runway (image→video) ошибка: `{err}`", parse_mode="Markdown")
                    return

                if time.time() - started > RUNWAY_MAX_WAIT_S:
                    await msg.reply_text(
                        "⌛ Runway считает слишком долго.\n"
                        "Если видео будет готово позже — я пришлю его автоматически."
                    )
                    # ВАЖНО: сейчас мы просто выходим.
                    # Если хочешь реально “автоматически позже” — добавлю background-poller (через create_task)
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Runway image2video exception: %s", e)
        await msg.reply_text("❌ Runway: ошибка выполнения image→video.")

# ---------------- helpers -----------------def-_dicts_bfs(cts_bfs(root: object, max_depth6)int = """Собираем словари в ширину, чтобы найти status/video_url в любом вложении."""ении.""" = []
    q = [(root, 0)]
    seen = set()
    while q:
        node, dpt = q.pop(0)
        if id(node) in seen:
            continue
        seen.add(id(node))

        if isinstance(node, dict):
            out.append(node)
            if dpt < max_depth:
                for v in node.values():
                    if isinstance(v, (dict, list, tuple)):
                        q.append((v, dpt + 1))
        elif isinstance(node, (list, tuple)):
            if dpt < max_depth:
                for v in node:
                    if isinstance(v, (dict, list, tuple)):
                        q.append((v, dpt + 1))
    return out


def _pick_status(sjs: dict) -> str:
    for d in _dicts_bfs(sjs):
        for k in ("status", "state", "task_status", "taskStatus", "job_status", "jobStatus"):
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip().lower()
    return ""


def _pick_error(sjs: dict) -> str:
    for d in _dicts_bfs(sjs):
        for k in ("error_message", "message", "detail", "task_status_msg"):
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        v = d.get("error")
        if isinstance(v, dict):
            for kk in ("message", "detail", "type"):
                vv = v.get(kk)
                if isinstance(vv, str) and vv.strip():
                    return vv.strip()
        elif isinstance(v, str) and v.strip():
            return v.strip()
    return ""

def _dicts_bfs(root, max_depth: int = 12):
    """
    Обход вложенных dict/list в ширину.
    Возвращает все dict, чтобы легко найти id/status/url где угодно в ответе.
    """
    q = [(root, 0)]
    seen = set()

    while q:
        cur, depth = q.pop(0)
        if depth > max_depth:
            continue

        if isinstance(cur, dict):
            obj_id = id(cur)
            if obj_id in seen:
                continue
            seen.add(obj_id)

            yield cur
            for v in cur.values():
                if isinstance(v, (dict, list, tuple)):
                    q.append((v, depth + 1))

        elif isinstance(cur, (list, tuple)):
            obj_id = id(cur)
            if obj_id in seen:
                continue
            seen.add(obj_id)

            for it in cur:
                if isinstance(it, (dict, list, tuple)):
                    q.append((it, depth + 1))
    
def _pick_video_url(obj):
    """
    Достаёт URL видео из любых форм ответов (Comet/Runway/Luma/etc).
    Часто Comet: data -> data -> output: [ "https://...mp4" ]
    """
    if not obj:
        return None

    if isinstance(obj, str):
        s = obj.strip()
        return s if s.startswith("http") else None

    if isinstance(obj, (list, tuple)):
        for it in obj:
            u = _pick_video_url(it)
            if u:
                return u
        return None

    if isinstance(obj, dict):
        # быстрые ключи
        for k in (
            "video_url", "videoUrl",
            "download_url", "downloadUrl",
            "output_url", "outputUrl",
            "url", "uri",
            "video", "videoUrl", "videoURL",
        ):
            v = obj.get(k)
            if isinstance(v, str) and v.strip().startswith("http"):
                return v.strip()

        # output / outputs
        for k in ("output", "outputs"):
            u = _pick_video_url(obj.get(k))
            if u:
                return u

        # типичные контейнеры
        for k in ("data", "result", "response", "payload", "assets"):
            u = _pick_video_url(obj.get(k))
            if u:
                return u

        # общий обход
        for v in obj.values():
            u = _pick_video_url(v)
            if u:
                return u

    return None

# ───────── RUNWAY: TEXT → VIDEO ─────────
async def _run_runway_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    duration_s: int,
    aspect: str,
) -> bool:
    """
    Текст → видео в Runway (через CometAPI /runwayml/v1/text_to_video).
    """
    msg = update.effective_message
    chat_id = update.effective_chat.id

    api_key = (os.environ.get("COMETAPI_KEY") or COMETAPI_KEY or "").strip()
    if not api_key:
        api_key = (os.environ.get("RUNWAY_API_KEY") or RUNWAY_API_KEY or "").strip()

    if not api_key:
        await msg.reply_text("⚠️ Runway: не настроен API-ключ (COMETAPI_KEY / RUNWAY_API_KEY).")
        return False

    await context.bot.send_chat_action(chat_id, ChatAction.RECORD_VIDEO)

    try:
        duration_s = int(duration_s or RUNWAY_DURATION_S or 5)
    except Exception:
        duration_s = RUNWAY_DURATION_S or 5
    if duration_s < 5:
        duration_s = 5
    if duration_s > 10:
        duration_s = 10

    ratio = _runway_aspect_to_ratio(aspect)
    prompt_clean = (prompt or "").strip()[:512]

    create_url = f"{RUNWAY_BASE_URL}{RUNWAY_TEXT2VIDEO_PATH}"
    status_tpl = RUNWAY_STATUS_PATH or "/runwayml/v1/tasks/{id}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Runway-Version": RUNWAY_API_VERSION,
    }

    payload = {
        "model": RUNWAY_MODEL or "gen3a_turbo",
        "promptText": prompt_clean or "Empty prompt",
        "duration": int(duration_s),
        "ratio": ratio,
        "watermark": False,
    }

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code != 200:
                txt = (r.text or "")[:800]
                log.warning("Runway text2video create error %s: %s", r.status_code, txt)
                await msg.reply_text(
                    "⚠️ Runway (text→video) отклонил задачу "
                    f"({r.status_code}).\nОтвет сервера:\n`{txt}`",
                    parse_mode="Markdown",
                )
                return False

            try:
                js = r.json() or {}
            except Exception:
                js = {}

            task_id = (
                js.get("id")
                or js.get("task_id")
                or (js.get("data") or {}).get("id")
                or (js.get("data") or {}).get("task_id")
            )
            if not task_id:
                snippet = (json.dumps(js, ensure_ascii=False) if js else r.text)[:800]
                await msg.reply_text(
                    "⚠️ Runway (text→video) не вернул ID задачи.\n"
                    f"Ответ сервера:\n`{snippet}`",
                    parse_mode="Markdown",
                )
                return False

            status_url = f"{RUNWAY_BASE_URL}{status_tpl.format(id=task_id)}"
            started = time.time()

            while True:
                rs = await client.get(status_url, headers=headers)
                if rs.status_code != 200:
                    txt = (rs.text or "")[:800]
                    log.warning("Runway text2video status error %s: %s", rs.status_code, txt)
                    await msg.reply_text(
                        "⚠️ Runway (text→video) статус-заказ вернул ошибку.\n"
                        f"Код: {rs.status_code}\n"
                        f"Ответ:\n`{txt}`",
                        parse_mode="Markdown",
                    )
                    return False

                try:
                    sjs = rs.json() or {}
                except Exception:
                    sjs = {}

                d = sjs.get("data") or sjs
                status = (
                    d.get("status")
                    or d.get("task_status")
                    or d.get("state")
                    or ""
                ).lower()

                if status in ("succeeded", "success", "completed", "done"):
                    video_url = None

                    candidates = [
                        d.get("result"),
                        d.get("output"),
                        d.get("task_result"),
                        d.get("data"),
                        d.get("video"),
                        d.get("videos"),
                        sjs.get("result"),
                        sjs.get("output"),
                    ]

                    def _extract_url(obj):
                        if isinstance(obj, dict):
                            for k in ("url", "uri", "video_url", "videoUri", "output_url"):
                                v = obj.get(k)
                                if isinstance(v, str) and v.startswith("http"):
                                    return v
                        return None

                    for c in candidates:
                        if isinstance(c, (list, tuple)):
                            for item in c:
                                video_url = _extract_url(item)
                                if video_url:
                                    break
                        else:
                            video_url = _extract_url(c)
                        if video_url:
                            break

                    if not video_url:
                        snippet = (json.dumps(sjs, ensure_ascii=False) if sjs else rs.text)[:800]
                        await msg.reply_text(
                            "⚠️ Runway (text→video): задача завершилась, но не найден URL видео.\n"
                            f"Ответ сервера:\n`{snippet}`",
                            parse_mode="Markdown",
                        )
                        return False

                    vr = await client.get(video_url, timeout=300)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(
                            "⚠️ Runway: не удалось скачать готовое видео "
                            f"({vr.status_code})."
                        )
                        return False

                    bio = BytesIO(vr.content)
                    bio.name = "runway_text2video.mp4"
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=bio,
                        supports_streaming=True,
                    )
                    return True

                if status in ("failed", "error", "cancelled", "canceled"):
                    err = (
                        d.get("error_message")
                        or d.get("error")
                        or d.get("task_status_msg")
                        or str(sjs)[:500]
                    )
                    await msg.reply_text(
                        f"❌ Runway (text→video) завершилась с ошибкой: `{err}`",
                        parse_mode="Markdown",
                    )
                    return False

                if time.time() - started > RUNWAY_MAX_WAIT_S:
                    await msg.reply_text("⌛ Runway (text→video): превышено время ожидания.")
                    return False

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Runway text2video exception: %s", e)
        err = str(e)[:400]
        await msg.reply_text(
            "❌ Runway: не удалось запустить/получить видео (text→video).\n"
            f"Текст ошибки:\n`{err}`",
            parse_mode="Markdown",
        )


# ───────── KLING: IMAGE → VIDEO (оживление фото) ─────────
    return False
async def _run_kling_animate_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    img_bytes: bytes,
    prompt: str,
    duration_s: int,
    aspect: str,
):
    """
    Оживление фото через Kling image2video (CometAPI /kling/v1/videos/image2video).
    """
    msg = update.effective_message
    chat_id = update.effective_chat.id

    api_key = (os.environ.get("COMETAPI_KEY") or COMETAPI_KEY or "").strip()
    if not api_key:
        await msg.reply_text("⚠️ Kling: не настроен COMETAPI_KEY.")
        return

    await context.bot.send_chat_action(chat_id, ChatAction.RECORD_VIDEO)

    try:
        dur = int(duration_s or KLING_DURATION_S or 5)
    except Exception:
        dur = KLING_DURATION_S or 5
    if dur not in (5, 10):
        dur = 5

    aspect_ratio = (aspect or KLING_ASPECT or "9:16").replace(" ", "")
    prompt_clean = (prompt or "").strip()[:500]
    img_b64 = base64.b64encode(img_bytes).decode()

    create_url = f"{KLING_BASE_URL}/kling/v1/videos/image2video"
    status_tpl = "/kling/v1/tasks/{id}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "model_name": KLING_MODEL_NAME or "kling-v1-6",
        "mode": KLING_MODE or "std",   # std / pro
        "duration": str(dur),
        "image": img_b64,
        "prompt": prompt_clean or "Animate this portrait.",
        "cfg_scale": 0.5,
        "aspect_ratio": aspect_ratio,
    }

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code != 200:
                txt = (r.text or "")[:800]
                log.warning("Kling image2video create error %s: %s", r.status_code, txt)
                await msg.reply_text(
                    "⚠️ Kling (image→video) отклонил задачу "
                    f"({r.status_code}).\nОтвет сервера:\n`{txt}`",
                    parse_mode="Markdown",
                )
                return

            try:
                js = r.json() or {}
            except Exception:
                js = {}

            data = js.get("data") or {}
            task_id = data.get("task_id") or data.get("id")
            if not task_id:
                snippet = (json.dumps(js, ensure_ascii=False) if js else r.text)[:800]
                await msg.reply_text(
                    "⚠️ Kling (image→video) не вернул ID задачи.\n"
                    f"Ответ сервера:\n`{snippet}`",
                    parse_mode="Markdown",
                )
                return

            await msg.reply_text("⏳ Kling: анимирую фото…")

            status_url = f"{KLING_BASE_URL}{status_tpl.format(id=task_id)}"
            started = time.time()

            while True:
                rs = await client.get(status_url, headers=headers)
                try:
                    sjs = rs.json() or {}
                except Exception:
                    sjs = {}

                d = sjs.get("data") or {}
                status = (d.get("task_status") or "").lower()

                if status in ("succeed", "success", "completed"):
                    tr = d.get("task_result") or {}
                    vids = tr.get("videos") or {}
                    video_url = vids.get("url") if isinstance(vids, dict) else None

                    if not video_url:
                        snippet = (json.dumps(sjs, ensure_ascii=False) if sjs else rs.text)[:800]
                        await msg.reply_text(
                            "⚠️ Kling (image→video): задача завершилась, но не найден URL видео.\n"
                            f"Ответ сервера:\n`{snippet}`",
                            parse_mode="Markdown",
                        )
                        return

                    vr = await client.get(video_url, timeout=300)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(
                            "⚠️ Kling: не удалось скачать готовое видео "
                            f"({vr.status_code})."
                        )
                        return

                    bio = BytesIO(vr.content)
                    bio.name = "kling_image2video.mp4"
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=bio,
                        supports_streaming=True,
                    )
                    return

                if status in ("failed", "error"):
                    err = d.get("task_status_msg") or str(sjs)[:500]
                    await msg.reply_text(
                        f"❌ Kling (image→video) завершилась с ошибкой: `{err}`",
                        parse_mode="Markdown",
                    )
                    return

                if time.time() - started > KLING_MAX_WAIT_S:
                    await msg.reply_text("⌛ Kling (image→video): превышено время ожидания.")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Kling image2video exception: %s", e)
        await msg.reply_text(
            "❌ Kling: не удалось запустить/получить видео (image→video)."
        )


# ───────── KLING: TEXT → VIDEO ─────────

async def _run_kling_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    duration: int,
    aspect: str,
):
    """
    Текст → видео в Kling (через CometAPI /kling/v1/videos/text2video).
    """
    msg = update.effective_message

    if not COMETAPI_KEY:
        await msg.reply_text("⚠️ Kling через CometAPI не настроен (нет COMETAPI_KEY).")
        return

    try:
        dur_val = int(duration or KLING_DURATION_S or 5)
    except Exception:
        dur_val = KLING_DURATION_S or 5
    if dur_val < 5:
        dur_val = 5
    if dur_val > 10:
        dur_val = 10
    dur = str(dur_val)

    aspect_ratio = (aspect or KLING_ASPECT or "9:16").replace(" ", "")

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            create_url = f"{KLING_BASE_URL}/kling/v1/videos/text2video"

            headers = {
                "Authorization": f"Bearer {COMETAPI_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            payload = {
                "prompt": (prompt or "").strip(),
                "model_name": KLING_MODEL_NAME,
                "mode": KLING_MODE,
                "duration": dur,
                "aspect_ratio": aspect_ratio,
            }

            log.info("Kling text2video create payload: %r", payload)
            r = await client.post(create_url, headers=headers, json=payload)

            try:
                js = r.json() or {}
            except Exception:
                js = {}
            log.info("Kling text2video create response: %r", js)

            if r.status_code != 200:
                txt = (r.text or "")[:800]
                await msg.reply_text(
                    "⚠️ Kling (text→video) отклонил задачу "
                    f"({r.status_code}).\nОтвет сервера:\n`{txt}`",
                    parse_mode="Markdown",
                )
                return

            data = js.get("data") or {}
            inner = data.get("data") or {}
            task_id = data.get("task_id") or inner.get("task_id") or js.get("task_id")

            if not task_id:
                await msg.reply_text(
                    "⚠️ Kling: не удалось получить task_id из ответа.\n"
                    f"Сырой ответ: `{js}`",
                    parse_mode="Markdown",
                )
                return

            await msg.reply_text("⏳ Kling: задача принята, начинаю рендер видео…")

            status_url = f"{KLING_BASE_URL}/kling/v1/videos/text2video/{task_id}"
            started = time.time()

            while True:
                rs = await client.get(
                    status_url,
                    headers={
                        "Authorization": f"Bearer {COMETAPI_KEY}",
                        "Accept": "application/json",
                    },
                    timeout=60.0,
                )

                try:
                    sjs = rs.json() or {}
                except Exception:
                    sjs = {}
                log.info("Kling text2video status: %r", sjs)

                sdata = sjs.get("data") or {}
                status = (sdata.get("task_status") or sdata.get("status") or "").lower()

                if status in ("succeed", "success", "completed"):
                    task_result = sdata.get("task_result") or {}
                    videos = task_result.get("videos")

                    video_obj = None
                    if isinstance(videos, list) and videos:
                        video_obj = videos[0]
                    elif isinstance(videos, dict):
                        video_obj = videos

                    video_url = None
                    if isinstance(video_obj, dict):
                        video_url = (
                            video_obj.get("url")
                            or video_obj.get("video_url")
                        )

                    if not video_url:
                        await msg.reply_text(
                            "⚠️ Kling: задача завершилась, но не найден URL видео.\n"
                            f"Сырой ответ: `{sjs}`",
                            parse_mode="Markdown",
                        )
                        return

                    vr = await client.get(video_url, timeout=300.0)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(
                            "⚠️ Kling: не удалось скачать готовое видео "
                            f"({vr.status_code})."
                        )
                        return

                    bio = BytesIO(vr.content)
                    bio.name = "kling_text2video.mp4"
                    await context.bot.send_video(
                        chat_id=update.effective_chat.id,
                        video=bio,
                        supports_streaming=True,
                    )
                    return

                if status in ("failed", "error"):
                    err = (
                        sdata.get("task_status_msg")
                        or sdata.get("error_message")
                        or sdata.get("error")
                        or str(sjs)[:500]
                    )
                    await msg.reply_text(
                        f"❌ Kling (text→video) завершился с ошибкой: `{err}`",
                        parse_mode="Markdown",
                    )
                    return

                if time.time() - started > KLING_MAX_WAIT_S:
                    await msg.reply_text("⌛ Kling (text→video): превышено время ожидания.")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Kling text2video exception: %s", e)
        err = str(e)[:400]
        await msg.reply_text(
            "❌ Kling: не удалось запустить/получить видео (text→video).\n"
            f"Текст ошибки:\n`{err}`",
            parse_mode="Markdown",
        )


# ───────── LUMA: IMAGE → VIDEO (оживление фото) ─────────

async def _run_luma_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    duration_s: int,
    aspect: str,
) -> bool:
    """
    Текст → видео в Luma Dream Machine (ray-2).
    """
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)

    if not LUMA_API_KEY:
        await update.effective_message.reply_text("⚠️ Luma: не настроен LUMA_API_KEY.")
        return False

    # duration
    try:
        duration_val = int(duration_s or LUMA_DURATION_S or 5)
    except Exception:
        duration_val = int(LUMA_DURATION_S or 5)
    duration_val = max(3, min(20, duration_val))

    aspect_ratio = _normalize_luma_aspect(aspect)
    prompt_clean = (prompt or "").strip()

    timeout = httpx.Timeout(60.0, connect=30.0)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            base = await _pick_luma_base(client)
            create_url = f"{base}{LUMA_CREATE_PATH}"

            headers = {
                "Authorization": f"Bearer {LUMA_API_KEY}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            payload = {
                "model": (LUMA_MODEL or "ray-2").strip(),
                "prompt": prompt_clean,
                "duration": f"{duration_val}s",
                "aspect_ratio": aspect_ratio,
            }

            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code >= 400:
                txt = (r.text or "")[:800]
                await update.effective_message.reply_text(
                    "⚠️ Luma (text→video) отклонила задачу.\n"
                    f"Код: {r.status_code}\n"
                    f"Ответ:\n`{txt}`",
                    parse_mode="Markdown",
                )
                return False

            try:
                gen = r.json() or {}
            except Exception:
                gen = {}

            gen_id = gen.get("id") or gen.get("generation_id")
            if not gen_id:
                snippet = (json.dumps(gen, ensure_ascii=False) if gen else (r.text or ""))[:800]
                await update.effective_message.reply_text(
                    "⚠️ Luma: не вернула id генерации.\n"
                    f"Ответ сервера:\n`{snippet}`",
                    parse_mode="Markdown",
                )
                return False

            # ВАЖНО: status_url должен быть СТРОКОЙ, а не .format-методом
            status_url = f"{base}{LUMA_STATUS_PATH}".format(id=gen_id)

            started = time.time()

            while True:
                rs = await client.get(status_url, headers=headers)
                try:
                    js = rs.json() or {}
                except Exception:
                    js = {}

                st = (js.get("state") or js.get("status") or "").lower()

                if st in ("completed", "succeeded", "finished", "ready"):
                    url = None
                    assets = js.get("assets")

                    def _extract_urls_from_assets(a):
                        urls = []
                        if isinstance(a, str):
                            if a.startswith("http"):
                                urls.append(a)
                        elif isinstance(a, dict):
                            for v in a.values():
                                urls.extend(_extract_urls_from_assets(v))
                        elif isinstance(a, (list, tuple)):
                            for item in a:
                                urls.extend(_extract_urls_from_assets(item))
                        return urls

                    candidates = []
                    if assets is not None:
                        candidates.extend(_extract_urls_from_assets(assets))

                    for k in ("video", "video_url"):
                        v = js.get(k)
                        if isinstance(v, str) and v.startswith("http"):
                            candidates.append(v)

                    for u in candidates:
                        if isinstance(u, str) and u.startswith("http"):
                            url = u
                            break

                    if not url:
                        log.error("Luma: ответ без ссылки на видео: %s", js)
                        await update.effective_message.reply_text("❌ Luma: ответ пришёл без ссылки на видео.")
                        return False

                    try:
                        v = await client.get(url, timeout=httpx.Timeout(120.0, connect=30.0))
                        v.raise_for_status()
                        bio = BytesIO(v.content)
                        bio.name = "luma_text2video.mp4"
                        await context.bot.send_video(
                            chat_id=update.effective_chat.id,
                            video=bio,
                            supports_streaming=True,
                        )
                    except Exception as e:
                        log.exception("Luma download/send error: %s", e)
                        await update.effective_message.reply_text("⚠️ Luma: ошибка при скачивании/отправке видео.")
                    return True

                if st in ("failed", "error"):
                    if _is_luma_ip_error(js):
                        await update.effective_message.reply_text(
                            "❌ Luma отклонила запрос из-за IP (защищённый персонаж/бренд в тексте).\n"
                            "Переформулируй без названий (например: «плюшевый медвежонок…») и попробуй ещё раз."
                        )
                    else:
                        await update.effective_message.reply_text(
                            f"❌ Luma (text→video) ошибка: {_short_luma_error(js)}"
                        )
                    return False

                if time.time() - started > LUMA_MAX_WAIT_S:
                    await update.effective_message.reply_text("⌛ Luma (text→video): превышено время ожидания.")
                    return False

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Luma error: %s", e)
        await update.effective_message.reply_text("❌ Luma: не удалось запустить/получить видео.")
                            
# ───────── LUMA: TEXT → VIDEO ─────────
    return False
async def _run_sora_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    seconds: int,
    aspect: str,
    tier: str = "free",
) -> bool:
    """Sora 2 video generation (placeholder).

    Integration is prepared, but actual credentials/endpoints may be provided later.
    Returns False if not configured.
    """
    msg = update.effective_message
    if not SORA_ENABLED or not SORA_COMET_BASE_URL or not SORA_COMET_API_KEY:
        await msg.reply_text("⚠️ Sora сейчас не настроена (нет ключей/URL).")
        return False

    # NOTE: This is an intentionally conservative placeholder.
    # Replace with your Comet aggregator endpoint when ready.
    await msg.reply_text("⚠️ Sora интеграция включена, но эндпоинт ещё не задан. Добавь вызов Comet API.")
    return False
def _is_luma_ip_error(obj: dict) -> bool:
    fr = (obj.get("failure_reason") or "")
    fr2 = (obj.get("error") or "")
    txt = f"{fr} {fr2}".lower()
    return ("contains ip" in txt) or ("intellectual property" in txt)

def _short_luma_error(obj: dict) -> str:
    fr = obj.get("failure_reason") or obj.get("message") or obj.get("error") or ""
    fr = str(fr).strip()
    if len(fr) > 400:
        fr = fr[:400].rstrip() + "…"
    return fr or "unknown error"


async def _run_luma_image2video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    image_url: str,
    prompt: str,
    aspect: str,
):
    """
    Luma: IMAGE → VIDEO (оживление фото).
    Использует /generations + keyframes (frame0=image).
    """
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)

    msg = update.effective_message
    chat_id = update.effective_chat.id

    if not LUMA_API_KEY:
        await msg.reply_text("⚠️ Luma: не настроен LUMA_API_KEY.")
        return

    base_timeout = 60.0
    prompt_clean = (prompt or "").strip()
    aspect_ratio = _normalize_luma_aspect(aspect)

    try:
        async with httpx.AsyncClient(timeout=base_timeout, follow_redirects=True) as client:
            base = await _pick_luma_base(client)
            create_url = f"{base}{LUMA_CREATE_PATH}"

            headers = {
                "Authorization": f"Bearer {LUMA_API_KEY}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            payload = {
                "model": (LUMA_MODEL or "ray-2"),
                "prompt": prompt_clean,
                "aspect_ratio": aspect_ratio,
                "keyframes": {
                    "frame0": {
                        "type": "image",
                        "url": (image_url or "").strip(),
                    }
                },
            }

            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code >= 400:
                txt = (r.text or "")[:1200]
                await msg.reply_text(
                    "⚠️ Luma (image→video) отклонила задачу.\n"
                    f"Код: {r.status_code}\n"
                    f"Ответ:\n`{txt}`",
                    parse_mode="Markdown",
                )
                return

            try:
                gen = r.json() or {}
            except Exception:
                gen = {}

            gen_id = gen.get("id") or gen.get("generation_id")
            if not gen_id:
                snippet = (json.dumps(gen, ensure_ascii=False) if gen else r.text)[:1200]
                await msg.reply_text(
                    "⚠️ Luma: не вернула id генерации.\n"
                    f"Ответ сервера:\n`{snippet}`",
                    parse_mode="Markdown",
                )
                return

            await msg.reply_text("⏳ Luma: оживляю фото…")

            status_url = f"{base}{LUMA_STATUS_PATH}".format(id=gen_id)
            started = time.time()

            while True:
                rs = await client.get(status_url, headers=headers)
                try:
                    js = rs.json() or {}
                except Exception:
                    js = {}

                st = (js.get("state") or js.get("status") or "").lower()

                if st in ("completed", "succeeded", "finished", "ready"):
                    url = None
                    assets = js.get("assets")

                    def _extract_urls_from_assets(a):
                        urls = []
                        if isinstance(a, str):
                            if a.startswith("http"):
                                urls.append(a)
                        elif isinstance(a, dict):
                            for v in a.values():
                                urls.extend(_extract_urls_from_assets(v))
                        elif isinstance(a, (list, tuple)):
                            for item in a:
                                urls.extend(_extract_urls_from_assets(item))
                        return urls

                    candidates = []
                    if assets is not None:
                        candidates.extend(_extract_urls_from_assets(assets))

                    for k in ("video", "video_url", "videoUrl"):
                        v = js.get(k)
                        if isinstance(v, str) and v.startswith("http"):
                            candidates.append(v)

                    for u in candidates:
                        if isinstance(u, str) and u.startswith("http"):
                            url = u
                            break

                    if not url:
                        log.error("Luma: completed but no video URL: %s", js)
                        await msg.reply_text("❌ Luma: ответ пришёл без ссылки на видео.")
                        return

                    try:
                        v = await client.get(url, timeout=120.0)
                        v.raise_for_status()
                        bio = BytesIO(v.content)
                        bio.name = "luma_image2video.mp4"
                        await context.bot.send_video(
                            chat_id=chat_id,
                            video=bio,
                            supports_streaming=True,
                        )
                    except Exception as e:
                        log.exception("Luma download/send error: %s", e)
                        await msg.reply_text("⚠️ Luma: ошибка при скачивании/отправке видео.")
                    return

                if st in ("failed", "error"):
                    if _is_luma_ip_error(js):
                        await msg.reply_text(
                            "❌ Luma отклонила запрос из-за IP (защищённый персонаж/бренд в тексте).\n"
                            "Переформулируй без названий (например: «плюшевый медвежонок…») и попробуй ещё раз."
                        )
                    else:
                        await msg.reply_text(f"❌ Luma (image→video) ошибка: {_short_luma_error(js)}")
                    return

                if time.time() - started > LUMA_MAX_WAIT_S:
                    await msg.reply_text("⌛ Luma (image→video): превышено время ожидания.")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Luma image2video error: %s", e)
        await msg.reply_text("❌ Luma: не удалось запустить/получить видео.")
            
async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.voice:
            return
        vf = await update.message.voice.get_file()
        bio = BytesIO(await vf.download_as_bytearray())
        bio.seek(0)
        setattr(bio, "name", f"voice.ogg")
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        text = await transcribe_audio(bio, "voice.ogg")
        if not text:
            await update.effective_message.reply_text("Не удалось распознать речь.")
            return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_voice error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Ошибка при обработке voice.")

async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.audio:
            return
        af = await update.message.audio.get_file()
        filename = update.message.audio.file_name or "audio.mp3"
        bio = BytesIO(await af.download_as_bytearray())
        bio.seek(0)
        setattr(bio, "name", filename)
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        text = await transcribe_audio(bio, filename)
        if not text:
            await update.effective_message.reply_text("Не удалось распознать речь из аудио.")
            return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_audio error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Ошибка при обработке аудио.")


# ───────── Обработчик ошибок PTB ─────────
async def on_error(update: object, context_: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error: %s", context_.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("Упс, произошла ошибка. Я уже разбираюсь.")
    except Exception:
        pass


# ───────── Роутеры для текстовых кнопок/режимов ─────────
async def on_btn_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_engines(update, context)

async def on_btn_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_balance(update, context)

async def on_btn_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = _plans_overview_text(user_id)
    await update.effective_message.reply_text(text, reply_markup=plans_root_kb())

async def on_mode_school_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "🎓 *Учёба*\n"
        "Помогу: конспекты из PDF/EPUB/DOCX/TXT, разбор задач пошагово, эссе/рефераты, мини-квизы.\n\n"
        "_Быстрые действия:_\n"
        "• Разобрать PDF → конспект\n"
        "• Сократить в шпаргалку\n"
        "• Объяснить тему с примерами\n"
        "• План ответа / презентации"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown")

async def on_mode_work_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "💼 *Работа*\n"
        "Письма/брифы/резюме/аналитика, ToDo/планы, сводные таблицы из документов.\n"
        "Для архитектора/дизайнера/проектировщика — структурирование ТЗ, чек-листы стадий, "
        "сводные таблицы листов, пояснительные записки.\n\n"
        "_Гибриды:_ GPT-5 (текст/логика) + Images (иллюстрации) + Luma/Runway (клипы/мокапы).\n\n"
        "_Быстрые действия:_\n"
        "• Сформировать бриф/ТЗ\n"
        "• Свести требования в таблицу\n"
        "• Сгенерировать письмо/резюме\n"
        "• Черновик презентации"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown")

async def on_mode_fun_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "🔥 *Развлечения*\n"
        "Фото-мастерская: удалить/заменить фон, добавить/убрать объект/человека, outpaint, "
        "*оживление старых фото*.\n"
        "Видео: Luma/Runway — клипы под Reels/Shorts; *Reels по смыслу из цельного видео* "
        "(умная нарезка), авто-таймкоды. Мемы/квизы.\n\n"
        "Выбери действие ниже:"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown", reply_markup=_fun_quick_kb())

# ───── Клавиатура «Развлечения» с новыми кнопками ─────
def _fun_quick_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🎭 Идеи для досуга", callback_data="fun:ideas")],
        [InlineKeyboardButton("🎬 Сценарий шорта", callback_data="fun:storyboard")],
        [InlineKeyboardButton("🎮 Игры/квиз",       callback_data="fun:quiz")],
        # Новые ключевые кнопки
        [
            InlineKeyboardButton("🪄 Оживить старое фото", callback_data="fun:revive"),
            InlineKeyboardButton("🎬 Reels из длинного видео", callback_data="fun:smartreels"),
        ],
        [
            InlineKeyboardButton("🎥 Runway",      callback_data="fun:clip"),
            InlineKeyboardButton("🎨 Midjourney",  callback_data="fun:img"),
            InlineKeyboardButton("🔊 STT/TTS",     callback_data="fun:speech"),
        ],
        [InlineKeyboardButton("📝 Свободный запрос", callback_data="fun:free")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="fun:back")],
    ]
    return InlineKeyboardMarkup(rows)
    if SORA_ENABLED:
        rows.append([InlineKeyboardButton("✨ Sora", callback_data="engine:sora")])


# ───────── Нормализация duration для Runway/Comet (image_to_video) ─────────
def _normalize_runway_duration_for_comet(seconds: int | float | None) -> int:
    """
    Comet/Runway принимает строго 5 или 10 секунд.
    Требование: 7–9 секунд => 10, всё остальное => 5.
    """
    try:
        d = int(round(float(seconds or 0)))
    except Exception:
        d = 0

    if d == 10 or (7 <= d <= 9):
        return 10
    return 5

# ───────── Оживление фото: универсальный пайплайн (Runway / Kling / Luma) ─────────

async def revive_old_photo_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    engine: str | None = None,
):
    """
    Универсальный пайплайн оживления фото.

    1) Берём последнее фото из _LAST_ANIM_PHOTO.
    2) Если движок не выбран — показываем меню выбора (Runway/Kling/Luma).
    3) Если выбран движок — считаем цену и запускаем соответствующий backend.
    """
    msg = update.effective_message
    user_id = update.effective_user.id

    photo_info = _LAST_ANIM_PHOTO.get(user_id) or {}
    img_bytes = photo_info.get("bytes")
    image_url = (photo_info.get("url") or "").strip()

    if not img_bytes:
        await msg.reply_text(
            "Сначала пришли фото (желательно портрет), "
            "а потом нажми «🪄 Оживить старое фото» или кнопку под фотографией."
        )
        return True

    # параметры (пришли из on_photo через context.user_data["revive_photo"])
    rp = context.user_data.get("revive_photo") or {}
    dur = int(rp.get("duration") or RUNWAY_DURATION_S or 5)
    asp = (rp.get("aspect") or RUNWAY_RATIO or "720:1280")
    prompt = (rp.get("prompt") or "").strip()

    # шаг 1: выбор движка
    if not engine:
        await msg.reply_text("Выбери движок для оживления фото:", reply_markup=revive_engine_kb())
        return True

    engine = engine.lower().strip()

    # --- готовим функции, которые будем отдавать в биллинг ---
    async def _go_runway():
        # Runway/Comet требует публичный URL картинки
        if not image_url or not image_url.startswith("http"):
            await msg.reply_text(
                "Для Runway нужен публичный URL изображения (Telegram file_path). "
                "Пришли фото ещё раз."
            )
            return
        await _run_runway_animate_photo(update, context, image_url, prompt, dur, asp)

    async def _go_kling():
        await _run_kling_animate_photo(update, context, img_bytes, prompt, dur, asp)

    async def _go_luma():
        if not image_url or not image_url.startswith("http"):
            await msg.reply_text(
                "Для Luma нужен публичный URL изображения (Telegram file_path). "
                "Пришли фото ещё раз."
            )
            return
        await _run_luma_image2video(update, context, image_url, prompt, asp)

    # стоимость (черновая)
    est_runway = max(1.0, float(RUNWAY_UNIT_COST_USD or 1.0) * (dur / max(1, int(RUNWAY_DURATION_S or 5))))
    est_kling  = max(1.0, float(globals().get("KLING_UNIT_COST_USD", RUNWAY_UNIT_COST_USD) or 1.0))
    est_luma   = max(1.0, float(globals().get("LUMA_UNIT_COST_USD", RUNWAY_UNIT_COST_USD) or 1.0))

    if engine == "runway":
        await _try_pay_then_do(
            update, context, user_id, "runway", est_runway, _go_runway,
            remember_kind="revive_photo",
            remember_payload={"engine": "runway", "duration": dur, "aspect": asp, "prompt": prompt},
        )
        return True

    if engine == "kling":
        await _try_pay_then_do(
            update, context, user_id, "kling", est_kling, _go_kling,
            remember_kind="revive_photo",
            remember_payload={"engine": "kling", "duration": dur, "aspect": asp, "prompt": prompt},
        )
        return True

    if engine == "luma":
        await _try_pay_then_do(
            update, context, user_id, "luma", est_luma, _go_luma,
            remember_kind="revive_photo",
            remember_payload={"engine": "luma", "duration": dur, "aspect": asp, "prompt": prompt},
        )
        return True

    await msg.reply_text("Неизвестный движок оживления. Попробуй ещё раз.")
    return True


# ───── Обработчик быстрых действий «Развлечения» (revive + выбор движка) ─────

async def on_cb_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()

    # action — часть после первого "fun:" или "something:"
    action = data.split(":", 1)[1] if ":" in data else ""

    async def _try_call(*fn_names, **kwargs):
        fn = _pick_first_defined(*fn_names)
        if callable(fn):
            return await fn(update, context, **kwargs)
        return None

    # ---------------------------------------------------------------------
    # Кнопка под фото "✨ оживить фото" (pedit:revive)
    # ---------------------------------------------------------------------
    if data.startswith("pedit:revive"):
        with contextlib.suppress(Exception):
            await q.answer("Оживление фото")
        # показываем выбор движка
        with contextlib.suppress(Exception):
            await q.edit_message_text("Выбери движок для оживления фото:", reply_markup=revive_engine_kb())
        return

    # ---------------------------------------------------------------------
    # Выбор движка оживления: revive_engine:runway / kling / luma
    # ---------------------------------------------------------------------
    if data.startswith("revive_engine:"):
        with contextlib.suppress(Exception):
            await q.answer()
        engine = data.split(":", 1)[1].strip().lower() if ":" in data else ""

        # Важно: запускаем пайплайн и НЕ пытаемся edit-ить старое сообщение дальше
        await revive_old_photo_flow(update, context, engine=engine)
        return

    # ---------------------------------------------------------------------
    # Меню "Развлечения" → оживление
    # ---------------------------------------------------------------------
    if action == "revive":
        with contextlib.suppress(Exception):
            await q.answer("Оживление фото")
        await revive_old_photo_flow(update, context, engine=None)
        return

    # ---------------------------------------------------------------------
    # Остальное — как у тебя было (оставляю структуру)
    # ---------------------------------------------------------------------
    if action == "smartreels":
        if await _try_call("smart_reels_from_video", "video_sense_reels"):
            return
        with contextlib.suppress(Exception):
            await q.answer("Reels из длинного видео")
        await q.edit_message_text(
            "🎬 *Reels из длинного видео*\n"
            "Пришли длинное видео (или ссылку) + тему/ЦА. "
            "Сделаю умную нарезку (hook → value → CTA), субтитры и таймкоды. "
            "Скажи формат: 9:16 или 1:1.",
            parse_mode="Markdown",
            reply_markup=_fun_quick_kb()
        )
        return

    if action == "clip":
        if await _try_call("start_runway_flow", "luma_make_clip", "runway_make_clip"):
            return
        with contextlib.suppress(Exception):
            await q.answer()
        await q.edit_message_text(
            "Запусти /diag_video чтобы проверить ключи Luma/Runway.",
            reply_markup=_fun_quick_kb()
        )
        return

    if action == "img":
        if await _try_call("cmd_img", "midjourney_flow", "images_make"):
            return
        with contextlib.suppress(Exception):
            await q.answer()
        await q.edit_message_text(
            "Введи /img и тему картинки, или пришли рефы.",
            reply_markup=_fun_quick_kb()
        )
        return

    if action == "storyboard":
        if await _try_call("start_storyboard", "storyboard_make"):
            return
        with contextlib.suppress(Exception):
            await q.answer()
        await q.edit_message_text(
            "Напиши тему шорта — накидаю структуру и раскадровку.",
            reply_markup=_fun_quick_kb()
        )
        return

    if action in {"ideas", "quiz", "speech", "free", "back"}:
        with contextlib.suppress(Exception):
            await q.answer()
        await q.edit_message_text(
            "Готов! Напиши задачу или выбери кнопку выше.",
            reply_markup=_fun_quick_kb()
        )
        return

    with contextlib.suppress(Exception):
        await q.answer()


# ───────── Роутеры-кнопки режимов (единая точка входа) ─────────
async def on_btn_study(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fn = globals().get("_send_mode_menu")
    if callable(fn):
        return await fn(update, context, "study")
    return await on_mode_school_text(update, context)

async def on_btn_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fn = globals().get("_send_mode_menu")
    if callable(fn):
        return await fn(update, context, "work")
    return await on_mode_work_text(update, context)

async def on_btn_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fn = globals().get("_send_mode_menu")
    if callable(fn):
        return await fn(update, context, "fun")
    return await on_mode_fun_text(update, context)

# ───────── Позитивный авто-ответ про возможности (текст/голос) ─────────
_CAPS_PATTERN = (
    r"(?is)(умеешь|можешь|делаешь|анализируешь|работаешь|поддерживаешь|умеет ли|может ли)"
    r".{0,120}"
    r"(pdf|epub|fb2|docx|txt|книг|книга|изображен|фото|картин|image|jpeg|png|video|видео|mp4|mov|аудио|audio|mp3|wav)"
)

async def on_capabilities_qa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Да, умею работать с файлами и медиа:\n"
        "• 📄 Документы: PDF/EPUB/FB2/DOCX/TXT — конспект, резюме, извлечение таблиц, проверка фактов.\n"
        "• 🖼 Изображения: анализ/описание, улучшение, фон, разметка, мемы, outpaint.\n"
        "• 🎞 Видео: разбор смысла, таймкоды, *Reels из длинного видео*, идеи/скрипт, субтитры.\n"
        "• 🎧 Аудио/книги: транскрипция, тезисы, план.\n\n"
        "_Подсказки:_ просто загрузите файл или пришлите ссылку + короткое ТЗ. "
        "Для фото — можно нажать «🪄 Оживить старое фото», для видео — «🎬 Reels из длинного видео»."
    )
    await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=_fun_quick_kb())

# ───────── Вспомогательное: взять первую объявленную функцию по имени ─────────
def _pick_first_defined(*names):
    for n in names:
        fn = globals().get(n)
        if callable(fn):
            return fn
    return None


# ───────── Регистрация хендлеров и запуск ─────────
def build_application() -> "Application":
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в переменных окружения.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ───── Команды ─────
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("help",         cmd_help))
    app.add_handler(CommandHandler("examples",     cmd_examples))
    app.add_handler(CommandHandler("engines",      cmd_engines))
    app.add_handler(CommandHandler("plans",        cmd_plans))
    app.add_handler(CommandHandler("balance",      cmd_balance))
    app.add_handler(CommandHandler("set_welcome",  cmd_set_welcome))
    app.add_handler(CommandHandler("show_welcome", cmd_show_welcome))
    app.add_handler(CommandHandler("diag_limits",  cmd_diag_limits))
    app.add_handler(CommandHandler("diag_stt",     cmd_diag_stt))
    app.add_handler(CommandHandler("diag_images",  cmd_diag_images))
    app.add_handler(CommandHandler("diag_video",   cmd_diag_video))
    app.add_handler(CommandHandler("img",          cmd_img))
    app.add_handler(CommandHandler("voice_on",     cmd_voice_on))
    app.add_handler(CommandHandler("voice_off",    cmd_voice_off))

    # ───── Платежи ─────
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    # >>> PATCH START — Handlers wiring (callbacks / media / text) >>>

    # ───── WebApp ─────
    with contextlib.suppress(Exception):
        app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))
    with contextlib.suppress(Exception):
        if hasattr(filters, "WEB_APP_DATA"):
            app.add_handler(MessageHandler(filters.WEB_APP_DATA, on_webapp_data))

    # ───────────────── CALLBACK QUERY HANDLERS ─────────────────
    # ВАЖНО: порядок = от узких к широким

    # 1) Подписка / оплата
    app.add_handler(
        CallbackQueryHandler(
            on_cb_plans,
            pattern=r"^(?:plan:|pay:)$|^(?:plan:|pay:).+"
        )
    )

    # 2) Режимы / подменю
    app.add_handler(
        CallbackQueryHandler(
            on_mode_cb,
            pattern=r"^(?:mode:|act:|school:|work:)"
        )
    )

    # 3) Fun + Photo Edit + Revive (КРИТИЧЕСКИЙ ПАТЧ)
    app.add_handler(
        CallbackQueryHandler(
            on_cb_fun,
            pattern=(
                r"^(?:"
                r"fun:[a-z_]+"
                r"|pedit:revive"
                r"|revive_engine:(?:runway|kling|luma)"
                r")$"
            )
        )
    )

    # 4) Catch-all (ВСЁ ОСТАЛЬНОЕ)
    app.add_handler(
        CallbackQueryHandler(on_cb),
        group=0
    )

    # ───────────────── MEDIA HANDLERS ─────────────────

    # Голос / аудио
    voice_fn = _pick_first_defined("handle_voice", "on_voice", "voice_handler")
    if voice_fn:
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_fn), group=1)

    # Фото
    photo_fn = _pick_first_defined("handle_photo", "on_photo", "photo_handler", "handle_image_message")
    if photo_fn:
        app.add_handler(MessageHandler(filters.PHOTO, photo_fn), group=1)

    # Документы
    doc_fn = _pick_first_defined("handle_doc", "on_document", "handle_document", "doc_handler")
    if doc_fn:
        app.add_handler(MessageHandler(filters.Document.ALL, doc_fn), group=1)

    # Видео
    video_fn = _pick_first_defined("handle_video", "on_video", "video_handler")
    if video_fn:
        app.add_handler(MessageHandler(filters.VIDEO, video_fn), group=1)

    # GIF / animation
    gif_fn = _pick_first_defined("handle_gif", "on_gif", "animation_handler")
    if gif_fn:
        app.add_handler(MessageHandler(filters.ANIMATION, gif_fn), group=1)

    # ───────────────── TEXT BUTTONS ─────────────────
    import re

    BTN_ENGINES = re.compile(r"^\s*(?:🧠\s*)?Движки\s*$")
    BTN_BALANCE = re.compile(r"^\s*(?:💳|🧾)?\s*Баланс\s*$")
    BTN_PLANS   = re.compile(r"^\s*(?:⭐\s*)?Подписка(?:\s*[·•]\s*Помощь)?\s*$")
    BTN_STUDY   = re.compile(r"^\s*(?:🎓\s*)?Уч[её]ба\s*$")
    BTN_WORK    = re.compile(r"^\s*(?:💼\s*)?Работа\s*$")
    BTN_FUN     = re.compile(r"^\s*(?:🔥\s*)?Развлечения\s*$")

    app.add_handler(MessageHandler(filters.Regex(BTN_ENGINES), on_btn_engines), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_BALANCE), on_btn_balance), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_PLANS),   on_btn_plans),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_STUDY),   on_btn_study),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_WORK),    on_btn_work),    group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_FUN),     on_btn_fun),     group=0)

    # ───────────────── CAPABILITIES Q/A ─────────────────
    app.add_handler(
        MessageHandler(filters.Regex(_CAPS_PATTERN), on_capabilities_qa),
        group=1
    )

    # ───────────────── FALLBACK TEXT ─────────────────
    text_fn = _pick_first_defined("handle_text", "on_text", "text_handler", "default_text_handler")
    if text_fn:
        btn_filters = (
            filters.Regex(BTN_ENGINES) |
            filters.Regex(BTN_BALANCE) |
            filters.Regex(BTN_PLANS)   |
            filters.Regex(BTN_STUDY)   |
            filters.Regex(BTN_WORK)    |
            filters.Regex(BTN_FUN)
        )
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND & ~btn_filters, text_fn),
            group=2
        )

    # ───────────────── ERRORS ─────────────────
    err_fn = _pick_first_defined("on_error", "handle_error")
    if err_fn:
        app.add_error_handler(err_fn)

    return app


# ───────── main() ─────────
def main():
    with contextlib.suppress(Exception):
        db_init()
    with contextlib.suppress(Exception):
        db_init_usage()
    with contextlib.suppress(Exception):
        _db_init_prefs()

    app = build_application()

    if USE_WEBHOOK:
        log.info("🚀 WEBHOOK mode. Public URL: %s  Path: %s  Port: %s", PUBLIC_URL, WEBHOOK_PATH, PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH.lstrip("/"),
            webhook_url=f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}",
            secret_token=(WEBHOOK_SECRET or None),
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        log.info("🚀 POLLING mode.")
        with contextlib.suppress(Exception):
            asyncio.get_event_loop().run_until_complete(
                app.bot.delete_webhook(drop_pending_updates=True)
            )
        app.run_polling(
            close_loop=False,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
        )


if __name__ == "__main__":
    main()
# === END PATCH ===


# ================== GPT5 PRO ADDITIONS — STEP 1 ==================
# Language selection (RU/EN) + Welcome + Engine registry stubs
# These are REAL, WORKING additions and will be extended in next steps.

import sqlite3

_DB_LANG = "lang.db"

def _lang_db():
    return sqlite3.connect(_DB_LANG)

def init_lang_db():
    with _lang_db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS user_lang (user_id INTEGER PRIMARY KEY, lang TEXT)")
        c.commit()

def get_user_lang(user_id: int):
    with _lang_db() as c:
        r = c.execute("SELECT lang FROM user_lang WHERE user_id=?", (user_id,)).fetchone()
        return r[0] if r else None

def set_user_lang(user_id: int, lang: str):
    with _lang_db() as c:
        c.execute("INSERT OR REPLACE INTO user_lang(user_id, lang) VALUES (?,?)", (user_id, lang))
        c.commit()

LANG_WELCOME = {
    "ru": "👋 Добро пожаловать в GPT‑5 PRO Bot!\nВыберите движок или напишите запрос.",
    "en": "👋 Welcome to GPT‑5 PRO Bot!\nChoose an engine or type a prompt."
}

ENGINE_REGISTRY = {
    "gemini": {
        "title": "Gemini",
        "desc": "Аналитика, код, сложные рассуждения"
    },
    "midjourney": {
        "title": "Midjourney",
        "desc": "Генерация изображений и дизайна"
    },
    "suno": {
        "title": "Suno",
        "desc": "Музыка и аудио"
    }
}

# ================== END STEP 1 ==================


# ================== GPT5 PRO ADDITIONS — STEP 2 ==================
# Gemini integration via CometAPI (REAL REQUEST LOGIC)

import httpx
import os

COMETAPI_KEY = os.getenv("COMETAPI_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-pro-preview")

async def run_gemini_comet(prompt: str) -> str:
    """
    Gemini text generation via CometAPI.
    """
    if not COMETAPI_KEY:
        raise RuntimeError("COMETAPI_KEY is not set")

    url = f"https://api.cometapi.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    headers = {
        "x-goog-api-key": COMETAPI_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return str(data)

# Engine dispatcher extension
async def dispatch_engine(engine: str, prompt: str):
    if engine == "gemini":
        return await run_gemini_comet(prompt)
    raise RuntimeError(f"Engine not supported yet: {engine}")

# ================== END STEP 2 ==================


# ================== GPT5 PRO ADDITIONS — STEP 3 ==================
# Suno integration via CometAPI (music generation)

import asyncio

SUNO_DEFAULT_MODEL = os.getenv("SUNO_DEFAULT_MODEL", "chirp-auk")

async def run_suno_comet(prompt: str) -> str:
    """
    Generate music via Suno (CometAPI).
    Returns audio URL when ready.
    """
    if not COMETAPI_KEY:
        raise RuntimeError("COMETAPI_KEY is not set")

    submit_url = "https://api.cometapi.com/suno/submit/music"
    headers = {
        "Authorization": f"Bearer {COMETAPI_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "mv": SUNO_DEFAULT_MODEL,
        "gpt_description_prompt": prompt,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(submit_url, headers=headers, json=payload)
        r.raise_for_status()
        task_id = r.json().get("task_id")

        if not task_id:
            raise RuntimeError("Suno task_id not returned")

        # Polling
        for _ in range(40):
            await asyncio.sleep(3)
            s = await client.get(
                f"https://api.cometapi.com/suno/fetch/{task_id}",
                headers=headers,
            )
            data = s.json()
            if data.get("status") == "SUCCESS":
                return data["data"].get("audio_url")

    raise RuntimeError("Suno generation timeout")

# Extend dispatcher
async def dispatch_engine(engine: str, prompt: str):
    if engine == "gemini":
        return await run_gemini_comet(prompt)
    if engine == "suno":
        return await run_suno_comet(prompt)
    raise RuntimeError(f"Engine not supported yet: {engine}")

# ================== END STEP 3 ==================


# ================== GPT5 PRO ADDITIONS — STEP 4 ==================
# Midjourney integration via CometAPI (imagine / fetch / action)

MJ_DEFAULT_MODE = os.getenv("MJ_DEFAULT_MODE", "FAST")

async def mj_imagine(prompt: str) -> str:
    """Submit Midjourney imagine task. Returns task_id."""
    if not COMETAPI_KEY:
        raise RuntimeError("COMETAPI_KEY is not set")

    url = "https://api.cometapi.com/mj/submit/imagine"
    headers = {
        "Authorization": f"Bearer {COMETAPI_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "botType": "MID_JOURNEY",
        "prompt": prompt,
        "accountFilter": {"modes": [MJ_DEFAULT_MODE]},
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        return data.get("task_id")

async def mj_fetch(task_id: str) -> dict:
    """Fetch Midjourney task status and result."""
    url = f"https://api.cometapi.com/mj/task/{task_id}/fetch"
    headers = {"Authorization": f"Bearer {COMETAPI_KEY}"}

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

async def mj_action(task_id: str, custom_id: str) -> str:
    """Perform Midjourney action (U/V/Reroll/Zoom). Returns new task_id."""
    url = "https://api.cometapi.com/mj/submit/action"
    headers = {
        "Authorization": f"Bearer {COMETAPI_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "taskId": task_id,
        "customId": custom_id,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        return data.get("task_id")

# Extend dispatcher
async def dispatch_engine(engine: str, prompt: str):
    if engine == "gemini":
        return await run_gemini_comet(prompt)
    if engine == "suno":
        return await run_suno_comet(prompt)
    if engine == "midjourney":
        return await mj_imagine(prompt)
    raise RuntimeError(f"Engine not supported yet: {engine}")

# ================== END STEP 4 ==================


# ================== GPT5 PRO ADDITIONS — STEP 5 (FINAL) ==================
# Final unification: single dispatcher, language-first guard, welcome hooks
# NOTE: Hooks are designed to be connected to existing Telegram handlers.

# ---- Unified engine dispatcher ----
async def dispatch_engine(engine: str, prompt: str):
    if engine == "gemini":
        return await run_gemini_comet(prompt)
    if engine == "suno":
        return await run_suno_comet(prompt)
    if engine == "midjourney":
        return await mj_imagine(prompt)
    raise RuntimeError(f"Unknown engine: {engine}")

# ---- Language-first guard ----
def require_language(user_id: int) -> bool:
    """Return True if language already selected."""
    return get_user_lang(user_id) is not None

# ---- Welcome text provider ----
def get_welcome_text(lang: str) -> str:
    if lang == "ru":
        return (
            "👋 Добро пожаловать в GPT-5 PRO Bot!\n\n"
            "🧠 Gemini — аналитика, код, сложные рассуждения\n"
            "🎨 Midjourney — изображения и дизайн\n"
            "🎵 Suno — музыка и аудио\n\n"
            "Выберите движок или просто напишите запрос."
        )
    return (
        "👋 Welcome to GPT-5 PRO Bot!\n\n"
        "🧠 Gemini — analysis & reasoning\n"
        "🎨 Midjourney — images & design\n"
        "🎵 Suno — music generation\n\n"
        "Choose an engine or type a prompt."
    )

# ================== END FINAL STEP ==================
