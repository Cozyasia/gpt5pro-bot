# -*- coding: utf-8 -*-
"""Wire the V252 photorealistic quality layer into the isolated Face Swap test.

This intentionally changes only the diagnostic button flow. Production AI-selfie
remains untouched until the isolated path is visually approved.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v252_faceswap_quality as quality

VERSION = "v252-isolated-quality-diagnostic-2026-08-08"


async def media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import selfie_v243_resilient_piapi_transport as transport

    session = diag._session(update, context)
    state = str(session.get("state") or "")
    if state not in {"source", "target"}:
        return

    message = getattr(update, "effective_message", None)
    if message is None:
        raise ApplicationHandlerStop

    trace = uuid.uuid4().hex[:12]
    diag._log("trace=%s stage=v252_handler_enter key=%s state=%s version=%s", trace, diag._key(update), state, VERSION)

    try:
        raw = await diag._download_image_message(message)
    except Exception as exc:
        diag._log("trace=%s stage=telegram_download_failed state=%s error=%r", trace, state, str(exc)[:1000])
        await message.reply_text(f"❌ Не удалось скачать изображение: {type(exc).__name__}: {str(exc)[:180]}")
        raise ApplicationHandlerStop

    if len(raw) < 1024:
        await message.reply_text("❌ Не удалось прочитать изображение. Пришлите обычное фото или JPG/PNG-документ.")
        raise ApplicationHandlerStop

    try:
        info = diag._describe(raw)
    except Exception as exc:
        await message.reply_text(f"❌ Файл не открылся как изображение: {type(exc).__name__}: {str(exc)[:180]}")
        raise ApplicationHandlerStop

    diag._log("trace=%s stage=input_received role=%s info=%r", trace, state, info)

    if state == "source":
        session["source"] = bytes(raw)
        session["source_info"] = info
        session["state"] = "target"
        context.user_data[diag.SOURCE] = bytes(raw)
        context.user_data[diag.STATE] = "target"
        warning = "" if info["faces"] else "\n⚠️ Локальный OpenCV-детектор лицо не увидел. Это не блокирует прямой PiAPI-тест."
        await message.reply_text(
            "✅ Фото-источник принято.\n"
            f"Размер: {info['dims']}, локально найдено лиц: {info['faces']}."
            f"{warning}\n\nШаг 2/2: пришлите целевую фотографию."
        )
        raise ApplicationHandlerStop

    source = bytes(session.get("source") or b"")
    if len(source) < 1024:
        diag._reset(update, context)
        await message.reply_text("❌ Источник лица потерян. Запустите тест заново.")
        raise ApplicationHandlerStop

    session["state"] = "running"
    source_info = session.get("source_info") or diag._describe(source)
    started = time.monotonic()
    diag._log(
        "trace=%s stage=swap_start source=%r target=%r transport=%s transport_version=%s quality_version=%s",
        trace, source_info, info, transport.resilient_piapi_single_face_swap.__name__,
        getattr(transport, "VERSION", "unknown"), quality.VERSION,
    )
    await message.reply_text(
        "⏳ Запускаю PiAPI Face Swap + V252 фотографичную интеграцию.\n"
        f"Код теста: {trace}. В Render ищите FACE_SWAP_DIAG и этот код."
    )

    try:
        provider_result = await transport.resilient_piapi_single_face_swap(bytes(raw), source, diag._log)
        provider_info = diag._describe(provider_result)
        diag._log("trace=%s stage=provider_success result=%r", trace, provider_info)

        polished, stats = quality.integrate_faceswap(bytes(raw), provider_result, diag._log)
        polished_info = diag._describe(polished)
        elapsed = time.monotonic() - started
        diag._log(
            "trace=%s stage=v252_quality_success elapsed=%.2f applied=%s changed_ratio=%.4f bbox=%s polished=%r",
            trace, elapsed, stats.applied, stats.changed_ratio, stats.bbox, polished_info,
        )

        if stats.applied:
            caption = (
                f"✅ PiAPI Face Swap + V252 интеграция выполнены. Код: {trace}. "
                f"Время: {elapsed:.1f} сек. Маска изменения: {stats.changed_ratio * 100:.1f}%."
            )
        else:
            caption = (
                f"✅ PiAPI Face Swap выполнен. V252 оставил raw-результат без вмешательства "
                f"({stats.reason}). Код: {trace}. Время: {elapsed:.1f} сек."
            )
        await message.reply_document(document=polished, filename=f"faceswap_v252_{trace}.jpg", caption=caption)
    except Exception as exc:
        elapsed = time.monotonic() - started
        diag._log(
            "trace=%s stage=v252_swap_failed elapsed=%.2f error_type=%s error=%r",
            trace, elapsed, type(exc).__name__, str(exc)[:2600],
        )
        await message.reply_text(
            "❌ PiAPI Face Swap/V252 завершился ошибкой.\n"
            f"Код: {trace}\nВремя: {elapsed:.1f} сек.\n"
            f"Причина: {type(exc).__name__}: {str(exc)[:1400]}\n\n"
            "Провайдерский контроль остаётся доступен отдельно:",
            reply_markup=diag._control_keyboard(),
        )
    finally:
        diag._reset(update, context)

    raise ApplicationHandlerStop


def install() -> bool:
    # Must execute before diag.bind_application() on a fresh deploy, so Telegram's
    # MessageHandler receives this function rather than the V250 raw-result handler.
    diag.media = media
    diag._log("stage=v252_quality_diag_patch status=installed version=%s quality=%s", VERSION, quality.VERSION)
    return True


__all__ = ["VERSION", "media", "install"]
