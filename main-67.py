import hashlib
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
import shutil
import sys
import tempfile
import contextlib

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
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, InputFile,
    LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters,
    PreCheckoutQueryHandler, CallbackQueryHandler
)
from telegram.constants import ChatAction
from telegram.error import TelegramError, TimedOut
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
try:
    from rembg import remove as rembg_remove, new_session as rembg_new_session
    REMBG_IMPORT_ERROR = ""
except Exception as _rembg_e:
    rembg_remove = None
    rembg_new_session = None
    REMBG_IMPORT_ERROR = repr(_rembg_e)

# ───────── LOGGING ─────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")

PATCH_VERSION = "v34.3-face-choice-fix-2026-07-07"

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
FACESWAP_FAST_COST_USD = _env_float("FACESWAP_FAST_COST_USD", 0.03)
FACESWAP_PREMIUM_COST_USD = _env_float("FACESWAP_PREMIUM_COST_USD", 0.12)
FACESWAP_TIMEOUT_S = float(os.environ.get("FACESWAP_TIMEOUT_S", "180") or 180)
FACESWAP_POLL_DELAY_S = float(os.environ.get("FACESWAP_POLL_DELAY_S", "2.5") or 2.5)
FACESWAP_INPUT_MAX_SIDE = int(os.environ.get("FACESWAP_INPUT_MAX_SIDE", "1600") or 1600)
FACESWAP_OUTPUT_MAX_SIDE = int(os.environ.get("FACESWAP_OUTPUT_MAX_SIDE", "1600") or 1600)
FACESWAP_RESULT_AS_DOCUMENT = os.environ.get("FACESWAP_RESULT_AS_DOCUMENT", "0").strip().lower() in ("1", "true", "yes", "on")
FACESWAP_IMAGE_DATA_URL = os.environ.get("FACESWAP_IMAGE_DATA_URL", "0").strip().lower() in ("1", "true", "yes", "on")
FACESWAP_WARN_TEXT = os.environ.get("FACESWAP_WARN_TEXT", "1").strip().lower() not in ("0", "false", "no", "off")
FACESWAP_MANUAL_CHOICE_IF_DETECTION_FAIL = os.environ.get("FACESWAP_MANUAL_CHOICE_IF_DETECTION_FAIL", "1").strip().lower() not in ("0", "false", "no", "off")

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
RUNWAY_TASK_NOT_EXIST_FALLBACK_S = int(os.environ.get("RUNWAY_TASK_NOT_EXIST_FALLBACK_S", "90") or 90)
RUNWAY_AUTO_FALLBACK_KLING = os.environ.get("RUNWAY_AUTO_FALLBACK_KLING", "1").strip().lower() not in ("0", "false", "no", "off")
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

# Таймауты
LUMA_MAX_WAIT_S     = int((os.environ.get("LUMA_MAX_WAIT_S") or "900").strip() or 900)
LUMA_TEMP_DISABLED = True  # временная заглушка: скрываем Luma из меню и отключаем использование
RUNWAY_MAX_WAIT_S   = int((os.environ.get("RUNWAY_MAX_WAIT_S") or "1200").strip() or 1200)
VIDEO_POLL_DELAY_S  = float((os.environ.get("VIDEO_POLL_DELAY_S") or "6.0").strip() or 6.0)
VIDEO_RESULT_SEND_AS_DOCUMENT = os.getenv("VIDEO_RESULT_SEND_AS_DOCUMENT", "1") == "1"
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
    "Команды: /start, /engines, /plans, /balance, /img <описание>, /voice_on, /voice_off, /diag_video, /diag_bg, /diag_face.\n"
    "Можно отправить фото и выбрать: оживить через Runway/Sora/Kling, ретушировать собственное фото/убрать лишнюю надпись, удалить/заменить фон, заменить лицо, расширить кадр, сделать раскадровку или анализ.\n"
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
    "Привет! Я Нейро-Bot — ⚡️ мультирежимный бот из 7 нейросетей для 🎓 учёбы, 💼 работы, 🔥 развлечений и 🩺 медицины.\n"
    "Я умею работать гибридно: могу сам выбрать лучший доступный движок под задачу или дать тебе выбрать вручную. 🤝🧠\n"
    "\n"
    "✨ Главные режимы:\n"
    "\n"
    "• 🎓 Учёба — объяснения с примерами, пошаговые решения задач, эссе/реферат/доклад, мини-квизы.\n"
    "📚 Также: разбор учебных PDF/электронных книг, шпаргалки и конспекты, конструктор тестов;\n"
    "🎧 тайм-коды по аудиокнигам/лекциям и краткие выжимки. 🧩\n"
    "\n"
    "• 💼 Работа — письма/брифы/документы, аналитика и резюме материалов, ToDo/планы, генератор идей.\n"
    "🛠️ Для архитектора/дизайнера/проектировщика: структурирование ТЗ, чек-листы стадий,\n"
    "🗂️ названия/описания листов, сводные таблицы из текстов, оформление пояснительных записок. 📊\n"
    "\n"
    "• 🔥 Развлечения — фото-мастерская, оживление фото, Reels/Shorts, сценарии, мини-фильмы, мемы/квизы. 🖼️🪄\n"
    "\n"
    "• 🩺 Медицина — справочный разбор выписок, анамнеза, врачебных заключений, МРТ/КТ/снимков и результатов анализов.\n"
    "⚠️ Это не официальный диагноз и не замена врачу/очному обследованию: я помогаю понять текст, выделить риски и подготовить вопросы специалисту.\n"
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
    # Не ставим 3 длинные кнопки в одну строку — на Android Telegram режет текст.
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎓 Учёба", callback_data="mode:study"),
            InlineKeyboardButton("💼 Работа", callback_data="mode:work"),
        ],
        [
            InlineKeyboardButton("🔥 Развлечения", callback_data="mode:fun"),
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
            "Главные быстрые действия: оживить фото, сделать Reels/Shorts, создать мини-фильм, заменить лицо, удалить или заменить фон на фото.\n"
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
            [InlineKeyboardButton("🪄 Оживить фото", callback_data="act:fun:revive")],
            [InlineKeyboardButton("🎭 Замена лица на фото", callback_data="act:fun:faceswap")],
            [InlineKeyboardButton("🧼 Удалить фон на фото", callback_data="act:fun:removebg")],
            [InlineKeyboardButton("🖼 Заменить фон на фото", callback_data="act:fun:replacebg")],
            [InlineKeyboardButton("📱 Сделать Reels / Shorts", callback_data="act:fun:reels")],
            [InlineKeyboardButton("🎞 Создать мини-фильм", callback_data="act:fun:film")],
            [InlineKeyboardButton("🎬 Сценарий шорта", callback_data="act:fun:shorts")],
            [InlineKeyboardButton("🎮 Игры / квиз", callback_data="act:fun:games")],
            [InlineKeyboardButton("🎭 Идеи для досуга", callback_data="act:fun:ideas")],
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

    if data == "act:fun:faceswap":
        await q.answer()
        _clear_transient_flows(context)
        _set_mode_clean(uid, "Развлечения", "faceswap")
        await _start_faceswap_flow(update, context, _get_cached_photo(uid))
        return

    if data == "act:fun:removebg":
        await q.answer()
        _clear_transient_flows(context)
        _set_mode_clean(uid, "Развлечения", "removebg")
        img = _get_cached_photo(uid)
        if img:
            await q.message.reply_text("🧼 Использую последнее загруженное фото и удаляю фон.")
            await _pedit_removebg(update, context, img)
        else:
            _set_waiting_removebg(context)
            await q.edit_message_text("🧼 Пришлите фото — удалю фон и верну PNG с прозрачной подложкой.", reply_markup=_mode_kb("fun"))
        return

    if data == "act:fun:replacebg":
        await q.answer()
        _clear_transient_flows(context)
        _set_mode_clean(uid, "Развлечения", "replacebg")
        img = _get_cached_photo(uid)
        if img:
            await q.message.reply_text("🖼 Выберите новый фон для последнего загруженного фото:", reply_markup=background_presets_kb())
        else:
            context.user_data["photo_flow"] = "replacebg_menu"
            await q.edit_message_text("🖼 Пришлите фото. После загрузки я покажу варианты фона: пляж, горы, природа, город или свой текст.", reply_markup=_mode_kb("fun"))
        return

    if data == "act:fun:revive":
        await q.answer()
        _set_waiting_photo_revival(update, context)
        await q.edit_message_text(
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
        await q.edit_message_text(
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
        await q.edit_message_text(
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
        await q.edit_message_text(_medical_menu_text(track), reply_markup=medicine_kb())
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
        "медицина": "medicine", "медицинa": "medicine",
    }
    key = mapping.get(text)
    if key:
        await _send_mode_menu(update, context, key)
        
def main_keyboard():
    # 2 кнопки в строке — так Telegram на мобильных не обрезает подписи.
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎓 Учёба"), KeyboardButton("💼 Работа")],
            [KeyboardButton("🔥 Развлечения"), KeyboardButton("🩺 Медицина")],
            [KeyboardButton("🧠 Движки"), KeyboardButton("🧾 Баланс")],
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
        [InlineKeyboardButton("🪄 Оживить фото", callback_data="fun:revive")],
        [InlineKeyboardButton("🎭 Замена лица на фото", callback_data="fun:faceswap")],
        [InlineKeyboardButton("🧼 Удалить фон на фото", callback_data="fun:removebg")],
        [InlineKeyboardButton("🖼 Заменить фон на фото", callback_data="fun:replacebg")],
        [InlineKeyboardButton("📱 Reels / Shorts", callback_data="fun:reels")],
        [InlineKeyboardButton("🎞 Создать мини-фильм", callback_data="fun:film")],
        [InlineKeyboardButton("🎬 Раскадровка под Reels", callback_data="fun:storyboard")],
        [InlineKeyboardButton("🖌 Сгенерировать изображение", callback_data="fun:img")],
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
        "🔥 Развлечения — быстрые действия: видео, фото, фон и замена лица.",
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
            await q.edit_message_text(f"{mode} → {track}. Напишите задание/тему — сделаю.")
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
        return await q.edit_message_text("Пришли промпт или используй команду /img <описание> — сгенерирую изображение.")
    if data == "fun:revive":
        return await q.edit_message_text("Загрузи фото (как картинку) и напиши, что оживить/как двигаться. Сделаю анимацию.")
    if data == "fun:clip":
        return await q.edit_message_text("Пришли текст/голос и формат (Reels/Shorts), музыку/стиль — соберу клип. Для генерации видео доступны Sora 2 и Kling; Runway — только оживление фото.")
    if data == "fun:storyboard":
        return await q.edit_message_text("Пришли фото или опиши идею ролика — верну раскадровку под Reels с тайм-кодами.")

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
def photo_quick_actions_kb():
    # Длинные подписи — отдельными строками, чтобы не обрезались в Telegram.
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Оживить фото через Runway", callback_data="pedit:revive_runway")],
        [InlineKeyboardButton("✨ Оживить фото через Kling", callback_data="pedit:revive_kling")],
        [InlineKeyboardButton("✨ Sora 2: фото без людей", callback_data="pedit:revive_sora")],
        [InlineKeyboardButton("🎭 Замена лица на фото", callback_data="pedit:faceswap")],
        [InlineKeyboardButton("🧼 Удалить фон на фото", callback_data="pedit:removebg")],
        [InlineKeyboardButton("🖼 Заменить фон на фото", callback_data="pedit:replacebg")],
        [InlineKeyboardButton("🧽 Ретушь / убрать надпись", callback_data="pedit:retouch")],
        [InlineKeyboardButton("🧭 Расширить кадр", callback_data="pedit:outpaint")],
        [InlineKeyboardButton("📽 Раскадровка по фото", callback_data="pedit:story")],
        [InlineKeyboardButton("🖌 Картинка по описанию", callback_data="pedit:lumaimg")],
        [InlineKeyboardButton("👁 Анализ фото", callback_data="pedit:vision")],
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

def background_presets_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌫 Размытый фон", callback_data="pedit:bg:blur"),
         InlineKeyboardButton("🏖 Пляж", callback_data="pedit:bg:beach")],
        [InlineKeyboardButton("🌿 Природа", callback_data="pedit:bg:nature"),
         InlineKeyboardButton("⛰ Горы", callback_data="pedit:bg:mountains")],
        [InlineKeyboardButton("🏙 Крыша/город", callback_data="pedit:bg:roof"),
         InlineKeyboardButton("⚪ Белый фон", callback_data="pedit:bg:white")],
        [InlineKeyboardButton("✍️ Свой фон текстом", callback_data="pedit:bg:custom")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="pedit:back")],
    ])


def _set_waiting_removebg(context):
    context.user_data["awaiting_photo_for"] = "removebg"
    context.user_data["photo_flow"] = "removebg"


def _is_waiting_removebg(context) -> bool:
    return bool(context and (context.user_data.get("awaiting_photo_for") == "removebg" or context.user_data.get("photo_flow") == "removebg"))


def _clear_removebg_wait(context):
    if not context:
        return
    if context.user_data.get("awaiting_photo_for") == "removebg":
        context.user_data.pop("awaiting_photo_for", None)
    if context.user_data.get("photo_flow") == "removebg":
        context.user_data.pop("photo_flow", None)


def _set_waiting_replacebg(context, prompt: str = ""):
    context.user_data["awaiting_photo_for"] = "replacebg"
    context.user_data["photo_flow"] = "replacebg"
    if prompt:
        context.user_data["replacebg_prompt"] = prompt.strip()


def _set_replacebg_wait_text(context):
    context.user_data["replacebg_wait_text"] = "1"


def _is_replacebg_wait_text(context) -> bool:
    return bool(context and context.user_data.get("replacebg_wait_text"))


def _is_waiting_replacebg(context) -> bool:
    return bool(context and (context.user_data.get("awaiting_photo_for") == "replacebg" or context.user_data.get("photo_flow") == "replacebg"))


def _clear_replacebg_wait(context):
    if not context:
        return
    for key in ("replacebg_wait_text", "replacebg_prompt"):
        context.user_data.pop(key, None)
    if context.user_data.get("awaiting_photo_for") == "replacebg":
        context.user_data.pop("awaiting_photo_for", None)
    if context.user_data.get("photo_flow") == "replacebg":
        context.user_data.pop("photo_flow", None)


def _is_remove_bg_request(text: str) -> bool:
    tl = (text or "").lower()
    return any(k in tl for k in ("удали фон", "удалить фон", "убери фон", "убрать фон", "removebg", "remove background", "прозрачный фон", "без фона"))


def _is_replace_bg_request(text: str) -> bool:
    tl = (text or "").lower()
    return any(k in tl for k in ("замени фон", "заменить фон", "поменяй фон", "поменять фон", "replacebg", "replace background", "фон на", "другой фон"))


def _bg_kind_from_text(text: str) -> tuple[str, str]:
    tl = (text or "").lower()
    if any(k in tl for k in ("пляж", "море", "океан", "beach")):
        return "beach", text
    if any(k in tl for k in ("горы", "гора", "mountain")):
        return "mountains", text
    if any(k in tl for k in ("крыша", "город", "небоскреб", "rooftop", "city")):
        return "roof", text
    if any(k in tl for k in ("природа", "лес", "зелень", "nature", "forest")):
        return "nature", text
    if any(k in tl for k in ("белый", "white")):
        return "white", text
    if any(k in tl for k in ("черный", "чёрный", "black")):
        return "black", text
    if any(k in tl for k in ("размы", "blur", "блюр")):
        return "blur", text
    return "custom", text


def _safe_b64decode_image(value: str) -> bytes | None:
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if s.startswith("data:") and "," in s:
        s = s.split(",", 1)[1]
    try:
        return base64.b64decode(s, validate=False)
    except Exception:
        return None


def _find_first_image_b64(obj) -> bytes | None:
    if isinstance(obj, dict):
        for key in ("b64_json", "image_b64", "image", "png", "result_b64"):
            if key in obj:
                out = _safe_b64decode_image(obj.get(key))
                if out:
                    return out
        for v in obj.values():
            out = _find_first_image_b64(v)
            if out:
                return out
    elif isinstance(obj, list):
        for v in obj:
            out = _find_first_image_b64(v)
            if out:
                return out
    return None


def _find_first_image_url(obj) -> str:
    if isinstance(obj, dict):
        for key in ("url", "image_url", "output_url", "result_url", "download_url", "file_url"):
            val = obj.get(key)
            if isinstance(val, str) and val.startswith(("http://", "https://")):
                return val
            if isinstance(val, dict):
                nested = val.get("url")
                if isinstance(nested, str) and nested.startswith(("http://", "https://")):
                    return nested
        for v in obj.values():
            url = _find_first_image_url(v)
            if url:
                return url
    elif isinstance(obj, list):
        for v in obj:
            url = _find_first_image_url(v)
            if url:
                return url
    return ""


async def _image_bytes_from_response(resp: httpx.Response, client: httpx.AsyncClient) -> bytes | None:
    ctype = (resp.headers.get("content-type") or "").lower()
    if ctype.startswith("image/") and resp.content:
        return bytes(resp.content)
    try:
        obj = resp.json()
    except Exception:
        return None
    out = _find_first_image_b64(obj)
    if out:
        return out
    url = _find_first_image_url(obj)
    if url:
        try:
            rr = await client.get(url, timeout=BG_REMOVE_TIMEOUT_S)
            rr.raise_for_status()
            if rr.content:
                return bytes(rr.content)
        except Exception as e:
            log.warning("background result url download failed: %s", e)
    return None


def _prepare_bytes_for_rembg(img_bytes: bytes) -> bytes:
    """
    Render Starter может упираться в RAM на больших фото.
    Для local rembg уменьшаем слишком крупные изображения до REMBG_MAX_SIDE.
    """
    if Image is None or not REMBG_MAX_SIDE or REMBG_MAX_SIDE <= 0:
        return img_bytes
    try:
        im = Image.open(BytesIO(img_bytes))
        with contextlib.suppress(Exception):
            im = ImageOps.exif_transpose(im)
        w, h = im.size
        mx = max(w, h)
        if mx <= REMBG_MAX_SIDE:
            return img_bytes
        scale = REMBG_MAX_SIDE / float(mx)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        resample = getattr(Image, "Resampling", Image).LANCZOS
        im = im.convert("RGB").resize((nw, nh), resample)
        out = BytesIO()
        im.save(out, format="JPEG", quality=94, optimize=True)
        _bg_note_error(f"local rembg input resized {w}x{h}->{nw}x{nh}")
        return out.getvalue()
    except Exception as e:
        _bg_note_error(f"local rembg resize skipped: {e}")
        return img_bytes


def _get_local_rembg_session():
    global _REMBG_SESSION
    if rembg_remove is None:
        _bg_note_error(f"rembg import failed: {REMBG_IMPORT_ERROR}")
        return None
    if rembg_new_session is None:
        _bg_note_error("rembg.new_session is not available")
        return None
    if _REMBG_SESSION is not None:
        return _REMBG_SESSION
    with _REMBG_SESSION_LOCK:
        if _REMBG_SESSION is not None:
            return _REMBG_SESSION
        with contextlib.suppress(Exception):
            os.environ.setdefault("U2NET_HOME", U2NET_HOME)
            os.makedirs(U2NET_HOME, exist_ok=True)
            os.makedirs(XDG_CACHE_HOME, exist_ok=True)
        last_exc = ""
        for model_name in REMBG_MODEL_FALLBACKS:
            try:
                log.info("Initializing local rembg session: model=%s U2NET_HOME=%s", model_name, os.environ.get("U2NET_HOME"))
                _REMBG_SESSION = rembg_new_session(model_name)
                log.info("local rembg session ready: model=%s", model_name)
                return _REMBG_SESSION
            except Exception as e:
                last_exc = repr(e)
                log.warning("local rembg session init failed model=%s: %s", model_name, e)
                _bg_note_error(f"local rembg session init failed model={model_name}: {e}")
        _bg_note_error(f"local rembg session unavailable: {last_exc}")
    return None



async def _local_rembg_remove_subprocess(img_bytes: bytes) -> bytes | None:
    """
    Изолированный local rembg worker. Если rembg/onnxruntime зависнет при скачивании
    или инициализации модели, основной бот не зависает: процесс убиваем по timeout.
    """
    if not LOCAL_REMBG_ENABLED or rembg_remove is None:
        return None
    if Image is not None:
        img_bytes = _prepare_bytes_for_rembg(img_bytes)
    timeout_s = max(20.0, float(LOCAL_REMBG_TIMEOUT_S or 180))
    env = os.environ.copy()
    env["U2NET_HOME"] = env.get("U2NET_HOME") or U2NET_HOME or "/tmp/.u2net"
    env["XDG_CACHE_HOME"] = env.get("XDG_CACHE_HOME") or XDG_CACHE_HOME or "/tmp/.cache"
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("MPLCONFIGDIR", "/tmp/.matplotlib")
    for d in (env["U2NET_HOME"], env["XDG_CACHE_HOME"], env["MPLCONFIGDIR"]):
        with contextlib.suppress(Exception):
            os.makedirs(d, exist_ok=True)

    worker_code = r'''
import os, sys
from pathlib import Path
try:
    from rembg import remove, new_session
except Exception as e:
    print(f"IMPORT_ERROR: {e}", file=sys.stderr)
    sys.exit(11)
model = os.environ.get("REMBG_MODEL", "u2netp") or "u2netp"
inp, outp = sys.argv[1], sys.argv[2]
try:
    Path(os.environ.get("U2NET_HOME", "/tmp/.u2net")).mkdir(parents=True, exist_ok=True)
    Path(os.environ.get("XDG_CACHE_HOME", "/tmp/.cache")).mkdir(parents=True, exist_ok=True)
    data = Path(inp).read_bytes()
    sess = new_session(model)
    try:
        out = remove(data, session=sess, force_return_bytes=True)
    except TypeError:
        out = remove(data, session=sess)
    Path(outp).write_bytes(out)
except Exception as e:
    print(f"REMBG_WORKER_ERROR: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(12)
'''
    in_path = out_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="rembg_in_", suffix=".jpg", delete=False) as f:
            f.write(img_bytes)
            in_path = f.name
        fd, out_path = tempfile.mkstemp(prefix="rembg_out_", suffix=".png")
        os.close(fd)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", worker_code, in_path, out_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            _bg_note_error(f"local rembg subprocess timeout after {timeout_s:.0f}s")
            return None
        if proc.returncode != 0:
            msg = (stderr or stdout or b"").decode("utf-8", "replace")[:800]
            _bg_note_error(f"local rembg subprocess failed rc={proc.returncode}: {msg}")
            return None
        if not out_path or not os.path.exists(out_path) or os.path.getsize(out_path) < 512:
            _bg_note_error("local rembg subprocess produced empty output")
            return None
        with open(out_path, "rb") as f:
            return f.read()
    except Exception as e:
        _bg_note_error(f"local rembg subprocess exception: {e}")
        log.warning("local rembg subprocess exception: %s", e)
        return None
    finally:
        for path in (in_path, out_path):
            if path:
                with contextlib.suppress(Exception):
                    os.remove(path)

def _local_rembg_remove_sync(img_bytes: bytes) -> bytes:
    img_bytes = _prepare_bytes_for_rembg(img_bytes)
    session = _get_local_rembg_session()
    if session is not None:
        try:
            return rembg_remove(img_bytes, session=session, force_return_bytes=True)
        except TypeError:
            return rembg_remove(img_bytes, session=session)
    try:
        return rembg_remove(img_bytes, force_return_bytes=True)
    except TypeError:
        return rembg_remove(img_bytes)


async def _local_rembg_remove_bytes(img_bytes: bytes) -> bytes | None:
    if not LOCAL_REMBG_ENABLED:
        return None
    if rembg_remove is None:
        log.warning("local rembg is not available: %s", REMBG_IMPORT_ERROR)
        return None

    if LOCAL_REMBG_SUBPROCESS:
        return await _local_rembg_remove_subprocess(img_bytes)

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_local_rembg_remove_sync, img_bytes),
            timeout=LOCAL_REMBG_TIMEOUT_S,
        )
    except Exception as e:
        log.warning("local rembg failed: %s", e)
        _bg_note_error(f"local rembg failed: {e}")
        return None




def _resize_image_bytes_for_bg_api(img_bytes: bytes, max_side: int | None = None) -> tuple[bytes, str, str]:
    """Сжимает вход перед Photoroom, чтобы не ловить API/Telegram timeout на больших фото."""
    max_side = int(max_side or PHOTOROOM_INPUT_MAX_SIDE or 1600)
    mime = sniff_image_mime(img_bytes) or "image/jpeg"
    if Image is None or max_side <= 0:
        ext = ".jpg" if mime == "image/jpeg" else (".png" if mime == "image/png" else ".webp")
        return img_bytes, f"image{ext}", mime
    try:
        im = Image.open(BytesIO(img_bytes))
        # Для исходных фото прозрачность не нужна, Photoroom сам вернёт PNG/RGBA.
        im = ImageOps.exif_transpose(im) if ImageOps else im
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        # JPEG сильно уменьшает размер запроса и ускоряет бесплатный API.
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        bio = BytesIO()
        im.save(bio, format="JPEG", quality=92, optimize=True, progressive=True)
        return bio.getvalue(), "image.jpg", "image/jpeg"
    except Exception as e:
        _bg_note_error(f"input resize for Photoroom failed: {e}")
        ext = ".jpg" if mime == "image/jpeg" else (".png" if mime == "image/png" else ".webp")
        return img_bytes, f"image{ext}", mime

async def _photoroom_api_remove_bytes(img_bytes: bytes) -> bytes | None:
    """Photoroom Remove Background API. Returns transparent PNG/RGBA bytes."""
    if not PHOTOROOM_API_KEY:
        _bg_note_error("Photoroom API key missing: set PHOTOROOM_API_KEY in Render Environment")
        return None
    upload_bytes, upload_name, mime = _resize_image_bytes_for_bg_api(img_bytes, PHOTOROOM_INPUT_MAX_SIDE)
    url = f"{PHOTOROOM_BASE_URL}{PHOTOROOM_REMOVE_PATH}"
    headers = {"x-api-key": PHOTOROOM_API_KEY}
    # Photoroom /v1/segment accepts remove.bg-compatible fields.
    data = {
        "format": PHOTOROOM_FORMAT or "png",
        "channels": PHOTOROOM_CHANNELS or "rgba",
        "size": PHOTOROOM_SIZE or "hd",
        "crop": PHOTOROOM_CROP or "false",
        "despill": PHOTOROOM_DESPILL or "false",
    }
    timeout = httpx.Timeout(PHOTOROOM_TIMEOUT_S, connect=20.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            files = {"image_file": (upload_name, upload_bytes, mime)}
            r = await client.post(url, headers=headers, data=data, files=files)
            if r.status_code >= 400:
                body = (r.text or "")[:900]
                _bg_note_error(f"Photoroom API failed status={r.status_code} body={body}")
                log.warning("Photoroom API failed status=%s body=%s", r.status_code, body)
                return None
            ctype = (r.headers.get("content-type") or "").lower()
            if not r.content or len(r.content) < 300:
                _bg_note_error(f"Photoroom API returned empty/short content: {len(r.content or b'')} bytes")
                return None
            if (not ctype.startswith("image/")) and (r.content[:1] not in (b"\x89", b"\xff")):
                _bg_note_error(f"Photoroom API returned non-image content-type={ctype} body={(r.text or '')[:700]}")
                return None
            return bytes(r.content)
    except Exception as e:
        _bg_note_error(f"Photoroom API exception: {type(e).__name__}: {e}")
        log.warning("Photoroom API exception: %s", e)
        return None


def _normalize_photo_result(img_bytes: bytes) -> bytes:
    if Image is None:
        return img_bytes
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGB")
        max_side = int(BG_OUTPUT_MAX_SIDE or 1600)
        if max_side > 0 and max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        bio = BytesIO()
        im.save(bio, format="JPEG", quality=93, optimize=True, progressive=True)
        return bio.getvalue()
    except Exception as e:
        _bg_note_error(f"normalize photo result failed: {e}")
        return img_bytes


def _clean_bg_prompt_text(prompt: str) -> str:
    """Remove wording that makes AI draw a visible phone/mirror instead of just selfie-like perspective."""
    s = (prompt or "").strip()
    replacements = {
        "на телефон": "",
        "с телефона": "",
        "на смартфон": "",
        "со смартфона": "",
        "телефон": "камера",
        "смартфон": "камера",
        "phone": "camera",
        "smartphone": "camera",
        "mirror": "",
        "зеркало": "",
        "selfie stick": "",
        "селфи-палка": "",
    }
    for a, b in replacements.items():
        s = re.sub(re.escape(a), b, s, flags=re.IGNORECASE)
    s = re.sub(r"\s{2,}", " ", s).strip(" ,.;")
    return s


def _build_selfie_background_prompt(kind: str, prompt: str = "") -> str:
    kind = (kind or "custom").lower().strip()
    user_prompt = _clean_bg_prompt_text(prompt)
    preset_map = {
        "beach": (
            "a real photorealistic tropical beach background with ocean shoreline, sand, soft waves, "
            "natural sky and warm sunlight, realistic depth of field"
        ),
        "mountains": (
            "a real photorealistic mountain landscape background with distant mountains, natural sky, "
            "soft atmospheric perspective and realistic outdoor light"
        ),
        "nature": (
            "a real photorealistic outdoor nature background with greenery, trees or a park, "
            "natural daylight and believable depth of field"
        ),
        "roof": (
            "a real photorealistic rooftop terrace or city skyline background, realistic urban light, "
            "believable depth and natural perspective"
        ),
        "custom": user_prompt,
    }
    scene = user_prompt or preset_map.get(kind) or "a real photorealistic environment"
    base = (
        "Generate only a new background and keep the original main subject completely unchanged: "
        "do not alter the face, hair, clothes, body, pose, proportions or skin texture. "
        "The final image must look like a realistic real-life portrait/selfie taken in that location, "
        "with a natural eye-level camera perspective, realistic lighting matched to the subject, natural colors, "
        "believable depth of field and clean composition. "
        "Do not generate or show a phone, smartphone edge, mirror, selfie stick, window frame, black vertical bar, pole, "
        "extra foreground object, extra person, duplicate subject, extra hands, text, logo or watermark. "
        "No illustration, no cartoon, no painting, no anime, no CGI, no 3D render."
    )
    if user_prompt and kind != "custom":
        scene_part = f" Background scene: {scene}. Additional user details: {user_prompt}."
    else:
        scene_part = f" Background scene: {scene}."
    return (base + scene_part).strip()


def _should_use_photoroom_ai_background(kind: str, prompt: str = "") -> bool:
    if not PHOTOROOM_EDIT_ENABLED or not PHOTOROOM_API_KEY:
        return False
    kind = (kind or "").lower().strip()
    if kind in ("beach", "mountains", "nature", "roof", "custom"):
        return True
    return bool(prompt and kind not in ("white", "black", "blur"))


async def _photoroom_api_edit_background_bytes(img_bytes: bytes, kind: str = "custom", prompt: str = "") -> bytes | None:
    """Photoroom Image Editing API for photorealistic background replacement."""
    if not PHOTOROOM_API_KEY:
        _bg_note_error("Photoroom API key missing for AI background: set PHOTOROOM_API_KEY in Render Environment")
        return None
    if not PHOTOROOM_EDIT_ENABLED:
        _bg_note_error("Photoroom AI background is disabled by PHOTOROOM_EDIT_ENABLED=0")
        return None
    upload_bytes, upload_name, mime = _resize_image_bytes_for_bg_api(img_bytes, PHOTOROOM_INPUT_MAX_SIDE)
    url = f"{PHOTOROOM_EDIT_BASE_URL}{PHOTOROOM_EDIT_PATH}"
    headers = {"x-api-key": PHOTOROOM_API_KEY}
    bg_prompt = _build_selfie_background_prompt(kind, prompt)
    data = {
        "referenceBox": "originalImage",
        "background.prompt": bg_prompt,
        "background.expandPrompt.mode": PHOTOROOM_EDIT_EXPAND_PROMPT_MODE or "ai.never",
    }
    if PHOTOROOM_EDIT_NEGATIVE_PROMPT:
        data["background.negativePrompt"] = PHOTOROOM_EDIT_NEGATIVE_PROMPT
    timeout = httpx.Timeout(PHOTOROOM_EDIT_TIMEOUT_S, connect=20.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            files = {"imageFile": (upload_name, upload_bytes, mime)}
            r = await client.post(url, headers=headers, data=data, files=files)
            if r.status_code >= 400:
                body = (r.text or "")[:900]
                _bg_note_error(f"Photoroom edit API failed status={r.status_code} body={body}")
                log.warning("Photoroom edit API failed status=%s body=%s", r.status_code, body)
                return None
            ctype = (r.headers.get("content-type") or "").lower()
            if ctype.startswith("image/") and r.content and len(r.content) > 300:
                return bytes(r.content)
            out = await _image_bytes_from_response(r, client)
            if out:
                return out
            _bg_note_error(f"Photoroom edit API returned non-image content-type={ctype} body={(r.text or '')[:700]}")
            return None
    except Exception as e:
        _bg_note_error(f"Photoroom edit API exception: {type(e).__name__}: {e}")
        log.warning("Photoroom edit API exception: %s", e)
        return None


async def _removebg_api_remove_bytes(img_bytes: bytes) -> bytes | None:
    """Official remove.bg-compatible API primary path. Returns transparent PNG bytes."""
    if not REMOVE_BG_API_KEY:
        _bg_note_error("remove.bg API key missing: set REMOVE_BG_API_KEY in Render Environment")
        return None
    mime = sniff_image_mime(img_bytes) or "image/jpeg"
    url = f"{REMOVE_BG_BASE_URL}{REMOVE_BG_PATH}"
    headers = {"X-Api-Key": REMOVE_BG_API_KEY}
    data = {
        "size": REMOVE_BG_SIZE,
        "format": REMOVE_BG_FORMAT,
        "type": "auto",
    }
    timeout = httpx.Timeout(REMOVE_BG_TIMEOUT_S, connect=20.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            files = {"image_file": ("image.jpg", img_bytes, mime)}
            r = await client.post(url, headers=headers, data=data, files=files)
            if r.status_code >= 400:
                body = (r.text or "")[:700]
                _bg_note_error(f"remove.bg API failed status={r.status_code} body={body}")
                log.warning("remove.bg API failed status=%s body=%s", r.status_code, body)
                return None
            if not r.content or len(r.content) < 300:
                _bg_note_error(f"remove.bg API returned empty/short content: {len(r.content or b'')} bytes")
                return None
            return bytes(r.content)
    except Exception as e:
        _bg_note_error(f"remove.bg API exception: {type(e).__name__}: {e}")
        log.warning("remove.bg API exception: %s", e)
        return None


async def _comet_bria_remove_bg_bytes(img_bytes: bytes) -> bytes | None:
    """Remote fallback only. Main production path should be local rembg."""
    if not COMET_API_KEY:
        return None
    headers = {"Authorization": f"Bearer {COMET_API_KEY}"}
    mime = sniff_image_mime(img_bytes)
    paths: list[str] = []
    for p in (BG_COMET_REMOVE_PATH, "/v1/images/edits", "/v1/images/generations"):
        if p and p not in paths:
            paths.append(p)
    timeout = httpx.Timeout(BG_REMOVE_TIMEOUT_S, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for path in paths:
            url = f"{COMET_BASE_URL}{path}"
            try:
                files = {"image": ("image.png", img_bytes, mime or "application/octet-stream")}
                data = {
                    "model": BG_COMET_MODEL,
                    "response_format": "b64_json",
                    "transparent_background": "true",
                }
                r = await client.post(url, headers=headers, files=files, data=data)
                if r.status_code >= 400:
                    err = f"Comet BG remove failed path={path} status={r.status_code} body={r.text[:500]}"
                    log.warning(err)
                    _bg_note_error(err)
                    continue
                out = await _image_bytes_from_response(r, client)
                if out:
                    return out
            except Exception as e:
                msg = f"Comet background remove exception path={path}: {e}"
                log.warning(msg)
                _bg_note_error(msg)
    return None


async def _bria_direct_remove_bg_bytes(img_bytes: bytes) -> bytes | None:
    """Direct Bria fallback, only if BRIA_API_KEY is configured."""
    if not BRIA_API_KEY:
        return None
    mime = sniff_image_mime(img_bytes)
    headers_variants = [
        {"Authorization": f"Bearer {BRIA_API_KEY}"},
        {"api_token": BRIA_API_KEY},
        {"Authorization": f"Bearer {BRIA_API_KEY}", "api_token": BRIA_API_KEY},
    ]
    paths: list[str] = []
    for p in (BRIA_REMOVE_PATH, "/v1/background/remove", "/v1/remove_background", "/background/remove"):
        if p and p not in paths:
            paths.append(p)
    timeout = httpx.Timeout(BG_REMOVE_TIMEOUT_S, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for path in paths:
            url = f"{BRIA_BASE_URL}{path}"
            for headers in headers_variants:
                try:
                    files = {"image": ("image.png", img_bytes, mime or "application/octet-stream")}
                    r = await client.post(url, headers=headers, files=files)
                    if r.status_code >= 400:
                        _bg_note_error(f"Bria direct failed path={path} status={r.status_code} body={r.text[:400]}")
                        continue
                    out = await _image_bytes_from_response(r, client)
                    if out:
                        return out
                except Exception as e:
                    msg = f"Bria direct remove exception path={path}: {e}"
                    log.warning(msg)
                    _bg_note_error(msg)
    return None


def _normalize_transparent_png(img_bytes: bytes) -> bytes:
    if Image is None:
        return img_bytes
    try:
        im = Image.open(BytesIO(img_bytes)).convert("RGBA")
        max_side = int(BG_OUTPUT_MAX_SIDE or 1600)
        if max_side > 0 and max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        bio = BytesIO()
        im.save(bio, format="PNG", optimize=True, compress_level=6)
        return bio.getvalue()
    except Exception as e:
        _bg_note_error(f"normalize transparent png failed: {e}")
        return img_bytes

async def _remove_bg_bytes_primary(img_bytes: bytes) -> bytes | None:
    """
    Production background pipeline.
    Primary: Photoroom Remove Background API.
    Optional fallbacks are used only in provider=multi/auto. Local rembg remains disabled on Render Starter.
    """
    provider = (BG_PROVIDER or "photoroom-api-only").lower().strip()
    photoroom_only = provider in (
        "photoroom", "photoroom-api", "photoroom-api-only",
        "photoroom-only", "api", "api-only"
    )

    # 1) Stable production path: Photoroom API.
    if provider in ("auto", "multi", "photoroom", "photoroom-api", "photoroom-api-only", "photoroom-only", "api", "api-only"):
        out = await _photoroom_api_remove_bytes(img_bytes)
        if out:
            return _normalize_transparent_png(out)
        if photoroom_only:
            return None

    # 2) Optional legacy remove.bg-compatible fallback if explicitly configured.
    if provider in ("auto", "multi", "removebg", "remove.bg", "removebg-api", "removebg-api-only", "removebg-only"):
        out = await _removebg_api_remove_bytes(img_bytes)
        if out:
            return _normalize_transparent_png(out)
        if provider in ("removebg", "remove.bg", "removebg-api", "removebg-api-only", "removebg-only"):
            return None

    # 3) Optional Comet/Bria fallback only when provider allows remote fallback.
    remote_allowed = provider not in (
        "local-only", "rembg-only", "local", "rembg",
        "photoroom-api-only", "photoroom-only", "api-only"
    )
    if remote_allowed and provider in ("auto", "multi", "comet", "cometapi", "bria-comet", "bria/remove-background"):
        out = await _comet_bria_remove_bg_bytes(img_bytes)
        if out:
            return _normalize_transparent_png(out)

    if remote_allowed and provider in ("auto", "multi", "bria", "direct-bria", "bria-direct"):
        out = await _bria_direct_remove_bg_bytes(img_bytes)
        if out:
            return _normalize_transparent_png(out)

    # 4) Last-resort local rembg only if explicitly enabled; disabled in production on Render Starter.
    local_allowed = bool((not BG_DISABLE_LOCAL_REMBG) and LOCAL_REMBG_ENABLED and rembg_remove is not None and provider not in ("photoroom-api-only", "photoroom-only", "removebg-api-only", "removebg-only", "api-only"))
    if local_allowed:
        out = await _local_rembg_remove_bytes(img_bytes)
        if out:
            return _normalize_transparent_png(out)

    if not PHOTOROOM_API_KEY and provider in ("photoroom", "photoroom-api", "photoroom-api-only", "photoroom-only", "api", "api-only"):
        _bg_note_error("PHOTOROOM_API_KEY is not configured")
    if rembg_remove is None and not BG_DISABLE_LOCAL_REMBG:
        _bg_note_error(f"local rembg unavailable: import failed {REMBG_IMPORT_ERROR}")
    return None

def _fit_cover(im, size: tuple[int, int]):
    if ImageOps:
        return ImageOps.fit(im, size, method=Image.LANCZOS, centering=(0.5, 0.5))
    return im.resize(size, Image.LANCZOS)


def _gradient_background(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]):
    w, h = size
    bg = Image.new("RGB", size, top)
    if ImageDraw is None:
        return bg
    draw = ImageDraw.Draw(bg)
    for y in range(max(1, h)):
        t = y / max(1, h - 1)
        c = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=c)
    return bg



_REAL_BG_URLS = {
    # Реальные фотосцены, а не рисованные заглушки. Если сеть недоступна — ниже останется локальный fallback.
    "beach": "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1800&q=85",
    "mountains": "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?auto=format&fit=crop&w=1800&q=85",
    "nature": "https://images.unsplash.com/photo-1448375240586-882707db888b?auto=format&fit=crop&w=1800&q=85",
    "roof": "https://images.unsplash.com/photo-1480714378408-67cf0d13bc1f?auto=format&fit=crop&w=1800&q=85",
}


def _safe_cache_name(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", key)[:80] or "bg"


def _real_photo_background(size: tuple[int, int], kind: str):
    """Берёт настоящий фотофон из кэша/URL и кропит под размер объекта."""
    if Image is None or not BG_REALISTIC_BACKGROUNDS:
        return None
    kind = (kind or "").lower().strip()
    url = _REAL_BG_URLS.get(kind)
    if not url:
        return None
    try:
        os.makedirs(BG_CACHE_DIR, exist_ok=True)
        cache_path = os.path.join(BG_CACHE_DIR, _safe_cache_name(kind) + ".jpg")
        data = None
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 1024:
            with open(cache_path, "rb") as f:
                data = f.read()
        else:
            with httpx.Client(timeout=BG_BACKGROUND_TIMEOUT_S, follow_redirects=True) as client:
                r = client.get(url, headers={"User-Agent": "GPT5ProBot/1.0"})
                r.raise_for_status()
                data = r.content
            with contextlib.suppress(Exception):
                with open(cache_path, "wb") as f:
                    f.write(data)
        if not data:
            return None
        bg = Image.open(BytesIO(data)).convert("RGB")
        bg = _fit_cover(bg, size)
        # Лёгкое размытие и затемнение, чтобы объект не выглядел вклеенным слишком резко.
        if ImageFilter:
            bg = bg.filter(ImageFilter.GaussianBlur(radius=max(1.2, min(size) / 450)))
        return bg
    except Exception as e:
        _bg_note_error(f"real background download failed kind={kind}: {type(e).__name__}: {e}")
        log.warning("real background failed kind=%s: %s", kind, e)
        return None

def _make_local_background(size: tuple[int, int], kind: str, original_bytes: bytes | None = None, prompt: str = ""):
    w, h = size
    kind = (kind or "blur").lower()
    if kind in ("beach", "mountains", "nature", "roof"):
        real_bg = _real_photo_background(size, kind)
        if real_bg is not None:
            return real_bg
    if kind == "blur" and original_bytes and ImageFilter:
        base = Image.open(BytesIO(original_bytes)).convert("RGB")
        bg = _fit_cover(base, size)
        return bg.filter(ImageFilter.GaussianBlur(radius=max(18, min(w, h) // 18)))
    if kind == "white":
        return Image.new("RGB", size, (255, 255, 255))
    if kind == "black":
        return Image.new("RGB", size, (12, 12, 12))

    if kind == "beach":
        bg = _gradient_background(size, (112, 190, 235), (247, 222, 170))
        if ImageDraw:
            d = ImageDraw.Draw(bg)
            d.rectangle([0, int(h * 0.62), w, h], fill=(238, 205, 145))
            d.rectangle([0, int(h * 0.50), w, int(h * 0.64)], fill=(57, 163, 203))
            d.arc([int(w*0.68), int(h*0.08), int(w*0.88), int(h*0.28)], 0, 360, fill=(255, 230, 120), width=max(3, w//180))
        return bg

    if kind == "mountains":
        bg = _gradient_background(size, (120, 170, 225), (225, 235, 245))
        if ImageDraw:
            d = ImageDraw.Draw(bg)
            d.polygon([(0, h), (int(w*0.28), int(h*0.35)), (int(w*0.58), h)], fill=(90, 105, 115))
            d.polygon([(int(w*0.30), h), (int(w*0.62), int(h*0.28)), (w, h)], fill=(75, 92, 105))
            d.polygon([(int(w*0.18), int(h*0.52)), (int(w*0.28), int(h*0.35)), (int(w*0.39), int(h*0.54))], fill=(235, 238, 240))
            d.polygon([(int(w*0.51), int(h*0.45)), (int(w*0.62), int(h*0.28)), (int(w*0.76), int(h*0.48))], fill=(235, 238, 240))
        return bg

    if kind == "roof":
        bg = _gradient_background(size, (90, 120, 170), (30, 35, 55))
        if ImageDraw:
            d = ImageDraw.Draw(bg)
            for i in range(7):
                x0 = int(w * (i / 7.0))
                bw = max(18, w // 11)
                bh = int(h * (0.18 + (i % 4) * 0.08))
                d.rectangle([x0, h - bh, x0 + bw, h], fill=(36, 42, 60))
                for yy in range(h - bh + 12, h - 8, 26):
                    d.rectangle([x0 + 8, yy, x0 + bw - 8, yy + 5], fill=(240, 205, 110))
            d.rectangle([0, int(h*0.78), w, h], fill=(50, 52, 55))
        return bg

    # nature/custom fallback: спокойный зелёный фон с глубиной.
    bg = _gradient_background(size, (125, 190, 140), (35, 80, 50))
    if ImageDraw:
        d = ImageDraw.Draw(bg)
        for i in range(12):
            x = int(w * i / 11)
            y = int(h * (0.45 + (i % 3) * 0.07))
            r = max(30, w // 12)
            d.ellipse([x-r, y-r, x+r, y+r], fill=(45, 115, 65))
        d.rectangle([0, int(h*0.70), w, h], fill=(42, 95, 55))
    return bg


async def _compose_replace_bg(img_bytes: bytes, bg_kind: str = "blur", prompt: str = "") -> bytes | None:
    if Image is None:
        return None

    # 1) Preferred path for presets/custom text: ask Photoroom Editing API to build a photorealistic selfie-style background.
    if _should_use_photoroom_ai_background(bg_kind, prompt):
        ai_out = await _photoroom_api_edit_background_bytes(img_bytes, kind=bg_kind, prompt=prompt)
        if ai_out:
            return _normalize_photo_result(ai_out)
        _bg_note_error(f"AI replace background failed for kind={bg_kind}; falling back to local composition")

    # 2) Fallback: classic cutout + local composition.
    cutout_bytes = await _remove_bg_bytes_primary(img_bytes)
    if not cutout_bytes:
        return None
    fg = Image.open(BytesIO(cutout_bytes)).convert("RGBA")
    bg = _make_local_background(fg.size, bg_kind, original_bytes=img_bytes, prompt=prompt).convert("RGBA")
    # Мягкая тень под объектом делает композицию менее «наклейкой».
    try:
        alpha = fg.getchannel("A")
        shadow = Image.new("RGBA", fg.size, (0, 0, 0, 0))
        sh = alpha.filter(ImageFilter.GaussianBlur(radius=max(5, min(fg.size)//80))) if ImageFilter else alpha
        shadow.putalpha(sh.point(lambda p: int(p * 0.22)))
        bg.alpha_composite(shadow, dest=(max(2, fg.size[0]//90), max(2, fg.size[1]//90)))
    except Exception:
        pass
    bg.alpha_composite(fg)
    bio = BytesIO()
    bg.convert("RGB").save(bio, format="JPEG", quality=94, optimize=True, progressive=True)
    return bio.getvalue()


async def _pedit_removebg(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes):
    try:
        await update.effective_message.reply_text("🧼 Удаляю фон. Верну PNG с прозрачной подложкой.")
        out = await asyncio.wait_for(_remove_bg_bytes_primary(img_bytes), timeout=BG_ACTION_TIMEOUT_S)
        if not out:
            if rembg_remove is None:
                await update.effective_message.reply_text(
                    "❌ Не удалось удалить фон через Photoroom API. "
                    "Проверьте PHOTOROOM_API_KEY и лимиты тестового ключа. Последние ошибки:\n" + _bg_last_errors_text()
                )
            else:
                await update.effective_message.reply_text("❌ Не удалось удалить фон. Для точной причины запустите /diag_bg. Последние ошибки:\n" + _bg_last_errors_text())
            return
        bio = BytesIO(out)
        bio.name = "no_bg.png"
        await update.effective_message.reply_document(
            InputFile(bio),
            caption="Фон удалён ✅ PNG с прозрачной подложкой.",
            read_timeout=120,
            write_timeout=120,
            connect_timeout=30,
            pool_timeout=30,
        )
    except TimedOut as e:
        _bg_note_error(f"telegram upload timeout: {type(e).__name__}: {e}")
        await update.effective_message.reply_text(
            "❌ Фон удалён, но Telegram не успел принять PNG-файл. "
            "Я уменьшил размер файлов в новой версии; попробуйте ещё раз или отправьте фото меньшего размера."
        )
    except asyncio.TimeoutError:
        _bg_note_error(f"removebg action timeout after {BG_ACTION_TIMEOUT_S:.0f}s")
        await update.effective_message.reply_text("❌ Удаление фона заняло слишком много времени и было остановлено. Попробуйте фото меньшего размера или повторите позже. Последние ошибки:\n" + _bg_last_errors_text())
    except Exception as e:
        log.exception("removebg error: %s", e)
        _bg_note_error(f"removebg exception: {type(e).__name__}: {e}")
        await update.effective_message.reply_text("Не удалось удалить фон. Последние ошибки:\n" + _bg_last_errors_text())


async def _pedit_replacebg(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes, kind: str = "blur", prompt: str = ""):
    if Image is None:
        await update.effective_message.reply_text("Pillow не установлен.")
        return
    try:
        await update.effective_message.reply_text("🖼 Вырезаю объект и заменяю только фон, без перерисовки человека/предмета. Для пресетов и своего описания стараюсь сделать результат как фотореалистичное селфи на новом фоне.")
        out = await asyncio.wait_for(_compose_replace_bg(img_bytes, bg_kind=kind, prompt=prompt), timeout=BG_ACTION_TIMEOUT_S)
        if not out:
            await update.effective_message.reply_text("❌ Не удалось отделить объект от фона. Для точной причины запустите /diag_bg. Последние ошибки:\n" + _bg_last_errors_text())
            return
        bio = BytesIO(out)
        bio.name = f"replace_bg_{kind or 'custom'}.jpg"
        cap = "Фон заменён ✅ Объект оставлен из исходного фото."
        if prompt:
            cap += f"\nЗапрос фона: {prompt[:250]}"
        await update.effective_message.reply_photo(
            InputFile(bio),
            caption=cap,
            read_timeout=180,
            write_timeout=180,
            connect_timeout=30,
            pool_timeout=30,
        )
    except TimedOut as e:
        _bg_note_error(f"telegram replacebg upload timeout: {type(e).__name__}: {e}")
        await update.effective_message.reply_text(
            "⚠️ Telegram слишком долго принимал изображение после замены фона. "
            "Если фото уже появилось в чате — результат успешно доставлен. "
            "Если фото не появилось, повторите попытку ещё раз или отправьте фото меньшего размера."
        )
    except asyncio.TimeoutError:
        _bg_note_error(f"replacebg action timeout after {BG_ACTION_TIMEOUT_S:.0f}s")
        await update.effective_message.reply_text("❌ Замена фона заняла слишком много времени и была остановлена. Попробуйте фото меньшего размера или повторите позже. Последние ошибки:\n" + _bg_last_errors_text())
    except Exception as e:
        log.exception("replacebg error: %s", e)
        _bg_note_error(f"replacebg exception: {type(e).__name__}: {e}")
        await update.effective_message.reply_text("Не удалось заменить фон. Последние ошибки:\n" + _bg_last_errors_text())


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



# ───────── Face swap production helpers ─────────
_faceswap_target_cache = {}   # user_id -> bytes: photo where face must be replaced
_faceswap_source_cache = {}   # user_id -> bytes: face/reference photo
_faceswap_target_face_index_cache = {}  # user_id -> Segmind/API face index in target image
_faceswap_source_face_index_cache = {}  # user_id -> Segmind/API face index in source image
_faceswap_target_face_count_cache = {}  # user_id -> detected target faces count
_faceswap_source_face_count_cache = {}  # user_id -> detected source faces count
_faceswap_errors = []


def _faceswap_note_error(msg: str):
    try:
        msg = str(msg).strip()
        if not msg:
            return
        _faceswap_errors.append(msg[:1200])
        del _faceswap_errors[:-8]
        log.warning("faceswap: %s", msg)
    except Exception:
        pass


def _faceswap_last_errors_text() -> str:
    if not _faceswap_errors:
        return "ошибок пока нет"
    return "\n".join("• " + e for e in _faceswap_errors[-5:])


def _faceswap_cv2_status() -> str:
    if not FACESWAP_FACE_DETECTION_ENABLED:
        return "disabled_by_env"
    try:
        import cv2  # type: ignore
        ver = getattr(cv2, "__version__", "")
        if not hasattr(cv2, "CascadeClassifier"):
            return f"BROKEN {ver}: no CascadeClassifier".strip()
        if not hasattr(cv2, "data") or not getattr(cv2.data, "haarcascades", ""):
            return f"BROKEN {ver}: no haarcascades".strip()
        return f"ok {ver}".strip()
    except Exception as e:
        return f"FAILED {type(e).__name__}: {e}"


async def cmd_diag_face(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [
        f"🧪 FaceSwap diagnostic / {PATCH_VERSION}",
        f"FACESWAP_ENABLED={FACESWAP_ENABLED} provider={FACESWAP_PROVIDER} fallback={FACESWAP_FALLBACK_PROVIDER}",
        f"fast_provider={FACESWAP_FAST_PROVIDER} premium_provider={FACESWAP_PREMIUM_PROVIDER}",
        f"target_choice={FACESWAP_ASK_TARGET_FACE} source_choice={FACESWAP_ASK_SOURCE_FACE} strict_selected={FACESWAP_STRICT_SELECTED_FACE}",
        f"manual_choice_if_detection_fail={FACESWAP_MANUAL_CHOICE_IF_DETECTION_FAIL}",
        f"face_detection={FACESWAP_FACE_DETECTION_ENABLED} cv2={_faceswap_cv2_status()} detect_max={FACESWAP_DETECTION_MAX_SIDE} preview_max={FACESWAP_PREVIEW_MAX_SIDE}",
        f"PIAPI_API_KEY={'on' if PIAPI_API_KEY else 'off'} base={PIAPI_BASE_URL} model={PIAPI_FACE_MODEL} task={PIAPI_FACE_TASK_TYPE}",
        f"SEGMIND_API_KEY={'on' if SEGMIND_API_KEY else 'off'} base={SEGMIND_BASE_URL} fast={SEGMIND_FACESWAP_MODEL_FAST} premium={SEGMIND_FACESWAP_MODEL_PREMIUM}",
        f"timeout={FACESWAP_TIMEOUT_S}s poll={FACESWAP_POLL_DELAY_S}s input_max={FACESWAP_INPUT_MAX_SIDE} output_max={FACESWAP_OUTPUT_MAX_SIDE}",
        "Последние ошибки:",
        _faceswap_last_errors_text(),
    ]
    await update.effective_message.reply_text("\n".join(lines)[:3900])


def face_swap_quality_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⚡ Быстро (~${FACESWAP_FAST_COST_USD:.2f})", callback_data="faceswap:run:fast")],
        [InlineKeyboardButton(f"💎 Премиум (~${FACESWAP_PREMIUM_COST_USD:.2f})", callback_data="faceswap:run:premium")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="pedit:back")],
    ])


def _is_face_swap_request(text: str) -> bool:
    tl = (text or "").strip().lower().replace("ё", "е")
    return any(k in tl for k in (
        "замени лицо", "заменить лицо", "поменяй лицо", "поменять лицо", "подставь лицо", "вставь лицо",
        "face swap", "faceswap", "swap face", "replace face", "смена лица", "замена лица"
    ))


def _set_faceswap_wait_source(context, target_bytes: bytes):
    # Реальный user_id прокидываем отдельно в вызовах через _faceswap_target_cache.
    context.user_data["faceswap_flow"] = "await_source"


def _clear_faceswap_flow(context):
    for k in ("faceswap_flow", "awaiting_photo_for"):
        with contextlib.suppress(Exception):
            context.user_data.pop(k, None)


def _clear_faceswap_user_cache(user_id: int):
    for d in (
        _faceswap_target_cache, _faceswap_source_cache,
        _faceswap_target_face_index_cache, _faceswap_source_face_index_cache,
        _faceswap_target_face_count_cache, _faceswap_source_face_count_cache,
    ):
        with contextlib.suppress(Exception):
            d.pop(user_id, None)


def _faceswap_target_for(user_id: int) -> bytes | None:
    return _faceswap_target_cache.get(user_id)


def _faceswap_source_for(user_id: int) -> bytes | None:
    return _faceswap_source_cache.get(user_id)


def _faceswap_selected_target_index(user_id: int) -> int:
    return int(_faceswap_target_face_index_cache.get(user_id, 0) or 0)


def _faceswap_selected_source_index(user_id: int) -> int:
    return int(_faceswap_source_face_index_cache.get(user_id, 0) or 0)


def _resize_image_bytes_for_faceswap_api(img_bytes: bytes, max_side: int | None = None) -> tuple[bytes, str, str]:
    max_side = int(max_side or FACESWAP_INPUT_MAX_SIDE or 1600)
    mime = sniff_image_mime(img_bytes) or "image/jpeg"
    if Image is None or max_side <= 0:
        ext = ".jpg" if mime == "image/jpeg" else (".png" if mime == "image/png" else ".webp")
        return img_bytes, f"faceswap{ext}", mime
    try:
        im = Image.open(BytesIO(img_bytes))
        im = ImageOps.exif_transpose(im) if ImageOps else im
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        bio = BytesIO()
        im.save(bio, format="JPEG", quality=93, optimize=True, progressive=True)
        return bio.getvalue(), "faceswap.jpg", "image/jpeg"
    except Exception as e:
        _faceswap_note_error(f"faceswap input resize failed: {type(e).__name__}: {e}")
        ext = ".jpg" if mime == "image/jpeg" else (".png" if mime == "image/png" else ".webp")
        return img_bytes, f"faceswap{ext}", mime


def _b64_for_faceswap(img_bytes: bytes) -> str:
    b, _name, mime = _resize_image_bytes_for_faceswap_api(img_bytes, FACESWAP_INPUT_MAX_SIDE)
    raw = base64.b64encode(b).decode("ascii")
    if FACESWAP_IMAGE_DATA_URL:
        return f"data:{mime};base64,{raw}"
    return raw


def _normalize_output_image_bytes(img_bytes: bytes) -> bytes:
    if Image is None or not img_bytes or FACESWAP_OUTPUT_MAX_SIDE <= 0:
        return img_bytes
    try:
        im = Image.open(BytesIO(img_bytes))
        im = ImageOps.exif_transpose(im) if ImageOps else im
        if max(im.size) > FACESWAP_OUTPUT_MAX_SIDE:
            im.thumbnail((FACESWAP_OUTPUT_MAX_SIDE, FACESWAP_OUTPUT_MAX_SIDE), Image.LANCZOS)
        out = BytesIO()
        if im.mode in ("RGBA", "LA"):
            im.save(out, format="PNG", optimize=True)
        else:
            im = im.convert("RGB")
            im.save(out, format="JPEG", quality=94, optimize=True, progressive=True)
        return out.getvalue()
    except Exception:
        return img_bytes


def _detect_faces_for_choice(img_bytes: bytes) -> list[dict]:
    """Определение лиц для UI и выбора индексов.

    Важный практический момент: в реальных тестах провайдеры вели себя стабильнее,
    когда индексы лиц передавались в визуальном порядке слева→направо.
    Поэтому api_index здесь синхронизирован с display_index, а не с сортировкой по размеру.
    Дополнительно режем ложные срабатывания (мелкие боксы на одежде/фоне).
    """
    if not FACESWAP_FACE_DETECTION_ENABLED or Image is None:
        return []
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        def _iou(a: dict, b: dict) -> float:
            ax1, ay1, ax2, ay2 = a["x"], a["y"], a["x"] + a["w"], a["y"] + a["h"]
            bx1, by1, bx2, by2 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
            ix1, iy1 = max(ax1, bx1), max(ay1, by1)
            ix2, iy2 = min(ax2, bx2), min(ay2, by2)
            iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
            inter = iw * ih
            if inter <= 0:
                return 0.0
            union = a["area"] + b["area"] - inter
            return (inter / union) if union > 0 else 0.0

        im = Image.open(BytesIO(img_bytes))
        im = ImageOps.exif_transpose(im) if ImageOps else im
        im = im.convert("RGB")
        orig_w, orig_h = im.size
        img_area = max(1, orig_w * orig_h)
        scale = 1.0
        max_side = int(FACESWAP_DETECTION_MAX_SIDE or 1200)
        if max_side > 0 and max(orig_w, orig_h) > max_side:
            scale = max_side / float(max(orig_w, orig_h))
            im_det = im.resize((max(1, int(orig_w * scale)), max(1, int(orig_h * scale))), Image.LANCZOS)
        else:
            im_det = im
        arr = np.array(im_det)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            _faceswap_note_error("cv2 haarcascade_frontalface_default.xml not loaded")
            return []
        faces = cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5, minSize=(40, 40))
        items = []
        for (x, y, w, h) in faces:
            ox = int(round(x / scale)); oy = int(round(y / scale)); ow = int(round(w / scale)); oh = int(round(h / scale))
            if ow < 24 or oh < 24:
                continue
            area = ow * oh
            # слишком маленькие боксы почти всегда ложные срабатывания
            if area < max(1600, int(img_area * 0.004)):
                continue
            cx, cy = ox + ow / 2, oy + oh / 2
            items.append({"x": ox, "y": oy, "w": ow, "h": oh, "area": area, "cx": cx, "cy": cy})

        if not items:
            return []

        # NMS / дедупликация сильно перекрывающихся боксов
        dedup = []
        for f in sorted(items, key=lambda z: z["area"], reverse=True):
            if any(_iou(f, kept) >= 0.35 for kept in dedup):
                continue
            dedup.append(f)
        items = dedup

        if not items:
            return []

        # Если явно доминирует одно лицо (типичный селфи-источник),
        # отбрасываем мелкие ложные боксы на плече/фоне.
        largest = max(items, key=lambda z: z["area"])
        second_area = max([z["area"] for z in items if z is not largest] or [0])
        dominant = largest["area"] >= max(2.0 * second_area, int(img_area * 0.03))
        if dominant:
            filt = []
            for f in items:
                if f is largest:
                    filt.append(f)
                    continue
                if f["area"] >= largest["area"] * 0.28:
                    filt.append(f)
            items = filt

        # Итоговый порядок: слева направо, затем сверху вниз.
        # Такой же индекс передаём провайдеру.
        display = sorted(items, key=lambda f: (f["cx"], f["cy"]))[:8]
        for i, f in enumerate(display, 1):
            f["display_index"] = i
            f["api_index"] = i - 1
            if len(display) == 2:
                f["pos_label"] = "слева" if i == 1 else "справа"
            elif len(display) == 3:
                f["pos_label"] = ["слева", "центр", "справа"][i - 1]
            else:
                f["pos_label"] = f"лицо {i}"
        return display
    except Exception as e:
        _faceswap_note_error(f"face detection failed: {type(e).__name__}: {e}")
        return []


def _face_choice_preview_bytes(img_bytes: bytes, faces: list[dict], title: str = "Выберите лицо") -> bytes | None:
    if Image is None or ImageDraw is None or not faces:
        return None
    try:
        im = Image.open(BytesIO(img_bytes))
        im = ImageOps.exif_transpose(im) if ImageOps else im
        im = im.convert("RGB")
        scale = 1.0
        max_side = int(FACESWAP_PREVIEW_MAX_SIDE or 1200)
        if max_side > 0 and max(im.size) > max_side:
            scale = max_side / float(max(im.size))
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
        draw = ImageDraw.Draw(im)
        try:
            font_big = ImageFont.truetype("DejaVuSans-Bold.ttf", max(24, int(42 * scale)))
            font_small = ImageFont.truetype("DejaVuSans-Bold.ttf", max(14, int(22 * scale)))
        except Exception:
            font_big = None
            font_small = None
        # title strip
        draw.rectangle([0, 0, im.width, min(im.height, 44)], fill=(0, 0, 0))
        draw.text((12, 8), title, fill=(255, 255, 255), font=font_small)
        for f in faces:
            x = int(f["x"] * scale); y = int(f["y"] * scale); w = int(f["w"] * scale); h = int(f["h"] * scale)
            label = str(f.get("display_index") or f.get("api_index") or 0)
            # Жёлтая рамка + чёрная подложка номера хорошо видны в Telegram.
            for off in range(4):
                draw.rectangle([x-off, y-off, x+w+off, y+h+off], outline=(255, 221, 0))
            lx, ly = x, max(44, y - 42)
            draw.ellipse([lx, ly, lx + 42, ly + 42], fill=(255, 221, 0), outline=(0, 0, 0), width=2)
            draw.text((lx + 14, ly + 6), label, fill=(0, 0, 0), font=font_big)
        bio = BytesIO()
        im.save(bio, format="JPEG", quality=92, optimize=True)
        return bio.getvalue()
    except Exception as e:
        _faceswap_note_error(f"face choice preview failed: {type(e).__name__}: {e}")
        return None


def _face_choice_kb(stage: str, faces: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for f in faces[:8]:
        disp = int(f.get("display_index") or 0)
        api_idx = int(f.get("api_index") or 0)
        pos = str(f.get("pos_label") or "")
        text = f"{disp} — {pos}" if pos and not pos.startswith("лицо") else f"Лицо {disp}"
        row.append(InlineKeyboardButton(text, callback_data=f"faceswap:{stage}:{api_idx}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⬅️ Отмена", callback_data="pedit:back")])
    return InlineKeyboardMarkup(buttons)


def _manual_face_choice_kb(stage: str) -> InlineKeyboardMarkup:
    # Ручной выбор нужен, если детектор лиц недоступен/слабый или Telegram прислал сложное групповое фото.
    # Индексы передаются провайдерам как target_face_index/source_face_index.
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👈 Лицо слева", callback_data=f"faceswap:{stage}:0")],
        [InlineKeyboardButton("🎯 Лицо в центре", callback_data=f"faceswap:{stage}:1")],
        [InlineKeyboardButton("👉 Лицо справа", callback_data=f"faceswap:{stage}:2")],
        [InlineKeyboardButton("🤖 Авто / первое лицо", callback_data=f"faceswap:{stage}:0")],
        [InlineKeyboardButton("⬅️ Отмена", callback_data="pedit:back")],
    ])


async def _ask_faceswap_source_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["faceswap_flow"] = "await_source"
    await update.effective_message.reply_text(
        "🎭 Теперь пришлите фото лица, которое нужно вставить.\n\n"
        "Важно: используйте только свои изображения или изображения, на которые у вас есть право. "
        "Нельзя использовать функцию для обмана, шантажа, документов, интимного контента и вредоносных подделок."
    )


async def _maybe_choose_target_face(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, img: bytes):
    _faceswap_target_cache[user_id] = img
    faces = _detect_faces_for_choice(img)
    _faceswap_target_face_count_cache[user_id] = len(faces)
    _faceswap_target_face_index_cache[user_id] = 0
    if FACESWAP_ASK_TARGET_FACE and len(faces) > 1:
        context.user_data["faceswap_flow"] = "choose_target_face"
        preview = _face_choice_preview_bytes(img, faces, "Кого заменить? Выберите номер лица")
        text = "🎭 На фото найдено несколько лиц. Выберите, у какого человека заменить лицо."
        if preview:
            bio = BytesIO(preview); bio.name = "faces_target_choice.jpg"
            await update.effective_message.reply_photo(InputFile(bio), caption=text, reply_markup=_face_choice_kb("target", faces))
        else:
            await update.effective_message.reply_text(text, reply_markup=_face_choice_kb("target", faces))
        return
    if FACESWAP_ASK_TARGET_FACE and not faces and FACESWAP_MANUAL_CHOICE_IF_DETECTION_FAIL:
        # Если OpenCV/детектор не нашёл лица, не берём рандомный index 0 молча.
        # Даём пользователю ручной выбор: левое/центр/правое/авто.
        context.user_data["faceswap_flow"] = "choose_target_face"
        _faceswap_target_face_count_cache[user_id] = 3
        await update.effective_message.reply_text(
            "🎭 Не смог уверенно определить лица на фото. Выберите вручную, у какого человека заменить лицо:",
            reply_markup=_manual_face_choice_kb("target"),
        )
        return
    await _ask_faceswap_source_photo(update, context)


async def _maybe_choose_source_face(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, img: bytes):
    _faceswap_source_cache[user_id] = img
    faces = _detect_faces_for_choice(img)
    _faceswap_source_face_count_cache[user_id] = len(faces)
    _faceswap_source_face_index_cache[user_id] = 0
    if FACESWAP_ASK_SOURCE_FACE and len(faces) > 1:
        context.user_data["faceswap_flow"] = "choose_source_face"
        preview = _face_choice_preview_bytes(img, faces, "Чьё лицо взять? Выберите номер")
        text = "🎭 На фото-источнике найдено несколько лиц. Выберите, чьё лицо вставить."
        if preview:
            bio = BytesIO(preview); bio.name = "faces_source_choice.jpg"
            await update.effective_message.reply_photo(InputFile(bio), caption=text, reply_markup=_face_choice_kb("source", faces))
        else:
            await update.effective_message.reply_text(text, reply_markup=_face_choice_kb("source", faces))
        return
    if FACESWAP_ASK_SOURCE_FACE and not faces and FACESWAP_MANUAL_CHOICE_IF_DETECTION_FAIL:
        context.user_data["faceswap_flow"] = "choose_source_face"
        _faceswap_source_face_count_cache[user_id] = 3
        await update.effective_message.reply_text(
            "🎭 Не смог уверенно определить лицо-источник. Выберите вручную, чьё лицо взять:",
            reply_markup=_manual_face_choice_kb("source"),
        )
        return
    context.user_data["faceswap_flow"] = "ready"
    await update.effective_message.reply_text("🎭 Фото лица получено. Выберите качество замены:", reply_markup=face_swap_quality_kb())


async def _extract_image_bytes_from_json_or_response(resp: httpx.Response, client: httpx.AsyncClient) -> bytes | None:
    out = await _image_bytes_from_response(resp, client)
    if out:
        return out
    try:
        obj = resp.json()
    except Exception:
        return None
    url = _find_first_image_url(obj)
    if url:
        rr = await client.get(url, timeout=60.0)
        rr.raise_for_status()
        return bytes(rr.content)
    return None


async def _piapi_faceswap(target_img: bytes, source_face: bytes, quality: str = "fast", target_index: int = 0, source_index: int = 0) -> bytes | None:
    if not PIAPI_API_KEY:
        _faceswap_note_error("PIAPI_API_KEY missing")
        return None
    target_b64 = _b64_for_faceswap(target_img)
    source_b64 = _b64_for_faceswap(source_face)
    url = f"{PIAPI_BASE_URL}{PIAPI_FACE_CREATE_PATH}"
    headers = {"x-api-key": PIAPI_API_KEY, "X-API-Key": PIAPI_API_KEY, "Content-Type": "application/json", "Accept": "application/json"}
    payload = {
        "model": PIAPI_FACE_MODEL,
        "task_type": PIAPI_FACE_TASK_TYPE,
        "input": {
            "target_image": target_b64,
            "swap_image": source_b64,
            # Если PiAPI начнёт поддерживать явный индекс, эти поля уже будут переданы.
            "target_face_index": int(target_index or 0),
            "source_face_index": int(source_index or 0),
        },
    }
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            _faceswap_note_error(f"PiAPI create failed status={r.status_code} body={r.text[:900]}")
            return None
        try:
            obj = r.json()
        except Exception:
            obj = {}
        direct = await _extract_image_bytes_from_json_or_response(r, client)
        if direct:
            return _normalize_output_image_bytes(direct)
        data = obj.get("data") if isinstance(obj, dict) else None
        task_id = ""
        if isinstance(data, dict):
            task_id = str(data.get("task_id") or data.get("id") or "")
        task_id = task_id or str(obj.get("task_id") or obj.get("id") or "") if isinstance(obj, dict) else ""
        if not task_id:
            _faceswap_note_error(f"PiAPI create returned no task_id body={str(obj)[:900]}")
            return None
        deadline = time.monotonic() + max(30.0, FACESWAP_TIMEOUT_S)
        status_url = f"{PIAPI_BASE_URL}{PIAPI_FACE_STATUS_PATH.format(task_id=task_id)}"
        last_obj = None
        while time.monotonic() < deadline:
            await asyncio.sleep(max(1.0, FACESWAP_POLL_DELAY_S))
            rr = await client.get(status_url, headers=headers)
            if rr.status_code >= 400:
                _faceswap_note_error(f"PiAPI status failed status={rr.status_code} body={rr.text[:900]}")
                return None
            try:
                last_obj = rr.json()
            except Exception:
                last_obj = {}
            img = await _extract_image_bytes_from_json_or_response(rr, client)
            if img:
                return _normalize_output_image_bytes(img)
            data = last_obj.get("data") if isinstance(last_obj, dict) else None
            st = ""
            if isinstance(data, dict):
                st = str(data.get("status") or data.get("state") or "").lower()
            st = st or str(last_obj.get("status") or last_obj.get("state") or "").lower() if isinstance(last_obj, dict) else ""
            if st in ("failed", "error", "canceled", "cancelled"):
                _faceswap_note_error(f"PiAPI task failed status={st} body={str(last_obj)[:900]}")
                return None
        _faceswap_note_error(f"PiAPI task timeout after {FACESWAP_TIMEOUT_S:.0f}s task_id={task_id}")
        return None


async def _segmind_faceswap_v2(target_img: bytes, source_face: bytes, target_index: int = 0, source_index: int = 0) -> bytes | None:
    if not SEGMIND_API_KEY:
        _faceswap_note_error("SEGMIND_API_KEY missing")
        return None
    url = f"{SEGMIND_BASE_URL}/v1/{SEGMIND_FACESWAP_MODEL_FAST}"
    payload = {
        "source_img": _b64_for_faceswap(source_face),
        "target_img": _b64_for_faceswap(target_img),
        "input_faces_index": str(int(target_index or 0)),
        "source_faces_index": str(int(source_index or 0)),
        "face_restore": SEGMIND_FACE_RESTORE,
        "base64": False,
    }
    headers = {"x-api-key": SEGMIND_API_KEY, "Content-Type": "application/json", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=FACESWAP_TIMEOUT_S, follow_redirects=True) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            _faceswap_note_error(f"Segmind v2 failed status={r.status_code} body={r.text[:900]}")
            return None
        img = await _extract_image_bytes_from_json_or_response(r, client)
        if img:
            return _normalize_output_image_bytes(img)
        _faceswap_note_error(f"Segmind v2 no output body={r.text[:900]}")
        return None


async def _segmind_faceswap_v4(target_img: bytes, source_face: bytes, quality: str = "premium") -> bytes | None:
    if not SEGMIND_API_KEY:
        _faceswap_note_error("SEGMIND_API_KEY missing")
        return None
    url = f"{SEGMIND_BASE_URL}/v1/{SEGMIND_FACESWAP_MODEL_PREMIUM}"
    payload = {
        "source_image": _b64_for_faceswap(source_face),
        "target_image": _b64_for_faceswap(target_img),
        "model_type": "quality" if quality == "premium" else "speed",
        "swap_type": SEGMIND_FACE_SWAP_TYPE,
        "style_type": SEGMIND_FACE_STYLE_TYPE,
        "seed": int(time.time()) % 100000000,
        "image_format": "png",
        "image_quality": 95 if quality == "premium" else 90,
        "hardware": "fast",
        "base64": False,
    }
    headers = {"x-api-key": SEGMIND_API_KEY, "Content-Type": "application/json", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=FACESWAP_TIMEOUT_S, follow_redirects=True) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            _faceswap_note_error(f"Segmind v4 failed status={r.status_code} body={r.text[:900]}")
            return None
        img = await _extract_image_bytes_from_json_or_response(r, client)
        if img:
            return _normalize_output_image_bytes(img)
        _faceswap_note_error(f"Segmind v4 no output body={r.text[:900]}")
        return None


def _faceswap_provider_supports_indices(provider: str) -> bool:
    provider = (provider or "").lower().strip()
    # PiAPI/Qubico принимает поля target_face_index/source_face_index в payload;
    # Segmind v2 принимает input_faces_index/source_faces_index.
    return provider in ("piapi", "pi", "qubico", "segmind", "segmind-v2", "segmind2")


async def _run_faceswap_provider(provider: str, target_img: bytes, source_face: bytes, quality: str, target_index: int = 0, source_index: int = 0) -> bytes | None:
    provider = (provider or "").lower().strip()
    if provider in ("piapi", "pi", "qubico"):
        return await _piapi_faceswap(target_img, source_face, quality=quality, target_index=target_index, source_index=source_index)
    if provider in ("segmind", "segmind-v2", "segmind2"):
        return await _segmind_faceswap_v2(target_img, source_face, target_index=target_index, source_index=source_index)
    if provider in ("segmind-v4", "segmind4"):
        return await _segmind_faceswap_v4(target_img, source_face, quality=quality)
    _faceswap_note_error(f"unknown faceswap provider={provider}")
    return None


def _faceswap_provider_order(quality: str, user_id: int) -> list[str]:
    if quality == "premium":
        base = [FACESWAP_PREMIUM_PROVIDER, FACESWAP_FALLBACK_PROVIDER, "segmind-v2", FACESWAP_PROVIDER]
    else:
        base = [FACESWAP_FAST_PROVIDER, FACESWAP_PROVIDER, FACESWAP_FALLBACK_PROVIDER, "segmind-v2"]
    seen = []
    order = [p for p in base if p and not (p in seen or seen.append(p))]
    selected_multi = (_faceswap_target_face_count_cache.get(user_id, 0) or 0) > 1 or (_faceswap_source_face_count_cache.get(user_id, 0) or 0) > 1
    if FACESWAP_STRICT_SELECTED_FACE and selected_multi:
        indexed = [p for p in order if _faceswap_provider_supports_indices(p)]
        if indexed:
            return indexed
        _faceswap_note_error("strict target/source face choice needs Segmind faceswap-v2, but no indexed provider configured")
    return order


async def _faceswap_process(update: Update, context: ContextTypes.DEFAULT_TYPE, quality: str = "fast"):
    user_id = update.effective_user.id
    target = _faceswap_target_for(user_id)
    source = _faceswap_source_for(user_id)
    target_index = _faceswap_selected_target_index(user_id)
    source_index = _faceswap_selected_source_index(user_id)
    if not target or not source:
        await update.effective_message.reply_text("Нужны 2 фото: сначала фото, где заменить лицо, затем фото лица для вставки.", reply_markup=main_kb)
        return
    if not FACESWAP_ENABLED:
        await update.effective_message.reply_text("🎭 Замена лица временно отключена в настройках сервера.")
        return
    provider_order = _faceswap_provider_order(quality, user_id)

    await update.effective_message.reply_text(
        f"🎭 Запускаю замену лица ({'Премиум' if quality == 'premium' else 'Быстро'}). "
        f"Целевое лицо №{target_index + 1}. Лицо-источник №{source_index + 1}. "
        "Сохраняю исходное тело, одежду, фон и композицию. Обычно 10–90 секунд…"
    )

    async def _go():
        out = None
        used_provider = ""
        for provider in provider_order:
            try:
                out = await asyncio.wait_for(
                    _run_faceswap_provider(provider, target, source, quality, target_index=target_index, source_index=source_index),
                    timeout=FACESWAP_TIMEOUT_S + 20,
                )
                if out:
                    used_provider = provider
                    break
            except asyncio.TimeoutError:
                _faceswap_note_error(f"{provider} timeout after {FACESWAP_TIMEOUT_S:.0f}s")
            except Exception as e:
                _faceswap_note_error(f"{provider} exception: {type(e).__name__}: {e}")
        if not out:
            await update.effective_message.reply_text("❌ Не удалось заменить лицо. Последние ошибки:\n" + _faceswap_last_errors_text())
            return
        _cache_photo(user_id, out)
        bio = BytesIO(out)
        cap = f"🎭 Лицо заменено ✅ Режим: {'Премиум' if quality == 'premium' else 'Быстро'} · провайдер: {used_provider}. Результат сохранён как исходное фото для дальнейших действий."
        if FACESWAP_RESULT_AS_DOCUMENT:
            bio.name = "face_swap.png"
            await update.effective_message.reply_document(InputFile(bio), caption=cap, reply_markup=photo_quick_actions_kb())
        else:
            bio.name = "face_swap.jpg"
            await update.effective_message.reply_photo(InputFile(bio), caption=cap, reply_markup=photo_quick_actions_kb())
        _clear_faceswap_flow(context)
        _clear_faceswap_user_cache(user_id)

    est = FACESWAP_PREMIUM_COST_USD if quality == "premium" else FACESWAP_FAST_COST_USD
    await _try_pay_then_do(update, context, user_id, "img", est, _go, remember_kind=f"faceswap_{quality}")


async def _start_faceswap_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes | None = None):
    user_id = update.effective_user.id
    target = img_bytes or _get_cached_photo(user_id)
    if not target:
        context.user_data["faceswap_flow"] = "await_target"
        await update.effective_message.reply_text(
            "🎭 Замена лица. Пришлите фото, где нужно заменить лицо. Если на фото несколько людей, я попрошу выбрать нужного человека. Затем я попрошу фото лица для вставки."
        )
        return
    await _maybe_choose_target_face(update, context, user_id, target)

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
                await q.edit_message_text(f"Минимальная сумма пополнения: {MIN_RUB_FOR_INVOICE} ₽")
                return
            ok = await _send_invoice_rub("Пополнение баланса", "Единый кошелёк для перерасходов.", amount_rub, "t=3", update)
            await q.answer("Выставляю счёт…" if ok else "Не удалось выставить счёт", show_alert=not ok)
            return

        # TOPUP CRYPTO
        if data.startswith("topup:crypto:"):
            await q.answer()
            if not CRYPTO_PAY_API_TOKEN:
                await q.edit_message_text("Настройте CRYPTO_PAY_API_TOKEN для оплаты через CryptoBot.")
                return
            try:
                usd = float((data.split(":", 2)[-1] or "0").strip() or "0")
            except Exception:
                usd = 0.0
            if usd <= 0.0:
                await q.edit_message_text("Неверная сумма.")
                return
            inv_id, pay_url, usd_amount, asset = await _crypto_create_invoice(usd, asset="USDT", description="Wallet top-up")
            if not inv_id or not pay_url:
                await q.edit_message_text("Не удалось создать счёт в CryptoBot. Попробуйте позже.")
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
                await q.edit_message_text("Не нашёл счёт. Создайте новый.")
                return
            st = (inv.get("status") or "").lower()
            if st == "paid":
                usd_amount = float(inv.get("amount", 0.0))
                if (inv.get("asset") or "").upper() == "TON":
                    usd_amount *= TON_USD_RATE
                _wallet_total_add(update.effective_user.id, usd_amount)
                await q.edit_message_text(f"💳 Оплата получена. Баланс пополнен на ≈ ${usd_amount:.2f}.")
            elif st == "active":
                await q.answer("Платёж ещё не подтверждён", show_alert=True)
            else:
                await q.edit_message_text(f"Статус счёта: {st}")
            return

        # Подписка: выбор способа
        if data.startswith("buy:"):
            await q.answer()
            _, tier, months = data.split(":", 2)
            months = int(months)
            desc = f"Подписка {tier.upper()} на {months} мес."
            await q.edit_message_text(
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
                await q.edit_message_text(
                    f"✅ Подписка {tier.upper()} активирована до {until.strftime('%Y-%m-%d')}.\n"
                    f"Списано с баланса: ~${need_usd:.2f}."
                )
            else:
                await q.edit_message_text(
                    "Недостаточно средств на едином балансе.\nПополните баланс и повторите.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Пополнить баланс", callback_data="topup")]])
                )
            return

        # Выбор движка
        if data.startswith("engine:"):
            await q.answer()
            engine = data.split(":", 1)[1]
            if engine == "luma" and LUMA_TEMP_DISABLED:
                await q.edit_message_text("⚠️ Luma временно отключена и скрыта из меню. Используйте Sora 2, Kling, Images или другие доступные движки. Runway — только для оживления фото.")
                return
            username = (update.effective_user.username or "")
            if engine == "runway":
                await q.edit_message_text(
                    "✅ Runway включён только для оживления фото.\n"
                    "Загрузите фотографию и нажмите ✨ Оживить (Runway) или отправьте фото с подписью: "
                    "«оживи фото: лёгкая улыбка, движение камеры, 5 секунд, 9:16».\n\n"
                    "Для создания видео по тексту/голосу используйте Sora 2 или Kling."
                )
                return
            if is_unlimited(update.effective_user.id, username):
                await q.edit_message_text(
                    f"✅ Движок «{engine}» доступен без ограничений.\n"
                    f"Для text→video используйте Sora 2 или Kling. Runway — только оживление фото."
                )
                return

            if engine in ("gpt", "stt_tts", "midjourney", "sora", "kling"):
                await q.edit_message_text(
                    f"✅ Выбран «{engine}». Отправьте запрос текстом/фото. "
                    f"Для видео напишите: «создай видео … 5 секунд 16:9» — я предложу Sora 2 или Kling. Runway — только для оживления фото."
                )
                return

            est_cost = IMG_COST_USD if engine == "images" else (0.40 if engine == "luma" else max(1.0, RUNWAY_UNIT_COST_USD))
            map_engine = {"images": "img", "luma": "luma", "runway": "runway"}[engine]
            ok, offer = _can_spend_or_offer(update.effective_user.id, username, map_engine, est_cost)

            if ok:
                await q.edit_message_text(
                    "✅ Доступно. " +
                    ("Запустите: /img кот в очках" if engine == "images"
                     else "Для видео по тексту доступны Sora 2 и Kling. Runway используйте только после загрузки фото для оживления.")
                )
                return

            if offer == "ASK_SUBSCRIBE":
                await q.edit_message_text(
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
            await q.edit_message_text(
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
            await q.edit_message_text("Движки:", reply_markup=engines_kb())
            return

        if data.startswith("mode:set:"):
            await q.answer()
            mode = data.split(":")[-1]
            mode_set(update.effective_user.id, mode)
            if mode == "study":
                study_sub_set(update.effective_user.id, "explain")
                await q.edit_message_text("Режим «Учёба» включён. Выберите подрежим:", reply_markup=study_kb())
            elif mode == "photo":
                await q.edit_message_text("Режим «Фото» включён. Пришлите изображение — появятся быстрые кнопки.", reply_markup=photo_quick_actions_kb())
            elif mode == "docs":
                await q.edit_message_text("Режим «Документы». Пришлите PDF/DOCX/EPUB/TXT — сделаю конспект.")
            elif mode == "voice":
                await q.edit_message_text("Режим «Голос». Отправьте voice/audio. Озвучка ответов: /voice_on")
            else:
                await q.edit_message_text(f"Режим «{mode}» активирован.")
            return

        if data.startswith("study:set:"):
            await q.answer()
            sub = data.split(":")[-1]
            study_sub_set(update.effective_user.id, sub)
            await q.edit_message_text(f"Учёба → {sub}. Напишите тему/задание.", reply_markup=study_kb())
            return

        # Photo edits require cached image
        if data.startswith("pedit:"):
            await q.answer()
            img = _get_cached_photo(update.effective_user.id)
            if not img:
                await q.edit_message_text("Сначала пришлите фото, затем выберите действие.", reply_markup=photo_quick_actions_kb())
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
            if data == "pedit:back":
                context.user_data.pop("photo_flow", None)
                await q.message.reply_text("Фото-мастерская:", reply_markup=photo_quick_actions_kb()); return
            if data == "pedit:removebg":
                await _pedit_removebg(update, context, img); return
            if data == "pedit:replacebg":
                await q.message.reply_text("Выберите новый фон или напишите свой вариант. Для пресетов постараюсь сделать результат как реальное селфи на новом фоне:", reply_markup=background_presets_kb()); return
            if data == "pedit:faceswap":
                await _start_faceswap_flow(update, context, img); return
            if data.startswith("pedit:bg:"):
                kind = data.split(":")[-1]
                if kind == "custom":
                    _set_replacebg_wait_text(context)
                    await q.message.reply_text("Напишите, какой фон поставить. Я сохраню человека из исходного фото и постараюсь сделать результат как настоящее селфи в этом месте. Например: «дорогой офис с панорамными окнами», «пляж Самуи на закате» или «крыша небоскрёба ночью». ")
                    return
                await _pedit_replacebg(update, context, img, kind=kind); return
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
                await q.edit_message_text("Напишите одно предложение — что сгенерировать. Я сделаю картинку.")
                return
            if data == "pedit:vision":
                b64 = base64.b64encode(img).decode("ascii")
                mime = sniff_image_mime(img)
                ans = await ask_openai_vision("Опиши фото и текст на нём кратко.", b64, mime)
                await update.effective_message.reply_text(ans or "Готово.")
                return

        if data.startswith("faceswap:target:"):
            await q.answer()
            try:
                idx = int(data.split(":")[-1])
            except Exception:
                idx = 0
            user_id = update.effective_user.id
            _faceswap_target_face_index_cache[user_id] = max(0, idx)
            await q.message.reply_text(f"✅ Выбрано целевое лицо №{max(0, idx) + 1}. Теперь пришлите фото лица, которое нужно вставить.")
            context.user_data["faceswap_flow"] = "await_source"
            return

        if data.startswith("faceswap:source:"):
            await q.answer()
            try:
                idx = int(data.split(":")[-1])
            except Exception:
                idx = 0
            user_id = update.effective_user.id
            _faceswap_source_face_index_cache[user_id] = max(0, idx)
            context.user_data["faceswap_flow"] = "ready"
            await q.message.reply_text(f"✅ Выбрано лицо-источник №{max(0, idx) + 1}. Выберите качество замены:", reply_markup=face_swap_quality_kb())
            return

        if data.startswith("faceswap:run:"):
            await q.answer()
            quality = data.split(":")[-1]
            await _faceswap_process(update, context, quality=quality)
            return

        # Подтверждение выбора движка для видео
        if data.startswith("choose:"):
            await q.answer()
            _, engine, aid = data.split(":", 2)
            if engine == "runway":
                _pending_actions.pop(aid, None)
                await q.edit_message_text(
                    "⚠️ Runway для создания видео по тексту/голосу отключён. "
                    "Оставлены Sora 2 и Kling. Runway используется только для оживления фото."
                )
                return
            if engine == "luma" and LUMA_TEMP_DISABLED:
                _pending_actions.pop(aid, None)
                await q.edit_message_text("⚠️ Luma временно отключена. Выберите Sora 2 или Kling.")
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
        f"• BG remove: provider={BG_PROVIDER} photoroom={'✅' if bool(PHOTOROOM_API_KEY) else '❌'} local_rembg={'✅' if (LOCAL_REMBG_ENABLED and rembg_remove is not None) else '❌'}",
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



def _cleanup_sent_video_keys():
    now = time.time()
    stale = [k for k, ts in _SENT_VIDEO_KEYS.items() if (now - ts) > VIDEO_RESULT_DEDUPE_TTL_S]
    for k in stale:
        _SENT_VIDEO_KEYS.pop(k, None)


def _mark_video_sent_once(key: str) -> bool:
    if not key:
        return False
    _cleanup_sent_video_keys()
    if key in _SENT_VIDEO_KEYS:
        return True
    _SENT_VIDEO_KEYS[key] = time.time()
    return False


def _video_result_key(chat_id: int | str, task_id: str = "", url: str = "", content: bytes | None = None) -> str:
    base = f"{chat_id}|{task_id or ''}|{url or ''}"
    if content:
        try:
            digest = hashlib.sha1(content).hexdigest()
        except Exception:
            digest = ""
        base += f"|{digest}"
    return base

async def _reply_video_from_url(update: Update, client: httpx.AsyncClient, url: str, caption: str, task_id: str = ""):
    """
    Отправляет ОДИН результат в Telegram.
    По умолчанию — MP4 как document, чтобы Telegram не маркировал короткий ролик как GIF.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GPT5ProBot/1.0)",
        "Accept": "video/mp4,video/*,*/*;q=0.8",
    }

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
        log.warning("reply_video_from_url: local download failed: %s", e)

    chat_id = getattr(getattr(update, "effective_chat", None), "id", "na")
    dedupe_key = _video_result_key(chat_id, task_id=task_id, url=url, content=downloaded)
    if _mark_video_sent_once(dedupe_key):
        log.info("reply_video_from_url: duplicate suppressed task_id=%s", task_id)
        return

    if downloaded:
        if VIDEO_RESULT_SEND_AS_DOCUMENT:
            try:
                bio = BytesIO(downloaded)
                bio.name = "result.mp4"
                await update.effective_message.reply_document(document=InputFile(bio), caption=caption)
                return
            except Exception as e:
                log.warning("reply_video_from_url: document send failed: %s", e)
        try:
            bio = BytesIO(downloaded)
            bio.name = "result.mp4"
            await update.effective_message.reply_video(video=InputFile(bio), caption=caption, supports_streaming=True)
            return
        except Exception as e:
            log.warning("reply_video_from_url: video send failed: %s", e)
        try:
            bio = BytesIO(downloaded)
            bio.name = "result.mp4"
            await update.effective_message.reply_document(document=InputFile(bio), caption=caption)
            return
        except Exception as e:
            log.warning("reply_video_from_url: document send fallback failed: %s", e)

    if not VIDEO_RESULT_SEND_AS_DOCUMENT:
        try:
            await update.effective_message.reply_video(video=url, caption=caption, supports_streaming=True)
            return
        except Exception as e:
            log.warning("reply_video_from_url: telegram URL video send failed: %s", e)
    try:
        await update.effective_message.reply_document(document=url, caption=caption)
        return
    except Exception as e:
        log.warning("reply_video_from_url: telegram URL document send failed: %s", e)

    safe_url = (url or "")[:3500]
    await update.effective_message.reply_text(
        f"{caption}\n⚠️ Telegram не принял видеофайл напрямую, оставляю ссылку:\n{safe_url}",
        disable_web_page_preview=False,
    )

async def _reply_video_bytes(update: Update, content: bytes, caption: str, task_id: str = ""):
    if not content or len(content) < 512:
        raise RuntimeError(f"empty video bytes: {len(content or b'')} bytes")
    chat_id = getattr(getattr(update, "effective_chat", None), "id", "na")
    dedupe_key = _video_result_key(chat_id, task_id=task_id, content=content)
    if _mark_video_sent_once(dedupe_key):
        log.info("reply_video_bytes: duplicate suppressed task_id=%s", task_id)
        return
    bio = BytesIO(content)
    bio.name = "result.mp4"
    if VIDEO_RESULT_SEND_AS_DOCUMENT:
        await update.effective_message.reply_document(document=InputFile(bio), caption=caption)
        return
    await update.effective_message.reply_video(video=InputFile(bio), caption=caption, supports_streaming=True)

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

async def _poll_video_task_generic(
    update: Update,
    client: httpx.AsyncClient,
    headers: dict,
    base_url: str,
    status_paths: list[str],
    task_id: str,
    caption: str,
    max_wait_s: int = 1200,
    task_not_exist_soft_fail_s: int = 0,
    silent_soft_fail: bool = False,
) -> bool:
    """
    Универсальный polling для async-video задач.

    Важно для Comet/Runway: ответ task_not_exist может приходить не как финальная ошибка,
    а как стадия первичной инициализации задачи. Поэтому мы не считаем его мгновенным
    провалом. Но если он держится дольше task_not_exist_soft_fail_s, возвращаем False,
    чтобы верхний уровень мог переключиться на другой движок/модель.
    """
    started = time.time()
    task_not_exist_seen_at: float | None = None

    while True:
        last_body = ""
        soft_not_exist_seen_this_round = False

        for path in status_paths:
            url = f"{base_url}{path}".format(id=task_id)
            try:
                rs = await client.get(url, headers=headers, timeout=60.0)
                body_preview = _api_error_preview(rs)

                if rs.status_code >= 400:
                    last_body = f"{rs.status_code}: {body_preview}"

                    # CometAPI/Runway soft-state: task created, but status storage is not ready yet.
                    if "task_not_exist" in (body_preview or "").lower():
                        soft_not_exist_seen_this_round = True
                        if task_not_exist_seen_at is None:
                            task_not_exist_seen_at = time.time()
                        if task_not_exist_soft_fail_s and (time.time() - task_not_exist_seen_at) >= task_not_exist_soft_fail_s:
                            log.warning(
                                "%s: task_not_exist persisted %.1fs for task_id=%s; soft fallback",
                                caption, time.time() - task_not_exist_seen_at, task_id,
                            )
                            if not silent_soft_fail:
                                await update.effective_message.reply_text(
                                    f"⚠️ {caption}: задача слишком долго не появляется в Comet/Runway. Переключаюсь на резервный путь."
                                )
                            return False
                        continue

                    continue

                try:
                    js = rs.json() or {}
                except Exception:
                    js = {}

            except Exception as e:
                last_body = str(e)
                continue

            st = str(js.get("status") or js.get("state") or js.get("task_status") or "").lower()

            # Comet/Runway иногда отдаёт task_not_exist внутри JSON при 200 OK.
            if st == "task_not_exist" or "task_not_exist" in json.dumps(js, ensure_ascii=False).lower():
                soft_not_exist_seen_this_round = True
                last_body = json.dumps(js, ensure_ascii=False)[:700]
                if task_not_exist_seen_at is None:
                    task_not_exist_seen_at = time.time()
                if task_not_exist_soft_fail_s and (time.time() - task_not_exist_seen_at) >= task_not_exist_soft_fail_s:
                    log.warning(
                        "%s: task_not_exist JSON persisted %.1fs for task_id=%s; soft fallback",
                        caption, time.time() - task_not_exist_seen_at, task_id,
                    )
                    if not silent_soft_fail:
                        await update.effective_message.reply_text(
                            f"⚠️ {caption}: задача слишком долго не появляется в Comet/Runway. Переключаюсь на резервный путь."
                        )
                    return False
                continue

            url = _extract_first_url(js.get("output")) or _extract_first_url(js.get("assets")) or _extract_first_url(js)
            if st in ("completed", "succeeded", "success", "finished", "ready", "done", "succeed") or (url and not st):
                if not url:
                    # OpenAI/Sora Videos API часто возвращает completed без URL.
                    # Финальный MP4 надо забрать отдельным GET /v1/videos/{id}/content.
                    if "sora" in (caption or "").lower() or "/v1/videos" in " ".join(status_paths):
                        try:
                            content_url = f"{base_url.rstrip("/")}/v1/videos/{task_id}/content"
                            cr = await client.get(content_url, headers=headers, timeout=240.0, follow_redirects=True)
                            if cr.status_code < 400 and cr.content and "application/json" not in (cr.headers.get("content-type") or "").lower():
                                await _reply_video_bytes(update, cr.content, f"{caption} ✅", task_id=task_id)
                                return True
                            log.warning("%s content download failed: %s %s", caption, cr.status_code, _api_error_preview(cr))
                        except Exception as e:
                            log.warning("%s content download exception: %s", caption, e)
                    await update.effective_message.reply_text(f"⚠️ {caption}: задача готова, но ссылка/MP4 на видео не найдены.")
                    return True
                await _reply_video_from_url(update, client, url, f"{caption} ✅", task_id=task_id)
                return True
            if st in ("failed", "error", "canceled", "cancelled", "rejected"):
                if "sora" in (caption or "").lower() and is_sora_people_moderation_error(js):
                    await update.effective_message.reply_text(_sora_people_moderation_text())
                    return True
                await update.effective_message.reply_text(f"❌ {caption}: ошибка рендера.\n{json.dumps(js, ensure_ascii=False)[:900]}")
                return True

        if time.time() - started > max_wait_s:
            # Для Runway/Comet timeout должен дать шанс верхнему fallback-уровню.
            if task_not_exist_seen_at is not None and silent_soft_fail:
                log.warning("%s: timeout with task_not_exist for task_id=%s; soft fallback", caption, task_id)
                return False
            await update.effective_message.reply_text(f"⌛ {caption}: время ожидания вышло. Последний ответ: {last_body[:700]}")
            return False

        # Если все пути дали только мягкий task_not_exist — просто ждём следующий цикл.
        await asyncio.sleep(VIDEO_POLL_DELAY_S)

async def _create_and_poll_i2v(
    update: Update,
    base_url: str,
    api_key: str,
    create_payloads: list[tuple[str, dict]],
    status_paths: list[str],
    caption: str,
    task_not_exist_soft_fail_s: int = 0,
    silent_soft_fail: bool = False,
) -> bool:
    if not api_key:
        await update.effective_message.reply_text(f"❌ {caption}: API-ключ не задан в ENV.")
        return True

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
                    or js.get("taskId")
                    or js.get("taskID")
                    or js.get("request_id")
                    or js.get("uuid")
                    or ""
                ).strip()

                if not task_id and isinstance(js.get("data"), dict):
                    d = js.get("data") or {}
                    task_id = str(
                        d.get("id")
                        or d.get("task_id")
                        or d.get("generation_id")
                        or d.get("video_id")
                        or d.get("taskId")
                        or d.get("taskID")
                        or d.get("request_id")
                        or d.get("uuid")
                        or ""
                    ).strip()

                if not task_id and isinstance(js.get("result"), dict):
                    d = js.get("result") or {}
                    task_id = str(
                        d.get("id")
                        or d.get("task_id")
                        or d.get("generation_id")
                        or d.get("video_id")
                        or d.get("taskId")
                        or d.get("taskID")
                        or d.get("request_id")
                        or d.get("uuid")
                        or ""
                    ).strip()

                if not task_id:
                    last_err = f"POST {path}: нет id задачи в ответе {json.dumps(js, ensure_ascii=False)[:700]}"
                    all_errors.append(last_err)
                    continue

                await update.effective_message.reply_text(f"⏳ {caption}: задача принята, ожидаю результат…")
                log.info("%s accepted: path=%s task_id=%s response=%s", caption, path, task_id, json.dumps(js, ensure_ascii=False)[:1200])

                return await _poll_video_task_generic(
                    update,
                    client,
                    headers,
                    base_url,
                    status_paths,
                    task_id,
                    caption,
                    max_wait_s=max(LUMA_MAX_WAIT_S, RUNWAY_MAX_WAIT_S),
                    task_not_exist_soft_fail_s=task_not_exist_soft_fail_s,
                    silent_soft_fail=silent_soft_fail,
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
    if "invalid api channeltype" in (details or "").lower():
        await update.effective_message.reply_text(
            f"⚠️ {caption}: у текущего провайдера/канала Sora сейчас недоступна (invalid api channelType)."
        )
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
        # По факту Comet/OpenAI proxy в ваших логах ожидает input_reference как СТРОКУ,
        # а не как объект. Поэтому пробуем в первую очередь string data-url,
        # затем string без seconds, затем multipart-файл как запасной вариант.
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

        # 1) Основной вариант: input_reference как string (data URL) + seconds + size.
        _add_json({
            "model": SORA_MODEL,
            "prompt": prompt,
            "input_reference": sora_data_url,
            "seconds": str(d),
            "size": size,
        })

        # 2) То же без seconds — если канал сам нормализует длительность.
        _add_json({
            "model": SORA_MODEL,
            "prompt": prompt,
            "input_reference": sora_data_url,
            "size": size,
        })

        # 3) Запасной вариант через публичный Telegram URL, если proxy не любит data URL.
        if tg_url and tg_url.startswith("https://"):
            _add_json({
                "model": SORA_MODEL,
                "prompt": prompt,
                "input_reference": tg_url,
                "seconds": str(d),
                "size": size,
            })
            _add_json({
                "model": SORA_MODEL,
                "prompt": prompt,
                "input_reference": tg_url,
                "size": size,
            })

        # 4) Multipart-вариант как запасной fallback.
        _add_multipart(str(d))
        _add_multipart(None)

        sora_ok = await _create_and_poll_i2v(
            update,
            COMET_BASE_URL,
            SORA_API_KEY,
            payloads,
            [SORA_STATUS_PATH, "/v1/videos/{id}", "/v1/tasks/{id}"],
            "Sora 2 image→video (без людей)",
        )
        if (not sora_ok) and SORA_AUTO_FALLBACK_KLING:
            await update.effective_message.reply_text(
                "↪️ Sora сейчас недоступна или не создала задачу. Переключаюсь на Kling image→video как резерв."
            )
            await _run_comet_i2v(update, context, "kling", img_bytes, prompt, duration_s, aspect)
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
        # Основной формат Runway API 2024-11-06.
        payloads.append((RUNWAY_COMET_CREATE_PATH, {
            "model": model,
            "promptImage": data_url,
            "promptText": prompt,
            "duration": duration,
            "ratio": ratio,
            "watermark": False,
        }))
        # Формат promptImage как массив с position=first — эквивалентен string и стабильнее на некоторых прокси.
        payloads.append((RUNWAY_COMET_CREATE_PATH, {
            "model": model,
            "promptImage": [{"uri": data_url, "position": "first"}],
            "promptText": prompt,
            "duration": duration,
            "ratio": ratio,
            "watermark": False,
        }))
        # snake_case fallback для совместимости с разными прокси.
        payloads.append((RUNWAY_COMET_CREATE_PATH, {
            "model": model,
            "prompt_image": data_url,
            "prompt_text": prompt,
            "duration": duration,
            "ratio": ratio,
            "watermark": False,
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
                "watermark": False,
            }))

    return await _create_and_poll_i2v(
        update,
        COMET_BASE_URL,
        COMET_API_KEY,
        payloads,
        [RUNWAY_COMET_STATUS_PATH, "/runwayml/v1/tasks/{id}", "/v1/tasks/{id}"],
        "Runway/Comet image→video",
        task_not_exist_soft_fail_s=RUNWAY_TASK_NOT_EXIST_FALLBACK_S,
        silent_soft_fail=True,
    )

# ───────── Runway: анимация загруженного фото (image→video) ─────────
async def _run_runway_animate_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, img_bytes: bytes, prompt: str, duration_s: int, aspect: str):
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VIDEO)
    prompt = (prompt or "animate the input photo with subtle camera motion, lifelike micro-movements").strip()
    seconds = _duration_for_engine("runway", duration_s)
    ratio = _ratio_for_aspect(aspect)

    # Предпочтительный путь: Runway через CometAPI, если COMET_API_KEY есть.
    runway_comet_failed_soft = False
    try:
        if await _run_runway_comet_animate_photo(update, context, img_bytes, prompt, seconds, aspect):
            return
        runway_comet_failed_soft = True
    except Exception as e:
        runway_comet_failed_soft = True
        log.warning("Runway Comet fallback to direct because of error: %s", e)

    # Если официального Runway ключа нет, а Comet/Runway завис на task_not_exist,
    # автоматически переводим оживление на Kling, чтобы пользователь получил результат, а не таймаут.
    if not RUNWAY_API_KEY:
        if RUNWAY_AUTO_FALLBACK_KLING and COMET_API_KEY:
            await update.effective_message.reply_text(
                "⚠️ Runway/Comet слишком долго не отдаёт статус задачи. Переключаюсь на резервный Kling image→video…"
            )
            await _run_comet_i2v(update, context, "kling", img_bytes, prompt, seconds, aspect)
            return
        await update.effective_message.reply_text(
            "❌ Runway: нет RUNWAY_API_KEY, а Comet/Runway не дал результат. "
            "Добавьте RUNWAY_API_KEY или используйте Kling."
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

    # Замена лица: отдельный двухшаговый режим.
    if _is_face_swap_request(text):
        _clear_medicine_wait(context)
        with contextlib.suppress(Exception):
            _mode_track_set(update.effective_user.id, "")
        await _start_faceswap_flow(update, context, _get_cached_photo(update.effective_user.id))
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

        est_sora = SORA_PRO_UNIT_COST_USD if "pro" in (SORA_MODEL or "").lower() else SORA_UNIT_COST_USD
        est_kling = KLING_UNIT_COST_USD

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"🎞 Sora 2 (~${est_sora:.2f})",
                    callback_data=f"choose:sora:{aid}",
                ),
                InlineKeyboardButton(
                    f"🎬 Kling (~${est_kling:.2f})",
                    callback_data=f"choose:kling:{aid}",
                ),
            ],
        ])

        await update.effective_message.reply_text(
            f"Что использовать?\n"
            f"Длительность: {duration} c • Аспект: {aspect}\n"
            f"Запрос: «{prompt}»\n\n"
            f"Luma временно скрыта; для text→video доступны Sora 2 и Kling. Runway — только оживление фото.",
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

        if mt.startswith("image/"):
            _cache_photo(update.effective_user.id, raw, getattr(tg_file, "file_path", "") or "")

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

            if context.user_data.get("photo_flow") == "replacebg_menu":
                context.user_data.pop("photo_flow", None)
                await update.effective_message.reply_text(
                    "🖼 Изображение получено. Выберите новый фон или напишите свой вариант текстом:",
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
        "Здесь быстрые творческие сценарии: оживить фотографию, заменить лицо, удалить или заменить фон, "
        "сделать Reels/Shorts, создать мини-фильм, придумать идеи, сценарий, игру или квиз.\n\n"
        "Выбери действие ниже или напиши свободный запрос."
    )
    await update.effective_message.reply_text(txt, parse_mode="Markdown", reply_markup=_fun_quick_kb())

# ───── Клавиатура «Развлечения» с новыми кнопками ─────
def _fun_quick_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🪄 Оживить фото", callback_data="fun:revive")],
        [InlineKeyboardButton("🎭 Замена лица на фото", callback_data="fun:faceswap")],
        [InlineKeyboardButton("🧼 Удалить фон на фото", callback_data="fun:removebg")],
        [InlineKeyboardButton("🖼 Заменить фон на фото", callback_data="fun:replacebg")],
        [InlineKeyboardButton("📱 Сделать Reels / Shorts", callback_data="fun:reels")],
        [InlineKeyboardButton("🎞 Создать мини-фильм", callback_data="fun:film")],
        [InlineKeyboardButton("🎬 Сценарий / раскадровка", callback_data="fun:storyboard")],
        [InlineKeyboardButton("🎮 Игры / квиз", callback_data="fun:quiz")],
        [InlineKeyboardButton("🎭 Идеи для досуга", callback_data="fun:ideas")],
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

    if action == "faceswap":
        await q.answer("Замена лица")
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "faceswap")
        await _start_faceswap_flow(update, context, _get_cached_photo(q.from_user.id))
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
            await q.edit_message_text("🧼 Пришлите фото — удалю фон и верну PNG с прозрачной подложкой.", reply_markup=_fun_quick_kb())
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
            await q.edit_message_text("🖼 Пришлите фото. После загрузки я покажу варианты фона: пляж, горы, природа, город или свой текст.", reply_markup=_fun_quick_kb())
        return

    if action == "revive":
        if await _try_call("revive_old_photo_flow", "do_revive_photo"):
            return
        _set_waiting_photo_revival(update, context)
        await q.answer("Оживление фото")
        await q.edit_message_text(_fun_revive_help_text(), parse_mode="Markdown", reply_markup=_fun_quick_kb())
        return

    if action in {"smartreels", "reels"}:
        if await _try_call("smart_reels_from_video", "video_sense_reels"):
            return
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "fun_reels")
        context.user_data["awaiting_reels_material"] = True
        await q.answer("Reels / Shorts")
        await q.edit_message_text(_fun_reels_help_text(), parse_mode="Markdown", reply_markup=_fun_quick_kb())
        return

    if action == "film":
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "fun_film")
        context.user_data["awaiting_film_material"] = True
        await q.answer("Создать фильм")
        await q.edit_message_text(_fun_film_help_text(), parse_mode="Markdown", reply_markup=_fun_quick_kb())
        return

    if action == "clip":
        if await _try_call("start_runway_flow", "luma_make_clip", "runway_make_clip"):
            return
        _clear_transient_flows(context)
        _set_mode_clean(q.from_user.id, "Развлечения", "fun_reels")
        context.user_data["awaiting_reels_material"] = True
        await q.answer()
        await q.edit_message_text(_fun_reels_help_text(), parse_mode="Markdown", reply_markup=_fun_quick_kb())
        return

    if action == "img":
        if await _try_call("cmd_img", "midjourney_flow", "images_make"):
            return
        await q.answer()
        await q.edit_message_text("Введи /img и тему картинки, или пришли рефы.", reply_markup=_fun_quick_kb())
        return

    if action == "storyboard":
        if await _try_call("start_storyboard", "storyboard_make"):
            return
        await q.answer()
        await q.edit_message_text("Напиши тему шорта — накидаю структуру и раскадровку.", reply_markup=_fun_quick_kb())
        return

    if action in {"ideas", "quiz", "speech", "free", "back"}:
        await q.answer()
        await q.edit_message_text(
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
        "• 🖼 Изображения: анализ/описание, удаление и замена фона, замена лица, ретушь, outpaint.\n"
        "• ✨ Оживление фото: загрузи фото — можно выбрать Runway, Sora 2 или Kling.\n"
        "• 🎞 Видео: разбор смысла, таймкоды, *Reels из длинного видео*, идеи/скрипт, субтитры.\n"
        "• 🎧 Аудио/книги: транскрипция, тезисы, план.\n"
        "• 🩺 Медицина: выписки, анамнез, заключения, анализы, снимки, МРТ/КТ — справочный разбор и вопросы врачу.\n\n"
        "_Подсказки:_ просто загрузите файл или пришлите ссылку + короткое ТЗ. "
        "Для фото — можно нажать «✨ Оживить», для видео — «🎬 Reels из длинного видео»."
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
    app.add_handler(CommandHandler("diag_bg",      cmd_diag_bg))
    app.add_handler(CommandHandler("diag_face",    cmd_diag_face))
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

    # Кнопки в приоритетной группе (0), чтобы они срабатывали раньше любых общих обработчиков
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
                       filters.Regex(BTN_MED))
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
