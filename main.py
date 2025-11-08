# -*- coding: utf-8 -*-
"""
GPT5 PRO Telegram Bot
- python-telegram-bot==21.6
- openai>=1.51.0
Features:
• Positive image capabilities responses (text & voice)
• TTS with streaming and MP3 fallback
• STT for voice
• Photo quick actions: remove BG, replace BG, Outpaint, Animate (stub), Camera (stub), Storyboard
• /img generation, /plans with CryptoBot, /ver
"""
import os, sys, io, re, json, base64, sqlite3, asyncio, contextlib, uuid, logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

# Heavy imports only executed in runtime, not in this build environment
from PIL import Image, ImageDraw  # Pillow
import httpx

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
    InlineKeyboardButton, InputFile
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ===== Logging =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("gpt5pro-bot")

# ===== Version =====
VERSION_TAG = "gpt5pro-main 2025-11-08-16:45"

# ===== ENV =====
BOT_TOKEN        = os.getenv("BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
PUBLIC_URL       = os.getenv("PUBLIC_URL", "").strip()
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL     = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
CRYPTOBOT_TOKEN  = os.getenv("CRYPTOBOT_TOKEN", "").strip()
LUMA_API_KEY     = os.getenv("LUMA_API_KEY", "").strip()
RUNWAY_API_KEY   = os.getenv("RUNWAY_API_KEY", "").strip()

# ===== Minimal persistence =====
DB_PATH = os.getenv("BOT_DB", "bot.db")

def db_init() -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            voice_on INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            text TEXT,
            ts TEXT
        )
    """)
    con.commit(); con.close()

def db_user_get_or_create(user_id: int) -> Dict[str, Any]:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT user_id, voice_on FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO users(user_id, voice_on, created_at) VALUES(?,?,?)",
                    (user_id, 0, datetime.now(timezone.utc).isoformat()))
        con.commit()
        row = (user_id, 0)
    con.close()
    return {"user_id": row[0], "voice_on": int(row[1])}

def db_user_set_voice(user_id: int, on: bool) -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("UPDATE users SET voice_on=? WHERE user_id=?", (1 if on else 0, user_id))
    con.commit(); con.close()

def db_save_turn(user_id: int, role: str, text: str) -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT INTO history(user_id, role, text, ts) VALUES(?,?,?,?)",
                (user_id, role, text, datetime.now(timezone.utc).isoformat()))
    con.commit(); con.close()

db_init()

# ===== OpenAI Client Wrapper =====
try:
    from openai import OpenAI
except Exception as e:
    OpenAI = None
    log.error("OpenAI SDK import failed: %s", e)

class OAClient:
    def __init__(self, key: str, model: str):
        if not key or not OpenAI:
            self.client = None
        else:
            self.client = OpenAI(api_key=key)
        self.model = model

    async def chat(self, text: str, sys_prompt: str="You are a helpful assistant.") -> str:
        if not self.client:
            return "OpenAI API key is not configured."
        try:
            res = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role":"system","content": sys_prompt},
                    {"role":"user","content": text}
                ]
            )
            return res.choices[0].message.content.strip()
        except Exception as e:
            log.exception("chat error")
            return f"Ошибка OpenAI: {e}"

    async def vision_analyze(self, image_url_or_b64: str, prompt: str="Опиши изображение кратко.") -> str:
        if not self.client:
            return "OpenAI API key is not configured."
        content = [{"type":"text","text": prompt}]
        if image_url_or_b64.startswith("http"):
            content.append({"type":"image_url","image_url":{"url": image_url_or_b64}})
        else:
            content.append({"type":"image_url","image_url":{"url": f"data:image/png;base64,{image_url_or_b64}"}})
        try:
            res = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role":"user","content": content}]
            )
            return res.choices[0].message.content.strip()
        except Exception as e:
            log.exception("vision error")
            return f"Не удалось проанализировать изображение: {e}"

    async def tts(self, text: str, voice: str="alloy", fmt: str="ogg") -> bytes:
        if not self.client:
            raise RuntimeError("OpenAI API key is not configured")
        model = "gpt-4o-mini-tts"
        from tempfile import NamedTemporaryFile
        try:
            with NamedTemporaryFile(delete=False, suffix=f".{fmt}") as tmp:
                tmp_path = tmp.name
            with self.client.audio.speech.with_streaming_response.create(
                model=model, voice=voice, input=text, format=fmt
            ) as resp:
                resp.stream_to_file(tmp_path)
            with open(tmp_path, "rb") as f:
                return f.read()
        except Exception as e:
            logging.warning("Streaming TTS failed: %s", e)
            audio = self.client.audio.speech.create(model=model, voice=voice, input=text, format=fmt)
            try:
                return audio.read()
            except Exception:
                try:
                    b64 = audio.get("audio", {}).get("data")
                    if b64:
                        return base64.b64decode(b64)
                except Exception:
                    pass
                raise

    async def stt(self, audio_bytes: bytes, ext: str="ogg") -> str:
        if not self.client:
            return ""
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp.write(audio_bytes); tmp_path = tmp.name
        try:
            # Prefer 4o-transcribe if available
            try:
                with open(tmp_path, "rb") as f:
                    r = self.client.audio.transcriptions.create(
                        model="gpt-4o-transcribe", file=f
                    )
                return r.text.strip()
            except Exception:
                with open(tmp_path, "rb") as f:
                    r = self.client.audio.transcriptions.create(
                        model="whisper-1", file=f
                    )
                return r.text.strip()
        finally:
            with contextlib.suppress(Exception):
                os.remove(tmp_path)

    async def image_generate(self, prompt: str, size: str="1024x1024") -> bytes:
        if not self.client:
            raise RuntimeError("OpenAI API key is not configured")
        res = self.client.images.generate(model="gpt-image-1", prompt=prompt, size=size)
        b64 = res.data[0].b64_json
        return base64.b64decode(b64)

    async def image_edit(self, prompt: str, image_png: bytes, mask_png: Optional[bytes], size: str="1024x1024") -> bytes:
        if not self.client:
            raise RuntimeError("OpenAI API key is not configured")
        if mask_png is None:
            res = self.client.images.edits(
                model="gpt-image-1",
                image=[{"image": image_png}],
                prompt=prompt, size=size
            )
        else:
            res = self.client.images.edits(
                model="gpt-image-1",
                image=[{"image": image_png}],
                mask=mask_png,
                prompt=prompt, size=size
            )
        b64 = res.data[0].b64_json
        return base64.b64decode(b64)

# Instantiate
try:
    OPENAI_CLIENT = OAClient(OPENAI_API_KEY, OPENAI_MODEL)
except Exception:
    OPENAI_CLIENT = None

# ===== Image capabilities intent =====
def wants_image_capabilities(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    img_words = ["изобр", "фото", "картин", "пикч", "image", "photo", "picture"]
    ask_words = ["что", "мож", "уме", "возможн", "способен", "can", "do"]
    return any(w in low for w in img_words) and any(w in low for w in ask_words)

def positive_image_capabilities_text() -> str:
    return (
        "Вот что я умею с изображениями и фото:\n"
        "• 🎬 Оживить фото (Image→Video) через Luma/Runway (реальные движки)\n"
        "• 🧼 Удалить/заменить фон (прозрачный PNG или фон по описанию)\n"
        "• ➕➖ Добавить/удалить объект или человека\n"
        "• 🧩 Расширить кадр (Outpaint) — дорисовать невидимые края/ракурсы\n"
        "• 🎥 Повернуть камеру (орбит/пан/тилт) и лёгкая динамика\n"
        "• 📝 Storyboard — сценарий «глобального оживления» с движением людей и объектов\n\n"
        "Это работает и по тексту, и по голосу. Пришлите фото — покажу кнопки быстрых действий."
    )

# ===== Utils =====
def build_outpaint_inputs(base_png: bytes, expand_pct: float = 0.25) -> tuple[bytes, bytes]:
    base = Image.open(io.BytesIO(base_png)).convert("RGBA")
    w, h = base.size
    dx, dy = int(w * expand_pct), int(h * expand_pct)
    canvas = Image.new("RGBA", (w + 2*dx, h + 2*dy), (0,0,0,0))
    canvas.paste(base, (dx, dy))
    mask = Image.new("L", canvas.size, 255)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((dx, dy, dx+w, dy+h), fill=0)
    b_img = io.BytesIO(); canvas.save(b_img, format="PNG")
    b_mask = io.BytesIO(); mask.save(b_mask, format="PNG")
    return b_img.getvalue(), b_mask.getvalue()

def human_exc(e: Exception) -> str:
    s = str(e)
    return s if len(s) < 400 else s[:400] + "…"

# ===== Telegram Handlers =====
START_TEXT = (
    "Привет! Это BOT GPT‑5, Runway, Midjourney, Luma, Deepgram.\n\n"
    "Что умею:\n"
    "• GPT‑5 тексты, код, документы\n"
    "• Midjourney — фотореалистичные изображения\n"
    "• Luma/Runway — видео из фото (image→video)\n"
    "• Deepgram/OpenAI — речь↔текст\n\n"
    "Подсказки:\n"
    "• /img кот в очках — сгенерирует картинку\n"
    "• «Оживи фото… 9 сек 9:16» — Luma/Runway (если подключены ключи)\n"
    "• /voice_on и /voice_off — озвучка ответов."
)

EXAMPLES_TEXT = (
    "Примеры:\n"
    "• Оживи фото в стиле кино, 6 секунд 9:16 — Luma/Runway\n"
    "• Удали фон у этой картинки\n"
    "• Дорисуй справа террасу и море (outpaint)\n"
    "• Поверни камеру вокруг на 20 градусов\n"
)

MODES_TEXT = (
    "Движки: GPT / Luma / Runway / Images / Docs.\n"
    "Озвучка: /voice_on, /voice_off."
)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user_get_or_create(user.id)
    kb = ReplyKeyboardMarkup([[KeyboardButton("/modes")],[KeyboardButton("/plans")]], resize_keyboard=True)
    await update.effective_message.reply_text(START_TEXT, reply_markup=kb)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Задай вопрос или пришли фото/документ. /examples — примеры.")

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(EXAMPLES_TEXT)

async def cmd_modes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(MODES_TEXT)

async def cmd_ver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(f"Версия: {VERSION_TAG}")

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_user_set_voice(update.effective_user.id, True)
    await update.effective_message.reply_text("🔊 Озвучка включена.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_user_set_voice(update.effective_user.id, False)
    await update.effective_message.reply_text("🔇 Озвучка выключена.")

# ===== CryptoBot =====
async def create_cryptobot_invoice(amount: float = 5.0, asset: str="USDT", desc: str="GPT5 PRO Subscription") -> Optional[str]:
    if not CRYPTOBOT_TOKEN:
        return None
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN, "Content-Type":"application/json"}
    payload = {"asset": asset, "amount": str(amount), "description": desc}
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.post("https://pay.crypt.bot/api/createInvoice", headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            if data.get("ok"):
                return data["result"]["pay_url"]
    except Exception as e:
        log.error("cryptobot createInvoice error: %s", e)
    return None

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = await create_cryptobot_invoice()
    if url:
        await update.effective_message.reply_text(f"Оплата подписки: {url}")
    else:
        await update.effective_message.reply_text("CryptoBot не настроен. Укажи CRYPTOBOT_TOKEN в переменных окружения.")

# ===== /img generate =====
async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args) if context.args else "a cute cat with glasses, studio photo"
    try:
        png = await OPENAI_CLIENT.image_generate(prompt, size="1024x1024")
        await update.effective_message.reply_photo(InputFile(io.BytesIO(png), filename="image.png"), caption="Готово.")
    except Exception as e:
        await update.effective_message.reply_text(f"Не удалось сгенерировать: {human_exc(e)}")

# ===== Text handler =====
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.effective_message.text or ""
    if wants_image_capabilities(text):
        await update.effective_message.reply_text(positive_image_capabilities_text())
        return

    # Outpaint follow-up
    await_outp = context.user_data.pop("await_outpaint", None)
    if await_outp:
        image_id = await_outp.get("image_id")
        meta = context.user_data.get("images_cache", {}).get(image_id)
        if not meta:
            await update.effective_message.reply_text("Не нашёл изображение. Пришлите снова.")
            return
        await update.effective_message.reply_text("Дорисовываю края кадра…")
        try:
            file = await context.bot.get_file(meta["file_id"])
            base_bytes = bytes(await file.download_as_bytearray())
            expanded_png, mask_png = build_outpaint_inputs(base_bytes, expand_pct=0.25)
            edited = await OPENAI_CLIENT.image_edit(text or "extend the scene naturally", expanded_png, mask_png, size="1024x1024")
            await update.effective_message.reply_document(InputFile(io.BytesIO(edited), filename="outpaint.png"),
                                                         caption="Готово: расширил кадр (Outpaint).")
        except Exception as e:
            await update.effective_message.reply_text(f"Ошибка outpaint: {human_exc(e)}")
        return

    db_save_turn(user.id, "user", text)
    reply = await OPENAI_CLIENT.chat(text, sys_prompt="Будь кратким и полезным.")
    db_save_turn(user.id, "assistant", reply)
    await update.effective_message.reply_text(reply)

    # TTS if on
    try:
        info = db_user_get_or_create(user.id)
        if info["voice_on"]:
            ogg = await OPENAI_CLIENT.tts(reply, fmt="ogg")
            try:
                await update.effective_message.reply_voice(ogg, caption="")
            except Exception:
                mp3 = await OPENAI_CLIENT.tts(reply, fmt="mp3")
                await update.effective_message.reply_audio(mp3, caption="")
    except Exception as e:
        await update.effective_message.reply_text(f"Не удалось озвучить: {human_exc(e)}")

# ===== Voice handler =====
async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = update.effective_message.voice or update.effective_message.audio
    if not v:
        return
    file = await context.bot.get_file(v.file_id)
    data = await file.download_as_bytearray()
    text = await OPENAI_CLIENT.stt(bytes(data), ext="ogg")
    await update.effective_message.reply_text(f"🗣 {text}")
    if wants_image_capabilities(text):
        await update.effective_message.reply_text(positive_image_capabilities_text())
        return
    db_save_turn(update.effective_user.id, "user", text)
    reply = await OPENAI_CLIENT.chat(text)
    db_save_turn(update.effective_user.id, "assistant", reply)
    await update.effective_message.reply_text(reply)
    # TTS optional
    try:
        info = db_user_get_or_create(update.effective_user.id)
        if info["voice_on"]:
            ogg = await OPENAI_CLIENT.tts(reply, fmt="ogg")
            try:
                await update.effective_message.reply_voice(ogg)
            except Exception:
                mp3 = await OPENAI_CLIENT.tts(reply, fmt="mp3")
                await update.effective_message.reply_audio(mp3)
    except Exception:
        pass

# ===== Photo handler =====
from rembg import remove as rembg_remove

def kb_photo_actions(image_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Оживить фото (Image→Video)", callback_data=f"anim:{image_id}")],
        [InlineKeyboardButton("🧼 Удалить фон", callback_data=f"rmbg:{image_id}"),
         InlineKeyboardButton("🏞 Заменить фон", callback_data=f"bg:{image_id}")],
        [InlineKeyboardButton("➕➖ Объекты/люди", callback_data=f"obj:{image_id}"),
         InlineKeyboardButton("🧩 Outpaint", callback_data=f"outp:{image_id}")],
        [InlineKeyboardButton("🎥 Повернуть камеру", callback_data=f"cam:{image_id}"),
         InlineKeyboardButton("📝 Storyboard", callback_data=f"story:{image_id}")],
    ])

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    caption = msg.caption or ""
    photos = msg.photo
    if not photos:
        return
    photo = photos[-1]  # best quality
    image_id = photo.file_unique_id
    # Cache
    cache = context.user_data.setdefault("images_cache", {})
    cache[image_id] = {"file_id": photo.file_id, "caption": caption}

    await msg.reply_text("Фото получено. Выберите действие:", reply_markup=kb_photo_actions(image_id))
    await msg.reply_text(positive_image_capabilities_text())

    # Auto reaction to caption
    if caption:
        try:
            f = await context.bot.get_file(photo.file_id)
            url = f.file_path  # Telegram CDN URL
            ans = await OPENAI_CLIENT.vision_analyze(url, f"Отреагируй дружелюбно на подпись и предложи улучшения. Подпись: «{caption}».")
            await msg.reply_text(ans)
        except Exception:
            pass

# ===== Callbacks =====
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    user_data = context.user_data
    cache = user_data.get("images_cache", {})

    async def load_image_bytes(image_id: str) -> bytes:
        meta = cache.get(image_id)
        if not meta:
            raise RuntimeError("Не найдено изображение в кэше.")
        file = await context.bot.get_file(meta["file_id"])
        return bytes(await file.download_as_bytearray())

    if data.startswith("rmbg:"):
        img_id = data.split(":",1)[1]
        try:
            raw = await load_image_bytes(img_id)
            out = rembg_remove(raw)
            await q.message.reply_document(InputFile(io.BytesIO(out), filename="no-bg.png"), caption="Готово: фон удалён (PNG).")
        except Exception as e:
            await q.message.reply_text(f"Ошибка удаления фона: {human_exc(e)}")
        return

    if data.startswith("bg:"):
        img_id = data.split(":",1)[1]
        user_data["await_bg_replace"] = {"image_id": img_id}
        await q.message.reply_text("Напиши, какой фон создать (описание сцены/стиля).")
        return

    if data.startswith("outp:"):
        img_id = data.split(":",1)[1]
        user_data["await_outpaint"] = {"image_id": img_id}
        await q.message.reply_text("Опиши, что дорисовать вокруг кадра (фон/интерьер/улицу).")
        return

    if data.startswith("obj:"):
        await q.message.reply_text("Опиши, что добавить или что/где удалить. (Примечание: тонкая маска потребует уточнений).")
        user_data["await_obj_edit"] = {"note": "text-guided edit"}
        return

    if data.startswith("story:"):
        try:
            story_prompt = "Сделай короткий storyboard оживления кадра (3–6 сцен) с движениями человека и объектов, кратко."
            res = await OPENAI_CLIENT.chat(story_prompt)
            await q.message.reply_text(res)
        except Exception as e:
            await q.message.reply_text(f"Ошибка storyboard: {human_exc(e)}")
        return

    if data.startswith("anim:"):
        if not (LUMA_API_KEY or RUNWAY_API_KEY):
            await q.message.reply_text("Для оживления фото подключи LUMA_API_KEY или RUNWAY_API_KEY в переменных окружения.")
            return
        await q.message.reply_text("Создаю задачу оживления (image→video)… (заглушка).")
        return

    if data.startswith("cam:"):
        if not (LUMA_API_KEY or RUNWAY_API_KEY):
            await q.message.reply_text("Для поворота камеры подключи LUMA_API_KEY или RUNWAY_API_KEY.")
            return
        await q.message.reply_text("Создаю задачу на поворот камеры… (заглушка).")
        return

# ===== Background actions from text follow-up =====
async def on_text_followups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    msg = update.effective_message
    text = msg.text or ""
    user_data = context.user_data
    cache = user_data.get("images_cache", {})

    # Replace background
    await_bg = user_data.pop("await_bg_replace", None)
    if await_bg:
        try:
            meta = cache.get(await_bg["image_id"])
            if not meta:
                await msg.reply_text("Не нашёл изображение. Пришлите снова.")
                return True
            file = await context.bot.get_file(meta["file_id"])
            base_bytes = bytes(await file.download_as_bytearray())
            # 1) Remove to alpha
            from rembg import remove as rembg_remove_local
            cut = rembg_remove_local(base_bytes)
            fg = Image.open(io.BytesIO(cut)).convert("RGBA")
            # 2) Generate background
            bg_png = await OPENAI_CLIENT.image_generate(text or "studio background", size="1024x1024")
            bg = Image.open(io.BytesIO(bg_png)).convert("RGBA").resize(fg.size)
            # 3) Composite
            canvas = Image.new("RGBA", fg.size, (0,0,0,0))
            canvas.paste(bg, (0,0))
            canvas.alpha_composite(fg)
            out = io.BytesIO(); canvas.save(out, format="PNG")
            await msg.reply_document(InputFile(io.BytesIO(out.getvalue()), filename="rebackground.png"),
                                     caption="Готово: фон заменён.")
        except Exception as e:
            await msg.reply_text(f"Ошибка замены фона: {human_exc(e)}")
        return True

    # Object edits (simple text-to-edit without precise mask)
    await_obj = user_data.pop("await_obj_edit", None)
    if await_obj:
        try:
            meta = None
            if cache:
                meta = list(cache.values())[-1]
            if not meta:
                await msg.reply_text("Не нашёл изображение. Пришлите снова.")
                return True
            file = await context.bot.get_file(meta["file_id"])
            base_bytes = bytes(await file.download_as_bytearray())
            edited = await OPENAI_CLIENT.image_edit(text or "enhance", base_bytes, None, size="1024x1024")
            await msg.reply_document(InputFile(io.BytesIO(edited), filename="edit.png"), caption="Готово.")
        except Exception as e:
            await msg.reply_text(f"Ошибка редактирования: {human_exc(e)}")
        return True

    return False

# ===== Router: wrap text updates to check followups first =====
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    handled = await on_text_followups(update, context)
    if handled:
        return
    await on_text(update, context)

# ===== App =====
def build_app() -> Application:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN is not set")
        sys.exit(1)
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("examples", cmd_examples))
    app.add_handler(CommandHandler("modes", cmd_modes))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("voice_on", cmd_voice_on))
    app.add_handler(CommandHandler("voice_off", cmd_voice_off))
    app.add_handler(CommandHandler("img", cmd_img))
    app.add_handler(CommandHandler("ver", cmd_ver))

    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    return app

async def main_async():
    app = build_app()
    await app.initialize()
    await app.start()
    log.info("Bot started: %s", VERSION_TAG)
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()

def main():
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    main()
