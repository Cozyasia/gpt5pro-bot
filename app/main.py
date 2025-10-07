import asyncio
import logging
import os
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram import Update
from app.config import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот запущен")

def build_app():
    # ВАЖНО: отключаем Updater, он нужен только для polling
    app = ApplicationBuilder().token(settings.BOT_TOKEN).updater(None).build()
    app.add_handler(CommandHandler("start", start))
    return app

async def run():
    app = build_app()

    webhook_url = f"{settings.PUBLIC_URL.rstrip('/')}/{settings.WEBHOOK_SECRET}"
    port = int(os.getenv("PORT", settings.PORT))

    # выставим вебхук явно (повторный вызов — ок)
    await app.bot.set_webhook(url=webhook_url, secret_token=settings.WEBHOOK_SECRET)

    await app.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url=webhook_url,
        secret_token=settings.WEBHOOK_SECRET,
    )

def main():
    asyncio.run(run())

if __name__ == "__main__":
    main()
