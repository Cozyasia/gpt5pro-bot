import hashlib
import hmac
# -*- coding: utf-8 -*-
import os
import re
import json
import time
import types
import base64
import logging
from io import BytesIO
import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import threading
import uuid
import urllib.parse
import shutil
import sys
import tempfile
import subprocess
import contextlib
import random

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ Render Secret Files bootstrap ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
# Must run before any API keys are read from os.environ.
from secret_loader import bootstrap_secret_environment, get_secret
_SECRET_FILE_SOURCES = bootstrap_secret_environment()

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ Rembg cache bootstrap ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
# Render Starter/—Ä—É—á–Ω–æ–π deploy —á–∞—Å—Ç–æ –Ω–µ –∏–º–µ–µ—Ç writable /data.
# Rembg/pooch –¥–æ–ª–∂–µ–Ω –ø–æ–ª—É—á–∏—Ç—å writable U2NET_HOME –î–û –∏–º–ø–æ—Ä—Ç–∞ rembg, –∏–Ω–∞—á–µ –º–æ–¥–µ–ª—å –Ω–µ —Å–∫–∞—á–∏–≤–∞–µ—Ç—Å—è.
def _ensure_writable_dir_env(var_name: str, preferred_default: str, fallback: str) -> str:
    raw = (os.environ.get(var_name) or "").strip()
    candidates = []
    for c in (raw, preferred_default, fallback):
        if c and c not in candidates:
            candidates.append(c)
    last = fallback
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".write_test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            with contextlib.suppress(Exception):
                os.remove(probe)
            os.environ[var_name] = d
            return d
        except Exception:
            last = d
            continue
    # –ü–æ—Å–ª–µ–¥–Ω–∏–π —Ä–µ–∑–µ—Ä–≤ ‚Äî /tmp, –¥–∞–∂–µ –µ—Å–ª–∏ –ø—Ä–æ–≤–µ—Ä–∫–∞ –≤—ã—à–µ –Ω–µ–æ–∂–∏–¥–∞–Ω–Ω–æ –Ω–µ –ø—Ä–æ—à–ª–∞.
    os.environ[var_name] = fallback
    with contextlib.suppress(Exception):
        os.makedirs(fallback, exist_ok=True)
    return fallback

U2NET_HOME = _ensure_writable_dir_env("U2NET_HOME", "/tmp/.u2net", "/tmp/.u2net")
XDG_CACHE_HOME = _ensure_writable_dir_env("XDG_CACHE_HOME", "/tmp/.cache", "/tmp/.cache")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/.matplotlib")
with contextlib.suppress(Exception):
    os.makedirs(os.environ.get("MPLCONFIGDIR", "/tmp/.matplotlib"), exist_ok=True)

from http.server import HTTPServer, BaseHTTPRequestHandler

import httpx
from runway_official import (
    RunwayOfficialClient, RunwayAPIError, RunwayTaskTimeout,
    key_format_hint as runway_key_format_hint,
    safe_key_fingerprint as runway_safe_key_fingerprint,
)
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InputFile,
    LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton, MenuButtonWebApp
)
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters,
    PreCheckoutQueryHandler, CallbackQueryHandler, ApplicationHandlerStop
)
from telegram.constants import ChatAction
from telegram.error import TelegramError, TimedOut, BadRequest
from presentation_studio import PresentationStudio, StudioConfig
# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ TTS imports ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
import contextlib  # —É–∂–µ —É —Ç–µ–±—è –≤—ã—à–µ –µ—Å—Ç—å, –¥—É–±–ª–∏—Ä–æ–≤–∞—Ç—å –ù–ï –Ω–∞–¥–æ, –µ—Å–ª–∏ –∏–º–ø–æ—Ä—Ç —Å—Ç–æ–∏—Ç

# Optional PIL / rembg for photo tools
try:
    from PIL import Image, ImageFilter, ImageOps, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageFilter = None
    ImageOps = None
    ImageDraw = None
try:
    from rembg import remove as rembg_remove, new_session as rembg_new_session
    REMBG_IMPORT_ERROR = ""
except Exception as _rembg_e:
    rembg_remove = None
    rembg_new_session = None
    REMBG_IMPORT_ERROR = repr(_rembg_e)

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ LOGGING ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")
# httpx INFO request logs include full Telegram Bot API URLs, which contain the bot
# credential in the path.  Application-owned provider/delivery logs already record
# status and timing without secrets, so keep transport libraries at WARNING.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

PATCH_VERSION = "v104-presentation-preflight-self-heal-2026-07-16"

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ ENV ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ

def _env_float(name: str, default: float) -> float:
    """
    –ë–µ–∑–æ–ø–∞—Å–Ω–æ–µ —á—Ç–µ–Ω–∏–µ float –∏–∑ ENV:
    - –ø–æ–¥–¥–µ—Ä–∂–∏–≤–∞–µ—Ç –∏ '4,99', –∏ '4.99'
    - –ø—Ä–∏ –æ—à–∏–±–∫–µ –≤–æ–∑–≤—Ä–∞—â–∞–µ—Ç default
    """
    raw = os.environ.get(name)
    if not raw:
        return float(default)
    raw = raw.replace(",", ".").strip()
    try:
        return float(raw)
    except Exception:
        return float(default)

# Commercial pricing guardrails.
# By default the bot uses audited canonical provider costs so stale Render ENV values
# cannot accidentally sell generations below cost. Set PRICING_CANONICAL_COSTS=0
# only when you intentionally want to manage every cost manually in Render.
PRICING_CANONICAL_COSTS = os.environ.get("PRICING_CANONICAL_COSTS", "1").strip().lower() not in ("0", "false", "no", "off")
PRICING_LOCK_1_CREDIT_1_RUB = os.environ.get("PRICING_LOCK_1_CREDIT_1_RUB", "1").strip().lower() not in ("0", "false", "no", "off")
PRICING_MIN_USD_RUB = max(1.0, _env_float("PRICING_MIN_USD_RUB", 100.0))
PRICING_MIN_MULTIPLIER = max(1.0, _env_float("PRICING_MIN_MULTIPLIER", 2.0))

def _pricing_cost(name: str, canonical: float) -> float:
    return float(canonical) if PRICING_CANONICAL_COSTS else _env_float(name, canonical)

BOT_TOKEN = (os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
BOT_USERNAME     = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
PUBLIC_URL       = os.environ.get("PUBLIC_URL", "").strip()
WEBAPP_URL       = os.environ.get("WEBAPP_URL", "").strip()

OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL  = os.environ.get("OPENAI_BASE_URL", "").strip()        # OpenRouter –∏–ª–∏ —Å–≤–æ–π –ø—Ä–æ–∫—Å–∏ –¥–ª—è —Ç–µ–∫—Å—Ç–∞
OPENAI_MODEL     = os.environ.get("OPENAI_MODEL", "openai/gpt-4o-mini").strip()

OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "").strip()

USE_WEBHOOK      = os.environ.get("USE_WEBHOOK", "1").lower() in ("1","true","yes","on")
WEBHOOK_PATH     = os.environ.get("WEBHOOK_PATH", "/tg").strip()
WEBHOOK_SECRET   = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()

BANNER_URL       = os.environ.get("BANNER_URL", "").strip()
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "").strip()

# –í–ê–ñ–ù–û: –ø—Ä–æ–≤–∞–π–¥–µ—Ä —Ç–µ–∫—Å—Ç–∞ (openai / openrouter –∏ —Ç.–ø.)
TEXT_PROVIDER    = os.environ.get("TEXT_PROVIDER", "").strip()

# STT:
OPENAI_STT_KEY   = os.environ.get("OPENAI_STT_KEY", "").strip()
TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1").strip()
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "").strip()

# TTS:
OPENAI_TTS_KEY       = os.environ.get("OPENAI_TTS_KEY", "").strip() or OPENAI_API_KEY
OPENAI_TTS_BASE_URL  = (os.environ.get("OPENAI_TTS_BASE_URL", "").strip() or "https://api.openai.com/v1")
OPENAI_TTS_MODEL     = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip()
OPENAI_TTS_VOICE     = os.environ.get("OPENAI_TTS_VOICE", "alloy").strip()
# –ì–æ–ª–æ—Å –ø–æ —É–º–æ–ª—á–∞–Ω–∏—é –∏–º–µ–Ω–Ω–æ –¥–ª—è –≥–æ–≤–æ—Ä—è—â–µ–≥–æ –∞–≤–∞—Ç–∞—Ä–∞. –ü–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å –º–æ–∂–µ—Ç –≤—ã–±—Ä–∞—Ç—å –≥–æ–ª–æ—Å –∫–Ω–æ–ø–∫–æ–π –≤ –º–µ–Ω—é –∞–≤–∞—Ç–∞—Ä–∞.
AVATAR_TTS_DEFAULT_VOICE = os.environ.get("AVATAR_TTS_DEFAULT_VOICE", OPENAI_TTS_VOICE or "nova").strip() or "nova"
AVATAR_TTS_VOICES = [v.strip() for v in os.environ.get("AVATAR_TTS_VOICES", "nova,alloy,onyx,shimmer,fable").split(",") if v.strip()]
TTS_MAX_CHARS        = int(os.environ.get("TTS_MAX_CHARS", "1000") or "1000")
# 0 = –Ω–µ –¥—É–±–ª–∏—Ä–æ–≤–∞—Ç—å –æ–∑–≤—É—á–µ–Ω–Ω—ã–π —Ç–µ–∫—Å—Ç –ø–æ–¥–ø–∏—Å—å—é –∫ voice-—Å–æ–æ–±—â–µ–Ω–∏—é.
# –ü–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å –ø–æ–ª—É—á–∞–µ—Ç: —Ç–µ–∫—Å—Ç–æ–≤—ã–π –æ—Ç–≤–µ—Ç + –æ—Ç–¥–µ–ª—å–Ω–æ–µ voice –±–µ–∑ caption.
TTS_VOICE_CAPTION    = os.environ.get("TTS_VOICE_CAPTION", "0").strip().lower() in ("1", "true", "yes", "on")
# 0 = –Ω–µ –æ—Ç–ø—Ä–∞–≤–ª—è—Ç—å –æ—Ç–¥–µ–ª—å–Ω–æ–µ —Å–æ–æ–±—â–µ–Ω–∏–µ ¬´–†–∞—Å–ø–æ–∑–Ω–∞–ª: ...¬ª –ø–æ—Å–ª–µ voice/STT.
STT_ECHO_TRANSCRIPT  = os.environ.get("STT_ECHO_TRANSCRIPT", "0").strip().lower() in ("1", "true", "yes", "on")

# –ü–∞–º—è—Ç—å –¥–∏–∞–ª–æ–≥–∞ –¥–ª—è GPT-–æ—Ç–≤–µ—Ç–æ–≤: –∫–æ—Ä–æ—Ç–∫–∞—è –∏—Å—Ç–æ—Ä–∏—è –ø–æ user_id/chat_id.
CHAT_MEMORY_ENABLED      = os.environ.get("CHAT_MEMORY_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
CHAT_MEMORY_MAX_MESSAGES = int(os.environ.get("CHAT_MEMORY_MAX_MESSAGES", "16") or "16")
CHAT_MEMORY_MAX_CHARS    = int(os.environ.get("CHAT_MEMORY_MAX_CHARS", "6000") or "6000")
CHAT_MEMORY_TTL_DAYS     = int(os.environ.get("CHAT_MEMORY_TTL_DAYS", "0") or "0")
# –í–∏—Ä—Ç—É–∞–ª—å–Ω—ã–µ –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å—Å–∫–∏–µ –¥–∏–∞–ª–æ–≥–∏ –≤–Ω—É—Ç—Ä–∏ –æ–¥–Ω–æ–≥–æ Telegram-—á–∞—Ç–∞.
CHAT_MAX_CONVERSATIONS      = max(1, min(4, int(os.environ.get("CHAT_MAX_CONVERSATIONS", "4") or "4")))
CHAT_HISTORY_PAGE_MESSAGES  = max(10, int(os.environ.get("CHAT_HISTORY_PAGE_MESSAGES", "40") or "40"))
CHAT_HISTORY_PAGE_SIZE      = max(4, min(12, int(os.environ.get("CHAT_HISTORY_PAGE_SIZE", "8") or "8")))

# Images:
OPENAI_IMAGE_KEY    = os.environ.get("OPENAI_IMAGE_KEY", "").strip() or OPENAI_API_KEY
IMAGES_BASE_URL     = (os.environ.get("OPENAI_IMAGE_BASE_URL", "").strip() or "https://api.openai.com/v1")
IMAGES_MODEL        = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1").strip() or "gpt-image-1"
OPENAI_IMAGE_QUALITY = os.environ.get("OPENAI_IMAGE_QUALITY", "medium").strip().lower() or "medium"

# Runway
# Priority: Render Environment -> Render Secret File -> legacy alias.
# Supported Secret Files include /etc/secrets/runway.env and, for compatibility, yookassa.env.
RUNWAY_API_KEY, RUNWAY_KEY_SOURCE = get_secret("RUNWAYML_API_SECRET", "RUNWAY_API_KEY", "RUNWAY_KEY")
# Official Runway Developer API is the primary production route. Comet remains only a fallback.
RUNWAY_DIRECT_ENABLED = os.environ.get("RUNWAY_DIRECT_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
RUNWAY_MODEL        = os.environ.get("RUNWAY_MODEL", "gen4.5").strip() or "gen4.5"
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
# Luma Images (–æ–ø—Ü–∏–æ–Ω–∞–ª—å–Ω–æ: –µ—Å–ª–∏ –Ω–µ—Ç ‚Äî –∏—Å–ø–æ–ª—å–∑—É–µ–º OpenAI Images –∫–∞–∫ —Ñ–æ–ª–±—ç–∫)
LUMA_IMG_BASE_URL = os.environ.get("LUMA_IMG_BASE_URL", "").strip().rstrip("/")
LUMA_IMG_MODEL    = os.environ.get("LUMA_IMG_MODEL", "imagine-image-1").strip()

# –§–æ–ª–±—ç–∫–∏ Luma
_fallbacks_raw = ",".join([
    os.environ.get("LUMA_FALLBACKS", ""),
    os.environ.get("LUMA_FALLBACK_BASE_URL", "")
])
LUMA_FALLBACKS = []
for u in re.split(r"[;,]\s*", _fallbacks_raw):
    if not u:
        continue
    u = u.strip().rstrip("/")
    if u and u != LUMA_BASE_URL and u not in LUMA_FALLBACKS:
        LUMA_FALLBACKS.append(u)

# Runway endpoints
RUNWAY_BASE_URL    = (os.environ.get("RUNWAY_BASE_URL", "https://api.dev.runwayml.com").strip().rstrip("/"))
RUNWAY_CREATE_PATH = "/v1/tasks"
RUNWAY_STATUS_PATH = "/v1/tasks/{id}"
RUNWAY_I2V_PATH    = os.environ.get("RUNWAY_I2V_PATH", "/v1/image_to_video").strip() or "/v1/image_to_video"
RUNWAY_TEXT_CREATE_PATH = os.environ.get("RUNWAY_TEXT_CREATE_PATH", "/v1/text_to_video").strip() or "/v1/text_to_video"
RUNWAY_TEXT_COMPAT_PATH = os.environ.get("RUNWAY_TEXT_COMPAT_PATH", "/v1/image_to_video").strip() or "/v1/image_to_video"
RUNWAY_UPLOAD_PATH = os.environ.get("RUNWAY_UPLOAD_PATH", "/v1/uploads").strip() or "/v1/uploads"
RUNWAY_ORGANIZATION_PATH = os.environ.get("RUNWAY_ORGANIZATION_PATH", "/v1/organization").strip() or "/v1/organization"
RUNWAY_API_VERSION = os.environ.get("RUNWAY_API_VERSION", "2024-11-06").strip()
RUNWAY_USE_COMET   = os.environ.get("RUNWAY_USE_COMET", "1").strip().lower() not in ("0", "false", "no", "off")

# CometAPI / Sora / Kling wrappers for image‚Üívideo
COMET_API_KEY  = (os.environ.get("COMET_API_KEY") or os.environ.get("COMETAPI_KEY") or "").strip()
COMET_BASE_URL = os.environ.get("COMET_BASE_URL", "https://api.cometapi.com").strip().rstrip("/")

# Optional Comet image generation fallback for business logos.
# If OpenAI Images/Luma are not configured, the bot tries this route and then a local PNG fallback.
COMET_IMAGE_GEN_MODEL = os.environ.get("COMET_IMAGE_GEN_MODEL", "gpt-image-1").strip() or "gpt-image-1"
COMET_IMAGE_GEN_PATH = os.environ.get("COMET_IMAGE_GEN_PATH", "/v1/images/generations").strip() or "/v1/images/generations"
COMET_IMAGE_GEN_TIMEOUT_S = int(os.environ.get("COMET_IMAGE_GEN_TIMEOUT_S", "180") or "180")
LOGO_LOCAL_FALLBACK = os.environ.get("LOGO_LOCAL_FALLBACK", "1").strip().lower() not in ("0", "false", "no", "off")

# Midjourney through CometAPI (official Comet wrapper flow: submit -> task fetch).
MIDJOURNEY_ENABLED = os.environ.get("MIDJOURNEY_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
MIDJOURNEY_MODE = os.environ.get("MIDJOURNEY_MODE", "fast").strip().lower() or "fast"
if MIDJOURNEY_MODE not in ("relax", "fast", "turbo"):
    MIDJOURNEY_MODE = "fast"
_MJ_PREFIX = {"relax": "", "fast": "/mj-fast", "turbo": "/mj-turbo"}[MIDJOURNEY_MODE]
MIDJOURNEY_CREATE_PATH = os.environ.get("MIDJOURNEY_CREATE_PATH", f"{_MJ_PREFIX}/mj/submit/imagine").strip() or f"{_MJ_PREFIX}/mj/submit/imagine"
MIDJOURNEY_STATUS_PATH = os.environ.get("MIDJOURNEY_STATUS_PATH", "/mj/task/{id}/fetch").strip() or "/mj/task/{id}/fetch"
MIDJOURNEY_TIMEOUT_S = int(os.environ.get("MIDJOURNEY_TIMEOUT_S", "600") or 600)
MIDJOURNEY_POLL_DELAY_S = float(os.environ.get("MIDJOURNEY_POLL_DELAY_S", "5") or 5)
MIDJOURNEY_UNIT_COST_USD = _pricing_cost("MIDJOURNEY_UNIT_COST_USD", 0.168 if MIDJOURNEY_MODE == "turbo" else 0.056)
MIDJOURNEY_DEFAULT_VERSION = os.environ.get("MIDJOURNEY_DEFAULT_VERSION", "7").strip() or "7"

# Suno / music generation through CometAPI-compatible gateway.
# Endpoints differ by Comet channel, so paths are configurable and several payloads are tried.
SUNO_ENABLED = os.environ.get("SUNO_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
SUNO_API_KEY = (os.environ.get("SUNO_API_KEY") or COMET_API_KEY).strip()
SUNO_BASE_URL = os.environ.get("SUNO_BASE_URL", COMET_BASE_URL).strip().rstrip("/")
SUNO_MODEL = os.environ.get("SUNO_MODEL", "chirp-bluejay").strip() or "chirp-bluejay"
# Comet Suno uses mv values, not OpenAI-style model names. Keep compatibility
# with old Render ENV values from earlier builds.
_suno_model_map = {
    "suno": "chirp-bluejay",
    "suno-v4": "chirp-v4",
    "suno-v4.0": "chirp-v4",
    "suno-v4.5": "chirp-auk",
    "suno-4.5": "chirp-auk",
    "suno-v4.5+": "chirp-bluejay",
    "suno-4.5+": "chirp-bluejay",
    "suno-v5": "chirp-crow",
    "suno-5": "chirp-crow",
}
SUNO_MODEL = _suno_model_map.get(SUNO_MODEL.lower(), SUNO_MODEL)
SUNO_CREATE_PATH = os.environ.get("SUNO_CREATE_PATH", "/suno/submit/music").strip() or "/suno/submit/music"
SUNO_STATUS_PATH = os.environ.get("SUNO_STATUS_PATH", "/suno/fetch/{id}").strip() or "/suno/fetch/{id}"
SUNO_TIMEOUT_S = int(os.environ.get("SUNO_TIMEOUT_S", "600") or 600)
SUNO_POLL_DELAY_S = float(os.environ.get("SUNO_POLL_DELAY_S", "5.0") or 5.0)
SUNO_COST_USD = _pricing_cost("SUNO_COST_USD", 0.20)
# –ü–æ–∫–∞ –æ—Ç–¥–µ–ª—å–Ω–æ–π –∫–æ–ª–æ–Ω–∫–∏ music –≤ –ë–î –Ω–µ—Ç, —Å–ø–∏—Å—ã–≤–∞–µ–º –∏–∑ –æ–±—â–µ–≥–æ –≤–∏–¥–µ–æ/generative-–±—é–¥–∂–µ—Ç–∞.
SUNO_BILLING_ENGINE = os.environ.get("SUNO_BILLING_ENGINE", "runway").strip().lower() or "runway"

# Background remove/replace pipeline:
# auto = Comet/Bria first, then local rembg fallback; local/rembg = only local.
BG_PROVIDER = os.environ.get("BG_PROVIDER", "photoroom-api-only").strip().lower() or "photoroom-api-only"
BG_COMET_MODEL = os.environ.get("BG_COMET_MODEL", "bria/remove-background").strip() or "bria/remove-background"
BG_COMET_REMOVE_PATH = os.environ.get("BG_COMET_REMOVE_PATH", "/v1/images/edits").strip() or "/v1/images/edits"
BG_REMOVE_TIMEOUT_S = float(os.environ.get("BG_REMOVE_TIMEOUT_S", "90") or 90)
BRIA_API_KEY = os.environ.get("BRIA_API_KEY", "").strip()
BRIA_BASE_URL = os.environ.get("BRIA_BASE_URL", "https://engine.prod.bria-api.com").strip().rstrip("/")
BRIA_REMOVE_PATH = os.environ.get("BRIA_REMOVE_PATH", "/v1/background/remove").strip() or "/v1/background/remove"
# Photoroom Remove Background API (primary production path)
PHOTOROOM_API_KEY = (
    os.environ.get("PHOTOROOM_API_KEY")
    or os.environ.get("PHOTOROOM_KEY")
    or os.environ.get("PHOTOROOM_REMOVE_BG_API_KEY")
    or ""
).strip()
PHOTOROOM_BASE_URL = os.environ.get("PHOTOROOM_BASE_URL", "https://sdk.photoroom.com").strip().rstrip("/")
PHOTOROOM_REMOVE_PATH = os.environ.get("PHOTOROOM_REMOVE_PATH", "/v1/segment").strip() or "/v1/segment"
PHOTOROOM_EDIT_BASE_URL = os.environ.get("PHOTOROOM_EDIT_BASE_URL", "https://image-api.photoroom.com").strip().rstrip("/")
PHOTOROOM_EDIT_PATH = os.environ.get("PHOTOROOM_EDIT_PATH", "/v2/edit").strip() or "/v2/edit"
PHOTOROOM_EDIT_ENABLED = os.environ.get("PHOTOROOM_EDIT_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
PHOTOROOM_EDIT_TIMEOUT_S = float(os.environ.get("PHOTOROOM_EDIT_TIMEOUT_S", "95") or 95)
PHOTOROOM_EDIT_EXPAND_PROMPT_MODE = os.environ.get("PHOTOROOM_EDIT_EXPAND_PROMPT_MODE", "ai.never").strip() or "ai.never"
PHOTOROOM_EDIT_NEGATIVE_PROMPT = (
    os.environ.get("PHOTOROOM_EDIT_NEGATIVE_PROMPT")
    or "phone, smartphone, phone edge, mirror, selfie stick, frame, window frame, black bar, vertical bar, pole, reflection, extra object, extra person, duplicate person, extra hands, text, watermark, logo, illustration, cartoon, painting, anime, CGI, 3d render, surreal background, distorted face, distorted horizon"
).strip()
PHOTOROOM_EDIT_GUIDANCE_SCALE = float(os.environ.get("PHOTOROOM_EDIT_GUIDANCE_SCALE", "0.8") or 0.8)
PHOTOROOM_FORMAT = os.environ.get("PHOTOROOM_FORMAT", "png").strip().lower() or "png"
PHOTOROOM_CHANNELS = os.environ.get("PHOTOROOM_CHANNELS", "rgba").strip().lower() or "rgba"
PHOTOROOM_SIZE = os.environ.get("PHOTOROOM_SIZE", "hd").strip().lower() or "hd"
PHOTOROOM_CROP = os.environ.get("PHOTOROOM_CROP", "false").strip().lower() or "false"
PHOTOROOM_DESPILL = os.environ.get("PHOTOROOM_DESPILL", "false").strip().lower() or "false"
PHOTOROOM_TIMEOUT_S = float(os.environ.get("PHOTOROOM_TIMEOUT_S", "70") or 70)
PHOTOROOM_INPUT_MAX_SIDE = int(os.environ.get("PHOTOROOM_INPUT_MAX_SIDE", "1400") or 1400)
BG_OUTPUT_MAX_SIDE = int(os.environ.get("BG_OUTPUT_MAX_SIDE", "1400") or 1400)
BG_REALISTIC_BACKGROUNDS = os.environ.get("BG_REALISTIC_BACKGROUNDS", "1").strip().lower() not in ("0", "false", "no", "off")
BG_BACKGROUND_TIMEOUT_S = float(os.environ.get("BG_BACKGROUND_TIMEOUT_S", "12") or 12)
BG_CACHE_DIR = os.environ.get("BG_CACHE_DIR", "/tmp/bg_cache").strip() or "/tmp/bg_cache"
BG_REPLACE_TWO_STAGE = os.environ.get("BG_REPLACE_TWO_STAGE", "1").strip().lower() not in ("0", "false", "no", "off")
BG_REPLACE_GENERATE_PRESETS = os.environ.get("BG_REPLACE_GENERATE_PRESETS", "0").strip().lower() in ("1", "true", "yes", "on")
BG_REPLACE_GENERATE_CUSTOM = os.environ.get("BG_REPLACE_GENERATE_CUSTOM", "1").strip().lower() not in ("0", "false", "no", "off")
BG_REPLACE_USE_STOCK_BACKGROUNDS = os.environ.get("BG_REPLACE_USE_STOCK_BACKGROUNDS", "1").strip().lower() not in ("0", "false", "no", "off")
BG_REPLACE_JPEG_QUALITY = int(os.environ.get("BG_REPLACE_JPEG_QUALITY", "94") or 94)

# Face swap production pipeline:
# piapi = fast/cheap primary; segmind = quality fallback/premium.
FACESWAP_ENABLED = os.environ.get("FACESWAP_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
FACESWAP_PROVIDER = os.environ.get("FACESWAP_PROVIDER", "piapi").strip().lower() or "piapi"
FACESWAP_FALLBACK_PROVIDER = os.environ.get("FACESWAP_FALLBACK_PROVIDER", "segmind-v2").strip().lower() or "segmind-v2"
FACESWAP_FAST_PROVIDER = os.environ.get("FACESWAP_FAST_PROVIDER", FACESWAP_PROVIDER).strip().lower() or FACESWAP_PROVIDER
FACESWAP_PREMIUM_PROVIDER = os.environ.get("FACESWAP_PREMIUM_PROVIDER", "segmind-v4").strip().lower() or "segmind-v4"
FACESWAP_ASK_TARGET_FACE = os.environ.get("FACESWAP_ASK_TARGET_FACE", "1").strip().lower() not in ("0", "false", "no", "off")
FACESWAP_ASK_SOURCE_FACE = os.environ.get("FACESWAP_ASK_SOURCE_FACE", "1").strip().lower() not in ("0", "false", "no", "off")
FACESWAP_STRICT_SELECTED_FACE = os.environ.get("FACESWAP_STRICT_SELECTED_FACE", "1").strip().lower() not in ("0", "false", "no", "off")
FACESWAP_FACE_DETECTION_ENABLED = os.environ.get("FACESWAP_FACE_DETECTION_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
FACESWAP_DETECTION_MAX_SIDE = int(os.environ.get("FACESWAP_DETECTION_MAX_SIDE", "1200") or 1200)
FACESWAP_PREVIEW_MAX_SIDE = int(os.environ.get("FACESWAP_PREVIEW_MAX_SIDE", "1200") or 1200)
FACESWAP_FAST_COST_USD = _pricing_cost("FACESWAP_FAST_COST_USD", 0.03)
FACESWAP_PREMIUM_COST_USD = _pricing_cost("FACESWAP_PREMIUM_COST_USD", 0.12)
FACESWAP_TIMEOUT_S = float(os.environ.get("FACESWAP_TIMEOUT_S", "300") or 300)
FACESWAP_POLL_DELAY_S = float(os.environ.get("FACESWAP_POLL_DELAY_S", "2.5") or 2.5)
FACESWAP_INPUT_MAX_SIDE = int(os.environ.get("FACESWAP_INPUT_MAX_SIDE", "1600") or 1600)
FACESWAP_OUTPUT_MAX_SIDE = int(os.environ.get("FACESWAP_OUTPUT_MAX_SIDE", "1600") or 1600)
FACESWAP_RESULT_AS_DOCUMENT = os.environ.get("FACESWAP_RESULT_AS_DOCUMENT", "0").strip().lower() in ("1", "true", "yes", "on")
FACESWAP_IMAGE_DATA_URL = os.environ.get("FACESWAP_IMAGE_DATA_URL", "0").strip().lower() in ("1", "true", "yes", "on")
FACESWAP_WARN_TEXT = os.environ.get("FACESWAP_WARN_TEXT", "1").strip().lower() not in ("0", "false", "no", "off")
FACESWAP_MANUAL_CHOICE_IF_DETECTION_FAIL = os.environ.get("FACESWAP_MANUAL_CHOICE_IF_DETECTION_FAIL", "1").strip().lower() not in ("0", "false", "no", "off")
# v35: —Ç–æ—á–Ω—ã–π FaceSwap –¥–ª—è –≥—Ä—É–ø–ø–æ–≤—ã—Ö —Ñ–æ—Ç–æ.
# –ò–¥–µ—è: –µ—Å–ª–∏ –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å –≤—ã–±—Ä–∞–ª –∫–æ–Ω–∫—Ä–µ—Ç–Ω–æ–µ –ª–∏—Ü–æ, –º—ã –∏–∑–æ–ª–∏—Ä—É–µ–º —ç—Ç–æ –ª–∏—Ü–æ –¥–ª—è –ø—Ä–æ–≤–∞–π–¥–µ—Ä–∞,
# –∞ –∑–∞—Ç–µ–º –≤–æ–∑–≤—Ä–∞—â–∞–µ–º –≤ –∏—Å—Ö–æ–¥–Ω—ã–π –∫–∞–¥—Ä —Ç–æ–ª—å–∫–æ –∏–∑–º–µ–Ω—ë–Ω–Ω—É—é –æ–±–ª–∞—Å—Ç—å –≤—ã–±—Ä–∞–Ω–Ω–æ–≥–æ –ª–∏—Ü–∞. –¢–∞–∫ –ø—Ä–æ–≤–∞–π–¥–µ—Ä
# –Ω–µ –º–æ–∂–µ—Ç —Å–ª—É—á–∞–π–Ω–æ –ø–æ–º–µ–Ω—è—Ç—å —Å–æ—Å–µ–¥–Ω–µ–≥–æ —á–µ–ª–æ–≤–µ–∫–∞, –¥–∞–∂–µ –µ—Å–ª–∏ –µ–≥–æ –≤–Ω—É—Ç—Ä–µ–Ω–Ω–∏–π –ø–æ—Ä—è–¥–æ–∫ –ª–∏—Ü –¥—Ä—É–≥–æ–π.
FACESWAP_PRECISE_COMPOSITE = os.environ.get("FACESWAP_PRECISE_COMPOSITE", "1").strip().lower() not in ("0", "false", "no", "off")
FACESWAP_FORCE_SEGMIND_FOR_MULTI = os.environ.get("FACESWAP_FORCE_SEGMIND_FOR_MULTI", "1").strip().lower() not in ("0", "false", "no", "off")
FACESWAP_GROUP_ALLOW_SEGMIND_FALLBACK = os.environ.get("FACESWAP_GROUP_ALLOW_SEGMIND_FALLBACK", "1").strip().lower() not in ("0", "false", "no", "off")
FACESWAP_FACE_BOX_FILTER_RATIO = float(os.environ.get("FACESWAP_FACE_BOX_FILTER_RATIO", "0.35") or 0.35)
FACESWAP_SOURCE_CROP_MARGIN = float(os.environ.get("FACESWAP_SOURCE_CROP_MARGIN", "2.20") or 2.20)
FACESWAP_TARGET_HIDE_MARGIN = float(os.environ.get("FACESWAP_TARGET_HIDE_MARGIN", "1.55") or 1.55)
FACESWAP_COMPOSITE_MARGIN_X = float(os.environ.get("FACESWAP_COMPOSITE_MARGIN_X", "1.85") or 1.85)
FACESWAP_COMPOSITE_MARGIN_Y_UP = float(os.environ.get("FACESWAP_COMPOSITE_MARGIN_Y_UP", "1.45") or 1.45)
FACESWAP_COMPOSITE_MARGIN_Y_DOWN = float(os.environ.get("FACESWAP_COMPOSITE_MARGIN_Y_DOWN", "1.75") or 1.75)

PIAPI_API_KEY = (os.environ.get("PIAPI_API_KEY") or os.environ.get("PIAPI_KEY") or "").strip()
PIAPI_BASE_URL = os.environ.get("PIAPI_BASE_URL", "https://api.piapi.ai").strip().rstrip("/")
PIAPI_FACE_CREATE_PATH = os.environ.get("PIAPI_FACE_CREATE_PATH", "/api/v1/task").strip() or "/api/v1/task"
PIAPI_FACE_STATUS_PATH = os.environ.get("PIAPI_FACE_STATUS_PATH", "/api/v1/task/{task_id}").strip() or "/api/v1/task/{task_id}"
PIAPI_FACE_MODEL = os.environ.get("PIAPI_FACE_MODEL", "Qubico/image-toolkit").strip() or "Qubico/image-toolkit"
PIAPI_FACE_TASK_TYPE = os.environ.get("PIAPI_FACE_TASK_TYPE", "face-swap").strip() or "face-swap"

SEGMIND_API_KEY = (os.environ.get("SEGMIND_API_KEY") or os.environ.get("SEGMIND_KEY") or "").strip()
SEGMIND_BASE_URL = os.environ.get("SEGMIND_BASE_URL", "https://api.segmind.com").strip().rstrip("/")
SEGMIND_FACESWAP_MODEL_FAST = os.environ.get("SEGMIND_FACESWAP_MODEL_FAST", "faceswap-v2").strip() or "faceswap-v2"
SEGMIND_FACESWAP_MODEL_PREMIUM = os.environ.get("SEGMIND_FACESWAP_MODEL_PREMIUM", "faceswap-v4").strip() or "faceswap-v4"
SEGMIND_FACE_RESTORE = os.environ.get("SEGMIND_FACE_RESTORE", "codeformer-v0.1.0.pth").strip() or "codeformer-v0.1.0.pth"
SEGMIND_FACE_SWAP_TYPE = os.environ.get("SEGMIND_FACE_SWAP_TYPE", "head").strip() or "head"
SEGMIND_FACE_STYLE_TYPE = os.environ.get("SEGMIND_FACE_STYLE_TYPE", "normal").strip() or "normal"

# Optional legacy remove.bg-compatible fallback; not used unless BG_PROVIDER=multi/auto and key exists.
REMOVE_BG_API_KEY = (os.environ.get("REMOVE_BG_API_KEY") or os.environ.get("REMOVEBG_API_KEY") or "").strip()
REMOVE_BG_BASE_URL = os.environ.get("REMOVE_BG_BASE_URL", "https://api.remove.bg").strip().rstrip("/")
REMOVE_BG_PATH = os.environ.get("REMOVE_BG_PATH", "/v1.0/removebg").strip() or "/v1.0/removebg"
REMOVE_BG_SIZE = os.environ.get("REMOVE_BG_SIZE", "auto").strip() or "auto"
REMOVE_BG_FORMAT = os.environ.get("REMOVE_BG_FORMAT", "png").strip() or "png"
REMOVE_BG_TIMEOUT_S = float(os.environ.get("REMOVE_BG_TIMEOUT_S", "60") or 60)
BG_DISABLE_LOCAL_REMBG = os.environ.get("BG_DISABLE_LOCAL_REMBG", "1").strip().lower() not in ("0", "false", "no", "off")
BRIA_ALLOW_LOCAL_FALLBACK = os.environ.get("BRIA_ALLOW_LOCAL_FALLBACK", "1").strip().lower() not in ("0", "false", "no", "off")
# –°—Ç–∞—Ä—ã–π Render ENV –º–æ–≥ –æ—Å—Ç–∞–≤–ª—è—Ç—å LOCAL_REMBG_ENABLED=0.
# –î–ª—è –ø—Ä–æ–¥–∞–∫—à–Ω-—Å–±–æ—Ä–∫–∏ —Ñ–æ–Ω–∞ –ø—Ä–∏–Ω—É–¥–∏—Ç–µ–ª—å–Ω–æ –≤–∫–ª—é—á–∞–µ–º local rembg,
# –µ—Å–ª–∏ —Å–ø–µ—Ü–∏–∞–ª—å–Ω–æ –Ω–µ –ø–æ—Å—Ç–∞–≤–ª–µ–Ω BG_FORCE_LOCAL_REMBG=0.
BG_FORCE_LOCAL_REMBG = os.environ.get("BG_FORCE_LOCAL_REMBG", "1").strip().lower() not in ("0", "false", "no", "off")
LOCAL_REMBG_ENABLED_RAW = os.environ.get("LOCAL_REMBG_ENABLED", "0").strip().lower()
LOCAL_REMBG_ENABLED = (not BG_DISABLE_LOCAL_REMBG) and (BG_FORCE_LOCAL_REMBG or (LOCAL_REMBG_ENABLED_RAW not in ("0", "false", "no", "off")))
REMBG_MODEL = os.environ.get("REMBG_MODEL", "u2netp").strip() or "u2netp"
LOCAL_REMBG_TIMEOUT_S = float(os.environ.get("LOCAL_REMBG_TIMEOUT_S", "240") or 240)
LOCAL_REMBG_SUBPROCESS = os.environ.get("LOCAL_REMBG_SUBPROCESS", "1").strip().lower() not in ("0", "false", "no", "off")
BG_ACTION_TIMEOUT_S = float(os.environ.get("BG_ACTION_TIMEOUT_S", "180") or 180)
BG_LOCAL_FIRST = os.environ.get("BG_LOCAL_FIRST", "1").strip().lower() not in ("0", "false", "no", "off")
REMBG_MAX_SIDE = int((os.environ.get("REMBG_MAX_SIDE") or "1600").strip() or 1600)
REMBG_MODEL_FALLBACKS = [m.strip() for m in os.environ.get("REMBG_MODEL_FALLBACKS", REMBG_MODEL).split(",") if m.strip()]
if REMBG_MODEL not in REMBG_MODEL_FALLBACKS:
    REMBG_MODEL_FALLBACKS.insert(0, REMBG_MODEL)
with contextlib.suppress(Exception):
    os.environ.setdefault("U2NET_HOME", U2NET_HOME)
    os.makedirs(U2NET_HOME, exist_ok=True)
    os.makedirs(XDG_CACHE_HOME, exist_ok=True)
_REMBG_SESSION = None
_REMBG_SESSION_LOCK = threading.Lock()
_LAST_BG_ERRORS: list[str] = []

def _bg_note_error(message: str):
    try:
        msg = str(message or "").strip()
        if not msg:
            return
        _LAST_BG_ERRORS.append(msg[:700])
        del _LAST_BG_ERRORS[:-8]
    except Exception:
        pass

def _bg_last_errors_text() -> str:
    if not _LAST_BG_ERRORS:
        return "–æ—à–∏–±–æ–∫ –ø–æ–∫–∞ –Ω–µ—Ç"
    return "\n".join(f"‚Ä¢ {x}" for x in _LAST_BG_ERRORS[-5:])


async def cmd_diag_bg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """–î–∏–∞–≥–Ω–æ—Å—Ç–∏–∫–∞ —É–¥–∞–ª–µ–Ω–∏—è/–∑–∞–º–µ–Ω—ã —Ñ–æ–Ω–∞: ENV, rembg import, model session."""
    lines: list[str] = []
    lines.append(f"üß™ BG diagnostic / {PATCH_VERSION}")
    lines.append(f"BG_PROVIDER={BG_PROVIDER}")
    lines.append(f"PHOTOROOM_API_KEY={'on' if bool(PHOTOROOM_API_KEY) else 'off'} remove={PHOTOROOM_BASE_URL}{PHOTOROOM_REMOVE_PATH} edit={PHOTOROOM_EDIT_BASE_URL}{PHOTOROOM_EDIT_PATH} edit_enabled={'on' if PHOTOROOM_EDIT_ENABLED else 'off'}")
    lines.append(f"PHOTOROOM_FORMAT={PHOTOROOM_FORMAT} channels={PHOTOROOM_CHANNELS} size={PHOTOROOM_SIZE} crop={PHOTOROOM_CROP} timeout={PHOTOROOM_TIMEOUT_S}")
    lines.append(f"PHOTOROOM_INPUT_MAX_SIDE={PHOTOROOM_INPUT_MAX_SIDE} BG_OUTPUT_MAX_SIDE={BG_OUTPUT_MAX_SIDE} edit_timeout={PHOTOROOM_EDIT_TIMEOUT_S}s")
    lines.append(f"BG_REALISTIC_BACKGROUNDS={BG_REALISTIC_BACKGROUNDS} cache={BG_CACHE_DIR}")
    lines.append(f"COMET_API_KEY={'on' if bool(COMET_API_KEY) else 'off'}")
    lines.append(f"BRIA_API_KEY={'on' if bool(BRIA_API_KEY) else 'off'}")
    lines.append(f"REMOVE_BG_API_KEY={'on' if bool(REMOVE_BG_API_KEY) else 'off'} base={REMOVE_BG_BASE_URL}{REMOVE_BG_PATH}")
    lines.append(f"LOCAL_REMBG_ENABLED={LOCAL_REMBG_ENABLED} raw={LOCAL_REMBG_ENABLED_RAW} force={BG_FORCE_LOCAL_REMBG} disable={BG_DISABLE_LOCAL_REMBG}")
    lines.append(f"LOCAL_REMBG_SUBPROCESS={LOCAL_REMBG_SUBPROCESS} timeout={LOCAL_REMBG_TIMEOUT_S} action_timeout={BG_ACTION_TIMEOUT_S}")
    lines.append(f"BG_LOCAL_FIRST={BG_LOCAL_FIRST}")
    lines.append(f"REMBG_MAX_SIDE={REMBG_MAX_SIDE}")
    lines.append(f"rembg_import={'ok' if rembg_remove is not None else 'FAILED'}")
    if rembg_remove is None:
        lines.append(f"REMBG_IMPORT_ERROR={REMBG_IMPORT_ERROR[:700]}")
    lines.append(f"REMBG_MODEL={REMBG_MODEL}")
    lines.append(f"REMBG_MODEL_FALLBACKS={','.join(REMBG_MODEL_FALLBACKS) or '-'}")
    lines.append(f"U2NET_HOME={os.environ.get('U2NET_HOME', '')}")
    lines.append(f"XDG_CACHE_HOME={os.environ.get('XDG_CACHE_HOME', '')}")
    lines.append(f"cache_bootstrap_u2net={U2NET_HOME}")

    # –ü—Ä–æ–≤–µ—Ä—è–µ–º –ø–∞–ø–∫–∏ –±–µ–∑ –ø–∞–¥–µ–Ω–∏—è –∫–æ–º–∞–Ω–¥—ã.
    for d in (os.environ.get('U2NET_HOME', ''), os.environ.get('XDG_CACHE_HOME', '')):
        if d:
            try:
                os.makedirs(d, exist_ok=True)
                lines.append(f"dir_ok={d}")
            except Exception as e:
                lines.append(f"dir_FAIL={d}: {e}")

    session_ok = False
    if LOCAL_REMBG_ENABLED and rembg_remove is not None:
        try:
            # –ü–µ—Ä–≤—ã–π –∑–∞–ø—É—Å–∫ –º–æ–∂–µ—Ç —Å–∫–∞—á–∞—Ç—å –º–æ–¥–µ–ª—å, –ø–æ—ç—Ç–æ–º—É –¥–∞—ë–º –±–æ–ª—å—à–µ –≤—Ä–µ–º–µ–Ω–∏.
            sess = await asyncio.wait_for(asyncio.to_thread(_get_local_rembg_session), timeout=min(max(30, int(LOCAL_REMBG_TIMEOUT_S)), 240))
            session_ok = sess is not None
        except Exception as e:
            _bg_note_error(f"diag session failed: {e}")
            lines.append(f"session_error={repr(e)[:700]}")

    lines.append(f"session_ok={session_ok}")
    lines.append("–ü–æ—Å–ª–µ–¥–Ω–∏–µ –æ—à–∏–±–∫–∏:")
    lines.append(_bg_last_errors_text())

    await update.effective_message.reply_text("\n".join(lines)[:3900])
RUNWAY_COMET_CREATE_PATH = os.environ.get("RUNWAY_COMET_CREATE_PATH", "/runwayml/v1/image_to_video").strip() or "/runwayml/v1/image_to_video"
RUNWAY_COMET_STATUS_PATH = os.environ.get("RUNWAY_COMET_STATUS_PATH", "/runwayml/v1/tasks/{id}").strip() or "/runwayml/v1/tasks/{id}"
# Comet/Runway –∏–Ω–æ–≥–¥–∞ –Ω–µ—Å–∫–æ–ª—å–∫–æ –º–∏–Ω—É—Ç –æ—Ç–≤–µ—á–∞–µ—Ç task_not_exist: —ç—Ç–æ —Å—Ç–∞–¥–∏—è –∏–Ω–∏—Ü–∏–∞–ª–∏–∑–∞—Ü–∏–∏.
# –ï—Å–ª–∏ –æ—Ç–≤–µ—Ç –≤–∏—Å–∏—Ç —Å–ª–∏—à–∫–æ–º –¥–æ–ª–≥–æ, –Ω–µ –¥–µ—Ä–∂–∏–º –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è 20 –º–∏–Ω—É—Ç ‚Äî –º—è–≥–∫–æ –ø–µ—Ä–µ–∫–ª—é—á–∞–µ–º—Å—è –Ω–∞ Kling.
RUNWAY_TASK_NOT_EXIST_FALLBACK_S = int(os.environ.get("RUNWAY_TASK_NOT_EXIST_FALLBACK_S", "45") or 45)
RUNWAY_AUTO_FALLBACK_KLING = os.environ.get("RUNWAY_AUTO_FALLBACK_KLING", "1").strip().lower() not in ("0", "false", "no", "off")
# v76: production-safe Runway/Comet controls.
RUNWAY_IMAGE2VIDEO_ENABLED = os.environ.get("RUNWAY_IMAGE2VIDEO_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
RUNWAY_HIDE_TECH_ERRORS = os.environ.get("RUNWAY_HIDE_TECH_ERRORS", "1").strip().lower() not in ("0", "false", "no", "off")
RUNWAY_IMAGE2VIDEO_FAIL_FAST = os.environ.get("RUNWAY_IMAGE2VIDEO_FAIL_FAST", "1").strip().lower() not in ("0", "false", "no", "off")
RUNWAY_PROVIDER_COOLDOWN_S = int(os.environ.get("RUNWAY_PROVIDER_COOLDOWN_S", "300") or 300)
RUNWAY_PROVIDER_FAIL_THRESHOLD = int(os.environ.get("RUNWAY_PROVIDER_FAIL_THRESHOLD", "2") or 2)
# v77: –ø–µ—Ä–≤—ã–º –ø—Ä–æ–±—É–µ–º –ø—É–±–ª–∏—á–Ω—ã–π –∏–¥–µ–Ω—Ç–∏—Ñ–∏–∫–∞—Ç–æ—Ä Comet model page, –∑–∞—Ç–µ–º backend-–∞–ª–∏–∞—Å—ã.
RUNWAY_IMAGE2VIDEO_MODELS_ENV = os.environ.get("RUNWAY_IMAGE2VIDEO_MODELS", "runwayml-image-to-video,gen4_turbo,gen3a_turbo,veo3.1_fast,veo3.1,veo3").strip()
RUNWAY_PUBLIC_FALLBACK_TEXT = os.environ.get("RUNWAY_PUBLIC_FALLBACK_TEXT", "‚ö†Ô∏è –ö–∞–Ω–∞–ª Runway —Å–µ–π—á–∞—Å –Ω–µ–¥–æ—Å—Ç—É–ø–µ–Ω —É –ø—Ä–æ–≤–∞–π–¥–µ—Ä–∞. –ê–≤—Ç–æ–º–∞—Ç–∏—á–µ—Å–∫–∏ –∑–∞–ø—É—Å–∫–∞—é Kling –±–µ–∑ –¥–æ–ø–æ–ª–Ω–∏—Ç–µ–ª—å–Ω–æ–≥–æ —Å–ø–∏—Å–∞–Ω–∏—è.").strip()
# v88: official Runway Developer API first; Comet is secondary and Kling is the production fallback.
RUNWAY_DIRECT_FIRST = os.environ.get("RUNWAY_DIRECT_FIRST", "1").strip().lower() not in ("0", "false", "no", "off")
RUNWAY_TEXT_MODEL = os.environ.get("RUNWAY_TEXT_MODEL", "gen4.5").strip() or "gen4.5"
RUNWAY_DIRECT_TEXT_MODELS_ENV = os.environ.get("RUNWAY_DIRECT_TEXT_MODELS", "gen4.5").strip()
RUNWAY_DIRECT_I2V_MODELS_ENV = os.environ.get("RUNWAY_DIRECT_I2V_MODELS", "gen4.5,gen4_turbo").strip()
RUNWAY_DIRECT_RETRY_ATTEMPTS = max(1, int(os.environ.get("RUNWAY_DIRECT_RETRY_ATTEMPTS", "4") or 4))
RUNWAY_DIRECT_RETRY_BASE_S = max(0.5, float(os.environ.get("RUNWAY_DIRECT_RETRY_BASE_S", "1.5") or 1.5))
RUNWAY_DIRECT_POLL_INTERVAL_S = max(5.0, float(os.environ.get("RUNWAY_DIRECT_POLL_INTERVAL_S", "5.0") or 5.0))
RUNWAY_DIRECT_POLL_MAX_INTERVAL_S = max(RUNWAY_DIRECT_POLL_INTERVAL_S, float(os.environ.get("RUNWAY_DIRECT_POLL_MAX_INTERVAL_S", "15.0") or 15.0))
RUNWAY_DIRECT_UPLOAD_ATTEMPTS = max(1, int(os.environ.get("RUNWAY_DIRECT_UPLOAD_ATTEMPTS", "2") or 2))
RUNWAY_DIRECT_DATA_URI_FALLBACK = os.environ.get("RUNWAY_DIRECT_DATA_URI_FALLBACK", "1").strip().lower() not in ("0", "false", "no", "off")
RUNWAY_COMET_TEXT_MODELS_ENV = os.environ.get("RUNWAY_COMET_TEXT_MODELS", "runway-video,gen4.5").strip()
RUNWAY_TEXT_FALLBACK_KLING = os.environ.get("RUNWAY_TEXT_FALLBACK_KLING", "1").strip().lower() not in ("0", "false", "no", "off")
# –ü—Ä–µ–¥–æ–±—Ä–∞–±–æ—Ç–∫–∞ –∏—Å—Ö–æ–¥–Ω–∏–∫–∞ –¥–ª—è image‚Üívideo: —É–º–µ–Ω—å—à–∞–µ—Ç —Ä–∏—Å–∫, —á—Ç–æ Kling/Runway –æ–∂–∏–≤–∏—Ç –≤–µ—Å—å —Å–∫—Ä–∏–Ω—à–æ—Ç —Ç–µ–ª–µ—Ñ–æ–Ω–∞ –≤–º–µ—Å—Ç–æ –ø–æ—Ä—Ç—Ä–µ—Ç–∞.
I2V_PREPROCESS_ENABLED = os.environ.get("I2V_PREPROCESS_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
I2V_WARN_BAD_SOURCE = os.environ.get("I2V_WARN_BAD_SOURCE", "1").strip().lower() not in ("0", "false", "no", "off")
I2V_AUTOCROP_BLACK_BORDERS = os.environ.get("I2V_AUTOCROP_BLACK_BORDERS", "1").strip().lower() not in ("0", "false", "no", "off")
I2V_MAX_SOURCE_SIDE = int(os.environ.get("I2V_MAX_SOURCE_SIDE", "1280") or 1280)
I2V_BAD_SOURCE_POLICY = os.environ.get("I2V_BAD_SOURCE_POLICY", "warn_continue").strip().lower()  # warn_continue | ask_clean
I2V_KLING_SAFE_PROMPT_SUFFIX = os.environ.get("I2V_KLING_SAFE_PROMPT_SUFFIX", "animate only the person/photo content; do not create phone screens, app interface, black borders, UI overlays, or screenshots; keep identity and original composition").strip()
SORA_API_KEY   = (os.environ.get("SORA_API_KEY") or COMET_API_KEY).strip()
SORA_MODEL     = os.environ.get("SORA_MODEL", "sora-2").strip()
# –ó–∞—â–∏—Ç–∞ –æ—Ç —Å—Ç–∞—Ä–æ–≥–æ ENV Render: –µ—Å–ª–∏ —Ç–∞–º —Å–ª—É—á–∞–π–Ω–æ –æ—Å—Ç–∞–ª–æ—Å—å sora-1,
# Comet –≤–æ–∑–≤—Ä–∞—â–∞–µ—Ç model_not_found. –î–ª—è —ç—Ç–æ–π —Å–±–æ—Ä–∫–∏ –ø—Ä–∏–Ω—É–¥–∏—Ç–µ–ª—å–Ω–æ –∏—Å–ø–æ–ª—å–∑—É–µ–º sora-2.
if SORA_MODEL.lower() in ("", "sora", "sora-1", "sora1"):
    SORA_MODEL = "sora-2"
SORA_CREATE_PATH = os.environ.get("SORA_CREATE_PATH", "/v1/videos").strip() or "/v1/videos"
SORA_STATUS_PATH = os.environ.get("SORA_STATUS_PATH", "/v1/videos/{id}").strip() or "/v1/videos/{id}"
KLING_API_KEY  = (os.environ.get("KLING_API_KEY") or COMET_API_KEY).strip()
KLING_MODEL    = os.environ.get("KLING_MODEL", "kling-v2-6").strip()
# Old v1.6 is increasingly unreliable on the current Comet Kling channel.
# Keep an explicit ENV override, but migrate the stale default automatically.
if KLING_MODEL.lower() in ("", "kling-v1-6", "kling-v1.6"):
    KLING_MODEL = "kling-v2-6"
KLING_CREATE_PATH = os.environ.get("KLING_CREATE_PATH", "/kling/v1/videos/image2video").strip() or "/kling/v1/videos/image2video"
KLING_STATUS_PATH = os.environ.get("KLING_STATUS_PATH", "/kling/v1/videos/image2video/{id}").strip() or "/kling/v1/videos/image2video/{id}"
# Text‚ÜíVideo —á–µ—Ä–µ–∑ CometAPI: Sora 2 (—Ç–æ–ª—å–∫–æ –±–µ–∑ –ª—é–¥–µ–π), Kling –∏ Runway. Luma –≤—Ä–µ–º–µ–Ω–Ω–æ —Å–∫—Ä—ã—Ç–∞.
KLING_TEXT_CREATE_PATH = os.environ.get("KLING_TEXT_CREATE_PATH", "/kling/v1/videos/text2video").strip() or "/kling/v1/videos/text2video"
KLING_TEXT_STATUS_PATH = os.environ.get("KLING_TEXT_STATUS_PATH", "/kling/v1/videos/text2video/{id}").strip() or "/kling/v1/videos/text2video/{id}"

# Kling Avatar / talking head / photo‚Üímusic-video
KLING_AVATAR_CREATE_PATH = os.environ.get("KLING_AVATAR_CREATE_PATH", "/kling/v1/videos/avatar/image2video").strip() or "/kling/v1/videos/avatar/image2video"
KLING_AVATAR_STATUS_PATH = os.environ.get("KLING_AVATAR_STATUS_PATH", "/kling/v1/videos/avatar/image2video/{id}").strip() or "/kling/v1/videos/avatar/image2video/{id}"
KLING_AVATAR_MODE = os.environ.get("KLING_AVATAR_MODE", "std").strip().lower() or "std"
if KLING_AVATAR_MODE not in ("std", "pro"):
    KLING_AVATAR_MODE = "std"
KLING_AVATAR_PROMPT = os.environ.get(
    "KLING_AVATAR_PROMPT",
    "The person talks naturally to camera, realistic facial motion, accurate lip sync, subtle head movement, stable identity."
).strip()

# Text‚Üíspeech for avatar. OpenAI TTS is primary because it supports Russian well;
# Kling TTS is kept as a fallback when the channel is available.
AVATAR_TTS_PROVIDER = os.environ.get("AVATAR_TTS_PROVIDER", "openai").strip().lower() or "openai"
KLING_TTS_CREATE_PATH = os.environ.get("KLING_TTS_CREATE_PATH", "/kling/v1/audio/tts").strip() or "/kling/v1/audio/tts"
KLING_TTS_STATUS_PATH = os.environ.get("KLING_TTS_STATUS_PATH", "/kling/v1/audio/tts/{id}").strip() or "/kling/v1/audio/tts/{id}"
KLING_TTS_VOICE_ID = os.environ.get("KLING_TTS_VOICE_ID", "genshin_vindi2").strip()
KLING_TTS_LANGUAGE = os.environ.get("KLING_TTS_LANGUAGE", "en").strip().lower() or "en"
KLING_TTS_SPEED = _env_float("KLING_TTS_SPEED", 1.0)

PHOTO_CLIP_SOUND = os.environ.get("PHOTO_CLIP_SOUND", "1").strip().lower() not in ("0", "false", "no", "off")
PHOTO_CLIP_MODE = os.environ.get("PHOTO_CLIP_MODE", "pro").strip().lower() or "pro"
if PHOTO_CLIP_MODE not in ("std", "pro"):
    PHOTO_CLIP_MODE = "pro"
SUNO_AUTO_FOR_PHOTO_CLIP = os.environ.get("SUNO_AUTO_FOR_PHOTO_CLIP", "1").strip().lower() in ("1", "true", "yes", "on")
PHOTO_CLIP_PIPELINE = os.environ.get("PHOTO_CLIP_PIPELINE", "1").strip().lower() not in ("0", "false", "no", "off")
PHOTO_CLIP_VIDEO_ENGINE = os.environ.get("PHOTO_CLIP_VIDEO_ENGINE", "kling").strip().lower() or "kling"
PHOTO_CLIP_DEFAULT_DURATION_S = int(os.environ.get("PHOTO_CLIP_DEFAULT_DURATION_S", "15") or 15)
PHOTO_CLIP_MAX_DURATION_S = int(os.environ.get("PHOTO_CLIP_MAX_DURATION_S", "90") or 90)
PHOTO_CLIP_SCENE_SECONDS = max(5, min(10, int(os.environ.get("PHOTO_CLIP_SCENE_SECONDS", "10") or 10)))
PHOTO_CLIP_MAX_SCENES = max(1, min(12, int(os.environ.get("PHOTO_CLIP_MAX_SCENES", "9") or 9)))
PHOTO_CLIP_MUX_AUDIO = os.environ.get("PHOTO_CLIP_MUX_AUDIO", "1").strip().lower() not in ("0", "false", "no", "off")
PHOTO_CLIP_SEND_BASE_IF_MUX_FAILS = os.environ.get("PHOTO_CLIP_SEND_BASE_IF_MUX_FAILS", "0").strip().lower() not in ("0", "false", "no", "off")
PHOTO_CLIP_BACKGROUND_TASK = os.environ.get("PHOTO_CLIP_BACKGROUND_TASK", "1").strip().lower() not in ("0", "false", "no", "off")
PHOTO_CLIP_PARALLEL_STAGES = os.environ.get("PHOTO_CLIP_PARALLEL_STAGES", "1").strip().lower() not in ("0", "false", "no", "off")
PHOTO_CLIP_SUNO_FAST_TIMEOUT_S = int(os.environ.get("PHOTO_CLIP_SUNO_FAST_TIMEOUT_S", "900") or 900)
PHOTO_CLIP_AUDIO_AFTER_VIDEO_WAIT_S = int(os.environ.get("PHOTO_CLIP_AUDIO_AFTER_VIDEO_WAIT_S", "900") or 900)
PHOTO_CLIP_TOTAL_USER_WAIT_S = int(os.environ.get("PHOTO_CLIP_TOTAL_USER_WAIT_S", "1200") or 1200)
PHOTO_CLIP_SEND_BASE_WHILE_MUSIC_PENDING = os.environ.get("PHOTO_CLIP_SEND_BASE_WHILE_MUSIC_PENDING", "0").strip().lower() not in ("0", "false", "no", "off")
FFMPEG_MUX_TIMEOUT_S = int(os.environ.get("FFMPEG_MUX_TIMEOUT_S", "180") or 180)
FFMPEG_MUX_COPY_FIRST = os.environ.get("FFMPEG_MUX_COPY_FIRST", "1").strip().lower() not in ("0", "false", "no", "off")
FFMPEG_MUX_REENCODE_PRESET = os.environ.get("FFMPEG_MUX_REENCODE_PRESET", "ultrafast").strip() or "ultrafast"
FFMPEG_MUX_AUDIO_BITRATE = os.environ.get("FFMPEG_MUX_AUDIO_BITRATE", "128k").strip() or "128k"
FFMPEG_MUX_MAX_MB = int(os.environ.get("FFMPEG_MUX_MAX_MB", "45") or 45)
FFMPEG_MUX_CRF = os.environ.get("FFMPEG_MUX_CRF", "32").strip() or "32"
FFMPEG_MUX_SCALE_HEIGHT = int(os.environ.get("FFMPEG_MUX_SCALE_HEIGHT", "720") or 720)
FFMPEG_MUX_FPS = int(os.environ.get("FFMPEG_MUX_FPS", "24") or 24)

# Audited provider cost estimates. Retail price is calculated centrally with the
# service multiplier. Canonical mode protects the commercial margin from stale ENV.
SORA_COST_PER_SECOND_USD = _pricing_cost("SORA_COST_PER_SECOND_USD", 0.10)
SORA_PRO_COST_PER_SECOND_USD = _pricing_cost("SORA_PRO_COST_PER_SECOND_USD", 0.30)
KLING_5S_COST_USD = _pricing_cost("KLING_5S_COST_USD", 0.23)
RUNWAY_COST_PER_SECOND_USD = _pricing_cost("RUNWAY_COST_PER_SECOND_USD", 0.12)
RUNWAY_TURBO_COST_PER_SECOND_USD = _pricing_cost("RUNWAY_TURBO_COST_PER_SECOND_USD", 0.05)
RUNWAY_5S_COST_USD = _pricing_cost("RUNWAY_5S_COST_USD", RUNWAY_COST_PER_SECOND_USD * 5)
SORA_UNIT_COST_USD = _pricing_cost("SORA_UNIT_COST_USD", SORA_COST_PER_SECOND_USD * 5)
SORA_PRO_UNIT_COST_USD = _pricing_cost("SORA_PRO_UNIT_COST_USD", SORA_PRO_COST_PER_SECOND_USD * 5)
KLING_UNIT_COST_USD = _pricing_cost("KLING_UNIT_COST_USD", KLING_5S_COST_USD)
AVATAR_UNIT_COST_USD = _pricing_cost("AVATAR_UNIT_COST_USD", 0.65)
# 15-second Kling video + Suno + mux/storage overhead.
PHOTO_CLIP_UNIT_COST_USD = _pricing_cost("PHOTO_CLIP_UNIT_COST_USD", 1.00)
SUNO_UNIT_COST_USD = _pricing_cost("SUNO_UNIT_COST_USD", 0.20)
# Music + avatar/lip-sync + retries/processing reserve.
VOCAL_CLIP_UNIT_COST_USD = _pricing_cost("VOCAL_CLIP_UNIT_COST_USD", 1.50)
# Kling Avatar —á–µ—Ä–µ–∑ Comet –Ω–µ—Å—Ç–∞–±–∏–ª—å–Ω–æ –ø—Ä–∏–Ω–∏–º–∞–µ—Ç –¥–ª–∏–Ω–Ω—ã–µ Suno-—Ç—Ä–µ–∫–∏.
# –î–ª—è lip-sync –¥–µ—Ä–∂–∏–º –±–µ–∑–æ–ø–∞—Å–Ω—ã–π —Ñ—Ä–∞–≥–º–µ–Ω—Ç: —Ç–∞–∫ –∑–∞–¥–∞—á–∞ –±—ã—Å—Ç—Ä–µ–µ —Å—Ç–∞—Ä—Ç—É–µ—Ç –∏ –Ω–µ –≤–∏—Å–∏—Ç –Ω–∞ polling.
VOCAL_CLIP_MAX_AUDIO_S = int(os.environ.get("VOCAL_CLIP_MAX_AUDIO_S", "65") or 65)
VOCAL_CLIP_MIN_AUDIO_S = int(os.environ.get("VOCAL_CLIP_MIN_AUDIO_S", "12") or 12)
VOCAL_CLIP_KLING_MAX_WAIT_S = int(os.environ.get("VOCAL_CLIP_KLING_MAX_WAIT_S", "1800") or 1800)
TEXT_VIDEO_UNIT_COST_USD = _env_float("TEXT_VIDEO_UNIT_COST_USD", KLING_UNIT_COST_USD)
TEXT_VIDEO_DEFAULT_ENGINE = os.environ.get("TEXT_VIDEO_DEFAULT_ENGINE", "kling").strip().lower() or "kling"
TEXT_VIDEO_ALLOW_RUNWAY = os.environ.get("TEXT_VIDEO_ALLOW_RUNWAY", "1").strip().lower() not in ("0", "false", "no", "off")

_photo_clip_background_jobs: set[str] = set()
_vocal_clip_background_jobs: set[str] = set()

# AI selfie / Nano Banana style multi-image editor routed through CometAPI.
# Expected path is OpenAI-compatible image edit endpoint on Comet.
# Comet Nano Banana / Gemini image edit.
# Production primary route is Gemini-style generateContent through CometAPI.
# Comet docs show Nano Banana/Gemini image via /v1beta/models/{model}:generateContent with inline image data.
COMET_IMAGE_EDIT_MODEL = os.environ.get("COMET_IMAGE_EDIT_MODEL", "gemini-2.5-flash-image").strip() or "gemini-2.5-flash-image"
COMET_IMAGE_EDIT_FALLBACK_MODELS = [m.strip() for m in os.environ.get("COMET_IMAGE_EDIT_FALLBACK_MODELS", "gemini-2.5-flash-image,gemini-2.5-flash-image-preview,gemini-3.1-flash-image,gemini-3-pro-image,gemini-2-5-flash-image").split(",") if m.strip()]
if COMET_IMAGE_EDIT_MODEL not in COMET_IMAGE_EDIT_FALLBACK_MODELS:
    COMET_IMAGE_EDIT_FALLBACK_MODELS.insert(0, COMET_IMAGE_EDIT_MODEL)
COMET_IMAGE_EDIT_PATH = os.environ.get("COMET_IMAGE_EDIT_PATH", "/v1beta/models/{model}:generateContent").strip() or "/v1beta/models/{model}:generateContent"
COMET_IMAGE_EDIT_STATUS_PATH = os.environ.get("COMET_IMAGE_EDIT_STATUS_PATH", "").strip()
COMET_IMAGE_EDIT_TIMEOUT_S = float(os.environ.get("COMET_IMAGE_EDIT_TIMEOUT_S", "600") or 600)
COMET_IMAGE_EDIT_OPENAI_FALLBACK = os.environ.get("COMET_IMAGE_EDIT_OPENAI_FALLBACK", "0").strip().lower() in ("1", "true", "yes", "on")
AI_SELFIE_UNIT_COST_USD = _pricing_cost("AI_SELFIE_UNIT_COST_USD", 0.15)
AI_SELFIE_DEFAULT_ASPECT = os.environ.get("AI_SELFIE_DEFAULT_ASPECT", "4:5").strip() or "4:5"
AI_SELFIE_IMAGE_SIZE = os.environ.get("AI_SELFIE_IMAGE_SIZE", "1K").strip() or "1K"
AI_SELFIE_MAX_SIDE = int(os.environ.get("AI_SELFIE_MAX_SIDE", "1024") or 1024)
AI_SELFIE_SEND_AS_DOCUMENT = os.environ.get("AI_SELFIE_SEND_AS_DOCUMENT", "1").strip().lower() not in ("0", "false", "no", "off")
AI_SELFIE_PROVIDER = os.environ.get("AI_SELFIE_PROVIDER", "comet").strip().lower() or "comet"
AI_SELFIE_ALLOW_PUBLIC_FIGURES = os.environ.get("AI_SELFIE_ALLOW_PUBLIC_FIGURES", "1").strip().lower() not in ("0", "false", "no", "off")
AI_SELFIE_FAST_MODE = os.environ.get("AI_SELFIE_FAST_MODE", "1").strip().lower() not in ("0", "false", "no", "off")
AI_SELFIE_RETRY_ON_TIMEOUT = os.environ.get("AI_SELFIE_RETRY_ON_TIMEOUT", "1").strip().lower() not in ("0", "false", "no", "off")

# –¢–∞–π–º–∞—É—Ç—ã
LUMA_MAX_WAIT_S     = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)
LUMA_TEMP_DISABLED = True  # –≤—Ä–µ–º–µ–Ω–Ω–∞—è –∑–∞–≥–ª—É—à–∫–∞: —Å–∫—Ä—ã–≤–∞–µ–º Luma –∏–∑ –º–µ–Ω—é –∏ –æ—Ç–∫–ª—é—á–∞–µ–º –∏—Å–ø–æ–ª—å–∑–æ–≤–∞–Ω–∏–µ
RUNWAY_MAX_WAIT_S   = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "1200").strip() or 1200)
VIDEO_POLL_DELAY_S  = float((os.environ.get("VIDEO_POLL_DELAY_S") or "6.0").strip() or 6.0)
VIDEO_RESULT_SEND_AS_DOCUMENT = os.getenv("VIDEO_RESULT_SEND_AS_DOCUMENT", "1") == "1"
VIDEO_SEND_WRITE_TIMEOUT_S = max(120, int(os.environ.get("VIDEO_SEND_WRITE_TIMEOUT_S", "180") or 180))
VOCAL_CLIP_ARTIFACT_DIR = os.path.abspath(os.environ.get("VOCAL_CLIP_ARTIFACT_DIR", "/data/vocal_clip_artifacts"))
TELEGRAM_RESULT_MAX_MB = int(os.environ.get("TELEGRAM_RESULT_MAX_MB", "48") or 48)
TELEGRAM_VIDEO_COMPRESS_ON_FAIL = os.getenv("TELEGRAM_VIDEO_COMPRESS_ON_FAIL", "1") == "1"
VIDEO_RESULT_DEDUPE_TTL_S = int((os.getenv("VIDEO_RESULT_DEDUPE_TTL_S") or "900").strip() or 900)
SORA_AUTO_FALLBACK_KLING = os.getenv("SORA_AUTO_FALLBACK_KLING", "1") == "1"
_SENT_VIDEO_KEYS: dict[str, float] = {}

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ UTILS ---------
_LUMA_ACTIVE_BASE = None  # –∫—ç—à –ø–æ—Å–ª–µ–¥–Ω–µ–≥–æ –∂–∏–≤–æ–≥–æ –±–∞–∑–æ–≤–æ–≥–æ URL

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

# Presentation/Catalog Studio v86
PRESENTATION_DATA_DIR = os.environ.get(
    "PRESENTATION_DATA_DIR",
    os.path.join(os.path.dirname(DB_PATH) or ".", "presentation_studio"),
).strip() or "/tmp/presentation_studio"
PRESENTATION_MAX_UPLOADS = int(os.environ.get("PRESENTATION_MAX_UPLOADS", "60") or 60)
PRESENTATION_MAX_GENERATED_IMAGES = int(os.environ.get("PRESENTATION_MAX_GENERATED_IMAGES", "10") or 10)
PRESENTATION_IMAGE_SIZE = os.environ.get("PRESENTATION_IMAGE_SIZE", "1536x1024").strip() or "1536x1024"
PRESENTATION_RENDER_COST_USD = _pricing_cost("PRESENTATION_RENDER_COST_USD", 0.20)
PRESENTATION_IMAGE_ENGINE_AUTO = os.environ.get("PRESENTATION_IMAGE_ENGINE_AUTO", "1").strip().lower() not in ("0", "false", "no", "off")
# Generated packaging/labels are kept blank; exact approved copy is rendered by PPTX/PDF code.
PRESENTATION_TEXT_SAFE_VISUALS = os.environ.get("PRESENTATION_TEXT_SAFE_VISUALS", "1").strip().lower() not in ("0", "false", "no", "off")
PRESENTATION_FORCE_OPENAI_FOR_TEXT = os.environ.get("PRESENTATION_FORCE_OPENAI_FOR_TEXT", "1").strip().lower() not in ("0", "false", "no", "off")


PLAN_PRICE_TABLE = {
    # v83: –ø–æ–¥–ø–∏—Å–∫–∞ + –∫—Ä–µ–¥–∏—Ç—ã –¥–ª—è —Ç—è–∂—ë–ª—ã—Ö –≥–µ–Ω–µ—Ä–∞—Ü–∏–π.
    "start":    {"month": int(os.environ.get("PRICE_START_RUB", "599")),  "quarter": int(os.environ.get("PRICE_START_QUARTER_RUB", "1590")),  "year": int(os.environ.get("PRICE_START_YEAR_RUB", "5990"))},
    "pro":      {"month": int(os.environ.get("PRICE_PRO_RUB", "1990")),    "quarter": int(os.environ.get("PRICE_PRO_QUARTER_RUB", "5490")),    "year": int(os.environ.get("PRICE_PRO_YEAR_RUB", "19900"))},
    "ultimate": {"month": int(os.environ.get("PRICE_ULT_RUB", "4990")),    "quarter": int(os.environ.get("PRICE_ULT_QUARTER_RUB", "13990")),   "year": int(os.environ.get("PRICE_ULT_YEAR_RUB", "49900"))},
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

# ‚îÄ‚îÄ –ë–µ–∑–ª–∏–º–∏—Ç ‚îÄ‚îÄ
def _parse_ids_csv(s: str) -> set[int]:
    return set(int(x) for x in s.split(",") if x.strip().isdigit())

UNLIM_USER_IDS   = _parse_ids_csv(os.environ.get("UNLIM_USER_IDS",""))
UNLIM_USERNAMES  = set(s.strip().lstrip("@").lower() for s in os.environ.get("UNLIM_USERNAMES","").split(",") if s.strip())
# –í—Å—Ç—Ä–æ–µ–Ω–Ω—ã–µ —Å–ª—É–∂–µ–±–Ω—ã–µ –±–µ–∑–ª–∏–º–∏—Ç–Ω—ã–µ –∞–∫–∫–∞—É–Ω—Ç—ã. –î–æ–ø–æ–ª–Ω–∏—Ç–µ–ª—å–Ω–æ –º–æ–∂–Ω–æ –∑–∞–¥–∞—Ç—å ENV UNLIM_USERNAMES.
UNLIM_USERNAMES.update({
    "gpt5pro_support",
    "neyrobotsupport",
    "granova_elena",
})

# –ü—Ä–æ–º–æ-–¥–æ—Å—Ç—É–ø: –±–µ–∑–ª–∏–º–∏—Ç–Ω—ã–π GPT + N –±–µ—Å–ø–ª–∞—Ç–Ω—ã—Ö –∑–∞–ø—É—Å–∫–æ–≤ –∫–∞–∂–¥–æ–π –ø–ª–∞—Ç–Ω–æ–π —Ñ—É–Ω–∫—Ü–∏–∏ –≤ –¥–µ–Ω—å.
PROMO_DAILY5_USERNAMES = set(
    s.strip().lstrip("@").lower()
    for s in os.environ.get("PROMO_DAILY5_USERNAMES", "MrMariton").split(",")
    if s.strip()
)
PROMO_UNLIM_GPT_USERNAMES = set(
    s.strip().lstrip("@").lower()
    for s in os.environ.get("PROMO_UNLIM_GPT_USERNAMES", "MrMariton").split(",")
    if s.strip()
) | PROMO_DAILY5_USERNAMES
PROMO_DAILY5_PER_FUNCTION_LIMIT = int(os.environ.get("PROMO_DAILY5_PER_FUNCTION_LIMIT", "5") or "5")

OWNER_ID           = int(os.environ.get("OWNER_ID","0") or "0")
FORCE_OWNER_UNLIM  = os.environ.get("FORCE_OWNER_UNLIM","1").strip().lower() not in ("0","false","no")

def _norm_username(username: str | None) -> str:
    return (username or "").strip().lstrip("@").lower()

def is_unlimited(user_id: int, username: str | None = None) -> bool:
    if FORCE_OWNER_UNLIM and OWNER_ID and user_id == OWNER_ID:
        return True
    if user_id in UNLIM_USER_IDS:
        return True
    if _norm_username(username) in UNLIM_USERNAMES:
        return True
    return False

def is_promo_unlim_gpt(user_id: int, username: str | None = None) -> bool:
    if is_unlimited(user_id, username):
        return True
    return _norm_username(username) in PROMO_UNLIM_GPT_USERNAMES

def is_promo_daily5_user(user_id: int, username: str | None = None) -> bool:
    if is_unlimited(user_id, username):
        return False
    return _norm_username(username) in PROMO_DAILY5_USERNAMES

# ‚îÄ‚îÄ Premium page URL ‚îÄ‚îÄ
def _make_tariff_url(src: str = "subscribe") -> str:
    base = (WEBAPP_URL or f"{PUBLIC_URL.rstrip('/')}/premium.html").strip()
    # –ù–µ–∑–∞–≤–∏—Å–∏–º—ã–π cache-buster –≥–∞—Ä–∞–Ω—Ç–∏—Ä—É–µ—Ç –∑–∞–≥—Ä—É–∑–∫—É –∞–∫—Ç—É–∞–ª—å–Ω–æ–≥–æ premium.html –ø–æ—Å–ª–µ –¥–µ–ø–ª–æ—è,
    # –¥–∞–∂–µ –µ—Å–ª–∏ –≤ Render WEBAPP_URL –æ—Å—Ç–∞–ª—Å—è —Å–æ —Å—Ç–∞—Ä—ã–º –ø–∞—Ä–∞–º–µ—Ç—Ä–æ–º v=.
    sep = "&" if "?" in base else "?"
    base = f"{base}{sep}build=v94"
    if src:
        sep = "&" if "?" in base else "?"
        base = f"{base}{sep}src={src}"
    if BOT_USERNAME:
        sep = "&" if "?" in base else "?"
        base = f"{base}{sep}bot={BOT_USERNAME}"
    # v93: inline/menu Mini Apps cannot use sendData for WebAppData.
    # Pass a signed server-side checkout bridge endpoint instead.
    checkout_url = f"{PUBLIC_URL.rstrip('/')}/webapp/checkout"
    sep = "&" if "?" in base else "?"
    base = f"{base}{sep}checkout={urllib.parse.quote(checkout_url, safe='')}"
    return base
TARIFF_URL = _make_tariff_url("subscribe")


# ‚îÄ‚îÄ Telegram profile / pre-start description ‚îÄ‚îÄ
AUTO_SET_BOT_PROFILE = os.environ.get("AUTO_SET_BOT_PROFILE", "1").strip().lower() not in ("0", "false", "no", "off")
AUTO_SET_BOT_MENU = os.environ.get("AUTO_SET_BOT_MENU", "1").strip().lower() not in ("0", "false", "no", "off")
BOT_MENU_TEXT = os.environ.get("BOT_MENU_TEXT", "–ú–µ–Ω—é –±–æ—Ç–æ–≤").strip()[:64] or "–ú–µ–Ω—é –±–æ—Ç–æ–≤"
BOT_PUBLIC_NAME = os.environ.get("BOT_PUBLIC_NAME", "Neyro-Bot GPT 5 Studio").strip()[:64]
BOT_SHORT_DESCRIPTION = os.environ.get(
    "BOT_SHORT_DESCRIPTION",
    'GPT-5, Sora 2, Kling, Runway, Midjourney, Suno: —Ç–µ–∫—Å—Ç, —Ñ–æ—Ç–æ, –≤–∏–¥–µ–æ, –º—É–∑—ã–∫–∞, –∞–≤–∞—Ç–∞—Ä, Reels/Shorts –≤ –æ–¥–Ω–æ–º AI-–±–æ—Ç–µ.'
).strip()[:120]
BOT_DESCRIPTION = os.environ.get(
    "BOT_DESCRIPTION",
    'Neyro-Bot GPT 5 Studio ‚Äî –º—É–ª—å—Ç–∏–º–æ–¥–µ–ª—å–Ω–∞—è AI-—Å—Ç—É–¥–∏—è –≤ Telegram. GPT-—á–∞—Ç, PDF/DOCX, —Ñ–æ—Ç–æ –∏ —Å–∫—Ä–∏–Ω—à–æ—Ç—ã, –∞–Ω–∞–ª–∏–∑ –¥–æ–∫—É–º–µ–Ω—Ç–æ–≤, –æ–∑–≤—É—á–∫–∞ –∏ —Ä–∞—Å–ø–æ–∑–Ω–∞–≤–∞–Ω–∏–µ —Ä–µ—á–∏, –≥–µ–Ω–µ—Ä–∞—Ü–∏—è –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–π, –ª–æ–≥–æ—Ç–∏–ø—ã, Midjourney-—Å—Ç–∏–ª—å, —É–¥–∞–ª–µ–Ω–∏–µ/–∑–∞–º–µ–Ω–∞ —Ñ–æ–Ω–∞, –∑–∞–º–µ–Ω–∞ –ª–∏—Ü–∞, –æ–∂–∏–≤–ª–µ–Ω–∏–µ —Ñ–æ—Ç–æ, –≥–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä, –∫–ª–∏–ø —Å –≤–æ–∫–∞–ª–æ–º –¥–ª—è 1 —á–µ–ª–æ–≤–µ–∫–∞, –≤–∏–¥–µ–æ –ø–æ —Ç–µ–∫—Å—Ç—É/–≥–æ–ª–æ—Å—É, Reels/Shorts, –º–∏–Ω–∏-—Ñ–∏–ª—å–º—ã, Sora 2, Kling, Runway, Suno-–º—É–∑—ã–∫–∞. –í—ã–±–µ—Ä–∏—Ç–µ —Ä–µ–∂–∏–º –∏–ª–∏ –ø—Ä–æ—Å—Ç–æ –Ω–∞–ø–∏—à–∏—Ç–µ –∑–∞–¥–∞—á—É.'
).strip()[:512]

# ‚îÄ‚îÄ OpenAI clients ‚îÄ‚îÄ
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

# Tavily (–æ–ø—Ü–∏–æ–Ω–∞–ª—å–Ω–æ)
try:
    if TAVILY_API_KEY:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
    else:
        tavily = None
except Exception:
    tavily = None

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ LIVE INTERNET / CURRENT DATA ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
# –≠—Ç–æ—Ç —Å–ª–æ–π –Ω—É–∂–µ–Ω, —á—Ç–æ–±—ã –±–æ—Ç –Ω–µ –æ—Ç–≤–µ—á–∞–ª ¬´–º–æ–∏ –¥–∞–Ω–Ω—ã–µ —É—Å—Ç–∞—Ä–µ–ª–∏¬ª –Ω–∞ –≤–æ–ø—Ä–æ—Å—ã –ø—Ä–æ –∫—É—Ä—Å—ã,
# –Ω–æ–≤–æ—Å—Ç–∏, –∑–∞–∫–æ–Ω—ã, —Ä–µ–ª–∏–∑—ã, –ø–æ–≥–æ–¥—É –∏ –ø—Ä–æ—á—É—é –∞–∫—Ç—É–∞–ª—å–Ω—É—é –∏–Ω—Ñ–æ—Ä–º–∞—Ü–∏—é.
LIVE_SEARCH_ENABLED = os.environ.get("LIVE_SEARCH_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
CRYPTO_RATE_ENABLED = os.environ.get("CRYPTO_RATE_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
LIVE_SEARCH_TIMEOUT_S = _env_float("LIVE_SEARCH_TIMEOUT_S", 18.0)
BINANCE_MARKET_BASE = os.environ.get("BINANCE_MARKET_BASE", "https://api.binance.com").strip().rstrip("/")
OPENAI_WEB_SEARCH_MODEL = os.environ.get("OPENAI_WEB_SEARCH_MODEL", "gpt-5.6").strip() or "gpt-5.6"

# v84: –µ–¥–∏–Ω–∞—è –¥–∞—Ç–∞/—á–∞—Å–æ–≤–æ–π –ø–æ—è—Å –¥–ª—è GPT –∏ live-–ø–æ–∏—Å–∫–∞.
# –ë–µ–∑ —ç—Ç–æ–≥–æ –æ—Ç–Ω–æ—Å–∏—Ç–µ–ª—å–Ω–æ–µ —Å–ª–æ–≤–æ ¬´—Å–µ–≥–æ–¥–Ω—è¬ª –º–æ–≥–ª–æ –±—ã—Ç—å —Å–æ–ø–æ—Å—Ç–∞–≤–ª–µ–Ω–æ —Å–æ —Å—Ç–∞—Ä–æ–π –Ω–æ–≤–æ—Å—Ç—å—é –∏–∑ –≤—ã–¥–∞—á–∏.
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
LIVE_SEARCH_DATE_GUARD = os.environ.get("LIVE_SEARCH_DATE_GUARD", "1").strip().lower() not in ("0", "false", "no", "off")
LIVE_SEARCH_TODAY_TIME_RANGE = os.environ.get("LIVE_SEARCH_TODAY_TIME_RANGE", "day").strip() or "day"
LIVE_SEARCH_RECENT_TIME_RANGE = os.environ.get("LIVE_SEARCH_RECENT_TIME_RANGE", "week").strip() or "week"
LIVE_SEARCH_NEWS_MAX_RESULTS = int(os.environ.get("LIVE_SEARCH_NEWS_MAX_RESULTS", "8") or 8)

LIVE_WORDS_RE = re.compile(
    r"(—Å–µ–≥–æ–¥–Ω—è|—Å–µ–π—á–∞—Å|–∞–∫—Ç—É–∞–ª—å–Ω|–ø–æ—Å–ª–µ–¥–Ω|–Ω–æ–≤–æ—Å—Ç|–∫—É—Ä—Å|–∫–æ—Ç–∏—Ä–æ–≤|—Ü–µ–Ω–∞|—Å—Ç–æ–∏–º–æ—Å—Ç—å|"
    r"—Å–∫–æ–ª—å–∫–æ —Å—Ç–æ–∏—Ç|–ø–æ—á[–µ—ë]–º|–ø–æ–≥–æ–¥–∞|—Ä–∞—Å–ø–∏—Å–∞–Ω–∏–µ|–∫–æ–≥–¥–∞ –≤—ã–π–¥–µ—Ç|–≤—ã—à–µ–ª –ª–∏|–∑–∞–∫–æ–Ω|—à—Ç—Ä–∞—Ñ|"
    r"–Ω–∞–ª–æ–≥|–ø–µ–Ω—Å–∏|–±–∏—Ä–∂|–∞–∫—Ü–∏|–¥–æ–ª–ª–∞—Ä|–µ–≤—Ä–æ|–±–∞—Ç|—Ä—É–±–ª|usdt|btc|bitcoin|–±–∏—Ç–∫–æ–∏–Ω|"
    r"–ø—Ä–µ–∑–∏–¥–µ–Ω—Ç|–≥—É–±–µ—Ä–Ω–∞—Ç–æ—Ä|ceo|–¥–∏—Ä–µ–∫—Ç–æ—Ä|—Ä–µ–ª–∏–∑|—Ç—Ä–µ–π–ª–µ—Ä|–æ–±–Ω–æ–≤–ª–µ–Ω–∏|–ø—Ä–æ–≤–µ—Ä[—å–∏]|–Ω–∞–π–¥–∏)",
    re.IGNORECASE,
)

CRYPTO_RE = re.compile(
    r"(btc|bitcoin|–±–∏—Ç–∫–æ–∏–Ω|–±–∏—Ç–∫–æ–∏–Ω–∞|–±–∏—Ç–æ–∫|eth|ethereum|—ç—Ñ–∏—Ä|usdt|solana|sol|—Å–æ–ª–∞–Ω–∞|bnb|toncoin|ton)",
    re.IGNORECASE,
)

RATE_RE = re.compile(
    r"(–∫—É—Ä—Å|—Ü–µ–Ω–∞|—Å—Ç–æ–∏–º–æ—Å—Ç—å|—Å–∫–æ–ª—å–∫–æ —Å—Ç–æ–∏—Ç|–ø–æ—á[–µ—ë]–º|—Å–µ–≥–æ–¥–Ω—è|—Å–µ–π—á–∞—Å|–∫–æ—Ç–∏—Ä–æ–≤|—Ç–æ—Ä–≥—É–µ—Ç—Å—è|rate|price)",
    re.IGNORECASE,
)

# –ó–∞–ø—Ä–æ—Å—ã –ø—Ä–æ–≥–Ω–æ–∑–∞ –ù–ï –¥–æ–ª–∂–Ω—ã –ø–µ—Ä–µ—Ö–≤–∞—Ç—ã–≤–∞—Ç—å—Å—è –±—ã—Å—Ç—Ä—ã–º –æ–±—Ä–∞–±–æ—Ç—á–∏–∫–æ–º –∫—É—Ä—Å–∞.
# –ò–Ω–∞—á–µ –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å —Å–ø—Ä–∞—à–∏–≤–∞–µ—Ç ¬´–ø—Ä–æ–≥–Ω–æ–∑ —Ä–æ—Å—Ç–∞/–ø–∞–¥–µ–Ω–∏—è¬ª, –∞ –±–æ—Ç —Å–Ω–æ–≤–∞ –æ—Ç–≤–µ—á–∞–µ—Ç —Ç–æ–ª—å–∫–æ —Ç–µ–∫—É—â–∏–º –∫—É—Ä—Å–æ–º.
FORECAST_RE = re.compile(
    r"(–ø—Ä–æ–≥–Ω–æ–∑|–ø–µ—Ä—Å–ø–µ–∫—Ç–∏–≤|–æ–∂–∏–¥–∞–Ω|—Ä–æ—Å—Ç|–ø–∞–¥–µ–Ω|–≤—ã—Ä–∞—Å—Ç|–≤—ã—Ä–∞—Å—Ç–∏|—É–ø–∞–¥|—É–ø–∞—Å—Ç—å|–±—É–¥–µ—Ç|–º–µ—Å—è—Ü|–Ω–µ–¥–µ–ª|"
    r"target|forecast|prediction|bull|bear|long|short)",
    re.IGNORECASE,
)

_RELATIVE_DATE_RE = re.compile(
    r"(—Å–µ–≥–æ–¥–Ω—è|—Å–µ–π—á–∞—Å|–Ω–∞ —Ç–µ–∫—É—â–∏–π –º–æ–º–µ–Ω—Ç|–∫ —ç—Ç–æ–º—É —á–∞—Å—É|–∑–∞ —Å–µ–≥–æ–¥–Ω—è|—Å —É—Ç—Ä–∞|—ç—Ç–æ–π –Ω–æ—á—å—é|"
    r"today|now|current(?:ly)?|this morning|tonight)",
    re.IGNORECASE,
)
_NEWS_INTENT_RE = re.compile(
    r"(–Ω–æ–≤–æ—Å—Ç|–∞—Ç–∞–∫|–¥—Ä–æ–Ω|–±–µ—Å–ø–∏–ª–æ—Ç|–æ–±—Å—Ç—Ä–µ–ª|–≤–∑—Ä—ã–≤|–ø—Ä–æ–∏—Å—à–µ—Å—Ç–≤|–ø–æ–∂–∞—Ä|–∞–≤–∞—Ä–∏|–≤–æ–π–Ω|–∫–æ–Ω—Ñ–ª–∏–∫—Ç|"
    r"–ø–æ–ª–∏—Ç–∏–∫|—Å–∞–Ω–∫—Ü–∏|–≤—ã–±–æ—Ä|–∞—ç—Ä–æ–ø–æ—Ä—Ç|–ø–≤–æ|–º—á—Å|—Ç–µ—Ä–∞–∫—Ç|news|attack|drone|breaking)",
    re.IGNORECASE,
)
_RU_MONTHS = {
    1: "—è–Ω–≤–∞—Ä—è", 2: "—Ñ–µ–≤—Ä–∞–ª—è", 3: "–º–∞—Ä—Ç–∞", 4: "–∞–ø—Ä–µ–ª—è", 5: "–º–∞—è", 6: "–∏—é–Ω—è",
    7: "–∏—é–ª—è", 8: "–∞–≤–≥—É—Å—Ç–∞", 9: "—Å–µ–Ω—Ç—è–±—Ä—è", 10: "–æ–∫—Ç—è–±—Ä—è", 11: "–Ω–æ—è–±—Ä—è", 12: "–¥–µ–∫–∞–±—Ä—è",
}
_RU_MONTH_TO_NUM = {v: k for k, v in _RU_MONTHS.items()}

def _app_now() -> datetime:
    try:
        return datetime.now(ZoneInfo(APP_TIMEZONE))
    except Exception:
        # –ë–µ–∑–æ–ø–∞—Å–Ω—ã–π fallback –¥–ª—è –æ—Å–Ω–æ–≤–Ω–æ–≥–æ —Ä–æ—Å—Å–∏–π—Å–∫–æ–≥–æ —á–∞—Å–æ–≤–æ–≥–æ –ø–æ—è—Å–∞.
        return datetime.now(timezone(timedelta(hours=3)))

def _current_date_meta() -> dict:
    now = _app_now()
    return {
        "now": now,
        "iso": now.strftime("%Y-%m-%d"),
        "ru": f"{now.day} {_RU_MONTHS[now.month]} {now.year} –≥–æ–¥–∞",
        "time": now.strftime("%H:%M"),
        "timezone": APP_TIMEZONE,
    }

def _current_date_system_text() -> str:
    d = _current_date_meta()
    return (
        f"–¢–µ–∫—É—â–∞—è –¥–∞—Ç–∞ –∏ –≤—Ä–µ–º—è —Å–µ—Ä–≤–∏—Å–∞: {d['ru']}, {d['time']} ({d['timezone']}; ISO {d['iso']}). "
        "–°–ª–æ–≤–∞ ¬´—Å–µ–≥–æ–¥–Ω—è¬ª, ¬´—Å–µ–π—á–∞—Å¬ª, ¬´—ç—Ç–æ–π –Ω–æ—á—å—é¬ª –∏ –¥—Ä—É–≥–∏–µ –æ—Ç–Ω–æ—Å–∏—Ç–µ–ª—å–Ω—ã–µ –¥–∞—Ç—ã –≤—Å–µ–≥–¥–∞ —Ç—Ä–∞–∫—Ç—É–π –æ—Ç–Ω–æ—Å–∏—Ç–µ–ª—å–Ω–æ —ç—Ç–æ–π –¥–∞—Ç—ã. "
        "–ù–µ –Ω–∞–∑—ã–≤–∞–π —Å—Ç–∞—Ä—É—é –¥–∞—Ç—É —Å–µ–≥–æ–¥–Ω—è—à–Ω–µ–π."
    )

def _is_news_intent(text: str) -> bool:
    return bool(text and _NEWS_INTENT_RE.search(text))

def _live_search_query_with_date(text: str) -> str:
    q = (text or "").strip()
    if not q:
        return q
    d = _current_date_meta()
    if _RELATIVE_DATE_RE.search(q):
        return (
            f"{q}. –¢–æ—á–Ω–∞—è —Ç–µ–∫—É—â–∞—è –¥–∞—Ç–∞: {d['iso']} ({d['ru']}), —á–∞—Å–æ–≤–æ–π –ø–æ—è—Å {d['timezone']}. "
            f"–ò—Å–∫–∞—Ç—å —Å–æ–±—ã—Ç–∏—è –∏–º–µ–Ω–Ω–æ –∑–∞ {d['iso']}; –±–æ–ª–µ–µ —Å—Ç–∞—Ä—ã–µ –º–∞—Ç–µ—Ä–∏–∞–ª—ã –Ω–µ —Å—á–∏—Ç–∞—Ç—å —Å–æ–±—ã—Ç–∏—è–º–∏ –∑–∞ —Å–µ–≥–æ–¥–Ω—è."
        )
    return q

def _claimed_today_date(text: str) -> tuple[int, int, int] | None:
    # –õ–æ–≤–∏–º —Ñ–æ—Ä–º—É–ª–∏—Ä–æ–≤–∫–∏ –≤–∏–¥–∞ ¬´–°–µ–≥–æ–¥–Ω—è, 18 –∏—é–Ω—è 2026 –≥–æ–¥–∞¬ª.
    m = re.search(
        r"—Å–µ–≥–æ–¥–Ω—è\s*[,‚Äî:-]?\s*(\d{1,2})\s+"
        r"(—è–Ω–≤–∞—Ä—è|—Ñ–µ–≤—Ä–∞–ª—è|–º–∞—Ä—Ç–∞|–∞–ø—Ä–µ–ª—è|–º–∞—è|–∏—é–Ω—è|–∏—é–ª—è|–∞–≤–≥—É—Å—Ç–∞|—Å–µ–Ω—Ç—è–±—Ä—è|–æ–∫—Ç—è–±—Ä—è|–Ω–æ—è–±—Ä—è|–¥–µ–∫–∞–±—Ä—è)"
        r"(?:\s+(\d{4}))?",
        text or "",
        re.IGNORECASE,
    )
    if not m:
        return None
    d = _current_date_meta()["now"]
    return int(m.group(3) or d.year), _RU_MONTH_TO_NUM[m.group(2).lower()], int(m.group(1))

def _has_wrong_today_date(text: str) -> bool:
    claimed = _claimed_today_date(text)
    if not claimed:
        return False
    now = _current_date_meta()["now"]
    return claimed != (now.year, now.month, now.day)

GENERAL_CAPABILITY_RE = re.compile(
    r"(—á—Ç–æ\s+—Ç—ã\s+—É–º–µ–µ—à—å|—á—Ç–æ\s+—É–º–µ–µ—à—å|–∫–∞–∫–∏–µ\s+—É\s+—Ç–µ–±—è\s+–≤–æ–∑–º–æ–∂–Ω–æ—Å—Ç–∏|"
    r"—á—Ç–æ\s+—É–º–µ–µ—Ç\s+–±–æ—Ç|–∫–∞–∫\s+–ø–æ–ª—å–∑–æ–≤–∞—Ç—å—Å—è|–ø–æ–∫–∞–∂–∏\s+—Ñ—É–Ω–∫—Ü–∏–∏|—Å–ø–∏—Å–æ–∫\s+—Ñ—É–Ω–∫—Ü–∏–π|"
    r"—á–µ–º\s+—Ç—ã\s+–º–æ–∂–µ—à—å\s+–ø–æ–º–æ—á—å|help|features|capabilities)",
    re.IGNORECASE,
)


def _crypto_symbol_from_text(text: str) -> tuple[str, str] | None:
    t = (text or "").lower()
    if any(x in t for x in ("–±–∏—Ç–∫–æ–∏–Ω", "–±–∏—Ç–∫–æ–∏–Ω–∞", "–±–∏—Ç–æ–∫", "btc", "bitcoin")):
        return "BTCUSDT", "–±–∏—Ç–∫–æ–∏–Ω"
    if any(x in t for x in ("—ç—Ñ–∏—Ä", "ethereum", "eth")):
        return "ETHUSDT", "Ethereum"
    if "usdt" in t or "tether" in t:
        return "USDCUSDT", "USDT"
    if any(x in t for x in ("solana", "—Å–æ–ª–∞–Ω–∞", "sol")):
        return "SOLUSDT", "Solana"
    if "bnb" in t:
        return "BNBUSDT", "BNB"
    if any(x in t for x in ("toncoin", "—Ç–æ–Ω", " ton", "ton ")):
        return "TONUSDT", "TON"
    return None


def _is_crypto_rate_query(text: str) -> bool:
    return bool(text and CRYPTO_RE.search(text) and RATE_RE.search(text))


def _is_crypto_forecast_query(text: str) -> bool:
    """–ü—Ä–æ–≥–Ω–æ–∑/—Å—Ü–µ–Ω–∞—Ä–∏–π –ø–æ –∫—Ä–∏–ø—Ç–µ: –Ω–µ –æ–±—Ä–∞–±–∞—Ç—ã–≤–∞–µ–º –∫–∞–∫ –ø—Ä–æ—Å—Ç–æ–π –∑–∞–ø—Ä–æ—Å –∫—É—Ä—Å–∞."""
    return bool(text and FORECAST_RE.search(text) and (CRYPTO_RE.search(text) or RATE_RE.search(text) or "–∞–∫—Ç–∏–≤" in text.lower()))


def _is_general_capability_query(text: str) -> bool:
    return bool(text and GENERAL_CAPABILITY_RE.search(text))


def _last_crypto_pair_from_memory(user_id: int | None, chat_id: int | None) -> tuple[str, str] | None:
    """–î–æ—Å—Ç–∞—ë–º –ø–æ—Å–ª–µ–¥–Ω–∏–π –æ–±—Å—É–∂–¥–∞–≤—à–∏–π—Å—è –∫—Ä–∏–ø—Ç–æ–∞–∫—Ç–∏–≤ –∏–∑ –ø–∞–º—è—Ç–∏, –Ω–æ –Ω–µ —Å–º–µ—à–∏–≤–∞–µ–º –≤–µ—Å—å –∫–æ–Ω—Ç–µ–∫—Å—Ç —Å –Ω–æ–≤—ã–º –∑–∞–ø—Ä–æ—Å–æ–º."""
    ctx = _chat_memory_context_text(user_id, chat_id, limit=10)
    return _crypto_symbol_from_text(ctx) if ctx else None


def _crypto_contextual_text(user_id: int | None, chat_id: int | None, original_text: str) -> tuple[str, tuple[str, str] | None]:
    """
    –î–æ–±–∞–≤–ª—è–µ—Ç –∫—Ä–∏–ø—Ç–æ-–∫–æ–Ω—Ç–µ–∫—Å—Ç —Ç–æ–ª—å–∫–æ –∫–æ–≥–¥–∞ —ç—Ç–æ –¥–µ–π—Å—Ç–≤–∏—Ç–µ–ª—å–Ω–æ follow-up –ø—Ä–æ —Ä—ã–Ω–æ–∫/–ø—Ä–æ–≥–Ω–æ–∑/–∫—É—Ä—Å.
    –ù–µ –ø–æ–¥–º–µ—à–∏–≤–∞–µ—Ç –∏—Å—Ç–æ—Ä–∏—é –≤ –≤–æ–ø—Ä–æ—Å—ã –≤—Ä–æ–¥–µ ¬´—á—Ç–æ —Ç—ã —É–º–µ–µ—à—å¬ª, —á—Ç–æ–±—ã –±–æ—Ç –Ω–µ –∑–∞–ª–∏–ø–∞–ª –Ω–∞ BTC.
    """
    t = (original_text or "").strip()
    if not t:
        return t, None
    direct = _crypto_symbol_from_text(t)
    if direct:
        return t, direct
    if _is_general_capability_query(t):
        return t, None
    looks_market_followup = bool(FORECAST_RE.search(t) or RATE_RE.search(t) or re.search(r"(–∞–∫—Ç–∏–≤|—Ä—ã–Ω–æ–∫|–∫—Ä–∏–ø—Ç|–º–æ–Ω–µ—Ç|–∫–æ–∏–Ω|—Ä–æ—Å—Ç|–ø–∞–¥–µ–Ω)", t, re.I))
    if not looks_market_followup:
        return t, None
    pair = _last_crypto_pair_from_memory(user_id, chat_id)
    if not pair:
        return t, None
    symbol, human = pair
    return f"{t}\n\n–ö–æ–Ω—Ç–µ–∫—Å—Ç –ø—Ä–µ–¥—ã–¥—É—â–µ–≥–æ –¥–∏–∞–ª–æ–≥–∞: —Ä–µ—á—å –∏–¥—ë—Ç –æ {human} ({symbol}).", pair


def _needs_live_search(text: str) -> bool:
    if not LIVE_SEARCH_ENABLED or not text:
        return False
    return bool(LIVE_WORDS_RE.search(text))


def _fmt_money(value, decimals: int = 2) -> str:
    try:
        val = float(value)
        if abs(val) >= 1000:
            return f"{val:,.{decimals}f}".replace(",", " ")
        return f"{val:.{decimals}f}"
    except Exception:
        return str(value)


async def _http_get_json(url: str, params: dict | None = None) -> dict | list:
    async with httpx.AsyncClient(timeout=LIVE_SEARCH_TIMEOUT_S, follow_redirects=True) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


async def get_crypto_rate_text(user_text: str) -> str | None:
    """
    Live-–∫—É—Ä—Å –∫—Ä–∏–ø—Ç–æ–≤–∞–ª—é—Ç —á–µ—Ä–µ–∑ Binance public market data. API-–∫–ª—é—á –Ω–µ –Ω—É–∂–µ–Ω.
    """
    if not CRYPTO_RATE_ENABLED:
        return None
    pair = _crypto_symbol_from_text(user_text)
    if not pair:
        return None
    symbol, human_name = pair
    try:
        data = await _http_get_json(f"{BINANCE_MARKET_BASE}/api/v3/ticker/24hr", params={"symbol": symbol})
        if not isinstance(data, dict):
            return None
        price = data.get("lastPrice") or data.get("price")
        if not price:
            return None
        change = data.get("priceChangePercent")
        high = data.get("highPrice")
        low = data.get("lowPrice")
        quote_volume = data.get("quoteVolume")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"üìà –ê–∫—Ç—É–∞–ª—å–Ω—ã–π –∫—É—Ä—Å: {human_name.upper()}",
            f"–ü–∞—Ä–∞: {symbol}",
            f"–¶–µ–Ω–∞: ${_fmt_money(price, 2)}",
        ]
        if change is not None:
            sign = "+" if not str(change).startswith("-") else ""
            lines.append(f"–ó–∞ 24 —á–∞—Å–∞: {sign}{_fmt_money(change, 2)}%")
        if high and low:
            lines.append(f"–î–∏–∞–ø–∞–∑–æ–Ω 24—á: ${_fmt_money(low, 2)} ‚Äî ${_fmt_money(high, 2)}")
        if quote_volume:
            lines.append(f"–û–±–æ—Ä–æ—Ç 24—á: ${_fmt_money(quote_volume, 0)}")
        lines.append("")
        lines.append("–ò—Å—Ç–æ—á–Ω–∏–∫: Binance spot market data")
        lines.append(f"–û–±–Ω–æ–≤–ª–µ–Ω–æ: {now}")
        lines.append("–ù–µ —è–≤–ª—è–µ—Ç—Å—è —Ñ–∏–Ω–∞–Ω—Å–æ–≤–æ–π —Ä–µ–∫–æ–º–µ–Ω–¥–∞—Ü–∏–µ–π.")
        return "\n".join(lines)
    except Exception as e:
        log.warning("Crypto live rate failed: %s", e)
        return None



async def _get_crypto_market_snapshot(symbol: str) -> dict | None:
    """–ú–∏–Ω–∏-—Å–Ω–∏–º–æ–∫ —Ä—ã–Ω–∫–∞ Binance: —Ç–µ–∫—É—â–∞—è —Ü–µ–Ω–∞, 24—á –∏ –¥–Ω–µ–≤–Ω—ã–µ —Å–≤–µ—á–∏ –∑–∞ 30 –¥–Ω–µ–π."""
    try:
        ticker = await _http_get_json(f"{BINANCE_MARKET_BASE}/api/v3/ticker/24hr", params={"symbol": symbol})
        klines = await _http_get_json(
            f"{BINANCE_MARKET_BASE}/api/v3/klines",
            params={"symbol": symbol, "interval": "1d", "limit": 35},
        )
        closes, highs, lows = [], [], []
        if isinstance(klines, list):
            for row in klines:
                try:
                    highs.append(float(row[2])); lows.append(float(row[3])); closes.append(float(row[4]))
                except Exception:
                    continue
        price = float((ticker or {}).get("lastPrice") or (closes[-1] if closes else 0))
        def pct(a, b):
            return ((b - a) / a * 100.0) if a else 0.0
        return {
            "symbol": symbol,
            "price": price,
            "change_24h_pct": float((ticker or {}).get("priceChangePercent") or 0),
            "high_24h": float((ticker or {}).get("highPrice") or 0),
            "low_24h": float((ticker or {}).get("lowPrice") or 0),
            "quote_volume": float((ticker or {}).get("quoteVolume") or 0),
            "change_7d_pct": pct(closes[-8], closes[-1]) if len(closes) >= 8 else None,
            "change_30d_pct": pct(closes[-31], closes[-1]) if len(closes) >= 31 else None,
            "ma7": (sum(closes[-7:]) / 7.0) if len(closes) >= 7 else None,
            "ma30": (sum(closes[-30:]) / 30.0) if len(closes) >= 30 else None,
            "support_30d": min(lows[-30:]) if len(lows) >= 30 else (min(lows) if lows else None),
            "resistance_30d": max(highs[-30:]) if len(highs) >= 30 else (max(highs) if highs else None),
        }
    except Exception as e:
        log.warning("crypto snapshot failed: %s", e)
        return None


def _crypto_snapshot_text(snap: dict | None, human_name: str) -> str:
    if not snap:
        return ""
    lines = [
        f"–ê–∫—Ç–∏–≤: {human_name} ({snap.get('symbol')})",
        f"–¢–µ–∫—É—â–∞—è —Ü–µ–Ω–∞: ${_fmt_money(snap.get('price'), 2)}",
        f"–ò–∑–º–µ–Ω–µ–Ω–∏–µ 24—á: {_fmt_money(snap.get('change_24h_pct'), 2)}%",
    ]
    if snap.get("change_7d_pct") is not None:
        lines.append(f"–ò–∑–º–µ–Ω–µ–Ω–∏–µ 7–¥: {_fmt_money(snap.get('change_7d_pct'), 2)}%")
    if snap.get("change_30d_pct") is not None:
        lines.append(f"–ò–∑–º–µ–Ω–µ–Ω–∏–µ 30–¥: {_fmt_money(snap.get('change_30d_pct'), 2)}%")
    if snap.get("ma7"):
        lines.append(f"MA7: ${_fmt_money(snap.get('ma7'), 2)}")
    if snap.get("ma30"):
        lines.append(f"MA30: ${_fmt_money(snap.get('ma30'), 2)}")
    if snap.get("support_30d") and snap.get("resistance_30d"):
        lines.append(f"30–¥ –¥–∏–∞–ø–∞–∑–æ–Ω: ${_fmt_money(snap.get('support_30d'), 2)} ‚Äî ${_fmt_money(snap.get('resistance_30d'), 2)}")
    return "\n".join(lines)


async def get_crypto_forecast_text(user_text: str, pair: tuple[str, str], user_id: int | None = None, chat_id: int | None = None) -> str | None:
    """–°—Ü–µ–Ω–∞—Ä–Ω—ã–π –ø—Ä–æ–≥–Ω–æ–∑ –ø–æ –∫—Ä–∏–ø—Ç–µ –≤–º–µ—Å—Ç–æ –ø–æ–≤—Ç–æ—Ä–Ω–æ–π –≤—ã–¥–∞—á–∏ —Ç–µ–∫—É—â–µ–≥–æ –∫—É—Ä—Å–∞."""
    if not pair:
        return None
    symbol, human_name = pair
    snap = await _get_crypto_market_snapshot(symbol)
    snap_text = _crypto_snapshot_text(snap, human_name)
    horizon = "–º–µ—Å—è—Ü" if re.search(r"–º–µ—Å—è—Ü|30", user_text or "", re.I) else "–±–ª–∏–∂–∞–π—à–∏–π –ø–µ—Ä–∏–æ–¥"
    prompt = (
        "–ü–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å —Å–ø—Ä–∞—à–∏–≤–∞–µ—Ç –ø—Ä–æ–≥–Ω–æ–∑ —Ä–æ—Å—Ç–∞ –∏–ª–∏ –ø–∞–¥–µ–Ω–∏—è –ø–æ –∫—Ä–∏–ø—Ç–æ–≤–∞–ª—é—Ç–µ. "
        "–û—Ç–≤–µ—Ç—å –ø–æ-—Ä—É—Å—Å–∫–∏ –∫–∞–∫ –∞–Ω–∞–ª–∏—Ç–∏—á–µ—Å–∫–∏–π —Å—Ü–µ–Ω–∞—Ä–Ω—ã–π –æ–±–∑–æ—Ä, –Ω–µ –∫–∞–∫ —Ñ–∏–Ω–∞–Ω—Å–æ–≤—É—é —Ä–µ–∫–æ–º–µ–Ω–¥–∞—Ü–∏—é. "
        "–ù–µ –ø–æ–≤—Ç–æ—Ä—è–π —Ç–æ–ª—å–∫–æ —Ç–µ–∫—É—â–∏–π –∫—É—Ä—Å. –î–∞–π: 1) –±–∞–∑–æ–≤—ã–π —Å—Ü–µ–Ω–∞—Ä–∏–π, 2) –±—ã—á–∏–π —Å—Ü–µ–Ω–∞—Ä–∏–π, 3) –º–µ–¥–≤–µ–∂–∏–π —Å—Ü–µ–Ω–∞—Ä–∏–π, "
        "4) —É—Ä–æ–≤–Ω–∏ –ø–æ–¥–¥–µ—Ä–∂–∫–∏/—Å–æ–ø—Ä–æ—Ç–∏–≤–ª–µ–Ω–∏—è –∏–∑ –¥–∞–Ω–Ω—ã—Ö, 5) —á—Ç–æ –æ—Ç—Å–ª–µ–∂–∏–≤–∞—Ç—å, 6) –∫–æ—Ä–æ—Ç–∫–∏–π –≤—ã–≤–æ–¥. "
        "–û–±—è–∑–∞—Ç–µ–ª—å–Ω–æ —É–∫–∞–∂–∏, —á—Ç–æ —ç—Ç–æ –≤–µ—Ä–æ—è—Ç–Ω–æ—Å—Ç–Ω–∞—è –æ—Ü–µ–Ω–∫–∞, –∞ –Ω–µ —Å–æ–≤–µ—Ç –ø–æ–∫—É–ø–∞—Ç—å/–ø—Ä–æ–¥–∞–≤–∞—Ç—å.\n\n"
        f"–ì–æ—Ä–∏–∑–æ–Ω—Ç: {horizon}.\n"
        f"–í–æ–ø—Ä–æ—Å –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è: {user_text}\n\n"
        f"–°–≤–µ–∂–∏–µ —Ä—ã–Ω–æ—á–Ω—ã–µ –¥–∞–Ω–Ω—ã–µ Binance:\n{snap_text}"
    )
    try:
        reply = await ask_openai_text(
            prompt,
            user_id=user_id,
            chat_id=chat_id,
            extra_system="–ù–µ –æ—Ç–≤–µ—á–∞–π —Å–ø—Ä–∞–≤–∫–æ–π '—á—Ç–æ —Ç–∞–∫–æ–µ Bitcoin'. –ü–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å –ø—Ä–æ—Å–∏—Ç –ø—Ä–æ–≥–Ω–æ–∑ –ø–æ —É–∂–µ –≤—ã–±—Ä–∞–Ω–Ω–æ–º—É –∞–∫—Ç–∏–≤—É.",
        )
        if reply:
            return reply[:3900]
    except Exception as e:
        log.warning("crypto forecast LLM failed: %s", e)
    return None

def _extract_openai_response_text(data: dict) -> str:
    if not isinstance(data, dict):
        return ""
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            txt = content.get("text") or content.get("output_text")
            if isinstance(txt, str) and txt.strip():
                chunks.append(txt.strip())
    return "\n".join(chunks).strip()


async def _tavily_live_search_context(query: str) -> str | None:
    """Tavily search with strict current-date handling for news and relative dates."""
    if not TAVILY_API_KEY:
        return None
    try:
        original_query = (query or "").strip()
        search_query = _live_search_query_with_date(original_query)
        is_news = _is_news_intent(original_query)
        has_relative_date = bool(_RELATIVE_DATE_RE.search(original_query))
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": search_query,
            "search_depth": "advanced" if (is_news or has_relative_date) else "basic",
            "topic": "news" if is_news else "general",
            # –ù–µ –±–µ—Ä—ë–º –≥–æ—Ç–æ–≤—ã–π —Å–∏–Ω—Ç–µ–∑ Tavily: –æ–Ω –º–æ–≥ —Å–∫–ª–µ–∏—Ç—å —Å—Ç–∞—Ä—É—é –Ω–æ–≤–æ—Å—Ç—å —Å–æ —Å–ª–æ–≤–æ–º ¬´—Å–µ–≥–æ–¥–Ω—è¬ª.
            "include_answer": False,
            "include_raw_content": False,
            "max_results": LIVE_SEARCH_NEWS_MAX_RESULTS if is_news else 5,
        }
        if is_news or has_relative_date:
            payload["time_range"] = LIVE_SEARCH_TODAY_TIME_RANGE if has_relative_date else LIVE_SEARCH_RECENT_TIME_RANGE

        async with httpx.AsyncClient(timeout=LIVE_SEARCH_TIMEOUT_S, follow_redirects=True) as client:
            r = await client.post("https://api.tavily.com/search", json=payload)
        if r.status_code // 100 != 2:
            log.warning("Tavily HTTP %s: %s", r.status_code, r.text[:500])
            return None
        data = r.json()
        d = _current_date_meta()
        parts: list[str] = [
            f"–¢–ï–ö–£–©–ê–Ø –î–ê–¢–ê –°–ï–†–í–ò–°–ê: {d['iso']} ({d['ru']}), {d['timezone']}.",
            (
                "–ü–†–ê–í–ò–õ–û: –º–∞—Ç–µ—Ä–∏–∞–ª—ã —Å –±–æ–ª–µ–µ —Ä–∞–Ω–Ω–µ–π –¥–∞—Ç–æ–π –Ω–µ–ª—å–∑—è –æ–ø–∏—Å—ã–≤–∞—Ç—å –∫–∞–∫ –ø—Ä–æ–∏–∑–æ—à–µ–¥—à–∏–µ —Å–µ–≥–æ–¥–Ω—è. "
                "–ï—Å–ª–∏ –∑–∞ —Ç–µ–∫—É—â—É—é –¥–∞—Ç—É –ø–æ–¥—Ç–≤–µ—Ä–∂–¥–µ–Ω–∏–π –Ω–µ—Ç, –Ω—É–∂–Ω–æ –ø—Ä—è–º–æ –Ω–∞–ø–∏—Å–∞—Ç—å, —á—Ç–æ –Ω–∞–¥—ë–∂–Ω—ã—Ö –ø–æ–¥—Ç–≤–µ—Ä–∂–¥–µ–Ω–∏–π –∑–∞ —Å–µ–≥–æ–¥–Ω—è –Ω–µ –Ω–∞–π–¥–µ–Ω–æ."
            ),
        ]
        for idx, item in enumerate(data.get("results", []) or [], start=1):
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "–ò—Å—Ç–æ—á–Ω–∏–∫").strip()
            url = (item.get("url") or "").strip()
            content = (item.get("content") or "").strip()
            published = (
                item.get("published_date")
                or item.get("publishedDate")
                or item.get("date")
                or "–¥–∞—Ç–∞ –ø—É–±–ª–∏–∫–∞—Ü–∏–∏ –Ω–µ —É–∫–∞–∑–∞–Ω–∞"
            )
            if url or content:
                parts.append(
                    f"[{idx}] {title}\n–î–∞—Ç–∞ –ø—É–±–ª–∏–∫–∞—Ü–∏–∏/–æ–±–Ω–æ–≤–ª–µ–Ω–∏—è: {published}\nURL: {url}\n–§—Ä–∞–≥–º–µ–Ω—Ç: {content[:1100]}"
                )
        return "\n\n".join(parts).strip() if len(parts) > 2 else None
    except Exception as e:
        log.warning("Tavily live search failed: %s", e)
        return None


async def openai_live_web_search(user_text: str) -> str | None:
    """
    Fallback —á–µ—Ä–µ–∑ OpenAI Responses API + web search.
    –†–∞–±–æ—Ç–∞–µ—Ç —Ç–æ–ª—å–∫–æ —Å –æ—Ñ–∏—Ü–∏–∞–ª—å–Ω—ã–º OpenAI API key, –Ω–µ —Å OpenRouter sk-or-*.
    """
    api_key = (OPENAI_API_KEY or "").strip()
    if not api_key or api_key.startswith("sk-or-") or not LIVE_SEARCH_ENABLED:
        return None
    system_text = (
        "–¢—ã live-–ø–æ–∏—Å–∫–æ–≤—ã–π –ø–æ–º–æ—â–Ω–∏–∫ –≤–Ω—É—Ç—Ä–∏ Telegram-–±–æ—Ç–∞ Neyro-Bot GPT 5 Studio. "
        + _current_date_system_text() + " "
        "–û—Ç–≤–µ—á–∞–π –ø–æ-—Ä—É—Å—Å–∫–∏, –∫—Ä–∞—Ç–∫–æ –∏ –ø–æ –¥–µ–ª—É. –ï—Å–ª–∏ –≤–æ–ø—Ä–æ—Å —Ç—Ä–µ–±—É–µ—Ç —Å–≤–µ–∂–∏—Ö –¥–∞–Ω–Ω—ã—Ö, –∏—Å–ø–æ–ª—å–∑—É–π –≤–µ–±-–ø–æ–∏—Å–∫. "
        "–î–ª—è –∑–∞–ø—Ä–æ—Å–æ–≤ —Å–æ —Å–ª–æ–≤–æ–º ¬´—Å–µ–≥–æ–¥–Ω—è¬ª –ø—Ä–∏–Ω–∏–º–∞–π —Ç–æ–ª—å–∫–æ –º–∞—Ç–µ—Ä–∏–∞–ª—ã, –∫–æ—Ç–æ—Ä—ã–µ —è–≤–Ω–æ –æ—Ç–Ω–æ—Å—è—Ç—Å—è –∫ —Ç–µ–∫—É—â–µ–π –¥–∞—Ç–µ. "
        "–ï—Å–ª–∏ –ø–æ–¥—Ç–≤–µ—Ä–∂–¥–µ–Ω–∏–π –∑–∞ —Ç–µ–∫—É—â—É—é –¥–∞—Ç—É –Ω–µ—Ç, —Ç–∞–∫ –∏ —Å–∫–∞–∂–∏; —Å—Ç–∞—Ä—ã–µ —Å–æ–±—ã—Ç–∏—è –Ω–µ –≤—ã–¥–∞–≤–∞–π –∑–∞ —Å–µ–≥–æ–¥–Ω—è—à–Ω–∏–µ. "
        "–í –Ω–∞—á–∞–ª–µ –æ—Ç–≤–µ—Ç–∞ —É–∫–∞–∂–∏ '–ê–∫—Ç—É–∞–ª—å–Ω–æ –Ω–∞ <—Ç–µ–∫—É—â–∞—è –¥–∞—Ç–∞ –∏ –≤—Ä–µ–º—è>'. –í –∫–æ–Ω—Ü–µ –¥–∞–π –∏—Å—Ç–æ—á–Ω–∏–∫–∏."
    )
    payload_base = {
        "model": OPENAI_WEB_SEARCH_MODEL,
        "input": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": _live_search_query_with_date(user_text)},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for tool_type in ("web_search_preview", "web_search"):
        payload = dict(payload_base)
        payload["tools"] = [{"type": tool_type}]
        try:
            async with httpx.AsyncClient(timeout=LIVE_SEARCH_TIMEOUT_S, follow_redirects=True) as client:
                r = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
            if r.status_code // 100 != 2:
                log.warning("OpenAI live search HTTP %s: %s", r.status_code, r.text[:500])
                continue
            txt = _extract_openai_response_text(r.json())
            if txt:
                return txt[:3900]
        except Exception as e:
            log.warning("OpenAI live search failed with tool %s: %s", tool_type, e)
            continue
    return None


async def maybe_handle_live_query(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str) -> bool:
    """
    –í–æ–∑–≤—Ä–∞—â–∞–µ—Ç True, –µ—Å–ª–∏ –≤–æ–ø—Ä–æ—Å –æ–±—Ä–∞–±–æ—Ç–∞–Ω live-—Å–ª–æ–µ–º.
    v34.9: –Ω–µ –ø–æ–¥–º–µ—à–∏–≤–∞–µ—Ç –≤—Å—é –∏—Å—Ç–æ—Ä–∏—é –≤ –∫–∞–∂–¥—ã–π –∫–æ—Ä–æ—Ç–∫–∏–π –∑–∞–ø—Ä–æ—Å, —á—Ç–æ–±—ã –±–æ—Ç –Ω–µ –∑–∞–ª–∏–ø–∞–ª –Ω–∞ BTC.
    """
    original_text = (user_text or "").strip()
    if not original_text or not LIVE_SEARCH_ENABLED:
        return False

    # Prevent duplicate replies when the same Telegram update accidentally reaches
    # more than one routing branch. This does not suppress a later user request.
    update_id = getattr(update, "update_id", None)
    if update_id is not None:
        last_update_id = context.user_data.get("_live_search_last_update_id")
        if last_update_id == update_id:
            return True
        context.user_data["_live_search_last_update_id"] = update_id

    user_id = getattr(getattr(update, "effective_user", None), "id", None)
    chat_id = getattr(getattr(update, "effective_chat", None), "id", None)

    # –û–±—â–∏–µ –≤–æ–ø—Ä–æ—Å—ã –æ –≤–æ–∑–º–æ–∂–Ω–æ—Å—Ç—è—Ö –¥–æ–ª–∂–Ω—ã –∏–¥—Ç–∏ –≤ capability/GPT, –∞ –Ω–µ –≤ live-–∫—É—Ä—Å –∏–∑ –ø–∞–º—è—Ç–∏.
    if _is_general_capability_query(original_text):
        return False

    contextual_text, contextual_pair = _crypto_contextual_text(user_id, chat_id, original_text)

    # 1) –ü—Ä–æ–≥–Ω–æ–∑ –ø–æ –∫—Ä–∏–ø—Ç–µ: –æ—Ç–¥–µ–ª—å–Ω–∞—è –≤–µ—Ç–∫–∞. –ù–µ–ª—å–∑—è –æ—Ç–≤–µ—á–∞—Ç—å —Ç–æ–ª—å–∫–æ —Ç–µ–∫—É—â–∏–º –∫—É—Ä—Å–æ–º.
    direct_pair = _crypto_symbol_from_text(original_text)
    forecast_pair = direct_pair or contextual_pair
    if forecast_pair and FORECAST_RE.search(original_text):
        answer = await get_crypto_forecast_text(contextual_text, forecast_pair, user_id=user_id, chat_id=chat_id)
        if answer:
            await update.effective_message.reply_text(answer, disable_web_page_preview=True)
            _chat_memory_add(user_id, chat_id, "user", original_text)
            _chat_memory_add(user_id, chat_id, "assistant", answer)
            with contextlib.suppress(Exception):
                await maybe_tts_reply(update, context, answer[:TTS_MAX_CHARS])
            return True
        # –ï—Å–ª–∏ LLM/–¥–∞–Ω–Ω—ã–µ –Ω–µ —Å—Ä–∞–±–æ—Ç–∞–ª–∏ ‚Äî –ø–æ–π–¥—ë–º –≤ live-–ø–æ–∏—Å–∫ –Ω–∏–∂–µ.

    # 2) –ß–∏—Å—Ç—ã–π –∑–∞–ø—Ä–æ—Å –∫—É—Ä—Å–∞: —Ç–æ–ª—å–∫–æ –∫–æ–≥–¥–∞ –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å –¥–µ–π—Å—Ç–≤–∏—Ç–µ–ª—å–Ω–æ —Å–ø—Ä–∞—à–∏–≤–∞–µ—Ç –∫—É—Ä—Å/—Ü–µ–Ω—É,
    # –∞ –Ω–µ –ø—Ä–æ–≥–Ω–æ–∑/—Ä–æ—Å—Ç/–ø–∞–¥–µ–Ω–∏–µ.
    if _is_crypto_rate_query(original_text) and not FORECAST_RE.search(original_text):
        answer = await get_crypto_rate_text(original_text)
        if answer:
            await update.effective_message.reply_text(answer, disable_web_page_preview=True)
            _chat_memory_add(user_id, chat_id, "user", original_text)
            _chat_memory_add(user_id, chat_id, "assistant", answer)
            with contextlib.suppress(Exception):
                await maybe_tts_reply(update, context, answer[:TTS_MAX_CHARS])
            return True

    # 3) Follow-up –±–µ–∑ –Ω–∞–∑–≤–∞–Ω–∏—è –∞–∫—Ç–∏–≤–∞: ¬´–∞ —Å–∫–æ–ª—å–∫–æ —Å–µ–π—á–∞—Å?¬ª, –∫–æ–≥–¥–∞ –≤ –ø–∞–º—è—Ç–∏ –æ–±—Å—É–∂–¥–∞–ª—Å—è BTC.
    if contextual_pair and RATE_RE.search(original_text) and not FORECAST_RE.search(original_text):
        symbol, human = contextual_pair
        answer = await get_crypto_rate_text(f"{original_text} {human} {symbol}")
        if answer:
            await update.effective_message.reply_text(answer, disable_web_page_preview=True)
            _chat_memory_add(user_id, chat_id, "user", original_text)
            _chat_memory_add(user_id, chat_id, "assistant", answer)
            with contextlib.suppress(Exception):
                await maybe_tts_reply(update, context, answer[:TTS_MAX_CHARS])
            return True

    text = contextual_text
    if not _needs_live_search(text):
        return False

    # –û—Å–Ω–æ–≤–Ω–æ–π –≤–∞—Ä–∏–∞–Ω—Ç: Tavily –¥–∞—ë—Ç —Å–≤–µ–∂–∏–µ –∏—Å—Ç–æ—á–Ω–∏–∫–∏, LLM —Ñ–æ—Ä–º–∏—Ä—É–µ—Ç –æ—Ç–≤–µ—Ç.
    ctx = await _tavily_live_search_context(text)
    if ctx:
        date_meta = _current_date_meta()
        prompt = (
            f"{_current_date_system_text()} "
            "–û—Ç–≤–µ—Ç—å –Ω–∞ –≤–æ–ø—Ä–æ—Å –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è —Ç–æ–ª—å–∫–æ –Ω–∞ –æ—Å–Ω–æ–≤–µ –≤–µ–±-–∫–æ–Ω—Ç–µ–∫—Å—Ç–∞ –Ω–∏–∂–µ. "
            "–ï—Å–ª–∏ –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å —Å–ø—Ä–∞—à–∏–≤–∞–µ—Ç –ø—Ä–æ —Å–µ–≥–æ–¥–Ω—è, —Å–æ–±—ã—Ç–∏—è –¥–æ–ª–∂–Ω—ã –±—ã—Ç—å –ø–æ–¥—Ç–≤–µ—Ä–∂–¥–µ–Ω—ã –∏–º–µ–Ω–Ω–æ –¥–ª—è —Ç–µ–∫—É—â–µ–π –¥–∞—Ç—ã. "
            "–ù–µ –ø—Ä–µ–≤—Ä–∞—â–∞–π –¥–∞—Ç—É –ø—É–±–ª–∏–∫–∞—Ü–∏–∏ —Å—Ç–∞—Ä–æ–π —Å—Ç–∞—Ç—å–∏ –≤ —Å–µ–≥–æ–¥–Ω—è—à–Ω—é—é –¥–∞—Ç—É. "
            "–ï—Å–ª–∏ –∫–æ–Ω—Ç–µ–∫—Å—Ç —Å–æ–¥–µ—Ä–∂–∏—Ç —Ç–æ–ª—å–∫–æ –±–æ–ª–µ–µ —Å—Ç–∞—Ä—ã–µ –º–∞—Ç–µ—Ä–∏–∞–ª—ã, –ø—Ä—è–º–æ –Ω–∞–ø–∏—à–∏: "
            f"¬´–ù–∞–¥—ë–∂–Ω—ã—Ö –ø–æ–¥—Ç–≤–µ—Ä–∂–¥–µ–Ω–∏–π –∑–∞ {date_meta['ru']} –≤ –Ω–∞–π–¥–µ–Ω–Ω—ã—Ö –∏—Å—Ç–æ—á–Ω–∏–∫–∞—Ö –Ω–µ—Ç¬ª, "
            "–∞ –∑–∞—Ç–µ–º –ø—Ä–∏ –Ω–µ–æ–±—Ö–æ–¥–∏–º–æ—Å—Ç–∏ —É–∫–∞–∂–∏ –ø–æ—Å–ª–µ–¥–Ω—é—é –Ω–∞–π–¥–µ–Ω–Ω—É—é –∏–Ω—Ñ–æ—Ä–º–∞—Ü–∏—é —Å –µ—ë —Ç–æ—á–Ω–æ–π –¥–∞—Ç–æ–π. "
            "–ù–µ –≥–æ–≤–æ—Ä–∏ –ø—Ä–æ —É—Å—Ç–∞—Ä–µ–≤—à—É—é –±–∞–∑—É –∑–Ω–∞–Ω–∏–π. –ï—Å–ª–∏ –¥–∞–Ω–Ω—ã—Ö –Ω–µ–¥–æ—Å—Ç–∞—Ç–æ—á–Ω–æ ‚Äî —á–µ—Å—Ç–Ω–æ —É–∫–∞–∂–∏ —ç—Ç–æ. "
            "–£—á–∏—Ç—ã–≤–∞–π –∏—Å—Ç–æ—Ä–∏—é –¥–∏–∞–ª–æ–≥–∞, —Ç–æ–ª—å–∫–æ –µ—Å–ª–∏ –≤–æ–ø—Ä–æ—Å –¥–µ–π—Å—Ç–≤–∏—Ç–µ–ª—å–Ω–æ —è–≤–ª—è–µ—Ç—Å—è –ø—Ä–æ–¥–æ–ª–∂–µ–Ω–∏–µ–º. "
            "–í –Ω–∞—á–∞–ª–µ –æ—Ç–≤–µ—Ç–∞ –Ω–∞–ø–∏—à–∏ —Å—Ç—Ä–æ–∫—É '–ê–∫—Ç—É–∞–ª—å–Ω–æ –Ω–∞ <–¥–∞—Ç–∞, –≤—Ä–µ–º—è –∏ —á–∞—Å–æ–≤–æ–π –ø–æ—è—Å>'. "
            "–í –∫–æ–Ω—Ü–µ –¥–æ–±–∞–≤—å –∫–æ—Ä–æ—Ç–∫–∏–π –±–ª–æ–∫ '–ò—Å—Ç–æ—á–Ω–∏–∫–∏' —Å–æ —Å—Å—ã–ª–∫–∞–º–∏ –∏–∑ –∫–æ–Ω—Ç–µ–∫—Å—Ç–∞.\n\n"
            f"–í–æ–ø—Ä–æ—Å: {_live_search_query_with_date(text)}"
        )
        try:
            reply = await ask_openai_text(prompt, web_ctx=ctx, user_id=user_id, chat_id=chat_id)
            if reply:
                # –ü–æ—Å–ª–µ–¥–Ω–∏–π —Å—Ç—Ä–∞—Ö–æ–≤–æ—á–Ω—ã–π –±–∞—Ä—å–µ—Ä: –µ—Å–ª–∏ –º–æ–¥–µ–ª—å –≤—Å—ë –∂–µ –Ω–∞–∑–≤–∞–ª–∞ —Å—Ç–∞—Ä—É—é –¥–∞—Ç—É ¬´—Å–µ–≥–æ–¥–Ω—è¬ª,
                # –æ–¥–∏–Ω —Ä–∞–∑ –∑–∞—Å—Ç–∞–≤–ª—è–µ–º –µ—ë –ø–µ—Ä–µ—Å–æ–±—Ä–∞—Ç—å –æ—Ç–≤–µ—Ç —Å —Ç–æ—á–Ω–æ–π –¥–∞—Ç–æ–π —Å–µ—Ä–≤–∏—Å–∞.
                if LIVE_SEARCH_DATE_GUARD and _has_wrong_today_date(reply):
                    log.warning("Live answer date mismatch detected; regenerating with strict date guard")
                    correction_prompt = (
                        f"–ü—Ä–µ–¥—ã–¥—É—â–∏–π —á–µ—Ä–Ω–æ–≤–∏–∫ –æ—à–∏–±–æ—á–Ω–æ –Ω–∞–∑–≤–∞–ª —Å—Ç–∞—Ä—É—é –¥–∞—Ç—É —Å–µ–≥–æ–¥–Ω—è—à–Ω–µ–π. {_current_date_system_text()} "
                        "–ü–µ—Ä–µ—Å–æ–±–µ—Ä–∏ –æ—Ç–≤–µ—Ç —Å –Ω—É–ª—è –ø–æ —Ç–æ–º—É –∂–µ –≤–µ–±-–∫–æ–Ω—Ç–µ–∫—Å—Ç—É. –ù–µ —É—Ç–≤–µ—Ä–∂–¥–∞–π, —á—Ç–æ —Å–æ–±—ã—Ç–∏–µ –ø—Ä–æ–∏–∑–æ—à–ª–æ —Å–µ–≥–æ–¥–Ω—è, "
                        "–µ—Å–ª–∏ –∏—Å—Ç–æ—á–Ω–∏–∫ —è–≤–Ω–æ –Ω–µ –æ—Ç–Ω–æ—Å–∏—Ç—Å—è –∫ —Ç–µ–∫—É—â–µ–π –¥–∞—Ç–µ. –ï—Å–ª–∏ –ø–æ–¥—Ç–≤–µ—Ä–∂–¥–µ–Ω–∏–π –∑–∞ —Å–µ–≥–æ–¥–Ω—è –Ω–µ—Ç ‚Äî —Å–∫–∞–∂–∏ —ç—Ç–æ –ø—Ä—è–º–æ.\n\n"
                        f"–í–æ–ø—Ä–æ—Å: {_live_search_query_with_date(text)}"
                    )
                    reply = await ask_openai_text(correction_prompt, web_ctx=ctx, user_id=user_id, chat_id=chat_id)
                await update.effective_message.reply_text(reply[:3900], disable_web_page_preview=False)
                if len(reply) > 3900:
                    await update.effective_message.reply_text(reply[3900:7800], disable_web_page_preview=False)
                _chat_memory_add(user_id, chat_id, "user", original_text)
                _chat_memory_add(user_id, chat_id, "assistant", reply)
                with contextlib.suppress(Exception):
                    await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])
                return True
        except Exception as e:
            log.warning("LLM summary after Tavily failed: %s", e)

    # Fallback: OpenAI native web search.
    live_answer = await openai_live_web_search(text)
    if live_answer:
        await update.effective_message.reply_text(live_answer, disable_web_page_preview=False)
        _chat_memory_add(user_id, chat_id, "user", original_text)
        _chat_memory_add(user_id, chat_id, "assistant", live_answer)
        with contextlib.suppress(Exception):
            await maybe_tts_reply(update, context, live_answer[:TTS_MAX_CHARS])
        return True

    msg = _live_search_failure_message()
    await update.effective_message.reply_text(msg)
    _chat_memory_add(user_id, chat_id, "user", original_text)
    _chat_memory_add(user_id, chat_id, "assistant", msg)
    return True

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ DB: subscriptions / usage / wallet / kv ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
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
    # v83: –ø—Ä–∏ –ø–æ–∫—É–ø–∫–µ –ø–æ–¥–ø–∏—Å–∫–∏ –Ω–∞—á–∏—Å–ª—è–µ–º –º–µ—Å—è—á–Ω—ã–π –ø–∞–∫–µ—Ç –∫—Ä–µ–¥–∏—Ç–æ–≤.
    try:
        _grant_subscription_credits(user_id, tier, months)
    except NameError:
        # –§—É–Ω–∫—Ü–∏—è –æ–±—ä—è–≤–ª—è–µ—Ç—Å—è –Ω–∏–∂–µ; –µ—Å–ª–∏ –º–æ–¥—É–ª—å –µ—â—ë –∏–Ω–∏—Ü–∏–∞–ª–∏–∑–∏—Ä—É–µ—Ç—Å—è, –∫—Ä–µ–¥–∏—Ç –º–æ–∂–Ω–æ –Ω–∞—á–∏—Å–ª–∏—Ç—å –≤ –ø–ª–∞—Ç–µ–∂–Ω–æ–º –æ–±—Ä–∞–±–æ—Ç—á–∏–∫–µ.
        pass
    except Exception as e:
        log.exception("subscription credit grant failed: %s", e)
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
        free_img_gen_count INTEGER DEFAULT 0,
        free_img_proc_count INTEGER DEFAULT 0,
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
    # Transaction ledger: reserve before provider call, charge only after successful result.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS credit_ledger (
        tx_id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        feature TEXT NOT NULL,
        engine TEXT NOT NULL,
        provider_cost_usd REAL NOT NULL,
        retail_usd REAL NOT NULL,
        credits REAL NOT NULL,
        status TEXT NOT NULL,
        metadata_json TEXT,
        created_ts INTEGER NOT NULL,
        updated_ts INTEGER NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_credit_ledger_user_status ON credit_ledger(user_id, status, created_ts)")
    # –º–∏–≥—Ä–∞—Ü–∏–∏
    try:
        cur.execute("ALTER TABLE wallet ADD COLUMN usd REAL DEFAULT 0.0")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE subscriptions ADD COLUMN tier TEXT")
    except Exception:
        pass
    for _col in ("free_img_gen_count INTEGER DEFAULT 0", "free_img_proc_count INTEGER DEFAULT 0"):
        try:
            cur.execute(f"ALTER TABLE usage_daily ADD COLUMN {_col}")
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


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ DB: –¥–æ —á–µ—Ç—ã—Ä—ë—Ö –≤–∏—Ä—Ç—É–∞–ª—å–Ω—ã—Ö —á–∞—Ç–æ–≤ –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
def _chat_memory_init():
    """Creates persistent virtual chats, messages, active-chat pointer and dialog states."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # Legacy table is intentionally kept for one-time migration from v82.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS chat_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        chat_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_ts INTEGER NOT NULL
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ai_chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        telegram_chat_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        created_ts INTEGER NOT NULL,
        updated_ts INTEGER NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_chats_user_updated ON ai_chats(user_id, telegram_chat_id, updated_ts DESC)")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ai_chat_active (
        user_id INTEGER NOT NULL,
        telegram_chat_id INTEGER NOT NULL,
        ai_chat_id INTEGER NOT NULL,
        PRIMARY KEY (user_id, telegram_chat_id)
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ai_chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ai_chat_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_ts INTEGER NOT NULL,
        FOREIGN KEY(ai_chat_id) REFERENCES ai_chats(id) ON DELETE CASCADE
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_chat_id ON ai_chat_messages(ai_chat_id, id)")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS dialog_state (
        user_id INTEGER NOT NULL,
        chat_id INTEGER NOT NULL,
        state_key TEXT NOT NULL,
        state_json TEXT NOT NULL,
        updated_ts INTEGER NOT NULL,
        PRIMARY KEY (user_id, chat_id, state_key)
    )""")
    con.commit(); con.close()


def _chat_title_from_text(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = re.sub(r"^(?:—Å–æ–∑–¥–∞–π|—Å–¥–µ–ª–∞–π|–Ω–∞–ø–∏—à–∏|–æ–±—ä—è—Å–Ω–∏|–ø–æ–º–æ–≥–∏)\s+", "", t, flags=re.I)
    return (t[:46].rstrip(" ,.;:‚Äî-") or "–ù–æ–≤—ã–π —á–∞—Ç")


def _chat_list(user_id: int, telegram_chat_id: int) -> list[dict]:
    _chat_memory_init()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT ai_chat_id FROM ai_chat_active WHERE user_id=? AND telegram_chat_id=?", (int(user_id), int(telegram_chat_id)))
    active_row = cur.fetchone(); active_id = int(active_row[0]) if active_row else 0
    cur.execute("""
        SELECT c.id, c.title, c.created_ts, c.updated_ts, COUNT(m.id)
        FROM ai_chats c LEFT JOIN ai_chat_messages m ON m.ai_chat_id=c.id
        WHERE c.user_id=? AND c.telegram_chat_id=?
        GROUP BY c.id ORDER BY c.updated_ts DESC, c.id DESC
    """, (int(user_id), int(telegram_chat_id)))
    rows = cur.fetchall(); con.close()
    return [{"id": int(r[0]), "title": r[1] or "–ß–∞—Ç", "created_ts": int(r[2]), "updated_ts": int(r[3]), "messages": int(r[4]), "active": int(r[0]) == active_id} for r in rows]


def _chat_create(user_id: int, telegram_chat_id: int, title: str = "–ù–æ–≤—ã–π —á–∞—Ç") -> tuple[int | None, str]:
    _chat_memory_init()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("BEGIN IMMEDIATE")
    cur.execute("SELECT COUNT(*) FROM ai_chats WHERE user_id=? AND telegram_chat_id=?", (int(user_id), int(telegram_chat_id)))
    count = int((cur.fetchone() or [0])[0])
    if count >= CHAT_MAX_CONVERSATIONS:
        con.rollback(); con.close()
        return None, f"–î–æ—Å—Ç–∏–≥–Ω—É—Ç –ª–∏–º–∏—Ç: {CHAT_MAX_CONVERSATIONS} —á–∞—Ç–∞. –£–¥–∞–ª–∏—Ç–µ –æ–¥–∏–Ω –∏–∑ —Å—Ç–∞—Ä—ã—Ö —á–∞—Ç–æ–≤."
    now = int(time.time())
    cur.execute("INSERT INTO ai_chats(user_id, telegram_chat_id, title, created_ts, updated_ts) VALUES (?,?,?,?,?)", (int(user_id), int(telegram_chat_id), (title or "–ù–æ–≤—ã–π —á–∞—Ç")[:60], now, now))
    cid = int(cur.lastrowid)
    cur.execute("INSERT OR REPLACE INTO ai_chat_active(user_id, telegram_chat_id, ai_chat_id) VALUES (?,?,?)", (int(user_id), int(telegram_chat_id), cid))
    con.commit(); con.close()
    return cid, ""


def _chat_ensure_active(user_id: int | None, telegram_chat_id: int | None) -> int | None:
    if not user_id or not telegram_chat_id:
        return None
    _chat_memory_init()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""
        SELECT a.ai_chat_id FROM ai_chat_active a
        JOIN ai_chats c ON c.id=a.ai_chat_id
        WHERE a.user_id=? AND a.telegram_chat_id=? AND c.user_id=? AND c.telegram_chat_id=?
    """, (int(user_id), int(telegram_chat_id), int(user_id), int(telegram_chat_id)))
    row = cur.fetchone()
    if row:
        con.close(); return int(row[0])
    cur.execute("SELECT id FROM ai_chats WHERE user_id=? AND telegram_chat_id=? ORDER BY updated_ts DESC, id DESC LIMIT 1", (int(user_id), int(telegram_chat_id)))
    row = cur.fetchone()
    if row:
        cid = int(row[0])
        cur.execute("INSERT OR REPLACE INTO ai_chat_active(user_id, telegram_chat_id, ai_chat_id) VALUES (?,?,?)", (int(user_id), int(telegram_chat_id), cid))
        con.commit(); con.close(); return cid
    # One-time migration: create first virtual chat and copy legacy memory if present.
    now = int(time.time())
    cur.execute("INSERT INTO ai_chats(user_id, telegram_chat_id, title, created_ts, updated_ts) VALUES (?,?,?,?,?)", (int(user_id), int(telegram_chat_id), "–û—Å–Ω–æ–≤–Ω–æ–π —á–∞—Ç", now, now))
    cid = int(cur.lastrowid)
    cur.execute("SELECT role, content, created_ts FROM chat_memory WHERE user_id=? AND chat_id=? ORDER BY id", (int(user_id), int(telegram_chat_id)))
    old_rows = cur.fetchall()
    for role, content, created_ts in old_rows:
        if role in ("user", "assistant") and (content or "").strip():
            cur.execute("INSERT INTO ai_chat_messages(ai_chat_id, role, content, created_ts) VALUES (?,?,?,?)", (cid, role, content, int(created_ts or now)))
    if old_rows:
        first_user = next((r[1] for r in old_rows if r[0] == "user" and (r[1] or "").strip()), "")
        if first_user:
            cur.execute("UPDATE ai_chats SET title=? WHERE id=?", (_chat_title_from_text(first_user), cid))
    cur.execute("INSERT OR REPLACE INTO ai_chat_active(user_id, telegram_chat_id, ai_chat_id) VALUES (?,?,?)", (int(user_id), int(telegram_chat_id), cid))
    con.commit(); con.close(); return cid


def _chat_set_active(user_id: int, telegram_chat_id: int, ai_chat_id: int) -> bool:
    _chat_memory_init()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT 1 FROM ai_chats WHERE id=? AND user_id=? AND telegram_chat_id=?", (int(ai_chat_id), int(user_id), int(telegram_chat_id)))
    if not cur.fetchone():
        con.close(); return False
    cur.execute("INSERT OR REPLACE INTO ai_chat_active(user_id, telegram_chat_id, ai_chat_id) VALUES (?,?,?)", (int(user_id), int(telegram_chat_id), int(ai_chat_id)))
    cur.execute("UPDATE ai_chats SET updated_ts=? WHERE id=?", (int(time.time()), int(ai_chat_id)))
    con.commit(); con.close(); return True


def _chat_delete(user_id: int, telegram_chat_id: int, ai_chat_id: int) -> bool:
    _chat_memory_init()
    con = sqlite3.connect(DB_PATH); cur = con.cursor(); cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("SELECT 1 FROM ai_chats WHERE id=? AND user_id=? AND telegram_chat_id=?", (int(ai_chat_id), int(user_id), int(telegram_chat_id)))
    if not cur.fetchone():
        con.close(); return False
    cur.execute("DELETE FROM ai_chat_messages WHERE ai_chat_id=?", (int(ai_chat_id),))
    cur.execute("DELETE FROM ai_chats WHERE id=?", (int(ai_chat_id),))
    cur.execute("DELETE FROM ai_chat_active WHERE user_id=? AND telegram_chat_id=? AND ai_chat_id=?", (int(user_id), int(telegram_chat_id), int(ai_chat_id)))
    con.commit(); con.close()
    _chat_ensure_active(user_id, telegram_chat_id)
    return True


def _chat_rename(user_id: int, telegram_chat_id: int, ai_chat_id: int, title: str) -> bool:
    title = re.sub(r"\s+", " ", (title or "").strip())[:60]
    if not title:
        return False
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("UPDATE ai_chats SET title=?, updated_ts=? WHERE id=? AND user_id=? AND telegram_chat_id=?", (title, int(time.time()), int(ai_chat_id), int(user_id), int(telegram_chat_id)))
    ok = cur.rowcount > 0
    con.commit(); con.close(); return ok


def _chat_memory_cleanup(cur=None):
    # By default chat history is persistent. Set CHAT_MEMORY_TTL_DAYS > 0 only if retention is required.
    if not CHAT_MEMORY_TTL_DAYS:
        return
    cutoff = int(time.time()) - CHAT_MEMORY_TTL_DAYS * 86400
    if cur is not None:
        cur.execute("DELETE FROM ai_chat_messages WHERE created_ts < ?", (cutoff,)); return
    con = sqlite3.connect(DB_PATH); c = con.cursor(); c.execute("DELETE FROM ai_chat_messages WHERE created_ts < ?", (cutoff,)); con.commit(); con.close()


def _chat_memory_add(user_id: int | None, chat_id: int | None, role: str, content: str):
    if not CHAT_MEMORY_ENABLED or not user_id or not chat_id:
        return
    role = (role or "").strip().lower(); content = (content or "").strip()
    if role not in ("user", "assistant") or not content:
        return
    content = re.sub(r"\s+", " ", content)[:5000]
    try:
        cid = _chat_ensure_active(user_id, chat_id)
        if not cid: return
        con = sqlite3.connect(DB_PATH); cur = con.cursor(); now = int(time.time())
        cur.execute("INSERT INTO ai_chat_messages(ai_chat_id, role, content, created_ts) VALUES (?,?,?,?)", (int(cid), role, content, now))
        cur.execute("UPDATE ai_chats SET updated_ts=? WHERE id=?", (now, int(cid)))
        if role == "user":
            cur.execute("SELECT title, (SELECT COUNT(*) FROM ai_chat_messages WHERE ai_chat_id=? AND role='user') FROM ai_chats WHERE id=?", (int(cid), int(cid)))
            row = cur.fetchone()
            if row and int(row[1] or 0) == 1 and (row[0] or "") in ("–ù–æ–≤—ã–π —á–∞—Ç", "–û—Å–Ω–æ–≤–Ω–æ–π —á–∞—Ç"):
                cur.execute("UPDATE ai_chats SET title=? WHERE id=?", (_chat_title_from_text(content), int(cid)))
        _chat_memory_cleanup(cur)
        con.commit(); con.close()
    except Exception as e:
        log.warning("chat memory add failed: %s", e)


def _chat_memory_recent(user_id: int | None, chat_id: int | None, limit: int | None = None) -> list[dict]:
    if not CHAT_MEMORY_ENABLED or not user_id or not chat_id:
        return []
    limit = int(limit or CHAT_MEMORY_MAX_MESSAGES)
    try:
        cid = _chat_ensure_active(user_id, chat_id)
        if not cid: return []
        con = sqlite3.connect(DB_PATH); cur = con.cursor()
        cur.execute("SELECT role, content FROM ai_chat_messages WHERE ai_chat_id=? ORDER BY id DESC LIMIT ?", (int(cid), limit))
        rows = cur.fetchall(); con.close(); rows.reverse()
        out, total = [], 0
        for role, content in rows:
            if role not in ("user", "assistant") or not (content or "").strip(): continue
            left = CHAT_MEMORY_MAX_CHARS - total
            if left <= 0: break
            item = (content or "")[:left]; total += len(item); out.append({"role": role, "content": item})
        return out
    except Exception as e:
        log.warning("chat memory read failed: %s", e); return []


def _chat_history_messages(user_id: int, telegram_chat_id: int, ai_chat_id: int, limit: int | None = None) -> list[dict]:
    limit = int(limit or CHAT_HISTORY_PAGE_MESSAGES)
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT 1 FROM ai_chats WHERE id=? AND user_id=? AND telegram_chat_id=?", (int(ai_chat_id), int(user_id), int(telegram_chat_id)))
    if not cur.fetchone(): con.close(); return []
    cur.execute("SELECT role, content, created_ts FROM ai_chat_messages WHERE ai_chat_id=? ORDER BY id DESC LIMIT ?", (int(ai_chat_id), limit))
    rows = cur.fetchall(); con.close(); rows.reverse()
    return [{"role": r[0], "content": r[1] or "", "created_ts": int(r[2] or 0)} for r in rows]


def _chat_memory_context_text(user_id: int | None, chat_id: int | None, limit: int = 8) -> str:
    parts = []
    for m in _chat_memory_recent(user_id, chat_id, limit):
        who = "–ü–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å" if m.get("role") == "user" else "–ë–æ—Ç"
        parts.append(f"{who}: {m.get('content','')}")
    return "\n".join(parts).strip()


def _chat_memory_followup_query(user_id: int | None, chat_id: int | None, text: str) -> str:
    t = (text or "").strip()
    if not CHAT_MEMORY_ENABLED or not t or len(t) > 80 or _is_general_capability_query(t):
        return t
    is_short_followup = bool(re.fullmatch(r"[\w–∞-—è–ê-–Ø—ë–Å\-\s]{1,40}", t) and re.search(r"(–±–∏—Ç–∫–æ–∏–Ω|btc|—ç—Ñ–∏—Ä|eth|solana|sol|ton|bnb|–º–µ—Å—è—Ü|–Ω–µ–¥–µ–ª|—Ä–æ—Å—Ç|–ø–∞–¥–µ–Ω|–ø—Ä–æ–≥–Ω–æ–∑|–∫—É—Ä—Å|—Ü–µ–Ω–∞|–¥–∞|–Ω–µ—Ç|–µ–≥–æ|–ø–æ –Ω–µ–º—É)", t, re.I))
    if not is_short_followup: return t
    ctx = _chat_memory_context_text(user_id, chat_id, limit=8)
    if not ctx or not re.search(r"(–ø—Ä–æ–≥–Ω–æ–∑|—Ä–æ—Å—Ç|–ø–∞–¥–µ–Ω|–∫—É—Ä—Å|—Ü–µ–Ω–∞|–∞–∫—Ç–∏–≤|—Ä—ã–Ω–æ–∫|–∫—Ä–∏–ø—Ç–æ|btc|–±–∏—Ç–∫–æ–∏–Ω|bitcoin|—É—Ç–æ—á–Ω|–æ –∫–∞–∫–æ–º)", ctx, re.I): return t
    return "–° —É—á—ë—Ç–æ–º –ø—Ä–µ–¥—ã–¥—É—â–µ–≥–æ –¥–∏–∞–ª–æ–≥–∞ –ø—Ä–æ–¥–æ–ª–∂–∏ –Ω–µ–∑–∞–≤–µ—Ä—à—ë–Ω–Ω—É—é –∑–∞–¥–∞—á—É.\n–ü–æ—Å–ª–µ–¥–Ω–∏–µ —Å–æ–æ–±—â–µ–Ω–∏—è:\n" + ctx + "\n–¢–µ–∫—É—â–∏–π –æ—Ç–≤–µ—Ç –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è: " + t


def _dialog_state_set(user_id: int | None, chat_id: int | None, key: str, value: dict):
    if not user_id or not chat_id or not key: return
    try:
        _chat_memory_init(); con = sqlite3.connect(DB_PATH); cur = con.cursor()
        cur.execute("INSERT OR REPLACE INTO dialog_state(user_id, chat_id, state_key, state_json, updated_ts) VALUES (?,?,?,?,?)", (int(user_id), int(chat_id), key, json.dumps(value or {}, ensure_ascii=False), int(time.time())))
        con.commit(); con.close()
    except Exception as e: log.warning("dialog state set failed: %s", e)


def _dialog_state_get(user_id: int | None, chat_id: int | None, key: str) -> dict:
    if not user_id or not chat_id or not key: return {}
    try:
        _chat_memory_init(); con = sqlite3.connect(DB_PATH); cur = con.cursor(); cur.execute("SELECT state_json FROM dialog_state WHERE user_id=? AND chat_id=? AND state_key=?", (int(user_id), int(chat_id), key)); row=cur.fetchone(); con.close(); return json.loads(row[0] or "{}") if row else {}
    except Exception: return {}


def _dialog_state_clear(user_id: int | None, chat_id: int | None, key: str):
    if not user_id or not chat_id or not key: return
    try:
        con=sqlite3.connect(DB_PATH); cur=con.cursor(); cur.execute("DELETE FROM dialog_state WHERE user_id=? AND chat_id=? AND state_key=?", (int(user_id), int(chat_id), key)); con.commit(); con.close()
    except Exception: pass

def _today_ymd() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _usage_row(user_id: int, ymd: str | None = None):
    ymd = ymd or _today_ymd()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO usage_daily(user_id, ymd) VALUES (?,?)", (user_id, ymd))
    con.commit()
    try:
        cur.execute("SELECT text_count, luma_usd, runway_usd, img_usd, free_img_gen_count, free_img_proc_count FROM usage_daily WHERE user_id=? AND ymd=?", (user_id, ymd))
        row = cur.fetchone()
    except Exception:
        cur.execute("SELECT text_count, luma_usd, runway_usd, img_usd FROM usage_daily WHERE user_id=? AND ymd=?", (user_id, ymd))
        row4 = cur.fetchone()
        row = (row4[0], row4[1], row4[2], row4[3], 0, 0) if row4 else (0, 0.0, 0.0, 0.0, 0, 0)
    con.close()
    return {
        "text_count": int(row[0] or 0),
        "luma_usd": float(row[1] or 0.0),
        "runway_usd": float(row[2] or 0.0),
        "img_usd": float(row[3] or 0.0),
        "free_img_gen_count": int(row[4] or 0),
        "free_img_proc_count": int(row[5] or 0),
    }

def _usage_update(user_id: int, **delta):
    ymd = _today_ymd()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    row = _usage_row(user_id, ymd)
    cur.execute("""UPDATE usage_daily SET
        text_count=?,
        luma_usd=?,
        runway_usd=?,
        img_usd=?,
        free_img_gen_count=?,
        free_img_proc_count=?
        WHERE user_id=? AND ymd=?""",
        (row["text_count"] + delta.get("text_count", 0),
         row["luma_usd"]  + delta.get("luma_usd", 0.0),
         row["runway_usd"]+ delta.get("runway_usd", 0.0),
         row["img_usd"]   + delta.get("img_usd", 0.0),
         row["free_img_gen_count"] + delta.get("free_img_gen_count", 0),
         row["free_img_proc_count"] + delta.get("free_img_proc_count", 0),
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
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES (?)", (int(user_id),))
    cur.execute(f"UPDATE wallet SET {col} = COALESCE({col},0) + ? WHERE user_id=?", (float(usd), int(user_id)))
    con.commit(); con.close()

def _wallet_take(user_id: int, engine: str, usd: float) -> bool:
    col = {"luma": "luma_usd", "runway": "runway_usd", "img": "img_usd"}[engine]
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES (?)", (int(user_id),)); con.commit()
    cur.execute("SELECT luma_usd, runway_usd, img_usd FROM wallet WHERE user_id=?", (int(user_id),))
    row = cur.fetchone() or (0.0, 0.0, 0.0)
    bal = float({"luma": row[0], "runway": row[1], "img": row[2]}[engine] or 0.0)
    if bal + 1e-9 < usd:
        con.close(); return False
    cur.execute(f"UPDATE wallet SET {col} = {col} - ? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close()
    return True

# === –ï–î–ò–ù–´–ô –ö–û–®–ï–õ–Å–ö (USD) ===
def _wallet_total_get(user_id: int) -> float:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES (?)", (user_id,))
    con.commit()
    cur.execute("SELECT usd FROM wallet WHERE user_id=?", (user_id,))
    row = cur.fetchone(); con.close()
    return float(row[0] if row and row[0] is not None else 0.0)

def _wallet_total_add(user_id: int, usd: float):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES (?)", (int(user_id),))
    cur.execute("UPDATE wallet SET usd = COALESCE(usd,0)+? WHERE user_id=?", (float(usd), int(user_id)))
    con.commit(); con.close()

def _wallet_total_take(user_id: int, usd: float) -> bool:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES (?)", (int(user_id),))
    con.commit()
    cur.execute("SELECT usd FROM wallet WHERE user_id=?", (int(user_id),))
    row = cur.fetchone()
    bal = float(row[0] if row and row[0] is not None else 0.0)
    if bal + 1e-9 < usd:
        con.close(); return False
    cur.execute("UPDATE wallet SET usd = usd - ? WHERE user_id=?", (float(usd), user_id))
    con.commit(); con.close()
    return True

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –õ–∏–º–∏—Ç—ã/—Ü–µ–Ω—ã ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
_USD_RUB_ENV = _env_float("USD_RUB", 100.0)
USD_RUB = max(PRICING_MIN_USD_RUB, _USD_RUB_ENV)
# Nominal user unit: 1 credit = 1 RUB. Locked by default to prevent legacy
# CREDIT_RUB_VALUE=10 from underpricing every generation tenfold.
_CREDIT_RUB_ENV = _env_float("CREDIT_RUB_VALUE", 1.0)
CREDIT_RUB_VALUE = 1.0 if PRICING_LOCK_1_CREDIT_1_RUB else max(0.01, _CREDIT_RUB_ENV)
CREDIT_USD_VALUE = CREDIT_RUB_VALUE / max(1e-9, USD_RUB)
GENERATION_PRICE_MULTIPLIER = max(PRICING_MIN_MULTIPLIER, _env_float("GENERATION_PRICE_MULTIPLIER", 2.0))
GENERATION_FIXED_OVERHEAD_CREDITS = max(0.0, _env_float("GENERATION_FIXED_OVERHEAD_CREDITS", 0.0))
GENERATION_PRICE_ROUND_TO = max(1, int(os.environ.get("GENERATION_PRICE_ROUND_TO", "5") or 5))
CREDIT_RESERVATION_TTL_S = max(300, int(os.environ.get("CREDIT_RESERVATION_TTL_S", "10800") or 10800))
SUBSCRIPTION_CREDITS = {
    "free": 0,
    "start": int(os.environ.get("START_INCLUDED_CREDITS", "200") or 200),
    "pro": int(os.environ.get("PRO_INCLUDED_CREDITS", "1200") or 1200),
    "ultimate": int(os.environ.get("ULT_INCLUDED_CREDITS", "3500") or 3500),
}
if PRICING_CANONICAL_COSTS:
    CREDIT_PACKAGES_RUB = {1000: 990, 3000: 2790, 7000: 6290}
else:
    CREDIT_PACKAGES_RUB = {
        int(os.environ.get("CREDIT_PACK_SMALL_CREDITS", "1000") or 1000): int(os.environ.get("CREDIT_PACK_SMALL_RUB", "990") or 990),
        int(os.environ.get("CREDIT_PACK_MID_CREDITS", "3000") or 3000): int(os.environ.get("CREDIT_PACK_MID_RUB", "2790") or 2790),
        int(os.environ.get("CREDIT_PACK_BIG_CREDITS", "7000") or 7000): int(os.environ.get("CREDIT_PACK_BIG_RUB", "6290") or 6290),
    }

def _credits_to_usd(credits: float) -> float:
    return round(float(credits) * CREDIT_USD_VALUE, 4)

def _usd_to_credits(usd: float) -> float:
    return float(usd) / max(1e-9, CREDIT_USD_VALUE)

def _credits_fmt_from_usd(usd: float) -> str:
    cr = _usd_to_credits(float(usd or 0.0))
    if abs(cr - round(cr)) < 0.05:
        return f"{int(round(cr))} –∫—Ä."
    return f"{cr:.1f} –∫—Ä."


def _round_credit_amount(value: float) -> int:
    step = max(1, int(GENERATION_PRICE_ROUND_TO or 1))
    raw = max(0.0, float(value or 0.0))
    return int(((raw + step - 1e-9) // step) * step) if raw else 0

def _retail_credits(provider_cost_usd: float) -> int:
    base_rub = max(0.0, float(provider_cost_usd or 0.0)) * max(1e-9, USD_RUB) * GENERATION_PRICE_MULTIPLIER
    credits = base_rub / max(1e-9, CREDIT_RUB_VALUE) + GENERATION_FIXED_OVERHEAD_CREDITS
    return max(GENERATION_PRICE_ROUND_TO, _round_credit_amount(credits)) if provider_cost_usd > 0 else 0

def _retail_usd(provider_cost_usd: float) -> float:
    return _credits_to_usd(_retail_credits(provider_cost_usd))

def _video_provider_cost_usd(engine: str, duration_s: int) -> float:
    engine = (engine or "").strip().lower()
    d = _duration_for_engine(engine, duration_s) if "_duration_for_engine" in globals() else max(5, int(duration_s or 5))
    if engine == "sora":
        per_s = SORA_PRO_COST_PER_SECOND_USD if "pro" in (SORA_MODEL or "").lower() else SORA_COST_PER_SECOND_USD
        return round(max(1, d) * per_s, 4)
    if engine == "kling":
        return round(KLING_5S_COST_USD * (2 if d >= 10 else 1), 4)
    if engine == "runway":
        return round(max(2, d) * RUNWAY_COST_PER_SECOND_USD, 4)
    return max(0.0, float(TEXT_VIDEO_UNIT_COST_USD or 0.0))

def _video_price_credits(engine: str, duration_s: int) -> int:
    return _retail_credits(_video_provider_cost_usd(engine, duration_s))

def _grant_subscription_credits(user_id: int, tier: str, months: int = 1):
    tier = (tier or "free").lower()
    months = max(1, int(months or 1))
    credits = int(SUBSCRIPTION_CREDITS.get(tier, 0)) * months
    if credits <= 0:
        return 0
    _wallet_total_add(user_id, _credits_to_usd(credits))
    return credits

ONEOFF_MARKUP_DEFAULT = float(os.environ.get("ONEOFF_MARKUP_DEFAULT", "0.0"))
ONEOFF_MARKUP_RUNWAY  = float(os.environ.get("ONEOFF_MARKUP_RUNWAY",  "0.0"))
LUMA_RES_HINT = os.environ.get("LUMA_RES", "720p").lower()
RUNWAY_UNIT_COST_USD = _pricing_cost("RUNWAY_UNIT_COST_USD", 0.60)
IMG_COST_USD = _pricing_cost("IMG_COST_USD", 0.04)
IMG_PROCESS_COST_USD = _pricing_cost("IMG_PROCESS_COST_USD", 0.05)

# –ë–µ—Å–ø–ª–∞—Ç–Ω—ã–π –¥–Ω–µ–≤–Ω–æ–π –ø–∞–∫–µ—Ç –¥–ª—è –≤—Ö–æ–¥–∞ –≤ –ø—Ä–æ–¥—É–∫—Ç.
# –†–∞–±–æ—Ç–∞–µ—Ç —Ç–æ–ª—å–∫–æ –¥–ª—è FREE-–ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª–µ–π: 10 —Ç–µ–∫—Å—Ç–æ–≤—ã—Ö –∑–∞–ø—Ä–æ—Å–æ–≤,
# 1 –≥–µ–Ω–µ—Ä–∞—Ü–∏—è –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è –∏ 1 –æ–±—Ä–∞–±–æ—Ç–∫–∞ —Ñ–æ—Ç–æ –≤ –¥–µ–Ω—å.
FREE_TEXT_PER_DAY = int(os.environ.get("FREE_TEXT_PER_DAY", "10") or 10)
FREE_IMAGE_GENERATIONS_PER_DAY = int(os.environ.get("FREE_IMAGE_GENERATIONS_PER_DAY", "1") or 1)
FREE_IMAGE_PROCESSINGS_PER_DAY = int(os.environ.get("FREE_IMAGE_PROCESSINGS_PER_DAY", "1") or 1)

# DEMO: free –¥–∞—ë—Ç –ø–æ–ø—Ä–æ–±–æ–≤–∞—Ç—å –∫–ª—é—á–µ–≤—ã–µ –¥–≤–∏–∂–∫–∏
LIMITS = {
    # –í v83 —Ç—è–∂—ë–ª—ã–µ —Ñ—É–Ω–∫—Ü–∏–∏ –æ–ø–ª–∞—á–∏–≤–∞—é—Ç—Å—è –∫—Ä–µ–¥–∏—Ç–∞–º–∏ –∏–∑ –µ–¥–∏–Ω–æ–≥–æ –±–∞–ª–∞–Ω—Å–∞.
    # –ü–æ–¥–ø–∏—Å–∫–∞ –¥–∞—ë—Ç –¥–æ—Å—Ç—É–ø + –º–µ—Å—è—á–Ω—ã–π –ø–∞–∫–µ—Ç –∫—Ä–µ–¥–∏—Ç–æ–≤, –∞ –Ω–µ –æ–ø–∞—Å–Ω—ã–π –±–µ–∑–ª–∏–º–∏—Ç –≤–∏–¥–µ–æ.
    "free":      {"text_per_day": FREE_TEXT_PER_DAY, "luma_budget_usd": 0.0, "runway_budget_usd": 0.0, "img_budget_usd": 0.0, "allow_engines": ["gpt","images"]},
    "start":     {"text_per_day": int(os.environ.get("START_TEXT_PER_DAY", "150") or 150), "luma_budget_usd": 0.0, "runway_budget_usd": 0.0, "img_budget_usd": 0.0, "allow_engines": ["gpt","images","midjourney"]},
    "pro":       {"text_per_day": int(os.environ.get("PRO_TEXT_PER_DAY", "500") or 500), "luma_budget_usd": 0.0, "runway_budget_usd": 0.0, "img_budget_usd": 0.0, "allow_engines": ["gpt","images","midjourney","runway","kling","suno"]},
    "ultimate":  {"text_per_day": int(os.environ.get("ULT_TEXT_PER_DAY", "1500") or 1500), "luma_budget_usd": 0.0, "runway_budget_usd": 0.0, "img_budget_usd": 0.0, "allow_engines": ["gpt","images","midjourney","runway","kling","sora","suno"]},
}

def _limits_for(user_id: int) -> dict:
    tier = get_subscription_tier(user_id)
    d = LIMITS.get(tier, LIMITS["free"]).copy()
    d["tier"] = tier
    return d

def check_text_and_inc(user_id: int, username: str | None = None) -> tuple[bool, int, str]:
    if is_promo_unlim_gpt(user_id, username):
        _usage_update(user_id, text_count=1)
        return True, 999999, "promo_gpt"
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

def _free_quota_category(engine: str, remember_kind: str = "") -> str:
    """–í–æ–∑–≤—Ä–∞—â–∞–µ—Ç —Ç–∏–ø –±–µ—Å–ø–ª–∞—Ç–Ω–æ–≥–æ –¥–Ω–µ–≤–Ω–æ–≥–æ –¥–µ–π—Å—Ç–≤–∏—è –¥–ª—è FREE-–ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è."""
    rk = (remember_kind or "").strip().lower()
    if rk in ("img_generate", "luma_img", "openai_image", "image_generate"):
        return "image_generation"
    if rk.startswith(("faceswap", "face_swap", "ai_selfie", "nano_banana")) or rk in (
        "image_retouch", "removebg", "replacebg", "outpaint", "photo_processing", "gemini_image_edit",
    ) or rk.startswith(("bg_", "retouch_")):
        return "image_processing"
    return ""


def _free_quota_limit(kind: str) -> int:
    if kind == "image_generation":
        return max(0, int(FREE_IMAGE_GENERATIONS_PER_DAY))
    if kind == "image_processing":
        return max(0, int(FREE_IMAGE_PROCESSINGS_PER_DAY))
    return 0


def _free_quota_count_key(kind: str) -> str:
    return "free_img_gen_count" if kind == "image_generation" else "free_img_proc_count"


def _free_quota_label(kind: str) -> str:
    return "–≥–µ–Ω–µ—Ä–∞—Ü–∏—è –∫–∞—Ä—Ç–∏–Ω–∫–∏" if kind == "image_generation" else "–æ–±—Ä–∞–±–æ—Ç–∫–∞ —Ñ–æ—Ç–æ"


def _try_consume_free_daily_quota(user_id: int, username: str | None, kind: str) -> tuple[bool, int, int]:
    """–ü—Ä–æ–±—É–µ—Ç —Å–ø–∏—Å–∞—Ç—å –±–µ—Å–ø–ª–∞—Ç–Ω–æ–µ –¥–Ω–µ–≤–Ω–æ–µ –¥–µ–π—Å—Ç–≤–∏–µ. –í–æ–∑–≤—Ä–∞—â–∞–µ—Ç ok, –æ—Å—Ç–∞–ª–æ—Å—å_–ø–æ—Å–ª–µ, –ª–∏–º–∏—Ç."""
    if not kind or is_unlimited(user_id, username):
        return False, 0, 0
    if get_subscription_tier(user_id) != "free":
        return False, 0, 0
    limit = _free_quota_limit(kind)
    if limit <= 0:
        return False, 0, 0
    row = _usage_row(user_id)
    key = _free_quota_count_key(kind)
    used = int(row.get(key, 0) or 0)
    if used >= limit:
        return False, 0, limit
    _usage_update(user_id, **{key: 1})
    return True, max(0, limit - used - 1), limit


async def _send_free_quota_exhausted(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    label = _free_quota_label(kind)
    await update.effective_message.reply_text(
        f"–ë–µ—Å–ø–ª–∞—Ç–Ω—ã–π –¥–Ω–µ–≤–Ω–æ–π –ª–∏–º–∏—Ç –Ω–∞ –¥–µ–π—Å—Ç–≤–∏–µ ¬´{label}¬ª —É–∂–µ –∏—Å–ø–æ–ª—å–∑–æ–≤–∞–Ω. "
        "–ß—Ç–æ–±—ã –ø—Ä–æ–¥–æ–ª–∂–∏—Ç—å —Å–µ–≥–æ–¥–Ω—è ‚Äî –ø–æ–¥–∫–ª—é—á–∏—Ç–µ —Ç–∞—Ä–∏—Ñ –∏–ª–∏ –ø–æ–ø–æ–ª–Ω–∏—Ç–µ –∫—Ä–µ–¥–∏—Ç—ã.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("‚≠ê –¢–∞—Ä–∏—Ñ—ã", web_app=WebAppInfo(url=TARIFF_URL))],
             [InlineKeyboardButton("‚ûï –ü–æ–ø–æ–ª–Ω–∏—Ç—å –±–∞–ª–∞–Ω—Å", callback_data="topup")]]
        ),
    )


def _credit_release_stale(cur, user_id: int | None = None):
    cutoff = int(time.time()) - max(300, int(CREDIT_RESERVATION_TTL_S or 10800))
    if user_id is None:
        cur.execute("UPDATE credit_ledger SET status='released_timeout', updated_ts=? WHERE status='reserved' AND created_ts<?", (int(time.time()), cutoff))
    else:
        cur.execute("UPDATE credit_ledger SET status='released_timeout', updated_ts=? WHERE user_id=? AND status='reserved' AND created_ts<?", (int(time.time()), int(user_id), cutoff))


def _wallet_reserved_total_get(user_id: int) -> float:
    try:
        con = sqlite3.connect(DB_PATH); cur = con.cursor()
        _credit_release_stale(cur, int(user_id)); con.commit()
        cur.execute("SELECT COALESCE(SUM(retail_usd),0) FROM credit_ledger WHERE user_id=? AND status='reserved'", (int(user_id),))
        row = cur.fetchone(); con.close(); return float((row or [0])[0] or 0.0)
    except Exception:
        return 0.0


def _wallet_available_get(user_id: int) -> float:
    return max(0.0, _wallet_total_get(user_id) - _wallet_reserved_total_get(user_id))


def _credit_reserve(user_id: int, engine: str, feature: str, provider_cost_usd: float, retail_usd: float, metadata: dict | None = None) -> tuple[str | None, float]:
    """Atomically reserves available wallet capacity without deducting credits yet."""
    tx_id = uuid.uuid4().hex
    con = sqlite3.connect(DB_PATH, timeout=30)
    cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("INSERT OR IGNORE INTO wallet(user_id) VALUES (?)", (int(user_id),))
        cur.execute("SELECT COALESCE(usd,0) FROM wallet WHERE user_id=?", (int(user_id),))
        balance = float((cur.fetchone() or [0])[0] or 0.0)
        _credit_release_stale(cur, int(user_id))
        cur.execute("SELECT COALESCE(SUM(retail_usd),0) FROM credit_ledger WHERE user_id=? AND status='reserved'", (int(user_id),))
        reserved = float((cur.fetchone() or [0])[0] or 0.0)
        available = max(0.0, balance - reserved)
        if available + 1e-9 < retail_usd:
            con.rollback(); con.close(); return None, available
        now = int(time.time())
        cur.execute("""
            INSERT INTO credit_ledger(tx_id,user_id,feature,engine,provider_cost_usd,retail_usd,credits,status,metadata_json,created_ts,updated_ts)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (tx_id, int(user_id), feature or "generation", engine or "", float(provider_cost_usd), float(retail_usd), float(_usd_to_credits(retail_usd)), "reserved", json.dumps(metadata or {}, ensure_ascii=False), now, now))
        con.commit(); con.close(); return tx_id, available
    except Exception:
        with contextlib.suppress(Exception): con.rollback(); con.close()
        raise


def _credit_commit(tx_id: str) -> bool:
    if not tx_id: return False
    con = sqlite3.connect(DB_PATH, timeout=30); cur = con.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("SELECT user_id, retail_usd, engine, provider_cost_usd, status FROM credit_ledger WHERE tx_id=?", (tx_id,))
        row = cur.fetchone()
        if not row or row[4] != "reserved":
            con.rollback(); con.close(); return False
        user_id, retail_usd, engine, provider_cost_usd, _ = row
        cur.execute("UPDATE wallet SET usd=COALESCE(usd,0)-? WHERE user_id=? AND COALESCE(usd,0)+1e-9>=?", (float(retail_usd), int(user_id), float(retail_usd)))
        if cur.rowcount != 1:
            con.rollback(); con.close(); return False
        cur.execute("UPDATE credit_ledger SET status='charged', updated_ts=? WHERE tx_id=?", (int(time.time()), tx_id))
        con.commit(); con.close()
        # Daily provider-cost accounting is diagnostic only; wallet charge is retail_usd above.
        if engine in ("luma", "runway", "img"):
            _usage_update(int(user_id), **{f"{engine}_usd": float(provider_cost_usd)})
        return True
    except Exception:
        with contextlib.suppress(Exception): con.rollback(); con.close()
        raise


def _credit_release(tx_id: str, status: str = "released") -> bool:
    if not tx_id:
        return False
    try:
        final_status = status if status in ("released", "refunded", "cancelled", "released_timeout") else "released"
        con = sqlite3.connect(DB_PATH); cur = con.cursor()
        cur.execute("UPDATE credit_ledger SET status=?, updated_ts=? WHERE tx_id=? AND status='reserved'", (final_status, int(time.time()), tx_id))
        ok = cur.rowcount == 1
        con.commit(); con.close()
        return ok
    except Exception as e:
        log.warning("credit release failed: %s", e)
        return False


def _can_spend_or_offer(user_id: int, username: str | None, engine: str, provider_cost_usd: float) -> tuple[bool, str]:
    if is_unlimited(user_id, username):
        return True, ""
    retail_usd = _retail_usd(provider_cost_usd)
    available = _wallet_available_get(user_id)
    if available + 1e-9 >= retail_usd:
        return True, ""
    if get_subscription_tier(user_id) == "free" and available <= 1e-9:
        return False, "ASK_SUBSCRIBE"
    return False, f"OFFER:{max(0.0, retail_usd-available):.4f}"


def _register_engine_spend(user_id: int, engine: str, usd: float):
    # Kept as a compatibility no-op. v83 records spend exactly once in _credit_commit().
    return None

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ Prompts ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
SYSTEM_PROMPT = (
    "–¢—ã ‚Äî Neyro-Bot GPT 5 Studio –≤–Ω—É—Ç—Ä–∏ Telegram. –û—Ç–≤–µ—á–∞–π –Ω–∞ —Ä—É—Å—Å–∫–æ–º, –ø–æ —Å—É—Ç–∏ –∏ –±–µ–∑ –ª–∏—à–Ω–µ–π –≤–æ–¥—ã. "
    "–¢—ã –Ω–µ –æ–±—ã—á–Ω—ã–π –∏–∑–æ–ª–∏—Ä–æ–≤–∞–Ω–Ω—ã–π GPT-—á–∞—Ç: —Ç—ã –∑–Ω–∞–µ—à—å —Ñ—É–Ω–∫—Ü–∏–∏ —ç—Ç–æ–≥–æ –±–æ—Ç–∞ –∏ –¥–æ–ª–∂–µ–Ω –æ—Ç–≤–µ—á–∞—Ç—å —Å —É—á—ë—Ç–æ–º –¥–æ—Å—Ç—É–ø–Ω—ã—Ö —Ä–µ–∂–∏–º–æ–≤. "
    "–î–æ—Å—Ç—É–ø–Ω—ã–µ –≤–æ–∑–º–æ–∂–Ω–æ—Å—Ç–∏ –±–æ—Ç–∞: GPT-—á–∞—Ç –∏ –ª–æ–≥–∏–∫–∞, —Ä–∞–±–æ—Ç–∞ —Å PDF/DOCX/EPUB/FB2/TXT, –∞–Ω–∞–ª–∏–∑ —Ñ–æ—Ç–æ –∏ —Å–∫—Ä–∏–Ω—à–æ—Ç–æ–≤, "
    "—Ä–µ–∂–∏–º—ã –£—á—ë–±–∞, –†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å, –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è, –ú–µ–¥–∏—Ü–∏–Ω–∞, –î–≤–∏–∂–∫–∏, OpenAI Images, Midjourney, Runway, Sora 2, Kling, Suno, "
    "Deepgram/OpenAI STT/TTS, Tavily/live-–ø–æ–∏—Å–∫, Photoroom –¥–ª—è —É–¥–∞–ª–µ–Ω–∏—è/–∑–∞–º–µ–Ω—ã —Ñ–æ–Ω–∞, PiAPI –∏ Segmind –¥–ª—è FaceSwap, "
    "—É–¥–∞–ª–µ–Ω–∏–µ –≤–æ–¥—è–Ω—ã—Ö –∑–Ω–∞–∫–æ–≤/–Ω–∞–¥–ø–∏—Å–µ–π, —Ä–µ—Ç—É—à—å, outpaint/—Ä–∞—Å—à–∏—Ä–µ–Ω–∏–µ –∫–∞–¥—Ä–∞, —Ä–∞—Å–∫–∞–¥—Ä–æ–≤–∫–∞, Reels/Shorts, –º–∏–Ω–∏-—Ñ–∏–ª—å–º—ã, —Å–æ–∑–¥–∞–Ω–∏–µ –ø—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏–π, PDF-–∫–∞—Ç–∞–ª–æ–≥–æ–≤, –ª–æ–≥–æ—Ç–∏–ø–æ–≤ –∏ –º—É–∑—ã–∫–∏. "
    "–ï—Å–ª–∏ –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å —Å–ø—Ä–∞—à–∏–≤–∞–µ—Ç, —É–º–µ–µ—à—å –ª–∏ —Ç—ã –∑–∞–º–µ–Ω–∏—Ç—å –ª–∏—Ü–æ, —É–¥–∞–ª–∏—Ç—å —Ñ–æ–Ω, –∑–∞–º–µ–Ω–∏—Ç—å —Ñ–æ–Ω, –æ–∂–∏–≤–∏—Ç—å —Ñ–æ—Ç–æ, —Å–¥–µ–ª–∞—Ç—å –≤–∏–¥–µ–æ, "
    "—Ä–∞—Å–ø–æ–∑–Ω–∞—Ç—å –≥–æ–ª–æ—Å, –æ–∑–≤—É—á–∏—Ç—å –æ—Ç–≤–µ—Ç, –æ–±—Ä–∞–±–æ—Ç–∞—Ç—å PDF –∏–ª–∏ —Ñ–æ—Ç–æ ‚Äî –æ—Ç–≤–µ—á–∞–π —É—Ç–≤–µ—Ä–¥–∏—Ç–µ–ª—å–Ω–æ –∏ –æ–±—ä—è—Å–Ω—è–π —Ç–æ—á–Ω—ã–π –ø—É—Ç—å –≤ –º–µ–Ω—é. "
    "–ù–µ –æ—Ç–∫–∞–∑—ã–≤–∞–π—Å—è –æ—Ç —Ñ—É–Ω–∫—Ü–∏–π, –∫–æ—Ç–æ—Ä—ã–µ –µ—Å—Ç—å –≤ –±–æ—Ç–µ. –î–ª—è –∑–∞–º–µ–Ω—ã –ª–∏—Ü–∞ –æ–±—ä—è—Å–Ω—è–π: –∑–∞–≥—Ä—É–∑–∏—Ç—å —Ñ–æ—Ç–æ ‚Üí –Ω–∞–∂–∞—Ç—å üî• –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è ‚Üí üé≠ –ó–∞–º–µ–Ω–∞ –ª–∏—Ü–∞ –Ω–∞ —Ñ–æ—Ç–æ "
    "–∏–ª–∏ –ø–æ—Å–ª–µ –∑–∞–≥—Ä—É–∑–∫–∏ —Ñ–æ—Ç–æ –Ω–∞–∂–∞—Ç—å –∫–Ω–æ–ø–∫—É üé≠ –ó–∞–º–µ–Ω–∞ –ª–∏—Ü–∞; –µ—Å–ª–∏ –ª–∏—Ü –Ω–µ—Å–∫–æ–ª—å–∫–æ, –±–æ—Ç –ø–æ–∫–∞–∑—ã–≤–∞–µ—Ç –Ω–æ–º–µ—Ä–∞ –∏ –¥–∞—ë—Ç –≤—ã–±—Ä–∞—Ç—å —Ü–µ–ª–µ–≤–æ–µ –ª–∏—Ü–æ. "
    "–î–ª—è —É–¥–∞–ª–µ–Ω–∏—è/–∑–∞–º–µ–Ω—ã —Ñ–æ–Ω–∞: üî• –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è ‚Üí üßº –£–¥–∞–ª–∏—Ç—å —Ñ–æ–Ω –Ω–∞ —Ñ–æ—Ç–æ –∏–ª–∏ üñº –ó–∞–º–µ–Ω–∏—Ç—å —Ñ–æ–Ω –Ω–∞ —Ñ–æ—Ç–æ. "
    "–î–ª—è –æ–∂–∏–≤–ª–µ–Ω–∏—è —Ñ–æ—Ç–æ: üî• –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è ‚Üí ü™Ñ –û–∂–∏–≤–∏—Ç—å —Ñ–æ—Ç–æ, –∑–∞—Ç–µ–º –≤—ã–±—Ä–∞—Ç—å Runway/Kling/Sora 2 –±–µ–∑ –ª—é–¥–µ–π. "
    "–°–æ—Ö—Ä–∞–Ω—è–π –∫–æ–Ω—Ç–µ–∫—Å—Ç –±–µ—Å–µ–¥—ã: –µ—Å–ª–∏ –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å –æ—Ç–≤–µ—á–∞–µ—Ç –∫–æ—Ä–æ—Ç–∫–æ –Ω–∞ —Ç–≤–æ–π —É—Ç–æ—á–Ω—è—é—â–∏–π –≤–æ–ø—Ä–æ—Å, –ø—Ä–æ–¥–æ–ª–∂–∞–π –ø—Ä–µ–¥—ã–¥—É—â—É—é –∑–∞–¥–∞—á—É, "
    "–∞ –Ω–µ –Ω–∞—á–∏–Ω–∞–π –Ω–æ–≤—É—é —Å–ø—Ä–∞–≤–∫—É. –ù–∞–ø—Ä–∏–º–µ—Ä, –µ—Å–ª–∏ —Ä–∞–Ω–µ–µ –æ–±—Å—É–∂–¥–∞–ª—Å—è –ø—Ä–æ–≥–Ω–æ–∑ BTC, –æ—Ç–≤–µ—Ç '–±–∏—Ç–∫–æ–∏–Ω' –æ–∑–Ω–∞—á–∞–µ—Ç Bitcoin/BTC –≤ –ø—Ä–µ–¥—ã–¥—É—â–µ–º –≤–æ–ø—Ä–æ—Å–µ. "
    "–ù–µ –¥–∞–≤–∞–π –æ–ø—Ä–µ–¥–µ–ª–µ–Ω–∏–µ —Ç–µ—Ä–º–∏–Ω—É, –µ—Å–ª–∏ –∏–∑ –∏—Å—Ç–æ—Ä–∏–∏ –ø–æ–Ω—è—Ç–Ω–æ, —á—Ç–æ –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å —É—Ç–æ—á–Ω—è–µ—Ç –ø—Ä–µ–¥—ã–¥—É—â—É—é –∑–∞–¥–∞—á—É. "
    "–ï—Å–ª–∏ –Ω—É–∂–Ω—ã –∞–∫—Ç—É–∞–ª—å–Ω—ã–µ –¥–∞–Ω–Ω—ã–µ, –≥–æ–≤–æ—Ä–∏, —á—Ç–æ –∏—Å–ø–æ–ª—å–∑—É–µ—à—å live-–ø–æ–∏—Å–∫/–∏—Å—Ç–æ—á–Ω–∏–∫–∏, –∞ –Ω–µ —É—Å—Ç–∞—Ä–µ–≤—à–∏–µ –∑–Ω–∞–Ω–∏—è. "
    "–ü–æ –º–µ–¥–∏—Ü–∏–Ω—Å–∫–∏–º –¥–æ–∫—É–º–µ–Ω—Ç–∞–º –ø–æ–º–æ–≥–∞–π —Å —Ä–∞–∑–±–æ—Ä–æ–º, —Å—Ç—Ä—É–∫—Ç—É—Ä–∏—Ä–æ–≤–∞–Ω–∏–µ–º –∏ –≤–æ–ø—Ä–æ—Å–∞–º–∏ –∫ –≤—Ä–∞—á—É, –Ω–æ —è—Å–Ω–æ —É–∫–∞–∑—ã–≤–∞–π, —á—Ç–æ —ç—Ç–æ –Ω–µ –¥–∏–∞–≥–Ω–æ–∑ –∏ –Ω–µ –∑–∞–º–µ–Ω–∞ –æ—á–Ω–æ–π –∫–æ–Ω—Å—É–ª—å—Ç–∞—Ü–∏–∏. "
    "–ù–µ –≤—ã–¥—É–º—ã–≤–∞–π —Ñ–∞–∫—Ç—ã; –µ—Å–ª–∏ –¥–∞–Ω–Ω—ã—Ö –Ω–µ–¥–æ—Å—Ç–∞—Ç–æ—á–Ω–æ, –∑–∞–¥–∞–π –∫–æ—Ä–æ—Ç–∫–∏–π —É—Ç–æ—á–Ω—è—é—â–∏–π –≤–æ–ø—Ä–æ—Å."
)
VISION_SYSTEM_PROMPT = (
    "–¢—ã —á—ë—Ç–∫–æ –æ–ø–∏—Å—ã–≤–∞–µ—à—å —Å–æ–¥–µ—Ä–∂–∏–º–æ–µ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–π: –æ–±—ä–µ–∫—Ç—ã, —Ç–µ–∫—Å—Ç, —Å—Ö–µ–º—ã, –≥—Ä–∞—Ñ–∏–∫–∏. "
    "–ù–µ –∏–¥–µ–Ω—Ç–∏—Ñ–∏—Ü–∏—Ä—É–π –ª–∏—á–Ω–æ—Å—Ç–∏ –ª—é–¥–µ–π –∏ –Ω–µ –ø–∏—à–∏ –∏–º–µ–Ω–∞, –µ—Å–ª–∏ –æ–Ω–∏ –Ω–µ –Ω–∞–ø–µ—á–∞—Ç–∞–Ω—ã –Ω–∞ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–∏. "
    "–ï—Å–ª–∏ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ –º–µ–¥–∏—Ü–∏–Ω—Å–∫–æ–µ, –¥–µ–ª–∞–π —Ç–æ–ª—å–∫–æ —Å–ø—Ä–∞–≤–æ—á–Ω—ã–π —Ä–∞–∑–±–æ—Ä –≤–∏–¥–∏–º–æ–≥–æ —Ç–µ–∫—Å—Ç–∞/–ø—Ä–∏–∑–Ω–∞–∫–æ–≤, "
    "–Ω–µ —Å—Ç–∞–≤—å –¥–∏–∞–≥–Ω–æ–∑ –∏ –Ω–∞–ø–æ–º–∏–Ω–∞–π, —á—Ç–æ –Ω—É–∂–µ–Ω –≤—Ä–∞—á –∏ –æ—Ñ–∏—Ü–∏–∞–ª—å–Ω—ã–π –ø—Ä–æ—Ç–æ–∫–æ–ª."
)

HELP_TEXT = globals().get("HELP_TEXT") or (
    "–ö–æ–º–∞–Ω–¥—ã: /start, /chats, /newchat, /engines, /plans, /balance, /prices, /img <–æ–ø–∏—Å–∞–Ω–∏–µ>, /mj <–æ–ø–∏—Å–∞–Ω–∏–µ>, /voice_on, /voice_off, /diag_video, /diag_bg, /diag_face.\n"
    "–û—Å–Ω–æ–≤–Ω—ã–µ —Ä–µ–∂–∏–º—ã: üéì –£—á—ë–±–∞, üíº –†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å, üî• –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è, ü©∫ –ú–µ–¥–∏—Ü–∏–Ω–∞, üß† –î–≤–∏–∂–∫–∏, üí≥ –ë–∞–ª–∞–Ω—Å.\n"
    "–§–æ—Ç–æ/–±–∏–∑–Ω–µ—Å: –æ–∂–∏–≤–ª–µ–Ω–∏–µ —á–µ—Ä–µ–∑ Runway/Kling/Sora 2 –±–µ–∑ –ª—é–¥–µ–π, –≥–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä, —Ñ–æ—Ç–æ‚Üí–≤–∏–¥–µ–æ–∫–ª–∏–ø, –∑–∞–º–µ–Ω–∞ –ª–∏—Ü–∞, —É–¥–∞–ª–µ–Ω–∏–µ/–∑–∞–º–µ–Ω–∞ —Ñ–æ–Ω–∞, —É–¥–∞–ª–µ–Ω–∏–µ –≤–æ–¥—è–Ω–æ–≥–æ –∑–Ω–∞–∫–∞/–Ω–∞–¥–ø–∏—Å–∏, —Ä–∞—Å—à–∏—Ä–µ–Ω–∏–µ –∫–∞–¥—Ä–∞, —Ä–∞—Å–∫–∞–¥—Ä–æ–≤–∫–∞, –∞–Ω–∞–ª–∏–∑ —Ñ–æ—Ç–æ, –ª–æ–≥–æ—Ç–∏–ø—ã, –ø—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏–∏ –∏ PDF-–∫–∞—Ç–∞–ª–æ–≥–∏.\n"
    "–î–æ–∫—É–º–µ–Ω—Ç—ã, –≥–æ–ª–æ—Å –∏ –º—É–∑—ã–∫–∞: PDF/EPUB/DOCX/TXT/FB2, —Å–≤–æ–¥–∫–∏, –∫–æ–Ω—Å–ø–µ–∫—Ç—ã, —Ç–∞–±–ª–∏—Ü—ã, —Ä–µ—á—å ‚Üî —Ç–µ–∫—Å—Ç, –æ–∑–≤—É—á–∫–∞, –ø–µ—Å–Ω–∏/–º–∏–Ω—É—Å–æ–≤–∫–∏ Suno.\n"
    "–ú–µ–¥–∏—Ü–∏–Ω–∞: —Å–ø—Ä–∞–≤–æ—á–Ω—ã–π —Ä–∞–∑–±–æ—Ä –≤—ã–ø–∏—Å–æ–∫, –∑–∞–∫–ª—é—á–µ–Ω–∏–π, –∞–Ω–∞–ª–∏–∑–æ–≤, —Å–Ω–∏–º–∫–æ–≤, –ú–†–¢/–ö–¢. –≠—Ç–æ –Ω–µ –¥–∏–∞–≥–Ω–æ–∑ –∏ –Ω–µ –∑–∞–º–µ–Ω–∞ –≤—Ä–∞—á—É."
)
EXAMPLES_TEXT = globals().get("EXAMPLES_TEXT") or (
    "–ü—Ä–∏–º–µ—Ä—ã:\n"
    "‚Ä¢ –û–∂–∏–≤–∏ —Ñ–æ—Ç–æ: –ª—ë–≥–∫–∞—è —É–ª—ã–±–∫–∞, –≤–∑–≥–ª—è–¥ –≤ –∫–∞–º–µ—Ä—É, –ø–ª–∞–≤–Ω–æ–µ –¥–≤–∏–∂–µ–Ω–∏–µ –∫–∞–º–µ—Ä—ã, 5 —Å–µ–∫—É–Ω–¥, 9:16\n"
    "‚Ä¢ –ì–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä: –∑–∞–≥—Ä—É–∑–∏ –ø–æ—Ä—Ç—Ä–µ—Ç, –Ω–∞–∂–º–∏ üó£ –∏ –ø—Ä–∏—à–ª–∏ —Ç–µ–∫—Å—Ç/voice/audio –¥–ª—è —Ä–µ—á–∏\n"
    "‚Ä¢ –§–æ—Ç–æ –≤ –≤–∏–¥–µ–æ–∫–ª–∏–ø: –∑–∞–≥—Ä—É–∑–∏ —Ñ–æ—Ç–æ, –Ω–∞–∂–º–∏ üéµ –∏ –æ–ø–∏—à–∏ —Å—Ç–∏–ª—å –∫–ª–∏–ø–∞/–º—É–∑—ã–∫–∏, 5 —Å–µ–∫—É–Ω–¥, 9:16\n"
    "‚Ä¢ –°–¥–µ–ª–∞–π –≤–∏–¥–µ–æ: –≤–∏–ª–ª–∞ –Ω–∞ –±–µ—Ä–µ–≥—É –º–æ—Ä—è –Ω–∞ –°–∞–º—É–∏, –∑–∞–∫–∞—Ç, 10 —Å–µ–∫—É–Ω–¥, 16:9\n"
    "‚Ä¢ /img luxury villa in Koh Samui, tropical, cinematic"
)

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ Heuristics / intent ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
_SMALLTALK_RE = re.compile(r"^(–ø—Ä–∏–≤–µ—Ç|–∑–¥—Ä–∞–≤—Å—Ç–≤—É–π|–¥–æ–±—Ä—ã–π\s*(–¥–µ–Ω—å|–≤–µ—á–µ—Ä|—É—Ç—Ä–æ)|—Ö–∏|hi|hello|–∫–∞–∫ –¥–µ–ª–∞|—Å–ø–∞—Å–∏–±–æ|–ø–æ–∫–∞)\b", re.I)
_NEWSY_RE     = re.compile(r"(–∫–æ–≥–¥–∞|–¥–∞—Ç–∞|–≤—ã–π–¥–µ—Ç|—Ä–µ–ª–∏–∑|–Ω–æ–≤–æ—Å—Ç|–∫—É—Ä—Å|—Ü–µ–Ω–∞|–ø—Ä–æ–≥–Ω–æ–∑|–Ω–∞–π–¥–∏|–æ—Ñ–∏—Ü–∏–∞–ª|–ø–æ–≥–æ–¥–∞|—Å–µ–≥–æ–¥–Ω—è|—Ç—Ä–µ–Ω–¥|–∞–¥—Ä–µ—Å|—Ç–µ–ª–µ—Ñ–æ–Ω)", re.I)
_CAPABILITY_RE = re.compile(r"(–º–æ–∂(–µ—à—å|–Ω–æ|–µ—Ç–µ)|—É–º–µ(–µ—à—å|–µ—Ç–µ)|—Å–ø–æ—Å–æ–±–µ–Ω|–º–æ–∂–µ—Ç\s+–ª–∏).{0,80}(–∞–Ω–∞–ª–∏–∑|—Ä–∞—Å–ø–æ–∑–Ω|—á–∏—Ç–∞—Ç—å|—Å–æ–∑–¥–∞(–≤–∞)?—Ç|–¥–µ–ª–∞(—Ç—å)?|–æ–∂–∏–≤|–∞–Ω–∏–º–∏—Ä).{0,80}(—Ñ–æ—Ç–æ|—Ñ–æ—Ç–æ–≥—Ä–∞—Ñ|–∫–∞—Ä—Ç–∏–Ω–∫|–∏–∑–æ–±—Ä–∞–∂–µ–Ω|pdf|docx|epub|fb2|–∞—É–¥–∏–æ|–∫–Ω–∏–≥|–≤–∏–¥–µ–æ)", re.I)

_IMG_WORDS = r"(–∫–∞—Ä—Ç–∏–Ω\w+|–∏–∑–æ–±—Ä–∞–∂–µ–Ω\w+|—Ñ–æ—Ç–æ\w*|—Ä–∏—Å—É–Ω–∫\w+|–ª–æ–≥–æ—Ç–∏–ø\w*|–ª–æ–≥–æ\b|—ç–º–±–ª–µ–º\w+|–±—Ä–µ–Ω–¥\w+|—Ñ–∏—Ä–º–µ–Ω–Ω\w+|image|picture|img\b|logo|banner|poster|brand|emblem)"
_VID_WORDS = r"(–≤–∏–¥–µ–æ|—Ä–æ–ª–∏–∫\w*|–∞–Ω–∏–º–∞—Ü–∏\w*|shorts?|reels?|clip|video|vid\b)"


_PEOPLE_PROMPT_RE = re.compile(
    r"\b(—á–µ–ª–æ–≤–µ–∫|–ª—é–¥–∏|–º—É–∂—á–∏–Ω\w*|–∂–µ–Ω—â–∏–Ω\w*|–¥–µ–≤—É—à–∫\w*|–ø–∞—Ä–Ω\w*|—Ä–µ–±[–µ—ë]–Ω–æ–∫|–¥–µ—Ç\w*|"
    r"–¥–≤–æ—Ä–Ω–∏–∫\w*|–ø–æ–ª–∏—Ü–µ–π—Å–∫\w*|—Å–æ–ª–¥–∞—Ç\w*|–≤—Ä–∞—á\w*|–∞–∫—Ç[–µ—ë]—Ä\w*|–ø–µ–≤[–µ—ë]—Ü\w*|–ø–µ—Ä—Å–æ–Ω–∞–∂\w*|"
    r"–ª–∏—Ü–æ|–ø–æ—Ä—Ç—Ä–µ—Ç|—Å–µ–ª—Ñ–∏|human|person|people|man|woman|girl|boy|child|children|actor|singer|worker|janitor)\b",
    re.IGNORECASE,
)

def _prompt_likely_has_people(prompt: str) -> bool:
    return bool(_PEOPLE_PROMPT_RE.search(prompt or ""))

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

_CREATE_CMD = r"(—Å–¥–µ–ª–∞(–π|–π—Ç–µ|—Ç—å)|—Å–æ–∑–¥–∞(–π|–π—Ç–µ|—Ç—å)|—Å–≥–µ–Ω–µ—Ä–∏—Ä—É(–π|–π—Ç–µ)|–Ω–∞—Ä–∏—Å—É(–π|–π—Ç–µ)|–Ω—É–∂–Ω–æ\s+—Å–¥–µ–ª–∞—Ç—å|—Ö–æ—á—É\s+—Å–æ–∑–¥–∞—Ç—å|render|generate|create|make)"
_PREFIXES_VIDEO = [r"^" + _CREATE_CMD + r"\s+–≤–∏–¥–µ–æ", r"^video\b", r"^reels?\b", r"^shorts?\b"]
_PREFIXES_IMAGE = [r"^" + _CREATE_CMD + r"\s+(?:–∫–∞—Ä—Ç–∏–Ω\w+|–∏–∑–æ–±—Ä–∞–∂–µ–Ω\w+|—Ñ–æ—Ç–æ\w+|—Ä–∏—Å—É–Ω–∫\w+|–ª–æ–≥–æ—Ç–∏–ø\w*|–ª–æ–≥–æ\b|—ç–º–±–ª–µ–º\w+|–±—Ä–µ–Ω–¥\w+|—Ñ–∏—Ä–º–µ–Ω–Ω\w+)", r"^image\b", r"^picture\b", r"^img\b"]

def _strip_leading(s: str) -> str:
    return s.strip(" \n\t:‚Äî‚Äì-\"‚Äú‚Äù'¬´¬ª,.()[]")

def _after_match(text: str, match) -> str:
    return _strip_leading(text[match.end():])

def _looks_like_capability_question(tl: str) -> bool:
    if "?" in tl and re.search(_CAPABILITY_RE, tl):
        if not re.search(_CREATE_CMD, tl, re.I):
            return True
    m = re.search(r"\b(—Ç—ã|–≤—ã)?\s*–º–æ–∂(–µ—à—å|–Ω–æ|–µ—Ç–µ)\b", tl)
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

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ OpenAI helpers ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
def _oai_text_client():
    return oai_llm

def _pick_vision_model() -> str:
    try:
        mv = globals().get("OPENAI_VISION_MODEL")
        return (mv or OPENAI_MODEL).strip()
    except Exception:
        return OPENAI_MODEL

async def ask_openai_text(user_text: str, web_ctx: str = "", user_id: int | None = None, chat_id: int | None = None, extra_system: str = "") -> str:
    """
    –£–Ω–∏–≤–µ—Ä—Å–∞–ª—å–Ω—ã–π –∑–∞–ø—Ä–æ—Å –∫ LLM:
    - –ø–æ–¥–¥–µ—Ä–∂–∏–≤–∞–µ—Ç OpenRouter (—á–µ—Ä–µ–∑ OPENAI_API_KEY = sk-or-...);
    - –ø—Ä–∏–Ω—É–¥–∏—Ç–µ–ª—å–Ω–æ —à–ª—ë—Ç JSON –≤ UTF-8, —á—Ç–æ–±—ã –Ω–µ –±—ã–ª–æ ascii-–æ—à–∏–±–æ–∫;
    - –ª–æ–≥–∏—Ä—É–µ—Ç HTTP-—Å—Ç–∞—Ç—É—Å –∏ —Ç–µ–ª–æ –æ—à–∏–±–∫–∏ –≤ Render-–ª–æ–≥–∏;
    - –¥–µ–ª–∞–µ—Ç –¥–æ 3 –ø–æ–ø—ã—Ç–æ–∫ —Å –Ω–µ–±–æ–ª—å—à–æ–π –ø–∞—É–∑–æ–π.
    """
    user_text = (user_text or "").strip()
    if not user_text:
        return "–ü—É—Å—Ç–æ–π –∑–∞–ø—Ä–æ—Å."

    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + _current_date_system_text()}]
    if extra_system:
        messages.append({"role": "system", "content": str(extra_system)[:3000]})
    if web_ctx:
        messages.append({
            "role": "system",
            "content": f"–ö–æ–Ω—Ç–µ–∫—Å—Ç –∏–∑ –≤–µ–±-–ø–æ–∏—Å–∫–∞:\n{web_ctx}",
        })

    # –ö–æ—Ä–æ—Ç–∫–∞—è –ø–∞–º—è—Ç—å –¥–∏–∞–ª–æ–≥–∞: –ø–æ—Å–ª–µ–¥–Ω–∏–µ —Å–æ–æ–±—â–µ–Ω–∏—è –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è –∏ –±–æ—Ç–∞.
    # –≠—Ç–æ –ø–æ–∑–≤–æ–ª—è–µ—Ç –ø–æ–Ω–∏–º–∞—Ç—å –æ—Ç–≤–µ—Ç—ã –≤—Ä–æ–¥–µ ¬´–±–∏—Ç–∫–æ–∏–Ω¬ª –∫–∞–∫ –ø—Ä–æ–¥–æ–ª–∂–µ–Ω–∏–µ –ø—Ä–µ–¥—ã–¥—É—â–µ–≥–æ –≤–æ–ø—Ä–æ—Å–∞,
    # –∞ –Ω–µ –Ω–∞—á–∏–Ω–∞—Ç—å –Ω–æ–≤—É—é —Å–ø—Ä–∞–≤–∫—É —Å –æ–ø—Ä–µ–¥–µ–ª–µ–Ω–∏—è —Ç–µ—Ä–º–∏–Ω–∞.
    if CHAT_MEMORY_ENABLED and user_id and chat_id:
        messages.extend(_chat_memory_recent(user_id, chat_id, CHAT_MEMORY_MAX_MESSAGES))

    messages.append({"role": "user", "content": user_text})

    # ‚îÄ‚îÄ –ë–∞–∑–æ–≤—ã–π URL ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
    # –ï—Å–ª–∏ –∫–ª—é—á –æ—Ç OpenRouter –∏–ª–∏ TEXT_PROVIDER=openrouter ‚Äî —à–ª—ë–º –Ω–∞ OpenRouter
    provider = (TEXT_PROVIDER or "").strip().lower()
    if OPENAI_API_KEY.startswith("sk-or-") or provider == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
    else:
        base_url = (OPENAI_BASE_URL or "").strip() or "https://api.openai.com/v1"

    # ‚îÄ‚îÄ –ó–∞–≥–æ–ª–æ–≤–∫–∏ ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept-Charset": "utf-8",
    }

    # –°–ª—É–∂–µ–±–Ω—ã–µ –∑–∞–≥–æ–ª–æ–≤–∫–∏ OpenRouter
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

            # –õ–æ–≥–∏—Ä—É–µ–º –≤—Å—ë, —á—Ç–æ –Ω–µ 2xx
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
        "‚ö†Ô∏è –°–µ–π—á–∞—Å –Ω–µ –ø–æ–ª—É—á–∏–ª–æ—Å—å –ø–æ–ª—É—á–∏—Ç—å –æ—Ç–≤–µ—Ç –æ—Ç –º–æ–¥–µ–ª–∏. "
        "–Ø –Ω–∞ —Å–≤—è–∑–∏ ‚Äî –ø–æ–ø—Ä–æ–±—É–π –ø–µ—Ä–µ—Ñ–æ—Ä–º—É–ª–∏—Ä–æ–≤–∞—Ç—å –∑–∞–ø—Ä–æ—Å –∏–ª–∏ –ø–æ–≤—Ç–æ—Ä–∏—Ç—å —á—É—Ç—å –ø–æ–∑–∂–µ."
    )
    
async def ask_openai_vision(user_text: str, img_b64: str, mime: str) -> str:
    try:
        prompt = (user_text or "–û–ø–∏—à–∏, —á—Ç–æ –Ω–∞ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–∏ –∏ –∫–∞–∫–æ–π —Ç–∞–º —Ç–µ–∫—Å—Ç.").strip()
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
        return "–ù–µ —É–¥–∞–ª–æ—Å—å –ø—Ä–æ–∞–Ω–∞–ª–∏–∑–∏—Ä–æ–≤–∞—Ç—å –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ."


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ü–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å—Å–∫–∏–µ –Ω–∞—Å—Ç—Ä–æ–π–∫–∏ (TTS) ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
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


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ù–∞–¥—ë–∂–Ω—ã–π TTS —á–µ—Ä–µ–∑ REST (OGG/Opus) ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
def _tts_bytes_sync(text: str, audio_format: str = "opus", voice: str | None = None) -> bytes | None:
    try:
        if not OPENAI_TTS_KEY:
            return None
        if OPENAI_TTS_KEY.startswith("sk-or-"):
            log.error("TTS key looks like OpenRouter (sk-or-...). Provide a real OpenAI key in OPENAI_TTS_KEY.")
            return None
        url = f"{OPENAI_TTS_BASE_URL.rstrip('/')}/audio/speech"
        payload = {
            "model": OPENAI_TTS_MODEL,
            "voice": (voice or OPENAI_TTS_VOICE or "alloy"),
            "input": text,
            "response_format": audio_format  # mp3 for avatar, opus for Telegram voice
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
                f"üîá –û–∑–≤—É—á–∫–∞ –≤—ã–∫–ª—é—á–µ–Ω–∞ –¥–ª—è —ç—Ç–æ–≥–æ —Å–æ–æ–±—â–µ–Ω–∏—è: —Ç–µ–∫—Å—Ç –¥–ª–∏–Ω–Ω–µ–µ {TTS_MAX_CHARS} —Å–∏–º–≤–æ–ª–æ–≤."
            )
        return
    if not OPENAI_TTS_KEY:
        return
    try:
        with contextlib.suppress(Exception):
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VOICE)
        audio = await asyncio.to_thread(_tts_bytes_sync, text, "opus")
        if not audio:
            with contextlib.suppress(Exception):
                await update.effective_message.reply_text("üîá –ù–µ —É–¥–∞–ª–æ—Å—å —Å–∏–Ω—Ç–µ–∑–∏—Ä–æ–≤–∞—Ç—å –≥–æ–ª–æ—Å.")
            return
        bio = BytesIO(audio); bio.seek(0); bio.name = "say.ogg"
        await update.effective_message.reply_voice(voice=InputFile(bio), caption=(text if TTS_VOICE_CAPTION else None))
    except Exception as e:
        log.exception("maybe_tts_reply error: %s", e)

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, True)
    await update.effective_message.reply_text(f"üîä –û–∑–≤—É—á–∫–∞ –≤–∫–ª—é—á–µ–Ω–∞. –õ–∏–º–∏—Ç {TTS_MAX_CHARS} —Å–∏–º–≤–æ–ª–æ–≤ –Ω–∞ –æ—Ç–≤–µ—Ç.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _tts_set(update.effective_user.id, False)
    await update.effective_message.reply_text("üîà –û–∑–≤—É—á–∫–∞ –≤—ã–∫–ª—é—á–µ–Ω–∞.")

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ Speech-to-Text (STT) ‚Ä¢ OpenAI Whisper/4o-mini-transcribe ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
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

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –•–µ–Ω–¥–ª–µ—Ä –≥–æ–ª–æ—Å–æ–≤—ã—Ö/–∞—É–¥–∏–æ ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    voice = getattr(msg, "voice", None)
    audio = getattr(msg, "audio", None)
    media = voice or audio
    if not media:
        await msg.reply_text("–ù–µ –Ω–∞—à—ë–ª –≥–æ–ª–æ—Å–æ–≤–æ–π —Ñ–∞–π–ª.")
        return

    # –°–∫–∞—á–∏–≤–∞–µ–º —Ñ–∞–π–ª
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
        await msg.reply_text("–ù–µ —É–¥–∞–ª–æ—Å—å —Å–∫–∞—á–∞—Ç—å –≥–æ–ª–æ—Å–æ–≤–æ–µ —Å–æ–æ–±—â–µ–Ω–∏–µ. –ü–æ–ø—Ä–æ–±—É–π—Ç–µ –æ—Ç–ø—Ä–∞–≤–∏—Ç—å –µ–≥–æ –µ—â—ë —Ä–∞–∑, –ª—É—á—à–µ –Ω–µ –ø–µ—Ä–µ—Å—ã–ª–∞—è, –∞ –∑–∞–≥—Ä—É–∑–∏–≤ –Ω–∞–ø—Ä—è–º—É—é.")
        return

    # –ï—Å–ª–∏ –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å –Ω–∞ —à–∞–≥–µ –≤—ã–±–æ—Ä–∞ –≥–æ–ª–æ—Å–∞ –ø—Ä–∏—Å–ª–∞–ª voice/audio, –∏—Å–ø–æ–ª—å–∑—É–µ–º —Ä–µ–∞–ª—å–Ω—ã–π –≥–æ–ª–æ—Å –±–µ–∑ TTS.
    if context.user_data.get("awaiting_avatar_voice_choice"):
        context.user_data.pop("awaiting_avatar_voice_choice", None)
        context.user_data["awaiting_avatar_script"] = True

    # –ï—Å–ª–∏ –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å –Ω–∞–∂–∞–ª ¬´–ì–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä¬ª, voice/audio —Å—Ç–∞–Ω–æ–≤–∏—Ç—Å—è —Ä–µ—á—å—é –¥–ª—è –∑–∞–≥—Ä—É–∂–µ–Ω–Ω–æ–≥–æ –ø–æ—Ä—Ç—Ä–µ—Ç–∞.
    if context.user_data.get("awaiting_avatar_script"):
        img = _get_cached_photo(update.effective_user.id)
        if not img:
            _clear_avatar_wait(context)
            await msg.reply_text("–°–Ω–∞—á–∞–ª–∞ –∑–∞–≥—Ä—É–∑–∏—Ç–µ –ø–æ—Ä—Ç—Ä–µ—Ç —á–µ–ª–æ–≤–µ–∫–∞, –∑–∞—Ç–µ–º –Ω–∞–∂–º–∏—Ç–µ üó£ –ì–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä.")
            return
        _clear_avatar_wait(context)
        await _start_talking_avatar(
            update, context, img,
            audio_bytes=raw,
            audio_filename=filename,
            audio_file_url=getattr(tg_file, "file_path", "") or "",
            audio_mime=mime,
        )
        return

    # STT
    transcript = await _stt_transcribe_bytes(filename, raw)
    if not transcript:
        await msg.reply_text("–û—à–∏–±–∫–∞ –ø—Ä–∏ —Ä–∞—Å–ø–æ–∑–Ω–∞–≤–∞–Ω–∏–∏ —Ä–µ—á–∏.")
        return

    transcript = transcript.strip()

    # –ü–æ —É–º–æ–ª—á–∞–Ω–∏—é –ù–ï –ø–æ–∫–∞–∑—ã–≤–∞–µ–º –æ—Ç–¥–µ–ª—å–Ω—É—é —Ä–∞—Å—à–∏—Ñ—Ä–æ–≤–∫—É voice, —á—Ç–æ–±—ã –Ω–µ –±—ã–ª–æ 3 —Å–æ–æ–±—â–µ–Ω–∏–π:
    # 1) —Ç–µ–∫—Å—Ç–æ–≤—ã–π –æ—Ç–≤–µ—Ç, 2) voice-–æ–∑–≤—É—á–∫–∞, 3) –¥—É–±–ª—å —Ä–∞—Å—à–∏—Ñ—Ä–æ–≤–∫–∏.
    if STT_ECHO_TRANSCRIPT:
        with contextlib.suppress(Exception):
            await msg.reply_text(f"üó£Ô∏è –†–∞—Å–ø–æ–∑–Ω–∞–ª: {transcript}")

    # ‚Äî‚Äî‚Äî –ö–õ–Æ–ß–ï–í–û–ô –ú–û–ú–ï–ù–¢ ‚Äî‚Äî‚Äî
    # –ë–æ–ª—å—à–µ –ù–ï —Å–æ–∑–¥–∞—ë–º —Ñ–µ–π–∫–æ–≤—ã–π Update, –Ω–µ –ª–µ–∑–µ–º –≤ Message.text ‚Äî —ç—Ç–æ –∑–∞–ø—Ä–µ—â–µ–Ω–æ –≤ Telegram API
    # –¢–µ–ø–µ—Ä—å –º—ã –∏—Å–ø–æ–ª—å–∑—É–µ–º –±–µ–∑–æ–ø–∞—Å–Ω—ã–π –ø—Ä–æ–∫—Å–∏-–º–µ—Ç–æ–¥, –∫–æ—Ç–æ—Ä—ã–π —Å–æ–∑–¥–∞—ë—Ç –≤—Ä–µ–º–µ–Ω–Ω—ã–π message-–æ–±—ä–µ–∫—Ç
    try:
        await on_text_with_text(update, context, transcript)
    except Exception as e:
        log.exception("Voice->text handler error: %s", e)
        await msg.reply_text("–£–ø—Å, –ø—Ä–æ–∏–∑–æ—à–ª–∞ –æ—à–∏–±–∫–∞. –Ø —É–∂–µ —Ä–∞–∑–±–∏—Ä–∞—é—Å—å.")
        
# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ò–∑–≤–ª–µ—á–µ–Ω–∏–µ —Ç–µ–∫—Å—Ç–∞ –∏–∑ –¥–æ–∫—É–º–µ–Ω—Ç–æ–≤ ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
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


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –°—É–º–º–∞—Ä–∏–∑–∞—Ü–∏—è –¥–ª–∏–Ω–Ω—ã—Ö —Ç–µ–∫—Å—Ç–æ–≤ ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
async def _summarize_chunk(text: str, query: str | None = None) -> str:
    prefix = "–°—É–º–º–∏—Ä—É–π –∫—Ä–∞—Ç–∫–æ –ø–æ –ø—É–Ω–∫—Ç–∞–º –æ—Å–Ω–æ–≤–Ω–æ–µ –∏–∑ —Ñ—Ä–∞–≥–º–µ–Ω—Ç–∞ –¥–æ–∫—É–º–µ–Ω—Ç–∞ –Ω–∞ —Ä—É—Å—Å–∫–æ–º:\n"
    if query:
        prefix = (f"–°—É–º–º–∏—Ä—É–π —Ñ—Ä–∞–≥–º–µ–Ω—Ç —Å —É—á—ë—Ç–æ–º —Ü–µ–ª–∏: {query}\n"
                  f"–î–∞–π –æ—Å–Ω–æ–≤–Ω—ã–µ —Ç–µ–∑–∏—Å—ã, —Ñ–∞–∫—Ç—ã, —Ü–∏—Ñ—Ä—ã. –†—É—Å—Å–∫–∏–π —è–∑—ã–∫.\n")
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
    combined = "\n\n".join(f"- –§—Ä–∞–≥–º–µ–Ω—Ç {idx+1}:\n{s}" for idx, s in enumerate(partials))
    final_prompt = ("–û–±—ä–µ–¥–∏–Ω–∏ —Ç–µ–∑–∏—Å—ã –ø–æ —Ñ—Ä–∞–≥–º–µ–Ω—Ç–∞–º –≤ —Ü–µ–ª—å–Ω–æ–µ —Ä–µ–∑—é–º–µ –¥–æ–∫—É–º–µ–Ω—Ç–∞: 1) 5‚Äì10 –≥–ª–∞–≤–Ω—ã—Ö –ø—É–Ω–∫—Ç–æ–≤; "
                    "2) –∫–ª—é—á–µ–≤—ã–µ —Ü–∏—Ñ—Ä—ã/—Å—Ä–æ–∫–∏; 3) –≤—ã–≤–æ–¥/—Ä–µ–∫–æ–º–µ–Ω–¥–∞—Ü–∏–∏. –†—É—Å—Å–∫–∏–π —è–∑—ã–∫.\n\n" + combined)
    return await ask_openai_text(final_prompt)


# ======= –ê–Ω–∞–ª–∏–∑ –¥–æ–∫—É–º–µ–Ω—Ç–æ–≤ (PDF/EPUB/DOCX/FB2/TXT) =======
async def on_doc_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document:
            return
        doc = update.message.document
        tg_file = await doc.get_file()
        data = await tg_file.download_as_bytearray()
        text, kind = extract_text_from_document(bytes(data), doc.file_name or "file")
        if not text.strip():
            await update.effective_message.reply_text(f"–ù–µ —É–¥–∞–ª–æ—Å—å –∏–∑–≤–ª–µ—á—å —Ç–µ–∫—Å—Ç –∏–∑ {kind}.")
            return
        caption = (update.message.caption or "").strip()
        goal = caption or None
        if _should_route_medical(context, update.effective_user.id, caption, doc.file_name or "file"):
            await _medical_analyze_text(update, context, text, goal=goal)
            _clear_medicine_wait(context)
            with contextlib.suppress(Exception):
                _mode_track_set(update.effective_user.id, "")
            return

        await update.effective_message.reply_text(f"üìÑ –ò–∑–≤–ª–µ–∫–∞—é —Ç–µ–∫—Å—Ç ({kind}), –≥–æ—Ç–æ–≤–ª—é –∫–æ–Ω—Å–ø–µ–∫—Ç‚Ä¶")
        summary = await summarize_long_text(text, query=goal)
        summary = summary or "–ì–æ—Ç–æ–≤–æ."
        await update.effective_message.reply_text(summary)
        await maybe_tts_reply(update, context, summary[:TTS_MAX_CHARS])
    except Exception as e:
        log.exception("on_doc_analyze error: %s", e)
    # –Ω–∏—á–µ–≥–æ –Ω–µ –±—Ä–æ—Å–∞–µ–º –Ω–∞—Ä—É–∂—É



# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ OpenAI Images (–≥–µ–Ω–µ—Ä–∞—Ü–∏—è –∫–∞—Ä—Ç–∏–Ω–æ–∫) ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
async def _generate_openai_image_bytes(prompt: str) -> bytes | None:
    try:
        try:
            resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", quality=OPENAI_IMAGE_QUALITY, n=1)
        except Exception:
            # Compatibility with proxies that do not expose the quality argument.
            resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
        b64 = resp.data[0].b64_json
        return base64.b64decode(b64) if b64 else None
    except Exception as e:
        log.exception("OpenAI image generation error: %s", e)
        return None

async def _do_img_generate(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str) -> bool:
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        img_bytes = await _generate_openai_image_bytes(prompt)
        if not img_bytes:
            await update.effective_message.reply_text("–ù–µ —É–¥–∞–ª–æ—Å—å —Å–æ–∑–¥–∞—Ç—å –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ.")
            return False
        await update.effective_message.reply_photo(
            photo=img_bytes,
            caption=f"–ì–æ—Ç–æ–≤–æ ‚úÖ\n–î–≤–∏–∂–æ–∫: OpenAI Images\n–ó–∞–ø—Ä–æ—Å: {prompt}",
        )
        return True
    except Exception as e:
        log.exception("IMG gen error: %s", e)
        await update.effective_message.reply_text("–ù–µ —É–¥–∞–ª–æ—Å—å —Å–æ–∑–¥–∞—Ç—å –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ.")
        return False


def _is_text_sensitive_image_prompt(prompt: str) -> bool:
    return bool(re.search(
        r"(logo|brand|branding|label|poster|flyer|banner|packag|box|bottle|menu|sign|screen|ui|ux|interface|"
        r"–ª–æ–≥–æ—Ç–∏–ø|–ª–æ–≥–æ|–±—Ä–µ–Ω–¥|—ç—Ç–∏–∫–µ—Ç|—É–ø–∞–∫–æ–≤|–±—É—Ç—ã–ª|–∫–æ—Ä–æ–±|–ø–ª–∞–∫–∞—Ç|–±–∞–Ω–Ω–µ—Ä|—Ñ–ª–∞–µ—Ä|–º–µ–Ω—é|–≤—ã–≤–µ—Å–∫|—ç–∫—Ä–∞–Ω|–∏–Ω—Ç–µ—Ä—Ñ–µ–π—Å)",
        prompt or "",
        re.I,
    ))


def _is_atmospheric_image_prompt(prompt: str) -> bool:
    return bool(re.search(
        r"(cinematic|editorial|mood|atmospher|luxury|premium|fashion|concept art|fantasy|epic|dramatic|"
        r"–∫–∏–Ω–æ—à–Ω|–∫–∏–Ω–µ–º–∞—Ç–æ–≥—Ä–∞—Ñ|–∞—Ç–º–æ—Å—Ñ–µ—Ä|–ª—é–∫—Å|–ø—Ä–µ–º–∏—É–º|–º—É–¥–±–æ—Ä–¥|—Ñ—ç—à–Ω|–∞—Ä—Ç|–∫–æ–Ω—Ü–µ–ø—Ç|—ç–ø–∏—á|–¥—Ä–∞–º–∞—Ç)",
        prompt or "",
        re.I,
    ))


def _resolve_general_image_engine(prompt: str, requested_engine: str = "auto") -> tuple[str, str]:
    requested_engine = (requested_engine or "auto").strip().lower()
    if requested_engine == "openai":
        return ("openai", "–ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å –≤—ã–±—Ä–∞–ª —Ç–æ—á–Ω—ã–π –¥–≤–∏–∂–æ–∫")
    if requested_engine == "midjourney":
        return ("midjourney", "–ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å –≤—ã–±—Ä–∞–ª —Ö—É–¥–æ–∂–µ—Å—Ç–≤–µ–Ω–Ω—ã–π –¥–≤–∏–∂–æ–∫")

    if _is_text_sensitive_image_prompt(prompt):
        return ("openai", "–æ–±–Ω–∞—Ä—É–∂–µ–Ω –∑–∞–ø—Ä–æ—Å –Ω–∞ —Ç–µ–∫—Å—Ç, –ª–æ–≥–æ—Ç–∏–ø, —É–ø–∞–∫–æ–≤–∫—É –∏–ª–∏ —Ç–æ—á–Ω—É—é –≥—Ä–∞—Ñ–∏–∫—É")
    if _is_atmospheric_image_prompt(prompt) and MIDJOURNEY_ENABLED and COMET_API_KEY:
        return ("midjourney", "–æ–±–Ω–∞—Ä—É–∂–µ–Ω –∞—Ç–º–æ—Å—Ñ–µ—Ä–Ω—ã–π/–∫–∏–Ω–µ–º–∞—Ç–æ–≥—Ä–∞—Ñ–∏—á–Ω—ã–π —Ö—É–¥–æ–∂–µ—Å—Ç–≤–µ–Ω–Ω—ã–π –∑–∞–ø—Ä–æ—Å")
    return ("openai", "—É–Ω–∏–≤–µ—Ä—Å–∞–ª—å–Ω—ã–π —Ä–µ–∂–∏–º –ø–æ —É–º–æ–ª—á–∞–Ω–∏—é")


def _image_engine_price_label(engine: str) -> str:
    engine = (engine or "").lower()
    cost = MIDJOURNEY_UNIT_COST_USD if engine == "midjourney" else IMG_COST_USD
    return f"{_retail_credits(cost)} –∫—Ä."


def _image_engine_choice_kb(aid: str, prompt: str = "") -> InlineKeyboardMarkup:
    auto_engine, _ = _resolve_general_image_engine(prompt, "auto")
    auto_title = "Midjourney" if auto_engine == "midjourney" else "OpenAI"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"‚ú® –ê–≤—Ç–æ: {auto_title} ¬∑ {_image_engine_price_label(auto_engine)}", callback_data=f"chooseimg:auto:{aid}")],
        [InlineKeyboardButton(f"üñº OpenAI Images ¬∑ {_image_engine_price_label('openai')}", callback_data=f"chooseimg:openai:{aid}")],
        [InlineKeyboardButton(f"üé® Midjourney ¬∑ {_image_engine_price_label('midjourney')}", callback_data=f"chooseimg:midjourney:{aid}")],
    ])


async def _ask_image_engine_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    aid = _new_aid()
    _pending_actions[aid] = {"kind": "image_generate", "prompt": prompt}
    mid_note = "–¥–æ—Å—Ç—É–ø–µ–Ω" if MIDJOURNEY_ENABLED and COMET_API_KEY else "–Ω–µ–¥–æ—Å—Ç—É–ø–µ–Ω —Å–µ–π—á–∞—Å"
    msg = (
        "–ö–∞–∫–æ–π –¥–≤–∏–∂–æ–∫ –∏—Å–ø–æ–ª—å–∑–æ–≤–∞—Ç—å –¥–ª—è –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è?\n"
        f"–ó–∞–ø—Ä–æ—Å: ¬´{prompt}¬ª\n\n"
        "‚ú® –ê–≤—Ç–æ ‚Äî –±–æ—Ç —Å–∞–º –≤—ã–±–µ—Ä–µ—Ç –ª—É—á—à–∏–π –º–∞—Ä—à—Ä—É—Ç –ø–æ–¥ –∑–∞–¥–∞—á—É. –û–±—ã—á–Ω–æ —ç—Ç–æ —Å–∞–º—ã–π —É–¥–æ–±–Ω—ã–π –≤–∞—Ä–∏–∞–Ω—Ç.\n"
        "üñº OpenAI Images ‚Äî –∫–æ–≥–¥–∞ –Ω—É–∂–Ω–∞ —Ç–æ—á–Ω–æ—Å—Ç—å: –ø—Ä–µ–¥–º–µ—Ç—ã, –ø—Ä–æ–¥—É–∫—Ç—ã, –±–∞–Ω–Ω–µ—Ä—ã, –ª–æ–≥–æ—Ç–∏–ø—ã, –ø–æ–Ω—è—Ç–Ω–∞—è –∫–æ–º–ø–æ–∑–∏—Ü–∏—è, —Ç–µ–∫—Å—Ç–æ–≤—ã–µ —ç–ª–µ–º–µ–Ω—Ç—ã –∏ –∫–æ–º–º–µ—Ä—á–µ—Å–∫–∏–µ –º–∞–∫–µ—Ç—ã.\n"
        f"üé® Midjourney ‚Äî –∫–æ–≥–¥–∞ –Ω—É–∂–µ–Ω –∞—Ç–º–æ—Å—Ñ–µ—Ä–Ω—ã–π, —Ö—É–¥–æ–∂–µ—Å—Ç–≤–µ–Ω–Ω—ã–π, –∫–∏–Ω–µ–º–∞—Ç–æ–≥—Ä–∞—Ñ–∏—á–Ω—ã–π –∏–ª–∏ fashion/editorial —Ä–µ–∑—É–ª—å—Ç–∞—Ç. –°—Ç–∞—Ç—É—Å —Å–µ–π—á–∞—Å: {mid_note}.\n\n"
        "–ü–æ–¥—Å–∫–∞–∑–∫–∞: /img ‚Äî –±—ã—Å—Ç—Ä—ã–π –∑–∞–ø—É—Å–∫ —á–µ—Ä–µ–∑ OpenAI Images, /mj ‚Äî –ø—Ä—è–º–æ–π –∑–∞–ø—É—Å–∫ Midjourney."
    )
    await update.effective_message.reply_text(msg, reply_markup=_image_engine_choice_kb(aid, prompt))


async def _run_selected_image_generation(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, requested_engine: str) -> bool:
    engine, reason = _resolve_general_image_engine(prompt, requested_engine)
    provider_cost = MIDJOURNEY_UNIT_COST_USD if engine == "midjourney" else IMG_COST_USD
    engine_title = "Midjourney" if engine == "midjourney" else "OpenAI Images"

    async def _go():
        try:
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        except Exception:
            pass
        try:
            if engine == "midjourney":
                if not MIDJOURNEY_ENABLED:
                    await update.effective_message.reply_text("‚ùå Midjourney –æ—Ç–∫–ª—é—á—ë–Ω –Ω–∞—Å—Ç—Ä–æ–π–∫–æ–π MIDJOURNEY_ENABLED=0.")
                    return False
                if not COMET_API_KEY:
                    await update.effective_message.reply_text("‚ùå Midjourney —Å–µ–π—á–∞—Å –Ω–µ–¥–æ—Å—Ç—É–ø–µ–Ω: –Ω–µ –∑–∞–¥–∞–Ω COMET_API_KEY.")
                    return False
                await update.effective_message.reply_text(f"üé® –î–≤–∏–∂–æ–∫: {engine_title}. –ó–∞–ø—É—Å–∫–∞—é –≥–µ–Ω–µ—Ä–∞—Ü–∏—é‚Ä¶")
                img, task_id = await _midjourney_generate_image_bytes(prompt)
                if not img:
                    await update.effective_message.reply_text("‚ùå Midjourney –Ω–µ –≤–µ—Ä–Ω—É–ª –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ.")
                    return False
                bio = BytesIO(img)
                bio.name = f"midjourney_{task_id}.jpg"
                caption = f"–ì–æ—Ç–æ–≤–æ ‚úÖ\n–î–≤–∏–∂–æ–∫: {engine_title}\n–ü—Ä–∏—á–∏–Ω–∞ –≤—ã–±–æ—Ä–∞: {reason}\n–ó–∞–ø—Ä–æ—Å: {prompt}"
                try:
                    await update.effective_message.reply_photo(photo=InputFile(bio), caption=caption[:1024])
                except Exception:
                    bio.seek(0)
                    await update.effective_message.reply_document(document=InputFile(bio), caption=caption[:1024])
                return True

            await update.effective_message.reply_text(f"üñº –î–≤–∏–∂–æ–∫: {engine_title}. –ó–∞–ø—É—Å–∫–∞—é –≥–µ–Ω–µ—Ä–∞—Ü–∏—é‚Ä¶")
            img = await _generate_openai_image_bytes(prompt)
            if not img:
                await update.effective_message.reply_text("–ù–µ —É–¥–∞–ª–æ—Å—å —Å–æ–∑–¥–∞—Ç—å –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ —á–µ—Ä–µ–∑ OpenAI Images.")
                return False
            caption = f"–ì–æ—Ç–æ–≤–æ ‚úÖ\n–î–≤–∏–∂–æ–∫: {engine_title}\n–ü—Ä–∏—á–∏–Ω–∞ –≤—ã–±–æ—Ä–∞: {reason}\n–ó–∞–ø—Ä–æ—Å: {prompt}"
            await update.effective_message.reply_photo(photo=img, caption=caption[:1024])
            return True
        except Exception as e:
            log.exception("Selected image generation failed: %s", e)
            await update.effective_message.reply_text(f"‚ùå –û—à–∏–±–∫–∞ –≥–µ–Ω–µ—Ä–∞—Ü–∏–∏ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è ({engine_title}). –ü–æ–ø—Ä–æ–±—É–π—Ç–µ –µ—â—ë —Ä–∞–∑ –ø–æ–∑–∂–µ.")
            return False

    await _try_pay_then_do(
        update,
        context,
        update.effective_user.id,
        "img",
        provider_cost,
        _go,
        remember_kind="img_generate",
        remember_payload={"prompt": prompt[:1000], "requested_engine": requested_engine, "resolved_engine": engine},
    )
    return True

async def _luma_generate_image_bytes(prompt: str) -> bytes | None:
    if not LUMA_IMG_BASE_URL or not LUMA_API_KEY:
        # —Ñ–æ–ª–±—ç–∫: OpenAI Images
        try:
            resp = oai_img.images.generate(model=IMAGES_MODEL, prompt=prompt, size="1024x1024", n=1)
            return base64.b64decode(resp.data[0].b64_json)
        except Exception as e:
            log.exception("OpenAI images fallback error: %s", e)
            return None
    try:
        # –ü—Ä–∏–º–µ—Ä–Ω—ã–π —ç–Ω–¥–ø–æ–∏–Ω—Ç; –µ—Å–ª–∏ —É —Ç–µ–±—è –¥—Ä—É–≥–æ–π ‚Äî –∑–∞–º–µ–Ω–∏ path/–ø–æ–ª—è –ø–æ–¥ —Å–≤–æ–π –∞–∫–∫–∞—É–Ω—Ç.
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
            await update.effective_message.reply_text("–ù–µ —É–¥–∞–ª–æ—Å—å —Å–æ–∑–¥–∞—Ç—å –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ.")
            return False
        await update.effective_message.reply_photo(photo=img, caption=f"üñå –ì–æ—Ç–æ–≤–æ ‚úÖ\n–ó–∞–ø—Ä–æ—Å: {prompt}")
        return True
    await _try_pay_then_do(update, context, update.effective_user.id, "img", IMG_COST_USD, _go,
                           remember_kind="luma_img", remember_payload={"prompt": prompt})


async def _midjourney_generate_image_bytes(prompt: str) -> tuple[bytes | None, str]:
    """Create a Midjourney grid through CometAPI and return bytes plus task id."""
    if not MIDJOURNEY_ENABLED:
        raise RuntimeError("Midjourney –æ—Ç–∫–ª—é—á—ë–Ω –Ω–∞—Å—Ç—Ä–æ–π–∫–æ–π MIDJOURNEY_ENABLED=0")
    if not COMET_API_KEY:
        raise RuntimeError("–î–ª—è Midjourney –Ω—É–∂–µ–Ω COMET_API_KEY")
    prompt = re.sub(r"\s+", " ", (prompt or "").strip())
    if not prompt:
        raise RuntimeError("–ü—É—Å—Ç–æ–π –ø—Ä–æ–º–ø—Ç Midjourney")
    # Add a default version only when the user did not specify one.
    if MIDJOURNEY_DEFAULT_VERSION and not re.search(r"(?:^|\s)--v(?:ersion)?\s+", prompt, re.I):
        prompt = f"{prompt} --v {MIDJOURNEY_DEFAULT_VERSION}"
    mode = MIDJOURNEY_MODE.upper()
    payload = {
        "botType": "MID_JOURNEY",
        "prompt": prompt,
        "accountFilter": {"modes": [mode]},
    }
    headers = {
        "Authorization": f"Bearer {COMET_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    create_paths = []
    for path in (MIDJOURNEY_CREATE_PATH, f"{_MJ_PREFIX}/mj/submit/imagine", "/mj/submit/imagine"):
        if path and path not in create_paths:
            create_paths.append(path)
    last_err = ""
    async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
        task_id = ""
        for path in create_paths:
            try:
                r = await client.post(f"{COMET_BASE_URL}{path}", headers=headers, json=payload)
                if r.status_code >= 400:
                    last_err = f"POST {path} ‚Üí {r.status_code}: {_api_error_preview(r)}"
                    continue
                js = r.json() or {}
                code = js.get("code")
                task_id = str(js.get("result") or js.get("taskId") or js.get("task_id") or js.get("id") or "").strip()
                if task_id and (code in (None, 1, "1", 200, "200") or str(js.get("description", "")).lower().find("success") >= 0):
                    break
                last_err = f"POST {path}: –Ω–µ—Ç task id: {json.dumps(js, ensure_ascii=False)[:700]}"
            except Exception as e:
                last_err = f"POST {path}: {e}"
        if not task_id:
            raise RuntimeError(last_err or "Midjourney –Ω–µ –≤–µ—Ä–Ω—É–ª task id")

        started = time.time()
        status_paths = []
        for path in (MIDJOURNEY_STATUS_PATH, "/mj/task/{id}/fetch"):
            if path and path not in status_paths:
                status_paths.append(path)
        last = ""
        while time.time() - started < MIDJOURNEY_TIMEOUT_S:
            for path in status_paths:
                try:
                    rr = await client.get(f"{COMET_BASE_URL}{path.format(id=task_id)}", headers=headers)
                    if rr.status_code >= 400:
                        last = f"GET {path} ‚Üí {rr.status_code}: {_api_error_preview(rr)}"
                        continue
                    js = rr.json() or {}
                    status = str(js.get("status") or js.get("state") or "").upper()
                    image_url = (
                        js.get("imageUrl") or js.get("image_url")
                        or _extract_first_url(js.get("output"))
                        or _extract_first_url(js.get("result"))
                        or _extract_first_url(js.get("data"))
                    )
                    if status == "SUCCESS" and image_url:
                        img_resp = await client.get(str(image_url), headers={"Accept": "image/*"})
                        img_resp.raise_for_status()
                        if not img_resp.content:
                            raise RuntimeError("Midjourney –≤–µ—Ä–Ω—É–ª –ø—É—Å—Ç–æ–µ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ")
                        return img_resp.content, task_id
                    if status in ("FAILURE", "FAILED", "ERROR", "CANCELLED", "CANCELED"):
                        desc = js.get("failReason") or js.get("description") or js.get("error") or js
                        raise RuntimeError(f"Midjourney task failed: {str(desc)[:900]}")
                    if status == "MODAL":
                        raise RuntimeError("Midjourney –∑–∞–ø—Ä–æ—Å–∏–ª –¥–æ–ø–æ–ª–Ω–∏—Ç–µ–ª—å–Ω—ã–π modal-–≤–≤–æ–¥; –¥–ª—è –æ–±—ã—á–Ω–æ–π –≥–µ–Ω–µ—Ä–∞—Ü–∏–∏ –∏–∑–º–µ–Ω–∏—Ç–µ –ø—Ä–æ–º–ø—Ç")
                    last = json.dumps(js, ensure_ascii=False)[:900]
                except RuntimeError:
                    raise
                except Exception as e:
                    last = str(e)
            await asyncio.sleep(MIDJOURNEY_POLL_DELAY_S)
        raise RuntimeError(f"Midjourney timeout. –ü–æ—Å–ª–µ–¥–Ω–∏–π –æ—Ç–≤–µ—Ç: {last[:900]}")


async def _start_midjourney_image(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    prompt = (prompt or "").strip()
    if not prompt:
        context.user_data["awaiting_midjourney_prompt"] = True
        await update.effective_message.reply_text(
            "üé® –û–ø–∏—à–∏—Ç–µ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ –¥–ª—è Midjourney. –ú–æ–∂–Ω–æ –¥–æ–±–∞–≤–∏—Ç—å –ø–∞—Ä–∞–º–µ—Ç—Ä—ã --ar, --stylize –∏ --v."
        )
        return False

    async def _go():
        await update.effective_message.reply_text(
            f"üé® Midjourney {MIDJOURNEY_MODE.upper()}: –∑–∞–¥–∞—á–∞ –ø—Ä–∏–Ω—è—Ç–∞, –æ–∂–∏–¥–∞—é –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ‚Ä¶"
        )
        try:
            img, task_id = await _midjourney_generate_image_bytes(prompt)
            if not img:
                return False
            bio = BytesIO(img); bio.name = f"midjourney_{task_id}.jpg"
            try:
                await update.effective_message.reply_photo(photo=InputFile(bio), caption=f"üé® Midjourney –≥–æ—Ç–æ–≤ ‚úÖ\n{prompt[:700]}")
            except Exception:
                bio.seek(0)
                await update.effective_message.reply_document(document=InputFile(bio), caption="üé® Midjourney –≥–æ—Ç–æ–≤ ‚úÖ")
            return True
        except Exception as e:
            log.exception("Midjourney failed: %s", e)
            await update.effective_message.reply_text(f"‚ùå Midjourney: {str(e)[:900]}")
            return False

    await _try_pay_then_do(
        update, context, update.effective_user.id,
        "img", MIDJOURNEY_UNIT_COST_USD, _go,
        remember_kind="midjourney_imagine",
        remember_payload={"prompt": prompt[:1000], "mode": MIDJOURNEY_MODE},
    )
    return True


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ Image retouch / own-image watermark cleanup ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
_RETOUCH_TERMS_RE = re.compile(
    r"(–≤–æ–¥—è–Ω(?:–æ–π|–æ–≥–æ|–æ–º—É|—ã–º|–æ–º)\s+–∑–Ω–∞–∫|–≤–æ–¥–Ω(?:—ã–π|–æ–≥–æ|–æ–º—É|—ã–º|–æ–º)\s+–∑–Ω–∞–∫|watermark|"
    r"–≤–∞—Ç–µ—Ä–º–∞—Ä–∫|—Ä–µ—Ç—É—à|—Ä–µ—Ç—É—à–∏—Ä|–∑–∞—Ä–µ—Ç—É—à|–≤–µ—Ç–æ—à—å|"
    r"(?:—É–±–µ—Ä(?:–∏|–∏—Ç–µ|—É)|—É–¥–∞–ª(?:–∏|–∏—Ç–µ|–∏—Ç—å)|—Å–æ—Ç—Ä(?:–∏|–∏—Ç–µ)|–∑–∞–º–∞–∂—å|–∑–∞–º–∞–∑–∞—Ç—å)\s+.{0,80}"
    r"(?:–≤–æ–¥—è–Ω(?:–æ–π|–æ–≥–æ|–æ–º—É|—ã–º|–æ–º)\s+–∑–Ω–∞–∫|–≤–æ–¥–Ω(?:—ã–π|–æ–≥–æ|–æ–º—É|—ã–º|–æ–º)\s+–∑–Ω–∞–∫|watermark|–Ω–∞–¥–ø–∏—Å—å|—Ç–µ–∫—Å—Ç|–ª–æ–≥–æ—Ç–∏–ø|–ª–æ–≥–æ|—ç–º–±–ª–µ–º|–ª–∏—à–Ω(?:–∏–π|—é—é|–µ–µ|–∏–µ)\s+–æ–±—ä–µ–∫—Ç)|"
    r"–æ—á–∏—Å—Ç(?:–∏|–∏—Ç–µ|–∏—Ç—å)\s+.{0,40}(?:—Ñ–æ—Ç–æ|–∏–∑–æ–±—Ä–∞–∂–µ–Ω|–∫–∞—Ä—Ç–∏–Ω–∫|photo|image)|"
    r"–ª–∏—à–Ω(?:–∏–π|—é—é|–µ–µ|–∏–µ)\s+(?:–Ω–∞–¥–ø–∏—Å—å|–æ–±—ä–µ–∫—Ç|–ª–æ–≥–æ—Ç–∏–ø|—Ç–µ–∫—Å—Ç)|"
    r"–Ω–∞–¥–ø–∏—Å—å\s+–Ω–∞\s+—Ñ–æ—Ç–æ|—Ç–µ–∫—Å—Ç\s+–Ω–∞\s+—Ñ–æ—Ç–æ|–ª–æ–≥–æ—Ç–∏–ø\s+–Ω–∞\s+—Ñ–æ—Ç–æ|"
    r"remove\s+(?:watermark|text|logo|object)|clean\s+(?:image|photo))",
    re.IGNORECASE,
)

_OWN_IMAGE_CONFIRM_RE = re.compile(
    r"(–º–æ[–π—è—ë–∏–µ]|—Å–≤–æ[–π—è—ë–µ–∏—Ö]|—Å–æ–±—Å—Ç–≤–µ–Ω–Ω|–º–æ–π\s+—Ñ–∞–π–ª|–º–æ–π\s+–º–∞–∫–µ—Ç|–º–æ—è\s+—Ñ–æ—Ç|"
    r"–µ—Å—Ç—å\s+–ø—Ä–∞–≤|–∏–º–µ—é\s+–ø—Ä–∞–≤|—Ä–∞–∑—Ä–µ—à–µ–Ω–∏|—è\s+–≤–ª–∞–¥–µ–ª–µ—Ü|own\s+image|my\s+image|my\s+photo|i\s+own)",
    re.IGNORECASE,
)


def _is_image_retouch_request(text: str) -> bool:
    """True –¥–ª—è –±–µ–∑–æ–ø–∞—Å–Ω–æ–π —Ä–µ—Ç—É—à–∏ —Å–æ–±—Å—Ç–≤–µ–Ω–Ω–æ–≥–æ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è: –≤–æ–¥—è–Ω–æ–π –∑–Ω–∞–∫, –ª–∏—à–Ω—è—è –Ω–∞–¥–ø–∏—Å—å, –ª–æ–≥–æ—Ç–∏–ø, –æ–±—ä–µ–∫—Ç."""
    return bool(_RETOUCH_TERMS_RE.search(text or ""))


def _has_own_image_confirmation(text: str) -> bool:
    return bool(_OWN_IMAGE_CONFIRM_RE.search(text or ""))


def _set_waiting_image_retouch(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str = ""):
    """–°–ª–µ–¥—É—é—â–µ–µ —Ñ–æ—Ç–æ –¥–æ–ª–∂–Ω–æ –ø–æ–π—Ç–∏ –≤ —Ä–µ—Ç—É—à—å —Å–æ–±—Å—Ç–≤–µ–Ω–Ω–æ–≥–æ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è, –∞ –Ω–µ –≤ –º–µ–¥–∏—Ü–∏–Ω—É/–∞–Ω–∞–ª–∏–∑."""
    uid = update.effective_user.id
    _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "")
    _clear_transient_flows(context)
    context.user_data["awaiting_photo_for"] = "retouch"
    context.user_data["photo_flow"] = "retouch"
    context.user_data["retouch_prompt"] = (prompt or "").strip()


def _is_waiting_image_retouch(context) -> bool:
    if not context:
        return False
    return (
        context.user_data.get("awaiting_photo_for") == "retouch"
        or context.user_data.get("photo_flow") == "retouch"
    )


def _set_retouch_wait_text(context, prompt: str = ""):
    if not context:
        return
    context.user_data["retouch_wait_text"] = "1"
    if prompt:
        context.user_data["retouch_prompt"] = prompt.strip()


def _is_retouch_wait_text(context) -> bool:
    return bool(context and context.user_data.get("retouch_wait_text"))


def _clear_image_retouch_wait(context):
    if not context:
        return
    for key in ("awaiting_photo_for", "photo_flow", "retouch_prompt", "retouch_wait_text"):
        with contextlib.suppress(Exception):
            context.user_data.pop(key, None)


def _retouch_user_hint_text() -> str:
    return (
        "üßΩ –î–∞, –º–æ–≥—É —Å–¥–µ–ª–∞—Ç—å —Ä–µ—Ç—É—à—å —Å–æ–±—Å—Ç–≤–µ–Ω–Ω–æ–≥–æ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è.\n\n"
        "–ü—Ä–∏—à–ª–∏—Ç–µ —Ñ–æ—Ç–æ –∏, –µ—Å–ª–∏ –≤–æ–∑–º–æ–∂–Ω–æ, —É–∫–∞–∂–∏—Ç–µ –≥–¥–µ –Ω–∞—Ö–æ–¥–∏—Ç—Å—è —ç–ª–µ–º–µ–Ω—Ç: "
        "–Ω–∞–ø—Ä–∏–º–µ—Ä ¬´–≤–æ–¥—è–Ω–æ–π –∑–Ω–∞–∫ —Å–ø—Ä–∞–≤–∞ —Å–Ω–∏–∑—É¬ª, ¬´–Ω–∞–¥–ø–∏—Å—å –ø–æ —Ü–µ–Ω—Ç—Ä—É¬ª, ¬´–ª–æ–≥–æ—Ç–∏–ø —Å–≤–µ—Ä—Ö—É¬ª.\n\n"
        "–í–∞–∂–Ω–æ: —è –æ–±—Ä–∞–±–∞—Ç—ã–≤–∞—é —Ç–æ–ª—å–∫–æ –≤–∞—à–∏ —Å–æ–±—Å—Ç–≤–µ–Ω–Ω—ã–µ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è/–º–∞–∫–µ—Ç—ã –∏–ª–∏ —Ñ–∞–π–ª—ã, "
        "–Ω–∞ –∫–æ—Ç–æ—Ä—ã–µ —É –≤–∞—Å –µ—Å—Ç—å –ø—Ä–∞–≤–æ —Ä–µ–¥–∞–∫—Ç–∏—Ä–æ–≤–∞–Ω–∏—è."
    )


def _retouch_system_prompt(user_instruction: str) -> str:
    instruction = (user_instruction or "watermark or unwanted text/logo").strip()
    return (
        "Edit this user-owned image. Remove only the unwanted watermark/text/logo/object described by the user: "
        f"{instruction}. Naturally reconstruct the background in that area, preserving texture, lighting, perspective, "
        "shadows, colors and all important details. Do not change faces, identity, composition, style, objects, "
        "branding created by the user, or any other part of the image. Keep the result realistic and high quality."
    )


def _prepare_image_for_edit(img_bytes: bytes) -> tuple[bytes, str, str]:
    """OpenAI image edit –ª—É—á—à–µ –∫–æ—Ä–º–∏—Ç—å PNG. –ï—Å–ª–∏ PIL –Ω–µ–¥–æ—Å—Ç—É–ø–µ–Ω ‚Äî –æ—Ç–ø—Ä–∞–≤–ª—è–µ–º –∏—Å—Ö–æ–¥–Ω—ã–π —Ñ–∞–π–ª."""
    if Image is None:
        mime = sniff_image_mime(img_bytes)
        ext = "jpg" if mime == "image/jpeg" else "png"
        return img_bytes, f"image.{ext}", mime
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGBA")
        # –û–≥—Ä–∞–Ω–∏—á–∏–≤–∞–µ–º —Ä–∞–∑–º–µ—Ä, —á—Ç–æ–±—ã –Ω–µ –ª–æ–≤–∏—Ç—å –ª–∏–º–∏—Ç—ã multipart, –Ω–æ —Å–æ—Ö—Ä–∞–Ω—è–µ–º —Ö–æ—Ä–æ—à—É—é –¥–µ—Ç–∞–ª–∏–∑–∞—Ü–∏—é.
        max_side = 1600
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        bio = BytesIO()
        im.save(bio, format="PNG")
        return bio.getvalue(), "image.png", "image/png"
    except Exception:
        mime = sniff_image_mime(img_bytes)
        ext = "jpg" if mime == "image/jpeg" else "png"
        return img_bytes, f"image.{ext}", mime


async def _openai_image_edit_bytes(img_bytes: bytes, user_instruction: str) -> bytes | None:
    """–†–µ–∞–ª—å–Ω–∞—è —Ä–µ—Ç—É—à—å —á–µ—Ä–µ–∑ OpenAI Images / gpt-image-1: /images/edits."""
    if not OPENAI_IMAGE_KEY:
        return None
    if OPENAI_IMAGE_KEY.startswith("sk-or-"):
        # OpenRouter –Ω–µ —É–º–µ–µ—Ç OpenAI Images edits.
        raise RuntimeError("OPENAI_IMAGE_KEY –ø–æ—Ö–æ–∂ –Ω–∞ –∫–ª—é—á OpenRouter. –î–ª—è —Ä–µ—Ç—É—à–∏ –Ω—É–∂–µ–Ω –æ—Ñ–∏—Ü–∏–∞–ª—å–Ω—ã–π OpenAI key –∏–ª–∏ —Å–æ–≤–º–µ—Å—Ç–∏–º—ã–π image-edit proxy.")

    edit_bytes, filename, mime = _prepare_image_for_edit(img_bytes)
    prompt = _retouch_system_prompt(user_instruction)
    base = (IMAGES_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {OPENAI_IMAGE_KEY}"}

    # –ù–µ–∫–æ—Ç–æ—Ä—ã–µ –ø—Ä–æ–∫—Å–∏ –Ω–µ –ª—é–±—è—Ç size, –ø–æ—ç—Ç–æ–º—É –¥–µ–ª–∞–µ–º –¥–≤–µ –ø–æ–ø—ã—Ç–∫–∏.
    attempts = [
        {"model": IMAGES_MODEL, "prompt": prompt, "n": "1", "size": "1024x1024"},
        {"model": IMAGES_MODEL, "prompt": prompt, "n": "1"},
    ]
    last_err = ""
    async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
        for data in attempts:
            try:
                files = {"image": (filename, edit_bytes, mime)}
                r = await client.post(f"{base}/images/edits", headers=headers, data=data, files=files)
                if r.status_code >= 400:
                    last_err = f"{r.status_code}: {_api_error_preview(r)}" if "_api_error_preview" in globals() else f"{r.status_code}: {r.text[:500]}"
                    log.warning("Image edit failed: %s", last_err)
                    continue
                js = r.json() or {}
                item = (js.get("data") or [{}])[0]
                b64 = item.get("b64_json")
                if b64:
                    return base64.b64decode(b64)
                url = item.get("url") or _extract_first_url(js) if "_extract_first_url" in globals() else item.get("url")
                if url:
                    rr = await client.get(url, timeout=180.0)
                    rr.raise_for_status()
                    return rr.content
                last_err = f"–Ω–µ—Ç b64_json/url –≤ –æ—Ç–≤–µ—Ç–µ: {json.dumps(js, ensure_ascii=False)[:500]}"
            except Exception as e:
                last_err = str(e)
                log.warning("Image edit exception: %s", e)
                continue
    raise RuntimeError(last_err or "image edit failed")


async def _edit_own_image_retouch(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes, instruction: str):
    """–û—Ç–ø—Ä–∞–≤–ª—è–µ—Ç —Ñ–æ—Ç–æ –≤ AI-—Ä–µ—Ç—É—à—å –∏ –≤–æ–∑–≤—Ä–∞—â–∞–µ—Ç —Ä–µ–∑—É–ª—å—Ç–∞—Ç –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—é."""
    instruction = (instruction or context.user_data.get("retouch_prompt") or "—É–±—Ä–∞—Ç—å –ª–∏—à–Ω—é—é –Ω–∞–¥–ø–∏—Å—å/–≤–æ–¥—è–Ω–æ–π –∑–Ω–∞–∫ –∏ –≤–æ—Å—Å—Ç–∞–Ω–æ–≤–∏—Ç—å —Ñ–æ–Ω").strip()
    if not OPENAI_IMAGE_KEY:
        await update.effective_message.reply_text("‚ùå –†–µ—Ç—É—à—å –Ω–µ–¥–æ—Å—Ç—É–ø–Ω–∞: –Ω–µ –∑–∞–¥–∞–Ω OPENAI_IMAGE_KEY/OPENAI_API_KEY.")
        return
    if OPENAI_IMAGE_KEY.startswith("sk-or-"):
        await update.effective_message.reply_text(
            "‚ùå –î–ª—è —Ä–µ—Ç—É—à–∏ –Ω—É–∂–µ–Ω –æ—Ñ–∏—Ü–∏–∞–ª—å–Ω—ã–π OpenAI image key. OpenRouter-–∫–ª—é—á –¥–ª—è image edit –Ω–µ –ø–æ–¥—Ö–æ–¥–∏—Ç."
        )
        return

    await update.effective_message.reply_text(
        "üßΩ –ó–∞–ø—É—Å–∫–∞—é —Ä–µ—Ç—É—à—å —Å–æ–±—Å—Ç–≤–µ–Ω–Ω–æ–≥–æ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è —á–µ—Ä–µ–∑ Images. "
        "–£–±–µ—Ä—É —Ç–æ–ª—å–∫–æ —É–∫–∞–∑–∞–Ω–Ω—ã–π –ª–∏—à–Ω–∏–π —ç–ª–µ–º–µ–Ω—Ç –∏ –ø–æ—Å—Ç–∞—Ä–∞—é—Å—å –µ—Å—Ç–µ—Å—Ç–≤–µ–Ω–Ω–æ –≤–æ—Å—Å—Ç–∞–Ω–æ–≤–∏—Ç—å —Ñ–æ–Ω."
    )
    with contextlib.suppress(Exception):
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
    try:
        out = await _openai_image_edit_bytes(img_bytes, instruction)
        if not out:
            await update.effective_message.reply_text("‚ùå –ù–µ —É–¥–∞–ª–æ—Å—å –ø–æ–ª—É—á–∏—Ç—å —Ä–µ–∑—É–ª—å—Ç–∞—Ç —Ä–µ—Ç—É—à–∏.")
            return
        bio = BytesIO(out)
        bio.name = "retouched.png"
        await update.effective_message.reply_document(
            InputFile(bio),
            caption="‚úÖ –ì–æ—Ç–æ–≤–æ: —Ä–µ—Ç—É—à—å –≤—ã–ø–æ–ª–Ω–µ–Ω–∞. –ü—Ä–æ–≤–µ—Ä—å—Ç–µ —Ñ–æ–Ω –∏ –¥–µ—Ç–∞–ª–∏; –ø—Ä–∏ –Ω–µ–æ–±—Ö–æ–¥–∏–º–æ—Å—Ç–∏ –º–æ–∂–Ω–æ –æ—Ç–ø—Ä–∞–≤–∏—Ç—å —É—Ç–æ—á–Ω–µ–Ω–∏–µ, —á—Ç–æ –ø–æ–ø—Ä–∞–≤–∏—Ç—å."
        )
        return True
    except Exception as e:
        log.exception("image retouch error: %s", e)
        await update.effective_message.reply_text(
            "‚ùå –ù–µ —É–¥–∞–ª–æ—Å—å –≤—ã–ø–æ–ª–Ω–∏—Ç—å —Ä–µ—Ç—É—à—å –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è. "
            f"–¢–µ—Ö–Ω–∏—á–µ—Å–∫–∞—è –ø—Ä–∏—á–∏–Ω–∞: {str(e)[:700]}"
        )
        return False


async def _start_image_retouch(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes, instruction: str):
    """–ü–ª–∞—Ç—ë–∂–Ω–∞—è –æ–±—ë—Ä—Ç–∫–∞ –¥–ª—è —Ä–µ—Ç—É—à–∏: –∏—Å–ø–æ–ª—å–∑—É–µ–º —Ç–æ—Ç –∂–µ –±—é–¥–∂–µ—Ç Images."""
    if not OPENAI_IMAGE_KEY or OPENAI_IMAGE_KEY.startswith("sk-or-"):
        return await _edit_own_image_retouch(update, context, img_bytes, instruction)

    async def _go():
        return await _edit_own_image_retouch(update, context, img_bytes, instruction)

    await _try_pay_then_do(
        update, context, update.effective_user.id,
        "img", IMG_COST_USD, _go,
        remember_kind="image_retouch",
        remember_payload={"instruction": instruction},
    )


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ UI / —Ç–µ–∫—Å—Ç—ã ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
START_TEXT = (
    "üëã –ü—Ä–∏–≤–µ—Ç! –Ø *Neyro-Bot GPT 5 Studio* ‚Äî –º—É–ª—å—Ç–∏–º–æ–¥–µ–ª—å–Ω–∞—è AI-—Å—Ç—É–¥–∏—è –≤ Telegram –¥–ª—è —Ç–µ–∫—Å—Ç–∞, –¥–æ–∫—É–º–µ–Ω—Ç–æ–≤, —Ñ–æ—Ç–æ, –≤–∏–¥–µ–æ, –º—É–∑—ã–∫–∏, —Ä–µ—á–∏ –∏ live-–ø–æ–∏—Å–∫–∞.\n"
    "–†–∞–±–æ—Ç–∞—é –≤ –ø—Ä–æ–¥–∞–∫—à–Ω-—Ä–µ–∂–∏–º–∞—Ö: —Å–∞–º –ø–æ–¥–±–∏—Ä–∞—é –ø–æ–¥—Ö–æ–¥—è—â–∏–π –¥–≤–∏–∂–æ–∫ –ø–æ–¥ –∑–∞–¥–∞—á—É –∏–ª–∏ –¥–∞—é –≤—ã–±—Ä–∞—Ç—å –µ–≥–æ –≤—Ä—É—á–Ω—É—é —á–µ—Ä–µ–∑ ¬´üß† –î–≤–∏–∂–∫–∏¬ª.\n"
    "\n"
    "üöÄ *–ß—Ç–æ —É–º–µ—é:*\n"
    "‚Ä¢ üéì *–£—á—ë–±–∞* ‚Äî –æ–±—ä—è—Å–Ω–µ–Ω–∏–µ —Ç–µ–º, –∑–∞–¥–∞—á–∏, —ç—Å—Å–µ/—Ä–µ—Ñ–µ—Ä–∞—Ç—ã, –∫–æ–Ω—Å–ø–µ–∫—Ç—ã –∏–∑ PDF/EPUB/DOCX, –ø–ª–∞–Ω—ã –∫ —ç–∫–∑–∞–º–µ–Ω–∞–º, —Ä–µ—á—å ‚Üî —Ç–µ–∫—Å—Ç.\n"
    "‚Ä¢ üíº *–†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å* ‚Äî –ø–∏—Å—å–º–∞, –ö–ü, –¥–æ–∫—É–º–µ–Ω—Ç—ã, –∞–Ω–∞–ª–∏—Ç–∏–∫–∞, ToDo, –±—Ä–∏—Ñ—ã, –ø—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏–∏, PDF-–∫–∞—Ç–∞–ª–æ–≥–∏, –ª–æ–≥–æ—Ç–∏–ø—ã, —É–¥–∞–ª–µ–Ω–∏–µ –≤–æ–¥—è–Ω—ã—Ö –∑–Ω–∞–∫–æ–≤, –¥–∏–∫—Ç–æ–≤–∫–∞ –∏ –æ–∑–≤—É—á–∫–∞.\n"
    "‚Ä¢ üî• *–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è* ‚Äî –æ–∂–∏–≤–ª–µ–Ω–∏–µ —Ñ–æ—Ç–æ, –≥–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä, —Ñ–æ—Ç–æ‚Üí–≤–∏–¥–µ–æ–∫–ª–∏–ø —Å –º—É–∑—ã–∫–æ–π, –∫–ª–∏–ø —Å –≤–æ–∫–∞–ª–æ–º –¥–ª—è 1 —á–µ–ª–æ–≤–µ–∫–∞, –≤–∏–¥–µ–æ –ø–æ —Ç–µ–∫—Å—Ç—É/–≥–æ–ª–æ—Å—É, Reels/Shorts, –º–∏–Ω–∏-—Ñ–∏–ª—å–º—ã, —Å—Ü–µ–Ω–∞—Ä–∏–∏, –∑–∞–º–µ–Ω–∞ –ª–∏—Ü–∞, —É–¥–∞–ª–µ–Ω–∏–µ/–∑–∞–º–µ–Ω–∞ —Ñ–æ–Ω–∞, —Ä–µ—Ç—É—à—å –∏ –º—É–∑—ã–∫–∞ Suno.\n"
    "‚Ä¢ ü©∫ *–ú–µ–¥–∏—Ü–∏–Ω–∞* ‚Äî —Å–ø—Ä–∞–≤–æ—á–Ω—ã–π —Ä–∞–∑–±–æ—Ä –≤—ã–ø–∏—Å–æ–∫, –∞–Ω–∞–ª–∏–∑–æ–≤, –∑–∞–∫–ª—é—á–µ–Ω–∏–π, –ú–†–¢/–ö–¢/—Å–Ω–∏–º–∫–æ–≤ –∏ –ø–æ–¥–≥–æ—Ç–æ–≤–∫–∞ –≤–æ–ø—Ä–æ—Å–æ–≤ –≤—Ä–∞—á—É. –≠—Ç–æ –Ω–µ –¥–∏–∞–≥–Ω–æ–∑ –∏ –Ω–µ –∑–∞–º–µ–Ω–∞ –æ—á–Ω–æ–π –∫–æ–Ω—Å—É–ª—å—Ç–∞—Ü–∏–∏.\n"
    "‚Ä¢ üåê *–ê–∫—Ç—É–∞–ª—å–Ω–∞—è –∏–Ω—Ñ–æ—Ä–º–∞—Ü–∏—è* ‚Äî live-–ø–æ–∏—Å–∫, –Ω–æ–≤–æ—Å—Ç–∏, –∫—É—Ä—Å—ã, —Ñ–∞–∫—Ç—ã –∏ –¥–∞–Ω–Ω—ã–µ –∏–∑ –∏–Ω—Ç–µ—Ä–Ω–µ—Ç–∞.\n"
    "‚Ä¢ üí¨ *–ú–æ–∏ —á–∞—Ç—ã* ‚Äî –¥–æ —á–µ—Ç—ã—Ä—ë—Ö –æ—Ç–¥–µ–ª—å–Ω—ã—Ö –¥–∏–∞–ª–æ–≥–æ–≤ —Å —Å–æ–±—Å—Ç–≤–µ–Ω–Ω–æ–π –ø–∞–º—è—Ç—å—é –∏ –∏—Å—Ç–æ—Ä–∏–µ–π.\n"
    "‚Ä¢ üí≥ *–ë–∞–ª–∞–Ω—Å –∏ –ø–æ–¥–ø–∏—Å–∫–∞* ‚Äî —Ç–∞—Ä–∏—Ñ—ã, –ø–æ–ø–æ–ª–Ω–µ–Ω–∏–µ, –ø–ª–∞—Ç–Ω—ã–µ –≥–µ–Ω–µ—Ä–∞—Ü–∏–∏ –∏ –∫–æ–Ω—Ç—Ä–æ–ª—å —Ä–∞—Å—Ö–æ–¥–æ–≤.\n"
    "\n"
    "üß© *–ü–æ–¥ –∫–∞–ø–æ—Ç–æ–º:* –º—É–ª—å—Ç–∏–º–æ–¥–µ–ª—å–Ω–∞—è —Å–≤—è–∑–∫–∞ GPT/OpenRouter, OpenAI Images/TTS, Deepgram, Tavily, Runway, Sora 2, Kling, Midjourney, Suno, Photoroom, PiAPI, Segmind –∏ CometAPI.\n"
    "\n"
    "–í—ã–±–µ—Ä–∏—Ç–µ —Ä–µ–∂–∏–º –∫–Ω–æ–ø–∫–æ–π –Ω–∏–∂–µ –∏–ª–∏ –ø—Ä–æ—Å—Ç–æ –Ω–∞–ø–∏—à–∏—Ç–µ –∑–∞–¥–∞—á—É —Ç–µ–∫—Å—Ç–æ–º/–≥–æ–ª–æ—Å–æ–º."
)

def engines_kb():
    # –û—Ç–¥–µ–ª—å–Ω—ã–π —Ä–µ–∂–∏–º ¬´–î–≤–∏–∂–∫–∏¬ª: –ø–æ–∫–∞–∑—ã–≤–∞–µ–º –≤—Å–µ —Å–µ—Ä–≤–∏—Å—ã/–Ω–µ–π—Ä–æ—Å–µ—Ç–∏,
    # —Ä–µ–∞–ª—å–Ω–æ –ø–æ–¥–∫–ª—é—á–µ–Ω–Ω—ã–µ –≤ —ç—Ç–æ–π —Å–±–æ—Ä–∫–µ. –ö–Ω–æ–ø–∫–∏ ‚Äî –ø–æ –æ–¥–Ω–æ–π –≤ —Å—Ç—Ä–æ–∫–µ,
    # —á—Ç–æ–±—ã Telegram –Ω–∞ Android –Ω–µ –æ–±—Ä–µ–∑–∞–ª –¥–ª–∏–Ω–Ω—ã–π —Ç–µ–∫—Å—Ç.
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("üß† GPT / OpenRouter", callback_data="engine:gpt")],
        [InlineKeyboardButton("üñº OpenAI Images", callback_data="engine:images")],
        [InlineKeyboardButton("üîä OpenAI TTS", callback_data="engine:openai_tts")],
        [InlineKeyboardButton("üó£ Deepgram STT", callback_data="engine:deepgram")],
        [InlineKeyboardButton("üåê Tavily –ø–æ–∏—Å–∫", callback_data="engine:tavily")],
        [InlineKeyboardButton("üé• Runway –≤–∏–¥–µ–æ", callback_data="engine:runway")],
        [InlineKeyboardButton("üéû Sora 2 ¬∑ –±–µ–∑ –ª—é–¥–µ–π", callback_data="engine:sora")],
        [InlineKeyboardButton("üé¨ Kling –≤–∏–¥–µ–æ", callback_data="engine:kling")],
        [InlineKeyboardButton("üé® Midjourney –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è", callback_data="engine:midjourney")],
        [InlineKeyboardButton("üéµ Suno –º—É–∑—ã–∫–∞", callback_data="engine:suno")],
        [InlineKeyboardButton("üßº Photoroom —Ñ–æ–Ω", callback_data="engine:photoroom")],
        [InlineKeyboardButton("üé≠ PiAPI –ª–∏—Ü–æ", callback_data="engine:piapi")],
        [InlineKeyboardButton("üíé Segmind –ª–∏—Ü–æ", callback_data="engine:segmind")],
        [InlineKeyboardButton("üåâ CometAPI —à–ª—é–∑", callback_data="engine:comet")],
        [InlineKeyboardButton("üí∞ –¶–µ–Ω—ã –≥–µ–Ω–µ—Ä–∞—Ü–∏–π", callback_data="pricing:list")],
    ])

ENGINE_INFO_TEXT = {
    "gpt": (
        "üß† GPT / OpenRouter: –æ—Å–Ω–æ–≤–Ω–æ–π —Ç–µ–∫—Å—Ç–æ–≤—ã–π –º–æ–∑–≥ –±–æ—Ç–∞.\n"
        "–ò—Å–ø–æ–ª—å–∑—É–µ—Ç—Å—è –¥–ª—è —á–∞—Ç–∞, –¥–æ–∫—É–º–µ–Ω—Ç–æ–≤, –∞–Ω–∞–ª–∏–∑–∞, —É—á–µ–±–Ω—ã—Ö –∏ —Ä–∞–±–æ—á–∏—Ö –∑–∞–¥–∞—á.\n"
        "–ö–ª—é—á–∏: OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL."
    ),
    "images": (
        "üñº OpenAI Images: –≥–µ–Ω–µ—Ä–∞—Ü–∏—è –∏ —á–∞—Å—Ç—å —Ä–µ–¥–∞–∫—Ç–∏—Ä–æ–≤–∞–Ω–∏—è –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–π.\n"
        "–ó–∞–ø—É—Å–∫: /img <–æ–ø–∏—Å–∞–Ω–∏–µ> –∏–ª–∏ –∫–Ω–æ–ø–∫–∏ —Ñ–æ—Ç–æ-–º–∞—Å—Ç–µ—Ä—Å–∫–æ–π.\n"
        "–ö–ª—é—á–∏: OPENAI_IMAGE_KEY –∏–ª–∏ OPENAI_API_KEY."
    ),
    "openai_tts": (
        "üîä OpenAI TTS —Ç–µ–∫—Å—Ç–∞ –≥–æ–ª–æ—Å–æ–º.\n"
        "–ò—Å–ø–æ–ª—å–∑—É–µ—Ç—Å—è –¥–ª—è —Ä–µ–∂–∏–º–∞ —Ä–µ—á—å/–æ–∑–≤—É—á–∫–∞.\n"
        "–ö–ª—é—á–∏: OPENAI_TTS_KEY / OPENAI_TTS_MODEL / OPENAI_TTS_VOICE."
    ),
    "deepgram": (
        "üó£ Deepgram STT: —Ä–∞—Å–ø–æ–∑–Ω–∞–≤–∞–Ω–∏–µ –≥–æ–ª–æ—Å–æ–≤—ã—Ö —Å–æ–æ–±—â–µ–Ω–∏–π –∏ –∞—É–¥–∏–æ –≤ —Ç–µ–∫—Å—Ç.\n"
        "–ö–ª—é—á: DEEPGRAM_API_KEY. –†–µ–∑–µ—Ä–≤: OPENAI_STT_KEY / Whisper."
    ),
    "stt_tts": (
        "üó£ –†–µ—á—å ‚Üî —Ç–µ–∫—Å—Ç: —Å–≤—è–∑–∫–∞ STT/TTS.\n"
        "STT: Deepgram –∏–ª–∏ OpenAI Whisper. TTS: OpenAI TTS."
    ),
    "tavily": (
        "üåê Tavily: live-–ø–æ–∏—Å–∫ –≤ –∏–Ω—Ç–µ—Ä–Ω–µ—Ç–µ –¥–ª—è —Å–≤–µ–∂–∏—Ö –¥–∞–Ω–Ω—ã—Ö, –Ω–æ–≤–æ—Å—Ç–µ–π, –∫—É—Ä—Å–æ–≤, –∑–∞–∫–æ–Ω–æ–≤ –∏ –∏—Å—Ç–æ—á–Ω–∏–∫–æ–≤.\n"
        "–ö–ª—é—á: TAVILY_API_KEY."
    ),
    "runway": (
        "üé• Runway: –æ—Ñ–∏—Ü–∏–∞–ª—å–Ω–∞—è –≥–µ–Ω–µ—Ä–∞—Ü–∏—è –≤–∏–¥–µ–æ –ø–æ —Ç–µ–∫—Å—Ç—É –∏ –æ–∂–∏–≤–ª–µ–Ω–∏–µ —Ñ–æ—Ç–æ.\n"
        "–û—Å–Ω–æ–≤–Ω–æ–π –º–∞—Ä—à—Ä—É—Ç ‚Äî Runway Developer API; CometAPI –∏ Kling –∏—Å–ø–æ–ª—å–∑—É—é—Ç—Å—è —Ç–æ–ª—å–∫–æ –∫–∞–∫ —Ä–µ–∑–µ—Ä–≤.\n"
        "–ö–ª—é—á: RUNWAYML_API_SECRET. Powered by Runway ‚Äî https://runwayml.com"
    ),
    "sora": (
        "üéû Sora 2: –≥–µ–Ω–µ—Ä–∞—Ü–∏—è –≤–∏–¥–µ–æ –ø–æ —Ç–µ–∫—Å—Ç—É –∏ —Ñ–æ—Ç–æ —á–µ—Ä–µ–∑ CometAPI.\n"
        "–í–∞–∂–Ω–æ: —Ä–µ–∂–∏–º Sora 2 –±–µ–∑ –ª—é–¥–µ–π ‚Äî –¥–ª—è —Ñ–æ—Ç–æ/–≤–∏–¥–µ–æ —Å –ª—é–¥—å–º–∏ –ª—É—á—à–µ Runway –∏–ª–∏ Kling.\n"
        "–ö–ª—é—á: COMET_API_KEY."
    ),
    "kling": (
        "üé¨ Kling: –≥–µ–Ω–µ—Ä–∞—Ü–∏—è –≤–∏–¥–µ–æ –ø–æ —Ç–µ–∫—Å—Ç—É –∏ —Ñ–æ—Ç–æ —á–µ—Ä–µ–∑ CometAPI.\n"
        "–ò—Å–ø–æ–ª—å–∑—É–µ—Ç—Å—è –¥–ª—è –¥–∏–Ω–∞–º–∏—á–Ω—ã—Ö –∫–ª–∏–ø–æ–≤, Reels/Shorts –∏ fallback –¥–ª—è –æ–∂–∏–≤–ª–µ–Ω–∏—è —Ñ–æ—Ç–æ.\n"
        "–ö–ª—é—á: COMET_API_KEY."
    ),
    "midjourney": (
        "üé® Midjourney: –≥–µ–Ω–µ—Ä–∞—Ü–∏—è –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–π —á–µ—Ä–µ–∑ CometAPI/—Å–æ–≤–º–µ—Å—Ç–∏–º—ã–π –∫–∞–Ω–∞–ª.\n"
        "–ò—Å–ø–æ–ª—å–∑—É–µ—Ç—Å—è –¥–ª—è –≤–∏–∑—É–∞–ª–æ–≤, –æ–±–ª–æ–∂–µ–∫, –ª–æ–≥–æ—Ç–∏–ø–æ–≤ –∏ –∏–ª–ª—é—Å—Ç—Ä–∞—Ü–∏–π.\n"
        "–ö–ª—é—á: COMET_API_KEY."
    ),
    "photoroom": (
        "üßº Photoroom: –ø—Ä–æ–¥–∞–∫—à–Ω-–∏–Ω—Å—Ç—Ä—É–º–µ–Ω—Ç –¥–ª—è —É–¥–∞–ª–µ–Ω–∏—è –∏ AI-–∑–∞–º–µ–Ω—ã —Ñ–æ–Ω–∞.\n"
        "–ò—Å–ø–æ–ª—å–∑—É–µ—Ç—Å—è –≤ –∫–Ω–æ–ø–∫–∞—Ö ¬´–£–¥–∞–ª–∏—Ç—å —Ñ–æ–Ω¬ª –∏ ¬´–ó–∞–º–µ–Ω–∏—Ç—å —Ñ–æ–Ω¬ª.\n"
        "–ö–ª—é—á: PHOTOROOM_API_KEY."
    ),
    "piapi": (
        "üé≠ PiAPI: –±—ã—Å—Ç—Ä—ã–π —Ä–µ–∂–∏–º –∑–∞–º–µ–Ω—ã –ª–∏—Ü–∞.\n"
        "–ò—Å–ø–æ–ª—å–∑—É–µ—Ç—Å—è –∫–∞–∫ –æ—Å–Ω–æ–≤–Ω–æ–π –±—ã—Å—Ç—Ä—ã–π FaceSwap-–ø—Ä–æ–≤–∞–π–¥–µ—Ä.\n"
        "–ö–ª—é—á: PIAPI_API_KEY."
    ),
    "segmind": (
        "üíé Segmind: –ø—Ä–µ–º–∏—É–º/—Ä–µ–∑–µ—Ä–≤–Ω—ã–π FaceSwap.\n"
        "–ò—Å–ø–æ–ª—å–∑—É–µ—Ç—Å—è –¥–ª—è –±–æ–ª–µ–µ –∫–∞—á–µ—Å—Ç–≤–µ–Ω–Ω–æ–π –∑–∞–º–µ–Ω—ã –ª–∏—Ü–∞ –∏ –∫–∞–∫ fallback, –∫–æ–≥–¥–∞ –¥–æ—Å—Ç–∞—Ç–æ—á–Ω–æ –∫—Ä–µ–¥–∏—Ç–æ–≤.\n"
        "–ö–ª—é—á: SEGMIND_API_KEY."
    ),
    "comet": (
        "üåâ CometAPI: –æ–±—â–∏–π —à–ª—é–∑ –¥–ª—è Sora 2, Kling, Runway/Midjourney-–∫–∞–Ω–∞–ª–æ–≤ –∏ –¥—Ä—É–≥–∏—Ö –≥–µ–Ω–µ—Ä–∞—Ç–∏–≤–Ω—ã—Ö –º–æ–¥–µ–ª–µ–π.\n"
        "–ö–ª—é—á: COMET_API_KEY."
    ),
}

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ MODES (–£—á—ë–±–∞ / –†–∞–±–æ—Ç–∞ / –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è) ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackQueryHandler, MessageHandler, filters

# –¢–µ–∫—Å—Ç –∫–æ—Ä–Ω–µ–≤–æ–≥–æ –º–µ–Ω—é —Ä–µ–∂–∏–º–æ–≤
def _modes_root_text() -> str:
    return (
        "–í—ã–±–µ—Ä–∏—Ç–µ —Ä–µ–∂–∏–º —Ä–∞–±–æ—Ç—ã. –ë–æ—Ç —Ä–∞–±–æ—Ç–∞–µ—Ç –∫–∞–∫ –µ–¥–∏–Ω—ã–π –ø—Ä–æ–¥–∞–∫—à–Ω-—Ü–µ–Ω—Ç—Ä –ò–ò:\n"
        "‚Ä¢ üéì –£—á—ë–±–∞ ‚Äî –æ–±—ä—è—Å–Ω–µ–Ω–∏—è, –∑–∞–¥–∞—á–∏, –∫–æ–Ω—Å–ø–µ–∫—Ç—ã, —ç–∫–∑–∞–º–µ–Ω—ã, —Ñ–∞–π–ª—ã –∏ –≥–æ–ª–æ—Å.\n"
        "‚Ä¢ üíº –†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å ‚Äî –ø–∏—Å—å–º–∞, –¥–æ–∫—É–º–µ–Ω—Ç—ã, –∞–Ω–∞–ª–∏—Ç–∏–∫–∞, –ø—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏–∏, PDF-–∫–∞—Ç–∞–ª–æ–≥–∏, –ª–æ–≥–æ—Ç–∏–ø—ã, —Ä–µ—Ç—É—à—å –∏ –ø–ª–∞–Ω—ã.\n"
        "‚Ä¢ üî• –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è ‚Äî —Ñ–æ—Ç–æ, –≤–∏–¥–µ–æ, Reels/Shorts, –º–∏–Ω–∏-—Ñ–∏–ª—å–º—ã, —Ñ–æ–Ω, –ª–∏—Ü–æ, AI-—Å–µ–ª—Ñ–∏, –≤–æ–∫–∞–ª—å–Ω—ã–µ –∫–ª–∏–ø—ã –∏ –º—É–∑—ã–∫–∞.\n"
        "‚Ä¢ ü©∫ –ú–µ–¥–∏—Ü–∏–Ω–∞ ‚Äî —Å–ø—Ä–∞–≤–æ—á–Ω—ã–π —Ä–∞–∑–±–æ—Ä –∞–Ω–∞–ª–∏–∑–æ–≤, –≤—ã–ø–∏—Å–æ–∫, –∑–∞–∫–ª—é—á–µ–Ω–∏–π –∏ —Å–Ω–∏–º–∫–æ–≤.\n"
        "‚Ä¢ üß† –î–≤–∏–∂–∫–∏ ‚Äî —Ä—É—á–Ω–æ–π –≤—ã–±–æ—Ä GPT/OpenRouter, OpenAI Images/TTS, Deepgram, Tavily, Runway, Sora 2, Kling, Midjourney, Suno, Photoroom, PiAPI, Segmind –∏ CometAPI.\n"
        "‚Ä¢ üí≥ –ë–∞–ª–∞–Ω—Å/–ø–æ–¥–ø–∏—Å–∫–∞ ‚Äî —Ç–∞—Ä–∏—Ñ—ã, –ø–æ–ø–æ–ª–Ω–µ–Ω–∏–µ –∏ –∫–æ–Ω—Ç—Ä–æ–ª—å –ø–ª–∞—Ç–Ω—ã—Ö –≥–µ–Ω–µ—Ä–∞—Ü–∏–π.\n\n"
        "–ú–æ–∂–Ω–æ –ø—Ä–æ—Å—Ç–æ –Ω–∞–ø–∏—Å–∞—Ç—å –∑–∞–ø—Ä–æ—Å ‚Äî –±–æ—Ç —Å–∞–º –æ–ø—Ä–µ–¥–µ–ª–∏—Ç –∑–∞–¥–∞—á—É."
    )

def modes_root_kb() -> InlineKeyboardMarkup:
    # –ù–µ —Å—Ç–∞–≤–∏–º 3 –¥–ª–∏–Ω–Ω—ã–µ –∫–Ω–æ–ø–∫–∏ –≤ –æ–¥–Ω—É —Å—Ç—Ä–æ–∫—É ‚Äî –Ω–∞ Android Telegram —Ä–µ–∂–µ—Ç —Ç–µ–∫—Å—Ç.
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("üéì –£—á—ë–±–∞", callback_data="mode:study"),
            InlineKeyboardButton("üíº –†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å", callback_data="mode:work"),
        ],
        [
            InlineKeyboardButton("üî• –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", callback_data="mode:fun"),
            InlineKeyboardButton("ü©∫ –ú–µ–¥–∏—Ü–∏–Ω–∞", callback_data="mode:medicine"),
        ],
    ])

# ‚îÄ‚îÄ –û–ø–∏—Å–∞–Ω–∏–µ –∏ –ø–æ–¥–º–µ–Ω—é –ø–æ —Ä–µ–∂–∏–º–∞–º
def _mode_desc(key: str) -> str:
    if key == "study":
        return (
            "üéì *–£—á—ë–±–∞*\n"
            "–ì–∏–±—Ä–∏–¥: GPT-5 –¥–ª—è –æ–±—ä—è—Å–Ω–µ–Ω–∏–π/–∫–æ–Ω—Å–ø–µ–∫—Ç–æ–≤, Vision –¥–ª—è —Ñ–æ—Ç–æ-–∑–∞–¥–∞—á, "
            "STT/TTS –¥–ª—è –≥–æ–ª–æ—Å–æ–≤—ã—Ö –∏ –∞—É–¥–∏–æ. –ì–µ–Ω–µ—Ä–∞—Ç–∏–≤–Ω—ã–µ —Ñ–æ—Ç–æ/–≤–∏–¥–µ–æ-–¥–≤–∏–∂–∫–∏ –≤—ã–Ω–µ—Å–µ–Ω—ã –≤ –æ—Ç–¥–µ–ª—å–Ω—ã–π —Ä–µ–∂–∏–º ¬´–î–≤–∏–∂–∫–∏¬ª.\n\n"
            "–ë—ã—Å—Ç—Ä—ã–µ –¥–µ–π—Å—Ç–≤–∏—è –Ω–∏–∂–µ. –ú–æ–∂–Ω–æ –Ω–∞–ø–∏—Å–∞—Ç—å —Å–≤–æ–±–æ–¥–Ω—ã–π –∑–∞–ø—Ä–æ—Å (–Ω–∞–ø—Ä–∏–º–µ—Ä: "
            "¬´—Å–¥–µ–ª–∞–π –∫–æ–Ω—Å–ø–µ–∫—Ç –∏–∑ PDF¬ª, ¬´–æ–±—ä—è—Å–Ω–∏ –∏–Ω—Ç–µ–≥—Ä–∞–ª—ã —Å –ø—Ä–∏–º–µ—Ä–∞–º–∏¬ª)."
        )
    if key == "work":
        return (
            "üíº *–†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å*\n"
            "–ì–∏–±—Ä–∏–¥: GPT-5 –¥–ª—è –¥–æ–∫—É–º–µ–Ω—Ç–æ–≤, –ö–ü, –∞–Ω–∞–ª–∏—Ç–∏–∫–∏ –∏ —Å—Ç—Ä—É–∫—Ç—É—Ä—ã; Vision –¥–ª—è —Ç–∞–±–ª–∏—Ü/—Å–∫—Ä–∏–Ω–æ–≤; "
            "OpenAI Images/Midjourney –¥–ª—è –ª–æ–≥–æ—Ç–∏–ø–æ–≤ –∏ –≤–∏–∑—É–∞–ª–æ–≤; image-edit –¥–ª—è —É–¥–∞–ª–µ–Ω–∏—è –≤–æ–¥—è–Ω—ã—Ö –∑–Ω–∞–∫–æ–≤; "
            "–ø–æ–ª–Ω–æ—Ü–µ–Ω–Ω—ã–π –º–∞—Å—Ç–µ—Ä –ø—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏–π/–∫–∞—Ç–∞–ª–æ–≥–æ–≤ —Å –ª–æ–≥–æ—Ç–∏–ø–æ–º, –º–∞—Å—Å–æ–≤–æ–π –∑–∞–≥—Ä—É–∑–∫–æ–π —Ñ–æ—Ç–æ, AI-–≤–∏–∑—É–∞–ª–∞–º–∏ –∏ —ç–∫—Å–ø–æ—Ä—Ç–æ–º PDF+PPTX; STT/TTS –¥–ª—è –¥–∏–∫—Ç–æ–≤–∫–∏ –∏ –æ–∑–≤—É—á–∫–∏.\n\n"
            "–ë—ã—Å—Ç—Ä—ã–µ –¥–µ–π—Å—Ç–≤–∏—è –Ω–∏–∂–µ. –ú–æ–∂–Ω–æ –Ω–∞–ø–∏—Å–∞—Ç—å —Å–≤–æ–±–æ–¥–Ω—ã–π –∑–∞–ø—Ä–æ—Å: ¬´—Å–¥–µ–ª–∞–π –ö–ü¬ª, ¬´—Å–æ–∑–¥–∞–π –ø—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏—é –Ω–∞ 10 —Å–ª–∞–π–¥–æ–≤¬ª, "
            "¬´—Å–æ–±–µ—Ä–∏ PDF-–∫–∞—Ç–∞–ª–æ–≥ –æ–±—ä–µ–∫—Ç–æ–≤¬ª, ¬´—Å–æ–∑–¥–∞–π –ª–æ–≥–æ—Ç–∏–ø –¥–ª—è –±—Ä–µ–Ω–¥–∞¬ª, ¬´—É–±–µ—Ä–∏ –≤–æ–¥—è–Ω–æ–π –∑–Ω–∞–∫ —Å —Ñ–æ—Ç–æ¬ª."
        )
    if key == "fun":
        return (
            "üî• *–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è*\n"
            "–ì–∏–±—Ä–∏–¥: GPT-5 (–∏–¥–µ–∏, —Å—Ü–µ–Ω–∞—Ä–∏–∏, —Ä–∞—Å–∫–∞–¥—Ä–æ–≤–∫–∞), Vision (—Ñ–æ—Ç–æ/—Ä–µ—Ñ–µ—Ä–µ–Ω—Å—ã), "
            "Sora 2 –±–µ–∑ –ª—é–¥–µ–π, Kling –∏ Runway (–≤–∏–¥–µ–æ –ø–æ —Ç–µ–∫—Å—Ç—É), Runway/Kling (–æ–∂–∏–≤–ª–µ–Ω–∏–µ —Ñ–æ—Ç–æ —Å –ª—é–¥—å–º–∏), Sora 2 ‚Äî —Ç–æ–ª—å–∫–æ —Å—Ü–µ–Ω—ã –±–µ–∑ –ª—é–¥–µ–π, STT/TTS (–≥–æ–ª–æ—Å –∏ –æ–∑–≤—É—á–∫–∞).\n\n"
            "–ì–ª–∞–≤–Ω—ã–µ –±—ã—Å—Ç—Ä—ã–µ –¥–µ–π—Å—Ç–≤–∏—è: –æ–∂–∏–≤–∏—Ç—å —Ñ–æ—Ç–æ, –≥–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä, AI-–≤–∏–¥–µ–æ–∫–ª–∏–ø/–ø–µ—Å–Ω—è —Å –º—É–∑—ã–∫–æ–π –∏–ª–∏ –≤–æ–∫–∞–ª–æ–º, –≤–∏–¥–µ–æ –ø–æ —Ç–µ–∫—Å—Ç—É/–≥–æ–ª–æ—Å—É —á–µ—Ä–µ–∑ Kling/Runway, —Å–¥–µ–ª–∞—Ç—å Reels/Shorts, —Å–æ–∑–¥–∞—Ç—å –º–∏–Ω–∏-—Ñ–∏–ª—å–º, –∑–∞–º–µ–Ω–∏—Ç—å –ª–∏—Ü–æ, —É–¥–∞–ª–∏—Ç—å –∏–ª–∏ –∑–∞–º–µ–Ω–∏—Ç—å —Ñ–æ–Ω –Ω–∞ —Ñ–æ—Ç–æ.\n"
            "–ú–æ–∂–Ω–æ –Ω–∞–ø–∏—Å–∞—Ç—å —Å–≤–æ–±–æ–¥–Ω—ã–π –∑–∞–ø—Ä–æ—Å, –Ω–∞–ø—Ä–∏–º–µ—Ä: ¬´—Å–¥–µ–ª–∞–π —Ä–∏–ª—Å 20 —Å–µ–∫—É–Ω–¥ –ø—Ä–æ –≤–∏–ª–ª—É –Ω–∞ –°–∞–º—É–∏, —Å—Ç–∏–ª—å luxury, 9:16¬ª."
        )
    if key == "medicine":
        return _medical_menu_text()
    return "–†–µ–∂–∏–º –Ω–µ –Ω–∞–π–¥–µ–Ω."

def _mode_kb(key: str) -> InlineKeyboardMarkup:
    if key == "study":
        # –í—Å–µ –¥–ª–∏–Ω–Ω—ã–µ –ø–æ–¥–ø–∏—Å–∏ –∏–¥—É—Ç –ø–æ –æ–¥–Ω–æ–π –∫–Ω–æ–ø–∫–µ –≤ —Å—Ç—Ä–æ–∫–µ ‚Äî Telegram –Ω–∞ Android –Ω–µ —Ä–µ–∂–µ—Ç —Ç–µ–∫—Å—Ç.
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("üìö –ö–æ–Ω—Å–ø–µ–∫—Ç PDF/EPUB/DOCX", callback_data="act:study:pdf_summary")],
            [InlineKeyboardButton("üîç –û–±—ä—è—Å–Ω–∏—Ç—å —Ç–µ–º—É", callback_data="act:study:explain")],
            [InlineKeyboardButton("üßÆ –†–µ—à–∏—Ç—å –∑–∞–¥–∞—á–∏", callback_data="act:study:tasks")],
            [InlineKeyboardButton("‚úçÔ∏è –≠—Å—Å–µ / —Ä–µ—Ñ–µ—Ä–∞—Ç", callback_data="act:study:essay")],
            [InlineKeyboardButton("üìù –ü–ª–∞–Ω –∫ —ç–∫–∑–∞–º–µ–Ω—É", callback_data="act:study:exam_plan")],
            [InlineKeyboardButton("üó£ –†–µ—á—å ‚Üî —Ç–µ–∫—Å—Ç", callback_data="act:open:voice")],
            [InlineKeyboardButton("üìù –°–≤–æ–±–æ–¥–Ω—ã–π –∑–∞–ø—Ä–æ—Å", callback_data="act:free")],
            [InlineKeyboardButton("‚¨ÖÔ∏è –ù–∞–∑–∞–¥", callback_data="mode:root")],
        ])

    if key == "work":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("üìÑ –ü–∏—Å—å–º–æ / –¥–æ–∫—É–º–µ–Ω—Ç", callback_data="act:work:doc")],
            [InlineKeyboardButton("üìä –ê–Ω–∞–ª–∏—Ç–∏–∫–∞ / —Å–≤–æ–¥–∫–∞", callback_data="act:work:report")],
            [InlineKeyboardButton("üóÇ –ü–ª–∞–Ω / ToDo", callback_data="act:work:plan")],
            [InlineKeyboardButton("üí° –ò–¥–µ–∏ / –±—Ä–∏—Ñ", callback_data="act:work:idea")],
            [InlineKeyboardButton("üìä –ü—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏—è PDF + PPTX", callback_data="act:work:presentation")],
            [InlineKeyboardButton("üìï –ö–∞—Ç–∞–ª–æ–≥ PDF + PPTX", callback_data="act:work:catalog_pdf")],
            [InlineKeyboardButton("üé® –°–æ–∑–¥–∞—Ç—å –ª–æ–≥–æ—Ç–∏–ø", callback_data="act:work:logo")],
            [InlineKeyboardButton("üßΩ –£–¥–∞–ª–∏—Ç—å –≤–æ–¥—è–Ω–æ–π –∑–Ω–∞–∫", callback_data="act:work:watermark")],
            [InlineKeyboardButton("üó£ –†–µ—á—å ‚Üî —Ç–µ–∫—Å—Ç", callback_data="act:open:voice")],
            [InlineKeyboardButton("üìù –°–≤–æ–±–æ–¥–Ω—ã–π –∑–∞–ø—Ä–æ—Å", callback_data="act:free")],
            [InlineKeyboardButton("‚¨ÖÔ∏è –ù–∞–∑–∞–¥", callback_data="mode:root")],
        ])

    if key == "fun":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("ü™Ñ –û–∂–∏–≤–∏—Ç—å —Ñ–æ—Ç–æ", callback_data="act:fun:revive")],
            [InlineKeyboardButton("üó£ –ì–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä", callback_data="act:fun:avatar")],
            [InlineKeyboardButton("üé§ AI-–≤–∏–¥–µ–æ–∫–ª–∏–ø / –ø–µ—Å–Ω—è", callback_data="act:fun:photoclip")],
            [InlineKeyboardButton("üé¨ –í–∏–¥–µ–æ –ø–æ —Ç–µ–∫—Å—Ç—É/–≥–æ–ª–æ—Å—É", callback_data="act:fun:textvideo")],
            [InlineKeyboardButton("ü§≥ AI-—Å–µ–ª—Ñ–∏ —Å–æ –∑–≤–µ–∑–¥–æ–π", callback_data="act:fun:aiselfie")],
            [InlineKeyboardButton("üé≠ –ó–∞–º–µ–Ω–∞ –ª–∏—Ü–∞ –Ω–∞ —Ñ–æ—Ç–æ", callback_data="act:fun:faceswap")],
            [InlineKeyboardButton("üßº –£–¥–∞–ª–∏—Ç—å —Ñ–æ–Ω –Ω–∞ —Ñ–æ—Ç–æ", callback_data="act:fun:removebg")],
            [InlineKeyboardButton("üñº –ó–∞–º–µ–Ω–∏—Ç—å —Ñ–æ–Ω –Ω–∞ —Ñ–æ—Ç–æ", callback_data="act:fun:replacebg")],
            [InlineKeyboardButton("üì± Reels / Shorts", callback_data="act:fun:reels")],
            [InlineKeyboardButton("üéû –°–æ–∑–¥–∞—Ç—å –º–∏–Ω–∏-—Ñ–∏–ª—å–º", callback_data="act:fun:film")],
            [InlineKeyboardButton("üé¨ –°—Ü–µ–Ω–∞—Ä–∏–π —à–æ—Ä—Ç–∞", callback_data="act:fun:shorts")],
            [InlineKeyboardButton("üéµ –ú—É–∑—ã–∫–∞ / –ø–µ—Å–Ω—è", callback_data="act:fun:music")],
            [InlineKeyboardButton("üéÆ –ò–≥—Ä—ã / –∫–≤–∏–∑", callback_data="act:fun:games")],
            [InlineKeyboardButton("üé≠ –ò–¥–µ–∏ –¥–ª—è –¥–æ—Å—É–≥–∞", callback_data="act:fun:ideas")],
            [InlineKeyboardButton("üìù –°–≤–æ–±–æ–¥–Ω—ã–π –∑–∞–ø—Ä–æ—Å", callback_data="act:free")],
            [InlineKeyboardButton("‚¨ÖÔ∏è –ù–∞–∑–∞–¥", callback_data="mode:root")],
        ])

    if key == "medicine":
        return medicine_kb()

    return modes_root_kb()


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ü–æ–¥–º–µ–Ω—é: –≥–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä / —Ñ–æ—Ç–æ‚Üí–≤–∏–¥–µ–æ–∫–ª–∏–ø ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
def _avatar_action_kb(prefix: str = "act") -> InlineKeyboardMarkup:
    """–ü–æ–¥–º–µ–Ω—é –≥–æ–≤–æ—Ä—è—â–µ–≥–æ –∞–≤–∞—Ç–∞—Ä–∞. prefix='act' –¥–ª—è _mode_kb, prefix='fun' –¥–ª—è —Å—Ç–∞—Ä–æ–≥–æ quick-menu."""
    base = "act:fun" if prefix == "act" else "fun"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("üì∏ –ó–∞–≥—Ä—É–∑–∏—Ç—å –ø–æ—Ä—Ç—Ä–µ—Ç", callback_data=f"{base}:avatar_upload")],
        [InlineKeyboardButton("‚úÖ –ò—Å–ø–æ–ª—å–∑–æ–≤–∞—Ç—å –ø–æ—Å–ª–µ–¥–Ω–µ–µ —Ñ–æ—Ç–æ", callback_data=f"{base}:avatar_last")],
        [InlineKeyboardButton("üë© –ì–æ–ª–æ—Å Nova", callback_data=f"{base}:av_voice_nova"), InlineKeyboardButton("üë® –ì–æ–ª–æ—Å Onyx", callback_data=f"{base}:av_voice_onyx")],
        [InlineKeyboardButton("‚ö™ –ì–æ–ª–æ—Å Alloy", callback_data=f"{base}:av_voice_alloy"), InlineKeyboardButton("‚ú® –ì–æ–ª–æ—Å Shimmer", callback_data=f"{base}:av_voice_shimmer")],
        [InlineKeyboardButton("üìñ –ì–æ–ª–æ—Å Fable", callback_data=f"{base}:av_voice_fable")],
        [InlineKeyboardButton("üìù –¢–µ–∫—Å—Ç ‚Üí –≥–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä", callback_data=f"{base}:avatar_text")],
        [InlineKeyboardButton("üéô Voice/audio ‚Üí –≥–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä", callback_data=f"{base}:avatar_voice")],
        [InlineKeyboardButton("‚¨ÖÔ∏è –ù–∞–∑–∞–¥ –≤ –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", callback_data="mode:fun" if prefix == "act" else "fun:back")],
    ])


def _avatar_voice_choice_kb(prefix: str = "act") -> InlineKeyboardMarkup:
    """–®–∞–≥ 2 –¥–ª—è —Ç–µ–∫—Å—Ç–æ–≤–æ–≥–æ –∞–≤–∞—Ç–∞—Ä–∞: –≤—ã–±–æ—Ä TTS-–≥–æ–ª–æ—Å–∞ –¥–æ –≤–≤–æ–¥–∞ —Ç–µ–∫—Å—Ç–∞."""
    base = "act:fun" if prefix == "act" else "fun"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("üë© Nova ‚Äî –º—è–≥–∫–∏–π –∂–µ–Ω—Å–∫–∏–π", callback_data=f"{base}:av_voice_nova")],
        [InlineKeyboardButton("üë® Onyx ‚Äî –Ω–∏–∑–∫–∏–π –º—É–∂—Å–∫–æ–π", callback_data=f"{base}:av_voice_onyx")],
        [InlineKeyboardButton("‚ú® Shimmer ‚Äî —Å–≤–µ—Ç–ª—ã–π –∂–µ–Ω—Å–∫–∏–π", callback_data=f"{base}:av_voice_shimmer")],
        [InlineKeyboardButton("üìñ Fable ‚Äî —Å—Ç–æ—Ä–∏—Ç–µ–ª–ª–∏–Ω–≥", callback_data=f"{base}:av_voice_fable")],
        [InlineKeyboardButton("‚ö™ Alloy ‚Äî –Ω–µ–π—Ç—Ä–∞–ª—å–Ω—ã–π", callback_data=f"{base}:av_voice_alloy")],
        [InlineKeyboardButton("üéô –í–º–µ—Å—Ç–æ TTS –ø—Ä–∏—Å–ª–∞—Ç—å —Å–≤–æ–π voice/audio", callback_data=f"{base}:avatar_voice")],
        [InlineKeyboardButton("‚¨ÖÔ∏è –ù–∞–∑–∞–¥ –∫ –∞–≤–∞—Ç–∞—Ä—É", callback_data=f"{base}:avatar")],
    ])


def _avatar_voice_choice_text() -> str:
    return (
        "üéô –®–∞–≥ 2/3: –≤—ã–±–µ—Ä–∏—Ç–µ –≥–æ–ª–æ—Å –¥–ª—è —Ç–µ–∫—Å—Ç–æ–≤–æ–π –æ–∑–≤—É—á–∫–∏ –∞–≤–∞—Ç–∞—Ä–∞.\n\n"
        "–°–∞–º—ã–π –µ—Å—Ç–µ—Å—Ç–≤–µ–Ω–Ω—ã–π –≤–∞—Ä–∏–∞–Ω—Ç ‚Äî –ø—Ä–∏—Å–ª–∞—Ç—å —Å–≤–æ–π MP3/WAV/M4A/AAC –∏–ª–∏ Telegram voice —á–µ—Ä–µ–∑ –∫–Ω–æ–ø–∫—É ¬´Voice/audio ‚Üí –≥–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä¬ª.\n"
        "–ï—Å–ª–∏ –Ω—É–∂–µ–Ω —Å–∏–Ω—Ç–µ–∑ –ø–æ —Ç–µ–∫—Å—Ç—É, –≤—ã–±–µ—Ä–∏—Ç–µ –æ–¥–∏–Ω –∏–∑ –≥–æ–ª–æ—Å–æ–≤ –Ω–∏–∂–µ, –∑–∞—Ç–µ–º –ø—Ä–∏—à–ª–∏—Ç–µ —Ñ—Ä–∞–∑—É –¥–ª—è –∞–≤–∞—Ç–∞—Ä–∞."
    )

def _avatar_menu_text() -> str:
    return (
        "üó£ *–ì–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä*\n"
        "–§–æ—Ç–æ —á–µ–ª–æ–≤–µ–∫–∞ ‚Üí —Ç–µ–∫—Å—Ç, voice –∏–ª–∏ –∞—É–¥–∏–æ ‚Üí –≤–∏–¥–µ–æ —Å —Å–∏–Ω—Ö—Ä–æ–Ω–∏–∑–∞—Ü–∏–µ–π –≥—É–±.\n\n"
        "–ü–æ—Å–ª–µ–¥–æ–≤–∞—Ç–µ–ª—å–Ω–æ—Å—Ç—å –¥–ª—è —Ç–µ–∫—Å—Ç–∞:\n"
        "1) –∑–∞–≥—Ä—É–∑–∏—Ç—å –ø–æ—Ä—Ç—Ä–µ—Ç;\n"
        "2) –≤—ã–±—Ä–∞—Ç—å –≥–æ–ª–æ—Å;\n"
        "3) –ø—Ä–∏—Å–ª–∞—Ç—å —Ç–µ–∫—Å—Ç ‚Äî –ø–æ—Å–ª–µ —ç—Ç–æ–≥–æ —Å—Ä–∞–∑—É –∑–∞–ø—É—Å–∫–∞–µ—Ç—Å—è Kling Avatar.\n\n"
        "–î–ª—è —Å–∞–º–æ–≥–æ –µ—Å—Ç–µ—Å—Ç–≤–µ–Ω–Ω–æ–≥–æ —Ä–µ–∑—É–ª—å—Ç–∞—Ç–∞ –º–æ–∂–Ω–æ –≤–º–µ—Å—Ç–æ TTS –ø—Ä–∏—Å–ª–∞—Ç—å —Å–≤–æ–π voice/audio ‚Äî —Ç–æ–≥–¥–∞ –∞–≤–∞—Ç–∞—Ä –≥–æ–≤–æ—Ä–∏—Ç —Ä–µ–∞–ª—å–Ω—ã–º –∑–∞–ø–∏—Å–∞–Ω–Ω—ã–º –≥–æ–ª–æ—Å–æ–º.\n\n"
        "–õ—É—á—à–µ –≤—Å–µ–≥–æ —Ä–∞–±–æ—Ç–∞–µ—Ç —Ñ—Ä–æ–Ω—Ç–∞–ª—å–Ω—ã–π –ø–æ—Ä—Ç—Ä–µ—Ç: –ª–∏—Ü–æ –≤–∏–¥–Ω–æ –ø–æ–ª–Ω–æ—Å—Ç—å—é, –±–µ–∑ —Å–∏–ª—å–Ω–æ–≥–æ –ø–æ–≤–æ—Ä–æ—Ç–∞ –∏ –±–µ–∑ –∑–∞–∫—Ä—ã—Ç–æ–≥–æ —Ä—Ç–∞."
    )


def _photoclip_action_kb(prefix: str = "act") -> InlineKeyboardMarkup:
    """Unified AI music-video mode: instrumental or vocal, one or more people."""
    base = "act:fun" if prefix == "act" else "fun"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("üì∏ –ó–∞–≥—Ä—É–∑–∏—Ç—å —Ñ–æ—Ç–æ", callback_data=f"{base}:photoclip_upload")],
        [InlineKeyboardButton("‚úÖ –ò—Å–ø–æ–ª—å–∑–æ–≤–∞—Ç—å –ø–æ—Å–ª–µ–¥–Ω–µ–µ —Ñ–æ—Ç–æ", callback_data=f"{base}:photoclip_last")],
        [InlineKeyboardButton("üé§ –ö–ª–∏–ø —Å –≤–æ–∫–∞–ª–æ–º / lip-sync", callback_data=f"{base}:vocalclip_prompt")],
        [InlineKeyboardButton("üé¨ –ö–∏–Ω–µ–º–∞—Ç–æ–≥—Ä–∞—Ñ–∏—á–Ω—ã–π –∫–ª–∏–ø", callback_data=f"{base}:pc_preset_cinematic")],
        [InlineKeyboardButton("üì± Reels / Shorts 9:16", callback_data=f"{base}:pc_preset_reels")],
        [InlineKeyboardButton("üèù Travel / luxury –∫–ª–∏–ø", callback_data=f"{base}:pc_preset_luxury")],
        [InlineKeyboardButton("üíÉ –ú—É–∑—ã–∫–∞–ª—å–Ω—ã–π –∫–ª–∏–ø", callback_data=f"{base}:pc_preset_music")],
        [InlineKeyboardButton("üì£ –†–µ–∫–ª–∞–º–Ω—ã–π –∫–ª–∏–ø", callback_data=f"{base}:pc_preset_ads")],
        [InlineKeyboardButton("üìù –°–≤–æ–π —Å—Ü–µ–Ω–∞—Ä–∏–π", callback_data=f"{base}:photoclip_custom")],
        [InlineKeyboardButton("‚¨ÖÔ∏è –ù–∞–∑–∞–¥ –≤ –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", callback_data="mode:fun" if prefix == "act" else "fun:back")],
    ])


def _photoclip_menu_text() -> str:
    return (
        "üé§ *AI-–≤–∏–¥–µ–æ–∫–ª–∏–ø / –ø–µ—Å–Ω—è*\n"
        "–§–æ—Ç–æ –æ–¥–Ω–æ–≥–æ –∏–ª–∏ –Ω–µ—Å–∫–æ–ª—å–∫–∏—Ö –ª—é–¥–µ–π ‚Üí –º—É–∑—ã–∫–∞–ª—å–Ω—ã–π –∫–ª–∏–ø —á–µ—Ä–µ–∑ Kling + Suno.\n\n"
        "–ú–æ–∂–Ω–æ —Å–¥–µ–ª–∞—Ç—å –∏–Ω—Å—Ç—Ä—É–º–µ–Ω—Ç–∞–ª—å–Ω—ã–π –∫–ª–∏–ø –∏–ª–∏ –∫–ª–∏–ø —Å –≤–æ–∫–∞–ª–æ–º/lip-sync. "
        "–í –æ–ø–∏—Å–∞–Ω–∏–∏ —É–∫–∞–∂–∏—Ç–µ, –∫—Ç–æ –ø–æ—ë—Ç: –Ω–∞–ø—Ä–∏–º–µ—Ä ¬´–∂–µ–Ω—â–∏–Ω–∞ ‚Äî –∂–µ–Ω—Å–∫–∏–π –≤–æ–∫–∞–ª, –º—É–∂—á–∏–Ω–∞ ‚Äî –º—É–∂—Å–∫–æ–π –≤–æ–∫–∞–ª; –ø—Ä–∏–ø–µ–≤ –ø–æ—é—Ç –≤–º–µ—Å—Ç–µ¬ª. "
        "–¢–∞–∫–∂–µ –º–æ–∂–Ω–æ –∑–∞–¥–∞—Ç—å –¥–≤–∏–∂–µ–Ω–∏—è, –≤–∑–∞–∏–º–æ–¥–µ–π—Å—Ç–≤–∏–µ –≥–µ—Ä–æ–µ–≤, —Å—Ç–∏–ª—å, —è–∑—ã–∫, –¥–ª–∏—Ç–µ–ª—å–Ω–æ—Å—Ç—å –∏ —Ñ–æ—Ä–º–∞—Ç.\n\n"
        "–î–ª–∏–Ω–Ω—ã–π –∏–Ω—Å—Ç—Ä—É–º–µ–Ω—Ç–∞–ª—å–Ω—ã–π –∫–ª–∏–ø —Å–æ–±–∏—Ä–∞–µ—Ç—Å—è –∏–∑ –∫–æ—Ä–æ—Ç–∫–∏—Ö —Å—Ü–µ–Ω. "
        "–í–æ–∫–∞–ª—å–Ω—ã–π lip-sync –ø–æ–∫–∞ –¥–æ—Å—Ç—É–ø–µ–Ω –¥–ª—è –æ–¥–Ω–æ–≥–æ —Ñ—Ä–∞–≥–º–µ–Ω—Ç–∞ –¥–æ 10 —Å–µ–∫—É–Ω–¥: —Å–±–æ—Ä–∫–∞ –¥–ª–∏–Ω–Ω—ã—Ö –≤–æ–∫–∞–ª—å–Ω—ã—Ö –∫–ª–∏–ø–æ–≤ –ø—Ä–æ—Ö–æ–¥–∏—Ç –ø—Ä–æ–≤–µ—Ä–∫—É. "
        "–†–µ–∫–æ–º–µ–Ω–¥—É–µ–º—ã–π —Ñ–æ—Ä–º–∞—Ç ‚Äî 9:16."
    )


def _clip_wants_vocals(prompt: str) -> bool:
    t = (prompt or "").lower().replace("—ë", "–µ")
    no_vocals = re.search(r"(–±–µ–∑\s+(?:–≤–æ–∫–∞–ª|–≥–æ–ª–æ—Å|–ø–µ–Ω–∏)|–∏–Ω—Å—Ç—Ä—É–º–µ–Ω—Ç–∞–ª|instrumental|–º–∏–Ω—É—Å–æ–≤)", t, re.I)
    explicit_singer = re.search(r"(–ø–æ–µ—Ç|–ø–æ—é—Ç|–ø–æ—é|–ø–æ–µ–º|–ø–æ–µ—à—å|–ø–µ—Ç—å|sings?|singer|–¥—É—ç—Ç|duet|–∂–µ–Ω—Å–∫\w*\s+–≤–æ–∫–∞–ª|–º—É–∂—Å–∫\w*\s+–≤–æ–∫–∞–ª|—Å\s+–≤–æ–∫–∞–ª–æ–º|with\s+vocals?)", t, re.I)
    if no_vocals and not explicit_singer:
        return False
    return bool(re.search(r"(–≤–æ–∫–∞–ª|–ø–æ–µ—Ç|–ø–æ—é—Ç|–ø–æ—é|–ø–æ–µ–º|–ø–æ–µ—à—å|–ø–µ—Ç—å|–ø–µ—Å–Ω—è|–ø–µ—Å–Ω—é|–ø—Ä–∏–ø–µ–≤|–∫—É–ø–ª–µ—Ç|lip[ -]?sync|sing|singer|duet|–¥—É—ç—Ç|–º—É–∂—Å–∫(?:–æ–π|–∏–º) –≥–æ–ª–æ—Å|–∂–µ–Ω—Å–∫(?:–∏–π|–∏–º) –≥–æ–ª–æ—Å)", t, re.I))


def _music_video_aspect(prompt: str) -> str:
    match = re.search(r"(?<!\d)(9|16|1|4|3)\s*[:/]\s*(16|9|1|5|4|3)(?!\d)", prompt or "")
    aspect = f"{match.group(1)}:{match.group(2)}" if match else "9:16"
    return aspect if aspect in {"9:16", "16:9", "1:1", "4:5", "3:4", "4:3"} else "9:16"


def _music_video_approval_kb(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("‚è± 10 —Å–µ–∫", callback_data=f"mv:dur10:{token}"),
         InlineKeyboardButton("30 —Å–µ–∫", callback_data=f"mv:dur30:{token}"),
         InlineKeyboardButton("60 —Å–µ–∫", callback_data=f"mv:dur60:{token}"),
         InlineKeyboardButton("90 —Å–µ–∫", callback_data=f"mv:dur90:{token}")],
        [InlineKeyboardButton("‚ú® –°–¥–µ–ª–∞—Ç—å –ø—Ä–æ–º–ø—Ç –∞–≤—Ç–æ–º–∞—Ç–∏—á–µ—Å–∫–∏", callback_data=f"mv:auto:{token}")],
        [InlineKeyboardButton("üéô –ü–æ –≥–æ–ª–æ—Å–æ–≤–æ–º—É –æ–ø–∏—Å–∞–Ω–∏—é", callback_data=f"mv:voice:{token}")],
        [InlineKeyboardButton("‚úÖ –£—Ç–≤–µ—Ä–∂–¥–∞—é", callback_data=f"mv:approve:{token}")],
        [InlineKeyboardButton("‚ûï –î–æ–ø–æ–ª–Ω–∏—Ç—å", callback_data=f"mv:augment:{token}")],
        [InlineKeyboardButton("‚úçÔ∏è –ù–∞–ø–∏—Å–∞—Ç—å –∑–∞–Ω–æ–≤–æ", callback_data=f"mv:rewrite:{token}")],
    ])


def _merge_music_video_prompt(original: str, addition: str) -> str:
    """Append a revision without deleting scene-local timing instructions."""
    original, addition = (original or "").strip(), (addition or "").strip()
    aspect_pattern = r"(?<!\d)(?:9|16|1|4|3)\s*[:/]\s*(?:16|9|1|5|4|3)(?!\d)"
    duration_match = re.search(
        r"(?i)(?:–¥–ª–∏—Ç–µ–ª—å–Ω–æ—Å—Ç—å(?:\s+(?:–∫–ª–∏–ø–∞|–≤–∏–¥–µ–æ))?|(?:clip|video)\s+duration)\s*[:‚Äî-]?\s*"
        r"(\d+(?:[.,]\d+)?)\s*(—Å–µ–∫\w*|seconds?|s|–º–∏–Ω\w*|minutes?|min)",
        addition,
    )
    music_brief, video_brief = _music_video_split_briefs(original)
    if duration_match:
        selected = _photo_clip_target_duration(duration_match.group(0))
        video_brief = _music_video_replace_duration_field(video_brief, selected)
        addition = (addition[:duration_match.start()] + addition[duration_match.end():]).strip(" ,;.")
    if re.search(aspect_pattern, addition):
        video_brief = re.sub(aspect_pattern, "", video_brief).strip(" ,;")
    if addition:
        video_brief = f"{video_brief.strip()}\n–î–æ–ø–æ–ª–Ω–µ–Ω–∏–µ: {addition}".strip()
    return _music_video_join_briefs(music_brief, video_brief)


def _music_video_split_briefs(prompt: str) -> tuple[str, str]:
    """Return (music_brief, video_brief) from the structured music-video prompt."""
    raw = (prompt or "").strip()
    marker_music = "[MUSIC_BRIEF]"
    marker_video = "[VIDEO_BRIEF]"
    if marker_music in raw and marker_video in raw:
        music = raw.split(marker_music, 1)[1].split(marker_video, 1)[0].strip()
        video = raw.split(marker_video, 1)[1].strip()
        return music, video
    return raw, raw


def _music_video_join_briefs(music_brief: str, video_brief: str) -> str:
    return f"[MUSIC_BRIEF]\n{(music_brief or '').strip()}\n\n[VIDEO_BRIEF]\n{(video_brief or '').strip()}".strip()


def _music_video_director_plan(video_brief: str, duration: int, scenes: int) -> str:
    """Preserve the user's video direction instead of replacing it with generic shot names."""
    brief = (video_brief or "").strip()
    if not brief:
        return "–°—Ü–µ–Ω–∞—Ä–∏–π –≤–∏–¥–µ–æ –µ—â—ë –Ω–µ –∑–∞–¥–∞–Ω."
    if scenes <= 1:
        # One short scene: show an explicit timing skeleton while preserving the brief verbatim.
        if duration <= 10:
            cuts = [(0, min(2, duration)), (min(2, duration), min(4, duration)),
                    (min(4, duration), min(6, duration)), (min(6, duration), duration)]
            labels = [
                "–Ω–∞—á–∞–ª–æ –¥–µ–π—Å—Ç–≤–∏—è –∏–∑ –æ–ø–∏—Å–∞–Ω–∏—è –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è",
                "–ø—Ä–æ–¥–æ–ª–∂–µ–Ω–∏–µ –¥–µ–π—Å—Ç–≤–∏—è; –∫–∞–º–µ—Ä–∞ —Å–ª–µ–¥—É–µ—Ç –ª–æ–≥–∏–∫–µ –æ–ø–∏—Å–∞–Ω–∏—è",
                "–ø–µ—Ä–µ—Ö–æ–¥/–¥–≤–∏–∂–µ–Ω–∏–µ –∫–∞–º–µ—Ä—ã –±–µ–∑ —Å–∞–º–æ–≤–æ–ª—å–Ω–æ–π —Å–º–µ–Ω—ã –º–µ—Å—Ç–∞",
                "–∑–∞–≤–µ—Ä—à–µ–Ω–∏–µ —Å—Ü–µ–Ω—ã —Å–æ–≥–ª–∞—Å–Ω–æ –æ–ø–∏—Å–∞–Ω–∏—é –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è",
            ]
            lines = []
            for (a, b), label in zip(cuts, labels):
                if b > a:
                    lines.append(f"0:{a:02d}‚Äì0:{b:02d} ‚Äî {label}.")
            return "\n".join(lines) + f"\n\n–¢–æ—á–Ω–æ–µ –∑–∞–¥–∞–Ω–∏–µ —Ä–µ–∂–∏—Å—Å—ë—Ä—É: {brief}"
        return f"0:00‚Äì0:{duration:02d} ‚Äî {brief}"
    scene_s = max(1, (duration + scenes - 1) // scenes)
    lines = []
    for i in range(scenes):
        a, b = i * scene_s, min(duration, (i + 1) * scene_s)
        if a >= duration:
            break
        lines.append(f"{a//60}:{a%60:02d}‚Äì{b//60}:{b%60:02d} ‚Äî –ø—Ä–æ–¥–æ–ª–∂–µ–Ω–∏–µ –µ–¥–∏–Ω–æ–≥–æ –¥–µ–π—Å—Ç–≤–∏—è: {brief}")
    return "\n".join(lines)


def _music_video_review_text(prompt: str, duration_s: int | None = None) -> str:
    music_brief, video_brief = _music_video_split_briefs(prompt)
    duration = (
        max(5, min(int(PHOTO_CLIP_MAX_DURATION_S or 90), int(duration_s)))
        if duration_s is not None else _photo_clip_target_duration(video_brief)
    )
    scene_s = max(5, min(10, int(PHOTO_CLIP_SCENE_SECONDS or 10)))
    scenes = max(1, min(PHOTO_CLIP_MAX_SCENES, (duration + scene_s - 1) // scene_s))
    vocal = _clip_wants_vocals(music_brief)
    plan = _music_video_director_plan(video_brief, duration, scenes)
    note = (
        f"\n\nüéû –î–ª–∏–Ω–Ω—ã–π –∫–ª–∏–ø –±—É–¥–µ—Ç —Å–æ–±—Ä–∞–Ω –∏–∑ {scenes} –ø–æ—Å–ª–µ–¥–æ–≤–∞—Ç–µ–ª—å–Ω—ã—Ö cinematic-—Å—Ü–µ–Ω –ø–æ ~{scene_s} —Å–µ–∫—É–Ω–¥ "
        "—Å –µ–¥–∏–Ω—ã–º Character Identity Pack –∏ continuity –º–µ–∂–¥—É —Å—Ü–µ–Ω–∞–º–∏."
        if scenes > 1 else "\n\n–ì–µ–Ω–µ—Ä–∞—Ü–∏—è –Ω–∞—á–Ω—ë—Ç—Å—è —Ç–æ–ª—å–∫–æ –ø–æ—Å–ª–µ —É—Ç–≤–µ—Ä–∂–¥–µ–Ω–∏—è —Å—Ü–µ–Ω–∞—Ä–∏—è."
    )
    return (
        "üé¨ –°—Ü–µ–Ω–∞—Ä–∏–π AI-–≤–∏–¥–µ–æ–∫–ª–∏–ø–∞ –Ω–∞ —É—Ç–≤–µ—Ä–∂–¥–µ–Ω–∏–µ\n\n"
        f"üéµ –ü–ï–°–ù–Ø\n{music_brief[:1400]}\n\n"
        f"üé• –ö–õ–ò–ü\n{video_brief[:1400]}\n\n"
        f"–ü–∞—Ä–∞–º–µ—Ç—Ä—ã: {duration} —Å–µ–∫—É–Ω–¥ ¬∑ {scenes} —Å—Ü–µ–Ω ¬∑ —Ñ–æ—Ä–º–∞—Ç {_music_video_aspect(prompt)}.\n\n"
        f"üéû –†–ï–ñ–ò–°–°–Å–†–°–ö–ê–Ø –†–ê–ó–ë–ò–í–ö–ê\n{plan}{note}"
    )[:4000]

def _music_video_replace_duration_field(video_brief: str, seconds: int) -> str:
    """Replace only the explicit clip-duration field; preserve scene/action timings."""
    text = (video_brief or "").strip()
    text = re.sub(
        r"(?im)^\s*(?:–¥–ª–∏—Ç–µ–ª—å–Ω–æ—Å—Ç—å\s+(?:–∫–ª–∏–ø–∞|–≤–∏–¥–µ–æ)|(?:clip|video)\s+duration)\s*[:‚Äî-]?\s*"
        r"\d+(?:[.,]\d+)?\s*(?:—Å–µ–∫\w*|seconds?|s|–º–∏–Ω\w*|minutes?|min)\s*[.!]?\s*$",
        "",
        text,
    ).strip()
    return f"–î–ª–∏—Ç–µ–ª—å–Ω–æ—Å—Ç—å –∫–ª–∏–ø–∞: {int(seconds)} —Å–µ–∫—É–Ω–¥.\n{text}".strip()


async def _stage_music_video_draft(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str = "",
    *,
    music_brief: str | None = None,
    video_brief: str | None = None,
    selected_duration_s: int | None = None,
) -> bool:
    """Stage a structured draft. Music and video instructions are deliberately isolated."""
    if music_brief is None or video_brief is None:
        parsed_music, parsed_video = _music_video_split_briefs(prompt)
        music_brief = parsed_music if music_brief is None else music_brief
        video_brief = parsed_video if video_brief is None else video_brief
    music_brief, video_brief = (music_brief or "").strip(), (video_brief or "").strip()
    if not music_brief:
        await update.effective_message.reply_text("–°–Ω–∞—á–∞–ª–∞ –æ–ø–∏—à–∏—Ç–µ –ø–µ—Å–Ω—é: –∂–∞–Ω—Ä, –Ω–∞—Å—Ç—Ä–æ–µ–Ω–∏–µ, —è–∑—ã–∫, —Ç–µ–º—É –∏ –≤–æ–∫–∞–ª.")
        return False
    if not video_brief:
        context.user_data["music_video_music_brief"] = music_brief
        context.user_data["awaiting_music_video_video_brief"] = True
        await update.effective_message.reply_text(
            "üé• –¢–µ–ø–µ—Ä—å –æ—Ç–¥–µ–ª—å–Ω–æ –æ–ø–∏—à–∏—Ç–µ, —á—Ç–æ –¥–æ–ª–∂–Ω–æ –ø—Ä–æ–∏—Å—Ö–æ–¥–∏—Ç—å –í –ö–õ–ò–ü–ï: –¥–µ–π—Å—Ç–≤–∏—è –≥–µ—Ä–æ—è, –º–µ—Å—Ç–æ, –¥–≤–∏–∂–µ–Ω–∏–µ –∫–∞–º–µ—Ä—ã, —Å–≤–µ—Ç, –∞–≤—Ç–æ–º–æ–±–∏–ª—å/–ø—Ä–µ–¥–º–µ—Ç—ã, —Ñ–∏–Ω–∞–ª—å–Ω—ã–π –∫–∞–¥—Ä.\n\n"
            "–≠—Ç–∞ —á–∞—Å—Ç—å –Ω–µ –±—É–¥–µ—Ç –æ—Ç–ø—Ä–∞–≤–ª—è—Ç—å—Å—è –≤ Suno."
        )
        return False
    duration = (
        max(5, min(int(PHOTO_CLIP_MAX_DURATION_S or 90), int(selected_duration_s)))
        if selected_duration_s is not None else _photo_clip_target_duration(video_brief)
    )
    if selected_duration_s is not None:
        video_brief = _music_video_replace_duration_field(video_brief, duration)
    combined = _music_video_join_briefs(music_brief, video_brief)
    # A new draft is a new audio review transaction. Never inherit an approved token
    # from a previous clip/test; explicit saved-song selection happens through its own action.
    context.user_data.pop("vocal_source_token", None)
    context.user_data.pop("music_video_pending_audio_token", None)
    pack_fn = globals().get("_music_video_identity_pack")
    complete_fn = globals().get("_music_video_identity_complete")
    if callable(pack_fn) and callable(complete_fn):
        refs = pack_fn(update.effective_user.id)
        img = refs.get("scene_reference") or _get_cached_photo(update.effective_user.id)
        if not complete_fn(update.effective_user.id):
            await update.effective_message.reply_text(
                "–î–ª—è high-fidelity AI-–≤–∏–¥–µ–æ–∫–ª–∏–ø–∞ —Å–Ω–∞—á–∞–ª–∞ —Å–æ–±–µ—Ä–∏—Ç–µ Character Identity Pack: "
                "FACE_FRONT + FACE_3Q + BODY_FULL + SCENE_REFERENCE."
            )
            return False
    else:  # isolated legacy unit-test harness only; production always defines the helpers above.
        refs = {}
        img = _get_cached_photo(update.effective_user.id)
        if not img:
            await update.effective_message.reply_text("–°–Ω–∞—á–∞–ª–∞ –∑–∞–≥—Ä—É–∑–∏—Ç–µ —Ñ–æ—Ç–æ –¥–ª—è AI-–≤–∏–¥–µ–æ–∫–ª–∏–ø–∞.")
            return False
    token = uuid.uuid4().hex[:12]
    for key in ("awaiting_photo_clip_prompt", "awaiting_vocal_clip_prompt", "awaiting_music_video_video_brief",
                "music_video_music_brief", "music_video_draft_edit"):
        context.user_data.pop(key, None)
    context.user_data["music_video_draft"] = {
        "prompt": combined, "music_brief": music_brief, "video_brief": video_brief,
        "token": token, "photo_digest": hashlib.sha256(img).hexdigest(),
        "identity_digests": {k: hashlib.sha256(v).hexdigest() for k, v in refs.items()} if refs else {},
        "duration": duration,
        "duration_locked": selected_duration_s is not None,
    }
    with contextlib.suppress(Exception):
        _mode_track_set(update.effective_user.id, "")
        kv_set(f"music_video_music_brief:{update.effective_user.id}", "")
    source_token = context.user_data.get("vocal_source_token")
    source_note = (
        "\n\nüéµ –î–ª—è —ç—Ç–æ–≥–æ –∫–ª–∏–ø–∞ –≤—ã–±—Ä–∞–Ω–∞ —Å–æ—Ö—Ä–∞–Ω—ë–Ω–Ω–∞—è –ø–æ–ª–Ω–∞—è –ø–µ—Å–Ω—è Suno; –Ω–æ–≤—É—é –ø–µ—Å–Ω—é –Ω–µ —Å–æ–∑–¥–∞—é."
        if _clip_wants_vocals(music_brief) and source_token
        and _load_vocal_artifact(update.effective_user.id, source_token, "audio") else ""
    )
    await update.effective_message.reply_text(
        (_music_video_review_text(combined, duration) + source_note)[:4096],
        reply_markup=_music_video_approval_kb(token)
    )
    return True

async def _on_music_video_draft_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = (q.data or "").split(":")
    draft = context.user_data.get("music_video_draft")
    if len(parts) != 3 or not draft or parts[2] != draft.get("token"):
        await q.answer("–°—Ü–µ–Ω–∞—Ä–∏–π —É—Å—Ç–∞—Ä–µ–ª")
        return
    action = parts[1]
    if action in ("dur10", "dur30", "dur60", "dur90"):
        seconds = int(action[3:])
        music_brief, video_brief = _music_video_split_briefs(draft["prompt"])
        # Duration buttons are authoritative. Strip old duration declarations with a
        # real regex (the previous raw string was double-escaped and silently failed).
        video_brief = _music_video_replace_duration_field(video_brief, seconds)
        draft["prompt"] = _music_video_join_briefs(music_brief, video_brief)
        draft["music_brief"] = music_brief
        draft["video_brief"] = video_brief
        draft["duration"] = seconds
        draft["duration_locked"] = True
        context.user_data["music_video_draft"] = draft
        await q.answer(f"–í—ã–±—Ä–∞–Ω–æ: {seconds} —Å–µ–∫—É–Ω–¥")
        with contextlib.suppress(Exception):
            await q.message.edit_text(_music_video_review_text(draft["prompt"], seconds)[:4096], reply_markup=_music_video_approval_kb(draft["token"]))
        return
    if action == "voice":
        context.user_data["music_video_draft_edit"] = "voice_rewrite"
        await q.answer("–ñ–¥—É –≥–æ–ª–æ—Å–æ–≤–æ–µ")
        await q.message.reply_text("üéô –û—Ç–ø—Ä–∞–≤—å—Ç–µ –≥–æ–ª–æ—Å–æ–≤–æ–µ —Å–æ–æ–±—â–µ–Ω–∏–µ —Å —Ç–µ–º, —á—Ç–æ —Ö–æ—Ç–∏—Ç–µ —É—Å–ª—ã—à–∞—Ç—å –∏ —É–≤–∏–¥–µ—Ç—å. –Ø –ø—Ä–µ–≤—Ä–∞—â—É –µ–≥–æ –≤ —Å—Ç—Ä—É–∫—Ç—É—Ä–∏—Ä–æ–≤–∞–Ω–Ω—ã–π –ø—Ä–æ–º–ø—Ç –∏ –ø—Ä–∏—à–ª—é –Ω–∞ –æ–¥–Ω–æ —É—Ç–≤–µ—Ä–∂–¥–µ–Ω–∏–µ.")
        return
    if action == "auto":
        seconds = int(draft.get("duration") or _photo_clip_target_duration(draft["prompt"]))
        music_brief, video_brief = _music_video_split_briefs(draft["prompt"])
        await q.answer("–ì–æ—Ç–æ–≤–ª—é –ø—Ä–æ–º–ø—Ç")
        generated = await ask_openai_text(
            "–ü–µ—Ä–µ–ø–∏—à–∏ –¥–≤–∞ –±—Ä–∏—Ñ–∞ –¥–ª—è –≥–µ–Ω–µ—Ä–∞—Ç–æ—Ä–æ–≤. –°–æ—Ö—Ä–∞–Ω–∏ –≤—Å–µ —Ñ–∞–∫—Ç—ã –∏ –Ω–∞–º–µ—Ä–µ–Ω–∏—è –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è, –Ω–∏—á–µ–≥–æ –Ω–æ–≤–æ–≥–æ —Å—é–∂–µ—Ç–Ω–æ –Ω–µ –¥–æ–±–∞–≤–ª—è–π. "
            f"–í–∏–¥–µ–æ –¥–ª–∏—Ç—Å—è —Ä–æ–≤–Ω–æ {seconds} —Å–µ–∫—É–Ω–¥: —Ä–∞–∑–±–µ–π VIDEO_BRIEF –Ω–∞ —Ö—Ä–æ–Ω–æ–ª–æ–≥–∏—á–µ—Å–∫–∏–µ 10-—Å–µ–∫—É–Ω–¥–Ω—ã–µ –±–ª–æ–∫–∏ —Å —è–≤–Ω—ã–º–∏ START/END states –∏ continuity. "
            "MUSIC_BRIEF —Å–¥–µ–ª–∞–π –∫–æ–º–ø–∞–∫—Ç–Ω—ã–º –∏ –ø—Ä–∏–≥–æ–¥–Ω—ã–º –¥–ª—è Suno. –í–µ—Ä–Ω–∏ —Å—Ç—Ä–æ–≥–æ [MUSIC_BRIEF] –∑–∞—Ç–µ–º [VIDEO_BRIEF].\n\n"
            + draft["prompt"],
            user_id=q.from_user.id, chat_id=q.message.chat_id,
            extra_system="–¢—ã prompt-director –¥–ª—è AI music video. –ù–µ –º–µ–Ω—è–π –∏–¥–µ–Ω—Ç–∏—á–Ω–æ—Å—Ç—å, —Ä–æ–ª–∏, —Ä–µ–∫–≤–∏–∑–∏—Ç –∏ –ø–æ—Å–ª–µ–¥–æ–≤–∞—Ç–µ–ª—å–Ω–æ—Å—Ç—å –¥–µ–π—Å—Ç–≤–∏–π –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è."
        )
        if "[MUSIC_BRIEF]" in generated and "[VIDEO_BRIEF]" in generated:
            music_brief, video_brief = _music_video_split_briefs(generated)
            video_brief = _music_video_replace_duration_field(video_brief, seconds)
            draft["prompt"] = _music_video_join_briefs(music_brief, video_brief)
            draft["music_brief"] = music_brief
            draft["video_brief"] = video_brief
            draft["duration"] = seconds
            context.user_data["music_video_draft"] = draft
            await q.message.edit_text(_music_video_review_text(draft["prompt"], seconds)[:4096], reply_markup=_music_video_approval_kb(draft["token"]))
        else:
            await q.message.reply_text("–ù–µ —É–¥–∞–ª–æ—Å—å –±–µ–∑–æ–ø–∞—Å–Ω–æ —Å—Ç—Ä—É–∫—Ç—É—Ä–∏—Ä–æ–≤–∞—Ç—å –ø—Ä–æ–º–ø—Ç. –ò—Å—Ö–æ–¥–Ω—ã–π —á–µ—Ä–Ω–æ–≤–∏–∫ —Å–æ—Ö—Ä–∞–Ω—ë–Ω.")
        return
    if action in ("augment", "rewrite"):
        context.user_data["music_video_draft_edit"] = action
        await q.answer("–ñ–¥—É —Ç–µ–∫—Å—Ç")
        await q.message.reply_text(
            "‚ûï –ù–∞–ø–∏—à–∏—Ç–µ, —á—Ç–æ –¥–æ–±–∞–≤–∏—Ç—å –∏–ª–∏ –∏–∑–º–µ–Ω–∏—Ç—å –≤ —Å—Ü–µ–Ω–∞—Ä–∏–∏." if action == "augment"
            else "‚úçÔ∏è –ù–∞–ø–∏—à–∏—Ç–µ —Å—Ü–µ–Ω–∞—Ä–∏–π –∑–∞–Ω–æ–≤–æ. –¢–µ–∫—É—â–µ–µ —Ñ–æ—Ç–æ —Å–æ—Ö—Ä–∞–Ω–∏—Ç—Å—è."
        )
        return
    if action != "approve":
        await q.answer("–ù–µ–∏–∑–≤–µ—Å—Ç–Ω–æ–µ –¥–µ–π—Å—Ç–≤–∏–µ")
        return
    pack_fn = globals().get("_music_video_identity_pack")
    complete_fn = globals().get("_music_video_identity_complete")
    if callable(pack_fn) and callable(complete_fn):
        refs = pack_fn(q.from_user.id)
        img = refs.get("scene_reference")
        invalid_photo = (
            not complete_fn(q.from_user.id) or not img
            or hashlib.sha256(img).hexdigest() != draft.get("photo_digest")
            or {k: hashlib.sha256(v).hexdigest() for k, v in refs.items()} != draft.get("identity_digests")
        )
    else:  # isolated legacy unit-test harness
        img = _get_cached_photo(q.from_user.id)
        invalid_photo = not img or hashlib.sha256(img).hexdigest() != draft.get("photo_digest")
    if invalid_photo:
        context.user_data.pop("music_video_draft", None)
        context.user_data.pop("music_video_draft_edit", None)
        await q.answer("–§–æ—Ç–æ –∏–∑–º–µ–Ω–∏–ª–æ—Å—å")
        await q.message.reply_text("–§–æ—Ç–æ –¥–ª—è —Å—Ü–µ–Ω–∞—Ä–∏—è –∏–∑–º–µ–Ω–∏–ª–æ—Å—å. –ü—Ä–∏—à–ª–∏—Ç–µ –æ–ø–∏—Å–∞–Ω–∏–µ –∫–ª–∏–ø–∞ –µ—â—ë —Ä–∞–∑, —á—Ç–æ–±—ã —É—Ç–≤–µ—Ä–¥–∏—Ç—å –µ–≥–æ —Å –Ω–æ–≤—ã–º —Ñ–æ—Ç–æ.")
        return
    prompt = draft["prompt"]
    seconds = int(draft.get("duration") or _photo_clip_target_duration(prompt))
    music_brief, video_brief = _music_video_split_briefs(prompt)
    video_brief = _music_video_replace_duration_field(video_brief, seconds)
    prompt = _music_video_join_briefs(music_brief, video_brief)
    # Consume the token before entering billing/provider code: repeated taps cannot launch duplicates.
    context.user_data.pop("music_video_draft", None)
    context.user_data.pop("music_video_draft_edit", None)
    await q.answer("–ó–∞–ø—É—Å–∫–∞—é –∫–ª–∏–ø")
    await q.message.reply_text("‚úÖ –°—Ü–µ–Ω–∞—Ä–∏–π —É—Ç–≤–µ—Ä–∂–¥—ë–Ω. –ü–µ—Ä–µ–¥–∞—é –µ–≥–æ –≤ —Ä–µ–∂–∏–º AI-–≤–∏–¥–µ–æ–∫–ª–∏–ø–∞.")
    try:
        if _clip_wants_vocals(prompt):
            await _start_vocal_clip(update, context, img, prompt, target_duration_s=seconds)
        else:
            await _start_photo_music_clip(update, context, img, prompt, target_duration_s=seconds)
    except Exception:
        log.exception("music video draft approval failed")
        await q.message.reply_text("‚ùå –ù–µ —É–¥–∞–ª–æ—Å—å –∑–∞–ø—É—Å—Ç–∏—Ç—å –∫–ª–∏–ø. –ö—Ä–µ–¥–∏—Ç—ã –∑–∞ –Ω–µ–∑–∞–≤–µ—Ä—à—ë–Ω–Ω—É—é –≥–µ–Ω–µ—Ä–∞—Ü–∏—é –Ω–µ —Å–ø–∏—Å–∞–Ω—ã. –ü–æ–ø—Ä–æ–±—É–π—Ç–µ —Å–Ω–æ–≤–∞.")


def _photoclip_preset_prompt(kind: str) -> str:
    kind = (kind or "").strip().lower()
    presets = {
        "cinematic": "cinematic portrait music video, slow dolly-in camera movement, realistic face and body motion, soft dramatic light, shallow depth of field, premium film look, 5 seconds, vertical 9:16",
        "reels": "viral Reels/Shorts style clip, energetic camera movement, modern social media pacing, confident pose, dynamic background motion, clean realistic look, 5 seconds, vertical 9:16",
        "luxury": "luxury travel music video, tropical premium lifestyle mood, warm sunset light, smooth camera movement, elegant cinematic motion, realistic identity preservation, 5 seconds, vertical 9:16",
        "music": "music video performance, the person moves naturally to the beat, expressive face, subtle body movement, dynamic camera, stylish lighting, realistic cinematic clip, 5 seconds, vertical 9:16",
        "ads": "premium advertising video clip, product/commercial style, confident natural movement, clean composition, luxury brand look, smooth camera motion, realistic high quality, 5 seconds, vertical 9:16",
    }
    return presets.get(kind, presets["cinematic"])




def _vocal_clip_menu_text() -> str:
    return (
        "üé§ *–ö–ª–∏–ø —Å –≤–æ–∫–∞–ª–æ–º / lip-sync (1 —á–µ–ª–æ–≤–µ–∫)*\n\n"
        "–≠—Ç–æ—Ç —Ä–µ–∂–∏–º –Ω—É–∂–µ–Ω, –∫–æ–≥–¥–∞ –ø–µ—Ä—Å–æ–Ω–∞–∂ –Ω–∞ —Ñ–æ—Ç–æ –¥–æ–ª–∂–µ–Ω *–ø–µ—Ç—å –ø–æ–¥ –≤–æ–∫–∞–ª*. "
        "–î–ª—è —Å—Ç–∞–±–∏–ª—å–Ω–æ–≥–æ —Ä–µ–∑—É–ª—å—Ç–∞—Ç–∞ —Ä–∞–±–æ—Ç–∞–µ—Ç —Ç–æ–ª—å–∫–æ —Å *–æ–¥–Ω–∏–º —á–µ–ª–æ–≤–µ–∫–æ–º –≤ –∫–∞–¥—Ä–µ*.\n\n"
        "–ü–æ—Å–ª–µ–¥–æ–≤–∞—Ç–µ–ª—å–Ω–æ—Å—Ç—å:\n"
        "1) –∑–∞–≥—Ä—É–∑–∏—Ç–µ —Ñ—Ä–æ–Ω—Ç–∞–ª—å–Ω—ã–π –ø–æ—Ä—Ç—Ä–µ—Ç –æ–¥–Ω–æ–≥–æ —á–µ–ª–æ–≤–µ–∫–∞;\n"
        "2) –æ–ø–∏—à–∏—Ç–µ –ø–µ—Å–Ω—é: —Å—Ç–∏–ª—å, –Ω–∞—Å—Ç—Ä–æ–µ–Ω–∏–µ, —è–∑—ã–∫, –ø—Ä–∏–ø–µ–≤, –¥–ª–∏—Ç–µ–ª—å–Ω–æ—Å—Ç—å;\n"
        "3) –±–æ—Ç –≥–µ–Ω–µ—Ä–∏—Ä—É–µ—Ç –≤–æ–∫–∞–ª —á–µ—Ä–µ–∑ Suno;\n"
        "4) –∑–∞—Ç–µ–º –¥–µ–ª–∞–µ—Ç lip-sync —á–µ—Ä–µ–∑ Kling Avatar.\n\n"
        "–í–∞–∂–Ω–æ: –µ—Å–ª–∏ –Ω–∞ —Ñ–æ—Ç–æ –¥–≤–∞ —á–µ–ª–æ–≤–µ–∫–∞, –∫–∞—á–µ—Å—Ç–≤–æ lip-sync —Ä–µ–∑–∫–æ –ø–∞–¥–∞–µ—Ç. –î–ª—è –¥—É—ç—Ç–∞ –ª—É—á—à–µ –¥–µ–ª–∞—Ç—å –¥–≤–µ –æ—Ç–¥–µ–ª—å–Ω—ã–µ —Å—Ü–µ–Ω—ã –ø–æ –æ–¥–Ω–æ–º—É —á–µ–ª–æ–≤–µ–∫—É."
    )


def _vocal_clip_action_kb(prefix: str = "act") -> InlineKeyboardMarkup:
    base = "act:fun" if prefix == "act" else "fun"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("üì∏ –ó–∞–≥—Ä—É–∑–∏—Ç—å –ø–æ—Ä—Ç—Ä–µ—Ç 1 —á–µ–ª–æ–≤–µ–∫–∞", callback_data=f"{base}:vocalclip_upload")],
        [InlineKeyboardButton("‚úÖ –ò—Å–ø–æ–ª—å–∑–æ–≤–∞—Ç—å –ø–æ—Å–ª–µ–¥–Ω–µ–µ —Ñ–æ—Ç–æ", callback_data=f"{base}:vocalclip_last")],
        [InlineKeyboardButton("üìù –û–ø–∏—Å–∞—Ç—å –ø–µ—Å–Ω—é/–∫–ª–∏–ø", callback_data=f"{base}:vocalclip_prompt")],
        [InlineKeyboardButton("‚¨ÖÔ∏è –ù–∞–∑–∞–¥ –≤ –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", callback_data="mode:fun" if prefix == "act" else "fun:back")],
    ])


def _textvideo_menu_text() -> str:
    return (
        "üé¨ *–í–∏–¥–µ–æ –ø–æ —Ç–µ–∫—Å—Ç—É –∏–ª–∏ –≥–æ–ª–æ—Å—É*\n\n"
        "–û–ø–∏—à–∏—Ç–µ —Å—Ü–µ–Ω—É —Ç–µ–∫—Å—Ç–æ–º –∏–ª–∏ –æ—Ç–ø—Ä–∞–≤—å—Ç–µ voice ‚Äî –±–æ—Ç —Ä–∞—Å–ø–æ–∑–Ω–∞–µ—Ç —Ä–µ—á—å –∏ –∑–∞–ø—É—Å—Ç–∏—Ç –≥–µ–Ω–µ—Ä–∞—Ü–∏—é.\n\n"
        "–î–≤–∏–∂–∫–∏:\n"
        "‚Ä¢ *Sora 2 ‚Äî —Ç–æ–ª—å–∫–æ –±–µ–∑ –ª—é–¥–µ–π* ‚Äî –ø—Ä–µ–¥–º–µ—Ç—ã, –∂–∏–≤–æ—Ç–Ω—ã–µ, –∑–¥–∞–Ω–∏—è, –ø–µ–π–∑–∞–∂–∏, –∏–Ω—Ç–µ—Ä—å–µ—Ä.\n"
        "‚Ä¢ *Kling* ‚Äî –ª—é–¥–∏, –¥–∏–Ω–∞–º–∏–∫–∞, Reels/Shorts –∏ —É–Ω–∏–≤–µ—Ä—Å–∞–ª—å–Ω—ã–µ —Å—Ü–µ–Ω—ã.\n"
        "‚Ä¢ *Runway* ‚Äî –ª—é–¥–∏ –∏ –∫–∏–Ω–µ–º–∞—Ç–æ–≥—Ä–∞—Ñ–∏—á–Ω—ã–µ —Å—Ü–µ–Ω—ã; –æ—Ñ–∏—Ü–∏–∞–ª—å–Ω—ã–π Runway API –∏—Å–ø–æ–ª—å–∑—É–µ—Ç—Å—è –ø–µ—Ä–≤—ã–º, Comet –∏ Kling ‚Äî —Ä–µ–∑–µ—Ä–≤.\n\n"
        "–°—Ç–æ–∏–º–æ—Å—Ç—å –ø–æ–∫–∞–∑—ã–≤–∞–µ—Ç—Å—è –≤ –∫—Ä–µ–¥–∏—Ç–∞—Ö –∏ —Å–ø–∏—Å—ã–≤–∞–µ—Ç—Å—è —Ç–æ–ª—å–∫–æ –ø–æ—Å–ª–µ —É—Å–ø–µ—à–Ω–æ–≥–æ —Ä–µ–∑—É–ª—å—Ç–∞—Ç–∞."
    )


def _textvideo_action_kb(prefix: str = "act") -> InlineKeyboardMarkup:
    base = "act:fun" if prefix == "act" else "fun"
    rows = [
        [InlineKeyboardButton(f"üéû Sora 2 ¬∑ –±–µ–∑ –ª—é–¥–µ–π ¬∑ {_video_price_credits('sora', 5)} –∫—Ä.", callback_data=f"{base}:tv_engine_sora")],
        [InlineKeyboardButton(f"üé¨ Kling ¬∑ {_video_price_credits('kling', 5)} –∫—Ä.", callback_data=f"{base}:tv_engine_kling")],
    ]
    if TEXT_VIDEO_ALLOW_RUNWAY:
        rows.append([InlineKeyboardButton(f"üé• Runway ¬∑ {_video_price_credits('runway', 5)} –∫—Ä.", callback_data=f"{base}:tv_engine_runway")])
    rows.extend([
        [InlineKeyboardButton("üìù –í–≤–µ—Å—Ç–∏ —Ç–µ–∫—Å—Ç / üéô –æ—Ç–ø—Ä–∞–≤–∏—Ç—å voice", callback_data=f"{base}:tv_prompt")],
        [InlineKeyboardButton("‚¨ÖÔ∏è –ù–∞–∑–∞–¥ –≤ –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", callback_data="mode:fun" if prefix == "act" else "fun:back")],
    ])
    return InlineKeyboardMarkup(rows)

def _ai_selfie_action_kb(prefix: str = "act") -> InlineKeyboardMarkup:
    """–ü–æ–¥–º–µ–Ω—é Nano Banana/Gemini style AI selfie."""
    base = "act:fun" if prefix == "act" else "fun"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("üì∏ –ó–∞–≥—Ä—É–∑–∏—Ç—å —Å–≤–æ—ë —Å–µ–ª—Ñ–∏", callback_data=f"{base}:aiselfie_upload")],
        [InlineKeyboardButton("‚úÖ –ò—Å–ø–æ–ª—å–∑–æ–≤–∞—Ç—å –ø–æ—Å–ª–µ–¥–Ω–µ–µ —Ñ–æ—Ç–æ", callback_data=f"{base}:aiselfie_last")],
        [InlineKeyboardButton("‚≠ê –°–æ –∑–Ω–∞–º–µ–Ω–∏—Ç–æ—Å—Ç—å—é", callback_data=f"{base}:aiselfie_custom")],
        [InlineKeyboardButton("ü¶∏ –° –∫–∏–Ω–æ–≥–µ—Ä–æ–µ–º / –ø–µ—Ä—Å–æ–Ω–∞–∂–µ–º", callback_data=f"{base}:as_preset_character")],
        [InlineKeyboardButton("üé¨ –ö–∏–Ω–æ—Å—Ü–µ–Ω–∞ / –ø—Ä–µ–º—å–µ—Ä–∞", callback_data=f"{base}:as_preset_movie")],
        [InlineKeyboardButton("üèù Travel / luxury selfie", callback_data=f"{base}:as_preset_luxury")],
        [InlineKeyboardButton("üì£ –†–µ–∫–ª–∞–º–Ω—ã–π –∫–∞–¥—Ä", callback_data=f"{base}:as_preset_ads")],
        [InlineKeyboardButton("üìù –°–≤–æ–π –ø—Ä–æ–º–ø—Ç", callback_data=f"{base}:aiselfie_custom")],
        [InlineKeyboardButton("‚¨ÖÔ∏è –ù–∞–∑–∞–¥ –≤ –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", callback_data="mode:fun" if prefix == "act" else "fun:back")],
    ])


def _ai_selfie_menu_text() -> str:
    return (
        "ü§≥ *AI-—Å–µ–ª—Ñ–∏ —Å–æ –∑–≤–µ–∑–¥–æ–π / –ø–µ—Ä—Å–æ–Ω–∞–∂–µ–º*\n"
        "–ó–∞–≥—Ä—É–∑–∏—Ç–µ —Å–≤–æ—ë —Å–µ–ª—Ñ–∏, –∑–∞—Ç–µ–º –º–æ–¥–µ–ª—å –ø–µ—Ä–µ—Å–æ–±–µ—Ä—ë—Ç –Ω–æ–≤—É—é —Ä–µ–∞–ª–∏—Å—Ç–∏—á–Ω—É—é AI-—Ñ–æ—Ç–æ—Å—Ü–µ–Ω—É "
        "—Å –Ω—É–∂–Ω–æ–π –∑–Ω–∞–º–µ–Ω–∏—Ç–æ—Å—Ç—å—é, –ø–µ—Ä—Å–æ–Ω–∞–∂–µ–º, –ª–æ–∫–∞—Ü–∏–µ–π –∏–ª–∏ —Ä–µ–∫–ª–∞–º–Ω—ã–º —Å—é–∂–µ—Ç–æ–º, —Å—Ç–∞—Ä–∞—è—Å—å —Å–æ—Ö—Ä–∞–Ω–∏—Ç—å –≤–∞—à–µ –ª–∏—Ü–æ.\n\n"
        "–ö–∞–∫ –ø–æ–ª—å–∑–æ–≤–∞—Ç—å—Å—è:\n"
        "1) –∑–∞–≥—Ä—É–∑–∏—Ç–µ —Å–≤–æ—ë —Å–µ–ª—Ñ–∏ –∏–ª–∏ –∏—Å–ø–æ–ª—å–∑—É–π—Ç–µ –ø–æ—Å–ª–µ–¥–Ω–µ–µ —Ñ–æ—Ç–æ;\n"
        "2) –Ω–∞–ø–∏—à–∏—Ç–µ: `—Å–µ–ª—Ñ–∏ —Å ...`, –Ω–∞–ø—Ä–∏–º–µ—Ä: `—Å–µ–ª—Ñ–∏ —Å –∏–∑–≤–µ—Å—Ç–Ω—ã–º –∞–∫—Ç—ë—Ä–æ–º –Ω–∞ –∫—Ä–∞—Å–Ω–æ–π –¥–æ—Ä–æ–∂–∫–µ, iPhone selfie, 4:5`;\n"
        "3) –±–æ—Ç –≤–µ—Ä–Ω—ë—Ç –Ω–æ–≤—É—é AI-—Ñ–æ—Ç–æ–≥—Ä–∞—Ñ–∏—é.\n\n"
        "–î–ª—è –±–µ–∑–æ–ø–∞—Å–Ω–æ–≥–æ –∏—Å–ø–æ–ª—å–∑–æ–≤–∞–Ω–∏—è –Ω–µ –ø—Ä–∏–º–µ–Ω—è–π—Ç–µ —Ä–µ–∑—É–ª—å—Ç–∞—Ç –∫–∞–∫ –¥–æ–∫–∞–∑–∞—Ç–µ–ª—å—Å—Ç–≤–æ —Ä–µ–∞–ª—å–Ω–æ–π –≤—Å—Ç—Ä–µ—á–∏, —Ä–µ–∫–ª–∞–º—ã, –ø–æ–¥–¥–µ—Ä–∂–∫–∏ –∏–ª–∏ –Ω–æ–≤–æ—Å—Ç–∏."
    )


def _ai_selfie_preset_prompt(kind: str) -> str:
    kind = (kind or "").strip().lower()
    presets = {
        "character": "Create a realistic fan selfie with a famous movie character specified by the user. If no character is specified, ask the user to name the character. iPhone selfie look, natural lighting, realistic skin, same user's face and identity, no text, no logos, 4:5.",
        "movie": "Create a realistic red-carpet movie premiere selfie. The user is standing next to the named celebrity or actor. Premium event lighting, shallow depth of field, iPhone selfie perspective, same user's face and identity, no text, no logos, 4:5.",
        "luxury": "Create a luxury travel selfie. The user is posing with the named celebrity or public figure in a premium travel location, yacht/hotel/resort mood, natural iPhone selfie, same user's face and identity, no text, no logos, 4:5.",
        "ads": "Create a premium advertising style AI selfie/poster scene with the user and the named celebrity/character. High-end commercial photography, clean composition, same user's face and identity, no fake endorsement text, no logos, 4:5.",
    }
    return presets.get(kind, "")


def _is_ai_selfie_intent(text: str) -> bool:
    t = (text or "").lower().replace("—ë", "–µ")
    return bool(re.search(r"(ai[-\s]?—Å–µ–ª—Ñ–∏|–∞–∏[-\s]?—Å–µ–ª—Ñ–∏|—Å–µ–ª—Ñ–∏\s+—Å–æ\s+–∑–≤–µ–∑–¥|—Å–µ–ª—Ñ–∏\s+—Å\s+–∏–∑–≤–µ—Å—Ç–Ω|—Å–µ–ª—Ñ–∏\s+—Å\s+–∞–∫—Ç|—Å–µ–ª—Ñ–∏\s+—Å\s+–ø–µ–≤|—Å–µ–ª—Ñ–∏\s+—Å\s+–ø–µ—Ä—Å–æ–Ω–∞–∂|nano\s*banana|–Ω–∞–Ω–æ\s*–±–∞–Ω–∞–Ω|—Ñ–æ—Ç–æ\s+—Å–æ\s+–∑–≤–µ–∑–¥|—Ñ–æ—Ç–æ\s+—Å\s+–∑–Ω–∞–º–µ–Ω–∏—Ç|celebrity\s+selfie|ai\s+selfie)", t, re.I))


def _clean_ai_selfie_prompt(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^(?:—Å–¥–µ–ª–∞–π|—Å–æ–∑–¥–∞–π|—Å–≥–µ–Ω–µ—Ä–∏—Ä—É–π|–Ω–∞—Ä–∏—Å—É–π)?\s*(?:ai[-\s]?—Å–µ–ª—Ñ–∏|–∞–∏[-\s]?—Å–µ–ª—Ñ–∏|—Å–µ–ª—Ñ–∏|—Ñ–æ—Ç–æ|nano\s*banana|–Ω–∞–Ω–æ\s*–±–∞–Ω–∞–Ω|celebrity\s*selfie|ai\s*selfie)\s*[:Ôºö,-]?\s*", "", t, flags=re.I)
    return t.strip()


def _set_ai_selfie_wait(context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_ai_selfie_prompt"] = True
    context.user_data.pop("awaiting_avatar_script", None)
    context.user_data.pop("awaiting_photo_clip_prompt", None)




def _clear_vocal_clip_wait(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting_vocal_clip_photo", None)
    context.user_data.pop("awaiting_vocal_clip_prompt", None)
    context.user_data.pop("vocal_clip_preset_prompt", None)


def _set_vocal_clip_wait(context: ContextTypes.DEFAULT_TYPE):
    # First question is only about the song. Video direction is collected separately.
    context.user_data["awaiting_vocal_clip_prompt"] = True
    context.user_data.pop("awaiting_music_video_video_brief", None)
    context.user_data.pop("music_video_music_brief", None)


def _clear_text_video_wait(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting_text_video_prompt", None)


def _set_text_video_wait(context: ContextTypes.DEFAULT_TYPE, engine: str | None = None):
    context.user_data["awaiting_text_video_prompt"] = True
    if engine:
        context.user_data["text_video_engine"] = engine


async def _handle_vocalclip_upload_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, q, prefix: str = "act"):
    _clear_transient_flows(context)
    _set_mode_clean(q.from_user.id, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "vocalclip")
    context.user_data["awaiting_vocal_clip_photo"] = True
    await q.message.reply_text(
        "üé§ –ü—Ä–∏—à–ª–∏—Ç–µ —Ñ—Ä–æ–Ω—Ç–∞–ª—å–Ω—ã–π –ø–æ—Ä—Ç—Ä–µ—Ç *–æ–¥–Ω–æ–≥–æ —á–µ–ª–æ–≤–µ–∫–∞*. –ï—Å–ª–∏ –≤ –∫–∞–¥—Ä–µ –¥–≤–∞ —á–µ–ª–æ–≤–µ–∫–∞, lip-sync –±—É–¥–µ—Ç –Ω–µ—Å—Ç–∞–±–∏–ª—å–Ω—ã–º.",
        parse_mode="Markdown",
        reply_markup=_vocal_clip_action_kb(prefix),
    )


async def _handle_vocalclip_prompt_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, q, prefix: str = "act"):
    _clear_transient_flows(context)
    _set_mode_clean(q.from_user.id, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "vocalclip")
    img = _get_cached_photo(q.from_user.id)
    if img:
        _set_vocal_clip_wait(context)
        await q.answer("–ì–æ—Ç–æ–≤–æ")
        await q.message.reply_text(
            "üéµ –ò—Å–ø–æ–ª—å–∑—É—é –ø–æ—Å–ª–µ–¥–Ω–µ–µ —Ñ–æ—Ç–æ. –°–Ω–∞—á–∞–ª–∞ –æ—Ç–¥–µ–ª—å–Ω–æ –æ–ø–∏—à–∏—Ç–µ –ü–ï–°–ù–Æ: –∂–∞–Ω—Ä, –Ω–∞—Å—Ç—Ä–æ–µ–Ω–∏–µ, —è–∑—ã–∫, —Ç–µ–º—É —Ç–µ–∫—Å—Ç–∞, –Ω—É–∂–µ–Ω –ª–∏ –≤–æ–∫–∞–ª –∏ –∫–∞–∫–∏–º –≥–æ–ª–æ—Å–æ–º.\n\n"
            "–ü–æ—Å–ª–µ —ç—Ç–æ–≥–æ —è –æ—Ç–¥–µ–ª—å–Ω–æ —Å–ø—Ä–æ—à—É, —á—Ç–æ –¥–æ–ª–∂–Ω–æ –ø—Ä–æ–∏—Å—Ö–æ–¥–∏—Ç—å –≤ –∫–ª–∏–ø–µ."
        )
    else:
        context.user_data["awaiting_vocal_clip_photo"] = True
        await q.message.reply_text(
            "–°–Ω–∞—á–∞–ª–∞ –ø—Ä–∏—à–ª–∏—Ç–µ –ø–æ—Ä—Ç—Ä–µ—Ç –æ–¥–Ω–æ–≥–æ —á–µ–ª–æ–≤–µ–∫–∞. –ü–æ—Å–ª–µ –∑–∞–≥—Ä—É–∑–∫–∏ —è —Å–Ω–∞—á–∞–ª–∞ –ø–æ–ø—Ä–æ—à—É –æ–ø–∏—Å–∞–Ω–∏–µ –ø–µ—Å–Ω–∏, –∑–∞—Ç–µ–º –æ—Ç–¥–µ–ª—å–Ω–æ —Å—Ü–µ–Ω–∞—Ä–∏–π –≤–∏–¥–µ–æ.",
            reply_markup=_vocal_clip_action_kb(prefix),
        )


async def _handle_textvideo_engine_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, q, engine: str, prefix: str = "act"):
    _clear_transient_flows(context)
    _set_mode_clean(q.from_user.id, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "textvideo")
    engine = (engine or TEXT_VIDEO_DEFAULT_ENGINE or "kling").strip().lower()
    if engine == "runway" and not TEXT_VIDEO_ALLOW_RUNWAY:
        engine = "kling"
    if engine not in ("sora", "kling", "runway"):
        engine = "kling"
    _set_text_video_wait(context, engine)
    labels = {"sora": "Sora 2 ‚Äî —Ç–æ–ª—å–∫–æ –±–µ–∑ –ª—é–¥–µ–π", "kling": "Kling", "runway": "Runway"}
    await q.answer(labels[engine][:180])
    warning = "\n‚ö†Ô∏è –í –ø—Ä–æ–º–ø—Ç–µ –Ω–µ –¥–æ–ª–∂–Ω–æ –±—ã—Ç—å –ª—é–¥–µ–π, –ª–∏—Ü –∏–ª–∏ –ø–µ—Ä—Å–æ–Ω–∞–∂–µ–π." if engine == "sora" else ""
    await q.message.reply_text(
        f"‚úÖ –í—ã–±—Ä–∞–Ω –¥–≤–∏–∂–æ–∫: {labels[engine]}.{warning}\n"
        "–¢–µ–ø–µ—Ä—å –Ω–∞–ø–∏—à–∏—Ç–µ –ø—Ä–æ–º–ø—Ç –∏–ª–∏ –æ—Ç–ø—Ä–∞–≤—å—Ç–µ voice. –£–∫–∞–∂–∏—Ç–µ —Å—Ü–µ–Ω—É, —Å—Ç–∏–ª—å, –¥–ª–∏—Ç–µ–ª—å–Ω–æ—Å—Ç—å –∏ —Ñ–æ—Ä–º–∞—Ç: –Ω–∞–ø—Ä–∏–º–µ—Ä `10 —Å–µ–∫—É–Ω–¥, 16:9`."
    )


async def _handle_textvideo_prompt_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, q, prefix: str = "act"):
    _clear_transient_flows(context)
    _set_mode_clean(q.from_user.id, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "textvideo")
    _set_text_video_wait(context, context.user_data.get("text_video_engine") or TEXT_VIDEO_DEFAULT_ENGINE)
    await q.answer("–í–∏–¥–µ–æ")
    await q.message.reply_text(
        "üé¨ –ù–∞–ø–∏—à–∏—Ç–µ —Ç–µ–∫—Å—Ç–æ–≤—ã–π –ø—Ä–æ–º–ø—Ç –∏–ª–∏ –æ—Ç–ø—Ä–∞–≤—å—Ç–µ voice. –ü–æ —É–º–æ–ª—á–∞–Ω–∏—é –∏—Å–ø–æ–ª—å–∑—É—é Kling. "
        "–ú–æ–∂–Ω–æ —Å–Ω–∞—á–∞–ª–∞ –≤—ã–±—Ä–∞—Ç—å Sora 2 –±–µ–∑ –ª—é–¥–µ–π, Kling –∏–ª–∏ Runway –∫–Ω–æ–ø–∫–æ–π –≤—ã—à–µ."
    )

def _clear_ai_selfie_wait(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting_ai_selfie_prompt", None)
    context.user_data.pop("awaiting_ai_selfie_photo", None)
    context.user_data.pop("ai_selfie_preset_prompt", None)


async def _handle_avatar_upload_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, q, prefix: str = "act"):
    _clear_transient_flows(context)
    _set_mode_clean(q.from_user.id, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "avatar")
    context.user_data["awaiting_avatar_photo"] = True
    await q.message.reply_text(
        "üó£ –®–∞–≥ 1/3: –ø—Ä–∏—à–ª–∏—Ç–µ –ø–æ—Ä—Ç—Ä–µ—Ç —á–µ–ª–æ–≤–µ–∫–∞. –ü–æ—Å–ª–µ –∑–∞–≥—Ä—É–∑–∫–∏ —è –ø—Ä–µ–¥–ª–æ–∂—É –≤—ã–±—Ä–∞—Ç—å –≥–æ–ª–æ—Å, –∑–∞—Ç–µ–º –ø–æ–ø—Ä–æ—à—É —Ç–µ–∫—Å—Ç. –ï—Å–ª–∏ –Ω—É–∂–µ–Ω —Ä–µ–∞–ª—å–Ω—ã–π –≥–æ–ª–æ—Å, –µ–≥–æ –º–æ–∂–Ω–æ –±—É–¥–µ—Ç –ø—Ä–∏—Å–ª–∞—Ç—å –ø–æ—Å–ª–µ –ø–æ—Ä—Ç—Ä–µ—Ç–∞."
    )


async def _handle_avatar_script_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, q, prefix: str = "act", voice_mode: bool = False):
    _clear_transient_flows(context)
    _set_mode_clean(q.from_user.id, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "avatar")
    img = _get_cached_photo(q.from_user.id)
    if img:
        if voice_mode:
            _set_avatar_wait(context)
            await q.message.reply_text("üéô –ò—Å–ø–æ–ª—å–∑—É—é –ø–æ—Å–ª–µ–¥–Ω–µ–µ –∑–∞–≥—Ä—É–∂–µ–Ω–Ω–æ–µ —Ñ–æ—Ç–æ. –¢–µ–ø–µ—Ä—å –ø—Ä–∏—à–ª–∏—Ç–µ voice/audio –¥–ª—è —Ä–µ—á–∏ –∞–≤–∞—Ç–∞—Ä–∞.")
        else:
            _set_avatar_voice_choice_wait(context)
            await q.message.reply_text(_avatar_voice_choice_text(), reply_markup=_avatar_voice_choice_kb(prefix))
        await q.answer("–ì–æ—Ç–æ–≤–æ")
    else:
        context.user_data["awaiting_avatar_photo"] = True
        await q.message.reply_text(
            "–°–Ω–∞—á–∞–ª–∞ –ø—Ä–∏—à–ª–∏—Ç–µ –ø–æ—Ä—Ç—Ä–µ—Ç —á–µ–ª–æ–≤–µ–∫–∞. –ü–æ—Å–ª–µ –∑–∞–≥—Ä—É–∑–∫–∏ —è –ø—Ä–µ–¥–ª–æ–∂—É –≤—ã–±—Ä–∞—Ç—å –≥–æ–ª–æ—Å, –∑–∞—Ç–µ–º –ø–æ–ø—Ä–æ—à—É —Ç–µ–∫—Å—Ç. –î–ª—è —Ä–µ–∞–ª—å–Ω–æ–≥–æ –≥–æ–ª–æ—Å–∞ –º–æ–∂–Ω–æ –≤—ã–±—Ä–∞—Ç—å voice/audio —Ä–µ–∂–∏–º.",
            reply_markup=_avatar_action_kb(prefix),
        )


async def _handle_photoclip_upload_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, q, prefix: str = "act"):
    _clear_transient_flows(context)
    _set_mode_clean(q.from_user.id, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "photoclip")
    _music_video_identity_clear(q.from_user.id)
    _set_music_video_identity_wait(context, "face_front")
    await q.message.reply_text(
        "üéµ –§–æ—Ç–æ ‚Üí –≤–∏–¥–µ–æ–∫–ª–∏–ø ¬∑ Character Identity Pack\n\n"
        "–î–ª—è –º–∞–∫—Å–∏–º–∞–ª—å–Ω–æ–≥–æ —Å–æ—Ö—Ä–∞–Ω–µ–Ω–∏—è –≤–Ω–µ—à–Ω–æ—Å—Ç–∏ –∑–∞–≥—Ä—É–∑–∏—Ç–µ 3 –æ—Ç–¥–µ–ª—å–Ω—ã–µ —Ñ–æ—Ç–æ–≥—Ä–∞—Ñ–∏–∏ –ª–∏—á–Ω–æ—Å—Ç–∏, "
        "–∞ –∑–∞—Ç–µ–º –æ—Ç–¥–µ–ª—å–Ω—ã–π —Å—Ç–∞—Ä—Ç–æ–≤—ã–π –∫–∞–¥—Ä —Å—Ü–µ–Ω—ã.\n\n"
        "1/3 ‚Äî –∑–∞–≥—Ä—É–∑–∏—Ç–µ –ª–∏—Ü–æ –ê–ù–§–ê–°. –•–æ—Ä–æ—à–∏–π —Å–≤–µ—Ç, –ª–∏—Ü–æ –æ—Ç–∫—Ä—ã—Ç–æ, –±–µ–∑ —Ç–µ–ª–µ—Ñ–æ–Ω–∞ –ø–µ—Ä–µ–¥ –ª–∏—Ü–æ–º."
    )


async def _handle_photoclip_prompt_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, q, prefix: str = "act"):
    _clear_transient_flows(context)
    _set_mode_clean(q.from_user.id, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "photoclip")
    img = _get_cached_photo(q.from_user.id)
    if img:
        _set_photo_clip_wait(context)
        await q.message.reply_text("üéµ –ò—Å–ø–æ–ª—å–∑—É—é –ø–æ—Å–ª–µ–¥–Ω–µ–µ —Ñ–æ—Ç–æ. –°–Ω–∞—á–∞–ª–∞ –æ—Ç–¥–µ–ª—å–Ω–æ –æ–ø–∏—à–∏—Ç–µ –ü–ï–°–ù–Æ: –∂–∞–Ω—Ä, –Ω–∞—Å—Ç—Ä–æ–µ–Ω–∏–µ, —è–∑—ã–∫, —Ç–µ–º—É —Ç–µ–∫—Å—Ç–∞, –Ω—É–∂–µ–Ω –ª–∏ –≤–æ–∫–∞–ª –∏ –∫–∞–∫–∏–º –≥–æ–ª–æ—Å–æ–º. –ü–æ—Å–ª–µ —ç—Ç–æ–≥–æ —è –æ—Ç–¥–µ–ª—å–Ω–æ —Å–ø—Ä–æ—à—É, —á—Ç–æ –¥–æ–ª–∂–Ω–æ –ø—Ä–æ–∏—Å—Ö–æ–¥–∏—Ç—å –≤ –∫–ª–∏–ø–µ.")
        await q.answer("–ì–æ—Ç–æ–≤–æ")
    else:
        context.user_data["awaiting_photo_clip_photo"] = True
        await q.message.reply_text(
            "üéµ –°–Ω–∞—á–∞–ª–∞ –ø—Ä–∏—à–ª–∏—Ç–µ —Ñ–æ—Ç–æ —á–µ–ª–æ–≤–µ–∫–∞/–æ–±—ä–µ–∫—Ç–∞. –ü–æ—Å–ª–µ –∑–∞–≥—Ä—É–∑–∫–∏ —è –æ—Ç–¥–µ–ª—å–Ω–æ —Å–ø—Ä–æ—à—É —Å–Ω–∞—á–∞–ª–∞ –ü–ï–°–ù–Æ, –∑–∞—Ç–µ–º –í–ò–î–ï–û."
        )


async def _handle_photoclip_preset_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, q, kind: str, prefix: str = "act"):
    prompt = _photoclip_preset_prompt(kind)
    _clear_transient_flows(context)
    _set_mode_clean(q.from_user.id, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "photoclip")
    img = _get_cached_photo(q.from_user.id)
    if img:
        await q.answer("–°—Ü–µ–Ω–∞—Ä–∏–π –≥–æ—Ç–æ–≤")
        await _stage_music_video_draft(update, context, prompt)
    else:
        context.user_data["awaiting_photo_clip_photo"] = True
        context.user_data["photo_clip_preset_prompt"] = prompt
        await q.message.reply_text(
            "üé¨ –ü—Ä–µ—Å–µ—Ç –≤—ã–±—Ä–∞–Ω. –¢–µ–ø–µ—Ä—å –ø—Ä–∏—à–ª–∏—Ç–µ —Ñ–æ—Ç–æ ‚Äî –∑–∞—Ç–µ–º —è –ø–æ–∫–∞–∂—É —Å—Ü–µ–Ω–∞—Ä–∏–π –¥–ª—è —É—Ç–≤–µ—Ä–∂–¥–µ–Ω–∏—è."
        )

# –ü–æ–∫–∞–∑–∞—Ç—å –≤—ã–±—Ä–∞–Ω–Ω—ã–π —Ä–µ–∂–∏–º (–∏—Å–ø–æ–ª—å–∑—É–µ—Ç—Å—è –∏ –¥–ª—è callback, –∏ –¥–ª—è —Ç–µ–∫—Å—Ç–∞)
async def _send_mode_menu(update, context, key: str):
    text = _mode_desc(key)
    kb = _mode_kb(key)
    # –ï—Å–ª–∏ –ø—Ä–∏—à–ª–∏ –∏–∑ callback ‚Äî —Ä–µ–¥–∞–∫—Ç–∏—Ä—É–µ–º; –µ—Å–ª–∏ —Ç–µ–∫—Å—Ç–æ–º ‚Äî —à–ª—ë–º –Ω–æ–≤—ã–º —Å–æ–æ–±—â–µ–Ω–∏–µ–º
    if getattr(update, "callback_query", None):
        q = update.callback_query
        await q.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
        await q.answer()
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# –û–±—Ä–∞–±–æ—Ç—á–∏–∫ callback –ø–æ —Ä–µ–∂–∏–º–∞–º
async def on_mode_cb(update, context):
    q = update.callback_query
    data = (q.data or "").strip()
    uid = q.from_user.id

    # –ù–∞–≤–∏–≥–∞—Ü–∏—è
    if data == "mode:root":
        _clear_transient_flows(context)
        await q.message.reply_text(_modes_root_text(), reply_markup=modes_root_kb())
        await q.answer(); return

    if data.startswith("mode:"):
        _, key = data.split(":", 1)
        _clear_transient_flows(context)
        if key == "medicine":
            _set_mode_clean(uid, "–ú–µ–¥–∏—Ü–∏–Ω–∞", "")
        elif key == "study":
            _set_mode_clean(uid, "–£—á—ë–±–∞", "")
        elif key == "work":
            _set_mode_clean(uid, "–†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å", "")
        elif key == "fun":
            _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "")
        await _send_mode_menu(update, context, key)
        return

    # –°–≤–æ–±–æ–¥–Ω—ã–π –≤–≤–æ–¥ –∏–∑ –ø–æ–¥–º–µ–Ω—é
    if data == "act:free":
        await q.answer()
        _clear_transient_flows(context)
        await q.message.reply_text(
            "üìù –ù–∞–ø–∏—à–∏—Ç–µ —Å–≤–æ–±–æ–¥–Ω—ã–π –∑–∞–ø—Ä–æ—Å –Ω–∏–∂–µ —Ç–µ–∫—Å—Ç–æ–º –∏–ª–∏ –≥–æ–ª–æ—Å–æ–º ‚Äî —è –ø–æ–¥—Å—Ç—Ä–æ—é—Å—å.",
            reply_markup=modes_root_kb(),
        )
        return

    # === –£—á—ë–±–∞
    if data == "act:study:pdf_summary":
        await q.answer()
        _mode_track_set(uid, "pdf_summary")
        await q.message.reply_text(
            "üìö –ü—Ä–∏—à–ª–∏—Ç–µ PDF/EPUB/DOCX/FB2/TXT ‚Äî —Å–¥–µ–ª–∞—é —Å—Ç—Ä—É–∫—Ç—É—Ä–∏—Ä–æ–≤–∞–Ω–Ω—ã–π –∫–æ–Ω—Å–ø–µ–∫—Ç.\n"
            "–ú–æ–∂–Ω–æ –≤ –ø–æ–¥–ø–∏—Å–∏ —É–∫–∞–∑–∞—Ç—å —Ü–µ–ª—å (–∫–æ—Ä–æ—Ç–∫–æ/–ø–æ–¥—Ä–æ–±–Ω–æ, —è–∑—ã–∫ –∏ —Ç.–ø.).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:explain":
        await q.answer()
        study_sub_set(uid, "explain")
        _mode_track_set(uid, "explain")
        await q.message.reply_text(
            "üîç –ù–∞–ø–∏—à–∏—Ç–µ —Ç–µ–º—É + —É—Ä–æ–≤–µ–Ω—å (—à–∫–æ–ª–∞/–≤—É–∑/–ø—Ä–æ—Ñ–∏). –ë—É–¥–µ—Ç –æ–±—ä—è—Å–Ω–µ–Ω–∏–µ —Å –ø—Ä–∏–º–µ—Ä–∞–º–∏.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:tasks":
        await q.answer()
        study_sub_set(uid, "tasks")
        _mode_track_set(uid, "tasks")
        await q.message.reply_text(
            "üßÆ –ü—Ä–∏—à–ª–∏—Ç–µ —É—Å–ª–æ–≤–∏–µ(—è) ‚Äî —Ä–µ—à—É –ø–æ—à–∞–≥–æ–≤–æ (—Ñ–æ—Ä–º—É–ª—ã, –ø–æ—è—Å–Ω–µ–Ω–∏—è, –∏—Ç–æ–≥).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:essay":
        await q.answer()
        study_sub_set(uid, "essay")
        _mode_track_set(uid, "essay")
        await q.message.reply_text(
            "‚úçÔ∏è –¢–µ–º–∞ + —Ç—Ä–µ–±–æ–≤–∞–Ω–∏—è (–æ–±—ä—ë–º/—Å—Ç–∏–ª—å/—è–∑—ã–∫) ‚Äî –ø–æ–¥–≥–æ—Ç–æ–≤–ª—é —ç—Å—Å–µ/—Ä–µ—Ñ–µ—Ä–∞—Ç.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:exam_plan":
        await q.answer()
        study_sub_set(uid, "quiz")
        _mode_track_set(uid, "exam_plan")
        await q.message.reply_text(
            "üìù –£–∫–∞–∂–∏—Ç–µ –ø—Ä–µ–¥–º–µ—Ç –∏ –¥–∞—Ç—É —ç–∫–∑–∞–º–µ–Ω–∞ ‚Äî —Å–æ—Å—Ç–∞–≤–ª—é –ø–ª–∞–Ω –ø–æ–¥–≥–æ—Ç–æ–≤–∫–∏ —Å –≤–µ—Ö–∞–º–∏.",
            reply_markup=_mode_kb("study"),
        )
        return

    # === –†–∞–±–æ—Ç–∞
    if data == "act:work:doc":
        await q.answer()
        _mode_track_set(uid, "work_doc")
        await q.message.reply_text(
            "üìÑ –ß—Ç–æ –∑–∞ –¥–æ–∫—É–º–µ–Ω—Ç/–∞–¥—Ä–µ—Å–∞—Ç/–∫–æ–Ω—Ç–µ–∫—Å—Ç? –°—Ñ–æ—Ä–º–∏—Ä—É—é —á–µ—Ä–Ω–æ–≤–∏–∫ –ø–∏—Å—å–º–∞/–¥–æ–∫—É–º–µ–Ω—Ç–∞.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:report":
        await q.answer()
        _mode_track_set(uid, "work_report")
        await q.message.reply_text(
            "üìä –ü—Ä–∏—à–ª–∏—Ç–µ —Ç–µ–∫—Å—Ç/—Ñ–∞–π–ª/—Å—Å—ã–ª–∫—É ‚Äî —Å–¥–µ–ª–∞—é –∞–Ω–∞–ª–∏—Ç–∏—á–µ—Å–∫—É—é –≤—ã–∂–∏–º–∫—É.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:plan":
        await q.answer()
        _mode_track_set(uid, "work_plan")
        await q.message.reply_text(
            "üóÇ –û–ø–∏—à–∏—Ç–µ –∑–∞–¥–∞—á—É/—Å—Ä–æ–∫–∏ ‚Äî —Å–æ–±–µ—Ä—É ToDo/–ø–ª–∞–Ω —Å–æ —Å—Ä–æ–∫–∞–º–∏ –∏ –ø—Ä–∏–æ—Ä–∏—Ç–µ—Ç–∞–º–∏.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:idea":
        await q.answer()
        _mode_track_set(uid, "work_idea")
        await q.message.reply_text(
            "üí° –†–∞—Å—Å–∫–∞–∂–∏—Ç–µ –ø—Ä–æ–¥—É–∫—Ç/–¶–ê/–∫–∞–Ω–∞–ª—ã ‚Äî –ø–æ–¥–≥–æ—Ç–æ–≤–ª—é –±—Ä–∏—Ñ/–∏–¥–µ–∏.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:presentation":
        await q.answer()
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å", "work_presentation")
        await _presentation_studio_get().start(update, context, "presentation")
        return

    if data == "act:work:catalog_pdf":
        await q.answer()
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å", "work_catalog_pdf")
        await _presentation_studio_get().start(update, context, "catalog")
        return

    if data == "act:work:logo":
        await q.answer()
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å", "work_logo")
        context.user_data["awaiting_work_logo_brief"] = True
        await q.message.reply_text(
            "üé® –û–ø–∏—à–∏—Ç–µ –ª–æ–≥–æ—Ç–∏–ø: –Ω–∞–∑–≤–∞–Ω–∏–µ –±—Ä–µ–Ω–¥–∞, –Ω–∏—à–∞, —Å—Ç–∏–ª—å, —Ü–≤–µ—Ç–∞, —Å–ª–æ–≥–∞–Ω, –≥–¥–µ –±—É–¥–µ—Ç –∏—Å–ø–æ–ª—å–∑–æ–≤–∞—Ç—å—Å—è. –Ø —Å–≥–µ–Ω–µ—Ä–∏—Ä—É—é –≤–∏–∑—É–∞–ª.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("‚¨ÖÔ∏è –ù–∞–∑–∞–¥ –≤ –†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å", callback_data="mode:work")],
            ]),
        )
        return

    if data == "act:work:watermark":
        await q.answer()
        _clear_medicine_wait(context)
        _set_mode_clean(uid, "–†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å", "work_watermark")
        img = _get_cached_photo(uid)
        if img:
            _set_retouch_wait_text(context)
            await q.message.reply_text(
                "üßΩ –ò—Å–ø–æ–ª—å–∑—É—é –ø–æ—Å–ª–µ–¥–Ω–µ–µ –∑–∞–≥—Ä—É–∂–µ–Ω–Ω–æ–µ —Ñ–æ—Ç–æ. –ù–∞–ø–∏—à–∏—Ç–µ, —á—Ç–æ —É–±—Ä–∞—Ç—å –∏ –≥–¥–µ –Ω–∞—Ö–æ–¥–∏—Ç—Å—è —ç–ª–µ–º–µ–Ω—Ç: –≤–æ–¥—è–Ω–æ–π –∑–Ω–∞–∫, –Ω–∞–¥–ø–∏—Å—å, –ª–æ–≥–æ—Ç–∏–ø –∏–ª–∏ –ª–∏—à–Ω–∏–π –æ–±—ä–µ–∫—Ç.\n"
                "–û—Ç–ø—Ä–∞–≤–ª—è—è –∫–æ–º–∞–Ω–¥—É, –≤—ã –ø–æ–¥—Ç–≤–µ—Ä–∂–¥–∞–µ—Ç–µ, —á—Ç–æ —ç—Ç–æ –≤–∞—à–µ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ –∏–ª–∏ —É –≤–∞—Å –µ—Å—Ç—å –ø—Ä–∞–≤–æ –µ–≥–æ —Ä–µ–¥–∞–∫—Ç–∏—Ä–æ–≤–∞—Ç—å."
            )
        else:
            _set_waiting_image_retouch(update, context, "—É–±—Ä–∞—Ç—å –≤–æ–¥—è–Ω–æ–π –∑–Ω–∞–∫/–Ω–∞–¥–ø–∏—Å—å/–ª–æ–≥–æ—Ç–∏–ø –∏ –≤–æ—Å—Å—Ç–∞–Ω–æ–≤–∏—Ç—å —Ñ–æ–Ω")
            await q.message.reply_text(
                "üßΩ –ü—Ä–∏—à–ª–∏—Ç–µ —Ñ–æ—Ç–æ, –∑–∞—Ç–µ–º –Ω–∞–ø–∏—à–∏—Ç–µ, —á—Ç–æ —É–±—Ä–∞—Ç—å: –≤–æ–¥—è–Ω–æ–π –∑–Ω–∞–∫, –Ω–∞–¥–ø–∏—Å—å, –ª–æ–≥–æ—Ç–∏–ø –∏–ª–∏ –ª–∏—à–Ω–∏–π –æ–±—ä–µ–∫—Ç.",
                reply_markup=_mode_kb("work"),
            )
        return

    # === –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è: –≥–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä –∏ —Ñ–æ—Ç–æ‚Üí–≤–∏–¥–µ–æ–∫–ª–∏–ø
    if data == "act:fun:avatar":
        await q.answer("–ì–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä")
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "avatar")
        await q.message.reply_text(_avatar_menu_text(), parse_mode="Markdown", reply_markup=_avatar_action_kb("act"))
        return

    if data.startswith("act:fun:av_voice_"):
        voice = data.rsplit("_", 1)[-1].strip()
        context.user_data["avatar_tts_voice"] = voice
        context.user_data.pop("awaiting_avatar_voice_choice", None)
        if _get_cached_photo(q.from_user.id):
            _set_avatar_wait(context)
            await q.answer(f"–ì–æ–ª–æ—Å: {voice}")
            await q.message.reply_text(f"‚úÖ –î–ª—è –∞–≤–∞—Ç–∞—Ä–∞ –≤—ã–±—Ä–∞–Ω –≥–æ–ª–æ—Å: {_avatar_tts_voice_label(voice)}. –®–∞–≥ 3/3: –ø—Ä–∏—à–ª–∏—Ç–µ —Ç–µ–∫—Å—Ç, –∫–æ—Ç–æ—Ä—ã–π –¥–æ–ª–∂–µ–Ω –ø—Ä–æ–∏–∑–Ω–µ—Å—Ç–∏ –∞–≤–∞—Ç–∞—Ä.")
        else:
            context.user_data["awaiting_avatar_photo"] = True
            await q.answer(f"–ì–æ–ª–æ—Å: {voice}")
            await q.message.reply_text(f"‚úÖ –ì–æ–ª–æ—Å –≤—ã–±—Ä–∞–Ω: {_avatar_tts_voice_label(voice)}. –¢–µ–ø–µ—Ä—å –ø—Ä–∏—à–ª–∏—Ç–µ –ø–æ—Ä—Ç—Ä–µ—Ç —á–µ–ª–æ–≤–µ–∫–∞.")
        return

    if data == "act:fun:avatar_upload":
        await q.answer("–ó–∞–≥—Ä—É–∑–∏—Ç–µ –ø–æ—Ä—Ç—Ä–µ—Ç")
        await _handle_avatar_upload_choice(update, context, q, prefix="act")
        return

    if data in ("act:fun:avatar_last", "act:fun:avatar_text"):
        await _handle_avatar_script_choice(update, context, q, prefix="act", voice_mode=False)
        return

    if data == "act:fun:avatar_voice":
        await _handle_avatar_script_choice(update, context, q, prefix="act", voice_mode=True)
        return

    if data == "act:fun:vocalclip":
        await q.answer("–ö–ª–∏–ø —Å –≤–æ–∫–∞–ª–æ–º")
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "vocalclip")
        await q.message.reply_text(_vocal_clip_menu_text(), parse_mode="Markdown", reply_markup=_vocal_clip_action_kb("act"))
        return

    if data == "act:fun:vocalclip_upload":
        await q.answer("–ó–∞–≥—Ä—É–∑–∏—Ç–µ –ø–æ—Ä—Ç—Ä–µ—Ç")
        await _handle_vocalclip_upload_choice(update, context, q, prefix="act")
        return

    if data in ("act:fun:vocalclip_last", "act:fun:vocalclip_prompt"):
        await _handle_vocalclip_prompt_choice(update, context, q, prefix="act")
        return

    if data == "act:fun:textvideo":
        await q.answer("–í–∏–¥–µ–æ –ø–æ —Ç–µ–∫—Å—Ç—É/–≥–æ–ª–æ—Å—É")
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "textvideo")
        await q.message.reply_text(_textvideo_menu_text(), parse_mode="Markdown", reply_markup=_textvideo_action_kb("act"))
        return

    if data == "act:fun:tv_engine_sora":
        await _handle_textvideo_engine_choice(update, context, q, "sora", prefix="act")
        return

    if data == "act:fun:tv_engine_kling":
        await _handle_textvideo_engine_choice(update, context, q, "kling", prefix="act")
        return

    if data == "act:fun:tv_engine_runway":
        await _handle_textvideo_engine_choice(update, context, q, "runway", prefix="act")
        return

    if data == "act:fun:tv_prompt":
        await _handle_textvideo_prompt_choice(update, context, q, prefix="act")
        return

    if data == "act:fun:photoclip":
        await q.answer("AI-–≤–∏–¥–µ–æ–∫–ª–∏–ø / –ø–µ—Å–Ω—è")
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "photoclip")
        await q.message.reply_text(_photoclip_menu_text(), parse_mode="Markdown", reply_markup=_photoclip_action_kb("act"))
        return

    if data == "act:fun:photoclip_upload":
        await q.answer("–ó–∞–≥—Ä—É–∑–∏—Ç–µ —Ñ–æ—Ç–æ")
        await _handle_photoclip_upload_choice(update, context, q, prefix="act")
        return

    if data == "act:fun:photoclip_last":
        await _handle_photoclip_prompt_choice(update, context, q, prefix="act")
        return

    if data == "act:fun:photoclip_custom":
        # "–°–≤–æ–π —Å—Ü–µ–Ω–∞—Ä–∏–π" must never silently collapse into the generic last-photo path.
        # If the high-fidelity pack is absent (for example after a deploy/restart), rebuild it.
        if _music_video_identity_complete(uid):
            await _handle_photoclip_prompt_choice(update, context, q, prefix="act")
        else:
            await q.answer("–°–Ω–∞—á–∞–ª–∞ —Å–æ–±–µ—Ä—ë–º Character Identity Pack")
            await _handle_photoclip_upload_choice(update, context, q, prefix="act")
        return

    if data.startswith("act:fun:pc_preset_"):
        kind = data.rsplit("_", 1)[-1]
        await _handle_photoclip_preset_choice(update, context, q, kind, prefix="act")
        return

    if data == "act:fun:aiselfie":
        await q.answer("AI-—Å–µ–ª—Ñ–∏")
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "aiselfie")
        await q.message.reply_text(_ai_selfie_menu_text(), parse_mode="Markdown", reply_markup=_ai_selfie_action_kb("act"))
        return

    if data == "act:fun:aiselfie_upload":
        await q.answer("–ó–∞–≥—Ä—É–∑–∏—Ç–µ —Å–µ–ª—Ñ–∏")
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "aiselfie")
        context.user_data["awaiting_ai_selfie_photo"] = True
        await q.message.reply_text("ü§≥ –ü—Ä–∏—à–ª–∏—Ç–µ —Å–≤–æ—ë —Å–µ–ª—Ñ–∏. –ü–æ—Å–ª–µ –∑–∞–≥—Ä—É–∑–∫–∏ —è –ø–æ–ø—Ä–æ—à—É –Ω–∞–ø–∏—Å–∞—Ç—å, —Å –∫–µ–º/–≥–¥–µ —Å–¥–µ–ª–∞—Ç—å AI-—Ñ–æ—Ç–æ.", reply_markup=_ai_selfie_action_kb("act"))
        return

    if data in ("act:fun:aiselfie_last", "act:fun:aiselfie_custom"):
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "aiselfie")
        img = _get_cached_photo(uid)
        if img:
            _set_ai_selfie_wait(context)
            await q.answer("–ì–æ—Ç–æ–≤–æ")
            await q.message.reply_text("ü§≥ –ò—Å–ø–æ–ª—å–∑—É—é –ø–æ—Å–ª–µ–¥–Ω–µ–µ —Ñ–æ—Ç–æ. –ù–∞–ø–∏—à–∏—Ç–µ —Å—Ü–µ–Ω—É: –Ω–∞–ø—Ä–∏–º–µ—Ä ¬´—Å–µ–ª—Ñ–∏ —Å –∏–∑–≤–µ—Å—Ç–Ω—ã–º –∞–∫—Ç—ë—Ä–æ–º –Ω–∞ –∫—Ä–∞—Å–Ω–æ–π –¥–æ—Ä–æ–∂–∫–µ, iPhone selfie, 4:5¬ª.")
        else:
            context.user_data["awaiting_ai_selfie_photo"] = True
            await q.message.reply_text("–°–Ω–∞—á–∞–ª–∞ –ø—Ä–∏—à–ª–∏—Ç–µ —Å–≤–æ—ë —Å–µ–ª—Ñ–∏. –ü–æ—Å–ª–µ –∑–∞–≥—Ä—É–∑–∫–∏ –Ω–∞–ø–∏—à–µ—Ç–µ, —Å –∫–µ–º/–≥–¥–µ —Å–¥–µ–ª–∞—Ç—å AI-—Ñ–æ—Ç–æ.", reply_markup=_ai_selfie_action_kb("act"))
        return

    if data.startswith("act:fun:as_preset_"):
        kind = data.rsplit("_", 1)[-1]
        preset = _ai_selfie_preset_prompt(kind)
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "aiselfie")
        img = _get_cached_photo(uid)
        if img:
            context.user_data["ai_selfie_preset_prompt"] = preset
            _set_ai_selfie_wait(context)
            await q.answer("–ü—Ä–µ—Å–µ—Ç –≤—ã–±—Ä–∞–Ω")
            await q.message.reply_text("ü§≥ –ü—Ä–µ—Å–µ—Ç –≤—ã–±—Ä–∞–Ω. –¢–µ–ø–µ—Ä—å –Ω–∞–ø–∏—à–∏—Ç–µ –∏–º—è –∑–Ω–∞–º–µ–Ω–∏—Ç–æ—Å—Ç–∏/–ø–µ—Ä—Å–æ–Ω–∞–∂–∞ –∏ –¥–µ—Ç–∞–ª–∏ —Å—Ü–µ–Ω—ã.")
        else:
            context.user_data["awaiting_ai_selfie_photo"] = True
            context.user_data["ai_selfie_preset_prompt"] = preset
            await q.message.reply_text("ü§≥ –ü—Ä–µ—Å–µ—Ç –≤—ã–±—Ä–∞–Ω. –¢–µ–ø–µ—Ä—å –ø—Ä–∏—à–ª–∏—Ç–µ —Å–≤–æ—ë —Å–µ–ª—Ñ–∏ ‚Äî –ø–æ—Å–ª–µ –∑–∞–≥—Ä—É–∑–∫–∏ —è –ø–æ–ø—Ä–æ—à—É –∏–º—è –∑–Ω–∞–º–µ–Ω–∏—Ç–æ—Å—Ç–∏/–ø–µ—Ä—Å–æ–Ω–∞–∂–∞.", reply_markup=_ai_selfie_action_kb("act"))
        return

    # === –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è (–∫–∞–∫ –±—ã–ª–æ)
    if data == "act:fun:ideas":
        await q.answer()
        await q.message.reply_text(
            "üî• –í—ã–±–µ—Ä–µ–º —Ñ–æ—Ä–º–∞—Ç: –¥–æ–º/—É–ª–∏—Ü–∞/–≥–æ—Ä–æ–¥/–≤ –ø–æ–µ–∑–¥–∫–µ. –ù–∞–ø–∏—à–∏—Ç–µ –±—é–¥–∂–µ—Ç/–Ω–∞—Å—Ç—Ä–æ–µ–Ω–∏–µ.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:shorts":
        await q.answer()
        await q.message.reply_text(
            "üé¨ –¢–µ–º–∞, –¥–ª–∏—Ç–µ–ª—å–Ω–æ—Å—Ç—å (15‚Äì30 —Å–µ–∫), —Å—Ç–∏–ª—å ‚Äî —Å–¥–µ–ª–∞—é —Å—Ü–µ–Ω–∞—Ä–∏–π —à–æ—Ä—Ç–∞ + –ø–æ–¥—Å–∫–∞–∑–∫–∏ –¥–ª—è –æ–∑–≤—É—á–∫–∏.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:games":
        await q.answer()
        await q.message.reply_text(
            "üéÆ –¢–µ–º–∞—Ç–∏–∫–∞ –∫–≤–∏–∑–∞/–∏–≥—Ä—ã? –°–≥–µ–Ω–µ—Ä–∏—Ä—É—é –±—ã—Å—Ç—Ä—É—é –≤–∏–∫—Ç–æ—Ä–∏–Ω—É –∏–ª–∏ –º–∏–Ω–∏-–∏–≥—Ä—É –≤ —á–∞—Ç–µ.",
            reply_markup=_mode_kb("fun"),
        )
        return

    if data == "act:fun:faceswap":
        await q.answer()
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "faceswap")
        await _start_faceswap_flow(update, context, None, use_cached=False)
        return

    if data == "act:fun:removebg":
        await q.answer()
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "removebg")
        img = _get_cached_photo(uid)
        if img:
            await q.message.reply_text("üßº –ò—Å–ø–æ–ª—å–∑—É—é –ø–æ—Å–ª–µ–¥–Ω–µ–µ –∑–∞–≥—Ä—É–∂–µ–Ω–Ω–æ–µ —Ñ–æ—Ç–æ –∏ —É–¥–∞–ª—è—é —Ñ–æ–Ω.")
            await _pedit_removebg(update, context, img)
        else:
            _set_waiting_removebg(context)
            await q.message.reply_text("üßº –ü—Ä–∏—à–ª–∏—Ç–µ —Ñ–æ—Ç–æ ‚Äî —É–¥–∞–ª—é —Ñ–æ–Ω –∏ –≤–µ—Ä–Ω—É PNG —Å –ø—Ä–æ–∑—Ä–∞—á–Ω–æ–π –ø–æ–¥–ª–æ–∂–∫–æ–π.", reply_markup=_mode_kb("fun"))
        return

    if data == "act:fun:replacebg":
        await q.answer()
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "replacebg")
        img = _get_cached_photo(uid)
        if img:
            await q.message.reply_text("üñº –í—ã–±–µ—Ä–∏—Ç–µ –Ω–æ–≤—ã–π —Ñ–æ–Ω –¥–ª—è –ø–æ—Å–ª–µ–¥–Ω–µ–≥–æ –∑–∞–≥—Ä—É–∂–µ–Ω–Ω–æ–≥–æ —Ñ–æ—Ç–æ:", reply_markup=background_presets_kb())
        else:
            context.user_data["photo_flow"] = "replacebg_menu"
            await q.message.reply_text("üñº –ü—Ä–∏—à–ª–∏—Ç–µ —Ñ–æ—Ç–æ. –ü–æ—Å–ª–µ –∑–∞–≥—Ä—É–∑–∫–∏ —è –ø–æ–∫–∞–∂—É –≤–∞—Ä–∏–∞–Ω—Ç—ã —Ñ–æ–Ω–∞: –ø–ª—è–∂, –≥–æ—Ä—ã, –ø—Ä–∏—Ä–æ–¥–∞, –≥–æ—Ä–æ–¥ –∏–ª–∏ —Å–≤–æ–π —Ç–µ–∫—Å—Ç.", reply_markup=_mode_kb("fun"))
        return

    if data == "act:fun:revive":
        await q.answer()
        _set_waiting_photo_revival(update, context)
        await q.message.reply_text(
            _fun_revive_help_text(),
            parse_mode="Markdown",
            reply_markup=photo_revival_wait_kb(),
        )
        return

    if data == "act:fun:reels":
        await q.answer()
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "fun_reels")
        context.user_data["awaiting_reels_material"] = True
        await q.message.reply_text(
            _fun_reels_help_text(),
            parse_mode="Markdown",
            reply_markup=_mode_kb("fun"),
        )
        return

    if data == "act:fun:film":
        await q.answer()
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "fun_film")
        context.user_data["awaiting_film_material"] = True
        await q.message.reply_text(
            _fun_film_help_text(),
            parse_mode="Markdown",
            reply_markup=_mode_kb("fun"),
        )
        return

    if data == "act:fun:music":
        await q.answer("–ú—É–∑—ã–∫–∞ / Suno")
        _clear_transient_flows(context)
        _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "suno_music")
        context.user_data["awaiting_suno_brief"] = True
        await _show_suno_help_from_callback(q, context, reply_markup=_suno_menu_kb(), submenu=True)
        return

    # === –ú–µ–¥–∏—Ü–∏–Ω–∞
    if data.startswith("act:med:"):
        await q.answer()
        action = data.split(":", 2)[2]
        mapping = {
            "extract": "med_extract",
            "scan": "med_scan",
            "conclusion": "med_conclusion",
            "mri": "med_mri",
            "ct": "med_ct",
            "labs": "med_labs",
            "free": "med_free",
        }
        track = mapping.get(action, "med_free")
        _set_mode_clean(uid, "–ú–µ–¥–∏—Ü–∏–Ω–∞", track)
        _clear_transient_flows(context)
        context.user_data["medicine_waiting_for_material"] = True
        context.user_data["pending_med_task"] = track
        await q.message.reply_text(_medical_menu_text(track), reply_markup=medicine_kb())
        return

    # === –ú–æ–¥—É–ª–∏ (–∫–∞–∫ –±—ã–ª–æ)
    if data == "act:open:runway":
        await q.answer()
        await q.message.reply_text(
            "üé¨ –ú–æ–¥—É–ª—å Runway: –ø—Ä–∏—à–ª–∏—Ç–µ –∏–¥–µ—é/—Ä–µ—Ñ–µ—Ä–µ–Ω—Å ‚Äî –ø–æ–¥–≥–æ—Ç–æ–≤–ª—é –ø—Ä–æ–º–ø—Ç –∏ –±—é–¥–∂–µ—Ç.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:mj":
        await q.answer()
        await q.message.reply_text(
            "üé® –ú–æ–¥—É–ª—å Midjourney: –æ–ø–∏—à–∏—Ç–µ –∫–∞—Ä—Ç–∏–Ω–∫—É ‚Äî –ø—Ä–µ–¥–ª–æ–∂—É 3 –ø—Ä–æ–º–ø—Ç–∞ –∏ —Å–µ—Ç–∫—É —Å—Ç–∏–ª–µ–π.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:voice":
        await q.answer()
        await q.message.reply_text(
            "üó£ –ì–æ–ª–æ—Å: /voice_on ‚Äî –æ–∑–≤—É—á–∫–∞ –æ—Ç–≤–µ—Ç–æ–≤, /voice_off ‚Äî –≤—ã–∫–ª—é—á–∏—Ç—å. "
            "–ú–æ–∂–µ—Ç–µ –ø—Ä–∏—Å–ª–∞—Ç—å –≥–æ–ª–æ—Å–æ–≤–æ–µ ‚Äî —Ä–∞—Å–ø–æ–∑–Ω–∞—é –∏ –æ—Ç–≤–µ—á—É.",
            reply_markup=modes_root_kb(),
        )
        return

    await q.answer()

# Fallback ‚Äî –µ—Å–ª–∏ –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å –Ω–∞–∂–º—ë—Ç ¬´–£—á—ë–±–∞/–†–∞–±–æ—Ç–∞/–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è¬ª –æ–±—ã—á–Ω–æ–π –∫–Ω–æ–ø–∫–æ–π/—Ç–µ–∫—Å—Ç–æ–º
async def on_mode_text(update, context):
    text = (update.effective_message.text or "").strip().lower()
    mapping = {
        "—É—á—ë–±–∞": "study", "—É—á–µ–±–∞": "study",
        "—Ä–∞–±–æ—Ç–∞": "work", "—Ä–∞–±–æ—Ç–∞/–±–∏–∑–Ω–µ—Å": "work", "–±–∏–∑–Ω–µ—Å": "work",
        "—Ä–∞–∑–≤–ª–µ—á–µ–Ω–∏—è": "fun", "—Ä–∞–∑–≤–ª–µ—á–µ–Ω–∏–µ": "fun",
        "–º–µ–¥–∏—Ü–∏–Ω–∞": "medicine", "–º–µ–¥–∏—Ü–∏–Ωa": "medicine",
    }
    key = mapping.get(text)
    if key:
        await _send_mode_menu(update, context, key)
        
def main_keyboard():
    # 2 –∫–Ω–æ–ø–∫–∏ –≤ —Å—Ç—Ä–æ–∫–µ ‚Äî —Ç–∞–∫ Telegram –Ω–∞ –º–æ–±–∏–ª—å–Ω—ã—Ö –Ω–µ –æ–±—Ä–µ–∑–∞–µ—Ç –ø–æ–¥–ø–∏—Å–∏.
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("üéì –£—á—ë–±–∞"), KeyboardButton("üíº –†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å")],
            [KeyboardButton("üî• –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è"), KeyboardButton("ü©∫ –ú–µ–¥–∏—Ü–∏–Ω–∞")],
            [KeyboardButton("üí¨ –ú–æ–∏ —á–∞—Ç—ã"), KeyboardButton("‚ûï –ù–æ–≤—ã–π —á–∞—Ç")],
            [KeyboardButton("üß† –î–≤–∏–∂–∫–∏"), KeyboardButton("üßæ –ë–∞–ª–∞–Ω—Å")],
            [KeyboardButton("‚≠ê –ü–æ–¥–ø–∏—Å–∫–∞ ¬∑ –ü–æ–º–æ—â—å")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
        input_field_placeholder="–í—ã–±–µ—Ä–∏—Ç–µ —Ä–µ–∂–∏–º –∏–ª–∏ –Ω–∞–ø–∏—à–∏—Ç–µ –∑–∞–ø—Ä–æ—Å‚Ä¶",
    )

main_kb = main_keyboard()

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ /start ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _handle_payment_start_payload(update, context):
        return
    with contextlib.suppress(Exception):
        _chat_ensure_active(update.effective_user.id, update.effective_chat.id)
    await update.effective_chat.send_message(
        START_TEXT,
        reply_markup=main_kb,
        disable_web_page_preview=True,
    )


def _chat_dt_label(ts: int) -> str:
    if not ts:
        return "‚Äî"
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    now = datetime.now(timezone.utc)
    if dt.date() == now.date():
        return "—Å–µ–≥–æ–¥–Ω—è " + dt.strftime("%H:%M")
    if dt.date() == (now - timedelta(days=1)).date():
        return "–≤—á–µ—Ä–∞ " + dt.strftime("%H:%M")
    return dt.strftime("%d.%m.%Y")


def _chat_list_kb(user_id: int, telegram_chat_id: int) -> InlineKeyboardMarkup:
    rows = []
    for item in _chat_list(user_id, telegram_chat_id):
        mark = "‚úÖ" if item["active"] else "üí¨"
        title = f"{mark} {item['title']} ¬∑ {_chat_dt_label(item['updated_ts'])}"
        rows.append([InlineKeyboardButton(title[:60], callback_data=f"chat:open:{item['id']}")])
        rows.append([
            InlineKeyboardButton("üìñ –ò—Å—Ç–æ—Ä–∏—è", callback_data=f"chat:history:{item['id']}:0"),
            InlineKeyboardButton("‚úèÔ∏è –ò–º—è", callback_data=f"chat:rename:{item['id']}"),
            InlineKeyboardButton("üóë –£–¥–∞–ª–∏—Ç—å", callback_data=f"chat:delete:{item['id']}"),
        ])
    rows.append([InlineKeyboardButton("‚ûï –°–æ–∑–¥–∞—Ç—å –Ω–æ–≤—ã–π —á–∞—Ç", callback_data="chat:new")])
    return InlineKeyboardMarkup(rows)


async def cmd_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; tgid = update.effective_chat.id
    _chat_ensure_active(uid, tgid)
    chats = _chat_list(uid, tgid)
    active = next((x for x in chats if x["active"]), None)
    text = (
        f"üí¨ –í–∞—à–∏ —á–∞—Ç—ã: {len(chats)}/{CHAT_MAX_CONVERSATIONS}.\n"
        "–ö–∞–∂–¥—ã–π —á–∞—Ç —Ö—Ä–∞–Ω–∏—Ç –æ—Ç–¥–µ–ª—å–Ω—ã–π –∫–æ–Ω—Ç–µ–∫—Å—Ç GPT. –ù–∞–∂–º–∏—Ç–µ –Ω–∞ —á–∞—Ç, —á—Ç–æ–±—ã –ø—Ä–æ–¥–æ–ª–∂–∏—Ç—å, –∏–ª–∏ –æ—Ç–∫—Ä–æ–π—Ç–µ –µ–≥–æ –∏—Å—Ç–æ—Ä–∏—é."
    )
    if active:
        text += f"\n\n–°–µ–π—á–∞—Å –∞–∫—Ç–∏–≤–µ–Ω: ¬´{active['title']}¬ª."
    await update.effective_message.reply_text(text, reply_markup=_chat_list_kb(uid, tgid))


async def cmd_newchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; tgid = update.effective_chat.id
    cid, err = _chat_create(uid, tgid, "–ù–æ–≤—ã–π —á–∞—Ç")
    if not cid:
        await update.effective_message.reply_text(err, reply_markup=_chat_list_kb(uid, tgid))
        return
    _clear_transient_flows(context)
    await update.effective_message.reply_text(
        "‚ûï –ù–æ–≤—ã–π —á–∞—Ç —Å–æ–∑–¥–∞–Ω –∏ –≤—ã–±—Ä–∞–Ω. –ù–∞–ø–∏—à–∏—Ç–µ –ø–µ—Ä–≤—ã–π –∑–∞–ø—Ä–æ—Å ‚Äî –Ω–∞–∑–≤–∞–Ω–∏–µ –ø–æ—è–≤–∏—Ç—Å—è –∞–≤—Ç–æ–º–∞—Ç–∏—á–µ—Å–∫–∏.",
        reply_markup=main_kb,
    )


def _chat_history_page(user_id: int, telegram_chat_id: int, ai_chat_id: int, page: int) -> tuple[list[dict], int, str]:
    page = max(0, int(page or 0)); offset = page * CHAT_HISTORY_PAGE_SIZE
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT title FROM ai_chats WHERE id=? AND user_id=? AND telegram_chat_id=?", (int(ai_chat_id), int(user_id), int(telegram_chat_id)))
    row = cur.fetchone()
    if not row:
        con.close(); return [], 0, "–ß–∞—Ç"
    title = row[0] or "–ß–∞—Ç"
    cur.execute("SELECT COUNT(*) FROM ai_chat_messages WHERE ai_chat_id=?", (int(ai_chat_id),))
    total = int((cur.fetchone() or [0])[0])
    # Page 0 is the newest page; inside the page messages are chronological.
    cur.execute(
        "SELECT role, content, created_ts FROM ai_chat_messages WHERE ai_chat_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
        (int(ai_chat_id), CHAT_HISTORY_PAGE_SIZE, offset),
    )
    rows = cur.fetchall(); con.close(); rows.reverse()
    return [{"role": r[0], "content": r[1] or "", "created_ts": int(r[2] or 0)} for r in rows], total, title


async def _send_chat_history(update: Update, context: ContextTypes.DEFAULT_TYPE, ai_chat_id: int, page: int = 0):
    uid = update.effective_user.id; tgid = update.effective_chat.id
    items, total, title = _chat_history_page(uid, tgid, ai_chat_id, page)
    if total <= 0:
        await update.effective_message.reply_text(f"üìñ –í —á–∞—Ç–µ ¬´{title}¬ª –ø–æ–∫–∞ –Ω–µ—Ç —Å–æ–æ–±—â–µ–Ω–∏–π.", reply_markup=_chat_list_kb(uid, tgid))
        return
    lines = [f"üìñ –ò—Å—Ç–æ—Ä–∏—è: {title}", f"–°–æ–æ–±—â–µ–Ω–∏–π: {total} ¬∑ —Å—Ç—Ä–∞–Ω–∏—Ü–∞ {page + 1}", ""]
    for item in items:
        who = "üë§ –í—ã" if item["role"] == "user" else "ü§ñ –ë–æ—Ç"
        stamp = datetime.fromtimestamp(item["created_ts"], tz=timezone.utc).strftime("%d.%m %H:%M") if item["created_ts"] else ""
        content = (item["content"] or "").strip()
        lines.append(f"{who} ¬∑ {stamp}\n{content}\n")
    text = "\n".join(lines)
    # Telegram limit: split long pages safely.
    for i in range(0, len(text), 3800):
        await update.effective_message.reply_text(text[i:i+3800])
    max_page = max(0, (total - 1) // CHAT_HISTORY_PAGE_SIZE)
    nav = []
    if page < max_page:
        nav.append(InlineKeyboardButton("‚¨ÖÔ∏è –°—Ç–∞—Ä–µ–µ", callback_data=f"chat:history:{ai_chat_id}:{page+1}"))
    if page > 0:
        nav.append(InlineKeyboardButton("–ù–æ–≤–µ–µ ‚û°Ô∏è", callback_data=f"chat:history:{ai_chat_id}:{page-1}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton("‚ñ∂Ô∏è –ü—Ä–æ–¥–æ–ª–∂–∏—Ç—å —ç—Ç–æ—Ç —á–∞—Ç", callback_data=f"chat:open:{ai_chat_id}")])
    rows.append([InlineKeyboardButton("üí¨ –í—Å–µ —á–∞—Ç—ã", callback_data="chat:list")])
    await update.effective_message.reply_text("–î–µ–π—Å—Ç–≤–∏—è —Å –∏—Å—Ç–æ—Ä–∏–µ–π:", reply_markup=InlineKeyboardMarkup(rows))


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ —Å–æ—Ö—Ä–∞–Ω–µ–Ω–∏–µ –≤—ã–±—Ä–∞–Ω–Ω–æ–≥–æ —Ä–µ–∂–∏–º–∞/–ø–æ–¥—Ä–µ–∂–∏–º–∞ (SQLite kv) ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
def _mode_set(user_id: int, mode: str):
    kv_set(f"mode:{user_id}", mode)

def _mode_get(user_id: int) -> str:
    return (kv_get(f"mode:{user_id}", "none") or "none")

def _mode_track_set(user_id: int, track: str):
    kv_set(f"mode_track:{user_id}", track)

def _mode_track_get(user_id: int) -> str:
    return kv_get(f"mode_track:{user_id}", "") or ""


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ë–µ–∑–æ–ø–∞—Å–Ω–∞—è –º–∞—Ä—à—Ä—É—Ç–∏–∑–∞—Ü–∏—è —Ä–µ–∂–∏–º–æ–≤ ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
def _set_mode_clean(user_id: int, mode: str, track: str = ""):
    """–ï–¥–∏–Ω—ã–π –≤—Ö–æ–¥ –¥–ª—è –ø–µ—Ä–µ–∫–ª—é—á–µ–Ω–∏—è —Ä–µ–∂–∏–º–∞: –Ω–æ–≤—ã–π —Ä–µ–∂–∏–º –≤—Å–µ–≥–¥–∞ —Å–±—Ä–∞—Å—ã–≤–∞–µ—Ç —Å—Ç–∞—Ä—ã–π –ø–æ–¥—Ä–µ–∂–∏–º."""
    with contextlib.suppress(Exception):
        _mode_set(user_id, mode)
    with contextlib.suppress(Exception):
        _mode_track_set(user_id, track or "")


def _clear_transient_flows(context):
    """–°–±—Ä–∞—Å—ã–≤–∞–µ—Ç –∫—Ä–∞—Ç–∫–æ–∂–∏–≤—É—â–∏–µ –æ–∂–∏–¥–∞–Ω–∏—è, –∫–æ—Ç–æ—Ä—ã–µ –Ω–µ –¥–æ–ª–∂–Ω—ã —Ç—è–Ω—É—Ç—å—Å—è –º–µ–∂–¥—É —Ä–µ–∂–∏–º–∞–º–∏."""
    if not context:
        return
    for key in (
        "awaiting_photo_for",
        "photo_flow",
        "retouch_prompt",
        "retouch_wait_text",
        "awaiting_med_file",
        "awaiting_med_photo",
        "awaiting_med_document",
        "pending_med_task",
        "medicine_waiting_for_material",
        "awaiting_reels_material",
        "awaiting_film_material",
        "awaiting_suno_brief",
        "suno_preset_kind",
        "awaiting_avatar_photo",
        "awaiting_avatar_voice_choice",
        "awaiting_avatar_script",
        "awaiting_photo_clip_photo",
        "awaiting_photo_clip_prompt",
        "photo_clip_preset_prompt",
        "awaiting_ai_selfie_photo",
        "awaiting_ai_selfie_prompt",
        "ai_selfie_preset_prompt",
        "awaiting_vocal_clip_photo",
        "awaiting_vocal_clip_prompt",
        "awaiting_music_video_video_brief",
        "music_video_music_brief",
        "vocal_clip_preset_prompt",
        "music_video_draft",
        "music_video_draft_edit",
        "awaiting_text_video_prompt",
        "text_video_engine",
        "presentation_studio_active",
    ):
        with contextlib.suppress(Exception):
            context.user_data.pop(key, None)


def _set_waiting_photo_revival(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """–ü–æ—Å–ª–µ —Ç–µ–∫—Å—Ç–∞/–≥–æ–ª–æ—Å–∞ ¬´–æ–∂–∏–≤–∏—Ç—å —Ñ–æ—Ç–æ¬ª —Å–ª–µ–¥—É—é—â–∞—è —Ñ–æ—Ç–æ–≥—Ä–∞—Ñ–∏—è –¥–æ–ª–∂–Ω–∞ –∏–¥—Ç–∏ –≤ —Ñ–æ—Ç–æ-–º–∞—Å—Ç–µ—Ä—Å–∫—É—é, –∞ –Ω–µ –≤ –º–µ–¥–∏—Ü–∏–Ω—É."""
    uid = update.effective_user.id
    _set_mode_clean(uid, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "")
    _clear_transient_flows(context)
    context.user_data["awaiting_photo_for"] = "revive"
    context.user_data["photo_flow"] = "revive"


def _is_waiting_photo_revival(context) -> bool:
    if not context:
        return False
    return (
        context.user_data.get("awaiting_photo_for") == "revive"
        or context.user_data.get("photo_flow") == "revive"
    )


def _clear_photo_revival_wait(context):
    if not context:
        return
    for key in ("awaiting_photo_for", "photo_flow"):
        with contextlib.suppress(Exception):
            context.user_data.pop(key, None)


# –†–µ—Ç—É—à—å —Å–æ–±—Å—Ç–≤–µ–Ω–Ω–æ–≥–æ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è –∏—Å–ø–æ–ª—å–∑—É–µ—Ç –æ—Ç–¥–µ–ª—å–Ω—ã–π photo_flow, —á—Ç–æ–±—ã –Ω–µ –∫–æ–Ω—Ñ–ª–∏–∫—Ç–æ–≤–∞—Ç—å —Å –º–µ–¥–∏—Ü–∏–Ω–æ–π.
# –§—É–Ω–∫—Ü–∏–∏ _set_waiting_image_retouch/_is_waiting_image_retouch –æ–±—ä—è–≤–ª–µ–Ω—ã –≤—ã—à–µ –≤ –±–ª–æ–∫–µ Image retouch.


def _set_medical_waiting(update: Update, context: ContextTypes.DEFAULT_TYPE, track: str = ""):
    """–ú–µ–¥–∏—Ü–∏–Ω–∞ —Å—Ç–∞–Ω–æ–≤–∏—Ç—Å—è –∞–∫—Ç–∏–≤–Ω–æ–π —Ç–æ–ª—å–∫–æ –∫–∞–∫ –º–µ–Ω—é/–∫–æ–Ω–∫—Ä–µ—Ç–Ω–∞—è –º–µ–¥. –∑–∞–¥–∞—á–∞, –Ω–æ –Ω–µ –¥–æ–ª–∂–Ω–∞ –ø–µ—Ä–µ—Ö–≤–∞—Ç—ã–≤–∞—Ç—å —Ñ–æ—Ç–æ –ø–æ—Å–ª–µ –¥—Ä—É–≥–∏—Ö –∑–∞–ø—Ä–æ—Å–æ–≤."""
    uid = update.effective_user.id
    _set_mode_clean(uid, "–ú–µ–¥–∏—Ü–∏–Ω–∞", track or "")
    _clear_transient_flows(context)
    if track:
        context.user_data["medicine_waiting_for_material"] = True
        context.user_data["pending_med_task"] = track


def _clear_medicine_wait(context):
    if not context:
        return
    for key in ("medicine_waiting_for_material", "pending_med_task", "awaiting_med_file", "awaiting_med_photo", "awaiting_med_document"):
        with contextlib.suppress(Exception):
            context.user_data.pop(key, None)


def _should_route_medical(context: ContextTypes.DEFAULT_TYPE, user_id: int, caption_or_text: str = "", filename: str = "") -> bool:
    """–ú–∞—Ä—à—Ä—É—Ç–∏–∑–∏—Ä—É–µ—Ç –≤ –º–µ–¥–∏—Ü–∏–Ω—É —Ç–æ–ª—å–∫–æ —è–≤–Ω—ã–π –º–µ–¥. –ø–æ–¥—Ä–µ–∂–∏–º/–æ–∂–∏–¥–∞–Ω–∏–µ –∏–ª–∏ —è–≤–Ω—ã–µ –º–µ–¥. —Å–ª–æ–≤–∞.
    –°–∞–º —Ñ–∞–∫—Ç, —á—Ç–æ –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å –∫–æ–≥–¥–∞-—Ç–æ –Ω–∞–∂–∞–ª ¬´–ú–µ–¥–∏—Ü–∏–Ω–∞¬ª, –±–æ–ª—å—à–µ –Ω–µ –¥–µ–ª–∞–µ—Ç –≤—Å–µ —Å–ª–µ–¥—É—é—â–∏–µ —Ñ–æ—Ç–æ –º–µ–¥–∏—Ü–∏–Ω—Å–∫–∏–º–∏.
    """
    track = ""
    with contextlib.suppress(Exception):
        track = _mode_track_get(user_id)
    combined = f"{caption_or_text or ''} {filename or ''}"
    # –í –º–µ–¥–∏—Ü–∏–Ω—É –æ—Ç–ø—Ä–∞–≤–ª—è–µ–º —Ç–æ–ª—å–∫–æ —è–≤–Ω—ã–π –º–µ–¥–∏—Ü–∏–Ω—Å–∫–∏–π –º–∞—Ç–µ—Ä–∏–∞–ª –∏–ª–∏ –º–∞—Ç–µ—Ä–∏–∞–ª,
    # –∫–æ—Ç–æ—Ä—ã–π –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—å –ø—Ä—è–º–æ –∂–¥–µ—Ç –ø–æ—Å–ª–µ –Ω–∞–∂–∞—Ç–∏—è –º–µ–¥. –ø–æ–¥–º–µ–Ω—é.
    # –°—Ç–∞—Ä—ã–π mode_track=med_* —Å–∞–º –ø–æ —Å–µ–±–µ –±–æ–ª—å—à–µ –Ω–µ –¥–æ–ª–∂–µ–Ω –ø–µ—Ä–µ—Ö–≤–∞—Ç—ã–≤–∞—Ç—å –≤—Å–µ –ø–æ–¥—Ä—è–¥.
    return (
        bool(_MEDICAL_TERMS_RE.search(combined))
        or bool(context and context.user_data.get("medicine_waiting_for_material") and (track or "").startswith("med_"))
    )


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –¢–µ–∫—Å—Ç—ã –±—ã—Å—Ç—Ä—ã—Ö –¥–µ–π—Å—Ç–≤–∏–π ¬´–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è¬ª ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
def _fun_revive_help_text() -> str:
    return (
        "ü™Ñ *–û–∂–∏–≤–∏—Ç—å —Ñ–æ—Ç–æ / —Ñ–æ—Ç–æ‚Üí–≤–∏–¥–µ–æ*\n"
        "–ú–æ–∂–Ω–æ —Å–¥–µ–ª–∞—Ç—å –∫–æ—Ä–æ—Ç–∫–æ–µ –≤–∏–¥–µ–æ –∏–∑ –æ–¥–Ω–æ–π —Ñ–æ—Ç–æ–≥—Ä–∞—Ñ–∏–∏, –≥–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä –∏–ª–∏ –∫–ª–∏–ø–æ–≤—É—é –∞–Ω–∏–º–∞—Ü–∏—é.\n\n"
        "–ö–∞–∫ –∑–∞–ø—É—Å—Ç–∏—Ç—å:\n"
        "1) –æ—Ç–ø—Ä–∞–≤—å—Ç–µ —Ñ–æ—Ç–æ –æ–±—ã—á–Ω–æ–π –∫–∞—Ä—Ç–∏–Ω–∫–æ–π;\n"
        "2) –ø–æ—Å–ª–µ –∑–∞–≥—Ä—É–∑–∫–∏ –ø–æ—è–≤—è—Ç—Å—è –∫–Ω–æ–ø–∫–∏ ‚ú® –û–∂–∏–≤–∏—Ç—å, üó£ –ì–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä –∏ üéµ –§–æ—Ç–æ‚Üí–≤–∏–¥–µ–æ–∫–ª–∏–ø;\n"
        "3) –ª–∏–±–æ —Å—Ä–∞–∑—É –æ—Ç–ø—Ä–∞–≤—å—Ç–µ —Ñ–æ—Ç–æ —Å –ø–æ–¥–ø–∏—Å—å—é: `–æ–∂–∏–≤–∏ —Ñ–æ—Ç–æ: –ª—ë–≥–∫–∞—è —É–ª—ã–±–∫–∞, –ø–ª–∞–≤–Ω–æ–µ –¥–≤–∏–∂–µ–Ω–∏–µ –∫–∞–º–µ—Ä—ã, 5 —Å–µ–∫—É–Ω–¥, 9:16`;\n"
        "4) –¥–ª—è –≥–æ–≤–æ—Ä—è—â–µ–≥–æ –∞–≤–∞—Ç–∞—Ä–∞ –Ω–∞–∂–º–∏—Ç–µ üó£ –∏ –ø—Ä–∏—à–ª–∏—Ç–µ —Ç–µ–∫—Å—Ç, voice –∏–ª–∏ –∞—É–¥–∏–æ—Ñ–∞–π–ª 2‚Äì60 —Å–µ–∫—É–Ω–¥.\n\n"
        "–†–µ–∫–æ–º–µ–Ω–¥–∞—Ü–∏—è: Runway ‚Äî —Å—Ç–∞–±–∏–ª—å–Ω–æ–µ –æ–∂–∏–≤–ª–µ–Ω–∏–µ –ø–æ—Ä—Ç—Ä–µ—Ç–æ–≤; Kling ‚Äî –¥–∏–Ω–∞–º–∏–∫–∞, –∞–≤–∞—Ç–∞—Ä—ã –∏ –∫–ª–∏–ø—ã; Sora 2 ‚Äî —Ç–æ–ª—å–∫–æ –¥–ª—è —Å—Ü–µ–Ω –±–µ–∑ –ª—é–¥–µ–π, –µ—Å–ª–∏ –∫–∞–Ω–∞–ª –≤ Comet –¥–æ—Å—Ç—É–ø–µ–Ω."
    )


def _fun_reels_help_text() -> str:
    return (
        "üì± *–°–¥–µ–ª–∞—Ç—å Reels / Shorts*\n"
        "–Ø –º–æ–≥—É —Å–æ–±—Ä–∞—Ç—å –∏–¥–µ—é, —Ö—É–∫, —Å—Ü–µ–Ω–∞—Ä–∏–π, —Ç–∞–π–º-–∫–æ–¥—ã, –ø–æ–¥–ø–∏—Å–∏, –ø—Ä–æ–º–ø—Ç—ã –¥–ª—è –≤–∏–¥–µ–æ–≥–µ–Ω–µ—Ä–∞—Ü–∏–∏ –∏ –ø–ª–∞–Ω –º–æ–Ω—Ç–∞–∂–∞.\n\n"
        "–ö–∞–∫ –∑–∞–ø—É—Å—Ç–∏—Ç—å:\n"
        "‚Ä¢ –Ω–∞–ø–∏—à–∏—Ç–µ —Ç–µ–º—É: `—Å–¥–µ–ª–∞–π —Ä–∏–ª—Å 20 —Å–µ–∫—É–Ω–¥ –ø—Ä–æ –≤–∏–ª–ª—É –Ω–∞ –°–∞–º—É–∏, luxury, 9:16`;\n"
        "‚Ä¢ –∏–ª–∏ –ø—Ä–∏—à–ª–∏—Ç–µ –∏—Å—Ö–æ–¥–Ω–æ–µ –≤–∏–¥–µ–æ/—Ñ–æ—Ç–æ –∏ –ø–æ–¥–ø–∏—Å—å: —á—Ç–æ –æ—Å—Ç–∞–≤–∏—Ç—å, —Å—Ç–∏–ª—å, –¥–ª–∏—Ç–µ–ª—å–Ω–æ—Å—Ç—å, –¶–ê;\n"
        "‚Ä¢ –¥–ª—è AI-–≤—Å—Ç–∞–≤–æ–∫ –ª—É—á—à–µ –∏—Å–ø–æ–ª—å–∑–æ–≤–∞—Ç—å Runway/Kling; Sora 2 ‚Äî —Ç–æ–ª—å–∫–æ –µ—Å–ª–∏ –¥–æ—Å—Ç—É–ø–µ–Ω –∫–∞–Ω–∞–ª –ø—Ä–æ–≤–∞–π–¥–µ—Ä–∞.\n\n"
        "–§–æ—Ä–º–∞—Ç —Ä–µ–∑—É–ª—å—Ç–∞—Ç–∞: hook ‚Üí —Å—Ü–µ–Ω—ã ‚Üí —Ç–µ–∫—Å—Ç –Ω–∞ —ç–∫—Ä–∞–Ω–µ ‚Üí voice-over ‚Üí CTA ‚Üí –ø—Ä–æ–º–ø—Ç—ã –¥–ª—è –≤—ã–±—Ä–∞–Ω–Ω–æ–≥–æ –¥–≤–∏–∂–∫–∞."
    )


def _fun_film_help_text() -> str:
    return (
        "üéû *–°–æ–∑–¥–∞—Ç—å —Ñ–∏–ª—å–º / –º–∏–Ω–∏-—Ñ–∏–ª—å–º*\n"
        "–ü–æ–¥—Ö–æ–¥–∏—Ç –¥–ª—è —Ä–æ–ª–∏–∫–∞ 30‚Äì90 —Å–µ–∫—É–Ω–¥ –∏–ª–∏ —Å–µ—Ä–∏–∏ —Å—Ü–µ–Ω: —Ä–µ–∫–ª–∞–º–∞, –∏—Å—Ç–æ—Ä–∏—è, —Ç—Ä–µ–π–ª–µ—Ä, –ø—Ä–æ–º–æ, –∫–ª–∏–ø.\n\n"
        "–ö–∞–∫ –∑–∞–ø—É—Å—Ç–∏—Ç—å:\n"
        "1) –Ω–∞–ø–∏—à–∏—Ç–µ –∏–¥–µ—é, –∂–∞–Ω—Ä, –¥–ª–∏—Ç–µ–ª—å–Ω–æ—Å—Ç—å, —Å—Ç–∏–ª—å –∏ —Ñ–æ—Ä–º–∞—Ç –∫–∞–¥—Ä–∞;\n"
        "2) —è —Å–¥–µ–ª–∞—é —Å—Ü–µ–Ω–∞—Ä–∏–π, —Å–ø–∏—Å–æ–∫ —Å—Ü–µ–Ω, —Ä–∞—Å–∫–∞–¥—Ä–æ–≤–∫—É –∏ –ø—Ä–æ–º–ø—Ç—ã;\n"
        "3) —Å—Ü–µ–Ω—ã –≥–µ–Ω–µ—Ä–∏—Ä—É—é—Ç—Å—è –∫–æ—Ä–æ—Ç–∫–∏–º–∏ —Ñ—Ä–∞–≥–º–µ–Ω—Ç–∞–º–∏ —á–µ—Ä–µ–∑ Sora 2 –±–µ–∑ –ª—é–¥–µ–π, Kling –∏–ª–∏ Runway, –∑–∞—Ç–µ–º —Å–∫–ª–µ–∏–≤–∞—é—Ç—Å—è.\n\n"
        "–†–µ–∫–æ–º–µ–Ω–¥–∞—Ü–∏—è: Runway ‚Äî –¥–ª—è –∫–æ–Ω—Ç—Ä–æ–ª—è –∏ –∫–∞—á–µ—Å—Ç–≤–∞, Kling ‚Äî –¥–ª—è –¥–∏–Ω–∞–º–∏—á–Ω—ã—Ö —Å—Ü–µ–Ω, Sora 2 ‚Äî –µ—Å–ª–∏ –¥–æ—Å—Ç—É–ø–µ–Ω —á–µ—Ä–µ–∑ –≤–∞—à Comet-–∫–∞–Ω–∞–ª –∏ –≤ –∫–∞–¥—Ä–µ –Ω–µ—Ç –ª—é–¥–µ–π."
    )

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ü–æ–¥–º–µ–Ω—é —Ä–µ–∂–∏–º–æ–≤ ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
def _school_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("üîé –û–±—ä—è—Å–Ω–µ–Ω–∏–µ", callback_data="school:explain")],
        [InlineKeyboardButton("üßÆ –ó–∞–¥–∞—á–∏", callback_data="school:tasks")],
        [InlineKeyboardButton("‚úçÔ∏è –≠—Å—Å–µ / —Ä–µ—Ñ–µ—Ä–∞—Ç", callback_data="school:essay")],
        [InlineKeyboardButton("üìù –≠–∫–∑–∞–º–µ–Ω / –∫–≤–∏–∑", callback_data="school:quiz")],
    ])

def _work_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("üìß –ü–∏—Å—å–º–æ / –¥–æ–∫—É–º–µ–Ω—Ç", callback_data="work:doc")],
        [InlineKeyboardButton("üìä –ê–Ω–∞–ª–∏—Ç–∏–∫–∞ / —Å–≤–æ–¥–∫–∞", callback_data="work:report")],
        [InlineKeyboardButton("üóÇ –ü–ª–∞–Ω / ToDo", callback_data="work:plan")],
        [InlineKeyboardButton("üí° –ò–¥–µ–∏ / –±—Ä–∏—Ñ", callback_data="work:idea")],
    ])

def _fun_quick_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ü™Ñ –û–∂–∏–≤–∏—Ç—å —Ñ–æ—Ç–æ", callback_data="fun:revive")],
        [InlineKeyboardButton("üó£ –ì–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä", callback_data="fun:avatar")],
        [InlineKeyboardButton("üéµ –§–æ—Ç–æ ‚Üí –≤–∏–¥–µ–æ–∫–ª–∏–ø", callback_data="fun:photoclip")],
        [InlineKeyboardButton("üé§ –ö–ª–∏–ø —Å –≤–æ–∫–∞–ª–æ–º (1 —á–µ–ª–æ–≤–µ–∫)", callback_data="fun:vocalclip")],
        [InlineKeyboardButton("üé¨ –í–∏–¥–µ–æ –ø–æ —Ç–µ–∫—Å—Ç—É/–≥–æ–ª–æ—Å—É", callback_data="fun:textvideo")],
        [InlineKeyboardButton("ü§≥ AI-—Å–µ–ª—Ñ–∏ —Å–æ –∑–≤–µ–∑–¥–æ–π", callback_data="fun:aiselfie")],
        [InlineKeyboardButton("üé≠ –ó–∞–º–µ–Ω–∞ –ª–∏—Ü–∞ –Ω–∞ —Ñ–æ—Ç–æ", callback_data="fun:faceswap")],
        [InlineKeyboardButton("üßº –£–¥–∞–ª–∏—Ç—å —Ñ–æ–Ω –Ω–∞ —Ñ–æ—Ç–æ", callback_data="fun:removebg")],
        [InlineKeyboardButton("üñº –ó–∞–º–µ–Ω–∏—Ç—å —Ñ–æ–Ω –Ω–∞ —Ñ–æ—Ç–æ", callback_data="fun:replacebg")],
        [InlineKeyboardButton("üì± Reels / Shorts", callback_data="fun:reels")],
        [InlineKeyboardButton("üéû –°–æ–∑–¥–∞—Ç—å –º–∏–Ω–∏-—Ñ–∏–ª—å–º", callback_data="fun:film")],
        [InlineKeyboardButton("üé¨ –†–∞—Å–∫–∞–¥—Ä–æ–≤–∫–∞ Reels", callback_data="fun:storyboard")],
        [InlineKeyboardButton("üñå –°–æ–∑–¥–∞—Ç—å –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ", callback_data="fun:img")],
    ])

def _fun_kb():
    # –æ—Å—Ç–∞–≤–∏–º –∏ —Å—Ç–∞—Ä–æ–µ –ø–æ–¥–º–µ–Ω—é ‚Äî –Ω–µ –∏—Å–ø–æ–ª—å–∑—É–µ—Ç—Å—è —Å–µ–π—á–∞—Å
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("üñº –§–æ—Ç–æ-–º–∞—Å—Ç–µ—Ä—Å–∫–∞—è", callback_data="fun:photo"),
         InlineKeyboardButton("üé¨ –í–∏–¥–µ–æ-–∏–¥–µ–∏",      callback_data="fun:video")],
        [InlineKeyboardButton("üé≤ –ö–≤–∏–∑—ã/–∏–≥—Ä—ã",      callback_data="fun:quiz"),
         InlineKeyboardButton("üòÜ –ú–µ–º—ã/—à—É—Ç–∫–∏",      callback_data="fun:meme")],
    ])


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ö–æ–º–∞–Ω–¥—ã/–∫–Ω–æ–ø–∫–∏ —Ä–µ–∂–∏–º–æ–≤ ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
async def cmd_mode_school(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_transient_flows(context)
    _set_mode_clean(update.effective_user.id, "–£—á—ë–±–∞", "")
    # –ø–æ–∫–∞–∑—ã–≤–∞–µ–º –ù–û–í–û–ï –ø–æ–¥–º–µ–Ω—é ¬´–£—á—ë–±–∞¬ª
    await _send_mode_menu(update, context, "study")

async def cmd_mode_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_transient_flows(context)
    _set_mode_clean(update.effective_user.id, "–†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å", "")
    # –ø–æ–∫–∞–∑—ã–≤–∞–µ–º –ù–û–í–û–ï –ø–æ–¥–º–µ–Ω—é ¬´–†–∞–±–æ—Ç–∞¬ª
    await _send_mode_menu(update, context, "work")

async def cmd_mode_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_transient_flows(context)
    _set_mode_clean(update.effective_user.id, "–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è", "")
    await update.effective_message.reply_text(
        "üî• –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è ‚Äî –±—ã—Å—Ç—Ä—ã–µ –¥–µ–π—Å—Ç–≤–∏—è: –≤–∏–¥–µ–æ, —Ñ–æ—Ç–æ, —Ñ–æ–Ω –∏ –∑–∞–º–µ–Ω–∞ –ª–∏—Ü–∞.",
        reply_markup=_fun_quick_kb()
    )

async def cmd_mode_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _set_medical_waiting(update, context, "")
    await update.effective_message.reply_text(_medical_menu_text(), reply_markup=medicine_kb())


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ö–æ–ª–ª–±—ç–∫–∏ –ø–æ–¥—Ä–µ–∂–∏–º–æ–≤ ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
async def on_cb_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "")
    try:
        if any(data.startswith(p) for p in ("school:", "work:", "fun:")):
            # –±–∞–∑–æ–≤—ã–π —Ç—Ä–µ–∫–∏–Ω–≥ —Å—Ç–∞—Ä—ã—Ö –≤–µ—Ç–æ–∫ (photo/video/quiz/meme)
            if data in ("fun:revive","fun:clip","fun:img","fun:storyboard"):
                # —ç—Ç–∏ –æ–±—Ä–∞–±–∞—Ç—ã–≤–∞—é—Ç—Å—è –æ—Ç–¥–µ–ª—å–Ω—ã–º —Ö–µ–Ω–¥–ª–µ—Ä–æ–º on_cb_fun
                return
            _, track = data.split(":", 1)
            _mode_track_set(update.effective_user.id, track)
            mode = _mode_get(update.effective_user.id)
            await q.message.reply_text(f"{mode} ‚Üí {track}. –ù–∞–ø–∏—à–∏—Ç–µ –∑–∞–¥–∞–Ω–∏–µ/—Ç–µ–º—É ‚Äî —Å–¥–µ–ª–∞—é.")
            return
    finally:
        with contextlib.suppress(Exception):
            await q.answer()

# –±—ã—Å—Ç—Ä—ã–µ –¥–µ–π—Å—Ç–≤–∏—è ¬´–†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è¬ª
async def on_cb_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "fun:img":
        return await q.message.reply_text("–ü—Ä–∏—à–ª–∏ –ø—Ä–æ–º–ø—Ç –∏–ª–∏ –∏—Å–ø–æ–ª—å–∑—É–π –∫–æ–º–∞–Ω–¥—É /img <–æ–ø–∏—Å–∞–Ω–∏–µ> ‚Äî —Å–≥–µ–Ω–µ—Ä–∏—Ä—É—é –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ.")
    if data == "fun:revive":
        return await q.message.reply_text("–ó–∞–≥—Ä—É–∑–∏ —Ñ–æ—Ç–æ (–∫–∞–∫ –∫–∞—Ä—Ç–∏–Ω–∫—É) –∏ –Ω–∞–ø–∏—à–∏, —á—Ç–æ –æ–∂–∏–≤–∏—Ç—å/–∫–∞–∫ –¥–≤–∏–≥–∞—Ç—å—Å—è. –°–¥–µ–ª–∞—é –∞–Ω–∏–º–∞—Ü–∏—é.")
    if data == "fun:avatar":
        context.user_data["awaiting_avatar_photo"] = True
        return await q.message.reply_text("–ó–∞–≥—Ä—É–∑–∏ –ø–æ—Ä—Ç—Ä–µ—Ç —á–µ–ª–æ–≤–µ–∫–∞, –∑–∞—Ç–µ–º –Ω–∞–∂–º–∏ üó£ –ì–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä. –ü–æ—Å–ª–µ —ç—Ç–æ–≥–æ –ø—Ä–∏—à–ª–∏ —Ç–µ–∫—Å—Ç, voice –∏–ª–∏ –∞—É–¥–∏–æ –¥–ª—è —Ä–µ—á–∏.")
    if data == "fun:photoclip":
        context.user_data["awaiting_photo_clip_photo"] = True
        return await q.message.reply_text("–ó–∞–≥—Ä—É–∑–∏ —Ñ–æ—Ç–æ —á–µ–ª–æ–≤–µ–∫–∞, –∑–∞—Ç–µ–º –Ω–∞–∂–º–∏ üéµ –§–æ—Ç–æ ‚Üí –≤–∏–¥–µ–æ–∫–ª–∏–ø. –ü–æ—Å–ª–µ —Ñ–æ—Ç–æ —è –æ—Ç–¥–µ–ª—å–Ω–æ —Å–ø—Ä–æ—à—É —Å–Ω–∞—á–∞–ª–∞ –ü–ï–°–ù–Æ, –∑–∞—Ç–µ–º –í–ò–î–ï–û.")
    if data == "fun:aiselfie":
        context.user_data["awaiting_ai_selfie_photo"] = True
        return await q.message.reply_text("ü§≥ –ó–∞–≥—Ä—É–∑–∏ —Å–≤–æ—ë —Å–µ–ª—Ñ–∏, –∑–∞—Ç–µ–º –Ω–∞–ø–∏—à–∏, —Å –∫–µ–º/–≥–¥–µ —Å–¥–µ–ª–∞—Ç—å AI-—Ñ–æ—Ç–æ: –∑–Ω–∞–º–µ–Ω–∏—Ç–æ—Å—Ç—å, –ø–µ—Ä—Å–æ–Ω–∞–∂, –ø—Ä–µ–º—å–µ—Ä–∞, —Ä–µ–∫–ª–∞–º–∞, travel/luxury.")
    if data == "fun:clip":
        return await q.message.reply_text("–ü—Ä–∏—à–ª–∏ —Ç–µ–∫—Å—Ç/–≥–æ–ª–æ—Å –∏ —Ñ–æ—Ä–º–∞—Ç (Reels/Shorts), –º—É–∑—ã–∫—É/—Å—Ç–∏–ª—å ‚Äî —Å–æ–±–µ—Ä—É –∫–ª–∏–ø. –î–ª—è –≥–µ–Ω–µ—Ä–∞—Ü–∏–∏ –≤–∏–¥–µ–æ –¥–æ—Å—Ç—É–ø–Ω—ã Sora 2 –±–µ–∑ –ª—é–¥–µ–π, Kling –∏ Runway.")
    if data == "fun:storyboard":
        return await q.message.reply_text("–ü—Ä–∏—à–ª–∏ —Ñ–æ—Ç–æ –∏–ª–∏ –æ–ø–∏—à–∏ –∏–¥–µ—é —Ä–æ–ª–∏–∫–∞ ‚Äî –≤–µ—Ä–Ω—É —Ä–∞—Å–∫–∞–¥—Ä–æ–≤–∫—É –ø–æ–¥ Reels —Å —Ç–∞–π–º-–∫–æ–¥–∞–º–∏.")

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –°—Ç–∞—Ä—Ç / –î–≤–∏–∂–∫–∏ / –ü–æ–º–æ—â—å ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _handle_payment_start_payload(update, context):
        return
    with contextlib.suppress(Exception):
        _chat_ensure_active(update.effective_user.id, update.effective_chat.id)

    # Keep the welcome animation, text and keyboard in one Telegram message.
    # Telegram captions are limited, so use a compact start caption here.
    start_caption = (
        "üëã –ü—Ä–∏–≤–µ—Ç! –Ø Neyro-Bot GPT 5 Studio ‚Äî –º—É–ª—å—Ç–∏–º–æ–¥–µ–ª—å–Ω–∞—è AI-—Å—Ç—É–¥–∏—è –≤ Telegram "
        "–¥–ª—è —Ç–µ–∫—Å—Ç–∞, –¥–æ–∫—É–º–µ–Ω—Ç–æ–≤, —Ñ–æ—Ç–æ, –≤–∏–¥–µ–æ, –º—É–∑—ã–∫–∏, —Ä–µ—á–∏ –∏ live-–ø–æ–∏—Å–∫–∞.\n\n"
        "üöÄ –ß—Ç–æ —É–º–µ—é:\n"
        "üéì –£—á—ë–±–∞ –∏ —Ä–∞–±–æ—Ç–∞ —Å PDF/DOCX\n"
        "üñº –ì–µ–Ω–µ—Ä–∞—Ü–∏—è –∏ –æ–±—Ä–∞–±–æ—Ç–∫–∞ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–π\n"
        "üé¨ –í–∏–¥–µ–æ, Reels/Shorts –∏ –æ–∂–∏–≤–ª–µ–Ω–∏–µ —Ñ–æ—Ç–æ\n"
        "üéô –†–∞—Å–ø–æ–∑–Ω–∞–≤–∞–Ω–∏–µ –∏ –æ–∑–≤—É—á–∫–∞ —Ä–µ—á–∏\n"
        "üéµ –ì–µ–Ω–µ—Ä–∞—Ü–∏—è –º—É–∑—ã–∫–∏\n"
        "üîé –ü–æ–∏—Å–∫ –∏ –∞–Ω–∞–ª–∏–∑ –∏–Ω—Ñ–æ—Ä–º–∞—Ü–∏–∏\n\n"
        "–í—ã–±–µ—Ä–∏—Ç–µ —Ä–µ–∂–∏–º –≤ –º–µ–Ω—é –Ω–∏–∂–µ –∏–ª–∏ –ø—Ä–æ—Å—Ç–æ –Ω–∞–ø–∏—à–∏—Ç–µ –∑–∞–¥–∞—á—É."
    )

    welcome_video = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "assets",
        "NeyroBot_start_Live_Centered_FullHD-2.mp4",
    )
    welcome_sent = False
    if os.path.isfile(welcome_video):
        try:
            with open(welcome_video, "rb") as video_file:
                await update.effective_message.reply_video(
                    video=video_file,
                    caption=start_caption,
                    reply_markup=main_kb,
                    supports_streaming=True,
                )
            welcome_sent = True
        except Exception as e:
            log.warning("Animated welcome failed, using image fallback: %s", e)

    if not welcome_sent:
        welcome_url = kv_get("welcome_url", BANNER_URL)
        if welcome_url:
            try:
                await update.effective_message.reply_photo(
                    welcome_url,
                    caption=start_caption,
                    reply_markup=main_kb,
                )
                welcome_sent = True
            except Exception as e:
                log.warning("Welcome image fallback failed: %s", e)

    if not welcome_sent:
        await update.effective_message.reply_text(
            start_caption,
            reply_markup=main_kb,
            disable_web_page_preview=True,
        )

async def cmd_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("üß† –í—ã–±–µ—Ä–∏—Ç–µ –Ω–µ–π—Ä–æ—Å–µ—Ç—å –∏–ª–∏ –ø—Ä–æ–≤–∞–π–¥–µ—Ä–∞:", reply_markup=engines_kb())

async def cmd_subs_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("‚≠ê –û—Ç–∫—Ä—ã—Ç—å —Ç–∞—Ä–∏—Ñ—ã", web_app=WebAppInfo(url=TARIFF_URL))],
        [InlineKeyboardButton("üöÄ PRO –Ω–∞ –º–µ—Å—è—Ü", callback_data="buyinv:pro:1")],
    ])
    await update.effective_message.reply_text("‚≠ê –¢–∞—Ä–∏—Ñ—ã –∏ –ø–æ–º–æ—â—å.\n\n" + HELP_TEXT, reply_markup=kb, disable_web_page_preview=True)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, disable_web_page_preview=True)

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(EXAMPLES_TEXT, disable_web_page_preview=True)

async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        f"‚úÖ –ö–æ–¥ –∑–∞–ø—É—â–µ–Ω: {PATCH_VERSION}\n"
        f"–§–∞–π–ª –¥–æ–ª–∂–µ–Ω –±—ã—Ç—å –∏–º–µ–Ω–Ω–æ main.py –Ω–∞ Render. Start Command: python -u main.py"
    )


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –î–∏–∞–≥–Ω–æ—Å—Ç–∏–∫–∞/–ª–∏–º–∏—Ç—ã ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
async def cmd_diag_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tier = get_subscription_tier(user_id)
    lim = _limits_for(user_id)
    row = _usage_row(user_id, _today_ymd())
    lines = [
        f"üë§ –¢–∞—Ä–∏—Ñ: {tier}",
        f"‚Ä¢ –¢–µ–∫—Å—Ç—ã —Å–µ–≥–æ–¥–Ω—è: {row['text_count']} / {lim['text_per_day']}",
        f"‚Ä¢ –ë–µ—Å–ø–ª–∞—Ç–Ω—ã–µ –∫–∞—Ä—Ç–∏–Ω–∫–∏: {row['free_img_gen_count']} / {FREE_IMAGE_GENERATIONS_PER_DAY}",
        f"‚Ä¢ –ë–µ—Å–ø–ª–∞—Ç–Ω—ã–µ –æ–±—Ä–∞–±–æ—Ç–∫–∏ —Ñ–æ—Ç–æ: {row['free_img_proc_count']} / {FREE_IMAGE_PROCESSINGS_PER_DAY}",
        f"‚Ä¢ –°–µ–±–µ—Å—Ç–æ–∏–º–æ—Å—Ç—å –≤–∏–¥–µ–æ —Å–µ–≥–æ–¥–Ω—è: {_credits_fmt_from_usd(row['runway_usd'])} (–≤–Ω—É—Ç—Ä–µ–Ω–Ω—è—è –¥–∏–∞–≥–Ω–æ—Å—Ç–∏–∫–∞)",
        f"‚Ä¢ –°–µ–±–µ—Å—Ç–æ–∏–º–æ—Å—Ç—å –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–π —Å–µ–≥–æ–¥–Ω—è: {_credits_fmt_from_usd(row['img_usd'])} (–≤–Ω—É—Ç—Ä–µ–Ω–Ω—è—è –¥–∏–∞–≥–Ω–æ—Å—Ç–∏–∫–∞)",
    ]
    await update.effective_message.reply_text("\n".join(lines))


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ Capability Q&A ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
_CAP_PDF   = re.compile(r"(pdf|–¥–æ–∫—É–º–µ–Ω—Ç(—ã)?|—Ñ–∞–π–ª(—ã)?)", re.I)
_CAP_EBOOK = re.compile(r"(ebook|e-?book|—ç–ª–µ–∫—Ç—Ä–æ–Ω–Ω(–∞—è|—ã–µ)\s+–∫–Ω–∏–≥|epub|fb2|docx|txt|mobi|azw)", re.I)
_CAP_AUDIO = re.compile(r"(–∞—É–¥–∏–æ ?–∫–Ω–∏–≥|audiobook|audio ?book|mp3|m4a|wav|ogg|webm|voice)", re.I)
_CAP_IMAGE = re.compile(r"(–∏–∑–æ–±—Ä–∞–∂–µ–Ω|–∫–∞—Ä—Ç–∏–Ω–∫|—Ñ–æ—Ç–æ|image|picture|img)", re.I)
_CAP_VIDEO = re.compile(r"(–≤–∏–¥–µ–æ|—Ä–æ–ª–∏–∫|shorts?|reels?|clip)", re.I)

def _is_photo_revival_question(text: str) -> bool:
    """–ñ—ë—Å—Ç–∫–∏–π –ø–µ—Ä–µ—Ö–≤–∞—Ç –≤–æ–ø—Ä–æ—Å–æ–≤/—Ñ—Ä–∞–∑ –ø—Ä–æ –≤–æ–∑–º–æ–∂–Ω–æ—Å—Ç—å –æ–∂–∏–≤–∏—Ç—å —Ñ–æ—Ç–æ.
    –ù–µ –æ—Ç–¥–∞—ë–º —Ç–∞–∫–∏–µ —Ñ—Ä–∞–∑—ã –≤ GPT, –ø–æ—Ç–æ–º—É —á—Ç–æ –º–æ–¥–µ–ª—å –º–æ–∂–µ—Ç –æ—Ç–≤–µ—Ç–∏—Ç—å –æ–±—â–∏–º –æ—Ç–∫–∞–∑–æ–º.
    """
    tl = (text or "").strip().lower()
    if not tl:
        return False
    has_photo = bool(re.search(r"(?:\\b—Ñ–æ—Ç–æ\\b|—Ñ–æ—Ç–æ–≥—Ä–∞—Ñ\\w*|–∫–∞—Ä—Ç–∏–Ω–∫\\w*|–∏–∑–æ–±—Ä–∞–∂–µ–Ω\\w*|\\bimage\\b|\\bpicture\\b|\\bphoto\\b)", tl, re.I))
    has_revival = bool(re.search(r"(–æ–∂–∏–≤|–∞–Ω–∏–º–∏—Ä|–¥–≤–∏–∂–µ–Ω|image\s*to\s*video|i2v|revive|animate)", tl, re.I))
    has_ability = bool(re.search(r"(–º–æ–∂(–µ—à—å|–µ—Ç–µ|–Ω–æ)|—É–º–µ(–µ—à—å|–µ—Ç–µ)|—Å–ø–æ—Å–æ–±–µ–Ω|–ø–æ–¥–¥–µ—Ä–∂–∏–≤–∞–µ—à—å|–¥–µ–ª–∞–µ—à—å|–ø–æ–ª—É—á–∏—Ç—Å—è|–º–æ–∂–µ—Ç\s+–ª–∏)", tl, re.I))
    # –õ–æ–≤–∏–º –∏ –ø—Ä—è–º–æ–π –≤–æ–ø—Ä–æ—Å ¬´–º–æ–∂–µ—à—å –æ–∂–∏–≤–∏—Ç—å —Ñ–æ—Ç–æ?¬ª, –∏ —Ñ—Ä–∞–∑—ã –≤–∏–¥–∞ ¬´–æ–∂–∏–≤–ª–µ–Ω–∏–µ —Ñ–æ—Ç–æ –≤–æ–∑–º–æ–∂–Ω–æ?¬ª
    return has_photo and has_revival and (has_ability or "?" in tl)

def _is_photo_revival_intent(text: str) -> bool:
    """–õ–æ–≤–∏—Ç –Ω–µ —Ç–æ–ª—å–∫–æ –≤–æ–ø—Ä–æ—Å ¬´–º–æ–∂–µ—à—å –æ–∂–∏–≤–∏—Ç—å —Ñ–æ—Ç–æ?¬ª, –Ω–æ –∏ –∫–æ–º–∞–Ω–¥—É/–Ω–∞–º–µ—Ä–µ–Ω–∏–µ ¬´–æ–∂–∏–≤–∏ —ç—Ç–æ —Ñ–æ—Ç–æ¬ª."""
    tl = (text or "").strip().lower().replace("—ë", "–µ")
    if not tl:
        return False
    has_photo = bool(re.search(r"(?:\\b—Ñ–æ—Ç–æ\\b|—Ñ–æ—Ç–æ–≥—Ä–∞—Ñ\\w*|–∫–∞—Ä—Ç–∏–Ω–∫\\w*|–∏–∑–æ–±—Ä–∞–∂–µ–Ω\\w*|\\bimage\\b|\\bpicture\\b|\\bphoto\\b)", tl, re.I))
    has_revival = bool(re.search(r"(–æ–∂–∏–≤|–∞–Ω–∏–º–∏—Ä|–¥–≤–∏–∂–µ–Ω|image\s*to\s*video|i2v|revive|animate|—Å–¥–µ–ª–∞–π\s+–≤–∏–¥–µ–æ)", tl, re.I))
    return has_photo and has_revival


def _revival_engine_from_text(text: str, default: str = "runway") -> str:
    tl = (text or "").lower().replace("—ë", "–µ")
    if "luma" in tl or "–ª—É–º–∞" in tl:
        return "luma"
    if "sora" in tl or "—Å–æ—Ä–∞" in tl:
        return "sora"
    if "kling" in tl or "–∫–ª–∏–Ω–≥" in tl:
        return "kling"
    if "runway" in tl or "—Ä–∞–Ω–≤–µ–π" in tl or "—Ä–∞–Ω–≤—ç–π" in tl:
        return "runway"
    return default


def _clean_revival_prompt(text: str) -> str:
    cleaned = re.sub(
        r"\b(–æ–∂–∏–≤–∏|–æ–∂–∏–≤–∏—Ç—å|–∞–Ω–∏–º–∏—Ä—É–π|–∞–Ω–∏–º–∏—Ä–æ–≤–∞—Ç—å|—Å–¥–µ–ª–∞–π\s+–≤–∏–¥–µ–æ|revive|animate|image\s*to\s*video|i2v|runway|luma|sora|kling|–ª—É–º–∞|—Å–æ—Ä–∞|–∫–ª–∏–Ω–≥|—Ä–∞–Ω–≤–µ–π|—Ä–∞–Ω–≤—ç–π)\b",
        "",
        text or "",
        flags=re.I,
    )
    cleaned = re.sub(
        r"\b(—Ñ–æ—Ç–æ|—Ñ–æ—Ç–æ–≥—Ä–∞—Ñ–∏(?:—è|—é|–∏|–µ–π)?|–∫–∞—Ä—Ç–∏–Ω–∫(?:–∞|—É|–∏|–æ–π)?|–∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏(?:–µ|—è|—é)?|photo|image|picture)\b",
        "",
        cleaned,
        flags=re.I,
    ).strip(" ,.:-‚Äî")
    # –ù–µ –æ—Ç–ø—Ä–∞–≤–ª—è–µ–º –≤ –¥–≤–∏–∂–æ–∫ –º—É—Å–æ—Ä–Ω—ã–π –ø—Ä–æ–º–ø—Ç –≤—Ä–æ–¥–µ ¬´—ç—Ç–æ¬ª / ¬´–ø–æ–∂–∞–ª—É–π—Å—Ç–∞¬ª.
    if len(cleaned) < 4:
        return ""
    return cleaned


def _photo_revival_capability_text() -> str:
    return (
        "–î–∞, –º–æ–≥—É –æ–∂–∏–≤–∏—Ç—å —Ñ–æ—Ç–æ–≥—Ä–∞—Ñ–∏—é –∏ —Å–¥–µ–ª–∞—Ç—å –∏–∑ –Ω–µ—ë –∫–æ—Ä–æ—Ç–∫–æ–µ –≤–∏–¥–µ–æ.\n\n"
        "–ö–∞–∫ –∑–∞–ø—É—Å—Ç–∏—Ç—å:\n"
        "1) –∑–∞–≥—Ä—É–∑–∏—Ç–µ —Ñ–æ—Ç–æ;\n"
        "2) –Ω–∞–∂–º–∏—Ç–µ –∫–Ω–æ–ø–∫—É ‚ú® –û–∂–∏–≤–∏—Ç—å: Runway / Kling / Sora 2 –±–µ–∑ –ª—é–¥–µ–π;\n"
        "3) –ª–∏–±–æ –æ—Ç–ø—Ä–∞–≤—å—Ç–µ —Ñ–æ—Ç–æ —Å –ø–æ–¥–ø–∏—Å—å—é: ¬´–æ–∂–∏–≤–∏ —Ñ–æ—Ç–æ: –ª—ë–≥–∫–∞—è —É–ª—ã–±–∫–∞, –¥–≤–∏–∂–µ–Ω–∏–µ –∫–∞–º–µ—Ä—ã, 5 —Å–µ–∫—É–Ω–¥, 9:16¬ª.\n\n"
        "–í–∞–∂–Ω–æ: Sora 2 —á–∞—Å—Ç–æ –±–ª–æ–∫–∏—Ä—É–µ—Ç –∑–∞–≥—Ä—É–∂–µ–Ω–Ω—ã–µ —Ñ–æ—Ç–æ —Å –ª—é–¥—å–º–∏ –∏–∑-–∑–∞ –º–æ–¥–µ—Ä–∞—Ü–∏–∏. "
        "–î–ª—è –ø–æ—Ä—Ç—Ä–µ—Ç–æ–≤ –∏ —Ñ–æ—Ç–æ –ª—é–¥–µ–π –ª—É—á—à–µ –≤—ã–±–∏—Ä–∞—Ç—å Runway –∏–ª–∏ Kling. "
        "Sora 2 –æ—Å—Ç–∞–≤–ª–µ–Ω–∞ –¥–ª—è –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–π –±–µ–∑ –ª—é–¥–µ–π: –ø—Ä–µ–¥–º–µ—Ç—ã, –∂–∏–≤–æ—Ç–Ω—ã–µ, –∑–¥–∞–Ω–∏—è, –ø–µ–π–∑–∞–∂–∏, –∏–Ω—Ç–µ—Ä—å–µ—Ä.\n\n"
        "–ï—Å–ª–∏ –¥–≤–∏–∂–æ–∫ –≤–µ—Ä–Ω—ë—Ç –æ—à–∏–±–∫—É, —è –ø–æ–∫–∞–∂—É —Ç–µ—Ö–Ω–∏—á–µ—Å–∫—É—é –ø—Ä–∏—á–∏–Ω—É: –∫–ª—é—á, –ª–∏–º–∏—Ç, –∫—Ä–µ–¥–∏—Ç—ã, –º–æ–¥–µ—Ä–∞—Ü–∏—è –∏–ª–∏ —Ñ–æ—Ä–º–∞—Ç –∑–∞–ø—Ä–æ—Å–∞."
    )

MEDICAL_DISCLAIMER = (
    "\n\n‚ö†Ô∏è –í–∞–∂–Ω–æ: —ç—Ç–æ —Å–ø—Ä–∞–≤–æ—á–Ω—ã–π —Ä–∞–∑–±–æ—Ä –∏ –ø–æ–¥–≥–æ—Ç–æ–≤–∫–∞ –≤–æ–ø—Ä–æ—Å–æ–≤ –∫ –≤—Ä–∞—á—É, "
    "–∞ –Ω–µ –æ—Ñ–∏—Ü–∏–∞–ª—å–Ω—ã–π –¥–∏–∞–≥–Ω–æ–∑, –Ω–µ –º–µ–¥–∏—Ü–∏–Ω—Å–∫–æ–µ –∑–∞–∫–ª—é—á–µ–Ω–∏–µ –∏ –Ω–µ –∑–∞–º–µ–Ω–∞ –æ—á–Ω–æ–π –∫–æ–Ω—Å—É–ª—å—Ç–∞—Ü–∏–∏/–æ–±—Å–ª–µ–¥–æ–≤–∞–Ω–∏—è."
)

_MEDICAL_TERMS_RE = re.compile(
    # –í–ê–ñ–ù–û: –Ω–µ –∏—Å–ø–æ–ª—å–∑—É–µ–º –≥–æ–ª—ã–π –∫–æ—Ä–µ–Ω—å ¬´–∞–Ω–∞–ª–∏–∑¬ª,
    # –∏–Ω–∞—á–µ —Ñ—Ä–∞–∑—ã ¬´–∞–Ω–∞–ª–∏–∑ PDF/—ç–ª–µ–∫—Ç—Ä–æ–Ω–Ω—ã—Ö –∫–Ω–∏–≥/—Ñ–æ—Ç–æ¬ª –æ—à–∏–±–æ—á–Ω–æ —É—Ö–æ–¥—è—Ç –≤ –º–µ–¥–∏—Ü–∏–Ω—É.
    r"(–º–µ–¥–∏—Ü–∏–Ω|–º–µ–¥–∫–∞—Ä—Ç|–∏—Å—Ç–æ—Ä–∏[—è–∏]\s+–±–æ–ª–µ–∑–Ω|–≤—ã–ø–∏—Å–∫|–∞–Ω–∞–º–Ω–µ–∑|"
    r"—Ä–µ–∑—É–ª—å—Ç–∞—Ç(?:—ã)?\s+(?:–ª–∞–±–æ—Ä–∞—Ç–æ—Ä–Ω(?:—ã—Ö|–æ–≥–æ)?\s+)?–∞–Ω–∞–ª–∏–∑(?:–æ–≤|—ã)?|"
    r"–ª–∞–±–æ—Ä–∞—Ç–æ—Ä–Ω(?:—ã–µ|—ã—Ö|–æ–≥–æ)?\s+–∞–Ω–∞–ª–∏–∑(?:—ã|–æ–≤)?|"
    r"–∞–Ω–∞–ª–∏–∑(?:—ã|–æ–≤)?\s+(?:–∫—Ä–æ–≤–∏|–º–æ—á–∏|–∫–∞–ª[–∞-—è]*|–≥–æ—Ä–º–æ–Ω(?:—ã|–æ–≤)?|–±–∏–æ—Ö–∏–º–∏[—è–∏]|—Ñ–µ—Ä—Ä–∏—Ç–∏–Ω|–≥–ª—é–∫–æ–∑[–∞-—è]*|—Ö–æ–ª–µ—Å—Ç–µ—Ä–∏–Ω)|"
    r"–∑–∞–∫–ª—é—á–µ–Ω–∏|–≤—Ä–∞—á–µ–±–Ω|–¥–∏–∞–≥–Ω–æ–∑|—ç–ø–∏–∫—Ä–∏–∑|–Ω–∞–∑–Ω–∞—á–µ–Ω–∏|—Ä–µ—Ü–µ–ø—Ç|"
    r"—Ä–µ–Ω—Ç–≥–µ–Ω|—É–∑–∏|–º—Ä—Ç|–∫—Ç|mri|ct|—Ç–æ–º–æ–≥—Ä–∞—Ñ|"
    r"(?:–º–µ–¥–∏—Ü–∏–Ω—Å–∫(?:–∏–π|–æ–≥–æ|–æ–º—É|–∏–º|–æ–º|–∞—è|—É—é|–æ–µ|–∏–µ|–∏—Ö)\s+)?—Å–Ω–∏–º–æ–∫|"
    r"–ø–µ—Ä–µ–ª–æ–º|—Ç—Ä–∞–≤–º|–±–æ–ª—å|–±–æ–ª–∏—Ç|–æ—Ç[–µ—ë]–∫|—Å–∏–º–ø—Ç–æ–º|–ª–µ—á–µ–Ω–∏–µ|–≤—Ä–∞—á|–ø–∞—Ü–∏–µ–Ω—Ç|"
    r"blood\s*test|medical|x[-\s]?ray|ultrasound|scan)",
    re.I,
)
_MEDICAL_ABILITY_RE = re.compile(
    r"(–º–æ–∂(–µ—à—å|–µ—Ç–µ|–Ω–æ)|—É–º–µ(–µ—à—å|–µ—Ç–µ)|—Å–ø–æ—Å–æ–±–µ–Ω|–ø–æ–¥–¥–µ—Ä–∂–∏–≤–∞–µ—à—å|–∞–Ω–∞–ª–∏–∑–∏—Ä—É–µ—à—å|"
    r"—Ä–∞–±–æ—Ç–∞–µ—à—å|—Ä–∞–∑–±–∏—Ä–∞–µ—à—å|–º–æ–∂–µ—Ç\s+–ª–∏|–º–æ–∂–Ω–æ\s+–ª–∏|–ø–æ–ª—É—á–∏—Ç—Å—è)",
    re.I,
)

def _is_medical_capability_question(text: str) -> bool:
    tl = (text or "").strip().lower()
    if not tl:
        return False
    return bool(_MEDICAL_TERMS_RE.search(tl) and (_MEDICAL_ABILITY_RE.search(tl) or "?" in tl))

def _medical_capability_text() -> str:
    return (
        "–î–∞, –º–æ–≥—É –ø–æ–º–æ—á—å —Å –º–µ–¥–∏—Ü–∏–Ω—Å–∫–∏–º–∏ —Ñ–∞–π–ª–∞–º–∏ –∏ –¥–æ–∫—É–º–µ–Ω—Ç–∞–º–∏.\n\n"
        "–ß—Ç–æ –º–æ–≥—É —Ä–∞–∑–æ–±—Ä–∞—Ç—å:\n"
        "‚Ä¢ –≤—ã–ø–∏—Å–∫—É –∏–∑ –º–µ–¥–∏—Ü–∏–Ω—Å–∫–æ–π –∫–∞—Ä—Ç—ã –∏ –∞–Ω–∞–º–Ω–µ–∑;\n"
        "‚Ä¢ –≤—Ä–∞—á–µ–±–Ω–æ–µ –∑–∞–∫–ª—é—á–µ–Ω–∏–µ/—ç–ø–∏–∫—Ä–∏–∑/–Ω–∞–∑–Ω–∞—á–µ–Ω–∏—è;\n"
        "‚Ä¢ —Ä–µ–∑—É–ª—å—Ç–∞—Ç—ã –ª–∞–±–æ—Ä–∞—Ç–æ—Ä–Ω—ã—Ö –∞–Ω–∞–ª–∏–∑–æ–≤;\n"
        "‚Ä¢ —Å–Ω–∏–º–æ–∫, —Ñ–æ—Ç–æ –¥–æ–∫—É–º–µ–Ω—Ç–∞, –£–ó–ò/—Ä–µ–Ω—Ç–≥–µ–Ω;\n"
        "‚Ä¢ –æ–ø–∏—Å–∞–Ω–∏–µ –ú–†–¢ –∏ –ö–¢, –∞ —Ç–∞–∫–∂–µ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ, –µ—Å–ª–∏ –µ–≥–æ –º–æ–∂–Ω–æ –ø—Ä–æ—á–∏—Ç–∞—Ç—å –ø–æ —Ñ–æ—Ç–æ.\n\n"
        "–ß—Ç–æ –≤—ã –ø–æ–ª—É—á–∏—Ç–µ: –ø–æ–Ω—è—Ç–Ω—É—é –≤—ã–∂–∏–º–∫—É, —Ä–∞—Å—à–∏—Ñ—Ä–æ–≤–∫—É —Ç–µ—Ä–º–∏–Ω–æ–≤, –∫–ª—é—á–µ–≤—ã–µ –ø–æ–∫–∞–∑–∞—Ç–µ–ª–∏, "
        "–∫—Ä–∞—Å–Ω—ã–µ —Ñ–ª–∞–≥–∏, —Å–ø–∏—Å–æ–∫ –≤–æ–ø—Ä–æ—Å–æ–≤ –≤—Ä–∞—á—É –∏ –ø–ª–∞–Ω, —á—Ç–æ —É—Ç–æ—á–Ω–∏—Ç—å –¥–∞–ª—å—à–µ."
        + MEDICAL_DISCLAIMER
    )

def _medical_menu_text(track: str = "") -> str:
    title = {
        "med_extract": "–≤—ã–ø–∏—Å–∫—É –∏–∑ –º–µ–¥–∏—Ü–∏–Ω—Å–∫–æ–π –∫–∞—Ä—Ç—ã",
        "med_scan": "—Å–Ω–∏–º–æ–∫/—Ñ–æ—Ç–æ –º–µ–¥–∏—Ü–∏–Ω—Å–∫–æ–≥–æ –¥–æ–∫—É–º–µ–Ω—Ç–∞",
        "med_conclusion": "–≤—Ä–∞—á–µ–±–Ω–æ–µ –∑–∞–∫–ª—é—á–µ–Ω–∏–µ",
        "med_mri": "–ú–†–¢",
        "med_ct": "–ö–¢",
        "med_labs": "—Ä–µ–∑—É–ª—å—Ç–∞—Ç—ã –∞–Ω–∞–ª–∏–∑–æ–≤",
    }.get(track, "–º–µ–¥–∏—Ü–∏–Ω—Å–∫–∏–π –¥–æ–∫—É–º–µ–Ω—Ç –∏–ª–∏ —Å–Ω–∏–º–æ–∫")
    return (
        f"ü©∫ –ú–µ–¥–∏—Ü–∏–Ω–∞ ‚Äî –≥–æ—Ç–æ–≤ —Ä–∞–∑–æ–±—Ä–∞—Ç—å {title}.\n\n"
        "–ö–∞–∫ –∑–∞–≥—Ä—É–∑–∏—Ç—å:\n"
        "1) –Ω–∞–∂–º–∏—Ç–µ –Ω—É–∂–Ω—É—é –∫–Ω–æ–ø–∫—É –Ω–∏–∂–µ;\n"
        "2) –æ—Ç–ø—Ä–∞–≤—å—Ç–µ PDF/DOCX/TXT –∏–ª–∏ —Ñ–æ—Ç–æ/—Å–∫—Ä–∏–Ω/–∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ;\n"
        "3) –≤ –ø–æ–¥–ø–∏—Å–∏ –º–æ–∂–Ω–æ –Ω–∞–ø–∏—Å–∞—Ç—å —Ü–µ–ª—å: ¬´–∫–æ—Ä–æ—Ç–∫–æ¬ª, ¬´–ø–æ–¥—Ä–æ–±–Ω–æ¬ª, ¬´—á—Ç–æ —Å–ø—Ä–æ—Å–∏—Ç—å —É –≤—Ä–∞—á–∞¬ª, "
        "¬´–æ–±—ä—è—Å–Ω–∏ –ø—Ä–æ—Å—Ç—ã–º–∏ —Å–ª–æ–≤–∞–º–∏¬ª.\n\n"
        "–†–µ–∑—É–ª—å—Ç–∞—Ç: –∫—Ä–∞—Ç–∫–æ–µ —Ä–µ–∑—é–º–µ, —Ä–∞—Å—à–∏—Ñ—Ä–æ–≤–∫–∞ —Ç–µ—Ä–º–∏–Ω–æ–≤, –≤–∞–∂–Ω—ã–µ —Ü–∏—Ñ—Ä—ã/–Ω–∞—Ö–æ–¥–∫–∏, "
        "–≤–æ–∑–º–æ–∂–Ω—ã–µ —Ä–∏—Å–∫–∏, –≤–æ–ø—Ä–æ—Å—ã –≤—Ä–∞—á—É –∏ —á—Ç–æ –ø—Ä–æ–≤–µ—Ä–∏—Ç—å –¥–æ–ø–æ–ª–Ω–∏—Ç–µ–ª—å–Ω–æ."
        + MEDICAL_DISCLAIMER
    )

def medicine_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("üìÑ –†–∞–∑–±–æ—Ä –≤—ã–ø–∏—Å–∫–∏", callback_data="act:med:extract")],
        [InlineKeyboardButton("üñº –†–∞–∑–±–æ—Ä —Å–Ω–∏–º–∫–∞", callback_data="act:med:scan")],
        [InlineKeyboardButton("üßæ –ó–∞–∫–ª—é—á–µ–Ω–∏–µ –≤—Ä–∞—á–∞", callback_data="act:med:conclusion")],
        [InlineKeyboardButton("üß≤ –ú–†–¢", callback_data="act:med:mri"),
         InlineKeyboardButton("üß† –ö–¢", callback_data="act:med:ct")],
        [InlineKeyboardButton("üß™ –ê–Ω–∞–ª–∏–∑—ã", callback_data="act:med:labs")],
        [InlineKeyboardButton("üìù –ú–µ–¥. –≤–æ–ø—Ä–æ—Å", callback_data="act:med:free")],
        [InlineKeyboardButton("‚¨ÖÔ∏è –ù–∞–∑–∞–¥", callback_data="mode:root")],
    ])

def _medical_track_title(track: str) -> str:
    return {
        "med_extract": "–≤—ã–ø–∏—Å–∫–∞ / –∞–Ω–∞–º–Ω–µ–∑",
        "med_scan": "–º–µ–¥–∏—Ü–∏–Ω—Å–∫–∏–π —Å–Ω–∏–º–æ–∫ / —Ñ–æ—Ç–æ",
        "med_conclusion": "–≤—Ä–∞—á–µ–±–Ω–æ–µ –∑–∞–∫–ª—é—á–µ–Ω–∏–µ",
        "med_mri": "–ú–†–¢",
        "med_ct": "–ö–¢",
        "med_labs": "–ª–∞–±–æ—Ä–∞—Ç–æ—Ä–Ω—ã–µ –∞–Ω–∞–ª–∏–∑—ã",
        "med_free": "–º–µ–¥–∏—Ü–∏–Ω—Å–∫–∏–π –≤–æ–ø—Ä–æ—Å",
    }.get(track or "", "–º–µ–¥–∏—Ü–∏–Ω—Å–∫–∏–π –º–∞—Ç–µ—Ä–∏–∞–ª")

def _is_medical_context(user_id: int, caption_or_text: str = "", filename: str = "") -> bool:
    # –°–æ–≤–º–µ—Å—Ç–∏–º–æ—Å—Ç—å –¥–ª—è —Å—Ç–∞—Ä—ã—Ö –º–µ—Å—Ç –≤—ã–∑–æ–≤–∞ –±–µ–∑ context.
    # –í–ê–ñ–ù–û: –æ–¥–∏–Ω —Ç–æ–ª—å–∫–æ mode == "–ú–µ–¥–∏—Ü–∏–Ω–∞" –±–æ–ª—å—à–µ –Ω–µ —Å—á–∏—Ç–∞–µ—Ç—Å—è –ø—Ä–∏—á–∏–Ω–æ–π
    # –æ—Ç–ø—Ä–∞–≤–ª—è—Ç—å –ª—é–±–æ–µ —Ñ–æ—Ç–æ/–¥–æ–∫—É–º–µ–Ω—Ç –≤ –º–µ–¥–∏—Ü–∏–Ω—Å–∫—É—é –≤–µ—Ç–∫—É.
    track = ""
    with contextlib.suppress(Exception):
        track = _mode_track_get(user_id)
    combined = f"{caption_or_text or ''} {filename or ''}"
    return bool(_MEDICAL_TERMS_RE.search(combined))

def _medical_doc_prompt(text: str, track: str = "", goal: str | None = None) -> str:
    task = _medical_track_title(track)
    extra = f"\n–¶–µ–ª—å –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è: {goal}" if goal else ""
    return (
        f"–¢—ã –∞–Ω–∞–ª–∏–∑–∏—Ä—É–µ—à—å –º–µ–¥–∏—Ü–∏–Ω—Å–∫–∏–π –º–∞—Ç–µ—Ä–∏–∞–ª: {task}. "
        "–ù–µ —Å—Ç–∞–≤—å –¥–∏–∞–≥–Ω–æ–∑ –∏ –Ω–µ –Ω–∞–∑–Ω–∞—á–∞–π –ª–µ—á–µ–Ω–∏–µ. –î–∞–π —Å–ø—Ä–∞–≤–æ—á–Ω—ã–π —Ä–∞–∑–±–æ—Ä –Ω–∞ —Ä—É—Å—Å–∫–æ–º. "
        "–°—Ç—Ä—É–∫—Ç—É—Ä–∞ –æ—Ç–≤–µ—Ç–∞:\n"
        "1) –ß—Ç–æ —ç—Ç–æ –∑–∞ –¥–æ–∫—É–º–µ–Ω—Ç/–∏—Å—Å–ª–µ–¥–æ–≤–∞–Ω–∏–µ.\n"
        "2) –ö—Ä–∞—Ç–∫–æ–µ —Ä–µ–∑—é–º–µ –ø—Ä–æ—Å—Ç—ã–º–∏ —Å–ª–æ–≤–∞–º–∏.\n"
        "3) –ö–ª—é—á–µ–≤—ã–µ –ø–æ–∫–∞–∑–∞—Ç–µ–ª–∏/–Ω–∞—Ö–æ–¥–∫–∏ –∏ —á—Ç–æ –æ–Ω–∏ –º–æ–≥—É—Ç –æ–∑–Ω–∞—á–∞—Ç—å –≤ –æ–±—â–µ–º —Å–º—ã—Å–ª–µ.\n"
        "4) –í–æ–∑–º–æ–∂–Ω—ã–µ —Ç—Ä–µ–≤–æ–∂–Ω—ã–µ –ø—É–Ω–∫—Ç—ã, –∫–æ—Ç–æ—Ä—ã–µ —Å—Ç–æ–∏—Ç –æ–±—Å—É–¥–∏—Ç—å —Å –≤—Ä–∞—á–æ–º.\n"
        "5) –°–ø–∏—Å–æ–∫ –≤–æ–ø—Ä–æ—Å–æ–≤ –≤—Ä–∞—á—É.\n"
        "6) –ß—Ç–æ –ø—Ä–æ–≤–µ—Ä–∏—Ç—å/–∫–∞–∫–∏–µ –¥–∞–Ω–Ω—ã–µ –Ω—É–∂–Ω—ã –¥–ª—è –ø–æ–ª–Ω–æ—Ü–µ–Ω–Ω–æ–π –æ—Ü–µ–Ω–∫–∏.\n"
        "–í –∫–æ–Ω—Ü–µ –æ–±—è–∑–∞—Ç–µ–ª—å–Ω–æ –¥–æ–±–∞–≤—å: —ç—Ç–æ –Ω–µ –¥–∏–∞–≥–Ω–æ–∑ –∏ –Ω–µ –∑–∞–º–µ–Ω–∞ –∫–æ–Ω—Å—É–ª—å—Ç–∞—Ü–∏–∏ –≤—Ä–∞—á–∞."
        f"{extra}\n\n–¢–µ–∫—Å—Ç –¥–æ–∫—É–º–µ–Ω—Ç–∞:\n{text[:24000]}"
    )

async def _medical_analyze_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, goal: str | None = None):
    user_id = update.effective_user.id
    track = _mode_track_get(user_id)
    await update.effective_message.reply_text("ü©∫ –ê–Ω–∞–ª–∏–∑–∏—Ä—É—é –º–µ–¥–∏—Ü–∏–Ω—Å–∫–∏–π –º–∞—Ç–µ—Ä–∏–∞–ª. –≠—Ç–æ —Å–ø—Ä–∞–≤–æ—á–Ω—ã–π —Ä–∞–∑–±–æ—Ä, –Ω–µ –¥–∏–∞–≥–Ω–æ–∑‚Ä¶")
    ans = await ask_openai_text(_medical_doc_prompt(text, track=track, goal=goal))
    if MEDICAL_DISCLAIMER.strip() not in ans:
        ans = ans.rstrip() + MEDICAL_DISCLAIMER
    await update.effective_message.reply_text(ans[:3900])
    if len(ans) > 3900:
        await update.effective_message.reply_text(ans[3900:7800])
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])

async def _medical_analyze_image(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes, goal: str | None = None):
    user_id = update.effective_user.id
    track = _mode_track_get(user_id)
    await update.effective_message.reply_text("ü©∫ –ê–Ω–∞–ª–∏–∑–∏—Ä—É—é –º–µ–¥–∏—Ü–∏–Ω—Å–∫–æ–µ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ/—Å–Ω–∏–º–æ–∫. –≠—Ç–æ —Å–ø—Ä–∞–≤–æ—á–Ω—ã–π —Ä–∞–∑–±–æ—Ä, –Ω–µ –¥–∏–∞–≥–Ω–æ–∑‚Ä¶")
    prompt = (
        f"–†–∞–∑–±–µ—Ä–∏ –º–µ–¥–∏—Ü–∏–Ω—Å–∫–æ–µ –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ/–¥–æ–∫—É–º–µ–Ω—Ç: {_medical_track_title(track)}. "
        "–ï—Å–ª–∏ —ç—Ç–æ —Ñ–æ—Ç–æ –≤—ã–ø–∏—Å–∫–∏/–∞–Ω–∞–ª–∏–∑–æ–≤ ‚Äî –ø—Ä–æ—á–∏—Ç–∞–π –≤–∏–¥–∏–º—ã–π —Ç–µ–∫—Å—Ç –∏ —Å—Ç—Ä—É–∫—Ç—É—Ä–∏—Ä—É–π. "
        "–ï—Å–ª–∏ —ç—Ç–æ —Å–Ω–∏–º–æ–∫ –ú–†–¢/–ö–¢/—Ä–µ–Ω—Ç–≥–µ–Ω/–£–ó–ò ‚Äî –æ–ø–∏—à–∏ —Ç–æ–ª—å–∫–æ –≤–∏–¥–∏–º—ã–µ —ç–ª–µ–º–µ–Ω—Ç—ã –∏ –æ–≥—Ä–∞–Ω–∏—á–µ–Ω–∏—è: "
        "–ø–æ –æ–¥–Ω–æ–º—É –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—é –Ω–µ–ª—å–∑—è —Å—Ç–∞–≤–∏—Ç—å –¥–∏–∞–≥–Ω–æ–∑, –Ω—É–∂–µ–Ω –æ—Ñ–∏—Ü–∏–∞–ª—å–Ω—ã–π –ø—Ä–æ—Ç–æ–∫–æ–ª –∏ –≤—Ä–∞—á. "
        "–î–∞–π: 1) —á—Ç–æ –≤–∏–¥–Ω–æ, 2) –≤–æ–∑–º–æ–∂–Ω—ã–π —Å–º—ã—Å–ª —Ç–µ—Ä–º–∏–Ω–æ–≤/–ø–æ–∫–∞–∑–∞—Ç–µ–ª–µ–π, 3) —á—Ç–æ —É—Ç–æ—á–Ω–∏—Ç—å —É –≤—Ä–∞—á–∞, "
        "4) –∫–∞–∫–∏–µ –¥–æ–ø–æ–ª–Ω–∏—Ç–µ–ª—å–Ω—ã–µ –¥–∞–Ω–Ω—ã–µ –Ω—É–∂–Ω—ã. –ù–µ –Ω–∞–∑–Ω–∞—á–∞–π –ª–µ—á–µ–Ω–∏–µ. "
        "–í –∫–æ–Ω—Ü–µ –¥–æ–±–∞–≤—å –ø—Ä–µ–¥—É–ø—Ä–µ–∂–¥–µ–Ω–∏–µ, —á—Ç–æ —ç—Ç–æ –Ω–µ –æ—Ñ–∏—Ü–∏–∞–ª—å–Ω–æ–µ –º–µ–¥–∏—Ü–∏–Ω—Å–∫–æ–µ –∑–∞–∫–ª—é—á–µ–Ω–∏–µ."
    )
    if goal:
        prompt += f"\n–¶–µ–ª—å –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è: {goal}"
    b64 = base64.b64encode(img_bytes).decode("ascii")
    ans = await ask_openai_vision(prompt, b64, sniff_image_mime(img_bytes))
    if MEDICAL_DISCLAIMER.strip() not in ans:
        ans = ans.rstrip() + MEDICAL_DISCLAIMER
    await update.effective_message.reply_text(ans[:3900])
    if len(ans) > 3900:
        await update.effective_message.reply_text(ans[3900:7800])
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])

def capability_answer(text: str) -> str | None:
    """
    –ö–æ—Ä–æ—Ç–∫–∏–µ –æ—Ç–≤–µ—Ç—ã –Ω–∞ –≤–æ–ø—Ä–æ—Å—ã –≤–∏–¥–∞:
    - ¬´—Ç—ã –º–æ–∂–µ—à—å –∞–Ω–∞–ª–∏–∑–∏—Ä–æ–≤–∞—Ç—å PDF?¬ª
    - ¬´—Ç—ã —É–º–µ–µ—à—å —Ä–∞–±–æ—Ç–∞—Ç—å —Å —ç–ª–µ–∫—Ç—Ä–æ–Ω–Ω—ã–º–∏ –∫–Ω–∏–≥–∞–º–∏?¬ª
    - ¬´—Ç—ã –º–æ–∂–µ—à—å —Å–æ–∑–¥–∞–≤–∞—Ç—å –≤–∏–¥–µ–æ?¬ª –∏ —Ç.–ø.

    –í–∞–∂–Ω–æ: –Ω–µ –ø–µ—Ä–µ—Ö–≤–∞—Ç—ã–≤–∞–µ–º —Ä–µ–∞–ª—å–Ω—ã–µ –∫–æ–º–∞–Ω–¥—ã
    ¬´—Å–¥–µ–ª–∞–π –≤–∏–¥–µ–æ‚Ä¶¬ª, ¬´—Å–≥–µ–Ω–µ—Ä–∏—Ä—É–π –∫–∞—Ä—Ç–∏–Ω–∫—É‚Ä¶¬ª –∏ —Ç.–¥.
    """
    tl = (text or "").strip().lower()
    if not tl:
        return None

    if _is_general_capability_query(tl):
        return (
            "–î–∞. –Ø ‚Äî Neyro-Bot GPT 5 Studio, –º—É–ª—å—Ç–∏–º–æ–¥–µ–ª—å–Ω–∞—è AI-—Å—Ç—É–¥–∏—è –≤ Telegram –¥–ª—è —Ç–µ–∫—Å—Ç–∞, –¥–æ–∫—É–º–µ–Ω—Ç–æ–≤, —Ñ–æ—Ç–æ, –≤–∏–¥–µ–æ, –º—É–∑—ã–∫–∏, —Ä–µ—á–∏ –∏ live-–¥–∞–Ω–Ω—ã—Ö.\n\n"
            "–û—Å–Ω–æ–≤–Ω—ã–µ —Ä–µ–∂–∏–º—ã:\n"
            "‚Ä¢ üéì –£—á—ë–±–∞ ‚Äî –æ–±—ä—è—Å–Ω–µ–Ω–∏–µ —Ç–µ–º, –∑–∞–¥–∞—á–∏, –∫–æ–Ω—Å–ø–µ–∫—Ç—ã –∏–∑ PDF/EPUB/DOCX, —ç—Å—Å–µ –∏ –ø–ª–∞–Ω—ã –∫ —ç–∫–∑–∞–º–µ–Ω—É.\n"
            "‚Ä¢ üíº –†–∞–±–æ—Ç–∞/–ë–∏–∑–Ω–µ—Å ‚Äî –ø–∏—Å—å–º–∞, –ö–ü, –¥–æ–∫—É–º–µ–Ω—Ç—ã, –∞–Ω–∞–ª–∏—Ç–∏–∫–∞, –ø—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏–∏, PDF-–∫–∞—Ç–∞–ª–æ–≥–∏, –ª–æ–≥–æ—Ç–∏–ø—ã, ToDo, –±—Ä–∏—Ñ—ã –∏ —Ä–µ—Ç—É—à—å –±–∏–∑–Ω–µ—Å-—Ñ–æ—Ç–æ.\n"
            "‚Ä¢ üî• –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è ‚Äî –æ–∂–∏–≤–ª–µ–Ω–∏–µ —Ñ–æ—Ç–æ, –∑–∞–º–µ–Ω–∞ –ª–∏—Ü–∞, —É–¥–∞–ª–µ–Ω–∏–µ/–∑–∞–º–µ–Ω–∞ —Ñ–æ–Ω–∞, —É–¥–∞–ª–µ–Ω–∏–µ –≤–æ–¥—è–Ω—ã—Ö –∑–Ω–∞–∫–æ–≤, Reels/Shorts, –º–∏–Ω–∏-—Ñ–∏–ª—å–º—ã, —Å—Ü–µ–Ω–∞—Ä–∏–∏.\n"
            "‚Ä¢ ü©∫ –ú–µ–¥–∏—Ü–∏–Ω–∞ ‚Äî —Å–ø—Ä–∞–≤–æ—á–Ω—ã–π —Ä–∞–∑–±–æ—Ä –≤—ã–ø–∏—Å–æ–∫, –∞–Ω–∞–ª–∏–∑–æ–≤, –ú–†–¢/–ö–¢/—Å–Ω–∏–º–∫–æ–≤ –±–µ–∑ –ø–æ—Å—Ç–∞–Ω–æ–≤–∫–∏ –¥–∏–∞–≥–Ω–æ–∑–∞.\n"
            "‚Ä¢ üß† –î–≤–∏–∂–∫–∏ ‚Äî –ø—Ä–∏–Ω—É–¥–∏—Ç–µ–ª—å–Ω—ã–π –≤—ã–±–æ—Ä GPT-5, OpenAI Images, Runway, Sora 2, Kling, Midjourney, Deepgram/STT/TTS, Photoroom, PiAPI/Segmind.\n\n"
            "–ú–æ–∂–Ω–æ –ø—Ä–æ—Å—Ç–æ –Ω–∞–ø–∏—Å–∞—Ç—å –∑–∞–¥–∞—á—É –∏–ª–∏ –æ—Ç–ø—Ä–∞–≤–∏—Ç—å —Ñ–æ—Ç–æ/–¥–æ–∫—É–º–µ–Ω—Ç/–≥–æ–ª–æ—Å–æ–≤–æ–µ. –î–ª—è –∑–∞–º–µ–Ω—ã –ª–∏—Ü–∞: üî• –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è ‚Üí üé≠ –ó–∞–º–µ–Ω–∞ –ª–∏—Ü–∞ –Ω–∞ —Ñ–æ—Ç–æ. "
            "–î–ª—è —Ñ–æ–Ω–∞: üî• –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è ‚Üí üßº –£–¥–∞–ª–∏—Ç—å —Ñ–æ–Ω –∏–ª–∏ üñº –ó–∞–º–µ–Ω–∏—Ç—å —Ñ–æ–Ω. –î–ª—è –æ–∑–≤—É—á–∫–∏ –æ—Ç–≤–µ—Ç–æ–≤: /voice_on."
        )

    if _is_medical_capability_question(tl):
        return _medical_capability_text()

    if _is_photo_revival_question(tl):
        return _photo_revival_capability_text()

    # --- –ó–∞–º–µ–Ω–∞ –ª–∏—Ü / FaceSwap ---
    if (
        re.search(r"(–º–æ–∂(–µ—à—å|–µ—Ç–µ|–Ω–æ)|—É–º–µ(–µ—à—å|–µ—Ç–µ)|—Å–ø–æ—Å–æ–±–µ–Ω|–ø–æ–¥–¥–µ—Ä–∂–∏–≤–∞–µ—à—å|–¥–µ–ª–∞–µ—à—å|–∑–∞–º–µ–Ω—è–µ—à—å|–º–æ–∂–µ—Ç\s+–ª–∏)", tl, re.I)
        and re.search(r"(–∑–∞–º–µ–Ω|–ø–æ–º–µ–Ω—è|–ø–æ–¥–º–µ–Ω|face\s*swap|faceswap)", tl, re.I)
        and re.search(r"(–ª–∏—Ü|–ª–∏—Ü–∞|–ª–∏—Ü–æ|face|—á–µ–ª–æ–≤–µ–∫–∞|—Ñ–æ—Ç–æ|—Ñ–æ—Ç–æ–≥—Ä–∞—Ñ|–∫–∞—Ä—Ç–∏–Ω–∫|–∏–∑–æ–±—Ä–∞–∂–µ–Ω)", tl, re.I)
    ):
        return (
            "–î–∞, —è —É–º–µ—é –∑–∞–º–µ–Ω—è—Ç—å –ª–∏—Ü–∞ –Ω–∞ —Ñ–æ—Ç–æ–≥—Ä–∞—Ñ–∏—è—Ö. –ú–æ–∂–Ω–æ —Ä–∞–±–æ—Ç–∞—Ç—å —Å —Ñ–æ—Ç–æ, –≥–¥–µ –æ–¥–∏–Ω, –¥–≤–∞ –∏–ª–∏ –Ω–µ—Å–∫–æ–ª—å–∫–æ —á–µ–ª–æ–≤–µ–∫: "
            "–±–æ—Ç –ø–æ–∫–∞–∂–µ—Ç –Ω–∞–π–¥–µ–Ω–Ω—ã–µ –ª–∏—Ü–∞ —Å –Ω–æ–º–µ—Ä–∞–º–∏, –≤—ã –≤—ã–±–µ—Ä–µ—Ç–µ, –∫–∞–∫–æ–µ –∏–º–µ–Ω–Ω–æ –ª–∏—Ü–æ –∑–∞–º–µ–Ω–∏—Ç—å, –∑–∞—Ç–µ–º –∑–∞–≥—Ä—É–∑–∏—Ç–µ –ª–∏—Ü–æ-–∏—Å—Ç–æ—á–Ω–∏–∫.\n\n"
            "–ö–∞–∫ –∑–∞–ø—É—Å—Ç–∏—Ç—å:\n"
            "1) –Ω–∞–∂–º–∏—Ç–µ üî• –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è ‚Üí üé≠ –ó–∞–º–µ–Ω–∞ –ª–∏—Ü–∞ –Ω–∞ —Ñ–æ—Ç–æ;\n"
            "2) –∑–∞–≥—Ä—É–∑–∏—Ç–µ –æ—Å–Ω–æ–≤–Ω–æ–µ —Ñ–æ—Ç–æ;\n"
            "3) –≤—ã–±–µ—Ä–∏—Ç–µ —Ü–µ–ª–µ–≤–æ–µ –ª–∏—Ü–æ –ø–æ –Ω–æ–º–µ—Ä—É ‚Äî —Å–ª–µ–≤–∞/—Ü–µ–Ω—Ç—Ä/—Å–ø—Ä–∞–≤–∞;\n"
            "4) –∑–∞–≥—Ä—É–∑–∏—Ç–µ —Ñ–æ—Ç–æ –ª–∏—Ü–∞, –∫–æ—Ç–æ—Ä–æ–µ –Ω—É–∂–Ω–æ –≤—Å—Ç–∞–≤–∏—Ç—å;\n"
            "5) –≤—ã–±–µ—Ä–∏—Ç–µ –∫–∞—á–µ—Å—Ç–≤–æ: ‚ö° –ë—ã—Å—Ç—Ä–æ —á–µ—Ä–µ–∑ PiAPI –∏–ª–∏ üíé –ü—Ä–µ–º–∏—É–º —á–µ—Ä–µ–∑ Segmind, –µ—Å–ª–∏ –Ω–∞ –±–∞–ª–∞–Ω—Å–µ Segmind –µ—Å—Ç—å –∫—Ä–µ–¥–∏—Ç—ã.\n\n"
            "–¢–∞–∫–∂–µ –º–æ–∂–Ω–æ –ø—Ä–æ—Å—Ç–æ –∑–∞–≥—Ä—É–∑–∏—Ç—å —Ñ–æ—Ç–æ –∏ –Ω–∞–∂–∞—Ç—å –∫–Ω–æ–ø–∫—É üé≠ –ó–∞–º–µ–Ω–∞ –ª–∏—Ü–∞. "
            "–Ø —Å–æ—Ö—Ä–∞–Ω—è—é —Ç–µ–ª–æ, –æ–¥–µ–∂–¥—É, —Ñ–æ–Ω –∏ –∫–æ–º–ø–æ–∑–∏—Ü–∏—é –∏—Å—Ö–æ–¥–Ω–æ–≥–æ —Ñ–æ—Ç–æ, –º–µ–Ω—è–µ—Ç—Å—è —Ç–æ–ª—å–∫–æ –≤—ã–±—Ä–∞–Ω–Ω–æ–µ –ª–∏—Ü–æ."
        )

    # --- –û–∂–∏–≤–ª–µ–Ω–∏–µ —Ñ–æ—Ç–æ / image-to-video ---
    if (
        re.search(r"(–º–æ–∂(–µ—à—å|–µ—Ç–µ)|—É–º–µ(–µ—à—å|–µ—Ç–µ)|–º–æ–∂–µ—Ç\s+–ª–∏|—Å–ø–æ—Å–æ–±–µ–Ω|–ø–æ–¥–¥–µ—Ä–∂–∏–≤–∞–µ—à—å)", tl)
        and re.search(r"(–æ–∂–∏–≤|–∞–Ω–∏–º–∏—Ä|–¥–≤–∏–∂–µ–Ω–∏|image\s*to\s*video|i2v)", tl)
        and re.search(r"(—Ñ–æ—Ç–æ|—Ñ–æ—Ç–æ–≥—Ä–∞—Ñ|–∫–∞—Ä—Ç–∏–Ω–∫|–∏–∑–æ–±—Ä–∞–∂–µ–Ω|image|picture)", tl)
    ):
        return (
            "–î–∞, –º–æ–≥—É –æ–∂–∏–≤–∏—Ç—å —Ñ–æ—Ç–æ–≥—Ä–∞—Ñ–∏—é –∏ —Å–¥–µ–ª–∞—Ç—å –∏–∑ –Ω–µ—ë –∫–æ—Ä–æ—Ç–∫–æ–µ –≤–∏–¥–µ–æ. "
            "–ó–∞–≥—Ä—É–∑–∏—Ç–µ —Ñ–æ—Ç–æ ‚Äî —è –ø–æ–∫–∞–∂—É –∫–Ω–æ–ø–∫–∏ Runway, Kling –∏ Sora 2 –±–µ–∑ –ª—é–¥–µ–π. "
            "–ú–æ–∂–Ω–æ —Ç–∞–∫–∂–µ –æ—Ç–ø—Ä–∞–≤–∏—Ç—å —Ñ–æ—Ç–æ —Å –ø–æ–¥–ø–∏—Å—å—é: ¬´–æ–∂–∏–≤–∏ —Ñ–æ—Ç–æ: –ª—ë–≥–∫–∞—è —É–ª—ã–±–∫–∞, –¥–≤–∏–∂–µ–Ω–∏–µ –∫–∞–º–µ—Ä—ã, 5 —Å–µ–∫—É–Ω–¥, 9:16¬ª."
        )

    # --- –ú–µ–¥–∏—Ü–∏–Ω–∞ / –º–µ–¥. –¥–æ–∫—É–º–µ–Ω—Ç—ã / –∞–Ω–∞–ª–∏–∑—ã / –ú–†–¢ / –ö–¢ ---
    if _is_medical_capability_question(tl):
        return _medical_capability_text()

    # --- –î–æ–∫—É–º–µ–Ω—Ç—ã / —Ñ–∞–π–ª—ã ---
    if re.search(r"\b(pdf|docx|epub|fb2|txt|mobi|azw)\b", tl) and "?" in tl:
        return (
            "–î–∞, —è –º–æ–≥—É –ø–æ–º–æ—á—å —Å –∞–Ω–∞–ª–∏–∑–æ–º –¥–æ–∫—É–º–µ–Ω—Ç–æ–≤ –∏ —ç–ª–µ–∫—Ç—Ä–æ–Ω–Ω—ã—Ö –∫–Ω–∏–≥. "
            "–û—Ç–ø—Ä–∞–≤—å —Ñ–∞–π–ª (PDF, EPUB, DOCX, FB2, TXT, MOBI/AZW ‚Äì –ø–æ –≤–æ–∑–º–æ–∂–Ω–æ—Å—Ç–∏), "
            "–∞ –≤ —Å–æ–æ–±—â–µ–Ω–∏–∏ –Ω–∞–ø–∏—à–∏, —á—Ç–æ –Ω—É–∂–Ω–æ: –∫–æ–Ω—Å–ø–µ–∫—Ç, –ø–ª–∞–Ω, —Ä–∞–∑–±–æ—Ä –∏ —Ç.–ø."
        )

    # --- –ê—É–¥–∏–æ / —Ä–µ—á—å ---
    if "–∞—É–¥–∏–æ" in tl or "–≥–æ–ª–æ—Å–æ–≤" in tl or "speech" in tl:
        if "?" in tl or "–º–æ–∂–µ—à—å" in tl or "—É–º–µ–µ—à—å" in tl:
            return (
                "–î–∞, —è –º–æ–≥—É —Ä–∞—Å–ø–æ–∑–Ω–∞–≤–∞—Ç—å —Ä–µ—á—å –∏–∑ –≥–æ–ª–æ—Å–æ–≤—ã—Ö –∏ –∞—É–¥–∏–æ. "
                "–ü—Ä–æ—Å—Ç–æ –ø—Ä–∏—à–ª–∏ –≥–æ–ª–æ—Å–æ–≤–æ–µ —Å–æ–æ–±—â–µ–Ω–∏–µ ‚Äî —è —Ä–∞—Å—à–∏—Ñ—Ä—É—é –µ–≥–æ –≤ —Ç–µ–∫—Å—Ç "
                "–∏ –æ—Ç–≤–µ—á—É –∫–∞–∫ –Ω–∞ –æ–±—ã—á–Ω—ã–π –∑–∞–ø—Ä–æ—Å."
            )

    # --- –ú—É–∑—ã–∫–∞ / Suno ---
    if (
        re.search(r"(–º—É–∑—ã–∫|–ø–µ—Å–Ω|—Ç—Ä–µ–∫|–¥–∂–∏–Ω–≥–ª|–º–∏–Ω—É—Å–æ–≤–∫|suno|music|song)", tl, re.I)
        and re.search(r"(–º–æ–∂(–µ—à—å|–µ—Ç–µ|–Ω–æ)|—É–º–µ(–µ—à—å|–µ—Ç–µ)|—Å–æ–∑–¥–∞[–µ—ë]—à—å|–¥–µ–ª–∞–µ—à—å|—Å–≥–µ–Ω–µ—Ä–∏—Ä—É–µ—à—å|–Ω–∞–ø–∏—Å–∞—Ç—å|–ø–æ–ª—É—á–∏—Ç—Å—è)", tl, re.I)
    ):
        return (
            "–î–∞, –º–æ–≥—É –∑–∞–ø—É—Å–∫–∞—Ç—å –≥–µ–Ω–µ—Ä–∞—Ü–∏—é –º—É–∑—ã–∫–∏ —á–µ—Ä–µ–∑ Suno. "
            "–ü–æ–¥—Ö–æ–¥–∏—Ç –¥–ª—è –ø–µ—Å–µ–Ω —Å —Ç–µ–∫—Å—Ç–æ–º, –¥–∂–∏–Ω–≥–ª–æ–≤, —Ñ–æ–Ω–æ–≤–æ–π –º—É–∑—ã–∫–∏, –∏–Ω—Ç—Ä–æ/–∞—É—Ç—Ä–æ, –º–∏–Ω—É—Å–æ–≤–æ–∫ –∏ –¥–µ–º–æ-—Ç—Ä–µ–∫–æ–≤.\n\n"
            "–ö–∞–∫ –∑–∞–ø—É—Å—Ç–∏—Ç—å: üî• –†–∞–∑–≤–ª–µ—á–µ–Ω–∏—è ‚Üí üéµ –ú—É–∑—ã–∫–∞ / –ø–µ—Å–Ω—è –∏–ª–∏ –∫–æ–º–∞–Ω–¥–∞ /music <–æ–ø–∏—Å–∞–Ω–∏–µ>. "
            "–í –æ–ø–∏—Å–∞–Ω–∏–∏ —É–∫–∞–∂–∏—Ç–µ –∂–∞–Ω—Ä, –Ω–∞—Å—Ç—Ä–æ–µ–Ω–∏–µ, —è–∑—ã–∫, –ø—Ä–∏–º–µ—Ä–Ω—ã–π —Ç–µ–º–ø/BPM, –Ω—É–∂–µ–Ω –ª–∏ –≤–æ–∫–∞–ª, —Ç–µ–∫—Å—Ç –∫—É–ø–ª–µ—Ç–∞/–ø—Ä–∏–ø–µ–≤–∞ –∏–ª–∏ instrumental."
        )

    # --- –í–∏–¥–µ–æ / —Ä–æ–ª–∏–∫–∏ / Reels / Shorts ---
    # –í–∞–∂–Ω–æ: –≥–æ–ª–æ—Å–æ–≤—ã–µ —á–∞—Å—Ç–æ –ø—Ä–∏—Ö–æ–¥—è—Ç –±–µ–∑ –≤–æ–ø—Ä–æ—Å–∏—Ç–µ–ª—å–Ω–æ–≥–æ –∑–Ω–∞–∫–∞: ¬´—Ç—ã –º–æ–∂–µ—à—å —Å–æ–∑–¥–∞—Ç—å –≤–∏–¥–µ–æ ...¬ª.
    # –¢–∞–∫–æ–π –∑–∞–ø—Ä–æ—Å –Ω–µ –¥–æ–ª–∂–µ–Ω —É—Ö–æ–¥–∏—Ç—å –≤ –æ–±—â–∏–π GPT-—á–∞—Ç, –≥–¥–µ –º–æ–¥–µ–ª—å –º–æ–∂–µ—Ç –æ—Ç–≤–µ—Ç–∏—Ç—å –æ—Ç–∫–∞–∑–æ–º.
    if (
        re.search(r"(–≤–∏–¥–µ–æ|—Ä–æ–ª–∏–∫|–∫–ª–∏–ø|reels?|shorts?|video|clip)", tl, re.I)
        and re.search(r"(—Ç—ã\s+)?(–º–æ–∂(–µ—à—å|–µ—Ç–µ|–Ω–æ)|—É–º–µ(–µ—à—å|–µ—Ç–µ)|—Å–ø–æ—Å–æ–±–µ–Ω|–ø–æ–¥–¥–µ—Ä–∂–∏–≤–∞–µ—à—å|–¥–µ–ª–∞–µ—à—å|—Å–æ–∑–¥–∞[–µ—ë]—à—å|–º–æ–∂–µ—Ç\s+–ª–∏|–º–æ–∂–Ω–æ\s+–ª–∏|–ø–æ–ª—É—á–∏—Ç—Å—è\s+–ª–∏)", tl, re.I)
    ):
        return (
            "–î–∞, –º–æ–≥—É —Å–æ–∑–¥–∞–≤–∞—Ç—å –∫–æ—Ä–æ—Ç–∫–∏–π –≤–∏–¥–µ–æ–∫–æ–Ω—Ç–µ–Ω—Ç –ø–æ —Ç–µ–∫—Å—Ç—É –∏–ª–∏ –≥–æ–ª–æ—Å–æ–≤–æ–º—É –∑–∞–ø—Ä–æ—Å—É. "
            "–ù–∞–ø–∏—à–∏—Ç–µ –∏–ª–∏ —Å–∫–∞–∂–∏—Ç–µ –∫–æ–º–∞–Ω–¥–æ–π: ¬´—Å–æ–∑–¥–∞–π –≤–∏–¥–µ–æ: –º–µ–¥–≤–µ–¥—å –ª–µ—Ç–∏—Ç –Ω–∞ –≤–æ–∑–¥—É—à–Ω–æ–º —à–∞—Ä–µ, 5 —Å–µ–∫—É–Ω–¥, 16:9¬ª. "
            "–ü–æ—Å–ª–µ —ç—Ç–æ–≥–æ —è –ø–æ–∫–∞–∂—É –≤—ã–±–æ—Ä –¥–≤–∏–∂–∫–∞: Sora 2 –±–µ–∑ –ª—é–¥–µ–π, Kling –∏–ª–∏ Runway. "
            "Luma —Å–µ–π—á–∞—Å –≤—Ä–µ–º–µ–Ω–Ω–æ —Å–∫—Ä—ã—Ç–∞ –∏ –Ω–µ –∏—Å–ø–æ–ª—å–∑—É–µ—Ç—Å—è."
        )

    # --- –ö–∞—Ä—Ç–∏–Ω–∫–∏ / –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è ---
    if re.search(r"(–∫–∞—Ä—Ç–∏–Ω–∫|–∏–∑–æ–±—Ä–∞–∂–µ–Ω|—Ñ–æ—Ç–æ|—Ñ–æ—Ç–æ–≥—Ä–∞—Ñ|image|picture|–ª–æ–≥–æ—Ç–∏–ø|–±–∞–Ω–Ω–µ—Ä)", tl) and "?" in tl:
        return (
            "–î–∞, –º–æ–≥—É —Ä–∞–±–æ—Ç–∞—Ç—å —Å –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è–º–∏: –∞–Ω–∞–ª–∏–∑–∏—Ä–æ–≤–∞—Ç—å —Ñ–æ—Ç–æ, —É–¥–∞–ª—è—Ç—å/–∑–∞–º–µ–Ω—è—Ç—å —Ñ–æ–Ω, —Ä–∞—Å—à–∏—Ä—è—Ç—å –∫–∞–¥—Ä, "
            "–¥–µ–ª–∞—Ç—å —Ä–µ—Ç—É—à—å —Å–æ–±—Å—Ç–≤–µ–Ω–Ω—ã—Ö –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–π, —É–±–∏—Ä–∞—Ç—å –ª–∏—à–Ω–∏–µ –Ω–∞–¥–ø–∏—Å–∏/–æ–±—ä–µ–∫—Ç—ã, "
            "—Å–æ–∑–¥–∞–≤–∞—Ç—å –ª–æ–≥–æ—Ç–∏–ø—ã/–∫–∞—Ä—Ç–∏–Ω–∫–∏ –ø–æ –æ–ø–∏—Å–∞–Ω–∏—é –∏ –æ–∂–∏–≤–ª—è—Ç—å —Ñ–æ—Ç–æ –≤ –∫–æ—Ä–æ—Ç–∫–æ–µ –≤–∏–¥–µ–æ. "
            "–ó–∞–≥—Ä—É–∑–∏—Ç–µ —Ñ–æ—Ç–æ ‚Äî –ø–æ—è–≤—è—Ç—Å—è –±—ã—Å—Ç—Ä—ã–µ –∫–Ω–æ–ø–∫–∏ –¥–µ–π—Å—Ç–≤–∏–π."
        )

    # –ù–∏—á–µ–≥–æ –ø–æ–¥—Ö–æ–¥—è—â–µ–≥–æ ‚Äî –ø—É—Å—Ç—å –¥–∞–ª—å—à–µ –æ–±—Ä–∞–±–∞—Ç—ã–≤–∞–µ—Ç—Å—è –æ–±—ã—á–Ω–æ–π –ª–æ–≥–∏–∫–æ–π
    return None


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ú–æ–¥—ã/–¥–≤–∏–∂–∫–∏ –¥–ª—è study ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
def _uk(user_id: int, name: str) -> str: return f"user:{user_id}:{name}"
def mode_set(user_id: int, mode: str):     kv_set(_uk(user_id, "mode"), (mode or "default"))
def mode_get(user_id: int) -> str:         return kv_get(_uk(user_id, "mode"), "default") or "default"
def engine_set(user_id: int, engine: str): kv_set(_uk(user_id, "engine"), (engine or "gpt"))
def engine_get(user_id: int) -> str:       return kv_get(_uk(user_id, "engine"), "gpt") or "gpt"
def study_sub_set(user_id: int, sub: str): kv_set(_uk(user_id, "study_sub"), (sub or "explain"))
def study_sub_get(user_id: int) -> str:    return kv_get(_uk(user_id, "study_sub"), "explain") or "explain"

def modes_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("üéì –£—á—ë–±–∞", callback_data="mode:set:study"),
         InlineKeyboardButton("üñº –§–æ—Ç–æ",  callback_data="mode:set:photo")],
        [InlineKeyboardButton("üìÑ –î–æ–∫—É–º–µ–Ω—Ç—ã", callback_data="mode:set:docs"),
         InlineKeyboardButton("üéô –ì–æ–ª–æ—Å",     callback_data="mode:set:voice")],
        [InlineKeyboardButton("üß† –î–≤–∏–∂–∫–∏", callback_data="mode:engines")]
    ])

def study_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("üîç –û–±—ä—è—Å–Ω–µ–Ω–∏–µ",          callback_data="study:set:explain"),
         InlineKeyboardButton("üßÆ –ó–∞–¥–∞—á–∏",              callback_data="study:set:tasks")],
        [InlineKeyboardButton("‚úçÔ∏è –≠—Å—Å–µ / —Ä–µ—Ñ–µ—Ä–∞—Ç", callback_data="study:set:essay")],
        [InlineKeyboardButton("üìù –≠–∫–∑–∞–º–µ–Ω/–∫–≤–∏–∑",        callback_data="study:set:quiz")]
    ])

async def study_process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    sub = study_sub_get(update.effective_user.id)
    if sub == "explain":
        prompt = f"–û–±—ä—è—Å–Ω–∏ –ø—Ä–æ—Å—Ç—ã–º–∏ —Å–ª–æ–≤–∞–º–∏, —Å 2‚Äì3 –ø—Ä–∏–º–µ—Ä–∞–º–∏ –∏ –º–∏–Ω–∏-–∏—Ç–æ–≥–æ–º:\n\n{text}"
    elif sub == "tasks":
        prompt = ("–†–µ—à–∏ –∑–∞–¥–∞—á—É(–∏) –ø–æ—à–∞–≥–æ–≤–æ: —Ñ–æ—Ä–º—É–ª—ã, –ø–æ—è—Å–Ω–µ–Ω–∏—è, –∏—Ç–æ–≥–æ–≤—ã–π –æ—Ç–≤–µ—Ç. "
                  "–ï—Å–ª–∏ –Ω–µ —Ö–≤–∞—Ç–∞–µ—Ç –¥–∞–Ω–Ω—ã—Ö ‚Äî —É—Ç–æ—á–Ω—è—é—â–∏–µ –≤–æ–ø—Ä–æ—Å—ã –≤ –∫–æ–Ω—Ü–µ.\n\n" + text)
    elif sub == "essay":
        prompt = ("–ù–∞–ø–∏—à–∏ —Å—Ç—Ä—É–∫—Ç—É—Ä–∏—Ä–æ–≤–∞–Ω–Ω—ã–π —Ç–µ–∫—Å—Ç 400‚Äì600 —Å–ª–æ–≤ (—ç—Å—Å–µ/—Ä–µ—Ñ–µ—Ä–∞—Ç/–¥–æ–∫–ª–∞–¥): "
                  "–≤–≤–µ–¥–µ–Ω–∏–µ, 3‚Äì5 —Ç–µ–∑–∏—Å–æ–≤ —Å —Ñ–∞–∫—Ç–∞–º–∏, –≤—ã–≤–æ–¥, —Å–ø–∏—Å–æ–∫ –∏–∑ 3 –∏—Å—Ç–æ—á–Ω–∏–∫–æ–≤ (–µ—Å–ª–∏ —É–º–µ—Å—Ç–Ω–æ).\n\n–¢–µ–º–∞:\n" + text)
    elif sub == "quiz":
        prompt = ("–°–æ—Å—Ç–∞–≤—å –º–∏–Ω–∏-–∫–≤–∏–∑ –ø–æ —Ç–µ–º–µ: 10 –≤–æ–ø—Ä–æ—Å–æ–≤, —É –∫–∞–∂–¥–æ–≥–æ 4 –≤–∞—Ä–∏–∞–Ω—Ç–∞ A‚ÄìD; "
                  "–≤ –∫–æ–Ω—Ü–µ –¥–∞–π –∫–ª—é—á –æ—Ç–≤–µ—Ç–æ–≤ (–Ω–æ–º–µ—Ä‚Üí–±—É–∫–≤–∞). –¢–µ–º–∞:\n\n" + text)
    else:
        prompt = text
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id if update.effective_chat else 0
    ans = await ask_openai_text(prompt, user_id=user_id, chat_id=chat_id)
    await update.effective_message.reply_text(ans)
    _chat_memory_add(user_id, chat_id, "user", text)
    _chat_memory_add(user_id, chat_id, "assistant", ans)
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ö–Ω–æ–ø–∫–∞ –ø—Ä–∏–≤–µ—Ç—Å—Ç–≤–µ–Ω–Ω–æ–π –∫–∞—Ä—Ç–∏–Ω–∫–∏ ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
async def cmd_set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("–ö–æ–º–∞–Ω–¥–∞ –¥–æ—Å—Ç—É–ø–Ω–∞ —Ç–æ–ª—å–∫–æ –≤–ª–∞–¥–µ–ª—å—Ü—É.")
        return
    if not context.args:
        await update.effective_message.reply_text("–§–æ—Ä–º–∞—Ç: /set_welcome <url_–∫–∞—Ä—Ç–∏–Ω–∫–∏>")
        return
    url = " ".join(context.args).strip()
    kv_set("welcome_url", url)
    await update.effective_message.reply_text("–ö–∞—Ä—Ç–∏–Ω–∫–∞ –ø—Ä–∏–≤–µ—Ç—Å—Ç–≤–∏—è –æ–±–Ω–æ–≤–ª–µ–Ω–∞. –û—Ç–ø—Ä–∞–≤—å—Ç–µ /start –¥–ª—è –ø—Ä–æ–≤–µ—Ä–∫–∏.")

async def cmd_show_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = kv_get("welcome_url", BANNER_URL)
    if url:
        await update.effective_message.reply_photo(url, caption="–¢–µ–∫—É—â–∞—è –∫–∞—Ä—Ç–∏–Ω–∫–∞ –ø—Ä–∏–≤–µ—Ç—Å—Ç–≤–∏—è")
    else:
        await update.effective_message.reply_text("–ö–∞—Ä—Ç–∏–Ω–∫–∞ –ø—Ä–∏–≤–µ—Ç—Å—Ç–≤–∏—è –Ω–µ –∑–∞–¥–∞–Ω–∞.")



# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ö–æ–º–º–µ—Ä—á–µ—Å–∫–∏–π –ø—Ä–∞–π—Å ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
def _pricing_catalog_text() -> str:
    lines = [
        "üí∞ –¶–µ–Ω—ã –ø–ª–∞—Ç–Ω—ã—Ö –≥–µ–Ω–µ—Ä–∞—Ü–∏–π",
        "–í—Å–µ —Ü–µ–Ω—ã —É–∂–µ –≤–∫–ª—é—á–∞—é—Ç —Å–µ—Ä–≤–∏—Å–Ω—É—é –º–∞—Ä–∂—É –∏ –æ–∫—Ä—É–≥–ª–µ–Ω—ã –¥–æ 5 –∫—Ä–µ–¥–∏—Ç–æ–≤.",
        "1 –∫—Ä–µ–¥–∏—Ç = 1 ‚ÇΩ; —Å–ø–∏—Å–∞–Ω–∏–µ ‚Äî —Ç–æ–ª—å–∫–æ –ø–æ—Å–ª–µ —É—Å–ø–µ—à–Ω–æ–≥–æ —Ä–µ–∑—É–ª—å—Ç–∞—Ç–∞.",
        "",
        "üñº –ò–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è",
        f"‚Ä¢ OpenAI Images, 1024√ó1024 medium ‚Äî {_retail_credits(IMG_COST_USD)} –∫—Ä.",
        f"‚Ä¢ Midjourney Fast ‚Äî {_retail_credits(MIDJOURNEY_UNIT_COST_USD)} –∫—Ä.",
        f"‚Ä¢ –û–±—Ä–∞–±–æ—Ç–∫–∞/—Ä–µ—Ç—É—à—å/—Ñ–æ–Ω ‚Äî –æ—Ç {_retail_credits(IMG_PROCESS_COST_USD)} –∫—Ä.",
        f"‚Ä¢ AI-—Å–µ–ª—Ñ–∏ ‚Äî {_retail_credits(AI_SELFIE_UNIT_COST_USD)} –∫—Ä.",
        "",
        "üé¨ –í–∏–¥–µ–æ",
        f"‚Ä¢ Sora 2 –±–µ–∑ –ª—é–¥–µ–π, 5 —Å–µ–∫ ‚Äî {_video_price_credits('sora', 5)} –∫—Ä.; 10 —Å–µ–∫ ‚Äî {_video_price_credits('sora', 10)} –∫—Ä.",
        f"‚Ä¢ Kling, 5 —Å–µ–∫ ‚Äî {_video_price_credits('kling', 5)} –∫—Ä.; 10 —Å–µ–∫ ‚Äî {_video_price_credits('kling', 10)} –∫—Ä.",
        f"‚Ä¢ Runway Gen-4.5, 5 —Å–µ–∫ ‚Äî {_video_price_credits('runway', 5)} –∫—Ä.; 10 —Å–µ–∫ ‚Äî {_video_price_credits('runway', 10)} –∫—Ä.",
        "",
        "üéµ –ü—Ä–æ–¥–∞–∫—à–Ω-—Ñ—É–Ω–∫—Ü–∏–∏",
        f"‚Ä¢ Suno –º—É–∑—ã–∫–∞ ‚Äî {_retail_credits(SUNO_COST_USD)} –∫—Ä.",
        f"‚Ä¢ –ì–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä ‚Äî {_retail_credits(AVATAR_UNIT_COST_USD)} –∫—Ä.",
        f"‚Ä¢ –§–æ—Ç–æ ‚Üí –≤–∏–¥–µ–æ–∫–ª–∏–ø —Å –º—É–∑—ã–∫–æ–π ‚Äî {_retail_credits(PHOTO_CLIP_UNIT_COST_USD)} –∫—Ä.",
        f"‚Ä¢ –ö–ª–∏–ø —Å –≤–æ–∫–∞–ª–æ–º / lip-sync, –¥–æ 10 —Å–µ–∫ (1 —Å—Ü–µ–Ω–∞) ‚Äî {_retail_credits(VOCAL_CLIP_UNIT_COST_USD)} –∫—Ä.",
        "",
        "üé≠ –ë–∏–∑–Ω–µ—Å –∏ —Ñ–æ—Ç–æ",
        f"‚Ä¢ FaceSwap –±—ã—Å—Ç—Ä–æ ‚Äî {_retail_credits(FACESWAP_FAST_COST_USD)} –∫—Ä.; –ø—Ä–µ–º–∏—É–º ‚Äî {_retail_credits(FACESWAP_PREMIUM_COST_USD)} –∫—Ä.",
        f"‚Ä¢ –°–±–æ—Ä–∫–∞ –ø—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏–∏ PDF + PPTX ‚Äî {_retail_credits(PRESENTATION_RENDER_COST_USD)} –∫—Ä. + –≤—ã–±—Ä–∞–Ω–Ω—ã–µ AI-–∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏—è.",
        "",
        "–§–∏–Ω–∞–ª—å–Ω–∞—è —Ü–µ–Ω–∞ –≤—Å–µ–≥–¥–∞ –ø–æ–∫–∞–∑—ã–≤–∞–µ—Ç—Å—è –¥–æ –∑–∞–ø—É—Å–∫–∞ –∑–∞–¥–∞—á–∏.",
    ]
    return "\n".join(lines)

async def cmd_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        _pricing_catalog_text(),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("‚ûï –ü–æ–ø–æ–ª–Ω–∏—Ç—å –±–∞–ª–∞–Ω—Å", callback_data="topup")]]),
    )

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ë–∞–ª–∞–Ω—Å / –ø–æ–ø–æ–ª–Ω–µ–Ω–∏–µ ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    w = _wallet_get(user_id)
    total = _wallet_total_get(user_id)
    row = _usage_row(user_id)
    lim = _limits_for(user_id)
    credits = int(round(_usd_to_credits(total)))
    reserved = int(round(_usd_to_credits(_wallet_reserved_total_get(user_id))))
    available = max(0, credits - reserved)
    msg = (
        "üßæ –ö—Ä–µ–¥–∏—Ç–Ω—ã–π –±–∞–ª–∞–Ω—Å:\n"
        f"‚Ä¢ –í—Å–µ–≥–æ: {credits} –∫—Ä.\n"
        f"‚Ä¢ –î–æ—Å—Ç—É–ø–Ω–æ: {available} –∫—Ä.\n"
        + (f"‚Ä¢ –ó–∞—Ä–µ–∑–µ—Ä–≤–∏—Ä–æ–≤–∞–Ω–æ –∞–∫—Ç–∏–≤–Ω—ã–º–∏ –∑–∞–¥–∞—á–∞–º–∏: {reserved} –∫—Ä.\n" if reserved else "")
        + "\n1 –∫—Ä–µ–¥–∏—Ç = 1 ‚ÇΩ. –¶–µ–Ω–∞ –∫–∞–∂–¥–æ–π –ø–ª–∞—Ç–Ω–æ–π –≥–µ–Ω–µ—Ä–∞—Ü–∏–∏ —É–∂–µ –≤–∫–ª—é—á–∞–µ—Ç –º–∞—Ä–∂—É —Å–µ—Ä–≤–∏—Å–∞; —Å–ø–∏—Å–∞–Ω–∏–µ –ø—Ä–æ–∏—Å—Ö–æ–¥–∏—Ç —Ç–æ–ª—å–∫–æ –ø–æ—Å–ª–µ —É—Å–ø–µ—à–Ω–æ–≥–æ —Ä–µ–∑—É–ª—å—Ç–∞—Ç–∞.\n\n"
        "–ê–∫—Ç—É–∞–ª—å–Ω—ã–π –ø—Ä–∞–π—Å: /prices\n\n"
        "–õ–∏–º–∏—Ç—ã —Å–µ–≥–æ–¥–Ω—è:\n"
        f"‚Ä¢ –¢–µ–∫—Å—Ç: {row['text_count']} / {lim['text_per_day']}\n"
        f"‚Ä¢ –ë–µ—Å–ø–ª–∞—Ç–Ω–∞—è –≥–µ–Ω–µ—Ä–∞—Ü–∏—è –∫–∞—Ä—Ç–∏–Ω–æ–∫: {row['free_img_gen_count']} / {FREE_IMAGE_GENERATIONS_PER_DAY}\n"
        f"‚Ä¢ –ë–µ—Å–ø–ª–∞—Ç–Ω–∞—è –æ–±—Ä–∞–±–æ—Ç–∫–∞ —Ñ–æ—Ç–æ: {row['free_img_proc_count']} / {FREE_IMAGE_PROCESSINGS_PER_DAY}\n"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("‚ûï –ü–æ–ø–æ–ª–Ω–∏—Ç—å –±–∞–ª–∞–Ω—Å", callback_data="topup"), InlineKeyboardButton("üí∞ –¶–µ–Ω—ã", callback_data="pricing:list")]])
    await update.effective_message.reply_text(msg, reply_markup=kb)

# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ü–æ–¥–ø–∏—Å–∫–∞ / —Ç–∞—Ä–∏—Ñ—ã ‚Äî UI –∏ –æ–ø–ª–∞—Ç—ã (PATCH) ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
# –ó–∞–≤–∏—Å–∏–º–æ—Å—Ç–∏ –æ–∫—Ä—É–∂–µ–Ω–∏—è:
#  - YOOKASSA_PROVIDER_TOKEN  (–ø–ª–∞—Ç—ë–∂–Ω—ã–π —Ç–æ–∫–µ–Ω Telegram Payments –æ—Ç –ÆKassa)
#  - YOOKASSA_CURRENCY        (–ø–æ —É–º–æ–ª—á–∞–Ω–∏—é "RUB")
#  - CRYPTO_PAY_API_TOKEN     (https://pay.crypt.bot ‚Äî —Ç–æ–∫–µ–Ω –ø—Ä–æ–¥–∞–≤—Ü–∞)
#  - CRYPTO_ASSET             (–Ω–∞–ø—Ä–∏–º–µ—Ä "USDT", –ø–æ —É–º–æ–ª—á–∞–Ω–∏—é "USDT")
#  - PRICE_START_RUB, PRICE_PRO_RUB, PRICE_ULT_RUB  (—Ü–µ–ª–æ–µ —á–∏—Å–ª–æ, ‚ÇΩ)
#  - PRICE_START_USD, PRICE_PRO_USD, PRICE_ULT_USD  (—á–∏—Å–ª–æ —Å —Ç–æ—á–∫–æ–π, $)
#
# –•—Ä–∞–Ω–∏–ª–∏—â–µ –ø–æ–¥–ø–∏—Å–∫–∏ –∏ –∫–æ—à–µ–ª—å–∫–∞ –∏—Å–ø–æ–ª—å–∑—É–µ—Ç—Å—è –Ω–∞ kv_*:
#   sub:tier:{user_id}   -> "start" | "pro" | "ultimate"
#   sub:until:{user_id}  -> ISO-—Å—Ç—Ä–æ–∫–∞ –¥–∞—Ç—ã –æ–∫–æ–Ω—á–∞–Ω–∏—è
#   wallet:usd:{user_id} -> –±–∞–ª–∞–Ω—Å –≤ USD (float)

YOOKASSA_PROVIDER_TOKEN = os.environ.get("YOOKASSA_PROVIDER_TOKEN", "").strip()
YOOKASSA_CURRENCY = (os.environ.get("YOOKASSA_CURRENCY") or "RUB").upper()

# v80: –ø—Ä—è–º—ã–µ –ø–ª–∞—Ç–µ–∂–∏ –ÆKassa –ø–æ —Å—Å—ã–ª–∫–µ/QR/–±–∞–Ω–∫–æ–≤—Å–∫–∏–º –ø—Ä–∏–ª–æ–∂–µ–Ω–∏—è–º.
# –≠—Ç–æ –ù–ï Telegram Payments invoice, –∞ API –ÆKassa /v3/payments + polling —Å—Ç–∞—Ç—É—Å–∞.
#
# Render –Ω–∞ –º–æ–±–∏–ª—å–Ω–æ–º –∏–Ω–æ–≥–¥–∞ –Ω–µ –¥–∞—ë—Ç –¥–æ–±–∞–≤–∏—Ç—å –Ω–æ–≤—ã–µ ENV. –ü–æ—ç—Ç–æ–º—É –∫–ª—é—á–∏ –ÆKassa –º–æ–∂–Ω–æ
# –ø–µ—Ä–µ–¥–∞—Ç—å —Ç—Ä–µ–º—è –ø—É—Ç—è–º–∏, –≤ –ø–æ—Ä—è–¥–∫–µ –ø—Ä–∏–æ—Ä–∏—Ç–µ—Ç–∞:
# 1) ENV: YOO_SHOP_ID/YOO_SECRET_KEY –∏–ª–∏ YOOKASSA_SHOP_ID/YOOKASSA_SECRET_KEY
# 2) –∫–æ—Ä–æ—Ç–∫–∏–µ ENV: YK_ID/YK_KEY
# 3) Render Secret File: /etc/secrets/yookassa.env —Å —Å–æ–¥–µ—Ä–∂–∏–º—ã–º:
#    YK_ID=1185809
#    YK_KEY=—Å–µ–∫—Ä–µ—Ç–Ω—ã–π_–∫–ª—é—á
def _read_simple_secret_file(path: str) -> dict:
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f.read().splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return data

_YOO_SECRET_FILE_VALUES = {}
for _p in (
    "/etc/secrets/yookassa.env",
    "/etc/secrets/yookassa.txt",
    "/etc/secrets/yk.env",
    "/etc/secrets/yk.txt",
):
    _YOO_SECRET_FILE_VALUES.update(_read_simple_secret_file(_p))

def _secret_value(*names: str) -> str:
    for name in names:
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    for name in names:
        val = (_YOO_SECRET_FILE_VALUES.get(name) or "").strip()
        if val:
            return val
    return ""

YOO_SHOP_ID = _secret_value("YOO_SHOP_ID", "YOOKASSA_SHOP_ID", "YK_ID", "PAY_ID")
YOO_SECRET_KEY = _secret_value("YOO_SECRET_KEY", "YOOKASSA_SECRET_KEY", "YK_KEY", "PAY_KEY")
YOO_DIRECT_ENABLED = os.environ.get("YOO_DIRECT_ENABLED", "1").lower() in ("1", "true", "yes", "on")
YOO_PAYMENT_RETURN_URL = os.environ.get("YOO_PAYMENT_RETURN_URL", "").strip() or f"{PUBLIC_URL.rstrip('/')}/payment_return"
YOO_SBP_ENABLED = os.environ.get("YOO_SBP_ENABLED", "1").lower() in ("1", "true", "yes", "on")
YOO_SBERPAY_ENABLED = os.environ.get("YOO_SBERPAY_ENABLED", "1").lower() in ("1", "true", "yes", "on")
YOO_TPAY_ENABLED = os.environ.get("YOO_TPAY_ENABLED", "1").lower() in ("1", "true", "yes", "on")
YOO_MIRPAY_ENABLED = os.environ.get("YOO_MIRPAY_ENABLED", "1").lower() in ("1", "true", "yes", "on")
YOO_CARD_ENABLED = os.environ.get("YOO_CARD_ENABLED", "1").lower() in ("1", "true", "yes", "on")
YOO_PAYMENT_POLL_SECONDS = int(os.environ.get("YOO_PAYMENT_POLL_SECONDS", "900") or 900)
YOO_PAYMENT_POLL_INTERVAL_S = float(os.environ.get("YOO_PAYMENT_POLL_INTERVAL_S", "5") or 5)
YOO_DEFAULT_METHOD = (os.environ.get("YOO_DEFAULT_METHOD", "sbp") or "sbp").strip().lower()
# –ï—Å–ª–∏ –≤ –ÆKassa –≤–∫–ª—é—á–µ–Ω–∞ –æ–Ω–ª–∞–π–Ω-–∫–∞—Å—Å–∞/–∞–≤—Ç–æ–æ—Ç–ø—Ä–∞–≤–∫–∞ —á–µ–∫–æ–≤, API –º–æ–∂–µ—Ç —Ç—Ä–µ–±–æ–≤–∞—Ç—å receipt.
# –≠—Ç–∏ –∑–Ω–∞—á–µ–Ω–∏—è –º–æ–∂–Ω–æ –ø–æ–ª–æ–∂–∏—Ç—å –≤ Render Secret File yookassa.env –±–µ–∑ –¥–æ–±–∞–≤–ª–µ–Ω–∏—è ENV-–ø–µ—Ä–µ–º–µ–Ω–Ω—ã—Ö:
# YK_RECEIPT_EMAIL=owner@example.com
# YK_VAT_CODE=1
YOO_RECEIPT_EMAIL = _secret_value("YOO_RECEIPT_EMAIL", "YOOKASSA_RECEIPT_EMAIL", "YK_RECEIPT_EMAIL", "PAY_RECEIPT_EMAIL")
YOO_VAT_CODE = int((_secret_value("YOO_VAT_CODE", "YK_VAT_CODE") or os.environ.get("YOO_VAT_CODE") or "1").strip() or 1)
YOO_DEBUG_PAY_ERRORS = os.environ.get("YOO_DEBUG_PAY_ERRORS", "1").lower() in ("1", "true", "yes", "on")

CRYPTO_PAY_API_TOKEN = os.environ.get("CRYPTO_PAY_API_TOKEN", "").strip()
CRYPTO_ASSET = (os.environ.get("CRYPTO_ASSET") or "USDT").upper()

# === COMPAT with existing vars/DB in your main.py ===
# 1) –ÆKassa: –µ—Å–ª–∏ —É–∂–µ –µ—Å—Ç—å PROVIDER_TOKEN (–∏–∑ PROVIDER_TOKEN_YOOKASSA), –∏—Å–ø–æ–ª—å–∑—É–µ–º –µ–≥–æ:
if not YOOKASSA_PROVIDER_TOKEN and 'PROVIDER_TOKEN' in globals() and PROVIDER_TOKEN:
    YOOKASSA_PROVIDER_TOKEN = PROVIDER_TOKEN

# 2) –ö–æ—à–µ–ª—ë–∫: –∏—Å–ø–æ–ª—å–∑—É–µ–º —Ç–≤–æ–π –µ–¥–∏–Ω—ã–π USD-–∫–æ—à–µ–ª—ë–∫ (wallet table) –≤–º–µ—Å—Ç–æ kv:
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

# 3) –ü–æ–¥–ø–∏—Å–∫–∞: –∞–∫—Ç–∏–≤–∏—Ä—É–µ–º —á–µ—Ä–µ–∑ —Ç–≤–æ–∏ —Ñ—É–Ω–∫—Ü–∏–∏ —Å –ë–î, –∞ –Ω–µ kv:
def _sub_activate(user_id: int, tier_key: str, months: int = 1) -> str:
    dt = activate_subscription_with_tier(user_id, tier_key, months)
    return dt.isoformat()

def _sub_info_text(user_id: int) -> str:
    tier = get_subscription_tier(user_id)
    dt = get_subscription_until(user_id)
    human_until = dt.strftime("%d.%m.%Y") if dt else ""
    bal = _user_balance_get(user_id)
    line_until = f"\n‚è≥ –ê–∫—Ç–∏–≤–Ω–∞ –¥–æ: {human_until}" if tier != "free" and human_until else ""
    return f"üßæ –¢–µ–∫—É—â–∞—è –ø–æ–¥–ø–∏—Å–∫–∞: {tier.upper() if tier!='free' else '–Ω–µ—Ç'}{line_until}\nü™ô –ë–∞–ª–∞–Ω—Å: {_credits_fmt_from_usd(bal)}"

# –¶–µ–Ω—ã ‚Äî –∏–∑ env —Å –æ—Å–º—ã—Å–ª–µ–Ω–Ω—ã–º–∏ –¥–µ—Ñ–æ–ª—Ç–∞–º–∏
PRICE_START_RUB = int(os.environ.get("PRICE_START_RUB", "599"))
PRICE_PRO_RUB = int(os.environ.get("PRICE_PRO_RUB", "1990"))
PRICE_ULT_RUB = int(os.environ.get("PRICE_ULT_RUB", "4990"))

PRICE_START_USD = _env_float("PRICE_START_USD", 5.99)
PRICE_PRO_USD   = _env_float("PRICE_PRO_USD", 19.90)
PRICE_ULT_USD   = _env_float("PRICE_ULT_USD", 49.90)

SUBS_TIERS = {
    "start": {
        "title": "START",
        "rub": PRICE_START_RUB,
        "usd": PRICE_START_USD,
        "credits": SUBSCRIPTION_CREDITS.get("start", 200),
        "features": [
            "üí¨ GPT-—á–∞—Ç, –¥–æ–∫—É–º–µ–Ω—Ç—ã –∏ –ø–µ—Ä–µ–≤–æ–¥—á–∏–∫",
            "üéß –û–∑–≤—É—á–∫–∞ –æ—Ç–≤–µ—Ç–æ–≤ –∏ —Ä–∞—Å–ø–æ–∑–Ω–∞–≤–∞–Ω–∏–µ —Ä–µ—á–∏",
            "üñº –§–æ—Ç–æ-–º–∞—Å—Ç–µ—Ä—Å–∫–∞—è, –∫–∞—Ä—Ç–∏–Ω–∫–∏ –∏ AI-—Ñ—É–Ω–∫—Ü–∏–∏ ‚Äî —á–µ—Ä–µ–∑ –∫—Ä–µ–¥–∏—Ç—ã",
            "üé¨ –í–∏–¥–µ–æ, –º—É–∑—ã–∫–∞ –∏ –∞–≤–∞—Ç–∞—Ä—ã –º–æ–∂–Ω–æ –∑–∞–ø—É—Å–∫–∞—Ç—å —á–µ—Ä–µ–∑ –∫—Ä–µ–¥–∏—Ç—ã",
            "‚öôÔ∏è –û–±—ã—á–Ω–∞—è –æ—á–µ—Ä–µ–¥—å",
            f"ü™ô {SUBSCRIPTION_CREDITS.get('start', 200)} –∫—Ä–µ–¥–∏—Ç–æ–≤ –∫–∞–∂–¥—ã–π –º–µ—Å—è—Ü",
        ],
    },
    "pro": {
        "title": "PRO",
        "rub": PRICE_PRO_RUB,
        "usd": PRICE_PRO_USD,
        "credits": SUBSCRIPTION_CREDITS.get("pro", 1200),
        "features": [
            "üí¨ –ü–æ–≤—ã—à–µ–Ω–Ω—ã–µ GPT-–ª–∏–º–∏—Ç—ã",
            "üìö –ì–ª—É–±–æ–∫–∏–π —Ä–∞–∑–±–æ—Ä PDF/DOCX/EPUB",
            "üé¨ Reels/Shorts, —Ñ–æ—Ç–æ‚Üí–≤–∏–¥–µ–æ, Suno, AI-—Ñ–æ—Ç–æ ‚Äî —á–µ—Ä–µ–∑ –∫—Ä–µ–¥–∏—Ç—ã",
            "üñº Outpaint, —Ñ–æ–Ω, FaceSwap, AI-—Å–µ–ª—Ñ–∏",
            "üé§ –ì–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä –∏ –∫–ª–∏–ø —Å –≤–æ–∫–∞–ª–æ–º –¥–æ—Å—Ç—É–ø–Ω—ã —á–µ—Ä–µ–∑ –∫—Ä–µ–¥–∏—Ç—ã",
            "‚ö° –£—Å–∫–æ—Ä–µ–Ω–Ω–∞—è –æ—á–µ—Ä–µ–¥—å",
            f"ü™ô {SUBSCRIPTION_CREDITS.get('pro', 1200)} –∫—Ä–µ–¥–∏—Ç–æ–≤ –∫–∞–∂–¥—ã–π –º–µ—Å—è—Ü",
        ],
    },
    "ultimate": {
        "title": "ULTIMATE",
        "rub": PRICE_ULT_RUB,
        "usd": PRICE_ULT_USD,
        "credits": SUBSCRIPTION_CREDITS.get("ultimate", 3500),
        "features": [
            "üí¨ –ú–∞–∫—Å–∏–º–∞–ª—å–Ω—ã–µ GPT-–ª–∏–º–∏—Ç—ã",
            "üöÄ –ë–æ–ª—å—à–µ –∫—Ä–µ–¥–∏—Ç–æ–≤ –¥–ª—è Runway / Kling / Sora 2 / Suno",
            "üé§ –ö–ª–∏–ø —Å –≤–æ–∫–∞–ª–æ–º, –≥–æ–≤–æ—Ä—è—â–∏–π –∞–≤–∞—Ç–∞—Ä, –≤–∏–¥–µ–æ –ø–æ —Ç–µ–∫—Å—Ç—É/–≥–æ–ª–æ—Å—É",
            "üé¨ –ë–æ–ª—å—à–µ –≤–∏–¥–µ–æ –∏ –ø—Ä–µ–º–∏—É–º-—Ä–µ–Ω–¥–µ—Ä–æ–≤",
            "üß† –ü—Ä–∏–æ—Ä–∏—Ç–µ—Ç–Ω–∞—è –æ—á–µ—Ä–µ–¥—å",
            "üõ† PRO-–∏–Ω—Å—Ç—Ä—É–º–µ–Ω—Ç—ã –∏ —Ä–∞—Å—à–∏—Ä–µ–Ω–Ω—ã–µ —Å—Ü–µ–Ω–∞—Ä–∏–∏",
            f"ü™ô {SUBSCRIPTION_CREDITS.get('ultimate', 3500)} –∫—Ä–µ–¥–∏—Ç–æ–≤ –∫–∞–∂–¥—ã–π –º–µ—Å—è—Ü",
        ],
    },
}

def _money_fmt_rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ‚ÇΩ"

def _money_fmt_usd(v: float) -> str:
    return f"${v:.2f}"

def _user_balance_get(user_id: int) -> float:
    return _wallet_total_get(user_id)

def _user_balance_add(user_id: int, delta: float) -> float:
    if delta >= 0:
        _wallet_total_add(user_id, delta)
    else:
        _wallet_total_take(user_id, -delta)
    return _wallet_total_get(user_id)

def _user_balance_debit(user_id: int, amount: float) -> bool:
    return _wallet_total_take(user_id, amount)

def _sub_activate(user_id: int, tier_key: str, months: int = 1) -> str:
    until_dt = activate_subscription_with_tier(user_id, tier_key, months)
    kv_set(f"sub:tier:{user_id}", tier_key)
    kv_set(f"sub:until:{user_id}", until_dt.isoformat())
    return until_dt.isoformat()

def _sub_info_text(user_id: int) -> str:
    tier = get_subscription_tier(user_id)
    until_dt = get_subscription_until(user_id)
    human_until = until_dt.strftime("%d.%m.%Y") if until_dt else ""
    bal = _user_balance_get(user_id)
    line_until = f"\n‚è≥ –ê–∫—Ç–∏–≤–Ω–∞ –¥–æ: {human_until}" if tier != "free" and human_until else ""
    title = tier.upper() if tier != "free" else "–Ω–µ—Ç"
    return f"üßæ –¢–µ–∫—É—â–∞—è –ø–æ–¥–ø–∏—Å–∫–∞: {title}{line_until}\nü™ô –ë–∞–ª–∞–Ω—Å: {_credits_fmt_from_usd(bal)}"

def _plan_card_text(key: str) -> str:
    p = SUBS_TIERS[key]
    fs = "\n".join("‚Ä¢ " + f for f in p["features"])
    return (
        f"‚≠ê –¢–∞—Ä–∏—Ñ {p['title']}\n"
        f"–¶–µ–Ω–∞: {_money_fmt_rub(p['rub'])} –≤ –º–µ—Å—è—Ü.\n"
        f"–í–∫–ª—é—á–µ–Ω–æ: {p.get('credits', 0)} –∫—Ä–µ–¥–∏—Ç–æ–≤ –Ω–∞ –ø–ª–∞—Ç–Ω—ã–µ —Ñ—É–Ω–∫—Ü–∏–∏.\n\n"
        f"{fs}\n"
    )

def _plans_overview_text(user_id: int) -> str:
    parts = [
        "‚≠ê –ü–æ–¥–ø–∏—Å–∫–∞ –∏ —Ç–∞—Ä–∏—Ñ—ã",
        "–í—Å–µ —Ç–∞—Ä–∏—Ñ—ã –æ—Ç–∫—Ä—ã–≤–∞—é—Ç –¥–æ—Å—Ç—É–ø –∫ AI-—Ñ—É–Ω–∫—Ü–∏—è–º Neyro-Bot GPT 5 Studio. 1 –∫—Ä–µ–¥–∏—Ç = 1 ‚ÇΩ. –¶–µ–Ω—ã –≥–µ–Ω–µ—Ä–∞—Ü–∏–π —É–∂–µ –≤–∫–ª—é—á–∞—é—Ç –º–∞—Ä–∂—É —Å–µ—Ä–≤–∏—Å–∞; –∫—Ä–µ–¥–∏—Ç—ã –æ–∫–æ–Ω—á–∞—Ç–µ–ª—å–Ω–æ —Å–ø–∏—Å—ã–≤–∞—é—Ç—Å—è —Ç–æ–ª—å–∫–æ –ø–æ—Å–ª–µ —É—Å–ø–µ—à–Ω–æ–π –≤—ã–¥–∞—á–∏ —Ä–µ–∑—É–ª—å—Ç–∞—Ç–∞. –ß–µ–º –≤—ã—à–µ —Ç–∞—Ä–∏—Ñ ‚Äî —Ç–µ–º –±–æ–ª—å—à–µ –∫—Ä–µ–¥–∏—Ç–æ–≤, –≤—ã—à–µ GPT-–ª–∏–º–∏—Ç—ã –∏ –±—ã—Å—Ç—Ä–µ–µ –æ—á–µ—Ä–µ–¥—å.",
        _sub_info_text(user_id),
        "‚Äî ‚Äî ‚Äî",
        _plan_card_text("start"),
        _plan_card_text("pro"),
        _plan_card_text("ultimate"),
        "–í—ã–±–µ—Ä–∏—Ç–µ —Ç–∞—Ä–∏—Ñ –∫–Ω–æ–ø–∫–æ–π –Ω–∏–∂–µ.",
    ]
    return "\n".join(parts)

def plans_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("‚≠ê START",    callback_data="plan:start"),
            InlineKeyboardButton("üöÄ PRO",      callback_data="plan:pro"),
            InlineKeyboardButton("üëë ULTIMATE", callback_data="plan:ultimate"),
        ],
        [InlineKeyboardButton("ü™ô –ö—É–ø–∏—Ç—å –∫—Ä–µ–¥–∏—Ç—ã", callback_data="topup")],
    ])

def plan_pay_kb(plan_key: str) -> InlineKeyboardMarkup:
    rows = []
    if YOO_SBP_ENABLED:
        rows.append([InlineKeyboardButton("‚ö° –°–ë–ü / QR", callback_data=f"pay:yoo_sbp:{plan_key}")])
    app_row = []
    if YOO_SBERPAY_ENABLED:
        app_row.append(InlineKeyboardButton("üü¢ SberPay", callback_data=f"pay:yoo_sberpay:{plan_key}"))
    if YOO_TPAY_ENABLED:
        app_row.append(InlineKeyboardButton("üü° T-Pay", callback_data=f"pay:yoo_tpay:{plan_key}"))
    if app_row:
        rows.append(app_row)
    app_row2 = []
    if YOO_MIRPAY_ENABLED:
        app_row2.append(InlineKeyboardButton("üíô Mir Pay", callback_data=f"pay:yoo_mirpay:{plan_key}"))
    if YOO_CARD_ENABLED:
        app_row2.append(InlineKeyboardButton("üí≥ –ö–∞—Ä—Ç–∞ Telegram", callback_data=f"pay:yookassa:{plan_key}"))
    if app_row2:
        rows.append(app_row2)
    rows.append([InlineKeyboardButton("üåê –í—Å–µ —Å–ø–æ—Å–æ–±—ã –ÆKassa", callback_data=f"pay:yoo_all:{plan_key}")])
    rows.append([InlineKeyboardButton("üí† CryptoBot", callback_data=f"pay:cryptobot:{plan_key}")])
    rows.append([InlineKeyboardButton("üßæ –° –±–∞–ª–∞–Ω—Å–∞", callback_data=f"pay:balance:{plan_key}")])
    rows.append([InlineKeyboardButton("‚¨ÖÔ∏è –ö —Ç–∞—Ä–∏—Ñ–∞–º", callback_data="plan:root")])
    return InlineKeyboardMarkup(rows)


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ÆKassa direct API: –°–ë–ü / QR, SberPay, T-Pay, Mir Pay ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
YOO_DIRECT_METHODS = {
    "yoo_sbp":      {"type": "sbp",          "confirmation": "redirect", "label": "‚ö° –°–ë–ü / QR"},
    "yoo_sberpay": {"type": "sberbank",     "confirmation": "redirect", "label": "üü¢ SberPay"},
    "yoo_tpay":    {"type": "tinkoff_bank", "confirmation": "redirect", "label": "üü° T-Pay"},
    # –í API –ÆKassa Mir Pay –ø—Ä–æ—Ö–æ–¥–∏—Ç –∫–∞–∫ bank_card; –Ω–∞ —Ñ–æ—Ä–º–µ/–º–æ–±. —É—Å—Ç—Ä–æ–π—Å—Ç–≤–µ –∏—Å—Ç–æ—á–Ω–∏–∫ –±—É–¥–µ—Ç mir_pay.
    "yoo_mirpay":  {"type": "bank_card",    "confirmation": "redirect", "label": "üíô Mir Pay"},
    # –£–Ω–∏–≤–µ—Ä—Å–∞–ª—å–Ω–∞—è —Å—Å—ã–ª–∫–∞ –ÆKassa: –±–µ–∑ –∂–µ—Å—Ç–∫–æ–≥–æ payment_method_data, —Ñ–æ—Ä–º–∞ –ø–æ–∫–∞–∂–µ—Ç –¥–æ—Å—Ç—É–ø–Ω—ã–µ –º–µ—Ç–æ–¥—ã –º–∞–≥–∞–∑–∏–Ω–∞.
    "yoo_all":     {"type": None,           "confirmation": "redirect", "label": "üåê –í—Å–µ —Å–ø–æ—Å–æ–±—ã –ÆKassa"},
}

def _yoo_direct_configured() -> bool:
    return bool(YOO_DIRECT_ENABLED and YOO_SHOP_ID and YOO_SECRET_KEY)

def _yoo_auth():
    return (YOO_SHOP_ID, YOO_SECRET_KEY)

async def _yoo_create_direct_payment(user_id: int, plan_key: str, months: int, method_key: str) -> dict:
    """–°–æ–∑–¥–∞—ë—Ç direct payment –≤ –ÆKassa –∏ –≤–æ–∑–≤—Ä–∞—â–∞–µ—Ç JSON –ø–ª–∞—Ç–µ–∂–∞."""
    plan = SUBS_TIERS[plan_key]
    method = YOO_DIRECT_METHODS[method_key]
    amount_rub = int(plan["rub"]) * max(1, int(months or 1))
    title = f"–ü–æ–¥–ø–∏—Å–∫–∞ {plan['title']} ‚Ä¢ {months} –º–µ—Å."
    confirmation_type = method.get("confirmation") or "redirect"
    payload = {
        "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
        "capture": True,
        "description": title,
        "metadata": {
            "kind": "subscription",
            "user_id": str(user_id),
            "tier": plan_key,
            "months": str(months),
            "credits": str(plan.get("credits", 0) * max(1, int(months or 1))),
            "method": method_key,
        },
        "confirmation": {"type": confirmation_type},
    }
    if method.get("type"):
        payload["payment_method_data"] = {"type": method["type"]}
    if confirmation_type in ("redirect", "external"):
        payload["confirmation"]["return_url"] = YOO_PAYMENT_RETURN_URL

    # –ï—Å–ª–∏ –º–∞–≥–∞–∑–∏–Ω —Ä–∞–±–æ—Ç–∞–µ—Ç —Å –æ–Ω–ª–∞–π–Ω-–∫–∞—Å—Å–æ–π, –ÆKassa –º–æ–∂–µ—Ç –Ω–µ —Å–æ–∑–¥–∞—Ç—å –ø–ª–∞—Ç–µ–∂ –±–µ–∑ receipt.
    # –î–æ–±–∞–≤–ª—è–µ–º —á–µ–∫, –µ—Å–ª–∏ –≤ secret file —É–∫–∞–∑–∞–Ω YK_RECEIPT_EMAIL.
    if YOO_RECEIPT_EMAIL:
        payload["receipt"] = {
            "customer": {"email": YOO_RECEIPT_EMAIL},
            "items": [{
                "description": title[:128],
                "quantity": "1.00",
                "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
                "vat_code": YOO_VAT_CODE,
                "payment_mode": "full_payment",
                "payment_subject": "service",
            }],
        }
    headers = {"Idempotence-Key": str(uuid.uuid4())}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post("https://api.yookassa.ru/v3/payments", auth=_yoo_auth(), headers=headers, json=payload)
        if r.status_code >= 400:
            log.error("YooKassa create payment failed status=%s method=%s body=%s", r.status_code, method_key, r.text[:1200])
            raise RuntimeError(f"YooKassa {r.status_code}: {r.text[:800]}")
        return r.json()



def _credit_pack_resolve(requested_credits: int = 0, requested_rub: int = 0) -> tuple[int, int] | None:
    """–†–∞–∑—Ä–µ—à–∞–µ—Ç —Ç–æ–ª—å–∫–æ –∑–∞—Ñ–∏–∫—Å–∏—Ä–æ–≤–∞–Ω–Ω—ã–µ –ø–∞–∫–µ—Ç—ã; –∑–Ω–∞—á–µ–Ω–∏—è –∏–∑ WebApp –Ω–µ —Å—á–∏—Ç–∞—é—Ç—Å—è –¥–æ–≤–µ—Ä–µ–Ω–Ω—ã–º–∏."""
    for credits_raw, rub_raw in CREDIT_PACKAGES_RUB.items():
        credits, rub = int(credits_raw), int(rub_raw)
        if requested_credits and requested_credits == credits:
            return credits, rub
        if requested_rub and requested_rub == rub:
            return credits, rub
    return None


async def _yoo_create_credit_payment(user_id: int, credits: int, amount_rub: int, method_key: str = "yoo_all") -> dict:
    resolved = _credit_pack_resolve(int(credits), int(amount_rub))
    if not resolved:
        raise ValueError("Unknown credit package")
    credits, amount_rub = resolved
    method_key = method_key if method_key in YOO_DIRECT_METHODS else "yoo_all"
    method = YOO_DIRECT_METHODS[method_key]
    title = f"–ü–æ–ø–æ–ª–Ω–µ–Ω–∏–µ –±–∞–ª–∞–Ω—Å–∞: {credits} –∫—Ä–µ–¥–∏—Ç–æ–≤"
    confirmation_type = method.get("confirmation") or "redirect"
    payload = {
        "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
        "capture": True,
        "description": title,
        "metadata": {
            "kind": "credit_topup",
            "user_id": str(user_id),
            "credits": str(credits),
            "amount_rub": str(amount_rub),
            "method": method_key,
        },
        "confirmation": {"type": confirmation_type},
    }
    if method.get("type"):
        payload["payment_method_data"] = {"type": method["type"]}
    if confirmation_type in ("redirect", "external"):
        payload["confirmation"]["return_url"] = YOO_PAYMENT_RETURN_URL
    if YOO_RECEIPT_EMAIL:
        payload["receipt"] = {
            "customer": {"email": YOO_RECEIPT_EMAIL},
            "items": [{
                "description": title[:128],
                "quantity": "1.00",
                "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
                "vat_code": YOO_VAT_CODE,
                "payment_mode": "full_payment",
                "payment_subject": "service",
            }],
        }
    headers = {"Idempotence-Key": str(uuid.uuid4())}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post("https://api.yookassa.ru/v3/payments", auth=_yoo_auth(), headers=headers, json=payload)
        if r.status_code >= 400:
            log.error("YooKassa credit payment failed status=%s body=%s", r.status_code, r.text[:1200])
            raise RuntimeError(f"YooKassa {r.status_code}: {r.text[:800]}")
        return r.json()


async def _poll_yoo_credit_payment(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    user_id: int,
    payment_id: str,
    credits: int,
    amount_rub: int,
):
    deadline = time.time() + max(60, YOO_PAYMENT_POLL_SECONDS)
    try:
        while time.time() < deadline:
            p = await _yoo_get_payment(payment_id)
            st = (p or {}).get("status", "").lower()
            if st == "succeeded":
                paid_key = f"yoo:credit_paid:{payment_id}"
                if kv_get(paid_key) != "1":
                    _wallet_total_add(user_id, _credits_to_usd(credits))
                    kv_set(paid_key, "1")
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=(
                            "‚úÖ –û–ø–ª–∞—Ç–∞ –ÆKassa –ø–æ–¥—Ç–≤–µ—Ä–∂–¥–µ–Ω–∞.\n"
                            f"–ù–∞—á–∏—Å–ª–µ–Ω–æ: {credits} –∫—Ä–µ–¥–∏—Ç–æ–≤ –∑–∞ {amount_rub} ‚ÇΩ.\n"
                            f"–¢–µ–∫—É—â–∏–π –±–∞–ª–∞–Ω—Å: {_credits_fmt_from_usd(_user_balance_get(user_id))}."
                        ),
                    )
                return
            if st in ("canceled", "cancelled", "failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"‚ùå –û–ø–ª–∞—Ç–∞ –ø–∞–∫–µ—Ç–∞ –∫—Ä–µ–¥–∏—Ç–æ–≤ –Ω–µ –∑–∞–≤–µ—Ä—à–µ–Ω–∞. –°—Ç–∞—Ç—É—Å: {st}.",
                    )
                return
            await asyncio.sleep(max(2.0, YOO_PAYMENT_POLL_INTERVAL_S))
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="‚åõ –í—Ä–µ–º—è –æ–∂–∏–¥–∞–Ω–∏—è –æ–ø–ª–∞—Ç—ã –≤—ã—à–ª–æ. –ï—Å–ª–∏ –ø–ª–∞—Ç—ë–∂ –∑–∞–≤–µ—Ä—à—ë–Ω ‚Äî –æ–±—Ä–∞—Ç–∏—Ç–µ—Å—å –≤ –ø–æ–¥–¥–µ—Ä–∂–∫—É –∏ —É–∫–∞–∂–∏—Ç–µ –≤—Ä–µ–º—è –æ–ø–ª–∞—Ç—ã.",
            )
    except Exception as e:
        log.exception("YooKassa credit poll error: %s", e)

async def _yoo_get_payment(payment_id: str) -> dict | None:
    if not payment_id or not _yoo_direct_configured():
        return None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", auth=_yoo_auth())
            if r.status_code >= 400:
                log.warning("YooKassa get payment failed %s: %s", r.status_code, r.text[:300])
                return None
            return r.json()
    except Exception as e:
        log.exception("YooKassa get payment error: %s", e)
        return None

async def _poll_yoo_subscription_payment(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, user_id: int, payment_id: str, plan_key: str, months: int):
    """–û–∂–∏–¥–∞–µ—Ç –æ–ø–ª–∞—Ç—É direct YooKassa –∏ –∞–∫—Ç–∏–≤–∏—Ä—É–µ—Ç —Ç–∞—Ä–∏—Ñ."""
    deadline = time.time() + max(60, YOO_PAYMENT_POLL_SECONDS)
    try:
        while time.time() < deadline:
            p = await _yoo_get_payment(payment_id)
            st = (p or {}).get("status", "").lower()
            if st == "succeeded":
                until = activate_subscription_with_tier(user_id, plan_key, months)
                credits = SUBSCRIPTION_CREDITS.get((plan_key or "").lower(), 0) * int(months)
                kv_set(f"yoo:paid:{payment_id}", "1")
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=(
                            "‚úÖ –û–ø–ª–∞—Ç–∞ –ÆKassa –ø–æ–¥—Ç–≤–µ—Ä–∂–¥–µ–Ω–∞.\n"
                            f"–ü–æ–¥–ø–∏—Å–∫–∞ {plan_key.upper()} –∞–∫—Ç–∏–≤–Ω–∞ –¥–æ {until.strftime('%Y-%m-%d')}.\n"
                            f"ü™ô –ö—Ä–µ–¥–∏—Ç—ã –Ω–∞—á–∏—Å–ª–µ–Ω—ã: {credits} –∫—Ä."
                        ),
                    )
                return
            if st in ("canceled", "cancelled", "failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=f"‚ùå –û–ø–ª–∞—Ç–∞ –Ω–µ –∑–∞–≤–µ—Ä—à–µ–Ω–∞. –°—Ç–∞—Ç—É—Å: {st}.")
                return
            await asyncio.sleep(max(2.0, YOO_PAYMENT_POLL_INTERVAL_S))
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="‚åõ –í—Ä–µ–º—è –æ–∂–∏–¥–∞–Ω–∏—è –æ–ø–ª–∞—Ç—ã –≤—ã—à–ª–æ. –ï—Å–ª–∏ –≤—ã –æ–ø–ª–∞—Ç–∏–ª–∏ ‚Äî –Ω–∞–∂–º–∏—Ç–µ ¬´üîé –ü—Ä–æ–≤–µ—Ä–∏—Ç—å –æ–ø–ª–∞—Ç—É¬ª –≤ –Ω–æ–≤–æ–º —Å—á—ë—Ç–µ –∏–ª–∏ –Ω–∞–ø–∏—à–∏—Ç–µ –≤ –ø–æ–¥–¥–µ—Ä–∂–∫—É.",
            )
    except Exception as e:
        log.exception("YooKassa subscription poll error: %s", e)

# –ö–Ω–æ–ø–∫–∞ ¬´‚≠ê –ü–æ–¥–ø–∏—Å–∫–∞ ¬∑ –ü–æ–º–æ—â—å¬ª
async def on_btn_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = _plans_overview_text(user_id)
    await update.effective_chat.send_message(text, reply_markup=plans_root_kb())

# –û–±—Ä–∞–±–æ—Ç—á–∏–∫ –Ω–∞—à–∏—Ö –∫–æ–ª–±—ç–∫–æ–≤ –ø–æ –ø–æ–¥–ø–∏—Å–∫–µ/–æ–ø–ª–∞—Ç–∞–º (–∑–∞—Ä–µ–≥–∏—Å—Ç—Ä–∏—Ä–æ–≤–∞—Ç—å –î–û –æ–±—â–µ–≥–æ on_cb!)
async def on_cb_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    user_id = q.from_user.id
    chat_id = q.message.chat.id  # FIX: –∫–æ—Ä—Ä–µ–∫—Ç–Ω–æ–µ –ø–æ–ª–µ –≤ PTB v21+

    # –ù–∞–≤–∏–≥–∞—Ü–∏—è –º–µ–∂–¥—É —Ç–∞—Ä–∏—Ñ–∞–º–∏
    if data.startswith("plan:"):
        _, arg = data.split(":", 1)
        if arg == "root":
            await q.message.reply_text(_plans_overview_text(user_id), reply_markup=plans_root_kb())
            await q.answer()
            return
        if arg in SUBS_TIERS:
            await q.message.reply_text(
                _plan_card_text(arg) + "\n–í—ã–±–µ—Ä–∏—Ç–µ —Å–ø–æ—Å–æ–± –æ–ø–ª–∞—Ç—ã:",
                reply_markup=plan_pay_kb(arg)
            )
            await q.answer()
            return

    # –ü–ª–∞—Ç–µ–∂–∏
    if data.startswith("pay:"):
        # –±–µ–∑–æ–ø–∞—Å–Ω—ã–π –ø–∞—Ä—Å–∏–Ω–≥
        try:
            _, method, plan_key = data.split(":", 2)
        except ValueError:
            await q.answer("–ù–µ–∫–æ—Ä—Ä–µ–∫—Ç–Ω—ã–µ –¥–∞–Ω–Ω—ã–µ –∫–Ω–æ–ø–∫–∏.", show_alert=True)
            return

        plan = SUBS_TIERS.get(plan_key)
        if not plan:
            await q.answer("–ù–µ–∏–∑–≤–µ—Å—Ç–Ω—ã–π —Ç–∞—Ä–∏—Ñ.", show_alert=True)
            return

        # –ÆKassa direct API: –°–ë–ü/QR, SberPay, T-Pay, Mir Pay
        if method in YOO_DIRECT_METHODS:
            await q.answer("–°–æ–∑–¥–∞—é —Å—Å—ã–ª–∫—É –Ω–∞ –æ–ø–ª–∞—Ç—É‚Ä¶")
            if not _yoo_direct_configured():
                await q.message.reply_text(
                    "‚ö†Ô∏è –ë—ã—Å—Ç—Ä–∞—è –æ–ø–ª–∞—Ç–∞ –ÆKassa –ø–æ–∫–∞ –Ω–µ –Ω–∞—Å—Ç—Ä–æ–µ–Ω–∞: –Ω—É–∂–Ω—ã YOO_SHOP_ID/YOO_SECRET_KEY –∏–ª–∏ Secret File yookassa.env —Å YK_ID/YK_KEY."
                )
                return
            try:
                pay = await _yoo_create_direct_payment(user_id, plan_key, 1, method)
                payment_id = str(pay.get("id") or "")
                conf = pay.get("confirmation") or {}
                pay_url = conf.get("confirmation_url") or conf.get("confirmation_data") or conf.get("external_url") or ""
                label = YOO_DIRECT_METHODS[method]["label"]
                if not pay_url:
                    raise RuntimeError(f"YooKassa did not return confirmation url: {pay}")
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{label} ‚Äî –æ–ø–ª–∞—Ç–∏—Ç—å", url=pay_url)],
                    [InlineKeyboardButton("‚¨ÖÔ∏è –ö —Ç–∞—Ä–∏—Ñ—É", callback_data=f"plan:{plan_key}")],
                ])
                msg = await q.message.reply_text(
                    _plan_card_text(plan_key)
                    + f"\n–°–ø–æ—Å–æ–± –æ–ø–ª–∞—Ç—ã: {label}\n"
                    + "–û—Ç–∫—Ä–æ–π—Ç–µ —Å—Å—ã–ª–∫—É. –ü–æ—Å–ª–µ –æ–ø–ª–∞—Ç—ã –±–æ—Ç –∞–∫—Ç–∏–≤–∏—Ä—É–µ—Ç –ø–æ–¥–ø–∏—Å–∫—É –∞–≤—Ç–æ–º–∞—Ç–∏—á–µ—Å–∫–∏.",
                    reply_markup=kb,
                )
                kv_set(f"yoo:pending:{payment_id}", json.dumps({"user_id": user_id, "tier": plan_key, "months": 1, "method": method}, ensure_ascii=False))
                context.application.create_task(_poll_yoo_subscription_payment(
                    context, msg.chat.id, msg.message_id, user_id, payment_id, plan_key, 1
                ))
            except Exception as e:
                log.exception("YooKassa direct payment create failed: %s", e)
                err = str(e)[:700]
                user_msg = "‚ö†Ô∏è –ù–µ —É–¥–∞–ª–æ—Å—å —Å–æ–∑–¥–∞—Ç—å –±—ã—Å—Ç—Ä—É—é –æ–ø–ª–∞—Ç—É –ÆKassa. –ü–æ–ø—Ä–æ–±—É–π—Ç–µ –∫–∞—Ä—Ç—É Telegram, CryptoBot –∏–ª–∏ –ø–æ–∑–∂–µ."
                if YOO_DEBUG_PAY_ERRORS:
                    user_msg += "\n\n–î–∏–∞–≥–Ω–æ—Å—Ç–∏–∫–∞ –ÆKassa: " + err
                await q.message.reply_text(user_msg)
            return

        # –ÆKassa —á–µ—Ä–µ–∑ Telegram Payments / –±–∞–Ω–∫–æ–≤—Å–∫–∞—è –∫–∞—Ä—Ç–∞
        if method == "yookassa":
            if not YOOKASSA_PROVIDER_TOKEN:
                await q.answer("–ÆKassa –Ω–µ –ø–æ–¥–∫–ª—é—á–µ–Ω–∞ (–Ω–µ—Ç YOOKASSA_PROVIDER_TOKEN).", show_alert=True)
                return

            title = f"–ü–æ–¥–ø–∏—Å–∫–∞ {plan['title']} ‚Ä¢ 1 –º–µ—Å—è—Ü"
            desc = "–î–æ—Å—Ç—É–ø –∫ —Ñ—É–Ω–∫—Ü–∏—è–º –±–æ—Ç–∞ —Å–æ–≥–ª–∞—Å–Ω–æ –≤—ã–±—Ä–∞–Ω–Ω–æ–º—É —Ç–∞—Ä–∏—Ñ—É. –ü–æ–¥–ø–∏—Å–∫–∞ –∞–∫—Ç–∏–≤–∏—Ä—É–µ—Ç—Å—è —Å—Ä–∞–∑—É –ø–æ—Å–ª–µ –æ–ø–ª–∞—Ç—ã."
            payload = json.dumps({"tier": plan_key, "months": 1})

            # Telegram –æ–∂–∏–¥–∞–µ—Ç —Å—É–º–º—É –≤ –º–∏–Ω–æ—Ä–Ω—ã—Ö –µ–¥–∏–Ω–∏—Ü–∞—Ö (–∫–æ–ø–µ–π–∫–∏/—Ü–µ–Ω—Ç—ã)
            if YOOKASSA_CURRENCY == "RUB":
                total_minor = int(round(float(plan["rub"]) * 100))
            else:
                total_minor = int(round(float(plan["usd"]) * 100))

            prices = [LabeledPrice(label=f"{plan['title']} 1 –º–µ—Å.", amount=total_minor)]
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
            await q.answer("–°—á—ë—Ç –≤—ã—Å—Ç–∞–≤–ª–µ–Ω ‚úÖ")
            return

        # CryptoBot (Crypto Pay API: —Å–æ–∑–¥–∞—ë–º –∏–Ω–≤–æ–π—Å –∏ –æ—Ç–¥–∞—ë–º —Å—Å—ã–ª–∫—É)
        if method == "cryptobot":  # FIX: –≤—ã—Ä–æ–≤–Ω–µ–Ω –æ—Ç—Å—Ç—É–ø
            if not CRYPTO_PAY_API_TOKEN:
                await q.answer("CryptoBot –Ω–µ –ø–æ–¥–∫–ª—é—á—ë–Ω (–Ω–µ—Ç CRYPTO_PAY_API_TOKEN).", show_alert=True)
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
                            "description": f"Subscription {plan['title']} ‚Ä¢ 1 month",
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
                    [InlineKeyboardButton("üí† CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("‚¨ÖÔ∏è –ö —Ç–∞—Ä–∏—Ñ—É", callback_data=f"plan:{plan_key}")],
                ])
                msg = await q.message.reply_text(
                    _plan_card_text(plan_key) + "\n–û—Ç–∫—Ä–æ–π—Ç–µ —Å—Å—ã–ª–∫—É –¥–ª—è –æ–ø–ª–∞—Ç—ã:",
                    reply_markup=kb
                )
                # –∞–≤—Ç–æ–ø—É–ª —Å—Ç–∞—Ç—É—Å–∞ –∏–º–µ–Ω–Ω–æ –¥–ª—è –ü–û–î–ü–ò–°–ö–ò
                context.application.create_task(_poll_crypto_sub_invoice(
                    context, msg.chat.id, msg.message_id, user_id, inv_id, plan_key, 1  # FIX: msg.chat.id
                ))
                await q.answer()
            except Exception as e:
                await q.answer("–ù–µ —É–¥–∞–ª–æ—Å—å —Å–æ–∑–¥–∞—Ç—å —Å—á—ë—Ç –≤ CryptoBot.", show_alert=True)
                log.exception("CryptoBot invoice error: %s", e)
            return

        # –°–ø–∏—Å–∞–Ω–∏–µ —Å –≤–Ω—É—Ç—Ä–µ–Ω–Ω–µ–≥–æ –∫—Ä–µ–¥–∏—Ç–Ω–æ–≥–æ –±–∞–ª–∞–Ω—Å–∞
        if method == "balance":
            price_credits = int(plan["rub"])
            price_internal = _credits_to_usd(price_credits)
            if not _user_balance_debit(user_id, price_internal):
                await q.answer("–ù–µ–¥–æ—Å—Ç–∞—Ç–æ—á–Ω–æ –∫—Ä–µ–¥–∏—Ç–æ–≤ –Ω–∞ –±–∞–ª–∞–Ω—Å–µ.", show_alert=True)
                return
            until = _sub_activate(user_id, plan_key, months=1)
            await q.message.reply_text(
                f"‚úÖ –ü–æ–¥–ø–∏—Å–∫–∞ {plan['title']} –∞–∫—Ç–∏–≤–∏—Ä–æ–≤–∞–Ω–∞ –¥–æ {until[:10]}.\n"
                f"ü™ô –°–ø–∏—Å–∞–Ω–æ: {price_credits} –∫—Ä. "
                f"–¢–µ–∫—É—â–∏–π –±–∞–ª–∞–Ω—Å: {_credits_fmt_from_usd(_user_balance_get(user_id))}",
                reply_markup=plans_root_kb(),
            )
            await q.answer()
            return

    # –ï—Å–ª–∏ –∫–æ–ª–±—ç–∫ –Ω–µ –Ω–∞—à ‚Äî –ø—Ä–æ–ø—É—Å–∫–∞–µ–º –¥–∞–ª—å—à–µ
    await q.answer()
    return


# –ï—Å–ª–∏ —É —Ç–µ–±—è —É–∂–µ –µ—Å—Ç—å on_precheckout / on_successful_payment ‚Äî –æ—Å—Ç–∞–≤—å –∏—Ö.
# –ï—Å–ª–∏ –Ω–µ—Ç, –º–æ–∂–µ—à—å –∏—Å–ø–æ–ª—å–∑–æ–≤–∞—Ç—å —ç—Ç–∏ –ø—Ä–æ—Å—Ç—ã–µ —Ä–µ–∞–ª–∏–∑–∞—Ü–∏–∏:

async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.pre_checkout_query.answer(ok=True)
    except Exception as e:
        log.exception("precheckout error: %s", e)

async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    –£–Ω–∏–≤–µ—Ä—Å–∞–ª—å–Ω—ã–π –æ–±—Ä–∞–±–æ—Ç—á–∏–∫ Telegram Payments:
    - –ü–æ–¥–¥–µ—Ä–∂–∏–≤–∞–µ—Ç payload –≤ –¥–≤—É—Ö —Ñ–æ—Ä–º–∞—Ç–∞—Ö:
        1) JSON: {"tier":"pro","months":1}
        2) –°—Ç—Ä–æ–∫–∞: "sub:pro:1"
    - –ò–Ω–∞—á–µ —Ç—Ä–∞–∫—Ç—É–µ—Ç –∫–∞–∫ –ø–æ–ø–æ–ª–Ω–µ–Ω–∏–µ –µ–¥–∏–Ω–æ–≥–æ USD-–∫–æ—à–µ–ª—å–∫–∞.
    """
    try:
        sp = update.message.successful_payment
        payload_raw = sp.invoice_payload or ""
        total_minor = sp.total_amount or 0
        rub = total_minor / 100.0
        uid = update.effective_user.id

        # 1) –ü—ã—Ç–∞–µ–º—Å—è —Ä–∞—Å–ø–∞—Ä—Å–∏—Ç—å JSON
        tier, months = None, None
        try:
            if payload_raw.strip().startswith("{"):
                obj = json.loads(payload_raw)
                tier = (obj.get("tier") or "").strip().lower() or None
                months = int(obj.get("months") or 1)
        except Exception:
            pass

        # 2) –ü—ã—Ç–∞–µ–º—Å—è —Ä–∞—Å–ø–∞—Ä—Å–∏—Ç—å —Å—Ç—Ä–æ–∫–æ–≤—ã–π —Ñ–æ—Ä–º–∞—Ç "sub:tier:months"
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
                f"üéâ –û–ø–ª–∞—Ç–∞ –ø—Ä–æ—à–ª–∞ —É—Å–ø–µ—à–Ω–æ!\n"
                f"‚úÖ –ü–æ–¥–ø–∏—Å–∫–∞ {tier.upper()} –∞–∫—Ç–∏–≤–∏—Ä–æ–≤–∞–Ω–∞ –¥–æ {until.strftime('%Y-%m-%d')}.\nü™ô –ö—Ä–µ–¥–∏—Ç—ã –Ω–∞—á–∏—Å–ª–µ–Ω—ã: {SUBSCRIPTION_CREDITS.get((tier or "").lower(), 0) * int(months)} –∫—Ä."
            )
            return

        if payload_raw.startswith("topup:"):
            try:
                _, credits_s, rub_s = payload_raw.split(":", 2)
                resolved = _credit_pack_resolve(int(credits_s), int(rub_s))
                if resolved:
                    credits, expected_rub = resolved
                    _wallet_total_add(uid, _credits_to_usd(credits))
                    await update.effective_message.reply_text(
                        f"‚úÖ –û–ø–ª–∞—Ç–∞ –ø—Ä–æ—à–ª–∞ —É—Å–ø–µ—à–Ω–æ. –ù–∞—á–∏—Å–ª–µ–Ω–æ: {credits} –∫—Ä–µ–¥–∏—Ç–æ–≤ –∑–∞ {expected_rub} ‚ÇΩ."
                    )
                    return
            except Exception:
                log.exception("Failed to parse topup payload: %s", payload_raw)

        # –ò–Ω–∞—á–µ —Å—á–∏—Ç–∞–µ–º, —á—Ç–æ —ç—Ç–æ –ø–æ–ø–æ–ª–Ω–µ–Ω–∏–µ –∫–æ—à–µ–ª—å–∫–∞ –≤ —Ä—É–±–ª—è—Ö
        usd = _credits_to_usd(rub)
        _wallet_total_add(uid, usd)
        await update.effective_message.reply_text(
            f"üí≥ –ü–æ–ø–æ–ª–Ω–µ–Ω–∏–µ: {rub:.0f} ‚ÇΩ. –ù–∞—á–∏—Å–ª–µ–Ω–æ: {_credits_fmt_from_usd(usd)}."
        )

    except Exception as e:
        log.exception("successful_payment handler error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("‚ö†Ô∏è –û—à–∏–±–∫–∞ –æ–±—Ä–∞–±–æ—Ç–∫–∏ –ø–ª–∞—Ç–µ–∂–∞. –ï—Å–ª–∏ –¥–µ–Ω—å–≥–∏ —Å–ø–∏—Å–∞–ª–∏—Å—å ‚Äî –Ω–∞–ø–∏—à–∏—Ç–µ –≤ –ø–æ–¥–¥–µ—Ä–∂–∫—É.")
# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ö–æ–Ω–µ—Ü PATCH ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
        
# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ –ö–æ–º–∞–Ω–¥–∞ /img ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip() if context.args else ""
    if not prompt:
        await update.effective_message.reply_text("–§–æ—Ä–º–∞—Ç: /img <–æ–ø–∏—Å–∞–Ω–∏–µ>")
        return

    async def _go():
        return await _do_img_generate(update, context, prompt)

    user_id = update.effective_user.id
    await _try_pay_then_do(
        update, context, user_id,
        "img", IMG_COST_USD, _go,
        remember_kind="img_generate", remember_payload={"prompt": prompt}
    )


async def cmd_midjourney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip() if context.args else ""
    await _start_midjourney_image(update, context, prompt)


# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ Work/Business generators + Suno music ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
def _safe_filename(name: str, ext: str) -> str:
    base = re.sub(r"[^a-zA-Z–∞-—è–ê-–Ø0-9_.-]+", "_", (name or "file")).strip("._")[:48] or "file"
    return f"{base}.{ext.lstrip('.')}"

async def _reply_long_text(update: Update, text: str, reply_markup=None):
    text = (text or "").strip()
    if not text:
        return
    first = True
    for i in range(0, len(text), 3800):
        await update.effective_message.reply_text(text[i:i+3800], reply_markup=reply_markup if first else None)
        first = False

async def _generate_business_presentation(update: Update, context: ContextTypes.DEFAULT_TYPE, brief: str):
    prompt = (
        "–¢—ã –±–∏–∑–Ω–µ—Å-–∫–æ–Ω—Å—É–ª—å—Ç–∞–Ω—Ç –∏ –ø—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏–æ–Ω–Ω—ã–π —Ä–µ–¥–∞–∫—Ç–æ—Ä. –ù–∞ —Ä—É—Å—Å–∫–æ–º —Å–¥–µ–ª–∞–π —Å—Ç—Ä—É–∫—Ç—É—Ä—É –ø—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏–∏ –ø–æ –¢–ó –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è. "
        "–§–æ—Ä–º–∞—Ç —Å—Ç—Ä–æ–≥–æ: –∑–∞–≥–æ–ª–æ–≤–æ–∫, –∑–∞—Ç–µ–º 8-12 —Å–ª–∞–π–¥–æ–≤. –î–ª—è –∫–∞–∂–¥–æ–≥–æ —Å–ª–∞–π–¥–∞: –ù–∞–∑–≤–∞–Ω–∏–µ, 3-5 –±—É–ª–ª–µ—Ç–æ–≤, –≤–∏–∑—É–∞–ª—å–Ω–∞—è –∏–¥–µ—è, –∑–∞–º–µ—Ç–∫–∞ —Å–ø–∏–∫–µ—Ä–∞. "
        "–ù–µ –ø–∏—à–∏ –ª–∏—à–Ω–∏—Ö –≤—Å—Ç—É–ø–ª–µ–Ω–∏–π. –¢–ó:\n" + (brief or "")
    )
    reply = await ask_openai_text(prompt, user_id=update.effective_user.id, chat_id=update.effective_chat.id)
    await _reply_long_text(update, "üìä –ß–µ—Ä–Ω–æ–≤–∏–∫ –ø—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏–∏ –≥–æ—Ç–æ–≤. –ù–∏–∂–µ —Å—Ç—Ä—É–∫—Ç—É—Ä–∞, –æ—Ç–¥–µ–ª—å–Ω–æ –ø—Ä–∏–∫—Ä–µ–ø–ª—è—é PPTX-—Ñ–∞–π–ª.\n\n" + reply)
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        prs = Presentation()
        title = (brief or "–ü—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏—è")[:80]
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = title
        slide.placeholders[1].text = "–ß–µ—Ä–Ω–æ–≤–∏–∫ —Å–æ–∑–¥–∞–Ω Neyro-Bot GPT 5 Studio"
        chunks = re.split(r"\n(?=\s*(?:–°–ª–∞–π–¥\s*\d+|\d+[\).]|#{1,3}\s+))", reply)
        slide_count = 0
        for ch in chunks:
            lines = [re.sub(r"^[#\s]*", "", x).strip(" -‚Ä¢\t") for x in ch.splitlines() if x.strip()]
            if not lines:
                continue
            if slide_count >= 12:
                break
            ttl = lines[0][:90] or f"–°–ª–∞–π–¥ {slide_count+1}"
            body_lines = [x for x in lines[1:8] if x][:6]
            sl = prs.slides.add_slide(prs.slide_layouts[1])
            sl.shapes.title.text = ttl
            tf = sl.placeholders[1].text_frame
            tf.clear()
            if not body_lines:
                body_lines = [ttl]
            for j, line in enumerate(body_lines):
                p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
                p.text = line[:240]
                p.level = 0
                with contextlib.suppress(Exception):
                    p.font.size = Pt(20)
            slide_count += 1
        if slide_count == 0:
            sl = prs.slides.add_slide(prs.slide_layouts[1])
            sl.shapes.title.text = "–°—Ç—Ä—É–∫—Ç—É—Ä–∞"
            sl.placeholders[1].text = reply[:1500]
        bio = BytesIO()
        prs.save(bio)
        bio.seek(0)
        bio.name = _safe_filename("presentation", "pptx")
        await update.effective_message.reply_document(InputFile(bio), caption="üìä –ü—Ä–µ–∑–µ–Ω—Ç–∞—Ü–∏—è PPTX –≥–æ—Ç–æ–≤–∞.")
    except Exception as e:
        log.exception("pptx generation failed: %s", e)
        bio = BytesIO(reply.encode("utf-8")); bio.name = _safe_filename("presentation_outline", "txt")
        await update.effective_message.reply_document(InputFile(bio), caption="‚ö†Ô∏è PPTX –Ω–µ —Å–æ–±—Ä–∞–ª—Å—è –Ω–∞ —Å–µ—Ä–≤–µ—Ä–µ, –æ—Ç–ø—Ä–∞–≤–ª—è—é —Å—Ç—Ä—É–∫—Ç—É—Ä—É TXT.")

async def _generate_business_catalog_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE, brief: str):
    prompt = (
        "–¢—ã –º–∞—Ä–∫–µ—Ç–æ–ª–æ–≥ –∏ —Ä–µ–¥–∞–∫—Ç–æ—Ä –∫–æ–º–º–µ—Ä—á–µ—Å–∫–∏—Ö –∫–∞—Ç–∞–ª–æ–≥–æ–≤. –ù–∞ —Ä—É—Å—Å–∫–æ–º –ø–æ–¥–≥–æ—Ç–æ–≤—å —Ç–µ–∫—Å—Ç PDF-–∫–∞—Ç–∞–ª–æ–≥–∞ –ø–æ –¢–ó –ø–æ–ª—å–∑–æ–≤–∞—Ç–µ–ª—è. "
        "–°—Ç—Ä—É–∫—Ç—É—Ä–∞: –æ–±–ª–æ–∂–∫–∞, –∫—Ä–∞—Ç–∫–æ–µ –£–¢–ü, –±–ª–æ–∫–∏ –æ–±—ä–µ–∫—Ç–æ–≤/—Ç–æ–≤–∞—Ä–æ–≤/—É—Å–ª—É–≥, —Ö–∞—Ä–∞–∫—Ç–µ—Ä–∏—Å—Ç–∏–∫–∏, –ø—Ä–µ–∏–º—É—â–µ—Å—Ç–≤–∞, —É—Å–ª–æ–≤–∏—è, CTA, –∫–æ–Ω—Ç–∞–∫—Ç—ã. "
        "–ï—Å–ª–∏ –¥–∞–Ω–Ω—ã—Ö –Ω–µ —Ö–≤–∞—Ç–∞–µ—Ç ‚Äî —Å–¥–µ–ª–∞–π –∞–∫–∫—É—Ä–∞—Ç–Ω—ã–π —à–∞–±–ª–æ–Ω —Å –º–µ—Å—Ç–∞–º–∏ –¥–ª—è –∑–∞–ø–æ–ª–Ω–µ–Ω–∏—è. –¢–ó:\n" + (brief or "")
    )
    reply = await ask_openai_text(prompt, user_id=update.effective_user.id, chat_id=update.effective_chat.id)
    await _reply_long_text(update, "üìï –ß–µ—Ä–Ω–æ–≤–∏–∫ PDF-–∫–∞—Ç–∞–ª–æ–≥–∞ –≥–æ—Ç–æ–≤. –ù–∏–∂–µ —Ç–µ–∫—Å—Ç, –æ—Ç–¥–µ–ª—å–Ω–æ –ø—Ä–∏–∫—Ä–µ–ø–ª—è—é PDF-—Ñ–∞–π–ª.\n\n" + reply)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib.units import mm
        # –ü—ã—Ç–∞–µ–º—Å—è –ø–æ–¥–∫–ª—é—á–∏—Ç—å DejaVu –¥–ª—è –∫–∏—Ä–∏–ª–ª–∏—Ü—ã, –µ—Å–ª–∏ –æ–Ω –µ—Å—Ç—å –≤ –æ–∫—Ä—É–∂–µ–Ω–∏–∏ Render.
        font_name = "Helvetica"
        for fp in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
            if os.path.exists(fp):
                pdfmetrics.registerFont(TTFont("DejaVuSans", fp))
                font_name = "DejaVuSans"
                break
        bio = BytesIO()
        c = canvas.Canvas(bio, pagesize=A4)
        width, height = A4
        x, y = 18*mm, height - 20*mm
        c.setFont(font_name, 16)
        c.drawString(x, y, "PDF-–∫–∞—Ç–∞–ª–æ–≥")
        y -= 12*mm
        c.setFont(font_name, 10)
        for raw in reply.splitlines():
            line = raw.strip()
            if not line:
                y -= 5*mm
                continue
            # –ü—Ä–æ—Å—Ç–∞—è –ø–µ—Ä–µ–Ω–æ—Å–∫–∞ —Å—Ç—Ä–æ–∫.
            while line:
                part = line[:105]
                line = line[105:]
                if y < 18*mm:
                    c.showPage(); c.setFont(font_name, 10); y = height - 20*mm
                c.drawString(x, y, part)
                y -= 5.2*mm
        c.save()
        bio.seek(0); bio.name = _safe_filename("catalog", "pdf")
        await update.effective_message.reply_document(InputFile(bio), caption="üìï PDF-–∫–∞—Ç–∞–ª–æ–≥ –≥–æ—Ç–æ–≤.")
    except Exception as e:
        log.exception("pdf catalog generation failed: %s", e)
        bio = BytesIO(reply.encode("utf-8")); bio.name = _safe_filename("catalog_text", "txt")
        await update.effective_message.reply_document(InputFile(bio), caption="‚ö†Ô∏è PDF –Ω–µ —Å–æ–±—Ä–∞–ª—Å—è –Ω–∞ —Å–µ—Ä–≤–µ—Ä–µ, –æ—Ç–ø—Ä–∞–≤–ª—è—é —Ç–µ–∫—Å—Ç –∫–∞—Ç–∞–ª–æ–≥–∞ TXT.")

def _extract_logo_brand_name(brief: str) -> str:
    s = (brief or "").strip()
    patterns = [
        r"(?:–Ω–∞–∑–≤–∞–Ω–∏–µ|–±—Ä–µ–Ω–¥|–∫–æ–º–ø–∞–Ω(?:–∏—è|–∏–∏)|–ø—Ä–æ–µ–∫—Ç)\s*[:‚Äî-]\s*['\"¬´]?([^'\"¬ª\n,.;]{2,40})",
        r"['\"¬´]([^'\"¬ª]{2,40})['\"¬ª]",
        r"(?:–ª–æ–≥–æ—Ç–∏–ø|–ª–æ–≥–æ)\s+(?:–¥–ª—è|–±—Ä–µ–Ω–¥–∞|–∫–æ–º–ø–∞–Ω–∏–∏)?\s*['\"¬´]?([^'\"¬ª\n,.;]{2,40})",
    ]
    for pat in patterns:
        m = re.search(pat, s, flags=re.I)
        if m:
            name = re.sub(r"\s+", " ", m.group(1)).strip(" -‚Äî:;,.¬´¬ª\"'")
            if 2 <= len(name) <= 40:
                return name
    words = re.findall(r"[A-Za-z–ê-–Ø–∞-—è–Å—ë0-9]+", s)
    stop = {"—Å–æ–∑–¥–∞–π", "—Å–¥–µ–ª–∞–π", "–ª–æ–≥–æ—Ç–∏–ø", "–ª–æ–≥–æ", "–¥–ª—è", "–±—Ä–µ–Ω–¥", "–±—Ä–µ–Ω–¥–∞", "–∫–æ–º–ø–∞–Ω–∏–∏", "–Ω–µ–π—Ä–æ", "–º—É–ª—å—Ç–∏–º–æ–¥–∞–ª—å–Ω—ã–π", "–±–æ—Ç", "—Å—Ç–∏–ª—å", "—Ü–≤–µ—Ç", "—Ü–≤–µ—Ç–∞"}
    picked = [w for w in words[:8] if w.lower() not in stop]
    return " ".join(picked[:2])[:32] or "Brand"


def _logo_initials(name: str) -> str:
    parts = re.findall(r"[A-Za-z–ê-–Ø–∞-—è–Å—ë0-9]+", name or "Brand")
    if not parts:
        return "B"
    return "".join(p[0].upper() for p in parts[:2])[:3]


def _load_logo_font(size: int, bold: bool = True):
    if ImageFont is None:
        return None
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for fp in candidates:
        if fp and os.path.exists(fp):
            with contextlib.suppress(Exception):
                return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def _draw_centered_text(draw, xy, text_value, font, fill):
    x, y = xy
    try:
        bbox = draw.textbbox((0, 0), text_value, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        w, h = draw.textlength(text_value, font=font), 40
    draw.text((x - w / 2, y - h / 2), text_value, font=font, fill=fill)


def _make_local_logo_png(brief: str) -> bytes | None:
    if not (LOGO_LOCAL_FALLBACK and Image and ImageDraw):
        return None
    try:
        brand = _extract_logo_brand_name(brief)
        initials = _logo_initials(brand)
        W, H = 1024, 1024
        img = Image.new("RGB", (W, H), (12, 18, 33))
        draw = ImageDraw.Draw(img)
        # simple premium gradient
        for y in range(H):
            r = int(12 + 18 * y / H)
            g = int(18 + 30 * y / H)
            b = int(33 + 55 * y / H)
            draw.line([(0, y), (W, y)], fill=(r, g, b))
        # soft glow circles
        for radius, alpha_color, cx, cy in [(360, (47, 128, 255), 240, 180), (300, (124, 224, 255), 840, 820)]:
            overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            for i in range(radius, 0, -8):
                a = int(55 * (i / radius) ** 2)
                c = alpha_color + (a,)
                od.ellipse((cx-i, cy-i, cx+i, cy+i), fill=c)
            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
            draw = ImageDraw.Draw(img)
        # emblem
        draw.rounded_rectangle((248, 168, 776, 696), radius=120, outline=(124, 224, 255), width=10, fill=(17, 28, 51))
        draw.ellipse((332, 246, 692, 606), outline=(47, 128, 255), width=18)
        f_big = _load_logo_font(170, True)
        f_brand = _load_logo_font(58, True)
        f_sub = _load_logo_font(30, False)
        _draw_centered_text(draw, (512, 430), initials, f_big, (248, 251, 255))
        _draw_centered_text(draw, (512, 790), brand[:32], f_brand, (248, 251, 255))
        tagline = "AI ‚Ä¢ BRAND ‚Ä¢ PRODUCT" if re.search(r"ai|–∏–∏|–Ω–µ–π—Ä–æ|–±–æ—Ç|tech|digital", brief or "", re.I) else "PREMIUM BRAND IDENTITY"
        _draw_centered_text(draw, (512, 854), tagline, f_sub, (199, 215, 235))
        out = BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception as e:
        log.exception("local logo fallback failed: %s", e)
        return None


async def _download_image_url_bytes(url: str, timeout_s: float = 180.0) -> bytes | None:
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            ct = (r.headers.get("content-type") or "").lower()
            if r.content and len(r.content) > 1000 and ("image" in ct or url.lower().split("?")[0].endswith((".png", ".jpg", ".jpeg", ".webp"))):
                return bytes(r.content)
    except Exception as e:
        log.warning("download image url failed: %s", e)
    return None


async def _comet_generate_image_bytes(prompt: str) -> bytes | None:
    if not (COMET_API_KEY and COMET_BASE_URL and COMET_IMAGE_GEN_PATH):
        return None
    url = f"{COMET_BASE_URL}{COMET_IMAGE_GEN_PATH}"
    headers = {"Authorization": f"Bearer {COMET_API_KEY}", "Content-Type": "application/json", "Accept": "application/json"}
    payloads = [
        {"model": COMET_IMAGE_GEN_MODEL, "prompt": prompt, "size": "1024x1024", "n": 1},
        {"model": COMET_IMAGE_GEN_MODEL, "prompt": prompt, "response_format": "b64_json", "size": "1024x1024", "n": 1},
    ]
    try:
        async with httpx.AsyncClient(timeout=float(COMET_IMAGE_GEN_TIMEOUT_S), follow_redirects=True) as client:
            last_body = ""
            for payload in payloads:
                r = await client.post(url, headers=headers, json=payload)
                last_body = r.text[:500]
                if r.status_code >= 400:
                    log.warning("Comet image gen HTTP %s: %s", r.status_code, last_body)
                    continue
                j = r.json() or {}
                candidates = []
                if isinstance(j.get("data"), list):
                    candidates.extend(j.get("data") or [])
                if isinstance(j.get("images"), list):
                    candidates.extend(j.get("images") or [])
                if isinstance(j.get("output"), list):
                    candidates.extend(j.get("output") or [])
                candidates.append(j)
                for item in candidates:
                    if not isinstance(item, dict):
                        continue
                    b64 = item.get("b64_json") or item.get("image_base64") or item.get("base64")
                    if b64:
                        if "," in b64 and b64.strip().startswith("data:"):
                            b64 = b64.split(",", 1)[1]
                        with contextlib.suppress(Exception):
                            return base64.b64decode(b64)
                    url2 = item.get("url") or item.get("image_url")
                    if isinstance(url2, dict):
                        url2 = url2.get("url")
                    if url2:
                        got = await _download_image_url_bytes(str(url2), timeout_s=float(COMET_IMAGE_GEN_TIMEOUT_S))
                        if got:
                            return got
            log.warning("Comet image generation did not return image. Last body: %s", last_body)
    except Exception as e:
        log.exception("Comet image generation failed: %s", e)
    return None


async def _generate_logo_image_bytes(prompt: str, brief: str) -> bytes | None:
    # 1) OpenAI/Luma route from older builds
    img = await _luma_generate_image_bytes(prompt)
    if img:
        return img
    # 2) Comet OpenAI-compatible image generation route
    img = await _comet_generate_image_bytes(prompt)
    if img:
        return img
    # 3) Guaranteed local fallback, so the user does not get a dead end
    return await asyncio.to_thread(_make_local_logo_png, brief)


async def _generate_business_logo(update: Update, context: ContextTypes.DEFAULT_TYPE, brief: str):
    prompt = (
        "Professional logo design, clean vector style, high-end brand identity, flat vector mark, no mockup, no watermark. "
        "Create a modern logo based on this Russian brief. Keep brand name readable if provided. "
        "Avoid small unreadable text. Square composition, transparent-background style if possible. Brief: " + (brief or "")
    )
    await update.effective_message.reply_text(
        "üé® –ó–∞–ø—É—Å–∫–∞—é —Å–æ–∑–¥–∞–Ω–∏–µ –ª–æ–≥–æ—Ç–∏–ø–∞. –ü—Ä–æ–±—É—é image-–ø—Ä–æ–≤–∞–π–¥–µ—Ä, –∞ –µ—Å–ª–∏ –æ–Ω –Ω–µ–¥–æ—Å—Ç—É–ø–µ–Ω ‚Äî —Å–æ–±–µ—Ä—É –∞–∫–∫—É—Ä–∞—Ç–Ω—ã–π –ª–æ–∫–∞–ª—å–Ω—ã–π PNG-–ª–æ–≥–æ—Ç–∏–ø, —á—Ç–æ–±—ã —Ñ—É–Ω–∫—Ü–∏—è –Ω–µ –ø–∞–¥–∞–ª–∞."
    )

    async def _go():
        img = await _generate_logo_image_bytes(prompt, brief)
        if not img:
            await update.effective_message.reply_text("–ù–µ —É–¥–∞–ª–æ—Å—å —Å–æ–∑–¥–∞—Ç—å –∏–∑–æ–±—Ä–∞–∂–µ–Ω–∏–µ. –ü—Ä–æ–≤–µ—Ä—å—Ç–µ OPENAI_IMAGE_KEY –∏–ª–∏ COMET_API_KEY.")
            return False
        try:
            await update.effective_message.reply_photo(photo=img, caption="üé® –õ–æ–≥–æ—Ç–∏–ø –≥–æ—Ç–æ–≤ ‚úÖ")
        except Exception:
            bio = BytesIO(img); bio.name = _safe_filename("logo", "png")
            await update.effective_message.reply_document(InputFile(bio), caption="üé® –õ–æ–≥–æ—Ç–∏–ø –≥–æ—Ç–æ–≤ ‚úÖ")
        return True

    await _try_pay_then_do(
        update, context, update.effective_user.id,
        "img", IMG_COST_USD, _go,
        remember_kind="business_logo",
        remember_payload={"brief": brief},
    )



# ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ Presentation / Catalog Studio v86 integration ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ‚îÄ
_PRESENTATION_STUDIO_INSTANCE = None


async def _presentation_llm_call(update: Update, prompt: str) -> str:
    return await ask_openai_text(
        prompt,
        user_id=update.effective_user.id if update.effective_user else None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
        extra_system=(
            "–¢—ã —Ä–∞–€]5◊¶ÚµÎ(ö+my÷Ê∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	¯˘í	≠ΩçÚ=ÌÌB"¬6∆∆&6µˆFF“'VFóC¶&sß&ˆˆb"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	¯˙"	ÌMçÚç}›]"¬6∆∆&6µˆFF“'VFóC¶&s¶ˆffñ6R"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.)™¢	]ΩΩí-=Mçù›ΩíMÌ“"¬6∆∆&6µˆFF“'VFóC¶&sßvÜóFR"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.)»ﬁ˚àÚ
-ÌíMÌ“"¬6∆∆&6µˆFF“'VFóC¶&s¶7W7Fˆ“"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.*»^˚àÚ	›}B"¬6∆∆&6µˆFF“'VFóC¶&6≤"ï“¿¢“ê††¶FVb˜6WE˜vóFñÊu˜&V÷˜fV&rÜ6ˆÁFWáBì†¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊu˜Ü˜Fıˆf˜"%““'&V÷˜fV&r ¢6ˆÁFWáBÁW6W%ˆFF≤'Ü˜Fıˆf∆˜r%““'&V÷˜fV&r ††¶FVbˆó5˜vóFñÊu˜&V÷˜fV&rÜ6ˆÁFWáBí”‚&ˆˆ√†¢&WGW&‚&ˆˆ¬Ü6ˆÁFWáBÊBÜ6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜Ü˜Fıˆf˜""í”“'&V÷˜fV&r"˜"6ˆÁFWáBÁW6W%ˆFFÊvWBÇ'Ü˜Fıˆf∆˜r"í”“'&V÷˜fV&r"íê††¶FVbˆ6∆V%˜&V÷˜fV&u˜vóBÜ6ˆÁFWáBì†¢ñbÊ˜B6ˆÁFWáC†¢&WGW&‡¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜Ü˜Fıˆf˜""í”“'&V÷˜fV&r#†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜Ü˜Fıˆf˜""¬ÊˆÊRê¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ'Ü˜Fıˆf∆˜r"í”“'&V÷˜fV&r#†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç'Ü˜Fıˆf∆˜r"¬ÊˆÊRê††¶FVb˜6WE˜vóFñÊu˜&W∆6V&rÜ6ˆÁFWáB¬&ˆ◊C¢7G"“""ì†¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊu˜Ü˜Fıˆf˜"%““'&W∆6V&r ¢6ˆÁFWáBÁW6W%ˆFF≤'Ü˜Fıˆf∆˜r%““'&W∆6V&r ¢ñb&ˆ◊C†¢6ˆÁFWáBÁW6W%ˆFF≤'&W∆6V&u˜&ˆ◊B%““&ˆ◊BÁ7G&óÇê††¶FVb˜6WE˜&W∆6V&u˜vóE˜FWáBÜ6ˆÁFWáBì†¢6ˆÁFWáBÁW6W%ˆFF≤'&W∆6V&u˜vóE˜FWáB%““# ††¶FVbˆó5˜&W∆6V&u˜vóE˜FWáBÜ6ˆÁFWáBí”‚&ˆˆ√†¢&WGW&‚&ˆˆ¬Ü6ˆÁFWáBÊB6ˆÁFWáBÁW6W%ˆFFÊvWBÇ'&W∆6V&u˜vóE˜FWáB"íê††¶FVbˆó5˜vóFñÊu˜&W∆6V&rÜ6ˆÁFWáBí”‚&ˆˆ√†¢&WGW&‚&ˆˆ¬Ü6ˆÁFWáBÊBÜ6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜Ü˜Fıˆf˜""í”“'&W∆6V&r"˜"6ˆÁFWáBÁW6W%ˆFFÊvWBÇ'Ü˜Fıˆf∆˜r"í”“'&W∆6V&r"íê††¶FVbˆ6∆V%˜&W∆6V&u˜vóBÜ6ˆÁFWáBì†¢ñbÊ˜B6ˆÁFWáC†¢&WGW&‡¢f˜"∂Wíñ‚Ç'&W∆6V&u˜vóE˜FWáB"¬'&W∆6V&u˜&ˆ◊B"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ü∂Wí¬ÊˆÊRê¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜Ü˜Fıˆf˜""í”“'&W∆6V&r#†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜Ü˜Fıˆf˜""¬ÊˆÊRê¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ'Ü˜Fıˆf∆˜r"í”“'&W∆6V&r#†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç'Ü˜Fıˆf∆˜r"¬ÊˆÊRê††¶FVbˆó5˜&V÷˜fUˆ&u˜&WVW7BáFWáC¢7G"í”‚&ˆˆ√†¢F¬“áFWáB˜"""íÊ∆˜vW"Çê¢&WGW&‚ÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-=MΩÇMÌ“"¬-=MΩç-¬MÌ“"¬-=]ÇMÌ“"¬-=-¬MÌ“"¬'&V÷˜fV&r"¬'&V÷˜fR&6∂w&˜VÊB"¬-˝Ì}}›ΩíMÌ“"¬-]rMÌ›"íê††¶FVbˆó5˜&W∆6Uˆ&u˜&WVW7BáFWáC¢7G"í”‚&ˆˆ√†¢F¬“áFWáB˜"""íÊ∆˜vW"Çê¢&WGW&‚ÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-}Õ]›ÇMÌ“"¬-}Õ]›ç-¬MÌ“"¬-˝ÌÕ]›˝íMÌ“"¬-˝ÌÕ]›˝-¬MÌ“"¬'&W∆6V&r"¬'&W∆6R&6∂w&˜VÊB"¬-MÌ“›"¬-M==ÌíMÌ“"íê††¶FVbˆ&uˆ∂ñÊEˆg&ˆ’˜FWáBáFWáC¢7G"í”‚GW∆U∑7G"¬7G%”†¢F¬“áFWáB˜"""íÊ∆˜vW"Çê¢ñbÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-˝Ω˝b"¬-ÕÌR"¬-Ì≠]“"¬&&V6Ç"¬&6ˆ7B"¬'6Ü˜&R"íì†¢&WGW&‚&&V6Ç"¬FWá@¢ñbÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-=Ì≤"¬-=Ì"¬&÷˜VÁFñ‚"¬&«2"¬-ΩÕÚ"íì†¢&WGW&‚&÷˜VÁFñÁ2"¬FWá@¢ñbÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-≠Ωç"¬-=ÌÌB"¬-›]Ì≠]"¬'&ˆˆgF˜"¬&6óGí"¬'6∑ñ∆ñÊR"¬--]"íì†¢&WGW&‚'&ˆˆb"¬FWá@¢ñbÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-ÌMç"¬-≠ç›]""¬&'W6ñÊW72"¬&ˆffñ6R"¬&6˜v˜&∂ñÊr"¬-˝]]=Ì-Ì"íì†¢&WGW&‚&ˆffñ6R"¬FWá@¢ñbÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-˝çÌM"¬-Ω]"¬-}]Ω]›¬"¬&ÊGW&R"¬&f˜&W7B"¬'&≤"¬-˝¢"íì†¢&WGW&‚&ÊGW&R"¬FWá@¢ñbÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-]ΩΩí"¬'vÜóFR"¬'7GVFñÚ"¬--=B"íì†¢&WGW&‚'vÜóFR"¬FWá@¢ñbÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-}]›Ωí"¬-}›Ωí"¬&&∆6≤"íì†¢&WGW&‚&&∆6≤"¬FWá@¢ñbÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-}Õ≤"¬&&«W""¬-ΩÌ"íì†¢&WGW&‚&&«W""¬FWá@¢&WGW&‚&7W7Fˆ“"¬FWá@††¶FVb˜6fUˆ#cFFV6ˆFUˆñ÷vRáf«VS¢7G"í”‚'óFW2¬ÊˆÊS†¢ñbÊ˜Bf«VR˜"Ê˜Bó6ñÁ7FÊ6Ráf«VR¬7G"ì†¢&WGW&‚ÊˆÊP¢2“f«VRÁ7G&óÇê¢ñb2Á7F'G7vóFÇÇ&FF¢"íÊB"¬"ñ‚3†¢2“2Á7∆óBÇ"¬"¬ï≥–¢G'ì†¢&WGW&‚&6ScBÊ#cFFV6ˆFRá2¬f∆ñFFS‘f«6Rê¢WÜ6WBWÜ6WFñˆ„†¢&WGW&‚ÊˆÊP††¶FVbˆfñÊEˆfó'7Eˆñ÷vUˆ#cBÜˆ&¢í”‚'óFW2¬ÊˆÊS†¢ñbó6ñÁ7FÊ6RÜˆ&¢¬Fñ7Bì†¢2vV÷ñÊíÚÊÊÚ&ÊÊvVÊW&FT6ˆÁFVÁB&WGW&Á26ÊFñFFW5µ“Ê6ˆÁFVÁBÁ'G5µ“ÊñÊ∆ñÊTFFˆñÊ∆ñÊUˆFFÊFF‡¢f˜"∂Wíñ‚Ç&ñÊ∆ñÊUˆFF"¬&ñÊ∆ñÊTFF"ì†¢b“ˆ&¢ÊvWBÜ∂Wíê¢ñbó6ñÁ7FÊ6Ráb¬Fñ7Bì†¢÷ñ÷R“7G"ábÊvWBÇ&÷ñ÷U˜GóR"í˜"bÊvWBÇ&÷ñ÷UGóR"í˜"""íÊ∆˜vW"Çê¢ñb÷ñ÷RÁ7F'G7vóFÇÇ&ñ÷vRÚ"í˜"bÊvWBÇ&FF"ì†¢˜WB“˜6fUˆ#cFFV6ˆFUˆñ÷vRábÊvWBÇ&FF"í˜"bÊvWBÇ&'óFW5ˆ&6ScB"í˜"bÊvWBÇ&'óFW4&6ScB"íê¢ñb˜WC†¢&WGW&‚˜W@¢f˜"∂Wíñ‚Ç&#cEˆß6ˆ‚"¬&ñ÷vUˆ#cB"¬&ñ÷vR"¬'Êr"¬'&W7V«Eˆ#cB"¬&'óFW5ˆ&6ScB"¬&'óFW4&6ScB"ì†¢ñb∂Wíñ‚ˆ&£†¢˜WB“˜6fUˆ#cFFV6ˆFUˆñ÷vRÜˆ&¢ÊvWBÜ∂Wííê¢ñb˜WC†¢&WGW&‚˜W@¢f˜"bñ‚ˆ&¢Áf«VW2Çì†¢˜WB“ˆfñÊEˆfó'7Eˆñ÷vUˆ#cBábê¢ñb˜WC†¢&WGW&‚˜W@¢V∆ñbó6ñÁ7FÊ6RÜˆ&¢¬∆ó7Bì†¢f˜"bñ‚ˆ&£†¢˜WB“ˆfñÊEˆfó'7Eˆñ÷vUˆ#cBábê¢ñb˜WC†¢&WGW&‚˜W@¢&WGW&‚ÊˆÊP††¶FVbˆfñÊEˆfó'7Eˆñ÷vU˜W&¬Üˆ&¢í”‚7G#†¢ñbó6ñÁ7FÊ6RÜˆ&¢¬Fñ7Bì†¢f˜"∂Wíñ‚Ç'W&¬"¬&ñ÷vU˜W&¬"¬&˜WGWE˜W&¬"¬'&W7V«E˜W&¬"¬&F˜vÊ∆ˆE˜W&¬"¬&fñ∆U˜W&¬"ì†¢f¬“ˆ&¢ÊvWBÜ∂Wíê¢ñbó6ñÁ7FÊ6Ráf¬¬7G"íÊBf¬Á7F'G7vóFÇÇÇ&áGG¢ÚÚ"¬&áGG3¢ÚÚ"íì†¢&WGW&‚f¿¢ñbó6ñÁ7FÊ6Ráf¬¬Fñ7Bì†¢ÊW7FVB“f¬ÊvWBÇ'W&¬"ê¢ñbó6ñÁ7FÊ6RÜÊW7FVB¬7G"íÊBÊW7FVBÁ7F'G7vóFÇÇÇ&áGG¢ÚÚ"¬&áGG3¢ÚÚ"íì†¢&WGW&‚ÊW7FV@¢f˜"bñ‚ˆ&¢Áf«VW2Çì†¢W&¬“ˆfñÊEˆfó'7Eˆñ÷vU˜W&¬ábê¢ñbW&√†¢&WGW&‚W&¿¢V∆ñbó6ñÁ7FÊ6RÜˆ&¢¬∆ó7Bì†¢f˜"bñ‚ˆ&£†¢W&¬“ˆfñÊEˆfó'7Eˆñ÷vU˜W&¬ábê¢ñbW&√†¢&WGW&‚W&¿¢&WGW&‚" ††¶7ñÊ2FVbˆñ÷vUˆ'óFW5ˆg&ˆ’˜&W7ˆÁ6Rá&W7¢áGGÇÂ&W7ˆÁ6R¬6∆ñVÁC¢áGGÇ‰7ñÊ46∆ñVÁBí”‚'óFW2¬ÊˆÊS†¢7GóR“á&W7ÊÜVFW'2ÊvWBÇ&6ˆÁFVÁB◊GóR"í˜"""íÊ∆˜vW"Çê¢ñb7GóRÁ7F'G7vóFÇÇ&ñ÷vRÚ"íÊB&W7Ê6ˆÁFVÁC†¢&WGW&‚'óFW2á&W7Ê6ˆÁFVÁBê¢G'ì†¢ˆ&¢“&W7Êß6ˆ‚Çê¢WÜ6WBWÜ6WFñˆ„†¢&WGW&‚ÊˆÊP¢˜WB“ˆfñÊEˆfó'7Eˆñ÷vUˆ#cBÜˆ&¢ê¢ñb˜WC†¢&WGW&‚˜W@¢W&¬“ˆfñÊEˆfó'7Eˆñ÷vU˜W&¬Üˆ&¢ê¢ñbW&√†¢G'ì†¢'"“vóB6∆ñVÁBÊvWBáW&¬¬Fñ÷V˜WC‘$uı$T‘ıdUıDî‘TıUEı2ê¢'"Á&ó6Uˆf˜%˜7FGW2Çê¢ñb'"Ê6ˆÁFVÁC†¢&WGW&‚'óFW2á'"Ê6ˆÁFVÁBê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ&&6∂w&˜VÊB&W7V«BW&¬F˜vÊ∆ˆBfñ∆VC¢W2"¬Rê¢&WGW&‚ÊˆÊP††¶FVb˜&W&Uˆ'óFW5ˆf˜%˜&V÷&rÜñ÷uˆ'óFW3¢'óFW2í”‚'óFW3†¢"" ¢&VÊFW"7F'FW"ÕÌm]"=˝ç-ÕÚ"$“›ÌΩÕççRMÌ-‚‡¢	MΩÚ∆ˆ6¬&V÷&r=Õ]›Õç]¬Ωçç≠Ì¬≠=˝›ΩRç}Ìm]›çÚM‚$T‘$uÙ‘Öı4îDR‡¢"" ¢ñbñ÷vRó2ÊˆÊR˜"Ê˜B$T‘$uÙ‘Öı4îDR˜"$T‘$uÙ‘Öı4îDR√“†¢&WGW&‚ñ÷uˆ'óFW0¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2íê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ñ““ñ÷vT˜2ÊWÜñe˜G&Á7˜6RÜñ“ê¢r¬Ç“ñ“Á6ó¶P¢◊Ç“÷Çár¬Çê¢ñb◊Ç√“$T‘$uÙ‘Öı4îDS†¢&WGW&‚ñ÷uˆ'óFW0¢66∆R“$T‘$uÙ‘Öı4îDRÚf∆ˆBÜ◊Çê¢Ár¬ÊÇ“÷ÇÉ¬ñÁBár¢66∆Ríí¬÷ÇÉ¬ñÁBÜÇ¢66∆Ríê¢&W6◊∆R“vWFGG"Ññ÷vR¬%&W6◊∆ñÊr"¬ñ÷vRí‰ƒ‰5§ı0¢ñ““ñ“Ê6ˆÁfW'BÇ%$t""íÁ&W6ó¶RÇÜÁr¬ÊÇí¬&W6◊∆Rê¢˜WB“'óFW4îÚÇê¢ñ“Á6fRÜ˜WB¬f˜&÷C“$•Tr"¬V∆óGì”ìB¬˜Fñ÷ó¶S’G'VRê¢ˆ&uˆÊ˜FUˆW'&˜"Üb&∆ˆ6¬&V÷&rñÁWB&W6ó¶VB∑w◊á∂á“”Á∂Áw◊á∂Êá“"ê¢&WGW&‚˜WBÊvWGf«VRÇê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆ&uˆÊ˜FUˆW'&˜"Üb&∆ˆ6¬&V÷&r&W6ó¶R6∂óVC¢∂W“"ê¢&WGW&‚ñ÷uˆ'óFW0††¶FVbˆvWEˆ∆ˆ6≈˜&V÷&u˜6W76ñˆ‚Çì†¢v∆ˆ&¬ı$T‘$uı4U54îÙ‡¢ñb&V÷&u˜&V÷˜fRó2ÊˆÊS†¢ˆ&uˆÊ˜FUˆW'&˜"Üb'&V÷&rñ◊˜'Bfñ∆VC¢µ$T‘$uÙî’ı%EÙU%$ı'“"ê¢&WGW&‚ÊˆÊP¢ñb&V÷&uˆÊWu˜6W76ñˆ‚ó2ÊˆÊS†¢ˆ&uˆÊ˜FUˆW'&˜"Ç'&V÷&rÊÊWu˜6W76ñˆ‚ó2Ê˜Bfñ∆&∆R"ê¢&WGW&‚ÊˆÊP¢ñbı$T‘$uı4U54îÙ‚ó2Ê˜BÊˆÊS†¢&WGW&‚ı$T‘$uı4U54îÙ‡¢vóFÇı$T‘$uı4U54îÙÂÙƒÙ4≥†¢ñbı$T‘$uı4U54îÙ‚ó2Ê˜BÊˆÊS†¢&WGW&‚ı$T‘$uı4U54îÙ‡¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢˜2ÊVÁfó&ˆ‚Á6WFFVfV«BÇ%S$‰UEÙÑÙ‘R"¬S$‰UEÙÑÙ‘Rê¢˜2Ê÷∂VFó'2ÖS$‰UEÙÑÙ‘R¬WÜó7Eˆˆ≥’G'VRê¢˜2Ê÷∂VFó'2ÖÑDuÙ44ÑUÙÑÙ‘R¬WÜó7Eˆˆ≥’G'VRê¢∆7EˆWÜ2“" ¢f˜"÷ˆFV≈ˆÊ÷Rñ‚$T‘$uÙ‘ÙDT≈Ùdƒƒ$4µ3†¢G'ì†¢∆ˆrÊñÊfÚÇ$ñÊóFñ∆ó¶ñÊr∆ˆ6¬&V÷&r6W76ñˆ„¢÷ˆFV√“W2S$‰UEÙÑÙ‘S“W2"¬÷ˆFV≈ˆÊ÷R¬˜2ÊVÁfó&ˆ‚ÊvWBÇ%S$‰UEÙÑÙ‘R"íê¢ı$T‘$uı4U54îÙ‚“&V÷&uˆÊWu˜6W76ñˆ‚Ü÷ˆFV≈ˆÊ÷Rê¢∆ˆrÊñÊfÚÇ&∆ˆ6¬&V÷&r6W76ñˆ‚&VGì¢÷ˆFV√“W2"¬÷ˆFV≈ˆÊ÷Rê¢&WGW&‚ı$T‘$uı4U54îÙ‡¢WÜ6WBWÜ6WFñˆ‚2S†¢∆7EˆWÜ2“&W"ÜRê¢∆ˆrÁv&ÊñÊrÇ&∆ˆ6¬&V÷&r6W76ñˆ‚ñÊóBfñ∆VB÷ˆFV√“W3¢W2"¬÷ˆFV≈ˆÊ÷R¬Rê¢ˆ&uˆÊ˜FUˆW'&˜"Üb&∆ˆ6¬&V÷&r6W76ñˆ‚ñÊóBfñ∆VB÷ˆFV√◊∂÷ˆFV≈ˆÊ÷W”¢∂W“"ê¢ˆ&uˆÊ˜FUˆW'&˜"Üb&∆ˆ6¬&V÷&r6W76ñˆ‚VÊfñ∆&∆S¢∂∆7EˆWÜ7“"ê¢&WGW&‚ÊˆÊP†††¶7ñÊ2FVbˆ∆ˆ6≈˜&V÷&u˜&V÷˜fU˜7V'&ˆ6W72Üñ÷uˆ'óFW3¢'óFW2í”‚'óFW2¬ÊˆÊS†¢"" ¢	ç}ÌΩçÌ-››Ωí∆ˆ6¬&V÷&rv˜&∂W"‚	]ΩÇ&V÷&rˆˆÊÁá'VÁFñ÷R}-ç›]"˝Ç≠}ç-›çÄ¢çΩÇç›çmçΩç}mçÇÕÌM]ΩÇ¬Ì›Ì-›ÌíÌ"›R}-ç]#¢˝Ìm]=ç-]¬˝‚Fñ÷V˜WB‡¢"" ¢ñbÊ˜BƒÙ4≈ı$T‘$uÙT‰$ƒTB˜"&V÷&u˜&V÷˜fRó2ÊˆÊS†¢&WGW&‚ÊˆÊP¢ñbñ÷vRó2Ê˜BÊˆÊS†¢ñ÷uˆ'óFW2“˜&W&Uˆ'óFW5ˆf˜%˜&V÷&rÜñ÷uˆ'óFW2ê¢Fñ÷V˜WE˜2“÷ÇÉ#„¬f∆ˆBÑƒÙ4≈ı$T‘$uıDî‘TıUEı2˜"Éíê¢VÁb“˜2ÊVÁfó&ˆ‚Ê6˜íÇê¢VÁe≤%S$‰UEÙÑÙ‘R%““VÁbÊvWBÇ%S$‰UEÙÑÙ‘R"í˜"S$‰UEÙÑÙ‘R˜""˜F◊ÚÁS&ÊWB ¢VÁe≤%ÑDuÙ44ÑUÙÑÙ‘R%““VÁbÊvWBÇ%ÑDuÙ44ÑUÙÑÙ‘R"í˜"ÑDuÙ44ÑUÙÑÙ‘R˜""˜F◊ÚÊ66ÜR ¢VÁbÁ6WFFVfV«BÇ$Ù’ÙÂT’ıDÖ$TE2"¬#"ê¢VÁbÁ6WFFVfV«BÇ$’ƒ4Ù‰dîtDï""¬"˜F◊ÚÊ÷G∆˜F∆ñ""ê¢f˜"Bñ‚ÜVÁe≤%S$‰UEÙÑÙ‘R%“¬VÁe≤%ÑDuÙ44ÑUÙÑÙ‘R%“¬VÁe≤$’ƒ4Ù‰dîtDï"%“ì†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢˜2Ê÷∂VFó'2ÜB¬WÜó7Eˆˆ≥’G'VRê†¢v˜&∂W%ˆ6ˆFR“"rrp¶ñ◊˜'B˜2¬7ó0¶g&ˆ“FÜ∆ñ"ñ◊˜'BFÄßG'ì†¢g&ˆ“&V÷&rñ◊˜'B&V÷˜fR¬ÊWu˜6W76ñˆ‡¶WÜ6WBWÜ6WFñˆ‚2S†¢&ñÁBÜb$î’ı%EÙU%$ı#¢∂W“"¬fñ∆S◊7ó2Á7FFW'"ê¢7ó2ÊWÜóBÉê¶÷ˆFV¬“˜2ÊVÁfó&ˆ‚ÊvWBÇ%$T‘$uÙ‘ÙDT¬"¬'S&ÊWG"í˜"'S&ÊWG ¶ñÁ¬˜WG“7ó2Ê&we≥“¬7ó2Ê&we≥%–ßG'ì†¢FÇÜ˜2ÊVÁfó&ˆ‚ÊvWBÇ%S$‰UEÙÑÙ‘R"¬"˜F◊ÚÁS&ÊWB"ííÊ÷∂Fó"á&VÁG3’G'VR¬WÜó7Eˆˆ≥’G'VRê¢FÇÜ˜2ÊVÁfó&ˆ‚ÊvWBÇ%ÑDuÙ44ÑUÙÑÙ‘R"¬"˜F◊ÚÊ66ÜR"ííÊ÷∂Fó"á&VÁG3’G'VR¬WÜó7Eˆˆ≥’G'VRê¢FF“FÇÜñÁíÁ&VEˆ'óFW2Çê¢6W72“ÊWu˜6W76ñˆ‚Ü÷ˆFV¬ê¢G'ì†¢˜WB“&V÷˜fRÜFF¬6W76ñˆ„◊6W72¬f˜&6U˜&WGW&Âˆ'óFW3’G'VRê¢WÜ6WBGóTW'&˜#†¢˜WB“&V÷˜fRÜFF¬6W76ñˆ„◊6W72ê¢FÇÜ˜WGíÁw&óFUˆ'óFW2Ü˜WBê¶WÜ6WBWÜ6WFñˆ‚2S†¢&ñÁBÜb%$T‘$uıtı$¥U%ÙU%$ı#¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"¬fñ∆S◊7ó2Á7FFW'"ê¢7ó2ÊWÜóBÉ"ê¢rrp¢ñÂ˜FÇ“˜WE˜FÇ“ÊˆÊP¢G'ì†¢vóFÇFV◊fñ∆R‰Ê÷VEFV◊˜&'îfñ∆Rá&VfóÉ“'&V÷&uˆñÂÚ"¬7VffóÉ“"Êßr"¬FV∆WFS‘f«6Rí2c†¢bÁw&óFRÜñ÷uˆ'óFW2ê¢ñÂ˜FÇ“bÊÊ÷P¢fB¬˜WE˜FÇ“FV◊fñ∆RÊ÷∑7FV◊á&VfóÉ“'&V÷&uˆ˜WEÚ"¬7VffóÉ“"ÁÊr"ê¢˜2Ê6∆˜6RÜfBê¢&ˆ2“vóB7ñÊ6ñÚÊ7&VFU˜7V'&ˆ6W75ˆWÜV2Ä¢7ó2ÊWÜV7WF&∆R¬"÷2"¬v˜&∂W%ˆ6ˆFR¬ñÂ˜FÇ¬˜WE˜FÇ¿¢7FF˜WC÷7ñÊ6ñÚÁ7V'&ˆ6W72ÂïR¿¢7FFW'#÷7ñÊ6ñÚÁ7V'&ˆ6W72ÂïR¿¢VÁc÷VÁb¿¢ê¢G'ì†¢7FF˜WB¬7FFW'"“vóB7ñÊ6ñÚÁvóEˆf˜"á&ˆ2Ê6ˆ÷◊VÊñ6FRÇí¬Fñ÷V˜WC◊Fñ÷V˜WE˜2ê¢WÜ6WB7ñÊ6ñÚÂFñ÷V˜WDW'&˜#†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢&ˆ2Ê∂ñ∆¬Çê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóB&ˆ2ÁvóBÇê¢ˆ&uˆÊ˜FUˆW'&˜"Üb&∆ˆ6¬&V÷&r7V'&ˆ6W72Fñ÷V˜WBgFW"∑Fñ÷V˜WE˜3¢„g◊2"ê¢&WGW&‚ÊˆÊP¢ñb&ˆ2Á&WGW&Ê6ˆFR“†¢◊6r“á7FFW'"˜"7FF˜WB˜""""íÊFV6ˆFRÇ'WFb”Ç"¬'&W∆6R"ï≥£É–¢ˆ&uˆÊ˜FUˆW'&˜"Üb&∆ˆ6¬&V÷&r7V'&ˆ6W72fñ∆VB&3◊∑&ˆ2Á&WGW&Ê6ˆFW”¢∂◊6w“"ê¢&WGW&‚ÊˆÊP¢ñbÊ˜B˜WE˜FÇ˜"Ê˜B˜2ÁFÇÊWÜó7G2Ü˜WE˜FÇí˜"˜2ÁFÇÊvWG6ó¶RÜ˜WE˜FÇí¬S#†¢ˆ&uˆÊ˜FUˆW'&˜"Ç&∆ˆ6¬&V÷&r7V'&ˆ6W72&ˆGV6VBV◊Gí˜WGWB"ê¢&WGW&‚ÊˆÊP¢vóFÇ˜V‚Ü˜WE˜FÇ¬'&""í2c†¢&WGW&‚bÁ&VBÇê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆ&uˆÊ˜FUˆW'&˜"Üb&∆ˆ6¬&V÷&r7V'&ˆ6W72WÜ6WFñˆ„¢∂W“"ê¢∆ˆrÁv&ÊñÊrÇ&∆ˆ6¬&V÷&r7V'&ˆ6W72WÜ6WFñˆ„¢W2"¬Rê¢&WGW&‚ÊˆÊP¢fñÊ∆«ì†¢f˜"FÇñ‚ÜñÂ˜FÇ¬˜WE˜FÇì†¢ñbFÉ†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢˜2Á&V÷˜fRáFÇê†¶FVbˆ∆ˆ6≈˜&V÷&u˜&V÷˜fU˜7ñÊ2Üñ÷uˆ'óFW3¢'óFW2í”‚'óFW3†¢ñ÷uˆ'óFW2“˜&W&Uˆ'óFW5ˆf˜%˜&V÷&rÜñ÷uˆ'óFW2ê¢6W76ñˆ‚“ˆvWEˆ∆ˆ6≈˜&V÷&u˜6W76ñˆ‚Çê¢ñb6W76ñˆ‚ó2Ê˜BÊˆÊS†¢G'ì†¢&WGW&‚&V÷&u˜&V÷˜fRÜñ÷uˆ'óFW2¬6W76ñˆ„◊6W76ñˆ‚¬f˜&6U˜&WGW&Âˆ'óFW3’G'VRê¢WÜ6WBGóTW'&˜#†¢&WGW&‚&V÷&u˜&V÷˜fRÜñ÷uˆ'óFW2¬6W76ñˆ„◊6W76ñˆ‚ê¢G'ì†¢&WGW&‚&V÷&u˜&V÷˜fRÜñ÷uˆ'óFW2¬f˜&6U˜&WGW&Âˆ'óFW3’G'VRê¢WÜ6WBGóTW'&˜#†¢&WGW&‚&V÷&u˜&V÷˜fRÜñ÷uˆ'óFW2ê††¶7ñÊ2FVbˆ∆ˆ6≈˜&V÷&u˜&V÷˜fUˆ'óFW2Üñ÷uˆ'óFW3¢'óFW2í”‚'óFW2¬ÊˆÊS†¢ñbÊ˜BƒÙ4≈ı$T‘$uÙT‰$ƒTC†¢&WGW&‚ÊˆÊP¢ñb&V÷&u˜&V÷˜fRó2ÊˆÊS†¢∆ˆrÁv&ÊñÊrÇ&∆ˆ6¬&V÷&ró2Ê˜Bfñ∆&∆S¢W2"¬$T‘$uÙî’ı%EÙU%$ı"ê¢&WGW&‚ÊˆÊP†¢ñbƒÙ4≈ı$T‘$uı5T%$Ù4U53†¢&WGW&‚vóBˆ∆ˆ6≈˜&V÷&u˜&V÷˜fU˜7V'&ˆ6W72Üñ÷uˆ'óFW2ê†¢G'ì†¢&WGW&‚vóB7ñÊ6ñÚÁvóEˆf˜"Ä¢7ñÊ6ñÚÁFı˜Fá&VBÖˆ∆ˆ6≈˜&V÷&u˜&V÷˜fU˜7ñÊ2¬ñ÷uˆ'óFW2í¿¢Fñ÷V˜WC‘ƒÙ4≈ı$T‘$uıDî‘TıUEı2¿¢ê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ&∆ˆ6¬&V÷&rfñ∆VC¢W2"¬Rê¢ˆ&uˆÊ˜FUˆW'&˜"Üb&∆ˆ6¬&V÷&rfñ∆VC¢∂W“"ê¢&WGW&‚ÊˆÊP††††¶FVb˜&W6ó¶Uˆñ÷vUˆ'óFW5ˆf˜%ˆ&uˆíÜñ÷uˆ'óFW3¢'óFW2¬÷Ö˜6ñFS¢ñÁB¬ÊˆÊR“ÊˆÊRí”‚GW∆U∂'óFW2¬7G"¬7G%”†¢""-
mçÕ]"-]ÌB˝]]BÜ˜F˜&ˆˆ“¬}-Ì≤›RΩÌ-ç-¬íıFV∆Vw&“Fñ÷V˜WB›ÌΩÕççRMÌ-‚‚"" ¢÷Ö˜6ñFR“ñÁBÜ÷Ö˜6ñFR˜"ÑıDı$ÙÙ’ÙîÂUEÙ‘Öı4îDR˜"cê¢÷ñ÷R“6Êñfeˆñ÷vUˆ÷ñ÷RÜñ÷uˆ'óFW2í˜"&ñ÷vRˆßVr ¢ñbñ÷vRó2ÊˆÊR˜"÷Ö˜6ñFR√“†¢WáB“"Êßr"ñb÷ñ÷R”“&ñ÷vRˆßVr"V«6RÇ"ÁÊr"ñb÷ñ÷R”“&ñ÷vR˜Êr"V«6R"ÁvV'"ê¢&WGW&‚ñ÷uˆ'óFW2¬b&ñ÷vW∂WáG“"¬÷ñ÷P¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2íê¢2	MΩÚç]ÌM›ΩRMÌ-‚˝Ì}}›Ì-¬›R›=m›¬Ü˜F˜&ˆˆ“¬-]›"‰rı$t$‡¢ñ““ñ÷vT˜2ÊWÜñe˜G&Á7˜6RÜñ“íñbñ÷vT˜2V«6Rñ–¢ñb÷ÇÜñ“Á6ó¶Rí‚÷Ö˜6ñFS†¢ñ“ÁFáV÷&Êñ¬ÇÜ÷Ö˜6ñFR¬÷Ö˜6ñFRí¬ñ÷vR‰ƒ‰5§ı2ê¢2•TrçΩÕ›‚=Õ]›Õç]"}Õ]}˝ÌÇ=≠Ì˝]"]˝Ω-›Ωíí‡¢ñbñ“Ê÷ˆFRÊ˜Bñ‚Ç%$t""¬$¬"ì†¢ñ““ñ“Ê6ˆÁfW'BÇ%$t""ê¢&ñÚ“'óFW4îÚÇê¢ñ“Á6fRÜ&ñÚ¬f˜&÷C“$•Tr"¬V∆óGì”ì"¬˜Fñ÷ó¶S’G'VR¬&ˆw&W76ófS’G'VRê¢&WGW&‚&ñÚÊvWGf«VRÇí¬&ñ÷vRÊßr"¬&ñ÷vRˆßVr ¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆ&uˆÊ˜FUˆW'&˜"Üb&ñÁWB&W6ó¶Rf˜"Ü˜F˜&ˆˆ“fñ∆VC¢∂W“"ê¢WáB“"Êßr"ñb÷ñ÷R”“&ñ÷vRˆßVr"V«6RÇ"ÁÊr"ñb÷ñ÷R”“&ñ÷vR˜Êr"V«6R"ÁvV'"ê¢&WGW&‚ñ÷uˆ'óFW2¬b&ñ÷vW∂WáG“"¬÷ñ÷P†¶7ñÊ2FVb˜Ü˜F˜&ˆˆ’ˆï˜&V÷˜fUˆ'óFW2Üñ÷uˆ'óFW3¢'óFW2í”‚'óFW2¬ÊˆÊS†¢""%Ü˜F˜&ˆˆ“&V÷˜fR&6∂w&˜VÊBí‚&WGW&Á2G&Á7&VÁB‰rı$t$'óFW2‚"" ¢ñbÊ˜BÑıDı$ÙÙ’ÙïÙ¥Uì†¢ˆ&uˆÊ˜FUˆW'&˜"Ç%Ü˜F˜&ˆˆ“í∂Wí÷ó76ñÊs¢6WBÑıDı$ÙÙ’ÙïÙ¥Uíñ‚&VÊFW"VÁfó&ˆÊ÷VÁB"ê¢&WGW&‚ÊˆÊP¢W∆ˆEˆ'óFW2¬W∆ˆEˆÊ÷R¬÷ñ÷R“˜&W6ó¶Uˆñ÷vUˆ'óFW5ˆf˜%ˆ&uˆíÜñ÷uˆ'óFW2¬ÑıDı$ÙÙ’ÙîÂUEÙ‘Öı4îDRê¢W&¬“b'µÑıDı$ÙÙ’Ù$4UıU$«◊µÑıDı$ÙÙ’ı$T‘ıdUıDá“ ¢ÜVFW'2“≤'Ç÷í÷∂Wí#¢ÑıDı$ÙÙ’ÙïÙ¥Uó–¢2Ü˜F˜&ˆˆ“˜c˜6Vv÷VÁB66WG2&V÷˜fRÊ&r÷6ˆ◊Fñ&∆RfñV∆G2‡¢FF“∞¢&f˜&÷B#¢ÑıDı$ÙÙ’Ùdı$‘B˜"'Êr"¿¢&6ÜÊÊV«2#¢ÑıDı$ÙÙ’Ù4Ñ‰‰T≈2˜"'&v&"¿¢'6ó¶R#¢ÑıDı$ÙÙ’ı4ï§R˜"&ÜB"¿¢&7&˜#¢ÑıDı$ÙÙ’Ù5$ı˜"&f«6R"¿¢&FW7ñ∆¬#¢ÑıDı$ÙÙ’ÙDU5îƒ¬˜"&f«6R"¿¢–¢Fñ÷V˜WB“áGGÇÂFñ÷V˜WBÖÑıDı$ÙÙ’ıDî‘TıUEı2¬6ˆÊÊV7C”#„ê¢G'ì†¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC◊Fñ÷V˜WB¬fˆ∆∆˜u˜&VFó&V7G3’G'VRí26∆ñVÁC†¢fñ∆W2“≤&ñ÷vUˆfñ∆R#¢áW∆ˆEˆÊ÷R¬W∆ˆEˆ'óFW2¬÷ñ÷Ró–¢"“vóB6∆ñVÁBÁ˜7BáW&¬¬ÜVFW'3÷ÜVFW'2¬FF÷FF¬fñ∆W3÷fñ∆W2ê¢ñb"Á7FGW5ˆ6ˆFR„“C†¢&ˆGí“á"ÁFWáB˜"""ï≥£ì–¢ˆ&uˆÊ˜FUˆW'&˜"Üb%Ü˜F˜&ˆˆ“ífñ∆VB7FGW3◊∑"Á7FGW5ˆ6ˆFW“&ˆGì◊∂&ˆGó“"ê¢∆ˆrÁv&ÊñÊrÇ%Ü˜F˜&ˆˆ“ífñ∆VB7FGW3“W2&ˆGì“W2"¬"Á7FGW5ˆ6ˆFR¬&ˆGíê¢&WGW&‚ÊˆÊP¢7GóR“á"ÊÜVFW'2ÊvWBÇ&6ˆÁFVÁB◊GóR"í˜"""íÊ∆˜vW"Çê¢ñbÊ˜B"Ê6ˆÁFVÁB˜"∆V‚á"Ê6ˆÁFVÁBí¬3†¢ˆ&uˆÊ˜FUˆW'&˜"Üb%Ü˜F˜&ˆˆ“í&WGW&ÊVBV◊Gí˜6Ü˜'B6ˆÁFVÁC¢∂∆V‚á"Ê6ˆÁFVÁB˜""rró“'óFW2"ê¢&WGW&‚ÊˆÊP¢ñbÜÊ˜B7GóRÁ7F'G7vóFÇÇ&ñ÷vRÚ"ííÊBá"Ê6ˆÁFVÁE≥£“Ê˜Bñ‚Ü"%«ÉÉí"¬"%«Üfb"íì†¢ˆ&uˆÊ˜FUˆW'&˜"Üb%Ü˜F˜&ˆˆ“í&WGW&ÊVBÊˆ‚÷ñ÷vR6ˆÁFVÁB◊GóS◊∂7GóW“&ˆGì◊≤á"ÁFWáB˜"rrï≥£s◊“"ê¢&WGW&‚ÊˆÊP¢&WGW&‚'óFW2á"Ê6ˆÁFVÁBê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆ&uˆÊ˜FUˆW'&˜"Üb%Ü˜F˜&ˆˆ“íWÜ6WFñˆ„¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢∆ˆrÁv&ÊñÊrÇ%Ü˜F˜&ˆˆ“íWÜ6WFñˆ„¢W2"¬Rê¢&WGW&‚ÊˆÊP††¶FVbˆÊ˜&÷∆ó¶U˜Ü˜Fı˜&W7V«BÜñ÷uˆ'óFW3¢'óFW2í”‚'óFW3†¢ñbñ÷vRó2ÊˆÊS†¢&WGW&‚ñ÷uˆ'óFW0¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2ííÊ6ˆÁfW'BÇ%$t""ê¢÷Ö˜6ñFR“ñÁBÑ$uÙıUEUEÙ‘Öı4îDR˜"cê¢ñb÷Ö˜6ñFR‚ÊB÷ÇÜñ“Á6ó¶Rí‚÷Ö˜6ñFS†¢ñ“ÁFáV÷&Êñ¬ÇÜ÷Ö˜6ñFR¬÷Ö˜6ñFRí¬ñ÷vR‰ƒ‰5§ı2ê¢&ñÚ“'óFW4îÚÇê¢ñ“Á6fRÜ&ñÚ¬f˜&÷C“$•Tr"¬V∆óGì”ì2¬˜Fñ÷ó¶S’G'VR¬&ˆw&W76ófS’G'VRê¢&WGW&‚&ñÚÊvWGf«VRÇê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆ&uˆÊ˜FUˆW'&˜"Üb&Ê˜&÷∆ó¶RÜ˜FÚ&W7V«Bfñ∆VC¢∂W“"ê¢&WGW&‚ñ÷uˆ'óFW0††¶FVbˆ6∆VÂˆ&u˜&ˆ◊E˜FWáBá&ˆ◊C¢7G"í”‚7G#†¢""%&V÷˜fRv˜&FñÊrFÜB÷∂W2íG&rfó6ñ&∆RÜˆÊRˆ÷ó'&˜"ñÁ7FVBˆbßW7B6V∆fñR÷∆ñ∂RW'7V7FófR‚"" ¢2“á&ˆ◊B˜"""íÁ7G&óÇê¢&W∆6V÷VÁG2“∞¢-›-]Ω]MÌ“#¢""¿¢--]Ω]MÌ›#¢""¿¢-›Õ-MÌ“#¢""¿¢-‚Õ-MÌ›#¢""¿¢--]Ω]MÌ“#¢-≠Õ]"¿¢-Õ-MÌ“#¢-≠Õ]"¿¢'ÜˆÊR#¢&6÷W&"¿¢'6÷'GÜˆÊR#¢&6÷W&"¿¢&÷ó'&˜"#¢""¿¢-}]≠Ω‚#¢""¿¢'6V∆fñR7Fñ6≤#¢""¿¢-]ΩMÇ›˝Ω≠#¢""¿¢–¢f˜"¬"ñ‚&W∆6V÷VÁG2ÊóFV◊2Çì†¢2“&RÁ7V"á&RÊW66RÜí¬"¬2¬f∆w3◊&R‰ît‰ı$T44Rê¢2“&RÁ7V"á"%«7≥"«“"¬""¬2íÁ7G&óÇ"¬„≤"ê¢&WGW&‚0††¶FVbˆ'Vñ∆Eˆ&6∂w&˜VÊE˜66VÊU˜&ˆ◊BÜ∂ñÊC¢7G"¬&ˆ◊C¢7G"“""í”‚7G#†¢∂ñÊB“Ü∂ñÊB˜"&7W7Fˆ“"íÊ∆˜vW"ÇíÁ7G&óÇê¢W6W%˜&ˆ◊B“ˆ6∆VÂˆ&u˜&ˆ◊E˜FWáBá&ˆ◊Bê¢&W6WEˆ÷“∞¢&&V6Ç#¢Ä¢'Ü˜F˜&V∆ó7Fñ2G&˜ñ6¬&V6Ç&6∂w&˜VÊB¬ÊGW&¬6ÊGí6Ü˜&R¬6∆V‚6VÜ˜&ó¶ˆ‚¬6∆“&«VRvFW"¬ ¢'6ˆgBvfW2¬&V∆ó7Fñ2Fñ∆ñváB¬&V∆ñWf&∆RG&fV¬◊Ü˜FÚF÷˜7ÜW&R¬˜V‚ó"¬VÊ6«WGFW&VBf˜&Vw&˜VÊB¬ ¢&ÊÚ'Vñ∆FñÊw2VÊ∆W72ÊGW&∆«íFó7FÁB ¢í¿¢&÷˜VÁFñÁ2#¢Ä¢'Ü˜F˜&V∆ó7Fñ2÷˜VÁFñ‚∆ÊG66R¬66VÊñ2«ñÊR˜"w&VV‚÷˜VÁFñÁ2¬˜V‚˜WFFˆ˜"fñWr¬&V∆ó7Fñ26∑í¬ ¢&ÊGW&¬Fñ∆ñváB¬F÷˜7ÜW&ñ2W'7V7FófR¬6∆V‚G&fV¬◊Ü˜FÚ6ˆ◊˜6óFñˆ‚¬ÊÚñÊFˆ˜"V∆V÷VÁG2 ¢í¿¢&ÊGW&R#¢Ä¢'Ü˜F˜&V∆ó7Fñ2&≤˜"ÊGW&R&6∂w&˜VÊB¬w&VVÊW'í¬G&VW2¬6ˆgBFWFÇ¬&V∆ó7Fñ2˜WFFˆ˜"Fñ∆ñváB¬ ¢&6∆“ÊGW&¬VÁfó&ˆÊ÷VÁB¬6∆V‚&V∆ñWf&∆R&6∂w&˜VÊB ¢í¿¢'&ˆˆb#¢Ä¢'Ü˜F˜&V∆ó7Fñ2&ˆˆgF˜FW'&6R˜"6óGí6∑ñ∆ñÊR¬V∆VvÁBW&&‚F÷˜7ÜW&R¬&V∆ó7Fñ2&6ÜóFV7GW&Rñ‚FÜRFó7FÊ6R¬ ¢&ÊGW&¬W'7V7FófR¬˜WFFˆ˜"∆ñváB¬6∆V‚÷ˆFW&‚&6∂w&˜VÊB ¢í¿¢&ˆffñ6R#¢Ä¢'Ü˜F˜&V∆ó7Fñ2&V÷óV“ˆffñ6R˜"'W6ñÊW72÷∆˜VÊvR&6∂w&˜VÊB¬÷ˆFW&‚ñÁFW&ñ˜"¬6∆V‚∆ñÊW2¬ ¢'6ˆgBFñ∆ñváB¬&V∆ó7Fñ2FWFÇ¬V∆VvÁB&ˆfW76ñˆÊ¬F÷˜7ÜW&R¬ÊÚ&ÊFˆ“vFvWG2ñ‚f˜&Vw&˜VÊB ¢í¿¢'vÜóFR#¢&6∆V‚vÜóFR7GVFñÚ&6∂w&˜VÊBvóFÇ6ˆgBWfV‚∆ñváBÊB&V∆ó7Fñ27V'F∆R6ÜF˜r"¿¢&&∆6≤#¢&6∆V‚F&≤7GVFñÚ&6∂w&˜VÊBvóFÇ6ˆgB6ˆÁG&ˆ∆∆VB∆ñváBÊB&V∆ó7Fñ27V'F∆R6ÜF˜r"¿¢&&«W"#¢'6ˆgBÊGW&¬&ˆ∂VÇ&6∂w&˜VÊBFW&ófVBg&ˆ“FÜR˜&ñvñÊ¬66VÊR¬&V∆ó7Fñ2∆VÁ2&«W"¬ÊÚWáG&ˆ&¶V7G2"¿¢&7W7Fˆ“#¢W6W%˜&ˆ◊B¿¢–¢66VÊR“W6W%˜&ˆ◊B˜"&W6WEˆ÷ÊvWBÜ∂ñÊBí˜"'Ü˜F˜&V∆ó7Fñ26∆V‚VÁfó&ˆÊ÷VÁB ¢&WGW&‚Ä¢$7&VFRˆÊ«íFÜR$4¥u$ıT‰B44T‰RvóFÇÊÚV˜∆R‚FÜó2ó27FW"ˆbGvÚ◊7FvRv˜&∂f∆˜s¢ ¢'FÜR7V&¶V7Bvñ∆¬&R6ˆ◊˜6óFVB∆FW"¬6Ú∆VfR6∆V‚g&VR76Rf˜"ˆÊRGV«BW'6ˆ‚ñ‚FÜR6VÁFW"f˜&Vw&˜VÊB‚ ¢%FÜR&W7V«B◊W7B&RÜ˜F˜&V∆ó7Fñ2¬&V∆ñWf&∆R¬ÊGW&¬W'7V7FófR¬WñR÷∆WfV¬6÷W&Êv∆R¬&V∆ó7Fñ2∆ñváB¬ ¢'&V¬◊v˜&∆BFWáGW&W2¬6ˆÜW&VÁBFWFÇÊB6∆V‚VÊ6«WGFW&VB6ˆ◊˜6óFñˆ‚‚ ¢b%66VÊR&WVW7C¢∑66VÊW“‚ ¢íÁ7G&óÇê††¶FVbˆ'Vñ∆Eˆ&6∂w&˜VÊEˆÊVvFófU˜&ˆ◊BÜ∂ñÊC¢7G"“""¬&ˆ◊C¢7G"“""í”‚7G#†¢'G2“∞¢&ÊÚV˜∆R"¬&ÊÚ˜'G&óG2"¬&ÊÚ6V∆fñR"¬&ÊÚf6R"¬&ÊÚÜÊG2"¬&ÊÚ&ˆGí"¿¢&ÊÚÜˆÊR"¬&ÊÚ6÷'GÜˆÊR"¬&ÊÚ67&VV‚"¬&ÊÚ÷ó'&˜""¬&ÊÚ6V∆fñR7Fñ6≤"¿¢&ÊÚ&∆6≤ÊV¬"¬&ÊÚ∂ñ˜6≤"¬&ÊÚv∆¬FWfñ6R"¬&ÊÚ&ÊFˆ“ñÊFˆ˜"'Fñf7B"¿¢&ÊÚGW∆ñ6FRˆ&¶V7G2"¬&ÊÚFWáB"¬&ÊÚvFW&÷&≤"¬&ÊÚ∆ˆvÚ"¬&ÊÚ6'Fˆˆ‚"¿¢&ÊÚñÁFñÊr"¬&ÊÚñ∆«W7G&Fñˆ‚"¬&ÊÚÊñ÷R"¬&ÊÚ4tí"¬&ÊÚ6B&VÊFW" ¢–¢∂ñÊB“Ü∂ñÊB˜"""íÊ∆˜vW"ÇíÁ7G&óÇê¢ñb∂ñÊB”“&&V6Ç#†¢'G2≥“≤&ÊÚ6Ê˜r"¬&ÊÚ÷˜VÁFñÁ2ñ‚f˜&Vw&˜VÊB"¬&ÊÚˆffñ6R%–¢V∆ñb∂ñÊB”“&÷˜VÁFñÁ2#†¢'G2≥“≤&ÊÚ&V6Ç"¬&ÊÚˆ6V‚"¬&ÊÚG&˜ñ6¬∆“G&VW2%–¢V∆ñb∂ñÊB”“&ˆffñ6R#†¢'G2≥“≤&ÊÚ&V6Ç"¬&ÊÚ÷˜VÁFñÁ2"¬&ÊÚ&ÊFˆ“FWfñ6R6∆˜6RFÚ6÷W&%–¢&WGW&‚"¬"Ê¶ˆñ‚ÜFñ7BÊg&ˆ÷∂Wó2á'G2íê††¶FVbˆ'Vñ∆E˜6V∆fñUˆ&6∂w&˜VÊE˜&ˆ◊BÜ∂ñÊC¢7G"¬&ˆ◊C¢7G"“""í”‚7G#†¢2∆Vv7íÜV«W"∂WBf˜"6ˆ◊Fñ&ñ∆óGíˆFV'Vr‡¢66VÊR“ˆ'Vñ∆Eˆ&6∂w&˜VÊE˜66VÊU˜&ˆ◊BÜ∂ñÊB¬&ˆ◊Bê¢ÊVvFófR“ˆ'Vñ∆Eˆ&6∂w&˜VÊEˆÊVvFófU˜&ˆ◊BÜ∂ñÊB¬&ˆ◊Bê¢&WGW&‚Ä¢$vVÊW&FRˆÊ«íÊWr&6∂w&˜VÊBÊB∂VWFÜR˜&ñvñÊ¬÷ñ‚7V&¶V7B6ˆ◊∆WFV«íVÊ6ÜÊvVC¢ ¢&FÚÊ˜B«FW"FÜRf6R¬Üó"¬6∆˜FÜW2¬&ˆGí¬˜6R¬&˜˜'FñˆÁ2˜"6∂ñ‚FWáGW&R‚ ¢≤66VÊR≤"fˆñC¢"≤ÊVvFófP¢íÁ7G&óÇê††¶FVb˜6Ü˜V∆E˜W6U˜Ü˜F˜&ˆˆ’ˆïˆ&6∂w&˜VÊBÜ∂ñÊC¢7G"¬&ˆ◊C¢7G"“""í”‚&ˆˆ√†¢2ñ‚&ˆGV7Fñˆ‚vRÊ˜r&VfW"7G&ñ7BGvÚ◊7FvRóV∆ñÊS¢&V÷˜fR&6∂w&˜VÊB”‚'Vñ∆B˜6V∆V7BÊWr&6∂w&˜VÊB”‚6ˆ◊˜6óFR‡¢2Ü˜F˜&ˆˆ“VFóBó2∂WBˆÊ«í2‚˜FñˆÊ¬FV'VrFÇÊBó2Fó6&∆VBf˜"&W6WG2'íFVfV«B‡¢ñbÊ˜BÑıDı$ÙÙ’ÙTDïEÙT‰$ƒTB˜"Ê˜BÑıDı$ÙÙ’ÙïÙ¥Uì†¢&WGW&‚f«6P¢&WGW&‚f«6P††¶7ñÊ2FVb˜Ü˜F˜&ˆˆ’ˆïˆVFóEˆ&6∂w&˜VÊEˆ'óFW2Üñ÷uˆ'óFW3¢'óFW2¬∂ñÊC¢7G"“&7W7Fˆ“"¬&ˆ◊C¢7G"“""í”‚'óFW2¬ÊˆÊS†¢""$∆Vv7íFó&V7BíVFóBFÇ‚∂WBf˜"˜FñˆÊ¬FñvÊ˜7Fñ72¬Ê˜BW6VB'íFÜRFVfV«BGvÚ◊7FvR&ˆGV7Fñˆ‚óV∆ñÊR‚"" ¢ñbÊ˜BÑıDı$ÙÙ’ÙïÙ¥Uì†¢ˆ&uˆÊ˜FUˆW'&˜"Ç%Ü˜F˜&ˆˆ“í∂Wí÷ó76ñÊrf˜"í&6∂w&˜VÊC¢6WBÑıDı$ÙÙ’ÙïÙ¥Uíñ‚&VÊFW"VÁfó&ˆÊ÷VÁB"ê¢&WGW&‚ÊˆÊP¢ñbÊ˜BÑıDı$ÙÙ’ÙTDïEÙT‰$ƒTC†¢ˆ&uˆÊ˜FUˆW'&˜"Ç%Ü˜F˜&ˆˆ“í&6∂w&˜VÊBó2Fó6&∆VB'íÑıDı$ÙÙ’ÙTDïEÙT‰$ƒTC”"ê¢&WGW&‚ÊˆÊP¢W∆ˆEˆ'óFW2¬W∆ˆEˆÊ÷R¬÷ñ÷R“˜&W6ó¶Uˆñ÷vUˆ'óFW5ˆf˜%ˆ&uˆíÜñ÷uˆ'óFW2¬ÑıDı$ÙÙ’ÙîÂUEÙ‘Öı4îDRê¢W&¬“b'µÑıDı$ÙÙ’ÙTDïEÙ$4UıU$«◊µÑıDı$ÙÙ’ÙTDïEıDá“ ¢ÜVFW'2“≤'Ç÷í÷∂Wí#¢ÑıDı$ÙÙ’ÙïÙ¥Uó–¢&u˜&ˆ◊B“ˆ'Vñ∆E˜6V∆fñUˆ&6∂w&˜VÊE˜&ˆ◊BÜ∂ñÊB¬&ˆ◊Bê¢FF“∞¢'&VfW&VÊ6T&˜Ç#¢&˜&ñvñÊƒñ÷vR"¿¢&&6∂w&˜VÊBÁ&ˆ◊B#¢&u˜&ˆ◊B¿¢&&6∂w&˜VÊBÊWáÊE&ˆ◊BÊ÷ˆFR#¢ÑıDı$ÙÙ’ÙTDïEÙUÖ‰Eı$Ù’EÙ‘ÙDR˜"&íÊÊWfW""¿¢–¢ñbÑıDı$ÙÙ’ÙTDïEÙ‰TtDïdUı$Ù’C†¢FF≤&&6∂w&˜VÊBÊÊVvFófU&ˆ◊B%““ÑıDı$ÙÙ’ÙTDïEÙ‰TtDïdUı$Ù’@¢Fñ÷V˜WB“áGGÇÂFñ÷V˜WBÖÑıDı$ÙÙ’ÙTDïEıDî‘TıUEı2¬6ˆÊÊV7C”#„ê¢G'ì†¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC◊Fñ÷V˜WB¬fˆ∆∆˜u˜&VFó&V7G3’G'VRí26∆ñVÁC†¢fñ∆W2“≤&ñ÷vTfñ∆R#¢áW∆ˆEˆÊ÷R¬W∆ˆEˆ'óFW2¬÷ñ÷Ró–¢"“vóB6∆ñVÁBÁ˜7BáW&¬¬ÜVFW'3÷ÜVFW'2¬FF÷FF¬fñ∆W3÷fñ∆W2ê¢ñb"Á7FGW5ˆ6ˆFR„“C†¢&ˆGí“á"ÁFWáB˜"""ï≥£ì–¢ˆ&uˆÊ˜FUˆW'&˜"Üb%Ü˜F˜&ˆˆ“VFóBífñ∆VB7FGW3◊∑"Á7FGW5ˆ6ˆFW“&ˆGì◊∂&ˆGó“"ê¢∆ˆrÁv&ÊñÊrÇ%Ü˜F˜&ˆˆ“VFóBífñ∆VB7FGW3“W2&ˆGì“W2"¬"Á7FGW5ˆ6ˆFR¬&ˆGíê¢&WGW&‚ÊˆÊP¢7GóR“á"ÊÜVFW'2ÊvWBÇ&6ˆÁFVÁB◊GóR"í˜"""íÊ∆˜vW"Çê¢ñb7GóRÁ7F'G7vóFÇÇ&ñ÷vRÚ"íÊB"Ê6ˆÁFVÁBÊB∆V‚á"Ê6ˆÁFVÁBí‚3†¢&WGW&‚'óFW2á"Ê6ˆÁFVÁBê¢˜WB“vóBˆñ÷vUˆ'óFW5ˆg&ˆ’˜&W7ˆÁ6Rá"¬6∆ñVÁBê¢ñb˜WC†¢&WGW&‚˜W@¢ˆ&uˆÊ˜FUˆW'&˜"Üb%Ü˜F˜&ˆˆ“VFóBí&WGW&ÊVBÊˆ‚÷ñ÷vR6ˆÁFVÁB◊GóS◊∂7GóW“&ˆGì◊≤á"ÁFWáB˜"rrï≥£s◊“"ê¢&WGW&‚ÊˆÊP¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆ&uˆÊ˜FUˆW'&˜"Üb%Ü˜F˜&ˆˆ“VFóBíWÜ6WFñˆ„¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢∆ˆrÁv&ÊñÊrÇ%Ü˜F˜&ˆˆ“VFóBíWÜ6WFñˆ„¢W2"¬Rê¢&WGW&‚ÊˆÊP††¶7ñÊ2FVb˜&V÷˜fV&uˆï˜&V÷˜fUˆ'óFW2Üñ÷uˆ'óFW3¢'óFW2í”‚'óFW2¬ÊˆÊS†¢""$ˆffñ6ñ¬&V÷˜fRÊ&r÷6ˆ◊Fñ&∆Rí&ñ÷'íFÇ‚&WGW&Á2G&Á7&VÁB‰r'óFW2‚"" ¢ñbÊ˜B$T‘ıdUÙ$uÙïÙ¥Uì†¢ˆ&uˆÊ˜FUˆW'&˜"Ç'&V÷˜fRÊ&rí∂Wí÷ó76ñÊs¢6WB$T‘ıdUÙ$uÙïÙ¥Uíñ‚&VÊFW"VÁfó&ˆÊ÷VÁB"ê¢&WGW&‚ÊˆÊP¢÷ñ÷R“6Êñfeˆñ÷vUˆ÷ñ÷RÜñ÷uˆ'óFW2í˜"&ñ÷vRˆßVr ¢W&¬“b'µ$T‘ıdUÙ$uÙ$4UıU$«◊µ$T‘ıdUÙ$uıDá“ ¢ÜVFW'2“≤%Ç‘í‘∂Wí#¢$T‘ıdUÙ$uÙïÙ¥Uó–¢FF“∞¢'6ó¶R#¢$T‘ıdUÙ$uı4ï§R¿¢&f˜&÷B#¢$T‘ıdUÙ$uÙdı$‘B¿¢'GóR#¢&WFÚ"¿¢–¢Fñ÷V˜WB“áGGÇÂFñ÷V˜WBÖ$T‘ıdUÙ$uıDî‘TıUEı2¬6ˆÊÊV7C”#„ê¢G'ì†¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC◊Fñ÷V˜WB¬fˆ∆∆˜u˜&VFó&V7G3’G'VRí26∆ñVÁC†¢fñ∆W2“≤&ñ÷vUˆfñ∆R#¢Ç&ñ÷vRÊßr"¬ñ÷uˆ'óFW2¬÷ñ÷Ró–¢"“vóB6∆ñVÁBÁ˜7BáW&¬¬ÜVFW'3÷ÜVFW'2¬FF÷FF¬fñ∆W3÷fñ∆W2ê¢ñb"Á7FGW5ˆ6ˆFR„“C†¢&ˆGí“á"ÁFWáB˜"""ï≥£s–¢ˆ&uˆÊ˜FUˆW'&˜"Üb'&V÷˜fRÊ&rífñ∆VB7FGW3◊∑"Á7FGW5ˆ6ˆFW“&ˆGì◊∂&ˆGó“"ê¢∆ˆrÁv&ÊñÊrÇ'&V÷˜fRÊ&rífñ∆VB7FGW3“W2&ˆGì“W2"¬"Á7FGW5ˆ6ˆFR¬&ˆGíê¢&WGW&‚ÊˆÊP¢ñbÊ˜B"Ê6ˆÁFVÁB˜"∆V‚á"Ê6ˆÁFVÁBí¬3†¢ˆ&uˆÊ˜FUˆW'&˜"Üb'&V÷˜fRÊ&rí&WGW&ÊVBV◊Gí˜6Ü˜'B6ˆÁFVÁC¢∂∆V‚á"Ê6ˆÁFVÁB˜""rró“'óFW2"ê¢&WGW&‚ÊˆÊP¢&WGW&‚'óFW2á"Ê6ˆÁFVÁBê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆ&uˆÊ˜FUˆW'&˜"Üb'&V÷˜fRÊ&ríWÜ6WFñˆ„¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢∆ˆrÁv&ÊñÊrÇ'&V÷˜fRÊ&ríWÜ6WFñˆ„¢W2"¬Rê¢&WGW&‚ÊˆÊP††¶7ñÊ2FVbˆ6ˆ÷WEˆ'&ñ˜&V÷˜fUˆ&uˆ'óFW2Üñ÷uˆ'óFW3¢'óFW2í”‚'óFW2¬ÊˆÊS†¢""%&V÷˜FRf∆∆&6≤ˆÊ«í‚÷ñ‚&ˆGV7Fñˆ‚FÇ6Ü˜V∆B&R∆ˆ6¬&V÷&r‚"" ¢ñbÊ˜B4Ù‘UEÙïÙ¥Uì†¢&WGW&‚ÊˆÊP¢ÜVFW'2“≤$WFÜ˜&ó¶Fñˆ‚#¢b$&V&W"¥4Ù‘UEÙïÙ¥Uó“'–¢÷ñ÷R“6Êñfeˆñ÷vUˆ÷ñ÷RÜñ÷uˆ'óFW2ê¢Fá3¢∆ó7E∑7G%““µ–¢f˜"ñ‚Ñ$uÙ4Ù‘UEı$T‘ıdUıDÇ¬"˜cˆñ÷vW2ˆVFóG2"¬"˜cˆñ÷vW2ˆvVÊW&FñˆÁ2"ì†¢ñbÊBÊ˜Bñ‚Fá3†¢Fá2ÊVÊBáê¢Fñ÷V˜WB“áGGÇÂFñ÷V˜WBÑ$uı$T‘ıdUıDî‘TıUEı2¬6ˆÊÊV7C”#„ê¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC◊Fñ÷V˜WB¬fˆ∆∆˜u˜&VFó&V7G3’G'VRí26∆ñVÁC†¢f˜"FÇñ‚Fá3†¢W&¬“b'¥4Ù‘UEÙ$4UıU$«◊∑Fá“ ¢G'ì†¢fñ∆W2“≤&ñ÷vR#¢Ç&ñ÷vRÁÊr"¬ñ÷uˆ'óFW2¬÷ñ÷R˜"&∆ñ6Fñˆ‚ˆˆ7FWB◊7G&V“"ó–¢FF“∞¢&÷ˆFV¬#¢$uÙ4Ù‘UEÙ‘ÙDT¬¿¢'&W7ˆÁ6Uˆf˜&÷B#¢&#cEˆß6ˆ‚"¿¢'G&Á7&VÁEˆ&6∂w&˜VÊB#¢'G'VR"¿¢–¢"“vóB6∆ñVÁBÁ˜7BáW&¬¬ÜVFW'3÷ÜVFW'2¬fñ∆W3÷fñ∆W2¬FF÷FFê¢ñb"Á7FGW5ˆ6ˆFR„“C†¢W'"“b$6ˆ÷WB$r&V÷˜fRfñ∆VBFÉ◊∑Fá“7FGW3◊∑"Á7FGW5ˆ6ˆFW“&ˆGì◊∑"ÁFWáE≥£S◊“ ¢∆ˆrÁv&ÊñÊrÜW'"ê¢ˆ&uˆÊ˜FUˆW'&˜"ÜW'"ê¢6ˆÁFñÁVP¢˜WB“vóBˆñ÷vUˆ'óFW5ˆg&ˆ’˜&W7ˆÁ6Rá"¬6∆ñVÁBê¢ñb˜WC†¢&WGW&‚˜W@¢WÜ6WBWÜ6WFñˆ‚2S†¢◊6r“b$6ˆ÷WB&6∂w&˜VÊB&V÷˜fRWÜ6WFñˆ‚FÉ◊∑Fá”¢∂W“ ¢∆ˆrÁv&ÊñÊrÜ◊6rê¢ˆ&uˆÊ˜FUˆW'&˜"Ü◊6rê¢&WGW&‚ÊˆÊP††¶7ñÊ2FVbˆ'&ñˆFó&V7E˜&V÷˜fUˆ&uˆ'óFW2Üñ÷uˆ'óFW3¢'óFW2í”‚'óFW2¬ÊˆÊS†¢""$Fó&V7B'&ñf∆∆&6≤¬ˆÊ«íñb%$îÙïÙ¥Uíó26ˆÊfñwW&VB‚"" ¢ñbÊ˜B%$îÙïÙ¥Uì†¢&WGW&‚ÊˆÊP¢÷ñ÷R“6Êñfeˆñ÷vUˆ÷ñ÷RÜñ÷uˆ'óFW2ê¢ÜVFW'5˜f&ñÁG2“∞¢≤$WFÜ˜&ó¶Fñˆ‚#¢b$&V&W"¥%$îÙïÙ¥Uó“'“¿¢≤&ï˜Fˆ∂V‚#¢%$îÙïÙ¥Uó“¿¢≤$WFÜ˜&ó¶Fñˆ‚#¢b$&V&W"¥%$îÙïÙ¥Uó“"¬&ï˜Fˆ∂V‚#¢%$îÙïÙ¥Uó“¿¢–¢Fá3¢∆ó7E∑7G%““µ–¢f˜"ñ‚Ñ%$îı$T‘ıdUıDÇ¬"˜cˆ&6∂w&˜VÊB˜&V÷˜fR"¬"˜c˜&V÷˜fUˆ&6∂w&˜VÊB"¬"ˆ&6∂w&˜VÊB˜&V÷˜fR"ì†¢ñbÊBÊ˜Bñ‚Fá3†¢Fá2ÊVÊBáê¢Fñ÷V˜WB“áGGÇÂFñ÷V˜WBÑ$uı$T‘ıdUıDî‘TıUEı2¬6ˆÊÊV7C”#„ê¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC◊Fñ÷V˜WB¬fˆ∆∆˜u˜&VFó&V7G3’G'VRí26∆ñVÁC†¢f˜"FÇñ‚Fá3†¢W&¬“b'¥%$îÙ$4UıU$«◊∑Fá“ ¢f˜"ÜVFW'2ñ‚ÜVFW'5˜f&ñÁG3†¢G'ì†¢fñ∆W2“≤&ñ÷vR#¢Ç&ñ÷vRÁÊr"¬ñ÷uˆ'óFW2¬÷ñ÷R˜"&∆ñ6Fñˆ‚ˆˆ7FWB◊7G&V“"ó–¢"“vóB6∆ñVÁBÁ˜7BáW&¬¬ÜVFW'3÷ÜVFW'2¬fñ∆W3÷fñ∆W2ê¢ñb"Á7FGW5ˆ6ˆFR„“C†¢ˆ&uˆÊ˜FUˆW'&˜"Üb$'&ñFó&V7Bfñ∆VBFÉ◊∑Fá“7FGW3◊∑"Á7FGW5ˆ6ˆFW“&ˆGì◊∑"ÁFWáE≥£C◊“"ê¢6ˆÁFñÁVP¢˜WB“vóBˆñ÷vUˆ'óFW5ˆg&ˆ’˜&W7ˆÁ6Rá"¬6∆ñVÁBê¢ñb˜WC†¢&WGW&‚˜W@¢WÜ6WBWÜ6WFñˆ‚2S†¢◊6r“b$'&ñFó&V7B&V÷˜fRWÜ6WFñˆ‚FÉ◊∑Fá”¢∂W“ ¢∆ˆrÁv&ÊñÊrÜ◊6rê¢ˆ&uˆÊ˜FUˆW'&˜"Ü◊6rê¢&WGW&‚ÊˆÊP††¶FVbˆÊ˜&÷∆ó¶U˜G&Á7&VÁE˜ÊrÜñ÷uˆ'óFW3¢'óFW2í”‚'óFW3†¢ñbñ÷vRó2ÊˆÊS†¢&WGW&‚ñ÷uˆ'óFW0¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2ííÊ6ˆÁfW'BÇ%$t$"ê¢÷Ö˜6ñFR“ñÁBÑ$uÙıUEUEÙ‘Öı4îDR˜"cê¢ñb÷Ö˜6ñFR‚ÊB÷ÇÜñ“Á6ó¶Rí‚÷Ö˜6ñFS†¢ñ“ÁFáV÷&Êñ¬ÇÜ÷Ö˜6ñFR¬÷Ö˜6ñFRí¬ñ÷vR‰ƒ‰5§ı2ê¢&ñÚ“'óFW4îÚÇê¢ñ“Á6fRÜ&ñÚ¬f˜&÷C“%‰r"¬˜Fñ÷ó¶S’G'VR¬6ˆ◊&W75ˆ∆WfV√”bê¢&WGW&‚&ñÚÊvWGf«VRÇê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆ&uˆÊ˜FUˆW'&˜"Üb&Ê˜&÷∆ó¶RG&Á7&VÁBÊrfñ∆VC¢∂W“"ê¢&WGW&‚ñ÷uˆ'óFW0†¶7ñÊ2FVb˜&V÷˜fUˆ&uˆ'óFW5˜&ñ÷'íÜñ÷uˆ'óFW3¢'óFW2í”‚'óFW2¬ÊˆÊS†¢"" ¢&ˆGV7Fñˆ‚&6∂w&˜VÊBóV∆ñÊR‡¢&ñ÷'ì¢Ü˜F˜&ˆˆ“&V÷˜fR&6∂w&˜VÊBí‡¢˜FñˆÊ¬f∆∆&6∑2&RW6VBˆÊ«íñ‚&˜fñFW#÷◊V«FíˆWFÚ‚∆ˆ6¬&V÷&r&V÷ñÁ2Fó6&∆VBˆ‚&VÊFW"7F'FW"‡¢"" ¢&˜fñFW"“Ñ$uı$ıdîDU"˜"'Ü˜F˜&ˆˆ“÷í÷ˆÊ«í"íÊ∆˜vW"ÇíÁ7G&óÇê¢Ü˜F˜&ˆˆ’ˆˆÊ«í“&˜fñFW"ñ‚Ä¢'Ü˜F˜&ˆˆ“"¬'Ü˜F˜&ˆˆ“÷í"¬'Ü˜F˜&ˆˆ“÷í÷ˆÊ«í"¿¢'Ü˜F˜&ˆˆ“÷ˆÊ«í"¬&í"¬&í÷ˆÊ«í ¢ê†¢2í7F&∆R&ˆGV7Fñˆ‚FÉ¢Ü˜F˜&ˆˆ“í‡¢ñb&˜fñFW"ñ‚Ç&WFÚ"¬&◊V«Fí"¬'Ü˜F˜&ˆˆ“"¬'Ü˜F˜&ˆˆ“÷í"¬'Ü˜F˜&ˆˆ“÷í÷ˆÊ«í"¬'Ü˜F˜&ˆˆ“÷ˆÊ«í"¬&í"¬&í÷ˆÊ«í"ì†¢˜WB“vóB˜Ü˜F˜&ˆˆ’ˆï˜&V÷˜fUˆ'óFW2Üñ÷uˆ'óFW2ê¢ñb˜WC†¢&WGW&‚ˆÊ˜&÷∆ó¶U˜G&Á7&VÁE˜ÊrÜ˜WBê¢ñbÜ˜F˜&ˆˆ’ˆˆÊ«ì†¢&WGW&‚ÊˆÊP†¢2"í˜FñˆÊ¬∆Vv7í&V÷˜fRÊ&r÷6ˆ◊Fñ&∆Rf∆∆&6≤ñbWá∆ñ6óF«í6ˆÊfñwW&VB‡¢ñb&˜fñFW"ñ‚Ç&WFÚ"¬&◊V«Fí"¬'&V÷˜fV&r"¬'&V÷˜fRÊ&r"¬'&V÷˜fV&r÷í"¬'&V÷˜fV&r÷í÷ˆÊ«í"¬'&V÷˜fV&r÷ˆÊ«í"ì†¢˜WB“vóB˜&V÷˜fV&uˆï˜&V÷˜fUˆ'óFW2Üñ÷uˆ'óFW2ê¢ñb˜WC†¢&WGW&‚ˆÊ˜&÷∆ó¶U˜G&Á7&VÁE˜ÊrÜ˜WBê¢ñb&˜fñFW"ñ‚Ç'&V÷˜fV&r"¬'&V÷˜fRÊ&r"¬'&V÷˜fV&r÷í"¬'&V÷˜fV&r÷í÷ˆÊ«í"¬'&V÷˜fV&r÷ˆÊ«í"ì†¢&WGW&‚ÊˆÊP†¢22í˜FñˆÊ¬6ˆ÷WBÙ'&ñf∆∆&6≤ˆÊ«ívÜV‚&˜fñFW"∆∆˜w2&V÷˜FRf∆∆&6≤‡¢&V÷˜FUˆ∆∆˜vVB“&˜fñFW"Ê˜Bñ‚Ä¢&∆ˆ6¬÷ˆÊ«í"¬'&V÷&r÷ˆÊ«í"¬&∆ˆ6¬"¬'&V÷&r"¿¢'Ü˜F˜&ˆˆ“÷í÷ˆÊ«í"¬'Ü˜F˜&ˆˆ“÷ˆÊ«í"¬&í÷ˆÊ«í ¢ê¢ñb&V÷˜FUˆ∆∆˜vVBÊB&˜fñFW"ñ‚Ç&WFÚ"¬&◊V«Fí"¬&6ˆ÷WB"¬&6ˆ÷WFí"¬&'&ñ÷6ˆ÷WB"¬&'&ñ˜&V÷˜fR÷&6∂w&˜VÊB"ì†¢˜WB“vóBˆ6ˆ÷WEˆ'&ñ˜&V÷˜fUˆ&uˆ'óFW2Üñ÷uˆ'óFW2ê¢ñb˜WC†¢&WGW&‚ˆÊ˜&÷∆ó¶U˜G&Á7&VÁE˜ÊrÜ˜WBê†¢ñb&V÷˜FUˆ∆∆˜vVBÊB&˜fñFW"ñ‚Ç&WFÚ"¬&◊V«Fí"¬&'&ñ"¬&Fó&V7B÷'&ñ"¬&'&ñ÷Fó&V7B"ì†¢˜WB“vóBˆ'&ñˆFó&V7E˜&V÷˜fUˆ&uˆ'óFW2Üñ÷uˆ'óFW2ê¢ñb˜WC†¢&WGW&‚ˆÊ˜&÷∆ó¶U˜G&Á7&VÁE˜ÊrÜ˜WBê†¢2Bí∆7B◊&W6˜'B∆ˆ6¬&V÷&rˆÊ«íñbWá∆ñ6óF«íVÊ&∆VC≤Fó6&∆VBñ‚&ˆGV7Fñˆ‚ˆ‚&VÊFW"7F'FW"‡¢∆ˆ6≈ˆ∆∆˜vVB“&ˆˆ¬ÇÜÊ˜B$uÙDï4$ƒUÙƒÙ4≈ı$T‘$ríÊBƒÙ4≈ı$T‘$uÙT‰$ƒTBÊB&V÷&u˜&V÷˜fRó2Ê˜BÊˆÊRÊB&˜fñFW"Ê˜Bñ‚Ç'Ü˜F˜&ˆˆ“÷í÷ˆÊ«í"¬'Ü˜F˜&ˆˆ“÷ˆÊ«í"¬'&V÷˜fV&r÷í÷ˆÊ«í"¬'&V÷˜fV&r÷ˆÊ«í"¬&í÷ˆÊ«í"íê¢ñb∆ˆ6≈ˆ∆∆˜vVC†¢˜WB“vóBˆ∆ˆ6≈˜&V÷&u˜&V÷˜fUˆ'óFW2Üñ÷uˆ'óFW2ê¢ñb˜WC†¢&WGW&‚ˆÊ˜&÷∆ó¶U˜G&Á7&VÁE˜ÊrÜ˜WBê†¢ñbÊ˜BÑıDı$ÙÙ’ÙïÙ¥UíÊB&˜fñFW"ñ‚Ç'Ü˜F˜&ˆˆ“"¬'Ü˜F˜&ˆˆ“÷í"¬'Ü˜F˜&ˆˆ“÷í÷ˆÊ«í"¬'Ü˜F˜&ˆˆ“÷ˆÊ«í"¬&í"¬&í÷ˆÊ«í"ì†¢ˆ&uˆÊ˜FUˆW'&˜"Ç%ÑıDı$ÙÙ’ÙïÙ¥Uíó2Ê˜B6ˆÊfñwW&VB"ê¢ñb&V÷&u˜&V÷˜fRó2ÊˆÊRÊBÊ˜B$uÙDï4$ƒUÙƒÙ4≈ı$T‘$s†¢ˆ&uˆÊ˜FUˆW'&˜"Üb&∆ˆ6¬&V÷&rVÊfñ∆&∆S¢ñ◊˜'Bfñ∆VBµ$T‘$uÙî’ı%EÙU%$ı'“"ê¢&WGW&‚ÊˆÊP†¶FVbˆfóEˆ6˜fW"Üñ“¬6ó¶S¢GW∆U∂ñÁB¬ñÁE“ì†¢ñbñ÷vT˜3†¢&WGW&‚ñ÷vT˜2ÊfóBÜñ“¬6ó¶R¬÷WFÜˆC‘ñ÷vR‰ƒ‰5§ı2¬6VÁFW&ñÊs“É„R¬„Ríê¢&WGW&‚ñ“Á&W6ó¶Rá6ó¶R¬ñ÷vR‰ƒ‰5§ı2ê††¶FVbˆw&FñVÁEˆ&6∂w&˜VÊBá6ó¶S¢GW∆U∂ñÁB¬ñÁE“¬F˜¢GW∆U∂ñÁB¬ñÁB¬ñÁE“¬&˜GFˆ”¢GW∆U∂ñÁB¬ñÁB¬ñÁE“ì†¢r¬Ç“6ó¶P¢&r“ñ÷vRÊÊWrÇ%$t""¬6ó¶R¬F˜ê¢ñbñ÷vTG&ró2ÊˆÊS†¢&WGW&‚&p¢G&r“ñ÷vTG&r‰G&rÜ&rê¢f˜"íñ‚&ÊvRÜ÷ÇÉ¬Çíì†¢B“íÚ÷ÇÉ¬Ç“ê¢2“GW∆RÜñÁBáF˜∂ï“¢É“Bí≤&˜GFˆ’∂ï“¢Bíf˜"íñ‚&ÊvRÉ2íê¢G&rÊ∆ñÊRÖ≤É¬íí¬ár¬íï“¬fñ∆√÷2ê¢&WGW&‚&p†††•ı$T≈Ù$uıU$≈2“∞¢2
]ΩÕ›ΩRMÌ-Ìm]›≤¬›RçÌ-››ΩR}=Ω=ç≠Ç‚	]ΩÇ]-¬›]MÌ-=˝›(	B›çmRÌ-›]-ÚΩÌ≠ΩÕ›Ωíf∆∆&6≤‡¢&&V6Ç#¢&áGG3¢Úˆñ÷vW2ÁVÁ7∆6ÇÊ6ˆ“˜Ü˜FÚ”SsS#SC#É3B÷#s#66cìcC6SˆWFÛ÷f˜&÷BffóC÷7&˜gs”Ég”ÉR"¿¢&÷˜VÁFñÁ2#¢&áGG3¢Úˆñ÷vW2ÁVÁ7∆6ÇÊ6ˆ“˜Ü˜FÚ”ScìSì#S3Cb”#&FFC3&FcCˆWFÛ÷f˜&÷BffóC÷7&˜gs”Ég”ÉR"¿¢&ÊGW&R#¢&áGG3¢Úˆñ÷vW2ÁVÁ7∆6ÇÊ6ˆ“˜Ü˜FÚ”CCÉ3sS#CSÉb”ÉÉ#svF#ÉÉÜ#ˆWFÛ÷f˜&÷BffóC÷7&˜gs”Ég”ÉR"¿¢'&ˆˆb#¢&áGG3¢Úˆñ÷vW2ÁVÁ7∆6ÇÊ6ˆ“˜Ü˜FÚ”CÉsC3sÉCÇ”cv6cC6&3cˆWFÛ÷f˜&÷BffóC÷7&˜gs”Ég”ÉR"¿¢&ˆffñ6R#¢&áGG3¢Úˆñ÷vW2ÁVÁ7∆6ÇÊ6ˆ“˜Ü˜FÚ”Cìs3ccsSC3R÷c#ìcÜfSs#ˆWFÛ÷f˜&÷BffóC÷7&˜gs”Ég”ÉR"¿ß–††¶FVb˜6fUˆ66ÜUˆÊ÷RÜ∂Wì¢7G"í”‚7G#†¢&WGW&‚&RÁ7V"á"%µÊ◊§’£”ïÚ‚’“≤"¬%Ú"¬∂Wíï≥£É“˜"&&r ††¶FVb˜&V≈˜Ü˜Fıˆ&6∂w&˜VÊBá6ó¶S¢GW∆U∂ñÁB¬ñÁE“¬∂ñÊC¢7G"ì†¢""-	]"›-Ì˝ùçíMÌ-ÌMÌ“çr≠›çıU$¬Ç≠Ì˝ç"˝ÌB}Õ]Ì≠]≠-‚"" ¢ñbñ÷vRó2ÊˆÊR˜"Ê˜B$uı$Tƒï5Dî5Ù$4¥u$ıT‰E3†¢&WGW&‚ÊˆÊP¢∂ñÊB“Ü∂ñÊB˜"""íÊ∆˜vW"ÇíÁ7G&óÇê¢W&¬“ı$T≈Ù$uıU$≈2ÊvWBÜ∂ñÊBê¢ñbÊ˜BW&√†¢&WGW&‚ÊˆÊP¢G'ì†¢˜2Ê÷∂VFó'2Ñ$uÙ44ÑUÙDï"¬WÜó7Eˆˆ≥’G'VRê¢66ÜU˜FÇ“˜2ÁFÇÊ¶ˆñ‚Ñ$uÙ44ÑUÙDï"¬˜6fUˆ66ÜUˆÊ÷RÜ∂ñÊBí≤"Êßr"ê¢FF“ÊˆÊP¢ñb˜2ÁFÇÊWÜó7G2Ü66ÜU˜FÇíÊB˜2ÁFÇÊvWG6ó¶RÜ66ÜU˜FÇí‚#C†¢vóFÇ˜V‚Ü66ÜU˜FÇ¬'&""í2c†¢FF“bÁ&VBÇê¢V«6S†¢vóFÇáGGÇ‰6∆ñVÁBáFñ÷V˜WC‘$uÙ$4¥u$ıT‰EıDî‘TıUEı2¬fˆ∆∆˜u˜&VFó&V7G3’G'VRí26∆ñVÁC†¢"“6∆ñVÁBÊvWBáW&¬¬ÜVFW'3◊≤%W6W"‘vVÁB#¢$uCU&Ù&˜BÛ„'“ê¢"Á&ó6Uˆf˜%˜7FGW2Çê¢FF“"Ê6ˆÁFVÁ@¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóFÇ˜V‚Ü66ÜU˜FÇ¬'v""í2c†¢bÁw&óFRÜFFê¢ñbÊ˜BFF†¢&WGW&‚ÊˆÊP¢&r“ñ÷vRÊ˜V‚Ñ'óFW4îÚÜFFííÊ6ˆÁfW'BÇ%$t""ê¢&r“ˆfóEˆ6˜fW"Ü&r¬6ó¶Rê¢2	Ω=≠ÌR}ÕΩ-çRÇ}-]Õ›]›çR¬}-Ì≤Ì≠]≠"›R-Ω=Ω˝M]≤-≠Ω]]››Ω¬Ωçç≠Ì¬]}≠‚‡¢ñbñ÷vTfñ«FW#†¢&r“&rÊfñ«FW"Ññ÷vTfñ«FW"‰vW76ñ‰&«W"á&FóW3÷÷ÇÉ„"¬÷ñ‚á6ó¶RíÚCSííê¢&WGW&‚&p¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆ&uˆÊ˜FUˆW'&˜"Üb'&V¬&6∂w&˜VÊBF˜vÊ∆ˆBfñ∆VB∂ñÊC◊∂∂ñÊG”¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢∆ˆrÁv&ÊñÊrÇ'&V¬&6∂w&˜VÊBfñ∆VB∂ñÊC“W3¢W2"¬∂ñÊB¬Rê¢&WGW&‚ÊˆÊP†¶FVbˆ÷∂Uˆ∆ˆ6≈ˆ&6∂w&˜VÊBá6ó¶S¢GW∆U∂ñÁB¬ñÁE“¬∂ñÊC¢7G"¬˜&ñvñÊ≈ˆ'óFW3¢'óFW2¬ÊˆÊR“ÊˆÊR¬&ˆ◊C¢7G"“""ì†¢r¬Ç“6ó¶P¢∂ñÊB“Ü∂ñÊB˜"&&«W""íÊ∆˜vW"Çê¢ñb$uı$Uƒ4UıU4Uı5DÙ4µÙ$4¥u$ıT‰E2ÊB∂ñÊBñ‚Ç&&V6Ç"¬&÷˜VÁFñÁ2"¬&ÊGW&R"¬'&ˆˆb"¬&ˆffñ6R"ì†¢&V≈ˆ&r“˜&V≈˜Ü˜Fıˆ&6∂w&˜VÊBá6ó¶R¬∂ñÊBê¢ñb&V≈ˆ&ró2Ê˜BÊˆÊS†¢&WGW&‚&V≈ˆ&p¢ñb∂ñÊB”“&&«W""ÊB˜&ñvñÊ≈ˆ'óFW2ÊBñ÷vTfñ«FW#†¢&6R“ñ÷vRÊ˜V‚Ñ'óFW4îÚÜ˜&ñvñÊ≈ˆ'óFW2ííÊ6ˆÁfW'BÇ%$t""ê¢&r“ˆfóEˆ6˜fW"Ü&6R¬6ó¶Rê¢&WGW&‚&rÊfñ«FW"Ññ÷vTfñ«FW"‰vW76ñ‰&«W"á&FóW3÷÷ÇÉÇ¬÷ñ‚ár¬ÇíÚÚÇííê¢ñb∂ñÊB”“'vÜóFR#†¢&WGW&‚ñ÷vRÊÊWrÇ%$t""¬6ó¶R¬É#SR¬#SR¬#SRíê¢ñb∂ñÊB”“&&∆6≤#†¢&WGW&‚ñ÷vRÊÊWrÇ%$t""¬6ó¶R¬ÉÇ¬Ç¬Çíê†¢ñb∂ñÊB”“&&V6Ç#†¢&r“ˆw&FñVÁEˆ&6∂w&˜VÊBá6ó¶R¬ÉB¬ìB¬#3rí¬É#CR¬#í¬c"íê¢ñbñ÷vTG&s†¢B“ñ÷vTG&r‰G&rÜ&rê¢BÁ&V7FÊv∆RÖ≥¬ñÁBÜÇ¢„cBí¬r¬Ö“¬fñ∆√“É#32¬#2¬Críê¢BÁ&V7FÊv∆RÖ≥¬ñÁBÜÇ¢„CÇí¬r¬ñÁBÜÇ¢„cbï“¬fñ∆√“ÉSÇ¬c¬#"íê¢&WGW&‚&p†¢ñb∂ñÊB”“&÷˜VÁFñÁ2#†¢&r“ˆw&FñVÁEˆ&6∂w&˜VÊBá6ó¶R¬É#b¬sb¬##íí¬É#3¬#3r¬#CBíê¢ñbñ÷vTG&s†¢B“ñ÷vTG&r‰G&rÜ&rê¢BÁˆ«ñvˆ‚Ö≤É¬Çí¬ÜñÁBár£„#bí¬ñÁBÜÇ£„Cíí¬ÜñÁBár£„SÇí¬Çï“¬fñ∆√“Éìr¬B¬#bíê¢BÁˆ«ñvˆ‚Ö≤ÜñÁBár£„3Bí¬Çí¬ÜñÁBár£„crí¬ñÁBÜÇ£„#Çíí¬ár¬Çï“¬fñ∆√“ÉsÇ¬ì2¬Çíê¢&WGW&‚&p†¢ñb∂ñÊB”“'&ˆˆb#†¢&r“ˆw&FñVÁEˆ&6∂w&˜VÊBá6ó¶R¬Éìb¬#2¬sí¬É3B¬3Ç¬Sbíê¢ñbñ÷vTG&s†¢B“ñ÷vTG&r‰G&rÜ&rê¢f˜"íñ‚&ÊvRÉÇì†¢É“ñÁBár¢ÜíÚÇ„íê¢'r“÷ÇÉÇ¬rÚÚ"ê¢&Ç“ñÁBÜÇ¢É„R≤ÜíRBí¢„Çíê¢BÁ&V7FÊv∆RÖ∑É¬Ç“&Ç¬É≤'r¬Ö“¬fñ∆√“ÉC¬Cb¬c"íê¢&WGW&‚&p†¢ñb∂ñÊB”“&ˆffñ6R#†¢&r“ˆw&FñVÁEˆ&6∂w&˜VÊBá6ó¶R¬É#C"¬#CB¬#Crí¬É#"¬#í¬##Çíê¢ñbñ÷vTG&s†¢B“ñ÷vTG&r‰G&rÜ&rê¢BÁ&V7FÊv∆RÖ≥¬ñÁBÜÇ£„sí¬r¬Ö“¬fñ∆√“É#¬ìb¬sÇíê¢f˜"Çñ‚&ÊvRÉ¬r¬÷ÇÉC¬rÚÚbíì†¢BÁ&V7FÊv∆RÖ∑Ç¬ñÁBÜÇ£„Çí¬÷ñ‚ár¬Ç≤÷ÇÉ#B¬rÚÚ"íí¬ñÁBÜÇ£„SÇï“¬fñ∆√“Éì¬#R¬#ííê¢&WGW&‚&p†¢2ÊGW&Rˆ7W7Fˆ“f∆∆&6≥¢˝Ì≠Ìù›Ωí}]Ω›ΩíMÌ“=Ω=ç›Ìí‡¢&r“ˆw&FñVÁEˆ&6∂w&˜VÊBá6ó¶R¬É#R¬ì¬Cí¬É3R¬É¬Síê¢ñbñ÷vTG&s†¢B“ñ÷vTG&r‰G&rÜ&rê¢f˜"íñ‚&ÊvRÉ"ì†¢Ç“ñÁBár¢íÚê¢í“ñÁBÜÇ¢É„CR≤ÜíR2í¢„ríê¢"“÷ÇÉ3¬rÚÚ"ê¢BÊV∆∆ó6RÖ∑Ç◊"¬í◊"¬Ç∑"¬í∑%“¬fñ∆√“ÉCR¬R¬cRíê¢BÁ&V7FÊv∆RÖ≥¬ñÁBÜÇ£„sí¬r¬Ö“¬fñ∆√“ÉC"¬ìR¬SRíê¢&WGW&‚&p††¶FVbˆ6ˆ◊˜6U˜7V&¶V7EˆˆÂˆ&6∂w&˜VÊBÜ&u˜&v"¬fu˜&v&ì†¢&r“&u˜&v"Ê6ˆÁfW'BÇ%$t$"íñbvWFGG"Ü&u˜&v"¬&÷ˆFR"¬""í“%$t$"V«6R&u˜&v"Ê6˜íÇê¢fr“fu˜&v&Ê6ˆÁfW'BÇ%$t$"ê¢«Ü“frÊvWF6ÜÊÊV¬Ç$"ê¢ñbñ÷vTfñ«FW#†¢G'ì†¢6ÜF˜uˆ÷6≤“«ÜÊfñ«FW"Ññ÷vTfñ«FW"‰vW76ñ‰&«W"á&FóW3÷÷ÇÉb¬÷ñ‚ÜfrÁ6ó¶RíÚÛìííê¢6ÜF˜r“ñ÷vRÊÊWrÇ%$t$"¬frÁ6ó¶R¬É¬¬¬íê¢6ÜF˜rÁWF«Üá6ÜF˜uˆ÷6≤ÁˆñÁBÜ∆÷&F¢ñÁBá¢„#ííê¢GÇ“÷ÇÉ"¬frÁ6ó¶U≥“ÚÚê¢Gí“÷ÇÉ"¬frÁ6ó¶U≥“ÚÚìê¢&rÊ«Üˆ6ˆ◊˜6óFRá6ÜF˜r¬FW7C“ÜGÇ¬Gííê¢WÜ6WBWÜ6WFñˆ„†¢70¢&rÊ«Üˆ6ˆ◊˜6óFRÜfrê¢&WGW&‚&p††¶7ñÊ2FVbˆvVÊW&FUˆ&6∂w&˜VÊEˆˆÊ«ïˆ'óFW2á6ó¶S¢GW∆U∂ñÁB¬ñÁE“¬∂ñÊC¢7G"“&7W7Fˆ“"¬&ˆ◊C¢7G"“""í”‚'óFW2¬ÊˆÊS†¢ñbñ÷vRó2ÊˆÊS†¢&WGW&‚ÊˆÊP¢∂ñÊB“Ü∂ñÊB˜"&7W7Fˆ“"íÊ∆˜vW"ÇíÁ7G&óÇê¢vÁEˆvV‚“Ü∂ñÊB”“&7W7Fˆ“"ÊB$uı$Uƒ4UÙtT‰U$DUÙ5U5DÙ“í˜"Ü∂ñÊB“&7W7Fˆ“"ÊB$uı$Uƒ4UÙtT‰U$DUı$U4UE2ê¢ñbÊ˜BvÁEˆvV„†¢&WGW&‚ÊˆÊP¢gV∆≈˜&ˆ◊B“ˆ'Vñ∆Eˆ&6∂w&˜VÊE˜66VÊU˜&ˆ◊BÜ∂ñÊB¬&ˆ◊Bê¢ÊVvFófR“ˆ'Vñ∆Eˆ&6∂w&˜VÊEˆÊVvFófU˜&ˆ◊BÜ∂ñÊB¬&ˆ◊Bê¢fñÊ≈˜&ˆ◊B“b'∂gV∆≈˜&ˆ◊G“fˆñC¢∂ÊVvFófW“‚ ¢G'ì†¢FF“vóBˆ«V÷ˆvVÊW&FUˆñ÷vUˆ'óFW2ÜfñÊ≈˜&ˆ◊Bê¢ñbÊ˜BFF†¢ˆ&uˆÊ˜FUˆW'&˜"Üb&&6∂w&˜VÊB÷ˆÊ«ívVÊW&Fñˆ‚&WGW&ÊVBV◊Gí˜WGWBf˜"∂ñÊC◊∂∂ñÊG“"ê¢&WGW&‚ÊˆÊP¢&r“ñ÷vRÊ˜V‚Ñ'óFW4îÚÜFFííÊ6ˆÁfW'BÇ%$t""ê¢&r“ˆfóEˆ6˜fW"Ü&r¬6ó¶Rê¢&ñÚ“'óFW4îÚÇê¢&rÁ6fRÜ&ñÚ¬f˜&÷C“$•Tr"¬V∆óGì÷÷ÇÉÉb¬÷ñ‚ÉìÇ¬$uı$Uƒ4UÙ•TuıTƒïEííí¬˜Fñ÷ó¶S’G'VR¬&ˆw&W76ófS’G'VRê¢&WGW&‚&ñÚÊvWGf«VRÇê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆ&uˆÊ˜FUˆW'&˜"Üb&&6∂w&˜VÊB÷ˆÊ«ívVÊW&Fñˆ‚fñ∆VB∂ñÊC◊∂∂ñÊG”¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢∆ˆrÁv&ÊñÊrÇ&&6∂w&˜VÊB÷ˆÊ«ívVÊW&Fñˆ‚fñ∆VB∂ñÊC“W3¢W2"¬∂ñÊB¬Rê¢&WGW&‚ÊˆÊP††¶7ñÊ2FVbˆ6ˆ◊˜6U˜&W∆6Uˆ&rÜñ÷uˆ'óFW3¢'óFW2¬&uˆ∂ñÊC¢7G"“&&«W""¬&ˆ◊C¢7G"“""í”‚'óFW2¬ÊˆÊS†¢ñbñ÷vRó2ÊˆÊS†¢&WGW&‚ÊˆÊP†¢27G&ñ7B&ˆGV7Fñˆ‚óV∆ñÊS¢í&V÷˜fR&6∂w&˜VÊB¬"í'Vñ∆B˜6V∆V7BÊWr&6∂w&˜VÊB¬2í6ˆ◊˜6óFR7V&¶V7B&6≤‡¢7WF˜WEˆ'óFW2“vóB˜&V÷˜fUˆ&uˆ'óFW5˜&ñ÷'íÜñ÷uˆ'óFW2ê¢ñbÊ˜B7WF˜WEˆ'óFW3†¢&WGW&‚ÊˆÊP†¢fr“ñ÷vRÊ˜V‚Ñ'óFW4îÚÜ7WF˜WEˆ'óFW2ííÊ6ˆÁfW'BÇ%$t$"ê¢F&vWE˜6ó¶R“frÁ6ó¶P†¢&u˜&v"“ÊˆÊP¢vVÂˆ'óFW2“vóBˆvVÊW&FUˆ&6∂w&˜VÊEˆˆÊ«ïˆ'óFW2áF&vWE˜6ó¶R¬∂ñÊC÷&uˆ∂ñÊB¬&ˆ◊C◊&ˆ◊Bê¢ñbvVÂˆ'óFW3†¢G'ì†¢&u˜&v"“ñ÷vRÊ˜V‚Ñ'óFW4îÚÜvVÂˆ'óFW2ííÊ6ˆÁfW'BÇ%$t""ê¢WÜ6WBWÜ6WFñˆ„†¢&u˜&v"“ÊˆÊP†¢ñb&u˜&v"ó2ÊˆÊS†¢&u˜&v"“ˆ÷∂Uˆ∆ˆ6≈ˆ&6∂w&˜VÊBáF&vWE˜6ó¶R¬&uˆ∂ñÊB¬˜&ñvñÊ≈ˆ'óFW3÷ñ÷uˆ'óFW2¬&ˆ◊C◊&ˆ◊BíÊ6ˆÁfW'BÇ%$t""ê†¢6ˆ◊˜6VB“ˆ6ˆ◊˜6U˜7V&¶V7EˆˆÂˆ&6∂w&˜VÊBÜ&u˜&v"¬frê¢&ñÚ“'óFW4îÚÇê¢6ˆ◊˜6VBÊ6ˆÁfW'BÇ%$t""íÁ6fRÄ¢&ñÚ¿¢f˜&÷C“$•Tr"¿¢V∆óGì÷÷ÇÉÉb¬÷ñ‚ÉìÇ¬$uı$Uƒ4UÙ•TuıTƒïEííí¿¢˜Fñ÷ó¶S’G'VR¿¢&ˆw&W76ófS’G'VR¿¢ê¢&WGW&‚&ñÚÊvWGf«VRÇê††¶7ñÊ2FVb˜VFóE˜&V÷˜fV&ráWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬ñ÷uˆ'óFW3¢'óFW2ì†¢ñbÊ˜B6ˆÁFWáBÁW6W%ˆFFÁ˜Ç%ˆñ÷vU˜&ˆ6W76ñÊu˜V˜Fˆˆ≤"¬f«6Rì†¢7ñÊ2FVbˆvÚÇì†¢6ˆÁFWáBÁW6W%ˆFF≤%ˆñ÷vU˜&ˆ6W76ñÊu˜V˜Fˆˆ≤%““G'VP¢&WGW&‚vóB˜VFóE˜&V÷˜fV&ráWFFR¬6ˆÁFWáB¬ñ÷uˆ'óFW2ê¢vóB˜G'ï˜ï˜FÜVÂˆFÚÄ¢WFFR¬6ˆÁFWáB¬WFFRÊVffV7FófU˜W6W"ÊñB¿¢&ñ÷r"¬î‘uı$Ù4U55Ù4ı5EıU4B¬ˆvÚ¿¢&V÷V÷&W%ˆ∂ñÊC“'&V÷˜fV&r"¿¢ê¢&WGW&‡¢G'ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	˙{¬
=MΩ˝‚MÌ“‚	-]›2‰r˝Ì}}›Ìí˝ÌMΩÌm≠Ìí‚"ê¢˜WB“vóB7ñÊ6ñÚÁvóEˆf˜"Ö˜&V÷˜fUˆ&uˆ'óFW5˜&ñ÷'íÜñ÷uˆ'óFW2í¬Fñ÷V˜WC‘$uÙ5DîÙÂıDî‘TıUEı2ê¢ñbÊ˜B˜WC†¢ñb&V÷&u˜&V÷˜fRó2ÊˆÊS†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)ÿ¬	›R=MΩÌ¬=MΩç-¬MÌ“}]]rÜ˜F˜&ˆˆ“í‚ ¢-	˝Ì-]Õ-RÑıDı$ÙÙ’ÙïÙ¥UíÇΩçÕç-≤-]-Ì-Ì=‚≠ΩÌ}‚	˝ÌΩ]M›çRÌçç≠É•∆‚"≤ˆ&uˆ∆7EˆW'&˜'5˜FWáBÇê¢ê¢V«6S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	›R=MΩÌ¬=MΩç-¬MÌ“‚	MΩÚ-Ì}›Ìí˝ç}ç›≤}˝=-ç-RˆFñuˆ&r‚	˝ÌΩ]M›çRÌçç≠É•∆‚"≤ˆ&uˆ∆7EˆW'&˜'5˜FWáBÇíê¢&WGW&‚f«6P¢&ñÚ“'óFW4îÚÜ˜WBê¢&ñÚÊÊ÷R“&Êıˆ&rÁÊr ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ïˆFˆ7V÷VÁBÄ¢ñÁWDfñ∆RÜ&ñÚí¿¢6Fñˆ„“-
MÌ“=MΩ“)»R‰r˝Ì}}›Ìí˝ÌMΩÌm≠Ìí‚"¿¢&VE˜Fñ÷V˜WC”#¿¢w&óFU˜Fñ÷V˜WC”#¿¢6ˆÊÊV7E˜Fñ÷V˜WC”3¿¢ˆˆ≈˜Fñ÷V˜WC”3¿¢ê¢&WGW&‚G'VP¢WÜ6WBFñ÷VD˜WB2S†¢ˆ&uˆÊ˜FUˆW'&˜"Üb'FV∆Vw&“W∆ˆBFñ÷V˜WC¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)ÿ¬
MÌ“=MΩ“¬›‚FV∆Vw&“›R=˝]≤˝ç›˝-¬‰r›Mù≤‚ ¢-
Ú=Õ]›Õçç≤}Õ]MùΩÌ""›Ì-Ìí-]çÉ≤˝Ì˝Ì=ù-R]ùrçΩÇÌ-˝-Õ-RMÌ-‚Õ]›Õç]=‚}Õ]‚ ¢ê¢&WGW&‚f«6P¢WÜ6WB7ñÊ6ñÚÂFñ÷V˜WDW'&˜#†¢ˆ&uˆÊ˜FUˆW'&˜"Üb'&V÷˜fV&r7Fñˆ‚Fñ÷V˜WBgFW"¥$uÙ5DîÙÂıDî‘TıUEı3¢„g◊2"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬
=MΩ]›çRMÌ›}›˝Ω‚Ωçç≠Ì¬Õ›Ì=‚-]Õ]›ÇÇΩΩ‚Ì-›Ì-Ω]›‚‚	˝Ì˝Ì=ù-RMÌ-‚Õ]›Õç]=‚}Õ]çΩÇ˝Ì--Ìç-R˝Ì}mR‚	˝ÌΩ]M›çRÌçç≠É•∆‚"≤ˆ&uˆ∆7EˆW'&˜'5˜FWáBÇíê¢&WGW&‚f«6P¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç'&V÷˜fV&rW'&˜#¢W2"¬Rê¢ˆ&uˆÊ˜FUˆW'&˜"Üb'&V÷˜fV&rWÜ6WFñˆ„¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›R=MΩÌ¬=MΩç-¬MÌ“‚	˝ÌΩ]M›çRÌçç≠É•∆‚"≤ˆ&uˆ∆7EˆW'&˜'5˜FWáBÇíê¢&WGW&‚f«6P††¶7ñÊ2FVb˜VFóE˜&W∆6V&ráWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬ñ÷uˆ'óFW3¢'óFW2¬∂ñÊC¢7G"“&&«W""¬&ˆ◊C¢7G"“""ì†¢ñbÊ˜B6ˆÁFWáBÁW6W%ˆFFÁ˜Ç%ˆñ÷vU˜&ˆ6W76ñÊu˜V˜Fˆˆ≤"¬f«6Rì†¢7ñÊ2FVbˆvÚÇì†¢6ˆÁFWáBÁW6W%ˆFF≤%ˆñ÷vU˜&ˆ6W76ñÊu˜V˜Fˆˆ≤%““G'VP¢&WGW&‚vóB˜VFóE˜&W∆6V&ráWFFR¬6ˆÁFWáB¬ñ÷uˆ'óFW2¬∂ñÊC÷∂ñÊB¬&ˆ◊C◊&ˆ◊Bê¢vóB˜G'ï˜ï˜FÜVÂˆFÚÄ¢WFFR¬6ˆÁFWáB¬WFFRÊVffV7FófU˜W6W"ÊñB¿¢&ñ÷r"¬î‘uı$Ù4U55Ù4ı5EıU4B¬ˆvÚ¿¢&V÷V÷&W%ˆ∂ñÊC“'&W∆6V&r"¿¢ê¢&WGW&‡¢ñbñ÷vRó2ÊˆÊS†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ%ñ∆∆˜r›R=-›Ì-Ω]“‚"ê¢&WGW&‚f«6P¢G'ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	˘k¬	}˝=≠‚M-=]›-˝›=‚}Õ]›2MÌ›¢í≠≠=-›‚-Ω]}‚}]ΩÌ-]≠˝Ì≠]≠"¬"íÌ-M]ΩÕ›‚˝ÌMç‚çΩÇ=]›]ç=‚›Ì-ΩíMÌ“¬2íÌç‚ç-Ì2]r˝]]çÌ-≠ÇΩçm¬ÌM]mM≤Ç˝Ì}≤‚"ê¢˜WB“vóB7ñÊ6ñÚÁvóEˆf˜"Öˆ6ˆ◊˜6U˜&W∆6Uˆ&rÜñ÷uˆ'óFW2¬&uˆ∂ñÊC÷∂ñÊB¬&ˆ◊C◊&ˆ◊Bí¬Fñ÷V˜WC‘$uÙ5DîÙÂıDî‘TıUEı2ê¢ñbÊ˜B˜WC†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	›R=MΩÌ¬Ì-M]Ωç-¬Ì≠]≠"Ì"MÌ›‚	MΩÚ-Ì}›Ìí˝ç}ç›≤}˝=-ç-RˆFñuˆ&r‚	˝ÌΩ]M›çRÌçç≠É•∆‚"≤ˆ&uˆ∆7EˆW'&˜'5˜FWáBÇíê¢&WGW&‚f«6P¢&ñÚ“'óFW4îÚÜ˜WBê¢&ñÚÊÊ÷R“b'&W∆6Uˆ&u˜∂∂ñÊB˜"v7W7Fˆ“w“Êßr ¢6“-
MÌ“}Õ]›“)»R	Ì≠]≠"Ì--Ω]“çrç]ÌM›Ì=‚MÌ-‚‚ ¢ñb&ˆ◊C†¢6≥“b%∆Ì	}˝ÌMÌ›¢∑&ˆ◊E≥£#S◊“ ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜Ü˜FÚÄ¢ñÁWDfñ∆RÜ&ñÚí¿¢6Fñˆ„÷6¿¢&VE˜Fñ÷V˜WC”É¿¢w&óFU˜Fñ÷V˜WC”É¿¢6ˆÊÊV7E˜Fñ÷V˜WC”3¿¢ˆˆ≈˜Fñ÷V˜WC”3¿¢ê¢&WGW&‚G'VP¢WÜ6WBFñ÷VD˜WB2S†¢ˆ&uˆÊ˜FUˆW'&˜"Üb'FV∆Vw&“&W∆6V&rW∆ˆBFñ÷V˜WC¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)™˚àÚFV∆Vw&“Ωçç≠Ì¬MÌΩ=‚˝ç›çÕ≤ç}Ìm]›çR˝ÌΩR}Õ]›≤MÌ›‚ ¢-	]ΩÇMÌ-‚=mR˝Ì˝-çΩÌ¬"}-R(	B]}=ΩÕ-"=˝]ç›‚MÌ--Ω]“‚ ¢-	]ΩÇMÌ-‚›R˝Ì˝-çΩÌ¬¬˝Ì--Ìç-R˝Ì˝Ω-≠2]ùrçΩÇÌ-˝-Õ-RMÌ-‚Õ]›Õç]=‚}Õ]‚ ¢ê¢&WGW&‚f«6P¢WÜ6WB7ñÊ6ñÚÂFñ÷V˜WDW'&˜#†¢ˆ&uˆÊ˜FUˆW'&˜"Üb'&W∆6V&r7Fñˆ‚Fñ÷V˜WBgFW"¥$uÙ5DîÙÂıDî‘TıUEı3¢„g◊2"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	}Õ]›MÌ›}›˝ΩΩçç≠Ì¬Õ›Ì=‚-]Õ]›ÇÇΩΩÌ-›Ì-Ω]›‚	˝Ì˝Ì=ù-RMÌ-‚Õ]›Õç]=‚}Õ]çΩÇ˝Ì--Ìç-R˝Ì}mR‚	˝ÌΩ]M›çRÌçç≠É•∆‚"≤ˆ&uˆ∆7EˆW'&˜'5˜FWáBÇíê¢&WGW&‚f«6P¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç'&W∆6V&rW'&˜#¢W2"¬Rê¢ˆ&uˆÊ˜FUˆW'&˜"Üb'&W∆6V&rWÜ6WFñˆ„¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›R=MΩÌ¬}Õ]›ç-¬MÌ“‚	˝ÌΩ]M›çRÌçç≠É•∆‚"≤ˆ&uˆ∆7EˆW'&˜'5˜FWáBÇíê¢&WGW&‚f«6P††¶7ñÊ2FVb˜VFóEˆ˜WGñÁBáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬ñ÷uˆ'óFW3¢'óFW2ì†¢ñbÊ˜B6ˆÁFWáBÁW6W%ˆFFÁ˜Ç%ˆñ÷vU˜&ˆ6W76ñÊu˜V˜Fˆˆ≤"¬f«6Rì†¢7ñÊ2FVbˆvÚÇì†¢6ˆÁFWáBÁW6W%ˆFF≤%ˆñ÷vU˜&ˆ6W76ñÊu˜V˜Fˆˆ≤%““G'VP¢&WGW&‚vóB˜VFóEˆ˜WGñÁBáWFFR¬6ˆÁFWáB¬ñ÷uˆ'óFW2ê¢vóB˜G'ï˜ï˜FÜVÂˆFÚÄ¢WFFR¬6ˆÁFWáB¬WFFRÊVffV7FófU˜W6W"ÊñB¿¢&ñ÷r"¬î‘uı$Ù4U55Ù4ı5EıU4B¬ˆvÚ¿¢&V÷V÷&W%ˆ∂ñÊC“&˜WGñÁB"¿¢ê¢&WGW&‡¢ñbñ÷vRó2ÊˆÊS†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ%ñ∆∆˜r›R=-›Ì-Ω]“‚"ê¢&WGW&‚f«6P¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2ííÊ6ˆÁfW'BÇ%$t""ê¢B“÷ÇÉcB¬÷ñ‚É#Sb¬÷ÇÜñ“Á6ó¶RíÚÛbíê¢&ñr“ñ÷vRÊÊWrÇ%$t""¬Üñ“ÁvñGFÇ≤"ßB¬ñ“ÊÜVñváB≤"ßBíê¢&r“ñ“Á&W6ó¶RÜ&ñrÁ6ó¶R¬ñ÷vR‰ƒ‰5§ı2íÊfñ«FW"Ññ÷vTfñ«FW"‰vW76ñ‰&«W"á&FóW3”#Bííñbñ÷vTfñ«FW"V«6Rñ“Á&W6ó¶RÜ&ñrÁ6ó¶Rê¢&ñrÁ7FRÜ&r¬É¬íì≤&ñrÁ7FRÜñ“¬áB¬Bíê¢&ñÚ“'óFW4îÚÇì≤&ñrÁ6fRÜ&ñÚ¬f˜&÷C“$•Tr"¬V∆óGì”ì"ì≤&ñÚÁ6VV≤Éì≤&ñÚÊÊ÷R“&˜WGñÁBÊßr ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜Ü˜FÚÑñÁWDfñ∆RÜ&ñÚí¬6Fñˆ„“-	˝Ì-Ìí˜WGñÁC¢ççç≤˝ÌΩÌ-›‚Õ˝=≠çÕÇ≠˝ÕÇ‚"ê¢&WGW&‚G'VP¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç&˜WGñÁBW'&˜#¢W2"¬Rê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›R=MΩÌ¬M]Ω-¬˜WGñÁB‚"ê¢&WGW&‚f«6P†¶7ñÊ2FVb˜VFóE˜7F˜'ñ&ˆ&BáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬ñ÷uˆ'óFW3¢'óFW2ì†¢G'ì†¢#cB“&6ScBÊ#cFVÊ6ˆFRÜñ÷uˆ'óFW2íÊFV6ˆFRÇ&66ñí"ê¢FW62“vóB6µˆ˜VÊï˜fó6ñˆ‚Ç-	Ì˝ççÇ≠ΩÌ}]-ΩR›Ω]Õ]›-≤≠MÌ}]›¬≠-≠‚‚"¬#cB¬6Êñfeˆñ÷vUˆ÷ñ÷RÜñ÷uˆ'óFW2íê¢∆‚“vóB6µˆ˜VÊï˜FWáBÄ¢-
M]Ωí≠MÌ-≠2Éb≠MÌ"í˝ÌBn(	3]≠=›M›Ωí≠ΩçÚ‚ ¢-	≠mMΩí≠M(	B-Ì≠¢≠M˝M]ù--çR˝≠=˝-]"‚	Ì›Ì-•∆‚"≤ÜFW62˜"""ê¢ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-
≠MÌ-≠•Õ“"≤∆‚ê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç'7F˜'ñ&ˆ&BW'&˜#¢W2"¬Rê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›R=MΩÌ¬˝Ì-Ìç-¬≠MÌ-≠2‚"ê†††¢2)H)H)H)H)H)H)H)H)Hf6R7v&ˆGV7Fñˆ‚ÜV«W'2)H)H)H)H)H)H)H)H)H •ˆf6W7v˜F&vWEˆ66ÜR“∑“2W6W%ˆñB”‚'óFW3¢Ü˜FÚvÜW&Rf6R◊W7B&R&W∆6V@•ˆf6W7v˜6˜W&6Uˆ66ÜR“∑“2W6W%ˆñB”‚'óFW3¢f6R˜&VfW&VÊ6RÜ˜F•ˆf6W7v˜F&vWEˆf6UˆñÊFWÖˆ66ÜR“∑“2W6W%ˆñB”‚6Vv÷ñÊBÙíf6RñÊFWÇñ‚F&vWBñ÷vP•ˆf6W7v˜6˜W&6Uˆf6UˆñÊFWÖˆ66ÜR“∑“2W6W%ˆñB”‚6Vv÷ñÊBÙíf6RñÊFWÇñ‚6˜W&6Rñ÷vP•ˆf6W7v˜F&vWEˆf6Uˆ6˜VÁEˆ66ÜR“∑“2W6W%ˆñB”‚FWFV7FVBF&vWBf6W26˜VÁ@•ˆf6W7v˜6˜W&6Uˆf6Uˆ6˜VÁEˆ66ÜR“∑“2W6W%ˆñB”‚FWFV7FVB6˜W&6Rf6W26˜VÁ@•ˆf6W7v˜F&vWEˆf6W5ˆ66ÜR“∑“2W6W%ˆñB”‚FWFV7FVBF&vWBf6W2∆ó7BvóFÇ&˜ÜW0•ˆf6W7v˜6˜W&6Uˆf6W5ˆ66ÜR“∑“2W6W%ˆñB”‚FWFV7FVB6˜W&6Rf6W2∆ó7BvóFÇ&˜ÜW0•ˆf6W7vˆW'&˜'2“µ–††¶FVbˆf6W7vˆÊ˜FUˆW'&˜"Ü◊6s¢7G"ì†¢G'ì†¢◊6r“7G"Ü◊6ríÁ7G&óÇê¢ñbÊ˜B◊6s†¢&WGW&‡¢ˆf6W7vˆW'&˜'2ÊVÊBÜ◊6u≥£#“ê¢FV¬ˆf6W7vˆW'&˜'5≥¢”Ö–¢∆ˆrÁv&ÊñÊrÇ&f6W7v¢W2"¬◊6rê¢WÜ6WBWÜ6WFñˆ„†¢70††¶FVbˆf6W7vˆ∆7EˆW'&˜'5˜FWáBÇí”‚7G#†¢ñbÊ˜Bˆf6W7vˆW'&˜'3†¢&WGW&‚-ÌççÌ¢˝Ì≠›]" ¢&WGW&‚%∆‚"Ê¶ˆñ‚Ç.(
""≤Rf˜"Rñ‚ˆf6W7vˆW'&˜'5≤”S•“ê††¶FVbˆf6W7vˆ7c%˜7FGW2Çí”‚7G#†¢ñbÊ˜Bd4U5tÙd4UÙDUDT5DîÙÂÙT‰$ƒTC†¢&WGW&‚&Fó6&∆VEˆ'ïˆVÁb ¢G'ì†¢ñ◊˜'B7c"2GóS¢ñvÊ˜&P¢fW"“vWFGG"Ü7c"¬%ı˜fW'6ñˆÂıÚ"¬""ê¢ñbÊ˜BÜ6GG"Ü7c"¬$666FT6∆76ñfñW""ì†¢&WGW&‚b$%$Ù¥T‚∑fW'”¢ÊÚ666FT6∆76ñfñW""Á7G&óÇê¢ñbÊ˜BÜ6GG"Ü7c"¬&FF"í˜"Ê˜BvWFGG"Ü7c"ÊFF¬&Ü&666FW2"¬""ì†¢&WGW&‚b$%$Ù¥T‚∑fW'”¢ÊÚÜ&666FW2"Á7G&óÇê¢&WGW&‚b&ˆ≤∑fW'“"Á7G&óÇê¢WÜ6WBWÜ6WFñˆ‚2S†¢&WGW&‚b$dîƒTB∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“ ††¶7ñÊ2FVb6÷EˆFñuˆf6RáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢∆ñÊW2“∞¢b/	˙z¢f6U7vFñvÊ˜7Fñ2ÚµD4ÖıdU%4îÙÁ“"¿¢b$d4U5tÙT‰$ƒTC◊¥d4U5tÙT‰$ƒTG“&˜fñFW#◊¥d4U5tı$ıdîDU'“f∆∆&6≥◊¥d4U5tÙdƒƒ$4µı$ıdîDU'“"¿¢b&f7E˜&˜fñFW#◊¥d4U5tÙd5Eı$ıdîDU'“&V÷óV’˜&˜fñFW#◊¥d4U5tı$T‘ïT’ı$ıdîDU'“"¿¢b'F&vWEˆ6Üˆñ6S◊¥d4U5tÙ4µıD$tUEÙd4W“6˜W&6Uˆ6Üˆñ6S◊¥d4U5tÙ4µı4ıU$4UÙd4W“7G&ñ7E˜6V∆V7FVC◊¥d4U5tı5E$î5Eı4TƒT5DTEÙd4W“"¿¢b&÷ÁV≈ˆ6Üˆñ6UˆñeˆFWFV7FñˆÂˆfñ√◊¥d4U5tÙ‘ÂT≈Ù4ÑÙî4UÙîeÙDUDT5DîÙÂÙdî«“"¿¢b&f6UˆFWFV7Fñˆ„◊¥d4U5tÙd4UÙDUDT5DîÙÂÙT‰$ƒTG“7c#◊µˆf6W7vˆ7c%˜7FGW2Çó“FWFV7Eˆ÷É◊¥d4U5tÙDUDT5DîÙÂÙ‘Öı4îDW“&WfñWuˆ÷É◊¥d4U5tı$UdîUuÙ‘Öı4îDW“"¿¢b'&V6ó6Uˆ6ˆ◊˜6óFS◊¥d4U5tı$T4ï4UÙ4Ù’ı4ïDW“f˜&6U˜6Vv÷ñÊEˆ◊V«Fì◊¥d4U5tÙdı$4Uı4Tt‘î‰EÙdı%Ù’T≈Dó“6Vv÷ñÊEˆf∆∆&6≥◊¥d4U5tÙu$ıUÙƒƒıuı4Tt‘î‰EÙdƒƒ$4∑“"¿¢b&f6Uˆfñ«FW%˜&FñÛ◊¥d4U5tÙd4UÙ$ıÖÙdî≈DU%ı$Dî˜“6˜W&6Uˆ7&˜◊¥d4U5tı4ıU$4UÙ5$ıÙ‘$tîÁ“ÜñFUˆ÷&vñ„◊¥d4U5tıD$tUEÙÑîDUÙ‘$tîÁ“"¿¢b%îïÙïÙ¥Uì◊≤vˆ‚rñbîïÙïÙ¥UíV«6Rvˆfbw“&6S◊µîïÙ$4UıU$«“÷ˆFV√◊µîïÙd4UÙ‘ÙDT«“F6≥◊µîïÙd4UıD4µıEïW“"¿¢b%4Tt‘î‰EÙïÙ¥Uì◊≤vˆ‚rñb4Tt‘î‰EÙïÙ¥UíV«6Rvˆfbw“&6S◊µ4Tt‘î‰EÙ$4UıU$«“f7C◊µ4Tt‘î‰EÙd4U5tÙ‘ÙDT≈Ùd5G“&V÷óV”◊µ4Tt‘î‰EÙd4U5tÙ‘ÙDT≈ı$T‘ïT◊“"¿¢b'Fñ÷V˜WC◊¥d4U5tıDî‘TıUEı7◊2ˆ∆√◊¥d4U5tıÙƒ≈ÙDTƒïı7◊2ñÁWEˆ÷É◊¥d4U5tÙîÂUEÙ‘Öı4îDW“˜WGWEˆ÷É◊¥d4U5tÙıUEUEÙ‘Öı4îDW“"¿¢-	˝ÌΩ]M›çRÌçç≠É¢"¿¢ˆf6W7vˆ∆7EˆW'&˜'5˜FWáBÇí¿¢–¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ%∆‚"Ê¶ˆñ‚Ü∆ñÊW2ï≥£3ì“ê††¶FVbf6U˜7v˜V∆óGïˆ∂"Çì†¢&WGW&‚ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb.)™	Ω-‚+rµ˜&WFñ≈ˆ7&VFóG2Ñd4U5tÙd5EÙ4ı5EıU4Bó“≠‚"¬6∆∆&6µˆFF“&f6W7vß'V„¶f7B"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb/	˘(‚	˝]Õç=¬+rµ˜&WFñ≈ˆ7&VFóG2Ñd4U5tı$T‘ïT’Ù4ı5EıU4Bó“≠‚"¬6∆∆&6µˆFF“&f6W7vß'V„ß&V÷óV“"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.*»^˚àÚ	›}B"¬6∆∆&6µˆFF“'VFóC¶&6≤"ï“¿¢“ê††¶FVbˆó5ˆf6U˜7v˜&WVW7BáFWáC¢7G"í”‚&ˆˆ√†¢F¬“áFWáB˜"""íÁ7G&óÇíÊ∆˜vW"ÇíÁ&W∆6RÇ-"¬-R"ê¢&WGW&‚ÁíÜ≤ñ‚F¬f˜"≤ñ‚Ä¢-}Õ]›ÇΩçm‚"¬-}Õ]›ç-¬Ωçm‚"¬-˝ÌÕ]›˝íΩçm‚"¬-˝ÌÕ]›˝-¬Ωçm‚"¬-˝ÌM--¬Ωçm‚"¬----¬Ωçm‚"¿¢&f6R7v"¬&f6W7v"¬'7vf6R"¬'&W∆6Rf6R"¬-Õ]›Ωçm"¬-}Õ]›Ωçm ¢íê††¶FVb˜6WEˆf6W7v˜vóE˜6˜W&6RÜ6ˆÁFWáB¬F&vWEˆ'óFW3¢'óFW2ì†¢2
]ΩÕ›ΩíW6W%ˆñB˝Ì≠çMΩ-]¬Ì-M]ΩÕ›‚"-Ω}Ì-R}]]rˆf6W7v˜F&vWEˆ66ÜR‡¢6ˆÁFWáBÁW6W%ˆFF≤&f6W7vˆf∆˜r%““&vóE˜6˜W&6R ††¶FVbˆ6∆V%ˆf6W7vˆf∆˜rÜ6ˆÁFWáBì†¢f˜"≤ñ‚Ç&f6W7vˆf∆˜r"¬&vóFñÊu˜Ü˜Fıˆf˜""ì†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ü≤¬ÊˆÊRê††¶FVbˆ6∆V%ˆf6W7v˜W6W%ˆ66ÜRáW6W%ˆñC¢ñÁBì†¢f˜"Bñ‚Ä¢ˆf6W7v˜F&vWEˆ66ÜR¬ˆf6W7v˜6˜W&6Uˆ66ÜR¿¢ˆf6W7v˜F&vWEˆf6UˆñÊFWÖˆ66ÜR¬ˆf6W7v˜6˜W&6Uˆf6UˆñÊFWÖˆ66ÜR¿¢ˆf6W7v˜F&vWEˆf6Uˆ6˜VÁEˆ66ÜR¬ˆf6W7v˜6˜W&6Uˆf6Uˆ6˜VÁEˆ66ÜR¿¢ˆf6W7v˜F&vWEˆf6W5ˆ66ÜR¬ˆf6W7v˜6˜W&6Uˆf6W5ˆ66ÜR¿¢ì†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢BÁ˜áW6W%ˆñB¬ÊˆÊRê††¶FVbˆf6W7v˜F&vWEˆf˜"áW6W%ˆñC¢ñÁBí”‚'óFW2¬ÊˆÊS†¢&WGW&‚ˆf6W7v˜F&vWEˆ66ÜRÊvWBáW6W%ˆñBê††¶FVbˆf6W7v˜6˜W&6Uˆf˜"áW6W%ˆñC¢ñÁBí”‚'óFW2¬ÊˆÊS†¢&WGW&‚ˆf6W7v˜6˜W&6Uˆ66ÜRÊvWBáW6W%ˆñBê††¶FVbˆf6W7v˜6V∆V7FVE˜F&vWEˆñÊFWÇáW6W%ˆñC¢ñÁBí”‚ñÁC†¢&WGW&‚ñÁBÖˆf6W7v˜F&vWEˆf6UˆñÊFWÖˆ66ÜRÊvWBáW6W%ˆñB¬í˜"ê††¶FVbˆf6W7v˜6V∆V7FVE˜6˜W&6UˆñÊFWÇáW6W%ˆñC¢ñÁBí”‚ñÁC†¢&WGW&‚ñÁBÖˆf6W7v˜6˜W&6Uˆf6UˆñÊFWÖˆ66ÜRÊvWBáW6W%ˆñB¬í˜"ê††¶FVb˜&W6ó¶Uˆñ÷vUˆ'óFW5ˆf˜%ˆf6W7vˆíÜñ÷uˆ'óFW3¢'óFW2¬÷Ö˜6ñFS¢ñÁB¬ÊˆÊR“ÊˆÊRí”‚GW∆U∂'óFW2¬7G"¬7G%”†¢÷Ö˜6ñFR“ñÁBÜ÷Ö˜6ñFR˜"d4U5tÙîÂUEÙ‘Öı4îDR˜"cê¢÷ñ÷R“6Êñfeˆñ÷vUˆ÷ñ÷RÜñ÷uˆ'óFW2í˜"&ñ÷vRˆßVr ¢ñbñ÷vRó2ÊˆÊR˜"÷Ö˜6ñFR√“†¢WáB“"Êßr"ñb÷ñ÷R”“&ñ÷vRˆßVr"V«6RÇ"ÁÊr"ñb÷ñ÷R”“&ñ÷vR˜Êr"V«6R"ÁvV'"ê¢&WGW&‚ñ÷uˆ'óFW2¬b&f6W7v∂WáG“"¬÷ñ÷P¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2íê¢ñ““ñ÷vT˜2ÊWÜñe˜G&Á7˜6RÜñ“íñbñ÷vT˜2V«6Rñ–¢ñb÷ÇÜñ“Á6ó¶Rí‚÷Ö˜6ñFS†¢ñ“ÁFáV÷&Êñ¬ÇÜ÷Ö˜6ñFR¬÷Ö˜6ñFRí¬ñ÷vR‰ƒ‰5§ı2ê¢ñbñ“Ê÷ˆFRÊ˜Bñ‚Ç%$t""¬$¬"ì†¢ñ““ñ“Ê6ˆÁfW'BÇ%$t""ê¢&ñÚ“'óFW4îÚÇê¢ñ“Á6fRÜ&ñÚ¬f˜&÷C“$•Tr"¬V∆óGì”ì2¬˜Fñ÷ó¶S’G'VR¬&ˆw&W76ófS’G'VRê¢&WGW&‚&ñÚÊvWGf«VRÇí¬&f6W7vÊßr"¬&ñ÷vRˆßVr ¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb&f6W7vñÁWB&W6ó¶Rfñ∆VC¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢WáB“"Êßr"ñb÷ñ÷R”“&ñ÷vRˆßVr"V«6RÇ"ÁÊr"ñb÷ñ÷R”“&ñ÷vR˜Êr"V«6R"ÁvV'"ê¢&WGW&‚ñ÷uˆ'óFW2¬b&f6W7v∂WáG“"¬÷ñ÷P††¶FVbˆ#cEˆf˜%ˆf6W7vÜñ÷uˆ'óFW3¢'óFW2í”‚7G#†¢"¬ˆÊ÷R¬÷ñ÷R“˜&W6ó¶Uˆñ÷vUˆ'óFW5ˆf˜%ˆf6W7vˆíÜñ÷uˆ'óFW2¬d4U5tÙîÂUEÙ‘Öı4îDRê¢&r“&6ScBÊ#cFVÊ6ˆFRÜ"íÊFV6ˆFRÇ&66ñí"ê¢ñbd4U5tÙî‘tUÙDDıU$√†¢&WGW&‚b&FFß∂÷ñ÷W”∂&6ScB«∑&w“ ¢&WGW&‚&p††¶FVbˆÊ˜&÷∆ó¶Uˆ˜WGWEˆñ÷vUˆ'óFW2Üñ÷uˆ'óFW3¢'óFW2í”‚'óFW3†¢ñbñ÷vRó2ÊˆÊR˜"Ê˜Bñ÷uˆ'óFW2˜"d4U5tÙıUEUEÙ‘Öı4îDR√“†¢&WGW&‚ñ÷uˆ'óFW0¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2íê¢ñ““ñ÷vT˜2ÊWÜñe˜G&Á7˜6RÜñ“íñbñ÷vT˜2V«6Rñ–¢ñb÷ÇÜñ“Á6ó¶Rí‚d4U5tÙıUEUEÙ‘Öı4îDS†¢ñ“ÁFáV÷&Êñ¬ÇÑd4U5tÙıUEUEÙ‘Öı4îDR¬d4U5tÙıUEUEÙ‘Öı4îDRí¬ñ÷vR‰ƒ‰5§ı2ê¢˜WB“'óFW4îÚÇê¢ñbñ“Ê÷ˆFRñ‚Ç%$t$"¬$ƒ"ì†¢ñ“Á6fRÜ˜WB¬f˜&÷C“%‰r"¬˜Fñ÷ó¶S’G'VRê¢V«6S†¢ñ““ñ“Ê6ˆÁfW'BÇ%$t""ê¢ñ“Á6fRÜ˜WB¬f˜&÷C“$•Tr"¬V∆óGì”ìB¬˜Fñ÷ó¶S’G'VR¬&ˆw&W76ófS’G'VRê¢&WGW&‚˜WBÊvWGf«VRÇê¢WÜ6WBWÜ6WFñˆ„†¢&WGW&‚ñ÷uˆ'óFW0††¶FVbˆ÷ñ&U˜&W6ó¶Uˆ˜WGWEˆñ÷vRÜñ÷uˆ'óFW3¢'óFW2í”‚'óFW3†¢""$&6∑v&B÷6ˆ◊Fñ&∆R˜WGWB&W6ó¶RÜV«W"W6VB'íf6R7vóV∆ñÊR‚"" ¢&WGW&‚ˆÊ˜&÷∆ó¶Uˆ˜WGWEˆñ÷vUˆ'óFW2Üñ÷uˆ'óFW2ê††¶FVbˆFWFV7Eˆf6W5ˆf˜%ˆ6Üˆñ6RÜñ÷uˆ'óFW3¢'óFW2í”‚∆ó7E∂Fñ7E”†¢""-	Ì˝]M]Ω]›çRΩçbMΩÚTíÇ-ΩÌç›M]≠Ì"‡†¢	-m›Ωí˝≠-ç}]≠çíÕÌÕ]›#¢"]ΩÕ›ΩR-]-R˝Ì-ùM]≤-]ΩÇ]Ú-çΩÕ›]R¿¢≠Ì=Mç›M]≠≤Ωçb˝]]M-Ωç¬"-ç}=ΩÕ›Ì¬˝Ì˝M≠RΩ]-(i-›˝-‚‡¢	˝Ì›-ÌÕ2ïˆñÊFWÇ}M]¬ç›]Ì›ç}çÌ-“Fó7∆ïˆñÊFWÇ¬›RÌ-çÌ-≠Ìí˝‚}Õ]2‡¢	MÌ˝ÌΩ›ç-]ΩÕ›‚]m]¬ΩÌm›ΩR-Ω-›çÚçÕ]Ω≠çRÌ≠≤›ÌM]mMR˝MÌ›Rí‡¢"" ¢ñbÊ˜Bd4U5tÙd4UÙDUDT5DîÙÂÙT‰$ƒTB˜"ñ÷vRó2ÊˆÊS†¢&WGW&‚µ–¢G'ì†¢ñ◊˜'B7c"2GóS¢ñvÊ˜&P¢ñ◊˜'BÁV◊í2Á2GóS¢ñvÊ˜&P†¢FVbˆñ˜RÜ¢Fñ7B¬#¢Fñ7Bí”‚f∆ˆC†¢É¬ì¬É"¬ì"“≤'Ç%“¬≤'í%“¬≤'Ç%“≤≤'r%“¬≤'í%“≤≤&Ç%–¢'É¬'ì¬'É"¬'ì"“%≤'Ç%“¬%≤'í%“¬%≤'Ç%“≤%≤'r%“¬%≤'í%“≤%≤&Ç%–¢óÉ¬óì“÷ÇÜÉ¬'Éí¬÷ÇÜì¬'ìê¢óÉ"¬óì"“÷ñ‚ÜÉ"¬'É"í¬÷ñ‚Üì"¬'ì"ê¢ór¬ñÇ“÷ÇÉ¬óÉ"“óÉí¬÷ÇÉ¬óì"“óìê¢ñÁFW"“ór¢ñÄ¢ñbñÁFW"√“†¢&WGW&‚„ ¢VÊñˆ‚“≤&&V%“≤%≤&&V%““ñÁFW ¢&WGW&‚ÜñÁFW"ÚVÊñˆ‚íñbVÊñˆ‚‚V«6R„ †¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2íê¢ñ““ñ÷vT˜2ÊWÜñe˜G&Á7˜6RÜñ“íñbñ÷vT˜2V«6Rñ–¢ñ““ñ“Ê6ˆÁfW'BÇ%$t""ê¢˜&ñu˜r¬˜&ñuˆÇ“ñ“Á6ó¶P¢ñ÷uˆ&V“÷ÇÉ¬˜&ñu˜r¢˜&ñuˆÇê¢66∆R“„ ¢÷Ö˜6ñFR“ñÁBÑd4U5tÙDUDT5DîÙÂÙ‘Öı4îDR˜"#ê¢ñb÷Ö˜6ñFR‚ÊB÷ÇÜ˜&ñu˜r¬˜&ñuˆÇí‚÷Ö˜6ñFS†¢66∆R“÷Ö˜6ñFRÚf∆ˆBÜ÷ÇÜ˜&ñu˜r¬˜&ñuˆÇíê¢ñ’ˆFWB“ñ“Á&W6ó¶RÇÜ÷ÇÉ¬ñÁBÜ˜&ñu˜r¢66∆Ríí¬÷ÇÉ¬ñÁBÜ˜&ñuˆÇ¢66∆Rííí¬ñ÷vR‰ƒ‰5§ı2ê¢V«6S†¢ñ’ˆFWB“ñ–¢'"“ÁÊ'&íÜñ’ˆFWBê¢w&í“7c"Ê7gD6ˆ∆˜"Ü'"¬7c"‰4Ùƒı%ı$t#$u$íê¢666FU˜FÇ“˜2ÁFÇÊ¶ˆñ‚Ü7c"ÊFFÊÜ&666FW2¬&Ü&666FUˆg&ˆÁF∆f6UˆFVfV«BÁÜ÷¬"ê¢666FR“7c"‰666FT6∆76ñfñW"Ü666FU˜FÇê¢ñb666FRÊV◊GíÇì†¢ˆf6W7vˆÊ˜FUˆW'&˜"Ç&7c"Ü&666FUˆg&ˆÁF∆f6UˆFVfV«BÁÜ÷¬Ê˜B∆ˆFVB"ê¢&WGW&‚µ–¢f6W2“666FRÊFWFV7D◊V«Fï66∆RÜw&í¬66∆Tf7F˜#”„Ç¬÷ñ‰ÊVñvÜ&˜'3”R¬÷ñÂ6ó¶S“ÉC¬Cíê¢óFV◊2“µ–¢f˜"áÇ¬í¬r¬Çíñ‚f6W3†¢˜Ç“ñÁBá&˜VÊBáÇÚ66∆Ríì≤˜í“ñÁBá&˜VÊBáíÚ66∆Ríì≤˜r“ñÁBá&˜VÊBárÚ66∆Ríì≤ˆÇ“ñÁBá&˜VÊBÜÇÚ66∆Ríê¢ñb˜r¬#B˜"ˆÇ¬#C†¢6ˆÁFñÁVP¢&V“˜r¢ˆÄ¢2Ωçç≠Ì¬ÕΩ]›Õ≠çRÌ≠≤˝Ì}-Ç-]=MΩÌm›ΩR-Ω-›ç¢ñb&V¬÷ÇÉc¬ñÁBÜñ÷uˆ&V¢„Bíì†¢6ˆÁFñÁVP¢&FñÚ“Ü˜rÚf∆ˆBÜ÷ÇÉ¬ˆÇííê¢2Ωçç≠Ì¬-Ω-˝›=-ΩRÌ≠≤MΩÚ-ΩÌΩçm˝Ì}-Ç-]=Mç=¿¢ñb&FñÚ¬„cR˜"&FñÚ‚„CS†¢6ˆÁFñÁVP¢7Ç¬7í“˜Ç≤˜rÚ"¬˜í≤ˆÇÚ ¢óFV◊2ÊVÊBá≤'Ç#¢˜Ç¬'í#¢˜í¬'r#¢˜r¬&Ç#¢ˆÇ¬&&V#¢&V¬&7Ç#¢7Ç¬&7í#¢7ó“ê†¢ñbÊ˜BóFV◊3†¢&WGW&‚µ–†¢2‰’2ÚM]M=˝Ωç≠mçÚçΩÕ›‚˝]]≠Ω-Ìùç]ÚÌ≠Ì ¢FVGW“µ–¢f˜"bñ‚6˜'FVBÜóFV◊2¬∂Wì÷∆÷&F£¢•≤&&V%“¬&WfW'6S’G'VRì†¢ñbÁíÖˆñ˜RÜb¬∂WBí„“„3Rf˜"∂WBñ‚FVGWì†¢6ˆÁFñÁVP¢FVGWÊVÊBÜbê¢óFV◊2“FVGW †¢ñbÊ˜BóFV◊3†¢&WGW&‚µ–†¢2c3S¢ΩÌm›ΩRÌ≠≤›mçΩ]-R˝ÌM]mMR˝-]›R}-‚ΩΩÇÕ]›ÕçR]ΩÕ›ΩRΩçb‡¢2	MΩÚ-ΩÌΩçm"˝ÌM≠ç›RΩ=}çR˝Ì˝=-ç-¬Ì}]›¬Õ]Ω≠çRÌ≠≤¬}]¬M-¬˝ÌΩÕ}Ì--]Ω‡¢2-Ω-¬-Ωçm‚"¬≠Ì-ÌÌR˝Ì-ùM]}-]¬›RÕÌm]"Ì˝Ì--ç-¬‡¢ñb∆V‚ÜóFV◊2í‚†¢∆&vW7Eˆ&V“÷Çá•≤&&V%“f˜"¢ñ‚óFV◊2ê¢÷ñÂˆ∂VW“÷ÇÜñÁBÜ∆&vW7Eˆ&V¢÷ÇÉ„¬÷ñ‚É„É¬d4U5tÙd4UÙ$ıÖÙdî≈DU%ı$DîÚííí¬ñÁBÜñ÷uˆ&V¢„bíê¢óFV◊2“∑¢f˜"¢ñ‚óFV◊2ñb•≤&&V%“„“÷ñÂˆ∂VW–¢ñbÊ˜BóFV◊3†¢&WGW&‚µ–†¢2	]ΩÇ˝-›‚MÌÕç›ç=]"ÌM›‚Ωçm‚ç-ç˝ç}›Ωí]ΩMÇ›ç-Ì}›ç¢í¿¢2Ì-Ω-]¬Õ]Ω≠çRΩÌm›ΩRÌ≠≤›˝Ω]}R˝MÌ›R‡¢∆&vW7B“÷ÇÜóFV◊2¬∂Wì÷∆÷&F£¢•≤&&V%“ê¢6V6ˆÊEˆ&V“÷ÇÖ∑•≤&&V%“f˜"¢ñ‚óFV◊2ñb¢ó2Ê˜B∆&vW7E“˜"≥“ê¢Fˆ÷ñÊÁB“∆&vW7E≤&&V%“„“÷ÇÉ"„¢6V6ˆÊEˆ&V¬ñÁBÜñ÷uˆ&V¢„2íê¢ñbFˆ÷ñÊÁC†¢fñ«B“µ–¢f˜"bñ‚óFV◊3†¢ñbbó2∆&vW7C†¢fñ«BÊVÊBÜbê¢6ˆÁFñÁVP¢ñbe≤&&V%“„“∆&vW7E≤&&V%“¢„CS†¢fñ«BÊVÊBÜbê¢óFV◊2“fñ«@†¢2	ç-Ì=Ì-Ωí˝Ì˝MÌ£¢Ω]-›˝-‚¬}-]¬-]]2-›çr‡¢2
-≠ÌímRç›M]≠˝]]M¬˝Ì-ùM]2‡¢Fó7∆í“6˜'FVBÜóFV◊2¬∂Wì÷∆÷&Fc¢Üe≤&7Ç%“¬e≤&7í%“íï≥£Ö–¢f˜"í¬bñ‚VÁV÷W&FRÜFó7∆í¬ì†¢e≤&Fó7∆ïˆñÊFWÇ%““ê¢e≤&ïˆñÊFWÇ%““í“¢ñb∆V‚ÜFó7∆íí”“#†¢e≤'˜5ˆ∆&V¬%““-Ω]-"ñbí”“V«6R-˝- ¢V∆ñb∆V‚ÜFó7∆íí”“3†¢e≤'˜5ˆ∆&V¬%““≤-Ω]-"¬-m]›-"¬-˝-%’∂í“–¢V«6S†¢e≤'˜5ˆ∆&V¬%““b-Ωçm‚∂ó“ ¢&WGW&‚Fó7∆ê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb&f6RFWFV7Fñˆ‚fñ∆VC¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢&WGW&‚µ–††¶FVbˆf6Uˆ6Üˆñ6U˜&WfñWuˆ'óFW2Üñ÷uˆ'óFW3¢'óFW2¬f6W3¢∆ó7E∂Fñ7E“¬FóF∆S¢7G"“-	-Ω]ç-RΩçm‚"í”‚'óFW2¬ÊˆÊS†¢ñbñ÷vRó2ÊˆÊR˜"ñ÷vTG&ró2ÊˆÊR˜"Ê˜Bf6W3†¢&WGW&‚ÊˆÊP¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2íê¢ñ““ñ÷vT˜2ÊWÜñe˜G&Á7˜6RÜñ“íñbñ÷vT˜2V«6Rñ–¢ñ““ñ“Ê6ˆÁfW'BÇ%$t""ê¢66∆R“„ ¢÷Ö˜6ñFR“ñÁBÑd4U5tı$UdîUuÙ‘Öı4îDR˜"#ê¢ñb÷Ö˜6ñFR‚ÊB÷ÇÜñ“Á6ó¶Rí‚÷Ö˜6ñFS†¢66∆R“÷Ö˜6ñFRÚf∆ˆBÜ÷ÇÜñ“Á6ó¶Ríê¢ñ““ñ“Á&W6ó¶RÇÜ÷ÇÉ¬ñÁBÜñ“ÁvñGFÇ¢66∆Ríí¬÷ÇÉ¬ñÁBÜñ“ÊÜVñváB¢66∆Rííí¬ñ÷vR‰ƒ‰5§ı2ê¢G&r“ñ÷vTG&r‰G&rÜñ“ê¢G'ì†¢fˆÁEˆ&ñr“ñ÷vTfˆÁBÁG'VWGóRÇ$FV¶gU6Á2‘&ˆ∆BÁGFb"¬÷ÇÉ#B¬ñÁBÉC"¢66∆Rííê¢fˆÁE˜6÷∆¬“ñ÷vTfˆÁBÁG'VWGóRÇ$FV¶gU6Á2‘&ˆ∆BÁGFb"¬÷ÇÉB¬ñÁBÉ#"¢66∆Rííê¢WÜ6WBWÜ6WFñˆ„†¢fˆÁEˆ&ñr“ÊˆÊP¢fˆÁE˜6÷∆¬“ÊˆÊP¢2FóF∆R7G&ó ¢G&rÁ&V7FÊv∆RÖ≥¬¬ñ“ÁvñGFÇ¬÷ñ‚Üñ“ÊÜVñváB¬CBï“¬fñ∆√“É¬¬íê¢G&rÁFWáBÇÉ"¬Çí¬FóF∆R¬fñ∆√“É#SR¬#SR¬#SRí¬fˆÁC÷fˆÁE˜6÷∆¬ê¢f˜"bñ‚f6W3†¢Ç“ñÁBÜe≤'Ç%“¢66∆Rì≤í“ñÁBÜe≤'í%“¢66∆Rì≤r“ñÁBÜe≤'r%“¢66∆Rì≤Ç“ñÁBÜe≤&Ç%“¢66∆Rê¢∆&V¬“7G"ÜbÊvWBÇ&Fó7∆ïˆñÊFWÇ"í˜"bÊvWBÇ&ïˆñÊFWÇ"í˜"ê¢2	mΩ-ÚÕ≠≤}›Ú˝ÌMΩÌm≠›ÌÕ]]ÌÌç‚-çM›≤"FV∆Vw&“‡¢f˜"ˆfbñ‚&ÊvRÉBì†¢G&rÁ&V7FÊv∆RÖ∑Ç÷ˆfb¬í÷ˆfb¬Ç∑r∂ˆfb¬í∂Ç∂ˆfe“¬˜WF∆ñÊS“É#SR¬##¬íê¢«Ç¬«í“Ç¬÷ÇÉCB¬í“C"ê¢G&rÊV∆∆ó6RÖ∂«Ç¬«í¬«Ç≤C"¬«í≤C%“¬fñ∆√“É#SR¬##¬í¬˜WF∆ñÊS“É¬¬í¬vñGFÉ”"ê¢G&rÁFWáBÇÜ«Ç≤B¬«í≤bí¬∆&V¬¬fñ∆√“É¬¬í¬fˆÁC÷fˆÁEˆ&ñrê¢&ñÚ“'óFW4îÚÇê¢ñ“Á6fRÜ&ñÚ¬f˜&÷C“$•Tr"¬V∆óGì”ì"¬˜Fñ÷ó¶S’G'VRê¢&WGW&‚&ñÚÊvWGf«VRÇê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb&f6R6Üˆñ6R&WfñWrfñ∆VC¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢&WGW&‚ÊˆÊP††¶FVbˆf6Uˆ6Üˆñ6Uˆ∂"á7FvS¢7G"¬f6W3¢∆ó7E∂Fñ7E“í”‚ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑W†¢'WGFˆÁ2“µ–¢&˜r“µ–¢f˜"bñ‚f6W5≥£Ö”†¢Fó7“ñÁBÜbÊvWBÇ&Fó7∆ïˆñÊFWÇ"í˜"ê¢ïˆñGÇ“ñÁBÜbÊvWBÇ&ïˆñÊFWÇ"í˜"ê¢˜2“7G"ÜbÊvWBÇ'˜5ˆ∆&V¬"í˜"""ê¢FWáB“b'∂Fó7“(	B∑˜7“"ñb˜2ÊBÊ˜B˜2Á7F'G7vóFÇÇ-Ωçm‚"íV«6Rb-	Ωçm‚∂Fó7“ ¢&˜rÊVÊBÑñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚áFWáB¬6∆∆&6µˆFF÷b&f6W7vß∑7FvW”ß∂ïˆñGá“"íê¢ñb∆V‚á&˜rí”“#†¢'WGFˆÁ2ÊVÊBá&˜rì≤&˜r“µ–¢ñb&˜s†¢'WGFˆÁ2ÊVÊBá&˜rê¢'WGFˆÁ2ÊVÊBÖ¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.*»^˚àÚ	Ì-Õ]›"¬6∆∆&6µˆFF“'VFóC¶&6≤"ï“ê¢&WGW&‚ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÜ'WGFˆÁ2ê††¶FVbˆ÷ÁV≈ˆf6Uˆ6Üˆñ6Uˆ∂"á7FvS¢7G"í”‚ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑W†¢2
=}›Ìí-ΩÌ›=m]“¬]ΩÇM]-]≠-ÌΩçb›]MÌ-=˝]“˝ΩΩíçΩÇFV∆Vw&“˝çΩ≤ΩÌm›ÌR==˝˝Ì-ÌRMÌ-‚‡¢2	ç›M]≠≤˝]]MÌ-Ú˝Ì-ùM]¬≠¢F&vWEˆf6UˆñÊFWÇ˜6˜W&6Uˆf6UˆñÊFWÇ‡¢&WGW&‚ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˘Ç	Ωçm‚Ω]-"¬6∆∆&6µˆFF÷b&f6W7vß∑7FvW”£"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	¯ÍÚ	Ωçm‚"m]›-R"¬6∆∆&6µˆFF÷b&f6W7vß∑7FvW”£"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˘í	Ωçm‚˝-"¬6∆∆&6µˆFF÷b&f6W7vß∑7FvW”£""ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˙Ib	--‚Ú˝]-ÌRΩçm‚"¬6∆∆&6µˆFF÷b&f6W7vß∑7FvW”£"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.*»^˚àÚ	Ì-Õ]›"¬6∆∆&6µˆFF“'VFóC¶&6≤"ï“¿¢“ê††¶7ñÊ2FVbˆ6µˆf6W7v˜6˜W&6U˜Ü˜FÚáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢6ˆÁFWáBÁW6W%ˆFF≤&f6W7vˆf∆˜r%““&vóE˜6˜W&6R ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	¯Í“
-]˝]¬˝ççΩç-RMÌ-‚Ωçm¬≠Ì-ÌÌR›=m›‚---ç-¬Â∆Â∆‚ ¢-	-m›„¢ç˝ÌΩÕ}=ù-R-ÌΩÕ≠‚-ÌÇç}Ìm]›çÚçΩÇç}Ìm]›çÚ¬›≠Ì-ÌΩR2-]-¬˝-‚‚ ¢-	›]ΩÕ}Úç˝ÌΩÕ}Ì--¬M=›≠mç‚MΩÚÌÕ›¬ç›-m¬MÌ≠=Õ]›-Ì"¬ç›-çÕ›Ì=‚≠Ì›-]›-Ç-]MÌ›Ì›ΩR˝ÌMM]ΩÌ¢‚ ¢ê††¶7ñÊ2FVbˆ÷ñ&Uˆ6Üˆ˜6U˜F&vWEˆf6RáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬W6W%ˆñC¢ñÁB¬ñ÷s¢'óFW2ì†¢ˆf6W7v˜F&vWEˆ66ÜU∑W6W%ˆñE““ñ÷p¢f6W2“ˆFWFV7Eˆf6W5ˆf˜%ˆ6Üˆñ6RÜñ÷rê¢ˆf6W7v˜F&vWEˆf6W5ˆ66ÜU∑W6W%ˆñE““f6W0¢ˆf6W7v˜F&vWEˆf6Uˆ6˜VÁEˆ66ÜU∑W6W%ˆñE““∆V‚Üf6W2ê¢ˆf6W7v˜F&vWEˆf6UˆñÊFWÖˆ66ÜU∑W6W%ˆñE““ ¢ñbd4U5tÙ4µıD$tUEÙd4RÊB∆V‚Üf6W2í‚†¢6ˆÁFWáBÁW6W%ˆFF≤&f6W7vˆf∆˜r%““&6Üˆ˜6U˜F&vWEˆf6R ¢&WfñWr“ˆf6Uˆ6Üˆñ6U˜&WfñWuˆ'óFW2Üñ÷r¬f6W2¬-	≠Ì=‚}Õ]›ç-√Ú	-Ω]ç-R›ÌÕ]Ωçm"ê¢FWáB“/	¯Í“	›MÌ-‚›ùM]›‚›]≠ÌΩÕ≠‚Ωçb‚	-Ω]ç-R¬2≠≠Ì=‚}]ΩÌ-]≠}Õ]›ç-¬Ωçm‚‚ ¢ñb&WfñWs†¢&ñÚ“'óFW4îÚá&WfñWrì≤&ñÚÊÊ÷R“&f6W5˜F&vWEˆ6Üˆñ6RÊßr ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜Ü˜FÚÑñÁWDfñ∆RÜ&ñÚí¬6Fñˆ„◊FWáB¬&W«ïˆ÷&∑W’ˆf6Uˆ6Üˆñ6Uˆ∂"Ç'F&vWB"¬f6W2íê¢V«6S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBáFWáB¬&W«ïˆ÷&∑W’ˆf6Uˆ6Üˆñ6Uˆ∂"Ç'F&vWB"¬f6W2íê¢&WGW&‡¢ñbd4U5tÙ4µıD$tUEÙd4RÊBÊ˜Bf6W2ÊBd4U5tÙ‘ÂT≈Ù4ÑÙî4UÙîeÙDUDT5DîÙÂÙdî√†¢2	]ΩÇ˜V‰5b˝M]-]≠-Ì›R›ç≤Ωçm¬›R]¬›MÌÕ›ΩíñÊFWÇÕÌΩ}‡¢2	M¬˝ÌΩÕ}Ì--]Ω‚=}›Ìí-ΩÌ¢Ω]-ÌR˝m]›-˝˝-ÌR˝--‚‡¢6ˆÁFWáBÁW6W%ˆFF≤&f6W7vˆf∆˜r%““&6Üˆ˜6U˜F&vWEˆf6R ¢ˆf6W7v˜F&vWEˆf6Uˆ6˜VÁEˆ66ÜU∑W6W%ˆñE““0¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	¯Í“	›RÕÌ2=-]]››‚Ì˝]M]Ωç-¬Ωçm›MÌ-‚‚	-Ω]ç-R-=}›=‚¬2≠≠Ì=‚}]ΩÌ-]≠}Õ]›ç-¬Ωçm„¢"¿¢&W«ïˆ÷&∑W’ˆ÷ÁV≈ˆf6Uˆ6Üˆñ6Uˆ∂"Ç'F&vWB"í¿¢ê¢&WGW&‡¢vóBˆ6µˆf6W7v˜6˜W&6U˜Ü˜FÚáWFFR¬6ˆÁFWáBê††¶7ñÊ2FVbˆ÷ñ&Uˆ6Üˆ˜6U˜6˜W&6Uˆf6RáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬W6W%ˆñC¢ñÁB¬ñ÷s¢'óFW2ì†¢ˆf6W7v˜6˜W&6Uˆ66ÜU∑W6W%ˆñE““ñ÷p¢f6W2“ˆFWFV7Eˆf6W5ˆf˜%ˆ6Üˆñ6RÜñ÷rê¢ˆf6W7v˜6˜W&6Uˆf6W5ˆ66ÜU∑W6W%ˆñE““f6W0¢ˆf6W7v˜6˜W&6Uˆf6Uˆ6˜VÁEˆ66ÜU∑W6W%ˆñE““∆V‚Üf6W2ê¢ˆf6W7v˜6˜W&6Uˆf6UˆñÊFWÖˆ66ÜU∑W6W%ˆñE““ ¢ñbd4U5tÙ4µı4ıU$4UÙd4RÊB∆V‚Üf6W2í‚†¢6ˆÁFWáBÁW6W%ˆFF≤&f6W7vˆf∆˜r%““&6Üˆ˜6U˜6˜W&6Uˆf6R ¢&WfñWr“ˆf6Uˆ6Üˆñ6U˜&WfñWuˆ'óFW2Üñ÷r¬f6W2¬-
}ÕΩçm‚-}˝-√Ú	-Ω]ç-R›ÌÕ]"ê¢FWáB“/	¯Í“	›MÌ-‚›ç-Ì}›ç≠R›ùM]›‚›]≠ÌΩÕ≠‚Ωçb‚	-Ω]ç-R¬}ÕΩçm‚---ç-¬‚ ¢ñb&WfñWs†¢&ñÚ“'óFW4îÚá&WfñWrì≤&ñÚÊÊ÷R“&f6W5˜6˜W&6Uˆ6Üˆñ6RÊßr ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜Ü˜FÚÑñÁWDfñ∆RÜ&ñÚí¬6Fñˆ„◊FWáB¬&W«ïˆ÷&∑W’ˆf6Uˆ6Üˆñ6Uˆ∂"Ç'6˜W&6R"¬f6W2íê¢V«6S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBáFWáB¬&W«ïˆ÷&∑W’ˆf6Uˆ6Üˆñ6Uˆ∂"Ç'6˜W&6R"¬f6W2íê¢&WGW&‡¢ñbd4U5tÙ4µı4ıU$4UÙd4RÊBÊ˜Bf6W2ÊBd4U5tÙ‘ÂT≈Ù4ÑÙî4UÙîeÙDUDT5DîÙÂÙdî√†¢6ˆÁFWáBÁW6W%ˆFF≤&f6W7vˆf∆˜r%““&6Üˆ˜6U˜6˜W&6Uˆf6R ¢ˆf6W7v˜6˜W&6Uˆf6Uˆ6˜VÁEˆ66ÜU∑W6W%ˆñE““0¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	¯Í“	›RÕÌ2=-]]››‚Ì˝]M]Ωç-¬Ωçm‚›ç-Ì}›ç¢‚	-Ω]ç-R-=}›=‚¬}ÕΩçm‚-}˝-√¢"¿¢&W«ïˆ÷&∑W’ˆ÷ÁV≈ˆf6Uˆ6Üˆñ6Uˆ∂"Ç'6˜W&6R"í¿¢ê¢&WGW&‡¢6ˆÁFWáBÁW6W%ˆFF≤&f6W7vˆf∆˜r%““'&VGí ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	¯Í“
MÌ-‚Ωçm˝ÌΩ=}]›‚‚	-Ω]ç-R≠}]--‚}Õ]›≥¢"¬&W«ïˆ÷&∑W÷f6U˜7v˜V∆óGïˆ∂"Çíê††¶7ñÊ2FVbˆWáG&7Eˆñ÷vUˆ'óFW5ˆg&ˆ’ˆß6ˆÂˆ˜%˜&W7ˆÁ6Rá&W7¢áGGÇÂ&W7ˆÁ6R¬6∆ñVÁC¢áGGÇ‰7ñÊ46∆ñVÁBí”‚'óFW2¬ÊˆÊS†¢˜WB“vóBˆñ÷vUˆ'óFW5ˆg&ˆ’˜&W7ˆÁ6Rá&W7¬6∆ñVÁBê¢ñb˜WC†¢&WGW&‚˜W@¢G'ì†¢ˆ&¢“&W7Êß6ˆ‚Çê¢WÜ6WBWÜ6WFñˆ„†¢&WGW&‚ÊˆÊP¢W&¬“ˆfñÊEˆfó'7Eˆñ÷vU˜W&¬Üˆ&¢ê¢ñbW&√†¢'"“vóB6∆ñVÁBÊvWBáW&¬¬Fñ÷V˜WC”c„ê¢'"Á&ó6Uˆf˜%˜7FGW2Çê¢&WGW&‚'óFW2á'"Ê6ˆÁFVÁBê¢&WGW&‚ÊˆÊP†††¶FVbˆf6W7vˆñ÷vU˜6ó¶RÜñ÷uˆ'óFW3¢'óFW2í”‚GW∆U∂ñÁB¬ñÁE”†¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2íê¢ñ““ñ÷vT˜2ÊWÜñe˜G&Á7˜6RÜñ“íñbñ÷vT˜2V«6Rñ–¢&WGW&‚ñÁBÜñ“ÁvñGFÇí¬ñÁBÜñ“ÊÜVñváBê¢WÜ6WBWÜ6WFñˆ„†¢&WGW&‚É¬ê††¶FVbˆf6W7v˜66∆VEˆf6W2Üf6W3¢∆ó7E∂Fñ7E“¬ÊˆÊR¬7&5ˆ'óFW3¢'óFW2¬G7Eˆ'óFW3¢'óFW2í”‚∆ó7E∂Fñ7E”†¢""-	˝]]}ç--¬Ì≠≤Ωçbçrç]ÌM›Ì=‚}Õ]"}Õ]≠-ç›≠Ç¬]ΩÕ›‚Ì-˝-Ω˝]ÕÌí"í‚"" ¢ñbÊ˜Bf6W3†¢&WGW&‚µ–¢7r¬6Ç“ˆf6W7vˆñ÷vU˜6ó¶Rá7&5ˆ'óFW2ê¢Gr¬FÇ“ˆf6W7vˆñ÷vU˜6ó¶RÜG7Eˆ'óFW2ê¢ñb7r√“˜"6Ç√“˜"Gr√“˜"FÇ√“†¢&WGW&‚∂Fñ7BÜbíf˜"bñ‚f6W5–¢7Ç¬7í“GrÚf∆ˆBá7rí¬FÇÚf∆ˆBá6Çê¢˜WB“µ–¢f˜"bñ‚f6W3†¢r“Fñ7BÜbê¢u≤'Ç%““ñÁBá&˜VÊBÜf∆ˆBÜbÊvWBÇ'Ç"¬íí¢7Çíê¢u≤'í%““ñÁBá&˜VÊBÜf∆ˆBÜbÊvWBÇ'í"¬íí¢7ííê¢u≤'r%““÷ÇÉ¬ñÁBá&˜VÊBÜf∆ˆBÜbÊvWBÇ'r"¬íí¢7Çííê¢u≤&Ç%““÷ÇÉ¬ñÁBá&˜VÊBÜf∆ˆBÜbÊvWBÇ&Ç"¬íí¢7íííê¢u≤&7Ç%““u≤'Ç%“≤u≤'r%“Ú"„ ¢u≤&7í%““u≤'í%“≤u≤&Ç%“Ú"„ ¢u≤&&V%““u≤'r%“¢u≤&Ç%–¢˜WBÊVÊBÜrê¢&WGW&‚˜W@††¶FVbˆf6W7vˆvWEˆf6Uˆ'ïˆñÊFWÇÜf6W3¢∆ó7E∂Fñ7E“¬ÊˆÊR¬ñGÉ¢ñÁBí”‚Fñ7B¬ÊˆÊS†¢ñbÊ˜Bf6W3†¢&WGW&‚ÊˆÊP¢ñGÇ“ñÁBÜñGÇ˜"ê¢f˜"bñ‚f6W3†¢ñbñÁBÜbÊvWBÇ&ïˆñÊFWÇ"¬”ììííí”“ñGÇ˜"ñÁBÜbÊvWBÇ&Fó7∆ïˆñÊFWÇ"¬íí“”“ñGÉ†¢&WGW&‚Fñ7BÜbê¢ñb√“ñGÇ¬∆V‚Üf6W2ì†¢&WGW&‚Fñ7BÜf6W5∂ñGÖ“ê¢&WGW&‚ÊˆÊP††¶FVbˆf6W7vˆWáÊEˆ&˜ÇÜ&˜É¢Fñ7B¬vñGFÉ¢ñÁB¬ÜVñváC¢ñÁB¬÷&vñ„¢f∆ˆB“„R¿¢÷&vñÂ˜É¢f∆ˆB¬ÊˆÊR“ÊˆÊR¬÷&vñÂ˜ï˜W¢f∆ˆB¬ÊˆÊR“ÊˆÊR¿¢÷&vñÂ˜ïˆF˜v„¢f∆ˆB¬ÊˆÊR“ÊˆÊRí”‚GW∆U∂ñÁB¬ñÁB¬ñÁB¬ñÁE”†¢Ç¬í¬r¬Ç“ñÁBÜ&˜ÇÊvWBÇ'Ç"¬íí¬ñÁBÜ&˜ÇÊvWBÇ'í"¬íí¬ñÁBÜ&˜ÇÊvWBÇ'r"¬íí¬ñÁBÜ&˜ÇÊvWBÇ&Ç"¬íê¢7Ç“Ç≤rÚ"„ ¢◊Ç“f∆ˆBÜ÷&vñÂ˜Çñb÷&vñÂ˜Çó2Ê˜BÊˆÊRV«6R÷&vñ‚ê¢◊óR“f∆ˆBÜ÷&vñÂ˜ï˜Wñb÷&vñÂ˜ï˜Wó2Ê˜BÊˆÊRV«6R÷&vñ‚ê¢◊ñB“f∆ˆBÜ÷&vñÂ˜ïˆF˜v‚ñb÷&vñÂ˜ïˆF˜v‚ó2Ê˜BÊˆÊRV«6R÷&vñ‚ê¢É“ñÁBá&˜VÊBÜ7Ç“ár¢◊ÇíÚ"„íê¢É"“ñÁBá&˜VÊBÜ7Ç≤ár¢◊ÇíÚ"„íê¢ì“ñÁBá&˜VÊBáí“Ç¢Ü◊óR“„ííê¢ì"“ñÁBá&˜VÊBáí≤Ç≤Ç¢Ü◊ñB“„ííê¢&WGW&‚÷ÇÉ¬Éí¬÷ÇÉ¬ìí¬÷ñ‚ávñGFÇ¬É"í¬÷ñ‚ÜÜVñváB¬ì"ê††¶FVbˆf6W7vˆ7&˜˜6˜W&6Uˆf6RÜñ÷uˆ'óFW3¢'óFW2¬f6S¢Fñ7B¬ÊˆÊRí”‚'óFW3†¢""-	Ì--ç-¬"6˜W&6R-ÌΩÕ≠‚-Ω››ÌRΩçm‚‚
›-‚=ç]"ΩÌm›ΩRç›M]≠≤›]ΩMÇ˝ÌM]mMR‚"" ¢ñbñ÷vRó2ÊˆÊR˜"Ê˜Bf6S†¢&WGW&‚ñ÷uˆ'óFW0¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2íê¢ñ““ñ÷vT˜2ÊWÜñe˜G&Á7˜6RÜñ“íñbñ÷vT˜2V«6Rñ–¢ñ““ñ“Ê6ˆÁfW'BÇ%$t""ê¢É¬ì¬É"¬ì"“ˆf6W7vˆWáÊEˆ&˜ÇÜf6R¬ñ“ÁvñGFÇ¬ñ“ÊÜVñváB¬÷&vñ„‘d4U5tı4ıU$4UÙ5$ıÙ‘$tî‚ê¢ñbÉ"√“É˜"ì"√“ì†¢&WGW&‚ñ÷uˆ'óFW0¢7&˜“ñ“Ê7&˜ÇáÉ¬ì¬É"¬ì"íê¢&ñÚ“'óFW4îÚÇê¢7&˜Á6fRÜ&ñÚ¬f˜&÷C“$•Tr"¬V∆óGì”ìB¬˜Fñ÷ó¶S’G'VRê¢&WGW&‚&ñÚÊvWGf«VRÇê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb'6˜W&6Rf6R7&˜fñ∆VC¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢&WGW&‚ñ÷uˆ'óFW0††¶FVbˆf6W7vˆÜñFUˆ˜FÜW%ˆf6W2áF&vWEˆ'óFW3¢'óFW2¬f6W3¢∆ó7E∂Fñ7E“¬ÊˆÊR¬6V∆V7FVEˆñGÉ¢ñÁBí”‚'óFW3†¢""-
≠Ω-¬-RΩçm¬≠ÌÕR-Ω››Ì=‚¬˝]]BÌ-˝-≠Ìí˝Ì-ùM]2‡†¢
Mç›ΩÕ›Ωí]}=ΩÕ-"]-Ú›Rm]Ωç≠Ì√¢›çmRÕ≤-≠Ω]ç-]¬-ÌΩÕ≠‚ÌΩ-¬-Ω››Ì=‚Ωçm ¢Ì-›‚"ç]ÌM›Ωí≠M‚	˝Ì›-ÌÕ2-]Õ]››ÌR≠Ω-çRÌ]M›çRΩçb]}Ì˝›‚Ç]ç] ¢˝ÌΩ]Õ2¬≠Ì=MíÕ]›˝]"›R-Ì=‚}]ΩÌ-]≠‡¢"" ¢ñbñ÷vRó2ÊˆÊR˜"ñ÷vTfñ«FW"ó2ÊˆÊR˜"Ê˜Bf6W3†¢&WGW&‚F&vWEˆ'óFW0¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚáF&vWEˆ'óFW2íê¢ñ““ñ÷vT˜2ÊWÜñe˜G&Á7˜6RÜñ“íñbñ÷vT˜2V«6Rñ–¢ñ““ñ“Ê6ˆÁfW'BÇ%$t""ê¢6V∆V7FVB“ˆf6W7vˆvWEˆf6Uˆ'ïˆñÊFWÇÜf6W2¬6V∆V7FVEˆñGÇê¢ñbÊ˜B6V∆V7FVC†¢&WGW&‚F&vWEˆ'óFW0¢&«W'&VB“ñ“Êfñ«FW"Ññ÷vTfñ«FW"‰vW76ñ‰&«W"á&FóW3÷÷ÇÉÇ¬ñÁBÜ÷ÇÜñ“Á6ó¶Rí¢„#Ríííê¢f˜"bñ‚f6W3†¢ñbñÁBÜbÊvWBÇ&ïˆñÊFWÇ"¬”ììííí”“ñÁBá6V∆V7FVBÊvWBÇ&ïˆñÊFWÇ"¬”ÉÉÇíì†¢6ˆÁFñÁVP¢É¬ì¬É"¬ì"“ˆf6W7vˆWáÊEˆ&˜ÇÜb¬ñ“ÁvñGFÇ¬ñ“ÊÜVñváB¬÷&vñ„‘d4U5tıD$tUEÙÑîDUÙ‘$tî‚ê¢ñbÉ"√“É˜"ì"√“ì†¢6ˆÁFñÁVP¢F6Ç“&«W'&VBÊ7&˜ÇáÉ¬ì¬É"¬ì"íê¢ñ“Á7FRáF6Ç¬áÉ¬ìíê¢&ñÚ“'óFW4îÚÇê¢ñ“Á6fRÜ&ñÚ¬f˜&÷C“$•Tr"¬V∆óGì”ìB¬˜Fñ÷ó¶S’G'VRê¢&WGW&‚&ñÚÊvWGf«VRÇê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb&ÜñFR˜FÜW"f6W2fñ∆VC¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢&WGW&‚F&vWEˆ'óFW0††¶FVbˆf6W7vˆ6ˆ◊˜6óFU˜6V∆V7FVE˜&Vvñˆ‚Ü˜&ñvñÊ≈˜F&vWEˆ'óFW3¢'óFW2¬&˜fñFW%ˆ˜WGWC¢'óFW2¬6V∆V7FVEˆf6S¢Fñ7B¬ÊˆÊRí”‚'óFW3†¢""-	-]›=-¬"ç]ÌM›Ωí≠M-ÌΩÕ≠‚ç}Õ]›››=‚ÌΩ-¬-Ω››Ì=‚Ωçm‚"" ¢ñbñ÷vRó2ÊˆÊR˜"ñ÷vTfñ«FW"ó2ÊˆÊR˜"Ê˜B6V∆V7FVEˆf6S†¢&WGW&‚&˜fñFW%ˆ˜WGW@¢G'ì†¢&6R“ñ÷vRÊ˜V‚Ñ'óFW4îÚÜ˜&ñvñÊ≈˜F&vWEˆ'óFW2íê¢&6R“ñ÷vT˜2ÊWÜñe˜G&Á7˜6RÜ&6Ríñbñ÷vT˜2V«6R&6P¢&6R“&6RÊ6ˆÁfW'BÇ%$t""ê¢˜WB“ñ÷vRÊ˜V‚Ñ'óFW4îÚá&˜fñFW%ˆ˜WGWBíê¢˜WB“ñ÷vT˜2ÊWÜñe˜G&Á7˜6RÜ˜WBíñbñ÷vT˜2V«6R˜W@¢˜WB“˜WBÊ6ˆÁfW'BÇ%$t""ê¢ñb˜WBÁ6ó¶R“&6RÁ6ó¶S†¢˜WB“˜WBÁ&W6ó¶RÜ&6RÁ6ó¶R¬ñ÷vR‰ƒ‰5§ı2ê¢É¬ì¬É"¬ì"“ˆf6W7vˆWáÊEˆ&˜ÇÄ¢6V∆V7FVEˆf6R¬&6RÁvñGFÇ¬&6RÊÜVñváB¿¢÷&vñÂ˜É‘d4U5tÙ4Ù’ı4ïDUÙ‘$tîÂıÇ¿¢÷&vñÂ˜ï˜W‘d4U5tÙ4Ù’ı4ïDUÙ‘$tîÂıïıU¿¢÷&vñÂ˜ïˆF˜v„‘d4U5tÙ4Ù’ı4ïDUÙ‘$tîÂıïÙDıt‚¿¢ê¢ñbÉ"√“É˜"ì"√“ì†¢&WGW&‚&˜fñFW%ˆ˜WGW@¢F6Ç“˜WBÊ7&˜ÇáÉ¬ì¬É"¬ì"íê¢÷6≤“ñ÷vRÊÊWrÇ$¬"¬áÉ"“É¬ì"“ìí¬ê¢÷B“ñ÷vTG&r‰G&rÜ÷6≤ê¢B“÷ÇÉ"¬ñÁBÜ÷ñ‚Ü÷6≤Á6ó¶Rí¢„Bíê¢÷BÁ&˜VÊFVE˜&V7FÊv∆RÖ∑B¬B¬÷6≤ÁvñGFÇ“B¬÷6≤ÊÜVñváB“E“¬&FóW3÷÷ÇÉ"¬ñÁBÜ÷ñ‚Ü÷6≤Á6ó¶Rí¢„#Çíí¬fñ∆√”#SRê¢÷6≤“÷6≤Êfñ«FW"Ññ÷vTfñ«FW"‰vW76ñ‰&«W"á&FóW3÷÷ÇÉb¬ñÁBÜ÷ñ‚Ü÷6≤Á6ó¶Rí¢„bíííê¢&6RÁ7FRáF6Ç¬áÉ¬ìí¬÷6≤ê¢&ñÚ“'óFW4îÚÇê¢&6RÁ6fRÜ&ñÚ¬f˜&÷C“$•Tr"¬V∆óGì”ìB¬˜Fñ÷ó¶S’G'VRê¢&WGW&‚&ñÚÊvWGf«VRÇê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb'6V∆V7FVBf6R6ˆ◊˜6óFRfñ∆VC¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢&WGW&‚&˜fñFW%ˆ˜WGW@††¶7ñÊ2FVb˜ñïˆf6W7váF&vWEˆñ÷s¢'óFW2¬6˜W&6Uˆf6S¢'óFW2¬V∆óGì¢7G"“&f7B"¬F&vWEˆñÊFWÉ¢ñÁB“¬6˜W&6UˆñÊFWÉ¢ñÁB“í”‚'óFW2¬ÊˆÊS†¢ñbÊ˜BîïÙïÙ¥Uì†¢ˆf6W7vˆÊ˜FUˆW'&˜"Ç%îïÙïÙ¥Uí÷ó76ñÊr"ê¢&WGW&‚ÊˆÊP¢F&vWEˆ#cB“ˆ#cEˆf˜%ˆf6W7váF&vWEˆñ÷rê¢6˜W&6Uˆ#cB“ˆ#cEˆf˜%ˆf6W7vá6˜W&6Uˆf6Rê¢W&¬“b'µîïÙ$4UıU$«◊µîïÙd4UÙ5$TDUıDá“ ¢ÜVFW'2“≤'Ç÷í÷∂Wí#¢îïÙïÙ¥Uí¬%Ç‘í‘∂Wí#¢îïÙïÙ¥Uí¬$6ˆÁFVÁB’GóR#¢&∆ñ6Fñˆ‚ˆß6ˆ‚"¬$66WB#¢&∆ñ6Fñˆ‚ˆß6ˆ‚'–¢ñ∆ˆB“∞¢&÷ˆFV¬#¢îïÙd4UÙ‘ÙDT¬¿¢'F6µ˜GóR#¢îïÙd4UıD4µıEïR¿¢&ñÁWB#¢∞¢'F&vWEˆñ÷vR#¢F&vWEˆ#cB¿¢'7vˆñ÷vR#¢6˜W&6Uˆ#cB¿¢2	]ΩÇîí›}›"˝ÌMM]mç--¬˝-›Ωíç›M]≠¬›-Ç˝ÌΩÚ=mR=M="˝]]M›≤‡¢'F&vWEˆf6UˆñÊFWÇ#¢ñÁBáF&vWEˆñÊFWÇ˜"í¿¢'6˜W&6Uˆf6UˆñÊFWÇ#¢ñÁBá6˜W&6UˆñÊFWÇ˜"í¿¢“¿¢–¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC”c„¬fˆ∆∆˜u˜&VFó&V7G3’G'VRí26∆ñVÁC†¢"“vóB6∆ñVÁBÁ˜7BáW&¬¬ÜVFW'3÷ÜVFW'2¬ß6ˆ„◊ñ∆ˆBê¢ñb"Á7FGW5ˆ6ˆFR„“C†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb%îí7&VFRfñ∆VB7FGW3◊∑"Á7FGW5ˆ6ˆFW“&ˆGì◊∑"ÁFWáE≥£ì◊“"ê¢&WGW&‚ÊˆÊP¢G'ì†¢ˆ&¢“"Êß6ˆ‚Çê¢WÜ6WBWÜ6WFñˆ„†¢ˆ&¢“∑–¢Fó&V7B“vóBˆWáG&7Eˆñ÷vUˆ'óFW5ˆg&ˆ’ˆß6ˆÂˆ˜%˜&W7ˆÁ6Rá"¬6∆ñVÁBê¢ñbFó&V7C†¢&WGW&‚ˆÊ˜&÷∆ó¶Uˆ˜WGWEˆñ÷vUˆ'óFW2ÜFó&V7Bê¢FF“ˆ&¢ÊvWBÇ&FF"íñbó6ñÁ7FÊ6RÜˆ&¢¬Fñ7BíV«6RÊˆÊP¢F6µˆñB“" ¢ñbó6ñÁ7FÊ6RÜFF¬Fñ7Bì†¢F6µˆñB“7G"ÜFFÊvWBÇ'F6µˆñB"í˜"FFÊvWBÇ&ñB"í˜"""ê¢F6µˆñB“F6µˆñB˜"7G"Üˆ&¢ÊvWBÇ'F6µˆñB"í˜"ˆ&¢ÊvWBÇ&ñB"í˜"""íñbó6ñÁ7FÊ6RÜˆ&¢¬Fñ7BíV«6R" ¢ñbÊ˜BF6µˆñC†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb%îí7&VFR&WGW&ÊVBÊÚF6µˆñB&ˆGì◊∑7G"Üˆ&¢ï≥£ì◊“"ê¢&WGW&‚ÊˆÊP¢FVF∆ñÊR“Fñ÷RÊ÷ˆÊ˜FˆÊñ2Çí≤÷ÇÉ3„¬d4U5tıDî‘TıUEı2ê¢7FGW5˜W&¬“b'µîïÙ$4UıU$«◊µîïÙd4Uı5DEU5ıDÇÊf˜&÷BáF6µˆñC◊F6µˆñBó“ ¢∆7Eˆˆ&¢“ÊˆÊP¢vÜñ∆RFñ÷RÊ÷ˆÊ˜FˆÊñ2Çí¬FVF∆ñÊS†¢vóB7ñÊ6ñÚÁ6∆VWÜ÷ÇÉ„¬d4U5tıÙƒ≈ÙDTƒïı2íê¢'"“vóB6∆ñVÁBÊvWBá7FGW5˜W&¬¬ÜVFW'3÷ÜVFW'2ê¢ñb'"Á7FGW5ˆ6ˆFR„“C†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb%îí7FGW2fñ∆VB7FGW3◊∑'"Á7FGW5ˆ6ˆFW“&ˆGì◊∑'"ÁFWáE≥£ì◊“"ê¢&WGW&‚ÊˆÊP¢G'ì†¢∆7Eˆˆ&¢“'"Êß6ˆ‚Çê¢WÜ6WBWÜ6WFñˆ„†¢∆7Eˆˆ&¢“∑–¢ñ÷r“vóBˆWáG&7Eˆñ÷vUˆ'óFW5ˆg&ˆ’ˆß6ˆÂˆ˜%˜&W7ˆÁ6Rá'"¬6∆ñVÁBê¢ñbñ÷s†¢&WGW&‚ˆÊ˜&÷∆ó¶Uˆ˜WGWEˆñ÷vUˆ'óFW2Üñ÷rê¢FF“∆7Eˆˆ&¢ÊvWBÇ&FF"íñbó6ñÁ7FÊ6RÜ∆7Eˆˆ&¢¬Fñ7BíV«6RÊˆÊP¢7B“" ¢ñbó6ñÁ7FÊ6RÜFF¬Fñ7Bì†¢7B“7G"ÜFFÊvWBÇ'7FGW2"í˜"FFÊvWBÇ'7FFR"í˜"""íÊ∆˜vW"Çê¢7B“7B˜"7G"Ü∆7Eˆˆ&¢ÊvWBÇ'7FGW2"í˜"∆7Eˆˆ&¢ÊvWBÇ'7FFR"í˜"""íÊ∆˜vW"Çíñbó6ñÁ7FÊ6RÜ∆7Eˆˆ&¢¬Fñ7BíV«6R" ¢ñb7Bñ‚Ç&fñ∆VB"¬&W'&˜""¬&6Ê6V∆VB"¬&6Ê6V∆∆VB"ì†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb%îíF6≤fñ∆VB7FGW3◊∑7G“&ˆGì◊∑7G"Ü∆7Eˆˆ&¢ï≥£ì◊“"ê¢&WGW&‚ÊˆÊP¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb%îíF6≤Fñ÷V˜WBgFW"¥d4U5tıDî‘TıUEı3¢„g◊2F6µˆñC◊∑F6µˆñG“"ê¢&WGW&‚ÊˆÊP††¶7ñÊ2FVb˜6Vv÷ñÊEˆf6W7v˜c"áF&vWEˆñ÷s¢'óFW2¬6˜W&6Uˆf6S¢'óFW2¬F&vWEˆñÊFWÉ¢ñÁB“¬6˜W&6UˆñÊFWÉ¢ñÁB“í”‚'óFW2¬ÊˆÊS†¢ñbÊ˜B4Tt‘î‰EÙïÙ¥Uì†¢ˆf6W7vˆÊ˜FUˆW'&˜"Ç%4Tt‘î‰EÙïÙ¥Uí÷ó76ñÊr"ê¢&WGW&‚ÊˆÊP¢W&¬“b'µ4Tt‘î‰EÙ$4UıU$«“˜c˜µ4Tt‘î‰EÙd4U5tÙ‘ÙDT≈Ùd5G“ ¢ñ∆ˆB“∞¢'6˜W&6Uˆñ÷r#¢ˆ#cEˆf˜%ˆf6W7vá6˜W&6Uˆf6Rí¿¢'F&vWEˆñ÷r#¢ˆ#cEˆf˜%ˆf6W7váF&vWEˆñ÷rí¿¢&ñÁWEˆf6W5ˆñÊFWÇ#¢7G"ÜñÁBáF&vWEˆñÊFWÇ˜"íí¿¢'6˜W&6Uˆf6W5ˆñÊFWÇ#¢7G"ÜñÁBá6˜W&6UˆñÊFWÇ˜"íí¿¢&f6U˜&W7F˜&R#¢4Tt‘î‰EÙd4Uı$U5Dı$R¿¢&&6ScB#¢f«6R¿¢–¢ÜVFW'2“≤'Ç÷í÷∂Wí#¢4Tt‘î‰EÙïÙ¥Uí¬$6ˆÁFVÁB’GóR#¢&∆ñ6Fñˆ‚ˆß6ˆ‚"¬$66WB#¢&∆ñ6Fñˆ‚ˆß6ˆ‚'–¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC‘d4U5tıDî‘TıUEı2¬fˆ∆∆˜u˜&VFó&V7G3’G'VRí26∆ñVÁC†¢"“vóB6∆ñVÁBÁ˜7BáW&¬¬ÜVFW'3÷ÜVFW'2¬ß6ˆ„◊ñ∆ˆBê¢ñb"Á7FGW5ˆ6ˆFR„“C†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb%6Vv÷ñÊBc"fñ∆VB7FGW3◊∑"Á7FGW5ˆ6ˆFW“&ˆGì◊∑"ÁFWáE≥£ì◊“"ê¢&WGW&‚ÊˆÊP¢ñ÷r“vóBˆWáG&7Eˆñ÷vUˆ'óFW5ˆg&ˆ’ˆß6ˆÂˆ˜%˜&W7ˆÁ6Rá"¬6∆ñVÁBê¢ñbñ÷s†¢&WGW&‚ˆÊ˜&÷∆ó¶Uˆ˜WGWEˆñ÷vUˆ'óFW2Üñ÷rê¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb%6Vv÷ñÊBc"ÊÚ˜WGWB&ˆGì◊∑"ÁFWáE≥£ì◊“"ê¢&WGW&‚ÊˆÊP††¶7ñÊ2FVb˜6Vv÷ñÊEˆf6W7v˜cBáF&vWEˆñ÷s¢'óFW2¬6˜W&6Uˆf6S¢'óFW2¬V∆óGì¢7G"“'&V÷óV“"í”‚'óFW2¬ÊˆÊS†¢ñbÊ˜B4Tt‘î‰EÙïÙ¥Uì†¢ˆf6W7vˆÊ˜FUˆW'&˜"Ç%4Tt‘î‰EÙïÙ¥Uí÷ó76ñÊr"ê¢&WGW&‚ÊˆÊP¢W&¬“b'µ4Tt‘î‰EÙ$4UıU$«“˜c˜µ4Tt‘î‰EÙd4U5tÙ‘ÙDT≈ı$T‘ïT◊“ ¢ñ∆ˆB“∞¢'6˜W&6Uˆñ÷vR#¢ˆ#cEˆf˜%ˆf6W7vá6˜W&6Uˆf6Rí¿¢'F&vWEˆñ÷vR#¢ˆ#cEˆf˜%ˆf6W7váF&vWEˆñ÷rí¿¢&÷ˆFV≈˜GóR#¢'V∆óGí"ñbV∆óGí”“'&V÷óV“"V«6R'7VVB"¿¢'7v˜GóR#¢4Tt‘î‰EÙd4Uı5tıEïR¿¢'7Gñ∆U˜GóR#¢4Tt‘î‰EÙd4Uı5EîƒUıEïR¿¢'6VVB#¢ñÁBáFñ÷RÁFñ÷RÇííR¿¢&ñ÷vUˆf˜&÷B#¢'Êr"¿¢&ñ÷vU˜V∆óGí#¢ìRñbV∆óGí”“'&V÷óV“"V«6Rì¿¢&Ü&Gv&R#¢&f7B"¿¢&&6ScB#¢f«6R¿¢–¢ÜVFW'2“≤'Ç÷í÷∂Wí#¢4Tt‘î‰EÙïÙ¥Uí¬$6ˆÁFVÁB’GóR#¢&∆ñ6Fñˆ‚ˆß6ˆ‚"¬$66WB#¢&∆ñ6Fñˆ‚ˆß6ˆ‚'–¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC‘d4U5tıDî‘TıUEı2¬fˆ∆∆˜u˜&VFó&V7G3’G'VRí26∆ñVÁC†¢"“vóB6∆ñVÁBÁ˜7BáW&¬¬ÜVFW'3÷ÜVFW'2¬ß6ˆ„◊ñ∆ˆBê¢ñb"Á7FGW5ˆ6ˆFR„“C†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb%6Vv÷ñÊBcBfñ∆VB7FGW3◊∑"Á7FGW5ˆ6ˆFW“&ˆGì◊∑"ÁFWáE≥£ì◊“"ê¢&WGW&‚ÊˆÊP¢ñ÷r“vóBˆWáG&7Eˆñ÷vUˆ'óFW5ˆg&ˆ’ˆß6ˆÂˆ˜%˜&W7ˆÁ6Rá"¬6∆ñVÁBê¢ñbñ÷s†¢&WGW&‚ˆÊ˜&÷∆ó¶Uˆ˜WGWEˆñ÷vUˆ'óFW2Üñ÷rê¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb%6Vv÷ñÊBcBÊÚ˜WGWB&ˆGì◊∑"ÁFWáE≥£ì◊“"ê¢&WGW&‚ÊˆÊP††¶FVbˆf6W7v˜&˜fñFW%˜7W˜'G5ˆñÊFñ6W2á&˜fñFW#¢7G"í”‚&ˆˆ√†¢&˜fñFW"“á&˜fñFW"˜"""íÊ∆˜vW"ÇíÁ7G&óÇê¢2	˝≠-ç≠-]-Ì"˝Ì≠}Ω†¢2“6Vv÷ñÊBc"M]ù--ç-]ΩÕ›‚=Õ]]"M]›Ωí-ΩÌΩçb˝‚ç›M]≠¬‡¢2“îíıV&ñ6ÚÕÌm]"=˝]ç›‚-˝-¬Ωçm¬›‚›RM"›Mm›Ìí=›-çÇ¿¢2}-‚F&vWEˆf6UˆñÊFWÇ˜6˜W&6Uˆf6UˆñÊFWÇ=M="ÌΩÌM]›≤MΩÚ==˝˝Ì-ΩRMÌ-‚‡¢2	˝Ì›-ÌÕ2MΩÚ-Ì=Ì=‚]mçÕ-ΩÌΩçm}ç-]¬ç›M]≠ç=]ÕΩ¬-ÌΩÕ≠‚6Vv÷ñÊBc"‡¢&WGW&‚&˜fñFW"ñ‚Ç'6Vv÷ñÊB"¬'6Vv÷ñÊB◊c""¬'6Vv÷ñÊC""ê††¶7ñÊ2FVb˜'VÂˆf6W7v˜&˜fñFW"á&˜fñFW#¢7G"¬F&vWEˆñ÷s¢'óFW2¬6˜W&6Uˆf6S¢'óFW2¬V∆óGì¢7G"¬F&vWEˆñÊFWÉ¢ñÁB“¬6˜W&6UˆñÊFWÉ¢ñÁB“í”‚'óFW2¬ÊˆÊS†¢&˜fñFW"“á&˜fñFW"˜"""íÊ∆˜vW"ÇíÁ7G&óÇê¢ñb&˜fñFW"ñ‚Ç'ñí"¬'í"¬'V&ñ6Ú"ì†¢&WGW&‚vóB˜ñïˆf6W7váF&vWEˆñ÷r¬6˜W&6Uˆf6R¬V∆óGì◊V∆óGí¬F&vWEˆñÊFWÉ◊F&vWEˆñÊFWÇ¬6˜W&6UˆñÊFWÉ◊6˜W&6UˆñÊFWÇê¢ñb&˜fñFW"ñ‚Ç'6Vv÷ñÊB"¬'6Vv÷ñÊB◊c""¬'6Vv÷ñÊC""ì†¢&WGW&‚vóB˜6Vv÷ñÊEˆf6W7v˜c"áF&vWEˆñ÷r¬6˜W&6Uˆf6R¬F&vWEˆñÊFWÉ◊F&vWEˆñÊFWÇ¬6˜W&6UˆñÊFWÉ◊6˜W&6UˆñÊFWÇê¢ñb&˜fñFW"ñ‚Ç'6Vv÷ñÊB◊cB"¬'6Vv÷ñÊCB"ì†¢&WGW&‚vóB˜6Vv÷ñÊEˆf6W7v˜cBáF&vWEˆñ÷r¬6˜W&6Uˆf6R¬V∆óGì◊V∆óGíê¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb'VÊ∂Ê˜v‚f6W7v&˜fñFW#◊∑&˜fñFW'“"ê¢&WGW&‚ÊˆÊP††¶FVbˆf6W7v˜&˜fñFW%ˆ˜&FW"áV∆óGì¢7G"¬W6W%ˆñC¢ñÁBí”‚∆ó7E∑7G%”†¢ñbV∆óGí”“'&V÷óV“#†¢&6R“¥d4U5tı$T‘ïT’ı$ıdîDU"¬d4U5tÙdƒƒ$4µı$ıdîDU"¬'6Vv÷ñÊB◊c""¬d4U5tı$ıdîDU%–¢V«6S†¢&6R“¥d4U5tÙd5Eı$ıdîDU"¬d4U5tı$ıdîDU"¬d4U5tÙdƒƒ$4µı$ıdîDU"¬'6Vv÷ñÊB◊c"%–¢6VV‚“µ–¢˜&FW"“∑f˜"ñ‚&6RñbÊBÊ˜Báñ‚6VV‚˜"6VV‚ÊVÊBáíï–¢6V∆V7FVEˆ◊V«Fí“Öˆf6W7v˜F&vWEˆf6Uˆ6˜VÁEˆ66ÜRÊvWBáW6W%ˆñB¬í˜"í‚˜"Öˆf6W7v˜6˜W&6Uˆf6Uˆ6˜VÁEˆ66ÜRÊvWBáW6W%ˆñB¬í˜"í‚†¢2c3S¢]ΩÇ˝ÌΩÕ}Ì--]Ω¬-Ωç≤Ωçm‚›==˝˝Ì-Ì¬MÌ-‚¬›RÌ-M¬}M}2îí‡¢2îí]ÌÌççíΩ-Ωí˝Ì-ùM]¬›‚"-]-RÌ“ç›Ì=Mç=›ÌçÌ-≤-Ω››Ωíç›M]≠‡¢2	MΩÚ-Ì}›Ì-ÇÌ--Ω˝]¬-ÌΩÕ≠‚6Vv÷ñÊC≤cBÕÌm]"ç˝ÌΩÕ}Ì--ÕÚ}]]ró6ˆ∆FR∂6ˆ◊˜6óFR¿¢2c"Ì--Úç›M]≠ç=]ÕΩ¬]}]-Ì¬¬]ΩÇ}]ç“‡¢ñbd4U5tÙdı$4Uı4Tt‘î‰EÙdı%Ù’T≈DíÊB6V∆V7FVEˆ◊V«Fì†¢6Vr“≤'6Vv÷ñÊB◊c"%–¢ñbV∆óGí”“'&V÷óV“"ÊBd4U5tÙu$ıUÙƒƒıuı4Tt‘î‰EÙdƒƒ$4≥†¢6VrÊVÊBÇ'6Vv÷ñÊB◊cB"ê¢V∆ñbV∆óGí“'&V÷óV“"ÊBd4U5tÙu$ıUÙƒƒıuı4Tt‘î‰EÙdƒƒ$4≥†¢6VrÊVÊBÇ'6Vv÷ñÊB◊cB"ê¢6VV„"“µ–¢&WGW&‚∑f˜"ñ‚6VrñbÊBÊ˜Báñ‚6VV„"˜"6VV„"ÊVÊBáíï–†¢ñbd4U5tı5E$î5Eı4TƒT5DTEÙd4RÊB6V∆V7FVEˆ◊V«Fì†¢ñÊFWÜVB“∑f˜"ñ‚˜&FW"ñbˆf6W7v˜&˜fñFW%˜7W˜'G5ˆñÊFñ6W2áï–¢ñbñÊFWÜVC†¢&WGW&‚ñÊFWÜV@¢ˆf6W7vˆÊ˜FUˆW'&˜"Ç'7G&ñ7BF&vWB˜6˜W&6Rf6R6Üˆñ6RÊVVG26Vv÷ñÊBf6W7v◊c"¬'WBÊÚñÊFWÜVB&˜fñFW"6ˆÊfñwW&VB"ê¢&WGW&‚˜&FW †¶7ñÊ2FVbˆf6W7v˜&ˆ6W72áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬V∆óGì¢7G"“&f7B"ì†¢W6W%ˆñB“WFFRÊVffV7FófU˜W6W"Êñ@¢F&vWB“ˆf6W7v˜F&vWEˆf˜"áW6W%ˆñBê¢6˜W&6R“ˆf6W7v˜6˜W&6Uˆf˜"áW6W%ˆñBê¢F&vWEˆñÊFWÇ“ˆf6W7v˜6V∆V7FVE˜F&vWEˆñÊFWÇáW6W%ˆñBê¢6˜W&6UˆñÊFWÇ“ˆf6W7v˜6V∆V7FVE˜6˜W&6UˆñÊFWÇáW6W%ˆñBê¢ñbÊ˜BF&vWB˜"Ê˜B6˜W&6S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›=m›≤"MÌ-„¢›}ΩMÌ-‚¬=MR}Õ]›ç-¬Ωçm‚¬}-]¬MÌ-‚ΩçmMΩÚ---≠Ç‚"¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡¢ñbÊ˜Bd4U5tÙT‰$ƒTC†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	¯Í“	}Õ]›Ωçm-]Õ]››‚Ì-≠ΩÌ}]›"›-Ìù≠R]-]‚"ê¢&WGW&‡†¢˜&ñvñÊ≈˜F&vWB“F&vW@¢F&vWEˆí¬˜F&vWEˆÊ÷R¬˜F&vWEˆ÷ñ÷R“˜&W6ó¶Uˆñ÷vUˆ'óFW5ˆf˜%ˆf6W7vˆíáF&vWB¬d4U5tÙîÂUEÙ‘Öı4îDRê¢F&vWEˆf6W5ˆí“ˆf6W7v˜66∆VEˆf6W2Öˆf6W7v˜F&vWEˆf6W5ˆ66ÜRÊvWBáW6W%ˆñBí¬F&vWB¬F&vWEˆíê¢6˜W&6Uˆf6W2“ˆf6W7v˜6˜W&6Uˆf6W5ˆ66ÜRÊvWBáW6W%ˆñBí˜"µ–¢6V∆V7FVE˜F&vWEˆf6R“ˆf6W7vˆvWEˆf6Uˆ'ïˆñÊFWÇáF&vWEˆf6W5ˆí¬F&vWEˆñÊFWÇê¢6V∆V7FVE˜6˜W&6Uˆf6R“ˆf6W7vˆvWEˆf6Uˆ'ïˆñÊFWÇá6˜W&6Uˆf6W2¬6˜W&6UˆñÊFWÇê†¢6V∆V7FVEˆ◊V«Fí“Öˆf6W7v˜F&vWEˆf6Uˆ6˜VÁEˆ66ÜRÊvWBáW6W%ˆñB¬í˜"í‚˜"Öˆf6W7v˜6˜W&6Uˆf6Uˆ6˜VÁEˆ66ÜRÊvWBáW6W%ˆñB¬í˜"í‚¢&˜fñFW%ˆ˜&FW"“ˆf6W7v˜&˜fñFW%ˆ˜&FW"áV∆óGí¬W6W%ˆñBê¢ñÊFWÜVEˆfñ∆&∆R“ÁíÖˆf6W7v˜&˜fñFW%˜7W˜'G5ˆñÊFñ6W2áíf˜"ñ‚&˜fñFW%ˆ˜&FW"ê¢&V6ó6R“&ˆˆ¬Ñd4U5tı$T4ï4UÙ4Ù’ı4ïDRÊB6V∆V7FVEˆ◊V«FíÊB6V∆V7FVE˜F&vWEˆf6RÊBÊ˜BñÊFWÜVEˆfñ∆&∆Rê¢&˜fñFW%˜F&vWB“ˆf6W7vˆÜñFUˆ˜FÜW%ˆf6W2áF&vWEˆí¬F&vWEˆf6W5ˆí¬F&vWEˆñÊFWÇíñb&V6ó6RV«6RF&vWEˆê¢&˜fñFW%˜6˜W&6R“ˆf6W7vˆ7&˜˜6˜W&6Uˆf6Rá6˜W&6R¬6V∆V7FVE˜6˜W&6Uˆf6Ríñb6V∆V7FVE˜6˜W&6Uˆf6RV«6R6˜W&6P¢&˜fñFW%˜F&vWEˆñÊFWÇ“ñb&V6ó6RV«6RF&vWEˆñÊFWÄ¢&˜fñFW%˜6˜W&6UˆñÊFWÇ“ñb6V∆V7FVE˜6˜W&6Uˆf6RV«6R6˜W&6UˆñÊFWÄ†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b/	¯Í“	}˝=≠‚}Õ]›2Ωçmá≤}	˝]Õç=¬rñbV∆óGí”“w&V÷óV“rV«6R}	Ω-‚w“í‚ ¢b-
m]Ω]-ÌRΩçm‚(Ig∑F&vWEˆñÊFWÇ≤“‚	Ωçm‚›ç-Ì}›ç¢(Ig∑6˜W&6UˆñÊFWÇ≤“‚ ¢b-	˝Ì-ùM]≥¢≤r¬rÊ¶ˆñ‚á&˜fñFW%ˆ˜&FW"ó“‚ ¢-
Ì]›˝‚ç]ÌM›ÌR-]Ω‚¬ÌM]mM2¬MÌ“Ç≠ÌÕ˝Ì}çmç‚‚	ÌΩ}›‚(	3É]≠=›N(
b ¢ê†¢7ñÊ2FVbˆvÚÇì†¢˜WB“ÊˆÊP¢W6VE˜&˜fñFW"“" ¢f˜"&˜fñFW"ñ‚&˜fñFW%ˆ˜&FW#†¢G'ì†¢˜WB“vóB7ñÊ6ñÚÁvóEˆf˜"Ä¢˜'VÂˆf6W7v˜&˜fñFW"á&˜fñFW"¬&˜fñFW%˜F&vWB¬&˜fñFW%˜6˜W&6R¬V∆óGí¬F&vWEˆñÊFWÉ◊&˜fñFW%˜F&vWEˆñÊFWÇ¬6˜W&6UˆñÊFWÉ◊&˜fñFW%˜6˜W&6UˆñÊFWÇí¿¢Fñ÷V˜WC‘d4U5tıDî‘TıUEı2≤3¿¢ê¢ñb˜WC†¢W6VE˜&˜fñFW"“&˜fñFW ¢'&V∞¢WÜ6WB7ñÊ6ñÚÂFñ÷V˜WDW'&˜#†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb'∑&˜fñFW'“Fñ÷V˜WBgFW"¥d4U5tıDî‘TıUEı3¢„g◊2"ê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆf6W7vˆÊ˜FUˆW'&˜"Üb'∑&˜fñFW'“WÜ6WFñˆ„¢∑GóRÜRíÂıˆÊ÷Uı˜”¢∂W“"ê¢ñbÊ˜B˜WC†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	›R=MΩÌ¬}Õ]›ç-¬Ωçm‚‚	˝ÌΩ]M›çRÌçç≠É•∆‚"≤ˆf6W7vˆ∆7EˆW'&˜'5˜FWáBÇíê¢&WGW&‚f«6P¢ñb&V6ó6S†¢2
Ì]›˝]¬Ì-ΩÕ›ΩRΩçmÇMÌ“çrç]ÌM›Ì=‚≠M≤Õ]›˝]¬-ÌΩÕ≠‚-Ω››=‚ÌΩ-¬‡¢˜WB“ˆf6W7vˆ6ˆ◊˜6óFU˜6V∆V7FVE˜&Vvñˆ‚áF&vWEˆí¬˜WB¬6V∆V7FVE˜F&vWEˆf6Rê¢˜WB“ˆ÷ñ&U˜&W6ó¶Uˆ˜WGWEˆñ÷vRÜ˜WBê¢ˆ66ÜU˜Ü˜FÚáW6W%ˆñB¬˜WBê¢&ñÚ“'óFW4îÚÜ˜WBê¢6“Ä¢b/	¯Í“	Ωçm‚}Õ]›]›‚)»R
]mç√¢≤}	˝]Õç=¬rñbV∆óGí”“w&V÷óV“rV«6R}	Ω-‚w“+r˝Ì-ùM]¢∑W6VE˜&˜fñFW'“‚ ¢b-
m]Ω]-ÌRΩçm‚(Ig∑F&vWEˆñÊFWÇ≤“¬ç-Ì}›ç¢(Ig∑6˜W&6UˆñÊFWÇ≤“‚ ¢-
]}=ΩÕ-"Ì]›“≠¢ç]ÌM›ÌRMÌ-‚MΩÚMΩÕ›]ùççRM]ù--çí‚ ¢ê¢ñbd4U5tı$U5T≈EÙ5ÙDÙ5T‘TÂC†¢&ñÚÊÊ÷R“&f6U˜7vÁÊr ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ïˆFˆ7V÷VÁBÑñÁWDfñ∆RÜ&ñÚí¬6Fñˆ„÷6¬&W«ïˆ÷&∑W◊Ü˜Fı˜Vñ6µˆ7FñˆÁ5ˆ∂"Çíê¢V«6S†¢&ñÚÊÊ÷R“&f6U˜7vÊßr ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜Ü˜FÚÑñÁWDfñ∆RÜ&ñÚí¬6Fñˆ„÷6¬&W«ïˆ÷&∑W◊Ü˜Fı˜Vñ6µˆ7FñˆÁ5ˆ∂"Çíê¢ˆ6∆V%ˆf6W7vˆf∆˜rÜ6ˆÁFWáBê¢ˆ6∆V%ˆf6W7v˜W6W%ˆ66ÜRáW6W%ˆñBê¢&WGW&‚G'VP†¢W7B“d4U5tı$T‘ïT’Ù4ı5EıU4BñbV∆óGí”“'&V÷óV“"V«6Rd4U5tÙd5EÙ4ı5EıU4@¢vóB˜G'ï˜ï˜FÜVÂˆFÚáWFFR¬6ˆÁFWáB¬W6W%ˆñB¬&ñ÷r"¬W7B¬ˆvÚ¬&V÷V÷&W%ˆ∂ñÊC÷b&f6W7v˜∑V∆óGó“"ê†¶7ñÊ2FVb˜7F'Eˆf6W7vˆf∆˜ráWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬ñ÷uˆ'óFW3¢'óFW2¬ÊˆÊR“ÊˆÊR¬W6Uˆ66ÜVC¢&ˆˆ¬“G'VRì†¢W6W%ˆñB“WFFRÊVffV7FófU˜W6W"Êñ@¢F&vWB“ñ÷uˆ'óFW2˜"ÖˆvWEˆ66ÜVE˜Ü˜FÚáW6W%ˆñBíñbW6Uˆ66ÜVBV«6RÊˆÊRê¢ñbÊ˜BF&vWC†¢ˆ6∆V%ˆf6W7v˜W6W%ˆ66ÜRáW6W%ˆñBê¢6ˆÁFWáBÁW6W%ˆFF≤&f6W7vˆf∆˜r%““&vóE˜F&vWB ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	¯Í“	}Õ]›Ωçm‚	˝ççΩç-R	›	Ì	-	Ì	RMÌ-‚¬=MR›=m›‚}Õ]›ç-¬Ωçm‚‚	]ΩÇ›MÌ-‚›]≠ÌΩÕ≠‚ΩÌM]í¬Ú˝Ì≠m2›ÌÕ]Ç˝Ì˝Ìç2-Ω-¬›=m›Ì=‚}]ΩÌ-]≠‚	}-]¬Ú˝Ì˝Ìç2MÌ-‚ΩçmMΩÚ---≠Ç‚ ¢ê¢&WGW&‡¢vóBˆ÷ñ&Uˆ6Üˆ˜6U˜F&vWEˆf6RáWFFR¬6ˆÁFWáB¬W6W%ˆñB¬F&vWBê†¢2)H)H)H)H)H)H)H)H)HvV$FFç-çM≤˝˝Ì˝ÌΩ›]›çÚí)H)H)H)H)H)H)H)H)H ¶7ñÊ2FVbˆÂ˜vV&ˆFFáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢G'ì†¢vB“WFFRÊVffV7FófUˆ÷W76vRÁvV%ˆˆFF¢&r“vBÊFFñbvBV«6R" ¢FF“∑–¢G'ì†¢FF“ß6ˆ‚Ê∆ˆG2á&rê¢WÜ6WBWÜ6WFñˆ„†¢f˜"'Bñ‚á&r˜"""íÁ7∆óBÇ"b"ì†¢ñb#“"ñ‚'C†¢≤¬b“'BÁ7∆óBÇ#“"¬ê¢FF∂µ““`†¢Gó“ÜFFÊvWBÇ'GóR"í˜"FFÊvWBÇ&7Fñˆ‚"í˜"""íÊ∆˜vW"Çê¢ñ÷÷VFñFR“7G"ÜFFÊvWBÇ&ñ÷÷VFñFR"í˜"""íÊ∆˜vW"Çíñ‚Ç#"¬'G'VR"¬'ñW2"¬&ˆ‚"ê¢W6W%ˆñB“WFFRÊVffV7FófU˜W6W"Êñ@†¢ñbGóñ‚Ç'7V'67&ñ&R"¬&'Wí"¬&'Wï˜7V""¬'7V""ì†¢FñW"“ÜFFÊvWBÇ'FñW""í˜"'&Ú"íÊ∆˜vW"Çê¢ñbFñW"Ê˜Bñ‚5T%5ıDîU%3†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›]ç}-]-›Ωí-çB‚	Ì-≠Ìù-R-›çm2-çMÌ"}›Ì-‚‚"ê¢&WGW&‡¢÷ˆÁFá2“÷ÇÉ¬÷ñ‚É"¬ñÁBÜFFÊvWBÇ&÷ˆÁFá2"í˜"ííê¢÷WFÜˆB“ÜFFÊvWBÇ&÷WFÜˆB"í˜"'ñˆıˆ∆¬"íÊ∆˜vW"Çê¢ñb÷WFÜˆBÊ˜Bñ‚îÙıÙDï$T5EÙ‘UDÑÙE3†¢÷WFÜˆB“'ñˆıˆ∆¬ †¢ñbñ÷÷VFñFRÊB˜ñˆıˆFó&V7Eˆ6ˆÊfñwW&VBÇì†¢G'ì†¢í“vóB˜ñˆıˆ7&VFUˆFó&V7E˜ñ÷VÁBáW6W%ˆñB¬FñW"¬÷ˆÁFá2¬÷WFÜˆBê¢ñ÷VÁEˆñB“7G"áíÊvWBÇ&ñB"í˜"""ê¢6ˆÊb“íÊvWBÇ&6ˆÊfó&÷Fñˆ‚"í˜"∑–¢ï˜W&¬“6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂ˜W&¬"í˜"6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂˆFF"í˜"6ˆÊbÊvWBÇ&WáFW&Ê≈˜W&¬"í˜"" ¢ñbÊ˜Bï˜W&√†¢&ó6R'VÁFñ÷TW'&˜"Ç%ñˆÙ∂76FñBÊ˜B&WGW&‚6ˆÊfó&÷Fñˆ‚U$¬"ê¢∆&V¬“îÙıÙDï$T5EÙ‘UDÑÙE5∂÷WFÜˆE’≤&∆&V¬%–¢◊6r“vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b.*Ÿ
-çB∑FñW"ÁWW"Çó“›∂÷ˆÁFá7“Õ]Â∆‚ ¢b-
˝ÌÌ¢∂∆&V«“‚	›mÕç-R≠›Ì˝≠2MΩÚÌ˝Ω-≥≤˝ÌΩR˝ÌM--]mM]›çÚ˝ÌM˝ç≠≠-ç-ç=]-Ú--ÌÕ-ç}]≠Ç‚"¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb'∂∆&V«“(	B˝]]ù-Ç¢Ì˝Ω-R"¬W&√◊ï˜W&¬ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç-	M==Ìí˝ÌÌÌ˝Ω-≤"¬6∆∆&6µˆFF÷b'∆„ß∑FñW'“"ï“¿¢“í¿¢ê¢∑e˜6WBÄ¢b'ñˆÛßVÊFñÊsß∑ñ÷VÁEˆñG“"¿¢ß6ˆ‚ÊGV◊2á≤'W6W%ˆñB#¢W6W%ˆñB¬'FñW"#¢FñW"¬&÷ˆÁFá2#¢÷ˆÁFá2¬&÷WFÜˆB#¢÷WFÜˆG“¬VÁ7W&Uˆ66ñì‘f«6Rí¿¢ê¢6ˆÁFWáBÊ∆ñ6Fñˆ‚Ê7&VFU˜F6≤Ä¢˜ˆ∆≈˜ñˆı˜7V'67&óFñˆÂ˜ñ÷VÁBÜ6ˆÁFWáB¬◊6rÊ6ÜBÊñB¬◊6rÊ÷W76vUˆñB¬W6W%ˆñB¬ñ÷VÁEˆñB¬FñW"¬÷ˆÁFá2ê¢ê¢&WGW&‡¢WÜ6WBWÜ6WFñˆ‚2WÜ3†¢∆ˆrÊWÜ6WFñˆ‚Ç%vV$ñ÷÷VFñFR7V'67&óFñˆ‚ñ÷VÁBfñ∆VC¢W2"¬WÜ2ê†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b-	ÌMÌÕΩ]›çR˝ÌM˝ç≠Ç∑FñW"ÁWW"Çó“›∂÷ˆÁFá7“Õ]Â∆Ì	-Ω]ç-R˝ÌÌÌ˝Ω-≥¢"¿¢&W«ïˆ÷&∑W◊∆Â˜ïˆ∂"áFñW"í¿¢ê¢&WGW&‡†¢ñbGóñ‚Ç'F˜W˜'V""¬''V%˜F˜W"¬&'Wïˆ7&VFóG2"¬&7&VFóE˜6≤"ì†¢&WVW7FVE˜'V"“ñÁBÜFFÊvWBÇ&÷˜VÁB"í˜"FFÊvWBÇ''V""í˜"ê¢&WVW7FVEˆ7&VFóG2“ñÁBÜFFÊvWBÇ&7&VFóG2"í˜"ê¢&W6ˆ«fVB“ˆ7&VFóE˜6µ˜&W6ˆ«fRá&WVW7FVEˆ7&VFóG2¬&WVW7FVE˜'V"ê¢ñbÊ˜B&W6ˆ«fVC†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›]ç}-]-›Ωí˝≠]"≠]Mç-Ì"‚	Ì-≠Ìù-R-›çm2-çMÌ"}›Ì-‚‚"ê¢&WGW&‡¢7&VFóG2¬÷˜VÁE˜'V"“&W6ˆ«fV@¢÷WFÜˆB“ÜFFÊvWBÇ&÷WFÜˆB"í˜"'ñˆıˆ∆¬"íÊ∆˜vW"Çê¢ñb÷WFÜˆBÊ˜Bñ‚îÙıÙDï$T5EÙ‘UDÑÙE3†¢÷WFÜˆB“'ñˆıˆ∆¬ †¢ñbñ÷÷VFñFRÊB˜ñˆıˆFó&V7Eˆ6ˆÊfñwW&VBÇì†¢G'ì†¢í“vóB˜ñˆıˆ7&VFUˆ7&VFóE˜ñ÷VÁBáW6W%ˆñB¬7&VFóG2¬÷˜VÁE˜'V"¬÷WFÜˆBê¢ñ÷VÁEˆñB“7G"áíÊvWBÇ&ñB"í˜"""ê¢6ˆÊb“íÊvWBÇ&6ˆÊfó&÷Fñˆ‚"í˜"∑–¢ï˜W&¬“6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂ˜W&¬"í˜"6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂˆFF"í˜"6ˆÊbÊvWBÇ&WáFW&Ê≈˜W&¬"í˜"" ¢ñbÊ˜Bï˜W&√†¢&ó6R'VÁFñ÷TW'&˜"Ç%ñˆÙ∂76FñBÊ˜B&WGW&‚6ˆÊfó&÷Fñˆ‚U$¬"ê¢∆&V¬“îÙıÙDï$T5EÙ‘UDÑÙE5∂÷WFÜˆE’≤&∆&V¬%–¢◊6r“vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b/	˙©í	˝≠]#¢∂7&VFóG7“≠]Mç-Ì"}∂÷˜VÁE˜'V'“(+“Â∆‚ ¢b-
˝ÌÌ¢∂∆&V«“‚	˝ÌΩRÌ˝Ω-≤≠]Mç-≤›}çΩ˝-Ú--ÌÕ-ç}]≠Ç‚"¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb'∂∆&V«“(	B˝]]ù-Ç¢Ì˝Ω-R"¬W&√◊ï˜W&¬ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç-	M==çR˝≠]-≤"¬6∆∆&6µˆFF“'F˜W"ï“¿¢“í¿¢ê¢∑e˜6WBÄ¢b'ñˆÛ¶7&VFóE˜VÊFñÊsß∑ñ÷VÁEˆñG“"¿¢ß6ˆ‚ÊGV◊2á≤'W6W%ˆñB#¢W6W%ˆñB¬&7&VFóG2#¢7&VFóG2¬&÷˜VÁE˜'V"#¢÷˜VÁE˜'V"¬&÷WFÜˆB#¢÷WFÜˆG“¬VÁ7W&Uˆ66ñì‘f«6Rí¿¢ê¢6ˆÁFWáBÊ∆ñ6Fñˆ‚Ê7&VFU˜F6≤Ä¢˜ˆ∆≈˜ñˆıˆ7&VFóE˜ñ÷VÁBÜ6ˆÁFWáB¬◊6rÊ6ÜBÊñB¬◊6rÊ÷W76vUˆñB¬W6W%ˆñB¬ñ÷VÁEˆñB¬7&VFóG2¬÷˜VÁE˜'V"ê¢ê¢&WGW&‡¢WÜ6WBWÜ6WFñˆ‚2WÜ3†¢∆ˆrÊWÜ6WFñˆ‚Ç%vV$ñ÷÷VFñFR7&VFóBñ÷VÁBfñ∆VC¢W2"¬WÜ2ê†¢vóB˜6VÊEˆñÁfˆñ6U˜'V"Ä¢b'∂7&VFóG7“≠]Mç-Ì""¿¢b-	˝Ì˝ÌΩ›]›çRΩ›ÊWó&Ú‘&˜C¢∂7&VFóG7“≠]Mç-Ì"‚"¿¢÷˜VÁE˜'V"¿¢b'F˜Wß∂7&VFóG7”ß∂÷˜VÁE˜'V'“"¿¢WFFR¿¢ê¢&WGW&‡†¢ñbGóñ‚Ç'F˜Wˆ7'óFÚ"¬&7'óFı˜F˜W"ì†¢ñbÊ˜B5%ïDııïÙïıDÙ¥T„†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ$7'óFÙ&˜B›R›-Ì]“‚"ê¢&WGW&‡¢W6B“f∆ˆBÜFFÊvWBÇ'W6B"í˜"ê¢ñÁeˆñB¬ï˜W&¬¬W6Eˆ÷˜VÁB¬76WB“vóBˆ7'óFıˆ7&VFUˆñÁfˆñ6RáW6B¬76WC“%U4EB"ê¢ñbÊ˜BñÁeˆñB˜"Ê˜Bï˜W&√†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›R=MΩÌ¬Ì}M-¬}""7'óFÙ&˜B‚"ê¢&WGW&‡¢◊6r“vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b-	Ì˝Ω-ç-R}]]r7'óFÙ&˜C¢∑W6Eˆ÷˜VÁC¢„&g“∂76WG“(i"µˆ7&VFóG5ˆf◊Eˆg&ˆ’˜W6BáW6Eˆ÷˜VÁBó“‚"¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˘*7'óFÙ&˜B"¬W&√◊ï˜W&¬ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˘H‚	˝Ì-]ç-¬"¬6∆∆&6µˆFF÷b&7'óFÛ¶6ÜV6≥ß∂ñÁeˆñG“"ï“¿¢“í¿¢ê¢6ˆÁFWáBÊ∆ñ6Fñˆ‚Ê7&VFU˜F6≤Ä¢˜ˆ∆≈ˆ7'óFıˆñÁfˆñ6RÜ6ˆÁFWáB¬◊6rÊ6ÜEˆñB¬◊6rÊ÷W76vUˆñB¬W6W%ˆñB¬ñÁeˆñB¬W6Eˆ÷˜VÁBê¢ê¢&WGW&‡†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	˝ÌΩ=}]›≤M››ΩRçrÕç›Ç›˝çΩÌm]›çÚ¬›‚≠ÌÕ›M›R˝Ì}››‚"ê¢WÜ6WBWÜ6WFñˆ‚2WÜ3†¢∆ˆrÊWÜ6WFñˆ‚Ç&ˆÂ˜vV&ˆFFW'&˜#¢W2"¬WÜ2ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	Ìçç≠ÌÌ-≠ÇM››ΩRÕç›Ç›˝çΩÌm]›çÚ‚"ê†††¢2)H)H)H)H)H)H)H)H)HcìC¢ñ÷VÁBFVW÷∆ñÊ≤f∆∆&6≤)H)H)H)H)H)H)H)H)H ¶7ñÊ2FVbˆÜÊF∆U˜ñ÷VÁE˜7F'E˜ñ∆ˆBáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRí”‚&ˆˆ√†¢&w2“∑7G"áÇ˜"""íÁ7G&óÇíÊ∆˜vW"Çíf˜"Çñ‚Ü6ˆÁFWáBÊ&w2˜"µ“ï–¢ñbÊ˜B&w3†¢&WGW&‚f«6P¢ñ∆ˆB“&w5≥–¢7V%ˆ÷“∞¢'ï˜7V%˜7F'B#¢'7F'B"¿¢'ï˜7V%˜&Ú#¢'&Ú"¿¢'ï˜7V%˜V«Fñ÷FR#¢'V«Fñ÷FR"¿¢–¢6µˆ÷“∞¢'ï˜6µÛ#¢É¬ììí¿¢'ï˜6µÛ3#¢É3¬#sìí¿¢'ï˜6µÛs#¢És¬c#ìí¿¢–¢ñbñ∆ˆBÊ˜Bñ‚7V%ˆ÷ÊBñ∆ˆBÊ˜Bñ‚6µˆ÷†¢&WGW&‚f«6P¢ñbÊ˜B˜ñˆıˆFó&V7Eˆ6ˆÊfñwW&VBÇì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢-	Ì˝Ω-
‰∂76]ù}›R›-Ì]›‚	Ì-≠Ìù-R*Ÿ	˝ÌM˝ç≠+r	˝ÌÕÌù¬çΩÇ›˝ççç-R"˝ÌMM]m≠2‚ ¢ê¢&WGW&‚G'VP†¢W6W%ˆñB“WFFRÊVffV7FófU˜W6W"Êñ@¢÷WFÜˆB“'ñˆıˆ∆¬ ¢∆&V¬“îÙıÙDï$T5EÙ‘UDÑÙE5∂÷WFÜˆE’≤&∆&V¬%–¢G'ì†¢ñbñ∆ˆBñ‚7V%ˆ÷†¢FñW"“7V%ˆ÷∑ñ∆ˆE–¢÷ˆÁFá2“¢í“vóB˜ñˆıˆ7&VFUˆFó&V7E˜ñ÷VÁBáW6W%ˆñB¬FñW"¬÷ˆÁFá2¬÷WFÜˆBê¢ñ÷VÁEˆñB“7G"áíÊvWBÇ&ñB"í˜"""ê¢6ˆÊb“íÊvWBÇ&6ˆÊfó&÷Fñˆ‚"í˜"∑–¢ï˜W&¬“7G"Ü6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂ˜W&¬"í˜"6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂˆFF"í˜"6ˆÊbÊvWBÇ&WáFW&Ê≈˜W&¬"í˜"""ê¢ñbÊ˜Bñ÷VÁEˆñB˜"Ê˜Bï˜W&√†¢&ó6R'VÁFñ÷TW'&˜"Ç%ñˆÙ∂76FñBÊ˜B&WGW&‚6ˆÊfó&÷Fñˆ‚U$¬"ê¢◊6r“vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b.*Ÿ
-çB∑FñW"ÁWW"Çó“›∂÷ˆÁFá7“Õ]Â∆Ì	›mÕç-R≠›Ì˝≠2MΩÚÌ˝Ω-≥≤˝ÌΩR˝ÌM--]mM]›çÚ˝ÌM˝ç≠≠-ç-ç=]-Ú--ÌÕ-ç}]≠Ç‚"¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb'∂∆&V«“(	B˝]]ù-Ç¢Ì˝Ω-R"¬W&√◊ï˜W&¬ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç-	M==Ìí˝ÌÌÌ˝Ω-≤"¬6∆∆&6µˆFF÷b'∆„ß∑FñW'“"ï“¿¢“í¿¢ê¢∑e˜6WBÄ¢b'ñˆÛßVÊFñÊsß∑ñ÷VÁEˆñG“"¿¢ß6ˆ‚ÊGV◊2á≤'W6W%ˆñB#¢W6W%ˆñB¬'FñW"#¢FñW"¬&÷ˆÁFá2#¢÷ˆÁFá2¬&÷WFÜˆB#¢÷WFÜˆG“¬VÁ7W&Uˆ66ñì‘f«6Rí¿¢ê¢6ˆÁFWáBÊ∆ñ6Fñˆ‚Ê7&VFU˜F6≤Ä¢˜ˆ∆≈˜ñˆı˜7V'67&óFñˆÂ˜ñ÷VÁBÜ6ˆÁFWáB¬◊6rÊ6ÜBÊñB¬◊6rÊ÷W76vUˆñB¬W6W%ˆñB¬ñ÷VÁEˆñB¬FñW"¬÷ˆÁFá2ê¢ê¢&WGW&‚G'VP†¢7&VFóG2¬÷˜VÁE˜'V"“6µˆ÷∑ñ∆ˆE–¢í“vóB˜ñˆıˆ7&VFUˆ7&VFóE˜ñ÷VÁBáW6W%ˆñB¬7&VFóG2¬÷˜VÁE˜'V"¬÷WFÜˆBê¢ñ÷VÁEˆñB“7G"áíÊvWBÇ&ñB"í˜"""ê¢6ˆÊb“íÊvWBÇ&6ˆÊfó&÷Fñˆ‚"í˜"∑–¢ï˜W&¬“7G"Ü6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂ˜W&¬"í˜"6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂˆFF"í˜"6ˆÊbÊvWBÇ&WáFW&Ê≈˜W&¬"í˜"""ê¢ñbÊ˜Bñ÷VÁEˆñB˜"Ê˜Bï˜W&√†¢&ó6R'VÁFñ÷TW'&˜"Ç%ñˆÙ∂76FñBÊ˜B&WGW&‚6ˆÊfó&÷Fñˆ‚U$¬"ê¢◊6r“vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b/	˙©í	˝≠]#¢∂7&VFóG7“≠]Mç-Ì"}∂÷˜VÁE˜'V'“(+“Â∆Ì	˝ÌΩRÌ˝Ω-≤≠]Mç-≤›}çΩ˝-Ú--ÌÕ-ç}]≠Ç‚"¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb'∂∆&V«“(	B˝]]ù-Ç¢Ì˝Ω-R"¬W&√◊ï˜W&¬ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç-	M==çR˝≠]-≤"¬6∆∆&6µˆFF“'F˜W"ï“¿¢“í¿¢ê¢∑e˜6WBÄ¢b'ñˆÛ¶7&VFóE˜VÊFñÊsß∑ñ÷VÁEˆñG“"¿¢ß6ˆ‚ÊGV◊2á≤'W6W%ˆñB#¢W6W%ˆñB¬&7&VFóG2#¢7&VFóG2¬&÷˜VÁE˜'V"#¢÷˜VÁE˜'V"¬&÷WFÜˆB#¢÷WFÜˆG“¬VÁ7W&Uˆ66ñì‘f«6Rí¿¢ê¢6ˆÁFWáBÊ∆ñ6Fñˆ‚Ê7&VFU˜F6≤Ä¢˜ˆ∆≈˜ñˆıˆ7&VFóE˜ñ÷VÁBÜ6ˆÁFWáB¬◊6rÊ6ÜBÊñB¬◊6rÊ÷W76vUˆñB¬W6W%ˆñB¬ñ÷VÁEˆñB¬7&VFóG2¬÷˜VÁE˜'V"ê¢ê¢&WGW&‚G'VP¢WÜ6WBWÜ6WFñˆ‚2WÜ3†¢∆ˆrÊWÜ6WFñˆ‚Ç%ñ÷VÁBFVW÷∆ñÊ≤f∆∆&6≤fñ∆VC¢W2"¬WÜ2ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›R=MΩÌ¬Ì}M-¬}"‚	˝Ì˝Ì=ù-R]ùrçΩÇ-Ω]ç-RÌ˝Ω-2}]]r*Ÿ	˝ÌM˝ç≠+r	˝ÌÕÌù¬‚"ê¢&WGW&‚G'VP††¢2)H)H)H)H)H)H)H)H)HcìC¢6W'fW"◊6ñFR6ÜV6∂˜WB'&ñFvRf˜"ñÊ∆ñÊRÙ÷VÁR÷ñÊí2)H)H)H)H)H)H)H)H)H ¶FVb˜f∆ñFFU˜FV∆Vw&’˜vV&ˆñÊóEˆFFÜñÊóEˆFF¢7G"¬÷ÖˆvU˜3¢ñÁB“ÉcCí”‚Fñ7C†¢""%f∆ñFFRFV∆Vw&“÷ñÊíñÊóDFFÊB&WGW&‚'6VBfñV∆G2‡†¢ñÊ∆ñÊRÙ÷VÁR÷ñÊí2&V6VófRVW'ïˆñBÊB◊W7B6ˆ÷◊VÊñ6FRFá&˜VvÇ¢6W'fW"◊6ñFR'&ñFvR‚ÊWfW"G'W7BW6W"ñB˜"W&6Ü6R&÷WFW'2g&ˆ“•0¢vóFÜ˜WBf∆ñFFñÊrñÊóDFFW6ñÊrFÜR&˜BFˆ∂V‚‡¢"" ¢&r“ÜñÊóEˆFF˜"""íÁ7G&óÇê¢ñbÊ˜B&s†¢&ó6Rf«VTW'&˜"Ç%FV∆Vw&“ñÊóDFFó2V◊Gí"ê¢ó'2“W&∆∆ñ"Á'6RÁ'6U˜6¬á&r¬∂VWˆ&∆Êµ˜f«VW3’G'VRê¢FF“∑7G"Ü≤ì¢7G"ábíf˜"≤¬bñ‚ó'7–¢&V6VófVEˆÜ6Ç“FFÁ˜Ç&Ü6Ç"¬""ê¢2f˜"&˜B◊Fˆ∂V‚Ñ‘2f∆ñFFñˆ‚¬∆¬&V6VófVBfñV∆G2WÜ6WBÜ6Ç&V÷ñ‡¢2ñ‚FÜRFF÷6ÜV6≤7G&ñÊr¬ñÊ6«VFñÊrFÜR˜FñˆÊ¬6ñvÊGW&RfñV∆B‡¢ñbÊ˜B&V6VófVEˆÜ6É†¢&ó6Rf«VTW'&˜"Ç%FV∆Vw&“ñÊóDFFÜ6Çó2÷ó76ñÊr"ê¢FFˆ6ÜV6µ˜7G&ñÊr“%∆‚"Ê¶ˆñ‚Üb'∂∑”◊∂FF∂µ◊“"f˜"≤ñ‚6˜'FVBÜFFíê¢6V7&WEˆ∂Wí“Ü÷2ÊÊWrÜ"%vV$FF"¬$ıEıDÙ¥T‚ÊVÊ6ˆFRÇ'WFb”Ç"í¬Ü6Ü∆ñ"Á6Ü#SbíÊFñvW7BÇê¢6∆7V∆FVEˆÜ6Ç“Ü÷2ÊÊWrá6V7&WEˆ∂Wí¬FFˆ6ÜV6µ˜7G&ñÊrÊVÊ6ˆFRÇ'WFb”Ç"í¬Ü6Ü∆ñ"Á6Ü#SbíÊÜWÜFñvW7BÇê¢ñbÊ˜BÜ÷2Ê6ˆ◊&UˆFñvW7BÜ6∆7V∆FVEˆÜ6Ç¬&V6VófVEˆÜ6Çì†¢&ó6Rf«VTW'&˜"Ç%FV∆Vw&“ñÊóDFF6ñvÊGW&Ró2ñÁf∆ñB"ê¢WFÖˆFFR“ñÁBÜFFÊvWBÇ&WFÖˆFFR"í˜"ê¢Ê˜u˜G2“ñÁBáFñ÷RÁFñ÷RÇíê¢ñbÊ˜BWFÖˆFFR˜"WFÖˆFFR‚Ê˜u˜G2≤c˜"Ê˜u˜G2“WFÖˆFFR‚÷ÖˆvU˜3†¢&ó6Rf«VTW'&˜"Ç%FV∆Vw&“ñÊóDFFÜ2Wáó&VB"ê¢W6W%˜&r“FFÊvWBÇ'W6W""í˜"'∑“ ¢G'ì†¢W6W"“ß6ˆ‚Ê∆ˆG2áW6W%˜&rê¢WÜ6WBWÜ6WFñˆ‚2WÜ3†¢&ó6Rf«VTW'&˜"Ç%FV∆Vw&“ñÊóDFFW6W"ó2ñÁf∆ñB"íg&ˆ“WÜ0¢W6W%ˆñB“ñÁBáW6W"ÊvWBÇ&ñB"í˜"ê¢ñbW6W%ˆñB√“†¢&ó6Rf«VTW'&˜"Ç%FV∆Vw&“W6W"ñBó2÷ó76ñÊr"ê¢FF≤'W6W%ˆˆ&¢%““W6W ¢FF≤'W6W%ˆñB%““W6W%ˆñ@¢&WGW&‚FF††¶FVbˆñÁ7F∆≈˜vV&ˆ6ÜV6∂˜WEˆ'&ñFvRÜ∆ñ6Fñˆ‚ì†¢""$WáFVÊBD"w2F˜&ÊFÚvV&Üˆˆ≤vóFÇ˜vV&ˆ6ÜV6∂˜WB‡†¢D"#„bFˆW2Ê˜BWá˜6R7W7Fˆ“&˜WFW2ñ‚'VÂ˜vV&Üˆˆ≤¬6ÚFÜó2&W∆6W2ˆÊ«ê¢FÜR6÷∆¬ñÁFW&Ê¬vV&Üˆˆ¥6∆72vÜñ∆R&W6W'fñÊrFV∆Vw&‘ÜÊF∆W"‡¢"" ¢G'ì†¢ñ◊˜'BF˜&ÊFÚÁvV ¢ñ◊˜'BFV∆Vw&“ÊWáBÂ˜WFFW"2F%˜WFFW ¢g&ˆ“FV∆Vw&“ÊWáBÂ˜WFñ«2ÁvV&Üˆˆ∂ÜÊF∆W"ñ◊˜'BFV∆Vw&‘ÜÊF∆W ¢WÜ6WBWÜ6WFñˆ‚2WÜ3†¢∆ˆrÊWÜ6WFñˆ‚Ç$6ÜV6∂˜WB'&ñFvRFWVÊFVÊ6ñW2VÊfñ∆&∆S¢W2"¬WÜ2ê¢&WGW&‚f«6P†¢6∆726ÜV6∂˜WD'&ñFvTÜÊF∆W"áF˜&ÊFÚÁvV"Â&WVW7DÜÊF∆W"ì†¢FVb6WEˆFVfV«EˆÜVFW'2á6V∆bì†¢6V∆bÁ6WEˆÜVFW"Ç$6ˆÁFVÁB’GóR"¬&∆ñ6Fñˆ‚ˆß6ˆ„≤6Ü'6WC◊WFb”Ç"ê¢6V∆bÁ6WEˆÜVFW"Ç$66W72‘6ˆÁG&ˆ¬‘∆∆˜r‘˜&ñvñ‚"¬"¢"ê¢6V∆bÁ6WEˆÜVFW"Ç$66W72‘6ˆÁG&ˆ¬‘∆∆˜r‘ÜVFW'2"¬$6ˆÁFVÁB’GóR"ê¢6V∆bÁ6WEˆÜVFW"Ç$66W72‘6ˆÁG&ˆ¬‘∆∆˜r‘÷WFÜˆG2"¬%ı5B¬ıDîÙÂ2"ê¢6V∆bÁ6WEˆÜVFW"Ç$66ÜR‘6ˆÁG&ˆ¬"¬&ÊÚ◊7F˜&R"ê†¢7ñÊ2FVbvWBá6V∆bì†¢6V∆bÊfñÊó6ÇÜß6ˆ‚ÊGV◊2á≤&ˆ≤#¢G'VR¬'fW'6ñˆ‚#¢D4ÖıdU%4îÙ‚¬'&˜WFR#¢"˜vV&ˆ6ÜV6∂˜WB'“¬VÁ7W&Uˆ66ñì‘f«6Ríê†¢7ñÊ2FVbÜVBá6V∆bì†¢6V∆bÁ6WE˜7FGW2É#Bê¢6V∆bÊfñÊó6ÇÇê†¢7ñÊ2FVb˜FñˆÁ2á6V∆bì†¢6V∆bÁ6WE˜7FGW2É#Bê¢6V∆bÊfñÊó6ÇÇê†¢7ñÊ2FVb˜7Bá6V∆bì†¢G'ì†¢ñbÊ˜B˜ñˆıˆFó&V7Eˆ6ˆÊfñwW&VBÇì†¢6V∆bÁ6WE˜7FGW2ÉS2ê¢6V∆bÊfñÊó6ÇÜß6ˆ‚ÊGV◊2á≤&ˆ≤#¢f«6R¬&W'&˜"#¢%ñˆÙ∂76Fó&V7Bíó2Ê˜B6ˆÊfñwW&VB'“¬VÁ7W&Uˆ66ñì‘f«6Ríê¢&WGW&‡¢G'ì†¢&ˆGí“ß6ˆ‚Ê∆ˆG2á6V∆bÁ&WVW7BÊ&ˆGíÊFV6ˆFRÇ'WFb”Ç"í˜"'∑“"ê¢WÜ6WBWÜ6WFñˆ„†¢6V∆bÁ6WE˜7FGW2ÉCê¢6V∆bÊfñÊó6ÇÜß6ˆ‚ÊGV◊2á≤&ˆ≤#¢f«6R¬&W'&˜"#¢$ñÁf∆ñB•4Ù‚'“¬VÁ7W&Uˆ66ñì‘f«6Ríê¢&WGW&‡¢ñÊóEˆFF“7G"Ü&ˆGíÊvWBÇ&ñÊóEˆFF"í˜"""ê¢W&6Ü6R“&ˆGíÊvWBÇ'W&6Ü6R"í˜"∑–¢ñbÊ˜Bó6ñÁ7FÊ6RáW&6Ü6R¬Fñ7Bì†¢&ó6Rf«VTW'&˜"Ç$ñÁf∆ñBW&6Ü6Rñ∆ˆB"ê¢f∆ñFFVB“˜f∆ñFFU˜FV∆Vw&’˜vV&ˆñÊóEˆFFÜñÊóEˆFFê¢W6W%ˆñB“ñÁBáf∆ñFFVE≤'W6W%ˆñB%“ê¢Gó“7G"áW&6Ü6RÊvWBÇ'GóR"í˜"W&6Ü6RÊvWBÇ&7Fñˆ‚"í˜"""íÊ∆˜vW"Çê¢÷WFÜˆB“7G"áW&6Ü6RÊvWBÇ&÷WFÜˆB"í˜"'ñˆıˆ∆¬"íÊ∆˜vW"Çê¢ñb÷WFÜˆBÊ˜Bñ‚îÙıÙDï$T5EÙ‘UDÑÙE3†¢÷WFÜˆB“'ñˆıˆ∆¬ †¢ñbGóñ‚Ç'7V'67&ñ&R"¬&'Wí"¬&'Wï˜7V""¬'7V""ì†¢FñW"“7G"áW&6Ü6RÊvWBÇ'FñW""í˜"'&Ú"íÊ∆˜vW"Çê¢ñbFñW"Ê˜Bñ‚5T%5ıDîU%3†¢&ó6Rf«VTW'&˜"Ç%VÊ∂Ê˜v‚7V'67&óFñˆ‚FñW""ê¢÷ˆÁFá2“÷ÇÉ¬÷ñ‚É"¬ñÁBáW&6Ü6RÊvWBÇ&÷ˆÁFá2"í˜"ííê¢í“vóB˜ñˆıˆ7&VFUˆFó&V7E˜ñ÷VÁBáW6W%ˆñB¬FñW"¬÷ˆÁFá2¬÷WFÜˆBê¢ñ÷VÁEˆñB“7G"áíÊvWBÇ&ñB"í˜"""ê¢6ˆÊb“íÊvWBÇ&6ˆÊfó&÷Fñˆ‚"í˜"∑–¢ï˜W&¬“7G"Ü6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂ˜W&¬"í˜"6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂˆFF"í˜"6ˆÊbÊvWBÇ&WáFW&Ê≈˜W&¬"í˜"""ê¢ñbÊ˜Bñ÷VÁEˆñB˜"Ê˜Bï˜W&√†¢&ó6R'VÁFñ÷TW'&˜"Ç%ñˆÙ∂76FñBÊ˜B&WGW&‚6ˆÊfó&÷Fñˆ‚U$¬"ê¢∆&V¬“îÙıÙDï$T5EÙ‘UDÑÙE5∂÷WFÜˆE’≤&∆&V¬%–¢◊6r“vóB∆ñ6Fñˆ‚Ê&˜BÁ6VÊEˆ÷W76vRÄ¢6ÜEˆñC◊W6W%ˆñB¿¢FWáC“Ä¢b.*Ÿ
-çB∑FñW"ÁWW"Çó“›∂÷ˆÁFá7“Õ]Â∆‚ ¢b-
˝ÌÌ¢∂∆&V«“‚	›mÕç-R≠›Ì˝≠2MΩÚÌ˝Ω-≥≤˝ÌΩR˝ÌM--]mM]›çÚ˝ÌM˝ç≠≠-ç-ç=]-Ú--ÌÕ-ç}]≠Ç‚ ¢í¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb'∂∆&V«“(	B˝]]ù-Ç¢Ì˝Ω-R"¬W&√◊ï˜W&¬ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç-	M==Ìí˝ÌÌÌ˝Ω-≤"¬6∆∆&6µˆFF÷b'∆„ß∑FñW'“"ï“¿¢“í¿¢ê¢∑e˜6WBÄ¢b'ñˆÛßVÊFñÊsß∑ñ÷VÁEˆñG“"¿¢ß6ˆ‚ÊGV◊2á≤'W6W%ˆñB#¢W6W%ˆñB¬'FñW"#¢FñW"¬&÷ˆÁFá2#¢÷ˆÁFá2¬&÷WFÜˆB#¢÷WFÜˆG“¬VÁ7W&Uˆ66ñì‘f«6Rí¿¢ê¢6ñ◊∆Uˆ6ˆÁFWáB“GóW2Â6ñ◊∆TÊ÷W76RÜ&˜C÷∆ñ6Fñˆ‚Ê&˜Bê¢∆ñ6Fñˆ‚Ê7&VFU˜F6≤Ä¢˜ˆ∆≈˜ñˆı˜7V'67&óFñˆÂ˜ñ÷VÁBá6ñ◊∆Uˆ6ˆÁFWáB¬◊6rÊ6ÜBÊñB¬◊6rÊ÷W76vUˆñB¬W6W%ˆñB¬ñ÷VÁEˆñB¬FñW"¬÷ˆÁFá2ê¢ê¢&W7V«B“≤&ˆ≤#¢G'VR¬'W&¬#¢ï˜W&¬¬'ñ÷VÁEˆñB#¢ñ÷VÁEˆñB¬&∂ñÊB#¢'7V'67&óFñˆ‚'–†¢V∆ñbGóñ‚Ç'F˜W˜'V""¬''V%˜F˜W"¬&'Wïˆ7&VFóG2"¬&7&VFóE˜6≤"ì†¢&WVW7FVE˜'V"“ñÁBáW&6Ü6RÊvWBÇ&÷˜VÁB"í˜"W&6Ü6RÊvWBÇ''V""í˜"ê¢&WVW7FVEˆ7&VFóG2“ñÁBáW&6Ü6RÊvWBÇ&7&VFóG2"í˜"ê¢&W6ˆ«fVB“ˆ7&VFóE˜6µ˜&W6ˆ«fRá&WVW7FVEˆ7&VFóG2¬&WVW7FVE˜'V"ê¢ñbÊ˜B&W6ˆ«fVC†¢&ó6Rf«VTW'&˜"Ç%VÊ∂Ê˜v‚7&VFóB6∂vR"ê¢7&VFóG2¬÷˜VÁE˜'V"“&W6ˆ«fV@¢í“vóB˜ñˆıˆ7&VFUˆ7&VFóE˜ñ÷VÁBáW6W%ˆñB¬7&VFóG2¬÷˜VÁE˜'V"¬÷WFÜˆBê¢ñ÷VÁEˆñB“7G"áíÊvWBÇ&ñB"í˜"""ê¢6ˆÊb“íÊvWBÇ&6ˆÊfó&÷Fñˆ‚"í˜"∑–¢ï˜W&¬“7G"Ü6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂ˜W&¬"í˜"6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂˆFF"í˜"6ˆÊbÊvWBÇ&WáFW&Ê≈˜W&¬"í˜"""ê¢ñbÊ˜Bñ÷VÁEˆñB˜"Ê˜Bï˜W&√†¢&ó6R'VÁFñ÷TW'&˜"Ç%ñˆÙ∂76FñBÊ˜B&WGW&‚6ˆÊfó&÷Fñˆ‚U$¬"ê¢∆&V¬“îÙıÙDï$T5EÙ‘UDÑÙE5∂÷WFÜˆE’≤&∆&V¬%–¢◊6r“vóB∆ñ6Fñˆ‚Ê&˜BÁ6VÊEˆ÷W76vRÄ¢6ÜEˆñC◊W6W%ˆñB¿¢FWáC“Ä¢b/	˙©í	˝≠]#¢∂7&VFóG7“≠]Mç-Ì"}∂÷˜VÁE˜'V'“(+“Â∆‚ ¢b-
˝ÌÌ¢∂∆&V«“‚	˝ÌΩRÌ˝Ω-≤≠]Mç-≤›}çΩ˝-Ú--ÌÕ-ç}]≠Ç‚ ¢í¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb'∂∆&V«“(	B˝]]ù-Ç¢Ì˝Ω-R"¬W&√◊ï˜W&¬ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç-	M==çR˝≠]-≤"¬6∆∆&6µˆFF“'F˜W"ï“¿¢“í¿¢ê¢∑e˜6WBÄ¢b'ñˆÛ¶7&VFóE˜VÊFñÊsß∑ñ÷VÁEˆñG“"¿¢ß6ˆ‚ÊGV◊2á≤'W6W%ˆñB#¢W6W%ˆñB¬&7&VFóG2#¢7&VFóG2¬&÷˜VÁE˜'V"#¢÷˜VÁE˜'V"¬&÷WFÜˆB#¢÷WFÜˆG“¬VÁ7W&Uˆ66ñì‘f«6Rí¿¢ê¢6ñ◊∆Uˆ6ˆÁFWáB“GóW2Â6ñ◊∆TÊ÷W76RÜ&˜C÷∆ñ6Fñˆ‚Ê&˜Bê¢∆ñ6Fñˆ‚Ê7&VFU˜F6≤Ä¢˜ˆ∆≈˜ñˆıˆ7&VFóE˜ñ÷VÁBá6ñ◊∆Uˆ6ˆÁFWáB¬◊6rÊ6ÜBÊñB¬◊6rÊ÷W76vUˆñB¬W6W%ˆñB¬ñ÷VÁEˆñB¬7&VFóG2¬÷˜VÁE˜'V"ê¢ê¢&W7V«B“≤&ˆ≤#¢G'VR¬'W&¬#¢ï˜W&¬¬'ñ÷VÁEˆñB#¢ñ÷VÁEˆñB¬&∂ñÊB#¢&7&VFóG2'–¢V«6S†¢&ó6Rf«VTW'&˜"Ç%VÊ∂Ê˜v‚W&6Ü6RGóR"ê†¢6V∆bÁ6WE˜7FGW2É#ê¢6V∆bÊfñÊó6ÇÜß6ˆ‚ÊGV◊2á&W7V«B¬VÁ7W&Uˆ66ñì‘f«6Ríê¢WÜ6WBf«VTW'&˜"2WÜ3†¢∆ˆrÁv&ÊñÊrÇ%vV$6ÜV6∂˜WB&V¶V7FVC¢W2"¬WÜ2ê¢6V∆bÁ6WE˜7FGW2ÉCê¢6V∆bÊfñÊó6ÇÜß6ˆ‚ÊGV◊2á≤&ˆ≤#¢f«6R¬&W'&˜"#¢7G"ÜWÜ2ó“¬VÁ7W&Uˆ66ñì‘f«6Ríê¢WÜ6WBWÜ6WFñˆ‚2WÜ3†¢∆ˆrÊWÜ6WFñˆ‚Ç%vV$6ÜV6∂˜WB'&ñFvRfñ∆VC¢W2"¬WÜ2ê¢6V∆bÁ6WE˜7FGW2ÉSê¢÷W76vR“7G"ÜWÜ2ï≥£S“ñbîÙıÙDT%TuıïÙU%$ı%2V«6R-	›R=MΩÌ¬Ì}M-¬Ì˝Ω-2 ¢6V∆bÊfñÊó6ÇÜß6ˆ‚ÊGV◊2á≤&ˆ≤#¢f«6R¬&W'&˜"#¢÷W76vW“¬VÁ7W&Uˆ66ñì‘f«6Ríê†¢6∆726ÜV6∂˜WEvV&Üˆˆ¥áF˜&ÊFÚÁvV"‰∆ñ6Fñˆ‚ì†¢FVbıˆñÊóEıÚá6V∆b¬vV&Üˆˆµ˜FÇ¬&˜B¬WFFU˜VWVR¬6V7&WE˜Fˆ∂V„‘ÊˆÊRì†¢6Ü&VB“≤&&˜B#¢&˜B¬'WFFU˜VWVR#¢WFFU˜VWVR¬'6V7&WE˜Fˆ∂V‚#¢6V7&WE˜Fˆ∂VÁ–¢ÜÊF∆W'2“∞¢á&b'∑vV&Üˆˆµ˜Fá“ÛÚ"¬FV∆Vw&‘ÜÊF∆W"¬6Ü&VBí¿¢á""˜vV&ˆ6ÜV6∂˜WBÛÚ"¬6ÜV6∂˜WD'&ñFvTÜÊF∆W"í¿¢á""ˆÜV«Fá¢ÛÚ"¬ÜV«FÑ'&ñFvTÜÊF∆W"í¿¢á""ÛÚ"¬&ˆ˜D'&ñFvTÜÊF∆W"í¿¢–¢7WW"ÇíÂıˆñÊóEıÚÜÜÊF∆W'2ê†¢FVb∆ˆu˜&WVW7Bá6V∆b¬ÜÊF∆W"ì†¢7FGW2“ÜÊF∆W"ÊvWE˜7FGW2Çê¢ñb7FGW2„“C†¢∆ˆrÁv&ÊñÊrÇ$ÖEEW2W2W2"¬7FGW2¬ÜÊF∆W"Á&WVW7BÊ÷WFÜˆB¬ÜÊF∆W"Á&WVW7BÁW&íê†¢6∆72ÜV«FÑ'&ñFvTÜÊF∆W"áF˜&ÊFÚÁvV"Â&WVW7DÜÊF∆W"ì†¢7ñÊ2FVbvWBá6V∆bì†¢6V∆bÁ6WEˆÜVFW"Ç$6ˆÁFVÁB’GóR"¬&∆ñ6Fñˆ‚ˆß6ˆ„≤6Ü'6WC◊WFb”Ç"ê¢6V∆bÊfñÊó6ÇÜß6ˆ‚ÊGV◊2á≤&ˆ≤#¢G'VR¬'fW'6ñˆ‚#¢D4ÖıdU%4îÙÁ“¬VÁ7W&Uˆ66ñì‘f«6Ríê†¢7ñÊ2FVbÜVBá6V∆bì†¢6V∆bÁ6WE˜7FGW2É#Bê¢6V∆bÊfñÊó6ÇÇê†¢6∆72&ˆ˜D'&ñFvTÜÊF∆W"áF˜&ÊFÚÁvV"Â&WVW7DÜÊF∆W"ì†¢7ñÊ2FVbvWBá6V∆bì†¢6V∆bÁ6WEˆÜVFW"Ç$6ˆÁFVÁB’GóR"¬&∆ñ6Fñˆ‚ˆß6ˆ„≤6Ü'6WC◊WFb”Ç"ê¢6V∆bÊfñÊó6ÇÜß6ˆ‚ÊGV◊2á≤&ˆ≤#¢G'VR¬'6W'fñ6R#¢$ÊWó&Ú‘&˜B"¬'fW'6ñˆ‚#¢D4ÖıdU%4îÙÁ“¬VÁ7W&Uˆ66ñì‘f«6Ríê†¢7ñÊ2FVbÜVBá6V∆bì†¢6V∆bÁ6WE˜7FGW2É#Bê¢6V∆bÊfñÊó6ÇÇê†¢F%˜WFFW"ÂvV&Üˆˆ¥6∆72“6ÜV6∂˜WEvV&Üˆˆ¥ ¢∆ˆrÊñÊfÚÇ%vV$6ÜV6∂˜WBˆ÷VÁR'&ñFvRñÁ7F∆∆VC¢W2˜vV&ˆ6ÜV6∂˜WB"¬T$ƒî5ıU$¬Á'7G&óÇ"Ú"íê¢&WGW&‚G'VP††¢2)H)H)H)H)H)H)H)H)H6∆∆&6µVW'íç-Ì-ΩÕ›ÌRí)H)H)H)H)H)H)H)H)H •˜VÊFñÊuˆ7FñˆÁ2“∑–†¶FVbˆÊWuˆñBÇí”‚7G#†¢&WGW&‚WVñBÁWVñCBÇíÊÜWÖ≥£%–†¶7ñÊ2FVbˆÂˆ6"áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢“WFFRÊ6∆∆&6µ˜VW'ê¢FF“áÊFF˜"""íÁ7G&óÇê¢G'ì†¢2&W6VÁFFñˆ‚Ù6F∆ˆr7GVFñÚcÉ`¢ñbFFÁ7F'G7vóFÇÇ'3¢"ì†¢G'ì†¢vóB˜&W6VÁFFñˆÂ˜7GVFñıˆvWBÇíÊÜÊF∆Uˆ6∆∆&6≤áWFFR¬6ˆÁFWáBê¢WÜ6WBWÜ6WFñˆ‚2S†¢2&W6VÁFFñˆÂ7GVFñÚ«&VGíW'6ó7G27FFRÊB&W˜'G27FvR◊7V6ñfñ2W'&˜'2‡¢2FÚÊ˜B∆V≤FÜó2ñÁFÚFÜR&˜B◊vñFRvVÊW&ñ26∆∆&6≤ˆW'&˜"÷W76vW2‡¢∆ˆrÊWÜ6WFñˆ‚Ç%&W6VÁFFñˆ‚6∆∆&6≤fñ∆VB∆ˆ6∆«ì¢W2"¬Rê¢&WGW&‡†¢2W'6ó7FVÁBfó'GV¬6ÜG0¢ñbFF”“&6ÜC¶∆ó7B#†¢vóBÊÁ7vW"Çê¢vóB6÷Eˆ6ÜG2áWFFR¬6ˆÁFWáBê¢&WGW&‡¢ñbFF”“&6ÜC¶ÊWr#†¢vóBÊÁ7vW"Çê¢vóB6÷EˆÊWv6ÜBáWFFR¬6ˆÁFWáBê¢&WGW&‡¢ñbFFÁ7F'G7vóFÇÇ&6ÜC¶˜V„¢"ì†¢vóBÊÁ7vW"Çê¢G'ì¢6ñB“ñÁBÜFFÁ7∆óBÇ#¢"¬"ï≥%“ê¢WÜ6WBWÜ6WFñˆ„¢6ñB“ ¢ñbÊ˜B6ñB˜"Ê˜Bˆ6ÜE˜6WEˆ7FófRáÊg&ˆ’˜W6W"ÊñB¬Ê÷W76vRÊ6ÜEˆñB¬6ñBì†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-
}"›R›ùM]“‚"ê¢&WGW&‡¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢FóF∆R“ÊWáBÇáÖ≤'FóF∆R%“f˜"Çñ‚ˆ6ÜEˆ∆ó7BáÊg&ˆ’˜W6W"ÊñB¬Ê÷W76vRÊ6ÜEˆñBíñbÖ≤&ñB%“”“6ñBí¬-
}""ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÜb.)kn˚àÚ
}"*∑∑FóF∆W‹+≤-Ω“‚	˝ÌMÌΩmù-R}=Ì-Ì‚"¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡¢ñbFFÁ7F'G7vóFÇÇ&6ÜC¶Üó7F˜'ì¢"ì†¢vóBÊÁ7vW"Çê¢'G2“FFÁ7∆óBÇ#¢"ê¢G'ì¢6ñB“ñÁBá'G5≥%“ì≤vR“ñÁBá'G5≥5“íñb∆V‚á'G2í‚2V«6R ¢WÜ6WBWÜ6WFñˆ„¢6ñB¬vR“¬ ¢ñb6ñC†¢vóB˜6VÊEˆ6ÜEˆÜó7F˜'íáWFFR¬6ˆÁFWáB¬6ñB¬vRê¢&WGW&‡¢ñbFFÁ7F'G7vóFÇÇ&6ÜCß&VÊ÷S¢"ì†¢vóBÊÁ7vW"Çê¢G'ì¢6ñB“ñÁBÜFFÁ7∆óBÇ#¢"¬"ï≥%“ê¢WÜ6WBWÜ6WFñˆ„¢6ñB“ ¢ñb6ñC†¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊuˆ6ÜE˜&VÊ÷R%““6ñ@¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ.)»˛˚àÚ	Ì-˝-Õ-R›Ì-ÌR›}-›çR}-ÌM›ç¬ÌÌù]›ç]¬çM‚cçÕ-ÌΩÌ"í‚"ê¢&WGW&‡¢ñbFFÁ7F'G7vóFÇÇ&6ÜC¶FV∆WFUˆ6ˆÊfó&”¢"ì†¢vóBÊÁ7vW"Çê¢G'ì¢6ñB“ñÁBÜFFÁ7∆óBÇ#¢"¬"ï≥%“ê¢WÜ6WBWÜ6WFñˆ„¢6ñB“ ¢ñb6ñBÊBˆ6ÜEˆFV∆WFRáÊg&ˆ’˜W6W"ÊñB¬Ê÷W76vRÊ6ÜEˆñB¬6ñBì†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ/	˘y
}"Ç]=‚ç-ÌçÚ=MΩ]›≤‚"¬&W«ïˆ÷&∑W’ˆ6ÜEˆ∆ó7Eˆ∂"áÊg&ˆ’˜W6W"ÊñB¬Ê÷W76vRÊ6ÜEˆñBíê¢V«6S†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-
}"›R›ùM]“‚"ê¢&WGW&‡¢ñbFFÁ7F'G7vóFÇÇ&6ÜC¶FV∆WFS¢"ì†¢vóBÊÁ7vW"Çê¢G'ì¢6ñB“ñÁBÜFFÁ7∆óBÇ#¢"¬"ï≥%“ê¢WÜ6WBWÜ6WFñˆ„¢6ñB“ ¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢-
=MΩç-¬›-Ì"}"-Õ]-R‚-]íç-Ìç]ìÚ"¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç-	M¬=MΩç-¬"¬6∆∆&6µˆFF÷b&6ÜC¶FV∆WFUˆ6ˆÊfó&”ß∂6ñG“"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç-	Ì-Õ]›"¬6∆∆&6µˆFF“&6ÜC¶∆ó7B"ï“¿¢“í¿¢ê¢&WGW&‡†¢ñbFF”“'&ñ6ñÊs¶∆ó7B#†¢vóBÊÁ7vW"Çê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢˜&ñ6ñÊuˆ6F∆ˆu˜FWáBÇí¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖµ¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.)ÈR	˝Ì˝ÌΩ›ç-¬Ω›"¬6∆∆&6µˆFF“'F˜W"ï’“í¿¢ê¢&WGW&‡†¢2DıUÕ]›‡¢ñbFF”“'F˜W#†¢vóBÊÁ7vW"Çê¢vóB˜6VÊE˜F˜Wˆ÷VÁRáWFFR¬6ˆÁFWáBê¢&WGW&‡†¢2DıU%T ¢ñbFFÁ7F'G7vóFÇÇ'F˜Wß'V#¢"ì†¢vóBÊÁ7vW"Çê¢G'ì†¢÷˜VÁE˜'V"“ñÁBÇÜFFÁ7∆óBÇ#¢"¬"ï≤”“˜"#"íÁ7G&óÇí˜"#"ê¢WÜ6WBWÜ6WFñˆ„†¢÷˜VÁE˜'V"“ ¢&W6ˆ«fVB“ˆ7&VFóE˜6µ˜&W6ˆ«fRÉ¬÷˜VÁE˜'V"ê¢ñbÊ˜B&W6ˆ«fVC†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	›]ç}-]-›Ωí˝≠]"≠]Mç-Ì"‚	Ì-≠Ìù-RÕ]›‚˝Ì˝ÌΩ›]›çÚ}›Ì-‚‚"ê¢&WGW&‡¢7&VFóG2¬÷˜VÁE˜'V"“&W6ˆ«fV@¢ˆ≤“vóB˜6VÊEˆñÁfˆñ6U˜'V"Ä¢b'∂7&VFóG7“≠]Mç-Ì""¿¢b-	˝Ì˝ÌΩ›]›çRΩ›ÊWó&Ú‘&˜C¢∂7&VFóG7“≠]Mç-Ì"‚"¿¢÷˜VÁE˜'V"¿¢b'F˜Wß∂7&VFóG7”ß∂÷˜VÁE˜'V'“"¿¢WFFR¿¢ê¢vóBÊÁ7vW"Ç-	-Ω--Ω˝‚}.(
b"ñbˆ≤V«6R-	›R=MΩÌ¬-Ω--ç-¬}""¬6Ü˜uˆ∆W'C÷Ê˜Bˆ≤ê¢&WGW&‡†¢2DıU5%ïD¢ñbFFÁ7F'G7vóFÇÇ'F˜W¶7'óFÛ¢"ì†¢vóBÊÁ7vW"Çê¢ñbÊ˜B5%ïDııïÙïıDÙ¥T„†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	›-Ìù-R5%ïDııïÙïıDÙ¥T‚MΩÚÌ˝Ω-≤}]]r7'óFÙ&˜B‚"ê¢&WGW&‡¢G'ì†¢W6B“f∆ˆBÇÜFFÁ7∆óBÇ#¢"¬"ï≤”“˜"#"íÁ7G&óÇí˜"#"ê¢WÜ6WBWÜ6WFñˆ„†¢W6B“„ ¢ñbW6B√“„†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	›]-]›Ú=ÕÕ‚"ê¢&WGW&‡¢ñÁeˆñB¬ï˜W&¬¬W6Eˆ÷˜VÁB¬76WB“vóBˆ7'óFıˆ7&VFUˆñÁfˆñ6RáW6B¬76WC“%U4EB"¬FW67&óFñˆ„“%v∆∆WBF˜◊W"ê¢ñbÊ˜BñÁeˆñB˜"Ê˜Bï˜W&√†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	›R=MΩÌ¬Ì}M-¬}""7'óFÙ&˜B‚	˝Ì˝Ì=ù-R˝Ì}mR‚"ê¢&WGW&‡¢◊6r“vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b-	Ì˝Ω-ç-R}]]r7'óFÙ&˜C¢∑W6Eˆ÷˜VÁC¢„&g“∂76WG“(i"µˆ7&VFóG5ˆf◊Eˆg&ˆ’˜W6BáW6Eˆ÷˜VÁBó“Â∆Ì	˝ÌΩRÌ˝Ω-≤≠]Mç-≤˝Ì˝ÌΩ›˝-Ú--ÌÕ-ç}]≠Ç‚"¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˘*7'óFÙ&˜B"¬W&√◊ï˜W&¬ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˘H‚	˝Ì-]ç-¬"¬6∆∆&6µˆFF÷b&7'óFÛ¶6ÜV6≥ß∂ñÁeˆñG“"ï–¢“ê¢ê¢6ˆÁFWáBÊ∆ñ6Fñˆ‚Ê7&VFU˜F6≤Ö˜ˆ∆≈ˆ7'óFıˆñÁfˆñ6RÄ¢6ˆÁFWáB¬◊6rÊ6ÜEˆñB¬◊6rÊ÷W76vUˆñB¬WFFRÊVffV7FófU˜W6W"ÊñB¬ñÁeˆñB¬W6Eˆ÷˜VÁ@¢íê¢&WGW&‡†¢ñbFFÁ7F'G7vóFÇÇ&7'óFÛ¶6ÜV6≥¢"ì†¢vóBÊÁ7vW"Çê¢ñÁeˆñB“FFÁ7∆óBÇ#¢"¬"ï≤”–¢ñÁb“vóBˆ7'óFıˆvWEˆñÁfˆñ6RÜñÁeˆñBê¢ñbÊ˜BñÁc†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	›R›ç≤}"‚
Ì}Mù-R›Ì-Ωí‚"ê¢&WGW&‡¢7B“ÜñÁbÊvWBÇ'7FGW2"í˜"""íÊ∆˜vW"Çê¢ñb7B”“'ñB#†¢W6Eˆ÷˜VÁB“f∆ˆBÜñÁbÊvWBÇ&÷˜VÁB"¬„íê¢ñbÜñÁbÊvWBÇ&76WB"í˜"""íÁWW"Çí”“%DÙ‚#†¢W6Eˆ÷˜VÁB£“DÙÂıU4Eı$DP¢˜v∆∆WE˜F˜F≈ˆFBáWFFRÊVffV7FófU˜W6W"ÊñB¬W6Eˆ÷˜VÁBê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÜb/	˘+2	Ì˝Ω-˝ÌΩ=}]›‚	›}çΩ]›„¢µˆ7&VFóG5ˆf◊Eˆg&ˆ’˜W6BáW6Eˆ÷˜VÁBó“‚"ê¢V∆ñb7B”“&7FófR#†¢vóBÊÁ7vW"Ç-	˝Ω-b]ù›R˝ÌM--]mM“"¬6Ü˜uˆ∆W'C’G'VRê¢V«6S†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÜb-
--=}-¢∑7G“"ê¢&WGW&‡†¢2	˝ÌM˝ç≠¢-ΩÌ˝ÌÌ ¢ñbFFÁ7F'G7vóFÇÇ&'Wì¢"ì†¢vóBÊÁ7vW"Çê¢Ú¬FñW"¬÷ˆÁFá2“FFÁ7∆óBÇ#¢"¬"ê¢÷ˆÁFá2“ñÁBÜ÷ˆÁFá2ê¢FW62“b-	˝ÌM˝ç≠∑FñW"ÁWW"Çó“›∂÷ˆÁFá7“Õ]‚ ¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢b'∂FW67’∆Ì	-Ω]ç-R˝ÌÌÌ˝Ω-≥¢"¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˘+2	≠-Ìí
‰∂76"¬6∆∆&6µˆFF÷b&'WññÁcß∑FñW'”ß∂÷ˆÁFá7“"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˙©í
≠]Mç-›Ì=‚Ω›"¬6∆∆&6µˆFF÷b&'Wóv∆∆WCß∑FñW'”ß∂÷ˆÁFá7“"ï“¿¢“ê¢ê¢&WGW&‡†¢2	˝ÌM˝ç≠}]]r
‰∂76Fó&V7Bíçr-Ì=‚'Wí›Õ]›‡¢ñbFFÁ7F'G7vóFÇÇ&'WóñˆÛ¢"ì†¢vóBÊÁ7vW"Ç-
Ì}M‚ΩΩ≠2›Ì˝Ω->(
b"ê¢G'ì†¢Ú¬“¬FñW"¬÷ˆÁFá2“FFÁ7∆óBÇ#¢"¬2ê¢÷ˆÁFá2“ñÁBÜ÷ˆÁFá2ê¢÷WFÜˆEˆ÷“≤'6'#¢'ñˆı˜6'"¬'6&W'í#¢'ñˆı˜6&W'í"¬'Gí#¢'ñˆı˜Gí"¬&÷ó'í#¢'ñˆıˆ÷ó'í'–¢÷WFÜˆEˆ∂Wí“÷WFÜˆEˆ÷ÊvWBÜ“ê¢ñbÊ˜B÷WFÜˆEˆ∂Wì†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	›]ç}-]-›Ωí˝ÌÌÌ˝Ω-≤‚"ê¢&WGW&‡¢ñbÊ˜B˜ñˆıˆFó&V7Eˆ6ˆÊfñwW&VBÇì†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ	Ω-ÚÌ˝Ω-
‰∂76˝Ì≠›R›-Ì]›¢›=m›≤îÙıı4ÑıÙîBıîÙıı4T5$UEÙ¥UíçΩÇ6V7&WBfñ∆Rñˆˆ∂76ÊVÁbîµÙîBıîµÙ¥Uí‚"ê¢&WGW&‡¢í“vóB˜ñˆıˆ7&VFUˆFó&V7E˜ñ÷VÁBáWFFRÊVffV7FófU˜W6W"ÊñB¬FñW"¬÷ˆÁFá2¬÷WFÜˆEˆ∂Wíê¢ñ÷VÁEˆñB“7G"áíÊvWBÇ&ñB"í˜"""ê¢6ˆÊb“íÊvWBÇ&6ˆÊfó&÷Fñˆ‚"í˜"∑–¢ï˜W&¬“6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂ˜W&¬"í˜"6ˆÊbÊvWBÇ&6ˆÊfó&÷FñˆÂˆFF"í˜"6ˆÊbÊvWBÇ&WáFW&Ê≈˜W&¬"í˜"" ¢ñbÊ˜Bï˜W&√†¢&ó6R'VÁFñ÷TW'&˜"Üb%ñˆÙ∂76FñBÊ˜B&WGW&‚6ˆÊfó&÷Fñˆ‚W&√¢∑ó“"ê¢∆&V¬“îÙıÙDï$T5EÙ‘UDÑÙE5∂÷WFÜˆEˆ∂Wï’≤&∆&V¬%–¢◊6r“vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢b-	˝ÌM˝ç≠∑FñW"ÁWW"Çó“›∂÷ˆÁFá7“Õ]Â∆Ì
˝ÌÌÌ˝Ω-≥¢∂∆&V«’∆Ì	Ì-≠Ìù-RΩΩ≠2MΩÚÌ˝Ω-≥¢"¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖµ¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb'∂∆&V«“(	BÌ˝Ω-ç-¬"¬W&√◊ï˜W&¬ï’“ê¢ê¢∑e˜6WBÜb'ñˆÛßVÊFñÊsß∑ñ÷VÁEˆñG“"¬ß6ˆ‚ÊGV◊2á≤'W6W%ˆñB#¢WFFRÊVffV7FófU˜W6W"ÊñB¬'FñW"#¢FñW"¬&÷ˆÁFá2#¢÷ˆÁFá2¬&÷WFÜˆB#¢÷WFÜˆEˆ∂Wó“¬VÁ7W&Uˆ66ñì‘f«6Ríê¢6ˆÁFWáBÊ∆ñ6Fñˆ‚Ê7&VFU˜F6≤Ö˜ˆ∆≈˜ñˆı˜7V'67&óFñˆÂ˜ñ÷VÁBÜ6ˆÁFWáB¬◊6rÊ6ÜEˆñB¬◊6rÊ÷W76vUˆñB¬WFFRÊVffV7FófU˜W6W"ÊñB¬ñ÷VÁEˆñB¬FñW"¬÷ˆÁFá2íê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç&'WóñˆÚñ÷VÁBfñ∆VC¢W2"¬Rê¢W'"“7G"ÜRï≥£s–¢W6W%ˆ◊6r“.)™˚àÚ	›R=MΩÌ¬Ì}M-¬Ì˝Ω-2
‰∂76‚	˝Ì˝Ì=ù-RM==Ìí˝ÌÌ‚ ¢ñbîÙıÙDT%TuıïÙU%$ı%3†¢W6W%ˆ◊6r≥“%∆Â∆Ì	Mç=›Ì-ç≠
‰∂76¢"≤W' ¢vóBÊ÷W76vRÁ&W«ï˜FWáBáW6W%ˆ◊6rê¢&WGW&‡†¢2	˝ÌM˝ç≠}]]r
‰∂76¢ñbFFÁ7F'G7vóFÇÇ&'WññÁc¢"ì†¢vóBÊÁ7vW"Çê¢Ú¬FñW"¬÷ˆÁFá2“FFÁ7∆óBÇ#¢"¬"ê¢÷ˆÁFá2“ñÁBÜ÷ˆÁFá2ê¢ñ∆ˆB¬÷˜VÁE˜'V"¬FóF∆R“˜∆Â˜ñ∆ˆEˆÊEˆ÷˜VÁBáFñW"¬÷ˆÁFá2ê¢FW62“b-	ÌMÌÕΩ]›çR˝ÌM˝ç≠Ç∑FñW"ÁWW"Çó“›∂÷ˆÁFá7“Õ]‚ ¢ˆ≤“vóB˜6VÊEˆñÁfˆñ6U˜'V"áFóF∆R¬FW62¬÷˜VÁE˜'V"¬ñ∆ˆB¬WFFRê¢ñbÊ˜Bˆ≥†¢vóBÊÁ7vW"Ç-	›R=MΩÌ¬-Ω--ç-¬}""¬6Ü˜uˆ∆W'C’G'VRê¢&WGW&‡†¢2	˝ÌM˝ç≠˝ç›ç]¬çr≠]Mç-›Ì=‚Ω› ¢ñbFFÁ7F'G7vóFÇÇ&'Wóv∆∆WC¢"ì†¢vóBÊÁ7vW"Çê¢Ú¬FñW"¬÷ˆÁFá2“FFÁ7∆óBÇ#¢"¬"ê¢÷ˆÁFá2“ñÁBÜ÷ˆÁFá2ê¢÷˜VÁE˜'V"“˜∆Â˜'V"áFñW"¬≥¢&÷ˆÁFÇ"¬3¢'V'FW""¬#¢'ñV"'’∂÷ˆÁFá5“ê¢ÊVVE˜W6B“ˆ7&VFóG5˜Fı˜W6BÜ÷˜VÁE˜'V"ê¢ñb˜v∆∆WE˜F˜F≈˜F∂RáWFFRÊVffV7FófU˜W6W"ÊñB¬ÊVVE˜W6Bì†¢VÁFñ¬“7FófFU˜7V'67&óFñˆÂ˜vóFÖ˜FñW"áWFFRÊVffV7FófU˜W6W"ÊñB¬FñW"¬÷ˆÁFá2ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢b.)»R	˝ÌM˝ç≠∑FñW"ÁWW"Çó“≠-ç-çÌ-›M‚∑VÁFñ¬Á7G&gFñ÷RÇrUí“V““VBró“Â∆‚ ¢b-
˝ç›‚Ω›¢∂ñÁBá&˜VÊBÖ˜W6E˜Fıˆ7&VFóG2ÜÊVVE˜W6Bííó“≠‚ ¢ê¢V«6S†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢-	›]MÌ--Ì}›‚]M-"›]Mç›Ì¬Ω›RÂ∆Ì	˝Ì˝ÌΩ›ç-RΩ›Ç˝Ì--Ìç-R‚"¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖµ¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.)ÈR	˝Ì˝ÌΩ›ç-¬Ω›"¬6∆∆&6µˆFF“'F˜W"ï’“ê¢ê¢&WGW&‡†¢2	-ΩÌM-çm≠ ¢ñbFFÁ7F'G7vóFÇÇ&VÊvñÊS¢"ì†¢vóBÊÁ7vW"Çê¢VÊvñÊR“FFÁ7∆óBÇ#¢"¬ï≥–¢ñbVÊvñÊR”“&«V÷"ÊB≈T‘ıDT’ÙDï4$ƒTC†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ«V÷-]Õ]››‚Ì-≠ΩÌ}]›Ç≠Ω-çrÕ]›‚‚	MΩÚfñFVÚç˝ÌΩÕ}=ù-R6˜&"]rΩÌM]í¬∂∆ñÊrçΩÇ'VÁví‚"ê¢&WGW&‡¢ñbVÊvñÊR”“&÷ñF¶˜W&ÊWí#†¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊuˆ÷ñF¶˜W&ÊWï˜&ˆ◊B%““G'VP¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢T‰tî‰UÙî‰dııDUÖE≤&÷ñF¶˜W&ÊWí%“∞¢b%∆Â∆Ì
-ÌçÕÌ-¬ÌM›Ìí=]›]mçÉ¢µ˜&WFñ≈ˆ7&VFóG2Ñ‘îD§ıU$‰UïıT‰ïEÙ4ı5EıU4Bó“≠‚	›˝ççç-R˝ÌÕ˝"Ω]M=Ìùç¬ÌÌù]›ç]¬çΩÇç˝ÌΩÕ}=ù-Rˆ÷¢ÕÌ˝ç›çS‚‚ ¢ê¢&WGW&‡¢ñbVÊvñÊRñ‚T‰tî‰UÙî‰dııDUÖC†¢&ñ6U˜7VffóÇ“" ¢ñbVÊvñÊR”“&ñ÷vW2#†¢&ñ6U˜7VffóÇ“b%∆Â∆Ì
m]›=]›]mçÉ¢µ˜&WFñ≈ˆ7&VFóG2Ñî‘uÙ4ı5EıU4Bó“≠‚ ¢V∆ñbVÊvñÊR”“''VÁví#†¢&ñ6U˜7VffóÇ“b%∆Â∆Ì
m]›vV‚”B„S¢µ˜fñFVı˜&ñ6Uˆ7&VFóG2Çw'VÁvír¬Ró“≠‚}R]¢‚ ¢V∆ñbVÊvñÊR”“'6˜&#†¢&ñ6U˜7VffóÇ“b%∆Â∆Ì
m]›6˜&#¢µ˜fñFVı˜&ñ6Uˆ7&VFóG2Çw6˜&r¬Ró“≠‚}R]¢‚ ¢V∆ñbVÊvñÊR”“&∂∆ñÊr#†¢&ñ6U˜7VffóÇ“b%∆Â∆Ì
m]›∂∆ñÊs¢µ˜fñFVı˜&ñ6Uˆ7&VFóG2Çv∂∆ñÊrr¬Ró“≠‚}R]¢‚ ¢V∆ñbVÊvñÊR”“'7VÊÚ#†¢&ñ6U˜7VffóÇ“b%∆Â∆Ì
m]›ÌM›Ìí=]›]mçÉ¢µ˜&WFñ≈ˆ7&VFóG2Ö5T‰ıÙ4ı5EıU4Bó“≠‚ ¢vóBÊ÷W76vRÁ&W«ï˜FWáBÑT‰tî‰UÙî‰dııDUÖE∂VÊvñÊU“≤&ñ6U˜7VffóÇ¬Fó6&∆U˜vV%˜vU˜&WfñWs’G'VRê¢&WGW&‡¢W6W&Ê÷R“áWFFRÊVffV7FófU˜W6W"ÁW6W&Ê÷R˜"""ê¢ñbVÊvñÊR”“''VÁví#†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢.)»R'VÁvíMÌ-=˝]“MΩÚ-çM]‚˝‚-]≠-2ÇMΩÚÌmç-Ω]›çÚMÌ-‚Â∆‚ ¢-	MΩÚÌmç-Ω]›çÚ}==}ç-RMÌ-Ì=Mç‚Ç›mÕç-R) Ç	Ìmç-ç-¬Ö'VÁvííçΩÇÌ-˝-Õ-RMÌ-‚˝ÌM˝çÕ„¢ ¢,*ΩÌmç-ÇMÌ-„¢Ω=≠Ú=ΩΩ≠¬M-çm]›çR≠Õ]≤¬R]≠=›B¬ì£l+≤Â∆Â∆‚ ¢-	MΩÚÌ}M›çÚ-çM]‚˝‚-]≠-2˝=ÌΩÌ2ç˝ÌΩÕ}=ù-R6˜&"]rΩÌM]í¬∂∆ñÊrçΩÇ'VÁví‚ ¢ê¢&WGW&‡¢ñbó5˜VÊ∆ñ÷óFVBáWFFRÊVffV7FófU˜W6W"ÊñB¬W6W&Ê÷Rì†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢b.)»R	M-çmÌ¢*∑∂VÊvñÊW‹+≤MÌ-=˝]“]rÌ=›ç}]›çíÂ∆‚ ¢b-	MΩÚFWáN(i'fñFVÚMÌ-=˝›≤6˜&"]rΩÌM]í¬∂∆ñÊrÇ'VÁví‚ ¢ê¢&WGW&‡†¢ñbVÊvñÊRñ‚Ç&wB"¬'7GE˜GG2"¬&÷ñF¶˜W&ÊWí"¬'6˜&"¬&∂∆ñÊr"ì†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢b.)»R	-Ω“*∑∂VÊvñÊW‹+≤‚	Ì-˝-Õ-R}˝Ì-]≠-Ì¬˝MÌ-‚‚ ¢b-	MΩÚ-çM]‚›˝ççç-S¢*ΩÌ}Mí-çM]‚(
bR]≠=›Bc£ú+≤(	BÚ˝]MΩÌm26˜&"]rΩÌM]í¬∂∆ñÊrÇ'VÁví‚ ¢ê¢&WGW&‡†¢W7Eˆ6˜7B“î‘uÙ4ı5EıU4BñbVÊvñÊR”“&ñ÷vW2"V«6RÉ„CñbVÊvñÊR”“&«V÷"V«6R÷ÇÉ„¬%TÂtïıT‰ïEÙ4ı5EıU4Bíê¢÷ˆVÊvñÊR“≤&ñ÷vW2#¢&ñ÷r"¬&«V÷#¢&«V÷"¬''VÁví#¢''VÁví'’∂VÊvñÊU–¢ˆ≤¬ˆffW"“ˆ6Â˜7VÊEˆ˜%ˆˆffW"áWFFRÊVffV7FófU˜W6W"ÊñB¬W6W&Ê÷R¬÷ˆVÊvñÊR¬W7Eˆ6˜7Bê†¢ñbˆ≥†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢.)»R	MÌ-=˝›‚‚"∞¢Ç-	}˝=-ç-S¢ˆñ÷r≠Ì""Ì}≠R"ñbVÊvñÊR”“&ñ÷vW2 ¢V«6R-	MΩÚ-çM]‚˝‚-]≠-2MÌ-=˝›≤6˜&"]rΩÌM]í¬∂∆ñÊrÇ'VÁví‚"ê¢ê¢&WGW&‡†¢ñbˆffW"”“$4µı5T%45$î$R#†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢-	MΩÚ›-Ì=‚M-çm≠›=m›≠-ç-›Ú˝ÌM˝ç≠çΩÇ]Mç›ΩíΩ›‚	Ì-≠Ìù-R˜∆Á2çΩÇ˝Ì˝ÌΩ›ç-R*ø	˙{‚	Ω›+≤‚"¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÄ¢µ¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.*Ÿ
-çM≤"¬vV%ˆ’vV$ñÊfÚáW&√’D$îdeıU$¬íï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.)ÈR	˝Ì˝ÌΩ›ç-¬Ω›"¬6∆∆&6µˆFF“'F˜W"ï’–¢í¿¢ê¢&WGW&‡†¢G'ì†¢ÊVVE˜W6B“f∆ˆBÜˆffW"Á7∆óBÇ#¢"¬ï≤”“ê¢WÜ6WBWÜ6WFñˆ„†¢ÊVVE˜W6B“W7Eˆ6˜7@¢÷˜VÁE˜'V"“ˆ6∆5ˆˆÊVˆfe˜&ñ6U˜'V"Ü÷ˆVÊvñÊR¬ÊVVE˜W6Bê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢b-	-ÇM›]-›ÌíΩçÕç"˝‚*∑∂VÊvñÊW‹+≤ç}]˝“‚
}Ì-Ú˝Ì≠=˝≠(òÇ∂÷˜VÁE˜'V'“(+“ ¢b-çΩÇ˝Ì˝ÌΩ›ç-RΩ›"*ø	˙{‚	Ω›+≤‚"¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÄ¢∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.*Ÿ
-çM≤"¬vV%ˆ’vV$ñÊfÚáW&√’D$îdeıU$¬íï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.)ÈR	˝Ì˝ÌΩ›ç-¬Ω›"¬6∆∆&6µˆFF“'F˜W"ï“¿¢–¢í¿¢ê¢&WGW&‡†¢2
]mçÕ≤Ú	M-çm≠Ä¢ñbFF”“&÷ˆFS¶VÊvñÊW2#†¢vóBÊÁ7vW"Çê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	M-çm≠É¢"¬&W«ïˆ÷&∑W÷VÊvñÊW5ˆ∂"Çíê¢&WGW&‡†¢ñbFFÁ7F'G7vóFÇÇ&÷ˆFSß6WC¢"ì†¢vóBÊÁ7vW"Çê¢÷ˆFR“FFÁ7∆óBÇ#¢"ï≤”–¢÷ˆFU˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬÷ˆFRê¢ñb÷ˆFR”“'7GVGí#†¢7GVGï˜7V%˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬&Wá∆ñ‚"ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-
]mç¬*Ω
=}+≤-≠ΩÌ}“‚	-Ω]ç-R˝ÌM]mç√¢"¬&W«ïˆ÷&∑W◊7GVGïˆ∂"Çíê¢V∆ñb÷ˆFR”“'Ü˜FÚ#†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-
]mç¬*Ω
MÌ-Ï+≤-≠ΩÌ}“‚	˝ççΩç-Rç}Ìm]›çR(	B˝Ì˝-˝-ÚΩ-ΩR≠›Ì˝≠Ç‚"¬&W«ïˆ÷&∑W◊Ü˜Fı˜Vñ6µˆ7FñˆÁ5ˆ∂"Çíê¢V∆ñb÷ˆFR”“&Fˆ72#†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-
]mç¬*Ω	MÌ≠=Õ]›-º+≤‚	˝ççΩç-RDbÙDÙ5ÇÙUT"ıEÖB(	BM]Ω‚≠Ì›˝]≠"‚"ê¢V∆ñb÷ˆFR”“'fˆñ6R#†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-
]mç¬*Ω	=ÌΩÌ+≤‚	Ì-˝-Õ-Rfˆñ6RˆVFñÚ‚	Ì}-=}≠Ì--]-Ì#¢˜fˆñ6Uˆˆ‚"ê¢V«6S†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÜb-
]mç¬*∑∂÷ˆFW‹+≤≠-ç-çÌ-“‚"ê¢&WGW&‡†¢ñbFFÁ7F'G7vóFÇÇ'7GVGìß6WC¢"ì†¢vóBÊÁ7vW"Çê¢7V"“FFÁ7∆óBÇ#¢"ï≤”–¢7GVGï˜7V%˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬7V"ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÜb-
=}(i"∑7V'“‚	›˝ççç-R-]Õ2˝}M›çR‚"¬&W«ïˆ÷&∑W◊7GVGïˆ∂"Çíê¢&WGW&‡†¢2Ü˜FÚVFóG2&WVó&R66ÜVBñ÷vP¢ñbFFÁ7F'G7vóFÇÇ'VFóC¢"ì†¢vóBÊÁ7vW"Çê¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢ñbÊ˜Bñ÷s†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-
›}Ω˝ççΩç-RMÌ-‚¬}-]¬-Ω]ç-RM]ù--çR‚"¬&W«ïˆ÷&∑W◊Ü˜Fı˜Vñ6µˆ7FñˆÁ5ˆ∂"Çíê¢&WGW&‡¢ñbFF”“'VFóC¶fF"#†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&fF%˜GG5˜fˆñ6R"ì†¢˜6WEˆfF%˜vóBÜ6ˆÁFWáBê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢b/	˘z2	˝Ì-]"-Ω“‚	=ÌΩÌ=mR-Ω”¢µˆfF%˜GG5˜fˆñ6Uˆ∆&V¬ÖˆfF%˜GG5˜fˆñ6UˆvWBÜ6ˆÁFWáBíó“‚
-]˝]¬˝ççΩç-R-]≠"¬fˆñ6RçΩÇ=MçÌMù≤’2ıtbÙ”DÙ2MΩÚ]}Ç--‚ ¢ê¢V«6S†¢˜6WEˆfF%˜fˆñ6Uˆ6Üˆñ6U˜vóBÜ6ˆÁFWáBê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÖˆfF%˜fˆñ6Uˆ6Üˆñ6U˜FWáBÇí¬&W«ïˆ÷&∑W’ˆfF%˜fˆñ6Uˆ6Üˆñ6Uˆ∂"Ç&7B"íê¢&WGW&‡¢ñbFF”“'VFóCßÜ˜Fˆ6∆ó#†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢˜6WE˜Ü˜Fıˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ/	¯ÎR
MÌ-‚-Ω›‚‚	Ì˝ççç-R-çΩ¬-çM]Ì≠Ωç˝¢Õ=}Ω≠¬M-çm]›çR¬›-Ì]›çR¬MΩç-]ΩÕ›Ì-¬ÇMÌÕ"ì£bÛc£í‚"ê¢&WGW&‡¢ñbFF”“'VFóCßfˆ6∆6∆ó#†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áÊg&ˆ’˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬'fˆ6∆6∆ó"ê¢˜6WE˜fˆ6≈ˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢/	¯ÍB	˝Ì-]"-Ω“MΩÚ≠Ωç˝-Ì≠ΩÌ¬‚
-]˝]¬Ì˝ççç-R˝]›‚˝≠ΩçÛ¢-çΩ¬¬˝}Ω¢¬›-Ì]›çR¬˝ç˝]"¬MΩç-]ΩÕ›Ì-¬Â∆Â∆‚ ¢-	-m›„¢]mç¬}ç-“›ÌM›Ì=‚}]ΩÌ-]≠"≠MR‚ ¢ê¢&WGW&‡¢ñbFF”“'VFóC¶ó6V∆fñR#†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢˜6WEˆï˜6V∆fñU˜vóBÜ6ˆÁFWáBê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ/	˙K2
MÌ-‚-Ω›‚‚	›˝ççç-Rm]›3¢≠≠Ìí}›Õ]›ç-Ì-Õ‚˝˝]Ì›m]¬¬=MR¬-çΩ¬¬MÌÕ"‚	›˝çÕ]¢*Ω]ΩMÇç}-]-›Ω¬≠-Ì¬›≠›ÌíMÌÌm≠R¬ïÜˆÊR6V∆fñR¬C£\+≤‚"ê¢&WGW&‡¢ñbFF”“'VFóCß&WF˜V6Ç#†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢˜6WE˜&WF˜V6Ö˜vóE˜FWáBÜ6ˆÁFWáBê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢/	˙{“
}-‚=-¬Ç=MR›]ÌMç-Ú›Ω]Õ]›#ı∆Â∆‚ ¢-	›˝çÕ]¢*Ω-ÌM˝›Ìí}›¢˝-›ç}<+≤¬*Ω›M˝ç¬˝‚m]›-<+≤¬*ΩΩÌ=Ì-çÚ"Ω]-Ì¬-]]›]¬==Ω<+≤Â∆‚ ¢-	Ì-˝-Ω˝Ú≠ÌÕ›M2¬-≤˝ÌM--]mM]-R¬}-‚›-‚-çRç}Ìm]›çRçΩÇ2-]-¬˝-‚]=‚]M≠-çÌ--¬‚ ¢ê¢&WGW&‡¢ñbFF”“'VFóC¶&6≤#†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç'Ü˜Fıˆf∆˜r"¬ÊˆÊRê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-
MÌ-‚›Õ-]≠Û¢"¬&W«ïˆ÷&∑W◊Ü˜Fı˜Vñ6µˆ7FñˆÁ5ˆ∂"Çíì≤&WGW&‡¢ñbFF”“'VFóCß&V÷˜fV&r#†¢vóB˜VFóE˜&V÷˜fV&ráWFFR¬6ˆÁFWáB¬ñ÷rì≤&WGW&‡¢ñbFF”“'VFóCß&W∆6V&r#†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	-Ω]ç-R›Ì-ΩíMÌ“‚
-]˝]¬}Õ]›Ì-]"""›-˝¢í≠≠=-›‚-Ω]}‚}]ΩÌ-]≠˝Ì≠]≠"¬"í˝ÌM--Ω˝‚›Ì-ΩíMÌ“]r˝]]çÌ-≠ÇÕÌ=‚}]ΩÌ-]≠‚	ÕÌm›‚-Ω-¬˝]]"çΩÇ›˝ç-¬-Ìí-ç›"‚"¬&W«ïˆ÷&∑W÷&6∂w&˜VÊE˜&W6WG5ˆ∂"Çíì≤&WGW&‡¢ñbFF”“'VFóC¶f6W7v#†¢vóB˜7F'Eˆf6W7vˆf∆˜ráWFFR¬6ˆÁFWáB¬ñ÷rì≤&WGW&‡¢ñbFFÁ7F'G7vóFÇÇ'VFóC¶&s¢"ì†¢∂ñÊB“FFÁ7∆óBÇ#¢"ï≤”–¢ñb∂ñÊB”“&7W7Fˆ“#†¢˜6WE˜&W∆6V&u˜vóE˜FWáBÜ6ˆÁFWáBê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	›˝ççç-R¬≠≠ÌíMÌ“˝Ì--ç-¬‚
ÚÌ]›‚}]ΩÌ-]≠çrç]ÌM›Ì=‚MÌ-‚¬Ì-M]ΩÕ›‚˝ÌM]2˝=]›]ç=‚›Ì-ΩíMÌ“Ç}-]¬≠≠=-›‚Ì]2ç-Ì2‚	˝çÕ]≥¢*ΩMÌÌ=ÌíÌMç˝›ÌÕ›ΩÕÇÌ≠›Õå+≤¬*Ω˝Ω˝b
Õ=Ç›}≠-\+≤¬*ΩΩÕ˝çù≠çR=Ì≤Ω]-ÌÃ+≤¬*Ω-]›]Ì≠›Ì}ÕÏ+≤‚"ê¢&WGW&‡¢vóB˜VFóE˜&W∆6V&ráWFFR¬6ˆÁFWáB¬ñ÷r¬∂ñÊC÷∂ñÊBì≤&WGW&‡¢ñbFF”“'VFóC¶˜WGñÁB#†¢vóB˜VFóEˆ˜WGñÁBáWFFR¬6ˆÁFWáB¬ñ÷rì≤&WGW&‡¢ñbFF”“'VFóCß7F˜'í#†¢vóB˜VFóE˜7F˜'ñ&ˆ&BáWFFR¬6ˆÁFWáB¬ñ÷rì≤&WGW&‡¢ñbFF”“'VFóCß&WfófUˆ÷VÁR#†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç'&Wfóf≈ˆ7W7Fˆ’˜&ˆ◊B"¬ÊˆÊRê¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç'&Wfóf≈ˆñFVÁFóGïˆ÷ˆFR"¬ÊˆÊRê¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜&Wfóf≈ˆ7W7Fˆ’˜&ˆ◊B"¬ÊˆÊRê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	-Ω]ç-R¬≠¢Ìmç-ç-¬MÌ-„¢"¬&W«ïˆ÷&∑W◊Ü˜Fı˜&Wfóf≈ˆ7FñˆÁ5ˆ∂"Çíê¢&WGW&‡¢ñbFF”“'VFóCß&WfófUˆWFÚ#†¢6ˆÁFWáBÁW6W%ˆFF≤'&Wfóf≈ˆ7W7Fˆ’˜&ˆ◊B%““" ¢6ˆÁFWáBÁW6W%ˆFF≤'&Wfóf≈ˆñFVÁFóGïˆ÷ˆFR%““f«6P¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜&Wfóf≈ˆ7W7Fˆ’˜&ˆ◊B"¬ÊˆÊRê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ.) Ç	]-]--]››ÌRÌmç-Ω]›çR-Ω›‚‚
-]˝]¬-Ω]ç-RM-çmÌ£¢"¬&W«ïˆ÷&∑W◊Ü˜Fı˜&Wfóf≈ˆVÊvñÊW5ˆ∂"Çíê¢&WGW&‡¢ñbFF”“'VFóCß&WfófUˆñFVÁFóGí#†¢6ˆÁFWáBÁW6W%ˆFF≤'&Wfóf≈ˆñFVÁFóGïˆ÷ˆFR%““G'VP¢6ˆÁFWáBÁW6W%ˆFF≤'&Wfóf≈ˆ7W7Fˆ’˜&ˆ◊B%““Ä¢%&W6W'fRWfW'íW'6ˆ‚w2WÜ7BñFVÁFóGí¬f6ñ¬vVˆ÷WG'í¬vR¬Üó'7Gñ∆R¬6∂ñ‚FWáGW&RÊB&V6ˆvÊó¶&∆Rf6ñ¬fVGW&W2g&ˆ“FÜR6˜W&6RÜ˜FÚ‚ ¢$f6W2&V÷ñ‚7F&∆RÊB&V6ˆvÊó¶&∆RFá&˜VvÜ˜WB‚∂VWÜVB&˜FFñˆÁ26÷∆¬ÊB6ˆÁG&ˆ∆∆VC≤ÊGW&¬&∆ñÊ∂ñÊr¬7V'F∆R6÷ñ∆W2ÊBWñR÷˜fV÷VÁB&R∆∆˜vVB‚ ¢%FÜR&ˆFñW2÷í÷˜fR÷˜&Rg&VV«íÊBÊGW&∆«ì¢V˜∆R÷íGW&‚FÜVó"&ˆFñW2¬7FÊBW¬v∆≤vÜñ∆R∆ˆˆ∂ñÊrF˜v&BFÜR6÷W&¬áVrV6Ç˜FÜW"¬6∆FÜVó"ÜÊG2¬ ¢&˜"vófRV6Ç˜FÜW"ÜñvÇ÷fófRvÜV‚6ˆ◊˜6óFñˆ‚W&÷óG2‚÷ñÁFñ‚6˜'&V7BÊFˆ◊í¬ÜÊG2¬6∆˜FÜñÊrÊBW'6ˆ‚6˜VÁB‚ ¢$FÚÊ˜B&W∆6R¬÷˜'Ç¬&VWFñgí¬&VßWfVÊFR˜"&VFW6ñv‚f6W2‚fˆñB&ˆfñ∆RfñWw2¬WáG&V÷RÜVBGW&Á2¬f6Rˆ66«W6ñˆ‚ÊBñFVÁFóGíG&ñgB‚ ¢$ÊGW&¬&V∆ó7Fñ2÷˜Fñˆ‚¬Fˆ7V÷VÁF'íf÷ñ«í◊fñFVÚfVV∆ñÊr¬6÷ˆ˜FÇ6÷W&÷˜Fñˆ‚‚ ¢ê¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜&Wfóf≈ˆ7W7Fˆ’˜&ˆ◊B"¬ÊˆÊRê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢/	˘∫
]mç¬Ì]›]›çÚΩçb-Ω“‚	ΩçmÇ›]ÌΩÕççRM-çm]›çÚ=ÌΩÌ-≤=M="Õ≠çÕΩÕ›‚-çΩÕ›ΩÕÇ¬ ¢-›‚-]Ω¬}]ç]›≤]-]--]››ΩRM]ù--çÚ(	B˝Ì-ÌÌ"¬---›çR¬ç=Ç¬Ì≠˝-çÚ¬]ΩÌ˝≠ÇÇ-}çÕÌM]ù--çR‚
-]˝]¬-Ω]ç-RM-çmÌ£¢"¿¢&W«ïˆ÷&∑W◊Ü˜Fı˜&Wfóf≈ˆVÊvñÊW5ˆ∂"Çí¿¢ê¢&WGW&‡¢ñbFF”“'VFóCß&WfófUˆ7W7Fˆ“#†¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊu˜&Wfóf≈ˆ7W7Fˆ’˜&ˆ◊B%““G'VP¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢.)»ﬁ˚àÚ	Ì˝ççç-R¬}-‚MÌΩm›‚˝Ìç}Ìù-Ç"≠MR‚	›˝çÕ]¢*ΩΩ]-Ωí}]ΩÌ-]¢--"Ç˝Ì-Ì}ç-]-Ú¢≠Õ]R¬˝-Ωí=ΩΩ]-Ú¬Ì-ΩÕ›ΩRΩ]=≠M-ç=Ì-Ú]-]--]››Ï+≤‚	˝ÌΩR›-Ì=‚Ú˝]MΩÌm2-Ω-¬M-çmÌ¢‚ ¢ê¢&WGW&‡¢ñbFFñ‚Ç'VFóCß&WfófR"¬'VFóCß&WfófU˜'VÁví"¬'VFóCß&WfófUˆ«V÷"¬'VFóCß&WfófU˜6˜&"¬'VFóCß&WfófUˆ∂∆ñÊr"ì†¢VÊvñÊR“∞¢'VFóCß&WfófR#¢''VÁví"¿¢'VFóCß&WfófU˜'VÁví#¢''VÁví"¿¢'VFóCß&WfófUˆ«V÷#¢&«V÷"¿¢'VFóCß&WfófU˜6˜&#¢'6˜&"¿¢'VFóCß&WfófUˆ∂∆ñÊr#¢&∂∆ñÊr"¿¢“ÊvWBÜFF¬''VÁví"ê¢ñbVÊvñÊR”“&«V÷"ÊB≈T‘ıDT’ÙDï4$ƒTC†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ«V÷-]Õ]››‚Ì-≠ΩÌ}]›Ç≠Ω-çrÕ]›‚‚	ç˝ÌΩÕ}=ù-R'VÁví¬∂∆ñÊrçΩÇ6˜&"]rΩÌM]í‚"ê¢&WGW&‡¢2	-çMçÕΩí4≤}2˝ÌΩR≠Ωç≠‚
-˝mΩÚ=]›]mçÚçM"˝ÌΩRΩ-Ì=‚Ì--]-FV∆Vw&“‡¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢6Ü˜vÂˆVÊvñÊR“%'VÁví--‚›]}]-Ì¬∂∆ñÊr"ñbVÊvñÊR”“''VÁví"V«6RVÊvñÊRÁWW"Çê¢7VffóÇ“"	]ΩÇÌ›Ì-›ÌíM-çmÌ¢›]MÌ-=˝]“¬˝]]≠ΩÌ}=¬›]}]-›Ωí‚"ñbVÊvñÊR”“''VÁví"V«6R"	M-çmÌ¢›R˝]]≠ΩÌ}‚‚ ¢vóBÊ÷W76vRÁ&W«ï˜FWáBÜb/	˘˙"	}˝=≠‚Ìmç-Ω]›çS¢∑6Ü˜vÂˆVÊvñÊW“Á∑7Vffóá“"ê¢G'ì†¢&Wfóf≈˜&ˆ◊B“Ü6ˆÁFWáBÁW6W%ˆFFÁ˜Ç'&Wfóf≈ˆ7W7Fˆ’˜&ˆ◊B"¬""í˜"""íÁ7G&óÇê¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç'&Wfóf≈ˆñFVÁFóGïˆ÷ˆFR"¬ÊˆÊRê¢vóB˜7F'E˜Ü˜Fı˜&Wfóf¬áWFFR¬6ˆÁFWáB¬VÊvñÊS÷VÊvñÊR¬ñ÷uˆ'óFW3÷ñ÷r¬&ˆ◊C◊&Wfóf≈˜&ˆ◊Bê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç'VFóB&WfófRfñ∆VC¢W2"¬Rê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ	›R=MΩÌ¬}˝=-ç-¬Ì›Ì-›ÌíM-çmÌ¢‚	Ì-≠Ìù-RÕ]›‚Ç˝Ì˝Ì=ù-R∂∆ñÊrçΩÇ˝Ì--Ìç-R˝Ì}mR‚"ê¢&WGW&‡†¢ñbFF”“'VFóC¶«V÷ñ÷r#†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬&«V÷ñ÷u˜vóE˜FWáB"ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	›˝ççç-RÌM›‚˝]MΩÌm]›çR(	B}-‚=]›]çÌ--¬‚
ÚM]Ω‚≠-ç›≠2‚"ê¢&WGW&‡¢ñbFF”“'VFóCßfó6ñˆ‚#†¢#cB“&6ScBÊ#cFVÊ6ˆFRÜñ÷ríÊFV6ˆFRÇ&66ñí"ê¢÷ñ÷R“6Êñfeˆñ÷vUˆ÷ñ÷RÜñ÷rê¢Á2“vóB6µˆ˜VÊï˜fó6ñˆ‚Ç-	Ì˝ççÇMÌ-‚Ç-]≠"››¬≠-≠‚‚"¬#cB¬÷ñ÷Rê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜÁ2˜"-	=Ì-Ì-‚‚"ê¢&WGW&‡†¢ñbFFÁ7F'G7vóFÇÇ&f6W7vßF&vWC¢"ì†¢vóBÊÁ7vW"Çê¢G'ì†¢ñGÇ“ñÁBÜFFÁ7∆óBÇ#¢"ï≤”“ê¢WÜ6WBWÜ6WFñˆ„†¢ñGÇ“ ¢W6W%ˆñB“WFFRÊVffV7FófU˜W6W"Êñ@¢ˆf6W7v˜F&vWEˆf6UˆñÊFWÖˆ66ÜU∑W6W%ˆñE““÷ÇÉ¬ñGÇê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÜb.)»R	-Ω›‚m]Ω]-ÌRΩçm‚(Ig∂÷ÇÉ¬ñGÇí≤“‚
-]˝]¬˝ççΩç-RMÌ-‚Ωçm¬≠Ì-ÌÌR›=m›‚---ç-¬‚"ê¢6ˆÁFWáBÁW6W%ˆFF≤&f6W7vˆf∆˜r%““&vóE˜6˜W&6R ¢&WGW&‡†¢ñbFFÁ7F'G7vóFÇÇ&f6W7vß6˜W&6S¢"ì†¢vóBÊÁ7vW"Çê¢G'ì†¢ñGÇ“ñÁBÜFFÁ7∆óBÇ#¢"ï≤”“ê¢WÜ6WBWÜ6WFñˆ„†¢ñGÇ“ ¢W6W%ˆñB“WFFRÊVffV7FófU˜W6W"Êñ@¢ˆf6W7v˜6˜W&6Uˆf6UˆñÊFWÖˆ66ÜU∑W6W%ˆñE““÷ÇÉ¬ñGÇê¢6ˆÁFWáBÁW6W%ˆFF≤&f6W7vˆf∆˜r%““'&VGí ¢vóBÊ÷W76vRÁ&W«ï˜FWáBÜb.)»R	-Ω›‚Ωçm‚›ç-Ì}›ç¢(Ig∂÷ÇÉ¬ñGÇí≤“‚	-Ω]ç-R≠}]--‚}Õ]›≥¢"¬&W«ïˆ÷&∑W÷f6U˜7v˜V∆óGïˆ∂"Çíê¢&WGW&‡†¢ñbFFÁ7F'G7vóFÇÇ&f6W7vß'V„¢"ì†¢vóBÊÁ7vW"Çê¢V∆óGí“FFÁ7∆óBÇ#¢"ï≤”–¢vóBˆf6W7v˜&ˆ6W72áWFFR¬6ˆÁFWáB¬V∆óGì◊V∆óGíê¢&WGW&‡†¢ñbFFÁ7F'G7vóFÇÇ&6Üˆ˜6Vñ÷s¢"ì†¢vóBÊÁ7vW"Çê¢G'ì†¢Ú¬VÊvñÊR¬ñB“FFÁ7∆óBÇ#¢"¬"ê¢WÜ6WBWÜ6WFñˆ„†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	›R=MΩÌ¬˝Ì}›-¬-ΩÌM-çm≠‚"ê¢&WGW&‡¢÷WF“˜VÊFñÊuˆ7FñˆÁ2Á˜ÜñB¬ÊˆÊRê¢ñbÊ˜B÷WF˜"÷WFÊvWBÇ&∂ñÊB"í“&ñ÷vUˆvVÊW&FR#†¢vóBÊÁ7vW"Ç-	}M}=-]Ω"¬6Ü˜uˆ∆W'C’G'VRê¢&WGW&‡¢&ˆ◊B“Ü÷WFÊvWBÇ'&ˆ◊B"í˜"""íÁ7G&óÇê¢ñbÊ˜B&ˆ◊C†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	˝ÌÕ˝"›R›ùM]“‚	}˝=-ç-R}˝Ì]ùr‚"ê¢&WGW&‡¢vóB˜'VÂ˜6V∆V7FVEˆñ÷vUˆvVÊW&Fñˆ‚áWFFR¬6ˆÁFWáB¬&ˆ◊B¬VÊvñÊRê¢&WGW&‡†¢2	˝ÌM--]mM]›çR-ΩÌM-çm≠MΩÚ-çM]‡¢ñbFFÁ7F'G7vóFÇÇ&6Üˆ˜6S¢"ì†¢vóBÊÁ7vW"Çê¢Ú¬VÊvñÊR¬ñB“FFÁ7∆óBÇ#¢"¬"ê¢ñbVÊvñÊR”“&«V÷"ÊB≈T‘ıDT’ÙDï4$ƒTC†¢˜VÊFñÊuˆ7FñˆÁ2Á˜ÜñB¬ÊˆÊRê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ«V÷-]Õ]››‚Ì-≠ΩÌ}]›‚	-Ω]ç-R6˜&"]rΩÌM]í¬∂∆ñÊrçΩÇ'VÁví‚"ê¢&WGW&‡¢÷WF“˜VÊFñÊuˆ7FñˆÁ2Á˜ÜñB¬ÊˆÊRê¢ñbÊ˜B÷WF†¢vóBÊÁ7vW"Ç-	}M}=-]Ω"¬6Ü˜uˆ∆W'C’G'VRì≤&WGW&‡¢&ˆ◊B¬GW&Fñˆ‚¬7V7B“÷WF≤'&ˆ◊B%“¬÷WF≤&GW&Fñˆ‚%“¬÷WF≤&7V7B%–¢VÊvñÊR“ÜVÊvñÊR˜"""íÊ∆˜vW"Çê¢ñbVÊvñÊRÊ˜Bñ‚Ç'6˜&"¬&∂∆ñÊr"¬''VÁví"ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	MÌ-=˝›≤6˜&"]rΩÌM]í¬∂∆ñÊrÇ'VÁví‚"ì≤&WGW&‡¢ñbVÊvñÊR”“''VÁví"ÊBÊ˜BDUÖEıdîDTıÙƒƒıuı%TÂtì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ'VÁví-]Õ]››‚Ì-≠ΩÌ}“›-Ìù≠ÌíDUÖEıdîDTıÙƒƒıuı%TÂtí‚"ì≤&WGW&‡¢ñbVÊvñÊR”“'6˜&"ÊB˜&ˆ◊Eˆ∆ñ∂V«ïˆÜ5˜V˜∆Rá&ˆ◊Bì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ6˜&"ç˝ÌΩÕ}=]-Ú-ÌΩÕ≠‚]rΩÌM]í‚	MΩÚ›-Ì=‚}˝Ì-Ω]ç-R∂∆ñÊrçΩÇ'VÁví‚"ì≤&WGW&‡¢&˜fñFW%ˆ6˜7B“˜fñFVı˜&˜fñFW%ˆ6˜7E˜W6BÜVÊvñÊR¬GW&Fñˆ‚ê†¢7ñÊ2FVb˜7F'E˜&V≈˜&VÊFW"Çì†¢ñbVÊvñÊR”“''VÁví#†¢&WGW&‚vóB˜'VÂ˜'VÁvï˜fñFVÚáWFFR¬6ˆÁFWáB¬&ˆ◊B¬GW&Fñˆ‚¬7V7Bê¢&WGW&‚vóB˜'VÂˆ6ˆ÷WE˜FWáE˜fñFVÚáWFFR¬6ˆÁFWáB¬VÊvñÊR¬&ˆ◊B¬GW&Fñˆ‚¬7V7Bê†¢vóB˜G'ï˜ï˜FÜVÂˆFÚÄ¢WFFR¬6ˆÁFWáB¬WFFRÊVffV7FófU˜W6W"ÊñB¿¢''VÁví"¬&˜fñFW%ˆ6˜7B¬˜7F'E˜&V≈˜&VÊFW"¿¢&V÷V÷&W%ˆ∂ñÊC÷b'fñFVı˜∂VÊvñÊW“"¿¢&V÷V÷&W%˜ñ∆ˆC◊≤'&ˆ◊B#¢&ˆ◊B¬&GW&Fñˆ‚#¢GW&Fñˆ‚¬&7V7B#¢7V7B¬&VÊvñÊR#¢VÊvñÊW“¿¢ê¢&WGW&‡†¢vóBÊÁ7vW"Ç-	›]ç}-]-›Ú≠ÌÕ›M"¬6Ü˜uˆ∆W'C’G'VRê†¢WÜ6WBWÜ6WFñˆ‚2S†¢◊6r“7G"ÜRê¢ñb'VW'íó2FˆÚˆ∆B"ñ‚◊6rÊ∆˜vW"Çí˜"'VW'íñBó2ñÁf∆ñB"ñ‚◊6rÊ∆˜vW"Çì†¢∆ˆrÁv&ÊñÊrÇ'7F∆R6∆∆&6≤ñvÊ˜&VC¢W2"¬◊6rê¢&WGW&‡¢∆ˆrÊWÜ6WFñˆ‚Ç&ˆÂˆ6"W'&˜#¢W2"¬Rê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ	≠›Ì˝≠=-]Ω‚	Ì-≠Ìù-RÕ]›‚}›Ì-‚Ç˝Ì--Ìç-RM]ù--çR‚"ê¢fñÊ∆«ì†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóBÊÁ7vW"Çê††¢2)H)H)H)H)H)H)H)H)H5EB)H)H)H)H)H)H)H)H)H ¶FVbˆ÷ñ÷Uˆg&ˆ’ˆfñ∆VÊ÷RÜf„¢7G"í”‚7G#†¢fÊ¬“Üf‚˜"""íÊ∆˜vW"Çê¢ñbfÊ¬ÊVÊG7vóFÇÇÇ"Êˆvr"¬"Êˆv"íì¢&WGW&‚&VFñÚˆˆvr ¢ñbfÊ¬ÊVÊG7vóFÇÇ"Ê◊2"ì¢&WGW&‚&VFñÚˆ◊Vr ¢ñbfÊ¬ÊVÊG7vóFÇÇÇ"Ê”F"¬"Ê◊B"íì¢&WGW&‚&VFñÚˆ◊B ¢ñbfÊ¬ÊVÊG7vóFÇÇ"Ávb"ì¢&WGW&‚&VFñÚ˜vb ¢ñbfÊ¬ÊVÊG7vóFÇÇ"ÁvV&“"ì¢&WGW&‚&VFñÚ˜vV&“ ¢&WGW&‚&∆ñ6Fñˆ‚ˆˆ7FWB◊7G&V“ †¶7ñÊ2FVbG&Á67&ñ&UˆVFñÚÜ'Vc¢'óFW4îÚ¬fñ∆VÊ÷UˆÜñÁC¢7G"“&VFñÚÊˆvr"í”‚7G#†¢FF“'VbÊvWGf«VRÇê¢ñbDTUu$’ÙïÙ¥Uì†¢G'ì†¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC”c„í26∆ñVÁC†¢&◊2“≤&÷ˆFV¬#¢&Ê˜f”""¬&∆ÊwVvR#¢''R"¬'6÷'Eˆf˜&÷B#¢'G'VR"¬'VÊ7GVFR#¢'G'VR'–¢ÜVFW'2“≤$WFÜ˜&ó¶Fñˆ‚#¢b%Fˆ∂V‚¥DTUu$’ÙïÙ¥Uó“"¬$6ˆÁFVÁB’GóR#¢ˆ÷ñ÷Uˆg&ˆ’ˆfñ∆VÊ÷RÜfñ∆VÊ÷UˆÜñÁBó–¢"“vóB6∆ñVÁBÁ˜7BÇ&áGG3¢ÚˆíÊFVWw&“Ê6ˆ“˜cˆ∆ó7FV‚"¬&◊3◊&◊2¬ÜVFW'3÷ÜVFW'2¬6ˆÁFVÁC÷FFê¢"Á&ó6Uˆf˜%˜7FGW2Çê¢Fr“"Êß6ˆ‚Çê¢FWáB“ÜFrÊvWBÇ'&W7V«G2"¬∑“íÊvWBÇ&6ÜÊÊV«2"¬∑∑’“ï≥“ÊvWBÇ&«FW&ÊFófW2"¬∑∑’“ï≥“ÊvWBÇ'G&Á67&óB"¬""ííÁ7G&óÇê¢ñbFWáC¢&WGW&‚FWá@¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç$FVWw&“5EBW'&˜#¢W2"¬Rê¢ñbˆï˜7GC†¢G'ì†¢'Vc"“'óFW4îÚÜFFì≤'Vc"Á6VV≤Éì≤6WFGG"Ü'Vc"¬&Ê÷R"¬fñ∆VÊ÷UˆÜñÁBê¢G"“ˆï˜7GBÊVFñÚÁG&Á67&óFñˆÁ2Ê7&VFRÜ÷ˆFV√’E$Â45$î$UÙ‘ÙDT¬¬fñ∆S÷'Vc"ê¢&WGW&‚áG"ÁFWáB˜"""íÁ7G&óÇê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç%vÜó7W"5EBW'&˜#¢W2"¬Rê¢&WGW&‚" ††¢2)H)H)H)H)H)H)H)H)H	Mç=›Ì-ç≠M-çm≠Ì")H)H)H)H)H)H)H)H)H ¶7ñÊ2FVb6÷EˆFñu˜7GBáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢∆ñÊW2“µ–¢∆ñÊW2ÊVÊBÇ/	˘H‚5EBMç=›Ì-ç≠¢"ê¢∆ñÊW2ÊVÊBÜb.(
"˜V‰ívÜó7W#¢≤~)»R≠Ωç]›"≠-ç-]“rñbˆï˜7GBV«6R~)ÿ¬›]MÌ-=˝]“w“"ê¢∆ñÊW2ÊVÊBÜb.(
"	ÕÌM]Ω¬vÜó7W#¢µE$Â45$î$UÙ‘ÙDT«“"ê¢∆ñÊW2ÊVÊBÇ.(
"	˝ÌMM]m≠MÌÕ-Ì#¢ˆvrˆˆv¬◊2¬”Fˆ◊B¬vb¬vV&“"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ%∆‚"Ê¶ˆñ‚Ü∆ñÊW2íê†¶7ñÊ2FVb6÷EˆFñuˆñ÷vW2áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢∂WïˆVÁb“˜2ÊVÁfó&ˆ‚ÊvWBÇ$ıT‰ïÙî‘tUÙ¥Uí"¬""íÁ7G&óÇê¢∂Wï˜W6VB“∂WïˆVÁb˜"ıT‰ïÙïÙ¥Uê¢&6R“î‘tU5Ù$4UıU$¿¢∆ñÊW2“∞¢/	˙z¢ñ÷vW2Ñ˜V‰ííMç=›Ì-ç≠¢"¿¢b.(
"ıT‰ïÙî‘tUÙ¥Uì¢≤~)»R›ùM]“rñb∂Wï˜W6VBV«6R~)ÿ¬›]"w“"¿¢b.(
"$4UıU$√¢∂&6W“"¿¢b.(
"‘ÙDT√¢¥î‘tU5Ù‘ÙDT«“"¿¢–¢ñb&˜VÁ&˜WFW""ñ‚Ü&6R˜"""íÊ∆˜vW"Çì†¢∆ñÊW2ÊVÊBÇ.)™˚àÚ$4UıU$¬=≠}Ω-]"›˜VÂ&˜WFW"(	B-¬›]"wB÷ñ÷vR”‚"ê¢∆ñÊW2ÊVÊBÇ"
=≠mÇáGG3¢ÚˆíÊ˜VÊíÊ6ˆ“˜cççΩÇ-Ìí˝Ì≠Çí"ıT‰ïÙî‘tUÙ$4UıU$¬‚"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ%∆‚"Ê¶ˆñ‚Ü∆ñÊW2íê†¶7ñÊ2FVb6÷EˆFñu˜fñFVÚáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢∆ñÊW2“∞¢b/	¯Í¬	-çM]‚›M-çm≠ÇÚµD4ÖıdU%4îÙÁ”¢"¿¢b.(
"«V÷∂Wì¢≤	˘™≤≠Ω-‚-]Õ]››‚rñb≈T‘ıDT’ÙDï4$ƒTBV«6RÇ~)»Rrñb&ˆˆ¬Ñ≈T‘ÙïÙ¥UííV«6R~)ÿ¬ró“&6S◊¥≈T‘Ù$4UıU$«“"¿¢b"7&VFS◊¥≈T‘Ù5$TDUıDá“7FGW3◊¥≈T‘ı5DEU5ıDá“÷ˆFV√◊¥≈T‘Ù‘ÙDT«“"¿¢b.(
"'VÁvíˆffñ6ñ√¢VÊ&∆VC◊≤~)»Rrñb%TÂtïÙDï$T5EÙT‰$ƒTBV«6R~)ÿ¬w“∂Wì◊≤~)»Rrñb&ˆˆ¬Ö%TÂtïÙïÙ¥UííV«6R~)ÿ¬w“6˜W&6S◊µ%TÂtïÙ¥Uïı4ıU$4W“fñÊvW'&ñÁC◊∑'VÁvï˜6fUˆ∂WïˆfñÊvW'&ñÁBÖ%TÂtïÙïÙ¥Uíó“"¿¢b"&6S◊µ%TÂtïÙ$4UıU$«“fW'6ñˆ„◊µ%TÂtïÙïıdU%4îÙÁ“FWáC◊µ%TÂtïıDUÖEÙ5$TDUıDá“ì'c◊µ%TÂtïÙì%eıDá“"¿¢b"W∆ˆG3◊µ%TÂtïıUƒÙEıDá“˜&s◊µ%TÂtïÙı$t‰ï§DîÙÂıDá“F6∑3◊µ%TÂtïı5DEU5ıDá“"¿¢b"FWáEˆ÷ˆFV«3◊≤r¬rÊ¶ˆñ‚Ö˜'VÁvïˆFó&V7E˜FWáEˆ÷ˆFV≈ˆ6ÊFñFFW2Çíó“ì'eˆ÷ˆFV«3◊≤r¬rÊ¶ˆñ‚Ö˜'VÁvïˆFó&V7Eˆì'eˆ÷ˆFV≈ˆ6ÊFñFFW2Çíó“ˆ∆√◊µ%TÂtïÙDï$T5EıÙƒ≈ÙîÂDU%d≈ı3¢„g“◊µ%TÂtïÙDï$T5EıÙƒ≈Ù‘ÖÙîÂDU%d≈ı3¢„g◊2W∆ˆEˆGFV◊G3◊µ%TÂtïÙDï$T5EıUƒÙEÙEDT’E7“"¿¢b.(
"6ˆ÷WB∂Wì¢≤~)»Rrñb&ˆˆ¬Ñ4Ù‘UEÙïÙ¥UííV«6R~)ÿ¬w“&6S◊¥4Ù‘UEÙ$4UıU$«“"¿¢b"'VÁvíÙ6ˆ÷WB7&VFS◊µ%TÂtïÙ4Ù‘UEÙ5$TDUıDá“7FGW3◊µ%TÂtïÙ4Ù‘UEı5DEU5ıDá“"¿¢b"'VÁvíì'bVÊ&∆VC◊≤~)»Rrñb%TÂtïÙî‘tS%dîDTıÙT‰$ƒTBV«6R~)ÿ¬w“÷ˆFV«3◊≤r¬rÊ¶ˆñ‚Ö˜'VÁvïˆì'eˆ÷ˆFV≈ˆ6ÊFñFFW2Çíó“6ˆˆ∆F˜v„◊µ˜&˜fñFW%ˆ6ˆˆ∆F˜vÂˆ∆VgBÇw'VÁvïˆì'bró◊2ÜñFUˆW'&˜'3◊≤~)»Rrñb%TÂtïÙÑîDUıDT4ÖÙU%$ı%2V«6R~(	Bw“"¿¢b.(
"$r&V÷˜fS¢&˜fñFW#◊¥$uı$ıdîDU'“Ü˜F˜&ˆˆ”◊≤~)»Rrñb&ˆˆ¬ÖÑıDı$ÙÙ’ÙïÙ¥UííV«6R~)ÿ¬w“∆ˆ6≈˜&V÷&s◊≤~)»RrñbÑƒÙ4≈ı$T‘$uÙT‰$ƒTBÊB&V÷&u˜&V÷˜fRó2Ê˜BÊˆÊRíV«6R~)ÿ¬w“"¿¢b.(
"6˜&∂Wì¢≤~)»Rrñb&ˆˆ¬Ö4ı$ÙïÙ¥UííV«6R~)ÿ¬w“÷ˆFV√◊µ4ı$Ù‘ÙDT«“7&VFS◊µ4ı$Ù5$TDUıDá“"¿¢b.(
"∂∆ñÊr∂Wì¢≤~)»Rrñb&ˆˆ¬Ñ¥ƒî‰uÙïÙ¥UííV«6R~)ÿ¬w“÷ˆFV√◊¥¥ƒî‰uÙ‘ÙDT«“7&VFS◊¥¥ƒî‰uÙ5$TDUıDá“"¿¢b.(
"∂∆ñÊrfF#¢7&VFS◊¥¥ƒî‰uÙdD%Ù5$TDUıDá“7FGW3◊¥¥ƒî‰uÙdD%ı5DEU5ıDá“÷ˆFS◊¥¥ƒî‰uÙdD%Ù‘ÙDW“fF%˜fˆñ6UˆFVfV«C◊¥dD%ıEE5ÙDTdT≈EıdÙî4W“6˜7C“G¥dD%ıT‰ïEÙ4ı5EıU4C¢„&g“"¿¢b.(
"Ü˜F˛(i&6∆óóV∆ñÊS¢≤~)»Rˆ‚rñbÑıDıÙ4ƒïıïTƒî‰RV«6R~(	Bˆfbw“VÊvñÊS◊µÑıDıÙ4ƒïıdîDTıÙT‰tî‰W“ÊFófU˜6˜VÊC◊≤vˆ‚rñbÑıDıÙ4ƒïı4ıT‰BV«6Rvˆfbw“÷ˆFS◊µÑıDıÙ4ƒïÙ‘ÙDW“FVfV«C◊µÑıDıÙ4ƒïÙDTdT≈EÙEU$DîÙÂı7◊2÷É◊µÑıDıÙ4ƒïÙ‘ÖÙEU$DîÙÂı7◊2◊WÖˆVFñÛ◊≤~)»RrñbÑıDıÙ4ƒïÙ’UÖÙTDîÚV«6R~(	Bw“6˜7C“GµÑıDıÙ4ƒïıT‰ïEÙ4ı5EıU4C¢„&g“"¿¢b.(
"ff◊Vr◊WÉ¢Fñ÷V˜WC◊¥dd’TuÙ’UÖıDî‘TıUEı7◊26˜ïˆfó'7C◊≤~)»Rrñbdd’TuÙ’UÖÙ4ıïÙdï%5BV«6R~(	Bw“&W6WC◊¥dd’TuÙ’UÖı$TT‰4ÙDUı$U4UG“7&c◊¥dd’TuÙ’UÖÙ5$g“66∆UˆÉ◊¥dd’TuÙ’UÖı44ƒUÙÑTîtÖG“g3◊¥dd’TuÙ’UÖÙe7“VFñÛ◊¥dd’TuÙ’UÖÙTDîıÙ$ïE$DW“÷É◊¥dd’TuÙ’UÖÙ‘ÖÙ‘'‘‘""¿¢b.(
"7VÊÚf˜"Ü˜F˛(i&6∆ó¢≤~)»RWFÚrñb5T‰ıÙUDıÙdı%ıÑıDıÙ4ƒïV«6R~(	Bˆfbw“VÊ&∆VC◊≤~)»Rrñb5T‰ıÙT‰$ƒTBV«6R~(	Bw“∂Wì◊≤~)»Rrñb&ˆˆ¬Ö5T‰ıÙïÙ¥UííV«6R~)ÿ¬w“7&VFS◊µ5T‰ıÙ5$TDUıDá“÷ˆFV√◊µ5T‰ıÙ‘ÙDT«“"¿¢b.(
"í6V∆fñS¢&˜fñFW#◊¥ïı4TƒdîUı$ıdîDU'“6ˆ÷WEˆ∂Wì◊≤vˆ‚rñb&ˆˆ¬Ñ4Ù‘UEÙïÙ¥UííV«6Rvˆfbw“÷ˆFV√◊¥4Ù‘UEÙî‘tUÙTDïEÙ‘ÙDT«“f∆∆&6∑3◊≤r¬rÊ¶ˆñ‚Ñ4Ù‘UEÙî‘tUÙTDïEÙdƒƒ$4µÙ‘ÙDT≈2ó“FÉ◊¥4Ù‘UEÙî‘tUÙTDïEıDá“Fñ÷V˜WC◊¥4Ù‘UEÙî‘tUÙTDïEıDî‘TıUEı7◊2÷Ö˜6ñFS◊¥ïı4TƒdîUÙ‘Öı4îDW“6ó¶S◊¥ïı4TƒdîUÙî‘tUı4ï§W“f7C◊¥ïı4TƒdîUÙd5EÙ‘ÙDW“6˜7C“G¥ïı4TƒdîUıT‰ïEÙ4ı5EıU4C¢„&g“"¿¢b.(
"	›ÌÕΩç}mçÚGW&Fñˆ„¢∂∆ñÊrRÛ]£≤6˜&BÛÇÛ"]¢]rΩÌM]ì≤'VÁvíFWáN(i'fñFVÚÇñ÷v^(i'fñFVÛ≤«V÷-]Õ]››‚≠Ω-"¿¢b.(
"	˝ÌΩΩç›2≠mMΩRµdîDTııÙƒ≈ÙDTƒïı3¢„g“2"¿¢–¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ%∆‚"Ê¶ˆñ‚Ü∆ñÊW2íê†¶7ñÊ2FVb6÷EˆFñu˜'VÁvíáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢""%'VÁvíÙ6ˆ÷WBÜV«FÇFñvÊ˜7Fñ2‡†¢	]r==Õ]›-Ì"(	B]}Ì˝›ÚMç=›Ì-ç≠≠Ì›Mç==mçÇÇ6ó&7VóB'&V∂W"‡¢ˆFñu˜'VÁvíWFÇ(	B]}Ì˝›‚˝Ì-]˝]"ÌMçmçΩÕ›Ωí≠ΩÌrÇí›≠]Mç-≤‡¢ˆFñu˜'VÁví&W6WB(	BÌ6ˆˆ∆F˜v‚‡¢ˆFñu˜'VÁvíFW7B(	B˝Ì=]"]ΩÕ›=‚ì'b}M}2˝‚˝ÌΩ]M›]Õ2MÌ-‚‡¢"" ¢&w2“∑7G"ÜíÊ∆˜vW"Çíf˜"ñ‚Ü6ˆÁFWáBÊ&w2˜"µ“ï–¢ñb'&W6WB"ñ‚&w3†¢˜&˜fñFW%˜&W6WBÇ''VÁvïˆì'b"ê¢˜&˜fñFW%˜&W6WBÇ''VÁvï˜FWáEˆ6ˆ÷WB"ê¢˜&˜fñFW%˜&W6WBÇ''VÁvïˆFó&V7B"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)»R'VÁví&˜fñFW"6ˆˆ∆F˜v‚Ìç]“MΩÚFó&V7B¬ñ÷v^(i'fñFVÚÇFWáN(i'fñFVÚ‚"ê¢&WGW&‡†¢ñb&WFÇ"ñ‚&w3†¢ˆ≤¬FWFñ¬“vóB˜'VÁvïˆFó&V7Eˆ˜&uˆñÊfÚÇê¢&VfóÇ“.)»R	ÌMçmçΩÕ›Ωí'VÁvííMÌ-=˝]“"ñbˆ≤V«6R.)ÿ¬	ÌMçmçΩÕ›Ωí'VÁvíí›R=Ì-Ì" ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBá&VfóÇ≤%∆‚"≤FWFñ¬ê¢&WGW&‡†¢∆ñÊW2“∞¢b/	˙z¢'VÁvíÙ6ˆ÷WBMç=›Ì-ç≠ÚµD4ÖıdU%4îÙÁ“"¿¢b.(
"VÊ&∆VC¢≤~)»Rrñb%TÂtïÙî‘tS%dîDTıÙT‰$ƒTBV«6R~)ÿ¬w“W6Uˆ6ˆ÷WC◊≤~)»Rrñb%TÂtïıU4UÙ4Ù‘UBV«6R~(	Bw“"¿¢b.(
"6ˆ÷WEˆ∂Wì¢≤~)»Rrñb&ˆˆ¬Ñ4Ù‘UEÙïÙ¥UííV«6R~)ÿ¬w“&6S◊¥4Ù‘UEÙ$4UıU$«“"¿¢b.(
"7&VFS◊µ%TÂtïÙ4Ù‘UEÙ5$TDUıDá“7FGW3◊µ%TÂtïÙ4Ù‘UEı5DEU5ıDá“"¿¢b.(
"fW'6ñˆ„◊µ%TÂtïÙïıdU%4îÙ‚˜"s##B””bw“"¿¢b.(
"÷ˆFV«3◊≤r¬rÊ¶ˆñ‚Ö˜'VÁvïˆì'eˆ÷ˆFV≈ˆ6ÊFñFFW2Çíó“"¿¢b.(
"Fó&V7EˆVÊ&∆VC¢≤~)»Rrñb%TÂtïÙDï$T5EÙT‰$ƒTBV«6R~)ÿ¬w“Fó&V7Eˆ∂Wì¢≤~)»Rrñb&ˆˆ¬Ö%TÂtïÙïÙ¥UííV«6R~)ÿ¬w“Fó&V7Eˆfó'7C◊≤~)»Rrñb%TÂtïÙDï$T5EÙdï%5BV«6R~(	Bw“"¿¢b.(
"∂Wï˜6˜W&6S◊µ%TÂtïÙ¥Uïı4ıU$4W“fñÊvW'&ñÁC◊∑'VÁvï˜6fUˆ∂WïˆfñÊvW'&ñÁBÖ%TÂtïÙïÙ¥Uíó“"¿¢b.(
"ˆffñ6ñ≈ˆ&6S◊µ%TÂtïÙ$4UıU$«“fW'6ñˆ„◊µ%TÂtïÙïıdU%4îÙÁ“"¿¢b.(
"ˆffñ6ñ≈ˆVÊGˆñÁG3¢FWáC◊µ%TÂtïıDUÖEÙ5$TDUıDá“ì'c◊µ%TÂtïÙì%eıDá“W∆ˆC◊µ%TÂtïıUƒÙEıDá“˜&s◊µ%TÂtïÙı$t‰ï§DîÙÂıDá“"¿¢b.(
"Fó&V7BFWáB÷ˆFV«3◊≤r¬rÊ¶ˆñ‚Ö˜'VÁvïˆFó&V7E˜FWáEˆ÷ˆFV≈ˆ6ÊFñFFW2Çíó“ì'b÷ˆFV«3◊≤r¬rÊ¶ˆñ‚Ö˜'VÁvïˆFó&V7Eˆì'eˆ÷ˆFV≈ˆ6ÊFñFFW2Çíó“"¿¢b.(
"ˆ∆∆ñÊs◊µ%TÂtïÙDï$T5EıÙƒ≈ÙîÂDU%d≈ı3¢„g“◊µ%TÂtïÙDï$T5EıÙƒ≈Ù‘ÖÙîÂDU%d≈ı3¢„g◊2&WG&ñW3◊µ%TÂtïÙDï$T5Eı$UE%ïÙEDT’E7“W∆ˆEˆGFV◊G3◊µ%TÂtïÙDï$T5EıUƒÙEÙEDT’E7“FF˜W&ïˆf∆∆&6≥◊≤~)»Rrñb%TÂtïÙDï$T5EÙDDıU$ïÙdƒƒ$4≤V«6R~(	Bw“"¿¢b.(
"ÜñFU˜FV6ÖˆW'&˜'3◊≤~)»Rrñb%TÂtïÙÑîDUıDT4ÖÙU%$ı%2V«6R~(	Bw“f∆∆&6µˆ∂∆ñÊs◊≤~)»Rrñb%TÂtïıDUÖEÙdƒƒ$4µÙ¥ƒî‰rÊB%TÂtïÙUDıÙdƒƒ$4µÙ¥ƒî‰rV«6R~(	Bw“"¿¢b.(
"ì'eˆ6ˆˆ∆F˜v„◊µ˜&˜fñFW%ˆ6ˆˆ∆F˜vÂˆ∆VgBÇw'VÁvïˆì'bró◊2FWáEˆ6ˆˆ∆F˜v„◊µ˜&˜fñFW%ˆ6ˆˆ∆F˜vÂˆ∆VgBÇw'VÁvï˜FWáEˆ6ˆ÷WBró◊2"¿¢–¢ñb˜&˜fñFW%ˆ∆7EˆW'&˜"ÊvWBÇ''VÁvïˆì'b"ì†¢∆ñÊW2ÊVÊBÇ.(
"∆7EˆW'&˜#“"≤˜&˜fñFW%ˆ∆7EˆW'&˜"ÊvWBÇ''VÁvïˆì'b"¬""ï≥£s“ê†¢ñb'FW7B"Ê˜Bñ‚&w3†¢∆ñÊW2ÊVÊBÇ""ê¢∆ñÊW2ÊVÊBÇ-	˝Ì-]ç-¬ÌMçmçΩÕ›Ωí≠ΩÌrÇí›≠]Mç-≥¢ˆFñu˜'VÁvíWFÇ"ê¢∆ñÊW2ÊVÊBÇ-	MΩÚ]ΩÕ›Ì=‚-]-Ì-˝-Õ-R}ç-ÌRMÌ-‚¬}-]√¢ˆFñu˜'VÁvíFW7B"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ%∆‚"Ê¶ˆñ‚Ü∆ñÊW2ï≥£3ì“ê¢&WGW&‡†¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢ñbÊ˜Bñ÷s†¢∆ñÊW2ÊVÊBÇ.)ÿ¬	›]"˝ÌΩ]M›]=‚MÌ-‚‚
›}ΩÌ-˝-Õ-RMÌ-‚"Ì"¬}-]¬ˆFñu˜'VÁvíFW7B"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ%∆‚"Ê¶ˆñ‚Ü∆ñÊW2ï≥£3ì“ê¢&WGW&‡†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ%∆‚"Ê¶ˆñ‚Ü∆ñÊW2ï≥£#S“≤%∆Â∆Ó)kn˚àÚ	}˝=≠‚]ΩÕ›Ωí≠ÌÌ-≠çí-]"ÌMçmçΩÕ›Ì=‚'VÁví‚
›-‚˝çç]"í›≠]Mç-≤¬]ΩÇ}M}=M]"˝ç›˝-‚"ê¢ñbÊ˜B%TÂtïÙïÙ¥Uì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬%TÂtî‘≈Ùïı4T5$UB›R›ùM]“‚	MÌ-Õ-R≠ΩÌr"&VÊFW"6V7&WBfñ∆R'VÁvíÊVÁbçΩÇ"VÁfó&ˆÊ÷VÁB‚"ê¢&WGW&‡¢ˆ≤“vóB˜'VÂ˜'VÁvïˆFó&V7EˆÊñ÷FU˜Ü˜FÚÄ¢WFFR¬6ˆÁFWáB¬ñ÷r¿¢'7V'F∆R˜'G&óBÊñ÷Fñˆ‚¬∂VWñFVÁFóGí¬6÷∆¬ÊGW&¬÷˜Fñˆ‚"¿¢R¬#ì£b"¿¢ê¢ñbˆ≥†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)»Rˆffñ6ñ¬'VÁvíFW7C¢}M}Ì-Ì-Ω‚"ê¢V«6S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚˆffñ6ñ¬'VÁvíFW7B›R˝Ìç≤‚	-Ω˝ÌΩ›ç-RˆFñu˜'VÁvíWFÇÇ˝Ì-]Õ-Rí›≠]Mç-≤"FWfV∆˜W"˜'F¬‚"ê†¶7ñÊ2FVb6÷E˜&˜fñFW%˜7FGW2áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢""%6Ü˜'B&˜fñFW"ÜV«FÇF6Ü&ˆ&Bf˜"&ˆGV7Fñˆ‚6ÜV6∑2‚"" ¢&w2“∑7G"ÜíÊ∆˜vW"Çíf˜"ñ‚Ü6ˆÁFWáBÊ&w2˜"µ“ï–¢ñb'&W6WB"ñ‚&w3†¢f˜"Ê÷Rñ‚Ç''VÁvïˆì'b"¬ì†¢˜&˜fñFW%˜&W6WBÜÊ÷Rê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)»R&˜fñFW"6ˆˆ∆F˜v‚Ìç]“‚"ê¢&WGW&‡¢∆ñÊW2“∞¢b/	˘8¢&˜fñFW"7FGW2ÚµD4ÖıdU%4îÙÁ“"¿¢b.(
"'VÁvíì'c¢≤~)»Rfñ∆&∆Rrñb˜&˜fñFW%ˆó5ˆfñ∆&∆RÇw'VÁvïˆì'bríV«6R	˘˙6ˆˆ∆F˜v‚w“Ú6ˆˆ∆F˜v„◊µ˜&˜fñFW%ˆ6ˆˆ∆F˜vÂˆ∆VgBÇw'VÁvïˆì'bró◊2Úfñ«3◊µ˜&˜fñFW%ˆfñ≈ˆ6˜VÁG2ÊvWBÇw'VÁvïˆì'br¬ó“"¿¢b.(
"'VÁví÷ˆFV«3¢≤r¬rÊ¶ˆñ‚Ö˜'VÁvïˆì'eˆ÷ˆFV≈ˆ6ÊFñFFW2Çíó“"¿¢b.(
"∂∆ñÊrf∆∆&6≥¢≤~)»RrñbÖ%TÂtïÙUDıÙdƒƒ$4µÙ¥ƒî‰rÊB&ˆˆ¬Ñ4Ù‘UEÙïÙ¥UíííV«6R~)ÿ¬w“ÚFÉ◊¥¥ƒî‰uÙ5$TDUıDá“"¿¢b.(
"ÜñFRFV6ÇW'&˜'3¢≤~)»Rrñb%TÂtïÙÑîDUıDT4ÖÙU%$ı%2V«6R~)ÿ¬w“"¿¢b.(
"ì%b&W&ˆ6W73¢≤~)»Rrñbì%eı$U$Ù4U55ÙT‰$ƒTBV«6R~)ÿ¬w“Ú÷Ö˜6ñFS◊¥ì%eÙ‘Öı4ıU$4Uı4îDW“"¿¢–¢ñb˜&˜fñFW%ˆ∆7EˆW'&˜"ÊvWBÇ''VÁvïˆì'b"ì†¢∆ñÊW2ÊVÊBÇ.(
"'VÁví∆7EˆW'&˜#¢"≤˜&˜fñFW%ˆ∆7EˆW'&˜"ÊvWBÇ''VÁvïˆì'b"¬""ï≥£ì“ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ%∆‚"Ê¶ˆñ‚Ü∆ñÊW2ï≥£3ì“ê††¢2)H)H)H)H)H)H)H)H)H‘î‘RMΩÚç}Ìm]›çí)H)H)H)H)H)H)H)H)H ¶FVb6Êñfeˆñ÷vUˆ÷ñ÷RÜFF¢'óFW2í”‚7G#†¢ñbÊ˜BFF˜"∆V‚ÜFFí¬#†¢&WGW&‚&∆ñ6Fñˆ‚ˆˆ7FWB◊7G&V“ ¢"“FF≥£%–¢ñb"Á7F'G7vóFÇÜ"%«ÉÉï‰u«%∆Â«É∆‚"ì†¢&WGW&‚&ñ÷vR˜Êr ¢ñb%≥£5“”“"%«Üfe«ÜCÖ«Üfb#†¢&WGW&‚&ñ÷vRˆßVr ¢ñb%≥£E“”“"%$îdb"ÊB%≥É£%“”“"%tT%#†¢&WGW&‚&ñ÷vR˜vV' ¢&WGW&‚&∆ñ6Fñˆ‚ˆˆ7FWB◊7G&V“ †¢2)H)H)H)H)H)H)H)H)H	˝Ì˝mçí-çM]‚)H)H)H)H)H)H)H)H)H •Ù5T5E2“≤#ì£b"¬#c£í"¬#£"¬#C£R"¬#3£B"¬#C£2'–†¶FVb'6U˜fñFVıˆ˜G2áFWáC¢7G"í”‚GW∆U∂ñÁB¬7G%”†¢F¬“áFWáB˜"""íÊ∆˜vW"Çê¢““&RÁ6V&6Çá""Ö∆B≤ï«2¢ÉÛ≠]ßÕï∆""¬F¬ê¢GW&Fñˆ‚“ñÁBÜ“Êw&˜WÉííñb“V«6R≈T‘ÙEU$DîÙÂı0¢GW&Fñˆ‚“÷ÇÉ2¬÷ñ‚É#¬GW&Fñˆ‚íê¢7“ÊˆÊP¢f˜"ñ‚Ù5T5E3†¢ñbñ‚F√†¢7“¢'&V∞¢7V7B“7˜"Ñ≈T‘Ù5T5Bñb≈T‘Ù5T5Bñ‚Ù5T5E2V«6R#c£í"ê¢&WGW&‚GW&Fñˆ‚¬7V7@††¢2)H)H)H)H)H)H)H)H)H«V÷fñFVÚ)H)H)H)H)H)H)H)H)H ¶7ñÊ2FVb˜'VÂˆ«V÷˜fñFVÚÄ¢WFFS¢WFFR¿¢6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¿¢&ˆ◊C¢7G"¿¢GW&FñˆÂ˜3¢ñÁB¿¢7V7C¢7G"¿¢ì†¢vóB6ˆÁFWáBÊ&˜BÁ6VÊEˆ6ÜEˆ7Fñˆ‚áWFFRÊVffV7FófUˆ6ÜBÊñB¬6ÜD7Fñˆ‚Â$T4ı$EıdîDTÚê¢G'ì†¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC”c„í26∆ñVÁC†¢&6R“vóB˜ñ6µˆ«V÷ˆ&6RÜ6∆ñVÁBê¢7&VFU˜W&¬“b'∂&6W◊¥≈T‘Ù5$TDUıDá“ †¢ÜVFW'2“∞¢$WFÜ˜&ó¶Fñˆ‚#¢b$&V&W"¥≈T‘ÙïÙ¥Uó“"¿¢$66WB#¢&∆ñ6Fñˆ‚ˆß6ˆ‚"¿¢–¢ñ∆ˆB“∞¢&÷ˆFV¬#¢≈T‘Ù‘ÙDT¬¿¢'&ˆ◊B#¢&ˆ◊B¿¢&GW&Fñˆ‚#¢b'∂GW&FñˆÂ˜7◊2"¿¢&7V7E˜&FñÚ#¢7V7B¿¢–†¢2Ì}M¬}M}0¢"“vóB6∆ñVÁBÁ˜7BÜ7&VFU˜W&¬¬ÜVFW'3÷ÜVFW'2¬ß6ˆ„◊ñ∆ˆBê¢ñb"Á7FGW5ˆ6ˆFR„“C†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b.)™˚àÚ«V÷Ì-≠ΩÌ›çΩ}M}2á∑"Á7FGW5ˆ6ˆFW“í‚ ¢ê¢&WGW&‡†¢FF“"Êß6ˆ‚Çí˜"∑–¢&ñB“FFÊvWBÇ&ñB"í˜"FFÊvWBÇ&vVÊW&FñˆÂˆñB"ê¢ñbÊ˜B&ñC†¢∆ˆrÊW'&˜"Ç$«V÷¢ÊÚvVÊW&Fñˆ‚ñBñ‚&W7ˆÁ6S¢W2"¬FFê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ«V÷›R-]›=ΩñB=]›]mçÇ‚"ê¢&WGW&‡†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.(˚2«V÷]›M]ç.(
b
ÚÌÌù2¬≠Ì=M-çM]‚=M]"=Ì-Ì-‚‚ ¢ê†¢7FGW5˜W&¬“b'∂&6W◊¥≈T‘ı5DEU5ıDá“"Êf˜&÷BÜñC◊&ñBê¢7F'FVB“Fñ÷RÁFñ÷RÇê†¢vÜñ∆RG'VS†¢'2“vóB6∆ñVÁBÊvWBá7FGW5˜W&¬¬ÜVFW'3÷ÜVFW'2ê¢G'ì†¢ß2“'2Êß6ˆ‚Çí˜"∑–¢WÜ6WBWÜ6WFñˆ„†¢ß2“∑–†¢7B“Üß2ÊvWBÇ'7FFR"í˜"ß2ÊvWBÇ'7FGW2"í˜"""íÊ∆˜vW"Çê†¢ñb7Bñ‚Ç&6ˆ◊∆WFVB"¬'7V66VVFVB"¬&fñÊó6ÜVB"¬'&VGí"ì†¢2“““	›	Ì	-
Ω	í›Mm›Ωí˝Ìç¢ΩΩ≠Ç›-çM]‚““–¢W&¬“ÊˆÊP¢76WG2“ß2ÊvWBÇ&76WG2"ê†¢FVbˆWáG&7E˜W&«5ˆg&ˆ’ˆ76WG2Üì†¢W&«2“µ–¢ñbó6ñÁ7FÊ6RÜ¬7G"ì†¢W&«2ÊVÊBÜê¢V∆ñbó6ñÁ7FÊ6RÜ¬Fñ7Bì†¢2-ç˝ç}›ΩíMÌÕ#¢≤'fñFVÚ#¢&áGG3¢ÚÚ‚‚‚'“çΩÇ≤'fñFVÚ#¢≤'W&¬#¢"‚‚‚'◊–¢f˜"bñ‚Áf«VW2Çì†¢W&«2ÊWáFVÊBÖˆWáG&7E˜W&«5ˆg&ˆ’ˆ76WG2ábíê¢V∆ñbó6ñÁ7FÊ6RÜ¬Ü∆ó7B¬GW∆Ríì†¢f˜"óFV“ñ‚†¢W&«2ÊWáFVÊBÖˆWáG&7E˜W&«5ˆg&ˆ’ˆ76WG2ÜóFV“íê¢&WGW&‚W&«0†¢ñb76WG2ó2Ê˜BÊˆÊS†¢f˜"Rñ‚ˆWáG&7E˜W&«5ˆg&ˆ’ˆ76WG2Ü76WG2ì†¢ñbó6ñÁ7FÊ6RáR¬7G"íÊBRÁ7F'G7vóFÇÇ&áGG"ì†¢W&¬“P¢'&V∞†¢2}˝›ΩR≠ΩÌ}Ç›-˝≠çíΩ=}ê¢ñbÊ˜BW&√†¢f˜"≤ñ‚Ç&˜WGWE˜W&¬"¬'fñFVı˜W&¬"¬'W&¬"ì†¢f¬“ß2ÊvWBÜ≤ê¢ñbó6ñÁ7FÊ6Ráf¬¬7G"íÊBf¬Á7F'G7vóFÇÇ&áGG"ì†¢W&¬“f¿¢'&V∞†¢ñbÊ˜BW&√†¢∆ˆrÊW'&˜"Ç$«V÷¢Ì--]"]rΩΩ≠Ç›-çM]„¢W2"¬ß2ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)ÿ¬«V÷¢Ì--]"˝çç≤]rΩΩ≠Ç›-çM]‚‚ ¢ê¢&WGW&‡†¢2
≠}ç-]¬ÇÌ-˝-Ω˝]¬Mù≤≠¢-çM]‡¢G'ì†¢b“vóB6∆ñVÁBÊvWBáW&¬¬Fñ÷V˜WC”#„ê¢bÁ&ó6Uˆf˜%˜7FGW2Çê¢&ñÚ“'óFW4îÚábÊ6ˆÁFVÁBê¢&ñÚÊÊ÷R“&«V÷Ê◊B ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜fñFVÚÄ¢ñÁWDfñ∆RÜ&ñÚí¿¢6Fñˆ„“/	¯Í¬«V÷¢=Ì-Ì-‚)»R"¿¢ê¢WÜ6WBWÜ6WFñˆ„†¢2]ΩÇ›R˝ÌΩ=}çΩÌ¬≠}-¬(	B]Ì-Ú≤M¬˝˝Õ=‚ΩΩ≠0¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b/	¯Í¬«V÷¢=Ì-Ì-‚)»U∆Á∑W&«“ ¢ê¢&WGW&‡†¢ñb7Bñ‚Ç&fñ∆VB"¬&W'&˜""¬&6Ê6V∆VB"¬&6Ê6V∆∆VB"ì†¢∆ˆrÊW'&˜"Ç$«V÷&WGW&ÊVBW'&˜"7FFS¢W2"¬ß2ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬«V÷¢Ìçç≠]›M]‚"ê¢&WGW&‡†¢ñbFñ÷RÁFñ÷RÇí“7F'FVB‚≈T‘Ù‘ÖıtïEı3†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.(…≤«V÷¢-]ÕÚÌmçM›çÚ-ΩçΩ‚‚ ¢ê¢&WGW&‡†¢vóB7ñÊ6ñÚÁ6∆VWÖdîDTııÙƒ≈ÙDTƒïı2ê†¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç$«V÷W'&˜#¢W2"¬Rê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)ÿ¬«V÷¢›R=MΩÌ¬}˝=-ç-¬˝˝ÌΩ=}ç-¬-çM]‚‚ ¢ê¢2)H)H)H)H)H)H)H)H)H'VÁvífñFVÚ)H)H)H)H)H)H)H)H)H ¶FVbˆFVGWUˆ÷ˆFV«2Ç¶óFV◊3¢7G"í”‚∆ó7E∑7G%”†¢˜WC¢∆ó7E∑7G%““µ–¢f˜"“ñ‚óFV◊3†¢““Ü“˜"""íÁ7G&óÇê¢ñb“ÊB“Ê˜Bñ‚˜WC†¢˜WBÊVÊBÜ“ê¢&WGW&‚˜W@†¶FVb˜'VÁvïˆì'eˆ÷ˆFV≈ˆ6ÊFñFFW2Çí”‚∆ó7E∑7G%”†¢""-	ÕÌM]ΩÇ'VÁvíMΩÚÌmç-Ω]›çÚMÌ-‚ˆñ÷v^(i'fñFVÚ‡†¢css¢˝çÌ¢]-Úçr%TÂtïÙî‘tS%dîDTıÙ‘ÙDT≈2‚	˝]-Ω¬-Ìç"˝=Ωç}›Ωê¢Ωç6ˆ÷WB'VÁvñ÷¬÷ñ÷vR◊FÚ◊fñFVÚ¬}-]¬&6∂VÊB›Ωç≤‚vV„B„R›Õ]]››‡¢›R-≠ΩÌ}“"M]MÌΩ"¬˝Ì-ÌÕ2}-‚"ΩÌ=R}-‚Ì--]}≤÷ˆFV≈ˆÊ˜Eˆf˜VÊBˆÊÚfñ∆&∆R6ÜÊÊV¬‡¢"" ¢VÁeˆ÷ˆFV«2“∂“Á7G&óÇíf˜"“ñ‚Ö%TÂtïÙî‘tS%dîDTıÙ‘ÙDT≈5ÙTÂb˜"""íÁ7∆óBÇ"¬"íñb“Á7G&óÇï–¢&WGW&‚ˆFVGWUˆ÷ˆFV«2Ç¢ÜVÁeˆ÷ˆFV«2˜"≤''VÁvñ÷¬÷ñ÷vR◊FÚ◊fñFVÚ"¬&vV„E˜GW&&Ú"¬&vV„6˜GW&&Ú"¬'fVÛ2„ˆf7B"¬'fVÛ2„"¬'fVÛ2%“íê†¶FVb˜'VÁvïˆFó&V7E˜FWáEˆ÷ˆFV≈ˆ6ÊFñFFW2Çí”‚∆ó7E∑7G%”†¢""$ˆffñ6ñ¬'VÁvíFWáN(i'fñFVÚ6ÊFñFFW2‚vV‚”B„R7W˜'G2FWáB÷ˆÊ«íñÁWB‚"" ¢VÁeˆ÷ˆFV«2“∂“Á7G&óÇíf˜"“ñ‚Ö%TÂtïÙDï$T5EıDUÖEÙ‘ÙDT≈5ÙTÂb˜"""íÁ7∆óBÇ"¬"íñb“Á7G&óÇï–¢&WGW&‚ˆFVGWUˆ÷ˆFV«2Ç¢ÜVÁeˆ÷ˆFV«2˜"µ%TÂtïıDUÖEÙ‘ÙDT¬¬&vV„B„R%“íê††¶FVb˜'VÁvïˆFó&V7Eˆì'eˆ÷ˆFV≈ˆ6ÊFñFFW2Çí”‚∆ó7E∑7G%”†¢""$ˆffñ6ñ¬'VÁvíñ÷v^(i'fñFVÚ6ÊFñFFW2ˆÊ«ì≤ÊÚ6ˆ÷WB∆ñ6W2˜"fVÚ÷ˆFV«2‚"" ¢VÁeˆ÷ˆFV«2“∂“Á7G&óÇíf˜"“ñ‚Ö%TÂtïÙDï$T5EÙì%eÙ‘ÙDT≈5ÙTÂb˜"""íÁ7∆óBÇ"¬"íñb“Á7G&óÇï–¢&WGW&‚ˆFVGWUˆ÷ˆFV«2Ç¢ÜVÁeˆ÷ˆFV«2˜"≤&vV„B„R"¬&vV„E˜GW&&Ú%“íê††¶FVb˜'VÁvïˆ6ˆ÷WE˜FWáEˆ÷ˆFV≈ˆ6ÊFñFFW2Çí”‚∆ó7E∑7G%”†¢""%6÷∆¬fñ¬÷f7B6ˆ÷WB6ÊFñFFR∆ó7C≤ÊÚñ∆ˆBˆ÷ˆFV¬7F˜&“vÜV‚FÜR6ÜÊÊV¬ó2VÊfñ∆&∆R‚"" ¢VÁeˆ÷ˆFV«2“∂“Á7G&óÇíf˜"“ñ‚Ö%TÂtïÙ4Ù‘UEıDUÖEÙ‘ÙDT≈5ÙTÂb˜"""íÁ7∆óBÇ"¬"íñb“Á7G&óÇï–¢&WGW&‚ˆFVGWUˆ÷ˆFV«2Ç¢ÜVÁeˆ÷ˆFV«2˜"≤''VÁví◊fñFVÚ"¬&vV„B„R%“íê††¶FVb˜'VÁvïˆFó&V7Eˆ&6Uˆ6ÊFñFFW2Çí”‚∆ó7E∑7G%”†¢"" ¢Fó&V7B'VÁvíí]ù}Ì-]"}]]ráGG3¢ÚˆíÊFWbÁ'VÁvñ÷¬Ê6ˆ“˜cÚ‚‚‚‡¢	]ΩÇ"TÂbÌ-ΩÚ-Ωí&6U˜W&¬¬--›‚MÌ-Ω˝]¬ÌMçmçΩÕ›Ωí&6R≠¢f∆∆&6≤‡¢"" ¢&r“Ö%TÂtïÙ$4UıU$¬˜"""íÁ7G&óÇíÁ'7G&óÇ"Ú"ê¢˜WC¢∆ó7E∑7G%““µ–¢f˜"&6Rñ‚á&r¬&áGG3¢ÚˆíÊFWbÁ'VÁvñ÷¬Ê6ˆ“"ì†¢ñbÊ˜B&6S†¢6ˆÁFñÁVP¢ñb&6RÊVÊG7vóFÇÇ"˜c"ì†¢&6R“&6U≥¢”5“Á'7G&óÇ"Ú"ê¢ñb&6RÊB&6RÊ˜Bñ‚˜WC†¢˜WBÊVÊBÜ&6Rê¢&WGW&‚˜W@††¶FVb˜'VÁvïˆFó&V7EˆÜVFW'2Çí”‚Fñ7E∑7G"¬7G%”†¢&WGW&‚∞¢$WFÜ˜&ó¶Fñˆ‚#¢b$&V&W"µ%TÂtïÙïÙ¥Uó“"¿¢$66WB#¢&∆ñ6Fñˆ‚ˆß6ˆ‚"¿¢$6ˆÁFVÁB’GóR#¢&∆ñ6Fñˆ‚ˆß6ˆ‚"¿¢%Ç’'VÁví’fW'6ñˆ‚#¢%TÂtïÙïıdU%4îÙ‚˜"###B””b"¿¢–††¶FVb˜'VÁvïˆFó&V7E˜&FñÚÜ7V7C¢7G"í”‚7G#†¢""$7W'&VÁB'VÁvívV‚”B„RÙvV‚”BGW&&Ú∆ÊG66R˜"˜'G&óB&FñÚ‚"" ¢&WGW&‚#s#£#É"ñbÜ7V7B˜"""íÁ7G&óÇíñ‚≤#ì£b"¬#3£B"¬#C£R'“V«6R##É£s# ††¶FVb˜'VÁvïˆˆffñ6ñ≈ˆ6∆ñVÁBÇí”‚'VÁvîˆffñ6ñƒ6∆ñVÁC†¢&WGW&‚'VÁvîˆffñ6ñƒ6∆ñVÁBÄ¢%TÂtïÙïÙ¥Uí¿¢&6U˜W&√’%TÂtïÙ$4UıU$¬¿¢ï˜fW'6ñˆ„’%TÂtïÙïıdU%4îÙ‚˜"###B””b"¿¢&WG'ïˆGFV◊G3’%TÂtïÙDï$T5Eı$UE%ïÙEDT’E2¿¢&WG'ïˆ&6U˜3’%TÂtïÙDï$T5Eı$UE%ïÙ$4Uı2¿¢ˆ∆≈ˆñÁFW'f≈˜3’%TÂtïÙDï$T5EıÙƒ≈ÙîÂDU%d≈ı2¿¢ˆ∆≈ˆ÷ÖˆñÁFW'f≈˜3’%TÂtïÙDï$T5EıÙƒ≈Ù‘ÖÙîÂDU%d≈ı2¿¢W∆ˆEˆGFV◊G3’%TÂtïÙDï$T5EıUƒÙEÙEDT’E2¿¢FF˜W&ïˆf∆∆&6≥’%TÂtïÙDï$T5EÙDDıU$ïÙdƒƒ$4≤¿¢ê††¶FVb˜'VÁvï˜W6W%ˆW'&˜%˜FWáBÜWÜ3¢WÜ6WFñˆ‚í”‚7G#†¢ñbó6ñÁ7FÊ6RÜWÜ2¬'VÁvïF6µFñ÷V˜WBì†¢&WGW&‚.(…≤'VÁví›R}-]çç≤}M}2}Ì--]M››ÌR-]ÕÚ‚	≠]Mç-≤Ì-›R˝ç›≤‚ ¢ñbó6ñÁ7FÊ6RÜWÜ2¬'VÁvîîW'&˜"ì†¢6ˆFR“ÜWÜ2Êfñ«W&Uˆ6ˆFR˜"""íÁWW"Çê¢FWáB“7G"ÜWÜ2íÊ∆˜vW"Çê¢ñb6ˆFRÁ7F'G7vóFÇÇ%4dUEí"í˜"'6fWGí"ñ‚FWáB˜"&÷ˆFW&Fñˆ‚"ñ‚FWáC†¢&WGW&‚.)™˚àÚ'VÁvíÌ-≠ΩÌ›ç≤}˝Ì˝‚˝-çΩ¬]}Ì˝›Ì-Ç‚	ç}Õ]›ç-Rm]›2çΩÇMÌÕ=ΩçÌ-≠2(	B≠]Mç-≤›R˝ç›≤‚ ¢ñbWÜ2Á7FGW5ˆ6ˆFRñ‚≥C¬C7”†¢&WGW&‚.)ÿ¬'VÁví›R˝ç›˝≤í›≠ΩÌr‚	˝Ì-]Õ-R%TÂtî‘≈Ùïı4T5$UB"&VÊFW"VÁfó&ˆÊ÷VÁBçΩÇ6V7&WBfñ∆R'VÁvíÊVÁb‚ ¢ñbWÜ2Á7FGW5ˆ6ˆFR”“C"˜"&7&VFóB"ñ‚FWáBÊBÇ&ñÁ7Vffñ6ñVÁB"ñ‚FWáB˜"&Ê˜BVÊ˜VvÇ"ñ‚FWáBì†¢&WGW&‚.)ÿ¬	›í›Ω›R'VÁví›]MÌ--Ì}›‚≠]Mç-Ì"‚	˝Ì˝ÌΩ›ç-R&ñ∆∆ñÊr"'VÁvíFWfV∆˜W"˜'F¬‚ ¢ñbWÜ2Á7FGW5ˆ6ˆFR”“C#ì†¢&WGW&‚.)™˚àÚ	MÌ-ç=›="ΩçÕç"'VÁvíMΩÚ-]≠=ù]=‚í◊FñW"‚	}M}=M]"›˝-Ω]›"]}]-›ΩíM-çmÌ¢‚ ¢ñbWÜ2Á7FGW5ˆ6ˆFR”“C†¢&WGW&‚.)™˚àÚ'VÁví›R˝ç›˝≤˝Õ]-≤}M}Ç‚	˝Ì-]Õ-RMΩç-]ΩÕ›Ì-¬¬MÌÕ"ç}Ìm]›çÚÇ-]≠"}˝Ì‚ ¢&WGW&‚.)™˚àÚ	ÌMçmçΩÕ›Ωí'VÁví-]Õ]››‚›RÌ--]-ç≤‚	ç˝ÌΩÕ}=‚]}]-›ΩíÕç="‚ ††¶7ñÊ2FVb˜'VÁvï˜&WVW7E˜vóFÖ˜&WG&ñW2Ü6∆ñVÁC¢áGGÇ‰7ñÊ46∆ñVÁB¬÷WFÜˆC¢7G"¬W&√¢7G"¬¢¬ÜVFW'3¢Fñ7B¬ß6ˆÂˆ&ˆGì¢Fñ7B¬ÊˆÊR“ÊˆÊRì†¢""%&WG'íˆÊ«íG&Á6ñVÁB'VÁví&W7ˆÁ6W2vóFÇWáˆÊVÁFñ¬&6∂ˆfbÊB¶óGFW"‚"" ¢G&Á6ñVÁB“≥C#í¬S"¬S2¬SG–¢∆7B“ÊˆÊP¢f˜"GFV◊Bñ‚&ÊvRÖ%TÂtïÙDï$T5Eı$UE%ïÙEDT’E2ì†¢G'ì†¢"“vóB6∆ñVÁBÁ&WVW7BÜ÷WFÜˆB¬W&¬¬ÜVFW'3÷ÜVFW'2¬ß6ˆ„÷ß6ˆÂˆ&ˆGíê¢∆7B“ ¢ñb"Á7FGW5ˆ6ˆFRÊ˜Bñ‚G&Á6ñVÁB˜"GFV◊B„“%TÂtïÙDï$T5Eı$UE%ïÙEDT’E2“†¢&WGW&‚ ¢FV∆í“%TÂtïÙDï$T5Eı$UE%ïÙ$4Uı2¢É"¢¢GFV◊Bê¢FV∆í≥“&ÊFˆ“ÁVÊñf˜&“É¬FV∆í¢„Rê¢∆ˆrÁv&ÊñÊrÇ%'VÁvíG&Á6ñVÁBÖEEW3≤&WG'íW2ÚW2ñ‚R„g2"¬"Á7FGW5ˆ6ˆFR¬GFV◊B≤¬%TÂtïÙDï$T5Eı$UE%ïÙEDT’E2¬FV∆íê¢vóB7ñÊ6ñÚÁ6∆VWÜFV∆íê¢WÜ6WBÜáGGÇÂFñ÷V˜WDWÜ6WFñˆ‚¬áGGÇÂG&Á7˜'DW'&˜"í2S†¢∆7B“P¢ñbGFV◊B„“%TÂtïÙDï$T5Eı$UE%ïÙEDT’E2“†¢&ó6P¢FV∆í“%TÂtïÙDï$T5Eı$UE%ïÙ$4Uı2¢É"¢¢GFV◊Bê¢FV∆í≥“&ÊFˆ“ÁVÊñf˜&“É¬FV∆í¢„Rê¢∆ˆrÁv&ÊñÊrÇ%'VÁvíG&Á7˜'BW'&˜#≤&WG'íW2ÚW2ñ‚R„g3¢W2"¬GFV◊B≤¬%TÂtïÙDï$T5Eı$UE%ïÙEDT’E2¬FV∆í¬Rê¢vóB7ñÊ6ñÚÁ6∆VWÜFV∆íê¢&WGW&‚∆7@††¶7ñÊ2FVb˜'VÁvïˆFó&V7Eˆ˜&uˆñÊfÚÇí”‚GW∆U∂&ˆˆ¬¬7G%”†¢""%&VB÷ˆÊ«íˆffñ6ñ¬'VÁvíWFÜVÁFñ6Fñˆ‚¬˜&vÊó¶Fñˆ‚ÊB7&VFóB6ÜV6≤‚"" ¢ñbÊ˜BÖ%TÂtïÙDï$T5EÙT‰$ƒTBÊB%TÂtïÙïÙ¥Uíì†¢&WGW&‚f«6R¬%%TÂtî‘≈Ùïı4T5$UB›R›ùM]“›Ç"&VÊFW"VÁfó&ˆÊ÷VÁB¬›Ç"6V7&WBfñ∆W2‚ ¢f˜&÷Eˆˆ≤¬f˜&÷EˆÊ˜FR“'VÁvïˆ∂Wïˆf˜&÷EˆÜñÁBÖ%TÂtïÙïÙ¥Uíê¢6˜W&6UˆÊ÷R“%TÂtïÙ¥Uïı4ıU$4P¢G'ì†¢7ñÊ2vóFÇ˜'VÁvïˆˆffñ6ñ≈ˆ6∆ñVÁBÇí2's†¢˜&r“vóB'rÊ˜&vÊó¶Fñˆ‚ÜVÊGˆñÁC’%TÂtïÙı$t‰ï§DîÙÂıDÇê¢ñ∆ˆB“˜&rÊvWBÇ&FF"íñbó6ñÁ7FÊ6RÜ˜&rÊvWBÇ&FF"í¬Fñ7BíV«6R˜&p¢7&VFóG2“ÊWáBÇáñ∆ˆBÊvWBÜ≤íf˜"≤ñ‚Ç&7&VFóD&∆Ê6R"¬&7&VFóG2"¬&&∆Ê6R"¬&fñ∆&∆T7&VFóG2"íñb≤ñ‚ñ∆ˆBí¬ÊˆÊRê¢FñW"“ÊWáBÇáñ∆ˆBÊvWBÜ≤íf˜"≤ñ‚Ç'FñW""¬'W6vUFñW""¬'&FT∆ñ÷óEFñW""íñb≤ñ‚ñ∆ˆBí¬ÊˆÊRê¢'G2“∞¢-≠ΩÌr˝ç›˝""¿¢b-˝]]Õ]››Û¢∑6˜W&6UˆÊ÷W“"¿¢b&fñÊvW'&ñÁC¢∑'VÁvï˜6fUˆ∂WïˆfñÊvW'&ñÁBÖ%TÂtïÙïÙ¥Uíó“"¿¢f˜&÷EˆÊ˜FR¿¢–¢ñb7&VFóG2ó2Ê˜BÊˆÊS†¢'G2ÊVÊBÜb$í›≠]Mç-≥¢∂7&VFóG7“"ê¢ñbFñW"ó2Ê˜BÊˆÊS†¢'G2ÊVÊBÜb'FñW#¢∑FñW'“"ê¢&WGW&‚G'VR¬%∆‚"Ê¶ˆñ‚á'G2ê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ%'VÁví˜&vÊó¶Fñˆ‚WFÇfñ∆VC¢W2"¬Rê¢&WGW&‚f«6R¬˜'VÁvï˜W6W%ˆW'&˜%˜FWáBÜRí≤b%∆‰fñÊvW'&ñÁC¢∑'VÁvï˜6fUˆ∂WïˆfñÊvW'&ñÁBÖ%TÂtïÙïÙ¥Uíó“ †¢2csb&˜fñFW"6ó&7VóB'&V∂W"ÚÜV«FÇ66ÜP•˜&˜fñFW%ˆfñ≈ˆ6˜VÁG3¢Fñ7E∑7G"¬ñÁE““∑–•˜&˜fñFW%ˆ6ˆˆ∆F˜vÂ˜VÁFñ√¢Fñ7E∑7G"¬f∆ˆE““∑–•˜&˜fñFW%ˆ∆7EˆW'&˜#¢Fñ7E∑7G"¬7G%““∑–†¶FVb˜&˜fñFW%ˆó5ˆfñ∆&∆RÜÊ÷S¢7G"í”‚&ˆˆ√†¢&WGW&‚Fñ÷RÁFñ÷RÇí„“f∆ˆBÖ˜&˜fñFW%ˆ6ˆˆ∆F˜vÂ˜VÁFñ¬ÊvWBÜÊ÷R¬í˜"ê†¶FVb˜&˜fñFW%ˆ6ˆˆ∆F˜vÂˆ∆VgBÜÊ÷S¢7G"í”‚ñÁC†¢&WGW&‚÷ÇÉ¬ñÁBÜf∆ˆBÖ˜&˜fñFW%ˆ6ˆˆ∆F˜vÂ˜VÁFñ¬ÊvWBÜÊ÷R¬í˜"í“Fñ÷RÁFñ÷RÇííê†¶FVb˜&˜fñFW%ˆ÷&µ˜7V66W72ÜÊ÷S¢7G"í”‚ÊˆÊS†¢˜&˜fñFW%ˆfñ≈ˆ6˜VÁG5∂Ê÷U““ ¢˜&˜fñFW%ˆ6ˆˆ∆F˜vÂ˜VÁFñ¬Á˜ÜÊ÷R¬ÊˆÊRê¢˜&˜fñFW%ˆ∆7EˆW'&˜"Á˜ÜÊ÷R¬ÊˆÊRê†¶FVb˜&˜fñFW%ˆ÷&µˆfñ«W&RÜÊ÷S¢7G"¬&V6ˆ„¢7G"“""í”‚ÊˆÊS†¢˜&˜fñFW%ˆ∆7EˆW'&˜%∂Ê÷U““á&V6ˆ‚˜"""ï≥£s–¢‚“ñÁBÖ˜&˜fñFW%ˆfñ≈ˆ6˜VÁG2ÊvWBÜÊ÷R¬í˜"í≤¢˜&˜fñFW%ˆfñ≈ˆ6˜VÁG5∂Ê÷U““‡¢ñb‚„“÷ÇÉ¬%TÂtïı$ıdîDU%Ùdî≈ıDÖ$U4ÑÙƒBì†¢˜&˜fñFW%ˆ6ˆˆ∆F˜vÂ˜VÁFñ≈∂Ê÷U““Fñ÷RÁFñ÷RÇí≤÷ÇÉ3¬%TÂtïı$ıdîDU%Ù4ÙÙƒDıtÂı2ê†¶FVb˜&˜fñFW%˜&W6WBÜÊ÷S¢7G"í”‚ÊˆÊS†¢˜&˜fñFW%ˆfñ≈ˆ6˜VÁG2Á˜ÜÊ÷R¬ÊˆÊRê¢˜&˜fñFW%ˆ6ˆˆ∆F˜vÂ˜VÁFñ¬Á˜ÜÊ÷R¬ÊˆÊRê¢˜&˜fñFW%ˆ∆7EˆW'&˜"Á˜ÜÊ÷R¬ÊˆÊRê†¶FVbˆó5˜'VÁvï˜VÊfñ∆&∆U˜FWáBá3¢7G"í”‚&ˆˆ√†¢B“á2˜"""íÊ∆˜vW"Çê¢ÊVVF∆W2“Ä¢&÷ˆFV≈ˆÊ˜Eˆf˜VÊB"¬&ÊÚfñ∆&∆R6ÜÊÊV¬"¬&ñÁf∆ñBW&¬"¿¢.j⁄NjäYËæ[{.KàæiÎb"¬&÷ˆFV¬Ü2&VV‚&V÷˜fVB"¬&÷ˆFV¬ó2&V÷˜fVB"¿¢&Ê˜Bf˜VÊB"¬&6ÜÊÊV¬"¬&ñÁf∆ñE˜&WVW7EˆW'&˜" ¢ê¢&WGW&‚ÁíáÇñ‚Bf˜"Çñ‚ÊVVF∆W2ê†¶FVbˆ∆ˆˆ∑5ˆ∆ñ∂U˜67&VVÁ6Ü˜Eˆ˜%ˆ&Eˆì'e˜6˜W&6RÜñ÷uˆ'óFW3¢'óFW2í”‚7G#†¢""%6ˆgBÜWW&ó7Fñ2ˆÊ«ì¢v&‚W6W"ñbñÁWB∆ˆˆ∑2∆ñ∂RÜˆÊR67&VVÁ6Ü˜Bˆg&÷R‚"" ¢ñbñ÷vRó2ÊˆÊS†¢&WGW&‚" ¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2ííÊ6ˆÁfW'BÇ%$t""ê¢r¬Ç“ñ“Á6ó¶P¢2	Ì}]›¬-ΩÌ≠çí˝ççÌ≠çí≠M}ùR-]=‚˝-Ω˝]-Ú≠ç›çÌ-Ì¬-]Ω]MÌ›˝›≠›‡¢ñbÇ‚r¢„SR˜"r‚Ç¢„SS†¢&WGW&‚-
MÌ-‚˝Ì]ÌmR›≠ç›çÌ"˝≠MÌΩÕççÕÇ˝ÌΩ˝ÕÇ‚	MΩÚΩ=}ç]=‚Ìmç-Ω]›çÚ}==}ç-R}ç-Ωí˝Ì-]"]rç›-]M]ù-]Ω]MÌ›Ç}›ΩRÕÌ¢‚ ¢2	ÌΩÕççR-Õ›ΩRÌΩ-Ç˝‚≠˝¬(	B}-Ωí˝ç}›¢MÌ-‚›≠›˝-çM]‚›˝Ω]]‡¢G'ì†¢6÷∆¬“ñ“Á&W6ó¶RÇÉcB¬cBíê¢Ç“∆ó7Bá6÷∆¬ÊvWFFFÇíê¢F&≤“7V“Éf˜""¬r¬"ñ‚Çñb÷Çá"¬r¬"í¬3"íÚ÷ÇÉ¬∆V‚áÇíê¢ñbF&≤‚„3S†¢&WGW&‚-	"≠MRÕ›Ì=‚}›ΩR˝ÌΩ]í˝›Ω]Õ]›-Ì"ç›-]M]ù‚	ÕÌM]Ω¬ÕÌm]"Ìmç-ç-¬Õ≠2çΩÇ›≠“-Õ]-‚}]ΩÌ-]≠‚	Ω=}çR}==}ç-¬}ç-ÌRMÌ-‚‚ ¢WÜ6WBWÜ6WFñˆ„†¢70¢WÜ6WBWÜ6WFñˆ„†¢&WGW&‚" ¢&WGW&‚" †¶FVb˜&W&Uˆì'e˜6˜W&6Uˆñ÷vRÜñ÷uˆ'óFW3¢'óFW2¬7V7C¢7G"“#ì£b"í”‚GW∆U∂'óFW2¬7G%”†¢"" ¢&ˆGV7Fñˆ‚◊6fR&W&Fñˆ‚f˜"ñ÷v^(i'fñFVÚ&˜fñFW'2‡¢	-Ì}-ù]"Ü'óFW2¬Ê˜FRí‚	›RM]Ω]"=]ç-›Ωíf6R÷7&˜¬}-Ì≤›Rç˝Ì-ç-¬MÌ-‚¿¢›‚=ç]"˝-›ΩR}›ΩRÕ≠ÇÇ›ÌÕΩç}=]"}Õ]˝MÌÕ"‡¢"" ¢ñbÊ˜Bì%eı$U$Ù4U55ÙT‰$ƒTB˜"ñ÷vRó2ÊˆÊS†¢&WGW&‚ñ÷uˆ'óFW2¬" ¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2ííÊ6ˆÁfW'BÇ%$t""ê¢r¬Ç“ñ“Á6ó¶P¢Ê˜FU˜'G2“µ–†¢2í
=MΩ]›çR˝-›ΩR}›ΩRÕÌ¢‚	›R-Ì=]¬¬]ΩÇ7&˜Ωçç≠Ì¬Õ≤˝ç≠Ì-››Ωí‡¢ñbì%eÙUDÙ5$ıÙ$ƒ4µÙ$ı$DU%2ÊB÷ñ‚ár¬Çí„“#†¢w&í“ñ“Ê6ˆÁfW'BÇ$¬"ê¢2	˝ç≠]ΩÇ˝}R˝ÌÌ=}ç-]¬ÌM]mçÕΩ¬‡¢÷6≤“w&íÁˆñÁBÜ∆÷&F¢#SRñb‚#ÇV«6Rê¢&&˜Ç“÷6≤ÊvWF&&˜ÇÇê¢ñb&&˜É†¢É¬ì¬É"¬ì"“&&˜Ä¢'r¬&Ç“É"“É¬ì"“ì¢&V˜&FñÚ“Ü'r¢&ÇíÚ÷ÇÉ¬r¢Çê¢27&˜-ÌΩÕ≠‚]ΩÇÌ“}Õ]-›‚=ç]"≠Ú¬›‚›R˝]-ù]"≠-ç›≠2"≠Ìç]}›ΩíM=Õ]› ¢÷&vñÂ˜&V÷˜fVB“áÉ‚r¢„B˜"ì‚Ç¢„B˜"É"¬r¢„ìb˜"ì"¬Ç¢„ìbê¢ñb÷&vñÂ˜&V÷˜fVBÊB„#√“&V˜&FñÚ√“„ìc†¢B“ñÁBÜ÷ÇÜ'r¬&Çí¢„Bê¢É“÷ÇÉ¬É“Bì≤ì“÷ÇÉ¬ì“Bê¢É"“÷ñ‚ár¬É"≤Bì≤ì"“÷ñ‚ÜÇ¬ì"≤Bê¢ñ““ñ“Ê7&˜ÇáÉ¬ì¬É"¬ì"íê¢r¬Ç“ñ“Á6ó¶P¢Ê˜FU˜'G2ÊVÊBÇ-=≤Ωçç›çR-Õ›ΩR˝ÌΩÚ"ê†¢2"í	›ÌÕΩç}mçÚ}Õ]¬}-Ì≤›RÌ-˝-Ω˝-¬Ì=ÌÕ›ΩR≠ç›çÌ-≤˝Ì-ùM]¬‡¢÷Ö˜6ñFR“÷ÇÉS"¬ñÁBÑì%eÙ‘Öı4ıU$4Uı4îDR˜"#Éíê¢ñb÷Çár¬Çí‚÷Ö˜6ñFS†¢ñ“ÁFáV÷&Êñ¬ÇÜ÷Ö˜6ñFR¬÷Ö˜6ñFRí¬vWFGG"Ññ÷vR¬%&W6◊∆ñÊr"¬ñ÷vRí‰ƒ‰5§ı2ê¢Ê˜FU˜'G2ÊVÊBÜb-m≤ç]ÌM›ç¢M‚∂÷Ö˜6ñFW◊Ç"ê†¢˜WB“'óFW4îÚÇê¢ñ“Á6fRÜ˜WB¬f˜&÷C“$•Tr"¬V∆óGì”ì"¬˜Fñ÷ó¶S’G'VRê¢&WGW&‚˜WBÊvWGf«VRÇí¬"¬"Ê¶ˆñ‚ÜÊ˜FU˜'G2ê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ&ì'b6˜W&6R&W&ˆ6W72fñ∆VC¢W2"¬Rê¢&WGW&‚ñ÷uˆ'óFW2¬" †¶7ñÊ2FVb˜'VÂ˜'VÁvï˜fñFVÚáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬&ˆ◊C¢7G"¬GW&FñˆÂ˜3¢ñÁB¬7V7C¢7G"ì†¢""%&ˆGV7Fñˆ‚'VÁvíFWáN(i'fñFVÛ¢ˆffñ6ñ¬ífó'7B¬6ˆ÷WB6V6ˆÊB¬∂∆ñÊrf∆∆&6≤‡†¢ˆffñ6ñ¬&˜WFRfˆ∆∆˜w27W'&VÁB'VÁvíFˆ7V÷VÁFFñˆ„†¢ı5B˜c˜FWáE˜Fı˜fñFVÚ”‚tUB˜c˜F6∑2˜∂ñG“‡¢f˜"&6∑v&G26ˆ◊Fñ&ñ∆óGíˆÊ«í¬CBÛCR6‚f∆¬&6≤F¢˜cˆñ÷vU˜Fı˜fñFVÚvóFÜ˜WB&ˆ◊Dñ÷vR‡¢"" ¢vóB6ˆÁFWáBÊ&˜BÁ6VÊEˆ6ÜEˆ7Fñˆ‚áWFFRÊVffV7FófUˆ6ÜBÊñB¬6ÜD7Fñˆ‚Â$T4ı$EıdîDTÚê¢&ˆ◊B“á&ˆ◊B˜"""íÁ7G&óÇê¢ñbÊ˜B&ˆ◊C†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬'VÁvì¢˝=-Ìí}˝ÌMΩÚ-çM]‚‚"ê¢&WGW&‚f«6P†¢GW&Fñˆ‚“÷ÇÉ"¬÷ñ‚É¬ñÁBÖˆGW&FñˆÂˆf˜%ˆVÊvñÊRÇ''VÁví"¬GW&FñˆÂ˜2íííê¢&FñÚ“˜'VÁvïˆFó&V7E˜&FñÚÜ7V7Bê¢W'&˜'3¢∆ó7E∑7G%““µ–¢Ü&E˜7F˜“f«6P†¢7ñÊ2FVbG'ïˆFó&V7BÇí”‚&ˆˆ√†¢ÊˆÊ∆ˆ6¬Ü&E˜7F˜ ¢ñbÊ˜BÖ%TÂtïÙDï$T5EÙT‰$ƒTBÊB%TÂtïÙïÙ¥Uíì†¢&WGW&‚f«6P¢G'ì†¢7ñÊ2vóFÇ˜'VÁvïˆˆffñ6ñ≈ˆ6∆ñVÁBÇí2's†¢F6µˆñB“vóB'rÊ7&VFU˜FWáE˜Fı˜fñFVÚÄ¢&ˆ◊E˜FWáC◊&ˆ◊B¿¢÷ˆFV√’˜'VÁvïˆFó&V7E˜FWáEˆ÷ˆFV≈ˆ6ÊFñFFW2Çï≥“¿¢&FñÛ◊&FñÚ¿¢GW&Fñˆ„÷GW&Fñˆ‚¿¢VÊGˆñÁC’%TÂtïıDUÖEÙ5$TDUıDÇ¿¢6ˆ◊Fñ&ñ∆óGïˆVÊGˆñÁC’%TÂtïıDUÖEÙ4Ù’EıDÇ¿¢ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b.(˚2'VÁvívV‚”B„S¢}M}˝ç›˝-á∂GW&FñˆÁ“¬∂7V7G“í‚	ÌmçM‚]}=ΩÕ-.(
b ¢ê¢&W7V«B“vóB'rÁvóEˆf˜%˜F6≤áF6µˆñB¬Fñ÷V˜WE˜3’%TÂtïÙ‘ÖıtïEı2ê†¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC”#C„¬fˆ∆∆˜u˜&VFó&V7G3’G'VRí2F≈ˆ6∆ñVÁC†¢vóB˜&W«ï˜fñFVıˆg&ˆ’˜W&¬Ä¢WFFR¬F≈ˆ6∆ñVÁB¬&W7V«BÊfó'7Eˆ˜WGWB¿¢%'VÁvíFWáN(i'fñFVÚ)»R+r˜vW&VB'í'VÁví"¿¢F6µˆñC◊F6µˆñB¿¢ê¢˜&˜fñFW%ˆ÷&µ˜7V66W72Ç''VÁvïˆFó&V7B"ê¢&WGW&‚G'VP¢WÜ6WB'VÁvîîW'&˜"2S†¢W'&˜'2ÊVÊBá7G"ÜRíì≤˜&˜fñFW%ˆ÷&µˆfñ«W&RÇ''VÁvïˆFó&V7B"¬7G"ÜRíê¢∆ˆrÁv&ÊñÊrÇ$ˆffñ6ñ¬'VÁvíFWáB◊FÚ◊fñFVÚfñ∆VC¢W2"¬Rê¢6ˆFR“ÜRÊfñ«W&Uˆ6ˆFR˜"""íÁWW"Çê¢ñb6ˆFRÁ7F'G7vóFÇÇ%4dUEí"í˜"RÁ7FGW5ˆ6ˆFRñ‚≥C¬C¬C2¬C'”†¢Ü&E˜7F˜“G'VP¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÖ˜'VÁvï˜W6W%ˆW'&˜%˜FWáBÜRíê¢&WGW&‚f«6P¢WÜ6WBWÜ6WFñˆ‚2S†¢W'&˜'2ÊVÊBá7G"ÜRíì≤˜&˜fñFW%ˆ÷&µˆfñ«W&RÇ''VÁvïˆFó&V7B"¬7G"ÜRíê¢∆ˆrÊWÜ6WFñˆ‚Ç$ˆffñ6ñ¬'VÁvíFWáB&˜WFRfñ∆VC¢W2"¬Rê¢&WGW&‚f«6P†¢7ñÊ2FVbG'ïˆ6ˆ÷WBÇí”‚&ˆˆ√†¢&˜fñFW%ˆÊ÷R“''VÁvï˜FWáEˆ6ˆ÷WB ¢ñbÊ˜BÖ%TÂtïıU4UÙ4Ù‘UBÊB4Ù‘UEÙïÙ¥Uíì†¢&WGW&‚f«6P¢ñbÊ˜B˜&˜fñFW%ˆó5ˆfñ∆&∆Rá&˜fñFW%ˆÊ÷Rì†¢∆ˆrÁv&ÊñÊrÇ%'VÁvíFWáBÙ6ˆ÷WB6∂óVC¢6ˆˆ∆F˜v‚W72"¬˜&˜fñFW%ˆ6ˆˆ∆F˜vÂˆ∆VgBá&˜fñFW%ˆÊ÷Ríê¢&WGW&‚f«6P¢ÜVFW'2“∞¢$WFÜ˜&ó¶Fñˆ‚#¢b$&V&W"¥4Ù‘UEÙïÙ¥Uó“"¿¢$66WB#¢&∆ñ6Fñˆ‚ˆß6ˆ‚"¿¢$6ˆÁFVÁB’GóR#¢&∆ñ6Fñˆ‚ˆß6ˆ‚"¿¢%Ç’'VÁví’fW'6ñˆ‚#¢%TÂtïÙïıdU%4îÙ‚˜"###B””b"¿¢–¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC”ì„í26∆ñVÁC†¢f˜"÷ˆFV¬ñ‚˜'VÁvïˆ6ˆ÷WE˜FWáEˆ÷ˆFV≈ˆ6ÊFñFFW2Çì†¢ñ∆ˆB“≤&÷ˆFV¬#¢÷ˆFV¬¬'&ˆ◊EFWáB#¢&ˆ◊B¬&GW&Fñˆ‚#¢GW&Fñˆ‚¬'&FñÚ#¢&Fñ˜–¢G'ì†¢"“vóB6∆ñVÁBÁ˜7BÜb'¥4Ù‘UEÙ$4UıU$«◊µ%TÂtïÙ4Ù‘UEÙ5$TDUıDá“"¬ÜVFW'3÷ÜVFW'2¬ß6ˆ„◊ñ∆ˆBê¢ñb"Á7FGW5ˆ6ˆFR„“C†¢W'"“b$6ˆ÷WB'VÁví∑"Á7FGW5ˆ6ˆFW”¢µˆïˆW'&˜%˜&WfñWrá"ó“ ¢W'&˜'2ÊVÊBÜW'"ì≤∆ˆrÁv&ÊñÊrÜW'"ê¢ñbˆó5˜'VÁvï˜VÊfñ∆&∆U˜FWáBÜW'"í˜""Á7FGW5ˆ6ˆFR”“S3†¢˜&˜fñFW%ˆ÷&µˆfñ«W&Rá&˜fñFW%ˆÊ÷R¬W'"ê¢'&V∞¢6ˆÁFñÁVP¢ß2“"Êß6ˆ‚Çí˜"∑–¢&VGï˜W&¬“ˆWáG&7Eˆfó'7E˜W&¬Üß2ÊvWBÇ&˜WGWB"íí˜"ˆWáG&7Eˆfó'7E˜W&¬Üß2ÊvWBÇ&FF"íí˜"ˆWáG&7Eˆfó'7E˜W&¬Üß2ê¢ñb&VGï˜W&√†¢˜&˜fñFW%ˆ÷&µ˜7V66W72á&˜fñFW%ˆÊ÷Rê¢vóB˜&W«ï˜fñFVıˆg&ˆ’˜W&¬áWFFR¬6∆ñVÁB¬&VGï˜W&¬¬%'VÁvíÙ6ˆ÷WBFWáN(i'fñFVÚ)»R+r˜vW&VB'í'VÁví"ê¢&WGW&‚G'VP¢F6µˆñB“7G"Üß2ÊvWBÇ&ñB"í˜"ß2ÊvWBÇ'F6µˆñB"í˜"ß2ÊvWBÇ&vVÊW&FñˆÂˆñB"í˜"ÇÜß2ÊvWBÇ&FF"í˜"∑“íÊvWBÇ&ñB"íñbó6ñÁ7FÊ6RÜß2ÊvWBÇ&FF"í¬Fñ7BíV«6R""í˜"""íÁ7G&óÇê¢ñbÊ˜BF6µˆñC†¢W'"“b$6ˆ÷WB'VÁvì¢ÊÚF6≤ñC¢∂ß6ˆ‚ÊGV◊2Üß2¬VÁ7W&Uˆ66ñì‘f«6Rï≥£S◊“ ¢W'&˜'2ÊVÊBÜW'"ì≤˜&˜fñFW%ˆ÷&µˆfñ«W&Rá&˜fñFW%ˆÊ÷R¬W'"ê¢6ˆÁFñÁVP¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.(˚2'VÁvíÙ6ˆ÷WC¢}M}˝ç›˝-¬ÌmçM‚]}=ΩÕ-.(
b"ê¢ˆ≤“&ˆˆ¬ÜvóB˜ˆ∆≈˜fñFVı˜F6µˆvVÊW&ñ2Ä¢WFFR¬6∆ñVÁB¬ÜVFW'2¬4Ù‘UEÙ$4UıU$¬¿¢µ%TÂtïÙ4Ù‘UEı5DEU5ıDÇ¬"˜'VÁvñ÷¬˜c˜F6∑2˜∂ñG“"¬"˜c˜F6∑2˜∂ñG“%“¿¢F6µˆñB¬%'VÁvíÙ6ˆ÷WBFWáN(i'fñFVÚ+r˜vW&VB'í'VÁví"¬%TÂtïÙ‘ÖıtïEı2¿¢íê¢ñbˆ≥†¢˜&˜fñFW%ˆ÷&µ˜7V66W72á&˜fñFW%ˆÊ÷Rê¢V«6S†¢˜&˜fñFW%ˆ÷&µˆfñ«W&Rá&˜fñFW%ˆÊ÷R¬'ˆ∆∆ñÊrfñ∆VB"ê¢&WGW&‚ˆ∞¢WÜ6WBWÜ6WFñˆ‚2S†¢W'"“b$6ˆ÷WB'VÁvíWÜ6WFñˆ„¢∂W“ ¢W'&˜'2ÊVÊBÜW'"ì≤∆ˆrÁv&ÊñÊrÜW'"ì≤˜&˜fñFW%ˆ÷&µˆfñ«W&Rá&˜fñFW%ˆÊ÷R¬W'"ê¢&WGW&‚f«6P†¢&˜WFW2“áG'ïˆFó&V7B¬G'ïˆ6ˆ÷WBíñb%TÂtïÙDï$T5EÙdï%5BV«6RáG'ïˆ6ˆ÷WB¬G'ïˆFó&V7Bê¢f˜"&˜WFRñ‚&˜WFW3†¢ñbÜ&E˜7F˜†¢&WGW&‚f«6P¢G'ì†¢ñbvóB&˜WFRÇì†¢&WGW&‚G'VP¢WÜ6WBWÜ6WFñˆ‚2S†¢W'&˜'2ÊVÊBá7G"ÜRíì≤∆ˆrÊWÜ6WFñˆ‚Ç%'VÁvíFWáB&˜WFRfñ∆VC¢W2"¬Rê†¢ñbÜ&E˜7F˜†¢&WGW&‚f«6P†¢ñb%TÂtïıDUÖEÙdƒƒ$4µÙ¥ƒî‰rÊB%TÂtïÙUDıÙdƒƒ$4µÙ¥ƒî‰rÊB4Ù‘UEÙïÙ¥Uì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÖ%TÂtïıT$ƒî5Ùdƒƒ$4µıDUÖBê¢G'ì†¢&WGW&‚&ˆˆ¬ÜvóB˜'VÂˆ6ˆ÷WE˜FWáE˜fñFVÚáWFFR¬6ˆÁFWáB¬&∂∆ñÊr"¬&ˆ◊B¬GW&Fñˆ‚¬7V7Bíê¢WÜ6WBWÜ6WFñˆ‚2S†¢W'&˜'2ÊVÊBÜb$∂∆ñÊrf∆∆&6≥¢∂W“"ì≤∆ˆrÊWÜ6WFñˆ‚Ç%'VÁvû(i$∂∆ñÊrf∆∆&6≤fñ∆VC¢W2"¬Rê†¢ñb%TÂtïÙÑîDUıDT4ÖÙU%$ı%3†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)™˚àÚ'VÁví]ù}›R˝ç›˝≤}M}2‚	≠]Mç-≤}›]=˝]ç›=‚=]›]mç‚›R˝çΩ-Ì-Ú‚ ¢-	˝Ì-]Õ-RˆFñu˜'VÁvíWFÇçΩÇ-Ω]ç-R∂∆ñÊr‚ ¢ê¢V«6S†¢FWFñ«2“%∆‚"Ê¶ˆñ‚ÜW'&˜'5≤”3•“í˜"$í›R-]›=≤˝ÌMÌ›Ì-Ç‚ ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb.)ÿ¬'VÁvì¢}M}›R-Ω˝ÌΩ›]›Â∆Á∂FWFñ«5≥£c◊“"ê¢&WGW&‚f«6P†¢2)H)H)H)H)H)H)H)H)Hñ÷v^(i%fñFVÚÜV«W'2)H)H)H)H)H)H)H)H)H ¶FVbˆïˆW'&˜%˜&WfñWrá&W7¬∆ñ÷óC¢ñÁB“ìí”‚7G#†¢G'ì†¢&ˆGí“ß6ˆ‚ÊGV◊2á&W7Êß6ˆ‚Çí¬VÁ7W&Uˆ66ñì‘f«6Rê¢WÜ6WBWÜ6WFñˆ„†¢&ˆGí“vWFGG"á&W7¬'FWáB"¬""í˜"" ¢&ˆGí“&RÁ7V"á"%«2≤"¬""¬&ˆGííÁ7G&óÇê¢&WGW&‚&ˆGï≥¶∆ñ÷óE“ñb&ˆGíV«6R-]r-]ΩÌ--]- ††¶FVb˜6˜&˜V˜∆Uˆ÷ˆFW&FñˆÂ˜FWáBÇí”‚7G#†¢&WGW&‚Ä¢.)™˚àÚ6˜&"}ΩÌ≠çÌ-Ω›-‚ç}Ìm]›çR›ÕÌM]mçÇ¬˝Ì-ÌÕ2}-‚›MÌ-‚]-¬}]ΩÌ-]¢˝ΩÌMÇÂ∆Â∆‚ ¢-
›-‚Ì=›ç}]›çR6˜&Ù6ˆ÷WB¬›RÌçç≠M]˝ΩÌÚÇ›RÌçç≠≠ΩÌ}Â∆Â∆‚ ¢-	MΩÚÌmç-Ω]›çÚMÌ-‚ΩÌMÕÕÇç˝ÌΩÕ}=ù-S•∆‚ ¢.(
") Ç	Ìmç-ç-¬Ö'VÁvíï∆‚ ¢.(
") Ç	Ìmç-ç-¬Ñ∂∆ñÊrï∆Â∆‚ ¢%6˜&"Ì--Ω]›MΩÚç}Ìm]›çí]rΩÌM]ì¢˝]MÕ]-≤¬mç-Ì-›ΩR¬}M›çÚ¬˝]ù}mÇ¬ç›-]Õ]‚ ¢ê††¶FVbó5˜6˜&˜V˜∆Uˆ÷ˆFW&FñˆÂˆW'&˜"ÜW'#¢ˆ&¶V7Bí”‚&ˆˆ√†¢G'ì†¢FWáB“ß6ˆ‚ÊGV◊2ÜW'"¬VÁ7W&Uˆ66ñì‘f«6RíÊ∆˜vW"Çê¢WÜ6WBWÜ6WFñˆ„†¢FWáB“7G"ÜW'"íÊ∆˜vW"Çê¢&WGW&‚Ä¢'V˜∆R÷ñ‚◊W6W"◊W∆ˆG2"ñ‚FWá@¢˜"&&∆ˆ6∂VB'í˜W"÷ˆFW&Fñˆ‚7ó7FV“"ñ‚FWá@¢˜"Ç&÷ˆFW&Fñˆ‚7ó7FV“"ñ‚FWáBÊB'6˜&"ñ‚FWáBê¢˜"Ç'&WVW7Bó2&∆ˆ6∂VB"ñ‚FWáBÊB'V˜∆R"ñ‚FWáBê¢ê†¶FVbˆWáG&7Eˆfó'7E˜W&¬Üˆ&¢í”‚7G"¬ÊˆÊS†¢ñbó6ñÁ7FÊ6RÜˆ&¢¬7G"ì†¢ñbˆ&¢Á7F'G7vóFÇÇ&áGG¢ÚÚ"í˜"ˆ&¢Á7F'G7vóFÇÇ&áGG3¢ÚÚ"ì†¢&WGW&‚ˆ&†¢&WGW&‚ÊˆÊP¢ñbó6ñÁ7FÊ6RÜˆ&¢¬Fñ7Bì†¢&VfW'&VB“Ç'fñFVÚ"¬'fñFVı˜W&¬"¬&˜WGWE˜W&¬"¬'W&¬"¬&F˜vÊ∆ˆE˜W&¬"¬&fñ∆R"¬&76WE˜W&¬"ê¢f˜"≤ñ‚&VfW'&VC†¢ñb≤ñ‚ˆ&£†¢f˜VÊB“ˆWáG&7Eˆfó'7E˜W&¬Üˆ&¢ÊvWBÜ≤íê¢ñbf˜VÊC†¢&WGW&‚f˜VÊ@¢f˜"bñ‚ˆ&¢Áf«VW2Çì†¢f˜VÊB“ˆWáG&7Eˆfó'7E˜W&¬ábê¢ñbf˜VÊC†¢&WGW&‚f˜VÊ@¢ñbó6ñÁ7FÊ6RÜˆ&¢¬Ü∆ó7B¬GW∆Ríì†¢f˜"óFV“ñ‚ˆ&£†¢f˜VÊB“ˆWáG&7Eˆfó'7E˜W&¬ÜóFV“ê¢ñbf˜VÊC†¢&WGW&‚f˜VÊ@¢&WGW&‚ÊˆÊP†††¶FVbˆ6∆VÁW˜6VÁE˜fñFVıˆ∂Wó2Çì†¢Ê˜r“Fñ÷RÁFñ÷RÇê¢7F∆R“∂≤f˜"≤¬G2ñ‚ı4TÂEıdîDTıÙ¥Uï2ÊóFV◊2ÇíñbÜÊ˜r“G2í‚dîDTıı$U5T≈EÙDTEUUıED≈ı5–¢f˜"≤ñ‚7F∆S†¢ı4TÂEıdîDTıÙ¥Uï2Á˜Ü≤¬ÊˆÊRê††¶FVbˆ÷&µ˜fñFVı˜6VÁEˆˆÊ6RÜ∂Wì¢7G"í”‚&ˆˆ√†¢ñbÊ˜B∂Wì†¢&WGW&‚f«6P¢ˆ6∆VÁW˜6VÁE˜fñFVıˆ∂Wó2Çê¢ñb∂Wíñ‚ı4TÂEıdîDTıÙ¥Uï3†¢&WGW&‚G'VP¢ı4TÂEıdîDTıÙ¥Uï5∂∂Wï““Fñ÷RÁFñ÷RÇê¢&WGW&‚f«6P††¶FVb˜fñFVı˜&W7V«Eˆ∂WíÜ6ÜEˆñC¢ñÁB¬7G"¬F6µˆñC¢7G"“""¬W&√¢7G"“""¬6ˆÁFVÁC¢'óFW2¬ÊˆÊR“ÊˆÊRí”‚7G#†¢&6R“b'∂6ÜEˆñG◊«∑F6µˆñB˜"rw◊«∑W&¬˜"rw“ ¢ñb6ˆÁFVÁC†¢G'ì†¢FñvW7B“Ü6Ü∆ñ"Á6ÜÜ6ˆÁFVÁBíÊÜWÜFñvW7BÇê¢WÜ6WBWÜ6WFñˆ„†¢FñvW7B“" ¢&6R≥“b'«∂FñvW7G“ ¢&WGW&‚&6P††¶FVbˆ6ˆ◊&W75˜fñFVıˆf˜%˜FV∆Vw&’˜7ñÊ2áfñFVıˆ'óFW3¢'óFW2¬÷Öˆ÷#¢ñÁB“CÇí”‚'óFW2¬ÊˆÊS†¢""%&R÷VÊ6ˆFR&˜fñFW"’BFÚFV∆Vw&“◊6fRFˆ7V÷VÁB˜fñFVÚ6ó¶R‡¢W6VBˆÊ«í2f∆∆&6≤vÜV‚FV∆Vw&“&V¶V7G2FÜR˜&ñvñÊ¬fñ∆R˜"óBó2FˆÚ∆&vR‡¢"" ¢ñbÊ˜BfñFVıˆ'óFW3†¢&WGW&‚ÊˆÊP¢÷Öˆ'óFW2“÷ÇÉR¬ñÁBÜ÷Öˆ÷"˜"CÇíí¢#B¢#@¢G'ì†¢ff◊Vr“ˆff◊VuˆWÜRÇê¢vóFÇFV◊fñ∆RÂFV◊˜&'îFó&V7F˜'íÇí2FC†¢7&2“˜2ÁFÇÊ¶ˆñ‚áFB¬&ñÁWBÊ◊B"ê¢˜WB“˜2ÁFÇÊ¶ˆñ‚áFB¬'Fu˜6fRÊ◊B"ê¢vóFÇ˜V‚á7&2¬'v""í2c†¢bÁw&óFRáfñFVıˆ'óFW2ê¢6÷B“∞¢ff◊Vr¬"◊í"¬"÷ÜñFUˆ&ÊÊW""¬"÷∆ˆv∆WfV¬"¬&W'&˜""¿¢"÷í"¬7&2¿¢"◊fb"¬'66∆S“v÷ñ‚És#∆órís¢”"∆g3”#B"¿¢"÷3ßb"¬&∆ñ'É#cB"¬"◊&W6WB"¬'V«G&f7B"¬"÷7&b"¬#3B"¬"◊óÖˆf◊B"¬'óWcC#"¿¢"÷3¶"¬&2"¬"÷#¶"¬#ìf≤"¿¢"÷÷˜ff∆w2"¬"∂f7G7F'B"¿¢˜WB¿¢–¢&W2“7V'&ˆ6W72Á'V‚Ü6÷B¬7FF˜WC◊7V'&ˆ6W72ÂïR¬7FFW'#◊7V'&ˆ6W72ÂïR¬Fñ÷V˜WC”Éê¢ñb&W2Á&WGW&Ê6ˆFR“†¢∆ˆrÁv&ÊñÊrÇ'FV∆Vw&“fñFVÚ6ˆ◊&W72fñ∆VB&3“W2W'#“W2"¬&W2Á&WGW&Ê6ˆFR¬&W2Á7FFW'"ÊFV6ˆFRÇ'WFb”Ç"¬&ñvÊ˜&R"ï≤”S•“ê¢&WGW&‚ÊˆÊP¢ñb˜2ÁFÇÊWÜó7G2Ü˜WBíÊB˜2ÁFÇÊvWG6ó¶RÜ˜WBí‚#C†¢vóFÇ˜V‚Ü˜WB¬'&""í2c†¢FF“bÁ&VBÇê¢ñb∆V‚ÜFFí√“÷Öˆ'óFW3†¢&WGW&‚FF¢∆ˆrÁv&ÊñÊrÇ'FV∆Vw&“fñFVÚ6ˆ◊&W72FˆÚ∆&vS¢W2‚W2"¬∆V‚ÜFFí¬÷Öˆ'óFW2ê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ'FV∆Vw&“fñFVÚ6ˆ◊&W72WÜ6WFñˆ„¢W2"¬Rê¢&WGW&‚ÊˆÊP†¶7ñÊ2FVbˆ6ˆ◊&W75˜fñFVıˆf˜%˜FV∆Vw&“áfñFVıˆ'óFW3¢'óFW2¬÷Öˆ÷#¢ñÁB“CÇí”‚'óFW2¬ÊˆÊS†¢&WGW&‚vóB7ñÊ6ñÚÁFı˜Fá&VBÖˆ6ˆ◊&W75˜fñFVıˆf˜%˜FV∆Vw&’˜7ñÊ2¬fñFVıˆ'óFW2¬÷Öˆ÷"ê†¶7ñÊ2FVb˜&W«ï˜fñFVıˆg&ˆ’˜W&¬áWFFS¢WFFR¬6∆ñVÁC¢áGGÇ‰7ñÊ46∆ñVÁB¬W&√¢7G"¬6Fñˆ„¢7G"¬F6µˆñC¢7G"“""ì†¢"" ¢	Ì-˝-Ω˝]"	Ì	M	ç	“]}=ΩÕ-""FV∆Vw&“‡¢	˝‚=ÕÌΩ}›ç‚(	B’B≠¢Fˆ7V÷VÁB¬}-Ì≤FV∆Vw&“›RÕ≠çÌ-≤≠ÌÌ-≠çíÌΩç¢≠¢tîb‡¢"" ¢ÜVFW'2“∞¢%W6W"‘vVÁB#¢$÷˜¶ñ∆∆ÛR„Ü6ˆ◊Fñ&∆S≤uCU&Ù&˜BÛ„í"¿¢$66WB#¢'fñFVÚˆ◊B«fñFVÚÚ¢¬¢Ú£∑”„Ç"¿¢–†¢F˜vÊ∆ˆFVC¢'óFW2¬ÊˆÊR“ÊˆÊP¢G'ì†¢"“vóB6∆ñVÁBÊvWBáW&¬¬ÜVFW'3÷ÜVFW'2¬Fñ÷V˜WC”#C„¬fˆ∆∆˜u˜&VFó&V7G3’G'VRê¢"Á&ó6Uˆf˜%˜7FGW2Çê¢6ˆÁFVÁE˜GóR“á"ÊÜVFW'2ÊvWBÇ&6ˆÁFVÁB◊GóR"í˜"""íÊ∆˜vW"Çê¢ñbÊ˜B"Ê6ˆÁFVÁB˜"∆V‚á"Ê6ˆÁFVÁBí¬S#†¢&ó6R'VÁFñ÷TW'&˜"Üb&V◊GífñFVÚ&W7ˆÁ6S¢∂∆V‚á"Ê6ˆÁFVÁBó“'óFW2"ê¢ñb'FWáBˆáF÷¬"ñ‚6ˆÁFVÁE˜GóR˜"&∆ñ6Fñˆ‚ˆß6ˆ‚"ñ‚6ˆÁFVÁE˜GóS†¢&ó6R'VÁFñ÷TW'&˜"Üb&Ê˜BfñFVÚ&W7ˆÁ6S¢∂6ˆÁFVÁE˜GóW”≤∑"ÁFWáE≥£3◊“"ê¢F˜vÊ∆ˆFVB“"Ê6ˆÁFVÁ@¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ'&W«ï˜fñFVıˆg&ˆ’˜W&√¢∆ˆ6¬F˜vÊ∆ˆBfñ∆VC¢W2"¬Rê†¢6ÜEˆñB“vWFGG"ÜvWFGG"áWFFR¬&VffV7FófUˆ6ÜB"¬ÊˆÊRí¬&ñB"¬&Ê"ê¢FVGWUˆ∂Wí“˜fñFVı˜&W7V«Eˆ∂WíÜ6ÜEˆñB¬F6µˆñC◊F6µˆñB¬W&√◊W&¬¬6ˆÁFVÁC÷F˜vÊ∆ˆFVBê¢ñbˆ÷&µ˜fñFVı˜6VÁEˆˆÊ6RÜFVGWUˆ∂Wíì†¢∆ˆrÊñÊfÚÇ'&W«ï˜fñFVıˆg&ˆ’˜W&√¢GW∆ñ6FR7W&W76VBF6µˆñC“W2"¬F6µˆñBê¢&WGW&‡†¢ñbF˜vÊ∆ˆFVC†¢2cs¢f˜"FV∆Vw&“&V¶V7Fñˆ‚˜6ó¶Ró77VW2¬G'í6ˆ◊7B’B&Vf˜&Rf∆∆ñÊr&6≤FÚ&r∆ñÊ≤‡¢ñbDTƒTu$’ıdîDTıÙ4Ù’$U55ÙÙÂÙdî¬ÊB∆V‚ÜF˜vÊ∆ˆFVBí‚÷ÇÉR¬ñÁBÖDTƒTu$’ı$U5T≈EÙ‘ÖÙ‘"˜"CÇíí¢#B¢#C†¢6ˆ◊7B“vóBˆ6ˆ◊&W75˜fñFVıˆf˜%˜FV∆Vw&“ÜF˜vÊ∆ˆFVB¬DTƒTu$’ı$U5T≈EÙ‘ÖÙ‘"ê¢ñb6ˆ◊7C†¢F˜vÊ∆ˆFVB“6ˆ◊7@¢ñbdîDTıı$U5T≈Eı4T‰EÙ5ÙDÙ5T‘TÂC†¢G'ì†¢&ñÚ“'óFW4îÚÜF˜vÊ∆ˆFVBê¢&ñÚÊÊ÷R“'&W7V«BÊ◊B ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ïˆFˆ7V÷VÁBÜFˆ7V÷VÁC‘ñÁWDfñ∆RÜ&ñÚí¬6Fñˆ„÷6Fñˆ‚ê¢&WGW&‡¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ'&W«ï˜fñFVıˆg&ˆ’˜W&√¢Fˆ7V÷VÁB6VÊBfñ∆VC¢W2"¬Rê¢G'ì†¢&ñÚ“'óFW4îÚÜF˜vÊ∆ˆFVBê¢&ñÚÊÊ÷R“'&W7V«BÊ◊B ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜fñFVÚáfñFVÛ‘ñÁWDfñ∆RÜ&ñÚí¬6Fñˆ„÷6Fñˆ‚¬7W˜'G5˜7G&V÷ñÊs’G'VRê¢&WGW&‡¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ'&W«ï˜fñFVıˆg&ˆ’˜W&√¢fñFVÚ6VÊBfñ∆VC¢W2"¬Rê¢G'ì†¢&ñÚ“'óFW4îÚÜF˜vÊ∆ˆFVBê¢&ñÚÊÊ÷R“'&W7V«BÊ◊B ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ïˆFˆ7V÷VÁBÜFˆ7V÷VÁC‘ñÁWDfñ∆RÜ&ñÚí¬6Fñˆ„÷6Fñˆ‚ê¢&WGW&‡¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ'&W«ï˜fñFVıˆg&ˆ’˜W&√¢Fˆ7V÷VÁB6VÊBf∆∆&6≤fñ∆VC¢W2"¬Rê¢ñbDTƒTu$’ıdîDTıÙ4Ù’$U55ÙÙÂÙdî√†¢6ˆ◊7B“vóBˆ6ˆ◊&W75˜fñFVıˆf˜%˜FV∆Vw&“ÜF˜vÊ∆ˆFVB¬DTƒTu$’ı$U5T≈EÙ‘ÖÙ‘"ê¢ñb6ˆ◊7BÊB6ˆ◊7B“F˜vÊ∆ˆFVC†¢G'ì†¢&ñÚ“'óFW4îÚÜ6ˆ◊7Bê¢&ñÚÊÊ÷R“'&W7V«E˜Fu˜6fRÊ◊B ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ïˆFˆ7V÷VÁBÜFˆ7V÷VÁC‘ñÁWDfñ∆RÜ&ñÚí¬6Fñˆ„÷6Fñˆ‚≤%∆Ô	˘:b	-çM]‚m-‚MΩÚÌ-˝-≠Ç"FV∆Vw&“‚"ê¢&WGW&‡¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ'&W«ï˜fñFVıˆg&ˆ’˜W&√¢6ˆ◊&W76VBFˆ7V÷VÁB6VÊBfñ∆VC¢W2"¬Rê†¢ñbÊ˜BdîDTıı$U5T≈Eı4T‰EÙ5ÙDÙ5T‘TÂC†¢G'ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜fñFVÚáfñFVÛ◊W&¬¬6Fñˆ„÷6Fñˆ‚¬7W˜'G5˜7G&V÷ñÊs’G'VRê¢&WGW&‡¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ'&W«ï˜fñFVıˆg&ˆ’˜W&√¢FV∆Vw&“U$¬fñFVÚ6VÊBfñ∆VC¢W2"¬Rê¢G'ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ïˆFˆ7V÷VÁBÜFˆ7V÷VÁC◊W&¬¬6Fñˆ„÷6Fñˆ‚ê¢&WGW&‡¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ'&W«ï˜fñFVıˆg&ˆ’˜W&√¢FV∆Vw&“U$¬Fˆ7V÷VÁB6VÊBfñ∆VC¢W2"¬Rê†¢6fU˜W&¬“áW&¬˜"""ï≥£3S–¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b'∂6FñˆÁ’∆Ó)™˚àÚFV∆Vw&“›R˝ç›˝≤-çM]ÌMù≤›˝˝Õ=‚¬Ì--Ω˝‚ΩΩ≠3•∆Á∑6fU˜W&«“"¿¢Fó6&∆U˜vV%˜vU˜&WfñWs‘f«6R¿¢ê†¶7ñÊ2FVb˜&W«ï˜fñFVıˆ'óFW2áWFFS¢WFFR¬6ˆÁFVÁC¢'óFW2¬6Fñˆ„¢7G"¬F6µˆñC¢7G"“""ì†¢ñbÊ˜B6ˆÁFVÁB˜"∆V‚Ü6ˆÁFVÁBí¬S#†¢&ó6R'VÁFñ÷TW'&˜"Üb&V◊GífñFVÚ'óFW3¢∂∆V‚Ü6ˆÁFVÁB˜""rró“'óFW2"ê¢6ÜEˆñB“vWFGG"ÜvWFGG"áWFFR¬&VffV7FófUˆ6ÜB"¬ÊˆÊRí¬&ñB"¬&Ê"ê¢FVGWUˆ∂Wí“˜fñFVı˜&W7V«Eˆ∂WíÜ6ÜEˆñB¬F6µˆñC◊F6µˆñB¬6ˆÁFVÁC÷6ˆÁFVÁBê¢ñbˆ÷&µ˜fñFVı˜6VÁEˆˆÊ6RÜFVGWUˆ∂Wíì†¢∆ˆrÊñÊfÚÇ'&W«ï˜fñFVıˆ'óFW3¢GW∆ñ6FR7W&W76VBF6µˆñC“W2"¬F6µˆñBê¢&WGW&‡¢6VÁEˆˆ≤“f«6P¢G'ì†¢&ñÚ“'óFW4îÚÜ6ˆÁFVÁBê¢&ñÚÊÊ÷R“'&W7V«BÊ◊B ¢ñbdîDTıı$U5T≈Eı4T‰EÙ5ÙDÙ5T‘TÂC†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ïˆFˆ7V÷VÁBÄ¢Fˆ7V÷VÁC‘ñÁWDfñ∆RÜ&ñÚí¬6Fñˆ„÷6Fñˆ‚¿¢w&óFU˜Fñ÷V˜WC’dîDTıı4T‰Eıu$ïDUıDî‘TıUEı2¬&VE˜Fñ÷V˜WC”#¿¢ê¢V«6S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜fñFVÚÄ¢fñFVÛ‘ñÁWDfñ∆RÜ&ñÚí¬6Fñˆ„÷6Fñˆ‚¬7W˜'G5˜7G&V÷ñÊs’G'VR¿¢w&óFU˜Fñ÷V˜WC’dîDTıı4T‰Eıu$ïDUıDî‘TıUEı2¬&VE˜Fñ÷V˜WC”#¿¢ê¢6VÁEˆˆ≤“G'VP¢fñÊ∆«ì†¢ñbÊ˜B6VÁEˆˆ≥†¢2G&Á7˜'Bfñ«W&R◊W7BÊ˜BGW&‚&WG'íñÁFÚ7W&W76VBGW∆ñ6FR‡¢ı4TÂEıdîDTıÙ¥Uï2Á˜ÜFVGWUˆ∂Wí¬ÊˆÊRê†¶FVb˜&Fñıˆf˜%ˆ7V7BÜ7V7C¢7G"í”‚7G#†¢"" ¢	MΩÚ'VÁvíífW'6ñˆ‚##B””b&FñÚMÌΩm]“Ω-¬}]ç]›ç]¬¿¢›R-Ì≠Ìíì£bÚc£í‡¢"" ¢÷ñÊr“∞¢#ì£b#¢#scÉ£#É"¿¢#c£í#¢##É£scÇ"¿¢#£#¢#ìc£ìc"¿¢#C£R#¢#scÉ£ìc"¿¢#3£B#¢#scÉ£#B"¿¢#C£2#¢##C£scÇ"¿¢–¢&WGW&‚÷ñÊrÊvWBÇÜ7V7B˜"""íÁ7G&óÇí¬#scÉ£#É"ê†¶FVbˆGW&FñˆÂˆf˜%ˆVÊvñÊRÜVÊvñÊS¢7G"¬GW&FñˆÂ˜3¢ñÁBí”‚ñÁC†¢G'ì†¢B“ñÁBÜGW&FñˆÂ˜2˜"Rê¢WÜ6WBWÜ6WFñˆ„†¢B“P¢VÊvñÊR“ÜVÊvñÊR˜"""íÊ∆˜vW"Çê¢ñbVÊvñÊR”“''VÁví#†¢&WGW&‚÷ÇÉ"¬÷ñ‚É¬Bíê¢ñbVÊvñÊR”“&∂∆ñÊr#†¢&WGW&‚ñbB„“rV«6RP¢ñbVÊvñÊR”“'6˜&#†¢26˜&Ù6ˆ÷WB-çΩÕ›]R˝ç›çÕ]"6V6ˆÊG2“BÛÇÛ"‡¢2]≠=›BçrTí›ÌÕΩç}=]¬"Ωçmùççí˝ÌMM]mç-]ÕΩí-ç›"(	BÇ¿¢2MΩç››ΩR}˝Ì≤(	B"‡¢ñbB√“S†¢&WGW&‚@¢ñbB√“†¢&WGW&‚Ä¢&WGW&‚ ¢ñbVÊvñÊR”“&«V÷#†¢&WGW&‚íñbB„“rV«6RP¢&WGW&‚÷ÇÉR¬÷ñ‚ÉR¬Bíê†¶FVbˆwVW75ˆ7V7Eˆg&ˆ’ˆñ÷vRÜñ÷uˆ'óFW3¢'óFW2¬f∆∆&6≥¢7G"“#ì£b"í”‚7G#†¢ñbñ÷vRó2ÊˆÊS†¢&WGW&‚f∆∆&6∞¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2íê¢r¬Ç“ñ“Á6ó¶P¢ñbÇ‚r¢„#†¢&WGW&‚#ì£b ¢ñbr‚Ç¢„#†¢&WGW&‚#c£í ¢&WGW&‚#£ ¢WÜ6WBWÜ6WFñˆ„†¢&WGW&‚f∆∆&6∞†¶FVbˆñ÷vU˜&Vg5ˆf˜%ˆì'báWFFS¢WFFR¬ñ÷uˆ'óFW3¢'óFW2í”‚GW∆U∑7G"¬7G%”†¢"" ¢	-Ì}-ù]¬›}ΩFF˜W&¬¬˝Ì-Ì¬FV∆Vw&“U$¬‡¢	MΩÚ6ˆ÷WBÚ'VÁvíÚ∂∆ñÊr]}Ì˝›]R˝]-Ω¬˝ÌÌ--¬&6ScBFF◊W&¬¿¢˝Ì-ÌÕ2}-‚-›]ç›çRí}-‚›RÕÌ=="≠Ì]≠-›‚}-¬FV∆Vw&“fñ∆U˜FÇ‡¢"" ¢FF˜W&¬“Ä¢b&FFß∑6Êñfeˆñ÷vUˆ÷ñ÷RÜñ÷uˆ'óFW2ó”∂&6ScB¬ ¢b'∂&6ScBÊ#cFVÊ6ˆFRÜñ÷uˆ'óFW2íÊFV6ˆFRÇv66ñíró“ ¢ê†¢Fu˜W&¬“" ¢G'ì†¢Fu˜W&¬“ˆvWEˆ66ÜVE˜Ü˜Fı˜W&¬áWFFRÊVffV7FófU˜W6W"ÊñBê¢WÜ6WBWÜ6WFñˆ„†¢Fu˜W&¬“" †¢&WGW&‚FF˜W&¬¬Fu˜W&¿†¶FVb˜6˜&˜6ó¶Uˆf˜%ˆ7V7BÜ7V7C¢7G"í”‚GW∆U∑7G"¬ñÁB¬ñÁE”†¢26˜&fñFV˜2í˝ç›çÕ]"›Rì£bÛc£í¬6ó¶R‡¢2	MΩÚ-›M-›Ì=‚6˜&”"-çΩÕ›ΩR}Õ]≥¢s#É#ÉçΩÇ#ÉÉs#‡¢“Ü7V7B˜"""íÁ7G&óÇê¢ñb”“#c£í#†¢&WGW&‚##ÉÉs#"¬#É¬s# ¢&WGW&‚#s#É#É"¬s#¬#É †¶FVb˜&W&U˜6˜&˜&VfW&VÊ6Uˆñ÷vRÜñ÷uˆ'óFW3¢'óFW2¬7V7C¢7G"í”‚GW∆U∂'óFW2¬7G"¬7G"¬7G%”†¢"" ¢	=Ì-Ì-ç"ç}Ìm]›çRMΩÚ6˜&ñ÷v^(i'fñFVÚ‡¢	-m›„¢ÌMçmçΩÕ›ΩífñFV˜2í-]=]"¬}-Ì≤&VfW&VÊ6Rñ÷vRÌ-˝M∞¢m]Ω]-Ω¬}Õ]Ì¬fñFVÚ6ó¶R‚	˝Ì›-ÌÕ2M]Ω]¬6VÁFW"÷7&˜≤&W6ó¶R‡¢	-Ì}-ù]#¢Ü'óFW2¬÷ñ÷R¬FF˜W&¬¬6ó¶Rí‡¢"" ¢6ó¶R¬Gr¬FÇ“˜6˜&˜6ó¶Uˆf˜%ˆ7V7BÜ7V7Bê†¢ñbñ÷vRó2ÊˆÊS†¢÷ñ÷R“6Êñfeˆñ÷vUˆ÷ñ÷RÜñ÷uˆ'óFW2ê¢FF˜W&¬“b&FFß∂÷ñ÷W”∂&6ScB«∂&6ScBÊ#cFVÊ6ˆFRÜñ÷uˆ'óFW2íÊFV6ˆFRÇv66ñíró“ ¢&WGW&‚ñ÷uˆ'óFW2¬÷ñ÷R¬FF˜W&¬¬6ó¶P†¢G'ì†¢ñ““ñ÷vRÊ˜V‚Ñ'óFW4îÚÜñ÷uˆ'óFW2íê¢G'ì†¢ñ““ñ÷vT˜2ÊWÜñe˜G&Á7˜6RÜñ“ê¢WÜ6WBWÜ6WFñˆ„†¢70¢ñ““ñ“Ê6ˆÁfW'BÇ%$t""ê¢r¬Ç“ñ“Á6ó¶P¢F&vWE˜&FñÚ“GrÚFÄ¢7W%˜&FñÚ“rÚ÷ÇÉ¬Çê†¢ñb7W%˜&FñÚ‚F&vWE˜&FñÛ†¢2
Ωçç≠Ì¬ççÌ≠ÌR(	B]m]¬≠Ú‡¢ÊWu˜r“ñÁBÜÇ¢F&vWE˜&FñÚê¢∆VgB“÷ÇÉ¬ár“ÊWu˜ríÚÚ"ê¢ñ““ñ“Ê7&˜ÇÜ∆VgB¬¬∆VgB≤ÊWu˜r¬Çíê¢V∆ñb7W%˜&FñÚ¬F&vWE˜&FñÛ†¢2
Ωçç≠Ì¬-ΩÌ≠ÌR(	B]m]¬-]R˝›çr‡¢ÊWuˆÇ“ñÁBárÚF&vWE˜&FñÚê¢F˜“÷ÇÉ¬ÜÇ“ÊWuˆÇíÚÚ"ê¢ñ““ñ“Ê7&˜ÇÉ¬F˜¬r¬F˜≤ÊWuˆÇíê†¢&W6◊∆R“vWFGG"Ññ÷vR¬%&W6◊∆ñÊr"¬ñ÷vRí‰ƒ‰5§ı0¢ñ““ñ“Á&W6ó¶RÇáGr¬FÇí¬&W6◊∆Rê¢˜WB“'óFW4îÚÇê¢ñ“Á6fRÜ˜WB¬f˜&÷C“$•Tr"¬V∆óGì”ì"¬˜Fñ÷ó¶S’G'VRê¢&W&VB“˜WBÊvWGf«VRÇê¢÷ñ÷R“&ñ÷vRˆßVr ¢FF˜W&¬“b&FFß∂÷ñ÷W”∂&6ScB«∂&6ScBÊ#cFVÊ6ˆFRá&W&VBíÊFV6ˆFRÇv66ñíró“ ¢&WGW&‚&W&VB¬÷ñ÷R¬FF˜W&¬¬6ó¶P¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ%6˜&ñ÷vR&W&Rfñ∆VB¬W6ñÊr˜&ñvñÊ¬'óFW3¢W2"¬Rê¢÷ñ÷R“6Êñfeˆñ÷vUˆ÷ñ÷RÜñ÷uˆ'óFW2ê¢FF˜W&¬“b&FFß∂÷ñ÷W”∂&6ScB«∂&6ScBÊ#cFVÊ6ˆFRÜñ÷uˆ'óFW2íÊFV6ˆFRÇv66ñíró“ ¢&WGW&‚ñ÷uˆ'óFW2¬÷ñ÷R¬FF˜W&¬¬6ó¶P†¶7ñÊ2FVb˜7F'E˜Ü˜Fı˜&Wfóf¬áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬VÊvñÊS¢7G"¬ñ÷uˆ'óFW3¢'óFW2¬&ˆ◊C¢7G"“""ì†¢VÊvñÊR“ÜVÊvñÊR˜"''VÁví"íÊ∆˜vW"ÇíÁ7G&óÇê¢ñbVÊvñÊR”“&«V÷"ÊB≈T‘ıDT’ÙDï4$ƒTC†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ«V÷-]Õ]››‚Ì-≠ΩÌ}]›Ç≠Ω-çrÕ]›‚‚	ç˝ÌΩÕ}=ù-R'VÁví¬∂∆ñÊrçΩÇ6˜&"]rΩÌM]í‚"ê¢&WGW&‡¢&ˆ◊B“á&ˆ◊B˜"'7V'F∆R∆ñfV∆ñ∂RÊñ÷Fñˆ‚¬ÊGW&¬÷ñ7&Ú÷÷˜fV÷VÁG2¬6÷ˆ˜FÇ6ñÊV÷Fñ26÷W&÷˜Fñˆ‚"íÁ7G&óÇê¢GW"¬7“'6U˜fñFVıˆ˜G2á&ˆ◊Bê¢ñbÊ˜B&RÁ6V&6Çá""ÉÛ£ì£g√c£ó√£√C£W√3£G√C£2í"¬&ˆ◊B˜"""¬&R‰íì†¢7“ˆwVW75ˆ7V7Eˆg&ˆ’ˆñ÷vRÜñ÷uˆ'óFW2¬7ê¢GW"“ˆGW&FñˆÂˆf˜%ˆVÊvñÊRÜVÊvñÊR¬GW"ê†¢ïˆVÊvñÊR“''VÁví"ñbVÊvñÊRñ‚Ç''VÁví"¬&∂∆ñÊr"¬'6˜&"íV«6R&«V÷ ¢W7B“˜fñFVı˜&˜fñFW%ˆ6˜7E˜W6BÜVÊvñÊR¬GW"íñbVÊvñÊRñ‚Ç''VÁví"¬&∂∆ñÊr"¬'6˜&"íV«6R„C †¢7ñÊ2FVbˆvÚÇì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b.)»R	}˝=≠‚Ìmç-Ω]›çRMÌ-„¢∂VÊvñÊRÁWW"Çó“(
"∂GW'“]¢(
"∂7“‚ ¢ê¢ñbVÊvñÊR”“''VÁví#†¢&WGW&‚&ˆˆ¬ÜvóB˜'VÂ˜'VÁvïˆÊñ÷FU˜Ü˜FÚáWFFR¬6ˆÁFWáB¬ñ÷uˆ'óFW2¬&ˆ◊C◊&ˆ◊B¬GW&FñˆÂ˜3÷GW"¬7V7C÷7íê¢ñbVÊvñÊR”“&«V÷#†¢&WGW&‚&ˆˆ¬ÜvóB˜'VÂˆ«V÷ˆÊñ÷FU˜Ü˜FÚáWFFR¬6ˆÁFWáB¬ñ÷uˆ'óFW2¬&ˆ◊C◊&ˆ◊B¬GW&FñˆÂ˜3÷GW"¬7V7C÷7íê¢ñbVÊvñÊRñ‚Ç'6˜&"¬&∂∆ñÊr"ì†¢&WGW&‚&ˆˆ¬ÜvóB˜'VÂˆ6ˆ÷WEˆì'báWFFR¬6ˆÁFWáB¬VÊvñÊR¬ñ÷uˆ'óFW2¬&ˆ◊C◊&ˆ◊B¬GW&FñˆÂ˜3÷GW"¬7V7C÷7íê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	›]ç}-]-›ΩíM-çmÌ¢Ìmç-Ω]›çÚMÌ-‚‚"ê¢&WGW&‚f«6P†¢vóB˜G'ï˜ï˜FÜVÂˆFÚÄ¢WFFR¬6ˆÁFWáB¬WFFRÊVffV7FófU˜W6W"ÊñB¬ïˆVÊvñÊR¬W7B¬ˆvÚ¿¢&V÷V÷&W%ˆ∂ñÊC÷b'&WfófU˜Ü˜Fı˜∂VÊvñÊW“"¿¢&V÷V÷&W%˜ñ∆ˆC◊≤&VÊvñÊR#¢VÊvñÊR¬&GW&Fñˆ‚#¢GW"¬&7V7B#¢7¬'&ˆ◊B#¢&ˆ◊G“¿¢ê†¶7ñÊ2FVb˜ˆ∆≈˜fñFVı˜F6µˆvVÊW&ñ2Ä¢WFFS¢WFFR¿¢6∆ñVÁC¢áGGÇ‰7ñÊ46∆ñVÁB¿¢ÜVFW'3¢Fñ7B¿¢&6U˜W&√¢7G"¿¢7FGW5˜Fá3¢∆ó7E∑7G%“¿¢F6µˆñC¢7G"¿¢6Fñˆ„¢7G"¿¢÷Ö˜vóE˜3¢ñÁB“#¿¢F6µˆÊ˜EˆWÜó7E˜6ˆgEˆfñ≈˜3¢ñÁB“¿¢6ñ∆VÁE˜6ˆgEˆfñ√¢&ˆˆ¬“f«6R¿¢í”‚&ˆˆ√†¢"" ¢
=›ç-]ΩÕ›Ωíˆ∆∆ñÊrMΩÚ7ñÊ2◊fñFVÚ}Mr‡†¢	-m›‚MΩÚ6ˆ÷WBı'VÁvì¢Ì--]"F6µˆÊ˜EˆWÜó7BÕÌm]"˝ç]ÌMç-¬›R≠¢Mç›ΩÕ›ÚÌçç≠¿¢≠¢-MçÚ˝]-ç}›Ìíç›çmçΩç}mçÇ}M}Ç‚	˝Ì›-ÌÕ2Õ≤›R}ç-]¬]=‚Õ=›Ì-]››Ω¿¢˝Ì-ΩÌ¬‚	›‚]ΩÇÌ“M]mç-ÚMÌΩÕçRF6µˆÊ˜EˆWÜó7E˜6ˆgEˆfñ≈˜2¬-Ì}-ù]¬f«6R¿¢}-Ì≤-]]›çí=Ì-]›¬ÕÌ2˝]]≠ΩÌ}ç-ÕÚ›M==ÌíM-çmÌ¢˝ÕÌM]Ω¬‡¢"" ¢7F'FVB“Fñ÷RÁFñ÷RÇê¢F6µˆÊ˜EˆWÜó7E˜6VVÂˆC¢f∆ˆB¬ÊˆÊR“ÊˆÊP¢ó5˜F∆∂ñÊuˆfF"“&∂∆ñÊrF∆∂ñÊrfF""ñ‚Ü6Fñˆ‚˜"""íÊ∆˜vW"Çê¢fF%ˆÊ˜Fñ6UˆgFW%˜2“S ¢fF%ˆÊ˜Fñ6UˆWfW'ï˜2“É ¢ÊWáEˆfF%ˆÊ˜Fñ6U˜2“fF%ˆÊ˜Fñ6UˆgFW%˜0†¢vÜñ∆RG'VS†¢∆7Eˆ&ˆGí“" ¢6ˆgEˆÊ˜EˆWÜó7E˜6VVÂ˜FÜó5˜&˜VÊB“f«6P†¢f˜"FÇñ‚7FGW5˜Fá3†¢W&¬“b'∂&6U˜W&«◊∑Fá“"Êf˜&÷BÜñC◊F6µˆñBê¢G'ì†¢'2“vóB6∆ñVÁBÊvWBáW&¬¬ÜVFW'3÷ÜVFW'2¬Fñ÷V˜WC”c„ê¢&ˆGï˜&WfñWr“ˆïˆW'&˜%˜&WfñWrá'2ê†¢ñb'2Á7FGW5ˆ6ˆFR„“C†¢∆7Eˆ&ˆGí“b'∑'2Á7FGW5ˆ6ˆFW”¢∂&ˆGï˜&WfñWw“ †¢26ˆ÷WDíı'VÁví6ˆgB◊7FFS¢F6≤7&VFVB¬'WB7FGW27F˜&vRó2Ê˜B&VGíñWB‡¢ñb'F6µˆÊ˜EˆWÜó7B"ñ‚Ü&ˆGï˜&WfñWr˜"""íÊ∆˜vW"Çì†¢6ˆgEˆÊ˜EˆWÜó7E˜6VVÂ˜FÜó5˜&˜VÊB“G'VP¢ñbF6µˆÊ˜EˆWÜó7E˜6VVÂˆBó2ÊˆÊS†¢F6µˆÊ˜EˆWÜó7E˜6VVÂˆB“Fñ÷RÁFñ÷RÇê¢ñbF6µˆÊ˜EˆWÜó7E˜6ˆgEˆfñ≈˜2ÊBáFñ÷RÁFñ÷RÇí“F6µˆÊ˜EˆWÜó7E˜6VVÂˆBí„“F6µˆÊ˜EˆWÜó7E˜6ˆgEˆfñ≈˜3†¢∆ˆrÁv&ÊñÊrÄ¢"W3¢F6µˆÊ˜EˆWÜó7BW'6ó7FVBR„g2f˜"F6µˆñC“W3≤6ˆgBf∆∆&6≤"¿¢6Fñˆ‚¬Fñ÷RÁFñ÷RÇí“F6µˆÊ˜EˆWÜó7E˜6VVÂˆB¬F6µˆñB¿¢ê¢ñbÊ˜B6ñ∆VÁE˜6ˆgEˆfñ√†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b.)™˚àÚ∂6FñˆÁ”¢}M}Ωçç≠Ì¬MÌΩ=‚›R˝Ì˝-Ω˝]-Ú"6ˆ÷WBı'VÁví‚	˝]]≠ΩÌ}Ì¬›]}]-›Ωí˝=-¬‚ ¢ê¢&WGW&‚f«6P¢6ˆÁFñÁVP†¢6ˆÁFñÁVP†¢G'ì†¢ß2“'2Êß6ˆ‚Çí˜"∑–¢WÜ6WBWÜ6WFñˆ„†¢ß2“∑–†¢WÜ6WBWÜ6WFñˆ‚2S†¢∆7Eˆ&ˆGí“7G"ÜRê¢6ˆÁFñÁVP†¢7B“7G"Üß2ÊvWBÇ'7FGW2"í˜"ß2ÊvWBÇ'7FFR"í˜"ß2ÊvWBÇ'F6µ˜7FGW2"í˜"""íÊ∆˜vW"Çê†¢26ˆ÷WBı'VÁvíç›Ì=MÌ-M"F6µˆÊ˜EˆWÜó7B-›=-Ç•4Ù‚˝Ç#Ù≤‡¢ñb7B”“'F6µˆÊ˜EˆWÜó7B"˜"'F6µˆÊ˜EˆWÜó7B"ñ‚ß6ˆ‚ÊGV◊2Üß2¬VÁ7W&Uˆ66ñì‘f«6RíÊ∆˜vW"Çì†¢6ˆgEˆÊ˜EˆWÜó7E˜6VVÂ˜FÜó5˜&˜VÊB“G'VP¢∆7Eˆ&ˆGí“ß6ˆ‚ÊGV◊2Üß2¬VÁ7W&Uˆ66ñì‘f«6Rï≥£s–¢ñbF6µˆÊ˜EˆWÜó7E˜6VVÂˆBó2ÊˆÊS†¢F6µˆÊ˜EˆWÜó7E˜6VVÂˆB“Fñ÷RÁFñ÷RÇê¢ñbF6µˆÊ˜EˆWÜó7E˜6ˆgEˆfñ≈˜2ÊBáFñ÷RÁFñ÷RÇí“F6µˆÊ˜EˆWÜó7E˜6VVÂˆBí„“F6µˆÊ˜EˆWÜó7E˜6ˆgEˆfñ≈˜3†¢∆ˆrÁv&ÊñÊrÄ¢"W3¢F6µˆÊ˜EˆWÜó7B•4Ù‚W'6ó7FVBR„g2f˜"F6µˆñC“W3≤6ˆgBf∆∆&6≤"¿¢6Fñˆ‚¬Fñ÷RÁFñ÷RÇí“F6µˆÊ˜EˆWÜó7E˜6VVÂˆB¬F6µˆñB¿¢ê¢ñbÊ˜B6ñ∆VÁE˜6ˆgEˆfñ√†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b.)™˚àÚ∂6FñˆÁ”¢}M}Ωçç≠Ì¬MÌΩ=‚›R˝Ì˝-Ω˝]-Ú"6ˆ÷WBı'VÁví‚	˝]]≠ΩÌ}Ì¬›]}]-›Ωí˝=-¬‚ ¢ê¢&WGW&‚f«6P¢6ˆÁFñÁVP†¢W&¬“ˆWáG&7Eˆfó'7E˜W&¬Üß2ÊvWBÇ&˜WGWB"íí˜"ˆWáG&7Eˆfó'7E˜W&¬Üß2ÊvWBÇ&76WG2"íí˜"ˆWáG&7Eˆfó'7E˜W&¬Üß2ê¢ñb7Bñ‚Ç&6ˆ◊∆WFVB"¬'7V66VVFVB"¬'7V66W72"¬&fñÊó6ÜVB"¬'&VGí"¬&FˆÊR"¬'7V66VVB"í˜"áW&¬ÊBÊ˜B7Bì†¢ñbÊ˜BW&√†¢2˜V‰íı6˜&fñFV˜2í}-‚-Ì}-ù]"6ˆ◊∆WFVB]rU$¬‡¢2
Mç›ΩÕ›Ωí’B›M‚}-¬Ì-M]ΩÕ›Ω¬tUB˜c˜fñFV˜2˜∂ñG“ˆ6ˆÁFVÁB‡¢ñb'6˜&"ñ‚Ü6Fñˆ‚˜"""íÊ∆˜vW"Çí˜""˜c˜fñFV˜2"ñ‚""Ê¶ˆñ‚á7FGW5˜Fá2ì†¢G'ì†¢6ˆÁFVÁE˜W&¬“b'∂&6U˜W&¬Á'7G&óÇ"Ú"ó“˜c˜fñFV˜2˜∑F6µˆñG“ˆ6ˆÁFVÁB ¢7"“vóB6∆ñVÁBÊvWBÜ6ˆÁFVÁE˜W&¬¬ÜVFW'3÷ÜVFW'2¬Fñ÷V˜WC”#C„¬fˆ∆∆˜u˜&VFó&V7G3’G'VRê¢ñb7"Á7FGW5ˆ6ˆFR¬CÊB7"Ê6ˆÁFVÁBÊB&∆ñ6Fñˆ‚ˆß6ˆ‚"Ê˜Bñ‚Ü7"ÊÜVFW'2ÊvWBÇ&6ˆÁFVÁB◊GóR"í˜"""íÊ∆˜vW"Çì†¢vóB˜&W«ï˜fñFVıˆ'óFW2áWFFR¬7"Ê6ˆÁFVÁB¬b'∂6FñˆÁ“)»R"¬F6µˆñC◊F6µˆñBê¢&WGW&‚G'VP¢∆ˆrÁv&ÊñÊrÇ"W26ˆÁFVÁBF˜vÊ∆ˆBfñ∆VC¢W2W2"¬6Fñˆ‚¬7"Á7FGW5ˆ6ˆFR¬ˆïˆW'&˜%˜&WfñWrÜ7"íê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ"W26ˆÁFVÁBF˜vÊ∆ˆBWÜ6WFñˆ„¢W2"¬6Fñˆ‚¬Rê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb.)™˚àÚ∂6FñˆÁ”¢}M}=Ì-Ì-¬›‚ΩΩ≠Ù’B›-çM]‚›R›ùM]›≤‚"ê¢&WGW&‚G'VP¢vóB˜&W«ï˜fñFVıˆg&ˆ’˜W&¬áWFFR¬6∆ñVÁB¬W&¬¬b'∂6FñˆÁ“)»R"¬F6µˆñC◊F6µˆñBê¢ñb''VÁví"ñ‚Ü6Fñˆ‚˜"""íÊ∆˜vW"Çì†¢˜&˜fñFW%ˆ÷&µ˜7V66W72Ç''VÁvïˆì'b"ê¢&WGW&‚G'VP¢ñb7Bñ‚Ç&fñ∆VB"¬&fñ¬"¬&W'&˜""¬&6Ê6V∆VB"¬&6Ê6V∆∆VB"¬'&V¶V7FVB"ì†¢ñb'6˜&"ñ‚Ü6Fñˆ‚˜"""íÊ∆˜vW"ÇíÊBó5˜6˜&˜V˜∆Uˆ÷ˆFW&FñˆÂˆW'&˜"Üß2ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÖ˜6˜&˜V˜∆Uˆ÷ˆFW&FñˆÂ˜FWáBÇíê¢&WGW&‚G'VP¢ñb''VÁví"ñ‚Ü6Fñˆ‚˜"""íÊ∆˜vW"ÇíÊB%TÂtïÙÑîDUıDT4ÖÙU%$ı%3†¢˜&˜fñFW%ˆ÷&µˆfñ«W&RÇ''VÁvïˆì'b"¬ß6ˆ‚ÊGV◊2Üß2¬VÁ7W&Uˆ66ñì‘f«6Rï≥£s“ê¢&WGW&‚f«6P¢&uˆfñ«W&R“ß6ˆ‚ÊGV◊2Üß2¬VÁ7W&Uˆ66ñì‘f«6Rê¢∆ˆrÁv&ÊñÊrÇ"W2FW&÷ñÊ¬&VÊFW"fñ«W&RF6µˆñC“W3¢W2"¬6Fñˆ‚¬F6µˆñB¬&uˆfñ«W&U≥£S“ê¢ñb&∂∆ñÊr"ñ‚Ü6Fñˆ‚˜"""íÊ∆˜vW"Çì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)ÿ¬∂∆ñÊr›RÕÌ2ÌÌ--¬›-‚MÌ-‚‚	M-çmÌ¢›R˝]]≠ΩÌ}ΩÚ‚	˝Ì˝Ì=ù-R]ùr‚ ¢ê¢&WGW&‚G'VP¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb.)ÿ¬∂6FñˆÁ”¢Ìçç≠]›M]‚"ê¢&WGW&‚G'VP†¢V∆6VE˜2“Fñ÷RÁFñ÷RÇí“7F'FV@¢ñbó5˜F∆∂ñÊuˆfF"ÊBV∆6VE˜2„“ÊWáEˆfF%ˆÊ˜Fñ6U˜3†¢V∆6VEˆ÷ñ‚“÷ÇÉ¬ñÁBÜV∆6VE˜2ÚÚcíê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b.(˚2	---]ùÌ}M-Ú(	BÌ"›R}-ç¬∂∆ñÊr˝ÌMÌΩm]"ÌÌ-≠2‚ ¢b-	˝ÌçΩ‚Ì≠ÌΩ‚∂V∆6VEˆ÷ñÁ“Õç“‚	ÌΩ}›‚Ì}M›çR}›çÕ]"M‚Õç›="¬ ¢-ç›Ì=M›]Õ›Ì=‚MÌΩÕçR‚	˝ÌmΩ=ù-¬ÌmçMù-R(	B]}=ΩÕ-"˝çM"ÌM--ÌÕ-ç}]≠Ç‚ ¢ê¢ÊWáEˆfF%ˆÊ˜Fñ6U˜2≥“fF%ˆÊ˜Fñ6UˆWfW'ï˜0†¢ñbV∆6VE˜2‚÷Ö˜vóE˜3†¢2	MΩÚ'VÁvíÙ6ˆ÷WBFñ÷V˜WBMÌΩm]“M-¬ç›-]]›]Õ2f∆∆&6≤›=Ì-›‚‡¢ñbF6µˆÊ˜EˆWÜó7E˜6VVÂˆBó2Ê˜BÊˆÊRÊB6ñ∆VÁE˜6ˆgEˆfñ√†¢∆ˆrÁv&ÊñÊrÇ"W3¢Fñ÷V˜WBvóFÇF6µˆÊ˜EˆWÜó7Bf˜"F6µˆñC“W3≤6ˆgBf∆∆&6≤"¬6Fñˆ‚¬F6µˆñBê¢&WGW&‚f«6P¢ñb''VÁví"ñ‚Ü6Fñˆ‚˜"""íÊ∆˜vW"ÇíÊB%TÂtïÙÑîDUıDT4ÖÙU%$ı%3†¢˜&˜fñFW%ˆ÷&µˆfñ«W&RÇ''VÁvïˆì'b"¬∆7Eˆ&ˆGï≥£s“ê¢&WGW&‚f«6P¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb.(…≤∂6FñˆÁ”¢-]ÕÚÌmçM›çÚ-ΩçΩ‚‚	˝ÌΩ]M›çíÌ--]#¢∂∆7Eˆ&ˆGï≥£S◊“"ê¢&WGW&‚f«6P†¢2	]ΩÇ-R˝=-ÇMΩÇ-ÌΩÕ≠‚Õ˝=≠çíF6µˆÊ˜EˆWÜó7B(	B˝Ì-‚mM¬Ω]M=Ìùçímç≠≤‡¢vóB7ñÊ6ñÚÁ6∆VWÖdîDTııÙƒ≈ÙDTƒïı2ê†¶7ñÊ2FVbˆ7&VFUˆÊE˜ˆ∆≈ˆì'bÄ¢WFFS¢WFFR¿¢&6U˜W&√¢7G"¿¢ïˆ∂Wì¢7G"¿¢7&VFU˜ñ∆ˆG3¢∆ó7E∑GW∆U∑7G"¬Fñ7E’“¿¢7FGW5˜Fá3¢∆ó7E∑7G%“¿¢6Fñˆ„¢7G"¿¢F6µˆÊ˜EˆWÜó7E˜6ˆgEˆfñ≈˜3¢ñÁB“¿¢6ñ∆VÁE˜6ˆgEˆfñ√¢&ˆˆ¬“f«6R¿¢÷Ö˜vóE˜3¢ñÁB¬ÊˆÊR“ÊˆÊR¿¢í”‚&ˆˆ√†¢ñbÊ˜Bïˆ∂Wì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb.)ÿ¬∂6FñˆÁ”¢í›≠ΩÌr›R}M“"TÂb‚"ê¢&WGW&‚G'VP†¢WFÖˆÜVFW'2“∞¢$WFÜ˜&ó¶Fñˆ‚#¢b$&V&W"∂ïˆ∂Wó“"¿¢$66WB#¢&∆ñ6Fñˆ‚ˆß6ˆ‚"¿¢–†¢∆7EˆW'"“" ¢∆≈ˆW'&˜'3¢∆ó7E∑7G%““µ–†¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC”ì„í26∆ñVÁC†¢f˜"FÇ¬ñ∆ˆBñ‚7&VFU˜ñ∆ˆG3†¢G'ì†¢ÜVFW'2“Fñ7BÜWFÖˆÜVFW'2ê†¢2'VÁví}]]r6ˆ÷WB-]=]"-]ç‚í‡¢ñb7G"áFÇíÁ7F'G7vóFÇÇ"˜'VÁvñ÷¬Ú"ì†¢ÜVFW'5≤%Ç’'VÁví’fW'6ñˆ‚%““%TÂtïÙïıdU%4îÙ‚˜"###B””b †¢2
˝]b›]mç¬MΩÚ6˜&Ù˜V‰ífñFV˜2ì¢ñÁWE˜&VfW&VÊ6R≠¢Mù∞¢2MÌΩm]“=]ÌMç-¬◊V«Fó'Bˆf˜&“÷FF¬›R•4Ù‚‚	"›-Ì¬]mçÕP¢26ˆÁFVÁB’GóR›R--ç¬-=}›=‚(	BáGGÇ¬MÌ-ç"&˜VÊF'í‡¢ñbó6ñÁ7FÊ6Ráñ∆ˆB¬Fñ7BíÊBñ∆ˆBÊvWBÇ%ıˆ◊V«Fó'B"ì†¢◊“ñ∆ˆBÊvWBÇ%ıˆ◊V«Fó'B"í˜"∑–¢FF“◊ÊvWBÇ&FF"í˜"∑–¢fñ∆W2“◊ÊvWBÇ&fñ∆W2"í˜"∑–¢"“vóB6∆ñVÁBÁ˜7BÜb'∂&6U˜W&«◊∑Fá“"¬ÜVFW'3÷ÜVFW'2¬FF÷FF¬fñ∆W3÷fñ∆W2ê¢V«6S†¢ÜVFW'5≤$6ˆÁFVÁB’GóR%““&∆ñ6Fñˆ‚ˆß6ˆ‚ ¢"“vóB6∆ñVÁBÁ˜7BÜb'∂&6U˜W&«◊∑Fá“"¬ÜVFW'3÷ÜVFW'2¬ß6ˆ„◊ñ∆ˆBê†¢ñb"Á7FGW5ˆ6ˆFR„“C†¢÷ˆFR“&◊V«Fó'B"ñbó6ñÁ7FÊ6Ráñ∆ˆB¬Fñ7BíÊBñ∆ˆBÊvWBÇ%ıˆ◊V«Fó'B"íV«6R&ß6ˆ‚ ¢∆7EˆW'"“b%ı5B∑Fá“∑∂÷ˆFW’“(i"∑"Á7FGW5ˆ6ˆFW”¢µˆïˆW'&˜%˜&WfñWrá"ó“ ¢∆≈ˆW'&˜'2ÊVÊBÜ∆7EˆW'"ê¢∆ˆrÁv&ÊñÊrÇ"W27&VFRfñ∆VC¢W2"¬6Fñˆ‚¬∆7EˆW'"ê¢6ˆÁFñÁVP†¢G'ì†¢ß2“"Êß6ˆ‚Çí˜"∑–¢WÜ6WBWÜ6WFñˆ„†¢ß2“∑–†¢&VGï˜W&¬“Ä¢ˆWáG&7Eˆfó'7E˜W&¬Üß2ÊvWBÇ&˜WGWB"íê¢˜"ˆWáG&7Eˆfó'7E˜W&¬Üß2ÊvWBÇ&˜WGWG2"íê¢˜"ˆWáG&7Eˆfó'7E˜W&¬Üß2ÊvWBÇ&76WG2"íê¢˜"ˆWáG&7Eˆfó'7E˜W&¬Üß2ÊvWBÇ&FF"íê¢˜"ˆWáG&7Eˆfó'7E˜W&¬Üß2ÊvWBÇ'&W7V«B"íê¢˜"ˆWáG&7Eˆfó'7E˜W&¬Üß2ÊvWBÇ'&W7ˆÁ6R"íê¢˜"ˆWáG&7Eˆfó'7E˜W&¬Üß2ÊvWBÇ'ñ∆ˆB"íê¢˜"ˆWáG&7Eˆfó'7E˜W&¬Üß2ê¢ê†¢ñb&VGï˜W&√†¢vóB˜&W«ï˜fñFVıˆg&ˆ’˜W&¬áWFFR¬6∆ñVÁB¬&VGï˜W&¬¬b'∂6FñˆÁ“)»R"ê¢&WGW&‚G'VP†¢F6µˆñB“7G"Ä¢ß2ÊvWBÇ&ñB"ê¢˜"ß2ÊvWBÇ'F6µˆñB"ê¢˜"ß2ÊvWBÇ&vVÊW&FñˆÂˆñB"ê¢˜"ß2ÊvWBÇ'fñFVıˆñB"ê¢˜"ß2ÊvWBÇ'F6¥ñB"ê¢˜"ß2ÊvWBÇ'F6¥îB"ê¢˜"ß2ÊvWBÇ'&WVW7EˆñB"ê¢˜"ß2ÊvWBÇ'WVñB"ê¢˜"" ¢íÁ7G&óÇê†¢ñbÊ˜BF6µˆñBÊBó6ñÁ7FÊ6RÜß2ÊvWBÇ&FF"í¬Fñ7Bì†¢B“ß2ÊvWBÇ&FF"í˜"∑–¢F6µˆñB“7G"Ä¢BÊvWBÇ&ñB"ê¢˜"BÊvWBÇ'F6µˆñB"ê¢˜"BÊvWBÇ&vVÊW&FñˆÂˆñB"ê¢˜"BÊvWBÇ'fñFVıˆñB"ê¢˜"BÊvWBÇ'F6¥ñB"ê¢˜"BÊvWBÇ'F6¥îB"ê¢˜"BÊvWBÇ'&WVW7EˆñB"ê¢˜"BÊvWBÇ'WVñB"ê¢˜"" ¢íÁ7G&óÇê†¢ñbÊ˜BF6µˆñBÊBó6ñÁ7FÊ6RÜß2ÊvWBÇ'&W7V«B"í¬Fñ7Bì†¢B“ß2ÊvWBÇ'&W7V«B"í˜"∑–¢F6µˆñB“7G"Ä¢BÊvWBÇ&ñB"ê¢˜"BÊvWBÇ'F6µˆñB"ê¢˜"BÊvWBÇ&vVÊW&FñˆÂˆñB"ê¢˜"BÊvWBÇ'fñFVıˆñB"ê¢˜"BÊvWBÇ'F6¥ñB"ê¢˜"BÊvWBÇ'F6¥îB"ê¢˜"BÊvWBÇ'&WVW7EˆñB"ê¢˜"BÊvWBÇ'WVñB"ê¢˜"" ¢íÁ7G&óÇê†¢ñbÊ˜BF6µˆñC†¢∆7EˆW'"“b%ı5B∑Fá”¢›]"ñB}M}Ç"Ì--]-R∂ß6ˆ‚ÊGV◊2Üß2¬VÁ7W&Uˆ66ñì‘f«6Rï≥£s◊“ ¢∆≈ˆW'&˜'2ÊVÊBÜ∆7EˆW'"ê¢6ˆÁFñÁVP†¢ñb&∂∆ñÊrF∆∂ñÊrfF""ñ‚Ü6Fñˆ‚˜"""íÊ∆˜vW"Çì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.(˚2∂∆ñÊrF∆∂ñÊrfF#¢}M}˝ç›˝-‚
Ì}M›çRÌΩ}›‚}›çÕ]"M‚Õç›="¬ ¢-ç›Ì=M›]Õ›Ì=‚MÌΩÕçR‚	Ì"˝ÌMÌΩmç"Ì-2Ç˝ççΩ"-çM]‚--ÌÕ-ç}]≠Ç‚ ¢ê¢V«6S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb.(˚2∂6FñˆÁ”¢}M}˝ç›˝-¬ÌmçM‚]}=ΩÕ-.(
b"ê¢∆ˆrÊñÊfÚÇ"W266WFVC¢FÉ“W2F6µˆñC“W2&W7ˆÁ6S“W2"¬6Fñˆ‚¬FÇ¬F6µˆñB¬ß6ˆ‚ÊGV◊2Üß2¬VÁ7W&Uˆ66ñì‘f«6Rï≥£#“ê†¢&WGW&‚vóB˜ˆ∆≈˜fñFVı˜F6µˆvVÊW&ñ2Ä¢WFFR¿¢6∆ñVÁB¿¢ÜVFW'2¿¢&6U˜W&¬¿¢7FGW5˜Fá2¿¢F6µˆñB¿¢6Fñˆ‚¿¢÷Ö˜vóE˜3÷ñÁBÜ÷Ö˜vóE˜2˜"÷ÇÑ≈T‘Ù‘ÖıtïEı2¬%TÂtïÙ‘ÖıtïEı2íí¿¢F6µˆÊ˜EˆWÜó7E˜6ˆgEˆfñ≈˜3◊F6µˆÊ˜EˆWÜó7E˜6ˆgEˆfñ≈˜2¿¢6ñ∆VÁE˜6ˆgEˆfñ√◊6ñ∆VÁE˜6ˆgEˆfñ¬¿¢ê†¢WÜ6WBWÜ6WFñˆ‚2S†¢∆7EˆW'"“b%ı5B∑Fá”¢∂W“ ¢∆≈ˆW'&˜'2ÊVÊBÜ∆7EˆW'"ê¢∆ˆrÁv&ÊñÊrÇ"W27&VFRWÜ6WFñˆ„¢W2"¬6Fñˆ‚¬Rê¢6ˆÁFñÁVP†¢ñb∆≈ˆW'&˜'3†¢FWFñ«2“%∆‚"Ê¶ˆñ‚Ü∆≈ˆW'&˜'5≤”S•“ê¢V«6S†¢FWFñ«2“∆7EˆW' †¢ñb''VÁví"ñ‚Ü6Fñˆ‚˜"""íÊ∆˜vW"Çì†¢ñbˆó5˜'VÁvï˜VÊfñ∆&∆U˜FWáBÜFWFñ«2ì†¢˜&˜fñFW%ˆ÷&µˆfñ«W&RÇ''VÁvïˆì'b"¬FWFñ«2ê¢ñb6ñ∆VÁE˜6ˆgEˆfñ¬˜"%TÂtïÙÑîDUıDT4ÖÙU%$ı%3†¢∆ˆrÁv&ÊñÊrÇ"W2ÜñFFV‚7&VFRfñ«W&S¢W2"¬6Fñˆ‚¬FWFñ«5≥£S“ê¢&WGW&‚f«6P†¢ñb'6˜&"ñ‚Ü6Fñˆ‚˜"""íÊ∆˜vW"ÇíÊBó5˜6˜&˜V˜∆Uˆ÷ˆFW&FñˆÂˆW'&˜"ÜFWFñ«2ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÖ˜6˜&˜V˜∆Uˆ÷ˆFW&FñˆÂ˜FWáBÇíê¢&WGW&‚f«6P¢ñb&ñÁf∆ñBí6ÜÊÊV«GóR"ñ‚ÜFWFñ«2˜"""íÊ∆˜vW"Çì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b.)™˚àÚ∂6FñˆÁ”¢2-]≠=ù]=‚˝Ì-ùM]˝≠›Ω6˜&]ù}›]MÌ-=˝›ÜñÁf∆ñBí6ÜÊÊV≈GóRí‚ ¢ê¢&WGW&‚f«6P¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb.)ÿ¬∂6FñˆÁ”¢›R=MΩÌ¬Ì}M-¬}M}2Â∆Á∂FWFñ«5≥£ì◊“"ê¢&WGW&‚f«6P†¶7ñÊ2FVb˜'VÂˆ«V÷ˆÊñ÷FU˜Ü˜FÚáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬ñ÷uˆ'óFW3¢'óFW2¬&ˆ◊C¢7G"¬GW&FñˆÂ˜3¢ñÁB¬7V7C¢7G"ì†¢ñbÊ˜B≈T‘ÙïÙ¥Uì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬«V÷¢≈T‘ÙïÙ¥Uí›R}M“"TÂb‚"ê¢&WGW&‚f«6P¢FF˜W&¬¬Fu˜W&¬“ˆñ÷vU˜&Vg5ˆf˜%ˆì'báWFFR¬ñ÷uˆ'óFW2ê¢ñ÷vU˜&Vb“FF˜W&¬˜"Fu˜W&¿¢GW&FñˆÂ˜2“ˆGW&FñˆÂˆf˜%ˆVÊvñÊRÇ&«V÷"¬GW&FñˆÂ˜2ê¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC”c„í26∆ñVÁC†¢&6R“vóB˜ñ6µˆ«V÷ˆ&6RÜ6∆ñVÁBê¢ñ∆ˆG2“∞¢Ñ≈T‘Ù5$TDUıDÇ¬∞¢&÷ˆFV¬#¢≈T‘Ù‘ÙDT¬¿¢'&ˆ◊B#¢&ˆ◊B¿¢&GW&Fñˆ‚#¢b'∂GW&FñˆÂ˜7◊2"¿¢&7V7E˜&FñÚ#¢7V7B¿¢&∂Wñg&÷W2#¢≤&g&÷S#¢≤'GóR#¢&ñ÷vR"¬'W&¬#¢ñ÷vU˜&Vg◊“¿¢“í¿¢Ñ≈T‘Ù5$TDUıDÇ¬∞¢&÷ˆFV¬#¢≈T‘Ù‘ÙDT¬¿¢'&ˆ◊B#¢&ˆ◊B¿¢&GW&Fñˆ‚#¢b'∂GW&FñˆÂ˜7◊2"¿¢&7V7E˜&FñÚ#¢7V7B¿¢&ñ÷vU˜&Vb#¢ñ÷vU˜&Vb¿¢“í¿¢–¢&WGW&‚&ˆˆ¬ÜvóBˆ7&VFUˆÊE˜ˆ∆≈ˆì'báWFFR¬&6R¬≈T‘ÙïÙ¥Uí¬ñ∆ˆG2¬¥≈T‘ı5DEU5ıDÖ“¬$«V÷ñ÷v^(i'fñFVÚ"íê†¶7ñÊ2FVb˜'VÂˆ6ˆ÷WEˆì'báWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬VÊvñÊS¢7G"¬ñ÷uˆ'óFW3¢'óFW2¬&ˆ◊C¢7G"¬GW&FñˆÂ˜3¢ñÁB¬7V7C¢7G"ì†¢VÊvñÊR“ÜVÊvñÊR˜"""íÊ∆˜vW"Çê†¢2	MΩÚ∂∆ñÊrı'VÁvíı6˜&›RÌ-˝-Ω˝]¬Ì=ÌÕ›ΩR≠ç›çÌ-≤≠¢]-√¢›ÌÕΩç}=]¬•TrÄ¢2Õ˝=≠‚=ç]¬}›ΩR˝ÌΩÚ¬]ΩÇ›-‚]}Ì˝›‚‡¢&W&VEˆÊ˜FR“" ¢ñbVÊvñÊRñ‚Ç&∂∆ñÊr"¬''VÁví"¬'6˜&"ì†¢ñ÷uˆ'óFW2¬&W&VEˆÊ˜FR“˜&W&Uˆì'e˜6˜W&6Uˆñ÷vRÜñ÷uˆ'óFW2¬7V7Bê¢ñb&W&VEˆÊ˜FS†¢∆ˆrÊñÊfÚÇ&ì'b6˜W&6R&W&VBf˜"W3¢W2"¬VÊvñÊR¬&W&VEˆÊ˜FRê†¢FF˜W&¬¬Fu˜W&¬“ˆñ÷vU˜&Vg5ˆf˜%ˆì'báWFFR¬ñ÷uˆ'óFW2ê¢&uˆ#cB“&6ScBÊ#cFVÊ6ˆFRÜñ÷uˆ'óFW2íÊFV6ˆFRÇ&66ñí"ê†¢ñbVÊvñÊR”“'6˜&#†¢B“ˆGW&FñˆÂˆf˜%ˆVÊvñÊRÇ'6˜&"¬GW&FñˆÂ˜2ê†¢2	˝‚M≠-2-ççR-]-Ì"6ˆ÷WBÙ˜V‰í˜c˜fñFV˜2	›	R˝ç›çÕ]#†¢2“F˜÷∆WfV¬ñ÷vU˜W&¬Úñ÷vU˜W&«0¢2“ñÁWEˆñ÷vP¢2“GW&Fñˆ‡¢2“7V7E˜&Fñ¢2	˝‚M≠-26ˆ÷WBÙ˜V‰í&˜áí"-ççRΩÌ=RÌmçM]"ñÁWE˜&VfW&VÊ6R≠¢

-
	Ì	≠
2¿¢2›R≠¢Ì≠]≠"‚	˝Ì›-ÌÕ2˝Ì=]¬"˝]-=‚Ì}]]M¬7G&ñÊrFF◊W&¬¿¢2}-]¬7G&ñÊr]r6V6ˆÊG2¬}-]¬◊V«Fó'B›Mù≤≠¢}˝›Ìí-ç›"‡¢6˜&ˆ'óFW2¬6˜&ˆ÷ñ÷R¬6˜&ˆFF˜W&¬¬6ó¶R“˜&W&U˜6˜&˜&VfW&VÊ6Uˆñ÷vRÜñ÷uˆ'óFW2¬7V7Bê†¢ñ∆ˆG2“µ–†¢FVbˆFEˆß6ˆ‚áñ∆ˆC¢Fñ7Bì†¢f˜"&Bñ‚Ç&ñÁWEˆñ÷vR"¬&GW&Fñˆ‚"¬&7V7E˜&FñÚ"¬&ñ÷vU˜W&¬"¬&ñ÷vU˜W&«2"ì†¢ñ∆ˆBÁ˜Ü&B¬ÊˆÊRê¢ñ∆ˆG2ÊVÊBÇÖ4ı$Ù5$TDUıDÇ¬ñ∆ˆBíê†¢FVbˆFEˆ◊V«Fó'Bá6V6ˆÊG5˜f«VS¢7G"¬ÊˆÊR“ÊˆÊRì†¢FF“∞¢&÷ˆFV¬#¢4ı$Ù‘ÙDT¬¿¢'&ˆ◊B#¢&ˆ◊B¿¢'6ó¶R#¢6ó¶R¿¢–¢ñb6V6ˆÊG5˜f«VS†¢FF≤'6V6ˆÊG2%““6V6ˆÊG5˜f«VP¢fñ∆W2“∞¢&ñÁWE˜&VfW&VÊ6R#¢Ç'&VfW&VÊ6RÊßr"¬6˜&ˆ'óFW2¬6˜&ˆ÷ñ÷R˜"&ñ÷vRˆßVr"í¿¢–¢ñ∆ˆG2ÊVÊBÇÖ4ı$Ù5$TDUıDÇ¬≤%ıˆ◊V«Fó'B#¢≤&FF#¢FF¬&fñ∆W2#¢fñ∆W7◊“íê†¢2í	Ì›Ì-›Ìí-ç›#¢ñÁWE˜&VfW&VÊ6R≠¢7G&ñÊrÜFFU$¬í≤6V6ˆÊG2≤6ó¶R‡¢ˆFEˆß6ˆ‚á∞¢&÷ˆFV¬#¢4ı$Ù‘ÙDT¬¿¢'&ˆ◊B#¢&ˆ◊B¿¢&ñÁWE˜&VfW&VÊ6R#¢6˜&ˆFF˜W&¬¿¢'6V6ˆÊG2#¢7G"ÜBí¿¢'6ó¶R#¢6ó¶R¿¢“ê†¢2"í
-‚mR]r6V6ˆÊG2(	B]ΩÇ≠›≤¬›ÌÕΩç}=]"MΩç-]ΩÕ›Ì-¬‡¢ˆFEˆß6ˆ‚á∞¢&÷ˆFV¬#¢4ı$Ù‘ÙDT¬¿¢'&ˆ◊B#¢&ˆ◊B¿¢&ñÁWE˜&VfW&VÊ6R#¢6˜&ˆFF˜W&¬¿¢'6ó¶R#¢6ó¶R¿¢“ê†¢22í	}˝›Ìí-ç›"}]]r˝=Ωç}›ΩíFV∆Vw&“U$¬¬]ΩÇ&˜áí›RΩÌç"FFU$¬‡¢ñbFu˜W&¬ÊBFu˜W&¬Á7F'G7vóFÇÇ&áGG3¢ÚÚ"ì†¢ˆFEˆß6ˆ‚á∞¢&÷ˆFV¬#¢4ı$Ù‘ÙDT¬¿¢'&ˆ◊B#¢&ˆ◊B¿¢&ñÁWE˜&VfW&VÊ6R#¢Fu˜W&¬¿¢'6V6ˆÊG2#¢7G"ÜBí¿¢'6ó¶R#¢6ó¶R¿¢“ê¢ˆFEˆß6ˆ‚á∞¢&÷ˆFV¬#¢4ı$Ù‘ÙDT¬¿¢'&ˆ◊B#¢&ˆ◊B¿¢&ñÁWE˜&VfW&VÊ6R#¢Fu˜W&¬¿¢'6ó¶R#¢6ó¶R¿¢“ê†¢2Bí◊V«Fó'B›-ç›"≠¢}˝›Ìíf∆∆&6≤‡¢ˆFEˆ◊V«Fó'Bá7G"ÜBíê¢ˆFEˆ◊V«Fó'BÑÊˆÊRê†¢6˜&ˆˆ≤“vóBˆ7&VFUˆÊE˜ˆ∆≈ˆì'bÄ¢WFFR¿¢4Ù‘UEÙ$4UıU$¬¿¢4ı$ÙïÙ¥Uí¿¢ñ∆ˆG2¿¢µ4ı$ı5DEU5ıDÇ¬"˜c˜fñFV˜2˜∂ñG“"¬"˜c˜F6∑2˜∂ñG“%“¿¢%6˜&"ñ÷v^(i'fñFVÚç]rΩÌM]íí"¿¢ê¢ñbÜÊ˜B6˜&ˆˆ≤íÊB4ı$ÙUDıÙdƒƒ$4µÙ¥ƒî‰s†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.(jÆ˚àÚ6˜&]ù}›]MÌ-=˝›çΩÇ›RÌ}MΩ}M}2‚	˝]]≠ΩÌ}Ì¬›∂∆ñÊrñ÷v^(i'fñFVÚ≠¢]}]"‚ ¢ê¢&WGW&‚&ˆˆ¬ÜvóB˜'VÂˆ6ˆ÷WEˆì'báWFFR¬6ˆÁFWáB¬&∂∆ñÊr"¬ñ÷uˆ'óFW2¬&ˆ◊B¬GW&FñˆÂ˜2¬7V7Bíê¢&WGW&‚&ˆˆ¬á6˜&ˆˆ≤ê†¢ñbVÊvñÊR”“&∂∆ñÊr#†¢2∂∆ñÊrÙ6ˆ÷WB7W'&VÁF«íf∆ñFFW2&ñ÷vR"2U$¬‚6VÊFñÊr&r&6ScB6‚&P¢266WFVB'íFÜR7&VFRVÊGˆñÁB'WBFÜV‚fñ«27ñÊ6á&ˆÊ˜W6«ívóFÄ¢2ñÁf∆ñE&÷WFW%f«VRÂW&ƒñ∆∆Vv¬‚&VfW"FÜRV&∆ñ2FV∆Vw&“fñ∆RU$¬‡¢B“7G"ÖˆGW&FñˆÂˆf˜%ˆVÊvñÊRÇ&∂∆ñÊr"¬GW&FñˆÂ˜2íê¢6fU˜&ˆ◊B“á&ˆ◊B˜"""íÁ7G&óÇê¢ñbì%eÙ¥ƒî‰uı4dUı$Ù’Eı5TddïÇÊBì%eÙ¥ƒî‰uı4dUı$Ù’Eı5TddïÇÊ∆˜vW"ÇíÊ˜Bñ‚6fU˜&ˆ◊BÊ∆˜vW"Çì†¢6fU˜&ˆ◊B“á6fU˜&ˆ◊B≤#≤"≤ì%eÙ¥ƒî‰uı4dUı$Ù’Eı5TddïÇíÁ7G&óÇ#≤"ê†¢∂∆ñÊuˆñ÷vU˜&Vb“Fu˜W&¬ñbáFu˜W&¬ÊBFu˜W&¬Á7F'G7vóFÇÇ&áGG3¢ÚÚ"ííV«6RFF˜W&¿¢ñ∆ˆG2“∞¢Ä¢¥ƒî‰uÙ5$TDUıDÇ¿¢∞¢&÷ˆFV≈ˆÊ÷R#¢¥ƒî‰uÙ‘ÙDT¬¿¢'&ˆ◊B#¢6fU˜&ˆ◊B¿¢&ÊVvFófU˜&ˆ◊B#¢&&«W''í¬∆˜rV∆óGí¬Fó7F˜'FVBf6W2¬WáG&∆ñ÷'2¬vFW&÷&≤¬FWáB˜fW&∆í"¿¢&6fu˜66∆R#¢„R¿¢&ñ÷vR#¢∂∆ñÊuˆñ÷vU˜&Vb¿¢&GW&Fñˆ‚#¢B¿¢&7V7E˜&FñÚ#¢7V7B¿¢&÷ˆFR#¢'7FB"¿¢“¿¢í¿¢–†¢2Wá∆ñ6óB∂∆ñÊr7Fñˆ‚◊W7B&V÷ñ‚∂∆ñÊs¢ÊÚ'VÁvíı6˜&f∆∆&6≤‡¢&WGW&‚&ˆˆ¬ÜvóBˆ7&VFUˆÊE˜ˆ∆≈ˆì'bÄ¢WFFR¿¢4Ù‘UEÙ$4UıU$¬¿¢¥ƒî‰uÙïÙ¥Uí¿¢ñ∆ˆG2¿¢≤"ˆ∂∆ñÊr˜c˜fñFV˜2ˆñ÷vS'fñFVÚ˜∂ñG“"¬¥ƒî‰uı5DEU5ıDÇ¬"ˆ∂∆ñÊr˜c˜fñFV˜2˜∂ñG“"¬"˜c˜F6∑2˜∂ñG“"¬"˜c˜fñFV˜2˜∂ñG“%“¿¢$∂∆ñÊrñ÷v^(i'fñFVÚ"¿¢íê†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	›]ç}-]-›Ωí6ˆ÷WBñ÷v^(i'fñFVÚM-çmÌ¢‚"ê¢&WGW&‚f«6P††¶7ñÊ2FVb˜'VÂˆ6ˆ÷WE˜FWáE˜fñFVÚáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬VÊvñÊS¢7G"¬&ˆ◊C¢7G"¬GW&FñˆÂ˜3¢ñÁB¬7V7C¢7G"í”‚&ˆˆ√†¢""%FWáB◊FÚ◊fñFVÚFá&˜VvÇ6ˆ÷WDì¢6˜&"¬∂∆ñÊr¬˜"'VÁví‚"" ¢VÊvñÊR“ÜVÊvñÊR˜"""íÊ∆˜vW"ÇíÁ7G&óÇì≤&ˆ◊B“á&ˆ◊B˜"""íÁ7G&óÇê¢ñbÊ˜B&ˆ◊C†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	˝=-Ìí}˝ÌMΩÚ-çM]‚‚"ê¢&WGW&‚f«6P¢ñbVÊvñÊR”“'6˜&"ÊB˜&ˆ◊Eˆ∆ñ∂V«ïˆÜ5˜V˜∆Rá&ˆ◊Bì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ6˜&"MÌ-=˝›-ÌΩÕ≠‚MΩÚm]“]rΩÌM]í‚	ç˝ÌΩÕ}=ù-R∂∆ñÊrçΩÇ'VÁví‚"ê¢&WGW&‚f«6P¢vóB6ˆÁFWáBÊ&˜BÁ6VÊEˆ6ÜEˆ7Fñˆ‚áWFFRÊVffV7FófUˆ6ÜBÊñB¬6ÜD7Fñˆ‚Â$T4ı$EıdîDTÚê¢ñbVÊvñÊR”“''VÁví#†¢&WGW&‚&ˆˆ¬ÜvóB˜'VÂ˜'VÁvï˜fñFVÚáWFFR¬6ˆÁFWáB¬&ˆ◊B¬GW&FñˆÂ˜2¬7V7Bíê¢ñbVÊvñÊR”“'6˜&#†¢B“ˆGW&FñˆÂˆf˜%ˆVÊvñÊRÇ'6˜&"¬GW&FñˆÂ˜2ì≤6ó¶R¬Ú¬Ú“˜6˜&˜6ó¶Uˆf˜%ˆ7V7BÜ7V7Bê¢ñ∆ˆG2“∞¢Ö4ı$Ù5$TDUıDÇ¬≤&÷ˆFV¬#¢4ı$Ù‘ÙDT¬¬'&ˆ◊B#¢&ˆ◊B¬'6V6ˆÊG2#¢7G"ÜBí¬'6ó¶R#¢6ó¶W“í¿¢Ö4ı$Ù5$TDUıDÇ¬≤&÷ˆFV¬#¢4ı$Ù‘ÙDT¬¬'&ˆ◊B#¢&ˆ◊B¬'6V6ˆÊG2#¢B¬'6ó¶R#¢6ó¶W“í¿¢Ö4ı$Ù5$TDUıDÇ¬≤&÷ˆFV¬#¢4ı$Ù‘ÙDT¬¬'&ˆ◊B#¢&ˆ◊B¬'6ó¶R#¢6ó¶W“í¿¢–¢&WGW&‚&ˆˆ¬ÜvóBˆ7&VFUˆÊE˜ˆ∆≈ˆì'báWFFR¬4Ù‘UEÙ$4UıU$¬¬4ı$ÙïÙ¥Uí¬ñ∆ˆG2¬µ4ı$ı5DEU5ıDÇ¬"˜c˜fñFV˜2˜∂ñG“"¬"˜c˜F6∑2˜∂ñG“%“¬%6˜&"FWáN(i'fñFVÚ+r]rΩÌM]í"íê¢ñbVÊvñÊR”“&∂∆ñÊr#†¢B“7G"ÖˆGW&FñˆÂˆf˜%ˆVÊvñÊRÇ&∂∆ñÊr"¬GW&FñˆÂ˜2íê¢ñ∆ˆG2“∞¢Ñ¥ƒî‰uıDUÖEÙ5$TDUıDÇ¬≤&÷ˆFV¬#¢¥ƒî‰uÙ‘ÙDT¬¬'&ˆ◊B#¢&ˆ◊B¬&GW&Fñˆ‚#¢B¬&7V7E˜&FñÚ#¢7V7G“í¿¢Ç"ˆ∂∆ñÊr˜c˜fñFV˜2˜FWáC'fñFVÚ"¬≤&÷ˆFV¬#¢¥ƒî‰uÙ‘ÙDT¬¬'&ˆ◊B#¢&ˆ◊B¬&GW&Fñˆ‚#¢B¬&7V7E˜&FñÚ#¢7V7G“í¿¢Ñ¥ƒî‰uıDUÖEÙ5$TDUıDÇ¬≤'&ˆ◊B#¢&ˆ◊B¬&GW&Fñˆ‚#¢B¬&7V7E˜&FñÚ#¢7V7G“í¿¢–¢&WGW&‚&ˆˆ¬ÜvóBˆ7&VFUˆÊE˜ˆ∆≈ˆì'báWFFR¬4Ù‘UEÙ$4UıU$¬¬¥ƒî‰uÙïÙ¥Uí¬ñ∆ˆG2¬¥¥ƒî‰uıDUÖEı5DEU5ıDÇ¬"ˆ∂∆ñÊr˜c˜fñFV˜2˜FWáC'fñFVÚ˜∂ñG“"¬"ˆ∂∆ñÊr˜c˜fñFV˜2˜∂ñG“"¬"˜c˜F6∑2˜∂ñG“"¬"˜c˜fñFV˜2˜∂ñG“%“¬$∂∆ñÊrFWáN(i'fñFVÚ"íê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	›]ç}-]-›ΩíFWáN(i'fñFVÚM-çmÌ¢‚	MÌ-=˝›≤6˜&"]rΩÌM]í¬∂∆ñÊrÇ'VÁví‚"ê¢&WGW&‚f«6P†¶7ñÊ2FVb˜'VÂ˜'VÁvïˆ6ˆ÷WEˆÊñ÷FU˜Ü˜FÚáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬ñ÷uˆ'óFW3¢'óFW2¬&ˆ◊C¢7G"¬GW&FñˆÂ˜3¢ñÁB¬7V7C¢7G"í”‚&ˆˆ√†¢ñbÊ˜BÖ%TÂtïÙî‘tS%dîDTıÙT‰$ƒTBÊB%TÂtïıU4UÙ4Ù‘UBÊB4Ù‘UEÙïÙ¥Uíì†¢&WGW&‚f«6P¢ñbÊ˜B˜&˜fñFW%ˆó5ˆfñ∆&∆RÇ''VÁvïˆì'b"ì†¢∆ˆrÁv&ÊñÊrÇ%'VÁvíÙ6ˆ÷WB6∂óVC¢6ˆˆ∆F˜v‚W72"¬˜&˜fñFW%ˆ6ˆˆ∆F˜vÂˆ∆VgBÇ''VÁvïˆì'b"íê¢&WGW&‚f«6P†¢ñ÷uˆ'óFW2¬&WˆÊ˜FR“˜&W&Uˆì'e˜6˜W&6Uˆñ÷vRÜñ÷uˆ'óFW2¬7V7Bê¢ñb&WˆÊ˜FS†¢∆ˆrÊñÊfÚÇ%'VÁvíì'b6˜W&6R&W&VC¢W2"¬&WˆÊ˜FRê¢FF˜W&¬¬Fu˜W&¬“ˆñ÷vU˜&Vg5ˆf˜%ˆì'báWFFR¬ñ÷uˆ'óFW2ê†¢GW&Fñˆ‚“ˆGW&FñˆÂˆf˜%ˆVÊvñÊRÇ''VÁví"¬GW&FñˆÂ˜2ê¢&FñÚ“˜&Fñıˆf˜%ˆ7V7BÜ7V7Bê†¢ñ∆ˆG2“µ–¢2	MΩÚñ÷v^(i'fñFVÚ›6ˆ÷WB›Rç˝ÌΩÕ}=]¬vV„B„R˝]-Ω√¢2-Ì“}-‚Ì--]}]"ÊÚfñ∆&∆R6ÜÊÊV¬‡¢2vV„E˜GW&&ÚˆvV„6˜GW&&Ú(	B›ÌÕΩÕ›ΩR≠›MçM-≤MΩÚÌmç-Ω]›çÚMÌ-‚‡¢f˜"÷ˆFV¬ñ‚˜'VÁvïˆì'eˆ÷ˆFV≈ˆ6ÊFñFFW2Çì†¢2	Ì›Ì-›ÌíMÌÕ"'VÁvíí##B””b‡¢ñ∆ˆG2ÊVÊBÇÖ%TÂtïÙ4Ù‘UEÙ5$TDUıDÇ¬∞¢&÷ˆFV¬#¢÷ˆFV¬¿¢'&ˆ◊Dñ÷vR#¢FF˜W&¬¿¢'&ˆ◊EFWáB#¢&ˆ◊B¿¢&GW&Fñˆ‚#¢GW&Fñˆ‚¿¢'&FñÚ#¢&FñÚ¿¢'vFW&÷&≤#¢f«6R¿¢“íê¢2
MÌÕ"&ˆ◊Dñ÷vR≠¢Õç"˜6óFñˆ„÷fó'7B(	B›≠-ç-Ω]›-]“7G&ñÊrÇ-çΩÕ›]R››]≠Ì-ÌΩR˝Ì≠Ç‡¢ñ∆ˆG2ÊVÊBÇÖ%TÂtïÙ4Ù‘UEÙ5$TDUıDÇ¬∞¢&÷ˆFV¬#¢÷ˆFV¬¿¢'&ˆ◊Dñ÷vR#¢∑≤'W&í#¢FF˜W&¬¬'˜6óFñˆ‚#¢&fó'7B'’“¿¢'&ˆ◊EFWáB#¢&ˆ◊B¿¢&GW&Fñˆ‚#¢GW&Fñˆ‚¿¢'&FñÚ#¢&FñÚ¿¢'vFW&÷&≤#¢f«6R¿¢“íê¢26Ê∂Uˆ66Rf∆∆&6≤MΩÚÌ-Õ]-çÕÌ-Ç}›ΩÕÇ˝Ì≠Ç‡¢ñ∆ˆG2ÊVÊBÇÖ%TÂtïÙ4Ù‘UEÙ5$TDUıDÇ¬∞¢&÷ˆFV¬#¢÷ˆFV¬¿¢'&ˆ◊Eˆñ÷vR#¢FF˜W&¬¿¢'&ˆ◊E˜FWáB#¢&ˆ◊B¿¢&GW&Fñˆ‚#¢GW&Fñˆ‚¿¢'&FñÚ#¢&FñÚ¿¢'vFW&÷&≤#¢f«6R¿¢“íê†¢2	}˝›Ìí-ç›"}]]rFV∆Vw&“U$¬¬]ΩÇ6ˆ÷WB›R˝çÕ]"FF◊W&í‡¢ñbFu˜W&¬ÊBFu˜W&¬Á7F'G7vóFÇÇ&áGG3¢ÚÚ"ì†¢f˜"÷ˆFV¬ñ‚˜'VÁvïˆì'eˆ÷ˆFV≈ˆ6ÊFñFFW2Çì†¢ñ∆ˆG2ÊVÊBÇÖ%TÂtïÙ4Ù‘UEÙ5$TDUıDÇ¬∞¢&÷ˆFV¬#¢÷ˆFV¬¿¢'&ˆ◊Dñ÷vR#¢Fu˜W&¬¿¢'&ˆ◊EFWáB#¢&ˆ◊B¿¢&GW&Fñˆ‚#¢GW&Fñˆ‚¿¢'&FñÚ#¢&FñÚ¿¢'vFW&÷&≤#¢f«6R¿¢“íê†¢&WGW&‚vóBˆ7&VFUˆÊE˜ˆ∆≈ˆì'bÄ¢WFFR¿¢4Ù‘UEÙ$4UıU$¬¿¢4Ù‘UEÙïÙ¥Uí¿¢ñ∆ˆG2¿¢µ%TÂtïÙ4Ù‘UEı5DEU5ıDÇ¬"˜'VÁvñ÷¬˜c˜F6∑2˜∂ñG“"¬"˜c˜F6∑2˜∂ñG“%“¿¢%'VÁvíÙ6ˆ÷WBñ÷v^(i'fñFVÚ"¿¢F6µˆÊ˜EˆWÜó7E˜6ˆgEˆfñ≈˜3’%TÂtïıD4µÙ‰ıEÙUÑï5EÙdƒƒ$4µı2¿¢6ñ∆VÁE˜6ˆgEˆfñ√’G'VR¿¢ê†¢2)H)H)H)H)H)H)H)H)H'VÁvì¢›çÕmçÚ}==m]››Ì=‚MÌ-‚Üñ÷v^(i'fñFVÚí)H)H)H)H)H)H)H)H)H ¶7ñÊ2FVb˜'VÂ˜'VÁvïˆFó&V7EˆÊñ÷FU˜Ü˜FÚáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬ñ÷uˆ'óFW3¢'óFW2¬&ˆ◊C¢7G"¬GW&FñˆÂ˜3¢ñÁB¬7V7C¢7G"í”‚&ˆˆ√†¢""$ˆffñ6ñ¬'VÁvíñ÷v^(i'fñFVÚW6ñÊrWÜV÷W&¬W∆ˆB≤F6≤ˆ∆∆ñÊr‚"" ¢ñbÊ˜BÖ%TÂtïÙDï$T5EÙT‰$ƒTBÊB%TÂtïÙïÙ¥Uíì†¢&WGW&‚f«6P†¢ñ÷uˆ'óFW2¬&WˆÊ˜FR“˜&W&Uˆì'e˜6˜W&6Uˆñ÷vRÜñ÷uˆ'óFW2¬7V7Bê¢ñb&WˆÊ˜FS†¢∆ˆrÊñÊfÚÇ%'VÁvíFó&V7Bì'b6˜W&6R&W&VC¢W2"¬&WˆÊ˜FRê¢÷ñ÷U˜GóR“6Êñfeˆñ÷vUˆ÷ñ÷RÜñ÷uˆ'óFW2ê¢ñb÷ñ÷U˜GóRÊ˜Bñ‚≤&ñ÷vRˆßVr"¬&ñ÷vR˜Êr"¬&ñ÷vR˜vV''”†¢÷ñ÷U˜GóR“&ñ÷vRˆßVr ¢WáFVÁ6ñˆ‚“≤&ñ÷vRˆßVr#¢&ßr"¬&ñ÷vR˜Êr#¢'Êr"¬&ñ÷vR˜vV'#¢'vV''“ÊvWBÜ÷ñ÷U˜GóR¬&ßr"ê¢fñ∆VÊ÷R“b''VÁvïˆñÁWBÁ∂WáFVÁ6ñˆÁ“ ¢&FñÚ“˜'VÁvïˆFó&V7E˜&FñÚÜ7V7Bê¢GW&Fñˆ‚“÷ÇÉ"¬÷ñ‚É¬ñÁBÜGW&FñˆÂ˜2˜"Rííê¢∆7EˆW'"“" †¢f˜"÷ˆFV¬ñ‚˜'VÁvïˆFó&V7Eˆì'eˆ÷ˆFV≈ˆ6ÊFñFFW2Çì†¢G'ì†¢7ñÊ2vóFÇ˜'VÁvïˆˆffñ6ñ≈ˆ6∆ñVÁBÇí2's†¢F6µˆñB“vóB'rÊ7&VFUˆñ÷vU˜Fı˜fñFVÚÄ¢ñ÷vUˆ'óFW3÷ñ÷uˆ'óFW2¿¢fñ∆VÊ÷S÷fñ∆VÊ÷R¿¢÷ñ÷U˜GóS÷÷ñ÷U˜GóR¿¢&ˆ◊E˜FWáC◊&ˆ◊B¿¢÷ˆFV√÷÷ˆFV¬¿¢&FñÛ◊&FñÚ¿¢GW&Fñˆ„÷GW&Fñˆ‚¿¢VÊGˆñÁC’%TÂtïÙì%eıDÇ¿¢W∆ˆEˆVÊGˆñÁC’%TÂtïıUƒÙEıDÇ¿¢ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b.(˚2'VÁví∂÷ˆFV«”¢ç}Ìm]›çR}==m]›‚¬}M}˝ç›˝-‚	ÌmçM‚]}=ΩÕ-.(
b ¢ê¢&W7V«B“vóB'rÁvóEˆf˜%˜F6≤áF6µˆñB¬Fñ÷V˜WE˜3’%TÂtïÙ‘ÖıtïEı2ê†¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC”#C„¬fˆ∆∆˜u˜&VFó&V7G3’G'VRí2F≈ˆ6∆ñVÁC†¢vóB˜&W«ï˜fñFVıˆg&ˆ’˜W&¬Ä¢WFFR¬F≈ˆ6∆ñVÁB¬&W7V«BÊfó'7Eˆ˜WGWB¿¢.) Ç	Ìmç-ç≤MÌ-‚)»R+r˜vW&VB'í'VÁví"¿¢F6µˆñC◊F6µˆñB¿¢ê¢˜&˜fñFW%ˆ÷&µ˜7V66W72Ç''VÁvïˆFó&V7B"ê¢&WGW&‚G'VP¢WÜ6WB'VÁvîîW'&˜"2S†¢∆7EˆW'"“7G"ÜRê¢∆ˆrÁv&ÊñÊrÇ%'VÁvíFó&V7Bì'b÷ˆFV√“W2fñ∆VC¢W2"¬÷ˆFV¬¬Rê¢2WFÜVÁFñ6Fñˆ‚¬&ñ∆∆ñÊr¬÷ˆFW&Fñˆ‚ÊBñÁf∆ñB÷ñÁWBW'&˜'2&RÊ˜BfóÜVB'í7vóF6ÜñÊr÷ˆFV«2‡¢6ˆFR“ÜRÊfñ«W&Uˆ6ˆFR˜"""íÁWW"Çê¢ñbRÁ7FGW5ˆ6ˆFRñ‚≥C¬C¬C"¬C7“˜"6ˆFRÁ7F'G7vóFÇÇ%4dUEí"ì†¢˜&˜fñFW%ˆ∆7EˆW'&˜%≤''VÁvïˆFó&V7B%““∆7EˆW'%≥£s–¢6ˆÁFWáBÁW6W%ˆFF≤%˜'VÁvïˆFó&V7EˆÜ&E˜7F˜%““G'VP¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÖ˜'VÁvï˜W6W%ˆW'&˜%˜FWáBÜRíê¢&WGW&‚f«6P¢6ˆÁFñÁVP¢WÜ6WBWÜ6WFñˆ‚2S†¢∆7EˆW'"“7G"ÜRê¢∆ˆrÁv&ÊñÊrÇ%'VÁvíFó&V7Bì'bWÜ6WFñˆ‚÷ˆFV√“W3¢W2"¬÷ˆFV¬¬Rê¢6ˆÁFñÁVP†¢ñb∆7EˆW'#†¢˜&˜fñFW%ˆ∆7EˆW'&˜%≤''VÁvïˆFó&V7B%““∆7EˆW'%≥£s–¢˜&˜fñFW%ˆ÷&µˆfñ«W&RÇ''VÁvïˆFó&V7B"¬∆7EˆW'"ê¢&WGW&‚f«6P††¶7ñÊ2FVb˜'VÂ˜'VÁvïˆÊñ÷FU˜Ü˜FÚáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬ñ÷uˆ'óFW3¢'óFW2¬&ˆ◊C¢7G"¬GW&FñˆÂ˜3¢ñÁB¬7V7C¢7G"ì†¢vóB6ˆÁFWáBÊ&˜BÁ6VÊEˆ6ÜEˆ7Fñˆ‚áWFFRÊVffV7FófUˆ6ÜBÊñB¬6ÜD7Fñˆ‚Â$T4ı$EıdîDTÚê¢&ˆ◊B“á&ˆ◊B˜"&Êñ÷FRFÜRñÁWBÜ˜FÚvóFÇ7V'F∆R6÷W&÷˜Fñˆ‚¬∆ñfV∆ñ∂R÷ñ7&Ú÷÷˜fV÷VÁG3≤∂VWFÜR˜&ñvñÊ¬W'6ˆ‚¬FÚÊ˜BG&Á6f˜&“ñFVÁFóGí¬FÚÊ˜BFBÜˆÊRg&÷W2˜"Tí"íÁ7G&óÇê¢6V6ˆÊG2“ˆGW&FñˆÂˆf˜%ˆVÊvñÊRÇ''VÁví"¬GW&FñˆÂ˜2ê¢&FñÚ“˜&Fñıˆf˜%ˆ7V7BÜ7V7Bê¢&E˜7&5ˆÊ˜FR“ˆ∆ˆˆ∑5ˆ∆ñ∂U˜67&VVÁ6Ü˜Eˆ˜%ˆ&Eˆì'e˜6˜W&6RÜñ÷uˆ'óFW2ê¢ñb&E˜7&5ˆÊ˜FRÊBì%eıt$ÂÙ$Eı4ıU$4S†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ñbì%eÙ$Eı4ıU$4UıÙƒî5í”“&6µˆ6∆V‚#†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.(Kû˚àÚ"≤&E˜7&5ˆÊ˜FR≤%∆Â∆Ì	˝ççΩç-R}ç-ÌRMÌ-‚¬}-Ì≤˝ÌΩ=}ç-¬-çΩÕ›Ωí]}=ΩÕ-"‚"ê¢&WGW&‚f«6P¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.(Kû˚àÚ"≤&E˜7&5ˆÊ˜FR≤%∆Ì	˝ÌMÌΩm‚ÌÌ-≠2¬›‚≠}]--‚ÕÌm]"Ω-¬]=mR‚"ê†¢2cÉÉ¢ÌMçmçΩÕ›Ωí'VÁvíFWfV∆˜W"í(	BÌ›Ì-›ÌíÕç="‡¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç%˜'VÁvïˆFó&V7EˆÜ&E˜7F˜"¬ÊˆÊRê¢ñb%TÂtïÙDï$T5EÙdï%5BÊB%TÂtïÙDï$T5EÙT‰$ƒTBÊB%TÂtïÙïÙ¥Uì†¢G'ì†¢ñbvóB˜'VÂ˜'VÁvïˆFó&V7EˆÊñ÷FU˜Ü˜FÚáWFFR¬6ˆÁFWáB¬ñ÷uˆ'óFW2¬&ˆ◊B¬6V6ˆÊG2¬7V7Bì†¢˜&˜fñFW%ˆ÷&µ˜7V66W72Ç''VÁvïˆFó&V7B"ê¢&WGW&‚G'VP¢ñb6ˆÁFWáBÁW6W%ˆFFÁ˜Ç%˜'VÁvïˆFó&V7EˆÜ&E˜7F˜"¬f«6Rì†¢&WGW&‚f«6P¢˜&˜fñFW%ˆ÷&µˆfñ«W&RÇ''VÁvïˆFó&V7B"¬˜&˜fñFW%ˆ∆7EˆW'&˜"ÊvWBÇ''VÁvïˆFó&V7B"¬&Fó&V7Bì'bfñ∆VB"íê¢WÜ6WBWÜ6WFñˆ‚2S†¢˜&˜fñFW%ˆ÷&µˆfñ«W&RÇ''VÁvïˆFó&V7B"¬7G"ÜRíê¢∆ˆrÁv&ÊñÊrÇ%'VÁvíFó&V7Bì'bfñ∆VC≤G'ññÊr6ˆ÷WC¢W2"¬Rê†¢26ˆ÷WBó2ˆÊ«íf∆∆&6≥≤óG2'VÁvíFó7G&ñ'WF˜"6ÜÊÊV¬6‚Fó6V"ñÊFWVÊFVÁF«í‡¢G'ì†¢ñbvóB˜'VÂ˜'VÁvïˆ6ˆ÷WEˆÊñ÷FU˜Ü˜FÚáWFFR¬6ˆÁFWáB¬ñ÷uˆ'óFW2¬&ˆ◊B¬6V6ˆÊG2¬7V7Bì†¢&WGW&‚G'VP¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ%'VÁví6ˆ÷WB&˜WFRfñ∆VC¢W2"¬Rê†¢ñbÜÊ˜B%TÂtïÙDï$T5EÙdï%5BíÊB%TÂtïÙDï$T5EÙT‰$ƒTBÊB%TÂtïÙïÙ¥Uì†¢G'ì†¢ñbvóB˜'VÂ˜'VÁvïˆFó&V7EˆÊñ÷FU˜Ü˜FÚáWFFR¬6ˆÁFWáB¬ñ÷uˆ'óFW2¬&ˆ◊B¬6V6ˆÊG2¬7V7Bì†¢˜&˜fñFW%ˆ÷&µ˜7V66W72Ç''VÁvïˆFó&V7B"ê¢&WGW&‚G'VP¢ñb6ˆÁFWáBÁW6W%ˆFFÁ˜Ç%˜'VÁvïˆFó&V7EˆÜ&E˜7F˜"¬f«6Rì†¢&WGW&‚f«6P¢WÜ6WBWÜ6WFñˆ‚2S†¢˜&˜fñFW%ˆ÷&µˆfñ«W&RÇ''VÁvïˆFó&V7B"¬7G"ÜRíê¢∆ˆrÁv&ÊñÊrÇ%'VÁvíFó&V7Bf∆∆&6≤fñ∆VC¢W2"¬Rê†¢ñb%TÂtïÙUDıÙdƒƒ$4µÙ¥ƒî‰rÊB4Ù‘UEÙïÙ¥Uì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÖ%TÂtïıT$ƒî5Ùdƒƒ$4µıDUÖBê¢&WGW&‚&ˆˆ¬ÜvóB˜'VÂˆ6ˆ÷WEˆì'báWFFR¬6ˆÁFWáB¬&∂∆ñÊr"¬ñ÷uˆ'óFW2¬&ˆ◊B¬6V6ˆÊG2¬7V7Bíê†¢ñb%TÂtïÙïÙ¥Uì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ	ÌMçmçΩÕ›Ωí'VÁví›R˝ç›˝≤}M}2‚	˝Ì-]Õ-R%TÂtî‘≈Ùïı4T5$UBÑVÁfó&ˆÊ÷VÁBı6V7&WBfñ∆RíÇí›≠]Mç-≥¢ˆFñu˜'VÁvíWFÇ"ê¢V«6S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ	MΩÚ˝Ì-Ì˝››Ì=‚MÌ-=˝¢'VÁvíMÌ-Õ-R%TÂtî‘≈Ùïı4T5$UB"&VÊFW"6V7&WBfñ∆R'VÁvíÊVÁbçΩÇVÁfó&ˆÊ÷VÁB‚"ê¢&WGW&‚f«6P†¢2)H)H)H)H)H)H)H)H)H	˝Ì≠=˝≠Ç˝ç›-Ìù≤)H)H)H)H)H)H)H)H)H ¶FVb˜∆Â˜'V"áFñW#¢7G"¬FW&”¢7G"í”‚ñÁC†¢FñW"“áFñW"˜"'&Ú"íÊ∆˜vW"Çê¢FW&““áFW&“˜"&÷ˆÁFÇ"íÊ∆˜vW"Çê¢&WGW&‚ñÁBÖƒÂı$î4UıD$ƒRÊvWBáFñW"¬ƒÂı$î4UıD$ƒU≤'&Ú%“íÊvWBáFW&“¬ƒÂı$î4UıD$ƒU≤'&Ú%’≤&÷ˆÁFÇ%“íê†¶FVb˜∆Â˜ñ∆ˆEˆÊEˆ÷˜VÁBáFñW#¢7G"¬÷ˆÁFá3¢ñÁBí”‚GW∆U∑7G"¬ñÁB¬7G%”†¢FW&““≥¢&÷ˆÁFÇ"¬3¢'V'FW""¬#¢'ñV"'“ÊvWBÜ÷ˆÁFá2¬&÷ˆÁFÇ"ê¢÷˜VÁB“˜∆Â˜'V"áFñW"¬FW&“ê¢FóF∆R“b-	˝ÌM˝ç≠∑FñW"ÁWW"Çó“á∑FW&◊“í ¢ñ∆ˆB“b'7V#ß∑FñW'”ß∂÷ˆÁFá7“ ¢&WGW&‚ñ∆ˆB¬÷˜VÁB¬FóF∆P†¶7ñÊ2FVb˜6VÊEˆñÁfˆñ6U˜'V"áFóF∆S¢7G"¬FW63¢7G"¬÷˜VÁE˜'V#¢ñÁB¬ñ∆ˆC¢7G"¬WFFS¢WFFRí”‚&ˆˆ√†¢G'ì†¢2]¬-Ì≠]“Ç-ΩÌ-2çrM-=Rç-Ì}›ç≠Ì"ç-Ωí$ıdîDU%ıDÙ¥T‚	ç	Ω	Ç›Ì-ΩíîÙÙ¥54ı$ıdîDU%ıDÙ¥T‚ê¢Fˆ∂V‚“Ö$ıdîDU%ıDÙ¥T‚˜"îÙÙ¥54ı$ıdîDU%ıDÙ¥T‚ê¢7W'"“Ñ5U%$T‰5íñbÑ5U%$T‰5íÊB5U%$T‰5í“%%T""íV«6RîÙÙ¥54Ù5U%$T‰5íí˜"%%T" †¢ñbÊ˜BFˆ∂V„†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ
‰∂76›R›-Ì]›ç›]"-Ì≠]›í‚"ê¢&WGW&‚f«6P†¢&ñ6W2“¥∆&V∆VE&ñ6RÜ∆&V√’ˆ66ñïˆ∆&V¬áFóF∆Rí¬÷˜VÁC÷ñÁBÜ÷˜VÁE˜'V"í¢ï–†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ïˆñÁfˆñ6RÄ¢FóF∆S◊FóF∆R¿¢FW67&óFñˆ„÷FW65≥£#SU“¿¢ñ∆ˆC◊ñ∆ˆB¿¢&˜fñFW%˜Fˆ∂V„◊Fˆ∂V‚¿¢7W'&VÊ7ì÷7W'"¿¢&ñ6W3◊&ñ6W2¿¢ÊVVEˆV÷ñ√‘f«6R¿¢ÊVVEˆÊ÷S‘f«6R¿¢ÊVVE˜ÜˆÊUˆÁV÷&W#‘f«6R¿¢ÊVVE˜6ÜóñÊuˆFG&W73‘f«6R¿¢ó5ˆf∆WÜñ&∆S‘f«6P¢ê¢&WGW&‚G'VP†¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç'6VÊEˆñÁfˆñ6RW'&˜#¢W2"¬Rê¢G'ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›R=MΩÌ¬-Ω--ç-¬}"‚"ê¢WÜ6WBWÜ6WFñˆ„†¢70¢&WGW&‚f«6P†¶7ñÊ2FVbˆÂ˜&V6ÜV6∂˜WBáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢G'ì†¢“WFFRÁ&Uˆ6ÜV6∂˜WE˜VW'ê¢vóBÊÁ7vW"Üˆ≥’G'VRê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç'&V6ÜV6∂˜WBW'&˜#¢W2"¬Rê†¶7ñÊ2FVbˆÂ˜7V66W76gV≈˜ñ÷VÁBáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢G'ì†¢7“WFFRÊ÷W76vRÁ7V66W76gV≈˜ñ÷VÁ@¢ñ∆ˆB“7ÊñÁfˆñ6U˜ñ∆ˆB˜"" ¢F˜F≈ˆ÷ñÊ˜"“7ÁF˜F≈ˆ÷˜VÁB˜" ¢'V"“F˜F≈ˆ÷ñÊ˜"Ú„ ¢VñB“WFFRÊVffV7FófU˜W6W"Êñ@†¢ñbñ∆ˆBÁ7F'G7vóFÇÇ'7V#¢"ì†¢Ú¬FñW"¬÷ˆÁFá2“ñ∆ˆBÁ7∆óBÇ#¢"¬"ê¢÷ˆÁFá2“ñÁBÜ÷ˆÁFá2ê¢VÁFñ¬“7FófFU˜7V'67&óFñˆÂ˜vóFÖ˜FñW"áVñB¬FñW"¬÷ˆÁFá2ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb.)»R	˝ÌM˝ç≠∑FñW"ÁWW"Çó“≠-ç-çÌ-›M‚∑VÁFñ¬Á7G&gFñ÷RÇrUí“V““VBró“Â∆Ô	˙©í	≠]Mç-≤›}çΩ]›≥¢µ5T%45$ïDîÙÂÙ5$TDïE2ÊvWBÇáFñW"˜"""íÊ∆˜vW"Çí¬í¢ñÁBÜ÷ˆÁFá2ó“≠‚"ê¢&WGW&‡†¢ñbñ∆ˆBÁ7F'G7vóFÇÇ'F˜W¢"ì†¢G'ì†¢Ú¬7&VFóG5˜2¬'V%˜2“ñ∆ˆBÁ7∆óBÇ#¢"¬"ê¢&W6ˆ«fVB“ˆ7&VFóE˜6µ˜&W6ˆ«fRÜñÁBÜ7&VFóG5˜2í¬ñÁBá'V%˜2íê¢ñb&W6ˆ«fVC†¢7&VFóG2¬WáV7FVE˜'V"“&W6ˆ«fV@¢˜v∆∆WE˜F˜F≈ˆFBáVñB¬ˆ7&VFóG5˜Fı˜W6BÜ7&VFóG2íê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b.)»R	Ì˝Ω-˝ÌçΩ=˝]ç›‚‚	›}çΩ]›„¢∂7&VFóG7“≠]Mç-Ì"}∂WáV7FVE˜'V'“(+“‚ ¢ê¢&WGW&‡¢WÜ6WBWÜ6WFñˆ„†¢∆ˆrÊWÜ6WFñˆ‚Ç$fñ∆VBFÚ'6RF˜Wñ∆ˆC¢W2"¬ñ∆ˆBê†¢2	ΩÌÌRç›ÌRñ∆ˆB(	B˝Ì˝ÌΩ›]›çR]Mç›Ì=‚≠Ìç]ΩÕ≠ ¢W6B“ˆ7&VFóG5˜Fı˜W6Bá'V"ê¢˜v∆∆WE˜F˜F≈ˆFBáVñB¬W6Bê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb/	˘+2	˝Ì˝ÌΩ›]›çS¢∑'V#¢„g“(+“‚	›}çΩ]›„¢µˆ7&VFóG5ˆf◊Eˆg&ˆ’˜W6BáW6Bó“‚"ê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç'7V66W76gV≈˜ñ÷VÁBÜÊF∆W"W'&˜#¢W2"¬Rê††¢2)H)H)H)H)H)H)H)H)H7'óFÙ&˜B)H)H)H)H)H)H)H)H)H §5%ïDııïÙïıDÙ¥T‚“˜2ÊVÁfó&ˆ‚ÊvWBÇ$5%ïDııïÙïıDÙ¥T‚"¬""íÁ7G&óÇê§5%ïDıÙ$4R“&áGG3¢Ú˜íÊ7'óBÊ&˜Bˆí •DÙÂıU4Eı$DR“f∆ˆBÜ˜2ÊVÁfó&ˆ‚ÊvWBÇ%DÙÂıU4Eı$DR"¬#R„"í˜"#R„"í2}˝›Ìí≠=†¶7ñÊ2FVbˆ7'óFıˆ7&VFUˆñÁfˆñ6RáW6Eˆ÷˜VÁC¢f∆ˆB¬76WC¢7G"“%U4EB"¬FW67&óFñˆ„¢7G"“""í”‚GW∆U∑7G'ƒÊˆÊR¬7G'ƒÊˆÊR¬f∆ˆB¬7G%”†¢ñbÊ˜B5%ïDııïÙïıDÙ¥T„†¢&WGW&‚ÊˆÊR¬ÊˆÊR¬„¬76W@¢G'ì†¢ñ∆ˆB“≤&76WB#¢76WB¬&÷˜VÁB#¢&˜VÊBÜf∆ˆBáW6Eˆ÷˜VÁBí¬"í¬&FW67&óFñˆ‚#¢FW67&óFñˆ‚˜"%F˜◊W'–¢ÜVFW'2“≤$7'óFÚ’í‘í’Fˆ∂V‚#¢5%ïDııïÙïıDÙ¥TÁ–¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC”3„í26∆ñVÁC†¢"“vóB6∆ñVÁBÁ˜7BÜb'¥5%ïDıÙ$4W“ˆ7&VFTñÁfˆñ6R"¬ÜVFW'3÷ÜVFW'2¬ß6ˆ„◊ñ∆ˆBê¢¢“"Êß6ˆ‚Çê¢ˆ≤“¢ÊvWBÇ&ˆ≤"íó2G'VP¢ñbÊ˜Bˆ≥†¢&WGW&‚ÊˆÊR¬ÊˆÊR¬„¬76W@¢&W2“¢ÊvWBÇ'&W7V«B"¬∑“ê¢&WGW&‚7G"á&W2ÊvWBÇ&ñÁfˆñ6UˆñB"íí¬&W2ÊvWBÇ'ï˜W&¬"í¬f∆ˆBá&W2ÊvWBÇ&÷˜VÁB"¬W6Eˆ÷˜VÁBíí¬&W2ÊvWBÇ&76WB"í˜"76W@¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç&7'óFÚ7&VFRW'&˜#¢W2"¬Rê¢&WGW&‚ÊˆÊR¬ÊˆÊR¬„¬76W@†¶7ñÊ2FVbˆ7'óFıˆvWEˆñÁfˆñ6RÜñÁfˆñ6UˆñC¢7G"í”‚Fñ7B¬ÊˆÊS†¢ñbÊ˜B5%ïDııïÙïıDÙ¥T„†¢&WGW&‚ÊˆÊP¢G'ì†¢ÜVFW'2“≤$7'óFÚ’í‘í’Fˆ∂V‚#¢5%ïDııïÙïıDÙ¥TÁ–¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC”#„í26∆ñVÁC†¢"“vóB6∆ñVÁBÊvWBÜb'¥5%ïDıÙ$4W“ˆvWDñÁfˆñ6W3ˆñÁfˆñ6UˆñG3◊∂ñÁfˆñ6UˆñG“"¬ÜVFW'3÷ÜVFW'2ê¢¢“"Êß6ˆ‚Çê¢ñbÊ˜B¢ÊvWBÇ&ˆ≤"ì†¢&WGW&‚ÊˆÊP¢óFV◊2“Ü¢ÊvWBÇ'&W7V«B"¬∑“í˜"∑“íÊvWBÇ&óFV◊2"¬µ“ê¢&WGW&‚óFV◊5≥“ñbóFV◊2V«6RÊˆÊP¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç&7'óFÚvWBW'&˜#¢W2"¬Rê¢&WGW&‚ÊˆÊP†¶7ñÊ2FVb˜ˆ∆≈ˆ7'óFıˆñÁfˆñ6RÜ6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬6ÜEˆñC¢ñÁB¬÷W76vUˆñC¢ñÁB¬W6W%ˆñC¢ñÁB¬ñÁfˆñ6UˆñC¢7G"¬W6Eˆ÷˜VÁC¢f∆ˆBì†¢G'ì†¢f˜"Úñ‚&ÊvRÉ#ì¢2„"Õç›="˝Çm}M]m≠P¢ñÁb“vóBˆ7'óFıˆvWEˆñÁfˆñ6RÜñÁfˆñ6UˆñBê¢7B“ÜñÁb˜"∑“íÊvWBÇ'7FGW2"¬""íÊ∆˜vW"ÇíñbñÁbV«6R" ¢ñb7B”“'ñB#†¢˜v∆∆WE˜F˜F≈ˆFBáW6W%ˆñB¬f∆ˆBáW6Eˆ÷˜VÁBíê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóB6ˆÁFWáBÊ&˜BÊVFóEˆ÷W76vU˜FWáBÜ6ÜEˆñC÷6ÜEˆñB¬÷W76vUˆñC÷÷W76vUˆñB¿¢FWáC÷b.)»R7'óFÙ&˜C¢˝Ω-b˝ÌM--]mM“‚	›}çΩ]›„¢µˆ7&VFóG5ˆf◊Eˆg&ˆ’˜W6BÜf∆ˆBáW6Eˆ÷˜VÁBíó“‚"ê¢&WGW&‡¢ñb7Bñ‚Ç&Wáó&VB"¬&6Ê6V∆∆VB"¬&6Ê6V∆VB"¬&fñ∆VB"ì†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóB6ˆÁFWáBÊ&˜BÊVFóEˆ÷W76vU˜FWáBÜ6ÜEˆñC÷6ÜEˆñB¬÷W76vUˆñC÷÷W76vUˆñB¿¢FWáC÷b.)ÿ¬7'óFÙ&˜C¢˝Ω-b›R}-]ç“ç--=¢∑7G“í‚"ê¢&WGW&‡¢vóB7ñÊ6ñÚÁ6∆VWÉb„ê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóB6ˆÁFWáBÊ&˜BÊVFóEˆ÷W76vU˜FWáBÜ6ÜEˆñC÷6ÜEˆñB¬÷W76vUˆñC÷÷W76vUˆñB¿¢FWáC“.(…≤7'óFÙ&˜C¢-]ÕÚÌmçM›çÚ-ΩçΩ‚‚	›mÕç-R*ø	˘H‚	˝Ì-]ç-Ã+≤˝Ì}mR‚"ê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç&7'óFÚˆ∆¬W'&˜#¢W2"¬Rê†¶7ñÊ2FVb˜ˆ∆≈ˆ7'óFı˜7V%ˆñÁfˆñ6RÄ¢6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¿¢6ÜEˆñC¢ñÁB¿¢÷W76vUˆñC¢ñÁB¿¢W6W%ˆñC¢ñÁB¿¢ñÁfˆñ6UˆñC¢7G"¿¢FñW#¢7G"¿¢÷ˆÁFá3¢ñÁ@¢ì†¢G'ì†¢f˜"Úñ‚&ÊvRÉ#ì¢2„"Õç›="˝Ç}M]m≠Rm¢ñÁb“vóBˆ7'óFıˆvWEˆñÁfˆñ6RÜñÁfˆñ6UˆñBê¢7B“ÜñÁb˜"∑“íÊvWBÇ'7FGW2"¬""íÊ∆˜vW"ÇíñbñÁbV«6R" ¢ñb7B”“'ñB#†¢VÁFñ¬“7FófFU˜7V'67&óFñˆÂ˜vóFÖ˜FñW"áW6W%ˆñB¬FñW"¬÷ˆÁFá2ê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóB6ˆÁFWáBÊ&˜BÊVFóEˆ÷W76vU˜FWáBÄ¢6ÜEˆñC÷6ÜEˆñB¬÷W76vUˆñC÷÷W76vUˆñB¿¢FWáC÷b.)»R7'óFÙ&˜C¢˝Ω-b˝ÌM--]mM“Â∆‚ ¢b-	˝ÌM˝ç≠∑FñW"ÁWW"Çó“≠-ç-›M‚∑VÁFñ¬Á7G&gFñ÷RÇrUí“V““VBró“Â∆Ô	˙©í	≠]Mç-≤›}çΩ]›≥¢µ5T%45$ïDîÙÂÙ5$TDïE2ÊvWBÇáFñW"˜"""íÊ∆˜vW"Çí¬í¢ñÁBÜ÷ˆÁFá2ó“≠‚ ¢ê¢&WGW&‡¢ñb7Bñ‚Ç&Wáó&VB"¬&6Ê6V∆∆VB"¬&6Ê6V∆VB"¬&fñ∆VB"ì†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóB6ˆÁFWáBÊ&˜BÊVFóEˆ÷W76vU˜FWáBÄ¢6ÜEˆñC÷6ÜEˆñB¬÷W76vUˆñC÷÷W76vUˆñB¿¢FWáC÷b.)ÿ¬7'óFÙ&˜C¢Ì˝Ω-›R}-]ç]›ç--=¢∑7G“í‚ ¢ê¢&WGW&‡¢vóB7ñÊ6ñÚÁ6∆VWÉb„ê†¢2
-ùÕ= ¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóB6ˆÁFWáBÊ&˜BÊVFóEˆ÷W76vU˜FWáBÄ¢6ÜEˆñC÷6ÜEˆñB¬÷W76vUˆñC÷÷W76vUˆñB¿¢FWáC“.(…≤7'óFÙ&˜C¢-]ÕÚÌmçM›çÚ-ΩçΩ‚‚	›mÕç-R*ø	˘H‚	˝Ì-]ç-Ã+≤çΩÇÌ˝Ω-ç-R}›Ì-‚‚ ¢ê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç&7'óFÚˆ∆¬á7V'67&óFñˆ‚íW'&˜#¢W2"¬Rê††¢2)H)H)H)H)H)H)H)H)H	˝]MΩÌm]›çR˝Ì˝ÌΩ›]›çÚ)H)H)H)H)H)H)H)H)H ¶7ñÊ2FVb˜6VÊE˜F˜Wˆ÷VÁRáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢2cÉ3¢˝ÌΩÕ}Ì--]Ω‚˝Ì≠}Ω-]¬≠]Mç-≤¬-›=-Ç∆Vv7í›Ω›]›ç-Ú"-]]›ç}]≠Ì¬›≠-ç-Ω]›-R‡¢6÷∆≈ˆ7"“ñÁBÜ˜2ÊVÁfó&ˆ‚ÊvWBÇ$5$TDïEı4µı4‘ƒ≈Ù5$TDïE2"¬#"í˜"ê¢÷ñEˆ7"“ñÁBÜ˜2ÊVÁfó&ˆ‚ÊvWBÇ$5$TDïEı4µÙ‘îEÙ5$TDïE2"¬#3"í˜"3ê¢&ñuˆ7"“ñÁBÜ˜2ÊVÁfó&ˆ‚ÊvWBÇ$5$TDïEı4µÙ$îuÙ5$TDïE2"¬#s"í˜"sê¢6÷∆≈˜'V"“ñÁBÜ˜2ÊVÁfó&ˆ‚ÊvWBÇ$5$TDïEı4µı4‘ƒ≈ı%T""¬#ìì"í˜"ììê¢÷ñE˜'V"“ñÁBÜ˜2ÊVÁfó&ˆ‚ÊvWBÇ$5$TDïEı4µÙ‘îEı%T""¬##sì"í˜"#sìê¢&ñu˜'V"“ñÁBÜ˜2ÊVÁfó&ˆ‚ÊvWBÇ$5$TDïEı4µÙ$îuı%T""¬#c#ì"í˜"c#ìê¢∂"“ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb'∑6÷∆≈ˆ7'“≠‚(
"∑6÷∆≈˜'V'“(+“"¬6∆∆&6µˆFF÷b'F˜Wß'V#ß∑6÷∆≈˜'V'“"í¿¢ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb'∂÷ñEˆ7'“≠‚(
"∂÷ñE˜'V'“(+“"¬6∆∆&6µˆFF÷b'F˜Wß'V#ß∂÷ñE˜'V'“"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb'∂&ñuˆ7'“≠‚(
"∂&ñu˜'V'“(+“"¬6∆∆&6µˆFF÷b'F˜Wß'V#ß∂&ñu˜'V'“"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb$7'óFÚÁ∑6÷∆≈ˆ7'“≠‚"¬6∆∆&6µˆFF÷b'F˜W¶7'óFÛßµˆ7&VFóG5˜Fı˜W6Bá6÷∆≈ˆ7"ì¢„&g“"í¿¢ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb$7'óFÚÁ∂÷ñEˆ7'“≠‚"¬6∆∆&6µˆFF÷b'F˜W¶7'óFÛßµˆ7&VFóG5˜Fı˜W6BÜ÷ñEˆ7"ì¢„&g“"ï“¿¢“ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	˙©í	≠]Mç-≤ç˝ÌΩÕ}=Ì-ÚMΩÚ-˝mΩΩRM=›≠mçì¢-çM]‚¬Õ=}Ω≠¬í›MÌ-‚¬f6U7v¬=Ì-Ì˝ùçí--Ç˝]Õç=¬›]›M]≤Â∆‚ ¢#≠]Mç"“(+“‚	-Ω]ç-R˝≠]#¢"¿¢&W«ïˆ÷&∑W÷∂"¿¢ê††¢2)H)H)H)H)H)H)H)H)H	˝ÌÕ‚›≠-Ì-≤˝‚M=›≠mç˝¬)H)H)H)H)H)H)H)H)H ¶FVb˜&ˆ÷ıˆfVGW&Uˆ∂WíÜVÊvñÊS¢7G"¬&V÷V÷&W%ˆ∂ñÊC¢7G"“""í”‚7G#†¢&≤“á&V÷V÷&W%ˆ∂ñÊB˜"""íÁ7G&óÇíÊ∆˜vW"Çê¢VÊr“ÜVÊvñÊR˜"""íÁ7G&óÇíÊ∆˜vW"Çê¢ñb'fˆ6¬"ñ‚&≤ÊBÇ&6∆ó"ñ‚&≤˜"&∆ó7ñÊ2"ñ‚&≤ì†¢&WGW&‚'fˆ6≈ˆ∆ó7ñÊ5ˆ6∆ó ¢ñb'Ü˜Fıˆ◊W6ñ5ˆ6∆ó"ñ‚&≤˜"'Ü˜Fıˆ6∆ó"ñ‚&≥†¢&WGW&‚'Ü˜Fıˆ◊W6ñ5ˆ6∆ó ¢ñb'F∆∂ñÊuˆfF""ñ‚&≤˜"&fF""ñ‚&≥†¢&WGW&‚'F∆∂ñÊuˆfF" ¢ñb&≤Á7F'G7vóFÇÇ'FWáE˜fñFVÚ"í˜"&≤Á7F'G7vóFÇÇ'fñFVıÚ"ì†¢&WGW&‚&∞¢ñb'&WfófU˜Ü˜FÚ"ñ‚&≥†¢&WGW&‚&∞¢ñb'7VÊÚ"ñ‚&≥†¢&WGW&‚'7VÊıˆ◊W6ñ2 ¢ñb&'W6ñÊW75ˆ∆ˆvÚ"ñ‚&≤˜"&∆ˆvÚ"ñ‚&≥†¢&WGW&‚&'W6ñÊW75ˆ∆ˆvÚ ¢ñb&f6W7v"ñ‚&≤˜"&f6U˜7v"ñ‚&≥†¢&WGW&‚&f6W7v ¢ñb&ï˜6V∆fñR"ñ‚&≥†¢&WGW&‚&ï˜6V∆fñR ¢ñb'&V÷˜fV&r"ñ‚&≤˜"'&V÷˜fUˆ&6∂w&˜VÊB"ñ‚&≥†¢&WGW&‚'&V÷˜fUˆ&6∂w&˜VÊB ¢ñb'&W∆6V&r"ñ‚&≤˜"'&W∆6Uˆ&6∂w&˜VÊB"ñ‚&≥†¢&WGW&‚'&W∆6Uˆ&6∂w&˜VÊB ¢ñb&˜WGñÁB"ñ‚&≥†¢&WGW&‚&˜WGñÁB ¢ñb&ñ÷vU˜&WF˜V6Ç"ñ‚&≤˜"'&WF˜V6Ç"ñ‚&≥†¢&WGW&‚&ñ÷vU˜&WF˜V6Ç ¢ñb&ñ÷uˆvVÊW&FR"ñ‚&≤˜"&ñ÷vUˆvVÊW&FR"ñ‚&≤˜"VÊr”“&ñ÷r#†¢&WGW&‚&ñ÷vUˆvVÊW&Fñˆ‚ ¢&WGW&‚&≤˜"VÊr˜"&gVÊ7Fñˆ‚ †¶FVb˜&ˆ÷ı˜V˜Fˆ∑eˆ∂WíáW6W%ˆñC¢ñÁB¬fVGW&S¢7G"¬ñ÷C¢7G"¬ÊˆÊR“ÊˆÊRí”‚7G#†¢6fR“&RÁ7V"á"%µÊ◊£”ïı¬’“≤"¬%Ú"¬ÜfVGW&R˜"&gVÊ7Fñˆ‚"íÊ∆˜vW"Çíï≥£É–¢&WGW&‚b'&ˆ÷ÛSß∑W6W%ˆñG”ß∑ñ÷B˜"˜FˆFï˜ñ÷BÇó”ß∑6fW“ †¶FVb˜G'ïˆ6ˆÁ7V÷U˜&ˆ÷ıˆFñ«ìU˜V˜FáW6W%ˆñC¢ñÁB¬W6W&Ê÷S¢7G"¬ÊˆÊR¬VÊvñÊS¢7G"¬&V÷V÷&W%ˆ∂ñÊC¢7G"“""í”‚GW∆U∂&ˆˆ¬¬ñÁB¬ñÁB¬7G%”†¢ñbÊ˜Bó5˜&ˆ÷ıˆFñ«ìU˜W6W"áW6W%ˆñB¬W6W&Ê÷Rì†¢&WGW&‚f«6R¬¬$Ù‘ıÙDî≈ìUıU%ÙeT‰5DîÙÂÙƒî‘ïB¬" ¢fVGW&R“˜&ˆ÷ıˆfVGW&Uˆ∂WíÜVÊvñÊR¬&V÷V÷&W%ˆ∂ñÊBê¢∆ñ÷óB“÷ÇÉ¬ñÁBÖ$Ù‘ıÙDî≈ìUıU%ÙeT‰5DîÙÂÙƒî‘ïBíê¢ñb∆ñ÷óB√“†¢&WGW&‚f«6R¬¬∆ñ÷óB¬fVGW&P¢∂Wí“˜&ˆ÷ı˜V˜Fˆ∑eˆ∂WíáW6W%ˆñB¬fVGW&Rê¢W6VB“ñÁBÜ∑eˆvWBÜ∂Wí¬#"í˜"#"ê¢ñbW6VB„“∆ñ÷óC†¢&WGW&‚f«6R¬¬∆ñ÷óB¬fVGW&P¢∑e˜6WBÜ∂Wí¬7G"áW6VB≤íê¢&WGW&‚G'VR¬÷ÇÉ¬∆ñ÷óB“W6VB“í¬∆ñ÷óB¬fVGW&P††¢2)H)H)H)H)H)H)H)H)H	˝Ì˝Ω-≠Ì˝Ω-ç-¬(i"-Ω˝ÌΩ›ç-¬)H)H)H)H)H)H)H)H)H ¶7ñÊ2FVb˜G'ï˜ï˜FÜVÂˆFÚÄ¢WFFS¢WFFR¿¢6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¿¢W6W%ˆñC¢ñÁB¿¢VÊvñÊS¢7G"¿¢W7Eˆ6˜7E˜W6C¢f∆ˆB¿¢6˜&ıˆgVÊ2¿¢&V÷V÷&W%ˆ∂ñÊC¢7G"“""¿¢&V÷V÷&W%˜ñ∆ˆC¢Fñ7B¬ÊˆÊR“ÊˆÊR¿¢6ñ∆VÁEˆfñ«W&S¢&ˆˆ¬“f«6R¿¢ì†¢""%&W6W'fR66óGí¬'V‚&˜fñFW"¬ÊB6Ü&vRˆÊ«ígFW"FÜR7Fñˆ‚Wá∆ñ6óF«í&WGW&Á2G'VR‚"" ¢W6W&Ê÷R“áWFFRÊVffV7FófU˜W6W"ÁW6W&Ê÷R˜"""ê†¢&ˆ÷ıˆˆ≤¬&ˆ÷ıˆ∆VgB¬&ˆ÷ıˆ∆ñ÷óB¬&ˆ÷ıˆfVGW&R“˜G'ïˆ6ˆÁ7V÷U˜&ˆ÷ıˆFñ«ìU˜V˜FáW6W%ˆñB¬W6W&Ê÷R¬VÊvñÊR¬&V÷V÷&W%ˆ∂ñÊBê¢ñb&ˆ÷ıˆˆ≥†¢G'ì†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb/	¯Ë	˝ÌÕ‚›MÌ-=Û¢M=›≠mçÚ*∑∑&ˆ÷ıˆfVGW&W‹+≤‚	Ì-ΩÌ¬]=ÌM›Û¢∑&ˆ÷ıˆ∆VgG“˜∑&ˆ÷ıˆ∆ñ÷óG“‚"ê¢&W7V«B“vóB6˜&ıˆgVÊ2Çê¢ñb&W7V«Bó2f«6S†¢&ó6R'VÁFñ÷TW'&˜"Ç'&˜fñFW"&WGW&ÊVBVÁ7V66W76gV¬&W7V«B"ê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç'&ˆ÷ÚFñ«ìR7Fñˆ‚fñ∆VC¢W2"¬Rê¢ñbÊ˜B6ñ∆VÁEˆfñ«W&S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	}M}›R-Ω˝ÌΩ›]›‚	˝ÌÕ‚›≠]Mç-≤›R˝çΩ-Ì-Ú‚"ê¢&WGW&‡¢ñbó5˜&ˆ÷ıˆFñ«ìU˜W6W"áW6W%ˆñB¬W6W&Ê÷RíÊB&ˆ÷ıˆfVGW&S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb-	˝ÌÕ‚›ΩçÕç"›M=›≠mç‚*∑∑&ˆ÷ıˆfVGW&W‹+≤]=ÌM›Úç}]˝”¢∑&ˆ÷ıˆ∆ñ÷óG“˜∑&ˆ÷ıˆ∆ñ÷óG“‚uB›}"Ì--Ú]}ΩçÕç-›Ω¬‚"ê¢&WGW&‡†¢g&VUˆ∂ñÊB“ˆg&VU˜V˜Fˆ6FVv˜'íÜVÊvñÊR¬&V÷V÷&W%ˆ∂ñÊBê¢ñbg&VUˆ∂ñÊBÊBvWE˜7V'67&óFñˆÂ˜FñW"áW6W%ˆñBí”“&g&VR"ÊBÊ˜Bó5˜VÊ∆ñ÷óFVBáW6W%ˆñB¬W6W&Ê÷Rì†¢ˆˆ≤¬ˆ∆VgB¬ˆ∆ñ÷óB“˜G'ïˆ6ˆÁ7V÷Uˆg&VUˆFñ«ï˜V˜FáW6W%ˆñB¬W6W&Ê÷R¬g&VUˆ∂ñÊBê¢ñbˆˆ≥†¢G'ì†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb/	¯Ë	]˝Ω-›ÌRM]ù--çS¢µˆg&VU˜V˜Fˆ∆&V¬Üg&VUˆ∂ñÊBó“‚	Ì-ΩÌ¬]=ÌM›Û¢∑ˆ∆VgG“˜∑ˆ∆ñ÷óG“‚"ê¢&W7V«B“vóB6˜&ıˆgVÊ2Çê¢ñb&W7V«Bó2f«6S¢&ó6R'VÁFñ÷TW'&˜"Ç'&˜fñFW"&WGW&ÊVBVÁ7V66W76gV¬&W7V«B"ê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç&g&VR7Fñˆ‚fñ∆VC¢W2"¬Rê¢ñbÊ˜B6ñ∆VÁEˆfñ«W&S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	}M}›R-Ω˝ÌΩ›]›‚	M]›]m›Ì=‚˝ç›çÚ›RΩΩ‚‚"ê¢&WGW&‡¢vóB˜6VÊEˆg&VU˜V˜FˆWÜÜW7FVBáWFFR¬6ˆÁFWáB¬g&VUˆ∂ñÊBì≤&WGW&‡†¢ñbó5˜VÊ∆ñ÷óFVBáW6W%ˆñB¬W6W&Ê÷Rì†¢G'ì†¢&W7V«B“vóB6˜&ıˆgVÊ2Çê¢ñb&W7V«Bó2f«6S¢&ó6R'VÁFñ÷TW'&˜"Ç'&˜fñFW"&WGW&ÊVBVÁ7V66W76gV¬&W7V«B"ê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç'VÊ∆ñ÷óFVB7Fñˆ‚fñ∆VC¢W2"¬Rê¢ñbÊ˜B6ñ∆VÁEˆfñ«W&S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	}M}›R-Ω˝ÌΩ›]›‚	˝Ì˝Ì=ù-R˝Ì}mR‚"ê¢&WGW&‡†¢&˜fñFW%ˆ6˜7B“÷ÇÉ„¬f∆ˆBÜW7Eˆ6˜7E˜W6B˜"„íê¢&WFñ≈˜W6B“˜&WFñ≈˜W6Bá&˜fñFW%ˆ6˜7Bê¢&ñ6Uˆ7&VFóG2“˜&WFñ≈ˆ7&VFóG2á&˜fñFW%ˆ6˜7Bê¢GÖˆñB“ÊˆÊP¢G'ì†¢GÖˆñB¬fñ∆&∆Uˆ&Vf˜&R“ˆ7&VFóE˜&W6W'fRáW6W%ˆñB¬VÊvñÊR¬&V÷V÷&W%ˆ∂ñÊB˜"VÊvñÊR¬&˜fñFW%ˆ6˜7B¬&WFñ≈˜W6B¬&V÷V÷&W%˜ñ∆ˆBê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç&7&VFóB&W6W'fRfñ∆VC¢W2"¬Rê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	›R=MΩÌ¬˝Ì-]ç-¬≠]Mç-›ΩíΩ›‚	˝Ì˝Ì=ù-R]ùr‚"ê¢&WGW&‡†¢ñbÊ˜BGÖˆñC†¢fñ∆&∆Uˆ7"“ñÁBá&˜VÊBÖ˜W6E˜Fıˆ7&VFóG2Üfñ∆&∆Uˆ&Vf˜&Rííê¢÷ó76ñÊuˆ7"“÷ÇÉ¬&ñ6Uˆ7&VFóG2“fñ∆&∆Uˆ7"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b-	›]MÌ--Ì}›‚≠]Mç-Ì"‚
-ÌçÕÌ-√¢∑&ñ6Uˆ7&VFóG7“≠‚	MÌ-=˝›„¢∂fñ∆&∆Uˆ7'“≠‚	›R]--]#¢∂÷ó76ñÊuˆ7'“≠‚"¿¢&W«ïˆ÷&∑W‘ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖµ¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.*Ÿ
-çM≤"¬vV%ˆ’vV$ñÊfÚáW&√’D$îdeıU$¬íï“≈¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.)ÈR	˝Ì˝ÌΩ›ç-¬Ω›"¬6∆∆&6µˆFF“'F˜W"ï’“ê¢ê¢&WGW&‡†¢gFW%ˆ7"“÷ÇÉ¬ñÁBá&˜VÊBÖ˜W6E˜Fıˆ7&VFóG2Üfñ∆&∆Uˆ&Vf˜&R“&WFñ≈˜W6Bíííê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb/	˙©í
-ÌçÕÌ-√¢∑&ñ6Uˆ7&VFóG7“≠‚
˝ç›çR˝Ìç}ÌùM"-ÌΩÕ≠‚˝ÌΩR=˝]ç›Ì=‚]}=ΩÕ--‚	˝ÌΩR-Ω˝ÌΩ›]›çÚÌ-›]-Û¢∂gFW%ˆ7'“≠‚"ê†¢G'ì†¢&W7V«B“vóB6˜&ıˆgVÊ2Çê¢ñb&W7V«Bó2Ê˜BG'VS†¢ˆ7&VFóE˜&V∆V6RáGÖˆñB¬'&V∆V6VB"ê¢ñbÊ˜B6ñ∆VÁEˆfñ«W&S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.(jû˚àÚ	=]›]mçÚ›R}-]ççΩ¬(	B≠]Mç-≤›R˝ç›≤‚"ê¢&WGW&‡¢ñbÊ˜Bˆ7&VFóEˆ6ˆ÷÷óBáGÖˆñBì†¢ˆ7&VFóE˜&V∆V6RáGÖˆñB¬'&V∆V6VB"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)™˚àÚ
]}=ΩÕ-"˝ÌΩ=}]“¬›‚˝ç›çR›R}Mç≠çÌ-›‚‚	Ì-ç-]¬"˝ÌMM]m≠2¬˝Ì--Ì›‚}˝=≠-¬Ì˝Ω-2›R›=m›‚‚"ê¢&WGW&‡¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb.)»R
˝ç›„¢∑&ñ6Uˆ7&VFóG7“≠‚"ê¢WÜ6WBWÜ6WFñˆ‚2S†¢ˆ7&VFóE˜&V∆V6RáGÖˆñB¬'&V∆V6VB"ê¢∆ˆrÊWÜ6WFñˆ‚Ç'ñB7Fñˆ‚fñ∆VC¢W2"¬Rê¢ñbÊ˜B6ñ∆VÁEˆfñ«W&S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬	}M}›R-Ω˝ÌΩ›]›‚	≠]Mç-≤›R˝ç›≤‚"ê††¶7ñÊ2FVb6÷EˆFñuˆ66W72áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢W6W"“WFFRÊVffV7FófU˜W6W ¢W6W%ˆñB“W6W"ÊñBñbW6W"V«6R ¢W6W&Ê÷R“W6W"ÁW6W&Ê÷RñbW6W"V«6R" ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	˘I66W72FñvÊ˜7Fñ5∆‚ ¢b'W6W%ˆñC¢∑W6W%ˆñG’∆‚ ¢b'W6W&Ê÷S¢∑W6W&Ê÷R˜"r“w’∆‚ ¢b'VÊ∆ñ÷óFVC¢∂ó5˜VÊ∆ñ÷óFVBáW6W%ˆñB¬W6W&Ê÷Ró’∆‚ ¢b'&ˆ÷ı˜VÊ∆ñ’ˆwC¢∂ó5˜&ˆ÷ı˜VÊ∆ñ’ˆwBáW6W%ˆñB¬W6W&Ê÷Ró’∆‚ ¢b'&ˆ÷ıˆFñ«ìS¢∂ó5˜&ˆ÷ıˆFñ«ìU˜W6W"áW6W%ˆñB¬W6W&Ê÷Ró’∆‚ ¢b'&ˆ÷ıˆ∆ñ÷óE˜W%ˆgVÊ7Fñˆ„¢µ$Ù‘ıÙDî≈ìUıU%ÙeT‰5DîÙÂÙƒî‘ïG“ ¢ê†¢2)H)H)H)H)H)H)H)H)H˜∆Á2)H)H)H)H)H)H)H)H)H ¶7ñÊ2FVb6÷E˜∆Á2áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢∆ñÊW2“≤.*Ÿ
-çM≤Ç≠]Mç-≥¢"¬-	˝ÌM˝ç≠Ì-≠Ω-]"MÌ-=Ú¬≠]Mç-≤]ÌM=Ì-Ú›-˝mΩΩR=]›]mçÇ‚%–¢f˜"FñW"¬FW&◊2ñ‚ƒÂı$î4UıD$ƒRÊóFV◊2Çì†¢∆ñÊW2ÊVÊBÜb.(	B∑FñW"ÁWW"Çó”¢ ¢b'∑FW&◊5≤v÷ˆÁFÇu◊ﬁ(+“˝Õ](
"∑FW&◊5≤wV'FW"u◊ﬁ(+“˝≠--≤(
"∑FW&◊5≤wñV"u◊ﬁ(+“˝=ÌB(
"µ5T%45$ïDîÙÂÙ5$TDïE2ÊvWBáFñW"√ó“≠‚˝Õ]"ê¢∂"“ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÖ∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç%5D%BÕ]"¬6∆∆&6µˆFF“&'Wìß7F'C£"í¿¢ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç%$ÚÕ]"¬6∆∆&6µˆFF“&'Wìß&Û£"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç%T≈Dî‘DRÕ]"¬6∆∆&6µˆFF“&'WìßV«Fñ÷FS£"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç-	Õç›Ç›-ç-ç›"¬vV%ˆ’vV$ñÊfÚáW&√’D$îdeıU$¬íï–¢“ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ%∆‚"Ê¶ˆñ‚Ü∆ñÊW2í¬&W«ïˆ÷&∑W÷∂"ê††¢2)H)H)H)H)H)H)H)H)H	Ì-≠MΩÚ˝]]M}Ç˝Ìç}-ÌΩÕ›Ì=‚-]≠-ç›˝‚çr5EBí)H)H)H)H)H)H)H)H)H ¶7ñÊ2FVbˆÂ˜FWáE˜vóFÖ˜FWáBÄ¢WFFS¢WFFR¿¢6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¿¢FWáC¢7G"¿¢ì†¢"" ¢	Ì-≠MΩÚ˝]]M}Ç-]≠-ç›˝çÕ]¬˝ÌΩR5EBí"ˆÂ˜FWáB¿¢]r˝Ì˝Ω-Ì¢ç}Õ]›ç-¬WFFRÊ÷W76vRá&VB÷ˆÊ«íí‡¢"" ¢FWáB“áFWáB˜"""íÁ7G&óÇê¢ñbÊ˜BFWáC†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›R=MΩÌ¬˝Ì}›-¬-]≠"‚"ê¢&WGW&‡†¢vóBˆÂ˜FWáBáWFFR¬6ˆÁFWáB¬÷ÁV≈˜FWáC◊FWáBê††¢2)H)H)H)H)H)H)H)H)H
-]≠-Ì-Ωí-]ÌB)H)H)H)H)H)H)H)H)H ¶7ñÊ2FVbˆÂ˜FWáBÄ¢WFFS¢WFFR¿¢6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¿¢÷ÁV≈˜FWáC¢7G"¬ÊˆÊR“ÊˆÊR¿¢ì†¢2	]ΩÇ-]≠"˝]]M“ç}-›R(i"ç˝ÌΩÕ}=]¬]=‡¢2ç›}R(	BÌΩ}›Ωí-]≠"ÌÌù]›ç¢ñb÷ÁV≈˜FWáBó2Ê˜BÊˆÊS†¢FWáB“÷ÁV≈˜FWáBÁ7G&óÇê¢V«6S†¢FWáB“áWFFRÊ÷W76vRÁFWáB˜"""íÁ7G&óÇê†¢2ñFV◊˜FVÊ7íwV&C¢FÜR&ñ˜&óGí&W6VÁFFñˆ‚7GVFñÚÜÊF∆W"÷í«&VGí˜v‚FÜó2WFFR‡¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ñb6ˆÁFWáBÊ6ÜEˆFFÊvWBÇ%˜&W6VÁFFñˆÂˆ∆7E˜WFFU˜Fˆ∂V‚"í”“˜&W6VÁFFñˆÂ˜WFFU˜Fˆ∂V‚áWFFRì†¢&WGW&‡†¢2&VÊ÷Rfó'GV¬6ÜB&Vf˜&R&˜WFñÊrFÜR÷W76vRFÚuB‡¢&VÊ÷Uˆ6ñB“6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊuˆ6ÜE˜&VÊ÷R"¬ÊˆÊRê¢ñb&VÊ÷Uˆ6ñC†¢ñbˆ6ÜE˜&VÊ÷RáWFFRÊVffV7FófU˜W6W"ÊñB¬WFFRÊVffV7FófUˆ6ÜBÊñB¬ñÁBá&VÊ÷Uˆ6ñBí¬FWáBì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)»R	›}-›çR}-Ì›Ì-Ω]›‚‚"¬&W«ïˆ÷&∑W’ˆ6ÜEˆ∆ó7Eˆ∂"áWFFRÊVffV7FófU˜W6W"ÊñB¬WFFRÊVffV7FófUˆ6ÜBÊñBíê¢V«6S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›R=MΩÌ¬˝]]çÕ]›Ì--¬}"‚"ê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊuˆ÷ñF¶˜W&ÊWï˜&ˆ◊B"¬ÊˆÊRì†¢vóB˜7F'Eˆ÷ñF¶˜W&ÊWïˆñ÷vRáWFFR¬6ˆÁFWáB¬FWáBê¢&WGW&‡†¢27FófR&W6VÁFFñˆ‚ˆ6F∆ˆr&ˆ¶V7BÜ2'6ˆ«WFR&ñ˜&óGí˜fW"vVÊW&ñ2uBˆ∆ófR◊6V&6Ç&˜WFñÊr‡¢˜7GVFñÚ“˜&W6VÁFFñˆÂ˜7GVFñıˆvWBÇê¢ñbvóB˜7GVFñÚÊÜÊF∆U˜FWáBáWFFR¬6ˆÁFWáB¬FWáBì†¢&WGW&‡¢2vÜV‚&ˆ¶V7Bó27FófR'WBFÜR7W'&VÁB7FvRWáV7G2'WGFˆ‚˜W∆ˆB&FÜW"FÜ‚g&VRFWáB¿¢2ÊWfW"72FÜR6÷R÷W76vRFÚvVÊW&ñ2uB˜"∆ófR◊6V&6Ç‡¢ˆ7FófU˜&W6VÁFFñˆ‚“˜7GVFñÚÂˆ7FófU˜&ˆ¶V7BáWFFRÊVffV7FófU˜W6W"ÊñB¬WFFRÊVffV7FófUˆ6ÜBÊñBê¢ñbˆ7FófU˜&W6VÁFFñˆ„†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢-	˝Ì]≠"˝]}]›-mçÇ≠-ç-]“‚	››-Ì¬›-˝Rç˝ÌΩÕ}=ù-R≠›Ì˝≠ÇÕ-]çΩÇ›mÕç-R*Ω	˝ÌMÌΩmç-Ã+≤‚ ¢ê¢&WGW&‡†¢2∂VW◊W6ñ2◊fñFVÚ&Wfó6ñˆÁ2ñ‚FÜR6÷R÷ˆFS≤ÊWfW"6VÊBG&gBFÚvVÊW&ñ26ÜB‡¢G&gB“6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&◊W6ñ5˜fñFVıˆG&gB"ê¢ñbG&gC†¢VFóB“6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&◊W6ñ5˜fñFVıˆG&gEˆVFóB"ê¢ñbVFóBñ‚Ç&Vv÷VÁB"¬'&Ww&óFR"¬'fˆñ6U˜&Ww&óFR"ì†¢7W'&VÁEˆGW&Fñˆ‚“ñÁBÜG&gBÊvWBÇ&GW&Fñˆ‚"í˜"˜Ü˜Fıˆ6∆ó˜F&vWEˆGW&Fñˆ‚ÜG&gE≤'fñFVıˆ'&ñVb%“íê¢6V∆V7FVEˆGW&Fñˆ‚“7W'&VÁEˆGW&Fñˆ‚ñbG&gBÊvWBÇ&GW&FñˆÂˆ∆ˆ6∂VB"íV«6RÊˆÊP¢ñbVFóB”“&Vv÷VÁB#†¢&ˆ◊B“ˆ÷W&vUˆ◊W6ñ5˜fñFVı˜&ˆ◊BÜG&gE≤'&ˆ◊B%“¬FWáBê¢vóB˜7FvUˆ◊W6ñ5˜fñFVıˆG&gBÄ¢WFFR¬6ˆÁFWáB¬&ˆ◊B¬6V∆V7FVEˆGW&FñˆÂ˜3◊6V∆V7FVEˆGW&Fñˆ‡¢ê¢V∆ñbVFóB”“'&Ww&óFR#†¢vóB˜7FvUˆ◊W6ñ5˜fñFVıˆG&gBÄ¢WFFR¬6ˆÁFWáB¬FWáB¬6V∆V7FVEˆGW&FñˆÂ˜3◊6V∆V7FVEˆGW&Fñˆ‡¢ê¢V«6S†¢vVÊW&FVB“vóB6µˆ˜VÊï˜FWáBÄ¢-	˝]Ì}=í=ÌΩÌÌ-ÌRÌ˝ç›çR˝ÌΩÕ}Ì--]ΩÚ"M-˝ÌM]çÌ›ΩÕ›ΩR˝ÌÕ˝-‚
Ì]›Ç]=‚}ÕΩ]≤‚ ¢b-	-çM]‚Ì-›‚∂7W'&VÁEˆGW&FñˆÁ“]≠=›C≤dîDTıÙ%$îTb}]í˝‚]≠=›B6ˆÁFñÁVóGíÇ5D%BÙT‰B7FFW2‚ ¢$’U4î5Ù%$îTbÌ˝-çÕç}ç=íMΩÚ7VÊÚ‚	-]›Ç-Ì=‚¥’U4î5Ù%$îTe“}-]¬µdîDTıÙ%$îTe“Â∆Â∆Ì	Ì˝ç›çS¢"≤FWáB¿¢W6W%ˆñC◊WFFRÊVffV7FófU˜W6W"ÊñB¬6ÜEˆñC◊WFFRÊVffV7FófUˆ6ÜBÊñB¿¢WáG&˜7ó7FV”“-
-≤&ˆ◊B÷Fó&V7F˜"í◊W6ñ2fñFVÚ‚	›R-ΩM=ÕΩ-íÌm]-›ΩRM≠-≤-]R=ÌΩÌÌ-Ì=‚Ì˝ç›çÚ‚ ¢ê¢vóB˜7FvUˆ◊W6ñ5˜fñFVıˆG&gBÄ¢WFFR¬6ˆÁFWáB¬vVÊW&FVB¬6V∆V7FVEˆGW&FñˆÂ˜3◊6V∆V7FVEˆGW&Fñˆ‡¢ê¢ ¢V«6S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢-
m]›çíÌmçM]"]ç]›çÚ‚	›mÕç-R*Ω
=--]mMÏ+≤¬*Ω	MÌ˝ÌΩ›ç-Ã+≤çΩÇ*Ω	›˝ç-¬}›Ì-Ï+≤‚"¿¢&W«ïˆ÷&∑W’ˆ◊W6ñ5˜fñFVıˆ&˜f≈ˆ∂"ÜG&gE≤'Fˆ∂V‚%“í¿¢ê¢&WGW&‡†¢2	-Ì˝Ì≤‚f6U7vMÌΩm›≤Ì--]}-¬Ì˝ç›ç]¬M=›≠mçÇ¬›R}2}˝=≠-¬]mç¬‡¢ñb&RÁ6V&6Çá""çÕÌbç]ç«Õ]-WÕ›‚óÕ=ÕRç]ç«Õ]-RóÕ˝ÌÌ]◊Õ˝ÌMM]mç-]ç«ÕM]Ω]ç«ÕÕÌm]%«2ΩΩÇí"¬FWáB˜"""¬&R‰ííÊB&RÁ6V&6Çá""çΩçgÕΩçmÕΩçmÁ∆f6W∆f6W7ví"¬FWáB˜"""¬&R‰íì†¢6ˆV&«í“6&ñ∆óGïˆÁ7vW"áFWáBê¢ñb6ˆV&«ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜ6ˆV&«í¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ6ÜEˆ÷V÷˜'ïˆFBáWFFRÊVffV7FófU˜W6W"ÊñB¬WFFRÊVffV7FófUˆ6ÜBÊñB¬'W6W""¬FWáBê¢ˆ6ÜEˆ÷V÷˜'ïˆFBáWFFRÊVffV7FófU˜W6W"ÊñB¬WFFRÊVffV7FófUˆ6ÜBÊñB¬&76ó7FÁB"¬6ˆV&«íê¢&WGW&‡†¢2	}Õ]›Ωçm¢Ì-M]ΩÕ›ΩíM-=]ç=Ì-Ωí]mç¬‡¢ñbˆó5ˆf6U˜7v˜&WVW7BáFWáBì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢vóB˜7F'Eˆf6W7vˆf∆˜ráWFFR¬6ˆÁFWáB¬ÊˆÊR¬W6Uˆ66ÜVC‘f«6Rê¢&WGW&‡†¢2
=MΩ]›çR˝}Õ]›MÌ›¢]ΩÇ˝ÌΩÕ}Ì--]Ω¬=mR}==}ç≤MÌ-‚çΩÇÌ"mM"=-Ì}›]›çR‡¢ñbˆó5˜&W∆6V&u˜vóE˜FWáBÜ6ˆÁFWáBì†¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢ñbÊ˜Bñ÷s†¢ˆ6∆V%˜&W∆6V&u˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-
›}Ω˝ççΩç-RMÌ-‚¬}-]¬-Ω]ç-R}Õ]›2MÌ›‚"¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡¢∂ñÊB¬&ˆ◊B“ˆ&uˆ∂ñÊEˆg&ˆ’˜FWáBáFWáBê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%˜&W∆6V&u˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢vóB˜VFóE˜&W∆6V&ráWFFR¬6ˆÁFWáB¬ñ÷r¬∂ñÊC÷∂ñÊB¬&ˆ◊C◊&ˆ◊Bê¢&WGW&‡†¢ñbˆó5˜&V÷˜fUˆ&u˜&WVW7BáFWáBì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢ñbñ÷s†¢vóB˜VFóE˜&V÷˜fV&ráWFFR¬6ˆÁFWáB¬ñ÷rê¢&WGW&‡¢˜6WE˜vóFñÊu˜&V÷˜fV&rÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	˝ççΩç-RMÌ-‚(	B=MΩ‚MÌ“Ç-]›2‰r˝Ì}}›Ìí˝ÌMΩÌm≠Ìí‚"¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡†¢ñbˆó5˜&W∆6Uˆ&u˜&WVW7BáFWáBì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢∂ñÊB¬&ˆ◊B“ˆ&uˆ∂ñÊEˆg&ˆ’˜FWáBáFWáBê¢ñbñ÷s†¢vóB˜VFóE˜&W∆6V&ráWFFR¬6ˆÁFWáB¬ñ÷r¬∂ñÊC÷∂ñÊB¬&ˆ◊C◊&ˆ◊Bê¢&WGW&‡¢˜6WE˜vóFñÊu˜&W∆6V&rÜ6ˆÁFWáB¬&ˆ◊C◊FWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	˝ççΩç-RMÌ-‚(	B-Ω]m2Ì≠]≠"Ç}Õ]›‚-ÌΩÕ≠‚MÌ“‚	MΩÚ˝]]-Ì"Ç-]≠-Ì-Ì=‚Ì˝ç›çÚ˝Ì-Ì¬M]Ω-¬]}=ΩÕ-"≠¢›-Ì˝ù]R]ΩMÇ‚"¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡†¢2
]-=ç¬Ì--]››Ì=‚ç}Ìm]›çÛ¢]ΩÇMÌ-‚=mR}==m]›‚ÇÌ"mM"=-Ì}›]›çR‡¢ñbˆó5˜&WF˜V6Ö˜vóE˜FWáBÜ6ˆÁFWáBì†¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢ñbÊ˜Bñ÷s†¢ˆ6∆V%ˆñ÷vU˜&WF˜V6Ö˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÖ˜&WF˜V6Ö˜W6W%ˆÜñÁE˜FWáBÇí¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡¢ñÁ7G'V7Fñˆ‚“FWáB˜"6ˆÁFWáBÁW6W%ˆFFÊvWBÇ'&WF˜V6Ö˜&ˆ◊B"í˜"-=-¬Ωçç›Ì‚›M˝ç¬˝-ÌM˝›Ìí}›¢ ¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%ˆñ÷vU˜&WF˜V6Ö˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢vóB˜7F'Eˆñ÷vU˜&WF˜V6ÇáWFFR¬6ˆÁFWáB¬ñ÷r¬ñÁ7G'V7Fñˆ‚ê¢&WGW&‡†¢2í›]ΩMÉ¢MÌ-‚=mR}==m]›‚¬mM¬m]›2˝}›Õ]›ç-Ì-¬˝˝]Ì›m‡¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊuˆï˜6V∆fñU˜&ˆ◊B"ì†¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢ñbÊ˜Bñ÷s†¢ˆ6∆V%ˆï˜6V∆fñU˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-
›}Ω}==}ç-R-Ì]ΩMÇ¬}-]¬›mÕç-R	˙K2í›]ΩMÇ‚}-]}MÌí‚"¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡¢&W6WB“Ü6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&ï˜6V∆fñU˜&W6WE˜&ˆ◊B"¬""í˜"""íÁ7G&óÇê¢ˆ6∆V%ˆï˜6V∆fñU˜vóBÜ6ˆÁFWáBê¢vóB˜7F'Eˆï˜6V∆fñRáWFFR¬6ˆÁFWáB¬ñ÷r¬FWáB¬&W6WBê¢&WGW&‡†¢2	=Ì-Ì˝ùçí--¢˝Ì-]"=mR}==m]“¬›‚˝]]B-]≠-Ì¬-]=]-Ú-Ω-¬=ÌΩÌ‡¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊuˆfF%˜fˆñ6Uˆ6Üˆñ6R"ì†¢F¬“áFWáB˜"""íÁ7G&óÇíÊ∆˜vW"Çê¢fˆñ6Uˆ∆ñ6W2“∞¢&Ê˜f#¢&Ê˜f"¬-›Ì-#¢&Ê˜f"¿¢&ˆÁóÇ#¢&ˆÁóÇ"¬-Ì›ç≠#¢&ˆÁóÇ"¿¢&∆∆˜í#¢&∆∆˜í"¬-ΩΩÌí#¢&∆∆˜í"¿¢'6Üñ÷÷W"#¢'6Üñ÷÷W""¬-ççÕÕ]#¢'6Üñ÷÷W""¿¢&f&∆R#¢&f&∆R"¬-M]ù≤#¢&f&∆R"¿¢–¢ñbF¬ñ‚fˆñ6Uˆ∆ñ6W3†¢6Ü˜6V‚“fˆñ6Uˆ∆ñ6W5∑F≈–¢6ˆÁFWáBÁW6W%ˆFF≤&fF%˜GG5˜fˆñ6R%““6Ü˜6V‡¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊuˆfF%˜fˆñ6Uˆ6Üˆñ6R"¬ÊˆÊRê¢VÊFñÊu˜67&óB“Ü6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&fF%˜VÊFñÊu˜67&óB"í˜"""íÁ7G&óÇê¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢ñbVÊFñÊu˜67&óBÊBñ÷s†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&fF%˜VÊFñÊu˜67&óB"¬ÊˆÊRê¢ˆ6∆V%ˆfF%˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb.)»R	MΩÚ---Ω“=ÌΩÌ¢µˆfF%˜GG5˜fˆñ6Uˆ∆&V¬Ü6Ü˜6V‚ó“‚
-]≠"=mR˝ÌΩ=}]“(	B}˝=≠‚=Ì-Ì˝ùçí--‚"ê¢vóB˜7F'E˜F∆∂ñÊuˆfF"áWFFR¬6ˆÁFWáB¬ñ÷r¬67&óE˜FWáC◊VÊFñÊu˜67&óBê¢&WGW&‡¢˜6WEˆfF%˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb.)»R	MΩÚ---Ω“=ÌΩÌ¢µˆfF%˜GG5˜fˆñ6Uˆ∆&V¬Ü6Ü˜6V‚ó“‚
-]˝]¬˝ççΩç-R-]≠"¬≠Ì-ÌΩíMÌΩm]“˝Ìç}›]-Ç--‚"ê¢&WGW&‡¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÖˆfF%˜fˆñ6Uˆ6Üˆñ6U˜FWáBÇí¬&W«ïˆ÷&∑W’ˆfF%˜fˆñ6Uˆ6Üˆñ6Uˆ∂"Ç&7B"íê¢&WGW&‡†¢2	=Ì-Ì˝ùçí--¢MÌ-‚=mR}==m]›‚¬mM¬-]≠"˝=ÌΩÌMΩÚ]}Ç‡¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊuˆfF%˜67&óB"ì†¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢ñbÊ˜Bñ÷s†¢ˆ6∆V%ˆfF%˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-
›}Ω}==}ç-R˝Ì-]"}]ΩÌ-]≠¬}-]¬›mÕç-R	˘z2	=Ì-Ì˝ùçí--‚"¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡¢ˆ6∆V%ˆfF%˜vóBÜ6ˆÁFWáBê¢vóB˜7F'E˜F∆∂ñÊuˆfF"áWFFR¬6ˆÁFWáB¬ñ÷r¬67&óE˜FWáC◊FWáBê¢&WGW&‡†¢2í›-çM]Ì≠ΩçÛ¢M-›]}-ççÕΩR-Ì˝Ì(	B›}Ω˝]›Ú¬}-]¬]mç=-çM]‚‡¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜fˆ6≈ˆ6∆ó˜&ˆ◊B"ì†¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢ñbÊ˜Bñ÷s†¢ˆ6∆V%˜fˆ6≈ˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-
›}Ω}==}ç-R˝Ì-]"ÌM›Ì=‚}]ΩÌ-]≠¬}-]¬›mÕç-R	¯ÍB	≠ΩçÚ-Ì≠ΩÌ¬‚"¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜fˆ6≈ˆ6∆ó˜&ˆ◊B"¬ÊˆÊRê¢6ˆÁFWáBÁW6W%ˆFF≤&◊W6ñ5˜fñFVıˆ◊W6ñ5ˆ'&ñVb%““FWáBÁ7G&óÇê¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊuˆ◊W6ñ5˜fñFVı˜fñFVıˆ'&ñVb%““G'VP¢2W'6ó7BFÜRdîDTÚ7FvR2vV∆¬2FÜR6ˆÊr'&ñVb‚FV∆Vw&“WFFW26‡¢2∆ÊBˆ‚g&W6Çv˜&∂W"˜&ˆ6W72¬6ÚW6W%ˆFF∆ˆÊRó2Ê˜BWFÜ˜&óFFófR‡¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢∑e˜6WBÜb&◊W6ñ5˜fñFVıˆ◊W6ñ5ˆ'&ñVcß∑WFFRÊVffV7FófU˜W6W"ÊñG“"¬FWáBÁ7G&óÇíê¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬&◊W6ñ7fñFVÛßfñFVÚ"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	¯ÍR
-]˝]¬Ì-M]ΩÕ›‚Ì˝ççç-R	-	ç	M	]	„¢}-‚˝Ìç]ÌMç""≠MR¬M]ù--çÚ=]ÌÚ¬≠=MÌ“çM"¬≠¢M-çm]-Ú≠Õ]¬Ì≠=m]›çR¬-]"ÇMç›ΩÕ›Ωí≠MÂ∆Â∆‚ ¢-	›˝çÕ]¢M-]ÇΩçM-Ì-≠Ω-Ì-Ú(i"Ú-Ω]Ìm2(i"≠Õ]Ì]ÌMç"Õ]›ÚÇ˝]]]ÌMç"}˝ç›2(i"Ω]M=]"}MÇ(i"Ú-Ω]Ìm2›ÌΩ›]}›=‚=Ωçm2¢Ì›m]-ÌÕ2∆÷&˜&vÜñÊíW'W2‚ ¢ê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊuˆ◊W6ñ5˜fñFVı˜fñFVıˆ'&ñVb"ì†¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢◊W6ñ5ˆ'&ñVb“Ü6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&◊W6ñ5˜fñFVıˆ◊W6ñ5ˆ'&ñVb"í˜"""íÁ7G&óÇê¢ñbÊ˜Bñ÷r˜"Ê˜B◊W6ñ5ˆ'&ñVc†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊuˆ◊W6ñ5˜fñFVı˜fñFVıˆ'&ñVb"¬ÊˆÊRê¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&◊W6ñ5˜fñFVıˆ◊W6ñ5ˆ'&ñVb"¬ÊˆÊRê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-
}]›Ì-ç¢≠Ωç˝˝Ì-]˝≤ç]ÌM›ΩRM››ΩR‚	›}›ç-R]mç¬í›-çM]Ì≠Ωç˝]ùr‚"ê¢&WGW&‡¢vóB˜7FvUˆ◊W6ñ5˜fñFVıˆG&gBáWFFR¬6ˆÁFWáB¬◊W6ñ5ˆ'&ñVc÷◊W6ñ5ˆ'&ñVb¬fñFVıˆ'&ñVc◊FWáBê¢&WGW&‡†¢2	Ìmç-Ω]›çRMÌ-‚˝‚˝ÌΩÕ}Ì--]ΩÕ≠ÌÕ2m]›ç„¢MÌ-‚=mR}==m]›‚¿¢2mM¬≠ÌÌ-≠çí÷˜Fñˆ‚&ˆ◊B¬}-]¬˝]MΩ=]¬-Ω-¬M-çmÌ¢‡¢ñb6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜&Wfóf≈ˆ7W7Fˆ’˜&ˆ◊B"¬ÊˆÊRì†¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢ñbÊ˜Bñ÷s†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç'&Wfóf≈ˆ7W7Fˆ’˜&ˆ◊B"¬ÊˆÊRê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-
›}Ω}==}ç-RMÌ-‚Ç›Ì-Ì-≠Ìù-R*Ω	Ìmç-ç-¬MÌ-Ï+≤‚"ê¢&WGW&‡¢6ˆÁFWáBÁW6W%ˆFF≤'&Wfóf≈ˆ7W7Fˆ’˜&ˆ◊B%““FWáBÁ7G&óÇê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)»R
m]›çíÌ]›“‚
-]˝]¬-Ω]ç-RM-çmÌ£¢"¿¢&W«ïˆ÷&∑W◊Ü˜Fı˜&Wfóf≈ˆVÊvñÊW5ˆ∂"Çí¿¢ê¢&WGW&‡†¢2	-çM]‚˝‚-]≠-2˝=ÌΩÌ3¢mM¬&ˆ◊B˝ÌΩR-ΩÌM-çm≠‡¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜FWáE˜fñFVı˜&ˆ◊B"ì†¢ˆ6∆V%˜FWáE˜fñFVı˜vóBÜ6ˆÁFWáBê¢vóB˜7F'E˜FWáE˜fñFVÚáWFFR¬6ˆÁFWáB¬FWáBê¢&WGW&‡†¢2
MÌ-Ó(i--çM]Ì≠ΩçÛ¢˝]-Ωí-]≠"˝ÌΩRMÌ-‚(	B-ÌΩÕ≠‚Õ=}Ω≠ΩÕ›ΩíçB‡¢2	›R˝]]M¬]=‚≠¢∆Vv7í6ˆ÷&ñÊVB&ˆ◊B¬ç›}RÌ“M=Ωç=]-Ú"dîDTıÙ%$îTb‡¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜Ü˜Fıˆ6∆ó˜&ˆ◊B"ì†¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢ñbÊ˜Bñ÷s†¢ˆ6∆V%˜Ü˜Fıˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-
›}Ω}==}ç-RMÌ-‚}]ΩÌ-]≠¬}-]¬›mÕç-R	¯ÎR
MÌ-‚(i"-çM]Ì≠ΩçÚ‚"¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜Ü˜Fıˆ6∆ó˜&ˆ◊B"¬ÊˆÊRê¢6ˆÁFWáBÁW6W%ˆFF≤&◊W6ñ5˜fñFVıˆ◊W6ñ5ˆ'&ñVb%““FWáBÁ7G&óÇê¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊuˆ◊W6ñ5˜fñFVı˜fñFVıˆ'&ñVb%““G'VP¢2W'6ó7BFÜRdîDTÚ7FvR2vV∆¬2FÜR6ˆÊr'&ñVb‚FÜó2&WfVÁG2FÜP¢2ÊWáB÷W76vRg&ˆ“f∆∆ñÊrFá&˜VvÇFÚvVÊW&ñ2uBı7VÊÚ6&ñ∆óGíFWáB‡¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢∑e˜6WBÜb&◊W6ñ5˜fñFVıˆ◊W6ñ5ˆ'&ñVcß∑WFFRÊVffV7FófU˜W6W"ÊñG“"¬FWáBÁ7G&óÇíê¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬&◊W6ñ7fñFVÛßfñFVÚ"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	¯Í¬
-]˝]¬Ì-M]ΩÕ›‚Ì˝ççç-R	-	ç	M	]	„¢}-‚˝Ìç]ÌMç""≠MR¬M]ù--çÚ=]ÌÚ¬≠=MÌ“çM"¬≠¢M-çm]-Ú≠Õ]¬Ì≠=m]›çR¬-]"ÇMç›ΩÕ›Ωí≠MÂ∆Â∆‚ ¢-	›˝çÕ]¢M-]ÇΩçM-Ì-≠Ω-Ì-Ú(i"Ú-Ω]Ìm2(i"≠Õ]˝Ω-›‚Ì]ÌMç"Õ]›ÚÇ˝]]]ÌMç"}˝ç›2(i"Ω]M=]"}MÇ˝‚≠ÌçMÌ2(i"Ú-Ω]Ìm2›ÌΩ›]}›=‚=Ωçm2¢Ì›m]-ÌÕ2∆÷&˜&vÜñÊíW'W2Â∆Â∆‚ ¢-
›-}-¬›R=M]"Ì-˝-Ω˝-ÕÚ"7VÊÚ‚ ¢ê¢&WGW&‡†¢2
-]≠-Ì-Ωí˝=ÌΩÌÌ-Ìí}˝Ì›]-=ç¬M‚}==}≠ÇMÌ-‚‡¢2
›-‚Ω-]"Õ]Mçmç›2Ç˝]]-ÌMç"Ω]M=Ìù]Rç}Ìm]›çR"ñ÷vR÷VFóB‡¢ñbˆó5ˆñ÷vU˜&WF˜V6Ö˜&WVW7BáFWáBì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢ñbñ÷rÊBˆÜ5ˆ˜vÂˆñ÷vUˆ6ˆÊfó&÷Fñˆ‚áFWáBì†¢vóB˜7F'Eˆñ÷vU˜&WF˜V6ÇáWFFR¬6ˆÁFWáB¬ñ÷r¬FWáBê¢&WGW&‡¢˜6WE˜vóFñÊuˆñ÷vU˜&WF˜V6ÇáWFFR¬6ˆÁFWáB¬FWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÖ˜&WF˜V6Ö˜W6W%ˆÜñÁE˜FWáBÇí¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡†¢ñbˆó5ˆï˜6V∆fñUˆñÁFVÁBáFWáBì†¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢&ˆ◊B“ˆ6∆VÂˆï˜6V∆fñU˜&ˆ◊BáFWáBê¢ñbñ÷rÊB&ˆ◊C†¢vóB˜7F'Eˆï˜6V∆fñRáWFFR¬6ˆÁFWáB¬ñ÷r¬&ˆ◊Bê¢&WGW&‡¢˜6WEˆï˜6V∆fñU˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢-	M¬M]Ω‚í›]ΩMÉ¢}==}ç-R-ÌMÌ-‚¬}-]¬›˝ççç-R¬≠]¬˝=MRM]Ω-¬m]›2‚	›˝çÕ]¢*Ω]ΩMÇç}-]-›Ω¬≠-Ì¬›≠›ÌíMÌÌm≠R¬ïÜˆÊR6V∆fñR¬C£\+≤‚"¿¢&W«ïˆ÷&∑W÷÷ñÂˆ∂"¿¢ê¢&WGW&‡†¢ñbˆó5ˆfF%ˆñÁFVÁBáFWáBì†¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢67&óB“ˆ6∆VÂˆfF%˜67&óBáFWáBê¢ñbñ÷s†¢ñb67&óBÊB∆V‚á67&óBí‚É†¢6ˆÁFWáBÁW6W%ˆFF≤&fF%˜VÊFñÊu˜67&óB%““67&ó@¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&fF%˜GG5˜fˆñ6R"ì†¢VÊFñÊu˜67&óB“Ü6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&fF%˜VÊFñÊu˜67&óB"í˜"""íÁ7G&óÇê¢ñbVÊFñÊu˜67&óC†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&fF%˜VÊFñÊu˜67&óB"¬ÊˆÊRê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b.)»R	˝Ì-]"›ùM]“‚	=ÌΩÌ=mR-Ω”¢µˆfF%˜GG5˜fˆñ6Uˆ∆&V¬ÖˆfF%˜GG5˜fˆñ6UˆvWBÜ6ˆÁFWáBíó“‚
-]≠"=mR˝ÌΩ=}]“(	B}˝=≠‚=Ì-Ì˝ùçí--‚ ¢ê¢vóB˜7F'E˜F∆∂ñÊuˆfF"áWFFR¬6ˆÁFWáB¬ñ÷r¬67&óE˜FWáC◊VÊFñÊu˜67&óBê¢V«6S†¢˜6WEˆfF%˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b.)»R	˝Ì-]"›ùM]“‚	=ÌΩÌ=mR-Ω”¢µˆfF%˜GG5˜fˆñ6Uˆ∆&V¬ÖˆfF%˜GG5˜fˆñ6UˆvWBÜ6ˆÁFWáBíó“‚
-]˝]¬˝ççΩç-R-]≠"¬fˆñ6RçΩÇ=MçÌMù≤.(	3c]≠=›B‚ ¢ê¢V«6S†¢˜6WEˆfF%˜fˆñ6Uˆ6Üˆñ6U˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÖˆfF%˜fˆñ6Uˆ6Üˆñ6U˜FWáBÇí¬&W«ïˆ÷&∑W’ˆfF%˜fˆñ6Uˆ6Üˆñ6Uˆ∂"Ç&7B"íê¢V«6S†¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊuˆfF%˜Ü˜FÚ%““G'VP¢ñb67&óBÊB∆V‚á67&óBí‚É†¢6ˆÁFWáBÁW6W%ˆFF≤&fF%˜VÊFñÊu˜67&óB%““67&ó@¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢-	M¬M]Ω‚=Ì-Ì˝ùçí--‚
›}Ω}==}ç-R˝Ì-]"}]ΩÌ-]≠‚	˝ÌΩR}==}≠ÇÚÌ˝}-]ΩÕ›‚˝]MΩÌm2-Ω-¬=ÌΩÌ¬}-]¬ç˝ÌΩÕ}=‚-Ç-]≠"¬fˆñ6RçΩÇ=MçÌMù≤.(	3c]≠=›B‚"¿¢&W«ïˆ÷&∑W÷÷ñÂˆ∂"¿¢ê¢&WGW&‡†¢ñbˆó5˜Ü˜Fıˆ6∆óˆñÁFVÁBáFWáBì†¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢&ˆ◊B“ˆ6∆VÂ˜Ü˜Fıˆ6∆ó˜&ˆ◊BáFWáBê¢ñbñ÷rÊB&ˆ◊C†¢vóB˜7FvUˆ◊W6ñ5˜fñFVıˆG&gBáWFFR¬6ˆÁFWáB¬&ˆ◊Bê¢&WGW&‡¢˜6WE˜Ü˜Fıˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢-	M¬M]Ω‚-çM]Ì≠ΩçÚçrMÌ-‚‚	}==}ç-RMÌ-‚}]ΩÌ-]≠¬}-]¬Ì˝ççç-R-çΩ¬≠Ωç˝˝Õ=}Ω≠Ç¬MΩç-]ΩÕ›Ì-¬ÇMÌÕ"‚"¿¢&W«ïˆ÷&∑W÷÷ñÂˆ∂"¿¢ê¢&WGW&‡†¢2	-Ì˝Ì˝≠ÌÕ›M˝‚Ìmç-Ω]›çRMÌ-‚MÌΩm›≤Ω--¬Õ]Mçmç›≠=‚-]-≠2‡¢2	ç›}R˝ÌΩR≠›Ì˝≠Ç*Ω	Õ]Mçmç›+≤Ω]M=Ìù]RÌΩ}›ÌRMÌ-‚ÌççÌ}›‚=]ÌMç""Õ]B‚›Ωçr‡¢ñbˆó5˜Ü˜Fı˜&Wfóf≈˜VW7Fñˆ‚áFWáBí˜"ˆó5˜Ü˜Fı˜&Wfóf≈ˆñÁFVÁBáFWáBì†¢˜6WE˜vóFñÊu˜Ü˜Fı˜&Wfóf¬áWFFR¬6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÖ˜Ü˜Fı˜&Wfóf≈ˆ6&ñ∆óGï˜FWáBÇí¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡†¢2∆Vv7í&W6VÁFFñˆ‚f∆w2g&ˆ“ˆ∆FW"FW∆˜ñ÷VÁG2&R÷ñw&FVBñÁFÚFÜRcÉb7GVFñÚ‡¢ñb6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜v˜&µ˜&W6VÁFFñˆÂˆ'&ñVb"¬ÊˆÊRì†¢vóB˜&W6VÁFFñˆÂ˜7GVFñıˆvWBÇíÁ7F'BáWFFR¬6ˆÁFWáB¬'&W6VÁFFñˆ‚"ê¢ñbvóB˜&W6VÁFFñˆÂ˜7GVFñıˆvWBÇíÊÜÊF∆U˜FWáBáWFFR¬6ˆÁFWáB¬FWáBì†¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜v˜&µˆ6F∆ˆuˆ'&ñVb"¬ÊˆÊRì†¢vóB˜&W6VÁFFñˆÂ˜7GVFñıˆvWBÇíÁ7F'BáWFFR¬6ˆÁFWáB¬&6F∆ˆr"ê¢ñbvóB˜&W6VÁFFñˆÂ˜7GVFñıˆvWBÇíÊÜÊF∆U˜FWáBáWFFR¬6ˆÁFWáB¬FWáBì†¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜v˜&µˆ∆ˆvıˆ'&ñVb"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜v˜&µˆ∆ˆvıˆ'&ñVb"¬ÊˆÊRê¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬'v˜&µˆ∆ˆvÚ"ê¢vóBˆvVÊW&FUˆ'W6ñÊW75ˆ∆ˆvÚáWFFR¬6ˆÁFWáB¬FWáBê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊuˆ◊W6ñ5˜fñFVıˆVFñı˜&ˆ◊EˆVFóB"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊuˆ◊W6ñ5˜fñFVıˆVFñı˜&ˆ◊EˆVFóB"¬ÊˆÊRê¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç'fˆ6≈˜6˜W&6U˜Fˆ∂V‚"¬ÊˆÊRê¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&◊W6ñ5˜fñFVı˜VÊFñÊuˆVFñı˜Fˆ∂V‚"¬ÊˆÊRê¢ÊWuˆ'&ñVb“FWáBÁ7G&óÇê¢ñbÊ˜BÊWuˆ'&ñVc†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	˝ÌÕ˝"˝=-Ìí‚	›mÕç-R*æ)»˛˚àÚ	ç}Õ]›ç-¬˝ÌÕ˝"=MçÏ+≤]ùr‚"ê¢&WGW&‡¢6ˆÁFWáBÁW6W%ˆFF≤&◊W6ñ5˜fñFVı˜VÊFñÊuˆ◊W6ñ5ˆ'&ñVb%““ÊWuˆ'&ñV`¢VÊFñÊu˜&ˆ◊B“Ü6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&◊W6ñ5˜fñFVı˜VÊFñÊu˜&ˆ◊B"í˜"""íÁ7G&óÇê¢ñbVÊFñÊu˜&ˆ◊C†¢Ú¬VÊFñÊu˜fñFVÚ“ˆ◊W6ñ5˜fñFVı˜7∆óEˆ'&ñVg2áVÊFñÊu˜&ˆ◊Bê¢6ˆÁFWáBÁW6W%ˆFF≤&◊W6ñ5˜fñFVı˜VÊFñÊu˜&ˆ◊B%““ˆ◊W6ñ5˜fñFVıˆ¶ˆñÂˆ'&ñVg2ÜÊWuˆ'&ñVb¬VÊFñÊu˜fñFVÚê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)»˛˚àÚ	˝ÌÕ˝"Ì›Ì-Ω“‚	=]›]ç=‚›Ì-Ωí-ç›"7VÊÛ≤-çM]‚˝Ì≠›R}˝=≠‚‚"ê¢g&W6Ç“vóB˜'VÂ˜7VÊıˆ◊W6ñ5˜&W7V«Eˆ'óFW2áWFFR¬ÊWuˆ'&ñVbê¢ñbÊ˜Bg&W6É†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬7VÊÚ›R-]›=≤›Ì-Ωí-ç›"‚	˝Ì˝Ì=ù-Rç}Õ]›ç-¬˝ÌÕ˝"]ùr‚"ê¢&WGW&‡¢ÊWu˜Fˆ∂V‚“WVñBÁWVñCBÇíÊÜWÖ≥£%–¢6ˆÁFWáBÁW6W%ˆFF≤&◊W6ñ5˜fñFVı˜VÊFñÊuˆVFñı˜Fˆ∂V‚%““ÊWu˜Fˆ∂V‡¢vóB7ñÊ6ñÚÁFı˜Fá&VBÖ˜6fU˜fˆ6≈ˆ'Fñf7B¬WFFRÊVffV7FófU˜W6W"ÊñB¬ÊWu˜Fˆ∂V‚¬&VFñÚ"¬g&W6Çê¢vóB˜6VÊE˜fˆ6≈˜6ˆÊuˆfñ∆RáWFFRÊVffV7FófUˆ÷W76vR¬g&W6Ç¬ÊWu˜Fˆ∂V‚ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	¯Ír	˝Ì-]Õ-R›Ì-Ωí-ç›"‚"¬&W«ïˆ÷&∑W’˜fˆ6≈˜6ˆÊuˆ∂"ÜÊWu˜Fˆ∂V‚¬VÊFñÊs’G'VRíê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜7VÊıˆ'&ñVb"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜7VÊıˆ'&ñVb"¬ÊˆÊRê¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬'7VÊıˆ◊W6ñ2"ê¢7VÊıˆ'&ñVb“˜&W&U˜7VÊıˆ'&ñVeˆg&ˆ’ˆ6ˆÁFWáBÜ6ˆÁFWáB¬FWáBê¢vóB˜'VÂ˜7VÊıˆ◊W6ñ2áWFFR¬6ˆÁFWáB¬7VÊıˆ'&ñVbê¢&WGW&‡†¢2	]ΩÇ˝ÌΩÕ}Ì--]Ω¬-Ω≤&VV«2˝MçΩÕ¬"Õ]›‚Ç-]˝]¬˝çç]"--ÌM›ΩR(	@¢2›}ΩM¬-=≠-=çÌ-››Ωím]››ΩíÌ--]"¬›RÌùçí}"‡¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜&VV«5ˆ÷FW&ñ¬"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜&VV«5ˆ÷FW&ñ¬"¬ÊˆÊRê¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬&gVÂ˜&VV«2"ê¢&ˆ◊B“Ä¢-
-≤˝ÌMÌ]≠ÌÌ-≠çR&VV«2ı6Ü˜'G2‚	›=≠Ì¬˝ÌM=Ì-Ì-√¢í]=¢¬"ím]›çí˝‚]≠=›M¬¬ ¢#2í-]≠"››≠›R¬Bífˆñ6R÷˜fW"¬Rí5D¬bí˝ÌÕ˝-≤MΩÚ6˜&Ù∂∆ñÊr¬ ¢#ríÕÌ›-m›ΩR˝ÌM≠}≠Ç‚	}˝Ì˝ÌΩÕ}Ì--]ΩÛ•∆‚"≤FWá@¢ê¢&W«í“vóB6µˆ˜VÊï˜FWáBá&ˆ◊Bê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBá&W«ï≥£3ì“¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢ñb∆V‚á&W«íí‚3ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBá&W«ï≥3ì£sÉ“ê¢vóB÷ñ&U˜GG5˜&W«íáWFFR¬6ˆÁFWáB¬&W«ï≥•EE5Ù‘ÖÙ4Ñ%5“ê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊuˆfñ∆’ˆ÷FW&ñ¬"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊuˆfñ∆’ˆ÷FW&ñ¬"¬ÊˆÊRê¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬&gVÂˆfñ∆“"ê¢&ˆ◊B“Ä¢-
-≤]mçÇ˝ÌÕ˝"›ç›m]›]í›-çM]‚‚	›=≠Ì¬˝ÌM=Ì-Ì-¬Õç›Ç›MçΩÕ√¢ ¢#íΩÌ=Ωù“¬"í-=≠-=m]“¬2í≠MÌ-≠¬Bí˝ÌÕ˝-≤MΩÚ≠ÌÌ-≠çR≠Ωç˝Ì"R”]¢ ¢-}]]r6˜&"]rΩÌM]í¬∂∆ñÊrçΩÇ'VÁví¬RíÕÌ›-b˝}-=¢˝-ç-≤¬bí˝Ω“Ì≠Ç‚	}˝Ì˝ÌΩÕ}Ì--]ΩÛ•∆‚"≤FWá@¢ê¢&W«í“vóB6µˆ˜VÊï˜FWáBá&ˆ◊Bê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBá&W«ï≥£3ì“¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢ñb∆V‚á&W«íí‚3ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBá&W«ï≥3ì£sÉ“ê¢vóB÷ñ&U˜GG5˜&W«íáWFFR¬6ˆÁFWáB¬&W«ï≥•EE5Ù‘ÖÙ4Ñ%5“ê¢&WGW&‡†¢2	-Ì˝Ì≤‚-Ì}ÕÌm›Ì-˝R‡¢2	]ΩÇ-Ì˝Ì›RÕ]Mçmç›≠çí¬Ω-]¬}-çççíÕ]B‚]mç¬¿¢2}-Ì≤Ω]M=ÌùçRMÌ-‚˝MÌ≠=Õ]›-≤›R=]ÌMçΩÇÌççÌ}›‚"Õ]Mçmç›2‡¢6“6&ñ∆óGïˆÁ7vW"áFWáBê¢ñb6†¢ñbÊ˜Bˆó5ˆ÷VFñ6≈ˆ6&ñ∆óGï˜VW7Fñˆ‚áFWáBì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜ6¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡†¢2	›Õ¢›Õ=}Ω≠2Ú˝]›‚}]]r7VÊ¢ñb&RÁ6V&6Çá""ÉÛ≠Ì}MΩùÖ◊ÕM]ΩΩùÖ◊Õ=]›]ç5ΩùÖ◊Õ›˝ççáÕ}˝=-ÇíÁ≥√É“çÕ=}ΩßÕ˝]◊Õ-]ßÕMmç›=∑ÕÕç›=Ì-ß«7VÊÚí"¬FWáB¬&R‰íì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬'7VÊıˆ◊W6ñ2"ê¢vóB˜'VÂ˜7VÊıˆ◊W6ñ2áWFFR¬6ˆÁFWáB¬FWáBê¢&WGW&‡†¢2	›Õ¢›=]›]mç‚-çM]ÌÌΩç≠ ¢◊GóR¬&W7B“FWFV7Eˆ÷VFñˆñÁFVÁBáFWáBê¢ñb◊GóR”“'fñFVÚ#†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢GW&Fñˆ‚¬7V7B“'6U˜fñFVıˆ˜G2áFWáBê¢&ˆ◊B“&W7B˜"&RÁ7V"Ä¢"%∆"Ö∆Bµ«2¢ÉÛ≠]ßÕï∆'¬ÉÛ£ì£g√c£ó√£√C£W√3£G√C£2íí"¿¢""¿¢FWáB¿¢f∆w3◊&R‰í¿¢íÁ7G&óÇ"¬‚"ê†¢ñbÊ˜B&ˆ◊C†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢-	Ì˝ççç-R¬}-‚çÕ]››‚›˝-¬¬›˝„¢*Ω]-‚›--‚›]]=2¬}≠,+≤‚ ¢ê¢&WGW&‡†¢ñB“ˆÊWuˆñBÇê¢˜VÊFñÊuˆ7FñˆÁ5∂ñE““∞¢'&ˆ◊B#¢&ˆ◊B¿¢&GW&Fñˆ‚#¢GW&Fñˆ‚¿¢&7V7B#¢7V7B¿¢–†¢V˜∆U˜&W6VÁB“˜&ˆ◊Eˆ∆ñ∂V«ïˆÜ5˜V˜∆Rá&ˆ◊Bê¢'WGFˆÁ2“µ–¢ñbÊ˜BV˜∆U˜&W6VÁC†¢'WGFˆÁ2ÊVÊBÖ¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb/	¯È‚6˜&"+r]rΩÌM]í+rµ˜fñFVı˜&ñ6Uˆ7&VFóG2Çw6˜&r¬GW&Fñˆ‚ó“≠‚"¬6∆∆&6µˆFF÷b&6Üˆ˜6Sß6˜&ß∂ñG“"ï“ê¢'WGFˆÁ2ÊVÊBÖ¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb/	¯Í¬∂∆ñÊr+rµ˜fñFVı˜&ñ6Uˆ7&VFóG2Çv∂∆ñÊrr¬GW&Fñˆ‚ó“≠‚"¬6∆∆&6µˆFF÷b&6Üˆ˜6S¶∂∆ñÊsß∂ñG“"ï“ê¢ñbDUÖEıdîDTıÙƒƒıuı%TÂtì†¢'WGFˆÁ2ÊVÊBÖ¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Üb/	¯ÍR'VÁví+rµ˜fñFVı˜&ñ6Uˆ7&VFóG2Çw'VÁvír¬GW&Fñˆ‚ó“≠‚"¬6∆∆&6µˆFF÷b&6Üˆ˜6Sß'VÁvìß∂ñG“"ï“ê¢∂"“ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑WÜ'WGFˆÁ2ê¢6˜&ˆÊ˜FR“-	"}˝ÌRÌ›=m]“}]ΩÌ-]¢(	B6˜&"≠Ω-‚"ñbV˜∆U˜&W6VÁBV«6R%6˜&"MÌ-=˝›-ÌΩÕ≠‚MΩÚm]“]rΩÌM]í‚ ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢b-
}-‚ç˝ÌΩÕ}Ì--√ı∆Ì	MΩç-]ΩÕ›Ì-√¢∂GW&FñˆÁ“2(
"	˝]≠#¢∂7V7G’∆Ì	}˝Ì¢*∑∑&ˆ◊G‹+µ∆Â∆Á∑6˜&ˆÊ˜FW’∆Ì
-ÌçÕÌ-¬=mR-≠ΩÌ}]"Õm2Ì-Ç=M]"˝ç›-ÌΩÕ≠‚˝ÌΩR=˝]ç›Ì=‚]}=ΩÕ--‚"¿¢&W«ïˆ÷&∑W÷∂"¿¢ê¢&WGW&‡†††¢2	›Õ¢›≠-ç›≠0¢ñb◊GóR”“&ñ÷vR#†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢&ˆ◊B“&W7B˜"&RÁ7V"Ä¢"%‚Üñ÷w∆ñ÷vW«ñ7GW&Rï«2•≥•¬’’«2¢"¿¢""¿¢FWáB¿¢f∆w3◊&R‰í¿¢íÁ7G&óÇê†¢ñbÊ˜B&ˆ◊C†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢-
MÌÕ#¢ˆñ÷rÕÌ˝ç›çRç}Ìm]›çÛ‚ ¢ê¢&WGW&‡†¢vóBˆ6µˆñ÷vUˆVÊvñÊUˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬&ˆ◊Bê¢&WGW&‡†¢2∆ófR›}˝Ì≥¢≠=≤¬›Ì-Ì-Ç¬}≠Ì›≤¬˝Ì=ÌM¬]Ωç}≤ÇΩÌΩR≠-=ΩÕ›ΩRM››ΩR‡¢2	=ÌΩÌÌ-ΩR}˝Ì≤˝Ì˝MÌ"ÌM}]]rˆÂ˜FWáE˜vóFÖ˜FWáB˝ÌΩR5EB‡¢ñbÊ˜BÙ‘TDî4≈ıDU$’5ı$RÁ6V&6ÇáFWáBì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢ñbvóB÷ñ&UˆÜÊF∆Uˆ∆ófU˜VW'íáWFFR¬6ˆÁFWáB¬FWáBì†¢&WGW&‡†¢2	ÌΩ}›Ωí-]≠"(i"u@¢ˆ≤¬Ú¬Ú“6ÜV6µ˜FWáEˆÊEˆñÊ2Ä¢WFFRÊVffV7FófU˜W6W"ÊñB¿¢WFFRÊVffV7FófU˜W6W"ÁW6W&Ê÷R˜"""¿¢ê†¢ñbÊ˜Bˆ≥†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢-	ΩçÕç"-]≠-Ì-ΩR}˝ÌÌ"›]=ÌM›Úç}]˝“‚ ¢-	ÌMÌÕç-R*Ÿ˝ÌM˝ç≠2çΩÇ˝Ì˝Ì=ù-R}--‚ ¢ê¢&WGW&‡†¢W6W%ˆñB“WFFRÊVffV7FófU˜W6W"Êñ@†¢2
]mçÕ∞¢G'ì†¢÷ˆFR“ˆ÷ˆFUˆvWBáW6W%ˆñBê¢G&6≤“ˆ÷ˆFU˜G&6µˆvWBáW6W%ˆñBê¢WÜ6WBÊ÷TW'&˜#†¢÷ˆFR¬G&6≤“&ÊˆÊR"¬" †¢ñb÷ˆFRÊB÷ˆFR“&ÊˆÊR#†¢FWáEˆf˜%ˆ∆∆““b%Ω
]mç√¢∂÷ˆFW”≤	˝ÌM]mç√¢∑G&6≤˜"r“w’’∆Á∑FWáG“ ¢V«6S†¢FWáEˆf˜%ˆ∆∆““FWá@†¢ñbÙ‘TDî4≈ıDU$’5ı$RÁ6V&6ÇáFWáBì†¢2
˝-›ΩíÕ]Mçmç›≠çí-Ì˝Ì˝-]≠"(	B}ç]¬≠¢Õ]B‚Õ-]ç≤‡¢vóBˆ÷VFñ6≈ˆÊ«ó¶U˜FWáBáWFFR¬6ˆÁFWáB¬FWáBê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáW6W%ˆñB¬""ê¢&WGW&‡†¢2	]ΩÇ˝ÌΩÕ}Ì--]Ω¬›ÕçR›m≤Õ]B‚˝ÌMÕ]›‚¬›‚-]˝]¬˝çç-]"˝‚Db¬≠›ç=Ç¬MÌ-‚¿¢2-çM]‚¬›Ì-Ì-Ç¬≠=%D2Ç"ÌÚ‚¬›RM]mç¬]=‚"Õ]Mçmç›≠Ìí-]-≠R‡¢ñbáG&6≤˜"""íÁ7F'G7vóFÇÇ&÷VEÚ"íÊBÊ˜B6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&÷VFñ6ñÊU˜vóFñÊuˆf˜%ˆ÷FW&ñ¬"ì†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáW6W%ˆñB¬""ê†¢ñb÷ˆFR”“-
=}"ÊBG&6≥†¢vóB7GVGï˜&ˆ6W75˜FWáBáWFFR¬6ˆÁFWáB¬FWáBê¢&WGW&‡†¢6ÜEˆñB“WFFRÊVffV7FófUˆ6ÜBÊñBñbWFFRÊVffV7FófUˆ6ÜBV«6R ¢2	]ΩÇ›-‚≠ÌÌ-≠çíÌ--]"›˝]MΩM=ùçí=-Ì}›˝Ìùçí-Ì˝Ì¬çç˝]¬}˝Ì≠Ì›-]≠-Ì¬‡¢∆∆’ˆñÁWB“ˆ6ÜEˆ÷V÷˜'ïˆfˆ∆∆˜wW˜VW'íáW6W%ˆñB¬6ÜEˆñB¬FWáEˆf˜%ˆ∆∆“ê¢&W«í“vóB6µˆ˜VÊï˜FWáBÜ∆∆’ˆñÁWB¬W6W%ˆñC◊W6W%ˆñB¬6ÜEˆñC÷6ÜEˆñBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBá&W«íê¢ˆ6ÜEˆ÷V÷˜'ïˆFBáW6W%ˆñB¬6ÜEˆñB¬'W6W""¬FWáBê¢ˆ6ÜEˆ÷V÷˜'ïˆFBáW6W%ˆñB¬6ÜEˆñB¬&76ó7FÁB"¬&W«íê¢vóB÷ñ&U˜GG5˜&W«íáWFFR¬6ˆÁFWáB¬&W«ï≥•EE5Ù‘ÖÙ4Ñ%5“ê†¢2)H)H)H)H)H)H)H)H)H
MÌ-‚Ú	MÌ≠=Õ]›-≤Ú	=ÌΩÌ)H)H)H)H)H)H)H)H)H ¶7ñÊ2FVbˆÂ˜Ü˜FÚáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢G'ì†¢Ç“WFFRÊ÷W76vRÁÜ˜Fı≤”–¢b“vóBÇÊvWEˆfñ∆RÇê¢FF“vóBbÊF˜vÊ∆ˆEˆ5ˆ'óFV'&íÇê¢ñ÷r“'óFW2ÜFFê¢ˆ66ÜU˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñB¬ñ÷r¬vWFGG"Üb¬&fñ∆U˜FÇ"¬""í˜"""ê†¢W6W%ˆñB“WFFRÊVffV7FófU˜W6W"Êñ@¢6Fñˆ‚“áWFFRÊ÷W76vRÊ6Fñˆ‚˜"""íÁ7G&óÇê†¢2ÜñvÇ÷fñFV∆óGí◊W6ñ2◊fñFVÚ6≤˜vÁ2FÜW6Rf˜W"W∆ˆG2&Vf˜&RWfW'ívVÊW&ñ2Ü˜FÚf∆˜r‡¢ñFVÁFóGï˜6∆˜B“ˆ◊W6ñ5˜fñFVıˆñFVÁFóGï˜vóE˜6∆˜BÜ6ˆÁFWáBê¢2FVfVÁ6ófR&V6˜fW'ì¢FV∆Vw&“˜W6W%ˆFFó2&ˆ6W72÷∆ˆ6¬ÊB6‚&R∆˜7Bˆ‚¢2FW∆˜í˜&W7F'B‚vÜñ∆RFÜRW6W"ó27Fñ∆¬ñ‚FÜRÜ˜Fˆ6∆óG&6≤¬‚ñÊ6ˆ◊∆WFP¢2ñFVÁFóGí6≤÷VÁ2FÜRÊWáBVÊ6∆ñ÷VBÜ˜FÚ&V∆ˆÊw2FÚFÜRfó'7B÷ó76ñÊr6∆˜B¿¢2Ê˜BFÚFÜRvVÊW&ñ2Ü˜FÚ÷VÁR‡¢ñbÊ˜BñFVÁFóGï˜6∆˜C†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ñbˆ÷ˆFU˜G&6µˆvWBáW6W%ˆñBí”“'Ü˜Fˆ6∆ó"ÊBÊ˜Bˆ◊W6ñ5˜fñFVıˆñFVÁFóGïˆ6ˆ◊∆WFRáW6W%ˆñBì†¢&Vg2“ˆ◊W6ñ5˜fñFVıˆñFVÁFóGï˜6≤áW6W%ˆñBê¢ñFVÁFóGï˜6∆˜B“ÊWáBÄ¢á6∆˜Bf˜"6∆˜Bñ‚Ç&f6Uˆg&ˆÁB"¬&f6UÛ7"¬&&ˆGïˆgV∆¬"¬'66VÊU˜&VfW&VÊ6R"íñbÊ˜B&Vg2ÊvWBá6∆˜Bíí¿¢""¿¢ê¢ñbñFVÁFóGï˜6∆˜C†¢˜6WEˆ◊W6ñ5˜fñFVıˆñFVÁFóGï˜vóBÜ6ˆÁFWáB¬ñFVÁFóGï˜6∆˜Bê¢ñbñFVÁFóGï˜6∆˜C†¢ˆ◊W6ñ5˜fñFVıˆñFVÁFóGï˜WBáW6W%ˆñB¬ñFVÁFóGï˜6∆˜B¬ñ÷rê¢ñbñFVÁFóGï˜6∆˜B”“&f6Uˆg&ˆÁB#†¢˜6WEˆ◊W6ñ5˜fñFVıˆñFVÁFóGï˜vóBÜ6ˆÁFWáB¬&f6UÛ7"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)»RÛ2(	BΩçm‚›MÌ]›]›‚Ì-M]ΩÕ›‚Â∆Â∆‚ ¢#"Û2(	B}==}ç-RΩçm‚˝Ì-ÌÌ-Ì¬˝çÕ]›‚3(	3C\+‚ ¢ê¢V∆ñbñFVÁFóGï˜6∆˜B”“&f6UÛ7#†¢˜6WEˆ◊W6ñ5˜fñFVıˆñFVÁFóGï˜vóBÜ6ˆÁFWáB¬&&ˆGïˆgV∆¬"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)»R"Û2(	B≠=3(	3C\+Ì]›“Ì-M]ΩÕ›‚Â∆Â∆‚ ¢#2Û2(	B}==}ç-RMÌ-‚	"	˝	Ì	Ω	›
Ω	í
	Ì

"¬Ì"=ÌΩÌ-≤M‚›Ì2‚ ¢ê¢V∆ñbñFVÁFóGï˜6∆˜B”“&&ˆGïˆgV∆¬#†¢˜6WEˆ◊W6ñ5˜fñFVıˆñFVÁFóGï˜vóBÜ6ˆÁFWáB¬'66VÊU˜&VfW&VÊ6R"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)»R6Ü&7FW"ñFVÁFóGí6≤Ì”¢d4UÙe$ÙÂB≤d4UÛ5≤$ÙEïÙeTƒ¬Â∆Â∆‚ ¢-
-]˝]¬}==}ç-R44T‰Uı$TdU$T‰4R(	B--Ì-Ωí≠MÌ≠=m]›çÚ˝˝Ì}≤‚ ¢-	Ì“}M"m]›2Ç≠ÌÕ˝Ì}çmç‚¬›‚	›	R}Õ]›˝]"MÌ-Ì=MçÇΩç}›Ì-Ç‚ ¢ê¢V«6S†¢˜6WEˆ◊W6ñ5˜fñFVıˆñFVÁFóGï˜vóBÜ6ˆÁFWáB¬'66VÊU˜&VfW&VÊ6R"ê¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&◊W6ñ5˜fñFVı˜66VÊU˜&VfW&VÊ6R"¬ÊˆÊRê¢˜6WE˜Ü˜Fıˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)»R44T‰Uı$TdU$T‰4RÌ]›“Ì-M]ΩÕ›‚‚	-RB&VfW&VÊ6R=Ì-Ì-≤Â∆Â∆‚ ¢/	¯ÎR
-]˝]¬Ì-M]ΩÕ›‚Ì˝ççç-R	˝	]
	›
„¢m›¬›-Ì]›çR¬˝}Ω¢¬-]Õ2-]≠-¬ ¢-›=m]“ΩÇ-Ì≠≤Ç≠≠ç¬=ÌΩÌÌ¬‚	˝ÌΩR›-Ì=‚ÚÌ-M]ΩÕ›‚˝Ìç2	-	ç	M	]	‚‚ ¢ê¢&WGW&‡†¢2&W6VÁFFñˆ‚7GVFñÛ¢∆ˆvÚ˜&ˆGV7BÜ˜FÚ'V∆≤W∆ˆB‡¢ñbvóB˜&W6VÁFFñˆÂ˜7GVFñıˆvWBÇíÊÜÊF∆U˜Ü˜FÚáWFFR¬6ˆÁFWáB¬ñ÷r¬÷ñ÷S“&ñ÷vRˆßVr"¬6Fñˆ„÷6Fñˆ‚ì†¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&◊W6ñ5˜fñFVıˆG&gB"¬ÊˆÊRì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&◊W6ñ5˜fñFVıˆG&gEˆVFóB"¬ÊˆÊRê¢˜6WE˜Ü˜Fıˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	˘;Ç
MÌ-‚MΩÚ≠Ωç˝Ì›Ì-Ω]›‚‚	Ì˝ççç-Rm]›çí]ùr¬}-Ì≤=--]Mç-¬]=‚MΩÚ›-Ì=‚MÌ-‚‚ ¢ê¢&WGW&‡†¢2í	}Õ]›Ωçm¢M-=]ç=Ì-Ωí]mç¬MÌΩm]“-Ω--¬›ÕçRÌ-ΩÕ›ΩRMÌ-‚›-]-Ì¢‡¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&f6W7vˆf∆˜r"í”“&vóE˜F&vWB#†¢vóBˆ÷ñ&Uˆ6Üˆ˜6U˜F&vWEˆf6RáWFFR¬6ˆÁFWáB¬W6W%ˆñB¬ñ÷rê¢&WGW&‡¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&f6W7vˆf∆˜r"í”“&vóE˜6˜W&6R#†¢vóBˆ÷ñ&Uˆ6Üˆ˜6U˜6˜W&6Uˆf6RáWFFR¬6ˆÁFWáB¬W6W%ˆñB¬ñ÷rê¢&WGW&‡¢ñb6Fñˆ‚ÊBˆó5ˆf6U˜7v˜&WVW7BÜ6Fñˆ‚ì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáW6W%ˆñB¬""ê¢vóB˜7F'Eˆf6W7vˆf∆˜ráWFFR¬6ˆÁFWáB¬ñ÷rê¢&WGW&‡†¢2„Rí	=Ì-Ì˝ùçí--ÚMÌ-Ó(i--çM]Ì≠ΩçÚçr˝ÌM˝çÇ¢MÌ-‚‡¢ñb6Fñˆ‚ÊBˆó5ˆfF%ˆñÁFVÁBÜ6Fñˆ‚ì†¢67&óB“ˆ6∆VÂˆfF%˜67&óBÜ6Fñˆ‚ê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ñb67&óBÊB∆V‚á67&óBí‚É†¢6ˆÁFWáBÁW6W%ˆFF≤&fF%˜VÊFñÊu˜67&óB%““67&ó@¢˜6WEˆfF%˜fˆñ6Uˆ6Üˆñ6U˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	˝Ì-]"˝ÌΩ=}]“‚
-]˝]¬-Ω]ç-R=ÌΩÌMΩÚ-]≠-Ì-ÌíÌ}-=}≠ÇçΩÇ˝ççΩç-R-Ìífˆñ6RˆVFñÚ‚"¬&W«ïˆ÷&∑W’ˆfF%˜fˆñ6Uˆ6Üˆñ6Uˆ∂"Ç&7B"íê¢&WGW&‡†¢ñb6Fñˆ‚ÊBˆó5˜Ü˜Fıˆ6∆óˆñÁFVÁBÜ6Fñˆ‚ì†¢&ˆ◊B“ˆ6∆VÂ˜Ü˜Fıˆ6∆ó˜&ˆ◊BÜ6Fñˆ‚ê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ñb&ˆ◊C†¢vóB˜7FvUˆ◊W6ñ5˜fñFVıˆG&gBáWFFR¬6ˆÁFWáB¬&ˆ◊Bê¢V«6S†¢˜6WE˜Ü˜Fıˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	¯ÎR
MÌ-‚˝ÌΩ=}]›‚‚
›}ΩÌ-M]ΩÕ›‚Ì˝ççç-R	˝	]
	›
„¢m›¬›-Ì]›çR¬˝}Ω¢¬-]Õ2-]≠-¬›=m]“ΩÇ-Ì≠≤Ç≠≠ç¬=ÌΩÌÌ¬‚	˝ÌΩR›-Ì=‚ÚÌ-M]ΩÕ›‚˝Ìç2	-	ç	M	]	‚‚"ê¢&WGW&‡†¢ñb6Fñˆ‚ÊBˆó5ˆï˜6V∆fñUˆñÁFVÁBÜ6Fñˆ‚ì†¢&ˆ◊B“ˆ6∆VÂˆï˜6V∆fñU˜&ˆ◊BÜ6Fñˆ‚ê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ñb&ˆ◊C†¢vóB˜7F'Eˆï˜6V∆fñRáWFFR¬6ˆÁFWáB¬ñ÷r¬&ˆ◊Bê¢V«6S†¢˜6WEˆï˜6V∆fñU˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-
]ΩMÇ˝ÌΩ=}]›‚‚
-]˝]¬›˝ççç-R¬≠]¬˝=MRM]Ω-¬í›MÌ-„¢}›Õ]›ç-Ì-¬¬˝]Ì›b¬˝]ÕÕ]¬]≠ΩÕ¬G&fV¬ˆ«WáW'í‚"ê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊuˆï˜6V∆fñU˜Ü˜FÚ"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊuˆï˜6V∆fñU˜Ü˜FÚ"¬ÊˆÊRê¢&W6WB“Ü6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&ï˜6V∆fñU˜&W6WE˜&ˆ◊B"¬""í˜"""íÁ7G&óÇê¢˜6WEˆï˜6V∆fñU˜vóBÜ6ˆÁFWáBê¢ñb&W6WC†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	˙K2
]ΩMÇ˝ÌΩ=}]›‚‚	˝]]"-Ω“‚
-]˝]¬›˝ççç-RçÕÚ}›Õ]›ç-Ì-Ç˝˝]Ì›mÇM]-ΩÇm]›≤‚"ê¢V«6S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	˙K2
]ΩMÇ˝ÌΩ=}]›‚‚
-]˝]¬›˝ççç-R¬≠]¬˝=MRM]Ω-¬í›MÌ-„¢}›Õ]›ç-Ì-¬¬˝]Ì›b¬˝]ÕÕ]¬]≠ΩÕ¬G&fV¬ˆ«WáW'í‚"ê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊuˆfF%˜Ü˜FÚ"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊuˆfF%˜Ü˜FÚ"¬ÊˆÊRê¢2W∆ˆBf∆˜ró2FWFW&÷ñÊó7Fñ3¢ÊWv«íW∆ˆFVB˜'G&óB«vó2GfÊ6W2FÚ7FW"‡¢2FÚÊ˜B6ñ∆VÁF«í6∂ófˆñ6R6V∆V7Fñˆ‚&V6W6R7F∆Rfˆñ6R&V÷ñÊVBg&ˆ“‚V&∆ñW"fF"6W76ñˆ‚‡¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&fF%˜GG5˜fˆñ6R"¬ÊˆÊRê¢˜6WEˆfF%˜fˆñ6Uˆ6Üˆñ6U˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)»R	˝Ì-]"˝ÌΩ=}]“‚
ç2"Û3¢-Ω]ç-R=ÌΩÌMΩÚ-]≠-Ì-ÌíÌ}-=}≠ÇçΩÇ˝ççΩç-R-Ìífˆñ6RˆVFñÚ‚"¿¢&W«ïˆ÷&∑W’ˆfF%˜fˆñ6Uˆ6Üˆñ6Uˆ∂"Ç&7B"í¿¢ê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜fˆ6≈ˆ6∆ó˜Ü˜FÚ"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜fˆ6≈ˆ6∆ó˜Ü˜FÚ"¬ÊˆÊRê¢˜6WE˜fˆ6≈ˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	¯ÍB	˝Ì-]"˝ÌΩ=}]“‚	Ì˝ççç-R˝]›‚¬-Ì≠≤¬M-çm]›çR¬MΩç-]ΩÕ›Ì-¬ÇMÌÕ"(	B˝Ì≠m2m]›çíMΩÚ=--]mM]›çÚ‚ ¢ê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜Ü˜Fıˆ6∆ó˜Ü˜FÚ"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜Ü˜Fıˆ6∆ó˜Ü˜FÚ"¬ÊˆÊRê¢&W6WE˜&ˆ◊B“Ü6ˆÁFWáBÁW6W%ˆFFÁ˜Ç'Ü˜Fıˆ6∆ó˜&W6WE˜&ˆ◊B"¬""í˜"""íÁ7G&óÇê¢ñb&W6WE˜&ˆ◊C†¢vóB˜7FvUˆ◊W6ñ5˜fñFVıˆG&gBáWFFR¬6ˆÁFWáB¬&W6WE˜&ˆ◊Bê¢V«6S†¢˜6WE˜Ü˜Fıˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	¯ÎR
MÌ-‚˝ÌΩ=}]›‚‚
›}ΩÌ-M]ΩÕ›‚Ì˝ççç-R	˝	]
	›
„¢m›¬›-Ì]›çR¬˝}Ω¢¬-]Õ2-]≠-¬›=m]“ΩÇ-Ì≠≤Ç≠≠ç¬=ÌΩÌÌ¬‚	˝ÌΩR›-Ì=‚ÚÌ-M]ΩÕ›‚˝Ìç2	-	ç	M	]	‚‚"ê¢&WGW&‡†¢2í
MÌ-‚˝ççΩ‚˝ÌΩR-]ÌMçrÕ]›‚*Ω
}-Ω]}]›çÚ(i"	}Õ]›ç-¬MÌ‹+≤‡¢2	›R}˝=≠]¬}Õ]›2}2¬˝Ì≠}Ω-]¬-ç›-≤MÌ›‡¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ'Ü˜Fıˆf∆˜r"í”“'&W∆6V&uˆ÷VÁR#†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç'Ü˜Fıˆf∆˜r"¬ÊˆÊRê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	˘k¬
MÌ-‚˝ÌΩ=}]›‚‚	-Ω]ç-R›Ì-ΩíMÌ“çΩÇ›˝ççç-R-Ìí-ç›"-]≠-Ì√¢"¿¢&W«ïˆ÷&∑W÷&6∂w&˜VÊE˜&W6WG5ˆ∂"Çí¿¢ê¢&WGW&‡†¢2í
=MΩ]›çR˝}Õ]›MÌ›MÌΩm›≤˝]]ç--¬Õ]Mçmç›≠çí≠Ì›-]≠"‡¢ñb6Fñˆ‚ÊBˆó5˜&V÷˜fUˆ&u˜&WVW7BÜ6Fñˆ‚ì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%˜&V÷˜fV&u˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáW6W%ˆñB¬""ê¢vóB˜VFóE˜&V÷˜fV&ráWFFR¬6ˆÁFWáB¬ñ÷rê¢&WGW&‡†¢ñbˆó5˜vóFñÊu˜&V÷˜fV&rÜ6ˆÁFWáBì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%˜&V÷˜fV&u˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáW6W%ˆñB¬""ê¢vóB˜VFóE˜&V÷˜fV&ráWFFR¬6ˆÁFWáB¬ñ÷rê¢&WGW&‡†¢ñb6Fñˆ‚ÊBˆó5˜&W∆6Uˆ&u˜&WVW7BÜ6Fñˆ‚ì†¢∂ñÊB¬&ˆ◊B“ˆ&uˆ∂ñÊEˆg&ˆ’˜FWáBÜ6Fñˆ‚ê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%˜&W∆6V&u˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáW6W%ˆñB¬""ê¢vóB˜VFóE˜&W∆6V&ráWFFR¬6ˆÁFWáB¬ñ÷r¬∂ñÊC÷∂ñÊB¬&ˆ◊C◊&ˆ◊Bê¢&WGW&‡†¢ñbˆó5˜vóFñÊu˜&W∆6V&rÜ6ˆÁFWáBì†¢&ˆ◊B“6Fñˆ‚˜"6ˆÁFWáBÁW6W%ˆFFÊvWBÇ'&W∆6V&u˜&ˆ◊B"í˜"-}ÕΩ-ΩíMÌ“ ¢∂ñÊB¬&ˆ◊B“ˆ&uˆ∂ñÊEˆg&ˆ’˜FWáBá&ˆ◊Bê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%˜&W∆6V&u˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáW6W%ˆñB¬""ê¢vóB˜VFóE˜&W∆6V&ráWFFR¬6ˆÁFWáB¬ñ÷r¬∂ñÊC÷∂ñÊB¬&ˆ◊C◊&ˆ◊Bê¢&WGW&‡†¢2í
]-=ç¬Ì--]››Ì=‚ç}Ìm]›çÚÚ=MΩ]›çRΩçç›]í›M˝çÇÚvFW&÷&≤‡¢2
›-‚MÌΩm›‚˝]]ç--¬Õ]Mçmç›≠çí≠Ì›-]≠"¬]ΩÇ˝ÌΩÕ}Ì--]Ω¬˝-›‚˝Ìç"]-=ç¬‡¢ñb6Fñˆ‚ÊBˆó5ˆñ÷vU˜&WF˜V6Ö˜&WVW7BÜ6Fñˆ‚ì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%ˆñ÷vU˜&WF˜V6Ö˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáW6W%ˆñB¬""ê¢vóB˜7F'Eˆñ÷vU˜&WF˜V6ÇáWFFR¬6ˆÁFWáB¬ñ÷r¬6Fñˆ‚ê¢&WGW&‡†¢ñbˆó5˜vóFñÊuˆñ÷vU˜&WF˜V6ÇÜ6ˆÁFWáBì†¢ñÁ7G'V7Fñˆ‚“6ˆÁFWáBÁW6W%ˆFFÊvWBÇ'&WF˜V6Ö˜&ˆ◊B"í˜"6Fñˆ‚˜"-=-¬Ωçç›Ì‚›M˝ç¬˝-ÌM˝›Ìí}›¢ ¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%ˆñ÷vU˜&WF˜V6Ö˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáW6W%ˆñB¬""ê¢vóB˜7F'Eˆñ÷vU˜&WF˜V6ÇáWFFR¬6ˆÁFWáB¬ñ÷r¬ñÁ7G'V7Fñˆ‚ê¢&WGW&‡†¢2í
ÕΩí-ΩÌ≠çí˝çÌç-]#¢˝-›Ú≠ÌÕ›MÌmç-ç-¬˝›çÕçÌ--¬MÌ-‚"˝ÌM˝çÇ‡¢2
›-‚MÌΩm›‚˝]]ç--¬MmR›]RÌ-≠Ω-Ωí}M]≤*Ω	Õ]Mçmç›+≤‡¢ñb6Fñˆ‚ÊBˆó5˜Ü˜Fı˜&Wfóf≈ˆñÁFVÁBÜ6Fñˆ‚ì†¢˜6WE˜vóFñÊu˜Ü˜Fı˜&Wfóf¬áWFFR¬6ˆÁFWáBê¢VÊvñÊR“˜&Wfóf≈ˆVÊvñÊUˆg&ˆ’˜FWáBÜ6Fñˆ‚¬FVfV«C“''VÁví"ê¢&ˆ◊B“ˆ6∆VÂ˜&Wfóf≈˜&ˆ◊BÜ6Fñˆ‚ê¢ˆ6∆V%˜Ü˜Fı˜&Wfóf≈˜vóBÜ6ˆÁFWáBê¢vóB˜7F'E˜Ü˜Fı˜&Wfóf¬áWFFR¬6ˆÁFWáB¬VÊvñÊS÷VÊvñÊR¬ñ÷uˆ'óFW3÷ñ÷r¬&ˆ◊C◊&ˆ◊Bê¢&WGW&‡†¢2"í	]ΩÇ˝]]BMÌ-‚˝ÌΩÕ}Ì--]Ω¬=ÌΩÌÌ¬˝-]≠-Ì¬˝Ìç≤˝‚Ìmç-Ω]›çRMÌ-‚(	@¢2˝Ì≠}Ω-]¬MÌ-‚›Õ-]≠=‚¬›RÕ]Mçmç›≠çí›Ωçr‡¢ñbˆó5˜vóFñÊu˜Ü˜Fı˜&Wfóf¬Ü6ˆÁFWáBì†¢ˆ6∆V%˜Ü˜Fı˜&Wfóf≈˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢-
MÌ-‚˝ÌΩ=}]›‚‚	-Ω]ç-Rm]›çíÌmç-Ω]›çÛ¢"¿¢&W«ïˆ÷&∑W◊Ü˜Fı˜&Wfóf≈ˆ7FñˆÁ5ˆ∂"Çí¿¢ê¢&WGW&‡†¢22í	Õ]Mçmç›≠Ú-]-≠(	B-ÌΩÕ≠‚˝-›ΩíÕ]B‚˝ÌM]mç¬˝ÌmçM›çRçΩÇÕ]B‚ΩÌ-"˝ÌM˝çÇ‡¢ñb˜6Ü˜V∆E˜&˜WFUˆ÷VFñ6¬Ü6ˆÁFWáB¬W6W%ˆñB¬6Fñˆ‚¬'Ü˜FÚ"ì†¢vóBˆ÷VFñ6≈ˆÊ«ó¶Uˆñ÷vRáWFFR¬6ˆÁFWáB¬ñ÷r¬vˆ√÷6Fñˆ‚˜"ÊˆÊRê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáW6W%ˆñB¬""ê¢&WGW&‡†¢ñb6Fñˆ„†¢F¬“6Fñˆ‚Ê∆˜vW"Çê¢2Ìmç-ç-¬MÌ-‚(i"-Ω››ΩíM-çmÌ¢çr˝ÌM˝çÇçΩÇ'VÁví˝‚=ÕÌΩ}›ç‡¢ñbÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-Ìmç-Ç"¬-Ìmç-ç-¬"¬-›çÕç2"¬-›çÕçÌ--¬"¬-M]Ωí-çM]‚"¬'&WfófR"¬&Êñ÷FR"¬&ñ÷vRFÚfñFVÚ"¬&ì'b"íì†¢VÊvñÊR“˜&Wfóf≈ˆVÊvñÊUˆg&ˆ’˜FWáBÜ6Fñˆ‚¬FVfV«C“''VÁví"ê¢&ˆ◊B“ˆ6∆VÂ˜&Wfóf≈˜&ˆ◊BÜ6Fñˆ‚ê¢vóB˜7F'E˜Ü˜Fı˜&Wfóf¬áWFFR¬6ˆÁFWáB¬VÊvñÊS÷VÊvñÊR¬ñ÷uˆ'óFW3÷ñ÷r¬&ˆ◊C◊&ˆ◊Bê¢&WGW&‡†¢2]-=ç¬Ú=-¬-ÌM˝›Ìí}›¢ÚΩçç›Ì‚›M˝ç¿¢ñbˆó5ˆñ÷vU˜&WF˜V6Ö˜&WVW7BÜ6Fñˆ‚ì†¢vóB˜7F'Eˆñ÷vU˜&WF˜V6ÇáWFFR¬6ˆÁFWáB¬ñ÷r¬6Fñˆ‚ì≤&WGW&‡†¢2=MΩç-¬MÌ–¢ñbÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-=MΩÇMÌ“"¬'&V÷˜fV&r"¬-=-¬MÌ“"íì†¢vóB˜VFóE˜&V÷˜fV&ráWFFR¬6ˆÁFWáB¬ñ÷rì≤&WGW&‡†¢2}Õ]›ç-¬MÌ–¢ñbÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-}Õ]›ÇMÌ“"¬'&W∆6V&r"¬-}ÕΩ-ΩíMÌ“"¬&&«W""íì†¢∂ñÊB¬&ˆ◊B“ˆ&uˆ∂ñÊEˆg&ˆ’˜FWáBÜ6Fñˆ‚ê¢vóB˜VFóE˜&W∆6V&ráWFFR¬6ˆÁFWáB¬ñ÷r¬∂ñÊC÷∂ñÊB¬&ˆ◊C◊&ˆ◊Bì≤&WGW&‡†¢2˜WGñÁ@¢ñb&˜WGñÁB"ñ‚F¬˜"-çç"ñ‚F√†¢vóB˜VFóEˆ˜WGñÁBáWFFR¬6ˆÁFWáB¬ñ÷rì≤&WGW&‡†¢2≠MÌ-≠ ¢ñb-≠MÌ""ñ‚F¬˜"'7F˜'ñ&ˆ&B"ñ‚F√†¢vóB˜VFóE˜7F˜'ñ&ˆ&BáWFFR¬6ˆÁFWáB¬ñ÷rì≤&WGW&‡†¢2≠-ç›≠˝‚Ì˝ç›ç‚Ñ«V÷ÚMÌΩ›¢˜V‰íê¢ñbÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-≠-ç“"¬-ç}Ìm]“"¬&ñ÷vR"¬&ñ÷r"ííÊBÁíÜ≤ñ‚F¬f˜"≤ñ‚Ç-=]›]ç2"¬-Ì}M"¬-M]Ωí"íì†¢vóB˜7F'Eˆ«V÷ˆñ÷ráWFFR¬6ˆÁFWáB¬6Fñˆ‚ì≤&WGW&‡†¢2]ΩÇ˝-›Ìí≠ÌÕ›M≤"˝ÌM˝çÇ›]"(	B˝Ì≠}Ω-]¬Ω-ΩR≠›Ì˝≠Ä¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-
MÌ-‚˝ÌΩ=}]›‚‚
}-‚M]Ω-√Ú"¿¢&W«ïˆ÷&∑W◊Ü˜Fı˜Vñ6µˆ7FñˆÁ5ˆ∂"Çíê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç&ˆÂ˜Ü˜FÚW'&˜#¢W2"¬Rê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬
MÌ-‚›R˝Ì}››‚¬˝Ì˝Ì=ù-R]ùr‚"ê†¶7ñÊ2FVbˆÂˆFˆ2áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢G'ì†¢ñbÊ˜BWFFRÊ÷W76vR˜"Ê˜BWFFRÊ÷W76vRÊFˆ7V÷VÁC†¢&WGW&‡¢Fˆ2“WFFRÊ÷W76vRÊFˆ7V÷VÁ@¢◊B“ÜFˆ2Ê÷ñ÷U˜GóR˜"""íÊ∆˜vW"Çê¢Fuˆfñ∆R“vóBFˆ2ÊvWEˆfñ∆RÇê¢FF“vóBFuˆfñ∆RÊF˜vÊ∆ˆEˆ5ˆ'óFV'&íÇê¢&r“'óFW2ÜFFê†¢6Fñˆ‚“áWFFRÊ÷W76vRÊ6Fñˆ‚˜"""íÁ7G&óÇê†¢2&W6VÁFFñˆ‚7GVFñÚ66WG2ñ÷vRFˆ7V÷VÁG2ÊB§ï&6ÜófW2vóFÇ÷ÁíÜ˜F˜2‡¢ñbvóB˜&W6VÁFFñˆÂ˜7GVFñıˆvWBÇíÊÜÊF∆UˆFˆ7V÷VÁBÄ¢WFFR¬6ˆÁFWáB¬&r¬Fˆ2Êfñ∆UˆÊ÷R˜"&fñ∆R"¬◊B¬6Fñˆ„÷6Fñˆ‡¢ì†¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊuˆfF%˜67&óB"íÊBÜ◊BÁ7F'G7vóFÇÇ&VFñÚÚ"í˜"ÜFˆ2Êfñ∆UˆÊ÷R˜"""íÊ∆˜vW"ÇíÊVÊG7vóFÇÇÇ"Ê◊2"¬"Ávb"¬"Ê”F"¬"Ê2"¬"Êˆvr"ííì†¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñBê¢ñbÊ˜Bñ÷s†¢ˆ6∆V%ˆfF%˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-
›}Ω}==}ç-R˝Ì-]"}]ΩÌ-]≠¬}-]¬›mÕç-R	˘z2	=Ì-Ì˝ùçí--‚"ê¢&WGW&‡¢ˆ6∆V%ˆfF%˜vóBÜ6ˆÁFWáBê¢vóB˜7F'E˜F∆∂ñÊuˆfF"Ä¢WFFR¬6ˆÁFWáB¬ñ÷r¿¢67&óE˜FWáC÷6Fñˆ‚ñb6Fñˆ‚ÊBÊ˜Bˆó5ˆfF%ˆñÁFVÁBÜ6Fñˆ‚íV«6Rˆ6∆VÂˆfF%˜67&óBÜ6Fñˆ‚í¿¢VFñıˆ'óFW3◊&r¿¢VFñıˆfñ∆VÊ÷S÷Fˆ2Êfñ∆UˆÊ÷R˜"&VFñÚ"¿¢VFñıˆfñ∆U˜W&√÷vWFGG"áFuˆfñ∆R¬&fñ∆U˜FÇ"¬""í˜"""¿¢VFñıˆ÷ñ÷S÷◊B¿¢ê¢&WGW&‡†¢ñb◊BÁ7F'G7vóFÇÇ&ñ÷vRÚ"ì†¢ˆ66ÜU˜Ü˜FÚáWFFRÊVffV7FófU˜W6W"ÊñB¬&r¬vWFGG"áFuˆfñ∆R¬&fñ∆U˜FÇ"¬""í˜"""ê†¢ñb6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&◊W6ñ5˜fñFVıˆG&gB"¬ÊˆÊRì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&◊W6ñ5˜fñFVıˆG&gEˆVFóB"¬ÊˆÊRê¢˜6WE˜Ü˜Fıˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	˘;Ç
MÌ-‚MΩÚ≠Ωç˝Ì›Ì-Ω]›‚‚	Ì˝ççç-Rm]›çí]ùr¬}-Ì≤=--]Mç-¬]=‚MΩÚ›-Ì=‚MÌ-‚‚ ¢ê¢&WGW&‡†¢2cs¢]ΩÇ˝ÌΩÕ}Ì--]Ω¬=mR-Ω≤]mç¬*Ω	≠ΩçÚ-Ì≠ΩÌÃ+≤¿¢2Ω]M=ÌùÚMÌ-Ì=MçÚMÌΩm›˝ÌMÌΩm-¬›-Ì"m]›çí¬›RÌ-≠Ω--¿¢2Ìù]RÕ]›‚*Ω
MÌ-‚˝ÌΩ=}]›‚‚
}-‚M]Ω-√¸+≤‚
›-‚-]=]"Ω=}Ç¿¢2≠Ì=MFV∆Vw&“˝≠Ωç]›"˝Ì-]˝≤G&Á6ñVÁBf∆r¬›‚÷ˆFU˜G&6≤Ì]›çΩÚ‡¢G'ì†¢˜G&6µˆÊ˜r“ˆ÷ˆFU˜G&6µˆvWBáWFFRÊVffV7FófU˜W6W"ÊñBê¢WÜ6WBWÜ6WFñˆ„†¢˜G&6µˆÊ˜r“" ¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜fˆ6≈ˆ6∆ó˜Ü˜FÚ"í˜"˜G&6µˆÊ˜r”“'fˆ6∆6∆ó#†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜fˆ6≈ˆ6∆ó˜Ü˜FÚ"¬ÊˆÊRê¢˜6WEˆ÷ˆFUˆ6∆V‚áWFFRÊVffV7FófU˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬'fˆ6∆6∆ó"ê¢˜6WE˜fˆ6≈ˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	¯ÎR	˝Ì-]"˝ÌΩ=}]“‚
›}ΩÌ-M]ΩÕ›‚Ì˝ççç-R	˝	]
	›
„¢m›¬›-Ì]›çR¬˝}Ω¢¬-]Õ2-]≠-¬-Ì≠≤Çm]Ω]Õ=‚MΩç-]ΩÕ›Ì-¬Â∆Â∆‚ ¢-
Ω]M=Ìùç¬ÌÌù]›ç]¬ÚÌ-M]ΩÕ›‚˝Ìç2m]›çí-çM]‚‚ ¢ê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&f6W7vˆf∆˜r"í”“&vóE˜F&vWB#†¢vóBˆ÷ñ&Uˆ6Üˆ˜6U˜F&vWEˆf6RáWFFR¬6ˆÁFWáB¬WFFRÊVffV7FófU˜W6W"ÊñB¬&rê¢&WGW&‡¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&f6W7vˆf∆˜r"í”“&vóE˜6˜W&6R#†¢vóBˆ÷ñ&Uˆ6Üˆ˜6U˜6˜W&6Uˆf6RáWFFR¬6ˆÁFWáB¬WFFRÊVffV7FófU˜W6W"ÊñB¬&rê¢&WGW&‡¢ñb6Fñˆ‚ÊBˆó5ˆf6U˜7v˜&WVW7BÜ6Fñˆ‚ì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢vóB˜7F'Eˆf6W7vˆf∆˜ráWFFR¬6ˆÁFWáB¬&rê¢&WGW&‡†¢ñb6Fñˆ‚ÊBˆó5ˆfF%ˆñÁFVÁBÜ6Fñˆ‚ì†¢67&óB“ˆ6∆VÂˆfF%˜67&óBÜ6Fñˆ‚ê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ñb67&óBÊB∆V‚á67&óBí‚É†¢6ˆÁFWáBÁW6W%ˆFF≤&fF%˜VÊFñÊu˜67&óB%““67&ó@¢˜6WEˆfF%˜fˆñ6Uˆ6Üˆñ6U˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	˝Ì-]"˝ÌΩ=}]“‚
-]˝]¬-Ω]ç-R=ÌΩÌMΩÚ-]≠-Ì-ÌíÌ}-=}≠ÇçΩÇ˝ççΩç-R-Ìífˆñ6RˆVFñÚ‚"¬&W«ïˆ÷&∑W’ˆfF%˜fˆñ6Uˆ6Üˆñ6Uˆ∂"Ç&7B"íê¢&WGW&‡†¢ñb6Fñˆ‚ÊBˆó5˜Ü˜Fıˆ6∆óˆñÁFVÁBÜ6Fñˆ‚ì†¢&ˆ◊B“ˆ6∆VÂ˜Ü˜Fıˆ6∆ó˜&ˆ◊BÜ6Fñˆ‚ê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ñb&ˆ◊C†¢vóB˜7FvUˆ◊W6ñ5˜fñFVıˆG&gBáWFFR¬6ˆÁFWáB¬&ˆ◊Bê¢V«6S†¢˜6WE˜Ü˜Fıˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	¯ÎR
MÌ-‚˝ÌΩ=}]›‚‚
›}ΩÌ-M]ΩÕ›‚Ì˝ççç-R	˝	]
	›
„¢m›¬›-Ì]›çR¬˝}Ω¢¬-]Õ2-]≠-¬›=m]“ΩÇ-Ì≠≤Ç≠≠ç¬=ÌΩÌÌ¬‚	˝ÌΩR›-Ì=‚ÚÌ-M]ΩÕ›‚˝Ìç2	-	ç	M	]	‚‚"ê¢&WGW&‡†¢ñb6Fñˆ‚ÊBˆó5ˆï˜6V∆fñUˆñÁFVÁBÜ6Fñˆ‚ì†¢&ˆ◊B“ˆ6∆VÂˆï˜6V∆fñU˜&ˆ◊BÜ6Fñˆ‚ê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ñb&ˆ◊C†¢vóB˜7F'Eˆï˜6V∆fñRáWFFR¬6ˆÁFWáB¬&r¬&ˆ◊Bê¢V«6S†¢˜6WEˆï˜6V∆fñU˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-
]ΩMÇ˝ÌΩ=}]›‚‚
-]˝]¬›˝ççç-R¬≠]¬˝=MRM]Ω-¬í›MÌ-„¢}›Õ]›ç-Ì-¬¬˝]Ì›b¬˝]ÕÕ]¬]≠ΩÕ¬G&fV¬ˆ«WáW'í‚"ê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊuˆï˜6V∆fñU˜Ü˜FÚ"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊuˆï˜6V∆fñU˜Ü˜FÚ"¬ÊˆÊRê¢&W6WB“Ü6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&ï˜6V∆fñU˜&W6WE˜&ˆ◊B"¬""í˜"""íÁ7G&óÇê¢˜6WEˆï˜6V∆fñU˜vóBÜ6ˆÁFWáBê¢ñb&W6WC†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	˙K2
]ΩMÇ˝ÌΩ=}]›‚‚	˝]]"-Ω“‚
-]˝]¬›˝ççç-RçÕÚ}›Õ]›ç-Ì-Ç˝˝]Ì›mÇM]-ΩÇm]›≤‚"ê¢V«6S†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	˙K2
]ΩMÇ˝ÌΩ=}]›‚‚
-]˝]¬›˝ççç-R¬≠]¬˝=MRM]Ω-¬í›MÌ-„¢}›Õ]›ç-Ì-¬¬˝]Ì›b¬˝]ÕÕ]¬]≠ΩÕ¬G&fV¬ˆ«WáW'í‚"ê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜fˆ6≈ˆ6∆ó˜Ü˜FÚ"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜fˆ6≈ˆ6∆ó˜Ü˜FÚ"¬ÊˆÊRê¢˜6WE˜fˆ6≈ˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	¯ÍB	˝Ì-]"˝ÌΩ=}]“‚
-]˝]¬Ì˝ççç-R˝]›‚˝≠ΩçÛ¢-çΩ¬¬˝}Ω¢¬›-Ì]›çR¬˝ç˝]"¬MΩç-]ΩÕ›Ì-¬Â∆Â∆Ì	-m›„¢]mç¬}ç-“›ÌM›Ì=‚}]ΩÌ-]≠"≠MR‚ ¢ê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊuˆfF%˜Ü˜FÚ"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊuˆfF%˜Ü˜FÚ"¬ÊˆÊRê¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&fF%˜GG5˜fˆñ6R"¬ÊˆÊRê¢˜6WEˆfF%˜fˆñ6Uˆ6Üˆñ6U˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)»R	˝Ì-]"˝ÌΩ=}]“‚
ç2"Û3¢-Ω]ç-R=ÌΩÌMΩÚ-]≠-Ì-ÌíÌ}-=}≠ÇçΩÇ˝ççΩç-R-Ìífˆñ6RˆVFñÚ‚"¿¢&W«ïˆ÷&∑W’ˆfF%˜fˆñ6Uˆ6Üˆñ6Uˆ∂"Ç&7B"í¿¢ê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜Ü˜Fıˆ6∆ó˜Ü˜FÚ"ì†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊu˜Ü˜Fıˆ6∆ó˜Ü˜FÚ"¬ÊˆÊRê¢&W6WE˜&ˆ◊B“Ü6ˆÁFWáBÁW6W%ˆFFÁ˜Ç'Ü˜Fıˆ6∆ó˜&W6WE˜&ˆ◊B"¬""í˜"""íÁ7G&óÇê¢ñb&W6WE˜&ˆ◊C†¢vóB˜7FvUˆ◊W6ñ5˜fñFVıˆG&gBáWFFR¬6ˆÁFWáB¬&W6WE˜&ˆ◊Bê¢V«6S†¢˜6WE˜Ü˜Fıˆ6∆ó˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	¯ÎR
MÌ-‚˝ÌΩ=}]›‚‚
›}ΩÌ-M]ΩÕ›‚Ì˝ççç-R	˝	]
	›
„¢m›¬›-Ì]›çR¬˝}Ω¢¬-]Õ2-]≠-¬›=m]“ΩÇ-Ì≠≤Ç≠≠ç¬=ÌΩÌÌ¬‚	˝ÌΩR›-Ì=‚ÚÌ-M]ΩÕ›‚˝Ìç2	-	ç	M	]	‚‚"ê¢&WGW&‡†¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ'Ü˜Fıˆf∆˜r"í”“'&W∆6V&uˆ÷VÁR#†¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç'Ü˜Fıˆf∆˜r"¬ÊˆÊRê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢/	˘k¬	ç}Ìm]›çR˝ÌΩ=}]›‚‚	-Ω]ç-R›Ì-ΩíMÌ“‚	}Õ]›-Ω˝ÌΩ›˝]-Ú""›-˝¢-Ω]}‚}]ΩÌ-]≠¬}-]¬˝ÌM--Ω˝‚›Ì-ΩíMÌ“]r˝]]çÌ-≠ÇΩçmÇÌM]mM≤‚"¿¢&W«ïˆ÷&∑W÷&6∂w&˜VÊE˜&W6WG5ˆ∂"Çí¿¢ê¢&WGW&‡†¢ñb6Fñˆ‚ÊBˆó5˜&V÷˜fUˆ&u˜&WVW7BÜ6Fñˆ‚ì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%˜&V÷˜fV&u˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢vóB˜VFóE˜&V÷˜fV&ráWFFR¬6ˆÁFWáB¬&rê¢&WGW&‡†¢ñbˆó5˜vóFñÊu˜&V÷˜fV&rÜ6ˆÁFWáBì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%˜&V÷˜fV&u˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢vóB˜VFóE˜&V÷˜fV&ráWFFR¬6ˆÁFWáB¬&rê¢&WGW&‡†¢ñb6Fñˆ‚ÊBˆó5˜&W∆6Uˆ&u˜&WVW7BÜ6Fñˆ‚ì†¢∂ñÊB¬&ˆ◊B“ˆ&uˆ∂ñÊEˆg&ˆ’˜FWáBÜ6Fñˆ‚ê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%˜&W∆6V&u˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢vóB˜VFóE˜&W∆6V&ráWFFR¬6ˆÁFWáB¬&r¬∂ñÊC÷∂ñÊB¬&ˆ◊C◊&ˆ◊Bê¢&WGW&‡†¢ñbˆó5˜vóFñÊu˜&W∆6V&rÜ6ˆÁFWáBì†¢&ˆ◊B“6Fñˆ‚˜"6ˆÁFWáBÁW6W%ˆFFÊvWBÇ'&W∆6V&u˜&ˆ◊B"í˜"-}ÕΩ-ΩíMÌ“ ¢∂ñÊB¬&ˆ◊B“ˆ&uˆ∂ñÊEˆg&ˆ’˜FWáBá&ˆ◊Bê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%˜&W∆6V&u˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢vóB˜VFóE˜&W∆6V&ráWFFR¬6ˆÁFWáB¬&r¬∂ñÊC÷∂ñÊB¬&ˆ◊C◊&ˆ◊Bê¢&WGW&‡†¢ñb6Fñˆ‚ÊBˆó5ˆñ÷vU˜&WF˜V6Ö˜&WVW7BÜ6Fñˆ‚ì†¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%ˆñ÷vU˜&WF˜V6Ö˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢vóB˜7F'Eˆñ÷vU˜&WF˜V6ÇáWFFR¬6ˆÁFWáB¬&r¬6Fñˆ‚ê¢&WGW&‡†¢ñbˆó5˜vóFñÊuˆñ÷vU˜&WF˜V6ÇÜ6ˆÁFWáBì†¢ñÁ7G'V7Fñˆ‚“6ˆÁFWáBÁW6W%ˆFFÊvWBÇ'&WF˜V6Ö˜&ˆ◊B"í˜"6Fñˆ‚˜"-=-¬Ωçç›Ì‚›M˝ç¬˝-ÌM˝›Ìí}›¢ ¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢ˆ6∆V%ˆñ÷vU˜&WF˜V6Ö˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢vóB˜7F'Eˆñ÷vU˜&WF˜V6ÇáWFFR¬6ˆÁFWáB¬&r¬ñÁ7G'V7Fñˆ‚ê¢&WGW&‡†¢ñb6Fñˆ‚ÊBˆó5˜Ü˜Fı˜&Wfóf≈ˆñÁFVÁBÜ6Fñˆ‚ì†¢˜6WE˜vóFñÊu˜Ü˜Fı˜&Wfóf¬áWFFR¬6ˆÁFWáBê¢VÊvñÊR“˜&Wfóf≈ˆVÊvñÊUˆg&ˆ’˜FWáBÜ6Fñˆ‚¬FVfV«C“''VÁví"ê¢&ˆ◊B“ˆ6∆VÂ˜&Wfóf≈˜&ˆ◊BÜ6Fñˆ‚ê¢ˆ6∆V%˜Ü˜Fı˜&Wfóf≈˜vóBÜ6ˆÁFWáBê¢vóB˜7F'E˜Ü˜Fı˜&Wfóf¬áWFFR¬6ˆÁFWáB¬VÊvñÊS÷VÊvñÊR¬ñ÷uˆ'óFW3◊&r¬&ˆ◊C◊&ˆ◊Bê¢&WGW&‡†¢ñbˆó5˜vóFñÊu˜Ü˜Fı˜&Wfóf¬Ü6ˆÁFWáBì†¢ˆ6∆V%˜Ü˜Fı˜&Wfóf≈˜vóBÜ6ˆÁFWáBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	ç}Ìm]›çR˝ÌΩ=}]›‚≠¢MÌ≠=Õ]›"‚	-Ω]ç-RMÌ-=˝›ΩíM-çmÌ¢MΩÚÌmç-Ω]›çÛ¢"¬&W«ïˆ÷&∑W◊Ü˜Fı˜Vñ6µˆ7FñˆÁ5ˆ∂"Çíê¢&WGW&‡†¢ñb˜6Ü˜V∆E˜&˜WFUˆ÷VFñ6¬Ü6ˆÁFWáB¬WFFRÊVffV7FófU˜W6W"ÊñB¬6Fñˆ‚¬Fˆ2Êfñ∆UˆÊ÷R˜"&ñ÷vR"ì†¢vóBˆ÷VFñ6≈ˆÊ«ó¶Uˆñ÷vRáWFFR¬6ˆÁFWáB¬&r¬vˆ√÷6Fñˆ‚˜"ÊˆÊRê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢&WGW&‡¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	ç}Ìm]›çR˝ÌΩ=}]›‚≠¢MÌ≠=Õ]›"‚
}-‚M]Ω-√Ú"¬&W«ïˆ÷&∑W◊Ü˜Fı˜Vñ6µˆ7FñˆÁ5ˆ∂"Çíê¢&WGW&‡†¢FWáB¬∂ñÊB“WáG&7E˜FWáEˆg&ˆ’ˆFˆ7V÷VÁBá&r¬Fˆ2Êfñ∆UˆÊ÷R˜"&fñ∆R"ê¢ñbÊ˜BáFWáB˜"""íÁ7G&óÇì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb-	›R=MΩÌ¬ç}-Ω]}¬-]≠"çr∂∂ñÊG“‚"ê¢&WGW&‡†¢2FWáBFˆ7V÷VÁB6‚6W'fR2FÜR'&ñVb˜"&Wfó6ñˆ‚f˜"‚7FófR&W6VÁFFñˆ‚&ˆ¶V7B‡¢ñbvóB˜&W6VÁFFñˆÂ˜7GVFñıˆvWBÇíÊÜÊF∆U˜FWáBáWFFR¬6ˆÁFWáB¬FWáBì†¢&WGW&‡†¢vˆ¬“áWFFRÊ÷W76vRÊ6Fñˆ‚˜"""íÁ7G&óÇí˜"ÊˆÊP¢ñb˜6Ü˜V∆E˜&˜WFUˆ÷VFñ6¬Ü6ˆÁFWáB¬WFFRÊVffV7FófU˜W6W"ÊñB¬6Fñˆ‚¬Fˆ2Êfñ∆UˆÊ÷R˜"&fñ∆R"ì†¢vóBˆ÷VFñ6≈ˆÊ«ó¶U˜FWáBáWFFR¬6ˆÁFWáB¬FWáB¬vˆ√÷vˆ¬ê¢ˆ6∆V%ˆ÷VFñ6ñÊU˜vóBÜ6ˆÁFWáBê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ÷ˆFU˜G&6µ˜6WBáWFFRÊVffV7FófU˜W6W"ÊñB¬""ê¢&WGW&‡†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜb/	˘8B	ç}-Ω]≠‚-]≠"á∂∂ñÊG“í¬=Ì-Ì-Ω‚≠Ì›˝]≠.(
b"ê¢7V÷÷'í“vóB7V÷÷&ó¶Uˆ∆ˆÊu˜FWáBáFWáB¬VW'ì÷vˆ¬ê¢7V÷÷'í“7V÷÷'í˜"-	=Ì-Ì-‚‚ ¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBá7V÷÷'íê¢vóB÷ñ&U˜GG5˜&W«íáWFFR¬6ˆÁFWáB¬7V÷÷'ï≥•EE5Ù‘ÖÙ4Ñ%5“ê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç&ˆÂˆFˆ2W'&˜#¢W2"¬Rê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ.)ÿ¬
MÌ-‚˝MÌ≠=Õ]›"›R˝Ì}›“¬˝Ì˝Ì=ù-R]ùr‚"ê†¶7ñÊ2FVbˆÂ˜fˆñ6RáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢G'ì†¢ñbÊ˜BWFFRÊ÷W76vR˜"Ê˜BWFFRÊ÷W76vRÁfˆñ6S†¢&WGW&‡¢fb“vóBWFFRÊ÷W76vRÁfˆñ6RÊvWEˆfñ∆RÇê¢&ñÚ“'óFW4îÚÜvóBfbÊF˜vÊ∆ˆEˆ5ˆ'óFV'&íÇíê¢&ñÚÁ6VV≤Éê¢6WFGG"Ü&ñÚ¬&Ê÷R"¬b'fˆñ6RÊˆvr"ê¢vóB6ˆÁFWáBÊ&˜BÁ6VÊEˆ6ÜEˆ7Fñˆ‚áWFFRÊVffV7FófUˆ6ÜBÊñB¬6ÜD7Fñˆ‚ÂEïî‰rê¢FWáB“vóBG&Á67&ñ&UˆVFñÚÜ&ñÚ¬'fˆñ6RÊˆvr"ê¢ñbÊ˜BFWáC†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›R=MΩÌ¬˝Ì}›-¬]}¬‚"ê¢&WGW&‡¢vóBˆÂ˜FWáBáWFFR¬6ˆÁFWáB¬÷ÁV≈˜FWáC◊FWáBê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç&ˆÂ˜fˆñ6RW'&˜#¢W2"¬Rê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	Ìçç≠˝ÇÌÌ-≠Rfˆñ6R‚"ê†¶7ñÊ2FVbˆÂˆVFñÚáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢G'ì†¢ñbÊ˜BWFFRÊ÷W76vR˜"Ê˜BWFFRÊ÷W76vRÊVFñÛ†¢&WGW&‡¢b“vóBWFFRÊ÷W76vRÊVFñÚÊvWEˆfñ∆RÇê¢fñ∆VÊ÷R“WFFRÊ÷W76vRÊVFñÚÊfñ∆UˆÊ÷R˜"&VFñÚÊ◊2 ¢&ñÚ“'óFW4îÚÜvóBbÊF˜vÊ∆ˆEˆ5ˆ'óFV'&íÇíê¢&ñÚÁ6VV≤Éê¢6WFGG"Ü&ñÚ¬&Ê÷R"¬fñ∆VÊ÷Rê¢vóB6ˆÁFWáBÊ&˜BÁ6VÊEˆ6ÜEˆ7Fñˆ‚áWFFRÊVffV7FófUˆ6ÜBÊñB¬6ÜD7Fñˆ‚ÂEïî‰rê¢FWáB“vóBG&Á67&ñ&UˆVFñÚÜ&ñÚ¬fñ∆VÊ÷Rê¢ñbÊ˜BFWáC†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	›R=MΩÌ¬˝Ì}›-¬]}¬çr=Mç‚‚"ê¢&WGW&‡¢vóBˆÂ˜FWáBáWFFR¬6ˆÁFWáB¬÷ÁV≈˜FWáC◊FWáBê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÊWÜ6WFñˆ‚Ç&ˆÂˆVFñÚW'&˜#¢W2"¬Rê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-	Ìçç≠˝ÇÌÌ-≠R=Mç‚‚"ê††¢2)H)H)H)H)H)H)H)H)H	ÌÌ-}ç¢ÌççÌ¢D")H)H)H)H)H)H)H)H)H ¶7ñÊ2FVbˆÂˆW'&˜"áWFFS¢ˆ&¶V7B¬6ˆÁFWáEÛ¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢∆ˆrÊWÜ6WFñˆ‚Ç%VÊÜÊF∆VBW'&˜#¢W2"¬6ˆÁFWáEÚÊW'&˜"ê¢G'ì†¢ñbó6ñÁ7FÊ6RáWFFR¬WFFRì†¢6%ˆFF“ÜvWFGG"ÜvWFGG"áWFFR¬&6∆∆&6µ˜VW'í"¬ÊˆÊRí¬&FF"¬""í˜"""íÁ7G&óÇê¢&W6VÁFFñˆÂˆ7FófR“&ˆˆ¬ÜvWFGG"Ü6ˆÁFWáEÚ¬'W6W%ˆFF"¬∑“íÊvWBÇ'&W6VÁFFñˆÂ˜7GVFñıˆ7FófR"íê¢2FÜR&W6VÁFFñˆ‚vó¶&BÜÊF∆W2ÊB&W˜'G2óG2˜v‚W'&˜'2gFW"6fñÊr7FFR‡¢27W&W72FÜR÷ó6∆VFñÊr6V6ˆÊB÷W76vR*Ω
=˝¬˝Ìç}ÌçΩÌçç≠+≤‡¢ñb6%ˆFFÁ7F'G7vóFÇÇ'3¢"í˜"&W6VÁFFñˆÂˆ7FófS†¢&WGW&‡¢ñbWFFRÊVffV7FófUˆ÷W76vS†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ-
=˝¬˝Ìç}ÌçΩÌçç≠‚
Ú=mR}çÌ¬‚"ê¢WÜ6WBWÜ6WFñˆ„†¢70††¢2)H)H)H)H)H)H)H)H)H
Ì=-]≤MΩÚ-]≠-Ì-ΩR≠›Ì˝Ì¢˝]mçÕÌ")H)H)H)H)H)H)H)H)H ¶7ñÊ2FVbˆÂˆ'FÂˆVÊvñÊW2áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢&WGW&‚vóB6÷EˆVÊvñÊW2áWFFR¬6ˆÁFWáBê†¶7ñÊ2FVbˆÂˆ'FÂˆ&∆Ê6RáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢&WGW&‚vóB6÷Eˆ&∆Ê6RáWFFR¬6ˆÁFWáBê†¶7ñÊ2FVbˆÂˆ'FÂ˜∆Á2áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢W6W%ˆñB“WFFRÊVffV7FófU˜W6W"Êñ@¢FWáB“˜∆Á5ˆ˜fW'fñWu˜FWáBáW6W%ˆñBê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBáFWáB¬&W«ïˆ÷&∑W◊∆Á5˜&ˆ˜Eˆ∂"Çíê†¶7ñÊ2FVbˆÂˆ÷ˆFU˜66Üˆˆ≈˜FWáBáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢GáB“Ä¢/	¯È2≠
=}•∆‚ ¢-	˝ÌÕÌ=3¢≠Ì›˝]≠-≤çrDbÙUT"ÙDÙ5ÇıEÖB¬}Ì}Mr˝Ìç=Ì-‚¬›R˝]M]-≤¬Õç›Ç›≠-ç}≤Â∆Â∆‚ ¢%˝	Ω-ΩRM]ù--çÛ•ı∆‚ ¢.(
"
}Ì-¬Db(i"≠Ì›˝]≠%∆‚ ¢.(
"
Ì≠-ç-¬"ç˝=Ω≠5∆‚ ¢.(
"	Ì≠˝›ç-¬-]Õ2˝çÕ]ÕÖ∆‚ ¢.(
"	˝Ω“Ì--]-Ú˝]}]›-mçÇ ¢ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBáGáB¬'6Uˆ÷ˆFS“$÷&∂F˜v‚"ê†¶7ñÊ2FVbˆÂˆ÷ˆFU˜v˜&µ˜FWáBáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢GáB“Ä¢/	˘+¬≠
Ì-˝	ç}›]•∆‚ ¢-	˝çÕÕ¬	≠	Ú¬MÌ=Ì-Ì›ΩR}]›Ì-ç≠Ç¬›Ωç-ç≠¬˝Ω›≤¬çM≤¬˝]}]›-mçÇ¬Db›≠-ΩÌ=Ç¬ΩÌ=Ì-ç˝≤Ç]-=ç¬ç}›]›MÌ-‚Â∆Â∆‚ ¢%˝	Ω-ΩRM]ù--çÛ•ı∆‚ ¢.(
"	˘8B	˝çÕÕ‚ÚMÌ≠=Õ]›%∆‚ ¢.(
"	˘8¢
Ì}M-¬˝]}]›-mçÂ∆‚ ¢.(
"	˘9R
Ì}M-¬Db›≠-ΩÌ5∆‚ ¢.(
"	¯ÍÇ
Ì}M-¬ΩÌ=Ì-çı∆‚ ¢.(
"	˙{“
=MΩç-¬-ÌM˝›Ìí}›¢Ú›M˝ç¬MÌ-‚ ¢ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBáGáB¬'6Uˆ÷ˆFS“$÷&∂F˜v‚"¬&W«ïˆ÷&∑W’ˆ÷ˆFUˆ∂"Ç'v˜&≤"íê†¶7ñÊ2FVbˆÂˆ÷ˆFUˆgVÂ˜FWáBáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢GáB“Ä¢/	˘JR≠
}-Ω]}]›çÚ•∆‚ ¢-	}M]¬Ω-ΩR--Ì}]≠çRm]›çÉ¢Ìmç-ç-¬MÌ-Ì=Mç‚¬M]Ω-¬=Ì-Ì˝ùçí--¬Ì}M-¬MÌ-Ó(i--çM]Ì≠ΩçÚÕ=}Ω≠Ìí¬≠ΩçÚ-Ì≠ΩÌ¬MΩÚ}]ΩÌ-]≠¬-çM]‚˝‚-]≠-2˝=ÌΩÌ2¬ ¢-}Õ]›ç-¬Ωçm‚¬=MΩç-¬çΩÇ}Õ]›ç-¬MÌ“¬M]Ω-¬&VV«2ı6Ü˜'G2¬Ì}M-¬Õç›Ç›MçΩÕ¬¬˝çM=Õ-¬çM]Ç¬m]›çí¬ç=2çΩÇ≠-çrÂ∆Â∆‚ ¢-	-Ω]ÇM]ù--çR›çmRçΩÇ›˝ççÇ-ÌÌM›Ωí}˝Ì‚ ¢ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBáGáB¬'6Uˆ÷ˆFS“$÷&∂F˜v‚"¬&W«ïˆ÷&∑W’ˆgVÂ˜Vñ6µˆ∂"Çíê†¢2)H)H)H)H)H	≠Ω-ç-=*Ω
}-Ω]}]›ç¸+≤›Ì-ΩÕÇ≠›Ì˝≠ÕÇ)H)H)H)H)H ¶FVbˆgVÂ˜Vñ6µˆ∂"Çí”‚ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑W†¢&˜w2“∞¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˙®B	Ìmç-ç-¬MÌ-‚"¬6∆∆&6µˆFF“&gV„ß&WfófR"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˘z2	=Ì-Ì˝ùçí--"¬6∆∆&6µˆFF“&gV„¶fF""ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	¯ÍBí›-çM]Ì≠ΩçÚÚ˝]›Ú"¬6∆∆&6µˆFF“&gV„ßÜ˜Fˆ6∆ó"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	¯Í¬	-çM]‚˝‚-]≠-2˝=ÌΩÌ2"¬6∆∆&6µˆFF“&gV„ßFWáGfñFVÚ"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˙K2í›]ΩMÇ‚}-]}MÌí"¬6∆∆&6µˆFF“&gV„¶ó6V∆fñR"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	¯Í“	}Õ]›Ωçm›MÌ-‚"¬6∆∆&6µˆFF“&gV„¶f6W7v"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˙{¬
=MΩç-¬MÌ“›MÌ-‚"¬6∆∆&6µˆFF“&gV„ß&V÷˜fV&r"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˘k¬	}Õ]›ç-¬MÌ“›MÌ-‚"¬6∆∆&6µˆFF“&gV„ß&W∆6V&r"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˘;&VV«2Ú6Ü˜'G2"¬6∆∆&6µˆFF“&gV„ß&VV«2"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	¯È‚
Ì}M-¬Õç›Ç›MçΩÕ¬"¬6∆∆&6µˆFF“&gV„¶fñ∆“"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	¯Í¬
m]›çíÚ≠M≤"¬6∆∆&6µˆFF“&gV„ß7F˜'ñ&ˆ&B"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	¯ÎR	Õ=}Ω≠Ú˝]›Ú"¬6∆∆&6µˆFF“&gV„¶◊W6ñ2"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	¯Í‚	ç=≤Ú≠-çr"¬6∆∆&6µˆFF“&gV„ßVó¢"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	¯Í“	çM]ÇMΩÚMÌ=="¬6∆∆&6µˆFF“&gV„¶ñFV2"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç/	˘9“
-ÌÌM›Ωí}˝Ì"¬6∆∆&6µˆFF“&gV„¶g&VR"ï“¿¢¥ñÊ∆ñÊT∂Wñ&ˆ&D'WGFˆ‚Ç.*»^˚àÚ	›}B"¬6∆∆&6µˆFF“&gV„¶&6≤"ï“¿¢–¢&WGW&‚ñÊ∆ñÊT∂Wñ&ˆ&D÷&∑Wá&˜w2ê†¢2)H)H)H)H)H	ÌÌ-}ç¢Ω-ΩRM]ù--çí*Ω
}-Ω]}]›ç¸+≤Üf∆∆&6≤÷g&ñVÊF«íí)H)H)H)H)H ¶7ñÊ2FVbˆÂˆ6%ˆgV‚áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢“WFFRÊ6∆∆&6µ˜VW'ê¢FF“áÊFF˜"""íÁ7G&óÇê¢7Fñˆ‚“FFÁ7∆óBÇ#¢"¬ï≥“ñb#¢"ñ‚FFV«6R" †¢7ñÊ2FVb˜G'ïˆ6∆¬Ç¶fÂˆÊ÷W2¬¢¶∑v&w2ì†¢f‚“˜ñ6µˆfó'7EˆFVfñÊVBÇ¶fÂˆÊ÷W2ê¢ñb6∆∆&∆RÜf‚ì†¢&WGW&‚vóBf‚áWFFR¬6ˆÁFWáB¬¢¶∑v&w2ê¢&WGW&‚ÊˆÊP†¢ñb7Fñˆ‚”“&fF"#†¢vóBÊÁ7vW"Ç-	=Ì-Ì˝ùçí--"ê¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áÊg&ˆ’˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬&fF""ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÖˆfF%ˆ÷VÁU˜FWáBÇí¬'6Uˆ÷ˆFS“$÷&∂F˜v‚"¬&W«ïˆ÷&∑W’ˆfF%ˆ7FñˆÂˆ∂"Ç&gV‚"íê¢&WGW&‡†¢ñb7Fñˆ‚Á7F'G7vóFÇÇ&e˜fˆñ6UÚ"ì†¢fˆñ6R“7Fñˆ‚Á'7∆óBÇ%Ú"¬ï≤”“Á7G&óÇê¢6ˆÁFWáBÁW6W%ˆFF≤&fF%˜GG5˜fˆñ6R%““fˆñ6P¢6ˆÁFWáBÁW6W%ˆFFÁ˜Ç&vóFñÊuˆfF%˜fˆñ6Uˆ6Üˆñ6R"¬ÊˆÊRê¢ñbˆvWEˆ66ÜVE˜Ü˜FÚáÊg&ˆ’˜W6W"ÊñBì†¢˜6WEˆfF%˜vóBÜ6ˆÁFWáBê¢vóBÊÁ7vW"Üb-	=ÌΩÌ¢∑fˆñ6W“"ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÜb.)»R	MΩÚ---Ω“=ÌΩÌ¢µˆfF%˜GG5˜fˆñ6Uˆ∆&V¬áfˆñ6Ró“‚
ç22Û3¢˝ççΩç-R-]≠"¬≠Ì-ÌΩíMÌΩm]“˝Ìç}›]-Ç--‚"ê¢V«6S†¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊuˆfF%˜Ü˜FÚ%““G'VP¢vóBÊÁ7vW"Üb-	=ÌΩÌ¢∑fˆñ6W“"ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÜb.)»R	=ÌΩÌ-Ω”¢µˆfF%˜GG5˜fˆñ6Uˆ∆&V¬áfˆñ6Ró“‚
-]˝]¬˝ççΩç-R˝Ì-]"}]ΩÌ-]≠‚"ê¢&WGW&‡†¢ñb7Fñˆ‚”“&fF%˜W∆ˆB#†¢vóBÊÁ7vW"Ç-	}==}ç-R˝Ì-]""ê¢vóBˆÜÊF∆UˆfF%˜W∆ˆEˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬&VfóÉ“&gV‚"ê¢&WGW&‡†¢ñb7Fñˆ‚ñ‚≤&fF%ˆ∆7B"¬&fF%˜FWáB'”†¢vóBˆÜÊF∆UˆfF%˜67&óEˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬&VfóÉ“&gV‚"¬fˆñ6Uˆ÷ˆFS‘f«6Rê¢&WGW&‡†¢ñb7Fñˆ‚”“&fF%˜fˆñ6R#†¢vóBˆÜÊF∆UˆfF%˜67&óEˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬&VfóÉ“&gV‚"¬fˆñ6Uˆ÷ˆFS’G'VRê¢&WGW&‡†¢ñb7Fñˆ‚”“'fˆ6∆6∆ó#†¢vóBÊÁ7vW"Ç-	≠ΩçÚ-Ì≠ΩÌ¬"ê¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áÊg&ˆ’˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬'fˆ6∆6∆ó"ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÖ˜fˆ6≈ˆ6∆óˆ÷VÁU˜FWáBÇí¬'6Uˆ÷ˆFS“$÷&∂F˜v‚"¬&W«ïˆ÷&∑W’˜fˆ6≈ˆ6∆óˆ7FñˆÂˆ∂"Ç&gV‚"íê¢&WGW&‡†¢ñb7Fñˆ‚”“'fˆ6∆6∆ó˜W∆ˆB#†¢vóBÊÁ7vW"Ç-	}==}ç-R˝Ì-]""ê¢vóBˆÜÊF∆U˜fˆ6∆6∆ó˜W∆ˆEˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬&VfóÉ“&gV‚"ê¢&WGW&‡†¢ñb7Fñˆ‚ñ‚≤'fˆ6∆6∆óˆ∆7B"¬'fˆ6∆6∆ó˜&ˆ◊B'”†¢vóBˆÜÊF∆U˜fˆ6∆6∆ó˜&ˆ◊Eˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬&VfóÉ“&gV‚"ê¢&WGW&‡†¢ñb7Fñˆ‚”“'FWáGfñFVÚ#†¢vóBÊÁ7vW"Ç-	-çM]‚˝‚-]≠-2˝=ÌΩÌ2"ê¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áÊg&ˆ’˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬'FWáGfñFVÚ"ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÖ˜FWáGfñFVıˆ÷VÁU˜FWáBÇí¬'6Uˆ÷ˆFS“$÷&∂F˜v‚"¬&W«ïˆ÷&∑W’˜FWáGfñFVıˆ7FñˆÂˆ∂"Ç&gV‚"íê¢&WGW&‡†¢ñb7Fñˆ‚”“'GeˆVÊvñÊU˜6˜&#†¢vóBˆÜÊF∆U˜FWáGfñFVıˆVÊvñÊUˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬'6˜&"¬&VfóÉ“&gV‚"ê¢&WGW&‡†¢ñb7Fñˆ‚”“'GeˆVÊvñÊUˆ∂∆ñÊr#†¢vóBˆÜÊF∆U˜FWáGfñFVıˆVÊvñÊUˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬&∂∆ñÊr"¬&VfóÉ“&gV‚"ê¢&WGW&‡†¢ñb7Fñˆ‚”“'GeˆVÊvñÊU˜'VÁví#†¢vóBˆÜÊF∆U˜FWáGfñFVıˆVÊvñÊUˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬''VÁví"¬&VfóÉ“&gV‚"ê¢&WGW&‡†¢ñb7Fñˆ‚”“'Ge˜&ˆ◊B#†¢vóBˆÜÊF∆U˜FWáGfñFVı˜&ˆ◊Eˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬&VfóÉ“&gV‚"ê¢&WGW&‡†¢ñb7Fñˆ‚”“'Ü˜Fˆ6∆ó#†¢vóBÊÁ7vW"Ç-
MÌ-‚(i"-çM]Ì≠ΩçÚ"ê¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áÊg&ˆ’˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬'Ü˜Fˆ6∆ó"ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÖ˜Ü˜Fˆ6∆óˆ÷VÁU˜FWáBÇí¬'6Uˆ÷ˆFS“$÷&∂F˜v‚"¬&W«ïˆ÷&∑W’˜Ü˜Fˆ6∆óˆ7FñˆÂˆ∂"Ç&gV‚"íê¢&WGW&‡†¢ñb7Fñˆ‚”“'Ü˜Fˆ6∆ó˜W∆ˆB#†¢vóBÊÁ7vW"Ç-	}==}ç-RMÌ-‚"ê¢vóBˆÜÊF∆U˜Ü˜Fˆ6∆ó˜W∆ˆEˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬&VfóÉ“&gV‚"ê¢&WGW&‡†¢ñb7Fñˆ‚”“'Ü˜Fˆ6∆óˆ∆7B#†¢vóBˆÜÊF∆U˜Ü˜Fˆ6∆ó˜&ˆ◊Eˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬&VfóÉ“&gV‚"ê¢&WGW&‡†¢ñb7Fñˆ‚”“'Ü˜Fˆ6∆óˆ7W7Fˆ“#†¢ñbˆ◊W6ñ5˜fñFVıˆñFVÁFóGïˆ6ˆ◊∆WFRáÊg&ˆ’˜W6W"ÊñBì†¢vóBˆÜÊF∆U˜Ü˜Fˆ6∆ó˜&ˆ◊Eˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬&VfóÉ“&gV‚"ê¢V«6S†¢vóBÊÁ7vW"Ç-
›}ΩÌ]¬6Ü&7FW"ñFVÁFóGí6≤"ê¢vóBˆÜÊF∆U˜Ü˜Fˆ6∆ó˜W∆ˆEˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬&VfóÉ“&gV‚"ê¢&WGW&‡†¢ñb7Fñˆ‚Á7F'G7vóFÇÇ'5˜&W6WEÚ"ì†¢∂ñÊB“7Fñˆ‚Á'7∆óBÇ%Ú"¬ï≤”–¢vóBˆÜÊF∆U˜Ü˜Fˆ6∆ó˜&W6WEˆ6Üˆñ6RáWFFR¬6ˆÁFWáB¬¬∂ñÊB¬&VfóÉ“&gV‚"ê¢&WGW&‡†¢ñb7Fñˆ‚”“&f6W7v#†¢vóBÊÁ7vW"Ç-	}Õ]›Ωçm"ê¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áÊg&ˆ’˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬&f6W7v"ê¢vóB˜7F'Eˆf6W7vˆf∆˜ráWFFR¬6ˆÁFWáB¬ÊˆÊR¬W6Uˆ66ÜVC‘f«6Rê¢&WGW&‡†¢ñb7Fñˆ‚”“'&V÷˜fV&r#†¢vóBÊÁ7vW"Ç-
=MΩ]›çRMÌ›"ê¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áÊg&ˆ’˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬'&V÷˜fV&r"ê¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáÊg&ˆ’˜W6W"ÊñBê¢ñbñ÷s†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ/	˙{¬	ç˝ÌΩÕ}=‚˝ÌΩ]M›]R}==m]››ÌRMÌ-‚Ç=MΩ˝‚MÌ“‚"ê¢vóB˜VFóE˜&V÷˜fV&ráWFFR¬6ˆÁFWáB¬ñ÷rê¢V«6S†¢˜6WE˜vóFñÊu˜&V÷˜fV&rÜ6ˆÁFWáBê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ/	˙{¬	˝ççΩç-RMÌ-‚(	B=MΩ‚MÌ“Ç-]›2‰r˝Ì}}›Ìí˝ÌMΩÌm≠Ìí‚"¬&W«ïˆ÷&∑W’ˆgVÂ˜Vñ6µˆ∂"Çíê¢&WGW&‡†¢ñb7Fñˆ‚”“'&W∆6V&r#†¢vóBÊÁ7vW"Ç-	}Õ]›MÌ›"ê¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áÊg&ˆ’˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬'&W∆6V&r"ê¢ñ÷r“ˆvWEˆ66ÜVE˜Ü˜FÚáÊg&ˆ’˜W6W"ÊñBê¢ñbñ÷s†¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ/	˘k¬	-Ω]ç-R›Ì-ΩíMÌ“MΩÚ˝ÌΩ]M›]=‚}==m]››Ì=‚MÌ-„¢"¬&W«ïˆ÷&∑W÷&6∂w&˜VÊE˜&W6WG5ˆ∂"Çíê¢V«6S†¢6ˆÁFWáBÁW6W%ˆFF≤'Ü˜Fıˆf∆˜r%““'&W∆6V&uˆ÷VÁR ¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ/	˘k¬	˝ççΩç-RMÌ-‚‚	˝ÌΩR}==}≠ÇÚ˝Ì≠m2-ç›-≤MÌ›¢˝Ω˝b¬=Ì≤¬˝çÌM¬=ÌÌBçΩÇ-Ìí-]≠"‚"¬&W«ïˆ÷&∑W’ˆgVÂ˜Vñ6µˆ∂"Çíê¢&WGW&‡†¢ñb7Fñˆ‚”“'&WfófR#†¢ñbvóB˜G'ïˆ6∆¬Ç'&WfófUˆˆ∆E˜Ü˜Fıˆf∆˜r"¬&Fı˜&WfófU˜Ü˜FÚ"ì†¢&WGW&‡¢˜6WE˜vóFñÊu˜Ü˜Fı˜&Wfóf¬áWFFR¬6ˆÁFWáBê¢vóBÊÁ7vW"Ç-	Ìmç-Ω]›çRMÌ-‚"ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÖˆgVÂ˜&WfófUˆÜV«˜FWáBÇí¬'6Uˆ÷ˆFS“$÷&∂F˜v‚"¬&W«ïˆ÷&∑W’ˆgVÂ˜Vñ6µˆ∂"Çíê¢&WGW&‡†¢ñb7Fñˆ‚ñ‚≤'6÷'G&VV«2"¬'&VV«2'”†¢ñbvóB˜G'ïˆ6∆¬Ç'6÷'E˜&VV«5ˆg&ˆ’˜fñFVÚ"¬'fñFVı˜6VÁ6U˜&VV«2"ì†¢&WGW&‡¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áÊg&ˆ’˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬&gVÂ˜&VV«2"ê¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊu˜&VV«5ˆ÷FW&ñ¬%““G'VP¢vóBÊÁ7vW"Ç%&VV«2Ú6Ü˜'G2"ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÖˆgVÂ˜&VV«5ˆÜV«˜FWáBÇí¬'6Uˆ÷ˆFS“$÷&∂F˜v‚"¬&W«ïˆ÷&∑W’ˆgVÂ˜Vñ6µˆ∂"Çíê¢&WGW&‡†¢ñb7Fñˆ‚”“&fñ∆“#†¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áÊg&ˆ’˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬&gVÂˆfñ∆“"ê¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊuˆfñ∆’ˆ÷FW&ñ¬%““G'VP¢vóBÊÁ7vW"Ç-
Ì}M-¬MçΩÕ¬"ê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÖˆgVÂˆfñ∆’ˆÜV«˜FWáBÇí¬'6Uˆ÷ˆFS“$÷&∂F˜v‚"¬&W«ïˆ÷&∑W’ˆgVÂ˜Vñ6µˆ∂"Çíê¢&WGW&‡†¢ñb7Fñˆ‚”“&6∆ó#†¢ñbvóB˜G'ïˆ6∆¬Ç'7F'E˜'VÁvïˆf∆˜r"¬&«V÷ˆ÷∂Uˆ6∆ó"¬''VÁvïˆ÷∂Uˆ6∆ó"ì†¢&WGW&‡¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áÊg&ˆ’˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬&gVÂ˜&VV«2"ê¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊu˜&VV«5ˆ÷FW&ñ¬%““G'VP¢vóBÊÁ7vW"Çê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÖˆgVÂ˜&VV«5ˆÜV«˜FWáBÇí¬'6Uˆ÷ˆFS“$÷&∂F˜v‚"¬&W«ïˆ÷&∑W’ˆgVÂ˜Vñ6µˆ∂"Çíê¢&WGW&‡†¢ñb7Fñˆ‚”“&ñ÷r#†¢ñbvóB˜G'ïˆ6∆¬Ç&6÷Eˆñ÷r"¬&÷ñF¶˜W&ÊWïˆf∆˜r"¬&ñ÷vW5ˆ÷∂R"ì†¢&WGW&‡¢vóBÊÁ7vW"Çê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	--]MÇˆñ÷rÇ-]Õ2≠-ç›≠Ç¬çΩÇ˝ççΩÇ]M≤‚"¬&W«ïˆ÷&∑W’ˆgVÂ˜Vñ6µˆ∂"Çíê¢&WGW&‡†¢ñb7Fñˆ‚”“'7F˜'ñ&ˆ&B#†¢ñbvóB˜G'ïˆ6∆¬Ç'7F'E˜7F˜'ñ&ˆ&B"¬'7F˜'ñ&ˆ&Eˆ÷∂R"ì†¢&WGW&‡¢vóBÊÁ7vW"Çê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÇ-	›˝ççÇ-]Õ2çÌ-(	B›≠çM‚-=≠-=2Ç≠MÌ-≠2‚"¬&W«ïˆ÷&∑W’ˆgVÂ˜Vñ6µˆ∂"Çíê¢&WGW&‡†¢ñb7Fñˆ‚”“&◊W6ñ2#†¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áÊg&ˆ’˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬'7VÊıˆ◊W6ñ2"ê¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊu˜7VÊıˆ'&ñVb%““G'VP¢vóBÊÁ7vW"Ç-	Õ=}Ω≠Ú7VÊÚ"ê¢vóB˜6Ü˜u˜7VÊıˆÜV«ˆg&ˆ’ˆ6∆∆&6≤á¬6ˆÁFWáB¬&W«ïˆ÷&∑W’˜7VÊıˆ÷VÁUˆ∂"Çí¬7V&÷VÁS’G'VRê¢&WGW&‡†¢ñb7Fñˆ‚ñ‚≤&ñFV2"¬'Vó¢"¬'7VV6Ç"¬&g&VR"¬&&6≤'”†¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢vóBÊÁ7vW"Çê¢vóBÊ÷W76vRÁ&W«ï˜FWáBÄ¢-	=Ì-Ì"	›˝ççÇ}M}2çΩÇ-Ω]Ç≠›Ì˝≠2-ΩçR‚"¿¢&W«ïˆ÷&∑W’ˆgVÂ˜Vñ6µˆ∂"Çê¢ê¢&WGW&‡†¢vóBÊÁ7vW"Çê†¢2)H)H)H)H)H)H)H)H)H
Ì=-]≤›≠›Ì˝≠Ç]mçÕÌ"ç]Mç›Ú-Ì}≠-]ÌMí)H)H)H)H)H)H)H)H)H ¶7ñÊ2FVbˆÂˆ'FÂ˜7GVGíáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áWFFRÊVffV7FófU˜W6W"ÊñB¬-
=}"¬""ê¢f‚“v∆ˆ&«2ÇíÊvWBÇ%˜6VÊEˆ÷ˆFUˆ÷VÁR"ê¢ñb6∆∆&∆RÜf‚ì†¢&WGW&‚vóBf‚áWFFR¬6ˆÁFWáB¬'7GVGí"ê¢&WGW&‚vóBˆÂˆ÷ˆFU˜66Üˆˆ≈˜FWáBáWFFR¬6ˆÁFWáBê†¶7ñÊ2FVbˆÂˆ'FÂ˜v˜&≤áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áWFFRÊVffV7FófU˜W6W"ÊñB¬-
Ì-˝	ç}›]"¬""ê¢f‚“v∆ˆ&«2ÇíÊvWBÇ%˜6VÊEˆ÷ˆFUˆ÷VÁR"ê¢ñb6∆∆&∆RÜf‚ì†¢&WGW&‚vóBf‚áWFFR¬6ˆÁFWáB¬'v˜&≤"ê¢&WGW&‚vóBˆÂˆ÷ˆFU˜v˜&µ˜FWáBáWFFR¬6ˆÁFWáBê†¶7ñÊ2FVbˆÂˆ'FÂˆgV‚áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢ˆ6∆V%˜G&Á6ñVÁEˆf∆˜w2Ü6ˆÁFWáBê¢˜6WEˆ÷ˆFUˆ6∆V‚áWFFRÊVffV7FófU˜W6W"ÊñB¬-
}-Ω]}]›çÚ"¬""ê¢f‚“v∆ˆ&«2ÇíÊvWBÇ%˜6VÊEˆ÷ˆFUˆ÷VÁR"ê¢ñb6∆∆&∆RÜf‚ì†¢&WGW&‚vóBf‚áWFFR¬6ˆÁFWáB¬&gV‚"ê¢&WGW&‚vóBˆÂˆ÷ˆFUˆgVÂ˜FWáBáWFFR¬6ˆÁFWáBê†¶7ñÊ2FVbˆÂˆ'FÂˆ÷VFñ6ñÊRáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢˜6WEˆ÷VFñ6≈˜vóFñÊráWFFR¬6ˆÁFWáB¬""ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÖˆ÷VFñ6≈ˆ÷VÁU˜FWáBÇí¬&W«ïˆ÷&∑W÷÷VFñ6ñÊUˆ∂"Çíê†¢2)H)H)H)H)H)H)H)H)H	˝çÌç-]-›ΩíÌ=-]í›-çM]Ì≠Ωç˝)H)H)H)H)H)H)H)H)H ¶FVbˆ◊W6ñ5˜fñFVı˜FWáE˜7FFRÜ6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïR¬W6W%ˆñC¢ñÁB¬ÊˆÊR“ÊˆÊRí”‚7G#†¢""-	≠-ç-›Ωí›-ÚÑıDÚ”‚4Ù‰r”‚dîDTÚ‚	Ì“-]=M-ΩçRvVÊW&ñ2÷VFñˆ6&ñ∆óGíñÁFVÁG2‚"" ¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊuˆ◊W6ñ5˜fñFVı˜fñFVıˆ'&ñVb"ì†¢&WGW&‚'fñFVÚ ¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜Ü˜Fıˆ6∆ó˜&ˆ◊B"í˜"6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&vóFñÊu˜fˆ6≈ˆ6∆ó˜&ˆ◊B"ì†¢&WGW&‚&◊W6ñ2 ¢ñb6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&◊W6ñ5˜fñFVıˆG&gEˆVFóB"ì†¢&WGW&‚&G&gEˆVFóB ¢ñbW6W%ˆñC†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢G&6≤“Öˆ÷ˆFU˜G&6µˆvWBáW6W%ˆñBí˜"""íÁ7G&óÇíÊ∆˜vW"Çê¢ñbG&6≤”“&◊W6ñ7fñFVÛßfñFVÚ#†¢&WGW&‚'fñFVÚ ¢ñbG&6≤”“&◊W6ñ7fñFVÛ¶◊W6ñ2#†¢&WGW&‚&◊W6ñ2 ¢&WGW&‚" ††¶7ñÊ2FVbˆÂˆ◊W6ñ5˜fñFVı˜FWáE˜&ñ˜&óGíáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢""-	]Mç›--]››Ωí-ΩM]Ω]b-]≠-¬˝Ì≠≠-ç-]“Õ-]í›-çM]Ì≠Ωç˝‚"" ¢VñB“WFFRÊVffV7FófU˜W6W"ÊñBñbWFFRÊVffV7FófU˜W6W"V«6R ¢7FvR“ˆ◊W6ñ5˜fñFVı˜FWáE˜7FFRÜ6ˆÁFWáB¬VñBê¢ñbÊ˜B7FvS†¢&WGW&‡†¢ñbVñBÊBÊ˜BˆvWEˆ66ÜVE˜Ü˜FÚáVñBì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢.)™˚àÚ
]mç¬í›-çM]Ì≠Ωç˝≠-ç-]“¬›‚ç]ÌM›ÌRMÌ-‚˝Ì-]˝›‚‚	˝ççΩç-R-‚mRMÌ-‚Ç›}›ç-R≠ΩçÚ›Ì-‚ ¢ê¢&ó6R∆ñ6Fñˆ‰ÜÊF∆W%7F˜ †¢2dîDTıÙ%$îTb6ˆÁ7V÷W2ÜW&RÊBÊWfW"&R÷VÁFW'2vVÊW&ñ2ˆÂ˜FWáBñÁFVÁB&˜WFñÊr‡¢ñb7FvR”“'fñFVÚ#†¢◊W6ñ5ˆ'&ñVb“Ü6ˆÁFWáBÁW6W%ˆFFÊvWBÇ&◊W6ñ5˜fñFVıˆ◊W6ñ5ˆ'&ñVb"í˜"""íÁ7G&óÇê¢ñbÊ˜B◊W6ñ5ˆ'&ñVbÊBVñC†¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢◊W6ñ5ˆ'&ñVb“Ü∑eˆvWBÜb&◊W6ñ5˜fñFVıˆ◊W6ñ5ˆ'&ñVcß∑VñG“"¬""í˜"""íÁ7G&óÇê¢ñbÊ˜B◊W6ñ5ˆ'&ñVc†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢-
}]›Ì-ç¢≠Ωç˝˝Ì-]˝≤Ì˝ç›çR˝]›Ç‚	›}›ç-R]mç¬í›-çM]Ì≠Ωç˝]ùr‚ ¢ê¢&ó6R∆ñ6Fñˆ‰ÜÊF∆W%7F˜ ¢6ˆÁFWáBÁW6W%ˆFF≤&◊W6ñ5˜fñFVıˆ◊W6ñ5ˆ'&ñVb%““◊W6ñ5ˆ'&ñV`¢6ˆÁFWáBÁW6W%ˆFF≤&vóFñÊuˆ◊W6ñ5˜fñFVı˜fñFVıˆ'&ñVb%““G'VP¢fñFVıˆ'&ñVb“ÜvWFGG"áWFFRÊVffV7FófUˆ÷W76vR¬'FWáB"¬""í˜"""íÁ7G&óÇê¢vóB˜7FvUˆ◊W6ñ5˜fñFVıˆG&gBÄ¢WFFR¬6ˆÁFWáB¬◊W6ñ5ˆ'&ñVc÷◊W6ñ5ˆ'&ñVb¬fñFVıˆ'&ñVc◊fñFVıˆ'&ñV`¢ê¢&ó6R∆ñ6Fñˆ‰ÜÊF∆W%7F˜ †¢vóBˆÂ˜FWáBáWFFR¬6ˆÁFWáBê¢&ó6R∆ñ6Fñˆ‰ÜÊF∆W%7F˜ †¢2)H)H)H)H)H)H)H)H)H	˝Ì}ç-ç-›Ωí--‚›Ì--]"˝‚-Ì}ÕÌm›Ì-Çç-]≠"˝=ÌΩÌí)H)H)H)H)H)H)H)H)H •Ù45ıEDU$‚“&RÊ6ˆ◊ñ∆RÄ¢""ç=Õ]]ç«ÕÕÌm]ç«ÕM]Ω]ç«Õ›Ωç}ç=]ç«ÕÌ-]ç«Õ˝ÌMM]mç-]ç«Õ=Õ]]%«2ΩΩáÕÕÌm]%«2ΩΩáÕÕÌm›Â«2ΩΩÇí ¢""Á≥√c“ ¢""áFg∆WV'∆f#'∆Fˆ7á«GáGÕ≠›ç7Õ≠›ç=Õç}Ìm]◊ÕMÌ-ÁÕMÌ-Ì=GÕ≠-ç◊ÕÌmç'Õ›çÕç¬ ¢"&ñ÷vW∆ßVw«Êw«fñFV˜Õ-çM]Á∆◊G∆÷˜gÕ=MçÁ∆VFñ˜∆◊7«vg¬ ¢"-Õ]Mçmç◊ÕÕ]M≠'Õ-Ω˝çßÕ›Õ›]wÕ›ΩçwÕ›çÕÌßÕÕ'Õ≠'Õ}≠ΩÌ}]›áÕ-}]◊ÕMç=›ÌwÕ=}áÕ]›-=]◊ÕΩçmÁÕΩçmÕΩçg∆f6W7v∆f6U«2ß7vÕÕ=}ΩßÕ˝]◊Õ-]ß«7VÊÚí"¿¢&R‰í¬&RÂ2¿¢ê†¶7ñÊ2FVbˆÂˆ6&ñ∆óFñW5˜áWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢ñÊ6ˆ÷ñÊu˜FWáB“ÜvWFGG"áWFFRÊVffV7FófUˆ÷W76vR¬'FWáB"¬""í˜"""íÁ7G&óÇê¢27FFVgV¬◊W6ñ2◊fñFVÚ&ˆ◊G2ÜfR&ñ˜&óGí˜fW"FÜRvVÊW&ñ26&ñ∆óGí÷F6ÜW"‡¢2ñ‚'Fñ7V∆"¬v˜&G27V6Ç2-MÌ-Ì]Ωç}¬"≤-M-çm]›çR"ñÁ6ñFRdîDTıÙ%$îT`¢2◊W7BÊWfW"&W6WBFÜRf∆˜rFÚ˜&FñÊ'íÜ˜FÚ&Wfóf¬‡¢ñbÁíÜ6ˆÁFWáBÁW6W%ˆFFÊvWBÜ∂Wííf˜"∂Wíñ‚Ä¢&vóFñÊu˜Ü˜Fıˆ6∆ó˜&ˆ◊B"¿¢&vóFñÊu˜fˆ6≈ˆ6∆ó˜&ˆ◊B"¿¢&vóFñÊuˆ◊W6ñ5˜fñFVı˜fñFVıˆ'&ñVb"¿¢&◊W6ñ5˜fñFVıˆG&gEˆVFóB"¿¢íì†¢2FÜó2ÜÊF∆W"'VÁ2ñ‚‚V&∆ñW"D"w&˜WFÜ‚FÜRvVÊW&¬FWáBÜÊF∆W"‡¢2Fó7F6ÇFÜR7FófR7FFVgV¬f∆˜rÜW&RÊB7F˜&˜vFñˆ‚6Ú÷F6ÜñÊp¢26&ñ∆óGíá&6R6‚ÊWfW"Á7vW"ñÁ7FVBˆb6ˆÁ7V÷ñÊr4Ù‰rıdîDTÚñÁWB‡¢vóBˆÂ˜FWáBáWFFR¬6ˆÁFWáBê¢&ó6R∆ñ6Fñˆ‰ÜÊF∆W%7F˜ ¢2ÊWfW"ñÁFW'&WB&W6VÁFFñˆ‚'&ñVb2vVÊW&ñ26&ñ∆óGíˆ∆ófR÷FFVW7Fñˆ‚‡¢7GVFñÚ“˜&W6VÁFFñˆÂ˜7GVFñıˆvWBÇê¢ñbWFFRÊVffV7FófU˜W6W"ÊBWFFRÊVffV7FófUˆ6ÜBÊB7GVFñÚÂˆ7FófU˜&ˆ¶V7BáWFFRÊVffV7FófU˜W6W"ÊñB¬WFFRÊVffV7FófUˆ6ÜBÊñBì†¢ñbvóB7GVFñÚÊÜÊF∆U˜FWáBáWFFR¬6ˆÁFWáB¬ñÊ6ˆ÷ñÊu˜FWáBì†¢&ó6R∆ñ6Fñˆ‰ÜÊF∆W%7F˜ ¢&WGW&‡¢ñbˆó5˜Ü˜Fı˜&Wfóf≈˜VW7Fñˆ‚ÜñÊ6ˆ÷ñÊu˜FWáBí˜"ˆó5˜Ü˜Fı˜&Wfóf≈ˆñÁFVÁBÜñÊ6ˆ÷ñÊu˜FWáBì†¢˜6WE˜vóFñÊu˜Ü˜Fı˜&Wfóf¬áWFFR¬6ˆÁFWáBê¢6“6&ñ∆óGïˆÁ7vW"ÜñÊ6ˆ÷ñÊu˜FWáBê¢ñb6†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜ6¬&W«ïˆ÷&∑W÷÷ñÂˆ∂"ê¢&WGW&‡†¢◊6r“Ä¢-	M¬=Õ]‚Ì--¬MùΩÕÇ¬Õ]MçÇÕ]Mçmç›≠çÕÇÕ-]çΩÕÉ•∆‚ ¢.(
"	˘8B	MÌ≠=Õ]›-≥¢DbÙUT"Ùd#"ÙDÙ5ÇıEÖB(	B≠Ì›˝]≠"¬]}ÌÕR¬ç}-Ω]}]›çR-Ωçb¬˝Ì-]≠M≠-Ì"Â∆‚ ¢.(
"	˘k¬	ç}Ìm]›çÛ¢›Ωçr˝Ì˝ç›çR¬=MΩ]›çRÇ}Õ]›MÌ›¬}Õ]›Ωçm¬]-=ç¬¬˜WGñÁBÂ∆‚ ¢.(
") Ç	Ìmç-Ω]›çRMÌ-„¢}==}ÇMÌ-‚(	BÕÌm›‚-Ω-¬'VÁví¬∂∆ñÊrçΩÇ6˜&"-ÌΩÕ≠‚MΩÚ≠MÌ"]rΩÌM]íÂ∆‚ ¢.(
"	¯È‚	-çM]„¢}ÌÕΩΩ¬-ùÕ≠ÌM≤¬•&VV«2çrMΩç››Ì=‚-çM]‚¢¬çM]Ç˝≠ç˝"¬=-ç-≤Â∆‚ ¢.(
"	¯Ír	=Mç‚˝≠›ç=É¢-›≠ç˝mçÚ¬-]}ç≤¬˝Ω“Â∆‚ ¢.(
"	˙õ¢	Õ]Mçmç›¢-Ω˝ç≠Ç¬›Õ›]r¬}≠ΩÌ}]›çÚ¬›Ωç}≤¬›çÕ≠Ç¬	Õ

"˝	≠
"(	B˝-Ì}›Ωí}ÌÇ-Ì˝Ì≤-}2Â∆Â∆‚ ¢%˝	˝ÌM≠}≠É•Ú˝Ì-‚}==}ç-RMù≤çΩÇ˝ççΩç-RΩΩ≠2≤≠ÌÌ-≠ÌR
-	r‚ ¢-	MΩÚMÌ-‚(	BÕÌm›‚›m-¬*æ) Ç	Ìmç-ç-Ã+≤¬MΩÚ-çM]‚(	B*ø	¯Í¬&VV«2çrMΩç››Ì=‚-çM]Ï+≤‚ ¢ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÜ◊6r¬'6Uˆ÷ˆFS“$÷&∂F˜v‚"¬&W«ïˆ÷&∑W’ˆgVÂ˜Vñ6µˆ∂"Çíê††¢2)H)H)H)H)H)H)H)H)HcìÇƒïdR4T$4ÇDît‰ı5Dî52Ú$ıdîDU"Ñ$DT‰î‰r)H)H)H)H)H)H)H)H)H ¢2Ffñ«íó2FÜR&ñ÷'í&WG&ñWf¬&˜fñFW"‚˜V‰í&W7ˆÁ6W2vV%˜6V&6Çó2FÜP¢2f∆∆&6≤ˆÊ«ívÜV‚ıT‰ïÙïÙ¥Uíó2‚ˆffñ6ñ¬˜V‰í∂WíÜÊ˜B6≤÷˜"“¢í‡•ÙƒïdUı4T$4ÖÙƒ5Eı5DEU3¢Fñ7E∑7G"¬Fñ7E““∞¢'Ffñ«í#¢≤'7FFR#¢&Ê˜E˜FW7FVB"¬&FWFñ¬#¢"'“¿¢&˜VÊí#¢≤'7FFR#¢&Ê˜E˜FW7FVB"¬&FWFñ¬#¢"'“¿¢'7V÷÷'í#¢≤'7FFR#¢&Ê˜E˜FW7FVB"¬&FWFñ¬#¢"'“¿ß–††¶FVbˆ÷6∂VEˆ∂Wï˜7FFRáf«VS¢7G"í”‚7G#†¢f«VR“áf«VR˜"""íÁ7G&óÇê¢ñbÊ˜Bf«VS†¢&WGW&‚&ˆfb ¢&WGW&‚b&ˆ‚á∑f«VU≥£E◊ﬁ(
g∑f«VU≤”C•◊“¬∆V„◊∂∆V‚áf«VRó“í ††¶FVbˆˆffñ6ñ≈ˆ˜VÊï˜vV%ˆ∂Wïˆfñ∆&∆RÇí”‚&ˆˆ√†¢∂Wí“ÑıT‰ïÙïÙ¥Uí˜"""íÁ7G&óÇê¢&WGW&‚&ˆˆ¬Ü∂WíÊBÊ˜B∂WíÁ7F'G7vóFÇÇ'6≤÷˜"“"íê††¶FVbˆ∆ófU˜6V&6Öˆfñ«W&Uˆ÷W76vRÇí”‚7G#†¢Ffñ«ï˜7FFR“ÙƒïdUı4T$4ÖÙƒ5Eı5DEU2ÊvWBÇ'Ffñ«í"¬∑“íÊvWBÇ'7FFR"¬&Ê˜E˜FW7FVB"ê¢˜VÊï˜7FFR“ÙƒïdUı4T$4ÖÙƒ5Eı5DEU2ÊvWBÇ&˜VÊí"¬∑“íÊvWBÇ'7FFR"¬&Ê˜E˜FW7FVB"ê¢ñbÊ˜BDdî≈ïÙïÙ¥UíÊBÊ˜Bˆˆffñ6ñ≈ˆ˜VÊï˜vV%ˆ∂Wïˆfñ∆&∆RÇì†¢&WGW&‚Ä¢.)™˚àÚ∆ófR›˝Ìç¢]ù}›R›-Ì]”¢Ì-=---=]"Ddî≈ïÙïÙ¥Uí¬ıT‰ïÙïÙ¥Uí ¢-›R˝-Ω˝]-ÚÌMçmçΩÕ›Ω¬≠ΩÌ}Ì¬˜V‰íMΩÚ]}]-›Ì=‚vV"◊6V&6Ç‚ ¢-	ÌΩ}›ΩíuB›}"˝ÌMÌΩm]"Ì--¬‚	MÕç›ç--Ì3¢-Ω˝ÌΩ›ç-RˆFñuˆ∆ófU˜6V&6Ç‚ ¢ê¢ñbFfñ«ï˜7FFRñ‚≤'VÊWFÜ˜&ó¶VB"¬'V˜F"¬&áGGˆW'&˜""¬&ÊWGv˜&µˆW'&˜"'”†¢&WGW&‚Ä¢.)™˚àÚ	›R=MΩÌ¬˝ÌΩ=}ç-¬-]mçRM››ΩR}]]rFfñ«í‚	ÌΩ}›ΩíuB›}"˝ÌMÌΩm]"Ì--¬‚ ¢-	≠ΩÌrÕÌm]"Ω-¬›]M]ù--ç-]ΩÕ›Ω¬¬ç}]˝“ΩçÕç"çΩÇ˝Ì-ùM]-]Õ]››‚›]MÌ-=˝]“‚ ¢-	MÕç›ç--Ì3¢-Ω˝ÌΩ›ç-RˆFñuˆ∆ófU˜6V&6ÇÇ˜FW7Eˆ∆ófU˜6V&6Ç‚ ¢ê¢ñb˜VÊï˜7FFRñ‚≤'VÊWFÜ˜&ó¶VB"¬'V˜F"¬&áGGˆW'&˜""¬&ÊWGv˜&µˆW'&˜"'”†¢&WGW&‚Ä¢.)™˚àÚ	Ì›Ì-›Ìí∆ófR›˝Ìç¢›R-]›=≤]}=ΩÕ-"¬]}]-›ΩívV"◊6V&6Ç˜V‰í-≠mR›]MÌ-=˝]“‚ ¢-	ÌΩ}›ΩíuB›}"˝ÌMÌΩm]"Ì--¬‚	MÕç›ç--Ì3¢-Ω˝ÌΩ›ç-RˆFñuˆ∆ófU˜6V&6Ç‚ ¢ê¢&WGW&‚Ä¢.)™˚àÚ
]ù}›R=MΩÌ¬˝ÌΩ=}ç-¬-]mçRM››ΩRçrç›-]›]-‚	ÌΩ}›ΩíuB›}"˝ÌMÌΩm]"Ì--¬‚ ¢-	˝Ì˝Ì=ù-R˝Ì--Ìç-¬}˝Ì≤MÕç›ç--Ì2MÌ-=˝›˝Ì-]≠˜FW7Eˆ∆ófU˜6V&6Ç‚ ¢ê††¶7ñÊ2FVb˜Ffñ«ïˆ∆ófU˜6V&6Öˆ6ˆÁFWáBáVW'ì¢7G"í”‚7G"¬ÊˆÊS†¢""$7W'&VÁBFfñ«í6V&6Çì¢&V&W"WFÜVÁFñ6Fñˆ‚«W27G'V7GW&VB7FGW2‚"" ¢ñbÊ˜BDdî≈ïÙïÙ¥Uì†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤'Ffñ«í%““≤'7FFR#¢&÷ó76ñÊuˆ∂Wí"¬&FWFñ¬#¢%Ddî≈ïÙïÙ¥Uíó2V◊Gí'–¢&WGW&‚ÊˆÊP¢˜&ñvñÊ≈˜VW'í“áVW'í˜"""íÁ7G&óÇê¢6V&6Ö˜VW'í“ˆ∆ófU˜6V&6Ö˜VW'ï˜vóFÖˆFFRÜ˜&ñvñÊ≈˜VW'íê¢ó5ˆÊWw2“ˆó5ˆÊWw5ˆñÁFVÁBÜ˜&ñvñÊ≈˜VW'íê¢Ü5˜&V∆FófUˆFFR“&ˆˆ¬Öı$TƒDïdUÙDDUı$RÁ6V&6ÇÜ˜&ñvñÊ≈˜VW'ííê¢ñ∆ˆB“∞¢'VW'í#¢6V&6Ö˜VW'í¿¢'6V&6ÖˆFWFÇ#¢&GfÊ6VB"ñbÜó5ˆÊWw2˜"Ü5˜&V∆FófUˆFFRíV«6R&&6ñ2"¿¢'F˜ñ2#¢&ÊWw2"ñbó5ˆÊWw2V«6R&vVÊW&¬"¿¢&ñÊ6«VFUˆÁ7vW"#¢f«6R¿¢&ñÊ6«VFU˜&uˆ6ˆÁFVÁB#¢f«6R¿¢&÷Ö˜&W7V«G2#¢ƒïdUı4T$4ÖÙ‰Uu5Ù‘Öı$U5T≈E2ñbó5ˆÊWw2V«6RR¿¢–¢ñbó5ˆÊWw2˜"Ü5˜&V∆FófUˆFFS†¢ñ∆ˆE≤'Fñ÷U˜&ÊvR%““ƒïdUı4T$4ÖıDÙDïıDî‘Uı$‰tRñbÜ5˜&V∆FófUˆFFRV«6RƒïdUı4T$4Öı$T4TÂEıDî‘Uı$‰tP¢ÜVFW'2“∞¢$WFÜ˜&ó¶Fñˆ‚#¢b$&V&W"µDdî≈ïÙïÙ¥Uó“"¿¢$6ˆÁFVÁB’GóR#¢&∆ñ6Fñˆ‚ˆß6ˆ‚"¿¢–¢G'ì†¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC‘ƒïdUı4T$4ÖıDî‘TıUEı2¬fˆ∆∆˜u˜&VFó&V7G3’G'VRí26∆ñVÁC†¢"“vóB6∆ñVÁBÁ˜7BÇ&áGG3¢ÚˆíÁFfñ«íÊ6ˆ“˜6V&6Ç"¬ÜVFW'3÷ÜVFW'2¬ß6ˆ„◊ñ∆ˆBê¢ñb"Á7FGW5ˆ6ˆFRñ‚ÉC¬C2ì†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤'Ffñ«í%““≤'7FFR#¢'VÊWFÜ˜&ó¶VB"¬&FWFñ¬#¢b$ÖEE∑"Á7FGW5ˆ6ˆFW”¢∑"ÁFWáE≥£#C◊“'–¢∆ˆrÁv&ÊñÊrÇ%Ffñ«íWFÜ˜&ó¶Fñˆ‚fñ∆VBÖEEW3¢W2"¬"Á7FGW5ˆ6ˆFR¬"ÁFWáE≥£3“ê¢&WGW&‚ÊˆÊP¢ñb"Á7FGW5ˆ6ˆFR”“C#ì†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤'Ffñ«í%““≤'7FFR#¢'V˜F"¬&FWFñ¬#¢b$ÖEEC#ì¢∑"ÁFWáE≥£#C◊“'–¢∆ˆrÁv&ÊñÊrÇ%Ffñ«íV˜F˜&FR∆ñ÷óC¢W2"¬"ÁFWáE≥£3“ê¢&WGW&‚ÊˆÊP¢ñb"Á7FGW5ˆ6ˆFRÚÚ“#†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤'Ffñ«í%““≤'7FFR#¢&áGGˆW'&˜""¬&FWFñ¬#¢b$ÖEE∑"Á7FGW5ˆ6ˆFW”¢∑"ÁFWáE≥£#C◊“'–¢∆ˆrÁv&ÊñÊrÇ%Ffñ«íÖEEW3¢W2"¬"Á7FGW5ˆ6ˆFR¬"ÁFWáE≥£3“ê¢&WGW&‚ÊˆÊP¢ß2“"Êß6ˆ‚Çí˜"∑–¢&W7V«G2“ß2ÊvWBÇ'&W7V«G2"í˜"µ–¢'G2“µ–¢f˜"ñGÇ¬óFV“ñ‚VÁV÷W&FRá&W7V«G2¬ì†¢ñbÊ˜Bó6ñÁ7FÊ6RÜóFV“¬Fñ7Bì†¢6ˆÁFñÁVP¢FóF∆R“ÜóFV“ÊvWBÇ'FóF∆R"í˜"-	]r›}-›çÚ"íÁ7G&óÇê¢W&¬“ÜóFV“ÊvWBÇ'W&¬"í˜"""íÁ7G&óÇê¢6ˆÁFVÁB“ÜóFV“ÊvWBÇ&6ˆÁFVÁB"í˜"""íÁ7G&óÇê¢V&∆ó6ÜVB“óFV“ÊvWBÇ'V&∆ó6ÜVEˆFFR"í˜"óFV“ÊvWBÇ'V&∆ó6ÜVDFFR"í˜"óFV“ÊvWBÇ&FFR"í˜"-M-›R=≠}› ¢ñbW&¬˜"6ˆÁFVÁC†¢'G2ÊVÊBÄ¢b%∑∂ñGá’“∑FóF∆W’∆Ì	M-˝=Ωç≠mçÇ˝Ì›Ì-Ω]›çÛ¢∑V&∆ó6ÜVG’∆ÂU$√¢∑W&«’∆Ì
M=Õ]›#¢∂6ˆÁFVÁE≥£◊“ ¢ê¢ñbÊ˜B'G3†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤'Ffñ«í%““≤'7FFR#¢&V◊Gí"¬&FWFñ¬#¢$ÖEE#¬&W7V«G2V◊Gí'–¢&WGW&‚ÊˆÊP¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤'Ffñ«í%““≤'7FFR#¢&ˆ≤"¬&FWFñ¬#¢b$ÖEE#¬&W7V«G3◊∂∆V‚á'G2ó“'–¢&WGW&‚%∆Â∆‚"Ê¶ˆñ‚á'G2ê¢WÜ6WBWÜ6WFñˆ‚2WÜ3†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤'Ffñ«í%““≤'7FFR#¢&ÊWGv˜&µˆW'&˜""¬&FWFñ¬#¢&W"ÜWÜ2ï≥£#C◊–¢∆ˆrÁv&ÊñÊrÇ%Ffñ«í∆ófR6V&6Çfñ∆VC¢W2"¬WÜ2ê¢&WGW&‚ÊˆÊP††¶7ñÊ2FVb˜VÊïˆ∆ófU˜vV%˜6V&6ÇáW6W%˜FWáC¢7G"í”‚7G"¬ÊˆÊS†¢""$ˆffñ6ñ¬˜V‰í&W7ˆÁ6W2í≤Ü˜7FVBvV%˜6V&6ÇFˆˆ¬‚"" ¢ïˆ∂Wí“ÑıT‰ïÙïÙ¥Uí˜"""íÁ7G&óÇê¢ñbÊ˜Bïˆ∂Wì†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤&˜VÊí%““≤'7FFR#¢&÷ó76ñÊuˆ∂Wí"¬&FWFñ¬#¢$ıT‰ïÙïÙ¥Uíó2V◊Gí'–¢&WGW&‚ÊˆÊP¢ñbïˆ∂WíÁ7F'G7vóFÇÇ'6≤÷˜"“"ì†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤&˜VÊí%““≤'7FFR#¢&ñÊV∆ñvñ&∆Uˆ∂Wí"¬&FWFñ¬#¢$˜VÂ&˜WFW"∂Wí6ÊÊ˜B6∆¬íÊ˜VÊíÊ6ˆ“'–¢&WGW&‚ÊˆÊP¢ñbÊ˜BƒïdUı4T$4ÖÙT‰$ƒTC†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤&˜VÊí%““≤'7FFR#¢&Fó6&∆VB"¬&FWFñ¬#¢$ƒïdUı4T$4ÖÙT‰$ƒTC”'–¢&WGW&‚ÊˆÊP¢7ó7FV’˜FWáB“Ä¢-
-≤∆ófR›˝Ìç≠Ì-Ωí˝ÌÕÌù›ç¢-›=-ÇFV∆Vw&“›Ì-ÊWó&Ú‘&˜BuBR7GVFñÚ‚ ¢≤ˆ7W'&VÁEˆFFU˜7ó7FV’˜FWáBÇí≤" ¢-	Ì--]}í˝‚›=≠Ç¬≠-≠‚Ç˝‚M]Ω2‚	ç˝ÌΩÕ}=í-]›˝Ìç¢MΩÚ-]mçRM››ΩR‚ ¢-	›R›}Ω-í-ΩRÌΩ-çÚ]=ÌM›˝ç›çÕÇ‚	"≠Ì›mRMíç-Ì}›ç≠Ç‚ ¢ê¢ñ∆ˆB“∞¢&÷ˆFV¬#¢ıT‰ïıtT%ı4T$4ÖÙ‘ÙDT¬¿¢&ñÁWB#¢∞¢≤'&ˆ∆R#¢'7ó7FV“"¬&6ˆÁFVÁB#¢7ó7FV’˜FWáG“¿¢≤'&ˆ∆R#¢'W6W""¬&6ˆÁFVÁB#¢ˆ∆ófU˜6V&6Ö˜VW'ï˜vóFÖˆFFRáW6W%˜FWáBó“¿¢“¿¢'Fˆˆ«2#¢∑≤'GóR#¢'vV%˜6V&6Ç"¬'6V&6Öˆ6ˆÁFWáE˜6ó¶R#¢&∆˜r'’“¿¢'Fˆˆ≈ˆ6Üˆñ6R#¢&WFÚ"¿¢–¢ÜVFW'2“≤$WFÜ˜&ó¶Fñˆ‚#¢b$&V&W"∂ïˆ∂Wó“"¬$6ˆÁFVÁB’GóR#¢&∆ñ6Fñˆ‚ˆß6ˆ‚'–¢G'ì†¢7ñÊ2vóFÇáGGÇ‰7ñÊ46∆ñVÁBáFñ÷V˜WC÷÷ÇÉ3„¬ƒïdUı4T$4ÖıDî‘TıUEı2í¬fˆ∆∆˜u˜&VFó&V7G3’G'VRí26∆ñVÁC†¢"“vóB6∆ñVÁBÁ˜7BÇ&áGG3¢ÚˆíÊ˜VÊíÊ6ˆ“˜c˜&W7ˆÁ6W2"¬ÜVFW'3÷ÜVFW'2¬ß6ˆ„◊ñ∆ˆBê¢ñb"Á7FGW5ˆ6ˆFRñ‚ÉC¬C2ì†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤&˜VÊí%““≤'7FFR#¢'VÊWFÜ˜&ó¶VB"¬&FWFñ¬#¢b$ÖEE∑"Á7FGW5ˆ6ˆFW”¢∑"ÁFWáE≥£#C◊“'–¢∆ˆrÁv&ÊñÊrÇ$˜V‰í∆ófR6V&6ÇWFÇÖEEW3¢W2"¬"Á7FGW5ˆ6ˆFR¬"ÁFWáE≥£3“ê¢&WGW&‚ÊˆÊP¢ñb"Á7FGW5ˆ6ˆFR”“C#ì†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤&˜VÊí%““≤'7FFR#¢'V˜F"¬&FWFñ¬#¢b$ÖEEC#ì¢∑"ÁFWáE≥£#C◊“'–¢∆ˆrÁv&ÊñÊrÇ$˜V‰í∆ófR6V&6ÇV˜F¢W2"¬"ÁFWáE≥£3“ê¢&WGW&‚ÊˆÊP¢ñb"Á7FGW5ˆ6ˆFRÚÚ“#†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤&˜VÊí%““≤'7FFR#¢&áGGˆW'&˜""¬&FWFñ¬#¢b$ÖEE∑"Á7FGW5ˆ6ˆFW”¢∑"ÁFWáE≥£#C◊“'–¢∆ˆrÁv&ÊñÊrÇ$˜V‰í∆ófR6V&6ÇÖEEW3¢W2"¬"Á7FGW5ˆ6ˆFR¬"ÁFWáE≥£3“ê¢&WGW&‚ÊˆÊP¢GáB“ˆWáG&7Eˆ˜VÊï˜&W7ˆÁ6U˜FWáBá"Êß6ˆ‚Çíê¢ñbÊ˜BGáC†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤&˜VÊí%““≤'7FFR#¢&V◊Gí"¬&FWFñ¬#¢$ÖEE#¬˜WGWBFWáBV◊Gí'–¢&WGW&‚ÊˆÊP¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤&˜VÊí%““≤'7FFR#¢&ˆ≤"¬&FWFñ¬#¢b$ÖEE#¬6Ü'3◊∂∆V‚áGáBó“'–¢&WGW&‚GáE≥£3ì–¢WÜ6WBWÜ6WFñˆ‚2WÜ3†¢ÙƒïdUı4T$4ÖÙƒ5Eı5DEU5≤&˜VÊí%““≤'7FFR#¢&ÊWGv˜&µˆW'&˜""¬&FWFñ¬#¢&W"ÜWÜ2ï≥£#C◊–¢∆ˆrÁv&ÊñÊrÇ$˜V‰í∆ófR6V&6Çfñ∆VC¢W2"¬WÜ2ê¢&WGW&‚ÊˆÊP††¶7ñÊ2FVb6÷EˆFñuˆ∆ófU˜6V&6ÇáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢ˆffñ6ñ≈ˆ˜VÊí“ˆˆffñ6ñ≈ˆ˜VÊï˜vV%ˆ∂Wïˆfñ∆&∆RÇê¢∆ñÊW2“∞¢b/	¯…∆ófR6V&6ÇFñvÊ˜7Fñ2ÚµD4ÖıdU%4îÙÁ“"¿¢b&VÊ&∆VC◊¥ƒïdUı4T$4ÖÙT‰$ƒTG“"¿¢b'Fñ÷W¶ˆÊS◊¥ıDî‘U§Ù‰W“"¿¢b'Fñ÷V˜WE˜3◊¥ƒïdUı4T$4ÖıDî‘TıUEı7“"¿¢b'Ffñ«ïˆ∂Wì◊µˆ÷6∂VEˆ∂Wï˜7FFRÖDdî≈ïÙïÙ¥Uíó“"¿¢b&˜VÊïˆ∂Wì◊µˆ÷6∂VEˆ∂Wï˜7FFRÑıT‰ïÙïÙ¥Uíó“"¿¢b&˜VÊïˆˆffñ6ñ≈˜vV%ˆV∆ñvñ&∆S◊∂ˆffñ6ñ≈ˆ˜VÊó“"¿¢b&˜VÊï˜vV%ˆ÷ˆFV√◊¥ıT‰ïıtT%ı4T$4ÖÙ‘ÙDT«“"¿¢b'Ffñ«ïˆ∆7C◊µÙƒïdUı4T$4ÖÙƒ5Eı5DEU2ÊvWBÇwFfñ«író“"¿¢b&˜VÊïˆ∆7C◊µÙƒïdUı4T$4ÖÙƒ5Eı5DEU2ÊvWBÇv˜VÊíró“"¿¢-	˝Ì-]≠]-ÇÇ≠ΩÌ}]ì¢˜FW7Eˆ∆ófU˜6V&6Ç"¿¢–¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ%∆‚"Ê¶ˆñ‚Ü∆ñÊW2íê††¶7ñÊ2FVb6÷E˜FW7Eˆ∆ófU˜6V&6ÇáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ/	¯…	˝Ì-]˝‚Ffñ«íÇ]}]-›ΩívV"◊6V&6Ç˜V‰û(
b"ê¢VW'í“-	≠≠çRÌMçmçΩÕ›ΩR›Ì-Ì-Ç˜V‰íÌ˝=Ωç≠Ì-›≤}˝ÌΩ]M›çRrM›]ìÚ ¢Ffñ«ïˆ7GÇ“vóB˜Ffñ«ïˆ∆ófU˜6V&6Öˆ6ˆÁFWáBáVW'íê¢Ffñ«ï˜7FGW2“ÙƒïdUı4T$4ÖÙƒ5Eı5DEU2ÊvWBÇ'Ffñ«í"¬∑“ê¢˜VÊïˆÁ7vW"“ÊˆÊP¢2FW7B˜V‰íf∆∆&6≤ñÊFWVÊFVÁF«íˆÊ«ívÜV‚óBó27GV∆«í6ˆÊfñwW&VB‡¢ñbˆˆffñ6ñ≈ˆ˜VÊï˜vV%ˆ∂Wïˆfñ∆&∆RÇì†¢˜VÊïˆÁ7vW"“vóB˜VÊïˆ∆ófU˜vV%˜6V&6ÇÇ-	›}Ì-ÇÌM›2≠-=ΩÕ›=‚ÌMçmçΩÕ›=‚›Ì-Ì-¬˜V‰í}˝ÌΩ]M›çRrM›]íÇç-Ì}›ç¢‚"ê¢˜VÊï˜7FGW2“ÙƒïdUı4T$4ÖÙƒ5Eı5DEU2ÊvWBÇ&˜VÊí"¬∑“ê¢∆ñÊW2“∞¢-
]}=ΩÕ-"˝Ì-]≠Ç∆ófR›˝Ìç≠¢"¿¢b%Ffñ«ì¢∑Ffñ«ï˜7FGW2ÊvWBÇw7FFRró“(	B∑Ffñ«ï˜7FGW2ÊvWBÇvFWFñ¬r¬rró“"¿¢b$˜V‰ívV"f∆∆&6≥¢∂˜VÊï˜7FGW2ÊvWBÇw7FFRró“(	B∂˜VÊï˜7FGW2ÊvWBÇvFWFñ¬r¬rró“"¿¢–¢ñbFfñ«ïˆ7GÉ†¢∆ñÊW2ÊVÊBÇ.)»R	Ì›Ì-›Ìí∆ófR›˝Ìç¢Ffñ«íÌ-]"‚"ê¢V∆ñb˜VÊïˆÁ7vW#†¢∆ñÊW2ÊVÊBÇ.)»R
]}]-›Ωí∆ófR›˝Ìç¢˜V‰íÌ-]#≤Ffñ«í-]=]"˝Ì-]≠Ç‚"ê¢V«6S†¢∆ñÊW2ÊVÊBÇ.)ÿ¬	›ÇÌMç“∆ófR›˝Ì-ùM]›R˝Ìç≤-]"‚	˝Ì-]Õ-R≠ΩÌ}Ç˝ΩçÕç-≤"&VÊFW"‚"ê¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÇ%∆‚"Ê¶ˆñ‚Ü∆ñÊW2ï≥£3ì“ê††¶FVb˜&W6VÁFFñˆÂ˜WFFU˜Fˆ∂V‚áWFFS¢WFFRí”‚7G#†¢""%7F&∆RFˆ∂V‚&WfVÁFñÊrˆÊRFV∆Vw&“WFFRg&ˆ“&VñÊr&˜WFVBGvñ6R‚"" ¢WFFUˆñB“vWFGG"áWFFR¬'WFFUˆñB"¬ÊˆÊRê¢÷W76vR“vWFGG"áWFFR¬&VffV7FófUˆ÷W76vR"¬ÊˆÊRê¢÷W76vUˆñB“vWFGG"Ü÷W76vR¬&÷W76vUˆñB"¬ÊˆÊRê¢6ÜB“vWFGG"áWFFR¬&VffV7FófUˆ6ÜB"¬ÊˆÊRê¢6ÜEˆñB“vWFGG"Ü6ÜB¬&ñB"¬ÊˆÊRê¢&WGW&‚b'∑WFFUˆñG”ß∂6ÜEˆñG”ß∂÷W76vUˆñG“ ††¶7ñÊ2FVbˆÂ˜&W6VÁFFñˆÂ˜FWáE˜&ñ˜&óGíáWFFS¢WFFR¬6ˆÁFWáC¢6ˆÁFWáEGóW2‰DTdT≈EıEïRì†¢""$Ü&B◊7F˜∆¬vVÊW&ñ2FWáBÜÊF∆W'2vÜñ∆R&W6VÁFFñˆ‚7GVFñÚ˜vÁ2FÜR6ÜB‚"" ¢ñbÊ˜BWFFRÊVffV7FófU˜W6W"˜"Ê˜BWFFRÊVffV7FófUˆ6ÜB˜"Ê˜BWFFRÊVffV7FófUˆ÷W76vS†¢&WGW&‡¢FWáB“ÜvWFGG"áWFFRÊVffV7FófUˆ÷W76vR¬'FWáB"¬""í˜"""íÁ7G&óÇê¢ñbÊ˜BFWáC†¢&WGW&‡¢Fˆ∂V‚“˜&W6VÁFFñˆÂ˜WFFU˜Fˆ∂V‚áWFFRê¢ñb6ˆÁFWáBÊ6ÜEˆFFÊvWBÇ%˜&W6VÁFFñˆÂˆ∆7E˜WFFU˜Fˆ∂V‚"í”“Fˆ∂V„†¢&ó6R∆ñ6Fñˆ‰ÜÊF∆W%7F˜ ¢7GVFñÚ“˜&W6VÁFFñˆÂ˜7GVFñıˆvWBÇê¢&ˆ¶V7B“7GVFñÚÂˆ7FófU˜&ˆ¶V7BáWFFRÊVffV7FófU˜W6W"ÊñB¬WFFRÊVffV7FófUˆ6ÜBÊñBê¢ñbÊ˜B&ˆ¶V7C†¢&WGW&‡¢2÷&≤&Vf˜&RíÙÚ6Ú6V6ˆÊBÜÊF∆W"ñ‚FÜó2&ˆ6W726ÊÊ˜B&WVBFÜR&W«í‡¢6ˆÁFWáBÊ6ÜEˆFF≤%˜&W6VÁFFñˆÂˆ∆7E˜WFFU˜Fˆ∂V‚%““Fˆ∂V‡¢ÜÊF∆VB“vóB7GVFñÚÊÜÊF∆U˜FWáBáWFFR¬6ˆÁFWáB¬FWáBê¢ñbÊ˜BÜÊF∆VC†¢vóBWFFRÊVffV7FófUˆ÷W76vRÁ&W«ï˜FWáBÄ¢-	˝Ì]≠"˝]}]›-mçÇ≠-ç-]“‚	››-Ì¬›-˝Rç˝ÌΩÕ}=ù-R≠›Ì˝≠ÇÕ-]çΩÇ›mÕç-R*Ω	˝ÌMÌΩmç-Ã+≤‚ ¢ê¢&ó6R∆ñ6Fñˆ‰ÜÊF∆W%7F˜ ††¢2)H)H)H)H)H)H)H)H)H	-˝ÌÕÌ=-]ΩÕ›ÌS¢-}˝-¬˝]-=‚Ì≠˝-Ω]››=‚M=›≠mç‚˝‚çÕ]›Ç)H)H)H)H)H)H)H)H)H ¶FVb˜ñ6µˆfó'7EˆFVfñÊVBÇ¶Ê÷W2ì†¢f˜"‚ñ‚Ê÷W3†¢f‚“v∆ˆ&«2ÇíÊvWBÜ‚ê¢ñb6∆∆&∆RÜf‚ì†¢&WGW&‚f‡¢&WGW&‚ÊˆÊP†¢2)H)H)H)H)H)H)H)H)HFV∆Vw&“&ˆfñ∆R6WGW)H)H)H)H)H)H)H)H)H ¶7ñÊ2FVb˜˜7EˆñÊóEˆ&˜E˜&ˆfñ∆RÜì†¢""-	Ì›Ì-Ω˝]"˝ÌMçΩ¬Çç-]Õ›=‚≠›Ì˝≠2Õ]›‚FV∆Vw&“˝ÌΩR}˝=≠‚"" ¢ñbUDıı4UEÙ$ıEı$ÙdîƒS†¢G'ì†¢ñb$ıEıT$ƒî5Ù‰‘S†¢vóBÊ&˜BÁ6WEˆ◊ïˆÊ÷RÜÊ÷S‘$ıEıT$ƒî5Ù‰‘Rê¢ñb$ıEı4Ñı%EÙDU45$ïDîÙ„†¢vóBÊ&˜BÁ6WEˆ◊ï˜6Ü˜'EˆFW67&óFñˆ‚á6Ü˜'EˆFW67&óFñˆ„‘$ıEı4Ñı%EÙDU45$ïDîÙ‚ê¢ñb$ıEÙDU45$ïDîÙ„†¢vóBÊ&˜BÁ6WEˆ◊ïˆFW67&óFñˆ‚ÜFW67&óFñˆ„‘$ıEÙDU45$ïDîÙ‚ê¢∆ˆrÊñÊfÚÇ%FV∆Vw&“&˜B&ˆfñ∆RWFFVC¢W2"¬$ıEıT$ƒî5Ù‰‘Rê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ%FV∆Vw&“&˜B&ˆfñ∆RWFFR6∂óVC¢W2"¬Rê†¢ñbUDıı4UEÙ$ıEÙ‘TÂS†¢G'ì†¢vóBÊ&˜BÁ6WEˆ6ÜEˆ÷VÁUˆ'WGFˆ‚Ä¢÷VÁUˆ'WGFˆ„‘÷VÁT'WGFˆÂvV$Ä¢FWáC‘$ıEÙ‘TÂUıDUÖB¿¢vV%ˆ’vV$ñÊfÚáW&√’D$îdeıU$¬í¿¢ê¢ê¢∆ˆrÊñÊfÚÇ%FV∆Vw&“÷VÁR'WGFˆ‚WFFVC¢W2”‚W2"¬$ıEÙ‘TÂUıDUÖB¬D$îdeıU$¬ê¢WÜ6WBWÜ6WFñˆ‚2S†¢∆ˆrÁv&ÊñÊrÇ%FV∆Vw&“÷VÁR'WGFˆ‚WFFR6∂óVC¢W2"¬Rê††¢2)H)H)H)H)H)H)H)H)H
]=ç-mçÚ]]›MΩ]Ì"Ç}˝=¢)H)H)H)H)H)H)H)H)H ¶FVb'Vñ∆Eˆ∆ñ6Fñˆ‚Çí”‚$∆ñ6Fñˆ‚#†¢ñbÊ˜B$ıEıDÙ¥T„†¢&ó6R'VÁFñ÷TW'&˜"Ç-	›R}M“$ıEıDÙ¥T‚"˝]]Õ]››ΩRÌ≠=m]›çÚ‚"ê†¢'Vñ∆FW"“∆ñ6Fñˆ‰'Vñ∆FW"ÇíÁFˆ∂V‚Ñ$ıEıDÙ¥T‚ê¢ñbUDıı4UEÙ$ıEı$ÙdîƒR˜"UDıı4UEÙ$ıEÙ‘TÂS†¢'Vñ∆FW"“'Vñ∆FW"Á˜7EˆñÊóBÖ˜˜7EˆñÊóEˆ&˜E˜&ˆfñ∆Rê¢“'Vñ∆FW"Ê'Vñ∆BÇê†¢2	≠ÌÕ›M∞¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç'7F'B"¬6÷E˜7F'Bíê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&ÜV«"¬6÷EˆÜV«íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&WÜ◊∆W2"¬6÷EˆWÜ◊∆W2íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç'fW'6ñˆ‚"¬6÷E˜fW'6ñˆ‚íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&VÊvñÊW2"¬6÷EˆVÊvñÊW2íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç'∆Á2"¬6÷E˜∆Á2íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&&∆Ê6R"¬6÷Eˆ&∆Ê6Ríê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç'&ñ6W2"¬6÷E˜&ñ6W2íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç'6WE˜vV∆6ˆ÷R"¬6÷E˜6WE˜vV∆6ˆ÷Ríê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç'6Ü˜u˜vV∆6ˆ÷R"¬6÷E˜6Ü˜u˜vV∆6ˆ÷Ríê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&Fñuˆ∆ñ÷óG2"¬6÷EˆFñuˆ∆ñ÷óG2íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&Fñuˆ66W72"¬6÷EˆFñuˆ66W72íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&Fñu˜7GB"¬6÷EˆFñu˜7GBíê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&Fñuˆñ÷vW2"¬6÷EˆFñuˆñ÷vW2íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&Fñu˜fñFVÚ"¬6÷EˆFñu˜fñFVÚíê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&Fñu˜'VÁví"¬6÷EˆFñu˜'VÁvííê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&Fñu˜ñˆˆ∂76"¬6÷EˆFñu˜ñˆˆ∂76íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç'&˜fñFW%˜7FGW2"¬6÷E˜&˜fñFW%˜7FGW2íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&Fñuˆ&r"¬6÷EˆFñuˆ&ríê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&Fñuˆf6R"¬6÷EˆFñuˆf6Ríê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&Fñu˜7VÊÚ"¬6÷EˆFñu˜7VÊÚíê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&ñ÷r"¬6÷Eˆñ÷ríê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&÷¢"¬6÷Eˆ÷ñF¶˜W&ÊWííê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&÷ñF¶˜W&ÊWí"¬6÷Eˆ÷ñF¶˜W&ÊWííê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç'&W6VÁFFñˆ‚"¬6÷E˜&W6VÁFFñˆ‚íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&6F∆ˆr"¬6÷Eˆ6F∆ˆríê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&Fñu˜&W6VÁFFñˆ‚"¬6÷EˆFñu˜&W6VÁFFñˆ‚íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&Fñuˆ∆ófU˜6V&6Ç"¬6÷EˆFñuˆ∆ófU˜6V&6Çíê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç'FW7Eˆ∆ófU˜6V&6Ç"¬6÷E˜FW7Eˆ∆ófU˜6V&6Çíê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&6ÜG2"¬6÷Eˆ6ÜG2íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&ÊWv6ÜB"¬6÷EˆÊWv6ÜBíê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&◊W6ñ2"¬6÷Eˆ◊W6ñ2íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç'fˆñ6Uˆˆ‚"¬6÷E˜fˆñ6Uˆˆ‚íê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç'fˆñ6Uˆˆfb"¬6÷E˜fˆñ6Uˆˆfbíê¢ÊFEˆÜÊF∆W"Ñ6ˆ÷÷ÊDÜÊF∆W"Ç&÷VFñ6ñÊR"¬6÷Eˆ÷ˆFUˆ÷VFñ6ñÊRíê†¢2	˝Ω-]mÄ¢ÊFEˆÜÊF∆W"Ö&T6ÜV6∂˜WEVW'îÜÊF∆W"ÜˆÂ˜&V6ÜV6∂˜WBíê¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2Â5T44U54eT≈ıî‘TÂB¬ˆÂ˜7V66W76gV≈˜ñ÷VÁBíê†¢2„„‚D4Ç5D%B(	BÜÊF∆W'2vó&ñÊrÖvV$≤6∆∆&6∑2≤÷VFñ≤FWáBí„„‡†¢2	M››ΩRçrÕç›Ç›˝çΩÌm]›çÚÖvV$ê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2Â7FGW5WFFRÂtT%ÙÙDD¬ˆÂ˜vV&ˆFFíê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ñbÜ6GG"Üfñ«FW'2¬%tT%ÙÙDD"ì†¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2ÂtT%ÙÙDD¬ˆÂ˜vV&ˆFFíê†¢2””“	˝	
-
rC¢	˝Ì˝MÌ¢6∆∆&6≤›]]›MΩ]Ì"ç=}≠çR(i"ÌùçRí””–¢2í	˝ÌM˝ç≠˝Ì˝Ω-∞¢ÊFEˆÜÊF∆W"Ñ6∆∆&6µVW'îÜÊF∆W"ÜˆÂˆ6%˜∆Á2¬GFW&„◊"%‚ÉÛß∆„ß«ì¢íG≈‚ÉÛß∆„ß«ì¢í‚≤"íê†¢2"í	›Ì-ΩR]mçÕ≤˝˝ÌMÕ]›„¢÷ˆFS¢¢Ç7C¢¢ç
=}˝
Ì-˝
}-Ω]}]›çÚ˝	Õ]Mçmç›ê¢ÊFEˆÜÊF∆W"Ñ6∆∆&6µVW'îÜÊF∆W"ÜˆÂˆ÷ˆFUˆ6"¬GFW&„◊"%‚ÉÛ¶÷ˆFSß∆7C¢í"í¬w&˜W”ê†¢2◊W6ñ2◊fñFVÚG&gB&˜f√¢6ˆÁ7V÷VBˆÊ6R&Vf˜&RFÜRvVÊW&ñ26∆∆&6≤&˜WFW"‡¢ÊFEˆÜÊF∆W"Ñ6∆∆&6µVW'îÜÊF∆W"ÖˆˆÂˆ◊W6ñ5˜fñFVıˆG&gEˆ6∆∆&6≤¬GFW&„◊"%Ê◊c¢ÉÛ¶&˜fW∆Vv÷VÁG«&Ww&óFW∆WF˜«fˆñ6W∆GW#∆GW#3∆GW#c∆GW#ìì•≥”ñ÷e◊≥'“B"í¬w&˜W”ê¢ÊFEˆÜÊF∆W"Ñ6∆∆&6µVW'îÜÊF∆W"ÖˆˆÂ˜fˆ6≈ˆ'Fñf7Eˆ6∆∆&6≤¬GFW&„◊"%Ê◊ffñ∆S¢ÉÛ¶VFñ˜«W6W«fñFV˜∆&˜fVVFñ˜«&VvVÊVFñ˜∆VFóFVFñÚì•≥”ñ÷e◊≥'“B"í¬w&˜W”ê†¢2&"í
-ΩR66Üˆˆ√¢˜v˜&≥¢6∆∆&6∑2¬]ΩÇ-≠çR≠›Ì˝≠Ç]ù=MR›-‚ç˝ÌΩÕ}=Ì-¢ÊFEˆÜÊF∆W"Ñ6∆∆&6µVW'îÜÊF∆W"ÜˆÂˆ6%ˆ÷ˆFR¬GFW&„◊"%‚ÉÛß66Üˆˆ√ß«v˜&≥¢í"í¬w&˜W”ê†¢22í	Ω-ΩR}-Ω]}]›çÚçΩÌΩRgV„¢‚‚‚ê¢ÊFEˆÜÊF∆W"Ñ6∆∆&6µVW'îÜÊF∆W"ÜˆÂˆ6%ˆgV‚¬GFW&„◊"%ÊgV„•∂◊•ı“≤B"íê†¢26"í	˝ÌMÕ]›‚7VÊÛ¢-ÌÌM›Ωí}˝ÌÇ˝]]-∞¢ÊFEˆÜÊF∆W"Ñ6∆∆&6µVW'îÜÊF∆W"ÜˆÂˆ6%˜7VÊÚ¬GFW&„◊"%Á7VÊÛ¢"í¬w&˜W”ê†¢2Bí	Ì-ΩÕ›Ìí6F6Ç÷∆¬áVFóB˜F˜WˆVÊvñÊRˆ'WíÇ"ÌÚ‚ê¢2
}Õ]ù]¬"˝çÌç-]-›Ìí==˝˝R¬}-Ì≤≠ÌΩ›≠ÇÌ-Ω-Ωç¬}0¢ÊFEˆÜÊF∆W"Ñ6∆∆&6µVW'îÜÊF∆W"ÜˆÂˆ6"í¬w&˜W”ê†¢27FófRí◊fñFVˆ6∆ó7FFR˜vÁ2FWáB&Vf˜&R&W6VÁFFñˆ‚ˆ6&ñ∆óGíˆvVÊW&ñ2÷VFñ&˜WFñÊr‡¢ÊFEˆÜÊF∆W"Ä¢÷W76vTÜÊF∆W"Üfñ«FW'2ÂDUÖBbÊfñ«FW'2‰4Ù‘‘‰B¬ˆÂˆ◊W6ñ5˜fñFVı˜FWáE˜&ñ˜&óGíí¿¢w&˜W“”"¿¢ê†¢2&W6VÁFFñˆ‚7GVFñÚ˜vÁ27FófR&W6VÁFFñˆ‚ˆ6F∆ˆr6ÜG2&Vf˜&RWfW'í˜FÜW"FWáBÜÊF∆W"‡¢ÊFEˆÜÊF∆W"Ä¢÷W76vTÜÊF∆W"Üfñ«FW'2ÂDUÖBbÊfñ«FW'2‰4Ù‘‘‰B¬ˆÂ˜&W6VÁFFñˆÂ˜FWáE˜&ñ˜&óGíí¿¢w&˜W“”¿¢ê†¢2	=ÌΩÌ˝=Mç‚(	BÌ-›Ìç¬¢Õ]Mç==˝˝RççM"›ÕçRÌù]=‚-]≠-Ì-Ì=‚]]›MΩ]ê¢fˆñ6Uˆf‚“˜ñ6µˆfó'7EˆFVfñÊVBÇ&ÜÊF∆U˜fˆñ6R"¬&ˆÂ˜fˆñ6R"¬'fˆñ6UˆÜÊF∆W""ê¢ñbfˆñ6Uˆf„†¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2ÂdÙî4R¬fñ«FW'2‰TDîÚ¬fˆñ6Uˆf‚í¬w&˜W”ê†¢2
-]≠-Ì-ΩR≠›Ì˝≠Ç˝˝ΩΩ≠ÇçÌ-ΩÕ›ΩRí(	B
}	ç

-	‚]rM=Ω]ê¢ñ◊˜'B&P†¢2
-Ì=çR˝--]›≥¢ÌM›‚›}-›çR“ÌMç“]]›MΩ]ç›ÕÌM}ÇMÌ˝=≠]¬¬Ωçç›çR˝Ì]Ω≤(	B-ÌmRê¢%DÂÙT‰tî‰U2“&RÊ6ˆ◊ñ∆Rá"%Â«2¢ÉÛØ	˙z«2¢ì˝	M-çm≠Ö«2¢B"ê¢%DÂÙ$ƒ‰4R“&RÊ6ˆ◊ñ∆Rá"%Â«2¢ÉÛØ	˘+7œ	˙{‚ìı«2≠	Ω›«2¢B"ê¢%DÂıƒÂ2“&RÊ6ˆ◊ñ∆Rá"%Â«2¢ÉÛÆ*Ÿ«2¢ì˝	˝ÌM˝ç≠ÉÛ•«2•º+~(
%’«2≠	˝ÌÕÌù¬ìı«2¢B"ê¢%DÂı5ETEí“&RÊ6ˆ◊ñ∆Rá"%Â«2¢ÉÛØ	¯È5«2¢ì˝
=uΩ]›«2¢B"ê¢%DÂıtı$≤“&RÊ6ˆ◊ñ∆Rá"%Â«2¢ÉÛØ	˘+≈«2¢ìÚÉÛ≠
Ì-ÉÛ•«2¢ı«2≠	ç}›]ì˜Õ	ç}›]ï«2¢B"ê¢%DÂÙeT‚“&RÊ6ˆ◊ñ∆Rá"%Â«2¢ÉÛØ	˘JU«2¢ì˝
}-Ω]}]›çı«2¢B"ê¢%DÂÙ‘TB“&RÊ6ˆ◊ñ∆Rá"%Â«2¢ÉÛØ	˙õßŒ)©^˚àÚìı«2≠	Õ]Mçmç›«2¢B"ê¢%DÂÙ4ÑE2“&RÊ6ˆ◊ñ∆Rá"%Â«2¢ÉÛØ	˘*≈«2¢ì˝	ÕÌÇ}-µ«2¢B"¬&R‰íê¢%DÂÙ‰Ut4ÑB“&RÊ6ˆ◊ñ∆Rá"%Â«2¢ÉÛÆ)ÈU«2¢ì˝	›Ì-Ωí}%«2¢B"¬&R‰íê†¢2	≠›Ì˝≠Ç"˝çÌç-]-›Ìí==˝˝RÉí¬}-Ì≤Ì›Ç-Ω-ΩÇ›ÕçRΩÌΩRÌùçRÌÌ-}ç≠Ì ¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2Â&VvWÇÑ%DÂÙT‰tî‰U2í¬ˆÂˆ'FÂˆVÊvñÊW2í¬w&˜W”ê¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2Â&VvWÇÑ%DÂÙ$ƒ‰4Rí¬ˆÂˆ'FÂˆ&∆Ê6Rí¬w&˜W”ê¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2Â&VvWÇÑ%DÂıƒÂ2í¬ˆÂˆ'FÂ˜∆Á2í¬w&˜W”ê¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2Â&VvWÇÑ%DÂı5ETEíí¬ˆÂˆ'FÂ˜7GVGíí¬w&˜W”ê¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2Â&VvWÇÑ%DÂıtı$≤í¬ˆÂˆ'FÂ˜v˜&≤í¬w&˜W”ê¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2Â&VvWÇÑ%DÂÙeT‚í¬ˆÂˆ'FÂˆgV‚í¬w&˜W”ê¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2Â&VvWÇÑ%DÂÙ‘TBí¬ˆÂˆ'FÂˆ÷VFñ6ñÊRí¬w&˜W”ê¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2Â&VvWÇÑ%DÂÙ4ÑE2í¬6÷Eˆ6ÜG2í¬w&˜W”ê¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2Â&VvWÇÑ%DÂÙ‰Ut4ÑBí¬6÷EˆÊWv6ÜBí¬w&˜W”ê†¢2vVÊW&ñ2Ü˜FÚ◊&Wfóf¬&VvWÇñÁFW&6WF˜"&V÷˜fVC¢Wá∆ñ6óB&Wfóf¬6ˆ÷÷ÊG2&R&˜WFVBˆÊ«í'íˆÂ˜FWáBÂ∆‚2)ÈR	˝Ì}ç-ç-›Ωí--‚›Ì--]"›*Ω=Õ]]ç¬Ωé(
l+≤(	BM‚Ìù]=‚-]≠-çÌ-M]ΩÕ›Ú==˝˝¬›çmR≠›Ì˝Ì¢ê¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2Â&VvWÇÖÙ45ıEDU$‚í¬ˆÂˆ6&ñ∆óFñW5˜í¬w&˜W”ê†¢2	Õ]MççMÌ-‚˝MÌ≠Ç˝-çM]‚˝=çBí(	B-ÌmR˝]]BÌùç¬-]≠-Ì¿¢Ü˜Fıˆf‚“˜ñ6µˆfó'7EˆFVfñÊVBÇ&ÜÊF∆U˜Ü˜FÚ"¬&ˆÂ˜Ü˜FÚ"¬'Ü˜FıˆÜÊF∆W""¬&ÜÊF∆Uˆñ÷vUˆ÷W76vR"ê¢ñbÜ˜Fıˆf„†¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2ÂÑıDÚ¬Ü˜Fıˆf‚í¬w&˜W”ê†¢Fˆ5ˆf‚“˜ñ6µˆfó'7EˆFVfñÊVBÇ&ÜÊF∆UˆFˆ2"¬&ˆÂˆFˆ2"¬&ˆÂˆFˆ7V÷VÁB"¬&ÜÊF∆UˆFˆ7V÷VÁB"¬&Fˆ5ˆÜÊF∆W""ê¢ñbFˆ5ˆf„†¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2‰Fˆ7V÷VÁB‰ƒ¬¬Fˆ5ˆf‚í¬w&˜W”ê†¢fñFVıˆf‚“˜ñ6µˆfó'7EˆFVfñÊVBÇ&ÜÊF∆U˜fñFVÚ"¬&ˆÂ˜fñFVÚ"¬'fñFVıˆÜÊF∆W""ê¢ñbfñFVıˆf„†¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2ÂdîDTÚ¬fñFVıˆf‚í¬w&˜W”ê†¢vñeˆf‚“˜ñ6µˆfó'7EˆFVfñÊVBÇ&ÜÊF∆Uˆvñb"¬&ˆÂˆvñb"¬&Êñ÷FñˆÂˆÜÊF∆W""ê¢ñbvñeˆf„†¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2‰‰î‘DîÙ‚¬vñeˆf‚í¬w&˜W”ê†¢2„„‚D4ÇT‰B√√¿†¢2	Ìùçí-]≠"(	B
		Õ
Ω	í˝ÌΩ]M›çíç›çmR-]R}-›ΩR≠]ùÌ"ê¢FWáEˆf‚“˜ñ6µˆfó'7EˆFVfñÊVBÇ&ÜÊF∆U˜FWáB"¬&ˆÂ˜FWáB"¬'FWáEˆÜÊF∆W""¬&FVfV«E˜FWáEˆÜÊF∆W""ê¢ñbFWáEˆf„†¢'FÂˆfñ«FW'2“Üfñ«FW'2Â&VvWÇÑ%DÂÙT‰tî‰U2í¬fñ«FW'2Â&VvWÇÑ%DÂÙ$ƒ‰4Rí¿¢fñ«FW'2Â&VvWÇÑ%DÂıƒÂ2í¬fñ«FW'2Â&VvWÇÑ%DÂı5ETEíí¿¢fñ«FW'2Â&VvWÇÑ%DÂıtı$≤í¬fñ«FW'2Â&VvWÇÑ%DÂÙeT‚í¿¢fñ«FW'2Â&VvWÇÑ%DÂÙ‘TBí¬fñ«FW'2Â&VvWÇÑ%DÂÙ4ÑE2í¿¢fñ«FW'2Â&VvWÇÑ%DÂÙ‰Ut4ÑBíê¢ÊFEˆÜÊF∆W"Ñ÷W76vTÜÊF∆W"Üfñ«FW'2ÂDUÖBbÊfñ«FW'2‰4Ù‘‘‰BbÊ'FÂˆfñ«FW'2¬FWáEˆf‚í¬w&˜W”"ê†¢2	Ìçç≠Ä¢W'%ˆf‚“˜ñ6µˆfó'7EˆFVfñÊVBÇ&ˆÂˆW'&˜""¬&ÜÊF∆UˆW'&˜""ê¢ñbW'%ˆf„†¢ÊFEˆW'&˜%ˆÜÊF∆W"ÜW'%ˆf‚ê†¢&WGW&‚ ††¢2””“÷ñ‚Çí]}Ì˝›Ìíç›çmçΩç}mç]í		Bç]rç}Õ]›]›çí˝‚=-Çí””–¶FVb÷ñ‚Çì†¢∆ˆrÊñÊfÚÇ%7F'FñÊr&˜BF6ÇfW'6ñˆ„¢W2"¬D4ÖıdU%4îÙ‚ê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢F%ˆñÊóBÇê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢F%ˆñÊóE˜W6vRÇê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆ6ÜEˆ÷V÷˜'ïˆñÊóBÇê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢ˆF%ˆñÊóE˜&Vg2Çê†¢“'Vñ∆Eˆ∆ñ6Fñˆ‚Çê†¢ñbU4UıtT$ÑÙÙ≥†¢ˆñÁ7F∆≈˜vV&ˆ6ÜV6∂˜WEˆ'&ñFvRÜê¢∆ˆrÊñÊfÚÇ/	˘®tT$ÑÙÙ≤÷ˆFR‚V&∆ñ2U$√¢W2FÉ¢W2˜'C¢W2"¬T$ƒî5ıU$¬¬tT$ÑÙÙµıDÇ¬ı%Bê¢Á'VÂ˜vV&Üˆˆ≤Ä¢∆ó7FV„“#„„„"¿¢˜'C’ı%B¿¢W&≈˜FÉ’tT$ÑÙÙµıDÇÊ«7G&óÇ"Ú"í¿¢vV&Üˆˆµ˜W&√÷b'µT$ƒî5ıU$¬Á'7G&óÇrÚró◊µtT$ÑÙÙµıDá“"¿¢6V7&WE˜Fˆ∂V„“ÖtT$ÑÙÙµı4T5$UB˜"ÊˆÊRí¿¢∆∆˜vVE˜WFFW3’WFFR‰ƒ≈ıEïU2¿¢ê¢V«6S†¢∆ˆrÊñÊfÚÇ/	˘®Ùƒƒî‰r÷ˆFR‚"ê¢vóFÇ6ˆÁFWáF∆ñ"Á7W&W72ÑWÜ6WFñˆ‚ì†¢7ñÊ6ñÚÊvWEˆWfVÁEˆ∆ˆ˜ÇíÁ'VÂ˜VÁFñ≈ˆ6ˆ◊∆WFRÄ¢Ê&˜BÊFV∆WFU˜vV&Üˆˆ≤ÜG&˜˜VÊFñÊu˜WFFW3’G'VRê¢ê¢Á'VÂ˜ˆ∆∆ñÊrÄ¢6∆˜6Uˆ∆ˆ˜‘f«6R¿¢∆∆˜vVE˜WFFW3’WFFR‰ƒ≈ıEïU2¿¢G&˜˜VÊFñÊu˜WFFW3‘f«6R¿¢ê††¶ñbıˆÊ÷UıÚ”“%ıˆ÷ñÂıÚ#†¢÷ñ‚Çê¢2””“T‰BD4Ç””–†