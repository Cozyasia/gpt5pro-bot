# -*- coding: utf-8 -*-
"""
GPT5 PRO Bot — production single-file bot
Features:
- Multilang UI (ru/en/th/zh/ar optional)
- Chat (OpenRouter/OpenAI)
- Voice -> STT (OpenAI Whisper)
- Text -> Video: Kling (Comet), Luma (Comet)
- Photo -> Video: Runway image2video (Comet)  ✅ FIXED animate photo
- Music: Suno text2music
- Plans via CryptoBot
- SQLite KV + subs + spend
- Anti-spam + one-active-job lock + TTL cleanup
"""

import os
import re
import json
import time
import uuid
import base64
import logging
import asyncio
import sqlite3
import threading
from io import BytesIO
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, List

import httpx

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InputFile,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatAction

# =============================
# Logging
# =============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt5pro_bot")

# =============================
# ENV helpers
# =============================
def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(key)
    if v is None or v == "":
        return default
    return v

def _env_int(key: str, default: int) -> int:
    try:
        return int(float(os.getenv(key, str(default))))
    except Exception:
        return default

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except Exception:
        return default

def _env_bool(key: str, default: bool = False) -> bool:
    v = (_env(key, "1" if default else "0") or "").strip().lower()
    return v not in ("0", "false", "no", "off", "")

# =============================
# Telegram / General
# =============================
TELEGRAM_BOT_TOKEN = (_env("TELEGRAM_BOT_TOKEN") or _env("BOT_TOKEN") or "").strip()
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN (or BOT_TOKEN) is not set")

APP_URL = (_env("APP_URL") or _env("PUBLIC_URL") or "").strip()
PORT = _env_int("PORT", 10000)

WEBHOOK_PATH = (_env("WEBHOOK_PATH") or "/telegram").strip()
WEBHOOK_SECRET = (_env("WEBHOOK_SECRET") or _env("TELEGRAM_WEBHOOK_SECRET") or "").strip()

# =============================
# HTTP / timeouts
# =============================
HTTP_TIMEOUT = _env_float("HTTP_TIMEOUT", 60.0)
VIDEO_POLL_DELAY_S = _env_int("VIDEO_POLL_DELAY_S", 5)

# =============================
# Comet API
# =============================
COMET_API_KEY = (
    (_env("COMET_API_KEY") or "")
    or (_env("COMETAPI_KEY") or "")
    or (_env("SORA_API_KEY") or "")
).strip()
COMET_BASE_URL = (_env("COMET_BASE_URL") or _env("KLING_BASE_URL") or "https://api.cometapi.com").rstrip("/")

# Engines toggles
KLING_ENABLED = _env_bool("KLING_ENABLED", True)
LUMA_ENABLED  = _env_bool("LUMA_ENABLED", True)
RUNWAY_ENABLED = _env_bool("RUNWAY_ENABLED", True)

# =============================
# Luma (direct key exists, but we will use Comet for video to be consistent)
# =============================
LUMA_API_KEY = (_env("LUMA_API_KEY") or "").strip()  # optional, not used in Comet-mode
LUMA_MODEL = (_env("LUMA_MODEL") or "ray-2").strip()

# =============================
# Runway (Comet)
# =============================
RUNWAY_MODEL = (_env("RUNWAY_MODEL") or "gen3a_turbo").strip()
RUNWAY_DURATION_S = _env_int("RUNWAY_DURATION_S", 5)
RUNWAY_RATIO = (_env("RUNWAY_RATIO") or "16:9").strip()

# =============================
# Sora (OpenAI provider per ENV)
# =============================
SORA_ENABLED = _env_bool("SORA_ENABLED", True)
SORA_PROVIDER = (_env("SORA_PROVIDER") or "openai").strip().lower()
SORA_MODEL = (_env("SORA_MODEL") or "sora-1").strip()

# =============================
# Suno
# =============================
SUNO_ENABLED = _env_bool("SUNO_ENABLED", True)
SUNO_API_KEY = (_env("SUNO_API_KEY") or "").strip()
SUNO_MODEL = (_env("SUNO_MODEL") or "v3").strip()

# =============================
# OpenAI / OpenRouter text + STT
# =============================
TEXT_PROVIDER = (_env("TEXT_PROVIDER") or "openai").strip().lower()

OPENAI_API_KEY = (_env("OPENAI_API_KEY") or "").strip()
OPENAI_BASE_URL = (_env("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")

OPENROUTER_API_KEY = (_env("OPENROUTER_API_KEY") or "").strip().replace("\n", "").replace('"', "").strip()
OPENROUTER_SITE_URL = (_env("OPENROUTER_SITE_URL") or "").strip()
OPENROUTER_APP_NAME = (_env("OPENROUTER_APP_NAME") or "GPT5PRO Bot").strip()

OPENAI_MODEL = (_env("OPENAI_MODEL") or "gpt-4o-mini").strip()
WHISPER_MODEL = (_env("WHISPER_MODEL") or "whisper-1").strip()

# =============================
# Costs (estimates)
# =============================
KLING_UNIT_COST_USD = _env_float("KLING_UNIT_COST_USD", 0.80)
LUMA_UNIT_COST_USD  = _env_float("LUMA_UNIT_COST_USD", 0.40)

# =============================
# Simple DB (SQLite)
# =============================
DB_PATH = _env("DB_PATH") or "bot.db"

def db_connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

_db = db_connect()
_db_lock = threading.Lock()

def db_exec(sql: str, params: tuple = ()):
    with _db_lock:
        cur = _db.cursor()
        cur.execute(sql, params)
        _db.commit()
        return cur

def db_init():
    db_exec("""
        CREATE TABLE IF NOT EXISTS kv (
            k TEXT PRIMARY KEY,
            v TEXT
        )
    """)
    db_exec("""
        CREATE TABLE IF NOT EXISTS spend (
            user_id INTEGER,
            engine TEXT,
            usd REAL,
            ts INTEGER
        )
    """)
    db_exec("""
        CREATE TABLE IF NOT EXISTS subs (
            user_id INTEGER PRIMARY KEY,
            tier TEXT,
            ts INTEGER
        )
    """)

db_init()

def kv_get(key: str, default: Optional[str] = None) -> Optional[str]:
    row = db_exec("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return (row["v"] if row else default)

def kv_set(key: str, value: str):
    db_exec("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (key, value))

# =============================
# Language system
# =============================
LANG_AVAILABLE = (_env("LANG_AVAILABLE") or "ru,en,th,zh,ar").strip()
LANGS = {}
for x in [s.strip() for s in LANG_AVAILABLE.split(",") if s.strip()]:
    LANGS[x] = x

LANG_LABELS = {
    "ru": "Русский",
    "en": "English",
    "th": "ไทย",
    "zh": "中文",
    "ar": "العربية",
}
DEFAULT_LANG = (_env("LANG_DEFAULT") or _env("DEFAULT_LANG") or "ru").strip()

def get_lang(user_id: int) -> str:
    v = kv_get(f"lang:{user_id}", None)
    if v in LANGS:
        return v
    return DEFAULT_LANG if DEFAULT_LANG in LANGS else "ru"

def set_lang(user_id: int, lang: str):
    if lang in LANGS:
        kv_set(f"lang:{user_id}", lang)

def system_prompt_for(lang: str) -> str:
    mapping = {
        "ru": "Отвечай на русском языке.",
        "en": "Answer in English.",
        "th": "ตอบเป็นภาษาไทย",
        "zh": "请用中文回答。",
        "ar": "أجب باللغة العربية.",
    }
    return mapping.get(lang, "Отвечай на русском языке.")

# =============================
# UI strings
# =============================
I18N = {
    "ru": {
        "choose_lang": "🌍 Выберите язык",
        "lang_set": "✅ Язык установлен",
        "menu_title": "Главное меню",
        "btn_video": "🎞 Создать видео",
        "btn_photo": "🖼 Оживить фото",
        "btn_music": "🎵 Suno музыка",
        "btn_help": "❓ Помощь",
        "btn_repeat": "🔁 Повторить",
    },
    "en": {
        "choose_lang": "🌍 Choose language",
        "lang_set": "✅ Language set",
        "menu_title": "Main menu",
        "btn_video": "🎞 Create video",
        "btn_photo": "🖼 Animate photo",
        "btn_music": "🎵 Suno music",
        "btn_help": "❓ Help",
        "btn_repeat": "🔁 Repeat",
    },
    "th": {
        "choose_lang": "🌍 เลือกภาษา",
        "lang_set": "✅ ตั้งค่าภาษาแล้ว",
        "menu_title": "เมนูหลัก",
        "btn_video": "🎞 สร้างวิดีโอ",
        "btn_photo": "🖼 ทำให้รูปเคลื่อนไหว",
        "btn_music": "🎵 Suno เพลง",
        "btn_help": "❓ ช่วยเหลือ",
        "btn_repeat": "🔁 ทำซ้ำ",
    },
    "zh": {
        "choose_lang": "🌍 选择语言",
        "lang_set": "✅ 语言已设置",
        "menu_title": "主菜单",
        "btn_video": "🎞 生成视频",
        "btn_photo": "🖼 照片动起来",
        "btn_music": "🎵 Suno 音乐",
        "btn_help": "❓ 帮助",
        "btn_repeat": "🔁 重复",
    },
    "ar": {
        "choose_lang": "🌍 اختر اللغة",
        "lang_set": "✅ تم ضبط اللغة",
        "menu_title": "القائمة الرئيسية",
        "btn_video": "🎞 إنشاء فيديو",
        "btn_photo": "🖼 تحريك صورة",
        "btn_music": "🎵 موسيقى Suno",
        "btn_help": "❓ مساعدة",
        "btn_repeat": "🔁 تكرار",
    },
}

def t(user_id: int, key: str) -> str:
    lang = get_lang(user_id)
    return (I18N.get(lang) or I18N.get("ru")).get(key, key)

PACK = {
    "welcome": {
        "ru": "Добро пожаловать! Выберите режим или напишите запрос.",
        "en": "Welcome! Choose a mode or type your request.",
        "th": "ยินดีต้อนรับ! เลือกโหมดหรือพิมพ์คำขอของคุณ",
        "zh": "欢迎！请选择模式或输入请求。",
        "ar": "مرحبًا! اختر وضعًا أو اكتب طلبك.",
    },
    "help": {
        "ru": "❓ Помощь:\n- Напиши: «Сделай видео: ... 7 сек 16:9»\n- Или пришли фото и нажми «Оживить фото»\n- Для музыки: нажми «Suno музыка» и напиши описание трека",
        "en": "❓ Help:\n- Type: “Make a video: ... 7s 16:9”\n- Or send a photo and tap “Animate photo”\n- For music: tap “Suno music” and describe the track",
    },
    "spam_wait": {
        "ru": "⚠️ Слишком часто. Подождите несколько секунд и попробуйте снова.",
        "en": "⚠️ Too frequent. Wait a few seconds and try again.",
    },
    "done": {
        "ru": "✅ Готово!",
        "en": "✅ Done!",
    },
    "cancel_btn": {"ru": "✖️ Отмена", "en": "✖️ Cancel"},
    "cancelled": {"ru": "✖️ Отменено.", "en": "✖️ Cancelled."},
    "err_button_failed": {"ru": "❌ Ошибка обработки кнопки.", "en": "❌ Button error."},
    "photo_received": {"ru": "🖼 Фото получено. Оживить?", "en": "🖼 Photo received. Animate it?"},
    "photo_missing_retry": {"ru": "🖼 Фото не найдено. Пришлите фото ещё раз.", "en": "🖼 Photo not found. Send again."},
    "ask_video_prompt": {"ru": "🎞 Напиши запрос для видео, например:\n«Сделай видео: закат над морем, 7 сек, 16:9»",
                         "en": "🎞 Type a video prompt, e.g.:\n“Make a video: sunset over the sea, 7s, 16:9”"},
    "ask_send_photo": {"ru": "🖼 Пришли фото, затем выбери «Оживить фото».", "en": "🖼 Send a photo, then tap “Animate photo”."},
    "ask_music_prompt": {"ru": "🎵 Опиши музыку для Suno, например:\n«Лиричный lo-fi, ночной город, 90 bpm, 2 минуты»",
                         "en": "🎵 Describe music for Suno, e.g.:\n“Lyrical lo-fi, night city, 90 bpm, 2 minutes”"},
    "engine_disabled": {"ru": "{name} отключён.", "en": "{name} is disabled."},
    "engine_no_key": {"ru": "{name}: нет ключа/токена API.", "en": "{name}: missing API key/token."},
    "engine_rendering": {"ru": "⏳ {name}: рендерю…", "en": "⏳ {name}: rendering…"},
    "engine_failed": {"ru": "❌ {name}: ошибка генерации.\n{txt}", "en": "❌ {name}: generation failed.\n{txt}"},
    "engine_timeout": {"ru": "⌛ {name}: превышено время ожидания.", "en": "⌛ {name}: timed out."},
    "engine_rejected": {"ru": "⚠️ {name} отклонил задачу ({code}).\n{txt}", "en": "⚠️ {name} rejected ({code}).\n{txt}"},
    "engine_no_task": {"ru": "{name}: не вернулся task_id.\n{txt}", "en": "{name}: missing task_id.\n{txt}"},
    "engine_no_url": {"ru": "{name}: нет ссылки на результат.\n{txt}", "en": "{name}: no result url.\n{txt}"},
    "choose_engine": {"ru": "Выберите движок:", "en": "Choose engine:"},
    "video_opts": {"ru": "🎞 Параметры:\n⏱ Длительность: {dur} сек\n🖼 Аспект: {asp}\nЗапрос: «{prompt}»\n\nВыберите движок ниже:",
                  "en": "🎞 Options:\n⏱ Duration: {dur}s\n🖼 Aspect: {asp}\nPrompt: “{prompt}”\n\nChoose engine below:"},
    "repeat_empty": {"ru": "Нечего повторять: сначала отправьте запрос для видео.", "en": "Nothing to repeat yet."},
    "repeat_offer": {"ru": "🔁 Повторить тем же движком ({engine}) или выбрать другой?",
                    "en": "🔁 Repeat with the same engine ({engine}) or choose another?"},
    "repeat_btn_same": {"ru": "🔁 Тем же движком", "en": "🔁 Same engine"},
    "repeat_btn_choose": {"ru": "🎛 Выбрать движок", "en": "🎛 Choose engine"},
    "pong": {"ru": "✅ Бот онлайн.", "en": "✅ Bot is online."},
}

def _tr(uid: int, key: str, **kwargs) -> str:
    lang = get_lang(uid)
    text = (PACK.get(key, {}) or {}).get(lang) or (PACK.get(key, {}) or {}).get("ru") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text

# =============================
# Engines meta descriptions (shown on selection)
# =============================
ENGINE_INFO = {
    "kling": {
        "name": "Kling",
        "desc_ru": "Текст → видео. Хорош для динамики, реалистики, эффектных сцен.",
        "desc_en": "Text → video. Great for dynamic & realistic scenes.",
    },
    "luma": {
        "name": "Luma",
        "desc_ru": "Текст → видео. Кинематографичный стиль, плавные движения.",
        "desc_en": "Text → video. Cinematic style, smooth motion.",
    },
    "sora": {
        "name": "Sora",
        "desc_ru": "Текст → видео (OpenAI). Высокое качество, сложные сцены.",
        "desc_en": "Text → video (OpenAI). High quality and complex scenes.",
    },
    "runway": {
        "name": "Runway",
        "desc_ru": "Фото → видео. Оживляет изображение, делает короткую анимацию.",
        "desc_en": "Photo → video. Animates a still image.",
    },
    "suno": {
        "name": "Suno",
        "desc_ru": "Текст → музыка. Генерация трека по описанию (жанр/настроение/темп).",
        "desc_en": "Text → music. Generates tracks from description.",
    },
}

# =============================
# Limits / Subscriptions
# =============================
LIMITS = {
    "free":      {"max_video_seconds": 5},
    "start":     {"max_video_seconds": 8},
    "pro":       {"max_video_seconds": 12},
    "ultimate":  {"max_video_seconds": 15},
}
USER_DEFAULT_TIER = (_env("USER_DEFAULT_TIER") or "free").strip().lower()

def get_subscription_tier(user_id: int) -> str:
    row = db_exec("SELECT tier FROM subs WHERE user_id=?", (user_id,)).fetchone()
    if row and row["tier"]:
        return str(row["tier"])
    return USER_DEFAULT_TIER if USER_DEFAULT_TIER in LIMITS else "free"

def set_subscription_tier(user_id: int, tier: str):
    if tier not in LIMITS:
        tier = "free"
    db_exec("INSERT OR REPLACE INTO subs(user_id,tier,ts) VALUES(?,?,?)",
            (user_id, tier, int(time.time())))

# =============================
# Runtime state
# =============================
PENDING_TTL_S = _env_int("PENDING_TTL_S", 60 * 60)
ACTIVE_JOB_TTL_S = _env_int("ACTIVE_JOB_TTL_S", 30 * 60)
ANTI_SPAM_WINDOW_S = _env_int("ANTI_SPAM_WINDOW_S", 12)
ANTI_SPAM_MAX = _env_int("ANTI_SPAM_MAX", 4)

_pending_actions: Dict[str, Dict[str, Any]] = {}
_active_jobs: Dict[int, Dict[str, Any]] = {}
_recent_msgs: Dict[int, List[float]] = {}
_last_video_prompt: Dict[int, Dict[str, Any]] = {}

def _new_aid() -> str:
    return uuid.uuid4().hex

def _spam_check(uid: int) -> bool:
    now = time.time()
    arr = _recent_msgs.get(uid) or []
    arr = [t for t in arr if now - t <= ANTI_SPAM_WINDOW_S]
    arr.append(now)
    _recent_msgs[uid] = arr
    return len(arr) > ANTI_SPAM_MAX

# =============================
# Helpers / Utils
# =============================
def normalize_seconds(sec: int) -> int:
    try:
        sec = int(sec)
    except Exception:
        return 5
    if sec < 1:
        sec = 1
    if sec > 30:
        sec = 30
    return sec

def normalize_aspect(aspect: str) -> str:
    aspect = (aspect or "").strip()
    if aspect in ("16:9", "9:16", "1:1"):
        return aspect
    # also accept 720:1280 style
    if aspect in ("720:1280", "1280:720", "1024:1024"):
        if aspect == "720:1280":
            return "9:16"
        if aspect == "1280:720":
            return "16:9"
        return "1:1"
    return "16:9"

def enforce_seconds_limit(seconds: int, tier: str) -> int:
    lim = LIMITS.get(tier, LIMITS["free"])
    maxs = int(lim.get("max_video_seconds", 5))
    seconds = normalize_seconds(seconds)
    return min(seconds, maxs)

def extract_video_url(st_js: dict) -> Optional[str]:
    """
    Try common locations for a video URL in Comet provider responses.
    """
    if not isinstance(st_js, dict):
        return None
    candidates = []
    # direct
    for k in ("video_url", "url", "result_url", "download_url"):
        v = st_js.get(k)
        if isinstance(v, str) and v.startswith("http"):
            candidates.append(v)

    data = st_js.get("data")
    if isinstance(data, dict):
        for k in ("video_url", "url", "result_url", "download_url"):
            v = data.get(k)
            if isinstance(v, str) and v.startswith("http"):
                candidates.append(v)
        # common outputs format
        out = data.get("output") or data.get("outputs") or data.get("result")
        if isinstance(out, dict):
            for k in ("url", "video", "video_url", "download_url"):
                v = out.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    candidates.append(v)
        if isinstance(out, list):
            for item in out:
                if isinstance(item, dict):
                    v = item.get("url") or item.get("video_url") or item.get("download_url")
                    if isinstance(v, str) and v.startswith("http"):
                        candidates.append(v)

    # sometimes st_js itself contains nested list
    for key in ("output", "outputs", "result"):
        out = st_js.get(key)
        if isinstance(out, list):
            for item in out:
                if isinstance(item, dict):
                    v = item.get("url") or item.get("video_url") or item.get("download_url")
                    if isinstance(v, str) and v.startswith("http"):
                        candidates.append(v)

    return candidates[0] if candidates else None

async def _safe_edit_or_reply(msg, text: str, reply_markup=None):
    try:
        await msg.edit_text(text, reply_markup=reply_markup)
        return
    except Exception:
        pass
    try:
        await msg.reply_text(text, reply_markup=reply_markup)
    except Exception:
        pass

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

async def download_bytes_redirect_safe(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict | None = None,
    timeout_s: float = 180.0,
    max_redirects: int = 5,
) -> bytes:
    cur = url
    for _ in range(max_redirects + 1):
        req = client.build_request("GET", cur, headers=headers)
        resp = await client.send(req, follow_redirects=False, timeout=timeout_s)

        if resp.status_code in _REDIRECT_STATUSES:
            loc = resp.headers.get("location") or resp.headers.get("Location")
            if not loc:
                raise httpx.HTTPStatusError("Redirect without Location", request=req, response=resp)
            cur = str(httpx.URL(cur).join(loc))
            continue

        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Download failed status={resp.status_code} body={(resp.text or '')[:400]}",
                request=req,
                response=resp,
            )

        data = resp.content or b""
        if not data:
            raise RuntimeError("Empty response body while downloading result")
        return data

    raise RuntimeError(f"Too many redirects while downloading: {url}")

async def safe_send_video(context: ContextTypes.DEFAULT_TYPE, chat_id: int, bio: BytesIO, caption: Optional[str] = None) -> bool:
    filename = getattr(bio, "name", None) or "video.mp4"
    try:
        bio.seek(0)
        await context.bot.send_video(
            chat_id=chat_id,
            video=InputFile(bio, filename=filename),
            caption=caption,
            supports_streaming=True,
        )
        return True
    except Exception as e:
        log.warning("send_video failed, trying document: %s", e)

    try:
        bio.seek(0)
        await context.bot.send_document(
            chat_id=chat_id,
            document=InputFile(bio, filename=filename),
            caption=caption,
        )
        return True
    except Exception as e:
        log.error("send_document failed: %s", e)
        return False

# =============================
# History
# =============================
def _hist_key(uid: int) -> str:
    return f"hist:{uid}"

def _hist_add(uid: int, role: str, content: str):
    try:
        raw = kv_get(_hist_key(uid), "[]") or "[]"
        arr = json.loads(raw)
        if not isinstance(arr, list):
            arr = []
    except Exception:
        arr = []
    arr.append({"ts": int(time.time()), "role": role, "content": (content or "")[:2000]})
    arr = arr[-20:]
    kv_set(_hist_key(uid), json.dumps(arr, ensure_ascii=False))

# =============================
# Main keyboards
# =============================
def _lang_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for code in LANGS.keys():
        label = LANG_LABELS.get(code, code)
        rows.append([InlineKeyboardButton(label, callback_data=f"lang:{code}")])
    return InlineKeyboardMarkup(rows)

def _main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t(user_id, "btn_video")), KeyboardButton(t(user_id, "btn_photo"))],
            [KeyboardButton(t(user_id, "btn_music")), KeyboardButton(t(user_id, "btn_repeat"))],
            [KeyboardButton(t(user_id, "btn_help"))],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

# =============================
# Video intent detection
# =============================
_VIDEO_PREFIXES = [
    r"\bсделай\s+видео\b",
    r"\bсоздай\s+видео\b",
    r"\bvideo\b",
    r"\bmake\s+video\b",
    r"\bgenerate\s+video\b",
]

def _detect_video_intent(text: str) -> bool:
    if not text:
        return False
    tl = text.lower().strip()
    return any(re.search(p, tl, re.I) for p in _VIDEO_PREFIXES)

def _parse_video_opts(text: str) -> Tuple[int, str]:
    duration = 5
    aspect = "16:9"
    m = re.search(r"(\d+)\s*(сек|s)", text, re.I)
    if m:
        try:
            duration = int(m.group(1))
        except Exception:
            duration = 5
    tl = (text or "").lower()
    if "9:16" in text or "вертик" in tl:
        aspect = "9:16"
    elif "1:1" in text:
        aspect = "1:1"
    return normalize_seconds(duration), normalize_aspect(aspect)

# =============================
# OpenAI/OpenRouter text chat
# =============================
def _oai_headers():
    return {"Authorization": f"Bearer {OPENAI_API_KEY}"}

def _openrouter_headers():
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
    if OPENROUTER_SITE_URL:
        headers["HTTP-Referer"] = OPENROUTER_SITE_URL
    if OPENROUTER_APP_NAME:
        headers["X-Title"] = OPENROUTER_APP_NAME
    return headers

async def _gpt_chat(user_id: int, messages: list[dict]) -> str:
    lang = get_lang(user_id)
    sys_msg = {"role": "system", "content": system_prompt_for(lang)}
    payload = {
        "model": OPENAI_MODEL,
        "messages": [sys_msg] + messages,
        "temperature": 0.7,
    }

    if TEXT_PROVIDER == "openrouter":
        if not OPENROUTER_API_KEY:
            return "OpenRouter API key is missing."
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = _openrouter_headers()
    else:
        if not OPENAI_API_KEY:
            return "OpenAI API key is missing."
        url = f"{OPENAI_BASE_URL}/chat/completions"
        headers = _oai_headers()

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        js = r.json()
        return (js["choices"][0]["message"]["content"] or "").strip()

# =============================
# Whisper STT
# =============================
async def _transcribe_telegram_voice(file_bytes: bytes, filename: str = "voice.ogg") -> str:
    if not OPENAI_API_KEY:
        return ""
    url = f"{OPENAI_BASE_URL}/audio/transcriptions"
    data = {"model": WHISPER_MODEL}
    files = {"file": (filename, file_bytes, "audio/ogg")}

    last_err = None
    for _ in range(2):
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
                resp = await client.post(url, headers=_oai_headers(), data=data, files=files)
            if resp.status_code >= 400:
                last_err = (resp.text or "")[:600]
                await asyncio.sleep(0.5)
                continue
            js = resp.json()
            return (js.get("text") or "").strip()
        except Exception as e:
            last_err = str(e)
            await asyncio.sleep(0.5)

    log.error("STT failed: %s", last_err)
    return ""

# =============================
# Engine chooser keyboard (Video)
# =============================
def _video_engine_kb(aid: str, user_id: int) -> InlineKeyboardMarkup:
    tier = get_subscription_tier(user_id)
    rows = []

    # Presets
    if tier in ("pro", "ultimate"):
        rows.append([
            InlineKeyboardButton("⏱ 5s", callback_data=f"setdur:5:{aid}"),
            InlineKeyboardButton("⏱ 8s", callback_data=f"setdur:8:{aid}"),
            InlineKeyboardButton("⏱ 12s", callback_data=f"setdur:12:{aid}"),
        ])
        rows.append([
            InlineKeyboardButton("🖼 16:9", callback_data=f"setasp:16:9:{aid}"),
            InlineKeyboardButton("🖼 9:16", callback_data=f"setasp:9:16:{aid}"),
            InlineKeyboardButton("🖼 1:1", callback_data=f"setasp:1:1:{aid}"),
        ])
    else:
        rows.append([InlineKeyboardButton("⏱ 5s", callback_data=f"setdur:5:{aid}")])
        rows.append([InlineKeyboardButton("🖼 16:9", callback_data=f"setasp:16:9:{aid}")])

    # Engines
    if KLING_ENABLED:
        rows.append([InlineKeyboardButton("📼 Kling", callback_data=f"choose:kling:{aid}")])
    if LUMA_ENABLED:
        rows.append([InlineKeyboardButton("🎞 Luma", callback_data=f"choose:luma:{aid}")])
    if SORA_ENABLED:
        rows.append([InlineKeyboardButton("✨ Sora", callback_data=f"choose:sora:{aid}")])

    rows.append([InlineKeyboardButton(_tr(user_id, "cancel_btn"), callback_data=f"cancel:{aid}")])
    return InlineKeyboardMarkup(rows)

def _repeat_choice_kb(user_id: int, engine: str) -> InlineKeyboardMarkup:
    label = (engine or "").strip().capitalize() or "Engine"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{_tr(user_id,'repeat_btn_same')} ({label})", callback_data=f"repeat:{engine}")],
        [InlineKeyboardButton(_tr(user_id,'repeat_btn_choose'), callback_data="repeat:choose")],
    ])

async def _ask_video_engine(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    uid = update.effective_user.id
    dur, asp = _parse_video_opts(prompt)
    dur = enforce_seconds_limit(dur, get_subscription_tier(uid))

    _last_video_prompt[uid] = {"prompt": prompt, "duration": dur, "aspect": asp, "ts": int(time.time())}

    aid = _new_aid()
    _pending_actions[aid] = {
        "uid": uid,
        "ts": int(time.time()),
        "type": "text_video",
        "prompt": prompt,
        "duration": dur,
        "aspect": asp,
    }

    await update.effective_message.reply_text(
        _tr(uid, "video_opts", dur=dur, asp=asp, prompt=prompt),
        reply_markup=_video_engine_kb(aid, uid),
    )

# =============================
# Poll status (Comet tasks)
# =============================
async def poll_task_until_done(
    client: httpx.AsyncClient,
    *,
    status_url: str,
    headers: dict,
    engine_name: str,
    msg,
    uid: int,
    timeout_s: int = 900,
    poll_delay_s: int = VIDEO_POLL_DELAY_S,
) -> Tuple[bool, dict]:
    started = time.time()
    last_ui_update = 0.0

    while True:
        # Cooperative cancel
        job = _active_jobs.get(uid)
        if not job or (str(job.get("engine") or "").lower() != str(engine_name).lower()):
            try:
                await msg.reply_text(_tr(uid, "cancelled"))
            except Exception:
                pass
            return False, {}

        elapsed = time.time() - started
        if elapsed > timeout_s:
            await msg.reply_text(_tr(uid, "engine_timeout", name=engine_name))
            return False, {}

        rs = await client.get(status_url, headers=headers)
        if rs.status_code != 200:
            await msg.reply_text(_tr(uid, "engine_failed", name=engine_name, txt=(rs.text or "")[:600]))
            return False, {}

        try:
            st_js = rs.json() or {}
        except Exception:
            await msg.reply_text(_tr(uid, "engine_failed", name=engine_name, txt="Invalid JSON status"))
            return False, {}

        st = (st_js.get("status") or (st_js.get("data") or {}).get("status") or "").lower()

        if (time.time() - last_ui_update) > 25:
            last_ui_update = time.time()
            try:
                await _safe_edit_or_reply(
                    msg,
                    _tr(uid, "engine_rendering", name=engine_name) + f" ({int(elapsed)}s)",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(_tr(uid, "cancel_btn"), callback_data=f"cancel:{job.get('aid','')}")]]),
                )
            except Exception:
                pass

        if st in ("completed", "succeeded", "done", "success"):
            return True, st_js

        if st in ("failed", "error", "rejected", "cancelled", "canceled"):
            await msg.reply_text(_tr(uid, "engine_failed", name=engine_name, txt=str(st_js)[:900]))
            return False, {}

        await asyncio.sleep(poll_delay_s)

# =============================
# Comet engines: Kling / Luma / Runway
# =============================
def _comet_headers():
    return {
        "Authorization": f"Bearer {COMET_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

async def _engine_confirm(msg, uid: int, engine_key: str):
    info = ENGINE_INFO.get(engine_key, {})
    name = info.get("name", engine_key)
    desc = info.get("desc_ru") if get_lang(uid) == "ru" else info.get("desc_en", "")
    await msg.reply_text(f"✅ Выбрано: {name}\nℹ️ {desc}")

async def _run_kling_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, seconds: int, aspect: str) -> bool:
    msg = update.effective_message
    uid = update.effective_user.id

    if not KLING_ENABLED:
        await msg.reply_text(_tr(uid, "engine_disabled", name="Kling"))
        return False
    if not COMET_API_KEY:
        await msg.reply_text(_tr(uid, "engine_no_key", name="Kling"))
        return False

    seconds = enforce_seconds_limit(seconds, get_subscription_tier(uid))
    aspect = normalize_aspect(aspect)

    await msg.reply_text(_tr(uid, "engine_rendering", name="Kling"))

    payload = {"prompt": (prompt or "").strip(), "seconds": int(seconds), "ratio": aspect}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.post(f"{COMET_BASE_URL}/kling/v1/text_to_video", headers=_comet_headers(), json=payload)
            if r.status_code >= 400:
                await msg.reply_text(_tr(uid, "engine_rejected", name="Kling", code=r.status_code, txt=(r.text or "")[:900]))
                return False

            js = r.json() or {}
            task_id = js.get("task_id") or js.get("taskId") or js.get("id") or (js.get("data") or {}).get("task_id") or (js.get("data") or {}).get("id")
            if not task_id:
                await msg.reply_text(_tr(uid, "engine_no_task", name="Kling", txt=str(js)[:900]))
                return False

            status_url = f"{COMET_BASE_URL}/kling/v1/tasks/{task_id}"
            ok, st_js = await poll_task_until_done(client, status_url=status_url, headers=_comet_headers(), engine_name="Kling", msg=msg, uid=uid, timeout_s=900)
            if not ok:
                return False

            video_url = extract_video_url(st_js)
            if not video_url:
                await msg.reply_text(_tr(uid, "engine_no_url", name="Kling", txt=str(st_js)[:900]))
                return False

            data = await download_bytes_redirect_safe(client, video_url, timeout_s=180.0)
            bio = BytesIO(data)
            bio.name = "kling.mp4"
            bio.seek(0)

            if not await safe_send_video(context, update.effective_chat.id, bio):
                await msg.reply_text(_tr(uid, "engine_failed", name="Kling", txt="send failed"))
                return False

            await msg.reply_text(_tr(uid, "done"))
            return True
    except Exception as e:
        log.exception("Kling exception: %s", e)
        await msg.reply_text(_tr(uid, "engine_failed", name="Kling", txt=str(e)))
        return False

async def _run_luma_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, seconds: int, aspect: str) -> bool:
    msg = update.effective_message
    uid = update.effective_user.id

    if not LUMA_ENABLED:
        await msg.reply_text(_tr(uid, "engine_disabled", name="Luma"))
        return False
    if not COMET_API_KEY:
        await msg.reply_text(_tr(uid, "engine_no_key", name="Luma"))
        return False

    seconds = enforce_seconds_limit(seconds, get_subscription_tier(uid))
    aspect = normalize_aspect(aspect)

    await msg.reply_text(_tr(uid, "engine_rendering", name="Luma"))

    payload = {"prompt": (prompt or "").strip(), "seconds": int(seconds), "ratio": aspect}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.post(f"{COMET_BASE_URL}/luma/v1/text_to_video", headers=_comet_headers(), json=payload)
            if r.status_code >= 400:
                await msg.reply_text(_tr(uid, "engine_rejected", name="Luma", code=r.status_code, txt=(r.text or "")[:900]))
                return False

            js = r.json() or {}
            task_id = js.get("task_id") or js.get("taskId") or js.get("id") or (js.get("data") or {}).get("task_id") or (js.get("data") or {}).get("id")
            if not task_id:
                await msg.reply_text(_tr(uid, "engine_no_task", name="Luma", txt=str(js)[:900]))
                return False

            status_url = f"{COMET_BASE_URL}/luma/v1/tasks/{task_id}"
            ok, st_js = await poll_task_until_done(client, status_url=status_url, headers=_comet_headers(), engine_name="Luma", msg=msg, uid=uid, timeout_s=900)
            if not ok:
                return False

            video_url = extract_video_url(st_js)
            if not video_url:
                await msg.reply_text(_tr(uid, "engine_no_url", name="Luma", txt=str(st_js)[:900]))
                return False

            data = await download_bytes_redirect_safe(client, video_url, timeout_s=180.0)
            bio = BytesIO(data)
            bio.name = "luma.mp4"
            bio.seek(0)

            if not await safe_send_video(context, update.effective_chat.id, bio):
                await msg.reply_text(_tr(uid, "engine_failed", name="Luma", txt="send failed"))
                return False

            await msg.reply_text(_tr(uid, "done"))
            return True
    except Exception as e:
        log.exception("Luma exception: %s", e)
        await msg.reply_text(_tr(uid, "engine_failed", name="Luma", txt=str(e)))
        return False

async def _run_runway_animate_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, photo_bytes: bytes, seconds: int, aspect: str) -> bool:
    msg = update.effective_message
    uid = update.effective_user.id

    if not RUNWAY_ENABLED:
        await msg.reply_text(_tr(uid, "engine_disabled", name="Runway"))
        return False
    if not COMET_API_KEY:
        await msg.reply_text(_tr(uid, "engine_no_key", name="Runway"))
        return False
    if not photo_bytes:
        await msg.reply_text(_tr(uid, "engine_failed", name="Runway", txt="no photo bytes"))
        return False

    seconds = enforce_seconds_limit(seconds, get_subscription_tier(uid))
    aspect = normalize_aspect(aspect)

    await msg.reply_text(_tr(uid, "engine_rendering", name="Runway"))

    try:
        img_b64 = base64.b64encode(photo_bytes).decode("ascii")
        image_data_url = f"data:image/jpeg;base64,{img_b64}"
    except Exception:
        await msg.reply_text(_tr(uid, "engine_failed", name="Runway", txt="failed to encode image"))
        return False

    payload = {
        "model": RUNWAY_MODEL,
        "promptImage": image_data_url,
        "seconds": int(seconds),
        "ratio": aspect,
    }

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.post(f"{COMET_BASE_URL}/runwayml/v1/image_to_video", headers=_comet_headers(), json=payload)
            if r.status_code >= 400:
                await msg.reply_text(_tr(uid, "engine_rejected", name="Runway", code=r.status_code, txt=(r.text or "")[:900]))
                return False

            js = r.json() or {}
            task_id = js.get("task_id") or js.get("taskId") or js.get("id") or (js.get("data") or {}).get("task_id") or (js.get("data") or {}).get("id")
            if not task_id:
                await msg.reply_text(_tr(uid, "engine_no_task", name="Runway", txt=str(js)[:900]))
                return False

            status_url = f"{COMET_BASE_URL}/runwayml/v1/tasks/{task_id}"
            ok, st_js = await poll_task_until_done(client, status_url=status_url, headers=_comet_headers(), engine_name="Runway", msg=msg, uid=uid, timeout_s=900)
            if not ok:
                return False

            video_url = extract_video_url(st_js)
            if not video_url:
                await msg.reply_text(_tr(uid, "engine_no_url", name="Runway", txt=str(st_js)[:900]))
                return False

            data = await download_bytes_redirect_safe(client, video_url, timeout_s=180.0)
            bio = BytesIO(data)
            bio.name = "runway.mp4"
            bio.seek(0)

            if not await safe_send_video(context, update.effective_chat.id, bio):
                await msg.reply_text(_tr(uid, "engine_failed", name="Runway", txt="send failed"))
                return False

            await msg.reply_text(_tr(uid, "done"))
            return True
    except Exception as e:
        log.exception("Runway exception: %s", e)
        await msg.reply_text(_tr(uid, "engine_failed", name="Runway", txt=str(e)))
        return False

# =============================
# Sora (minimal OpenAI stub)
# NOTE: only included if you have access. Otherwise it will error gracefully.
# =============================
async def _run_sora_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, seconds: int, aspect: str) -> bool:
    msg = update.effective_message
    uid = update.effective_user.id

    if not SORA_ENABLED:
        await msg.reply_text(_tr(uid, "engine_disabled", name="Sora"))
        return False
    if SORA_PROVIDER != "openai":
        await msg.reply_text(_tr(uid, "engine_failed", name="Sora", txt=f"Unsupported provider: {SORA_PROVIDER}"))
        return False
    if not OPENAI_API_KEY:
        await msg.reply_text(_tr(uid, "engine_no_key", name="Sora"))
        return False

    # placeholder: many accounts don't have video endpoint access
    await msg.reply_text(_tr(uid, "engine_failed", name="Sora", txt="Video endpoint not implemented in this build (account access differs)."))
    return False

# =============================
# Suno — text -> music
# =============================
async def _run_suno_music(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str) -> bool:
    msg = update.effective_message
    uid = update.effective_user.id

    if not SUNO_ENABLED:
        await msg.reply_text(_tr(uid, "engine_disabled", name="Suno"))
        return False
    if not SUNO_API_KEY:
        await msg.reply_text(_tr(uid, "engine_no_key", name="Suno"))
        return False

    await msg.reply_text(_tr(uid, "engine_rendering", name="Suno"))

    # NOTE: Suno has several APIs depending on vendor; keep robust generic call.
    # If your provider is different, adjust endpoint in ENV + update here.
    # Default example:
    # POST https://api.suno.ai/v1/generate  (varies)
    endpoint = (_env("SUNO_BASE_URL") or "https://api.suno.ai").rstrip("/")
    url = f"{endpoint}/v1/generate"

    headers = {"Authorization": f"Bearer {SUNO_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": SUNO_MODEL,
        "prompt": (prompt or "").strip(),
    }

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                await msg.reply_text(_tr(uid, "engine_failed", name="Suno", txt=(r.text or "")[:900]))
                return False

            js = r.json() or {}

            # Try to extract audio url
            audio_url = None
            for k in ("audio_url", "url", "download_url"):
                v = js.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    audio_url = v
                    break
            if not audio_url:
                data = js.get("data")
                if isinstance(data, dict):
                    for k in ("audio_url", "url", "download_url"):
                        v = data.get(k)
                        if isinstance(v, str) and v.startswith("http"):
                            audio_url = v
                            break

            if not audio_url:
                await msg.reply_text(_tr(uid, "engine_failed", name="Suno", txt="No audio URL in response"))
                return False

            # Download audio
            data = await download_bytes_redirect_safe(client, audio_url, timeout_s=180.0)
            bio = BytesIO(data)
            bio.name = "suno.mp3"
            bio.seek(0)

            try:
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=InputFile(bio, filename=bio.name),
                    caption="🎵 Suno",
                )
                await msg.reply_text(_tr(uid, "done"))
                return True
            except Exception as e:
                await msg.reply_text(_tr(uid, "engine_failed", name="Suno", txt=f"Send audio failed: {e}"))
                return False

    except Exception as e:
        log.exception("Suno exception: %s", e)
        await msg.reply_text(_tr(uid, "engine_failed", name="Suno", txt=str(e)))
        return False

# =============================
# CryptoBot plans (simplified but working)
# =============================
CRYPTOBOT_TOKEN = (_env("CRYPTOBOT_TOKEN") or _env("CRYPTO_PAY_API_TOKEN") or "").strip()
CRYPTOBOT_BASE = (_env("CRYPTOBOT_BASE") or "https://pay.crypt.bot").rstrip("/")
CRYPTOBOT_API = (_env("CRYPTOBOT_API") or f"{CRYPTOBOT_BASE}/api").rstrip("/")

PLANS = {
    "start": {"title": "START", "price_usdt": float(_env_float("PLAN_START_PRICE", 19.0)), "desc": "Повышенные лимиты.", "tier": "start"},
    "pro": {"title": "PRO", "price_usdt": float(_env_float("PLAN_PRO_PRICE", 49.0)), "desc": "Максимум пресетов.", "tier": "pro"},
    "ultimate": {"title": "ULTIMATE", "price_usdt": float(_env_float("PLAN_ULTIMATE_PRICE", 99.0)), "desc": "Максимальные лимиты.", "tier": "ultimate"},
}

async def _cryptobot_create_invoice(amount_usdt: float, description: str):
    if not CRYPTOBOT_TOKEN:
        return None
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    payload = {
        "asset": "USDT",
        "amount": str(amount_usdt),
        "description": description[:250],
        "paid_btn_name": "openBot",
        "paid_btn_url": "https://t.me",
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        r = await client.post(f"{CRYPTOBOT_API}/createInvoice", headers=headers, data=payload)
        if r.status_code != 200:
            return None
        js = r.json() or {}
        if not js.get("ok"):
            return None
        return js.get("result")

async def _cryptobot_get_invoice(invoice_id: str):
    if not CRYPTOBOT_TOKEN:
        return None
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        r = await client.get(f"{CRYPTOBOT_API}/getInvoices", headers=headers, params={"invoice_ids": invoice_id})
        if r.status_code != 200:
            return None
        js = r.json() or {}
        if not js.get("ok"):
            return None
        items = (js.get("result") or {}).get("items") or []
        return items[0] if items else None

# =============================
# Commands / handlers
# =============================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if kv_get(f"lang:{uid}", None) is None:
        await update.effective_message.reply_text(t(uid, "choose_lang"), reply_markup=_lang_keyboard())
        return
    await update.effective_message.reply_text(t(uid, "menu_title"), reply_markup=_main_menu_keyboard(uid))

async def on_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    data = (q.data or "").strip()
    if not data.startswith("lang:"):
        await q.answer()
        return
    code = data.split(":", 1)[1]
    if code not in LANGS:
        await q.answer()
        return
    set_lang(uid, code)
    await q.answer()
    await q.edit_message_text(f"{t(uid,'lang_set')}: {LANG_LABELS.get(code, code)}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=_tr(uid, "welcome"), reply_markup=_main_menu_keyboard(uid))

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.effective_message.reply_text(_tr(uid, "help"), reply_markup=_main_menu_keyboard(uid))

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.effective_message.reply_text(_tr(uid, "pong"), reply_markup=_main_menu_keyboard(uid))

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        raw = kv_get(_hist_key(uid), "[]") or "[]"
        arr = json.loads(raw)
        if not isinstance(arr, list) or not arr:
            await update.effective_message.reply_text("История пуста.")
            return
    except Exception:
        await update.effective_message.reply_text("История пуста.")
        return
    lines = []
    for item in arr[-20:]:
        role = item.get("role") or "?"
        c = (item.get("content") or "").replace("\n", " ")
        if len(c) > 160:
            c = c[:160] + "…"
        lines.append(f"[{role}] {c}")
    await update.effective_message.reply_text("🧾 History (last 20):\n\n" + "\n".join(lines))

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    lines = []
    for k, p in PLANS.items():
        lines.append(f"• {p['title']}: {p['price_usdt']} USDT — {p['desc']}")
    txt = "💳 Тарифы:\n\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(p["title"], callback_data=f"plan:{k}")] for k, p in PLANS.items()])
    await update.effective_message.reply_text(txt, reply_markup=kb)

async def on_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_key: str):
    q = update.callback_query
    uid = update.effective_user.id
    plan = PLANS.get(plan_key)
    if not plan:
        await q.answer("Неизвестный тариф.", show_alert=True)
        return

    inv = await _cryptobot_create_invoice(float(plan["price_usdt"]), f"GPT5PRO: {plan['title']} ({uid})")
    if not inv:
        await q.answer("Оплата сейчас недоступна.", show_alert=True)
        return

    pay_url = inv.get("pay_url")
    inv_id = str(inv.get("invoice_id") or "")
    if pay_url and inv_id:
        kv_set(f"invoice:{uid}", inv_id)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💠 Оплатить в CryptoBot", url=pay_url)],
            [InlineKeyboardButton("✅ Я оплатил", callback_data=f"paid:{plan_key}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="plans:back")],
        ])
        await q.edit_message_text(
            f"Тариф: {plan['title']}\nЦена: {plan['price_usdt']} USDT\n\n{plan['desc']}\n\n"
            "Нажми «Оплатить», затем «Я оплатил».",
            reply_markup=kb,
        )
    else:
        await q.answer("Не удалось создать инвойс.", show_alert=True)

async def on_paid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_key: str):
    q = update.callback_query
    uid = update.effective_user.id
    inv_id = kv_get(f"invoice:{uid}", None)
    if not inv_id:
        await q.answer("Инвойс не найден.", show_alert=True)
        return
    info = await _cryptobot_get_invoice(inv_id)
    if not info:
        await q.answer("Не удалось проверить оплату.", show_alert=True)
        return
    status = (info.get("status") or "").lower()
    if status == "paid":
        tier = (PLANS.get(plan_key) or {}).get("tier") or "start"
        set_subscription_tier(uid, tier)
        await q.edit_message_text(f"✅ Оплата подтверждена. Тариф активирован: {tier}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=t(uid, "menu_title"), reply_markup=_main_menu_keyboard(uid))
    else:
        await q.answer(f"Статус оплаты: {status}", show_alert=True)

# =============================
# Message handlers
# =============================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = update.effective_user.id
    text = (msg.text or "").strip()
    if not text:
        return

    if _spam_check(uid):
        await msg.reply_text(_tr(uid, "spam_wait"))
        return

    _hist_add(uid, "user", text)

    if text == t(uid, "btn_help"):
        await cmd_help(update, context)
        return

    if text == t(uid, "btn_video"):
        await msg.reply_text(_tr(uid, "ask_video_prompt"), reply_markup=_main_menu_keyboard(uid))
        return

    if text == t(uid, "btn_photo"):
        await msg.reply_text(_tr(uid, "ask_send_photo"), reply_markup=_main_menu_keyboard(uid))
        return

    if text == t(uid, "btn_music"):
        await msg.reply_text(_tr(uid, "ask_music_prompt"), reply_markup=_main_menu_keyboard(uid))
        # remember we are in "awaiting suno"
        kv_set(f"mode:{uid}", "suno")
        return

    if text == t(uid, "btn_repeat"):
        last = _last_video_prompt.get(uid) or {}
        lp = (last.get("prompt") or "").strip()
        if not lp:
            await msg.reply_text(_tr(uid, "repeat_empty"), reply_markup=_main_menu_keyboard(uid))
            return
        last_engine = (last.get("engine") or "").strip().lower()
        if last_engine in ("kling", "luma", "sora"):
            await msg.reply_text(_tr(uid, "repeat_offer", engine=last_engine.capitalize()), reply_markup=_repeat_choice_kb(uid, last_engine))
            return
        await _ask_video_engine(update, context, lp)
        return

    # If user in suno mode
    if (kv_get(f"mode:{uid}", "") or "") == "suno":
        kv_set(f"mode:{uid}", "")
        await _engine_confirm(msg, uid, "suno")
        await _run_suno_music(update, context, text)
        return

    if _detect_video_intent(text):
        await _ask_video_engine(update, context, text)
        return

    # GPT chat
    try:
        ans = await _gpt_chat(uid, [{"role": "user", "content": text}])
        await msg.reply_text(ans)
        _hist_add(uid, "assistant", ans)
    except Exception as e:
        log.exception("GPT error: %s", e)
        await msg.reply_text("Ошибка генерации ответа.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = update.effective_user.id
    if not msg.photo:
        return

    if _spam_check(uid):
        await msg.reply_text(_tr(uid, "spam_wait"))
        return

    photo = msg.photo[-1]
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        tg_file = await context.bot.get_file(photo.file_id)
        raw = await tg_file.download_as_bytearray()
    except Exception as e:
        log.exception("Photo download error: %s", e)
        await msg.reply_text("Не удалось скачать фото.")
        return

    # ✅ store seconds/aspect properly (FIX)
    tier = get_subscription_tier(uid)
    seconds = enforce_seconds_limit(RUNWAY_DURATION_S, tier)
    aspect = normalize_aspect(RUNWAY_RATIO)

    aid = _new_aid()
    _pending_actions[aid] = {
        "uid": uid,
        "ts": int(time.time()),
        "type": "animate_photo",
        "photo_bytes": bytes(raw),
        "seconds": int(seconds),
        "aspect": aspect,
    }

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎬 Оживить фото (Runway)", callback_data=f"animate_photo:{aid}")]])
    await msg.reply_text(_tr(uid, "photo_received"), reply_markup=kb)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = update.effective_user.id

    if _spam_check(uid):
        await msg.reply_text(_tr(uid, "spam_wait"))
        return

    media = msg.voice or msg.audio
    if not media:
        await msg.reply_text("Не найдено голосовое сообщение.")
        return

    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        tg_file = await context.bot.get_file(media.file_id)
        raw = await tg_file.download_as_bytearray()
    except Exception as e:
        log.exception("Voice download error: %s", e)
        await msg.reply_text("Не удалось скачать голосовое сообщение.")
        return

    text = await _transcribe_telegram_voice(bytes(raw))
    if not text:
        await msg.reply_text("Не удалось распознать речь.")
        return

    await msg.reply_text(f"🗣 {text}")
    _hist_add(uid, "user", text)

    if _detect_video_intent(text):
        await _ask_video_engine(update, context, text)
        return

    try:
        ans = await _gpt_chat(uid, [{"role": "user", "content": text}])
        await msg.reply_text(ans)
        _hist_add(uid, "assistant", ans)
    except Exception as e:
        log.exception("GPT error: %s", e)
        await msg.reply_text("Ошибка генерации ответа.")

# =============================
# Callback router
# =============================
async def on_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    data = (q.data or "").strip()
    if not data:
        await q.answer()
        return

    try:
        # Language
        if data.startswith("lang:"):
            await on_lang_callback(update, context)
            return

        # Plans
        if data.startswith("plan:"):
            _, plan_key = data.split(":", 1)
            await on_plan_callback(update, context, plan_key)
            return

        if data == "plans:back":
            await q.answer()
            await cmd_plans(update, context)
            return

        if data.startswith("paid:"):
            _, plan_key = data.split(":", 1)
            await q.answer()
            await on_paid_callback(update, context, plan_key)
            return

        # Cancel
        if data.startswith("cancel:"):
            _, aid = data.split(":", 1)
            _pending_actions.pop(aid, None)
            _active_jobs.pop(uid, None)
            await q.answer()
            await q.message.reply_text(_tr(uid, "cancelled"), reply_markup=_main_menu_keyboard(uid))
            return

        # Repeat
        if data.startswith("repeat:"):
            _, arg = data.split(":", 1)
            arg = (arg or "").strip().lower()

            last = _last_video_prompt.get(uid) or {}
            lp = (last.get("prompt") or "").strip()
            if not lp:
                await q.answer()
                await q.message.reply_text(_tr(uid, "repeat_empty"))
                return

            if arg == "choose":
                await q.answer()
                await _ask_video_engine(update, context, lp)
                return
            if arg in ("kling", "luma", "sora"):
                await q.answer()
                await _ask_video_engine(update, context, lp)
                return

            await q.answer()
            return

        # Animate photo ✅ FIXED
        if data.startswith("animate_photo:"):
            _, aid = data.split(":", 1)
            act = _pending_actions.get(aid) or {}
            photo_bytes = act.get("photo_bytes")
            if not photo_bytes:
                await q.answer()
                await q.message.reply_text(_tr(uid, "photo_missing_retry"))
                return

            seconds = int(act.get("seconds") or RUNWAY_DURATION_S)
            aspect = str(act.get("aspect") or RUNWAY_RATIO)
            seconds = enforce_seconds_limit(seconds, get_subscription_tier(uid))
            aspect = normalize_aspect(aspect)

            # lock one job per user
            if _active_jobs.get(uid):
                await q.answer()
                await q.message.reply_text("⏳ Уже идёт генерация. Подождите или отмените предыдущую.")
                return

            _active_jobs[uid] = {"ts": int(time.time()), "engine": "Runway", "aid": aid}

            await q.answer()
            await _engine_confirm(q.message, uid, "runway")

            try:
                await _safe_edit_or_reply(
                    q.message,
                    _tr(uid, "engine_rendering", name="Runway"),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(_tr(uid, "cancel_btn"), callback_data=f"cancel:{aid}")]]),
                )
            except Exception:
                pass

            try:
                await _run_runway_animate_photo(update, context, photo_bytes, seconds=seconds, aspect=aspect)
            finally:
                _active_jobs.pop(uid, None)
                _pending_actions.pop(aid, None)
            return

        # setdur
        if data.startswith("setdur:"):
            parts = data.split(":")
            if len(parts) != 3:
                await q.answer()
                return
            _, sec_s, aid = parts
            act = _pending_actions.get(aid)
            if not act:
                await q.answer()
                await q.message.reply_text("⌛ Кнопка устарела. Отправьте запрос заново.")
                return
            sec = normalize_seconds(int(sec_s))
            sec = enforce_seconds_limit(sec, get_subscription_tier(uid))
            act["duration"] = sec
            act["ts"] = int(time.time())

            prompt = (act.get("prompt") or "").strip()
            aspect = normalize_aspect(str(act.get("aspect") or "16:9"))
            await q.answer()
            await q.message.edit_text(_tr(uid, "video_opts", dur=sec, asp=aspect, prompt=prompt), reply_markup=_video_engine_kb(aid, uid))
            return

        # setasp
        if data.startswith("setasp:"):
            parts = data.split(":")
            if len(parts) != 4:
                await q.answer()
                return
            _, a1, a2, aid = parts
            act = _pending_actions.get(aid)
            if not act:
                await q.answer()
                await q.message.reply_text("⌛ Кнопка устарела. Отправьте запрос заново.")
                return
            asp = normalize_aspect(f"{a1}:{a2}")
            act["aspect"] = asp
            act["ts"] = int(time.time())
            prompt = (act.get("prompt") or "").strip()
            dur = enforce_seconds_limit(int(act.get("duration") or 5), get_subscription_tier(uid))
            await q.answer()
            await q.message.edit_text(_tr(uid, "video_opts", dur=dur, asp=asp, prompt=prompt), reply_markup=_video_engine_kb(aid, uid))
            return

        # choose engine
        if data.startswith("choose:"):
            parts = data.split(":")
            if len(parts) != 3:
                await q.answer()
                return
            _, engine, aid = parts
            act = _pending_actions.get(aid) or {}

            prompt = (act.get("prompt") or "").strip()
            duration = enforce_seconds_limit(int(act.get("duration") or 5), get_subscription_tier(uid))
            aspect = normalize_aspect(str(act.get("aspect") or "16:9"))

            if not prompt:
                await q.answer()
                await q.message.reply_text("Промпт пустой. Напишите запрос заново.")
                return

            # one job per user
            if _active_jobs.get(uid):
                await q.answer()
                await q.message.reply_text("⏳ Уже идёт генерация. Подождите или отмените.")
                return

            # store last engine for repeat
            _last_video_prompt.setdefault(uid, {})["engine"] = engine

            await q.answer()
            await _engine_confirm(q.message, uid, engine)

            _active_jobs[uid] = {"ts": int(time.time()), "engine": ENGINE_INFO.get(engine, {}).get("name", engine), "aid": aid}

            try:
                await _safe_edit_or_reply(
                    q.message,
                    _tr(uid, "engine_rendering", name=ENGINE_INFO.get(engine, {}).get("name", engine)),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(_tr(uid, "cancel_btn"), callback_data=f"cancel:{aid}")]]),
                )
            except Exception:
                pass

            try:
                if engine == "kling":
                    await _run_kling_video(update, context, prompt, duration, aspect)
                elif engine == "luma":
                    await _run_luma_video(update, context, prompt, duration, aspect)
                elif engine == "sora":
                    await _run_sora_video(update, context, prompt, duration, aspect)
                else:
                    await q.message.reply_text("⚠️ Неизвестный движок.")
            finally:
                _active_jobs.pop(uid, None)
                _pending_actions.pop(aid, None)
            return

        await q.answer()
        await q.message.reply_text("⚠️ Неизвестное действие.")
        return

    except Exception as e:
        log.exception("on_callback_query error: %s", e)
        try:
            await q.answer()
        except Exception:
            pass
        try:
            await q.message.reply_text(_tr(uid, "err_button_failed"))
        except Exception:
            pass

# =============================
# Cleanup loop
# =============================
async def _cleanup_loop(app: Application):
    while True:
        try:
            now = int(time.time())
            for aid, act in list(_pending_actions.items()):
                ts = int(act.get("ts") or 0)
                if ts and (now - ts) > PENDING_TTL_S:
                    _pending_actions.pop(aid, None)
            for u, job in list(_active_jobs.items()):
                ts = int(job.get("ts") or 0)
                if ts and (now - ts) > ACTIVE_JOB_TTL_S:
                    _active_jobs.pop(u, None)
        except Exception as e:
            log.warning("cleanup loop error: %s", e)
        await asyncio.sleep(30)

# =============================
# Register / Build app
# =============================
def register_all_handlers(app: Application):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("history", cmd_history))

    app.add_handler(CallbackQueryHandler(on_callback_query))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

def build_app() -> Application:
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )
    register_all_handlers(app)
    app.job_queue.run_once(lambda ctx: asyncio.create_task(_cleanup_loop(app)), when=1)
    return app

# =============================
# Main
# =============================
def main():
    if not APP_URL:
        raise RuntimeError("APP_URL/PUBLIC_URL is required for webhook mode.")

    app = build_app()

    path = WEBHOOK_PATH if WEBHOOK_PATH.startswith("/") else f"/{WEBHOOK_PATH}"
    webhook_full = f"{APP_URL.rstrip('/')}{path}"

    log.info(
        "Bot started in WEBHOOK mode: %s | flags=%s",
        webhook_full,
        {"KLING": KLING_ENABLED, "LUMA": LUMA_ENABLED, "RUNWAY": RUNWAY_ENABLED, "SORA": SORA_ENABLED, "SUNO": SUNO_ENABLED},
    )

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=path.lstrip("/"),
        webhook_url=webhook_full,
        secret_token=(WEBHOOK_SECRET or None),
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
