# -*- coding: utf-8 -*-
"""Celebrity Selfie v154: production cutout backend and user-face recovery.

The live v153 trace exposed two independent infrastructure faults after the
Comet scene and catalog-reference fixes had started working:

* ``rembg`` was installed without its CPU inference backend, therefore every
  local fallback failed with ``No module named 'onnxruntime'``;
* when the optional face detector returned zero boxes for the user's clear
  selfie, the transparent person cutout still had no verified face metadata and
  v149 rejected it before compositing.

v154 keeps the source-pixel architecture and repairs those exact failure modes:

* use the CPU-enabled rembg installation and a cached ``u2net_human_seg``
  session stored on the Render persistent disk;
* prefer local human segmentation, with PhotoRoom retained as fallback;
* minimally clear only the least-occupied PhotoRoom corners when an otherwise
  valid cutout fails the strict transparent-corner gate;
* recover a face/head region from a validated human alpha silhouette when the
  optional detector returns zero boxes, for both catalog references and the
  user's primary selfie;
* never generate a face, never enable face swap, and never charge credits when
  no final image is delivered.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
import uuid
from io import BytesIO
from pathlib import Path
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
import celebrity_selfie_v153 as v153

VERSION = "v154-cpu-rembg-user-face-recovery-2026-07-22"
_GROUP = -2_100_001_700
_BUILDER_FLAG = "_celebrity_selfie_v154_builder"
_HANDLER_FLAG = "_celebrity_selfie_v154_handlers"
_LAST_RUN_DEBUG: dict[str, Any] = {}

_ORIGINAL_SOURCE_FACE_INFO = v153._source_face_info
_ORIGINAL_PREPARE_CUTOUT = v153._prepare_user_cutout
_ORIGINAL_PHOTOROOM_CUTOUT = v142._photoroom_cutout
_REMBG_SESSION: Any | None = None
_REMBG_SESSION_LOCK = threading.Lock()


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    return v139._number(name, default, minimum, maximum)


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    return v139._integer(name, default, minimum, maximum)


def _open_rgba(raw: bytes) -> Image.Image:
    if not raw:
        raise ValueError("empty image")
    with Image.open(BytesIO(raw)) as opened:
        return ImageOps.exif_transpose(opened).convert("RGBA")


def _encode_png(image: Image.Image) -> bytes:
    out = BytesIO()
    image.convert("RGBA").save(out, "PNG", optimize=True)
    return out.getvalue()


def _select_u2net_home() -> Path:
    configured = str(os.environ.get("U2NET_HOME") or "").strip()
    candidates = [configured, "/data/.u2net", "/tmp/.u2net"]
    for value in candidates:
        if not value:
            continue
        path = Path(value).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / f".probe-{os.getpid()}-{uuid.uuid4().hex}"
            probe.write_bytes(b"ok")
            probe.unlink(missing_ok=True)
            os.environ["U2NET_HOME"] = str(path)
            return path
        except Exception:
            continue
    fallback = Path("/tmp") / f"u2net-{os.getpid()}"
    fallback.mkdir(parents=True, exist_ok=True)
    os.environ["U2NET_HOME"] = str(fallback)
    return fallback


def _corner_boxes(size: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    width, height = size
    corner_w = max(3, int(width * 0.09))
    corner_h = max(3, int(height * 0.09))
    return [
        (0, 0, corner_w, corner_h),
        (width - corner_w, 0, width, corner_h),
        (0, height - corner_h, corner_w, height),
        (width - corner_w, height - corner_h, width, height),
    ]


def _clear_least_occupied_corners(image: Image.Image, minimum_clear: int = 2) -> Image.Image:
    """Clear only enough low-alpha corners to satisfy the strict cutout gate."""
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    boxes = _corner_boxes(image.size)
    means = [float(ImageStat.Stat(alpha.crop(box)).mean[0]) for box in boxes]
    clear = {index for index, value in enumerate(means) if value <= 45.0}
    needed = max(0, minimum_clear - len(clear))
    if not needed:
        return image
    candidates = [index for index in sorted(range(4), key=lambda idx: means[idx]) if index not in clear]
    for index in candidates[:needed]:
        alpha.paste(0, boxes[index])
    image.putalpha(alpha)
    return image


def _repair_photoroom_cutout(raw: bytes) -> bytes:
    """Repair only the observed false-positive transparent-corner rejection."""
    image = _open_rgba(raw)
    metrics = v143._alpha_metrics(image)
    if int(metrics.get("transparent_corners") or 0) >= 2:
        return raw
    if not metrics.get("bbox"):
        return raw
    coverage = float(metrics.get("coverage") or 0)
    transparent = float(metrics.get("transparent") or 0)
    border_opaque = float(metrics.get("border_opaque") or 1)
    bbox_opaque = float(metrics.get("bbox_opaque") or 1)
    # Do not hide a genuinely bad segmentation. Repair only when every other
    # alpha metric is already close to the strict v143 production contract.
    if not (0.03 <= coverage <= 0.84 and transparent >= 0.08 and border_opaque <= 0.52 and bbox_opaque <= 0.88):
        return raw
    repaired = _clear_least_occupied_corners(image, minimum_clear=2)
    encoded = _encode_png(repaired)
    try:
        v143._validate_cutout(encoded)
    except Exception:
        return raw
    return encoded


async def _photoroom_cutout(mod: Any, raw: bytes) -> bytes:
    result = await _ORIGINAL_PHOTOROOM_CUTOUT(mod, raw)
    return _repair_photoroom_cutout(result)


def _get_rembg_session() -> Any:
    global _REMBG_SESSION
    if _REMBG_SESSION is not None:
        return _REMBG_SESSION
    with _REMBG_SESSION_LOCK:
        if _REMBG_SESSION is None:
            _select_u2net_home()
            from rembg import new_session

            model = str(os.environ.get("CELEBRITY_V154_REMBG_MODEL") or "u2net_human_seg").strip()
            _REMBG_SESSION = new_session(model)
    return _REMBG_SESSION


async def _local_rembg_cutout(raw: bytes) -> bytes:
    if not _flag("CELEBRITY_V142_LOCAL_REMBG_FALLBACK", True):
        raise RuntimeError("local rembg fallback disabled")

    def run() -> bytes:
        from rembg import remove

        result = remove(raw, session=_get_rembg_session())
        if not isinstance(result, (bytes, bytearray)):
            raise RuntimeError("rembg returned no bytes")
        value = bytes(result)
        v142._validate_cutout(value)
        return value

    timeout_s = _integer("CELEBRITY_V154_REMBG_TIMEOUT_S", 420, 60, 900)
    return await asyncio.wait_for(asyncio.to_thread(run), timeout=timeout_s)


def _is_zero_face_error(exc: BaseException) -> bool:
    text = v139._safe_error(exc).casefold()
    return any(token in text for token in ("found 0", "no face", "zero face", "no verified source face"))


def _source_face_info(raw: bytes, role: str) -> dict[str, Any]:
    try:
        info = dict(_ORIGINAL_SOURCE_FACE_INFO(raw, role))
        info.setdefault("face_detection", "local-detector")
        return info
    except Exception as exc:
        allow = role == "celebrity" or _flag("CELEBRITY_V154_USER_FACE_FALLBACK", True)
        if not allow or not _is_zero_face_error(exc):
            raise
        info = dict(v153._provisional_portrait_face(raw, role))
        info["face_detection"] = "v154-provisional-zero-box-recovery"
        return info


def _band_width(binary: Image.Image, box: tuple[int, int, int, int]) -> int:
    crop = binary.crop(box)
    bbox = crop.getbbox()
    return 0 if not bbox else max(0, bbox[2] - bbox[0])


def _human_silhouette_problem(image: Image.Image) -> str:
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    binary = alpha.point(lambda value: 255 if value >= 24 else 0)
    bbox = binary.getbbox()
    if not bbox:
        return "alpha silhouette is empty"
    left, top, right, bottom = bbox
    width = max(1, right - left)
    height = max(1, bottom - top)
    height_ratio = height / max(1.0, float(image.height))
    aspect = width / max(1.0, float(height))
    if height_ratio < _number("CELEBRITY_V154_MIN_SILHOUETTE_HEIGHT", 0.28, 0.12, 0.70):
        return f"alpha silhouette is too short: {height_ratio:.3f}"
    if aspect < 0.12 or aspect > 1.45:
        return f"alpha silhouette aspect is not portrait-like: {aspect:.3f}"

    head_end = min(bottom, top + max(6, int(height * 0.22)))
    torso_start = min(bottom - 1, top + max(4, int(height * 0.22)))
    torso_end = min(bottom, top + max(8, int(height * 0.58)))
    head_width = _band_width(binary, (left, top, right, head_end))
    torso_width = _band_width(binary, (left, torso_start, right, torso_end))
    if head_width <= 0:
        return "alpha silhouette has no retained head region"
    if torso_width > 0 and head_width > torso_width * 1.35:
        return f"alpha silhouette head/torso geometry is implausible: {head_width}/{torso_width}"
    return ""


async def _prepare_user_cutout(
    mod: Any,
    raw: bytes,
    debug: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    cutout = await _ORIGINAL_PREPARE_CUTOUT(mod, raw, debug, label)
    if isinstance(cutout.get("face"), dict):
        cutout.setdefault("face_detection", "local-detector")
        return cutout

    image = cutout.get("image")
    if not isinstance(image, Image.Image):
        raise v139.PipelineError("source_cutout", f"{label} cutout image is unavailable")
    problem = _human_silhouette_problem(image)
    if problem:
        raise v139.PipelineError("source_cutout", f"{label} {problem}")

    face, details = v153._infer_face_from_alpha(image)
    cutout["face"] = face
    cutout["face_detection"] = "v154-alpha-silhouette-head-region"
    cutout["inferred_face"] = details
    role = "celebrity" if str(label).casefold().startswith("celebrity_ref_") else "user"

    entries = debug.get("cutouts") or []
    for row in reversed(entries):
        if str(row.get("label") or "") == str(label):
            row["face"] = face
            row["face_detection"] = cutout["face_detection"]
            row["inferred_face_alpha"] = details.get("alpha")
            break
    debug.setdefault("source_face_fallbacks", []).append({
        "label": label,
        "role": role,
        "method": cutout["face_detection"],
        **details,
    })
    return cutout


async def _run_v154_generation(
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
        "architecture": "empty-comet-scene+cpu-human-segmentation+source-pixel-dual-composite",
        "cutout_provider_order": ["rembg", "photoroom"],
        "rembg_backend": "onnxruntime-cpu",
        "rembg_model": str(os.environ.get("CELEBRITY_V154_REMBG_MODEL") or "u2net_human_seg"),
        "celebrity_reference_gate": "detector-first+alpha-silhouette-fallback",
        "user_reference_gate": "detector-first+alpha-silhouette-fallback",
        "user_face_generation": "disabled",
        "celebrity_face_generation": "disabled",
        "face_swap": "disabled",
        "credit_charge_on_failure": False,
    }
    try:
        output, debug = await v153._run_v153_generation(
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
        debug["v154_duration_s"] = round(time.time() - started, 2)
        _LAST_RUN_DEBUG = debug
        for module in (v153, v152, v151, v150, v149, v147, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
        return output, debug
    except Exception as exc:
        debug = dict(getattr(exc, "debug", None) or {})
        debug.update(contract)
        debug["v154_duration_s"] = round(time.time() - started, 2)
        _LAST_RUN_DEBUG = debug
        for module in (v153, v152, v151, v150, v149, v147, v143, v142, v139):
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
    output, _ = await _run_v154_generation(
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
        "architecture=empty_comet_scene+cpu_human_segmentation+source_pixel_dual_composite",
        "scene_provider_order=comet",
        f"comet={'ready' if bool(v150._comet_key()) else 'missing'}",
        f"comet_model={v151._comet_model()}",
        "cutout_provider_order=rembg,photoroom",
        "rembg_backend=onnxruntime-cpu",
        f"rembg_model={os.environ.get('CELEBRITY_V154_REMBG_MODEL') or 'u2net_human_seg'}",
        f"u2net_home={os.environ.get('U2NET_HOME') or '-'}",
        "celebrity_reference_gate=detector_first+alpha_silhouette_fallback",
        "user_reference_gate=detector_first+alpha_silhouette_fallback",
        "face_swap=disabled",
        f"run_id={debug.get('run_id') or '-'}",
        f"state={session.get('state') or '-'}",
        f"scene_candidates={len(debug.get('scene_candidates') or [])}",
        f"celebrity_candidates={len(debug.get('identity_candidates') or [])}",
        f"composite_candidates={len(debug.get('composite_candidates') or [])}",
        f"source_face_fallbacks={str(debug.get('source_face_fallbacks') or '-')[:1600]}",
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
    v153.install()
    _select_u2net_home()
    os.environ.setdefault("CELEBRITY_V142_LOCAL_REMBG_FALLBACK", "1")
    os.environ.setdefault("CELEBRITY_V143_CUTOUT_PROVIDERS", "rembg,photoroom")
    os.environ.setdefault("CELEBRITY_V154_REMBG_MODEL", "u2net_human_seg")
    os.environ.setdefault("CELEBRITY_V154_REMBG_TIMEOUT_S", "420")
    os.environ.setdefault("CELEBRITY_V154_USER_FACE_FALLBACK", "1")

    v142._photoroom_cutout = _photoroom_cutout
    v142._local_rembg_cutout = _local_rembg_cutout
    v149._source_face_info = _source_face_info
    v143._prepare_user_cutout = _prepare_user_cutout

    v139.selfie._run_v154_generation = _run_v154_generation
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
                "diag_selfie_v154",
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
    "_repair_photoroom_cutout",
    "_local_rembg_cutout",
    "_source_face_info",
    "_human_silhouette_problem",
    "_prepare_user_cutout",
    "_run_v154_generation",
    "_diag",
]
