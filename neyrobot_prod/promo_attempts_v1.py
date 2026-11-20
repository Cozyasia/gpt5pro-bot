"""Atomic reservations for existing daily promo counters."""
from __future__ import annotations

import sqlite3
import uuid


def reserve(db_path: str, key: str, limit: int) -> tuple[str | None, int]:
    if not db_path or not key or limit <= 0:
        raise ValueError('invalid promo reservation')
    con = sqlite3.connect(db_path, timeout=30)
    try:
        con.execute('BEGIN IMMEDIATE')
        con.execute('CREATE TABLE IF NOT EXISTS promo_attempts (token TEXT PRIMARY KEY, quota_key TEXT NOT NULL, status TEXT NOT NULL)')
        row = con.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        used = int(row[0]) if row else 0
        if used < 0:
            raise ValueError('invalid promo counter')
        if used >= limit:
            con.commit()
            return None, 0
        token = uuid.uuid4().hex
        con.execute('INSERT INTO promo_attempts(token,quota_key,status) VALUES(?,?,?)', (token,key,'reserved'))
        con.execute('INSERT INTO kv(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key,str(used+1)))
        con.commit()
        return token, limit-used-1
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def finish(db_path: str, token: str, *, success: bool) -> bool:
    if not db_path or not token:
        raise ValueError('invalid promo attempt')
    con = sqlite3.connect(db_path, timeout=30)
    try:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT quota_key,status FROM promo_attempts WHERE token=?', (token,)).fetchone()
        if not row or row[1] != 'reserved':
            con.commit()
            return False
        if not success:
            counter = con.execute('SELECT value FROM kv WHERE key=?', (row[0],)).fetchone()
            if not counter or int(counter[0]) < 1:
                raise ValueError('promo counter missing or invalid')
            con.execute('UPDATE kv SET value=? WHERE key=?', (str(int(counter[0])-1),row[0]))
        con.execute('UPDATE promo_attempts SET status=? WHERE token=?', ('used' if success else 'released',token))
        con.commit()
        return True
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()
