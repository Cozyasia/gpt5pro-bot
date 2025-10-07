import asyncio
import logging
import os

from telegram.ext import Application, CommandHandler, MessageHandler, filters
from .config import settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

async def start(update, context):
    await update.message.reply_text("Бот запущен ✅")

async def echo(update, context):
    if update.message and update.message.text:
        await update.message.reply_text(update.message.text)

def build_application() -> Application:
    app = Application.builder().token(settings.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    return app

async def run():
    application = build_application()

    public = settings.PUBLIC_URL.rstrip("/")
    path = settings.WEBHOOK_SECRET         # это будет URL-путь
    port = int(os.environ.get("PORT", "8080"))  # Render задаёт PORT автоматически

    # одна команда делает всё: регистрирует вебхук и запускает aiohttp-сервер
    await application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=path,                                  # важно: url_path (НЕ webhook_path)
        webhook_url=f"{public}/{path}",
    )

def main():
    asyncio.run(run())

if __name__ == "__main__":
    main()
