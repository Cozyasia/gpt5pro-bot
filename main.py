# -*- coding: utf-8 -*-
import os
import re
import json
import base64
import logging
from io import BytesIO

import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ChatAction

# ========== LOGGING ==========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")

# ========== ENV ==========
BOT_TOKEN        = os.environ.get("BOT_TOKEN", "").strip()
PUBLIC_URL       = os.environ.get("PUBLIC_URL", "").strip()   # https://<subdomain>.onrender.com
WEBHOOK_SECRET   = os.environ.get("WEBHOOK_SECRET", "").strip()
BANNER_URL       = os.environ.get("BANNER_URL", "").strip()   # можно пустым
PORT             = int(os.environ.get("PORT", "10000"))

OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL     = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1").strip()

DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "").strip()
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")
if not OPENAI_API_KEY:
    log.warning("OPENAI_API_KEY is empty — ответы модели работать не будут")

# ========== CLIENTS ==========
from openai import OpenAI
oai = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

try:
    if TAVILY_API_KEY:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
    else:
        tavily = None
except Exception:
    tavily = None

httpx_client = httpx.AsyncClient(timeout=60)

# ========== PROMPTS ==========
SYSTEM_PROMPT = (
    "Ты дружелюбный и лаконичный ассистент на русском. "
    "Отвечай по сути, добавляй списки и шаги, когда это полезно. "
    "Если приводишь источники — в конце дай короткий список ссылок. "
    "Не выдумывай факты; если не уверен — скажи об этом."
)

VISION_SYSTEM_PROMPT = (
    "Ты описываешь изображения: предметы, текст, макеты, графики. "
    "Не определяй личности людей и не давай их имен, если они не напечатаны на изображении. "
    "Будь конкретным и полезным."
)

VISION_CAPABILITY_HELP = (
    "Да — я умею анализировать изображения и помогать с видео.\n\n"
    "• Фото/скриншоты: пришли JPG/PNG/WebP — опишу содержимое и извлеку текст.\n"
    "• Видео: пришли короткий MP4 — извлеку речь и отвечу по содержанию; "
    "для визуального разбора пришли 1–3 ключевых кадра.\n"
    "• Голосовые/аудио: отправь голосовое — распознаю и отвечу по смыслу."
)

# Расширенная эвристика: вопрос о способностях анализировать фото/видео/голос
def asks_about_capabilities(text: str) -> bool:
    t = text.lower()
    has_media_word = any(w in t for w in ("фото", "картинк", "изображен", "image", "picture", "видео", "video", "голос", "аудио"))
    has_action_word = any(w in t for w in ("анализ", "анализиру", "распозна", "видиш", "умееш", "можеш", "обрабатыва", "работаешь"))
    return has_media_word and has_action_word

_SMALLTALK_RE = re.compile(
    r"^(привет|здравствуй|добрый\s*(день|вечер|утро)|хи|hi|hello|хелло|как дела|спасибо|пока)\b",
    re.IGNORECASE
)
_NEWSY_RE = re.compile(
    r"(когда|дата|выйдет|релиз|новост|курс|цена|прогноз|что такое|кто такой|найди|ссылка|официал|адрес|телефон|"
    r"погода|сегодня|сейчас|штраф|закон|тренд|котировк|обзор|расписани|запуск|update|новая версия)",
    re.IGNORECASE
)

def is_smalltalk(text: str) -> bool:
    return bool(_SMALLTALK_RE.search(text.strip()))

def should_browse(text: str) -> bool:
    t = text.strip()
    if is_smalltalk(t):
        return False
    if _NEWSY_RE.search(t) or "?" in t or len(t) > 80:
        return True
    return False

# ========== UTILS ==========
async def typing(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        await ctx.bot.send_chat_action(chat_id, action=ChatAction.TYPING)
    except Exception:
        pass

def sniff_image_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[:4] == b"RIFF" and b"WEBP" in data[:16]:
        return "image/webp"
    return "image/jpeg"

def sniff_av_mime(data: bytes, filename_hint: str = "") -> str:
    name = (filename_hint or "").lower()
    if data[:4] == b"OggS" or name.endswith(".ogg") or "opus" in name:
        return "audio/ogg"
    if data[:3] == b"ID3" or name.endswith(".mp3"):
        return "audio/mpeg"
    if name.endswith(".m4a"):
        return "audio/mp4"
    if b"ftyp" in data[:16] and (name.endswith(".mp4") or name.endswith(".mov") or name.endswith(".m4v")):
        # для видео подойдёт video/mp4 — Deepgram сам вытащит аудиодорожку
        return "video/mp4"
    if name.endswith(".wav"):
        return "audio/wav"
    return "application/octet-stream"

def format_sources(items):
    if not items:
        return ""
    lines = []
    for i, it in enumerate(items, 1):
        title = it.get("title") or it.get("url") or "Источник"
        url = it.get("url") or ""
        lines.append(f"[{i}] {title} — {url}")
    return "\n\nСсылки:\n" + "\n".join(lines)

def tavily_search(query: str, max_results: int = 5):
    if not tavily:
        return None, []
    try:
        res = tavily.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
            include_answer=True,
            include_raw_content=False,
        )
        answer = res.get("answer") or ""
        results = res.get("results") or []
        return answer, results
    except Exception as e:
        log.exception("Tavily error: %s", e)
        return None, []

# ========== OPENAI CALLS ==========
async def ask_openai_text(user_text: str, web_ctx: str = "") -> str:
    if not oai:
        return "OPENAI_API_KEY не задан. Сообщи админу."
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({"role": "system", "content": f"В помощь тебе контекст с веб-источниками:\n{web_ctx}"})
    messages.append({"role": "user", "content": user_text})
    try:
        resp = oai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0.6,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("OpenAI chat error: %s", e)
        return "Не удалось получить ответ от модели (лимит/ключ). Попробуй позже."

async def ask_openai_vision(user_text: str, img_b64: str, mime: str) -> str:
    if not oai:
        return "OPENAI_API_KEY не задан. Сообщи админу."
    try:
        resp = oai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text or "Опиши, что на изображении и какой там текст."},
                        {"type": "image_url",
                         "image_url": {"url": f"data:{mime};base64,{img_b64}"}}
                    ]
                }
            ],
            temperature=0.4,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("Vision error: %s", e)
        return "Не удалось проанализировать изображение. Попробуй ещё раз или пришли другой файл."

# ========== STT (Deepgram -> OpenAI fallback) ==========
async def deepgram_transcribe(data: bytes, content_type: str) -> str:
    """Распознаём речь через Deepgram. Возвращаем текст или пустую строку."""
    if not DEEPGRAM_API_KEY:
        return ""
    try:
        params = {
            "smart_format": "true",
            "punctuate": "true",
            "language": "ru",   # можно auto с detect_language=true, но так быстрее/дешевле
        }
        headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": content_type or "application/octet-stream",
        }
        r = await httpx_client.post(
            "https://api.deepgram.com/v1/listen",
            params=params,
            headers=headers,
            content=data,
        )
        if r.status_code != 200:
            log.error("Deepgram HTTP %s: %s", r.status_code, r.text[:500])
            return ""
        j = r.json()
        # универсальный парсинг
        transcript = (
            j.get("results", {})
             .get("channels", [{}])[0]
             .get("alternatives", [{}])[0]
             .get("transcript", "")
            or j.get("results", {})
             .get("channels", [{}])[0]
             .get("alternatives", [{}])[0]
             .get("paragraphs", {})
             .get("transcript", "")
        )
        return (transcript or "").strip()
    except Exception as e:
        log.exception("Deepgram error: %s", e)
        return ""

async def openai_transcribe(buf: BytesIO, filename_hint: str) -> str:
    if not oai:
        return ""
    try:
        buf.seek(0)
        setattr(buf, "name", filename_hint)
        tr = oai.audio.transcriptions.create(model=TRANSCRIBE_MODEL, file=buf)
        return (tr.text or "").strip()
    except Exception as e:
        log.exception("OpenAI Whisper error: %s", e)
        return ""

async def transcribe_audio_unified(raw: bytes, filename_hint: str = "") -> str:
    """Единая точка входа: сначала Deepgram, если нет — OpenAI Whisper."""
    ct = sniff_av_mime(raw, filename_hint)
    # 1) Deepgram
    if DEEPGRAM_API_KEY:
        text = await deepgram_transcribe(raw, ct)
        if text:
            return text
    # 2) OpenAI fallback (нужно file-like)
    buf = BytesIO(raw)
    return await openai_transcribe(buf, filename_hint or "audio.bin")

# ========== HANDLERS ==========
START_GREETING = (
    "Привет! Я готов. Напиши любой вопрос.\n\n"
    "Подсказки:\n"
    "• Я ищу свежую информацию в интернете для фактов и дат, когда это нужно.\n"
    "• Примеры: «Когда выйдет GTA 6?», «Курс биткоина сейчас и прогноз», "
    "«Найди учебник алгебры 11 класс (официальные источники)», «Новости по …?»\n"
    "• Можно прислать фото — опишу и извлеку текст.\n"
    "• Можно отправить голосовое/аудио/видео — распознаю речь и отвечу по содержанию."
)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if BANNER_URL:
        try:
            await update.effective_message.reply_photo(BANNER_URL)
        except Exception:
            pass
    await update.effective_message.reply_text(START_GREETING)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id

    # Явный вопрос про «умеешь ли анализировать…» — отвечаем утверждением
    if asks_about_capabilities(text):
        await update.message.reply_text(VISION_CAPABILITY_HELP, disable_web_page_preview=True)
        return

    await typing(context, chat_id)

    if is_smalltalk(text):
        reply = await ask_openai_text(text)
        await update.message.reply_text(reply)
        return

    web_ctx = ""
    sources = []
    if should_browse(text):
        answer_from_search, results = tavily_search(text, max_results=5)
        sources = results or []
        ctx_lines = []
        if answer_from_search:
            ctx_lines.append(f"Краткая сводка поиском: {answer_from_search}")
        for i, it in enumerate(sources, 1):
            ctx_lines.append(f"[{i}] {it.get('title','')}: {it.get('url','')}")
        web_ctx = "\n".join(ctx_lines)

    answer = await ask_openai_text(text, web_ctx=web_ctx)
    answer += format_sources(sources)
    await update.message.reply_text(answer, disable_web_page_preview=False)

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await typing(context, chat_id)

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    buf = BytesIO()
    await file.download_to_memory(buf)
    data = buf.getvalue()

    mime = sniff_image_mime(data)
    img_b64 = base64.b64encode(data).decode("ascii")
    user_text = (update.message.caption or "").strip()

    answer = await ask_openai_vision(user_text, img_b64, mime)
    await update.message.reply_text(answer, disable_web_page_preview=True)

async def handle_stt_reply(update: Update, recognized_text: str):
    """Общий ответ после распознавания речи."""
    prefix = f"🗣️ Распознал: «{recognized_text}»\n\n"
    web_ctx = ""
    sources = []
    if should_browse(recognized_text):
        answer_from_search, results = tavily_search(recognized_text, max_results=5)
        sources = results or []
        ctx_lines = []
        if answer_from_search:
            ctx_lines.append(f"Краткая сводка поиском: {answer_from_search}")
        for i, it in enumerate(sources, 1):
            ctx_lines.append(f"[{i}] {it.get('title','')}: {it.get('url','')}")
        web_ctx = "\n".join(ctx_lines)

    answer = await ask_openai_text(recognized_text, web_ctx=web_ctx)
    return prefix + answer + format_sources(sources)

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram voice (OGG/OPUS)."""
    chat_id = update.effective_chat.id
    await typing(context, chat_id)

    file = await context.bot.get_file(update.message.voice.file_id)
    buf = BytesIO()
    await file.download_to_memory(buf)
    raw = buf.getvalue()

    text = await transcribe_audio_unified(raw, filename_hint="audio.ogg")
    if not text:
        await update.message.reply_text("Не удалось распознать голос. Попробуй ещё раз.")
        return

    reply = await handle_stt_reply(update, text)
    await update.message.reply_text(reply, disable_web_page_preview=False)

async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обычные аудио-файлы (mp3/m4a/wav)."""
    chat_id = update.effective_chat.id
    await typing(context, chat_id)

    audio = update.message.audio
    file = await context.bot.get_file(audio.file_id)
    buf = BytesIO()
    await file.download_to_memory(buf)
    raw = buf.getvalue()

    filename = (audio.file_name or "audio.mp3")
    text = await transcribe_audio_unified(raw, filename_hint=filename)
    if not text:
        await update.message.reply_text("Не удалось распознать аудио. Попробуй ещё раз.")
        return

    reply = await handle_stt_reply(update, text)
    await update.message.reply_text(reply, disable_web_page_preview=False)

async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Короткие видео (mp4) — отправляем целиком в Deepgram, он сам вытащит аудио."""
    chat_id = update.effective_chat.id
    await typing(context, chat_id)

    video = update.message.video
    file = await context.bot.get_file(video.file_id)
    buf = BytesIO()
    await file.download_to_memory(buf)
    raw = buf.getvalue()

    filename = (video.file_name or "video.mp4")
    text = await transcribe_audio_unified(raw, filename_hint=filename)
    if not text:
        await update.message.reply_text("Не удалось извлечь речь из видео. Пришли 1–3 кадра (скриншота) — разберу по изображениям.")
        return

    reply = await handle_stt_reply(update, text)
    await update.message.reply_text(reply, disable_web_page_preview=False)

# ========== BOOTSTRAP ==========
def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.AUDIO, on_audio))
    app.add_handler(MessageHandler(filters.VIDEO, on_video))
    return app

def run_webhook(app):
    url_path = f"webhook/{BOT_TOKEN}"
    webhook_url = f"{PUBLIC_URL.rstrip('/')}/{url_path}"

    log.info("Starting webhook on 0.0.0.0:%s  ->  %s", PORT, webhook_url)
    # ВАЖНО: только webhook, без polling — иначе будет 409 Conflict
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
