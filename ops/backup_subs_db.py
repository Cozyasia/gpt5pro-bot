#!/usr/bin/env python3
"""Create a consistent SQLite backup on the Render persistent disk.

Usage inside the existing production container:
  python /app/ops/backup_subs_db.py
Does not log user data or secrets. Does not overwrite existing backups.
Copy the resulting file OFF the Render disk for disaster recovery.
"""
import datetime
import os
from pathlib import Path
import sys

try:
    from ops.reconcile_neyronix_db import backup_sqlite
except ModuleNotFoundError:  # Direct execution as /app/ops/backup_subs_db.py.
    from reconcile_neyronix_db import backup_sqlite

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
result = backup_sqlite(source, target)
print("BACKUP_OK path=" + str(target))
print("size_bytes=" + str(result["size_bytes"]))
print("sha256=" + str(result["sha256"]))
print("integrity_check=" + str(result["integrity_check"]))
print("WARNING: Backup remains on the SAME Render disk. Export it to independent storage.")
