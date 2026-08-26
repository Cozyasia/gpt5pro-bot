# -*- coding: utf-8 -*-
"""V261 retouch UX overlay: fresh upload, batch queue and resilient Telegram delivery.

This module deliberately registers no Telegram handlers.  It patches the existing
main.py retouch helpers at Application build time, preserving the established
callback/payment routing while fixing the concrete production failure:
OpenAI image edit succeeded (HTTP 200), then Telegram reply_document timed out and
was incorrectly reported twice as a provider failure.

Behavior:
- each press of the existing work-watermark action starts a fresh upload session;
- the old cached photo is bypassed once, so the callback asks for a new upload;
- the reply keyboard is removed for that upload prompt;
- up to 20 photos/documents can be collected (Telegram albums are supported
  naturally because messages arrive into the same debounced queue);
- jobs are processed strictly sequentially through the existing billing wrapper;
- finished PNGs are returned individually; 2+ results are also offered as one ZIP
  when the archive remains below the safe Telegram document size budget;
- document delivery gets explicit long read/write timeouts and one bounded retry;
- an ambiguous Telegram TimedOut after the result exists is never converted into a
  second "provider returned unsuccessful result" error.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import os
import shutil
import sys
import tempfile
import time
import zipfile
from io import BytesIO
from typing import Any

VERSION = "v261-retouch-batch-resilient-delivery-2026-08-26"
_MAX_BATCH_IMAGES = 20
_BATCH_DEBOUNCE_S = 3.0
_TELEGRAM_SEND_TIMEOUT_S = 180.0
_ZIP_MAX_BYTES = 45 * 1024 * 1024

_INSTALLED = False
_PATCHED_RUNTIME_IDS: set[int] = set()
_BATCH_STATES: dict[int, dict[str, Any]] = {}
_BATCH_TASKS: dict[int, asyncio.Task] = {}
_FORCE_FRESH_UNTIL: dict[int, float] = {}
_REMOVE_KEYBOARD_ONCE = contextvars.ContextVar("retouch_v261_remove_keyboard_once", default=False)
_BATCH_DELIVERY_UID = contextvars.ContextVar("retouch_v261_batch_delivery_uid", default=0)


def _runtime():
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "_start_image_retouch"):
            return mod
    return None


def _safe_uid(update: Any) -> int:
    try:
        return int(update.effective_user.id)
    except Exception:
        return 0


def _cleanup_state(uid: int) -> None:
    uid = int(uid or 0)
    state = _BATCH_STATES.pop(uid, None)
    task = _BATCH_TASKS.pop(uid, None)
    if task is not None and not task.done():
        task.cancel()
    if state:
        tmpdir = str(state.get("tmpdir") or "")
        if tmpdir:
            with contextlib.suppress(Exception):
                shutil.rmtree(tmpdir, ignore_errors=True)
        context = state.get("context")
        if context is not None:
            with contextlib.suppress(Exception):
                context.user_data.pop("_retouch_v261_uid", None)
    _FORCE_FRESH_UNTIL.pop(uid, None)


def _new_state(uid: int, context: Any) -> dict[str, Any]:
    _cleanup_state(uid)
    state = {
        "uid": int(uid),
        "context": context,
        "queue": [],
        "results": [],
        "failed": 0,
        "last_enqueue": time.monotonic(),
        "tmpdir": tempfile.mkdtemp(prefix=f"retouch_v261_{int(uid)}_"),
        "processing": False,
        "announced": False,
        "seq": 0,
    }
    _BATCH_STATES[int(uid)] = state
    with contextlib.suppress(Exception):
        context.user_data["_retouch_v261_uid"] = int(uid)
    return state


def _state_for_context(context: Any) -> dict[str, Any] | None:
    try:
        uid = int(context.user_data.get("_retouch_v261_uid") or 0)
    except Exception:
        uid = 0
    state = _BATCH_STATES.get(uid)
    return state if state is not None and state.get("context") is context else None


async def _send_document_resilient(runtime: Any, update: Any, context: Any, data: bytes, *, filename: str, caption: str) -> bool:
    """Long-timeout Telegram document delivery with one bounded retry.

    Telegram may accept a multi-megabyte file just before the local HTTP client
    reaches its read timeout.  A TimedOut is therefore ambiguous, not proof that the
    image provider or edit failed.
    """
    TimedOut = getattr(runtime, "TimedOut", Exception)
    InputFile = runtime.InputFile

    async def _attempt(attempt: int) -> None:
        bio = BytesIO(bytes(data or b""))
        bio.name = filename
        await update.effective_message.reply_document(
            InputFile(bio),
            caption=caption[:1024],
            read_timeout=_TELEGRAM_SEND_TIMEOUT_S,
            write_timeout=_TELEGRAM_SEND_TIMEOUT_S,
            connect_timeout=30.0,
            pool_timeout=30.0,
        )
        runtime.log.info(
            "RETOUCH_V261_DELIVERY status=success attempt=%s bytes=%s filename=%s",
            attempt, len(data or b""), filename,
        )

    try:
        await _attempt(1)
        return True
    except TimedOut:
        runtime.log.warning(
            "RETOUCH_V261_DELIVERY status=timeout_ambiguous attempt=1 bytes=%s retry=true",
            len(data or b""),
        )
        await asyncio.sleep(1.0)
        try:
            await _attempt(2)
            return True
        except TimedOut:
            # Do not return False here: the production incident proved Telegram can
            # deliver the file even though PTB raises TimedOut. Returning False would
            # make _try_pay_then_do emit a second, incorrect provider-failure message.
            runtime.log.warning(
                "RETOUCH_V261_DELIVERY status=timeout_ambiguous attempt=2 bytes=%s "
                "provider_success=true suppress_false_provider_error=true",
                len(data or b""),
            )
            return True


async def _patched_edit(runtime: Any, update: Any, context: Any, img_bytes: bytes, instruction: str):
    instruction = (
        instruction
        or context.user_data.get("retouch_prompt")
        or "убрать лишнюю надпись/водяной знак и восстановить фон"
    ).strip()
    if not runtime.OPENAI_IMAGE_KEY:
        await update.effective_message.reply_text("❌ Ретушь недоступна: не задан OPENAI_IMAGE_KEY/OPENAI_API_KEY.")
        return False
    if runtime.OPENAI_IMAGE_KEY.startswith("sk-or-"):
        await update.effective_message.reply_text(
            "❌ Для ретуши нужен официальный OpenAI image key. OpenRouter-ключ для image edit не подходит."
        )
        return False

    uid = _safe_uid(update)
    state = _BATCH_STATES.get(uid)
    in_batch = bool(state and state.get("processing"))
    if not in_batch:
        await update.effective_message.reply_text(
            "🧽 Запускаю ретушь собственного изображения. Уберу указанный элемент и естественно восстановлю фон."
        )
    with contextlib.suppress(Exception):
        await context.bot.send_chat_action(update.effective_chat.id, runtime.ChatAction.UPLOAD_PHOTO)

    try:
        out = await runtime._openai_image_edit_bytes(img_bytes, instruction)
        if not out:
            await update.effective_message.reply_text("❌ Не удалось получить результат ретуши.")
            return False

        if state and state.get("tmpdir"):
            result_no = len(state["results"]) + 1
            result_path = os.path.join(state["tmpdir"], f"retouched_{result_no:02d}.png")
            with open(result_path, "wb") as fh:
                fh.write(out)
            state["results"].append(result_path)

        ok = await _send_document_resilient(
            runtime, update, context, out,
            filename="retouched.png",
            caption="✅ Готово: водяной знак/лишний элемент удалён, фон восстановлен.",
        )
        # An ambiguous Telegram timeout is intentionally treated as successful once
        # provider output exists. This prevents the second false error from billing.
        return bool(ok)
    except Exception as exc:
        runtime.log.exception("image retouch error: %s", exc)
        await update.effective_message.reply_text(
            "❌ Не удалось выполнить ретушь изображения. "
            f"Техническая причина: {str(exc)[:500]}"
        )
        return False


async def _send_batch_zip(runtime: Any, state: dict[str, Any]) -> None:
    results = list(state.get("results") or [])
    if len(results) < 2:
        return
    zip_path = os.path.join(state["tmpdir"], "retouched_batch.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for idx, path in enumerate(results, 1):
            if os.path.isfile(path):
                zf.write(path, arcname=f"retouched_{idx:02d}.png")
    size = os.path.getsize(zip_path)
    update = state.get("last_update")
    context = state.get("context")
    if update is None or context is None:
        return
    if size > _ZIP_MAX_BYTES:
        await update.effective_message.reply_text(
            f"✅ Пакет готов: {len(results)} файлов отправлены отдельно. ZIP не прикладываю — он получился больше 45 МБ."
        )
        return
    try:
        with open(zip_path, "rb") as fh:
            payload = fh.read()
        await _send_document_resilient(
            runtime, update, context, payload,
            filename="retouched_batch.zip",
            caption=f"📦 Все готовые изображения одним архивом: {len(results)} шт.",
        )
    except Exception as exc:
        runtime.log.warning("RETOUCH_V261_ZIP status=failed error=%s:%s", type(exc).__name__, str(exc)[:220])


async def _run_batch(runtime: Any, uid: int, original_start: Any) -> None:
    state = _BATCH_STATES.get(int(uid))
    if not state:
        return
    try:
        # Debounce album/several-message uploads into one visible batch.
        while True:
            wait = _BATCH_DEBOUNCE_S - (time.monotonic() - float(state.get("last_enqueue") or 0.0))
            if wait <= 0:
                break
            await asyncio.sleep(min(wait, 0.75))

        state["processing"] = True
        context = state["context"]
        first_update = (state.get("queue") or [{}])[0].get("update") if state.get("queue") else None
        if first_update is not None:
            await first_update.effective_message.reply_text(
                f"🧽 Принято изображений: {len(state['queue'])}. Обрабатываю по очереди; готовые файлы пришлю сюда."
            )
        state["announced"] = True

        processed = 0
        while True:
            queue = state.get("queue") or []
            if processed >= len(queue):
                # Short grace interval catches a late member of a Telegram album.
                await asyncio.sleep(0.8)
                queue = state.get("queue") or []
                if processed >= len(queue):
                    break
            item = queue[processed]
            processed += 1
            state["last_update"] = item["update"]
            try:
                with open(item["path"], "rb") as fh:
                    raw = fh.read()
                token = _BATCH_DELIVERY_UID.set(int(uid))
                try:
                    await original_start(item["update"], context, raw, item["instruction"])
                finally:
                    _BATCH_DELIVERY_UID.reset(token)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state["failed"] = int(state.get("failed") or 0) + 1
                runtime.log.exception("RETOUCH_V261_BATCH item=%s status=failed error=%s", processed, exc)

        await _send_batch_zip(runtime, state)
        last_update = state.get("last_update") or first_update
        if last_update is not None:
            done = len(state.get("results") or [])
            failed = int(state.get("failed") or 0)
            suffix = f" Не удалось обработать: {failed}." if failed else ""
            await last_update.effective_message.reply_text(
                f"✅ Пакетная ретушь завершена. Готово файлов: {done}.{suffix}"
            )
        runtime.log.info(
            "RETOUCH_V261_BATCH status=complete queued=%s results=%s failed=%s sequential=true",
            len(state.get("queue") or []), len(state.get("results") or []), int(state.get("failed") or 0),
        )
    finally:
        _BATCH_TASKS.pop(int(uid), None)
        _cleanup_state(int(uid))


def _patch_runtime(runtime: Any) -> None:
    rid = id(runtime)
    if rid in _PATCHED_RUNTIME_IDS:
        return
    required = (
        "_set_mode_clean", "_get_cached_photo", "_set_waiting_image_retouch",
        "_is_waiting_image_retouch", "_start_image_retouch", "_edit_own_image_retouch",
        "_mode_kb",
    )
    if any(not hasattr(runtime, name) for name in required):
        return

    original_set_mode = runtime._set_mode_clean
    original_get_cached = runtime._get_cached_photo
    original_set_waiting = runtime._set_waiting_image_retouch
    original_is_waiting = runtime._is_waiting_image_retouch
    original_start = runtime._start_image_retouch
    original_mode_kb = runtime._mode_kb

    def _set_mode_clean_v261(uid, mode, submode=""):
        result = original_set_mode(uid, mode, submode)
        uid_i = int(uid or 0)
        if str(submode or "") == "work_watermark":
            _cleanup_state(uid_i)
            _FORCE_FRESH_UNTIL[uid_i] = time.monotonic() + 15.0
        else:
            if uid_i in _BATCH_STATES:
                _cleanup_state(uid_i)
        return result

    def _get_cached_photo_v261(uid):
        uid_i = int(uid or 0)
        until = float(_FORCE_FRESH_UNTIL.get(uid_i) or 0.0)
        if until >= time.monotonic():
            _FORCE_FRESH_UNTIL.pop(uid_i, None)
            runtime.log.info("RETOUCH_V261_FRESH_UPLOAD uid=%s cached_photo_bypassed=true", uid_i)
            return None
        _FORCE_FRESH_UNTIL.pop(uid_i, None)
        return original_get_cached(uid)

    def _set_waiting_v261(update, context, prompt=""):
        result = original_set_waiting(update, context, prompt)
        uid_i = _safe_uid(update)
        _new_state(uid_i, context)
        _REMOVE_KEYBOARD_ONCE.set(True)
        runtime.log.info(
            "RETOUCH_V261_BATCH status=armed uid=%s max_images=%s fresh_upload=true keyboard_removed=true",
            uid_i, _MAX_BATCH_IMAGES,
        )
        return result

    def _is_waiting_v261(context):
        if original_is_waiting(context):
            return True
        return _state_for_context(context) is not None

    def _mode_kb_v261(*args, **kwargs):
        if bool(_REMOVE_KEYBOARD_ONCE.get()):
            _REMOVE_KEYBOARD_ONCE.set(False)
            from telegram import ReplyKeyboardRemove
            return ReplyKeyboardRemove()
        return original_mode_kb(*args, **kwargs)

    async def _start_v261(update, context, img_bytes, instruction):
        uid_i = _safe_uid(update)
        state = _BATCH_STATES.get(uid_i)
        if not state:
            return await original_start(update, context, img_bytes, instruction)
        queue = state["queue"]
        if len(queue) >= _MAX_BATCH_IMAGES:
            await update.effective_message.reply_text(
                f"⚠️ В одном пакете можно обработать до {_MAX_BATCH_IMAGES} изображений. Лишний файл не добавлен."
            )
            return True
        state["seq"] = int(state.get("seq") or 0) + 1
        src_path = os.path.join(state["tmpdir"], f"source_{state['seq']:02d}.bin")
        with open(src_path, "wb") as fh:
            fh.write(bytes(img_bytes or b""))
        queue.append({
            "path": src_path,
            "instruction": (instruction or "убрать водяной знак/надпись/логотип и восстановить фон").strip(),
            "update": update,
        })
        state["last_enqueue"] = time.monotonic()
        state["last_update"] = update
        runtime.log.info(
            "RETOUCH_V261_BATCH status=queued uid=%s index=%s bytes=%s max_images=%s",
            uid_i, len(queue), len(img_bytes or b""), _MAX_BATCH_IMAGES,
        )
        task = _BATCH_TASKS.get(uid_i)
        if task is None or task.done():
            _BATCH_TASKS[uid_i] = asyncio.create_task(_run_batch(runtime, uid_i, original_start))
        return True

    runtime._set_mode_clean = _set_mode_clean_v261
    runtime._get_cached_photo = _get_cached_photo_v261
    runtime._set_waiting_image_retouch = _set_waiting_v261
    runtime._is_waiting_image_retouch = _is_waiting_v261
    runtime._mode_kb = _mode_kb_v261
    runtime._start_image_retouch = _start_v261
    runtime._edit_own_image_retouch = lambda update, context, img_bytes, instruction: _patched_edit(
        runtime, update, context, img_bytes, instruction
    )

    runtime.RETOUCH_BATCH_VERSION = VERSION
    runtime.RETOUCH_BATCH_MAX_IMAGES = _MAX_BATCH_IMAGES
    _PATCHED_RUNTIME_IDS.add(rid)
    runtime.log.info(
        "RETOUCH_V261_INSTALL status=ok fresh_upload=true batch_max=%s sequential=true "
        "zip_limit_mb=45 telegram_timeout=%.0f no_new_handlers=true",
        _MAX_BATCH_IMAGES, _TELEGRAM_SEND_TIMEOUT_S,
    )


def install() -> None:
    """Install one ApplicationBuilder wrapper; no callbacks/handlers are registered."""
    global _INSTALLED
    if _INSTALLED:
        runtime = _runtime()
        if runtime is not None:
            _patch_runtime(runtime)
        return

    from telegram.ext import ApplicationBuilder

    flag = "_neyrobot_retouch_v261_batch_builder_hooked"
    if not getattr(ApplicationBuilder, flag, False):
        original_build = ApplicationBuilder.build

        def _build_with_retouch_v261(self, *args, **kwargs):
            app = original_build(self, *args, **kwargs)
            runtime = _runtime()
            if runtime is not None:
                _patch_runtime(runtime)
            return app

        ApplicationBuilder.build = _build_with_retouch_v261
        setattr(ApplicationBuilder, flag, True)

    _INSTALLED = True
    runtime = _runtime()
    if runtime is not None:
        _patch_runtime(runtime)


__all__ = ["VERSION", "install"]
