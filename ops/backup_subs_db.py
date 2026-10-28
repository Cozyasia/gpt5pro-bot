#!/usr/bin/env python3
"""Create a consistent SQLite backup on the Render persistent disk.

Usage inside the existing production container:
  python /app/ops/backup_subs_db.py
Does not log user data or secrets. Does not overwrite existing backups.
Copy the resulting file OFF the Render disk for disaster recovery.
"""
import datetime
import hashlib
import os
from pathlib import Path
import sqlite3
import sys

source = Path(os.environ.get("DB_PATH", "/data/subs.db")).resolve()
if not source.is_file():
    sys.exit("ERROR: DB_PATH is not an existing file")
if source.stat().st_size == 0:
    sys.exit("ERROR: database is empty")
outdir = Path("/data/neyronix-backups")
outdir.mkdir(mode=0o700, parents=True, exist_ok=True)
os.chmod(outdir, 0o700)
timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
target = outdir / ("subs-" + timestamp + ".sqlite3")
if target.exists():
    sys.exit("ERROR: backup filename collision")
with sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30) as src:
    with sqlite3.connect(str(target), timeout=30) as dst:
        src.backup(dst, pages=128, sleep=0.2)
with sqlite3.connect(f"file:{target}?mode=ro", uri=True) as check:
    result = check.execute("PRAGMA integrity_check").fetchone()[0]
if result != "ok":
    target.unlink(missing_ok=True)
    sys.exit("ERROR: backup integrity check failed")
os.chmod(target, 0o600)
h = hashlib.sha256()
with target.open("rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(chunk)
print("BACKUP_OK path=" + str(target))
print("size_bytes=" + str(target.stat().st_size))
print("sha256=" + h.hexdigest())
print("integrity_check=ok")
print("WARNING: Backup remains on the SAME Render disk. Export it to independent storage.")
