from pathlib import Path


path = Path("/app/main.py")
source = path.read_text(encoding="utf-8")

old_caption = '''    start_caption = (
        "👋 Привет! Я NEYRONIX — мультимодельный AI-бот в Telegram.\\n\\n"
        "🚀 Помогаю с текстом и голосом, PDF/DOCX, изображениями, "
        "Маркетплейсами, AI-видео, музыкой, live-поиском, "
        "нейропродакшеном и видеообзорами недвижимости.\\n\\n"
        "Выберите направление в меню ниже или просто напишите задачу."
    )'''
new_caption = '''    start_caption = (
        "👋 Добро пожаловать в NEYRONIX.\\n\\n"
        "Это ваша AI-студия в Telegram: выберите режим в меню или "
        "просто пришлите задачу.\\n\\n"
        "🚀 Доступны текст и документы, изображения, Маркетплейсы, "
        "AI-видео, музыка, голос, live-поиск и нейропродакшен.\\n\\n"
        "Выберите направление ниже — я подскажу следующий шаг."
    )'''

old_media = '''    # The branded still is the canonical first-contact card. It is local, so
    # it works even when BANNER_URL is unset or an external host is down.
    if os.path.isfile(welcome_image):
        try:
            with open(welcome_image, "rb") as image_file:
                await update.effective_message.reply_photo(
                    photo=image_file,
                    caption=start_caption,
                    reply_markup=main_kb,
                )
            welcome_sent = True
        except Exception as e:
            log.warning("Branded welcome image failed, trying animated fallback: %s", e)

    if not welcome_sent and os.path.isfile(welcome_video):
        try:
            with open(welcome_video, "rb") as video_file:
                await update.effective_message.reply_video(
                    video=video_file,
                    caption=start_caption,
                    reply_markup=main_kb,
                    supports_streaming=True,
                )
            welcome_sent = True
        except (TimedOut, asyncio.TimeoutError) as e:
            log.warning(
                "Animated welcome delivery outcome unknown; suppressing fallback "
                "to avoid duplicate welcome: %s",
                e,
            )
            return
        except Exception as e:
            log.warning("Animated welcome fallback failed: %s", e)
'''
new_media = '''    # Send exactly one media welcome. The short Telegram profile description
    # is the first contact; this caption continues it instead of repeating it.
    # Prefer the animated NEYRONIX intro, with the local branded card as a
    # deterministic fallback when Telegram rejects or times out the upload.
    if os.path.isfile(welcome_video):
        try:
            with open(welcome_video, "rb") as video_file:
                await update.effective_message.reply_video(
                    video=video_file,
                    caption=start_caption,
                    reply_markup=main_kb,
                    supports_streaming=True,
                )
            welcome_sent = True
        except (TimedOut, asyncio.TimeoutError) as e:
            log.warning(
                "Animated welcome delivery outcome unknown; suppressing fallback "
                "to avoid duplicate welcome: %s",
                e,
            )
            return
        except Exception as e:
            log.warning("Animated welcome failed, trying branded card fallback: %s", e)

    if not welcome_sent and os.path.isfile(welcome_image):
        try:
            with open(welcome_image, "rb") as image_file:
                await update.effective_message.reply_photo(
                    photo=image_file,
                    caption=start_caption,
                    reply_markup=main_kb,
                )
            welcome_sent = True
        except Exception as e:
            log.warning("Branded welcome card failed: %s", e)
'''

if old_caption in source:
    source = source.replace(old_caption, new_caption, 1)
elif new_caption not in source:
    raise SystemExit("NEYRONIX start caption anchor not found")

if old_media in source:
    source = source.replace(old_media, new_media, 1)
elif new_media not in source:
    raise SystemExit("NEYRONIX welcome media anchor not found")

path.write_text(source, encoding="utf-8")
