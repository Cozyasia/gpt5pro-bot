"""Single-submit scene execution with persistent billing-safe journal states.

The caller owns a cross-process job lock and provides the provider's submit,
poll and result-storage callbacks. Never auto-resubmit uncertain submissions.
"""
from __future__ import annotations
from pathlib import Path
from typing import Awaitable, Callable

from .veo_task_journal import mark_scene, read_job


class ReconciliationRequired(RuntimeError):
    pass


async def run_journaled_scene(
    journal_path: str | Path,
    index: int,
    submit: Callable[[], Awaitable[str]],
    poll: Callable[[str], Awaitable[bytes]],
    save_result: Callable[[int, bytes], Awaitable[None]],
) -> bytes:
    """Resume known task IDs; never submit twice after an ambiguous response.

    Caller must serialize access to the journal across processes. The durable
    completed marker is written only after save_result returns successfully.
    """
    prior = read_job(journal_path)["scenes"].get(str(index))
    if prior:
        state, task_id = prior.get("state"), prior.get("task_id")
        if state == "completed":
            raise ReconciliationRequired(
                "Completed scene: load its persisted artifact instead of regenerating"
            )
        if not task_id:
            raise ReconciliationRequired(
                "Unknown submission outcome: reconcile provider before retry"
            )
    else:
        mark_scene(journal_path, index, "submitting")
        try:
            task_id = await submit()
            if not isinstance(task_id, str) or not task_id.strip():
                raise ValueError("Provider did not return a task ID")
            mark_scene(journal_path, index, "accepted", task_id.strip())
        except BaseException:
            mark_scene(journal_path, index, "uncertain")
            raise
    try:
        data = await poll(task_id)
        if not isinstance(data, bytes) or not data:
            raise ValueError("Provider returned no video bytes")
        await save_result(index, data)
        mark_scene(journal_path, index, "completed", task_id)
        return data
    except BaseException:
        # The accepted task remains recoverable by task ID; never resubmit.
        raise
