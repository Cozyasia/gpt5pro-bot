# -*- coding: utf-8 -*-
"""Fail-closed runtime safety guard for the V265 strict second pass.

V265 remains the single production owner and its quality thresholds/gate are unchanged.
Before a strict attempt this guard reclaims Python/glibc arenas and verifies real Linux
cgroup memory headroom. If the process is too close to its container limit, that single
operation fails closed before heavy strict work instead of risking a process restart.
"""
from __future__ import annotations

import ctypes
import gc
import os
from pathlib import Path
from typing import Any, Callable

from neyrobot_prod import dense68_engine_v265 as engine

_INSTALLED = False
_BASE_TRANSFER: Callable[..., Any] | None = None
# The strict regression reached ~25 MiB above strict-entry RSS; reserve substantially
# more than that measured native transient while still allowing a 512 MiB worker to run.
_STRICT_HEADROOM_RESERVE = 64 * 1024 * 1024


def _read_int(path: str) -> int | None:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
        if not value or value == "max":
            return None
        return int(value)
    except Exception:
        return None


def _memory_state() -> tuple[int | None, int | None, int | None]:
    current = _read_int("/sys/fs/cgroup/memory.current")
    limit = _read_int("/sys/fs/cgroup/memory.max")
    rss = None
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1]) * 1024
                break
    except Exception:
        pass
    return current, limit, rss


def _reclaim_before_strict() -> tuple[int | None, int | None, int | None]:
    gc.collect()
    # CPython/OpenCV native temporaries can leave free pages in glibc arenas after the
    # standard pass. malloc_trim releases those pages back to the container cgroup.
    try:
        libc = ctypes.CDLL(None)
        trim = getattr(libc, "malloc_trim", None)
        if callable(trim):
            trim(0)
    except Exception:
        pass
    return _memory_state()


def _strict_preflight() -> None:
    current, limit, rss = _reclaim_before_strict()
    headroom = None if current is None or limit is None else max(0, limit - current)
    print(
        "AI_SELFIE_V265_STRICT_MEMORY "
        f"current={current if current is not None else 'unknown'} "
        f"limit={limit if limit is not None else 'unknown'} "
        f"headroom={headroom if headroom is not None else 'unknown'} "
        f"rss={rss if rss is not None else 'unknown'} reserve={_STRICT_HEADROOM_RESERVE} "
        "gc=true malloc_trim=true",
        flush=True,
    )
    if headroom is not None and headroom < _STRICT_HEADROOM_RESERVE:
        raise RuntimeError(
            "V265 strict retry blocked before heavy work: insufficient container memory headroom"
        )


def install() -> None:
    global _INSTALLED, _BASE_TRANSFER
    if _INSTALLED:
        return

    _BASE_TRANSFER = engine.transfer_attempt

    def _guarded_transfer_attempt(*args: Any, strict: bool, **kwargs: Any):
        if bool(strict):
            _strict_preflight()
        return _BASE_TRANSFER(*args, strict=bool(strict), **kwargs)

    engine.transfer_attempt = _guarded_transfer_attempt
    _INSTALLED = True
    print(
        "AI_SELFIE_V265_STRICT_SAFETY status=armed strict_enabled=true "
        "memory_headroom_guard=true standard_gate_unchanged=true legacy_fallback=false",
        flush=True,
    )


__all__ = ["install"]
