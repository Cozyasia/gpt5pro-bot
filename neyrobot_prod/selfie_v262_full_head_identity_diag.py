# -*- coding: utf-8 -*-
"""V262 Full-Head Identity Authority diagnostic.

Purpose: test whether the V261-winning InSwapper configuration can stop looking
like a hybrid when the source identity is allowed to control not only the inner
face, but also the forehead, temples, hairline, cheeks and jaw contour.

A = V261 winner baseline: InSwapper + Face Restore ON, fidelity 0.95, integrated
    with the existing face-centric edge composite.
B = A + medium full-head source authority.
C = A + strong full-head source authority (identity core is nearly literal).

This module only replaces the isolated Face Swap diagnostic handler. Production
AI-selfie remains untouched until the visual test is accepted.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from io import BytesIO
from typing import Any

from telegram.error import TimedOut

from neyrobot_prod import selfie_v246_faceswap_diagnostic as diag
from neyrobot_prod import selfie_v252_faceswap_quality_diag as v260am
from neyrobot_prod import selfie_v261_identity_authority_diag as v261
from neyrobot_prod import face_swap_service_v257 as fs

VERSION = "v262-full-head-identity-authority-2026-08-10"
_INSTALLED = False


def _head_box(face_box: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Expand a detected face to an identity-bearing head region.

    The negative y shift deliberately reaches above the forehead into the
    hairline while keeping the lower edge around the jaw/upper neck.
    """
    return fs._expand(face_box, size, 1.56, 2.08, -0.105)


def _color_match(source: Any, reference: Any, amount: float = 0.72) -> Any:
    """Match broad lighting/color statistics without rebuilding facial detail."""
    import numpy as np  # type: ignore
    from PIL import Image

    src = np.asarray(source.convert("RGB"), dtype=np.float32)
    ref = np.asarray(reference.convert("RGB"), dtype=np.float32)
    out = src.copy()
    for channel in range(3):
        s = src[:, :, channel]
        r = ref[:, :, channel]
        sm, ss = float(s.mean()), float(s.std())
        rm, rs = float(r.mean()), float(r.std())
        ss = max(8.0, ss)
        rs = max(8.0, rs)
        matched = (s - sm) * (rs / ss) + rm
        out[:, :, channel] = s * (1.0 - amount) + matched * amount
    out = np.clip(out, 0, 255).astype("uint8")
    return Image.fromarray(out, mode="RGB")


def _full_head_overlay(
    *,
    source_full_raw: bytes,
    source_face_box: tuple[int, int, int, int],
    target_full_raw: bytes,
    target_face_box: tuple[int, int, int, int],
    baseline_full_raw: bytes,
    outer_strength: float,
    core_strength: float,
) -> tuple[bytes, dict[str, Any]]:
    """Warp the source head onto the target head with a feathered authority mask.

    The baseline already contains the provider Face Swap. This pass gives the
    source photograph direct authority over the identity-bearing head region.
    Background and body remain from the target image.
    """
    from PIL import Image, ImageDraw, ImageFilter

    source_img = fs.image(source_full_raw)
    target_img = fs.image(target_full_raw)
    baseline = fs.image(baseline_full_raw)

    source_box = _head_box(source_face_box, source_img.size)
    target_box = _head_box(target_face_box, target_img.size)
    sl, st, sr, sb = source_box
    tl, tt, tr, tb = target_box
    tw, th = tr - tl, tb - tt
    if tw < 128 or th < 160:
        raise ValueError("target head region is too small")

    source_head = source_img.crop(source_box).resize((tw, th), Image.LANCZOS)
    reference = baseline.crop(target_box)
    source_head = _color_match(source_head, reference, amount=0.68)

    # Outer head mask: hairline, forehead, temples, cheeks, jaw and a small part
    # of the upper neck. Corners stay transparent so source background is not
    # pasted as a rectangle.
    mask = Image.new("L", (tw, th), 0)
    draw = ImageDraw.Draw(mask)
    margin_x = max(2, int(tw * 0.055))
    margin_top = max(2, int(th * 0.018))
    margin_bottom = max(2, int(th * 0.055))
    draw.ellipse(
        (margin_x, margin_top, tw - margin_x, th - margin_bottom),
        fill=int(round(255 * max(0.0, min(1.0, outer_strength)))),
    )
    feather = max(4, int(min(tw, th) * 0.035))
    mask = mask.filter(ImageFilter.GaussianBlur(feather))

    # Identity core gets stronger authority than the perimeter. This is the
    # anti-hybrid part: eyes/nose/mouth/face shape are not averaged down to the
    # same degree as the transition around the hair/head boundary.
    fx, fy, fw, fh = target_face_box
    local_fx = fx - tl
    local_fy = fy - tt
    core = Image.new("L", (tw, th), 0)
    cdraw = ImageDraw.Draw(core)
    cx1 = max(0, int(local_fx - fw * 0.09))
    cy1 = max(0, int(local_fy - fh * 0.16))
    cx2 = min(tw, int(local_fx + fw * 1.09))
    cy2 = min(th, int(local_fy + fh * 1.14))
    cdraw.ellipse(
        (cx1, cy1, cx2, cy2),
        fill=int(round(255 * max(0.0, min(1.0, core_strength)))),
    )
    core = core.filter(ImageFilter.GaussianBlur(max(3, int(min(fw, fh) * 0.045))))

    # Lighter of two masks would weaken the identity core; use per-pixel max.
    import numpy as np  # type: ignore
    ma = np.asarray(mask, dtype=np.uint8)
    ca = np.asarray(core, dtype=np.uint8)
    combined = Image.fromarray(np.maximum(ma, ca), mode="L")

    merged_head = Image.composite(source_head, reference, combined)
    output = baseline.copy()
    output.paste(merged_head, (tl, tt))
    payload = fs.jpeg(output, max_side=2048, quality=97)
    metrics = {
        "source_head_box": source_box,
        "target_head_box": target_box,
        "outer_strength": float(outer_strength),
        "core_strength": float(core_strength),
        "feather": int(feather),
    }
    return payload, metrics


async def _download_with_retry(message: Any, trace: str, attempts: int = 3) -> bytes:
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
                "trace=%s stage=v262_telegram_download_retry attempt=%s/%s error=%r",
                trace, attempt, attempts, str(exc)[:500],
            )
            if attempt < attempts:
                await asyncio.sleep(1.2 * attempt)
        except Exception:
            raise
    if last is not None:
        raise last
    return b""


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
    diag._log("trace=%s stage=v262_handler_enter key=%s state=%s version=%s", trace, diag._key(update), state, VERSION)

    try:
        raw = await _download_with_retry(message, trace)
    except Exception as exc:
        diag._log("trace=%s stage=v262_telegram_download_failed state=%s error=%r", trace, state, str(exc)[:1000])
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

    diag._log("trace=%s stage=v262_input_received role=%s info=%r", trace, state, info)

    if state == "source":
        try:
            source_img, source_target, source_metrics = v260am._identity_crop(bytes(raw), role="source")
            head_box = _head_box(source_target.face_box, source_img.size)
        except Exception as exc:
            await message.reply_text(f"❌ Не удалось надёжно выделить голову/лицо-источник: {type(exc).__name__}: {str(exc)[:220]}")
            raise ApplicationHandlerStop

        session["source"] = bytes(raw)
        session["source_info"] = info
        session["source_crop"] = source_target.crop_raw
        session["source_face_box"] = tuple(source_target.face_box)
        session["source_head_box"] = tuple(head_box)
        session["source_metrics"] = source_metrics
        session["state"] = "target"
        context.user_data[diag.SOURCE] = bytes(raw)
        context.user_data[diag.STATE] = "target"

        diag._log(
            "trace=%s stage=v262_source_locked face=%s identity_crop=%s head_box=%s crop_dims=%s metrics=%r",
            trace, source_target.face_box, source_target.crop_box, head_box, fs.dims(source_target.crop_raw), source_metrics,
        )
        await message.reply_text(
            "✅ V262: источник личности принят.\n"
            f"Размер: {info['dims']}. Face coverage: {source_metrics['face_w_coverage']:.2f}×{source_metrics['face_h_coverage']:.2f}.\n"
            "Отдельно зафиксированы лицо, лоб, виски, линия волос, щёки и контур челюсти.\n\n"
            "Шаг 2/2: пришлите целевую фотографию."
        )
        raise ApplicationHandlerStop

    source = bytes(session.get("source") or b"")
    source_crop = bytes(session.get("source_crop") or b"")
    source_face_box_raw = session.get("source_face_box")
    if len(source) < 1024 or len(source_crop) < 1024 or not source_face_box_raw:
        diag._reset(update, context)
        await message.reply_text("❌ Источник личности потерян. Запустите тест заново.")
        raise ApplicationHandlerStop
    source_face_box = tuple(int(v) for v in source_face_box_raw)

    try:
        target_img, target_face, target_metrics = v260am._identity_crop(bytes(raw), role="target")
        target_head_box = _head_box(target_face.face_box, target_img.size)
    except Exception as exc:
        await message.reply_text(f"❌ Не удалось надёжно выделить целевую голову/лицо: {type(exc).__name__}: {str(exc)[:220]}")
        raise ApplicationHandlerStop

    session["state"] = "running"
    started = time.monotonic()
    diag._log(
        "trace=%s stage=v262_test_start source_full=%r target_full=%r source_face=%s source_head=%s target_face=%s target_head=%s source_crop_dims=%s target_crop_dims=%s",
        trace, session.get("source_info") or diag._describe(source), info, source_face_box,
        session.get("source_head_box"), target_face.face_box, target_head_box,
        fs.dims(source_crop), fs.dims(target_face.crop_raw),
    )

    await message.reply_text(
        "🧬 V262 Full-Head Identity Authority.\n\n"
        "Сначала один InSwapper (победитель V261: Face Restore ON, fidelity 0.95), затем три варианта интеграции:\n"
        "A — лицо через InSwapper, волосы/форма головы цели сохранены;\n"
        "B — источник управляет лицом + большей частью головы;\n"
        "C — максимальный приоритет источника: лицо, лоб, виски, линия волос, щёки и челюсть.\n\n"
        "Фон и тело во всех вариантах остаются целевыми. Сравнивайте, исчез ли эффект гибрида.\n"
        f"Код теста: {trace}."
    )

    failures: list[str] = []
    outputs: list[str] = []
    try:
        try:
            provider = await v260am._replicate_swap_once(
                version=v260am.REPLICATE_INSWAPPER_VERSION,
                inputs=v261._inswapper_inputs(source_crop, target_face.crop_raw, restore=True, fidelity=0.95),
                trace=trace,
                label="v262_inswapper_f095",
            )
            diag._log(
                "trace=%s stage=v262_provider_ready dims=%s bytes=%s sha=%s",
                trace, fs.dims(provider), len(provider), fs.sha(provider),
            )
        except Exception as exc:
            failures.append(f"InSwapper: {type(exc).__name__}: {str(exc)[:180]}")
            raise

        # A: current provider identity with the existing safe face-centric integration.
        baseline = fs.edge_composite(target_img, target_face, provider)
        outputs.append("A_face_only")
        await v260am._send_doc(
            message, baseline, f"faceswap_v262_A_face_only_{trace}.jpg",
            "🅰️ V262 A — InSwapper 0.95 + face-centric integration. Контроль: волосы и внешняя форма головы цели сохранены.", trace,
        )

        # B: stronger source authority over the full head, but retain a softer edge.
        medium, medium_metrics = _full_head_overlay(
            source_full_raw=source,
            source_face_box=source_face_box,
            target_full_raw=bytes(raw),
            target_face_box=tuple(target_face.face_box),
            baseline_full_raw=baseline,
            outer_strength=0.76,
            core_strength=0.94,
        )
        outputs.append("B_full_head_medium")
        diag._log("trace=%s stage=v262_B_ready metrics=%r dims=%s bytes=%s sha=%s", trace, medium_metrics, fs.dims(medium), len(medium), fs.sha(medium))
        await v260am._send_doc(
            message, medium, f"faceswap_v262_B_full_head_{trace}.jpg",
            "🅱️ V262 B — Full-Head Medium. Личность источника усилена по лицу, лбу, вискам, волосам и челюсти; переход по краю головы мягкий.", trace,
        )

        # C: near-literal identity core + strong hair/head authority.
        strong, strong_metrics = _full_head_overlay(
            source_full_raw=source,
            source_face_box=source_face_box,
            target_full_raw=bytes(raw),
            target_face_box=tuple(target_face.face_box),
            baseline_full_raw=baseline,
            outer_strength=0.92,
            core_strength=1.00,
        )
        outputs.append("C_full_head_strong")
        diag._log("trace=%s stage=v262_C_ready metrics=%r dims=%s bytes=%s sha=%s", trace, strong_metrics, fs.dims(strong), len(strong), fs.sha(strong))
        await v260am._send_doc(
            message, strong, f"faceswap_v262_C_full_head_strong_{trace}.jpg",
            "🅲 V262 C — Full-Head Strong. Максимальный приоритет фото-источника в центре лица и по всей голове; фон/тело цели сохранены.", trace,
        )

        elapsed = time.monotonic() - started
        diag._log("trace=%s stage=v262_finished elapsed=%.2f ok=%s failures=%r", trace, elapsed, outputs, failures)
        await message.reply_text(
            f"✅ V262 завершён. Код: {trace}. Время: {elapsed:.1f} сек.\n\n"
            "Выберите A/B/C именно по двум критериям: 1) узнаваемость источника, 2) отсутствие видимого шва/маски. "
            "Если B или C выигрывает, этот режим перенесём в production AI-селфи со звездой."
        )
    except Exception as exc:
        diag._log("trace=%s stage=v262_failed error=%r", trace, str(exc)[:1800])
        await message.reply_text(
            "❌ V262 не завершён: " + f"{type(exc).__name__}: {str(exc)[:220]}"
        )
    finally:
        diag._reset(update, context)

    raise ApplicationHandlerStop


def install() -> bool:
    global _INSTALLED
    if _INSTALLED or getattr(diag.media, "_v262_full_head_identity_owned", False):
        _INSTALLED = True
        return True
    setattr(media, "_v262_full_head_identity_owned", True)
    diag.media = media
    _INSTALLED = True
    diag._log("stage=v262_full_head_identity_patch status=installed version=%s", VERSION)
    return True


__all__ = ["VERSION", "media", "install"]
