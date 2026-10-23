"""Opt-in, priced Veo 8s canary. No paid retries or unsupported durations."""
import os
from pathlib import Path
from uuid import uuid4
from property_video_billing import reserve, record_operation, mark_delivered, refund_before_submission, status
from real_estate_pipeline import fetch_telegram_photos
from neyrobot_prod.veo_google_adapter import GoogleVeoClient, GoogleVeoSubmissionUncertain

async def execute(update, context, state, prompt):
    query = update.callback_query
    if state.get("engine") != "veo" or state.get("duration") != 8:
        await query.message.reply_text("Платная генерация пока доступна только для Google Veo, 8 секунд.")
        return
    if len(state["photos"]) != 1:
        await query.message.reply_text("Для первого реального Veo-ролика загрузите ровно 1 фото. Ваши 9 фото не потеряны; многосценный режим пока не подключён.")
        return
    price = os.getenv("PROPERTY_VIDEO_VEO_PRICE_USD", "").strip()
    key = os.getenv("GEMINI_VIDEO_API_KEY") or os.getenv("GEMINI_API_KEY")
    db = os.getenv("DB_PATH", "subs.db")
    if not price or not key:
        await query.message.reply_text("Veo не настроен: требуется цена и API-ключ. Списаний нет.")
        return
    if state.get("generating"):
        await query.message.reply_text("Генерация уже выполняется.")
        return
    state["generating"] = True
    job = state.setdefault("job_id", uuid4().hex)
    old = status(db, job)
    if old:
        state["generating"] = False
        await query.message.reply_text("Задача уже зарегистрирована (статус: %s). Повторный платный запрос запрещён." % old[0])
        return
    # Fetch the input before reserving credits; this is a no-charge operation.
    folder = Path("/data/real_estate_jobs") / job
    folder.mkdir(parents=True, exist_ok=True)
    try:
        photos = await fetch_telegram_photos(context.bot, state["photos"], str(folder))
    except Exception:
        await query.message.reply_text("Не удалось получить фотографию из Telegram. Средства не списаны.")
        return
    from decimal import Decimal
    try:
        amount = Decimal(price)
        if not amount.is_finite() or amount <= 0:
            raise ValueError("Invalid price")
    except Exception:
        await query.message.reply_text("Стоимость Veo настроена некорректно. Списаний нет.")
        return
    result = reserve(db, job, update.effective_user.id, amount)
    if result == "insufficient":
        await query.message.reply_text(f"Недостаточно кредитов. Стоимость: ${amount:.2f}. Средства не списаны.")
        return
    if result != "reserved":
        await query.message.reply_text("Задача уже учтена. Повторная отправка запрещена.")
        return
    await query.message.reply_text("⏳ Veo: задача принята, ожидаем видео. Повторно не нажимайте.")
    client = GoogleVeoClient(key, base_url=os.getenv("GEMINI_VIDEO_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
                           model=os.getenv("VEO_GOOGLE_MODEL", "veo-3.1-fast-generate-preview"))
    try:
        operation = await client.submit_initial(prompt, reference_image=photos[0], aspect_ratio="9:16")
    except GoogleVeoSubmissionUncertain:
        state["generating"] = False
        await query.message.reply_text("Статус отправки Google неизвестен. Резерв сохранён для сверки, повторная генерация запрещена.")
        return
    except Exception:
        refund_before_submission(db, job)
        state["generating"] = False
        await query.message.reply_text("Google отклонил запрос. Резерв возвращён, если списание не было подтверждено.")
        return
    record_operation(db, job, operation)
    (folder / "operation.txt").write_text(operation, encoding="utf-8")
    try:
        video = await client.poll_bytes(operation)
        target = folder / "result.mp4"
        target.write_bytes(video)
        with target.open("rb") as handle:
            await query.message.reply_video(video=handle, supports_streaming=True)
        mark_delivered(db, job)
        state.clear()
    except Exception:
        await query.message.reply_text("Google принял задачу, но доставка не завершена. Операция сохранена; не запускайте повторно.")
