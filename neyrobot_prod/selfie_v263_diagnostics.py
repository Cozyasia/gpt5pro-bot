# -*- coding: utf-8 -*-
"""Safe process/memory checkpoints for V263 crash investigation.

This module never logs image content, model credentials, request identifiers, or user
metadata. It reports only checkpoint ids, dimensions, array metadata, elapsed time,
and process memory counters needed to localize native process termination.
"""
from __future__ import annotations

import os
import resource
import time
from pathlib import Path
from typing import Any, Callable, Iterable


def memory_snapshot() -> tuple[int, int]:
    """Return (current_rss_bytes, peak_rss_bytes) without external dependencies."""
    rss = 0
    peak = 0
    status = Path("/proc/self/status")
    try:
        for line in status.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1]) * 1024
            elif line.startswith("VmHWM:"):
                peak = int(line.split()[1]) * 1024
    except Exception:
        pass
    try:
        ru_peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # Linux reports KiB. macOS reports bytes; production/CI are Linux, but keep
        # the fallback conservative for local diagnostics.
        if os.name == "posix" and Path("/proc").exists():
            ru_peak *= 1024
        peak = max(peak, ru_peak)
    except Exception:
        pass
    return max(0, rss), max(0, peak)


def _array_meta(name: str, value: Any) -> tuple[str, int]:
    shape = getattr(value, "shape", None)
    dtype = getattr(value, "dtype", None)
    nbytes = int(getattr(value, "nbytes", 0) or 0)
    if shape is None:
        shape_text = "none"
    else:
        try:
            shape_text = "x".join(str(int(v)) for v in tuple(shape))
        except Exception:
            shape_text = "unknown"
    dtype_text = str(dtype) if dtype is not None else type(value).__name__
    return f"{name}[shape={shape_text},dtype={dtype_text},bytes={nbytes}]", nbytes


def checkpoint(
    log: Callable[..., None],
    checkpoint_id: str,
    *,
    started: float | None = None,
    dims: str = "none",
    arrays: Iterable[tuple[str, Any]] = (),
    note: str = "none",
) -> float:
    """Emit one content-free checkpoint and return a fresh perf-counter timestamp."""
    now = time.perf_counter()
    elapsed_ms = -1.0 if started is None else max(0.0, (now - float(started)) * 1000.0)
    parts: list[str] = []
    buffer_bytes = 0
    for name, value in arrays:
        meta, nbytes = _array_meta(str(name), value)
        parts.append(meta)
        buffer_bytes += nbytes
    rss, peak = memory_snapshot()
    log(
        "AI_SELFIE_V263_CHECKPOINT id=%s dims=%s arrays=%s approx_buffer_bytes=%s "
        "rss_bytes=%s peak_rss_bytes=%s elapsed_ms=%.3f pid=%s note=%s",
        str(checkpoint_id), str(dims), ";".join(parts) if parts else "none",
        int(buffer_bytes), int(rss), int(peak), float(elapsed_ms), os.getpid(), str(note),
    )
    return time.perf_counter()


__all__ = ["checkpoint", "memory_snapshot"]
