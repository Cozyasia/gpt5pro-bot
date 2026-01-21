# main.py
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from engine import sora2, suno, midjourney

TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot online. Commands: /sora /suno /mj")

async def text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text or ""
    if t.startswith("/sora"):
        res = await sora2(t.replace("/sora","").strip())
        await update.message.reply_text(str(res))
    elif t.startswith("/suno"):
        res = await suno(t.replace("/suno","").strip())
        await update.message.reply_text(str(res))
    elif t.startswith("/mj"):
        res = await midjourney(t.replace("/mj","").strip())
        await update.message.reply_text(str(res))
    else:
        await update.message.reply_text("Use /sora /suno /mj")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT","10000")),
        webhook_url=f"{WEBHOOK_BASE}/webhook"
    )

if __name__ == "__main__":
    main()
