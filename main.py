# -*- coding: utf-8 -*-
import os
import logging
from typing import List, Dict

from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder,
    CommandHandler, MessageHandler, ContextTypes, filters
)

# ------------ LOGGING ------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-free-bot")

# ------------ ENV (строго под твои ключи) ------------
BOT_TOKEN      = os.getenv("BOT_TOKEN", "").strip()
PUBLIC_URL     = os.getenv("PUBLIC_URL", "").strip()          # https://gpt5pro-bot.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()      # 9b12...
PORT           = int(os.getenv("PORT", "10000"))              # Render подставит сам

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")
if not PUBLIC_URL.startswith("http"):
    raise RuntimeError("PUBLIC_URL must look like https://<your-app>.onrender.com")

# ------------ OpenAI ------------
def build_openai():
    if not OPENAI_API_KEY:
        return None
    from openai import OpenAI
    return OpenAI(api_key=OPENAI_API_KEY, timeout=60)

OAI = build_openai()

# Небольшая «память» диалога на последние 8 сообщений туда-сюда
HISTORY_TURNS = 8
def push_history(context: ContextTypes.DEFAULT_TYPE, role: str, content: str):
    hist: List[Dict[str, str]] = context.user_data.get("history", [])
    hist.append({"role": role, "content": content})
    if len(hist) > 2 * HISTORY_TURNS:
        hist = hist[-2 * HISTORY_TURNS :]
    context.user_data["history"] = hist

def build_messages(context: ContextTypes.DEFAULT_TYPE, user_text: str):
    sys_prompt = (
        "Ты универсальный помощник. Отвечай ясно, кратко и дружелюбно. "
        "Структурируй длинные ответы списками, давай пошаговые инструкции, когда это уместно."
    )
    msgs: List[Dict[str, str]] = [{"role": "system", "content": sys_prompt}]
    msgs += context.user_data.get("history", [])
    msgs.append({"role": "user", "content": user_text})
    return msgs

TELEGRAM_MAX = 4096
async def send_long(update: Update, text: str):
    while text:
        chunk = text[:TELEGRAM_MAX]
        await update.effective_message.reply_text(chunk)
        text = text[TELEGRAM_MAX:]

# ------------ Handlers ------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Привет! Я GPT-бот. Пиши любой вопрос.\n\n"
        "/reset — очистить контекст\n"
        "/model — показать модель"
    )

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.effective_message.reply_text("Контекст очищен.")

async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(f"Модель: {OPENAI_MODEL}")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = (update.message.text or "").strip()
    if not user_text:
        return
    if OAI is None:
        await update.message.reply_text("OPENAI_API_KEY не задан — не могу ответить.")
        return
    try:
        push_history(context, "user", user_text)
        resp = OAI.chat.completions.create(
            model=OPENAI_MODEL,
            messages=build_messages(context, user_text),
            temperature=0.6,
        )
        answer = (
