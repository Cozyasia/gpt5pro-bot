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

# =============================
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

# =============================
# UI dictionary (short labels for buttons/menus)
# =============================
I18N: dict[str, dict[str, str]] = {
    "ru": {
        "choose_lang": "🌍 Выберите язык",
        "lang_set": "✅ Язык установлен",
        "menu_title": "Главное меню",
        "btn_video": "🎞 Создать видео",
        "btn_photo": "🖼 Оживить фото",
        "btn_help": "❓ Помощь",
    },
    "be": {
        "choose_lang": "🌍 Абярыце мову",
        "lang_set": "✅ Мова ўсталявана",
        "menu_title": "Галоўнае меню",
        "btn_video": "🎞 Стварыць відэа",
        "btn_photo": "🖼 Ажывіць фота",
        "btn_help": "❓ Дапамога",
    },
    "uk": {
        "choose_lang": "🌍 Оберіть мову",
        "lang_set": "✅ Мову встановлено",
        "menu_title": "Головне меню",
        "btn_video": "🎞 Створити відео",
        "btn_photo": "🖼 Оживити фото",
        "btn_help": "❓ Допомога",
    },
    "de": {
        "choose_lang": "🌍 Sprache auswählen",
        "lang_set": "✅ Sprache gesetzt",
        "menu_title": "Hauptmenü",
        "btn_video": "🎞 Video erstellen",
        "btn_photo": "🖼 Foto animieren",
        "btn_help": "❓ Hilfe",
    },
    "en": {
        "choose_lang": "🌍 Choose language",
        "lang_set": "✅ Language set",
        "menu_title": "Main menu",
        "btn_video": "🎞 Create video",
        "btn_photo": "🖼 Animate photo",
        "btn_help": "❓ Help",
    },
    "fr": {
        "choose_lang": "🌍 Choisir la langue",
        "lang_set": "✅ Langue définie",
        "menu_title": "Menu principal",
        "btn_video": "🎞 Créer une vidéo",
        "btn_photo": "🖼 Animer une photo",
        "btn_help": "❓ Aide",
    },
    "th": {
        "choose_lang": "🌍 เลือกภาษา",
        "lang_set": "✅ ตั้งค่าภาษาแล้ว",
        "menu_title": "เมนูหลัก",
        "btn_video": "🎞 สร้างวิดีโอ",
        "btn_photo": "🖼 ทำให้รูปเคลื่อนไหว",
        "btn_help": "❓ ช่วยเหลือ",
    },
}

def t(user_id: int, key: str) -> str:
    """
    Short UI strings (buttons/menus).
    """
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
# Extended language pack (long UI texts / hints / messages)
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
    "help": {
        "ru": "❓ Помощь: напиши «сделай видео …» или пришли фото и нажми «Оживить фото».",
        "be": "❓ Дапамога: напішы «зрабі відэа …» або дашлі фота і націсні «Ажывіць фота».",
        "uk": "❓ Допомога: напиши «зроби відео …» або надішли фото й натисни «Оживити фото».",
        "de": "❓ Hilfe: schreibe „make video …“ oder sende ein Foto und drücke „Foto animieren“.",
        "en": "❓ Help: type “make video …” or send a photo and tap “Animate photo”.",
        "fr": "❓ Aide : écrivez « make video … » ou envoyez une photo puis « Animer une photo ».",
        "th": "❓ วิธีใช้: พิมพ์ “ทำวิดีโอ …” หรือส่งรูปแล้วกด “ทำให้รูปเคลื่อนไหว”",
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
}

# Add common/technical messages (errors/status) to long pack
I18N_PACK.update({
    "limit_exceeded": {
        "ru": "⛔ Лимит исчерпан. Обновите подписку.",
        "be": "⛔ Ліміт вычарпаны. Абнавіце падпіску.",
        "uk": "⛔ Ліміт вичерпано. Оновіть підписку.",
        "de": "⛔ Limit erreicht. Bitte Abo upgraden.",
        "en": "⛔ Limit reached. Please upgrade your plan.",
        "fr": "⛔ Limite atteinte. Veuillez améliorer votre abonnement.",
        "th": "⛔ ใช้โควตาครบแล้ว โปรดอัปเกรดแพ็กเกจ",
    },
    "err_bad_callback": {
        "ru": "⚠️ Некорректная кнопка (bad callback).",
        "be": "⚠️ Некарэктная кнопка (bad callback).",
        "uk": "⚠️ Некоректна кнопка (bad callback).",
        "de": "⚠️ Ungültiger Callback.",
        "en": "⚠️ Invalid callback.",
        "fr": "⚠️ Callback invalide.",
        "th": "⚠️ ปุ่มไม่ถูกต้อง",
    },
    "err_unknown_action": {
        "ru": "⚠️ Неизвестное действие.",
        "be": "⚠️ Невядомае дзеянне.",
        "uk": "⚠️ Невідома дія.",
        "de": "⚠️ Unbekannte Aktion.",
        "en": "⚠️ Unknown action.",
        "fr": "⚠️ Action inconnue.",
        "th": "⚠️ ไม่รู้จักคำสั่ง",
    },
    "err_unknown_engine": {
        "ru": "⚠️ Неизвестный движок.",
        "be": "⚠️ Невядомы рухавік.",
        "uk": "⚠️ Невідомий рушій.",
        "de": "⚠️ Unbekannte Engine.",
        "en": "⚠️ Unknown engine.",
        "fr": "⚠️ Moteur inconnu.",
        "th": "⚠️ ไม่รู้จักเอนจิน",
    },
    "photo_missing_retry": {
        "ru": "🖼 Фото не найдено. Пришлите фото ещё раз.",
        "be": "🖼 Фота не знойдзена. Дашліце фота яшчэ раз.",
        "uk": "🖼 Фото не знайдено. Надішліть фото ще раз.",
        "de": "🖼 Foto nicht gefunden. Bitte sende es erneut.",
        "en": "🖼 Photo not found. Please send it again.",
        "fr": "🖼 Photo introuvable. Merci de l’envoyer à nouveau.",
        "th": "🖼 ไม่พบรูป โปรดส่งใหม่อีกครั้ง",
    },
    "cancel_btn": {
        "ru": "✖️ Отмена",
        "be": "✖️ Адмена",
        "uk": "✖️ Скасувати",
        "de": "✖️ Abbrechen",
        "en": "✖️ Cancel",
        "fr": "✖️ Annuler",
        "th": "✖️ ยกเลิก",
    },
    "cancelled": {
        "ru": "✖️ Отменено.",
        "be": "✖️ Адменена.",
        "uk": "✖️ Скасовано.",
        "de": "✖️ Abgebrochen.",
        "en": "✖️ Cancelled.",
        "fr": "✖️ Annulé.",
        "th": "✖️ ยกเลิกแล้ว",
    },
    "err_button_failed": {
        "ru": "❌ Ошибка обработки кнопки.",
        "be": "❌ Памылка апрацоўкі кнопкі.",
        "uk": "❌ Помилка обробки кнопки.",
        "de": "❌ Fehler bei der Button-Verarbeitung.",
        "en": "❌ Button processing error.",
        "fr": "❌ Erreur de traitement du bouton.",
        "th": "❌ เกิดข้อผิดพลาดในการประมวลผลปุ่ม",
    },
    "voice_not_found": {
        "ru": "Не найдено голосовое сообщение.",
        "be": "Галасавое паведамленне не знойдзена.",
        "uk": "Голосове повідомлення не знайдено.",
        "de": "Keine Sprachnachricht gefunden.",
        "en": "No voice message found.",
        "fr": "Message vocal introuvable.",
        "th": "ไม่พบข้อความเสียง",
    },
    "voice_download_failed": {
        "ru": "Не удалось скачать голосовое сообщение.",
        "be": "Не ўдалося спампаваць галасавое паведамленне.",
        "uk": "Не вдалося завантажити голосове повідомлення.",
        "de": "Sprachnachricht konnte nicht geladen werden.",
        "en": "Failed to download the voice message.",
        "fr": "Impossible de télécharger le message vocal.",
        "th": "ดาวน์โหลดข้อความเสียงไม่สำเร็จ",
    },
    "voice_stt_failed": {
        "ru": "Не удалось распознать речь.",
        "be": "Не атрымалася распазнаць маўленне.",
        "uk": "Не вдалося розпізнати мовлення.",
        "de": "Spracherkennung fehlgeschlagen.",
        "en": "Speech recognition failed.",
        "fr": "Échec de la reconnaissance vocale.",
        "th": "รู้จำเสียงไม่สำเร็จ",
    },
    "photo_download_failed": {
        "ru": "Не удалось скачать фото.",
        "be": "Не ўдалося спампаваць фота.",
        "uk": "Не вдалося завантажити фото.",
        "de": "Foto konnte nicht geladen werden.",
        "en": "Failed to download the photo.",
        "fr": "Impossible de télécharger la photo.",
        "th": "ดาวน์โหลดรูปไม่สำเร็จ",
    },
    "gpt_failed": {
        "ru": "Ошибка генерации ответа.",
        "be": "Памылка генерацыі адказу.",
        "uk": "Помилка генерації відповіді.",
        "de": "Fehler bei der Antwortgenerierung.",
        "en": "Failed to generate a reply.",
        "fr": "Échec de génération de la réponse.",
        "th": "สร้างคำตอบไม่สำเร็จ",
    },
})

# =============================
# Engine messages (status/errors)
# =============================
I18N_PACK.update({
    "engine_disabled": {
        "ru": "{name} отключён.",
        "be": "{name} адключаны.",
        "uk": "{name} вимкнено.",
        "de": "{name} ist deaktiviert.",
        "en": "{name} is disabled.",
        "fr": "{name} est désactivé.",
        "th": "ปิดใช้งาน {name}",
    },
    "engine_no_key": {
        "ru": "{name}: нет ключа/токена API.",
        "be": "{name}: няма ключа/токена API.",
        "uk": "{name}: немає ключа/токена API.",
        "de": "{name}: API-Key/Token fehlt.",
        "en": "{name}: missing API key/token.",
        "fr": "{name} : clé/token API manquant.",
        "th": "{name}: ไม่มีคีย์/โทเคน API",
    },
    "engine_rendering": {
        "ru": "⏳ {name}: рендерю…",
        "be": "⏳ {name}: рэндэр…",
        "uk": "⏳ {name}: рендерю…",
        "de": "⏳ {name}: rendere…",
        "en": "⏳ {name}: rendering…",
        "fr": "⏳ {name} : rendu…",
        "th": "⏳ {name}: กำลังสร้าง…",
    },
    "engine_rejected": {
        "ru": "⚠️ {name} отклонил задачу ({code}).\n{txt}",
        "be": "⚠️ {name} адхіліў задачу ({code}).\n{txt}",
        "uk": "⚠️ {name} відхилив задачу ({code}).\n{txt}",
        "de": "⚠️ {name} hat die Aufgabe abgelehnt ({code}).\n{txt}",
        "en": "⚠️ {name} rejected the request ({code}).\n{txt}",
        "fr": "⚠️ {name} a rejeté la requête ({code}).\n{txt}",
        "th": "⚠️ {name} ปฏิเสธงาน ({code}).\n{txt}",
    },
    "engine_status_error": {
        "ru": "⚠️ {name}: ошибка статуса ({code}).\n{txt}",
        "be": "⚠️ {name}: памылка статусу ({code}).\n{txt}",
        "uk": "⚠️ {name}: помилка статусу ({code}).\n{txt}",
        "de": "⚠️ {name}: Statusfehler ({code}).\n{txt}",
        "en": "⚠️ {name}: status error ({code}).\n{txt}",
        "fr": "⚠️ {name} : erreur de statut ({code}).\n{txt}",
        "th": "⚠️ {name}: สถานะผิดพลาด ({code}).\n{txt}",
    },
    "engine_no_task": {
        "ru": "{name}: не вернулся task_id.\n{txt}",
        "be": "{name}: не вярнуўся task_id.\n{txt}",
        "uk": "{name}: не повернувся task_id.\n{txt}",
        "de": "{name}: task_id fehlt.\n{txt}",
        "en": "{name}: task_id missing.\n{txt}",
        "fr": "{name} : task_id manquant.\n{txt}",
        "th": "{name}: ไม่มี task_id\n{txt}",
    },
    "engine_no_url": {
        "ru": "{name}: нет ссылки на видео.\n{txt}",
        "be": "{name}: няма спасылкі на відэа.\n{txt}",
        "uk": "{name}: немає посилання на відео.\n{txt}",
        "de": "{name}: keine Video-URL.\n{txt}",
        "en": "{name}: no video URL.\n{txt}",
        "fr": "{name} : pas d’URL vidéo.\n{txt}",
        "th": "{name}: ไม่มีลิงก์วิดีโอ\n{txt}",
    },
    "engine_failed": {
        "ru": "❌ {name}: ошибка генерации.\n{txt}",
        "be": "❌ {name}: памылка генерацыі.\n{txt}",
        "uk": "❌ {name}: помилка генерації.\n{txt}",
        "de": "❌ {name}: Generierungsfehler.\n{txt}",
        "en": "❌ {name}: generation failed.\n{txt}",
        "fr": "❌ {name} : échec de génération.\n{txt}",
        "th": "❌ {name}: สร้างไม่สำเร็จ\n{txt}",
    },
    "engine_timeout": {
        "ru": "⌛ {name}: превышено время ожидания.",
        "be": "⌛ {name}: перавышаны час чакання.",
        "uk": "⌛ {name}: перевищено час очікування.",
        "de": "⌛ {name}: Zeitüberschreitung.",
        "en": "⌛ {name}: timed out.",
        "fr": "⌛ {name} : délai dépassé.",
        "th": "⌛ {name}: หมดเวลา",
    },
    "engine_download_err": {
        "ru": "{name}: не удалось скачать видео (redirect/download error).",
        "be": "{name}: не ўдалося спампаваць відэа (redirect/download error).",
        "uk": "{name}: не вдалося завантажити відео (redirect/download error).",
        "de": "{name}: Download fehlgeschlagen (redirect/download error).",
        "en": "{name}: failed to download video (redirect/download error).",
        "fr": "{name} : échec du téléchargement (redirect/download error).",
        "th": "{name}: ดาวน์โหลดวิดีโอไม่สำเร็จ (redirect/download error)",
    },
    "engine_send_err": {
        "ru": "❌ {name}: не удалось отправить файл в Telegram.",
        "be": "❌ {name}: не ўдалося адправіць файл у Telegram.",
        "uk": "❌ {name}: не вдалося надіслати файл у Telegram.",
        "de": "❌ {name}: Senden an Telegram fehlgeschlagen.",
        "en": "❌ {name}: failed to send the file to Telegram.",
        "fr": "❌ {name} : envoi vers Telegram échoué.",
        "th": "❌ {name}: ส่งไฟล์ไป Telegram ไม่สำเร็จ",
    },
})

def _tr(user_id: int, key: str, **kwargs) -> str:
    """
    Long UI strings / messages (I18N_PACK).
    Safe fallback: returns RU if present, else returns key.
    """
    lang = get_lang(user_id)
    pack = I18N_PACK.get(key) or {}
    text = pack.get(lang) or pack.get("ru") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text

# =============================
# Pending actions
# =============================
_pending_actions: dict[str, dict] = {}

def _new_aid() -> str:
    return uuid.uuid4().hex

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
    return True

async def _try_pay_then_do(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int,
                          engine: str, est_usd: float, coro):
    if not _can_spend(user_id, engine, est_usd):
        await update.effective_message.reply_text(_tr(user_id, "limit_exceeded"))
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

async def cmd_start_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
        text=_tr(user_id, "welcome"),
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
            duration = int(m.group(1))
        except Exception:
            duration = 5

    tl = (text or "").lower()
    if "9:16" in text or "вертик" in tl:
        aspect = "9:16"
    elif "1:1" in text:
        aspect = "1:1"
    else:
        aspect = "16:9"

    return normalize_seconds(duration), normalize_aspect(aspect)

def _aspect_to_size(aspect: str) -> str:
    if aspect == "9:16":
        return "720x1280"
    if aspect == "1:1":
        return "1024x1024"
    return "1280x720"

# =============================
# MERGED keys into I18N_PACK (no redefinition)
# =============================
I18N_PACK.update({
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
})

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
    await update.effective_message.reply_text(
        _tr(uid, "help"),
        reply_markup=_mk_menu_kb(uid),
    )

def _video_engine_kb(aid: str, user_id: int) -> InlineKeyboardMarkup:
    tier = get_subscription_tier(user_id)
    rows: list[list[InlineKeyboardButton]] = []

    if KLING_ENABLED:
        rows.append([
            InlineKeyboardButton(
                f"📼 Kling (~${KLING_UNIT_COST_USD:.2f})",
                callback_data=f"choose:kling:{aid}",
            )
        ])
    if LUMA_ENABLED:
        rows.append([
            InlineKeyboardButton(
                f"🎞 Luma (~${LUMA_UNIT_COST_USD:.2f})",
                callback_data=f"choose:luma:{aid}",
            )
        ])

    if SORA_ENABLED:
        if tier in ("pro", "ultimate"):
            rows.append([InlineKeyboardButton("✨ Sora 2 Pro", callback_data=f"choose:sora:{aid}")])
        else:
            rows.append([InlineKeyboardButton("✨ Sora 2", callback_data=f"choose:sora:{aid}")])

    rows.append([InlineKeyboardButton(_tr(user_id, "cancel_btn"), callback_data=f"cancel:{aid}")])

    return InlineKeyboardMarkup(rows)

async def _ask_video_engine(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str):
    uid = update.effective_user.id
    dur, asp = _parse_video_opts(prompt)

    dur = normalize_seconds(dur)
    asp = normalize_aspect(asp)

    aid = _new_aid()
    _pending_actions[aid] = {
        "prompt": prompt,
        "duration": dur,
        "aspect": asp,
    }

    await update.effective_message.reply_text(
        _tr(uid, "video_opts", dur=dur, asp=asp, prompt=prompt),
        reply_markup=_video_engine_kb(aid, uid),
    )

# =============================
# OpenAI / GPT client placeholders
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

    data = {"model": WHISPER_MODEL}
    files = {"file": (filename, file_bytes, "audio/ogg")}

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
        await msg.reply_text(_tr(uid, "voice_not_found"))
        return

    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        tg_file = await context.bot.get_file(media.file_id)
        raw = await tg_file.download_as_bytearray()
    except Exception as e:
        log.exception("Voice download error: %s", e)
        await msg.reply_text(_tr(uid, "voice_download_failed"))
        return

    text = await _transcribe_telegram_voice(bytes(raw))
    if not text:
        await msg.reply_text(_tr(uid, "voice_stt_failed"))
        return

    await msg.reply_text(f"🗣 {text}")

    if _detect_video_intent(text):
        await _ask_video_engine(update, context, text)
        return

    try:
        ans = await _gpt_chat(uid, [{"role": "user", "content": text}])
        await msg.reply_text(ans)
    except Exception as e:
        log.exception("GPT error: %s", e)
        await msg.reply_text(_tr(uid, "gpt_failed"))

# ============================================================
# TEXT HANDLER
# ============================================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = update.effective_user.id
    text = (msg.text or "").strip()
    if not text:
        return

    if text == t(uid, "btn_help"):
        await cmd_help(update, context)
        return

    if text == t(uid, "btn_video"):
        tip = _tr(uid, "ask_video_prompt")
        if tip == "ask_video_prompt" or not tip.strip():
            tip = (
                "🎞 Напиши запрос для видео, например:\n"
                "«Сделай видео: закат над морем, 7 сек, 16:9»"
            )
        await msg.reply_text(tip, reply_markup=_main_menu_keyboard(uid))
        return

    if text == t(uid, "btn_photo"):
        tip = _tr(uid, "ask_send_photo")
        if tip == "ask_send_photo" or not tip.strip():
            tip = "🖼 Пришли фото, затем выбери «Оживить фото»."
        await msg.reply_text(tip, reply_markup=_main_menu_keyboard(uid))
        return

    if _detect_video_intent(text):
        await _ask_video_engine(update, context, text)
        return

    try:
        ans = await _gpt_chat(uid, [{"role": "user", "content": text}])
        await msg.reply_text(ans)
    except Exception as e:
        log.exception("GPT error: %s", e)
        await msg.reply_text(_tr(uid, "gpt_failed"))

# ============================================================
# KLING — TEXT / VOICE -> VIDEO
# ============================================================
async def _run_kling_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    seconds: int,
    aspect: str,
) -> bool:
    msg = update.effective_message
    uid = update.effective_user.id

    if not KLING_ENABLED:
        await msg.reply_text(_tr(uid, "engine_disabled", name="Kling"))
        return False
    if not COMET_API_KEY:
        await msg.reply_text(_tr(uid, "engine_no_key", name="Kling"))
        return False

    seconds = normalize_seconds(seconds)
    aspect = normalize_aspect(aspect)

    await msg.reply_text(_tr(uid, "engine_rendering", name="Kling"))

    payload = {
        "prompt": (prompt or "").strip(),
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
                txt = (r.text or "")[:1200]
                await msg.reply_text(_tr(uid, "engine_rejected", name="Kling", code=r.status_code, txt=txt))
                return False

            try:
                js = r.json() or {}
            except Exception:
                txt = (r.text or "")[:1200]
                await msg.reply_text(f"Kling: неожиданный ответ (не JSON).\n{txt}")
                return False

            task_id = (
                js.get("task_id")
                or js.get("taskId")
                or js.get("id")
                or (js.get("data") or {}).get("task_id")
                or (js.get("data") or {}).get("id")
            )
            if not task_id:
                await msg.reply_text(_tr(uid, "engine_no_task", name="Kling", txt=str(js)[:1200]))
                return False

            status_url = f"{COMET_BASE_URL}/kling/v1/tasks/{task_id}"

            ok, st_js = await poll_task_until_done(
                client,
                status_url=status_url,
                headers=headers,
                engine_name="Kling",
                msg=msg,
                uid=uid,
                timeout_s=900,
            )
            if not ok:
                return False

            video_url = extract_video_url(st_js)
            if not video_url:
                await msg.reply_text(_tr(uid, "engine_no_url", name="Kling", txt=str(st_js)[:1000]))
                return False

            try:
                data = await download_bytes_redirect_safe(client, video_url, timeout_s=180.0)
            except Exception as e:
                log.exception("Kling download failed: %s", e)
                await msg.reply_text(_tr(uid, "engine_download_err", name="Kling"))
                return False

            bio = BytesIO(data)
            bio.name = "kling.mp4"
            bio.seek(0)

            ok_send = await safe_send_video(context, update.effective_chat.id, bio)
            if not ok_send:
                await msg.reply_text(_tr(uid, "engine_send_err", name="Kling"))
                return False

            await msg.reply_text(_tr(uid, "done"))
            return True

    except Exception as e:
        log.exception("Kling exception: %s", e)
        await msg.reply_text(_tr(uid, "engine_failed", name="Kling", txt=str(e)))
        return False

# ============================================================
# LUMA — TEXT / VOICE -> VIDEO
# ============================================================
async def _run_luma_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    seconds: int,
    aspect: str,
) -> bool:
    msg = update.effective_message
    uid = update.effective_user.id

    if not LUMA_ENABLED:
        await msg.reply_text(_tr(uid, "engine_disabled", name="Luma"))
        return False
    if not COMET_API_KEY:
        await msg.reply_text(_tr(uid, "engine_no_key", name="Luma"))
        return False

    seconds = normalize_seconds(seconds)
    aspect = normalize_aspect(aspect)

    await msg.reply_text(_tr(uid, "engine_rendering", name="Luma"))

    payload = {
        "prompt": (prompt or "").strip(),
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
                txt = (r.text or "")[:1200]
                await msg.reply_text(_tr(uid, "engine_rejected", name="Luma", code=r.status_code, txt=txt))
                return False

            try:
                js = r.json() or {}
            except Exception:
                txt = (r.text or "")[:1200]
                await msg.reply_text(f"Luma: неожиданный ответ (не JSON).\n{txt}")
                return False

            task_id = (
                js.get("task_id")
                or js.get("taskId")
                or js.get("id")
                or (js.get("data") or {}).get("task_id")
                or (js.get("data") or {}).get("id")
            )
            if not task_id:
                await msg.reply_text(_tr(uid, "engine_no_task", name="Luma", txt=str(js)[:1200]))
                return False

            status_url = f"{COMET_BASE_URL}/luma/v1/tasks/{task_id}"

            ok, st_js = await poll_task_until_done(
                client,
                status_url=status_url,
                headers=headers,
                engine_name="Luma",
                msg=msg,
                uid=uid,
                timeout_s=900,
            )
            if not ok:
                return False

            video_url = extract_video_url(st_js)
            if not video_url:
                await msg.reply_text(_tr(uid, "engine_no_url", name="Luma", txt=str(st_js)[:1000]))
                return False

            try:
                data = await download_bytes_redirect_safe(client, video_url, timeout_s=180.0)
            except Exception as e:
                log.exception("Luma download failed: %s", e)
                await msg.reply_text(_tr(uid, "engine_download_err", name="Luma"))
                return False

            bio = BytesIO(data)
            bio.name = "luma.mp4"
            bio.seek(0)

            ok_send = await safe_send_video(context, update.effective_chat.id, bio)
            if not ok_send:
                await msg.reply_text(_tr(uid, "engine_send_err", name="Luma"))
                return False

            await msg.reply_text(_tr(uid, "done"))
            return True

    except Exception as e:
        log.exception("Luma exception: %s", e)
        await msg.reply_text(_tr(uid, "engine_failed", name="Luma", txt=str(e)))
        return False

# ──────────────────────────────────────────────────────────────────────────────
# CryptoBot (оплата)
# ──────────────────────────────────────────────────────────────────────────────
CRYPTOBOT_TOKEN = (_env("CRYPTOBOT_TOKEN") or "").strip()
CRYPTOBOT_BASE = (_env("CRYPTOBOT_BASE") or "https://pay.crypt.bot").rstrip("/")
CRYPTOBOT_API = (_env("CRYPTOBOT_API") or f"{CRYPTOBOT_BASE}/api").rstrip("/")

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
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(p["title"], callback_data=f"plan:{k}")]
        for k, p in PLANS.items()
    ])
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
# /start override: show language picker first
# ──────────────────────────────────────────────────────────────────────────────

# FIX: cmd_start must exist before referencing it
cmd_start = cmd_start_impl
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

# ============================================================
# PHOTO HANDLER
# ============================================================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = update.effective_user.id

    if not msg.photo:
        return

    photo = msg.photo[-1]

    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        tg_file = await context.bot.get_file(photo.file_id)
        raw = await tg_file.download_as_bytearray()
    except Exception as e:
        log.exception("Photo download error: %s", e)
        await msg.reply_text(_tr(uid, "photo_download_failed"))
        return

    aid = _new_aid()
    _pending_actions[aid] = {"photo_bytes": bytes(raw)}

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(_tr(uid, "animate_btn"), callback_data=f"animate_photo:{aid}")]
    ])
    await msg.reply_text(_tr(uid, "photo_received"), reply_markup=kb)

# ============================================================
# RUNWAY — IMAGE -> VIDEO (ТОЛЬКО ЗДЕСЬ)
# ============================================================
async def _run_runway_animate_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    photo_bytes: bytes,
    seconds: int = 5,
    aspect: str = "16:9",
) -> bool:
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

    seconds = normalize_seconds(seconds)
    aspect = normalize_aspect(aspect)

    await msg.reply_text(_tr(uid, "engine_rendering", name="Runway"))

    try:
        img_b64 = base64.b64encode(photo_bytes).decode("ascii")
        image_data_url = f"data:image/jpeg;base64,{img_b64}"
    except Exception:
        await msg.reply_text("Runway: не удалось подготовить изображение.")
        return False

    payload = {
        "model": RUNWAY_MODEL,
        "promptImage": image_data_url,
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
                f"{COMET_BASE_URL}/runwayml/v1/image_to_video",
                headers=headers,
                json=payload,
            )

            if r.status_code >= 400:
                txt = (r.text or "")[:1200]
                await msg.reply_text(_tr(uid, "engine_rejected", name="Runway", code=r.status_code, txt=txt))
                return False

            try:
                js = r.json() or {}
            except Exception:
                txt = (r.text or "")[:1200]
                await msg.reply_text(f"Runway: неожиданный ответ (не JSON).\n{txt}")
                return False

            task_id = (
                js.get("task_id")
                or js.get("taskId")
                or js.get("id")
                or (js.get("data") or {}).get("task_id")
                or (js.get("data") or {}).get("id")
            )
            if not task_id:
                await msg.reply_text(_tr(uid, "engine_no_task", name="Runway", txt=str(js)[:1200]))
                return False

            status_url = f"{COMET_BASE_URL}/runwayml/v1/tasks/{task_id}"

            ok, st_js = await poll_task_until_done(
                client,
                status_url=status_url,
                headers=headers,
                engine_name="Runway",
                msg=msg,
                uid=uid,
                timeout_s=900,
            )
            if not ok:
                return False

            video_url = extract_video_url(st_js)
            if not video_url:
                await msg.reply_text(_tr(uid, "engine_no_url", name="Runway", txt=str(st_js)[:1000]))
                return False

            try:
                data = await download_bytes_redirect_safe(client, video_url, timeout_s=180.0)
            except Exception as e:
                log.exception("Runway download failed: %s", e)
                await msg.reply_text(_tr(uid, "engine_download_err", name="Runway"))
                return False

            bio = BytesIO(data)
            bio.name = "runway.mp4"
            bio.seek(0)

            ok_send = await safe_send_video(context, update.effective_chat.id, bio)
            if not ok_send:
                await msg.reply_text(_tr(uid, "engine_send_err", name="Runway"))
                return False

            await msg.reply_text(_tr(uid, "done"))
            return True

    except Exception as e:
        log.exception("Runway exception: %s", e)
        await msg.reply_text(_tr(uid, "engine_failed", name="Runway", txt=str(e)))
        return False

# ============================================================
# CALLBACK ROUTER — SINGLE (lang + plans + animate_photo + engines)
# ============================================================
async def on_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return

    uid = update.effective_user.id
    data = (q.data or "").strip()
    if not data:
        await q.answer()
        return

    try:
        # lang:<code>
        if data.startswith("lang:"):
            await on_lang_callback(update, context)
            return

        # plan:<key>
        if data.startswith("plan:"):
            parts = data.split(":", 1)
            if len(parts) != 2:
                await q.answer()
                await q.message.reply_text(_tr(uid, "err_bad_callback"))
                return
            _, plan_key = parts
            await on_plan_callback(update, context, plan_key)
            return

        # plans:back
        if data == "plans:back":
            await q.answer()
            await cmd_plans(update, context)
            return

        # paid:<plan_key>
        if data.startswith("paid:"):
            parts = data.split(":", 1)
            if len(parts) != 2:
                await q.answer()
                await q.message.reply_text(_tr(uid, "err_bad_callback"))
                return
            _, plan_key = parts
            await q.answer()
            await on_paid_callback(update, context, plan_key)
            return

        # animate_photo:<aid>
        if data.startswith("animate_photo:"):
            parts = data.split(":")
            if len(parts) != 2:
                await q.answer()
                await q.message.reply_text(_tr(uid, "err_bad_callback"))
                return
            _, aid = parts

            act = _pending_actions.get(aid) or {}
            photo_bytes = act.get("photo_bytes")
            if not photo_bytes:
                await q.answer()
                await q.message.reply_text(_tr(uid, "photo_missing_retry"))
                return

            seconds = normalize_seconds(int(act.get("duration") or 5))
            aspect = normalize_aspect(str(act.get("aspect") or "16:9"))

            async def _do():
                try:
                    ok = await _run_runway_animate_photo(update, context, photo_bytes, seconds=seconds, aspect=aspect)
                    return ok
                finally:
                    _pending_actions.pop(aid, None)

            await q.answer()
            await _do()
            return

# cancel:<aid>
        if data.startswith("cancel:"):
            parts = data.split(":")
            if len(parts) != 2:
                await q.answer()
                await q.message.reply_text(_tr(uid, "err_bad_callback"))
                return
            _, aid = parts
            _pending_actions.pop(aid, None)
            await q.answer()
            await q.message.reply_text(_tr(uid, "cancelled"), reply_markup=_main_menu_keyboard(uid))
            return

        # choose:<engine>:<aid>
        if data.startswith("choose:"):
            parts = data.split(":")
            if len(parts) != 3:
                await q.answer()
                await q.message.reply_text(_tr(uid, "err_bad_callback"))
                return
            _, engine, aid = parts

            act = _pending_actions.get(aid) or {}
            prompt = (act.get("prompt") or "").strip()
            duration = normalize_seconds(int(act.get("duration") or 5))
            aspect = normalize_aspect(str(act.get("aspect") or "16:9"))

            # Runway для text/voice→video отключён
            if engine == "runway":
                await q.answer()
                await q.message.reply_text(_tr(uid, "runway_disabled_textvideo"))
                return

            if engine == "kling":
                est = float(KLING_UNIT_COST_USD or 0.40) * duration

                async def _do():
                    try:
                        ok = await _run_kling_video(update, context, prompt, duration, aspect)
                        if ok:
                            _register_engine_spend(uid, "kling", est)
                        return ok
                    finally:
                        _pending_actions.pop(aid, None)

                await q.answer()
                await _try_pay_then_do(update, context, uid, "kling", est, _do)
                return

            if engine == "luma":
                est = float(LUMA_UNIT_COST_USD or 0.40) * duration

                async def _do():
                    try:
                        ok = await _run_luma_video(update, context, prompt, duration, aspect)
                        if ok:
                            _register_engine_spend(uid, "luma", est)
                        return ok
                    finally:
                        _pending_actions.pop(aid, None)

                await q.answer()
                await _try_pay_then_do(update, context, uid, "luma", est, _do)
                return

            if engine == "sora":
                est = _sora_est_cost_usd(uid, duration)

                async def _do():
                    try:
                        ok = await _run_sora_video(update, context, prompt, duration, aspect)
                        if ok:
                            _register_engine_spend(uid, "sora", est)
                        return ok
                    finally:
                        _pending_actions.pop(aid, None)

                await q.answer()
                await _try_pay_then_do(update, context, uid, "sora", est, _do)
                return

            await q.answer()
            await q.message.reply_text(_tr(uid, "err_unknown_engine"))
            return

        await q.answer()
        await q.message.reply_text(_tr(uid, "err_unknown_action"))
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
        return

# ============================================================
# REGISTER ALL HANDLERS
# ============================================================
def register_all_handlers(app: Application):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("status", cmd_status))

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
    return app

# ============================================================
# UTILITIES / FALLBACKS / COMPATIBILITY
# ============================================================
async def safe_send_video(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    bio: BytesIO,
    caption: str | None = None,
) -> bool:
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
            cur = httpx.URL(cur).join(loc)
            continue

        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Download failed status={resp.status_code} body={(resp.text or '')[:400]}",
                request=req,
                response=resp,
            )

        data = resp.content or b""
        if not data:
            raise RuntimeError("Empty response body while downloading video")
        return data

    raise RuntimeError(f"Too many redirects while downloading: {url}")


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
) -> tuple[bool, dict]:
    """Poll provider task status until completion/failure/timeout."""
    started = time.time()

    while True:
        rs = await client.get(status_url, headers=headers)
        if rs.status_code >= 400:
            txt = (rs.text or "")[:1000]
            await msg.reply_text(_tr(uid, "engine_status_error", name=engine_name, code=rs.status_code, txt=txt))
            return False, {}

        try:
            st_js = rs.json() or {}
        except Exception:
            txt = (rs.text or "")[:1000]
            await msg.reply_text(_tr(uid, "engine_status_error", name=engine_name, code=rs.status_code, txt=txt))
            return False, {}

        st = (st_js.get("status") or "").lower()

        if st in ("completed", "succeeded", "done"):
            return True, st_js

        if st in ("failed", "error", "rejected", "cancelled", "canceled"):
            await msg.reply_text(_tr(uid, "engine_failed", name=engine_name, txt=str(st_js)[:1200]))
            return False, st_js

        if time.time() - started > float(timeout_s):
            await msg.reply_text(_tr(uid, "engine_timeout", name=engine_name))
            return False, st_js

        await asyncio.sleep(poll_delay_s)


def extract_video_url(status_json: dict) -> str | None:
    """Extract a video URL from different response shapes."""
    out = status_json.get("output")

    if isinstance(out, dict):
        return (
            out.get("url")
            or out.get("video_url")
            or out.get("videoUrl")
            or (out.get("data") or {}).get("url")
            or (out.get("data") or {}).get("video_url")
        )

    if isinstance(out, str) and out.startswith("http"):
        return out

    if isinstance(out, list) and out:
        first = out[0]
        if isinstance(first, str) and first.startswith("http"):
            return first
        if isinstance(first, dict):
            return first.get("url") or first.get("video_url")

    return None

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

# ============================================================
# SORA — TEXT / VOICE -> VIDEO (через Comet)
# ============================================================
async def _run_sora_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prompt: str,
    seconds: int,
    aspect: str,
) -> bool:
    msg = update.effective_message
    uid = update.effective_user.id

    if not SORA_ENABLED:
        await msg.reply_text(_tr(uid, "engine_disabled", name="Sora"))
        return False
    if not COMET_API_KEY:
        await msg.reply_text(_tr(uid, "engine_no_key", name="Sora"))
        return False

    seconds = normalize_seconds(seconds)
    aspect = normalize_aspect(aspect)

    await msg.reply_text(_tr(uid, "engine_rendering", name="Sora"))

    tier = get_subscription_tier(uid)
    sora_model = _pick_sora_model(uid)

    payload = {
        "model": sora_model,
        "prompt": (prompt or "").strip(),
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
                f"{COMET_BASE_URL}/sora/v1/text_to_video",
                headers=headers,
                json=payload,
            )

            if r.status_code >= 400:
                txt = (r.text or "")[:1200]
                await msg.reply_text(_tr(uid, "engine_rejected", name="Sora", code=r.status_code, txt=txt))
                return False

            try:
                js = r.json() or {}
            except Exception:
                txt = (r.text or "")[:1200]
                await msg.reply_text(f"Sora: неожиданный ответ (не JSON).\n{txt}")
                return False

            task_id = (
                js.get("task_id")
                or js.get("taskId")
                or js.get("id")
                or (js.get("data") or {}).get("task_id")
                or (js.get("data") or {}).get("id")
            )
            if not task_id:
                await msg.reply_text(_tr(uid, "engine_no_task", name="Sora", txt=str(js)[:1200]))
                return False

            status_url = f"{COMET_BASE_URL}/sora/v1/tasks/{task_id}"

            ok, st_js = await poll_task_until_done(
                client,
                status_url=status_url,
                headers=headers,
                engine_name="Sora",
                msg=msg,
                uid=uid,
                timeout_s=900,
            )
            if not ok:
                return False

            video_url = extract_video_url(st_js)
            if not video_url:
                await msg.reply_text(_tr(uid, "engine_no_url", name="Sora", txt=str(st_js)[:1000]))
                return False

            try:
                data = await download_bytes_redirect_safe(client, video_url, timeout_s=180.0)
            except Exception as e:
                log.exception("Sora download failed: %s", e)
                await msg.reply_text(_tr(uid, "engine_download_err", name="Sora"))
                return False

            bio = BytesIO(data)
            bio.name = "sora.mp4"
            bio.seek(0)

            ok_send = await safe_send_video(context, update.effective_chat.id, bio)
            if not ok_send:
                await msg.reply_text(_tr(uid, "engine_send_err", name="Sora"))
                return False

            await msg.reply_text(_tr(uid, "done"))
            return True

    except Exception as e:
        log.exception("Sora exception: %s", e)
        await msg.reply_text(_tr(uid, "engine_failed", name="Sora", txt=str(e)))
        return False

log.info(
    "Feature flags loaded: %s",
    {
        "KLING_ENABLED": KLING_ENABLED,
        "LUMA_ENABLED": LUMA_ENABLED,
        "SORA_ENABLED": SORA_ENABLED,
        "RUNWAY_ENABLED": RUNWAY_ENABLED,
    },
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
