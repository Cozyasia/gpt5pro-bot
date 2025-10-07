import asyncio
import logging
import os

from telegram import Update
from telegram.ext import ApplicationBuilder, Application, CommandHandler, ContextTypes
from .config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bot")

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👍 Bot is alive!")

def build_app() -> Application:
    app = ApplicationBuilder().token(settings.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    return app

async def run():
    app = build_app()

    port = int(os.environ.get("PORT", "8080"))   # Render подставит PORT
    path = settings.WEBHOOK_SECRET.strip("/")    # путь = секрет
    base = settings.PUBLIC_URL.rstrip("/")       # базовый URL без '/'

    webhook_url = f"{base}/{path}"
    log.info("Starting webhook on %s", webhook_url)

    await app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=path,                 # <-- ВАЖНО: url_path (не webhook_path)
        webhook_url=webhook_url,
        secret_token=settings.WEBHOOK_SECRET,
    )

def main():
    asyncio.run(run())

if __name__ == "__main__":
    main()
