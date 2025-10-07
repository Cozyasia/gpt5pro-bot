from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from app.config import settings

async def start(update, context):
    await update.message.reply_text("Бот на Render запущен ✅")

async def echo(update, context):
    await update.message.reply_text(update.message.text)

def build_app():
    app = ApplicationBuilder().token(settings.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    return app

def main():
    app = build_app()
    webhook_url = f"{settings.PUBLIC_URL}/{settings.WEBHOOK_SECRET}"
    # ВАЖНО: без await — метод блокирующий и сам управляет loop.
    app.run_webhook(
        listen="0.0.0.0",
        port=settings.PORT,            # Render передаст свой $PORT
        webhook_url=webhook_url,
    )

if __name__ == "__main__":
    main()
