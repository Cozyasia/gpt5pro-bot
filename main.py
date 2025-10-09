# -*- coding: utf-8 -*-
import os
import logging
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
PUBLIC_URL      = os.environ.get("PUBLIC_URL", "").strip()   # https://<subdomain>.onrender.com
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL    = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
WEBHOOK_SECRET  = os.environ.get("WEBHOOK_SECRET", "").strip()
BANNER_URL      = os.environ.get("BANNER_URL", "").strip()   # напр.: https://.../assets/IMG_3451.jpeg
TAVILY_API_KEY  = os.environ.get("TAVILY_API_KEY", "").strip()
PORT            = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")

# -------------------- UTILS: web search --------------------
def _should_search_web(s: str) -> bool:
    """Грубая эвристика: что-то явно «актуальное» -> пробуем веб-поиск."""
    s = (s or "").lower()
    triggers = [
        # RU
        "сегодня", "вчера", "сейчас", "новост", "погода", "курс",
        "котиров", "цена акций", "расписан", "матч", "играет", "рейс",
        "пробк", "трафик",
        # EN (на всякий)
        "today", "now", "current", "latest", "news", "weather",
        "price", "stock", "schedule", "traffic", "score"
    ]
    return any(t in s for t in triggers)

def search_web_answer(query: str) -> str | None:
    """Ищем через Tavily и формируем компактный ответ + 2-3 источника."""
    if not TAVILY_API_KEY:
        log.info("Tavily disabled: no TAVILY_API_KEY")
        return None
    try:
        from tavily import TavilyClient  # импорт внутри, чтобы не падать без пакета
        client = TavilyClient(api_key=TAVILY_API_KEY)
        res = client.search(
            query=query,
            max_results=5,
            include_answer=True,
        )
        answer = (res.get("answer") or "").strip()
        results = res.get("results") or []
        bullets = []
        for r in results[:3]:
            title = (r.get("title") or "").strip()
            url = (r.get("url") or "").strip()
            if title and url:
                bullets.append(f"• {title}\n{url}")
        tail = ("\n\n" + "\n".join(bullets)) if bullets else ""
        text = (answer + tail).strip()
        return text or None
    except Exception as e:
        log.error("Tavily search failed: %s", e)
        return None

# -------------------- HANDLERS --------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1) баннер, если указан
    if BANNER_URL:
        try:
            await update.effective_message.reply_photo(BANNER_URL)
        except Exception as e:
            log.warning("Failed to send BANNER_URL: %s", e)
    # 2) приветствие
    await update.effective_message.reply_text(
        "Привет! Я готов. Напиши любой вопрос."
    )

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    # Попытка веб-поиска для «живых» вопросов
    if _should_search_web(text):
        web = search_web_answer(text)
        if web:
            await update.message.reply_text(web, disable_web_page_preview=False)
            return

    if not OPENAI_API_KEY:
        await update.message.reply_text("OPENAI_API_KEY не задан. Сообщи админу.")
        return

    # Обычный ответ модели
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        sys_prompt = "Ты дружелюбный и лаконичный ассистент. Отвечай по сути."
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text},
            ],
            temperature=0.6,
        )
        answer = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("OpenAI error: %s", e)
        answer = "Не удалось получить ответ от модели. Попробуй еще раз позже."

    await update.message.reply_text(answer)

# -------------------- BOOTSTRAP --------------------
def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app

def run_webhook(app):
    # уникальный путь (чтоб никто случайно не дергал)
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
