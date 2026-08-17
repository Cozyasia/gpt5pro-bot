# -*- coding: utf-8 -*-
"""V307 production Stage-2 identity: bounded provider race + face-aware PiAPI rescue.

V306 proved transport failover works, but production still failed because Replicate
can legitimately process longer than the reserved 48 s while PiAPI rejected the
large provider canvases with `no face found`. V307 keeps Stage-1 and V305 target
locking untouched. It races only the two remote identity transports using bounded
inputs. PiAPI receives locally re-detected, tight face-centered crops and its result
is composited back into the original target crop before geometry validation.
"""
from __future__ import annotations

import asyncio
import contextlib
import gc
import os
import time
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v295_identity_fidelity_lock as v299

VERSION = "v307-bounded-identity-race-face-aware-piapi-2026-08-17"
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        from neyrobot_prod import selfie_v229_canonical_two_stage as v229
        v229._log(message, *args)


def _tight_face(raw: bytes, *, trace: str, role: str):
    face = fs.source_face_crop(raw, None)
    _log(
        "AI_SELFIE_V307_FACE trace=%s role=%s face=%s crop=%s in=%s out=%s support=%s eyes=%s",
        trace, role, face.face_box, face.crop_box, fs.dims(raw), fs.dims(face.crop_raw), face.support, face.eye_count,
    )
    return face


async def _piapi_face_aware(target_crop: bytes, source_crop: bytes, *, trace: str):
    if not str(os.getenv("PIAPI_API_KEY") or "").strip():
        raise RuntimeError("PIAPI_API_KEY is missing")

    # Qubico's upstream detector is less tolerant than our local detector. Re-lock
    # both faces and send face-dominant canvases instead of the large 1050px crops.
    target_face = _tight_face(target_crop, trace=trace, role="target")
    source_face = _tight_face(source_crop, trace=trace, role="source")
    tight_target = v299._bounded_jpeg(target_face.crop_raw, max_side=900, quality=96)
    tight_source = v299._bounded_jpeg(source_face.crop_raw, max_side=900, quality=96)
    _log(
        "AI_SELFIE_V307_PIAPI trace=%s stage=create_face_aware target=%s source=%s",
        trace, fs.dims(tight_target), fs.dims(tight_source),
    )
    swapped_tight = await fs.piapi_swap_once(tight_target, tight_source, _log, trace=trace)

    # Restore provider output into the exact full target crop expected by the
    # downstream V292 integration/geometry checks.
    base = fs.image(target_crop)
    restored = fs.edge_composite(base, target_face, swapped_tight)
    restored = v299._bounded_jpeg(restored, max_side=1400, quality=97)
    _log(
        "AI_SELFIE_V307_PIAPI trace=%s stage=restored_full_target tight=%s full=%s",
        trace, fs.dims(swapped_tight), fs.dims(restored),
    )
    return restored, "piapi_qubico_v307_face_aware"


async def _replicate_branch(target_crop: bytes, source_crop: bytes, *, trace: str):
    # Keep the V299 quality path. V306 already replaced its Replicate transport
    # with truly asynchronous create+poll semantics.
    return await v299._replicate_fast(target_crop, source_crop, trace=trace)


async def _provider_race_v307(target_crop: bytes, source_crop: bytes, *, trace: str):
    budget = v299._identity_budget()
    started = time.monotonic()
    deadline = started + budget
    tasks: dict[asyncio.Task, str] = {}

    if str(os.getenv("REPLICATE_API_TOKEN") or "").strip():
        tasks[asyncio.create_task(_replicate_branch(target_crop, source_crop, trace=trace))] = "replicate"
    if str(os.getenv("PIAPI_API_KEY") or "").strip():
        tasks[asyncio.create_task(_piapi_face_aware(target_crop, source_crop, trace=trace))] = "piapi_face_aware"
    if not tasks:
        raise RuntimeError("No Face Swap provider configured")

    _log(
        "AI_SELFIE_V307_IDENTITY trace=%s stage=providers_start mode=bounded_race providers=%s budget=%.0fs",
        trace, ",".join(tasks.values()), budget,
    )
    errors: list[str] = []
    pending = set(tasks)
    try:
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0.5:
                break
            done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                break
            for task in done:
                name = tasks[task]
                try:
                    raw, provider = task.result()
                    raw, provider = await v299._validate_result(target_crop, raw, provider, trace=trace)
                    _log(
                        "AI_SELFIE_V307_IDENTITY trace=%s stage=provider_winner provider=%s elapsed=%.2fs",
                        trace, provider, time.monotonic() - started,
                    )
                    for other in pending:
                        other.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                    return raw, provider
                except Exception as exc:
                    errors.append(f"{name}:{type(exc).__name__}:{str(exc)[:220]}")
                    _log(
                        "AI_SELFIE_V307_IDENTITY trace=%s stage=provider_failed provider=%s error_type=%s error=%s remaining=%.1fs",
                        trace, name, type(exc).__name__, str(exc)[:400], max(0.0, deadline-time.monotonic()),
                    )
                    gc.collect()
        raise TimeoutError("; ".join(errors) or f"identity provider race exceeded {budget:.0f}s")
    finally:
        leftovers = [t for t in tasks if not t.done()]
        for task in leftovers:
            task.cancel()
        if leftovers:
            await asyncio.gather(*leftovers, return_exceptions=True)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    v299._provider_sequential = _provider_race_v307
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V307"
    setattr(terminal, "_v307_identity_race", True)
    setattr(terminal, "_v307_face_aware_piapi", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V307 bounded identity race + face-aware PiAPI installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
