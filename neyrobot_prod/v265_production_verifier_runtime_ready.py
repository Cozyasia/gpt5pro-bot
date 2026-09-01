# -*- coding: utf-8 -*-
"""Temporary readiness wrapper for the one-shot V265 production verifier.

The previous verifier waited on legacy runtime metadata that stays stale even when the
actual V265 production owner is correctly installed. This wrapper validates concrete
runtime state instead: running process/port, V265 bootstrap, exact transfer/delivery
owners, dense68 availability, production package flags, and Gemini configuration.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

_SENTINEL = Path("/data/v265_prod_verify_pr104_fc2529df_runtime_ready_v2.once")
_ARTIFACT_DIR = Path("/data/v265_prod_verify_pr104_fc2529df_runtime_ready_v2")
_STARTED = False


def _emit(message: str) -> None:
    print(message, flush=True)


def _write_state(payload: dict[str, Any]) -> None:
    _SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SENTINEL.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with tmp.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(tmp, _SENTINEL)


def _claim_pending() -> bool:
    _SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(_SENTINEL), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with contextlib.suppress(Exception):
            state = json.loads(_SENTINEL.read_text(encoding="utf-8"))
            _emit(
                "AI_SELFIE_V265_VERIFY status=skipped reason=sentinel_exists "
                f"state={state.get('status', 'unknown')} sentinel={_SENTINEL}"
            )
            return False
        _emit(f"AI_SELFIE_V265_VERIFY status=skipped reason=sentinel_exists sentinel={_SENTINEL}")
        return False
    payload = {
        "status": "pending",
        "pid": os.getpid(),
        "time": time.time(),
        "git_commit": os.environ.get("RENDER_GIT_COMMIT", ""),
    }
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.flush()
        os.fsync(handle.fileno())
    _emit(f"AI_SELFIE_V265_VERIFY status=pending pid={os.getpid()} sentinel={_SENTINEL}")
    return True


def _runtime() -> tuple[str, Any | None]:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return name, mod
    return "", None


def _port_open(runtime: Any | None) -> bool:
    if runtime is None:
        return False
    try:
        port = int(getattr(runtime, "PORT", 10000) or 10000)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.20)
            return sock.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def _readiness() -> tuple[str, Any | None, dict[str, Any]]:
    import neyrobot_prod as package
    from neyrobot_prod import dense68_engine_v265 as engine
    from neyrobot_prod import selfie_v211_delivery as delivery
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer
    from neyrobot_prod import selfie_v265_single_owner as v265

    runtime_name, runtime = _runtime()
    owner = getattr(transfer, "_true_face_transfer", None)
    delivery_owner = getattr(delivery, "_deliver", None)
    runtime_version = str(getattr(runtime, "AI_SELFIE_RUNTIME_VERSION", "") or "") if runtime is not None else ""
    runtime_route = str(getattr(runtime, "CELEBRITY_SELFIE_ROUTE", "") or "") if runtime is not None else ""

    checks = {
        "process_started": bool(
            os.getpid() > 1
            and runtime is not None
            and callable(getattr(runtime, "main", None))
            and bool(str(getattr(runtime, "BOT_TOKEN", "") or "").strip())
            and _port_open(runtime)
        ),
        "bootstrap_v265": bool(
            getattr(package, "PRODUCTION_SELFIE_RUNTIME", "") == "v265"
            and getattr(package, "V265_PRODUCTION_ACCEPTED", False) is True
            and getattr(package, "V264_PRODUCTION_ACCEPTED", True) is False
            and getattr(package, "V263_PRODUCTION_ACCEPTED", True) is False
            and getattr(v265, "_INSTALLED", False)
        ),
        "owner_registered": bool(owner is v265._true_face_transfer_v265),
        "delivery_owner_registered": bool(delivery_owner is v265._deliver_original_only),
        "dense68_available": bool(
            getattr(engine, "VERSION", "") == v265.VERSION
            and callable(getattr(engine, "transfer_attempt", None))
            and callable(getattr(engine, "apply_ocular_lock", None))
        ),
        "gemini_configured": bool(os.environ.get("GEMINI_IMAGE_API_KEY", "").strip()),
        # Diagnostic only: these legacy metadata fields are known to remain stale.
        "legacy_runtime_marker_matches_v265": bool(runtime_version == v265.VERSION),
        "legacy_runtime_route_matches_v265": bool(runtime_route == "v265-single-owner-dense68-roi-local-only-lossless-document"),
    }
    checks["safe_to_begin"] = all(
        checks[key]
        for key in (
            "process_started",
            "bootstrap_v265",
            "owner_registered",
            "delivery_owner_registered",
            "dense68_available",
            "gemini_configured",
        )
    )
    details = {
        **checks,
        "runtime_name": runtime_name,
        "runtime_version": runtime_version,
        "runtime_route": runtime_route,
        "owner_module": getattr(owner, "__module__", ""),
        "owner_name": getattr(owner, "__name__", ""),
        "engine": getattr(engine, "__name__", ""),
    }
    return runtime_name, runtime, details


def _worker() -> None:
    runtime_name = ""
    runtime = None
    readiness: dict[str, Any] = {}
    deadline = time.monotonic() + 180.0
    last_report = 0.0
    while time.monotonic() < deadline:
        try:
            runtime_name, runtime, readiness = _readiness()
            if bool(readiness.get("safe_to_begin")):
                break
            now = time.monotonic()
            if now - last_report >= 15.0:
                last_report = now
                _emit("AI_SELFIE_V265_VERIFY_READINESS " + json.dumps(readiness, sort_keys=True))
        except Exception as exc:
            now = time.monotonic()
            if now - last_report >= 15.0:
                last_report = now
                _emit(f"AI_SELFIE_V265_VERIFY_READINESS error={type(exc).__name__}:{str(exc)[:500]}")
        time.sleep(2.0)

    if runtime is None or not bool(readiness.get("safe_to_begin")):
        _write_state({
            "status": "failed",
            "phase": "runtime_wait",
            "pid": os.getpid(),
            "readiness": readiness,
        })
        _emit(
            "AI_SELFIE_V265_VERIFY status=failed phase=runtime_wait error=V265_runtime_not_ready "
            + json.dumps(readiness, sort_keys=True)
        )
        return

    _emit("AI_SELFIE_V265_VERIFY_READINESS status=ready " + json.dumps(readiness, sort_keys=True))
    _write_state({
        "status": "started",
        "pid": os.getpid(),
        "time": time.time(),
        "git_commit": os.environ.get("RENDER_GIT_COMMIT", ""),
        "runtime_name": runtime_name,
        "readiness": readiness,
    })
    _emit(
        f"AI_SELFIE_V265_VERIFY status=started pid={os.getpid()} sentinel={_SENTINEL} "
        "heavy_started_after_sentinel=true target_short=1856 target_long=2304"
    )

    try:
        from neyrobot_prod import v265_production_verifier as base
        base._SENTINEL = _SENTINEL
        base._ARTIFACT_DIR = _ARTIFACT_DIR
        asyncio.run(base._verify_async(runtime))
    except Exception as exc:
        _write_state({
            "status": "failed",
            "phase": "production_validation",
            "pid": os.getpid(),
            "error": f"{type(exc).__name__}:{str(exc)[:1200]}",
        })
        _emit(
            f"AI_SELFIE_V265_PROD_VERIFY status=failed pid={os.getpid()} "
            f"error={type(exc).__name__}:{str(exc)[:1200]}"
        )


def start_once() -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    if not _claim_pending():
        return
    thread = threading.Thread(target=_worker, name="v265-production-verifier-ready", daemon=True)
    thread.start()


__all__ = ["start_once"]
