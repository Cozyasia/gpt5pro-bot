# -*- coding: utf-8 -*-
"""V299 low-memory provider-adapted identity for AI Selfie.

Production priorities:
- photo #3 is the only identity source;
- Replicate/InSwapper is the primary provider;
- PiAPI is sequential fallback, not a concurrent race;
- provider canvases are bounded before upload and before local face validation;
- no 2x/4x remote output is retained when the final target crop is much smaller;
- hard identity SLA is 80 s by default (65..95 configurable).

The previous concurrent V296 race duplicated supersampled images in memory and the
Replicate branch returned ~2400x2800 PNGs which were then decoded again by the local
geometry validator. On a small Render instance that can cross the process memory
limit. V299 keeps enough pixels for a sharp 799x927-class face crop without carrying
multi-megapixel intermediates through the whole pipeline.
"""
from __future__ import annotations

import asyncio
import contextlib
import gc
import os
import time
from io import BytesIO
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v289_native_identity_primary as v289
from neyrobot_prod import selfie_v290_gaze_quality_singleflight as v292

VERSION = "v299-low-memory-sequential-identity-2026-08-17"
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        from neyrobot_prod import selfie_v229_canonical_two_stage as v229
        v229._log(message, *args)


def _identity_budget() -> float:
    try:
        value = float(os.getenv("AI_SELFIE_IDENTITY_TIMEOUT_S") or "80")
    except Exception:
        value = 80.0
    return max(65.0, min(95.0, value))


def _source_eye_evidence(source_crop: bytes) -> tuple[bool, str]:
    try:
        face = fs.source_face_crop(source_crop, None)
        eyes = int(getattr(face, "eye_count", 0))
        support = int(getattr(face, "support", 0))
        fw = int(face.face_box[2]); fh = int(face.face_box[3])
        good = bool((eyes >= 1 or support >= 4) and fw >= 220 and fh >= 220)
        return good, f"eyes={eyes} support={support} face={face.face_box}"
    except Exception as exc:
        return False, f"{type(exc).__name__}:{str(exc)[:300]}"


def _bounded_jpeg(raw: bytes, *, max_side: int = 1400, quality: int = 96) -> bytes:
    """Bound provider output before Haar/OpenCV validation to avoid Render OOM."""
    data = bytes(raw or b"")
    try:
        from PIL import Image, ImageOps
        img = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
        if max(img.size) <= max_side:
            return data
        resampling = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        img.thumbnail((max_side, max_side), resampling)
        out = BytesIO()
        img.save(out, "JPEG", quality=quality, subsampling=0, optimize=False, progressive=False)
        result = out.getvalue()
        del img
        gc.collect()
        return result if len(result) > 1024 else data
    except Exception:
        return data


async def _replicate_fast(target_crop: bytes, source_crop: bytes, *, trace: str) -> tuple[bytes, str]:
    token = str(os.getenv("REPLICATE_API_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN is missing")
    from neyrobot_prod import selfie_v252_faceswap_quality_diag as ins

    # The final crop is usually below 1000 px on the long side. 1100 px provider
    # inputs retain face detail without creating a 2400x2800 restored PNG.
    target = terminal._supersample(target_crop, min_long_side=1100)
    source = terminal._supersample(source_crop, min_long_side=1100)
    inputs = {
        "upscale": 1,
        "source_img": ins._data_url(source),
        "target_img": ins._data_url(target),
        "face_restore": True,
        "face_upsample": True,
        "source_indexes": "0",
        "target_indexes": "0",
        "background_enhance": False,
        "codeformer_fidelity": 0.94,
    }
    _log(
        "AI_SELFIE_V299_IDENTITY trace=%s provider=replicate stage=create target=%s source=%s upscale=1 restore=true memory_bounded=true",
        trace, fs.dims(target), fs.dims(source),
    )
    raw = await ins._replicate_swap_once(
        version=ins.REPLICATE_INSWAPPER_VERSION,
        inputs=inputs,
        trace=trace,
        label="v299_memory_bounded_inswapper",
    )
    if len(raw) < 1024 or fs.sha(raw) == fs.sha(target):
        raise RuntimeError("Replicate returned unchanged/empty identity image")
    bounded = _bounded_jpeg(raw, max_side=1400, quality=97)
    _log(
        "AI_SELFIE_V299_IDENTITY trace=%s provider=replicate stage=bounded raw_dims=%s raw_bytes=%s out_dims=%s out_bytes=%s",
        trace, fs.dims(raw), len(raw), fs.dims(bounded), len(bounded),
    )
    del raw, target, source
    gc.collect()
    return bounded, "replicate_inswapper_v299_bounded"


async def _piapi_fast(target_crop: bytes, source_crop: bytes, *, trace: str) -> tuple[bytes, str]:
    if not str(os.getenv("PIAPI_API_KEY") or "").strip():
        raise RuntimeError("PIAPI_API_KEY is missing")
    # Fallback only; do not keep a second provider canvas alive concurrently.
    target = terminal._supersample(target_crop, min_long_side=1050)
    source = terminal._supersample(source_crop, min_long_side=1050)
    raw = await fs.piapi_swap_once(target, source, _log, trace=trace)
    if len(raw) < 1024 or fs.sha(raw) == fs.sha(target):
        raise RuntimeError("PiAPI returned unchanged/empty identity image")
    bounded = _bounded_jpeg(raw, max_side=1400, quality=97)
    del raw, target, source
    gc.collect()
    return bounded, "piapi_qubico_v299_fallback"


async def _validate_result(target_crop: bytes, raw: bytes, provider: str, *, trace: str) -> tuple[bytes, str]:
    bounded = _bounded_jpeg(raw, max_side=1400, quality=97)
    geometry_ok, geometry_reason = v289._geometry_status(target_crop, bounded, _log, trace=trace)
    if not geometry_ok:
        raise RuntimeError(f"{provider} geometry rejected: {geometry_reason}")
    return bounded, provider


async def _provider_sequential(target_crop: bytes, source_crop: bytes, *, trace: str) -> tuple[bytes, str]:
    budget = _identity_budget()
    started = time.monotonic()
    deadline = started + budget
    providers: list[tuple[str, Any]] = []
    if str(os.getenv("REPLICATE_API_TOKEN") or "").strip():
        providers.append(("replicate", _replicate_fast))
    if str(os.getenv("PIAPI_API_KEY") or "").strip():
        providers.append(("piapi", _piapi_fast))
    if not providers:
        raise RuntimeError("No Face Swap provider configured")

    _log(
        "AI_SELFIE_V299_IDENTITY trace=%s stage=providers_start mode=sequential providers=%s budget=%.0fs memory_bounded=true",
        trace, ",".join(name for name, _ in providers), budget,
    )
    errors: list[str] = []
    for name, fn in providers:
        remaining = deadline - time.monotonic()
        if remaining <= 1.0:
            break
        try:
            raw, provider = await asyncio.wait_for(fn(target_crop, source_crop, trace=trace), timeout=remaining)
            raw, provider = await _validate_result(target_crop, raw, provider, trace=trace)
            _log(
                "AI_SELFIE_V299_IDENTITY trace=%s stage=provider_winner provider=%s elapsed=%.2fs",
                trace, provider, time.monotonic() - started,
            )
            return raw, provider
        except asyncio.TimeoutError:
            errors.append(f"{name}:TimeoutError")
            break
        except Exception as exc:
            errors.append(f"{name}:{type(exc).__name__}:{str(exc)[:220]}")
            _log(
                "AI_SELFIE_V299_IDENTITY trace=%s stage=provider_failed provider=%s error_type=%s error=%s",
                trace, name, type(exc).__name__, str(exc)[:400],
            )
            gc.collect()
    raise RuntimeError("; ".join(errors) or "identity providers exceeded budget")


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    source_good, source_reason = _source_eye_evidence(source_crop)
    started = time.monotonic()
    budget = _identity_budget()
    log(
        "AI_SELFIE_V299_IDENTITY trace=%s stage=start source_photo3=true source_eye_evidence=%s detail=%s target=%s source=%s budget=%.0fs source_paste=false memory_bounded=true",
        trace, source_good, source_reason, fs.dims(target_crop), fs.dims(source_crop), budget,
    )
    try:
        candidate, provider = await asyncio.wait_for(
            _provider_sequential(target_crop, source_crop, trace=trace),
            timeout=budget + 1.0,
        )
    except asyncio.TimeoutError as exc:
        log(
            "AI_SELFIE_V299_IDENTITY trace=%s stage=timeout elapsed=%.2fs budget=%.0fs fail_fast=true",
            trace, time.monotonic() - started, budget,
        )
        raise TimeoutError(f"AI Selfie identity transfer exceeded production SLA ({budget:.0f}s)") from exc

    if source_good:
        log(
            "AI_SELFIE_V299_IDENTITY trace=%s stage=success provider=%s gaze=provider_preserved source_paste=false elapsed=%.2fs out=%s",
            trace, provider, time.monotonic() - started, fs.dims(candidate),
        )
        return candidate, str(provider) + "+v299_gaze_preserved"

    corrected = v292._iris_only_camera_gaze(target_crop, candidate, log, trace=trace)
    log(
        "AI_SELFIE_V299_IDENTITY trace=%s stage=success provider=%s gaze=iris_fallback source_paste=false elapsed=%.2fs out=%s",
        trace, provider, time.monotonic() - started, fs.dims(corrected),
    )
    return corrected, str(provider) + "+v299_iris_fallback"


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._identity_swap = _identity_swap
    setattr(terminal, "_v296_fast_provider_race", False)
    setattr(terminal, "_v299_low_memory_identity", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V299 low-memory sequential identity installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
