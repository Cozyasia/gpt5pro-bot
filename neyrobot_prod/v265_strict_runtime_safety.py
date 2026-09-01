# -*- coding: utf-8 -*-
"""Fail-closed runtime safety guard for the V265 strict second pass.

V265 remains the single production owner and its quality thresholds/gate are unchanged.
Before a strict attempt this guard reclaims Python/glibc arenas and verifies Linux cgroup
memory headroom. Reclaimable inactive file cache is discounted conservatively so model
and image page-cache does not masquerade as anonymous process pressure. If effective
headroom is still unsafe, only that operation fails closed before heavy strict work.
"""
from __future__ import annotations

import ctypes
import gc
from pathlib import Path
from typing import Any, Callable

from neyrobot_prod import dense68_engine_v265 as engine

_INSTALLED = False
_BASE_TRANSFER: Callable[..., Any] | None = None
# The strict regression reached ~25 MiB above strict-entry RSS; reserve substantially
# more than that measured native transient while keeping the hard quality gate intact.
_STRICT_HEADROOM_RESERVE = 64 * 1024 * 1024


def _read_int(path: str) -> int | None:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
        if not value or value == "max":
            return None
        return int(value)
    except Exception:
        return None


def _read_inactive_file() -> int | None:
    """Read reclaimable inactive file cache from cgroup-v2 memory.stat."""
    try:
        for line in Path("/sys/fs/cgroup/memory.stat").read_text(encoding="utf-8").splitlines():
            key, value = line.split(None, 1)
            if key == "inactive_file":
                return max(0, int(value))
    except Exception:
        pass
    return None


def _memory_state() -> tuple[int | None, int | None, int | None, int | None]:
    current = _read_int("/sys/fs/cgroup/memory.current")
    limit = _read_int("/sys/fs/cgroup/memory.max")
    inactive_file = _read_inactive_file()
    rss = None
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1]) * 1024
                break
    except Exception:
        pass
    return current, limit, rss, inactive_file


def _reclaim_before_strict() -> tuple[int | None, int | None, int | None, int | None]:
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


def _effective_memory(
    current: int | None,
    limit: int | None,
    rss: int | None,
    inactive_file: int | None,
) -> tuple[int | None, int | None, int]:
    """Return effective current/headroom after conservative file-cache accounting.

    cgroup memory.current includes filesystem page cache created while downloading and
    reading the ONNX models. Linux may reclaim inactive_file under pressure. We only
    credit cache that is both reported inactive and above the process RSS floor; this
    prevents the safety check from treating anonymous/resident process memory as free.
    """
    reclaimable = 0
    if current is not None and rss is not None and inactive_file is not None:
        reclaimable = min(max(0, inactive_file), max(0, current - rss))
    effective_current = None if current is None else max(0, current - reclaimable)
    effective_headroom = (
        None
        if effective_current is None or limit is None
        else max(0, limit - effective_current)
    )
    return effective_current, effective_headroom, reclaimable


def _strict_preflight() -> None:
    current, limit, rss, inactive_file = _reclaim_before_strict()
    raw_headroom = None if current is None or limit is None else max(0, limit - current)
    effective_current, effective_headroom, reclaimable = _effective_memory(
        current, limit, rss, inactive_file
    )
    print(
        "AI_SELFIE_V265_STRICT_MEMORY "
        f"current={current if current is not None else 'unknown'} "
        f"limit={limit if limit is not None else 'unknown'} "
        f"inactive_file={inactive_file if inactive_file is not None else 'unknown'} "
        f"reclaimable_file={reclaimable} "
        f"effective_current={effective_current if effective_current is not None else 'unknown'} "
        f"raw_headroom={raw_headroom if raw_headroom is not None else 'unknown'} "
        f"effective_headroom={effective_headroom if effective_headroom is not None else 'unknown'} "
        f"rss={rss if rss is not None else 'unknown'} reserve={_STRICT_HEADROOM_RESERVE} "
        "gc=true malloc_trim=true",
        flush=True,
    )
    if effective_headroom is not None and effective_headroom < _STRICT_HEADROOM_RESERVE:
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
        "memory_headroom_guard=true reclaimable_file_cache=true "
        "standard_gate_unchanged=true legacy_fallback=false",
        flush=True,
    )


__all__ = ["install"]
