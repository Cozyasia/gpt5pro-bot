import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from .config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Webhook-бот запущен ✅")

def main():
    app = ApplicationBuilder().token(settings.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    # Полный URL для вебхука: https://<host>/<секретный-путь>
    base = settings.PUBLIC_URL.rstrip("/")
    webhook_url = f"{base}/{settings.WEBHOOK_SECRET}"

    # ВАЖНО: run_webhook сам поднимет aiohttp-сервер и выставит вебхук
    app.run_webhook(
        listen="0.0.0.0",
        port=settings.PORT,
        webhook_url=webhook_url,
        secret_token=settings.WEBHOOK_SECRET,    # валидация X-Telegram-Bot-Api-Secret-Token
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )

if __name__ == "__main__":
    main()
