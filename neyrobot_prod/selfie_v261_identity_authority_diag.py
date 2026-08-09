# -*- coding: utf-8 -*-
"""V261 Identity Authority isolated Face Swap diagnostic.

Compares three parameterizations of the same Replicate InSwapper backend using
exactly the same identity-first source crop and target crop. Production AI-selfie
is not changed here.

A = restore OFF (pure identity transfer)
B = restore ON, CodeFormer fidelity 0.95
C = restore ON, CodeFormer fidelity 0.90 (current V260AM reference)
"""
from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import Any

from telegram.error import TimedOut

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v252_faceswap_quality_diag as v260am
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v261-identity-authority-inswapper-2026-08-10"
_INSTALLED = False


async def _download_with_retry(message: Any, trace: str, attempts: int = 3) -> bytes:
    """Retry Telegram image download on transport timeouts only."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            raw = await diag._download_image_message(message)
            if raw:
                return bytes(raw)
            return b""
        except (TimedOut, TimeoutError) as exc:
            last = exc
            diag._log(
                "trace=%s stage=v261_telegram_download_retry attempt=%s/%s error=%r",
                trace, attempt, attempts, str(exc)[:500],
            )
            if attempt < attempts:
                await asyncio.sleep(1.2 * attempt)
        except Exception:
            raise
    if last is not None:
        raise last
    return b""


def _inswapper_inputs(source_crop: bytes, target_crop: bytes, *, restore: bool, fidelity: float) -> dict[str, Any]:
    return {
        "upscale": 1,
        "source_img": v260am._data_url(source_crop),
        "target_img": v260am._data_url(target_crop),
        "face_restore": bool(restore),
        "face_upsample": bool(restore),
        "source_indexes": "-1",
        "target_indexes": "-1",
        "background_enhance": False,
        "codeformer_fidelity": float(fidelity),
    }


async def media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    session = diag._session(update, context)
    state = str(session.get("state") or "")
    if state not in {"source", "target"}:
        return

    message = getattr(update, "effective_message", None)
    if message is None:
        raise ApplicationHandlerStop

    trace = uuid.uuid4().hex[:12]
    diag._log("trace=%s stage=v261_handler_enter key=%s state=%s version=%s", trace, diag._key(update), state, VERSION)

    try:
        raw = await _download_with_retry(message, trace)
    except Exception as exc:
        diag._log("trace=%s stage=v261_telegram_download_failed state=%s error=%r", trace, state, str(exc)[:1000])
        await message.reply_text(f"❌ Не удалось скачать изображение после повторных попыток: {type(exc).__name__}: {str(exc)[:180]}")
        raise ApplicationHandlerStop

    if len(raw) < 1024:
        await message.reply_text("❌ Не удалось прочитать изображение. Пришлите обычное фото или JPG/PNG-документ.")
        raise ApplicationHandlerStop

    try:
        info = diag._describe(raw)
    except Exception as exc:
        await message.reply_text(f"❌ Файл не открылся как изображение: {type(exc).__name__}: {str(exc)[:180]}")
        raise ApplicationHandlerStop

    diag._log("trace=%s stage=v261_input_received role=%s info=%r", trace, state, info)

    if state == "source":
        try:
            _, source_target, source_metrics = v260am._identity_crop(bytes(raw), role="source")
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
            "trace=%s stage=v261_source_locked face=%s crop=%s crop_dims=%s metrics=%r",
            trace, source_target.face_box, source_target.crop_box, fs.dims(source_target.crop_raw), source_metrics,
        )
        await message.reply_text(
            "✅ V261: фото-источник принято.\n"
            f"Размер: {info['dims']}. Face coverage: {source_metrics['face_w_coverage']:.2f}×{source_metrics['face_h_coverage']:.2f}.\n\n"
            "Шаг 2/2: пришлите ту же целевую фотографию взрослого человека."
        )
        raise ApplicationHandlerStop

    source = bytes(session.get("source") or b"")
    source_crop = bytes(session.get("source_crop") or b"")
    if len(source) < 1024 or len(source_crop) < 1024:
        diag._reset(update, context)
        await message.reply_text("❌ Источник лица потерян. Запустите тест заново.")
        raise ApplicationHandlerStop

    try:
        _, target_face, target_metrics = v260am._identity_crop(bytes(raw), role="target")
    except Exception as exc:
        await message.reply_text(f"❌ Не удалось надёжно выделить целевое лицо: {type(exc).__name__}: {str(exc)[:220]}")
        raise ApplicationHandlerStop

    session["state"] = "running"
    started = time.monotonic()
    diag._log(
        "trace=%s stage=v261_compare_start source_full=%r target_full=%r source_crop_dims=%s target_crop_dims=%s source_metrics=%r target_metrics=%r",
        trace, session.get("source_info") or diag._describe(source), info,
        fs.dims(source_crop), fs.dims(target_face.crop_raw), session.get("source_metrics"), target_metrics,
    )

    await message.reply_text(
        "🧬 V261 Identity Authority: один источник + одна цель → три режима одного InSwapper.\n\n"
        "A — Face Restore OFF\n"
        "B — Face Restore ON, fidelity 0.95\n"
        "C — Face Restore ON, fidelity 0.90\n\n"
        "Все три результата RAW: без Gemini и без нашей локальной маски. Сравнивайте прежде всего форму лица, глаза, нос, рот и общий возраст/узнаваемость.\n"
        f"Код теста: {trace}."
    )

    variants = [
        ("A_restore_off", False, 1.0, "🅰️ RAW A — InSwapper, Face Restore OFF. Максимально чистый перенос identity без CodeFormer."),
        ("B_restore_f095", True, 0.95, "🅱️ RAW B — InSwapper, Face Restore ON, CodeFormer fidelity 0.95."),
        ("C_restore_f090", True, 0.90, "🅲 RAW C — InSwapper, Face Restore ON, CodeFormer fidelity 0.90 (референс V260AM)."),
    ]

    results: list[str] = []
    failures: list[str] = []
    try:
        for label, restore, fidelity, caption in variants:
            try:
                result = await v260am._replicate_swap_once(
                    version=v260am.REPLICATE_INSWAPPER_VERSION,
                    inputs=_inswapper_inputs(source_crop, target_face.crop_raw, restore=restore, fidelity=fidelity),
                    trace=trace,
                    label=f"v261_{label}",
                )
                results.append(label)
                diag._log(
                    "trace=%s stage=v261_variant_success variant=%s restore=%s fidelity=%.2f dims=%s bytes=%s sha=%s",
                    trace, label, restore, fidelity, fs.dims(result), len(result), fs.sha(result),
                )
                await v260am._send_doc(
                    message,
                    result,
                    f"faceswap_v261_{label}_{trace}.jpg",
                    caption,
                    trace,
                )
            except Exception as exc:
                failures.append(f"{label}: {type(exc).__name__}: {str(exc)[:180]}")
                diag._log("trace=%s stage=v261_variant_failed variant=%s error=%r", trace, label, str(exc)[:1600])

        elapsed = time.monotonic() - started
        diag._log("trace=%s stage=v261_finished elapsed=%.2f ok=%s failures=%r", trace, elapsed, results, failures)
        lines = [f"✅ V261 завершён. Код: {trace}. Время: {elapsed:.1f} сек."]
        lines.append("Получены: " + (", ".join(results) if results else "нет результатов"))
        if failures:
            lines.append("Ошибки/пропуски:\n• " + "\n• ".join(failures))
        lines.append(
            "Выберите A/B/C только по сходству с лицом-источником. Победителя затем зафиксируем как production Face Swap для AI-селфи со звездой."
        )
        await message.reply_text("\n\n".join(lines))
    finally:
        diag._reset(update, context)

    raise ApplicationHandlerStop


def install() -> bool:
    global _INSTALLED
    if _INSTALLED or getattr(diag.media, "_v261_identity_authority_owned", False):
        _INSTALLED = True
        return True
    setattr(media, "_v261_identity_authority_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v261_identity_authority_patch status=installed version=%s", VERSION)
    return True


__all__ = ["VERSION", "media", "install"]
