"""Atomic, idempotent settlement primitives for linked Kling recovery jobs.

This module has no startup side effects. Callers must verify delivery or a
terminal provider failure before settling. Unknown outcomes are never settled.
"""
from __future__ import annotations
import sqlite3
import time

_SCHEMA = '''CREATE TABLE IF NOT EXISTS kling_job_finance (
 job_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
 reference TEXT NOT NULL UNIQUE, outcome TEXT NOT NULL DEFAULT 'pending')'''

def _connect(path):
    con=sqlite3.connect(path,timeout=30)
    con.execute('PRAGMA busy_timeout=30000')
    return con

def link(db_path: str, job_id: str, user_id: int, kind: str, reference: str) -> None:
    if kind not in ('credit','promo') or not job_id or not reference:
        raise ValueError('invalid finance link')
    con=_connect(db_path)
    try:
        con.execute('BEGIN IMMEDIATE');con.execute(_SCHEMA)
        row=con.execute("SELECT user_id,provider FROM durable_jobs WHERE job_id=?",(job_id,)).fetchone()
        if not row or row != (user_id,'kling'):
            raise ValueError('job ownership mismatch')
        if kind=='credit':
            item=con.execute('SELECT user_id,status FROM credit_ledger WHERE tx_id=?',(reference,)).fetchone()
            if not item or item!=(user_id,'reserved'): raise ValueError('credit ownership or status mismatch')
        else:
            item=con.execute('SELECT quota_key,status FROM promo_attempts WHERE token=?',(reference,)).fetchone()
            if not item or not item[0].startswith(f'promo5:{user_id}:') or item[1]!='reserved':
                raise ValueError('promo ownership or status mismatch')
        old=con.execute('SELECT user_id,kind,reference FROM kling_job_finance WHERE job_id=?',(job_id,)).fetchone()
        if old and old!=(user_id,kind,reference):raise ValueError('job already linked')
        if not old:con.execute('INSERT INTO kling_job_finance(job_id,user_id,kind,reference) VALUES(?,?,?,?)',(job_id,user_id,kind,reference))
        con.commit()
    except BaseException:
        con.rollback();raise
    finally:con.close()

def finalize(db_path: str, job_id: str, outcome: str) -> bool:
    if outcome not in ('delivered','failed','unknown'):raise ValueError('invalid outcome')
    con=_connect(db_path)
    try:
        con.execute('BEGIN IMMEDIATE');con.execute(_SCHEMA)
        row=con.execute('SELECT user_id,kind,reference,outcome FROM kling_job_finance WHERE job_id=?',(job_id,)).fetchone()
        if not row:raise ValueError('job is not linked')
        user_id,kind,ref,previous=row
        if outcome=='unknown' or previous==outcome:
            con.commit();return False
        if previous!='pending':raise ValueError('conflicting terminal outcome')
        if kind=='credit':
            item=con.execute('SELECT user_id,retail_usd,status FROM credit_ledger WHERE tx_id=?',(ref,)).fetchone()
            if not item or item[0]!=user_id or item[2]!='reserved':raise ValueError('credit not reserved')
            if outcome=='delivered':
                amount=float(item[1])
                if amount<=0:raise ValueError('invalid credit amount')
                cur=con.execute('UPDATE wallet SET usd=COALESCE(usd,0)-? WHERE user_id=? AND COALESCE(usd,0)+1e-9>=?',(amount,user_id,amount))
                if cur.rowcount!=1:raise ValueError('insufficient wallet balance')
            con.execute('UPDATE credit_ledger SET status=?,updated_ts=? WHERE tx_id=?',('charged' if outcome=='delivered' else 'released',int(time.time()),ref))
        else:
            item=con.execute('SELECT quota_key,status FROM promo_attempts WHERE token=?',(ref,)).fetchone()
            if not item or not item[0].startswith(f'promo5:{user_id}:') or item[1]!='reserved':raise ValueError('promo not reserved')
            if outcome=='failed':
                count=con.execute('SELECT value FROM kv WHERE key=?',(item[0],)).fetchone()
                if not count or int(count[0])<1:raise ValueError('invalid promo counter')
                con.execute('UPDATE kv SET value=? WHERE key=?',(str(int(count[0])-1),item[0]))
            con.execute('UPDATE promo_attempts SET status=? WHERE token=?',('used' if outcome=='delivered' else 'released',ref))
        con.execute('UPDATE kling_job_finance SET outcome=? WHERE job_id=?',(outcome,job_id))
        con.commit();return True
    except BaseException:
        con.rollback();raise
    finally:con.close()
