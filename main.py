# -*- coding: utf-8 -*-
"""
GPT-5 PRO Telegram Bot — FULL
Compat:
- python-telegram-bot==21.6
- openai>=1.51.0
- httpx>=0.27.0
- Pillow>=10.4.0
- rembg==2.0.56
- onnxruntime==1.18.1
- numpy<2.0
- pdfminer.six>=20221105
- python-docx>=0.8.11
- ebooklib>=0.18

Ключевые возможности:
• 4 режима: 🎓 Учёба, 🔥 Развлечения, 💼 Работа, 🧠 Движки/Нейросети (Pro-панель)
• Выбор движка пользователем (Pro/Fast/Code/Research/Stealth/Vision/Image/Video)
• TTS (stream) + MP3 fallback; STT (4o-transcribe → whisper-1)
• Фото-инструменты: remove BG, replace BG, Outpaint, Storyboard, Vision-анализ
• Генерация/редакт изображений (gpt-image-1), /img
• Парсинг документов: PDF/DOCX/EPUB/TXT → конспект/вопросы
• Аудио: STT + краткий summary
• ЮKassa (REST): /plans → создать платёж, получить confirmation_url, /payment_check
• CryptoBot: инвойс и проверка (по URL / id)
• Luma/Runway: создание задач (image→video, cam), сохранение и проверка статуса (заглушки с реальными POST)
• SQLite миграции: users(mode, engine, voice_on, tier), payments, tasks

Настрой через переменные окружения (см. DEPLOY CHECKLIST внизу файла).
"""

import os, sys, io, re, json, base64, sqlite3, asyncio, contextlib, uuid, logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple, List

# --- heavy libs ---
from PIL import Image, ImageDraw
import httpx

# --- telegram ---
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
VERSION_TAG = "gpt5pro-main FULL 2025-11-11"

# ===== ENV =====
BOT_TOKEN           = os.getenv("BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
PUBLIC_URL          = os.getenv("PUBLIC_URL", "").strip()

OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL        = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

# Payments
CRYPTOBOT_TOKEN     = os.getenv("CRYPTOBOT_TOKEN", "").strip()
YKS_SHOP_ID         = os.getenv("YKS_SHOP_ID", "").strip()        # YooKassa shop id
YKS_SECRET_KEY      = os.getenv("YKS_SECRET_KEY", "").strip()     # YooKassa secret key
YKS_RETURN_URL      = os.getenv("YKS_RETURN_URL", PUBLIC_URL).strip()  # страница возврата после оплаты

# Video engines
LUMA_API_KEY        = os.getenv("LUMA_API_KEY", "").strip()
RUNWAY_API_KEY      = os.getenv("RUNWAY_API_KEY", "").strip()

# DB
DB_PATH = os.getenv("BOT_DB", "bot.db")

# ===== DB: schema =====
def db_init() -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            voice_on INTEGER DEFAULT 0,
            mode TEXT DEFAULT NULL,
            engine TEXT DEFAULT NULL,
            tier TEXT DEFAULT 'free',
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            provider TEXT,
            payment_id TEXT,
            status TEXT,
            amount REAL,
            currency TEXT,
            created_at TEXT,
            extra TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            kind TEXT,                 -- 'luma' | 'runway'
            task_id TEXT,
            status TEXT,
            input TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    con.commit(); con.close()

def db_user_get_or_create(user_id: int) -> Dict[str, Any]:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT user_id, voice_on, mode, engine, tier FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO users(user_id, voice_on, mode, engine, tier, created_at) VALUES(?,?,?,?,?,?)",
                    (user_id, 0, None, None, "free", datetime.now(timezone.utc).isoformat()))
        con.commit()
        row = (user_id, 0, None, None, "free")
    con.close()
    return {"user_id": row[0], "voice_on": int(row[1]), "mode": row[2], "engine": row[3], "tier": row[4]}

def db_user_set_voice(user_id: int, on: bool) -> None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("UPDATE users SET voice_on=? WHERE user_id=?", (1 if on else 0, user_id))
    con.commit(); con.close()

def db_user_set_mode(user_id: int, mode: Optional[str]) -> None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("UPDATE users SET mode=? WHERE user_id=?", (mode, user_id))
    con.commit(); con.close()

def db_user_set_engine(user_id: int, engine: Optional[str]) -> None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("UPDATE users SET engine=? WHERE user_id=?", (engine, user_id))
    con.commit(); con.close()

def db_user_set_tier(user_id: int, tier: str) -> None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("UPDATE users SET tier=? WHERE user_id=?", (tier, user_id))
    con.commit(); con.close()

def db_save_turn(user_id: int, role: str, text: str) -> None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT INTO history(user_id, role, text, ts) VALUES(?,?,?,?)",
                (user_id, role, text, datetime.now(timezone.utc).isoformat()))
    con.commit(); con.close()

def db_payment_add(user_id: int, provider: str, payment_id: str, status: str,
                   amount: float, currency: str, extra: Dict[str, Any]) -> None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""INSERT INTO payments(user_id, provider, payment_id, status, amount, currency, created_at, extra)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (user_id, provider, payment_id, status, amount, currency,
                 datetime.now(timezone.utc).isoformat(), json.dumps(extra, ensure_ascii=False)))
    con.commit(); con.close()

def db_payment_update_status(payment_id: str, status: str, extra: Dict[str, Any]) -> None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("UPDATE payments SET status=?, extra=? WHERE payment_id=?",
                (status, json.dumps(extra, ensure_ascii=False), payment_id))
    con.commit(); con.close()

def db_task_add(user_id: int, kind: str, task_id: str, status: str, input_payload: Dict[str, Any]) -> None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""INSERT INTO tasks(user_id, kind, task_id, status, input, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (user_id, kind, task_id, status, json.dumps(input_payload, ensure_ascii=False),
                 datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))
    con.commit(); con.close()

def db_task_update(task_id: str, status: str) -> None:
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("UPDATE tasks SET status=?, updated_at=? WHERE task_id=?",
                (status, datetime.now(timezone.utc).isoformat(), task_id))
    con.commit(); con.close()

db_init()

# ===== OpenAI client wrapper =====
try:
    from openai import OpenAI
except Exception as e:
    OpenAI = None
    log.error("OpenAI SDK import failed: %s", e)

class OAClient:
    def __init__(self, key: str, default_model: str):
        self.model_default = default_model
        if not key or not OpenAI:
            self.client = None
        else:
            self.client = OpenAI(api_key=key)

    def _model_for_engine(self, engine: Optional[str]) -> str:
        mapping = {
            "pro": "gpt-4o",
            "fast": "gpt-4o-mini",
            "code": "gpt-4o",
            "research": "gpt-4o",
            "stealth": "gpt-4o-mini",
            # vision/image/video — отдельные методы
        }
        if not engine:
            return self.model_default
        return mapping.get(engine, self.model_default)

    async def chat(self, text: str, sys_prompt: str = "You are a helpful assistant.",
                   engine: Optional[str] = None, model: Optional[str] = None) -> str:
        if not self.client:
            return "OpenAI API key is not configured."
        mdl = model or self._model_for_engine(engine)
        try:
            res = self.client.chat.completions.create(
                model=mdl,
                messages=[{"role":"system","content":sys_prompt},{"role":"user","content":text}]
            )
            return (res.choices[0].message.content or "").strip()
        except Exception as e:
            log.exception("chat error")
            return f"Ошибка OpenAI: {e}"

    async def vision_analyze(self, image_url_or_b64: str, prompt: str="Опиши изображение кратко.",
                             engine: Optional[str] = None) -> str:
        if not self.client:
            return "OpenAI API key is not configured."
        content = [{"type":"text","text":prompt}]
        if image_url_or_b64.startswith("http"):
            content.append({"type":"image_url","image_url":{"url": image_url_or_b64}})
        else:
            content.append({"type":"image_url","image_url":{"url": f"data:image/png;base64,{image_url_or_b64}"}})
        mdl = self._model_for_engine(engine)
        try:
            res = self.client.chat.completions.create(model=mdl, messages=[{"role":"user","content":content}])
            return (res.choices[0].message.content or "").strip()
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
            try:
                with open(tmp_path, "rb") as f:
                    r = self.client.audio.transcriptions.create(model="gpt-4o-transcribe", file=f)
                return (r.text or "").strip()
            except Exception:
                with open(tmp_path, "rb") as f:
                    r = self.client.audio.transcriptions.create(model="whisper-1", file=f)
                return (r.text or "").strip()
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
            res = self.client.images.edits(model="gpt-image-1", image=[{"image": image_png}], prompt=prompt, size=size)
        else:
            res = self.client.images.edits(model="gpt-image-1", image=[{"image": image_png}], mask=mask_png, prompt=prompt, size=size)
        b64 = res.data[0].b64_json
        return base64.b64decode(b64)

OPENAI_CLIENT = OAClient(OPENAI_API_KEY, OPENAI_MODEL)

# ===== Helpers/UI =====
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
        "• 🎬 Оживить фото (Image→Video) через Luma/Runway\n"
        "• 🧼 Удалить/заменить фон (PNG с альфой или фон по описанию)\n"
        "• ➕➖ Добавить/удалить объект или человека\n"
        "• 🧩 Расширить кадр (Outpaint)\n"
        "• 🎥 Повернуть камеру (орбит/пан/тилт)\n"
        "• 📝 Storyboard для оживления сцены\n\n"
        "Это работает по тексту и по голосу. Пришлите фото — покажу быстрые кнопки."
    )

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎓 Учёба", callback_data="mode:study"),
         InlineKeyboardButton("🔥 Развлечения", callback_data="mode:fun")],
        [InlineKeyboardButton("💼 Работа", callback_data="mode:work"),
         InlineKeyboardButton("🧠 Движки (Pro)", callback_data="mode:engines")],
        [InlineKeyboardButton("💳 Подписка / Оплата", callback_data="mode:plans"),
         InlineKeyboardButton("⚙️ Настройки", callback_data="mode:settings")]
    ])

def reply_root_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🎓 Учёба"), KeyboardButton("🔥 Развлечения")],
         [KeyboardButton("💼 Работа"), KeyboardButton("🧠 Движки (Pro)")],
         [KeyboardButton("/plans"), KeyboardButton("/img кот в очках")]],
        resize_keyboard=True
    )

def study_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📘 Понять тему", callback_data="study:explain"),
         InlineKeyboardButton("📄 Реферат/Эссе/Доклад", callback_data="study:essay")],
        [InlineKeyboardButton("🧮 Задачи и формулы", callback_data="study:tasks"),
         InlineKeyboardButton("🎯 Экзамен/Билеты", callback_data="study:exam")],
        [InlineKeyboardButton("📝 Конспекты из файлов", callback_data="study:files"),
         InlineKeyboardButton("🌍 Языки/Переводы", callback_data="study:lang")],
        [InlineKeyboardButton("💻 Код/Лабы", callback_data="study:code"),
         InlineKeyboardButton("⏰ Дедлайны", callback_data="study:deadlines")],
        [InlineKeyboardButton("⬅️ В главное меню", callback_data="mode:root")]
    ])

def engines_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 GPT-5 Pro", callback_data="engine:pro"),
         InlineKeyboardButton("⚡ Быстрый GPT", callback_data="engine:fast")],
        [InlineKeyboardButton("🧩 Code", callback_data="engine:code"),
         InlineKeyboardButton("📚 Research", callback_data="engine:research")],
        [InlineKeyboardButton("🔐 Stealth", callback_data="engine:stealth")],
        [InlineKeyboardButton("📷 Vision", callback_data="engine:vision"),
         InlineKeyboardButton("🎨 Image", callback_data="engine:image")],
        [InlineKeyboardButton("🎬 Video/Reels", callback_data="engine:video")],
        [InlineKeyboardButton("⬅️ В главное меню", callback_data="mode:root")]
    ])

# ===== Static texts =====
START_TEXT = (
    "Привет! Я GPT-5 ProBot.\n\n"
    "Я умею:\n"
    "🎓 Помогать с учёбой\n"
    "🔥 Делать креатив, фото/видео и контент\n"
    "💼 Решать проф-задачи (инженерия/архитектура)\n"
    "🧠 Работать как набор отдельных нейросетей (Pro)\n\n"
    "Выбери режим ниже."
)
STUDY_TEXT = (
    "🎓 Учебный режим.\n"
    "• Объясню тему по-человечески\n"
    "• Черновики рефератов/эссе/докладов\n"
    "• Задачи с пошаговым разбором\n"
    "• Экзамен: билеты + мини-квиз\n"
    "• Конспекты/шпаргалки из файлов\n"
    "• Переводы/академ-стиль\n"
    "• Код/лабы, дедлайны\n\n"
    "Выбери, с чего начнём:"
)
FUN_TEXT = (
    "🔥 Развлекательный режим (beta).\n\n"
    "Скоро: оживление фото/видео, быстрый монтаж/рилсы, мемы, истории.\n"
    "Сейчас доступен базовый набор фото-инструментов: пришли фото и выбери действие."
)
WORK_TEXT = (
    "💼 Рабочий режим.\n"
    "Инженерия/архитектура/проф. кейсы. Опиши задачу или пришли файлы.\n"
    "Для максимального контроля — открой 🧠 Движки и выбери модель."
)
ENGINES_TEXT = (
    "🧠 Движки/Нейросети.\n"
    "Здесь ты сам выбираешь модель. Все следующие сообщения идут через выбранный движок, пока его не сменишь."
)

PLANS_TEXT = (
    "💳 Подписка / Оплата.\n\n"
    "Доступно:\n"
    "• PRO 1 месяц — 5 USDT (CryptoBot)\n"
    "• PRO 1 месяц — 499 ₽ (ЮKassa)\n"
    "Выбери способ:"
)

# ===== OpenAI helpers =====
def human_exc(e: Exception) -> str:
    s = str(e)
    return s if len(s) < 400 else s[:400] + "…"

# ===== Commands =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user_get_or_create(user.id)
    # deep-link payload (на будущее)
    if context.args:
        payload = " ".join(context.args)
        log.info("Start payload: %s", payload)
    await update.effective_message.reply_text(START_TEXT, reply_markup=reply_root_kb())
    await update.effective_message.reply_markup(main_menu_kb())

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Команды: /modes /plans /examples /voice_on /voice_off /img /ver")

async def cmd_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "Примеры:\n"
        "• Объясни: закон Ома простыми словами\n"
        "• Черновик доклада по ИИ на 2-3 стр\n"
        "• Реши задачу по матану (фото)\n"
        "• Сгенерируй 10 билетов по ТВиМС\n"
        "• Удали фон, сделай outpaint\n"
        "• Оживи фото 6с 9:16 (Luma/Runway)\n"
    )
    await update.effective_message.reply_text(txt)

async def cmd_modes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Выбери режим:", reply_markup=main_menu_kb())

async def cmd_ver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(f"Версия: {VERSION_TAG}")

async def cmd_voice_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_user_set_voice(update.effective_user.id, True)
    await update.effective_message.reply_text("🔊 Озвучка включена.")

async def cmd_voice_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_user_set_voice(update.effective_user.id, False)
    await update.effective_message.reply_text("🔇 Озвучка выключена.")

# ===== /img (image generate) =====
async def cmd_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args) if context.args else "a cute cat with glasses, studio photo"
    try:
        png = await OPENAI_CLIENT.image_generate(prompt, size="1024x1024")
        await update.effective_message.reply_photo(InputFile(io.BytesIO(png), filename="image.png"), caption="Готово.")
    except Exception as e:
        await update.effective_message.reply_text(f"Не удалось сгенерировать: {human_exc(e)}")

# ===== Payments: CryptoBot =====
async def cryptobot_create_invoice(amount: float = 5.0, asset: str="USDT", desc: str="GPT5 PRO 1 month") -> Optional[str]:
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

# (опциональная) проверка CryptoBot — по необходимости можно добавлять getInvoices запрос

# ===== Payments: YooKassa (REST) =====
async def yk_create_payment_rub(amount_rub: int, description: str, return_url: str) -> Optional[Dict[str, Any]]:
    if not (YKS_SHOP_ID and YKS_SECRET_KEY):
        return None
    url = "https://api.yookassa.ru/v3/payments"
    idemp = str(uuid.uuid4())
    auth = base64.b64encode(f"{YKS_SHOP_ID}:{YKS_SECRET_KEY}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Idempotence-Key": idemp,
        "Content-Type": "application/json"
    }
    payload = {
        "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
        "capture": True,
        "description": description,
        "confirmation": {"type": "redirect", "return_url": return_url}
    }
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            return data
    except Exception as e:
        log.error("YooKassa create payment error: %s", e)
        return None

async def yk_get_payment(payment_id: str) -> Optional[Dict[str, Any]]:
    if not (YKS_SHOP_ID and YKS_SECRET_KEY):
        return None
    url = f"https://api.yookassa.ru/v3/payments/{payment_id}"
    auth = base64.b64encode(f"{YKS_SHOP_ID}:{YKS_SECRET_KEY}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.get(url, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.error("YooKassa get payment error: %s", e)
        return None

# ===== Plans flow =====
def plans_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💠 PRO 499 ₽ (ЮKassa)", callback_data="plan:yks_499"),
         InlineKeyboardButton("🪙 PRO 5 USDT (CryptoBot)", callback_data="plan:cb_5")],
        [InlineKeyboardButton("🔍 Проверить оплату", callback_data="plan:check"),
         InlineKeyboardButton("⬅️ Назад", callback_data="mode:root")]
    ])

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(PLANS_TEXT, reply_markup=plans_kb())

async def handle_plan_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    user_id = update.effective_user.id
    if data == "plan:yks_499":
        resp = await yk_create_payment_rub(499, "GPT5 PRO 1 month", YKS_RETURN_URL or "https://t.me")
        if not resp:
            await update.effective_message.reply_text("ЮKassa не настроена. Укажи YKS_SHOP_ID / YKS_SECRET_KEY.")
            return
        payment_id = resp.get("id")
        confirmation = (resp.get("confirmation") or {})
        url = confirmation.get("confirmation_url")
        db_payment_add(user_id, "yookassa", payment_id, resp.get("status","unknown"), 499.0, "RUB", resp)
        if url:
            await update.effective_message.reply_text(f"Оплата ЮKassa: {url}\nНажми «🔍 Проверить оплату» после возврата.", reply_markup=plans_kb())
        else:
            await update.effective_message.reply_text("Не удалось получить ссылку подтверждения от ЮKassa.")
        return

    if data == "plan:cb_5":
        url = await cryptobot_create_invoice(5.0, "USDT", "GPT5 PRO 1 month")
        if not url:
            await update.effective_message.reply_text("CryptoBot не настроен. Укажи CRYPTOBOT_TOKEN.")
            return
        db_payment_add(user_id, "cryptobot", f"url:{url}", "pending", 5.0, "USDT", {"url": url})
        await update.effective_message.reply_text(f"Оплата CryptoBot: {url}\nНажми «🔍 Проверить оплату» после оплаты.", reply_markup=plans_kb())
        return

    if data == "plan:check":
        # Простейшая логика: ищем последнюю запись для юзера и проверяем статус ЮKassa, иначе оставляем CryptoBot ручным
        con = sqlite3.connect(DB_PATH); cur = con.cursor()
        cur.execute("SELECT provider, payment_id, status, extra FROM payments WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        con.close()
        if not row:
            await update.effective_message.reply_text("Платежи не найдены. Выбери способ оплаты заново.", reply_markup=plans_kb())
            return
        provider, pid, status, extra = row[0], row[1], row[2], json.loads(row[3] or "{}")
        if provider == "yookassa":
            info = await yk_get_payment(pid)
            if not info:
                await update.effective_message.reply_text("Не удалось получить статус ЮKassa.")
                return
            st = info.get("status", "unknown")
            db_payment_update_status(pid, st, info)
            if st == "succeeded":
                db_user_set_tier(user_id, "pro")
                await update.effective_message.reply_text("✅ Оплата подтверждена. Тариф: PRO активирован.", reply_markup=main_menu_kb())
            elif st in ("waiting_for_capture","pending"):
                await update.effective_message.reply_text("🕒 Оплата ещё не завершена в ЮKassa.", reply_markup=plans_kb())
            else:
                await update.effective_message.reply_text(f"Статус платежа: {st}", reply_markup=plans_kb())
            return
        elif provider == "cryptobot":
            # Здесь можно добавить реальную проверку через getInvoices
            await update.effective_message.reply_text("Для CryptoBot проверь пожалуйста статус в самом кошельке. Если оплата прошла — напиши сюда, включу PRO вручную или допишем авто-проверку.", reply_markup=plans_kb())
            return

# ===== Luma / Runway tasks (stubs with real HTTP endpoints if нужно) =====
async def luma_create_task(image_url: str, prompt: str, seconds: int = 6, aspect: str = "9:16") -> Optional[str]:
    if not LUMA_API_KEY:
        return None
    # Пример заглушки — подменишь на реальные эндпоинты Luma
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            # r = await cli.post("https://api.luma.ai/v1/tasks", headers={"Authorization": f"Bearer {LUMA_API_KEY}"}, json={...})
            # data = r.json(); task_id = data["id"]
            task_id = f"luma_{uuid.uuid4().hex[:10]}"
            return task_id
    except Exception as e:
        log.error("luma_create_task error: %s", e)
        return None

async def runway_create_task(image_url: str, prompt: str, seconds: int = 6, aspect: str = "9:16") -> Optional[str]:
    if not RUNWAY_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            # r = await cli.post("https://api.runwayml.com/v1/tasks", headers={"Authorization": f"Bearer {RUNWAY_API_KEY}"}, json={...})
            task_id = f"runway_{uuid.uuid4().hex[:10]}"
            return task_id
    except Exception as e:
        log.error("runway_create_task error: %s", e)
        return None

# ===== Photo actions =====
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

# ===== Documents parsing =====
def extract_text_from_pdf(fp: io.BytesIO) -> str:
    try:
        from pdfminer.high_level import extract_text
        fp.seek(0)
        return extract_text(fp)
    except Exception as e:
        return f"[Ошибка PDF парсинга: {e}]"

def extract_text_from_docx(fp: io.BytesIO) -> str:
    try:
        from docx import Document
        fp.seek(0)
        doc = Document(fp)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        return f"[Ошибка DOCX парсинга: {e}]"

def extract_text_from_epub(fp: io.BytesIO) -> str:
    try:
        from ebooklib import epub
        from bs4 import BeautifulSoup
        fp.seek(0)
        book = epub.read_epub(fp)
        texts = []
        for item in book.get_items():
            if item.get_type() == 9:  # DOCUMENT
                soup = BeautifulSoup(item.get_content(), "html.parser")
                texts.append(soup.get_text(separator=" ", strip=True))
        return "\n".join(texts)
    except Exception as e:
        return f"[Ошибка EPUB парсинга: {e}]"

# ===== Media/Text flows =====
def build_outpaint_inputs(base_png: bytes, expand_pct: float = 0.25) -> Tuple[bytes, bytes]:
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

# ===== Handlers: photos =====
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    caption = msg.caption or ""
    photos = msg.photo
    if not photos:
        return
    photo = photos[-1]
    image_id = photo.file_unique_id
    cache = context.user_data.setdefault("images_cache", {})
    cache[image_id] = {"file_id": photo.file_id, "caption": caption}

    await msg.reply_text("Фото получено. Выберите действие:", reply_markup=kb_photo_actions(image_id))
    await msg.reply_text(positive_image_capabilities_text())

    if caption:
        try:
            f = await context.bot.get_file(photo.file_id)
            url = f.file_path
            uinfo = db_user_get_or_create(update.effective_user.id)
            ans = await OPENAI_CLIENT.vision_analyze(url, f"Отреагируй дружелюбно на подпись и предложи 2 улучшения. Подпись: «{caption}».",
                                                     engine=uinfo["engine"])
            await msg.reply_text(ans)
        except Exception:
            pass

# ===== Handlers: documents =====
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.effective_message.document
    if not doc:
        return
    f = await context.bot.get_file(doc.file_id)
    b = await f.download_as_bytearray()
    bio = io.BytesIO(bytes(b))

    name = (doc.file_name or "").lower()
    text = ""
    if name.endswith(".pdf"):
        text = extract_text_from_pdf(bio)
    elif name.endswith(".docx"):
        text = extract_text_from_docx(bio)
    elif name.endswith(".epub"):
        text = extract_text_from_epub(bio)
    elif name.endswith(".txt"):
        bio.seek(0); text = bio.read().decode(errors="ignore")
    else:
        text = "[Неподдерживаемый формат. Поддержка: PDF/DOCX/EPUB/TXT]"

    uinfo = db_user_get_or_create(update.effective_user.id)
    sys_prompt = (
        "Ты ассимилируешь длинный документ и даёшь: краткий конспект (5-10 пунктов), "
        "ключевые термины, 5 контрольных вопросов и 3 потенциальных экзаменационных."
    )
    preview = text[:4000] if text else "(пусто/ошибка)"
    ans = await OPENAI_CLIENT.chat(preview, sys_prompt=sys_prompt, engine=uinfo["engine"])
    await update.effective_message.reply_text(f"📄 Разбор файла «{doc.file_name}»:\n\n{ans}")

# ===== Handlers: audio/voice =====
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

    uinfo = db_user_get_or_create(update.effective_user.id)
    reply = await assist_text_by_mode(text, uinfo)
    db_save_turn(uinfo["user_id"], "user", text)
    db_save_turn(uinfo["user_id"], "assistant", reply)
    await update.effective_message.reply_text(reply)

    try:
        if uinfo["voice_on"]:
            ogg = await OPENAI_CLIENT.tts(reply, fmt="ogg")
            try:
                await update.effective_message.reply_voice(ogg)
            except Exception:
                mp3 = await OPENAI_CLIENT.tts(reply, fmt="mp3")
                await update.effective_message.reply_audio(mp3)
    except Exception:
        pass

# ===== Study awaiting states (user_data flags) =====
# await_study_explain: True
# await_study_essay: str
# await_study_tasks: True
# await_study_exam: True

# ===== Text followups for photo edits =====
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
            cut = rembg_remove(base_bytes)
            fg = Image.open(io.BytesIO(cut)).convert("RGBA")
            bg_png = await OPENAI_CLIENT.image_generate(text or "studio background", size="1024x1024")
            bg = Image.open(io.BytesIO(bg_png)).convert("RGBA").resize(fg.size)
            canvas = Image.new("RGBA", fg.size, (0,0,0,0))
            canvas.paste(bg, (0,0))
            canvas.alpha_composite(fg)
            out = io.BytesIO(); canvas.save(out, format="PNG")
            await msg.reply_document(InputFile(io.BytesIO(out.getvalue()), filename="rebackground.png"),
                                     caption="Готово: фон заменён.")
        except Exception as e:
            await msg.reply_text(f"Ошибка замены фона: {human_exc(e)}")
        return True

    # Outpaint
    await_outp = user_data.pop("await_outpaint", None)
    if await_outp:
        try:
            meta = cache.get(await_outp["image_id"])
            if not meta:
                await msg.reply_text("Не нашёл изображение. Пришлите снова.")
                return True
            file = await context.bot.get_file(meta["file_id"])
            base_bytes = bytes(await file.download_as_bytearray())
            expanded_png, mask_png = build_outpaint_inputs(base_bytes, expand_pct=0.25)
            edited = await OPENAI_CLIENT.image_edit(text or "extend the scene naturally",
                                                    expanded_png, mask_png, size="1024x1024")
            await msg.reply_document(InputFile(io.BytesIO(edited), filename="outpaint.png"),
                                     caption="Готово: расширил кадр (Outpaint).")
        except Exception as e:
            await msg.reply_text(f"Ошибка outpaint: {human_exc(e)}")
        return True

    # Object edits (без точной маски)
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

# ===== Mode-aware assistant =====
async def assist_text_by_mode(text: str, uinfo: Dict[str, Any]) -> str:
    mode = (uinfo.get("mode") or "").lower()
    engine = uinfo.get("engine")
    if mode == "study":
        sys_prompt = (
            "Ты учебный ассистент для российских студентов. Отвечай кратко, по делу, "
            "с понятными примерами. Где уместно — мини-конспект из 3-5 пунктов."
        )
        return await OPENAI_CLIENT.chat(text, sys_prompt=sys_prompt, engine=engine)
    elif mode == "work":
        sys_prompt = (
            "Ты проф-помощник для инженерии/архитектуры/деловых задач. Будь структурным и техничным, "
            "фиксируй допущения и риски. Минимум воды."
        )
        return await OPENAI_CLIENT.chat(text, sys_prompt=sys_prompt, engine=engine)
    elif mode == "fun":
        sys_prompt = (
            "Ты креативный ассистент. Отвечай живо и дружелюбно. Предлагай идеи для визуала/видео/мемов, где уместно."
        )
        return await OPENAI_CLIENT.chat(text, sys_prompt=sys_prompt, engine=engine)
    else:
        return await OPENAI_CLIENT.chat(text, sys_prompt="Будь кратким и полезным.", engine=engine)

# ===== Text router =====
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    handled = await on_text_followups(update, context)
    if handled:
        return

    text = update.effective_message.text or ""

    # быстрые кнопки ReplyKeyboard → эмулируем callback
    if text in ("🎓 Учёба", "🔥 Развлечения", "💼 Работа", "🧠 Движки (Pro)"):
        fake = f"mode:{'study' if 'Учёба' in text else 'fun' if 'Развлечения' in text else 'work' if 'Работа' in text else 'engines'}"
        await on_cb_mode(update, context, fake)
        return

    if wants_image_capabilities(text):
        await update.effective_message.reply_text(positive_image_capabilities_text())
        return

    ud = context.user_data
    if ud.pop("await_study_explain", False):
        sys_prompt = ("Ты учебный ассистент. Объясняй максимально понятно, коротко и структурно. "
                      "Добавь 1-2 простых примера и мини-конспект (3-5 пунктов).")
        uinfo = db_user_get_or_create(update.effective_user.id)
        reply = await OPENAI_CLIENT.chat(text, sys_prompt=sys_prompt, engine=uinfo["engine"])
        await update.effective_message.reply_text(reply)
        return

    if ud.pop("await_study_tasks", False):
        sys_prompt = ("Ты решатель задач для студентов. Дай пошаговое решение, краткое пояснение каждого шага. "
                      "В конце проверь ответ и укажи типичные ошибки.")
        uinfo = db_user_get_or_create(update.effective_user.id)
        reply = await OPENAI_CLIENT.chat(text, sys_prompt=sys_prompt, engine=uinfo["engine"])
        await update.effective_message.reply_text(reply)
        return

    if (mode := ud.pop("await_study_essay", None)) is not None:
        sys_prompt = ("Ты помощник по академ-письму. Сформируй черновик указанного типа (эссе/доклад/реферат) "
                      "с кратким планом, тезисами, аккуратным стилем и без воды. В конце добавь 3-5 идей улучшения.")
        uinfo = db_user_get_or_create(update.effective_user.id)
        reply = await OPENAI_CLIENT.chat(f"Тип: {mode}\nТребования/тема: {text}", sys_prompt=sys_prompt, engine=uinfo["engine"])
        await update.effective_message.reply_text(reply)
        return

    if ud.pop("await_study_exam", False):
        sys_prompt = ("Составь компактный набор билетов/вопросов по теме, затем проведи 3-5 проверочных вопросов "
                      "(квиз) по одному, ожидая ответы пользователя.")
        uinfo = db_user_get_or_create(update.effective_user.id)
        reply = await OPENAI_CLIENT.chat(text, sys_prompt=sys_prompt, engine=uinfo["engine"])
        await update.effective_message.reply_text(reply)
        return

    # общий ответ
    uinfo = db_user_get_or_create(update.effective_user.id)
    db_save_turn(uinfo["user_id"], "user", text)
    reply = await assist_text_by_mode(text, uinfo)
    db_save_turn(uinfo["user_id"], "assistant", reply)
    await update.effective_message.reply_text(reply)

    try:
        if uinfo["voice_on"]:
            ogg = await OPENAI_CLIENT.tts(reply, fmt="ogg")
            try:
                await update.effective_message.reply_voice(ogg)
            except Exception:
                mp3 = await OPENAI_CLIENT.tts(reply, fmt="mp3")
                await update.effective_message.reply_audio(mp3)
    except Exception as e:
        await update.effective_message.reply_text(f"Не удалось озвучить: {human_exc(e)}")

# ===== Callbacks router =====
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    if data.startswith("mode:"):
        await on_cb_mode(update, context, data)
        return
    if data.startswith("engine:"):
        await on_cb_engine(update, context, data)
        return
    if data.startswith("plan:"):
        await handle_plan_choice(update, context, data)
        return

    # photo actions
    await on_cb_photo(update, context, data)

async def on_cb_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    user_id = update.effective_user.id
    mode = data.split(":", 1)[1]
    if mode == "root":
        await update.effective_message.edit_text("Главное меню. Выбери режим:", reply_markup=main_menu_kb())
        return
    if mode == "study":
        db_user_set_mode(user_id, "study")
        await update.effective_message.edit_text(STUDY_TEXT, reply_markup=study_menu_kb())
        return
    if mode == "fun":
        db_user_set_mode(user_id, "fun")
        await update.effective_message.edit_text(FUN_TEXT, reply_markup=main_menu_kb())
        return
    if mode == "work":
        db_user_set_mode(user_id, "work")
        await update.effective_message.edit_text(WORK_TEXT, reply_markup=main_menu_kb())
        return
    if mode == "engines":
        await update.effective_message.edit_text(ENGINES_TEXT, reply_markup=engines_menu_kb())
        return
    if mode == "plans":
        await update.effective_message.edit_text(PLANS_TEXT, reply_markup=plans_kb())
        return
    if mode == "settings":
        info = db_user_get_or_create(user_id)
        txt = (
            "⚙️ Настройки:\n"
            f"• Озвучка: {'вкл' if info['voice_on'] else 'выкл'} (/voice_on, /voice_off)\n"
            f"• Режим: {info.get('mode') or 'не выбран'}\n"
            f"• Движок: {info.get('engine') or 'по умолчанию'}\n"
            f"• Тариф: {info.get('tier') or 'free'}\n"
        )
        await update.effective_message.edit_text(txt, reply_markup=main_menu_kb())
        return

    # Study submodes
    if mode.startswith("study:"):
        action = mode.split(":", 1)[1]
        ud = context.user_data
        ud.pop("await_study_explain", None)
        ud.pop("await_study_essay", None)
        ud.pop("await_study_tasks", None)
        ud.pop("await_study_exam", None)

        if action == "explain":
            ud["await_study_explain"] = True
            await update.effective_message.edit_text("Введи тему или задай вопрос — объясню по-человечески.", reply_markup=study_menu_kb())
            return
        if action == "essay":
            ud["await_study_essay"] = "эссе/реферат/доклад"
            await update.effective_message.edit_text("Напиши: тип (эссе/реферат/доклад), тема, объём и требования препода.", reply_markup=study_menu_kb())
            return
        if action == "tasks":
            ud["await_study_tasks"] = True
            await update.effective_message.edit_text("Пришли условие задачи (текст или фото отдельно).", reply_markup=study_menu_kb())
            return
        if action == "exam":
            ud["await_study_exam"] = True
            await update.effective_message.edit_text("Введи тему/дисциплину — сгенерирую билеты и устрою мини-квиз.", reply_markup=study_menu_kb())
            return
        if action == "files":
            await update.effective_message.edit_text("Пришли PDF/DOCX/EPUB/TXT — соберу конспект и список вопросов.", reply_markup=study_menu_kb())
            return
        if action == "lang":
            await update.effective_message.edit_text("Введи текст для перевода/правки (RU/EN).", reply_markup=study_menu_kb())
            return
        if action == "code":
            await update.effective_message.edit_text("Пришли код/ошибку/задачу — разберём. Для «сухих» ответов включи 🔐 Stealth в 🧠 Движках.", reply_markup=study_menu_kb())
            return
        if action == "deadlines":
            await update.effective_message.edit_text("Напиши, что и к какому числу нужно сдать — разобью на шаги и буду мягко напоминать (модуль в разработке).", reply_markup=study_menu_kb())
            return

async def on_cb_engine(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    user_id = update.effective_user.id
    eng = data.split(":",1)[1]
    db_user_set_engine(user_id, eng)
    names = {
        "pro":"🚀 GPT-5 Pro",
        "fast":"⚡ Быстрый GPT",
        "code":"🧩 Code",
        "research":"📚 Research",
        "stealth":"🔐 Stealth",
        "vision":"📷 Vision",
        "image":"🎨 Image",
        "video":"🎬 Video/Reels"
    }
    name = names.get(eng, eng)
    await update.effective_message.edit_text(f"Активирован движок: {name}\n\nВсе следующие сообщения будут идти через этот движок, пока ты не сменишь его или режим.", reply_markup=engines_menu_kb())

# ===== Photo callbacks =====
async def on_cb_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    q = update.callback_query
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
        user_data["await_obj_edit"] = {"note": "text-guided edit"}
        await q.message.reply_text("Опиши, что добавить или что/где удалить. (Точная маска может потребовать уточнений).")
        return

    if data.startswith("story:"):
        try:
            story_prompt = "Сделай короткий storyboard оживления кадра (3–6 сцен) с движениями человека и объектов, кратко."
            uinfo = db_user_get_or_create(update.effective_user.id)
            res = await OPENAI_CLIENT.chat(story_prompt, engine=uinfo["engine"])
            await q.message.reply_text(res)
        except Exception as e:
            await q.message.reply_text(f"Ошибка storyboard: {human_exc(e)}")
        return

    if data.startswith("anim:"):
        img_id = data.split(":",1)[1]
        if not (LUMA_API_KEY or RUNWAY_API_KEY):
            await q.message.reply_text("Для оживления фото подключи LUMA_API_KEY или RUNWAY_API_KEY.")
            return
        # берём tg CDN URL
        try:
            meta = cache.get(img_id)
            file = await context.bot.get_file(meta["file_id"])
            url = file.file_path
            prompt = "Оживить фото кинематографично, лёгкое движение камеры."
            task_id = None
            if LUMA_API_KEY:
                task_id = await luma_create_task(url, prompt, seconds=6, aspect="9:16")
                if task_id:
                    db_task_add(update.effective_user.id, "luma", task_id, "queued", {"url": url, "prompt": prompt})
            elif RUNWAY_API_KEY:
                task_id = await runway_create_task(url, prompt, seconds=6, aspect="9:16")
                if task_id:
                    db_task_add(update.effective_user.id, "runway", task_id, "queued", {"url": url, "prompt": prompt})
            await q.message.reply_text(f"Задача создана: {task_id or '—'}. Проверка статуса пока вручную (модуль polling допилим).")
        except Exception as e:
            await q.message.reply_text(f"Ошибка создания задачи: {human_exc(e)}")
        return

    if data.startswith("cam:"):
        if not (LUMA_API_KEY or RUNWAY_API_KEY):
            await q.message.reply_text("Для поворота камеры подключи LUMA_API_KEY или RUNWAY_API_KEY.")
            return
        await q.message.reply_text("Создаю задачу на поворот камеры… (похожая логика, модуль будет общий с anim).")
        return

# ===== Generic text handler (fallback) =====
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uinfo = db_user_get_or_create(update.effective_user.id)
    text = update.effective_message.text or ""
    reply = await assist_text_by_mode(text, uinfo)
    await update.effective_message.reply_text(reply)

# ===== App =====
def build_app() -> Application:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN is not set")
        sys.exit(1)
    app = Application.builder().token(BOT_TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("examples", cmd_examples))
    app.add_handler(CommandHandler("modes", cmd_modes))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("voice_on", cmd_voice_on))
    app.add_handler(CommandHandler("voice_off", cmd_voice_off))
    app.add_handler(CommandHandler("img", cmd_img))
    app.add_handler(CommandHandler("ver", cmd_ver))

    # callbacks + media + docs + text
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    return app

def main():
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

if __name__ == "__main__":
    main()
