# -*- coding: utf-8 -*-
"""
GPT5PRO Telegram Bot
- Умные ответы: локально или с веб-поиском (Tavily) по необходимости
- Надёжный анализ изображений (OpenAI Vision) — без проблем с invalid_image_url
- Webhook-режим для Render
"""

import os
import re
import base64
import mimetypes
import logging
from typing import List, Dict, Any

import httpx
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)

# -------------------- LOGGING --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt-bot")

# -------------------- ENV --------------------
BOT_TOKEN       = os.environ.get("BOT_TOKEN", "").strip()
PUBLIC_URL      = os.environ.get("PUBLIC_URL", "").strip()   # https://<subdomain>.onrender.com
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL    = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
VISION_MODEL    = os.environ.get("VISION_MODEL", OPENAI_MODEL).strip()
WEBHOOK_SECRET  = os.environ.get("WEBHOOK_SECRET", "").strip()
BANNER_URL      = os.environ.get("BANNER_URL", "").strip()   # например: https://.../assets/IMG_3451.jpeg
TAVILY_API_KEY  = os.environ.get("TAVILY_API_KEY", "").strip()
PORT            = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")

# -------------------- OPENAI CLIENT --------------------
from openai import OpenAI
oa_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

# ---------- эвристика: нужно ли идти в веб-поиск ----------
_NEWSY = (
    r"\b(сейчас|сегодня|вчера|завтра|только что|актуальн|последн(ие|яя)|итоги|новост|апдейт|обновлен)\b"
)
_QUESY = (
    r"\b(когда|где|кто|что такое|почему|как (?:получить|сделать|настроить)|найди|посмотри|узнай|сколько|курс|цена|стоимость)\b"
)
_TOPICS_FORCE_WEB = (
    r"\b(погода|курс|биткоин|доллар|евро|акци(я|и)|индекс|тариф|расписани|мероприяти|релиз|выходит|выйдет|дата выхода|E3|GTA|Rockstar|мировой|матч|score|ваканси|самолет|рейс)\b"
)

def need_browse(q: str) -> bool:
    ql = q.lower().strip()
    # Явные команды поиска
    if re.search(_QUESY, ql):
        return True
    # Темы, которые почти всегда требуют онлайна
    if re.search(_TOPICS_FORCE_WEB, ql):
        return True
    # Новостная/временная лексика
    if re.search(_NEWSY, ql):
        return True
    # Очень длинный или фактологический вопрос
    if len(ql) > 160 and ("http" not in ql):
        return True
    return False

def is_smalltalk(q: str) -> bool:
    ql = q.lower().strip()
    return bool(re.fullmatch(r"(пр(иве)?т|здравств(уй|уйте)|добрый (день|вечер|утро)|как дела\??|спасибо|ок|пока)", ql))


# ---------- Tavily ----------
async def tavily_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Возвращает dict вида:
    {
      "answer": str|None,
      "results": [ { "title":..., "url":..., "content":... }, ... ]
    }
    """
    if not TAVILY_API_KEY:
        return {"answer": None, "results": []}

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_answer": True,
        "include_images": False,
        "include_domains": [],
        "exclude_domains": [],
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post("https://api.tavily.com/search", json=payload)
            r.raise_for_status()
            data = r.json()
            # Нормализуем
            results = data.get("results") or data.get("results_list") or []
            norm = []
            for it in results:
                norm.append({
                    "title": it.get("title") or "",
                    "url": it.get("url") or it.get("url_link") or "",
                    "content": it.get("content") or it.get("snippet") or "",
                })
            return {"answer": data.get("answer"), "results": norm}
    except Exception as e:
        log.exception("Tavily error: %s", e)
        return {"answer": None, "results": []}

def format_sources(results: List[Dict[str, str]], limit: int = 6) -> str:
    if not results:
        return ""
    lines = []
    for i, r in enumerate(results[:limit], 1):
        url = (r.get("url") or "").strip()
        title = (r.get("title") or url or "Источник").strip()
        if not url:
            continue
        lines.append(f"[{i}] {title} — {url}")
    return "\n".join(lines)


# ---------- Внутренний вызов OpenAI без веба ----------
async def llm_answer_local(prompt: str) -> str:
    if not oa_client:
        return "OPENAI_API_KEY не задан. Сообщи админу."

    sys = (
        "Ты дружелюбный и лаконичный ассистент. Отвечай по делу, "
        "можешь задавать уточняющие вопросы. Если вопрос приветственный — поприветствуй и предложи помощь."
    )
    try:
        resp = oa_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
            max_tokens=600,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("OpenAI local error: %s", e)
        return "Не удалось получить ответ от модели. Попробуй ещё раз позже."


# ---------- Комбинированный ответ: веб-поиск + анализ ----------
async def llm_answer_with_browse(query: str) -> str:
    # 1) Поиск
    search = await tavily_search(query, max_results=6)
    sources = search.get("results", [])
    fused_context = "\n\n".join(
        f"Источник {i+1}: {s.get('title','')}\nURL: {s.get('url','')}\nСодержание: {s.get('content','')}"
        for i, s in enumerate(sources)
    )[:12000]  # подрежем на всякий

    # 2) Анализ в LLM
    if not oa_client:
        # Без ключа хотя бы вернём ссылки
        src = format_sources(sources)
        return f"Вот, что нашёл:\n{src if src else 'Источники не найдены.'}"

    sys = (
        "Ты аналитик-исследователь. Используй предоставленные сниппеты как основное основание ответа. "
        "Дай краткий, точный вывод и, если уместно, укажи цифры/даты. "
        "Если есть противоречия — явно укажи это. Не выдумывай фактов."
    )
    user = (
        f"Вопрос пользователя:\n{query}\n\n"
        f"Материалы из поиска:\n{fused_context if fused_context else 'Нет результатов'}\n\n"
        "Сформируй ответ по сути. В конце не вставляй литеральных [1], [2]; ссылки я добавлю отдельно."
    )
    try:
        resp = oa_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
            temperature=0.3,
            max_tokens=700,
        )
        answer = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("OpenAI browse error: %s", e)
        answer = "Не удалось проанализировать результаты поиска. Попробуй уточнить запрос."

    src_block = format_sources(sources)
    if src_block:
        answer = f"{answer}\n\nСсылки:\n{src_block}"
    return answer


# -------------------- ВИЗУАЛ (ФОТО/ДОКУМЕНТ-ИЗОБРАЖЕНИЕ) --------------------

async def _tg_get_file_url(bot, file_id: str) -> str:
    """Возвращает ПОЛНЫЙ корректный URL файла Telegram (без ручного склеивания)."""
    f = await bot.get_file(file_id)
    # telegram.ext.File имеет поле .file_path — это уже полный https-URL
    return f.file_path

async def _download_bytes(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content

def _to_data_url(raw: bytes, mime: str = "image/jpeg") -> str:
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    try:
        if not OPENAI_API_KEY:
            await msg.reply_text("OPENAI_API_KEY не задан. Сообщи админу.")
            return

        # Берём самую большую копию
        file_id = msg.photo[-1].file_id
        file_url = await _tg_get_file_url(context.bot, file_id)

        raw = await _download_bytes(file_url)
        data_url = _to_data_url(raw, "image/jpeg")

        user_prompt = (msg.caption or "Опиши изображение и вытащи важные факты.").strip()
        resp = oa_client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {"role": "system", "content": "Ты кратко и по делу описываешь изображение и извлекаешь факты."},
                {"role": "user", "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]}
            ],
            temperature=0.2,
            max_tokens=700,
        )
        ans = (resp.choices[0].message.content or "").strip()
        await msg.reply_text(ans)
    except Exception as e:
        log.exception("Vision error: %s", e)
        await msg.reply_text("Не удалось проанализировать изображение. Попробуй ещё раз или пришли другой файл.")

async def on_document_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.effective_message.document
    if not doc or not (doc.mime_type or "").startswith("image/"):
        return
    try:
        if not OPENAI_API_KEY:
            await update.effective_message.reply_text("OPENAI_API_KEY не задан. Сообщи админу.")
            return

        file_url = await _tg_get_file_url(context.bot, doc.file_id)
        mime = doc.mime_type or mimetypes.guess_type(doc.file_name or "")[0] or "image/jpeg"
        raw = await _download_bytes(file_url)
        data_url = _to_data_url(raw, mime)

        user_prompt = (update.effective_message.caption or "Опиши изображение и вытащи важные факты.").strip()
        resp = oa_client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {"role": "system", "content": "Ты кратко и по делу описываешь изображение и извлекаешь факты."},
                {"role": "user", "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]}
            ],
            temperature=0.2,
            max_tokens=700,
        )
        ans = (resp.choices[0].message.content or "").strip()
        await update.effective_message.reply_text(ans)
    except Exception as e:
        log.exception("Vision(doc) error: %s", e)
        await update.effective_message.reply_text("Не удалось проанализировать изображение. Попробуй другой файл.")


# -------------------- ТЕКСТОВЫЕ ХЕНДЛЕРЫ --------------------

START_GREETING = (
    "Привет! Я готов. Напиши любой вопрос.\n\n"
    "Подсказки:\n"
    "• Я ищу свежую информацию в интернете и даю ответ со ссылками при необходимости.\n"
    "• Простые фразы («привет», «спасибо») — отвечаю сразу, без поиска.\n"
    "• Примеры: «Дата выхода GTA 6?», «Курс биткоина сейчас и прогноз», "
    "«Найди учебник алгебры 11 класс (официальные источники)», «Новости по ...», «Кто такой ...?»."
)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Пытаемся отправить баннер, если указан
    if BANNER_URL:
        try:
            await update.effective_message.reply_photo(BANNER_URL)
        except Exception:  # не мешаем старту, если картинка недоступна
            pass
    await update.effective_message.reply_text(START_GREETING)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if not OPENAI_API_KEY:
        await update.message.reply_text("OPENAI_API_KEY не задан. Сообщи админу.")
        return

    # 1) болталка — без веба
    if is_smalltalk(text):
        reply = await llm_answer_local(text)
        await update.message.reply_text(reply)
        return

    # 2) решаем: нужен ли веб
    if need_browse(text):
        reply = await llm_answer_with_browse(text)
    else:
        reply = await llm_answer_local(text)

    await update.message.reply_text(reply)


# -------------------- BOOTSTRAP --------------------
def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))

    # Фото как медиа
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    # Изображение, присланное как документ
    app.add_handler(MessageHandler(filters.Document.IMAGE, on_document_image))

    # Обычный текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


def run_webhook(app):
    # уникальный путь (чтоб никто случайно не дергал)
    url_path = f"webhook/{BOT_TOKEN}"
    webhook_url = f"{PUBLIC_URL.rstrip('/')}/{url_path}"

    log.info("Starting webhook on 0.0.0.0:%s  ->  %s", PORT, webhook_url)
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=url_path,
        webhook_url=webhook_url,
        secret_token=WEBHOOK_SECRET or None,   # Telegram header X-Telegram-Bot-Api-Secret-Token
        drop_pending_updates=True,
    )


def main():
    app = build_app()
    run_webhook(app)


if __name__ == "__main__":
    main()
