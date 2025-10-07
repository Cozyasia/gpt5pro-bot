from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from app.config import settings

async def cmd_start(update, context):
    await update.message.reply_text("Бот работает ✅")

async def echo(update, context):
    await update.message.reply_text(update.message.text)

def build_app():
    app = ApplicationBuilder().token(settings.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    return app

def main():
    application = build_app()

    # PUBLIC_URL из pydantic — это объект Url → приводим к строке
    public_url = str(settings.PUBLIC_URL).rstrip('/')
    webhook_url = f"{public_url}/{settings.WEBHOOK_SECRET}"

    # ВАЖНО: run_webhook — синхронный и блокирующий. НЕ вызываем через asyncio.run!
    application.run_webhook(
        listen="0.0.0.0",
        port=settings.PORT,
        webhook_url=webhook_url,
        secret_token=settings.WEBHOOK_SECRET,
    )

if __name__ == "__main__":
    main()
