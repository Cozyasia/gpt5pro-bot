# -*- coding: utf-8 -*-
import os
import re
import logging
from typing import List, Tuple

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
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "").strip()
PUBLIC_URL     = os.environ.get("PUBLIC_URL", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL   = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()  # поддерживает изображения
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()
BANNER_URL     = os.environ.get("BANNER_URL", "").strip()
PORT           = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")

# -------------------- TEXTS --------------------
START_GREETING = (
    "Привет! Я готов. Напиши любой вопрос.\n\n"
    "Подсказки:\n"
    "• Я отвечаю сам, а если нужно — сверяюсь с интернетом и даю ссылки.\n"
    "• Могу анализировать фото/картинки (через 📎) — прочитать текст, описать объекты, сделать выводы.\n"
    "• Примеры: «Дата выхода GTA 6?», «Курс биткоина сейчас и прогноз», "
    "«Найди учебник алгебры 11 класс (официальные источники)», «Кто такой …?» и т.д."
)

# -------------------- HEURISTICS --------------------
_greetings = re.compile(r"\b(прив(ет|ствую)|здравств|доброе|добрый|hello|hi|hey)\b", re.I)
_smalltalk = re.compile(r"(как дела|кто ты|что умеешь|спасибо|благодарю|пока|до свид|рад знакомству)", re.I)
_no_web_hint = re.compile(r"(без интернета|не ищи|не гугли)", re.I)

_need_web_keywords = [
    "сегодня", "сейчас", "завтра", "новост", "обновлен", "релиз", "когда", "дата",
    "курс", "котиров", "цена", "стоимость", "ставка", "индекс", "акци", "биткоин", "btc",
    "погода", "расписан", "трансляц", "матч", "турнир", "рейс", "самолет", "поезд",
    "найди", "ссылка", "ссылки", "официальн", "википед", "pdf", "скачать", "документ",
    "учебник", "мануал", "руководств", "адрес", "телефон", "контакты", "как добраться",
]

def need_web_search(text: str) -> bool:
    t = text.strip().lower()
    if _no_web_hint.search(t):
        return False
    if len(t) <= 2 or _greetings.search(t) or _smalltalk.search(t):
        return False
    for kw in _need_web_keywords:
        if kw in t:
            return True
    if re.search(r"\b(что|кто|где|когда|почему|зачем|какой|какие|сколько|как)\b", t) and "пример" not in t:
        if any(x in t for x in ["переведи", "перевод", "перепиши", "сформулируй", "придумай", "написать", "наполни"]):
            return False
        return True
    return len(t) >= 160

# -------------------- LLM & SEARCH --------------------
from openai import OpenAI
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

def llm_answer(user_text: str, system_hint: str = "") -> str:
    sp = (
        "Ты дружелюбный и лаконичный ассистент. Отвечай по делу, "
        "не выдумывай фактов. Если не хватает контекста — предложи уточнить."
    )
    if system_hint:
        sp += " " + system_hint
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": sp},
                {"role": "user", "content": user_text},
            ],
            temperature=0.6,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("OpenAI error: %s", e)
        return "Не удалось получить ответ от модели. Попробуй ещё раз позже."

def web_search(query: str) -> Tuple[str, List[Tuple[str, str]]]:
    try:
        from tavily import TavilyClient
        tv = TavilyClient(api_key=TAVILY_API_KEY)
        res = tv.search(
            query=query, search_depth="advanced",
            max_results=6, include_answer=True,
        )
        answer = (res.get("answer") or "").strip()
        sources = []
        for item in res.get("results", []):
            title = (item.get("title") or "Источник").strip()
            url = (item.get("url") or "").strip()
            if url:
                sources.append((title, url))
        return answer, sources
    except Exception as e:
        log.exception("Tavily error: %s", e)
        return "", []

def synthesize_with_sources(user_text: str, web_answer: str, sources: List[Tuple[str, str]]) -> str:
    context = (
        "Используй сводку из поиска и оформи ясный ответ на русском. "
        "Если в сводке нет точного факта — скажи об этом. "
        "Не пиши огромный реферат — 3–7 коротких абзацев или список. "
        "В конце перечисли источники списком."
    )
    combined_prompt = (
        f"Вопрос пользователя: {user_text}\n\n"
        f"Сводка из поиска:\n{web_answer or '—'}\n"
        f"(Подробные ссылки добавит бот.)"
    )
    body = llm_answer(combined_prompt, system_hint=context)
    if sources:
        links = "\n".join([f"• {title} — {url}" for title, url in sources[:6]])
        body = f"{body}\n\nСсылки:\n{links}"
    return body

# ---------- Helpers для загрузок из Telegram ----------
async def _tg_file_url(context: ContextTypes.DEFAULT_TYPE, file_id: str) -> str:
    """
    Получаем прямую ссылку на файл Telegram (с токеном бота).
    OpenAI сможет её скачать, чтобы проанализировать изображение.
    """
    f = await context.bot.get_file(file_id)
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{f.file_path}"

def vision_on_image(image_url: str, user_hint: str = "") -> str:
    """
    Анализ изображения через модель с поддержкой vision.
    """
    try:
        sys = (
            "Ты компьютерное зрение-ассистент. Описывай кратко и точно, "
            "извлекай ключевые факты, перечисляй объекты, по возможности считывай текст (OCR) "
            "и делай выводы, полезные пользователю."
        )
        user_text = user_hint.strip() or "Проанализируй изображение. Извлеки текст, перечисли важные объекты и сделай выводы."
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ]},
            ],
            temperature=0.2,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("Vision error: %s", e)
        return "Не удалось проанализировать изображение. Попробуй ещё раз или пришли другой файл."

# -------------------- HANDLERS --------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if BANNER_URL:
        try:
            await update.effective_message.reply_photo(BANNER_URL)
        except Exception:
            pass
    await update.effective_message.reply_text(START_GREETING, disable_web_page_preview=True)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not OPENAI_API_KEY:
        await update.message.reply_text("OPENAI_API_KEY не задан. Сообщи админу.")
        return

    use_web = bool(TAVILY_API_KEY) and need_web_search(text)
    if not use_web:
        answer = llm_answer(text)
        await update.message.reply_text(answer, disable_web_page_preview=True)
        return

    web_answer, sources = web_search(text)
    if not web_answer and not sources:
        fallback = llm_answer(
            f"Пользователь спросил: {text}\n"
            f"Поиск в интернете временно не дал результатов. "
            f"Дай общий ответ и предложи уточнить критерии/источники."
        )
        await update.message.reply_text(fallback, disable_web_page_preview=True)
        return

    final = synthesize_with_sources(text, web_answer, sources)
    await update.message.reply_text(final, disable_web_page_preview=True)

# ---- Фото и картинки (включая отправленные «как файл») ----
async def on_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    caption = (msg.caption or "").strip()

    file_id = None
    if msg.photo:
        # берём самое большое превью
        file_id = msg.photo[-1].file_id
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        file_id = msg.document.file_id

    if not file_id:
        await msg.reply_text("Файл не распознан как изображение.")
        return

    if not OPENAI_API_KEY:
        await msg.reply_text("OPENAI_API_KEY не задан. Сообщи админу.")
        return

    try:
        url = await _tg_file_url(context, file_id)
        result = vision_on_image(url, user_hint=caption)
        await msg.reply_text(result, disable_web_page_preview=True)
    except Exception as e:
        log.exception("on_image error: %s", e)
        await msg.reply_text("Не удалось обработать изображение. Попробуй ещё раз.")

# ---- Видео: разбираем превью-кадр (thumbnail) ----
async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    v = msg.video
    thumb = getattr(v, "thumbnail", None) or getattr(v, "thumb", None)

    if not thumb:
        await msg.reply_text(
            "Я получил видео. Сейчас могу анализировать его превью-кадр. "
            "Пожалуйста, пришли скриншоты ключевых моментов — дам подробный разбор."
        )
        return

    if not OPENAI_API_KEY:
        await msg.reply_text("OPENAI_API_KEY не задан. Сообщи админу.")
        return

    try:
        url = await _tg_file_url(context, thumb.file_id)
        hint = (msg.caption or "").strip()
        hint = ("Это превью кадр видео. Опиши, что видно, считай текст, "
                "выдели ключевые объекты и сделай выводы. " + (hint if hint else ""))
        result = vision_on_image(url, user_hint=hint)
        await msg.reply_text(result, disable_web_page_preview=True)
    except Exception as e:
        log.exception("on_video error: %s", e)
        await msg.reply_text("Не удалось обработать превью видео. Пришли скриншоты — разберу их.")

# -------------------- BOOTSTRAP --------------------
def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))

    # медиа
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_image))
    app.add_handler(MessageHandler(filters.VIDEO, on_video))

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
