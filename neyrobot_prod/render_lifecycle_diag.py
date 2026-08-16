# -*- coding: utf-8 -*-
"""Render/PTB lifecycle diagnostics.

This module is intentionally observational: it does not alter Telegram routing,
AI Selfie providers, or business logic.  It logs process identity, periodic
heartbeats, PTB stop calls, and POSIX signals registered by python-telegram-bot
so Render deploy/restart shutdowns can be distinguished from application crashes.
"""
from __future__ import annotations

import atexit
import asyncio
import os
import signal
import threading
import time
import traceback
from typing import Any

VERSION = "v282-render-lifecycle-diagnostic-2026-08-16"
_INSTALLED = False
_STARTED_AT = time.time()
_PID = os.getpid()
_STOP_SEEN = False


def _render_meta() -> str:
    keys = (
        "RENDER_SERVICE_ID",
        "RENDER_SERVICE_NAME",
        "RENDER_INSTANCE_ID",
        "RENDER_GIT_COMMIT",
        "RENDER_EXTERNAL_HOSTNAME",
        "RENDER",
    )
    parts: list[str] = []
    for key in keys:
        value = str(os.getenv(key) or "").strip()
        if value:
            parts.append(f"{key}={value}")
    return " ".join(parts) if parts else "render_meta=unavailable"


def _emit(stage: str, **extra: Any) -> None:
    uptime = max(0.0, time.time() - _STARTED_AT)
    suffix = " ".join(f"{k}={v}" for k, v in extra.items() if v is not None)
    print(
        f"[neyrobot-prod] RENDER_LIFECYCLE version={VERSION} stage={stage} "
        f"pid={_PID} uptime={uptime:.1f}s {_render_meta()} {suffix}".rstrip(),
        flush=True,
    )


def _heartbeat() -> None:
    interval = max(15.0, float(os.getenv("RENDER_LIFECYCLE_HEARTBEAT_S") or "30"))
    while True:
        time.sleep(interval)
        _emit("heartbeat")


def _wrap_application_stop() -> None:
    try:
        from telegram.ext import Application
    except Exception as exc:
        _emit("ptb_import_failed", error=repr(exc))
        return

    original = getattr(Application, "stop", None)
    if not callable(original) or getattr(original, "_neyrobot_lifecycle_wrapped", False):
        return

    async def traced_stop(self: Any, *args: Any, **kwargs: Any):
        global _STOP_SEEN
        _STOP_SEEN = True
        _emit("ptb_stop_enter")
        try:
            return await original(self, *args, **kwargs)
        finally:
            _emit("ptb_stop_exit")

    setattr(traced_stop, "_neyrobot_lifecycle_wrapped", True)
    Application.stop = traced_stop


def _wrap_run_webhook_signal_registration() -> None:
    """Wrap the signal callbacks PTB itself registers, without changing semantics."""
    try:
        from telegram.ext import Application
    except Exception:
        return

    original = getattr(Application, "run_webhook", None)
    if not callable(original) or getattr(original, "_neyrobot_lifecycle_wrapped", False):
        return

    def traced_run_webhook(self: Any, *args: Any, **kwargs: Any):
        loop = None
        original_add = None
        patched = False
        try:
            loop = asyncio.get_event_loop()
            original_add = getattr(loop, "add_signal_handler", None)
            if callable(original_add):
                def traced_add_signal_handler(sig: int, callback: Any, *cb_args: Any):
                    sig_name = getattr(signal.Signals(sig), "name", str(sig))

                    def traced_callback(*runtime_args: Any):
                        _emit("signal_received", signal=sig_name)
                        return callback(*runtime_args)

                    return original_add(sig, traced_callback, *cb_args)

                try:
                    setattr(loop, "add_signal_handler", traced_add_signal_handler)
                    patched = True
                    _emit("signal_probe_installed")
                except Exception as exc:
                    _emit("signal_probe_install_failed", error=repr(exc))

            _emit("run_webhook_enter")
            return original(self, *args, **kwargs)
        except BaseException as exc:
            _emit("run_webhook_exception", error=f"{type(exc).__name__}:{exc}")
            raise
        finally:
            if patched and loop is not None and original_add is not None:
                try:
                    setattr(loop, "add_signal_handler", original_add)
                except Exception:
                    pass
            _emit("run_webhook_exit", stop_seen=_STOP_SEEN)

    setattr(traced_run_webhook, "_neyrobot_lifecycle_wrapped", True)
    Application.run_webhook = traced_run_webhook


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    _INSTALLED = True

    _emit("installed", thread=threading.current_thread().name)
    _wrap_application_stop()
    _wrap_run_webhook_signal_registration()

    t = threading.Thread(target=_heartbeat, name="render-lifecycle-heartbeat", daemon=True)
    t.start()

    @atexit.register
    def _on_exit() -> None:
        _emit("atexit", stop_seen=_STOP_SEEN)

    return True


__all__ = ["VERSION", "install"]
