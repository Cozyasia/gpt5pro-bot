# -*- coding: utf-8 -*-
"""V246: preserve the proven V245 selfie architecture and fix the remaining UX/quality defects.

NON-NEGOTIABLE invariants:
- Gemini V242 composition/expression contract remains unchanged;
- true front-camera selfie framing remains unchanged;
- photo #3 remains the authoritative user identity/expression source;
- isolated real Segmind/PiAPI FaceSwap remains the identity-transfer stage;
- PERSON B / hero pixels are never passed to FaceSwap and remain untouched;
- no second generative face model, no source-texture injection, no redraw.

V246 changes only four boundaries:
1) guaranteed acknowledgement/duplicate guard at the actual generate() boundary;
2) suppress Telegram TimedOut from reaching the legacy generic «Упс…» error UI;
3) preserve FaceSwap pixels losslessly through the final pipeline and apply a
   deterministic target-only micro-detail pass to PERSON A's swapped face;
4) own the final ApplicationBuilder boundary so older V239/V245 builder hooks can
   never be the last writer after the Telegram Application is constructed.
"""
from __future__ import annotations

import contextlib
import io
from typing import Any

from neyrobot_prod import selfie_v241_authoritative_runtime as v241
from neyrobot_prod import selfie_v244_runtime_lock as v245

VERSION = "v246-lossless-target-detail-ux-hardlock-2026-08-19"
_INSTALLED = False
_ERROR_PROCESS_HOOKED = False
_BUILDER_HOOKED = False
_BUSY_KEY = "_v246_selfie_generation_busy"


def _log(message: str, *args: Any) -> None:
    v241._log(message, *args)


def _face_box(image: bytes):
    """Return the largest face in an isolated PERSON-A crop."""
    runtime = v241._runtime()
    faces = v241._detect(runtime, bytes(image or b"")) if runtime is not None else []
    if not faces:
        return None
    face = max(faces, key=lambda f: int(f.get("w", 0)) * int(f.get("h", 0)))
    x = int(face.get("x", 0)); y = int(face.get("y", 0))
    w = int(face.get("w", 0)); h = int(face.get("h", 0))
    if w < 64 or h < 64:
        return None
    return x, y, w, h


def _target_only_detail(swapped_crop: bytes) -> bytes:
    """Sharpen only provider pixels; never mix source photo pixels into the result."""
    from PIL import Image, ImageDraw, ImageFilter

    raw = bytes(swapped_crop or b"")
    if len(raw) < 1024:
        return raw

    box = _face_box(raw)
    if box is None:
        _log("AI_SELFIE_V246_DETAIL status=skip reason=no_face")
        return raw

    im = Image.open(io.BytesIO(raw)).convert("RGB")
    x, y, fw, fh = box
    x0 = max(0, int(round(x - fw * 0.12)))
    x1 = min(im.width, int(round(x + fw * 1.12)))
    y0 = max(0, int(round(y - fh * 0.16)))
    y1 = min(im.height, int(round(y + fh * 1.13)))
    pw, ph = x1 - x0, y1 - y0
    if pw < 96 or ph < 96:
        return raw

    patch = im.crop((x0, y0, x1, y1))
    up = patch.resize((pw * 2, ph * 2), Image.Resampling.LANCZOS)
    up = up.filter(ImageFilter.UnsharpMask(radius=1.15, percent=92, threshold=3))
    up = up.filter(ImageFilter.UnsharpMask(radius=0.42, percent=42, threshold=4))
    restored = up.resize((pw, ph), Image.Resampling.LANCZOS)

    mask = Image.new("L", (pw, ph), 0)
    draw = ImageDraw.Draw(mask)
    ix = max(5, int(pw * 0.06)); iy = max(5, int(ph * 0.05))
    draw.ellipse((ix, iy, pw - ix, ph - iy), fill=242)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(7.0, min(pw, ph) * 0.035)))
    patch.paste(restored, (0, 0), mask)
    im.paste(patch, (x0, y0))

    out = io.BytesIO()
    im.save(out, format="JPEG", quality=100, subsampling=0, optimize=True)
    encoded = out.getvalue()
    _log(
        "AI_SELFIE_V246_DETAIL status=applied face=%s,%s,%s,%s patch=%sx%s method=target_only_lanczos_multiscale source_pixels=false jpeg=100 bytes=%s",
        x, y, fw, fh, pw, ph, len(encoded),
    )
    return encoded


def _merge_lossless(base: bytes, swapped_crop: bytes, box):
    """Use V245's proven isolated merge, but feed it a cleaner target-only face."""
    enhanced = _target_only_detail(bytes(swapped_crop or b""))
    merged = v245._merge_clean_face_roi(bytes(base), enhanced, box)
    _log("AI_SELFIE_V246_MERGE mode=v245_isolated_target_only detail=v246 lossless_next=true")
    return merged


def _ensure_full_hd_lossless(image: bytes) -> bytes:
    """Never re-encode an already-FHD/2K result."""
    from PIL import Image, ImageFilter

    raw = bytes(image or b"")
    with Image.open(io.BytesIO(raw)) as src:
        w, h = int(src.width), int(src.height)
    short_side = min(w, h)
    long_side = max(w, h)
    scale = max(1.0, 1080.0 / max(1, short_side), 1920.0 / max(1, long_side))

    if scale <= 1.0001:
        _log(
            "AI_SELFIE_V246_FULLHD input=%sx%s output=%sx%s scale=1.000 passthrough=true recompress=false bytes=%s",
            w, h, w, h, len(raw),
        )
        return raw

    im = Image.open(io.BytesIO(raw)).convert("RGB")
    nw = max(1080, int(round(w * scale)))
    nh = max(1080, int(round(h * scale)))
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    im = im.filter(ImageFilter.UnsharpMask(radius=0.65, percent=65, threshold=3))
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=100, subsampling=0, optimize=True)
    encoded = out.getvalue()
    _log(
        "AI_SELFIE_V246_FULLHD input=%sx%s output=%sx%s scale=%.3f passthrough=false recompress=required jpeg=100 bytes=%s",
        w, h, nw, nh, scale, len(encoded),
    )
    return encoded


async def _generate_guarded(update: Any, context: Any, scene: str = "") -> bool:
    """Actual generation boundary: immediate feedback and duplicate protection."""
    if bool(context.user_data.get(_BUSY_KEY)):
        query = getattr(update, "callback_query", None)
        if query is not None:
            with contextlib.suppress(Exception):
                await query.answer("⏳ Генерация уже запущена. Дождитесь результата.", show_alert=False)
        message = getattr(update, "effective_message", None)
        if message is not None:
            with contextlib.suppress(Exception):
                await message.reply_text("⏳ Генерация уже выполняется. Повторный запуск не создан.")
        _log("AI_SELFIE_V246_DUPLICATE blocked=true")
        return False

    called_from_v245_owner = bool(context.user_data.get("_v245_selfie_generation_busy"))
    context.user_data[_BUSY_KEY] = True
    try:
        if not called_from_v245_owner:
            message = getattr(update, "effective_message", None)
            if message is not None:
                with contextlib.suppress(Exception):
                    await message.reply_text(
                        "✅ Сцена выбрана. Начинаю создание изображения — это может занять несколько минут."
                    )
            _log("AI_SELFIE_V246_IMMEDIATE_ACK sent=true source=generate_boundary")
        else:
            _log("AI_SELFIE_V246_IMMEDIATE_ACK sent=false reason=v245_owner_already_acknowledged")

        enforce_runtime(bind_generate=True)
        if not callable(v241._BASE_GENERATE):
            raise RuntimeError("V246 base selfie generator is unavailable")
        return await v241._BASE_GENERATE(update, context, scene)
    finally:
        context.user_data[_BUSY_KEY] = False
        _log("AI_SELFIE_V246_GENERATION_LOCK state=released")


def _install_process_error_filter() -> None:
    """Filter Telegram TimedOut before any legacy generic error handler can run."""
    global _ERROR_PROCESS_HOOKED
    if _ERROR_PROCESS_HOOKED:
        return
    from telegram.ext import Application
    from telegram.error import TimedOut

    flag = "_neyrobot_v246_process_error_filtered"
    if getattr(Application, flag, False):
        _ERROR_PROCESS_HOOKED = True
        return

    original = Application.process_error

    async def process_error(self: Any, *args: Any, **kwargs: Any):
        err = kwargs.get("error")
        if err is None and len(args) >= 2:
            err = args[1]
        if isinstance(err, TimedOut):
            _log("AI_SELFIE_V246_TELEGRAM_TIMEOUT suppressed_before_legacy_handler=true error=%s", err)
            return False
        return await original(self, *args, **kwargs)

    Application.process_error = process_error
    setattr(Application, flag, True)
    _ERROR_PROCESS_HOOKED = True


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V245 first, then apply only V246 boundary fixes."""
    from neyrobot_prod import selfie_v219_triref_scene_owner as ui
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    v245.enforce_runtime()

    transfer._merge_left_crop = _merge_lossless
    transfer._ensure_full_hd = _ensure_full_hd_lossless

    if bind_generate:
        transfer.generate = _generate_guarded
        google.generate = _generate_guarded
        ui.generate = _generate_guarded
        with contextlib.suppress(Exception):
            ui.public_callback.__globals__["generate"] = _generate_guarded

    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    transfer.VERSION = VERSION
    google.VERSION = VERSION
    ui.VERSION = VERSION
    v241.VERSION = VERSION
    v245.VERSION = VERSION

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v246-v245-front-camera-expression-real-faceswap-target-only-lossless-final"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini V242 expression lock -> V245 compact isolated real FaceSwap -> "
            "V246 target-only deterministic detail -> lossless native-2K final"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V246_ENFORCE status=ok architecture=v245 expression=v242 faceswap=real detail=target_only source_texture=false final_recompress=false immediate_ack=generate_boundary hero=pixel_locked version=%s",
        VERSION,
    )


def _install_final_builder_hook() -> None:
    """Make V246 the last writer after every older ApplicationBuilder wrapper."""
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return
    from telegram.ext import ApplicationBuilder

    flag = "_neyrobot_v246_final_builder_lock"
    if getattr(ApplicationBuilder, flag, False):
        _BUILDER_HOOKED = True
        return

    previous_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = previous_build(self, *args, **kwargs)
        enforce_runtime(bind_generate=True)
        with contextlib.suppress(Exception):
            v245._bind_priority_generation_owner(app)
        with contextlib.suppress(Exception):
            from neyrobot_prod import selfie_v233_true_face_transfer as transfer
            transfer.bind_application(app)
        enforce_runtime(bind_generate=True)
        setattr(app, "_neyrobot_v246_final_owner", True)
        _log("AI_SELFIE_V246_BIND status=ok final_builder=true priority_owner=true")
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, flag, True)
    _BUILDER_HOOKED = True


def install() -> None:
    global _INSTALLED
    _install_process_error_filter()
    v245.install()
    _install_final_builder_hook()
    enforce_runtime(bind_generate=True)
    if not _INSTALLED:
        _INSTALLED = True
        print("[neyrobot-prod] V246 lossless target-detail UX hard lock installed over V245", flush=True)

    # V247 is a quality-only overlay loaded from the proven V246 owner itself.
    # Keeping the chain here means sitecustomize does not need another callback or
    # builder owner: all V246 UX/runtime locks remain authoritative and V247 only
    # replaces the isolated FaceSwap pixel path.
    try:
        from neyrobot_prod.selfie_v247_provider_supersample import install as install_v247_quality
        install_v247_quality()
    except Exception as exc:
        _log("AI_SELFIE_V247_INSTALL status=failed error=%s:%s", type(exc).__name__, exc)


__all__ = ["VERSION", "install", "enforce_runtime"]
