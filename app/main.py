from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from .config import BOT_TOKEN, PUBLIC_URL, WEBHOOK_SECRET, PORT

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен ✅")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    # ВАЖНО: без asyncio.run() — этот метод сам блокирующий
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_SECRET,                     # путь для входящих запросов
        webhook_url=f"{PUBLIC_URL}/{WEBHOOK_SECRET}" # публичный URL для setWebhook
    )

if __name__ == "__main__":
    main()
