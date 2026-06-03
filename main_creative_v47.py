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
    from PIL import Image, ImageFilter, ImageOps
except Exception:
    Image = None
    ImageFilter = None
try:
    from rembg import remove as rembg_remove
    REMBG_IMPORT_ERROR = ""
except Exception as _rembg_e:
    rembg_remove = None
    REMBG_IMPORT_ERROR = repr(_rembg_e)

# ───────── LOGGING ─────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")

PATCH_VERSION = "v46-comet-bg-remove-2026-06-02"

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

BOT_TOKEN = (os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
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
TTS_MAX_CHARS        = int(os.environ.get("TTS_MAX_CHARS", "1000") or "1000")

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
RUNWAY_API_VERSION = os.environ.get("RUNWAY_API_VERSION", "2024-11-06").strip()
RUNWAY_USE_COMET   = os.environ.get("RUNWAY_USE_COMET", "1").strip().lower() not in ("0", "false", "no", "off")

# CometAPI / Sora / Kling wrappers for image→video
COMET_API_KEY  = (os.environ.get("COMET_API_KEY") or os.environ.get("COMETAPI_KEY") or "").strip()
COMET_BASE_URL = os.environ.get("COMET_BASE_URL", "https://api.cometapi.com").strip().rstrip("/")
RUNWAY_COMET_CREATE_PATH = os.environ.get("RUNWAY_COMET_CREATE_PATH", "/runwayml/v1/image_to_video").strip() or "/runwayml/v1/image_to_video"
RUNWAY_COMET_STATUS_PATH = os.environ.get("RUNWAY_COMET_STATUS_PATH", "/runwayml/v1/tasks/{id}").strip() or "/runwayml/v1/tasks/{id}"
SORA_API_KEY   = (os.environ.get("SORA_API_KEY") or COMET_API_KEY).strip()
SORA_MODEL     = os.environ.get("SORA_MODEL", "sora-2").strip()
# Защита от старого ENV Render: если там случайно осталось sora-1,
# Comet возвращает model_not_found. Для этой сборки принудительно используем sora-2.
if SORA_MODEL.lower() in ("", "sora", "sora-1", "sora1"):
    SORA_MODEL = "sora-2"
SORA_CREATE_PATH = os.environ.get("SORA_CREATE_PATH", "/v1/videos").strip() or "/v1/videos"
SORA_STATUS_PATH = os.environ.get("SORA_STATUS_PATH", "/v1/videos/{id}").strip() or "/v1/videos/{id}"
KLING_API_KEY  = (os.environ.get("KLING_API_KEY") or COMET_API_KEY).strip()
KLING_MODEL    = os.environ.get("KLING_MODEL", "kling-v1-6").strip()
KLING_CREATE_PATH = os.environ.get("KLING_CREATE_PATH", "/kling/v1/videos/image2video").strip() or "/kling/v1/videos/image2video"
KLING_STATUS_PATH = os.environ.get("KLING_STATUS_PATH", "/kling/v1/videos/image2video/{id}").strip() or "/kling/v1/videos/image2video/{id}"
# Text→Video через CometAPI. Luma временно скрыта; текстовое/голосовое видео выбирается только между Sora 2 и Kling. Runway оставлен только для оживления фото.
KLING_TEXT_CREATE_PATH = os.environ.get("KLING_TEXT_CREATE_PATH", "/kling/v1/videos/text2video").strip() or "/kling/v1/videos/text2video"
KLING_TEXT_STATUS_PATH = os.environ.get("KLING_TEXT_STATUS_PATH", "/kling/v1/videos/text2video/{id}").strip() or "/kling/v1/videos/text2video/{id}"
SORA_UNIT_COST_USD = _env_float("SORA_UNIT_COST_USD", 0.15)
SORA_PRO_UNIT_COST_USD = _env_float("SORA_PRO_UNIT_COST_USD", 0.30)
KLING_UNIT_COST_USD = _env_float("KLING_UNIT_COST_USD", 0.40)


# Creative Router / AI Reels Studio / extra Comet video engines
COMET_OPENAI_BASE_URL = os.environ.get("COMET_OPENAI_BASE_URL", f"{COMET_BASE_URL}/v1").strip().rstrip("/")
AUTO_ENGINE_ENABLED = os.environ.get("AUTO_ENGINE_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
AUTO_ENGINE_DEFAULT = os.environ.get("AUTO_ENGINE_DEFAULT", "auto").strip().lower() or "auto"
REELS_STUDIO_ENABLED = os.environ.get("REELS_STUDIO_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
REELS_DEFAULT_ASPECT = os.environ.get("REELS_DEFAULT_ASPECT", "9:16").strip() or "9:16"
REELS_DEFAULT_DURATION_S = int(os.environ.get("REELS_DEFAULT_DURATION_S", "20") or 20)
REELS_SCENE_DURATION_S = int(os.environ.get("REELS_SCENE_DURATION_S", "5") or 5)
REELS_MAX_PHOTOS = int(os.environ.get("REELS_MAX_PHOTOS", "12") or 12)
REELS_ALBUM_SETTLE_S = float(os.environ.get("REELS_ALBUM_SETTLE_S", "2.2") or 2.2)
REELS_AUTO_POST = os.environ.get("REELS_AUTO_POST", "1").strip().lower() not in ("0", "false", "no", "off")
REELS_AUTO_COVER = os.environ.get("REELS_AUTO_COVER", "1").strip().lower() not in ("0", "false", "no", "off")
REELS_AUTO_SUBTITLES = os.environ.get("REELS_AUTO_SUBTITLES", "1").strip().lower() not in ("0", "false", "no", "off")
REELS_AUTO_MUSIC = os.environ.get("REELS_AUTO_MUSIC", "0").strip().lower() in ("1", "true", "yes", "on")
BRAND_KIT_ENABLED = os.environ.get("BRAND_KIT_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")

# Background tools via CometAPI.
# v47: Comet-first provider. Tries the documented OpenAI-compatible /v1/responses
# route and Bria-compatible /bria/image/edit/remove-background route.
BG_PROVIDER = os.environ.get("BG_PROVIDER", "comet").strip().lower() or "comet"
COMET_BG_MODEL = os.environ.get("COMET_BG_MODEL", "bria/remove-background").strip() or "bria/remove-background"
# Keep the old single-path ENV name, but v47 uses ordered candidates to survive Comet route changes.
def _env_list(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default) or default
    out = []
    for item in re.split(r"[;,]\s*", raw):
        item = item.strip()
        if item and item not in out:
            out.append(item)
    return out

COMET_BG_REMOVE_PATH = os.environ.get("COMET_BG_REMOVE_PATH", "/v1/responses").strip() or "/v1/responses"
COMET_BG_REMOVE_PATHS = _env_list(
    "COMET_BG_REMOVE_PATHS",
    f"{COMET_BG_REMOVE_PATH},/bria/image/edit/remove-background,/bria/image/edit/remove_background,/bria/image/edit/remove-bg"
)
COMET_BG_STATUS_PATH = os.environ.get("COMET_BG_STATUS_PATH", "/v1/responses/{id}").strip() or "/v1/responses/{id}"
COMET_BG_STATUS_PATHS = _env_list("COMET_BG_STATUS_PATHS", f"{COMET_BG_STATUS_PATH},/bria/{{id}},/v1/responses/{{id}}")
COMET_BG_TIMEOUT_S = float(os.environ.get("COMET_BG_TIMEOUT_S", "180") or 180)
COMET_BG_POLL_DELAY_S = float(os.environ.get("COMET_BG_POLL_DELAY_S", "3") or 3)
COMET_BG_MAX_WAIT_S = float(os.environ.get("COMET_BG_MAX_WAIT_S", "180") or 180)
COMET_BG_USE_TELEGRAM_URL = os.environ.get("COMET_BG_USE_TELEGRAM_URL", "1").strip().lower() not in ("0", "false", "no", "off")
COMET_BG_DEBUG_TO_CHAT = (os.environ.get("COMET_BG_DEBUG_TO_CHAT") or os.environ.get("COMET_BRIA_DEBUG_TO_CHAT") or "0").strip().lower() in ("1", "true", "yes", "on")
# Optional second Comet key just for Bria route. Useful when the dashboard issued a separate key/channel.
COMET_BRIA_API_KEY = (os.environ.get("COMET_BRIA_API_KEY") or os.environ.get("COMET_BG_API_KEY") or "").strip()
# Legacy direct BRIA / local paths are not production paths here, but remain available if explicitly selected.
BRIA_API_KEY = (os.environ.get("BRIA_API_KEY") or os.environ.get("BRIA_KEY") or os.environ.get("BRIA_API_TOKEN") or "").strip()
BRIA_REMOVE_BG_URL = os.environ.get("BRIA_REMOVE_BG_URL", "https://engine.prod.bria-api.com/v2/image/edit/remove_background").strip()
BRIA_REPLACE_BG_URL = os.environ.get("BRIA_REPLACE_BG_URL", "https://engine.prod.bria-api.com/v2/image/edit/replace_background").strip()
BRIA_REPLACE_BG_MODE = os.environ.get("BRIA_REPLACE_BG_MODE", "high_control").strip() or "high_control"
BRIA_SYNC = os.environ.get("BRIA_SYNC", "1").strip().lower() not in ("0", "false", "no", "off")
BRIA_TIMEOUT_S = float(os.environ.get("BRIA_TIMEOUT_S", "180") or 180)
BRIA_ALLOW_LOCAL_FALLBACK = os.environ.get("BRIA_ALLOW_LOCAL_FALLBACK", "0").strip().lower() in ("1", "true", "yes", "on")
LOCAL_REMBG_ENABLED = os.environ.get("LOCAL_REMBG_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")

RUNWAY_ENABLED = os.environ.get("RUNWAY_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
KLING_ENABLED = os.environ.get("KLING_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
SORA_ENABLED = os.environ.get("SORA_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
SEEDANCE_ENABLED = os.environ.get("SEEDANCE_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
VEO_ENABLED = os.environ.get("VEO_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
HAILUO_ENABLED = os.environ.get("HAILUO_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
VIDU_ENABLED = os.environ.get("VIDU_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
GROK_VIDEO_ENABLED = os.environ.get("GROK_VIDEO_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
LUMA_ENABLED = os.environ.get("LUMA_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")

KLING_MULTI_CREATE_PATH = os.environ.get("KLING_MULTI_CREATE_PATH", "/kling/v1/videos/multi-image2video").strip() or "/kling/v1/videos/multi-image2video"
KLING_MULTI_STATUS_PATH = os.environ.get("KLING_MULTI_STATUS_PATH", "/kling/v1/videos/multi-image2video/{id}").strip() or "/kling/v1/videos/multi-image2video/{id}"
KLING_AVATAR_CREATE_PATH = os.environ.get("KLING_AVATAR_CREATE_PATH", "/kling/v1/videos/avatar/image2video").strip() or "/kling/v1/videos/avatar/image2video"
KLING_LIPSYNC_IDENTIFY_PATH = os.environ.get("KLING_LIPSYNC_IDENTIFY_PATH", "/kling/v1/videos/identify-face").strip() or "/kling/v1/videos/identify-face"

SEEDANCE_MODEL = os.environ.get("SEEDANCE_MODEL", "doubao-seedance-2-0-fast").strip() or "doubao-seedance-2-0-fast"
SEEDANCE_CREATE_PATH = os.environ.get("SEEDANCE_CREATE_PATH", "/v1/videos").strip() or "/v1/videos"
SEEDANCE_STATUS_PATH = os.environ.get("SEEDANCE_STATUS_PATH", "/v1/videos/{id}").strip() or "/v1/videos/{id}"
SEEDANCE_UNIT_COST_USD = _env_float("SEEDANCE_UNIT_COST_USD", 0.25)
SEEDANCE_AUTO_FIRST = os.environ.get("SEEDANCE_AUTO_FIRST", "0").strip().lower() in ("1", "true", "yes", "on")

VEO_MODEL = os.environ.get("VEO_MODEL", "veo3.1_fast").strip() or "veo3.1_fast"
VEO_CREATE_PATH = os.environ.get("VEO_CREATE_PATH", "/v1/videos").strip() or "/v1/videos"
VEO_STATUS_PATH = os.environ.get("VEO_STATUS_PATH", "/v1/videos/{id}").strip() or "/v1/videos/{id}"
VEO_UNIT_COST_USD = _env_float("VEO_UNIT_COST_USD", 1.00)

HAILUO_MODEL = os.environ.get("HAILUO_MODEL", "hailuo-2.3").strip() or "hailuo-2.3"
HAILUO_CREATE_PATH = os.environ.get("HAILUO_CREATE_PATH", "/v1/videos").strip() or "/v1/videos"
HAILUO_STATUS_PATH = os.environ.get("HAILUO_STATUS_PATH", "/v1/videos/{id}").strip() or "/v1/videos/{id}"
HAILUO_UNIT_COST_USD = _env_float("HAILUO_UNIT_COST_USD", 0.25)

VIDU_MODEL = os.environ.get("VIDU_MODEL", "vidu-q3").strip() or "vidu-q3"
VIDU_CREATE_PATH = os.environ.get("VIDU_CREATE_PATH", "/v1/videos").strip() or "/v1/videos"
VIDU_STATUS_PATH = os.environ.get("VIDU_STATUS_PATH", "/v1/videos/{id}").strip() or "/v1/videos/{id}"
VIDU_UNIT_COST_USD = _env_float("VIDU_UNIT_COST_USD", 0.25)

GROK_VIDEO_MODEL = os.environ.get("GROK_VIDEO_MODEL", "grok-imagine-video").strip() or "grok-imagine-video"
GROK_VIDEO_CREATE_PATH = os.environ.get("GROK_VIDEO_CREATE_PATH", "/v1/videos").strip() or "/v1/videos"
GROK_VIDEO_STATUS_PATH = os.environ.get("GROK_VIDEO_STATUS_PATH", "/v1/videos/{id}").strip() or "/v1/videos/{id}"
GROK_VIDEO_UNIT_COST_USD = _env_float("GROK_VIDEO_UNIT_COST_USD", 0.10)

COMET_TTS_MODEL = os.environ.get("COMET_TTS_MODEL", os.environ.get("OPENAI_TTS_MODEL", "tts-1")).strip() or "tts-1"
COMET_TTS_VOICE = os.environ.get("COMET_TTS_VOICE", "alloy").strip() or "alloy"
COMET_TTS_PATH = os.environ.get("COMET_TTS_PATH", "/v1/audio/speech").strip() or "/v1/audio/speech"
COMET_TRANSCRIBE_MODEL = os.environ.get("COMET_TRANSCRIBE_MODEL", TRANSCRIBE_MODEL).strip() or TRANSCRIBE_MODEL
COMET_TRANSCRIBE_PATH = os.environ.get("COMET_TRANSCRIBE_PATH", "/v1/audio/transcriptions").strip() or "/v1/audio/transcriptions"
SUNO_ENABLED = os.environ.get("SUNO_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
SUNO_MODEL_VERSION = os.environ.get("SUNO_MODEL_VERSION", "chirp-auk").strip() or "chirp-auk"
SUNO_CREATE_PATH = os.environ.get("SUNO_CREATE_PATH", "/suno/submit/music").strip() or "/suno/submit/music"
SUNO_FETCH_PATH = os.environ.get("SUNO_FETCH_PATH", "/suno/fetch/{task_id}").strip() or "/suno/fetch/{task_id}"
SUNO_UNIT_COST_USD = _env_float("SUNO_UNIT_COST_USD", 0.15)

# Таймауты
LUMA_MAX_WAIT_S     = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)
LUMA_TEMP_DISABLED = True  # временная заглушка: скрываем Luma из меню и отключаем использование
RUNWAY_MAX_WAIT_S   = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "1200").strip() or 1200)
VIDEO_POLL_DELAY_S  = float((os.environ.get("VIDEO_POLL_DELAY_S") or "6.0").strip() or 6.0)

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

# ───────── LIVE INTERNET / CURRENT DATA ─────────
# Этот слой нужен, чтобы бот не отвечал «мои данные устарели» на вопросы про курсы,
# новости, законы, релизы, погоду и прочую актуальную информацию.
LIVE_SEARCH_ENABLED = os.environ.get("LIVE_SEARCH_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
CRYPTO_RATE_ENABLED = os.environ.get("CRYPTO_RATE_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
LIVE_SEARCH_TIMEOUT_S = _env_float("LIVE_SEARCH_TIMEOUT_S", 18.0)
BINANCE_MARKET_BASE = os.environ.get("BINANCE_MARKET_BASE", "https://api.binance.com").strip().rstrip("/")
OPENAI_WEB_SEARCH_MODEL = os.environ.get("OPENAI_WEB_SEARCH_MODEL", "gpt-4o-mini-search-preview").strip()

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
    """
    Tavily — основной внешний поиск. Нужен TAVILY_API_KEY.
    Возвращает компактный контекст со ссылками для LLM.
    """
    if not TAVILY_API_KEY:
        return None
    try:
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": query,
            "search_depth": "basic",
            "include_answer": True,
            "include_raw_content": False,
            "max_results": 5,
        }
        async with httpx.AsyncClient(timeout=LIVE_SEARCH_TIMEOUT_S, follow_redirects=True) as client:
            r = await client.post("https://api.tavily.com/search", json=payload)
        if r.status_code // 100 != 2:
            log.warning("Tavily HTTP %s: %s", r.status_code, r.text[:500])
            return None
        data = r.json()
        parts: list[str] = []
        ans = data.get("answer")
        if isinstance(ans, str) and ans.strip():
            parts.append("Краткий ответ поиска: " + ans.strip())
        for idx, item in enumerate(data.get("results", []) or [], start=1):
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "Источник").strip()
            url = (item.get("url") or "").strip()
            content = (item.get("content") or "").strip()
            if url or content:
                parts.append(f"[{idx}] {title}\nURL: {url}\nФрагмент: {content[:900]}")
        return "\n\n".join(parts).strip() or None
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
        "Ты live-поисковый помощник внутри Telegram-бота Neuro-Bot GPT-5. "
        "Отвечай по-русски, кратко и по делу. Если вопрос требует свежих данных, "
        "используй веб-поиск. Не пиши, что база знаний устарела. В конце дай источники."
    )
    payload_base = {
        "model": OPENAI_WEB_SEARCH_MODEL,
        "input": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
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
    Возвращает True, если вопрос уже обработан live-слоем и дальше в обычный GPT идти не нужно.
    """
    text = (user_text or "").strip()
    if not text or not LIVE_SEARCH_ENABLED:
        return False

    # Криптовалюты — быстрый публичный API без ключа.
    if _is_crypto_rate_query(text):
        answer = await get_crypto_rate_text(text)
        if answer:
            await update.effective_message.reply_text(answer, disable_web_page_preview=True)
            return True
        # Если Binance недоступен, падаем в общий live-поиск.

    if not _needs_live_search(text):
        return False

    # Основной вариант: Tavily даёт свежие источники, LLM формирует ответ.
    ctx = await _tavily_live_search_context(text)
    if ctx:
        prompt = (
            "Ответь на вопрос пользователя на основе свежего веб-контекста ниже. "
            "Не говори про устаревшую базу знаний. Если данных недостаточно — честно укажи это. "
            "В конце добавь короткий блок 'Источники' со ссылками из контекста.\n\n"
            f"Вопрос: {text}"
        )
        try:
            reply = await ask_openai_text(prompt, web_ctx=ctx)
            if reply:
                await update.effective_message.reply_text(reply[:3900], disable_web_page_preview=False)
                if len(reply) > 3900:
                    await update.effective_message.reply_text(reply[3900:7800], disable_web_page_preview=False)
                return True
        except Exception as e:
            log.warning("LLM summary after Tavily failed: %s", e)

    # Fallback: OpenAI native web search.
    live_answer = await openai_live_web_search(text)
    if live_answer:
        await update.effective_message.reply_text(live_answer, disable_web_page_preview=False)
        return True

    await update.effective_message.reply_text(
        "Я понял, что вопрос требует актуальных данных, но сейчас не смог получить ответ из интернета. "
        "Проверьте TAVILY_API_KEY или OPENAI_API_KEY для live-поиска и повторите запрос."
    )
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

def _can_spend_or_offer(user_id: int, username: str | None, engine: str, est_cost_usd: float) -> tuple[bool, str]:
    if is_unlimited(user_id, username):
        if engine in ("luma", "runway", "img"):
            _usage_update(user_id, **{f"{engine}_usd": est_cost_usd})
        return True, ""
    if engine not in ("luma", "runway", "img"):
        return True, ""
    tier = get_subscription_tier(user_id)
    lim = _limits_for(user_id)
    row = _usage_row(user_id)
    spent = row[f"{engine}_usd"]; budget = lim[f"{engine}_budget_usd"]

    if spent + est_cost_usd <= budget + 1e-9:
        _usage_update(user_id, **{f"{engine}_usd": est_cost_usd})
        return True, ""

    # Попытка покрыть из единого кошелька
    need = max(0.0, spent + est_cost_usd - budget)
    if need > 0:
        if _wallet_total_take(user_id, need):
            _usage_update(user_id, **{f"{engine}_usd": est_cost_usd})
            return True, ""
        if tier == "free":
            return False, "ASK_SUBSCRIBE"
        return False, f"OFFER:{need:.2f}"
    return True, ""

def _register_engine_spend(user_id: int, engine: str, usd: float):
    if engine in ("luma","runway","img"):
        _usage_update(user_id, **{f"{engine}_usd": float(usd)})

# ───────── Prompts ─────────
SYSTEM_PROMPT = (
    "Ты дружелюбный и лаконичный ассистент на русском. "
    "Отвечай по сути, структурируй списками/шагами, не выдумывай факты. "
    "Если ссылаешься на источники — в конце дай короткий список ссылок. "
    "По медицинским документам помогай с разбором, структурированием и вопросами к врачу, "
    "но ясно указывай, что это не диагноз и не замена очной консультации."
)
VISION_SYSTEM_PROMPT = (
    "Ты чётко описываешь содержимое изображений: объекты, текст, схемы, графики. "
    "Не идентифицируй личности людей и не пиши имена, если они не напечатаны на изображении. "
    "Если изображение медицинское, делай только справочный разбор видимого текста/признаков, "
    "не ставь диагноз и напоминай, что нужен врач и официальный протокол."
)

HELP_TEXT = globals().get("HELP_TEXT") or (
    "Команды: /start, /engines, /plans, /balance, /img <описание>, /voice_on, /voice_off, /diag_video.\n"
    "Можно отправить фото и выбрать: оживить через Runway/Sora/Kling, ретушировать собственное фото/убрать лишнюю надпись, удалить/заменить фон, расширить кадр, сделать раскадровку или анализ.\n"
    "🩺 Медицина: разбор выписок, анамнеза, врачебных заключений, анализов, снимков, МРТ/КТ."
)
EXAMPLES_TEXT = globals().get("EXAMPLES_TEXT") or (
    "Примеры:\n"
    "• Оживи фото: лёгкая улыбка, взгляд в камеру, плавное движение камеры, 5 секунд, 9:16\n"
    "• Сделай видео: вилла на берегу моря на Самуи, закат, 10 секунд, 16:9\n"
    "• /img luxury villa in Koh Samui, tropical, cinematic"
)

# ───────── Heuristics / intent ─────────
_SMALLTALK_RE = re.compile(r"^(привет|здравствуй|добрый\s*(день|вечер|утро)|хи|hi|hello|как дела|спасибо|пока)\b", re.I)
_NEWSY_RE     = re.compile(r"(когда|дата|выйдет|релиз|новост|курс|цена|прогноз|найди|официал|погода|сегодня|тренд|адрес|телефон)", re.I)
_CAPABILITY_RE = re.compile(r"(мож(ешь|но|ете)|уме(ешь|ете)|способен|может\s+ли).{0,80}(анализ|распозн|читать|созда(ва)?т|дела(ть)?|ожив|анимир).{0,80}(фото|фотограф|картинк|изображен|pdf|docx|epub|fb2|аудио|книг|видео)", re.I)

_IMG_WORDS = r"(картин\w+|изображен\w+|фото\w*|рисунк\w+|логотип\w*|лого\b|эмблем\w+|бренд\w+|фирменн\w+|image|picture|img\b|logo|banner|poster|brand|emblem)"
_VID_WORDS = r"(видео|ролик\w*|анимаци\w*|рилс\w*|reels?|shorts?|шортс\w*|клип\w*|clip|video|vid\b)"

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
        caption = (update.message.caption or "").strip()
        goal = caption or None
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


# ───────── Image retouch / own-image watermark cleanup ─────────
_RETOUCH_TERMS_RE = re.compile(
    r"(водян(?:ой|ого|ому|ым|ом)\s+знак|водн(?:ый|ого|ому|ым|ом)\s+знак|watermark|"
    r"ватермарк|ретуш|ретушир|заретуш|ветошь|"
    r"(?:убер(?:и|ите|у)|удал(?:и|ите|ить)|сотр(?:и|ите)|замажь|замазать)\s+.{0,80}"
    r"(?:водян(?:ой|ого|ому|ым|ом)\s+знак|водн(?:ый|ого|ому|ым|ом)\s+знак|watermark|надпись|текст|логотип|лого|эмблем|лишн(?:ий|юю|ее|ие)\s+объект)|"
    r"очист(?:и|ите|ить)\s+.{0,40}(?:фото|изображен|картинк|photo|image)|"
    r"лишн(?:ий|юю|ее|ие)\s+(?:надпись|объект|логотип|текст)|"
    r"надпись\s+на\s+фото|текст\s+на\s+фото|логотип\s+на\s+фото|"
    r"remove\s+(?:watermark|text|logo|object)|clean\s+(?:image|photo))",
    re.IGNORECASE,
)

_OWN_IMAGE_CONFIRM_RE = re.compile(
    r"(мо[йяёие]|сво[йяёеих]|собственн|мой\s+файл|мой\s+макет|моя\s+фот|"
    r"есть\s+прав|имею\s+прав|разрешени|я\s+владелец|own\s+image|my\s+image|my\s+photo|i\s+own)",
    re.IGNORECASE,
)


def _is_image_retouch_request(text: str) -> bool:
    """True для безопасной ретуши собственного изображения: водяной знак, лишняя надпись, логотип, объект."""
    return bool(_RETOUCH_TERMS_RE.search(text or ""))


def _has_own_image_confirmation(text: str) -> bool:
    return bool(_OWN_IMAGE_CONFIRM_RE.search(text or ""))


def _set_waiting_image_retouch(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str = ""):
    """Следующее фото должно пойти в ретушь собственного изображения, а не в медицину/анализ."""
    uid = update.effective_user.id
    _set_mode_clean(uid, "Развлечения", "")
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
        "🧽 Да, могу сделать ретушь собственного изображения.\n\n"
        "Пришлите фото и, если возможно, укажите где находится элемент: "
        "например «водяной знак справа снизу», «надпись по центру», «логотип сверху».\n\n"
        "Важно: я обрабатываю только ваши собственные изображения/макеты или файлы, "
        "на которые у вас есть право редактирования."
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
    """OpenAI image edit лучше кормить PNG. Если PIL недоступен — отправляем исходный файл."""
    if Image is None:
        mime = sniff_image_mime(img_bytes)
        ext = "jpg" if mime == "image/jpeg" else "png"
        return img_bytes, f"image.{ext}", mime
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGBA")
        # Ограничиваем размер, чтобы не ловить лимиты multipart, но сохраняем хорошую детализацию.
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
    """Реальная ретушь через OpenAI Images / gpt-image-1: /images/edits."""
    if not OPENAI_IMAGE_KEY:
        return None
    if OPENAI_IMAGE_KEY.startswith("sk-or-"):
        # OpenRouter не умеет OpenAI Images edits.
        raise RuntimeError("OPENAI_IMAGE_KEY похож на ключ OpenRouter. Для ретуши нужен официальный OpenAI key или совместимый image-edit proxy.")

    edit_bytes, filename, mime = _prepare_image_for_edit(img_bytes)
    prompt = _retouch_system_prompt(user_instruction)
    base = (IMAGES_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {OPENAI_IMAGE_KEY}"}

    # Некоторые прокси не любят size, поэтому делаем две попытки.
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
                last_err = f"нет b64_json/url в ответе: {json.dumps(js, ensure_ascii=False)[:500]}"
            except Exception as e:
                last_err = str(e)
                log.warning("Image edit exception: %s", e)
                continue
    raise RuntimeError(last_err or "image edit failed")


async def _edit_own_image_retouch(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes, instruction: str):
    """Отправляет фото в AI-ретушь и возвращает результат пользователю."""
    instruction = (instruction or context.user_data.get("retouch_prompt") or "убрать лишнюю надпись/водяной знак и восстановить фон").strip()
    if not OPENAI_IMAGE_KEY:
        await update.effective_message.reply_text("❌ Ретушь недоступна: не задан OPENAI_IMAGE_KEY/OPENAI_API_KEY.")
        return
    if OPENAI_IMAGE_KEY.startswith("sk-or-"):
        await update.effective_message.reply_text(
            "❌ Для ретуши нужен официальный OpenAI image key. OpenRouter-ключ для image edit не подходит."
        )
        return

    await update.effective_message.reply_text(
        "🧽 Запускаю ретушь собственного изображения через Images. "
        "Уберу только указанный лишний элемент и постараюсь естественно восстановить фон."
    )
    with contextlib.suppress(Exception):
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
    try:
        out = await _openai_image_edit_bytes(img_bytes, instruction)
        if not out:
            await update.effective_message.reply_text("❌ Не удалось получить результат ретуши.")
            return
        bio = BytesIO(out)
        bio.name = "retouched.png"
        await update.effective_message.reply_document(
            InputFile(bio),
            caption="✅ Готово: ретушь выполнена. Проверьте фон и детали; при необходимости можно отправить уточнение, что поправить."
        )
    except Exception as e:
        log.exception("image retouch error: %s", e)
        await update.effective_message.reply_text(
            "❌ Не удалось выполнить ретушь изображения. "
            f"Техническая причина: {str(e)[:700]}"
        )


async def _start_image_retouch(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes, instruction: str):
    """Платёжная обёртка для ретуши: используем тот же бюджет Images."""
    if not OPENAI_IMAGE_KEY or OPENAI_IMAGE_KEY.startswith("sk-or-"):
        await _edit_own_image_retouch(update, context, img_bytes, instruction)
        return

    async def _go():
        await _edit_own_image_retouch(update, context, img_bytes, instruction)

    await _try_pay_then_do(
        update, context, update.effective_user.id,
        "img", IMG_COST_USD, _go,
        remember_kind="image_retouch",
        remember_payload={"instruction": instruction},
    )


# ───────── UI / тексты ─────────
START_TEXT = (
    "Привет! Я Нейро-Bot — AI‑студия внутри Telegram.\n"
    "Теперь логика собрана вокруг задач, а не вокруг названий движков: рилсы, фото, голос, документы, бизнес и GPT‑чат.\n\n"
    "🎬 Видео / Reels — AI Reels Studio, оживление фото, текст→видео, фото→видео, аватар, lip-sync, субтитры, музыка.\n"
    "🖼 Фото / Дизайн — генерация, улучшение, фон, ретушь, обложки, фото товара и недвижимости.\n"
    "🗣 Голос / Аудио — речь→текст, текст→голос, перевод, музыка и озвучка для видео.\n"
    "📄 Документы — PDF/DOCX/EPUB/TXT/FB2/MOBI/AZW, резюме, перевод, вопросы, медицина.\n"
    "🏡 Бизнес / Недвижимость — посты, рилсы, КП, презентации, ROI, WhatsApp‑сообщения.\n\n"
    "🧠 Движок выбирается автоматически через Creative Router. Ручной выбор доступен в настройках."
)
def engines_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 GPT (текст/фото/документы)", callback_data="engine:gpt")],
        [InlineKeyboardButton("🖼 Images (OpenAI)",             callback_data="engine:images")],
        [InlineKeyboardButton("🎥 Runway — оживление фото",      callback_data="engine:runway")],
        [InlineKeyboardButton("🎞 Sora 2 — text/image→video",    callback_data="engine:sora")],
        [InlineKeyboardButton("🎬 Kling — text/image→video",     callback_data="engine:kling")],
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
        "• GPT-5 (текст/логика) + Vision (фото/снимки) + STT/TTS (голос)\n"
        "• Runway / Kling — оживление фото, Sora 2 — видео и фото без людей, Midjourney — изображения\n"
        "• 🩺 Медицина — справочный разбор выписок, заключений, МРТ/КТ и анализов\n\n"
        "Можете также просто написать свободный запрос — бот поймёт."
    )

def modes_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎓 Учёба", callback_data="mode:study"),
            InlineKeyboardButton("💼 Работа", callback_data="mode:work"),
            InlineKeyboardButton("🔥 Развлечения", callback_data="mode:fun"),
        ],
        [
            InlineKeyboardButton("🩺 Медицина", callback_data="mode:medicine"),
        ],
    ])

# ── Описание и подменю по режимам
def _mode_desc(key: str) -> str:
    if key == "study":
        return (
            "🎓 *Учёба*\n"
            "Гибрид: GPT-5 для объяснений/конспектов, Vision для фото-задач, "
            "STT/TTS для голосовых, + Midjourney (иллюстрации), Sora 2/Kling для роликов; Runway — только оживление фото.\n\n"
            "Быстрые действия ниже. Можно написать свободный запрос (например: "
            "«сделай конспект из PDF», «объясни интегралы с примерами»)."
        )
    if key == "work":
        return (
            "💼 *Работа*\n"
            "Гибрид: GPT-5 (резюме/письма/аналитика), Vision (таблицы/скрины), "
            "STT/TTS (диктовка/озвучка), + Midjourney (визуалы), Sora 2/Kling для презентационных роликов; Runway — только оживление фото.\n\n"
            "Быстрые действия ниже. Можно написать свободный запрос (например: "
            "«адаптируй резюме под вакансию PM», «написать коммерческое предложение»)."
        )
    if key == "fun":
        return (
            "🔥 *Развлечения*\n"
            "Гибрид: GPT-5 (идеи, сценарии, раскадровка), Vision (фото/референсы), "
            "Sora 2/Kling (короткие видео), Runway/Kling (оживление фото с людьми), Sora 2 — только фото без людей, STT/TTS (голос и озвучка).\n\n"
            "Главные быстрые действия: оживить фото, сделать Reels/Shorts, создать мини-фильм из сцен.\n"
            "Можно написать свободный запрос, например: «сделай рилс 20 секунд про виллу на Самуи, стиль luxury, 9:16»."
        )
    if key == "medicine":
        return _medical_menu_text()
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
                InlineKeyboardButton("🪄 Оживить фото", callback_data="act:fun:revive"),
                InlineKeyboardButton("📱 Сделать Reels", callback_data="act:fun:reels"),
                InlineKeyboardButton("🎞 Создать фильм", callback_data="act:fun:film"),
            ],
            [InlineKeyboardButton("📝 Свободный запрос", callback_data="act:free")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="mode:root")],
        ])

    if key == "medicine":
        return medicine_kb()

    return modes_root_kb()

# Показать выбранный режим (используется и для callback, и для текста)
async def _send_mode_menu(update, context, key: str):
    text = _mode_desc(key)
    kb = _mode_kb(key)
    # Если пришли из callback — редактируем; если текстом — шлём новым сообщением
    if getattr(update, "callback_query", None):
        q = update.callback_query
        await _safe_q_edit(update, context, text, reply_markup=kb, parse_mode="Markdown")
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
        await _safe_q_edit(update, context, _modes_root_text(), reply_markup=modes_root_kb())
        await q.answer(); return

    if data.startswith("mode:"):
        _, key = data.split(":", 1)
        _clear_transient_flows(context)
        if key == "medicine":
            _set_mode_clean(uid, "Медицина", "")
        elif key == "study":
            _set_mode_clean(uid, "Учёба", "")
        elif key == "work":
            _set_mode_clean(uid, "Работа", "")
        elif key == "fun":
            _set_mode_clean(uid, "Развлечения", "")
        await _send_mode_menu(update, context, key)
        return

    # Свободный ввод из подменю
    if data == "act:free":
        await q.answer()
        await _safe_q_edit(update, context, 
            "📝 Напишите свободный запрос ниже текстом или голосом — я подстроюсь.",
            reply_markup=modes_root_kb(),
        )
        return

    # === Учёба
    if data == "act:study:pdf_summary":
        await q.answer()
        _mode_track_set(uid, "pdf_summary")
        await _safe_q_edit(update, context, 
            "📚 Пришлите PDF/EPUB/DOCX/FB2/TXT — сделаю структурированный конспект.\n"
            "Можно в подписи указать цель (коротко/подробно, язык и т.п.).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:explain":
        await q.answer()
        study_sub_set(uid, "explain")
        _mode_track_set(uid, "explain")
        await _safe_q_edit(update, context, 
            "🔍 Напишите тему + уровень (школа/вуз/профи). Будет объяснение с примерами.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:tasks":
        await q.answer()
        study_sub_set(uid, "tasks")
        _mode_track_set(uid, "tasks")
        await _safe_q_edit(update, context, 
            "🧮 Пришлите условие(я) — решу пошагово (формулы, пояснения, итог).",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:essay":
        await q.answer()
        study_sub_set(uid, "essay")
        _mode_track_set(uid, "essay")
        await _safe_q_edit(update, context, 
            "✍️ Тема + требования (объём/стиль/язык) — подготовлю эссе/реферат.",
            reply_markup=_mode_kb("study"),
        )
        return

    if data == "act:study:exam_plan":
        await q.answer()
        study_sub_set(uid, "quiz")
        _mode_track_set(uid, "exam_plan")
        await _safe_q_edit(update, context, 
            "📝 Укажите предмет и дату экзамена — составлю план подготовки с вехами.",
            reply_markup=_mode_kb("study"),
        )
        return

    # === Работа
    if data == "act:work:doc":
        await q.answer()
        _mode_track_set(uid, "work_doc")
        await _safe_q_edit(update, context, 
            "📄 Что за документ/адресат/контекст? Сформирую черновик письма/документа.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:report":
        await q.answer()
        _mode_track_set(uid, "work_report")
        await _safe_q_edit(update, context, 
            "📊 Пришлите текст/файл/ссылку — сделаю аналитическую выжимку.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:plan":
        await q.answer()
        _mode_track_set(uid, "work_plan")
        await _safe_q_edit(update, context, 
            "🗂 Опишите задачу/сроки — соберу ToDo/план со сроками и приоритетами.",
            reply_markup=_mode_kb("work"),
        )
        return

    if data == "act:work:idea":
        await q.answer()
        _mode_track_set(uid, "work_idea")
        await _safe_q_edit(update, context, 
            "💡 Расскажите продукт/ЦА/каналы — подготовлю бриф/идеи.",
            reply_markup=_mode_kb("work"),
        )
        return

    # === Развлечения (как было)
    if data == "act:fun:ideas":
        await q.answer()
        await _safe_q_edit(update, context, 
            "🔥 Выберем формат: дом/улица/город/в поездке. Напишите бюджет/настроение.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:shorts":
        await q.answer()
        await _safe_q_edit(update, context, 
            "🎬 Тема, длительность (15–30 сек), стиль — сделаю сценарий шорта + подсказки для озвучки.",
            reply_markup=_mode_kb("fun"),
        )
        return
    if data == "act:fun:games":
        await q.answer()
        await _safe_q_edit(update, context, 
            "🎮 Тематика квиза/игры? Сгенерирую быструю викторину или мини-игру в чате.",
            reply_markup=_mode_kb("fun"),
        )
        return

    if data == "act:fun:revive":
        await q.answer()
        _set_waiting_photo_revival(update, context)
        await _safe_q_edit(update, context, 
            _fun_revive_help_text(),
            parse_mode="Markdown",
            reply_markup=_mode_kb("fun"),
        )
        return

    if data == "act:fun:reels":
        await q.answer()
        _clear_transient_flows(context)
        _set_mode_clean(uid, "Развлечения", "fun_reels")
        context.user_data["awaiting_reels_material"] = True
        await _safe_q_edit(update, context, 
            _fun_reels_help_text(),
            parse_mode="Markdown",
            reply_markup=_mode_kb("fun"),
        )
        return

    if data == "act:fun:film":
        await q.answer()
        _clear_transient_flows(context)
        _set_mode_clean(uid, "Развлечения", "fun_film")
        context.user_data["awaiting_film_material"] = True
        await _safe_q_edit(update, context, 
            _fun_film_help_text(),
            parse_mode="Markdown",
            reply_markup=_mode_kb("fun"),
        )
        return

    # === Медицина
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
        _set_mode_clean(uid, "Медицина", track)
        _clear_transient_flows(context)
        context.user_data["medicine_waiting_for_material"] = True
        context.user_data["pending_med_task"] = track
        await _safe_q_edit(update, context, _medical_menu_text(track), reply_markup=medicine_kb())
        return

    # === Модули (как было)
    if data == "act:open:runway":
        await q.answer()
        await _safe_q_edit(update, context, 
            "🎬 Модуль Runway: пришлите идею/референс — подготовлю промпт и бюджет.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:mj":
        await q.answer()
        await _safe_q_edit(update, context, 
            "🎨 Модуль Midjourney: опишите картинку — предложу 3 промпта и сетку стилей.",
            reply_markup=modes_root_kb(),
        )
        return
    if data == "act:open:voice":
        await q.answer()
        await _safe_q_edit(update, context, 
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
        "медицина": "medicine", "медицинa": "medicine",
    }
    key = mapping.get(text)
    if key:
        await _send_mode_menu(update, context, key)
        
def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎓 Учёба"), KeyboardButton("💼 Работа"), KeyboardButton("🔥 Развлечения")],
            [KeyboardButton("🩺 Медицина"), KeyboardButton("🧠 Движки"), KeyboardButton("🧾 Баланс")],
            [KeyboardButton("⭐ Подписка · Помощь")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
        input_field_placeholder="Выберите режим или напишите запрос…",
    )

main_kb = main_keyboard()

# ───────── /start ─────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        START_TEXT,
        reply_markup=main_kb,
        disable_web_page_preview=True,
    )

# ───────── сохранение выбранного режима/подрежима (SQLite kv) ─────────
def _mode_set(user_id: int, mode: str):
    kv_set(f"mode:{user_id}", mode)

def _mode_get(user_id: int) -> str:
    return (kv_get(f"mode:{user_id}", "none") or "none")

def _mode_track_set(user_id: int, track: str):
    kv_set(f"mode_track:{user_id}", track)

def _mode_track_get(user_id: int) -> str:
    return kv_get(f"mode_track:{user_id}", "") or ""


# ───────── Безопасная маршрутизация режимов ─────────
def _set_mode_clean(user_id: int, mode: str, track: str = ""):
    """Единый вход для переключения режима: новый режим всегда сбрасывает старый подрежим."""
    with contextlib.suppress(Exception):
        _mode_set(user_id, mode)
    with contextlib.suppress(Exception):
        _mode_track_set(user_id, track or "")


def _clear_transient_flows(context):
    """Сбрасывает краткоживущие ожидания, которые не должны тянуться между режимами."""
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
    ):
        with contextlib.suppress(Exception):
            context.user_data.pop(key, None)


def _set_waiting_photo_revival(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """После текста/голоса «оживить фото» следующая фотография должна идти в фото-мастерскую, а не в медицину."""
    uid = update.effective_user.id
    _set_mode_clean(uid, "Развлечения", "")
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


# Ретушь собственного изображения использует отдельный photo_flow, чтобы не конфликтовать с медициной.
# Функции _set_waiting_image_retouch/_is_waiting_image_retouch объявлены выше в блоке Image retouch.


def _set_medical_waiting(update: Update, context: ContextTypes.DEFAULT_TYPE, track: str = ""):
    """Медицина становится активной только как меню/конкретная мед. задача, но не должна перехватывать фото после других запросов."""
    uid = update.effective_user.id
    _set_mode_clean(uid, "Медицина", track or "")
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
    """Маршрутизирует в медицину только явный мед. подрежим/ожидание или явные мед. слова.
    Сам факт, что пользователь когда-то нажал «Медицина», больше не делает все следующие фото медицинскими.
    """
    track = ""
    with contextlib.suppress(Exception):
        track = _mode_track_get(user_id)
    combined = f"{caption_or_text or ''} {filename or ''}"
    # В медицину отправляем только явный медицинский материал или материал,
    # который пользователь прямо ждет после нажатия мед. подменю.
    # Старый mode_track=med_* сам по себе больше не должен перехватывать все подряд.
    return (
        bool(_MEDICAL_TERMS_RE.search(combined))
        or bool(context and context.user_data.get("medicine_waiting_for_material") and (track or "").startswith("med_"))
    )


# ───────── Тексты быстрых действий «Развлечения» ─────────
def _fun_revive_help_text() -> str:
    return (
        "🪄 *Оживить фото*\n"
        "Можно сделать короткое видео из одной фотографии.\n\n"
        "Как запустить:\n"
        "1) отправьте фото обычной картинкой;\n"
        "2) после загрузки появятся кнопки ✨ Оживить: Runway / Sora 2 / Kling;\n"
        "3) либо сразу отправьте фото с подписью: `оживи фото: лёгкая улыбка, плавное движение камеры, 5 секунд, 9:16`.\n\n"
        "Рекомендация: Runway — лучший вариант для стабильного оживления портретов и референсов; Kling — для динамики; Sora 2 — только для фото без людей, если канал в Comet доступен."
    )


def _fun_reels_help_text() -> str:
    return (
        "📱 *Сделать Reels / Shorts*\n"
        "Я могу собрать идею, хук, сценарий, тайм-коды, подписи, промпты для видеогенерации и план монтажа.\n\n"
        "Как запустить:\n"
        "• напишите тему: `сделай рилс 20 секунд про виллу на Самуи, luxury, 9:16`;\n"
        "• или пришлите исходное видео/фото и подпись: что оставить, стиль, длительность, ЦА;\n"
        "• для AI-вставок лучше использовать Runway/Kling; Sora 2 — только если доступен канал провайдера.\n\n"
        "Формат результата: hook → сцены → текст на экране → voice-over → CTA → промпты для выбранного движка."
    )


def _fun_film_help_text() -> str:
    return (
        "🎞 *Создать фильм / мини-фильм*\n"
        "Подходит для ролика 30–90 секунд или серии сцен: реклама, история, трейлер, промо, клип.\n\n"
        "Как запустить:\n"
        "1) напишите идею, жанр, длительность, стиль и формат кадра;\n"
        "2) я сделаю сценарий, список сцен, раскадровку и промпты;\n"
        "3) сцены генерируются короткими фрагментами 5–10 сек через Sora 2/Kling, затем склеиваются. Runway используем только для оживления фото.\n\n"
        "Рекомендация: Runway — для контроля и качества, Kling — для динамичных сцен, Sora 2 — если доступен через ваш Comet-канал и в кадре нет людей."
    )

# ───────── Подменю режимов ─────────
def _school_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Объяснение",          callback_data="school:explain"),
         InlineKeyboardButton("🧮 Задачи",              callback_data="school:tasks")],
        [InlineKeyboardButton("✍️ Эссе/реферат/доклад", callback_data="school:essay"),
         InlineKeyboardButton("📝 Экзамен/квиз",        callback_data="school:quiz")],
    ])

def _work_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📧 Письмо/документ",  callback_data="work:doc"),
         InlineKeyboardButton("📊 Аналитика/сводка", callback_data="work:report")],
        [InlineKeyboardButton("🗂 План/ToDo",        callback_data="work:plan"),
         InlineKeyboardButton("💡 Идеи/бриф",       callback_data="work:idea")],
    ])

def _fun_quick_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Оживить фото (анимация)", callback_data="fun:revive")],
        [InlineKeyboardButton("Клип из текста/голоса",    callback_data="fun:clip")],
        [InlineKeyboardButton("Сгенерировать изображение /img", callback_data="fun:img")],
        [InlineKeyboardButton("Раскадровка под Reels",    callback_data="fun:storyboard")],
    ])

def _fun_kb():
    # оставим и старое подменю — не используется сейчас
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 Фото-мастерская", callback_data="fun:photo"),
         InlineKeyboardButton("🎬 Видео-идеи",      callback_data="fun:video")],
        [InlineKeyboardButton("🎲 Квизы/игры",      callback_data="fun:quiz"),
         InlineKeyboardButton("😆 Мемы/шутки",      callback_data="fun:meme")],
    ])


# ───────── Команды/кнопки режимов ─────────
async def cmd_mode_school(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_transient_flows(context)
    _set_mode_clean(update.effective_user.id, "Учёба", "")
    # показываем НОВОЕ подменю «Учёба»
    await _send_mode_menu(update, context, "study")

async def cmd_mode_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_transient_flows(context)
    _set_mode_clean(update.effective_user.id, "Работа", "")
    # показываем НОВОЕ подменю «Работа»
    await _send_mode_menu(update, context, "work")

async def cmd_mode_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_transient_flows(context)
    _set_mode_clean(update.effective_user.id, "Развлечения", "")
    await update.effective_message.reply_text(
        "🔥 Развлечения — быстрые действия:",
        reply_markup=_fun_quick_kb()
    )

async def cmd_mode_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _set_medical_waiting(update, context, "")
    await update.effective_message.reply_text(_medical_menu_text(), reply_markup=medicine_kb())


# ───────── Коллбэки подрежимов ─────────
async def on_cb_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "")
    try:
        if any(data.startswith(p) for p in ("school:", "work:", "fun:")):
            # базовый трекинг старых веток (photo/video/quiz/meme)
            if data in ("fun:revive","fun:clip","fun:img","fun:storyboard"):
                # эти обрабатываются отдельным хендлером on_cb_fun
                return
            _, track = data.split(":", 1)
            _mode_track_set(update.effective_user.id, track)
            mode = _mode_get(update.effective_user.id)
            await _safe_q_edit(update, context, f"{mode} → {track}. Напишите задание/тему — сделаю.")
            return
    finally:
        with contextlib.suppress(Exception):
            await q.answer()

# быстрые действия «Развлечения»
async def on_cb_fun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "fun:img":
        return await _safe_q_edit(update, context, "Пришли промпт или используй команду /img <описание> — сгенерирую изображение.")
    if data == "fun:revive":
        return await _safe_q_edit(update, context, "Загрузи фото (как картинку) и напиши, что оживить/как двигаться. Сделаю анимацию.")
    if data == "fun:clip":
        return await _safe_q_edit(update, context, "Пришли текст/голос и формат (Reels/Shorts), музыку/стиль — соберу клип. Для генерации видео доступны Sora 2 и Kling; Runway — только оживление фото.")
    if data == "fun:storyboard":
        return await _safe_q_edit(update, context, "Пришли фото или опиши идею ролика — верну раскадровку под Reels с тайм-кодами.")

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

async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        f"✅ Код запущен: {PATCH_VERSION}\n"
        f"Файл должен быть именно main.py на Render. Start Command: python -u main.py"
    )


# ───────── Диагностика/лимиты ─────────
async def cmd_diag_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tier = get_subscription_tier(user_id)
    lim = _limits_for(user_id)
    row = _usage_row(user_id, _today_ymd())
    lines = [
        f"👤 Тариф: {tier}",
        f"• Тексты сегодня: {row['text_count']} / {lim['text_per_day']}",
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

def _is_photo_revival_question(text: str) -> bool:
    """Жёсткий перехват вопросов/фраз про возможность оживить фото.
    Не отдаём такие фразы в GPT, потому что модель может ответить общим отказом.
    """
    tl = (text or "").strip().lower()
    if not tl:
        return False
    has_photo = bool(re.search(r"(фото|фотограф|картинк|изображен|image|picture|photo)", tl, re.I))
    has_revival = bool(re.search(r"(ожив|анимир|движен|image\s*to\s*video|i2v|revive|animate)", tl, re.I))
    has_ability = bool(re.search(r"(мож(ешь|ете|но)|уме(ешь|ете)|способен|поддерживаешь|делаешь|получится|может\s+ли)", tl, re.I))
    # Ловим и прямой вопрос «можешь оживить фото?», и фразы вида «оживление фото возможно?»
    return has_photo and has_revival and (has_ability or "?" in tl)

def _is_photo_revival_intent(text: str) -> bool:
    """Ловит не только вопрос «можешь оживить фото?», но и команду/намерение «оживи это фото»."""
    tl = (text or "").strip().lower().replace("ё", "е")
    if not tl:
        return False
    has_photo = bool(re.search(r"(фото|фотограф|картинк|изображен|image|picture|photo)", tl, re.I))
    has_revival = bool(re.search(r"(ожив|анимир|движен|image\s*to\s*video|i2v|revive|animate|сделай\s+видео)", tl, re.I))
    return has_photo and has_revival


def _revival_engine_from_text(text: str, default: str = "runway") -> str:
    tl = (text or "").lower().replace("ё", "е")
    if "luma" in tl or "лума" in tl:
        return "luma"
    if "sora" in tl or "сора" in tl:
        return "sora"
    if "kling" in tl or "клинг" in tl:
        return "kling"
    if "runway" in tl or "ранвей" in tl or "ранвэй" in tl:
        return "runway"
    return default


def _clean_revival_prompt(text: str) -> str:
    cleaned = re.sub(
        r"\b(оживи|оживить|анимируй|анимировать|сделай\s+видео|revive|animate|image\s*to\s*video|i2v|runway|luma|sora|kling|лума|сора|клинг|ранвей|ранвэй)\b",
        "",
        text or "",
        flags=re.I,
    )
    cleaned = re.sub(
        r"\b(фото|фотографи(?:я|ю|и|ей)?|картинк(?:а|у|и|ой)?|изображени(?:е|я|ю)?|photo|image|picture)\b",
        "",
        cleaned,
        flags=re.I,
    ).strip(" ,.:-—")
    # Не отправляем в движок мусорный промпт вроде «это» / «пожалуйста».
    if len(cleaned) < 4:
        return ""
    return cleaned


def _photo_revival_capability_text() -> str:
    return (
        "Да, могу оживить фотографию и сделать из неё короткое видео.\n\n"
        "Как запустить:\n"
        "1) загрузите фото;\n"
        "2) нажмите кнопку ✨ Оживить: Runway / Kling / Sora 2 без людей;\n"
        "3) либо отправьте фото с подписью: «оживи фото: лёгкая улыбка, движение камеры, 5 секунд, 9:16».\n\n"
        "Важно: Sora 2 часто блокирует загруженные фото с людьми из-за модерации. "
        "Для портретов и фото людей лучше выбирать Runway или Kling. "
        "Sora 2 оставлена для изображений без людей: предметы, животные, здания, пейзажи, интерьер.\n\n"
        "Если движок вернёт ошибку, я покажу техническую причину: ключ, лимит, кредиты, модерация или формат запроса."
    )

MEDICAL_DISCLAIMER = (
    "\n\n⚠️ Важно: это справочный разбор и подготовка вопросов к врачу, "
    "а не официальный диагноз, не медицинское заключение и не замена очной консультации/обследования."
)

_MEDICAL_TERMS_RE = re.compile(
    # ВАЖНО: не используем голый корень «анализ»,
    # иначе фразы «анализ PDF/электронных книг/фото» ошибочно уходят в медицину.
    r"(медицин|медкарт|истори[яи]\s+болезн|выписк|анамнез|"
    r"результат(?:ы)?\s+(?:лабораторн(?:ых|ого)?\s+)?анализ(?:ов|ы)?|"
    r"лабораторн(?:ые|ых|ого)?\s+анализ(?:ы|ов)?|"
    r"анализ(?:ы|ов)?\s+(?:крови|мочи|кал[а-я]*|гормон(?:ы|ов)?|биохими[яи]|ферритин|глюкоз[а-я]*|холестерин)|"
    r"заключени|врачебн|диагноз|эпикриз|назначени|рецепт|"
    r"рентген|узи|мрт|кт|mri|ct|томограф|"
    r"(?:медицинск(?:ий|ого|ому|им|ом|ая|ую|ое|ие|их)\s+)?снимок|"
    r"перелом|травм|боль|болит|от[её]к|симптом|лечение|врач|пациент|"
    r"blood\s*test|medical|x[-\s]?ray|ultrasound|scan)",
    re.I,
)
_MEDICAL_ABILITY_RE = re.compile(
    r"(мож(ешь|ете|но)|уме(ешь|ете)|способен|поддерживаешь|анализируешь|"
    r"работаешь|разбираешь|может\s+ли|можно\s+ли|получится)",
    re.I,
)

def _is_medical_capability_question(text: str) -> bool:
    tl = (text or "").strip().lower()
    if not tl:
        return False
    return bool(_MEDICAL_TERMS_RE.search(tl) and (_MEDICAL_ABILITY_RE.search(tl) or "?" in tl))

def _medical_capability_text() -> str:
    return (
        "Да, могу помочь с медицинскими файлами и документами.\n\n"
        "Что могу разобрать:\n"
        "• выписку из медицинской карты и анамнез;\n"
        "• врачебное заключение/эпикриз/назначения;\n"
        "• результаты лабораторных анализов;\n"
        "• снимок, фото документа, УЗИ/рентген;\n"
        "• описание МРТ и КТ, а также изображение, если его можно прочитать по фото.\n\n"
        "Что вы получите: понятную выжимку, расшифровку терминов, ключевые показатели, "
        "красные флаги, список вопросов врачу и план, что уточнить дальше."
        + MEDICAL_DISCLAIMER
    )

def _medical_menu_text(track: str = "") -> str:
    title = {
        "med_extract": "выписку из медицинской карты",
        "med_scan": "снимок/фото медицинского документа",
        "med_conclusion": "врачебное заключение",
        "med_mri": "МРТ",
        "med_ct": "КТ",
        "med_labs": "результаты анализов",
    }.get(track, "медицинский документ или снимок")
    return (
        f"🩺 Медицина — готов разобрать {title}.\n\n"
        "Как загрузить:\n"
        "1) нажмите нужную кнопку ниже;\n"
        "2) отправьте PDF/DOCX/TXT или фото/скрин/изображение;\n"
        "3) в подписи можно написать цель: «коротко», «подробно», «что спросить у врача», "
        "«объясни простыми словами».\n\n"
        "Результат: краткое резюме, расшифровка терминов, важные цифры/находки, "
        "возможные риски, вопросы врачу и что проверить дополнительно."
        + MEDICAL_DISCLAIMER
    )

def medicine_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Проанализировать выписку", callback_data="act:med:extract")],
        [InlineKeyboardButton("🖼 Проанализировать снимок", callback_data="act:med:scan")],
        [InlineKeyboardButton("🧾 Врачебное заключение", callback_data="act:med:conclusion")],
        [InlineKeyboardButton("🧲 МРТ", callback_data="act:med:mri"),
         InlineKeyboardButton("🧠 КТ", callback_data="act:med:ct")],
        [InlineKeyboardButton("🧪 Результаты анализов", callback_data="act:med:labs")],
        [InlineKeyboardButton("📝 Свободный мед. вопрос", callback_data="act:med:free")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="mode:root")],
    ])

def _medical_track_title(track: str) -> str:
    return {
        "med_extract": "выписка / анамнез",
        "med_scan": "медицинский снимок / фото",
        "med_conclusion": "врачебное заключение",
        "med_mri": "МРТ",
        "med_ct": "КТ",
        "med_labs": "лабораторные анализы",
        "med_free": "медицинский вопрос",
    }.get(track or "", "медицинский материал")

def _is_medical_context(user_id: int, caption_or_text: str = "", filename: str = "") -> bool:
    # Совместимость для старых мест вызова без context.
    # ВАЖНО: один только mode == "Медицина" больше не считается причиной
    # отправлять любое фото/документ в медицинскую ветку.
    track = ""
    with contextlib.suppress(Exception):
        track = _mode_track_get(user_id)
    combined = f"{caption_or_text or ''} {filename or ''}"
    return bool(_MEDICAL_TERMS_RE.search(combined))

def _medical_doc_prompt(text: str, track: str = "", goal: str | None = None) -> str:
    task = _medical_track_title(track)
    extra = f"\nЦель пользователя: {goal}" if goal else ""
    return (
        f"Ты анализируешь медицинский материал: {task}. "
        "Не ставь диагноз и не назначай лечение. Дай справочный разбор на русском. "
        "Структура ответа:\n"
        "1) Что это за документ/исследование.\n"
        "2) Краткое резюме простыми словами.\n"
        "3) Ключевые показатели/находки и что они могут означать в общем смысле.\n"
        "4) Возможные тревожные пункты, которые стоит обсудить с врачом.\n"
        "5) Список вопросов врачу.\n"
        "6) Что проверить/какие данные нужны для полноценной оценки.\n"
        "В конце обязательно добавь: это не диагноз и не замена консультации врача."
        f"{extra}\n\nТекст документа:\n{text[:24000]}"
    )

async def _medical_analyze_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, goal: str | None = None):
    user_id = update.effective_user.id
    track = _mode_track_get(user_id)
    await update.effective_message.reply_text("🩺 Анализирую медицинский материал. Это справочный разбор, не диагноз…")
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
    await update.effective_message.reply_text("🩺 Анализирую медицинское изображение/снимок. Это справочный разбор, не диагноз…")
    prompt = (
        f"Разбери медицинское изображение/документ: {_medical_track_title(track)}. "
        "Если это фото выписки/анализов — прочитай видимый текст и структурируй. "
        "Если это снимок МРТ/КТ/рентген/УЗИ — опиши только видимые элементы и ограничения: "
        "по одному изображению нельзя ставить диагноз, нужен официальный протокол и врач. "
        "Дай: 1) что видно, 2) возможный смысл терминов/показателей, 3) что уточнить у врача, "
        "4) какие дополнительные данные нужны. Не назначай лечение. "
        "В конце добавь предупреждение, что это не официальное медицинское заключение."
    )
    if goal:
        prompt += f"\nЦель пользователя: {goal}"
    b64 = base64.b64encode(img_bytes).decode("ascii")
    ans = await ask_openai_vision(prompt, b64, sniff_image_mime(img_bytes))
    if MEDICAL_DISCLAIMER.strip() not in ans:
        ans = ans.rstrip() + MEDICAL_DISCLAIMER
    await update.effective_message.reply_text(ans[:3900])
    if len(ans) > 3900:
        await update.effective_message.reply_text(ans[3900:7800])
    await maybe_tts_reply(update, context, ans[:TTS_MAX_CHARS])

async def on_photo_revival_capability(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _set_waiting_photo_revival(update, context)
    await update.effective_message.reply_text(_photo_revival_capability_text(), reply_markup=main_kb)

def capability_answer(text: str) -> str | None:
    """
    Короткие ответы на вопросы вида:
    - «ты можешь анализировать PDF?»
    - «ты умеешь работать с электронными книгами?»
    - «ты можешь создавать видео?» и т.п.

    Важно: не перехватываем реальные команды
    «сделай видео…», «сгенерируй картинку…» и т.д.
    """
    tl = (text or "").strip().lower()
    if not tl:
        return None

    if _is_medical_capability_question(tl):
        return _medical_capability_text()

    if _is_photo_revival_question(tl):
        return _photo_revival_capability_text()

    # --- Оживление фото / image-to-video ---
    if (
        re.search(r"(мож(ешь|ете)|уме(ешь|ете)|может\s+ли|способен|поддерживаешь)", tl)
        and re.search(r"(ожив|анимир|движени|image\s*to\s*video|i2v)", tl)
        and re.search(r"(фото|фотограф|картинк|изображен|image|picture)", tl)
    ):
        return (
            "Да, могу оживить фотографию и сделать из неё короткое видео. "
            "Загрузите фото — я покажу кнопки Runway, Kling и Sora 2 без людей. "
            "Можно также отправить фото с подписью: «оживи фото: лёгкая улыбка, движение камеры, 5 секунд, 9:16»."
        )

    # --- Медицина / мед. документы / анализы / МРТ / КТ ---
    if _is_medical_capability_question(tl):
        return _medical_capability_text()

    # --- Документы / файлы ---
    if re.search(r"\b(pdf|docx|epub|fb2|txt|mobi|azw)\b", tl) and "?" in tl:
        return (
            "Да, я могу помочь с анализом документов и электронных книг. "
            "Отправь файл (PDF, EPUB, DOCX, FB2, TXT, MOBI/AZW – по возможности), "
            "а в сообщении напиши, что нужно: конспект, план, разбор и т.п."
        )

    # --- Аудио / речь ---
    if "аудио" in tl or "голосов" in tl or "speech" in tl:
        if "?" in tl or "можешь" in tl or "умеешь" in tl:
            return (
                "Да, я могу распознавать речь из голосовых и аудио. "
                "Просто пришли голосовое сообщение — я расшифрую его в текст "
                "и отвечу как на обычный запрос."
            )

    # --- Видео / ролики / Reels / Shorts ---
    # Важно: голосовые часто приходят без вопросительного знака: «ты можешь создать видео ...».
    # Такой запрос не должен уходить в общий GPT-чат, где модель может ответить отказом.
    if (
        re.search(r"(видео|ролик|клип|reels?|shorts?|video|clip)", tl, re.I)
        and re.search(r"(ты\s+)?(мож(ешь|ете|но)|уме(ешь|ете)|способен|поддерживаешь|делаешь|созда[её]шь|может\s+ли|можно\s+ли|получится\s+ли)", tl, re.I)
    ):
        return (
            "Да, могу создавать короткий видеоконтент по тексту или голосовому запросу. "
            "Напишите или скажите командой: «создай видео: медведь летит на воздушном шаре, 5 секунд, 16:9». "
            "После этого я покажу выбор движка: Sora 2 или Kling. Runway оставлен только для оживления фото по загруженной фотографии. "
            "Luma сейчас временно скрыта и не используется."
        )

    # --- Картинки / изображения ---
    if re.search(r"(картинк|изображен|фото|фотограф|image|picture|логотип|баннер)", tl) and "?" in tl:
        return (
            "Да, могу работать с изображениями: анализировать фото, удалять/заменять фон, расширять кадр, "
            "делать ретушь собственных изображений, убирать лишние надписи/объекты, "
            "создавать логотипы/картинки по описанию и оживлять фото в короткое видео. "
            "Загрузите фото — появятся быстрые кнопки действий."
        )

    # Ничего подходящего — пусть дальше обрабатывается обычной логикой
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
        "  (расходуется на перерасход по Runway/Images)\n\n"
        "Детализация сегодня / лимиты тарифа:\n"
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
            "🚀 Runway / Kling / Sora 2 — премиум-рендеры",
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
            await _safe_q_edit(update, context, _plans_overview_text(user_id), reply_markup=plans_root_kb())
            await q.answer()
            return
        if arg in SUBS_TIERS:
            await _safe_q_edit(update, context, 
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
                msg = await _safe_q_edit(update, context, 
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
            await _safe_q_edit(update, context, 
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
def photo_quick_actions_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Оживить (Runway)", callback_data="pedit:revive_runway"),
         InlineKeyboardButton("✨ Sora 2 без людей", callback_data="pedit:revive_sora")],
        [InlineKeyboardButton("✨ Оживить (Kling)",  callback_data="pedit:revive_kling")],
        [InlineKeyboardButton("🧽 Ретушь / убрать надпись", callback_data="pedit:retouch")],
        [InlineKeyboardButton("🧼 Удалить фон",  callback_data="pedit:removebg"),
         InlineKeyboardButton("🖼 Заменить фон", callback_data="pedit:replacebg")],
        [InlineKeyboardButton("🧭 Расширить кадр (outpaint)", callback_data="pedit:outpaint"),
         InlineKeyboardButton("📽 Раскадровка", callback_data="pedit:story")],
        [InlineKeyboardButton("🖌 Картинка по описанию", callback_data="pedit:lumaimg"),
         InlineKeyboardButton("👁 Анализ фото", callback_data="pedit:vision")],
    ])

_photo_cache = {}      # user_id -> bytes
_photo_url_cache = {}  # user_id -> Telegram file URL when available

def _cache_photo(user_id: int, data: bytes, file_url: str | None = None):
    try:
        _photo_cache[user_id] = data
        if file_url:
            _photo_url_cache[user_id] = str(file_url)
    except Exception:
        pass

def _get_cached_photo(user_id: int) -> bytes | None:
    return _photo_cache.get(user_id)

def _get_cached_photo_url(user_id: int) -> str:
    return _photo_url_cache.get(user_id, "") or ""

def _bg_runtime_status() -> str:
    parts = []
    parts.append(f"BG_PROVIDER={BG_PROVIDER or 'comet'}")
    parts.append(f"Comet={'on' if bool(COMET_API_KEY) else 'missing'}")
    parts.append(f"COMET_BG_MODEL={COMET_BG_MODEL}")
    parts.append("CometBriaKey=on" if bool(COMET_BRIA_API_KEY) else "CometBriaKey=off")
    parts.append("BRIA_legacy=on" if bool(BRIA_API_KEY) else "BRIA_legacy=off")
    parts.append("rembg_legacy=on" if rembg_remove is not None else "rembg_legacy=off")
    parts.append("paths=" + ",".join(COMET_BG_REMOVE_PATHS[:3]))
    return "; ".join(parts)

def _bg_use_comet() -> bool:
    return bool(COMET_API_KEY or COMET_BRIA_API_KEY) and BG_PROVIDER in {"auto", "comet", "cometapi", "bria-comet", "bria/remove-background"}

def _bg_use_bria() -> bool:
    # Legacy emergency path only.
    return bool(BRIA_API_KEY) and BG_PROVIDER in {"bria", "briai", "bria-ai", "legacy-bria"}

def _bg_use_local() -> bool:
    # Legacy emergency path only.
    return LOCAL_REMBG_ENABLED and BRIA_ALLOW_LOCAL_FALLBACK and rembg_remove is not None and BG_PROVIDER in {"local", "rembg", "legacy-local"}

def _comet_bg_key_candidates() -> list[str]:
    keys = []
    for k in (COMET_API_KEY, COMET_BRIA_API_KEY):
        k = (k or "").strip()
        if k and k not in keys:
            keys.append(k)
    return keys

def _as_bria_base64(img_bytes: bytes) -> str:
    return base64.b64encode(img_bytes).decode("ascii")

def _looks_like_image_bytes(data: bytes) -> bool:
    return bool(data) and (data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8\xff") or data.startswith(b"RIFF") or data.startswith(b"GIF8") or data[:12].lower().find(b"webp") >= 0)

def _extract_image_payloads(data):
    """Return image URLs/data-URLs/base64 strings from Comet/Bria/Responses style JSON."""
    found = []
    seen = set()

    def add(x):
        if not isinstance(x, str):
            return
        s = x.strip()
        if not s or s in seen:
            return
        low = s.lower()
        # Direct image URL / data URL.
        if low.startswith("data:image/"):
            seen.add(s); found.append(s); return
        if low.startswith(("http://", "https://")) and any(ext in low.split("?", 1)[0] for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif")):
            seen.add(s); found.append(s); return
        # Some providers return signed image URLs without obvious extension.
        if low.startswith(("http://", "https://")) and any(h in low for h in ("image", "cdn", "storage", "s3", "media", "result", "output", "bria")):
            seen.add(s); found.append(s); return
        # Some responses use raw base64 under fields like b64_json/base64/image.
        compact = s.replace("\n", "").replace("\r", "")
        if len(compact) > 200 and re.fullmatch(r"[A-Za-z0-9+/=]+", compact or ""):
            try:
                raw = base64.b64decode(compact, validate=False)
                if _looks_like_image_bytes(raw):
                    seen.add(s); found.append("data:image/png;base64," + compact)
            except Exception:
                pass

    def walk(obj, key_hint=""):
        if isinstance(obj, dict):
            # Prefer common output fields first.
            for k in (
                "image_url", "imageUrl", "url", "result_url", "output_url", "outputImageUrl",
                "image", "b64_json", "base64", "image_base64", "data", "file", "download_url"
            ):
                if k in obj:
                    v = obj.get(k)
                    if isinstance(v, (dict, list)):
                        walk(v, k)
                    else:
                        add(v)
            # OpenAI Responses often nest output in output/content arrays.
            for k, v in obj.items():
                if k not in {"image_url", "imageUrl", "url", "result_url", "output_url", "outputImageUrl", "image", "b64_json", "base64", "image_base64", "data", "file", "download_url"}:
                    walk(v, k)
        elif isinstance(obj, list):
            for it in obj:
                walk(it, key_hint)
        else:
            add(obj)

    walk(data)
    return found

def _extract_image_url_from_json(data) -> str:
    payloads = _extract_image_payloads(data)
    return payloads[0] if payloads else ""

async def _download_image_url(url: str) -> bytes:
    if url.startswith("data:image/"):
        return base64.b64decode(url.split(",", 1)[1])
    async with httpx.AsyncClient(timeout=COMET_BG_TIMEOUT_S, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "GPT5ProBot/1.0"})
        r.raise_for_status()
        return r.content

async def _comet_bg_get_status(client: httpx.AsyncClient, rid: str, api_key: str) -> dict | None:
    if not rid:
        return None
    headers = {"Authorization": f"Bearer {api_key}"}
    for path in COMET_BG_STATUS_PATHS:
        try:
            url = f"{COMET_BASE_URL}{path.format(id=rid, request_id=rid, task_id=rid)}"
            r = await client.get(url, headers=headers)
            if r.status_code < 400:
                return r.json()
        except Exception as e:
            log.warning("Comet BG status error %s: %s", path, e)
    return None

def _comet_bg_request_candidates(img_bytes: bytes, image_url: str = "") -> list[tuple[str, dict]]:
    """Build robust candidates for Comet Bria bg removal.

    Comet docs list bria/remove-background via /v1/responses, while the Bria
    image-editing family also exposes /bria/image/edit/{action}. We try both.
    """
    mime = sniff_image_mime(img_bytes)
    b64 = base64.b64encode(img_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"
    image_inputs = []
    if image_url and COMET_BG_USE_TELEGRAM_URL:
        image_inputs.append(image_url)
    image_inputs.append(data_url)

    candidates: list[tuple[str, dict]] = []
    # Documented OpenAI-compatible route: POST /v1/responses with input_image.
    for img in image_inputs:
        candidates.append((
            "/v1/responses",
            {
                "model": COMET_BG_MODEL,
                "input": [{
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Remove the background from this image. Return a PNG with transparent background and preserve the foreground subject."},
                        {"type": "input_image", "image_url": img},
                    ],
                }],
            }
        ))
    # Compatibility: some OpenAI-like routes accept a flat prompt + image.
    for img in image_inputs:
        candidates.append((
            "/v1/responses",
            {"model": COMET_BG_MODEL, "prompt": "Remove the background from this image and return a transparent PNG.", "image": img}
        ))
    # Bria-compatible edit route: POST /bria/image/edit/remove-background.
    bria_payloads = []
    if image_url and COMET_BG_USE_TELEGRAM_URL:
        bria_payloads.extend([
            {"image_url": image_url, "preserve_alpha": True, "force_background_detection": True, "visual_input_content_moderation": False, "visual_output_content_moderation": False, "sync": True},
            {"image": image_url, "preserve_alpha": True, "force_background_detection": True, "visual_input_content_moderation": False, "visual_output_content_moderation": False, "sync": True},
        ])
    bria_payloads.extend([
        {"image": b64, "preserve_alpha": True, "force_background_detection": True, "visual_input_content_moderation": False, "visual_output_content_moderation": False, "sync": True},
        {"image": data_url, "preserve_alpha": True, "force_background_detection": True, "visual_input_content_moderation": False, "visual_output_content_moderation": False, "sync": True},
        {"image_url": data_url, "preserve_alpha": True, "force_background_detection": True, "visual_input_content_moderation": False, "visual_output_content_moderation": False, "sync": True},
    ])
    for path in COMET_BG_REMOVE_PATHS:
        if path == "/v1/responses":
            continue
        for payload in bria_payloads:
            candidates.append((path, payload))
    return candidates

async def _comet_remove_bg_bytes(img_bytes: bytes, image_url: str = "") -> bytes | None:
    """CometAPI background removal using bria/remove-background.

    Tries both Comet's /v1/responses model path and Bria-compatible
    /bria/image/edit/remove-background path. This avoids the previous failure
    where only /v1/responses + base64 data URL was attempted.
    """
    keys = _comet_bg_key_candidates()
    if not keys:
        return None
    last_err = None
    candidates = _comet_bg_request_candidates(img_bytes, image_url=image_url or "")
    async with httpx.AsyncClient(timeout=COMET_BG_TIMEOUT_S, follow_redirects=True) as client:
        for api_key in keys:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            for path, payload in candidates:
                try:
                    r = await client.post(f"{COMET_BASE_URL}{path}", headers=headers, json=payload)
                    if r.status_code >= 400:
                        last_err = f"POST {path} -> {r.status_code}: {r.text[:900]}"
                        continue
                    try:
                        data = r.json()
                    except Exception:
                        # Rare case: provider returns raw image bytes.
                        if _looks_like_image_bytes(r.content):
                            return r.content
                        last_err = f"POST {path} returned non-json: {r.text[:500]}"
                        continue
                    img = _extract_image_url_from_json(data)
                    if img:
                        return await _download_image_url(img)
                    rid = ""
                    if isinstance(data, dict):
                        rid = str(data.get("id") or data.get("response_id") or data.get("request_id") or data.get("task_id") or data.get("job_id") or "")
                        status_url = str(data.get("status_url") or data.get("poll_url") or data.get("urls", {}).get("get") or "")
                    else:
                        status_url = ""
                    start = time.time()
                    while rid and time.time() - start < COMET_BG_MAX_WAIT_S:
                        await asyncio.sleep(COMET_BG_POLL_DELAY_S)
                        sd = None
                        if status_url:
                            try:
                                rr = await client.get(status_url, headers=headers)
                                if rr.status_code < 400:
                                    sd = rr.json()
                            except Exception:
                                sd = None
                        if sd is None:
                            sd = await _comet_bg_get_status(client, rid, api_key)
                        if not sd:
                            continue
                        img = _extract_image_url_from_json(sd)
                        if img:
                            return await _download_image_url(img)
                        st = str(sd.get("status") or sd.get("state") or sd.get("task_status") or "").lower() if isinstance(sd, dict) else ""
                        if st in {"failed", "error", "rejected", "cancelled", "canceled"}:
                            last_err = f"status {rid}: {str(sd)[:900]}"
                            break
                    last_err = f"POST {path} accepted but no image found: {str(data)[:900]}"
                except Exception as e:
                    last_err = f"POST {path} exception: {repr(e)}"
                    continue
    if last_err:
        log.warning("Comet background removal failed: %s", last_err)
        try:
            # Stored in module globals for optional user-facing diagnostics.
            globals()["_LAST_COMET_BG_ERROR"] = last_err
        except Exception:
            pass
    return None

async def _bria_image_call(url: str, payloads: list[dict]) -> bytes | None:
    """Legacy direct BRIA fallback. Not used when BG_PROVIDER=comet."""
    if not BRIA_API_KEY:
        return None
    last_err = None
    async with httpx.AsyncClient(timeout=BRIA_TIMEOUT_S, follow_redirects=True) as client:
        for payload in payloads:
            body = dict(payload)
            if BRIA_SYNC:
                body.setdefault("sync", True)
            headers = {"Content-Type": "application/json", "api_token": BRIA_API_KEY}
            try:
                r = await client.post(url, headers=headers, json=body)
                if r.status_code >= 400:
                    last_err = f"{r.status_code}: {r.text[:500]}"
                    continue
                data = r.json()
                img_url = _extract_image_url_from_json(data)
                if img_url:
                    return await _download_image_url(img_url)
                status_url = data.get("status_url") or data.get("urls", {}).get("get") if isinstance(data, dict) else None
                if status_url:
                    for _ in range(60):
                        await asyncio.sleep(2)
                        rr = await client.get(status_url, headers=headers)
                        if rr.status_code >= 400:
                            continue
                        sd = rr.json()
                        img_url = _extract_image_url_from_json(sd)
                        if img_url:
                            return await _download_image_url(img_url)
                        st = str(sd.get("status") or sd.get("state") or "").lower()
                        if st in ("failed", "error", "rejected"):
                            last_err = str(sd)[:500]
                            break
                last_err = str(data)[:500]
            except Exception as e:
                last_err = repr(e)
                continue
    if last_err:
        log.warning("BRIA legacy image call failed: %s", last_err)
    return None

async def _bria_remove_bg_bytes(img_bytes: bytes) -> bytes | None:
    b64 = _as_bria_base64(img_bytes)
    data_url = f"data:{sniff_image_mime(img_bytes)};base64,{b64}"
    payloads = [
        {"image": b64, "preserve_alpha": True, "visual_input_content_moderation": False, "visual_output_content_moderation": False, "force_background_detection": True},
        {"image": data_url, "preserve_alpha": True, "visual_input_content_moderation": False, "visual_output_content_moderation": False, "force_background_detection": True},
    ]
    return await _bria_image_call(BRIA_REMOVE_BG_URL, payloads)

def _bria_bg_prompt(preset: str) -> str:
    preset = (preset or "blur").lower().strip()
    prompts = {
        "white": "clean pure white studio background, professional product photo lighting, keep the person or main object unchanged",
        "beach": "luxury tropical beach background, soft daylight, premium travel photography, realistic perspective, keep the person or main object unchanged",
        "nature": "fresh green natural background, soft daylight, realistic outdoor photography, keep the person or main object unchanged",
        "office": "modern bright office studio background, clean professional business setting, keep the person or main object unchanged",
        "luxury": "premium luxury interior background, elegant warm lighting, high-end editorial style, keep the person or main object unchanged",
        "blur": "soft blurred indoor background with realistic depth of field, keep the person or main object unchanged and sharp",
    }
    return prompts.get(preset, prompts["blur"])

async def _bria_replace_bg_bytes(img_bytes: bytes, preset: str) -> bytes | None:
    b64 = _as_bria_base64(img_bytes)
    data_url = f"data:{sniff_image_mime(img_bytes)};base64,{b64}"
    prompt = _bria_bg_prompt(preset)
    payloads = [
        {"image": b64, "mode": BRIA_REPLACE_BG_MODE, "prompt": prompt, "original_quality": True, "force_background_detection": True, "visual_output_content_moderation": False},
        {"image": data_url, "mode": BRIA_REPLACE_BG_MODE, "prompt": prompt, "original_quality": True, "force_background_detection": True, "visual_output_content_moderation": False},
    ]
    return await _bria_image_call(BRIA_REPLACE_BG_URL, payloads)

async def _remove_bg_bytes_primary(img_bytes: bytes, image_url: str = "") -> bytes | None:
    """v47 production order: Comet bria/remove-background first.

    We pass Telegram file URL when available because Comet/Bria routes can be
    stricter with base64 data URLs. Legacy fallbacks only if explicitly enabled.
    """
    if _bg_use_comet():
        out = await _comet_remove_bg_bytes(img_bytes, image_url=image_url or "")
        if out:
            return out
    if _bg_use_bria():
        out = await _bria_remove_bg_bytes(img_bytes)
        if out:
            return out
    if _bg_use_local():
        try:
            return rembg_remove(img_bytes)
        except Exception as e:
            log.warning("local rembg fallback failed: %s", e)
    return None

async def _pedit_removebg(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    try:
        user_id = update.effective_user.id if update.effective_user else 0
        img_url = _get_cached_photo_url(user_id) if user_id else ""
        out = await _remove_bg_bytes_primary(img_bytes, image_url=img_url)
        if not out:
            diag = _bg_runtime_status()
            last = globals().get("_LAST_COMET_BG_ERROR", "")
            extra = f"\n\nПоследняя ошибка Comet: {str(last)[:900]}" if COMET_BG_DEBUG_TO_CHAT and last else ""
            await update.effective_message.reply_text(
                "Не удалось удалить фон через Comet. Проверьте доступность модели bria/remove-background в Comet и корректность COMET_API_KEY.\n"
                f"Диагностика: {diag}{extra}"
            )
            return
        bio = BytesIO(out); bio.name = "no_bg.png"; bio.seek(0)
        await update.effective_message.reply_document(InputFile(bio), caption="Фон удалён через Comet ✅ Прозрачный PNG.")
    except Exception as e:
        log.exception("removebg error: %s", e)
        await update.effective_message.reply_text("Не удалось удалить фон через Comet.")

def _bg_replace_preset_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌫 Размытие", callback_data="pedit:bg:blur"), InlineKeyboardButton("⚪ Белый", callback_data="pedit:bg:white")],
        [InlineKeyboardButton("🌴 Пляж", callback_data="pedit:bg:beach"), InlineKeyboardButton("🌿 Природа", callback_data="pedit:bg:nature")],
        [InlineKeyboardButton("🏢 Офис", callback_data="pedit:bg:office"), InlineKeyboardButton("✨ Luxury", callback_data="pedit:bg:luxury")],
        [InlineKeyboardButton("⬅️ Фото", callback_data="nav:photo")],
    ])

def _bg_preset_from_text(text: str) -> str:
    t = (text or "").lower()
    if any(x in t for x in ("бел", "white")):
        return "white"
    if any(x in t for x in ("пляж", "море", "beach", "sea", "ocean")):
        return "beach"
    if any(x in t for x in ("природ", "лес", "зел", "nature", "forest")):
        return "nature"
    if any(x in t for x in ("офис", "студ", "office", "studio")):
        return "office"
    if any(x in t for x in ("luxury", "преми", "золот", "дорог")):
        return "luxury"
    return "blur"

def _make_replacement_bg(size: tuple[int, int], preset: str, src_img=None):
    w, h = size
    preset = (preset or "blur").lower().strip()
    if preset == "blur" and src_img is not None:
        base = src_img.convert("RGB")
        if ImageFilter:
            base = base.filter(ImageFilter.GaussianBlur(radius=max(18, min(w, h)//24)))
        return base.convert("RGBA")
    if preset == "white":
        return Image.new("RGBA", (w, h), (255, 255, 255, 255))
    palettes = {
        "beach": ((86, 188, 232), (255, 222, 157), (245, 190, 110)),
        "nature": ((44, 128, 92), (151, 205, 132), (232, 242, 213)),
        "office": ((224, 228, 235), (183, 194, 207), (245, 245, 247)),
        "luxury": ((34, 45, 38), (181, 151, 88), (246, 236, 210)),
    }
    c1, c2, c3 = palettes.get(preset, palettes["office"])
    bg = Image.new("RGBA", (w, h), c1 + (255,))
    pix = bg.load()
    for y in range(h):
        ratio = y / max(1, h - 1)
        if ratio < 0.55:
            k = ratio / 0.55; a, b = c1, c2
        else:
            k = (ratio - 0.55) / 0.45; a, b = c2, c3
        col = tuple(int(a[i] * (1-k) + b[i] * k) for i in range(3)) + (255,)
        for x in range(w):
            pix[x, y] = col
    if ImageFilter:
        bg = bg.filter(ImageFilter.GaussianBlur(radius=1.2))
    return bg

async def _foreground_cutout(img_bytes: bytes, image_url: str = ""):
    out = await _remove_bg_bytes_primary(img_bytes, image_url=image_url or "")
    if not out or Image is None:
        return None
    return Image.open(BytesIO(out)).convert("RGBA")

async def _pedit_replacebg_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    provider_line = "Comet bria/remove-background"
    msg = (
        f"🌈 Выберите новый фон. Провайдер: {provider_line}. "
        "Объект/человек сохраняется, меняется только фон.\n\n"
        "Для прозрачного PNG используйте «Фон» / «Удалить фон»."
    )
    if getattr(update, "callback_query", None) and update.callback_query.message:
        await update.callback_query.message.reply_text(msg, reply_markup=_bg_replace_preset_kb())
    else:
        await update.effective_message.reply_text(msg, reply_markup=_bg_replace_preset_kb())

async def _pedit_replacebg(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes, preset: str = "blur"):
    if Image is None:
        await update.effective_message.reply_text("Pillow не установлен.")
        return
    try:
        src = Image.open(BytesIO(img_bytes)).convert("RGBA")
        user_id = update.effective_user.id if update.effective_user else 0
        img_url = _get_cached_photo_url(user_id) if user_id else ""
        fg = await _foreground_cutout(img_bytes, image_url=img_url)
        if fg is None:
            raise RuntimeError("Comet foreground cutout failed")
        if fg.size != src.size:
            fg = fg.resize(src.size, Image.LANCZOS)
        bg = _make_replacement_bg(src.size, preset, src_img=src)
        bg.alpha_composite(fg)
        out = bg.convert("RGB")
        bio = BytesIO(); out.save(bio, format="JPEG", quality=94); bio.seek(0); bio.name = f"comet_bg_{preset}.jpg"
        captions = {
            "blur": "Заменил фон через Comet: размытый фон, объект резкий ✅",
            "white": "Заменил фон через Comet: белая подложка ✅",
            "beach": "Заменил фон через Comet: пляжная подложка ✅",
            "nature": "Заменил фон через Comet: природная подложка ✅",
            "office": "Заменил фон через Comet: офисная/студийная подложка ✅",
            "luxury": "Заменил фон через Comet: premium/luxury подложка ✅",
        }
        await update.effective_message.reply_photo(InputFile(bio), caption=captions.get(preset, "Фон заменён через Comet ✅"))
    except Exception as e:
        log.exception("replacebg error: %s", e)
        await update.effective_message.reply_text(
            "Не удалось заменить фон через Comet. Проверьте доступность модели bria/remove-background в Comet.\n"
            f"Диагностика: {_bg_runtime_status()}" + (f"\n\nПоследняя ошибка Comet: {str(globals().get('_LAST_COMET_BG_ERROR', ''))[:900]}" if COMET_BG_DEBUG_TO_CHAT and globals().get("_LAST_COMET_BG_ERROR") else "")
        )

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
    try:
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
                await _safe_q_edit(update, context, f"Минимальная сумма пополнения: {MIN_RUB_FOR_INVOICE} ₽")
                return
            ok = await _send_invoice_rub("Пополнение баланса", "Единый кошелёк для перерасходов.", amount_rub, "t=3", update)
            await q.answer("Выставляю счёт…" if ok else "Не удалось выставить счёт", show_alert=not ok)
            return

        # TOPUP CRYPTO
        if data.startswith("topup:crypto:"):
            await q.answer()
            if not CRYPTO_PAY_API_TOKEN:
                await _safe_q_edit(update, context, "Настройте CRYPTO_PAY_API_TOKEN для оплаты через CryptoBot.")
                return
            try:
                usd = float((data.split(":", 2)[-1] or "0").strip() or "0")
            except Exception:
                usd = 0.0
            if usd <= 0.0:
                await _safe_q_edit(update, context, "Неверная сумма.")
                return
            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(usd, asset="USDT", description="Wallet top-up")
            if not inv_id or not pay_url:
                await _safe_q_edit(update, context, "Не удалось создать счёт в CryptoBot. Попробуйте позже.")
                return
            msg = await update.effective_message.reply_text(
                f"Оплатите через CryptoBot: ≈ ${usd_amount:.2f} ({asset}).\nПосле оплаты баланс пополнится автоматически.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить в CryptoBot", url=pay_url)],
                    [InlineKeyboardButton("Проверить оплату", callback_data=f"crypto:check:{inv_id}")]
                ])
            )
            context.application.create_task(_poll_crypto_invoice(
                context, msg.chat_id, msg.message_id, update.effective_user.id, inv_id, usd_amount
            ))
            return

        if data.startswith("crypto:check:"):
            await q.answer()
            inv_id = data.split(":", 2)[-1]
            inv = await _crypto_get_invoice(inv_id)
            if not inv:
                await _safe_q_edit(update, context, "Не нашёл счёт. Создайте новый.")
                return
            st = (inv.get("status") or "").lower()
            if st == "paid":
                usd_amount = float(inv.get("amount", 0.0))
                if (inv.get("asset") or "").upper() == "TON":
                    usd_amount *= TON_USD_RATE
                _wallet_total_add(update.effective_user.id, usd_amount)
                await _safe_q_edit(update, context, f"💳 Оплата получена. Баланс пополнен на ≈ ${usd_amount:.2f}.")
            elif st == "active":
                await q.answer("Платёж ещё не подтверждён", show_alert=True)
            else:
                await _safe_q_edit(update, context, f"Статус счёта: {st}")
            return

        # Подписка: выбор способа
        if data.startswith("buy:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            desc = f"Подписка {tier.upper()} на {months} мес."
            await _safe_q_edit(update, context, 
                f"{desc}\nВыберите способ оплаты:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Оплатить картой (ЮKassa)", callback_data=f"buyinv:{tier}:{months}")],
                    [InlineKeyboardButton("Списать с баланса (USD)",  callback_data=f"buywallet:{tier}:{months}")],
                ])
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
            amount_rub = _plan_rub(tier, {1: "month", 3: "quarter", 12: "year"}[months])
            need_usd = float(amount_rub) / max(1e-9, USD_RUB)
            if _wallet_total_take(update.effective_user.id, need_usd):
                until = activate_subscription_with_tier(update.effective_user.id, tier, months)
                await _safe_q_edit(update, context, 
                    f"✅ Подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')}.\n"
                    f"Списано с баланса: ~${need_usd:.2f}."
                )
            else:
                await _safe_q_edit(update, context, 
                    "Недостаточно средств на едином балансе.\nПополните баланс и повторите.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]])
                )
            return

        # Выбор движка
        if data.startswith("engine:"):
            await q.answer()
            engine = data.split(":", 1)[1]
            if engine == "luma" and LUMA_TEMP_DISABLED:
                await _safe_q_edit(update, context, "⚠️ Luma временно отключена и скрыта из меню. Используйте Sora 2, Kling, Images или другие доступные движки. Runway — только для оживления фото.")
                return
            username = (update.effective_user.username or "")
            if engine == "runway":
                await _safe_q_edit(update, context, 
                    "✅ Runway включён только для оживления фото.\n"
                    "Загрузите фотографию и нажмите ✨ Оживить (Runway) или отправьте фото с подписью: "
                    "«оживи фото: лёгкая улыбка, движение камеры, 5 секунд, 9:16».\n\n"
                    "Для создания видео по тексту/голосу используйте Sora 2 или Kling."
                )
                return
            if is_unlimited(update.effective_user.id, username):
                await _safe_q_edit(update, context, 
                    f"✅ Движок «{engine}» доступен без ограничений.\n"
                    f"Для text→video используйте Sora 2 или Kling. Runway — только оживление фото."
                )
                return

            if engine in ("gpt", "stt_tts", "midjourney", "sora", "kling"):
                await _safe_q_edit(update, context, 
                    f"✅ Выбран «{engine}». Отправьте запрос текстом/фото. "
                    f"Для видео напишите: «создай видео … 5 секунд 16:9» — я предложу Sora 2 или Kling. Runway — только для оживления фото."
                )
                return

            est_cost = IMG_COST_USD if engine == "images" else (0.40 if engine == "luma" else max(1.0, RUNWAY_UNIT_COST_USD))
            map_engine = {"images": "img", "luma": "luma", "runway": "runway"}[engine]
            ok, offer = _can_spend_or_offer(update.effective_user.id, username, map_engine, est_cost)

            if ok:
                await _safe_q_edit(update, context, 
                    "✅ Доступно. " +
                    ("Запустите: /img кот в очках" if engine == "images"
                     else "Для видео по тексту доступны Sora 2 и Kling. Runway используйте только после загрузки фото для оживления.")
                )
                return

            if offer == "ASK_SUBSCRIBE":
                await _safe_q_edit(update, context, 
                    "Для этого движка нужна активная подписка или единый баланс. Откройте /plans или пополните «🧾 Баланс».",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("⭐ Тарифы", web_app=WebAppInfo(url=TARIFF_URL))],
                         [InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]]
                    ),
                )
                return

            try:
                need_usd = float(offer.split(":", 1)[-1])
            except Exception:
                need_usd = est_cost
            amount_rub = _calc_oneoff_price_rub(map_engine, need_usd)
            await _safe_q_edit(update, context, 
                f"Ваш дневной лимит по «{engine}» исчерпан. Разовая покупка ≈ {amount_rub} ₽ "
                f"или пополните баланс в «🧾 Баланс».",
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
            await _safe_q_edit(update, context, "Движки:", reply_markup=engines_kb())
            return

        if data.startswith("mode:set:"):
            await q.answer()
            mode = data.split(":")[-1]
            mode_set(update.effective_user.id, mode)
            if mode == "study":
                study_sub_set(update.effective_user.id, "explain")
                await _safe_q_edit(update, context, "Режим «Учёба» включён. Выберите подрежим:", reply_markup=study_kb())
            elif mode == "photo":
                await _safe_q_edit(update, context, "Режим «Фото» включён. Пришлите изображение — появятся быстрые кнопки.", reply_markup=photo_quick_actions_kb())
            elif mode == "docs":
                await _safe_q_edit(update, context, "Режим «Документы». Пришлите PDF/DOCX/EPUB/TXT — сделаю конспект.")
            elif mode == "voice":
                await _safe_q_edit(update, context, "Режим «Голос». Отправьте voice/audio. Озвучка ответов: /voice_on")
            else:
                await _safe_q_edit(update, context, f"Режим «{mode}» активирован.")
            return

        if data.startswith("study:set:"):
            await q.answer()
            sub = data.split(":")[-1]
            study_sub_set(update.effective_user.id, sub)
            await _safe_q_edit(update, context, f"Учёба → {sub}. Напишите тему/задание.", reply_markup=study_kb())
            return

        # Photo edits require cached image
        if data.startswith("pedit:"):
            await q.answer()
            img = _get_cached_photo(update.effective_user.id)
            if not img:
                await _safe_q_edit(update, context, "Сначала пришлите фото, затем выберите действие.", reply_markup=photo_quick_actions_kb())
                return
            if data == "pedit:retouch":
                _clear_medicine_wait(context)
                _set_retouch_wait_text(context)
                await q.message.reply_text(
                    "🧽 Что убрать и где находится элемент?\n\n"
                    "Например: «водяной знак справа снизу», «надпись по центру», «логотип в левом верхнем углу».\n"
                    "Отправляя команду, вы подтверждаете, что это ваше изображение или у вас есть право его редактировать."
                )
                return
            if data == "pedit:removebg":
                await _pedit_removebg(update, context, img); return
            if data == "pedit:replacebg":
                await _pedit_replacebg_menu(update, context); return
            if data.startswith("pedit:bg:"):
                await _pedit_replacebg(update, context, img, preset=data.split(":")[-1]); return
            if data == "pedit:outpaint":
                await _pedit_outpaint(update, context, img); return
            if data == "pedit:story":
                await _pedit_storyboard(update, context, img); return
            if data in ("pedit:revive", "pedit:revive_runway", "pedit:revive_luma", "pedit:revive_sora", "pedit:revive_kling"):
                engine = {
                    "pedit:revive": "runway",
                    "pedit:revive_runway": "runway",
                    "pedit:revive_luma": "luma",
                    "pedit:revive_sora": "sora",
                    "pedit:revive_kling": "kling",
                }.get(data, "runway")
                if engine == "luma" and LUMA_TEMP_DISABLED:
                    await q.message.reply_text("⚠️ Luma временно отключена и скрыта из меню. Используйте Runway, Kling или Sora 2 без людей.")
                    return
                # Видимый ACK сразу после клика. Так пользователь не видит «молчание», даже если дальше ошибка лимита/API.
                with contextlib.suppress(Exception):
                    await q.message.reply_text(f"🟢 Кнопка принята: запускаю оживление через {engine.upper()}. Проверяю фото, лимиты и API…")
                try:
                    await _start_photo_revival(update, context, engine=engine, img_bytes=img, prompt="")
                except Exception as e:
                    log.exception("pedit revive failed: %s", e)
                    await update.effective_message.reply_text(f"❌ Не удалось запустить оживление через {engine.upper()}: {e}")
                return

            if data == "pedit:lumaimg":
                _mode_track_set(update.effective_user.id, "lumaimg_wait_text")
                await _safe_q_edit(update, context, "Напишите одно предложение — что сгенерировать. Я сделаю картинку.")
                return
            if data == "pedit:vision":
                b64 = base64.b64encode(img).decode("ascii")
                mime = sniff_image_mime(img)
                ans = await ask_openai_vision("Опиши фото и текст на нём кратко.", b64, mime)
                await update.effective_message.reply_text(ans or "Готово.")
                return

        # Подтверждение выбора движка для видео
        if data.startswith("choose:"):
            await q.answer()
            _, engine, aid = data.split(":", 2)
            if engine == "runway":
                _pending_actions.pop(aid, None)
                await _safe_q_edit(update, context, 
                    "⚠️ Runway для создания видео по тексту/голосу отключён. "
                    "Оставлены Sora 2 и Kling. Runway используется только для оживления фото."
                )
                return
            if engine == "luma" and LUMA_TEMP_DISABLED:
                _pending_actions.pop(aid, None)
                await _safe_q_edit(update, context, "⚠️ Luma временно отключена. Выберите Sora 2 или Kling.")
                return
            meta = _pending_actions.pop(aid, None)
            if not meta:
                await q.answer("Задача устарела", show_alert=True)
                return
            prompt   = meta["prompt"]
            duration = meta["duration"]
            aspect   = meta["aspect"]
            if engine == "luma":
                est = 0.40
                map_engine = "luma"
            elif engine == "kling":
                est = KLING_UNIT_COST_USD
                map_engine = "runway"  # используем общий видео-бюджет, чтобы не ломать текущую БД
            elif engine == "sora":
                est = SORA_PRO_UNIT_COST_USD if "pro" in (SORA_MODEL or "").lower() else SORA_UNIT_COST_USD
                map_engine = "runway"  # используем общий видео-бюджет, чтобы не ломать текущую БД
            else:
                await update.effective_message.reply_text(
                    "❌ Для создания видео по тексту/голосу доступны только Sora 2 и Kling."
                )
                return

            async def _start_real_render():
                if engine == "luma":
                    await _run_luma_video(update, context, prompt, duration, aspect)
                    _register_engine_spend(update.effective_user.id, "luma", 0.40)
                elif engine == "sora":
                    await _run_comet_text_video(update, context, "sora", prompt, duration, aspect)
                    _register_engine_spend(update.effective_user.id, "runway", est)
                elif engine == "kling":
                    await _run_comet_text_video(update, context, "kling", prompt, duration, aspect)
                    _register_engine_spend(update.effective_user.id, "runway", est)
                else:
                    await update.effective_message.reply_text(
                        "❌ Для text→video доступны только Sora 2 и Kling. Runway оставлен только для оживления фото."
                    )

            await _try_pay_then_do(
                update, context, update.effective_user.id,
                map_engine, est, _start_real_render,
                remember_kind=f"video_{engine}",
                remember_payload={"prompt": prompt, "duration": duration, "aspect": aspect},
            )
            return

        await q.answer("Неизвестная команда", show_alert=True)

    except Exception as e:
        log.exception("on_cb error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text(f"❌ Ошибка обработки кнопки: {e}")
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
    lines = [
        f"🎬 Видео-движки / {PATCH_VERSION}:",
        f"• Luma key: {'🚫 скрыто временно' if LUMA_TEMP_DISABLED else ('✅' if bool(LUMA_API_KEY) else '❌')}  base={LUMA_BASE_URL}",
        f"  create={LUMA_CREATE_PATH}  status={LUMA_STATUS_PATH}  model={LUMA_MODEL}",
        f"• Runway direct key: {'✅' if bool(RUNWAY_API_KEY) else '❌'}  base={RUNWAY_BASE_URL}",
        f"  i2v={RUNWAY_I2V_PATH}  tasks={RUNWAY_STATUS_PATH}  model={RUNWAY_MODEL}  version={RUNWAY_API_VERSION}",
        f"• Comet key: {'✅' if bool(COMET_API_KEY) else '❌'}  base={COMET_BASE_URL}",
        f"  Runway/Comet create={RUNWAY_COMET_CREATE_PATH}  status={RUNWAY_COMET_STATUS_PATH}",
        f"• Sora key: {'✅' if bool(SORA_API_KEY) else '❌'}  model={SORA_MODEL}  create={SORA_CREATE_PATH}",
        f"• Kling key: {'✅' if bool(KLING_API_KEY) else '❌'}  model={KLING_MODEL}  create={KLING_CREATE_PATH}",
        f"• Нормализация duration: Kling 5 или 10 сек; Sora 4/8/12 сек; Runway только image→video; Sora i2v — без людей; Luma временно скрыта",
        f"• Поллинг каждые {VIDEO_POLL_DELAY_S:.1f} c",
    ]
    await update.effective_message.reply_text("\n".join(lines))


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
    return duration, aspect


# ───────── Luma video ─────────
async def _run_luma_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    duration_s: int,
    aspect: str,
):
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            base = await _pick_luma_base(client)
            create_url = f"{base}{LUMA_CREATE_PATH}"

            headers = {
                "Authorization": f"Bearer {LUMA_API_KEY}",
                "Accept": "application/json",
            }
            payload = {
                "model": LUMA_MODEL,
                "prompt": prompt,
                "duration": f"{duration_s}s",
                "aspect_ratio": aspect,
            }

            # создаём задачу
            r = await client.post(create_url, headers=headers, json=payload)
            if r.status_code >= 400:
                await update.effective_message.reply_text(
                    f"⚠️ Luma отклонила задачу ({r.status_code})."
                )
                return

            data = r.json() or {}
            rid = data.get("id") or data.get("generation_id")
            if not rid:
                log.error("Luma: no generation id in response: %s", data)
                await update.effective_message.reply_text("⚠️ Luma не вернула id генерации.")
                return

            await update.effective_message.reply_text(
                "⏳ Luma рендерит… Я сообщу, когда видео будет готово."
            )

            status_url = f"{base}{LUMA_STATUS_PATH}".format(id=rid)
            started = time.time()

            while True:
                rs = await client.get(status_url, headers=headers)
                try:
                    js = rs.json() or {}
                except Exception:
                    js = {}

                st = (js.get("state") or js.get("status") or "").lower()

                if st in ("completed", "succeeded", "finished", "ready"):
                    # --- НОВЫЙ надёжный поиск ссылки на видео ---
                    url = None
                    assets = js.get("assets")

                    def _extract_urls_from_assets(a):
                        urls = []
                        if isinstance(a, str):
                            urls.append(a)
                        elif isinstance(a, dict):
                            # типичный формат: {"video": "https://..."} или {"video": {"url": "..."}}
                            for v in a.values():
                                urls.extend(_extract_urls_from_assets(v))
                        elif isinstance(a, (list, tuple)):
                            for item in a:
                                urls.extend(_extract_urls_from_assets(item))
                        return urls

                    if assets is not None:
                        for u in _extract_urls_from_assets(assets):
                            if isinstance(u, str) and u.startswith("http"):
                                url = u
                                break

                    # запасные ключи на всякий случай
                    if not url:
                        for k in ("output_url", "video_url", "url"):
                            val = js.get(k)
                            if isinstance(val, str) and val.startswith("http"):
                                url = val
                                break

                    if not url:
                        log.error("Luma: ответ без ссылки на видео: %s", js)
                        await update.effective_message.reply_text(
                            "❌ Luma: ответ пришёл без ссылки на видео."
                        )
                        return

                    # Скачиваем и отправляем файл как видео
                    try:
                        v = await client.get(url, timeout=120.0)
                        v.raise_for_status()
                        bio = BytesIO(v.content)
                        bio.name = "luma.mp4"
                        await update.effective_message.reply_video(
                            InputFile(bio),
                            caption="🎬 Luma: готово ✅",
                        )
                    except Exception:
                        # если не получилось скачать — хотя бы даём прямую ссылку
                        await update.effective_message.reply_text(
                            f"🎬 Luma: готово ✅\n{url}"
                        )
                    return

                if st in ("failed", "error", "canceled", "cancelled"):
                    log.error("Luma returned error state: %s", js)
                    await update.effective_message.reply_text("❌ Luma: ошибка рендера.")
                    return

                if time.time() - started > LUMA_MAX_WAIT_S:
                    await update.effective_message.reply_text(
                        "⌛ Luma: время ожидания вышло."
                    )
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Luma error: %s", e)
        await update.effective_message.reply_text(
            "❌ Luma: не удалось запустить/получить видео."
        )
# ───────── Runway video ─────────
def _dedupe_models(*items: str) -> list[str]:
    out: list[str] = []
    for m in items:
        m = (m or "").strip()
        if m and m not in out:
            out.append(m)
    return out

def _runway_i2v_model_candidates() -> list[str]:
    """Модели Runway для оживления фото/image→video."""
    return _dedupe_models(RUNWAY_MODEL, "gen4_turbo", "gen4.5", "gen3a_turbo", "veo3.1_fast", "veo3.1", "veo3")

def _runway_direct_text_model_candidates() -> list[str]:
    """
    Модели для official/direct Runway text→video.
    gen4_turbo/gen3a_turbo требуют картинку, поэтому для text→video их не используем.
    """
    text_capable = {"gen4.5", "veo3", "veo3.1", "veo3.1_fast"}
    env_model = (RUNWAY_MODEL or "").strip()
    first = env_model if env_model in text_capable else ""
    return _dedupe_models(first, "gen4.5", "veo3.1_fast", "veo3.1", "veo3")

def _runway_comet_text_model_candidates() -> list[str]:
    """
    Модели для Runway через Comet text→video.
    В вашем Comet-аккаунте gen4.5 сейчас отвечает model_not_found/no available channel,
    а gen4_turbo/gen3a_turbo дают prompt_image_empty, потому что они image→video.
    Поэтому Comet text→video пробуем через модели/алиасы, которые Comet обычно прокидывает
    как видео-gateway: gen4_aleph/veo*.
    """
    env_model = (RUNWAY_MODEL or "").strip()
    allowed = {"gen4_aleph", "veo3.1_fast", "veo3.1", "veo3", "runway-video"}
    first = env_model if env_model in allowed else ""
    return _dedupe_models(first, "gen4_aleph", "veo3.1_fast", "veo3.1", "veo3", "runway-video")

def _runway_direct_base_candidates() -> list[str]:
    """
    Direct Runway API сейчас работает через https://api.dev.runwayml.com/v1/... .
    Если в ENV остался старый base_url, всё равно добавляем официальный base как fallback.
    """
    raw = (RUNWAY_BASE_URL or "").strip().rstrip("/")
    out: list[str] = []
    for base in (raw, "https://api.dev.runwayml.com"):
        if not base:
            continue
        if base.endswith("/v1"):
            base = base[:-3].rstrip("/")
        if base and base not in out:
            out.append(base)
    return out

async def _run_runway_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration_s: int, aspect: str):
    """
    Runway text→video.

    В старой версии здесь был старый формат: POST /v1/tasks + Authorization: Token + input{...}.
    Он даёт тихий fail/400. Актуальный формат Runway: POST /v1/image_to_video без promptImage,
    поля promptText/ratio/duration, Authorization: Bearer и X-Runway-Version.

    Порядок: сначала Comet/Runway wrapper, затем direct Runway API.
    """
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)

    prompt = (prompt or "").strip()
    if not prompt:
        await update.effective_message.reply_text("❌ Runway: пустой запрос для видео.")
        return

    duration = _duration_for_engine("runway", duration_s)
    ratio = _ratio_for_aspect(aspect)
    all_errors: list[str] = []

    # 1) Runway через CometAPI — основной путь для вашего проекта.
    if RUNWAY_USE_COMET and COMET_API_KEY:
        comet_headers = {
            "Authorization": f"Bearer {COMET_API_KEY}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Runway-Version": RUNWAY_API_VERSION or "2024-11-06",
        }
        comet_payloads: list[tuple[str, dict]] = []
        for model in _runway_comet_text_model_candidates():
            # Не отправляем promptImage/prompt_image: это именно text→video.
            comet_payloads.extend([
                (RUNWAY_COMET_CREATE_PATH, {"model": model, "promptText": prompt, "duration": duration, "ratio": ratio}),
                (RUNWAY_COMET_CREATE_PATH, {"model": model, "prompt_text": prompt, "duration": duration, "ratio": ratio}),
                (RUNWAY_COMET_CREATE_PATH, {"model": model, "prompt": prompt, "duration": duration, "ratio": ratio}),
            ])

        async with httpx.AsyncClient(timeout=90.0) as client:
            for path, payload in comet_payloads:
                try:
                    r = await client.post(f"{COMET_BASE_URL}{path}", headers=comet_headers, json=payload)
                    if r.status_code >= 400:
                        err = f"Comet POST {path} → {r.status_code}: {_api_error_preview(r)}"
                        all_errors.append(err)
                        log.warning("Runway text→video Comet failed: %s", err)
                        continue

                    try:
                        js = r.json() or {}
                    except Exception:
                        js = {}

                    ready_url = (
                        _extract_first_url(js.get("output"))
                        or _extract_first_url(js.get("outputs"))
                        or _extract_first_url(js.get("assets"))
                        or _extract_first_url(js.get("data"))
                        or _extract_first_url(js.get("result"))
                        or _extract_first_url(js)
                    )
                    if ready_url:
                        await _reply_video_from_url(update, client, ready_url, "Runway text→video ✅")
                        return

                    task_id = str(
                        js.get("id")
                        or js.get("task_id")
                        or js.get("generation_id")
                        or js.get("video_id")
                        or ((js.get("data") or {}).get("id") if isinstance(js.get("data"), dict) else "")
                        or ((js.get("result") or {}).get("id") if isinstance(js.get("result"), dict) else "")
                        or ""
                    ).strip()
                    if not task_id:
                        all_errors.append(f"Comet POST {path}: нет id задачи в ответе {json.dumps(js, ensure_ascii=False)[:700]}")
                        continue

                    await update.effective_message.reply_text("⏳ Runway/Comet text→video: задача принята, ожидаю результат…")
                    ok = await _poll_video_task_generic(
                        update, client, comet_headers, COMET_BASE_URL,
                        [RUNWAY_COMET_STATUS_PATH, "/runwayml/v1/tasks/{id}", "/v1/tasks/{id}", "/v1/videos/{id}"],
                        task_id, "Runway/Comet text→video", RUNWAY_MAX_WAIT_S,
                    )
                    return
                except Exception as e:
                    err = f"Comet POST {path}: {e}"
                    all_errors.append(err)
                    log.warning("Runway text→video Comet exception: %s", err)
                    continue

    # 2) Direct Runway API — запасной путь.
    if RUNWAY_API_KEY:
        direct_headers = {
            "Authorization": f"Bearer {RUNWAY_API_KEY}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Runway-Version": RUNWAY_API_VERSION or "2024-11-06",
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            for base in _runway_direct_base_candidates():
                for model in _runway_direct_text_model_candidates():
                    payload = {
                        "model": model,
                        "promptText": prompt,
                        "ratio": ratio,
                        "duration": duration,
                    }
                    try:
                        r = await client.post(f"{base}/v1/image_to_video", headers=direct_headers, json=payload)
                        if r.status_code == 401:
                            all_errors.append("Direct Runway → 401: RUNWAY_API_KEY отклонён. Проверьте ключ в Render ENV.")
                            continue
                        if r.status_code >= 400:
                            err = f"Direct Runway POST {base}/v1/image_to_video → {r.status_code}: {_api_error_preview(r)}"
                            all_errors.append(err)
                            log.warning("Runway direct text→video failed: %s", err)
                            continue

                        try:
                            js = r.json() or {}
                        except Exception:
                            js = {}

                        ready_url = _extract_first_url(js.get("output")) or _extract_first_url(js)
                        if ready_url:
                            await _reply_video_from_url(update, client, ready_url, "Runway text→video ✅")
                            return

                        task_id = str(js.get("id") or js.get("task_id") or js.get("uuid") or "").strip()
                        if not task_id:
                            all_errors.append(f"Direct Runway: нет id задачи в ответе {json.dumps(js, ensure_ascii=False)[:700]}")
                            continue

                        await update.effective_message.reply_text("⏳ Runway text→video: задача принята, ожидаю результат…")
                        await _poll_video_task_generic(
                            update, client, direct_headers, base,
                            ["/v1/tasks/{id}", RUNWAY_STATUS_PATH],
                            task_id, "Runway text→video", RUNWAY_MAX_WAIT_S,
                        )
                        return
                    except Exception as e:
                        err = f"Direct Runway POST {base}/v1/image_to_video: {e}"
                        all_errors.append(err)
                        log.warning("Runway direct text→video exception: %s", err)
                        continue

    if not RUNWAY_API_KEY and not COMET_API_KEY:
        await update.effective_message.reply_text(
            "❌ Runway: нет RUNWAY_API_KEY и COMET_API_KEY в Render ENV. "
            "Для Runway нужен хотя бы один из этих ключей."
        )
        return

    # Показываем только последние 3 ошибки, иначе Telegram получает огромную простыню.
    details = "\n".join(all_errors[-3:]) or "API не вернул подробности."
    hint = "\n\nПодсказка: если Comet пишет no available channel/model_not_found по Runway, добавьте официальный RUNWAY_API_KEY или используйте Kling/Sora для text→video."
    await update.effective_message.reply_text(f"❌ Runway: не удалось запустить/получить видео.\n{details[:1300]}{hint}")
        
# ───────── Image→Video helpers ─────────
def _api_error_preview(resp, limit: int = 900) -> str:
    try:
        body = json.dumps(resp.json(), ensure_ascii=False)
    except Exception:
        body = getattr(resp, "text", "") or ""
    body = re.sub(r"\s+", " ", body).strip()
    return body[:limit] if body else "без тела ответа"


def _sora_people_moderation_text() -> str:
    return (
        "⚠️ Sora 2 заблокировала это изображение на модерации, потому что на фото есть человек/люди.\n\n"
        "Это ограничение Sora/Comet, а не ошибка деплоя и не ошибка ключа.\n\n"
        "Для оживления фото с людьми используйте:\n"
        "• ✨ Оживить (Runway)\n"
        "• ✨ Оживить (Kling)\n\n"
        "Sora 2 оставлена для изображений без людей: предметы, животные, здания, пейзажи, интерьер."
    )


def is_sora_people_moderation_error(err: object) -> bool:
    try:
        text = json.dumps(err, ensure_ascii=False).lower()
    except Exception:
        text = str(err).lower()
    return (
        "people-in-user-uploads" in text
        or "blocked by our moderation system" in text
        or ("moderation system" in text and "sora" in text)
        or ("request is blocked" in text and "people" in text)
    )

def _extract_first_url(obj) -> str | None:
    if isinstance(obj, str):
        if obj.startswith("http://") or obj.startswith("https://"):
            return obj
        return None
    if isinstance(obj, dict):
        preferred = ("video", "video_url", "output_url", "url", "download_url", "file", "asset_url")
        for k in preferred:
            if k in obj:
                found = _extract_first_url(obj.get(k))
                if found:
                    return found
        for v in obj.values():
            found = _extract_first_url(v)
            if found:
                return found
    if isinstance(obj, (list, tuple)):
        for item in obj:
            found = _extract_first_url(item)
            if found:
                return found
    return None

async def _reply_video_from_url(update: Update, client: httpx.AsyncClient, url: str, caption: str):
    """
    Отправляет результат именно файлом в Telegram.
    Для Kling/Sora CDN часто отдаёт длинные подписанные ссылки. Поэтому сначала скачиваем MP4
    в память и отправляем InputFile; ссылку показываем только самым последним fallback.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GPT5ProBot/1.0)",
        "Accept": "video/mp4,video/*,*/*;q=0.8",
    }

    downloaded: bytes | None = None

    # 1) Скачиваем файл сами: так не показываем пользователю огромную CDN-ссылку.
    try:
        r = await client.get(url, headers=headers, timeout=240.0, follow_redirects=True)
        r.raise_for_status()
        content_type = (r.headers.get("content-type") or "").lower()
        if not r.content or len(r.content) < 512:
            raise RuntimeError(f"empty video response: {len(r.content)} bytes")
        if "text/html" in content_type or "application/json" in content_type:
            raise RuntimeError(f"not a video response: {content_type}; {r.text[:300]}")
        downloaded = r.content
    except Exception as e:
        log.warning("reply_video_from_url: local download failed: %s", e)

    # 2) Если скачали — пробуем отправить как video, затем как document.
    if downloaded:
        try:
            bio = BytesIO(downloaded)
            bio.name = "result.mp4"
            await update.effective_message.reply_video(
                video=InputFile(bio),
                caption=caption,
                supports_streaming=True,
            )
            return
        except Exception as e:
            log.warning("reply_video_from_url: InputFile video send failed: %s", e)

        try:
            bio = BytesIO(downloaded)
            bio.name = "result.mp4"
            await update.effective_message.reply_document(
                document=InputFile(bio),
                caption=caption,
            )
            return
        except Exception as e:
            log.warning("reply_video_from_url: InputFile document send failed: %s", e)

    # 3) Иногда Telegram сам умеет забрать публичный https URL.
    try:
        await update.effective_message.reply_video(
            video=url,
            caption=caption,
            supports_streaming=True,
        )
        return
    except Exception as e:
        log.warning("reply_video_from_url: telegram URL send failed: %s", e)

    try:
        await update.effective_message.reply_document(document=url, caption=caption)
        return
    except Exception as e:
        log.warning("reply_video_from_url: telegram document URL send failed: %s", e)

    safe_url = (url or "")[:3500]
    await update.effective_message.reply_text(
        f"{caption}\n⚠️ Telegram не принял видеофайл напрямую, оставляю ссылку:\n{safe_url}",
        disable_web_page_preview=False,
    )

async def _reply_video_bytes(update: Update, content: bytes, caption: str):
    if not content or len(content) < 512:
        raise RuntimeError(f"empty video bytes: {len(content or b'')} bytes")
    bio = BytesIO(content)
    bio.name = "result.mp4"
    await update.effective_message.reply_video(
        video=InputFile(bio),
        caption=caption,
        supports_streaming=True,
    )

def _ratio_for_aspect(aspect: str) -> str:
    """
    Для Runway API version 2024-11-06 ratio должен быть разрешением,
    а не строкой 9:16 / 16:9.
    """
    mapping = {
        "9:16": "768:1280",
        "16:9": "1280:768",
        "1:1": "960:960",
        "4:5": "768:960",
        "3:4": "768:1024",
        "4:3": "1024:768",
    }
    return mapping.get((aspect or "").strip(), "768:1280")

def _duration_for_engine(engine: str, duration_s: int) -> int:
    try:
        d = int(duration_s or 5)
    except Exception:
        d = 5
    engine = (engine or "").lower()
    if engine in ("runway", "kling"):
        return 10 if d >= 7 else 5
    if engine == "sora":
        # Sora/Comet стабильнее принимает seconds = 4/8/12.
        # 10 секунд из UI нормализуем в ближайший поддерживаемый вариант — 8,
        # длинные запросы — 12.
        if d <= 5:
            return 4
        if d <= 10:
            return 8
        return 12
    if engine == "luma":
        return 9 if d >= 7 else 5
    return max(5, min(15, d))

def _guess_aspect_from_image(img_bytes: bytes, fallback: str = "9:16") -> str:
    if Image is None:
        return fallback
    try:
        im = Image.open(BytesIO(img_bytes))
        w, h = im.size
        if h > w * 1.2:
            return "9:16"
        if w > h * 1.2:
            return "16:9"
        return "1:1"
    except Exception:
        return fallback

def _image_refs_for_i2v(update: Update, img_bytes: bytes) -> tuple[str, str]:
    """
    Возвращаем сначала data_url, потом Telegram URL.
    Для Comet / Runway / Kling безопаснее первым пробовать base64 data-url,
    потому что внешние API часто не могут корректно забрать Telegram file_path.
    """
    data_url = (
        f"data:{sniff_image_mime(img_bytes)};base64,"
        f"{base64.b64encode(img_bytes).decode('ascii')}"
    )

    tg_url = ""
    try:
        tg_url = _get_cached_photo_url(update.effective_user.id)
    except Exception:
        tg_url = ""

    return data_url, tg_url

def _sora_size_for_aspect(aspect: str) -> tuple[str, int, int]:
    # Sora Videos API принимает не 9:16/16:9, а size.
    # Для стандартного sora-2 стабильные размеры: 720x1280 или 1280x720.
    a = (aspect or "").strip()
    if a == "16:9":
        return "1280x720", 1280, 720
    return "720x1280", 720, 1280

def _prepare_sora_reference_image(img_bytes: bytes, aspect: str) -> tuple[bytes, str, str, str]:
    """
    Готовит изображение для Sora image→video.
    Важно: официальный Videos API требует, чтобы reference image совпадал
    с целевым размером video size. Поэтому делаем center-crop + resize.
    Возвращает: (bytes, mime, data_url, size).
    """
    size, tw, th = _sora_size_for_aspect(aspect)

    if Image is None:
        mime = sniff_image_mime(img_bytes)
        data_url = f"data:{mime};base64,{base64.b64encode(img_bytes).decode('ascii')}"
        return img_bytes, mime, data_url, size

    try:
        im = Image.open(BytesIO(img_bytes))
        try:
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass
        im = im.convert("RGB")
        w, h = im.size
        target_ratio = tw / th
        cur_ratio = w / max(1, h)

        if cur_ratio > target_ratio:
            # Слишком широкое — режем края.
            new_w = int(h * target_ratio)
            left = max(0, (w - new_w) // 2)
            im = im.crop((left, 0, left + new_w, h))
        elif cur_ratio < target_ratio:
            # Слишком высокое — режем верх/низ.
            new_h = int(w / target_ratio)
            top = max(0, (h - new_h) // 2)
            im = im.crop((0, top, w, top + new_h))

        resample = getattr(Image, "Resampling", Image).LANCZOS
        im = im.resize((tw, th), resample)
        out = BytesIO()
        im.save(out, format="JPEG", quality=92, optimize=True)
        prepared = out.getvalue()
        mime = "image/jpeg"
        data_url = f"data:{mime};base64,{base64.b64encode(prepared).decode('ascii')}"
        return prepared, mime, data_url, size
    except Exception as e:
        log.warning("Sora image prepare failed, using original bytes: %s", e)
        mime = sniff_image_mime(img_bytes)
        data_url = f"data:{mime};base64,{base64.b64encode(img_bytes).decode('ascii')}"
        return img_bytes, mime, data_url, size

async def _start_photo_revival(update: Update, context: ContextTypes.DEFAULT_TYPE, engine: str, img_bytes: bytes, prompt: str = ""):
    engine = (engine or "runway").lower().strip()
    if engine == "luma" and LUMA_TEMP_DISABLED:
        await update.effective_message.reply_text("⚠️ Luma временно отключена и скрыта из меню. Используйте Runway, Kling или Sora 2 без людей.")
        return
    prompt = (prompt or "subtle lifelike animation, natural micro-movements, smooth cinematic camera motion").strip()
    dur, asp = parse_video_opts(prompt)
    if not re.search(r"(?:9:16|16:9|1:1|4:5|3:4|4:3)", prompt or "", re.I):
        asp = _guess_aspect_from_image(img_bytes, asp)
    dur = _duration_for_engine(engine, dur)

    if engine == "runway":
        pay_engine = "runway"
        est = max(1.0, RUNWAY_UNIT_COST_USD * (dur / max(1, RUNWAY_DURATION_S)))
    else:
        pay_engine = "luma"
        est = 0.40

    _remember_last_creative(context, engine=engine, prompt=prompt, duration=dur, aspect=asp, images=[img_bytes], intent="animate_photo", kind="video")

    async def _go():
        await update.effective_message.reply_text(
            f"✅ Запускаю оживление фото: {engine.upper()} • {dur} сек • {asp}."
        )
        if engine == "runway":
            await _run_runway_animate_photo(update, context, img_bytes, prompt=prompt, duration_s=dur, aspect=asp)
        elif engine == "luma":
            await _run_luma_animate_photo(update, context, img_bytes, prompt=prompt, duration_s=dur, aspect=asp)
        elif engine in ("sora", "kling"):
            await _run_comet_i2v(update, context, engine, img_bytes, prompt=prompt, duration_s=dur, aspect=asp)
        else:
            await update.effective_message.reply_text("❌ Неизвестный движок оживления фото.")

    await _try_pay_then_do(
        update, context, update.effective_user.id, pay_engine, est, _go,
        remember_kind=f"revive_photo_{engine}",
        remember_payload={"engine": engine, "duration": dur, "aspect": asp, "prompt": prompt},
    )

async def _poll_video_task_generic(update: Update, client: httpx.AsyncClient, headers: dict, base_url: str, status_paths: list[str], task_id: str, caption: str, max_wait_s: int = 1200) -> bool:
    started = time.time()
    while True:
        last_body = ""
        for path in status_paths:
            url = f"{base_url}{path}".format(id=task_id)
            try:
                rs = await client.get(url, headers=headers, timeout=60.0)
                if rs.status_code >= 400:
                    last_body = f"{rs.status_code}: {_api_error_preview(rs)}"
                    continue
                js = rs.json() or {}
            except Exception as e:
                last_body = str(e)
                continue

            st = str(js.get("status") or js.get("state") or js.get("task_status") or "").lower()
            url = _extract_first_url(js.get("output")) or _extract_first_url(js.get("assets")) or _extract_first_url(js)
            if st in ("completed", "succeeded", "success", "finished", "ready", "done") or (url and not st):
                if not url:
                    # OpenAI/Sora Videos API часто возвращает completed без URL.
                    # Финальный MP4 надо забрать отдельным GET /v1/videos/{id}/content.
                    if "sora" in (caption or "").lower() or "/v1/videos" in " ".join(status_paths):
                        try:
                            content_url = f"{base_url.rstrip('/')}/v1/videos/{task_id}/content"
                            cr = await client.get(content_url, headers=headers, timeout=240.0, follow_redirects=True)
                            if cr.status_code < 400 and cr.content and "application/json" not in (cr.headers.get("content-type") or "").lower():
                                await _reply_video_bytes(update, cr.content, f"{caption} ✅")
                                return True
                            log.warning("%s content download failed: %s %s", caption, cr.status_code, _api_error_preview(cr))
                        except Exception as e:
                            log.warning("%s content download exception: %s", caption, e)
                    await update.effective_message.reply_text(f"⚠️ {caption}: задача готова, но ссылка/MP4 на видео не найдены.")
                    return True
                await _reply_video_from_url(update, client, url, f"{caption} ✅")
                return True
            if st in ("failed", "error", "canceled", "cancelled", "rejected"):
                if "sora" in (caption or "").lower() and is_sora_people_moderation_error(js):
                    await update.effective_message.reply_text(_sora_people_moderation_text())
                    return True
                await update.effective_message.reply_text(f"❌ {caption}: ошибка рендера.\n{json.dumps(js, ensure_ascii=False)[:900]}")
                return True

        if time.time() - started > max_wait_s:
            await update.effective_message.reply_text(f"⌛ {caption}: время ожидания вышло. Последний ответ: {last_body[:700]}")
            return True
        await asyncio.sleep(VIDEO_POLL_DELAY_S)

async def _create_and_poll_i2v(update: Update, base_url: str, api_key: str, create_payloads: list[tuple[str, dict]], status_paths: list[str], caption: str, quiet_errors: bool = False) -> bool:
    if not api_key:
        if not quiet_errors:
            await update.effective_message.reply_text(f"❌ {caption}: API-ключ не задан в ENV.")
        return False

    auth_headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    last_err = ""
    all_errors: list[str] = []

    async with httpx.AsyncClient(timeout=90.0) as client:
        for path, payload in create_payloads:
            try:
                headers = dict(auth_headers)

                # Runway через Comet требует версию API.
                if str(path).startswith("/runwayml/"):
                    headers["X-Runway-Version"] = RUNWAY_API_VERSION or "2024-11-06"

                # Спец-режим для Sora/OpenAI Videos API: input_reference как файл
                # должен уходить multipart/form-data, а не JSON. В этом режиме
                # Content-Type не ставим вручную — httpx сам добавит boundary.
                if isinstance(payload, dict) and payload.get("__multipart"):
                    mp = payload.get("__multipart") or {}
                    data = mp.get("data") or {}
                    files = mp.get("files") or {}
                    r = await client.post(f"{base_url}{path}", headers=headers, data=data, files=files)
                else:
                    headers["Content-Type"] = "application/json"
                    r = await client.post(f"{base_url}{path}", headers=headers, json=payload)

                if r.status_code >= 400:
                    mode = "multipart" if isinstance(payload, dict) and payload.get("__multipart") else "json"
                    last_err = f"POST {path} [{mode}] → {r.status_code}: {_api_error_preview(r)}"
                    all_errors.append(last_err)
                    log.warning("%s create failed: %s", caption, last_err)
                    continue

                try:
                    js = r.json() or {}
                except Exception:
                    js = {}

                ready_url = (
                    _extract_first_url(js.get("output"))
                    or _extract_first_url(js.get("outputs"))
                    or _extract_first_url(js.get("assets"))
                    or _extract_first_url(js.get("data"))
                    or _extract_first_url(js.get("result"))
                    or _extract_first_url(js.get("response"))
                    or _extract_first_url(js.get("payload"))
                    or _extract_first_url(js)
                )

                if ready_url:
                    await _reply_video_from_url(update, client, ready_url, f"{caption} ✅")
                    return True

                task_id = str(
                    js.get("id")
                    or js.get("task_id")
                    or js.get("generation_id")
                    or js.get("video_id")
                    or ""
                ).strip()

                if not task_id and isinstance(js.get("data"), dict):
                    d = js.get("data") or {}
                    task_id = str(
                        d.get("id")
                        or d.get("task_id")
                        or d.get("generation_id")
                        or d.get("video_id")
                        or ""
                    ).strip()

                if not task_id and isinstance(js.get("result"), dict):
                    d = js.get("result") or {}
                    task_id = str(
                        d.get("id")
                        or d.get("task_id")
                        or d.get("generation_id")
                        or d.get("video_id")
                        or ""
                    ).strip()

                if not task_id:
                    last_err = f"POST {path}: нет id задачи в ответе {json.dumps(js, ensure_ascii=False)[:700]}"
                    all_errors.append(last_err)
                    continue

                await update.effective_message.reply_text(f"⏳ {caption}: задача принята, ожидаю результат…")

                return await _poll_video_task_generic(
                    update,
                    client,
                    headers,
                    base_url,
                    status_paths,
                    task_id,
                    caption,
                    max_wait_s=max(LUMA_MAX_WAIT_S, RUNWAY_MAX_WAIT_S),
                )

            except Exception as e:
                last_err = f"POST {path}: {e}"
                all_errors.append(last_err)
                log.warning("%s create exception: %s", caption, e)
                continue

    if all_errors:
        # Показываем последние попытки, чтобы было понятно, какой именно формат отклонил API.
        details = "\n".join(all_errors[-5:])
    else:
        details = last_err
    if "sora" in (caption or "").lower() and is_sora_people_moderation_error(details):
        await update.effective_message.reply_text(_sora_people_moderation_text())
        return False
    if quiet_errors:
        log.warning("%s failed quietly: %s", caption, details[:1500])
        return False
    await update.effective_message.reply_text(f"❌ {caption}: не удалось создать задачу.\n{details[:1500]}")
    return False

async def _run_luma_animate_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes, prompt: str, duration_s: int, aspect: str):
    if not LUMA_API_KEY:
        await update.effective_message.reply_text("❌ Luma: LUMA_API_KEY не задан в ENV.")
        return
    data_url, tg_url = _image_refs_for_i2v(update, img_bytes)
    image_ref = data_url or tg_url
    duration_s = _duration_for_engine("luma", duration_s)
    async with httpx.AsyncClient(timeout=60.0) as client:
        base = await _pick_luma_base(client)
    payloads = [
        (LUMA_CREATE_PATH, {
            "model": LUMA_MODEL,
            "prompt": prompt,
            "duration": f"{duration_s}s",
            "aspect_ratio": aspect,
            "keyframes": {"frame0": {"type": "image", "url": image_ref}},
        }),
        (LUMA_CREATE_PATH, {
            "model": LUMA_MODEL,
            "prompt": prompt,
            "duration": f"{duration_s}s",
            "aspect_ratio": aspect,
            "image_ref": image_ref,
        }),
    ]
    await _create_and_poll_i2v(update, base, LUMA_API_KEY, payloads, [LUMA_STATUS_PATH], "Luma image→video")

async def _run_comet_i2v(update: Update, context: ContextTypes.DEFAULT_TYPE, engine: str, img_bytes: bytes, prompt: str, duration_s: int, aspect: str):
    engine = (engine or "").lower()

    data_url, tg_url = _image_refs_for_i2v(update, img_bytes)
    raw_b64 = base64.b64encode(img_bytes).decode("ascii")

    if engine == "sora":
        d = _duration_for_engine("sora", duration_s)

        # По факту ваших тестов Comet/OpenAI /v1/videos НЕ принимает:
        #   - top-level image_url / image_urls
        #   - input_image
        #   - duration
        #   - aspect_ratio
        # А input_reference должен быть объектом или файлом multipart.
        # Поэтому оставляем только официальные варианты:
        #   JSON:      input_reference={"image_url": "data:image/jpeg;base64,..."}
        #   multipart: input_reference=@reference.jpg
        sora_bytes, sora_mime, sora_data_url, size = _prepare_sora_reference_image(img_bytes, aspect)

        payloads = []

        def _add_json(payload: dict):
            for bad in ("input_image", "duration", "aspect_ratio", "image_url", "image_urls"):
                payload.pop(bad, None)
            payloads.append((SORA_CREATE_PATH, payload))

        def _add_multipart(seconds_value: str | None = None):
            data = {
                "model": SORA_MODEL,
                "prompt": prompt,
                "size": size,
            }
            if seconds_value:
                data["seconds"] = seconds_value
            files = {
                "input_reference": ("reference.jpg", sora_bytes, sora_mime or "image/jpeg"),
            }
            payloads.append((SORA_CREATE_PATH, {"__multipart": {"data": data, "files": files}}))

        # 1) Главный вариант по OpenAI Videos API JSON: input_reference — объект.
        # Data URL уже приведён к нужному size, что критично для Sora.
        _add_json({
            "model": SORA_MODEL,
            "prompt": prompt,
            "input_reference": {"image_url": sora_data_url},
            "seconds": str(d),
            "size": size,
        })

        # 2) Тот же JSON без seconds — если конкретный Comet-канал сам нормализует длительность.
        _add_json({
            "model": SORA_MODEL,
            "prompt": prompt,
            "input_reference": {"image_url": sora_data_url},
            "size": size,
        })

        # 3) Официальный multipart-вариант: input_reference как файл.
        _add_multipart(str(d))
        _add_multipart(None)

        await _create_and_poll_i2v(
            update,
            COMET_BASE_URL,
            SORA_API_KEY,
            payloads,
            [SORA_STATUS_PATH, "/v1/videos/{id}", "/v1/tasks/{id}"],
            "Sora 2 image→video (без людей)",
        )
        return

    if engine == "kling":
        # Kling через Comet ждёт чистый base64 без data:image/...;base64,
        # и duration строкой.
        d = str(_duration_for_engine("kling", duration_s))

        payloads = [
            (
                KLING_CREATE_PATH,
                {
                    "model": KLING_MODEL,
                    "prompt": prompt,
                    "image": raw_b64,
                    "duration": d,
                    "aspect_ratio": aspect,
                },
            ),
            (
                "/kling/v1/videos/image2video",
                {
                    "model": KLING_MODEL,
                    "prompt": prompt,
                    "image": raw_b64,
                    "duration": d,
                    "aspect_ratio": aspect,
                },
            ),
        ]

        await _create_and_poll_i2v(
            update,
            COMET_BASE_URL,
            KLING_API_KEY,
            payloads,
            ["/kling/v1/videos/image2video/{id}", KLING_STATUS_PATH, "/kling/v1/videos/{id}", "/v1/tasks/{id}", "/v1/videos/{id}"],
            "Kling image→video",
        )
        return

    await update.effective_message.reply_text("❌ Неизвестный Comet image→video движок.")


async def _run_comet_text_video(update: Update, context: ContextTypes.DEFAULT_TYPE, engine: str, prompt: str, duration_s: int, aspect: str):
    """Text→Video через CometAPI для Sora 2 и Kling. Luma здесь намеренно не используется."""
    engine = (engine or "").lower().strip()
    prompt = (prompt or "").strip()
    if not prompt:
        await update.effective_message.reply_text("❌ Пустой запрос для видео.")
        return

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)

    if engine == "sora":
        api_key = SORA_API_KEY
        d = _duration_for_engine("sora", duration_s)
        size, _, _ = _sora_size_for_aspect(aspect)
        payloads = [
            (SORA_CREATE_PATH, {"model": SORA_MODEL, "prompt": prompt, "seconds": str(d), "size": size}),
            (SORA_CREATE_PATH, {"model": SORA_MODEL, "prompt": prompt, "seconds": d, "size": size}),
            (SORA_CREATE_PATH, {"model": SORA_MODEL, "prompt": prompt, "size": size}),
        ]
        await _create_and_poll_i2v(
            update,
            COMET_BASE_URL,
            api_key,
            payloads,
            [SORA_STATUS_PATH, "/v1/videos/{id}", "/v1/tasks/{id}"],
            "Sora 2 text→video",
        )
        return

    if engine == "kling":
        api_key = KLING_API_KEY
        d = str(_duration_for_engine("kling", duration_s))
        payloads = [
            (KLING_TEXT_CREATE_PATH, {"model": KLING_MODEL, "prompt": prompt, "duration": d, "aspect_ratio": aspect}),
            ("/kling/v1/videos/text2video", {"model": KLING_MODEL, "prompt": prompt, "duration": d, "aspect_ratio": aspect}),
            (KLING_TEXT_CREATE_PATH, {"prompt": prompt, "duration": d, "aspect_ratio": aspect}),
        ]
        await _create_and_poll_i2v(
            update,
            COMET_BASE_URL,
            api_key,
            payloads,
            [KLING_TEXT_STATUS_PATH, "/kling/v1/videos/text2video/{id}", "/kling/v1/videos/{id}", "/v1/tasks/{id}", "/v1/videos/{id}"],
            "Kling text→video",
        )
        return

    await update.effective_message.reply_text("❌ Неизвестный text→video движок. Доступны Sora 2 и Kling. Runway — только для оживления фото.")

async def _run_runway_comet_animate_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes, prompt: str, duration_s: int, aspect: str) -> bool:
    if not (RUNWAY_USE_COMET and COMET_API_KEY):
        return False

    data_url, tg_url = _image_refs_for_i2v(update, img_bytes)

    duration = _duration_for_engine("runway", duration_s)
    ratio = _ratio_for_aspect(aspect)

    payloads = []
    # Для image→video на Comet не используем gen4.5 первым: у вас он часто отвечает no available channel.
    # gen4_turbo/gen3a_turbo — нормальные кандидаты для оживления фото.
    for model in _runway_i2v_model_candidates():
        payloads.append((RUNWAY_COMET_CREATE_PATH, {
            "model": model,
            "promptImage": data_url,
            "promptText": prompt,
            "duration": duration,
            "ratio": ratio,
        }))
        # snake_case fallback для совместимости с разными прокси.
        payloads.append((RUNWAY_COMET_CREATE_PATH, {
            "model": model,
            "prompt_image": data_url,
            "prompt_text": prompt,
            "duration": duration,
            "ratio": ratio,
        }))

    # Запасной вариант через Telegram URL, если Comet не примет data-uri.
    if tg_url and tg_url.startswith("https://"):
        for model in _runway_i2v_model_candidates():
            payloads.append((RUNWAY_COMET_CREATE_PATH, {
                "model": model,
                "promptImage": tg_url,
                "promptText": prompt,
                "duration": duration,
                "ratio": ratio,
            }))

    return await _create_and_poll_i2v(
        update,
        COMET_BASE_URL,
        COMET_API_KEY,
        payloads,
        [RUNWAY_COMET_STATUS_PATH, "/v1/tasks/{id}", "/runwayml/v1/tasks/{id}"],
        "Runway/Comet image→video",
    )

# ───────── Runway: анимация загруженного фото (image→video) ─────────
async def _run_runway_animate_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes, prompt: str, duration_s: int, aspect: str):
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)
    prompt = (prompt or "animate the input photo with subtle camera motion, lifelike micro-movements").strip()
    seconds = _duration_for_engine("runway", duration_s)
    ratio = _ratio_for_aspect(aspect)

    # Предпочтительный путь: Runway через CometAPI, если COMET_API_KEY есть.
    try:
        if await _run_runway_comet_animate_photo(update, context, img_bytes, prompt, seconds, aspect):
            return
    except Exception as e:
        log.warning("Runway Comet fallback to direct because of error: %s", e)

    if not RUNWAY_API_KEY:
        await update.effective_message.reply_text(
            "❌ Runway: нет RUNWAY_API_KEY и/или COMET_API_KEY. "
            "Добавьте ключ в Render ENV."
        )
        return

    try:
        data_url, tg_url = _image_refs_for_i2v(update, img_bytes)
        image_ref = data_url or tg_url
        headers = {
            "Authorization": f"Bearer {RUNWAY_API_KEY}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if RUNWAY_API_VERSION:
            headers["X-Runway-Version"] = RUNWAY_API_VERSION

        payload_variants = []
        for model in _runway_i2v_model_candidates():
            payload_variants.extend([
                (RUNWAY_I2V_PATH, {"model": model, "promptImage": image_ref, "promptText": prompt, "duration": seconds, "ratio": ratio}),
                (RUNWAY_I2V_PATH, {"model": model, "prompt_image": image_ref, "prompt_text": prompt, "duration": seconds, "ratio": ratio}),
            ])
        # Самый старый fallback оставлен последним, только для обратной совместимости.
        payload_variants.append((RUNWAY_CREATE_PATH, {"model": RUNWAY_MODEL, "input": {"prompt": prompt, "duration": seconds, "ratio": ratio, "init_image": image_ref}}))

        async with httpx.AsyncClient(timeout=90.0) as client:
            last_err = ""
            for path, payload in payload_variants:
                r = await client.post(f"{RUNWAY_BASE_URL}{path}", headers=headers, json=payload)
                if r.status_code == 401:
                    await update.effective_message.reply_text("⚠️ Runway: ключ отклонён (401). Проверь RUNWAY_API_KEY.")
                    return
                if r.status_code >= 400:
                    last_err = f"POST {path} → {r.status_code}: {_api_error_preview(r)}"
                    log.warning("Runway direct create failed: %s", last_err)
                    continue

                js = r.json() or {}
                ready_url = _extract_first_url(js.get("output")) or _extract_first_url(js.get("assets")) or _extract_first_url(js)
                if ready_url:
                    await _reply_video_from_url(update, client, ready_url, "✨ Оживил фото (Runway) ✅")
                    return

                rid = str(js.get("id") or js.get("task_id") or js.get("generation_id") or "").strip()
                if not rid:
                    last_err = f"Runway не вернул id задачи: {json.dumps(js, ensure_ascii=False)[:700]}"
                    continue

                await update.effective_message.reply_text("⏳ Оживляю фото в Runway… Сообщу, когда будет готово.")
                status_paths = [RUNWAY_STATUS_PATH, "/v1/tasks/{id}", "/v1/image_to_video/{id}"]
                await _poll_video_task_generic(update, client, headers, RUNWAY_BASE_URL, status_paths, rid, "Runway image→video", RUNWAY_MAX_WAIT_S)
                return

            await update.effective_message.reply_text(f"❌ Runway: не удалось создать задачу.\n{last_err[:900]}")

    except Exception as e:
        log.exception("Runway revive error: %s", e)
        await update.effective_message.reply_text(f"❌ Не удалось анимировать фото в Runway: {e}")

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
    try:
        ok, offer = _can_spend_or_offer(user_id, username, engine, est_cost_usd)
    except Exception as e:
        log.exception("limit/wallet check failed: %s", e)
        await update.effective_message.reply_text(f"❌ Ошибка проверки лимитов/баланса: {e}")
        return
    if ok:
        try:
            await coro_func()
        except Exception as e:
            log.exception("paid action failed: %s", e)
            await update.effective_message.reply_text(f"❌ Задача не запустилась: {e}")
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

    # Вопрос/команда про оживление фото должны сбрасывать медицинскую ветку.
    # Иначе после кнопки «Медицина» следующее обычное фото ошибочно уходит в мед. анализ.
    if _is_photo_revival_question(text) or _is_photo_revival_intent(text):
        _set_waiting_photo_revival(update, context)
        await update.effective_message.reply_text(_photo_revival_capability_text(), reply_markup=main_kb)
        return

    # Если пользователь выбрал AI Reels Studio и пишет ТЗ текстом —
    # не выдаём просто сценарий. Сначала показываем понятную развилку: запустить видео / выбрать движок / добавить фото.
    if context.user_data.get("awaiting_reels_material"):
        context.user_data.pop("awaiting_reels_material", None)
        _mode_track_set(update.effective_user.id, "fun_reels")
        duration, aspect = parse_video_opts(text)
        if not re.search(r"(?:9:16|16:9|1:1|4:5|3:4|4:3)", text or "", re.I):
            aspect = REELS_DEFAULT_ASPECT or "9:16"
        await _handle_text_to_video_auto(update, context, text, duration=duration, aspect=aspect, intent="reels")
        return

    if context.user_data.get("awaiting_film_material"):
        context.user_data.pop("awaiting_film_material", None)
        _mode_track_set(update.effective_user.id, "fun_film")
        prompt = (
            "Ты режиссёр и промпт-инженер AI-видео. На русском подготовь мини-фильм: "
            "1) логлайн, 2) структура сцен, 3) раскадровка, 4) промпты для коротких клипов 5-10 сек "
            "через Sora/Kling, 5) монтаж/звук/титры, 6) план сборки. Runway использовать только для оживления фото. Запрос пользователя:\n" + text
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

    # Ожидания новых creative-flow режимов
    if context.user_data.get("awaiting_text_video"):
        context.user_data.pop("awaiting_text_video", None)
        duration, aspect = parse_video_opts(text)
        await _handle_text_to_video_auto(update, context, text, duration=duration, aspect=aspect, intent="text_video")
        return

    if context.user_data.get("awaiting_post_pack"):
        context.user_data.pop("awaiting_post_pack", None)
        await _handle_post_pack(update, context, text)
        return

    if context.user_data.get("awaiting_music_prompt"):
        context.user_data.pop("awaiting_music_prompt", None)
        await _handle_music_prompt(update, context, text)
        return

    if context.user_data.get("awaiting_logo_brief"):
        context.user_data.pop("awaiting_logo_brief", None)
        logo_prompt = (
            "Professional brand logo design, clean vector-like mark, premium commercial style, usable on website, Telegram avatar and business materials. "
            "Create 2-3 clear logo directions in one image, no mockup, no watermark. Brief: " + text
        )
        await update.effective_message.reply_text("🛡 Бриф логотипа принят. Генерирую варианты…")
        await _do_img_generate(update, context, logo_prompt)
        return

    # Намёк на генерацию видеоролика — теперь через Creative Router, а не ручной выбор Sora/Kling.
    mtype, rest = detect_media_intent(text)
    if mtype == "video":
        _clear_medicine_wait(context)
        with contextlib.suppress(Exception):
            _mode_track_set(update.effective_user.id, "")
        duration, aspect = parse_video_opts(text)
        prompt = rest or re.sub(
            r"(\d+\s*(?:сек|с)|(?:9:16|16:9|1:1|4:5|3:4|4:3))",
            "",
            text,
            flags=re.I,
        ).strip(" ,.")
        if not prompt:
            await update.effective_message.reply_text("Опишите, что именно снять, например: «вилла на Самуи, luxury, 9:16, 10 секунд».")
            return
        await _handle_text_to_video_auto(update, context, prompt, duration=duration, aspect=aspect, intent="text_video")
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

    reply = await ask_openai_text(text_for_llm)
    await update.effective_message.reply_text(reply)
    await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])

# ───────── Фото / Документы / Голос ─────────
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ph = update.message.photo[-1]
        f = await ph.get_file()
        data = await f.download_as_bytearray()
        img = bytes(data)
        _cache_photo(update.effective_user.id, img, getattr(f, "file_path", "") or "")

        user_id = update.effective_user.id
        caption = (update.message.caption or "").strip()

        # Creative/Reels album collector: фотоальбом + подпись обрабатываются как единый бриф.
        if await _maybe_collect_reels_album(update, context, img, caption):
            return

        # Если пользователь уже выбрал AI Reels Studio и прислал одно фото — запускаем фото→reels.
        if context.user_data.get("awaiting_reels_material") and not getattr(update.message, "media_group_id", None):
            context.user_data.pop("awaiting_reels_material", None)
            await _handle_reels_assets(update, context, [img], caption or "Сделай вертикальный AI Reels по этому фото")
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
                "Фото получено. Выберите доступный движок для оживления:",
                reply_markup=photo_quick_actions_kb(),
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

            # заменить фон: сохраняем объект/человека резким, меняем только подложку
            if any(k in tl for k in ("замени фон", "replacebg", "размытый фон", "blur", "пляжный фон", "белый фон", "фон пляж", "фон природа")):
                await _pedit_replacebg(update, context, img, preset=_bg_preset_from_text(caption)); return

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

        caption = (update.message.caption or "").strip()

        if _is_waiting_image_retouch(context) and not mt.startswith("image/"):
            await update.effective_message.reply_text(
                "🧽 Удаление водяного знака сейчас работает для изображений/скринов. "
                "Пришлите страницу документа как фото, PNG или JPG — обработаю ретушью."
            )
            return

        if mt.startswith("image/"):
            _cache_photo(update.effective_user.id, raw, getattr(tg_file, "file_path", "") or "")

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
            await update.effective_message.reply_text("Ошибка при обработке документа.")

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
        "_Гибриды:_ GPT-5 (текст/логика) + Images (иллюстрации) + Sora 2/Kling (клипы/мокапы); Runway — оживление фото.\n\n"
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
        "Здесь быстрые творческие сценарии: оживить фотографию, сделать Reels/Shorts, "
        "создать мини-фильм из нескольких сцен, придумать идеи, сценарий, игру или квиз.\n\n"
        "Выбери действие ниже или напиши свободный запрос."
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown", reply_markup=_fun_quick_kb())

# ───── Клавиатура «Развлечения» с новыми кнопками ─────
def _fun_quick_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🎭 Идеи для досуга", callback_data="fun:ideas")],
        [InlineKeyboardButton("🎬 Сценарий шорта", callback_data="fun:storyboard")],
        [InlineKeyboardButton("🎮 Игры/квиз",       callback_data="fun:quiz")],
        [
            InlineKeyboardButton("🪄 Оживить фото", callback_data="fun:revive"),
            InlineKeyboardButton("📱 Сделать Reels", callback_data="fun:reels"),
            InlineKeyboardButton("🎞 Создать фильм", callback_data="fun:film"),
        ],
        [InlineKeyboardButton("📝 Свободный запрос", callback_data="fun:free")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="fun:back")],
    ]
    return InlineKeyboardMarkup(rows)

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

    if action == "revive":
        if await _try_call("revive_old_photo_flow", "do_revive_photo"):
            return
        _set_waiting_photo_revival(update, context)
        await q.answer("Оживление фото")
        await _safe_q_edit(update, context, _fun_revive_help_text(), parse_mode="Markdown", reply_markup=_fun_quick_kb())
        return

    if action in {"smartreels", "reels"}:
        if await _try_call("smart_reels_from_video", "video_sense_reels"):
            return
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "fun_reels")
        context.user_data["awaiting_reels_material"] = True
        await q.answer("Reels / Shorts")
        await _safe_q_edit(update, context, _fun_reels_help_text(), parse_mode="Markdown", reply_markup=_fun_quick_kb())
        return

    if action == "film":
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "fun_film")
        context.user_data["awaiting_film_material"] = True
        await q.answer("Создать фильм")
        await _safe_q_edit(update, context, _fun_film_help_text(), parse_mode="Markdown", reply_markup=_fun_quick_kb())
        return

    if action == "clip":
        if await _try_call("start_runway_flow", "luma_make_clip", "runway_make_clip"):
            return
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "fun_reels")
        context.user_data["awaiting_reels_material"] = True
        await q.answer()
        await _safe_q_edit(update, context, _fun_reels_help_text(), parse_mode="Markdown", reply_markup=_fun_quick_kb())
        return

    if action == "img":
        if await _try_call("cmd_img", "midjourney_flow", "images_make"):
            return
        await q.answer()
        await _safe_q_edit(update, context, "Введи /img и тему картинки, или пришли рефы.", reply_markup=_fun_quick_kb())
        return

    if action == "storyboard":
        if await _try_call("start_storyboard", "storyboard_make"):
            return
        await q.answer()
        await _safe_q_edit(update, context, "Напиши тему шорта — накидаю структуру и раскадровку.", reply_markup=_fun_quick_kb())
        return

    if action in {"ideas", "quiz", "speech", "free", "back"}:
        await q.answer()
        await _safe_q_edit(update, context, 
            "Готов! Напиши задачу или выбери кнопку выше.",
            reply_markup=_fun_quick_kb()
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
    _set_mode_clean(update.effective_user.id, "Работа", "")
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

# ───────── Позитивный авто-ответ про возможности (текст/голос) ─────────
_CAPS_PATTERN = re.compile(
    r"(умеешь|можешь|делаешь|анализируешь|работаешь|поддерживаешь|умеет\s+ли|может\s+ли|можно\s+ли)"
    r".{0,160}"
    r"(pdf|epub|fb2|docx|txt|книг|книга|изображен|фото|фотограф|картин|ожив|анимир|"
    r"image|jpeg|png|video|видео|mp4|mov|аудио|audio|mp3|wav|"
    r"медицин|медкарт|выписк|анамнез|анализ|снимок|мрт|кт|заключени|врачебн|диагноз|узи|рентген)",
    re.I | re.S,
)

async def on_capabilities_qa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    incoming_text = (getattr(update.effective_message, "text", "") or "").strip()
    if _is_photo_revival_question(incoming_text) or _is_photo_revival_intent(incoming_text):
        _set_waiting_photo_revival(update, context)
    cap = capability_answer(incoming_text)
    if cap:
        await update.effective_message.reply_text(cap, reply_markup=main_kb)
        return

    msg = (
        "Да, умею работать с файлами, медиа и медицинскими материалами:\n"
        "• 📄 Документы: PDF/EPUB/FB2/DOCX/TXT — конспект, резюме, извлечение таблиц, проверка фактов.\n"
        "• 🖼 Изображения: анализ/описание, улучшение, фон, разметка, мемы, outpaint.\n"
        "• ✨ Оживление фото: загрузи фото — можно выбрать Runway, Sora 2 или Kling.\n"
        "• 🎞 Видео: разбор смысла, таймкоды, *Reels из длинного видео*, идеи/скрипт, субтитры.\n"
        "• 🎧 Аудио/книги: транскрипция, тезисы, план.\n"
        "• 🩺 Медицина: выписки, анамнез, заключения, анализы, снимки, МРТ/КТ — справочный разбор и вопросы врачу.\n\n"
        "_Подсказки:_ просто загрузите файл или пришлите ссылку + короткое ТЗ. "
        "Для фото — можно нажать «✨ Оживить», для видео — «🎬 Reels из длинного видео»."
    )
    await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=_fun_quick_kb())


# ───────── COMET CREATIVE ROUTER / AI REELS STUDIO v40 ─────────

_CREATIVE_ALBUMS: dict[str, dict] = {}

def _engine_enabled(name: str) -> bool:
    name = (name or "").lower().strip()
    mapping = {
        "runway": RUNWAY_ENABLED and bool(COMET_API_KEY or RUNWAY_API_KEY),
        "kling": KLING_ENABLED and bool(KLING_API_KEY),
        "kling_multi": KLING_ENABLED and bool(KLING_API_KEY),
        "sora": SORA_ENABLED and bool(SORA_API_KEY),
        "seedance": SEEDANCE_ENABLED and bool(COMET_API_KEY),
        "veo": VEO_ENABLED and bool(COMET_API_KEY),
        "hailuo": HAILUO_ENABLED and bool(COMET_API_KEY),
        "vidu": VIDU_ENABLED and bool(COMET_API_KEY),
        "grok": GROK_VIDEO_ENABLED and bool(COMET_API_KEY),
        "suno": SUNO_ENABLED and bool(COMET_API_KEY),
        "luma": LUMA_ENABLED and bool(LUMA_API_KEY),
    }
    return bool(mapping.get(name, False))

def _estimate_engine_cost(engine: str, duration_s: int = 5) -> float:
    engine = (engine or "").lower().strip()
    if engine in ("kling", "kling_multi"):
        return KLING_UNIT_COST_USD
    if engine == "runway":
        return max(0.8, RUNWAY_UNIT_COST_USD * (_duration_for_engine("runway", duration_s) / max(1, RUNWAY_DURATION_S)))
    if engine == "sora":
        return SORA_PRO_UNIT_COST_USD if "pro" in (SORA_MODEL or "").lower() else SORA_UNIT_COST_USD
    if engine == "seedance":
        return SEEDANCE_UNIT_COST_USD
    if engine == "veo":
        return VEO_UNIT_COST_USD
    if engine == "hailuo":
        return HAILUO_UNIT_COST_USD
    if engine == "vidu":
        return VIDU_UNIT_COST_USD
    if engine == "grok":
        return GROK_VIDEO_UNIT_COST_USD
    if engine == "suno":
        return SUNO_UNIT_COST_USD
    return 0.25

def _choose_creative_engine(intent: str, assets: dict | None = None, brief: str = "") -> str:
    """Auto Router v42: стабильные Kling/Runway первыми, экспериментальные каналы Comet — после них."""
    assets = assets or {}
    brief_l = (brief or "").lower()
    n_images = int(assets.get("images", 0) or 0)

    if intent in ("text_video", "reels") and _engine_enabled("veo") and re.search(r"\b(cinematic|cinema|luxury|премиум|кино|кинематограф|реклама|commercial)\b", brief_l, re.I):
        return "veo"

    if intent in ("reels", "multi_photo_reels") and n_images >= 2:
        if _engine_enabled("kling_multi"):
            return "kling_multi"
        if _engine_enabled("runway"):
            return "runway"
        if _engine_enabled("seedance"):
            return "seedance"
        if _engine_enabled("hailuo"):
            return "hailuo"

    if intent == "animate_photo" or (intent == "reels" and n_images == 1):
        if _engine_enabled("runway"):
            return "runway"
        if _engine_enabled("kling"):
            return "kling"
        if _engine_enabled("seedance"):
            return "seedance"

    if intent == "avatar":
        return "kling" if _engine_enabled("kling") else "none"

    if intent == "lip_sync":
        if _engine_enabled("kling"):
            return "kling"
        if _engine_enabled("grok"):
            return "grok"

    if intent in ("text_video", "reels"):
        # Seedance is useful for multimodal reels, but only put it first when explicitly allowed.
        # Otherwise keep Kling as the stable production default and use Seedance by manual choice/fallback.
        if SEEDANCE_AUTO_FIRST and _engine_enabled("seedance"):
            return "seedance"
        if _engine_enabled("kling"):
            return "kling"
        if _engine_enabled("seedance"):
            return "seedance"
        if _engine_enabled("hailuo"):
            return "hailuo"
        if _engine_enabled("sora"):
            return "sora"

    if _engine_enabled("kling"):
        return "kling"
    if _engine_enabled("seedance"):
        return "seedance"
    if _engine_enabled("sora"):
        return "sora"
    return "none"

def _normalize_creative_aspect(aspect: str | None = None) -> str:
    a = (aspect or REELS_DEFAULT_ASPECT or "9:16").strip()
    return a if a in ("9:16", "16:9", "1:1", "4:5", "3:4", "4:3") else "9:16"

def _after_result_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Повторить", callback_data="creative:repeat"), InlineKeyboardButton("🧠 Другой", callback_data="creative:other_engine")],
        [InlineKeyboardButton("💬 Субтитры", callback_data="creative:subtitles"), InlineKeyboardButton("🎵 Музыка", callback_data="creative:music")],
        [InlineKeyboardButton("🖼 Обложка", callback_data="creative:cover"), InlineKeyboardButton("📲 Пост", callback_data="creative:post")],
        [InlineKeyboardButton("🏠 Меню", callback_data="nav:home")],
    ])

async def _reply_video_from_url(update: Update, client: httpx.AsyncClient, url: str, caption: str):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; GPT5ProBot/1.0)", "Accept": "video/mp4,video/*,*/*;q=0.8"}
    downloaded: bytes | None = None
    try:
        r = await client.get(url, headers=headers, timeout=240.0, follow_redirects=True)
        r.raise_for_status()
        content_type = (r.headers.get("content-type") or "").lower()
        if not r.content or len(r.content) < 512:
            raise RuntimeError(f"empty video response: {len(r.content)} bytes")
        if "text/html" in content_type or "application/json" in content_type:
            raise RuntimeError(f"not a video response: {content_type}; {r.text[:300]}")
        downloaded = r.content
    except Exception as e:
        log.warning("reply_video_from_url creative: local download failed: %s", e)
    if downloaded:
        try:
            bio = BytesIO(downloaded); bio.name = "result.mp4"
            await update.effective_message.reply_video(video=InputFile(bio), caption=caption, supports_streaming=True, reply_markup=_after_result_kb())
            return
        except Exception as e:
            log.warning("reply_video_from_url creative: InputFile video send failed: %s", e)
        try:
            bio = BytesIO(downloaded); bio.name = "result.mp4"
            await update.effective_message.reply_document(document=InputFile(bio), caption=caption, reply_markup=_after_result_kb())
            return
        except Exception as e:
            log.warning("reply_video_from_url creative: InputFile document send failed: %s", e)
    try:
        await update.effective_message.reply_video(video=url, caption=caption, supports_streaming=True, reply_markup=_after_result_kb())
        return
    except Exception as e:
        log.warning("reply_video_from_url creative: telegram URL send failed: %s", e)
    safe_url = (url or "")[:3500]
    await update.effective_message.reply_text(f"{caption}\n⚠️ Telegram не принял видеофайл напрямую, оставляю ссылку:\n{safe_url}", disable_web_page_preview=False, reply_markup=_after_result_kb())

async def _reply_video_bytes(update: Update, content: bytes, caption: str):
    if not content or len(content) < 512:
        raise RuntimeError(f"empty video bytes: {len(content or b'')} bytes")
    bio = BytesIO(content); bio.name = "result.mp4"
    await update.effective_message.reply_video(video=InputFile(bio), caption=caption, supports_streaming=True, reply_markup=_after_result_kb())

async def _creative_llm_text(prompt: str, fallback: str = "") -> str:
    try:
        out = await ask_openai_text(prompt)
        return (out or fallback or "").strip()
    except Exception as e:
        log.warning("creative llm failed: %s", e)
        return fallback or ""

async def _make_reels_prompt(brief: str, n_images: int = 0) -> str:
    source = (brief or "").strip() or "вертикальный премиальный Reels по присланным материалам"
    prompt = (
        "Ты AI creative producer для коротких Reels/Shorts. Сформируй один компактный промпт для video generation engine. "
        "Нужно: вертикальный 9:16, динамика камеры, естественное движение, чистый premium social media style, без текста внутри кадра, без логотипов. "
        f"Материалы: {n_images} фото. Бриф пользователя: {source}\n"
        "Ответь только финальным промптом на английском, максимум 900 символов."
    )
    fallback = f"Vertical 9:16 premium cinematic social media reel, smooth camera movement, natural realistic motion, clean luxury style. Brief: {source}"
    out = await _creative_llm_text(prompt, fallback=fallback)
    return out[:1200]

async def _make_social_post_pack(update: Update, context: ContextTypes.DEFAULT_TYPE, brief: str):
    if not REELS_AUTO_POST:
        return
    prompt = (
        "Сделай пакет публикации на русском для Telegram/Reels по этому AI-видео. "
        "Формат: 1) заголовок, 2) короткое описание, 3) CTA, 4) 12 хештегов, 5) короткая WhatsApp-версия. "
        "Если это недвижимость/вилла — стиль Cozy Asia: премиально, понятно, без воды.\n\n"
        f"Бриф: {brief}"
    )
    text = await _creative_llm_text(prompt)
    if text:
        await update.effective_message.reply_text("📲 Готов пакет публикации:\n\n" + text[:3800], reply_markup=_after_result_kb())

async def _run_comet_model_text_video(update: Update, context: ContextTypes.DEFAULT_TYPE, engine: str, prompt: str, duration_s: int, aspect: str, quiet_errors: bool = False) -> bool:
    engine = (engine or "").lower().strip()
    if not COMET_API_KEY:
        if not quiet_errors:
            await update.effective_message.reply_text("❌ COMET_API_KEY не задан в ENV.")
        return False
    conf = {
        "seedance": (SEEDANCE_MODEL, SEEDANCE_CREATE_PATH, [SEEDANCE_STATUS_PATH, "/v1/videos/{id}"], "Seedance text→video"),
        "veo": (VEO_MODEL, VEO_CREATE_PATH, [VEO_STATUS_PATH, "/v1/videos/{id}"], "Veo text→video"),
        "hailuo": (HAILUO_MODEL, HAILUO_CREATE_PATH, [HAILUO_STATUS_PATH, "/v1/videos/{id}"], "Hailuo text→video"),
        "vidu": (VIDU_MODEL, VIDU_CREATE_PATH, [VIDU_STATUS_PATH, "/v1/videos/{id}"], "Vidu text→video"),
        "grok": (GROK_VIDEO_MODEL, GROK_VIDEO_CREATE_PATH, [GROK_VIDEO_STATUS_PATH, "/v1/videos/{id}"], "Grok Imagine text→video"),
    }.get(engine)
    if not conf:
        if not quiet_errors:
            await update.effective_message.reply_text(f"❌ Нет конфигурации для движка {engine}.")
        return False
    model, path, status_paths, caption = conf
    d = _duration_for_engine(engine, duration_s)
    a = _normalize_creative_aspect(aspect)
    size = "720x1280" if a == "9:16" else ("1280x720" if a == "16:9" else "1024x1024")
    payloads = [
        (path, {"model": model, "prompt": prompt, "seconds": str(d), "size": size, "aspect_ratio": a}),
        (path, {"model": model, "prompt": prompt, "duration": str(d), "aspect_ratio": a}),
        (path, {"model": model, "prompt": prompt, "seconds": d, "size": size}),
        (path, {"model": model, "prompt": prompt}),
    ]
    return await _create_and_poll_i2v(update, COMET_BASE_URL, COMET_API_KEY, payloads, status_paths, caption, quiet_errors=quiet_errors)

async def _run_kling_multi_i2v(update: Update, context: ContextTypes.DEFAULT_TYPE, images: list[bytes], prompt: str, duration_s: int, aspect: str) -> bool:
    images = [b for b in (images or []) if b][:REELS_MAX_PHOTOS]
    if len(images) < 2:
        return await _run_comet_i2v(update, context, "kling", images[0], prompt, duration_s, aspect)
    b64s = [base64.b64encode(b).decode("ascii") for b in images]
    d = str(_duration_for_engine("kling", duration_s))
    a = _normalize_creative_aspect(aspect)
    payloads = [
        (KLING_MULTI_CREATE_PATH, {"model": KLING_MODEL, "prompt": prompt, "images": b64s, "duration": d, "aspect_ratio": a}),
        (KLING_MULTI_CREATE_PATH, {"model": KLING_MODEL, "prompt": prompt, "image_list": b64s, "duration": d, "aspect_ratio": a}),
        (KLING_MULTI_CREATE_PATH, {"model": KLING_MODEL, "prompt": prompt, "input_images": [{"image": x} for x in b64s], "duration": d, "aspect_ratio": a}),
        ("/kling/v1/videos/multi-image2video", {"model": KLING_MODEL, "prompt": prompt, "images": b64s, "duration": d, "aspect_ratio": a}),
    ]
    return await _create_and_poll_i2v(update, COMET_BASE_URL, KLING_API_KEY, payloads, [KLING_MULTI_STATUS_PATH, "/kling/v1/videos/multi-image2video/{id}", "/kling/v1/videos/{id}", "/v1/tasks/{id}", "/v1/videos/{id}"], "Kling multi-image→Reels")

async def _run_creative_video(update: Update, context: ContextTypes.DEFAULT_TYPE, engine: str, prompt: str, duration: int, aspect: str, images: list[bytes] | None = None, intent: str = "text_video"):
    engine = (engine or "").lower().strip()
    images = images or []
    _remember_last_creative(context, engine=engine, prompt=prompt, duration=duration, aspect=aspect, images=images, intent=intent, kind="video")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)
    if images and engine == "runway":
        await _start_photo_revival(update, context, engine="runway", img_bytes=images[0], prompt=prompt)
        return
    if images and engine == "kling_multi":
        await _run_kling_multi_i2v(update, context, images, prompt, duration, aspect)
        return
    if images and engine == "kling":
        await _run_comet_i2v(update, context, "kling", images[0], prompt, duration, aspect)
        return
    if images and engine in {"seedance", "veo", "hailuo", "vidu", "grok"}:
        data_urls = [f"data:{sniff_image_mime(b)};base64,{base64.b64encode(b).decode('ascii')}" for b in images[:REELS_MAX_PHOTOS]]
        model = {"seedance": SEEDANCE_MODEL, "veo": VEO_MODEL, "hailuo": HAILUO_MODEL, "vidu": VIDU_MODEL, "grok": GROK_VIDEO_MODEL}[engine]
        path = {"seedance": SEEDANCE_CREATE_PATH, "veo": VEO_CREATE_PATH, "hailuo": HAILUO_CREATE_PATH, "vidu": VIDU_CREATE_PATH, "grok": GROK_VIDEO_CREATE_PATH}[engine]
        status = {"seedance": SEEDANCE_STATUS_PATH, "veo": VEO_STATUS_PATH, "hailuo": HAILUO_STATUS_PATH, "vidu": VIDU_STATUS_PATH, "grok": GROK_VIDEO_STATUS_PATH}[engine]
        d = _duration_for_engine(engine, duration)
        a = _normalize_creative_aspect(aspect)
        size = "720x1280" if a == "9:16" else ("1280x720" if a == "16:9" else "1024x1024")
        payloads = [
            (path, {"model": model, "prompt": prompt, "input_reference": {"image_url": data_urls[0]}, "seconds": str(d), "size": size}),
            (path, {"model": model, "prompt": prompt, "input_references": [{"image_url": u} for u in data_urls], "seconds": str(d), "size": size}),
            (path, {"model": model, "prompt": prompt, "images": data_urls, "duration": str(d), "aspect_ratio": a}),
        ]
        ok = await _create_and_poll_i2v(update, COMET_BASE_URL, COMET_API_KEY, payloads, [status, "/v1/videos/{id}", "/v1/tasks/{id}"], f"{engine.title()} image→video", quiet_errors=True)
        if ok:
            return
        if len(images) >= 2 and _engine_enabled("kling_multi"):
            await update.effective_message.reply_text(f"⚠️ {engine} сейчас недоступен в Comet. Пробую Kling multi-image…")
            await _run_kling_multi_i2v(update, context, images, prompt, duration, aspect)
            return
        if _engine_enabled("kling"):
            await update.effective_message.reply_text(f"⚠️ {engine} сейчас недоступен в Comet. Пробую Kling image→video…")
            await _run_comet_i2v(update, context, "kling", images[0], prompt, duration, aspect)
            return
        if _engine_enabled("runway"):
            await update.effective_message.reply_text(f"⚠️ {engine} сейчас недоступен в Comet. Пробую Runway…")
            await _start_photo_revival(update, context, engine="runway", img_bytes=images[0], prompt=prompt)
            return
        await update.effective_message.reply_text(f"❌ {engine} сейчас недоступен, а запасной видео-движок не включён.")
        return
    if engine == "sora":
        await _run_comet_text_video(update, context, "sora", prompt, duration, aspect)
        return
    if engine == "kling":
        await _run_comet_text_video(update, context, "kling", prompt, duration, aspect)
        return
    if engine in {"seedance", "veo", "hailuo", "vidu", "grok"}:
        ok = await _run_comet_model_text_video(update, context, engine, prompt, duration, aspect, quiet_errors=True)
        if ok:
            return
        if _engine_enabled("kling"):
            await update.effective_message.reply_text(f"⚠️ {engine} сейчас недоступен в Comet. Автоматически пробую Kling text→video.")
            await _run_comet_text_video(update, context, "kling", prompt, duration, aspect)
            return
        if _engine_enabled("sora"):
            await update.effective_message.reply_text(f"⚠️ {engine} сейчас недоступен в Comet. Пробую Sora fallback.")
            await _run_comet_text_video(update, context, "sora", prompt, duration, aspect)
            return
        await update.effective_message.reply_text(f"❌ {engine} сейчас недоступен, а запасной Kling/Sora не включён.")
        return
    await update.effective_message.reply_text("❌ Ни один видео-движок не доступен. Проверьте COMET_API_KEY и ENV-флаги.")

async def _handle_text_to_video_auto(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, duration: int = 5, aspect: str = "9:16", intent: str = "text_video"):
    prompt = (prompt or "").strip()
    if not prompt:
        await update.effective_message.reply_text("Опишите, что нужно снять.")
        return
    aspect = _normalize_creative_aspect(aspect)
    engine = _choose_creative_engine(intent, {"images": 0}, prompt)
    if engine == "none":
        await update.effective_message.reply_text("❌ Сейчас нет доступного Comet-видео движка. Проверьте COMET_API_KEY / KLING_ENABLED / SEEDANCE_ENABLED.")
        return
    est = _estimate_engine_cost(engine, duration)
    aid = _new_aid()
    _pending_actions[aid] = {"prompt": prompt, "duration": duration, "aspect": aspect, "engine": engine, "intent": intent}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🚀 Запустить Auto: {engine} (~${est:.2f})", callback_data=f"choose:{engine}:{aid}")],
        [InlineKeyboardButton("⚙️ Выбрать вручную", callback_data=f"creative:manual_video:{aid}")],
        [InlineKeyboardButton("⬅️ Видео-меню", callback_data="nav:video")],
    ])
    await update.effective_message.reply_text(
        f"🧠 Creative Router выбрал: *{engine}*\n"
        f"Формат: {aspect} • длительность: {_duration_for_engine(engine, duration)} сек.\n"
        f"Запрос: «{prompt[:700]}»\n\n"
        f"Нажмите запуск или выберите движок вручную.",
        parse_mode="Markdown",
        reply_markup=kb,
    )

async def _handle_reels_assets(update: Update, context: ContextTypes.DEFAULT_TYPE, images: list[bytes], brief: str):
    images = [b for b in (images or []) if b][:REELS_MAX_PHOTOS]
    brief = (brief or "").strip() or "Сделай вертикальный AI Reels по присланным материалам"
    prompt = await _make_reels_prompt(brief, len(images))
    intent = "multi_photo_reels" if len(images) >= 2 else "reels"
    engine = _choose_creative_engine(intent, {"images": len(images)}, brief)
    if engine == "none":
        await update.effective_message.reply_text("❌ Нет доступного движка для Reels. Проверьте COMET_API_KEY и включите KLING/SEEDANCE/RUNWAY.")
        return
    duration = 10 if len(images) >= 2 else REELS_SCENE_DURATION_S
    await update.effective_message.reply_text(f"🎬 AI Reels Studio принял материалы: {len(images)} фото.\n🧠 Автовыбор движка: {engine}\nФормат: 9:16 • бриф учтён как главное ТЗ.\nЗапускаю генерацию…")
    await _run_creative_video(update, context, engine, prompt, duration, "9:16", images=images, intent=intent)
    await _make_social_post_pack(update, context, brief)

async def _maybe_collect_reels_album(update: Update, context: ContextTypes.DEFAULT_TYPE, img: bytes, caption: str) -> bool:
    msg = update.message
    mgid = getattr(msg, "media_group_id", None)
    if not mgid:
        return False
    wants_reels = bool(context.user_data.get("awaiting_reels_material")) or bool(re.search(r"\b(reels?|рилс|shorts?|шортс|клип|ролик|видео|тур|villa|вилл|недвиж)\b", caption or "", re.I))
    if not wants_reels:
        return False
    key = f"{update.effective_chat.id}:{mgid}"
    bucket = _CREATIVE_ALBUMS.setdefault(key, {"images": [], "caption": "", "update": update, "context": context, "task": None})
    bucket["images"].append(img)
    if caption:
        bucket["caption"] = caption
    bucket["update"] = update
    bucket["context"] = context
    context.user_data["awaiting_reels_material"] = True
    if not bucket.get("task"):
        bucket["task"] = asyncio.create_task(_flush_reels_album_later(key))
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text("📸 Собираю фотоальбом для AI Reels Studio. Подпись к альбому будет главным ТЗ.")
    return True

async def _flush_reels_album_later(key: str):
    await asyncio.sleep(REELS_ALBUM_SETTLE_S)
    bucket = _CREATIVE_ALBUMS.pop(key, None)
    if not bucket:
        return
    update = bucket.get("update")
    context = bucket.get("context")
    if not update or not context:
        return
    with contextlib.suppress(Exception):
        context.user_data.pop("awaiting_reels_material", None)
    await _handle_reels_assets(update, context, bucket.get("images") or [], bucket.get("caption") or "")

async def _handle_post_pack(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    await _make_social_post_pack(update, context, text)

async def _handle_music_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    if not _engine_enabled("suno"):
        await update.effective_message.reply_text("🎵 Музыка через Comet/Suno пока выключена. Добавьте SUNO_ENABLED=1 и проверьте SUNO_CREATE_PATH в ENV.", reply_markup=_after_result_kb())
        return
    await update.effective_message.reply_text("🎵 Музыкальный промпт принят. Следующим шагом подключается Suno через Comet: submit → polling → добавление к видео.\n\n" + f"Промпт: {text[:1000]}", reply_markup=_after_result_kb())

def main_keyboard():
    # Короткие подписи: в Telegram/Android длинные кнопки часто обрезаются.
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎬 Видео"), KeyboardButton("🖼 Фото")],
            [KeyboardButton("🗣 Аудио"), KeyboardButton("📄 Документы")],
            [KeyboardButton("🤖 GPT‑чат"), KeyboardButton("🏡 Бизнес")],
            [KeyboardButton("💼 Проекты"), KeyboardButton("⚙️ Настройки")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
        input_field_placeholder="Выберите задачу или напишите запрос…",
    )
main_kb = main_keyboard()

def _home_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Видео", callback_data="nav:video"), InlineKeyboardButton("🖼 Фото", callback_data="nav:photo")],
        [InlineKeyboardButton("🗣 Аудио", callback_data="nav:audio"), InlineKeyboardButton("📄 Документы", callback_data="nav:docs")],
        [InlineKeyboardButton("🤖 GPT‑чат", callback_data="nav:gpt"), InlineKeyboardButton("🏡 Бизнес", callback_data="nav:business")],
        [InlineKeyboardButton("💼 Проекты", callback_data="nav:projects"), InlineKeyboardButton("⚙️ Настройки", callback_data="nav:settings")],
    ])

def _home_text() -> str:
    return "🏠 Главное меню\nВыберите задачу. Движок можно оставить на Auto — бот сам подберёт Comet‑модель под материал и цель."

def _video_menu_text() -> str:
    return "🎬 *Видео / Reels*\nВыберите продукт, а не движок. После выбора бот спросит материалы, формат и стиль, затем Creative Router подберёт Comet‑движок."

def _video_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 AI Reels", callback_data="creative:reels")],
        [InlineKeyboardButton("🪄 Оживить", callback_data="creative:revive"), InlineKeyboardButton("📝 Текст→видео", callback_data="creative:t2v")],
        [InlineKeyboardButton("🧩 Фото→Reels", callback_data="creative:multi_reels")],
        [InlineKeyboardButton("🗣 Аватар", callback_data="creative:avatar"), InlineKeyboardButton("👄 Lip-sync", callback_data="creative:lipsync")],
        [InlineKeyboardButton("💬 Субтитры", callback_data="creative:subtitles"), InlineKeyboardButton("🎵 Музыка", callback_data="creative:music")],
        [InlineKeyboardButton("🖼 Обложка", callback_data="creative:cover"), InlineKeyboardButton("📲 Пост", callback_data="creative:post")],
        [InlineKeyboardButton("🎛 Движки", callback_data="settings:engines"), InlineKeyboardButton("🏠 Меню", callback_data="nav:home")],
    ])

def _photo_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎨 Генерация", callback_data="pedit:lumaimg"), InlineKeyboardButton("👁 Анализ", callback_data="pedit:vision")],
        [InlineKeyboardButton("🧼 Удалить фон", callback_data="pedit:removebg"), InlineKeyboardButton("🌈 Замена фона", callback_data="pedit:replacebg")],
        [InlineKeyboardButton("🧽 Ретушь", callback_data="pedit:retouch"), InlineKeyboardButton("🖼 Обложка", callback_data="creative:cover")],
        [InlineKeyboardButton("🎬 Оживить", callback_data="creative:revive"), InlineKeyboardButton("🏠 Меню", callback_data="nav:home")],
    ])

def _audio_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎙 STT", callback_data="creative:stt"), InlineKeyboardButton("🔊 TTS", callback_data="creative:tts")],
        [InlineKeyboardButton("🎵 Музыка", callback_data="creative:music"), InlineKeyboardButton("📢 Озвучка", callback_data="creative:voiceover")],
        [InlineKeyboardButton("🗣 Для аватара", callback_data="creative:avatar"), InlineKeyboardButton("🏠 Меню", callback_data="nav:home")],
    ])

def _docs_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📎 Анализ", callback_data="act:study:pdf_summary"), InlineKeyboardButton("🧠 Резюме", callback_data="act:study:pdf_summary")],
        [InlineKeyboardButton("🌍 Перевод", callback_data="act:free"), InlineKeyboardButton("📊 PDF", callback_data="biz:presentation")],
        [InlineKeyboardButton("🧽 Водн. знак", callback_data="docs:watermark"), InlineKeyboardButton("🩺 Медицина", callback_data="mode:medicine")],
        [InlineKeyboardButton("🏠 Меню", callback_data="nav:home")],
    ])

def _business_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏡 Пост виллы", callback_data="biz:villa_post"), InlineKeyboardButton("🎬 Рилс виллы", callback_data="biz:villa_reels")],
        [InlineKeyboardButton("🛡 Логотип", callback_data="biz:logo"), InlineKeyboardButton("📊 Презентация", callback_data="biz:presentation")],
        [InlineKeyboardButton("💰 ROI", callback_data="biz:roi"), InlineKeyboardButton("📲 WhatsApp", callback_data="biz:whatsapp")],
        [InlineKeyboardButton("🌍 Перевод", callback_data="biz:translate"), InlineKeyboardButton("🎨 Brand Kit", callback_data="settings:brand")],
        [InlineKeyboardButton("🏠 Меню", callback_data="nav:home")],
    ])

def engines_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧠 Auto Router", callback_data="engine:auto")],
        [InlineKeyboardButton("🎬 Kling", callback_data="engine:kling"), InlineKeyboardButton("🎥 Runway", callback_data="engine:runway")],
        [InlineKeyboardButton("🧪 Seedance", callback_data="engine:seedance"), InlineKeyboardButton("🎞 Veo", callback_data="engine:veo")],
        [InlineKeyboardButton("🧪 Hailuo", callback_data="engine:hailuo"), InlineKeyboardButton("🧪 Vidu", callback_data="engine:vidu")],
        [InlineKeyboardButton("🧪 Grok Video", callback_data="engine:grok"), InlineKeyboardButton("⚠️ Sora", callback_data="engine:sora")],
        [InlineKeyboardButton("🖼 Images", callback_data="engine:images"), InlineKeyboardButton("🗣 STT/TTS", callback_data="engine:stt_tts")],
        [InlineKeyboardButton("🏠 Меню", callback_data="nav:home")],
    ])

def photo_quick_actions_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Оживить", callback_data="pedit:revive_runway"), InlineKeyboardButton("🎞 Kling", callback_data="pedit:revive_kling")],
        [InlineKeyboardButton("🎬 Reels", callback_data="creative:reels_from_last"), InlineKeyboardButton("🖼 Обложка", callback_data="creative:cover")],
        [InlineKeyboardButton("🧽 Ретушь", callback_data="pedit:retouch"), InlineKeyboardButton("🧼 Фон", callback_data="pedit:removebg")],
        [InlineKeyboardButton("🌈 Замена фона", callback_data="pedit:replacebg"), InlineKeyboardButton("👁 Анализ", callback_data="pedit:vision")],
    ])

def _fun_reels_help_text() -> str:
    return "🎬 *AI Reels Studio*\nПришлите текст, голос, одно фото или фотоальбом. Если отправляете альбом — подпись к альбому будет главным ТЗ.\n\nПример: `Сделай рилс 20 секунд про виллу на Самуи, luxury, 9:16, с CTA в конце`.\n\nПосле результата появятся кнопки: субтитры, музыка, обложка, пост, повтор, другой движок."

def _clear_transient_flows(context):
    if not context:
        return
    for key in ("awaiting_photo_for", "photo_flow", "retouch_prompt", "retouch_wait_text", "awaiting_med_file", "awaiting_med_photo", "awaiting_med_document", "pending_med_task", "medicine_waiting_for_material", "awaiting_reels_material", "awaiting_film_material", "awaiting_text_video", "awaiting_post_pack", "awaiting_music_prompt", "awaiting_avatar_photo", "awaiting_lipsync_video", "awaiting_subtitles_media", "awaiting_logo_brief", "awaiting_doc_watermark"):
        with contextlib.suppress(Exception):
            context.user_data.pop(key, None)


async def _safe_q_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    """Безопасный ответ на inline-кнопки.
    Если кнопка висит под видео/фото, edit_message_text падает: "There is no text in the message to edit".
    Поэтому для медиа-сообщений отправляем новое текстовое сообщение, а для обычных текстов редактируем старое.
    """
    q = update.callback_query
    msg = getattr(q, "message", None) if q else None
    try:
        if msg is not None and getattr(msg, "text", None):
            return await q.edit_message_text(text, **kwargs)
        if msg is not None:
            return await msg.reply_text(text, **kwargs)
        if update.effective_message:
            return await update.effective_message.reply_text(text, **kwargs)
    except TelegramError as e:
        err = str(e).lower()
        if "no text" in err or "message is not modified" in err or "there is no text" in err:
            if msg is not None:
                return await msg.reply_text(text, **kwargs)
            if update.effective_message:
                return await update.effective_message.reply_text(text, **kwargs)
        raise

def _remember_last_creative(context: ContextTypes.DEFAULT_TYPE, **meta):
    try:
        clean = {k: v for k, v in meta.items() if v is not None}
        context.user_data["last_creative"] = clean
    except Exception:
        pass


def _get_last_creative(context: ContextTypes.DEFAULT_TYPE) -> dict:
    try:
        return dict(context.user_data.get("last_creative") or {})
    except Exception:
        return {}

async def on_nav_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()
    uid = q.from_user.id
    try:
        if data == "nav:home":
            _clear_transient_flows(context)
            await _safe_q_edit(update, context, _home_text(), reply_markup=_home_inline_kb())
            await q.answer(); return
        if data == "nav:video":
            await _safe_q_edit(update, context, _video_menu_text(), parse_mode="Markdown", reply_markup=_video_menu_kb())
            await q.answer(); return
        if data == "nav:photo":
            await _safe_q_edit(update, context, "🖼 *Фото / Дизайн*\nПришлите фото или выберите действие.", parse_mode="Markdown", reply_markup=_photo_menu_kb())
            await q.answer(); return
        if data == "nav:audio":
            await _safe_q_edit(update, context, "🗣 *Голос / Аудио*\nВыберите действие или пришлите voice/audio.", parse_mode="Markdown", reply_markup=_audio_menu_kb())
            await q.answer(); return
        if data == "nav:docs":
            await _safe_q_edit(update, context, "📄 *Документы*\nПришлите файл или выберите сценарий.", parse_mode="Markdown", reply_markup=_docs_menu_kb())
            await q.answer(); return
        if data == "nav:gpt":
            await _safe_q_edit(update, context, _modes_root_text(), reply_markup=modes_root_kb())
            await q.answer(); return
        if data == "nav:business":
            await _safe_q_edit(update, context, "🏡 *Бизнес / Недвижимость*\nГотовые сценарии для Cozy Asia и любых объектов.", parse_mode="Markdown", reply_markup=_business_menu_kb())
            await q.answer(); return
        if data == "nav:projects":
            await _safe_q_edit(update, context, "💼 *Мои проекты*\nИстория генераций и Brand Kit будут храниться в SQLite. Mini App можно подключить следующим шагом.", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎨 Brand Kit", callback_data="settings:brand")], [InlineKeyboardButton("🏠 Меню", callback_data="nav:home")]]))
            await q.answer(); return
        if data in ("nav:settings", "settings:root"):
            await _safe_q_edit(update, context, "⚙️ *Баланс / Настройки*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Баланс", callback_data="settings:balance"), InlineKeyboardButton("⭐ Подписка", callback_data="settings:plans")], [InlineKeyboardButton("🎛 Движки", callback_data="settings:engines"), InlineKeyboardButton("🎨 Brand Kit", callback_data="settings:brand")], [InlineKeyboardButton("🌐 Язык", callback_data="settings:lang"), InlineKeyboardButton("🏠 Меню", callback_data="nav:home")]]))
            await q.answer(); return
        if data == "settings:balance":
            await q.answer(); return await cmd_balance(update, context)
        if data == "settings:plans":
            await _safe_q_edit(update, context, _plans_overview_text(uid), reply_markup=plans_root_kb())
            await q.answer(); return
        if data == "settings:engines":
            await _safe_q_edit(update, context, "🎛 Движки\nРекомендуемый режим — Auto Router.", reply_markup=engines_kb())
            await q.answer(); return
        if data == "settings:brand":
            await _safe_q_edit(update, context, "🎨 Brand Kit\nПришлите название бренда, стиль, CTA, контакты и ссылки. Я буду применять это к постам, рилсам и презентациям.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="nav:home")]]))
            await q.answer(); return
        if data == "settings:lang":
            await _safe_q_edit(update, context, "🌐 Язык\nЯзыковая панель уже сохранена в общей логике проекта. Для следующего этапа можно вынести сюда: RU / EN / DE / FR / TH / UA / BY.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="nav:home")]]))
            await q.answer(); return
        if data == "docs:watermark":
            _clear_medicine_wait(context)
            _set_waiting_image_retouch(update, context, "убрать водяной знак/логотип/надпись и восстановить фон")
            context.user_data["awaiting_doc_watermark"] = True
            await _safe_q_edit(update, context, "🧽 Удаление водяного знака\nПришлите изображение/скрин/страницу документа как фото или PNG/JPG. Если файл ваш или у вас есть право редактирования — уберу водяной знак/лишнюю надпись и восстановлю фон.", reply_markup=_docs_menu_kb())
            await q.answer(); return
        if data in ("creative:stt", "creative:tts", "creative:voiceover"):
            if data == "creative:stt":
                txt = "🎙 Голос → текст\nПришлите voice/audio — бот распознает речь и передаст текст в нужный сценарий."
            elif data == "creative:tts":
                txt = "🔊 Текст → голос\nНапишите текст после /voice_on или пришлите текст в чат. На следующем этапе можно переключить TTS на Comet endpoint."
            else:
                txt = "📢 Рекламная озвучка\nПришлите текст ролика — я подготовлю voice-over, затем его можно связать с Reels/Avatar."
            await _safe_q_edit(update, context, txt, reply_markup=_audio_menu_kb())
            await q.answer(); return
        if data in ("creative:reels", "creative:multi_reels", "creative:reels_from_last"):
            _clear_transient_flows(context)
            _set_mode_clean(uid, "Видео", "reels")
            context.user_data["awaiting_reels_material"] = True
            if data == "creative:reels_from_last":
                img = _get_cached_photo(uid)
                if img:
                    await q.answer("Reels по последнему фото")
                    await _handle_reels_assets(update, context, [img], "Сделай вертикальный AI Reels по последнему фото")
                    return
            await _safe_q_edit(update, context, _fun_reels_help_text(), parse_mode="Markdown", reply_markup=_video_menu_kb())
            await q.answer(); return
        if data == "creative:revive":
            _clear_transient_flows(context)
            _set_waiting_photo_revival(update, context)
            await _safe_q_edit(update, context, _fun_revive_help_text(), parse_mode="Markdown", reply_markup=_video_menu_kb())
            await q.answer(); return
        if data == "creative:t2v":
            _clear_transient_flows(context)
            context.user_data["awaiting_text_video"] = True
            await _safe_q_edit(update, context, "📝 Текст → видео\nНапишите промпт. Можно указать: 5/10/15 сек, 9:16/16:9/1:1, стиль luxury/cinematic/viral.", reply_markup=_video_menu_kb())
            await q.answer(); return
        if data == "creative:avatar":
            _clear_transient_flows(context)
            context.user_data["awaiting_avatar_photo"] = True
            await _safe_q_edit(update, context, "🗣 Говорящий аватар\nПришлите фото человека и текст озвучки в подписи. Я подготовлю цепочку Kling TTS → Avatar.", reply_markup=_video_menu_kb())
            await q.answer(); return
        if data == "creative:lipsync":
            _clear_transient_flows(context)
            context.user_data["awaiting_lipsync_video"] = True
            await _safe_q_edit(update, context, "👄 Lip-sync / дубляж\nПришлите видео с лицом и текст/аудио для озвучки. На первом этапе включён безопасный сценарий с согласием владельца видео.", reply_markup=_video_menu_kb())
            await q.answer(); return
        if data == "creative:subtitles":
            _clear_transient_flows(context)
            context.user_data["awaiting_subtitles_media"] = True
            last = _get_last_creative(context)
            if last:
                await _safe_q_edit(update, context, "💬 Субтитры\nДля готового ролика пришлите видео/аудио отдельным сообщением — распознаю речь и подготовлю SRT/текст. Если нужна озвучка для этого сценария, нажмите 🎵 Музыка или 📲 Пост для текста.", reply_markup=_video_menu_kb())
            else:
                await _safe_q_edit(update, context, "💬 Субтитры\nПришлите видео или аудио — распознаю речь и подготовлю текст/субтитры.", reply_markup=_video_menu_kb())
            await q.answer(); return
        if data == "creative:music":
            _clear_transient_flows(context)
            last = _get_last_creative(context)
            if last:
                mood = f"cinematic luxury social media background music, no vocals, {int(last.get('duration') or 20)} seconds, for: {str(last.get('prompt') or '')[:300]}"
                await q.answer("Готовлю музыку…")
                await _handle_music_prompt(update, context, mood)
            else:
                context.user_data["awaiting_music_prompt"] = True
                await _safe_q_edit(update, context, "🎵 Музыка\nОпишите настроение: luxury tropical, cinematic, no vocals, 20 sec.", reply_markup=_video_menu_kb())
            return
        if data == "creative:cover":
            last = _get_last_creative(context)
            if last:
                cover_prompt = "Vertical premium cover/poster for a short social media video, high contrast, clean luxury design, no text, based on: " + str(last.get("prompt") or "")[:700]
                await q.answer("Генерирую обложку…")
                await _do_img_generate(update, context, cover_prompt)
            else:
                await _safe_q_edit(update, context, "🖼 Обложка\nПришлите кадр/фото или описание обложки.", reply_markup=_video_menu_kb())
            return
        if data == "creative:post":
            _clear_transient_flows(context)
            last = _get_last_creative(context)
            if last:
                await q.answer("Готовлю пост…")
                await _make_social_post_pack(update, context, str(last.get("prompt") or ""))
            else:
                context.user_data["awaiting_post_pack"] = True
                await _safe_q_edit(update, context, "📲 Пост\nПришлите описание результата/объекта/ролика — сделаю Telegram-пост, CTA, hashtags и WhatsApp-версию.", reply_markup=_video_menu_kb())
            return
        if data.startswith("creative:manual_video:"):
            aid = data.rsplit(":", 1)[-1]
            meta = _pending_actions.get(aid) or {}
            buttons = []
            has_images = bool(meta.get("images"))
            candidates = ("runway", "kling", "kling_multi", "veo", "hailuo", "vidu", "grok", "seedance", "sora") if has_images else ("kling", "veo", "hailuo", "vidu", "grok", "seedance", "sora")
            for eng in candidates:
                if _engine_enabled(eng):
                    buttons.append(InlineKeyboardButton(f"{eng} (~${_estimate_engine_cost(eng, int(meta.get('duration') or 5)):.2f})", callback_data=f"choose:{eng}:{aid}"))
            rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)] or [[InlineKeyboardButton("Нет доступных движков", callback_data="nav:video")]]
            rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="nav:video")])
            await _safe_q_edit(update, context, "⚙️ Ручной выбор движка", reply_markup=InlineKeyboardMarkup(rows))
            await q.answer(); return
        if data in ("creative:repeat", "creative:other_engine"):
            last = _get_last_creative(context)
            if not last:
                await _safe_q_edit(update, context, "🔁 Для повтора пришлите материал заново или выберите сценарий в меню.", reply_markup=_video_menu_kb())
                await q.answer(); return
            aid = _new_aid()
            _pending_actions[aid] = last
            if data == "creative:repeat":
                eng = str(last.get("engine") or _choose_creative_engine(str(last.get("intent") or "text_video"), {"images": len(last.get("images") or [])}, str(last.get("prompt") or "")))
                est = _estimate_engine_cost(eng, int(last.get("duration") or 5))
                kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"🚀 Повторить: {eng} (~${est:.2f})", callback_data=f"choose:{eng}:{aid}")], [InlineKeyboardButton("🎛 Другой движок", callback_data=f"creative:manual_video:{aid}")], [InlineKeyboardButton("🏠 Меню", callback_data="nav:home")]])
                await _safe_q_edit(update, context, "🔁 Повтор генерации\nМожно запустить тем же движком или выбрать другой.", reply_markup=kb)
            else:
                buttons = []
                has_images = bool(last.get("images"))
                candidates = ["runway", "kling", "kling_multi", "veo", "hailuo", "vidu", "grok", "seedance", "sora"] if has_images else ["kling", "veo", "hailuo", "vidu", "grok", "seedance", "sora"]
                for eng in candidates:
                    if _engine_enabled(eng):
                        buttons.append(InlineKeyboardButton(f"{eng} ~${_estimate_engine_cost(eng, int(last.get('duration') or 5)):.2f}", callback_data=f"choose:{eng}:{aid}"))
                rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)] or [[InlineKeyboardButton("Нет доступных", callback_data="nav:video")]]
                rows.append([InlineKeyboardButton("🏠 Меню", callback_data="nav:home")])
                await _safe_q_edit(update, context, "🧠 Выберите другой движок для этого же материала/промпта:", reply_markup=InlineKeyboardMarkup(rows))
            await q.answer(); return
        if data.startswith("biz:"):
            action = data.split(":", 1)[1]
            if action in ("villa_reels", "villa_post"):
                _clear_transient_flows(context)
                if action == "villa_reels":
                    context.user_data["awaiting_reels_material"] = True
                    await _safe_q_edit(update, context, "🏡 Рилс о вилле\nПришлите фотоальбом виллы и подпись: район, цена, спальни, депозит, комиссия, CTA. Подпись станет главным ТЗ.", reply_markup=_business_menu_kb())
                else:
                    context.user_data["awaiting_post_pack"] = True
                    await _safe_q_edit(update, context, "🏡 Пост о вилле\nПришлите описание, цену, район, условия, комиссию и ссылку на карту — сделаю пост в стиле Cozy Asia.", reply_markup=_business_menu_kb())
                await q.answer(); return
            if action == "logo":
                _clear_transient_flows(context)
                context.user_data["awaiting_logo_brief"] = True
                await _safe_q_edit(update, context, "🛡 Логотип\nПришлите бриф: название бренда, сфера, стиль, цвета, слоган и где будет использоваться логотип.\n\nПример: Cozy Asia Villas, недвижимость Самуи, premium tropical, зелёный/золото, без сложных деталей.", reply_markup=_business_menu_kb())
                await q.answer(); return
            await _safe_q_edit(update, context, "🏡 Бизнес-сценарий выбран. Пришлите вводные текстом или файлом — подготовлю структуру/пост/КП.", reply_markup=_business_menu_kb())
            await q.answer(); return
        await q.answer()
    except Exception as e:
        log.exception("on_nav_cb error: %s", e)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text(f"❌ Ошибка меню: {e}")

async def on_btn_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(_video_menu_text(), parse_mode="Markdown", reply_markup=_video_menu_kb())
async def on_btn_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("🖼 *Фото / Дизайн*\nПришлите фото или выберите действие.", parse_mode="Markdown", reply_markup=_photo_menu_kb())
async def on_btn_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("🗣 *Голос / Аудио*\nВыберите действие или пришлите voice/audio.", parse_mode="Markdown", reply_markup=_audio_menu_kb())
async def on_btn_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("📄 *Документы*\nПришлите файл или выберите сценарий.", parse_mode="Markdown", reply_markup=_docs_menu_kb())
async def on_btn_gpt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(_modes_root_text(), reply_markup=modes_root_kb())
async def on_btn_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("🏡 *Бизнес / Недвижимость*", parse_mode="Markdown", reply_markup=_business_menu_kb())
async def on_btn_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("💼 *Мои проекты*\nИстория генераций и Mini App кабинет подключаются следующим этапом.", parse_mode="Markdown", reply_markup=_home_inline_kb())
async def on_btn_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("⚙️ *Баланс / Настройки*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Баланс", callback_data="settings:balance"), InlineKeyboardButton("⭐ Подписка", callback_data="settings:plans")], [InlineKeyboardButton("🎛 Движки", callback_data="settings:engines"), InlineKeyboardButton("🎨 Brand Kit", callback_data="settings:brand")], [InlineKeyboardButton("🏠 Меню", callback_data="nav:home")]]))

_old_on_cb = on_cb
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip() if q else ""
    if data.startswith("engine:"):
        engine = data.split(":", 1)[1]
        if engine == "auto":
            await q.answer()
            await _safe_q_edit(update, context, "✅ Auto Router включён. Бот будет выбирать движок по задаче и материалам.", reply_markup=engines_kb())
            return
        if engine in {"seedance", "veo", "hailuo", "vidu", "grok"}:
            await q.answer()
            status = "✅ доступен" if _engine_enabled(engine) else "⚠️ выключен или нет COMET_API_KEY"
            await _safe_q_edit(update, context, f"{engine}: {status}\nВключается через ENV-флаг и модель/endpoint. Для обычного пользователя лучше оставлять Auto Router.", reply_markup=engines_kb())
            return
    if data.startswith("choose:"):
        try:
            await q.answer()
            _, engine, aid = data.split(":", 2)
            meta = _pending_actions.pop(aid, None)
            if not meta:
                await q.answer("Задача устарела", show_alert=True)
                return
            prompt = meta.get("prompt") or ""
            duration = int(meta.get("duration") or 5)
            aspect = meta.get("aspect") or "9:16"
            est = _estimate_engine_cost(engine, duration)
            map_engine = "runway" if engine in {"kling", "kling_multi", "sora", "seedance", "veo", "hailuo", "vidu", "grok"} else engine
            async def _start_real_render():
                await _run_creative_video(update, context, engine, prompt, duration, aspect, images=meta.get("images") or None, intent=meta.get("intent") or "text_video")
                _register_engine_spend(update.effective_user.id, map_engine, est)
            await _try_pay_then_do(update, context, update.effective_user.id, map_engine, est, _start_real_render, remember_kind=f"video_{engine}", remember_payload=meta)
            return
        except Exception as e:
            log.exception("creative choose failed: %s", e)
            with contextlib.suppress(Exception):
                await update.effective_message.reply_text(f"❌ Ошибка запуска движка: {e}")
            return
    return await _old_on_cb(update, context)

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

    # Команды
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("help",         cmd_help))
    app.add_handler(CommandHandler("examples",     cmd_examples))
    app.add_handler(CommandHandler("version",      cmd_version))
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
    app.add_handler(CallbackQueryHandler(on_cb_plans, pattern=r"^(?:plan:|pay:)$|^(?:plan:|pay:).+"))

    # 2) Новые режимы/подменю: mode:* и act:* (Учёба/Работа/Развлечения/Медицина)
    app.add_handler(CallbackQueryHandler(on_mode_cb, pattern=r"^(?:mode:|act:)"), group=0)

    # 2b) Старые school:/work: callbacks, если такие кнопки ещё где-то используются
    app.add_handler(CallbackQueryHandler(on_cb_mode, pattern=r"^(?:school:|work:)"), group=0)

    # 3) Быстрые развлечения (любые fun:...)
    app.add_handler(CallbackQueryHandler(on_cb_fun,   pattern=r"^fun:[a-z_]+$"))

    # 3b) Новое продуктовое меню: nav/creative/biz/settings/project
    app.add_handler(CallbackQueryHandler(on_nav_cb, pattern=r"^(?:nav:|creative:|biz:|settings:|project:).+"), group=0)

    # 4) Остальной catch-all (pedit/topup/engine/buy и т.п.)
    # Размещаем в приоритетной группе, чтобы колбэки обрабатывались сразу
    app.add_handler(CallbackQueryHandler(on_cb), group=0)

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
    BTN_WORK    = re.compile(r"^\s*(?:💼\s*)?Работа\s*$")
    BTN_FUN     = re.compile(r"^\s*(?:🔥\s*)?Развлечения\s*$")
    BTN_MED     = re.compile(r"^\s*(?:🩺|⚕️)?\s*Медицина\s*$")
    BTN_VIDEO   = re.compile(r"^\s*(?:🎬\s*)?(?:Видео\s*/\s*Reels|Видео|Reels|Рилс(?:ы)?)\s*$", re.I)
    BTN_PHOTO   = re.compile(r"^\s*(?:🖼\s*)?(?:Фото\s*/\s*Дизайн|Фото|Дизайн)\s*$", re.I)
    BTN_AUDIO   = re.compile(r"^\s*(?:🗣\s*)?(?:Голос\s*/\s*Аудио|Голос|Аудио)\s*$", re.I)
    BTN_DOCS    = re.compile(r"^\s*(?:📄\s*)?(?:Документы|Файлы)\s*$", re.I)
    BTN_GPT     = re.compile(r"^\s*(?:🤖\s*)?GPT[‑-]?чат\s*$", re.I)
    BTN_BIZ     = re.compile(r"^\s*(?:🏡\s*)?(?:Бизнес|Недвижимость|Бизнес\s*/\s*Недвижимость)\s*$", re.I)
    BTN_PROJECTS= re.compile(r"^\s*(?:💼\s*)?(?:Мои\s+проекты|Проекты)\s*$", re.I)
    BTN_SETTINGS= re.compile(r"^\s*(?:⚙️\s*)?(?:Баланс\s*/\s*Настройки|Настройки)\s*$", re.I)

    # Кнопки в приоритетной группе (0), чтобы они срабатывали раньше любых общих обработчиков
    app.add_handler(MessageHandler(filters.Regex(BTN_VIDEO),   on_btn_video),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_PHOTO),   on_btn_photo),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_AUDIO),   on_btn_audio),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_DOCS),    on_btn_docs),    group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_GPT),     on_btn_gpt),     group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_BIZ),     on_btn_business),group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_PROJECTS),on_btn_projects),group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_SETTINGS),on_btn_settings),group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_ENGINES), on_btn_engines), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_BALANCE), on_btn_balance), group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_PLANS),   on_btn_plans),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_STUDY),   on_btn_study),   group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_WORK),    on_btn_work),    group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_FUN),     on_btn_fun),     group=0)
    app.add_handler(MessageHandler(filters.Regex(BTN_MED),     on_btn_medicine), group=0)

    # Жёсткий перехват «можешь оживить фото?» — до любого GPT-ответа.
    # ВАЖНО: здесь намеренно нет inline-флагов вида (?is), чтобы Render/Python 3.12 не падал.
    photo_revive_capability_re = re.compile(
        r"(мож(ешь|ете|но)|уме(ешь|ете)|может\s+ли|способен|поддерживаешь|получится|делаешь)"
        r".{0,160}(ожив|анимир|revive|animate)"
        r".{0,160}(фото|фотограф|картинк|изображен|photo|image|picture)"
        r"|"
        r"(ожив|анимир|revive|animate)"
        r".{0,160}(фото|фотограф|картинк|изображен|photo|image|picture)"
        r".{0,80}\?",
        re.I | re.S,
    )
    app.add_handler(
        MessageHandler(filters.Regex(photo_revive_capability_re), on_photo_revival_capability),
        group=0,
    )
    # ➕ Позитивный авто-ответ на «а умеешь ли…» — до общего текста (отдельная группа, ниже кнопок)
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
                       filters.Regex(BTN_MED)     | filters.Regex(BTN_VIDEO) |
                       filters.Regex(BTN_PHOTO)   | filters.Regex(BTN_AUDIO) |
                       filters.Regex(BTN_DOCS)    | filters.Regex(BTN_GPT) |
                       filters.Regex(BTN_BIZ)     | filters.Regex(BTN_PROJECTS) |
                       filters.Regex(BTN_SETTINGS))
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
