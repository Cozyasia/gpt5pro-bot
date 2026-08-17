# -*- coding: utf-8 -*-
"""V306 production identity transport fix.

The V305 test proved Stage-1 and target acquisition now reach identity transfer,
but Replicate still timed out. Root cause: the shared Replicate helper sends
`Prefer: wait=60`, so the create POST can sit open for about a minute before the
prediction id is returned. The outer identity SLA then expires before polling can
finish.

V306 makes Replicate truly asynchronous (no Prefer wait), polls immediately, and
reserves time for PiAPI fallback. A Replicate timeout no longer aborts the provider
loop; it falls through to PiAPI within the same request budget.
"""
from __future__ import annotations

import asyncio
import contextlib
import gc
import os
import time
from typing import Any

import httpx

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v252_faceswap_quality_diag as ins
from neyrobot_prod import selfie_v295_identity_fidelity_lock as v299
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal

VERSION = "v306-async-replicate-provider-failover-2026-08-17"
_INSTALLED = False


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        from neyrobot_prod import selfie_v229_canonical_two_stage as v229
        v229._log(message, *args)


def _prediction_output_url(payload: dict[str, Any]) -> str:
    output = payload.get("output") if isinstance(payload, dict) else None
    if isinstance(output, str) and output.startswith("http"):
        return output
    if isinstance(output, list):
        for item in output:
            if isinstance(item, str) and item.startswith("http"):
                return item
    if isinstance(output, dict):
        for key in ("url", "image", "image_url", "output_url"):
            value = output.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
    return ""


async def _replicate_swap_once_async(*, version: str, inputs: dict[str, Any], trace: str, label: str) -> bytes:
    token = str(os.getenv("REPLICATE_API_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN is missing")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        # Intentionally NO `Prefer: wait=60`: production must receive the
        # prediction id immediately and poll under our own SLA.
    }
    timeout = httpx.Timeout(connect=10.0, read=20.0, write=20.0, pool=10.0)
    started = time.monotonic()
    _log("AI_SELFIE_V306_REPLICATE trace=%s stage=create_async label=%s", trace, label)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.post(
            ins.REPLICATE_PREDICTIONS_URL,
            headers=headers,
            json={"version": version, "input": inputs},
        )
        response.raise_for_status()
        payload = response.json() or {}
        prediction_id = str(payload.get("id") or "")
        status = str(payload.get("status") or "").lower()
        get_url = str(((payload.get("urls") or {}) if isinstance(payload, dict) else {}).get("get") or "")
        _log(
            "AI_SELFIE_V306_REPLICATE trace=%s stage=created_async id=%s status=%s elapsed=%.2fs",
            trace, prediction_id, status, time.monotonic() - started,
        )
        if not prediction_id and not get_url and status not in {"succeeded", "failed", "canceled"}:
            raise RuntimeError("Replicate returned no prediction id/get URL")

        deadline = time.monotonic() + 70.0
        last_status = status
        while status not in {"succeeded", "failed", "canceled"}:
            if time.monotonic() >= deadline:
                raise TimeoutError("Replicate prediction exceeded V306 polling deadline")
            await asyncio.sleep(1.5)
            if not get_url:
                get_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
            check = await client.get(get_url, headers={"Authorization": f"Bearer {token}"})
            check.raise_for_status()
            payload = check.json() or {}
            status = str(payload.get("status") or "").lower()
            if status != last_status:
                _log(
                    "AI_SELFIE_V306_REPLICATE trace=%s stage=poll id=%s status=%s elapsed=%.2fs",
                    trace, prediction_id, status, time.monotonic() - started,
                )
                last_status = status

        if status != "succeeded":
            raise RuntimeError(
                f"Replicate {label} ended with status={status}: {str(payload.get('error') or '')[:500]}"
            )
        output_url = _prediction_output_url(payload)
        if not output_url:
            raise RuntimeError(f"Replicate {label} succeeded without output URL")
        out = await client.get(output_url)
        out.raise_for_status()
        raw = bytes(out.content)
        if len(raw) < 1024:
            raise RuntimeError(f"Replicate {label} returned empty output")
        _log(
            "AI_SELFIE_V306_REPLICATE trace=%s stage=success elapsed=%.2fs dims=%s bytes=%s sha=%s",
            trace, time.monotonic() - started, fs.dims(raw), len(raw), fs.sha(raw),
        )
        return raw


async def _provider_sequential_v306(target_crop: bytes, source_crop: bytes, *, trace: str):
    budget = v299._identity_budget()
    started = time.monotonic()
    deadline = started + budget
    providers: list[tuple[str, Any]] = []
    if str(os.getenv("REPLICATE_API_TOKEN") or "").strip():
        providers.append(("replicate", v299._replicate_fast))
    if str(os.getenv("PIAPI_API_KEY") or "").strip():
        providers.append(("piapi", v299._piapi_fast))
    if not providers:
        raise RuntimeError("No Face Swap provider configured")

    _log(
        "AI_SELFIE_V306_IDENTITY trace=%s stage=providers_start mode=sequential_failover providers=%s budget=%.0fs",
        trace, ",".join(name for name, _ in providers), budget,
    )
    errors: list[str] = []
    for index, (name, fn) in enumerate(providers):
        remaining = deadline - time.monotonic()
        if remaining <= 2.0:
            break

        providers_left = len(providers) - index - 1
        if name == "replicate" and providers_left:
            # Historical processing after prediction creation is ~20-30 s. Give
            # Replicate enough time to win, but reserve a real fallback window.
            timeout_s = min(48.0, max(24.0, remaining - 27.0))
        else:
            timeout_s = max(2.0, remaining)

        _log(
            "AI_SELFIE_V306_IDENTITY trace=%s stage=provider_attempt provider=%s timeout=%.1fs remaining=%.1fs",
            trace, name, timeout_s, remaining,
        )
        try:
            raw, provider = await asyncio.wait_for(
                fn(target_crop, source_crop, trace=trace),
                timeout=timeout_s,
            )
            raw, provider = await v299._validate_result(target_crop, raw, provider, trace=trace)
            _log(
                "AI_SELFIE_V306_IDENTITY trace=%s stage=provider_winner provider=%s elapsed=%.2fs",
                trace, provider, time.monotonic() - started,
            )
            return raw, provider
        except (asyncio.TimeoutError, TimeoutError) as exc:
            errors.append(f"{name}:TimeoutError")
            _log(
                "AI_SELFIE_V306_IDENTITY trace=%s stage=provider_timeout provider=%s elapsed=%.2fs fallback_next=%s",
                trace, name, time.monotonic() - started, bool(providers_left),
            )
            gc.collect()
            continue
        except Exception as exc:
            errors.append(f"{name}:{type(exc).__name__}:{str(exc)[:220]}")
            _log(
                "AI_SELFIE_V306_IDENTITY trace=%s stage=provider_failed provider=%s error_type=%s error=%s fallback_next=%s",
                trace, name, type(exc).__name__, str(exc)[:400], bool(providers_left),
            )
            gc.collect()
            continue

    raise RuntimeError("; ".join(errors) or "identity providers exceeded budget")


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    # V299 calls this symbol dynamically from selfie_v252_faceswap_quality_diag,
    # so replacing it here changes only transport semantics, not swap quality.
    ins._replicate_swap_once = _replicate_swap_once_async
    v299._provider_sequential = _provider_sequential_v306
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V306"
    setattr(terminal, "_v306_async_replicate", True)
    setattr(terminal, "_v306_provider_failover", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V306 async Replicate + provider failover installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
