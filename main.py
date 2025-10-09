# -*- coding: utf-8 -*-
import os
import re
import logging
from typing import List, Tuple

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
WEBHOOK_SECRET  = os.environ.get("WEBHOOK_SECRET", "").strip()
BANNER_URL      = os.environ.get("BANNER_URL", "").strip()
TAVILY_API_KEY  = os.environ.get("TAVILY_API_KEY", "").strip()
WEB_MODE        = os.environ.get("WEB_MODE", "always").strip().lower()   # always | auto | never
PORT            = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")

# -------------------- OPTIONAL: OPENAI client --------------------
from openai import OpenAI
_oai = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# -------------------- OPTIONAL: Tavily client -------------------
try:
    from tavily import TavilyClient
    _tv = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None
except Exception as e:
    log.warning("Tavily import failed: %s", e)
    _tv = None

# -------------------- UTILS --------------------
SEARCH_KEYWORDS = re.compile(
    r"(что такое|кто такой|когда|дата|новост|курс|сколько стоит|цена|прогноз|"
    r"релиз|выйдет|объясни события|итоги|статистик|как дела у|когда будет|"
    r"опубликован|запуск|release|price|wiki|изобрели|история|биограф|"
    r"закон|постановлен|регламент|инструкция|how to|why|when|where|what)",
    re.IGNORECASE
)

CREATIVE_KEYWORDS = re.compile(
    r"(напиши|сочини|переведи|перефразируй|придумай|сгенерируй|оформи|подбери|тон|"
    r"письмо|пост|статью|эссе|тз|бриф|слоган|скрипт|диалог|код(?!\s+пример)|"
    r"таблиц|презентац|резюме|summary|перескажи)",
    re.IGNORECASE
)

def need_web_search(q: str) -> bool:
    """Решаем, идти ли в веб."""
    if WEB_MODE == "never":
        return False
    if WEB_MODE == "always":
        # кроме явно креативных/генеративных задач
        return not bool(CREATIVE_KEYWORDS.search(q))
    # WEB_MODE == "auto"
    if CREATIVE_KEYWORDS.search(q):
        return False
    return bool(SEARCH_KEYWORDS.search(q)) or ("http" in q or "www" in q)

def tavily_search(query: str, max_results: int = 6) -> Tuple[str, List[dict]]:
    """Ищем в Tavily. Возвращаем (краткий ответ, список источников)."""
    if not _tv:
        return "", []
    try:
        resp = _tv.search(
            query=query,
            max_results=max_results,
            include_answer=True,
            include_raw_content=True,
            search_depth="advanced",
        )
        answer = (resp.get("answer") or "").strip()
        sources = resp.get("results") or []
        return answer, sources
    except Exception as e:
        log.exception("Tavily error: %s", e)
        return "", []

def format_sources(sources: List[dict], limit: int = 5) -> str:
    out = []
    for i, s in enumerate(sources[:limit], start=1):
        title = (s.get("title") or s.get("url") or "").strip()
        url = (s.get("url") or "").strip()
        if title and url:
            out.append(f"{i}) {title}\n{url}")
    return "\n".join(out)

def llm_answer(user_text: str, web_summary: str = "", sources: List[dict] = None) -> str:
    """Готовим ответ от модели. Если есть веб-данные — просим их учесть и дать итог + ссылки."""
    if not _oai:
        return "OPENAI_API_KEY не задан. Сообщи админу."

    sys_prompt = (
        "Ты аналитичный помощник. Если предоставлены источники/сводка — опирайся на них. "
        "Пиши по-русски, кратко по делу. Если факты зависят от времени — "
        "излагай как «на данный момент» и добавляй ссылки.\n"
        "Структура: короткий ответ, затем при необходимости маркированный список. "
        "Если источники переданы — в конце раздел «Источники»."
    )

    user_prompt = f"Вопрос пользователя: {user_text}"
    if web_summary:
        user_prompt += f"\n\nСводка из веб-поиска:\n{web_summary}"

    if sources:
        numbered = format_sources(sources)
        user_prompt += f"\n\nИсточники (нумерованные):\n{numbered}\n\n" \
                       f"Пожалуйста, используй эти источники при ответе."

    try:
        resp = _oai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("OpenAI error: %s", e)
        return "Не удалось получить ответ от модели. Попробуй ещё раз позже."

# -------------------- HANDLERS --------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Баннер (если хочешь показывать при /start)
    if BANNER_URL:
        try:
            await update.effective_message.reply_photo(BANNER_URL)
        except Exception as e:
            log.warning("Banner send failed: %s", e)

    text = (
        "Привет! Я готов. Напиши любой вопрос.\n\n"
        "Подсказки:\n"
        "• Могу искать в интернете: просто спроси «что такое…», «найди…», «новости…», «когда выйдет…» и т.д.\n"
        "• Примеры: «Какая погода в Москве?», «Найди учебник алгебры (официальные источники)», "
        "«Кто такой Ньютон?», «Дата выхода GTA 6»."
    )
    await update.effective_message.reply_text(text)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = (update.message.text or "").strip()

    use_web = need_web_search(q)
    web_summary = ""
    sources = []

    if use_web:
        # небольшой “перефраз” запроса, чтобы поиску легче:
        enriched_q = q
        # если есть явный объект (бренд, игра, компания) — чаще полезно добавить «официальный сайт»
        if re.search(r"(официальн|official|rockstar|gta|дат[аы]\s+выхода)", q, re.I):
            enriched_q += " официальный сайт"
        # ищем
        ans, srcs = tavily_search(enriched_q, max_results=6)
        web_summary = ans or ""   # краткая сводка Tavily
        sources = srcs or []

    answer = llm_answer(q, web_summary=web_summary, sources=sources)

    # Если не поискали (или Tavily дал пусто) и ответ выглядит «старым», а вопрос фактологический — сделаем fallback: короткий список ссылок
    if use_web and not web_summary and sources:
        answer += "\n\nИсточники:\n" + format_sources(sources)

    await update.message.reply_text(answer, disable_web_page_preview=False)

# -------------------- BOOTSTRAP --------------------
def build_app():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app

def run_webhook(app):
    url_path = f"webhook/{BOT_TOKEN}"
    webhook_url = f"{PUBLIC_URL.rstrip('/')}/{url_path}"

    log.info("Starting webhook on 0.0.0.0:%s  ->  %s", PORT, webhook_url)
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=url_path,
        webhook_url=webhook_url,
        secret_token=WEBHOOK_SECRET or None,
        drop_pending_updates=True,
    )

def main():
    app = build_app()
    run_webhook(app)

if __name__ == "__main__":
    main()
