Warning: truncated output (original token count: 277238)
... 60376 bytes omitted ...

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

# ───────── Render Secret Files bootstrap ─────────
# Must run before any API keys are read from os.environ.
from secret_loader import bootstrap_secret_environment, get_secret
_SECRET_FILE_SOURCES = bootstrap_secret_environment()


from music_video_scene_plan import (
    ScenePlan,
    chunk_review_messages,
    render_scene_plan_review,
    scene_plan_from_dict,
    scene_plan_from_explicit_timeline,
)
from video_studio import SeedanceError, seedance_generate, seedance_scene_prompt

# ───────── Rembg cache bootstrap ─────────
# Render Starter/ручной deploy часто не имеет writable /data.
# Rembg/pooch должен получить writable U2NET_HOME ДО импорта rembg, иначе модель не скачивается.
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
    # Последний резерв — /tmp, даже если проверка выше неожиданно не прошла.
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
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, WebAppInfo, InputFile,
    LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton, MenuButtonWebApp
)
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters,
    PreCheckoutQueryHandler, CallbackQueryHandler, ApplicationHandlerStop
)
from telegram.constants import ChatAction
from telegram.error import TelegramError, TimedOut, BadRequest
from presentation_studio import PresentationStudio, StudioConfig
from neyrobot_prod.entertainment import (
    build_keyboard as build_entertainment_keyboard,
    classify_callback as classify_entertainment_callback,
    entertainment_menu_v2_enabled,
    get_menu as get_entertainment_menu,
)
# ───────── TTS imports ─────────
import contextlib  # уже у тебя выше есть, дублировать НЕ надо, если импорт стоит

# Optional PIL / rembg for photo tools
try:
    from PIL import Image, ImageFilter, ImageOps, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageFilter = None
    ImageOps = None
    ImageDraw = None
# rembg imports onnxruntime and can reserve hundreds of MiB.  It is only needed
# by the optional background-removal flow, not by the bot/video providers, so do
# not load it during normal startup on the 512 MiB Render Starter instance.
rembg_remove = None
rembg_new_session = None
REMBG_IMPORT_ERROR = "lazy import not attempted"
_REMBG_IMPORT_ATTEMPTED = False


def _ensure_rembg_import() -> bool:
    global rembg_remove, rembg_new_session, REMBG_IMPORT_ERROR, _REMBG_IMPORT_ATTEMPTED
    if _REMBG_IMPORT_ATTEMPTED:
        return rembg_remove is not None
    _REMBG_IMPORT_ATTEMPTED = True
    try:
        from rembg import remove as _remove, new_session as _new_session
        rembg_remove = _remove
        rembg_new_session = _new_session
        REMBG_IMPORT_ERROR = ""
        return True
    except Exception as exc:
        REMBG_IMPORT_ERROR = repr(exc)
        return False

# ───────── LOGGING ─────────
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

PATCH_VERSION = "v105-seedance-video-studio-2026-10-16"

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

# Provider inputs cannot use Telegram's bot-file URL: some video providers reject
# it while fetching, and it would expose the bot credential in a third-party
# request.  Render serves short-lived opaque artifacts from this directory instead.
PROVIDER_INPUT_DIR = _ensure_writable_dir_env(
    "PROVIDER_INPUT_DIR", "/data/neyro_provider_inputs", "/tmp/neyro_provider_inputs"
)
PROVIDER_INPUT_TTL_S = max(300, min(24 * 3600, int(os.environ.get("PROVIDER_INPUT_TTL_S", "3600") or 3600)))
PROVIDER_INPUT_MAX_BYTES = max(1024 * 1024, min(100 * 1024 * 1024, int(
    os.environ.get("PROVIDER_INPUT_MAX_BYTES", str(64 * 1024 * 1024)) or 64 * 1024 * 1024
)))

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

# ВАЖНО: провайдер текста (openai / openrouter и т.п.)
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
# Голос по умолчанию именно для говорящего аватара. Пользователь может выбрать голос кнопкой в меню аватара.
AVATAR_TTS_DEFAULT_VOICE = os.environ.get("AVATAR_TTS_DEFAULT_VOICE", OPENAI_TTS_VOICE or "nova").strip() or "nova"
AVATAR_TTS_VOICES = [v.strip() for v in os.environ.get("AVATAR_TTS_VOICES", "nova,alloy,onyx,shimmer,fable").split(",") if v.strip()]
TTS_MAX_CHARS        = int(os.environ.get("TTS_MAX_CHARS", "1000") or "1000")
# 0 = не дублировать озвученный текст подписью к voice-сообщению.
# Пользователь получает: текстовый ответ + отдельное voice без caption.
TTS_VOICE_CAPTION    = os.environ.get("TTS_VOICE_CAPTION", "0").strip().lower() in ("1", "true", "yes", "on")
# 0 = не отправлять отдельное сообщение «Распознал: ...» после voice/STT.
STT_ECHO_TRANSCRIPT  = os.environ.get("STT_ECHO_TRANSCRIPT", "0").strip().lower() in ("1", "true", "yes", "on")

# Память диалога для GPT-ответов: короткая история по user_id/chat_id.
CHAT_MEMORY_ENABLED      = os.environ.get("CHAT_MEMORY_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
CHAT_MEMORY_MAX_MESSAGES = int(os.environ.get("CHAT_MEMORY_MAX_MESSAGES", "16") or "16")
CHAT_MEMORY_MAX_CHARS    = int(os.environ.get("CHAT_MEMORY_MAX_CHARS", "6000") or "6000")
CHAT_MEMORY_TTL_DAYS     = int(os.environ.get("CHAT_MEMORY_TTL_DAYS", "0") or "0")
# Виртуальные пользовательские диалоги внутри одного Telegram-чата.
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
# Luma Images (опционально: если нет — используем OpenAI Images как фолбэк)
LUMA_IMG_BASE_URL = os.environ.get("LUMA_IMG_BASE_URL", "").strip().rstrip("/")
LUMA_IMG_MODEL    = os.environ.get("LUMA_IMG_MODEL", "imagine-image-1").strip()

# Фолбэки Luma
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

# CometAPI / Sora / Kling wrappers for image→video
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
# Пока отдельной колонки music в БД нет, списываем из общего видео/generative-бюджета.
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
# v35: точный FaceSwap для групповых фото.
# Идея: если пользователь выбрал конкретное лицо, мы изолируем это лицо для провайдера,
# а затем возвращаем в исходный кадр только изменённую область выбранного лица. Так провайдер
# не может случайно поменять соседнего человека, даже если его внутренний порядок лиц другой.
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
# Старый Render ENV мог оставлять LOCAL_REMBG_ENABLED=0.
# Для продакшн-сборки фона принудительно включаем local rembg,
# если специально не поставлен BG_FORCE_LOCAL_REMBG=0.
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
        return "ошибок пока нет"
    return "\n".join(f"• {x}" for x in _LAST_BG_ERRORS[-5:])


async def cmd_diag_bg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Диагностика удаления/замены фона: ENV, rembg import, model session."""
    _ensure_rembg_import()
    lines: list[str] = []
    lines.append(f"🧪 BG diagnostic / {PATCH_VERSION}")
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

    # Проверяем папки без падения команды.
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
            # Первый запуск может скачать модель, поэтому даём больше времени.
            sess = await asyncio.wait_for(asyncio.to_thread(_get_local_rembg_session), timeout=min(max(30, int(LOCAL_REMBG_TIMEOUT_S)), 240))
            session_ok = sess is not None
        except Exception as e:
            _bg_note_error(f"diag session failed: {e}")
            lines.append(f"session_error={repr(e)[:700]}")

    lines.append(f"session_ok={session_ok}")
    lines.append("Последние ошибки:")
    lines.append(_bg_last_errors_text())

    await update.effective_message.reply_text("\n".join(lines)[:3900])
RUNWAY_COMET_CREATE_PATH = os.environ.get("RUNWAY_COMET_CREATE_PATH", "/runwayml/v1/image_to_video").strip() or "/runwayml/v1/image_to_video"
RUNWAY_COMET_STATUS_PATH = os.environ.get("RUNWAY_COMET_STATUS_PATH", "/runwayml/v1/tasks/{id}").strip() or "/runwayml/v1/tasks/{id}"
# Comet/Runway иногда несколько минут отвечает task_not_exist: это стадия инициализации.
# Если ответ висит слишком долго, не держим пользователя 20 минут — мягко переключаемся на Kling.
RUNWAY_TASK_NOT_EXIST_FALLBACK_S = int(os.environ.get("RUNWAY_TASK_NOT_EXIST_FALLBACK_S", "45") or 45)
RUNWAY_AUTO_FALLBACK_KLING = os.environ.get("RUNWAY_AUTO_FALLBACK_KLING", "1").strip().lower() not in ("0", "false", "no", "off")
# v76: production-safe Runway/Comet controls.
RUNWAY_IMAGE2VIDEO_ENABLED = os.environ.get("RUNWAY_IMAGE2VIDEO_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
RUNWAY_HIDE_TECH_ERRORS = os.environ.get("RUNWAY_HIDE_TECH_ERRORS", "1").strip().lower() not in ("0", "false", "no", "off")
RUNWAY_IMAGE2VIDEO_FAIL_FAST = os.environ.get("RUNWAY_IMAGE2VIDEO_FAIL_FAST", "1").strip().lower() not in ("0", "false", "no", "off")
RUNWAY_PROVIDER_COOLDOWN_S = int(os.environ.get("RUNWAY_PROVIDER_COOLDOWN_S", "300") or 300)
RUNWAY_PROVIDER_FAIL_THRESHOLD = int(os.environ.get("RUNWAY_PROVIDER_FAIL_THRESHOLD", "2") or 2)
# v77: первым пробуем публичный идентификатор Comet model page, затем backend-алиасы.
RUNWAY_IMAGE2VIDEO_MODELS_ENV = os.environ.get("RUNWAY_IMAGE2VIDEO_MODELS", "runwayml-image-to-video,gen4_turbo,gen3a_turbo,veo3.1_fast,veo3.1,veo3").strip()
RUNWAY_PUBLIC_FALLBACK_TEXT = os.environ.get("RUNWAY_PUBLIC_FALLBACK_TEXT", "⚠️ Канал Runway сейчас недоступен у провайдера. Автоматически запускаю Kling без дополнительного списания.").strip()
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
# Предобработка исходника для image→video: уменьшает риск, что Kling/Runway оживит весь скриншот телефона вместо портрета.
I2V_PREPROCESS_ENABLED = os.environ.get("I2V_PREPROCESS_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
I2V_WARN_BAD_SOURCE = os.environ.get("I2V_WARN_BAD_SOURCE", "1").strip().lower() not in ("0", "false", "no", "off")
I2V_AUTOCROP_BLACK_BORDERS = os.environ.get("I2V_AUTOCROP_BLACK_BORDERS", "1").strip().lower() not in ("0", "false", "no", "off")
I2V_MAX_SOURCE_SIDE = int(os.environ.get("I2V_MAX_SOURCE_SIDE", "1280") or 1280)
I2V_BAD_SOURCE_POLICY = os.environ.get("I2V_BAD_SOURCE_POLICY", "warn_continue").strip().lower()  # warn_continue | ask_clean
I2V_KLING_SAFE_PROMPT_SUFFIX = os.environ.get("I2V_KLING_SAFE_PROMPT_SUFFIX", "animate only the person/photo content; do not create phone screens, app interface, black borders, UI overlays, or screenshots; keep identity and original composition").strip()
SORA_API_KEY   = (os.environ.get("SORA_API_KEY") or COMET_API_KEY).strip()
SORA_MODEL     = os.environ.get("SORA_MODEL", "sora-2").strip()
# Защита от старого ENV Render: если там случайно осталось sora-1,
# Comet возвращает model_not_found. Для этой сборки принудительно используем sora-2.
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
# Text→Video через CometAPI: Sora 2 (только без людей), Kling и Runway. Luma временно скрыта.
KLING_TEXT_CREATE_PATH = os.environ.get("KLING_TEXT_CREATE_PATH", "/kling/v1/videos/text2video").strip() or "/kling/v1/videos/text2video"
KLING_TEXT_STATUS_PATH = os.environ.get("KLING_TEXT_STATUS_PATH", "/kling/v1/videos/text2video/{id}").strip() or "/kling/v1/videos/text2video/{id}"

# Kling Avatar / talking head / photo→music-video
KLING_AVATAR_CREATE_PATH = os.environ.get("KLING_AVATAR_CREATE_PATH", "/kling/v1/videos/avatar/image2video").strip() or "/kling/v1/videos/avatar/image2video"
KLING_AVATAR_STATUS_PATH = os.environ.get("KLING_AVATAR_STATUS_PATH", "/kling/v1/videos/avatar/image2video/{id}").strip() or "/kling/v1/videos/avatar/image2video/{id}"
KLING_LIPSYNC_ENABLED = os.environ.get("KLING_LIPSYNC_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
KLING_IDENTIFY_FACE_PATH = os.environ.get("KLING_IDENTIFY_FACE_PATH", "/kling/v1/videos/identify-face").strip() or "/kling/v1/videos/identify-face"
KLING_LIPSYNC_CREATE_PATH = os.environ.get("KLING_LIPSYNC_CREATE_PATH", "/kling/v1/videos/advanced-lip-sync").strip() or "/kling/v1/videos/advanced-lip-sync"
if KLING_LIPSYNC_CREATE_PATH.rstrip("/") == "/kling/v1/videos/lip-sync":
    KLING_LIPSYNC_CREATE_PATH = "/kling/v1/videos/advanced-lip-sync"
KLING_LIPSYNC_STATUS_PATH = os.environ.get("KLING_LIPSYNC_STATUS_PATH", "/kling/v1/videos/lip-sync/{id}").strip() or "/kling/v1/videos/lip-sync/{id}"
KLING_LIPSYNC_RETRY_ATTEMPTS = max(1, int(os.environ.get("KLING_LIPSYNC_RETRY_ATTEMPTS", "3") or 3))
KLING_LIPSYNC_RETRY_BASE_S = max(0.0, float(os.environ.get("KLING_LIPSYNC_RETRY_BASE_S", "1.5") or 1.5))
KLING_AVATAR_MODE = os.environ.get("KLING_AVATAR_MODE", "std").strip().lower() or "std"
if KLING_AVATAR_MODE not in ("std", "pro"):
    KLING_AVATAR_MODE = "std"
KLING_AVATAR_PROMPT = os.environ.get(
    "KLING_AVATAR_PROMPT",
    "The person talks naturally to camera, realistic facial motion, accurate lip sync, subtle head movement, stable identity."
).strip()

# Text→speech for avatar. OpenAI TTS is primary because it supports Russian well;
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
FFMPEG_MUX_MAX_LONG_EDGE = max(720, min(3840, int(os.environ.get("FFMPEG_MUX_MAX_LONG_EDGE", "2160") or 2160)))
FFMPEG_MUX_THREADS = max(1, min(4, int(os.environ.get("FFMPEG_MUX_THREADS", "1") or 1)))
MUSIC_VIDEO_FINALIZE_CONCURRENCY = max(1, min(2, int(os.environ.get("MUSIC_VIDEO_FINALIZE_CONCURRENCY", "1") or 1)))

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
# Kling Avatar через Comet нестабильно принимает длинные Suno-треки.
# Для lip-sync держим безопасный фрагмент: так задача быстрее стартует и не висит на polling.
VOCAL_CLIP_MAX_AUDIO_S = int(os.environ.get("VOCAL_CLIP_MAX_AUDIO_S", "65") or 65)
VOCAL_CLIP_MIN_AUDIO_S = int(os.environ.get("VOCAL_CLIP_MIN_AUDIO_S", "12") or 12)
VOCAL_CLIP_KLING_MAX_WAIT_S = int(os.environ.get("VOCAL_CLIP_KLING_MAX_WAIT_S", "1800") or 1800)
TEXT_VIDEO_UNIT_COST_USD = _env_float("TEXT_VIDEO_UNIT_COST_USD", KLING_UNIT_COST_USD)
TEXT_VIDEO_DEFAULT_ENGINE = os.environ.get("TEXT_VIDEO_DEFAULT_ENGINE", "kling").strip().lower() or "kling"
VEO_FAST_MODEL = os.environ.get("VEO_FAST_MODEL", "veo3.1-fast")
VEO_FAST_COST_PER_SECOND_USD = _env_float("VEO_FAST_COST_PER_SECOND_USD", 0.096)
# Published Comet price for kling-advanced-lip-syn, one request per scene.
VEO_24S_KLING_LIPSYNC_COST_USD = _pricing_cost("VEO_24S_KLING_LIPSYNC_COST_USD", 0.056)
# The vocal-clip flow uses the same documented advanced lip-sync endpoint.  Keep
# its estimate separate so a future provider change cannot silently affect Veo.
VOCAL_CLIP_KLING_LIPSYNC_COST_USD = _pricing_cost(
    "VOCAL_CLIP_KLING_LIPSYNC_COST_USD", VEO_24S_KLING_LIPSYNC_COST_USD
)
# OpenAI lists gpt-4o-mini-tts at an estimated $0.015 per generated minute.
# A 24-second master track is therefore budgeted before any paid provider POST.
VEO_24S_TTS_COST_PER_MINUTE_USD = _pricing_cost("VEO_24S_TTS_COST_PER_MINUTE_USD", 0.015)
TEXT_VIDEO_ALLOW_RUNWAY = os.environ.get("TEXT_VIDEO_ALLOW_RUNWAY", "1").strip().lower() not in ("0", "false", "no", "off")
SEEDANCE_ENABLED = os.environ.get("SEEDANCE_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
SEEDANCE_MODEL = os.environ.get("SEEDANCE_MODEL", "seedance-2-5-260628").strip() or "seedance-2-5-260628"
SEEDANCE_MODEL_FALLBACKS = [item.strip() for item in os.environ.get("SEEDANCE_MODEL_FALLBACKS", "seedance-2-5,seedance-2-5-260628").split(",") if item.strip()]
SEEDANCE_CREATE_PATH = os.environ.get("SEEDANCE_CREATE_PATH", "/v1/videos").strip() or "/v1/videos"
SEEDANCE_COST_PER_SECOND_USD = _pricing_cost("SEEDANCE_COST_PER_SECOND_USD", 0.10)

_photo_clip_background_jobs: set[str] = set()
_vocal_clip_background_jobs: set[str] = set()
_music_video_finalize_semaphore = asyncio.Semaphore(MUSIC_VIDEO_FINALIZE_CONCURRENCY)

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

# Таймауты
LUMA_MAX_WAIT_S     = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)
LUMA_TEMP_DISABLED = True  # временная заглушка: скрываем Luma из меню и отключаем использование
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
    # v83: подписка + кредиты для тяжёлых генераций.
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

# ── Безлимит ──
def _parse_ids_csv(s: str) -> set[int]:
    return set(int(x) for x in s.split(",") if x.strip().isdigit())

UNLIM_USER_IDS   = _parse_ids_csv(os.environ.get("UNLIM_USER_IDS",""))
UNLIM_USERNAMES  = set(s.strip().lstrip("@").lower() for s in os.environ.get("UNLIM_USERNAMES","").split(",") if s.strip())
# Встроенные служебные безлимитные аккаунты. Дополнительно можно задать ENV UNLIM_USERNAMES.
UNLIM_USERNAMES.update({
    "gpt5pro_support",
    "neyrobotsupport",
    "granova_elena",
})

# Промо-доступ: безлимитный GPT + N бесплатных запусков каждой платной функции в день.
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

# ── Premium page URL ──
def _make_tariff_url(src: str = "subscribe") -> str:
    base = (WEBAPP_URL or f"{PUBLIC_URL.rstrip('/')}/premium.html").strip()
    # Независимый cache-buster гарантирует загрузку актуального premium.html после деплоя,
    # даже если в Render WEBAPP_URL остался со старым параметром v=.
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


# ── Telegram profile / pre-start description ──
AUTO_SET_BOT_PROFILE = os.environ.get("AUTO_SET_BOT_PROFILE", "1").strip().lower() not in ("0", "false", "no", "off")
AUTO_SET_BOT_MENU = os.environ.get("AUTO_SET_BOT_MENU", "1").strip().lower() not in ("0", "false", "no", "off")
BOT_MENU_TEXT = os.environ.get("BOT_MENU_TEXT", "Меню ботов").strip()[:64] or "Меню ботов"
BOT_PUBLIC_NAME = os.environ.get("BOT_PUBLIC_NAME", "Neyro-Bot GPT 5 Studio").strip()[:64]
BOT_SHORT_DESCRIPTION = os.environ.get(
    "BOT_SHORT_DESCRIPTION",
    'GPT-5, Sora 2, Kling, Runway, Midjourney, Suno: текст, фото, видео, музыка, аватар, Reels/Shorts в одном AI-боте.'
).strip()[:120]
BOT_DESCRIPTION = os.environ.get(
    "BOT_DESCRIPTION",
    'Neyro-Bot GPT 5 Studio — мультимодельная AI-студия в Telegram. GPT-чат, PDF/DOCX, фото и скриншоты, анализ документов, озвучка и распознавание речи, генерация изображений, логотипы, Midjourney-стиль, удаление/замена фона, замена лица, оживление фото, говорящий аватар, клип с вокалом для 1 человека, видео по тексту/голосу, Reels/Shorts, мини-фильмы, Sora 2, Kling, Runway, Suno-музыка. Выберите режим или просто напишите задачу.'
).strip()[:512]

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

# ───────── LIVE INTERNET / CURRENT DATA ─────────
# Этот слой нужен, чтобы бот не отвечал «мои данные устарели» на вопросы про курсы,
# новости, законы, релизы, погоду и прочую актуальную информацию.
LIVE_SEARCH_ENABLED = os.environ.get("LIVE_SEARCH_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
CRYPTO_RATE_ENABLED = os.environ.get("CRYPTO_RATE_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
LIVE_SEARCH_TIMEOUT_S = _env_float("LIVE_SEARCH_TIMEOUT_S", 18.0)
BINANCE_MARKET_BASE = os.environ.get("BINANCE_MARKET_BASE", "https://api.binance.com").strip().rstrip("/")
OPENAI_WEB_SEARCH_MODEL = os.environ.get("OPENAI_WEB_SEARCH_MODEL", "gpt-5.6").strip() or "gpt-5.6"

# v84: единая дата/часовой пояс для GPT и live-поиска.
# Без этого относительное слово «сегодня» могло быть сопоставлено со старой новостью из выдачи.
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
LIVE_SEARCH_DATE_GUARD = os.environ.get("LIVE_SEARCH_DATE_GUARD", "1").strip().lower() not in ("0", "false", "no", "off")
LIVE_SEARCH_TODAY_TIME_RANGE = os.environ.get("LIVE_SEARCH_TODAY_TIME_RANGE", "day").strip() or "day"
LIVE_SEARCH_RECENT_TIME_RANGE = os.environ.get("LIVE_SEARCH_RECENT_TIME_RANGE", "week").strip() or "week"
LIVE_SEARCH_NEWS_MAX_RESULTS = int(os.environ.get("LIVE_SEARCH_NEWS_MAX_RESULTS", "8") or 8)

LIVE_WORDS_RE = re.compile(
    r"(сегодня|сейчас|актуальн|последн|новост|курс|котиров|цена|стоимость|"
    r"сколько стоит|поч[её]м|погода|расписание|когда выйдет|вышел ли|закон|штраф|"
    r"налог|пенси|бирж|акци|доллар|евро|бат|рубл|usdt|btc|bitcoin|биткоин|"
    r"президент|губернатор|ceo|директор|релиз|трейлер|обновлени|провер[ьи]|найди)",
    re.IGNORECASE,
)

CRYPTO_RE = re.compile(
    r"(btc|bitcoin|биткоин|биткоина|биток|eth|ethereum|эфир|usdt|solana|sol|солана|bnb|toncoin|ton)",
    re.IGNORECASE,
)

RATE_RE = re.compile(
    r"(курс|цена|стоимость|сколько стоит|поч[её]м|сегодня|сейчас|котиров|торгуется|rate|price)",
    re.IGNORECASE,
)

# Запросы прогноза НЕ должны перехватываться быстрым обработчиком курса.
# Иначе пользователь спрашивает «прогноз роста/падения», а бот снова отвечает только текущим курсом.
FORECAST_RE = re.compile(
    r"(прогноз|перспектив|ожидан|рост|паден|выраст|вырасти|упад|упасть|будет|месяц|недел|"
    r"target|forecast|prediction|bull|bear|long|short)",
    re.IGNORECASE,
)

_RELATIVE_DATE_RE = re.compile(
    r"(сегодня|сейчас|на текущий момент|к этому часу|за сегодня|с утра|этой ночью|"
    r"today|now|current(?:ly)?|this morning|tonight)",
    re.IGNORECASE,
)
_NEWS_INTENT_RE = re.compile(
    r"(новост|атак|дрон|беспилот|обстрел|взрыв|происшеств|пожар|авари|войн|конфликт|"
    r"политик|санкци|выбор|аэропорт|пво|мчс|теракт|news|attack|drone|breaking)",
    re.IGNORECASE,
)
_RU_MONTHS = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
_RU_MONTH_TO_NUM = {v: k for k, v in _RU_MONTHS.items()}

def _app_now() -> datetime:
    try:
        return datetime.now(ZoneInfo(APP_TIMEZONE))
    except Exception:
        # Безопасный fallback для основного российского часового пояса.
        return datetime.now(timezone(timedelta(hours=3)))

def _current_date_meta() -> dict:
    now = _app_now()
    return {
        "now": now,
        "iso": now.strftime("%Y-%m-%d"),
        "ru": f"{now.day} {_RU_MONTHS[now.month]} {now.year} года",
        "time": now.strftime("%H:%M"),
        "timezone": APP_TIMEZONE,
    }

def _current_date_system_text() -> str:
    d = _current_date_meta()
    return (
        f"Текущая дата и время сервиса: {d['ru']}, {d['time']} ({d['timezone']}; ISO {d['iso']}). "
        "Слова «сегодня», «сейчас», «этой ночью» и другие относительные даты всегда трактуй относительно этой даты. "
        "Не называй старую дату сегодняшней."
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
            f"{q}. Точная текущая дата: {d['iso']} ({d['ru']}), часовой пояс {d['timezone']}. "
            f"Искать события именно за {d['iso']}; более старые материалы не считать событиями за сегодня."
        )
    return q

def _claimed_today_date(text: str) -> tuple[int, int, int] | None:
    # Ловим формулировки вида «Сегодня, 18 июня 2026 года».
    m = re.search(
        r"сегодня\s*[,—:-]?\s*(\d{1,2})\s+"
        r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
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
    r"(что\s+ты\s+умеешь|что\s+умеешь|какие\s+у\s+тебя\s+возможности|"
    r"что\s+умеет\s+бот|как\s+пользоваться|покажи\s+функции|список\s+функций|"
    r"чем\s+ты\s+можешь\s+помочь|help|features|capabilities)",
    re.IGNORECASE,
)


def _crypto_symbol_from_text(text: str) -> tuple[str, str] | None:
    t = (text or "").lower()
    if any(x in t for x in ("биткоин", "биткоина", "биток", "btc", "bitcoin")):
        return "BTCUSDT", "биткоин"
    if any(x in t for x in ("эфир", "ethereum", "eth")):
        return "ETHUSDT", "Ethereum"
    if "usdt" in t or "tether" in t:
        return "USDCUSDT", "USDT"
    if any(x in t for x in ("solana", "солана", "sol")):
        return "SOLUSDT", "Solana"
    if "bnb" in t:
        return "BNBUSDT", "BNB"
    if any(x in t for x in ("toncoin", "тон", " ton", "ton ")):
        return "TONUSDT", "TON"
    return None


def _is_crypto_rate_query(text: str) -> bool:
    return bool(text and CRYPTO_RE.search(text) and RATE_RE.search(text))


def _is_crypto_forecast_query(text: str) -> bool:
    """Прогноз/сценарий по крипте: не обрабатываем как простой запрос курса."""
    return bool(text and FORECAST_RE.search(text) and (CRYPTO_RE.search(text) or RATE_RE.search(text) or "актив" in text.lower()))


def _is_general_capability_query(text: str) -> bool:
    return bool(text and GENERAL_CAPABILITY_RE.search(text))


def _last_crypto_pair_from_memory(user_id: int | None, chat_id: int | None) -> tuple[str, str] | None:
    """Достаём последний обсуждавшийся криптоактив из памяти, но не смешиваем весь контекст с новым запросом."""
    ctx = _chat_memory_context_text(user_id, chat_id, limit=10)
    return _crypto_symbol_from_text(ctx) if ctx else None


def _crypto_contextual_text(user_id: int | None, chat_id: int | None, original_text: str) -> tuple[str, tuple[str, str] | None]:
    """
    Добавляет крипто-контекст только когда это действительно follow-up про рынок/прогноз/курс.
    Не подмешивает историю в вопросы вроде «что ты умеешь», чтобы бот не залипал на BTC.
    """
    t = (original_text or "").strip()
    if not t:
        return t, None
    direct = _crypto_symbol_from_text(t)
    if direct:
        return t, direct
    if _is_general_capability_query(t):
        return t, None
    looks_market_followup = bool(FORECAST_RE.search(t) or RATE_RE.search(t) or re.search(r"(актив|рынок|крипт|монет|коин|рост|паден)", t, re.I))
    if not looks_market_followup:
        return t, None
    pair = _last_crypto_pair_from_memory(user_id, chat_id)
    if not pair:
        return t, None
    symbol, human = pair
    return f"{t}\n\nКонтекст предыдущего диалога: речь идёт о {human} ({symbol}).", pair


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
    Live-курс криптовалют через Binance public market data. API-ключ не нужен.
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
            f"📈 Актуальный курс: {human_name.upper()}",
            f"Пара: {symbol}",
            f"Цена: ${_fmt_money(price, 2)}",
        ]
        if change is not None:
            sign = "+" if not str(change).startswith("-") else ""
            lines.append(f"За 24 часа: {sign}{_fmt_money(change, 2)}%")
        if high and low:
            lines.append(f"Диапазон 24ч: ${_fmt_money(low, 2)} — ${_fmt_money(high, 2)}")
        if quote_volume:
            lines.append(f"Оборот 24ч: ${_fmt_money(quote_volume, 0)}")
        lines.append("")
        lines.append("Источник: Binance spot market data")
        lines.append(f"Обновлено: {now}")
        lines.append("Не является финансовой рекомендацией.")
        return "\n".join(lines)
    except Exception as e:
        log.warning("Crypto live rate failed: %s", e)
        return None



async def _get_crypto_market_snapshot(symbol: str) -> dict | None:
    """Мини-снимок рынка Binance: текущая цена, 24ч и дневные свечи за 30 дней."""
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
        f"Актив: {human_name} ({snap.get('symbol')})",
        f"Текущая цена: ${_fmt_money(snap.get('price'), 2)}",
        f"Изменение 24ч: {_fmt_money(snap.get('change_24h_pct'), 2)}%",
    ]
    if snap.get("change_7d_pct") is not None:
        lines.append(f"Изменение 7д: {_fmt_money(snap.get('change_7d_pct'), 2)}%")
    if snap.get("change_30d_pct") is not None:
        lines.append(f"Изменение 30д: {_fmt_money(snap.get('change_30d_pct'), 2)}%")
    if snap.get("ma7"):
        lines.append(f"MA7: ${_fmt_money(snap.get('ma7'), 2)}")
    if snap.get("ma30"):
        lines.append(f"MA30: ${_fmt_money(snap.get('ma30'), 2)}")
    if snap.get("support_30d") and snap.get("resistance_30d"):
        lines.append(f"30д диапазон: ${_fmt_money(snap.get('support_30d'), 2)} — ${_fmt_money(snap.get('resistance_30d'), 2)}")
    return "\n".join(lines)


async def get_crypto_forecast_text(user_text: str, pair: tuple[str, str], user_id: int | None = None, chat_id: int | None = None) -> str | None:
    """Сценарный прогноз по крипте вместо повторной выдачи текущего курса."""
    if not pair:
        return None
    symbol, human_name = pair
    snap = await _get_crypto_market_snapshot(symbol)
    snap_text = _crypto_snapshot_text(snap, human_name)
    horizon = "месяц" if re.search(r"месяц|30", user_text or "", re.I) else "ближайший период"
    prompt = (
        "Пользователь спрашивает прогноз роста или падения по криптовалюте. "
        "Ответь по-русски как аналитический сценарный обзор, не как финансовую рекомендацию. "
        "Не повторяй только текущий курс. Дай: 1) базовый сценарий, 2) бычий сценарий, 3) медвежий сценарий, "
        "4) уровни поддержки/сопротивления из данных, 5) что отслеживать, 6) короткий вывод. "
        "Обязательно укажи, что это вероятностная оценка, а не совет покупать/продавать.\n\n"
        f"Горизонт: {horizon}.\n"
        f"Вопрос пользователя: {user_text}\n\n"
        f"Свежие рыночные данные Binance:\n{snap_text}"
    )
    try:
        reply = await ask_openai_text(
            prompt,
            user_id=user_id,
            chat_id=chat_id,
            extra_system="Не отвечай справкой 'что такое Bitcoin'. Пользователь просит прогноз по уже выбранному активу.",
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
            # Не берём готовый синтез Tavily: он мог склеить старую новость со словом «сегодня».
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
            f"ТЕКУЩАЯ ДАТА СЕРВИСА: {d['iso']} ({d['ru']}), {d['timezone']}.",
            (
                "ПРАВИЛО: материалы с более ранней датой нельзя описывать как произошедшие сегодня. "
                "Если за текущую дату подтверждений нет, нужно прямо написать, что надёжных подтверждений за сегодня не найдено."
            ),
        ]
        for idx, item in enumerate(data.get("results", []) or [], start=1):
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "Источник").strip()
            url = (item.get("url") or "").strip()
            content = (item.get("content") or "").strip()
            published = (
                item.get("published_date")
                or item.get("publishedDate")
                or item.get("date")
                or "дата публикации не указана"
            )
            if url or content:
                parts.append(
                    f"[{idx}] {title}\nДата публикации/обновления: {published}\nURL: {url}\nФрагмент: {content[:1100]}"
                )
        return "\n\n".join(parts).strip() if len(parts) > 2 else None
    except Exception as e:
        log.warning("Tavily live search failed: %s", e)
        return None


async def openai_live_web_search(user_text: str) -> str | None:
    """
    Fallback через OpenAI Responses API + web search.
    Работает только с официальным OpenAI API key, не с OpenRouter sk-or-*.
    """
    api_key = (OPENAI_API_KEY or "").strip()
    if not api_key or api_key.startswith("sk-or-") or not LIVE_SEARCH_ENABLED:
        return None
    system_text = (
        "Ты live-поисковый помощник внутри Telegram-бота Neyro-Bot GPT 5 Studio. "
        + _current_date_system_text() + " "
        "Отвечай по-русски, кратко и по делу. Если вопрос требует свежих данных, используй веб-поиск. "
        "Для запросов со словом «сегодня» принимай только материалы, которые явно относятся к текущей дате. "
        "Если подтверждений за текущую дату нет, так и скажи; старые события не выдавай за сегодняшние. "
        "В начале ответа укажи 'Актуально на <текущая дата и время>'. В конце дай источники."
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
    Возвращает True, если вопрос обработан live-слоем.
    v34.9: не подмешивает всю историю в каждый короткий запрос, чтобы бот не залипал на BTC.
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

    # Общие вопросы о возможностях должны идти в capability/GPT, а не в live-курс из памяти.
    if _is_general_capability_query(original_text):
        return False

    contextual_text, contextual_pair = _crypto_contextual_text(user_id, chat_id, original_text)

    # 1) Прогноз по крипте: отдельная ветка. Нельзя отвечать только текущим курсом.
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
        # Если LLM/данные не сработали — пойдём в live-поиск ниже.

    # 2) Чистый запрос курса: только когда пользователь действительно спрашивает курс/цену,
    # а не прогноз/рост/падение.
    if _is_crypto_rate_query(original_text) and not FORECAST_RE.search(original_text):
        answer = await get_crypto_rate_text(original_text)
        if answer:
            await update.effective_message.reply_text(answer, disable_web_page_preview=True)
            _chat_memory_add(user_id, chat_id, "user", original_text)
            _chat_memory_add(user_id, chat_id, "assistant", answer)
            with contextlib.suppress(Exception):
                await maybe_tts_reply(update, context, answer[:TTS_MAX_CHARS])
            return True

    # 3) Follow-up без названия актива: «а сколько сейчас?», когда в памяти обсуждался BTC.
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

    # Основной вариант: Tavily даёт свежие источники, LLM формирует ответ.
    ctx = await _tavily_live_search_context(text)
    if ctx:
        date_meta = _current_date_meta()
        prompt = (
            f"{_current_date_system_text()} "
            "Ответь на вопрос пользователя только на основе веб-контекста ниже. "
            "Если пользователь спрашивает про сегодня, события должны быть подтверждены именно для текущей даты. "
            "Не превращай дату публикации старой статьи в сегодняшнюю дату. "
            "Если контекст содержит только более старые материалы, прямо напиши: "
            f"«Надёжных подтверждений за {date_meta['ru']} в найденных источниках нет», "
            "а затем при необходимости укажи последнюю найденную информацию с её точной датой. "
            "Не говори про устаревшую базу знаний. Если данных недостаточно — честно укажи это. "
            "Учитывай историю диалога, только если вопрос действительно является продолжением. "
            "В начале ответа напиши строку 'Актуально на <дата, время и часовой пояс>'. "
            "В конце добавь короткий блок 'Источники' со ссылками из контекста.\n\n"
            f"Вопрос: {_live_search_query_with_date(text)}"
        )
        try:
            reply = await ask_openai_text(prompt, web_ctx=ctx, user_id=user_id, chat_id=chat_id)
            if reply:
                # Последний страховочный барьер: если модель всё же назвала старую дату «сегодня»,
                # один раз заставляем её пересобрать ответ с точной датой сервиса.
                if LIVE_SEARCH_DATE_GUARD and _has_wrong_today_date(reply):
                    log.warning("Live answer date mismatch detected; regenerating with strict date guard")
                    correction_prompt = (
                        f"Предыдущий черновик ошибочно назвал старую дату сегодняшней. {_current_date_system_text()} "
                        "Пересобери ответ с нуля по тому же веб-контексту. Не утверждай, что событие произошло сегодня, "
                        "если источник явно не относится к текущей дате. Если подтверждений за сегодня нет — скажи это прямо.\n\n"
                        f"Вопрос: {_live_search_query_with_date(text)}"
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
    # v83: при покупке подписки начисляем месячный пакет кредитов.
    try:
        _grant_subscription_credits(user_id, tier, months)
    except NameError:
        # Функция объявляется ниже; если модуль ещё инициализируется, кредит можно начислить в платежном обработчике.
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
    # миграции
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


# ───────── DB: до четырёх виртуальных чатов пользователя ─────────
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
    t = re.sub(r"^(?:создай|сделай|напиши|объясни|помоги)\s+", "", t, flags=re.I)
    return (t[:46].rstrip(" ,.;:—-") or "Новый чат")


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
    return [{"id": int(r[0]), "title": r[1] or "Чат", "created_ts": int(r[2]), "updated_ts": int(r[3]), "messages": int(r[4]), "active": int(r[0]) == active_id} for r in rows]


def _chat_create(user_id: int, telegram_chat_id: int, title: str = "Новый чат") -> tuple[int | None, str]:
    _chat_memory_init()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("BEGIN IMMEDIATE")
    cur.execute("SELECT COUNT(*) FROM ai_chats WHERE user_id=? AND telegram_chat_id=?", (int(user_id), int(telegram_chat_id)))
    count = int((cur.fetchone() or [0])[0])
    if count >= CHAT_MAX_CONVERSATIONS:
        con.rollback(); con.close()
        return None, f"Достигнут лимит: {CHAT_MAX_CONVERSATIONS} чата. Удалите один из старых чатов."
    now = int(time.time())
    cur.execute("INSERT INTO ai_chats(user_id, telegram_chat_id, title, created_ts, updated_ts) VALUES (?,?,?,?,?)", (int(user_id), int(telegram_chat_id), (title or "Новый чат")[:60], now, now))
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
    cur.execute("INSERT INTO ai_chats(user_id, telegram_chat_id, title, created_ts, updated_ts) VALUES (?,?,?,?,?)", (int(user_id), int(telegram_chat_id), "Основной чат", now, now))
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
            if row and int(row[1] or 0) == 1 and (row[0] or "") in ("Новый чат", "Основной чат"):
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
        who = "Пользователь" if m.get("role") == "user" else "Бот"
        parts.append(f"{who}: {m.get('content','')}")
    return "\n".join(parts).strip()


def _chat_memory_followup_query(user_id: int | None, chat_id: int | None, text: str) -> str:
    t = (text or "").strip()
    if not CHAT_MEMORY_ENABLED or not t or len(t) > 80 or _is_general_capability_query(t):
        return t
    is_short_followup = bool(re.fullmatch(r"[\wа-яА-ЯёЁ\-\s]{1,40}", t) and re.search(r"(биткоин|btc|эфир|eth|solana|sol|ton|bnb|месяц|недел|рост|паден|прогноз|курс|цена|да|нет|его|по нему)", t, re.I))
    if not is_short_followup: return t
    ctx = _chat_memory_context_text(user_id, chat_id, limit=8)
    if not ctx or not re.search(r"(прогноз|рост|паден|курс|цена|актив|рынок|крипто|btc|биткоин|bitcoin|уточн|о каком)", ctx, re.I): return t
    return "С учётом предыдущего диалога продолжи незавершённую задачу.\nПоследние сообщения:\n" + ctx + "\nТекущий ответ пользователя: " + t


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

# ───────── Лимиты/цены ─────────
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
        return f"{int(round(cr))} кр."
    return f"{cr:.1f} кр."


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
    if engine == "veo":
        return round(((int(duration_s or 8) + 7) // 8) * 8 * VEO_FAST_COST_PER_SECOND_USD, 4)
    if engine == "sora":
        per_s = SORA_PRO_COST_PER_SECOND_USD if "pro" in (SORA_MODEL or "").lower() else SORA_COST_PER_SECOND_USD
        return round(max(1, d) * per_s, 4)
    if engine == "seedance":
        return round(max(4, min(30, int(duration_s or 10))) * SEEDANCE_COST_PER_SECOND_USD, 4)
    if engine == "kling":
        return round(KLING_5S_COST_USD * (max(1, (int(duration_s or 5) + 4) // 5) if int(duration_s or 5) > 10 else (2 if d >= 10 else 1)), 4)
    if engine == "runway":
        return round(max(2, d) * RUNWAY_COST_PER_SECOND_USD, 4)
    return max(0.0, float(TEXT_VIDEO_UNIT_COST_USD or 0.0))


def _veo_24s_provider_cost_usd() -> float:
    """Known provider estimate for 3 Veo scenes + 3 lip-sync jobs + one 24s TTS."""
    return round(
        _video_provider_cost_usd("veo", 24)
        + 3 * VEO_24S_KLING_LIPSYNC_COST_USD
        + (24.0 / 60.0) * VEO_24S_TTS_COST_PER_MINUTE_USD,
        4,
    )


def _veo_24s_cost_breakdown_usd() -> tuple[float, float, float, float]:
    veo = _video_provider_cost_usd("veo", 24)
    lipsync = round(3 * VEO_24S_KLING_LIPSYNC_COST_USD, 4)
    tts = round((24.0 / 60.0) * VEO_24S_TTS_COST_PER_MINUTE_USD, 4)
    return veo, lipsync, tts, round(veo + lipsync + tts, 4)


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

# Бесплатный дневной пакет для входа в продукт.
# Работает только для FREE-пользователей: 10 текстовых запросов,
# 1 генерация изображения и 1 обработка фото в день.
FREE_TEXT_PER_DAY = int(os.environ.get("FREE_TEXT_PER_DAY", "10") or 10)
FREE_IMAGE_GENERATIONS_PER_DAY = int(os.environ.get("FREE_IMAGE_GENERATIONS_PER_DAY", "1") or 1)
FREE_IMAGE_PROCESSINGS_PER_DAY = int(os.environ.get("FREE_IMAGE_PROCESSINGS_PER_DAY", "1") or 1)

# DEMO: free даёт попробовать ключевые движки
LIMITS = {
    # В v83 тяжёлые функции оплачиваются кредитами из единого баланса.
    # Подписка даёт доступ + месячный пакет кредитов, а не опасный безлимит видео.
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
    """Возвращает тип бесплатного дневного действия для FREE-пользователя."""
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
    return "генерация картинки" if kind == "image_generation" else "обработка фото"


def _try_consume_free_daily_quota(user_id: int, username: str | None, kind: str) -> tuple[bool, int, int]:
    """Пробует списать бесплатное дневное действие. Возвращает ok, осталось_после, лимит."""
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
        f"Бесплатный дневной лимит на действие «{label}» уже использован. "
        "Чтобы продолжить сегодня — подключите тариф или пополните кредиты.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
             [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
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

# ───────── Prompts ─────────
SYSTEM_PROMPT = (
    "Ты — Neyro-Bot GPT 5 Studio внутри Telegram. Отвечай на русском, по сути и без лишней воды. "
    "Ты не обычный изолированный GPT-чат: ты знаешь функции этого бота и должен отвечать с учётом доступных режимов. "
    "Доступные возможности бота: GPT-чат и логика, работа с PDF/DOCX/EPUB/FB2/TXT, анализ фото и скриншотов, "
    "режимы Учёба, Работа/Бизнес, Развлечения, Медицина, Движки, OpenAI Images, Midjourney, Runway, Sora 2, Kling, Suno, "
    "Deepgram/OpenAI STT/TTS, Tavily/live-поиск, Photoroom для удаления/замены фона, PiAPI и Segmind для FaceSwap, "
    "удаление водяных знаков/надписей, ретушь, outpaint/расширение кадра, раскадровка, Reels/Shorts, мини-фильмы, создание презентаций, PDF-каталогов, логотипов и музыки. "
    "Если пользователь спрашивает, умеешь ли ты заменить лицо, удалить фон, заменить фон, оживить фото, сделать видео, "
    "распознать голос, озвучить ответ, обработать PDF или фото — отвечай утвердительно и объясняй точный путь в меню. "
    "Не отказывайся от функций, которые есть в боте. Для замены лица объясняй: загрузить фото → нажать 🔥 Развлечения → 🎭 Замена лица на фото "
    "или после загрузки фото нажать кнопку 🎭 Замена лица; если лиц несколько, бот показывает номера и даёт выбрать целевое лицо. "
    "Для удаления/замены фона: 🔥 Развлечения → 🧼 Удалить фон на фото или 🖼 Заменить фон на фото. "
    "Для оживления фото: 🔥 Развлечения → 🪄 Оживить фото, затем выбрать Runway/Kling/Sora 2 без людей. "
    "Сохраняй контекст беседы: если пользователь отвечает коротко на твой уточняющий вопрос, продолжай предыдущую задачу, "
    "а не начинай новую справку. Например, если ранее обсуждался прогноз BTC, ответ 'биткоин' означает Bitcoin/BTC в предыдущем вопросе. "
    "Не давай определение термину, если из истории понятно, что пользователь уточняет предыдущую задачу. "
    "Если нужны актуальные данные, говори, что используешь live-поиск/источники, а не устаревшие знания. "
    "По медицинским документам помогай с разбором, структурированием и вопросами к врачу, но ясно указывай, что это не диагноз и не замена очной консультации. "
    "Не выдумывай факты; если данных недостаточно, задай короткий уточняющий вопрос."
)
VISION_SYSTEM_PROMPT = (
    "Ты чётко описываешь содержимое изображений: объекты, текст, схемы, графики. "
    "Не идентифицируй личности людей и не пиши имена, если они не напечатаны на изображении. "
    "Если изображение медицинское, делай только справочный разбор видимого текста/признаков, "
    "не ставь диагноз и напоминай, что нужен врач и официальный протокол."
)

HELP_TEXT = globals().get("HELP_TEXT") or (
    "Команды: /start, /chats, /newchat, /engines, /plans, /balance, /prices, /img <описание>, /mj <описание>, /voice_on, /voice_off, /diag_video, /diag_bg, /diag_face.\n"
    "Основные режимы: 🎓 Учёба, 💼 Работа/Бизнес, 🔥 Развлечения, 🩺 Медицина, 🧠 Движки, 💳 Баланс.\n"
    "Фото/бизнес: оживление через Runway/Kling/Sora 2 без людей, говорящий аватар, фото→видеоклип, замена лица, удаление/замена фона, удаление водяного знака/надписи, расширение кадра, раскадровка, анализ фото, логотипы, презентации и PDF-каталоги.\n"
    "Документы, голос и музыка: PDF/EPUB/DOCX/TXT/FB2, сводки, конспекты, таблицы, речь ↔ текст, озвучка, песни/минусовки Suno.\n"
    "Медицина: справочный разбор выписок, заключений, анализов, снимков, МРТ/КТ. Это не диагноз и не замена врачу."
)
EXAMPLES_TEXT = globals().get("EXAMPLES_TEXT") or (
    "Примеры:\n"
    "• Оживи фото: лёгкая улыбка, взгляд в камеру, плавное движение камеры, 5 секунд, 9:16\n"
    "• Говорящий аватар: загрузи портрет, нажми 🗣 и пришли текст/voice/audio для речи\n"
    "• Фото в видеоклип: загрузи фото, нажми 🎵 и опиши стиль клипа/музыки, 5 секунд, 9:16\n"
    "• Сделай видео: вилла на берегу моря на Самуи, закат, 10 секунд, 16:9\n"
    "• /img luxury villa in Koh Samui, tropical, cinematic"
)

# ───────── Heuristics / intent ─────────
_SMALLTALK_RE = re.compile(r"^(привет|здравствуй|добрый\s*(день|вечер|утро)|хи|hi|hello|как дела|спасибо|пока)\b", re.I)
_NEWSY_RE     = re.compile(r"(когда|дата|выйдет|релиз|новост|курс|цена|прогноз|найди|официал|погода|сегодня|тренд|адрес|телефон)", re.I)
_CAPABILITY_RE = re.compile(r"(мож(ешь|но|ете)|уме(ешь|ете)|способен|может\s+ли).{0,80}(анализ|распозн|читать|созда(ва)?т|дела(ть)?|ожив|анимир).{0,80}(фото|фотограф|картинк|изображен|pdf|docx|epub|fb2|аудио|книг|видео)", re.I)

_IMG_WORDS = r"(картин\w+|изображен\w+|фото\w*|рисунк\w+|логотип\w*|лого\b|эмблем\w+|бренд\w+|фирменн\w+|image|picture|img\b|logo|banner|poster|brand|emblem)"
_VID_WORDS = r"(видео|ролик\w*|анимаци\w*|shorts?|reels?|clip|video|vid\b)"


_PEOPLE_PROMPT_RE = re.compile(
    r"\b(человек|люди|мужчин\w*|женщин\w*|девушк\w*|парн\w*|реб[её]нок|дет\w*|"
    r"дворник\w*|полицейск\w*|солдат\w*|врач\w*|акт[её]р\w*|пев[её]ц\w*|персонаж\w*|"
    r"лицо|портрет|селфи|human|person|people|man|woman|girl|boy|child|children|actor|singer|worker|janitor)\b",
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

_CREATE_CMD = r"(сдела(й|йте|ть)|созда(й|йте|ть)|сгенериру(й|йте)|нарису(й|йте)|нужно\s+сделать|хочу\s+создать|render|generate|create|make)"
_PREFIXES_VIDEO = [r"^" + _CREATE_CMD + r"\s+видео", r"^video\b", r"^reels?\b", r"^shorts?\b"]
_PREFIXES_IMAGE = [r"^" + _CREATE_CMD + r"\s+(?:картин\w+|изображен\w+|фото\w+|рисунк\w+|логотип\w*|лого\b|эмблем\w+|бренд\w+|фирменн\w+)", r"^image\b", r"^picture\b", r"^img\b"]

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
    Универсальный запрос к LLM:
    - поддерживает OpenRouter (через OPENAI_API_KEY = sk-or-...);
    - принудительно шлёт JSON в UTF-8, чтобы не было ascii-ошибок;
    - логирует HTTP-статус и тело ошибки в Render-логи;
    - делает до 3 попыток с небольшой паузой.
    """
    user_text = (user_text or "").strip()
    if not user_text:
        return "Пустой запрос."

    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + _current_date_system_text()}]
    if extra_system:
        messages.append({"role": "system", "content": str(extra_system)[:3000]})
    if web_ctx:
        messages.append({
            "role": "system",
            "content": f"Контекст из веб-поиска:\n{web_ctx}",
        })

    # Короткая память диалога: последние сообщения пользователя и бота.
    # Это позволяет понимать ответы вроде «биткоин» как продолжение предыдущего вопроса,
    # а не начинать новую справку с определения термина.
    if CHAT_MEMORY_ENABLED and user_id and chat_id:
        messages.extend(_chat_memory_recent(user_id, chat_id, CHAT_MEMORY_MAX_MESSAGES))

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
        r = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=15.0)) as client:
                    r = client.post(url, headers=headers, json=payload)
                r.raise_for_status()
                break
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError) as exc:
                log.warning("TTS transient transport failure attempt %s/3: %s", attempt + 1, type(exc).__name__)
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        data = r.content if r is not None and r.content else None
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
        audio = await asyncio.to_thread(_tts_bytes_sync, text, "opus")
        if not audio:
            with contextlib.suppress(Exception):
                await update.effective_message.reply_text("🔇 Не удалось синтезировать голос.")
            return
        bio = BytesIO(audio); bio.seek(0); bio.name = "say.ogg"
        await update.effective_message.reply_voice(voice=InputFile(bio), caption=(text if TTS_VOICE_CAPTION else None))
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


def _normalize_vocal_source_audio_sync(raw: bytes, filename: str) -> bytes:
    """Keep MP3 untouched; transcode other Telegram audio to a safe MP3 source."""
    if not 512 <= len(raw or b"") <= 50 * 1024 * 1024:
        raise ValueError("audio size is outside the 512 B–50 MB limit")
    if str(filename or "").lower().endswith(".mp3"):
        return raw
    suffix = os.path.splitext(str(filename or "audio.bin"))[1].lower() or ".bin"
    with tempfile.TemporaryDirectory(prefix="neyro_vocal_source_") as td:
        source_path = os.path.join(td, "source" + suffix)
        output_path = os.path.join(td, "source.mp3")
        with open(source_path, "wb") as fh:
            fh.write(raw)
        completed = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", source_path,
                "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "44100",
                "-c:a", "libmp3lame", "-b:a", "192k", output_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0 or not os.path.isfile(output_path):
            raise RuntimeError("ffmpeg could not normalize the uploaded audio")
        with open(output_path, "rb") as fh:
            normalized = fh.read()
    if not 512 <= len(normalized) <= 50 * 1024 * 1024:
        raise RuntimeError("normalized audio size is invalid")
    return normalized

# ───────── Хендлер голосовых/аудио ───────…182152 tokens truncated…= _looks_like_screenshot_or_bad_i2v_source(img_bytes)
    if bad_src_note and I2V_WARN_BAD_SOURCE:
        with contextlib.suppress(Exception):
            if I2V_BAD_SOURCE_POLICY == "ask_clean":
                await update.effective_message.reply_text("ℹ️ " + bad_src_note + "\n\nПришлите чистое фото, чтобы получить стабильный результат.")
                return False
            await update.effective_message.reply_text("ℹ️ " + bad_src_note + "\nПродолжаю обработку, но качество может быть хуже.")

    # v88: официальный Runway Developer API — основной маршрут.
    context.user_data.pop("_runway_direct_hard_stop", None)
    if RUNWAY_DIRECT_FIRST and RUNWAY_DIRECT_ENABLED and RUNWAY_API_KEY:
        try:
            if await _run_runway_direct_animate_photo(update, context, img_bytes, prompt, seconds, aspect):
                _provider_mark_success("runway_direct")
                return True
            if context.user_data.pop("_runway_direct_hard_stop", False):
                return False
            _provider_mark_failure("runway_direct", _provider_last_error.get("runway_direct", "direct i2v failed"))
        except Exception as e:
            _provider_mark_failure("runway_direct", str(e))
            log.warning("Runway direct i2v failed; trying Comet: %s", e)

    # Comet is only a fallback; its Runway distributor channel can disappear independently.
    try:
        if await _run_runway_comet_animate_photo(update, context, img_bytes, prompt, seconds, aspect):
            return True
    except Exception as e:
        log.warning("Runway Comet route failed: %s", e)

    if (not RUNWAY_DIRECT_FIRST) and RUNWAY_DIRECT_ENABLED and RUNWAY_API_KEY:
        try:
            if await _run_runway_direct_animate_photo(update, context, img_bytes, prompt, seconds, aspect):
                _provider_mark_success("runway_direct")
                return True
            if context.user_data.pop("_runway_direct_hard_stop", False):
                return False
        except Exception as e:
            _provider_mark_failure("runway_direct", str(e))
            log.warning("Runway direct fallback failed: %s", e)

    if RUNWAY_AUTO_FALLBACK_KLING and COMET_API_KEY:
        await update.effective_message.reply_text(RUNWAY_PUBLIC_FALLBACK_TEXT)
        return bool(await _run_comet_i2v(update, context, "kling", img_bytes, prompt, seconds, aspect))

    if RUNWAY_API_KEY:
        await update.effective_message.reply_text("⚠️ Официальный Runway не принял задачу. Проверьте RUNWAYML_API_SECRET (Environment/Secret File) и API-кредиты: /diag_runway auth")
    else:
        await update.effective_message.reply_text("⚠️ Для постоянного доступа к Runway добавьте RUNWAYML_API_SECRET в Render Secret File runway.env или Environment.")
    return False

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
            await update.effective_message.reply_text(f"✅ Подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')}.\n🪙 Кредиты начислены: {SUBSCRIPTION_CREDITS.get((tier or '').lower(), 0) * int(months)} кр.")
            return

        if payload.startswith("topup:"):
            try:
                _, credits_s, rub_s = payload.split(":", 2)
                resolved = _credit_pack_resolve(int(credits_s), int(rub_s))
                if resolved:
                    credits, expected_rub = resolved
                    _wallet_total_add(uid, _credits_to_usd(credits))
                    await update.effective_message.reply_text(
                        f"✅ Оплата прошла успешно. Начислено: {credits} кредитов за {expected_rub} ₽."
                    )
                    return
            except Exception:
                log.exception("Failed to parse topup payload: %s", payload)

        # Любое иное payload — пополнение единого кошелька
        usd = _credits_to_usd(rub)
        _wallet_total_add(uid, usd)
        await update.effective_message.reply_text(f"💳 Пополнение: {rub:.0f} ₽. Начислено: {_credits_fmt_from_usd(usd)}.")
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
                        text=f"✅ CryptoBot: платёж подтверждён. Начислено: {_credits_fmt_from_usd(float(usd_amount))}.")
                return
            if st in ("expired", "cancelled", "canceled", "failed"):
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                        text=f"❌ CryptoBot: платёж не завершён (статус: {st}).")
                return
            await asyncio.sleep(6.0)
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                text="⌛ CryptoBot: время ожидания вышло. Нажмите «🔎 Проверить» позже.")
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
                             f"Подписка {tier.upper()} активна до {until.strftime('%Y-%m-%d')}.\n🪙 Кредиты начислены: {SUBSCRIPTION_CREDITS.get((tier or '').lower(), 0) * int(months)} кр."
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
                text="⌛ CryptoBot: время ожидания вышло. Нажмите «🔎 Проверить» или оплатите заново."
            )
    except Exception as e:
        log.exception("crypto poll (subscription) error: %s", e)


# ───────── Предложение пополнения ─────────
async def _send_topup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # v83: пользователю показываем кредиты, внутри legacy-баланс хранится в техническом эквиваленте.
    small_cr = int(os.environ.get("CREDIT_PACK_SMALL_CREDITS", "1000") or 1000)
    mid_cr = int(os.environ.get("CREDIT_PACK_MID_CREDITS", "3000") or 3000)
    big_cr = int(os.environ.get("CREDIT_PACK_BIG_CREDITS", "7000") or 7000)
    small_rub = int(os.environ.get("CREDIT_PACK_SMALL_RUB", "990") or 990)
    mid_rub = int(os.environ.get("CREDIT_PACK_MID_RUB", "2790") or 2790)
    big_rub = int(os.environ.get("CREDIT_PACK_BIG_RUB", "6290") or 6290)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{small_cr} кр. • {small_rub} ₽", callback_data=f"topup:rub:{small_rub}"),
         InlineKeyboardButton(f"{mid_cr} кр. • {mid_rub} ₽", callback_data=f"topup:rub:{mid_rub}")],
        [InlineKeyboardButton(f"{big_cr} кр. • {big_rub} ₽", callback_data=f"topup:rub:{big_rub}")],
        [InlineKeyboardButton(f"Crypto ~{small_cr} кр.", callback_data=f"topup:crypto:{_credits_to_usd(small_cr):.2f}"),
         InlineKeyboardButton(f"Crypto ~{mid_cr} кр.", callback_data=f"topup:crypto:{_credits_to_usd(mid_cr):.2f}")],
    ])
    await update.effective_message.reply_text(
        "🪙 Кредиты используются для тяжёлых функций: видео, музыка, AI-фото, FaceSwap, говорящий аватар и премиум-рендеры.\n"
        "1 кредит = 1 ₽. Выберите пакет:",
        reply_markup=kb,
    )


# ───────── Промо-квоты по функциям ─────────
def _promo_feature_key(engine: str, remember_kind: str = "") -> str:
    rk = (remember_kind or "").strip().lower()
    eng = (engine or "").strip().lower()
    if "vocal" in rk and ("clip" in rk or "lipsync" in rk):
        return "vocal_lipsync_clip"
    if "photo_music_clip" in rk or "photo_clip" in rk:
        return "photo_music_clip"
    if "talking_avatar" in rk or "avatar" in rk:
        return "talking_avatar"
    if rk.startswith("text_video") or rk.startswith("video_"):
        return rk
    if "revive_photo" in rk:
        return rk
    if "suno" in rk:
        return "suno_music"
    if "business_logo" in rk or "logo" in rk:
        return "business_logo"
    if "faceswap" in rk or "face_swap" in rk:
        return "faceswap"
    if "ai_selfie" in rk:
        return "ai_selfie"
    if "removebg" in rk or "remove_background" in rk:
        return "remove_background"
    if "replacebg" in rk or "replace_background" in rk:
        return "replace_background"
    if "outpaint" in rk:
        return "outpaint"
    if "image_retouch" in rk or "retouch" in rk:
        return "image_retouch"
    if "img_generate" in rk or "image_generate" in rk or eng == "img":
        return "image_generation"
    return rk or eng or "function"

def _promo_quota_kv_key(user_id: int, feature: str, ymd: str | None = None) -> str:
    safe = re.sub(r"[^a-z0-9_\-]+", "_", (feature or "function").lower())[:80]
    return f"promo5:{user_id}:{ymd or _today_ymd()}:{safe}"

def _try_consume_promo_daily5_quota(user_id: int, username: str | None, engine: str, remember_kind: str = "") -> tuple[bool, int, int, str]:
    if not is_promo_daily5_user(user_id, username):
        return False, 0, PROMO_DAILY5_PER_FUNCTION_LIMIT, ""
    feature = _promo_feature_key(engine, remember_kind)
    limit = max(0, int(PROMO_DAILY5_PER_FUNCTION_LIMIT))
    if limit <= 0:
        return False, 0, limit, feature
    key = _promo_quota_kv_key(user_id, feature)
    used = int(kv_get(key, "0") or "0")
    if used >= limit:
        return False, 0, limit, feature
    kv_set(key, str(used + 1))
    return True, max(0, limit - used - 1), limit, feature


# ───────── Попытка оплатить → выполнить ─────────
async def _try_pay_then_do(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    engine: str,
    est_cost_usd: float,
    coro_func,
    remember_kind: str = "",
    remember_payload: dict | None = None,
    silent_failure: bool = False,
):
    """Reserve capacity, run provider, and charge only after the action explicitly returns True."""
    username = (update.effective_user.username or "")

    promo_ok, promo_left, promo_limit, promo_feature = _try_consume_promo_daily5_quota(user_id, username, engine, remember_kind)
    if promo_ok:
        try:
            with contextlib.suppress(Exception):
                await update.effective_message.reply_text(f"🎁 Промо-доступ: функция «{promo_feature}». Осталось сегодня: {promo_left}/{promo_limit}.")
            result = await coro_func()
            if result is False:
                raise RuntimeError("provider returned unsuccessful result")
        except Exception as e:
            log.exception("promo daily5 action failed: %s", e)
            if not silent_failure:
                await update.effective_message.reply_text("❌ Задача не выполнена. Промо-кредиты не списываются.")
        return
    if is_promo_daily5_user(user_id, username) and promo_feature:
        await update.effective_message.reply_text(f"Промо-лимит на функцию «{promo_feature}» сегодня исчерпан: {promo_limit}/{promo_limit}. GPT-чат остаётся безлимитным.")
        return

    free_kind = _free_quota_category(engine, remember_kind)
    if free_kind and get_subscription_tier(user_id) == "free" and not is_unlimited(user_id, username):
        q_ok, q_left, q_limit = _try_consume_free_daily_quota(user_id, username, free_kind)
        if q_ok:
            try:
                with contextlib.suppress(Exception): await update.effective_message.reply_text(f"🎁 Бесплатное действие: {_free_quota_label(free_kind)}. Осталось сегодня: {q_left}/{q_limit}.")
                result = await coro_func()
                if result is False: raise RuntimeError("provider returned unsuccessful result")
            except Exception as e:
                log.exception("free action failed: %s", e)
                if not silent_failure:
                    await update.effective_message.reply_text("❌ Задача не выполнена. Денежного списания не было.")
            return
        await _send_free_quota_exhausted(update, context, free_kind); return

    if is_unlimited(user_id, username):
        try:
            result = await coro_func()
            if result is False: raise RuntimeError("provider returned unsuccessful result")
        except Exception as e:
            log.exception("unlimited action failed: %s", e)
            if not silent_failure:
                await update.effective_message.reply_text("❌ Задача не выполнена. Попробуйте позже.")
        return

    provider_cost = max(0.0, float(est_cost_usd or 0.0))
    retail_usd = _retail_usd(provider_cost)
    price_credits = _retail_credits(provider_cost)
    tx_id = None
    try:
        tx_id, available_before = _credit_reserve(user_id, engine, remember_kind or engine, provider_cost, retail_usd, remember_payload)
    except Exception as e:
        log.exception("credit reserve failed: %s", e)
        await update.effective_message.reply_text("❌ Не удалось проверить кредитный баланс. Попробуйте ещё раз.")
        return

    if not tx_id:
        available_cr = int(round(_usd_to_credits(available_before)))
        missing_cr = max(0, price_credits - available_cr)
        await update.effective_message.reply_text(
            f"Недостаточно кредитов. Стоимость: {price_credits} кр. Доступно: {available_cr} кр. Не хватает: {missing_cr} кр.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],[InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]])
        )
        return

    after_cr = max(0, int(round(_usd_to_credits(available_before - retail_usd))))
    with contextlib.suppress(Exception):
        await update.effective_message.reply_text(f"🪙 Стоимость: {price_credits} кр. Списание произойдёт только после успешного результата. После выполнения останется: {after_cr} кр.")

    try:
        result = await coro_func()
        if result is not True:
            _credit_release(tx_id, "released")
            if not silent_failure:
                await update.effective_message.reply_text("↩️ Генерация не завершилась — кредиты не списаны.")
            return
        if not _credit_commit(tx_id):
            _credit_release(tx_id, "released")
            await update.effective_message.reply_text("⚠️ Результат получен, но списание не зафиксировано. Обратитесь в поддержку, повторно запускать оплату не нужно.")
            return
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text(f"✅ Списано: {price_credits} кр.")
    except Exception as e:
        _credit_release(tx_id, "released")
        log.exception("paid action failed: %s", e)
        if not silent_failure:
            await update.effective_message.reply_text("❌ Задача не выполнена. Кредиты не списаны.")


async def cmd_diag_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user else 0
    username = user.username if user else ""
    await update.effective_message.reply_text(
        "🔐 Access diagnostic\n"
        f"user_id: {user_id}\n"
        f"username: @{username or '-'}\n"
        f"unlimited: {is_unlimited(user_id, username)}\n"
        f"promo_unlim_gpt: {is_promo_unlim_gpt(user_id, username)}\n"
        f"promo_daily5: {is_promo_daily5_user(user_id, username)}\n"
        f"promo_limit_per_function: {PROMO_DAILY5_PER_FUNCTION_LIMIT}"
    )

# ───────── /plans ─────────
async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["⭐ Тарифы и кредиты:", "Подписка открывает доступ, кредиты расходуются на тяжёлые генерации."]
    for tier, terms in PLAN_PRICE_TABLE.items():
        lines.append(f"— {tier.upper()}: "
                     f"{terms['month']}₽/мес • {terms['quarter']}₽/квартал • {terms['year']}₽/год • {SUBSCRIPTION_CREDITS.get(tier,0)} кр./мес")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("START 1 мес",    callback_data="buy:start:1"),
         InlineKeyboardButton("PRO 1 мес",      callback_data="buy:pro:1")],
        [InlineKeyboardButton("ULTIMATE 1 мес", callback_data="buy:ultimate:1")],
        [InlineKeyboardButton("Мини-витрина",    web_app=WebAppInfo(url=TARIFF_URL))]
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

    # Studio prompt edit is an explicit one-message draft workflow; no provider call.
    if context.user_data.get("studio_prompt_awaiting_edit"):
        from neyrobot_prod.studio_prompt_handlers import receive_prompt_draft
        if await receive_prompt_draft(update, context, text):
            return

    # Idempotency guard: the priority Presentation Studio handler may already own this update.
    with contextlib.suppress(Exception):
        if context.chat_data.get("_presentation_last_update_token") == _presentation_update_token(update):
            return

    # Rename virtual chat before routing the message to GPT.
    rename_cid = context.user_data.pop("awaiting_chat_rename", None)
    if rename_cid:
        if _chat_rename(update.effective_user.id, update.effective_chat.id, int(rename_cid), text):
            await update.effective_message.reply_text("✅ Название чата обновлено.", reply_markup=_chat_list_kb(update.effective_user.id, update.effective_chat.id))
        else:
            await update.effective_message.reply_text("Не удалось переименовать чат.")
        return

    if context.user_data.pop("awaiting_midjourney_prompt", None):
        await _start_midjourney_image(update, context, text)
        return

    # Active presentation/catalog project has absolute priority over generic GPT/live-search routing.
    _studio = _presentation_studio_get()
    if await _studio.handle_text(update, context, text):
        return
    # When a project is active but the current stage expects a button/upload rather than free text,
    # never pass the same message to generic GPT or live-search.
    _active_presentation = _studio._active_project(update.effective_user.id, update.effective_chat.id)
    if _active_presentation:
        await update.effective_message.reply_text(
            "Проект презентации активен. На этом этапе используйте кнопки мастера или нажмите «Продолжить»."
        )
        return

    # Keep music-video revisions in the same mode; never send a draft to generic chat.
    draft = context.user_data.get("music_video_draft")
    if draft:
        edit = context.user_data.get("music_video_draft_edit")
        if edit in ("augment", "rewrite", "voice_rewrite"):
            current_duration = int(draft.get("duration") or _photo_clip_target_duration(draft["video_brief"]))
            selected_duration = current_duration if draft.get("duration_locked") else None
            if edit == "augment":
                prompt = _merge_music_video_prompt(draft["prompt"], text)
                await _stage_music_video_draft(
                    update, context, prompt, selected_duration_s=selected_duration
                )
            elif edit == "rewrite":
                await _stage_music_video_draft(
                    update, context, text, selected_duration_s=selected_duration
                )
            else:
                generated = await ask_openai_text(
                    "Преобразуй голосовое описание пользователя в два профессиональных промпта. Сохрани его замысел. "
                    f"Видео ровно {current_duration} секунд; VIDEO_BRIEF разбей по 10 секунд с continuity и START/END states. "
                    "MUSIC_BRIEF оптимизируй для Suno. Верни строго [MUSIC_BRIEF] затем [VIDEO_BRIEF].\n\nОписание: " + text,
                    user_id=update.effective_user.id, chat_id=update.effective_chat.id,
                    extra_system="Ты prompt-director AI music video. Не выдумывай сюжетные факты сверх голосового описания."
                )
                await _stage_music_video_draft(
                    update, context, generated, selected_duration_s=selected_duration
                )
        
        else:
            await update.effective_message.reply_text(
                "Сценарий ожидает решения. Нажмите «Утверждаю», «Дополнить» или «Написать заново».",
                reply_markup=_music_video_approval_kb(draft["token"]),
            )
        return

    # Вопросы о FaceSwap должны отвечать описанием функции, а не сразу запускать режим.
    if re.search(r"(мож(ешь|ете|но)|уме(ешь|ете)|способен|поддерживаешь|делаешь|может\s+ли)", text or "", re.I) and re.search(r"(лиц|лица|лицо|face|faceswap)", text or "", re.I):
        cap_early = capability_answer(text)
        if cap_early:
            await update.effective_message.reply_text(cap_early, reply_markup=main_kb)
            with contextlib.suppress(Exception):
                _chat_memory_add(update.effective_user.id, update.effective_chat.id, "user", text)
                _chat_memory_add(update.effective_user.id, update.effective_chat.id, "assistant", cap_early)
            return

    # Замена лица: отдельный двухшаговый режим.
    if _is_face_swap_request(text):
        _clear_medicine_wait(context)
        with contextlib.suppress(Exception):
            _mode_track_set(update.effective_user.id, "")
        await _start_faceswap_flow(update, context, None, use_cached=False)
        return

    # Удаление/замена фона: если пользователь уже загрузил фото или бот ждёт уточнение.
    if _is_replacebg_wait_text(context):
        img = _get_cached_photo(update.effective_user.id)
        if not img:
            _clear_replacebg_wait(context)
            await update.effective_message.reply_text("Сначала пришлите фото, затем выберите замену фона.", reply_markup=main_kb)
            return
        kind, prompt = _bg_kind_from_text(text)
        _clear_medicine_wait(context)
        _clear_replacebg_wait(context)
        with contextlib.suppress(Exception):
            _mode_track_set(update.effective_user.id, "")
        await _pedit_replacebg(update, context, img, kind=kind, prompt=prompt)
        return

    if _is_remove_bg_request(text):
        _clear_medicine_wait(context)
        with contextlib.suppress(Exception):
            _mode_track_set(update.effective_user.id, "")
        img = _get_cached_photo(update.effective_user.id)
        if img:
            await _pedit_removebg(update, context, img)
            return
        _set_waiting_removebg(context)
        await update.effective_message.reply_text("Пришлите фото — удалю фон и верну PNG с прозрачной подложкой.", reply_markup=main_kb)
        return

    if _is_replace_bg_request(text):
        _clear_medicine_wait(context)
        with contextlib.suppress(Exception):
            _mode_track_set(update.effective_user.id, "")
        img = _get_cached_photo(update.effective_user.id)
        kind, prompt = _bg_kind_from_text(text)
        if img:
            await _pedit_replacebg(update, context, img, kind=kind, prompt=prompt)
            return
        _set_waiting_replacebg(context, prompt=text)
        await update.effective_message.reply_text("Пришлите фото — вырежу объект и заменю только фон. Для пресетов и текстового описания постараюсь сделать результат как настоящее селфи.", reply_markup=main_kb)
        return

    # Ретушь собственного изображения: если фото уже загружено и бот ждёт уточнение.
    if _is_retouch_wait_text(context):
        img = _get_cached_photo(update.effective_user.id)
        if not img:
            _clear_image_retouch_wait(context)
            await update.effective_message.reply_text(_retouch_user_hint_text(), reply_markup=main_kb)
            return
        instruction = text or context.user_data.get("retouch_prompt") or "убрать лишнюю надпись/водяной знак"
        _clear_medicine_wait(context)
        _clear_image_retouch_wait(context)
        with contextlib.suppress(Exception):
            _mode_track_set(update.effective_user.id, "")
        await _start_image_retouch(update, context, img, instruction)
        return

    # AI-селфи: фото уже загружено, ждём сцену/знаменитость/персонажа.
    if context.user_data.get("awaiting_ai_selfie_prompt"):
        img = _get_cached_photo(update.effective_user.id)
        if not img:
            _clear_ai_selfie_wait(context)
            await update.effective_message.reply_text("Сначала загрузите своё селфи, затем нажмите 🤳 AI-селфи со звездой.", reply_markup=main_kb)
            return
        preset = (context.user_data.pop("ai_selfie_preset_prompt", "") or "").strip()
        _clear_ai_selfie_wait(context)
        await _start_ai_selfie(update, context, img, text, preset)
        return

    # Говорящий аватар: портрет уже загружен, но перед текстом требуется выбрать голос.
    if context.user_data.get("awaiting_avatar_voice_choice"):
        tl = (text or "").strip().lower()
        voice_aliases = {
            "nova": "nova", "нова": "nova",
            "onyx": "onyx", "оникс": "onyx",
            "alloy": "alloy", "аллой": "alloy",
            "shimmer": "shimmer", "шиммер": "shimmer",
            "fable": "fable", "фейбл": "fable",
        }
        if tl in voice_aliases:
            chosen = voice_aliases[tl]
            context.user_data["avatar_tts_voice"] = chosen
            context.user_data.pop("awaiting_avatar_voice_choice", None)
            pending_script = (context.user_data.get("avatar_pending_script") or "").strip()
            img = _get_cached_photo(update.effective_user.id)
            if pending_script and img:
                context.user_data.pop("avatar_pending_script", None)
                _clear_avatar_wait(context)
                await update.effective_message.reply_text(f"✅ Для аватара выбран голос: {_avatar_tts_voice_label(chosen)}. Текст уже получен — запускаю говорящий аватар.")
                await _start_talking_avatar(update, context, img, script_text=pending_script)
                return
            _set_avatar_wait(context)
            await update.effective_message.reply_text(f"✅ Для аватара выбран голос: {_avatar_tts_voice_label(chosen)}. Теперь пришлите текст, который должен произнести аватар.")
            return
        await update.effective_message.reply_text(_avatar_voice_choice_text(), reply_markup=_avatar_voice_choice_kb("act"))
        return

    # Говорящий аватар: фото уже загружено, ждём текст/голос для речи.
    if context.user_data.get("awaiting_avatar_script"):
        img = _get_cached_photo(update.effective_user.id)
        if not img:
            _clear_avatar_wait(context)
            await update.effective_message.reply_text("Сначала загрузите портрет человека, затем нажмите 🗣 Говорящий аватар.", reply_markup=main_kb)
            return
        _clear_avatar_wait(context)
        await _start_talking_avatar(update, context, img, script_text=text)
        return

    # AI-видеоклип: два независимых вопроса — сначала песня, затем режиссура видео.
    if context.user_data.get("awaiting_vocal_clip_prompt"):
        img = _get_cached_photo(update.effective_user.id)
        if not img:
            _clear_vocal_clip_wait(context)
            await update.effective_message.reply_text("Сначала загрузите портрет одного человека, затем нажмите 🎤 Клип с вокалом.", reply_markup=main_kb)
            return
        context.user_data.pop("awaiting_vocal_clip_prompt", None)
        context.user_data["music_video_music_brief"] = text.strip()
        context.user_data["awaiting_music_video_video_brief"] = True
        # Persist the VIDEO stage as well as the song brief. Telegram updates can
        # land on a fresh worker/process, so user_data alone is not authoritative.
        with contextlib.suppress(Exception):
            kv_set(f"music_video_music_brief:{update.effective_user.id}", text.strip())
            _mode_track_set(
                update.effective_user.id,
                "vocalclip:video" if context.user_data.get("vocal_clip_flow") else "musicvideo:video",
            )
        await update.effective_message.reply_text(
            "🎥 Теперь отдельно опишите ВИДЕО: что происходит в кадре, действия героя, куда он идёт, как движется камера, окружение, свет и финальный кадр.\n\n"
            "Например: двери лифта открываются → я выхожу → камера обходит меня и переходит за спину → следует сзади → я выхожу на солнечную улицу к оранжевому Lamborghini Urus."
        )
        return

    if context.user_data.get("awaiting_music_video_video_brief"):
        img = _get_cached_photo(update.effective_user.id)
        music_brief = (context.user_data.get("music_video_music_brief") or "").strip()
        if not img or not music_brief:
            context.user_data.pop("awaiting_music_video_video_brief", None)
            context.user_data.pop("music_video_music_brief", None)
            await update.effective_message.reply_text("Черновик клипа потерял исходные данные. Начните режим AI-видеоклипа ещё раз.")
            return
        await _stage_music_video_draft(update, context, music_brief=music_brief, video_brief=text)
        return

    # Оживление фото по пользовательскому сценарию: фото уже загружено,
    # ждём короткий motion prompt, затем предлагаем выбрать движок.
    if context.user_data.pop("awaiting_revival_custom_prompt", None):
        img = _get_cached_photo(update.effective_user.id)
        if not img:
            context.user_data.pop("revival_custom_prompt", None)
            await update.effective_message.reply_text("Сначала загрузите фото и снова откройте «Оживить фото».")
            return
        context.user_data["revival_custom_prompt"] = text.strip()
        await update.effective_message.reply_text(
            "✅ Сценарий сохранён. Теперь выберите движок:",
            reply_markup=photo_revival_engines_kb(),
        )
        return

    # Video Studio: one prompt -> validated scene plan -> Seedance scenes -> montage.
    if context.user_data.get("awaiting_video_studio_prompt"):
        await _start_video_studio(update, context, text)
        return

    # Видео по тексту/голосу: ждём prompt после выбора движка.
    if context.user_data.get("awaiting_text_video_prompt"):
        _clear_text_video_wait(context)
        await _start_text_video(update, context, text)
        return

    # Фото→видеоклип: первый текст после фото — только музыкальный бриф.
    # Не передаём его как legacy combined prompt, иначе он дублируется в VIDEO_BRIEF.
    if context.user_data.get("awaiting_photo_clip_prompt"):
        img = _get_cached_photo(update.effective_user.id)
        if not img:
            _clear_photo_clip_wait(context)
            await update.effective_message.reply_text("Сначала загрузите фото человека, затем нажмите 🎵 Фото → видеоклип.", reply_markup=main_kb)
            return
        context.user_data.pop("awaiting_photo_clip_prompt", None)
        context.user_data["music_video_music_brief"] = text.strip()
        context.user_data["awaiting_music_video_video_brief"] = True
        # Persist the VIDEO stage as well as the song brief. This prevents the
        # next message from falling through to generic GPT/Suno capability text.
        with contextlib.suppress(Exception):
            kv_set(f"music_video_music_brief:{update.effective_user.id}", text.strip())
            _mode_track_set(update.effective_user.id, "musicvideo:video")
        await update.effective_message.reply_text(
            "🎬 Теперь отдельно опишите ВИДЕО: что происходит в кадре, действия героя, куда он идёт, как движется камера, окружение, свет и финальный кадр.\n\n"
            "Например: двери лифта открываются → я выхожу → камера плавно обходит меня и переходит за спину → следует сзади по коридору → я выхожу на солнечную улицу к оранжевому Lamborghini Urus.\n\n"
            "Эта часть не будет отправляться в Suno."
        )
        return

    # Текстовый/голосовой запрос на ретушь до загрузки фото.
    # Это сбрасывает медицину и переводит следующее изображение в image-edit.
    if _is_image_retouch_request(text):
        _clear_medicine_wait(context)
        with contextlib.suppress(Exception):
            _mode_track_set(update.effective_user.id, "")
        img = _get_cached_photo(update.effective_user.id)
        if img and _has_own_image_confirmation(text):
            await _start_image_retouch(update, context, img, text)
            return
        _set_waiting_image_retouch(update, context, text)
        await update.effective_message.reply_text(_retouch_user_hint_text(), reply_markup=main_kb)
        return

    if _is_ai_selfie_intent(text):
        img = _get_cached_photo(update.effective_user.id)
        prompt = _clean_ai_selfie_prompt(text)
        if img and prompt:
            await _start_ai_selfie(update, context, img, prompt)
            return
        _set_ai_selfie_wait(context)
        await update.effective_message.reply_text(
            "Да, сделаю AI-селфи: загрузите своё фото, затем напишите, с кем/где сделать сцену. Например: «селфи с известным актёром на красной дорожке, iPhone selfie, 4:5».",
            reply_markup=main_kb,
        )
        return

    if _is_avatar_intent(text):
        img = _get_cached_photo(update.effective_user.id)
        script = _clean_avatar_script(text)
        if img:
            if script and len(script) > 8:
                context.user_data["avatar_pending_script"] = script
            if context.user_data.get("avatar_tts_voice"):
                pending_script = (context.user_data.get("avatar_pending_script") or "").strip()
                if pending_script:
                    context.user_data.pop("avatar_pending_script", None)
                    await update.effective_message.reply_text(
                        f"✅ Портрет найден. Голос уже выбран: {_avatar_tts_voice_label(_avatar_tts_voice_get(context))}. Текст уже получен — запускаю говорящий аватар."
                    )
                    await _start_talking_avatar(update, context, img, script_text=pending_script)
                else:
                    _set_avatar_wait(context)
                    await update.effective_message.reply_text(
                        f"✅ Портрет найден. Голос уже выбран: {_avatar_tts_voice_label(_avatar_tts_voice_get(context))}. Теперь пришлите текст, voice или аудиофайл 2–60 секунд."
                    )
            else:
                _set_avatar_voice_choice_wait(context)
                await update.effective_message.reply_text(_avatar_voice_choice_text(), reply_markup=_avatar_voice_choice_kb("act"))
        else:
            context.user_data["awaiting_avatar_photo"] = True
            if script and len(script) > 8:
                context.user_data["avatar_pending_script"] = script
            await update.effective_message.reply_text(
                "Да, сделаю говорящий аватар. Сначала загрузите портрет человека. После загрузки я обязательно предложу выбрать голос, а затем использую ваш текст, voice или аудиофайл 2–60 секунд.",
                reply_markup=main_kb,
            )
        return

    if _is_photo_clip_intent(text):
        img = _get_cached_photo(update.effective_user.id)
        prompt = _clean_photo_clip_prompt(text)
        if img and prompt:
            await _stage_music_video_draft(update, context, prompt)
            return
        _set_photo_clip_wait(context)
        await update.effective_message.reply_text(
            "Да, сделаю видеоклип из фото. Загрузите фото человека, затем опишите стиль клипа/музыки, длительность и формат.",
            reply_markup=main_kb,
        )
        return

    # Вопрос/команда про оживление фото должны сбрасывать медицинскую ветку.
    # Иначе после кнопки «Медицина» следующее обычное фото ошибочно уходит в мед. анализ.
    if _is_photo_revival_question(text) or _is_photo_revival_intent(text):
        _set_waiting_photo_revival(update, context)
        await update.effective_message.reply_text(_photo_revival_capability_text(), reply_markup=main_kb)
        return

    # Legacy presentation flags from older deployments are migrated into the v86 studio.
    if context.user_data.pop("awaiting_work_presentation_brief", None):
        await _presentation_studio_get().start(update, context, "presentation")
        if await _presentation_studio_get().handle_text(update, context, text):
            return

    if context.user_data.pop("awaiting_work_catalog_brief", None):
        await _presentation_studio_get().start(update, context, "catalog")
        if await _presentation_studio_get().handle_text(update, context, text):
            return

    if context.user_data.get("awaiting_work_logo_brief"):
        context.user_data.pop("awaiting_work_logo_brief", None)
        _mode_track_set(update.effective_user.id, "work_logo")
        await _generate_business_logo(update, context, text)
        return

    if context.user_data.get("awaiting_music_video_audio_prompt_edit"):
        context.user_data.pop("awaiting_music_video_audio_prompt_edit", None)
        context.user_data.pop("vocal_source_token", None)
        context.user_data.pop("music_video_pending_audio_token", None)
        new_brief = text.strip()
        if not new_brief:
            await update.effective_message.reply_text("Промпт пустой. Нажмите «✏️ Изменить промпт аудио» ещё раз.")
            return
        context.user_data["music_video_pending_music_brief"] = new_brief
        pending_prompt = (context.user_data.get("music_video_pending_prompt") or "").strip()
        if pending_prompt:
            _, pending_video = _music_video_split_briefs(pending_prompt)
            context.user_data["music_video_pending_prompt"] = _music_video_join_briefs(new_brief, pending_video)
        await update.effective_message.reply_text("✏️ Промпт обновлён. Генерирую новый вариант Suno; видео пока не запускаю.")
        fresh = await _run_suno_music_result_bytes(update, new_brief)
        if not fresh:
            await update.effective_message.reply_text("❌ Suno не вернул новый вариант. Попробуйте изменить промпт ещё раз.")
            return
        new_token = uuid.uuid4().hex[:12]
        context.user_data["music_video_pending_audio_token"] = new_token
        await asyncio.to_thread(_save_vocal_artifact, update.effective_user.id, new_token, "audio", fresh)
        await _send_vocal_song_file(update.effective_message, fresh, new_token)
        await update.effective_message.reply_text("🎧 Проверьте новый вариант.", reply_markup=_vocal_song_kb(new_token, pending=True))
        return

    if context.user_data.get("awaiting_suno_brief"):
        context.user_data.pop("awaiting_suno_brief", None)
        _mode_track_set(update.effective_user.id, "suno_music")
        suno_brief = _prepare_suno_brief_from_context(context, text)
        await _run_suno_music(update, context, suno_brief)
        return

    # Если пользователь выбрал Reels/фильм в меню и теперь пишет вводные —
    # сначала даём структурированный сценарный ответ, а не общий чат.
    if context.user_data.get("awaiting_reels_material"):
        context.user_data.pop("awaiting_reels_material", None)
        _mode_track_set(update.effective_user.id, "fun_reels")
        prompt = (
            "Ты продюсер коротких Reels/Shorts. На русском подготовь: 1) хук, 2) сценарий по секундам, "
            "3) текст на экране, 4) voice-over, 5) CTA, 6) промпты для Sora/Kling, "
            "7) монтажные подсказки. Запрос пользователя:\n" + text
        )
        reply = await ask_openai_text(prompt)
        await update.effective_message.reply_text(reply[:3900], reply_markup=main_kb)
        if len(reply) > 3900:
            await update.effective_message.reply_text(reply[3900:7800])
        await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])
        return

    if context.user_data.get("awaiting_film_material"):
        context.user_data.pop("awaiting_film_material", None)
        _mode_track_set(update.effective_user.id, "fun_film")
        prompt = (
            "Ты режиссёр и промпт-инженер AI-видео. На русском подготовь мини-фильм: "
            "1) логлайн, 2) структура сцен, 3) раскадровка, 4) промпты для коротких клипов 5-10 сек "
            "через Sora 2 без людей, Kling или Runway, 5) монтаж/звук/титры, 6) план сборки. Запрос пользователя:\n" + text
        )
        reply = await ask_openai_text(prompt)
        await update.effective_message.reply_text(reply[:3900], reply_markup=main_kb)
        if len(reply) > 3900:
            await update.effective_message.reply_text(reply[3900:7800])
        await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])
        return

    # Вопросы о возможностях.
    # Если вопрос не медицинский, сбрасываем зависший мед. режим,
    # чтобы следующие фото/документы не уходили ошибочно в медицину.
    cap = capability_answer(text)
    if cap:
        if not _is_medical_capability_question(text):
            _clear_medicine_wait(context)
            with contextlib.suppress(Exception):
                _mode_track_set(update.effective_user.id, "")
        await update.effective_message.reply_text(cap, reply_markup=main_kb)
        return

    # Намёк на музыку / песню через Suno
    if re.search(r"(?:созда[йи]|сдела[йи]|сгенериру[йи]|напиши|запусти).{0,80}(музык|песн|трек|джингл|минусовк|suno)", text, re.I):
        _clear_medicine_wait(context)
        with contextlib.suppress(Exception):
            _mode_track_set(update.effective_user.id, "suno_music")
        await _run_suno_music(update, context, text)
        return

    # Намёк на генерацию видеоролика
    mtype, rest = detect_media_intent(text)
    if mtype == "video":
        _clear_medicine_wait(context)
        with contextlib.suppress(Exception):
            _mode_track_set(update.effective_user.id, "")
        duration, aspect = parse_video_opts(text)
        prompt = rest or re.sub(
            r"\b(\d+\s*(?:сек|с)\b|(?:9:16|16:9|1:1|4:5|3:4|4:3))",
            "",
            text,
            flags=re.I,
        ).strip(" ,.")

        if not prompt:
            await update.effective_message.reply_text(
                "Опишите, что именно снять, напр.: «ретро-авто на берегу, закат»."
            )
            return

        aid = _new_aid()
        _pending_actions[aid] = {
            "prompt": prompt,
            "duration": duration,
            "aspect": aspect,
        }

        people_present = _prompt_likely_has_people(prompt)
        buttons = []
        if not people_present:
            buttons.append([InlineKeyboardButton(f"🎞 Sora 2 · без людей · {_video_price_credits('sora', duration)} кр.", callback_data=f"choose:sora:{aid}")])
        buttons.append([InlineKeyboardButton(f"🎬 Kling · {_video_price_credits('kling', duration)} кр.", callback_data=f"choose:kling:{aid}")])
        if TEXT_VIDEO_ALLOW_RUNWAY:
            buttons.append([InlineKeyboardButton(f"🎥 Runway · {_video_price_credits('runway', duration)} кр.", callback_data=f"choose:runway:{aid}")])
        kb = InlineKeyboardMarkup(buttons)
        sora_note = "В запросе обнаружен человек — Sora 2 скрыта." if people_present else "Sora 2 доступна только для сцен без людей."
        await update.effective_message.reply_text(
            f"Что использовать?\nДлительность: {duration} c • Аспект: {aspect}\nЗапрос: «{prompt}»\n\n{sora_note}\nСтоимость уже включает маржу бота и будет списана только после успешного результата.",
            reply_markup=kb,
        )
        return



    # Намёк на картинку
    if mtype == "image":
        _clear_medicine_wait(context)
        with contextlib.suppress(Exception):
            _mode_track_set(update.effective_user.id, "")
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

        await _ask_image_engine_choice(update, context, prompt)
        return

    # Live-запросы: курсы, новости, законы, погода, релизы и любые актуальные данные.
    # Голосовые запросы попадают сюда через on_text_with_text после STT.
    if not _MEDICAL_TERMS_RE.search(text):
        _clear_medicine_wait(context)
        with contextlib.suppress(Exception):
            _mode_track_set(update.effective_user.id, "")
    if await maybe_handle_live_query(update, context, text):
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

    if _MEDICAL_TERMS_RE.search(text):
        # Явный медицинский вопрос/текст — разбираем как мед. материал.
        await _medical_analyze_text(update, context, text)
        _clear_medicine_wait(context)
        with contextlib.suppress(Exception):
            _mode_track_set(user_id, "")
        return

    # Если пользователь раньше нажал мед. подменю, но теперь спрашивает про PDF, книги, фото,
    # видео, новости, курс BTC и т.п., не держим его в медицинской ветке.
    if (track or "").startswith("med_") and not context.user_data.get("medicine_waiting_for_material"):
        with contextlib.suppress(Exception):
            _mode_track_set(user_id, "")

    if mode == "Учёба" and track:
        await study_process_text(update, context, text)
        return

    chat_id = update.effective_chat.id if update.effective_chat else 0
    # Если это короткий ответ на предыдущий уточняющий вопрос, расширяем запрос контекстом.
    llm_input = _chat_memory_followup_query(user_id, chat_id, text_for_llm)
    reply = await ask_openai_text(llm_input, user_id=user_id, chat_id=chat_id)
    await update.effective_message.reply_text(reply)
    _chat_memory_add(user_id, chat_id, "user", text)
    _chat_memory_add(user_id, chat_id, "assistant", reply)
    await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])

# ───────── Фото / Документы / Голос ─────────
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ph = update.message.photo[-1]
        f = await _telegram_media_get_file_with_retry(ph, label="incoming photo")
        data = await f.download_as_bytearray()
        img = bytes(data)
        _cache_photo(update.effective_user.id, img, getattr(f, "file_path", "") or "")

        user_id = update.effective_user.id
        caption = (update.message.caption or "").strip()

        # High-fidelity music-video pack owns these four uploads before every generic photo flow.
        identity_slot = _music_video_identity_wait_slot(context)
        # Defensive recovery: Telegram/user_data is process-local and can be lost on a
        # deploy/restart. While the user is still in the photoclip track, an incomplete
        # identity pack means the next unclaimed photo belongs to the first missing slot,
        # not to the generic photo menu.
        if not identity_slot:
            with contextlib.suppress(Exception):
                if _mode_track_get(user_id) == "photoclip" and not _music_video_identity_complete(user_id):
                    refs = _music_video_identity_pack(user_id)
                    identity_slot = next(
                        (slot for slot in ("face_front", "face_3q", "body_full", "scene_reference") if not refs.get(slot)),
                        "",
                    )
                    if identity_slot:
                        _set_music_video_identity_wait(context, identity_slot)
        if identity_slot:
            _music_video_identity_put(user_id, identity_slot, img)
            if identity_slot == "face_front":
                _set_music_video_identity_wait(context, "face_3q")
                await update.effective_message.reply_text(
                    "✅ 1/3 — лицо анфас сохранено отдельно.\n\n"
                    "2/3 — загрузите лицо с поворотом примерно 30–45°."
                )
            elif identity_slot == "face_3q":
                _set_music_video_identity_wait(context, "body_full")
                await update.effective_message.reply_text(
                    "✅ 2/3 — ракурс 30–45° сохранён отдельно.\n\n"
                    "3/3 — загрузите фото В ПОЛНЫЙ РОСТ, от головы до ног."
                )
            elif identity_slot == "body_full":
                _set_music_video_identity_wait(context, "scene_reference")
                await update.effective_message.reply_text(
                    "✅ Character Identity Pack собран: FACE_FRONT + FACE_3Q + BODY_FULL.\n\n"
                    "Теперь загрузите SCENE_REFERENCE — стартовый кадр окружения/позы. "
                    "Он задаёт сцену и композицию, но НЕ заменяет фотографии личности."
                )
            else:
                _set_music_video_identity_wait(context, "scene_reference")
                context.user_data.pop("music_video_scene_reference", None)
                _set_photo_clip_wait(context)
                await update.effective_message.reply_text(
                    "✅ SCENE_REFERENCE сохранён отдельно. Все 4 reference готовы.\n\n"
                    "🎵 Теперь отдельно опишите ПЕСНЮ: жанр, настроение, язык, тему текста, "
                    "нужен ли вокал и каким голосом. После этого я отдельно спрошу ВИДЕО."
                )
            return

        # Presentation Studio: logo/product photo bulk upload.
        if await _presentation_studio_get().handle_photo(update, context, img, mime="image/jpeg", caption=caption):
            return

        if context.user_data.pop("music_video_draft", None):
            context.user_data.pop("music_video_draft_edit", None)
            _set_photo_clip_wait(context)
            await update.effective_message.reply_text(
                "📸 Фото для клипа обновлено. Опишите сценарий ещё раз, чтобы утвердить его для этого фото."
            )
            return

        # 0) Замена лица: двухшаговый режим должен срабатывать раньше остальных фото-веток.
        if context.user_data.get("faceswap_flow") == "await_target":
            await _maybe_choose_target_face(update, context, user_id, img)
            return
        if context.user_data.get("faceswap_flow") == "await_source":
            await _maybe_choose_source_face(update, context, user_id, img)
            return
        if caption and _is_face_swap_request(caption):
            _clear_medicine_wait(context)
            with contextlib.suppress(Exception):
                _mode_track_set(user_id, "")
            await _start_faceswap_flow(update, context, img)
            return

        # 0.5) Говорящий аватар / фото→видеоклип из подписи к фото.
        if caption and _is_avatar_intent(caption):
            script = _clean_avatar_script(caption)
            _clear_medicine_wait(context)
            if script and len(script) > 8:
                context.user_data["avatar_pending_script"] = script
            _set_avatar_voice_choice_wait(context)
            await update.effective_message.reply_text("Портрет получен. Теперь выберите голос для текстовой озвучки или пришлите свой voice/audio.", reply_markup=_avatar_voice_choice_kb("act"))
            return

        if caption and _is_photo_clip_intent(caption):
            prompt = _clean_photo_clip_prompt(caption)
            _clear_medicine_wait(context)
            if prompt:
                await _stage_music_video_draft(update, context, prompt)
            else:
                _set_photo_clip_wait(context)
                await update.effective_message.reply_text("🎵 Фото получено. Сначала отдельно опишите ПЕСНЮ: жанр, настроение, язык, тему текста, нужен ли вокал и каким голосом. После этого я отдельно спрошу ВИДЕО.")
            return

        if caption and _is_ai_selfie_intent(caption):
            prompt = _clean_ai_selfie_prompt(caption)
            _clear_medicine_wait(context)
            if prompt:
                await _start_ai_selfie(update, context, img, prompt)
            else:
                _set_ai_selfie_wait(context)
                await update.effective_message.reply_text("Селфи получено. Теперь напишите, с кем/где сделать AI-фото: знаменитость, персонаж, премьера, реклама, travel/luxury.")
            return

        if context.user_data.get("awaiting_ai_selfie_photo"):
            context.user_data.pop("awaiting_ai_selfie_photo", None)
            preset = (context.user_data.get("ai_selfie_preset_prompt", "") or "").strip()
            _set_ai_selfie_wait(context)
            if preset:
                await update.effective_message.reply_text("🤳 Селфи получено. Пресет выбран. Теперь напишите имя знаменитости/персонажа и детали сцены.")
            else:
                await update.effective_message.reply_text("🤳 Селфи получено. Теперь напишите, с кем/где сделать AI-фото: знаменитость, персонаж, премьера, реклама, travel/luxury.")
            return

        if context.user_data.get("awaiting_avatar_photo"):
            context.user_data.pop("awaiting_avatar_photo", None)
            # Upload flow is deterministic: a newly uploaded portrait always advances to step 2.
            # Do not silently skip voice selection because a stale voice remained from an earlier avatar session.
            context.user_data.pop("avatar_tts_voice", None)
            _set_avatar_voice_choice_wait(context)
            await update.effective_message.reply_text(
                "✅ Портрет получен. Шаг 2/3: выберите голос для текстовой озвучки или пришлите свой voice/audio.",
                reply_markup=_avatar_voice_choice_kb("act"),
            )
            return

        if context.user_data.get("awaiting_vocal_clip_photo"):
            context.user_data.pop("awaiting_vocal_clip_photo", None)
            _seed_vocal_identity_from_portrait(user_id, img)
            if context.user_data.get("vocal_audio_is_custom") and context.user_data.get("vocal_source_token"):
                _set_vocal_clip_video_brief_after_custom_audio(context)
                await update.effective_message.reply_text(
                    "✅ Портрет и исходная аудиодорожка получены. Теперь опишите видеоряд: сцены, движения, локации и настроение."
                )
            else:
                _set_vocal_clip_wait(context)
                await update.effective_message.reply_text(
                    "🎤 Портрет получен. Опишите песню, вокал, движение, длительность и формат — покажу сценарий для утверждения."
                )
            return

        if context.user_data.get("awaiting_photo_clip_photo"):
            context.user_data.pop("awaiting_photo_clip_photo", None)
            preset_prompt = (context.user_data.pop("photo_clip_preset_prompt", "") or "").strip()
            if preset_prompt:
                await _stage_music_video_draft(update, context, preset_prompt)
            else:
                _set_photo_clip_wait(context)
                await update.effective_message.reply_text("🎵 Фото получено. Сначала отдельно опишите ПЕСНЮ: жанр, настроение, язык, тему текста, нужен ли вокал и каким голосом. После этого я отдельно спрошу ВИДЕО.")
            return

        # 0) Фото пришло после входа из меню «Развлечения → Заменить фон».
        # Не запускаем замену сразу, а показываем варианты фона.
        if context.user_data.get("photo_flow") == "replacebg_menu":
            context.user_data.pop("photo_flow", None)
            await update.effective_message.reply_text(
                "🖼 Фото получено. Выберите новый фон или напишите свой вариант текстом:",
                reply_markup=background_presets_kb(),
            )
            return

        # 0) Удаление/замена фона должны перебивать медицинский контекст.
        if caption and _is_remove_bg_request(caption):
            _clear_medicine_wait(context)
            _clear_removebg_wait(context)
            with contextlib.suppress(Exception):
                _mode_track_set(user_id, "")
            await _pedit_removebg(update, context, img)
            return

        if _is_waiting_removebg(context):
            _clear_medicine_wait(context)
            _clear_removebg_wait(context)
            with contextlib.suppress(Exception):
                _mode_track_set(user_id, "")
            await _pedit_removebg(update, context, img)
            return

        if caption and _is_replace_bg_request(caption):
            kind, prompt = _bg_kind_from_text(caption)
            _clear_medicine_wait(context)
            _clear_replacebg_wait(context)
            with contextlib.suppress(Exception):
                _mode_track_set(user_id, "")
            await _pedit_replacebg(update, context, img, kind=kind, prompt=prompt)
            return

        if _is_waiting_replacebg(context):
            prompt = caption or context.user_data.get("replacebg_prompt") or "размытый фон"
            kind, prompt = _bg_kind_from_text(prompt)
            _clear_medicine_wait(context)
            _clear_replacebg_wait(context)
            with contextlib.suppress(Exception):
                _mode_track_set(user_id, "")
            await _pedit_replacebg(update, context, img, kind=kind, prompt=prompt)
            return

        # 0) Ретушь собственного изображения / удаление лишней надписи / watermark.
        # Это должно перебивать медицинский контекст, если пользователь явно просит ретушь.
        if caption and _is_image_retouch_request(caption):
            _clear_medicine_wait(context)
            _clear_image_retouch_wait(context)
            with contextlib.suppress(Exception):
                _mode_track_set(user_id, "")
            await _start_image_retouch(update, context, img, caption)
            return

        if _is_waiting_image_retouch(context):
            instruction = context.user_data.get("retouch_prompt") or caption or "убрать лишнюю надпись/водяной знак"
            _clear_medicine_wait(context)
            _clear_image_retouch_wait(context)
            with contextlib.suppress(Exception):
                _mode_track_set(user_id, "")
            await _start_image_retouch(update, context, img, instruction)
            return

        # 1) Самый высокий приоритет: явная команда оживить/анимировать фото в подписи.
        # Это должно перебивать даже ранее открытый раздел «Медицина».
        if caption and _is_photo_revival_intent(caption):
            _set_waiting_photo_revival(update, context)
            engine = _revival_engine_from_text(caption, default="runway")
            prompt = _clean_revival_prompt(caption)
            _clear_photo_revival_wait(context)
            await _start_photo_revival(update, context, engine=engine, img_bytes=img, prompt=prompt)
            return

        # 2) Если перед фото пользователь голосом/текстом спросил про оживление фото —
        # показываем фото-мастерскую, а не медицинский анализ.
        if _is_waiting_photo_revival(context):
            _clear_photo_revival_wait(context)
            await update.effective_message.reply_text(
                "Фото получено. Выберите сценарий оживления:",
                reply_markup=photo_revival_actions_kb(),
            )
            return

        # 3) Медицинская ветка — только явный мед. подрежим/ожидание или мед. слова в подписи.
        if _should_route_medical(context, user_id, caption, "photo"):
            await _medical_analyze_image(update, context, img, goal=caption or None)
            _clear_medicine_wait(context)
            with contextlib.suppress(Exception):
                _mode_track_set(user_id, "")
            return

        if caption:
            tl = caption.lower()
            # оживить фото → выбранный движок из подписи или Runway по умолчанию
            if any(k in tl for k in ("оживи", "оживить", "анимиру", "анимировать", "сделай видео", "revive", "animate", "image to video", "i2v")):
                engine = _revival_engine_from_text(caption, default="runway")
                prompt = _clean_revival_prompt(caption)
                await _start_photo_revival(update, context, engine=engine, img_bytes=img, prompt=prompt)
                return

            # ретушь / убрать водяной знак / лишнюю надпись
            if _is_image_retouch_request(caption):
                await _start_image_retouch(update, context, img, caption); return

            # удалить фон
            if any(k in tl for k in ("удали фон", "removebg", "убрать фон")):
                await _pedit_removebg(update, context, img); return

            # заменить фон
            if any(k in tl for k in ("замени фон", "replacebg", "размытый фон", "blur")):
                kind, prompt = _bg_kind_from_text(caption)
                await _pedit_replacebg(update, context, img, kind=kind, prompt=prompt); return

            # outpaint
            if "outpaint" in tl or "расшир" in tl:
                await _pedit_outpaint(update, context, img); return

            # раскадровка
            if "раскадров" in tl or "storyboard" in tl:
                await _pedit_storyboard(update, context, img); return

            # картинка по описанию (Luma / фолбэк OpenAI)
            if any(k in tl for k in ("картин", "изображен", "image", "img")) and any(k in tl for k in ("сгенериру", "созда", "сделай")):
                await _start_luma_img(update, context, caption); return

        # если явной команды в подписи нет — показываем быстрые кнопки
        await update.effective_message.reply_text("Фото получено. Что сделать?",
                                                  reply_markup=photo_quick_actions_kb())
    except Exception as e:
        log.exception("on_photo error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("❌ Фото не распознано, попробуйте ещё раз.")

async def on_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.document:
            return
        doc = update.message.document
        mt = (doc.mime_type or "").lower()
        tg_file = await doc.get_file()
        data = await tg_file.download_as_bytearray()
        raw = bytes(data)

        caption = (update.message.caption or "").strip()

        # Presentation Studio accepts image documents and ZIP archives with many photos.
        if await _presentation_studio_get().handle_document(
            update, context, raw, doc.file_name or "file", mt, caption=caption
        ):
            return

        if context.user_data.get("awaiting_avatar_script") and (mt.startswith("audio/") or (doc.file_name or "").lower().endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg"))):
            img = _get_cached_photo(update.effective_user.id)
            if not img:
                _clear_avatar_wait(context)
                await update.effective_message.reply_text("Сначала загрузите портрет человека, затем нажмите 🗣 Говорящий аватар.")
                return
            _clear_avatar_wait(context)
            await _start_talking_avatar(
                update, context, img,
                script_text=caption if caption and not _is_avatar_intent(caption) else _clean_avatar_script(caption),
                audio_bytes=raw,
                audio_filename=doc.file_name or "audio",
                audio_file_url=getattr(tg_file, "file_path", "") or "",
                audio_mime=mt,
            )
            return

        if mt.startswith("image/"):
            _cache_photo(update.effective_user.id, raw, getattr(tg_file, "file_path", "") or "")

            if context.user_data.pop("music_video_draft", None):
                context.user_data.pop("music_video_draft_edit", None)
                _set_photo_clip_wait(context)
                await update.effective_message.reply_text(
                    "📸 Фото для клипа обновлено. Опишите сценарий ещё раз, чтобы утвердить его для этого фото."
                )
                return

            # v70: если пользователь уже выбрал режим «Клип с вокалом»,
            # следующая фотография должна продолжать этот сценарий, а не открывать
            # общее меню «Фото получено. Что сделать?». Это страхует случаи,
            # когда Telegram/клиент потерял transient flag, но mode_track сохранился.
            try:
                _track_now = _mode_track_get(update.effective_user.id)
            except Exception:
                _track_now = ""
            if context.user_data.get("awaiting_vocal_clip_photo") or _track_now.startswith("vocalclip"):
                context.user_data.pop("awaiting_vocal_clip_photo", None)
                _set_mode_clean(update.effective_user.id, "Развлечения", "vocalclip")
                _seed_vocal_identity_from_portrait(update.effective_user.id, raw)
                _set_vocal_clip_wait(context)
                await update.effective_message.reply_text(
                    "🎵 Портрет получен. Сначала отдельно опишите ПЕСНЮ: жанр, настроение, язык, тему текста, вокал и желаемую длительность.\n\n"
                    "Следующим сообщением я отдельно спрошу сценарий видео."
                )
                return

            if context.user_data.get("faceswap_flow") == "await_target":
                await _maybe_choose_target_face(update, context, update.effective_user.id, raw)
                return
            if context.user_data.get("faceswap_flow") == "await_source":
                await _maybe_choose_source_face(update, context, update.effective_user.id, raw)
                return
            if caption and _is_face_swap_request(caption):
                _clear_medicine_wait(context)
                with contextlib.suppress(Exception):
                    _mode_track_set(update.effective_user.id, "")
                await _start_faceswap_flow(update, context, raw)
                return

            if caption and _is_avatar_intent(caption):
                script = _clean_avatar_script(caption)
                _clear_medicine_wait(context)
                if script and len(script) > 8:
                    context.user_data["avatar_pending_script"] = script
                _set_avatar_voice_choice_wait(context)
                await update.effective_message.reply_text("Портрет получен. Теперь выберите голос для текстовой озвучки или пришлите свой voice/audio.", reply_markup=_avatar_voice_choice_kb("act"))
                return

            if caption and _is_photo_clip_intent(caption):
                prompt = _clean_photo_clip_prompt(caption)
                _clear_medicine_wait(context)
                if prompt:
                    await _stage_music_video_draft(update, context, prompt)
                else:
                    _set_photo_clip_wait(context)
                    await update.effective_message.reply_text("🎵 Фото получено. Сначала отдельно опишите ПЕСНЮ: жанр, настроение, язык, тему текста, нужен ли вокал и каким голосом. После этого я отдельно спрошу ВИДЕО.")
                return

            if caption and _is_ai_selfie_intent(caption):
                prompt = _clean_ai_selfie_prompt(caption)
                _clear_medicine_wait(context)
                if prompt:
                    await _start_ai_selfie(update, context, raw, prompt)
                else:
                    _set_ai_selfie_wait(context)
                    await update.effective_message.reply_text("Селфи получено. Теперь напишите, с кем/где сделать AI-фото: знаменитость, персонаж, премьера, реклама, travel/luxury.")
                return

            if context.user_data.get("awaiting_ai_selfie_photo"):
                context.user_data.pop("awaiting_ai_selfie_photo", None)
                preset = (context.user_data.get("ai_selfie_preset_prompt", "") or "").strip()
                _set_ai_selfie_wait(context)
                if preset:
                    await update.effective_message.reply_text("🤳 Селфи получено. Пресет выбран. Теперь напишите имя знаменитости/персонажа и детали сцены.")
                else:
                    await update.effective_message.reply_text("🤳 Селфи получено. Теперь напишите, с кем/где сделать AI-фото: знаменитость, персонаж, премьера, реклама, travel/luxury.")
                return

            if context.user_data.get("awaiting_vocal_clip_photo"):
                context.user_data.pop("awaiting_vocal_clip_photo", None)
                _set_vocal_clip_wait(context)
                await update.effective_message.reply_text(
                    "🎤 Портрет получен. Теперь опишите песню/клип: стиль, язык, настроение, припев, длительность.\n\nВажно: режим рассчитан на одного человека в кадре."
                )
                return

            if context.user_data.get("awaiting_avatar_photo"):
                context.user_data.pop("awaiting_avatar_photo", None)
                context.user_data.pop("avatar_tts_voice", None)
                _set_avatar_voice_choice_wait(context)
                await update.effective_message.reply_text(
                    "✅ Портрет получен. Шаг 2/3: выберите голос для текстовой озвучки или пришлите свой voice/audio.",
                    reply_markup=_avatar_voice_choice_kb("act"),
                )
                return

            if context.user_data.get("awaiting_photo_clip_photo"):
                context.user_data.pop("awaiting_photo_clip_photo", None)
                preset_prompt = (context.user_data.pop("photo_clip_preset_prompt", "") or "").strip()
                if preset_prompt:
                    await _stage_music_video_draft(update, context, preset_prompt)
                else:
                    _set_photo_clip_wait(context)
                    await update.effective_message.reply_text("🎵 Фото получено. Сначала отдельно опишите ПЕСНЮ: жанр, настроение, язык, тему текста, нужен ли вокал и каким голосом. После этого я отдельно спрошу ВИДЕО.")
                return

            if context.user_data.get("photo_flow") == "replacebg_menu":
                context.user_data.pop("photo_flow", None)
                await update.effective_message.reply_text(
                    "🖼 Изображение получено. Выберите новый фон. Замена выполняется в 2 этапа: вырезаю человека, затем подставляю новый фон без перерисовки лица и одежды.",
                    reply_markup=background_presets_kb(),
                )
                return

            if caption and _is_remove_bg_request(caption):
                _clear_medicine_wait(context)
                _clear_removebg_wait(context)
                with contextlib.suppress(Exception):
                    _mode_track_set(update.effective_user.id, "")
                await _pedit_removebg(update, context, raw)
                return

            if _is_waiting_removebg(context):
                _clear_medicine_wait(context)
                _clear_removebg_wait(context)
                with contextlib.suppress(Exception):
                    _mode_track_set(update.effective_user.id, "")
                await _pedit_removebg(update, context, raw)
                return

            if caption and _is_replace_bg_request(caption):
                kind, prompt = _bg_kind_from_text(caption)
                _clear_medicine_wait(context)
                _clear_replacebg_wait(context)
                with contextlib.suppress(Exception):
                    _mode_track_set(update.effective_user.id, "")
                await _pedit_replacebg(update, context, raw, kind=kind, prompt=prompt)
                return

            if _is_waiting_replacebg(context):
                prompt = caption or context.user_data.get("replacebg_prompt") or "размытый фон"
                kind, prompt = _bg_kind_from_text(prompt)
                _clear_medicine_wait(context)
                _clear_replacebg_wait(context)
                with contextlib.suppress(Exception):
                    _mode_track_set(update.effective_user.id, "")
                await _pedit_replacebg(update, context, raw, kind=kind, prompt=prompt)
                return

            if caption and _is_image_retouch_request(caption):
                _clear_medicine_wait(context)
                _clear_image_retouch_wait(context)
                with contextlib.suppress(Exception):
                    _mode_track_set(update.effective_user.id, "")
                await _start_image_retouch(update, context, raw, caption)
                return

            if _is_waiting_image_retouch(context):
                instruction = context.user_data.get("retouch_prompt") or caption or "убрать лишнюю надпись/водяной знак"
                _clear_medicine_wait(context)
                _clear_image_retouch_wait(context)
                with contextlib.suppress(Exception):
                    _mode_track_set(update.effective_user.id, "")
                await _start_image_retouch(update, context, raw, instruction)
                return

            if caption and _is_photo_revival_intent(caption):
                _set_waiting_photo_revival(update, context)
                engine = _revival_engine_from_text(caption, default="runway")
                prompt = _clean_revival_prompt(caption)
                _clear_photo_revival_wait(context)
                await _start_photo_revival(update, context, engine=engine, img_bytes=raw, prompt=prompt)
                return

            if _is_waiting_photo_revival(context):
                _clear_photo_revival_wait(context)
                await update.effective_message.reply_text("Изображение получено как документ. Выберите доступный движок для оживления:", reply_markup=photo_quick_actions_kb())
                return

            if _should_route_medical(context, update.effective_user.id, caption, doc.file_name or "image"):
                await _medical_analyze_image(update, context, raw, goal=caption or None)
                _clear_medicine_wait(context)
                with contextlib.suppress(Exception):
                    _mode_track_set(update.effective_user.id, "")
                return
            await update.effective_message.reply_text("Изображение получено как документ. Что сделать?", reply_markup=photo_quick_actions_kb())
            return

        text, kind = extract_text_from_document(raw, doc.file_name or "file")
        if not (text or "").strip():
            await update.effective_message.reply_text(f"Не удалось извлечь текст из {kind}.")
            return

        # A text document can serve as the brief or revision for an active presentation project.
        if await _presentation_studio_get().handle_text(update, context, text):
            return

        goal = (update.message.caption or "").strip() or None
        if _should_route_medical(context, update.effective_user.id, caption, doc.file_name or "file"):
            await _medical_analyze_text(update, context, text, goal=goal)
            _clear_medicine_wait(context)
            with contextlib.suppress(Exception):
                _mode_track_set(update.effective_user.id, "")
            return

        await update.effective_message.reply_text(f"📄 Извлекаю текст ({kind}), готовлю конспект…")
        summary = await summarize_long_text(text, query=goal)
        summary = summary or "Готово."
        await update.effective_message.reply_text(summary)
        await maybe_tts_reply(update, context, summary[:TTS_MAX_CHARS])
    except Exception as e:
        log.exception("on_doc error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("❌ Фото/документ не распознан, попробуйте ещё раз.")

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
        await on_text(update, context, manual_text=text)
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
        await on_text(update, context, manual_text=text)
    except Exception as e:
        log.exception("on_audio error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("Ошибка при обработке аудио.")


# ───────── Обработчик ошибок PTB ─────────
async def on_error(update: object, context_: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled error: %s", context_.error)
    try:
        if isinstance(update, Update):
            cb_data = (getattr(getattr(update, "callback_query", None), "data", "") or "").strip()
            presentation_active = bool(getattr(context_, "user_data", {}).get("presentation_studio_active"))
            # The presentation wizard handles and reports its own errors after saving state.
            # Suppress the misleading second message «Упс, произошла ошибка».
            if cb_data.startswith("ps:") or presentation_active:
                return
            if update.effective_message:
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
        "💼 *Работа/Бизнес*\n"
        "Письма, КП, договорные черновики, аналитика, планы, брифы, презентации, PDF-каталоги, логотипы и ретушь бизнес-фото.\n\n"
        "_Быстрые действия:_\n"
        "• 📄 Письмо / документ\n"
        "• 📊 Создать презентацию\n"
        "• 📕 Создать PDF-каталог\n"
        "• 🎨 Создать логотип\n"
        "• 🧽 Удалить водяной знак / надпись с фото"
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown", reply_markup=_mode_kb("work"))

async def on_mode_fun_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    txt = _mode_desc("fun", user_id)
    await update.effective_message.reply_text(
        txt,
        parse_mode="Markdown",
        reply_markup=_fun_quick_kb(user_id),
    )

# ───── Единая совместимая клавиатура «Развлечения» ─────
def _legacy_fun_quick_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🪄 Оживить фото", callback_data="fun:revive")],
        [InlineKeyboardButton("🗣 Говорящий аватар", callback_data="fun:avatar")],
        [InlineKeyboardButton("🎤 AI-видеоклип / песня", callback_data="fun:photoclip")],
        [InlineKeyboardButton("🎬 Видео по тексту/голосу", callback_data="fun:textvideo")],
        [InlineKeyboardButton("🤳 AI-селфи со звездой", callback_data="fun:aiselfie")],
        [InlineKeyboardButton("🎭 Замена лица на фото", callback_data="fun:faceswap")],
        [InlineKeyboardButton("🧼 Удалить фон на фото", callback_data="fun:removebg")],
        [InlineKeyboardButton("🖼 Заменить фон на фото", callback_data="fun:replacebg")],
        [InlineKeyboardButton("📱 Reels / Shorts", callback_data="fun:reels")],
        [InlineKeyboardButton("🎞 Создать мини-фильм", callback_data="fun:film")],
        [InlineKeyboardButton("🎬 Сценарий / кадры", callback_data="fun:storyboard")],
        [InlineKeyboardButton("🎵 Музыка / песня", callback_data="fun:music")],
        [InlineKeyboardButton("🎮 Игры / квиз", callback_data="fun:quiz")],
        [InlineKeyboardButton("🎭 Идеи для досуга", callback_data="fun:ideas")],
        [InlineKeyboardButton("📝 Свободный запрос", callback_data="fun:free")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="fun:back")],
    ]
    return InlineKeyboardMarkup(rows)


def _fun_quick_kb(user_id: int | None = None) -> InlineKeyboardMarkup:
    if entertainment_menu_v2_enabled(user_id=user_id):
        return build_entertainment_keyboard(
            "root", InlineKeyboardButton, InlineKeyboardMarkup
        )
    return _legacy_fun_quick_kb()


async def on_cb_entertainment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not entertainment_menu_v2_enabled(user_id=q.from_user.id):
        await q.message.reply_text(
            "🔥 Развлечения — быстрые действия: видео, фото, фон и замена лица.",
            reply_markup=_legacy_fun_quick_kb(),
        )
        return

    route = classify_entertainment_callback(q.data or "")
    if route.kind == "soon":
        menu_id = context.user_data.get("ent_nav_menu", "root")
        try:
            get_entertainment_menu(menu_id)
        except KeyError:
            menu_id = "root"
        await q.message.reply_text(
            "🚧 Этот сценарий уже готовим. Скоро он появится в меню — "
            "пока кредиты не списываются.",
            reply_markup=build_entertainment_keyboard(
                menu_id, InlineKeyboardButton, InlineKeyboardMarkup
            ),
        )
        return

    menu_id = route.target if route.kind in {"menu", "back"} else "root"
    context.user_data["ent_nav_menu"] = menu_id
    menu = get_entertainment_menu(menu_id)
    await q.message.reply_text(
        f"{menu.title}\n\n{menu.intro}",
        reply_markup=build_entertainment_keyboard(
            menu_id, InlineKeyboardButton, InlineKeyboardMarkup
        ),
    )

# ───── Обработчик быстрых действий «Развлечения» (fallback-friendly) ─────
async def on_cb_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()
    action = data.split(":", 1)[1] if ":" in data else ""

    async def _try_call(*fn_names, **kwargs):
        fn = _pick_first_defined(*fn_names)
        if callable(fn):
            return await fn(update, context, **kwargs)
        return None

    if action == "ideas":
        from neyrobot_prod.entertainment.leisure import handle_leisure_menu
        return await handle_leisure_menu(update, context)

    if action == "quiz":
        from neyrobot_prod.entertainment.game_telegram import handle_game_menu
        return await handle_game_menu(update, context)

    if action == "avatar":
        await q.answer("Говорящий аватар")
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "avatar")
        await q.message.reply_text(_avatar_menu_text(), parse_mode="Markdown", reply_markup=_avatar_action_kb("fun"))
        return

    if action.startswith("av_voice_"):
        voice = action.rsplit("_", 1)[-1].strip()
        context.user_data["avatar_tts_voice"] = voice
        context.user_data.pop("awaiting_avatar_voice_choice", None)
        if _get_cached_photo(q.from_user.id):
            _set_avatar_wait(context)
            await q.answer(f"Голос: {voice}")
            await q.message.reply_text(f"✅ Для аватара выбран голос: {_avatar_tts_voice_label(voice)}. Шаг 3/3: пришлите текст, который должен произнести аватар.")
        else:
            context.user_data["awaiting_avatar_photo"] = True
            await q.answer(f"Голос: {voice}")
            await q.message.reply_text(f"✅ Голос выбран: {_avatar_tts_voice_label(voice)}. Теперь пришлите портрет человека.")
        return

    if action == "avatar_upload":
        await q.answer("Загрузите портрет")
        await _handle_avatar_upload_choice(update, context, q, prefix="fun")
        return

    if action in {"avatar_last", "avatar_text"}:
        await _handle_avatar_script_choice(update, context, q, prefix="fun", voice_mode=False)
        return

    if action == "avatar_voice":
        await _handle_avatar_script_choice(update, context, q, prefix="fun", voice_mode=True)
        return

    if action == "vocalclip":
        await q.answer("Клип с вокалом")
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "vocalclip")
        await q.message.reply_text(_vocal_clip_menu_text(), parse_mode="Markdown", reply_markup=_vocal_clip_action_kb("fun"))
        return

    if action == "vocalclip_upload":
        await q.answer("Загрузите портрет")
        await _handle_vocalclip_upload_choice(update, context, q, prefix="fun")
        return

    if action == "vocalclip_audio":
        await _handle_vocalclip_audio_choice(update, context, q, prefix="fun")
        return

    if action in {"vocalclip_last", "vocalclip_prompt"}:
        await _handle_vocalclip_prompt_choice(update, context, q, prefix="fun")
        return

    if action == "textvideo":
        await q.answer("Видео по тексту/голосу")
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "textvideo")
        await q.message.reply_text(_textvideo_menu_text(), parse_mode="Markdown", reply_markup=_textvideo_action_kb("fun"))
        return

    if action == "tv_engine_sora":
        await _handle_textvideo_engine_choice(update, context, q, "sora", prefix="fun")
        return

    if action == "tv_engine_veo":
        await _handle_textvideo_engine_choice(update, context, q, "veo", prefix="fun")
        return

    if action == "tv_engine_seedance":
        await _handle_textvideo_engine_choice(update, context, q, "seedance", prefix="fun")
        return

    if action == "ad_caption_style":
        await q.answer()
        await q.message.reply_text("🔤 Выберите оформление русских титров:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚪ Белый", callback_data="adstyle:white"),
             InlineKeyboardButton("⚫ Чёрный", callback_data="adstyle:black")],
            [InlineKeyboardButton("◐ Автоконтраст", callback_data="adstyle:auto")],
        ]))
        return

    if action in {"video_director", "video_montage"}:
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", action)
        context.user_data["awaiting_video_studio_prompt"] = True
        context.user_data["video_studio_mode"] = "director" if action == "video_director" else "montage"
        await q.answer("Авторежиссёр" if action == "video_director" else "Автомонтаж")
        await q.message.reply_text(
            ("🎬 Пришлите один промпт для авторежиссёра. Я разобью его на сцены, "
             "создам сцены через Seedance 2.5 и соберу финальный ролик.")
            if action == "video_director"
            else
            ("🛠 Пришлите описание ролика для автомонтажа. Я создам отдельные сцены "
             "и автоматически склею удачные фрагменты в один ролик.\n\n"
             "Для надписей добавьте строки, например:\n"
             "ТИТРЫ: 0-3 | КРАСОТА В КАЖДОЙ КАПЛЕ\n"
             "ТИТРЫ: 3-6 | ПОПРОБУЙТЕ СЕГОДНЯ\n"
             "Цвет выбирается отдельной кнопкой «Цвет титров».")
        )
        return

    if action == "tv_engine_kling":
        await _handle_textvideo_engine_choice(update, context, q, "kling", prefix="fun")
        return

    if action == "tv_engine_runway":
        await _handle_textvideo_engine_choice(update, context, q, "runway", prefix="fun")
        return

    if action == "tv_prompt":
        await _handle_textvideo_prompt_choice(update, context, q, prefix="fun")
        return

    if action == "photoclip":
        await q.answer("Фото → видеоклип")
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "photoclip")
        await q.message.reply_text(_photoclip_menu_text(), parse_mode="Markdown", reply_markup=_photoclip_action_kb("fun"))
        return

    if action == "photoclip_upload":
        await q.answer("Загрузите фото")
        await _handle_photoclip_upload_choice(update, context, q, prefix="fun")
        return

    if action == "photoclip_last":
        await _handle_photoclip_prompt_choice(update, context, q, prefix="fun")
        return

    if action == "photoclip_custom":
        if _music_video_identity_complete(q.from_user.id):
            await _handle_photoclip_prompt_choice(update, context, q, prefix="fun")
        else:
            await q.answer("Сначала соберём Character Identity Pack")
            await _handle_photoclip_upload_choice(update, context, q, prefix="fun")
        return

    if action.startswith("pc_preset_"):
        kind = action.rsplit("_", 1)[-1]
        await _handle_photoclip_preset_choice(update, context, q, kind, prefix="fun")
        return

    if action == "aiselfie":
        await q.answer("AI-селфи")
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "aiselfie")
        await q.message.reply_text(
            _ai_selfie_menu_text(),
            parse_mode="Markdown",
            reply_markup=_ai_selfie_action_kb("fun"),
        )
        return

    if action == "faceswap":
        await q.answer("Замена лица")
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "faceswap")
        await _start_faceswap_flow(update, context, None, use_cached=False)
        return

    if action == "removebg":
        await q.answer("Удаление фона")
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "removebg")
        img = _get_cached_photo(q.from_user.id)
        if img:
            await q.message.reply_text("🧼 Использую последнее загруженное фото и удаляю фон.")
            await _pedit_removebg(update, context, img)
        else:
            _set_waiting_removebg(context)
            await q.message.reply_text("🧼 Пришлите фото — удалю фон и верну PNG с прозрачной подложкой.", reply_markup=_fun_quick_kb(q.from_user.id))
        return

    if action == "replacebg":
        await q.answer("Замена фона")
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "replacebg")
        img = _get_cached_photo(q.from_user.id)
        if img:
            await q.message.reply_text("🖼 Выберите новый фон для последнего загруженного фото:", reply_markup=background_presets_kb())
        else:
            context.user_data["photo_flow"] = "replacebg_menu"
            await q.message.reply_text("🖼 Пришлите фото. После загрузки я покажу варианты фона: пляж, горы, природа, город или свой текст.", reply_markup=_fun_quick_kb(q.from_user.id))
        return

    if action == "revive":
        if await _try_call("revive_old_photo_flow", "do_revive_photo"):
            return
        _set_waiting_photo_revival(update, context)
        await q.answer("Оживление фото")
        await q.message.reply_text(_fun_revive_help_text(), parse_mode="Markdown", reply_markup=_fun_quick_kb(q.from_user.id))
        return

    if action in {"smartreels", "reels"}:
        if await _try_call("smart_reels_from_video", "video_sense_reels"):
            return
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "fun_reels")
        context.user_data["awaiting_reels_material"] = True
        await q.answer("Reels / Shorts")
        await q.message.reply_text(_fun_reels_help_text(), parse_mode="Markdown", reply_markup=_fun_quick_kb(q.from_user.id))
        return

    if action == "film":
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "fun_film")
        context.user_data["awaiting_film_material"] = True
        await q.answer("Создать фильм")
        await q.message.reply_text(_fun_film_help_text(), parse_mode="Markdown", reply_markup=_fun_quick_kb(q.from_user.id))
        return

    if action == "clip":
        if await _try_call("start_runway_flow", "luma_make_clip", "runway_make_clip"):
            return
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "fun_reels")
        context.user_data["awaiting_reels_material"] = True
        await q.answer()
        await q.message.reply_text(_fun_reels_help_text(), parse_mode="Markdown", reply_markup=_fun_quick_kb(q.from_user.id))
        return

    if action == "img":
        if await _try_call("cmd_img", "midjourney_flow", "images_make"):
            return
        await q.answer()
        await q.message.reply_text("Введи /img и тему картинки, или пришли рефы.", reply_markup=_fun_quick_kb(q.from_user.id))
        return

    if action == "storyboard":
        if await _try_call("start_storyboard", "storyboard_make"):
            return
        await q.answer()
        await q.message.reply_text("Напиши тему шорта — накидаю структуру и раскадровку.", reply_markup=_fun_quick_kb(q.from_user.id))
        return

    if action == "music":
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "suno_music")
        context.user_data["awaiting_suno_brief"] = True
        await q.answer("Музыка / Suno")
        await _show_suno_help_from_callback(q, context, reply_markup=_suno_menu_kb(), submenu=True)
        return

    if action in {"ideas", "quiz", "speech", "free", "back"}:
        _clear_transient_flows(context)
        await q.answer()
        await q.message.reply_text(
            "Готов! Напиши задачу или выбери кнопку выше.",
            reply_markup=_fun_quick_kb(q.from_user.id)
        )
        return

    await q.answer()

# ───────── Роутеры-кнопки режимов (единая точка входа) ─────────
async def on_btn_study(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_transient_flows(context)
    _set_mode_clean(update.effective_user.id, "Учёба", "")
    fn = globals().get("_send_mode_menu")
    if callable(fn):
        return await fn(update, context, "study")
    return await on_mode_school_text(update, context)

async def on_btn_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_transient_flows(context)
    _set_mode_clean(update.effective_user.id, "Работа/Бизнес", "")
    fn = globals().get("_send_mode_menu")
    if callable(fn):
        return await fn(update, context, "work")
    return await on_mode_work_text(update, context)

async def on_btn_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_transient_flows(context)
    _set_mode_clean(update.effective_user.id, "Развлечения", "")
    fn = globals().get("_send_mode_menu")
    if callable(fn):
        return await fn(update, context, "fun")
    return await on_mode_fun_text(update, context)

async def on_btn_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _set_medical_waiting(update, context, "")
    await update.effective_message.reply_text(_medical_menu_text(), reply_markup=medicine_kb())

# ───────── Приоритетный роутер AI-видеоклипа ─────────
def _music_video_text_state(context: ContextTypes.DEFAULT_TYPE, user_id: int | None = None) -> str:
    """Активный этап PHOTO -> SONG -> VIDEO. Он всегда выше generic media/capability intents."""
    if context.user_data.get("awaiting_music_video_video_brief"):
        return "video"
    if context.user_data.get("awaiting_photo_clip_prompt") or context.user_data.get("awaiting_vocal_clip_prompt"):
        return "music"
    if context.user_data.get("music_video_draft_edit"):
        return "draft_edit"
    if user_id:
        with contextlib.suppress(Exception):
            track = (_mode_track_get(user_id) or "").strip().lower()
            if track in {"musicvideo:video", "vocalclip:video"}:
                return "video"
            if track in {"musicvideo:music", "vocalclip:music"}:
                return "music"
    return ""


async def on_music_video_text_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единственный владелец текста, пока активен мастер AI-видеоклипа."""
    uid = update.effective_user.id if update.effective_user else 0
    stage = _music_video_text_state(context, uid)
    if not stage:
        return

    if uid and not _get_cached_photo(uid):
        await update.effective_message.reply_text(
            "⚠️ Режим AI-видеоклипа активен, но исходное фото потеряно. Пришлите то же фото и начните клип снова."
        )
        raise ApplicationHandlerStop

    # VIDEO_BRIEF consumes here and never re-enters generic on_text intent routing.
    if stage == "video":
        music_brief = (context.user_data.get("music_video_music_brief") or "").strip()
        if not music_brief and uid:
            with contextlib.suppress(Exception):
                music_brief = (kv_get(f"music_video_music_brief:{uid}", "") or "").strip()
        if not music_brief:
            await update.effective_message.reply_text(
                "Черновик клипа потерял описание песни. Начните режим AI-видеоклипа ещё раз."
            )
            raise ApplicationHandlerStop
        context.user_data["music_video_music_brief"] = music_brief
        context.user_data["awaiting_music_video_video_brief"] = True
        with contextlib.suppress(Exception):
            if (_mode_track_get(uid) or "").strip().lower() == "vocalclip:video":
                context.user_data["vocal_clip_flow"] = True
        video_brief = (getattr(update.effective_message, "text", "") or "").strip()
        await _stage_music_video_draft(
            update, context, music_brief=music_brief, video_brief=video_brief
        )
        raise ApplicationHandlerStop

    await on_text(update, context)
    raise ApplicationHandlerStop

# ───────── Позитивный авто-ответ про возможности (текст/голос) ─────────
_CAPS_PATTERN = re.compile(
    r"(умеешь|можешь|делаешь|анализируешь|работаешь|поддерживаешь|умеет\s+ли|может\s+ли|можно\s+ли)"
    r".{0,160}"
    r"(pdf|epub|fb2|docx|txt|книг|книга|изображен|фото|фотограф|картин|ожив|анимир|"
    r"image|jpeg|png|video|видео|mp4|mov|аудио|audio|mp3|wav|"
    r"медицин|медкарт|выписк|анамнез|анализ|снимок|мрт|кт|заключени|врачебн|диагноз|узи|рентген|лицо|лица|лиц|faceswap|face\s*swap|музык|песн|трек|suno)",
    re.I | re.S,
)

async def on_capabilities_qa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    incoming_text = (getattr(update.effective_message, "text", "") or "").strip()
    # Stateful music-video prompts have priority over the generic capability matcher.
    # In particular, words such as "фотореализм" + "движение" inside VIDEO_BRIEF
    # must never reset the flow to ordinary photo revival.
    if any(context.user_data.get(key) for key in (
        "awaiting_photo_clip_prompt",
        "awaiting_vocal_clip_prompt",
        "awaiting_music_video_video_brief",
        "music_video_draft_edit",
    )):
        # This handler runs in an earlier PTB group than the general text handler.
        # Dispatch the active stateful flow here and stop propagation so a matching
        # capability phrase can never answer instead of consuming SONG/VIDEO input.
        await on_text(update, context)
        raise ApplicationHandlerStop
    # Never interpret a presentation brief as a generic capability/live-data question.
    studio = _presentation_studio_get()
    if update.effective_user and update.effective_chat and studio._active_project(update.effective_user.id, update.effective_chat.id):
        if await studio.handle_text(update, context, incoming_text):
            raise ApplicationHandlerStop
        return
    if _is_photo_revival_question(incoming_text) or _is_photo_revival_intent(incoming_text):
        _set_waiting_photo_revival(update, context)
    cap = capability_answer(incoming_text)
    if cap:
        await update.effective_message.reply_text(cap, reply_markup=main_kb)
        return

    msg = (
        "Да, умею работать с файлами, медиа и медицинскими материалами:\n"
        "• 📄 Документы: PDF/EPUB/FB2/DOCX/TXT — конспект, резюме, извлечение таблиц, проверка фактов.\n"
        "• 🖼 Изображения: анализ/описание, удаление и замена фона, замена лица, ретушь, outpaint.\n"
        "• ✨ Оживление фото: загрузи фото — можно выбрать Runway, Kling или Sora 2 только для кадров без людей.\n"
        "• 🎞 Видео: разбор смысла, таймкоды, *Reels из длинного видео*, идеи/скрипт, субтитры.\n"
        "• 🎧 Аудио/книги: транскрипция, тезисы, план.\n"
        "• 🩺 Медицина: выписки, анамнез, заключения, анализы, снимки, МРТ/КТ — справочный разбор и вопросы врачу.\n\n"
        "_Подсказки:_ просто загрузите файл или пришлите ссылку + короткое ТЗ. "
        "Для фото — можно нажать «✨ Оживить», для видео — «🎬 Reels из длинного видео»."
    )
    await update.effective_message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=_fun_quick_kb(update.effective_user.id),
    )


# ───────── v98 LIVE SEARCH DIAGNOSTICS / PROVIDER HARDENING ─────────
# Tavily is the primary retrieval provider. OpenAI Responses web_search is the
# fallback only when OPENAI_API_KEY is an official OpenAI key (not sk-or-*).
_LIVE_SEARCH_LAST_STATUS: dict[str, dict] = {
    "tavily": {"state": "not_tested", "detail": ""},
    "openai": {"state": "not_tested", "detail": ""},
    "summary": {"state": "not_tested", "detail": ""},
}


def _masked_key_state(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "off"
    return f"on ({value[:4]}…{value[-4:]}, len={len(value)})"


def _official_openai_web_key_available() -> bool:
    key = (OPENAI_API_KEY or "").strip()
    return bool(key and not key.startswith("sk-or-"))


def _live_search_failure_message() -> str:
    tavily_state = _LIVE_SEARCH_LAST_STATUS.get("tavily", {}).get("state", "not_tested")
    openai_state = _LIVE_SEARCH_LAST_STATUS.get("openai", {}).get("state", "not_tested")
    if not TAVILY_API_KEY and not _official_openai_web_key_available():
        return (
            "⚠️ Live-поиск сейчас не настроен: отсутствует TAVILY_API_KEY, а OPENAI_API_KEY "
            "не является официальным ключом OpenAI для резервного web-search. "
            "Обычный GPT-чат продолжает работать. Администратору: выполните /diag_live_search."
        )
    if tavily_state in {"unauthorized", "quota", "http_error", "network_error"}:
        return (
            "⚠️ Не удалось получить свежие данные через Tavily. Обычный GPT-чат продолжает работать. "
            "Ключ может быть недействительным, исчерпан лимит или провайдер временно недоступен. "
            "Администратору: выполните /diag_live_search и /test_live_search."
        )
    if openai_state in {"unauthorized", "quota", "http_error", "network_error"}:
        return (
            "⚠️ Основной live-поиск не вернул результат, а резервный web-search OpenAI также недоступен. "
            "Обычный GPT-чат продолжает работать. Администратору: выполните /diag_live_search."
        )
    return (
        "⚠️ Сейчас не удалось получить свежие данные из интернета. Обычный GPT-чат продолжает работать. "
        "Попробуйте повторить запрос; администратору доступна проверка /test_live_search."
    )


async def _tavily_live_search_context(query: str) -> str | None:
    """Current Tavily Search API: Bearer authentication plus structured status."""
    if not TAVILY_API_KEY:
        _LIVE_SEARCH_LAST_STATUS["tavily"] = {"state": "missing_key", "detail": "TAVILY_API_KEY is empty"}
        return None
    original_query = (query or "").strip()
    search_query = _live_search_query_with_date(original_query)
    is_news = _is_news_intent(original_query)
    has_relative_date = bool(_RELATIVE_DATE_RE.search(original_query))
    payload = {
        "query": search_query,
        "search_depth": "advanced" if (is_news or has_relative_date) else "basic",
        "topic": "news" if is_news else "general",
        "include_answer": False,
        "include_raw_content": False,
        "max_results": LIVE_SEARCH_NEWS_MAX_RESULTS if is_news else 5,
    }
    if is_news or has_relative_date:
        payload["time_range"] = LIVE_SEARCH_TODAY_TIME_RANGE if has_relative_date else LIVE_SEARCH_RECENT_TIME_RANGE
    headers = {
        "Authorization": f"Bearer {TAVILY_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=LIVE_SEARCH_TIMEOUT_S, follow_redirects=True) as client:
            r = await client.post("https://api.tavily.com/search", headers=headers, json=payload)
        if r.status_code in (401, 403):
            _LIVE_SEARCH_LAST_STATUS["tavily"] = {"state": "unauthorized", "detail": f"HTTP {r.status_code}: {r.text[:240]}"}
            log.warning("Tavily authorization failed HTTP %s: %s", r.status_code, r.text[:300])
            return None
        if r.status_code == 429:
            _LIVE_SEARCH_LAST_STATUS["tavily"] = {"state": "quota", "detail": f"HTTP 429: {r.text[:240]}"}
            log.warning("Tavily quota/rate limit: %s", r.text[:300])
            return None
        if r.status_code // 100 != 2:
            _LIVE_SEARCH_LAST_STATUS["tavily"] = {"state": "http_error", "detail": f"HTTP {r.status_code}: {r.text[:240]}"}
            log.warning("Tavily HTTP %s: %s", r.status_code, r.text[:300])
            return None
        js = r.json() or {}
        results = js.get("results") or []
        parts = []
        for idx, item in enumerate(results, 1):
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "Без названия").strip()
            url = (item.get("url") or "").strip()
            content = (item.get("content") or "").strip()
            published = item.get("published_date") or item.get("publishedDate") or item.get("date") or "дата не указана"
            if url or content:
                parts.append(
                    f"[{idx}] {title}\nДата публикации/обновления: {published}\nURL: {url}\nФрагмент: {content[:1100]}"
                )
        if not parts:
            _LIVE_SEARCH_LAST_STATUS["tavily"] = {"state": "empty", "detail": "HTTP 200, results empty"}
            return None
        _LIVE_SEARCH_LAST_STATUS["tavily"] = {"state": "ok", "detail": f"HTTP 200, results={len(parts)}"}
        return "\n\n".join(parts)
    except Exception as exc:
        _LIVE_SEARCH_LAST_STATUS["tavily"] = {"state": "network_error", "detail": repr(exc)[:240]}
        log.warning("Tavily live search failed: %s", exc)
        return None


async def openai_live_web_search(user_text: str) -> str | None:
    """Official OpenAI Responses API + hosted web_search tool."""
    api_key = (OPENAI_API_KEY or "").strip()
    if not api_key:
        _LIVE_SEARCH_LAST_STATUS["openai"] = {"state": "missing_key", "detail": "OPENAI_API_KEY is empty"}
        return None
    if api_key.startswith("sk-or-"):
        _LIVE_SEARCH_LAST_STATUS["openai"] = {"state": "ineligible_key", "detail": "OpenRouter key cannot call api.openai.com"}
        return None
    if not LIVE_SEARCH_ENABLED:
        _LIVE_SEARCH_LAST_STATUS["openai"] = {"state": "disabled", "detail": "LIVE_SEARCH_ENABLED=0"}
        return None
    system_text = (
        "Ты live-поисковый помощник внутри Telegram-бота Neyro-Bot GPT 5 Studio. "
        + _current_date_system_text() + " "
        "Отвечай по-русски, кратко и по делу. Используй веб-поиск для свежих данных. "
        "Не называй старые события сегодняшними. В конце дай источники."
    )
    payload = {
        "model": OPENAI_WEB_SEARCH_MODEL,
        "input": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": _live_search_query_with_date(user_text)},
        ],
        "tools": [{"type": "web_search", "search_context_size": "low"}],
        "tool_choice": "auto",
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=max(30.0, LIVE_SEARCH_TIMEOUT_S), follow_redirects=True) as client:
            r = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
        if r.status_code in (401, 403):
            _LIVE_SEARCH_LAST_STATUS["openai"] = {"state": "unauthorized", "detail": f"HTTP {r.status_code}: {r.text[:240]}"}
            log.warning("OpenAI live search auth HTTP %s: %s", r.status_code, r.text[:300])
            return None
        if r.status_code == 429:
            _LIVE_SEARCH_LAST_STATUS["openai"] = {"state": "quota", "detail": f"HTTP 429: {r.text[:240]}"}
            log.warning("OpenAI live search quota: %s", r.text[:300])
            return None
        if r.status_code // 100 != 2:
            _LIVE_SEARCH_LAST_STATUS["openai"] = {"state": "http_error", "detail": f"HTTP {r.status_code}: {r.text[:240]}"}
            log.warning("OpenAI live search HTTP %s: %s", r.status_code, r.text[:300])
            return None
        txt = _extract_openai_response_text(r.json())
        if not txt:
            _LIVE_SEARCH_LAST_STATUS["openai"] = {"state": "empty", "detail": "HTTP 200, output text empty"}
            return None
        _LIVE_SEARCH_LAST_STATUS["openai"] = {"state": "ok", "detail": f"HTTP 200, chars={len(txt)}"}
        return txt[:3900]
    except Exception as exc:
        _LIVE_SEARCH_LAST_STATUS["openai"] = {"state": "network_error", "detail": repr(exc)[:240]}
        log.warning("OpenAI live search failed: %s", exc)
        return None


async def cmd_diag_live_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    official_openai = _official_openai_web_key_available()
    lines = [
        f"🌐 Live Search diagnostic / {PATCH_VERSION}",
        f"enabled={LIVE_SEARCH_ENABLED}",
        f"timezone={APP_TIMEZONE}",
        f"timeout_s={LIVE_SEARCH_TIMEOUT_S}",
        f"tavily_key={_masked_key_state(TAVILY_API_KEY)}",
        f"openai_key={_masked_key_state(OPENAI_API_KEY)}",
        f"openai_official_web_eligible={official_openai}",
        f"openai_web_model={OPENAI_WEB_SEARCH_MODEL}",
        f"tavily_last={_LIVE_SEARCH_LAST_STATUS.get('tavily')}",
        f"openai_last={_LIVE_SEARCH_LAST_STATUS.get('openai')}",
        "Проверка сети и ключей: /test_live_search",
    ]
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_test_live_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("🌐 Проверяю Tavily и резервный web-search OpenAI…")
    query = "Какие официальные новости OpenAI опубликованы за последние 7 дней?"
    tavily_ctx = await _tavily_live_search_context(query)
    tavily_status = _LIVE_SEARCH_LAST_STATUS.get("tavily", {})
    openai_answer = None
    # Test OpenAI fallback independently only when it is actually configured.
    if _official_openai_web_key_available():
        openai_answer = await openai_live_web_search("Назови одну актуальную официальную новость OpenAI за последние 7 дней и источник.")
    openai_status = _LIVE_SEARCH_LAST_STATUS.get("openai", {})
    lines = [
        "Результат проверки live-поиска:",
        f"Tavily: {tavily_status.get('state')} — {tavily_status.get('detail', '')}",
        f"OpenAI web fallback: {openai_status.get('state')} — {openai_status.get('detail', '')}",
    ]
    if tavily_ctx:
        lines.append("✅ Основной live-поиск Tavily работает.")
    elif openai_answer:
        lines.append("✅ Резервный live-поиск OpenAI работает; Tavily требует проверки.")
    else:
        lines.append("❌ Ни один live-провайдер не прошёл тест. Проверьте ключи/лимиты в Render.")
    await update.effective_message.reply_text("\n".join(lines)[:3900])


def _presentation_update_token(update: Update) -> str:
    """Stable token preventing one Telegram update from being routed twice."""
    update_id = getattr(update, "update_id", None)
    message = getattr(update, "effective_message", None)
    message_id = getattr(message, "message_id", None)
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    return f"{update_id}:{chat_id}:{message_id}"


async def on_presentation_text_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hard-stop all generic text handlers while Presentation Studio owns the chat."""
    if not update.effective_user or not update.effective_chat or not update.effective_message:
        return
    text = (getattr(update.effective_message, "text", "") or "").strip()
    if not text:
        return
    token = _presentation_update_token(update)
    if context.chat_data.get("_presentation_last_update_token") == token:
        raise ApplicationHandlerStop
    studio = _presentation_studio_get()
    project = studio._active_project(update.effective_user.id, update.effective_chat.id)
    if not project:
        return
    # Mark before I/O so a second handler in this process cannot repeat the reply.
    context.chat_data["_presentation_last_update_token"] = token
    handled = await studio.handle_text(update, context, text)
    if not handled:
        await update.effective_message.reply_text(
            "Проект презентации активен. На этом этапе используйте кнопки мастера или нажмите «Продолжить»."
        )
    raise ApplicationHandlerStop


# ───────── Вспомогательное: взять первую объявленную функцию по имени ─────────
def _pick_first_defined(*names):
    for n in names:
        fn = globals().get(n)
        if callable(fn):
            return fn
    return None

# ───────── Telegram profile setup ─────────
async def _post_init_bot_profile(app):
    """Обновляет профиль и системную кнопку меню Telegram после запуска."""
    if AUTO_SET_BOT_PROFILE:
        try:
            if BOT_PUBLIC_NAME:
                await app.bot.set_my_name(name=BOT_PUBLIC_NAME)
            if BOT_SHORT_DESCRIPTION:
                await app.bot.set_my_short_description(short_description=BOT_SHORT_DESCRIPTION)
            if BOT_DESCRIPTION:
                await app.bot.set_my_description(description=BOT_DESCRIPTION)
            log.info("Telegram bot profile updated: %s", BOT_PUBLIC_NAME)
        except Exception as e:
            log.warning("Telegram bot profile update skipped: %s", e)

    if AUTO_SET_BOT_MENU:
        try:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text=BOT_MENU_TEXT,
                    web_app=WebAppInfo(url=TARIFF_URL),
                )
            )
            log.info("Telegram menu button updated: %s -> %s", BOT_MENU_TEXT, TARIFF_URL)
        except Exception as e:
            log.warning("Telegram menu button update skipped: %s", e)

    try:
        from property_video_execution import recover_after_restart
        app.create_task(recover_after_restart(app), update=None, name="property-video-restart-recovery")
    except Exception as e:
        log.warning("Property video restart recovery was not scheduled: %s", e)


# ───────── Регистрация хендлеров и запуск ─────────
def build_application() -> "Application":
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в переменных окружения.")

    builder = ApplicationBuilder().token(BOT_TOKEN)
    # Opt-in only: do not redirect production until a local Bot API server is healthy.
    local_api_url = (os.environ.get("TELEGRAM_LOCAL_API_URL") or "").strip().rstrip("/")
    if local_api_url:
        if not local_api_url.startswith(("http://", "https://")):
            raise RuntimeError("TELEGRAM_LOCAL_API_URL must be an HTTP(S) URL")
        builder = builder.base_url(local_api_url + "/bot").base_file_url(local_api_url + "/file/bot").local_mode(True)
        log.info("Telegram local Bot API enabled (endpoint configured)")
    # Keep restart recovery active even when profile/menu automation is disabled.
    builder = builder.post_init(_post_init_bot_profile)
    app = builder.build()

    # Telegram local/cloud migration can deliver the SAME message with different
    # update_id values. Deduplicate by stable Telegram object identity instead.
    # This handler runs before all business handlers, across all update types.
    from telegram.ext import TypeHandler

    async def _claim_incoming_telegram_event(update, context):
        q = getattr(update, "callback_query", None)
        m = getattr(update, "message", None)
        if m is None:
            m = getattr(update, "edited_message", None)
        if m is None:
            m = getattr(update, "channel_post", None)
        if m is None:
            m = getattr(update, "edited_channel_post", None)
        if q is not None:
            identity = "callback:" + str(q.id)
        elif m is not None and getattr(m, "chat_id", None) is not None:
            kind = "edited" if getattr(update, "edited_message", None) is not None or getattr(update, "edited_channel_post", None) is not None else "message"
            edit_ts = getattr(m, "edit_date", None)
            identity = f"{kind}:{m.chat_id}:{m.message_id}" + (f":{edit_ts.isoformat()}" if edit_ts else "")
        else:
            # Other Telegram update classes: preserve normal handling.
            return
        try:
            with sqlite3.connect(DB_PATH, timeout=20) as con:
                con.execute("BEGIN IMMEDIATE")
                con.execute("CREATE TABLE IF NOT EXISTS processed_telegram_events (identity TEXT PRIMARY KEY, created_at INTEGER NOT NULL)")
                now = int(time.time())
                con.execute("DELETE FROM processed_telegram_events WHERE created_at < ?", (now - 7 * 86400,))
                inserted = con.execute(
                    "INSERT OR IGNORE INTO processed_telegram_events(identity, created_at) VALUES (?, ?)",
                    (identity, now),
                ).rowcount == 1
            if not inserted:
                log.warning("TELEGRAM_EVENT_DUPLICATE identity=%s update_id=%s", identity, update.update_id)
                raise ApplicationHandlerStop
        except ApplicationHandlerStop:
            raise
        except Exception:
            log.exception("Telegram event dedupe DB unavailable, update_id=%s", update.update_id)
            # Avoid taking down the bot if the dedupe database is unavailable.
            return

    app.add_handler(TypeHandler(Update, _claim_incoming_telegram_event), group=-100)

    # Команды
    app.add_handler(CommandHandler("veo_recover", cmd_veo_recover))
    app.add_handler(CommandHandler("heygen", cmd_heygen))
    app.add_handler(CommandHandler("veo_extend", cmd_veo_extend))
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("help",         cmd_help))
    app.add_handler(CommandHandler("examples",     cmd_examples))
    from neyrobot_prod.studio_prompt_handlers import cmd_studio_prompts, cb_studio_prompts
    app.add_handler(CommandHandler("prompts", cmd_studio_prompts))
    app.add_handler(CommandHandler("version",      cmd_version))
    app.add_handler(CommandHandler("engines",      cmd_engines))
    app.add_handler(CommandHandler("plans",        cmd_plans))
    app.add_handler(CommandHandler("balance",      cmd_balance))
    app.add_handler(CommandHandler("prices",       cmd_prices))
    app.add_handler(CommandHandler("set_welcome",  cmd_set_welcome))
    app.add_handler(CommandHandler("show_welcome", cmd_show_welcome))
    app.add_handler(CommandHandler("diag_limits",  cmd_diag_limits))
    app.add_handler(CommandHandler("diag_access",  cmd_diag_access))
    app.add_handler(CommandHandler("diag_stt",     cmd_diag_stt))
    app.add_handler(CommandHandler("diag_images",  cmd_diag_images))
    app.add_handler(CommandHandler("diag_video",   cmd_diag_video))
    app.add_handler(CommandHandler("diag_runway",  cmd_diag_runway))
    app.add_handler(CommandHandler("diag_yookassa", cmd_diag_yookassa))
    app.add_handler(CommandHandler("provider_status", cmd_provider_status))
    app.add_handler(CommandHandler("diag_bg",      cmd_diag_bg))
    app.add_handler(CommandHandler("diag_face",    cmd_diag_face))
    app.add_handler(CommandHandler("diag_suno",    cmd_diag_suno))
    app.add_handler(CommandHandler("img",          cmd_img))
    app.add_handler(CommandHandler("mj",           cmd_midjourney))
    app.add_handler(CommandHandler("midjourney",   cmd_midjourney))
    app.add_handler(CommandHandler("presentation", cmd_presentation))
    app.add_handler(CommandHandler("catalog",      cmd_catalog))
    app.add_handler(CommandHandler("diag_presentation", cmd_diag_presentation))
    app.add_handler(CommandHandler("diag_live_search", cmd_diag_live_search))
    app.add_handler(CommandHandler("test_live_search", cmd_test_live_search))
    app.add_handler(CommandHandler("chats",        cmd_chats))
    app.add_handler(CommandHandler("newchat",      cmd_newchat))
    app.add_handler(CommandHandler("music",       cmd_music))
    app.add_handler(CommandHandler("voice_on",     cmd_voice_on))
    app.add_handler(CommandHandler("voice_off",    cmd_voice_off))
    app.add_handler(CommandHandler("medicine",     cmd_mode_medicine))

    # Платежи
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    # >>> PATCH START — Handlers wiring (WebApp + callbacks + media + text) >>>

    # Данные из мини-приложения (WebApp)
    with contextlib.suppress(Exception):
        app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_webapp_data))
    with contextlib.suppress(Exception):
        if hasattr(filters, "WEB_APP_DATA"):
            app.add_handler(MessageHandler(filters.WEB_APP_DATA, on_webapp_data))

    # === ПАТЧ 4: Порядок callback-хендлеров (узкие → общие) ===
    # 1) Подписка/оплаты
    async def _studio_director_quote_callback(update, context):
        q = update.callback_query
        await q.answer()
        draft = context.user_data.get("studio_prompt_draft")
        if not draft:
            await q.message.reply_text("Черновик не найден. Начните с /prompts.")
            return
        import re
        match = re.search(r"(?i)(\\d+)\\s*(?:секунд(?:ы|у)?|сек(?:унд)?|с)(?![а-яa-z])", draft)
        duration = max(4, min(30, int(match.group(1)) if match else 20))
        # This is an illustrative one-scene baseline, NOT a final payable quote:
        # the LLM scene planner determines the actual number and lengths.
        baseline = _video_provider_cost_usd("seedance", duration)
        await q.message.reply_text(
            f"💳 Ориентир для Seedance: {duration} сек, одна сцена — "
            f"{_retail_credits(baseline)} кредитов.\\n"
            "Это НЕ окончательная цена: Авторежиссёр может создать несколько сцен. "
            "Точная сумма рассчитывается после составления плана сцен. "
            "Генерация не запущена, списаний нет."
        )

    app.add_handler(CallbackQueryHandler(_studio_director_quote_callback, pattern=r"^spl:director:quote$"))
    app.add_handler(CallbackQueryHandler(cb_studio_prompts, pattern=r"^spl:"))
    app.add_handler(CallbackQueryHandler(on_cb_plans, pattern=r"^(?:plan:|pay:)$|^(?:plan:|pay:).+"))

    async def _on_ad_caption_style_callback(update, context):
        q = update.callback_query
        style = (q.data or "").split(":")[-1]
        if style not in {"white", "black", "auto"}:
            await q.answer("Недопустимый режим", show_alert=True)
            raise ApplicationHandlerStop
        context.user_data["ad_caption_style"] = style
        label = {"white": "белый", "black": "чёрный", "auto": "автоконтраст"}[style]
        await q.answer("Стиль сохранён")
        await q.message.reply_text(f"🔤 Стиль титров: {label}.")
        raise ApplicationHandlerStop

    app.add_handler(CallbackQueryHandler(_on_ad_caption_style_callback, pattern=r"^adstyle:(white|black|auto)$"))

    # Explicit high-priority Video Studio callback routing, independent of legacy fun/act routers.
    async def _on_video_studio_engine_callback(update, context):
        q = update.callback_query
        action = (q.data or "").rsplit(":", 1)[-1]
        engines = {"tv_engine_seedance": "seedance", "tv_engine_veo": "veo",
                   "tv_engine_kling": "kling", "tv_engine_sora": "sora",
                   "tv_engine_runway": "runway"}
        try:
            await _handle_textvideo_engine_choice(update, context, q, engines[action], prefix="fun")
        except Exception:
            log.exception("Video Studio engine selection failed: %s", action)
            with contextlib.suppress(Exception):
                await q.answer("Ошибка выбора движка", show_alert=True)
            with contextlib.suppress(Exception):
                await q.message.reply_text("Не удалось открыть движок. Повторите выбор.")
        raise ApplicationHandlerStop

    async def _on_seedance_duration_callback(update, context):
        q = update.callback_query
        seconds = int((q.data or "").split(":")[-1])
        if seconds not in (4, 8, 10, 15, 20, 30):
            await q.answer("Недопустимая длительность", show_alert=True)
            raise ApplicationHandlerStop
        context.user_data["seedance_text_duration"] = seconds
        _set_text_video_wait(context, "seedance")
        await q.answer(f"Seedance: {seconds} сек")
        await q.message.reply_text(
            f"✅ Seedance 2.5 · {seconds} секунд · 9:16. Теперь отправьте промпт. "
            "Стоимость будет рассчитана для выбранной длительности.",
            reply_markup=_seedance_duration_keyboard(context),
        )
        raise ApplicationHandlerStop

    app.add_handler(CallbackQueryHandler(
        _on_seedance_duration_callback,
        pattern=r"^seedance_duration:(?:4|8|10|15|20|30)$"
    ), group=-2)

    app.add_handler(CallbackQueryHandler(
        _on_video_studio_engine_callback,
        pattern=r"^(?:fun:|act:fun:)tv_engine_(?:seedance|veo|kling|sora|runway)$"
    ), group=-1)

    # 2) Новые режимы/подменю: mode:* и act:* (Учёба/Работа/Развлечения/Медицина)
    app.add_handler(CallbackQueryHandler(on_mode_cb, pattern=r"^(?:mode:|act:)"), group=0)
    app.add_handler(CallbackQueryHandler(_on_kling_video_option, pattern=r"^tvopt:(?:dur:(?:5|10|15|30|60)|sound:(?:on|off))$"), group=0)
    app.add_handler(CallbackQueryHandler(_on_veo_video_option, pattern=r"^veoopt:dur:(?:8|15|24|30|60)$"), group=0)

    # Music-video draft approval: consumed once before the generic callback router.
    app.add_handler(CallbackQueryHandler(_on_music_video_draft_callback, pattern=r"^mv:(?:approve|augment|rewrite|auto|voice|dur10|dur30|dur60|dur90):[0-9a-f]{12}$"), group=0)
    app.add_handler(CallbackQueryHandler(_on_vocal_artifact_callback, pattern=r"^mvfile:(?:audio|use|video|approveaudio|regenaudio|editaudio|resume):[0-9a-f]{12}$"), group=0)

    # 2b) Старые school:/work: callbacks, если такие кнопки ещё где-то используются
    app.add_handler(CallbackQueryHandler(on_cb_mode, pattern=r"^(?:school:|work:)"), group=0)

    # 3) Быстрые развлечения (любые fun:...)
    from neyrobot_prod.entertainment.production import handle_production_brief
    from neyrobot_prod.entertainment.game_telegram import handle_game_callback
    from neyrobot_prod.entertainment.leisure import handle_leisure_callback
    app.add_handler(CallbackQueryHandler(handle_production_brief, pattern=r"^ent:brief:"), group=0)
    app.add_handler(CallbackQueryHandler(on_cb_entertainment, pattern=r"^ent:"))
    app.add_handler(CallbackQueryHandler(handle_game_callback, pattern=r"^game:"), group=0)
    app.add_handler(CallbackQueryHandler(handle_leisure_callback, pattern=r"^leisure:"), group=0)
    app.add_handler(CallbackQueryHandler(on_cb_fun,   pattern=r"^fun:[a-z_]+$"))

    # 3b) Подменю Suno: свободный запрос и пресеты
    app.add_handler(CallbackQueryHandler(on_cb_suno,  pattern=r"^suno:"), group=0)

    # 4) Остальной catch-all (pedit/topup/engine/buy и т.п.)
    # Размещаем в приоритетной группе, чтобы колбэки обрабатывались сразу
    app.add_handler(CallbackQueryHandler(on_cb), group=0)

    # Selected text-to-video engine owns the next prompt before generic AI routing.
    async def _route_selected_text_video(update, context):
        if not context.user_data.get("awaiting_text_video_prompt"):
            return
        incoming = (getattr(update.effective_message, "text", "") or "").strip()
        if not incoming:
            return
        # Preserve the selection until _start_text_video has inspected it.
        await _start_text_video(update, context, incoming)
        _clear_text_video_wait(context)
        raise ApplicationHandlerStop

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _route_selected_text_video), group=-3)

    # Active AI-videoclip state owns text before presentation/capability/generic media routing.
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_music_video_text_priority),
        group=-2,
    )

    # Presentation Studio owns active presentation/catalog chats before every other text handler.
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_presentation_text_priority),
        group=-1,
    )

    # Голос/аудио — относим к медиагруппе (идёт раньше общего текстового хендлера)
    voice_fn = _pick_first_defined("handle_voice", "on_voice", "voice_handler")
    if voice_fn:
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_fn), group=1)

    # Текстовые кнопки/ярлыки (остальные) — ЧИСТО без дублей
    import re

    # Строгие паттерны: одно название = один хендлер (эмодзи допускаем, лишние пробелы — тоже)
    BTN_ENGINES = re.compile(r"^\s*(?:🧠\s*)?Движки\s*$")
    BTN_BALANCE = re.compile(r"^\s*(?:💳|🧾)?\s*Баланс\s*$")
    BTN_PLANS   = re.compile(r"^\s*(?:⭐\s*)?Подписка(?:\s*[·•]\s*Помощь)?\s*$")
    BTN_STUDY   = re.compile(r"^\s*(?:🎓\s*)?Уч[её]ба\s*$")
    BTN_WORK    = re.compile(r"^\s*(?:💼\s*)?(?:Работа(?:\s*/\s*Бизнес)?|Бизнес)\s*$")
    BTN_FUN     = re.compile(r"^\s*(?:🔥\s*)?Развлечения\s*$")
    BTN_MED     = re.compile(r"^\s*(?:🩺|⚕️)?\s*Медицина\s*$")
    BTN_CHATS   = re.compile(r"^\s*(?:💬\s*)?Мои чаты\s*$", re.I)
    BTN_NEWCHAT = re.compile(r"^\s*(?:➕\s*)?Новый чат\s*$", re.I)

    # Кнопки в приоритетной группе (0), чтобы они срабатывали раньше любых общих обработчиков
    app.add_handler(MessageHandler(filters.Regex(BTN_ENGINES), on_btn_engines), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_BALANCE), on_btn_balance), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_PLANS),   on_btn_plans),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_STUDY),   on_btn_study),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_WORK),    on_btn_work),    group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_FUN),     on_btn_fun),     group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_MED),     on_btn_medicine), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_CHATS),   cmd_chats), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_NEWCHAT), cmd_newchat), group=0)

    # Generic photo-revival regex interceptor removed: explicit revival commands are routed only by on_text.\n    # ➕ Позитивный авто-ответ на «а умеешь ли…» — до общего текста (отдельная группа, ниже кнопок)
    app.add_handler(MessageHandler(filters.Regex(_CAPS_PATTERN), on_capabilities_qa), group=1)

    # Медиа (фото/доки/видео/гиф) — тоже перед общим текстом
    photo_fn = _pick_first_defined("handle_photo", "on_photo", "photo_handler", "handle_image_message")
    if photo_fn:
        app.add_handler(MessageHandler(filters.PHOTO, photo_fn), group=1)

    doc_fn = _pick_first_defined("handle_doc", "on_doc", "on_document", "handle_document", "doc_handler")
    if doc_fn:
        app.add_handler(MessageHandler(filters.Document.ALL, doc_fn), group=1)

    video_fn = _pick_first_defined("handle_video", "on_video", "video_handler")
    if video_fn:
        app.add_handler(MessageHandler(filters.VIDEO, video_fn), group=1)

    gif_fn = _pick_first_defined("handle_gif", "on_gif", "animation_handler")
    if gif_fn:
        app.add_handler(MessageHandler(filters.ANIMATION, gif_fn), group=1)

    # >>> PATCH END <<<

    # Общий текст — САМЫЙ последний (ниже всех частных кейсов)
    text_fn = _pick_first_defined("handle_text", "on_text", "text_handler", "default_text_handler")
    if text_fn:
        btn_filters = (filters.Regex(BTN_ENGINES) | filters.Regex(BTN_BALANCE) |
                       filters.Regex(BTN_PLANS)   | filters.Regex(BTN_STUDY)   |
                       filters.Regex(BTN_WORK)    | filters.Regex(BTN_FUN) |
                       filters.Regex(BTN_MED)     | filters.Regex(BTN_CHATS) |
                       filters.Regex(BTN_NEWCHAT))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~btn_filters, text_fn), group=2)

    # Ошибки
    err_fn = _pick_first_defined("on_error", "handle_error")
    if err_fn:
        app.add_error_handler(err_fn)

    return app


# === main() с безопасной инициализацией БД (без изменений по сути) ===
def main():
    log.info("Starting bot patch version: %s", PATCH_VERSION)
    with contextlib.suppress(Exception):
        db_init()
    with contextlib.suppress(Exception):
        db_init_usage()
    with contextlib.suppress(Exception):
        _chat_memory_init()
    with contextlib.suppress(Exception):
        _db_init_prefs()

    app = build_application()

    if USE_WEBHOOK:
        _install_webapp_checkout_bridge(app)
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
