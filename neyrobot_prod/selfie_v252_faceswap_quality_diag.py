# -*- coding: utf-8 -*-
"""Wire the photorealistic quality layer into the isolated Face Swap test.

V253 keeps the approved V252 image integration but fixes a misleading failure:
Telegram can accept the result document and still let the client-side upload call
raise telegram.error.TimedOut a few seconds later. That used to be caught by the
outer provider exception handler and produced a red PiAPI/V252 failure message
after a valid result had already been delivered.

Production AI-selfie is patched separately. This diagnostic installer is
idempotent so repeated package imports do not flood Render logs.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v252_faceswap_quality as quality

VERSION = "v253-isolated-quality-delivery-timeout-fix-2026-08-08"
_INSTALLED = False


async def _send_result_document(message: Any, payload: bytes, filename: str, caption: str, trace: str) -> bool:
    try:
        await message.reply_document(
            document=payload,
            filename=filename,
            caption=caption,
            read_timeout=120.0,
            write_timeout=120.0,
            connect_timeout=30.0,
            pool_timeout=30.0,
        )
        diag._log("trace=%s stage=telegram_result_delivery_ok bytes=%s", trace, len(payload))
        return True
    except Exception as exc:
        try:
            from telegram.error import TimedOut
            is_timeout = isinstance(exc, TimedOut)
        except Exception:
            is_timeout = type(exc).__name__ in {"TimedOut", "TimeoutError"}
        if is_timeout:
            diag._log(
                "trace=%s stage=telegram_result_delivery_timeout_ignored bytes=%s error=%r",
                trace, len(payload), str(exc)[:800],
            )
            return True
        raise


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
    diag._log("trace=%s stage=v253_handler_enter key=%s state=%s version=%s", trace, diag._key(update), state, VERSION)

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
        "⏳ Запускаю PiAPI Face Swap + фотографичную интеграцию.\n"
        f"Код теста: {trace}. В Render ищите FACE_SWAP_DIAG и этот код."
    )

    provider_done = False
    try:
        provider_result = await transport.resilient_piapi_single_face_swap(bytes(raw), source, diag._log)
        provider_done = True
        provider_info = diag._describe(provider_result)
        diag._log("trace=%s stage=provider_success result=%r", trace, provider_info)

        polished, stats = quality.integrate_faceswap(bytes(raw), provider_result, diag._log)
        polished_info = diag._describe(polished)
        elapsed = time.monotonic() - started
        diag._log(
            "trace=%s stage=v253_quality_success elapsed=%.2f applied=%s changed_ratio=%.4f bbox=%s polished=%r",
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
        await _send_result_document(message, polished, f"faceswap_v252_{trace}.jpg", caption, trace)
    except Exception as exc:
        elapsed = time.monotonic() - started
        diag._log(
            "trace=%s stage=v253_swap_failed elapsed=%.2f provider_done=%s error_type=%s error=%r",
            trace, elapsed, provider_done, type(exc).__name__, str(exc)[:2600],
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
    global _INSTALLED
    if _INSTALLED or getattr(diag.media, "_v253_quality_diag_owned", False):
        _INSTALLED = True
        return True
    setattr(media, "_v253_quality_diag_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v253_quality_diag_patch status=installed version=%s quality=%s", VERSION, quality.VERSION)
    return True


__all__ = ["VERSION", "media", "install"]
