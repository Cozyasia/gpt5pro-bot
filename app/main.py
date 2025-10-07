# app/main.py
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from .config import settings  # или from config import settings, если без пакета

# --- handlers ---
async def start(update, context):
    await update.message.reply_text("Бот жив! ✨")

async def echo(update, context):
    await update.message.reply_text(update.message.text)

def build_app() -> Application:
    app = Application.builder().token(settings.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    return app

def main():
    app = build_app()
    # Вебхук: PTB сам создаст/поставит вебхук и запустит сервер
    app.run_webhook(
        listen="0.0.0.0",
        port=settings.PORT,  # Render подставит PORT из env
        url_path=settings.WEBHOOK_SECRET,
        webhook_url=f"{settings.PUBLIC_URL}/{settings.WEBHOOK_SECRET}",
    )

if __name__ == "__main__":
    main()
