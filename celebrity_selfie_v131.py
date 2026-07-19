# -*- coding: utf-8 -*-
"""Celebrity Selfie v131: tolerant preflight for normal user photos.

v130 treated a zero result from the legacy local face detector as proof that an
image contained no face. That detector is useful for hints, but it produces
false negatives on common half-body and environmental portraits. v131 keeps
resolution/brightness/contrast/sharpness checks strict while making local face
count advisory by default. The paid PiAPI identity-lock provider remains
mandatory and still fails closed on provider errors.
"""
from __future__ import annotations

import logging
from typing import Any

import celebrity_selfie_v130_runtime as previous

impl = previous.impl
core = impl.core
engine = impl.engine

VERSION = "v131-celebrity-selfie-tolerant-face-preflight-2026-07-19"
log = logging.getLogger("gpt-bot.celebrity-selfie-v131")

# The historical routing chain compares session owner against module-level
# VERSION values. Keep the complete live chain on one release identifier.
for _module in (
    previous,
    impl,
    impl.previous,
    impl.previous.previous,
    impl.previous.previous.previous,
    impl.previous.previous.previous.previous,
    core,
):
    try:
        _module.VERSION = VERSION
    except Exception:
        pass


async def _accept_user_photo(update: Any, context: Any, raw: bytes) -> None:
    """Accept ordinary clear portraits even when the local detector misses.

    Hard rejection is based on measurable image quality. Face-count output is
    stored for diagnostics and becomes a hard gate only when the optional
    CELEBRITY_FACE_DETECTOR_STRICT=1 flag is explicitly enabled.
    """
    try:
        normalized = impl._jpeg(raw, max_side=1900)
        metrics = impl._quality_metrics(normalized)
        problem = impl._quality_problem(metrics)
        count = await impl._face_count(normalized)
    except Exception as exc:
        log.warning("Selfie preflight failed: %s", exc)
        normalized = b""
        metrics = {}
        count = None
        problem = "файл изображения повреждён или не поддерживается"

    strict_detector = impl._flag("CELEBRITY_FACE_DETECTOR_STRICT", False)
    detector_warning = ""
    if count == 0:
        detector_warning = "local_detector_miss"
        if strict_detector and not problem:
            problem = "лицо не распознано"
    elif count is not None and count > 1:
        detector_warning = "multiple_faces_detected"
        if strict_detector and not problem:
            problem = "на фотографии должно быть только одно лицо"

    if problem:
        session = core._session(context)
        session["owner"] = VERSION
        session["state"] = "await_user_photo"
        session["selfie_quality"] = {
            **metrics,
            "accepted": False,
            "reason": problem,
            "detector_faces": count,
            "detector_strict": strict_detector,
        }
        await update.effective_message.reply_text(
            "❌ Это фото пока не подходит: " + problem + ".\n\n"
            "Пришлите изображение большего размера, без сильного смаза, полной темноты "
            "или пересвета. Обычные поясные и ростовые фотографии принимаются.",
            reply_markup=core._photo_choice_kb(False),
        )
        return

    session = core._session(context)
    session["selfie_quality"] = {
        **metrics,
        "accepted": True,
        "detector_faces": count,
        "detector_warning": detector_warning,
        "detector_strict": strict_detector,
        "gate": "image_quality_hard_face_detector_advisory",
    }
    if detector_warning:
        log.info(
            "Celebrity selfie accepted despite advisory detector result=%s user=%s",
            detector_warning,
            getattr(getattr(update, "effective_user", None), "id", None),
        )
    await impl._ORIGINAL_ACCEPT_USER_PHOTO(update, context, normalized)


async def _identity_lock(mod: Any, user_photo: bytes, celebrity_ref: bytes, target: bytes) -> bytes:
    """Trust a successful provider result; local face count is diagnostic only.

    The specialized PiAPI multi-face task remains mandatory. A provider error,
    timeout or empty output still fails closed. Only the unreliable local
    post-check is softened unless strict mode is explicitly requested.
    """
    source = impl._source_pair(user_photo, celebrity_ref)
    target = impl._jpeg(target, max_side=1900, quality=95)
    locked = await impl._piapi_task(
        mod,
        "multi-face-swap",
        {
            "swap_image": impl._b64(source),
            "target_image": impl._b64(target),
            "swap_faces_index": "0,1",
            "target_faces_index": "0,1",
        },
    )
    count = await impl._face_count(locked)
    strict_detector = impl._flag("CELEBRITY_FACE_DETECTOR_STRICT", False)
    if strict_detector and count is not None and count < 2:
        raise RuntimeError("Проверка результата не нашла два уверенных лица")
    if count is not None and count < 2:
        log.warning(
            "Identity-lock provider succeeded, but advisory local detector found %s face(s); result retained",
            count,
        )
    return locked


core._accept_user_photo = _accept_user_photo
impl._identity_lock = _identity_lock

# Reuse the already audited single-owner handler installer. The installer reads
# impl.VERSION dynamically, so diagnostics and sessions report v131.
install_builder_hook = impl.install_builder_hook

__all__ = ["VERSION", "install_builder_hook", "_accept_user_photo", "_identity_lock"]
