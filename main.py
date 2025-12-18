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
from telegram.error import TelegramError

# ───────── TTS imports ─────────

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
def _env(key: str, default: str | None = None) -> str | None:
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

# =============================
# Telegram / General
# =============================
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

APP_URL = (_env("APP_URL") or "").strip()
PORT = _env_int("PORT", 10000)

# =============================
# HTTP / Comet
# =============================
HTTP_TIMEOUT = _env_float("HTTP_TIMEOUT", 60.0)
VIDEO_POLL_DELAY_S = _env_int("VIDEO_POLL_DELAY_S", 5)

COMET_API_KEY = (
    (_env("COMET_API_KEY") or "")
    or (_env("COMETAPI_KEY") or "")
    or (_env("SORA_API_KEY") or "")
).strip()

COMET_BASE_URL = (_env("COMET_BASE_URL") or "https://api.cometapi.com").rstrip("/")

# =============================
# Provider toggles
# =============================
KLING_ENABLED = (_env("KLING_ENABLED") or "1").strip() != "0"
LUMA_ENABLED = (_env("LUMA_ENABLED") or "1").strip() != "0"

# Runway: оставляем для image->video (оживить фото). Для text/voice->video — отключаем в UI/логике.
RUNWAY_ENABLED = (_env("RUNWAY_ENABLED") or "1").strip() != "0"
RUNWAY_BASE_URL = (_env("RUNWAY_BASE_URL") or "").rstrip("/")
RUNWAY_MODEL = (_env("RUNWAY_MODEL") or "gen3a_turbo").strip()
RUNWAY_API_KEY = (_env("RUNWAY_API_KEY") or "").strip()

# Sora через Comet
SORA_ENABLED = (_env("SORA_ENABLED") or "1").strip() != "0"
SORA_BASE_URL = (_env("SORA_BASE_URL") or f"{COMET_BASE_URL}/v1").rstrip("/")
SORA_MODEL_DEFAULT = (_env("SORA_MODEL_DEFAULT") or "sora-2").strip()
SORA_MODEL_PRO = (_env("SORA_MODEL_PRO") or "sora-2-pro").strip()
SORA_MAX_WAIT_S = _env_int("SORA_MAX_WAIT_S", 900)

# =============================
WEBHOOK_PATH = (_env("WEBHOOK_PATH") or "/telegram").strip()
WEBHOOK_SECRET = (_env("WEBHOOK_SECRET") or "").strip()  # опционально

# Costs (estimates)
# =============================
KLING_UNIT_COST_USD = _env_float("KLING_UNIT_COST_USD", 0.40)
LUMA_UNIT_COST_USD = _env_float("LUMA_UNIT_COST_USD", 0.40)
SORA_UNIT_COST_USD = _env_float("SORA_UNIT_COST_USD", 0.10)  # дефолт для sora-2
SORA_PRO_UNIT_COST_USD = _env_float("SORA_PRO_UNIT_COST_USD", 0.30)  # для sora-2-pro (720p)

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
    db_exec(
        """
        CREATE TABLE IF NOT EXISTS kv (
            k TEXT PRIMARY KEY,
            v TEXT
        )
        """
    )
    db_exec(
        """
        CREATE TABLE IF NOT EXISTS spend (
            user_id INTEGER,
            engine TEXT,
            usd REAL,
            ts INTEGER
        )
        """
    )
    db_exec(
        """
        CREATE TABLE IF NOT EXISTS subs (
            user_id INTEGER PRIMARY KEY,
            tier TEXT,
            ts INTEGER
        )
        """
    )

db_init()

def kv_get(key: str, default: str | None = None) -> str | None:
    row = db_exec("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return (row["v"] if row else default)

def kv_set(key: str, value: str):
    db_exec("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (key, value))

# =============================
# Language system
# =============================
LANGS = {
    "ru": "Русский",
    "be": "Белорусский",
    "uk": "Украинский",
    "de": "Deutsch",
    "en": "English",
    "fr": "Français",
    "th": "ไทย",
}
DEFAULT_LANG = (_env("DEFAULT_LANG") or "ru").strip()

def get_lang(user_id: int) -> str:
    v = kv_get(f"lang:{user_id}", None)
    if v in LANGS:
        return v
    return DEFAULT_LANG

def set_lang(user_id: int, lang: str):
    if lang in LANGS:
        kv_set(f"lang:{user_id}", lang)

# Мини-словарь (полные пакеты дальше по файлу)
I18N: dict[str, dict[str, str]] = {
    "ru": {
        "choose_lang": "🌍 Выберите язык",
        "lang_set": "✅ Язык установлен",
        "menu_title": "Главное меню",
        "btn_video": "🎞 Создать видео",
        "btn_photo": "🖼 Оживить фото",
        "btn_help": "❓ Помощь",
    },
    "en": {
        "choose_lang": "🌍 Choose language",
        "lang_set": "✅ Language set",
        "menu_title": "Main menu",
        "btn_video": "🎞 Create video",
        "btn_photo": "🖼 Animate photo",
        "btn_help": "❓ Help",
    },
}

def t(user_id: int, key: str) -> str:
    lang = get_lang(user_id)
    return (I18N.get(lang) or I18N["ru"]).get(key, key)

def system_prompt_for(lang: str) -> str:
    """
    GPT system prompt that forces output language.
    """
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

# =============================
# Pending actions
# =============================
_pending_actions: dict[str, dict] = {}

def _new_aid() -> str:
    return uuid.uuid4().hex

# === END PART 1 ===

# =============================
# Subscription / Limits
# =============================
LIMITS = {
    "free":      {"text_per_day": 5,    "luma_budget_usd": 0.40, "sora_budget_usd": 0.0},
    "start":     {"text_per_day": 200,  "luma_budget_usd": 0.80, "sora_budget_usd": 0.0},
    "pro":       {"text_per_day": 1000, "luma_budget_usd": 4.00, "sora_budget_usd": 10.0},
    "ultimate":  {"text_per_day": 5000, "luma_budget_usd": 8.00, "sora_budget_usd": 25.0},
}

def get_subscription_tier(user_id: int) -> str:
    row = db_exec("SELECT tier FROM subs WHERE user_id=?", (user_id,)).fetchone()
    if row and row["tier"]:
        return row["tier"]
    return "free"

def set_subscription_tier(user_id: int, tier: str):
    if tier not in LIMITS:
        tier = "free"
    db_exec("INSERT OR REPLACE INTO subs(user_id,tier,ts) VALUES(?,?,?)",
            (user_id, tier, int(time.time())))

def _pick_sora_model(user_id: int) -> str:
    tier = (get_subscription_tier(user_id) or "free").lower()
    return SORA_MODEL_PRO if tier in ("pro", "ultimate") else SORA_MODEL_DEFAULT

def _sora_est_cost_usd(user_id: int, seconds: int) -> float:
    tier = (get_subscription_tier(user_id) or "free").lower()
    if tier in ("pro", "ultimate"):
        return max(0.01, SORA_PRO_UNIT_COST_USD * float(seconds))
    return max(0.01, SORA_UNIT_COST_USD * float(seconds))

def _register_engine_spend(user_id: int, engine: str, usd: float):
    db_exec(
        "INSERT INTO spend(user_id,engine,usd,ts) VALUES(?,?,?,?)",
        (user_id, engine, float(usd), int(time.time())),
    )

def _spent_today(user_id: int, engine: str) -> float:
    since = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
    row = db_exec(
        "SELECT COALESCE(SUM(usd),0) AS s FROM spend WHERE user_id=? AND engine=? AND ts>=?",
        (user_id, engine, since),
    ).fetchone()
    return float(row["s"] if row else 0.0)

def _can_spend(user_id: int, engine: str, usd: float) -> bool:
    tier = get_subscription_tier(user_id)
    limits = LIMITS.get(tier, LIMITS["free"])
    if engine == "luma":
        return (_spent_today(user_id, "luma") + usd) <= float(limits.get("luma_budget_usd", 0.0))
    if engine == "sora":
        return (_spent_today(user_id, "sora") + usd) <= float(limits.get("sora_budget_usd", 0.0))
    # kling/runway/img etc. — оставляем как было или безлимит, зависит от твоей логики
    return True

async def _try_pay_then_do(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int,
                          engine: str, est_usd: float, coro):
    if not _can_spend(user_id, engine, est_usd):
        await update.effective_message.reply_text("⛔ Лимит исчерпан. Обновите подписку.")
        return
    await coro()

# =============================
# UI: Language chooser
# =============================
def _lang_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for code, name in LANGS.items():
        rows.append([InlineKeyboardButton(name, callback_data=f"lang:{code}")])
    return InlineKeyboardMarkup(rows)

def _main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t(user_id, "btn_video")), KeyboardButton(t(user_id, "btn_photo"))],
            [KeyboardButton(t(user_id, "btn_help"))],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Если язык ещё не выбран — показываем панель
    lang = get_lang(user_id)
    if kv_get(f"lang:{user_id}", None) is None:
        await update.effective_message.reply_text(
            t(user_id, "choose_lang"),
            reply_markup=_lang_keyboard(),
        )
        return

    await update.effective_message.reply_text(
        t(user_id, "menu_title"),
        reply_markup=_main_menu_keyboard(user_id),
    )

async def on_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()
    user_id = update.effective_user.id
    if not data.startswith("lang:"):
        return
    code = data.split(":", 1)[1]
    if code not in LANGS:
        await q.answer()
        return
    set_lang(user_id, code)
    await q.answer()

    await q.edit_message_text(f"{t(user_id, 'lang_set')}: {LANGS[code]}")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=t(user_id, "menu_title"),
        reply_markup=_main_menu_keyboard(user_id),
    )

# =============================
# Video intent detection (text/voice)
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
    for p in _VIDEO_PREFIXES:
        if re.search(p, tl, re.I):
            return True
    return False

def _parse_video_opts(text: str) -> tuple[int, str]:
    duration = 5
    aspect = "16:9"
    m = re.search(r"(\d+)\s*(сек|s)", text, re.I)
    if m:
        try:
            duration = max(1, min(30, int(m.group(1))))
        except Exception:
            pass
    if "9:16" in text or "вертик" in text.lower():
        aspect = "9:16"
    elif "1:1" in text:
        aspect = "1:1"
    return duration, aspect

def _aspect_to_size(aspect: str) -> str:
    if aspect == "9:16":
        return "720x1280"
    if aspect == "1:1":
        return "1024x1024"
    return "1280x720"

# === END PART 2 ===

# =============================
# Full language pack (menus/buttons/answers)
# =============================

I18N_PACK: dict[str, dict[str, str]] = {
    "welcome": {
        "ru": "Добро пожаловать! Выберите режим или напишите запрос.",
        "be": "Сардэчна запрашаем! Абярыце рэжым або напішыце запыт.",
        "uk": "Ласкаво просимо! Оберіть режим або напишіть запит.",
        "de": "Willkommen! Wähle einen Modus oder schreibe eine Anfrage.",
        "en": "Welcome! Choose a mode or type your request.",
        "fr": "Bienvenue ! Choisissez un mode ou écrivez votre demande.",
        "th": "ยินดีต้อนรับ! เลือกโหมดหรือพิมพ์คำขอของคุณ",
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
    "video_opts": {
        "ru": "Что использовать?\nДлительность: {dur} с • Аспект: {asp}\nЗапрос: «{prompt}»",
        "be": "Што выкарыстоўваць?\nПрацягласць: {dur} c • Аспект: {asp}\nЗапыт: «{prompt}»",
        "uk": "Що використати?\nТривалість: {dur} с • Аспект: {asp}\nЗапит: «{prompt}»",
        "de": "Was verwenden?\nDauer: {dur}s • Seitenverhältnis: {asp}\nPrompt: „{prompt}“",
        "en": "What to use?\nDuration: {dur}s • Aspect: {asp}\nPrompt: “{prompt}”",
        "fr": "Que choisir ?\nDurée : {dur}s • Ratio : {asp}\nPrompt : « {prompt} »",
        "th": "ใช้ตัวไหน?\nความยาว: {dur} วิ • อัตราส่วน: {asp}\nคำสั่ง: “{prompt}”",
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
    "rendering": {
        "ru": "⏳ Рендерю…",
        "be": "⏳ Рэндэр…",
        "uk": "⏳ Рендерю…",
        "de": "⏳ Rendere…",
        "en": "⏳ Rendering…",
        "fr": "⏳ Rendu…",
        "th": "⏳ กำลังสร้าง…",
    },
    "done": {
        "ru": "✅ Готово!",
        "be": "✅ Гатова!",
        "uk": "✅ Готово!",
        "de": "✅ Fertig!",
        "en": "✅ Done!",
        "fr": "✅ Terminé !",
        "th": "✅ เสร็จแล้ว!",
    },
    "help": {
        "ru": "❓ Помощь: напиши «сделай видео …» или пришли фото и нажми «Оживить фото».",
        "be": "❓ Дапамога: напішы «зрабі відэа …» або дашлі фота і націсні «Ажывіць фота».",
        "uk": "❓ Допомога: напиши «зроби відео …» або надішли фото й натисни «Оживити фото».",
        "de": "❓ Hilfe: schreibe „make video …“ oder sende ein Foto und drücke „Animate photo“.",
        "en": "❓ Help: type “make video …” or send a photo and tap “Animate photo”.",
        "fr": "❓ Aide : écrivez « make video … » ou envoyez une photo puis « Animate photo ».",
        "th": "❓ วิธีใช้: พิมพ์ “ทำวิดีโอ …” หรือส่งรูปแล้วกด “ทำให้รูปเคลื่อนไหว”",
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

def _mk_menu_kb(user_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t(user_id, "btn_video")), KeyboardButton(t(user_id, "btn_photo"))],
            [KeyboardButton(t(user_id, "btn_help"))],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.effective_message.reply_text(_tr(uid, "help"), reply_markup=_mk_menu_kb(uid))

def _video_engine_kb(aid: str, user_id: int) -> InlineKeyboardMarkup:
    tier = get_subscription_tier(user_id)
    rows = []

    # Kling + Luma всегда
    if KLING_ENABLED:
        rows.append([InlineKeyboardButton(f"📼 Kling (~${KLING_UNIT_COST_USD:.2f})", callback_data=f"choose:kling:{aid}")])
    if LUMA_ENABLED:
        rows.append([InlineKeyboardButton(f"🎞 Luma (~${LUMA_UNIT_COST_USD:.2f})", callback_data=f"choose:luma:{aid}")])

    # Sora: доступна всем, но sora-2-pro = pro/ultimate
    if SORA_ENABLED:
        if tier in ("pro", "ultimate"):
            rows.append([InlineKeyboardButton("✨ Sora 2 Pro", callback_data=f"choose:sora:{aid}")])
        else:
            rows.append([InlineKeyboardButton("✨ Sora 2", callback_data=f"choose:sora:{aid}")])

    return InlineKeyboardMarkup(rows)

async def _ask_video_engine(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    uid = update.effective_user.id
    dur, asp = _parse_video_opts(prompt)

    aid = _new_aid()
    _pending_actions[aid] = {"prompt": prompt, "duration": dur, "aspect": asp}

    await update.effective_message.reply_text(
        _tr(uid, "video_opts", dur=dur, asp=asp, prompt=prompt),
        reply_markup=_video_engine_kb(aid, uid),
    )

# =============================
# OpenAI / GPT client placeholders
# (оставляем интерфейс, реализация у тебя ниже по файлу)
# =============================
OPENAI_API_KEY = (_env("OPENAI_API_KEY") or "").strip()
OPENAI_BASE_URL = (_env("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")

def _oai_headers():
    return {"Authorization": f"Bearer {OPENAI_API_KEY}"}

def _oai_client():
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True)

def _oai_stt_client():
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True)

async def _gpt_chat(user_id: int, messages: list[dict], model: str = "gpt-4o-mini") -> str:
    """
    GPT ответ ДОЛЖЕН идти на выбранном языке.
    Мы добавляем system-подсказку в messages.
    """
    lang = get_lang(user_id)
    sys_msg = {"role": "system", "content": system_prompt_for(lang)}
    payload = {
        "model": model,
        "messages": [sys_msg] + messages,
        "temperature": 0.7,
    }
    url = f"{OPENAI_BASE_URL}/chat/completions"
    async with _oai_client() as client:
        r = await client.post(url, headers=_oai_headers(), json=payload)
        r.raise_for_status()
        js = r.json()
        return (js["choices"][0]["message"]["content"] or "").strip()

# =============================
# Whisper / STT (voice -> text) helpers
# =============================
WHISPER_MODEL = (_env("WHISPER_MODEL") or "whisper-1").strip()

async def _transcribe_telegram_voice(file_bytes: bytes, filename: str = "voice.ogg") -> str:
    if not OPENAI_API_KEY:
        return ""
    url = f"{OPENAI_BASE_URL}/audio/transcriptions"

    # Multipart/form-data
    data = {
        "model": WHISPER_MODEL,
    }
    files = {
        "file": (filename, file_bytes, "audio/ogg"),
    }

    last_err = None
    for _ in range(2):
        try:
            async with _oai_stt_client() as client:
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

# ============================================================
# VOICE HANDLER (voice -> STT -> intent)
# ============================================================

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = update.effective_user.id

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

    # STT
    text = await _transcribe_telegram_voice(bytes(raw))
    if not text:
        await msg.reply_text("Не удалось распознать речь.")
        return

    await msg.reply_text(f"🗣 {text}")

    # video intent
    if _detect_video_intent(text):
        await _ask_video_engine(update, context, text)
        return

    # обычный GPT
    try:
        ans = await _gpt_chat(uid, [{"role": "user", "content": text}])
        await msg.reply_text(ans)
    except Exception as e:
        log.exception("GPT error: %s", e)
        await msg.reply_text("Ошибка генерации ответа.")


# ============================================================
# TEXT HANDLER
# ============================================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = update.effective_user.id
    text = (msg.text or "").strip()
    if not text:
        return

    # меню
    if text == t(uid, "btn_help"):
        await cmd_help(update, context)
        return

    if text == t(uid, "btn_video"):
        await msg.reply_text(
            "🎞 Напиши запрос для видео, например:\n"
            "«Сделай видео: закат над морем, 7 сек, 16:9»"
        )
        return

    if text == t(uid, "btn_photo"):
        await msg.reply_text("🖼 Пришли фото, затем выбери «Оживить фото».")
        return

    # video intent
    if _detect_video_intent(text):
        await _ask_video_engine(update, context, text)
        return

    # обычный GPT
    try:
        ans = await _gpt_chat(uid, [{"role": "user", "content": text}])
        await msg.reply_text(ans)
    except Exception as e:
        log.exception("GPT error: %s", e)
        await msg.reply_text("Ошибка генерации ответа.")


# === END PART 4 ===

# ============================================================
# KLING — TEXT / VOICE -> VIDEO
# ============================================================

async def _run_kling_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    seconds: int,
    aspect: str,
):
    msg = update.effective_message
    uid = update.effective_user.id

    if not KLING_ENABLED:
        await msg.reply_text("Kling отключён.")
        return
    if not COMET_API_KEY:
        await msg.reply_text("Kling: нет COMET_API_KEY.")
        return

    await msg.reply_text(_tr(uid, "rendering"))

    payload = {
        "prompt": prompt.strip(),
        "seconds": int(seconds),
        "ratio": aspect,
    }

    headers = {
        "Authorization": f"Bearer {COMET_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.post(
                f"{COMET_BASE_URL}/kling/v1/text_to_video",
                headers=headers,
                json=payload,
            )

            if r.status_code >= 400:
                await msg.reply_text(
                    f"⚠️ Kling отклонил задачу ({r.status_code}).\n{(r.text or '')[:1000]}"
                )
                return

            js = r.json() or {}
            task_id = js.get("id") or js.get("task_id")
            if not task_id:
                await msg.reply_text("Kling: не вернулся task_id.")
                return

            status_url = f"{COMET_BASE_URL}/kling/v1/tasks/{task_id}"
            started = time.time()

            while True:
                rs = await client.get(status_url, headers=headers)
                if rs.status_code >= 400:
                    await msg.reply_text(
                        f"⚠️ Kling: ошибка статуса ({rs.status_code}).\n{(rs.text or '')[:1000]}"
                    )
                    return

                st_js = rs.json() or {}
                st = (st_js.get("status") or "").lower()

                if st in ("completed", "succeeded", "done"):
                    out = st_js.get("output") or {}
                    video_url = out.get("url") or out.get("video_url")
                    if not video_url:
                        await msg.reply_text("Kling: нет ссылки на видео.")
                        return

                    vr = await client.get(video_url, timeout=180.0)
                    if vr.status_code >= 400:
                        await msg.reply_text(f"Kling: не удалось скачать видео ({vr.status_code}).")
                        return

                    bio = BytesIO(vr.content)
                    bio.name = "kling.mp4"

                    await context.bot.send_video(
                        chat_id=update.effective_chat.id,
                        video=bio,
                        supports_streaming=True,
                    )
                    await msg.reply_text(_tr(uid, "done"))
                    return

                if st in ("failed", "error", "rejected", "cancelled", "canceled"):
                    await msg.reply_text(f"❌ Kling: ошибка генерации.\n{st_js}")
                    return

                if time.time() - started > 900:
                    await msg.reply_text("⌛ Kling: превышено время ожидания.")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Kling exception: %s", e)
        await msg.reply_text("❌ Ошибка Kling.")


# ============================================================
# LUMA — TEXT / VOICE -> VIDEO
# ============================================================

async def _run_luma_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    seconds: int,
    aspect: str,
):
    msg = update.effective_message
    uid = update.effective_user.id

    if not LUMA_ENABLED:
        await msg.reply_text("Luma отключена.")
        return
    if not COMET_API_KEY:
        await msg.reply_text("Luma: нет COMET_API_KEY.")
        return

    await msg.reply_text(_tr(uid, "rendering"))

    payload = {
        "prompt": prompt.strip(),
        "seconds": int(seconds),
        "ratio": aspect,
    }

    headers = {
        "Authorization": f"Bearer {COMET_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.post(
                f"{COMET_BASE_URL}/luma/v1/text_to_video",
                headers=headers,
                json=payload,
            )

            if r.status_code >= 400:
                await msg.reply_text(
                    f"⚠️ Luma отклонила задачу ({r.status_code}).\n{(r.text or '')[:1000]}"
                )
                return

            js = r.json() or {}
            task_id = js.get("id") or js.get("task_id")
            if not task_id:
                await msg.reply_text("Luma: не вернулся task_id.")
                return

            status_url = f"{COMET_BASE_URL}/luma/v1/tasks/{task_id}"
            started = time.time()

            while True:
                rs = await client.get(status_url, headers=headers)
                if rs.status_code >= 400:
                    await msg.reply_text(
                        f"⚠️ Luma: ошибка статуса ({rs.status_code}).\n{(rs.text or '')[:1000]}"
                    )
                    return

                st_js = rs.json() or {}
                st = (st_js.get("status") or "").lower()

                if st in ("completed", "succeeded", "done"):
                    out = st_js.get("output") or {}
                    video_url = out.get("url") or out.get("video_url")
                    if not video_url:
                        await msg.reply_text("Luma: нет ссылки на видео.")
                        return

                    vr = await client.get(video_url, timeout=180.0)
                    if vr.status_code >= 400:
                        await msg.reply_text(f"Luma: не удалось скачать видео ({vr.status_code}).")
                        return

                    bio = BytesIO(vr.content)
                    bio.name = "luma.mp4"

                    await context.bot.send_video(
                        chat_id=update.effective_chat.id,
                        video=bio,
                        supports_streaming=True,
                    )
                    await msg.reply_text(_tr(uid, "done"))
                    return

                if st in ("failed", "error", "rejected", "cancelled", "canceled"):
                    await msg.reply_text(f"❌ Luma: ошибка генерации.\n{st_js}")
                    return

                if time.time() - started > 900:
                    await msg.reply_text("⌛ Luma: превышено время ожидания.")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Luma exception: %s", e)
        await msg.reply_text("❌ Ошибка Luma.")


# === END PART 5 ===

# ──────────────────────────────────────────────────────────────────────────────
# CryptoBot (оплата)
# ──────────────────────────────────────────────────────────────────────────────

CRYPTOBOT_TOKEN = (_env("CRYPTOBOT_TOKEN") or "").strip()
CRYPTOBOT_BASE = (_env("CRYPTOBOT_BASE") or "https://pay.crypt.bot").rstrip("/")
CRYPTOBOT_API = (_env("CRYPTOBOT_API") or "https://pay.crypt.bot/api").rstrip("/")

PLANS = {
    "start": {
        "title": "START",
        "price_usdt": float(_env_float("PLAN_START_PRICE", 19.0)),
        "desc": "Повышенные лимиты + доступ к Luma.",
        "tier": "start",
    },
    "pro": {
        "title": "PRO",
        "price_usdt": float(_env_float("PLAN_PRO_PRICE", 49.0)),
        "desc": "Сильно повышенные лимиты + доступ к Sora 2 Pro.",
        "tier": "pro",
    },
    "ultimate": {
        "title": "ULTIMATE",
        "price_usdt": float(_env_float("PLAN_ULTIMATE_PRICE", 99.0)),
        "desc": "Максимальные лимиты + Sora 2 Pro.",
        "tier": "ultimate",
    },
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
            log.warning("CryptoBot createInvoice status=%s text=%s", r.status_code, (r.text or "")[:400])
            return None
        js = r.json() or {}
        if not js.get("ok"):
            log.warning("CryptoBot createInvoice not ok: %s", js)
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

async def _set_paid_tier(user_id: int, tier: str):
    set_subscription_tier(user_id, tier)

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    lines = []
    for k, p in PLANS.items():
        lines.append(f"• {p['title']}: {p['price_usdt']} USDT — {p['desc']}")
    txt = "💳 Тарифы:\n\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(p["title"], callback_data=f"plan:{k}")]] for k, p in PLANS.items())
    await update.effective_message.reply_text(txt, reply_markup=kb)

async def on_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_key: str):
    q = update.callback_query
    uid = update.effective_user.id
    plan = PLANS.get(plan_key)
    if not plan:
        await q.answer("Неизвестный тариф.", show_alert=True)
        return

    price = float(plan["price_usdt"])
    desc = plan["desc"]

    inv = await _cryptobot_create_invoice(price, f"GPT5PRO: {plan['title']} ({uid})")
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
            f"Тариф: {plan['title']}\nЦена: {price} USDT\n\n{desc}\n\n"
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
        await _set_paid_tier(uid, tier)
        await q.edit_message_text(f"✅ Оплата подтверждена. Тариф активирован: {tier}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t(uid, "menu_title"),
            reply_markup=_main_menu_keyboard(uid),
        )
    else:
        await q.answer(f"Статус оплаты: {status}", show_alert=True)

# ──────────────────────────────────────────────────────────────────────────────
# Callback router extension (plans)
# ──────────────────────────────────────────────────────────────────────────────

async def on_callback_query_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    q = update.callback_query
    data = (q.data or "").strip()

    if data == "plans:back":
        await q.answer()
        await cmd_plans(update, context)
        return True

    if data.startswith("plan:"):
        await q.answer()
        plan_key = data.split(":", 1)[1]
        await on_plan_callback(update, context, plan_key)
        return True

    if data.startswith("paid:"):
        await q.answer()
        plan_key = data.split(":", 1)[1]
        await on_paid_callback(update, context, plan_key)
        return True

    return False


# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# /start override: show language picker first
# ──────────────────────────────────────────────────────────────────────────────

_old_cmd_start = cmd_start

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if kv_get(f"lang:{uid}", None) is None:
        await update.effective_message.reply_text(
            t(uid, "choose_lang"),
            reply_markup=_lang_keyboard(),
        )
        return
    await _old_cmd_start(update, context)


# ──────────────────────────────────────────────────────────────────────────────
# /plans command
# ──────────────────────────────────────────────────────────────────────────────

# (cmd_plans already defined above)

# ──────────────────────────────────────────────────────────────────────────────
# Human-readable subscription status
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tier = get_subscription_tier(uid)
    luma_spent = _spent_today(uid, "luma")
    sora_spent = _spent_today(uid, "sora")
    lim = LIMITS.get(tier, LIMITS["free"])
    txt = (
        f"📊 Статус\n\n"
        f"Тариф: {tier}\n"
        f"Luma: потрачено ${luma_spent:.2f} / лимит ${float(lim.get('luma_budget_usd',0.0)):.2f}\n"
        f"Sora: потрачено ${sora_spent:.2f} / лимит ${float(lim.get('sora_budget_usd',0.0)):.2f}\n"
    )
    await update.effective_message.reply_text(txt)

# ──────────────────────────────────────────────────────────────────────────────
# End part
# ──────────────────────────────────────────────────────────────────────────────

# ============================================================
# PHOTO HANDLER
# ============================================================

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = update.effective_user.id

    if not msg.photo:
        return

    # Берём фото максимального размера
    photo = msg.photo[-1]

    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        tg_file = await context.bot.get_file(photo.file_id)
        raw = await tg_file.download_as_bytearray()
    except Exception as e:
        log.exception("Photo download error: %s", e)
        await msg.reply_text("Не удалось скачать фото.")
        return

    # Сохраняем во временный буфер
    bio = BytesIO(raw)
    bio.name = "photo.jpg"

    # Сохраняем в pending, чтобы кнопка знала, что оживлять
    aid = _new_aid()
    _pending_actions[aid] = {
        "photo_bytes": bytes(raw),
    }

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Оживить фото", callback_data=f"animate_photo:{aid}")],
    ])

    await msg.reply_text(
        "🖼 Фото получено. Хотите оживить?",
        reply_markup=kb,
    )


# ============================================================
# RUNWAY — IMAGE -> VIDEO (ТОЛЬКО ЗДЕСЬ)
# ============================================================

async def _run_runway_animate_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    photo_bytes: bytes,
    seconds: int = 5,
    aspect: str = "16:9",
):
    msg = update.effective_message
    uid = update.effective_user.id

    if not RUNWAY_ENABLED:
        await msg.reply_text("Runway отключён.")
        return

    if not RUNWAY_BASE_URL or not RUNWAY_MODEL:
        await msg.reply_text("Runway: не настроен.")
        return

    if not RUNWAY_API_KEY:
        await msg.reply_text("Runway: нет RUNWAY_API_KEY.")
        return
        
    headers = {
        "Authorization": f"Bearer {RUNWAY_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # 1) Загружаем изображение (Runway требует URL)
    # Используем data: URL
    img_b64 = base64.b64encode(photo_bytes).decode("ascii")
    image_url = f"data:image/jpeg;base64,{img_b64}"

    payload = {
        "model": RUNWAY_MODEL,
        "promptImage": image_url,
        "seconds": int(seconds),
        "ratio": aspect,
    }

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.post(
                f"{RUNWAY_BASE_URL}/image_to_video",
                headers=headers,
                json=payload,
            )

            if r.status_code >= 400:
                await msg.reply_text(
                    f"⚠️ Runway отклонил задачу ({r.status_code}).\n{(r.text or '')[:1000]}"
                )
                return

            js = r.json() or {}
            task_id = js.get("id") or js.get("task_id")
            if not task_id:
                await msg.reply_text("Runway: не вернулся task_id.")
                return

            status_url = f"{RUNWAY_BASE_URL}/tasks/{task_id}"
            started = time.time()

            while True:
                rs = await client.get(status_url, headers=headers)
                if rs.status_code >= 400:
                    await msg.reply_text(
                        f"⚠️ Runway: ошибка статуса ({rs.status_code}).\n{(rs.text or '')[:1000]}"
                    )
                    return

                st_js = rs.json() or {}
                st = (st_js.get("status") or "").lower()

                if st in ("completed", "succeeded", "done"):
                    out = st_js.get("output") or {}
                    video_url = out.get("url") or out.get("video_url")
                    if not video_url:
                        await msg.reply_text("Runway: нет ссылки на видео.")
                        return

                    vr = await client.get(video_url, timeout=180.0)
                    if vr.status_code >= 400:
                        await msg.reply_text(f"Runway: не удалось скачать видео ({vr.status_code}).")
                        return

                    bio = BytesIO(vr.content)
                    bio.name = "runway.mp4"

                    await context.bot.send_video(
                        chat_id=update.effective_chat.id,
                        video=bio,
                        supports_streaming=True,
                    )
                    await msg.reply_text(_tr(uid, "done"))
                    return

                if st in ("failed", "error", "rejected", "cancelled", "canceled"):
                    await msg.reply_text(f"❌ Runway: ошибка генерации.\n{st_js}")
                    return

                if time.time() - started > 900:
                    await msg.reply_text("⌛ Runway: превышено время ожидания.")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Runway exception: %s", e)
        await msg.reply_text("❌ Ошибка Runway.")


# ============================================================
# CALLBACK EXTENSION: animate_photo
# ============================================================

async def on_callback_query_animate_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    q = update.callback_query
    data = (q.data or "").strip()
    uid = update.effective_user.id

    if not data.startswith("animate_photo:"):
        return False

    await q.answer()

    aid = data.split(":", 1)[1]
    meta = _pending_actions.pop(aid, None)
    if not meta:
        await q.answer("Задача устарела.", show_alert=True)
        return True

    photo_bytes = meta.get("photo_bytes")
    if not photo_bytes:
        await q.answer("Фото не найдено.", show_alert=True)
        return True

    await _run_runway_animate_photo(update, context, photo_bytes)
    return True

# ============================================================
# CALLBACK ROUTER — SINGLE (lang + plans + animate_photo + engines)
# ============================================================

async def on_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()
    uid = update.effective_user.id

    # 1) Language
    if data.startswith("lang:"):
        await on_lang_callback(update, context)
        return

    # 2) Plans / payments
    if data == "plans:back" or data.startswith("plan:") or data.startswith("paid:"):
        handled = await on_callback_query_plans(update, context)
        if handled:
            return

    # 3) Animate photo
    if data.startswith("animate_photo:"):
        handled = await on_callback_query_animate_photo(update, context)
        if handled:
            return

    # 4) Hard-disable Runway for text/voice → video
    if data.startswith("choose:runway:"):
        await q.answer(_tr(uid, "runway_disabled_textvideo"), show_alert=True)
        return

    # 5) Engine choose (Kling/Luma/Sora)
    if not data.startswith("choose:"):
        await q.answer()
        return

    await q.answer()

    try:
        _, engine, aid = data.split(":", 2)
    except Exception:
        await q.answer("Некорректная кнопка.", show_alert=True)
        return

    meta = _pending_actions.pop(aid, None)
    if not meta:
        await q.answer("Задача устарела.", show_alert=True)
        return

    prompt = meta.get("prompt", "")
    duration = int(meta.get("duration", 5))
    aspect = meta.get("aspect", "16:9")

    if engine == "kling":
        est = float(KLING_UNIT_COST_USD or 0.40)

        async def _do():
            await _run_kling_video(update, context, prompt, duration, aspect)
            _register_engine_spend(uid, "kling", est)

        await _try_pay_then_do(update, context, uid, "kling", est, _do)
        return

    if engine == "luma":
        est = float(LUMA_UNIT_COST_USD or 0.40)

        async def _do():
            await _run_luma_video(update, context, prompt, duration, aspect)
            _register_engine_spend(uid, "luma", est)

        await _try_pay_then_do(update, context, uid, "luma", est, _do)
        return

    if engine == "sora":
        est = _sora_est_cost_usd(uid, duration)

        async def _do():
            await _run_sora_video(update, context, prompt, duration, aspect)
            _register_engine_spend(uid, "sora", est)

        await _try_pay_then_do(update, context, uid, "sora", est, _do)
        return

    await q.answer("Неизвестный движок.", show_alert=True)


# ============================================================
# PATCH CALLBACK ROUTER (add animate_photo)
# ============================================================

# === END PART 7 ===

# ============================================================
# REGISTER ALL HANDLERS
# ============================================================

def register_all_handlers(app: Application):
    # commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("status", cmd_status))

    # callbacks (buttons)
    app.add_handler(CallbackQueryHandler(on_callback_query))

    # media
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    # text (last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))


# ============================================================

def build_app() -> Application:
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    register_all_handlers(app)
    return app


# ============================================================
# MAIN ENTRYPOINT — WEBHOOK ONLY
# ============================================================

# === END PART 8 ===

# ============================================================
# UTILITIES / FALLBACKS / COMPATIBILITY
# ============================================================

# ------------------------------------------------------------
# Safe send helpers (Telegram sometimes fails on large files)
# ------------------------------------------------------------

async def safe_send_video(context: ContextTypes.DEFAULT_TYPE, chat_id: int, bio: BytesIO, caption: str | None = None):
    try:
        await context.bot.send_video(
            chat_id=chat_id,
            video=bio,
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
            document=bio,
            caption=caption,
        )
        return True
    except Exception as e:
        log.error("send_document failed: %s", e)
        return False


# ------------------------------------------------------------
# Normalize aspect / seconds (extra safety)
# ------------------------------------------------------------

def normalize_seconds(sec: int) -> int:
    try:
        sec = int(sec)
    except Exception:
        sec = 5
    return max(1, min(30, sec))

def normalize_aspect(aspect: str) -> str:
    if aspect in ("16:9", "9:16", "1:1"):
        return aspect
    return "16:9"


# ------------------------------------------------------------
# Legacy compatibility shims
# (если старый код где-то всё ещё вызывает эти имена)
# ------------------------------------------------------------

async def run_kling_video(*args, **kwargs):
    log.warning("run_kling_video is deprecated, use _run_kling_video")
    return await _run_kling_video(*args, **kwargs)

async def run_luma_video(*args, **kwargs):
    log.warning("run_luma_video is deprecated, use _run_luma_video")
    return await _run_luma_video(*args, **kwargs)

# ============================================================
# SORA — TEXT / VOICE -> VIDEO (через Comet)
# ============================================================

async def _run_sora_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    seconds: int,
    aspect: str,
):
    msg = update.effective_message
    uid = update.effective_user.id

    if not SORA_ENABLED:
        await msg.reply_text("Sora отключена.")
        return
    if not COMET_API_KEY:
        await msg.reply_text("Sora: нет COMET_API_KEY.")
        return

    seconds = max(1, min(30, int(seconds)))
    aspect = aspect if aspect in ("16:9", "9:16", "1:1") else "16:9"
    model = _pick_sora_model(uid)

    await msg.reply_text(_tr(uid, "rendering"))

    headers = {
        "Authorization": f"Bearer {COMET_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "model": model,
        "prompt": (prompt or "").strip(),
        "seconds": seconds,
        "ratio": aspect,
    }

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.post(
                f"{SORA_BASE_URL}/video/generations",
                headers=headers,
                json=payload,
            )
            if r.status_code >= 400:
                await msg.reply_text(f"⚠️ Sora отклонила задачу ({r.status_code}).\n{(r.text or '')[:1000]}")
                return

            js = r.json() or {}
            task_id = js.get("id") or js.get("task_id")
            if not task_id:
                await msg.reply_text("Sora: не вернулся task_id.")
                return

            status_url = f"{SORA_BASE_URL}/video/generations/{task_id}"
            started = time.time()

            while True:
                rs = await client.get(status_url, headers=headers)
                if rs.status_code >= 400:
                    await msg.reply_text(f"⚠️ Sora: ошибка статуса ({rs.status_code}).\n{(rs.text or '')[:1000]}")
                    return

                st_js = rs.json() or {}
                st = (st_js.get("status") or "").lower()

                if st in ("completed", "succeeded", "done"):
                    out = st_js.get("output") or st_js.get("result") or {}
                    video_url = out.get("url") or out.get("video_url")
                    if not video_url:
                        await msg.reply_text("Sora: нет ссылки на видео.")
                        return

                    vr = await client.get(video_url, timeout=180.0)
                    if vr.status_code >= 400:
                        await msg.reply_text(f"Sora: не удалось скачать видео ({vr.status_code}).")
                        return

                    bio = BytesIO(vr.content)
                    bio.name = "sora.mp4"
                    await context.bot.send_video(
                        chat_id=update.effective_chat.id,
                        video=bio,
                        supports_streaming=True,
                    )
                    await msg.reply_text(_tr(uid, "done"))
                    return

                if st in ("failed", "error", "rejected", "cancelled", "canceled"):
                    await msg.reply_text(f"❌ Sora: ошибка генерации.\n{st_js}")
                    return

                if time.time() - started > int(SORA_MAX_WAIT_S or 900):
                    await msg.reply_text("⌛ Sora: превышено время ожидания.")
                    return

                await asyncio.sleep(VIDEO_POLL_DELAY_S)

    except Exception as e:
        log.exception("Sora exception: %s", e)
        await msg.reply_text("❌ Ошибка Sora.")

async def run_sora_video(*args, **kwargs):
    log.warning("run_sora_video is deprecated, use _run_sora_video")
    return await _run_sora_video(*args, **kwargs)

async def run_runway_animate_photo(*args, **kwargs):
    log.warning("run_runway_animate_photo is deprecated, use _run_runway_animate_photo")
    return await _run_runway_animate_photo(*args, **kwargs)


# ------------------------------------------------------------
# Defensive wrappers around GPT / STT
# ------------------------------------------------------------

async def safe_gpt_chat(user_id: int, messages: list[dict], model: str = "gpt-4o-mini") -> str:
    try:
        return await _gpt_chat(user_id, messages, model=model)
    except Exception as e:
        log.exception("safe_gpt_chat failed: %s", e)
        return "⚠️ Ошибка генерации ответа. Попробуйте позже."

async def safe_transcribe(raw: bytes, filename: str = "voice.ogg") -> str:
    try:
        return await _transcribe_telegram_voice(raw, filename=filename)
    except Exception as e:
        log.exception("safe_transcribe failed: %s", e)
        return ""


# ------------------------------------------------------------
# Small helpers for prompts
# ------------------------------------------------------------

def trim_prompt(prompt: str, max_len: int = 800) -> str:
    p = (prompt or "").strip()
    if len(p) > max_len:
        return p[:max_len]
    return p

def enrich_video_prompt(prompt: str) -> str:
    """
    Лёгкое улучшение промпта без изменения смысла.
    Можно дорабатывать позже.
    """
    p = trim_prompt(prompt)
    if not p:
        return p
    return p


# ------------------------------------------------------------
# Logging helpers
# ------------------------------------------------------------

def log_user_action(user_id: int, action: str, meta: dict | None = None):
    try:
        log.info("user=%s action=%s meta=%s", user_id, action, meta or {})
    except Exception:
        pass


# ------------------------------------------------------------
# Feature flags summary (for debug)
# ------------------------------------------------------------

def feature_flags() -> dict:
    return {
        "KLING_ENABLED": KLING_ENABLED,
        "LUMA_ENABLED": LUMA_ENABLED,
        "SORA_ENABLED": SORA_ENABLED,
        "RUNWAY_ENABLED": RUNWAY_ENABLED,
    }


# ------------------------------------------------------------
# Final safety note
# ------------------------------------------------------------

log.info(
    "Feature flags loaded: %s",
    feature_flags(),
)

def main():
    if not APP_URL:
        raise RuntimeError("APP_URL is required for webhook mode (public https url of your service).")

    app = build_app()

    path = WEBHOOK_PATH if WEBHOOK_PATH.startswith("/") else f"/{WEBHOOK_PATH}"
    webhook_full = f"{APP_URL.rstrip('/')}{path}"

    log.info("Bot started in WEBHOOK mode: %s", webhook_full)

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

# === END PART 9 ===
