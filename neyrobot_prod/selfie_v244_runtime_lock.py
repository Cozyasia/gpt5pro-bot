# -*- coding: utf-8 -*-
"""V245: clean real-FaceSwap quality + final runtime/UX lock.

This is a deliberately narrow continuation of the proven V244/V243/V242 route.
It does NOT introduce a new generative face pass and does NOT redraw PERSON A.

Changes over V244:
- keep Gemini V242 expression-locked composition and real isolated FaceSwap;
- make the FaceSwap ROI compact enough that Segmind normally returns it at native
  resolution instead of downscaling a ~1900px-tall crop to 1600px and forcing us
  to enlarge it again;
- remove V243's source high-frequency overlay, which can create double contours /
  ghost-like smears when the source and swapped face are not pixel-aligned;
- use only a very mild TARGET-ONLY sharpen after the real FaceSwap result;
- immediately acknowledge scene selection and guard against duplicate taps while
  a generation is already running;
- suppress the misleading global «Упс…» message for transient Telegram TimedOut
  exceptions while still logging them.

PERSON B and the rest of the Gemini scene remain untouched by the FaceSwap merge.
"""
from __future__ import annotations

import contextlib
import io
from typing import Any

from neyrobot_prod import selfie_v241_authoritative_runtime as v241
from neyrobot_prod import selfie_v242_expression_lock as v242
from neyrobot_prod import selfie_v243_face_detail_restore as v243

VERSION = "v245-clean-real-faceswap-ux-lock-2026-08-19"
_INSTALLED = False
_BUILDER_HOOKED = False
_ERROR_HOOKED = False

_GENERATION_PATTERN = r"^(?:cs201:preset:|cs201:generate_current$|cs201:reuse:repeat$)"
_BUSY_KEY = "_v245_selfie_generation_busy"


def _log(message: str, *args: Any) -> None:
    v241._log(message, *args)


def _compact_provider_roi(image: bytes):
    """Crop PERSON A tightly enough to stay below provider's ~1600px long-side cap.

    The previous successful test used a 1002x1892 target. Segmind returned
    847x1600, so the face was later enlarged again. This function targets a
    roughly 1.3-1.5K tall ROI around the already-detected PERSON-A face, which
    preserves more native provider pixels without changing identity or geometry.
    """
    from PIL import Image

    data = bytes(image or b"")
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size
    runtime = v241._runtime()
    faces = v241._detect(runtime, data) if runtime is not None else []

    candidates = []
    for f in faces:
        try:
            x = int(f.get("x", 0)); y = int(f.get("y", 0))
            fw = int(f.get("w", 0)); fh = int(f.get("h", 0))
            cx = x + fw / 2.0
            if fw >= 48 and fh >= 48 and cx < w * 0.55:
                candidates.append((fw * fh, x, y, fw, fh))
        except Exception:
            continue
    if not candidates:
        raise RuntimeError("V245 could not locate PERSON A face for compact FaceSwap ROI")

    _, x, y, fw, fh = max(candidates, key=lambda t: t[0])
    cx = x + fw / 2.0
    cy = y + fh / 2.0

    # Keep enough hair/neck/shoulders for provider context but do not feed a huge
    # crop that Segmind must downscale. Hard long-side ceiling leaves margin below
    # the observed 1600px provider cap.
    roi_w = min(float(int(w * 0.54)), max(720.0, fw * 1.46))
    roi_h = min(1480.0, max(920.0, fh * 1.66))

    x0 = max(0, int(round(cx - roi_w * 0.50)))
    x1 = min(int(w * 0.54), int(round(cx + roi_w * 0.50)))
    y0 = max(0, int(round(cy - roi_h * 0.47)))
    y1 = min(h, int(round(cy + roi_h * 0.53)))

    # Re-center after boundary clipping while respecting PERSON-B firewall.
    want_w = int(round(min(roi_w, w * 0.54)))
    want_h = int(round(min(roi_h, h)))
    if x1 - x0 < want_w:
        if x0 == 0:
            x1 = min(int(w * 0.54), want_w)
        else:
            x0 = max(0, x1 - want_w)
    if y1 - y0 < want_h:
        if y0 == 0:
            y1 = min(h, want_h)
        else:
            y0 = max(0, y1 - want_h)

    if x1 - x0 < 420 or y1 - y0 < 620:
        raise RuntimeError("V245 compact FaceSwap ROI is too small")

    crop = im.crop((x0, y0, x1, y1))
    out = io.BytesIO()
    crop.save(out, format="JPEG", quality=100, subsampling=0, optimize=True)
    encoded = out.getvalue()
    _log(
        "AI_SELFIE_V245_FACE_ROI status=compact_native box=%s,%s,%s,%s face=%s,%s,%s,%s crop=%sx%s base=%sx%s provider_long_side_target<=1480",
        x0, y0, x1, y1, x, y, fw, fh, crop.width, crop.height, w, h,
    )
    return encoded, (x0, y0, x1, y1)


def _merge_clean_face_roi(base: bytes, swapped_crop: bytes, box):
    """Merge the REAL FaceSwap result with no source-image texture injection.

    V243 added high-frequency residuals from photo #3 after FaceSwap. Those
    residuals are useful only under near-perfect pixel alignment; otherwise eyes,
    nose and mouth can show faint doubled/smeared contours. V245 removes that
    cross-image operation completely. The only enhancement is a conservative
    sharpen of the provider's own pixels, so identity/expression remain exactly
    those produced by the real FaceSwap stage.
    """
    from PIL import Image, ImageDraw, ImageFilter

    base_im = Image.open(io.BytesIO(bytes(base))).convert("RGB")
    crop_im = Image.open(io.BytesIO(bytes(swapped_crop))).convert("RGB")
    x0, y0, x1, y1 = box
    cw, ch = x1 - x0, y1 - y0
    provider_size = crop_im.size

    resized = crop_im.size != (cw, ch)
    if resized:
        crop_im = crop_im.resize((cw, ch), Image.Resampling.LANCZOS)

    # Target-only micro-contrast. No source photo is blended into the result.
    crop_im = crop_im.filter(ImageFilter.UnsharpMask(radius=0.42, percent=34, threshold=5))

    feather = max(10, min(24, int(min(cw, ch) * 0.018)))
    mask = Image.new("L", (cw, ch), 0)
    draw = ImageDraw.Draw(mask)
    inset = max(7, feather)
    draw.rectangle((inset, inset, max(inset + 1, cw - inset - 1), max(inset + 1, ch - inset - 1)), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))
    base_im.paste(crop_im, (x0, y0), mask)

    out = io.BytesIO()
    base_im.save(out, format="JPEG", quality=100, subsampling=0, optimize=True)
    encoded = out.getvalue()
    _log(
        "AI_SELFIE_V245_MERGE mode=real_faceswap_target_only provider_crop=%sx%s roi=%sx%s base=%sx%s resized=%s source_texture_injection=false sharpen=0.42/34 feather=%s jpeg=100 bytes=%s",
        provider_size[0], provider_size[1], cw, ch, base_im.width, base_im.height,
        str(resized).lower(), feather, len(encoded),
    )
    return encoded


async def _generation_owner(update: Any, context: Any) -> None:
    """Immediate UX acknowledgement + per-user duplicate-generation guard."""
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    query = getattr(update, "callback_query", None)
    if query is None:
        return
    data = str(query.data or "")

    if bool(context.user_data.get(_BUSY_KEY)):
        with contextlib.suppress(Exception):
            await query.answer("⏳ Генерация уже запущена. Дождитесь результата.", show_alert=False)
        _log("AI_SELFIE_V245_DUPLICATE blocked=true data=%s", data)
        raise ApplicationHandlerStop

    with contextlib.suppress(Exception):
        await query.answer("✅ Принято. Начинаю работу…", show_alert=False)

    if data.startswith("cs201:preset:"):
        key = data.rsplit(":", 1)[-1]
        preset = base.SCENES.get(key)
        if not preset:
            await query.message.reply_text("Выберите готовую сцену:", reply_markup=v215._preset_keyboard(v241._runtime()))
            raise ApplicationHandlerStop
        context.user_data["cs215_scene_mode"] = v215.SCENE_PRESET
        context.user_data["cs215_scene_text"] = v215._clean_preset_scene(preset[1])
        context.user_data.pop("cs215_scene_image", None)
        start_text = "✅ Сцена выбрана. Начинаю создание изображения — это может занять несколько минут."
    elif data in {"cs201:generate_current", "cs201:reuse:repeat"}:
        if not v219._scene_ready(context):
            await query.message.reply_text("Сцена ещё не задана.", reply_markup=v215._scene_source_keyboard(v241._runtime()))
            raise ApplicationHandlerStop
        start_text = "✅ Параметры приняты. Начинаю создание изображения — это может занять несколько минут."
    else:
        return

    # This message is intentionally sent BEFORE payment/provider work so the UI
    # never appears frozen and repeated taps do not launch parallel generations.
    with contextlib.suppress(Exception):
        await query.message.reply_text(start_text)

    context.user_data[_BUSY_KEY] = True
    _log("AI_SELFIE_V245_GENERATION_LOCK state=acquired data=%s", data)
    try:
        enforce_runtime()
        scene_text = str(context.user_data.get("cs215_scene_text") or "")
        await transfer.generate(update, context, scene_text)
    finally:
        context.user_data[_BUSY_KEY] = False
        _log("AI_SELFIE_V245_GENERATION_LOCK state=released data=%s", data)
    raise ApplicationHandlerStop


def _bind_priority_generation_owner(app: Any) -> None:
    """Run before the historical -1000000 generation callback."""
    if app is None or getattr(app, "_neyrobot_v245_generation_owner", False):
        return
    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(_generation_owner, pattern=_GENERATION_PATTERN), group=-1000001)
    setattr(app, "_neyrobot_v245_generation_owner", True)
    _log("AI_SELFIE_V245_BIND status=ok group=-1000001 immediate_ack=true duplicate_guard=true")


def _install_error_filter_hook() -> None:
    """Do not show a scary generic error for a transient Telegram API timeout."""
    global _ERROR_HOOKED
    if _ERROR_HOOKED:
        return
    from telegram.ext import Application
    from telegram.error import TimedOut

    flag = "_neyrobot_v245_timeout_error_filter"
    if getattr(Application, flag, False):
        _ERROR_HOOKED = True
        return

    original = Application.add_error_handler

    def add_error_handler(self: Any, callback: Any, block: bool = True):
        if getattr(callback, "_neyrobot_v245_timeout_filtered", False):
            return original(self, callback, block=block)

        async def filtered(update: Any, context: Any):
            err = getattr(context, "error", None)
            if isinstance(err, TimedOut):
                _log("AI_SELFIE_V245_TELEGRAM_TIMEOUT user_message_suppressed=true error=%s", err)
                return None
            return await callback(update, context)

        setattr(filtered, "_neyrobot_v245_timeout_filtered", True)
        return original(self, filtered, block=block)

    Application.add_error_handler = add_error_handler
    setattr(Application, flag, True)
    _ERROR_HOOKED = True


def enforce_runtime() -> None:
    """Reassert proven V243/V242 ownership, then apply V245 quality-only overrides."""
    from neyrobot_prod import selfie_v219_triref_scene_owner as ui
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer

    v243.VERSION = VERSION
    v242.VERSION = VERSION
    v241.VERSION = VERSION
    v243.enforce_runtime()

    # V245 quality correction: still the same real FaceSwap, just a tighter native
    # provider crop and target-only merge. No second model and no face redraw.
    transfer._left_person_crop = _compact_provider_roi
    transfer._merge_left_crop = _merge_clean_face_roi

    # Rebind guarded runtime so later old enforcers cannot take ownership back.
    v241.enforce_runtime = enforce_runtime
    v242.enforce_runtime = enforce_runtime

    transfer.VERSION = VERSION
    google.VERSION = VERSION
    ui.VERSION = VERSION
    v241.VERSION = VERSION
    v242.VERSION = VERSION
    v243.VERSION = VERSION

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v245-v244-lock-v242-expression-compact-native-real-faceswap-target-only-clean-merge"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini V242 expression-locked composition -> compact native-resolution isolated real FaceSwap -> "
            "target-only clean merge (no source texture overlay) -> final runtime lock"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V245_ENFORCE status=ok expression=v242 faceswap=real roi=compact_native detail=target_only source_texture_injection=false hero=pixel_locked version=%s",
        VERSION,
    )


def _install_final_builder_hook() -> None:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return
    from telegram.ext import ApplicationBuilder

    flag = "_neyrobot_v245_final_runtime_lock_hooked"
    if getattr(ApplicationBuilder, flag, False):
        _BUILDER_HOOKED = True
        return

    previous_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = previous_build(self, *args, **kwargs)
        enforce_runtime()
        _bind_priority_generation_owner(app)
        with contextlib.suppress(Exception):
            from neyrobot_prod import selfie_v233_true_face_transfer as transfer
            transfer.bind_application(app)
        enforce_runtime()
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, flag, True)
    _BUILDER_HOOKED = True


def install() -> None:
    global _INSTALLED

    # Must be installed before main.py registers its global error handler.
    _install_error_filter_hook()

    # Initialize the exact proven V243/V242/real-FaceSwap plumbing first.
    v243.install()
    _install_final_builder_hook()
    enforce_runtime()

    if not _INSTALLED:
        _INSTALLED = True
        print("[neyrobot-prod] V245 clean real-FaceSwap quality/UX lock installed over V244/V243", flush=True)


__all__ = ["VERSION", "install", "enforce_runtime"]
