# -*- coding: utf-8 -*-
import os
import logging
from typing import List, Tuple

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)

# ---- LOGGING ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("gpt5pro-bot")

# ---- ENV ----
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "").strip()
PUBLIC_URL     = os.environ.get("PUBLIC_URL", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL   = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
BANNER_URL     = os.environ.get("BANNER_URL", "").strip()
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()
ALWAYS_BROWSE  = os.environ.get("ALWAYS_BROWSE", "1").lower() not in ("0","false","no")
PORT           = int(os.environ.get("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is required")
if not PUBLIC_URL or not PUBLIC_URL.startswith("http"):
    raise RuntimeError("ENV PUBLIC_URL must look like https://xxx.onrender.com")

# ---- OPENAI ----
from openai import OpenAI
oa_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ---- Tavily ----
try:
    from tavily import TavilyClient
    tv_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None
except Exception as e:
    tv_client = None
    log.warning("Tavily import failed: %s", e)


# ---------- helpers ----------
def _clip(text: str, limit: int = 3600) -> str:
    """telegram ~4096; оставим запас под ссылки"""
    if text and len(text) > limit:
        return text[:limit-20].rstrip() + "…"
    return text

def _to_links(results: List[dict]) -> Tuple[str, List[str]]:
    """Возвращает текстовый список ссылок и список URL для приоритезации."""
    lines, urls = [], []
    for i, r in enumerate(results[:6], start=1):
        url = r.get("url") or r.get("source") or ""
        title = (r.get("title") or "").strip() or url
        urls.append(url)
        lines.append(f"[{i}] {title} — {url}")
    return "\n".join(lines), urls


async def _browse_then_answer(query: str) -> str:
    """
    1) Ищем Tavily (всегда, если включен ALWAYS_BROWSE)
    2) Суммаризуем источники в OpenAI
    """
    if not tv_client:
        return ""  # пусть сработает офлайн-фолбэк

    results = []
    try:
        # advanced = лучше для свежести/точности
        sr = tv_client.search(
            query=query,
            search_depth="advanced",
            max_results=6,
            include_answer=False,
        )
        results = sr.get("results") or []
    except Exception as e:
        log.exception("Tavily error: %s", e)
        results = []

    if not results:
        return ""

    links_text, urls = _to_links(results)

    # Собираем «корпус» фактов
    chunks = []
    for idx, r in enumerate(results[:6], start=1):
        title = r.get("title") or ""
        url = r.get("url") or r.get("source") or ""
        content = r.get("content") or r.get("snippet") or ""
        chunks.append(f"[{idx}] {title}\nURL: {url}\n{content}")

    research_block = "\n\n".join(_clip(c, 1200) for c in chunks)

    system = (
        "Ты аналитичный ассистент. ДЕЛАЙ ВЫВОДЫ ТОЛЬКО из предоставленных источников. "
        "Если источники противоречат друг другу — укажи это и отметь степень уверенности. "
        "Будь краток и точен, отвечай на русском. Сначала дай прямой ответ на запрос, "
        "затем добавь раздел «Ссылки» со списком вида [1] Тайтл — URL."
    )

    user = (
        f"Запрос пользователя: {query}\n\n"
        f"ИСТОЧНИКИ (выдержки):\n{research_block}\n\n"
        "Сформируй итоговый ответ (3–8 предложений максимум). "
        "Если запрос о датах/суммах/курсах/сроках — приводи актуальные числа из источников. "
        "Если нет однозначной информации — честно укажи это."
    )

    try:
        resp = oa_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.2,
        )
        summary = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("OpenAI summarize error: %s", e)
        summary = ""

    if not summary:
        return ""

    return _clip(summary) + "\n\n" + links_text


# ---------- handlers ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # баннер (если задан)
    if BANNER_URL:
        try:
            await update.effective_message.reply_photo(BANNER_URL)
        except Exception as e:
            log.warning("Banner send failed: %s", e)

    greet = (
        "Привет! Я готов. Напиши любой вопрос.\n\n"
        "Подсказки:\n"
        "• Я всегда ищу свежую информацию в интернете и даю ответ с ссылками.\n"
        "• Примеры: «Дата выхода GTA 6?», «Курс биткоина сейчас и прогноз», "
        "«Найди учебник алгебры 11 класс (официальные источники)», "
        "«Новости по …», «Кто такой …?» и т.д."
    )
    await update.effective_message.reply_text(greet)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = (update.message.text or "").strip()

    # 1) Всегда пробуем веб-поиск (если включен флаг)
    answer = ""
    if ALWAYS_BROWSE:
        answer = await _browse_then_answer(q)

    # 2) Если веб-поиск не дал результата — офлайн-ответ (как фолбэк)
    if not answer:
        if not oa_client:
            await update.message.reply_text("Не удалось получить ответ. Попробуй ещё раз.")
            return
        try:
            sys_prompt = (
                "Ты дружелюбный и лаконичный ассистент. "
                "Если тебя спрашивают о свежих новостях/датах/ценах — скажи, что не уверен без доступа к сети."
            )
            resp = oa_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": q},
                ],
                temperature=0.6,
            )
            answer = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            log.exception("OpenAI offline error: %s", e)
            answer = "Не удалось получить ответ. Попробуй ещё раз."

    await update.message.reply_text(_clip(answer))


# ---------- bootstrap ----------
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
