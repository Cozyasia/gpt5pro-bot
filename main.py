# -*- coding: utf-8 -*-
"""
GPT-5 PRO Bot (Telegram, PTB v20+)

Ключевые фичи:
- OpenAI/OpenRouter через ENV:
    OPENAI_API_KEY   — ключ (OpenRouter или OpenAI)
    OPENAI_BASE_URL  — при работе через OpenRouter укажи: https://openrouter.ai/api/v1
    OPENAI_MODEL     — напр. "openai/gpt-4o-mini" (OpenRouter) или "gpt-4o-mini" (OpenAI)
    OPENROUTER_SITE_URL — (опц.) для X-Referer заголовка
    OPENROUTER_APP_NAME — (опц.) для X-Title заголовка
- Mini-App web_app_data: кнопки «Задать вопрос», «Подписка», «Открыть бота»
- Vision: фото/картинки, подпись к фото — в диалог
- Голос: Deepgram → fallback Whisper
- Веб-поиск Tavily (по эвристике should_browse)
- /start, /modes, /examples, клавиатура с WebApp-кнопками
- Вебхуки для Render: PUBLIC_URL/webhook/<BOT_TOKEN>
"""

import os
import re
import json
import base64
import logging
from io import BytesIO

import httpx
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)
from telegram.constants import ChatAction

# ================== LOGGING ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt5pro-bot")

# ================== ENV ==================
BOT_TOKEN        = os.environ.get("BOT_TOKEN", "").strip()
PUBLIC_URL       = os.environ.get("PUBLIC_URL", "").strip()      # https://<subdomain>.onrender.com
WEBAPP_URL       = os.environ.get("WEBAPP_URL", "").strip()      # если пусто — возьмём PUBLIC_URL
OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL  = os.environ.get("OPENAI_BASE_URL", "").strip() # OpenRouter: https://openrouter.ai/api/v1
OPENAI_MODEL     = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()

# «Вежливые» заголовки для OpenRouter (необязательно, но желательно)
OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "").strip()

WEBHOOK_SECRET   = os.environ.get("WEBHOOK_SECRET", "").strip()
BANNER_URL       = os.environ.get("BANNER_URL", "").strip()
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "").strip()
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "").strip()
TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1").strip()
PORT             = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")

WEB_ROOT = WEBAPP_URL or PUBLIC_URL  # базовый адрес для WebApp-страниц

# ================== OpenAI / OpenRouter client ==================
from openai import OpenAI

_default_headers = {}
# Для OpenRouter — корректно заполняем заголовки (они их любят)
if OPENROUTER_SITE_URL:
    _default_headers["HTTP-Referer"] = OPENROUTER_SITE_URL
if OPENROUTER_APP_NAME:
    _default_headers["X-Title"] = OPENROUTER_APP_NAME

oai = None
if OPENAI_API_KEY:
    # Если OPENAI_BASE_URL задан, клиент пойдёт в OpenRouter (или другой совместимый бэкенд)
    oai = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL or None,
        default_headers=_default_headers or None
    )

# ================== Tavily ==================
try:
    if TAVILY_API_KEY:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
    else:
        tavily = None
except Exception:
    tavily = None

# ================== PROMPTS ==================
SYSTEM_PROMPT = (
    "Ты дружелюбный и лаконичный ассистент на русском. "
    "Отвечай по сути, структурируй списками/шагами, не выдумывай факты. "
    "Если ссылаешься на источники — в конце дай короткий список ссылок."
)

VISION_SYSTEM_PROMPT = (
    "Ты чётко описываешь содержимое изображений: объекты, текст, схемы, графики. "
    "Не идентифицируй личности людей и не указывай имена, если они не напечатаны на изображении."
)

VISION_CAPABILITY_HELP = (
    "Да — анализирую изображения и помогаю с видео по кадрам, а ещё распознаю голос. ✅\n\n"
    "• Фото/скриншоты: JPG/PNG/WebP (до ~10 МБ) — опишу, прочитаю текст, разберу графики.\n"
    "• Документы/PDF: пришли как *файл*, извлеку текст/таблицы.\n"
    "• Видео: пришли 1–3 ключевых кадра (скриншота) — проанализирую по кадрам.\n"
    "• Голосовые/аудио: распознаю речь и отвечу по содержанию."
)

# ================== HEURISTICS ==================
_SMALLTALK_RE = re.compile(
    r"^(привет|здравствуй|добрый\s*(день|вечер|утро)|хи|hi|hello|хелло|как дела|спасибо|пока)\b",
    re.IGNORECASE
)
_NEWSY_RE = re.compile(
    r"(когда|дата|выйдет|релиз|новост|курс|цена|прогноз|что такое|кто такой|найди|ссылка|официал|адрес|телефон|"
    r"погода|сегодня|сейчас|штраф|закон|тренд|котировк|обзор|расписани|запуск|update|новая версия)",
    re.IGNORECASE
)
_CAPABILITY_RE = re.compile(
    r"(мож(ешь|но).{0,10}(анализ(ировать)?|распознав(ать|ание)).{0,10}(фото|картинк|изображен|image|picture)|"
    r"анализ(ировать)?.{0,8}(фото|картинк|изображен)|"
    r"(мож(ешь|но).{0,10})?(анализ|работать).{0,6}с.{0,6}видео)",
    re.IGNORECASE
)

def is_smalltalk(text: str) -> bool:
    return bool(_SMALLTALK_RE.search(text.strip()))

def should_browse(text: str) -> bool:
    t = text.strip()
    if is_smalltalk(t):
        return False
    return bool(_NEWSY_RE.search(t) or "?" in t or len(t) > 80)

def is_vision_capability_question(text: str) -> bool:
    return bool(_CAPABILITY_RE.search(text))

# ================== UTILS ==================
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

# ================== OPENAI HELPERS ==================
async def ask_openai_text(user_text: str, web_ctx: str = "") -> str:
    if not oai:
        return "Не удалось получить ответ от модели (ключ/лимит). Попробуй позже."

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if web_ctx:
        messages.append({"role": "system", "content": f"Контекст из веб-поиска:\n{web_ctx}"})
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
        return "Не удалось проанализировать изображение (ключ/лимит). Попробуй позже."
    try:
        resp = oai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text or "Опиши, что на изображении и какой там текст."},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}" }}
                    ]
                }
            ],
            temperature=0.4,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("Vision error: %s", e)
        return "Не удалось проанализировать изображение (лимит/ключ). Попробуй позже."

# ================== STT: Deepgram -> Whisper fallback ==================
async def transcribe_audio(buf: BytesIO, filename_hint: str = "audio.ogg") -> str:
    """
    1) Пытаемся распознать в Deepgram (если есть ключ).
    2) Если не получилось — fallback на OpenAI Whisper.
    """
    data = buf.getvalue()

    # --- Deepgram ---
    if DEEPGRAM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                params = {
                    "model": "nova-2",
                    "language": "ru",
                    "smart_format": "true",
                    "punctuate": "true",
                }
                headers = {
                    "Authorization": f"Token {DEEPGRAM_API_KEY}",
                    "Content-Type": "audio/ogg" if filename_hint.endswith(".ogg") else "application/octet-stream",
                }
                r = await client.post(
                    "https://api.deepgram.com/v1/listen",
                    params=params,
                    headers=headers,
                    content=data
                )
                r.raise_for_status()
                dg = r.json()
                text = (
                    dg.get("results", {})
                      .get("channels", [{}])[0]
                      .get("alternatives", [{}])[0]
                      .get("transcript", "")
                ).strip()
                if text:
                    return text
        except Exception as e:
            log.exception("Deepgram STT error: %s", e)

    # --- Whisper fallback ---
    if oai:
        try:
            buf2 = BytesIO(data)
            buf2.seek(0)
            setattr(buf2, "name", filename_hint)
            tr = oai.audio.transcriptions.create(
                model=TRANSCRIBE_MODEL,  # "whisper-1"
                file=buf2
            )
            return (tr.text or "").strip()
        except Exception as e:
            log.exception("Whisper STT error: %s", e)

    return ""

# ================== STATIC TEXTS ==================
START_TEXT = "Привет! Я готов. Чем помочь?"

MODES_TEXT = (
    "⚙️ *Режимы работы*\n"
    "• 💬 Универсальный — обычный диалог.\n"
    "• 🧠 Исследователь — факты/источники, сводки.\n"
    "• ✍️ Редактор — правки текста, стиль, структура.\n"
    "• 📊 Аналитик — формулы, таблицы, расчёты.\n"
    "• 🖼️ Визуальный — описание изображений, OCR, схемы.\n"
    "• 🎙️ Голос — распознаю аудио и отвечаю по содержанию.\n\n"
    "_Выбирай режим сообщением или просто сформулируй задачу._"
)

EXAMPLES_TEXT = (
    "🧩 *Примеры запросов*\n"
    "• «Сделай конспект главы 3 и выдели формулы»\n"
    "• «Проанализируй CSV, найди тренды и сделай краткий вывод»\n"
    "• «Составь письмо клиенту, дружелюбно и по делу»\n"
    "• «Суммируй статью из ссылки и дай источники»\n"
    "• «Опиши текст на фото и извлеки таблицу»"
)

# ================== START UI / KEYBOARD ==================
main_kb = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🧭 Меню", web_app=WebAppInfo(url=WEB_ROOT))],
        [KeyboardButton("⚙️ Режимы"), KeyboardButton("🧩 Примеры")],
        [KeyboardButton("⭐ Подписка", web_app=WebAppInfo(url=f"{WEB_ROOT}/premium.html"))],
    ],
    resize_keyboard=True
)

# ================== HANDLERS ==================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if BANNER_URL:
        try:
            await update.effective_message.reply_photo(BANNER_URL)
        except Exception:
            pass
    await update.effective_message.reply_text(START_TEXT, reply_markup=main_kb, disable_web_page_preview=True)

async def cmd_modes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(MODES_TEXT, disable_web_page_preview=True, parse_mode="Markdown")

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(EXAMPLES_TEXT, disable_web_page_preview=True, parse_mode="Markdown")

async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """События из мини-приложения (tg.sendData)."""
    msg = update.effective_message
    wad = getattr(msg, "web_app_data", None)
    if not wad:
        return
    raw = wad.data or ""
    try:
        payload = json.loads(raw) if raw.strip().startswith("{") else {"type": raw}
    except Exception:
        payload = {"type": str(raw)}

    ptype = (payload.get("type") or "").strip().lower()
    log.info("web_app_data: %s", payload)

    if ptype in ("help_from_webapp", "help", "question"):
        await msg.reply_text(
            "🧑‍💻 Поддержка GPT-5 PRO.\nНапиши здесь свой вопрос — отвечу в чате.\n\n"
            "Также можно на почту: sale.rielt@bk.ru"
        )
        return

    if ptype in ("plan_from_webapp", "plan", "subscribe", "subscription"):
        kb = ReplyKeyboardMarkup(
            [[KeyboardButton("⭐ Открыть подписку", web_app=WebAppInfo(url=f"{WEB_ROOT}/premium.html"))]],
            resize_keyboard=True, one_time_keyboard=True
        )
        await msg.reply_text("Оформить подписку можно по кнопке ниже. ⤵️", reply_markup=kb)
        return

    if ptype in ("open_bot", "open"):
        await msg.reply_text("Открыл бота. Можешь писать сюда свой запрос. 🙂", reply_markup=main_kb)
        return

    await msg.reply_text("Открыл бота. Чем помочь?", reply_markup=main_kb)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id

    lower = text.lower()
    if lower in ("⚙️ режимы", "режимы", "/modes"):
        await cmd_modes(update, context); return
    if lower in ("🧩 примеры", "примеры", "/examples"):
        await cmd_examples(update, context); return

    if is_vision_capability_question(text):
        await update.message.reply_text(VISION_CAPABILITY_HELP, disable_web_page_preview=True)
        return

    await typing(context, chat_id)

    if is_smalltalk(text):
        reply = await ask_openai_text(text)
        await update.message.reply_text(reply)
        return

    # Веб-поиск по эвристике
    web_ctx, sources = "", []
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

async def _handle_image_bytes(update: Update, context: ContextTypes.DEFAULT_TYPE, data: bytes, user_text: str):
    mime = sniff_image_mime(data)
    img_b64 = base64.b64encode(data).decode("ascii")
    answer = await ask_openai_vision(user_text, img_b64, mime)
    await update.message.reply_text(answer, disable_web_page_preview=True)

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await typing(context, chat_id)

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    buf = BytesIO()
    await file.download_to_memory(buf)
    user_text = (update.message.caption or "").strip()
    await _handle_image_bytes(update, context, buf.getvalue(), user_text)

async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Картинки, присланные как файл (image/*). PDF/документы — даём подсказку."""
    chat_id = update.effective_chat.id
    await typing(context, chat_id)

    doc = update.message.document
    mime = (doc.mime_type or "").lower()
    if mime.startswith("image/"):
        file = await context.bot.get_file(doc.file_id)
        buf = BytesIO()
        await file.download_to_memory(buf)
        user_text = (update.message.caption or "").strip()
        await _handle_image_bytes(update, context, buf.getvalue(), user_text)
    else:
        await update.message.reply_text(
            "Файл получил. Если это PDF/документ — пришли конкретные страницы как изображения или укажи, что извлечь."
        )

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Voice message (OGG/OPUS)."""
    chat_id = update.effective_chat.id
    await typing(context, chat_id)

    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    buf = BytesIO()
    await file.download_to_memory(buf)

    text = await transcribe_audio(buf, filename_hint="audio.ogg")
    if not text:
        await update.message.reply_text("Не удалось распознать голос. Попробуй ещё раз.")
        return

    prefix = f"🗣️ Распознал: «{text}»\n\n"
    web_ctx, sources = "", []
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
    answer = prefix + answer + format_sources(sources)
    await update.message.reply_text(answer, disable_web_page_preview=False)

async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обычные аудиофайлы (mp3/m4a/wav) — обрабатываем как voice."""
    chat_id = update.effective_chat.id
    await typing(context, chat_id)

    audio = update.message.audio
    file = await context.bot.get_file(audio.file_id)
    buf = BytesIO()
    await file.download_to_memory(buf)

    filename = (audio.file_name or "audio.mp3")
    text = await transcribe_audio(buf, filename_hint=filename)
    if not text:
        await update.message.reply_text("Не удалось распознать аудио. Попробуй ещё раз.")
        return

    prefix = f"🗣️ Распознал: «{text}»\n\n"
    web_ctx, sources = "", []
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
    answer = prefix + answer + format_sources(sources)
    await update.message.reply_text(answer, disable_web_page_preview=False)

async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Позитивный ответ на видео: просим прислать ключевые кадры."""
    await update.message.reply_text(
        "Да, помогу с видео: пришли 1–3 ключевых кадра (скриншота) — проанализирую по кадрам и отвечу по содержанию. 📽️"
    )

# ================== BOOTSTRAP ==================
def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("modes", cmd_modes))
    app.add_handler(CommandHandler("examples", cmd_examples))

    # события из WebApp (tg.sendData)
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))

    # текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    # фото и документы-картинки
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, on_document))
    # голосовые и аудио
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.AUDIO, on_audio))
    # видео — даём позитивную инструкцию
    app.add_handler(MessageHandler(filters.VIDEO, on_video))
    return app

def run_webhook(app):
    # уникальный путь, чтобы никто посторонний не дёргал
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
