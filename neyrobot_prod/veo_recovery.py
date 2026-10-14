"""Small, non-network helpers for user-confirmed Veo Extend recovery."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path


JOB_ID_RE = re.compile(r"^[0-9a-f]{24}$")
RECOVERY_CALLBACK_PREFIX = "veoresume:"


def callback_data(job_id: str) -> str:
    value = str(job_id or "").strip().lower()
    if not JOB_ID_RE.fullmatch(value):
        raise ValueError("invalid Veo job id")
    return RECOVERY_CALLBACK_PREFIX + value


def parse_callback_data(data: str) -> str | None:
    value = str(data or "")
    if not value.startswith(RECOVERY_CALLBACK_PREFIX):
        return None
    job_id = value[len(RECOVERY_CALLBACK_PREFIX):]
    return job_id if JOB_ID_RE.fullmatch(job_id) else None


def metadata_path(directory: str | Path) -> Path:
    return Path(directory) / "job_metadata.json"


def write_metadata(directory: str | Path, **values) -> dict:
    target = metadata_path(directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    current = read_metadata(directory)
    current.update({key: value for key, value in values.items() if value is not None})
    fd, temporary = tempfile.mkstemp(prefix=".veo-meta-", dir=str(target.parent))
    try:
        with open(fd, "w", encoding="utf-8", closefd=True) as handle:
            json.dump(current, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(target)
    finally:
        temporary_path = Path(temporary)
        if temporary_path.exists():
            temporary_path.unlink()
    return current


def read_metadata(directory: str | Path) -> dict:
    target = metadata_path(directory)
    if not target.exists():
        return {}
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid Veo job metadata")
    return data


def retryable_extension(directory: str | Path) -> dict | None:
    """Return the first explicit-resume checkpoint, if one exists."""
    for state_file in sorted(Path(directory).glob("extension_*.json")):
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if state.get("status") == "resume_required" and state.get("retryable") is True:
            return state
    return None


def completed_extension_seconds(directory: str | Path) -> int:
    latest = 8
    for state_file in sorted(Path(directory).glob("extension_*.json")):
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if state.get("status") != "accepted":
            break
        step = int(state.get("step", 0))
        if step < 1:
            break
        latest = 8 + 7 * step
    return latest
