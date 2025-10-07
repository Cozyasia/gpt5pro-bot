import os
import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)
from .config import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен ✅")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(update.message.text)

def build_app() -> Application:
    app = ApplicationBuilder().token(settings.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    return app

async def run():
    app = build_app()

    port = int(os.environ.get("PORT", settings.PORT))
    base_url = os.environ.get("RENDER_EXTERNAL_URL")  # Render сам выставляет, напр. https://gpt5pro-bot.onrender.com
    path = f"/webhook/{settings.BOT_TOKEN}"

    if base_url:  # клауд: веб-хук
        webhook_url = base_url + path
        log.info("Setting webhook to %s", webhook_url)
        await app.bot.set_webhook(url=webhook_url, secret_token=settings.WEBHOOK_SECRET)
        await app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=path.lstrip("/"),
            secret_token=settings.WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
    else:  # локально: поллинг (для разработки)
        log.info("Local run: polling")
        await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(run())
