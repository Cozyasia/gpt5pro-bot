# -*- coding: utf-8 -*-
# ============================================================
# ONE BOT — 12 NEURAL ENGINES
# EngineHub v1 + Deepgram STT/TTS + Video adapters
# DEPLOY-READY main.py (ASCII-safe)
# Target: Render.com
# ============================================================

import os
import asyncio
import json
import time
import logging
from typing import Dict, Any, Optional

import httpx
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------------------
# LOGGING
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("enginehub-bot")

# ---------------------------
# ENV
# ---------------------------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))

# OpenRouter
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE = os.getenv("OPENROUTER_BASE", "https://openrouter.ai/api/v1")

# Comet (Gemini)
COMET_API_KEY = os.getenv("COMET_API_KEY", "").strip()
COMET_BASE = os.getenv("COMET_BASE", "https://api.comet.com/v1")

# Deepgram
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "").strip()
DEEPGRAM_BASE = "https://api.deepgram.com/v1"

# Video providers (placeholders for real keys)
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY", "").strip()
LUMA_API_KEY = os.getenv("LUMA_API_KEY", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

# ---------------------------
# GLOBAL STATE (simple, in-memory)
# ---------------------------
USER_LANG: Dict[int, str] = {}
USER_MODE: Dict[int, str] = {}
USER_ENGINE: Dict[int, str] = {}
USER_SOURCE: Dict[int, str] = {}  # channel / organic / invite

DEFAULT_LANG = "en"
DEFAULT_ENGINE = "openrouter:gpt-4o-mini"

# ---------------------------
# I18N (minimal)
# ---------------------------
I18N = {
    "en": {
        "welcome": "One bot — 12 neural engines.",
        "choose_lang": "Choose language:",
        "menu": "Main menu:",
        "study": "Study",
        "work": "Work",
        "fun": "Fun",
        "engines": "Engines",
        "balance": "Balance",
        "subscription": "Subscription",
        "free_chat": "Free Chat",
        "engine_set": "Engine set to",
        "type_query": "Type your query:",
        "demo": "Demo mode enabled.",
        "from_channel": "You came from our AI news channel. Try all engines.",
        "voice_received": "Voice received. Transcribing...",
        "video_started": "Video generation started. This may take a while.",
        "video_done": "Video job finished.",
        "send_image": "Send an image with caption 'animate' to create a video.",
    },
    "ru": {
        "welcome": "Один бот — 12 нейросетей.",
        "choose_lang": "Выберите язык:",
        "menu": "Главное меню:",
        "study": "Учёба",
        "work": "Работа",
        "fun": "Развлечения",
        "engines": "Движки",
        "balance": "Баланс",
        "subscription": "Подписка",
        "free_chat": "Свободный чат",
        "engine_set": "Движок выбран",
        "type_query": "Введите запрос:",
        "demo": "Демо-режим включен.",
        "from_channel": "Вы пришли из канала про ИИ. Попробуйте все движки.",
        "voice_received": "Голос получен. Распознаю...",
        "video_started": "Запущена генерация видео. Это займет время.",
        "video_done": "Видео готово.",
        "send_image": "Отправьте изображение с подписью 'animate' для видео.",
    },
}

def t(uid: int, key: str) -> str:
    lang = USER_LANG.get(uid, DEFAULT_LANG)
    return I18N.get(lang, I18N[DEFAULT_LANG]).get(key, key)

# ---------------------------
# KEYBOARDS
# ---------------------------
def kb_lang():
    return ReplyKeyboardMarkup(
        [["English", "Russian"]],
        resize_keyboard=True,
    )

def kb_main(uid: int):
    lang = USER_LANG.get(uid, DEFAULT_LANG)
    return ReplyKeyboardMarkup(
        [
            [I18N[lang]["study"], I18N[lang]["work"], I18N[lang]["fun"]],
            [I18N[lang]["engines"], I18N[lang]["subscription"], I18N[lang]["balance"]],
            [I18N[lang]["free_chat"]],
        ],
        resize_keyboard=True,
    )

def kb_engines():
    return ReplyKeyboardMarkup(
        [
            ["OpenRouter: GPT-4o-mini", "OpenRouter: GPT-4.1"],
            ["Gemini 1.5 Pro (Comet)"],
            ["Back"],
        ],
        resize_keyboard=True,
    )

# ---------------------------
# ENGINE HUB
# ---------------------------
class EngineResponse:
    def __init__(self, text: str):
        self.text = text

class BaseEngine:
    async def generate(self, prompt: str, uid: int, mode: str) -> EngineResponse:
        raise NotImplementedError

class OpenRouterEngine(BaseEngine):
    def __init__(self, model: str):
        self.model = model

    async def generate(self, prompt: str, uid: int, mode: str) -> EngineResponse:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": f"Answer in {USER_LANG.get(uid, DEFAULT_LANG)}."},
                {"role": "user", "content": prompt},
            ],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            return EngineResponse(text)

class GeminiCometEngine(BaseEngine):
    async def generate(self, prompt: str, uid: int, mode: str) -> EngineResponse:
        headers = {
            "Authorization": f"Bearer {COMET_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gemini-1.5-pro",
            "input": prompt,
            "lang": USER_LANG.get(uid, DEFAULT_LANG),
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{COMET_BASE}/generate", headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            return EngineResponse(data.get("output", ""))

ENGINE_REGISTRY: Dict[str, BaseEngine] = {
    "openrouter:gpt-4o-mini": OpenRouterEngine("gpt-4o-mini"),
    "openrouter:gpt-4.1": OpenRouterEngine("gpt-4.1"),
    "gemini:1.5-pro": GeminiCometEngine(),
}

# ---------------------------
# DEEPGRAM (STT / TTS)
# ---------------------------
async def deepgram_stt(audio_bytes: bytes, uid: int) -> str:
    if not DEEPGRAM_API_KEY:
        return ""
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "audio/ogg",
    }
    params = {
        "model": "nova-2",
        "language": USER_LANG.get(uid, DEFAULT_LANG),
        "punctuate": "true",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{DEEPGRAM_BASE}/listen", headers=headers, params=params, content=audio_bytes)
        r.raise_for_status()
        data = r.json()
        return data["results"]["channels"][0]["alternatives"][0]["transcript"]

async def deepgram_tts(text: str, uid: int) -> bytes:
    if not DEEPGRAM_API_KEY:
        return b""
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "voice": "aura-asteria-en",
        "model": "aura",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{DEEPGRAM_BASE}/speak", headers=headers, json=payload)
        r.raise_for_status()
        return r.content

# ---------------------------
# VIDEO (BASE ADAPTERS)
# ---------------------------
async def video_from_text(prompt: str, uid: int) -> str:
    # Placeholder: integrate Runway/Luma real endpoints here
    await asyncio.sleep(2)
    return "https://example.com/video-from-text.mp4"

async def video_from_image(image_url: str, uid: int) -> str:
    # Placeholder: integrate Runway/Luma real endpoints here
    await asyncio.sleep(2)
    return "https://example.com/video-from-image.mp4"

# ---------------------------
# GROWTH / ONBOARDING
# ---------------------------
async def onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if USER_SOURCE.get(uid) == "channel":
        await update.message.reply_text(t(uid, "from_channel"))
    await update.message.reply_text(t(uid, "demo"))

# ---------------------------
# HANDLERS
# ---------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    USER_LANG[uid] = DEFAULT_LANG
    USER_MODE[uid] = "menu"
    USER_ENGINE[uid] = DEFAULT_ENGINE
    USER_SOURCE.setdefault(uid, "organic")
    await update.message.reply_text(t(uid, "choose_lang"), reply_markup=kb_lang())

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text.lower()
    if "english" in txt:
        USER_LANG[uid] = "en"
    elif "russian" in txt:
        USER_LANG[uid] = "ru"
    await update.message.reply_text(t(uid, "welcome"), reply_markup=kb_main(uid))
    await onboarding(update, context)

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text
    lang = USER_LANG.get(uid, DEFAULT_LANG)

    if txt == I18N[lang]["study"]:
        USER_MODE[uid] = "study"
        await update.message.reply_text(t(uid, "type_query"), reply_markup=ReplyKeyboardRemove())
        return
    if txt == I18N[lang]["work"]:
        USER_MODE[uid] = "work"
        await update.message.reply_text(t(uid, "type_query"), reply_markup=ReplyKeyboardRemove())
        return
    if txt == I18N[lang]["fun"]:
        USER_MODE[uid] = "fun"
        await update.message.reply_text(t(uid, "type_query"), reply_markup=ReplyKeyboardRemove())
        return
    if txt == I18N[lang]["engines"]:
        await update.message.reply_text("Select engine:", reply_markup=kb_engines())
        return
    if txt == I18N[lang]["balance"]:
        await update.message.reply_text("Balance info.")
        return
    if txt == I18N[lang]["subscription"]:
        await update.message.reply_text("Subscription info.")
        return
    if txt == I18N[lang]["free_chat"]:
        USER_MODE[uid] = "free"
        await update.message.reply_text(t(uid, "type_query"), reply_markup=ReplyKeyboardRemove())
        return

async def handle_engines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text
    if txt.startswith("OpenRouter: GPT-4o"):
        USER_ENGINE[uid] = "openrouter:gpt-4o-mini"
        await update.message.reply_text(f"{t(uid,'engine_set')}: GPT-4o-mini", reply_markup=kb_main(uid))
    elif txt.startswith("OpenRouter: GPT-4.1"):
        USER_ENGINE[uid] = "openrouter:gpt-4.1"
        await update.message.reply_text(f"{t(uid,'engine_set')}: GPT-4.1", reply_markup=kb_main(uid))
    elif txt.startswith("Gemini"):
        USER_ENGINE[uid] = "gemini:1.5-pro"
        await update.message.reply_text(f"{t(uid,'engine_set')}: Gemini 1.5 Pro", reply_markup=kb_main(uid))
    elif txt == "Back":
        await update.message.reply_text(t(uid, "menu"), reply_markup=kb_main(uid))

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(t(uid, "voice_received"))
    file = await update.message.voice.get_file()
    audio_bytes = await file.download_as_bytearray()
    text = await deepgram_stt(bytes(audio_bytes), uid)
    if not text:
        await update.message.reply_text("STT failed.")
        return
    await free_chat_text(uid, text, update)

async def free_chat_text(uid: int, prompt: str, update: Update):
    engine_key = USER_ENGINE.get(uid, DEFAULT_ENGINE)
    engine = ENGINE_REGISTRY.get(engine_key)
    if not engine:
        await update.message.reply_text("Engine not available.")
        return
    res = await engine.generate(prompt, uid, USER_MODE.get(uid, "free"))
    await update.message.reply_text(res.text)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    caption = (update.message.caption or "").lower()
    if "animate" in caption:
        await update.message.reply_text(t(uid, "video_started"))
        photo = update.message.photo[-1]
        file = await photo.get_file()
        video_url = await video_from_image(file.file_path, uid)
        await update.message.reply_text(f"{t(uid,'video_done')}: {video_url}")
    else:
        await update.message.reply_text(t(uid, "send_image"))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    prompt = update.message.text
    await free_chat_text(uid, prompt, update)

# ---------------------------
# ROUTER
# ---------------------------
async def router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text or ""

    if txt in ("English", "Russian"):
        await set_language(update, context)
        return

    if txt in ("OpenRouter: GPT-4o-mini", "OpenRouter: GPT-4.1", "Gemini 1.5 Pro (Comet)", "Back"):
        await handle_engines(update, context)
        return

    if USER_MODE.get(uid, "menu") == "menu":
        await handle_menu(update, context)
        return

    await handle_text(update, context)

# ---------------------------
# MAIN
# ---------------------------
async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router))
    log.info("EngineHub bot starting with Deepgram and Video")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
