"""Atomic durable state for the paid stages of a 24-second Veo job."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def load_state(path: str | Path) -> dict:
    target = Path(path)
    if not target.exists():
        return {"version": 1, "lipsync": {}}
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("lipsync", {}), dict):
        raise ValueError("Invalid 24-second Veo workflow state")
    data.setdefault("version", 1)
    data.setdefault("lipsync", {})
    return data


def save_state(path: str | Path, state: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".veo24-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def record_job_metadata(path: str | Path, **metadata) -> dict:
    state = load_state(path)
    state.setdefault("job", {}).update({key: value for key, value in metadata.items() if value is not None})
    save_state(path, state)
    return state


def begin_lipsync_submission(path: str | Path, index: int) -> dict:
    state = load_state(path)
    key = str(index)
    prior = state["lipsync"].get(key, {})
    if prior.get("state") in {"submitting", "uncertain"}:
        raise RuntimeError("Kling submission requires reconciliation; automatic resubmission is blocked")
    if prior.get("state") in {"accepted", "completed"}:
        raise RuntimeError("Kling task already exists; resume the existing task instead")
    state["lipsync"][key] = {"state": "submitting"}
    save_state(path, state)
    return state


def mark_lipsync_accepted(path: str | Path, index: int, task_id: str) -> dict:
    if not task_id:
        raise ValueError("Kling task ID is required")
    state = load_state(path)
    state["lipsync"][str(index)] = {"state": "accepted", "task_id": str(task_id)}
    save_state(path, state)
    return state


def mark_lipsync_completed(path: str | Path, index: int, artifact: str) -> dict:
    state = load_state(path)
    item = state["lipsync"].setdefault(str(index), {})
    item.update({"state": "completed", "artifact": artifact})
    save_state(path, state)
    return state


def mark_lipsync_uncertain(path: str | Path, index: int) -> dict:
    state = load_state(path)
    item = state["lipsync"].setdefault(str(index), {})
    item["state"] = "uncertain"
    save_state(path, state)
    return state
