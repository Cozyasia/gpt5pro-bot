# -*- coding: utf-8 -*-
import os
import io
import base64
import json
import logging
from typing import Optional, Tuple, List

import httpx
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)

# -------------------- LOGGING --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")

# -------------------- ENV --------------------
BOT_TOKEN       = os.environ.get("BOT_TOKEN", "").strip()
PUBLIC_URL      = os.environ.get("PUBLIC_URL", "").strip()
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL    = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
WEBHOOK_SECRET  = os.environ.get("WEBHOOK_SECRET", "").strip()
BANNER_URL      = os.environ.get("BANNER_URL", "").strip()

TAVILY_API_KEY  = os.environ.get("TAVILY_API_KEY", "").strip()
TAVILY_ENDPOINT = "https://api.tavily.com/search"

# STT: Deepgram (free tier) + OpenAI fallback
DEEPGRAM_API_KEY    = os.environ.get("DEEPGRAM_API_KEY", "").strip()
OPENAI_STT_PRIMARY  = os.environ.get("OPENAI_STT_PRIMARY", "gpt-4o-mini-transcribe").strip()
OPENAI_STT_FALLBACK = os.environ.get("OPENAI_STT_FALLBACK", "whisper-1").strip()

PORT = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")

# -------------------- SMALL UTILS --------------------
def tidy(s: str) -> str:
    return (s or "").strip()

def need_search(q: str) -> bool:
    """Простая эвристика: когда есть смысл идти в интернет."""
    ql = q.lower()
    if len(ql) < 3:
        return False
    triggers = [
        "когда", "дата", "сколько", "курс", "что такое", "найди",
        "новости", "кто такой", "как называется", "во сколько", "ссылка",
        "прогноз", "расписание", "адрес", "цена", "релиз", "выходит", "вышел",
    ]
    if any(t in ql for t in triggers):
        return True
    # вопросительный знак/цифры/конкретные сущности часто указывают на фактологию
    if "?" in ql or any(ch.isdigit() for ch in ql):
        return True
    return False

# -------------------- OPENAI CLIENT (lazy) --------------------
_openai_client = None
def get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client

# -------------------- TAVILY SEARCH --------------------
async def tavily_search(query: str, max_results: int = 5) -> dict:
    """Вернёт dict с 'answer' (краткий вывод) и 'results' (список ссылок)."""
    if not TAVILY_API_KEY:
        return {"answer": "", "results": []}
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "include_answer": True,
        "max_results": max_results,
        "search_depth": "advanced",
        "include_domains": [],  # можно ограничить домены, если нужно
    }
    try:
        async with httpx.AsyncClient(timeout=30) as sx:
            r = await sx.post(TAVILY_ENDPOINT, json=payload)
            r.raise_for_status()
            data = r.json()
            return {
                "answer": tidy(data.get("answer", "")),
                "results": data.get("results", []) or [],
            }
    except Exception as e:
        log.warning("Tavily error: %s", e)
        return {"answer": "", "results": []}

def format_sources(results: List[dict]) -> str:
    """Пул ссылок в bullet-список."""
    if not results:
        return ""
    lines = []
    for i, it in enumerate(results[:6], start=1):
        title = tidy(it.get("title") or it.get("url") or "")
        url = tidy(it.get("url") or "")
        if not url:
            continue
        lines.append(f"[{i}] {title} — {url}")
    return "\n" + "\n".join(lines) if lines else ""

# -------------------- IMAGE ANALYSIS --------------------
async def describe_image_bytes(image_bytes: bytes, user_prompt: Optional[str] = None) -> str:
    """
    Описание/извлечение текста с картинки.
    Картинку шлём как data:base64, чтобы не дергать внешние URL.
    """
    if not OPENAI_API_KEY:
        return "Извините, анализ изображений сейчас недоступен (нет ключа модели)."

    prompt = user_prompt or "Опиши изображение кратко и извлеки важные текстовые фрагменты (OCR), если они есть."
    b64 = base64.b64encode(image_bytes).decode("ascii")
    image_url = f"data:image/jpeg;base64,{b64}"

    try:
        client = get_openai()
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "Ты внимательный ассистент. Если на изображении есть текст — извлеки его отдельным блоком."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}}
                ]}
            ]
        )
        return tidy(resp.choices[0].message.content)
    except Exception as e:
        log.exception("Vision error: %s", e)
        return "Не удалось проанализировать изображение. Попробуй ещё раз или пришли другой файл."

# -------------------- STT: DEEPGRAM + OPENAI --------------------
async def stt_deepgram(audio_bytes: bytes, mimetype: str) -> str:
    """
    Deepgram prerecorded transcription.
    Документация: POST /v1/listen  (headers: Authorization: Token <key>)
    """
    if not DEEPGRAM_API_KEY:
        raise RuntimeError("NO_DEEPGRAM_KEY")

    params = {
        "punctuate": "true",
        "smart_format": "true",
        "detect_language": "true",  # можно добавить languages=ru,en при желании
    }
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": mimetype or "application/octet-stream",
    }
    async with httpx.AsyncClient(timeout=60) as sx:
        r = await sx.post("https://api.deepgram.com/v1/listen", params=params, headers=headers, content=audio_bytes)
        r.raise_for_status()
        data = r.json()
        # Путь к транскрипту
        alt = (((data.get("results") or {}).get("channels") or [{}])[0].get("alternatives") or [{}])[0]
        return tidy(alt.get("transcript", ""))

async def stt_openai(audio_bytes: bytes, filename: str, mimetype: str) -> str:
    client = get_openai()
    # 1) primary
    try:
        r = client.audio.transcriptions.create(
            model=OPENAI_STT_PRIMARY,
            file=(filename, audio_bytes, mimetype),
            response_format="text",
            temperature=0.0,
        )
        return r if isinstance(r, str) else tidy(getattr(r, "text", ""))
    except Exception:
        # 2) fallback
        r = client.audio.transcriptions.create(
            model=OPENAI_STT_FALLBACK,
            file=(filename, audio_bytes, mimetype),
            response_format="text",
            temperature=0.0,
        )
        return r if isinstance(r, str) else tidy(getattr(r, "text", ""))

async def transcribe_audio(audio_bytes: bytes, filename: str, mimetype: str) -> str:
    """
    Общая точка: сначала Deepgram (если есть ключ), затем OpenAI.
    """
    # 1) Deepgram
    if DEEPGRAM_API_KEY:
        try:
            txt = await stt_deepgram(audio_bytes, mimetype)
            if txt:
                return txt
        except Exception as e:
            log.warning("Deepgram STT failed: %s", e)

    # 2) OpenAI fallback
    if OPENAI_API_KEY:
        try:
            txt = await stt_openai(audio_bytes, filename, mimetype)
            if txt:
                return txt
        except Exception as e:
            log.warning("OpenAI STT failed: %s", e)

    raise RuntimeError("STT_FAILED")

# -------------------- LLM ANSWER (с опциональным поиском) --------------------
async def llm_answer(user_text: str, sources_block: str = "") -> str:
    if not OPENAI_API_KEY:
        return "OPENAI_API_KEY не задан. Сообщи админу."

    sys_prompt = (
        "Ты дружелюбный и лаконичный ассистент. "
        "Если тебе передали источники, опирайся на них и в конце выдай список ссылок. "
        "Если вопрос бытовой/простой — отвечай без ссылок."
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": (user_text + ("\n\nИсточники:\n" + sources_block if sources_block else ""))}
    ]
    try:
        client = get_openai()
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0.6,
        )
        return tidy(resp.choices[0].message.content)
    except Exception as e:
        log.exception("OpenAI error: %s", e)
        return "Не удалось получить ответ от модели. Попробуй ещё раз позже."

# -------------------- TELEGRAM HELPERS --------------------
async def download_tg_file_bytes(file_obj) -> Tuple[bytes, str, str]:
    """Скачать файл Telegram и вернуть (bytes, filename, mimetype)."""
    tg_file = await file_obj.get_file()
    url = tg_file.file_path
    # У Telegram CDN корректный HTTPS (общедоступный). Скачать байты:
    async with httpx.AsyncClient(timeout=60) as sx:
        r = await sx.get(url)
        r.raise_for_status()
        content = r.content
        # имя
        filename = os.path.basename(url.split("?")[0]) or "file.bin"
        # грубое угадывание mimetype
        if filename.endswith(".ogg"):
            mime = "audio/ogg"
        elif filename.endswith(".mp3"):
            mime = "audio/mpeg"
        elif filename.endswith(".m4a"):
            mime = "audio/m4a"
        elif filename.endswith(".mp4"):
            mime = "video/mp4"
        elif filename.endswith(".jpg") or filename.endswith(".jpeg"):
            mime = "image/jpeg"
        elif filename.endswith(".png"):
            mime = "image/png"
        else:
            mime = "application/octet-stream"
        return content, filename, mime

# -------------------- HANDLERS --------------------
START_HINT = (
    "Привет! Я готов. Напиши любой вопрос.\n\n"
    "Подсказки:\n"
    "• Я ищу свежую информацию в интернете для фактов и дат, когда это нужно.\n"
    "• Примеры: «Когда выйдет GTA 6?», «Курс биткоина сейчас и прогноз», "
    "«Найди учебник алгебры 11 класс (официальные источники)», «Новости по ...?»\n"
    "• Можно прислать фото — опишу и извлеку текст.\n"
    "• Можно отправить голосовое или видео — распознаю речь и отвечу по содержанию."
)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if BANNER_URL:
        try:
            await update.effective_message.reply_photo(BANNER_URL)
        except Exception:
            pass
    await update.effective_message.reply_text(START_HINT)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = tidy(update.effective_message.text)
    if not text:
        return

    # вежливое small-talk без поиска
    smalltalk = {"привет", "здравствуй", "здравствуйте", "hi", "hello", "добрый день", "доброе утро", "добрый вечер"}
    if text.lower() in smalltalk or text.lower().startswith(("прив", "здра")):
        await update.effective_message.reply_text("Привет! Как я могу помочь?")
        return

    sources_block = ""
    if need_search(text) and TAVILY_API_KEY:
        s = await tavily_search(text, max_results=5)
        sources_block = format_sources(s["results"])
        # Подменяем вопрос, если Tavily дал короткий summary
        if s["answer"]:
            text = f"{text}\n\nКраткая сводка по источникам: {s['answer']}"

    answer = await llm_answer(text, sources_block)
    if sources_block and sources_block not in answer:
        # если модель не вставила ссылки сама — добавим блоком
        answer = f"{answer}\n\nСсылки:\n{sources_block}"
    await update.effective_message.reply_text(answer)

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Берём фото лучшего качества (последний в списке)
        photo = update.effective_message.photo[-1]
        image_bytes, filename, mime = await download_tg_file_bytes(photo)
        desc = await describe_image_bytes(image_bytes)
        await update.effective_message.reply_text(desc)
    except Exception as e:
        log.exception("photo handler failed: %s", e)
        await update.effective_message.reply_text("Не удалось проанализировать изображение. Попробуй ещё раз.")

async def on_document_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Если картинка прислана как документ."""
    doc = update.effective_message.document
    if not doc or not (doc.mime_type or "").startswith("image/"):
        return
    try:
        image_bytes, filename, mime = await download_tg_file_bytes(doc)
        desc = await describe_image_bytes(image_bytes)
        await update.effective_message.reply_text(desc)
    except Exception as e:
        log.exception("doc image failed: %s", e)
        await update.effective_message.reply_text("Не удалось проанализировать изображение. Попробуй ещё раз.")

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Распознаём voice/audio → текст → как обычный вопрос."""
    try:
        v = update.effective_message.voice or update.effective_message.audio
        if not v:
            await update.effective_message.reply_text("Не нашёл голосовой файл.")
            return
        audio_bytes, filename, mime = await download_tg_file_bytes(v)
        text = await transcribe_audio(audio_bytes, filename, mime)
        if not text:
            await update.effective_message.reply_text("Не удалось распознать голос. Попробуй ещё раз.")
            return
        update.effective_message.text = text
        await on_text(update, context)
    except Exception as e:
        msg = str(e)
        if "insufficient_quota" in msg or "RateLimitError" in msg:
            await update.effective_message.reply_text(
                "Сейчас не могу распознавать голос: закончилась квота распознавания. "
                "Как только пополним — заработает."
            )
            return
        log.exception("voice handler failed: %s", e)
        await update.effective_message.reply_text("Не удалось распознать голос. Попробуй ещё раз.")

async def on_video_or_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Видео/кружок — берём аудиотрек (Deepgram/OpenAI принимают mp4) → текст."""
    v = update.effective_message.video or update.effective_message.video_note
    if not v:
        return
    try:
        bytes_, filename, mime = await download_tg_file_bytes(v)
        # большинство видео у Телеграма mp4
        if not mime.startswith("video/"):
            mime = "video/mp4"
        text = await transcribe_audio(bytes_, filename if filename.endswith(".mp4") else "video.mp4", mime)
        if not text:
            await update.effective_message.reply_text("Не удалось распознать речь в видео.")
            return
        update.effective_message.text = text
        await on_text(update, context)
    except Exception as e:
        log.exception("video handler failed: %s", e)
        await update.effective_message.reply_text("Не удалось распознать речь в видео. Попробуй другой файл.")

# -------------------- BOOTSTRAP --------------------
def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))

    # медиа
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, on_document_image))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, on_video_or_note))

    # текст
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
        secret_token=WEBHOOK_SECRET or None,
        drop_pending_updates=True,
    )

def main():
    app = build_app()
    run_webhook(app)

if __name__ == "__main__":
    main()
