# -*- coding: utf-8 -*-
"""Identity-first isolated Face Swap diagnostic.

V260 keeps the standalone Telegram test, but no longer sends full-frame source and
target images directly to Qubico. Both faces are detected locally, cropped tightly
around the identity region, swapped once through PiAPI, and then the provider result
is composited back into the untouched target with a wider face/jaw/forehead oval.

The raw PiAPI crop is delivered before the final composite. This makes it possible
to distinguish provider identity loss from local integration loss in one test.
"""
from __future__ import annotations

import time
import uuid
from io import BytesIO
from typing import Any

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v260-identity-first-isolated-faceswap-2026-08-09"
_INSTALLED = False


def _identity_crop(raw: bytes, *, role: str) -> tuple[Any, fs.FaceTarget, dict[str, float]]:
    """Return full image + tight authoritative face crop for source or target."""
    detected = fs.source_face_crop(raw, None)
    img = fs.image(raw)
    if role == "source":
        wf, hf, ys = 1.46, 1.62, 0.015
        max_side = 1180
    else:
        wf, hf, ys = 1.68, 1.92, 0.020
        max_side = 1280
    crop_box = fs._expand(detected.face_box, img.size, wf, hf, ys)
    crop = img.crop(crop_box)
    crop_raw = fs.jpeg(crop, max_side=max_side, quality=98)
    fw, fh = detected.face_box[2], detected.face_box[3]
    cw, ch = crop.size
    metrics = {
        "face_w_coverage": fw / float(max(1, cw)),
        "face_h_coverage": fh / float(max(1, ch)),
        "support": float(detected.support),
        "eyes": float(detected.eye_count),
    }
    target = fs.FaceTarget(
        detected.face_box,
        crop_box,
        crop_raw,
        detected.support,
        detected.eye_count,
        detected.score,
    )
    return img, target, metrics


def _identity_first_composite(base_img: Any, target: fs.FaceTarget, provider_raw: bytes) -> bytes:
    """Keep PiAPI authoritative over a wider identity oval; feather only perimeter."""
    from PIL import Image, ImageDraw, ImageFilter

    cl, ct, cr, cb = target.crop_box
    cw, ch = cr - cl, cb - ct
    provider = fs.image(provider_raw).resize((cw, ch), Image.LANCZOS)
    original_crop = base_img.crop(target.crop_box)
    fx, fy, fw, fh = target.face_box
    local_face = (fx - cl, fy - ct, fw, fh)

    # Wider than the V257 scene compositor so temples, forehead, cheeks and jaw
    # remain provider-authoritative. Hair outside this oval stays target-native.
    region = fs._expand(local_face, (cw, ch), 2.10, 2.30, 0.018)
    left, top, right, bottom = region
    rw, rh = right - left, bottom - top
    provider_region = provider.crop(region)
    original_region = original_crop.crop(region)

    mask = Image.new("L", (rw, rh), 0)
    draw = ImageDraw.Draw(mask)
    mx = max(2, int(rw * 0.010))
    my = max(2, int(rh * 0.010))
    draw.ellipse((mx, my, rw - mx, rh - my), fill=255)
    feather = max(2, int(min(rw, rh) * 0.009))
    mask = mask.filter(ImageFilter.GaussianBlur(feather))

    merged_region = Image.composite(provider_region, original_region, mask)
    merged_crop = original_crop.copy()
    merged_crop.paste(merged_region, (left, top))
    output = base_img.copy()
    output.paste(merged_crop, (cl, ct))
    return fs.jpeg(output, max_side=2048, quality=98)


async def _send_doc(message: Any, payload: bytes, filename: str, caption: str, trace: str) -> bool:
    try:
        bio = BytesIO(payload)
        bio.name = filename
        await message.reply_document(
            document=bio,
            filename=filename,
            caption=caption,
            read_timeout=150.0,
            write_timeout=150.0,
            connect_timeout=30.0,
            pool_timeout=30.0,
        )
        diag._log("trace=%s stage=v260_telegram_delivery_ok file=%s bytes=%s", trace, filename, len(payload))
        return True
    except Exception as exc:
        try:
            from telegram.error import TimedOut
            is_timeout = isinstance(exc, TimedOut)
        except Exception:
            is_timeout = type(exc).__name__ in {"TimedOut", "TimeoutError"}
        if is_timeout:
            diag._log("trace=%s stage=v260_telegram_delivery_timeout_ignored file=%s bytes=%s", trace, filename, len(payload))
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
    diag._log("trace=%s stage=v260_handler_enter key=%s state=%s version=%s", trace, diag._key(update), state, VERSION)

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

    diag._log("trace=%s stage=v260_input_received role=%s info=%r", trace, state, info)

    if state == "source":
        try:
            _, source_target, source_metrics = _identity_crop(bytes(raw), role="source")
        except Exception as exc:
            await message.reply_text(f"❌ Не удалось надёжно выделить лицо-источник: {type(exc).__name__}: {str(exc)[:220]}")
            raise ApplicationHandlerStop
        session["source"] = bytes(raw)
        session["source_info"] = info
        session["source_crop"] = source_target.crop_raw
        session["source_metrics"] = source_metrics
        session["state"] = "target"
        context.user_data[diag.SOURCE] = bytes(raw)
        context.user_data[diag.STATE] = "target"
        diag._log(
            "trace=%s stage=v260_source_locked face=%s crop=%s crop_dims=%s metrics=%r",
            trace, source_target.face_box, source_target.crop_box, fs.dims(source_target.crop_raw), source_metrics,
        )
        await message.reply_text(
            "✅ Фото-источник принято и лицо выделено в identity-first crop.\n"
            f"Исходный размер: {info['dims']}. Face coverage: {source_metrics['face_w_coverage']:.2f}×{source_metrics['face_h_coverage']:.2f}.\n\n"
            "Шаг 2/2: пришлите целевую фотографию."
        )
        raise ApplicationHandlerStop

    source = bytes(session.get("source") or b"")
    source_crop = bytes(session.get("source_crop") or b"")
    if len(source) < 1024 or len(source_crop) < 1024:
        diag._reset(update, context)
        await message.reply_text("❌ Источник лица потерян. Запустите тест заново.")
        raise ApplicationHandlerStop

    try:
        target_img, target_face, target_metrics = _identity_crop(bytes(raw), role="target")
    except Exception as exc:
        await message.reply_text(f"❌ Не удалось надёжно выделить целевое лицо: {type(exc).__name__}: {str(exc)[:220]}")
        raise ApplicationHandlerStop

    session["state"] = "running"
    started = time.monotonic()
    diag._log(
        "trace=%s stage=v260_swap_start source_full=%r target_full=%r source_crop_dims=%s target_crop_dims=%s source_metrics=%r target_metrics=%r transport=%s",
        trace, session.get("source_info") or diag._describe(source), info, fs.dims(source_crop), fs.dims(target_face.crop_raw),
        session.get("source_metrics"), target_metrics, transport.resilient_piapi_single_face_swap.__name__,
    )
    await message.reply_text(
        "⏳ V260: запускаю identity-first PiAPI Face Swap.\n"
        "Сначала получите RAW-результат PiAPI, затем финальную интеграцию.\n"
        f"Код теста: {trace}."
    )

    provider_done = False
    try:
        provider_result = await transport.resilient_piapi_single_face_swap(target_face.crop_raw, source_crop, diag._log)
        provider_done = True
        elapsed_provider = time.monotonic() - started
        diag._log(
            "trace=%s stage=v260_provider_success elapsed=%.2f raw_dims=%s raw_bytes=%s raw_sha=%s",
            trace, elapsed_provider, fs.dims(provider_result), len(provider_result), fs.sha(provider_result),
        )

        await _send_doc(
            message,
            provider_result,
            f"faceswap_v260_raw_{trace}.jpg",
            "🧬 V260 RAW PiAPI. Это результат провайдера ДО локальной интеграции. Оценивайте здесь именно сходство личности.",
            trace,
        )

        final = _identity_first_composite(target_img, target_face, provider_result)
        elapsed = time.monotonic() - started
        diag._log(
            "trace=%s stage=v260_final_ready elapsed=%.2f final_dims=%s final_bytes=%s final_sha=%s target_crop=%s",
            trace, elapsed, fs.dims(final), len(final), fs.sha(final), target_face.crop_box,
        )
        await _send_doc(
            message,
            final,
            f"faceswap_v260_final_{trace}.jpg",
            f"✅ V260 Identity-First Face Swap готов. Код: {trace}. Время: {elapsed:.1f} сек. Provider-authoritative область расширена до лба, висков, щёк и линии челюсти; исходный фон/тело сохранены.",
            trace,
        )
    except Exception as exc:
        elapsed = time.monotonic() - started
        diag._log(
            "trace=%s stage=v260_swap_failed elapsed=%.2f provider_done=%s error_type=%s error=%r",
            trace, elapsed, provider_done, type(exc).__name__, str(exc)[:2600],
        )
        await message.reply_text(
            "❌ V260 Face Swap завершился ошибкой.\n"
            f"Код: {trace}\nВремя: {elapsed:.1f} сек.\n"
            f"Причина: {type(exc).__name__}: {str(exc)[:1200]}"
        )
    finally:
        diag._reset(update, context)

    raise ApplicationHandlerStop


def install() -> bool:
    global _INSTALLED
    if _INSTALLED or getattr(diag.media, "_v260_identity_first_owned", False):
        _INSTALLED = True
        return True
    setattr(media, "_v260_identity_first_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v260_identity_first_patch status=installed version=%s", VERSION)
    return True


__all__ = ["VERSION", "media", "install"]
