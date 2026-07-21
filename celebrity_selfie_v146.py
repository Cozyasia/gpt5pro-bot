# -*- coding: utf-8 -*-
"""Celebrity Selfie v146: local celebrity-face locking with fail-closed QC.

Production v145 confirmed that the release bootstrap was correct, but PiAPI could
still return HTTP 500 when a small face was swapped on the complete scene plate.
This overlay keeps the user's source pixels untouched and changes only the public
person stage:

* enlarge the sole right-side face into a private local crop before face swap;
* use PiAPI single ``face-swap`` only (no one-face ``multi-face-swap`` fallback);
* try several public-person references independently;
* blend only the repaired head region back into the original scene plate;
* use a local OpenAI edit crop as provider fallback, never a full-frame user edit;
* verify the finished full plate against the best available reference;
* keep every v143 structural and final-composite quality gate enabled.
"""
from __future__ import annotations

import os
import time
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageOps

import celebrity_selfie_v139 as v139
import celebrity_selfie_v142 as v142
import celebrity_selfie_v143 as v143
import celebrity_selfie_v144 as v144
import celebrity_selfie_v145 as v145

VERSION = "v146-local-face-lock-2026-07-21"
_GROUP = -2_100_000_900
_BUILDER_FLAG = "_celebrity_selfie_v146_builder"
_HANDLER_FLAG = "_celebrity_selfie_v146_handlers"

_ORIGINAL_V145_RUN = v145._run_v145_generation
_ORIGINAL_V145_PIAPI_ONCE = v145._piapi_face_swap_once
_ORIGINAL_V144_SCENE_PROMPT = v144._scene_prompt
_LAST_RUN_DEBUG: dict[str, Any] = {}
_LAST_SWAP_DEBUG: dict[str, Any] = {}


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    return v139._number(name, default, minimum, maximum)


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    return v139._integer(name, default, minimum, maximum)


def _open_rgb(raw: bytes) -> Image.Image:
    if not raw:
        raise ValueError("empty image")
    with Image.open(BytesIO(raw)) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def _encode_jpeg(image: Image.Image, quality: int = 95) -> bytes:
    out = BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def _shifted_square_box(
    width: int,
    height: int,
    cx: float,
    cy: float,
    side: float,
) -> tuple[int, int, int, int]:
    side_i = max(96, min(int(round(side)), width, height))
    left = int(round(cx - side_i / 2))
    top = int(round(cy - side_i / 2))
    left = max(0, min(left, width - side_i))
    top = max(0, min(top, height - side_i))
    return left, top, left + side_i, top + side_i


def _target_face_region(raw: bytes) -> dict[str, Any]:
    """Return a square right-side head crop and coordinates in the full plate."""
    image = _open_rgb(raw)
    boxes = []
    try:
        boxes = [dict(item) for item in (v142._face_boxes(raw) or []) if isinstance(item, dict)]
    except Exception:
        boxes = []

    valid = [
        row for row in boxes
        if float(row.get("w") or 0) >= 12 and float(row.get("h") or 0) >= 12
    ]
    face: dict[str, float] | None = None
    detector = "heuristic-right-region"

    if valid:
        chosen = max(
            valid,
            key=lambda row: (
                float(row.get("w") or 0) * float(row.get("h") or 0),
                float(row.get("x") or 0),
            ),
        )
        x = float(chosen.get("x") or 0)
        y = float(chosen.get("y") or 0)
        w = max(1.0, float(chosen.get("w") or 1))
        h = max(1.0, float(chosen.get("h") or 1))
        cx = x + w / 2.0
        cy = y + h / 2.0 + h * 0.10
        side = max(w, h) * _number("CELEBRITY_V146_TARGET_CROP_FACE_MULTIPLIER", 4.2, 2.8, 6.0)
        side = max(side, min(image.size) * 0.28)
        bbox = _shifted_square_box(image.width, image.height, cx, cy, side)
        face = {
            "x": x - bbox[0],
            "y": y - bbox[1],
            "w": w,
            "h": h,
        }
        detector = "local-face-detector"
    else:
        # v144 already required independent Vision confirmation when the local
        # detector missed a plate. Crop the known right-side composition region.
        side = min(image.height * 0.72, image.width * 0.56)
        cx = image.width * 0.74
        cy = image.height * 0.34
        bbox = _shifted_square_box(image.width, image.height, cx, cy, side)

    crop = image.crop(bbox)
    provider_side = _integer("CELEBRITY_V146_PROVIDER_CROP_SIDE", 1280, 768, 1600)
    crop_provider = ImageOps.fit(
        crop,
        (provider_side, provider_side),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.46),
    )
    return {
        "image": image,
        "bbox": bbox,
        "crop": crop,
        "provider_crop": crop_provider,
        "face": face,
        "detector": detector,
    }


def _face_blend_mask(size: tuple[int, int], face: dict[str, float] | None) -> Image.Image:
    width, height = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)

    if face:
        x = float(face.get("x") or width * 0.35)
        y = float(face.get("y") or height * 0.25)
        w = max(24.0, float(face.get("w") or width * 0.25))
        h = max(24.0, float(face.get("h") or height * 0.25))
        box = (
            max(0, int(x - w * 0.58)),
            max(0, int(y - h * 0.65)),
            min(width, int(x + w * 1.58)),
            min(height, int(y + h * 1.90)),
        )
    else:
        box = (
            int(width * 0.12),
            int(height * 0.06),
            int(width * 0.88),
            int(height * 0.91),
        )

    draw.ellipse(box, fill=255)
    blur = max(10, int(min(width, height) * _number(
        "CELEBRITY_V146_BLEND_FEATHER_RATIO", 0.045, 0.015, 0.10
    )))
    return mask.filter(ImageFilter.GaussianBlur(radius=blur))


def _merge_local_identity(target: bytes, swapped_crop: bytes, region: dict[str, Any]) -> bytes:
    base = region["image"].copy()
    bbox = tuple(int(value) for value in region["bbox"])
    original_crop = region["crop"].convert("RGB")
    repaired = _open_rgb(swapped_crop).resize(original_crop.size, Image.Resampling.LANCZOS)

    # Keep the original local background and transfer only the head/face area.
    mask = _face_blend_mask(original_crop.size, region.get("face"))
    merged_crop = Image.composite(repaired, original_crop, mask)
    base.paste(merged_crop, (bbox[0], bbox[1]))
    return v139._jpeg(_encode_jpeg(base, 96), max_side=2000, quality=96)


def _piapi_modes() -> list[str]:
    """Single-face plates must never fall into the unstable multi-face task."""
    raw = os.environ.get("CELEBRITY_V146_PIAPI_MODES") or "face-swap"
    result: list[str] = []
    allow_multi = _flag("CELEBRITY_V146_ALLOW_MULTI_FACE_SWAP", False)
    for item in raw.split(","):
        mode = item.strip().casefold()
        if mode == "face-swap" and mode not in result:
            result.append(mode)
        elif mode == "multi-face-swap" and allow_multi and mode not in result:
            result.append(mode)
    return result or ["face-swap"]


async def _piapi_face_swap_once(mod: Any, target: bytes, reference: bytes, mode: str) -> bytes:
    """Swap on an enlarged local face crop, then blend it into the full plate."""
    global _LAST_SWAP_DEBUG
    if mode != "face-swap":
        raise RuntimeError("v146 blocks multi-face-swap for a one-face scene plate")

    region = _target_face_region(target)
    source = v145._piapi_ready_image(v139._face_crop(reference, 1024), source=True)
    target_crop = v145._piapi_ready_image(_encode_jpeg(region["provider_crop"], 95), source=False)
    task_type, inputs = v145._piapi_request("face-swap", source, target_crop)
    errors: list[str] = []

    try:
        swapped = await v139.pi_identity._piapi_task(mod, task_type, inputs)
        merged = _merge_local_identity(target, swapped, region)
        _LAST_SWAP_DEBUG = {
            "strategy": "local-face-crop",
            "detector": region["detector"],
            "bbox": list(region["bbox"]),
            "source_bytes": len(source),
            "target_crop_bytes": len(target_crop),
            "result_bytes": len(merged),
            "errors": [],
        }
        return merged
    except Exception as exc:
        errors.append("local-face-crop:" + v139._safe_error(exc))

    # A whole-plate single-face retry remains useful when the provider rejects a
    # crop for transient reasons. It still never uses multi-face-swap.
    if _flag("CELEBRITY_V146_WHOLE_PLATE_RETRY", True):
        try:
            merged = await _ORIGINAL_V145_PIAPI_ONCE(mod, target, reference, "face-swap")
            _LAST_SWAP_DEBUG = {
                "strategy": "whole-plate-single-face-retry",
                "detector": region["detector"],
                "bbox": list(region["bbox"]),
                "result_bytes": len(merged),
                "errors": errors,
            }
            return merged
        except Exception as exc:
            errors.append("whole-plate:" + v139._safe_error(exc))

    _LAST_SWAP_DEBUG = {
        "strategy": "failed",
        "detector": region["detector"],
        "bbox": list(region["bbox"]),
        "errors": errors,
    }
    raise RuntimeError("PiAPI local celebrity lock failed: " + " | ".join(errors[-3:])[:1200])


async def _openai_local_identity_once(
    mod: Any,
    target: bytes,
    references: list[bytes],
    celebrity_name: str,
    *,
    repair: bool,
) -> bytes:
    region = _target_face_region(target)
    target_crop = _encode_jpeg(region["provider_crop"], 95)
    repaired = await v139._openai_single_face(
        mod,
        target_crop,
        references[:3],
        "right",
        f"the selected PUBLIC PERSON ({celebrity_name}); exactly one close adult face",
        "1:1",
        repair=repair,
    )
    return _merge_local_identity(target, repaired, region)


async def _best_identity_score(
    mod: Any,
    output: bytes,
    references: list[bytes],
    limit: int = 3,
) -> dict[str, Any]:
    best = {"score": 0.0, "unknown": True, "reason": "no usable identity reference", "reference_index": 0}
    for index, reference in enumerate([raw for raw in references if raw][:limit], start=1):
        qc = await v143._single_face_identity_score(mod, output, reference)
        score = float(qc.get("score") or 0)
        if score > float(best.get("score") or 0):
            best = dict(qc)
            best["reference_index"] = index
        if not qc.get("unknown") and score >= _number("CELEBRITY_V146_QC_EARLY_STOP", 82.0, 60.0, 97.0):
            break
    return best


async def _celebrity_variants(
    mod: Any,
    plate: dict[str, Any],
    references: list[bytes],
    celebrity_name: str,
    aspect: str,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    """Create verified celebrity plates without touching the future user side."""
    debug.setdefault("celebrity_lock_attempts", [])
    results: list[dict[str, Any]] = []
    minimum = _number(
        "CELEBRITY_V146_MIN_CELEBRITY_SCORE",
        _number("CELEBRITY_V143_MIN_CELEBRITY_SCORE", 66.0, 45.0, 92.0),
        45.0,
        92.0,
    )
    stop_score = _number("CELEBRITY_V146_STOP_SCORE", 80.0, minimum, 97.0)
    ref_limit = _integer("CELEBRITY_V146_REFERENCE_ATTEMPTS", 4, 1, 8)
    public_refs = [raw for raw in references if raw][:ref_limit]
    if not public_refs:
        return []

    providers = [
        item.strip().casefold()
        for item in str(os.environ.get("CELEBRITY_V146_CELEBRITY_PROVIDERS") or "piapi,openai").split(",")
        if item.strip().casefold() in {"piapi", "openai"}
    ]

    for provider in providers:
        accepted_before = len(results)

        if provider == "piapi" and v139.pi_identity._piapi_key(mod):
            for reference_index, reference in enumerate(public_refs, start=1):
                label = f"{plate['label']}_v146_celebrity_piapi_r{reference_index}_local"
                stage = v139._stage_start(
                    debug,
                    label,
                    "piapi",
                    reference_index=reference_index,
                    task_type="face-swap",
                    strategy="local-face-crop",
                )
                attempt = v145._identity_attempt(
                    label=label,
                    provider="piapi",
                    reference_index=reference_index,
                    mode="face-swap-local-crop",
                )
                debug["celebrity_lock_attempts"].append(attempt)
                try:
                    raw = await _piapi_face_swap_once(mod, plate["output"], reference, "face-swap")
                    problem = v143._plate_problem(raw, label)
                    if problem:
                        raise v139.PipelineError("structural_qc", problem)
                    qc = await _best_identity_score(mod, raw, public_refs)
                    score = float(qc.get("score") or 0)
                    if qc.get("unknown") or score < minimum:
                        raise v139.PipelineError(
                            "celebrity_identity",
                            f"strict celebrity score {score:.1f} below {minimum:.1f}: {qc.get('reason')}",
                        )
                    row = {
                        "label": label,
                        "scene": plate["label"],
                        "scene_provider": plate["provider"],
                        "celebrity_provider": "piapi",
                        "celebrity_identity": round(score, 1),
                        "identity_unknown": False,
                        "reason": qc.get("reason"),
                        "reference_index": int(qc.get("reference_index") or reference_index),
                        "piapi_task_type": "face-swap",
                        "piapi_strategy": _LAST_SWAP_DEBUG.get("strategy"),
                        "output": raw,
                    }
                    results.append(row)
                    debug["identity_candidates"].append({key: value for key, value in row.items() if key != "output"})
                    attempt.update(status="ok", score=round(score, 1), reason=str(qc.get("reason") or "ok")[:500])
                    v139._stage_finish(
                        stage,
                        "ok",
                        score=round(score, 1),
                        bytes=len(raw),
                        strategy=_LAST_SWAP_DEBUG.get("strategy"),
                    )
                    if score >= stop_score:
                        break
                except Exception as exc:
                    attempt.update(status="error", reason=v139._safe_error(exc)[:500])
                    v139._record_error(debug, stage, exc)

        elif provider == "openai" and v139.selfie._openai_key(mod):
            attempts = _integer("CELEBRITY_V146_OPENAI_LOCAL_ATTEMPTS", 2, 1, 3)
            for attempt_index in range(attempts):
                label = f"{plate['label']}_v146_celebrity_openai_local_{attempt_index + 1}"
                stage = v139._stage_start(
                    debug,
                    label,
                    "openai",
                    attempt=attempt_index + 1,
                    strategy="local-face-crop",
                )
                attempt = v145._identity_attempt(
                    label=label,
                    provider="openai",
                    reference_index=1,
                    mode="local-high-fidelity-edit" if attempt_index == 0 else "local-targeted-repair",
                )
                debug["celebrity_lock_attempts"].append(attempt)
                try:
                    raw = await _openai_local_identity_once(
                        mod,
                        plate["output"],
                        public_refs,
                        celebrity_name,
                        repair=bool(attempt_index),
                    )
                    problem = v143._plate_problem(raw, label)
                    if problem:
                        raise v139.PipelineError("structural_qc", problem)
                    qc = await _best_identity_score(mod, raw, public_refs)
                    score = float(qc.get("score") or 0)
                    if qc.get("unknown") or score < minimum:
                        raise v139.PipelineError(
                            "celebrity_identity",
                            f"strict celebrity score {score:.1f} below {minimum:.1f}: {qc.get('reason')}",
                        )
                    row = {
                        "label": label,
                        "scene": plate["label"],
                        "scene_provider": plate["provider"],
                        "celebrity_provider": "openai",
                        "celebrity_identity": round(score, 1),
                        "identity_unknown": False,
                        "reason": qc.get("reason"),
                        "reference_index": int(qc.get("reference_index") or 1),
                        "openai_attempt": attempt_index + 1,
                        "openai_strategy": "local-face-crop",
                        "output": raw,
                    }
                    results.append(row)
                    debug["identity_candidates"].append({key: value for key, value in row.items() if key != "output"})
                    attempt.update(status="ok", score=round(score, 1), reason=str(qc.get("reason") or "ok")[:500])
                    v139._stage_finish(stage, "ok", score=round(score, 1), bytes=len(raw))
                    if score >= stop_score:
                        break
                except Exception as exc:
                    attempt.update(status="error", reason=v139._safe_error(exc)[:500])
                    v139._record_error(debug, stage, exc)

        if len(results) > accepted_before:
            break

    results.sort(key=lambda item: float(item.get("celebrity_identity") or 0), reverse=True)
    return results[:3]


def _scene_prompt(scene: str, aspect: str, variant: int, lighting: str, *, rescue: bool = False) -> str:
    prompt = _ORIGINAL_V144_SCENE_PROMPT(scene, aspect, variant, lighting, rescue=rescue)
    prompt = prompt.replace(
        "The right-side man's face should occupy roughly 3 to 10 percent of the image area",
        "The right-side man's face should occupy roughly 7 to 14 percent of the image area",
    )
    return prompt.replace(
        "chest-up or waist-up, close enough that his unobstructed face is clearly detectable",
        "close head-and-shoulders or chest-up, with an unobstructed face at least 220 pixels tall on a 1024-pixel short side",
    )


async def _run_v146_generation(
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
    try:
        output, debug = await _ORIGINAL_V145_RUN(
            mod,
            user_photo,
            celebrity_refs,
            celebrity_name,
            scene,
            previous_result=previous_result,
            additional_user_refs=additional_user_refs,
        )
        debug = dict(debug or {})
        debug.update({
            "version": VERSION,
            "celebrity_lock_contract": "local-face-crop+single-face-swap+local-openai-fallback+best-reference-qc",
            "piapi_modes": _piapi_modes(),
            "last_swap": dict(_LAST_SWAP_DEBUG),
            "v146_duration_s": round(time.time() - started, 2),
        })
        _LAST_RUN_DEBUG = debug
        for module in (v145, v144, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
        return output, debug
    except Exception as exc:
        debug = dict(getattr(exc, "debug", None) or {})
        debug.update({
            "version": VERSION,
            "celebrity_lock_contract": "local-face-crop+single-face-swap+local-openai-fallback+best-reference-qc",
            "piapi_modes": _piapi_modes(),
            "last_swap": dict(_LAST_SWAP_DEBUG),
            "v146_duration_s": round(time.time() - started, 2),
        })
        _LAST_RUN_DEBUG = debug
        for module in (v145, v144, v143, v142, v139):
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
    output, _ = await _run_v146_generation(
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
    debug = session.get("v142_debug") or _LAST_RUN_DEBUG or v145._LAST_RUN_DEBUG or {}
    selected = debug.get("selected") or {}
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "architecture=strict_preserve_user+local_celebrity_face_lock",
        "user_face_generation=disabled",
        "celebrity_provider_order=piapi,openai",
        "piapi_primary_task=face-swap",
        "piapi_multi_face_swap=blocked",
        "piapi_strategy=local-face-crop+whole-plate-single-face-retry",
        "openai_fallback=local-face-crop-only",
        "identity_qc=best-of-reference-set",
        f"run_id={debug.get('run_id') or '-'}",
        f"state={session.get('state') or '-'}",
        f"scene_candidates={len(debug.get('scene_candidates') or [])}",
        f"celebrity_candidates={len(debug.get('identity_candidates') or [])}",
        f"composite_candidates={len(debug.get('composite_candidates') or [])}",
        f"last_swap={str(debug.get('last_swap') or _LAST_SWAP_DEBUG or '-')[:1800]}",
        f"celebrity_lock_attempts={str(debug.get('celebrity_lock_attempts') or '-')[:1800]}",
        f"delivery_mode={session.get('delivery_mode') or '-'}",
        f"selected={str(selected or '-')[:1400]}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    errors = debug.get("errors") or []
    if errors:
        lines.append("errors:")
        for item in errors[-8:]:
            lines.append(f"- {item.get('stage')} [{item.get('provider')}]: {str(item.get('error') or '')[:320]}")
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    v145.install()
    os.environ.setdefault("CELEBRITY_V146_CELEBRITY_PROVIDERS", "piapi,openai")
    os.environ.setdefault("CELEBRITY_V146_PIAPI_MODES", "face-swap")
    os.environ.setdefault("CELEBRITY_V146_ALLOW_MULTI_FACE_SWAP", "0")
    os.environ.setdefault("CELEBRITY_V146_REFERENCE_ATTEMPTS", "4")
    os.environ.setdefault("CELEBRITY_V146_PROVIDER_CROP_SIDE", "1280")
    os.environ.setdefault("CELEBRITY_V146_TARGET_CROP_FACE_MULTIPLIER", "4.2")
    os.environ.setdefault("CELEBRITY_V146_WHOLE_PLATE_RETRY", "1")
    os.environ.setdefault("CELEBRITY_V146_OPENAI_LOCAL_ATTEMPTS", "2")
    os.environ.setdefault("CELEBRITY_V146_STOP_SCORE", "80")
    os.environ["CELEBRITY_V143_LEGACY_FALLBACK"] = "0"

    v144._scene_prompt = _scene_prompt
    v145._piapi_modes = _piapi_modes
    v145._piapi_face_swap_once = _piapi_face_swap_once
    v145._celebrity_variants = _celebrity_variants
    v143._celebrity_variants = _celebrity_variants
    v142._celebrity_variants = _celebrity_variants
    v139.selfie._run_v146_generation = _run_v146_generation
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
                "diag_selfie_v146",
                "diag_selfie_v145",
                "diag_selfie_v144",
                "diag_selfie_v143",
                "diag_selfie_v142",
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
    "_target_face_region",
    "_face_blend_mask",
    "_merge_local_identity",
    "_piapi_modes",
    "_piapi_face_swap_once",
    "_openai_local_identity_once",
    "_best_identity_score",
    "_celebrity_variants",
    "_run_v146_generation",
    "_diag",
]
