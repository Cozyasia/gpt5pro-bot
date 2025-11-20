# patch_main.py
# -*- coding: utf-8 -*-
import re, sys, os, shutil, datetime

SRC = "main.py"
DST = "main.fixed.py"

if not os.path.exists(SRC):
    print(f"Не найден {SRC}. Положи сюда свой текущий main.py и запусти снова.")
    sys.exit(1)

ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup = f"main.backup.{ts}.py"
shutil.copyfile(SRC, backup)
print(f"Сделал бэкап: {backup}")

src = open(SRC, "r", encoding="utf-8").read()

def find_funcs(text, name):
    # Захватываем опциональные декораторы, сам def и тело до следующего def/@/EOF
    pat = re.compile(rf"(?ms)^[ \t]*(@[^\n]*\n)*[ \t]*def\s+{name}\s*\([^)]*\)\s*:\s*.*?(?=^[ \t]*(@|def)\s|\Z)")
    return list(pat.finditer(text))

def replace_func(text, name, new_body):
    # Заменяем ВСЕ вхождения функции на один новый вариант (последний по позиции)
    matches = find_funcs(text, name)
    if not matches:
        print(f"⚠️  Не нашёл функцию {name} — пропускаю (оставлю как есть).")
        return text
    # Удаляем все существующие версии и вставляем новую на место ПЕРВОЙ (сохраним порядок)
    first = matches[0]
    start = first.start()
    # Вырезаем все куски:
    cut_idx = []
    for m in matches:
        cut_idx.append((m.start(), m.end()))
    cut_idx.sort()
    new_text = []
    last = 0
    for s,e in cut_idx:
        new_text.append(text[last:s])
        last = e
    new_text.append(text[last:])
    text_no_dupes = "".join(new_text)
    # Вставляем новый код в исходную позицию первой дефиниции
    text_before = text_no_dupes[:start]
    text_after  = text_no_dupes[start:]
    return text_before + new_body.strip() + "\n\n" + text_after

def ensure_runway_guard(text, fname):
    matches = find_funcs(text, fname)
    if not matches:
        print(f"⚠️  {fname} не найден — пропускаю guard.")
        return text
    m = matches[-1]
    block = text[m.start():m.end()]
    if "RUNWAY_API_KEY" in block and "not RUNWAY_API_KEY" in block:
        print(f"✅ В {fname} уже есть проверка RUNWAY_API_KEY.")
        return text
    # Вставим защиту сразу после заголовка def ...:
    header = re.search(r"(?ms)^[ \t]*(@[^\n]*\n)*[ \t]*def\s+" + re.escape(fname) + r"\s*\([^)]*\)\s*:\s*", block)
    if not header:
        print(f"⚠️  Не смог выделить заголовок {fname} — пропускаю guard.")
        return text
    guard = (
        "    # Guard: явная проверка ключа Runway\n"
        "    if not RUNWAY_API_KEY:\n"
        "        await update.effective_message.reply_text(\n"
        "            \"Runway не настроен (нет RUNWAY_API_KEY). Выполни /diag_video и добавь ключ.\"\n"
        "        )\n"
        "        return\n"
    )
    new_block = block[:header.end()] + guard + block[header.end():]
    return text[:m.start()] + new_block + text[m.end():]

# --- Новые устойчивые реализации ---

ON_MODE_TEXT = r'''
async def on_mode_text(update, context):
    raw = (update.effective_message.text or "").strip()
    tl = raw.lower()
    # Схлопываем эмодзи/знаки — оставим буквы/цифры/пробелы
    tl = re.sub(r"[^\w\sёа-я]", " ", tl)

    key = None
    if "учеб" in tl or "учёб" in tl:
        key = "study"
    elif "работ" in tl:
        key = "work"
    elif "развлеч" in tl or "fun" in tl:
        key = "fun"

    if key:
        await _send_mode_menu(update, context, key)
    # иначе молча отдаём событие дальше другим хендлерам
'''.strip()

ON_TEXT = r'''
async def on_text(update, context):
    text = (update.message.text or "").strip()

    # 1) Явные интенты "видео/картинка" — сначала
    mtype, rest = detect_media_intent(text)
    if mtype == "video":
        duration, aspect = parse_video_opts(text)
        prompt = rest or re.sub(r"\b(\d+\s*(?:сек|с)\b|(?:9:16|16:9|1:1|4:5|3:4|4:3))", "", text, flags=re.I).strip(" ,.")
        if not prompt:
            await update.effective_message.reply_text("Опишите, что именно снять, напр.: «ретро-авто на берегу, закат».")
            return
        aid = _new_aid()
        _pending_actions[aid] = {"prompt": prompt, "duration": duration, "aspect": aspect}
        est_luma = 0.40
        est_runway = max(1.0, RUNWAY_UNIT_COST_USD * (duration / max(1, RUNWAY_DURATION_S)))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🎬 Luma (~${est_luma:.2f})",    callback_data=f"choose:luma:{aid}")],
            [InlineKeyboardButton(f"🎥 Runway (~${est_runway:.2f})", callback_data=f"choose:runway:{aid}")],
        ])
        await update.effective_message.reply_text(
            f"Что используем?\nДлительность: {duration} c • Аспект: {aspect}\nЗапрос: «{prompt}»",
            reply_markup=kb
        )
        return

    if mtype == "image":
        prompt = rest or re.sub(r"^(img|image|picture)\s*[:\-]\s*", "", text, flags=re.I).strip()
        if not prompt:
            await update.effective_message.reply_text("Формат: /img <описание изображения>")
            return
        async def _go(): await _do_img_generate(update, context, prompt)
        await _try_pay_then_do(update, context, update.effective_user.id, "img", IMG_COST_USD, _go)
        return

    # 2) Информационные вопросы "а умеешь ли?" — теперь
    cap = capability_answer(text)
    if cap:
        await update.effective_message.reply_text(cap)
        return

    # 3) Обычный текст → LLM
    ok, _, _ = check_text_and_inc(update.effective_user.id, update.effective_user.username or "")
    if not ok:
        await update.effective_message.reply_text("Лимит текстов исчерпан. Оформите ⭐ подписку или попробуйте завтра.")
        return

    user_id = update.effective_user.id
    mode  = _mode_get(user_id)
    track = _mode_track_get(user_id)
    text_for_llm = f"[Режим: {mode}; Подрежим: {track or '-'}]\\n{text}" if mode and mode != "none" else text
    reply = await ask_openai_text(text_for_llm)
    await update.effective_message.reply_text(reply)
    await maybe_tts_reply(update, context, reply[:TTS_MAX_CHARS])
'''.strip()

HANDLE_VOICE = r'''
async def handle_voice(update, context):
    msg = update.effective_message
    voice = getattr(msg, "voice", None) or getattr(msg, "audio", None)
    if not voice:
        await msg.reply_text("Не нашёл голосовой файл.")
        return

    try:
        tg_file = await context.bot.get_file(voice.file_id)
        from io import BytesIO
        buf = BytesIO()
        await tg_file.download_to_memory(out=buf)
        raw = buf.getvalue()
        mime = (getattr(voice, "mime_type", "") or "").lower()
        filename = "voice.ogg" if ("ogg" in mime or "opus" in mime) else ("voice.webm" if "webm" in mime else "voice.mp3")
    except Exception:
        await msg.reply_text("Не удалось скачать голосовое.")
        return

    transcript = await _stt_transcribe_bytes(filename, raw)
    if not transcript:
        await msg.reply_text("Ошибка при распознавании.")
        return

    try:
        await msg.reply_text(f"🗣️ Распознал: {transcript}")
    except Exception:
        pass

    # Проксируем в on_text
    update.message.text = transcript
    await on_text(update, context)
'''.strip()

# Мы НЕ переписываем cmd_start / on_cb_fun / on_btn_plans / _fun_quick_kb содержательно —
# только убираем дубли, оставляя одну (исходную позднюю) версию каждой функции.
dupes = ["cmd_start", "on_cb_fun", "on_btn_plans", "_fun_quick_kb"]

# 1) Дедупликация указанных функций (сохраняем последнюю реализацию)
for name in dupes:
    ms = find_funcs(src, name)
    if len(ms) > 1:
        print(f"🧹 Удаляю дубли {name}: было {len(ms)}")
        # оставим ПОСЛЕДНЮЮ реализацию
        last = ms[-1]
        keep_block = src[last.start():last.end()]
        # вырежем все и вставим keep на место ПЕРВОЙ
        first = ms[0]
        # удалить все
        parts = []
        last_idx = 0
        for m in ms:
            parts.append(src[last_idx:m.start()])
            last_idx = m.end()
        parts.append(src[last_idx:])
        src_no = "".join(parts)
        # вставка
        src = src_no[:first.start()] + keep_block + src_no[first.start():]
        print(f"   → оставил последнюю версию {name}")
    elif len(ms) == 1:
        print(f"✅ Дубликатов {name} нет (1 шт).")
    else:
        print(f"⚠️  {name} не найден — пропускаю.")

# 2) Заменяем реализацию on_mode_text (устойчиво к эмодзи)
src = replace_func(src, "on_mode_text", ON_MODE_TEXT)

# 3) Переписываем on_text и handle_voice под нужную логику
src = replace_func(src, "on_text", ON_TEXT)
src = replace_func(src, "handle_voice", HANDLE_VOICE)

# 4) Добавляем guard в runway-функции (если есть)
src = ensure_runway_guard(src, "_run_runway_animate_photo")
src = ensure_runway_guard(src, "_run_runway_video")

# 5) Готово — записываем в новый файл
open(DST, "w", encoding="utf-8").write(src)
print(f"\n✅ Готово: {DST}\n"
      f"Ничего лишнего не трогал. Если что — есть бэкап {backup}.\n"
      f"Проверь запуск, затем можешь заменить {SRC} на {DST}.")
