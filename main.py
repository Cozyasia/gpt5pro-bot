# main.py
import os
import re
import json
import logging
from typing import Optional, Tuple

import httpx
from telegram import Update, MessageEntity
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

# ====== ЛОГИ ======
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("gpt5pro-bot")

# ====== ENV ======
BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")  # опционально
ALWAYS_BROWSE = os.environ.get("ALWAYS_BROWSE", "0") == "1"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # опционально

# ====== КЛИЕНТЫ ======
HTTP_TIMEOUT = httpx.Timeout(60.0, connect=30.0)
http = httpx.AsyncClient(timeout=HTTP_TIMEOUT)

# -------- OpenAI (чтение, визион, ответы) --------
# Используем Chat Completions для универсальности
OPENAI_BASE = os.environ.get("OPENAI_BASE", "https://api.openai.com/v1")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")  # поддерживает vision

async def openai_chat(messages, temperature=0.3):
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    r = await http.post(f"{OPENAI_BASE}/chat/completions", headers=headers, json=payload)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()

async def openai_vision_describe(image_url: str, user_prompt: str = "Опиши, что на изображении. Извлеки видимый текст."):
    if not OPENAI_API_KEY:
        return "Не настроен ключ OpenAI для анализа изображений."
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": image_url}}
        ],
    }]
    payload = {"model": OPENAI_MODEL, "messages": messages, "temperature": 0.2}
    r = await http.post(f"{OPENAI_BASE}/chat/completions", headers=headers, json=payload)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()

# -------- Deepgram (ASR) --------
DEEPGRAM_API = "https://api.deepgram.com/v1/listen"
# Будем использовать prerecord URL (Deepgram сам тянет файл по URL)
async def deepgram_transcribe(file_url: str, language_hint: Optional[str] = None) -> Optional[str]:
    """
    Возвращает распознанный текст или None в случае неудачи.
    """
    if not DEEPGRAM_API_KEY:
        log.warning("DEEPGRAM_API_KEY is not set.")
        return None

    params = {
        "model": "nova-2",          # качественная универсальная модель
        "smart_format": "true",     # пунктуация/форматирование
        "punctuate": "true",
    }
    if language_hint:
        params["language"] = language_hint  # например "ru"; можно не указывать — авто

    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {"url": file_url}

    try:
        r = await http.post(DEEPGRAM_API, params=params, headers=headers, json=body)
        if r.status_code >= 400:
            log.error("Deepgram error %s: %s", r.status_code, r.text)
            return None
        data = r.json()
        # Безопасно достаем текст
        alt = (
            data.get("results", {})
                .get("channels", [{}])[0]
                .get("alternatives", [{}])[0]
        )
        transcript = alt.get("transcript", "").strip()
        return transcript or None
    except Exception as e:
        log.exception("Deepgram request failed: %s", e)
        return None

# ====== УТИЛИТЫ ======

HELLO_RE = re.compile(r"^(привет|здравствуй|hi|hello|добрый\s+(день|вечер|утро))[\s!,.]*$", re.I)
SIMPLE_THANKS = re.compile(r"(спасибо|благодарю)\b", re.I)

CAPS_RE = re.compile(
    r"(можешь|умеешь|умеет|способен|анализируешь).*(фото|изображени|картин|видео|аудио|голос|voice)",
    re.I
)

FACTY_RE = re.compile(
    r"(когда|сколько|курс|новост|что\sтакое|кто\sтакой|дата|цена|прогноз|объясни).*",
    re.I
)

def is_simple_greeting(text: str) -> bool:
    return bool(HELLO_RE.match(text.strip()))

def is_capability_question(text: str) -> bool:
    return bool(CAPS_RE.search(text))

def likely_needs_web(text: str) -> bool:
    return ALWAYS_BROWSE or bool(FACTY_RE.search(text))

def user_lang(update: Update) -> str:
    code = "ru"
    try:
        code = (update.effective_user.language_code or "ru").split("-")[0]
    except Exception:
        pass
    return code or "ru"

async def telegram_file_url(context: ContextTypes.DEFAULT_TYPE, file_id: str) -> str:
    """
    Возвращает корректный публичный URL файла Telegram:
    https://api.telegram.org/file/bot<token>/<file_path>
    """
    tg_file = await context.bot.get_file(file_id)
    # tg_file.file_path уже содержит относительный путь вида `voice/file_123.oga`
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{tg_file.file_path}"

# ====== БАЗОВЫЕ ОТВЕТЫ ======

START_TEXT = (
    "Привет! Я готов. Напиши любой вопрос.\n\n"
    "Подсказки:\n"
    "• Я ищу свежую информацию в интернете для фактов и дат, когда это нужно.\n"
    "• Примеры: «Когда выйдет GTA 6?», «Курс биткоина сейчас и прогноз», "
    "«Найди учебник алгебры 11 класс (официальные источники)», «Новости по …?»\n"
    "• Можно прислать фото — опишу и извлеку текст.\n"
    "• Можно отправить голосовое или видео — распознаю речь и отвечу по содержанию."
)

CAPABILITIES_TEXT = (
    "Да, умею:\n"
    "• Фото/картинки — опишу, извлеку текст (OCR) и уточню детали.\n"
    "• Голос/аудио — распознаю речь и отвечу по смыслу (Deepgram).\n"
    "• Видео — извлеку звуковую дорожку через Deepgram и сгенерирую ответ.\n\n"
    "Просто пришли файл (фото, голосовое, аудио или видео)."
)

# ====== ХЕНДЛЕРЫ ======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_TEXT)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    lang = user_lang(update)

    # 1) Приветствия/простое общение — без интернета
    if is_simple_greeting(text):
        await update.message.reply_text("Привет! Как я могу помочь?")
        return

    # 2) Вопрос о возможностях
    if is_capability_question(text):
        await update.message.reply_text(CAPABILITIES_TEXT)
        return

    # 3) “Спасибо”
    if SIMPLE_THANKS.search(text):
        await update.message.reply_text("Пожалуйста! 😊 Чем ещё помочь?")
        return

    # 4) Ответ: либо оффлайн, либо с походом в сеть (при необходимости)
    if likely_needs_web(text):
        # Мини-агент: спросим модель, как лучше ответить, и попросим сослаться на источники
        prompt = (
            "Пользователь спросил:\n"
            f"{text}\n\n"
            "Сначала найди свежую информацию в интернете (используй популярные и надёжные источники), "
            "затем коротко и по делу ответь по-русски и приведи 2–5 ссылок внизу."
        )
    else:
        prompt = (
            "Ответь по-русски кратко и по делу. Если вопрос фактический/новостной, "
            "сам предложи при необходимости поискать и уточнить в интернете."
            f"\n\nВопрос: {text}"
        )

    try:
        reply = await openai_chat([
            {"role": "system", "content": "Ты вежливый и полезный помощник."},
            {"role": "user", "content": prompt},
        ])
    except Exception as e:
        log.exception("OpenAI text error: %s", e)
        reply = "Извини, сейчас не получилось ответить. Попробуй ещё раз."
    await update.message.reply_text(reply, disable_web_page_preview=False)

# ----- Фото (Vision) -----
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Берём самое большое превью
        photo = update.message.photo[-1]
        url = await telegram_file_url(context, photo.file_id)
        desc = await openai_vision_describe(url)
        await update.message.reply_text(desc, disable_web_page_preview=True)
    except Exception as e:
        log.exception("Vision/photo failed: %s", e)
        await update.message.reply_text("Не удалось проанализировать изображение. Попробуй ещё раз или пришли другой файл.")

# ----- Голос (voice) / аудио (audio) / видео (video) / видео-заметка (video_note) -----

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # voice: .ogg (opus)
    voice = update.message.voice
    await transcribe_and_answer(update, context, voice.file_id, hint_lang=user_lang(update))

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    audio = update.message.audio  # mp3/m4a/wav…
    await transcribe_and_answer(update, context, audio.file_id, hint_lang=user_lang(update))

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video = update.message.video  # mp4/mov…
    await transcribe_and_answer(update, context, video.file_id, hint_lang=user_lang(update))

async def handle_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.message.video_note  # кружочек
    await transcribe_and_answer(update, context, v.file_id, hint_lang=user_lang(update))

async def transcribe_and_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str, hint_lang: str = "ru"):
    try:
        url = await telegram_file_url(context, file_id)
        log.info("Transcribing via Deepgram: %s", url)
        text = await deepgram_transcribe(url, language_hint=hint_lang)
        if not text:
            await update.message.reply_text("Не удалось распознать голос. Попробуй ещё раз.")
            return

        # Отвечаем по содержанию распознанного текста
        user_q = text.strip()
        pre = f"Распознанный текст: «{user_q}».\n\n"
        needs_web = likely_needs_web(user_q)
        if needs_web:
            prompt = (
                "Пользователь продиктовал вопрос. Найди свежие данные в интернете и "
                "ответь по-русски кратко и по делу. В конце дай 2–5 ссылок-источников.\n\n"
                f"Вопрос: {user_q}"
            )
        else:
            prompt = (
                "Ответь по-русски кратко и по делу.\n\n"
                f"Вопрос: {user_q}"
            )

        try:
            answer = await openai_chat([
                {"role": "system", "content": "Ты вежливый и полезный помощник."},
                {"role": "user", "content": prompt},
            ])
        except Exception as e:
            log.exception("OpenAI after ASR error: %s", e)
            answer = "Принял текст, но не смог сформировать ответ. Попробуй снова."

        await update.message.reply_text(pre + answer, disable_web_page_preview=False)
    except Exception as e:
        log.exception("ASR flow failed: %s", e)
        await update.message.reply_text("Не удалось распознать голос. Попробуй ещё раз.")

# ====== РЕГИСТРАЦИЯ ======

def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # Медиа
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE, handle_video_note))

    # Текст в самом конце (чтобы не перехватывал медиа)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    return app

async def on_startup(app: Application):
    if WEBHOOK_URL:
        await app.bot.set_webhook(WEBHOOK_URL)
        log.info("Webhook set to %s", WEBHOOK_URL)
    else:
        log.info("Running in long-polling mode")

def main():
    app = build_app()
    if WEBHOOK_URL:
        # Render обычно за прокси — слушаем 0.0.0.0:10000 (или как в Render)
        port = int(os.environ.get("PORT", "10000"))
        app.run_webhook(listen="0.0.0.0", port=port, webhook_url=WEBHOOK_URL, drop_pending_updates=True)
    else:
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
