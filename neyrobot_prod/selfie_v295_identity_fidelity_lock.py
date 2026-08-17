# -*- coding: utf-8 -*-
"""V296 low-latency provider-adapted identity for AI Selfie.

Production priorities:
- photo #3 is the only identity source;
- no source-pixel/affine face paste;
- do not traverse the historical nested V285/V288/V289 fallback chain;
- start available Face Swap providers concurrently and take the first valid result;
- enforce a hard identity-transfer SLA (95 s default, 70..120 configurable);
- preserve provider-adapted gaze when source eye evidence is strong;
- fail fast when providers cannot finish instead of holding a Telegram request for
  many minutes.

The concurrent race intentionally trades some provider cost for production latency.
Set AI_SELFIE_PROVIDER_RACE=0 to use Replicate first and PiAPI second if cost becomes
more important than latency.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v289_native_identity_primary as v289
from neyrobot_prod import selfie_v290_gaze_quality_singleflight as v292

VERSION = "v296-fast-provider-race-identity-2026-08-17"
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        from neyrobot_prod import selfie_v229_canonical_two_stage as v229
        v229._log(message, *args)


def _truthy(name: str, default: str = "1") -> bool:
    return str(os.getenv(name) or default).strip().lower() not in {"0", "false", "off", "no"}


def _identity_budget() -> float:
    try:
        value = float(os.getenv("AI_SELFIE_IDENTITY_TIMEOUT_S") or "95")
    except Exception:
        value = 95.0
    return max(70.0, min(120.0, value))


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


async def _replicate_fast(target_crop: bytes, source_crop: bytes, *, trace: str) -> tuple[bytes, str]:
    token = str(os.getenv("REPLICATE_API_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN is missing")
    from neyrobot_prod import selfie_v252_faceswap_quality_diag as ins

    # Keep enough resolution for a sharp face without the old 1800px/4x cost/latency.
    target = terminal._supersample(target_crop, min_long_side=1400)
    source = terminal._supersample(source_crop, min_long_side=1400)
    inputs = {
        "upscale": 2,
        "source_img": ins._data_url(source),
        "target_img": ins._data_url(target),
        "face_restore": True,
        "face_upsample": True,
        "source_indexes": "0",
        "target_indexes": "0",
        "background_enhance": False,
        "codeformer_fidelity": 0.92,
    }
    _log(
        "AI_SELFIE_V296_IDENTITY trace=%s provider=replicate stage=create target=%s source=%s upscale=2 restore=true",
        trace, fs.dims(target), fs.dims(source),
    )
    raw = await ins._replicate_swap_once(
        version=ins.REPLICATE_INSWAPPER_VERSION,
        inputs=inputs,
        trace=trace,
        label="v296_fast_inswapper",
    )
    if len(raw) < 1024 or fs.sha(raw) == fs.sha(target):
        raise RuntimeError("Replicate returned unchanged/empty identity image")
    return raw, "replicate_inswapper_v296_fast"


async def _piapi_fast(target_crop: bytes, source_crop: bytes, *, trace: str) -> tuple[bytes, str]:
    if not str(os.getenv("PIAPI_API_KEY") or "").strip():
        raise RuntimeError("PIAPI_API_KEY is missing")
    # Smaller provider canvas avoids the old 1600px+ repeated transport overhead.
    target = terminal._supersample(target_crop, min_long_side=1300)
    source = terminal._supersample(source_crop, min_long_side=1300)
    raw = await fs.piapi_swap_once(target, source, _log, trace=trace)
    if len(raw) < 1024 or fs.sha(raw) == fs.sha(target):
        raise RuntimeError("PiAPI returned unchanged/empty identity image")
    return raw, "piapi_qubico_v296_fast"


async def _validate_result(target_crop: bytes, task: asyncio.Task, *, trace: str) -> tuple[bytes, str]:
    raw, provider = await task
    geometry_ok, geometry_reason = v289._geometry_status(target_crop, raw, _log, trace=trace)
    if not geometry_ok:
        raise RuntimeError(f"{provider} geometry rejected: {geometry_reason}")
    return raw, provider


async def _provider_race(target_crop: bytes, source_crop: bytes, *, trace: str) -> tuple[bytes, str]:
    budget = _identity_budget()
    started = time.monotonic()
    factories = []
    if str(os.getenv("REPLICATE_API_TOKEN") or "").strip():
        factories.append(("replicate", _replicate_fast))
    if str(os.getenv("PIAPI_API_KEY") or "").strip():
        factories.append(("piapi", _piapi_fast))
    if not factories:
        raise RuntimeError("No Face Swap provider configured")

    race = _truthy("AI_SELFIE_PROVIDER_RACE", "1") and len(factories) > 1
    _log(
        "AI_SELFIE_V296_IDENTITY trace=%s stage=providers_start mode=%s providers=%s budget=%.0fs",
        trace, "race" if race else "sequential", ",".join(name for name, _ in factories), budget,
    )

    if not race:
        errors = []
        deadline = time.monotonic() + budget
        for name, fn in factories:
            remaining = deadline - time.monotonic()
            if remaining <= 1.0:
                break
            try:
                task = asyncio.create_task(fn(target_crop, source_crop, trace=trace))
                raw, provider = await asyncio.wait_for(_validate_result(target_crop, task, trace=trace), timeout=remaining)
                _log("AI_SELFIE_V296_IDENTITY trace=%s stage=provider_winner provider=%s elapsed=%.2fs", trace, provider, time.monotonic()-started)
                return raw, provider
            except Exception as exc:
                errors.append(f"{name}:{type(exc).__name__}:{str(exc)[:180]}")
        raise RuntimeError("; ".join(errors) or "identity providers exceeded budget")

    tasks: dict[asyncio.Task, str] = {}
    for name, fn in factories:
        task = asyncio.create_task(fn(target_crop, source_crop, trace=trace))
        tasks[task] = name

    errors = []
    deadline = time.monotonic() + budget
    try:
        pending = set(tasks)
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"identity provider race exceeded {budget:.0f}s")
            done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise TimeoutError(f"identity provider race exceeded {budget:.0f}s")
            for task in done:
                name = tasks.get(task, "provider")
                try:
                    raw, provider = await _validate_result(target_crop, task, trace=trace)
                    _log(
                        "AI_SELFIE_V296_IDENTITY trace=%s stage=provider_winner provider=%s elapsed=%.2fs losers_cancelled=%s",
                        trace, provider, time.monotonic() - started, len(pending),
                    )
                    for loser in pending:
                        loser.cancel()
                    return raw, provider
                except Exception as exc:
                    errors.append(f"{name}:{type(exc).__name__}:{str(exc)[:220]}")
                    _log("AI_SELFIE_V296_IDENTITY trace=%s stage=provider_failed provider=%s error_type=%s error=%s", trace, name, type(exc).__name__, str(exc)[:400])
        raise RuntimeError("; ".join(errors) or "all identity providers failed")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks.keys(), return_exceptions=True)


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    source_good, source_reason = _source_eye_evidence(source_crop)
    started = time.monotonic()
    budget = _identity_budget()
    log(
        "AI_SELFIE_V296_IDENTITY trace=%s stage=start source_photo3=true source_eye_evidence=%s detail=%s target=%s source=%s budget=%.0fs source_paste=false",
        trace, source_good, source_reason, fs.dims(target_crop), fs.dims(source_crop), budget,
    )
    try:
        candidate, provider = await asyncio.wait_for(
            _provider_race(target_crop, source_crop, trace=trace),
            timeout=budget + 2.0,
        )
    except asyncio.TimeoutError as exc:
        log("AI_SELFIE_V296_IDENTITY trace=%s stage=timeout elapsed=%.2fs budget=%.0fs fail_fast=true", trace, time.monotonic()-started, budget)
        raise TimeoutError(f"AI Selfie identity transfer exceeded production SLA ({budget:.0f}s)") from exc

    if source_good:
        log(
            "AI_SELFIE_V296_IDENTITY trace=%s stage=success provider=%s gaze=provider_preserved source_paste=false elapsed=%.2fs out=%s",
            trace, provider, time.monotonic()-started, fs.dims(candidate),
        )
        return candidate, str(provider) + "+v296_gaze_preserved"

    corrected = v292._iris_only_camera_gaze(target_crop, candidate, log, trace=trace)
    log(
        "AI_SELFIE_V296_IDENTITY trace=%s stage=success provider=%s gaze=iris_fallback source_paste=false elapsed=%.2fs out=%s",
        trace, provider, time.monotonic()-started, fs.dims(corrected),
    )
    return corrected, str(provider) + "+v296_iris_fallback"


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._identity_swap = _identity_swap
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V296"
    setattr(terminal, "_v295_source_photo3_likeness_lock", False)
    setattr(terminal, "_v295b_provider_adapted_identity", False)
    setattr(terminal, "_v296_fast_provider_race", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V296 fast provider-race identity installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
