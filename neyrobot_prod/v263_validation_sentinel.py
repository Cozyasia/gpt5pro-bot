# -*- coding: utf-8 -*-
"""Crash-safe persisted state machine for controlled V263 validation.

A validation run must persist `started` before any heavy inference/allocation. If the
process is killed, the next process observes `started` and refuses to auto-run the
same heavy validation again. States: armed -> started -> completed/failed.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

_ALLOWED = {"armed", "started", "completed", "failed"}
_TERMINAL_OR_INFLIGHT = {"started", "completed", "failed"}


def read_state(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("state") in _ALLOWED:
            return payload
    except Exception:
        pass
    return None


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        Path(tmp_name).replace(path)
    finally:
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except Exception:
            pass


def arm(path: Path, *, run_id: str) -> bool:
    current = read_state(path)
    if current and current.get("state") in _TERMINAL_OR_INFLIGHT:
        return False
    _atomic_write(path, {"state": "armed", "run_id": str(run_id)})
    return True


def mark_started(path: Path, *, run_id: str) -> bool:
    current = read_state(path)
    if current and current.get("state") in _TERMINAL_OR_INFLIGHT:
        return False
    _atomic_write(path, {"state": "started", "run_id": str(run_id)})
    return True


def mark_completed(path: Path, *, run_id: str) -> None:
    _atomic_write(path, {"state": "completed", "run_id": str(run_id)})


def mark_failed(path: Path, *, run_id: str, error_type: str) -> None:
    # Error class only; never persist exception messages that could contain data.
    _atomic_write(path, {"state": "failed", "run_id": str(run_id), "error_type": str(error_type)[:96]})


__all__ = ["read_state", "arm", "mark_started", "mark_completed", "mark_failed"]
