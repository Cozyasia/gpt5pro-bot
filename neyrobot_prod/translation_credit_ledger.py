"""Transactional reservations for paid video translation attempts.

Callers may settle failure only after a definitive failure. An ambiguous
provider or delivery result keeps the reservation until reconciliation.
"""
from __future__ import annotations
import json
import math
import sqlite3
import time
import uuid

_SCHEMA = '''CREATE TABLE IF NOT EXISTS translation_attempts (
 request_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
 tx_id TEXT NOT NULL UNIQUE, provider_cost REAL NOT NULL,
 retail_cost REAL NOT NULL, credits REAL NOT NULL,
 state TEXT NOT NULL, provider_task_id TEXT NOT NULL DEFAULT '', updated_ts INTEGER NOT NULL)'''


def _connect(path):
    con = sqlite3.connect(path, timeout=30)
    con.execute('PRAGMA busy_timeout=30000')
    return con


def _begin(con):
    con.execute('BEGIN IMMEDIATE')
    con.execute(_SCHEMA)
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS translation_provider_task_unique ON translation_attempts(provider_task_id) WHERE provider_task_id != ''")


def _get(con, request_id, user_id):
    row = con.execute('SELECT user_id,tx_id,state,provider_task_id FROM translation_attempts WHERE request_id=?', (request_id,)).fetchone()
    if not row or row[0] != int(user_id):
        raise ValueError('attempt not found for user')
    return row


def reserve(path, request_id, user_id, *, provider_cost, retail_cost, credits):
    if not isinstance(request_id,str) or not request_id or len(request_id)>200 or int(user_id)<=0:
        raise ValueError('invalid request identity')
    vals = tuple(float(x) for x in (provider_cost, retail_cost, credits))
    if any(not math.isfinite(x) or x <= 0 for x in vals) or vals[1] < vals[0]:
        raise ValueError('invalid quote')
    con = _connect(path)
    try:
        _begin(con)
        old = con.execute('SELECT user_id,tx_id,provider_cost,retail_cost,credits FROM translation_attempts WHERE request_id=?', (request_id,)).fetchone()
        if old:
            if old[0] != int(user_id) or tuple(old[2:]) != vals:
                raise ValueError('request identity or quote mismatch')
            con.commit(); return old[1]
        wallet = con.execute('SELECT COALESCE(usd,0) FROM wallet WHERE user_id=?', (int(user_id),)).fetchone()
        balance = float(wallet[0]) if wallet else 0.0
        holds = float(con.execute("SELECT COALESCE(SUM(retail_usd),0) FROM credit_ledger WHERE user_id=? AND status='reserved'", (int(user_id),)).fetchone()[0])
        if not math.isfinite(balance) or not math.isfinite(holds) or balance - holds + 1e-9 < vals[1]:
            raise ValueError('insufficient balance')
        tx_id = uuid.uuid4().hex; now = int(time.time())
        con.execute('INSERT INTO credit_ledger(tx_id,user_id,feature,engine,provider_cost_usd,retail_usd,credits,status,metadata_json,created_ts,updated_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (tx_id,int(user_id),'video_translation_lipsync','kling',*vals,'reserved',json.dumps({'request_id':request_id}),now,now))
        con.execute('INSERT INTO translation_attempts(request_id,user_id,tx_id,provider_cost,retail_cost,credits,state,updated_ts) VALUES(?,?,?,?,?,?,?,?)',
                    (request_id,int(user_id),tx_id,*vals,'reserved',now))
        con.commit(); return tx_id
    except BaseException:
        con.rollback(); raise
    finally:
        con.close()


def begin_provider(path, request_id, user_id):
    con=_connect(path)
    try:
        _begin(con); row=_get(con,request_id,user_id)
        if row[2] != 'reserved':
            con.commit(); return False
        con.execute("UPDATE translation_attempts SET state='provider_started',updated_ts=? WHERE request_id=?", (int(time.time()),request_id))
        con.commit(); return True
    except BaseException:
        con.rollback(); raise
    finally:
        con.close()


def record_provider_task(path, request_id, user_id, task_id):
    if not isinstance(task_id,str) or not task_id or len(task_id)>200:
        raise ValueError('invalid task id')
    con=_connect(path)
    try:
        _begin(con); row=_get(con,request_id,user_id)
        if row[2] not in ('provider_started','unknown','submitted') or (row[3] and row[3] != task_id):
            raise ValueError('invalid provider task transition')
        prior = con.execute('SELECT request_id FROM translation_attempts WHERE provider_task_id=?', (task_id,)).fetchone()
        if prior and prior[0] != request_id:
            raise ValueError('provider task already linked')
        con.execute("UPDATE translation_attempts SET state='submitted',provider_task_id=?,updated_ts=? WHERE request_id=?", (task_id,int(time.time()),request_id))
        con.commit()
    except BaseException:
        con.rollback(); raise
    finally:
        con.close()


def settle(path, request_id, user_id, outcome):
    if outcome not in ('delivered','failed','unknown'):
        raise ValueError('invalid outcome')
    con=_connect(path)
    try:
        _begin(con); row=_get(con,request_id,user_id); state=row[2]
        if state in ('delivered','failed'):
            if state != outcome: raise ValueError('conflicting terminal outcome')
            con.commit(); return False
        if outcome == 'unknown':
            if state == 'reserved': raise ValueError('provider has not started')
            con.execute("UPDATE translation_attempts SET state='unknown',updated_ts=? WHERE request_id=?",(int(time.time()),request_id))
            con.commit(); return False
        if outcome == 'delivered' and (state not in ('submitted', 'unknown') or not row[3]):
            raise ValueError('provider result not established')
        entry=con.execute('SELECT user_id,retail_usd,status FROM credit_ledger WHERE tx_id=?',(row[1],)).fetchone()
        if not entry or entry[0] != int(user_id) or entry[2] != 'reserved':
            raise ValueError('reservation unavailable')
        if outcome == 'delivered':
            cur=con.execute('UPDATE wallet SET usd=COALESCE(usd,0)-? WHERE user_id=? AND COALESCE(usd,0)+1e-9>=?',(float(entry[1]),int(user_id),float(entry[1])))
            if cur.rowcount != 1: raise ValueError('insufficient balance')
        now=int(time.time())
        con.execute('UPDATE credit_ledger SET status=?,updated_ts=? WHERE tx_id=?',('charged' if outcome=='delivered' else 'released',now,row[1]))
        con.execute('UPDATE translation_attempts SET state=?,updated_ts=? WHERE request_id=?',(outcome,now,request_id))
        con.commit(); return True
    except BaseException:
        con.rollback(); raise
    finally:
        con.close()

class ConfirmedFailure(Exception):
    """A terminal failure known not to have produced a deliverable result."""


async def execute(path, request_id, user_id, *, provider_cost, retail_cost, credits, render, deliver):
    """Run one paid attempt without replaying ambiguous work or deliveries.

    render receives a synchronous callback to record the provider's task ID.
    A retry of the same request never re-runs the provider. Unknown outcomes
    retain the reservation for explicit reconciliation.
    """
    reserve(path, request_id, user_id, provider_cost=provider_cost, retail_cost=retail_cost, credits=credits)
    if not begin_provider(path, request_id, user_id):
        return 'already_started'
    def on_task(task_id):
        record_provider_task(path, request_id, user_id, task_id)
    try:
        video = await render(on_task)
        if not isinstance(video, (bytes, bytearray)) or not video:
            raise RuntimeError('provider produced an invalid result')
        con = _connect(path)
        try:
            row = _get(con, request_id, user_id)
            if row[2] != 'submitted' or not row[3]:
                raise RuntimeError('provider task not recorded')
        finally:
            con.close()
    except ConfirmedFailure:
        settle(path, request_id, user_id, 'failed')
        return 'failed'
    except Exception:
        settle(path, request_id, user_id, 'unknown')
        return 'unknown'
    try:
        sent = await deliver(video)
        if sent is not True:
            raise RuntimeError('delivery was not confirmed')
    except Exception:
        settle(path, request_id, user_id, 'unknown')
        return 'unknown'
    try:
        settle(path, request_id, user_id, 'delivered')
    except Exception:
        # Delivery may already have happened. Keep the hold and never resend.
        settle(path, request_id, user_id, 'unknown')
        return 'unknown'
    return 'delivered'
