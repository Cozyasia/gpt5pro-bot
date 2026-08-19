# -*- coding: utf-8 -*-
"""V251: identity-fidelity correction for production AI selfies.

V249/V250 proved the runtime/UX path, but both FaceSwap-v4 and HyperSwap can
synthesize a plausible identity rather than preserve the user's face closely enough.
The last route that consistently preserved identity was the isolated Segmind V2
FaceSwap path; its remaining defect was local softness/pixelation.

V251 therefore freezes the proven UX/composition architecture and changes only the
PERSON-A identity-quality stage:
- Gemini V242 still owns scene, true front-camera framing and source expression;
- V247 still supplies the supersampled isolated PERSON-A target ROI;
- photo #3 is cropped to the verified face before FaceSwap;
- Segmind FaceSwap V2 is restored as the primary identity transfer;
- no HyperSwap or FaceSwap-v4 runs in the V251 production path;
- only source-derived mid/high-frequency facial detail is injected after V2; source
  low-frequency shape/colour is never pasted, so expression/pose remain target-owned;
- V250 face-local merge keeps target hair, body, background and PERSON-B pixels;
- native Gemini 2K output remains lossless after the face merge;
- a -1000003 callback owner executes before V250/V245 so late legacy enforcers cannot
  overwrite V251 at the real generation boundary.

The goal is deliberately narrower than another generative "enhancer": preserve the
recognisable real user first, then recover detail without inventing a new face.
"""
from __future__ import annotations

import contextlib
import io
from typing import Any

VERSION = "v251-v2-identity-source-detail-lock-2026-08-20"
_INSTALLED = False
_BUILDER_HOOKED = False
_BASE_V247_ENFORCE = None
_BASE_TRUE_FACE_TRANSFER = None

_GENERATION_PATTERN = r"^(?:cs201:preset:|cs201:generate_current$|cs201:reuse:repeat$)"
_BUSY_KEY = "_v251_selfie_generation_busy"


def _modules():
    from neyrobot_prod import selfie_v241_authoritative_runtime as v241
    from neyrobot_prod import selfie_v244_runtime_lock as v245
    from neyrobot_prod import selfie_v246_quality_hardlock as v246
    from neyrobot_prod import selfie_v247_provider_supersample as v247
    from neyrobot_prod import selfie_v248_faceswap_v4_quality as v249
    from neyrobot_prod import selfie_v250_hyperswap_identity as v250
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v219_triref_scene_owner as ui
    return v241, v245, v246, v247, v249, v250, transfer, google, ui


def _log(message: str, *args: Any) -> None:
    v241, _, _, _, _, _, _, _, _ = _modules()
    v241._log(message, *args)


def _dims(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(bytes(data or b""))) as im:
            return int(im.width), int(im.height)
    except Exception:
        return 0, 0


def _largest_face_box(image: bytes):
    v241, _, _, _, _, _, _, _, _ = _modules()
    runtime = v241._runtime()
    if runtime is None:
        return None
    faces = v241._detect(runtime, bytes(image or b""))
    if not faces:
        return None
    face = max(faces, key=lambda f: int(f.get("w", 0)) * int(f.get("h", 0)))
    x = int(face.get("x", 0)); y = int(face.get("y", 0))
    w = int(face.get("w", 0)); h = int(face.get("h", 0))
    if w < 64 or h < 64:
        return None
    return x, y, w, h


def _verified_source_face(source: bytes) -> bytes:
    """Close-up source for V2; removes phone/hand/body/background before embedding."""
    v241, _, _, _, _, _, _, _, _ = _modules()
    crop = v241._expression_crop(bytes(source or b""))
    sw, sh = _dims(crop)
    _log(
        "AI_SELFIE_V251_SOURCE_FACE status=verified source_photo=3 dims=%sx%s bytes=%s full_photo_to_provider=false",
        sw, sh, len(crop),
    )
    return crop


def _source_guided_detail(swapped_crop: bytes, source_crop: bytes) -> bytes:
    """Deblock V2 gently and restore only source mid/high-frequency facial detail.

    This intentionally does not paste source RGB/low-frequency geometry. V2 remains
    the identity/pose bridge; source #3 contributes pores, eyelashes, lip edges,
    eyebrow strands and other local detail that provider JPEG/restore can soften.
    """
    from PIL import Image, ImageDraw, ImageFilter
    import numpy as np

    target_raw = bytes(swapped_crop or b"")
    source_raw = bytes(source_crop or b"")
    if len(target_raw) < 1024 or len(source_raw) < 1024:
        return target_raw

    tbox = _largest_face_box(target_raw)
    sbox = _largest_face_box(source_raw)
    if tbox is None or sbox is None:
        _log(
            "AI_SELFIE_V251_DETAIL status=skip reason=face_detection target=%s source=%s",
            bool(tbox), bool(sbox),
        )
        return target_raw

    tim = Image.open(io.BytesIO(target_raw)).convert("RGB")
    sim = Image.open(io.BytesIO(source_raw)).convert("RGB")
    tx, ty, tw0, th0 = tbox
    sx, sy, sw0, sh0 = sbox

    def expanded(x: int, y: int, w: int, h: int, iw: int, ih: int):
        return (
            max(0, int(round(x - w * 0.13))),
            max(0, int(round(y - h * 0.15))),
            min(iw, int(round(x + w * 1.13))),
            min(ih, int(round(y + h * 1.17))),
        )

    tx0, ty0, tx1, ty1 = expanded(tx, ty, tw0, th0, tim.width, tim.height)
    sx0, sy0, sx1, sy1 = expanded(sx, sy, sw0, sh0, sim.width, sim.height)
    pw, ph = tx1 - tx0, ty1 - ty0
    if pw < 128 or ph < 128:
        return target_raw

    target_face = tim.crop((tx0, ty0, tx1, ty1))
    source_face = sim.crop((sx0, sy0, sx1, sy1)).resize((pw, ph), Image.Resampling.LANCZOS)

    # Suppress provider block edges very slightly before adding real source detail.
    target_soft = target_face.filter(ImageFilter.GaussianBlur(radius=0.38))
    tgt = np.asarray(target_face, dtype=np.float32)
    tgt_soft = np.asarray(target_soft, dtype=np.float32)
    tgt_clean = tgt * 0.80 + tgt_soft * 0.20

    # Two source frequency bands. The broad/low-frequency source image is never
    # inserted; this prevents source head shape/lighting from fighting target pose.
    src = np.asarray(source_face, dtype=np.float32)
    fine_blur_radius = max(1.05, min(pw, ph) / 330.0)
    mid_blur_radius = max(2.8, min(pw, ph) / 125.0)
    fine_blur = np.asarray(
        source_face.filter(ImageFilter.GaussianBlur(radius=fine_blur_radius)),
        dtype=np.float32,
    )
    mid_blur = np.asarray(
        source_face.filter(ImageFilter.GaussianBlur(radius=mid_blur_radius)),
        dtype=np.float32,
    )
    fine = src - fine_blur
    mid = fine_blur - mid_blur

    fine_gain = 0.72
    mid_gain = 0.18
    restored = np.clip(tgt_clean + fine * fine_gain + mid * mid_gain, 0, 255).astype(np.uint8)
    restored_im = Image.fromarray(restored, mode="RGB")
    restored_im = restored_im.filter(ImageFilter.UnsharpMask(radius=0.42, percent=34, threshold=3))

    mask = Image.new("L", (pw, ph), 0)
    draw = ImageDraw.Draw(mask)
    inset_x = max(7, int(round(pw * 0.075)))
    inset_y = max(7, int(round(ph * 0.055)))
    draw.ellipse((inset_x, inset_y, pw - inset_x, ph - inset_y), fill=238)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(9.0, min(pw, ph) * 0.045)))
    target_face.paste(restored_im, (0, 0), mask)
    tim.paste(target_face, (tx0, ty0))

    # PNG here prevents another lossy encode before the native face-local merge.
    out = io.BytesIO()
    tim.save(out, format="PNG", optimize=False)
    encoded = out.getvalue()
    _log(
        "AI_SELFIE_V251_DETAIL status=applied target_face=%sx%s source_face=%sx%s fine_gain=%.2f mid_gain=%.2f source_low_frequency=false source_detail=true output=png bytes=%s",
        pw, ph, sx1 - sx0, sy1 - sy0, fine_gain, mid_gain, len(encoded),
    )
    return encoded


async def _segmind_v2_verified_detail(
    target_img: bytes,
    source_face: bytes,
    target_index: int = 0,
    source_index: int = 0,
) -> bytes | None:
    """Call proven Segmind V2 directly, then apply non-generative source detail."""
    v241, _, _, _, _, _, _, _, _ = _modules()
    runtime = v241._runtime()
    if runtime is None or not getattr(runtime, "SEGMIND_API_KEY", ""):
        return None

    try:
        source_crop = _verified_source_face(bytes(source_face or b""))
    except Exception as exc:
        _log(
            "AI_SELFIE_V251_SOURCE_FACE status=failed reason=%s:%s",
            type(exc).__name__, str(exc)[:180],
        )
        return None

    tw, th = _dims(target_img)
    sw, sh = _dims(source_crop)
    url = f"{runtime.SEGMIND_BASE_URL}/v1/faceswap-v2"
    payload = {
        "source_img": runtime._b64_for_faceswap(source_crop),
        "target_img": runtime._b64_for_faceswap(bytes(target_img or b"")),
        "input_faces_index": str(int(target_index)),
        "source_faces_index": str(int(source_index)),
        "face_restore": "codeformer-v0.1.0.pth",
        "base64": False,
    }
    headers = {
        "x-api-key": runtime.SEGMIND_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json,image/*",
    }

    _log(
        "AI_SELFIE_V251_PROVIDER_START provider=segmind_faceswap_v2 source=verified_photo3_face target=v247_supersampled_roi target=%sx%s source=%sx%s restore=codeformer",
        tw, th, sw, sh,
    )
    try:
        timeout_s = max(90.0, float(getattr(runtime, "FACESWAP_TIMEOUT_S", 180) or 180))
        async with runtime.httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                _log(
                    "AI_SELFIE_V251_PROVIDER status=failed reason=http_%s body=%s fallback=piapi",
                    response.status_code,
                    (response.text or "")[:400].replace("\n", " "),
                )
                return None
            image = await runtime._extract_image_bytes_from_json_or_response(response, client)
            if not image:
                _log("AI_SELFIE_V251_PROVIDER status=failed reason=no_output fallback=piapi")
                return None
            image = bytes(image)
            ow, oh = _dims(image)
            _log(
                "AI_SELFIE_V251_PROVIDER_SUCCESS provider=segmind_faceswap_v2 output=%sx%s bytes=%s content_type=%s",
                ow, oh, len(image), response.headers.get("content-type", ""),
            )
            detailed = _source_guided_detail(image, source_crop)
            runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "segmind_faceswap_v2_v251_source_detail"
            return detailed
    except Exception as exc:
        _log(
            "AI_SELFIE_V251_PROVIDER status=failed reason=%s:%s fallback=piapi",
            type(exc).__name__, str(exc)[:240],
        )
        return None


async def _true_face_transfer_with_v251_label(
    runtime: Any,
    stage1: bytes,
    source: bytes,
    source_photo_no: int,
):
    global _BASE_TRUE_FACE_TRANSFER
    if not callable(_BASE_TRUE_FACE_TRANSFER):
        raise RuntimeError("V251 base true-face-transfer function is unavailable")

    runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = ""
    final, legacy_provider = await _BASE_TRUE_FACE_TRANSFER(runtime, stage1, source, source_photo_no)
    actual = str(getattr(runtime, "AI_SELFIE_LAST_FACESWAP_PROVIDER", "") or "")
    if actual == "segmind_faceswap_v2_v251_source_detail":
        provider = "segmind_faceswap_v2_verified_source_detail_isolated"
    else:
        # Original transfer can fall back to PiAPI; preserve that truthful label.
        provider = str(legacy_provider or "")
    _log(
        "AI_SELFIE_V251_TRANSFER_RESULT provider=%s legacy_provider=%s actual_marker=%s",
        provider, legacy_provider, actual or "none",
    )
    return final, provider


def enforce_runtime(bind_generate: bool = True) -> None:
    """Restore frozen V247, then apply V251 provider/detail/merge as last writer."""
    global _BASE_V247_ENFORCE
    v241, v245, v246, v247, v249, v250, transfer, google, ui = _modules()
    if not callable(_BASE_V247_ENFORCE):
        raise RuntimeError("V251 base V247 enforce function was not captured")

    _BASE_V247_ENFORCE(bind_generate=bind_generate)

    runtime = v241._runtime()
    if runtime is not None:
        runtime._segmind_faceswap_v2 = _segmind_v2_verified_detail

    transfer._left_person_crop = v247._provider_supersample_roi
    transfer._merge_left_crop = v250._merge_face_local
    transfer._ensure_full_hd = v246._ensure_full_hd_lossless
    transfer._true_face_transfer = _true_face_transfer_with_v251_label

    # V246's guarded generate re-runs its module-level enforcer immediately before
    # the base generator. Point those late-bound names back to V251 so V247/V250
    # cannot silently replace the provider at the last moment.
    v246.enforce_runtime = enforce_runtime
    v247.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    for mod in (transfer, google, ui, v241, v245, v246, v247, v249, v250):
        mod.VERSION = VERSION

    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v251-front-camera-v2-verified-source-supersampled-source-detail-face-local-native2k"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini V242 expression lock -> V247 supersampled isolated PERSON-A ROI -> "
            "verified photo-3 face crop -> Segmind FaceSwap V2 identity transfer -> "
            "V251 source mid/high-frequency detail only -> V250 face-local merge -> "
            "V246 lossless native-2K final; PiAPI fallback; HyperSwap/V4 disabled"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V251_ENFORCE status=ok base=v247 provider=segmind_faceswap_v2 source=verified_photo3_face target=supersampled<=1440 detail=source_mid_high_only source_low_frequency=false merge=face_local fallback=piapi hyperswap=false v4=false hero=pixel_locked version=%s",
        VERSION,
    )


async def _generation_owner(update: Any, context: Any) -> None:
    """Own generation before V250 (-1000002) and V245 (-1000001)."""
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
        _log("AI_SELFIE_V251_DUPLICATE blocked=true data=%s", data)
        raise ApplicationHandlerStop

    with contextlib.suppress(Exception):
        await query.answer("✅ Принято. Начинаю работу…", show_alert=False)

    runtime = v241_runtime()
    if data.startswith("cs201:preset:"):
        key = data.rsplit(":", 1)[-1]
        preset = base.SCENES.get(key)
        if not preset:
            await query.message.reply_text("Выберите готовую сцену:", reply_markup=v215._preset_keyboard(runtime))
            raise ApplicationHandlerStop
        context.user_data["cs215_scene_mode"] = v215.SCENE_PRESET
        context.user_data["cs215_scene_text"] = v215._clean_preset_scene(preset[1])
        context.user_data.pop("cs215_scene_image", None)
        start_text = "✅ Сцена выбрана. Начинаю создание изображения — это может занять несколько минут."
    elif data in {"cs201:generate_current", "cs201:reuse:repeat"}:
        if not v219._scene_ready(context):
            await query.message.reply_text("Сцена ещё не задана.", reply_markup=v215._scene_source_keyboard(runtime))
            raise ApplicationHandlerStop
        start_text = "✅ Параметры приняты. Начинаю создание изображения — это может занять несколько минут."
    else:
        return

    with contextlib.suppress(Exception):
        await query.message.reply_text(start_text)

    context.user_data[_BUSY_KEY] = True
    previous_v245_busy = bool(context.user_data.get("_v245_selfie_generation_busy"))
    context.user_data["_v245_selfie_generation_busy"] = True
    _log("AI_SELFIE_V251_GENERATION_LOCK state=acquired data=%s", data)
    try:
        enforce_runtime(bind_generate=True)
        _, _, _, _, _, _, transfer, _, _ = _modules()
        scene_text = str(context.user_data.get("cs215_scene_text") or "")
        await transfer.generate(update, context, scene_text)
    finally:
        context.user_data[_BUSY_KEY] = False
        context.user_data["_v245_selfie_generation_busy"] = previous_v245_busy
        _log("AI_SELFIE_V251_GENERATION_LOCK state=released data=%s", data)
    raise ApplicationHandlerStop


def v241_runtime():
    v241, _, _, _, _, _, _, _, _ = _modules()
    return v241._runtime()


def _bind_priority_owner(app: Any) -> None:
    if app is None or getattr(app, "_neyrobot_v251_generation_owner", False):
        return
    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(_generation_owner, pattern=_GENERATION_PATTERN), group=-1000003)
    setattr(app, "_neyrobot_v251_generation_owner", True)
    _log("AI_SELFIE_V251_BIND status=ok group=-1000003 owner=v251 v250_v245_bypassed=true")


def _install_builder_hook() -> None:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return
    from telegram.ext import ApplicationBuilder

    flag = "_neyrobot_v251_final_builder_lock"
    if getattr(ApplicationBuilder, flag, False):
        _BUILDER_HOOKED = True
        return

    previous_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = previous_build(self, *args, **kwargs)
        enforce_runtime(bind_generate=True)
        _bind_priority_owner(app)
        enforce_runtime(bind_generate=True)
        setattr(app, "_neyrobot_v251_final_owner", True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, flag, True)
    _BUILDER_HOOKED = True


def install() -> None:
    global _INSTALLED, _BASE_V247_ENFORCE, _BASE_TRUE_FACE_TRANSFER
    v241, _, _, v247, v249, v250, transfer, _, _ = _modules()

    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    # V249 captured the real V247 enforcer before V4 replaced module bindings.
    base_v247 = getattr(v249, "_BASE_V247_ENFORCE", None)
    if not callable(base_v247):
        raise RuntimeError("V251 could not locate frozen V247 enforcer")
    _BASE_V247_ENFORCE = base_v247

    # V250 captured the original V236 transfer function. Calling it avoids V4 and
    # HyperSwap reporting wrappers while preserving the proven PiAPI fallback.
    base_transfer = getattr(v250, "_BASE_TRUE_FACE_TRANSFER", None)
    if not callable(base_transfer):
        base_transfer = getattr(v249, "_BASE_TRUE_FACE_TRANSFER", None)
    if not callable(base_transfer):
        base_transfer = getattr(transfer, "_true_face_transfer", None)
    _BASE_TRUE_FACE_TRANSFER = base_transfer

    _install_builder_hook()
    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V251 V2 identity + source-detail final owner installed", flush=True)


__all__ = ["VERSION", "install", "enforce_runtime"]
