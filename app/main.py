import asyncio
from aiohttp import web
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram import Update
from .config import settings

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот жив. /help — список команд.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Доступно: /start /help")

def build_app():
    application = ApplicationBuilder().token(settings.BOT_TOKEN).concurrent_updates(True).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))

    # healthcheck и корень
    async def health(_: web.Request):
        return web.Response(text="ok")
    async def root(_: web.Request):
        return web.Response(text="Telegram bot is running")

    application.web_app.add_routes([
        web.get("/", root),
        web.get("/healthz", health),
    ])
    return application

async def run():
    app = build_app()
    if settings.MODE == "webhook":
        # Настраиваем вебхук и запускаем встроенный aiohttp-сервер PTB
        await app.bot.set_webhook(url=settings.webhook_url, secret_token=settings.WEBHOOK_SECRET, drop_pending_updates=True)
        await app.initialize()
        await app.start()
        try:
            await app.updater.start_webhook(
                listen="0.0.0.0",
                port=settings.PORT,
                url_path=f"tg/{settings.WEBHOOK_SECRET}",
                webhook_url=settings.webhook_url,
                secret_token=settings.WEBHOOK_SECRET,
            )
            # держим процесс живым
            await asyncio.Event().wait()
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
    else:
        # Режим локальной отладки (polling) — только с ДРУГИМ токеном, чтобы не конфликтовать с продом!
        await app.bot.delete_webhook(True)
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    asyncio.run(run())
