# web_api.py
# Запуск: uvicorn web_api:app --host 0.0.0.0 --port $PORT
import os, re, base64, logging
from io import BytesIO

import httpx
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gpt5pro-webapi")

# ==== ENV ====
OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL     = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "").strip()
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "").strip()

from openai import OpenAI
oai = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Tavily
try:
    if TAVILY_API_KEY:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
    else:
        tavily = None
except Exception:
    tavily = None

# ==== Heuristics ====
_SMALLTALK_RE = re.compile(r"^(привет|здравствуй|добрый\s*(день|вечер|утро)|hi|hello|спасибо|пока)\b", re.I)
_NEWSY_RE = re.compile(r"(когда|дата|выйдет|релиз|новост|курс|цена|прогноз|найди|ссылка|официал|адрес|телефон|погода|штраф|закон|расписани|update)", re.I)

def is_smalltalk(t: str) -> bool:
    return bool(_SMALLTALK_RE.search(t.strip()))

def should_browse(t: str) -> bool:
    t = t.strip()
    if is_smalltalk(t): return False
    return ("?" in t) or bool(_NEWSY_RE.search(t)) or len(t) > 80

def sniff_image_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8"): return "image/jpeg"
    if data.startswith(b"\x89PNG"):   return "image/png"
    if data[:4] == b"RIFF" and b"WEBP" in data[:16]: return "image/webp"
    return "image/jpeg"

def tavily_search(query: str, max_results: int = 5):
    if not tavily:
        return None, []
    try:
        res = tavily.search(
            query=query, search_depth="advanced",
            max_results=max_results, include_answer=True, include_raw_content=False
        )
        return res.get("answer") or "", res.get("results") or []
    except Exception as e:
        log.exception("Tavily error: %s", e)
        return None, []

SYSTEM_PROMPT = (
    "Ты дружелюбный и лаконичный ассистент на русском. "
    "Отвечай по сути, структурируй списками/шагами, не выдумывай факты. "
    "Если ссылаешься на источники — в конце дай короткий список ссылок."
)
VISION_SYSTEM_PROMPT = (
    "Ты чётко описываешь содержимое изображений: объекты, текст, схемы, графики. "
    "Не идентифицируй личности людей и не пиши имена, если они не напечатаны на изображении."
)

async def answer_text(user_text: str, web_ctx: str = "") -> str:
    if not oai:
        return "Нет доступа к модели. Проверьте ключи/лимиты."
    msgs = [{"role":"system","content":SYSTEM_PROMPT}]
    if web_ctx:
        msgs.append({"role":"system","content":f"Контекст из веб-поиска:\n{web_ctx}"})
    msgs.append({"role":"user","content":user_text})
    try:
        r = oai.chat.completions.create(model=OPENAI_MODEL, messages=msgs, temperature=0.6)
        return (r.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("OpenAI chat error: %s", e)
        return "Не удалось получить ответ от модели (лимит/ключ). Попробуйте позже."

async def answer_vision(user_text: str, img_bytes: bytes) -> str:
    if not oai:
        return "Нет доступа к модели. Проверьте ключи/лимиты."
    mime = sniff_image_mime(img_bytes)
    b64 = base64.b64encode(img_bytes).decode("ascii")
    try:
        r = oai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role":"system","content":VISION_SYSTEM_PROMPT},
                {"role":"user","content":[
                    {"type":"text","text": user_text or "Опиши, что на изображении и какой там текст."},
                    {"type":"image_url","image_url":{"url": f"data:{mime};base64,{b64}"}}
                ]}
            ],
            temperature=0.4
        )
        return (r.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("OpenAI vision error: %s", e)
        return "Не удалось проанализировать изображение. Попробуйте другой файл."

async def transcribe(data: bytes, filename_hint: str) -> str:
    # 1) Deepgram
    if DEEPGRAM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                params = {"model":"nova-2","language":"ru","smart_format":"true","punctuate":"true"}
                headers = {
                    "Authorization": f"Token {DEEPGRAM_API_KEY}",
                    "Content-Type": "application/octet-stream",
                }
                r = await client.post("https://api.deepgram.com/v1/listen", params=params, headers=headers, content=data)
                r.raise_for_status()
                dg = r.json()
                text = (dg.get("results",{}).get("channels",[{}])[0].get("alternatives",[{}])[0].get("transcript","") or "").strip()
                if text: return text
        except Exception as e:
            log.exception("Deepgram STT error: %s", e)
    # 2) Whisper fallback
    if oai:
        try:
            buf = BytesIO(data); buf.seek(0); setattr(buf, "name", filename_hint or "audio.wav")
            tr = oai.audio.transcriptions.create(model=os.environ.get("OPENAI_TRANSCRIBE_MODEL","whisper-1"), file=buf)
            return (tr.text or "").strip()
        except Exception as e:
            log.exception("Whisper STT error: %s", e)
    return ""

# ==== FastAPI app ====
app = FastAPI(title="GPT-5 PRO Web API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

class ChatIn(BaseModel):
    message: str

@app.get("/health")
async def health(): return {"ok": True}

@app.post("/api/chat")
async def api_chat(payload: ChatIn):
    text = (payload.message or "").strip()
    sources = []
    web_ctx = ""
    if should_browse(text):
        ans, results = tavily_search(text, max_results=5)
        sources = results or []
        ctx = []
        if ans: ctx.append(f"Краткая сводка поиском: {ans}")
        for i, it in enumerate(sources, 1):
            ctx.append(f"[{i}] {it.get('title','')}: {it.get('url','')}")
        web_ctx = "\n".join(ctx)

    answer = await answer_text(text, web_ctx=web_ctx)
    return {"answer": answer, "sources": sources}

@app.post("/api/vision")
async def api_vision(message: str = Form(""), file: UploadFile = File(...)):
    data = await file.read()
    ans = await answer_vision(message, data)
    return {"answer": ans}

@app.post("/api/transcribe")
async def api_transcribe(file: UploadFile = File(...)):
    data = await file.read()
    text = await transcribe(data, file.filename or "audio.wav")
    return {"text": text}
