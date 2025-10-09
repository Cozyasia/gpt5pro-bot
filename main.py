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
OPENAI_MODEL   = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
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
    "• Я **отвечаю сам**, а если нужно — **сверяюсь с интернетом** и даю ссылки.\n"
    "• Примеры: «Дата выхода GTA 6?», «Курс биткоина сейчас и прогноз», "
    "«Найди учебник алгебры 11 класс (официальные источники)», «Новости по …», "
    "«Кто такой …?» и т.д."
)

# -------------------- HEURISTICS --------------------
_greetings = re.compile(r"\b(прив(ет|ствую)|здравств|доброе|добрый|hello|hi|hey)\b", re.I)
_smalltalk = re.compile(r"(как дела|кто ты|что умеешь|спасибо|благодарю|пока|до свид|рад знакомству)", re.I)
_no_web_hint = re.compile(r"(без интернета|не ищи|не гугли)", re.I)

# ключевые индикаторы, когда почти всегда нужно идти в сеть
_need_web_keywords = [
    # актуалка/новости/даты/курсы/расписания/погода
    "сегодня", "сейчас", "завтра", "новост", "обновлен", "релиз", "когда", "дата",
    "курс", "котиров", "цена", "стоимость", "ставка", "индекс", "акци", "биткоин", "btc",
    "погода", "расписан", "трансляц", "матч", "турнир", "рейс", "самолет", "поезд",
    # «найди / дай ссылку / pdf / скачать / оф.источники»
    "найди", "ссылка", "ссылки", "официальн", "википед", "pdf", "скачать", "документ",
    "учебник", "мануал", "руководств", "адрес", "телефон", "контакты", "как добраться",
]

def need_web_search(text: str) -> bool:
    """Грубая, но практичная эвристика: решаем, нужен ли интернет."""
    t = text.strip().lower()

    if _no_web_hint.search(t):
        return False  # пользователь явно просит без сети

    # совсем короткие/ритуальные — не ищем
    if len(t) <= 2 or _greetings.search(t) or _smalltalk.search(t):
        return False

    # прямые «поисковые» маркеры
    for kw in _need_web_keywords:
        if kw in t:
            return True

    # вопросы в форме «что/кто/где/когда/почему/как ...?» часто требуют фактов.
    if re.search(r"\b(что|кто|где|когда|почему|зачем|какой|какие|сколько|как)\b", t) and "пример" not in t:
        # если это явно про письмо/перевод/перефраз — оставим оффлайн
        if any(x in t for x in ["переведи", "перевод", "перепиши", "сформулируй", "придумай", "написать", "наполни"]):
            return False
        return True

    # длинные «реферативные» запросы (>= 160 символов) часто полезно проверить источниками
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
    """
    Ищем через Tavily и возвращаем (краткий_итог, [(title, url), ...])
    """
    try:
        from tavily import TavilyClient
        tv = TavilyClient(api_key=TAVILY_API_KEY)
        res = tv.search(
            query=query,
            search_depth="advanced",
            max_results=6,
            include_answer=True,
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
    """
    Склеиваем финальный ответ: анализ + ссылки.
    """
    # Подмешаем веб-выжимку как контекст и попросим ИИ оформить вывод.
    context = (
        "Используй сводку из поиска и оформи ясный ответ на русском. "
        "Если в сводке нет точного факта — честно скажи, что данных нет/они противоречивы. "
        "Не пиши огромный реферат — 3–7 коротких абзацев или список. "
        "В конце перечисли источники списком."
    )
    combined_prompt = (
        f"Вопрос пользователя: {user_text}\n\n"
        f"Сводка из поиска:\n{web_answer or '—'}\n"
        f"(Подробные ссылки будут добавлены ниже ботом.)"
    )
    body = llm_answer(combined_prompt, system_hint=context)

    if sources:
        links = "\n".join([f"• {title} — {url}" for title, url in sources[:6]])
        body = f"{body}\n\nСсылки:\n{links}"
    return body

# -------------------- HANDLERS --------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Если есть баннер – отправим первым сообщением (молча, игнорируя ошибки)
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

    # 1) решаем, нужен ли веб
    use_web = bool(TAVILY_API_KEY) and need_web_search(text)

    # 2) если веб не нужен — обычный ответ (small talk / креатив / объяснения)
    if not use_web:
        answer = llm_answer(text)
        await update.message.reply_text(answer, disable_web_page_preview=True)
        return

    # 3) веб нужен — ищем и оформляем
    web_answer, sources = web_search(text)

    if not web_answer and not sources:
        # не повезло — честно ответим и дадим обычный оффлайн-ответ
        fallback = llm_answer(
            f"Пользователь спросил: {text}\n"
            f"Поиск в интернете временно не дал результатов. "
            f"Дай общий ответ и предложи уточнить критерии/источники."
        )
        await update.message.reply_text(fallback, disable_web_page_preview=True)
        return

    final = synthesize_with_sources(text, web_answer, sources)
    await update.message.reply_text(final, disable_web_page_preview=True)

# -------------------- BOOTSTRAP --------------------
def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
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
