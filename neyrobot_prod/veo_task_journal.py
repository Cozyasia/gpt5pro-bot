"""Durable local task journal for billed video scene submissions.

One journal per job. Atomic replace and fsync reduce lost task identifiers.
A submission without a known provider ID is marked uncertain, never retried
automatically. Caller must use a per-job lock across workers.
"""
import json
import os
import tempfile
from pathlib import Path


def read_job(path):
    p = Path(path)
    if not p.exists():
        return {"scenes": {}}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), dict):
        raise ValueError("Invalid job journal")
    return data


def write_job(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".veo-", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def mark_scene(path, index, state, task_id=None):
    if state not in ("submitting", "accepted", "completed", "uncertain", "failed"):
        raise ValueError("Unknown scene state")
    if index < 1:
        raise ValueError("Invalid scene index")
    if state in ("accepted", "completed") and not task_id:
        raise ValueError("Accepted scene requires provider task ID")
    data = read_job(path)
    key = str(index)
    previous = data["scenes"].get(key, {})
    old_id = previous.get("task_id")
    if old_id and task_id and old_id != task_id:
        raise ValueError("Provider task ID cannot be replaced")
    data["scenes"][key] = {"state": state, "task_id": task_id or old_id}
    write_job(path, data)
    return data["scenes"][key]


def may_submit(path, index):
    return str(index) not in read_job(path)["scenes"]
