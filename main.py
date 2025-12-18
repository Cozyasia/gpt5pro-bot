# -*- coding: utf-8 -*-
import os
import re
import json
import time
import uuid
import math
import asyncio
import logging
import sqlite3
import threading
from io import BytesIO
from datetime import datetime, timedelta, timezone

import httpx

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt5pro")

# ============================================================
# ENV HELPERS
# ============================================================

def _env(key: str, default=None):
    v = os.getenv(key)
    return v if v not in (None, "") else default

def _env_int(key: str, default: int):
    try:
        return int(float(os.getenv(key, default)))
    except Exception:
        return default

def _env_float(key: str, default: float):
    try:
        return float(os.getenv(key, default))
    except Exception:
        return default

# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

# ============================================================
# HTTP / COMET
# ============================================================

HTTP_TIMEOUT = _env_float("HTTP_TIMEOUT", 60.0)
VIDEO_POLL_DELAY_S = _env_int("VIDEO_POLL_DELAY_S", 5)

COMET_API_KEY = (
    _env("COMET_API_KEY")
    or _env("COMETAPI_KEY")
    or ""
).strip()

COMET_BASE_URL = (_env("COMET_BASE_URL", "https://api.cometapi.com")).rstrip("/")

# ============================================================
# DATABASE
# ============================================================

DB_PATH = _env("DB_PATH", "bot.db")
_db_lock = threading.Lock()

def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

_DB = db()

def db_exec(sql: str, params=()):
    with _db_lock:
        cur = _DB.cursor()
        cur.execute(sql, params)
        _DB.commit()
        return cur

def db_init():
    db_exec("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    db_exec(
        "CREATE TABLE IF NOT EXISTS spend (user_id INTEGER, engine TEXT, usd REAL, ts INTEGER)"
    )
    db_exec(
        "CREATE TABLE IF NOT EXISTS subs (user_id INTEGER PRIMARY KEY, tier TEXT, ts INTEGER)"
    )

db_init()

def kv_get(key: str, default=None):
    row = db_exec("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return row["v"] if row else default

def kv_set(key: str, value: str):
    db_exec("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (key, value))

# ============================================================
# LANGUAGE SYSTEM
# ============================================================

LANGS = {
    "ru": "Русский",
    "be": "Белорусский",
    "uk": "Украинский",
    "de": "Deutsch",
    "en": "English",
    "fr": "Français",
    "th": "ไทย",
}

DEFAULT_LANG = _env("DEFAULT_LANG", "ru")

def get_lang(user_id: int) -> str:
    return kv_get(f"lang:{user_id}", DEFAULT_LANG)

def set_lang(user_id: int, lang: str):
    if lang in LANGS:
        kv_set(f"lang:{user_id}", lang)

# ============================================================
# I18N BASE
# ============================================================

I18N = {
    "ru": {
        "choose_lang": "🌍 Выберите язык",
        "lang_set": "Язык установлен",
        "menu": "Главное меню",
        "btn_video": "🎞 Создать видео",
        "btn_photo": "🖼 Оживить фото",
        "btn_help": "❓ Помощь",
    },
    "en": {
        "choose_lang": "🌍 Choose language",
        "lang_set": "Language set",
        "menu": "Main menu",
        "btn_video": "🎞 Create video",
        "btn_photo": "🖼 Animate photo",
        "btn_help": "❓ Help",
    },
}

def t(user_id: int, key: str) -> str:
    lang = get_lang(user_id)
    return I18N.get(lang, I18N["ru"]).get(key, key)

def system_prompt_for(lang: str) -> str:
    return {
        "ru": "Отвечай на русском языке.",
        "be": "Адказвай па-беларуску.",
        "uk": "Відповідай українською.",
        "de": "Antworte auf Deutsch.",
        "en": "Answer in English.",
        "fr": "Réponds en français.",
        "th": "ตอบเป็นภาษาไทย",
    }.get(lang, "Отвечай на русском языке.")

# ============================================================
# STATE
# ============================================================

_pending_actions = {}

def _new_aid():
    return uuid.uuid4().hex

# === END PART 1 ===
