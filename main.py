
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
# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ TTS imports Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
import contextlib  # ÃÃÂ¶ÃÂµ Ã ÃÃÂµÃÃ ÃÂ²ÃÃÃÂµ ÃÂµÃÃÃ, ÃÂ´ÃÃÃÂ»ÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÃ ÃÂ½ÃÂ°ÃÂ´ÃÂ¾, ÃÂµÃÃÂ»ÃÂ¸ ÃÂ¸ÃÂ¼ÃÂ¿ÃÂ¾ÃÃ ÃÃÃÂ¾ÃÂ¸Ã

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

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ LOGGING Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ENV Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

def _env_float(name: str, default: float) -> float:
    """
    ÃÃÂµÃÂ·ÃÂ¾ÃÂ¿ÃÂ°ÃÃÂ½ÃÂ¾ÃÂµ ÃÃÃÂµÃÂ½ÃÂ¸ÃÂµ float ÃÂ¸ÃÂ· ENV:
    - ÃÂ¿ÃÂ¾ÃÂ´ÃÂ´ÃÂµÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ°ÃÂµÃ ÃÂ¸ '4,99', ÃÂ¸ '4.99'
    - ÃÂ¿ÃÃÂ¸ ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂµ ÃÂ²ÃÂ¾ÃÂ·ÃÂ²ÃÃÂ°ÃÃÂ°ÃÂµÃ default
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
OPENAI_BASE_URL  = os.environ.get("OPENAI_BASE_URL", "").strip()  # OpenRouter ÃÂ¸ÃÂ»ÃÂ¸ ÃÃÂ²ÃÂ¾ÃÂ¹ ÃÂ¿ÃÃÂ¾ÃÂºÃÃÂ¸ ÃÂ´ÃÂ»Ã ÃÃÂµÃÂºÃÃÃÂ°
OPENAI_MODEL     = os.environ.get("OPENAI_MODEL", "openai/gpt-4o-mini").strip()

OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "").strip()

USE_WEBHOOK      = os.environ.get("USE_WEBHOOK", "1").lower() in ("1", "true", "yes", "on")
WEBHOOK_PATH     = os.environ.get("WEBHOOK_PATH", "/tg").strip()
WEBHOOK_SECRET   = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()

BANNER_URL       = os.environ.get("BANNER_URL", "").strip()
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "").strip()

# ÃÃÃÃÂ¸ÃÂ¹ ÃÂºÃÂ»ÃÃ CometAPI (ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÃÃ ÃÂ¸ ÃÂ´ÃÂ»Ã Kling, ÃÂ¸ ÃÂ´ÃÂ»Ã Runway)
COMETAPI_KEY     = os.environ.get("COMETAPI_KEY", "").strip()

# ÃÃÃÃÃ: ÃÂ¿ÃÃÂ¾ÃÂ²ÃÂ°ÃÂ¹ÃÂ´ÃÂµÃ ÃÃÂµÃÂºÃÃÃÂ° (openai / openrouter ÃÂ¸ Ã.ÃÂ¿.)
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

# Images (ÃÃÂ¾ÃÂ»ÃÃÃÂº Ã¢ OpenAI Images)
OPENAI_IMAGE_KEY    = os.environ.get("OPENAI_IMAGE_KEY", "").strip() or OPENAI_API_KEY
IMAGES_BASE_URL     = (os.environ.get("OPENAI_IMAGE_BASE_URL", "").strip() or "https://api.openai.com/v1")
IMAGES_MODEL        = "gpt-image-1"

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Runway / CometAPI (ÃÃÂ½ÃÂ¸ÃÃÂ¸ÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ½ÃÂ°Ã ÃÂºÃÂ¾ÃÂ½ÃÃÂ¸ÃÂ³ÃÃÃÂ°ÃÃÂ¸Ã) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

# API-ÃÂºÃÂ»ÃÃ:
# 1) ÃÃÃÂ»ÃÂ¸ RUNWAY_API_KEY ÃÃÂºÃÂ°ÃÂ·ÃÂ°ÃÂ½ Ã¢ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÂ¼ ÃÂ¿ÃÃÃÂ¼ÃÂ¾ÃÂ¹ Runway (ÃÃÂµÃÂºÃÂ¾ÃÂ¼ÃÂµÃÂ½ÃÂ´ÃÃÂµÃÃÃ ÃÂ´ÃÂ»Ã imageÃ¢video)
# 2) ÃÃÃÂ»ÃÂ¸ ÃÂ½ÃÂµÃ Ã¢ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÂ¼ CometAPI_KEY (ÃÃÂ¾ÃÂ²ÃÂ¼ÃÂµÃÃÃÂ¸ÃÂ¼ÃÂ¾ÃÃÃ Ã ÃÃÂ²ÃÂ¾ÃÂ¸ÃÂ¼ ÃÃÂµÃÂºÃÃÃÂ¸ÃÂ¼ ÃÂ¿ÃÃÂ¾ÃÂµÃÂºÃÃÂ¾ÃÂ¼)
RUNWAY_API_KEY = (os.environ.get("RUNWAY_API_KEY", "").strip() or COMETAPI_KEY)

# ÃÃÂ¾ÃÂ´ÃÂµÃÂ»Ã (ÃÂ¿ÃÂ¾ ÃÃÂ¼ÃÂ¾ÃÂ»ÃÃÂ°ÃÂ½ÃÂ¸Ã Gen-3a Turbo)
RUNWAY_MODEL = os.environ.get("RUNWAY_MODEL", "gen3a_turbo").strip()

# Ã ÃÂµÃÂºÃÂ¾ÃÂ¼ÃÂµÃÂ½ÃÂ´ÃÃÂµÃÂ¼ÃÃÂ¹ ratio Ã¢ ÃÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÂ² ÃÂ²ÃÂ¸ÃÂ´ÃÂµ "1280:720", "720:1280", "960:960"
RUNWAY_RATIO = os.environ.get("RUNWAY_RATIO", "1280:720").strip()

# ÃÃÂ»ÃÂ¸ÃÃÂµÃÂ»ÃÃÂ½ÃÂ¾ÃÃÃ video default
RUNWAY_DURATION_S = int((os.environ.get("RUNWAY_DURATION_S") or "5").strip() or "5")

# ÃÃÂ°ÃÂºÃÃÂ¸ÃÂ¼ÃÂ°ÃÂ»ÃÃÂ½ÃÂ¾ÃÂµ ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ´ÃÂ°ÃÂ½ÃÂ¸ÃÂµ ÃÃÂµÃÂ·ÃÃÂ»ÃÃÃÂ°ÃÃÂ° (ÃÃÂµÃÂº)
RUNWAY_MAX_WAIT_S = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "1200").strip() or "1200")

# ÃÃÂ°ÃÂ·ÃÂ° API:
# ÃÃÃÃÃ: Runway imageÃ¢video ÃÂºÃÂ¾ÃÃÃÂµÃÂºÃÃÂ½ÃÂ¾ ÃÃÂ°ÃÃÂ¾ÃÃÂ°ÃÂµÃ ÃÂ¢ÃÃÃÂ¬ÃÃ ÃÃÂµÃÃÂµÃÂ· ÃÂ¾ÃÃÂ¸ÃÃÂ¸ÃÂ°ÃÂ»ÃÃÂ½ÃÃ ÃÃÂ°ÃÂ·Ã:
#   https://api.runwayml.com
# CometAPI ÃÂ¾ÃÃÃÂ°ÃÃÃÃ ÃÂºÃÂ°ÃÂº fallback (ÃÃÂµÃÃÂµÃÂ· env), ÃÂ½ÃÂ¾ ÃÂ¿ÃÂ¾ ÃÃÂ¼ÃÂ¾ÃÂ»ÃÃÂ°ÃÂ½ÃÂ¸Ã ÃÃÃÂ°ÃÂ²ÃÂ¸ÃÂ¼ ÃÂ¾ÃÃÂ¸ÃÃÂ¸ÃÂ°ÃÂ»ÃÃÂ½ÃÃÂ¹ URL
RUNWAY_BASE_URL = (
    os.environ.get("RUNWAY_BASE_URL", "https://api.runwayml.com")
        .strip()
        .rstrip("/")
)

# ÃÂ­ÃÂ½ÃÂ´ÃÂ¿ÃÂ¾ÃÂ¸ÃÂ½ÃÃ Runway (ÃÂ¾ÃÃÂ¸ÃÃÂ¸ÃÂ°ÃÂ»ÃÃÂ½ÃÃÂµ ÃÂ¸ ÃÃÂ¾ÃÂ²ÃÂ¼ÃÂµÃÃÃÂ¸ÃÂ¼ÃÃÂµ)
RUNWAY_IMAGE2VIDEO_PATH = "/v1/image_to_video"      # ÃÂ½ÃÂ¾ÃÂ²ÃÃÂ¹ ÃÂºÃÂ¾ÃÃÃÂµÃÂºÃÃÂ½ÃÃÂ¹ endpoint Runway
RUNWAY_TEXT2VIDEO_PATH  = "/v1/text_to_video"       # ÃÃÂ½ÃÂ¸ÃÂ²ÃÂµÃÃÃÂ°ÃÂ»ÃÃÂ½ÃÃÂ¹ endpoint Runway
RUNWAY_STATUS_PATH      = "/v1/tasks/{id}"          # ÃÂµÃÂ´ÃÂ¸ÃÂ½ÃÃÂ¹ ÃÃÃÂ°ÃÃÃÃÂ½ÃÃÂ¹ endpoint Runway

# ÃÃÂµÃÃÃÂ¸Ã Runway API (ÃÂ¾ÃÃÃÂ·ÃÂ°ÃÃÂµÃÂ»ÃÃÂ½ÃÂ¾!)
RUNWAY_API_VERSION = os.environ.get("RUNWAY_API_VERSION", "2024-11-06").strip()

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Luma Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

LUMA_API_KEY     = os.environ.get("LUMA_API_KEY", "").strip()

# ÃÃÃÂµÃÂ³ÃÂ´ÃÂ° ÃÂ³ÃÂ°ÃÃÂ°ÃÂ½ÃÃÂ¸ÃÃÃÂµÃÂ¼ ÃÂ½ÃÂµÃÂ¿ÃÃÃÃÂ¾ÃÂ¹ model/aspect, ÃÂ´ÃÂ°ÃÂ¶ÃÂµ ÃÂµÃÃÂ»ÃÂ¸ ÃÂ² ENV ÃÂ¿ÃÃÃÃÂ°Ã ÃÃÃÃÂ¾ÃÂºÃÂ°
_LUMA_MODEL_ENV  = (os.environ.get("LUMA_MODEL") or "").strip()
LUMA_MODEL       = _LUMA_MODEL_ENV or "ray-2"

_LUMA_ASPECT_ENV = (os.environ.get("LUMA_ASPECT") or "").strip()
LUMA_ASPECT      = _LUMA_ASPECT_ENV or "16:9"

LUMA_DURATION_S  = int((os.environ.get("LUMA_DURATION_S") or "5").strip() or 5)

# ÃÃÂ°ÃÂ·ÃÂ° ÃÃÂ¶ÃÂµ ÃÃÂ¾ÃÂ´ÃÂµÃÃÂ¶ÃÂ¸Ã /dream-machine/v1 Ã¢ ÃÂ´ÃÂ°ÃÂ»ÃÃÃÂµ ÃÂ´ÃÂ¾ÃÃÂ°ÃÂ²ÃÂ»ÃÃÂµÃÂ¼ /generations
LUMA_BASE_URL    = (
    os.environ.get("LUMA_BASE_URL", "https://api.lumalabs.ai/dream-machine/v1")
    .strip()
    .rstrip("/")
)
LUMA_CREATE_PATH = "/generations"
LUMA_STATUS_PATH = "/generations/{id}"

# ÃÃÂ°ÃÂºÃÃÂ¸ÃÂ¼ÃÂ°ÃÂ»ÃÃÂ½ÃÃÂ¹ ÃÃÂ°ÃÂ¹ÃÂ¼ÃÂ°ÃÃ ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ´ÃÂ°ÃÂ½ÃÂ¸Ã Luma
LUMA_MAX_WAIT_S  = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)

# Luma Images (ÃÂ¾ÃÂ¿ÃÃÂ¸ÃÂ¾ÃÂ½ÃÂ°ÃÂ»ÃÃÂ½ÃÂ¾: ÃÂµÃÃÂ»ÃÂ¸ ÃÂ½ÃÂµÃ Ã¢ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÂ¼ OpenAI Images ÃÂºÃÂ°ÃÂº ÃÃÂ¾ÃÂ»ÃÃÃÂº)
LUMA_IMG_BASE_URL = os.environ.get("LUMA_IMG_BASE_URL", "").strip().rstrip("/")
LUMA_IMG_MODEL    = os.environ.get("LUMA_IMG_MODEL", "imagine-image-1").strip()

# ÃÂ¤ÃÂ¾ÃÂ»ÃÃÃÂºÃÂ¸ Luma
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

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Kling (ÃÂ½ÃÂ¾ÃÂ²ÃÃÂ¹ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº ÃÃÂµÃÃÂµÃÂ· CometAPI) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

KLING_BASE_URL   = os.environ.get("KLING_BASE_URL", "https://api.cometapi.com").strip().rstrip("/")
KLING_MODEL_NAME = os.environ.get("KLING_MODEL_NAME", "kling-v1-6").strip()
KLING_MODE       = os.environ.get("KLING_MODE", "std").strip()
KLING_ASPECT     = os.environ.get("KLING_ASPECT", "9:16").strip()
KLING_DURATION_S = int((os.environ.get("KLING_DURATION_S") or "5").strip() or 5)
KLING_MAX_WAIT_S = int((os.environ.get("KLING_MAX_WAIT_S") or "900").strip() or 900)
KLING_UNIT_COST_USD = float((os.environ.get("KLING_UNIT_COST_USD") or "0.80").replace(",", ".") or "0.80")

# ÃÃÃÃÂ¸ÃÂ¹ ÃÂ¸ÃÂ½ÃÃÂµÃÃÂ²ÃÂ°ÃÂ» ÃÂ¼ÃÂµÃÂ¶ÃÂ´Ã ÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃÂ°ÃÂ¼ÃÂ¸ ÃÃÃÂ°ÃÃÃÃÂ° ÃÂ·ÃÂ°ÃÂ´ÃÂ°Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾
VIDEO_POLL_DELAY_S = _env_float("VIDEO_POLL_DELAY_S", 6.0)

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ­ÃÂ¨Ã / ÃÃÃÃÃÃÃÂ¬ÃÃÃ ÃÂ¡ÃÃÂ¡ÃÂ¢ÃÃÂ¯ÃÃÃ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

# ÃÃÂ¾ÃÃÂ»ÃÂµÃÂ´ÃÂ½ÃÂµÃÂµ ÃÃÂ¾ÃÃÂ¾ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃÂµÃÂ»Ã ÃÂ´ÃÂ»Ã ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ°ÃÃÂ¸ÃÂ¸ (ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸Ã)
# user_id -> {"bytes": b"...", "url": "https://..."}
_LAST_ANIM_PHOTO: dict[int, dict] = {}
# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Runway ÃÃÂµÃÃÂµÃÂ· CometAPI Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

# ÃÃÂ»ÃÃ ÃÃÂµÃÃÃÂ¼ ÃÂ¸ÃÂ· RUNWAY_API_KEY, ÃÂ° ÃÂµÃÃÂ»ÃÂ¸ ÃÂ¾ÃÂ½ ÃÂ¿ÃÃÃÃÂ¾ÃÂ¹ Ã¢ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÂ¼ ÃÂ¾ÃÃÃÂ¸ÃÂ¹ COMETAPI_KEY
RUNWAY_API_KEY     = (os.environ.get("RUNWAY_API_KEY", "").strip() or COMETAPI_KEY)

# ÃÃÂ¾ÃÂ´ÃÂµÃÂ»Ã Runway, ÃÂºÃÂ¾ÃÃÂ¾ÃÃÂ°Ã ÃÂ¸ÃÂ´ÃÃ ÃÃÂµÃÃÂµÃÂ· CometAPI
RUNWAY_MODEL       = os.environ.get("RUNWAY_MODEL", "gen3a_turbo").strip()

# Ã ÃÂµÃÂºÃÂ¾ÃÂ¼ÃÂµÃÂ½ÃÂ´ÃÃÂµÃÂ¼ÃÃÂ¹ ÃÃÂ¾ÃÃÂ¼ÃÂ°Ã Ã¢ ÃÃÂ°ÃÂ·ÃÃÂµÃÃÂµÃÂ½ÃÂ¸ÃÂµ, ÃÂºÃÂ°ÃÂº ÃÂ² ÃÂ½ÃÂ¾ÃÂ²ÃÂ¾ÃÂ¹ ÃÂ²ÃÂµÃÃÃÂ¸ÃÂ¸ API (ÃÃÂ¼. docs Runway)
# ÃÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃ "1280:720", "720:1280", "960:960" ÃÂ¸ Ã.ÃÂ¿.
RUNWAY_RATIO       = os.environ.get("RUNWAY_RATIO", "1280:720").strip()

RUNWAY_DURATION_S  = int((os.environ.get("RUNWAY_DURATION_S") or "5").strip() or 5)
RUNWAY_MAX_WAIT_S  = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "900").strip() or 900)

# ÃÃÂ°ÃÂ·ÃÂ° ÃÂ¸ÃÂ¼ÃÂµÃÂ½ÃÂ½ÃÂ¾ CometAPI (ÃÂ° ÃÂ½ÃÂµ api.dev.runwayml.com)
RUNWAY_BASE_URL          = (os.environ.get("RUNWAY_BASE_URL", "https://api.cometapi.com").strip().rstrip("/"))

# ÃÂ­ÃÂ½ÃÂ´ÃÂ¿ÃÂ¾ÃÂ¸ÃÂ½ÃÃ Runway ÃÃÂµÃÃÂµÃÂ· CometAPI
RUNWAY_IMAGE2VIDEO_PATH  = "/runwayml/v1/image_to_video"
RUNWAY_TEXT2VIDEO_PATH   = "/runwayml/v1/text_to_video"
RUNWAY_STATUS_PATH       = "/runwayml/v1/tasks/{id}"

# ÃÃÂµÃÃÃÂ¸Ã Runway API Ã¢ ÃÂ¾ÃÃÃÂ·ÃÂ°ÃÃÂµÃÂ»ÃÃÂ½ÃÂ¾ 2024-11-06 (ÃÂºÃÂ°ÃÂº ÃÂ² ÃÂ¸Ã ÃÂ´ÃÂ¾ÃÂºÃÂµ)
RUNWAY_API_VERSION = os.environ.get("RUNWAY_API_VERSION", "2024-11-06").strip()

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Luma Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

LUMA_API_KEY     = os.environ.get("LUMA_API_KEY", "").strip()

# ÃÃÃÂµÃÂ³ÃÂ´ÃÂ° ÃÂ³ÃÂ°ÃÃÂ°ÃÂ½ÃÃÂ¸ÃÃÃÂµÃÂ¼ ÃÂ½ÃÂµÃÂ¿ÃÃÃÃÂ¾ÃÂ¹ model/aspect, ÃÂ´ÃÂ°ÃÂ¶ÃÂµ ÃÂµÃÃÂ»ÃÂ¸ ÃÂ² ENV ÃÂ¿ÃÃÃÃÂ°Ã ÃÃÃÃÂ¾ÃÂºÃÂ°
_LUMA_MODEL_ENV  = (os.environ.get("LUMA_MODEL") or "").strip()
LUMA_MODEL       = _LUMA_MODEL_ENV or "ray-2"

_LUMA_ASPECT_ENV = (os.environ.get("LUMA_ASPECT") or "").strip()
LUMA_ASPECT      = _LUMA_ASPECT_ENV or "16:9"

LUMA_DURATION_S  = int((os.environ.get("LUMA_DURATION_S") or "5").strip() or 5)

# ÃÃÂ°ÃÂ·ÃÂ° ÃÃÂ¶ÃÂµ ÃÃÂ¾ÃÂ´ÃÂµÃÃÂ¶ÃÂ¸Ã /dream-machine/v1 Ã¢ ÃÂ´ÃÂ°ÃÂ»ÃÃÃÂµ ÃÂ´ÃÂ¾ÃÃÂ°ÃÂ²ÃÂ»ÃÃÂµÃÂ¼ /generations
LUMA_BASE_URL    = (
    os.environ.get("LUMA_BASE_URL", "https://api.lumalabs.ai/dream-machine/v1")
    .strip()
    .rstrip("/")
)
LUMA_CREATE_PATH = "/generations"
LUMA_STATUS_PATH = "/generations/{id}"

# ÃÃÂ°ÃÂºÃÃÂ¸ÃÂ¼ÃÂ°ÃÂ»ÃÃÂ½ÃÃÂ¹ ÃÃÂ°ÃÂ¹ÃÂ¼ÃÂ°ÃÃ ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ´ÃÂ°ÃÂ½ÃÂ¸Ã Luma
LUMA_MAX_WAIT_S  = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)

# Luma Images (ÃÂ¾ÃÂ¿ÃÃÂ¸ÃÂ¾ÃÂ½ÃÂ°ÃÂ»ÃÃÂ½ÃÂ¾: ÃÂµÃÃÂ»ÃÂ¸ ÃÂ½ÃÂµÃ Ã¢ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÂ¼ OpenAI Images ÃÂºÃÂ°ÃÂº ÃÃÂ¾ÃÂ»ÃÃÃÂº)
LUMA_IMG_BASE_URL = os.environ.get("LUMA_IMG_BASE_URL", "").strip().rstrip("/")
LUMA_IMG_MODEL    = os.environ.get("LUMA_IMG_MODEL", "imagine-image-1").strip()

# ÃÂ¤ÃÂ¾ÃÂ»ÃÃÃÂºÃÂ¸ Luma
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

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Kling (ÃÂ½ÃÂ¾ÃÂ²ÃÃÂ¹ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº ÃÃÂµÃÃÂµÃÂ· CometAPI) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

KLING_BASE_URL   = os.environ.get("KLING_BASE_URL", "https://api.cometapi.com").strip().rstrip("/")
KLING_MODEL_NAME = os.environ.get("KLING_MODEL_NAME", "kling-v1-6").strip()
KLING_MODE       = os.environ.get("KLING_MODE", "std").strip()
KLING_ASPECT     = os.environ.get("KLING_ASPECT", "9:16").strip()
KLING_DURATION_S = int((os.environ.get("KLING_DURATION_S") or "5").strip() or 5)
KLING_MAX_WAIT_S = int((os.environ.get("KLING_MAX_WAIT_S") or "900").strip() or 900)
KLING_UNIT_COST_USD = float((os.environ.get("KLING_UNIT_COST_USD") or "0.80").replace(",", ".") or "0.80")

# ÃÃÃÃÂ¸ÃÂ¹ ÃÂ¸ÃÂ½ÃÃÂµÃÃÂ²ÃÂ°ÃÂ» ÃÂ¼ÃÂµÃÂ¶ÃÂ´Ã ÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃÂ°ÃÂ¼ÃÂ¸ ÃÃÃÂ°ÃÃÃÃÂ° ÃÂ·ÃÂ°ÃÂ´ÃÂ°Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾
VIDEO_POLL_DELAY_S = _env_float("VIDEO_POLL_DELAY_S", 6.0)

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ­ÃÂ¨Ã / ÃÃÃÃÃÃÃÂ¬ÃÃÃ ÃÂ¡ÃÃÂ¡ÃÂ¢ÃÃÂ¯ÃÃÃ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

# ÃÃÂ¾ÃÃÂ»ÃÂµÃÂ´ÃÂ½ÃÂµÃÂµ ÃÃÂ¾ÃÃÂ¾ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃÂµÃÂ»Ã ÃÂ´ÃÂ»Ã ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ°ÃÃÂ¸ÃÂ¸ (ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸Ã)
# user_id -> {"bytes": b"...", "url": "https://..."}
_LAST_ANIM_PHOTO: dict[int, dict] = {}

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ UTILS ---------
_LUMA_ACTIVE_BASE = None  # ÃÂºÃÃ ÃÂ¿ÃÂ¾ÃÃÂ»ÃÂµÃÂ´ÃÂ½ÃÂµÃÂ³ÃÂ¾ ÃÂ¶ÃÂ¸ÃÂ²ÃÂ¾ÃÂ³ÃÂ¾ ÃÃÂ°ÃÂ·ÃÂ¾ÃÂ²ÃÂ¾ÃÂ³ÃÂ¾ URL

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

# Ã¢Ã¢ ÃÃÂµÃÂ·ÃÂ»ÃÂ¸ÃÂ¼ÃÂ¸Ã Ã¢Ã¢
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

# Ã¢Ã¢ Premium page URL Ã¢Ã¢
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

# Ã¢Ã¢ OpenAI clients Ã¢Ã¢
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

# Tavily (ÃÂ¾ÃÂ¿ÃÃÂ¸ÃÂ¾ÃÂ½ÃÂ°ÃÂ»ÃÃÂ½ÃÂ¾)
try:
    if TAVILY_API_KEY:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
    else:
        tavily = None
except Exception:
    tavily = None

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ DB: subscriptions / usage / wallet / kv Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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
    # ÃÂ¼ÃÂ¸ÃÂ³ÃÃÂ°ÃÃÂ¸ÃÂ¸
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
    "ru": "Ã ÃÃÃÃÂºÃÂ¸ÃÂ¹",
    "be": "ÃÃÂµÃÂ»ÃÂ¾ÃÃÃÃÃÂºÃÂ¸ÃÂ¹",
    "uk": "ÃÂ£ÃÂºÃÃÂ°ÃÂ¸ÃÂ½ÃÃÂºÃÂ¸ÃÂ¹",
    "de": "Deutsch",
    "en": "English",
    "fr": "FranÃÂ§ais",
    "th": "Ã Â¹Ã Â¸Ã Â¸Â¢",
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
        "choose_lang": "Ã° ÃÃÃÃÂµÃÃÂ¸ÃÃÂµ ÃÃÂ·ÃÃÂº",
        "lang_set": "Ã¢ ÃÂ¯ÃÂ·ÃÃÂº ÃÃÃÃÂ°ÃÂ½ÃÂ¾ÃÂ²ÃÂ»ÃÂµÃÂ½",
        "menu_title": "ÃÃÂ»ÃÂ°ÃÂ²ÃÂ½ÃÂ¾ÃÂµ ÃÂ¼ÃÂµÃÂ½Ã",
        "btn_engines": "Ã°Â§  ÃÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸",
        "btn_sub": "Ã¢Â­ ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° Ã¢Â¢ ÃÃÂ¾ÃÂ¼ÃÂ¾ÃÃ",
        "btn_wallet": "Ã°Â§Â¾ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã",
        "btn_video": "Ã° ÃÂ¡ÃÂ¾ÃÂ·ÃÂ´ÃÂ°ÃÃ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾",
        "btn_photo": "Ã°Â¼ ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ ÃÃÂ¾ÃÃÂ¾",
        "btn_help": "Ã¢ ÃÃÂ¾ÃÂ¼ÃÂ¾ÃÃ",
        "btn_back": "Ã¢Â¬Ã¯Â¸ ÃÃÂ°ÃÂ·ÃÂ°ÃÂ´",
        "btn_study": "Ã° ÃÂ£ÃÃÃÃÂ°",
        "btn_work": "Ã°Â¼ Ã ÃÂ°ÃÃÂ¾ÃÃÂ°",
        "btn_fun": "Ã° Ã ÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸Ã",
    },
    "be": {
        "choose_lang": "Ã° ÃÃÃÃÃÃÃÂµ ÃÂ¼ÃÂ¾ÃÂ²Ã",
        "lang_set": "Ã¢ ÃÃÂ¾ÃÂ²ÃÂ° ÃÃÃÃÂ°ÃÂ»ÃÃÂ²ÃÂ°ÃÂ½ÃÂ°",
        "menu_title": "ÃÃÂ°ÃÂ»ÃÂ¾ÃÃÂ½ÃÂ°ÃÂµ ÃÂ¼ÃÂµÃÂ½Ã",
        "btn_engines": "Ã°Â§  Ã ÃÃÃÂ°ÃÂ²ÃÃÂºÃ",
        "btn_sub": "Ã¢Â­ ÃÃÂ°ÃÂ´ÃÂ¿ÃÃÃÂºÃÂ° Ã¢Â¢ ÃÃÂ°ÃÂ¿ÃÂ°ÃÂ¼ÃÂ¾ÃÂ³ÃÂ°",
        "btn_wallet": "Ã°Â§Â¾ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã",
        "btn_video": "Ã° ÃÂ¡ÃÃÂ²ÃÂ°ÃÃÃÃ ÃÂ²ÃÃÂ´ÃÃÂ°",
        "btn_photo": "Ã°Â¼ ÃÃÂ¶ÃÃÂ²ÃÃÃ ÃÃÂ¾ÃÃÂ°",
        "btn_help": "Ã¢ ÃÃÂ°ÃÂ¿ÃÂ°ÃÂ¼ÃÂ¾ÃÂ³ÃÂ°",
        "btn_back": "Ã¢Â¬Ã¯Â¸ ÃÃÂ°ÃÂ·ÃÂ°ÃÂ´",
    },
    "uk": {
        "choose_lang": "Ã° ÃÃÃÂµÃÃÃÃ ÃÂ¼ÃÂ¾ÃÂ²Ã",
        "lang_set": "Ã¢ ÃÃÂ¾ÃÂ²Ã ÃÂ²ÃÃÃÂ°ÃÂ½ÃÂ¾ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¾",
        "menu_title": "ÃÃÂ¾ÃÂ»ÃÂ¾ÃÂ²ÃÂ½ÃÂµ ÃÂ¼ÃÂµÃÂ½Ã",
        "btn_engines": "Ã°Â§  Ã ÃÃÃÃ",
        "btn_sub": "Ã¢Â­ ÃÃÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° Ã¢Â¢ ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ¼ÃÂ¾ÃÂ³ÃÂ°",
        "btn_wallet": "Ã°Â§Â¾ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã",
        "btn_video": "Ã° ÃÂ¡ÃÃÂ²ÃÂ¾ÃÃÂ¸ÃÃÂ¸ ÃÂ²ÃÃÂ´ÃÂµÃÂ¾",
        "btn_photo": "Ã°Â¼ ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃÂ¸ ÃÃÂ¾ÃÃÂ¾",
        "btn_help": "Ã¢ ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ¼ÃÂ¾ÃÂ³ÃÂ°",
        "btn_back": "Ã¢Â¬Ã¯Â¸ ÃÃÂ°ÃÂ·ÃÂ°ÃÂ´",
        "btn_study": "Ã° ÃÃÂ°ÃÂ²ÃÃÂ°ÃÂ½ÃÂ½Ã",
        "btn_work": "Ã°Â¼ Ã ÃÂ¾ÃÃÂ¾ÃÃÂ°",
        "btn_fun": "Ã°Â¥ Ã ÃÂ¾ÃÂ·ÃÂ²ÃÂ°ÃÂ³ÃÂ¸",
        "input_placeholder": "ÃÃÃÂµÃÃÃÃ ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ ÃÂ°ÃÃÂ¾ ÃÂ½ÃÂ°ÃÂ¿ÃÂ¸ÃÃÃÃ ÃÂ·ÃÂ°ÃÂ¿ÃÂ¸ÃÃ¢Â¦",
    
    },
    "de": {
        "choose_lang": "Ã° Sprache wÃÂ¤hlen",
        "lang_set": "Ã¢ Sprache gesetzt",
        "menu_title": "HauptmenÃÂ¼",
        "btn_engines": "Ã°Â§  Engines",
        "btn_sub": "Ã¢Â­ Abo Ã¢Â¢ Hilfe",
        "btn_wallet": "Ã°Â§Â¾ Guthaben",
        "btn_video": "Ã° Video erstellen",
        "btn_photo": "Ã°Â¼ Foto animieren",
        "btn_help": "Ã¢ Hilfe",
        "btn_back": "Ã¢Â¬Ã¯Â¸ ZurÃÂ¼ck",
        "btn_study": "Ã° Lernen",
        "btn_work": "Ã°Â¼ Arbeit",
        "btn_fun": "Ã° SpaÃ",
    },
    "en": {
        "choose_lang": "Ã° Choose language",
        "lang_set": "Ã¢ Language set",
        "menu_title": "Main menu",
        "btn_engines": "Ã°Â§  Engines",
        "btn_sub": "Ã¢Â­ Subscription Ã¢Â¢ Help",
        "btn_wallet": "Ã°Â§Â¾ Balance",
        "btn_video": "Ã° Create video",
        "btn_photo": "Ã°Â¼ Animate photo",
        "btn_help": "Ã¢ Help",
        "btn_back": "Ã¢Â¬Ã¯Â¸ Back",
        "btn_study": "Ã° Study",
        "btn_work": "Ã°Â¼ Work",
        "btn_fun": "Ã° Fun",
    },
    "fr": {
        "choose_lang": "Ã° Choisir la langue",
        "lang_set": "Ã¢ Langue dÃÂ©finie",
        "menu_title": "Menu principal",
        "btn_engines": "Ã°Â§  Moteurs",
        "btn_sub": "Ã¢Â­ Abonnement Ã¢Â¢ Aide",
        "btn_wallet": "Ã°Â§Â¾ Solde",
        "btn_video": "Ã° CrÃÂ©er une vidÃÂ©o",
        "btn_photo": "Ã°Â¼ Animer une photo",
        "btn_help": "Ã¢ Aide",
        "btn_back": "Ã¢Â¬Ã¯Â¸ Retour",
        "btn_study": "Ã° Ãtudes",
        "btn_work": "Ã°Â¼ Travail",
        "btn_fun": "Ã° Divertissement",
    },
    "th": {
        "choose_lang": "Ã° Ã Â¹Ã Â¸Â¥Ã Â¸Â·Ã Â¸Â­Ã Â¸Ã Â¸ Ã Â¸Â²Ã Â¸Â©Ã Â¸Â²",
        "lang_set": "Ã¢ Ã Â¸Ã Â¸Ã Â¹Ã Â¸Ã Â¸Ã Â¹Ã Â¸Â²Ã Â¸ Ã Â¸Â²Ã Â¸Â©Ã Â¸Â²Ã Â¹Ã Â¸Â¥Ã Â¹Ã Â¸Â§",
        "menu_title": "Ã Â¹Ã Â¸Â¡Ã Â¸Ã Â¸Â¹Ã Â¸Â«Ã Â¸Â¥Ã Â¸Ã Â¸",
        "btn_engines": "Ã°Â§  Ã Â¹Ã Â¸Â­Ã Â¸Ã Â¸Ã Â¸Â´Ã Â¸",
        "btn_sub": "Ã¢Â­ Ã Â¸ÂªÃ Â¸Â¡Ã Â¸Ã Â¸Ã Â¸Â£Ã Â¸ÂªÃ Â¸Â¡Ã Â¸Â²Ã Â¸Ã Â¸Â´Ã Â¸ Ã¢Â¢ Ã Â¸Ã Â¹Ã Â¸Â§Ã Â¸Â¢Ã Â¹Ã Â¸Â«Ã Â¸Â¥Ã Â¸Â·Ã Â¸Â­",
        "btn_wallet": "Ã°Â§Â¾ Ã Â¸Â¢Ã Â¸Â­Ã Â¸Ã Â¸Ã Â¸Ã Â¹Ã Â¸Â«Ã Â¸Â¥Ã Â¸Â·Ã Â¸Â­",
        "btn_video": "Ã° Ã Â¸ÂªÃ Â¸Â£Ã Â¹Ã Â¸Â²Ã Â¸Ã Â¸Â§Ã Â¸Â´Ã Â¸Ã Â¸ÂµÃ Â¹Ã Â¸Â­",
        "btn_photo": "Ã°Â¼ Ã Â¸Ã Â¸Â³Ã Â¹Ã Â¸Â«Ã Â¹Ã Â¸Â£Ã Â¸Â¹Ã Â¸Ã Â¹Ã Â¸Ã Â¸Â¥Ã Â¸Â·Ã Â¹Ã Â¸Â­Ã Â¸Ã Â¹Ã Â¸Â«Ã Â¸Â§",
        "btn_help": "Ã¢ Ã Â¸Ã Â¹Ã Â¸Â§Ã Â¸Â¢Ã Â¹Ã Â¸Â«Ã Â¸Â¥Ã Â¸Â·Ã Â¸Â­",
        "btn_back": "Ã¢Â¬Ã¯Â¸ Ã Â¸Ã Â¸Â¥Ã Â¸Ã Â¸",
        "btn_study": "Ã° Ã Â¹Ã Â¸Â£Ã Â¸ÂµÃ Â¸Â¢Ã Â¸",
        "btn_work": "Ã°Â¼ Ã Â¸Ã Â¸Â²Ã Â¸",
        "btn_fun": "Ã° Ã Â¸ÂªÃ Â¸Ã Â¸Â¸Ã Â¸",
    },
}

def t(user_id: int, key: str) -> str:
    lang = get_lang(user_id)
    return (I18N.get(lang) or I18N["ru"]).get(key, key)

def system_prompt_for(lang: str) -> str:
    mapping = {
        "ru": "ÃÃÃÂ²ÃÂµÃÃÂ°ÃÂ¹ ÃÂ½ÃÂ° ÃÃÃÃÃÂºÃÂ¾ÃÂ¼ ÃÃÂ·ÃÃÂºÃÂµ.",
        "be": "ÃÃÂ´ÃÂºÃÂ°ÃÂ·ÃÂ²ÃÂ°ÃÂ¹ ÃÂ¿ÃÂ°-ÃÃÂµÃÂ»ÃÂ°ÃÃÃÃÂºÃ.",
        "uk": "ÃÃÃÂ´ÃÂ¿ÃÂ¾ÃÂ²ÃÃÂ´ÃÂ°ÃÂ¹ ÃÃÂºÃÃÂ°ÃÃÂ½ÃÃÃÂºÃÂ¾Ã ÃÂ¼ÃÂ¾ÃÂ²ÃÂ¾Ã.",
        "de": "Antworte auf Deutsch.",
        "en": "Answer in English.",
        "fr": "RÃÂ©ponds en franÃÂ§ais.",
        "th": "Ã Â¸Ã Â¸Â­Ã Â¸Ã Â¹Ã Â¸Ã Â¹Ã Â¸Ã Â¸ Ã Â¸Â²Ã Â¸Â©Ã Â¸Â²Ã Â¹Ã Â¸Ã Â¸Â¢",
    }
    return mapping.get(lang, mapping["ru"])

# Extended pack (long UI texts / hints)
I18N_PACK: dict[str, dict[str, str]] = {
    "welcome": {
        "ru": "ÃÃÃÂ¸ÃÂ²ÃÂµÃ! ÃÂ¯ ÃÃÂµÃÂ¹ÃÃÂ¾Ã¢Bot Ã¢ Ã¢Â¡ ÃÂ¼ÃÃÂ»ÃÃÃÂ¸ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ÃÂ½ÃÃÂ¹ ÃÃÂ¾Ã ÃÂ¸ÃÂ· 7 ÃÂ½ÃÂµÃÂ¹ÃÃÂ¾ÃÃÂµÃÃÂµÃÂ¹ ÃÂ´ÃÂ»Ã ÃÃÃÃÃ, ÃÃÂ°ÃÃÂ¾ÃÃ ÃÂ¸ ÃÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸ÃÂ¹.",
        "be": "ÃÃÃÃÂ²ÃÃÃÂ°ÃÂ½ÃÂ½ÃÂµ! ÃÂ¯ ÃÃÂµÃÂ¹ÃÃÂ¾Ã¢Bot Ã¢ Ã¢Â¡ ÃÃÂ¼ÃÂ°ÃÃÃÃÂ¶ÃÃÂ¼ÃÂ½Ã ÃÃÂ¾Ã ÃÂ· 7 ÃÂ½ÃÂµÃÂ¹ÃÃÂ°ÃÃÂµÃÃÂ°ÃÂº ÃÂ´ÃÂ»Ã ÃÂ²ÃÃÃÂ¾ÃÃ, ÃÂ¿ÃÃÂ°ÃÃ Ã ÃÂ·ÃÂ°ÃÃÂ°Ã.",
        "uk": "ÃÃÃÂ¸ÃÂ²ÃÃ! ÃÂ¯ ÃÃÂµÃÂ¹ÃÃÂ¾Ã¢Bot Ã¢ Ã¢Â¡ ÃÂ¼ÃÃÂ»ÃÃÃÂ¸ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ÃÂ½ÃÂ¸ÃÂ¹ ÃÃÂ¾Ã ÃÃÂ· 7 ÃÂ½ÃÂµÃÂ¹ÃÃÂ¾ÃÂ¼ÃÂµÃÃÂµÃÂ¶ ÃÂ´ÃÂ»Ã ÃÂ½ÃÂ°ÃÂ²ÃÃÂ°ÃÂ½ÃÂ½Ã, ÃÃÂ¾ÃÃÂ¾ÃÃÂ¸ ÃÃÂ° ÃÃÂ¾ÃÂ·ÃÂ²ÃÂ°ÃÂ³.",
        "de": "Hallo! Ich bin NeuroÃ¢Bot Ã¢ Ã¢Â¡ ein MultimodeÃ¢Bot mit 7 KIÃ¢Engines fÃÂ¼r Lernen, Arbeit und SpaÃ.",
        "en": "Hi! IÃ¢m NeuroÃ¢Bot Ã¢ Ã¢Â¡ a multiÃ¢mode bot with 7 AI engines for study, work and fun.",
        "fr": "Salut ! Je suis NeuroÃ¢Bot Ã¢ Ã¢Â¡ un bot multiÃ¢modes avec 7 moteurs IA pour ÃÂ©tudier, travailler et se divertir.",
        "th": "Ã Â¸ÂªÃ Â¸Â§Ã Â¸Ã Â¸ÂªÃ Â¸Ã Â¸Âµ! Ã Â¸Ã Â¸Ã Â¸Ã Â¸Ã Â¸Â·Ã Â¸Â­ NeuroÃ¢Bot Ã¢ Ã¢Â¡ Ã Â¸Ã Â¸Â­Ã Â¸Ã Â¸Â«Ã Â¸Â¥Ã Â¸Â²Ã Â¸Â¢Ã Â¹Ã Â¸Â«Ã Â¸Â¡Ã Â¸Ã Â¸Ã Â¸Â£Ã Â¹Ã Â¸Â­Ã Â¸Â¡Ã Â¹Ã Â¸Â­Ã Â¸Ã Â¸Ã Â¸Â´Ã Â¸ AI 7 Ã Â¸Ã Â¸Ã Â¸Â§ Ã Â¸ÂªÃ Â¸Â³Ã Â¸Â«Ã Â¸Â£Ã Â¸Ã Â¸Ã Â¹Ã Â¸Â£Ã Â¸ÂµÃ Â¸Â¢Ã Â¸ Ã Â¸Ã Â¸Â²Ã Â¸ Ã Â¹Ã Â¸Â¥Ã Â¸Â°Ã Â¸Ã Â¸Â§Ã Â¸Â²Ã Â¸Â¡Ã Â¸Ã Â¸Ã Â¸Ã Â¹Ã Â¸Ã Â¸Â´Ã Â¸",
    },
    "ask_video_prompt": {
        "ru": "Ã° ÃÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã ÃÂ´ÃÂ»Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾, ÃÂ½ÃÂ°ÃÂ¿ÃÃÂ¸ÃÂ¼ÃÂµÃ:\nÃÂ«ÃÂ¡ÃÂ´ÃÂµÃÂ»ÃÂ°ÃÂ¹ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾: ÃÂ·ÃÂ°ÃÂºÃÂ°Ã ÃÂ½ÃÂ°ÃÂ´ ÃÂ¼ÃÂ¾ÃÃÂµÃÂ¼, 7 ÃÃÂµÃÂº, 16:9ÃÂ»",
        "be": "Ã° ÃÃÂ°ÃÂ¿ÃÃÃ ÃÂ·ÃÂ°ÃÂ¿ÃÃ ÃÂ´ÃÂ»Ã ÃÂ²ÃÃÂ´ÃÃÂ°, ÃÂ½ÃÂ°ÃÂ¿ÃÃÃÂºÃÂ»ÃÂ°ÃÂ´:\nÃÂ«ÃÃÃÂ°ÃÃ ÃÂ²ÃÃÂ´ÃÃÂ°: ÃÂ·ÃÂ°ÃÃÂ°ÃÂ´ ÃÃÂ¾ÃÂ½ÃÃÂ° ÃÂ½ÃÂ°ÃÂ´ ÃÂ¼ÃÂ¾ÃÃÂ°ÃÂ¼, 7 ÃÃÂµÃÂº, 16:9ÃÂ»",
        "uk": "Ã° ÃÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ ÃÂ·ÃÂ°ÃÂ¿ÃÂ¸Ã ÃÂ´ÃÂ»Ã ÃÂ²ÃÃÂ´ÃÂµÃÂ¾, ÃÂ½ÃÂ°ÃÂ¿ÃÃÂ¸ÃÂºÃÂ»ÃÂ°ÃÂ´:\nÃÂ«ÃÃÃÂ¾ÃÃÂ¸ ÃÂ²ÃÃÂ´ÃÂµÃÂ¾: ÃÂ·ÃÂ°ÃÃÃÂ´ ÃÂ½ÃÂ°ÃÂ´ ÃÂ¼ÃÂ¾ÃÃÂµÃÂ¼, 7 Ã, 16:9ÃÂ»",
        "de": "Ã° Schreibe einen Prompt fÃÂ¼r das Video, z.B.:\nÃ¢Erstelle ein Video: Sonnenuntergang am Meer, 7s, 16:9Ã¢",
        "en": "Ã° Type a video prompt, e.g.:\nÃ¢Make a video: sunset over the sea, 7s, 16:9Ã¢",
        "fr": "Ã° Ãcris un prompt pour la vidÃÂ©o, par ex. :\nÃÂ« Fais une vidÃÂ©o : coucher de soleil sur la mer, 7s, 16:9 ÃÂ»",
        "th": "Ã° Ã Â¸Ã Â¸Â´Ã Â¸Â¡Ã Â¸Ã Â¹Ã Â¸Ã Â¸Â³Ã Â¸ÂªÃ Â¸Ã Â¹Ã Â¸Ã Â¸Ã Â¸Â³Ã Â¸Â§Ã Â¸Â´Ã Â¸Ã Â¸ÂµÃ Â¹Ã Â¸Â­ Ã Â¹Ã Â¸Ã Â¹Ã Â¸:\nÃ¢Ã Â¸Ã Â¸Â³Ã Â¸Â§Ã Â¸Â´Ã Â¸Ã Â¸ÂµÃ Â¹Ã Â¸Â­: Ã Â¸Ã Â¸Â£Ã Â¸Â°Ã Â¸Â­Ã Â¸Â²Ã Â¸Ã Â¸Â´Ã Â¸Ã Â¸Â¢Ã Â¹Ã Â¸Ã Â¸Ã Â¹Ã Â¸Â«Ã Â¸Ã Â¸Â·Ã Â¸Â­Ã Â¸Ã Â¸Â°Ã Â¹Ã Â¸Â¥ 7Ã Â¸Â§Ã Â¸Â´ 16:9Ã¢",
    },
    "ask_send_photo": {
        "ru": "Ã°Â¼ ÃÃÃÂ¸ÃÃÂ»ÃÂ¸ ÃÃÂ¾ÃÃÂ¾, ÃÂ·ÃÂ°ÃÃÂµÃÂ¼ ÃÂ²ÃÃÃÂµÃÃÂ¸ ÃÂ«ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ ÃÃÂ¾ÃÃÂ¾ÃÂ».",
        "be": "Ã°Â¼ ÃÃÂ°ÃÃÂ»Ã ÃÃÂ¾ÃÃÂ°, ÃÂ·ÃÂ°ÃÃÃÂ¼ ÃÂ²ÃÃÃÂµÃÃ ÃÂ«ÃÃÂ¶ÃÃÂ²ÃÃÃ ÃÃÂ¾ÃÃÂ°ÃÂ».",
        "uk": "Ã°Â¼ ÃÃÂ°ÃÂ´ÃÃÃÂ»ÃÂ¸ ÃÃÂ¾ÃÃÂ¾, ÃÂ¿ÃÂ¾ÃÃÃÂ¼ ÃÂ¾ÃÃÂµÃÃÂ¸ ÃÂ«ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃÂ¸ ÃÃÂ¾ÃÃÂ¾ÃÂ».",
        "de": "Ã°Â¼ Sende ein Foto, dann wÃÂ¤hle Ã¢Foto animierenÃ¢.",
        "en": "Ã°Â¼ Send a photo, then choose Ã¢Animate photoÃ¢.",
        "fr": "Ã°Â¼ Envoyez une photo, puis choisissez ÃÂ« Animer la photo ÃÂ».",
        "th": "Ã°Â¼ Ã Â¸ÂªÃ Â¹Ã Â¸Ã Â¸Â£Ã Â¸Â¹Ã Â¸ Ã Â¸Ã Â¸Â²Ã Â¸Ã Â¸Ã Â¸Ã Â¹Ã Â¸Ã Â¹Ã Â¸Â¥Ã Â¸Â·Ã Â¸Â­Ã Â¸ Ã¢Ã Â¸Ã Â¸Â³Ã Â¹Ã Â¸Â«Ã Â¹Ã Â¸Â£Ã Â¸Â¹Ã Â¸Ã Â¹Ã Â¸Ã Â¸Â¥Ã Â¸Â·Ã Â¹Ã Â¸Â­Ã Â¸Ã Â¹Ã Â¸Â«Ã Â¸Â§Ã¢",
    },
    "photo_received": {
        "ru": "Ã°Â¼ ÃÂ¤ÃÂ¾ÃÃÂ¾ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂµÃÂ½ÃÂ¾. ÃÂ¥ÃÂ¾ÃÃÂ¸ÃÃÂµ ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ?",
        "be": "Ã°Â¼ ÃÂ¤ÃÂ¾ÃÃÂ° ÃÂ°ÃÃÃÃÂ¼ÃÂ°ÃÂ½ÃÂ°. ÃÃÂ¶ÃÃÂ²ÃÃÃ?",
        "uk": "Ã°Â¼ ÃÂ¤ÃÂ¾ÃÃÂ¾ ÃÂ¾ÃÃÃÂ¸ÃÂ¼ÃÂ°ÃÂ½ÃÂ¾. ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃÂ¸?",
        "de": "Ã°Â¼ Foto erhalten. Animieren?",
        "en": "Ã°Â¼ Photo received. Animate it?",
        "fr": "Ã°Â¼ Photo reÃÂ§ue. LÃ¢animer ?",
        "th": "Ã°Â¼ Ã Â¹Ã Â¸Ã Â¹Ã Â¸Â£Ã Â¸Ã Â¸Ã Â¸Â£Ã Â¸Â¹Ã Â¸Ã Â¹Ã Â¸Â¥Ã Â¹Ã Â¸Â§ Ã Â¸Ã Â¹Ã Â¸Â­Ã Â¸Ã Â¸Ã Â¸Â²Ã Â¸Â£Ã Â¸Ã Â¸Â³Ã Â¹Ã Â¸Â«Ã Â¹Ã Â¹Ã Â¸Ã Â¸Â¥Ã Â¸Â·Ã Â¹Ã Â¸Â­Ã Â¸Ã Â¹Ã Â¸Â«Ã Â¸Â§Ã Â¹Ã Â¸Â«Ã Â¸Â¡?",
    },
    "animate_btn": {
        "ru": "Ã°Â¬ ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ ÃÃÂ¾ÃÃÂ¾",
        "be": "Ã°Â¬ ÃÃÂ¶ÃÃÂ²ÃÃÃ ÃÃÂ¾ÃÃÂ°",
        "uk": "Ã°Â¬ ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃÂ¸ ÃÃÂ¾ÃÃÂ¾",
        "de": "Ã°Â¬ Foto animieren",
        "en": "Ã°Â¬ Animate photo",
        "fr": "Ã°Â¬ Animer la photo",
        "th": "Ã°Â¬ Ã Â¸Ã Â¸Â³Ã Â¹Ã Â¸Â«Ã Â¹Ã Â¸Â£Ã Â¸Â¹Ã Â¸Ã Â¹Ã Â¸Ã Â¸Â¥Ã Â¸Â·Ã Â¹Ã Â¸Â­Ã Â¸Ã Â¹Ã Â¸Â«Ã Â¸Â§",
    },
    "choose_engine": {
        "ru": "ÃÃÃÃÂµÃÃÂ¸ÃÃÂµ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº:",
        "be": "ÃÃÃÃÃÃÃÂµ ÃÃÃÃÂ°ÃÂ²ÃÃÂº:",
        "uk": "ÃÃÃÂµÃÃÃÃ ÃÃÃÃÃÂ¹:",
        "de": "WÃÂ¤hle die Engine:",
        "en": "Choose engine:",
        "fr": "Choisissez le moteur:",
        "th": "Ã Â¹Ã Â¸Â¥Ã Â¸Â·Ã Â¸Â­Ã Â¸Ã Â¹Ã Â¸Â­Ã Â¸Ã Â¸Ã Â¸Â´Ã Â¸:",
    },
    "runway_disabled_textvideo": {
        "ru": "Ã¢ Ã¯Â¸ Runway ÃÂ¾ÃÃÂºÃÂ»ÃÃÃÃÂ½ ÃÂ´ÃÂ»Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÂ¿ÃÂ¾ ÃÃÂµÃÂºÃÃÃ/ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃ. ÃÃÃÃÂµÃÃÂ¸ÃÃÂµ Kling, Luma ÃÂ¸ÃÂ»ÃÂ¸ Sora.",
        "be": "Ã¢ Ã¯Â¸ Runway ÃÂ°ÃÂ´ÃÂºÃÂ»ÃÃÃÂ°ÃÂ½Ã ÃÂ´ÃÂ»Ã ÃÂ²ÃÃÂ´ÃÃÂ° ÃÂ¿ÃÂ° ÃÃÃÂºÃÃÃÂµ/ÃÂ³ÃÂ¾ÃÂ»ÃÂ°ÃÃÂµ. ÃÃÃÃÃÃÃÂµ Kling, Luma ÃÂ°ÃÃÂ¾ Sora.",
        "uk": "Ã¢ Ã¯Â¸ Runway ÃÂ²ÃÂ¸ÃÂ¼ÃÂºÃÂ½ÃÂµÃÂ½ÃÂ¾ ÃÂ´ÃÂ»Ã ÃÂ²ÃÃÂ´ÃÂµÃÂ¾ ÃÂ· ÃÃÂµÃÂºÃÃÃ/ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃ. ÃÃÃÂµÃÃÃÃ Kling, Luma ÃÂ°ÃÃÂ¾ Sora.",
        "de": "Ã¢ Ã¯Â¸ Runway ist fÃÂ¼r Text/VoiceÃ¢Video deaktiviert. WÃÂ¤hle Kling, Luma oder Sora.",
        "en": "Ã¢ Ã¯Â¸ Runway is disabled for text/voiceÃ¢video. Choose Kling, Luma or Sora.",
        "fr": "Ã¢ Ã¯Â¸ Runway est dÃÂ©sactivÃÂ© pour texte/voixÃ¢vidÃÂ©o. Choisissez Kling, Luma ou Sora.",
        "th": "Ã¢ Ã¯Â¸ Ã Â¸Ã Â¸Â´Ã Â¸ Runway Ã Â¸ÂªÃ Â¸Â³Ã Â¸Â«Ã Â¸Â£Ã Â¸Ã Â¸Ã Â¸Ã Â¹Ã Â¸Â­Ã Â¸Ã Â¸Â§Ã Â¸Â²Ã Â¸Â¡/Ã Â¹Ã Â¸ÂªÃ Â¸ÂµÃ Â¸Â¢Ã Â¸Ã¢Ã Â¸Â§Ã Â¸Â´Ã Â¸Ã Â¸ÂµÃ Â¹Ã Â¸Â­ Ã Â¹Ã Â¸Â¥Ã Â¸Â·Ã Â¸Â­Ã Â¸ Kling, Luma Ã Â¸Â«Ã Â¸Â£Ã Â¸Â·Ã Â¸Â­ Sora",
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
    ÃÃÂ»ÃÂ°ÃÂ²ÃÂ¸ÃÂ°ÃÃÃÃÂ° ÃÂ²ÃÃÃÂ¾ÃÃÂ° ÃÃÂ·ÃÃÂºÃÂ°.
    ÃÂ¢ÃÃÂµÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ¸ÃÂµ: ÃÂ¿ÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÃ ÃÂ¿ÃÃÂ¸ ÃÂºÃÂ°ÃÂ¶ÃÂ´ÃÂ¾ÃÂ¼ /start.
    ÃÃÂ»Ã ÃÃÂ´ÃÂ¾ÃÃÃÃÂ²ÃÂ° ÃÂ´ÃÂ¾ÃÃÂ°ÃÂ²ÃÂ»ÃÃÂµÃÂ¼ ÃÂ«ÃÃÃÂ¾ÃÂ´ÃÂ¾ÃÂ»ÃÂ¶ÃÂ¸ÃÃÃÂ» Ã ÃÃÂµÃÂºÃÃÃÂ¸ÃÂ¼ ÃÃÂ·ÃÃÂºÃÂ¾ÃÂ¼, ÃÂµÃÃÂ»ÃÂ¸ ÃÂ¾ÃÂ½ ÃÃÂ¶ÃÂµ ÃÂ²ÃÃÃÃÂ°ÃÂ½.
    """
    uid = int(user_id) if user_id is not None else 0
    rows = []
    if uid and has_lang(uid):
        cur = get_lang(uid)
        cur_name = LANG_NAMES.get(cur, cur)
        rows.append([InlineKeyboardButton(f"Ã¢Â¡Ã¯Â¸ ÃÃÃÂ¾ÃÂ´ÃÂ¾ÃÂ»ÃÂ¶ÃÂ¸ÃÃ ({cur_name})", callback_data="lang:__keep__")])
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

# === ÃÃÃÃÃÂ«Ã ÃÃÃÂ¨ÃÃÃÃ (USD) ===
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

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¸ÃÂ¼ÃÂ¸ÃÃ/ÃÃÂµÃÂ½Ã Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
USD_RUB = float(os.environ.get("USD_RUB", "100"))
ONEOFF_MARKUP_DEFAULT = float(os.environ.get("ONEOFF_MARKUP_DEFAULT", "1.0"))
ONEOFF_MARKUP_RUNWAY  = float(os.environ.get("ONEOFF_MARKUP_RUNWAY",  "0.5"))
LUMA_RES_HINT = os.environ.get("LUMA_RES", "720p").lower()
RUNWAY_UNIT_COST_USD = float(os.environ.get("RUNWAY_UNIT_COST_USD", "7.0"))
IMG_COST_USD = float(os.environ.get("IMG_COST_USD", "0.05"))

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ SORA (via Comet / aggregator) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
# Variables may be provided later; keep disabled safely by default.
SORA_ENABLED = bool(os.environ.get("SORA_ENABLED", "").strip())
SORA_COMET_BASE_URL = os.environ.get("SORA_COMET_BASE_URL", "").strip()  # e.g. https://api.cometapi.com
SORA_COMET_API_KEY = os.environ.get("SORA_COMET_API_KEY", "").strip()
SORA_MODEL_FREE = os.environ.get("SORA_MODEL_FREE", "sora-2").strip()
SORA_MODEL_PRO = os.environ.get("SORA_MODEL_PRO", "sora-2-pro").strip()
SORA_UNIT_COST_USD = float(os.environ.get("SORA_UNIT_COST_USD", "0.40"))  # fallback estimate per second


# DEMO: free ÃÂ´ÃÂ°ÃÃ ÃÂ¿ÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÂºÃÂ»ÃÃÃÂµÃÂ²ÃÃÂµ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸
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
    "kling":  "luma",    # <Ã¢ Kling ÃÃÂ¸ÃÂ´ÃÂ¸Ã ÃÂ½ÃÂ° ÃÃÂ¾ÃÂ¼ ÃÂ¶ÃÂµ ÃÃÃÂ´ÃÂ¶ÃÂµÃÃÂµ
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

# ÃÂºÃÂ°ÃÂºÃÂ¸ÃÂµ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸ ÃÂ½ÃÂ° ÃÂºÃÂ°ÃÂºÃÂ¾ÃÂ¹ ÃÃÃÂ´ÃÂ¶ÃÂµÃ ÃÃÂ°ÃÂ´ÃÃÃÃ
ENGINE_BUDGET_GROUP = {
    "luma": "luma",
    "kling": "luma",   # Kling ÃÂ¸ Luma ÃÂ´ÃÂµÃÂ»ÃÃ ÃÂ¾ÃÂ´ÃÂ¸ÃÂ½ ÃÃÃÂ´ÃÂ¶ÃÂµÃ
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
    ÃÃÃÂ¾ÃÂ²ÃÂµÃÃÃÂµÃÂ¼, ÃÂ¼ÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ ÃÂ»ÃÂ¸ ÃÂ¿ÃÂ¾ÃÃÃÂ°ÃÃÂ¸ÃÃ est_cost_usd ÃÂ½ÃÂ° ÃÃÂºÃÂ°ÃÂ·ÃÂ°ÃÂ½ÃÂ½ÃÃÂ¹ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº.
    ÃÃÂ¾ÃÂ·ÃÂ²ÃÃÂ°ÃÃÂ°ÃÂµÃÂ¼ (ok, reason):
      ok = True  -> ÃÂ¼ÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾, reason = ""
      ok = False -> ÃÂ½ÃÂµÃÂ»ÃÃÂ·Ã, reason = "ASK_SUBSCRIBE" ÃÂ¸ÃÂ»ÃÂ¸ "OFFER:<usd>"
    """
    group = ENGINE_BUDGET_GROUP.get(engine, engine)

    # ÃÃÂµÃÂ·ÃÂ»ÃÂ¸ÃÂ¼ÃÂ¸ÃÃÂ½ÃÃÂµ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃÂµÃÂ»ÃÂ¸
    if is_unlimited(user_id, username):
        if group in ("luma", "runway", "img"):
            _usage_update(user_id, **{f"{group}_usd": est_cost_usd})
        return True, ""

    # ÃÂµÃÃÂ»ÃÂ¸ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº ÃÂ½ÃÂµ ÃÃÂ°ÃÃÂ¸ÃÃÂ¸ÃÃÂ¸ÃÃÃÂµÃÂ¼ÃÃÂ¹ Ã¢ ÃÂ¿ÃÃÂ¾ÃÃÃÂ¾ ÃÃÂ°ÃÂ·ÃÃÂµÃÃÂ°ÃÂµÃÂ¼
    if group not in ("luma", "runway", "img"):
        return True, ""

    tier = get_subscription_tier(user_id)
    lim = _limits_for(user_id)
    row = _usage_row(user_id)

    spent = row[f"{group}_usd"]
    budget = lim[f"{group}_budget_usd"]

    # ÃÂµÃÃÂ»ÃÂ¸ ÃÂ²ÃÂ»ÃÂµÃÂ·ÃÂ°ÃÂµÃÂ¼ ÃÂ² ÃÂ´ÃÂ½ÃÂµÃÂ²ÃÂ½ÃÂ¾ÃÂ¹ ÃÃÃÂ´ÃÂ¶ÃÂµÃ ÃÂ¿ÃÂ¾ ÃÂ³ÃÃÃÂ¿ÃÂ¿ÃÂµ (luma/runway/img)
    if spent + est_cost_usd <= budget + 1e-9:
        _usage_update(user_id, **{f"{group}_usd": est_cost_usd})
        return True, ""

    # ÃÃÂ¾ÃÂ¿ÃÃÃÂºÃÂ° ÃÂ¿ÃÂ¾ÃÂºÃÃÃÃ ÃÂ¸ÃÂ· ÃÂµÃÂ´ÃÂ¸ÃÂ½ÃÂ¾ÃÂ³ÃÂ¾ ÃÂºÃÂ¾ÃÃÂµÃÂ»ÃÃÂºÃÂ°
    need = max(0.0, spent + est_cost_usd - budget)
    if need > 0:
        if _wallet_total_take(user_id, need):
            _usage_update(user_id, **{f"{group}_usd": est_cost_usd})
            return True, ""

        # ÃÂ½ÃÂ° ÃÃÃÂ¸-ÃÃÂ°ÃÃÂ¸ÃÃÂµ ÃÂ¿ÃÃÂ¾ÃÃÂ¸ÃÂ¼ ÃÂ¾ÃÃÂ¾ÃÃÂ¼ÃÂ¸ÃÃ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃ
        if tier == "free":
            return False, "ASK_SUBSCRIBE"

        # ÃÂ½ÃÂ° ÃÂ¿ÃÂ»ÃÂ°ÃÃÂ½ÃÃ ÃÃÂ°ÃÃÂ¸ÃÃÂ°Ã ÃÂ¿ÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÂ¿ÃÃÂµÃÂ´ÃÂ»ÃÂ¾ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ´ÃÂ¾ÃÂºÃÃÂ¿ÃÂ¸ÃÃ ÃÂ»ÃÂ¸ÃÂ¼ÃÂ¸Ã
        return False, f"OFFER:{need:.2f}"

    return True, ""


def _register_engine_spend(user_id: int, engine: str, usd: float):
    """
    Ã ÃÂµÃÂ³ÃÂ¸ÃÃÃÃÂ¸ÃÃÃÂµÃÂ¼ ÃÃÂ¶ÃÂµ ÃÃÂ¾ÃÂ²ÃÂµÃÃÃÃÂ½ÃÂ½ÃÃÂ¹ ÃÃÂ°ÃÃÃÂ¾ÃÂ´ ÃÂ¿ÃÂ¾ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃ.
    ÃÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÃÃ ÃÂ´ÃÂ»Ã ÃÃÂµÃ ÃÂ²ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ¾ÃÂ², ÃÂ³ÃÂ´ÃÂµ ÃÃÃÂ¾ÃÂ¸ÃÂ¼ÃÂ¾ÃÃÃ ÃÂ¸ÃÂ·ÃÂ²ÃÂµÃÃÃÂ½ÃÂ° ÃÂ¿ÃÂ¾ÃÃÃÃÂ°ÃÂºÃÃÃÂ¼
    ÃÂ¸ÃÂ»ÃÂ¸ ÃÂºÃÂ¾ÃÂ³ÃÂ´ÃÂ° ÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃÂµÃÂ»Ã ÃÃÂµÃÂ·ÃÂ»ÃÂ¸ÃÂ¼ÃÂ¸ÃÃÂ½ÃÃÂ¹.
    """
    group = ENGINE_BUDGET_GROUP.get(engine, engine)
    if group in ("luma", "runway", "img"):
        _usage_update(user_id, **{f"{group}_usd": float(usd)})
        
# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Prompts Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
SYSTEM_PROMPT = (
    "ÃÂ¢Ã ÃÂ´ÃÃÃÂ¶ÃÂµÃÂ»ÃÃÃÂ½ÃÃÂ¹ ÃÂ¸ ÃÂ»ÃÂ°ÃÂºÃÂ¾ÃÂ½ÃÂ¸ÃÃÂ½ÃÃÂ¹ ÃÂ°ÃÃÃÂ¸ÃÃÃÂµÃÂ½Ã ÃÂ½ÃÂ° ÃÃÃÃÃÂºÃÂ¾ÃÂ¼. "
    "ÃÃÃÂ²ÃÂµÃÃÂ°ÃÂ¹ ÃÂ¿ÃÂ¾ ÃÃÃÃÂ¸, ÃÃÃÃÃÂºÃÃÃÃÂ¸ÃÃÃÂ¹ ÃÃÂ¿ÃÂ¸ÃÃÂºÃÂ°ÃÂ¼ÃÂ¸/ÃÃÂ°ÃÂ³ÃÂ°ÃÂ¼ÃÂ¸, ÃÂ½ÃÂµ ÃÂ²ÃÃÂ´ÃÃÂ¼ÃÃÂ²ÃÂ°ÃÂ¹ ÃÃÂ°ÃÂºÃÃ. "
    "ÃÃÃÂ»ÃÂ¸ ÃÃÃÃÂ»ÃÂ°ÃÂµÃÃÃÃ ÃÂ½ÃÂ° ÃÂ¸ÃÃÃÂ¾ÃÃÂ½ÃÂ¸ÃÂºÃÂ¸ Ã¢ ÃÂ² ÃÂºÃÂ¾ÃÂ½ÃÃÂµ ÃÂ´ÃÂ°ÃÂ¹ ÃÂºÃÂ¾ÃÃÂ¾ÃÃÂºÃÂ¸ÃÂ¹ ÃÃÂ¿ÃÂ¸ÃÃÂ¾ÃÂº ÃÃÃÃÂ»ÃÂ¾ÃÂº."
)
VISION_SYSTEM_PROMPT = (
    "ÃÂ¢Ã ÃÃÃÃÂºÃÂ¾ ÃÂ¾ÃÂ¿ÃÂ¸ÃÃÃÂ²ÃÂ°ÃÂµÃÃ ÃÃÂ¾ÃÂ´ÃÂµÃÃÂ¶ÃÂ¸ÃÂ¼ÃÂ¾ÃÂµ ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂ¹: ÃÂ¾ÃÃÃÂµÃÂºÃÃ, ÃÃÂµÃÂºÃÃ, ÃÃÃÂµÃÂ¼Ã, ÃÂ³ÃÃÂ°ÃÃÂ¸ÃÂºÃÂ¸. "
    "ÃÃÂµ ÃÂ¸ÃÂ´ÃÂµÃÂ½ÃÃÂ¸ÃÃÂ¸ÃÃÂ¸ÃÃÃÂ¹ ÃÂ»ÃÂ¸ÃÃÂ½ÃÂ¾ÃÃÃÂ¸ ÃÂ»ÃÃÂ´ÃÂµÃÂ¹ ÃÂ¸ ÃÂ½ÃÂµ ÃÂ¿ÃÂ¸ÃÃÂ¸ ÃÂ¸ÃÂ¼ÃÂµÃÂ½ÃÂ°, ÃÂµÃÃÂ»ÃÂ¸ ÃÂ¾ÃÂ½ÃÂ¸ ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÂ¿ÃÂµÃÃÂ°ÃÃÂ°ÃÂ½Ã ÃÂ½ÃÂ° ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂ¸."
)

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Heuristics / intent Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
_SMALLTALK_RE = re.compile(r"^(ÃÂ¿ÃÃÂ¸ÃÂ²ÃÂµÃ|ÃÂ·ÃÂ´ÃÃÂ°ÃÂ²ÃÃÃÂ²ÃÃÂ¹|ÃÂ´ÃÂ¾ÃÃÃÃÂ¹\s*(ÃÂ´ÃÂµÃÂ½Ã|ÃÂ²ÃÂµÃÃÂµÃ|ÃÃÃÃÂ¾)|ÃÃÂ¸|hi|hello|ÃÂºÃÂ°ÃÂº ÃÂ´ÃÂµÃÂ»ÃÂ°|ÃÃÂ¿ÃÂ°ÃÃÂ¸ÃÃÂ¾|ÃÂ¿ÃÂ¾ÃÂºÃÂ°)\b", re.I)
_NEWSY_RE     = re.compile(r"(ÃÂºÃÂ¾ÃÂ³ÃÂ´ÃÂ°|ÃÂ´ÃÂ°ÃÃÂ°|ÃÂ²ÃÃÂ¹ÃÂ´ÃÂµÃ|ÃÃÂµÃÂ»ÃÂ¸ÃÂ·|ÃÂ½ÃÂ¾ÃÂ²ÃÂ¾ÃÃ|ÃÂºÃÃÃ|ÃÃÂµÃÂ½ÃÂ°|ÃÂ¿ÃÃÂ¾ÃÂ³ÃÂ½ÃÂ¾ÃÂ·|ÃÂ½ÃÂ°ÃÂ¹ÃÂ´ÃÂ¸|ÃÂ¾ÃÃÂ¸ÃÃÂ¸ÃÂ°ÃÂ»|ÃÂ¿ÃÂ¾ÃÂ³ÃÂ¾ÃÂ´ÃÂ°|ÃÃÂµÃÂ³ÃÂ¾ÃÂ´ÃÂ½Ã|ÃÃÃÂµÃÂ½ÃÂ´|ÃÂ°ÃÂ´ÃÃÂµÃ|ÃÃÂµÃÂ»ÃÂµÃÃÂ¾ÃÂ½)", re.I)
_CAPABILITY_RE= re.compile(r"(ÃÂ¼ÃÂ¾ÃÂ¶(ÃÂµÃÃ|ÃÂ½ÃÂ¾|ÃÂµÃÃÂµ).{0,16}(ÃÂ°ÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÂ·|ÃÃÂ°ÃÃÂ¿ÃÂ¾ÃÂ·ÃÂ½|ÃÃÂ¸ÃÃÂ°ÃÃ|ÃÃÂ¾ÃÂ·ÃÂ´ÃÂ°(ÃÂ²ÃÂ°)?Ã|ÃÂ´ÃÂµÃÂ»ÃÂ°(ÃÃ)?).{0,24}(ÃÃÂ¾ÃÃÂ¾|ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂº|ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½|pdf|docx|epub|fb2|ÃÂ°ÃÃÂ´ÃÂ¸ÃÂ¾|ÃÂºÃÂ½ÃÂ¸ÃÂ³))", re.I)

_IMG_WORDS = r"(ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½\w+|ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½\w+|ÃÃÂ¾ÃÃÂ¾\w*|ÃÃÂ¸ÃÃÃÂ½ÃÂº\w+|image|picture|img\b|logo|banner|poster)"
_VID_WORDS = r"(ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾|ÃÃÂ¾ÃÂ»ÃÂ¸ÃÂº\w*|ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ°ÃÃÂ¸\w*|shorts?|reels?|clip|video|vid\b)"

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

_CREATE_CMD = r"(ÃÃÂ´ÃÂµÃÂ»ÃÂ°(ÃÂ¹|ÃÂ¹ÃÃÂµ)|ÃÃÂ¾ÃÂ·ÃÂ´ÃÂ°(ÃÂ¹|ÃÂ¹ÃÃÂµ)|ÃÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ¸ÃÃ(ÃÂ¹|ÃÂ¹ÃÃÂµ)|ÃÂ½ÃÂ°ÃÃÂ¸ÃÃ(ÃÂ¹|ÃÂ¹ÃÃÂµ)|render|generate|create|make)"
_PREFIXES_VIDEO = [r"^" + _CREATE_CMD + r"\s+ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾", r"^video\b", r"^reels?\b", r"^shorts?\b"]
_PREFIXES_IMAGE = [r"^" + _CREATE_CMD + r"\s+(?:ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½\w+|ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½\w+|ÃÃÂ¾ÃÃÂ¾\w+|ÃÃÂ¸ÃÃÃÂ½ÃÂº\w+)", r"^image\b", r"^picture\b", r"^img\b"]

def _strip_leading(s: str) -> str:
    return s.strip(" \n\t:Ã¢Ã¢-\"Ã¢Ã¢'ÃÂ«ÃÂ»,.()[]")

def _after_match(text: str, match) -> str:
    return _strip_leading(text[match.end():])

def _looks_like_capability_question(tl: str) -> bool:
    if "?" in tl and re.search(_CAPABILITY_RE, tl):
        if not re.search(_CREATE_CMD, tl, re.I):
            return True
    m = re.search(r"\b(ÃÃ|ÃÂ²Ã)?\s*ÃÂ¼ÃÂ¾ÃÂ¶(ÃÂµÃÃ|ÃÂ½ÃÂ¾|ÃÂµÃÃÂµ)\b", tl)
    if m and re.search(_CAPABILITY_RE, tl) and not re.search(_CREATE_CMD, tl, re.I):
        return True
    return False

def detect_media_intent(text: str):
    """
    ÃÃÃÃÂ°ÃÂµÃÂ¼ÃÃ ÃÂ¿ÃÂ¾ÃÂ½ÃÃÃ, ÃÂ¿ÃÃÂ¾ÃÃÂ¸Ã ÃÂ»ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃÂµÃÂ»Ã:
    - ÃÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÃÃÃÃ ("video")
    - ÃÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÃÃ ÃÂ¢ÃÃÃÃÂ£ ("image")
    ÃÃÂ¾ÃÂ·ÃÂ²ÃÃÂ°ÃÃÂ°ÃÂµÃÂ¼ ÃÂºÃÂ¾ÃÃÃÂµÃÂ¶ (mtype, rest), ÃÂ³ÃÂ´ÃÂµ:
        mtype Ã¢ {"video", "image", None}
        rest  Ã¢ ÃÂ¾ÃÃÂ¸ÃÃÂµÃÂ½ÃÂ½ÃÃÂ¹ ÃÂ¿ÃÃÂ¾ÃÂ¼ÃÂ¿Ã ÃÃÂµÃÂ· ÃÃÂ»ÃÃÂ¶ÃÂµÃÃÂ½ÃÃ ÃÃÂ»ÃÂ¾ÃÂ².
    """
    if not text:
        return (None, "")

    t = text.strip()
    tl = t.lower()

    # ÃÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃ "ÃÃÃÂ¾ ÃÃ ÃÃÂ¼ÃÂµÃÂµÃÃ?" ÃÂ¸ Ã.ÃÂ¿. ÃÃÃÂ°ÃÂ·Ã ÃÂ¾ÃÃÃÃÂ°ÃÃÃÂ²ÃÂ°ÃÂµÃÂ¼
    if _looks_like_capability_question(tl):
        return (None, "")

    # 1) ÃÂ¯ÃÂ²ÃÂ½ÃÃÂµ ÃÂ¿ÃÂ°ÃÃÃÂµÃÃÂ½Ã ÃÂ´ÃÂ»Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ (Ã ÃÃÃÃÃÂ¾ÃÂ¼ ÃÂ½ÃÂ¾ÃÂ²ÃÃ _PREFIXES_VIDEO)
    for p in _PREFIXES_VIDEO:
        m = re.search(p, tl, re.I)
        if m:
            return ("video", _after_match(t, m))

    # 2) ÃÂ¯ÃÂ²ÃÂ½ÃÃÂµ ÃÂ¿ÃÂ°ÃÃÃÂµÃÃÂ½Ã ÃÂ´ÃÂ»Ã ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂ¾ÃÂº (ÃÂ½ÃÂ¾ÃÂ²ÃÃÂµ _PREFIXES_IMAGE)
    for p in _PREFIXES_IMAGE:
        m = re.search(p, tl, re.I)
        if m:
            return ("image", _after_match(t, m))

    # 3) ÃÃÃÃÂ¸ÃÂ¹ ÃÃÂ»ÃÃÃÂ°ÃÂ¹: ÃÂµÃÃÂ»ÃÂ¸ ÃÂµÃÃÃ ÃÂ³ÃÂ»ÃÂ°ÃÂ³ÃÂ¾ÃÂ» ÃÂ¸ÃÂ· _CREATE_CMD
    #    ÃÂ¸ ÃÂ¾ÃÃÂ´ÃÂµÃÂ»ÃÃÂ½ÃÂ¾ ÃÃÂ»ÃÂ¾ÃÂ²ÃÂ° "ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾/ÃÃÂ¾ÃÂ»ÃÂ¸ÃÂº" ÃÂ¸ÃÂ»ÃÂ¸ "ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ°/ÃÃÂ¾ÃÃÂ¾/Ã¢Â¦"
    if re.search(_CREATE_CMD, tl, re.I):
        # --- ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ---
        if re.search(_VID_WORDS, tl, re.I):
            # ÃÂ²ÃÃÃÂµÃÂ·ÃÂ°ÃÂµÃÂ¼ "ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾/ÃÃÂ¾ÃÂ»ÃÂ¸ÃÂº" ÃÂ¸ ÃÂ³ÃÂ»ÃÂ°ÃÂ³ÃÂ¾ÃÂ» ÃÃ ÃÃ ÃÃÃÃÃÃÃÂ¬ÃÃÃ ÃÂ¡ÃÂ¢Ã ÃÃÃ t
            clean = re.sub(_VID_WORDS, "", t, flags=re.I)
            clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
            return ("video", _strip_leading(clean))

        # --- ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ¸ ---
        if re.search(_IMG_WORDS, tl, re.I):
            clean = re.sub(_IMG_WORDS, "", t, flags=re.I)
            clean = re.sub(_CREATE_CMD, "", clean, flags=re.I)
            return ("image", _strip_leading(clean))

    # 4) ÃÂ¡ÃÃÂ°ÃÃÃÂµ ÃÂºÃÂ¾ÃÃÂ¾ÃÃÂºÃÂ¸ÃÂµ ÃÃÂ¾ÃÃÂ¼ÃÂ°ÃÃ "img: ..." / "image: ..." / "picture: ..."
    m = re.match(r"^(img|image|picture)\s*[:\-]\s*(.+)$", tl)
    if m:
        # ÃÃÂµÃÃÃÂ¼ ÃÃÂ²ÃÂ¾ÃÃ ÃÃÂ¶ÃÂµ ÃÂ¸ÃÂ· ÃÂ¾ÃÃÂ¸ÃÂ³ÃÂ¸ÃÂ½ÃÂ°ÃÂ»ÃÃÂ½ÃÂ¾ÃÂ¹ ÃÃÃÃÂ¾ÃÂºÃÂ¸ t
        return ("image", _strip_leading(t[m.end(1) + 1:]))

    # 5) ÃÂ¡ÃÃÂ°ÃÃÃÂµ ÃÂºÃÂ¾ÃÃÂ¾ÃÃÂºÃÂ¸ÃÂµ ÃÃÂ¾ÃÃÂ¼ÃÂ°ÃÃ "video: ..." / "reels: ..." / "shorts: ..."
    m = re.match(r"^(video|vid|reels?|shorts?)\s*[:\-]\s*(.+)$", tl)
    if m:
        return ("video", _strip_leading(t[m.end(1) + 1:]))

    # ÃÃÂ¸ÃÃÂµÃÂ³ÃÂ¾ ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÃÂ»ÃÂ¸ Ã¢ ÃÂ¾ÃÃÃÃÂ½ÃÃÂ¹ ÃÃÂµÃÂºÃÃ
    return (None, "")
# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ OpenAI helpers Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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
    ÃÂ£ÃÂ½ÃÂ¸ÃÂ²ÃÂµÃÃÃÂ°ÃÂ»ÃÃÂ½ÃÃÂ¹ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã ÃÂº LLM:
    - ÃÂ¿ÃÂ¾ÃÂ´ÃÂ´ÃÂµÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ°ÃÂµÃ OpenRouter (ÃÃÂµÃÃÂµÃÂ· OPENAI_API_KEY = sk-or-...);
    - ÃÂ¿ÃÃÂ¸ÃÂ½ÃÃÂ´ÃÂ¸ÃÃÂµÃÂ»ÃÃÂ½ÃÂ¾ ÃÃÂ»ÃÃ JSON ÃÂ² UTF-8, ÃÃÃÂ¾ÃÃ ÃÂ½ÃÂµ ÃÃÃÂ»ÃÂ¾ ascii-ÃÂ¾ÃÃÂ¸ÃÃÂ¾ÃÂº;
    - ÃÂ»ÃÂ¾ÃÂ³ÃÂ¸ÃÃÃÂµÃ HTTP-ÃÃÃÂ°ÃÃÃ ÃÂ¸ ÃÃÂµÃÂ»ÃÂ¾ ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ¸ ÃÂ² Render-ÃÂ»ÃÂ¾ÃÂ³ÃÂ¸;
    - ÃÂ´ÃÂµÃÂ»ÃÂ°ÃÂµÃ ÃÂ´ÃÂ¾ 3 ÃÂ¿ÃÂ¾ÃÂ¿ÃÃÃÂ¾ÃÂº Ã ÃÂ½ÃÂµÃÃÂ¾ÃÂ»ÃÃÃÂ¾ÃÂ¹ ÃÂ¿ÃÂ°ÃÃÂ·ÃÂ¾ÃÂ¹.
    """
    user_text = (user_text or "").strip()
    if not user_text:
        return "ÃÃÃÃÃÂ¾ÃÂ¹ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã."

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({
            "role": "system",
            "content": f"ÃÃÂ¾ÃÂ½ÃÃÂµÃÂºÃÃ ÃÂ¸ÃÂ· ÃÂ²ÃÂµÃ-ÃÂ¿ÃÂ¾ÃÂ¸ÃÃÂºÃÂ°:\n{web_ctx}",
        })
    messages.append({"role": "user", "content": user_text})

    # Ã¢Ã¢ ÃÃÂ°ÃÂ·ÃÂ¾ÃÂ²ÃÃÂ¹ URL Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
    # ÃÃÃÂ»ÃÂ¸ ÃÂºÃÂ»ÃÃ ÃÂ¾Ã OpenRouter ÃÂ¸ÃÂ»ÃÂ¸ TEXT_PROVIDER=openrouter Ã¢ ÃÃÂ»ÃÃÂ¼ ÃÂ½ÃÂ° OpenRouter
    provider = (TEXT_PROVIDER or "").strip().lower()
    if OPENAI_API_KEY.startswith("sk-or-") or provider == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
    else:
        base_url = (OPENAI_BASE_URL or "").strip() or "https://api.openai.com/v1"

    # Ã¢Ã¢ ÃÃÂ°ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÂ²ÃÂºÃÂ¸ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept-Charset": "utf-8",
    }

    # ÃÂ¡ÃÂ»ÃÃÂ¶ÃÂµÃÃÂ½ÃÃÂµ ÃÂ·ÃÂ°ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÂ²ÃÂºÃÂ¸ OpenRouter
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

            # ÃÃÂ¾ÃÂ³ÃÂ¸ÃÃÃÂµÃÂ¼ ÃÂ²ÃÃ, ÃÃÃÂ¾ ÃÂ½ÃÂµ 2xx
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
        "Ã¢ Ã¯Â¸ ÃÂ¡ÃÂµÃÂ¹ÃÃÂ°Ã ÃÂ½ÃÂµ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂ¸ÃÂ»ÃÂ¾ÃÃ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂ¸ÃÃ ÃÂ¾ÃÃÂ²ÃÂµÃ ÃÂ¾Ã ÃÂ¼ÃÂ¾ÃÂ´ÃÂµÃÂ»ÃÂ¸. "
        "ÃÂ¯ ÃÂ½ÃÂ° ÃÃÂ²ÃÃÂ·ÃÂ¸ Ã¢ ÃÂ¿ÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃÃÂ¹ ÃÂ¿ÃÂµÃÃÂµÃÃÂ¾ÃÃÂ¼ÃÃÂ»ÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ²ÃÃÂ¾ÃÃÂ¸ÃÃ ÃÃÃÃ ÃÂ¿ÃÂ¾ÃÂ·ÃÂ¶ÃÂµ."
    )
    

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Gemini (ÃÃÂµÃÃÂµÃÂ· CometAPI, ÃÂ¾ÃÂ¿ÃÃÂ¸ÃÂ¾ÃÂ½ÃÂ°ÃÂ»ÃÃÂ½ÃÂ¾) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

GEMINI_API_KEY   = (os.environ.get("GEMINI_API_KEY", "").strip() or COMETAPI_KEY)
GEMINI_BASE_URL  = os.environ.get("GEMINI_BASE_URL", "https://api.cometapi.com").strip().rstrip("/")
GEMINI_CHAT_PATH = os.environ.get("GEMINI_CHAT_PATH", "/gemini/v1/chat").strip()
GEMINI_MODEL     = os.environ.get("GEMINI_MODEL", "gemini-1.5-pro").strip()

async def ask_gemini_text(user_text: str) -> str:
    """
    ÃÃÂ¸ÃÂ½ÃÂ¸ÃÂ¼ÃÂ°ÃÂ»ÃÃÂ½ÃÂ°Ã ÃÂ¸ÃÂ½ÃÃÂµÃÂ³ÃÃÂ°ÃÃÂ¸Ã Gemini ÃÃÂµÃÃÂµÃÂ· CometAPI (ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ»ÃÃÃÂ¾ÃÂ¹ ÃÃÂ¾ÃÂ²ÃÂ¼ÃÂµÃÃÃÂ¸ÃÂ¼ÃÃÂ¹ ÃÂ¿ÃÃÂ¾ÃÂºÃÃÂ¸).
    ÃÃÃÂ»ÃÂ¸ ÃÃÂ½ÃÂ´ÃÂ¿ÃÂ¾ÃÂ¸ÃÂ½Ã ÃÂ¾ÃÃÂ»ÃÂ¸ÃÃÂ°ÃÂµÃÃÃ Ã¢ ÃÂ¿ÃÂ¾ÃÂ¿ÃÃÂ°ÃÂ²Ã GEMINI_CHAT_PATH/GEMINI_BASE_URL ÃÂ² ENV.
    """
    if not GEMINI_API_KEY:
        return "Ã¢ Ã¯Â¸ Gemini: ÃÂ½ÃÂµ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÂ½ GEMINI_API_KEY/COMETAPI_KEY. ÃÃÂ¾ÃÃÂ°ÃÂ²ÃÃÃÂµ ÃÂºÃÂ»ÃÃ ÃÂ² Environment."
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
            return "Ã¢ Ã¯Â¸ Gemini: ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ° ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾ÃÃÂ°. ÃÃÃÂ¾ÃÂ²ÃÂµÃÃÃÃÂµ GEMINI_CHAT_PATH/BASE_URL ÃÂ¸ ÃÂºÃÂ»ÃÃ."
        js = r.json()
        # ÃÃÃÃÂ°ÃÂµÃÂ¼ÃÃ ÃÂ²ÃÃÃÂ°ÃÃÂ¸ÃÃ ÃÃÂµÃÂºÃÃ ÃÂ¸ÃÂ· ÃÃÂ°ÃÂ·ÃÂ½ÃÃ ÃÃÃÂµÃÂ¼ ÃÂ¾ÃÃÂ²ÃÂµÃÃÂ¾ÃÂ²
        for k in ("text", "output", "result", "content", "message"):
            v = js.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # ÃÃÂ½ÃÂ¾ÃÂ³ÃÂ´ÃÂ° ÃÂ¾ÃÃÂ²ÃÂµÃ ÃÃÃÂ²ÃÂ°ÃÂµÃ ÃÂ²ÃÂ¸ÃÂ´ÃÂ° {"choices":[{"message":{"content":"..."}}]}
        ch = js.get("choices")
        if isinstance(ch, list) and ch:
            msg = (ch[0].get("message") or {})
            cont = msg.get("content")
            if isinstance(cont, str) and cont.strip():
                return cont.strip()
        return "Ã¢ Ã¯Â¸ Gemini: ÃÂ¾ÃÃÂ²ÃÂµÃ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂµÃÂ½, ÃÂ½ÃÂ¾ ÃÃÂ¾ÃÃÂ¼ÃÂ°Ã ÃÂ½ÃÂµ ÃÃÂ°ÃÃÂ¿ÃÂ¾ÃÂ·ÃÂ½ÃÂ°ÃÂ½. ÃÂ¡ÃÂ¼ÃÂ¾ÃÃÃÂ¸ÃÃÂµ ÃÂ»ÃÂ¾ÃÂ³ÃÂ¸."
    except Exception as e:
        log.exception("Gemini request error: %s", e)
        return "Ã¢ Ã¯Â¸ Gemini: ÃÂ¸ÃÃÂºÃÂ»ÃÃÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ¿ÃÃÂ¸ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾ÃÃÂµ. ÃÂ¡ÃÂ¼ÃÂ¾ÃÃÃÂ¸ÃÃÂµ ÃÂ»ÃÂ¾ÃÂ³ÃÂ¸."

async def ask_openai_vision(user_text: str, img_b64: str, mime: str) -> str:
    try:
        prompt = (user_text or "ÃÃÂ¿ÃÂ¸ÃÃÂ¸, ÃÃÃÂ¾ ÃÂ½ÃÂ° ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂ¸ ÃÂ¸ ÃÂºÃÂ°ÃÂºÃÂ¾ÃÂ¹ ÃÃÂ°ÃÂ¼ ÃÃÂµÃÂºÃÃ.").strip()
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
        return "ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ¿ÃÃÂ¾ÃÂ°ÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÂ·ÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂµ."


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃÂµÃÂ»ÃÃÃÂºÃÂ¸ÃÂµ ÃÂ½ÃÂ°ÃÃÃÃÂ¾ÃÂ¹ÃÂºÃÂ¸ (TTS) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ°ÃÂ´ÃÃÂ¶ÃÂ½ÃÃÂ¹ TTS ÃÃÂµÃÃÂµÃÂ· REST (OGG/Opus) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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
            "format": "ogg"  # OGG/Opus ÃÂ´ÃÂ»Ã Telegram voice
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
                f"Ã° ÃÃÂ·ÃÂ²ÃÃÃÂºÃÂ° ÃÂ²ÃÃÂºÃÂ»ÃÃÃÂµÃÂ½ÃÂ° ÃÂ´ÃÂ»Ã ÃÃÃÂ¾ÃÂ³ÃÂ¾ ÃÃÂ¾ÃÂ¾ÃÃÃÂµÃÂ½ÃÂ¸Ã: ÃÃÂµÃÂºÃÃ ÃÂ´ÃÂ»ÃÂ¸ÃÂ½ÃÂ½ÃÂµÃÂµ {TTS_MAX_CHARS} ÃÃÂ¸ÃÂ¼ÃÂ²ÃÂ¾ÃÂ»ÃÂ¾ÃÂ²."
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
                await update.effective_message.reply_text("Ã° ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂ¸ÃÂ½ÃÃÂµÃÂ·ÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾Ã.")
            return
        bio = BytesIO(audio); bio.seek(0); bio.name = "say.ogg"
        await update.effective_message.reply_voice(voice=InputFile(bio), caption=text)
    except Exception as e:
        log.exception("maybe_tts_reply error: %s", e)

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, True)
    await update.effective_message.reply_text(f"Ã° ÃÃÂ·ÃÂ²ÃÃÃÂºÃÂ° ÃÂ²ÃÂºÃÂ»ÃÃÃÂµÃÂ½ÃÂ°. ÃÃÂ¸ÃÂ¼ÃÂ¸Ã {TTS_MAX_CHARS} ÃÃÂ¸ÃÂ¼ÃÂ²ÃÂ¾ÃÂ»ÃÂ¾ÃÂ² ÃÂ½ÃÂ° ÃÂ¾ÃÃÂ²ÃÂµÃ.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, False)
    await update.effective_message.reply_text("Ã° ÃÃÂ·ÃÂ²ÃÃÃÂºÃÂ° ÃÂ²ÃÃÂºÃÂ»ÃÃÃÂµÃÂ½ÃÂ°.")

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Speech-to-Text (STT) Ã¢Â¢ OpenAI Whisper/4o-mini-transcribe Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÂ¥ÃÂµÃÂ½ÃÂ´ÃÂ»ÃÂµÃ ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃÂ¾ÃÂ²ÃÃ/ÃÂ°ÃÃÂ´ÃÂ¸ÃÂ¾ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    voice = getattr(msg, "voice", None)
    audio = getattr(msg, "audio", None)
    media = voice or audio
    if not media:
        await msg.reply_text("ÃÃÂµ ÃÂ½ÃÂ°ÃÃÃÂ» ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾ÃÂ¹ ÃÃÂ°ÃÂ¹ÃÂ».")
        return

    # ÃÂ¡ÃÂºÃÂ°ÃÃÂ¸ÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÃÂ°ÃÂ¹ÃÂ»
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
        await msg.reply_text("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂºÃÂ°ÃÃÂ°ÃÃ ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾ÃÂµ ÃÃÂ¾ÃÂ¾ÃÃÃÂµÃÂ½ÃÂ¸ÃÂµ.")
        return

    # STT
    transcript = await _stt_transcribe_bytes(filename, raw)
    if not transcript:
        await msg.reply_text("ÃÃÃÂ¸ÃÃÂºÃÂ° ÃÂ¿ÃÃÂ¸ ÃÃÂ°ÃÃÂ¿ÃÂ¾ÃÂ·ÃÂ½ÃÂ°ÃÂ²ÃÂ°ÃÂ½ÃÂ¸ÃÂ¸ ÃÃÂµÃÃÂ¸.")
        return

    transcript = transcript.strip()

    # ÃÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÃÂµÃÂºÃÃ ÃÂ´ÃÂ»Ã ÃÂ¾ÃÃÂ»ÃÂ°ÃÂ´ÃÂºÃÂ¸
    with contextlib.suppress(Exception):
        await msg.reply_text(f"Ã°Â£Ã¯Â¸ Ã ÃÂ°ÃÃÂ¿ÃÂ¾ÃÂ·ÃÂ½ÃÂ°ÃÂ»: {transcript}")

    # Ã¢Ã¢Ã¢ ÃÃÃÂ®ÃÂ§ÃÃÃÃ ÃÃÃÃÃÃÂ¢ Ã¢Ã¢Ã¢
    # ÃÃÂ¾ÃÂ»ÃÃÃÂµ ÃÃ ÃÃÂ¾ÃÂ·ÃÂ´ÃÂ°ÃÃÂ¼ ÃÃÂµÃÂ¹ÃÂºÃÂ¾ÃÂ²ÃÃÂ¹ Update, ÃÂ½ÃÂµ ÃÂ»ÃÂµÃÂ·ÃÂµÃÂ¼ ÃÂ² Message.text Ã¢ ÃÃÃÂ¾ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂµÃÃÂµÃÂ½ÃÂ¾ ÃÂ² Telegram API
    # ÃÂ¢ÃÂµÃÂ¿ÃÂµÃÃ ÃÂ¼Ã ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÂ¼ ÃÃÂµÃÂ·ÃÂ¾ÃÂ¿ÃÂ°ÃÃÂ½ÃÃÂ¹ ÃÂ¿ÃÃÂ¾ÃÂºÃÃÂ¸-ÃÂ¼ÃÂµÃÃÂ¾ÃÂ´, ÃÂºÃÂ¾ÃÃÂ¾ÃÃÃÂ¹ ÃÃÂ¾ÃÂ·ÃÂ´ÃÂ°ÃÃ ÃÂ²ÃÃÂµÃÂ¼ÃÂµÃÂ½ÃÂ½ÃÃÂ¹ message-ÃÂ¾ÃÃÃÂµÃÂºÃ
    try:
        await on_text_with_text(update, context, transcript)
    except Exception as e:
        log.exception("Voice->text handler error: %s", e)
        await msg.reply_text("ÃÂ£ÃÂ¿Ã, ÃÂ¿ÃÃÂ¾ÃÂ¸ÃÂ·ÃÂ¾ÃÃÂ»ÃÂ° ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ°. ÃÂ¯ ÃÃÂ¶ÃÂµ ÃÃÂ°ÃÂ·ÃÃÂ¸ÃÃÂ°ÃÃÃ.")
        
# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂµÃÂºÃÃÃÂ° ÃÂ¸ÃÂ· ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃÂ¾ÃÂ² Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÂ¡ÃÃÂ¼ÃÂ¼ÃÂ°ÃÃÂ¸ÃÂ·ÃÂ°ÃÃÂ¸Ã ÃÂ´ÃÂ»ÃÂ¸ÃÂ½ÃÂ½ÃÃ ÃÃÂµÃÂºÃÃÃÂ¾ÃÂ² Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def _summarize_chunk(text: str, query: str | None = None) -> str:
    prefix = "ÃÂ¡ÃÃÂ¼ÃÂ¼ÃÂ¸ÃÃÃÂ¹ ÃÂºÃÃÂ°ÃÃÂºÃÂ¾ ÃÂ¿ÃÂ¾ ÃÂ¿ÃÃÂ½ÃÂºÃÃÂ°ÃÂ¼ ÃÂ¾ÃÃÂ½ÃÂ¾ÃÂ²ÃÂ½ÃÂ¾ÃÂµ ÃÂ¸ÃÂ· ÃÃÃÂ°ÃÂ³ÃÂ¼ÃÂµÃÂ½ÃÃÂ° ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃÂ° ÃÂ½ÃÂ° ÃÃÃÃÃÂºÃÂ¾ÃÂ¼:\n"
    if query:
        prefix = (f"ÃÂ¡ÃÃÂ¼ÃÂ¼ÃÂ¸ÃÃÃÂ¹ ÃÃÃÂ°ÃÂ³ÃÂ¼ÃÂµÃÂ½Ã Ã ÃÃÃÃÃÂ¾ÃÂ¼ ÃÃÂµÃÂ»ÃÂ¸: {query}\n"
                  f"ÃÃÂ°ÃÂ¹ ÃÂ¾ÃÃÂ½ÃÂ¾ÃÂ²ÃÂ½ÃÃÂµ ÃÃÂµÃÂ·ÃÂ¸ÃÃ, ÃÃÂ°ÃÂºÃÃ, ÃÃÂ¸ÃÃÃ. Ã ÃÃÃÃÂºÃÂ¸ÃÂ¹ ÃÃÂ·ÃÃÂº.\n")
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
    combined = "\n\n".join(f"- ÃÂ¤ÃÃÂ°ÃÂ³ÃÂ¼ÃÂµÃÂ½Ã {idx+1}:\n{s}" for idx, s in enumerate(partials))
    final_prompt = ("ÃÃÃÃÂµÃÂ´ÃÂ¸ÃÂ½ÃÂ¸ ÃÃÂµÃÂ·ÃÂ¸ÃÃ ÃÂ¿ÃÂ¾ ÃÃÃÂ°ÃÂ³ÃÂ¼ÃÂµÃÂ½ÃÃÂ°ÃÂ¼ ÃÂ² ÃÃÂµÃÂ»ÃÃÂ½ÃÂ¾ÃÂµ ÃÃÂµÃÂ·ÃÃÂ¼ÃÂµ ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃÂ°: 1) 5Ã¢10 ÃÂ³ÃÂ»ÃÂ°ÃÂ²ÃÂ½ÃÃ ÃÂ¿ÃÃÂ½ÃÂºÃÃÂ¾ÃÂ²; "
                    "2) ÃÂºÃÂ»ÃÃÃÂµÃÂ²ÃÃÂµ ÃÃÂ¸ÃÃÃ/ÃÃÃÂ¾ÃÂºÃÂ¸; 3) ÃÂ²ÃÃÂ²ÃÂ¾ÃÂ´/ÃÃÂµÃÂºÃÂ¾ÃÂ¼ÃÂµÃÂ½ÃÂ´ÃÂ°ÃÃÂ¸ÃÂ¸. Ã ÃÃÃÃÂºÃÂ¸ÃÂ¹ ÃÃÂ·ÃÃÂº.\n\n" + combined)
    return await ask_openai_text(final_prompt)


# ======= ÃÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÂ· ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃÂ¾ÃÂ² (PDF/EPUB/DOCX/FB2/TXT) =======
async def on_doc_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document:
            return
        doc = update.message.document
        tg_file = await doc.get_file()
        data = await tg_file.download_as_bytearray()
        text, kind = extract_text_from_document(bytes(data), doc.file_name or "file")
        if not text.strip():
            await update.effective_message.reply_text(f"ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ¸ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃ ÃÃÂµÃÂºÃÃ ÃÂ¸ÃÂ· {kind}.")
            return
        goal = (update.message.caption or "").strip() or None
        await update.effective_message.reply_text(f"Ã° ÃÃÂ·ÃÂ²ÃÂ»ÃÂµÃÂºÃÂ°Ã ÃÃÂµÃÂºÃÃ ({kind}), ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ»Ã ÃÂºÃÂ¾ÃÂ½ÃÃÂ¿ÃÂµÃÂºÃÃ¢Â¦")
        summary = await summarize_long_text(text, query=goal)
        summary = summary or "ÃÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾."
        await update.effective_message.reply_text(summary)
        await maybe_tts_reply(update, context, summary[:TTS_MAX_CHARS])
    except Exception as e:
        log.exception("on_doc_analyze error: %s", e)
    # ÃÂ½ÃÂ¸ÃÃÂµÃÂ³ÃÂ¾ ÃÂ½ÃÂµ ÃÃÃÂ¾ÃÃÂ°ÃÂµÃÂ¼ ÃÂ½ÃÂ°ÃÃÃÂ¶Ã

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ OpenAI Images (ÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ°ÃÃÂ¸Ã ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂ¾ÃÂº) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def _do_img_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
        b64 = resp.data[0].b64_json
        img_bytes = base64.b64decode(b64)
        await update.effective_message.reply_photo(photo=img_bytes, caption=f"ÃÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾ Ã¢\nÃÃÂ°ÃÂ¿ÃÃÂ¾Ã: {prompt}")
    except Exception as e:
        log.exception("IMG gen error: %s", e)
        await update.effective_message.reply_text("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂ¾ÃÂ·ÃÂ´ÃÂ°ÃÃ ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂµ.")

async def _luma_generate_image_bytes(prompt: str) -> bytes | None:
    if not LUMA_IMG_BASE_URL or not LUMA_API_KEY:
        # ÃÃÂ¾ÃÂ»ÃÃÃÂº: OpenAI Images
        try:
            resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
            return base64.b64decode(resp.data[0].b64_json)
        except Exception as e:
            log.exception("OpenAI images fallback error: %s", e)
            return None
    try:
        # ÃÃÃÂ¸ÃÂ¼ÃÂµÃÃÂ½ÃÃÂ¹ ÃÃÂ½ÃÂ´ÃÂ¿ÃÂ¾ÃÂ¸ÃÂ½Ã; ÃÂµÃÃÂ»ÃÂ¸ Ã ÃÃÂµÃÃ ÃÂ´ÃÃÃÂ³ÃÂ¾ÃÂ¹ Ã¢ ÃÂ·ÃÂ°ÃÂ¼ÃÂµÃÂ½ÃÂ¸ path/ÃÂ¿ÃÂ¾ÃÂ»Ã ÃÂ¿ÃÂ¾ÃÂ´ ÃÃÂ²ÃÂ¾ÃÂ¹ ÃÂ°ÃÂºÃÂºÃÂ°ÃÃÂ½Ã.
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
            await update.effective_message.reply_text("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂ¾ÃÂ·ÃÂ´ÃÂ°ÃÃ ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂµ.")
            return
        await update.effective_message.reply_photo(photo=img, caption=f"Ã° ÃÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾ Ã¢\nÃÃÂ°ÃÂ¿ÃÃÂ¾Ã: {prompt}")
    await _try_pay_then_do(update, context, update.effective_user.id, "img", IMG_COST_USD, _go,
                           remember_kind="luma_img", remember_payload={"prompt": prompt})


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ UI / ÃÃÂµÃÂºÃÃÃ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
START_TEXT = (
    "ÃÃÃÂ¸ÃÂ²ÃÂµÃ! ÃÂ¯ ÃÃÂµÃÂ¹ÃÃÂ¾-Bot Ã¢ Ã¢Â¡Ã¯Â¸ ÃÂ¼ÃÃÂ»ÃÃÃÂ¸ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ÃÂ½ÃÃÂ¹ ÃÃÂ¾Ã ÃÂ¸ÃÂ· 7 ÃÂ½ÃÂµÃÂ¹ÃÃÂ¾ÃÃÂµÃÃÂµÃÂ¹ ÃÂ´ÃÂ»Ã Ã° ÃÃÃÃÃ, Ã°Â¼ ÃÃÂ°ÃÃÂ¾ÃÃ ÃÂ¸ Ã°Â¥ ÃÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸ÃÂ¹.\n"
    "ÃÂ¯ ÃÃÂ¼ÃÂµÃ ÃÃÂ°ÃÃÂ¾ÃÃÂ°ÃÃ ÃÂ³ÃÂ¸ÃÃÃÂ¸ÃÂ´ÃÂ½ÃÂ¾: ÃÂ¼ÃÂ¾ÃÂ³Ã ÃÃÂ°ÃÂ¼ ÃÂ²ÃÃÃÃÂ°ÃÃ ÃÂ»ÃÃÃÃÂ¸ÃÂ¹ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº ÃÂ¿ÃÂ¾ÃÂ´ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃ ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ´ÃÂ°ÃÃ ÃÃÂµÃÃÂµ ÃÂ²ÃÃÃÃÂ°ÃÃ ÃÂ²ÃÃÃÃÂ½ÃÃ. Ã°Â¤Ã°Â§ \n"
    "\n"
    "Ã¢Â¨ ÃÃÂ»ÃÂ°ÃÂ²ÃÂ½ÃÃÂµ ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼Ã:\n"
    "\n"
    "\n"
    "Ã¢Â¢ Ã° ÃÂ£ÃÃÃÃÂ° Ã¢ ÃÂ¾ÃÃÃÃÃÂ½ÃÂµÃÂ½ÃÂ¸Ã Ã ÃÂ¿ÃÃÂ¸ÃÂ¼ÃÂµÃÃÂ°ÃÂ¼ÃÂ¸, ÃÂ¿ÃÂ¾ÃÃÂ°ÃÂ³ÃÂ¾ÃÂ²ÃÃÂµ ÃÃÂµÃÃÂµÃÂ½ÃÂ¸Ã ÃÂ·ÃÂ°ÃÂ´ÃÂ°Ã, ÃÃÃÃÂµ/ÃÃÂµÃÃÂµÃÃÂ°Ã/ÃÂ´ÃÂ¾ÃÂºÃÂ»ÃÂ°ÃÂ´, ÃÂ¼ÃÂ¸ÃÂ½ÃÂ¸-ÃÂºÃÂ²ÃÂ¸ÃÂ·Ã.\n"
    "Ã° ÃÂ¢ÃÂ°ÃÂºÃÂ¶ÃÂµ: ÃÃÂ°ÃÂ·ÃÃÂ¾Ã ÃÃÃÂµÃÃÂ½ÃÃ PDF/ÃÃÂ»ÃÂµÃÂºÃÃÃÂ¾ÃÂ½ÃÂ½ÃÃ ÃÂºÃÂ½ÃÂ¸ÃÂ³, ÃÃÂ¿ÃÂ°ÃÃÂ³ÃÂ°ÃÂ»ÃÂºÃÂ¸ ÃÂ¸ ÃÂºÃÂ¾ÃÂ½ÃÃÂ¿ÃÂµÃÂºÃÃ, ÃÂºÃÂ¾ÃÂ½ÃÃÃÃÃÂºÃÃÂ¾Ã ÃÃÂµÃÃÃÂ¾ÃÂ²;\n"
    "Ã°Â§ ÃÃÂ°ÃÂ¹ÃÂ¼-ÃÂºÃÂ¾ÃÂ´Ã ÃÂ¿ÃÂ¾ ÃÂ°ÃÃÂ´ÃÂ¸ÃÂ¾ÃÂºÃÂ½ÃÂ¸ÃÂ³ÃÂ°ÃÂ¼/ÃÂ»ÃÂµÃÂºÃÃÂ¸ÃÃÂ¼ ÃÂ¸ ÃÂºÃÃÂ°ÃÃÂºÃÂ¸ÃÂµ ÃÂ²ÃÃÂ¶ÃÂ¸ÃÂ¼ÃÂºÃÂ¸. Ã°Â§Â©\n"
    "\n"
    "Ã¢Â¢ Ã°Â¼ Ã ÃÂ°ÃÃÂ¾ÃÃÂ° Ã¢ ÃÂ¿ÃÂ¸ÃÃÃÂ¼ÃÂ°/ÃÃÃÂ¸ÃÃ/ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃ, ÃÂ°ÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÃÂ¸ÃÂºÃÂ° ÃÂ¸ ÃÃÂµÃÂ·ÃÃÂ¼ÃÂµ ÃÂ¼ÃÂ°ÃÃÂµÃÃÂ¸ÃÂ°ÃÂ»ÃÂ¾ÃÂ², ToDo/ÃÂ¿ÃÂ»ÃÂ°ÃÂ½Ã, ÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ°ÃÃÂ¾Ã ÃÂ¸ÃÂ´ÃÂµÃÂ¹.\n"
    "Ã° Ã¯Â¸ ÃÃÂ»Ã ÃÂ°ÃÃÃÂ¸ÃÃÂµÃÂºÃÃÂ¾ÃÃÂ°/ÃÂ´ÃÂ¸ÃÂ·ÃÂ°ÃÂ¹ÃÂ½ÃÂµÃÃÂ°/ÃÂ¿ÃÃÂ¾ÃÂµÃÂºÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÃÂ¸ÃÂºÃÂ°: ÃÃÃÃÃÂºÃÃÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ¸ÃÂµ ÃÂ¢Ã, ÃÃÂµÃÂº-ÃÂ»ÃÂ¸ÃÃÃ ÃÃÃÂ°ÃÂ´ÃÂ¸ÃÂ¹,\n"
    "Ã°Ã¯Â¸ ÃÂ½ÃÂ°ÃÂ·ÃÂ²ÃÂ°ÃÂ½ÃÂ¸Ã/ÃÂ¾ÃÂ¿ÃÂ¸ÃÃÂ°ÃÂ½ÃÂ¸Ã ÃÂ»ÃÂ¸ÃÃÃÂ¾ÃÂ², ÃÃÂ²ÃÂ¾ÃÂ´ÃÂ½ÃÃÂµ ÃÃÂ°ÃÃÂ»ÃÂ¸ÃÃ ÃÂ¸ÃÂ· ÃÃÂµÃÂºÃÃÃÂ¾ÃÂ², ÃÂ¾ÃÃÂ¾ÃÃÂ¼ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ¿ÃÂ¾ÃÃÃÂ½ÃÂ¸ÃÃÂµÃÂ»ÃÃÂ½ÃÃ ÃÂ·ÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¾ÃÂº. Ã°\n"
    "\n"
    "Ã¢Â¢ Ã°Â¥ Ã ÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸Ã Ã¢ ÃÃÂ¾ÃÃÂ¾-ÃÂ¼ÃÂ°ÃÃÃÂµÃÃÃÂºÃÂ°Ã (ÃÃÂ´ÃÂ°ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ/ÃÂ·ÃÂ°ÃÂ¼ÃÂµÃÂ½ÃÂ° ÃÃÂ¾ÃÂ½ÃÂ°, ÃÂ´ÃÂ¾ÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÂºÃÂ°, outpaint), ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÃÂ°ÃÃÃ ÃÃÂ¾ÃÃÂ¾,\n"
    "Ã°Â¬ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÂ¿ÃÂ¾ ÃÃÂµÃÂºÃÃÃ/ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃ, ÃÂ¸ÃÂ´ÃÂµÃÂ¸ ÃÂ¸ ÃÃÂ¾ÃÃÂ¼ÃÂ°ÃÃ ÃÂ´ÃÂ»Ã Reels/Shorts, ÃÂ°ÃÂ²ÃÃÂ¾-ÃÂ½ÃÂ°ÃÃÂµÃÂ·ÃÂºÃÂ° ÃÂ¸ÃÂ· ÃÂ´ÃÂ»ÃÂ¸ÃÂ½ÃÂ½ÃÃ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾\n"
    "(ÃÃÃÂµÃÂ½ÃÂ°ÃÃÂ¸ÃÂ¹/ÃÃÂ°ÃÂ¹ÃÂ¼-ÃÂºÃÂ¾ÃÂ´Ã), ÃÂ¼ÃÂµÃÂ¼Ã/ÃÂºÃÂ²ÃÂ¸ÃÂ·Ã. Ã°Â¼Ã¯Â¸Ã°Âª\n"
    "\n"
    "Ã°Â§Â­ ÃÃÂ°ÃÂº ÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃÃÃ:\n"
    "ÃÂ¿ÃÃÂ¾ÃÃÃÂ¾ ÃÂ²ÃÃÃÂµÃÃÂ¸ ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ ÃÂºÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ¾ÃÂ¹ ÃÂ½ÃÂ¸ÃÂ¶ÃÂµ ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ½ÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã Ã¢ Ã ÃÃÂ°ÃÂ¼ ÃÂ¾ÃÂ¿ÃÃÂµÃÂ´ÃÂµÃÂ»Ã ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃ ÃÂ¸ ÃÂ¿ÃÃÂµÃÂ´ÃÂ»ÃÂ¾ÃÂ¶Ã ÃÂ²ÃÂ°ÃÃÂ¸ÃÂ°ÃÂ½ÃÃ. Ã¢Ã¯Â¸Ã¢Â¨\n"
    "\n"
    "Ã°Â§  ÃÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ° ÃÂ«ÃÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸ÃÂ»:\n"
    "ÃÂ´ÃÂ»Ã ÃÃÂ¾ÃÃÂ½ÃÂ¾ÃÂ³ÃÂ¾ ÃÂ²ÃÃÃÂ¾ÃÃÂ°, ÃÂºÃÂ°ÃÂºÃÃ ÃÂ½ÃÂµÃÂ¹ÃÃÂ¾ÃÃÂµÃÃ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÂ¿ÃÃÂ¸ÃÂ½ÃÃÂ´ÃÂ¸ÃÃÂµÃÂ»ÃÃÂ½ÃÂ¾. Ã°Â¯Ã°Â¤"
)

def engines_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Ã°Â¬ GPT (ÃÃÂµÃÂºÃÃ/ÃÃÂ¾ÃÃÂ¾/ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃ)", callback_data="engine:gpt")],
        [InlineKeyboardButton("Ã°Â¼ Images (OpenAI)",             callback_data="engine:images")],
        [InlineKeyboardButton("Ã° Kling Ã¢ ÃÂºÃÂ»ÃÂ¸ÃÂ¿Ã / ÃÃÂ¾ÃÃÃ",       callback_data="engine:kling")],
        [InlineKeyboardButton("Ã°Â¬ Luma Ã¢ ÃÂºÃÂ¾ÃÃÂ¾ÃÃÂºÃÂ¸ÃÂµ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾",       callback_data="engine:luma")],
        [InlineKeyboardButton("Ã°Â¥ Runway Ã¢ ÃÂ¿ÃÃÂµÃÂ¼ÃÂ¸ÃÃÂ¼-ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾",      callback_data="engine:runway")],
        [InlineKeyboardButton("Ã°Â¬ Sora Ã¢ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ (Comet)",        callback_data="engine:sora")],
        [InlineKeyboardButton("Ã°Â§  Gemini (Comet)",             callback_data="engine:gemini")],
        [InlineKeyboardButton("Ã°Âµ Suno (music)",               callback_data="engine:suno")],
        [InlineKeyboardButton("Ã°Â¨ Midjourney (ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã)",    callback_data="engine:midjourney")],
        [InlineKeyboardButton("Ã°Â£ STT/TTS Ã¢ ÃÃÂµÃÃÃ¢ÃÃÂµÃÂºÃÃ",        callback_data="engine:stt_tts")],
    ])
# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ MODES (ÃÂ£ÃÃÃÃÂ° / Ã ÃÂ°ÃÃÂ¾ÃÃÂ° / Ã ÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸Ã) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackQueryHandler, MessageHandler, filters

# ÃÂ¢ÃÂµÃÂºÃÃ ÃÂºÃÂ¾ÃÃÂ½ÃÂµÃÂ²ÃÂ¾ÃÂ³ÃÂ¾ ÃÂ¼ÃÂµÃÂ½Ã ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ÃÂ¾ÃÂ²
def _modes_root_text() -> str:
    return (
        "ÃÃÃÃÂµÃÃÂ¸ÃÃÂµ ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ ÃÃÂ°ÃÃÂ¾ÃÃ. Ã ÃÂºÃÂ°ÃÂ¶ÃÂ´ÃÂ¾ÃÂ¼ ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ÃÂµ ÃÃÂ¾Ã ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃ ÃÂ³ÃÂ¸ÃÃÃÂ¸ÃÂ´ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¾ÃÂ²:\n"
        "Ã¢Â¢ GPT-5 (ÃÃÂµÃÂºÃÃ/ÃÂ»ÃÂ¾ÃÂ³ÃÂ¸ÃÂºÃÂ°) + Vision (ÃÃÂ¾ÃÃÂ¾) + STT/TTS (ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾Ã)\n"
        "Ã¢Â¢ Luma/Runway Ã¢ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾, Midjourney Ã¢ ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã\n\n"
        "ÃÃÂ¾ÃÂ¶ÃÂµÃÃÂµ ÃÃÂ°ÃÂºÃÂ¶ÃÂµ ÃÂ¿ÃÃÂ¾ÃÃÃÂ¾ ÃÂ½ÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ°ÃÃ ÃÃÂ²ÃÂ¾ÃÃÂ¾ÃÂ´ÃÂ½ÃÃÂ¹ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã Ã¢ ÃÃÂ¾Ã ÃÂ¿ÃÂ¾ÃÂ¹ÃÂ¼ÃÃ."
    )

def modes_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Ã° ÃÂ£ÃÃÃÃÂ°", callback_data="mode:study"),
            InlineKeyboardButton("Ã°Â¼ Ã ÃÂ°ÃÃÂ¾ÃÃÂ°", callback_data="mode:work"),
            InlineKeyboardButton("Ã°Â¥ Ã ÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸Ã", callback_data="mode:fun"),
        ],
    ])

# Ã¢Ã¢ ÃÃÂ¿ÃÂ¸ÃÃÂ°ÃÂ½ÃÂ¸ÃÂµ ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ¼ÃÂµÃÂ½Ã ÃÂ¿ÃÂ¾ ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ÃÂ°ÃÂ¼
def _mode_desc(key: str) -> str:
    if key == "study":
        return (
            "Ã° *ÃÂ£ÃÃÃÃÂ°*\n"
            "ÃÃÂ¸ÃÃÃÂ¸ÃÂ´: GPT-5 ÃÂ´ÃÂ»Ã ÃÂ¾ÃÃÃÃÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂ¹/ÃÂºÃÂ¾ÃÂ½ÃÃÂ¿ÃÂµÃÂºÃÃÂ¾ÃÂ², Vision ÃÂ´ÃÂ»Ã ÃÃÂ¾ÃÃÂ¾-ÃÂ·ÃÂ°ÃÂ´ÃÂ°Ã, "
            "STT/TTS ÃÂ´ÃÂ»Ã ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃÂ¾ÃÂ²ÃÃ, + Midjourney (ÃÂ¸ÃÂ»ÃÂ»ÃÃÃÃÃÂ°ÃÃÂ¸ÃÂ¸) ÃÂ¸ Luma/Runway (ÃÃÃÂµÃÃÂ½ÃÃÂµ ÃÃÂ¾ÃÂ»ÃÂ¸ÃÂºÃÂ¸).\n\n"
            "ÃÃÃÃÃÃÃÂµ ÃÂ´ÃÂµÃÂ¹ÃÃÃÂ²ÃÂ¸Ã ÃÂ½ÃÂ¸ÃÂ¶ÃÂµ. ÃÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ ÃÂ½ÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ°ÃÃ ÃÃÂ²ÃÂ¾ÃÃÂ¾ÃÂ´ÃÂ½ÃÃÂ¹ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã (ÃÂ½ÃÂ°ÃÂ¿ÃÃÂ¸ÃÂ¼ÃÂµÃ: "
            "ÃÂ«ÃÃÂ´ÃÂµÃÂ»ÃÂ°ÃÂ¹ ÃÂºÃÂ¾ÃÂ½ÃÃÂ¿ÃÂµÃÂºÃ ÃÂ¸ÃÂ· PDFÃÂ», ÃÂ«ÃÂ¾ÃÃÃÃÃÂ½ÃÂ¸ ÃÂ¸ÃÂ½ÃÃÂµÃÂ³ÃÃÂ°ÃÂ»Ã Ã ÃÂ¿ÃÃÂ¸ÃÂ¼ÃÂµÃÃÂ°ÃÂ¼ÃÂ¸ÃÂ»)."
        )
    if key == "work":
        return (
            "Ã°Â¼ *Ã ÃÂ°ÃÃÂ¾ÃÃÂ°*\n"
            "ÃÃÂ¸ÃÃÃÂ¸ÃÂ´: GPT-5 (ÃÃÂµÃÂ·ÃÃÂ¼ÃÂµ/ÃÂ¿ÃÂ¸ÃÃÃÂ¼ÃÂ°/ÃÂ°ÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÃÂ¸ÃÂºÃÂ°), Vision (ÃÃÂ°ÃÃÂ»ÃÂ¸ÃÃ/ÃÃÂºÃÃÂ¸ÃÂ½Ã), "
            "STT/TTS (ÃÂ´ÃÂ¸ÃÂºÃÃÂ¾ÃÂ²ÃÂºÃÂ°/ÃÂ¾ÃÂ·ÃÂ²ÃÃÃÂºÃÂ°), + Midjourney (ÃÂ²ÃÂ¸ÃÂ·ÃÃÂ°ÃÂ»Ã), Luma/Runway (ÃÂ¿ÃÃÂµÃÂ·ÃÂµÃÂ½ÃÃÂ°ÃÃÂ¸ÃÂ¾ÃÂ½ÃÂ½ÃÃÂµ ÃÃÂ¾ÃÂ»ÃÂ¸ÃÂºÃÂ¸).\n\n"
            "ÃÃÃÃÃÃÃÂµ ÃÂ´ÃÂµÃÂ¹ÃÃÃÂ²ÃÂ¸Ã ÃÂ½ÃÂ¸ÃÂ¶ÃÂµ. ÃÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ ÃÂ½ÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ°ÃÃ ÃÃÂ²ÃÂ¾ÃÃÂ¾ÃÂ´ÃÂ½ÃÃÂ¹ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã (ÃÂ½ÃÂ°ÃÂ¿ÃÃÂ¸ÃÂ¼ÃÂµÃ: "
            "ÃÂ«ÃÂ°ÃÂ´ÃÂ°ÃÂ¿ÃÃÂ¸ÃÃÃÂ¹ ÃÃÂµÃÂ·ÃÃÂ¼ÃÂµ ÃÂ¿ÃÂ¾ÃÂ´ ÃÂ²ÃÂ°ÃÂºÃÂ°ÃÂ½ÃÃÂ¸Ã PMÃÂ», ÃÂ«ÃÂ½ÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ°ÃÃ ÃÂºÃÂ¾ÃÂ¼ÃÂ¼ÃÂµÃÃÃÂµÃÃÂºÃÂ¾ÃÂµ ÃÂ¿ÃÃÂµÃÂ´ÃÂ»ÃÂ¾ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂµÃÂ»)."
        )
    if key == "fun":
        return (
            "Ã°Â¥ *Ã ÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸Ã*\n"
            "ÃÃÂ¸ÃÃÃÂ¸ÃÂ´: GPT-5 (ÃÂ¸ÃÂ´ÃÂµÃÂ¸, ÃÃÃÂµÃÂ½ÃÂ°ÃÃÂ¸ÃÂ¸), Midjourney (ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ¸), Luma/Runway (ÃÃÂ¾ÃÃÃ/ÃÃÂ¸ÃÂµÃÂ»ÃÃ), "
            "STT/TTS (ÃÂ¾ÃÂ·ÃÂ²ÃÃÃÂºÃÂ°). ÃÃÃ ÃÂ´ÃÂ»Ã ÃÃÃÃÃÃÃ ÃÃÂ²ÃÂ¾ÃÃÃÂµÃÃÂºÃÂ¸Ã ÃÃÃÃÂº.\n\n"
            "ÃÃÃÃÃÃÃÂµ ÃÂ´ÃÂµÃÂ¹ÃÃÃÂ²ÃÂ¸Ã ÃÂ½ÃÂ¸ÃÂ¶ÃÂµ. ÃÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ ÃÂ½ÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ°ÃÃ ÃÃÂ²ÃÂ¾ÃÃÂ¾ÃÂ´ÃÂ½ÃÃÂ¹ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã (ÃÂ½ÃÂ°ÃÂ¿ÃÃÂ¸ÃÂ¼ÃÂµÃ: "
            "ÃÂ«ÃÃÂ´ÃÂµÃÂ»ÃÂ°ÃÂ¹ ÃÃÃÂµÃÂ½ÃÂ°ÃÃÂ¸ÃÂ¹ 30-ÃÃÂµÃÂº ÃÃÂ¾ÃÃÃÂ° ÃÂ¿ÃÃÂ¾ ÃÂºÃÂ¾ÃÃÂ°-ÃÃÂ°ÃÃÂ¸ÃÃÃÂ°ÃÂ»)."
        )
    return "Ã ÃÂµÃÂ¶ÃÂ¸ÃÂ¼ ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÂ¹ÃÂ´ÃÂµÃÂ½."

def _mode_kb(key: str) -> InlineKeyboardMarkup:
    if key == "study":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("Ã° ÃÃÂ¾ÃÂ½ÃÃÂ¿ÃÂµÃÂºÃ ÃÂ¸ÃÂ· PDF/EPUB/DOCX", callback_data="act:study:pdf_summary")],
            [InlineKeyboardButton("Ã° ÃÃÃÃÃÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂµÃÂ¼Ã",            callback_data="act:study:explain"),
             InlineKeyboardButton("Ã°Â§Â® Ã ÃÂµÃÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ·ÃÂ°ÃÂ´ÃÂ°Ã",              callback_data="act:study:tasks")],
            [InlineKeyboardButton("Ã¢Ã¯Â¸ ÃÂ­ÃÃÃÂµ/ÃÃÂµÃÃÂµÃÃÂ°Ã/ÃÂ´ÃÂ¾ÃÂºÃÂ»ÃÂ°ÃÂ´",       callback_data="act:study:essay"),
             InlineKeyboardButton("Ã° ÃÃÂ»ÃÂ°ÃÂ½ ÃÂº ÃÃÂºÃÂ·ÃÂ°ÃÂ¼ÃÂµÃÂ½Ã",           callback_data="act:study:exam_plan")],
            [
                InlineKeyboardButton("Ã°Â¬ Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("Ã°Â¨ Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("Ã°Â£ STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("Ã° ÃÂ¡ÃÂ²ÃÂ¾ÃÃÂ¾ÃÂ´ÃÂ½ÃÃÂ¹ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã", callback_data="act:free")],
            [InlineKeyboardButton("Ã¢Â¬Ã¯Â¸ ÃÃÂ°ÃÂ·ÃÂ°ÃÂ´", callback_data="mode:root")],
        ])

    if key == "work":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("Ã° ÃÃÂ¸ÃÃÃÂ¼ÃÂ¾/ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½Ã",            callback_data="act:work:doc"),
             InlineKeyboardButton("Ã° ÃÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÃÂ¸ÃÂºÃÂ°/ÃÃÂ²ÃÂ¾ÃÂ´ÃÂºÃÂ°",           callback_data="act:work:report")],
            [InlineKeyboardButton("Ã° ÃÃÂ»ÃÂ°ÃÂ½/ToDo",                  callback_data="act:work:plan"),
             InlineKeyboardButton("Ã°Â¡ ÃÃÂ´ÃÂµÃÂ¸/ÃÃÃÂ¸Ã",                 callback_data="act:work:idea")],
            [
                InlineKeyboardButton("Ã°Â¬ Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("Ã°Â¨ Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("Ã°Â£ STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("Ã° ÃÂ¡ÃÂ²ÃÂ¾ÃÃÂ¾ÃÂ´ÃÂ½ÃÃÂ¹ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã", callback_data="act:free")],
            [InlineKeyboardButton("Ã¢Â¬Ã¯Â¸ ÃÃÂ°ÃÂ·ÃÂ°ÃÂ´", callback_data="mode:root")],
        ])

    if key == "fun":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("Ã°Â­ ÃÃÂ´ÃÂµÃÂ¸ ÃÂ´ÃÂ»Ã ÃÂ´ÃÂ¾ÃÃÃÂ³ÃÂ°",             callback_data="act:fun:ideas")],
            [InlineKeyboardButton("Ã°Â¬ ÃÂ¡ÃÃÂµÃÂ½ÃÂ°ÃÃÂ¸ÃÂ¹ ÃÃÂ¾ÃÃÃÂ°",              callback_data="act:fun:shorts")],
            [InlineKeyboardButton("Ã°Â® ÃÃÂ³ÃÃ/ÃÂºÃÂ²ÃÂ¸ÃÂ·",                   callback_data="act:fun:games")],
            [
                InlineKeyboardButton("Ã°Â¬ Runway",       callback_data="act:open:runway"),
                InlineKeyboardButton("Ã°Â¨ Midjourney",   callback_data="act:open:mj"),
                InlineKeyboardButton("Ã°Â£ STT/TTS",      callback_data="act:open:voice"),
            ],
            [InlineKeyboardButton("Ã° ÃÂ¡ÃÂ²ÃÂ¾ÃÃÂ¾ÃÂ´ÃÂ½ÃÃÂ¹ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã", callback_data="act:free")],
            [InlineKeyboardButton("Ã¢Â¬Ã¯Â¸ ÃÃÂ°ÃÂ·ÃÂ°ÃÂ´", callback_data="mode:root")],
        ])

    return modes_root_kb()

# ÃÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÂ°ÃÃ ÃÂ²ÃÃÃÃÂ°ÃÂ½ÃÂ½ÃÃÂ¹ ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ (ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÃÃ ÃÂ¸ ÃÂ´ÃÂ»Ã callback, ÃÂ¸ ÃÂ´ÃÂ»Ã ÃÃÂµÃÂºÃÃÃÂ°)
async def _send_mode_menu(update, context, key: str):
    text = _mode_desc(key)
    kb = _mode_kb(key)
    # ÃÃÃÂ»ÃÂ¸ ÃÂ¿ÃÃÂ¸ÃÃÂ»ÃÂ¸ ÃÂ¸ÃÂ· callback Ã¢ ÃÃÂµÃÂ´ÃÂ°ÃÂºÃÃÂ¸ÃÃÃÂµÃÂ¼; ÃÂµÃÃÂ»ÃÂ¸ ÃÃÂµÃÂºÃÃÃÂ¾ÃÂ¼ Ã¢ ÃÃÂ»ÃÃÂ¼ ÃÂ½ÃÂ¾ÃÂ²ÃÃÂ¼ ÃÃÂ¾ÃÂ¾ÃÃÃÂµÃÂ½ÃÂ¸ÃÂµÃÂ¼
    if getattr(update, "callback_query", None):
        q = update.callback_query
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        await q.answer()
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# ÃÃÃÃÂ°ÃÃÂ¾ÃÃÃÂ¸ÃÂº callback ÃÂ¿ÃÂ¾ ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ÃÂ°ÃÂ¼
async def on_mode_cb(update, context):
    q = update.callback_query
    data = (q.data or "").strip()
    uid = q.from_user.id

    # ÃÃÂ°ÃÂ²ÃÂ¸ÃÂ³ÃÂ°ÃÃÂ¸Ã
    if data == "mode:root":
        await q.edit_message_text(_modes_root_text(), reply_markup=modes_root_kb())
        await q.answer(); return

    if data.startswith("mode:"):
        _, key = data.split(":", 1)
        await _send_mode_menu(update, context, key)
        return

    # ÃÂ¡ÃÂ²ÃÂ¾ÃÃÂ¾ÃÂ´ÃÂ½ÃÃÂ¹ ÃÂ²ÃÂ²ÃÂ¾ÃÂ´ ÃÂ¸ÃÂ· ÃÂ¿ÃÂ¾ÃÂ´ÃÂ¼ÃÂµÃÂ½Ã
    if data == "act:free":
        await q.answer()
        await q.edit_message_text(
            "Ã° ÃÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ÃÃÂµ ÃÃÂ²ÃÂ¾ÃÃÂ¾ÃÂ´ÃÂ½ÃÃÂ¹ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã ÃÂ½ÃÂ¸ÃÂ¶ÃÂµ ÃÃÂµÃÂºÃÃÃÂ¾ÃÂ¼ ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃÂ¾ÃÂ¼ Ã¢ Ã ÃÂ¿ÃÂ¾ÃÂ´ÃÃÃÃÂ¾ÃÃÃ.",
            reply_markup=modes_root_kb(),
        )
        return

    # === ÃÂ£ÃÃÃÃÂ°
    if data == "act:study:pdf_summary":
        await q.answer()
        _mode_track_set(uid, "pdf_summary")
        await q.edit_message_text(
            "Ã° ÃÃÃÂ¸ÃÃÂ»ÃÂ¸ÃÃÂµ PDF/EPUB/DOCX/FB2/TXT Ã¢ ÃÃÂ´ÃÂµÃÂ»ÃÂ°Ã ÃÃÃÃÃÂºÃÃÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ½ÃÃÂ¹ ÃÂºÃÂ¾ÃÂ½ÃÃÂ¿ÃÂµÃÂºÃ.\n"
            "ÃÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ ÃÂ² ÃÂ¿ÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂ¸ ÃÃÂºÃÂ°ÃÂ·ÃÂ°ÃÃ ÃÃÂµÃÂ»Ã (ÃÂºÃÂ¾ÃÃÂ¾ÃÃÂºÃÂ¾/ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂ¾ÃÃÂ½ÃÂ¾, ÃÃÂ·ÃÃÂº ÃÂ¸ Ã.ÃÂ¿.).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:explain":
        await q.answer()
        study_sub_set(uid, "explain")
        _mode_track_set(uid, "explain")
        await q.edit_message_text(
            "Ã° ÃÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ÃÃÂµ ÃÃÂµÃÂ¼Ã + ÃÃÃÂ¾ÃÂ²ÃÂµÃÂ½Ã (ÃÃÂºÃÂ¾ÃÂ»ÃÂ°/ÃÂ²ÃÃÂ·/ÃÂ¿ÃÃÂ¾ÃÃÂ¸). ÃÃÃÂ´ÃÂµÃ ÃÂ¾ÃÃÃÃÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ Ã ÃÂ¿ÃÃÂ¸ÃÂ¼ÃÂµÃÃÂ°ÃÂ¼ÃÂ¸.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:tasks":
        await q.answer()
        study_sub_set(uid, "tasks")
        _mode_track_set(uid, "tasks")
        await q.edit_message_text(
            "Ã°Â§Â® ÃÃÃÂ¸ÃÃÂ»ÃÂ¸ÃÃÂµ ÃÃÃÂ»ÃÂ¾ÃÂ²ÃÂ¸ÃÂµ(Ã) Ã¢ ÃÃÂµÃÃ ÃÂ¿ÃÂ¾ÃÃÂ°ÃÂ³ÃÂ¾ÃÂ²ÃÂ¾ (ÃÃÂ¾ÃÃÂ¼ÃÃÂ»Ã, ÃÂ¿ÃÂ¾ÃÃÃÂ½ÃÂµÃÂ½ÃÂ¸Ã, ÃÂ¸ÃÃÂ¾ÃÂ³).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:essay":
        await q.answer()
        study_sub_set(uid, "essay")
        _mode_track_set(uid, "essay")
        await q.edit_message_text(
            "Ã¢Ã¯Â¸ ÃÂ¢ÃÂµÃÂ¼ÃÂ° + ÃÃÃÂµÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ¸Ã (ÃÂ¾ÃÃÃÃÂ¼/ÃÃÃÂ¸ÃÂ»Ã/ÃÃÂ·ÃÃÂº) Ã¢ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ»Ã ÃÃÃÃÂµ/ÃÃÂµÃÃÂµÃÃÂ°Ã.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:exam_plan":
        await q.answer()
        study_sub_set(uid, "quiz")
        _mode_track_set(uid, "exam_plan")
        await q.edit_message_text(
            "Ã° ÃÂ£ÃÂºÃÂ°ÃÂ¶ÃÂ¸ÃÃÂµ ÃÂ¿ÃÃÂµÃÂ´ÃÂ¼ÃÂµÃ ÃÂ¸ ÃÂ´ÃÂ°ÃÃ ÃÃÂºÃÂ·ÃÂ°ÃÂ¼ÃÂµÃÂ½ÃÂ° Ã¢ ÃÃÂ¾ÃÃÃÂ°ÃÂ²ÃÂ»Ã ÃÂ¿ÃÂ»ÃÂ°ÃÂ½ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂºÃÂ¸ Ã ÃÂ²ÃÂµÃÃÂ°ÃÂ¼ÃÂ¸.",
            reply_markup=_mode_kb("study"),
        )
        return

    # === Ã ÃÂ°ÃÃÂ¾ÃÃÂ°
    if data == "act:work:doc":
        await q.answer()
        _mode_track_set(uid, "work_doc")
        await q.edit_message_text(
            "Ã° ÃÂ§ÃÃÂ¾ ÃÂ·ÃÂ° ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½Ã/ÃÂ°ÃÂ´ÃÃÂµÃÃÂ°Ã/ÃÂºÃÂ¾ÃÂ½ÃÃÂµÃÂºÃÃ? ÃÂ¡ÃÃÂ¾ÃÃÂ¼ÃÂ¸ÃÃÃ ÃÃÂµÃÃÂ½ÃÂ¾ÃÂ²ÃÂ¸ÃÂº ÃÂ¿ÃÂ¸ÃÃÃÂ¼ÃÂ°/ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃÂ°.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:report":
        await q.answer()
        _mode_track_set(uid, "work_report")
        await q.edit_message_text(
            "Ã° ÃÃÃÂ¸ÃÃÂ»ÃÂ¸ÃÃÂµ ÃÃÂµÃÂºÃÃ/ÃÃÂ°ÃÂ¹ÃÂ»/ÃÃÃÃÂ»ÃÂºÃ Ã¢ ÃÃÂ´ÃÂµÃÂ»ÃÂ°Ã ÃÂ°ÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÃÂ¸ÃÃÂµÃÃÂºÃÃ ÃÂ²ÃÃÂ¶ÃÂ¸ÃÂ¼ÃÂºÃ.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:plan":
        await q.answer()
        _mode_track_set(uid, "work_plan")
        await q.edit_message_text(
            "Ã° ÃÃÂ¿ÃÂ¸ÃÃÂ¸ÃÃÂµ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃ/ÃÃÃÂ¾ÃÂºÃÂ¸ Ã¢ ÃÃÂ¾ÃÃÂµÃÃ ToDo/ÃÂ¿ÃÂ»ÃÂ°ÃÂ½ ÃÃÂ¾ ÃÃÃÂ¾ÃÂºÃÂ°ÃÂ¼ÃÂ¸ ÃÂ¸ ÃÂ¿ÃÃÂ¸ÃÂ¾ÃÃÂ¸ÃÃÂµÃÃÂ°ÃÂ¼ÃÂ¸.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:idea":
        await q.answer()
        _mode_track_set(uid, "work_idea")
        await q.edit_message_text(
            "Ã°Â¡ Ã ÃÂ°ÃÃÃÂºÃÂ°ÃÂ¶ÃÂ¸ÃÃÂµ ÃÂ¿ÃÃÂ¾ÃÂ´ÃÃÂºÃ/ÃÂ¦Ã/ÃÂºÃÂ°ÃÂ½ÃÂ°ÃÂ»Ã Ã¢ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ»Ã ÃÃÃÂ¸Ã/ÃÂ¸ÃÂ´ÃÂµÃÂ¸.",
            reply_markup=_mode_kb("work"),
        )
        return

    # === Ã ÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸Ã (ÃÂºÃÂ°ÃÂº ÃÃÃÂ»ÃÂ¾)
    if data == "act:fun:ideas":
        await q.answer()
        await q.edit_message_text(
            "Ã°Â¥ ÃÃÃÃÂµÃÃÂµÃÂ¼ ÃÃÂ¾ÃÃÂ¼ÃÂ°Ã: ÃÂ´ÃÂ¾ÃÂ¼/ÃÃÂ»ÃÂ¸ÃÃÂ°/ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ´/ÃÂ² ÃÂ¿ÃÂ¾ÃÂµÃÂ·ÃÂ´ÃÂºÃÂµ. ÃÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ÃÃÂµ ÃÃÃÂ´ÃÂ¶ÃÂµÃ/ÃÂ½ÃÂ°ÃÃÃÃÂ¾ÃÂµÃÂ½ÃÂ¸ÃÂµ.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:shorts":
        await q.answer()
        await q.edit_message_text(
            "Ã°Â¬ ÃÂ¢ÃÂµÃÂ¼ÃÂ°, ÃÂ´ÃÂ»ÃÂ¸ÃÃÂµÃÂ»ÃÃÂ½ÃÂ¾ÃÃÃ (15Ã¢30 ÃÃÂµÃÂº), ÃÃÃÂ¸ÃÂ»Ã Ã¢ ÃÃÂ´ÃÂµÃÂ»ÃÂ°Ã ÃÃÃÂµÃÂ½ÃÂ°ÃÃÂ¸ÃÂ¹ ÃÃÂ¾ÃÃÃÂ° + ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂºÃÂ°ÃÂ·ÃÂºÃÂ¸ ÃÂ´ÃÂ»Ã ÃÂ¾ÃÂ·ÃÂ²ÃÃÃÂºÃÂ¸.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:games":
        await q.answer()
        await q.edit_message_text(
            "Ã°Â® ÃÂ¢ÃÂµÃÂ¼ÃÂ°ÃÃÂ¸ÃÂºÃÂ° ÃÂºÃÂ²ÃÂ¸ÃÂ·ÃÂ°/ÃÂ¸ÃÂ³ÃÃ? ÃÂ¡ÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ¸ÃÃÃ ÃÃÃÃÃÃÃ ÃÂ²ÃÂ¸ÃÂºÃÃÂ¾ÃÃÂ¸ÃÂ½Ã ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ¼ÃÂ¸ÃÂ½ÃÂ¸-ÃÂ¸ÃÂ³ÃÃ ÃÂ² ÃÃÂ°ÃÃÂµ.",
            reply_markup=_mode_kb("fun"),
        )
        return

    # === ÃÃÂ¾ÃÂ´ÃÃÂ»ÃÂ¸ (ÃÂºÃÂ°ÃÂº ÃÃÃÂ»ÃÂ¾)
    if data == "act:open:runway":
        await q.answer()
        await q.edit_message_text(
            "Ã°Â¬ ÃÃÂ¾ÃÂ´ÃÃÂ»Ã Runway: ÃÂ¿ÃÃÂ¸ÃÃÂ»ÃÂ¸ÃÃÂµ ÃÂ¸ÃÂ´ÃÂµÃ/ÃÃÂµÃÃÂµÃÃÂµÃÂ½Ã Ã¢ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ»Ã ÃÂ¿ÃÃÂ¾ÃÂ¼ÃÂ¿Ã ÃÂ¸ ÃÃÃÂ´ÃÂ¶ÃÂµÃ.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:mj":
        await q.answer()
        await q.edit_message_text(
            "Ã°Â¨ ÃÃÂ¾ÃÂ´ÃÃÂ»Ã Midjourney: ÃÂ¾ÃÂ¿ÃÂ¸ÃÃÂ¸ÃÃÂµ ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃ Ã¢ ÃÂ¿ÃÃÂµÃÂ´ÃÂ»ÃÂ¾ÃÂ¶Ã 3 ÃÂ¿ÃÃÂ¾ÃÂ¼ÃÂ¿ÃÃÂ° ÃÂ¸ ÃÃÂµÃÃÂºÃ ÃÃÃÂ¸ÃÂ»ÃÂµÃÂ¹.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:voice":
        await q.answer()
        await q.edit_message_text(
            "Ã°Â£ ÃÃÂ¾ÃÂ»ÃÂ¾Ã: /voice_on Ã¢ ÃÂ¾ÃÂ·ÃÂ²ÃÃÃÂºÃÂ° ÃÂ¾ÃÃÂ²ÃÂµÃÃÂ¾ÃÂ², /voice_off Ã¢ ÃÂ²ÃÃÂºÃÂ»ÃÃÃÂ¸ÃÃ. "
            "ÃÃÂ¾ÃÂ¶ÃÂµÃÃÂµ ÃÂ¿ÃÃÂ¸ÃÃÂ»ÃÂ°ÃÃ ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾ÃÂµ Ã¢ ÃÃÂ°ÃÃÂ¿ÃÂ¾ÃÂ·ÃÂ½ÃÂ°Ã ÃÂ¸ ÃÂ¾ÃÃÂ²ÃÂµÃÃ.",
            reply_markup=modes_root_kb(),
        )
        return

    await q.answer()

# Fallback Ã¢ ÃÂµÃÃÂ»ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃÂµÃÂ»Ã ÃÂ½ÃÂ°ÃÂ¶ÃÂ¼ÃÃ ÃÂ«ÃÂ£ÃÃÃÃÂ°/Ã ÃÂ°ÃÃÂ¾ÃÃÂ°/Ã ÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸ÃÃÂ» ÃÂ¾ÃÃÃÃÂ½ÃÂ¾ÃÂ¹ ÃÂºÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ¾ÃÂ¹/ÃÃÂµÃÂºÃÃÃÂ¾ÃÂ¼
async def on_mode_text(update, context):
    text = (update.effective_message.text or "").strip().lower()
    mapping = {
        "ÃÃÃÃÃÂ°": "study", "ÃÃÃÂµÃÃÂ°": "study",
        "ÃÃÂ°ÃÃÂ¾ÃÃÂ°": "work",
        "ÃÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸Ã": "fun", "ÃÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸ÃÂµ": "fun",
    }
    key = mapping.get(text)
    if key:
        await _send_mode_menu(update, context, key)
        
def main_keyboard(user_id: int | None = None) -> ReplyKeyboardMarkup:
    """
    ÃÃÂ»ÃÂ°ÃÂ²ÃÂ½ÃÂ°Ã ReplyKeyboard, ÃÂ»ÃÂ¾ÃÂºÃÂ°ÃÂ»ÃÂ¸ÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ½ÃÂ°Ã ÃÂ¿ÃÂ¾ÃÂ´ ÃÃÂ·ÃÃÂº ÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃÂµÃÂ»Ã.
    ÃÃÃÂ»ÃÂ¸ user_id ÃÂ½ÃÂµ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÂ½ Ã¢ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÂ¼ RU.
    """
    uid = int(user_id) if user_id is not None else 0
    # ÃÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ¸ ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ÃÂ¾ÃÂ² (ÃÃÂ¼ÃÂ¾ÃÂ´ÃÂ·ÃÂ¸ ÃÂ¾ÃÃÃÂ°ÃÂ²ÃÂ»ÃÃÂµÃÂ¼ ÃÂ´ÃÂ»Ã ÃÃÂ·ÃÂ½ÃÂ°ÃÂ²ÃÂ°ÃÂµÃÂ¼ÃÂ¾ÃÃÃÂ¸)
    # ÃÃÂ¾ÃÂºÃÂ°ÃÂ»ÃÂ¸ÃÂ·ÃÂ°ÃÃÂ¸Ã Ã¢ ÃÃÂµÃÃÂµÃÂ· I18N (ÃÂ¼ÃÂ¸ÃÂ½ÃÂ¸ÃÂ¼ÃÂ°ÃÂ»ÃÃÂ½ÃÃÂ¹ ÃÂ½ÃÂ°ÃÃÂ¾Ã ÃÃÃÃÂ¾ÃÂº).
    try:
        study = t(uid, "btn_study")
        work  = t(uid, "btn_work")
        fun   = t(uid, "btn_fun")
    except Exception:
        study, work, fun = "Ã° ÃÂ£ÃÃÃÃÂ°", "Ã°Â¼ Ã ÃÂ°ÃÃÂ¾ÃÃÂ°", "Ã°Â¥ Ã ÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸Ã"

    try:
        engines = t(uid, "btn_engines")
        subhelp = t(uid, "btn_sub")
        wallet  = t(uid, "btn_wallet")
    except Exception:
        engines, subhelp, wallet = "Ã°Â§  ÃÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸", "Ã¢Â­ ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° ÃÂ· ÃÃÂ¾ÃÂ¼ÃÂ¾ÃÃ", "Ã°Â§Â¾ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã"

    placeholder = t(uid, "input_placeholder") if "input_placeholder" in (I18N.get(get_lang(uid), {}) or {}) else "ÃÃÃÃÂµÃÃÂ¸ÃÃÂµ ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ½ÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ÃÃÂµ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾ÃÃ¢Â¦"

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

# RU-ÃÂºÃÂ»ÃÂ°ÃÂ²ÃÂ¸ÃÂ°ÃÃÃÃÂ° ÃÂ¿ÃÂ¾ ÃÃÂ¼ÃÂ¾ÃÂ»ÃÃÂ°ÃÂ½ÃÂ¸Ã (ÃÂ½ÃÂ° ÃÃÂ»ÃÃÃÂ°ÃÂ¹ ÃÃÂµÃÂ´ÃÂºÃÂ¸Ã ÃÂ¼ÃÂµÃÃ ÃÃÂµÃÂ· user_id)
main_kb = main_keyboard(0)

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ /start Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def _send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ÃÃÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÂºÃÂ° ÃÂ³ÃÂ»ÃÂ°ÃÂ²ÃÂ½ÃÂ¾ÃÂ³ÃÂ¾ ÃÂ¼ÃÂµÃÂ½Ã (ÃÂ¿ÃÂ¾ÃÃÂ»ÃÂµ ÃÂ²ÃÃÃÂ¾ÃÃÂ° ÃÃÂ·ÃÃÂºÃÂ° ÃÂ¸ ÃÂ² ÃÂ´ÃÃÃÂ³ÃÂ¸Ã ÃÂ¼ÃÂµÃÃÃÂ°Ã).
    """
    uid = update.effective_user.id
    # ÃÃÂ°ÃÂ½ÃÂ½ÃÂµÃ (ÃÂµÃÃÂ»ÃÂ¸ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÂ½)
    welcome_url = kv_get("welcome_url", BANNER_URL)
    if welcome_url:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_photo(welcome_url)

    # ÃÃÂ¾ÃÃÂ¾ÃÃÂºÃÂ¾ÃÂµ ÃÂ¿ÃÃÂ¸ÃÂ²ÃÂµÃÃÃÃÂ²ÃÂ¸ÃÂµ ÃÂ½ÃÂ° ÃÂ²ÃÃÃÃÂ°ÃÂ½ÃÂ½ÃÂ¾ÃÂ¼ ÃÃÂ·ÃÃÂºÃÂµ
    text = _tr(uid, "welcome")
    with contextlib.suppress(Exception):
        await update.effective_message.reply_text(
            text,
            reply_markup=main_keyboard(uid),
            disable_web_page_preview=True,
        )

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ /start Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ÃÂ¢ÃÃÂµÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ¸ÃÂµ: ÃÂ²ÃÃÃÂ¾Ã ÃÃÂ·ÃÃÂºÃÂ° ÃÂ¿ÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÂ¿ÃÃÂ¸ ÃÂºÃÂ°ÃÂ¶ÃÂ´ÃÂ¾ÃÂ¼ ÃÂ½ÃÂ¾ÃÂ²ÃÂ¾ÃÂ¼ /start (ÃÂ½ÃÂµ ÃÃÂ¾ÃÂ»ÃÃÂºÃÂ¾ ÃÂ¿ÃÂµÃÃÂ²ÃÃÂ¹ ÃÃÂ°ÃÂ·).
    ÃÃÂµÃÂ½Ã ÃÂ¿ÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÂ¿ÃÂ¾ÃÃÂ»ÃÂµ ÃÂ½ÃÂ°ÃÂ¶ÃÂ°ÃÃÂ¸Ã ÃÂºÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ¸ ÃÃÂ·ÃÃÂºÃÂ° (ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ«ÃÃÃÂ¾ÃÂ´ÃÂ¾ÃÂ»ÃÂ¶ÃÂ¸ÃÃÃÂ»).
    """
    uid = update.effective_user.id

    # ÃÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÃÂ°ÃÂ½ÃÂ½ÃÂµÃ (ÃÂµÃÃÂ»ÃÂ¸ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÂ½)
    welcome_url = kv_get("welcome_url", BANNER_URL)
    if welcome_url:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_photo(welcome_url)

    # ÃÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÂ²ÃÃÃÂ¾Ã ÃÃÂ·ÃÃÂºÃÂ° ÃÂ²ÃÃÂµÃÂ³ÃÂ´ÃÂ°
    await update.effective_message.reply_text(
        t(uid, "choose_lang"),
        reply_markup=_lang_choose_kb(uid),
    )
# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÂ¡ÃÃÂ°ÃÃ / ÃÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸ / ÃÃÂ¾ÃÂ¼ÃÂ¾ÃÃ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

async def cmd_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.effective_message.reply_text(_tr(uid, "choose_engine"), reply_markup=engines_kb())

async def cmd_subs_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("ÃÃÃÂºÃÃÃÃ ÃÃÂ°ÃÃÂ¸ÃÃ (WebApp)", web_app=WebAppInfo(url=TARIFF_URL))],
        [InlineKeyboardButton("ÃÃÃÂ¾ÃÃÂ¼ÃÂ¸ÃÃ PRO ÃÂ½ÃÂ° ÃÂ¼ÃÂµÃÃÃ (ÃÂ®Kassa)", callback_data="buyinv:pro:1")],
    ])
    await update.effective_message.reply_text("Ã¢Â­ ÃÂ¢ÃÂ°ÃÃÂ¸ÃÃ ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ¼ÃÂ¾ÃÃ.\n\n" + HELP_TEXT, reply_markup=kb, disable_web_page_preview=True)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, disable_web_page_preview=True)

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(EXAMPLES_TEXT, disable_web_page_preview=True)


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¸ÃÂ°ÃÂ³ÃÂ½ÃÂ¾ÃÃÃÂ¸ÃÂºÃÂ°/ÃÂ»ÃÂ¸ÃÂ¼ÃÂ¸ÃÃ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def cmd_diag_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tier = get_subscription_tier(user_id)
    lim = _limits_for(user_id)
    row = _usage_row(user_id, _today_ymd())
    lines = [
        f"Ã°Â¤ ÃÂ¢ÃÂ°ÃÃÂ¸Ã: {tier}",
        f"Ã¢Â¢ ÃÂ¢ÃÂµÃÂºÃÃÃ ÃÃÂµÃÂ³ÃÂ¾ÃÂ´ÃÂ½Ã: {row['text_count']} / {lim['text_per_day']}",
        f"Ã¢Â¢ Luma $: {row['luma_usd']:.2f} / {lim['luma_budget_usd']:.2f}",
        f"Ã¢Â¢ Runway $: {row['runway_usd']:.2f} / {lim['runway_budget_usd']:.2f}",
        f"Ã¢Â¢ Images $: {row['img_usd']:.2f} / {lim['img_budget_usd']:.2f}",
    ]
    await update.effective_message.reply_text("\n".join(lines))


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Capability Q&A Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
_CAP_PDF   = re.compile(r"(pdf|ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½Ã(Ã)?|ÃÃÂ°ÃÂ¹ÃÂ»(Ã)?)", re.I)
_CAP_EBOOK = re.compile(r"(ebook|e-?book|ÃÃÂ»ÃÂµÃÂºÃÃÃÂ¾ÃÂ½ÃÂ½(ÃÂ°Ã|ÃÃÂµ)\s+ÃÂºÃÂ½ÃÂ¸ÃÂ³|epub|fb2|docx|txt|mobi|azw)", re.I)
_CAP_AUDIO = re.compile(r"(ÃÂ°ÃÃÂ´ÃÂ¸ÃÂ¾ ?ÃÂºÃÂ½ÃÂ¸ÃÂ³|audiobook|audio ?book|mp3|m4a|wav|ogg|webm|voice)", re.I)
_CAP_IMAGE = re.compile(r"(ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½|ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂº|ÃÃÂ¾ÃÃÂ¾|image|picture|img)", re.I)
_CAP_VIDEO = re.compile(r"(ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾|ÃÃÂ¾ÃÂ»ÃÂ¸ÃÂº|shorts?|reels?|clip)", re.I)

def capability_answer(text: str) -> str | None:
    """
    ÃÃÂ¾ÃÃÂ¾ÃÃÂºÃÂ¸ÃÂµ ÃÂ¾ÃÃÂ²ÃÂµÃÃ ÃÂ½ÃÂ° ÃÂ²ÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃ ÃÂ²ÃÂ¸ÃÂ´ÃÂ°:
    - ÃÂ«ÃÃ ÃÂ¼ÃÂ¾ÃÂ¶ÃÂµÃÃ ÃÂ°ÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÂ·ÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ PDF?ÃÂ»
    - ÃÂ«ÃÃ ÃÃÂ¼ÃÂµÃÂµÃÃ ÃÃÂ°ÃÃÂ¾ÃÃÂ°ÃÃ Ã ÃÃÂ»ÃÂµÃÂºÃÃÃÂ¾ÃÂ½ÃÂ½ÃÃÂ¼ÃÂ¸ ÃÂºÃÂ½ÃÂ¸ÃÂ³ÃÂ°ÃÂ¼ÃÂ¸?ÃÂ»
    - ÃÂ«ÃÃ ÃÂ¼ÃÂ¾ÃÂ¶ÃÂµÃÃ ÃÃÂ¾ÃÂ·ÃÂ´ÃÂ°ÃÂ²ÃÂ°ÃÃ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾?ÃÂ»
    - ÃÂ«ÃÃ ÃÂ¼ÃÂ¾ÃÂ¶ÃÂµÃÃ ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ ÃÃÂ¾ÃÃÂ¾ÃÂ³ÃÃÂ°ÃÃÂ¸Ã?ÃÂ» ÃÂ¸ Ã.ÃÂ¿.

    ÃÃÂ°ÃÂ¶ÃÂ½ÃÂ¾: ÃÂ½ÃÂµ ÃÂ¿ÃÂµÃÃÂµÃÃÂ²ÃÂ°ÃÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÃÂµÃÂ°ÃÂ»ÃÃÂ½ÃÃÂµ ÃÂºÃÂ¾ÃÂ¼ÃÂ°ÃÂ½ÃÂ´Ã
    ÃÂ«ÃÃÂ´ÃÂµÃÂ»ÃÂ°ÃÂ¹ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾Ã¢Â¦ÃÂ», ÃÂ«ÃÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ¸ÃÃÃÂ¹ ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÃ¢Â¦ÃÂ» ÃÂ¸ Ã.ÃÂ´.
    """

    tl = (text or "").strip().lower()
    if not tl:
        return None

    # --- ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÃÂ°ÃÃÃ ÃÃÂ¾ÃÃÂ¾ / ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ°ÃÃÂ¸Ã ÃÃÂ½ÃÂ¸ÃÂ¼ÃÂºÃÂ¾ÃÂ² (ÃÃÂ«ÃÂ¡ÃÃÃÃ ÃÃ ÃÃÃ ÃÃÂ¢ÃÃÂ¢) ---
    if (
        any(k in tl for k in ("ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸", "ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ", "ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ¸ÃÃÃÂ¹", "ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ"))
        and any(k in tl for k in ("ÃÃÂ¾ÃÃÂ¾", "ÃÃÂ¾ÃÃÂ¾ÃÂ³ÃÃÂ°Ã", "ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½", "ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½", "ÃÂ¿ÃÂ¾ÃÃÃÃÂµÃ"))
    ):
        # ÃÃÂµÃÃÃÂ¾ÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÂ·ÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ½ÃÃÂ¹ ÃÂ¾ÃÃÂ²ÃÂµÃ ÃÂ¸ÃÂ¼ÃÂµÃÂ½ÃÂ½ÃÂ¾ ÃÂ¿ÃÂ¾ÃÂ´ ÃÃÃÂ½ÃÂºÃÃÂ¸Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸Ã
        return (
            "Ã°Âª ÃÂ¯ ÃÃÂ¼ÃÂµÃ ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÃÃ ÃÃÂ¾ÃÃÂ¾ÃÂ³ÃÃÂ°ÃÃÂ¸ÃÂ¸ ÃÂ¸ ÃÂ´ÃÂµÃÂ»ÃÂ°ÃÃ ÃÂ¸ÃÂ· ÃÂ½ÃÂ¸Ã ÃÂºÃÂ¾ÃÃÂ¾ÃÃÂºÃÂ¸ÃÂµ ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ°ÃÃÂ¸ÃÂ¸.\n\n"
            "ÃÂ§ÃÃÂ¾ ÃÂ¼ÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ:\n"
            "Ã¢Â¢ ÃÂ»ÃÃÂ³ÃÂºÃÂ°Ã ÃÂ¼ÃÂ¸ÃÂ¼ÃÂ¸ÃÂºÃÂ°: ÃÂ¼ÃÂ¾ÃÃÂ³ÃÂ°ÃÂ½ÃÂ¸ÃÂµ ÃÂ³ÃÂ»ÃÂ°ÃÂ·, ÃÂ¼ÃÃÂ³ÃÂºÃÂ°Ã ÃÃÂ»ÃÃÃÂºÃÂ°;\n"
            "Ã¢Â¢ ÃÂ¿ÃÂ»ÃÂ°ÃÂ²ÃÂ½ÃÃÂµ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÂ²Ã ÃÂ¸ ÃÂ¿ÃÂ»ÃÂµÃ, ÃÃÃÃÂµÃÂºÃ ÃÂ´ÃÃÃÂ°ÃÂ½ÃÂ¸Ã;\n"
            "Ã¢Â¢ ÃÂ»ÃÃÂ³ÃÂºÃÂ¾ÃÂµ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ¿ÃÂ°ÃÃÂ°ÃÂ»ÃÂ»ÃÂ°ÃÂºÃ ÃÃÂ¾ÃÂ½ÃÂ°.\n\n"
            "ÃÃÂ¾ÃÃÃÃÂ¿ÃÂ½ÃÃÂµ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸:\n"
            "Ã¢Â¢ Runway Ã¢ ÃÂ¼ÃÂ°ÃÂºÃÃÂ¸ÃÂ¼ÃÂ°ÃÂ»ÃÃÂ½ÃÂ¾ ÃÃÂµÃÂ°ÃÂ»ÃÂ¸ÃÃÃÂ¸ÃÃÂ½ÃÂ¾ÃÂµ ÃÂ¿ÃÃÂµÃÂ¼ÃÂ¸ÃÃÂ¼-ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂµ;\n"
            "Ã¢Â¢ Kling Ã¢ ÃÂ¾ÃÃÂ»ÃÂ¸ÃÃÂ½ÃÂ¾ ÃÂ¿ÃÂµÃÃÂµÃÂ´ÃÂ°ÃÃ ÃÂ²ÃÂ·ÃÂ³ÃÂ»ÃÃÂ´, ÃÂ¼ÃÂ¸ÃÂ¼ÃÂ¸ÃÂºÃ ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ²ÃÂ¾ÃÃÂ¾ÃÃ ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÂ²Ã;\n"
            "Ã¢Â¢ Luma Ã¢ ÃÂ¿ÃÂ»ÃÂ°ÃÂ²ÃÂ½ÃÃÂµ ÃÃÃÂ´ÃÂ¾ÃÂ¶ÃÂµÃÃÃÂ²ÃÂµÃÂ½ÃÂ½ÃÃÂµ ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ°ÃÃÂ¸ÃÂ¸.\n\n"
            "ÃÃÃÂ¸ÃÃÂ»ÃÂ¸ ÃÃÃÂ´ÃÂ° ÃÃÂ¾ÃÃÂ¾ (ÃÂ»ÃÃÃÃÂµ ÃÂ¿ÃÂ¾ÃÃÃÃÂµÃ). ÃÃÂ¾ÃÃÂ»ÃÂµ ÃÂ·ÃÂ°ÃÂ³ÃÃÃÂ·ÃÂºÃÂ¸ Ã ÃÂ¿ÃÃÂµÃÂ´ÃÂ»ÃÂ¾ÃÂ¶Ã ÃÂ²ÃÃÃÃÂ°ÃÃ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº "
            "ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ»Ã ÃÂ¿ÃÃÂµÃÂ²ÃÃ/ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾."
        )

    # --- ÃÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃ / ÃÃÂ°ÃÂ¹ÃÂ»Ã ---
    if re.search(r"\b(pdf|docx|epub|fb2|txt|mobi|azw)\b", tl) and "?" in tl:
        return (
            "ÃÃÂ°, ÃÂ¼ÃÂ¾ÃÂ³Ã ÃÂ¿ÃÂ¾ÃÂ¼ÃÂ¾ÃÃ Ã ÃÂ°ÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÂ·ÃÂ¾ÃÂ¼ ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃÂ¾ÃÂ² ÃÂ¸ ÃÃÂ»ÃÂµÃÂºÃÃÃÂ¾ÃÂ½ÃÂ½ÃÃ ÃÂºÃÂ½ÃÂ¸ÃÂ³. "
            "ÃÃÃÂ¿ÃÃÂ°ÃÂ²Ã ÃÃÂ°ÃÂ¹ÃÂ» (PDF, EPUB, DOCX, FB2, TXT, MOBI/AZW Ã¢ ÃÂ¿ÃÂ¾ ÃÂ²ÃÂ¾ÃÂ·ÃÂ¼ÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ÃÃÃÂ¸) "
            "ÃÂ¸ ÃÂ½ÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸, ÃÃÃÂ¾ ÃÂ½ÃÃÂ¶ÃÂ½ÃÂ¾: ÃÂºÃÂ¾ÃÂ½ÃÃÂ¿ÃÂµÃÂºÃ, ÃÂ²ÃÃÂ¶ÃÂ¸ÃÂ¼ÃÂºÃ, ÃÂ¿ÃÂ»ÃÂ°ÃÂ½, ÃÃÂ°ÃÂ·ÃÃÂ¾Ã ÃÂ¿ÃÂ¾ ÃÂ¿ÃÃÂ½ÃÂºÃÃÂ°ÃÂ¼ ÃÂ¸ Ã.ÃÂ¿."
        )

    # --- ÃÃÃÂ´ÃÂ¸ÃÂ¾ / ÃÃÂµÃÃ ---
    if ("ÃÂ°ÃÃÂ´ÃÂ¸ÃÂ¾" in tl or "ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃÂ¾ÃÂ²" in tl or "voice" in tl or "speech" in tl) and (
        "?" in tl or "ÃÂ¼ÃÂ¾ÃÂ¶ÃÂµÃÃ" in tl or "ÃÃÂ¼ÃÂµÃÂµÃÃ" in tl
    ):
        return (
            "ÃÃÂ°, ÃÂ¼ÃÂ¾ÃÂ³Ã ÃÃÂ°ÃÃÂ¿ÃÂ¾ÃÂ·ÃÂ½ÃÂ°ÃÂ²ÃÂ°ÃÃ ÃÃÂµÃÃ ÃÂ¸ÃÂ· ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃÂ¾ÃÂ²ÃÃ ÃÂ¸ ÃÂ°ÃÃÂ´ÃÂ¸ÃÂ¾. "
            "ÃÃÃÂ¾ÃÃÃÂ¾ ÃÂ¿ÃÃÂ¸ÃÃÂ»ÃÂ¸ ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾ÃÂµ ÃÃÂ¾ÃÂ¾ÃÃÃÂµÃÂ½ÃÂ¸ÃÂµ Ã¢ Ã ÃÂ¿ÃÂµÃÃÂµÃÂ²ÃÂµÃÂ´Ã ÃÂµÃÂ³ÃÂ¾ ÃÂ² ÃÃÂµÃÂºÃÃ ÃÂ¸ ÃÂ¾ÃÃÂ²ÃÂµÃÃ ÃÂºÃÂ°ÃÂº ÃÂ½ÃÂ° ÃÂ¾ÃÃÃÃÂ½ÃÃÂ¹ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã."
        )

    # --- ÃÃÂ¸ÃÂ´ÃÂµÃÂ¾ (ÃÂ¾ÃÃÃÂ¸ÃÂµ ÃÂ²ÃÂ¾ÃÂ·ÃÂ¼ÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ÃÃÃÂ¸, ÃÂ½ÃÂµ ÃÂºÃÂ¾ÃÂ¼ÃÂ°ÃÂ½ÃÂ´Ã) ---
    if (
        re.search(r"\bÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾\b", tl)
        and "?" in tl
        and re.search(r"\b(ÃÂ¼ÃÂ¾ÃÂ¶(ÃÂµÃÃ|ÃÂµÃÃÂµ)|ÃÃÂ¼ÃÂµ(ÃÂµÃÃ|ÃÂµÃÃÂµ)|ÃÃÂ¿ÃÂ¾ÃÃÂ¾ÃÃÂµÃÂ½)\b", tl)
    ):
        return (
            "ÃÃÂ°, ÃÂ¼ÃÂ¾ÃÂ³Ã ÃÂ·ÃÂ°ÃÂ¿ÃÃÃÂºÃÂ°ÃÃ ÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ°ÃÃÂ¸Ã ÃÂºÃÂ¾ÃÃÂ¾ÃÃÂºÃÂ¸Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾. "
            "ÃÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ ÃÃÂ´ÃÂµÃÂ»ÃÂ°ÃÃ ÃÃÂ¾ÃÂ»ÃÂ¸ÃÂº ÃÂ¿ÃÂ¾ ÃÃÂµÃÂºÃÃÃÂ¾ÃÂ²ÃÂ¾ÃÂ¼Ã ÃÂ¾ÃÂ¿ÃÂ¸ÃÃÂ°ÃÂ½ÃÂ¸Ã ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ ÃÃÂ¾ÃÃÂ¾. "
            "ÃÃÂ¾ÃÃÂ»ÃÂµ ÃÃÂ¾ÃÂ³ÃÂ¾ ÃÂºÃÂ°ÃÂº ÃÃ ÃÂ¿ÃÃÂ¸ÃÃÂ»ÃÃÃ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã ÃÂ¸/ÃÂ¸ÃÂ»ÃÂ¸ ÃÃÂ°ÃÂ¹ÃÂ», Ã ÃÂ¿ÃÃÂµÃÂ´ÃÂ»ÃÂ¾ÃÂ¶Ã ÃÂ²ÃÃÃÃÂ°ÃÃ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº "
            "(Runway, Kling, Luma Ã¢ ÃÂ² ÃÂ·ÃÂ°ÃÂ²ÃÂ¸ÃÃÂ¸ÃÂ¼ÃÂ¾ÃÃÃÂ¸ ÃÂ¾Ã ÃÂ´ÃÂ¾ÃÃÃÃÂ¿ÃÂ½ÃÃ)."
        )

    # --- ÃÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ¸ / ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã (ÃÃÂµÃÂ· /img ÃÂ¸ ÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ°ÃÃÂ¸ÃÂ¸ ÃÂ¿ÃÂ¾ ÃÂ¿ÃÃÂ¾ÃÂ¼ÃÂ¿ÃÃ) ---
    if (
        re.search(r"(ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂº|ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½|ÃÃÂ¾ÃÃÂ¾|picture|ÃÂ»ÃÂ¾ÃÂ³ÃÂ¾ÃÃÂ¸ÃÂ¿|ÃÃÂ°ÃÂ½ÃÂ½ÃÂµÃ)", tl)
        and "?" in tl
    ):
        return (
            "ÃÃÂ°, ÃÂ¼ÃÂ¾ÃÂ³Ã ÃÃÂ°ÃÃÂ¾ÃÃÂ°ÃÃ Ã ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÃÂ¼ÃÂ¸: ÃÂ°ÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÂ·, ÃÃÂ»ÃÃÃÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂºÃÂ°ÃÃÂµÃÃÃÂ²ÃÂ°, ÃÃÂ´ÃÂ°ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ·ÃÂ°ÃÂ¼ÃÂµÃÂ½ÃÂ° ÃÃÂ¾ÃÂ½ÃÂ°, "
            "ÃÃÂ°ÃÃÃÂ¸ÃÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂºÃÂ°ÃÂ´ÃÃÂ°, ÃÂ¿ÃÃÂ¾ÃÃÃÂ°Ã ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ°ÃÃÂ¸Ã. "
            "ÃÃÃÂ¾ÃÃÃÂ¾ ÃÂ¿ÃÃÂ¸ÃÃÂ»ÃÂ¸ ÃÃÃÂ´ÃÂ° ÃÃÂ¾ÃÃÂ¾ ÃÂ¸ ÃÂºÃÂ¾ÃÃÂ¾ÃÃÂºÃÂ¾ ÃÂ¾ÃÂ¿ÃÂ¸ÃÃÂ¸, ÃÃÃÂ¾ ÃÂ½ÃÃÂ¶ÃÂ½ÃÂ¾ ÃÃÂ´ÃÂµÃÂ»ÃÂ°ÃÃ."
        )

    # ÃÃÂ¸ÃÃÂµÃÂ³ÃÂ¾ ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂ¾ÃÂ´ÃÃÃÂµÃÂ³ÃÂ¾ Ã¢ ÃÂ¿ÃÃÃÃ ÃÂ¾ÃÃÃÂ°ÃÃÂ°ÃÃÃÂ²ÃÂ°ÃÂµÃÃÃ ÃÂ¾ÃÃÂ½ÃÂ¾ÃÂ²ÃÂ½ÃÂ¾ÃÂ¹ ÃÂ»ÃÂ¾ÃÂ³ÃÂ¸ÃÂºÃÂ¾ÃÂ¹
    return None

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¾ÃÂ´Ã/ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸ ÃÂ´ÃÂ»Ã study Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
def _uk(user_id: int, name: str) -> str: return f"user:{user_id}:{name}"
def mode_set(user_id: int, mode: str):     kv_set(_uk(user_id, "mode"), (mode or "default"))
def mode_get(user_id: int) -> str:         return kv_get(_uk(user_id, "mode"), "default") or "default"
def engine_set(user_id: int, engine: str): kv_set(_uk(user_id, "engine"), (engine or "gpt"))
def engine_get(user_id: int) -> str:       return kv_get(_uk(user_id, "engine"), "gpt") or "gpt"
def study_sub_set(user_id: int, sub: str): kv_set(_uk(user_id, "study_sub"), (sub or "explain"))
def study_sub_get(user_id: int) -> str:    return kv_get(_uk(user_id, "study_sub"), "explain") or "explain"

def modes_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Ã° ÃÂ£ÃÃÃÃÂ°", callback_data="mode:set:study"),
         InlineKeyboardButton("Ã°Â¼ ÃÂ¤ÃÂ¾ÃÃÂ¾",  callback_data="mode:set:photo")],
        [InlineKeyboardButton("Ã° ÃÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃ", callback_data="mode:set:docs"),
         InlineKeyboardButton("Ã° ÃÃÂ¾ÃÂ»ÃÂ¾Ã",     callback_data="mode:set:voice")],
        [InlineKeyboardButton("Ã°Â§  ÃÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸", callback_data="mode:engines")]
    ])

def study_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Ã° ÃÃÃÃÃÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ",          callback_data="study:set:explain"),
         InlineKeyboardButton("Ã°Â§Â® ÃÃÂ°ÃÂ´ÃÂ°ÃÃÂ¸",              callback_data="study:set:tasks")],
        [InlineKeyboardButton("Ã¢Ã¯Â¸ ÃÂ­ÃÃÃÂµ/ÃÃÂµÃÃÂµÃÃÂ°Ã/ÃÂ´ÃÂ¾ÃÂºÃÂ»ÃÂ°ÃÂ´", callback_data="study:set:essay")],
        [InlineKeyboardButton("Ã° ÃÂ­ÃÂºÃÂ·ÃÂ°ÃÂ¼ÃÂµÃÂ½/ÃÂºÃÂ²ÃÂ¸ÃÂ·",        callback_data="study:set:quiz")]
    ])

async def study_process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    sub = study_sub_get(update.effective_user.id)
    if sub == "explain":
        prompt = f"ÃÃÃÃÃÃÂ½ÃÂ¸ ÃÂ¿ÃÃÂ¾ÃÃÃÃÂ¼ÃÂ¸ ÃÃÂ»ÃÂ¾ÃÂ²ÃÂ°ÃÂ¼ÃÂ¸, Ã 2Ã¢3 ÃÂ¿ÃÃÂ¸ÃÂ¼ÃÂµÃÃÂ°ÃÂ¼ÃÂ¸ ÃÂ¸ ÃÂ¼ÃÂ¸ÃÂ½ÃÂ¸-ÃÂ¸ÃÃÂ¾ÃÂ³ÃÂ¾ÃÂ¼:\n\n{text}"
    elif sub == "tasks":
        prompt = ("Ã ÃÂµÃÃÂ¸ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃ(ÃÂ¸) ÃÂ¿ÃÂ¾ÃÃÂ°ÃÂ³ÃÂ¾ÃÂ²ÃÂ¾: ÃÃÂ¾ÃÃÂ¼ÃÃÂ»Ã, ÃÂ¿ÃÂ¾ÃÃÃÂ½ÃÂµÃÂ½ÃÂ¸Ã, ÃÂ¸ÃÃÂ¾ÃÂ³ÃÂ¾ÃÂ²ÃÃÂ¹ ÃÂ¾ÃÃÂ²ÃÂµÃ. "
                  "ÃÃÃÂ»ÃÂ¸ ÃÂ½ÃÂµ ÃÃÂ²ÃÂ°ÃÃÂ°ÃÂµÃ ÃÂ´ÃÂ°ÃÂ½ÃÂ½ÃÃ Ã¢ ÃÃÃÂ¾ÃÃÂ½ÃÃÃÃÂ¸ÃÂµ ÃÂ²ÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃ ÃÂ² ÃÂºÃÂ¾ÃÂ½ÃÃÂµ.\n\n" + text)
    elif sub == "essay":
        prompt = ("ÃÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ ÃÃÃÃÃÂºÃÃÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ½ÃÃÂ¹ ÃÃÂµÃÂºÃÃ 400Ã¢600 ÃÃÂ»ÃÂ¾ÃÂ² (ÃÃÃÃÂµ/ÃÃÂµÃÃÂµÃÃÂ°Ã/ÃÂ´ÃÂ¾ÃÂºÃÂ»ÃÂ°ÃÂ´): "
                  "ÃÂ²ÃÂ²ÃÂµÃÂ´ÃÂµÃÂ½ÃÂ¸ÃÂµ, 3Ã¢5 ÃÃÂµÃÂ·ÃÂ¸ÃÃÂ¾ÃÂ² Ã ÃÃÂ°ÃÂºÃÃÂ°ÃÂ¼ÃÂ¸, ÃÂ²ÃÃÂ²ÃÂ¾ÃÂ´, ÃÃÂ¿ÃÂ¸ÃÃÂ¾ÃÂº ÃÂ¸ÃÂ· 3 ÃÂ¸ÃÃÃÂ¾ÃÃÂ½ÃÂ¸ÃÂºÃÂ¾ÃÂ² (ÃÂµÃÃÂ»ÃÂ¸ ÃÃÂ¼ÃÂµÃÃÃÂ½ÃÂ¾).\n\nÃÂ¢ÃÂµÃÂ¼ÃÂ°:\n" + text)
    elif sub == "quiz":
        prompt = ("ÃÂ¡ÃÂ¾ÃÃÃÂ°ÃÂ²Ã ÃÂ¼ÃÂ¸ÃÂ½ÃÂ¸-ÃÂºÃÂ²ÃÂ¸ÃÂ· ÃÂ¿ÃÂ¾ ÃÃÂµÃÂ¼ÃÂµ: 10 ÃÂ²ÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃÂ¾ÃÂ², Ã ÃÂºÃÂ°ÃÂ¶ÃÂ´ÃÂ¾ÃÂ³ÃÂ¾ 4 ÃÂ²ÃÂ°ÃÃÂ¸ÃÂ°ÃÂ½ÃÃÂ° AÃ¢D; "
                  "ÃÂ² ÃÂºÃÂ¾ÃÂ½ÃÃÂµ ÃÂ´ÃÂ°ÃÂ¹ ÃÂºÃÂ»ÃÃ ÃÂ¾ÃÃÂ²ÃÂµÃÃÂ¾ÃÂ² (ÃÂ½ÃÂ¾ÃÂ¼ÃÂµÃÃ¢ÃÃÃÂºÃÂ²ÃÂ°). ÃÂ¢ÃÂµÃÂ¼ÃÂ°:\n\n" + text)
    else:
        prompt = text
    ans = await ask_openai_text(prompt)
    await update.effective_message.reply_text(ans)
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ° ÃÂ¿ÃÃÂ¸ÃÂ²ÃÂµÃÃÃÃÂ²ÃÂµÃÂ½ÃÂ½ÃÂ¾ÃÂ¹ ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ¸ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def cmd_set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("ÃÃÂ¾ÃÂ¼ÃÂ°ÃÂ½ÃÂ´ÃÂ° ÃÂ´ÃÂ¾ÃÃÃÃÂ¿ÃÂ½ÃÂ° ÃÃÂ¾ÃÂ»ÃÃÂºÃÂ¾ ÃÂ²ÃÂ»ÃÂ°ÃÂ´ÃÂµÃÂ»ÃÃÃ.")
        return
    if not context.args:
        await update.effective_message.reply_text("ÃÂ¤ÃÂ¾ÃÃÂ¼ÃÂ°Ã: /set_welcome <url_ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ¸>")
        return
    url = " ".join(context.args).strip()
    kv_set("welcome_url", url)
    await update.effective_message.reply_text("ÃÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ° ÃÂ¿ÃÃÂ¸ÃÂ²ÃÂµÃÃÃÃÂ²ÃÂ¸Ã ÃÂ¾ÃÃÂ½ÃÂ¾ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ°. ÃÃÃÂ¿ÃÃÂ°ÃÂ²ÃÃÃÂµ /start ÃÂ´ÃÂ»Ã ÃÂ¿ÃÃÂ¾ÃÂ²ÃÂµÃÃÂºÃÂ¸.")

async def cmd_show_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = kv_get("welcome_url", BANNER_URL)
    if url:
        await update.effective_message.reply_photo(url, caption="ÃÂ¢ÃÂµÃÂºÃÃÃÂ°Ã ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ° ÃÂ¿ÃÃÂ¸ÃÂ²ÃÂµÃÃÃÃÂ²ÃÂ¸Ã")
    else:
        await update.effective_message.reply_text("ÃÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ° ÃÂ¿ÃÃÂ¸ÃÂ²ÃÂµÃÃÃÃÂ²ÃÂ¸Ã ÃÂ½ÃÂµ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÂ½ÃÂ°.")


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã / ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    w = _wallet_get(user_id)
    total = _wallet_total_get(user_id)
    row = _usage_row(user_id)
    lim = _limits_for(user_id)
    msg = (
        "Ã°Â§Â¾ ÃÃÂ¾ÃÃÂµÃÂ»ÃÃÂº:\n"
        f"Ã¢Â¢ ÃÃÂ´ÃÂ¸ÃÂ½ÃÃÂ¹ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã: ${total:.2f}\n"
        "  (ÃÃÂ°ÃÃÃÂ¾ÃÂ´ÃÃÂµÃÃÃ ÃÂ½ÃÂ° ÃÂ¿ÃÂµÃÃÂµÃÃÂ°ÃÃÃÂ¾ÃÂ´ ÃÂ¿ÃÂ¾ Luma/Runway/Images)\n\n"
        "ÃÃÂµÃÃÂ°ÃÂ»ÃÂ¸ÃÂ·ÃÂ°ÃÃÂ¸Ã ÃÃÂµÃÂ³ÃÂ¾ÃÂ´ÃÂ½Ã / ÃÂ»ÃÂ¸ÃÂ¼ÃÂ¸ÃÃ ÃÃÂ°ÃÃÂ¸ÃÃÂ°:\n"
        f"Ã¢Â¢ Luma: ${row['luma_usd']:.2f} / ${lim['luma_budget_usd']:.2f}\n"
        f"Ã¢Â¢ Runway: ${row['runway_usd']:.2f} / ${lim['runway_budget_usd']:.2f}\n"
        f"Ã¢Â¢ Images: ${row['img_usd']:.2f} / ${lim['img_budget_usd']:.2f}\n"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Ã¢ ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂ¸ÃÃ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã", callback_data="topup")]])
    await update.effective_message.reply_text(msg, reply_markup=kb)

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° / ÃÃÂ°ÃÃÂ¸ÃÃ Ã¢ UI ÃÂ¸ ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃ (PATCH) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
# ÃÃÂ°ÃÂ²ÃÂ¸ÃÃÂ¸ÃÂ¼ÃÂ¾ÃÃÃÂ¸ ÃÂ¾ÃÂºÃÃÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã:
#  - YOOKASSA_PROVIDER_TOKEN  (ÃÂ¿ÃÂ»ÃÂ°ÃÃÃÂ¶ÃÂ½ÃÃÂ¹ ÃÃÂ¾ÃÂºÃÂµÃÂ½ Telegram Payments ÃÂ¾Ã ÃÂ®Kassa)
#  - YOOKASSA_CURRENCY        (ÃÂ¿ÃÂ¾ ÃÃÂ¼ÃÂ¾ÃÂ»ÃÃÂ°ÃÂ½ÃÂ¸Ã "RUB")
#  - CRYPTO_PAY_API_TOKEN     (https://pay.crypt.bot Ã¢ ÃÃÂ¾ÃÂºÃÂµÃÂ½ ÃÂ¿ÃÃÂ¾ÃÂ´ÃÂ°ÃÂ²ÃÃÂ°)
#  - CRYPTO_ASSET             (ÃÂ½ÃÂ°ÃÂ¿ÃÃÂ¸ÃÂ¼ÃÂµÃ "USDT", ÃÂ¿ÃÂ¾ ÃÃÂ¼ÃÂ¾ÃÂ»ÃÃÂ°ÃÂ½ÃÂ¸Ã "USDT")
#  - PRICE_START_RUB, PRICE_PRO_RUB, PRICE_ULT_RUB  (ÃÃÂµÃÂ»ÃÂ¾ÃÂµ ÃÃÂ¸ÃÃÂ»ÃÂ¾, Ã¢Â½)
#  - PRICE_START_USD, PRICE_PRO_USD, PRICE_ULT_USD  (ÃÃÂ¸ÃÃÂ»ÃÂ¾ Ã ÃÃÂ¾ÃÃÂºÃÂ¾ÃÂ¹, $)
#
# ÃÂ¥ÃÃÂ°ÃÂ½ÃÂ¸ÃÂ»ÃÂ¸ÃÃÂµ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ¸ ÃÂ¸ ÃÂºÃÂ¾ÃÃÂµÃÂ»ÃÃÂºÃÂ° ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÃÃ ÃÂ½ÃÂ° kv_*:
#   sub:tier:{user_id}   -> "start" | "pro" | "ultimate"
#   sub:until:{user_id}  -> ISO-ÃÃÃÃÂ¾ÃÂºÃÂ° ÃÂ´ÃÂ°ÃÃ ÃÂ¾ÃÂºÃÂ¾ÃÂ½ÃÃÂ°ÃÂ½ÃÂ¸Ã
#   wallet:usd:{user_id} -> ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã ÃÂ² USD (float)

YOOKASSA_PROVIDER_TOKEN = os.environ.get("YOOKASSA_PROVIDER_TOKEN", "").strip()
YOOKASSA_CURRENCY = (os.environ.get("YOOKASSA_CURRENCY") or "RUB").upper()

CRYPTO_PAY_API_TOKEN = os.environ.get("CRYPTO_PAY_API_TOKEN", "").strip()
CRYPTO_ASSET = (os.environ.get("CRYPTO_ASSET") or "USDT").upper()

# === COMPAT with existing vars/DB in your main.py ===
# 1) ÃÂ®Kassa: ÃÂµÃÃÂ»ÃÂ¸ ÃÃÂ¶ÃÂµ ÃÂµÃÃÃ PROVIDER_TOKEN (ÃÂ¸ÃÂ· PROVIDER_TOKEN_YOOKASSA), ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÂ¼ ÃÂµÃÂ³ÃÂ¾:
if not YOOKASSA_PROVIDER_TOKEN and 'PROVIDER_TOKEN' in globals() and PROVIDER_TOKEN:
    YOOKASSA_PROVIDER_TOKEN = PROVIDER_TOKEN

# 2) ÃÃÂ¾ÃÃÂµÃÂ»ÃÃÂº: ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÂ¼ ÃÃÂ²ÃÂ¾ÃÂ¹ ÃÂµÃÂ´ÃÂ¸ÃÂ½ÃÃÂ¹ USD-ÃÂºÃÂ¾ÃÃÂµÃÂ»ÃÃÂº (wallet table) ÃÂ²ÃÂ¼ÃÂµÃÃÃÂ¾ kv:
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

# 3) ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ°: ÃÂ°ÃÂºÃÃÂ¸ÃÂ²ÃÂ¸ÃÃÃÂµÃÂ¼ ÃÃÂµÃÃÂµÃÂ· ÃÃÂ²ÃÂ¾ÃÂ¸ ÃÃÃÂ½ÃÂºÃÃÂ¸ÃÂ¸ Ã ÃÃ, ÃÂ° ÃÂ½ÃÂµ kv:
def _sub_activate(user_id: int, tier_key: str, months: int = 1) -> str:
    dt = activate_subscription_with_tier(user_id, tier_key, months)
    return dt.isoformat()

def _sub_info_text(user_id: int) -> str:
    tier = get_subscription_tier(user_id)
    dt = get_subscription_until(user_id)
    human_until = dt.strftime("%d.%m.%Y") if dt else ""
    bal = _user_balance_get(user_id)
    line_until = f"\nÃ¢Â³ ÃÃÂºÃÃÂ¸ÃÂ²ÃÂ½ÃÂ° ÃÂ´ÃÂ¾: {human_until}" if tier != "free" and human_until else ""
    return f"Ã°Â§Â¾ ÃÂ¢ÃÂµÃÂºÃÃÃÂ°Ã ÃÂ¿ÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ°: {tier.upper() if tier!='free' else 'ÃÂ½ÃÂµÃ'}{line_until}\nÃ°Âµ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã: ${bal:.2f}"

# ÃÂ¦ÃÂµÃÂ½Ã Ã¢ ÃÂ¸ÃÂ· env Ã ÃÂ¾ÃÃÂ¼ÃÃÃÂ»ÃÂµÃÂ½ÃÂ½ÃÃÂ¼ÃÂ¸ ÃÂ´ÃÂµÃÃÂ¾ÃÂ»ÃÃÂ°ÃÂ¼ÃÂ¸
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
            "Ã°Â¬ GPT-ÃÃÂ°Ã ÃÂ¸ ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃ (ÃÃÂ°ÃÂ·ÃÂ¾ÃÂ²ÃÃÂµ ÃÂ»ÃÂ¸ÃÂ¼ÃÂ¸ÃÃ)",
            "Ã°Â¼ ÃÂ¤ÃÂ¾ÃÃÂ¾-ÃÂ¼ÃÂ°ÃÃÃÂµÃÃÃÂºÃÂ°Ã: ÃÃÂ¾ÃÂ½, ÃÂ»ÃÃÂ³ÃÂºÃÂ°Ã ÃÂ´ÃÂ¾ÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÂºÃÂ°",
            "Ã°Â§ ÃÃÂ·ÃÂ²ÃÃÃÂºÃÂ° ÃÂ¾ÃÃÂ²ÃÂµÃÃÂ¾ÃÂ² (TTS)",
        ],
    },
    "pro": {
        "title": "PRO",
        "rub": PRICE_PRO_RUB,
        "usd": PRICE_PRO_USD,
        "features": [
            "Ã° ÃÃÂ»ÃÃÃÂ¾ÃÂºÃÂ¸ÃÂ¹ ÃÃÂ°ÃÂ·ÃÃÂ¾Ã PDF/DOCX/EPUB",
            "Ã°Â¬ Reels/Shorts ÃÂ¿ÃÂ¾ ÃÃÂ¼ÃÃÃÂ»Ã, ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÂ¸ÃÂ· ÃÃÂ¾ÃÃÂ¾",
            "Ã°Â¼ Outpaint ÃÂ¸ ÃÂ«ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµÃÂ» ÃÃÃÂ°ÃÃÃ ÃÃÂ¾ÃÃÂ¾",
        ],
    },
    "ultimate": {
        "title": "ULTIMATE",
        "rub": PRICE_ULT_RUB,
        "usd": PRICE_ULT_USD,
        "features": [
            "Ã° Runway/Luma Ã¢ ÃÂ¿ÃÃÂµÃÂ¼ÃÂ¸ÃÃÂ¼-ÃÃÂµÃÂ½ÃÂ´ÃÂµÃÃ",
            "Ã°Â§  Ã ÃÂ°ÃÃÃÂ¸ÃÃÂµÃÂ½ÃÂ½ÃÃÂµ ÃÂ»ÃÂ¸ÃÂ¼ÃÂ¸ÃÃ ÃÂ¸ ÃÂ¿ÃÃÂ¸ÃÂ¾ÃÃÂ¸ÃÃÂµÃÃÂ½ÃÂ°Ã ÃÂ¾ÃÃÂµÃÃÂµÃÂ´Ã",
            "Ã°  PRO-ÃÂ¸ÃÂ½ÃÃÃÃÃÂ¼ÃÂµÃÂ½ÃÃ (ÃÂ°ÃÃÃÂ¸ÃÃÂµÃÂºÃÃÃÃÂ°/ÃÂ´ÃÂ¸ÃÂ·ÃÂ°ÃÂ¹ÃÂ½)",
        ],
    },
}

def _money_fmt_rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " Ã¢Â½"

def _money_fmt_usd(v: float) -> str:
    return f"${v:.2f}"

def _user_balance_get(user_id: int) -> float:
    # ÃÃÃÃÂ°ÃÂµÃÂ¼ÃÃ ÃÂ²ÃÂ·ÃÃÃ ÃÂ¸ÃÂ· ÃÃÂ²ÃÂ¾ÃÂµÃÂ³ÃÂ¾ ÃÂºÃÂ¾ÃÃÂµÃÂ»ÃÃÂºÃÂ°, ÃÂµÃÃÂ»ÃÂ¸ ÃÂµÃÃÃ, ÃÂ¸ÃÂ½ÃÂ°ÃÃÂµ Ã¢ kv
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
    tier = kv_get(f"sub:tier:{user_id}", "") or "ÃÂ½ÃÂµÃ"
    until = kv_get(f"sub:until:{user_id}", "")
    human_until = ""
    if until:
        try:
            d = datetime.fromisoformat(until)
            human_until = d.strftime("%d.%m.%Y")
        except Exception:
            human_until = until
    bal = _user_balance_get(user_id)
    line_until = f"\nÃ¢Â³ ÃÃÂºÃÃÂ¸ÃÂ²ÃÂ½ÃÂ° ÃÂ´ÃÂ¾: {human_until}" if tier != "ÃÂ½ÃÂµÃ" and human_until else ""
    return f"Ã°Â§Â¾ ÃÂ¢ÃÂµÃÂºÃÃÃÂ°Ã ÃÂ¿ÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ°: {tier.upper() if tier!='ÃÂ½ÃÂµÃ' else 'ÃÂ½ÃÂµÃ'}{line_until}\nÃ°Âµ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã: {_money_fmt_usd(bal)}"

def _plan_card_text(key: str) -> str:
    p = SUBS_TIERS[key]
    fs = "\n".join("Ã¢Â¢ " + f for f in p["features"])
    return (
        f"Ã¢Â­ ÃÂ¢ÃÂ°ÃÃÂ¸Ã {p['title']}\n"
        f"ÃÂ¦ÃÂµÃÂ½ÃÂ°: {_money_fmt_rub(p['rub'])} / {_money_fmt_usd(p['usd'])} ÃÂ² ÃÂ¼ÃÂµÃ.\n\n"
        f"{fs}\n"
    )

def _plans_overview_text(user_id: int) -> str:
    parts = [
        "Ã¢Â­ ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° ÃÂ¸ ÃÃÂ°ÃÃÂ¸ÃÃ",
        "ÃÃÃÃÂµÃÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂ¾ÃÂ´ÃÃÃÂ¸ÃÂ¹ ÃÃÃÂ¾ÃÂ²ÃÂµÃÂ½Ã Ã¢ ÃÂ´ÃÂ¾ÃÃÃÃÂ¿ ÃÂ¾ÃÃÂºÃÃÂ¾ÃÂµÃÃÃ ÃÃÃÂ°ÃÂ·Ã ÃÂ¿ÃÂ¾ÃÃÂ»ÃÂµ ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃ.",
        _sub_info_text(user_id),
        "Ã¢ Ã¢ Ã¢",
        _plan_card_text("start"),
        _plan_card_text("pro"),
        _plan_card_text("ultimate"),
        "ÃÃÃÃÂµÃÃÂ¸ÃÃÂµ ÃÃÂ°ÃÃÂ¸Ã ÃÂºÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ¾ÃÂ¹ ÃÂ½ÃÂ¸ÃÂ¶ÃÂµ.",
    ]
    return "\n".join(parts)

def plans_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Ã¢Â­ START",    callback_data="plan:start"),
            InlineKeyboardButton("Ã° PRO",      callback_data="plan:pro"),
            InlineKeyboardButton("Ã° ULTIMATE", callback_data="plan:ultimate"),
        ]
    ])

def plan_pay_kb(plan_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Ã°Â³ ÃÃÂ¿ÃÂ»ÃÂ°ÃÃÂ¸ÃÃ Ã¢ ÃÂ®Kassa", callback_data=f"pay:yookassa:{plan_key}"),
        ],
        [
            InlineKeyboardButton("Ã°  ÃÃÂ¿ÃÂ»ÃÂ°ÃÃÂ¸ÃÃ Ã¢ CryptoBot", callback_data=f"pay:cryptobot:{plan_key}"),
        ],
        [
            InlineKeyboardButton("Ã°Â§Â¾ ÃÂ¡ÃÂ¿ÃÂ¸ÃÃÂ°ÃÃ Ã ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½ÃÃÂ°", callback_data=f"pay:balance:{plan_key}"),
        ],
        [
            InlineKeyboardButton("Ã¢Â¬Ã¯Â¸ Ã ÃÃÂ°ÃÃÂ¸ÃÃÂ°ÃÂ¼", callback_data="plan:root"),
        ]
    ])

# ÃÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ° ÃÂ«Ã¢Â­ ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° ÃÂ· ÃÃÂ¾ÃÂ¼ÃÂ¾ÃÃÃÂ»
async def on_btn_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = _plans_overview_text(user_id)
    await update.effective_chat.send_message(text, reply_markup=plans_root_kb())

# ÃÃÃÃÂ°ÃÃÂ¾ÃÃÃÂ¸ÃÂº ÃÂ½ÃÂ°ÃÃÂ¸Ã ÃÂºÃÂ¾ÃÂ»ÃÃÃÂºÃÂ¾ÃÂ² ÃÂ¿ÃÂ¾ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂµ/ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃÂ°ÃÂ¼ (ÃÂ·ÃÂ°ÃÃÂµÃÂ³ÃÂ¸ÃÃÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÃ ÃÂ¾ÃÃÃÂµÃÂ³ÃÂ¾ on_cb!)
async def on_cb_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    user_id = q.from_user.id
    chat_id = q.message.chat.id  # FIX: ÃÂºÃÂ¾ÃÃÃÂµÃÂºÃÃÂ½ÃÂ¾ÃÂµ ÃÂ¿ÃÂ¾ÃÂ»ÃÂµ ÃÂ² PTB v21+

    # ÃÃÂ°ÃÂ²ÃÂ¸ÃÂ³ÃÂ°ÃÃÂ¸Ã ÃÂ¼ÃÂµÃÂ¶ÃÂ´Ã ÃÃÂ°ÃÃÂ¸ÃÃÂ°ÃÂ¼ÃÂ¸
    if data.startswith("plan:"):
        _, arg = data.split(":", 1)
        if arg == "root":
            await q.edit_message_text(_plans_overview_text(user_id), reply_markup=plans_root_kb())
            await q.answer()
            return
        if arg in SUBS_TIERS:
            await q.edit_message_text(
                _plan_card_text(arg) + "\nÃÃÃÃÂµÃÃÂ¸ÃÃÂµ ÃÃÂ¿ÃÂ¾ÃÃÂ¾Ã ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃ:",
                reply_markup=plan_pay_kb(arg)
            )
            await q.answer()
            return

    # ÃÃÂ»ÃÂ°ÃÃÂµÃÂ¶ÃÂ¸
    if data.startswith("pay:"):
        # ÃÃÂµÃÂ·ÃÂ¾ÃÂ¿ÃÂ°ÃÃÂ½ÃÃÂ¹ ÃÂ¿ÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂ³
        try:
            _, method, plan_key = data.split(":", 2)
        except ValueError:
            await q.answer("ÃÃÂµÃÂºÃÂ¾ÃÃÃÂµÃÂºÃÃÂ½ÃÃÂµ ÃÂ´ÃÂ°ÃÂ½ÃÂ½ÃÃÂµ ÃÂºÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ¸.", show_alert=True)
            return

        plan = SUBS_TIERS.get(plan_key)
        if not plan:
            await q.answer("ÃÃÂµÃÂ¸ÃÂ·ÃÂ²ÃÂµÃÃÃÂ½ÃÃÂ¹ ÃÃÂ°ÃÃÂ¸Ã.", show_alert=True)
            return

        # ÃÂ®Kassa ÃÃÂµÃÃÂµÃÂ· Telegram Payments
        if method == "yookassa":
            if not YOOKASSA_PROVIDER_TOKEN:
                await q.answer("ÃÂ®Kassa ÃÂ½ÃÂµ ÃÂ¿ÃÂ¾ÃÂ´ÃÂºÃÂ»ÃÃÃÂµÃÂ½ÃÂ° (ÃÂ½ÃÂµÃ YOOKASSA_PROVIDER_TOKEN).", show_alert=True)
                return

            title = f"ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° {plan['title']} Ã¢Â¢ 1 ÃÂ¼ÃÂµÃÃÃ"
            desc = "ÃÃÂ¾ÃÃÃÃÂ¿ ÃÂº ÃÃÃÂ½ÃÂºÃÃÂ¸ÃÃÂ¼ ÃÃÂ¾ÃÃÂ° ÃÃÂ¾ÃÂ³ÃÂ»ÃÂ°ÃÃÂ½ÃÂ¾ ÃÂ²ÃÃÃÃÂ°ÃÂ½ÃÂ½ÃÂ¾ÃÂ¼Ã ÃÃÂ°ÃÃÂ¸ÃÃ. ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° ÃÂ°ÃÂºÃÃÂ¸ÃÂ²ÃÂ¸ÃÃÃÂµÃÃÃ ÃÃÃÂ°ÃÂ·Ã ÃÂ¿ÃÂ¾ÃÃÂ»ÃÂµ ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃ."
            payload = json.dumps({"tier": plan_key, "months": 1})

            # Telegram ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ´ÃÂ°ÃÂµÃ ÃÃÃÂ¼ÃÂ¼Ã ÃÂ² ÃÂ¼ÃÂ¸ÃÂ½ÃÂ¾ÃÃÂ½ÃÃ ÃÂµÃÂ´ÃÂ¸ÃÂ½ÃÂ¸ÃÃÂ°Ã (ÃÂºÃÂ¾ÃÂ¿ÃÂµÃÂ¹ÃÂºÃÂ¸/ÃÃÂµÃÂ½ÃÃ)
            if YOOKASSA_CURRENCY == "RUB":
                total_minor = int(round(float(plan["rub"]) * 100))
            else:
                total_minor = int(round(float(plan["usd"]) * 100))

            prices = [LabeledPrice(label=f"{plan['title']} 1 ÃÂ¼ÃÂµÃ.", amount=total_minor)]
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
            await q.answer("ÃÂ¡ÃÃÃ ÃÂ²ÃÃÃÃÂ°ÃÂ²ÃÂ»ÃÂµÃÂ½ Ã¢")
            return

        # CryptoBot (Crypto Pay API: ÃÃÂ¾ÃÂ·ÃÂ´ÃÂ°ÃÃÂ¼ ÃÂ¸ÃÂ½ÃÂ²ÃÂ¾ÃÂ¹Ã ÃÂ¸ ÃÂ¾ÃÃÂ´ÃÂ°ÃÃÂ¼ ÃÃÃÃÂ»ÃÂºÃ)
        if method == "cryptobot":  # FIX: ÃÂ²ÃÃÃÂ¾ÃÂ²ÃÂ½ÃÂµÃÂ½ ÃÂ¾ÃÃÃÃÃÂ¿
            if not CRYPTO_PAY_API_TOKEN:
                await q.answer("CryptoBot ÃÂ½ÃÂµ ÃÂ¿ÃÂ¾ÃÂ´ÃÂºÃÂ»ÃÃÃÃÂ½ (ÃÂ½ÃÂµÃ CRYPTO_PAY_API_TOKEN).", show_alert=True)
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
                            "description": f"Subscription {plan['title']} Ã¢Â¢ 1 month",
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
                    [InlineKeyboardButton("Ã°  ÃÃÂ¿ÃÂ»ÃÂ°ÃÃÂ¸ÃÃ ÃÂ² CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("Ã¢Â¬Ã¯Â¸ Ã ÃÃÂ°ÃÃÂ¸ÃÃ", callback_data=f"plan:{plan_key}")],
                ])
                msg = await q.edit_message_text(
                    _plan_card_text(plan_key) + "\nÃÃÃÂºÃÃÂ¾ÃÂ¹ÃÃÂµ ÃÃÃÃÂ»ÃÂºÃ ÃÂ´ÃÂ»Ã ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃ:",
                    reply_markup=kb
                )
                # ÃÂ°ÃÂ²ÃÃÂ¾ÃÂ¿ÃÃÂ» ÃÃÃÂ°ÃÃÃÃÂ° ÃÂ¸ÃÂ¼ÃÂµÃÂ½ÃÂ½ÃÂ¾ ÃÂ´ÃÂ»Ã ÃÃÃÃÃÃÂ¡ÃÃ
                context.application.create_task(_poll_crypto_sub_invoice(
                    context, msg.chat.id, msg.message_id, user_id, inv_id, plan_key, 1  # FIX: msg.chat.id
                ))
                await q.answer()
            except Exception as e:
                await q.answer("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂ¾ÃÂ·ÃÂ´ÃÂ°ÃÃ ÃÃÃÃ ÃÂ² CryptoBot.", show_alert=True)
                log.exception("CryptoBot invoice error: %s", e)
            return

        # ÃÂ¡ÃÂ¿ÃÂ¸ÃÃÂ°ÃÂ½ÃÂ¸ÃÂµ Ã ÃÂ²ÃÂ½ÃÃÃÃÂµÃÂ½ÃÂ½ÃÂµÃÂ³ÃÂ¾ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½ÃÃÂ° (USD)
        if method == "balance":
            price_usd = float(plan["usd"])
            if not _user_balance_debit(user_id, price_usd):
                await q.answer("ÃÃÂµÃÂ´ÃÂ¾ÃÃÃÂ°ÃÃÂ¾ÃÃÂ½ÃÂ¾ ÃÃÃÂµÃÂ´ÃÃÃÂ² ÃÂ½ÃÂ° ÃÂ²ÃÂ½ÃÃÃÃÂµÃÂ½ÃÂ½ÃÂµÃÂ¼ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½ÃÃÂµ.", show_alert=True)
                return
            until = _sub_activate(user_id, plan_key, months=1)
            await q.edit_message_text(
                f"Ã¢ ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° {plan['title']} ÃÂ°ÃÂºÃÃÂ¸ÃÂ²ÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ° ÃÂ´ÃÂ¾ {until[:10]}.\n"
                f"Ã°Âµ ÃÂ¡ÃÂ¿ÃÂ¸ÃÃÂ°ÃÂ½ÃÂ¾: {_money_fmt_usd(price_usd)}. "
                f"ÃÂ¢ÃÂµÃÂºÃÃÃÂ¸ÃÂ¹ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã: {_money_fmt_usd(_user_balance_get(user_id))}",
                reply_markup=plans_root_kb(),
            )
            await q.answer()
            return

    # ÃÃÃÂ»ÃÂ¸ ÃÂºÃÂ¾ÃÂ»ÃÃÃÂº ÃÂ½ÃÂµ ÃÂ½ÃÂ°Ã Ã¢ ÃÂ¿ÃÃÂ¾ÃÂ¿ÃÃÃÂºÃÂ°ÃÂµÃÂ¼ ÃÂ´ÃÂ°ÃÂ»ÃÃÃÂµ
    await q.answer()
    return


# ÃÃÃÂ»ÃÂ¸ Ã ÃÃÂµÃÃ ÃÃÂ¶ÃÂµ ÃÂµÃÃÃ on_precheckout / on_successful_payment Ã¢ ÃÂ¾ÃÃÃÂ°ÃÂ²Ã ÃÂ¸Ã.
# ÃÃÃÂ»ÃÂ¸ ÃÂ½ÃÂµÃ, ÃÂ¼ÃÂ¾ÃÂ¶ÃÂµÃÃ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÃÃÂ¸ ÃÂ¿ÃÃÂ¾ÃÃÃÃÂµ ÃÃÂµÃÂ°ÃÂ»ÃÂ¸ÃÂ·ÃÂ°ÃÃÂ¸ÃÂ¸:

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.pre_checkout_query.answer(ok=True)
    except Exception as e:
        log.exception("precheckout error: %s", e)

async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ÃÂ£ÃÂ½ÃÂ¸ÃÂ²ÃÂµÃÃÃÂ°ÃÂ»ÃÃÂ½ÃÃÂ¹ ÃÂ¾ÃÃÃÂ°ÃÃÂ¾ÃÃÃÂ¸ÃÂº Telegram Payments:
    - ÃÃÂ¾ÃÂ´ÃÂ´ÃÂµÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ°ÃÂµÃ payload ÃÂ² ÃÂ´ÃÂ²ÃÃ ÃÃÂ¾ÃÃÂ¼ÃÂ°ÃÃÂ°Ã:
        1) JSON: {"tier":"pro","months":1}
        2) ÃÂ¡ÃÃÃÂ¾ÃÂºÃÂ°: "sub:pro:1"
    - ÃÃÂ½ÃÂ°ÃÃÂµ ÃÃÃÂ°ÃÂºÃÃÃÂµÃ ÃÂºÃÂ°ÃÂº ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂµÃÂ´ÃÂ¸ÃÂ½ÃÂ¾ÃÂ³ÃÂ¾ USD-ÃÂºÃÂ¾ÃÃÂµÃÂ»ÃÃÂºÃÂ°.
    """
    try:
        sp = update.message.successful_payment
        payload_raw = sp.invoice_payload or ""
        total_minor = sp.total_amount or 0
        rub = total_minor / 100.0
        uid = update.effective_user.id

        # 1) ÃÃÃÃÂ°ÃÂµÃÂ¼ÃÃ ÃÃÂ°ÃÃÂ¿ÃÂ°ÃÃÃÂ¸ÃÃ JSON
        tier, months = None, None
        try:
            if payload_raw.strip().startswith("{"):
                obj = json.loads(payload_raw)
                tier = (obj.get("tier") or "").strip().lower() or None
                months = int(obj.get("months") or 1)
        except Exception:
            pass

        # 2) ÃÃÃÃÂ°ÃÂµÃÂ¼ÃÃ ÃÃÂ°ÃÃÂ¿ÃÂ°ÃÃÃÂ¸ÃÃ ÃÃÃÃÂ¾ÃÂºÃÂ¾ÃÂ²ÃÃÂ¹ ÃÃÂ¾ÃÃÂ¼ÃÂ°Ã "sub:tier:months"
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
                f"Ã° ÃÃÂ¿ÃÂ»ÃÂ°ÃÃÂ° ÃÂ¿ÃÃÂ¾ÃÃÂ»ÃÂ° ÃÃÃÂ¿ÃÂµÃÃÂ½ÃÂ¾!\n"
                f"Ã¢ ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° {tier.upper()} ÃÂ°ÃÂºÃÃÂ¸ÃÂ²ÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ° ÃÂ´ÃÂ¾ {until.strftime('%Y-%m-%d')}."
            )
            return

        # ÃÃÂ½ÃÂ°ÃÃÂµ ÃÃÃÂ¸ÃÃÂ°ÃÂµÃÂ¼, ÃÃÃÂ¾ ÃÃÃÂ¾ ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂºÃÂ¾ÃÃÂµÃÂ»ÃÃÂºÃÂ° ÃÂ² ÃÃÃÃÂ»ÃÃ
        usd = rub / max(1e-9, USD_RUB)
        _wallet_total_add(uid, usd)
        await update.effective_message.reply_text(
            f"Ã°Â³ ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ: {rub:.0f} Ã¢Â½ Ã¢ ${usd:.2f} ÃÂ·ÃÂ°ÃÃÂ¸ÃÃÂ»ÃÂµÃÂ½ÃÂ¾ ÃÂ½ÃÂ° ÃÂµÃÂ´ÃÂ¸ÃÂ½ÃÃÂ¹ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã."
        )

    except Exception as e:
        log.exception("successful_payment handler error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Ã¢ Ã¯Â¸ ÃÃÃÂ¸ÃÃÂºÃÂ° ÃÂ¾ÃÃÃÂ°ÃÃÂ¾ÃÃÂºÃÂ¸ ÃÂ¿ÃÂ»ÃÂ°ÃÃÂµÃÂ¶ÃÂ°. ÃÃÃÂ»ÃÂ¸ ÃÂ´ÃÂµÃÂ½ÃÃÂ³ÃÂ¸ ÃÃÂ¿ÃÂ¸ÃÃÂ°ÃÂ»ÃÂ¸ÃÃ Ã¢ ÃÂ½ÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ÃÃÂµ ÃÂ² ÃÂ¿ÃÂ¾ÃÂ´ÃÂ´ÃÂµÃÃÂ¶ÃÂºÃ.")
# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¾ÃÂ½ÃÂµÃ PATCH Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
        
# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¾ÃÂ¼ÃÂ°ÃÂ½ÃÂ´ÃÂ° /img Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip() if context.args else ""
    if not prompt:
        await update.effective_message.reply_text("ÃÂ¤ÃÂ¾ÃÃÂ¼ÃÂ°Ã: /img <ÃÂ¾ÃÂ¿ÃÂ¸ÃÃÂ°ÃÂ½ÃÂ¸ÃÂµ>")
        return

    async def _go():
        await _do_img_generate(update, context, prompt)

    user_id = update.effective_user.id
    await _try_pay_then_do(
        update, context, user_id,
        "img", IMG_COST_USD, _go,
        remember_kind="img_generate", remember_payload={"prompt": prompt}
    )


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Photo quick actions Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
def photo_quick_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Ã¢Â¨ ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ ÃÃÂ¾ÃÃÂ¾", callback_data="pedit:revive")],
        [InlineKeyboardButton("Ã°Â§Â¼ ÃÂ£ÃÂ´ÃÂ°ÃÂ»ÃÂ¸ÃÃ ÃÃÂ¾ÃÂ½",  callback_data="pedit:removebg"),
         InlineKeyboardButton("Ã°Â¼ ÃÃÂ°ÃÂ¼ÃÂµÃÂ½ÃÂ¸ÃÃ ÃÃÂ¾ÃÂ½", callback_data="pedit:replacebg")],
        [InlineKeyboardButton("Ã°Â§Â­ Ã ÃÂ°ÃÃÃÂ¸ÃÃÂ¸ÃÃ ÃÂºÃÂ°ÃÂ´Ã (outpaint)", callback_data="pedit:outpaint"),
         InlineKeyboardButton("Ã°Â½ Ã ÃÂ°ÃÃÂºÃÂ°ÃÂ´ÃÃÂ¾ÃÂ²ÃÂºÃÂ°", callback_data="pedit:story")],
        [InlineKeyboardButton("Ã° ÃÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ° ÃÂ¿ÃÂ¾ ÃÂ¾ÃÂ¿ÃÂ¸ÃÃÂ°ÃÂ½ÃÂ¸Ã (Luma)", callback_data="pedit:lumaimg")],
        [InlineKeyboardButton("Ã° ÃÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÂ· ÃÃÂ¾ÃÃÂ¾", callback_data="pedit:vision")],
    ])


def revive_engine_kb() -> InlineKeyboardMarkup:
    """
    ÃÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ¸ ÃÂ²ÃÃÃÂ¾ÃÃÂ° ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ° ÃÂ´ÃÂ»Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸Ã ÃÃÂ¾ÃÃÂ¾.
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
        await update.effective_message.reply_text("rembg ÃÂ½ÃÂµ ÃÃÃÃÂ°ÃÂ½ÃÂ¾ÃÂ²ÃÂ»ÃÂµÃÂ½. ÃÂ£ÃÃÃÂ°ÃÂ½ÃÂ¾ÃÂ²ÃÂ¸ÃÃÂµ rembg/onnxruntime.")
        return
    try:
        out = rembg_remove(img_bytes)
        bio = BytesIO(out); bio.name = "no_bg.png"
        await update.effective_message.reply_document(InputFile(bio), caption="ÃÂ¤ÃÂ¾ÃÂ½ ÃÃÂ´ÃÂ°ÃÂ»ÃÃÂ½ Ã¢")
    except Exception as e:
        log.exception("removebg error: %s", e)
        await update.effective_message.reply_text("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¸ÃÃ ÃÃÂ¾ÃÂ½.")

async def _pedit_replacebg(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    if Image is None:
        await update.effective_message.reply_text("Pillow ÃÂ½ÃÂµ ÃÃÃÃÂ°ÃÂ½ÃÂ¾ÃÂ²ÃÂ»ÃÂµÃÂ½.")
        return
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGBA")
        bg = im.convert("RGB").filter(ImageFilter.GaussianBlur(radius=22)) if ImageFilter else im.convert("RGB")
        bio = BytesIO(); bg.save(bio, format="JPEG", quality=92); bio.seek(0); bio.name = "bg_blur.jpg"
        await update.effective_message.reply_photo(InputFile(bio), caption="ÃÃÂ°ÃÂ¼ÃÂµÃÂ½ÃÂ¸ÃÂ» ÃÃÂ¾ÃÂ½ ÃÂ½ÃÂ° ÃÃÂ°ÃÂ·ÃÂ¼ÃÃÃÃÂ¹ ÃÂ²ÃÂ°ÃÃÂ¸ÃÂ°ÃÂ½Ã.")
    except Exception as e:
        log.exception("replacebg error: %s", e)
        await update.effective_message.reply_text("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ·ÃÂ°ÃÂ¼ÃÂµÃÂ½ÃÂ¸ÃÃ ÃÃÂ¾ÃÂ½.")

async def _pedit_outpaint(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    if Image is None:
        await update.effective_message.reply_text("Pillow ÃÂ½ÃÂµ ÃÃÃÃÂ°ÃÂ½ÃÂ¾ÃÂ²ÃÂ»ÃÂµÃÂ½.")
        return
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGB")
        pad = max(64, min(256, max(im.size)//6))
        big = Image.new("RGB", (im.width + 2*pad, im.height + 2*pad))
        bg = im.resize(big.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(radius=24)) if ImageFilter else im.resize(big.size)
        big.paste(bg, (0, 0)); big.paste(im, (pad, pad))
        bio = BytesIO(); big.save(bio, format="JPEG", quality=92); bio.seek(0); bio.name = "outpaint.jpg"
        await update.effective_message.reply_photo(InputFile(bio), caption="ÃÃÃÂ¾ÃÃÃÂ¾ÃÂ¹ outpaint: ÃÃÂ°ÃÃÃÂ¸ÃÃÂ¸ÃÂ» ÃÂ¿ÃÂ¾ÃÂ»ÃÂ¾ÃÃÂ½ÃÂ¾ Ã ÃÂ¼ÃÃÂ³ÃÂºÃÂ¸ÃÂ¼ÃÂ¸ ÃÂºÃÃÂ°ÃÃÂ¼ÃÂ¸.")
    except Exception as e:
        log.exception("outpaint error: %s", e)
        await update.effective_message.reply_text("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂ´ÃÂµÃÂ»ÃÂ°ÃÃ outpaint.")

async def _pedit_storyboard(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    try:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        desc = await ask_openai_vision("ÃÃÂ¿ÃÂ¸ÃÃÂ¸ ÃÂºÃÂ»ÃÃÃÂµÃÂ²ÃÃÂµ ÃÃÂ»ÃÂµÃÂ¼ÃÂµÃÂ½ÃÃ ÃÂºÃÂ°ÃÂ´ÃÃÂ° ÃÂ¾ÃÃÂµÃÂ½Ã ÃÂºÃÃÂ°ÃÃÂºÃÂ¾.", b64, sniff_image_mime(img_bytes))
        plan = await ask_openai_text(
            "ÃÂ¡ÃÂ´ÃÂµÃÂ»ÃÂ°ÃÂ¹ ÃÃÂ°ÃÃÂºÃÂ°ÃÂ´ÃÃÂ¾ÃÂ²ÃÂºÃ (6 ÃÂºÃÂ°ÃÂ´ÃÃÂ¾ÃÂ²) ÃÂ¿ÃÂ¾ÃÂ´ 6Ã¢10 ÃÃÂµÃÂºÃÃÂ½ÃÂ´ÃÂ½ÃÃÂ¹ ÃÂºÃÂ»ÃÂ¸ÃÂ¿. "
            "ÃÃÂ°ÃÂ¶ÃÂ´ÃÃÂ¹ ÃÂºÃÂ°ÃÂ´Ã Ã¢ 1 ÃÃÃÃÂ¾ÃÂºÃÂ°: ÃÂºÃÂ°ÃÂ´Ã/ÃÂ´ÃÂµÃÂ¹ÃÃÃÂ²ÃÂ¸ÃÂµ/ÃÃÂ°ÃÂºÃÃÃ/ÃÃÂ²ÃÂµÃ. ÃÃÃÂ½ÃÂ¾ÃÂ²ÃÂ°:\n" + (desc or "")
        )
        await update.effective_message.reply_text("Ã ÃÂ°ÃÃÂºÃÂ°ÃÂ´ÃÃÂ¾ÃÂ²ÃÂºÃÂ°:\ÃÂ½" + plan)
    except Exception as e:
        log.exception("storyboard error: %s", e)
        await update.effective_message.reply_text("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ¿ÃÂ¾ÃÃÃÃÂ¾ÃÂ¸ÃÃ ÃÃÂ°ÃÃÂºÃÂ°ÃÂ´ÃÃÂ¾ÃÂ²ÃÂºÃ.")


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ WebApp data (ÃÃÂ°ÃÃÂ¸ÃÃ/ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸Ã) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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
            desc = f"ÃÃÃÂ¾ÃÃÂ¼ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ¸ {tier.upper()} ÃÂ½ÃÂ° {months} ÃÂ¼ÃÂµÃ."
            await update.effective_message.reply_text(
                f"{desc}\nÃÃÃÃÂµÃÃÂ¸ÃÃÂµ ÃÃÂ¿ÃÂ¾ÃÃÂ¾Ã:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("ÃÃÂ¿ÃÂ»ÃÂ°ÃÃÂ¸ÃÃ ÃÂºÃÂ°ÃÃÃÂ¾ÃÂ¹ (ÃÂ®Kassa)", callback_data=f"buyinv:{tier}:{months}")],
                    [InlineKeyboardButton("ÃÂ¡ÃÂ¿ÃÂ¸ÃÃÂ°ÃÃ Ã ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½ÃÃÂ° (USD)",  callback_data=f"buywallet:{tier}:{months}")],
                ])
            )
            return

        if typ in ("topup_rub", "rub_topup"):
            amount_rub = int(data.get("amount") or 0)
            if amount_rub < MIN_RUB_FOR_INVOICE:
                await update.effective_message.reply_text(f"ÃÃÂ¸ÃÂ½ÃÂ¸ÃÂ¼ÃÂ°ÃÂ»ÃÃÂ½ÃÂ°Ã ÃÃÃÂ¼ÃÂ¼ÃÂ°: {MIN_RUB_FOR_INVOICE} Ã¢Â½")
                return
            await _send_invoice_rub("ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½ÃÃÂ°", "ÃÃÂ´ÃÂ¸ÃÂ½ÃÃÂ¹ ÃÂºÃÂ¾ÃÃÂµÃÂ»ÃÃÂº", amount_rub, "t=3", update)
            return

        if typ in ("topup_crypto", "crypto_topup"):
            if not CRYPTO_PAY_API_TOKEN:
                await update.effective_message.reply_text("CryptoBot ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÃÃÃÂ¾ÃÂµÃÂ½.")
                return
            usd = float(data.get("usd") or 0)
            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(usd, asset="USDT")
            if not inv_id or not pay_url:
                await update.effective_message.reply_text("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂ¾ÃÂ·ÃÂ´ÃÂ°ÃÃ ÃÃÃÃ ÃÂ² CryptoBot.")
                return
            msg = await update.effective_message.reply_text(
                f"ÃÃÂ¿ÃÂ»ÃÂ°ÃÃÂ¸ÃÃÂµ ÃÃÂµÃÃÂµÃÂ· CryptoBot: Ã¢ ${usd_amount:.2f} ({asset}).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("ÃÃÂ¿ÃÂ»ÃÂ°ÃÃÂ¸ÃÃ ÃÂ² CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("ÃÃÃÂ¾ÃÂ²ÃÂµÃÃÂ¸ÃÃ ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃ", callback_data=f"crypto:check:{inv_id}")]
                ])
            )
            context.application.create_task(_poll_crypto_invoice(
                context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id, usd_amount
            ))
            return

        await update.effective_message.reply_text("ÃÃÂ¾ÃÂ»ÃÃÃÂµÃÂ½Ã ÃÂ´ÃÂ°ÃÂ½ÃÂ½ÃÃÂµ ÃÂ¸ÃÂ· ÃÂ¼ÃÂ¸ÃÂ½ÃÂ¸-ÃÂ¿ÃÃÂ¸ÃÂ»ÃÂ¾ÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã, ÃÂ½ÃÂ¾ ÃÂºÃÂ¾ÃÂ¼ÃÂ°ÃÂ½ÃÂ´ÃÂ° ÃÂ½ÃÂµ ÃÃÂ°ÃÃÂ¿ÃÂ¾ÃÂ·ÃÂ½ÃÂ°ÃÂ½ÃÂ°.")
    except Exception as e:
        log.exception("on_webapp_data error: %s", e)
        await update.effective_message.reply_text("ÃÃÃÂ¸ÃÃÂºÃÂ° ÃÂ¾ÃÃÃÂ°ÃÃÂ¾ÃÃÂºÃÂ¸ ÃÂ´ÃÂ°ÃÂ½ÃÂ½ÃÃ ÃÂ¼ÃÂ¸ÃÂ½ÃÂ¸-ÃÂ¿ÃÃÂ¸ÃÂ»ÃÂ¾ÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã.")


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ CallbackQuery (ÃÂ²ÃÃ ÃÂ¾ÃÃÃÂ°ÃÂ»ÃÃÂ½ÃÂ¾ÃÂµ) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

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

        # ÃÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÂ³ÃÂ»ÃÂ°ÃÂ²ÃÂ½ÃÂ¾ÃÂµ ÃÂ¼ÃÂµÃÂ½Ã ÃÂ¿ÃÂ¾ÃÃÂ»ÃÂµ ÃÂ²ÃÃÃÂ¾ÃÃÂ° ÃÃÂ·ÃÃÂºÃÂ°
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

        # ÃÃÂ¾ÃÃÂ¾ÃÃÂºÃÂ¾ÃÂµ ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂ²ÃÂµÃÃÂ¶ÃÂ´ÃÂµÃÂ½ÃÂ¸ÃÂµ + ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂºÃÂ°ÃÂ·ÃÂºÃÂ°
        hint = {
            "gpt": "ÃÂ¢ÃÂµÃÂ¿ÃÂµÃÃ ÃÂ¿ÃÂ¾ ÃÃÂ¼ÃÂ¾ÃÂ»ÃÃÂ°ÃÂ½ÃÂ¸Ã ÃÂ¾ÃÃÂ²ÃÂµÃÃÂ°Ã ÃÃÂµÃÂºÃÃÃÂ¾ÃÂ¼ (GPT).",
            "images": "ÃÂ¢ÃÂµÃÂ¿ÃÂµÃÃ ÃÂ»ÃÃÃÂ¾ÃÂ¹ ÃÃÂµÃÂºÃÃ ÃÃÃÂ´ÃÂµÃ ÃÃÃÂ°ÃÂºÃÃÂ¾ÃÂ²ÃÂ°ÃÃÃÃ ÃÂºÃÂ°ÃÂº ÃÂ¿ÃÃÂ¾ÃÂ¼ÃÂ¿Ã ÃÂ´ÃÂ»Ã ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ¸ (Images).",
            "kling": "ÃÂ¢ÃÂµÃÂ¿ÃÂµÃÃ ÃÂ»ÃÃÃÂ¾ÃÂ¹ ÃÃÂµÃÂºÃÃ ÃÃÃÂ´ÃÂµÃ ÃÃÃÂ°ÃÂºÃÃÂ¾ÃÂ²ÃÂ°ÃÃÃÃ ÃÂºÃÂ°ÃÂº ÃÂ¿ÃÃÂ¾ÃÂ¼ÃÂ¿Ã ÃÂ´ÃÂ»Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÂ² Kling.",
            "luma": "ÃÂ¢ÃÂµÃÂ¿ÃÂµÃÃ ÃÂ»ÃÃÃÂ¾ÃÂ¹ ÃÃÂµÃÂºÃÃ ÃÃÃÂ´ÃÂµÃ ÃÃÃÂ°ÃÂºÃÃÂ¾ÃÂ²ÃÂ°ÃÃÃÃ ÃÂºÃÂ°ÃÂº ÃÂ¿ÃÃÂ¾ÃÂ¼ÃÂ¿Ã ÃÂ´ÃÂ»Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÂ² Luma.",
            "runway": "Runway ÃÂ²ÃÃÃÃÂ°ÃÂ½. ÃÃÂ»Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂ¹ÃÃÂµ ÃÂ«ÃÃÂ´ÃÂµÃÂ»ÃÂ°ÃÂ¹ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾Ã¢Â¦ÃÂ» (ÃÃÂµÃÂºÃÃÃ¢ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÂ¼ÃÂ¾ÃÂ¶ÃÂµÃ ÃÃÃÃ ÃÂ¾ÃÃÂºÃÂ»ÃÃÃÃÂ½).",
            "sora": "Sora ÃÂ²ÃÃÃÃÂ°ÃÂ½ (ÃÃÂµÃÃÂµÃÂ· Comet). ÃÃÃÂ»ÃÂ¸ ÃÂºÃÂ»ÃÃÃÂ¸/ÃÃÂ½ÃÂ´ÃÂ¿ÃÂ¾ÃÂ¸ÃÂ½Ã ÃÂ½ÃÂµ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÂ½Ã Ã¢ ÃÂ¿ÃÂ¾ÃÂºÃÂ°ÃÂ¶Ã ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂºÃÂ°ÃÂ·ÃÂºÃ.",
            "gemini": "Gemini ÃÂ²ÃÃÃÃÂ°ÃÂ½ (ÃÃÂµÃÃÂµÃÂ· Comet). ÃÃÃÂ»ÃÂ¸ ÃÂºÃÂ»ÃÃÃÂ¸/ÃÃÂ½ÃÂ´ÃÂ¿ÃÂ¾ÃÂ¸ÃÂ½Ã ÃÂ½ÃÂµ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÂ½Ã Ã¢ ÃÃÃÂ´ÃÂµÃ ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂºÃÂ°ÃÂ·ÃÂºÃÂ°/ÃÃÂ¾ÃÂ»ÃÃÃÂº.",
            "suno": "Suno ÃÂ²ÃÃÃÃÂ°ÃÂ½ (ÃÂ¼ÃÃÂ·ÃÃÂºÃÂ°). ÃÂ¡ÃÂµÃÂ¹ÃÃÂ°Ã ÃÂ²ÃÂºÃÂ»ÃÃÃÃÂ½ ÃÂºÃÂ°ÃÂº ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼-ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂºÃÂ°ÃÂ·ÃÂºÃÂ°.",
            "midjourney": "Midjourney ÃÂ²ÃÃÃÃÂ°ÃÂ½. ÃÂ¡ÃÂµÃÂ¹ÃÃÂ°Ã ÃÂ²ÃÂºÃÂ»ÃÃÃÃÂ½ ÃÂºÃÂ°ÃÂº ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼-ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂºÃÂ°ÃÂ·ÃÂºÃÂ°.",
            "stt_tts": "Ã ÃÂµÃÂ¶ÃÂ¸ÃÂ¼ STT/TTS: ÃÂ¼ÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ ÃÂ¿ÃÃÂ¸ÃÃÂ»ÃÂ°ÃÃ ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾ÃÂµ ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ²ÃÂºÃÂ»ÃÃÃÂ¸ÃÃ ÃÂ¾ÃÂ·ÃÂ²ÃÃÃÂºÃ ÃÂ¾ÃÃÂ²ÃÂµÃÃÂ¾ÃÂ².",
        }.get(eng, f"ÃÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº ÃÂ²ÃÃÃÃÂ°ÃÂ½: {eng}")

        with contextlib.suppress(Exception):
            await q.message.reply_text(hint, reply_markup=main_keyboard(uid))
        return

    try:
        # Ã° ÃÃÃÃÂ¾Ã ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ° ÃÂ´ÃÂ»Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸Ã ÃÃÂ¾ÃÃÂ¾ (Runway/Kling/Luma)
        if data.startswith("revive_engine:"):
            await q.answer()
            engine = data.split(":", 1)[1] if ":" in data else ""
            await revive_old_photo_flow(update, context, engine=engine)
            return

        # Photo edit / ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ°ÃÃÂ¸Ã ÃÂ¿ÃÂ¾ inline-ÃÂºÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ°ÃÂ¼ pedit:...
        if data.startswith("pedit:"):
            await q.answer()
            action = data.split(":", 1)[1] if ":" in data else ""
            user_id = update.effective_user.id

            # ÃÂ¡ÃÂ¿ÃÂµÃÃÂ¸ÃÂ°ÃÂ»ÃÃÂ½ÃÃÂ¹ ÃÃÂ»ÃÃÃÂ°ÃÂ¹: ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂ¾ÃÃÂ¾ Ã¢ ÃÂ¿ÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÂ°ÃÃ ÃÂ²ÃÃÃÂ¾Ã ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ°
            if action == "revive":
                if user_id not in _LAST_ANIM_PHOTO:
                    await q.edit_message_text(
                        "ÃÃÂµ ÃÂ½ÃÂ°ÃÃÃÂ» ÃÃÂ¾ÃÃÂ¾ ÃÂ² ÃÂºÃÃÃÂµ. ÃÃÃÂ¸ÃÃÂ»ÃÂ¸ ÃÃÂ¾ÃÃÂ¾ ÃÂµÃÃ ÃÃÂ°ÃÂ·, ÃÂ¿ÃÂ¾ÃÂ¶ÃÂ°ÃÂ»ÃÃÂ¹ÃÃÃÂ°."
                    )
                    return

                await q.edit_message_text(
                    "ÃÃÃÃÂµÃÃÂ¸ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº ÃÂ´ÃÂ»Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸Ã ÃÃÂ¾ÃÃÂ¾:",
                    reply_markup=revive_engine_kb(),
                )
                return

            # ÃÃÂ»Ã ÃÂ¾ÃÃÃÂ°ÃÂ»ÃÃÂ½ÃÃ pedit:* ÃÂ½ÃÃÂ¶ÃÂµÃÂ½ ÃÃÂ°ÃÂ¹ÃÃÂ¾ÃÂ²ÃÃÂ¹ ÃÂ¾ÃÃÃÂ°ÃÂ· ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ¸
            img = _get_cached_photo(user_id)
            if not img:
                await q.edit_message_text(
                    "ÃÃÂµ ÃÂ½ÃÂ°ÃÃÃÂ» ÃÃÂ¾ÃÃÂ¾ ÃÂ² ÃÂºÃÃÃÂµ. ÃÃÃÂ¸ÃÃÂ»ÃÂ¸ ÃÃÂ¾ÃÃÂ¾ ÃÂµÃÃ ÃÃÂ°ÃÂ·, ÃÂ¿ÃÂ¾ÃÂ¶ÃÂ°ÃÂ»ÃÃÂ¹ÃÃÃÂ°."
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

            # ÃÂ½ÃÂµÃÂ¸ÃÂ·ÃÂ²ÃÂµÃÃÃÂ½ÃÃÂ¹ pedit:* Ã¢ ÃÂ¿ÃÃÂ¾ÃÃÃÂ¾ ÃÂ²ÃÃÃÂ¾ÃÂ´ÃÂ¸ÃÂ¼
            return

        # TOPUP ÃÂ¼ÃÂµÃÂ½Ã
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
                    f"ÃÃÂ¸ÃÂ½ÃÂ¸ÃÂ¼ÃÂ°ÃÂ»ÃÃÂ½ÃÂ°Ã ÃÃÃÂ¼ÃÂ¼ÃÂ° ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸Ã {MIN_RUB_FOR_INVOICE} Ã¢Â½."
                )
                return
            title = "ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½ÃÃÂ° (ÃÂºÃÂ°ÃÃÃÂ°)"
            desc = f"ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ USD-ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½ÃÃÂ° ÃÃÂ¾ÃÃÂ° ÃÂ½ÃÂ° ÃÃÃÂ¼ÃÂ¼Ã Ã¢ {amount_rub} Ã¢Â½"
            payload = f"topup:{amount_rub}"
            ok = await _send_invoice_rub(title, desc, amount_rub, payload, update)
            if not ok:
                await q.answer("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ²ÃÃÃÃÂ°ÃÂ²ÃÂ¸ÃÃ ÃÃÃÃ", show_alert=True)
            return

        # TOPUP CRYPTO: ÃÂ²ÃÃÃÂ¾Ã ÃÃÃÂ¼ÃÂ¼Ã
        if data == "topup:crypto":
            await q.answer()
            await q.edit_message_text(
                "ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂµÃÃÂµÃÂ· CryptoBot (USDT):\n\n"
                "ÃÃÃÃÂµÃÃÂ¸ÃÃÂµ ÃÃÃÂ¼ÃÂ¼Ã ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸Ã ($):",
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
                        [InlineKeyboardButton("ÃÃÃÂ¼ÃÂµÃÂ½ÃÂ°", callback_data="topup:cancel")],
                    ]
                ),
            )
            return

        # TOPUP CRYPTO: ÃÃÂ¾ÃÂ·ÃÂ´ÃÂ°ÃÂ½ÃÂ¸ÃÂµ ÃÂ¸ÃÂ½ÃÂ²ÃÂ¾ÃÂ¹ÃÃÂ°
        if data.startswith("topup:crypto:"):
            await q.answer()
            try:
                usd = float((data.split(":", 2)[-1] or "0").strip() or "0")
            except Exception:
                usd = 0.0
            if usd <= 0.0:
                await q.edit_message_text("ÃÃÂµÃÂ²ÃÂµÃÃÂ½ÃÂ°Ã ÃÃÃÂ¼ÃÂ¼ÃÂ°.")
                return

            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(
                usd, asset="USDT", description="Wallet top-up"
            )
            if not inv_id or not pay_url:
                await q.edit_message_text(
                    "ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂ¾ÃÂ·ÃÂ´ÃÂ°ÃÃ ÃÃÃÃ ÃÂ² CryptoBot. ÃÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃÃÂ¹ÃÃÂµ ÃÂ¿ÃÂ¾ÃÂ·ÃÂ¶ÃÂµ."
                )
                return

            msg = await update.effective_message.reply_text(
                f"ÃÃÂ¿ÃÂ»ÃÂ°ÃÃÂ¸ÃÃÂµ ÃÃÂµÃÃÂµÃÂ· CryptoBot: Ã¢ ${usd_amount:.2f} ({asset}).\n"
                "ÃÃÂ¾ÃÃÂ»ÃÂµ ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂ¸ÃÃÃ ÃÂ°ÃÂ²ÃÃÂ¾ÃÂ¼ÃÂ°ÃÃÂ¸ÃÃÂµÃÃÂºÃÂ¸.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("ÃÃÂ¿ÃÂ»ÃÂ°ÃÃÂ¸ÃÃ ÃÂ² CryptoBot", url=pay_url)],
                        [InlineKeyboardButton("ÃÃÃÂ¾ÃÂ²ÃÂµÃÃÂ¸ÃÃ ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃ", callback_data=f"crypto:check:{inv_id}")],
                    ]
                ),
            )
            # ÃÂ·ÃÂ°ÃÂ¿ÃÃÃÃÂ¸ÃÂ¼ ÃÃÂ¾ÃÂ½ÃÂ¾ÃÂ²ÃÃÂ¹ ÃÂ¿ÃÂ¾ÃÂ»ÃÂ»ÃÂ¸ÃÂ½ÃÂ³ ÃÂ¸ÃÂ½ÃÂ²ÃÂ¾ÃÂ¹ÃÃÂ°
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

        # CryptoBot: ÃÃÃÃÂ½ÃÂ°Ã ÃÂ¿ÃÃÂ¾ÃÂ²ÃÂµÃÃÂºÃÂ° ÃÂ¸ÃÂ½ÃÂ²ÃÂ¾ÃÂ¹ÃÃÂ°
        if data.startswith("crypto:check:"):
            await q.answer()
            inv_id = data.split(":", 2)[-1]
            inv = await _crypto_get_invoice(inv_id)
            status = (inv or {}).get("status", "").lower() if inv else ""
            paid_amount = (inv or {}).get("amount") or 0
            asset = (inv or {}).get("asset") or "USDT"

            if status == "paid":
                await q.edit_message_text(
                    f"Ã¢ ÃÃÂ»ÃÂ°ÃÃÃÂ¶ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂµÃÂ½: {paid_amount} {asset}.\n"
                    "ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã ÃÃÃÂ´ÃÂµÃ ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ ÃÂ² ÃÃÂµÃÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ¼ÃÂ¸ÃÂ½ÃÃÃ."
                )
            elif status == "active":
                await q.edit_message_text("ÃÂ¡ÃÃÃ ÃÂµÃÃ ÃÂ½ÃÂµ ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃÂµÃÂ½.")
            else:
                await q.edit_message_text("ÃÂ¡ÃÃÃ ÃÂ½ÃÂµ ÃÂ°ÃÂºÃÃÂ¸ÃÂ²ÃÂµÃÂ½ ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ¸ÃÃÃÃÂº.")
            return

        # TOPUP cancel
        if data == "topup:cancel":
            await q.answer()
            await q.edit_message_text("ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ¾ÃÃÂ¼ÃÂµÃÂ½ÃÂµÃÂ½ÃÂ¾.")
            return

        # ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ°: ÃÃÃÂ°ÃÃÂ¾ÃÂµ ÃÂ¼ÃÂµÃÂ½Ã /plans (ÃÂµÃÃÂ»ÃÂ¸ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÃ)
        if data == "plans":
            await q.answer()
            await cmd_plans(update, context)
            return

        # ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ°: ÃÂ²ÃÃÃÂ¾Ã ÃÃÂ°ÃÃÂ¸ÃÃÂ° ÃÂ¸ ÃÃÃÂ¾ÃÂºÃÂ°
        if data.startswith("buy:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            desc = f"ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° {tier.upper()} ÃÂ½ÃÂ° {months} ÃÂ¼ÃÂµÃ."
            await q.edit_message_text(
                f"{desc}\nÃÃÃÃÂµÃÃÂ¸ÃÃÂµ ÃÃÂ¿ÃÂ¾ÃÃÂ¾Ã ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃ:",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "ÃÃÂ¿ÃÂ»ÃÂ°ÃÃÂ¸ÃÃ ÃÂºÃÂ°ÃÃÃÂ¾ÃÂ¹ (ÃÂ®Kassa)",
                                callback_data=f"buyinv:{tier}:{months}",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "ÃÂ¡ÃÂ¿ÃÂ¸ÃÃÂ°ÃÃ Ã ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½ÃÃÂ° (USD)",
                                callback_data=f"buywallet:{tier}:{months}",
                            )
                        ],
                    ]
                ),
            )
            return

        # ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° ÃÃÂµÃÃÂµÃÂ· ÃÂ®Kassa
        if data.startswith("buyinv:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            payload, amount_rub, title = _plan_payload_and_amount(tier, months)
            desc = f"ÃÃÃÂ¾ÃÃÂ¼ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ¸ {tier.upper()} ÃÂ½ÃÂ° {months} ÃÂ¼ÃÂµÃ."
            ok = await _send_invoice_rub(title, desc, amount_rub, payload, update)
            if not ok:
                await q.answer("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ²ÃÃÃÃÂ°ÃÂ²ÃÂ¸ÃÃ ÃÃÃÃ", show_alert=True)
            return

        # ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° ÃÃÂ¿ÃÂ¸ÃÃÂ°ÃÂ½ÃÂ¸ÃÂµÃÂ¼ ÃÂ¸ÃÂ· USD-ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½ÃÃÂ°
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
                    f"ÃÃÂ° ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½ÃÃÂµ ÃÂ½ÃÂµÃÂ´ÃÂ¾ÃÃÃÂ°ÃÃÂ¾ÃÃÂ½ÃÂ¾ ÃÃÃÂµÃÂ´ÃÃÃÂ².\n"
                    f"ÃÂ¢ÃÃÂµÃÃÃÂµÃÃÃ ÃÂµÃÃ Ã¢ ${need:.2f}.\n\n"
                    "ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂ¸ÃÃÂµ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã ÃÃÂµÃÃÂµÃÂ· ÃÂ¼ÃÂµÃÂ½Ã ÃÂ«Ã°Â§Â¾ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½ÃÃÂ».",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("Ã¢ ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂ¸ÃÃ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã", callback_data="topup")]]
                    ),
                )
                return
            # ÃÃÂ¿ÃÂ¸ÃÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÂ¸ ÃÂ°ÃÂºÃÃÂ¸ÃÂ²ÃÂ¸ÃÃÃÂµÃÂ¼
            _user_balance_debit(update.effective_user.id, usd_price)
            tier_name = payload.split(":", 1)[-1]
            activate_subscription_with_tier(update.effective_user.id, tier_name, months)
            await q.edit_message_text(
                f"Ã¢ ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° {tier_name.upper()} ÃÂ½ÃÂ° {months} ÃÂ¼ÃÂµÃ. ÃÂ¾ÃÃÂ¾ÃÃÂ¼ÃÂ»ÃÂµÃÂ½ÃÂ°.\n"
                f"ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã: ${_user_balance_get(update.effective_user.id):.2f}"
            )
            return

        # ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã: ÃÂ¿ÃÃÂ¾ÃÃÃÂ¾ ÃÂ¾ÃÃÂºÃÃÃÃ ÃÂ¼ÃÂµÃÂ½Ã
        if data == "balance:open":
            await q.answer()
            await cmd_balance(update, context)
            return

        # ÃÃÃÃÂµÃ ÃÂ½ÃÂ° ÃÂ´ÃÂ¾ÃÂ¿.ÃÃÂ°ÃÃÃÂ¾ÃÂ´ (ÃÂºÃÂ¾ÃÂ³ÃÂ´ÃÂ° ÃÂ½ÃÂµ ÃÃÂ²ÃÂ°ÃÃÂ¸ÃÂ»ÃÂ¾ ÃÂ»ÃÂ¸ÃÂ¼ÃÂ¸ÃÃÂ°)
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
                f"ÃÃÂ°Ã ÃÂ´ÃÂ½ÃÂµÃÂ²ÃÂ½ÃÂ¾ÃÂ¹ ÃÂ»ÃÂ¸ÃÂ¼ÃÂ¸Ã ÃÂ¿ÃÂ¾ ÃÂ«{engine}ÃÂ» ÃÂ¸ÃÃÃÂµÃÃÂ¿ÃÂ°ÃÂ½. Ã ÃÂ°ÃÂ·ÃÂ¾ÃÂ²ÃÂ°Ã ÃÂ¿ÃÂ¾ÃÂºÃÃÂ¿ÃÂºÃÂ° Ã¢ {amount_rub} Ã¢Â½ "
                "ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂ¸ÃÃÂµ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã ÃÂ² ÃÂ«Ã°Â§Â¾ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½ÃÃÂ».",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("Ã¢Â­ ÃÂ¢ÃÂ°ÃÃÂ¸ÃÃ", web_app=WebAppInfo(url=TARIFF_URL))],
                        [InlineKeyboardButton("Ã¢ ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂ¸ÃÃ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã", callback_data="topup")],
                    ]
                ),
            )
            return

        # Ã ÃÂµÃÂ¶ÃÂ¸ÃÂ¼Ã / ÃÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸
        if data == "mode:engines":
            await q.answer()
            await q.edit_message_text("ÃÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸:", reply_markup=engines_kb())
            return

        if data.startswith("mode:set:"):
            await q.answer()
            _, _, mode = data.split(":", 2)
            _mode_set(update.effective_user.id, mode)
            if mode == "none":
                await q.edit_message_text("Ã ÃÂµÃÂ¶ÃÂ¸ÃÂ¼ ÃÂ²ÃÃÂºÃÂ»ÃÃÃÂµÃÂ½.")
            else:
                await q.edit_message_text(
                    f"Ã ÃÂµÃÂ¶ÃÂ¸ÃÂ¼ ÃÂ«{mode}ÃÂ» ÃÂ²ÃÂºÃÂ»ÃÃÃÃÂ½. ÃÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ÃÃÂµ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÂ½ÃÂ¸ÃÂµ."
                )
            return

        # ÃÃÂ¾ÃÂ´ÃÃÂ²ÃÂµÃÃÂ¶ÃÂ´ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ²ÃÃÃÂ¾ÃÃÂ° ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ° ÃÂ´ÃÂ»Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ (Kling / Luma / Runway)
        if data.startswith("choose:"):
            await q.answer()
            _, engine, aid = data.split(":", 2)
            meta = _pending_actions.pop(aid, None)
            if not meta:
                await q.answer("ÃÃÂ°ÃÂ´ÃÂ°ÃÃÂ° ÃÃÃÃÂ°ÃÃÂµÃÂ»ÃÂ°", show_alert=True)
                return

            prompt   = (meta.get("prompt") or "").strip()
            duration = normalize_seconds(int(meta.get("duration") or LUMA_DURATION_S))
            aspect   = normalize_aspect(str(meta.get("aspect") or "16:9"))

            uid = update.effective_user.id
            tier = get_subscription_tier(uid)

            # Runway ÃÂ´ÃÂ»Ã text/voiceÃ¢video ÃÂ¾ÃÃÂºÃÂ»ÃÃÃÃÂ½ (ÃÂ¾ÃÃÃÂ°ÃÂ²ÃÂ»ÃÃÂµÃÂ¼ ÃÃÂ¾ÃÂ»ÃÃÂºÃÂ¾ Kling/Luma/Sora)
            if engine == "runway":
                await q.message.reply_text("Ã¢ Ã¯Â¸ Runway ÃÂ¾ÃÃÂºÃÂ»ÃÃÃÃÂ½ ÃÂ´ÃÂ»Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÂ¿ÃÂ¾ ÃÃÂµÃÂºÃÃÃ/ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃ. ÃÃÃÃÂµÃÃÂ¸ÃÃÂµ Kling, Luma ÃÂ¸ÃÂ»ÃÂ¸ Sora.")
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
                await q.answer("ÃÃÂµÃÂ¸ÃÂ·ÃÂ²ÃÂµÃÃÃÂ½ÃÃÂ¹ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº", show_alert=True)
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

        # ÃÃÃÂ»ÃÂ¸ ÃÂ½ÃÂµ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ¾ÃÃÂ»ÃÂ° ÃÂ½ÃÂ¸ ÃÂ¾ÃÂ´ÃÂ½ÃÂ° ÃÂ²ÃÂµÃÃÂºÃÂ°
        await q.answer("ÃÃÂµÃÂ¸ÃÂ·ÃÂ²ÃÂµÃÃÃÂ½ÃÂ°Ã ÃÂºÃÂ¾ÃÂ¼ÃÂ°ÃÂ½ÃÂ´ÃÂ°", show_alert=True)

    except Exception as e:
        log.exception("on_cb error: %s", e)
    finally:
        with contextlib.suppress(Exception):
            await q.answer()



# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ STT Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¸ÃÂ°ÃÂ³ÃÂ½ÃÂ¾ÃÃÃÂ¸ÃÂºÃÂ° ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¾ÃÂ² Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def cmd_diag_stt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = []
    lines.append("Ã° STT ÃÂ´ÃÂ¸ÃÂ°ÃÂ³ÃÂ½ÃÂ¾ÃÃÃÂ¸ÃÂºÃÂ°:")
    lines.append(f"Ã¢Â¢ OpenAI Whisper: {'Ã¢ ÃÂºÃÂ»ÃÂ¸ÃÂµÃÂ½Ã ÃÂ°ÃÂºÃÃÂ¸ÃÂ²ÃÂµÃÂ½' if oai_stt else 'Ã¢ ÃÂ½ÃÂµÃÂ´ÃÂ¾ÃÃÃÃÂ¿ÃÂµÃÂ½'}")
    lines.append(f"Ã¢Â¢ ÃÃÂ¾ÃÂ´ÃÂµÃÂ»Ã Whisper: {TRANSCRIBE_MODEL}")
    lines.append("Ã¢Â¢ ÃÃÂ¾ÃÂ´ÃÂ´ÃÂµÃÃÂ¶ÃÂºÃÂ° ÃÃÂ¾ÃÃÂ¼ÃÂ°ÃÃÂ¾ÃÂ²: ogg/oga, mp3, m4a/mp4, wav, webm")
    await update.effective_message.reply_text("\n".join(lines))

async def cmd_diag_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key_env  = os.environ.get("OPENAI_IMAGE_KEY", "").strip()
    key_used = key_env or OPENAI_API_KEY
    base     = IMAGES_BASE_URL
    lines = [
        "Ã°Â§Âª Images (OpenAI) ÃÂ´ÃÂ¸ÃÂ°ÃÂ³ÃÂ½ÃÂ¾ÃÃÃÂ¸ÃÂºÃÂ°:",
        f"Ã¢Â¢ OPENAI_IMAGE_KEY: {'Ã¢ ÃÂ½ÃÂ°ÃÂ¹ÃÂ´ÃÂµÃÂ½' if key_used else 'Ã¢ ÃÂ½ÃÂµÃ'}",
        f"Ã¢Â¢ BASE_URL: {base}",
        f"Ã¢Â¢ MODEL: {IMAGES_MODEL}",
    ]
    if "openrouter" in (base or "").lower():
        lines.append("Ã¢ Ã¯Â¸ BASE_URL ÃÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÂµÃ ÃÂ½ÃÂ° OpenRouter Ã¢ ÃÃÂ°ÃÂ¼ ÃÂ½ÃÂµÃ gpt-image-1.")
        lines.append("   ÃÂ£ÃÂºÃÂ°ÃÂ¶ÃÂ¸ https://api.openai.com/v1 (ÃÂ¸ÃÂ»ÃÂ¸ ÃÃÂ²ÃÂ¾ÃÂ¹ ÃÂ¿ÃÃÂ¾ÃÂºÃÃÂ¸) ÃÂ² OPENAI_IMAGE_BASE_URL.")
    await update.effective_message.reply_text("\n".join(lines))

async def cmd_diag_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    lines = [
        "Ã°Â¬ ÃÃÂ¸ÃÂ´ÃÂµÃÂ¾-ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸:",
        # Luma
        f"Ã¢Â¢ Luma key: {'Ã¢' if bool(LUMA_API_KEY) else 'Ã¢'}  base={LUMA_BASE_URL}",
        f"  create={LUMA_CREATE_PATH}  status={LUMA_STATUS_PATH}",
        f"  model={LUMA_MODEL}  durations=['5s','9s','10s']  aspect=['16:9','9:16','1:1']",
        "",
        # Kling ÃÃÂµÃÃÂµÃÂ· CometAPI
        f"Ã¢Â¢ Kling key (COMETAPI_KEY): {'Ã¢' if bool(COMETAPI_KEY) else 'Ã¢'}  base={KLING_BASE_URL}",
        f"  model_name={KLING_MODEL_NAME}  mode={KLING_MODE}  aspect={KLING_ASPECT}  duration={KLING_DURATION_S}s",
        "",
        # Runway (ÃÃÂµÃÂºÃÃÃÂ¸ÃÂ¹ DEV ÃÂ¸ÃÂ»ÃÂ¸ Comet Ã¢ ÃÂ½ÃÂµÃÂ²ÃÂ°ÃÂ¶ÃÂ½ÃÂ¾, ÃÂ¿ÃÃÂ¾ÃÃÃÂ¾ ÃÂ¿ÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÂºÃÂ¾ÃÂ½ÃÃÂ¸ÃÂ³)
        f"Ã¢Â¢ Runway key: {'Ã¢' if bool(RUNWAY_API_KEY) else 'Ã¢'}  base={RUNWAY_BASE_URL}",
        f"  text2video={RUNWAY_TEXT2VIDEO_PATH}  image2video={RUNWAY_IMAGE2VIDEO_PATH}",
        f"  api_version={RUNWAY_API_VERSION}",
        "",
        f"Ã¢Â¢ ÃÃÂ¾ÃÂ»ÃÂ»ÃÂ¸ÃÂ½ÃÂ³ ÃÂºÃÂ°ÃÂ¶ÃÂ´ÃÃÂµ {VIDEO_POLL_DELAY_S:.1f} c",
    ]

    await msg.reply_text("\n".join(lines))

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ MIME ÃÂ´ÃÂ»Ã ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂ¹ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ°ÃÃ ÃÂ¾ÃÂ¿ÃÃÂ¸ÃÂ¹ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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
    m = re.search(r"(\d+)\s*(?:ÃÃÂµÃÂº|Ã)\b", tl)
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
    ÃÃÂ°ÃÂ¿ÃÃÃÂº ÃÃÂµÃÂ½ÃÂ´ÃÂµÃÃÂ° ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÂ² Kling (ÃÃÂµÃÃÂµÃÂ· CometAPI) ÃÂ¸ ÃÂ¾ÃÃÂ¿ÃÃÂ°ÃÂ²ÃÂºÃÂ° ÃÃÂµÃÂ·ÃÃÂ»ÃÃÃÂ°ÃÃÂ°
    ÃÂ² Telegram ÃÃÂ¶ÃÂµ ÃÂºÃÂ°ÃÂº mp4-ÃÃÂ°ÃÂ¹ÃÂ»ÃÂ°, ÃÂ° ÃÂ½ÃÂµ ÃÂ¿ÃÃÂ¾ÃÃÃÂ¾ ÃÃÃÃÂ»ÃÂºÃÂ¾ÃÂ¹.
    """
    msg = update.effective_message

    if not COMETAPI_KEY:
        await msg.reply_text("Ã¢ Ã¯Â¸ Kling ÃÃÂµÃÃÂµÃÂ· CometAPI ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÃÃÃÂ¾ÃÂµÃÂ½ (ÃÂ½ÃÂµÃ COMETAPI_KEY).")
        return False

    # ÃÃÂ¾ÃÃÂ¼ÃÂ°ÃÂ»ÃÂ¸ÃÂ·ÃÃÂµÃÂ¼ ÃÂ´ÃÂ»ÃÂ¸ÃÃÂµÃÂ»ÃÃÂ½ÃÂ¾ÃÃÃ ÃÂ¸ ÃÂ°ÃÃÂ¿ÃÂµÃÂºÃ
    dur = str(max(1, min(duration, 10)))   # Kling ÃÂ¶ÃÂ´ÃÃ ÃÃÃÃÂ¾ÃÂºÃ "5" / "10"
    aspect_ratio = aspect.replace(" ", "") # "16:9", "9:16" ÃÂ¸ Ã.ÃÂ¿.

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            create_url = f"{KLING_BASE_URL}/kling/v1/videos/text2video"

            headers = {
                "Authorization": f"Bearer {COMETAPI_KEY}",  # ÃÂºÃÂ»ÃÃ CometAPI
                "Content-Type": "application/json",
            }

            payload = {
                "prompt": prompt.strip(),
                "model_name": KLING_MODEL_NAME,   # ÃÂ½ÃÂ°ÃÂ¿Ã. "kling-v1-6"
                "mode": KLING_MODE,              # "std" ÃÂ¸ÃÂ»ÃÂ¸ "pro"
                "duration": dur,                 # "5" ÃÂ¸ÃÂ»ÃÂ¸ "10"
                "aspect_ratio": aspect_ratio,    # "16:9", "9:16", "1:1" ...
            }

            log.info("Kling create payload: %r", payload)
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code != 200:
                txt = (r.text or "")[:800]
                log.warning("Kling create error %s: %s", r.status_code, txt)
                await msg.reply_text(
                    f"Ã¢ Ã¯Â¸ Kling (textÃ¢video) ÃÂ¾ÃÃÂºÃÂ»ÃÂ¾ÃÂ½ÃÂ¸ÃÂ» ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃ ({r.status_code}).\n"
                    f"ÃÃÃÂ²ÃÂµÃ ÃÃÂµÃÃÂ²ÃÂµÃÃÂ°:\n`{txt}`",
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
                    "Ã¢ Ã¯Â¸ Kling: ÃÂ½ÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂ¸ÃÃ task_id ÃÂ¸ÃÂ· ÃÂ¾ÃÃÂ²ÃÂµÃÃÂ°.\n"
                    f"ÃÂ¡ÃÃÃÂ¾ÃÂ¹ ÃÂ¾ÃÃÂ²ÃÂµÃ ÃÃÂµÃÃÂ²ÃÂµÃÃÂ°: {js}"
                )
                return False

            await msg.reply_text("Ã¢Â³ Kling: ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃÂ° ÃÂ¿ÃÃÂ¸ÃÂ½ÃÃÃÂ°, ÃÂ½ÃÂ°ÃÃÂ¸ÃÂ½ÃÂ°Ã ÃÃÂµÃÂ½ÃÂ´ÃÂµÃ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾Ã¢Â¦")

            # ÃÃÃÂ»ÃÂ¸ÃÂ¼ ÃÃÃÂ°ÃÃÃ ÃÂ¿ÃÂ¾ GET /kling/v1/videos/text2video/{task_id}
            status_url = f"{KLING_BASE_URL}/kling/v1/videos/text2video/{task_id}"
            started = time.time()

            while True:
                if time.time() - started > 600:  # 10 ÃÂ¼ÃÂ¸ÃÂ½ÃÃ
                    await msg.reply_text("Ã¢ Ã¯Â¸ Kling: ÃÂ¿ÃÃÂµÃÂ²ÃÃÃÂµÃÂ½ ÃÂ»ÃÂ¸ÃÂ¼ÃÂ¸Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ´ÃÂ°ÃÂ½ÃÂ¸Ã ÃÃÂµÃÂ½ÃÂ´ÃÂµÃÃÂ° (>10 ÃÂ¼ÃÂ¸ÃÂ½ÃÃ).")
                    return False

                sr = await client.get(status_url, headers=headers)
                if sr.status_code != 200:
                    txt = (sr.text or "")[:500]
                    log.warning("Kling status error %s: %s", sr.status_code, txt)
                    await msg.reply_text(
                        f"Ã¢ Ã¯Â¸ Kling status error ({sr.status_code}).\n"
                        f"ÃÃÃÂ²ÃÂµÃ ÃÃÂµÃÃÂ²ÃÂµÃÃÂ°:\n`{txt}`",
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
                    # ÃÃÂ°ÃÃÂ°ÃÂµÃÂ¼ ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾ÃÂµ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾
                    vr = await client.get(video_url, timeout=300)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(
                            "Ã¢ Ã¯Â¸ Kling: ÃÂ½ÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂºÃÂ°ÃÃÂ°ÃÃ ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾ÃÂµ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ "
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
                        f"Ã¢ Kling ÃÂ·ÃÂ°ÃÂ²ÃÂµÃÃÃÂ¸ÃÂ»ÃÃ Ã ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ¾ÃÂ¹: `{err}`",
                        parse_mode="Markdown",
                    )
                    return False

                # ÃÃÂ½ÃÂ°ÃÃÂµ Ã¢ ÃÂ¶ÃÂ´ÃÃÂ¼ ÃÂ´ÃÂ°ÃÂ»ÃÃÃÂµ
                await asyncio.sleep(5.0)

    except Exception as e:
        log.exception("Kling text2video exception: %s", e)
        await msg.reply_text("Ã¢ Kling: ÃÂ²ÃÂ½ÃÃÃÃÂµÃÂ½ÃÂ½ÃÃ ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ° ÃÂ¿ÃÃÂ¸ ÃÃÂµÃÂ½ÃÂ´ÃÂµÃÃÂµ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾.")
    return False
def _normalize_luma_aspect(aspect: str | None) -> str:
    """
    Luma Dream Machine ÃÂ¿ÃÂ¾ÃÂ´ÃÂ´ÃÂµÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ°ÃÂµÃ ÃÂ¾ÃÂ³ÃÃÂ°ÃÂ½ÃÂ¸ÃÃÂµÃÂ½ÃÂ½ÃÃÂ¹ ÃÂ½ÃÂ°ÃÃÂ¾Ã ÃÂ°ÃÃÂ¿ÃÂµÃÂºÃÃÂ¾ÃÂ².
    ÃÃÃÂ¸ÃÂ²ÃÂ¾ÃÂ´ÃÂ¸ÃÂ¼ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃÂµÃÂ»ÃÃÃÂºÃÂ¸ÃÂ¹ ÃÂ°ÃÃÂ¿ÃÂµÃÂºÃ ÃÂº ÃÂ´ÃÂ¾ÃÂ¿ÃÃÃÃÂ¸ÃÂ¼ÃÂ¾ÃÂ¼Ã ÃÂ·ÃÂ½ÃÂ°ÃÃÂµÃÂ½ÃÂ¸Ã.
    """
    allowed = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"}
    if not aspect:
        a = (LUMA_ASPECT or "16:9").replace(" ", "")
    else:
        a = aspect.replace(" ", "")

    if a in allowed:
        return a

    # ÃÃÃÂ³ÃÂºÃÂ°Ã ÃÂºÃÂ¾ÃÃÃÂµÃÂºÃÃÂ¸Ã ÃÂ«ÃÂ¿ÃÂ¾ÃÃÂ¾ÃÂ¶ÃÂ¸ÃÃÂ» ÃÃÂ¾ÃÃÂ¼ÃÂ°ÃÃÂ¾ÃÂ²
    mapping = {
        "4:5": "3:4",
        "5:4": "4:3",
    }
    if a in mapping:
        return mapping[a]

    return "16:9"

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¾ÃÂºÃÃÂ¿ÃÂºÃÂ¸/ÃÂ¸ÃÂ½ÃÂ²ÃÂ¾ÃÂ¹ÃÃ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
def _plan_rub(tier: str, term: str) -> int:
    tier = (tier or "pro").lower()
    term = (term or "month").lower()
    return int(PLAN_PRICE_TABLE.get(tier, PLAN_PRICE_TABLE["pro"]).get(term, PLAN_PRICE_TABLE["pro"]["month"]))

def _plan_payload_and_amount(tier: str, months: int) -> tuple[str, int, str]:
    term = {1: "month", 3: "quarter", 12: "year"}.get(months, "month")
    amount = _plan_rub(tier, term)
    title = f"ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° {tier.upper()} ({term})"
    payload = f"sub:{tier}:{months}"
    return payload, amount, title

async def _send_invoice_rub(title: str, desc: str, amount_rub: int, payload: str, update: Update) -> bool:
    try:
        # ÃÃÂµÃÃÃÂ¼ ÃÃÂ¾ÃÂºÃÂµÃÂ½ ÃÂ¸ ÃÂ²ÃÂ°ÃÂ»ÃÃÃ ÃÂ¸ÃÂ· ÃÂ´ÃÂ²ÃÃ ÃÂ¸ÃÃÃÂ¾ÃÃÂ½ÃÂ¸ÃÂºÃÂ¾ÃÂ² (ÃÃÃÂ°ÃÃÃÂ¹ PROVIDER_TOKEN ÃÃÃ ÃÂ½ÃÂ¾ÃÂ²ÃÃÂ¹ YOOKASSA_PROVIDER_TOKEN)
        token = (PROVIDER_TOKEN or YOOKASSA_PROVIDER_TOKEN)
        curr  = (CURRENCY if (CURRENCY and CURRENCY != "RUB") else YOOKASSA_CURRENCY) or "RUB"

        if not token:
            await update.effective_message.reply_text("Ã¢ Ã¯Â¸ ÃÂ®Kassa ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÃÃÃÂ¾ÃÂµÃÂ½ÃÂ° (ÃÂ½ÃÂµÃ ÃÃÂ¾ÃÂºÃÂµÃÂ½ÃÂ°).")
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
            await update.effective_message.reply_text("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ²ÃÃÃÃÂ°ÃÂ²ÃÂ¸ÃÃ ÃÃÃÃ.")
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
            await update.effective_message.reply_text(f"Ã¢ ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° {tier.upper()} ÃÂ°ÃÂºÃÃÂ¸ÃÂ²ÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ° ÃÂ´ÃÂ¾ {until.strftime('%Y-%m-%d')}.")
            return

        # ÃÃÃÃÂ¾ÃÂµ ÃÂ¸ÃÂ½ÃÂ¾ÃÂµ payload Ã¢ ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂµÃÂ´ÃÂ¸ÃÂ½ÃÂ¾ÃÂ³ÃÂ¾ ÃÂºÃÂ¾ÃÃÂµÃÂ»ÃÃÂºÃÂ°
        usd = rub / max(1e-9, USD_RUB)
        _wallet_total_add(uid, usd)
        await update.effective_message.reply_text(f"Ã°Â³ ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸ÃÂµ: {rub:.0f} Ã¢Â½ Ã¢ ${usd:.2f} ÃÂ·ÃÂ°ÃÃÂ¸ÃÃÂ»ÃÂµÃÂ½ÃÂ¾ ÃÂ½ÃÂ° ÃÂµÃÂ´ÃÂ¸ÃÂ½ÃÃÂ¹ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã.")
    except Exception as e:
        log.exception("successful_payment handler error: %s", e)


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ CryptoBot Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
CRYPTO_PAY_API_TOKEN = os.environ.get("CRYPTO_PAY_API_TOKEN", "").strip()
CRYPTO_BASE = "https://pay.crypt.bot/api"
TON_USD_RATE = float(os.environ.get("TON_USD_RATE", "5.0") or "5.0")  # ÃÂ·ÃÂ°ÃÂ¿ÃÂ°ÃÃÂ½ÃÂ¾ÃÂ¹ ÃÂºÃÃÃ

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
        for _ in range(120):  # ~12 ÃÂ¼ÃÂ¸ÃÂ½ÃÃ ÃÂ¿ÃÃÂ¸ 6Ã ÃÂ·ÃÂ°ÃÂ´ÃÂµÃÃÂ¶ÃÂºÃÂµ
            inv = await _crypto_get_invoice(invoice_id)
            st = (inv or {}).get("status", "").lower() if inv else ""
            if st == "paid":
                _wallet_total_add(user_id, float(usd_amount))
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                        text=f"Ã¢ CryptoBot: ÃÂ¿ÃÂ»ÃÂ°ÃÃÃÂ¶ ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂ²ÃÂµÃÃÂ¶ÃÂ´ÃÃÂ½. ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ ÃÂ½ÃÂ° ${float(usd_amount):.2f}.")
                return
            if st in ("expired", "cancelled", "canceled", "failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                        text=f"Ã¢ CryptoBot: ÃÂ¿ÃÂ»ÃÂ°ÃÃÃÂ¶ ÃÂ½ÃÂµ ÃÂ·ÃÂ°ÃÂ²ÃÂµÃÃÃÃÂ½ (ÃÃÃÂ°ÃÃÃ: {st}).")
                return
            await asyncio.sleep(6.0)
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                text="Ã¢ CryptoBot: ÃÂ²ÃÃÂµÃÂ¼Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ´ÃÂ°ÃÂ½ÃÂ¸Ã ÃÂ²ÃÃÃÂ»ÃÂ¾. ÃÃÂ°ÃÂ¶ÃÂ¼ÃÂ¸ÃÃÂµ ÃÂ«ÃÃÃÂ¾ÃÂ²ÃÂµÃÃÂ¸ÃÃ ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃÃÂ» ÃÂ¿ÃÂ¾ÃÂ·ÃÂ¶ÃÂµ.")
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
        for _ in range(120):  # ~12 ÃÂ¼ÃÂ¸ÃÂ½ÃÃ ÃÂ¿ÃÃÂ¸ ÃÂ·ÃÂ°ÃÂ´ÃÂµÃÃÂ¶ÃÂºÃÂµ 6Ã
            inv = await _crypto_get_invoice(invoice_id)
            st = (inv or {}).get("status", "").lower() if inv else ""
            if st == "paid":
                until = activate_subscription_with_tier(user_id, tier, months)
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=f"Ã¢ CryptoBot: ÃÂ¿ÃÂ»ÃÂ°ÃÃÃÂ¶ ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂ²ÃÂµÃÃÂ¶ÃÂ´ÃÃÂ½.\n"
                             f"ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° {tier.upper()} ÃÂ°ÃÂºÃÃÂ¸ÃÂ²ÃÂ½ÃÂ° ÃÂ´ÃÂ¾ {until.strftime('%Y-%m-%d')}."
                    )
                return
            if st in ("expired", "cancelled", "canceled", "failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=f"Ã¢ CryptoBot: ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃÂ° ÃÂ½ÃÂµ ÃÂ·ÃÂ°ÃÂ²ÃÂµÃÃÃÂµÃÂ½ÃÂ° (ÃÃÃÂ°ÃÃÃ: {st})."
                    )
                return
            await asyncio.sleep(6.0)

        # ÃÂ¢ÃÂ°ÃÂ¹ÃÂ¼ÃÂ°ÃÃ
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="Ã¢ CryptoBot: ÃÂ²ÃÃÂµÃÂ¼Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ´ÃÂ°ÃÂ½ÃÂ¸Ã ÃÂ²ÃÃÃÂ»ÃÂ¾. ÃÃÂ°ÃÂ¶ÃÂ¼ÃÂ¸ÃÃÂµ ÃÂ«ÃÃÃÂ¾ÃÂ²ÃÂµÃÃÂ¸ÃÃ ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃÃÂ» ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃÂ¸ÃÃÂµ ÃÂ·ÃÂ°ÃÂ½ÃÂ¾ÃÂ²ÃÂ¾."
            )
    except Exception as e:
        log.exception("crypto poll (subscription) error: %s", e)


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÃÂµÃÂ´ÃÂ»ÃÂ¾ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸Ã Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def _send_topup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("500 Ã¢Â½",  callback_data="topup:rub:500"),
         InlineKeyboardButton("1000 Ã¢Â½", callback_data="topup:rub:1000"),
         InlineKeyboardButton("2000 Ã¢Â½", callback_data="topup:rub:2000")],
        [InlineKeyboardButton("Crypto $5",  callback_data="topup:crypto:5"),
         InlineKeyboardButton("Crypto $10", callback_data="topup:crypto:10"),
         InlineKeyboardButton("Crypto $20", callback_data="topup:crypto:20")],
    ])
    await update.effective_message.reply_text("ÃÃÃÃÂµÃÃÂ¸ÃÃÂµ ÃÃÃÂ¼ÃÂ¼Ã ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸Ã:", reply_markup=kb)


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¾ÃÂ¿ÃÃÃÂºÃÂ° ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃÂ¸ÃÃ Ã¢ ÃÂ²ÃÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂ¸ÃÃ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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
            "ÃÃÂ»Ã ÃÂ²ÃÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸Ã ÃÂ½ÃÃÂ¶ÃÂµÃÂ½ ÃÃÂ°ÃÃÂ¸Ã ÃÂ¸ÃÂ»ÃÂ¸ ÃÂµÃÂ´ÃÂ¸ÃÂ½ÃÃÂ¹ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Ã¢Â­ ÃÂ¢ÃÂ°ÃÃÂ¸ÃÃ", web_app=WebAppInfo(url=TARIFF_URL))],
                 [InlineKeyboardButton("Ã¢ ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂ¸ÃÃ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã", callback_data="topup")]]
            )
        )
        return
    try:
        need_usd = float(offer.split(":", 1)[-1])
    except Exception:
        need_usd = est_cost_usd
    amount_rub = _calc_oneoff_price_rub(engine, need_usd)
    await update.effective_message.reply_text(
        f"ÃÃÂµÃÂ´ÃÂ¾ÃÃÃÂ°ÃÃÂ¾ÃÃÂ½ÃÂ¾ ÃÂ»ÃÂ¸ÃÂ¼ÃÂ¸ÃÃÂ°. Ã ÃÂ°ÃÂ·ÃÂ¾ÃÂ²ÃÂ°Ã ÃÂ¿ÃÂ¾ÃÂºÃÃÂ¿ÃÂºÃÂ° Ã¢ {amount_rub} Ã¢Â½ ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂ¸ÃÃÂµ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã:",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Ã¢Â­ ÃÂ¢ÃÂ°ÃÃÂ¸ÃÃ", web_app=WebAppInfo(url=TARIFF_URL))],
                [InlineKeyboardButton("Ã¢ ÃÃÂ¾ÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂ¸ÃÃ ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã", callback_data="topup")],
            ]
        ),
    )


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ /plans Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["Ã¢Â­ ÃÂ¢ÃÂ°ÃÃÂ¸ÃÃ:"]
    for tier, terms in PLAN_PRICE_TABLE.items():
        lines.append(f"Ã¢ {tier.upper()}: "
                     f"{terms['month']}Ã¢Â½/ÃÂ¼ÃÂµÃ Ã¢Â¢ {terms['quarter']}Ã¢Â½/ÃÂºÃÂ²ÃÂ°ÃÃÃÂ°ÃÂ» Ã¢Â¢ {terms['year']}Ã¢Â½/ÃÂ³ÃÂ¾ÃÂ´")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("ÃÃÃÂ¿ÃÂ¸ÃÃ START (1 ÃÂ¼ÃÂµÃ)",    callback_data="buy:start:1"),
         InlineKeyboardButton("ÃÃÃÂ¿ÃÂ¸ÃÃ PRO (1 ÃÂ¼ÃÂµÃ)",      callback_data="buy:pro:1")],
        [InlineKeyboardButton("ÃÃÃÂ¿ÃÂ¸ÃÃ ULTIMATE (1 ÃÂ¼ÃÂµÃ)", callback_data="buy:ultimate:1")],
        [InlineKeyboardButton("ÃÃÃÂºÃÃÃÃ ÃÂ¼ÃÂ¸ÃÂ½ÃÂ¸-ÃÂ²ÃÂ¸ÃÃÃÂ¸ÃÂ½Ã",    web_app=WebAppInfo(url=TARIFF_URL))]
    ])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=kb)


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÃÃÃÃÂºÃÂ° ÃÂ´ÃÂ»Ã ÃÂ¿ÃÂµÃÃÂµÃÂ´ÃÂ°ÃÃÂ¸ ÃÂ¿ÃÃÂ¾ÃÂ¸ÃÂ·ÃÂ²ÃÂ¾ÃÂ»ÃÃÂ½ÃÂ¾ÃÂ³ÃÂ¾ ÃÃÂµÃÂºÃÃÃÂ° (ÃÂ½ÃÂ°ÃÂ¿Ã. ÃÂ¸ÃÂ· STT) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def on_text_with_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
):
    """
    ÃÃÃÃÃÃÂºÃÂ° ÃÂ´ÃÂ»Ã ÃÂ¿ÃÂµÃÃÂµÃÂ´ÃÂ°ÃÃÂ¸ ÃÃÂµÃÂºÃÃÃÂ° (ÃÂ½ÃÂ°ÃÂ¿ÃÃÂ¸ÃÂ¼ÃÂµÃ, ÃÂ¿ÃÂ¾ÃÃÂ»ÃÂµ STT) ÃÂ² on_text,
    ÃÃÂµÃÂ· ÃÂ¿ÃÂ¾ÃÂ¿ÃÃÃÂ¾ÃÂº ÃÂ¸ÃÂ·ÃÂ¼ÃÂµÃÂ½ÃÂ¸ÃÃ update.message (read-only!).
    """
    text = (text or "").strip()
    if not text:
        await update.effective_message.reply_text("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂ°ÃÃÂ¿ÃÂ¾ÃÂ·ÃÂ½ÃÂ°ÃÃ ÃÃÂµÃÂºÃÃ.")
        return

    await on_text(update, context, manual_text=text)


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÂ¢ÃÂµÃÂºÃÃÃÂ¾ÃÂ²ÃÃÂ¹ ÃÂ²ÃÃÂ¾ÃÂ´ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def on_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    manual_text: str | None = None,
):
    # ÃÃÃÂ»ÃÂ¸ ÃÃÂµÃÂºÃÃ ÃÂ¿ÃÂµÃÃÂµÃÂ´ÃÂ°ÃÂ½ ÃÂ¸ÃÂ·ÃÂ²ÃÂ½ÃÂµ Ã¢ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÂ¼ ÃÂµÃÂ³ÃÂ¾
    # ÃÂ¸ÃÂ½ÃÂ°ÃÃÂµ Ã¢ ÃÂ¾ÃÃÃÃÂ½ÃÃÂ¹ ÃÃÂµÃÂºÃÃ ÃÃÂ¾ÃÂ¾ÃÃÃÂµÃÂ½ÃÂ¸Ã
    if manual_text is not None:
        text = manual_text.strip()
    else:
        text = (update.message.text or "").strip()

    # ÃÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃ ÃÂ¾ ÃÂ²ÃÂ¾ÃÂ·ÃÂ¼ÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ÃÃÃÃ
    cap = capability_answer(text)
    if cap:
        await update.effective_message.reply_text(cap)
        return

    # ÃÃÂ°ÃÂ¼ÃÃÂº ÃÂ½ÃÂ° ÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ°ÃÃÂ¸Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ÃÃÂ¾ÃÂ»ÃÂ¸ÃÂºÃÂ°
    mtype, rest = detect_media_intent(text)
    # ÃÃÃÂ¸ÃÂ½ÃÃÂ´ÃÂ¸ÃÃÂµÃÂ»ÃÃÂ½ÃÃÂ¹ ÃÂ²ÃÃÃÂ¾Ã ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ° (ÃÃÂµÃÃÂµÃÂ· ÃÂ¼ÃÂµÃÂ½Ã ÃÂ«ÃÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸ÃÂ»)
    user_id = update.effective_user.id
    forced_engine = "gpt"
    with contextlib.suppress(Exception):
        forced_engine = engine_get(user_id)

    # ÃÃÃÂ»ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃÂµÃÂ»Ã ÃÂ²ÃÃÃÃÂ°ÃÂ» ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾-ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº, ÃÂ° ÃÃÂ²ÃÂ½ÃÂ¾ÃÂ³ÃÂ¾ ÃÂ¿ÃÃÂµÃÃÂ¸ÃÂºÃÃÂ° ÃÂ½ÃÂµÃ Ã¢ ÃÃÃÂ°ÃÂºÃÃÃÂµÃÂ¼ ÃÃÂµÃÂºÃÃ ÃÂºÃÂ°ÃÂº ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾-ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã
    if (mtype is None) and forced_engine in ("kling", "luma", "runway", "sora"):
        prompt = text.strip()
        duration, aspect = parse_video_opts(text)

        # Runway textÃ¢video ÃÂ¼ÃÂ¾ÃÂ¶ÃÂµÃ ÃÃÃÃ ÃÂ²ÃÃÂºÃÂ»ÃÃÃÂµÃÂ½ (ÃÂ¾ÃÃÃÂ°ÃÂ²ÃÂ»ÃÃÂµÃÂ¼ ÃÂ·ÃÂ°ÃÃÂ¸ÃÃ ÃÂºÃÂ°ÃÂº ÃÃÂ°ÃÂ½ÃÃÃÂµ)
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

        # ÃÃÂ»ÃÂ°ÃÃÃÂ¶/ÃÂ»ÃÂ¸ÃÂ¼ÃÂ¸ÃÃ Ã¢ ÃÃÃÂ¸ÃÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÂºÃÂ°ÃÂº ÃÂ«oneoffÃÂ» ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾
        est = float(KLING_UNIT_COST_USD or 0.40) * duration
        if forced_engine == "luma":
            est = float(LUMA_UNIT_COST_USD or 0.40) * duration
        elif forced_engine == "runway":
            est = float(RUNWAY_UNIT_COST_USD or 1.00) * duration
        elif forced_engine == "sora":
            est = float(SORA_UNIT_COST_USD or 0.40) * duration

        await _try_pay_then_do(update, context, user_id, forced_engine, est, _go_video)
        return

    # ÃÃÃÂ»ÃÂ¸ ÃÂ²ÃÃÃÃÂ°ÃÂ½ Images, ÃÂ° ÃÂ¿ÃÃÂµÃÃÂ¸ÃÂºÃÃÂ° ÃÂ½ÃÂµÃ Ã¢ ÃÃÃÂ°ÃÂºÃÃÃÂµÃÂ¼ ÃÃÂµÃÂºÃÃ ÃÂºÃÂ°ÃÂº ÃÂ¿ÃÃÂ¾ÃÂ¼ÃÂ¿Ã ÃÂ´ÃÂ»Ã ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ¸
    if (mtype is None) and forced_engine == "images":
        prompt = text.strip()
        if not prompt:
            await update.effective_message.reply_text("ÃÂ¤ÃÂ¾ÃÃÂ¼ÃÂ°Ã: /img <ÃÂ¾ÃÂ¿ÃÂ¸ÃÃÂ°ÃÂ½ÃÂ¸ÃÂµ ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã>")
            return

        async def _go_img():
            await _do_img_generate(update, context, prompt)

        await _try_pay_then_do(update, context, user_id, "img", IMG_COST_USD, _go_img)
        return

    # ÃÃÃÂ»ÃÂ¸ ÃÂ²ÃÃÃÃÂ°ÃÂ½ Gemini Ã¢ ÃÂ¾ÃÃÃÂ°ÃÃÂ°ÃÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÂ¾ÃÃÃÃÂ½ÃÃÂ¹ ÃÃÂµÃÂºÃÃ ÃÃÂµÃÃÂµÃÂ· Gemini (Comet) ÃÂ²ÃÂ¼ÃÂµÃÃÃÂ¾ OpenAI
    if (mtype is None) and forced_engine == "gemini":
        reply = await ask_gemini_text(text)
        await update.effective_message.reply_text(reply)
        await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])
        return

    # Suno / Midjourney ÃÂ¿ÃÂ¾ÃÂºÃÂ° ÃÂºÃÂ°ÃÂº ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂºÃÂ°ÃÂ·ÃÂºÃÂ° (ÃÃÂµÃÂ· ÃÂ¿ÃÃÃÂ¼ÃÂ¾ÃÂ³ÃÂ¾ API ÃÂ² ÃÃÃÂ¾ÃÂ¼ ÃÃÂ°ÃÂ¹ÃÂ»ÃÂµ)
    if (mtype is None) and forced_engine in ("suno", "midjourney"):
        if forced_engine == "suno":
            await update.effective_message.reply_text(
                "Ã°Âµ Suno ÃÂ²ÃÃÃÃÂ°ÃÂ½. ÃÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ÃÃÂµ: ÃÂ«ÃÂ¿ÃÂµÃÃÂ½Ã: ÃÂ¶ÃÂ°ÃÂ½Ã, ÃÂ½ÃÂ°ÃÃÃÃÂ¾ÃÂµÃÂ½ÃÂ¸ÃÂµ, ÃÃÂµÃÂ¼ÃÂ°, ÃÂ´ÃÂ»ÃÂ¸ÃÃÂµÃÂ»ÃÃÂ½ÃÂ¾ÃÃÃÃÂ» Ã¢ ÃÂ¸ Ã ÃÂ¿ÃÂ¾ÃÂ´ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ»Ã ÃÃÂµÃÂºÃÃ/ÃÃÃÃÃÂºÃÃÃÃ.\n"
                "ÃÃÃÂ»ÃÂ¸ Ã ÃÂ²ÃÂ°Ã ÃÂµÃÃÃ API/ÃÂ¿ÃÃÂ¾ÃÂ²ÃÂ°ÃÂ¹ÃÂ´ÃÂµÃ Ã¢ ÃÂ´ÃÂ¾ÃÃÂ°ÃÂ²ÃÃÃÂµ ÃÂºÃÂ»ÃÃÃÂ¸, ÃÂ¸ Ã ÃÂ¿ÃÂ¾ÃÂ´ÃÂºÃÂ»ÃÃÃ ÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ°ÃÃÂ¸Ã."
            )
        else:
            await update.effective_message.reply_text(
                "Ã°Â¨ Midjourney ÃÂ²ÃÃÃÃÂ°ÃÂ½. ÃÃÂ¿ÃÂ¸ÃÃÂ¸ÃÃÂµ ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂµ Ã¢ Ã ÃÂ¿ÃÂ¾ÃÂ´ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ»Ã ÃÂ¿ÃÃÂ¾ÃÂ¼ÃÂ¿Ã. "
                "ÃÃÂ°ÃÂ»ÃÃÃÂµ ÃÂ²Ã ÃÂ¼ÃÂ¾ÃÂ¶ÃÂµÃÃÂµ ÃÂ¾ÃÃÂ¿ÃÃÂ°ÃÂ²ÃÂ¸ÃÃ ÃÂµÃÂ³ÃÂ¾ ÃÂ² Midjourney/Discord."
            )
        return
    if mtype == "video":
        # ÃÃÃ ÃÃÃÂ¢ÃÃ ÃÃÃÃÃÃ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃÂ¼ prompt ÃÂ´ÃÂ»Ã ÃÃÂµÃÂºÃÃÃÂ° ÃÂ¸ ÃÂ´ÃÂ»Ã ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾ÃÃÂ°
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
            f"Ã° Kling (~${est_kling:.2f})",
            callback_data=f"choose:kling:{aid}",
        )])
        rows.append([InlineKeyboardButton(
            f"Ã°Â¬ Luma (~${est_luma:.2f})",
            callback_data=f"choose:luma:{aid}",
        )])

        # Sora: show Pro label for pro/ultimate tiers
        if SORA_ENABLED:
            if tier in ("pro", "ultimate"):
                rows.append([InlineKeyboardButton("Ã¢Â¨ Sora 2 Pro", callback_data=f"choose:sora:{aid}")])
            else:
                rows.append([InlineKeyboardButton("Ã¢Â¨ Sora 2", callback_data=f"choose:sora:{aid}")])

        kb = InlineKeyboardMarkup(rows)

        await update.effective_message.reply_text(
            f"ÃÂ§ÃÃÂ¾ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃ?\n"
            f"ÃÃÂ»ÃÂ¸ÃÃÂµÃÂ»ÃÃÂ½ÃÂ¾ÃÃÃ: {duration} c Ã¢Â¢ ÃÃÃÂ¿ÃÂµÃÂºÃ: {aspect}\n"
            f"ÃÃÂ°ÃÂ¿ÃÃÂ¾Ã: ÃÂ«{prompt}ÃÂ»",
            reply_markup=kb,
        )
        return

    # ÃÃÂ°ÃÂ¼ÃÃÂº ÃÂ½ÃÂ° ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃ
    if mtype == "image":
        prompt = rest or re.sub(
            r"^(img|image|picture)\s*[:\-]\s*",
            "",
            text,
            flags=re.I,
        ).strip()

        if not prompt:
            await update.effective_message.reply_text(
                "ÃÂ¤ÃÂ¾ÃÃÂ¼ÃÂ°Ã: /img <ÃÂ¾ÃÂ¿ÃÂ¸ÃÃÂ°ÃÂ½ÃÂ¸ÃÂµ ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã>"
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

    # ÃÃÃÃÃÂ½ÃÃÂ¹ ÃÃÂµÃÂºÃÃ Ã¢ GPT
    ok, _, _ = check_text_and_inc(
        update.effective_user.id,
        update.effective_user.username or "",
    )

    if not ok:
        await update.effective_message.reply_text(
            "ÃÃÂ¸ÃÂ¼ÃÂ¸Ã ÃÃÂµÃÂºÃÃÃÂ¾ÃÂ²ÃÃ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾ÃÃÂ¾ÃÂ² ÃÂ½ÃÂ° ÃÃÂµÃÂ³ÃÂ¾ÃÂ´ÃÂ½Ã ÃÂ¸ÃÃÃÂµÃÃÂ¿ÃÂ°ÃÂ½. "
            "ÃÃÃÂ¾ÃÃÂ¼ÃÂ¸ÃÃÂµ Ã¢Â­ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃ ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃÃÂ¹ÃÃÂµ ÃÂ·ÃÂ°ÃÂ²ÃÃÃÂ°."
        )
        return

    user_id = update.effective_user.id

    # Ã ÃÂµÃÂ¶ÃÂ¸ÃÂ¼Ã
    try:
        mode = _mode_get(user_id)
        track = _mode_track_get(user_id)
    except NameError:
        mode, track = "none", ""

    if mode and mode != "none":
        text_for_llm = f"[Ã ÃÂµÃÂ¶ÃÂ¸ÃÂ¼: {mode}; ÃÃÂ¾ÃÂ´ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼: {track or '-'}]\n{text}"
    else:
        text_for_llm = text

    if mode == "ÃÂ£ÃÃÃÃÂ°" and track:
        await study_process_text(update, context, text)
        return

    reply = await ask_openai_text(text_for_llm)
    await update.effective_message.reply_text(reply)
    await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])
    
# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÂ¤ÃÂ¾ÃÃÂ¾ / ÃÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃ / ÃÃÂ¾ÃÂ»ÃÂ¾Ã Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.photo:
            return

        ph = update.message.photo[-1]
        f = await ph.get_file()
        data = await f.download_as_bytearray()
        img = bytes(data)

        # --- ÃÂ¡ÃÂ¢ÃÃ ÃÂ«Ã ÃÃÂ­ÃÂ¨ (ÃÂºÃÂ°ÃÂº ÃÃÂ°ÃÂ½ÃÃÃÂµ) ---
        _cache_photo(update.effective_user.id, img)

        # --- ÃÃÃÃÂ«Ã ÃÃÂ­ÃÂ¨ ÃÃÃÂ¯ ÃÃÃÃÃÃÃÃÃÂ¯ / LUMA / KLING ---
        # ÃÂ¡ÃÂ¾ÃÃÃÂ°ÃÂ½ÃÃÂµÃÂ¼ ÃÂ¸ bytes, ÃÂ¸ ÃÂ¿ÃÃÃÂ»ÃÂ¸ÃÃÂ½ÃÃÂ¹ URL Telegram (ÃÂ¿ÃÂ¾ÃÂ´ÃÃÂ¾ÃÂ´ÃÂ¸Ã ÃÂ´ÃÂ»Ã Luma/Comet)
        with contextlib.suppress(Exception):
            _LAST_ANIM_PHOTO[update.effective_user.id] = {
                "bytes": img,
                "url": (f.file_path or "").strip(),   # ÃÂ¿ÃÃÃÂ»ÃÂ¸ÃÃÂ½ÃÃÂ¹ HTTPS-URL Telegram API
            }

        caption = (update.message.caption or "").strip()
        if caption:
            tl = caption.lower()

            # Ã¢Ã¢ ÃÃÃÃÃÃÃÃÃ ÃÂ¤ÃÃÂ¢Ã (ÃÃÂµÃÃÂµÃÂ· ÃÂ²ÃÃÃÂ¾Ã ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ°) Ã¢Ã¢
            if any(k in tl for k in ("ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸", "ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ", "ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ¸ÃÃ", "ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ", "ÃÃÂ´ÃÂµÃÂ»ÃÂ°ÃÂ¹ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾", "revive", "animate")):
                dur, asp = parse_video_opts(caption)

                # ÃÂ¾ÃÃÂ¸ÃÃÂ°ÃÂµÃÂ¼ prompt ÃÂ¾Ã ÃÃÃÂ¸ÃÂ³ÃÂ³ÃÂµÃ-ÃÃÂ»ÃÂ¾ÃÂ²
                prompt = re.sub(
                    r"\b(ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸|ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ|ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ¸ÃÃÃÂ¹|ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ|ÃÃÂ´ÃÂµÃÂ»ÃÂ°ÃÂ¹ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾|revive|animate)\b",
                    "",
                    caption,
                    flags=re.I
                ).strip(" ,.")

                # ÃÃÂ¾ÃÃÃÂ°ÃÂ½ÃÃÂµÃÂ¼ ÃÂ²ÃÃÂ¾ÃÂ´ÃÂ½ÃÃÂµ ÃÂ¿ÃÂ°ÃÃÂ°ÃÂ¼ÃÂµÃÃÃ ÃÂ² user_data (ÃÃÂµÃÂ· ÃÂ³ÃÂ»ÃÂ¾ÃÃÂ°ÃÂ»ÃÃÂ½ÃÃ pending)
                context.user_data["revive_photo"] = {
                    "duration": int(dur),
                    "aspect": asp,
                    "prompt": prompt,
                }

                # ÃÂ¿ÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÂ²ÃÃÃÂ¾Ã ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ°
                await update.effective_message.reply_text(
                    "ÃÃÃÃÂµÃÃÂ¸ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº ÃÂ´ÃÂ»Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸Ã ÃÃÂ¾ÃÃÂ¾:",
                    reply_markup=revive_engine_kb()
                )
                return

            # Ã¢Ã¢ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¸ÃÃ ÃÃÂ¾ÃÂ½ Ã¢Ã¢
            if any(k in tl for k in ("ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¸ ÃÃÂ¾ÃÂ½", "removebg", "ÃÃÃÃÂ°ÃÃ ÃÃÂ¾ÃÂ½")):
                await _pedit_removebg(update, context, img)
                return

            # Ã¢Ã¢ ÃÂ·ÃÂ°ÃÂ¼ÃÂµÃÂ½ÃÂ¸ÃÃ ÃÃÂ¾ÃÂ½ Ã¢Ã¢
            if any(k in tl for k in ("ÃÂ·ÃÂ°ÃÂ¼ÃÂµÃÂ½ÃÂ¸ ÃÃÂ¾ÃÂ½", "replacebg", "ÃÃÂ°ÃÂ·ÃÂ¼ÃÃÃÃÂ¹", "blur")):
                await _pedit_replacebg(update, context, img)
                return

            # Ã¢Ã¢ outpaint Ã¢Ã¢
            if "outpaint" in tl or "ÃÃÂ°ÃÃÃÂ¸Ã" in tl:
                await _pedit_outpaint(update, context, img)
                return

            # Ã¢Ã¢ ÃÃÂ°ÃÃÂºÃÂ°ÃÂ´ÃÃÂ¾ÃÂ²ÃÂºÃÂ° Ã¢Ã¢
            if "ÃÃÂ°ÃÃÂºÃÂ°ÃÂ´ÃÃÂ¾ÃÂ²" in tl or "storyboard" in tl:
                await _pedit_storyboard(update, context, img)
                return

            # Ã¢Ã¢ ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ° ÃÂ¿ÃÂ¾ ÃÂ¾ÃÂ¿ÃÂ¸ÃÃÂ°ÃÂ½ÃÂ¸Ã (Luma / fallback OpenAI) Ã¢Ã¢
            if (
                any(k in tl for k in ("ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½", "ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½", "image", "img"))
                and any(k in tl for k in ("ÃÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ¸ÃÃ", "ÃÃÂ¾ÃÂ·ÃÂ´ÃÂ°", "ÃÃÂ´ÃÂµÃÂ»ÃÂ°ÃÂ¹"))
            ):
                await _start_luma_img(update, context, caption)
                return

        # ÃÂµÃÃÂ»ÃÂ¸ ÃÃÂ²ÃÂ½ÃÂ¾ÃÂ¹ ÃÂºÃÂ¾ÃÂ¼ÃÂ°ÃÂ½ÃÂ´Ã ÃÂ½ÃÂµÃ Ã¢ ÃÃÃÃÃÃÃÂµ ÃÂºÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ¸
        await update.effective_message.reply_text(
            "ÃÂ¤ÃÂ¾ÃÃÂ¾ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂµÃÂ½ÃÂ¾. ÃÂ§ÃÃÂ¾ ÃÃÂ´ÃÂµÃÂ»ÃÂ°ÃÃ?",
            reply_markup=photo_quick_actions_kb()
        )

    except Exception as e:
        log.exception("on_photo error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("ÃÃÂµ ÃÃÂ¼ÃÂ¾ÃÂ³ ÃÂ¾ÃÃÃÂ°ÃÃÂ¾ÃÃÂ°ÃÃ ÃÃÂ¾ÃÃÂ¾.")
            
async def on_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document:
            return

        doc = update.message.document
        mt = (doc.mime_type or "").lower()
        tg_file = await doc.get_file()
        data = await tg_file.download_as_bytearray()
        raw = bytes(data)

        # ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½Ã ÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÂ°ÃÂ»ÃÃ ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂµÃÂ¼
        if mt.startswith("image/"):
            _cache_photo(update.effective_user.id, raw)

            # --- ÃÃÃÃÂ«Ã ÃÃÂ­ÃÂ¨ ÃÃÃÂ¯ ÃÃÃÃÃÃÃÃÃÂ¯ ---
            try:
                _LAST_ANIM_PHOTO[update.effective_user.id] = {
                    "bytes": raw,
                    "url": tg_file.file_path,    # Telegram public URL
                }
            except Exception:
                pass

            await update.effective_message.reply_text(
                "ÃÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂµÃÂ½ÃÂ¾ ÃÂºÃÂ°ÃÂº ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½Ã. ÃÂ§ÃÃÂ¾ ÃÃÂ´ÃÂµÃÂ»ÃÂ°ÃÃ?",
                reply_markup=photo_quick_actions_kb()
            )
            return

        # ÃÂ¾ÃÃÃÂ°ÃÂ»ÃÃÂ½ÃÃÂµ ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃ Ã¢ ÃÂ¸ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂµÃÂºÃÃÃÂ°
        text, kind = extract_text_from_document(raw, doc.file_name or "file")
        if not (text or "").strip():
            await update.effective_message.reply_text(f"ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ¸ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃ ÃÃÂµÃÂºÃÃ ÃÂ¸ÃÂ· {kind}.")
            return

        goal = (update.message.caption or "").strip() or NoneÃÃ
        await update.effective_message.reply_text(f"Ã° ÃÃÂ·ÃÂ²ÃÂ»ÃÂµÃÂºÃÂ°Ã ÃÃÂµÃÂºÃÃ ({kind}), ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ»Ã ÃÂºÃÂ¾ÃÂ½ÃÃÂ¿ÃÂµÃÂºÃÃ¢Â¦")

        summary = await summarize_long_text(text, query=goal)
        summary = summary or "ÃÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾."
        await update.effective_message.reply_text(summary)

        await maybe_tts_reply(update, context, summary[:TTS_MAX_CHARS])

    except Exception as e:
        log.exception("on_doc error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("ÃÃÃÂ¸ÃÃÂºÃÂ° ÃÂ¿ÃÃÂ¸ ÃÂ¾ÃÃÃÂ°ÃÃÂ¾ÃÃÂºÃÂµ ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃÂ°.")
            
# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÂ¥ÃÂµÃÂ»ÃÂ¿ÃÂµÃÃ ÃÂ´ÃÂ»Ã ÃÂ°ÃÃÂ¿ÃÂµÃÂºÃÃÂ¾ÃÂ² Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

def _runway_aspect_to_ratio(aspect_str: str | None) -> str:
    """
    ÃÃÂµÃÃÂµÃÂ²ÃÂ¾ÃÂ´ÃÂ¸Ã "16:9"/"9:16"/"1:1" ÃÂ² ÃÂ´ÃÂ¾ÃÂ¿ÃÃÃÃÂ¸ÃÂ¼ÃÃÂµ ratio Runway:
    1280:720, 720:1280, 960:960, 1104:832, 832:1104, 1584:672, 1280:768, 768:1280.
    ÃÃÃÂ»ÃÂ¸ ÃÂ¿ÃÃÂ¸ÃÃÂ»ÃÂ¾ ÃÃÂ¶ÃÂµ "1280:720" ÃÂ¸ Ã.ÃÂ¿. Ã¢ ÃÂ²ÃÂ¾ÃÂ·ÃÂ²ÃÃÂ°ÃÃÂ°ÃÂµÃÂ¼ ÃÂºÃÂ°ÃÂº ÃÂµÃÃÃ.
    """
    default_ratio = RUNWAY_RATIO or "1280:720"
    mapping = {
        "16:9": "1280:720",
        "9:16": "720:1280",
        "1:1": "960:960",
        "4:3": "1104:832",
        "3:4": "832:1104",
        # ÃÃÂ¸ÃÃÂ¾ÃÂºÃÂ¸ÃÂµ ÃÃÂ¾ÃÃÂ¼ÃÂ°ÃÃ ÃÂ¼ÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ ÃÂ¿ÃÃÂ¸ÃÂ²ÃÃÂ·ÃÂ°ÃÃ ÃÂº ÃÃÂ°ÃÂ¼ÃÃÂ¼ ÃÃÂ»ÃÂ¸ÃÂ·ÃÂºÃÂ¸ÃÂ¼
        "21:9": "1584:672",
        "9:21": "768:1280",
    }
    if not aspect_str:
        return default_ratio
    a = aspect_str.replace(" ", "")
    if a in mapping:
        return mapping[a]
    # ÃÂµÃÃÂ»ÃÂ¸ ÃÃÂ¶ÃÂµ ÃÂ¿ÃÂ¾ÃÃÂ¾ÃÂ¶ÃÂµ ÃÂ½ÃÂ° "1280:720"
    if re.match(r"^\d+:\d+$", a):
        return a
    return default_ratio


def _normalize_luma_aspect(aspect: str | None) -> str:
    """
    Luma Dream Machine ÃÂ¿ÃÂ¾ÃÂ´ÃÂ´ÃÂµÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ°ÃÂµÃ ÃÂ¾ÃÂ³ÃÃÂ°ÃÂ½ÃÂ¸ÃÃÂµÃÂ½ÃÂ½ÃÃÂ¹ ÃÂ½ÃÂ°ÃÃÂ¾Ã ÃÂ°ÃÃÂ¿ÃÂµÃÂºÃÃÂ¾ÃÂ².
    ÃÃÃÂ¸ÃÂ²ÃÂ¾ÃÂ´ÃÂ¸ÃÂ¼ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÃÂµÃÂ»ÃÃÃÂºÃÂ¸ÃÂ¹ ÃÂ°ÃÃÂ¿ÃÂµÃÂºÃ ÃÂº ÃÂ´ÃÂ¾ÃÂ¿ÃÃÃÃÂ¸ÃÂ¼ÃÂ¾ÃÂ¼Ã ÃÂ·ÃÂ½ÃÂ°ÃÃÂµÃÂ½ÃÂ¸Ã.
    """
    allowed = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"}
    if not aspect:
        a = (LUMA_ASPECT or "16:9").replace(" ", "")
    else:
        a = aspect.replace(" ", "")

    if a in allowed:
        return a

    # ÃÃÃÂ³ÃÂºÃÂ°Ã ÃÂºÃÂ¾ÃÃÃÂµÃÂºÃÃÂ¸Ã ÃÂ«ÃÂ¿ÃÂ¾ÃÃÂ¾ÃÂ¶ÃÂ¸ÃÃÂ» ÃÃÂ¾ÃÃÂ¼ÃÂ°ÃÃÂ¾ÃÂ²
    mapping = {
        "4:5": "3:4",
        "5:4": "4:3",
    }
    if a in mapping:
        return mapping[a]

    return "16:9"


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ RUNWAY: IMAGE Ã¢ VIDEO (CometAPI) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

async def _run_runway_animate_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    image_url: str,
    prompt: str = "",
    duration_s: int = 5,
    aspect: str = "16:9",
):
    """
    Image -> Video ÃÃÂµÃÃÂµÃÂ· CometAPI (runwayml wrapper).
    ÃÃÂµÃÂ»ÃÂ°ÃÂµÃ create -> poll status -> download mp4 -> send_video
    + ÃÃÂ²ÃÂµÃÂ´ÃÂ¾ÃÂ¼ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ, ÃÂµÃÃÂ»ÃÂ¸ ÃÃÃÂ¸ÃÃÂ°ÃÂµÃ > 3 ÃÂ¼ÃÂ¸ÃÂ½ÃÃ.
    """
    chat_id = update.effective_chat.id
    msg = update.effective_message

    await context.bot.send_chat_action(chat_id, ChatAction.RECORD_VIDEO)

    # ÃÃÂµÃÃÃÂ¼ ÃÂºÃÂ»ÃÃ: ÃÂ¿ÃÃÂ¸ÃÂ¾ÃÃÂ¸ÃÃÂµÃ COMETAPI_KEY, ÃÂ¸ÃÂ½ÃÂ°ÃÃÂµ RUNWAY_API_KEY
    api_key = (COMETAPI_KEY or RUNWAY_API_KEY or "").strip()
    if not api_key:
        await msg.reply_text("Ã¢ Ã¯Â¸ Runway/Comet: ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÃÃÃÂ¾ÃÂµÃÂ½ ÃÂºÃÂ»ÃÃ (COMETAPI_KEY ÃÂ¸ÃÂ»ÃÂ¸ RUNWAY_API_KEY).")
        return

    # ÃÃÂ¾ÃÃÂ¼ÃÂ°ÃÂ»ÃÂ¸ÃÂ·ÃÃÂµÃÂ¼ duration
    try:
        duration_val = int(duration_s or RUNWAY_DURATION_S or 5)
    except Exception:
        duration_val = RUNWAY_DURATION_S or 5
    duration_val = max(3, min(20, duration_val))

    ratio = _runway_aspect_to_ratio(aspect)  # Ã ÃÃÂµÃÃ ÃÃÂ¶ÃÂµ ÃÂµÃÃÃ ÃÃÃÂ° ÃÃÃÂ½ÃÂºÃÃÂ¸Ã/ÃÂ¼ÃÂ°ÃÂ¿ÃÂ¿ÃÂ¸ÃÂ½ÃÂ³
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
                    "Ã¢ Ã¯Â¸ Runway/Comet imageÃ¢video ÃÂ¾ÃÃÂºÃÂ»ÃÂ¾ÃÂ½ÃÂ¸ÃÂ» ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃ.\n"
                    f"ÃÃÂ¾ÃÂ´: {r.status_code}\n"
                    f"ÃÃÃÂ²ÃÂµÃ:\n`{txt}`",
                    parse_mode="Markdown",
                )
                return

            try:
                js = r.json() or {}
            except Exception:
                js = {}

            # Comet: id ÃÂ¼ÃÂ¾ÃÂ¶ÃÂµÃ ÃÂ»ÃÂµÃÂ¶ÃÂ°ÃÃ ÃÂ³ÃÂ»ÃÃÃÂ¾ÃÂºÃÂ¾
            task_id = None
            for d in _dicts_bfs(js):
                v = d.get("id") or d.get("task_id") or d.get("taskId")
                if isinstance(v, str) and v.strip():
                    task_id = v.strip()
                    break

            if not task_id:
                await msg.reply_text(
                    f"Ã¢ Ã¯Â¸ Runway/Comet: ÃÂ½ÃÂµ ÃÂ²ÃÂµÃÃÂ½ÃÃÂ» id ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃÂ¸.\n`{str(js)[:1200]}`",
                    parse_mode="Markdown",
                )
                return

            await msg.reply_text("Ã¢Â³ Runway: ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ¸ÃÃÃ ÃÃÂ¾ÃÃÂ¾Ã¢Â¦")

            status_url = f"{RUNWAY_BASE_URL}{status_tpl.format(id=task_id)}"
            started = time.time()
            notified_long_wait = False

            while True:
                rs = await client.get(status_url, headers=headers, timeout=60.0)

                if rs.status_code >= 400:
                    txt = (rs.text or "")[:1200]
                    log.warning("Runway/Comet status error %s: %s", rs.status_code, txt)
                    await msg.reply_text(
                        "Ã¢ Ã¯Â¸ Runway: ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ° ÃÃÃÂ°ÃÃÃÃÂ°.\n"
                        f"ÃÃÂ¾ÃÂ´: {rs.status_code}\n"
                        f"ÃÃÃÂ²ÃÂµÃ:\n`{txt}`",
                        parse_mode="Markdown",
                    )
                    return

                try:
                    sjs = rs.json() or {}
                except Exception:
                    sjs = {}

                status = _pick_status(sjs)

                # ÃÂ£ÃÂ²ÃÂµÃÂ´ÃÂ¾ÃÂ¼ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ¿ÃÃÂ¸ ÃÂ´ÃÂ¾ÃÂ»ÃÂ³ÃÂ¾ÃÂ¼ ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ´ÃÂ°ÃÂ½ÃÂ¸ÃÂ¸ (1 ÃÃÂ°ÃÂ·)
                elapsed = time.time() - started
                if elapsed > 180 and not notified_long_wait:
                    notified_long_wait = True
                    await msg.reply_text(
                        "Ã¢Â³ Runway ÃÃÃÂ¸ÃÃÂ°ÃÂµÃ ÃÂ´ÃÂ¾ÃÂ»ÃÃÃÂµ ÃÂ¾ÃÃÃÃÂ½ÃÂ¾ÃÂ³ÃÂ¾.\n"
                        "ÃÂ¯ ÃÂ¿ÃÃÂ¸ÃÃÂ»Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÃÃÂ°ÃÂ·Ã, ÃÂºÃÂ°ÃÂº ÃÂ¾ÃÂ½ÃÂ¾ ÃÃÃÂ´ÃÂµÃ ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾."
                    )

                if status in ("succeeded", "success", "completed", "finished", "ready", "done"):
                    video_url = _pick_video_url(sjs)
                    if not video_url:
                        await msg.reply_text(
                            f"Ã¢ Ã¯Â¸ Runway: ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃÂ° ÃÂ·ÃÂ°ÃÂ²ÃÂµÃÃÃÂ¸ÃÂ»ÃÂ°ÃÃ, ÃÂ½ÃÂ¾ ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÂ¹ÃÂ´ÃÂµÃÂ½ URL ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾.\n`{str(sjs)[:1200]}`",
                            parse_mode="Markdown",
                        )
                        return

                    vr = await client.get(video_url, timeout=300.0)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(f"Ã¢ Ã¯Â¸ Runway: ÃÂ½ÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂºÃÂ°ÃÃÂ°ÃÃ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ({vr.status_code}).")
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
                    await msg.reply_text(f"Ã¢ Runway (imageÃ¢video) ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ°: `{err}`", parse_mode="Markdown")
                    return

                if time.time() - started > RUNWAY_MAX_WAIT_S:
                    await msg.reply_text(
                        "Ã¢ Runway ÃÃÃÂ¸ÃÃÂ°ÃÂµÃ ÃÃÂ»ÃÂ¸ÃÃÂºÃÂ¾ÃÂ¼ ÃÂ´ÃÂ¾ÃÂ»ÃÂ³ÃÂ¾.\n"
                        "ÃÃÃÂ»ÃÂ¸ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÃÃÂ´ÃÂµÃ ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾ ÃÂ¿ÃÂ¾ÃÂ·ÃÂ¶ÃÂµ Ã¢ Ã ÃÂ¿ÃÃÂ¸ÃÃÂ»Ã ÃÂµÃÂ³ÃÂ¾ ÃÂ°ÃÂ²ÃÃÂ¾ÃÂ¼ÃÂ°ÃÃÂ¸ÃÃÂµÃÃÂºÃÂ¸."
                    )
                    # ÃÃÃÃÃ: ÃÃÂµÃÂ¹ÃÃÂ°Ã ÃÂ¼Ã ÃÂ¿ÃÃÂ¾ÃÃÃÂ¾ ÃÂ²ÃÃÃÂ¾ÃÂ´ÃÂ¸ÃÂ¼.
                    # ÃÃÃÂ»ÃÂ¸ ÃÃÂ¾ÃÃÂµÃÃ ÃÃÂµÃÂ°ÃÂ»ÃÃÂ½ÃÂ¾ Ã¢ÃÂ°ÃÂ²ÃÃÂ¾ÃÂ¼ÃÂ°ÃÃÂ¸ÃÃÂµÃÃÂºÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ·ÃÂ¶ÃÂµÃ¢ Ã¢ ÃÂ´ÃÂ¾ÃÃÂ°ÃÂ²ÃÂ»Ã background-poller (ÃÃÂµÃÃÂµÃÂ· create_task)
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Runway image2video exception: %s", e)
        await msg.reply_text("Ã¢ Runway: ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ° ÃÂ²ÃÃÂ¿ÃÂ¾ÃÂ»ÃÂ½ÃÂµÃÂ½ÃÂ¸Ã imageÃ¢video.")

# ---------------- helpers -----------------def-_dicts_bfs(cts_bfs(root: object, max_depth6)int = """ÃÂ¡ÃÂ¾ÃÃÂ¸ÃÃÂ°ÃÂµÃÂ¼ ÃÃÂ»ÃÂ¾ÃÂ²ÃÂ°ÃÃÂ¸ ÃÂ² ÃÃÂ¸ÃÃÂ¸ÃÂ½Ã, ÃÃÃÂ¾ÃÃ ÃÂ½ÃÂ°ÃÂ¹ÃÃÂ¸ status/video_url ÃÂ² ÃÂ»ÃÃÃÂ¾ÃÂ¼ ÃÂ²ÃÂ»ÃÂ¾ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂ¸."""ÃÂµÃÂ½ÃÂ¸ÃÂ¸.""" = []
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
    ÃÃÃÃÂ¾ÃÂ´ ÃÂ²ÃÂ»ÃÂ¾ÃÂ¶ÃÂµÃÂ½ÃÂ½ÃÃ dict/list ÃÂ² ÃÃÂ¸ÃÃÂ¸ÃÂ½Ã.
    ÃÃÂ¾ÃÂ·ÃÂ²ÃÃÂ°ÃÃÂ°ÃÂµÃ ÃÂ²ÃÃÂµ dict, ÃÃÃÂ¾ÃÃ ÃÂ»ÃÂµÃÂ³ÃÂºÃÂ¾ ÃÂ½ÃÂ°ÃÂ¹ÃÃÂ¸ id/status/url ÃÂ³ÃÂ´ÃÂµ ÃÃÂ³ÃÂ¾ÃÂ´ÃÂ½ÃÂ¾ ÃÂ² ÃÂ¾ÃÃÂ²ÃÂµÃÃÂµ.
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
    ÃÃÂ¾ÃÃÃÂ°ÃÃ URL ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÂ¸ÃÂ· ÃÂ»ÃÃÃÃ ÃÃÂ¾ÃÃÂ¼ ÃÂ¾ÃÃÂ²ÃÂµÃÃÂ¾ÃÂ² (Comet/Runway/Luma/etc).
    ÃÂ§ÃÂ°ÃÃÃÂ¾ Comet: data -> data -> output: [ "https://...mp4" ]
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
        # ÃÃÃÃÃÃÃÂµ ÃÂºÃÂ»ÃÃÃÂ¸
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

        # ÃÃÂ¸ÃÂ¿ÃÂ¸ÃÃÂ½ÃÃÂµ ÃÂºÃÂ¾ÃÂ½ÃÃÂµÃÂ¹ÃÂ½ÃÂµÃÃ
        for k in ("data", "result", "response", "payload", "assets"):
            u = _pick_video_url(obj.get(k))
            if u:
                return u

        # ÃÂ¾ÃÃÃÂ¸ÃÂ¹ ÃÂ¾ÃÃÃÂ¾ÃÂ´
        for v in obj.values():
            u = _pick_video_url(v)
            if u:
                return u

    return None

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ RUNWAY: TEXT Ã¢ VIDEO Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def _run_runway_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    duration_s: int,
    aspect: str,
) -> bool:
    """
    ÃÂ¢ÃÂµÃÂºÃÃ Ã¢ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÂ² Runway (ÃÃÂµÃÃÂµÃÂ· CometAPI /runwayml/v1/text_to_video).
    """
    msg = update.effective_message
    chat_id = update.effective_chat.id

    api_key = (os.environ.get("COMETAPI_KEY") or COMETAPI_KEY or "").strip()
    if not api_key:
        api_key = (os.environ.get("RUNWAY_API_KEY") or RUNWAY_API_KEY or "").strip()

    if not api_key:
        await msg.reply_text("Ã¢ Ã¯Â¸ Runway: ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÃÃÃÂ¾ÃÂµÃÂ½ API-ÃÂºÃÂ»ÃÃ (COMETAPI_KEY / RUNWAY_API_KEY).")
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
                    "Ã¢ Ã¯Â¸ Runway (textÃ¢video) ÃÂ¾ÃÃÂºÃÂ»ÃÂ¾ÃÂ½ÃÂ¸ÃÂ» ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃ "
                    f"({r.status_code}).\nÃÃÃÂ²ÃÂµÃ ÃÃÂµÃÃÂ²ÃÂµÃÃÂ°:\n`{txt}`",
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
                    "Ã¢ Ã¯Â¸ Runway (textÃ¢video) ÃÂ½ÃÂµ ÃÂ²ÃÂµÃÃÂ½ÃÃÂ» ID ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃÂ¸.\n"
                    f"ÃÃÃÂ²ÃÂµÃ ÃÃÂµÃÃÂ²ÃÂµÃÃÂ°:\n`{snippet}`",
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
                        "Ã¢ Ã¯Â¸ Runway (textÃ¢video) ÃÃÃÂ°ÃÃÃ-ÃÂ·ÃÂ°ÃÂºÃÂ°ÃÂ· ÃÂ²ÃÂµÃÃÂ½ÃÃÂ» ÃÂ¾ÃÃÂ¸ÃÃÂºÃ.\n"
                        f"ÃÃÂ¾ÃÂ´: {rs.status_code}\n"
                        f"ÃÃÃÂ²ÃÂµÃ:\n`{txt}`",
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
                            "Ã¢ Ã¯Â¸ Runway (textÃ¢video): ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃÂ° ÃÂ·ÃÂ°ÃÂ²ÃÂµÃÃÃÂ¸ÃÂ»ÃÂ°ÃÃ, ÃÂ½ÃÂ¾ ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÂ¹ÃÂ´ÃÂµÃÂ½ URL ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾.\n"
                            f"ÃÃÃÂ²ÃÂµÃ ÃÃÂµÃÃÂ²ÃÂµÃÃÂ°:\n`{snippet}`",
                            parse_mode="Markdown",
                        )
                        return False

                    vr = await client.get(video_url, timeout=300)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(
                            "Ã¢ Ã¯Â¸ Runway: ÃÂ½ÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂºÃÂ°ÃÃÂ°ÃÃ ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾ÃÂµ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ "
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
                        f"Ã¢ Runway (textÃ¢video) ÃÂ·ÃÂ°ÃÂ²ÃÂµÃÃÃÂ¸ÃÂ»ÃÂ°ÃÃ Ã ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ¾ÃÂ¹: `{err}`",
                        parse_mode="Markdown",
                    )
                    return False

                if time.time() - started > RUNWAY_MAX_WAIT_S:
                    await msg.reply_text("Ã¢ Runway (textÃ¢video): ÃÂ¿ÃÃÂµÃÂ²ÃÃÃÂµÃÂ½ÃÂ¾ ÃÂ²ÃÃÂµÃÂ¼Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ´ÃÂ°ÃÂ½ÃÂ¸Ã.")
                    return False

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Runway text2video exception: %s", e)
        err = str(e)[:400]
        await msg.reply_text(
            "Ã¢ Runway: ÃÂ½ÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ·ÃÂ°ÃÂ¿ÃÃÃÃÂ¸ÃÃ/ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂ¸ÃÃ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ (textÃ¢video).\n"
            f"ÃÂ¢ÃÂµÃÂºÃÃ ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ¸:\n`{err}`",
            parse_mode="Markdown",
        )


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ KLING: IMAGE Ã¢ VIDEO (ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂ¾ÃÃÂ¾) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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
    ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂ¾ÃÃÂ¾ ÃÃÂµÃÃÂµÃÂ· Kling image2video (CometAPI /kling/v1/videos/image2video).
    """
    msg = update.effective_message
    chat_id = update.effective_chat.id

    api_key = (os.environ.get("COMETAPI_KEY") or COMETAPI_KEY or "").strip()
    if not api_key:
        await msg.reply_text("Ã¢ Ã¯Â¸ Kling: ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÃÃÃÂ¾ÃÂµÃÂ½ COMETAPI_KEY.")
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
                    "Ã¢ Ã¯Â¸ Kling (imageÃ¢video) ÃÂ¾ÃÃÂºÃÂ»ÃÂ¾ÃÂ½ÃÂ¸ÃÂ» ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃ "
                    f"({r.status_code}).\nÃÃÃÂ²ÃÂµÃ ÃÃÂµÃÃÂ²ÃÂµÃÃÂ°:\n`{txt}`",
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
                    "Ã¢ Ã¯Â¸ Kling (imageÃ¢video) ÃÂ½ÃÂµ ÃÂ²ÃÂµÃÃÂ½ÃÃÂ» ID ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃÂ¸.\n"
                    f"ÃÃÃÂ²ÃÂµÃ ÃÃÂµÃÃÂ²ÃÂµÃÃÂ°:\n`{snippet}`",
                    parse_mode="Markdown",
                )
                return

            await msg.reply_text("Ã¢Â³ Kling: ÃÂ°ÃÂ½ÃÂ¸ÃÂ¼ÃÂ¸ÃÃÃ ÃÃÂ¾ÃÃÂ¾Ã¢Â¦")

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
                            "Ã¢ Ã¯Â¸ Kling (imageÃ¢video): ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃÂ° ÃÂ·ÃÂ°ÃÂ²ÃÂµÃÃÃÂ¸ÃÂ»ÃÂ°ÃÃ, ÃÂ½ÃÂ¾ ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÂ¹ÃÂ´ÃÂµÃÂ½ URL ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾.\n"
                            f"ÃÃÃÂ²ÃÂµÃ ÃÃÂµÃÃÂ²ÃÂµÃÃÂ°:\n`{snippet}`",
                            parse_mode="Markdown",
                        )
                        return

                    vr = await client.get(video_url, timeout=300)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(
                            "Ã¢ Ã¯Â¸ Kling: ÃÂ½ÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂºÃÂ°ÃÃÂ°ÃÃ ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾ÃÂµ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ "
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
                        f"Ã¢ Kling (imageÃ¢video) ÃÂ·ÃÂ°ÃÂ²ÃÂµÃÃÃÂ¸ÃÂ»ÃÂ°ÃÃ Ã ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ¾ÃÂ¹: `{err}`",
                        parse_mode="Markdown",
                    )
                    return

                if time.time() - started > KLING_MAX_WAIT_S:
                    await msg.reply_text("Ã¢ Kling (imageÃ¢video): ÃÂ¿ÃÃÂµÃÂ²ÃÃÃÂµÃÂ½ÃÂ¾ ÃÂ²ÃÃÂµÃÂ¼Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ´ÃÂ°ÃÂ½ÃÂ¸Ã.")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Kling image2video exception: %s", e)
        await msg.reply_text(
            "Ã¢ Kling: ÃÂ½ÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ·ÃÂ°ÃÂ¿ÃÃÃÃÂ¸ÃÃ/ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂ¸ÃÃ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ (imageÃ¢video)."
        )


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ KLING: TEXT Ã¢ VIDEO Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

async def _run_kling_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    duration: int,
    aspect: str,
):
    """
    ÃÂ¢ÃÂµÃÂºÃÃ Ã¢ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÂ² Kling (ÃÃÂµÃÃÂµÃÂ· CometAPI /kling/v1/videos/text2video).
    """
    msg = update.effective_message

    if not COMETAPI_KEY:
        await msg.reply_text("Ã¢ Ã¯Â¸ Kling ÃÃÂµÃÃÂµÃÂ· CometAPI ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÃÃÃÂ¾ÃÂµÃÂ½ (ÃÂ½ÃÂµÃ COMETAPI_KEY).")
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
                    "Ã¢ Ã¯Â¸ Kling (textÃ¢video) ÃÂ¾ÃÃÂºÃÂ»ÃÂ¾ÃÂ½ÃÂ¸ÃÂ» ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃ "
                    f"({r.status_code}).\nÃÃÃÂ²ÃÂµÃ ÃÃÂµÃÃÂ²ÃÂµÃÃÂ°:\n`{txt}`",
                    parse_mode="Markdown",
                )
                return

            data = js.get("data") or {}
            inner = data.get("data") or {}
            task_id = data.get("task_id") or inner.get("task_id") or js.get("task_id")

            if not task_id:
                await msg.reply_text(
                    "Ã¢ Ã¯Â¸ Kling: ÃÂ½ÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂ¸ÃÃ task_id ÃÂ¸ÃÂ· ÃÂ¾ÃÃÂ²ÃÂµÃÃÂ°.\n"
                    f"ÃÂ¡ÃÃÃÂ¾ÃÂ¹ ÃÂ¾ÃÃÂ²ÃÂµÃ: `{js}`",
                    parse_mode="Markdown",
                )
                return

            await msg.reply_text("Ã¢Â³ Kling: ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃÂ° ÃÂ¿ÃÃÂ¸ÃÂ½ÃÃÃÂ°, ÃÂ½ÃÂ°ÃÃÂ¸ÃÂ½ÃÂ°Ã ÃÃÂµÃÂ½ÃÂ´ÃÂµÃ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾Ã¢Â¦")

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
                            "Ã¢ Ã¯Â¸ Kling: ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃÂ° ÃÂ·ÃÂ°ÃÂ²ÃÂµÃÃÃÂ¸ÃÂ»ÃÂ°ÃÃ, ÃÂ½ÃÂ¾ ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÂ¹ÃÂ´ÃÂµÃÂ½ URL ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾.\n"
                            f"ÃÂ¡ÃÃÃÂ¾ÃÂ¹ ÃÂ¾ÃÃÂ²ÃÂµÃ: `{sjs}`",
                            parse_mode="Markdown",
                        )
                        return

                    vr = await client.get(video_url, timeout=300.0)
                    try:
                        vr.raise_for_status()
                    except Exception:
                        await msg.reply_text(
                            "Ã¢ Ã¯Â¸ Kling: ÃÂ½ÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂºÃÂ°ÃÃÂ°ÃÃ ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¾ÃÂµ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ "
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
                        f"Ã¢ Kling (textÃ¢video) ÃÂ·ÃÂ°ÃÂ²ÃÂµÃÃÃÂ¸ÃÂ»ÃÃ Ã ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ¾ÃÂ¹: `{err}`",
                        parse_mode="Markdown",
                    )
                    return

                if time.time() - started > KLING_MAX_WAIT_S:
                    await msg.reply_text("Ã¢ Kling (textÃ¢video): ÃÂ¿ÃÃÂµÃÂ²ÃÃÃÂµÃÂ½ÃÂ¾ ÃÂ²ÃÃÂµÃÂ¼Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ´ÃÂ°ÃÂ½ÃÂ¸Ã.")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Kling text2video exception: %s", e)
        err = str(e)[:400]
        await msg.reply_text(
            "Ã¢ Kling: ÃÂ½ÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ·ÃÂ°ÃÂ¿ÃÃÃÃÂ¸ÃÃ/ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂ¸ÃÃ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ (textÃ¢video).\n"
            f"ÃÂ¢ÃÂµÃÂºÃÃ ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ¸:\n`{err}`",
            parse_mode="Markdown",
        )


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ LUMA: IMAGE Ã¢ VIDEO (ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂ¾ÃÃÂ¾) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

async def _run_luma_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    duration_s: int,
    aspect: str,
) -> bool:
    """
    ÃÂ¢ÃÂµÃÂºÃÃ Ã¢ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÂ² Luma Dream Machine (ray-2).
    """
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)

    if not LUMA_API_KEY:
        await update.effective_message.reply_text("Ã¢ Ã¯Â¸ Luma: ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÃÃÃÂ¾ÃÂµÃÂ½ LUMA_API_KEY.")
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
                    "Ã¢ Ã¯Â¸ Luma (textÃ¢video) ÃÂ¾ÃÃÂºÃÂ»ÃÂ¾ÃÂ½ÃÂ¸ÃÂ»ÃÂ° ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃ.\n"
                    f"ÃÃÂ¾ÃÂ´: {r.status_code}\n"
                    f"ÃÃÃÂ²ÃÂµÃ:\n`{txt}`",
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
                    "Ã¢ Ã¯Â¸ Luma: ÃÂ½ÃÂµ ÃÂ²ÃÂµÃÃÂ½ÃÃÂ»ÃÂ° id ÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ°ÃÃÂ¸ÃÂ¸.\n"
                    f"ÃÃÃÂ²ÃÂµÃ ÃÃÂµÃÃÂ²ÃÂµÃÃÂ°:\n`{snippet}`",
                    parse_mode="Markdown",
                )
                return False

            # ÃÃÃÃÃ: status_url ÃÂ´ÃÂ¾ÃÂ»ÃÂ¶ÃÂµÃÂ½ ÃÃÃÃ ÃÂ¡ÃÂ¢Ã ÃÃÃÃ, ÃÂ° ÃÂ½ÃÂµ .format-ÃÂ¼ÃÂµÃÃÂ¾ÃÂ´ÃÂ¾ÃÂ¼
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
                        log.error("Luma: ÃÂ¾ÃÃÂ²ÃÂµÃ ÃÃÂµÃÂ· ÃÃÃÃÂ»ÃÂºÃÂ¸ ÃÂ½ÃÂ° ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾: %s", js)
                        await update.effective_message.reply_text("Ã¢ Luma: ÃÂ¾ÃÃÂ²ÃÂµÃ ÃÂ¿ÃÃÂ¸ÃÃÃÂ» ÃÃÂµÃÂ· ÃÃÃÃÂ»ÃÂºÃÂ¸ ÃÂ½ÃÂ° ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾.")
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
                        await update.effective_message.reply_text("Ã¢ Ã¯Â¸ Luma: ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ° ÃÂ¿ÃÃÂ¸ ÃÃÂºÃÂ°ÃÃÂ¸ÃÂ²ÃÂ°ÃÂ½ÃÂ¸ÃÂ¸/ÃÂ¾ÃÃÂ¿ÃÃÂ°ÃÂ²ÃÂºÃÂµ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾.")
                    return True

                if st in ("failed", "error"):
                    if _is_luma_ip_error(js):
                        await update.effective_message.reply_text(
                            "Ã¢ Luma ÃÂ¾ÃÃÂºÃÂ»ÃÂ¾ÃÂ½ÃÂ¸ÃÂ»ÃÂ° ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã ÃÂ¸ÃÂ·-ÃÂ·ÃÂ° IP (ÃÂ·ÃÂ°ÃÃÂ¸ÃÃÃÂ½ÃÂ½ÃÃÂ¹ ÃÂ¿ÃÂµÃÃÃÂ¾ÃÂ½ÃÂ°ÃÂ¶/ÃÃÃÂµÃÂ½ÃÂ´ ÃÂ² ÃÃÂµÃÂºÃÃÃÂµ).\n"
                            "ÃÃÂµÃÃÂµÃÃÂ¾ÃÃÂ¼ÃÃÂ»ÃÂ¸ÃÃÃÂ¹ ÃÃÂµÃÂ· ÃÂ½ÃÂ°ÃÂ·ÃÂ²ÃÂ°ÃÂ½ÃÂ¸ÃÂ¹ (ÃÂ½ÃÂ°ÃÂ¿ÃÃÂ¸ÃÂ¼ÃÂµÃ: ÃÂ«ÃÂ¿ÃÂ»ÃÃÃÂµÃÂ²ÃÃÂ¹ ÃÂ¼ÃÂµÃÂ´ÃÂ²ÃÂµÃÂ¶ÃÂ¾ÃÂ½ÃÂ¾ÃÂºÃ¢Â¦ÃÂ») ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃÃÂ¹ ÃÂµÃÃ ÃÃÂ°ÃÂ·."
                        )
                    else:
                        await update.effective_message.reply_text(
                            f"Ã¢ Luma (textÃ¢video) ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ°: {_short_luma_error(js)}"
                        )
                    return False

                if time.time() - started > LUMA_MAX_WAIT_S:
                    await update.effective_message.reply_text("Ã¢ Luma (textÃ¢video): ÃÂ¿ÃÃÂµÃÂ²ÃÃÃÂµÃÂ½ÃÂ¾ ÃÂ²ÃÃÂµÃÂ¼Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ´ÃÂ°ÃÂ½ÃÂ¸Ã.")
                    return False

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Luma error: %s", e)
        await update.effective_message.reply_text("Ã¢ Luma: ÃÂ½ÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ·ÃÂ°ÃÂ¿ÃÃÃÃÂ¸ÃÃ/ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂ¸ÃÃ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾.")
                            
# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ LUMA: TEXT Ã¢ VIDEO Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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
        await msg.reply_text("Ã¢ Ã¯Â¸ Sora ÃÃÂµÃÂ¹ÃÃÂ°Ã ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÃÃÃÂ¾ÃÂµÃÂ½ÃÂ° (ÃÂ½ÃÂµÃ ÃÂºÃÂ»ÃÃÃÂµÃÂ¹/URL).")
        return False

    # NOTE: This is an intentionally conservative placeholder.
    # Replace with your Comet aggregator endpoint when ready.
    await msg.reply_text("Ã¢ Ã¯Â¸ Sora ÃÂ¸ÃÂ½ÃÃÂµÃÂ³ÃÃÂ°ÃÃÂ¸Ã ÃÂ²ÃÂºÃÂ»ÃÃÃÂµÃÂ½ÃÂ°, ÃÂ½ÃÂ¾ ÃÃÂ½ÃÂ´ÃÂ¿ÃÂ¾ÃÂ¸ÃÂ½Ã ÃÂµÃÃ ÃÂ½ÃÂµ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÂ½. ÃÃÂ¾ÃÃÂ°ÃÂ²Ã ÃÂ²ÃÃÂ·ÃÂ¾ÃÂ² Comet API.")
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
        fr = fr[:400].rstrip() + "Ã¢Â¦"
    return fr or "unknown error"


async def _run_luma_image2video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    image_url: str,
    prompt: str,
    aspect: str,
):
    """
    Luma: IMAGE Ã¢ VIDEO (ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂ¾ÃÃÂ¾).
    ÃÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃ /generations + keyframes (frame0=image).
    """
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)

    msg = update.effective_message
    chat_id = update.effective_chat.id

    if not LUMA_API_KEY:
        await msg.reply_text("Ã¢ Ã¯Â¸ Luma: ÃÂ½ÃÂµ ÃÂ½ÃÂ°ÃÃÃÃÂ¾ÃÂµÃÂ½ LUMA_API_KEY.")
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
                    "Ã¢ Ã¯Â¸ Luma (imageÃ¢video) ÃÂ¾ÃÃÂºÃÂ»ÃÂ¾ÃÂ½ÃÂ¸ÃÂ»ÃÂ° ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃ.\n"
                    f"ÃÃÂ¾ÃÂ´: {r.status_code}\n"
                    f"ÃÃÃÂ²ÃÂµÃ:\n`{txt}`",
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
                    "Ã¢ Ã¯Â¸ Luma: ÃÂ½ÃÂµ ÃÂ²ÃÂµÃÃÂ½ÃÃÂ»ÃÂ° id ÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ°ÃÃÂ¸ÃÂ¸.\n"
                    f"ÃÃÃÂ²ÃÂµÃ ÃÃÂµÃÃÂ²ÃÂµÃÃÂ°:\n`{snippet}`",
                    parse_mode="Markdown",
                )
                return

            await msg.reply_text("Ã¢Â³ Luma: ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÃ ÃÃÂ¾ÃÃÂ¾Ã¢Â¦")

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
                        await msg.reply_text("Ã¢ Luma: ÃÂ¾ÃÃÂ²ÃÂµÃ ÃÂ¿ÃÃÂ¸ÃÃÃÂ» ÃÃÂµÃÂ· ÃÃÃÃÂ»ÃÂºÃÂ¸ ÃÂ½ÃÂ° ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾.")
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
                        await msg.reply_text("Ã¢ Ã¯Â¸ Luma: ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ° ÃÂ¿ÃÃÂ¸ ÃÃÂºÃÂ°ÃÃÂ¸ÃÂ²ÃÂ°ÃÂ½ÃÂ¸ÃÂ¸/ÃÂ¾ÃÃÂ¿ÃÃÂ°ÃÂ²ÃÂºÃÂµ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾.")
                    return

                if st in ("failed", "error"):
                    if _is_luma_ip_error(js):
                        await msg.reply_text(
                            "Ã¢ Luma ÃÂ¾ÃÃÂºÃÂ»ÃÂ¾ÃÂ½ÃÂ¸ÃÂ»ÃÂ° ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã ÃÂ¸ÃÂ·-ÃÂ·ÃÂ° IP (ÃÂ·ÃÂ°ÃÃÂ¸ÃÃÃÂ½ÃÂ½ÃÃÂ¹ ÃÂ¿ÃÂµÃÃÃÂ¾ÃÂ½ÃÂ°ÃÂ¶/ÃÃÃÂµÃÂ½ÃÂ´ ÃÂ² ÃÃÂµÃÂºÃÃÃÂµ).\n"
                            "ÃÃÂµÃÃÂµÃÃÂ¾ÃÃÂ¼ÃÃÂ»ÃÂ¸ÃÃÃÂ¹ ÃÃÂµÃÂ· ÃÂ½ÃÂ°ÃÂ·ÃÂ²ÃÂ°ÃÂ½ÃÂ¸ÃÂ¹ (ÃÂ½ÃÂ°ÃÂ¿ÃÃÂ¸ÃÂ¼ÃÂµÃ: ÃÂ«ÃÂ¿ÃÂ»ÃÃÃÂµÃÂ²ÃÃÂ¹ ÃÂ¼ÃÂµÃÂ´ÃÂ²ÃÂµÃÂ¶ÃÂ¾ÃÂ½ÃÂ¾ÃÂºÃ¢Â¦ÃÂ») ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃÃÂ¹ ÃÂµÃÃ ÃÃÂ°ÃÂ·."
                        )
                    else:
                        await msg.reply_text(f"Ã¢ Luma (imageÃ¢video) ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ°: {_short_luma_error(js)}")
                    return

                if time.time() - started > LUMA_MAX_WAIT_S:
                    await msg.reply_text("Ã¢ Luma (imageÃ¢video): ÃÂ¿ÃÃÂµÃÂ²ÃÃÃÂµÃÂ½ÃÂ¾ ÃÂ²ÃÃÂµÃÂ¼Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ´ÃÂ°ÃÂ½ÃÂ¸Ã.")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Luma image2video error: %s", e)
        await msg.reply_text("Ã¢ Luma: ÃÂ½ÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÂ·ÃÂ°ÃÂ¿ÃÃÃÃÂ¸ÃÃ/ÃÂ¿ÃÂ¾ÃÂ»ÃÃÃÂ¸ÃÃ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾.")
            
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
            await update.effective_message.reply_text("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂ°ÃÃÂ¿ÃÂ¾ÃÂ·ÃÂ½ÃÂ°ÃÃ ÃÃÂµÃÃ.")
            return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_voice error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("ÃÃÃÂ¸ÃÃÂºÃÂ° ÃÂ¿ÃÃÂ¸ ÃÂ¾ÃÃÃÂ°ÃÃÂ¾ÃÃÂºÃÂµ voice.")

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
            await update.effective_message.reply_text("ÃÃÂµ ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¾ÃÃ ÃÃÂ°ÃÃÂ¿ÃÂ¾ÃÂ·ÃÂ½ÃÂ°ÃÃ ÃÃÂµÃÃ ÃÂ¸ÃÂ· ÃÂ°ÃÃÂ´ÃÂ¸ÃÂ¾.")
            return
        update.message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("on_audio error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("ÃÃÃÂ¸ÃÃÂºÃÂ° ÃÂ¿ÃÃÂ¸ ÃÂ¾ÃÃÃÂ°ÃÃÂ¾ÃÃÂºÃÂµ ÃÂ°ÃÃÂ´ÃÂ¸ÃÂ¾.")


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÃÃÂ°ÃÃÂ¾ÃÃÃÂ¸ÃÂº ÃÂ¾ÃÃÂ¸ÃÃÂ¾ÃÂº PTB Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
async def on_error(update: object, context_: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error: %s", context_.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("ÃÂ£ÃÂ¿Ã, ÃÂ¿ÃÃÂ¾ÃÂ¸ÃÂ·ÃÂ¾ÃÃÂ»ÃÂ° ÃÂ¾ÃÃÂ¸ÃÃÂºÃÂ°. ÃÂ¯ ÃÃÂ¶ÃÂµ ÃÃÂ°ÃÂ·ÃÃÂ¸ÃÃÂ°ÃÃÃ.")
    except Exception:
        pass


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Ã ÃÂ¾ÃÃÃÂµÃÃ ÃÂ´ÃÂ»Ã ÃÃÂµÃÂºÃÃÃÂ¾ÃÂ²ÃÃ ÃÂºÃÂ½ÃÂ¾ÃÂ¿ÃÂ¾ÃÂº/ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ÃÂ¾ÃÂ² Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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
        "Ã° *ÃÂ£ÃÃÃÃÂ°*\n"
        "ÃÃÂ¾ÃÂ¼ÃÂ¾ÃÂ³Ã: ÃÂºÃÂ¾ÃÂ½ÃÃÂ¿ÃÂµÃÂºÃÃ ÃÂ¸ÃÂ· PDF/EPUB/DOCX/TXT, ÃÃÂ°ÃÂ·ÃÃÂ¾Ã ÃÂ·ÃÂ°ÃÂ´ÃÂ°Ã ÃÂ¿ÃÂ¾ÃÃÂ°ÃÂ³ÃÂ¾ÃÂ²ÃÂ¾, ÃÃÃÃÂµ/ÃÃÂµÃÃÂµÃÃÂ°ÃÃ, ÃÂ¼ÃÂ¸ÃÂ½ÃÂ¸-ÃÂºÃÂ²ÃÂ¸ÃÂ·Ã.\n\n"
        "_ÃÃÃÃÃÃÃÂµ ÃÂ´ÃÂµÃÂ¹ÃÃÃÂ²ÃÂ¸Ã:_\n"
        "Ã¢Â¢ Ã ÃÂ°ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÃ PDF Ã¢ ÃÂºÃÂ¾ÃÂ½ÃÃÂ¿ÃÂµÃÂºÃ\n"
        "Ã¢Â¢ ÃÂ¡ÃÂ¾ÃÂºÃÃÂ°ÃÃÂ¸ÃÃ ÃÂ² ÃÃÂ¿ÃÂ°ÃÃÂ³ÃÂ°ÃÂ»ÃÂºÃ\n"
        "Ã¢Â¢ ÃÃÃÃÃÃÂ½ÃÂ¸ÃÃ ÃÃÂµÃÂ¼Ã Ã ÃÂ¿ÃÃÂ¸ÃÂ¼ÃÂµÃÃÂ°ÃÂ¼ÃÂ¸\n"
        "Ã¢Â¢ ÃÃÂ»ÃÂ°ÃÂ½ ÃÂ¾ÃÃÂ²ÃÂµÃÃÂ° / ÃÂ¿ÃÃÂµÃÂ·ÃÂµÃÂ½ÃÃÂ°ÃÃÂ¸ÃÂ¸"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown")

async def on_mode_work_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "Ã°Â¼ *Ã ÃÂ°ÃÃÂ¾ÃÃÂ°*\n"
        "ÃÃÂ¸ÃÃÃÂ¼ÃÂ°/ÃÃÃÂ¸ÃÃ/ÃÃÂµÃÂ·ÃÃÂ¼ÃÂµ/ÃÂ°ÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÃÂ¸ÃÂºÃÂ°, ToDo/ÃÂ¿ÃÂ»ÃÂ°ÃÂ½Ã, ÃÃÂ²ÃÂ¾ÃÂ´ÃÂ½ÃÃÂµ ÃÃÂ°ÃÃÂ»ÃÂ¸ÃÃ ÃÂ¸ÃÂ· ÃÂ´ÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃÂ¾ÃÂ².\n"
        "ÃÃÂ»Ã ÃÂ°ÃÃÃÂ¸ÃÃÂµÃÂºÃÃÂ¾ÃÃÂ°/ÃÂ´ÃÂ¸ÃÂ·ÃÂ°ÃÂ¹ÃÂ½ÃÂµÃÃÂ°/ÃÂ¿ÃÃÂ¾ÃÂµÃÂºÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÃÂ¸ÃÂºÃÂ° Ã¢ ÃÃÃÃÃÂºÃÃÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ¸ÃÂµ ÃÂ¢Ã, ÃÃÂµÃÂº-ÃÂ»ÃÂ¸ÃÃÃ ÃÃÃÂ°ÃÂ´ÃÂ¸ÃÂ¹, "
        "ÃÃÂ²ÃÂ¾ÃÂ´ÃÂ½ÃÃÂµ ÃÃÂ°ÃÃÂ»ÃÂ¸ÃÃ ÃÂ»ÃÂ¸ÃÃÃÂ¾ÃÂ², ÃÂ¿ÃÂ¾ÃÃÃÂ½ÃÂ¸ÃÃÂµÃÂ»ÃÃÂ½ÃÃÂµ ÃÂ·ÃÂ°ÃÂ¿ÃÂ¸ÃÃÂºÃÂ¸.\n\n"
        "_ÃÃÂ¸ÃÃÃÂ¸ÃÂ´Ã:_ GPT-5 (ÃÃÂµÃÂºÃÃ/ÃÂ»ÃÂ¾ÃÂ³ÃÂ¸ÃÂºÃÂ°) + Images (ÃÂ¸ÃÂ»ÃÂ»ÃÃÃÃÃÂ°ÃÃÂ¸ÃÂ¸) + Luma/Runway (ÃÂºÃÂ»ÃÂ¸ÃÂ¿Ã/ÃÂ¼ÃÂ¾ÃÂºÃÂ°ÃÂ¿Ã).\n\n"
        "_ÃÃÃÃÃÃÃÂµ ÃÂ´ÃÂµÃÂ¹ÃÃÃÂ²ÃÂ¸Ã:_\n"
        "Ã¢Â¢ ÃÂ¡ÃÃÂ¾ÃÃÂ¼ÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÃÃÂ¸Ã/ÃÂ¢Ã\n"
        "Ã¢Â¢ ÃÂ¡ÃÂ²ÃÂµÃÃÃÂ¸ ÃÃÃÂµÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ¸Ã ÃÂ² ÃÃÂ°ÃÃÂ»ÃÂ¸ÃÃ\n"
        "Ã¢Â¢ ÃÂ¡ÃÂ³ÃÂµÃÂ½ÃÂµÃÃÂ¸ÃÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÂ¿ÃÂ¸ÃÃÃÂ¼ÃÂ¾/ÃÃÂµÃÂ·ÃÃÂ¼ÃÂµ\n"
        "Ã¢Â¢ ÃÂ§ÃÂµÃÃÂ½ÃÂ¾ÃÂ²ÃÂ¸ÃÂº ÃÂ¿ÃÃÂµÃÂ·ÃÂµÃÂ½ÃÃÂ°ÃÃÂ¸ÃÂ¸"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown")

async def on_mode_fun_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "Ã°Â¥ *Ã ÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸Ã*\n"
        "ÃÂ¤ÃÂ¾ÃÃÂ¾-ÃÂ¼ÃÂ°ÃÃÃÂµÃÃÃÂºÃÂ°Ã: ÃÃÂ´ÃÂ°ÃÂ»ÃÂ¸ÃÃ/ÃÂ·ÃÂ°ÃÂ¼ÃÂµÃÂ½ÃÂ¸ÃÃ ÃÃÂ¾ÃÂ½, ÃÂ´ÃÂ¾ÃÃÂ°ÃÂ²ÃÂ¸ÃÃ/ÃÃÃÃÂ°ÃÃ ÃÂ¾ÃÃÃÂµÃÂºÃ/ÃÃÂµÃÂ»ÃÂ¾ÃÂ²ÃÂµÃÂºÃÂ°, outpaint, "
        "*ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÃÂ°ÃÃÃ ÃÃÂ¾ÃÃÂ¾*.\n"
        "ÃÃÂ¸ÃÂ´ÃÂµÃÂ¾: Luma/Runway Ã¢ ÃÂºÃÂ»ÃÂ¸ÃÂ¿Ã ÃÂ¿ÃÂ¾ÃÂ´ Reels/Shorts; *Reels ÃÂ¿ÃÂ¾ ÃÃÂ¼ÃÃÃÂ»Ã ÃÂ¸ÃÂ· ÃÃÂµÃÂ»ÃÃÂ½ÃÂ¾ÃÂ³ÃÂ¾ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾* "
        "(ÃÃÂ¼ÃÂ½ÃÂ°Ã ÃÂ½ÃÂ°ÃÃÂµÃÂ·ÃÂºÃÂ°), ÃÂ°ÃÂ²ÃÃÂ¾-ÃÃÂ°ÃÂ¹ÃÂ¼ÃÂºÃÂ¾ÃÂ´Ã. ÃÃÂµÃÂ¼Ã/ÃÂºÃÂ²ÃÂ¸ÃÂ·Ã.\n\n"
        "ÃÃÃÃÂµÃÃÂ¸ ÃÂ´ÃÂµÃÂ¹ÃÃÃÂ²ÃÂ¸ÃÂµ ÃÂ½ÃÂ¸ÃÂ¶ÃÂµ:"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown", reply_markup=_fun_quick_kb())

# Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ»ÃÂ°ÃÂ²ÃÂ¸ÃÂ°ÃÃÃÃÂ° ÃÂ«Ã ÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸ÃÃÂ» Ã ÃÂ½ÃÂ¾ÃÂ²ÃÃÂ¼ÃÂ¸ ÃÂºÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ°ÃÂ¼ÃÂ¸ Ã¢Ã¢Ã¢Ã¢Ã¢
def _fun_quick_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("Ã°Â­ ÃÃÂ´ÃÂµÃÂ¸ ÃÂ´ÃÂ»Ã ÃÂ´ÃÂ¾ÃÃÃÂ³ÃÂ°", callback_data="fun:ideas")],
        [InlineKeyboardButton("Ã°Â¬ ÃÂ¡ÃÃÂµÃÂ½ÃÂ°ÃÃÂ¸ÃÂ¹ ÃÃÂ¾ÃÃÃÂ°", callback_data="fun:storyboard")],
        [InlineKeyboardButton("Ã°Â® ÃÃÂ³ÃÃ/ÃÂºÃÂ²ÃÂ¸ÃÂ·",       callback_data="fun:quiz")],
        # ÃÃÂ¾ÃÂ²ÃÃÂµ ÃÂºÃÂ»ÃÃÃÂµÃÂ²ÃÃÂµ ÃÂºÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ¸
        [
            InlineKeyboardButton("Ã°Âª ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ ÃÃÃÂ°ÃÃÂ¾ÃÂµ ÃÃÂ¾ÃÃÂ¾", callback_data="fun:revive"),
            InlineKeyboardButton("Ã°Â¬ Reels ÃÂ¸ÃÂ· ÃÂ´ÃÂ»ÃÂ¸ÃÂ½ÃÂ½ÃÂ¾ÃÂ³ÃÂ¾ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾", callback_data="fun:smartreels"),
        ],
        [
            InlineKeyboardButton("Ã°Â¥ Runway",      callback_data="fun:clip"),
            InlineKeyboardButton("Ã°Â¨ Midjourney",  callback_data="fun:img"),
            InlineKeyboardButton("Ã° STT/TTS",     callback_data="fun:speech"),
        ],
        [InlineKeyboardButton("Ã° ÃÂ¡ÃÂ²ÃÂ¾ÃÃÂ¾ÃÂ´ÃÂ½ÃÃÂ¹ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã", callback_data="fun:free")],
        [InlineKeyboardButton("Ã¢Â¬Ã¯Â¸ ÃÃÂ°ÃÂ·ÃÂ°ÃÂ´", callback_data="fun:back")],
    ]
    return InlineKeyboardMarkup(rows)
    if SORA_ENABLED:
        rows.append([InlineKeyboardButton("Ã¢Â¨ Sora", callback_data="engine:sora")])


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¾ÃÃÂ¼ÃÂ°ÃÂ»ÃÂ¸ÃÂ·ÃÂ°ÃÃÂ¸Ã duration ÃÂ´ÃÂ»Ã Runway/Comet (image_to_video) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
def _normalize_runway_duration_for_comet(seconds: int | float | None) -> int:
    """
    Comet/Runway ÃÂ¿ÃÃÂ¸ÃÂ½ÃÂ¸ÃÂ¼ÃÂ°ÃÂµÃ ÃÃÃÃÂ¾ÃÂ³ÃÂ¾ 5 ÃÂ¸ÃÂ»ÃÂ¸ 10 ÃÃÂµÃÂºÃÃÂ½ÃÂ´.
    ÃÂ¢ÃÃÂµÃÃÂ¾ÃÂ²ÃÂ°ÃÂ½ÃÂ¸ÃÂµ: 7Ã¢9 ÃÃÂµÃÂºÃÃÂ½ÃÂ´ => 10, ÃÂ²ÃÃ ÃÂ¾ÃÃÃÂ°ÃÂ»ÃÃÂ½ÃÂ¾ÃÂµ => 5.
    """
    try:
        d = int(round(float(seconds or 0)))
    except Exception:
        d = 0

    if d == 10 or (7 <= d <= 9):
        return 10
    return 5

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂ¾ÃÃÂ¾: ÃÃÂ½ÃÂ¸ÃÂ²ÃÂµÃÃÃÂ°ÃÂ»ÃÃÂ½ÃÃÂ¹ ÃÂ¿ÃÂ°ÃÂ¹ÃÂ¿ÃÂ»ÃÂ°ÃÂ¹ÃÂ½ (Runway / Kling / Luma) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

async def revive_old_photo_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    engine: str | None = None,
):
    """
    ÃÂ£ÃÂ½ÃÂ¸ÃÂ²ÃÂµÃÃÃÂ°ÃÂ»ÃÃÂ½ÃÃÂ¹ ÃÂ¿ÃÂ°ÃÂ¹ÃÂ¿ÃÂ»ÃÂ°ÃÂ¹ÃÂ½ ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸Ã ÃÃÂ¾ÃÃÂ¾.

    1) ÃÃÂµÃÃÃÂ¼ ÃÂ¿ÃÂ¾ÃÃÂ»ÃÂµÃÂ´ÃÂ½ÃÂµÃÂµ ÃÃÂ¾ÃÃÂ¾ ÃÂ¸ÃÂ· _LAST_ANIM_PHOTO.
    2) ÃÃÃÂ»ÃÂ¸ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº ÃÂ½ÃÂµ ÃÂ²ÃÃÃÃÂ°ÃÂ½ Ã¢ ÃÂ¿ÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÂ¼ÃÂµÃÂ½Ã ÃÂ²ÃÃÃÂ¾ÃÃÂ° (Runway/Kling/Luma).
    3) ÃÃÃÂ»ÃÂ¸ ÃÂ²ÃÃÃÃÂ°ÃÂ½ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº Ã¢ ÃÃÃÂ¸ÃÃÂ°ÃÂµÃÂ¼ ÃÃÂµÃÂ½Ã ÃÂ¸ ÃÂ·ÃÂ°ÃÂ¿ÃÃÃÂºÃÂ°ÃÂµÃÂ¼ ÃÃÂ¾ÃÂ¾ÃÃÂ²ÃÂµÃÃÃÃÂ²ÃÃÃÃÂ¸ÃÂ¹ backend.
    """
    msg = update.effective_message
    user_id = update.effective_user.id

    photo_info = _LAST_ANIM_PHOTO.get(user_id) or {}
    img_bytes = photo_info.get("bytes")
    image_url = (photo_info.get("url") or "").strip()

    if not img_bytes:
        await msg.reply_text(
            "ÃÂ¡ÃÂ½ÃÂ°ÃÃÂ°ÃÂ»ÃÂ° ÃÂ¿ÃÃÂ¸ÃÃÂ»ÃÂ¸ ÃÃÂ¾ÃÃÂ¾ (ÃÂ¶ÃÂµÃÂ»ÃÂ°ÃÃÂµÃÂ»ÃÃÂ½ÃÂ¾ ÃÂ¿ÃÂ¾ÃÃÃÃÂµÃ), "
            "ÃÂ° ÃÂ¿ÃÂ¾ÃÃÂ¾ÃÂ¼ ÃÂ½ÃÂ°ÃÂ¶ÃÂ¼ÃÂ¸ ÃÂ«Ã°Âª ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ ÃÃÃÂ°ÃÃÂ¾ÃÂµ ÃÃÂ¾ÃÃÂ¾ÃÂ» ÃÂ¸ÃÂ»ÃÂ¸ ÃÂºÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃ ÃÂ¿ÃÂ¾ÃÂ´ ÃÃÂ¾ÃÃÂ¾ÃÂ³ÃÃÂ°ÃÃÂ¸ÃÂµÃÂ¹."
        )
        return True

    # ÃÂ¿ÃÂ°ÃÃÂ°ÃÂ¼ÃÂµÃÃÃ (ÃÂ¿ÃÃÂ¸ÃÃÂ»ÃÂ¸ ÃÂ¸ÃÂ· on_photo ÃÃÂµÃÃÂµÃÂ· context.user_data["revive_photo"])
    rp = context.user_data.get("revive_photo") or {}
    dur = int(rp.get("duration") or RUNWAY_DURATION_S or 5)
    asp = (rp.get("aspect") or RUNWAY_RATIO or "720:1280")
    prompt = (rp.get("prompt") or "").strip()

    # ÃÃÂ°ÃÂ³ 1: ÃÂ²ÃÃÃÂ¾Ã ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ°
    if not engine:
        await msg.reply_text("ÃÃÃÃÂµÃÃÂ¸ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº ÃÂ´ÃÂ»Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸Ã ÃÃÂ¾ÃÃÂ¾:", reply_markup=revive_engine_kb())
        return True

    engine = engine.lower().strip()

    # --- ÃÂ³ÃÂ¾ÃÃÂ¾ÃÂ²ÃÂ¸ÃÂ¼ ÃÃÃÂ½ÃÂºÃÃÂ¸ÃÂ¸, ÃÂºÃÂ¾ÃÃÂ¾ÃÃÃÂµ ÃÃÃÂ´ÃÂµÃÂ¼ ÃÂ¾ÃÃÂ´ÃÂ°ÃÂ²ÃÂ°ÃÃ ÃÂ² ÃÃÂ¸ÃÂ»ÃÂ»ÃÂ¸ÃÂ½ÃÂ³ ---
    async def _go_runway():
        # Runway/Comet ÃÃÃÂµÃÃÃÂµÃ ÃÂ¿ÃÃÃÂ»ÃÂ¸ÃÃÂ½ÃÃÂ¹ URL ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ¸
        if not image_url or not image_url.startswith("http"):
            await msg.reply_text(
                "ÃÃÂ»Ã Runway ÃÂ½ÃÃÂ¶ÃÂµÃÂ½ ÃÂ¿ÃÃÃÂ»ÃÂ¸ÃÃÂ½ÃÃÂ¹ URL ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã (Telegram file_path). "
                "ÃÃÃÂ¸ÃÃÂ»ÃÂ¸ ÃÃÂ¾ÃÃÂ¾ ÃÂµÃÃ ÃÃÂ°ÃÂ·."
            )
            return
        await _run_runway_animate_photo(update, context, image_url, prompt, dur, asp)

    async def _go_kling():
        await _run_kling_animate_photo(update, context, img_bytes, prompt, dur, asp)

    async def _go_luma():
        if not image_url or not image_url.startswith("http"):
            await msg.reply_text(
                "ÃÃÂ»Ã Luma ÃÂ½ÃÃÂ¶ÃÂµÃÂ½ ÃÂ¿ÃÃÃÂ»ÃÂ¸ÃÃÂ½ÃÃÂ¹ URL ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã (Telegram file_path). "
                "ÃÃÃÂ¸ÃÃÂ»ÃÂ¸ ÃÃÂ¾ÃÃÂ¾ ÃÂµÃÃ ÃÃÂ°ÃÂ·."
            )
            return
        await _run_luma_image2video(update, context, image_url, prompt, asp)

    # ÃÃÃÂ¾ÃÂ¸ÃÂ¼ÃÂ¾ÃÃÃ (ÃÃÂµÃÃÂ½ÃÂ¾ÃÂ²ÃÂ°Ã)
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

    await msg.reply_text("ÃÃÂµÃÂ¸ÃÂ·ÃÂ²ÃÂµÃÃÃÂ½ÃÃÂ¹ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸Ã. ÃÃÂ¾ÃÂ¿ÃÃÂ¾ÃÃÃÂ¹ ÃÂµÃÃ ÃÃÂ°ÃÂ·.")
    return True


# Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÃÃÂ°ÃÃÂ¾ÃÃÃÂ¸ÃÂº ÃÃÃÃÃÃÃ ÃÂ´ÃÂµÃÂ¹ÃÃÃÂ²ÃÂ¸ÃÂ¹ ÃÂ«Ã ÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸ÃÃÂ» (revive + ÃÂ²ÃÃÃÂ¾Ã ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ°) Ã¢Ã¢Ã¢Ã¢Ã¢

async def on_cb_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()

    # action Ã¢ ÃÃÂ°ÃÃÃ ÃÂ¿ÃÂ¾ÃÃÂ»ÃÂµ ÃÂ¿ÃÂµÃÃÂ²ÃÂ¾ÃÂ³ÃÂ¾ "fun:" ÃÂ¸ÃÂ»ÃÂ¸ "something:"
    action = data.split(":", 1)[1] if ":" in data else ""

    async def _try_call(*fn_names, **kwargs):
        fn = _pick_first_defined(*fn_names)
        if callable(fn):
            return await fn(update, context, **kwargs)
        return None

    # ---------------------------------------------------------------------
    # ÃÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ° ÃÂ¿ÃÂ¾ÃÂ´ ÃÃÂ¾ÃÃÂ¾ "Ã¢Â¨ ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ ÃÃÂ¾ÃÃÂ¾" (pedit:revive)
    # ---------------------------------------------------------------------
    if data.startswith("pedit:revive"):
        with contextlib.suppress(Exception):
            await q.answer("ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂ¾ÃÃÂ¾")
        # ÃÂ¿ÃÂ¾ÃÂºÃÂ°ÃÂ·ÃÃÂ²ÃÂ°ÃÂµÃÂ¼ ÃÂ²ÃÃÃÂ¾Ã ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ°
        with contextlib.suppress(Exception):
            await q.edit_message_text("ÃÃÃÃÂµÃÃÂ¸ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº ÃÂ´ÃÂ»Ã ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸Ã ÃÃÂ¾ÃÃÂ¾:", reply_markup=revive_engine_kb())
        return

    # ---------------------------------------------------------------------
    # ÃÃÃÃÂ¾Ã ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ° ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸Ã: revive_engine:runway / kling / luma
    # ---------------------------------------------------------------------
    if data.startswith("revive_engine:"):
        with contextlib.suppress(Exception):
            await q.answer()
        engine = data.split(":", 1)[1].strip().lower() if ":" in data else ""

        # ÃÃÂ°ÃÂ¶ÃÂ½ÃÂ¾: ÃÂ·ÃÂ°ÃÂ¿ÃÃÃÂºÃÂ°ÃÂµÃÂ¼ ÃÂ¿ÃÂ°ÃÂ¹ÃÂ¿ÃÂ»ÃÂ°ÃÂ¹ÃÂ½ ÃÂ¸ ÃÃ ÃÂ¿ÃÃÃÂ°ÃÂµÃÂ¼ÃÃ edit-ÃÂ¸ÃÃ ÃÃÃÂ°ÃÃÂ¾ÃÂµ ÃÃÂ¾ÃÂ¾ÃÃÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÂ´ÃÂ°ÃÂ»ÃÃÃÂµ
        await revive_old_photo_flow(update, context, engine=engine)
        return

    # ---------------------------------------------------------------------
    # ÃÃÂµÃÂ½Ã "Ã ÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸Ã" Ã¢ ÃÂ¾ÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ
    # ---------------------------------------------------------------------
    if action == "revive":
        with contextlib.suppress(Exception):
            await q.answer("ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂ¾ÃÃÂ¾")
        await revive_old_photo_flow(update, context, engine=None)
        return

    # ---------------------------------------------------------------------
    # ÃÃÃÃÂ°ÃÂ»ÃÃÂ½ÃÂ¾ÃÂµ Ã¢ ÃÂºÃÂ°ÃÂº Ã ÃÃÂµÃÃ ÃÃÃÂ»ÃÂ¾ (ÃÂ¾ÃÃÃÂ°ÃÂ²ÃÂ»ÃÃ ÃÃÃÃÃÂºÃÃÃÃ)
    # ---------------------------------------------------------------------
    if action == "smartreels":
        if await _try_call("smart_reels_from_video", "video_sense_reels"):
            return
        with contextlib.suppress(Exception):
            await q.answer("Reels ÃÂ¸ÃÂ· ÃÂ´ÃÂ»ÃÂ¸ÃÂ½ÃÂ½ÃÂ¾ÃÂ³ÃÂ¾ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾")
        await q.edit_message_text(
            "Ã°Â¬ *Reels ÃÂ¸ÃÂ· ÃÂ´ÃÂ»ÃÂ¸ÃÂ½ÃÂ½ÃÂ¾ÃÂ³ÃÂ¾ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾*\n"
            "ÃÃÃÂ¸ÃÃÂ»ÃÂ¸ ÃÂ´ÃÂ»ÃÂ¸ÃÂ½ÃÂ½ÃÂ¾ÃÂµ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ (ÃÂ¸ÃÂ»ÃÂ¸ ÃÃÃÃÂ»ÃÂºÃ) + ÃÃÂµÃÂ¼Ã/ÃÂ¦Ã. "
            "ÃÂ¡ÃÂ´ÃÂµÃÂ»ÃÂ°Ã ÃÃÂ¼ÃÂ½ÃÃ ÃÂ½ÃÂ°ÃÃÂµÃÂ·ÃÂºÃ (hook Ã¢ value Ã¢ CTA), ÃÃÃÃÃÂ¸ÃÃÃ ÃÂ¸ ÃÃÂ°ÃÂ¹ÃÂ¼ÃÂºÃÂ¾ÃÂ´Ã. "
            "ÃÂ¡ÃÂºÃÂ°ÃÂ¶ÃÂ¸ ÃÃÂ¾ÃÃÂ¼ÃÂ°Ã: 9:16 ÃÂ¸ÃÂ»ÃÂ¸ 1:1.",
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
            "ÃÃÂ°ÃÂ¿ÃÃÃÃÂ¸ /diag_video ÃÃÃÂ¾ÃÃ ÃÂ¿ÃÃÂ¾ÃÂ²ÃÂµÃÃÂ¸ÃÃ ÃÂºÃÂ»ÃÃÃÂ¸ Luma/Runway.",
            reply_markup=_fun_quick_kb()
        )
        return

    if action == "img":
        if await _try_call("cmd_img", "midjourney_flow", "images_make"):
            return
        with contextlib.suppress(Exception):
            await q.answer()
        await q.edit_message_text(
            "ÃÃÂ²ÃÂµÃÂ´ÃÂ¸ /img ÃÂ¸ ÃÃÂµÃÂ¼Ã ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½ÃÂºÃÂ¸, ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ¿ÃÃÂ¸ÃÃÂ»ÃÂ¸ ÃÃÂµÃÃ.",
            reply_markup=_fun_quick_kb()
        )
        return

    if action == "storyboard":
        if await _try_call("start_storyboard", "storyboard_make"):
            return
        with contextlib.suppress(Exception):
            await q.answer()
        await q.edit_message_text(
            "ÃÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ ÃÃÂµÃÂ¼Ã ÃÃÂ¾ÃÃÃÂ° Ã¢ ÃÂ½ÃÂ°ÃÂºÃÂ¸ÃÂ´ÃÂ°Ã ÃÃÃÃÃÂºÃÃÃÃ ÃÂ¸ ÃÃÂ°ÃÃÂºÃÂ°ÃÂ´ÃÃÂ¾ÃÂ²ÃÂºÃ.",
            reply_markup=_fun_quick_kb()
        )
        return

    if action in {"ideas", "quiz", "speech", "free", "back"}:
        with contextlib.suppress(Exception):
            await q.answer()
        await q.edit_message_text(
            "ÃÃÂ¾ÃÃÂ¾ÃÂ²! ÃÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÃ ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ²ÃÃÃÂµÃÃÂ¸ ÃÂºÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃ ÃÂ²ÃÃÃÂµ.",
            reply_markup=_fun_quick_kb()
        )
        return

    with contextlib.suppress(Exception):
        await q.answer()


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Ã ÃÂ¾ÃÃÃÂµÃÃ-ÃÂºÃÂ½ÃÂ¾ÃÂ¿ÃÂºÃÂ¸ ÃÃÂµÃÂ¶ÃÂ¸ÃÂ¼ÃÂ¾ÃÂ² (ÃÂµÃÂ´ÃÂ¸ÃÂ½ÃÂ°Ã ÃÃÂ¾ÃÃÂºÃÂ° ÃÂ²ÃÃÂ¾ÃÂ´ÃÂ°) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¾ÃÂ·ÃÂ¸ÃÃÂ¸ÃÂ²ÃÂ½ÃÃÂ¹ ÃÂ°ÃÂ²ÃÃÂ¾-ÃÂ¾ÃÃÂ²ÃÂµÃ ÃÂ¿ÃÃÂ¾ ÃÂ²ÃÂ¾ÃÂ·ÃÂ¼ÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ÃÃÃÂ¸ (ÃÃÂµÃÂºÃÃ/ÃÂ³ÃÂ¾ÃÂ»ÃÂ¾Ã) Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
_CAPS_PATTERN = (
    r"(?is)(ÃÃÂ¼ÃÂµÃÂµÃÃ|ÃÂ¼ÃÂ¾ÃÂ¶ÃÂµÃÃ|ÃÂ´ÃÂµÃÂ»ÃÂ°ÃÂµÃÃ|ÃÂ°ÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÂ·ÃÂ¸ÃÃÃÂµÃÃ|ÃÃÂ°ÃÃÂ¾ÃÃÂ°ÃÂµÃÃ|ÃÂ¿ÃÂ¾ÃÂ´ÃÂ´ÃÂµÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ°ÃÂµÃÃ|ÃÃÂ¼ÃÂµÃÂµÃ ÃÂ»ÃÂ¸|ÃÂ¼ÃÂ¾ÃÂ¶ÃÂµÃ ÃÂ»ÃÂ¸)"
    r".{0,120}"
    r"(pdf|epub|fb2|docx|txt|ÃÂºÃÂ½ÃÂ¸ÃÂ³|ÃÂºÃÂ½ÃÂ¸ÃÂ³ÃÂ°|ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½|ÃÃÂ¾ÃÃÂ¾|ÃÂºÃÂ°ÃÃÃÂ¸ÃÂ½|image|jpeg|png|video|ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾|mp4|mov|ÃÂ°ÃÃÂ´ÃÂ¸ÃÂ¾|audio|mp3|wav)"
)

async def on_capabilities_qa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "ÃÃÂ°, ÃÃÂ¼ÃÂµÃ ÃÃÂ°ÃÃÂ¾ÃÃÂ°ÃÃ Ã ÃÃÂ°ÃÂ¹ÃÂ»ÃÂ°ÃÂ¼ÃÂ¸ ÃÂ¸ ÃÂ¼ÃÂµÃÂ´ÃÂ¸ÃÂ°:\n"
        "Ã¢Â¢ Ã° ÃÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃ: PDF/EPUB/FB2/DOCX/TXT Ã¢ ÃÂºÃÂ¾ÃÂ½ÃÃÂ¿ÃÂµÃÂºÃ, ÃÃÂµÃÂ·ÃÃÂ¼ÃÂµ, ÃÂ¸ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸ÃÂµ ÃÃÂ°ÃÃÂ»ÃÂ¸Ã, ÃÂ¿ÃÃÂ¾ÃÂ²ÃÂµÃÃÂºÃÂ° ÃÃÂ°ÃÂºÃÃÂ¾ÃÂ².\n"
        "Ã¢Â¢ Ã°Â¼ ÃÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã: ÃÂ°ÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÂ·/ÃÂ¾ÃÂ¿ÃÂ¸ÃÃÂ°ÃÂ½ÃÂ¸ÃÂµ, ÃÃÂ»ÃÃÃÃÂµÃÂ½ÃÂ¸ÃÂµ, ÃÃÂ¾ÃÂ½, ÃÃÂ°ÃÂ·ÃÂ¼ÃÂµÃÃÂºÃÂ°, ÃÂ¼ÃÂµÃÂ¼Ã, outpaint.\n"
        "Ã¢Â¢ Ã° ÃÃÂ¸ÃÂ´ÃÂµÃÂ¾: ÃÃÂ°ÃÂ·ÃÃÂ¾Ã ÃÃÂ¼ÃÃÃÂ»ÃÂ°, ÃÃÂ°ÃÂ¹ÃÂ¼ÃÂºÃÂ¾ÃÂ´Ã, *Reels ÃÂ¸ÃÂ· ÃÂ´ÃÂ»ÃÂ¸ÃÂ½ÃÂ½ÃÂ¾ÃÂ³ÃÂ¾ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾*, ÃÂ¸ÃÂ´ÃÂµÃÂ¸/ÃÃÂºÃÃÂ¸ÃÂ¿Ã, ÃÃÃÃÃÂ¸ÃÃÃ.\n"
        "Ã¢Â¢ Ã°Â§ ÃÃÃÂ´ÃÂ¸ÃÂ¾/ÃÂºÃÂ½ÃÂ¸ÃÂ³ÃÂ¸: ÃÃÃÂ°ÃÂ½ÃÃÂºÃÃÂ¸ÃÂ¿ÃÃÂ¸Ã, ÃÃÂµÃÂ·ÃÂ¸ÃÃ, ÃÂ¿ÃÂ»ÃÂ°ÃÂ½.\n\n"
        "_ÃÃÂ¾ÃÂ´ÃÃÂºÃÂ°ÃÂ·ÃÂºÃÂ¸:_ ÃÂ¿ÃÃÂ¾ÃÃÃÂ¾ ÃÂ·ÃÂ°ÃÂ³ÃÃÃÂ·ÃÂ¸ÃÃÂµ ÃÃÂ°ÃÂ¹ÃÂ» ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ¿ÃÃÂ¸ÃÃÂ»ÃÂ¸ÃÃÂµ ÃÃÃÃÂ»ÃÂºÃ + ÃÂºÃÂ¾ÃÃÂ¾ÃÃÂºÃÂ¾ÃÂµ ÃÂ¢Ã. "
        "ÃÃÂ»Ã ÃÃÂ¾ÃÃÂ¾ Ã¢ ÃÂ¼ÃÂ¾ÃÂ¶ÃÂ½ÃÂ¾ ÃÂ½ÃÂ°ÃÂ¶ÃÂ°ÃÃ ÃÂ«Ã°Âª ÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ¸ÃÃ ÃÃÃÂ°ÃÃÂ¾ÃÂµ ÃÃÂ¾ÃÃÂ¾ÃÂ», ÃÂ´ÃÂ»Ã ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ Ã¢ ÃÂ«Ã°Â¬ Reels ÃÂ¸ÃÂ· ÃÂ´ÃÂ»ÃÂ¸ÃÂ½ÃÂ½ÃÂ¾ÃÂ³ÃÂ¾ ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ÃÂ»."
    )
    await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=_fun_quick_kb())

# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÃÂ¿ÃÂ¾ÃÂ¼ÃÂ¾ÃÂ³ÃÂ°ÃÃÂµÃÂ»ÃÃÂ½ÃÂ¾ÃÂµ: ÃÂ²ÃÂ·ÃÃÃ ÃÂ¿ÃÂµÃÃÂ²ÃÃ ÃÂ¾ÃÃÃÃÂ²ÃÂ»ÃÂµÃÂ½ÃÂ½ÃÃ ÃÃÃÂ½ÃÂºÃÃÂ¸Ã ÃÂ¿ÃÂ¾ ÃÂ¸ÃÂ¼ÃÂµÃÂ½ÃÂ¸ Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
def _pick_first_defined(*names):
    for n in names:
        fn = globals().get(n)
        if callable(fn):
            return fn
    return None


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ Ã ÃÂµÃÂ³ÃÂ¸ÃÃÃÃÂ°ÃÃÂ¸Ã ÃÃÂµÃÂ½ÃÂ´ÃÂ»ÃÂµÃÃÂ¾ÃÂ² ÃÂ¸ ÃÂ·ÃÂ°ÃÂ¿ÃÃÃÂº Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
def build_application() -> "Application":
    if not BOT_TOKEN:
        raise RuntimeError("ÃÃÂµ ÃÂ·ÃÂ°ÃÂ´ÃÂ°ÃÂ½ BOT_TOKEN ÃÂ² ÃÂ¿ÃÂµÃÃÂµÃÂ¼ÃÂµÃÂ½ÃÂ½ÃÃ ÃÂ¾ÃÂºÃÃÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ¾ÃÂ¼ÃÂ°ÃÂ½ÃÂ´Ã Ã¢Ã¢Ã¢Ã¢Ã¢
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

    # Ã¢Ã¢Ã¢Ã¢Ã¢ ÃÃÂ»ÃÂ°ÃÃÂµÃÂ¶ÃÂ¸ Ã¢Ã¢Ã¢Ã¢Ã¢
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    # >>> PATCH START Ã¢ Handlers wiring (callbacks / media / text) >>>

    # Ã¢Ã¢Ã¢Ã¢Ã¢ WebApp Ã¢Ã¢Ã¢Ã¢Ã¢
    with contextlib.suppress(Exception):
        app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))
    with contextlib.suppress(Exception):
        if hasattr(filters, "WEB_APP_DATA"):
            app.add_handler(MessageHandler(filters.WEB_APP_DATA, on_webapp_data))

    # Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ CALLBACK QUERY HANDLERS Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
    # ÃÃÃÃÃ: ÃÂ¿ÃÂ¾ÃÃÃÂ´ÃÂ¾ÃÂº = ÃÂ¾Ã ÃÃÂ·ÃÂºÃÂ¸Ã ÃÂº ÃÃÂ¸ÃÃÂ¾ÃÂºÃÂ¸ÃÂ¼

    # 1) ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ° / ÃÂ¾ÃÂ¿ÃÂ»ÃÂ°ÃÃÂ°
    app.add_handler(
        CallbackQueryHandler(
            on_cb_plans,
            pattern=r"^(?:plan:|pay:)$|^(?:plan:|pay:).+"
        )
    )

    # 2) Ã ÃÂµÃÂ¶ÃÂ¸ÃÂ¼Ã / ÃÂ¿ÃÂ¾ÃÂ´ÃÂ¼ÃÂµÃÂ½Ã
    app.add_handler(
        CallbackQueryHandler(
            on_mode_cb,
            pattern=r"^(?:mode:|act:|school:|work:)"
        )
    )

    # 3) Fun + Photo Edit + Revive (ÃÃ ÃÃÂ¢ÃÃÂ§ÃÃÂ¡ÃÃÃ ÃÃÃÂ¢ÃÂ§)
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

    # 4) Catch-all (ÃÃÂ¡Ã ÃÃÂ¡ÃÂ¢ÃÃÃÂ¬ÃÃÃ)
    app.add_handler(
        CallbackQueryHandler(on_cb),
        group=0
    )

    # Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ MEDIA HANDLERS Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢

    # ÃÃÂ¾ÃÂ»ÃÂ¾Ã / ÃÂ°ÃÃÂ´ÃÂ¸ÃÂ¾
    voice_fn = _pick_first_defined("handle_voice", "on_voice", "voice_handler")
    if voice_fn:
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_fn), group=1)

    # ÃÂ¤ÃÂ¾ÃÃÂ¾
    photo_fn = _pick_first_defined("handle_photo", "on_photo", "photo_handler", "handle_image_message")
    if photo_fn:
        app.add_handler(MessageHandler(filters.PHOTO, photo_fn), group=1)

    # ÃÃÂ¾ÃÂºÃÃÂ¼ÃÂµÃÂ½ÃÃ
    doc_fn = _pick_first_defined("handle_doc", "on_document", "handle_document", "doc_handler")
    if doc_fn:
        app.add_handler(MessageHandler(filters.Document.ALL, doc_fn), group=1)

    # ÃÃÂ¸ÃÂ´ÃÂµÃÂ¾
    video_fn = _pick_first_defined("handle_video", "on_video", "video_handler")
    if video_fn:
        app.add_handler(MessageHandler(filters.VIDEO, video_fn), group=1)

    # GIF / animation
    gif_fn = _pick_first_defined("handle_gif", "on_gif", "animation_handler")
    if gif_fn:
        app.add_handler(MessageHandler(filters.ANIMATION, gif_fn), group=1)

    # Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ TEXT BUTTONS Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
    import re

    BTN_ENGINES = re.compile(r"^\s*(?:Ã°Â§ \s*)?ÃÃÂ²ÃÂ¸ÃÂ¶ÃÂºÃÂ¸\s*$")
    BTN_BALANCE = re.compile(r"^\s*(?:Ã°Â³|Ã°Â§Â¾)?\s*ÃÃÂ°ÃÂ»ÃÂ°ÃÂ½Ã\s*$")
    BTN_PLANS   = re.compile(r"^\s*(?:Ã¢Â­\s*)?ÃÃÂ¾ÃÂ´ÃÂ¿ÃÂ¸ÃÃÂºÃÂ°(?:\s*[ÃÂ·Ã¢Â¢]\s*ÃÃÂ¾ÃÂ¼ÃÂ¾ÃÃ)?\s*$")
    BTN_STUDY   = re.compile(r"^\s*(?:Ã°\s*)?ÃÂ£Ã[ÃÂµÃ]ÃÃÂ°\s*$")
    BTN_WORK    = re.compile(r"^\s*(?:Ã°Â¼\s*)?Ã ÃÂ°ÃÃÂ¾ÃÃÂ°\s*$")
    BTN_FUN     = re.compile(r"^\s*(?:Ã°Â¥\s*)?Ã ÃÂ°ÃÂ·ÃÂ²ÃÂ»ÃÂµÃÃÂµÃÂ½ÃÂ¸Ã\s*$")

    app.add_handler(MessageHandler(filters.Regex(BTN_ENGINES), on_btn_engines), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_BALANCE), on_btn_balance), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_PLANS),   on_btn_plans),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_STUDY),   on_btn_study),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_WORK),    on_btn_work),    group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_FUN),     on_btn_fun),     group=0)

    # Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ CAPABILITIES Q/A Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
    app.add_handler(
        MessageHandler(filters.Regex(_CAPS_PATTERN), on_capabilities_qa),
        group=1
    )

    # Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ FALLBACK TEXT Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
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

    # Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ ERRORS Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
    err_fn = _pick_first_defined("on_error", "handle_error")
    if err_fn:
        app.add_error_handler(err_fn)

    return app


# Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢ main() Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢Ã¢
def main():
    with contextlib.suppress(Exception):
        db_init()
    with contextlib.suppress(Exception):
        db_init_usage()
    with contextlib.suppress(Exception):
        _db_init_prefs()

    app = build_application()

    if USE_WEBHOOK:
        log.info("Ã° WEBHOOK mode. Public URL: %s  Path: %s  Port: %s", PUBLIC_URL, WEBHOOK_PATH, PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH.lstrip("/"),
            webhook_url=f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}",
            secret_token=(WEBHOOK_SECRET or None),
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        log.info("Ã° POLLING mode.")
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


# ================== GPT5 PRO ADDITIONS Ã¢ STEP 1 ==================
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
    "ru": "Ã° ÃÃÂ¾ÃÃÃÂ¾ ÃÂ¿ÃÂ¾ÃÂ¶ÃÂ°ÃÂ»ÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÂ² GPTÃ¢5 PRO Bot!\nÃÃÃÃÂµÃÃÂ¸ÃÃÂµ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ½ÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ÃÃÂµ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã.",
    "en": "Ã° Welcome to GPTÃ¢5 PRO Bot!\nChoose an engine or type a prompt."
}

ENGINE_REGISTRY = {
    "gemini": {
        "title": "Gemini",
        "desc": "ÃÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÃÂ¸ÃÂºÃÂ°, ÃÂºÃÂ¾ÃÂ´, ÃÃÂ»ÃÂ¾ÃÂ¶ÃÂ½ÃÃÂµ ÃÃÂ°ÃÃÃÃÂ¶ÃÂ´ÃÂµÃÂ½ÃÂ¸Ã"
    },
    "midjourney": {
        "title": "Midjourney",
        "desc": "ÃÃÂµÃÂ½ÃÂµÃÃÂ°ÃÃÂ¸Ã ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸ÃÂ¹ ÃÂ¸ ÃÂ´ÃÂ¸ÃÂ·ÃÂ°ÃÂ¹ÃÂ½ÃÂ°"
    },
    "suno": {
        "title": "Suno",
        "desc": "ÃÃÃÂ·ÃÃÂºÃÂ° ÃÂ¸ ÃÂ°ÃÃÂ´ÃÂ¸ÃÂ¾"
    }
}

# ================== END STEP 1 ==================


# ================== GPT5 PRO ADDITIONS Ã¢ STEP 2 ==================
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


# ================== GPT5 PRO ADDITIONS Ã¢ STEP 3 ==================
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


# ================== GPT5 PRO ADDITIONS Ã¢ STEP 4 ==================
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


# ================== GPT5 PRO ADDITIONS Ã¢ STEP 5 (FINAL) ==================
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
            "Ã° ÃÃÂ¾ÃÃÃÂ¾ ÃÂ¿ÃÂ¾ÃÂ¶ÃÂ°ÃÂ»ÃÂ¾ÃÂ²ÃÂ°ÃÃ ÃÂ² GPT-5 PRO Bot!\n\n"
            "Ã°Â§  Gemini Ã¢ ÃÂ°ÃÂ½ÃÂ°ÃÂ»ÃÂ¸ÃÃÂ¸ÃÂºÃÂ°, ÃÂºÃÂ¾ÃÂ´, ÃÃÂ»ÃÂ¾ÃÂ¶ÃÂ½ÃÃÂµ ÃÃÂ°ÃÃÃÃÂ¶ÃÂ´ÃÂµÃÂ½ÃÂ¸Ã\n"
            "Ã°Â¨ Midjourney Ã¢ ÃÂ¸ÃÂ·ÃÂ¾ÃÃÃÂ°ÃÂ¶ÃÂµÃÂ½ÃÂ¸Ã ÃÂ¸ ÃÂ´ÃÂ¸ÃÂ·ÃÂ°ÃÂ¹ÃÂ½\n"
            "Ã°Âµ Suno Ã¢ ÃÂ¼ÃÃÂ·ÃÃÂºÃÂ° ÃÂ¸ ÃÂ°ÃÃÂ´ÃÂ¸ÃÂ¾\n\n"
            "ÃÃÃÃÂµÃÃÂ¸ÃÃÂµ ÃÂ´ÃÂ²ÃÂ¸ÃÂ¶ÃÂ¾ÃÂº ÃÂ¸ÃÂ»ÃÂ¸ ÃÂ¿ÃÃÂ¾ÃÃÃÂ¾ ÃÂ½ÃÂ°ÃÂ¿ÃÂ¸ÃÃÂ¸ÃÃÂµ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂ¾Ã."
        )
    return (
        "Ã° Welcome to GPT-5 PRO Bot!\n\n"
        "Ã°Â§  Gemini Ã¢ analysis & reasoning\n"
        "Ã°Â¨ Midjourney Ã¢ images & design\n"
        "Ã°Âµ Suno Ã¢ music generation\n\n"
        "Choose an engine or type a prompt."
    )

# ================== END FINAL STEP ==================


# ================== ENV VARIABLES TO ADD / UPDATE ==================
# ÃÃÂ¾ÃÃÂ°ÃÂ²ÃÃÃÂµ/ÃÂ¿ÃÃÂ¾ÃÂ²ÃÂµÃÃÃÃÂµ ÃÃÃÂ¸ ÃÂ¿ÃÂµÃÃÂµÃÂ¼ÃÂµÃÂ½ÃÂ½ÃÃÂµ ÃÂ² Environment (Render):
#
# --- Language ---
# (ÃÃÂ·ÃÃÂº ÃÃÃÂ°ÃÂ½ÃÂ¸ÃÃÃ ÃÂ² SQLite kv_store ÃÂ°ÃÂ²ÃÃÂ¾ÃÂ¼ÃÂ°ÃÃÂ¸ÃÃÂµÃÃÂºÃÂ¸, ÃÂ´ÃÂ¾ÃÂ¿. ENV ÃÂ½ÃÂµ ÃÂ½ÃÃÂ¶ÃÂ½ÃÂ¾)
#
# --- CometAPI shared key (ÃÂµÃÃÂ»ÃÂ¸ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂµÃÃÂµ ÃÃÂµÃÃÂµÃÂ· Comet) ---
# COMETAPI_KEY=...
#
# --- Kling (CometAPI) ---
# KLING_BASE_URL=https://api.cometapi.com
# KLING_MODEL_NAME=kling-v1-6
# KLING_MODE=std               # std|pro (ÃÂµÃÃÂ»ÃÂ¸ ÃÂ¿ÃÂ¾ÃÂ´ÃÂ´ÃÂµÃÃÂ¶ÃÂ¸ÃÂ²ÃÂ°ÃÂµÃÃÃ ÃÂ²ÃÂ°ÃÃÂ¸ÃÂ¼ ÃÂ°ÃÂºÃÂºÃÂ°ÃÃÂ½ÃÃÂ¾ÃÂ¼)
# KLING_ASPECT=9:16
# KLING_DURATION_S=5
# KLING_UNIT_COST_USD=0.80     # ÃÂ¾ÃÂ¿ÃÃÂ¸ÃÂ¾ÃÂ½ÃÂ°ÃÂ»ÃÃÂ½ÃÂ¾ ÃÂ´ÃÂ»Ã ÃÃÂ°ÃÃÃÃÃÂ°/ÃÂ¸ÃÂ½ÃÂ²ÃÂ¾ÃÂ¹ÃÃÂ¾ÃÂ²
#
# --- Runway ---
# RUNWAY_API_KEY=...           # ÃÂµÃÃÂ»ÃÂ¸ ÃÂ¿ÃÃÃÃÂ¾ Ã¢ ÃÃÃÂ´ÃÂµÃ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÂ½ COMETAPI_KEY
# RUNWAY_MODEL=gen3a_turbo
# RUNWAY_API_VERSION=2024-11-06
# RUNWAY_DISABLE_TEXTVIDEO=1   # ÃÂµÃÃÂ»ÃÂ¸ ÃÃÂ¾ÃÃÂ¸ÃÃÂµ ÃÂ·ÃÂ°ÃÂ¿ÃÃÂµÃÃÂ¸ÃÃ ÃÃÂµÃÂºÃÃÃ¢ÃÂ²ÃÂ¸ÃÂ´ÃÂµÃÂ¾ ÃÃÂµÃÃÂµÃÂ· Runway
#
# --- Luma ---
# LUMA_API_KEY=...
# LUMA_BASE_URL=https://api.lumalabs.ai/dream-machine/v1
# LUMA_MODEL=ray-2
# LUMA_ASPECT=16:9
# LUMA_DURATION_S=5
# LUMA_UNIT_COST_USD=0.40      # ÃÂ¾ÃÂ¿ÃÃÂ¸ÃÂ¾ÃÂ½ÃÂ°ÃÂ»ÃÃÂ½ÃÂ¾
#
# --- Sora (ÃÃÂµÃÃÂµÃÂ· Comet / ÃÂ²ÃÂ°Ã ÃÂ¿ÃÃÂ¾ÃÂºÃÃÂ¸) ---
# SORA_ENABLED=0|1
# SORA_COMET_BASE_URL=https://api.cometapi.com
# SORA_COMET_API_KEY=...       # ÃÂµÃÃÂ»ÃÂ¸ ÃÂ¿ÃÃÃÃÂ¾ Ã¢ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÃÂ¹ÃÃÂµ COMETAPI_KEY
# SORA_MODEL_FREE=sora
# SORA_MODEL_PRO=sora
# SORA_UNIT_COST_USD=0.40
#
# --- Gemini (ÃÃÂµÃÃÂµÃÂ· Comet / ÃÂ²ÃÂ°Ã ÃÂ¿ÃÃÂ¾ÃÂºÃÃÂ¸) ---
# GEMINI_API_KEY=...           # ÃÂµÃÃÂ»ÃÂ¸ ÃÂ¿ÃÃÃÃÂ¾ Ã¢ ÃÃÃÂ´ÃÂµÃ ÃÂ¸ÃÃÂ¿ÃÂ¾ÃÂ»ÃÃÂ·ÃÂ¾ÃÂ²ÃÂ°ÃÂ½ COMETAPI_KEY
# GEMINI_BASE_URL=https://api.cometapi.com
# GEMINI_CHAT_PATH=/gemini/v1/chat   # ÃÃÃÃÃ: ÃÂ¿ÃÃÃ ÃÂ·ÃÂ°ÃÂ²ÃÂ¸ÃÃÂ¸Ã ÃÂ¾Ã ÃÂ²ÃÂ°ÃÃÂµÃÂ³ÃÂ¾ ÃÂ¿ÃÃÂ¾ÃÂ²ÃÂ°ÃÂ¹ÃÂ´ÃÂµÃÃÂ°/Comet. ÃÃÃÂ¿ÃÃÂ°ÃÂ²ÃÃÃÂµ ÃÂ¿ÃÃÂ¸ ÃÂ½ÃÂµÃÂ¾ÃÃÃÂ¾ÃÂ´ÃÂ¸ÃÂ¼ÃÂ¾ÃÃÃÂ¸.
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
