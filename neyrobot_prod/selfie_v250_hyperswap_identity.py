# -*- coding: utf-8 -*-
"""V250: production identity-transfer correction after the V249 FaceSwap-v4 test.

Why this exists:
- V249 proved that the runtime/UX/bootstrap problems were fixed, but Segmind
  FaceSwap-v4 quality produced an uncanny hybrid face for the user.
- FaceSwap-v4 is a generative face/head swap model. For this bot the requirement is
  stricter: transfer the real user identity while preserving target lighting, pose
  and expression, without beautification/redraw.
- Segmind HyperSwap by FaceFusion Labs is explicitly built for identity transfer and
  exposes a high-fidelity hyperswap_1c variant. It is therefore a better production
  fit than V4 for PERSON-A.

V250 keeps every proven V249/V247/V246 invariant:
- photo #3 is the only user identity source;
- Gemini V242 still owns scene/expression composition;
- selfie remains true front-camera output with no visible phone/foreground hand;
- PERSON B is never sent to FaceSwap;
- V247 provider supersampling is restored at the actual generation boundary;
- only the detected PERSON-A face region is merged back; hair/clothes/background are
  preserved from Gemini rather than replacing the whole PERSON-A ROI;
- no source pixels are pasted into the target and there is no generative restoration;
- HyperSwap failure falls back to the proven Segmind V2 provider, not to V4.
"""
from __future__ import annotations

import contextlib
import io
from typing import Any

VERSION = "v250-hyperswap-identity-lock-2026-08-19"
_INSTALLED = False
_BUILDER_HOOKED = False
_BASE_V249_ENFORCE = None
_BASE_V2_PROVIDER = None
_BASE_TRUE_FACE_TRANSFER = None

_GENERATION_PATTERN = r"^(?:cs201:preset:|cs201:generate_current$|cs201:reuse:repeat$)"
_BUSY_KEY = "_v250_selfie_generation_busy"


def _modules():
    from neyrobot_prod import selfie_v241_authoritative_runtime as v241
    from neyrobot_prod import selfie_v244_runtime_lock as v245
    from neyrobot_prod import selfie_v246_quality_hardlock as v246
    from neyrobot_prod import selfie_v247_provider_supersample as v247
    from neyrobot_prod import selfie_v248_faceswap_v4_quality as v249
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v219_triref_scene_owner as ui
    return v241, v245, v246, v247, v249, transfer, google, ui


def _log(message: str, *args: Any) -> None:
    v241, _, _, _, _, _, _, _ = _modules()
    v241._log(message, *args)


def _dims(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(bytes(data or b""))) as im:
            return int(im.width), int(im.height)
    except Exception:
        return 0, 0


def _mark_provider(runtime: Any | None, value: str) -> None:
    if runtime is not None:
        runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = str(value or "")


def _tight_source_face(source: bytes) -> bytes:
    """Use the already-proven verified face crop instead of the whole phone photo."""
    v241, _, _, _, _, _, _, _ = _modules()
    crop = v241._expression_crop(bytes(source or b""))
    sw, sh = _dims(crop)
    _log(
        "AI_SELFIE_V250_SOURCE_FACE crop=verified source_photo=3 dims=%sx%s bytes=%s full_photo_to_provider=false",
        sw, sh, len(crop),
    )
    return crop


async def _segmind_hyperswap_1c(
    target_img: bytes,
    source_face: bytes,
    target_index: int = 0,
    source_index: int = 0,
) -> bytes | None:
    """High-fidelity identity transfer; V2 is the only Segmind fallback."""
    global _BASE_V2_PROVIDER

    v241, _, _, _, _, _, _, _ = _modules()
    runtime = v241._runtime()
    if runtime is None or not getattr(runtime, "SEGMIND_API_KEY", ""):
        _mark_provider(runtime, "segmind_faceswap_v2_fallback")
        if callable(_BASE_V2_PROVIDER):
            return await _BASE_V2_PROVIDER(target_img, source_face, target_index, source_index)
        return None

    try:
        source_crop = _tight_source_face(bytes(source_face or b""))
    except Exception as exc:
        _log("AI_SELFIE_V250_SOURCE_FACE status=fallback_full_source error=%s:%s", type(exc).__name__, str(exc)[:180])
        source_crop = bytes(source_face or b"")

    url = f"{runtime.SEGMIND_BASE_URL}/v1/hyperswap-image-faceswap-by-facefusion-labs"
    payload = {
        "source_image": runtime._b64_for_faceswap(source_crop),
        "target_image": runtime._b64_for_faceswap(bytes(target_img or b"")),
        "model_name": "hyperswap_1c",
        "output_format": "png",
        "output_quality": 100,
    }
    headers = {
        "x-api-key": runtime.SEGMIND_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json,image/*",
    }

    tw, th = _dims(target_img)
    sw, sh = _dims(source_crop)
    _log(
        "AI_SELFIE_V250_PROVIDER_START provider=segmind_hyperswap model=hyperswap_1c target=%sx%s source_face=%sx%s format=png quality=100",
        tw, th, sw, sh,
    )

    try:
        timeout_s = max(120.0, float(getattr(runtime, "FACESWAP_TIMEOUT_S", 180) or 180))
        async with runtime.httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                _log(
                    "AI_SELFIE_V250_PROVIDER status=fallback_v2 reason=http_%s body=%s",
                    response.status_code,
                    (response.text or "")[:400].replace("\n", " "),
                )
                _mark_provider(runtime, "segmind_faceswap_v2_fallback")
                if callable(_BASE_V2_PROVIDER):
                    return await _BASE_V2_PROVIDER(target_img, source_face, target_index, source_index)
                return None

            image = await runtime._extract_image_bytes_from_json_or_response(response, client)
            if not image:
                _log("AI_SELFIE_V250_PROVIDER status=fallback_v2 reason=no_output")
                _mark_provider(runtime, "segmind_faceswap_v2_fallback")
                if callable(_BASE_V2_PROVIDER):
                    return await _BASE_V2_PROVIDER(target_img, source_face, target_index, source_index)
                return None

            image = bytes(image)
            ow, oh = _dims(image)
            _mark_provider(runtime, "segmind_hyperswap_1c")
            _log(
                "AI_SELFIE_V250_PROVIDER_SUCCESS provider=segmind_hyperswap model=hyperswap_1c output=%sx%s bytes=%s content_type=%s fallback=false",
                ow, oh, len(image), response.headers.get("content-type", ""),
            )
            return image
    except Exception as exc:
        _log(
            "AI_SELFIE_V250_PROVIDER status=fallback_v2 reason=%s:%s",
            type(exc).__name__, str(exc)[:240],
        )
        _mark_provider(runtime, "segmind_faceswap_v2_fallback")
        if callable(_BASE_V2_PROVIDER):
            return await _BASE_V2_PROVIDER(target_img, source_face, target_index, source_index)
        return None


def _left_face_box_in_roi(base: bytes, box) -> tuple[int, int, int, int] | None:
    """Detect PERSON-A face inside the native target ROI for a face-local merge."""
    from PIL import Image

    v241, _, _, _, _, _, _, _ = _modules()
    runtime = v241._runtime()
    if runtime is None:
        return None

    im = Image.open(io.BytesIO(bytes(base or b""))).convert("RGB")
    x0, y0, x1, y1 = [int(v) for v in box]
    roi = im.crop((x0, y0, x1, y1))
    out = io.BytesIO()
    roi.save(out, format="JPEG", quality=100, subsampling=0, optimize=True)
    faces = v241._detect(runtime, out.getvalue())
    if not faces:
        return None
    face = max(faces, key=lambda f: int(f.get("w", 0)) * int(f.get("h", 0)))
    x = int(face.get("x", 0)); y = int(face.get("y", 0))
    w = int(face.get("w", 0)); h = int(face.get("h", 0))
    if w < 64 or h < 64:
        return None
    return x, y, w, h


def _merge_face_local(base: bytes, swapped_crop: bytes, box) -> bytes:
    """Merge only the face oval from HyperSwap; keep target hair/body/scene pixels."""
    from PIL import Image, ImageDraw, ImageFilter

    base_im = Image.open(io.BytesIO(bytes(base or b""))).convert("RGB")
    provider = Image.open(io.BytesIO(bytes(swapped_crop or b""))).convert("RGB")
    x0, y0, x1, y1 = [int(v) for v in box]
    cw, ch = x1 - x0, y1 - y0
    provider_size = provider.size
    if provider.size != (cw, ch):
        provider = provider.resize((cw, ch), Image.Resampling.LANCZOS)

    face = _left_face_box_in_roi(bytes(base or b""), box)
    if face is None:
        _, v245, _, _, _, _, _, _ = _modules()
        _log("AI_SELFIE_V250_MERGE mode=fallback_v245 reason=no_face_in_native_roi")
        return v245._merge_clean_face_roi(bytes(base or b""), bytes(swapped_crop or b""), box)

    fx, fy, fw, fh = face
    mx0 = max(0, int(round(fx - fw * 0.14)))
    mx1 = min(cw, int(round(fx + fw * 1.14)))
    my0 = max(0, int(round(fy - fh * 0.10)))
    my1 = min(ch, int(round(fy + fh * 1.20)))

    mask = Image.new("L", (cw, ch), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((mx0, my0, mx1, my1), fill=255)
    feather = max(10.0, min(28.0, min(fw, fh) * 0.045))
    mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))

    native_roi = base_im.crop((x0, y0, x1, y1))
    native_roi.paste(provider, (0, 0), mask)
    base_im.paste(native_roi, (x0, y0))

    out = io.BytesIO()
    base_im.save(out, format="JPEG", quality=100, subsampling=0, optimize=True)
    encoded = out.getvalue()
    _log(
        "AI_SELFIE_V250_MERGE mode=face_local provider=%sx%s roi=%sx%s face=%s,%s,%s,%s mask=%s,%s,%s,%s feather=%.1f target_hair_body_preserved=true source_pixels=false bytes=%s",
        provider_size[0], provider_size[1], cw, ch,
        fx, fy, fw, fh, mx0, my0, mx1, my1, feather, len(encoded),
    )
    return encoded


async def _true_face_transfer_with_actual_provider(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    global _BASE_TRUE_FACE_TRANSFER
    if not callable(_BASE_TRUE_FACE_TRANSFER):
        raise RuntimeError("V250 base true-face-transfer function is unavailable")

    _mark_provider(runtime, "")
    final, legacy_provider = await _BASE_TRUE_FACE_TRANSFER(runtime, stage1, source, source_photo_no)
    actual = str(getattr(runtime, "AI_SELFIE_LAST_FACESWAP_PROVIDER", "") or "")
    if actual == "segmind_hyperswap_1c":
        provider = "segmind_hyperswap_1c_identity_isolated"
    elif actual == "segmind_faceswap_v2_fallback":
        provider = "segmind_faceswap_v2_fallback_isolated"
    else:
        provider = str(legacy_provider or "")
    _log(
        "AI_SELFIE_V250_TRANSFER_RESULT provider=%s legacy_provider=%s actual_marker=%s",
        provider, legacy_provider, actual or "none",
    )
    return final, provider


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V249, then make V250 the final provider/merge/runtime owner."""
    global _BASE_V249_ENFORCE

    v241, v245, v246, v247, v249, transfer, google, ui = _modules()
    if not callable(_BASE_V249_ENFORCE):
        raise RuntimeError("V250 base V249 enforce function was not captured")

    _BASE_V249_ENFORCE(bind_generate=bind_generate)

    runtime = v241._runtime()
    if runtime is not None:
        runtime._segmind_faceswap_v2 = _segmind_hyperswap_1c

    transfer._left_person_crop = v247._provider_supersample_roi
    transfer._merge_left_crop = _merge_face_local
    transfer._ensure_full_hd = v246._ensure_full_hd_lossless
    transfer._true_face_transfer = _true_face_transfer_with_actual_provider

    v247.enforce_runtime = enforce_runtime
    v246.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    for mod in (transfer, google, ui, v241, v245, v246, v247, v249):
        mod.VERSION = VERSION

    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v250-front-camera-hyperswap1c-verified-face-source-supersampled-face-local-native2k"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini V242 expression lock -> V247 supersampled isolated PERSON-A ROI -> "
            "verified photo-3 face crop -> Segmind HyperSwap 1c identity transfer PNG100 -> "
            "V250 face-local target merge -> V246 lossless native-2K final; V2 fallback only"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V250_ENFORCE status=ok provider=segmind_hyperswap model=hyperswap_1c source=verified_photo3_face target=v247_supersampled_roi merge=face_local fallback=v2 v4_production=false hero=pixel_locked final_recompress=false version=%s",
        VERSION,
    )


async def _generation_owner(update: Any, context: Any) -> None:
    """Own generation before V245 (-1000001), so old enforcers cannot overwrite V250."""
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v215_shot_scene_modes as v215
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219

    query = getattr(update, "callback_query", None)
    if query is None:
        return
    data = str(query.data or "")

    if bool(context.user_data.get(_BUSY_KEY)):
        with contextlib.suppress(Exception):
            await query.answer("⏳ Генерация уже запущена. Дождитесь результата.", show_alert=False)
        _log("AI_SELFIE_V250_DUPLICATE blocked=true data=%s", data)
        raise ApplicationHandlerStop

    with contextlib.suppress(Exception):
        await query.answer("✅ Принято. Начинаю работу…", show_alert=False)

    if data.startswith("cs201:preset:"):
        key = data.rsplit(":", 1)[-1]
        preset = base.SCENES.get(key)
        if not preset:
            await query.message.reply_text("Выберите готовую сцену:", reply_markup=v215._preset_keyboard(v241_runtime()))
            raise ApplicationHandlerStop
        context.user_data["cs215_scene_mode"] = v215.SCENE_PRESET
        context.user_data["cs215_scene_text"] = v215._clean_preset_scene(preset[1])
        context.user_data.pop("cs215_scene_image", None)
        start_text = "✅ Сцена выбрана. Начинаю создание изображения — это может занять несколько минут."
    elif data in {"cs201:generate_current", "cs201:reuse:repeat"}:
        if not v219._scene_ready(context):
            await query.message.reply_text("Сцена ещё не задана.", reply_markup=v215._scene_source_keyboard(v241_runtime()))
            raise ApplicationHandlerStop
        start_text = "✅ Параметры приняты. Начинаю создание изображения — это может занять несколько минут."
    else:
        return

    with contextlib.suppress(Exception):
        await query.message.reply_text(start_text)

    context.user_data[_BUSY_KEY] = True
    previous_v245_busy = bool(context.user_data.get("_v245_selfie_generation_busy"))
    context.user_data["_v245_selfie_generation_busy"] = True
    _log("AI_SELFIE_V250_GENERATION_LOCK state=acquired data=%s", data)
    try:
        enforce_runtime(bind_generate=True)
        _, _, _, _, _, transfer, _, _ = _modules()
        scene_text = str(context.user_data.get("cs215_scene_text") or "")
        await transfer.generate(update, context, scene_text)
    finally:
        context.user_data[_BUSY_KEY] = False
        context.user_data["_v245_selfie_generation_busy"] = previous_v245_busy
        _log("AI_SELFIE_V250_GENERATION_LOCK state=released data=%s", data)
    raise ApplicationHandlerStop


def v241_runtime():
    v241, _, _, _, _, _, _, _ = _modules()
    return v241._runtime()


def _bind_priority_owner(app: Any) -> None:
    if app is None or getattr(app, "_neyrobot_v250_generation_owner", False):
        return
    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(_generation_owner, pattern=_GENERATION_PATTERN), group=-1000002)
    setattr(app, "_neyrobot_v250_generation_owner", True)
    _log("AI_SELFIE_V250_BIND status=ok group=-1000002 owner=v250 old_v245_bypassed=true")


def _install_builder_hook() -> None:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return
    from telegram.ext import ApplicationBuilder

    flag = "_neyrobot_v250_final_builder_lock"
    if getattr(ApplicationBuilder, flag, False):
        _BUILDER_HOOKED = True
        return

    previous_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = previous_build(self, *args, **kwargs)
        enforce_runtime(bind_generate=True)
        _bind_priority_owner(app)
        enforce_runtime(bind_generate=True)
        setattr(app, "_neyrobot_v250_final_owner", True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, flag, True)
    _BUILDER_HOOKED = True


def install() -> None:
    global _INSTALLED, _BASE_V249_ENFORCE, _BASE_V2_PROVIDER, _BASE_TRUE_FACE_TRANSFER

    _, _, _, _, v249, transfer, _, _ = _modules()

    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    current = v249.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V249_ENFORCE = current

    v2 = getattr(v249, "_BASE_PROVIDER", None)
    if callable(v2):
        _BASE_V2_PROVIDER = v2

    base_transfer = getattr(v249, "_BASE_TRUE_FACE_TRANSFER", None)
    if not callable(base_transfer):
        base_transfer = getattr(transfer, "_true_face_transfer", None)
    _BASE_TRUE_FACE_TRANSFER = base_transfer

    _install_builder_hook()
    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V250 HyperSwap 1c identity-transfer final owner installed", flush=True)


__all__ = ["VERSION", "install", "enforce_runtime"]
