# -*- coding: utf-8 -*-
import os
import logging
from typing import List, Dict

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
TAVILY_API_KEY  = os.environ.get("TAVILY_API_KEY", "").strip()

# баннер для /start (положи картинку и укажи прямую ссылку)
BANNER_URL      = os.environ.get("BANNER_URL", "").strip()

PORT            = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")

# -------------------- HELPERS --------------------
def wants_web(q: str) -> bool:
    """Грубая эвристика: когда стоит звать веб-поиск."""
    text = (q or "").lower()

    # явные принуждения к вебу
    force_words = [
        "в интернете", "в сети", "онлайн",
        "найти", "найди", "ищи", "поищи", "поиск",
        "новости", "сегодня", "сейчас",
        "кто такой", "что такое",
        "курс", "цена", "погода",
        "список", "топ", "лучшие",
        "pdf", "github", "скачать", "инструкция",
        "учебник", "реферат", "статья", "официальный сайт",
    ]
    if any(w in text for w in force_words):
        return True

    # вопросительный знак часто означает запрос фактов
    if "?" in text:
        return True

    # Негативные триггеры: генеративные задания без интернета
    negative = ["напиши", "сочини", "перепиши", "сгенерируй",
                "придумай", "переведи", "рассчитай", "посчитай"]
    if any(w in text for w in negative):
        return False

    return False


def build_sources_block(results: List[Dict], limit: int = 5) -> str:
    lines = []
    for it in results[:limit]:
        url = it.get("url") or ""
        title = it.get("title") or url
        lines.append(f"• {title}\n{url}")
    return "\n".join(lines)


async def answer_via_openai(prompt: str) -> str:
    """Обычный ответ модели без веба."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        sys_prompt = "Ты дружелюбный и лаконичный ассистент. Отвечай по сути на русском языке."
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("OpenAI error: %s", e)
        return "Не удалось получить ответ от модели. Попробуй ещё раз позже."


async def answer_via_web(prompt: str) -> str:
    """Поиск Tavily + компактный ответ со списком источников."""
    if not TAVILY_API_KEY:
        # если ключа нет — мягко откатываемся к оффлайн-ответу
        return await answer_via_openai(prompt)

    try:
        from tavily import TavilyClient  # требует tavily-python
        tv = TavilyClient(TAVILY_API_KEY)

        data = tv.search(
            query=prompt,
            search_depth="advanced",
            include_answer=True,
            max_results=5,
        )

        # может вернуться пусто — отдаем оффлайн-ответ
        if not data or not data.get("results"):
            return await answer_via_openai(prompt)

        ans = (data.get("answer") or "").strip()
        sources = build_sources_block(data.get("results", []), limit=5)

        # Если краткого ответа нет — попросим OpenAI сжать сниппеты.
        if not ans:
            snippets = "\n\n".join(
                f"{i+1}) {r.get('title','')}: {r.get('content','')[:500]}"
                for i, r in enumerate(data.get("results", []))
            )
            ans = await answer_via_openai(
                f"Суммируй по-русски, коротко и по фактам, с учётом источников ниже.\n\nВопрос: {prompt}\n\nИсточники:\n{snippets}"
            )

        return f"{ans}\n\n{sources}" if sources else ans

    except Exception as e:
        log.exception("Tavily error: %s", e)
        return await answer_via_openai(prompt)

# -------------------- HANDLERS --------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Пытаемся показать баннер, если указан
    if BANNER_URL:
        try:
            await update.effective_message.reply_photo(BANNER_URL)
        except Exception as e:
            log.warning("Banner send failed: %s", e)

    greet = (
        "Привет! Я готов. Напиши любой вопрос.\n\n"
        "Подсказки:\n"
        "• Могу искать в интернете: просто спроси «что такое…», «найди…», «новости…» и т.д.\n"
        "• Примеры: «Какая погода в Москве?», «Найди учебник алгебры 11 класс (официальные источники)», "
        "«Кто такой Ньютон?», «Курс биткоина»."
    )
    await update.effective_message.reply_text(greet)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    # если нет OpenAI ключа — сразу выходим
    if not OPENAI_API_KEY:
        await update.message.reply_text("OPENAI_API_KEY не задан. Сообщи админу.")
        return

    use_web = wants_web(text)
    if use_web:
        answer = await answer_via_web(text)
    else:
        answer = await answer_via_openai(text)

    await update.message.reply_text(answer)

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
