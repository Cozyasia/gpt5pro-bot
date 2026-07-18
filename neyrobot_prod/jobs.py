# -*- coding: utf-8 -*-
"""Durable provider-job registry and recovery for Neyro-Bot."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
import uuid
from types import SimpleNamespace
from typing import Any

import httpx

from .db import connect, init_schema, record_event

_ACTIVE_RECOVERY: set[str] = set()
_RECOVERY_LOCK = asyncio.Lock()


def _db_path(mod: Any) -> str:
    return str(getattr(mod, "DB_PATH", "") or "")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:30000]


def begin_job(
    mod: Any,
    *,
    user_id: int,
    chat_id: int,
    feature: str,
    provider: str,
    provider_task_id: str = "",
    payload: dict[str, Any] | None = None,
    job_id: str = "",
) -> str:
    db_path = _db_path(mod)
    init_schema(db_path)
    if not job_id:
        base = f"{provider}|{provider_task_id}|{user_id}|{chat_id}|{feature}"
        digest = hashlib.sha256(base.encode("utf-8", errors="ignore")).hexdigest()[:24]
        job_id = f"job_{digest}" if provider_task_id else f"job_{uuid.uuid4().hex}"
    now = int(time.time())
    con = connect(db_path)
    try:
        con.execute(
            """INSERT INTO durable_jobs(job_id,user_id,chat_id,feature,provider,provider_task_id,state,payload_json,created_ts,updated_ts,next_poll_ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(job_id) DO UPDATE SET
                 provider_task_id=excluded.provider_task_id,
                 state=CASE WHEN durable_jobs.state IN ('completed','failed','cancelled') THEN durable_jobs.state ELSE 'pending' END,
                 payload_json=excluded.payload_json,
                 updated_ts=excluded.updated_ts,
                 next_poll_ts=excluded.next_poll_ts""",
            (
                job_id,
                int(user_id or 0),
                int(chat_id or 0),
                str(feature or "provider_job")[:100],
                str(provider or "provider")[:40],
                str(provider_task_id or "")[:200],
                "pending",
                _json(payload or {}),
                now,
                now,
                now,
            ),
        )
        con.commit()
    finally:
        con.close()
    return job_id


def update_job(mod: Any, job_id: str, *, state: str | None = None, result_url: str | None = None, error: str | None = None, next_poll_ts: int | None = None) -> None:
    db_path = _db_path(mod)
    if not db_path or not job_id:
        return
    init_schema(db_path)
    fields = ["updated_ts=?", "attempts=attempts+1"]
    values: list[Any] = [int(time.time())]
    if state is not None:
        fields.append("state=?")
        values.append(str(state)[:30])
    if result_url is not None:
        fields.append("result_url=?")
        values.append(str(result_url)[:2000])
    if error is not None:
        fields.append("error_text=?")
        values.append(str(error)[:4000])
    if next_poll_ts is not None:
        fields.append("next_poll_ts=?")
        values.append(int(next_poll_ts))
    if state in {"completed", "failed", "cancelled"}:
        fields.append("completed_ts=?")
        values.append(int(time.time()))
    values.append(job_id)
    con = connect(db_path)
    try:
        con.execute(f"UPDATE durable_jobs SET {', '.join(fields)} WHERE job_id=?", values)
        con.commit()
    finally:
        con.close()


def pending_jobs(mod: Any, limit: int = 50) -> list[dict[str, Any]]:
    db_path = _db_path(mod)
    init_schema(db_path)
    con = connect(db_path)
    try:
        rows = con.execute(
            """SELECT job_id,user_id,chat_id,feature,provider,provider_task_id,state,payload_json,attempts,created_ts,updated_ts
               FROM durable_jobs
               WHERE state IN ('pending','polling','recovering')
               ORDER BY updated_ts ASC LIMIT ?""",
            (max(1, min(200, int(limit))),),
        ).fetchall()
    finally:
        con.close()
    result = []
    for row in rows:
        try:
            payload = json.loads(row[7] or "{}")
        except Exception:
            payload = {}
        result.append({
            "job_id": row[0], "user_id": row[1], "chat_id": row[2], "feature": row[3],
            "provider": row[4], "provider_task_id": row[5], "state": row[6], "payload": payload,
            "attempts": row[8], "created_ts": row[9], "updated_ts": row[10],
        })
    return result


class _MessageProxy:
    def __init__(self, bot: Any, chat_id: int):
        self.bot = bot
        self.chat_id = int(chat_id)

    async def reply_text(self, text: str, **kwargs: Any):
        return await self.bot.send_message(chat_id=self.chat_id, text=text, **kwargs)

    async def reply_audio(self, audio: Any, **kwargs: Any):
        return await self.bot.send_audio(chat_id=self.chat_id, audio=audio, **kwargs)

    async def reply_document(self, document: Any, **kwargs: Any):
        return await self.bot.send_document(chat_id=self.chat_id, document=document, **kwargs)

    async def reply_video(self, video: Any, **kwargs: Any):
        return await self.bot.send_video(chat_id=self.chat_id, video=video, **kwargs)


class _UpdateProxy:
    def __init__(self, bot: Any, chat_id: int, user_id: int):
        self.effective_message = _MessageProxy(bot, chat_id)
        self.effective_chat = SimpleNamespace(id=int(chat_id))
        self.effective_user = SimpleNamespace(id=int(user_id), username="")


def _provider_headers(mod: Any, provider: str) -> dict[str, str]:
    provider = (provider or "").lower()
    key = ""
    if provider == "suno":
        key = str(getattr(mod, "SUNO_API_KEY", "") or getattr(mod, "COMET_API_KEY", "") or "")
    elif provider == "sora":
        key = str(getattr(mod, "SORA_API_KEY", "") or getattr(mod, "COMET_API_KEY", "") or "")
    elif provider == "kling":
        key = str(getattr(mod, "KLING_API_KEY", "") or getattr(mod, "COMET_API_KEY", "") or "")
    else:
        key = str(getattr(mod, "COMET_API_KEY", "") or "")
    return {"Authorization": f"Bearer {key}", "Accept": "application/json", "Content-Type": "application/json"}


async def _recover_suno(mod: Any, app: Any, job: dict[str, Any]) -> bool:
    task_id = str(job.get("provider_task_id") or "")
    if not task_id or not callable(getattr(mod, "_poll_suno_task", None)):
        return False
    proxy = _UpdateProxy(app.bot, int(job["chat_id"]), int(job["user_id"]))
    headers = _provider_headers(mod, "suno")
    async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
        return bool(await mod._poll_suno_task(proxy, client, headers, task_id))


async def _recover_generic_video(mod: Any, app: Any, job: dict[str, Any]) -> bool:
    original = getattr(mod, "_PROD_ORIGINAL_POLL_VIDEO", None)
    if not callable(original):
        return False
    payload = job.get("payload") or {}
    task_id = str(job.get("provider_task_id") or "")
    base_url = str(payload.get("base_url") or getattr(mod, "COMET_BASE_URL", ""))
    status_paths = list(payload.get("status_paths") or [])
    caption = str(payload.get("caption") or "Видео готово ✅")
    max_wait_s = int(payload.get("max_wait_s") or 1200)
    provider = str(job.get("provider") or "comet")
    proxy = _UpdateProxy(app.bot, int(job["chat_id"]), int(job["user_id"]))
    headers = _provider_headers(mod, provider)
    async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
        return bool(await original(proxy, client, headers, base_url, status_paths, task_id, caption, max_wait_s))


async def recover_pending(mod: Any, app: Any) -> None:
    async with _RECOVERY_LOCK:
        for job in pending_jobs(mod, 100):
            job_id = str(job["job_id"])
            if job_id in _ACTIVE_RECOVERY:
                continue
            if int(time.time()) - int(job.get("created_ts") or 0) > 24 * 3600:
                update_job(mod, job_id, state="failed", error="Recovery window expired")
                continue
            _ACTIVE_RECOVERY.add(job_id)
            update_job(mod, job_id, state="recovering", next_poll_ts=int(time.time()) + 30)
            try:
                provider = str(job.get("provider") or "")
                if provider == "suno":
                    ok = await _recover_suno(mod, app, job)
                elif provider in {"sora", "kling", "runway", "comet"}:
                    ok = await _recover_generic_video(mod, app, job)
                else:
                    ok = False
                update_job(mod, job_id, state="completed" if ok else "failed", error="" if ok else "Recovery returned no result")
                if not ok:
                    with contextlib.suppress(Exception):
                        await app.bot.send_message(chat_id=int(job["chat_id"]), text=f"⚠️ Не удалось автоматически восстановить задачу {job_id}. Повторное списание не выполнялось; обратитесь в поддержку.")
            except Exception as exc:
                update_job(mod, job_id, state="failed", error=repr(exc))
                record_event(_db_path(mod), "job_recovery_error", severity="error", user_id=int(job.get("user_id") or 0), feature=str(job.get("feature") or ""), details={"job_id": job_id, "error": repr(exc)})
            finally:
                _ACTIVE_RECOVERY.discard(job_id)


def _ids(update: Any) -> tuple[int, int]:
    user_id = int(getattr(getattr(update, "effective_user", None), "id", 0) or 0)
    chat_id = int(getattr(getattr(update, "effective_chat", None), "id", 0) or 0)
    return user_id, chat_id


def patch_runtime(mod: Any) -> bool:
    changed = False

    original_suno = getattr(mod, "_poll_suno_task", None)
    if callable(original_suno) and not getattr(original_suno, "_prod_durable", False):
        async def poll_suno(update: Any, client: Any, headers: dict, task_id: str):
            uid, chat_id = _ids(update)
            job_id = begin_job(mod, user_id=uid, chat_id=chat_id, feature="suno_music", provider="suno", provider_task_id=str(task_id), payload={})
            update_job(mod, job_id, state="polling")
            try:
                ok = bool(await original_suno(update, client, headers, task_id))
                update_job(mod, job_id, state="completed" if ok else "failed")
                return ok
            except Exception as exc:
                update_job(mod, job_id, state="failed", error=repr(exc))
                raise
        poll_suno._prod_durable = True  # type: ignore[attr-defined]
        mod._poll_suno_task = poll_suno
        changed = True

    original_video = getattr(mod, "_poll_video_task_generic", None)
    if callable(original_video) and not getattr(original_video, "_prod_durable", False):
        mod._PROD_ORIGINAL_POLL_VIDEO = original_video

        async def poll_video(update: Any, client: Any, headers: dict, base_url: str, status_paths: list[str], task_id: str, caption: str, max_wait_s: int, *args: Any, **kwargs: Any):
            uid, chat_id = _ids(update)
            low = (caption or "").lower()
            provider = "sora" if "sora" in low else "kling" if "kling" in low else "runway" if "runway" in low else "comet"
            job_id = begin_job(
                mod,
                user_id=uid,
                chat_id=chat_id,
                feature="video_generation",
                provider=provider,
                provider_task_id=str(task_id),
                payload={"base_url": base_url, "status_paths": list(status_paths or []), "caption": caption, "max_wait_s": int(max_wait_s or 1200)},
            )
            update_job(mod, job_id, state="polling")
            try:
                ok = bool(await original_video(update, client, headers, base_url, status_paths, task_id, caption, max_wait_s, *args, **kwargs))
                update_job(mod, job_id, state="completed" if ok else "failed")
                return ok
            except Exception as exc:
                update_job(mod, job_id, state="failed", error=repr(exc))
                raise
        poll_video._prod_durable = True  # type: ignore[attr-defined]
        mod._poll_video_task_generic = poll_video
        changed = True

    if changed:
        mod._PROD_JOBS_PATCHED = True
    return changed or bool(getattr(mod, "_PROD_JOBS_PATCHED", False))


async def diag_jobs(mod: Any, update: Any, context: Any) -> None:
    jobs = pending_jobs(mod, 20)
    lines = ["🧰 Durable jobs diagnostic", f"pending={len(jobs)}"]
    for job in jobs[:10]:
        age = max(0, int(time.time()) - int(job.get("created_ts") or 0))
        lines.append(f"• {job['job_id']} · {job['provider']} · {job['feature']} · {job['state']} · age={age}s")
    if not jobs:
        lines.append("Активных незавершённых задач нет.")
    await update.effective_message.reply_text("\n".join(lines)[:3900])


__all__ = ["begin_job", "update_job", "pending_jobs", "recover_pending", "patch_runtime", "diag_jobs"]
