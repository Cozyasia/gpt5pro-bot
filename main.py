
# ===================== PATCH: MENU+LANG+FREE_CHAT =====================
# Injected patch to ensure:
# 1) Explicit mode routing for Study/Work/Fun/Free Chat
# 2) user_lang propagation to all replies and LLM calls
# 3) Free Chat works only when mode == 'free'
# 4) MessageHandler(TEXT) placed AFTER menu handlers
# =====================================================================

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
# âââââââââ TTS imports âââââââââ
import contextlib  # ÑÐ¶Ðµ Ñ ÑÐµÐ+/-Ñ Ð²ÑÑÐµ ÐµÑÑÑ, Ð´ÑÐ+/-Ð»Ð¸ÑÐ¾Ð²Ð°ÑÑ ÐÐ Ð½Ð°Ð´Ð¾, ÐµÑÐ»Ð¸ Ð¸Ð¼Ð¿Ð¾ÑÑ ÑÑÐ¾Ð¸Ñ

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

# âââââââââ LOGGING âââââââââ
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")


# âââââââââ ENV âââââââââ

def _env_float(name: str, default: float) -> float:
    """
    ÐÐµÐ·Ð¾Ð¿Ð°ÑÐ½Ð¾Ðµ ÑÑÐµÐ½Ð¸Ðµ float Ð¸Ð· ENV:
    - Ð¿Ð¾Ð´Ð´ÐµÑÐ¶Ð¸Ð²Ð°ÐµÑ Ð¸ '4,99', Ð¸ '4.99'
    - Ð¿ÑÐ¸ Ð¾ÑÐ¸Ð+/-ÐºÐµ Ð²Ð¾Ð·Ð²ÑÐ°ÑÐ°ÐµÑ default
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
OPENAI_BASE_URL  = os.environ.get("OPENAI_BASE_URL", "").strip()  # OpenRouter Ð¸Ð»Ð¸ ÑÐ²Ð¾Ð¹ Ð¿ÑÐ¾ÐºÑÐ¸ Ð´Ð»Ñ ÑÐµÐºÑÑÐ°
OPENAI_MODEL     = os.environ.get("OPENAI_MODEL", "openai/gpt-4o-mini").strip()

OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "").strip()

USE_WEBHOOK      = os.environ.get("USE_WEBHOOK", "1").lower() in ("1", "true", "yes", "on")
WEBHOOK_PATH     = os.environ.get("WEBHOOK_PATH", "/tg").strip()
WEBHOOK_SECRET   = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()

BANNER_URL       = os.environ.get("BANNER_URL", "").strip()
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "").strip()

# ÐÐ+/-ÑÐ¸Ð¹ ÐºÐ»ÑÑ CometAPI (Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÑÑÑ Ð¸ Ð´Ð»Ñ Kling, Ð¸ Ð´Ð»Ñ Runway)
COMETAPI_KEY     = os.environ.get("COMETAPI_KEY", "").strip()

# ÐÐÐÐÐ: Ð¿ÑÐ¾Ð²Ð°Ð¹Ð´ÐµÑ ÑÐµÐºÑÑÐ° (openai / openrouter Ð¸ Ñ.Ð¿.)
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

# Images (ÑÐ¾Ð»Ð+/-ÑÐº â OpenAI Images)
OPENAI_IMAGE_KEY    = os.environ.get("OPENAI_IMAGE_KEY", "").strip() or OPENAI_API_KEY
IMAGES_BASE_URL     = (os.environ.get("OPENAI_IMAGE_BASE_URL", "").strip() or "https://api.openai.com/v1")
IMAGES_MODEL        = "gpt-image-1"

# âââââââââ Runway / CometAPI (ÑÐ½Ð¸ÑÐ¸ÑÐ¸ÑÐ¾Ð²Ð°Ð½Ð½Ð°Ñ ÐºÐ¾Ð½ÑÐ¸Ð³ÑÑÐ°ÑÐ¸Ñ) âââââââââ

# API-ÐºÐ»ÑÑ:
# 1) ÐÑÐ»Ð¸ RUNWAY_API_KEY ÑÐºÐ°Ð·Ð°Ð½ â Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÐ¼ Ð¿ÑÑÐ¼Ð¾Ð¹ Runway (ÑÐµÐºÐ¾Ð¼ÐµÐ½Ð´ÑÐµÑÑÑ Ð´Ð»Ñ imageâvideo)
# 2) ÐÑÐ»Ð¸ Ð½ÐµÑ â Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÐ¼ CometAPI_KEY (ÑÐ¾Ð²Ð¼ÐµÑÑÐ¸Ð¼Ð¾ÑÑÑ Ñ ÑÐ²Ð¾Ð¸Ð¼ ÑÐµÐºÑÑÐ¸Ð¼ Ð¿ÑÐ¾ÐµÐºÑÐ¾Ð¼)
RUNWAY_API_KEY = (os.environ.get("RUNWAY_API_KEY", "").strip() or COMETAPI_KEY)

# ÐÐ¾Ð´ÐµÐ»Ñ (Ð¿Ð¾ ÑÐ¼Ð¾Ð»ÑÐ°Ð½Ð¸Ñ Gen-3a Turbo)
RUNWAY_MODEL = os.environ.get("RUNWAY_MODEL", "gen3a_turbo").strip()

# Ð ÐµÐºÐ¾Ð¼ÐµÐ½Ð´ÑÐµÐ¼ÑÐ¹ ratio â ÑÐºÐ°Ð·ÑÐ²Ð°ÐµÐ¼ Ð² Ð²Ð¸Ð´Ðµ "1280:720", "720:1280", "960:960"
RUNWAY_RATIO = os.environ.get("RUNWAY_RATIO", "1280:720").strip()

# ÐÐ»Ð¸ÑÐµÐ»ÑÐ½Ð¾ÑÑÑ video default
RUNWAY_DURATION_S = int((os.environ.get("RUNWAY_DURATION_S") or "5").strip() or "5")

# ÐÐ°ÐºÑÐ¸Ð¼Ð°Ð»ÑÐ½Ð¾Ðµ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ðµ ÑÐµÐ·ÑÐ»ÑÑÐ°ÑÐ° (ÑÐµÐº)
RUNWAY_MAX_WAIT_S = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "1200").strip() or "1200")

# ÐÐ°Ð·Ð° API:
# ÐÐÐÐÐ: Runway imageâvideo ÐºÐ¾ÑÑÐµÐºÑÐ½Ð¾ ÑÐ°Ð+/-Ð¾ÑÐ°ÐµÑ Ð¢ÐÐÐ¬ÐÐ ÑÐµÑÐµÐ· Ð¾ÑÐ¸ÑÐ¸Ð°Ð»ÑÐ½ÑÑ Ð+/-Ð°Ð·Ñ:
#   https://api.runwayml.com
# CometAPI Ð¾ÑÑÐ°ÑÑÑÑ ÐºÐ°Ðº fallback (ÑÐµÑÐµÐ· env), Ð½Ð¾ Ð¿Ð¾ ÑÐ¼Ð¾Ð»ÑÐ°Ð½Ð¸Ñ ÑÑÐ°Ð²Ð¸Ð¼ Ð¾ÑÐ¸ÑÐ¸Ð°Ð»ÑÐ½ÑÐ¹ URL
RUNWAY_BASE_URL = (
    os.environ.get("RUNWAY_BASE_URL", "https://api.runwayml.com")
        .strip()
        .rstrip("/")
)

# ÐÐ½Ð´Ð¿Ð¾Ð¸Ð½ÑÑ Runway (Ð¾ÑÐ¸ÑÐ¸Ð°Ð»ÑÐ½ÑÐµ Ð¸ ÑÐ¾Ð²Ð¼ÐµÑÑÐ¸Ð¼ÑÐµ)
RUNWAY_IMAGE2VIDEO_PATH = "/v1/image_to_video"      # Ð½Ð¾Ð²ÑÐ¹ ÐºÐ¾ÑÑÐµÐºÑÐ½ÑÐ¹ endpoint Runway
RUNWAY_TEXT2VIDEO_PATH  = "/v1/text_to_video"       # ÑÐ½Ð¸Ð²ÐµÑÑÐ°Ð»ÑÐ½ÑÐ¹ endpoint Runway
RUNWAY_STATUS_PATH      = "/v1/tasks/{id}"          # ÐµÐ´Ð¸Ð½ÑÐ¹ ÑÑÐ°ÑÑÑÐ½ÑÐ¹ endpoint Runway

# ÐÐµÑÑÐ¸Ñ Runway API (Ð¾Ð+/-ÑÐ·Ð°ÑÐµÐ»ÑÐ½Ð¾!)
RUNWAY_API_VERSION = os.environ.get("RUNWAY_API_VERSION", "2024-11-06").strip()

# âââââââââ Luma âââââââââ

LUMA_API_KEY     = os.environ.get("LUMA_API_KEY", "").strip()

# ÐÑÐµÐ³Ð´Ð° Ð³Ð°ÑÐ°Ð½ÑÐ¸ÑÑÐµÐ¼ Ð½ÐµÐ¿ÑÑÑÐ¾Ð¹ model/aspect, Ð´Ð°Ð¶Ðµ ÐµÑÐ»Ð¸ Ð² ENV Ð¿ÑÑÑÐ°Ñ ÑÑÑÐ¾ÐºÐ°
_LUMA_MODEL_ENV  = (os.environ.get("LUMA_MODEL") or "").strip()
LUMA_MODEL       = _LUMA_MODEL_ENV or "ray-2"

_LUMA_ASPECT_ENV = (os.environ.get("LUMA_ASPECT") or "").strip()
LUMA_ASPECT      = _LUMA_ASPECT_ENV or "16:9"

LUMA_DURATION_S  = int((os.environ.get("LUMA_DURATION_S") or "5").strip() or 5)

# ÐÐ°Ð·Ð° ÑÐ¶Ðµ ÑÐ¾Ð´ÐµÑÐ¶Ð¸Ñ /dream-machine/v1 â Ð´Ð°Ð»ÑÑÐµ Ð´Ð¾Ð+/-Ð°Ð²Ð»ÑÐµÐ¼ /generations
LUMA_BASE_URL    = (
    os.environ.get("LUMA_BASE_URL", "https://api.lumalabs.ai/dream-machine/v1")
    .strip()
    .rstrip("/")
)
LUMA_CREATE_PATH = "/generations"
LUMA_STATUS_PATH = "/generations/{id}"

# ÐÐ°ÐºÑÐ¸Ð¼Ð°Ð»ÑÐ½ÑÐ¹ ÑÐ°Ð¹Ð¼Ð°ÑÑ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ñ Luma
LUMA_MAX_WAIT_S  = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)

# Luma Images (Ð¾Ð¿ÑÐ¸Ð¾Ð½Ð°Ð»ÑÐ½Ð¾: ÐµÑÐ»Ð¸ Ð½ÐµÑ â Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÐ¼ OpenAI Images ÐºÐ°Ðº ÑÐ¾Ð»Ð+/-ÑÐº)
LUMA_IMG_BASE_URL = os.environ.get("LUMA_IMG_BASE_URL", "").strip().rstrip("/")
LUMA_IMG_MODEL    = os.environ.get("LUMA_IMG_MODEL", "imagine-image-1").strip()

# Ð¤Ð¾Ð»Ð+/-ÑÐºÐ¸ Luma
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

# âââââââââ Kling (Ð½Ð¾Ð²ÑÐ¹ Ð²Ð¸Ð´ÐµÐ¾Ð´Ð²Ð¸Ð¶Ð¾Ðº ÑÐµÑÐµÐ· CometAPI) âââââââââ

KLING_BASE_URL   = os.environ.get("KLING_BASE_URL", "https://api.cometapi.com").strip().rstrip("/")
KLING_MODEL_NAME = os.environ.get("KLING_MODEL_NAME", "kling-v1-6").strip()
KLING_MODE       = os.environ.get("KLING_MODE", "std").strip()
KLING_ASPECT     = os.environ.get("KLING_ASPECT", "9:16").strip()
KLING_DURATION_S = int((os.environ.get("KLING_DURATION_S") or "5").strip() or 5)
KLING_MAX_WAIT_S = int((os.environ.get("KLING_MAX_WAIT_S") or "900").strip() or 900)
KLING_UNIT_COST_USD = float((os.environ.get("KLING_UNIT_COST_USD") or "0.80").replace(",", ".") or "0.80")

# ÐÐ+/-ÑÐ¸Ð¹ Ð¸Ð½ÑÐµÑÐ²Ð°Ð» Ð¼ÐµÐ¶Ð´Ñ Ð¾Ð¿ÑÐ¾ÑÐ°Ð¼Ð¸ ÑÑÐ°ÑÑÑÐ° Ð·Ð°Ð´Ð°Ñ Ð²Ð¸Ð´ÐµÐ¾
VIDEO_POLL_DELAY_S = _env_float("VIDEO_POLL_DELAY_S", 6.0)

# âââââââââ ÐÐÐ¨Ð / ÐÐÐÐÐÐÐ¬ÐÐÐ Ð¡ÐÐ¡Ð¢ÐÐ¯ÐÐÐ âââââââââ

# ÐÐ¾ÑÐ»ÐµÐ´Ð½ÐµÐµ ÑÐ¾ÑÐ¾ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ Ð´Ð»Ñ Ð°Ð½Ð¸Ð¼Ð°ÑÐ¸Ð¸ (Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ñ)
# user_id -> {"bytes": b"...", "url": "https://..."}
_LAST_ANIM_PHOTO: dict[int, dict] = {}
# âââââââââ Runway ÑÐµÑÐµÐ· CometAPI âââââââââ

# ÐÐ»ÑÑ Ð+/-ÐµÑÑÐ¼ Ð¸Ð· RUNWAY_API_KEY, Ð° ÐµÑÐ»Ð¸ Ð¾Ð½ Ð¿ÑÑÑÐ¾Ð¹ â Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÐ¼ Ð¾Ð+/-ÑÐ¸Ð¹ COMETAPI_KEY
RUNWAY_API_KEY     = (os.environ.get("RUNWAY_API_KEY", "").strip() or COMETAPI_KEY)

# ÐÐ¾Ð´ÐµÐ»Ñ Runway, ÐºÐ¾ÑÐ¾ÑÐ°Ñ Ð¸Ð´ÑÑ ÑÐµÑÐµÐ· CometAPI
RUNWAY_MODEL       = os.environ.get("RUNWAY_MODEL", "gen3a_turbo").strip()

# Ð ÐµÐºÐ¾Ð¼ÐµÐ½Ð´ÑÐµÐ¼ÑÐ¹ ÑÐ¾ÑÐ¼Ð°Ñ â ÑÐ°Ð·ÑÐµÑÐµÐ½Ð¸Ðµ, ÐºÐ°Ðº Ð² Ð½Ð¾Ð²Ð¾Ð¹ Ð²ÐµÑÑÐ¸Ð¸ API (ÑÐ¼. docs Runway)
# ÐÐ¾Ð¶Ð½Ð¾ Ð·Ð°Ð´Ð°ÑÑ "1280:720", "720:1280", "960:960" Ð¸ Ñ.Ð¿.
RUNWAY_RATIO       = os.environ.get("RUNWAY_RATIO", "1280:720").strip()

RUNWAY_DURATION_S  = int((os.environ.get("RUNWAY_DURATION_S") or "5").strip() or 5)
RUNWAY_MAX_WAIT_S  = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "900").strip() or 900)

# ÐÐ°Ð·Ð° Ð¸Ð¼ÐµÐ½Ð½Ð¾ CometAPI (Ð° Ð½Ðµ api.dev.runwayml.com)
RUNWAY_BASE_URL          = (os.environ.get("RUNWAY_BASE_URL", "https://api.cometapi.com").strip().rstrip("/"))

# ÐÐ½Ð´Ð¿Ð¾Ð¸Ð½ÑÑ Runway ÑÐµÑÐµÐ· CometAPI
RUNWAY_IMAGE2VIDEO_PATH  = "/runwayml/v1/image_to_video"
RUNWAY_TEXT2VIDEO_PATH   = "/runwayml/v1/text_to_video"
RUNWAY_STATUS_PATH       = "/runwayml/v1/tasks/{id}"

# ÐÐµÑÑÐ¸Ñ Runway API â Ð¾Ð+/-ÑÐ·Ð°ÑÐµÐ»ÑÐ½Ð¾ 2024-11-06 (ÐºÐ°Ðº Ð² Ð¸Ñ Ð´Ð¾ÐºÐµ)
RUNWAY_API_VERSION = os.environ.get("RUNWAY_API_VERSION", "2024-11-06").strip()

# âââââââââ Luma âââââââââ

LUMA_API_KEY     = os.environ.get("LUMA_API_KEY", "").strip()

# ÐÑÐµÐ³Ð´Ð° Ð³Ð°ÑÐ°Ð½ÑÐ¸ÑÑÐµÐ¼ Ð½ÐµÐ¿ÑÑÑÐ¾Ð¹ model/aspect, Ð´Ð°Ð¶Ðµ ÐµÑÐ»Ð¸ Ð² ENV Ð¿ÑÑÑÐ°Ñ ÑÑÑÐ¾ÐºÐ°
_LUMA_MODEL_ENV  = (os.environ.get("LUMA_MODEL") or "").strip()
LUMA_MODEL       = _LUMA_MODEL_ENV or "ray-2"

_LUMA_ASPECT_ENV = (os.environ.get("LUMA_ASPECT") or "").strip()
LUMA_ASPECT      = _LUMA_ASPECT_ENV or "16:9"

LUMA_DURATION_S  = int((os.environ.get("LUMA_DURATION_S") or "5").strip() or 5)

# ÐÐ°Ð·Ð° ÑÐ¶Ðµ ÑÐ¾Ð´ÐµÑÐ¶Ð¸Ñ /dream-machine/v1 â Ð´Ð°Ð»ÑÑÐµ Ð´Ð¾Ð+/-Ð°Ð²Ð»ÑÐµÐ¼ /generations
LUMA_BASE_URL    = (
    os.environ.get("LUMA_BASE_URL", "https://api.lumalabs.ai/dream-machine/v1")
    .strip()
    .rstrip("/")
)
LUMA_CREATE_PATH = "/generations"
LUMA_STATUS_PATH = "/generations/{id}"

# ÐÐ°ÐºÑÐ¸Ð¼Ð°Ð»ÑÐ½ÑÐ¹ ÑÐ°Ð¹Ð¼Ð°ÑÑ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ñ Luma
LUMA_MAX_WAIT_S  = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)

# Luma Images (Ð¾Ð¿ÑÐ¸Ð¾Ð½Ð°Ð»ÑÐ½Ð¾: ÐµÑÐ»Ð¸ Ð½ÐµÑ â Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÐ¼ OpenAI Images ÐºÐ°Ðº ÑÐ¾Ð»Ð+/-ÑÐº)
LUMA_IMG_BASE_URL = os.environ.get("LUMA_IMG_BASE_URL", "").strip().rstrip("/")
LUMA_IMG_MODEL    = os.environ.get("LUMA_IMG_MODEL", "imagine-image-1").strip()

# Ð¤Ð¾Ð»Ð+/-ÑÐºÐ¸ Luma
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

# âââââââââ Kling (Ð½Ð¾Ð²ÑÐ¹ Ð²Ð¸Ð´ÐµÐ¾Ð´Ð²Ð¸Ð¶Ð¾Ðº ÑÐµÑÐµÐ· CometAPI) âââââââââ

KLING_BASE_URL   = os.environ.get("KLING_BASE_URL", "https://api.cometapi.com").strip().rstrip("/")
KLING_MODEL_NAME = os.environ.get("KLING_MODEL_NAME", "kling-v1-6").strip()
KLING_MODE       = os.environ.get("KLING_MODE", "std").strip()
KLING_ASPECT     = os.environ.get("KLING_ASPECT", "9:16").strip()
KLING_DURATION_S = int((os.environ.get("KLING_DURATION_S") or "5").strip() or 5)
KLING_MAX_WAIT_S = int((os.environ.get("KLING_MAX_WAIT_S") or "900").strip() or 900)
KLING_UNIT_COST_USD = float((os.environ.get("KLING_UNIT_COST_USD") or "0.80").replace(",", ".") or "0.80")

# ÐÐ+/-ÑÐ¸Ð¹ Ð¸Ð½ÑÐµÑÐ²Ð°Ð» Ð¼ÐµÐ¶Ð´Ñ Ð¾Ð¿ÑÐ¾ÑÐ°Ð¼Ð¸ ÑÑÐ°ÑÑÑÐ° Ð·Ð°Ð´Ð°Ñ Ð²Ð¸Ð´ÐµÐ¾
VIDEO_POLL_DELAY_S = _env_float("VIDEO_POLL_DELAY_S", 6.0)

# âââââââââ ÐÐÐ¨Ð / ÐÐÐÐÐÐÐ¬ÐÐÐ Ð¡ÐÐ¡Ð¢ÐÐ¯ÐÐÐ âââââââââ

# ÐÐ¾ÑÐ»ÐµÐ´Ð½ÐµÐµ ÑÐ¾ÑÐ¾ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ Ð´Ð»Ñ Ð°Ð½Ð¸Ð¼Ð°ÑÐ¸Ð¸ (Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ñ)
# user_id -> {"bytes": b"...", "url": "https://..."}
_LAST_ANIM_PHOTO: dict[int, dict] = {}

# âââââââââ UTILS ---------
_LUMA_ACTIVE_BASE = None  # ÐºÑÑ Ð¿Ð¾ÑÐ»ÐµÐ´Ð½ÐµÐ³Ð¾ Ð¶Ð¸Ð²Ð¾Ð³Ð¾ Ð+/-Ð°Ð·Ð¾Ð²Ð¾Ð³Ð¾ URL

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

# ââ ÐÐµÐ·Ð»Ð¸Ð¼Ð¸Ñ ââ
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

# ââ Premium page URL ââ
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

# ââ OpenAI clients ââ
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

# Tavily (Ð¾Ð¿ÑÐ¸Ð¾Ð½Ð°Ð»ÑÐ½Ð¾)
try:
    if TAVILY_API_KEY:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
    else:
        tavily = None
except Exception:
    tavily = None

# âââââââââ DB: subscriptions / usage / wallet / kv âââââââââ
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
    # Ð¼Ð¸Ð³ÑÐ°ÑÐ¸Ð¸
    try:
        cur.execute("ALTER TABLE wallet ADD COLUMN usd REAL DEFAULT 0.0")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE subscriptions ADD COLUMN tier TEXT")
    except Exception:
        pass
    con.commit(); con.close()


# Ensure DB schema exists even during module import (Render cold-start safe).
# main_keyboard() is built at import-time below, and it depends on get_lang() -> kv_get() -> table kv.
with contextlib.suppress(Exception):
    db_init()
with contextlib.suppress(Exception):
    db_init_usage()
def kv_get(key: str, default: str | None = None) -> str | None:
    """Small KV helper backed by SQLite.
    Robust to first-run / missing schema (auto-creates tables on demand).
    """
    try:
        con = sqlite3.connect(DB_PATH); cur = con.cursor()
        cur.execute("SELECT value FROM kv WHERE key=?", (key,))
        row = cur.fetchone(); con.close()
        return (row[0] if row else default)
    except sqlite3.OperationalError as e:
        # Typically: sqlite3.OperationalError: no such table: kv
        with contextlib.suppress(Exception):
            db_init_usage()
        with contextlib.suppress(Exception):
            con = sqlite3.connect(DB_PATH); cur = con.cursor()
            cur.execute("SELECT value FROM kv WHERE key=?", (key,))
            row = cur.fetchone(); con.close()
            return (row[0] if row else default)
        raise
def kv_set(key: str, value: str):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?,?)", (key, value))
    con.commit(); con.close()

# =============================
# Language / i18n
# =============================

LANGS: list[str] = ["ru", "be", "uk", "de", "en", "fr", "th"]
LANG_NAMES: dict[str, str] = {
    "ru": "Ð ÑÑÑÐºÐ¸Ð¹",
    "be": "ÐÐµÐ»Ð¾ÑÑÑÑÐºÐ¸Ð¹",
    "uk": "Ð£ÐºÑÐ°Ð¸Ð½ÑÐºÐ¸Ð¹",
    "de": "Deutsch",
    "en": "English",
    "fr": "FranÃ§ais",
    "th": "à¹à¸à¸¢",
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
        "choose_lang": "ð ÐÑÐ+/-ÐµÑÐ¸ÑÐµ ÑÐ·ÑÐº",
        "lang_set": "â Ð¯Ð·ÑÐº ÑÑÑÐ°Ð½Ð¾Ð²Ð»ÐµÐ½",
        "menu_title": "ÐÐ»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½Ñ",
        "btn_engines": "ð§  ÐÐ²Ð¸Ð¶ÐºÐ¸",
        "btn_sub": "â ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° â¢ ÐÐ¾Ð¼Ð¾ÑÑ",
        "btn_wallet": "ð§¾ ÐÐ°Ð»Ð°Ð½Ñ",
        "btn_video": "ð Ð¡Ð¾Ð·Ð´Ð°ÑÑ Ð²Ð¸Ð´ÐµÐ¾",
        "btn_photo": "ð¼ ÐÐ¶Ð¸Ð²Ð¸ÑÑ ÑÐ¾ÑÐ¾",
        "btn_help": "â ÐÐ¾Ð¼Ð¾ÑÑ",
        "btn_back": "â¬ï¸ ÐÐ°Ð·Ð°Ð´",
        "btn_study": "ð Ð£ÑÑÐ+/-Ð°",
        "btn_work": "ð¼ Ð Ð°Ð+/-Ð¾ÑÐ°",
        "btn_fun": "ð Ð Ð°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ñ",
    },
    "be": {
        "choose_lang": "ð ÐÐ+/-ÑÑÑÑÐµ Ð¼Ð¾Ð²Ñ",
        "lang_set": "â ÐÐ¾Ð²Ð° ÑÑÑÐ°Ð»ÑÐ²Ð°Ð½Ð°",
        "menu_title": "ÐÐ°Ð»Ð¾ÑÐ½Ð°Ðµ Ð¼ÐµÐ½Ñ",
        "btn_engines": "ð§  Ð ÑÑÐ°Ð²ÑÐºÑ",
        "btn_sub": "â ÐÐ°Ð´Ð¿ÑÑÐºÐ° â¢ ÐÐ°Ð¿Ð°Ð¼Ð¾Ð³Ð°",
        "btn_wallet": "ð§¾ ÐÐ°Ð»Ð°Ð½Ñ",
        "btn_video": "ð Ð¡ÑÐ²Ð°ÑÑÑÑ Ð²ÑÐ´ÑÐ°",
        "btn_photo": "ð¼ ÐÐ¶ÑÐ²ÑÑÑ ÑÐ¾ÑÐ°",
        "btn_help": "â ÐÐ°Ð¿Ð°Ð¼Ð¾Ð³Ð°",
        "btn_back": "â¬ï¸ ÐÐ°Ð·Ð°Ð´",
    },
    "uk": {
        "choose_lang": "ð ÐÐ+/-ÐµÑÑÑÑ Ð¼Ð¾Ð²Ñ",
        "lang_set": "â ÐÐ¾Ð²Ñ Ð²ÑÑÐ°Ð½Ð¾Ð²Ð»ÐµÐ½Ð¾",
        "menu_title": "ÐÐ¾Ð»Ð¾Ð²Ð½Ðµ Ð¼ÐµÐ½Ñ",
        "btn_engines": "ð§  Ð ÑÑÑÑ",
        "btn_sub": "â ÐÑÐ´Ð¿Ð¸ÑÐºÐ° â¢ ÐÐ¾Ð¿Ð¾Ð¼Ð¾Ð³Ð°",
        "btn_wallet": "ð§¾ ÐÐ°Ð»Ð°Ð½Ñ",
        "btn_video": "ð Ð¡ÑÐ²Ð¾ÑÐ¸ÑÐ¸ Ð²ÑÐ´ÐµÐ¾",
        "btn_photo": "ð¼ ÐÐ¶Ð¸Ð²Ð¸ÑÐ¸ ÑÐ¾ÑÐ¾",
        "btn_help": "â ÐÐ¾Ð¿Ð¾Ð¼Ð¾Ð³Ð°",
        "btn_back": "â¬ï¸ ÐÐ°Ð·Ð°Ð´",
        "btn_study": "ð ÐÐ°Ð²ÑÐ°Ð½Ð½Ñ",
        "btn_work": "ð¼ Ð Ð¾Ð+/-Ð¾ÑÐ°",
        "btn_fun": "ð¥ Ð Ð¾Ð·Ð²Ð°Ð³Ð¸",
        "input_placeholder": "ÐÐ+/-ÐµÑÑÑÑ ÑÐµÐ¶Ð¸Ð¼ Ð°Ð+/-Ð¾ Ð½Ð°Ð¿Ð¸ÑÑÑÑ Ð·Ð°Ð¿Ð¸Ñâ¦",
    
    },
    "de": {
        "choose_lang": "ð Sprache wÃ¤hlen",
        "lang_set": "â Sprache gesetzt",
        "menu_title": "HauptmenÃ¼",
        "btn_engines": "ð§  Engines",
        "btn_sub": "â Abo â¢ Hilfe",
        "btn_wallet": "ð§¾ Guthaben",
        "btn_video": "ð Video erstellen",
        "btn_photo": "ð¼ Foto animieren",
        "btn_help": "â Hilfe",
        "btn_back": "â¬ï¸ ZurÃ¼ck",
        "btn_study": "ð Lernen",
        "btn_work": "ð¼ Arbeit",
        "btn_fun": "ð SpaÃ",
    },
    "en": {
        "choose_lang": "ð Choose language",
        "lang_set": "â Language set",
        "menu_title": "Main menu",
        "btn_engines": "ð§  Engines",
        "btn_sub": "â Subscription â¢ Help",
        "btn_wallet": "ð§¾ Balance",
        "btn_video": "ð Create video",
        "btn_photo": "ð¼ Animate photo",
        "btn_help": "â Help",
        "btn_back": "â¬ï¸ Back",
        "btn_study": "ð Study",
        "btn_work": "ð¼ Work",
        "btn_fun": "ð Fun",
    },
    "fr": {
        "choose_lang": "ð Choisir la langue",
        "lang_set": "â Langue dÃ©finie",
        "menu_title": "Menu principal",
        "btn_engines": "ð§  Moteurs",
        "btn_sub": "â Abonnement â¢ Aide",
        "btn_wallet": "ð§¾ Solde",
        "btn_video": "ð CrÃ©er une vidÃ©o",
        "btn_photo": "ð¼ Animer une photo",
        "btn_help": "â Aide",
        "btn_back": "â¬ï¸ Retour",
        "btn_study": "ð Ãtudes",
        "btn_work": "ð¼ Travail",
        "btn_fun": "ð Divertissement",
    },
    "th": {
        "choose_lang": "ð à¹à¸¥à¸·à¸à¸à¸ à¸²à¸©à¸²",
        "lang_set": "â à¸à¸+/-à¹à¸à¸à¹à¸²à¸ à¸²à¸©à¸²à¹à¸¥à¹à¸§",
        "menu_title": "à¹à¸¡à¸à¸¹à¸«à¸¥à¸+/-à¸",
        "btn_engines": "ð§  à¹à¸à¸à¸à¸´à¸",
        "btn_sub": "â à¸ªà¸¡à¸+/-à¸à¸£à¸ªà¸¡à¸²à¸à¸´à¸ â¢ à¸à¹à¸§à¸¢à¹à¸«à¸¥à¸·à¸",
        "btn_wallet": "ð§¾ à¸¢à¸à¸à¸à¸à¹à¸«à¸¥à¸·à¸",
        "btn_video": "ð à¸ªà¸£à¹à¸²à¸à¸§à¸´à¸à¸µà¹à¸",
        "btn_photo": "ð¼ à¸à¸³à¹à¸«à¹à¸£à¸¹à¸à¹à¸à¸¥à¸·à¹à¸à¸à¹à¸«à¸§",
        "btn_help": "â à¸à¹à¸§à¸¢à¹à¸«à¸¥à¸·à¸",
        "btn_back": "â¬ï¸ à¸à¸¥à¸+/-à¸",
        "btn_study": "ð à¹à¸£à¸µà¸¢à¸",
        "btn_work": "ð¼ à¸à¸²à¸",
        "btn_fun": "ð à¸ªà¸à¸¸à¸",
    },
}

def t(user_id: int, key: str) -> str:
    lang = get_lang(user_id)
    return (I18N.get(lang) or I18N["ru"]).get(key, key)

def system_prompt_for(lang: str) -> str:
    mapping = {
        "ru": "ÐÑÐ²ÐµÑÐ°Ð¹ Ð½Ð° ÑÑÑÑÐºÐ¾Ð¼ ÑÐ·ÑÐºÐµ.",
        "be": "ÐÐ´ÐºÐ°Ð·Ð²Ð°Ð¹ Ð¿Ð°-Ð+/-ÐµÐ»Ð°ÑÑÑÐºÑ.",
        "uk": "ÐÑÐ´Ð¿Ð¾Ð²ÑÐ´Ð°Ð¹ ÑÐºÑÐ°ÑÐ½ÑÑÐºÐ¾Ñ Ð¼Ð¾Ð²Ð¾Ñ.",
        "de": "Antworte auf Deutsch.",
        "en": "Answer in English.",
        "fr": "RÃ©ponds en franÃ§ais.",
        "th": "à¸à¸à¸à¹à¸à¹à¸à¸ à¸²à¸©à¸²à¹à¸à¸¢",
    }
    return mapping.get(lang, mapping["ru"])

# Extended pack (long UI texts / hints)
I18N_PACK: dict[str, dict[str, str]] = {
    "welcome": {
        "ru": "ÐÑÐ¸Ð²ÐµÑ! Ð¯ ÐÐµÐ¹ÑÐ¾âBot â â¡ Ð¼ÑÐ»ÑÑÐ¸ÑÐµÐ¶Ð¸Ð¼Ð½ÑÐ¹ Ð+/-Ð¾Ñ Ð¸Ð· 7 Ð½ÐµÐ¹ÑÐ¾ÑÐµÑÐµÐ¹ Ð´Ð»Ñ ÑÑÑÐ+/-Ñ, ÑÐ°Ð+/-Ð¾ÑÑ Ð¸ ÑÐ°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ð¹.",
        "be": "ÐÑÑÐ²ÑÑÐ°Ð½Ð½Ðµ! Ð¯ ÐÐµÐ¹ÑÐ¾âBot â â¡ ÑÐ¼Ð°ÑÑÑÐ¶ÑÐ¼Ð½Ñ Ð+/-Ð¾Ñ Ð· 7 Ð½ÐµÐ¹ÑÐ°ÑÐµÑÐ°Ðº Ð´Ð»Ñ Ð²ÑÑÐ¾Ð+/-Ñ, Ð¿ÑÐ°ÑÑ Ñ Ð·Ð°Ð+/-Ð°Ñ.",
        "uk": "ÐÑÐ¸Ð²ÑÑ! Ð¯ ÐÐµÐ¹ÑÐ¾âBot â â¡ Ð¼ÑÐ»ÑÑÐ¸ÑÐµÐ¶Ð¸Ð¼Ð½Ð¸Ð¹ Ð+/-Ð¾Ñ ÑÐ· 7 Ð½ÐµÐ¹ÑÐ¾Ð¼ÐµÑÐµÐ¶ Ð´Ð»Ñ Ð½Ð°Ð²ÑÐ°Ð½Ð½Ñ, ÑÐ¾Ð+/-Ð¾ÑÐ¸ ÑÐ° ÑÐ¾Ð·Ð²Ð°Ð³.",
        "de": "Hallo! Ich bin NeuroâBot â â¡ ein MultimodeâBot mit 7 KIâEngines fÃ¼r Lernen, Arbeit und SpaÃ.",
        "en": "Hi! Iâm NeuroâBot â â¡ a multiâmode bot with 7 AI engines for study, work and fun.",
        "fr": "Salut ! Je suis NeuroâBot â â¡ un bot multiâmodes avec 7 moteurs IA pour Ã©tudier, travailler et se divertir.",
        "th": "à¸ªà¸§à¸+/-à¸ªà¸à¸µ! à¸à¸+/-à¸à¸à¸·à¸ NeuroâBot â â¡ à¸à¸à¸à¸«à¸¥à¸²à¸¢à¹à¸«à¸¡à¸à¸à¸£à¹à¸à¸¡à¹à¸à¸à¸à¸´à¸ AI 7 à¸à¸+/-à¸§ à¸ªà¸³à¸«à¸£à¸+/-à¸à¹à¸£à¸µà¸¢à¸ à¸à¸²à¸ à¹à¸¥à¸°à¸à¸§à¸²à¸¡à¸à¸+/-à¸à¹à¸à¸´à¸",
    },
    "ask_video_prompt": {
        "ru": "ð ÐÐ°Ð¿Ð¸ÑÐ¸ Ð·Ð°Ð¿ÑÐ¾Ñ Ð´Ð»Ñ Ð²Ð¸Ð´ÐµÐ¾, Ð½Ð°Ð¿ÑÐ¸Ð¼ÐµÑ:\nÂ«Ð¡Ð´ÐµÐ»Ð°Ð¹ Ð²Ð¸Ð´ÐµÐ¾: Ð·Ð°ÐºÐ°Ñ Ð½Ð°Ð´ Ð¼Ð¾ÑÐµÐ¼, 7 ÑÐµÐº, 16:9Â»",
        "be": "ð ÐÐ°Ð¿ÑÑÑ Ð·Ð°Ð¿ÑÑ Ð´Ð»Ñ Ð²ÑÐ´ÑÐ°, Ð½Ð°Ð¿ÑÑÐºÐ»Ð°Ð´:\nÂ«ÐÑÐ°Ð+/-Ñ Ð²ÑÐ´ÑÐ°: Ð·Ð°ÑÐ°Ð´ ÑÐ¾Ð½ÑÐ° Ð½Ð°Ð´ Ð¼Ð¾ÑÐ°Ð¼, 7 ÑÐµÐº, 16:9Â»",
        "uk": "ð ÐÐ°Ð¿Ð¸ÑÐ¸ Ð·Ð°Ð¿Ð¸Ñ Ð´Ð»Ñ Ð²ÑÐ´ÐµÐ¾, Ð½Ð°Ð¿ÑÐ¸ÐºÐ»Ð°Ð´:\nÂ«ÐÑÐ¾Ð+/-Ð¸ Ð²ÑÐ´ÐµÐ¾: Ð·Ð°ÑÑÐ´ Ð½Ð°Ð´ Ð¼Ð¾ÑÐµÐ¼, 7 Ñ, 16:9Â»",
        "de": "ð Schreibe einen Prompt fÃ¼r das Video, z.B.:\nâErstelle ein Video: Sonnenuntergang am Meer, 7s, 16:9â",
        "en": "ð Type a video prompt, e.g.:\nâMake a video: sunset over the sea, 7s, 16:9â",
        "fr": "ð Ãcris un prompt pour la vidÃ©o, par ex. :\nÂ« Fais une vidÃ©o : coucher de soleil sur la mer, 7s, 16:9 Â»",
        "th": "ð à¸à¸´à¸¡à¸à¹à¸à¸³à¸ªà¸+/-à¹à¸à¸à¸³à¸§à¸´à¸à¸µà¹à¸ à¹à¸à¹à¸:\nâà¸à¸³à¸§à¸´à¸à¸µà¹à¸: à¸à¸£à¸°à¸à¸²à¸à¸´à¸à¸¢à¹à¸à¸à¹à¸«à¸à¸·à¸à¸à¸°à¹à¸¥ 7à¸§à¸´ 16:9â",
    },
    "ask_send_photo": {
        "ru": "ð¼ ÐÑÐ¸ÑÐ»Ð¸ ÑÐ¾ÑÐ¾, Ð·Ð°ÑÐµÐ¼ Ð²ÑÐ+/-ÐµÑÐ¸ Â«ÐÐ¶Ð¸Ð²Ð¸ÑÑ ÑÐ¾ÑÐ¾Â».",
        "be": "ð¼ ÐÐ°ÑÐ»Ñ ÑÐ¾ÑÐ°, Ð·Ð°ÑÑÐ¼ Ð²ÑÐ+/-ÐµÑÑ Â«ÐÐ¶ÑÐ²ÑÑÑ ÑÐ¾ÑÐ°Â».",
        "uk": "ð¼ ÐÐ°Ð´ÑÑÐ»Ð¸ ÑÐ¾ÑÐ¾, Ð¿Ð¾ÑÑÐ¼ Ð¾Ð+/-ÐµÑÐ¸ Â«ÐÐ¶Ð¸Ð²Ð¸ÑÐ¸ ÑÐ¾ÑÐ¾Â».",
        "de": "ð¼ Sende ein Foto, dann wÃ¤hle âFoto animierenâ.",
        "en": "ð¼ Send a photo, then choose âAnimate photoâ.",
        "fr": "ð¼ Envoyez une photo, puis choisissez Â« Animer la photo Â».",
        "th": "ð¼ à¸ªà¹à¸à¸£à¸¹à¸ à¸à¸²à¸à¸à¸+/-à¹à¸à¹à¸¥à¸·à¸à¸ âà¸à¸³à¹à¸«à¹à¸£à¸¹à¸à¹à¸à¸¥à¸·à¹à¸à¸à¹à¸«à¸§â",
    },
    "photo_received": {
        "ru": "ð¼ Ð¤Ð¾ÑÐ¾ Ð¿Ð¾Ð»ÑÑÐµÐ½Ð¾. Ð¥Ð¾ÑÐ¸ÑÐµ Ð¾Ð¶Ð¸Ð²Ð¸ÑÑ?",
        "be": "ð¼ Ð¤Ð¾ÑÐ° Ð°ÑÑÑÐ¼Ð°Ð½Ð°. ÐÐ¶ÑÐ²ÑÑÑ?",
        "uk": "ð¼ Ð¤Ð¾ÑÐ¾ Ð¾ÑÑÐ¸Ð¼Ð°Ð½Ð¾. ÐÐ¶Ð¸Ð²Ð¸ÑÐ¸?",
        "de": "ð¼ Foto erhalten. Animieren?",
        "en": "ð¼ Photo received. Animate it?",
        "fr": "ð¼ Photo reÃ§ue. Lâanimer ?",
        "th": "ð¼ à¹à¸à¹à¸£à¸+/-à¸à¸£à¸¹à¸à¹à¸¥à¹à¸§ à¸à¹à¸à¸à¸à¸²à¸£à¸à¸³à¹à¸«à¹à¹à¸à¸¥à¸·à¹à¸à¸à¹à¸«à¸§à¹à¸«à¸¡?",
    },
    "animate_btn": {
        "ru": "ð¬ ÐÐ¶Ð¸Ð²Ð¸ÑÑ ÑÐ¾ÑÐ¾",
        "be": "ð¬ ÐÐ¶ÑÐ²ÑÑÑ ÑÐ¾ÑÐ°",
        "uk": "ð¬ ÐÐ¶Ð¸Ð²Ð¸ÑÐ¸ ÑÐ¾ÑÐ¾",
        "de": "ð¬ Foto animieren",
        "en": "ð¬ Animate photo",
        "fr": "ð¬ Animer la photo",
        "th": "ð¬ à¸à¸³à¹à¸«à¹à¸£à¸¹à¸à¹à¸à¸¥à¸·à¹à¸à¸à¹à¸«à¸§",
    },
    "choose_engine": {
        "ru": "ÐÑÐ+/-ÐµÑÐ¸ÑÐµ Ð´Ð²Ð¸Ð¶Ð¾Ðº:",
        "be": "ÐÐ+/-ÑÑÑÑÐµ ÑÑÑÐ°Ð²ÑÐº:",
        "uk": "ÐÐ+/-ÐµÑÑÑÑ ÑÑÑÑÐ¹:",
        "de": "WÃ¤hle die Engine:",
        "en": "Choose engine:",
        "fr": "Choisissez le moteur:",
        "th": "à¹à¸¥à¸·à¸à¸à¹à¸à¸à¸à¸´à¸:",
    },
    "runway_disabled_textvideo": {
        "ru": "â ï¸ Runway Ð¾ÑÐºÐ»ÑÑÑÐ½ Ð´Ð»Ñ Ð²Ð¸Ð´ÐµÐ¾ Ð¿Ð¾ ÑÐµÐºÑÑÑ/Ð³Ð¾Ð»Ð¾ÑÑ. ÐÑÐ+/-ÐµÑÐ¸ÑÐµ Kling, Luma Ð¸Ð»Ð¸ Sora.",
        "be": "â ï¸ Runway Ð°Ð´ÐºÐ»ÑÑÐ°Ð½Ñ Ð´Ð»Ñ Ð²ÑÐ´ÑÐ° Ð¿Ð° ÑÑÐºÑÑÐµ/Ð³Ð¾Ð»Ð°ÑÐµ. ÐÐ+/-ÑÑÑÑÐµ Kling, Luma Ð°Ð+/-Ð¾ Sora.",
        "uk": "â ï¸ Runway Ð²Ð¸Ð¼ÐºÐ½ÐµÐ½Ð¾ Ð´Ð»Ñ Ð²ÑÐ´ÐµÐ¾ Ð· ÑÐµÐºÑÑÑ/Ð³Ð¾Ð»Ð¾ÑÑ. ÐÐ+/-ÐµÑÑÑÑ Kling, Luma Ð°Ð+/-Ð¾ Sora.",
        "de": "â ï¸ Runway ist fÃ¼r Text/VoiceâVideo deaktiviert. WÃ¤hle Kling, Luma oder Sora.",
        "en": "â ï¸ Runway is disabled for text/voiceâvideo. Choose Kling, Luma or Sora.",
        "fr": "â ï¸ Runway est dÃ©sactivÃ© pour texte/voixâvidÃ©o. Choisissez Kling, Luma ou Sora.",
        "th": "â ï¸ à¸à¸´à¸ Runway à¸ªà¸³à¸«à¸£à¸+/-à¸à¸à¹à¸à¸à¸§à¸²à¸¡/à¹à¸ªà¸µà¸¢à¸âà¸§à¸´à¸à¸µà¹à¸ à¹à¸¥à¸·à¸à¸ Kling, Luma à¸«à¸£à¸·à¸ Sora",
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

def _lang_choose_kb(user_id: int | None = None) -> InlineKeyboardMarkup:
    """
    ÐÐ»Ð°Ð²Ð¸Ð°ÑÑÑÐ° Ð²ÑÐ+/-Ð¾ÑÐ° ÑÐ·ÑÐºÐ°.
    Ð¢ÑÐµÐ+/-Ð¾Ð²Ð°Ð½Ð¸Ðµ: Ð¿Ð¾ÐºÐ°Ð·ÑÐ²Ð°ÑÑ Ð¿ÑÐ¸ ÐºÐ°Ð¶Ð´Ð¾Ð¼ /start.
    ÐÐ»Ñ ÑÐ´Ð¾Ð+/-ÑÑÐ²Ð° Ð´Ð¾Ð+/-Ð°Ð²Ð»ÑÐµÐ¼ Â«ÐÑÐ¾Ð´Ð¾Ð»Ð¶Ð¸ÑÑÂ» Ñ ÑÐµÐºÑÑÐ¸Ð¼ ÑÐ·ÑÐºÐ¾Ð¼, ÐµÑÐ»Ð¸ Ð¾Ð½ ÑÐ¶Ðµ Ð²ÑÐ+/-ÑÐ°Ð½.
    """
    uid = int(user_id) if user_id is not None else 0
    rows = []
    if uid and has_lang(uid):
        cur = get_lang(uid)
        cur_name = LANG_NAMES.get(cur, cur)
        rows.append([InlineKeyboardButton(f"â¡ï¸ ÐÑÐ¾Ð´Ð¾Ð»Ð¶Ð¸ÑÑ ({cur_name})", callback_data="lang:__keep__")])
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

# === ÐÐÐÐÐ«Ð ÐÐÐ¨ÐÐÐÐ (USD) ===
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

# âââââââââ ÐÐ¸Ð¼Ð¸ÑÑ/ÑÐµÐ½Ñ âââââââââ
USD_RUB = float(os.environ.get("USD_RUB", "100"))
ONEOFF_MARKUP_DEFAULT = float(os.environ.get("ONEOFF_MARKUP_DEFAULT", "1.0"))
ONEOFF_MARKUP_RUNWAY  = float(os.environ.get("ONEOFF_MARKUP_RUNWAY",  "0.5"))
LUMA_RES_HINT = os.environ.get("LUMA_RES", "720p").lower()
RUNWAY_UNIT_COST_USD = float(os.environ.get("RUNWAY_UNIT_COST_USD", "7.0"))
IMG_COST_USD = float(os.environ.get("IMG_COST_USD", "0.05"))

# âââââââââââââââââ SORA (via Comet / aggregator) âââââââââââââââââ
# Variables may be provided later; keep disabled safely by default.
SORA_ENABLED = bool(os.environ.get("SORA_ENABLED", "").strip())
SORA_COMET_BASE_URL = os.environ.get("SORA_COMET_BASE_URL", "").strip()  # e.g. https://api.cometapi.com
SORA_COMET_API_KEY = os.environ.get("SORA_COMET_API_KEY", "").strip()
SORA_MODEL_FREE = os.environ.get("SORA_MODEL_FREE", "sora-2").strip()
SORA_MODEL_PRO = os.environ.get("SORA_MODEL_PRO", "sora-2-pro").strip()
SORA_UNIT_COST_USD = float(os.environ.get("SORA_UNIT_COST_USD", "0.40"))  # fallback estimate per second


# DEMO: free Ð´Ð°ÑÑ Ð¿Ð¾Ð¿ÑÐ¾Ð+/-Ð¾Ð²Ð°ÑÑ ÐºÐ»ÑÑÐµÐ²ÑÐµ Ð´Ð²Ð¸Ð¶ÐºÐ¸
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
    "kling":  "luma",    # <â Kling ÑÐ¸Ð´Ð¸Ñ Ð½Ð° ÑÐ¾Ð¼ Ð¶Ðµ Ð+/-ÑÐ´Ð¶ÐµÑÐµ
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

# ÐºÐ°ÐºÐ¸Ðµ Ð´Ð²Ð¸Ð¶ÐºÐ¸ Ð½Ð° ÐºÐ°ÐºÐ¾Ð¹ Ð+/-ÑÐ´Ð¶ÐµÑ ÑÐ°Ð´ÑÑÑÑ
ENGINE_BUDGET_GROUP = {
    "luma": "luma",
    "kling": "luma",   # Kling Ð¸ Luma Ð´ÐµÐ»ÑÑ Ð¾Ð´Ð¸Ð½ Ð+/-ÑÐ´Ð¶ÐµÑ
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
    ÐÑÐ¾Ð²ÐµÑÑÐµÐ¼, Ð¼Ð¾Ð¶Ð½Ð¾ Ð»Ð¸ Ð¿Ð¾ÑÑÐ°ÑÐ¸ÑÑ est_cost_usd Ð½Ð° ÑÐºÐ°Ð·Ð°Ð½Ð½ÑÐ¹ Ð´Ð²Ð¸Ð¶Ð¾Ðº.
    ÐÐ¾Ð·Ð²ÑÐ°ÑÐ°ÐµÐ¼ (ok, reason):
      ok = True  -> Ð¼Ð¾Ð¶Ð½Ð¾, reason = ""
      ok = False -> Ð½ÐµÐ»ÑÐ·Ñ, reason = "ASK_SUBSCRIBE" Ð¸Ð»Ð¸ "OFFER:<usd>"
    """
    group = ENGINE_BUDGET_GROUP.get(engine, engine)

    # Ð+/-ÐµÐ·Ð»Ð¸Ð¼Ð¸ÑÐ½ÑÐµ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ð¸
    if is_unlimited(user_id, username):
        if group in ("luma", "runway", "img"):
            _usage_update(user_id, **{f"{group}_usd": est_cost_usd})
        return True, ""

    # ÐµÑÐ»Ð¸ Ð´Ð²Ð¸Ð¶Ð¾Ðº Ð½Ðµ ÑÐ°ÑÐ¸ÑÐ¸ÑÐ¸ÑÑÐµÐ¼ÑÐ¹ â Ð¿ÑÐ¾ÑÑÐ¾ ÑÐ°Ð·ÑÐµÑÐ°ÐµÐ¼
    if group not in ("luma", "runway", "img"):
        return True, ""

    tier = get_subscription_tier(user_id)
    lim = _limits_for(user_id)
    row = _usage_row(user_id)

    spent = row[f"{group}_usd"]
    budget = lim[f"{group}_budget_usd"]

    # ÐµÑÐ»Ð¸ Ð²Ð»ÐµÐ·Ð°ÐµÐ¼ Ð² Ð´Ð½ÐµÐ²Ð½Ð¾Ð¹ Ð+/-ÑÐ´Ð¶ÐµÑ Ð¿Ð¾ Ð³ÑÑÐ¿Ð¿Ðµ (luma/runway/img)
    if spent + est_cost_usd <= budget + 1e-9:
        _usage_update(user_id, **{f"{group}_usd": est_cost_usd})
        return True, ""

    # ÐÐ¾Ð¿ÑÑÐºÐ° Ð¿Ð¾ÐºÑÑÑÑ Ð¸Ð· ÐµÐ´Ð¸Ð½Ð¾Ð³Ð¾ ÐºÐ¾ÑÐµÐ»ÑÐºÐ°
    need = max(0.0, spent + est_cost_usd - budget)
    if need > 0:
        if _wallet_total_take(user_id, need):
            _usage_update(user_id, **{f"{group}_usd": est_cost_usd})
            return True, ""

        # Ð½Ð° ÑÑÐ¸-ÑÐ°ÑÐ¸ÑÐµ Ð¿ÑÐ¾ÑÐ¸Ð¼ Ð¾ÑÐ¾ÑÐ¼Ð¸ÑÑ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÑ
        if tier == "free":
            return False, "ASK_SUBSCRIBE"

        # Ð½Ð° Ð¿Ð»Ð°ÑÐ½ÑÑ ÑÐ°ÑÐ¸ÑÐ°Ñ Ð¿Ð¾ÐºÐ°Ð·ÑÐ²Ð°ÐµÐ¼ Ð¿ÑÐµÐ´Ð»Ð¾Ð¶ÐµÐ½Ð¸Ðµ Ð´Ð¾ÐºÑÐ¿Ð¸ÑÑ Ð»Ð¸Ð¼Ð¸Ñ
        return False, f"OFFER:{need:.2f}"

    return True, ""


def _register_engine_spend(user_id: int, engine: str, usd: float):
    """
    Ð ÐµÐ³Ð¸ÑÑÑÐ¸ÑÑÐµÐ¼ ÑÐ¶Ðµ ÑÐ¾Ð²ÐµÑÑÑÐ½Ð½ÑÐ¹ ÑÐ°ÑÑÐ¾Ð´ Ð¿Ð¾ Ð´Ð²Ð¸Ð¶ÐºÑ.
    ÐÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÑÑÑ Ð´Ð»Ñ ÑÐµÑ Ð²ÑÐ·Ð¾Ð²Ð¾Ð², Ð³Ð´Ðµ ÑÑÐ¾Ð¸Ð¼Ð¾ÑÑÑ Ð¸Ð·Ð²ÐµÑÑÐ½Ð° Ð¿Ð¾ÑÑÑÐ°ÐºÑÑÐ¼
    Ð¸Ð»Ð¸ ÐºÐ¾Ð³Ð´Ð° Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ Ð+/-ÐµÐ·Ð»Ð¸Ð¼Ð¸ÑÐ½ÑÐ¹.
    """
    group = ENGINE_BUDGET_GROUP.get(engine, engine)
    if group in ("luma", "runway", "img"):
        _usage_update(user_id, **{f"{group}_usd": float(usd)})
        
# âââââââââ Prompts âââââââââ
SYSTEM_PROMPT = (
    "Ð¢Ñ Ð´ÑÑÐ¶ÐµÐ»ÑÐ+/-Ð½ÑÐ¹ Ð¸ Ð»Ð°ÐºÐ¾Ð½Ð¸ÑÐ½ÑÐ¹ Ð°ÑÑÐ¸ÑÑÐµÐ½Ñ Ð½Ð° ÑÑÑÑÐºÐ¾Ð¼. "
    "ÐÑÐ²ÐµÑÐ°Ð¹ Ð¿Ð¾ ÑÑÑÐ¸, ÑÑÑÑÐºÑÑÑÐ¸ÑÑÐ¹ ÑÐ¿Ð¸ÑÐºÐ°Ð¼Ð¸/ÑÐ°Ð³Ð°Ð¼Ð¸, Ð½Ðµ Ð²ÑÐ´ÑÐ¼ÑÐ²Ð°Ð¹ ÑÐ°ÐºÑÑ. "
    "ÐÑÐ»Ð¸ ÑÑÑÐ»Ð°ÐµÑÑÑÑ Ð½Ð° Ð¸ÑÑÐ¾ÑÐ½Ð¸ÐºÐ¸ â Ð² ÐºÐ¾Ð½ÑÐµ Ð´Ð°Ð¹ ÐºÐ¾ÑÐ¾ÑÐºÐ¸Ð¹ ÑÐ¿Ð¸ÑÐ¾Ðº ÑÑÑÐ»Ð¾Ðº."
)
VISION_SYSTEM_PROMPT = (
    "Ð¢Ñ ÑÑÑÐºÐ¾ Ð¾Ð¿Ð¸ÑÑÐ²Ð°ÐµÑÑ ÑÐ¾Ð´ÐµÑÐ¶Ð¸Ð¼Ð¾Ðµ Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ð¹: Ð¾Ð+/-ÑÐµÐºÑÑ, ÑÐµÐºÑÑ, ÑÑÐµÐ¼Ñ, Ð³ÑÐ°ÑÐ¸ÐºÐ¸. "
    "ÐÐµ Ð¸Ð´ÐµÐ½ÑÐ¸ÑÐ¸ÑÐ¸ÑÑÐ¹ Ð»Ð¸ÑÐ½Ð¾ÑÑÐ¸ Ð»ÑÐ´ÐµÐ¹ Ð¸ Ð½Ðµ Ð¿Ð¸ÑÐ¸ Ð¸Ð¼ÐµÐ½Ð°, ÐµÑÐ»Ð¸ Ð¾Ð½Ð¸ Ð½Ðµ Ð½Ð°Ð¿ÐµÑÐ°ÑÐ°Ð½Ñ Ð½Ð° Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ð¸."
)

# âââââââââ Heuristics / intent âââââââââ
_SMALLTALK_RE = re.compile(r"^(Ð¿ÑÐ¸Ð²ÐµÑ|Ð·Ð´ÑÐ°Ð²ÑÑÐ²ÑÐ¹|Ð´Ð¾Ð+/-ÑÑÐ¹\s*(Ð´ÐµÐ½Ñ|Ð²ÐµÑÐµÑ|ÑÑÑÐ¾)|ÑÐ¸|hi|hello|ÐºÐ°Ðº Ð´ÐµÐ»Ð°|ÑÐ¿Ð°ÑÐ¸Ð+/-Ð¾|Ð¿Ð¾ÐºÐ°)\b", re.I)
_NEWSY_RE     = re.compile(r"(ÐºÐ¾Ð³Ð´Ð°|Ð´Ð°ÑÐ°|Ð²ÑÐ¹Ð´ÐµÑ|ÑÐµÐ»Ð¸Ð·|Ð½Ð¾Ð²Ð¾ÑÑ|ÐºÑÑÑ|ÑÐµÐ½Ð°|Ð¿ÑÐ¾Ð³Ð½Ð¾Ð·|Ð½Ð°Ð¹Ð´Ð¸|Ð¾ÑÐ¸ÑÐ¸Ð°Ð»|Ð¿Ð¾Ð³Ð¾Ð´Ð°|ÑÐµÐ³Ð¾Ð´Ð½Ñ|ÑÑÐµÐ½Ð´|Ð°Ð´ÑÐµÑ|ÑÐµÐ»ÐµÑÐ¾Ð½)", re.I)
_CAPABILITY_RE= re.compile(r"(Ð¼Ð¾Ð¶(ÐµÑÑ|Ð½Ð¾|ÐµÑÐµ).{0,16}(Ð°Ð½Ð°Ð»Ð¸Ð·|ÑÐ°ÑÐ¿Ð¾Ð·Ð½|ÑÐ¸ÑÐ°ÑÑ|ÑÐ¾Ð·Ð´Ð°(Ð²Ð°)?Ñ|Ð´ÐµÐ»Ð°(ÑÑ)?).{0,24}(ÑÐ¾ÑÐ¾|ÐºÐ°ÑÑÐ¸Ð½Ðº|Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½|pdf|docx|epub|fb2|Ð°ÑÐ´Ð¸Ð¾|ÐºÐ½Ð¸Ð³))", re.I)

_IMG_WORDS = r"(ÐºÐ°ÑÑÐ¸Ð½\w+|Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½\w+|ÑÐ¾ÑÐ¾\w*|ÑÐ¸ÑÑÐ½Ðº\w+|image|picture|img\b|logo|banner|poster)"
_VID_WORDS = r"(Ð²Ð¸Ð´ÐµÐ¾|ÑÐ¾Ð»Ð¸Ðº\w*|Ð°Ð½Ð¸Ð¼Ð°ÑÐ¸\w*|shorts?|reels?|clip|video|vid\b)"

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

_CREATE_CMD = r"(ÑÐ´ÐµÐ»Ð°(Ð¹|Ð¹ÑÐµ)|ÑÐ¾Ð·Ð´Ð°(Ð¹|Ð¹ÑÐµ)|ÑÐ³ÐµÐ½ÐµÑÐ¸ÑÑ(Ð¹|Ð¹ÑÐµ)|Ð½Ð°ÑÐ¸ÑÑ(Ð¹|Ð¹ÑÐµ)|render|generate|create|make)"
_PREFIXES_VIDEO = [r"^" + _CREATE_CMD + r"\s+Ð²Ð¸Ð´ÐµÐ¾", r"^video\b", r"^reels?\b", r"^shorts?\b"]
_PREFIXES_IMAGE = [r"^" + _CREATE_CMD + r"\s+(?:ÐºÐ°ÑÑÐ¸Ð½\w+|Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½\w+|ÑÐ¾ÑÐ¾\w+|ÑÐ¸ÑÑÐ½Ðº\w+)", r"^image\b", r"^picture\b", r"^img\b"]

def _strip_leading(s: str) -> str:
    return s.strip(" \n\t:ââ-\"ââ'Â«Â»,.()[]")

def _after_match(text: str, match) -> str:
    return _strip_leading(text[match.end():])

def _looks_like_capability_question(tl: str) -> bool:
    if "?" in tl and re.search(_CAPABILITY_RE, tl):
        if not re.search(_CREATE_CMD, tl, re.I):
            return True
    m = re.search(r"\b(ÑÑ|Ð²Ñ)?\s*Ð¼Ð¾Ð¶(ÐµÑÑ|Ð½Ð¾|ÐµÑÐµ)\b", tl)
    if m and re.search(_CAPABILITY_RE, tl) and not re.search(_CREATE_CMD, tl, re.I):
        return True
    return False

def detect_media_intent(text: str):
    """
    ÐÑÑÐ°ÐµÐ¼ÑÑ Ð¿Ð¾Ð½ÑÑÑ, Ð¿ÑÐ¾ÑÐ¸Ñ Ð»Ð¸ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ:
    - ÑÐ³ÐµÐ½ÐµÑÐ¸ÑÐ¾Ð²Ð°ÑÑ ÐÐÐÐÐ ("video")
    - ÑÐ³ÐµÐ½ÐµÑÐ¸ÑÐ¾Ð²Ð°ÑÑ ÐÐÐ Ð¢ÐÐÐÐ£ ("image")
    ÐÐ¾Ð·Ð²ÑÐ°ÑÐ°ÐµÐ¼ ÐºÐ¾ÑÑÐµÐ¶ (mtype, rest), Ð³Ð´Ðµ:
        mtype â {"video", "image", None}
        rest  â Ð¾ÑÐ¸ÑÐµÐ½Ð½ÑÐ¹ Ð¿ÑÐ¾Ð¼Ð¿Ñ Ð+/-ÐµÐ· ÑÐ»ÑÐ¶ÐµÐ+/-Ð½ÑÑ ÑÐ»Ð¾Ð².
    """
    if not text:
        return (None, "")

    t = text.strip()
    tl = t.lower()

    # ÐÐ¾Ð¿ÑÐ¾ÑÑ "ÑÑÐ¾ ÑÑ ÑÐ¼ÐµÐµÑÑ?" Ð¸ Ñ.Ð¿. ÑÑÐ°Ð·Ñ Ð¾ÑÐ+/-ÑÐ°ÑÑÐ²Ð°ÐµÐ¼
    if _looks_like_capability_question(tl):
        return (None, "")

    # 1) Ð¯Ð²Ð½ÑÐµ Ð¿Ð°ÑÑÐµÑÐ½Ñ Ð´Ð»Ñ Ð²Ð¸Ð´ÐµÐ¾ (Ñ ÑÑÑÑÐ¾Ð¼ Ð½Ð¾Ð²ÑÑ _PREFIXES_VIDEO)
    for p in _PREFIXES_VIDEO:
        m = re.search(p, tl, re.I)
        if m:
            return ("video", _after_match(t, m))

    # 2) Ð¯Ð²Ð½ÑÐµ Ð¿Ð°ÑÑÐµÑÐ½Ñ Ð´Ð»Ñ ÐºÐ°ÑÑÐ¸Ð½Ð¾Ðº (Ð½Ð¾Ð²ÑÐµ _PREFIXES_IMAGE)
    for p in _PREFIXES_IMAGE:
        m = re.search(p, tl, re.I)
        if m:
            return ("image", _after_match(t, m))

    # 3) ÐÐ+/-ÑÐ¸Ð¹ ÑÐ»ÑÑÐ°Ð¹: ÐµÑÐ»Ð¸ ÐµÑÑÑ Ð³Ð»Ð°Ð³Ð¾Ð» Ð¸Ð· _CREATE_CMD
    #    Ð¸ Ð¾ÑÐ´ÐµÐ»ÑÐ½Ð¾ ÑÐ»Ð¾Ð²Ð° "Ð²Ð¸Ð´ÐµÐ¾/ÑÐ¾Ð»Ð¸Ðº" Ð¸Ð»Ð¸ "ÐºÐ°ÑÑÐ¸Ð½ÐºÐ°/ÑÐ¾ÑÐ¾/â¦"
    if re.search(_CREATE_CMD, tl, re.I):
        # --- Ð²Ð¸Ð´ÐµÐ¾ ---
        if re.search(_VID_WORDS, tl, re.I):
            # Ð²ÑÑÐµÐ·Ð°ÐµÐ¼ "Ð²Ð¸Ð´ÐµÐ¾/ÑÐ¾Ð»Ð¸Ðº" Ð¸ Ð³Ð»Ð°Ð³Ð¾Ð» ÐÐ ÐÐ ÐÐÐÐÐÐÐ¬ÐÐÐ Ð¡Ð¢Ð ÐÐÐ t
            clean = re.sub(_VID_WORDS, "", t, flags=re.I)
            clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
            return ("video", _strip_leading(clean))

        # --- ÐºÐ°ÑÑÐ¸Ð½ÐºÐ¸ ---
        if re.search(_IMG_WORDS, tl, re.I):
            clean = re.sub(_IMG_WORDS, "", t, flags=re.I)
            clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
            return ("image", _strip_leading(clean))

    # 4) Ð¡ÑÐ°ÑÑÐµ ÐºÐ¾ÑÐ¾ÑÐºÐ¸Ðµ ÑÐ¾ÑÐ¼Ð°ÑÑ "img: ..." / "image: ..." / "picture: ..."
    m = re.match(r"^(img|image|picture)\s*[:\-]\s*(.+)$", tl)
    if m:
        # Ð+/-ÐµÑÑÐ¼ ÑÐ²Ð¾ÑÑ ÑÐ¶Ðµ Ð¸Ð· Ð¾ÑÐ¸Ð³Ð¸Ð½Ð°Ð»ÑÐ½Ð¾Ð¹ ÑÑÑÐ¾ÐºÐ¸ t
        return ("image", _strip_leading(t[m.end(1) + 1:]))

    # 5) Ð¡ÑÐ°ÑÑÐµ ÐºÐ¾ÑÐ¾ÑÐºÐ¸Ðµ ÑÐ¾ÑÐ¼Ð°ÑÑ "video: ..." / "reels: ..." / "shorts: ..."
    m = re.match(r"^(video|vid|reels?|shorts?)\s*[:\-]\s*(.+)$", tl)
    if m:
        return ("video", _strip_leading(t[m.end(1) + 1:]))

    # ÐÐ¸ÑÐµÐ³Ð¾ Ð½Ðµ Ð½Ð°ÑÐ»Ð¸ â Ð¾Ð+/-ÑÑÐ½ÑÐ¹ ÑÐµÐºÑÑ
    return (None, "")
# âââââââââ OpenAI helpers âââââââââ
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
    Ð£Ð½Ð¸Ð²ÐµÑÑÐ°Ð»ÑÐ½ÑÐ¹ Ð·Ð°Ð¿ÑÐ¾Ñ Ðº LLM:
    - Ð¿Ð¾Ð´Ð´ÐµÑÐ¶Ð¸Ð²Ð°ÐµÑ OpenRouter (ÑÐµÑÐµÐ· OPENAI_API_KEY = sk-or-...);
    - Ð¿ÑÐ¸Ð½ÑÐ´Ð¸ÑÐµÐ»ÑÐ½Ð¾ ÑÐ»ÑÑ JSON Ð² UTF-8, ÑÑÐ¾Ð+/-Ñ Ð½Ðµ Ð+/-ÑÐ»Ð¾ ascii-Ð¾ÑÐ¸Ð+/-Ð¾Ðº;
    - Ð»Ð¾Ð³Ð¸ÑÑÐµÑ HTTP-ÑÑÐ°ÑÑÑ Ð¸ ÑÐµÐ»Ð¾ Ð¾ÑÐ¸Ð+/-ÐºÐ¸ Ð² Render-Ð»Ð¾Ð³Ð¸;
    - Ð´ÐµÐ»Ð°ÐµÑ Ð´Ð¾ 3 Ð¿Ð¾Ð¿ÑÑÐ¾Ðº Ñ Ð½ÐµÐ+/-Ð¾Ð»ÑÑÐ¾Ð¹ Ð¿Ð°ÑÐ·Ð¾Ð¹.
    """
    user_text = (user_text or "").strip()
    if not user_text:
        return "ÐÑÑÑÐ¾Ð¹ Ð·Ð°Ð¿ÑÐ¾Ñ."

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({
            "role": "system",
            "content": f"ÐÐ¾Ð½ÑÐµÐºÑÑ Ð¸Ð· Ð²ÐµÐ+/--Ð¿Ð¾Ð¸ÑÐºÐ°:\n{web_ctx}",
        })
    messages.append({"role": "user", "content": user_text})

    # ââ ÐÐ°Ð·Ð¾Ð²ÑÐ¹ URL âââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
    # ÐÑÐ»Ð¸ ÐºÐ»ÑÑ Ð¾Ñ OpenRouter Ð¸Ð»Ð¸ TEXT_PROVIDER=openrouter â ÑÐ»ÑÐ¼ Ð½Ð° OpenRouter
    provider = (TEXT_PROVIDER or "").strip().lower()
    if OPENAI_API_KEY.startswith("sk-or-") or provider == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
    else:
        base_url = (OPENAI_BASE_URL or "").strip() or "https://api.openai.com/v1"

    # ââ ÐÐ°Ð³Ð¾Ð»Ð¾Ð²ÐºÐ¸ âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept-Charset": "utf-8",
    }

    # Ð¡Ð»ÑÐ¶ÐµÐ+/-Ð½ÑÐµ Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²ÐºÐ¸ OpenRouter
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

            # ÐÐ¾Ð³Ð¸ÑÑÐµÐ¼ Ð²ÑÑ, ÑÑÐ¾ Ð½Ðµ 2xx
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
        "â ï¸ Ð¡ÐµÐ¹ÑÐ°Ñ Ð½Ðµ Ð¿Ð¾Ð»ÑÑÐ¸Ð»Ð¾ÑÑ Ð¿Ð¾Ð»ÑÑÐ¸ÑÑ Ð¾ÑÐ²ÐµÑ Ð¾Ñ Ð¼Ð¾Ð´ÐµÐ»Ð¸. "
        "Ð¯ Ð½Ð° ÑÐ²ÑÐ·Ð¸ â Ð¿Ð¾Ð¿ÑÐ¾Ð+/-ÑÐ¹ Ð¿ÐµÑÐµÑÐ¾ÑÐ¼ÑÐ»Ð¸ÑÐ¾Ð²Ð°ÑÑ Ð·Ð°Ð¿ÑÐ¾Ñ Ð¸Ð»Ð¸ Ð¿Ð¾Ð²ÑÐ¾ÑÐ¸ÑÑ ÑÑÑÑ Ð¿Ð¾Ð·Ð¶Ðµ."
    )
    

# âââââââââ Gemini (ÑÐµÑÐµÐ· CometAPI, Ð¾Ð¿ÑÐ¸Ð¾Ð½Ð°Ð»ÑÐ½Ð¾) âââââââââ

GEMINI_API_KEY   = (os.environ.get("GEMINI_API_KEY", "").strip() or COMETAPI_KEY)
GEMINI_BASE_URL  = os.environ.get("GEMINI_BASE_URL", "https://api.cometapi.com").strip().rstrip("/")
GEMINI_CHAT_PATH = os.environ.get("GEMINI_CHAT_PATH", "/gemini/v1/chat").strip()
GEMINI_MODEL     = os.environ.get("GEMINI_MODEL", "gemini-1.5-pro").strip()

async def ask_gemini_text(user_text: str) -> str:
    """
    ÐÐ¸Ð½Ð¸Ð¼Ð°Ð»ÑÐ½Ð°Ñ Ð¸Ð½ÑÐµÐ³ÑÐ°ÑÐ¸Ñ Gemini ÑÐµÑÐµÐ· CometAPI (Ð¸Ð»Ð¸ Ð»ÑÐ+/-Ð¾Ð¹ ÑÐ¾Ð²Ð¼ÐµÑÑÐ¸Ð¼ÑÐ¹ Ð¿ÑÐ¾ÐºÑÐ¸).
    ÐÑÐ»Ð¸ ÑÐ½Ð´Ð¿Ð¾Ð¸Ð½Ñ Ð¾ÑÐ»Ð¸ÑÐ°ÐµÑÑÑ â Ð¿Ð¾Ð¿ÑÐ°Ð²Ñ GEMINI_CHAT_PATH/GEMINI_BASE_URL Ð² ENV.
    """
    if not GEMINI_API_KEY:
        return "â ï¸ Gemini: Ð½Ðµ Ð·Ð°Ð´Ð°Ð½ GEMINI_API_KEY/COMETAPI_KEY. ÐÐ¾Ð+/-Ð°Ð²ÑÑÐµ ÐºÐ»ÑÑ Ð² Environment."
    if not user_text.strip():
        return ""

    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": GEMINI_MODEL,
        "prompt": user_text.strip(),
    }

    try:
        async with httpx.AsyncClient(base_url=GEMINI_BASE_URL, timeout=60.0) as client:
            r = await client.post(GEMINI_CHAT_PATH, headers=headers, json=payload)
        if r.status_code // 100 != 2:
            txt = (r.text or "")[:1200]
            log.warning("Gemini error %s: %s", r.status_code, txt)
            return "â ï¸ Gemini: Ð¾ÑÐ¸Ð+/-ÐºÐ° Ð·Ð°Ð¿ÑÐ¾ÑÐ°. ÐÑÐ¾Ð²ÐµÑÑÑÐµ GEMINI_CHAT_PATH/BASE_URL Ð¸ ÐºÐ»ÑÑ."
        js = r.json()
        # ÐÑÑÐ°ÐµÐ¼ÑÑ Ð²ÑÑÐ°ÑÐ¸ÑÑ ÑÐµÐºÑÑ Ð¸Ð· ÑÐ°Ð·Ð½ÑÑ ÑÑÐµÐ¼ Ð¾ÑÐ²ÐµÑÐ¾Ð²
        for k in ("text", "output", "result", "content", "message"):
            v = js.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # ÐÐ½Ð¾Ð³Ð´Ð° Ð¾ÑÐ²ÐµÑ Ð+/-ÑÐ²Ð°ÐµÑ Ð²Ð¸Ð´Ð° {"choices":[{"message":{"content":"..."}}]}
        ch = js.get("choices")
        if isinstance(ch, list) and ch:
            msg = (ch[0].get("message") or {})
            cont = msg.get("content")
            if isinstance(cont, str) and cont.strip():
                return cont.strip()
        return "â ï¸ Gemini: Ð¾ÑÐ²ÐµÑ Ð¿Ð¾Ð»ÑÑÐµÐ½, Ð½Ð¾ ÑÐ¾ÑÐ¼Ð°Ñ Ð½Ðµ ÑÐ°ÑÐ¿Ð¾Ð·Ð½Ð°Ð½. Ð¡Ð¼Ð¾ÑÑÐ¸ÑÐµ Ð»Ð¾Ð³Ð¸."
    except Exception as e:
        log.exception("Gemini request error: %s", e)
        return "â ï¸ Gemini: Ð¸ÑÐºÐ»ÑÑÐµÐ½Ð¸Ðµ Ð¿ÑÐ¸ Ð·Ð°Ð¿ÑÐ¾ÑÐµ. Ð¡Ð¼Ð¾ÑÑÐ¸ÑÐµ Ð»Ð¾Ð³Ð¸."

async def ask_openai_vision(user_text: str, img_b64: str, mime: str) -> str:
    try:
        prompt = (user_text or "ÐÐ¿Ð¸ÑÐ¸, ÑÑÐ¾ Ð½Ð° Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ð¸ Ð¸ ÐºÐ°ÐºÐ¾Ð¹ ÑÐ°Ð¼ ÑÐµÐºÑÑ.").strip()
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
        return "ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð¿ÑÐ¾Ð°Ð½Ð°Ð»Ð¸Ð·Ð¸ÑÐ¾Ð²Ð°ÑÑ Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ðµ."


# âââââââââ ÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»ÑÑÐºÐ¸Ðµ Ð½Ð°ÑÑÑÐ¾Ð¹ÐºÐ¸ (TTS) âââââââââ
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


# âââââââââ ÐÐ°Ð´ÑÐ¶Ð½ÑÐ¹ TTS ÑÐµÑÐµÐ· REST (OGG/Opus) âââââââââ
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
            "format": "ogg"  # OGG/Opus Ð´Ð»Ñ Telegram voice
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
                f"ð ÐÐ·Ð²ÑÑÐºÐ° Ð²ÑÐºÐ»ÑÑÐµÐ½Ð° Ð´Ð»Ñ ÑÑÐ¾Ð³Ð¾ ÑÐ¾Ð¾Ð+/-ÑÐµÐ½Ð¸Ñ: ÑÐµÐºÑÑ Ð´Ð»Ð¸Ð½Ð½ÐµÐµ {TTS_MAX_CHARS} ÑÐ¸Ð¼Ð²Ð¾Ð»Ð¾Ð²."
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
                await update.effective_message.reply_text("ð ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ¸Ð½ÑÐµÐ·Ð¸ÑÐ¾Ð²Ð°ÑÑ Ð³Ð¾Ð»Ð¾Ñ.")
            return
        bio = BytesIO(audio); bio.seek(0); bio.name = "say.ogg"
        await update.effective_message.reply_voice(voice=InputFile(bio), caption=text)
    except Exception as e:
        log.exception("maybe_tts_reply error: %s", e)

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, True)
    await update.effective_message.reply_text(f"ð ÐÐ·Ð²ÑÑÐºÐ° Ð²ÐºÐ»ÑÑÐµÐ½Ð°. ÐÐ¸Ð¼Ð¸Ñ {TTS_MAX_CHARS} ÑÐ¸Ð¼Ð²Ð¾Ð»Ð¾Ð² Ð½Ð° Ð¾ÑÐ²ÐµÑ.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, False)
    await update.effective_message.reply_text("ð ÐÐ·Ð²ÑÑÐºÐ° Ð²ÑÐºÐ»ÑÑÐµÐ½Ð°.")

# âââââââââ Speech-to-Text (STT) â¢ OpenAI Whisper/4o-mini-transcribe âââââââââ
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

# âââââââââ Ð¥ÐµÐ½Ð´Ð»ÐµÑ Ð³Ð¾Ð»Ð¾ÑÐ¾Ð²ÑÑ/Ð°ÑÐ´Ð¸Ð¾ âââââââââ
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    voice = getattr(msg, "voice", None)
    audio = getattr(msg, "audio", None)
    media = voice or audio
    if not media:
        await msg.reply_text("ÐÐµ Ð½Ð°ÑÑÐ» Ð³Ð¾Ð»Ð¾ÑÐ¾Ð²Ð¾Ð¹ ÑÐ°Ð¹Ð».")
        return

    # Ð¡ÐºÐ°ÑÐ¸Ð²Ð°ÐµÐ¼ ÑÐ°Ð¹Ð»
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
        await msg.reply_text("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐºÐ°ÑÐ°ÑÑ Ð³Ð¾Ð»Ð¾ÑÐ¾Ð²Ð¾Ðµ ÑÐ¾Ð¾Ð+/-ÑÐµÐ½Ð¸Ðµ.")
        return

    # STT
    transcript = await _stt_transcribe_bytes(filename, raw)
    if not transcript:
        await msg.reply_text("ÐÑÐ¸Ð+/-ÐºÐ° Ð¿ÑÐ¸ ÑÐ°ÑÐ¿Ð¾Ð·Ð½Ð°Ð²Ð°Ð½Ð¸Ð¸ ÑÐµÑÐ¸.")
        return

    transcript = transcript.strip()

    # ÐÐ¾ÐºÐ°Ð·ÑÐ²Ð°ÐµÐ¼ ÑÐµÐºÑÑ Ð´Ð»Ñ Ð¾ÑÐ»Ð°Ð´ÐºÐ¸
    with contextlib.suppress(Exception):
        await msg.reply_text(f"ð£ï¸ Ð Ð°ÑÐ¿Ð¾Ð·Ð½Ð°Ð»: {transcript}")

    # âââ ÐÐÐ®Ð§ÐÐÐÐ ÐÐÐÐÐÐ¢ âââ
    # ÐÐ¾Ð»ÑÑÐµ ÐÐ ÑÐ¾Ð·Ð´Ð°ÑÐ¼ ÑÐµÐ¹ÐºÐ¾Ð²ÑÐ¹ Update, Ð½Ðµ Ð»ÐµÐ·ÐµÐ¼ Ð² Message.text â ÑÑÐ¾ Ð·Ð°Ð¿ÑÐµÑÐµÐ½Ð¾ Ð² Telegram API
    # Ð¢ÐµÐ¿ÐµÑÑ Ð¼Ñ Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÐ¼ Ð+/-ÐµÐ·Ð¾Ð¿Ð°ÑÐ½ÑÐ¹ Ð¿ÑÐ¾ÐºÑÐ¸-Ð¼ÐµÑÐ¾Ð´, ÐºÐ¾ÑÐ¾ÑÑÐ¹ ÑÐ¾Ð·Ð´Ð°ÑÑ Ð²ÑÐµÐ¼ÐµÐ½Ð½ÑÐ¹ message-Ð¾Ð+/-ÑÐµÐºÑ
    try:
        await on_text_with_text(update, context, transcript)
    except Exception as e:
        log.exception("Voice->text handler error: %s", e)
        await msg.reply_text("Ð£Ð¿Ñ, Ð¿ÑÐ¾Ð¸Ð·Ð¾ÑÐ»Ð° Ð¾ÑÐ¸Ð+/-ÐºÐ°. Ð¯ ÑÐ¶Ðµ ÑÐ°Ð·Ð+/-Ð¸ÑÐ°ÑÑÑ.")
        
# âââââââââ ÐÐ·Ð²Ð»ÐµÑÐµÐ½Ð¸Ðµ ÑÐµÐºÑÑÐ° Ð¸Ð· Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÐ¾Ð² âââââââââ
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


# âââââââââ Ð¡ÑÐ¼Ð¼Ð°ÑÐ¸Ð·Ð°ÑÐ¸Ñ Ð´Ð»Ð¸Ð½Ð½ÑÑ ÑÐµÐºÑÑÐ¾Ð² âââââââââ
async def _summarize_chunk(text: str, query: str | None = None) -> str:
    prefix = "Ð¡ÑÐ¼Ð¼Ð¸ÑÑÐ¹ ÐºÑÐ°ÑÐºÐ¾ Ð¿Ð¾ Ð¿ÑÐ½ÐºÑÐ°Ð¼ Ð¾ÑÐ½Ð¾Ð²Ð½Ð¾Ðµ Ð¸Ð· ÑÑÐ°Ð³Ð¼ÐµÐ½ÑÐ° Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÐ° Ð½Ð° ÑÑÑÑÐºÐ¾Ð¼:\n"
    if query:
        prefix = (f"Ð¡ÑÐ¼Ð¼Ð¸ÑÑÐ¹ ÑÑÐ°Ð³Ð¼ÐµÐ½Ñ Ñ ÑÑÑÑÐ¾Ð¼ ÑÐµÐ»Ð¸: {query}\n"
                  f"ÐÐ°Ð¹ Ð¾ÑÐ½Ð¾Ð²Ð½ÑÐµ ÑÐµÐ·Ð¸ÑÑ, ÑÐ°ÐºÑÑ, ÑÐ¸ÑÑÑ. Ð ÑÑÑÐºÐ¸Ð¹ ÑÐ·ÑÐº.\n")
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
    combined = "\n\n".join(f"- Ð¤ÑÐ°Ð³Ð¼ÐµÐ½Ñ {idx+1}:\n{s}" for idx, s in enumerate(partials))
    final_prompt = ("ÐÐ+/-ÑÐµÐ´Ð¸Ð½Ð¸ ÑÐµÐ·Ð¸ÑÑ Ð¿Ð¾ ÑÑÐ°Ð³Ð¼ÐµÐ½ÑÐ°Ð¼ Ð² ÑÐµÐ»ÑÐ½Ð¾Ðµ ÑÐµÐ·ÑÐ¼Ðµ Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÐ°: 1) 5â10 Ð³Ð»Ð°Ð²Ð½ÑÑ Ð¿ÑÐ½ÐºÑÐ¾Ð²; "
                    "2) ÐºÐ»ÑÑÐµÐ²ÑÐµ ÑÐ¸ÑÑÑ/ÑÑÐ¾ÐºÐ¸; 3) Ð²ÑÐ²Ð¾Ð´/ÑÐµÐºÐ¾Ð¼ÐµÐ½Ð´Ð°ÑÐ¸Ð¸. Ð ÑÑÑÐºÐ¸Ð¹ ÑÐ·ÑÐº.\n\n" + combined)
    return await ask_openai_text(final_prompt)


# ======= ÐÐ½Ð°Ð»Ð¸Ð· Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÐ¾Ð² (PDF/EPUB/DOCX/FB2/TXT) =======
async def on_doc_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document:
            return
        doc = update.message.document
        tg_file = await doc.get_file()
        data = await tg_file.download_as_bytearray()
        text, kind = extract_text_from_document(bytes(data), doc.file_name or "file")
        if not text.strip():
            await update.effective_message.reply_text(f"ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð¸Ð·Ð²Ð»ÐµÑÑ ÑÐµÐºÑÑ Ð¸Ð· {kind}.")
            return
        goal = (update.message.caption or "").strip() or None
        await update.effective_message.reply_text(f"ð ÐÐ·Ð²Ð»ÐµÐºÐ°Ñ ÑÐµÐºÑÑ ({kind}), Ð³Ð¾ÑÐ¾Ð²Ð»Ñ ÐºÐ¾Ð½ÑÐ¿ÐµÐºÑâ¦")
        summary = await summarize_long_text(text, query=goal)
        summary = summary or "ÐÐ¾ÑÐ¾Ð²Ð¾."
        await update.effective_message.reply_text(summary)
        await maybe_tts_reply(update, context, summary[:TTS_MAX_CHARS])
    except Exception as e:
        log.exception("on_doc_analyze error: %s", e)
    # Ð½Ð¸ÑÐµÐ³Ð¾ Ð½Ðµ Ð+/-ÑÐ¾ÑÐ°ÐµÐ¼ Ð½Ð°ÑÑÐ¶Ñ

# âââââââââ OpenAI Images (Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ñ ÐºÐ°ÑÑÐ¸Ð½Ð¾Ðº) âââââââââ
async def _do_img_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
        b64 = resp.data[0].b64_json
        img_bytes = base64.b64decode(b64)
        await update.effective_message.reply_photo(photo=img_bytes, caption=f"ÐÐ¾ÑÐ¾Ð²Ð¾ â\nÐÐ°Ð¿ÑÐ¾Ñ: {prompt}")
    except Exception as e:
        log.exception("IMG gen error: %s", e)
        await update.effective_message.reply_text("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ¾Ð·Ð´Ð°ÑÑ Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ðµ.")

async def _luma_generate_image_bytes(prompt: str) -> bytes | None:
    if not LUMA_IMG_BASE_URL or not LUMA_API_KEY:
        # ÑÐ¾Ð»Ð+/-ÑÐº: OpenAI Images
        try:
            resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
            return base64.b64decode(resp.data[0].b64_json)
        except Exception as e:
            log.exception("OpenAI images fallback error: %s", e)
            return None
    try:
        # ÐÑÐ¸Ð¼ÐµÑÐ½ÑÐ¹ ÑÐ½Ð´Ð¿Ð¾Ð¸Ð½Ñ; ÐµÑÐ»Ð¸ Ñ ÑÐµÐ+/-Ñ Ð´ÑÑÐ³Ð¾Ð¹ â Ð·Ð°Ð¼ÐµÐ½Ð¸ path/Ð¿Ð¾Ð»Ñ Ð¿Ð¾Ð´ ÑÐ²Ð¾Ð¹ Ð°ÐºÐºÐ°ÑÐ½Ñ.
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
            await update.effective_message.reply_text("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ¾Ð·Ð´Ð°ÑÑ Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ðµ.")
            return
        await update.effective_message.reply_photo(photo=img, caption=f"ð ÐÐ¾ÑÐ¾Ð²Ð¾ â\nÐÐ°Ð¿ÑÐ¾Ñ: {prompt}")
    await _try_pay_then_do(update, context, update.effective_user.id, "img", IMG_COST_USD, _go,
                           remember_kind="luma_img", remember_payload={"prompt": prompt})


# âââââââââ UI / ÑÐµÐºÑÑÑ âââââââââ
START_TEXT = (
    "ÐÑÐ¸Ð²ÐµÑ! Ð¯ ÐÐµÐ¹ÑÐ¾-Bot â â¡ï¸ Ð¼ÑÐ»ÑÑÐ¸ÑÐµÐ¶Ð¸Ð¼Ð½ÑÐ¹ Ð+/-Ð¾Ñ Ð¸Ð· 7 Ð½ÐµÐ¹ÑÐ¾ÑÐµÑÐµÐ¹ Ð´Ð»Ñ ð ÑÑÑÐ+/-Ñ, ð¼ ÑÐ°Ð+/-Ð¾ÑÑ Ð¸ ð¥ ÑÐ°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ð¹.\n"
    "Ð¯ ÑÐ¼ÐµÑ ÑÐ°Ð+/-Ð¾ÑÐ°ÑÑ Ð³Ð¸Ð+/-ÑÐ¸Ð´Ð½Ð¾: Ð¼Ð¾Ð³Ñ ÑÐ°Ð¼ Ð²ÑÐ+/-ÑÐ°ÑÑ Ð»ÑÑÑÐ¸Ð¹ Ð´Ð²Ð¸Ð¶Ð¾Ðº Ð¿Ð¾Ð´ Ð·Ð°Ð´Ð°ÑÑ Ð¸Ð»Ð¸ Ð´Ð°ÑÑ ÑÐµÐ+/-Ðµ Ð²ÑÐ+/-ÑÐ°ÑÑ Ð²ÑÑÑÐ½ÑÑ. ð¤ð§ \n"
    "\n"
    "â¨ ÐÐ»Ð°Ð²Ð½ÑÐµ ÑÐµÐ¶Ð¸Ð¼Ñ:\n"
    "\n"
    "\n"
    "â¢ ð Ð£ÑÑÐ+/-Ð° â Ð¾Ð+/-ÑÑÑÐ½ÐµÐ½Ð¸Ñ Ñ Ð¿ÑÐ¸Ð¼ÐµÑÐ°Ð¼Ð¸, Ð¿Ð¾ÑÐ°Ð³Ð¾Ð²ÑÐµ ÑÐµÑÐµÐ½Ð¸Ñ Ð·Ð°Ð´Ð°Ñ, ÑÑÑÐµ/ÑÐµÑÐµÑÐ°Ñ/Ð´Ð¾ÐºÐ»Ð°Ð´, Ð¼Ð¸Ð½Ð¸-ÐºÐ²Ð¸Ð·Ñ.\n"
    "ð Ð¢Ð°ÐºÐ¶Ðµ: ÑÐ°Ð·Ð+/-Ð¾Ñ ÑÑÐµÐ+/-Ð½ÑÑ PDF/ÑÐ»ÐµÐºÑÑÐ¾Ð½Ð½ÑÑ ÐºÐ½Ð¸Ð³, ÑÐ¿Ð°ÑÐ³Ð°Ð»ÐºÐ¸ Ð¸ ÐºÐ¾Ð½ÑÐ¿ÐµÐºÑÑ, ÐºÐ¾Ð½ÑÑÑÑÐºÑÐ¾Ñ ÑÐµÑÑÐ¾Ð²;\n"
    "ð§ ÑÐ°Ð¹Ð¼-ÐºÐ¾Ð´Ñ Ð¿Ð¾ Ð°ÑÐ´Ð¸Ð¾ÐºÐ½Ð¸Ð³Ð°Ð¼/Ð»ÐµÐºÑÐ¸ÑÐ¼ Ð¸ ÐºÑÐ°ÑÐºÐ¸Ðµ Ð²ÑÐ¶Ð¸Ð¼ÐºÐ¸. ð§©\n"
    "\n"
    "â¢ ð¼ Ð Ð°Ð+/-Ð¾ÑÐ° â Ð¿Ð¸ÑÑÐ¼Ð°/Ð+/-ÑÐ¸ÑÑ/Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÑ, Ð°Ð½Ð°Ð»Ð¸ÑÐ¸ÐºÐ° Ð¸ ÑÐµÐ·ÑÐ¼Ðµ Ð¼Ð°ÑÐµÑÐ¸Ð°Ð»Ð¾Ð², ToDo/Ð¿Ð»Ð°Ð½Ñ, Ð³ÐµÐ½ÐµÑÐ°ÑÐ¾Ñ Ð¸Ð´ÐµÐ¹.\n"
    "ð ï¸ ÐÐ»Ñ Ð°ÑÑÐ¸ÑÐµÐºÑÐ¾ÑÐ°/Ð´Ð¸Ð·Ð°Ð¹Ð½ÐµÑÐ°/Ð¿ÑÐ¾ÐµÐºÑÐ¸ÑÐ¾Ð²ÑÐ¸ÐºÐ°: ÑÑÑÑÐºÑÑÑÐ¸ÑÐ¾Ð²Ð°Ð½Ð¸Ðµ Ð¢Ð, ÑÐµÐº-Ð»Ð¸ÑÑÑ ÑÑÐ°Ð´Ð¸Ð¹,\n"
    "ðï¸ Ð½Ð°Ð·Ð²Ð°Ð½Ð¸Ñ/Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ñ Ð»Ð¸ÑÑÐ¾Ð², ÑÐ²Ð¾Ð´Ð½ÑÐµ ÑÐ°Ð+/-Ð»Ð¸ÑÑ Ð¸Ð· ÑÐµÐºÑÑÐ¾Ð², Ð¾ÑÐ¾ÑÐ¼Ð»ÐµÐ½Ð¸Ðµ Ð¿Ð¾ÑÑÐ½Ð¸ÑÐµÐ»ÑÐ½ÑÑ Ð·Ð°Ð¿Ð¸ÑÐ¾Ðº. ð\n"
    "\n"
    "â¢ ð¥ Ð Ð°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ñ â ÑÐ¾ÑÐ¾-Ð¼Ð°ÑÑÐµÑÑÐºÐ°Ñ (ÑÐ´Ð°Ð»ÐµÐ½Ð¸Ðµ/Ð·Ð°Ð¼ÐµÐ½Ð° ÑÐ¾Ð½Ð°, Ð´Ð¾ÑÐ¸ÑÐ¾Ð²ÐºÐ°, outpaint), Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ðµ ÑÑÐ°ÑÑÑ ÑÐ¾ÑÐ¾,\n"
    "ð¬ Ð²Ð¸Ð´ÐµÐ¾ Ð¿Ð¾ ÑÐµÐºÑÑÑ/Ð³Ð¾Ð»Ð¾ÑÑ, Ð¸Ð´ÐµÐ¸ Ð¸ ÑÐ¾ÑÐ¼Ð°ÑÑ Ð´Ð»Ñ Reels/Shorts, Ð°Ð²ÑÐ¾-Ð½Ð°ÑÐµÐ·ÐºÐ° Ð¸Ð· Ð´Ð»Ð¸Ð½Ð½ÑÑ Ð²Ð¸Ð´ÐµÐ¾\n"
    "(ÑÑÐµÐ½Ð°ÑÐ¸Ð¹/ÑÐ°Ð¹Ð¼-ÐºÐ¾Ð´Ñ), Ð¼ÐµÐ¼Ñ/ÐºÐ²Ð¸Ð·Ñ. ð¼ï¸ðª\n"
    "\n"
    "ð§ ÐÐ°Ðº Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÑÑÑ:\n"
    "Ð¿ÑÐ¾ÑÑÐ¾ Ð²ÑÐ+/-ÐµÑÐ¸ ÑÐµÐ¶Ð¸Ð¼ ÐºÐ½Ð¾Ð¿ÐºÐ¾Ð¹ Ð½Ð¸Ð¶Ðµ Ð¸Ð»Ð¸ Ð½Ð°Ð¿Ð¸ÑÐ¸ Ð·Ð°Ð¿ÑÐ¾Ñ â Ñ ÑÐ°Ð¼ Ð¾Ð¿ÑÐµÐ´ÐµÐ»Ñ Ð·Ð°Ð´Ð°ÑÑ Ð¸ Ð¿ÑÐµÐ´Ð»Ð¾Ð¶Ñ Ð²Ð°ÑÐ¸Ð°Ð½ÑÑ. âï¸â¨\n"
    "\n"
    "ð§  ÐÐ½Ð¾Ð¿ÐºÐ° Â«ÐÐ²Ð¸Ð¶ÐºÐ¸Â»:\n"
    "Ð´Ð»Ñ ÑÐ¾ÑÐ½Ð¾Ð³Ð¾ Ð²ÑÐ+/-Ð¾ÑÐ°, ÐºÐ°ÐºÑÑ Ð½ÐµÐ¹ÑÐ¾ÑÐµÑÑ Ð¸ÑÐ¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÑ Ð¿ÑÐ¸Ð½ÑÐ´Ð¸ÑÐµÐ»ÑÐ½Ð¾. ð¯ð¤"
)

def engines_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ð¬ GPT (ÑÐµÐºÑÑ/ÑÐ¾ÑÐ¾/Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÑ)", callback_data="engine:gpt")],
        [InlineKeyboardButton("ð¼ Images (OpenAI)",             callback_data="engine:images")],
        [InlineKeyboardButton("ð Kling â ÐºÐ»Ð¸Ð¿Ñ / ÑÐ¾ÑÑÑ",       callback_data="engine:kling")],
        [InlineKeyboardButton("ð¬ Luma â ÐºÐ¾ÑÐ¾ÑÐºÐ¸Ðµ Ð²Ð¸Ð´ÐµÐ¾",       callback_data="engine:luma")],
        [InlineKeyboardButton("ð¥ Runway â Ð¿ÑÐµÐ¼Ð¸ÑÐ¼-Ð²Ð¸Ð´ÐµÐ¾",      callback_data="engine:runway")],
        [InlineKeyboardButton("ð¬ Sora â Ð²Ð¸Ð´ÐµÐ¾ (Comet)",        callback_data="engine:sora")],
        [InlineKeyboardButton("ð§  Gemini (Comet)",             callback_data="engine:gemini")],
        [InlineKeyboardButton("ðµ Suno (music)",               callback_data="engine:suno")],
        [InlineKeyboardButton("ð¨ Midjourney (Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ñ)",    callback_data="engine:midjourney")],
        [InlineKeyboardButton("ð£ STT/TTS â ÑÐµÑÑâÑÐµÐºÑÑ",        callback_data="engine:stt_tts")],
    ])
# âââââââââ MODES (Ð£ÑÑÐ+/-Ð° / Ð Ð°Ð+/-Ð¾ÑÐ° / Ð Ð°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ñ) âââââââââ

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackQueryHandler, MessageHandler, filters

# Ð¢ÐµÐºÑÑ ÐºÐ¾ÑÐ½ÐµÐ²Ð¾Ð³Ð¾ Ð¼ÐµÐ½Ñ ÑÐµÐ¶Ð¸Ð¼Ð¾Ð²
def _modes_root_text() -> str:
    return (
        "ÐÑÐ+/-ÐµÑÐ¸ÑÐµ ÑÐµÐ¶Ð¸Ð¼ ÑÐ°Ð+/-Ð¾ÑÑ. Ð ÐºÐ°Ð¶Ð´Ð¾Ð¼ ÑÐµÐ¶Ð¸Ð¼Ðµ Ð+/-Ð¾Ñ Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÑ Ð³Ð¸Ð+/-ÑÐ¸Ð´ Ð´Ð²Ð¸Ð¶ÐºÐ¾Ð²:\n"
        "â¢ GPT-5 (ÑÐµÐºÑÑ/Ð»Ð¾Ð³Ð¸ÐºÐ°) + Vision (ÑÐ¾ÑÐ¾) + STT/TTS (Ð³Ð¾Ð»Ð¾Ñ)\n"
        "â¢ Luma/Runway â Ð²Ð¸Ð´ÐµÐ¾, Midjourney â Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ñ\n\n"
        "ÐÐ¾Ð¶ÐµÑÐµ ÑÐ°ÐºÐ¶Ðµ Ð¿ÑÐ¾ÑÑÐ¾ Ð½Ð°Ð¿Ð¸ÑÐ°ÑÑ ÑÐ²Ð¾Ð+/-Ð¾Ð´Ð½ÑÐ¹ Ð·Ð°Ð¿ÑÐ¾Ñ â Ð+/-Ð¾Ñ Ð¿Ð¾Ð¹Ð¼ÑÑ."
    )

def modes_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("ð Ð£ÑÑÐ+/-Ð°", callback_data="mode:study"),
            InlineKeyboardButton("ð¼ Ð Ð°Ð+/-Ð¾ÑÐ°", callback_data="mode:work"),
            InlineKeyboardButton("ð¥ Ð Ð°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ñ", callback_data="mode:fun"),
        ],
    ])

# ââ ÐÐ¿Ð¸ÑÐ°Ð½Ð¸Ðµ Ð¸ Ð¿Ð¾Ð´Ð¼ÐµÐ½Ñ Ð¿Ð¾ ÑÐµÐ¶Ð¸Ð¼Ð°Ð¼
def _mode_desc(key: str) -> str:
    if key == "study":
        return (
            "ð *Ð£ÑÑÐ+/-Ð°*\n"
            "ÐÐ¸Ð+/-ÑÐ¸Ð´: GPT-5 Ð´Ð»Ñ Ð¾Ð+/-ÑÑÑÐ½ÐµÐ½Ð¸Ð¹/ÐºÐ¾Ð½ÑÐ¿ÐµÐºÑÐ¾Ð², Vision Ð´Ð»Ñ ÑÐ¾ÑÐ¾-Ð·Ð°Ð´Ð°Ñ, "
            "STT/TTS Ð´Ð»Ñ Ð³Ð¾Ð»Ð¾ÑÐ¾Ð²ÑÑ, + Midjourney (Ð¸Ð»Ð»ÑÑÑÑÐ°ÑÐ¸Ð¸) Ð¸ Luma/Runway (ÑÑÐµÐ+/-Ð½ÑÐµ ÑÐ¾Ð»Ð¸ÐºÐ¸).\n\n"
            "ÐÑÑÑÑÑÐµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ñ Ð½Ð¸Ð¶Ðµ. ÐÐ¾Ð¶Ð½Ð¾ Ð½Ð°Ð¿Ð¸ÑÐ°ÑÑ ÑÐ²Ð¾Ð+/-Ð¾Ð´Ð½ÑÐ¹ Ð·Ð°Ð¿ÑÐ¾Ñ (Ð½Ð°Ð¿ÑÐ¸Ð¼ÐµÑ: "
            "Â«ÑÐ´ÐµÐ»Ð°Ð¹ ÐºÐ¾Ð½ÑÐ¿ÐµÐºÑ Ð¸Ð· PDFÂ», Â«Ð¾Ð+/-ÑÑÑÐ½Ð¸ Ð¸Ð½ÑÐµÐ³ÑÐ°Ð»Ñ Ñ Ð¿ÑÐ¸Ð¼ÐµÑÐ°Ð¼Ð¸Â»)."
        )
    if key == "work":
        return (
            "ð¼ *Ð Ð°Ð+/-Ð¾ÑÐ°*\n"
            "ÐÐ¸Ð+/-ÑÐ¸Ð´: GPT-5 (ÑÐµÐ·ÑÐ¼Ðµ/Ð¿Ð¸ÑÑÐ¼Ð°/Ð°Ð½Ð°Ð»Ð¸ÑÐ¸ÐºÐ°), Vision (ÑÐ°Ð+/-Ð»Ð¸ÑÑ/ÑÐºÑÐ¸Ð½Ñ), "
            "STT/TTS (Ð´Ð¸ÐºÑÐ¾Ð²ÐºÐ°/Ð¾Ð·Ð²ÑÑÐºÐ°), + Midjourney (Ð²Ð¸Ð·ÑÐ°Ð»Ñ), Luma/Runway (Ð¿ÑÐµÐ·ÐµÐ½ÑÐ°ÑÐ¸Ð¾Ð½Ð½ÑÐµ ÑÐ¾Ð»Ð¸ÐºÐ¸).\n\n"
            "ÐÑÑÑÑÑÐµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ñ Ð½Ð¸Ð¶Ðµ. ÐÐ¾Ð¶Ð½Ð¾ Ð½Ð°Ð¿Ð¸ÑÐ°ÑÑ ÑÐ²Ð¾Ð+/-Ð¾Ð´Ð½ÑÐ¹ Ð·Ð°Ð¿ÑÐ¾Ñ (Ð½Ð°Ð¿ÑÐ¸Ð¼ÐµÑ: "
            "Â«Ð°Ð´Ð°Ð¿ÑÐ¸ÑÑÐ¹ ÑÐµÐ·ÑÐ¼Ðµ Ð¿Ð¾Ð´ Ð²Ð°ÐºÐ°Ð½ÑÐ¸Ñ PMÂ», Â«Ð½Ð°Ð¿Ð¸ÑÐ°ÑÑ ÐºÐ¾Ð¼Ð¼ÐµÑÑÐµÑÐºÐ¾Ðµ Ð¿ÑÐµÐ´Ð»Ð¾Ð¶ÐµÐ½Ð¸ÐµÂ»)."
        )
    if key == "fun":
        return (
            "ð¥ *Ð Ð°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ñ*\n"
            "ÐÐ¸Ð+/-ÑÐ¸Ð´: GPT-5 (Ð¸Ð´ÐµÐ¸, ÑÑÐµÐ½Ð°ÑÐ¸Ð¸), Midjourney (ÐºÐ°ÑÑÐ¸Ð½ÐºÐ¸), Luma/Runway (ÑÐ¾ÑÑÑ/ÑÐ¸ÐµÐ»ÑÑ), "
            "STT/TTS (Ð¾Ð·Ð²ÑÑÐºÐ°). ÐÑÑ Ð´Ð»Ñ Ð+/-ÑÑÑÑÑÑ ÑÐ²Ð¾ÑÑÐµÑÐºÐ¸Ñ ÑÑÑÐº.\n\n"
            "ÐÑÑÑÑÑÐµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ñ Ð½Ð¸Ð¶Ðµ. ÐÐ¾Ð¶Ð½Ð¾ Ð½Ð°Ð¿Ð¸ÑÐ°ÑÑ ÑÐ²Ð¾Ð+/-Ð¾Ð´Ð½ÑÐ¹ Ð·Ð°Ð¿ÑÐ¾Ñ (Ð½Ð°Ð¿ÑÐ¸Ð¼ÐµÑ: "
            "Â«ÑÐ´ÐµÐ»Ð°Ð¹ ÑÑÐµÐ½Ð°ÑÐ¸Ð¹ 30-ÑÐµÐº ÑÐ¾ÑÑÐ° Ð¿ÑÐ¾ ÐºÐ¾ÑÐ°-Ð+/-Ð°ÑÐ¸ÑÑÐ°Â»)."
        )
    return "Ð ÐµÐ¶Ð¸Ð¼ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½."

def _mode_kb(key: str) -> InlineKeyboardMarkup:
    if key == "study":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("ð ÐÐ¾Ð½ÑÐ¿ÐµÐºÑ Ð¸Ð· PDF/EPUB/DOCX", callback_data="act:study:pdf_summary")],
            [InlineKeyboardButton("ð ÐÐ+/-ÑÑÑÐ½ÐµÐ½Ð¸Ðµ ÑÐµÐ¼Ñ",            callback_data="act:study:explain"),
             InlineKeyboardButton("ð§® Ð ÐµÑÐµÐ½Ð¸Ðµ Ð·Ð°Ð´Ð°Ñ",              callback_data="act:study:tasks")],
            [InlineKeyboardButton("âï¸ ÐÑÑÐµ/ÑÐµÑÐµÑÐ°Ñ/Ð´Ð¾ÐºÐ»Ð°Ð´",       callback_data="act:study:essay"),
             InlineKeyboardButton("ð ÐÐ»Ð°Ð½ Ðº ÑÐºÐ·Ð°Ð¼ÐµÐ½Ñ",           callback_data="act:study:exam_plan")],
            [
                InlineKeyboardButton("ð¬ Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("ð¨ Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("ð£ STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("ð Ð¡Ð²Ð¾Ð+/-Ð¾Ð´Ð½ÑÐ¹ Ð·Ð°Ð¿ÑÐ¾Ñ", callback_data="act:free")],
            [InlineKeyboardButton("â¬ï¸ ÐÐ°Ð·Ð°Ð´", callback_data="mode:root")],
        ])

    if key == "work":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("ð ÐÐ¸ÑÑÐ¼Ð¾/Ð´Ð¾ÐºÑÐ¼ÐµÐ½Ñ",            callback_data="act:work:doc"),
             InlineKeyboardButton("ð ÐÐ½Ð°Ð»Ð¸ÑÐ¸ÐºÐ°/ÑÐ²Ð¾Ð´ÐºÐ°",           callback_data="act:work:report")],
            [InlineKeyboardButton("ð ÐÐ»Ð°Ð½/ToDo",                  callback_data="act:work:plan"),
             InlineKeyboardButton("ð¡ ÐÐ´ÐµÐ¸/Ð+/-ÑÐ¸Ñ",                 callback_data="act:work:idea")],
            [
                InlineKeyboardButton("ð¬ Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("ð¨ Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("ð£ STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("ð Ð¡Ð²Ð¾Ð+/-Ð¾Ð´Ð½ÑÐ¹ Ð·Ð°Ð¿ÑÐ¾Ñ", callback_data="act:free")],
            [InlineKeyboardButton("â¬ï¸ ÐÐ°Ð·Ð°Ð´", callback_data="mode:root")],
        ])

    if key == "fun":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("ð ÐÐ´ÐµÐ¸ Ð´Ð»Ñ Ð´Ð¾ÑÑÐ³Ð°",             callback_data="act:fun:ideas")],
            [InlineKeyboardButton("ð¬ Ð¡ÑÐµÐ½Ð°ÑÐ¸Ð¹ ÑÐ¾ÑÑÐ°",              callback_data="act:fun:shorts")],
            [InlineKeyboardButton("ð® ÐÐ³ÑÑ/ÐºÐ²Ð¸Ð·",                   callback_data="act:fun:games")],
            [
                InlineKeyboardButton("ð¬ Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("ð¨ Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("ð£ STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("ð Ð¡Ð²Ð¾Ð+/-Ð¾Ð´Ð½ÑÐ¹ Ð·Ð°Ð¿ÑÐ¾Ñ", callback_data="act:free")],
            [InlineKeyboardButton("â¬ï¸ ÐÐ°Ð·Ð°Ð´", callback_data="mode:root")],
        ])

    return modes_root_kb()

# ÐÐ¾ÐºÐ°Ð·Ð°ÑÑ Ð²ÑÐ+/-ÑÐ°Ð½Ð½ÑÐ¹ ÑÐµÐ¶Ð¸Ð¼ (Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÑÑÑ Ð¸ Ð´Ð»Ñ callback, Ð¸ Ð´Ð»Ñ ÑÐµÐºÑÑÐ°)
async def _send_mode_menu(update, context, key: str):
    text = _mode_desc(key)
    kb = _mode_kb(key)
    # ÐÑÐ»Ð¸ Ð¿ÑÐ¸ÑÐ»Ð¸ Ð¸Ð· callback â ÑÐµÐ´Ð°ÐºÑÐ¸ÑÑÐµÐ¼; ÐµÑÐ»Ð¸ ÑÐµÐºÑÑÐ¾Ð¼ â ÑÐ»ÑÐ¼ Ð½Ð¾Ð²ÑÐ¼ ÑÐ¾Ð¾Ð+/-ÑÐµÐ½Ð¸ÐµÐ¼
    if getattr(update, "callback_query", None):
        q = update.callback_query
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        await q.answer()
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# ÐÐ+/-ÑÐ°Ð+/-Ð¾ÑÑÐ¸Ðº callback Ð¿Ð¾ ÑÐµÐ¶Ð¸Ð¼Ð°Ð¼
async def on_mode_cb(update, context):
    q = update.callback_query
    data = (q.data or "").strip()
    uid = q.from_user.id

    # ÐÐ°Ð²Ð¸Ð³Ð°ÑÐ¸Ñ
    if data == "mode:root":
        await q.edit_message_text(_modes_root_text(), reply_markup=modes_root_kb())
        await q.answer(); return

    if data.startswith("mode:"):
        _, key = data.split(":", 1)
        await _send_mode_menu(update, context, key)
        return

    # Ð¡Ð²Ð¾Ð+/-Ð¾Ð´Ð½ÑÐ¹ Ð²Ð²Ð¾Ð´ Ð¸Ð· Ð¿Ð¾Ð´Ð¼ÐµÐ½Ñ
    if data == "act:free":
        await q.answer()
        await q.edit_message_text(
            "ð ÐÐ°Ð¿Ð¸ÑÐ¸ÑÐµ ÑÐ²Ð¾Ð+/-Ð¾Ð´Ð½ÑÐ¹ Ð·Ð°Ð¿ÑÐ¾Ñ Ð½Ð¸Ð¶Ðµ ÑÐµÐºÑÑÐ¾Ð¼ Ð¸Ð»Ð¸ Ð³Ð¾Ð»Ð¾ÑÐ¾Ð¼ â Ñ Ð¿Ð¾Ð´ÑÑÑÐ¾ÑÑÑ.",
            reply_markup=modes_root_kb(),
        )
        return

    # === Ð£ÑÑÐ+/-Ð°
    if data == "act:study:pdf_summary":
        await q.answer()
        _mode_track_set(uid, "pdf_summary")
        await q.edit_message_text(
            "ð ÐÑÐ¸ÑÐ»Ð¸ÑÐµ PDF/EPUB/DOCX/FB2/TXT â ÑÐ´ÐµÐ»Ð°Ñ ÑÑÑÑÐºÑÑÑÐ¸ÑÐ¾Ð²Ð°Ð½Ð½ÑÐ¹ ÐºÐ¾Ð½ÑÐ¿ÐµÐºÑ.\n"
            "ÐÐ¾Ð¶Ð½Ð¾ Ð² Ð¿Ð¾Ð´Ð¿Ð¸ÑÐ¸ ÑÐºÐ°Ð·Ð°ÑÑ ÑÐµÐ»Ñ (ÐºÐ¾ÑÐ¾ÑÐºÐ¾/Ð¿Ð¾Ð´ÑÐ¾Ð+/-Ð½Ð¾, ÑÐ·ÑÐº Ð¸ Ñ.Ð¿.).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:explain":
        await q.answer()
        study_sub_set(uid, "explain")
        _mode_track_set(uid, "explain")
        await q.edit_message_text(
            "ð ÐÐ°Ð¿Ð¸ÑÐ¸ÑÐµ ÑÐµÐ¼Ñ + ÑÑÐ¾Ð²ÐµÐ½Ñ (ÑÐºÐ¾Ð»Ð°/Ð²ÑÐ·/Ð¿ÑÐ¾ÑÐ¸). ÐÑÐ´ÐµÑ Ð¾Ð+/-ÑÑÑÐ½ÐµÐ½Ð¸Ðµ Ñ Ð¿ÑÐ¸Ð¼ÐµÑÐ°Ð¼Ð¸.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:tasks":
        await q.answer()
        study_sub_set(uid, "tasks")
        _mode_track_set(uid, "tasks")
        await q.edit_message_text(
            "ð§® ÐÑÐ¸ÑÐ»Ð¸ÑÐµ ÑÑÐ»Ð¾Ð²Ð¸Ðµ(Ñ) â ÑÐµÑÑ Ð¿Ð¾ÑÐ°Ð³Ð¾Ð²Ð¾ (ÑÐ¾ÑÐ¼ÑÐ»Ñ, Ð¿Ð¾ÑÑÐ½ÐµÐ½Ð¸Ñ, Ð¸ÑÐ¾Ð³).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:essay":
        await q.answer()
        study_sub_set(uid, "essay")
        _mode_track_set(uid, "essay")
        await q.edit_message_text(
            "âï¸ Ð¢ÐµÐ¼Ð° + ÑÑÐµÐ+/-Ð¾Ð²Ð°Ð½Ð¸Ñ (Ð¾Ð+/-ÑÑÐ¼/ÑÑÐ¸Ð»Ñ/ÑÐ·ÑÐº) â Ð¿Ð¾Ð´Ð³Ð¾ÑÐ¾Ð²Ð»Ñ ÑÑÑÐµ/ÑÐµÑÐµÑÐ°Ñ.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:exam_plan":
        await q.answer()
        study_sub_set(uid, "quiz")
        _mode_track_set(uid, "exam_plan")
        await q.edit_message_text(
            "ð Ð£ÐºÐ°Ð¶Ð¸ÑÐµ Ð¿ÑÐµÐ´Ð¼ÐµÑ Ð¸ Ð´Ð°ÑÑ ÑÐºÐ·Ð°Ð¼ÐµÐ½Ð° â ÑÐ¾ÑÑÐ°Ð²Ð»Ñ Ð¿Ð»Ð°Ð½ Ð¿Ð¾Ð´Ð³Ð¾ÑÐ¾Ð²ÐºÐ¸ Ñ Ð²ÐµÑÐ°Ð¼Ð¸.",
            reply_markup=_mode_kb("study"),
        )
        return

    # === Ð Ð°Ð+/-Ð¾ÑÐ°
    if data == "act:work:doc":
        await q.answer()
        _mode_track_set(uid, "work_doc")
        await q.edit_message_text(
            "ð Ð§ÑÐ¾ Ð·Ð° Ð´Ð¾ÐºÑÐ¼ÐµÐ½Ñ/Ð°Ð´ÑÐµÑÐ°Ñ/ÐºÐ¾Ð½ÑÐµÐºÑÑ? Ð¡ÑÐ¾ÑÐ¼Ð¸ÑÑÑ ÑÐµÑÐ½Ð¾Ð²Ð¸Ðº Ð¿Ð¸ÑÑÐ¼Ð°/Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÐ°.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:report":
        await q.answer()
        _mode_track_set(uid, "work_report")
        await q.edit_message_text(
            "ð ÐÑÐ¸ÑÐ»Ð¸ÑÐµ ÑÐµÐºÑÑ/ÑÐ°Ð¹Ð»/ÑÑÑÐ»ÐºÑ â ÑÐ´ÐµÐ»Ð°Ñ Ð°Ð½Ð°Ð»Ð¸ÑÐ¸ÑÐµÑÐºÑÑ Ð²ÑÐ¶Ð¸Ð¼ÐºÑ.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:plan":
        await q.answer()
        _mode_track_set(uid, "work_plan")
        await q.edit_message_text(
            "ð ÐÐ¿Ð¸ÑÐ¸ÑÐµ Ð·Ð°Ð´Ð°ÑÑ/ÑÑÐ¾ÐºÐ¸ â ÑÐ¾Ð+/-ÐµÑÑ ToDo/Ð¿Ð»Ð°Ð½ ÑÐ¾ ÑÑÐ¾ÐºÐ°Ð¼Ð¸ Ð¸ Ð¿ÑÐ¸Ð¾ÑÐ¸ÑÐµÑÐ°Ð¼Ð¸.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:idea":
        await q.answer()
        _mode_track_set(uid, "work_idea")
        await q.edit_message_text(
            "ð¡ Ð Ð°ÑÑÐºÐ°Ð¶Ð¸ÑÐµ Ð¿ÑÐ¾Ð´ÑÐºÑ/Ð¦Ð/ÐºÐ°Ð½Ð°Ð»Ñ â Ð¿Ð¾Ð´Ð³Ð¾ÑÐ¾Ð²Ð»Ñ Ð+/-ÑÐ¸Ñ/Ð¸Ð´ÐµÐ¸.",
            reply_markup=_mode_kb("work"),
        )
        return

    # === Ð Ð°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ñ (ÐºÐ°Ðº Ð+/-ÑÐ»Ð¾)
    if data == "act:fun:ideas":
        await q.answer()
        await q.edit_message_text(
            "ð¥ ÐÑÐ+/-ÐµÑÐµÐ¼ ÑÐ¾ÑÐ¼Ð°Ñ: Ð´Ð¾Ð¼/ÑÐ»Ð¸ÑÐ°/Ð³Ð¾ÑÐ¾Ð´/Ð² Ð¿Ð¾ÐµÐ·Ð´ÐºÐµ. ÐÐ°Ð¿Ð¸ÑÐ¸ÑÐµ Ð+/-ÑÐ´Ð¶ÐµÑ/Ð½Ð°ÑÑÑÐ¾ÐµÐ½Ð¸Ðµ.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:shorts":
        await q.answer()
        await q.edit_message_text(
            "ð¬ Ð¢ÐµÐ¼Ð°, Ð´Ð»Ð¸ÑÐµÐ»ÑÐ½Ð¾ÑÑÑ (15â30 ÑÐµÐº), ÑÑÐ¸Ð»Ñ â ÑÐ´ÐµÐ»Ð°Ñ ÑÑÐµÐ½Ð°ÑÐ¸Ð¹ ÑÐ¾ÑÑÐ° + Ð¿Ð¾Ð´ÑÐºÐ°Ð·ÐºÐ¸ Ð´Ð»Ñ Ð¾Ð·Ð²ÑÑÐºÐ¸.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:games":
        await q.answer()
        await q.edit_message_text(
            "ð® Ð¢ÐµÐ¼Ð°ÑÐ¸ÐºÐ° ÐºÐ²Ð¸Ð·Ð°/Ð¸Ð³ÑÑ? Ð¡Ð³ÐµÐ½ÐµÑÐ¸ÑÑÑ Ð+/-ÑÑÑÑÑÑ Ð²Ð¸ÐºÑÐ¾ÑÐ¸Ð½Ñ Ð¸Ð»Ð¸ Ð¼Ð¸Ð½Ð¸-Ð¸Ð³ÑÑ Ð² ÑÐ°ÑÐµ.",
            reply_markup=_mode_kb("fun"),
        )
        return

    # === ÐÐ¾Ð´ÑÐ»Ð¸ (ÐºÐ°Ðº Ð+/-ÑÐ»Ð¾)
    if data == "act:open:runway":
        await q.answer()
        await q.edit_message_text(
            "ð¬ ÐÐ¾Ð´ÑÐ»Ñ Runway: Ð¿ÑÐ¸ÑÐ»Ð¸ÑÐµ Ð¸Ð´ÐµÑ/ÑÐµÑÐµÑÐµÐ½Ñ â Ð¿Ð¾Ð´Ð³Ð¾ÑÐ¾Ð²Ð»Ñ Ð¿ÑÐ¾Ð¼Ð¿Ñ Ð¸ Ð+/-ÑÐ´Ð¶ÐµÑ.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:mj":
        await q.answer()
        await q.edit_message_text(
            "ð¨ ÐÐ¾Ð´ÑÐ»Ñ Midjourney: Ð¾Ð¿Ð¸ÑÐ¸ÑÐµ ÐºÐ°ÑÑÐ¸Ð½ÐºÑ â Ð¿ÑÐµÐ´Ð»Ð¾Ð¶Ñ 3 Ð¿ÑÐ¾Ð¼Ð¿ÑÐ° Ð¸ ÑÐµÑÐºÑ ÑÑÐ¸Ð»ÐµÐ¹.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:voice":
        await q.answer()
        await q.edit_message_text(
            "ð£ ÐÐ¾Ð»Ð¾Ñ: /voice_on â Ð¾Ð·Ð²ÑÑÐºÐ° Ð¾ÑÐ²ÐµÑÐ¾Ð², /voice_off â Ð²ÑÐºÐ»ÑÑÐ¸ÑÑ. "
            "ÐÐ¾Ð¶ÐµÑÐµ Ð¿ÑÐ¸ÑÐ»Ð°ÑÑ Ð³Ð¾Ð»Ð¾ÑÐ¾Ð²Ð¾Ðµ â ÑÐ°ÑÐ¿Ð¾Ð·Ð½Ð°Ñ Ð¸ Ð¾ÑÐ²ÐµÑÑ.",
            reply_markup=modes_root_kb(),
        )
        return

    await q.answer()

# Fallback â ÐµÑÐ»Ð¸ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ Ð½Ð°Ð¶Ð¼ÑÑ Â«Ð£ÑÑÐ+/-Ð°/Ð Ð°Ð+/-Ð¾ÑÐ°/Ð Ð°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸ÑÂ» Ð¾Ð+/-ÑÑÐ½Ð¾Ð¹ ÐºÐ½Ð¾Ð¿ÐºÐ¾Ð¹/ÑÐµÐºÑÑÐ¾Ð¼
async def on_mode_text(update, context):
    text = (update.effective_message.text or "").strip().lower()
    mapping = {
        "ÑÑÑÐ+/-Ð°": "study", "ÑÑÐµÐ+/-Ð°": "study",
        "ÑÐ°Ð+/-Ð¾ÑÐ°": "work",
        "ÑÐ°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ñ": "fun", "ÑÐ°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ðµ": "fun",
    }
    key = mapping.get(text)
    if key:
        await _send_mode_menu(update, context, key)
        
def main_keyboard(user_id: int | None = None) -> ReplyKeyboardMarkup:
    """
    ÐÐ»Ð°Ð²Ð½Ð°Ñ ReplyKeyboard, Ð»Ð¾ÐºÐ°Ð»Ð¸Ð·Ð¾Ð²Ð°Ð½Ð½Ð°Ñ Ð¿Ð¾Ð´ ÑÐ·ÑÐº Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ.
    ÐÑÐ»Ð¸ user_id Ð½Ðµ Ð·Ð°Ð´Ð°Ð½ â Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÐ¼ RU.
    """
    uid = int(user_id) if user_id is not None else 0
    # ÐÐ½Ð¾Ð¿ÐºÐ¸ ÑÐµÐ¶Ð¸Ð¼Ð¾Ð² (ÑÐ¼Ð¾Ð´Ð·Ð¸ Ð¾ÑÑÐ°Ð²Ð»ÑÐµÐ¼ Ð´Ð»Ñ ÑÐ·Ð½Ð°Ð²Ð°ÐµÐ¼Ð¾ÑÑÐ¸)
    # ÐÐ¾ÐºÐ°Ð»Ð¸Ð·Ð°ÑÐ¸Ñ â ÑÐµÑÐµÐ· I18N (Ð¼Ð¸Ð½Ð¸Ð¼Ð°Ð»ÑÐ½ÑÐ¹ Ð½Ð°Ð+/-Ð¾Ñ ÑÑÑÐ¾Ðº).
    try:
        study = t(uid, "btn_study")
        work  = t(uid, "btn_work")
        fun   = t(uid, "btn_fun")
    except Exception:
        study, work, fun = "ð Ð£ÑÑÐ+/-Ð°", "ð¼ Ð Ð°Ð+/-Ð¾ÑÐ°", "ð¥ Ð Ð°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ñ"

    try:
        engines = t(uid, "btn_engines")
        subhelp = t(uid, "btn_sub")
        wallet  = t(uid, "btn_wallet")
    except Exception:
        engines, subhelp, wallet = "ð§  ÐÐ²Ð¸Ð¶ÐºÐ¸", "â ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° Â· ÐÐ¾Ð¼Ð¾ÑÑ", "ð§¾ ÐÐ°Ð»Ð°Ð½Ñ"

    placeholder = t(uid, "input_placeholder") if "input_placeholder" in (I18N.get(get_lang(uid), {}) or {}) else "ÐÑÐ+/-ÐµÑÐ¸ÑÐµ ÑÐµÐ¶Ð¸Ð¼ Ð¸Ð»Ð¸ Ð½Ð°Ð¿Ð¸ÑÐ¸ÑÐµ Ð·Ð°Ð¿ÑÐ¾Ñâ¦"

    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(study), KeyboardButton(work), KeyboardButton(fun)],
            [KeyboardButton(engines), KeyboardButton(subhelp), KeyboardButton(wallet)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
        input_field_placeholder=placeholder,
    )

# RU-ÐºÐ»Ð°Ð²Ð¸Ð°ÑÑÑÐ° Ð¿Ð¾ ÑÐ¼Ð¾Ð»ÑÐ°Ð½Ð¸Ñ (Ð½Ð° ÑÐ»ÑÑÐ°Ð¹ ÑÐµÐ´ÐºÐ¸Ñ Ð¼ÐµÑÑ Ð+/-ÐµÐ· user_id)
main_kb = main_keyboard(0)

# âââââââââ /start âââââââââ
async def _send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ÐÑÑÐ¸ÑÐ¾Ð²ÐºÐ° Ð³Ð»Ð°Ð²Ð½Ð¾Ð³Ð¾ Ð¼ÐµÐ½Ñ (Ð¿Ð¾ÑÐ»Ðµ Ð²ÑÐ+/-Ð¾ÑÐ° ÑÐ·ÑÐºÐ° Ð¸ Ð² Ð´ÑÑÐ³Ð¸Ñ Ð¼ÐµÑÑÐ°Ñ).
    """
    uid = update.effective_user.id
    # ÐÐ°Ð½Ð½ÐµÑ (ÐµÑÐ»Ð¸ Ð·Ð°Ð´Ð°Ð½)
    welcome_url = kv_get("welcome_url", BANNER_URL)
    if welcome_url:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_photo(welcome_url)

    # ÐÐ¾ÑÐ¾ÑÐºÐ¾Ðµ Ð¿ÑÐ¸Ð²ÐµÑÑÑÐ²Ð¸Ðµ Ð½Ð° Ð²ÑÐ+/-ÑÐ°Ð½Ð½Ð¾Ð¼ ÑÐ·ÑÐºÐµ
    text = _tr(uid, "welcome")
    with contextlib.suppress(Exception):
        await update.effective_message.reply_text(
            text,
            reply_markup=main_keyboard(uid),
            disable_web_page_preview=True,
        )

# âââââââââ /start âââââââââ
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ð¢ÑÐµÐ+/-Ð¾Ð²Ð°Ð½Ð¸Ðµ: Ð²ÑÐ+/-Ð¾Ñ ÑÐ·ÑÐºÐ° Ð¿Ð¾ÐºÐ°Ð·ÑÐ²Ð°ÐµÐ¼ Ð¿ÑÐ¸ ÐºÐ°Ð¶Ð´Ð¾Ð¼ Ð½Ð¾Ð²Ð¾Ð¼ /start (Ð½Ðµ ÑÐ¾Ð»ÑÐºÐ¾ Ð¿ÐµÑÐ²ÑÐ¹ ÑÐ°Ð·).
    ÐÐµÐ½Ñ Ð¿Ð¾ÐºÐ°Ð·ÑÐ²Ð°ÐµÐ¼ Ð¿Ð¾ÑÐ»Ðµ Ð½Ð°Ð¶Ð°ÑÐ¸Ñ ÐºÐ½Ð¾Ð¿ÐºÐ¸ ÑÐ·ÑÐºÐ° (Ð¸Ð»Ð¸ Â«ÐÑÐ¾Ð´Ð¾Ð»Ð¶Ð¸ÑÑÂ»).
    """
    uid = update.effective_user.id

    # ÐÐ¾ÐºÐ°Ð·ÑÐ²Ð°ÐµÐ¼ Ð+/-Ð°Ð½Ð½ÐµÑ (ÐµÑÐ»Ð¸ Ð·Ð°Ð´Ð°Ð½)
    welcome_url = kv_get("welcome_url", BANNER_URL)
    if welcome_url:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_photo(welcome_url)

    # ÐÐ¾ÐºÐ°Ð·ÑÐ²Ð°ÐµÐ¼ Ð²ÑÐ+/-Ð¾Ñ ÑÐ·ÑÐºÐ° Ð²ÑÐµÐ³Ð´Ð°
    await update.effective_message.reply_text(
        t(uid, "choose_lang"),
        reply_markup=_lang_choose_kb(uid),
    )
# âââââââââ Ð¡ÑÐ°ÑÑ / ÐÐ²Ð¸Ð¶ÐºÐ¸ / ÐÐ¾Ð¼Ð¾ÑÑ âââââââââ

async def cmd_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.effective_message.reply_text(_tr(uid, "choose_engine"), reply_markup=engines_kb())

async def cmd_subs_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("ÐÑÐºÑÑÑÑ ÑÐ°ÑÐ¸ÑÑ (WebApp)", web_app=WebAppInfo(url=TARIFF_URL))],
        [InlineKeyboardButton("ÐÑÐ¾ÑÐ¼Ð¸ÑÑ PRO Ð½Ð° Ð¼ÐµÑÑÑ (Ð®Kassa)", callback_data="buyinv:pro:1")],
    ])
    await update.effective_message.reply_text("â Ð¢Ð°ÑÐ¸ÑÑ Ð¸ Ð¿Ð¾Ð¼Ð¾ÑÑ.\n\n" + HELP_TEXT, reply_markup=kb, disable_web_page_preview=True)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, disable_web_page_preview=True)

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(EXAMPLES_TEXT, disable_web_page_preview=True)


# âââââââââ ÐÐ¸Ð°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ°/Ð»Ð¸Ð¼Ð¸ÑÑ âââââââââ
async def cmd_diag_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tier = get_subscription_tier(user_id)
    lim = _limits_for(user_id)
    row = _usage_row(user_id, _today_ymd())
    lines = [
        f"ð¤ Ð¢Ð°ÑÐ¸Ñ: {tier}",
        f"â¢ Ð¢ÐµÐºÑÑÑ ÑÐµÐ³Ð¾Ð´Ð½Ñ: {row['text_count']} / {lim['text_per_day']}",
        f"â¢ Luma $: {row['luma_usd']:.2f} / {lim['luma_budget_usd']:.2f}",
        f"â¢ Runway $: {row['runway_usd']:.2f} / {lim['runway_budget_usd']:.2f}",
        f"â¢ Images $: {row['img_usd']:.2f} / {lim['img_budget_usd']:.2f}",
    ]
    await update.effective_message.reply_text("\n".join(lines))


# âââââââââ Capability Q&A âââââââââ
_CAP_PDF   = re.compile(r"(pdf|Ð´Ð¾ÐºÑÐ¼ÐµÐ½Ñ(Ñ)?|ÑÐ°Ð¹Ð»(Ñ)?)", re.I)
_CAP_EBOOK = re.compile(r"(ebook|e-?book|ÑÐ»ÐµÐºÑÑÐ¾Ð½Ð½(Ð°Ñ|ÑÐµ)\s+ÐºÐ½Ð¸Ð³|epub|fb2|docx|txt|mobi|azw)", re.I)
_CAP_AUDIO = re.compile(r"(Ð°ÑÐ´Ð¸Ð¾ ?ÐºÐ½Ð¸Ð³|audiobook|audio ?book|mp3|m4a|wav|ogg|webm|voice)", re.I)
_CAP_IMAGE = re.compile(r"(Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½|ÐºÐ°ÑÑÐ¸Ð½Ðº|ÑÐ¾ÑÐ¾|image|picture|img)", re.I)
_CAP_VIDEO = re.compile(r"(Ð²Ð¸Ð´ÐµÐ¾|ÑÐ¾Ð»Ð¸Ðº|shorts?|reels?|clip)", re.I)

def capability_answer(text: str) -> str | None:
    """
    ÐÐ¾ÑÐ¾ÑÐºÐ¸Ðµ Ð¾ÑÐ²ÐµÑÑ Ð½Ð° Ð²Ð¾Ð¿ÑÐ¾ÑÑ Ð²Ð¸Ð´Ð°:
    - Â«ÑÑ Ð¼Ð¾Ð¶ÐµÑÑ Ð°Ð½Ð°Ð»Ð¸Ð·Ð¸ÑÐ¾Ð²Ð°ÑÑ PDF?Â»
    - Â«ÑÑ ÑÐ¼ÐµÐµÑÑ ÑÐ°Ð+/-Ð¾ÑÐ°ÑÑ Ñ ÑÐ»ÐµÐºÑÑÐ¾Ð½Ð½ÑÐ¼Ð¸ ÐºÐ½Ð¸Ð³Ð°Ð¼Ð¸?Â»
    - Â«ÑÑ Ð¼Ð¾Ð¶ÐµÑÑ ÑÐ¾Ð·Ð´Ð°Ð²Ð°ÑÑ Ð²Ð¸Ð´ÐµÐ¾?Â»
    - Â«ÑÑ Ð¼Ð¾Ð¶ÐµÑÑ Ð¾Ð¶Ð¸Ð²Ð¸ÑÑ ÑÐ¾ÑÐ¾Ð³ÑÐ°ÑÐ¸Ñ?Â» Ð¸ Ñ.Ð¿.

    ÐÐ°Ð¶Ð½Ð¾: Ð½Ðµ Ð¿ÐµÑÐµÑÐ²Ð°ÑÑÐ²Ð°ÐµÐ¼ ÑÐµÐ°Ð»ÑÐ½ÑÐµ ÐºÐ¾Ð¼Ð°Ð½Ð´Ñ
    Â«ÑÐ´ÐµÐ»Ð°Ð¹ Ð²Ð¸Ð´ÐµÐ¾â¦Â», Â«ÑÐ³ÐµÐ½ÐµÑÐ¸ÑÑÐ¹ ÐºÐ°ÑÑÐ¸Ð½ÐºÑâ¦Â» Ð¸ Ñ.Ð´.
    """

    tl = (text or "").strip().lower()
    if not tl:
        return None

    # --- ÐÐ¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ðµ ÑÑÐ°ÑÑÑ ÑÐ¾ÑÐ¾ / Ð°Ð½Ð¸Ð¼Ð°ÑÐ¸Ñ ÑÐ½Ð¸Ð¼ÐºÐ¾Ð² (ÐÐ«Ð¡ÐÐÐÐ ÐÐ ÐÐÐ ÐÐ¢ÐÐ¢) ---
    if (
        any(k in tl for k in ("Ð¾Ð¶Ð¸Ð²Ð¸", "Ð¾Ð¶Ð¸Ð²Ð¸ÑÑ", "Ð°Ð½Ð¸Ð¼Ð¸ÑÑÐ¹", "Ð°Ð½Ð¸Ð¼Ð¸ÑÐ¾Ð²Ð°ÑÑ"))
        and any(k in tl for k in ("ÑÐ¾ÑÐ¾", "ÑÐ¾ÑÐ¾Ð³ÑÐ°Ñ", "ÐºÐ°ÑÑÐ¸Ð½", "Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½", "Ð¿Ð¾ÑÑÑÐµÑ"))
    ):
        # ÐÐµÑÑÐ¾Ð½Ð°Ð»Ð¸Ð·Ð¸ÑÐ¾Ð²Ð°Ð½Ð½ÑÐ¹ Ð¾ÑÐ²ÐµÑ Ð¸Ð¼ÐµÐ½Ð½Ð¾ Ð¿Ð¾Ð´ ÑÑÐ½ÐºÑÐ¸Ñ Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ñ
        return (
            "ðª Ð¯ ÑÐ¼ÐµÑ Ð¾Ð¶Ð¸Ð²Ð»ÑÑÑ ÑÐ¾ÑÐ¾Ð³ÑÐ°ÑÐ¸Ð¸ Ð¸ Ð´ÐµÐ»Ð°ÑÑ Ð¸Ð· Ð½Ð¸Ñ ÐºÐ¾ÑÐ¾ÑÐºÐ¸Ðµ Ð°Ð½Ð¸Ð¼Ð°ÑÐ¸Ð¸.\n\n"
            "Ð§ÑÐ¾ Ð¼Ð¾Ð¶Ð½Ð¾ Ð¾Ð¶Ð¸Ð²Ð¸ÑÑ:\n"
            "â¢ Ð»ÑÐ³ÐºÐ°Ñ Ð¼Ð¸Ð¼Ð¸ÐºÐ°: Ð¼Ð¾ÑÐ³Ð°Ð½Ð¸Ðµ Ð³Ð»Ð°Ð·, Ð¼ÑÐ³ÐºÐ°Ñ ÑÐ»ÑÐ+/-ÐºÐ°;\n"
            "â¢ Ð¿Ð»Ð°Ð²Ð½ÑÐµ Ð´Ð²Ð¸Ð¶ÐµÐ½Ð¸Ñ Ð³Ð¾Ð»Ð¾Ð²Ñ Ð¸ Ð¿Ð»ÐµÑ, ÑÑÑÐµÐºÑ Ð´ÑÑÐ°Ð½Ð¸Ñ;\n"
            "â¢ Ð»ÑÐ³ÐºÐ¾Ðµ Ð´Ð²Ð¸Ð¶ÐµÐ½Ð¸Ðµ Ð¸Ð»Ð¸ Ð¿Ð°ÑÐ°Ð»Ð»Ð°ÐºÑ ÑÐ¾Ð½Ð°.\n\n"
            "ÐÐ¾ÑÑÑÐ¿Ð½ÑÐµ Ð´Ð²Ð¸Ð¶ÐºÐ¸:\n"
            "â¢ Runway â Ð¼Ð°ÐºÑÐ¸Ð¼Ð°Ð»ÑÐ½Ð¾ ÑÐµÐ°Ð»Ð¸ÑÑÐ¸ÑÐ½Ð¾Ðµ Ð¿ÑÐµÐ¼Ð¸ÑÐ¼-Ð´Ð²Ð¸Ð¶ÐµÐ½Ð¸Ðµ;\n"
            "â¢ Kling â Ð¾ÑÐ»Ð¸ÑÐ½Ð¾ Ð¿ÐµÑÐµÐ´Ð°ÑÑ Ð²Ð·Ð³Ð»ÑÐ´, Ð¼Ð¸Ð¼Ð¸ÐºÑ Ð¸ Ð¿Ð¾Ð²Ð¾ÑÐ¾ÑÑ Ð³Ð¾Ð»Ð¾Ð²Ñ;\n"
            "â¢ Luma â Ð¿Ð»Ð°Ð²Ð½ÑÐµ ÑÑÐ´Ð¾Ð¶ÐµÑÑÐ²ÐµÐ½Ð½ÑÐµ Ð°Ð½Ð¸Ð¼Ð°ÑÐ¸Ð¸.\n\n"
            "ÐÑÐ¸ÑÐ»Ð¸ ÑÑÐ´Ð° ÑÐ¾ÑÐ¾ (Ð»ÑÑÑÐµ Ð¿Ð¾ÑÑÑÐµÑ). ÐÐ¾ÑÐ»Ðµ Ð·Ð°Ð³ÑÑÐ·ÐºÐ¸ Ñ Ð¿ÑÐµÐ´Ð»Ð¾Ð¶Ñ Ð²ÑÐ+/-ÑÐ°ÑÑ Ð´Ð²Ð¸Ð¶Ð¾Ðº "
            "Ð¸ Ð¿Ð¾Ð´Ð³Ð¾ÑÐ¾Ð²Ð»Ñ Ð¿ÑÐµÐ²ÑÑ/Ð²Ð¸Ð´ÐµÐ¾."
        )

    # --- ÐÐ¾ÐºÑÐ¼ÐµÐ½ÑÑ / ÑÐ°Ð¹Ð»Ñ ---
    if re.search(r"\b(pdf|docx|epub|fb2|txt|mobi|azw)\b", tl) and "?" in tl:
        return (
            "ÐÐ°, Ð¼Ð¾Ð³Ñ Ð¿Ð¾Ð¼Ð¾ÑÑ Ñ Ð°Ð½Ð°Ð»Ð¸Ð·Ð¾Ð¼ Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÐ¾Ð² Ð¸ ÑÐ»ÐµÐºÑÑÐ¾Ð½Ð½ÑÑ ÐºÐ½Ð¸Ð³. "
            "ÐÑÐ¿ÑÐ°Ð²Ñ ÑÐ°Ð¹Ð» (PDF, EPUB, DOCX, FB2, TXT, MOBI/AZW â Ð¿Ð¾ Ð²Ð¾Ð·Ð¼Ð¾Ð¶Ð½Ð¾ÑÑÐ¸) "
            "Ð¸ Ð½Ð°Ð¿Ð¸ÑÐ¸, ÑÑÐ¾ Ð½ÑÐ¶Ð½Ð¾: ÐºÐ¾Ð½ÑÐ¿ÐµÐºÑ, Ð²ÑÐ¶Ð¸Ð¼ÐºÑ, Ð¿Ð»Ð°Ð½, ÑÐ°Ð·Ð+/-Ð¾Ñ Ð¿Ð¾ Ð¿ÑÐ½ÐºÑÐ°Ð¼ Ð¸ Ñ.Ð¿."
        )

    # --- ÐÑÐ´Ð¸Ð¾ / ÑÐµÑÑ ---
    if ("Ð°ÑÐ´Ð¸Ð¾" in tl or "Ð³Ð¾Ð»Ð¾ÑÐ¾Ð²" in tl or "voice" in tl or "speech" in tl) and (
        "?" in tl or "Ð¼Ð¾Ð¶ÐµÑÑ" in tl or "ÑÐ¼ÐµÐµÑÑ" in tl
    ):
        return (
            "ÐÐ°, Ð¼Ð¾Ð³Ñ ÑÐ°ÑÐ¿Ð¾Ð·Ð½Ð°Ð²Ð°ÑÑ ÑÐµÑÑ Ð¸Ð· Ð³Ð¾Ð»Ð¾ÑÐ¾Ð²ÑÑ Ð¸ Ð°ÑÐ´Ð¸Ð¾. "
            "ÐÑÐ¾ÑÑÐ¾ Ð¿ÑÐ¸ÑÐ»Ð¸ Ð³Ð¾Ð»Ð¾ÑÐ¾Ð²Ð¾Ðµ ÑÐ¾Ð¾Ð+/-ÑÐµÐ½Ð¸Ðµ â Ñ Ð¿ÐµÑÐµÐ²ÐµÐ´Ñ ÐµÐ³Ð¾ Ð² ÑÐµÐºÑÑ Ð¸ Ð¾ÑÐ²ÐµÑÑ ÐºÐ°Ðº Ð½Ð° Ð¾Ð+/-ÑÑÐ½ÑÐ¹ Ð·Ð°Ð¿ÑÐ¾Ñ."
        )

    # --- ÐÐ¸Ð´ÐµÐ¾ (Ð¾Ð+/-ÑÐ¸Ðµ Ð²Ð¾Ð·Ð¼Ð¾Ð¶Ð½Ð¾ÑÑÐ¸, Ð½Ðµ ÐºÐ¾Ð¼Ð°Ð½Ð´Ñ) ---
    if (
        re.search(r"\bÐ²Ð¸Ð´ÐµÐ¾\b", tl)
        and "?" in tl
        and re.search(r"\b(Ð¼Ð¾Ð¶(ÐµÑÑ|ÐµÑÐµ)|ÑÐ¼Ðµ(ÐµÑÑ|ÐµÑÐµ)|ÑÐ¿Ð¾ÑÐ¾Ð+/-ÐµÐ½)\b", tl)
    ):
        return (
            "ÐÐ°, Ð¼Ð¾Ð³Ñ Ð·Ð°Ð¿ÑÑÐºÐ°ÑÑ Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ñ ÐºÐ¾ÑÐ¾ÑÐºÐ¸Ñ Ð²Ð¸Ð´ÐµÐ¾. "
            "ÐÐ¾Ð¶Ð½Ð¾ ÑÐ´ÐµÐ»Ð°ÑÑ ÑÐ¾Ð»Ð¸Ðº Ð¿Ð¾ ÑÐµÐºÑÑÐ¾Ð²Ð¾Ð¼Ñ Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ñ Ð¸Ð»Ð¸ Ð¾Ð¶Ð¸Ð²Ð¸ÑÑ ÑÐ¾ÑÐ¾. "
            "ÐÐ¾ÑÐ»Ðµ ÑÐ¾Ð³Ð¾ ÐºÐ°Ðº ÑÑ Ð¿ÑÐ¸ÑÐ»ÑÑÑ Ð·Ð°Ð¿ÑÐ¾Ñ Ð¸/Ð¸Ð»Ð¸ ÑÐ°Ð¹Ð», Ñ Ð¿ÑÐµÐ´Ð»Ð¾Ð¶Ñ Ð²ÑÐ+/-ÑÐ°ÑÑ Ð´Ð²Ð¸Ð¶Ð¾Ðº "
            "(Runway, Kling, Luma â Ð² Ð·Ð°Ð²Ð¸ÑÐ¸Ð¼Ð¾ÑÑÐ¸ Ð¾Ñ Ð´Ð¾ÑÑÑÐ¿Ð½ÑÑ)."
        )

    # --- ÐÐ°ÑÑÐ¸Ð½ÐºÐ¸ / Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ñ (Ð+/-ÐµÐ· /img Ð¸ Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ð¸ Ð¿Ð¾ Ð¿ÑÐ¾Ð¼Ð¿ÑÑ) ---
    if (
        re.search(r"(ÐºÐ°ÑÑÐ¸Ð½Ðº|Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½|ÑÐ¾ÑÐ¾|picture|Ð»Ð¾Ð³Ð¾ÑÐ¸Ð¿|Ð+/-Ð°Ð½Ð½ÐµÑ)", tl)
        and "?" in tl
    ):
        return (
            "ÐÐ°, Ð¼Ð¾Ð³Ñ ÑÐ°Ð+/-Ð¾ÑÐ°ÑÑ Ñ Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸ÑÐ¼Ð¸: Ð°Ð½Ð°Ð»Ð¸Ð·, ÑÐ»ÑÑÑÐµÐ½Ð¸Ðµ ÐºÐ°ÑÐµÑÑÐ²Ð°, ÑÐ´Ð°Ð»ÐµÐ½Ð¸Ðµ Ð¸Ð»Ð¸ Ð·Ð°Ð¼ÐµÐ½Ð° ÑÐ¾Ð½Ð°, "
            "ÑÐ°ÑÑÐ¸ÑÐµÐ½Ð¸Ðµ ÐºÐ°Ð´ÑÐ°, Ð¿ÑÐ¾ÑÑÐ°Ñ Ð°Ð½Ð¸Ð¼Ð°ÑÐ¸Ñ. "
            "ÐÑÐ¾ÑÑÐ¾ Ð¿ÑÐ¸ÑÐ»Ð¸ ÑÑÐ´Ð° ÑÐ¾ÑÐ¾ Ð¸ ÐºÐ¾ÑÐ¾ÑÐºÐ¾ Ð¾Ð¿Ð¸ÑÐ¸, ÑÑÐ¾ Ð½ÑÐ¶Ð½Ð¾ ÑÐ´ÐµÐ»Ð°ÑÑ."
        )

    # ÐÐ¸ÑÐµÐ³Ð¾ Ð¿Ð¾Ð´ÑÐ¾Ð´ÑÑÐµÐ³Ð¾ â Ð¿ÑÑÑÑ Ð¾Ð+/-ÑÐ°Ð+/-Ð°ÑÑÐ²Ð°ÐµÑÑÑ Ð¾ÑÐ½Ð¾Ð²Ð½Ð¾Ð¹ Ð»Ð¾Ð³Ð¸ÐºÐ¾Ð¹
    return None

# âââââââââ ÐÐ¾Ð´Ñ/Ð´Ð²Ð¸Ð¶ÐºÐ¸ Ð´Ð»Ñ study âââââââââ
def _uk(user_id: int, name: str) -> str: return f"user:{user_id}:{name}"
def mode_set(user_id: int, mode: str):     kv_set(_uk(user_id, "mode"), (mode or "default"))
def mode_get(user_id: int) -> str:         return kv_get(_uk(user_id, "mode"), "default") or "default"
def engine_set(user_id: int, engine: str): kv_set(_uk(user_id, "engine"), (engine or "gpt"))
def engine_get(user_id: int) -> str:       return kv_get(_uk(user_id, "engine"), "gpt") or "gpt"
def study_sub_set(user_id: int, sub: str): kv_set(_uk(user_id, "study_sub"), (sub or "explain"))
def study_sub_get(user_id: int) -> str:    return kv_get(_uk(user_id, "study_sub"), "explain") or "explain"

def modes_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ð Ð£ÑÑÐ+/-Ð°", callback_data="mode:set:study"),
         InlineKeyboardButton("ð¼ Ð¤Ð¾ÑÐ¾",  callback_data="mode:set:photo")],
        [InlineKeyboardButton("ð ÐÐ¾ÐºÑÐ¼ÐµÐ½ÑÑ", callback_data="mode:set:docs"),
         InlineKeyboardButton("ð ÐÐ¾Ð»Ð¾Ñ",     callback_data="mode:set:voice")],
        [InlineKeyboardButton("ð§  ÐÐ²Ð¸Ð¶ÐºÐ¸", callback_data="mode:engines")]
    ])

def study_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ð ÐÐ+/-ÑÑÑÐ½ÐµÐ½Ð¸Ðµ",          callback_data="study:set:explain"),
         InlineKeyboardButton("ð§® ÐÐ°Ð´Ð°ÑÐ¸",              callback_data="study:set:tasks")],
        [InlineKeyboardButton("âï¸ ÐÑÑÐµ/ÑÐµÑÐµÑÐ°Ñ/Ð´Ð¾ÐºÐ»Ð°Ð´", callback_data="study:set:essay")],
        [InlineKeyboardButton("ð ÐÐºÐ·Ð°Ð¼ÐµÐ½/ÐºÐ²Ð¸Ð·",        callback_data="study:set:quiz")]
    ])

async def study_process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    sub = study_sub_get(update.effective_user.id)
    if sub == "explain":
        prompt = f"ÐÐ+/-ÑÑÑÐ½Ð¸ Ð¿ÑÐ¾ÑÑÑÐ¼Ð¸ ÑÐ»Ð¾Ð²Ð°Ð¼Ð¸, Ñ 2â3 Ð¿ÑÐ¸Ð¼ÐµÑÐ°Ð¼Ð¸ Ð¸ Ð¼Ð¸Ð½Ð¸-Ð¸ÑÐ¾Ð³Ð¾Ð¼:\n\n{text}"
    elif sub == "tasks":
        prompt = ("Ð ÐµÑÐ¸ Ð·Ð°Ð´Ð°ÑÑ(Ð¸) Ð¿Ð¾ÑÐ°Ð³Ð¾Ð²Ð¾: ÑÐ¾ÑÐ¼ÑÐ»Ñ, Ð¿Ð¾ÑÑÐ½ÐµÐ½Ð¸Ñ, Ð¸ÑÐ¾Ð³Ð¾Ð²ÑÐ¹ Ð¾ÑÐ²ÐµÑ. "
                  "ÐÑÐ»Ð¸ Ð½Ðµ ÑÐ²Ð°ÑÐ°ÐµÑ Ð´Ð°Ð½Ð½ÑÑ â ÑÑÐ¾ÑÐ½ÑÑÑÐ¸Ðµ Ð²Ð¾Ð¿ÑÐ¾ÑÑ Ð² ÐºÐ¾Ð½ÑÐµ.\n\n" + text)
    elif sub == "essay":
        prompt = ("ÐÐ°Ð¿Ð¸ÑÐ¸ ÑÑÑÑÐºÑÑÑÐ¸ÑÐ¾Ð²Ð°Ð½Ð½ÑÐ¹ ÑÐµÐºÑÑ 400â600 ÑÐ»Ð¾Ð² (ÑÑÑÐµ/ÑÐµÑÐµÑÐ°Ñ/Ð´Ð¾ÐºÐ»Ð°Ð´): "
                  "Ð²Ð²ÐµÐ´ÐµÐ½Ð¸Ðµ, 3â5 ÑÐµÐ·Ð¸ÑÐ¾Ð² Ñ ÑÐ°ÐºÑÐ°Ð¼Ð¸, Ð²ÑÐ²Ð¾Ð´, ÑÐ¿Ð¸ÑÐ¾Ðº Ð¸Ð· 3 Ð¸ÑÑÐ¾ÑÐ½Ð¸ÐºÐ¾Ð² (ÐµÑÐ»Ð¸ ÑÐ¼ÐµÑÑÐ½Ð¾).\n\nÐ¢ÐµÐ¼Ð°:\n" + text)
    elif sub == "quiz":
        prompt = ("Ð¡Ð¾ÑÑÐ°Ð²Ñ Ð¼Ð¸Ð½Ð¸-ÐºÐ²Ð¸Ð· Ð¿Ð¾ ÑÐµÐ¼Ðµ: 10 Ð²Ð¾Ð¿ÑÐ¾ÑÐ¾Ð², Ñ ÐºÐ°Ð¶Ð´Ð¾Ð³Ð¾ 4 Ð²Ð°ÑÐ¸Ð°Ð½ÑÐ° AâD; "
                  "Ð² ÐºÐ¾Ð½ÑÐµ Ð´Ð°Ð¹ ÐºÐ»ÑÑ Ð¾ÑÐ²ÐµÑÐ¾Ð² (Ð½Ð¾Ð¼ÐµÑâÐ+/-ÑÐºÐ²Ð°). Ð¢ÐµÐ¼Ð°:\n\n" + text)
    else:
        prompt = text
    ans = await ask_openai_text(prompt)
    await update.effective_message.reply_text(ans)
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])


# âââââââââ ÐÐ½Ð¾Ð¿ÐºÐ° Ð¿ÑÐ¸Ð²ÐµÑÑÑÐ²ÐµÐ½Ð½Ð¾Ð¹ ÐºÐ°ÑÑÐ¸Ð½ÐºÐ¸ âââââââââ
async def cmd_set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("ÐÐ¾Ð¼Ð°Ð½Ð´Ð° Ð´Ð¾ÑÑÑÐ¿Ð½Ð° ÑÐ¾Ð»ÑÐºÐ¾ Ð²Ð»Ð°Ð´ÐµÐ»ÑÑÑ.")
        return
    if not context.args:
        await update.effective_message.reply_text("Ð¤Ð¾ÑÐ¼Ð°Ñ: /set_welcome <url_ÐºÐ°ÑÑÐ¸Ð½ÐºÐ¸>")
        return
    url = " ".join(context.args).strip()
    kv_set("welcome_url", url)
    await update.effective_message.reply_text("ÐÐ°ÑÑÐ¸Ð½ÐºÐ° Ð¿ÑÐ¸Ð²ÐµÑÑÑÐ²Ð¸Ñ Ð¾Ð+/-Ð½Ð¾Ð²Ð»ÐµÐ½Ð°. ÐÑÐ¿ÑÐ°Ð²ÑÑÐµ /start Ð´Ð»Ñ Ð¿ÑÐ¾Ð²ÐµÑÐºÐ¸.")

async def cmd_show_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = kv_get("welcome_url", BANNER_URL)
    if url:
        await update.effective_message.reply_photo(url, caption="Ð¢ÐµÐºÑÑÐ°Ñ ÐºÐ°ÑÑÐ¸Ð½ÐºÐ° Ð¿ÑÐ¸Ð²ÐµÑÑÑÐ²Ð¸Ñ")
    else:
        await update.effective_message.reply_text("ÐÐ°ÑÑÐ¸Ð½ÐºÐ° Ð¿ÑÐ¸Ð²ÐµÑÑÑÐ²Ð¸Ñ Ð½Ðµ Ð·Ð°Ð´Ð°Ð½Ð°.")


# âââââââââ ÐÐ°Ð»Ð°Ð½Ñ / Ð¿Ð¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ðµ âââââââââ
async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    w = _wallet_get(user_id)
    total = _wallet_total_get(user_id)
    row = _usage_row(user_id)
    lim = _limits_for(user_id)
    msg = (
        "ð§¾ ÐÐ¾ÑÐµÐ»ÑÐº:\n"
        f"â¢ ÐÐ´Ð¸Ð½ÑÐ¹ Ð+/-Ð°Ð»Ð°Ð½Ñ: ${total:.2f}\n"
        "  (ÑÐ°ÑÑÐ¾Ð´ÑÐµÑÑÑ Ð½Ð° Ð¿ÐµÑÐµÑÐ°ÑÑÐ¾Ð´ Ð¿Ð¾ Luma/Runway/Images)\n\n"
        "ÐÐµÑÐ°Ð»Ð¸Ð·Ð°ÑÐ¸Ñ ÑÐµÐ³Ð¾Ð´Ð½Ñ / Ð»Ð¸Ð¼Ð¸ÑÑ ÑÐ°ÑÐ¸ÑÐ°:\n"
        f"â¢ Luma: ${row['luma_usd']:.2f} / ${lim['luma_budget_usd']:.2f}\n"
        f"â¢ Runway: ${row['runway_usd']:.2f} / ${lim['runway_budget_usd']:.2f}\n"
        f"â¢ Images: ${row['img_usd']:.2f} / ${lim['img_budget_usd']:.2f}\n"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("â ÐÐ¾Ð¿Ð¾Ð»Ð½Ð¸ÑÑ Ð+/-Ð°Ð»Ð°Ð½Ñ", callback_data="topup")]])
    await update.effective_message.reply_text(msg, reply_markup=kb)

# âââââââââ ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° / ÑÐ°ÑÐ¸ÑÑ â UI Ð¸ Ð¾Ð¿Ð»Ð°ÑÑ (PATCH) âââââââââ
# ÐÐ°Ð²Ð¸ÑÐ¸Ð¼Ð¾ÑÑÐ¸ Ð¾ÐºÑÑÐ¶ÐµÐ½Ð¸Ñ:
#  - YOOKASSA_PROVIDER_TOKEN  (Ð¿Ð»Ð°ÑÑÐ¶Ð½ÑÐ¹ ÑÐ¾ÐºÐµÐ½ Telegram Payments Ð¾Ñ Ð®Kassa)
#  - YOOKASSA_CURRENCY        (Ð¿Ð¾ ÑÐ¼Ð¾Ð»ÑÐ°Ð½Ð¸Ñ "RUB")
#  - CRYPTO_PAY_API_TOKEN     (https://pay.crypt.bot â ÑÐ¾ÐºÐµÐ½ Ð¿ÑÐ¾Ð´Ð°Ð²ÑÐ°)
#  - CRYPTO_ASSET             (Ð½Ð°Ð¿ÑÐ¸Ð¼ÐµÑ "USDT", Ð¿Ð¾ ÑÐ¼Ð¾Ð»ÑÐ°Ð½Ð¸Ñ "USDT")
#  - PRICE_START_RUB, PRICE_PRO_RUB, PRICE_ULT_RUB  (ÑÐµÐ»Ð¾Ðµ ÑÐ¸ÑÐ»Ð¾, â½)
#  - PRICE_START_USD, PRICE_PRO_USD, PRICE_ULT_USD  (ÑÐ¸ÑÐ»Ð¾ Ñ ÑÐ¾ÑÐºÐ¾Ð¹, $)
#
# Ð¥ÑÐ°Ð½Ð¸Ð»Ð¸ÑÐµ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ¸ Ð¸ ÐºÐ¾ÑÐµÐ»ÑÐºÐ° Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÑÑÑ Ð½Ð° kv_*:
#   sub:tier:{user_id}   -> "start" | "pro" | "ultimate"
#   sub:until:{user_id}  -> ISO-ÑÑÑÐ¾ÐºÐ° Ð´Ð°ÑÑ Ð¾ÐºÐ¾Ð½ÑÐ°Ð½Ð¸Ñ
#   wallet:usd:{user_id} -> Ð+/-Ð°Ð»Ð°Ð½Ñ Ð² USD (float)

YOOKASSA_PROVIDER_TOKEN = os.environ.get("YOOKASSA_PROVIDER_TOKEN", "").strip()
YOOKASSA_CURRENCY = (os.environ.get("YOOKASSA_CURRENCY") or "RUB").upper()

CRYPTO_PAY_API_TOKEN = os.environ.get("CRYPTO_PAY_API_TOKEN", "").strip()
CRYPTO_ASSET = (os.environ.get("CRYPTO_ASSET") or "USDT").upper()

# === COMPAT with existing vars/DB in your main.py ===
# 1) Ð®Kassa: ÐµÑÐ»Ð¸ ÑÐ¶Ðµ ÐµÑÑÑ PROVIDER_TOKEN (Ð¸Ð· PROVIDER_TOKEN_YOOKASSA), Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÐ¼ ÐµÐ³Ð¾:
if not YOOKASSA_PROVIDER_TOKEN and 'PROVIDER_TOKEN' in globals() and PROVIDER_TOKEN:
    YOOKASSA_PROVIDER_TOKEN = PROVIDER_TOKEN

# 2) ÐÐ¾ÑÐµÐ»ÑÐº: Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÐ¼ ÑÐ²Ð¾Ð¹ ÐµÐ´Ð¸Ð½ÑÐ¹ USD-ÐºÐ¾ÑÐµÐ»ÑÐº (wallet table) Ð²Ð¼ÐµÑÑÐ¾ kv:
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

# 3) ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ°: Ð°ÐºÑÐ¸Ð²Ð¸ÑÑÐµÐ¼ ÑÐµÑÐµÐ· ÑÐ²Ð¾Ð¸ ÑÑÐ½ÐºÑÐ¸Ð¸ Ñ ÐÐ, Ð° Ð½Ðµ kv:
def _sub_activate(user_id: int, tier_key: str, months: int = 1) -> str:
    dt = activate_subscription_with_tier(user_id, tier_key, months)
    return dt.isoformat()

def _sub_info_text(user_id: int) -> str:
    tier = get_subscription_tier(user_id)
    dt = get_subscription_until(user_id)
    human_until = dt.strftime("%d.%m.%Y") if dt else ""
    bal = _user_balance_get(user_id)
    line_until = f"\nâ³ ÐÐºÑÐ¸Ð²Ð½Ð° Ð´Ð¾: {human_until}" if tier != "free" and human_until else ""
    return f"ð§¾ Ð¢ÐµÐºÑÑÐ°Ñ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ°: {tier.upper() if tier!='free' else 'Ð½ÐµÑ'}{line_until}\nðµ ÐÐ°Ð»Ð°Ð½Ñ: ${bal:.2f}"

# Ð¦ÐµÐ½Ñ â Ð¸Ð· env Ñ Ð¾ÑÐ¼ÑÑÐ»ÐµÐ½Ð½ÑÐ¼Ð¸ Ð´ÐµÑÐ¾Ð»ÑÐ°Ð¼Ð¸
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
            "ð¬ GPT-ÑÐ°Ñ Ð¸ Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÑ (Ð+/-Ð°Ð·Ð¾Ð²ÑÐµ Ð»Ð¸Ð¼Ð¸ÑÑ)",
            "ð¼ Ð¤Ð¾ÑÐ¾-Ð¼Ð°ÑÑÐµÑÑÐºÐ°Ñ: ÑÐ¾Ð½, Ð»ÑÐ³ÐºÐ°Ñ Ð´Ð¾ÑÐ¸ÑÐ¾Ð²ÐºÐ°",
            "ð§ ÐÐ·Ð²ÑÑÐºÐ° Ð¾ÑÐ²ÐµÑÐ¾Ð² (TTS)",
        ],
    },
    "pro": {
        "title": "PRO",
        "rub": PRICE_PRO_RUB,
        "usd": PRICE_PRO_USD,
        "features": [
            "ð ÐÐ»ÑÐ+/-Ð¾ÐºÐ¸Ð¹ ÑÐ°Ð·Ð+/-Ð¾Ñ PDF/DOCX/EPUB",
            "ð¬ Reels/Shorts Ð¿Ð¾ ÑÐ¼ÑÑÐ»Ñ, Ð²Ð¸Ð´ÐµÐ¾ Ð¸Ð· ÑÐ¾ÑÐ¾",
            "ð¼ Outpaint Ð¸ Â«Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸ÐµÂ» ÑÑÐ°ÑÑÑ ÑÐ¾ÑÐ¾",
        ],
    },
    "ultimate": {
        "title": "ULTIMATE",
        "rub": PRICE_ULT_RUB,
        "usd": PRICE_ULT_USD,
        "features": [
            "ð Runway/Luma â Ð¿ÑÐµÐ¼Ð¸ÑÐ¼-ÑÐµÐ½Ð´ÐµÑÑ",
            "ð§  Ð Ð°ÑÑÐ¸ÑÐµÐ½Ð½ÑÐµ Ð»Ð¸Ð¼Ð¸ÑÑ Ð¸ Ð¿ÑÐ¸Ð¾ÑÐ¸ÑÐµÑÐ½Ð°Ñ Ð¾ÑÐµÑÐµÐ´Ñ",
            "ð  PRO-Ð¸Ð½ÑÑÑÑÐ¼ÐµÐ½ÑÑ (Ð°ÑÑÐ¸ÑÐµÐºÑÑÑÐ°/Ð´Ð¸Ð·Ð°Ð¹Ð½)",
        ],
    },
}

def _money_fmt_rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " â½"

def _money_fmt_usd(v: float) -> str:
    return f"${v:.2f}"

def _user_balance_get(user_id: int) -> float:
    # ÐÑÑÐ°ÐµÐ¼ÑÑ Ð²Ð·ÑÑÑ Ð¸Ð· ÑÐ²Ð¾ÐµÐ³Ð¾ ÐºÐ¾ÑÐµÐ»ÑÐºÐ°, ÐµÑÐ»Ð¸ ÐµÑÑÑ, Ð¸Ð½Ð°ÑÐµ â kv
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
    tier = kv_get(f"sub:tier:{user_id}", "") or "Ð½ÐµÑ"
    until = kv_get(f"sub:until:{user_id}", "")
    human_until = ""
    if until:
        try:
            d = datetime.fromisoformat(until)
            human_until = d.strftime("%d.%m.%Y")
        except Exception:
            human_until = until
    bal = _user_balance_get(user_id)
    line_until = f"\nâ³ ÐÐºÑÐ¸Ð²Ð½Ð° Ð´Ð¾: {human_until}" if tier != "Ð½ÐµÑ" and human_until else ""
    return f"ð§¾ Ð¢ÐµÐºÑÑÐ°Ñ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ°: {tier.upper() if tier!='Ð½ÐµÑ' else 'Ð½ÐµÑ'}{line_until}\nðµ ÐÐ°Ð»Ð°Ð½Ñ: {_money_fmt_usd(bal)}"

def _plan_card_text(key: str) -> str:
    p = SUBS_TIERS[key]
    fs = "\n".join("â¢ " + f for f in p["features"])
    return (
        f"â Ð¢Ð°ÑÐ¸Ñ {p['title']}\n"
        f"Ð¦ÐµÐ½Ð°: {_money_fmt_rub(p['rub'])} / {_money_fmt_usd(p['usd'])} Ð² Ð¼ÐµÑ.\n\n"
        f"{fs}\n"
    )

def _plans_overview_text(user_id: int) -> str:
    parts = [
        "â ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° Ð¸ ÑÐ°ÑÐ¸ÑÑ",
        "ÐÑÐ+/-ÐµÑÐ¸ Ð¿Ð¾Ð´ÑÐ¾Ð´ÑÑÐ¸Ð¹ ÑÑÐ¾Ð²ÐµÐ½Ñ â Ð´Ð¾ÑÑÑÐ¿ Ð¾ÑÐºÑÐ¾ÐµÑÑÑ ÑÑÐ°Ð·Ñ Ð¿Ð¾ÑÐ»Ðµ Ð¾Ð¿Ð»Ð°ÑÑ.",
        _sub_info_text(user_id),
        "â â â",
        _plan_card_text("start"),
        _plan_card_text("pro"),
        _plan_card_text("ultimate"),
        "ÐÑÐ+/-ÐµÑÐ¸ÑÐµ ÑÐ°ÑÐ¸Ñ ÐºÐ½Ð¾Ð¿ÐºÐ¾Ð¹ Ð½Ð¸Ð¶Ðµ.",
    ]
    return "\n".join(parts)

def plans_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("â START",    callback_data="plan:start"),
            InlineKeyboardButton("ð PRO",      callback_data="plan:pro"),
            InlineKeyboardButton("ð ULTIMATE", callback_data="plan:ultimate"),
        ]
    ])

def plan_pay_kb(plan_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("ð³ ÐÐ¿Ð»Ð°ÑÐ¸ÑÑ â Ð®Kassa", callback_data=f"pay:yookassa:{plan_key}"),
        ],
        [
            InlineKeyboardButton("ð  ÐÐ¿Ð»Ð°ÑÐ¸ÑÑ â CryptoBot", callback_data=f"pay:cryptobot:{plan_key}"),
        ],
        [
            InlineKeyboardButton("ð§¾ Ð¡Ð¿Ð¸ÑÐ°ÑÑ Ñ Ð+/-Ð°Ð»Ð°Ð½ÑÐ°", callback_data=f"pay:balance:{plan_key}"),
        ],
        [
            InlineKeyboardButton("â¬ï¸ Ð ÑÐ°ÑÐ¸ÑÐ°Ð¼", callback_data="plan:root"),
        ]
    ])

# ÐÐ½Ð¾Ð¿ÐºÐ° Â«â ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° Â· ÐÐ¾Ð¼Ð¾ÑÑÂ»
async def on_btn_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = _plans_overview_text(user_id)
    await update.effective_chat.send_message(text, reply_markup=plans_root_kb())

# ÐÐ+/-ÑÐ°Ð+/-Ð¾ÑÑÐ¸Ðº Ð½Ð°ÑÐ¸Ñ ÐºÐ¾Ð»Ð+/-ÑÐºÐ¾Ð² Ð¿Ð¾ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐµ/Ð¾Ð¿Ð»Ð°ÑÐ°Ð¼ (Ð·Ð°ÑÐµÐ³Ð¸ÑÑÑÐ¸ÑÐ¾Ð²Ð°ÑÑ ÐÐ Ð¾Ð+/-ÑÐµÐ³Ð¾ on_cb!)
async def on_cb_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    user_id = q.from_user.id
    chat_id = q.message.chat.id  # FIX: ÐºÐ¾ÑÑÐµÐºÑÐ½Ð¾Ðµ Ð¿Ð¾Ð»Ðµ Ð² PTB v21+

    # ÐÐ°Ð²Ð¸Ð³Ð°ÑÐ¸Ñ Ð¼ÐµÐ¶Ð´Ñ ÑÐ°ÑÐ¸ÑÐ°Ð¼Ð¸
    if data.startswith("plan:"):
        _, arg = data.split(":", 1)
        if arg == "root":
            await q.edit_message_text(_plans_overview_text(user_id), reply_markup=plans_root_kb())
            await q.answer()
            return
        if arg in SUBS_TIERS:
            await q.edit_message_text(
                _plan_card_text(arg) + "\nÐÑÐ+/-ÐµÑÐ¸ÑÐµ ÑÐ¿Ð¾ÑÐ¾Ð+/- Ð¾Ð¿Ð»Ð°ÑÑ:",
                reply_markup=plan_pay_kb(arg)
            )
            await q.answer()
            return

    # ÐÐ»Ð°ÑÐµÐ¶Ð¸
    if data.startswith("pay:"):
        # Ð+/-ÐµÐ·Ð¾Ð¿Ð°ÑÐ½ÑÐ¹ Ð¿Ð°ÑÑÐ¸Ð½Ð³
        try:
            _, method, plan_key = data.split(":", 2)
        except ValueError:
            await q.answer("ÐÐµÐºÐ¾ÑÑÐµÐºÑÐ½ÑÐµ Ð´Ð°Ð½Ð½ÑÐµ ÐºÐ½Ð¾Ð¿ÐºÐ¸.", show_alert=True)
            return

        plan = SUBS_TIERS.get(plan_key)
        if not plan:
            await q.answer("ÐÐµÐ¸Ð·Ð²ÐµÑÑÐ½ÑÐ¹ ÑÐ°ÑÐ¸Ñ.", show_alert=True)
            return

        # Ð®Kassa ÑÐµÑÐµÐ· Telegram Payments
        if method == "yookassa":
            if not YOOKASSA_PROVIDER_TOKEN:
                await q.answer("Ð®Kassa Ð½Ðµ Ð¿Ð¾Ð´ÐºÐ»ÑÑÐµÐ½Ð° (Ð½ÐµÑ YOOKASSA_PROVIDER_TOKEN).", show_alert=True)
                return

            title = f"ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° {plan['title']} â¢ 1 Ð¼ÐµÑÑÑ"
            desc = "ÐÐ¾ÑÑÑÐ¿ Ðº ÑÑÐ½ÐºÑÐ¸ÑÐ¼ Ð+/-Ð¾ÑÐ° ÑÐ¾Ð³Ð»Ð°ÑÐ½Ð¾ Ð²ÑÐ+/-ÑÐ°Ð½Ð½Ð¾Ð¼Ñ ÑÐ°ÑÐ¸ÑÑ. ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° Ð°ÐºÑÐ¸Ð²Ð¸ÑÑÐµÑÑÑ ÑÑÐ°Ð·Ñ Ð¿Ð¾ÑÐ»Ðµ Ð¾Ð¿Ð»Ð°ÑÑ."
            payload = json.dumps({"tier": plan_key, "months": 1})

            # Telegram Ð¾Ð¶Ð¸Ð´Ð°ÐµÑ ÑÑÐ¼Ð¼Ñ Ð² Ð¼Ð¸Ð½Ð¾ÑÐ½ÑÑ ÐµÐ´Ð¸Ð½Ð¸ÑÐ°Ñ (ÐºÐ¾Ð¿ÐµÐ¹ÐºÐ¸/ÑÐµÐ½ÑÑ)
            if YOOKASSA_CURRENCY == "RUB":
                total_minor = int(round(float(plan["rub"]) * 100))
            else:
                total_minor = int(round(float(plan["usd"]) * 100))

            prices = [LabeledPrice(label=f"{plan['title']} 1 Ð¼ÐµÑ.", amount=total_minor)]
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
            await q.answer("Ð¡ÑÑÑ Ð²ÑÑÑÐ°Ð²Ð»ÐµÐ½ â")
            return

        # CryptoBot (Crypto Pay API: ÑÐ¾Ð·Ð´Ð°ÑÐ¼ Ð¸Ð½Ð²Ð¾Ð¹Ñ Ð¸ Ð¾ÑÐ´Ð°ÑÐ¼ ÑÑÑÐ»ÐºÑ)
        if method == "cryptobot":  # FIX: Ð²ÑÑÐ¾Ð²Ð½ÐµÐ½ Ð¾ÑÑÑÑÐ¿
            if not CRYPTO_PAY_API_TOKEN:
                await q.answer("CryptoBot Ð½Ðµ Ð¿Ð¾Ð´ÐºÐ»ÑÑÑÐ½ (Ð½ÐµÑ CRYPTO_PAY_API_TOKEN).", show_alert=True)
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
                            "description": f"Subscription {plan['title']} â¢ 1 month",
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
                    [InlineKeyboardButton("ð  ÐÐ¿Ð»Ð°ÑÐ¸ÑÑ Ð² CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("â¬ï¸ Ð ÑÐ°ÑÐ¸ÑÑ", callback_data=f"plan:{plan_key}")],
                ])
                msg = await q.edit_message_text(
                    _plan_card_text(plan_key) + "\nÐÑÐºÑÐ¾Ð¹ÑÐµ ÑÑÑÐ»ÐºÑ Ð´Ð»Ñ Ð¾Ð¿Ð»Ð°ÑÑ:",
                    reply_markup=kb
                )
                # Ð°Ð²ÑÐ¾Ð¿ÑÐ» ÑÑÐ°ÑÑÑÐ° Ð¸Ð¼ÐµÐ½Ð½Ð¾ Ð´Ð»Ñ ÐÐÐÐÐÐ¡ÐÐ
                context.application.create_task(_poll_crypto_sub_invoice(
                    context, msg.chat.id, msg.message_id, user_id, inv_id, plan_key, 1  # FIX: msg.chat.id
                ))
                await q.answer()
            except Exception as e:
                await q.answer("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ¾Ð·Ð´Ð°ÑÑ ÑÑÑÑ Ð² CryptoBot.", show_alert=True)
                log.exception("CryptoBot invoice error: %s", e)
            return

        # Ð¡Ð¿Ð¸ÑÐ°Ð½Ð¸Ðµ Ñ Ð²Ð½ÑÑÑÐµÐ½Ð½ÐµÐ³Ð¾ Ð+/-Ð°Ð»Ð°Ð½ÑÐ° (USD)
        if method == "balance":
            price_usd = float(plan["usd"])
            if not _user_balance_debit(user_id, price_usd):
                await q.answer("ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ÑÑÐµÐ´ÑÑÐ² Ð½Ð° Ð²Ð½ÑÑÑÐµÐ½Ð½ÐµÐ¼ Ð+/-Ð°Ð»Ð°Ð½ÑÐµ.", show_alert=True)
                return
            until = _sub_activate(user_id, plan_key, months=1)
            await q.edit_message_text(
                f"â ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° {plan['title']} Ð°ÐºÑÐ¸Ð²Ð¸ÑÐ¾Ð²Ð°Ð½Ð° Ð´Ð¾ {until[:10]}.\n"
                f"ðµ Ð¡Ð¿Ð¸ÑÐ°Ð½Ð¾: {_money_fmt_usd(price_usd)}. "
                f"Ð¢ÐµÐºÑÑÐ¸Ð¹ Ð+/-Ð°Ð»Ð°Ð½Ñ: {_money_fmt_usd(_user_balance_get(user_id))}",
                reply_markup=plans_root_kb(),
            )
            await q.answer()
            return

    # ÐÑÐ»Ð¸ ÐºÐ¾Ð»Ð+/-ÑÐº Ð½Ðµ Ð½Ð°Ñ â Ð¿ÑÐ¾Ð¿ÑÑÐºÐ°ÐµÐ¼ Ð´Ð°Ð»ÑÑÐµ
    await q.answer()
    return


# ÐÑÐ»Ð¸ Ñ ÑÐµÐ+/-Ñ ÑÐ¶Ðµ ÐµÑÑÑ on_precheckout / on_successful_payment â Ð¾ÑÑÐ°Ð²Ñ Ð¸Ñ.
# ÐÑÐ»Ð¸ Ð½ÐµÑ, Ð¼Ð¾Ð¶ÐµÑÑ Ð¸ÑÐ¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÑ ÑÑÐ¸ Ð¿ÑÐ¾ÑÑÑÐµ ÑÐµÐ°Ð»Ð¸Ð·Ð°ÑÐ¸Ð¸:

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.pre_checkout_query.answer(ok=True)
    except Exception as e:
        log.exception("precheckout error: %s", e)

async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ð£Ð½Ð¸Ð²ÐµÑÑÐ°Ð»ÑÐ½ÑÐ¹ Ð¾Ð+/-ÑÐ°Ð+/-Ð¾ÑÑÐ¸Ðº Telegram Payments:
    - ÐÐ¾Ð´Ð´ÐµÑÐ¶Ð¸Ð²Ð°ÐµÑ payload Ð² Ð´Ð²ÑÑ ÑÐ¾ÑÐ¼Ð°ÑÐ°Ñ:
        1) JSON: {"tier":"pro","months":1}
        2) Ð¡ÑÑÐ¾ÐºÐ°: "sub:pro:1"
    - ÐÐ½Ð°ÑÐµ ÑÑÐ°ÐºÑÑÐµÑ ÐºÐ°Ðº Ð¿Ð¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ðµ ÐµÐ´Ð¸Ð½Ð¾Ð³Ð¾ USD-ÐºÐ¾ÑÐµÐ»ÑÐºÐ°.
    """
    try:
        sp = update.message.successful_payment
        payload_raw = sp.invoice_payload or ""
        total_minor = sp.total_amount or 0
        rub = total_minor / 100.0
        uid = update.effective_user.id

        # 1) ÐÑÑÐ°ÐµÐ¼ÑÑ ÑÐ°ÑÐ¿Ð°ÑÑÐ¸ÑÑ JSON
        tier, months = None, None
        try:
            if payload_raw.strip().startswith("{"):
                obj = json.loads(payload_raw)
                tier = (obj.get("tier") or "").strip().lower() or None
                months = int(obj.get("months") or 1)
        except Exception:
            pass

        # 2) ÐÑÑÐ°ÐµÐ¼ÑÑ ÑÐ°ÑÐ¿Ð°ÑÑÐ¸ÑÑ ÑÑÑÐ¾ÐºÐ¾Ð²ÑÐ¹ ÑÐ¾ÑÐ¼Ð°Ñ "sub:tier:months"
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
                f"ð ÐÐ¿Ð»Ð°ÑÐ° Ð¿ÑÐ¾ÑÐ»Ð° ÑÑÐ¿ÐµÑÐ½Ð¾!\n"
                f"â ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° {tier.upper()} Ð°ÐºÑÐ¸Ð²Ð¸ÑÐ¾Ð²Ð°Ð½Ð° Ð´Ð¾ {until.strftime('%Y-%m-%d')}."
            )
            return

        # ÐÐ½Ð°ÑÐµ ÑÑÐ¸ÑÐ°ÐµÐ¼, ÑÑÐ¾ ÑÑÐ¾ Ð¿Ð¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ðµ ÐºÐ¾ÑÐµÐ»ÑÐºÐ° Ð² ÑÑÐ+/-Ð»ÑÑ
        usd = rub / max(1e-9, USD_RUB)
        _wallet_total_add(uid, usd)
        await update.effective_message.reply_text(
            f"ð³ ÐÐ¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ðµ: {rub:.0f} â½ â ${usd:.2f} Ð·Ð°ÑÐ¸ÑÐ»ÐµÐ½Ð¾ Ð½Ð° ÐµÐ´Ð¸Ð½ÑÐ¹ Ð+/-Ð°Ð»Ð°Ð½Ñ."
        )

    except Exception as e:
        log.exception("successful_payment handler error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("â ï¸ ÐÑÐ¸Ð+/-ÐºÐ° Ð¾Ð+/-ÑÐ°Ð+/-Ð¾ÑÐºÐ¸ Ð¿Ð»Ð°ÑÐµÐ¶Ð°. ÐÑÐ»Ð¸ Ð´ÐµÐ½ÑÐ³Ð¸ ÑÐ¿Ð¸ÑÐ°Ð»Ð¸ÑÑ â Ð½Ð°Ð¿Ð¸ÑÐ¸ÑÐµ Ð² Ð¿Ð¾Ð´Ð´ÐµÑÐ¶ÐºÑ.")
# âââââââââ ÐÐ¾Ð½ÐµÑ PATCH âââââââââ
        
# âââââââââ ÐÐ¾Ð¼Ð°Ð½Ð´Ð° /img âââââââââ
async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip() if context.args else ""
    if not prompt:
        await update.effective_message.reply_text("Ð¤Ð¾ÑÐ¼Ð°Ñ: /img <Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ðµ>")
        return

    async def _go():
        await _do_img_generate(update, context, prompt)

    user_id = update.effective_user.id
    await _try_pay_then_do(
        update, context, user_id,
        "img", IMG_COST_USD, _go,
        remember_kind="img_generate", remember_payload={"prompt": prompt}
    )


# âââââââââ Photo quick actions âââââââââ
def photo_quick_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("â¨ ÐÐ¶Ð¸Ð²Ð¸ÑÑ ÑÐ¾ÑÐ¾", callback_data="pedit:revive")],
        [InlineKeyboardButton("ð§¼ Ð£Ð´Ð°Ð»Ð¸ÑÑ ÑÐ¾Ð½",  callback_data="pedit:removebg"),
         InlineKeyboardButton("ð¼ ÐÐ°Ð¼ÐµÐ½Ð¸ÑÑ ÑÐ¾Ð½", callback_data="pedit:replacebg")],
        [InlineKeyboardButton("ð§ Ð Ð°ÑÑÐ¸ÑÐ¸ÑÑ ÐºÐ°Ð´Ñ (outpaint)", callback_data="pedit:outpaint"),
         InlineKeyboardButton("ð½ Ð Ð°ÑÐºÐ°Ð´ÑÐ¾Ð²ÐºÐ°", callback_data="pedit:story")],
        [InlineKeyboardButton("ð ÐÐ°ÑÑÐ¸Ð½ÐºÐ° Ð¿Ð¾ Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ñ (Luma)", callback_data="pedit:lumaimg")],
        [InlineKeyboardButton("ð ÐÐ½Ð°Ð»Ð¸Ð· ÑÐ¾ÑÐ¾", callback_data="pedit:vision")],
    ])


def revive_engine_kb() -> InlineKeyboardMarkup:
    """
    ÐÐ½Ð¾Ð¿ÐºÐ¸ Ð²ÑÐ+/-Ð¾ÑÐ° Ð´Ð²Ð¸Ð¶ÐºÐ° Ð´Ð»Ñ Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ñ ÑÐ¾ÑÐ¾.
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
        await update.effective_message.reply_text("rembg Ð½Ðµ ÑÑÑÐ°Ð½Ð¾Ð²Ð»ÐµÐ½. Ð£ÑÑÐ°Ð½Ð¾Ð²Ð¸ÑÐµ rembg/onnxruntime.")
        return
    try:
        out = rembg_remove(img_bytes)
        bio = BytesIO(out); bio.name = "no_bg.png"
        await update.effective_message.reply_document(InputFile(bio), caption="Ð¤Ð¾Ð½ ÑÐ´Ð°Ð»ÑÐ½ â")
    except Exception as e:
        log.exception("removebg error: %s", e)
        await update.effective_message.reply_text("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ´Ð°Ð»Ð¸ÑÑ ÑÐ¾Ð½.")

async def _pedit_replacebg(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    if Image is None:
        await update.effective_message.reply_text("Pillow Ð½Ðµ ÑÑÑÐ°Ð½Ð¾Ð²Ð»ÐµÐ½.")
        return
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGBA")
        bg = im.convert("RGB").filter(ImageFilter.GaussianBlur(radius=22)) if ImageFilter else im.convert("RGB")
        bio = BytesIO(); bg.save(bio, format="JPEG", quality=92); bio.seek(0); bio.name = "bg_blur.jpg"
        await update.effective_message.reply_photo(InputFile(bio), caption="ÐÐ°Ð¼ÐµÐ½Ð¸Ð» ÑÐ¾Ð½ Ð½Ð° ÑÐ°Ð·Ð¼ÑÑÑÐ¹ Ð²Ð°ÑÐ¸Ð°Ð½Ñ.")
    except Exception as e:
        log.exception("replacebg error: %s", e)
        await update.effective_message.reply_text("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð·Ð°Ð¼ÐµÐ½Ð¸ÑÑ ÑÐ¾Ð½.")

async def _pedit_outpaint(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    if Image is None:
        await update.effective_message.reply_text("Pillow Ð½Ðµ ÑÑÑÐ°Ð½Ð¾Ð²Ð»ÐµÐ½.")
        return
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGB")
        pad = max(64, min(256, max(im.size)//6))
        big = Image.new("RGB", (im.width + 2*pad, im.height + 2*pad))
        bg = im.resize(big.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(radius=24)) if ImageFilter else im.resize(big.size)
        big.paste(bg, (0, 0)); big.paste(im, (pad, pad))
        bio = BytesIO(); big.save(bio, format="JPEG", quality=92); bio.seek(0); bio.name = "outpaint.jpg"
        await update.effective_message.reply_photo(InputFile(bio), caption="ÐÑÐ¾ÑÑÐ¾Ð¹ outpaint: ÑÐ°ÑÑÐ¸ÑÐ¸Ð» Ð¿Ð¾Ð»Ð¾ÑÐ½Ð¾ Ñ Ð¼ÑÐ³ÐºÐ¸Ð¼Ð¸ ÐºÑÐ°ÑÐ¼Ð¸.")
    except Exception as e:
        log.exception("outpaint error: %s", e)
        await update.effective_message.reply_text("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ´ÐµÐ»Ð°ÑÑ outpaint.")

async def _pedit_storyboard(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    try:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        desc = await ask_openai_vision("ÐÐ¿Ð¸ÑÐ¸ ÐºÐ»ÑÑÐµÐ²ÑÐµ ÑÐ»ÐµÐ¼ÐµÐ½ÑÑ ÐºÐ°Ð´ÑÐ° Ð¾ÑÐµÐ½Ñ ÐºÑÐ°ÑÐºÐ¾.", b64, sniff_image_mime(img_bytes))
        plan = await ask_openai_text(
            "Ð¡Ð´ÐµÐ»Ð°Ð¹ ÑÐ°ÑÐºÐ°Ð´ÑÐ¾Ð²ÐºÑ (6 ÐºÐ°Ð´ÑÐ¾Ð²) Ð¿Ð¾Ð´ 6â10 ÑÐµÐºÑÐ½Ð´Ð½ÑÐ¹ ÐºÐ»Ð¸Ð¿. "
            "ÐÐ°Ð¶Ð´ÑÐ¹ ÐºÐ°Ð´Ñ â 1 ÑÑÑÐ¾ÐºÐ°: ÐºÐ°Ð´Ñ/Ð´ÐµÐ¹ÑÑÐ²Ð¸Ðµ/ÑÐ°ÐºÑÑÑ/ÑÐ²ÐµÑ. ÐÑÐ½Ð¾Ð²Ð°:\n" + (desc or "")
        )
        await update.effective_message.reply_text("Ð Ð°ÑÐºÐ°Ð´ÑÐ¾Ð²ÐºÐ°:\Ð½" + plan)
    except Exception as e:
        log.exception("storyboard error: %s", e)
        await update.effective_message.reply_text("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð¿Ð¾ÑÑÑÐ¾Ð¸ÑÑ ÑÐ°ÑÐºÐ°Ð´ÑÐ¾Ð²ÐºÑ.")


# âââââââââ WebApp data (ÑÐ°ÑÐ¸ÑÑ/Ð¿Ð¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ) âââââââââ
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
            desc = f"ÐÑÐ¾ÑÐ¼Ð»ÐµÐ½Ð¸Ðµ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ¸ {tier.upper()} Ð½Ð° {months} Ð¼ÐµÑ."
            await update.effective_message.reply_text(
                f"{desc}\nÐÑÐ+/-ÐµÑÐ¸ÑÐµ ÑÐ¿Ð¾ÑÐ¾Ð+/-:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("ÐÐ¿Ð»Ð°ÑÐ¸ÑÑ ÐºÐ°ÑÑÐ¾Ð¹ (Ð®Kassa)", callback_data=f"buyinv:{tier}:{months}")],
                    [InlineKeyboardButton("Ð¡Ð¿Ð¸ÑÐ°ÑÑ Ñ Ð+/-Ð°Ð»Ð°Ð½ÑÐ° (USD)",  callback_data=f"buywallet:{tier}:{months}")],
                ])
            )
            return

        if typ in ("topup_rub", "rub_topup"):
            amount_rub = int(data.get("amount") or 0)
            if amount_rub < MIN_RUB_FOR_INVOICE:
                await update.effective_message.reply_text(f"ÐÐ¸Ð½Ð¸Ð¼Ð°Ð»ÑÐ½Ð°Ñ ÑÑÐ¼Ð¼Ð°: {MIN_RUB_FOR_INVOICE} â½")
                return
            await _send_invoice_rub("ÐÐ¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ðµ Ð+/-Ð°Ð»Ð°Ð½ÑÐ°", "ÐÐ´Ð¸Ð½ÑÐ¹ ÐºÐ¾ÑÐµÐ»ÑÐº", amount_rub, "t=3", update)
            return

        if typ in ("topup_crypto", "crypto_topup"):
            if not CRYPTO_PAY_API_TOKEN:
                await update.effective_message.reply_text("CryptoBot Ð½Ðµ Ð½Ð°ÑÑÑÐ¾ÐµÐ½.")
                return
            usd = float(data.get("usd") or 0)
            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(usd, asset="USDT")
            if not inv_id or not pay_url:
                await update.effective_message.reply_text("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ¾Ð·Ð´Ð°ÑÑ ÑÑÑÑ Ð² CryptoBot.")
                return
            msg = await update.effective_message.reply_text(
                f"ÐÐ¿Ð»Ð°ÑÐ¸ÑÐµ ÑÐµÑÐµÐ· CryptoBot: â ${usd_amount:.2f} ({asset}).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("ÐÐ¿Ð»Ð°ÑÐ¸ÑÑ Ð² CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("ÐÑÐ¾Ð²ÐµÑÐ¸ÑÑ Ð¾Ð¿Ð»Ð°ÑÑ", callback_data=f"crypto:check:{inv_id}")]
                ])
            )
            context.application.create_task(_poll_crypto_invoice(
                context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id, usd_amount
            ))
            return

        await update.effective_message.reply_text("ÐÐ¾Ð»ÑÑÐµÐ½Ñ Ð´Ð°Ð½Ð½ÑÐµ Ð¸Ð· Ð¼Ð¸Ð½Ð¸-Ð¿ÑÐ¸Ð»Ð¾Ð¶ÐµÐ½Ð¸Ñ, Ð½Ð¾ ÐºÐ¾Ð¼Ð°Ð½Ð´Ð° Ð½Ðµ ÑÐ°ÑÐ¿Ð¾Ð·Ð½Ð°Ð½Ð°.")
    except Exception as e:
        log.exception("on_webapp_data error: %s", e)
        await update.effective_message.reply_text("ÐÑÐ¸Ð+/-ÐºÐ° Ð¾Ð+/-ÑÐ°Ð+/-Ð¾ÑÐºÐ¸ Ð´Ð°Ð½Ð½ÑÑ Ð¼Ð¸Ð½Ð¸-Ð¿ÑÐ¸Ð»Ð¾Ð¶ÐµÐ½Ð¸Ñ.")


# âââââââââ CallbackQuery (Ð²ÑÑ Ð¾ÑÑÐ°Ð»ÑÐ½Ð¾Ðµ) âââââââââ

_pending_actions = {}

def _new_aid() -> str:
    return uuid.uuid4().hex[:12]

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()
    
        # Language selection (lang:<code>)
    if data.startswith("lang:"):
        code = data.split(":", 1)[1].strip()
        uid = update.effective_user.id

        # "keep current" shortcut
        if code != "__keep__":
            set_lang(uid, code)

        await q.answer()

        # ÐÐ¾ÐºÐ°Ð·ÑÐ²Ð°ÐµÐ¼ Ð³Ð»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½Ñ Ð¿Ð¾ÑÐ»Ðµ Ð²ÑÐ+/-Ð¾ÑÐ° ÑÐ·ÑÐºÐ°
        try:
            await q.message.reply_text(t(uid, "lang_set"), reply_markup=main_keyboard(uid))
        except Exception:
            pass

        try:
            await _send_main_menu(update, context)
        except Exception:
            pass
        return

    # Engine selection (engine:<name>)
    if data.startswith("engine:"):
        await q.answer()
        eng = data.split(":", 1)[1].strip() if ":" in data else "gpt"
        engine_set(uid, eng)

        # ÐÐ¾ÑÐ¾ÑÐºÐ¾Ðµ Ð¿Ð¾Ð´ÑÐ²ÐµÑÐ¶Ð´ÐµÐ½Ð¸Ðµ + Ð¿Ð¾Ð´ÑÐºÐ°Ð·ÐºÐ°
        hint = {
            "gpt": "Ð¢ÐµÐ¿ÐµÑÑ Ð¿Ð¾ ÑÐ¼Ð¾Ð»ÑÐ°Ð½Ð¸Ñ Ð¾ÑÐ²ÐµÑÐ°Ñ ÑÐµÐºÑÑÐ¾Ð¼ (GPT).",
            "images": "Ð¢ÐµÐ¿ÐµÑÑ Ð»ÑÐ+/-Ð¾Ð¹ ÑÐµÐºÑÑ Ð+/-ÑÐ´ÐµÑ ÑÑÐ°ÐºÑÐ¾Ð²Ð°ÑÑÑÑ ÐºÐ°Ðº Ð¿ÑÐ¾Ð¼Ð¿Ñ Ð´Ð»Ñ ÐºÐ°ÑÑÐ¸Ð½ÐºÐ¸ (Images).",
            "kling": "Ð¢ÐµÐ¿ÐµÑÑ Ð»ÑÐ+/-Ð¾Ð¹ ÑÐµÐºÑÑ Ð+/-ÑÐ´ÐµÑ ÑÑÐ°ÐºÑÐ¾Ð²Ð°ÑÑÑÑ ÐºÐ°Ðº Ð¿ÑÐ¾Ð¼Ð¿Ñ Ð´Ð»Ñ Ð²Ð¸Ð´ÐµÐ¾ Ð² Kling.",
            "luma": "Ð¢ÐµÐ¿ÐµÑÑ Ð»ÑÐ+/-Ð¾Ð¹ ÑÐµÐºÑÑ Ð+/-ÑÐ´ÐµÑ ÑÑÐ°ÐºÑÐ¾Ð²Ð°ÑÑÑÑ ÐºÐ°Ðº Ð¿ÑÐ¾Ð¼Ð¿Ñ Ð´Ð»Ñ Ð²Ð¸Ð´ÐµÐ¾ Ð² Luma.",
            "runway": "Runway Ð²ÑÐ+/-ÑÐ°Ð½. ÐÐ»Ñ Ð²Ð¸Ð´ÐµÐ¾ Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐ¹ÑÐµ Â«ÑÐ´ÐµÐ»Ð°Ð¹ Ð²Ð¸Ð´ÐµÐ¾â¦Â» (ÑÐµÐºÑÑâÐ²Ð¸Ð´ÐµÐ¾ Ð¼Ð¾Ð¶ÐµÑ Ð+/-ÑÑÑ Ð¾ÑÐºÐ»ÑÑÑÐ½).",
            "sora": "Sora Ð²ÑÐ+/-ÑÐ°Ð½ (ÑÐµÑÐµÐ· Comet). ÐÑÐ»Ð¸ ÐºÐ»ÑÑÐ¸/ÑÐ½Ð´Ð¿Ð¾Ð¸Ð½Ñ Ð½Ðµ Ð·Ð°Ð´Ð°Ð½Ñ â Ð¿Ð¾ÐºÐ°Ð¶Ñ Ð¿Ð¾Ð´ÑÐºÐ°Ð·ÐºÑ.",
            "gemini": "Gemini Ð²ÑÐ+/-ÑÐ°Ð½ (ÑÐµÑÐµÐ· Comet). ÐÑÐ»Ð¸ ÐºÐ»ÑÑÐ¸/ÑÐ½Ð´Ð¿Ð¾Ð¸Ð½Ñ Ð½Ðµ Ð·Ð°Ð´Ð°Ð½Ñ â Ð+/-ÑÐ´ÐµÑ Ð¿Ð¾Ð´ÑÐºÐ°Ð·ÐºÐ°/ÑÐ¾Ð»Ð+/-ÑÐº.",
            "suno": "Suno Ð²ÑÐ+/-ÑÐ°Ð½ (Ð¼ÑÐ·ÑÐºÐ°). Ð¡ÐµÐ¹ÑÐ°Ñ Ð²ÐºÐ»ÑÑÑÐ½ ÐºÐ°Ðº ÑÐµÐ¶Ð¸Ð¼-Ð¿Ð¾Ð´ÑÐºÐ°Ð·ÐºÐ°.",
            "midjourney": "Midjourney Ð²ÑÐ+/-ÑÐ°Ð½. Ð¡ÐµÐ¹ÑÐ°Ñ Ð²ÐºÐ»ÑÑÑÐ½ ÐºÐ°Ðº ÑÐµÐ¶Ð¸Ð¼-Ð¿Ð¾Ð´ÑÐºÐ°Ð·ÐºÐ°.",
            "stt_tts": "Ð ÐµÐ¶Ð¸Ð¼ STT/TTS: Ð¼Ð¾Ð¶Ð½Ð¾ Ð¿ÑÐ¸ÑÐ»Ð°ÑÑ Ð³Ð¾Ð»Ð¾ÑÐ¾Ð²Ð¾Ðµ Ð¸Ð»Ð¸ Ð²ÐºÐ»ÑÑÐ¸ÑÑ Ð¾Ð·Ð²ÑÑÐºÑ Ð¾ÑÐ²ÐµÑÐ¾Ð².",
        }.get(eng, f"ÐÐ²Ð¸Ð¶Ð¾Ðº Ð²ÑÐ+/-ÑÐ°Ð½: {eng}")

        with contextlib.suppress(Exception):
            await q.message.reply_text(hint, reply_markup=main_keyboard(uid))
        return

    try:
        # ð ÐÑÐ+/-Ð¾Ñ Ð´Ð²Ð¸Ð¶ÐºÐ° Ð´Ð»Ñ Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ñ ÑÐ¾ÑÐ¾ (Runway/Kling/Luma)
        if data.startswith("revive_engine:"):
            await q.answer()
            engine = data.split(":", 1)[1] if ":" in data else ""
            await revive_old_photo_flow(update, context, engine=engine)
            return

        # Photo edit / Ð°Ð½Ð¸Ð¼Ð°ÑÐ¸Ñ Ð¿Ð¾ inline-ÐºÐ½Ð¾Ð¿ÐºÐ°Ð¼ pedit:...
        if data.startswith("pedit:"):
            await q.answer()
            action = data.split(":", 1)[1] if ":" in data else ""
            user_id = update.effective_user.id

            # Ð¡Ð¿ÐµÑÐ¸Ð°Ð»ÑÐ½ÑÐ¹ ÑÐ»ÑÑÐ°Ð¹: Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ðµ ÑÐ¾ÑÐ¾ â Ð¿Ð¾ÐºÐ°Ð·Ð°ÑÑ Ð²ÑÐ+/-Ð¾Ñ Ð´Ð²Ð¸Ð¶ÐºÐ°
            if action == "revive":
                if user_id not in _LAST_ANIM_PHOTO:
                    await q.edit_message_text(
                        "ÐÐµ Ð½Ð°ÑÑÐ» ÑÐ¾ÑÐ¾ Ð² ÐºÑÑÐµ. ÐÑÐ¸ÑÐ»Ð¸ ÑÐ¾ÑÐ¾ ÐµÑÑ ÑÐ°Ð·, Ð¿Ð¾Ð¶Ð°Ð»ÑÐ¹ÑÑÐ°."
                    )
                    return

                await q.edit_message_text(
                    "ÐÑÐ+/-ÐµÑÐ¸ Ð´Ð²Ð¸Ð¶Ð¾Ðº Ð´Ð»Ñ Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ñ ÑÐ¾ÑÐ¾:",
                    reply_markup=revive_engine_kb(),
                )
                return

            # ÐÐ»Ñ Ð¾ÑÑÐ°Ð»ÑÐ½ÑÑ pedit:* Ð½ÑÐ¶ÐµÐ½ Ð+/-Ð°Ð¹ÑÐ¾Ð²ÑÐ¹ Ð¾Ð+/-ÑÐ°Ð· ÐºÐ°ÑÑÐ¸Ð½ÐºÐ¸
            img = _get_cached_photo(user_id)
            if not img:
                await q.edit_message_text(
                    "ÐÐµ Ð½Ð°ÑÑÐ» ÑÐ¾ÑÐ¾ Ð² ÐºÑÑÐµ. ÐÑÐ¸ÑÐ»Ð¸ ÑÐ¾ÑÐ¾ ÐµÑÑ ÑÐ°Ð·, Ð¿Ð¾Ð¶Ð°Ð»ÑÐ¹ÑÑÐ°."
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

            # Ð½ÐµÐ¸Ð·Ð²ÐµÑÑÐ½ÑÐ¹ pedit:* â Ð¿ÑÐ¾ÑÑÐ¾ Ð²ÑÑÐ¾Ð´Ð¸Ð¼
            return

        # TOPUP Ð¼ÐµÐ½Ñ
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
                    f"ÐÐ¸Ð½Ð¸Ð¼Ð°Ð»ÑÐ½Ð°Ñ ÑÑÐ¼Ð¼Ð° Ð¿Ð¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ {MIN_RUB_FOR_INVOICE} â½."
                )
                return
            title = "ÐÐ¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ðµ Ð+/-Ð°Ð»Ð°Ð½ÑÐ° (ÐºÐ°ÑÑÐ°)"
            desc = f"ÐÐ¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ðµ USD-Ð+/-Ð°Ð»Ð°Ð½ÑÐ° Ð+/-Ð¾ÑÐ° Ð½Ð° ÑÑÐ¼Ð¼Ñ â {amount_rub} â½"
            payload = f"topup:{amount_rub}"
            ok = await _send_invoice_rub(title, desc, amount_rub, payload, update)
            if not ok:
                await q.answer("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð²ÑÑÑÐ°Ð²Ð¸ÑÑ ÑÑÑÑ", show_alert=True)
            return

        # TOPUP CRYPTO: Ð²ÑÐ+/-Ð¾Ñ ÑÑÐ¼Ð¼Ñ
        if data == "topup:crypto":
            await q.answer()
            await q.edit_message_text(
                "ÐÐ¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ðµ ÑÐµÑÐµÐ· CryptoBot (USDT):\n\n"
                "ÐÑÐ+/-ÐµÑÐ¸ÑÐµ ÑÑÐ¼Ð¼Ñ Ð¿Ð¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ ($):",
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
                        [InlineKeyboardButton("ÐÑÐ¼ÐµÐ½Ð°", callback_data="topup:cancel")],
                    ]
                ),
            )
            return

        # TOPUP CRYPTO: ÑÐ¾Ð·Ð´Ð°Ð½Ð¸Ðµ Ð¸Ð½Ð²Ð¾Ð¹ÑÐ°
        if data.startswith("topup:crypto:"):
            await q.answer()
            try:
                usd = float((data.split(":", 2)[-1] or "0").strip() or "0")
            except Exception:
                usd = 0.0
            if usd <= 0.0:
                await q.edit_message_text("ÐÐµÐ²ÐµÑÐ½Ð°Ñ ÑÑÐ¼Ð¼Ð°.")
                return

            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(
                usd, asset="USDT", description="Wallet top-up"
            )
            if not inv_id or not pay_url:
                await q.edit_message_text(
                    "ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ¾Ð·Ð´Ð°ÑÑ ÑÑÑÑ Ð² CryptoBot. ÐÐ¾Ð¿ÑÐ¾Ð+/-ÑÐ¹ÑÐµ Ð¿Ð¾Ð·Ð¶Ðµ."
                )
                return

            msg = await update.effective_message.reply_text(
                f"ÐÐ¿Ð»Ð°ÑÐ¸ÑÐµ ÑÐµÑÐµÐ· CryptoBot: â ${usd_amount:.2f} ({asset}).\n"
                "ÐÐ¾ÑÐ»Ðµ Ð¾Ð¿Ð»Ð°ÑÑ Ð+/-Ð°Ð»Ð°Ð½Ñ Ð¿Ð¾Ð¿Ð¾Ð»Ð½Ð¸ÑÑÑ Ð°Ð²ÑÐ¾Ð¼Ð°ÑÐ¸ÑÐµÑÐºÐ¸.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("ÐÐ¿Ð»Ð°ÑÐ¸ÑÑ Ð² CryptoBot", url=pay_url)],
                        [InlineKeyboardButton("ÐÑÐ¾Ð²ÐµÑÐ¸ÑÑ Ð¾Ð¿Ð»Ð°ÑÑ", callback_data=f"crypto:check:{inv_id}")],
                    ]
                ),
            )
            # Ð·Ð°Ð¿ÑÑÑÐ¸Ð¼ ÑÐ¾Ð½Ð¾Ð²ÑÐ¹ Ð¿Ð¾Ð»Ð»Ð¸Ð½Ð³ Ð¸Ð½Ð²Ð¾Ð¹ÑÐ°
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

        # CryptoBot: ÑÑÑÐ½Ð°Ñ Ð¿ÑÐ¾Ð²ÐµÑÐºÐ° Ð¸Ð½Ð²Ð¾Ð¹ÑÐ°
        if data.startswith("crypto:check:"):
            await q.answer()
            inv_id = data.split(":", 2)[-1]
            inv = await _crypto_get_invoice(inv_id)
            status = (inv or {}).get("status", "").lower() if inv else ""
            paid_amount = (inv or {}).get("amount") or 0
            asset = (inv or {}).get("asset") or "USDT"

            if status == "paid":
                await q.edit_message_text(
                    f"â ÐÐ»Ð°ÑÑÐ¶ Ð¿Ð¾Ð»ÑÑÐµÐ½: {paid_amount} {asset}.\n"
                    "ÐÐ°Ð»Ð°Ð½Ñ Ð+/-ÑÐ´ÐµÑ Ð¿Ð¾Ð¿Ð¾Ð»Ð½ÐµÐ½ Ð² ÑÐµÑÐµÐ½Ð¸Ðµ Ð¼Ð¸Ð½ÑÑÑ."
                )
            elif status == "active":
                await q.edit_message_text("Ð¡ÑÑÑ ÐµÑÑ Ð½Ðµ Ð¾Ð¿Ð»Ð°ÑÐµÐ½.")
            else:
                await q.edit_message_text("Ð¡ÑÑÑ Ð½Ðµ Ð°ÐºÑÐ¸Ð²ÐµÐ½ Ð¸Ð»Ð¸ Ð¸ÑÑÑÐº.")
            return

        # TOPUP cancel
        if data == "topup:cancel":
            await q.answer()
            await q.edit_message_text("ÐÐ¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ðµ Ð¾ÑÐ¼ÐµÐ½ÐµÐ½Ð¾.")
            return

        # ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ°: ÑÑÐ°ÑÐ¾Ðµ Ð¼ÐµÐ½Ñ /plans (ÐµÑÐ»Ð¸ Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÑÑ)
        if data == "plans":
            await q.answer()
            await cmd_plans(update, context)
            return

        # ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ°: Ð²ÑÐ+/-Ð¾Ñ ÑÐ°ÑÐ¸ÑÐ° Ð¸ ÑÑÐ¾ÐºÐ°
        if data.startswith("buy:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            desc = f"ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° {tier.upper()} Ð½Ð° {months} Ð¼ÐµÑ."
            await q.edit_message_text(
                f"{desc}\nÐÑÐ+/-ÐµÑÐ¸ÑÐµ ÑÐ¿Ð¾ÑÐ¾Ð+/- Ð¾Ð¿Ð»Ð°ÑÑ:",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "ÐÐ¿Ð»Ð°ÑÐ¸ÑÑ ÐºÐ°ÑÑÐ¾Ð¹ (Ð®Kassa)",
                                callback_data=f"buyinv:{tier}:{months}",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "Ð¡Ð¿Ð¸ÑÐ°ÑÑ Ñ Ð+/-Ð°Ð»Ð°Ð½ÑÐ° (USD)",
                                callback_data=f"buywallet:{tier}:{months}",
                            )
                        ],
                    ]
                ),
            )
            return

        # ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° ÑÐµÑÐµÐ· Ð®Kassa
        if data.startswith("buyinv:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            payload, amount_rub, title = _plan_payload_and_amount(tier, months)
            desc = f"ÐÑÐ¾ÑÐ¼Ð»ÐµÐ½Ð¸Ðµ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ¸ {tier.upper()} Ð½Ð° {months} Ð¼ÐµÑ."
            ok = await _send_invoice_rub(title, desc, amount_rub, payload, update)
            if not ok:
                await q.answer("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð²ÑÑÑÐ°Ð²Ð¸ÑÑ ÑÑÑÑ", show_alert=True)
            return

        # ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° ÑÐ¿Ð¸ÑÐ°Ð½Ð¸ÐµÐ¼ Ð¸Ð· USD-Ð+/-Ð°Ð»Ð°Ð½ÑÐ°
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
                    f"ÐÐ° Ð+/-Ð°Ð»Ð°Ð½ÑÐµ Ð½ÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ÑÑÐµÐ´ÑÑÐ².\n"
                    f"Ð¢ÑÐµÐ+/-ÑÐµÑÑÑ ÐµÑÑ â ${need:.2f}.\n\n"
                    "ÐÐ¾Ð¿Ð¾Ð»Ð½Ð¸ÑÐµ Ð+/-Ð°Ð»Ð°Ð½Ñ ÑÐµÑÐµÐ· Ð¼ÐµÐ½Ñ Â«ð§¾ ÐÐ°Ð»Ð°Ð½ÑÂ».",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("â ÐÐ¾Ð¿Ð¾Ð»Ð½Ð¸ÑÑ Ð+/-Ð°Ð»Ð°Ð½Ñ", callback_data="topup")]]
                    ),
                )
                return
            # ÑÐ¿Ð¸ÑÑÐ²Ð°ÐµÐ¼ Ð¸ Ð°ÐºÑÐ¸Ð²Ð¸ÑÑÐµÐ¼
            _user_balance_debit(update.effective_user.id, usd_price)
            tier_name = payload.split(":", 1)[-1]
            activate_subscription_with_tier(update.effective_user.id, tier_name, months)
            await q.edit_message_text(
                f"â ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° {tier_name.upper()} Ð½Ð° {months} Ð¼ÐµÑ. Ð¾ÑÐ¾ÑÐ¼Ð»ÐµÐ½Ð°.\n"
                f"ÐÐ°Ð»Ð°Ð½Ñ: ${_user_balance_get(update.effective_user.id):.2f}"
            )
            return

        # ÐÐ°Ð»Ð°Ð½Ñ: Ð¿ÑÐ¾ÑÑÐ¾ Ð¾ÑÐºÑÑÑÑ Ð¼ÐµÐ½Ñ
        if data == "balance:open":
            await q.answer()
            await cmd_balance(update, context)
            return

        # ÐÑÑÐµÑ Ð½Ð° Ð´Ð¾Ð¿.ÑÐ°ÑÑÐ¾Ð´ (ÐºÐ¾Ð³Ð´Ð° Ð½Ðµ ÑÐ²Ð°ÑÐ¸Ð»Ð¾ Ð»Ð¸Ð¼Ð¸ÑÐ°)
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
                f"ÐÐ°Ñ Ð´Ð½ÐµÐ²Ð½Ð¾Ð¹ Ð»Ð¸Ð¼Ð¸Ñ Ð¿Ð¾ Â«{engine}Â» Ð¸ÑÑÐµÑÐ¿Ð°Ð½. Ð Ð°Ð·Ð¾Ð²Ð°Ñ Ð¿Ð¾ÐºÑÐ¿ÐºÐ° â {amount_rub} â½ "
                "Ð¸Ð»Ð¸ Ð¿Ð¾Ð¿Ð¾Ð»Ð½Ð¸ÑÐµ Ð+/-Ð°Ð»Ð°Ð½Ñ Ð² Â«ð§¾ ÐÐ°Ð»Ð°Ð½ÑÂ».",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("â Ð¢Ð°ÑÐ¸ÑÑ", web_app=WebAppInfo(url=TARIFF_URL))],
                        [InlineKeyboardButton("â ÐÐ¾Ð¿Ð¾Ð»Ð½Ð¸ÑÑ Ð+/-Ð°Ð»Ð°Ð½Ñ", callback_data="topup")],
                    ]
                ),
            )
            return

        # Ð ÐµÐ¶Ð¸Ð¼Ñ / ÐÐ²Ð¸Ð¶ÐºÐ¸
        if data == "mode:engines":
            await q.answer()
            await q.edit_message_text("ÐÐ²Ð¸Ð¶ÐºÐ¸:", reply_markup=engines_kb())
            return

        if data.startswith("mode:set:"):
            await q.answer()
            _, _, mode = data.split(":", 2)
            _mode_set(update.effective_user.id, mode)
            if mode == "none":
                await q.edit_message_text("Ð ÐµÐ¶Ð¸Ð¼ Ð²ÑÐºÐ»ÑÑÐµÐ½.")
            else:
                await q.edit_message_text(
                    f"Ð ÐµÐ¶Ð¸Ð¼ Â«{mode}Â» Ð²ÐºÐ»ÑÑÑÐ½. ÐÐ°Ð¿Ð¸ÑÐ¸ÑÐµ Ð·Ð°Ð´Ð°Ð½Ð¸Ðµ."
                )
            return

        # ÐÐ¾Ð´ÑÐ²ÐµÑÐ¶Ð´ÐµÐ½Ð¸Ðµ Ð²ÑÐ+/-Ð¾ÑÐ° Ð´Ð²Ð¸Ð¶ÐºÐ° Ð´Ð»Ñ Ð²Ð¸Ð´ÐµÐ¾ (Kling / Luma / Runway)
        if data.startswith("choose:"):
            await q.answer()
            _, engine, aid = data.split(":", 2)
            meta = _pending_actions.pop(aid, None)
            if not meta:
                await q.answer("ÐÐ°Ð´Ð°ÑÐ° ÑÑÑÐ°ÑÐµÐ»Ð°", show_alert=True)
                return

            prompt   = (meta.get("prompt") or "").strip()
            duration = normalize_seconds(int(meta.get("duration") or LUMA_DURATION_S))
            aspect   = normalize_aspect(str(meta.get("aspect") or "16:9"))

            uid = update.effective_user.id
            tier = get_subscription_tier(uid)

            # Runway Ð´Ð»Ñ text/voiceâvideo Ð¾ÑÐºÐ»ÑÑÑÐ½ (Ð¾ÑÑÐ°Ð²Ð»ÑÐµÐ¼ ÑÐ¾Ð»ÑÐºÐ¾ Kling/Luma/Sora)
            if engine == "runway":
                await q.message.reply_text("â ï¸ Runway Ð¾ÑÐºÐ»ÑÑÑÐ½ Ð´Ð»Ñ Ð²Ð¸Ð´ÐµÐ¾ Ð¿Ð¾ ÑÐµÐºÑÑÑ/Ð³Ð¾Ð»Ð¾ÑÑ. ÐÑÐ+/-ÐµÑÐ¸ÑÐµ Kling, Luma Ð¸Ð»Ð¸ Sora.")
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
                await q.answer("ÐÐµÐ¸Ð·Ð²ÐµÑÑÐ½ÑÐ¹ Ð´Ð²Ð¸Ð¶Ð¾Ðº", show_alert=True)
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

        # ÐÑÐ»Ð¸ Ð½Ðµ Ð¿Ð¾Ð´Ð¾ÑÐ»Ð° Ð½Ð¸ Ð¾Ð´Ð½Ð° Ð²ÐµÑÐºÐ°
        await q.answer("ÐÐµÐ¸Ð·Ð²ÐµÑÑÐ½Ð°Ñ ÐºÐ¾Ð¼Ð°Ð½Ð´Ð°", show_alert=True)

    except Exception as e:
        log.exception("on_cb error: %s", e)
    finally:
        with contextlib.suppress(Exception):
            await q.answer()



# âââââââââ STT âââââââââ
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


# âââââââââ ÐÐ¸Ð°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° Ð´Ð²Ð¸Ð¶ÐºÐ¾Ð² âââââââââ
async def cmd_diag_stt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = []
    lines.append("ð STT Ð´Ð¸Ð°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ°:")
    lines.append(f"â¢ OpenAI Whisper: {'â ÐºÐ»Ð¸ÐµÐ½Ñ Ð°ÐºÑÐ¸Ð²ÐµÐ½' if oai_stt else 'â Ð½ÐµÐ´Ð¾ÑÑÑÐ¿ÐµÐ½'}")
    lines.append(f"â¢ ÐÐ¾Ð´ÐµÐ»Ñ Whisper: {TRANSCRIBE_MODEL}")
    lines.append("â¢ ÐÐ¾Ð´Ð´ÐµÑÐ¶ÐºÐ° ÑÐ¾ÑÐ¼Ð°ÑÐ¾Ð²: ogg/oga, mp3, m4a/mp4, wav, webm")
    await update.effective_message.reply_text("\n".join(lines))

async def cmd_diag_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key_env  = os.environ.get("OPENAI_IMAGE_KEY", "").strip()
    key_used = key_env or OPENAI_API_KEY
    base     = IMAGES_BASE_URL
    lines = [
        "ð§ª Images (OpenAI) Ð´Ð¸Ð°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ°:",
        f"â¢ OPENAI_IMAGE_KEY: {'â Ð½Ð°Ð¹Ð´ÐµÐ½' if key_used else 'â Ð½ÐµÑ'}",
        f"â¢ BASE_URL: {base}",
        f"â¢ MODEL: {IMAGES_MODEL}",
    ]
    if "openrouter" in (base or "").lower():
        lines.append("â ï¸ BASE_URL ÑÐºÐ°Ð·ÑÐ²Ð°ÐµÑ Ð½Ð° OpenRouter â ÑÐ°Ð¼ Ð½ÐµÑ gpt-image-1.")
        lines.append("   Ð£ÐºÐ°Ð¶Ð¸ https://api.openai.com/v1 (Ð¸Ð»Ð¸ ÑÐ²Ð¾Ð¹ Ð¿ÑÐ¾ÐºÑÐ¸) Ð² OPENAI_IMAGE_BASE_URL.")
    await update.effective_message.reply_text("\n".join(lines))

async def cmd_diag_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    lines = [
        "ð¬ ÐÐ¸Ð´ÐµÐ¾-Ð´Ð²Ð¸Ð¶ÐºÐ¸:",
        # Luma
        f"â¢ Luma key: {'â' if bool(LUMA_API_KEY) else 'â'}  base={LUMA_BASE_URL}",
        f"  create={LUMA_CREATE_PATH}  status={LUMA_STATUS_PATH}",
        f"  model={LUMA_MODEL}  durations=['5s','9s','10s']  aspect=['16:9','9:16','1:1']",
        "",
        # Kling ÑÐµÑÐµÐ· CometAPI
        f"â¢ Kling key (COMETAPI_KEY): {'â' if bool(COMETAPI_KEY) else 'â'}  base={KLING_BASE_URL}",
        f"  model_name={KLING_MODEL_NAME}  mode={KLING_MODE}  aspect={KLING_ASPECT}  duration={KLING_DURATION_S}s",
        "",
        # Runway (ÑÐµÐºÑÑÐ¸Ð¹ DEV Ð¸Ð»Ð¸ Comet â Ð½ÐµÐ²Ð°Ð¶Ð½Ð¾, Ð¿ÑÐ¾ÑÑÐ¾ Ð¿Ð¾ÐºÐ°Ð·ÑÐ²Ð°ÐµÐ¼ ÐºÐ¾Ð½ÑÐ¸Ð³)
        f"â¢ Runway key: {'â' if bool(RUNWAY_API_KEY) else 'â'}  base={RUNWAY_BASE_URL}",
        f"  text2video={RUNWAY_TEXT2VIDEO_PATH}  image2video={RUNWAY_IMAGE2VIDEO_PATH}",
        f"  api_version={RUNWAY_API_VERSION}",
        "",
        f"â¢ ÐÐ¾Ð»Ð»Ð¸Ð½Ð³ ÐºÐ°Ð¶Ð´ÑÐµ {VIDEO_POLL_DELAY_S:.1f} c",
    ]

    await msg.reply_text("\n".join(lines))

# âââââââââ MIME Ð´Ð»Ñ Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ð¹ âââââââââ
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

# âââââââââ ÐÐ°ÑÑ Ð¾Ð¿ÑÐ¸Ð¹ Ð²Ð¸Ð´ÐµÐ¾ âââââââââ
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
    m = re.search(r"(\d+)\s*(?:ÑÐµÐº|Ñ)\b", tl)
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
    ÐÐ°Ð¿ÑÑÐº ÑÐµÐ½Ð´ÐµÑÐ° Ð²Ð¸Ð´ÐµÐ¾ Ð² Kling (ÑÐµÑÐµÐ· CometAPI) Ð¸ Ð¾ÑÐ¿ÑÐ°Ð²ÐºÐ° ÑÐµÐ·ÑÐ»ÑÑÐ°ÑÐ°
    Ð² Telegram ÑÐ¶Ðµ ÐºÐ°Ðº mp4-ÑÐ°Ð¹Ð»Ð°, Ð° Ð½Ðµ Ð¿ÑÐ¾ÑÑÐ¾ ÑÑÑÐ»ÐºÐ¾Ð¹.
    """
    msg = update.effective_message

    if not COMETAPI_KEY:
        await msg.reply_text("â ï¸ Kling ÑÐµÑÐµÐ· CometAPI Ð½Ðµ Ð½Ð°ÑÑÑÐ¾ÐµÐ½ (Ð½ÐµÑ COMETAPI_KEY).")
        return False

    # ÐÐ¾ÑÐ¼Ð°Ð»Ð¸Ð·ÑÐµÐ¼ Ð´Ð»Ð¸ÑÐµÐ»ÑÐ½Ð¾ÑÑÑ Ð¸ Ð°ÑÐ¿ÐµÐºÑ
    dur = str(max(1, min(duration, 10)))   # Kling Ð¶Ð´ÑÑ ÑÑÑÐ¾ÐºÑ "5" / "10"
    aspect_ratio = aspect.replace(" ", "") # "16:9", "9:16" Ð¸ Ñ.Ð¿.

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            create_url = f"{KLING_BASE_URL}/kling/v1/videos/text2video"

            headers = {
                "Authorization": f"Bearer {COMETAPI_KEY}",  # ÐºÐ»ÑÑ CometAPI
                "Content-Type": "application/json",
            }

            payload = {
                "prompt": prompt.strip(),
                "model_name": KLING_MODEL_NAME,   # Ð½Ð°Ð¿Ñ. "kling-v1-6"
                "mode": KLING_MODE,              # "std" Ð¸Ð»Ð¸ "pro"
                "duration": dur,                 # "5" Ð¸Ð»Ð¸ "10"
                "aspect_ratio": aspect_ratio,    # "16:9", "9:16", "1:1" ...
            }

            log.info("Kling create payload: %r", payload)
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code != 200:
                txt = (r.text or "")[:800]
                log.warning("Kling create error %s: %s", r.status_code, txt)
                await msg.reply_text(
                    f"â ï¸ Kling (textâvideo) Ð¾ÑÐºÐ»Ð¾Ð½Ð¸Ð» Ð·Ð°Ð´Ð°ÑÑ ({r.status_code}).\n"
                    f"ÐÑÐ²ÐµÑ ÑÐµÑÐ²ÐµÑÐ°:\n`{txt}`",
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
                    "â ï¸ Kling: Ð½Ðµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð¿Ð¾Ð»ÑÑÐ¸ÑÑ task_id Ð¸Ð· Ð¾ÑÐ²ÐµÑÐ°.\n"
                    f"Ð¡ÑÑÐ¾Ð¹ Ð¾ÑÐ²ÐµÑ ÑÐµÑÐ²ÐµÑÐ°: {js}"
                )
                return False

            await msg.reply_text("â³ Kling: Ð·Ð°Ð´Ð°ÑÐ° Ð¿ÑÐ¸Ð½ÑÑÐ°, Ð½Ð°ÑÐ¸Ð½Ð°Ñ ÑÐµÐ½Ð´ÐµÑ Ð²Ð¸Ð´ÐµÐ¾â¦")

            # ÐÑÐ»Ð¸Ð¼ ÑÑÐ°ÑÑÑ Ð¿Ð¾ GET /kling/v1/videos/text2video/{task_id}
            status_url = f"{KLING_BASE_URL}/kling/v1/videos/text2video/{task_id}"
            started = time.time()

            while True:
                if time.time() - started > 600:  # 10 Ð¼Ð¸Ð½ÑÑ
                    await msg.reply_text("â ï¸ Kling: Ð¿ÑÐµÐ²ÑÑÐµÐ½ Ð»Ð¸Ð¼Ð¸Ñ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ñ ÑÐµÐ½Ð´ÐµÑÐ° (>10 Ð¼Ð¸Ð½ÑÑ).")
                    return False

                sr = await client.get(status_url, headers=headers)
                if sr.status_code != 200:
                    txt = (sr.text or "")[:500]
                    log.warning("Kling status error %s: %s", sr.status_code, txt)
                    await msg.reply_text(
                        f"â ï¸ Kling status error ({sr.status_code}).\n"
                        f"ÐÑÐ²ÐµÑ ÑÐµÑÐ²ÐµÑÐ°:\n`{txt}`",
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
                    # ÐÐ°ÑÐ°ÐµÐ¼ Ð³Ð¾ÑÐ¾Ð²Ð¾Ðµ Ð²Ð¸Ð´ÐµÐ¾
                    vr = await client.get(video_url, timeout=300)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(
                            "â ï¸ Kling: Ð½Ðµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐºÐ°ÑÐ°ÑÑ Ð³Ð¾ÑÐ¾Ð²Ð¾Ðµ Ð²Ð¸Ð´ÐµÐ¾ "
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
                        f"â Kling Ð·Ð°Ð²ÐµÑÑÐ¸Ð»ÑÑ Ñ Ð¾ÑÐ¸Ð+/-ÐºÐ¾Ð¹: `{err}`",
                        parse_mode="Markdown",
                    )
                    return False

                # ÐÐ½Ð°ÑÐµ â Ð¶Ð´ÑÐ¼ Ð´Ð°Ð»ÑÑÐµ
                await asyncio.sleep(5.0)

    except Exception as e:
        log.exception("Kling text2video exception: %s", e)
        await msg.reply_text("â Kling: Ð²Ð½ÑÑÑÐµÐ½Ð½ÑÑ Ð¾ÑÐ¸Ð+/-ÐºÐ° Ð¿ÑÐ¸ ÑÐµÐ½Ð´ÐµÑÐµ Ð²Ð¸Ð´ÐµÐ¾.")
    return False
def _normalize_luma_aspect(aspect: str | None) -> str:
    """
    Luma Dream Machine Ð¿Ð¾Ð´Ð´ÐµÑÐ¶Ð¸Ð²Ð°ÐµÑ Ð¾Ð³ÑÐ°Ð½Ð¸ÑÐµÐ½Ð½ÑÐ¹ Ð½Ð°Ð+/-Ð¾Ñ Ð°ÑÐ¿ÐµÐºÑÐ¾Ð².
    ÐÑÐ¸Ð²Ð¾Ð´Ð¸Ð¼ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»ÑÑÐºÐ¸Ð¹ Ð°ÑÐ¿ÐµÐºÑ Ðº Ð´Ð¾Ð¿ÑÑÑÐ¸Ð¼Ð¾Ð¼Ñ Ð·Ð½Ð°ÑÐµÐ½Ð¸Ñ.
    """
    allowed = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"}
    if not aspect:
        a = (LUMA_ASPECT or "16:9").replace(" ", "")
    else:
        a = aspect.replace(" ", "")

    if a in allowed:
        return a

    # ÐÑÐ³ÐºÐ°Ñ ÐºÐ¾ÑÑÐµÐºÑÐ¸Ñ Â«Ð¿Ð¾ÑÐ¾Ð¶Ð¸ÑÂ» ÑÐ¾ÑÐ¼Ð°ÑÐ¾Ð²
    mapping = {
        "4:5": "3:4",
        "5:4": "4:3",
    }
    if a in mapping:
        return mapping[a]

    return "16:9"

# âââââââââ ÐÐ¾ÐºÑÐ¿ÐºÐ¸/Ð¸Ð½Ð²Ð¾Ð¹ÑÑ âââââââââ
def _plan_rub(tier: str, term: str) -> int:
    tier = (tier or "pro").lower()
    term = (term or "month").lower()
    return int(PLAN_PRICE_TABLE.get(tier, PLAN_PRICE_TABLE["pro"]).get(term, PLAN_PRICE_TABLE["pro"]["month"]))

def _plan_payload_and_amount(tier: str, months: int) -> tuple[str, int, str]:
    term = {1: "month", 3: "quarter", 12: "year"}.get(months, "month")
    amount = _plan_rub(tier, term)
    title = f"ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° {tier.upper()} ({term})"
    payload = f"sub:{tier}:{months}"
    return payload, amount, title

async def _send_invoice_rub(title: str, desc: str, amount_rub: int, payload: str, update: Update) -> bool:
    try:
        # Ð+/-ÐµÑÑÐ¼ ÑÐ¾ÐºÐµÐ½ Ð¸ Ð²Ð°Ð»ÑÑÑ Ð¸Ð· Ð´Ð²ÑÑ Ð¸ÑÑÐ¾ÑÐ½Ð¸ÐºÐ¾Ð² (ÑÑÐ°ÑÑÐ¹ PROVIDER_TOKEN ÐÐÐ Ð½Ð¾Ð²ÑÐ¹ YOOKASSA_PROVIDER_TOKEN)
        token = (PROVIDER_TOKEN or YOOKASSA_PROVIDER_TOKEN)
        curr  = (CURRENCY if (CURRENCY and CURRENCY != "RUB") else YOOKASSA_CURRENCY) or "RUB"

        if not token:
            await update.effective_message.reply_text("â ï¸ Ð®Kassa Ð½Ðµ Ð½Ð°ÑÑÑÐ¾ÐµÐ½Ð° (Ð½ÐµÑ ÑÐ¾ÐºÐµÐ½Ð°).")
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
            await update.effective_message.reply_text("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð²ÑÑÑÐ°Ð²Ð¸ÑÑ ÑÑÑÑ.")
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
            await update.effective_message.reply_text(f"â ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° {tier.upper()} Ð°ÐºÑÐ¸Ð²Ð¸ÑÐ¾Ð²Ð°Ð½Ð° Ð´Ð¾ {until.strftime('%Y-%m-%d')}.")
            return

        # ÐÑÐ+/-Ð¾Ðµ Ð¸Ð½Ð¾Ðµ payload â Ð¿Ð¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ðµ ÐµÐ´Ð¸Ð½Ð¾Ð³Ð¾ ÐºÐ¾ÑÐµÐ»ÑÐºÐ°
        usd = rub / max(1e-9, USD_RUB)
        _wallet_total_add(uid, usd)
        await update.effective_message.reply_text(f"ð³ ÐÐ¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ðµ: {rub:.0f} â½ â ${usd:.2f} Ð·Ð°ÑÐ¸ÑÐ»ÐµÐ½Ð¾ Ð½Ð° ÐµÐ´Ð¸Ð½ÑÐ¹ Ð+/-Ð°Ð»Ð°Ð½Ñ.")
    except Exception as e:
        log.exception("successful_payment handler error: %s", e)


# âââââââââ CryptoBot âââââââââ
CRYPTO_PAY_API_TOKEN = os.environ.get("CRYPTO_PAY_API_TOKEN", "").strip()
CRYPTO_BASE = "https://pay.crypt.bot/api"
TON_USD_RATE = float(os.environ.get("TON_USD_RATE", "5.0") or "5.0")  # Ð·Ð°Ð¿Ð°ÑÐ½Ð¾Ð¹ ÐºÑÑÑ

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
        for _ in range(120):  # ~12 Ð¼Ð¸Ð½ÑÑ Ð¿ÑÐ¸ 6Ñ Ð·Ð°Ð´ÐµÑÐ¶ÐºÐµ
            inv = await _crypto_get_invoice(invoice_id)
            st = (inv or {}).get("status", "").lower() if inv else ""
            if st == "paid":
                _wallet_total_add(user_id, float(usd_amount))
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                        text=f"â CryptoBot: Ð¿Ð»Ð°ÑÑÐ¶ Ð¿Ð¾Ð´ÑÐ²ÐµÑÐ¶Ð´ÑÐ½. ÐÐ°Ð»Ð°Ð½Ñ Ð¿Ð¾Ð¿Ð¾Ð»Ð½ÐµÐ½ Ð½Ð° ${float(usd_amount):.2f}.")
                return
            if st in ("expired", "cancelled", "canceled", "failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                        text=f"â CryptoBot: Ð¿Ð»Ð°ÑÑÐ¶ Ð½Ðµ Ð·Ð°Ð²ÐµÑÑÑÐ½ (ÑÑÐ°ÑÑÑ: {st}).")
                return
            await asyncio.sleep(6.0)
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                text="â CryptoBot: Ð²ÑÐµÐ¼Ñ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ñ Ð²ÑÑÐ»Ð¾. ÐÐ°Ð¶Ð¼Ð¸ÑÐµ Â«ÐÑÐ¾Ð²ÐµÑÐ¸ÑÑ Ð¾Ð¿Ð»Ð°ÑÑÂ» Ð¿Ð¾Ð·Ð¶Ðµ.")
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
        for _ in range(120):  # ~12 Ð¼Ð¸Ð½ÑÑ Ð¿ÑÐ¸ Ð·Ð°Ð´ÐµÑÐ¶ÐºÐµ 6Ñ
            inv = await _crypto_get_invoice(invoice_id)
            st = (inv or {}).get("status", "").lower() if inv else ""
            if st == "paid":
                until = activate_subscription_with_tier(user_id, tier, months)
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=f"â CryptoBot: Ð¿Ð»Ð°ÑÑÐ¶ Ð¿Ð¾Ð´ÑÐ²ÐµÑÐ¶Ð´ÑÐ½.\n"
                             f"ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° {tier.upper()} Ð°ÐºÑÐ¸Ð²Ð½Ð° Ð´Ð¾ {until.strftime('%Y-%m-%d')}."
                    )
                return
            if st in ("expired", "cancelled", "canceled", "failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=f"â CryptoBot: Ð¾Ð¿Ð»Ð°ÑÐ° Ð½Ðµ Ð·Ð°Ð²ÐµÑÑÐµÐ½Ð° (ÑÑÐ°ÑÑÑ: {st})."
                    )
                return
            await asyncio.sleep(6.0)

        # Ð¢Ð°Ð¹Ð¼Ð°ÑÑ
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="â CryptoBot: Ð²ÑÐµÐ¼Ñ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ñ Ð²ÑÑÐ»Ð¾. ÐÐ°Ð¶Ð¼Ð¸ÑÐµ Â«ÐÑÐ¾Ð²ÐµÑÐ¸ÑÑ Ð¾Ð¿Ð»Ð°ÑÑÂ» Ð¸Ð»Ð¸ Ð¾Ð¿Ð»Ð°ÑÐ¸ÑÐµ Ð·Ð°Ð½Ð¾Ð²Ð¾."
            )
    except Exception as e:
        log.exception("crypto poll (subscription) error: %s", e)


# âââââââââ ÐÑÐµÐ´Ð»Ð¾Ð¶ÐµÐ½Ð¸Ðµ Ð¿Ð¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ âââââââââ
async def _send_topup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("500 â½",  callback_data="topup:rub:500"),
         InlineKeyboardButton("1000 â½", callback_data="topup:rub:1000"),
         InlineKeyboardButton("2000 â½", callback_data="topup:rub:2000")],
        [InlineKeyboardButton("Crypto $5",  callback_data="topup:crypto:5"),
         InlineKeyboardButton("Crypto $10", callback_data="topup:crypto:10"),
         InlineKeyboardButton("Crypto $20", callback_data="topup:crypto:20")],
    ])
    await update.effective_message.reply_text("ÐÑÐ+/-ÐµÑÐ¸ÑÐµ ÑÑÐ¼Ð¼Ñ Ð¿Ð¾Ð¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ:", reply_markup=kb)


# âââââââââ ÐÐ¾Ð¿ÑÑÐºÐ° Ð¾Ð¿Ð»Ð°ÑÐ¸ÑÑ â Ð²ÑÐ¿Ð¾Ð»Ð½Ð¸ÑÑ âââââââââ
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
            "ÐÐ»Ñ Ð²ÑÐ¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ Ð½ÑÐ¶ÐµÐ½ ÑÐ°ÑÐ¸Ñ Ð¸Ð»Ð¸ ÐµÐ´Ð¸Ð½ÑÐ¹ Ð+/-Ð°Ð»Ð°Ð½Ñ.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("â Ð¢Ð°ÑÐ¸ÑÑ", web_app=WebAppInfo(url=TARIFF_URL))],
                 [InlineKeyboardButton("â ÐÐ¾Ð¿Ð¾Ð»Ð½Ð¸ÑÑ Ð+/-Ð°Ð»Ð°Ð½Ñ", callback_data="topup")]]
            )
        )
        return
    try:
        need_usd = float(offer.split(":", 1)[-1])
    except Exception:
        need_usd = est_cost_usd
    amount_rub = _calc_oneoff_price_rub(engine, need_usd)
    await update.effective_message.reply_text(
        f"ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ Ð»Ð¸Ð¼Ð¸ÑÐ°. Ð Ð°Ð·Ð¾Ð²Ð°Ñ Ð¿Ð¾ÐºÑÐ¿ÐºÐ° â {amount_rub} â½ Ð¸Ð»Ð¸ Ð¿Ð¾Ð¿Ð¾Ð»Ð½Ð¸ÑÐµ Ð+/-Ð°Ð»Ð°Ð½Ñ:",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("â Ð¢Ð°ÑÐ¸ÑÑ", web_app=WebAppInfo(url=TARIFF_URL))],
                [InlineKeyboardButton("â ÐÐ¾Ð¿Ð¾Ð»Ð½Ð¸ÑÑ Ð+/-Ð°Ð»Ð°Ð½Ñ", callback_data="topup")],
            ]
        ),
    )


# âââââââââ /plans âââââââââ
async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["â Ð¢Ð°ÑÐ¸ÑÑ:"]
    for tier, terms in PLAN_PRICE_TABLE.items():
        lines.append(f"â {tier.upper()}: "
                     f"{terms['month']}â½/Ð¼ÐµÑ â¢ {terms['quarter']}â½/ÐºÐ²Ð°ÑÑÐ°Ð» â¢ {terms['year']}â½/Ð³Ð¾Ð´")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("ÐÑÐ¿Ð¸ÑÑ START (1 Ð¼ÐµÑ)",    callback_data="buy:start:1"),
         InlineKeyboardButton("ÐÑÐ¿Ð¸ÑÑ PRO (1 Ð¼ÐµÑ)",      callback_data="buy:pro:1")],
        [InlineKeyboardButton("ÐÑÐ¿Ð¸ÑÑ ULTIMATE (1 Ð¼ÐµÑ)", callback_data="buy:ultimate:1")],
        [InlineKeyboardButton("ÐÑÐºÑÑÑÑ Ð¼Ð¸Ð½Ð¸-Ð²Ð¸ÑÑÐ¸Ð½Ñ",    web_app=WebAppInfo(url=TARIFF_URL))]
    ])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb)


# âââââââââ ÐÐ+/-ÑÑÑÐºÐ° Ð´Ð»Ñ Ð¿ÐµÑÐµÐ´Ð°ÑÐ¸ Ð¿ÑÐ¾Ð¸Ð·Ð²Ð¾Ð»ÑÐ½Ð¾Ð³Ð¾ ÑÐµÐºÑÑÐ° (Ð½Ð°Ð¿Ñ. Ð¸Ð· STT) âââââââââ
async def on_text_with_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
):
    """
    ÐÐ+/-ÑÑÑÐºÐ° Ð´Ð»Ñ Ð¿ÐµÑÐµÐ´Ð°ÑÐ¸ ÑÐµÐºÑÑÐ° (Ð½Ð°Ð¿ÑÐ¸Ð¼ÐµÑ, Ð¿Ð¾ÑÐ»Ðµ STT) Ð² on_text,
    Ð+/-ÐµÐ· Ð¿Ð¾Ð¿ÑÑÐ¾Ðº Ð¸Ð·Ð¼ÐµÐ½Ð¸ÑÑ update.message (read-only!).
    """
    text = (text or "").strip()
    if not text:
        await update.effective_message.reply_text("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ°ÑÐ¿Ð¾Ð·Ð½Ð°ÑÑ ÑÐµÐºÑÑ.")
        return

    await on_text(update, context, manual_text=text)


# âââââââââ Ð¢ÐµÐºÑÑÐ¾Ð²ÑÐ¹ Ð²ÑÐ¾Ð´ âââââââââ
async def on_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    manual_text: str | None = None,
):
    # ÐÑÐ»Ð¸ ÑÐµÐºÑÑ Ð¿ÐµÑÐµÐ´Ð°Ð½ Ð¸Ð·Ð²Ð½Ðµ â Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÐ¼ ÐµÐ³Ð¾
    # Ð¸Ð½Ð°ÑÐµ â Ð¾Ð+/-ÑÑÐ½ÑÐ¹ ÑÐµÐºÑÑ ÑÐ¾Ð¾Ð+/-ÑÐµÐ½Ð¸Ñ
    if manual_text is not None:
        text = manual_text.strip()
    else:
        text = (update.message.text or "").strip()

    # ÐÐ¾Ð¿ÑÐ¾ÑÑ Ð¾ Ð²Ð¾Ð·Ð¼Ð¾Ð¶Ð½Ð¾ÑÑÑÑ
    cap = capability_answer(text)
    if cap:
        await update.effective_message.reply_text(cap)
        return

    # ÐÐ°Ð¼ÑÐº Ð½Ð° Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ñ Ð²Ð¸Ð´ÐµÐ¾ÑÐ¾Ð»Ð¸ÐºÐ°
    mtype, rest = detect_media_intent(text)
    # ÐÑÐ¸Ð½ÑÐ´Ð¸ÑÐµÐ»ÑÐ½ÑÐ¹ Ð²ÑÐ+/-Ð¾Ñ Ð´Ð²Ð¸Ð¶ÐºÐ° (ÑÐµÑÐµÐ· Ð¼ÐµÐ½Ñ Â«ÐÐ²Ð¸Ð¶ÐºÐ¸Â»)
    user_id = update.effective_user.id
    forced_engine = "gpt"
    with contextlib.suppress(Exception):
        forced_engine = engine_get(user_id)

    # ÐÑÐ»Ð¸ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ Ð²ÑÐ+/-ÑÐ°Ð» Ð²Ð¸Ð´ÐµÐ¾-Ð´Ð²Ð¸Ð¶Ð¾Ðº, Ð° ÑÐ²Ð½Ð¾Ð³Ð¾ Ð¿ÑÐµÑÐ¸ÐºÑÐ° Ð½ÐµÑ â ÑÑÐ°ÐºÑÑÐµÐ¼ ÑÐµÐºÑÑ ÐºÐ°Ðº Ð²Ð¸Ð´ÐµÐ¾-Ð·Ð°Ð¿ÑÐ¾Ñ
    if (mtype is None) and forced_engine in ("kling", "luma", "runway", "sora"):
        prompt = text.strip()
        duration, aspect = parse_video_opts(text)

        # Runway textâvideo Ð¼Ð¾Ð¶ÐµÑ Ð+/-ÑÑÑ Ð²ÑÐºÐ»ÑÑÐµÐ½ (Ð¾ÑÑÐ°Ð²Ð»ÑÐµÐ¼ Ð·Ð°ÑÐ¸ÑÑ ÐºÐ°Ðº ÑÐ°Ð½ÑÑÐµ)
        if forced_engine == "runway" and RUNWAY_DISABLE_TEXTVIDEO:
            await update.effective_message.reply_text(_tr(user_id, "runway_disabled_textvideo"))
            return

        async def _go_video():
            if forced_engine == "kling":
                return await _run_kling_video(update, context, prompt, duration, aspect)
            if forced_engine == "luma":
                return await _run_luma_video(update, context, prompt, duration, aspect)
            if forced_engine == "runway":
                return await _run_runway_video(update, context, prompt, duration, aspect)
            if forced_engine == "sora":
                return await _run_sora_video(update, context, prompt, duration, aspect)
            return False

        # ÐÐ»Ð°ÑÑÐ¶/Ð»Ð¸Ð¼Ð¸ÑÑ â ÑÑÐ¸ÑÑÐ²Ð°ÐµÐ¼ ÐºÐ°Ðº Â«oneoffÂ» Ð²Ð¸Ð´ÐµÐ¾
        est = float(KLING_UNIT_COST_USD or 0.40) * duration
        if forced_engine == "luma":
            est = float(LUMA_UNIT_COST_USD or 0.40) * duration
        elif forced_engine == "runway":
            est = float(RUNWAY_UNIT_COST_USD or 1.00) * duration
        elif forced_engine == "sora":
            est = float(SORA_UNIT_COST_USD or 0.40) * duration

        await _try_pay_then_do(update, context, user_id, forced_engine, est, _go_video)
        return

    # ÐÑÐ»Ð¸ Ð²ÑÐ+/-ÑÐ°Ð½ Images, Ð° Ð¿ÑÐµÑÐ¸ÐºÑÐ° Ð½ÐµÑ â ÑÑÐ°ÐºÑÑÐµÐ¼ ÑÐµÐºÑÑ ÐºÐ°Ðº Ð¿ÑÐ¾Ð¼Ð¿Ñ Ð´Ð»Ñ ÐºÐ°ÑÑÐ¸Ð½ÐºÐ¸
    if (mtype is None) and forced_engine == "images":
        prompt = text.strip()
        if not prompt:
            await update.effective_message.reply_text("Ð¤Ð¾ÑÐ¼Ð°Ñ: /img <Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ðµ Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ñ>")
            return

        async def _go_img():
            await _do_img_generate(update, context, prompt)

        await _try_pay_then_do(update, context, user_id, "img", IMG_COST_USD, _go_img)
        return

    # ÐÑÐ»Ð¸ Ð²ÑÐ+/-ÑÐ°Ð½ Gemini â Ð¾Ð+/-ÑÐ°Ð+/-Ð°ÑÑÐ²Ð°ÐµÐ¼ Ð¾Ð+/-ÑÑÐ½ÑÐ¹ ÑÐµÐºÑÑ ÑÐµÑÐµÐ· Gemini (Comet) Ð²Ð¼ÐµÑÑÐ¾ OpenAI
    if (mtype is None) and forced_engine == "gemini":
        reply = await ask_gemini_text(text)
        await update.effective_message.reply_text(reply)
        await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])
        return

    # Suno / Midjourney Ð¿Ð¾ÐºÐ° ÐºÐ°Ðº Ð¿Ð¾Ð´ÑÐºÐ°Ð·ÐºÐ° (Ð+/-ÐµÐ· Ð¿ÑÑÐ¼Ð¾Ð³Ð¾ API Ð² ÑÑÐ¾Ð¼ ÑÐ°Ð¹Ð»Ðµ)
    if (mtype is None) and forced_engine in ("suno", "midjourney"):
        if forced_engine == "suno":
            await update.effective_message.reply_text(
                "ðµ Suno Ð²ÑÐ+/-ÑÐ°Ð½. ÐÐ°Ð¿Ð¸ÑÐ¸ÑÐµ: Â«Ð¿ÐµÑÐ½Ñ: Ð¶Ð°Ð½Ñ, Ð½Ð°ÑÑÑÐ¾ÐµÐ½Ð¸Ðµ, ÑÐµÐ¼Ð°, Ð´Ð»Ð¸ÑÐµÐ»ÑÐ½Ð¾ÑÑÑÂ» â Ð¸ Ñ Ð¿Ð¾Ð´Ð³Ð¾ÑÐ¾Ð²Ð»Ñ ÑÐµÐºÑÑ/ÑÑÑÑÐºÑÑÑÑ.\n"
                "ÐÑÐ»Ð¸ Ñ Ð²Ð°Ñ ÐµÑÑÑ API/Ð¿ÑÐ¾Ð²Ð°Ð¹Ð´ÐµÑ â Ð´Ð¾Ð+/-Ð°Ð²ÑÑÐµ ÐºÐ»ÑÑÐ¸, Ð¸ Ñ Ð¿Ð¾Ð´ÐºÐ»ÑÑÑ Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ñ."
            )
        else:
            await update.effective_message.reply_text(
                "ð¨ Midjourney Ð²ÑÐ+/-ÑÐ°Ð½. ÐÐ¿Ð¸ÑÐ¸ÑÐµ Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ðµ â Ñ Ð¿Ð¾Ð´Ð³Ð¾ÑÐ¾Ð²Ð»Ñ Ð¿ÑÐ¾Ð¼Ð¿Ñ. "
                "ÐÐ°Ð»ÑÑÐµ Ð²Ñ Ð¼Ð¾Ð¶ÐµÑÐµ Ð¾ÑÐ¿ÑÐ°Ð²Ð¸ÑÑ ÐµÐ³Ð¾ Ð² Midjourney/Discord."
            )
        return
    if mtype == "video":
        # ÐÐÐ ÐÐÐ¢ÐÐ ÐÐÐÐÐÐ Ð·Ð°Ð´Ð°ÑÐ¼ prompt Ð´Ð»Ñ ÑÐµÐºÑÑÐ° Ð¸ Ð´Ð»Ñ Ð³Ð¾Ð»Ð¾ÑÐ°
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
            f"ð Kling (~${est_kling:.2f})",
            callback_data=f"choose:kling:{aid}",
        )])
        rows.append([InlineKeyboardButton(
            f"ð¬ Luma (~${est_luma:.2f})",
            callback_data=f"choose:luma:{aid}",
        )])

        # Sora: show Pro label for pro/ultimate tiers
        if SORA_ENABLED:
            if tier in ("pro", "ultimate"):
                rows.append([InlineKeyboardButton("â¨ Sora 2 Pro", callback_data=f"choose:sora:{aid}")])
            else:
                rows.append([InlineKeyboardButton("â¨ Sora 2", callback_data=f"choose:sora:{aid}")])

        kb = InlineKeyboardMarkup(rows)

        await update.effective_message.reply_text(
            f"Ð§ÑÐ¾ Ð¸ÑÐ¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÑ?\n"
            f"ÐÐ»Ð¸ÑÐµÐ»ÑÐ½Ð¾ÑÑÑ: {duration} c â¢ ÐÑÐ¿ÐµÐºÑ: {aspect}\n"
            f"ÐÐ°Ð¿ÑÐ¾Ñ: Â«{prompt}Â»",
            reply_markup=kb,
        )
        return

    # ÐÐ°Ð¼ÑÐº Ð½Ð° ÐºÐ°ÑÑÐ¸Ð½ÐºÑ
    if mtype == "image":
        prompt = rest or re.sub(
            r"^(img|image|picture)\s*[:\-]\s*",
            "",
            text,
            flags=re.I,
        ).strip()

        if not prompt:
            await update.effective_message.reply_text(
                "Ð¤Ð¾ÑÐ¼Ð°Ñ: /img <Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ðµ Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ñ>"
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

    # ÐÐ+/-ÑÑÐ½ÑÐ¹ ÑÐµÐºÑÑ â GPT
    ok, _, _ = check_text_and_inc(
        update.effective_user.id,
        update.effective_user.username or "",
    )

    if not ok:
        await update.effective_message.reply_text(
            "ÐÐ¸Ð¼Ð¸Ñ ÑÐµÐºÑÑÐ¾Ð²ÑÑ Ð·Ð°Ð¿ÑÐ¾ÑÐ¾Ð² Ð½Ð° ÑÐµÐ³Ð¾Ð´Ð½Ñ Ð¸ÑÑÐµÑÐ¿Ð°Ð½. "
            "ÐÑÐ¾ÑÐ¼Ð¸ÑÐµ â Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÑ Ð¸Ð»Ð¸ Ð¿Ð¾Ð¿ÑÐ¾Ð+/-ÑÐ¹ÑÐµ Ð·Ð°Ð²ÑÑÐ°."
        )
        return

    user_id = update.effective_user.id

    # Ð ÐµÐ¶Ð¸Ð¼Ñ
    try:
        mode = _mode_get(user_id)
        track = _mode_track_get(user_id)
    except NameError:
        mode, track = "none", ""

    if mode and mode != "none":
        text_for_llm = f"[Ð ÐµÐ¶Ð¸Ð¼: {mode}; ÐÐ¾Ð´ÑÐµÐ¶Ð¸Ð¼: {track or '-'}]\n{text}"
    else:
        text_for_llm = text

    if mode == "Ð£ÑÑÐ+/-Ð°" and track:
        await study_process_text(update, context, text)
        return

    reply = await ask_openai_text(text_for_llm)
    await update.effective_message.reply_text(reply)
    await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])
    
# âââââââââ Ð¤Ð¾ÑÐ¾ / ÐÐ¾ÐºÑÐ¼ÐµÐ½ÑÑ / ÐÐ¾Ð»Ð¾Ñ âââââââââ
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.photo:
            return

        ph = update.message.photo[-1]
        f = await ph.get_file()
        data = await f.download_as_bytearray()
        img = bytes(data)

        # --- Ð¡Ð¢ÐÐ Ð«Ð ÐÐÐ¨ (ÐºÐ°Ðº ÑÐ°Ð½ÑÑÐµ) ---
        _cache_photo(update.effective_user.id, img)

        # --- ÐÐÐÐ«Ð ÐÐÐ¨ ÐÐÐ¯ ÐÐÐÐÐÐÐÐÐ¯ / LUMA / KLING ---
        # Ð¡Ð¾ÑÑÐ°Ð½ÑÐµÐ¼ Ð¸ bytes, Ð¸ Ð¿ÑÐ+/-Ð»Ð¸ÑÐ½ÑÐ¹ URL Telegram (Ð¿Ð¾Ð´ÑÐ¾Ð´Ð¸Ñ Ð´Ð»Ñ Luma/Comet)
        with contextlib.suppress(Exception):
            _LAST_ANIM_PHOTO[update.effective_user.id] = {
                "bytes": img,
                "url": (f.file_path or "").strip(),   # Ð¿ÑÐ+/-Ð»Ð¸ÑÐ½ÑÐ¹ HTTPS-URL Telegram API
            }

        caption = (update.message.caption or "").strip()
        if caption:
            tl = caption.lower()

            # ââ ÐÐÐÐÐÐÐÐÐ Ð¤ÐÐ¢Ð (ÑÐµÑÐµÐ· Ð²ÑÐ+/-Ð¾Ñ Ð´Ð²Ð¸Ð¶ÐºÐ°) ââ
            if any(k in tl for k in ("Ð¾Ð¶Ð¸Ð²Ð¸", "Ð¾Ð¶Ð¸Ð²Ð¸ÑÑ", "Ð°Ð½Ð¸Ð¼Ð¸ÑÑ", "Ð°Ð½Ð¸Ð¼Ð¸ÑÐ¾Ð²Ð°ÑÑ", "ÑÐ´ÐµÐ»Ð°Ð¹ Ð²Ð¸Ð´ÐµÐ¾", "revive", "animate")):
                dur, asp = parse_video_opts(caption)

                # Ð¾ÑÐ¸ÑÐ°ÐµÐ¼ prompt Ð¾Ñ ÑÑÐ¸Ð³Ð³ÐµÑ-ÑÐ»Ð¾Ð²
                prompt = re.sub(
                    r"\b(Ð¾Ð¶Ð¸Ð²Ð¸|Ð¾Ð¶Ð¸Ð²Ð¸ÑÑ|Ð°Ð½Ð¸Ð¼Ð¸ÑÑÐ¹|Ð°Ð½Ð¸Ð¼Ð¸ÑÐ¾Ð²Ð°ÑÑ|ÑÐ´ÐµÐ»Ð°Ð¹ Ð²Ð¸Ð´ÐµÐ¾|revive|animate)\b",
                    "",
                    caption,
                    flags=re.I
                ).strip(" ,.")

                # ÑÐ¾ÑÑÐ°Ð½ÑÐµÐ¼ Ð²ÑÐ¾Ð´Ð½ÑÐµ Ð¿Ð°ÑÐ°Ð¼ÐµÑÑÑ Ð² user_data (Ð+/-ÐµÐ· Ð³Ð»Ð¾Ð+/-Ð°Ð»ÑÐ½ÑÑ pending)
                context.user_data["revive_photo"] = {
                    "duration": int(dur),
                    "aspect": asp,
                    "prompt": prompt,
                }

                # Ð¿Ð¾ÐºÐ°Ð·ÑÐ²Ð°ÐµÐ¼ Ð²ÑÐ+/-Ð¾Ñ Ð´Ð²Ð¸Ð¶ÐºÐ°
                await update.effective_message.reply_text(
                    "ÐÑÐ+/-ÐµÑÐ¸ Ð´Ð²Ð¸Ð¶Ð¾Ðº Ð´Ð»Ñ Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ñ ÑÐ¾ÑÐ¾:",
                    reply_markup=revive_engine_kb()
                )
                return

            # ââ ÑÐ´Ð°Ð»Ð¸ÑÑ ÑÐ¾Ð½ ââ
            if any(k in tl for k in ("ÑÐ´Ð°Ð»Ð¸ ÑÐ¾Ð½", "removebg", "ÑÐ+/-ÑÐ°ÑÑ ÑÐ¾Ð½")):
                await _pedit_removebg(update, context, img)
                return

            # ââ Ð·Ð°Ð¼ÐµÐ½Ð¸ÑÑ ÑÐ¾Ð½ ââ
            if any(k in tl for k in ("Ð·Ð°Ð¼ÐµÐ½Ð¸ ÑÐ¾Ð½", "replacebg", "ÑÐ°Ð·Ð¼ÑÑÑÐ¹", "blur")):
                await _pedit_replacebg(update, context, img)
                return

            # ââ outpaint ââ
            if "outpaint" in tl or "ÑÐ°ÑÑÐ¸Ñ" in tl:
                await _pedit_outpaint(update, context, img)
                return

            # ââ ÑÐ°ÑÐºÐ°Ð´ÑÐ¾Ð²ÐºÐ° ââ
            if "ÑÐ°ÑÐºÐ°Ð´ÑÐ¾Ð²" in tl or "storyboard" in tl:
                await _pedit_storyboard(update, context, img)
                return

            # ââ ÐºÐ°ÑÑÐ¸Ð½ÐºÐ° Ð¿Ð¾ Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ñ (Luma / fallback OpenAI) ââ
            if (
                any(k in tl for k in ("ÐºÐ°ÑÑÐ¸Ð½", "Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½", "image", "img"))
                and any(k in tl for k in ("ÑÐ³ÐµÐ½ÐµÑÐ¸ÑÑ", "ÑÐ¾Ð·Ð´Ð°", "ÑÐ´ÐµÐ»Ð°Ð¹"))
            ):
                await _start_luma_img(update, context, caption)
                return

        # ÐµÑÐ»Ð¸ ÑÐ²Ð½Ð¾Ð¹ ÐºÐ¾Ð¼Ð°Ð½Ð´Ñ Ð½ÐµÑ â Ð+/-ÑÑÑÑÑÐµ ÐºÐ½Ð¾Ð¿ÐºÐ¸
        await update.effective_message.reply_text(
            "Ð¤Ð¾ÑÐ¾ Ð¿Ð¾Ð»ÑÑÐµÐ½Ð¾. Ð§ÑÐ¾ ÑÐ´ÐµÐ»Ð°ÑÑ?",
            reply_markup=photo_quick_actions_kb()
        )

    except Exception as e:
        log.exception("on_photo error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("ÐÐµ ÑÐ¼Ð¾Ð³ Ð¾Ð+/-ÑÐ°Ð+/-Ð¾ÑÐ°ÑÑ ÑÐ¾ÑÐ¾.")
            
async def on_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document:
            return

        doc = update.message.document
        mt = (doc.mime_type or "").lower()
        tg_file = await doc.get_file()
        data = await tg_file.download_as_bytearray()
        raw = bytes(data)

        # Ð´Ð¾ÐºÑÐ¼ÐµÐ½Ñ Ð¾ÐºÐ°Ð·Ð°Ð»ÑÑ Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸ÐµÐ¼
        if mt.startswith("image/"):
            _cache_photo(update.effective_user.id, raw)

            # --- ÐÐÐÐ«Ð ÐÐÐ¨ ÐÐÐ¯ ÐÐÐÐÐÐÐÐÐ¯ ---
            try:
                _LAST_ANIM_PHOTO[update.effective_user.id] = {
                    "bytes": raw,
                    "url": tg_file.file_path,    # Telegram public URL
                }
            except Exception:
                pass

            await update.effective_message.reply_text(
                "ÐÐ·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ðµ Ð¿Ð¾Ð»ÑÑÐµÐ½Ð¾ ÐºÐ°Ðº Ð´Ð¾ÐºÑÐ¼ÐµÐ½Ñ. Ð§ÑÐ¾ ÑÐ´ÐµÐ»Ð°ÑÑ?",
                reply_markup=photo_quick_actions_kb()
            )
            return

        # Ð¾ÑÑÐ°Ð»ÑÐ½ÑÐµ Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÑ â Ð¸Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ðµ ÑÐµÐºÑÑÐ°
        text, kind = extract_text_from_document(raw, doc.file_name or "file")
        if not (text or "").strip():
            await update.effective_message.reply_text(f"ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð¸Ð·Ð²Ð»ÐµÑÑ ÑÐµÐºÑÑ Ð¸Ð· {kind}.")
            return

        goal = (update.message.caption or "").strip() or None
        await update.effective_message.reply_text(f"ð ÐÐ·Ð²Ð»ÐµÐºÐ°Ñ ÑÐµÐºÑÑ ({kind}), Ð³Ð¾ÑÐ¾Ð²Ð»Ñ ÐºÐ¾Ð½ÑÐ¿ÐµÐºÑâ¦")

        summary = await summarize_long_text(text, query=goal)
        summary = summary or "ÐÐ¾ÑÐ¾Ð²Ð¾."
        await update.effective_message.reply_text(summary)

        await maybe_tts_reply(update, context, summary[:TTS_MAX_CHARS])

    except Exception as e:
        log.exception("on_doc error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("ÐÑÐ¸Ð+/-ÐºÐ° Ð¿ÑÐ¸ Ð¾Ð+/-ÑÐ°Ð+/-Ð¾ÑÐºÐµ Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÐ°.")
            
# âââââââââ Ð¥ÐµÐ»Ð¿ÐµÑÑ Ð´Ð»Ñ Ð°ÑÐ¿ÐµÐºÑÐ¾Ð² âââââââââ

def _runway_aspect_to_ratio(aspect_str: str | None) -> str:
    """
    ÐÐµÑÐµÐ²Ð¾Ð´Ð¸Ñ "16:9"/"9:16"/"1:1" Ð² Ð´Ð¾Ð¿ÑÑÑÐ¸Ð¼ÑÐµ ratio Runway:
    1280:720, 720:1280, 960:960, 1104:832, 832:1104, 1584:672, 1280:768, 768:1280.
    ÐÑÐ»Ð¸ Ð¿ÑÐ¸ÑÐ»Ð¾ ÑÐ¶Ðµ "1280:720" Ð¸ Ñ.Ð¿. â Ð²Ð¾Ð·Ð²ÑÐ°ÑÐ°ÐµÐ¼ ÐºÐ°Ðº ÐµÑÑÑ.
    """
    default_ratio = RUNWAY_RATIO or "1280:720"
    mapping = {
        "16:9": "1280:720",
        "9:16": "720:1280",
        "1:1": "960:960",
        "4:3": "1104:832",
        "3:4": "832:1104",
        # ÑÐ¸ÑÐ¾ÐºÐ¸Ðµ ÑÐ¾ÑÐ¼Ð°ÑÑ Ð¼Ð¾Ð¶Ð½Ð¾ Ð¿ÑÐ¸Ð²ÑÐ·Ð°ÑÑ Ðº ÑÐ°Ð¼ÑÐ¼ Ð+/-Ð»Ð¸Ð·ÐºÐ¸Ð¼
        "21:9": "1584:672",
        "9:21": "768:1280",
    }
    if not aspect_str:
        return default_ratio
    a = aspect_str.replace(" ", "")
    if a in mapping:
        return mapping[a]
    # ÐµÑÐ»Ð¸ ÑÐ¶Ðµ Ð¿Ð¾ÑÐ¾Ð¶Ðµ Ð½Ð° "1280:720"
    if re.match(r"^\d+:\d+$", a):
        return a
    return default_ratio


def _normalize_luma_aspect(aspect: str | None) -> str:
    """
    Luma Dream Machine Ð¿Ð¾Ð´Ð´ÐµÑÐ¶Ð¸Ð²Ð°ÐµÑ Ð¾Ð³ÑÐ°Ð½Ð¸ÑÐµÐ½Ð½ÑÐ¹ Ð½Ð°Ð+/-Ð¾Ñ Ð°ÑÐ¿ÐµÐºÑÐ¾Ð².
    ÐÑÐ¸Ð²Ð¾Ð´Ð¸Ð¼ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»ÑÑÐºÐ¸Ð¹ Ð°ÑÐ¿ÐµÐºÑ Ðº Ð´Ð¾Ð¿ÑÑÑÐ¸Ð¼Ð¾Ð¼Ñ Ð·Ð½Ð°ÑÐµÐ½Ð¸Ñ.
    """
    allowed = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"}
    if not aspect:
        a = (LUMA_ASPECT or "16:9").replace(" ", "")
    else:
        a = aspect.replace(" ", "")

    if a in allowed:
        return a

    # ÐÑÐ³ÐºÐ°Ñ ÐºÐ¾ÑÑÐµÐºÑÐ¸Ñ Â«Ð¿Ð¾ÑÐ¾Ð¶Ð¸ÑÂ» ÑÐ¾ÑÐ¼Ð°ÑÐ¾Ð²
    mapping = {
        "4:5": "3:4",
        "5:4": "4:3",
    }
    if a in mapping:
        return mapping[a]

    return "16:9"


# âââââââââ RUNWAY: IMAGE â VIDEO (CometAPI) âââââââââ

async def _run_runway_animate_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    image_url: str,
    prompt: str = "",
    duration_s: int = 5,
    aspect: str = "16:9",
):
    """
    Image -> Video ÑÐµÑÐµÐ· CometAPI (runwayml wrapper).
    ÐÐµÐ»Ð°ÐµÑ create -> poll status -> download mp4 -> send_video
    + ÑÐ²ÐµÐ´Ð¾Ð¼Ð»ÐµÐ½Ð¸Ðµ, ÐµÑÐ»Ð¸ ÑÑÐ¸ÑÐ°ÐµÑ > 3 Ð¼Ð¸Ð½ÑÑ.
    """
    chat_id = update.effective_chat.id
    msg = update.effective_message

    await context.bot.send_chat_action(chat_id, ChatAction.RECORD_VIDEO)

    # ÐÐµÑÑÐ¼ ÐºÐ»ÑÑ: Ð¿ÑÐ¸Ð¾ÑÐ¸ÑÐµÑ COMETAPI_KEY, Ð¸Ð½Ð°ÑÐµ RUNWAY_API_KEY
    api_key = (COMETAPI_KEY or RUNWAY_API_KEY or "").strip()
    if not api_key:
        await msg.reply_text("â ï¸ Runway/Comet: Ð½Ðµ Ð½Ð°ÑÑÑÐ¾ÐµÐ½ ÐºÐ»ÑÑ (COMETAPI_KEY Ð¸Ð»Ð¸ RUNWAY_API_KEY).")
        return

    # ÐÐ¾ÑÐ¼Ð°Ð»Ð¸Ð·ÑÐµÐ¼ duration
    try:
        duration_val = int(duration_s or RUNWAY_DURATION_S or 5)
    except Exception:
        duration_val = RUNWAY_DURATION_S or 5
    duration_val = max(3, min(20, duration_val))

    ratio = _runway_aspect_to_ratio(aspect)  # Ñ ÑÐµÐ+/-Ñ ÑÐ¶Ðµ ÐµÑÑÑ ÑÑÐ° ÑÑÐ½ÐºÑÐ¸Ñ/Ð¼Ð°Ð¿Ð¿Ð¸Ð½Ð³
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
                    "â ï¸ Runway/Comet imageâvideo Ð¾ÑÐºÐ»Ð¾Ð½Ð¸Ð» Ð·Ð°Ð´Ð°ÑÑ.\n"
                    f"ÐÐ¾Ð´: {r.status_code}\n"
                    f"ÐÑÐ²ÐµÑ:\n`{txt}`",
                    parse_mode="Markdown",
                )
                return

            try:
                js = r.json() or {}
            except Exception:
                js = {}

            # Comet: id Ð¼Ð¾Ð¶ÐµÑ Ð»ÐµÐ¶Ð°ÑÑ Ð³Ð»ÑÐ+/-Ð¾ÐºÐ¾
            task_id = None
            for d in _dicts_bfs(js):
                v = d.get("id") or d.get("task_id") or d.get("taskId")
                if isinstance(v, str) and v.strip():
                    task_id = v.strip()
                    break

            if not task_id:
                await msg.reply_text(
                    f"â ï¸ Runway/Comet: Ð½Ðµ Ð²ÐµÑÐ½ÑÐ» id Ð·Ð°Ð´Ð°ÑÐ¸.\n`{str(js)[:1200]}`",
                    parse_mode="Markdown",
                )
                return

            await msg.reply_text("â³ Runway: Ð°Ð½Ð¸Ð¼Ð¸ÑÑÑ ÑÐ¾ÑÐ¾â¦")

            status_url = f"{RUNWAY_BASE_URL}{status_tpl.format(id=task_id)}"
            started = time.time()
            notified_long_wait = False

            while True:
                rs = await client.get(status_url, headers=headers, timeout=60.0)

                if rs.status_code >= 400:
                    txt = (rs.text or "")[:1200]
                    log.warning("Runway/Comet status error %s: %s", rs.status_code, txt)
                    await msg.reply_text(
                        "â ï¸ Runway: Ð¾ÑÐ¸Ð+/-ÐºÐ° ÑÑÐ°ÑÑÑÐ°.\n"
                        f"ÐÐ¾Ð´: {rs.status_code}\n"
                        f"ÐÑÐ²ÐµÑ:\n`{txt}`",
                        parse_mode="Markdown",
                    )
                    return

                try:
                    sjs = rs.json() or {}
                except Exception:
                    sjs = {}

                status = _pick_status(sjs)

                # Ð£Ð²ÐµÐ´Ð¾Ð¼Ð»ÐµÐ½Ð¸Ðµ Ð¿ÑÐ¸ Ð´Ð¾Ð»Ð³Ð¾Ð¼ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ð¸ (1 ÑÐ°Ð·)
                elapsed = time.time() - started
                if elapsed > 180 and not notified_long_wait:
                    notified_long_wait = True
                    await msg.reply_text(
                        "â³ Runway ÑÑÐ¸ÑÐ°ÐµÑ Ð´Ð¾Ð»ÑÑÐµ Ð¾Ð+/-ÑÑÐ½Ð¾Ð³Ð¾.\n"
                        "Ð¯ Ð¿ÑÐ¸ÑÐ»Ñ Ð²Ð¸Ð´ÐµÐ¾ ÑÑÐ°Ð·Ñ, ÐºÐ°Ðº Ð¾Ð½Ð¾ Ð+/-ÑÐ´ÐµÑ Ð³Ð¾ÑÐ¾Ð²Ð¾."
                    )

                if status in ("succeeded", "success", "completed", "finished", "ready", "done"):
                    video_url = _pick_video_url(sjs)
                    if not video_url:
                        await msg.reply_text(
                            f"â ï¸ Runway: Ð·Ð°Ð´Ð°ÑÐ° Ð·Ð°Ð²ÐµÑÑÐ¸Ð»Ð°ÑÑ, Ð½Ð¾ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½ URL Ð²Ð¸Ð´ÐµÐ¾.\n`{str(sjs)[:1200]}`",
                            parse_mode="Markdown",
                        )
                        return

                    vr = await client.get(video_url, timeout=300.0)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(f"â ï¸ Runway: Ð½Ðµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐºÐ°ÑÐ°ÑÑ Ð²Ð¸Ð´ÐµÐ¾ ({vr.status_code}).")
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
                    await msg.reply_text(f"â Runway (imageâvideo) Ð¾ÑÐ¸Ð+/-ÐºÐ°: `{err}`", parse_mode="Markdown")
                    return

                if time.time() - started > RUNWAY_MAX_WAIT_S:
                    await msg.reply_text(
                        "â Runway ÑÑÐ¸ÑÐ°ÐµÑ ÑÐ»Ð¸ÑÐºÐ¾Ð¼ Ð´Ð¾Ð»Ð³Ð¾.\n"
                        "ÐÑÐ»Ð¸ Ð²Ð¸Ð´ÐµÐ¾ Ð+/-ÑÐ´ÐµÑ Ð³Ð¾ÑÐ¾Ð²Ð¾ Ð¿Ð¾Ð·Ð¶Ðµ â Ñ Ð¿ÑÐ¸ÑÐ»Ñ ÐµÐ³Ð¾ Ð°Ð²ÑÐ¾Ð¼Ð°ÑÐ¸ÑÐµÑÐºÐ¸."
                    )
                    # ÐÐÐÐÐ: ÑÐµÐ¹ÑÐ°Ñ Ð¼Ñ Ð¿ÑÐ¾ÑÑÐ¾ Ð²ÑÑÐ¾Ð´Ð¸Ð¼.
                    # ÐÑÐ»Ð¸ ÑÐ¾ÑÐµÑÑ ÑÐµÐ°Ð»ÑÐ½Ð¾ âÐ°Ð²ÑÐ¾Ð¼Ð°ÑÐ¸ÑÐµÑÐºÐ¸ Ð¿Ð¾Ð·Ð¶Ðµâ â Ð´Ð¾Ð+/-Ð°Ð²Ð»Ñ background-poller (ÑÐµÑÐµÐ· create_task)
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Runway image2video exception: %s", e)
        await msg.reply_text("â Runway: Ð¾ÑÐ¸Ð+/-ÐºÐ° Ð²ÑÐ¿Ð¾Ð»Ð½ÐµÐ½Ð¸Ñ imageâvideo.")

# ---------------- helpers -----------------def-_dicts_bfs(cts_bfs(root: object, max_depth6)int = """Ð¡Ð¾Ð+/-Ð¸ÑÐ°ÐµÐ¼ ÑÐ»Ð¾Ð²Ð°ÑÐ¸ Ð² ÑÐ¸ÑÐ¸Ð½Ñ, ÑÑÐ¾Ð+/-Ñ Ð½Ð°Ð¹ÑÐ¸ status/video_url Ð² Ð»ÑÐ+/-Ð¾Ð¼ Ð²Ð»Ð¾Ð¶ÐµÐ½Ð¸Ð¸."""ÐµÐ½Ð¸Ð¸.""" = []
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
    ÐÐ+/-ÑÐ¾Ð´ Ð²Ð»Ð¾Ð¶ÐµÐ½Ð½ÑÑ dict/list Ð² ÑÐ¸ÑÐ¸Ð½Ñ.
    ÐÐ¾Ð·Ð²ÑÐ°ÑÐ°ÐµÑ Ð²ÑÐµ dict, ÑÑÐ¾Ð+/-Ñ Ð»ÐµÐ³ÐºÐ¾ Ð½Ð°Ð¹ÑÐ¸ id/status/url Ð³Ð´Ðµ ÑÐ³Ð¾Ð´Ð½Ð¾ Ð² Ð¾ÑÐ²ÐµÑÐµ.
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
    ÐÐ¾ÑÑÐ°ÑÑ URL Ð²Ð¸Ð´ÐµÐ¾ Ð¸Ð· Ð»ÑÐ+/-ÑÑ ÑÐ¾ÑÐ¼ Ð¾ÑÐ²ÐµÑÐ¾Ð² (Comet/Runway/Luma/etc).
    Ð§Ð°ÑÑÐ¾ Comet: data -> data -> output: [ "https://...mp4" ]
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
        # Ð+/-ÑÑÑÑÑÐµ ÐºÐ»ÑÑÐ¸
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

        # ÑÐ¸Ð¿Ð¸ÑÐ½ÑÐµ ÐºÐ¾Ð½ÑÐµÐ¹Ð½ÐµÑÑ
        for k in ("data", "result", "response", "payload", "assets"):
            u = _pick_video_url(obj.get(k))
            if u:
                return u

        # Ð¾Ð+/-ÑÐ¸Ð¹ Ð¾Ð+/-ÑÐ¾Ð´
        for v in obj.values():
            u = _pick_video_url(v)
            if u:
                return u

    return None

# âââââââââ RUNWAY: TEXT â VIDEO âââââââââ
async def _run_runway_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    duration_s: int,
    aspect: str,
) -> bool:
    """
    Ð¢ÐµÐºÑÑ â Ð²Ð¸Ð´ÐµÐ¾ Ð² Runway (ÑÐµÑÐµÐ· CometAPI /runwayml/v1/text_to_video).
    """
    msg = update.effective_message
    chat_id = update.effective_chat.id

    api_key = (os.environ.get("COMETAPI_KEY") or COMETAPI_KEY or "").strip()
    if not api_key:
        api_key = (os.environ.get("RUNWAY_API_KEY") or RUNWAY_API_KEY or "").strip()

    if not api_key:
        await msg.reply_text("â ï¸ Runway: Ð½Ðµ Ð½Ð°ÑÑÑÐ¾ÐµÐ½ API-ÐºÐ»ÑÑ (COMETAPI_KEY / RUNWAY_API_KEY).")
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
                    "â ï¸ Runway (textâvideo) Ð¾ÑÐºÐ»Ð¾Ð½Ð¸Ð» Ð·Ð°Ð´Ð°ÑÑ "
                    f"({r.status_code}).\nÐÑÐ²ÐµÑ ÑÐµÑÐ²ÐµÑÐ°:\n`{txt}`",
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
                    "â ï¸ Runway (textâvideo) Ð½Ðµ Ð²ÐµÑÐ½ÑÐ» ID Ð·Ð°Ð´Ð°ÑÐ¸.\n"
                    f"ÐÑÐ²ÐµÑ ÑÐµÑÐ²ÐµÑÐ°:\n`{snippet}`",
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
                        "â ï¸ Runway (textâvideo) ÑÑÐ°ÑÑÑ-Ð·Ð°ÐºÐ°Ð· Ð²ÐµÑÐ½ÑÐ» Ð¾ÑÐ¸Ð+/-ÐºÑ.\n"
                        f"ÐÐ¾Ð´: {rs.status_code}\n"
                        f"ÐÑÐ²ÐµÑ:\n`{txt}`",
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
                            "â ï¸ Runway (textâvideo): Ð·Ð°Ð´Ð°ÑÐ° Ð·Ð°Ð²ÐµÑÑÐ¸Ð»Ð°ÑÑ, Ð½Ð¾ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½ URL Ð²Ð¸Ð´ÐµÐ¾.\n"
                            f"ÐÑÐ²ÐµÑ ÑÐµÑÐ²ÐµÑÐ°:\n`{snippet}`",
                            parse_mode="Markdown",
                        )
                        return False

                    vr = await client.get(video_url, timeout=300)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(
                            "â ï¸ Runway: Ð½Ðµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐºÐ°ÑÐ°ÑÑ Ð³Ð¾ÑÐ¾Ð²Ð¾Ðµ Ð²Ð¸Ð´ÐµÐ¾ "
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
                        f"â Runway (textâvideo) Ð·Ð°Ð²ÐµÑÑÐ¸Ð»Ð°ÑÑ Ñ Ð¾ÑÐ¸Ð+/-ÐºÐ¾Ð¹: `{err}`",
                        parse_mode="Markdown",
                    )
                    return False

                if time.time() - started > RUNWAY_MAX_WAIT_S:
                    await msg.reply_text("â Runway (textâvideo): Ð¿ÑÐµÐ²ÑÑÐµÐ½Ð¾ Ð²ÑÐµÐ¼Ñ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ñ.")
                    return False

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Runway text2video exception: %s", e)
        err = str(e)[:400]
        await msg.reply_text(
            "â Runway: Ð½Ðµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð·Ð°Ð¿ÑÑÑÐ¸ÑÑ/Ð¿Ð¾Ð»ÑÑÐ¸ÑÑ Ð²Ð¸Ð´ÐµÐ¾ (textâvideo).\n"
            f"Ð¢ÐµÐºÑÑ Ð¾ÑÐ¸Ð+/-ÐºÐ¸:\n`{err}`",
            parse_mode="Markdown",
        )


# âââââââââ KLING: IMAGE â VIDEO (Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ðµ ÑÐ¾ÑÐ¾) âââââââââ
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
    ÐÐ¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ðµ ÑÐ¾ÑÐ¾ ÑÐµÑÐµÐ· Kling image2video (CometAPI /kling/v1/videos/image2video).
    """
    msg = update.effective_message
    chat_id = update.effective_chat.id

    api_key = (os.environ.get("COMETAPI_KEY") or COMETAPI_KEY or "").strip()
    if not api_key:
        await msg.reply_text("â ï¸ Kling: Ð½Ðµ Ð½Ð°ÑÑÑÐ¾ÐµÐ½ COMETAPI_KEY.")
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
                    "â ï¸ Kling (imageâvideo) Ð¾ÑÐºÐ»Ð¾Ð½Ð¸Ð» Ð·Ð°Ð´Ð°ÑÑ "
                    f"({r.status_code}).\nÐÑÐ²ÐµÑ ÑÐµÑÐ²ÐµÑÐ°:\n`{txt}`",
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
                    "â ï¸ Kling (imageâvideo) Ð½Ðµ Ð²ÐµÑÐ½ÑÐ» ID Ð·Ð°Ð´Ð°ÑÐ¸.\n"
                    f"ÐÑÐ²ÐµÑ ÑÐµÑÐ²ÐµÑÐ°:\n`{snippet}`",
                    parse_mode="Markdown",
                )
                return

            await msg.reply_text("â³ Kling: Ð°Ð½Ð¸Ð¼Ð¸ÑÑÑ ÑÐ¾ÑÐ¾â¦")

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
                            "â ï¸ Kling (imageâvideo): Ð·Ð°Ð´Ð°ÑÐ° Ð·Ð°Ð²ÐµÑÑÐ¸Ð»Ð°ÑÑ, Ð½Ð¾ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½ URL Ð²Ð¸Ð´ÐµÐ¾.\n"
                            f"ÐÑÐ²ÐµÑ ÑÐµÑÐ²ÐµÑÐ°:\n`{snippet}`",
                            parse_mode="Markdown",
                        )
                        return

                    vr = await client.get(video_url, timeout=300)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(
                            "â ï¸ Kling: Ð½Ðµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐºÐ°ÑÐ°ÑÑ Ð³Ð¾ÑÐ¾Ð²Ð¾Ðµ Ð²Ð¸Ð´ÐµÐ¾ "
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
                        f"â Kling (imageâvideo) Ð·Ð°Ð²ÐµÑÑÐ¸Ð»Ð°ÑÑ Ñ Ð¾ÑÐ¸Ð+/-ÐºÐ¾Ð¹: `{err}`",
                        parse_mode="Markdown",
                    )
                    return

                if time.time() - started > KLING_MAX_WAIT_S:
                    await msg.reply_text("â Kling (imageâvideo): Ð¿ÑÐµÐ²ÑÑÐµÐ½Ð¾ Ð²ÑÐµÐ¼Ñ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ñ.")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Kling image2video exception: %s", e)
        await msg.reply_text(
            "â Kling: Ð½Ðµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð·Ð°Ð¿ÑÑÑÐ¸ÑÑ/Ð¿Ð¾Ð»ÑÑÐ¸ÑÑ Ð²Ð¸Ð´ÐµÐ¾ (imageâvideo)."
        )


# âââââââââ KLING: TEXT â VIDEO âââââââââ

async def _run_kling_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    duration: int,
    aspect: str,
):
    """
    Ð¢ÐµÐºÑÑ â Ð²Ð¸Ð´ÐµÐ¾ Ð² Kling (ÑÐµÑÐµÐ· CometAPI /kling/v1/videos/text2video).
    """
    msg = update.effective_message

    if not COMETAPI_KEY:
        await msg.reply_text("â ï¸ Kling ÑÐµÑÐµÐ· CometAPI Ð½Ðµ Ð½Ð°ÑÑÑÐ¾ÐµÐ½ (Ð½ÐµÑ COMETAPI_KEY).")
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
                    "â ï¸ Kling (textâvideo) Ð¾ÑÐºÐ»Ð¾Ð½Ð¸Ð» Ð·Ð°Ð´Ð°ÑÑ "
                    f"({r.status_code}).\nÐÑÐ²ÐµÑ ÑÐµÑÐ²ÐµÑÐ°:\n`{txt}`",
                    parse_mode="Markdown",
                )
                return

            data = js.get("data") or {}
            inner = data.get("data") or {}
            task_id = data.get("task_id") or inner.get("task_id") or js.get("task_id")

            if not task_id:
                await msg.reply_text(
                    "â ï¸ Kling: Ð½Ðµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð¿Ð¾Ð»ÑÑÐ¸ÑÑ task_id Ð¸Ð· Ð¾ÑÐ²ÐµÑÐ°.\n"
                    f"Ð¡ÑÑÐ¾Ð¹ Ð¾ÑÐ²ÐµÑ: `{js}`",
                    parse_mode="Markdown",
                )
                return

            await msg.reply_text("â³ Kling: Ð·Ð°Ð´Ð°ÑÐ° Ð¿ÑÐ¸Ð½ÑÑÐ°, Ð½Ð°ÑÐ¸Ð½Ð°Ñ ÑÐµÐ½Ð´ÐµÑ Ð²Ð¸Ð´ÐµÐ¾â¦")

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
                            "â ï¸ Kling: Ð·Ð°Ð´Ð°ÑÐ° Ð·Ð°Ð²ÐµÑÑÐ¸Ð»Ð°ÑÑ, Ð½Ð¾ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½ URL Ð²Ð¸Ð´ÐµÐ¾.\n"
                            f"Ð¡ÑÑÐ¾Ð¹ Ð¾ÑÐ²ÐµÑ: `{sjs}`",
                            parse_mode="Markdown",
                        )
                        return

                    vr = await client.get(video_url, timeout=300.0)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(
                            "â ï¸ Kling: Ð½Ðµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐºÐ°ÑÐ°ÑÑ Ð³Ð¾ÑÐ¾Ð²Ð¾Ðµ Ð²Ð¸Ð´ÐµÐ¾ "
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
                        f"â Kling (textâvideo) Ð·Ð°Ð²ÐµÑÑÐ¸Ð»ÑÑ Ñ Ð¾ÑÐ¸Ð+/-ÐºÐ¾Ð¹: `{err}`",
                        parse_mode="Markdown",
                    )
                    return

                if time.time() - started > KLING_MAX_WAIT_S:
                    await msg.reply_text("â Kling (textâvideo): Ð¿ÑÐµÐ²ÑÑÐµÐ½Ð¾ Ð²ÑÐµÐ¼Ñ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ñ.")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Kling text2video exception: %s", e)
        err = str(e)[:400]
        await msg.reply_text(
            "â Kling: Ð½Ðµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð·Ð°Ð¿ÑÑÑÐ¸ÑÑ/Ð¿Ð¾Ð»ÑÑÐ¸ÑÑ Ð²Ð¸Ð´ÐµÐ¾ (textâvideo).\n"
            f"Ð¢ÐµÐºÑÑ Ð¾ÑÐ¸Ð+/-ÐºÐ¸:\n`{err}`",
            parse_mode="Markdown",
        )


# âââââââââ LUMA: IMAGE â VIDEO (Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ðµ ÑÐ¾ÑÐ¾) âââââââââ

async def _run_luma_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    duration_s: int,
    aspect: str,
) -> bool:
    """
    Ð¢ÐµÐºÑÑ â Ð²Ð¸Ð´ÐµÐ¾ Ð² Luma Dream Machine (ray-2).
    """
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)

    if not LUMA_API_KEY:
        await update.effective_message.reply_text("â ï¸ Luma: Ð½Ðµ Ð½Ð°ÑÑÑÐ¾ÐµÐ½ LUMA_API_KEY.")
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
                    "â ï¸ Luma (textâvideo) Ð¾ÑÐºÐ»Ð¾Ð½Ð¸Ð»Ð° Ð·Ð°Ð´Ð°ÑÑ.\n"
                    f"ÐÐ¾Ð´: {r.status_code}\n"
                    f"ÐÑÐ²ÐµÑ:\n`{txt}`",
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
                    "â ï¸ Luma: Ð½Ðµ Ð²ÐµÑÐ½ÑÐ»Ð° id Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ð¸.\n"
                    f"ÐÑÐ²ÐµÑ ÑÐµÑÐ²ÐµÑÐ°:\n`{snippet}`",
                    parse_mode="Markdown",
                )
                return False

            # ÐÐÐÐÐ: status_url Ð´Ð¾Ð»Ð¶ÐµÐ½ Ð+/-ÑÑÑ Ð¡Ð¢Ð ÐÐÐÐ, Ð° Ð½Ðµ .format-Ð¼ÐµÑÐ¾Ð´Ð¾Ð¼
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
                        log.error("Luma: Ð¾ÑÐ²ÐµÑ Ð+/-ÐµÐ· ÑÑÑÐ»ÐºÐ¸ Ð½Ð° Ð²Ð¸Ð´ÐµÐ¾: %s", js)
                        await update.effective_message.reply_text("â Luma: Ð¾ÑÐ²ÐµÑ Ð¿ÑÐ¸ÑÑÐ» Ð+/-ÐµÐ· ÑÑÑÐ»ÐºÐ¸ Ð½Ð° Ð²Ð¸Ð´ÐµÐ¾.")
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
                        await update.effective_message.reply_text("â ï¸ Luma: Ð¾ÑÐ¸Ð+/-ÐºÐ° Ð¿ÑÐ¸ ÑÐºÐ°ÑÐ¸Ð²Ð°Ð½Ð¸Ð¸/Ð¾ÑÐ¿ÑÐ°Ð²ÐºÐµ Ð²Ð¸Ð´ÐµÐ¾.")
                    return True

                if st in ("failed", "error"):
                    if _is_luma_ip_error(js):
                        await update.effective_message.reply_text(
                            "â Luma Ð¾ÑÐºÐ»Ð¾Ð½Ð¸Ð»Ð° Ð·Ð°Ð¿ÑÐ¾Ñ Ð¸Ð·-Ð·Ð° IP (Ð·Ð°ÑÐ¸ÑÑÐ½Ð½ÑÐ¹ Ð¿ÐµÑÑÐ¾Ð½Ð°Ð¶/Ð+/-ÑÐµÐ½Ð´ Ð² ÑÐµÐºÑÑÐµ).\n"
                            "ÐÐµÑÐµÑÐ¾ÑÐ¼ÑÐ»Ð¸ÑÑÐ¹ Ð+/-ÐµÐ· Ð½Ð°Ð·Ð²Ð°Ð½Ð¸Ð¹ (Ð½Ð°Ð¿ÑÐ¸Ð¼ÐµÑ: Â«Ð¿Ð»ÑÑÐµÐ²ÑÐ¹ Ð¼ÐµÐ´Ð²ÐµÐ¶Ð¾Ð½Ð¾Ðºâ¦Â») Ð¸ Ð¿Ð¾Ð¿ÑÐ¾Ð+/-ÑÐ¹ ÐµÑÑ ÑÐ°Ð·."
                        )
                    else:
                        await update.effective_message.reply_text(
                            f"â Luma (textâvideo) Ð¾ÑÐ¸Ð+/-ÐºÐ°: {_short_luma_error(js)}"
                        )
                    return False

                if time.time() - started > LUMA_MAX_WAIT_S:
                    await update.effective_message.reply_text("â Luma (textâvideo): Ð¿ÑÐµÐ²ÑÑÐµÐ½Ð¾ Ð²ÑÐµÐ¼Ñ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ñ.")
                    return False

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Luma error: %s", e)
        await update.effective_message.reply_text("â Luma: Ð½Ðµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð·Ð°Ð¿ÑÑÑÐ¸ÑÑ/Ð¿Ð¾Ð»ÑÑÐ¸ÑÑ Ð²Ð¸Ð´ÐµÐ¾.")
                            
# âââââââââ LUMA: TEXT â VIDEO âââââââââ
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
        await msg.reply_text("â ï¸ Sora ÑÐµÐ¹ÑÐ°Ñ Ð½Ðµ Ð½Ð°ÑÑÑÐ¾ÐµÐ½Ð° (Ð½ÐµÑ ÐºÐ»ÑÑÐµÐ¹/URL).")
        return False

    # NOTE: This is an intentionally conservative placeholder.
    # Replace with your Comet aggregator endpoint when ready.
    await msg.reply_text("â ï¸ Sora Ð¸Ð½ÑÐµÐ³ÑÐ°ÑÐ¸Ñ Ð²ÐºÐ»ÑÑÐµÐ½Ð°, Ð½Ð¾ ÑÐ½Ð´Ð¿Ð¾Ð¸Ð½Ñ ÐµÑÑ Ð½Ðµ Ð·Ð°Ð´Ð°Ð½. ÐÐ¾Ð+/-Ð°Ð²Ñ Ð²ÑÐ·Ð¾Ð² Comet API.")
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
        fr = fr[:400].rstrip() + "â¦"
    return fr or "unknown error"


async def _run_luma_image2video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    image_url: str,
    prompt: str,
    aspect: str,
):
    """
    Luma: IMAGE â VIDEO (Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ðµ ÑÐ¾ÑÐ¾).
    ÐÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÑ /generations + keyframes (frame0=image).
    """
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)

    msg = update.effective_message
    chat_id = update.effective_chat.id

    if not LUMA_API_KEY:
        await msg.reply_text("â ï¸ Luma: Ð½Ðµ Ð½Ð°ÑÑÑÐ¾ÐµÐ½ LUMA_API_KEY.")
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
                    "â ï¸ Luma (imageâvideo) Ð¾ÑÐºÐ»Ð¾Ð½Ð¸Ð»Ð° Ð·Ð°Ð´Ð°ÑÑ.\n"
                    f"ÐÐ¾Ð´: {r.status_code}\n"
                    f"ÐÑÐ²ÐµÑ:\n`{txt}`",
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
                    "â ï¸ Luma: Ð½Ðµ Ð²ÐµÑÐ½ÑÐ»Ð° id Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ð¸.\n"
                    f"ÐÑÐ²ÐµÑ ÑÐµÑÐ²ÐµÑÐ°:\n`{snippet}`",
                    parse_mode="Markdown",
                )
                return

            await msg.reply_text("â³ Luma: Ð¾Ð¶Ð¸Ð²Ð»ÑÑ ÑÐ¾ÑÐ¾â¦")

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
                        await msg.reply_text("â Luma: Ð¾ÑÐ²ÐµÑ Ð¿ÑÐ¸ÑÑÐ» Ð+/-ÐµÐ· ÑÑÑÐ»ÐºÐ¸ Ð½Ð° Ð²Ð¸Ð´ÐµÐ¾.")
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
                        await msg.reply_text("â ï¸ Luma: Ð¾ÑÐ¸Ð+/-ÐºÐ° Ð¿ÑÐ¸ ÑÐºÐ°ÑÐ¸Ð²Ð°Ð½Ð¸Ð¸/Ð¾ÑÐ¿ÑÐ°Ð²ÐºÐµ Ð²Ð¸Ð´ÐµÐ¾.")
                    return

                if st in ("failed", "error"):
                    if _is_luma_ip_error(js):
                        await msg.reply_text(
                            "â Luma Ð¾ÑÐºÐ»Ð¾Ð½Ð¸Ð»Ð° Ð·Ð°Ð¿ÑÐ¾Ñ Ð¸Ð·-Ð·Ð° IP (Ð·Ð°ÑÐ¸ÑÑÐ½Ð½ÑÐ¹ Ð¿ÐµÑÑÐ¾Ð½Ð°Ð¶/Ð+/-ÑÐµÐ½Ð´ Ð² ÑÐµÐºÑÑÐµ).\n"
                            "ÐÐµÑÐµÑÐ¾ÑÐ¼ÑÐ»Ð¸ÑÑÐ¹ Ð+/-ÐµÐ· Ð½Ð°Ð·Ð²Ð°Ð½Ð¸Ð¹ (Ð½Ð°Ð¿ÑÐ¸Ð¼ÐµÑ: Â«Ð¿Ð»ÑÑÐµÐ²ÑÐ¹ Ð¼ÐµÐ´Ð²ÐµÐ¶Ð¾Ð½Ð¾Ðºâ¦Â») Ð¸ Ð¿Ð¾Ð¿ÑÐ¾Ð+/-ÑÐ¹ ÐµÑÑ ÑÐ°Ð·."
                        )
                    else:
                        await msg.reply_text(f"â Luma (imageâvideo) Ð¾ÑÐ¸Ð+/-ÐºÐ°: {_short_luma_error(js)}")
                    return

                if time.time() - started > LUMA_MAX_WAIT_S:
                    await msg.reply_text("â Luma (imageâvideo): Ð¿ÑÐµÐ²ÑÑÐµÐ½Ð¾ Ð²ÑÐµÐ¼Ñ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ñ.")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Luma image2video error: %s", e)
        await msg.reply_text("â Luma: Ð½Ðµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð·Ð°Ð¿ÑÑÑÐ¸ÑÑ/Ð¿Ð¾Ð»ÑÑÐ¸ÑÑ Ð²Ð¸Ð´ÐµÐ¾.")
            
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
            await update.effective_message.reply_text("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ°ÑÐ¿Ð¾Ð·Ð½Ð°ÑÑ ÑÐµÑÑ.")
            return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_voice error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("ÐÑÐ¸Ð+/-ÐºÐ° Ð¿ÑÐ¸ Ð¾Ð+/-ÑÐ°Ð+/-Ð¾ÑÐºÐµ voice.")

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
            await update.effective_message.reply_text("ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ°ÑÐ¿Ð¾Ð·Ð½Ð°ÑÑ ÑÐµÑÑ Ð¸Ð· Ð°ÑÐ´Ð¸Ð¾.")
            return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_audio error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("ÐÑÐ¸Ð+/-ÐºÐ° Ð¿ÑÐ¸ Ð¾Ð+/-ÑÐ°Ð+/-Ð¾ÑÐºÐµ Ð°ÑÐ´Ð¸Ð¾.")


# âââââââââ ÐÐ+/-ÑÐ°Ð+/-Ð¾ÑÑÐ¸Ðº Ð¾ÑÐ¸Ð+/-Ð¾Ðº PTB âââââââââ
async def on_error(update: object, context_: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error: %s", context_.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("Ð£Ð¿Ñ, Ð¿ÑÐ¾Ð¸Ð·Ð¾ÑÐ»Ð° Ð¾ÑÐ¸Ð+/-ÐºÐ°. Ð¯ ÑÐ¶Ðµ ÑÐ°Ð·Ð+/-Ð¸ÑÐ°ÑÑÑ.")
    except Exception:
        pass


# âââââââââ Ð Ð¾ÑÑÐµÑÑ Ð´Ð»Ñ ÑÐµÐºÑÑÐ¾Ð²ÑÑ ÐºÐ½Ð¾Ð¿Ð¾Ðº/ÑÐµÐ¶Ð¸Ð¼Ð¾Ð² âââââââââ
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
        "ð *Ð£ÑÑÐ+/-Ð°*\n"
        "ÐÐ¾Ð¼Ð¾Ð³Ñ: ÐºÐ¾Ð½ÑÐ¿ÐµÐºÑÑ Ð¸Ð· PDF/EPUB/DOCX/TXT, ÑÐ°Ð·Ð+/-Ð¾Ñ Ð·Ð°Ð´Ð°Ñ Ð¿Ð¾ÑÐ°Ð³Ð¾Ð²Ð¾, ÑÑÑÐµ/ÑÐµÑÐµÑÐ°ÑÑ, Ð¼Ð¸Ð½Ð¸-ÐºÐ²Ð¸Ð·Ñ.\n\n"
        "_ÐÑÑÑÑÑÐµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ñ:_\n"
        "â¢ Ð Ð°Ð·Ð¾Ð+/-ÑÐ°ÑÑ PDF â ÐºÐ¾Ð½ÑÐ¿ÐµÐºÑ\n"
        "â¢ Ð¡Ð¾ÐºÑÐ°ÑÐ¸ÑÑ Ð² ÑÐ¿Ð°ÑÐ³Ð°Ð»ÐºÑ\n"
        "â¢ ÐÐ+/-ÑÑÑÐ½Ð¸ÑÑ ÑÐµÐ¼Ñ Ñ Ð¿ÑÐ¸Ð¼ÐµÑÐ°Ð¼Ð¸\n"
        "â¢ ÐÐ»Ð°Ð½ Ð¾ÑÐ²ÐµÑÐ° / Ð¿ÑÐµÐ·ÐµÐ½ÑÐ°ÑÐ¸Ð¸"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown")

async def on_mode_work_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "ð¼ *Ð Ð°Ð+/-Ð¾ÑÐ°*\n"
        "ÐÐ¸ÑÑÐ¼Ð°/Ð+/-ÑÐ¸ÑÑ/ÑÐµÐ·ÑÐ¼Ðµ/Ð°Ð½Ð°Ð»Ð¸ÑÐ¸ÐºÐ°, ToDo/Ð¿Ð»Ð°Ð½Ñ, ÑÐ²Ð¾Ð´Ð½ÑÐµ ÑÐ°Ð+/-Ð»Ð¸ÑÑ Ð¸Ð· Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÐ¾Ð².\n"
        "ÐÐ»Ñ Ð°ÑÑÐ¸ÑÐµÐºÑÐ¾ÑÐ°/Ð´Ð¸Ð·Ð°Ð¹Ð½ÐµÑÐ°/Ð¿ÑÐ¾ÐµÐºÑÐ¸ÑÐ¾Ð²ÑÐ¸ÐºÐ° â ÑÑÑÑÐºÑÑÑÐ¸ÑÐ¾Ð²Ð°Ð½Ð¸Ðµ Ð¢Ð, ÑÐµÐº-Ð»Ð¸ÑÑÑ ÑÑÐ°Ð´Ð¸Ð¹, "
        "ÑÐ²Ð¾Ð´Ð½ÑÐµ ÑÐ°Ð+/-Ð»Ð¸ÑÑ Ð»Ð¸ÑÑÐ¾Ð², Ð¿Ð¾ÑÑÐ½Ð¸ÑÐµÐ»ÑÐ½ÑÐµ Ð·Ð°Ð¿Ð¸ÑÐºÐ¸.\n\n"
        "_ÐÐ¸Ð+/-ÑÐ¸Ð´Ñ:_ GPT-5 (ÑÐµÐºÑÑ/Ð»Ð¾Ð³Ð¸ÐºÐ°) + Images (Ð¸Ð»Ð»ÑÑÑÑÐ°ÑÐ¸Ð¸) + Luma/Runway (ÐºÐ»Ð¸Ð¿Ñ/Ð¼Ð¾ÐºÐ°Ð¿Ñ).\n\n"
        "_ÐÑÑÑÑÑÐµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ñ:_\n"
        "â¢ Ð¡ÑÐ¾ÑÐ¼Ð¸ÑÐ¾Ð²Ð°ÑÑ Ð+/-ÑÐ¸Ñ/Ð¢Ð\n"
        "â¢ Ð¡Ð²ÐµÑÑÐ¸ ÑÑÐµÐ+/-Ð¾Ð²Ð°Ð½Ð¸Ñ Ð² ÑÐ°Ð+/-Ð»Ð¸ÑÑ\n"
        "â¢ Ð¡Ð³ÐµÐ½ÐµÑÐ¸ÑÐ¾Ð²Ð°ÑÑ Ð¿Ð¸ÑÑÐ¼Ð¾/ÑÐµÐ·ÑÐ¼Ðµ\n"
        "â¢ Ð§ÐµÑÐ½Ð¾Ð²Ð¸Ðº Ð¿ÑÐµÐ·ÐµÐ½ÑÐ°ÑÐ¸Ð¸"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown")

async def on_mode_fun_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "ð¥ *Ð Ð°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ñ*\n"
        "Ð¤Ð¾ÑÐ¾-Ð¼Ð°ÑÑÐµÑÑÐºÐ°Ñ: ÑÐ´Ð°Ð»Ð¸ÑÑ/Ð·Ð°Ð¼ÐµÐ½Ð¸ÑÑ ÑÐ¾Ð½, Ð´Ð¾Ð+/-Ð°Ð²Ð¸ÑÑ/ÑÐ+/-ÑÐ°ÑÑ Ð¾Ð+/-ÑÐµÐºÑ/ÑÐµÐ»Ð¾Ð²ÐµÐºÐ°, outpaint, "
        "*Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ðµ ÑÑÐ°ÑÑÑ ÑÐ¾ÑÐ¾*.\n"
        "ÐÐ¸Ð´ÐµÐ¾: Luma/Runway â ÐºÐ»Ð¸Ð¿Ñ Ð¿Ð¾Ð´ Reels/Shorts; *Reels Ð¿Ð¾ ÑÐ¼ÑÑÐ»Ñ Ð¸Ð· ÑÐµÐ»ÑÐ½Ð¾Ð³Ð¾ Ð²Ð¸Ð´ÐµÐ¾* "
        "(ÑÐ¼Ð½Ð°Ñ Ð½Ð°ÑÐµÐ·ÐºÐ°), Ð°Ð²ÑÐ¾-ÑÐ°Ð¹Ð¼ÐºÐ¾Ð´Ñ. ÐÐµÐ¼Ñ/ÐºÐ²Ð¸Ð·Ñ.\n\n"
        "ÐÑÐ+/-ÐµÑÐ¸ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ðµ Ð½Ð¸Ð¶Ðµ:"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown", reply_markup=_fun_quick_kb())

# âââââ ÐÐ»Ð°Ð²Ð¸Ð°ÑÑÑÐ° Â«Ð Ð°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸ÑÂ» Ñ Ð½Ð¾Ð²ÑÐ¼Ð¸ ÐºÐ½Ð¾Ð¿ÐºÐ°Ð¼Ð¸ âââââ
def _fun_quick_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("ð ÐÐ´ÐµÐ¸ Ð´Ð»Ñ Ð´Ð¾ÑÑÐ³Ð°", callback_data="fun:ideas")],
        [InlineKeyboardButton("ð¬ Ð¡ÑÐµÐ½Ð°ÑÐ¸Ð¹ ÑÐ¾ÑÑÐ°", callback_data="fun:storyboard")],
        [InlineKeyboardButton("ð® ÐÐ³ÑÑ/ÐºÐ²Ð¸Ð·",       callback_data="fun:quiz")],
        # ÐÐ¾Ð²ÑÐµ ÐºÐ»ÑÑÐµÐ²ÑÐµ ÐºÐ½Ð¾Ð¿ÐºÐ¸
        [
            InlineKeyboardButton("ðª ÐÐ¶Ð¸Ð²Ð¸ÑÑ ÑÑÐ°ÑÐ¾Ðµ ÑÐ¾ÑÐ¾", callback_data="fun:revive"),
            InlineKeyboardButton("ð¬ Reels Ð¸Ð· Ð´Ð»Ð¸Ð½Ð½Ð¾Ð³Ð¾ Ð²Ð¸Ð´ÐµÐ¾", callback_data="fun:smartreels"),
        ],
        [
            InlineKeyboardButton("ð¥ Runway",      callback_data="fun:clip"),
            InlineKeyboardButton("ð¨ Midjourney",  callback_data="fun:img"),
            InlineKeyboardButton("ð STT/TTS",     callback_data="fun:speech"),
        ],
        [InlineKeyboardButton("ð Ð¡Ð²Ð¾Ð+/-Ð¾Ð´Ð½ÑÐ¹ Ð·Ð°Ð¿ÑÐ¾Ñ", callback_data="fun:free")],
        [InlineKeyboardButton("â¬ï¸ ÐÐ°Ð·Ð°Ð´", callback_data="fun:back")],
    ]
    return InlineKeyboardMarkup(rows)
    if SORA_ENABLED:
        rows.append([InlineKeyboardButton("â¨ Sora", callback_data="engine:sora")])


# âââââââââ ÐÐ¾ÑÐ¼Ð°Ð»Ð¸Ð·Ð°ÑÐ¸Ñ duration Ð´Ð»Ñ Runway/Comet (image_to_video) âââââââââ
def _normalize_runway_duration_for_comet(seconds: int | float | None) -> int:
    """
    Comet/Runway Ð¿ÑÐ¸Ð½Ð¸Ð¼Ð°ÐµÑ ÑÑÑÐ¾Ð³Ð¾ 5 Ð¸Ð»Ð¸ 10 ÑÐµÐºÑÐ½Ð´.
    Ð¢ÑÐµÐ+/-Ð¾Ð²Ð°Ð½Ð¸Ðµ: 7â9 ÑÐµÐºÑÐ½Ð´ => 10, Ð²ÑÑ Ð¾ÑÑÐ°Ð»ÑÐ½Ð¾Ðµ => 5.
    """
    try:
        d = int(round(float(seconds or 0)))
    except Exception:
        d = 0

    if d == 10 or (7 <= d <= 9):
        return 10
    return 5

# âââââââââ ÐÐ¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ðµ ÑÐ¾ÑÐ¾: ÑÐ½Ð¸Ð²ÐµÑÑÐ°Ð»ÑÐ½ÑÐ¹ Ð¿Ð°Ð¹Ð¿Ð»Ð°Ð¹Ð½ (Runway / Kling / Luma) âââââââââ

async def revive_old_photo_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    engine: str | None = None,
):
    """
    Ð£Ð½Ð¸Ð²ÐµÑÑÐ°Ð»ÑÐ½ÑÐ¹ Ð¿Ð°Ð¹Ð¿Ð»Ð°Ð¹Ð½ Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ñ ÑÐ¾ÑÐ¾.

    1) ÐÐµÑÑÐ¼ Ð¿Ð¾ÑÐ»ÐµÐ´Ð½ÐµÐµ ÑÐ¾ÑÐ¾ Ð¸Ð· _LAST_ANIM_PHOTO.
    2) ÐÑÐ»Ð¸ Ð´Ð²Ð¸Ð¶Ð¾Ðº Ð½Ðµ Ð²ÑÐ+/-ÑÐ°Ð½ â Ð¿Ð¾ÐºÐ°Ð·ÑÐ²Ð°ÐµÐ¼ Ð¼ÐµÐ½Ñ Ð²ÑÐ+/-Ð¾ÑÐ° (Runway/Kling/Luma).
    3) ÐÑÐ»Ð¸ Ð²ÑÐ+/-ÑÐ°Ð½ Ð´Ð²Ð¸Ð¶Ð¾Ðº â ÑÑÐ¸ÑÐ°ÐµÐ¼ ÑÐµÐ½Ñ Ð¸ Ð·Ð°Ð¿ÑÑÐºÐ°ÐµÐ¼ ÑÐ¾Ð¾ÑÐ²ÐµÑÑÑÐ²ÑÑÑÐ¸Ð¹ backend.
    """
    msg = update.effective_message
    user_id = update.effective_user.id

    photo_info = _LAST_ANIM_PHOTO.get(user_id) or {}
    img_bytes = photo_info.get("bytes")
    image_url = (photo_info.get("url") or "").strip()

    if not img_bytes:
        await msg.reply_text(
            "Ð¡Ð½Ð°ÑÐ°Ð»Ð° Ð¿ÑÐ¸ÑÐ»Ð¸ ÑÐ¾ÑÐ¾ (Ð¶ÐµÐ»Ð°ÑÐµÐ»ÑÐ½Ð¾ Ð¿Ð¾ÑÑÑÐµÑ), "
            "Ð° Ð¿Ð¾ÑÐ¾Ð¼ Ð½Ð°Ð¶Ð¼Ð¸ Â«ðª ÐÐ¶Ð¸Ð²Ð¸ÑÑ ÑÑÐ°ÑÐ¾Ðµ ÑÐ¾ÑÐ¾Â» Ð¸Ð»Ð¸ ÐºÐ½Ð¾Ð¿ÐºÑ Ð¿Ð¾Ð´ ÑÐ¾ÑÐ¾Ð³ÑÐ°ÑÐ¸ÐµÐ¹."
        )
        return True

    # Ð¿Ð°ÑÐ°Ð¼ÐµÑÑÑ (Ð¿ÑÐ¸ÑÐ»Ð¸ Ð¸Ð· on_photo ÑÐµÑÐµÐ· context.user_data["revive_photo"])
    rp = context.user_data.get("revive_photo") or {}
    dur = int(rp.get("duration") or RUNWAY_DURATION_S or 5)
    asp = (rp.get("aspect") or RUNWAY_RATIO or "720:1280")
    prompt = (rp.get("prompt") or "").strip()

    # ÑÐ°Ð³ 1: Ð²ÑÐ+/-Ð¾Ñ Ð´Ð²Ð¸Ð¶ÐºÐ°
    if not engine:
        await msg.reply_text("ÐÑÐ+/-ÐµÑÐ¸ Ð´Ð²Ð¸Ð¶Ð¾Ðº Ð´Ð»Ñ Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ñ ÑÐ¾ÑÐ¾:", reply_markup=revive_engine_kb())
        return True

    engine = engine.lower().strip()

    # --- Ð³Ð¾ÑÐ¾Ð²Ð¸Ð¼ ÑÑÐ½ÐºÑÐ¸Ð¸, ÐºÐ¾ÑÐ¾ÑÑÐµ Ð+/-ÑÐ´ÐµÐ¼ Ð¾ÑÐ´Ð°Ð²Ð°ÑÑ Ð² Ð+/-Ð¸Ð»Ð»Ð¸Ð½Ð³ ---
    async def _go_runway():
        # Runway/Comet ÑÑÐµÐ+/-ÑÐµÑ Ð¿ÑÐ+/-Ð»Ð¸ÑÐ½ÑÐ¹ URL ÐºÐ°ÑÑÐ¸Ð½ÐºÐ¸
        if not image_url or not image_url.startswith("http"):
            await msg.reply_text(
                "ÐÐ»Ñ Runway Ð½ÑÐ¶ÐµÐ½ Ð¿ÑÐ+/-Ð»Ð¸ÑÐ½ÑÐ¹ URL Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ñ (Telegram file_path). "
                "ÐÑÐ¸ÑÐ»Ð¸ ÑÐ¾ÑÐ¾ ÐµÑÑ ÑÐ°Ð·."
            )
            return
        await _run_runway_animate_photo(update, context, image_url, prompt, dur, asp)

    async def _go_kling():
        await _run_kling_animate_photo(update, context, img_bytes, prompt, dur, asp)

    async def _go_luma():
        if not image_url or not image_url.startswith("http"):
            await msg.reply_text(
                "ÐÐ»Ñ Luma Ð½ÑÐ¶ÐµÐ½ Ð¿ÑÐ+/-Ð»Ð¸ÑÐ½ÑÐ¹ URL Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ñ (Telegram file_path). "
                "ÐÑÐ¸ÑÐ»Ð¸ ÑÐ¾ÑÐ¾ ÐµÑÑ ÑÐ°Ð·."
            )
            return
        await _run_luma_image2video(update, context, image_url, prompt, asp)

    # ÑÑÐ¾Ð¸Ð¼Ð¾ÑÑÑ (ÑÐµÑÐ½Ð¾Ð²Ð°Ñ)
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

    await msg.reply_text("ÐÐµÐ¸Ð·Ð²ÐµÑÑÐ½ÑÐ¹ Ð´Ð²Ð¸Ð¶Ð¾Ðº Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ñ. ÐÐ¾Ð¿ÑÐ¾Ð+/-ÑÐ¹ ÐµÑÑ ÑÐ°Ð·.")
    return True


# âââââ ÐÐ+/-ÑÐ°Ð+/-Ð¾ÑÑÐ¸Ðº Ð+/-ÑÑÑÑÑÑ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ð¹ Â«Ð Ð°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸ÑÂ» (revive + Ð²ÑÐ+/-Ð¾Ñ Ð´Ð²Ð¸Ð¶ÐºÐ°) âââââ

async def on_cb_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()

    # action â ÑÐ°ÑÑÑ Ð¿Ð¾ÑÐ»Ðµ Ð¿ÐµÑÐ²Ð¾Ð³Ð¾ "fun:" Ð¸Ð»Ð¸ "something:"
    action = data.split(":", 1)[1] if ":" in data else ""

    async def _try_call(*fn_names, **kwargs):
        fn = _pick_first_defined(*fn_names)
        if callable(fn):
            return await fn(update, context, **kwargs)
        return None

    # ---------------------------------------------------------------------
    # ÐÐ½Ð¾Ð¿ÐºÐ° Ð¿Ð¾Ð´ ÑÐ¾ÑÐ¾ "â¨ Ð¾Ð¶Ð¸Ð²Ð¸ÑÑ ÑÐ¾ÑÐ¾" (pedit:revive)
    # ---------------------------------------------------------------------
    if data.startswith("pedit:revive"):
        with contextlib.suppress(Exception):
            await q.answer("ÐÐ¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ðµ ÑÐ¾ÑÐ¾")
        # Ð¿Ð¾ÐºÐ°Ð·ÑÐ²Ð°ÐµÐ¼ Ð²ÑÐ+/-Ð¾Ñ Ð´Ð²Ð¸Ð¶ÐºÐ°
        with contextlib.suppress(Exception):
            await q.edit_message_text("ÐÑÐ+/-ÐµÑÐ¸ Ð´Ð²Ð¸Ð¶Ð¾Ðº Ð´Ð»Ñ Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ñ ÑÐ¾ÑÐ¾:", reply_markup=revive_engine_kb())
        return

    # ---------------------------------------------------------------------
    # ÐÑÐ+/-Ð¾Ñ Ð´Ð²Ð¸Ð¶ÐºÐ° Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ñ: revive_engine:runway / kling / luma
    # ---------------------------------------------------------------------
    if data.startswith("revive_engine:"):
        with contextlib.suppress(Exception):
            await q.answer()
        engine = data.split(":", 1)[1].strip().lower() if ":" in data else ""

        # ÐÐ°Ð¶Ð½Ð¾: Ð·Ð°Ð¿ÑÑÐºÐ°ÐµÐ¼ Ð¿Ð°Ð¹Ð¿Ð»Ð°Ð¹Ð½ Ð¸ ÐÐ Ð¿ÑÑÐ°ÐµÐ¼ÑÑ edit-Ð¸ÑÑ ÑÑÐ°ÑÐ¾Ðµ ÑÐ¾Ð¾Ð+/-ÑÐµÐ½Ð¸Ðµ Ð´Ð°Ð»ÑÑÐµ
        await revive_old_photo_flow(update, context, engine=engine)
        return

    # ---------------------------------------------------------------------
    # ÐÐµÐ½Ñ "Ð Ð°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ñ" â Ð¾Ð¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ðµ
    # ---------------------------------------------------------------------
    if action == "revive":
        with contextlib.suppress(Exception):
            await q.answer("ÐÐ¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ðµ ÑÐ¾ÑÐ¾")
        await revive_old_photo_flow(update, context, engine=None)
        return

    # ---------------------------------------------------------------------
    # ÐÑÑÐ°Ð»ÑÐ½Ð¾Ðµ â ÐºÐ°Ðº Ñ ÑÐµÐ+/-Ñ Ð+/-ÑÐ»Ð¾ (Ð¾ÑÑÐ°Ð²Ð»ÑÑ ÑÑÑÑÐºÑÑÑÑ)
    # ---------------------------------------------------------------------
    if action == "smartreels":
        if await _try_call("smart_reels_from_video", "video_sense_reels"):
            return
        with contextlib.suppress(Exception):
            await q.answer("Reels Ð¸Ð· Ð´Ð»Ð¸Ð½Ð½Ð¾Ð³Ð¾ Ð²Ð¸Ð´ÐµÐ¾")
        await q.edit_message_text(
            "ð¬ *Reels Ð¸Ð· Ð´Ð»Ð¸Ð½Ð½Ð¾Ð³Ð¾ Ð²Ð¸Ð´ÐµÐ¾*\n"
            "ÐÑÐ¸ÑÐ»Ð¸ Ð´Ð»Ð¸Ð½Ð½Ð¾Ðµ Ð²Ð¸Ð´ÐµÐ¾ (Ð¸Ð»Ð¸ ÑÑÑÐ»ÐºÑ) + ÑÐµÐ¼Ñ/Ð¦Ð. "
            "Ð¡Ð´ÐµÐ»Ð°Ñ ÑÐ¼Ð½ÑÑ Ð½Ð°ÑÐµÐ·ÐºÑ (hook â value â CTA), ÑÑÐ+/-ÑÐ¸ÑÑÑ Ð¸ ÑÐ°Ð¹Ð¼ÐºÐ¾Ð´Ñ. "
            "Ð¡ÐºÐ°Ð¶Ð¸ ÑÐ¾ÑÐ¼Ð°Ñ: 9:16 Ð¸Ð»Ð¸ 1:1.",
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
            "ÐÐ°Ð¿ÑÑÑÐ¸ /diag_video ÑÑÐ¾Ð+/-Ñ Ð¿ÑÐ¾Ð²ÐµÑÐ¸ÑÑ ÐºÐ»ÑÑÐ¸ Luma/Runway.",
            reply_markup=_fun_quick_kb()
        )
        return

    if action == "img":
        if await _try_call("cmd_img", "midjourney_flow", "images_make"):
            return
        with contextlib.suppress(Exception):
            await q.answer()
        await q.edit_message_text(
            "ÐÐ²ÐµÐ´Ð¸ /img Ð¸ ÑÐµÐ¼Ñ ÐºÐ°ÑÑÐ¸Ð½ÐºÐ¸, Ð¸Ð»Ð¸ Ð¿ÑÐ¸ÑÐ»Ð¸ ÑÐµÑÑ.",
            reply_markup=_fun_quick_kb()
        )
        return

    if action == "storyboard":
        if await _try_call("start_storyboard", "storyboard_make"):
            return
        with contextlib.suppress(Exception):
            await q.answer()
        await q.edit_message_text(
            "ÐÐ°Ð¿Ð¸ÑÐ¸ ÑÐµÐ¼Ñ ÑÐ¾ÑÑÐ° â Ð½Ð°ÐºÐ¸Ð´Ð°Ñ ÑÑÑÑÐºÑÑÑÑ Ð¸ ÑÐ°ÑÐºÐ°Ð´ÑÐ¾Ð²ÐºÑ.",
            reply_markup=_fun_quick_kb()
        )
        return

    if action in {"ideas", "quiz", "speech", "free", "back"}:
        with contextlib.suppress(Exception):
            await q.answer()
        await q.edit_message_text(
            "ÐÐ¾ÑÐ¾Ð²! ÐÐ°Ð¿Ð¸ÑÐ¸ Ð·Ð°Ð´Ð°ÑÑ Ð¸Ð»Ð¸ Ð²ÑÐ+/-ÐµÑÐ¸ ÐºÐ½Ð¾Ð¿ÐºÑ Ð²ÑÑÐµ.",
            reply_markup=_fun_quick_kb()
        )
        return

    with contextlib.suppress(Exception):
        await q.answer()


# âââââââââ Ð Ð¾ÑÑÐµÑÑ-ÐºÐ½Ð¾Ð¿ÐºÐ¸ ÑÐµÐ¶Ð¸Ð¼Ð¾Ð² (ÐµÐ´Ð¸Ð½Ð°Ñ ÑÐ¾ÑÐºÐ° Ð²ÑÐ¾Ð´Ð°) âââââââââ
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

# âââââââââ ÐÐ¾Ð·Ð¸ÑÐ¸Ð²Ð½ÑÐ¹ Ð°Ð²ÑÐ¾-Ð¾ÑÐ²ÐµÑ Ð¿ÑÐ¾ Ð²Ð¾Ð·Ð¼Ð¾Ð¶Ð½Ð¾ÑÑÐ¸ (ÑÐµÐºÑÑ/Ð³Ð¾Ð»Ð¾Ñ) âââââââââ
_CAPS_PATTERN = (
    r"(?is)(ÑÐ¼ÐµÐµÑÑ|Ð¼Ð¾Ð¶ÐµÑÑ|Ð´ÐµÐ»Ð°ÐµÑÑ|Ð°Ð½Ð°Ð»Ð¸Ð·Ð¸ÑÑÐµÑÑ|ÑÐ°Ð+/-Ð¾ÑÐ°ÐµÑÑ|Ð¿Ð¾Ð´Ð´ÐµÑÐ¶Ð¸Ð²Ð°ÐµÑÑ|ÑÐ¼ÐµÐµÑ Ð»Ð¸|Ð¼Ð¾Ð¶ÐµÑ Ð»Ð¸)"
    r".{0,120}"
    r"(pdf|epub|fb2|docx|txt|ÐºÐ½Ð¸Ð³|ÐºÐ½Ð¸Ð³Ð°|Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½|ÑÐ¾ÑÐ¾|ÐºÐ°ÑÑÐ¸Ð½|image|jpeg|png|video|Ð²Ð¸Ð´ÐµÐ¾|mp4|mov|Ð°ÑÐ´Ð¸Ð¾|audio|mp3|wav)"
)

async def on_capabilities_qa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "ÐÐ°, ÑÐ¼ÐµÑ ÑÐ°Ð+/-Ð¾ÑÐ°ÑÑ Ñ ÑÐ°Ð¹Ð»Ð°Ð¼Ð¸ Ð¸ Ð¼ÐµÐ´Ð¸Ð°:\n"
        "â¢ ð ÐÐ¾ÐºÑÐ¼ÐµÐ½ÑÑ: PDF/EPUB/FB2/DOCX/TXT â ÐºÐ¾Ð½ÑÐ¿ÐµÐºÑ, ÑÐµÐ·ÑÐ¼Ðµ, Ð¸Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ðµ ÑÐ°Ð+/-Ð»Ð¸Ñ, Ð¿ÑÐ¾Ð²ÐµÑÐºÐ° ÑÐ°ÐºÑÐ¾Ð².\n"
        "â¢ ð¼ ÐÐ·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ñ: Ð°Ð½Ð°Ð»Ð¸Ð·/Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ðµ, ÑÐ»ÑÑÑÐµÐ½Ð¸Ðµ, ÑÐ¾Ð½, ÑÐ°Ð·Ð¼ÐµÑÐºÐ°, Ð¼ÐµÐ¼Ñ, outpaint.\n"
        "â¢ ð ÐÐ¸Ð´ÐµÐ¾: ÑÐ°Ð·Ð+/-Ð¾Ñ ÑÐ¼ÑÑÐ»Ð°, ÑÐ°Ð¹Ð¼ÐºÐ¾Ð´Ñ, *Reels Ð¸Ð· Ð´Ð»Ð¸Ð½Ð½Ð¾Ð³Ð¾ Ð²Ð¸Ð´ÐµÐ¾*, Ð¸Ð´ÐµÐ¸/ÑÐºÑÐ¸Ð¿Ñ, ÑÑÐ+/-ÑÐ¸ÑÑÑ.\n"
        "â¢ ð§ ÐÑÐ´Ð¸Ð¾/ÐºÐ½Ð¸Ð³Ð¸: ÑÑÐ°Ð½ÑÐºÑÐ¸Ð¿ÑÐ¸Ñ, ÑÐµÐ·Ð¸ÑÑ, Ð¿Ð»Ð°Ð½.\n\n"
        "_ÐÐ¾Ð´ÑÐºÐ°Ð·ÐºÐ¸:_ Ð¿ÑÐ¾ÑÑÐ¾ Ð·Ð°Ð³ÑÑÐ·Ð¸ÑÐµ ÑÐ°Ð¹Ð» Ð¸Ð»Ð¸ Ð¿ÑÐ¸ÑÐ»Ð¸ÑÐµ ÑÑÑÐ»ÐºÑ + ÐºÐ¾ÑÐ¾ÑÐºÐ¾Ðµ Ð¢Ð. "
        "ÐÐ»Ñ ÑÐ¾ÑÐ¾ â Ð¼Ð¾Ð¶Ð½Ð¾ Ð½Ð°Ð¶Ð°ÑÑ Â«ðª ÐÐ¶Ð¸Ð²Ð¸ÑÑ ÑÑÐ°ÑÐ¾Ðµ ÑÐ¾ÑÐ¾Â», Ð´Ð»Ñ Ð²Ð¸Ð´ÐµÐ¾ â Â«ð¬ Reels Ð¸Ð· Ð´Ð»Ð¸Ð½Ð½Ð¾Ð³Ð¾ Ð²Ð¸Ð´ÐµÐ¾Â»."
    )
    await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=_fun_quick_kb())

# âââââââââ ÐÑÐ¿Ð¾Ð¼Ð¾Ð³Ð°ÑÐµÐ»ÑÐ½Ð¾Ðµ: Ð²Ð·ÑÑÑ Ð¿ÐµÑÐ²ÑÑ Ð¾Ð+/-ÑÑÐ²Ð»ÐµÐ½Ð½ÑÑ ÑÑÐ½ÐºÑÐ¸Ñ Ð¿Ð¾ Ð¸Ð¼ÐµÐ½Ð¸ âââââââââ
def _pick_first_defined(*names):
    for n in names:
        fn = globals().get(n)
        if callable(fn):
            return fn
    return None


# âââââââââ Ð ÐµÐ³Ð¸ÑÑÑÐ°ÑÐ¸Ñ ÑÐµÐ½Ð´Ð»ÐµÑÐ¾Ð² Ð¸ Ð·Ð°Ð¿ÑÑÐº âââââââââ
def build_application() -> "Application":
    if not BOT_TOKEN:
        raise RuntimeError("ÐÐµ Ð·Ð°Ð´Ð°Ð½ BOT_TOKEN Ð² Ð¿ÐµÑÐµÐ¼ÐµÐ½Ð½ÑÑ Ð¾ÐºÑÑÐ¶ÐµÐ½Ð¸Ñ.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # âââââ ÐÐ¾Ð¼Ð°Ð½Ð´Ñ âââââ
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

    # âââââ ÐÐ»Ð°ÑÐµÐ¶Ð¸ âââââ
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    # >>> PATCH START â Handlers wiring (callbacks / media / text) >>>

    # âââââ WebApp âââââ
    with contextlib.suppress(Exception):
        app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))
    with contextlib.suppress(Exception):
        if hasattr(filters, "WEB_APP_DATA"):
            app.add_handler(MessageHandler(filters.WEB_APP_DATA, on_webapp_data))

    # âââââââââââââââââ CALLBACK QUERY HANDLERS âââââââââââââââââ
    # ÐÐÐÐÐ: Ð¿Ð¾ÑÑÐ´Ð¾Ðº = Ð¾Ñ ÑÐ·ÐºÐ¸Ñ Ðº ÑÐ¸ÑÐ¾ÐºÐ¸Ð¼

    # 1) ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ° / Ð¾Ð¿Ð»Ð°ÑÐ°
    app.add_handler(
        CallbackQueryHandler(
            on_cb_plans,
            pattern=r"^(?:plan:|pay:)$|^(?:plan:|pay:).+"
        )
    )

    # 2) Ð ÐµÐ¶Ð¸Ð¼Ñ / Ð¿Ð¾Ð´Ð¼ÐµÐ½Ñ
    app.add_handler(
        CallbackQueryHandler(
            on_mode_cb,
            pattern=r"^(?:mode:|act:|school:|work:)"
        )
    )

    # 3) Fun + Photo Edit + Revive (ÐÐ ÐÐ¢ÐÐ§ÐÐ¡ÐÐÐ ÐÐÐ¢Ð§)
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

    # 4) Catch-all (ÐÐ¡Ð ÐÐ¡Ð¢ÐÐÐ¬ÐÐÐ)
    app.add_handler(
        CallbackQueryHandler(on_cb),
        group=0
    )

    # âââââââââââââââââ MEDIA HANDLERS âââââââââââââââââ

    # ÐÐ¾Ð»Ð¾Ñ / Ð°ÑÐ´Ð¸Ð¾
    voice_fn = _pick_first_defined("handle_voice", "on_voice", "voice_handler")
    if voice_fn:
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_fn), group=1)

    # Ð¤Ð¾ÑÐ¾
    photo_fn = _pick_first_defined("handle_photo", "on_photo", "photo_handler", "handle_image_message")
    if photo_fn:
        app.add_handler(MessageHandler(filters.PHOTO, photo_fn), group=1)

    # ÐÐ¾ÐºÑÐ¼ÐµÐ½ÑÑ
    doc_fn = _pick_first_defined("handle_doc", "on_document", "handle_document", "doc_handler")
    if doc_fn:
        app.add_handler(MessageHandler(filters.Document.ALL, doc_fn), group=1)

    # ÐÐ¸Ð´ÐµÐ¾
    video_fn = _pick_first_defined("handle_video", "on_video", "video_handler")
    if video_fn:
        app.add_handler(MessageHandler(filters.VIDEO, video_fn), group=1)

    # GIF / animation
    gif_fn = _pick_first_defined("handle_gif", "on_gif", "animation_handler")
    if gif_fn:
        app.add_handler(MessageHandler(filters.ANIMATION, gif_fn), group=1)

    # âââââââââââââââââ TEXT BUTTONS âââââââââââââââââ
    import re

    BTN_ENGINES = re.compile(r"^\s*(?:ð§ \s*)?ÐÐ²Ð¸Ð¶ÐºÐ¸\s*$")
    BTN_BALANCE = re.compile(r"^\s*(?:ð³|ð§¾)?\s*ÐÐ°Ð»Ð°Ð½Ñ\s*$")
    BTN_PLANS   = re.compile(r"^\s*(?:â\s*)?ÐÐ¾Ð´Ð¿Ð¸ÑÐºÐ°(?:\s*[Â·â¢]\s*ÐÐ¾Ð¼Ð¾ÑÑ)?\s*$")
    BTN_STUDY   = re.compile(r"^\s*(?:ð\s*)?Ð£Ñ[ÐµÑ]Ð+/-Ð°\s*$")
    BTN_WORK    = re.compile(r"^\s*(?:ð¼\s*)?Ð Ð°Ð+/-Ð¾ÑÐ°\s*$")
    BTN_FUN     = re.compile(r"^\s*(?:ð¥\s*)?Ð Ð°Ð·Ð²Ð»ÐµÑÐµÐ½Ð¸Ñ\s*$")

    app.add_handler(MessageHandler(filters.Regex(BTN_ENGINES), on_btn_engines), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_BALANCE), on_btn_balance), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_PLANS),   on_btn_plans),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_STUDY),   on_btn_study),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_WORK),    on_btn_work),    group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_FUN),     on_btn_fun),     group=0)

    # âââââââââââââââââ CAPABILITIES Q/A âââââââââââââââââ
    app.add_handler(
        MessageHandler(filters.Regex(_CAPS_PATTERN), on_capabilities_qa),
        group=1
    )

    # âââââââââââââââââ FALLBACK TEXT âââââââââââââââââ
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

    # âââââââââââââââââ ERRORS âââââââââââââââââ
    err_fn = _pick_first_defined("on_error", "handle_error")
    if err_fn:
        app.add_error_handler(err_fn)

    return app


# âââââââââ main() âââââââââ
def main():
    with contextlib.suppress(Exception):
        db_init()
    with contextlib.suppress(Exception):
        db_init_usage()
    with contextlib.suppress(Exception):
        _db_init_prefs()

    app = build_application()

    if USE_WEBHOOK:
        log.info("ð WEBHOOK mode. Public URL: %s  Path: %s  Port: %s", PUBLIC_URL, WEBHOOK_PATH, PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH.lstrip("/"),
            webhook_url=f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}",
            secret_token=(WEBHOOK_SECRET or None),
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        log.info("ð POLLING mode.")
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


# ================== GPT5 PRO ADDITIONS â STEP 1 ==================
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
    "ru": "ð ÐÐ¾Ð+/-ÑÐ¾ Ð¿Ð¾Ð¶Ð°Ð»Ð¾Ð²Ð°ÑÑ Ð² GPTâ5 PRO Bot!\nÐÑÐ+/-ÐµÑÐ¸ÑÐµ Ð´Ð²Ð¸Ð¶Ð¾Ðº Ð¸Ð»Ð¸ Ð½Ð°Ð¿Ð¸ÑÐ¸ÑÐµ Ð·Ð°Ð¿ÑÐ¾Ñ.",
    "en": "ð Welcome to GPTâ5 PRO Bot!\nChoose an engine or type a prompt."
}

ENGINE_REGISTRY = {
    "gemini": {
        "title": "Gemini",
        "desc": "ÐÐ½Ð°Ð»Ð¸ÑÐ¸ÐºÐ°, ÐºÐ¾Ð´, ÑÐ»Ð¾Ð¶Ð½ÑÐµ ÑÐ°ÑÑÑÐ¶Ð´ÐµÐ½Ð¸Ñ"
    },
    "midjourney": {
        "title": "Midjourney",
        "desc": "ÐÐµÐ½ÐµÑÐ°ÑÐ¸Ñ Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ð¹ Ð¸ Ð´Ð¸Ð·Ð°Ð¹Ð½Ð°"
    },
    "suno": {
        "title": "Suno",
        "desc": "ÐÑÐ·ÑÐºÐ° Ð¸ Ð°ÑÐ´Ð¸Ð¾"
    }
}

# ================== END STEP 1 ==================


# ================== GPT5 PRO ADDITIONS â STEP 2 ==================
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


# ================== GPT5 PRO ADDITIONS â STEP 3 ==================
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


# ================== GPT5 PRO ADDITIONS â STEP 4 ==================
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


# ================== GPT5 PRO ADDITIONS â STEP 5 (FINAL) ==================
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
            "ð ÐÐ¾Ð+/-ÑÐ¾ Ð¿Ð¾Ð¶Ð°Ð»Ð¾Ð²Ð°ÑÑ Ð² GPT-5 PRO Bot!\n\n"
            "ð§  Gemini â Ð°Ð½Ð°Ð»Ð¸ÑÐ¸ÐºÐ°, ÐºÐ¾Ð´, ÑÐ»Ð¾Ð¶Ð½ÑÐµ ÑÐ°ÑÑÑÐ¶Ð´ÐµÐ½Ð¸Ñ\n"
            "ð¨ Midjourney â Ð¸Ð·Ð¾Ð+/-ÑÐ°Ð¶ÐµÐ½Ð¸Ñ Ð¸ Ð´Ð¸Ð·Ð°Ð¹Ð½\n"
            "ðµ Suno â Ð¼ÑÐ·ÑÐºÐ° Ð¸ Ð°ÑÐ´Ð¸Ð¾\n\n"
            "ÐÑÐ+/-ÐµÑÐ¸ÑÐµ Ð´Ð²Ð¸Ð¶Ð¾Ðº Ð¸Ð»Ð¸ Ð¿ÑÐ¾ÑÑÐ¾ Ð½Ð°Ð¿Ð¸ÑÐ¸ÑÐµ Ð·Ð°Ð¿ÑÐ¾Ñ."
        )
    return (
        "ð Welcome to GPT-5 PRO Bot!\n\n"
        "ð§  Gemini â analysis & reasoning\n"
        "ð¨ Midjourney â images & design\n"
        "ðµ Suno â music generation\n\n"
        "Choose an engine or type a prompt."
    )

# ================== END FINAL STEP ==================


# ================== ENV VARIABLES TO ADD / UPDATE ==================
# ÐÐ¾Ð+/-Ð°Ð²ÑÑÐµ/Ð¿ÑÐ¾Ð²ÐµÑÑÑÐµ ÑÑÐ¸ Ð¿ÐµÑÐµÐ¼ÐµÐ½Ð½ÑÐµ Ð² Environment (Render):
#
# --- Language ---
# (ÑÐ·ÑÐº ÑÑÐ°Ð½Ð¸ÑÑÑ Ð² SQLite kv_store Ð°Ð²ÑÐ¾Ð¼Ð°ÑÐ¸ÑÐµÑÐºÐ¸, Ð´Ð¾Ð¿. ENV Ð½Ðµ Ð½ÑÐ¶Ð½Ð¾)
#
# --- CometAPI shared key (ÐµÑÐ»Ð¸ Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐµÑÐµ ÑÐµÑÐµÐ· Comet) ---
# COMETAPI_KEY=...
#
# --- Kling (CometAPI) ---
# KLING_BASE_URL=https://api.cometapi.com
# KLING_MODEL_NAME=kling-v1-6
# KLING_MODE=std               # std|pro (ÐµÑÐ»Ð¸ Ð¿Ð¾Ð´Ð´ÐµÑÐ¶Ð¸Ð²Ð°ÐµÑÑÑ Ð²Ð°ÑÐ¸Ð¼ Ð°ÐºÐºÐ°ÑÐ½ÑÐ¾Ð¼)
# KLING_ASPECT=9:16
# KLING_DURATION_S=5
# KLING_UNIT_COST_USD=0.80     # Ð¾Ð¿ÑÐ¸Ð¾Ð½Ð°Ð»ÑÐ½Ð¾ Ð´Ð»Ñ ÑÐ°ÑÑÑÑÐ°/Ð¸Ð½Ð²Ð¾Ð¹ÑÐ¾Ð²
#
# --- Runway ---
# RUNWAY_API_KEY=...           # ÐµÑÐ»Ð¸ Ð¿ÑÑÑÐ¾ â Ð+/-ÑÐ´ÐµÑ Ð¸ÑÐ¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°Ð½ COMETAPI_KEY
# RUNWAY_MODEL=gen3a_turbo
# RUNWAY_API_VERSION=2024-11-06
# RUNWAY_DISABLE_TEXTVIDEO=1   # ÐµÑÐ»Ð¸ ÑÐ¾ÑÐ¸ÑÐµ Ð·Ð°Ð¿ÑÐµÑÐ¸ÑÑ ÑÐµÐºÑÑâÐ²Ð¸Ð´ÐµÐ¾ ÑÐµÑÐµÐ· Runway
#
# --- Luma ---
# LUMA_API_KEY=...
# LUMA_BASE_URL=https://api.lumalabs.ai/dream-machine/v1
# LUMA_MODEL=ray-2
# LUMA_ASPECT=16:9
# LUMA_DURATION_S=5
# LUMA_UNIT_COST_USD=0.40      # Ð¾Ð¿ÑÐ¸Ð¾Ð½Ð°Ð»ÑÐ½Ð¾
#
# --- Sora (ÑÐµÑÐµÐ· Comet / Ð²Ð°Ñ Ð¿ÑÐ¾ÐºÑÐ¸) ---
# SORA_ENABLED=0|1
# SORA_COMET_BASE_URL=https://api.cometapi.com
# SORA_COMET_API_KEY=...       # ÐµÑÐ»Ð¸ Ð¿ÑÑÑÐ¾ â Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÐ¹ÑÐµ COMETAPI_KEY
# SORA_MODEL_FREE=sora
# SORA_MODEL_PRO=sora
# SORA_UNIT_COST_USD=0.40
#
# --- Gemini (ÑÐµÑÐµÐ· Comet / Ð²Ð°Ñ Ð¿ÑÐ¾ÐºÑÐ¸) ---
# GEMINI_API_KEY=...           # ÐµÑÐ»Ð¸ Ð¿ÑÑÑÐ¾ â Ð+/-ÑÐ´ÐµÑ Ð¸ÑÐ¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°Ð½ COMETAPI_KEY
# GEMINI_BASE_URL=https://api.cometapi.com
# GEMINI_CHAT_PATH=/gemini/v1/chat   # ÐÐÐÐÐ: Ð¿ÑÑÑ Ð·Ð°Ð²Ð¸ÑÐ¸Ñ Ð¾Ñ Ð²Ð°ÑÐµÐ³Ð¾ Ð¿ÑÐ¾Ð²Ð°Ð¹Ð´ÐµÑÐ°/Comet. ÐÑÐ¿ÑÐ°Ð²ÑÑÐµ Ð¿ÑÐ¸ Ð½ÐµÐ¾Ð+/-ÑÐ¾Ð´Ð¸Ð¼Ð¾ÑÑÐ¸.
# GEMINI_MODEL=gemini-1.5-pro
#
# --- Optional placeholders (no direct API in this file yet) ---
# SUNO_API_KEY=...
# MIDJOURNEY_API_KEY=...
# ================================================================

def set_mode(context, mode):
    context.user_data["mode"] = mode

def get_mode(context):
    return context.user_data.get("mode", None)

def handle_study(update, context):
    set_mode(context, "study")

def handle_work(update, context):
    set_mode(context, "work")

def handle_fun(update, context):
    set_mode(context, "fun")

def handle_free_chat(update, context):
    set_mode(context, "free")
