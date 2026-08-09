# -*- coding: utf-8 -*-
"""V260AM A/B/C isolated Face Swap diagnostic.

A = current PiAPI/Qubico production transport.
B = Replicate ddvinh1/inswapper.
C = Replicate codeplugtech/face-swap.

All three providers receive the same identity-first source crop and the same target
crop. The Telegram test sends the provider RAW outputs without local compositing so
identity transfer can be compared directly. Production AI-selfie is not changed by
this branch.
"""
from __future__ import annotations

import asyncio
import base64
import os
import time
import uuid
from io import BytesIO
from typing import Any

import httpx

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v260am-abc-faceswap-diagnostic-2026-08-10"
_INSTALLED = False

REPLICATE_PREDICTIONS_URL = "https://api.replicate.com/v1/predictions"
REPLICATE_INSWAPPER_VERSION = "ddvinh1/inswapper:25bdae46f2713138640b6e8c04dc4ca18625ce95b1863936b053eee42d9ba6db"
REPLICATE_CODEPLUG_VERSION = "codeplugtech/face-swap:278a81e7ebb22db98bcba54de985d22cc1abeead2754eb1f2af717247be69b34"


def _identity_crop(raw: bytes, *, role: str) -> tuple[Any, fs.FaceTarget, dict[str, float]]:
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
    crop_raw = fs.jpeg(crop, max_side=max_side, quality=96)
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


def _data_url(raw: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(bytes(raw)).decode("ascii")


def _prediction_output_url(payload: dict[str, Any]) -> str:
    output = payload.get("output") if isinstance(payload, dict) else None
    if isinstance(output, str) and output.startswith("http"):
        return output
    if isinstance(output, list):
        for item in output:
            if isinstance(item, str) and item.startswith("http"):
                return item
    if isinstance(output, dict):
        for key in ("url", "image", "image_url", "output_url"):
            value = output.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
    return ""


async def _replicate_swap_once(*, version: str, inputs: dict[str, Any], trace: str, label: str) -> bytes:
    token = str(os.getenv("REPLICATE_API_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN is missing")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "wait=60",
    }
    timeout = httpx.Timeout(connect=30.0, read=75.0, write=75.0, pool=30.0)
    started = time.monotonic()
    diag._log("trace=%s stage=v260am_%s_create version=%s", trace, label, version)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.post(REPLICATE_PREDICTIONS_URL, headers=headers, json={"version": version, "input": inputs})
        response.raise_for_status()
        payload = response.json()
        prediction_id = str(payload.get("id") or "")
        status = str(payload.get("status") or "").lower()
        get_url = str(((payload.get("urls") or {}) if isinstance(payload, dict) else {}).get("get") or "")
        diag._log("trace=%s stage=v260am_%s_created id=%s status=%s", trace, label, prediction_id, status)

        deadline = time.monotonic() + 180.0
        last_status = status
        while status not in {"succeeded", "failed", "canceled"} and time.monotonic() < deadline:
            await asyncio.sleep(2.0)
            if not get_url:
                if not prediction_id:
                    raise RuntimeError(f"Replicate {label} returned no prediction id")
                get_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
            check = await client.get(get_url, headers={"Authorization": f"Bearer {token}"})
            check.raise_for_status()
            payload = check.json()
            status = str(payload.get("status") or "").lower()
            if status != last_status:
                diag._log("trace=%s stage=v260am_%s_poll id=%s status=%s", trace, label, prediction_id, status)
                last_status = status

        if status != "succeeded":
            raise RuntimeError(f"Replicate {label} ended with status={status}: {str(payload.get('error') or '')[:800]}")

        output_url = _prediction_output_url(payload)
        if not output_url:
            raise RuntimeError(f"Replicate {label} succeeded without output URL")
        out = await client.get(output_url)
        out.raise_for_status()
        raw = bytes(out.content)
        if len(raw) < 1024:
            raise RuntimeError(f"Replicate {label} returned empty output")
        diag._log(
            "trace=%s stage=v260am_%s_success elapsed=%.2f dims=%s bytes=%s sha=%s",
            trace, label, time.monotonic() - started, fs.dims(raw), len(raw), fs.sha(raw),
        )
        return raw


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
        diag._log("trace=%s stage=v260am_telegram_delivery_ok file=%s bytes=%s", trace, filename, len(payload))
        return True
    except Exception as exc:
        try:
            from telegram.error import TimedOut
            is_timeout = isinstance(exc, TimedOut)
        except Exception:
            is_timeout = type(exc).__name__ in {"TimedOut", "TimeoutError"}
        if is_timeout:
            diag._log("trace=%s stage=v260am_telegram_delivery_timeout_ignored file=%s bytes=%s", trace, filename, len(payload))
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
    diag._log("trace=%s stage=v260am_handler_enter key=%s state=%s version=%s", trace, diag._key(update), state, VERSION)

    try:
        raw = await diag._download_image_message(message)
    except Exception as exc:
        diag._log("trace=%s stage=v260am_telegram_download_failed state=%s error=%r", trace, state, str(exc)[:1000])
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

    diag._log("trace=%s stage=v260am_input_received role=%s info=%r", trace, state, info)

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
            "trace=%s stage=v260am_source_locked face=%s crop=%s crop_dims=%s metrics=%r",
            trace, source_target.face_box, source_target.crop_box, fs.dims(source_target.crop_raw), source_metrics,
        )
        await message.reply_text(
            "✅ V260AM ABC: фото-источник принято.\n"
            f"Размер: {info['dims']}. Face coverage: {source_metrics['face_w_coverage']:.2f}×{source_metrics['face_h_coverage']:.2f}.\n\n"
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
        _, target_face, target_metrics = _identity_crop(bytes(raw), role="target")
    except Exception as exc:
        await message.reply_text(f"❌ Не удалось надёжно выделить целевое лицо: {type(exc).__name__}: {str(exc)[:220]}")
        raise ApplicationHandlerStop

    session["state"] = "running"
    started = time.monotonic()
    diag._log(
        "trace=%s stage=v260am_abc_start source_full=%r target_full=%r source_crop_dims=%s target_crop_dims=%s source_metrics=%r target_metrics=%r",
        trace, session.get("source_info") or diag._describe(source), info, fs.dims(source_crop), fs.dims(target_face.crop_raw),
        session.get("source_metrics"), target_metrics,
    )
    await message.reply_text(
        "🧪 V260AM ABC: один источник + одна цель → три независимых Face Swap backend.\n"
        "A — PiAPI/Qubico\nB — Replicate InSwapper\nC — Replicate Codeplug Face Swap\n\n"
        "Все результаты RAW, без Gemini и без нашей локальной маски. Сравнивайте именно узнаваемость личности.\n"
        f"Код теста: {trace}."
    )

    results: list[tuple[str, bytes]] = []
    failures: list[str] = []
    try:
        try:
            a = await transport.resilient_piapi_single_face_swap(target_face.crop_raw, source_crop, diag._log)
            results.append(("A_Qubico", a))
            diag._log("trace=%s stage=v260am_A_success dims=%s bytes=%s sha=%s", trace, fs.dims(a), len(a), fs.sha(a))
            await _send_doc(message, a, f"faceswap_v260am_A_qubico_{trace}.jpg", "🅰️ RAW A — текущий PiAPI/Qubico. Без локальной интеграции.", trace)
        except Exception as exc:
            failures.append(f"A/Qubico: {type(exc).__name__}: {str(exc)[:180]}")
            diag._log("trace=%s stage=v260am_A_failed error=%r", trace, str(exc)[:1200])

        token = str(os.getenv("REPLICATE_API_TOKEN") or "").strip()
        if not token:
            failures.append("B/C Replicate: REPLICATE_API_TOKEN отсутствует")
            await message.reply_text("⚠️ A выполнен. B и C пока пропущены: в Render не задан REPLICATE_API_TOKEN.")
        else:
            try:
                b = await _replicate_swap_once(
                    version=REPLICATE_INSWAPPER_VERSION,
                    inputs={
                        "upscale": 1,
                        "source_img": _data_url(source_crop),
                        "target_img": _data_url(target_face.crop_raw),
                        "face_restore": True,
                        "face_upsample": True,
                        "source_indexes": "-1",
                        "target_indexes": "-1",
                        "background_enhance": False,
                        "codeformer_fidelity": 0.9,
                    },
                    trace=trace,
                    label="B_inswapper",
                )
                results.append(("B_InSwapper", b))
                await _send_doc(message, b, f"faceswap_v260am_B_inswapper_{trace}.jpg", "🅱️ RAW B — Replicate InSwapper. Face restore ON, fidelity 0.9; без нашей локальной интеграции.", trace)
            except Exception as exc:
                failures.append(f"B/InSwapper: {type(exc).__name__}: {str(exc)[:180]}")
                diag._log("trace=%s stage=v260am_B_failed error=%r", trace, str(exc)[:1600])

            try:
                c = await _replicate_swap_once(
                    version=REPLICATE_CODEPLUG_VERSION,
                    inputs={
                        "input_image": _data_url(target_face.crop_raw),
                        "swap_image": _data_url(source_crop),
                    },
                    trace=trace,
                    label="C_codeplug",
                )
                results.append(("C_Codeplug", c))
                await _send_doc(message, c, f"faceswap_v260am_C_codeplug_{trace}.jpg", "🅲 RAW C — Replicate Codeplug Face Swap. Без нашей локальной интеграции.", trace)
            except Exception as exc:
                failures.append(f"C/Codeplug: {type(exc).__name__}: {str(exc)[:180]}")
                diag._log("trace=%s stage=v260am_C_failed error=%r", trace, str(exc)[:1600])

        elapsed = time.monotonic() - started
        diag._log("trace=%s stage=v260am_abc_finished elapsed=%.2f ok=%s failures=%r", trace, elapsed, [name for name, _ in results], failures)
        summary = [f"✅ V260AM ABC завершён. Код: {trace}. Время: {elapsed:.1f} сек."]
        summary.append("Получены: " + (", ".join(name for name, _ in results) if results else "нет результатов"))
        if failures:
            summary.append("Ошибки/пропуски:\n• " + "\n• ".join(failures))
        summary.append("Выберите визуально A/B/C по сходству лица с источником; после этого победителя перенесём в production AI-селфи.")
        await message.reply_text("\n\n".join(summary))
    finally:
        diag._reset(update, context)

    raise ApplicationHandlerStop


def install() -> bool:
    global _INSTALLED
    if _INSTALLED or getattr(diag.media, "_v260am_abc_owned", False):
        _INSTALLED = True
        return True
    setattr(media, "_v260am_abc_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v260am_abc_patch status=installed version=%s", VERSION)
    return True


__all__ = ["VERSION", "media", "install"]
