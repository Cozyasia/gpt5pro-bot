"""Durable per-chat guard against Telegram /start interrupting Veo jobs."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


DEFAULT_STALE_SECONDS = 6 * 60 * 60


def _marker_path(user_id: int, chat_id: int) -> Path:
    root = Path(os.environ.get("VEO_JOBS_DIR", "/data/veo_jobs"))
    root.mkdir(parents=True, exist_ok=True)
    return root / f".active_veo_{int(user_id)}_{int(chat_id)}.json"


def _stale_seconds() -> float:
    try:
        return max(300.0, float(os.environ.get("VEO_ACTIVE_JOB_STALE_S", DEFAULT_STALE_SECONDS)))
    except (TypeError, ValueError):
        return float(DEFAULT_STALE_SECONDS)


def is_veo_job_active(user_id: int, chat_id: int) -> bool:
    marker = _marker_path(user_id, chat_id)
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        started_at = float(payload.get("started_at", marker.stat().st_mtime))
        if time.time() - started_at > _stale_seconds():
            marker.unlink(missing_ok=True)
            return False
        return True
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def begin_veo_job(user_id: int, chat_id: int, token: str) -> bool:
    """Claim the user's Veo slot; a second concurrent job is rejected."""
    marker = _marker_path(user_id, chat_id)
    if is_veo_job_active(user_id, chat_id):
        return False
    payload = {"user_id": int(user_id), "chat_id": int(chat_id), "token": str(token), "started_at": time.time()}
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        marker.unlink(missing_ok=True)
        raise
    return True


def end_veo_job(user_id: int, chat_id: int, token: str) -> None:
    marker = _marker_path(user_id, chat_id)
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        if str(payload.get("token", "")) == str(token):
            marker.unlink(missing_ok=True)
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return
