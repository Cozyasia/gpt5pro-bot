# -*- coding: utf-8 -*-
"""Celebrity Selfie v153: detector-miss recovery for licensed references.

Production v152 fixed the empty Comet scene contract.  The next live failure was
in the public-person reference gate: all four licensed portrait files were
rejected with ``found 0`` when the optional local face detector returned no
boxes.  The files were valid images and the background remover was available,
but v149 stopped before segmentation could prove the human layer.

v153 keeps the fail-closed source-pixel architecture while adding one narrow
recovery path for catalog celebrity portraits only:

* use the existing detector whenever it returns a valid single face;
* on a detector miss, allow a provisional upper-centre portrait region;
* after PhotoRoom/rembg segmentation, infer the head/face region from the top of
  the non-rectangular person alpha silhouette;
* require strong alpha coverage inside that inferred region before the source
  can be composited;
* never use this fallback for the user's primary selfie.

No face is generated and no identity swap is introduced.  The delivered human
pixels still come from the selected licensed reference and the user's selfie.
"""
from __future__ import annotations

import os
import time
from io import BytesIO
from typing import Any

from PIL import Image, ImageOps, ImageStat

import celebrity_selfie_v139 as v139
import celebrity_selfie_v142 as v142
import celebrity_selfie_v143 as v143
import celebrity_selfie_v147 as v147
import celebrity_selfie_v149 as v149
import celebrity_selfie_v150 as v150
import celebrity_selfie_v151 as v151
import celebrity_selfie_v152 as v152

VERSION = "v153-reference-detector-miss-recovery-2026-07-21"
_GROUP = -2_100_001_600
_BUILDER_FLAG = "_celebrity_selfie_v153_builder"
_HANDLER_FLAG = "_celebrity_selfie_v153_handlers"
_LAST_RUN_DEBUG: dict[str, Any] = {}

_ORIGINAL_SOURCE_FACE_INFO = v149._source_face_info
_ORIGINAL_PREPARE_USER_CUTOUT = v143._prepare_user_cutout


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    return v139._number(name, default, minimum, maximum)


def _open_rgb(raw: bytes) -> Image.Image:
    if not raw:
        raise ValueError("empty image")
    with Image.open(BytesIO(raw)) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def _provisional_portrait_face(raw: bytes, role: str) -> dict[str, Any]:
    """Return a conservative face region only after a zero-box detector miss."""
    image = _open_rgb(raw)
    width, height = image.size
    if min(width, height) < _number("CELEBRITY_V153_MIN_REFERENCE_SIDE", 320, 160, 1200):
        raise v139.PipelineError("source_identity", f"{role} source resolution is too small")
    ratio = width / max(1.0, float(height))
    if ratio < 0.32 or ratio > 2.60:
        raise v139.PipelineError("source_identity", f"{role} source aspect is unsuitable: {ratio:.2f}")
    metrics = v139._image_metrics(raw)
    if float(metrics.get("brightness") or 0) < 8 or float(metrics.get("brightness") or 0) > 250:
        raise v139.PipelineError("source_identity", f"{role} source exposure is unusable")
    if float(metrics.get("contrast") or 0) < 2.0:
        raise v139.PipelineError("source_identity", f"{role} source contrast is unusable")

    short = float(min(width, height))
    face_w = min(width * 0.46, max(short * 0.25, short * 0.34))
    face_h = min(height * 0.46, face_w * 1.28)
    center_x = width * 0.50
    center_y = height * (0.30 if height >= width else 0.38)
    x = max(0.0, min(width - face_w, center_x - face_w / 2.0))
    y = max(0.0, min(height - face_h, center_y - face_h / 2.0))
    face = {"x": x, "y": y, "w": face_w, "h": face_h, "fallback": True}
    area_ratio = (face_w * face_h) / max(1.0, float(width * height))
    return {
        "face": face,
        "source_size": [width, height],
        "face_area_ratio": round(area_ratio, 5),
        "face_center": [round((x + face_w / 2.0) / width, 4), round((y + face_h / 2.0) / height, 4)],
        "face_detection": "provisional-zero-box-recovery",
    }


def _source_face_info(raw: bytes, role: str) -> dict[str, Any]:
    try:
        info = dict(_ORIGINAL_SOURCE_FACE_INFO(raw, role))
        info.setdefault("face_detection", "local-detector")
        return info
    except Exception as exc:
        text = v139._safe_error(exc).casefold()
        if (
            role != "celebrity"
            or not _flag("CELEBRITY_V153_REFERENCE_FACE_FALLBACK", True)
            or not any(token in text for token in ("found 0", "no face", "zero face"))
        ):
            raise
        return _provisional_portrait_face(raw, role)


def _alpha_mean(alpha: Image.Image, box: tuple[int, int, int, int]) -> float:
    crop = alpha.crop(box)
    if crop.width <= 0 or crop.height <= 0:
        return 0.0
    return float(ImageStat.Stat(crop).mean[0]) / 255.0


def _infer_face_from_alpha(image: Image.Image) -> tuple[dict[str, float], dict[str, Any]]:
    """Infer a head region from the top of a validated person silhouette."""
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    alpha = image.getchannel("A")
    binary = alpha.point(lambda value: 255 if value >= 24 else 0)
    bbox = binary.getbbox()
    if not bbox:
        raise v139.PipelineError("source_cutout", "celebrity cutout has no alpha subject")
    left, top, right, bottom = bbox
    subject_w = max(1, right - left)
    subject_h = max(1, bottom - top)
    if subject_h < image.height * 0.18 or subject_w < image.width * 0.08:
        raise v139.PipelineError("source_cutout", "celebrity alpha subject is too small")

    # The first 22% of a person silhouette normally contains hair/head but not
    # the full shoulder span. Its alpha bounding box gives a stable horizontal
    # anchor even when the optional face detector is unavailable.
    head_band_bottom = min(bottom, top + max(12, int(subject_h * 0.22)))
    head_band = binary.crop((left, top, right, head_band_bottom))
    head_bbox = head_band.getbbox()
    if head_bbox:
        h_left = left + head_bbox[0]
        h_right = left + head_bbox[2]
        head_span = max(1, h_right - h_left)
        center_x = (h_left + h_right) / 2.0
    else:
        head_span = max(1, int(subject_w * 0.42))
        center_x = (left + right) / 2.0

    face_w = max(subject_w * 0.18, min(subject_w * 0.48, head_span * 0.72))
    face_h = max(subject_h * 0.12, min(subject_h * 0.32, face_w * 1.28))
    base_y = top + subject_h * 0.025

    best: tuple[float, tuple[int, int, int, int]] | None = None
    for dx_ratio in (-0.08, -0.04, 0.0, 0.04, 0.08):
        for dy_ratio in (0.00, 0.025, 0.05, 0.075, 0.10):
            cx = center_x + subject_w * dx_ratio
            y = base_y + subject_h * dy_ratio
            x1 = int(round(cx - face_w / 2.0))
            y1 = int(round(y))
            x2 = int(round(x1 + face_w))
            y2 = int(round(y1 + face_h))
            x1 = max(0, min(image.width - 2, x1))
            y1 = max(0, min(image.height - 2, y1))
            x2 = max(x1 + 2, min(image.width, x2))
            y2 = max(y1 + 2, min(image.height, y2))
            box = (x1, y1, x2, y2)
            coverage = _alpha_mean(alpha, box)
            # Prefer strong alpha and slightly higher boxes when scores tie.
            score = coverage - dy_ratio * 0.08 - abs(dx_ratio) * 0.03
            if best is None or score > best[0]:
                best = (score, box)

    assert best is not None
    box = best[1]
    coverage = _alpha_mean(alpha, box)
    minimum = _number("CELEBRITY_V153_INFERRED_FACE_ALPHA_MIN", 0.58, 0.35, 0.90)
    if coverage < minimum:
        raise v139.PipelineError(
            "source_cutout",
            f"celebrity inferred head region is not retained by alpha: {coverage:.3f}",
        )
    face = {
        "x": float(box[0]),
        "y": float(box[1]),
        "w": float(box[2] - box[0]),
        "h": float(box[3] - box[1]),
        "fallback": True,
    }
    details = {
        "method": "alpha-silhouette-head-region",
        "alpha": round(coverage, 4),
        "subject_bbox": [left, top, right, bottom],
        "face_box": list(box),
    }
    return face, details


async def _prepare_user_cutout(
    mod: Any,
    raw: bytes,
    debug: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    cutout = await _ORIGINAL_PREPARE_USER_CUTOUT(mod, raw, debug, label)
    if isinstance(cutout.get("face"), dict):
        cutout.setdefault("face_detection", "local-detector")
        return cutout

    # Never relax the user's primary-selfie proof. This recovery is exclusively
    # for catalog celebrity references whose downloader already selected images
    # associated with the chosen public person.
    if not str(label or "").casefold().startswith("celebrity_ref_"):
        return cutout
    if not _flag("CELEBRITY_V153_REFERENCE_FACE_FALLBACK", True):
        return cutout

    image = cutout.get("image")
    if not isinstance(image, Image.Image):
        raise v139.PipelineError("source_cutout", "celebrity cutout image is unavailable")
    face, details = _infer_face_from_alpha(image)
    cutout["face"] = face
    cutout["face_detection"] = details["method"]
    cutout["inferred_face"] = details

    entries = debug.get("cutouts") or []
    for row in reversed(entries):
        if str(row.get("label") or "") == str(label):
            row["face"] = face
            row["face_detection"] = details["method"]
            row["inferred_face_alpha"] = details["alpha"]
            break
    debug.setdefault("reference_face_fallbacks", []).append({"label": label, **details})
    return cutout


async def _run_v153_generation(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
    *,
    additional_user_refs: list[bytes] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    global _LAST_RUN_DEBUG
    started = time.time()
    contract = {
        "version": VERSION,
        "architecture": "empty-comet-scene+source-pixel-layers+reference-detector-miss-recovery",
        "celebrity_reference_gate": "detector-first+alpha-silhouette-fallback-on-zero-box",
        "user_reference_fallback": "disabled",
        "scene_provider_order": ["comet"],
        "user_face_generation": "disabled",
        "celebrity_face_generation": "disabled",
        "face_swap": "disabled",
        "credit_charge_on_failure": False,
    }
    try:
        output, debug = await v152._run_v152_generation(
            mod,
            user_photo,
            celebrity_refs,
            celebrity_name,
            scene,
            previous_result=previous_result,
            additional_user_refs=additional_user_refs,
        )
        debug = dict(debug or {})
        debug.update(contract)
        debug["v153_duration_s"] = round(time.time() - started, 2)
        _LAST_RUN_DEBUG = debug
        for module in (v152, v151, v150, v149, v147, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
        return output, debug
    except Exception as exc:
        debug = dict(getattr(exc, "debug", None) or {})
        debug.update(contract)
        debug["v153_duration_s"] = round(time.time() - started, 2)
        _LAST_RUN_DEBUG = debug
        for module in (v152, v151, v150, v149, v147, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
        if isinstance(exc, v139.PipelineError):
            exc.debug = debug
        raise


async def _run_compat(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
    *,
    additional_user_refs: list[bytes] | None = None,
) -> bytes:
    output, _ = await _run_v153_generation(
        mod,
        user_photo,
        celebrity_refs,
        celebrity_name,
        scene,
        previous_result=previous_result,
        additional_user_refs=additional_user_refs,
    )
    return output


def _patch_version_contract() -> None:
    try:
        import neyrobot_prod
        from neyrobot_prod import bootstrap, versioning

        neyrobot_prod.VERSION = VERSION
        bootstrap.VERSION = VERSION
        versioning.VERSION = VERSION
    except Exception:
        pass


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    session = v139.selfie.engine._session(context, create=False) or {}
    debug = session.get("v142_debug") or session.get("v139_debug") or _LAST_RUN_DEBUG or {}
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "architecture=empty_comet_scene+source_pixel_layers+reference_detector_miss_recovery",
        "scene_provider_order=comet",
        f"comet={'ready' if bool(v150._comet_key()) else 'missing'}",
        f"comet_model={v151._comet_model()}",
        "empty_scene_plate_gate=composition_ready",
        "celebrity_reference_gate=detector_first+alpha_silhouette_fallback_on_zero_box",
        "user_reference_fallback=disabled",
        "gemini_scene=disabled",
        "flux_scene=disabled",
        "face_swap=disabled",
        f"run_id={debug.get('run_id') or '-'}",
        f"state={session.get('state') or '-'}",
        f"scene_candidates={len(debug.get('scene_candidates') or [])}",
        f"celebrity_candidates={len(debug.get('identity_candidates') or [])}",
        f"composite_candidates={len(debug.get('composite_candidates') or [])}",
        f"reference_face_fallbacks={str(debug.get('reference_face_fallbacks') or '-')[:1600]}",
        f"background_attempts={str(debug.get('background_attempts') or '-')[:1200]}",
        f"selected={str(debug.get('selected') or '-')[:800]}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    for item in (debug.get("errors") or [])[-8:]:
        lines.append(
            f"- {item.get('stage')} [{item.get('provider')}]: "
            f"{str(item.get('error') or '')[:320]}"
        )
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    v152.install()
    os.environ.setdefault("CELEBRITY_V153_REFERENCE_FACE_FALLBACK", "1")
    os.environ.setdefault("CELEBRITY_V153_INFERRED_FACE_ALPHA_MIN", "0.58")
    os.environ.setdefault("CELEBRITY_V153_MIN_REFERENCE_SIDE", "320")

    # v149 resolves these globals at call time, so patching the live module and
    # the live cutout primitive repairs every already-installed v149 function.
    v149._source_face_info = _source_face_info
    v143._prepare_user_cutout = _prepare_user_cutout

    v139.selfie._run_v153_generation = _run_v153_generation
    v139.selfie.engine._run_multi_reference_generation = _run_compat
    v139.selfie.engine._diag = _diag
    _patch_version_contract()


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        install()
        if not getattr(app, _HANDLER_FLAG, False):
            for command in (
                "diag_selfie_v153",
                "diag_selfie_v152",
                "diag_selfie_v151",
                "diag_selfie_v150",
                "diag_selfie_v149",
                "diag_selfie_v148",
                "diag_selfie_v147",
                "diag_selfie_v146",
                "diag_selfie_v145",
                "diag_selfie_v144",
                "diag_selfie_v143",
                "diag_celebrity_flow",
                "diag_brand",
            ):
                app.add_handler(CommandHandler(command, _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


def install_early() -> None:
    install()
    install_builder_hook()


__all__ = [
    "VERSION",
    "install",
    "install_early",
    "install_builder_hook",
    "_source_face_info",
    "_infer_face_from_alpha",
    "_prepare_user_cutout",
    "_run_v153_generation",
    "_diag",
]
