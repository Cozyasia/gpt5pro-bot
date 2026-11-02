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
new_media = '''    # Acknowledge /start immediately. Uploading a 7 MB video inside the
    # webhook handler can exceed Telegram's request timeout, making Telegram
    # show no response even though the update was claimed. The text/menu is
    # therefore sent synchronously; the intro video is delivered in a tracked
    # background task with a longer upload timeout.
    await update.effective_message.reply_text(
        start_caption,
        reply_markup=main_kb,
        disable_web_page_preview=True,
    )

    async def _deliver_neyronix_intro():
        if not os.path.isfile(welcome_video):
            return
        try:
            with open(welcome_video, "rb") as video_file:
                await update.effective_message.reply_video(
                    video=video_file,
                    caption="🎬 NEYRONIX готов помочь с вашей задачей.",
                    supports_streaming=True,
                    connect_timeout=30,
                    write_timeout=120,
                    read_timeout=120,
                    pool_timeout=30,
                )
            log.info("NEYRONIX_START_VIDEO delivered chat_id=%s", update.effective_chat.id)
        except (TimedOut, asyncio.TimeoutError) as e:
            # Telegram may have accepted the upload even if the client timed
            # out. Never send a fallback after an uncertain video delivery.
            log.warning("NEYRONIX_START_VIDEO outcome_unknown chat_id=%s error=%s", update.effective_chat.id, type(e).__name__)
        except Exception as e:
            log.warning("NEYRONIX_START_VIDEO failed chat_id=%s error_type=%s", update.effective_chat.id, type(e).__name__)
            if os.path.isfile(welcome_image):
                try:
                    with open(welcome_image, "rb") as image_file:
                        await update.effective_message.reply_photo(
                            photo=image_file,
                            caption="🖼 NEYRONIX — текст, документы, фото, видео и нейропродакшен.",
                        )
                except Exception:
                    log.exception("NEYRONIX_START_IMAGE fallback failed")

    context.application.create_task(
        _deliver_neyronix_intro(),
        update=update,
        name="neyronix-start-video",
    )
    # Prevent the legacy synchronous fallback below this block from sending
    # a duplicate welcome message after the immediate acknowledgement.
    welcome_sent = True
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
