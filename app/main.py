import asyncio
import logging
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update
from .config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("gpt5pro-bot")

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот жив. /start")

def build_ptb_app() -> Application:
    app = Application.builder().token(settings.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    return app

async def run():
    application = build_ptb_app()

    # Внешний URL и путь вебхука
    secret_path = settings.WEBHOOK_SECRET
    public_base = str(settings.PUBLIC_URL).rstrip("/")   # ВАЖНО: str()
    webhook_url = f"{public_base}/{secret_path}"

    log.info("Set webhook: %s", webhook_url)
    await application.bot.set_webhook(
        url=webhook_url,
        secret_token=settings.WEBHOOK_SECRET,
    )

    # Запуск встроенного веб-сервера PTB
    await application.run_webhook(
        listen="0.0.0.0",
        port=settings.PORT,                     # Render передаёт PORT в env
        webhook_path=f"/{secret_path}",
        secret_token=settings.WEBHOOK_SECRET,
    )

def main():
    asyncio.run(run())

if __name__ == "__main__":
    main()
