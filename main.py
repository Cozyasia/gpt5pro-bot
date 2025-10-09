# -*- coding: utf-8 -*-
import os
import io
import base64
import logging
import asyncio
from typing import List, Tuple

import httpx
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)

# =============== LOGGING ===============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")

# =============== ENV ===============
BOT_TOKEN       = os.environ.get("BOT_TOKEN", "").strip()
PUBLIC_URL      = os.environ.get("PUBLIC_URL", "").strip()   # https://<subdomain>.onrender.com
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL    = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
WEBHOOK_SECRET  = os.environ.get("WEBHOOK_SECRET", "").strip()
BANNER_URL      = os.environ.get("BANNER_URL", "").strip()
PORT            = int(os.environ.get("PORT", "10000"))

# Веб-поиск (опционально)
TAVILY_API_KEY  = os.environ.get("TAVILY_API_KEY", "").strip()

# Голос/аудио/видео (Deepgram)
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")

# =============== OPENAI CLIENT (ленивая инициализация) ===============
def _openai_client():
    from openai import OpenAI
    return OpenAI(api_key=OPENAI_API_KEY)

# =============== TAVILY (опционально) ===============
def _tavily_client():
    if not TAVILY_API_KEY:
        return None
    try:
        from tavily import TavilyClient
        return TavilyClient(api_key=TAVILY_API_KEY)
    except Exception as e:
        log.warning("Tavily not available: %s", e)
        return None

# ------------- Хелперы -------------
SIMPLE_GREETINGS = {
    "привет", "привет!", "здравствуй", "здравствуйте", "ку", "салют",
    "hi", "hello", "hey", "yo", "hola"
}

def is_simple_greeting(text: str) -> bool:
    t = (text or "").strip().lower()
    # только короткие приветствия без вопросительных слов
    return (t in SIMPLE_GREETINGS) or (t.startswith("привет") and len(t) <= 12) or (t in {"/start", "/help"})

def should_browse(text: str) -> bool:
    """Грубая эвристика: ищем, если вопрос про факты/даты/новости/цены и т.п."""
    t = (text or "").lower()
    if is_simple_greeting(t):
        return False
    # ключевые “интернетные” слова
    keys = [
        "когда", "дата", "сколько", "цена", "курс", "новости", "кто такой",
        "что такое", "найди", "официальн", "источн", "релиз", "расписани",
        "выйдет", "адрес", "телефон", "ссылк", "buy", "price", "release", "news"
    ]
    if any(k in t for k in keys):
        return True
    # длинные запросы с фактологией
    return len(t) >= 80

async def tavily_search(query: str) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Возвращает (краткий ответ от Tavily, [(title, url), ...]).
    Если Tavily не настроен — вернётся ("", []).
    """
    tv = _tavily_client()
    if not tv:
        return "", []

    try:
        res = tv.search(
            query=query,
            max_results=6,
            include_answer=True,
            include_raw_content=False,
        )
        answer = (res.get("answer") or "").strip()
        sources = []
        for i in res.get("results", []):
            title = (i.get("title") or i.get("url") or "").strip()
            url = (i.get("url") or "").strip()
            if url:
                sources.append((title, url))
        return answer, sources
    except Exception as e:
        log.exception("Tavily error: %s", e)
        return "", []

def format_sources(sources: List[Tuple[str, str]]) -> str:
    if not sources:
        return ""
    lines = []
    for idx, (title, url) in enumerate(sources, 1):
        safe_title = title[:120] or url
        lines.append(f"[{idx}] {safe_title} — {url}")
    return "\n\nСсылки:\n" + "\n".join(lines)

# =============== Ответ по ТЕКСТУ ===============
async def answer_text(update: Update, text: str):
    if is_simple_greeting(text):
        msg = "Привет! Как я могу помочь?"
        await update.message.reply_text(msg)
        return

    browse = should_browse(text)
    web_answer, web_sources = ("", [])
    if browse and TAVILY_API_KEY:
        web_answer, web_sources = await asyncio.get_event_loop().run_in_executor(
            None, tavily_search, text
        )

    if not OPENAI_API_KEY:
        # если OpenAI недоступен — просто отдадим найденное
        fallback = (web_answer or "Готов помочь. Уточни, что именно найти?")
        fallback += format_sources(web_sources)
        await update.message.reply_text(fallback.strip())
        return

    try:
        client = _openai_client()

        sys_prompt = (
            "Ты дружелюбный и лаконичный ассистент. "
            "Если тебе дано резюме из поиска и ссылки — используй их, "
            "но пиши своими словами, структурировано и без воды."
        )

        user_parts = [{"type": "text", "text": text}]
        if web_answer or web_sources:
            sources_block = (web_answer or "") + format_sources(web_sources)
            if sources_block.strip():
                user_parts.append({"type": "text", "text": "\n\n---\nМатериалы из поиска:\n" + sources_block})

        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_parts},
            ],
            temperature=0.6,
        )
        answer = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("OpenAI error: %s", e)
        # фолбэк: вернём хотя бы то, что нашли
        answer = (web_answer or "Не удалось получить ответ от модели.")
        answer += format_sources(web_sources)

    await update.message.reply_text(answer)

# =============== ВИЗИОН (фото) ===============
def _guess_img_mime(path: str) -> str:
    p = (path or "").lower()
    if p.endswith(".png"): return "image/png"
    if p.endswith(".webp"): return "image/webp"
    if p.endswith(".bmp"): return "image/bmp"
    if p.endswith(".gif"): return "image/gif"
    return "image/jpeg"

async def tg_download_file_bytes(bot, file_id: str) -> Tuple[bytes, str]:
    f = await bot.get_file(file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f.file_path}"
    mime = _guess_img_mime(f.file_path)
    async with httpx.AsyncClient(timeout=90) as cli:
        r = await cli.get(url)
        r.raise_for_status()
        return r.content, mime

async def describe_image_bytes(image_bytes: bytes, mime: str, ask: str) -> str:
    """
    Отправляем изображение в OpenAI через data:URL (надёжно для приватных ссылок).
    """
    if not OPENAI_API_KEY:
        return "Визуальный анализ недоступен (нет OPENAI_API_KEY)."

    try:
        client = _openai_client()
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"

        sys_prompt = (
            "Ты видишь изображение. Кратко опиши, что на нём, и, если уместно, извлеки текст (OCR). "
            "Будь точным, не выдумывай."
        )
        user_parts = [
            {"type": "input_text", "text": ask or "Опиши изображение и извлеки текст, если он есть."},
            {"type": "input_image", "image_url": data_url},
        ]

        # Для совместимости с chat.completions используем типы 'text' и 'image_url':
        # некоторые окружения ещё не поддерживают input_* — используем классический формат.
        user_parts_compat = [
            {"type": "text", "text": ask or "Опиши изображение и извлеки текст, если он есть."},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]

        try:
            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_parts_compat},
                ],
                temperature=0.2,
            )
        except Exception:
            # на случай, если какой-то формат не поддерживается в вашей версии
            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_parts},
                ],
                temperature=0.2,
            )

        return (resp.choices[0].message.content or "").strip()

    except Exception as e:
        log.exception("Vision error: %s", e)
        return "Не удалось проанализировать изображение. Попробуй ещё раз или пришли другой файл."

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.photo:
            return
        # берём самый большой размер
        file_id = update.message.photo[-1].file_id
        img_bytes, mime = await tg_download_file_bytes(context.bot, file_id)
        ask = (update.message.caption or "").strip()
        answer = await describe_image_bytes(img_bytes, mime, ask)
        await update.message.reply_text(answer)
    except Exception as e:
        log.exception("Photo handler error: %s", e)
        await update.message.reply_text("Не удалось проанализировать изображение. Попробуй ещё раз.")

# =============== ГОЛОС/АУДИО/ВИДЕО (Deepgram) ===============
def _guess_media_mime(path: str) -> str:
    p = (path or "").lower()
    if p.endswith(".ogg") or p.endswith(".oga") or p.endswith(".opus"):
        return "audio/ogg"
    if p.endswith(".mp3"):
        return "audio/mpeg"
    if p.endswith(".wav"):
        return "audio/wav"
    if p.endswith(".m4a"):
        return "audio/mp4"
    if p.endswith(".mp4") or p.endswith(".mov"):
        return "video/mp4"
    return "application/octet-stream"

async def tg_download_media_bytes(bot, file_id: str) -> Tuple[bytes, str]:
    f = await bot.get_file(file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f.file_path}"
    mime = _guess_media_mime(f.file_path)
    async with httpx.AsyncClient(timeout=90) as cli:
        r = await cli.get(url)
        r.raise_for_status()
        return r.content, mime

async def transcribe_deepgram(audio_or_video_bytes: bytes, mime: str) -> str:
    if not DEEPGRAM_API_KEY:
        return ""
    params = {
        "model": "nova-2-general",
        "smart_format": "true",
        "punctuate": "true",
        "detect_language": "true",  # можете зафиксировать язык: "language": "ru"
    }
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": mime or "application/octet-stream",
    }
    url = "https://api.deepgram.com/v1/listen"
    try:
        async with httpx.AsyncClient(timeout=120) as cli:
            resp = await cli.post(url, params=params, headers=headers, content=audio_or_video_bytes)
            resp.raise_for_status()
            data = resp.json()
        text = (data.get("results", {})
                    .get("channels", [{}])[0]
                    .get("alternatives", [{}])[0]
                    .get("transcript", "")).strip()
        return text
    except Exception as e:
        log.exception("Deepgram error: %s", e)
        return ""

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.voice:
            return
        if not DEEPGRAM_API_KEY:
            await update.message.reply_text("Распознавание голоса временно недоступно.")
            return
        bts, mime = await tg_download_media_bytes(context.bot, update.message.voice.file_id)
        text = await transcribe_deepgram(bts, mime)
        if not text:
            await update.message.reply_text("Не удалось распознать голос. Попробуй ещё раз.")
            return
        await answer_text(update, text)
    except Exception as e:
        log.exception("Voice handler error: %s", e)
        await update.message.reply_text("Не удалось распознать голос. Попробуй ещё раз.")

async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.audio:
            return
        if not DEEPGRAM_API_KEY:
            await update.message.reply_text("Распознавание аудио временно недоступно.")
            return
        bts, mime = await tg_download_media_bytes(context.bot, update.message.audio.file_id)
        text = await transcribe_deepgram(bts, mime)
        if not text:
            await update.message.reply_text("Не удалось распознать аудио. Попробуй ещё раз.")
            return
        await answer_text(update, text)
    except Exception as e:
        log.exception("Audio handler error: %s", e)
        await update.message.reply_text("Не удалось распознать аудио. Попробуй ещё раз.")

async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        vid = update.message.video or update.message.video_note
        if not vid:
            return
        if not DEEPGRAM_API_KEY:
            await update.message.reply_text("Распознавание речи в видео временно недоступно.")
            return
        bts, mime = await tg_download_media_bytes(context.bot, vid.file_id)
        if not mime.startswith("video/"):
            mime = "video/mp4"
        text = await transcribe_deepgram(bts, mime)
        if not text:
            await update.message.reply_text("Не удалось распознать речь в видео. Попробуй ещё раз.")
            return
        await answer_text(update, text)
    except Exception as e:
        log.exception("Video handler error: %s", e)
        await update.message.reply_text("Не удалось распознать речь в видео. Попробуй ещё раз.")

# =============== ХЕНДЛЕРЫ ТЕКСТА И /start ===============
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tips = (
        "Привет! Я готов. Напиши любой вопрос.\n\n"
        "Подсказки:\n"
        "• Я ищу свежую информацию в интернете для фактов и дат, когда это нужно.\n"
        "• Примеры: «Когда выйдет GTA 6?», «Курс биткоина сейчас и прогноз», "
        "«Найди учебник алгебры 11 класс (официальные источники)», «Новости по …?»\n"
        "• Можно прислать фото — опишу и извлеку текст.\n"
        "• Можно отправить голосовое или видео — распознаю речь и отвечу по содержанию."
    )
    await update.message.reply_text(tips)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    await answer_text(update, text)

# =============== BOOTSTRAP ===============
def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    # media
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.AUDIO, on_audio))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, on_video))
    # text
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app

def run_webhook(app):
    url_path = f"webhook/{BOT_TOKEN}"
    webhook_url = f"{PUBLIC_URL.rstrip('/')}/{url_path}"

    log.info("Starting webhook on 0.0.0.0:%s  ->  %s", PORT, webhook_url)
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=url_path,
        webhook_url=webhook_url,
        secret_token=WEBHOOK_SECRET or None,   # Telegram header X-Telegram-Bot-Api-Secret-Token
        drop_pending_updates=True,
    )

def main():
    app = build_app()
    run_webhook(app)

if __name__ == "__main__":
    main()
