# -*- coding: utf-8 -*-
"""Concurrency guard for expensive generation workflows."""
from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

_GLOBAL_SEMAPHORE: asyncio.Semaphore | None = None
_USER_SEMAPHORES: dict[int, asyncio.Semaphore] = {}


def _global_limit() -> int:
    return max(1, min(20, int(os.environ.get("HEAVY_GLOBAL_CONCURRENCY", "3") or 3)))


def _semaphores(user_id: int) -> tuple[asyncio.Semaphore, asyncio.Semaphore]:
    global _GLOBAL_SEMAPHORE
    if _GLOBAL_SEMAPHORE is None:
        _GLOBAL_SEMAPHORE = asyncio.Semaphore(_global_limit())
    user = _USER_SEMAPHORES.setdefault(int(user_id), asyncio.Semaphore(1))
    return _GLOBAL_SEMAPHORE, user


def patch_runtime(mod: Any) -> bool:
    current = getattr(mod, "_try_pay_then_do", None)
    if not callable(current):
        return False
    if getattr(current, "_prod_v119_limited", False):
        mod._PROD_LIMITS_PATCHED = True
        return True

    original = current

    async def guarded(
        update: Any,
        context: Any,
        user_id: int,
        engine: str,
        est_cost_usd: float,
        coro_func: Any,
        *args: Any,
        **kwargs: Any,
    ):
        global_sem, user_sem = _semaphores(int(user_id))
        queued = global_sem.locked() or user_sem.locked()
        if queued:
            with contextlib.suppress(Exception):
                await update.effective_message.reply_text(
                    "⏳ Задача поставлена в очередь. Для одного аккаунта одновременно выполняется "
                    "одна тяжёлая генерация — это защищает от дублей и случайного двойного расхода."
                )
        async with global_sem:
            async with user_sem:
                return await original(
                    update,
                    context,
                    user_id,
                    engine,
                    est_cost_usd,
                    coro_func,
                    *args,
                    **kwargs,
                )

    guarded._prod_v119_limited = True  # type: ignore[attr-defined]
    guarded._prod_v119_original = original  # type: ignore[attr-defined]
    mod._try_pay_then_do = guarded
    mod._PROD_LIMITS_PATCHED = True
    return True


__all__ = ["patch_runtime"]
