
# -*- coding: utf-8 -*-
import os
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from engine import run_engine, ENGINE_HELP

logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_TOKEN")

DEFAULT_STATE = {"mode": None, "engine": None, "last_photo": None}

def ensure(ctx):
    for k,v in DEFAULT_STATE.items():
        ctx.user_data.setdefault(k,v)

def menu():
    return ReplyKeyboardMarkup([["🎓 Учёба","💼 Работа"],["🔥 Развлечения","🧠 Движки"]],resize_keyboard=True)

def engines():
    return ReplyKeyboardMarkup([["Runway","Luma"],["Sora","Kling"],["⬅ Назад"]],resize_keyboard=True)

async def start(u:Update,c:ContextTypes.DEFAULT_TYPE):
    ensure(c)
    await u.message.reply_text("Выберите режим.",reply_markup=menu())

async def on_text(u:Update,c:ContextTypes.DEFAULT_TYPE):
    ensure(c)
    t=u.message.text
    if t=="⬅ Назад":
        c.user_data.update(DEFAULT_STATE)
        await u.message.reply_text("Меню.",reply_markup=menu()); return
    if t in ("🎓 Учёба","💼 Работа","🔥 Развлечения"):
        c.user_data["mode"]=t
        await u.message.reply_text(f"{t} выбран. Напишите запрос.",reply_markup=ReplyKeyboardRemove()); return
    if t=="🧠 Движки":
        await u.message.reply_text("Выберите движок.",reply_markup=engines()); return
    if t in ("Runway","Luma","Sora","Kling"):
        c.user_data["engine"]=t.lower()
        await u.message.reply_text(f"Движок {t}. {ENGINE_HELP[t.lower()]}"); return
    if c.user_data.get("engine"):
        res=await run_engine(c.user_data["engine"],"text2video",t,c.user_data.get("last_photo"))
        await u.message.reply_text(res); return
    await u.message.reply_text("Сначала выберите режим или движок.",reply_markup=menu())

async def on_photo(u:Update,c:ContextTypes.DEFAULT_TYPE):
    ensure(c)
    p=u.message.photo[-1]
    f=await p.get_file()
    c.user_data["last_photo"]={"file_id":p.file_id,"url":f.file_path}
    await u.message.reply_text("Фото сохранено. Выберите движок и нажмите «✨ Оживить».")

def main():
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.PHOTO,on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,on_text))
    app.run_polling()

if __name__=="__main__":
    main()
