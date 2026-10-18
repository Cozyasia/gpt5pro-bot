"""Read-only, value-free inventory for migrating Render env vars to Secret Files.

Usage: python scripts/audit_secret_migration.py
Prints counts only. Does not alter os.environ or any file.
"""
from __future__ import annotations

import os
from pathlib import Path


def audit(file_path: str = "/etc/secrets/neyro_bot.env", environ=None) -> dict[str, int | bool]:
    env = os.environ if environ is None else environ
    path = Path(file_path)
    if not path.is_file():
        return {"file_found": False, "file_entries": 0, "env_overrides": 0, "file_only": 0, "empty_entries": 0, "duplicate_names": 0}
    seen = set()
    duplicate = 0
    empty = 0
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.isidentifier() or not key.isascii():
            continue
        if key in seen:
            duplicate += 1
        seen.add(key)
        if not value.strip().strip("\\\"'"):
            empty += 1
    overrides = sum(bool((env.get(key) or "").strip()) for key in seen)
    return {"file_found": True, "file_entries": len(seen), "env_overrides": overrides, "file_only": len(seen) - overrides, "empty_entries": empty, "duplicate_names": duplicate}


if __name__ == "__main__":
    result = audit()
    for key, value in result.items():
        print(f"{key}: {value}")
