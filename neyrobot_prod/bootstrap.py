# -*- coding: utf-8 -*-
"""Early production bootstrap for Neyro-Bot v119.

Loaded by ``sitecustomize.py`` before main.py reads secrets or builds the PTB
Application. Critical routes are registered at negative handler groups and the
runtime patches are re-applied after legacy asynchronous patch workers settle.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import VERSION
from .db import backup_database, connect, init_schema, install_sqlite_hardening, record_event

_INSTALLED = False
_RUNTIME_THREAD_STARTED = False
_BACKUP_THREAD_STARTED = False
_BUILDER_HOOKED = False


def _flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() not in {"0", "false", "no", "off"}


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _is_owner(mod: Any, user: Any) -> bool:
    uid = int(getattr(user, "id", 0) or 0)
    if uid and uid == int(getattr(mod, "OWNER_ID", 0) or 0):
        return True
    checker = getattr(mod, "is_unlimited", None)
    if callable(checker):
        with contextlib.suppress(Exception):
            return bool(checker(uid, str(getattr(user, "username", "") or "")))
    return False


def _key_paths(mod: Any) -> tuple[str, ...]:
    db_path = Path(str(getattr(mod, "DB_PATH", "/data/subs.db") or "/data/subs.db"))
    configured = (os.environ.get("MEDICAL_CARD_STORAGE_DIR") or "").strip()
    root = Path(configured) if configured else db_path.parent / "medical_card_files"
    candidates = [
        root / ".medical_card_fernet.key",
        db_path.parent / ".medical_card_fernet.key",
    ]
    return tuple(str(path) for path in candidates)


def _run_backup(mod: Any) -> dict[str, Any]:
    db_path = str(getattr(mod, "DB_PATH", "/data/subs.db") or "/data/subs.db")
    backup_dir = (os.environ.get("BACKUP_DIR") or str(Path(db_path).parent / "backups")).strip()
    retention = max(3, int(os.environ.get("BACKUP_RETENTION", "14") or 14))
    result = backup_database(db_path, backup_dir, key_paths=_key_paths(mod), retention=retention)
    record_event(db_path, "database_backup", details=result)
    return result


def _start_backup_thread() -> None:
    global _BACKUP_THREAD_STARTED
    if _BACKUP_THREAD_STARTED or not _flag("AUTO_BACKUP_ENABLED", True):
        return
    _BACKUP_THREAD_STARTED = True

    def worker() -> None:
        initial_delay = max(30, int(os.environ.get("BACKUP_INITIAL_DELAY_S", "90") or 90))
        interval = max(3600, int(os.environ.get("BACKUP_INTERVAL_S", "86400") or 86400))
        time.sleep(initial_delay)
        while True:
            mod = _runtime_module()
            if mod is not None:
                try:
                    _run_backup(mod)
                except Exception as exc:
                    record_event(
                        str(getattr(mod, "DB_PATH", "") or ""),
                        "database_backup_error",
                        severity="error",
                        details={"error": repr(exc)},
                    )
            time.sleep(interval)

    threading.Thread(target=worker, name="neyrobot-backup-v119", daemon=True).start()


async def _priority_successful_payment(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    mod = _runtime_module()
    try:
        if mod is None:
            raise RuntimeError("runtime module unavailable")
        from .payments import successful_payment_handler
        await successful_payment_handler(mod, update, context)
    except Exception as exc:
        if mod is not None:
            logger = getattr(mod, "log", None)
            with contextlib.suppress(Exception):
                logger.exception("v119 successful payment processing failed: %r", exc)
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text(
                "⚠️ Платёж получен, но автоматическая обработка не завершилась. "
                "Повторно платить не нужно — обратитесь в поддержку."
            )
    raise ApplicationHandlerStop


async def _priority_precheckout(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    mod = _runtime_module()
    try:
        if mod is None:
            await update.pre_checkout_query.answer(ok=False, error_message="Бот ещё запускается. Повторите оплату через минуту.")
        else:
            from .payments import precheckout_handler
            await precheckout_handler(mod, update, context)
    finally:
        raise ApplicationHandlerStop


async def _cmd_diag_prod(update: Any, context: Any) -> None:
    mod = _runtime_module()
    if mod is None:
        return
    db_path = str(getattr(mod, "DB_PATH", "") or "")
    journal = "—"
    payment_events = durable_jobs = 0
    try:
        init_schema(db_path)
        con = connect(db_path)
        try:
            journal = str(con.execute("PRAGMA journal_mode").fetchone()[0])
            payment_events = int(con.execute("SELECT COUNT(*) FROM payment_events").fetchone()[0])
            durable_jobs = int(con.execute("SELECT COUNT(*) FROM durable_jobs WHERE state IN ('pending','polling','recovering')").fetchone()[0])
        finally:
            con.close()
    except Exception as exc:
        journal = f"error:{type(exc).__name__}"

    text_handler = getattr(getattr(mod, "_medical_analyze_text", None), "_prod_v119_medical", False)
    image_handler = getattr(getattr(mod, "_medical_analyze_image", None), "_prod_v119_medical", False)
    lines = [
        "🛡 Production diagnostic",
        f"version={VERSION}",
        f"sqlite_journal={journal}",
        f"payments_patch={'on' if getattr(mod, '_PROD_PAYMENTS_PATCHED', False) else 'off'}",
        f"payment_events={payment_events}",
        f"jobs_patch={'on' if getattr(mod, '_PROD_JOBS_PATCHED', False) else 'off'}",
        f"concurrency_guard={'on' if getattr(mod, '_PROD_LIMITS_PATCHED', False) else 'off'}",
        f"pending_jobs={durable_jobs}",
        f"medical_text_route={'v119' if text_handler else 'legacy'}",
        f"medical_image_route={'v119' if image_handler else 'legacy'}",
        f"medical_card_version={getattr(mod, 'MEDICAL_CARD_VERSION', '—')}",
        f"auto_backup={'on' if _flag('AUTO_BACKUP_ENABLED', True) else 'off'}",
        f"backup_dir={os.environ.get('BACKUP_DIR') or str(Path(db_path).parent / 'backups')}",
    ]
    await update.effective_message.reply_text("\n".join(lines)[:3900])


async def _cmd_diag_jobs(update: Any, context: Any) -> None:
    mod = _runtime_module()
    if mod is None:
        return
    from .jobs import diag_jobs
    await diag_jobs(mod, update, context)


async def _cmd_diag_medcard(update: Any, context: Any) -> None:
    mod = _runtime_module()
    if mod is None:
        return
    from .medical_followup import diag_medcard
    await diag_medcard(mod, update, context)


async def _cmd_backup_now(update: Any, context: Any) -> None:
    mod = _runtime_module()
    if mod is None:
        return
    if not _is_owner(mod, update.effective_user):
        await update.effective_message.reply_text("Команда доступна владельцу бота.")
        return
    try:
        result = await asyncio.to_thread(_run_backup, mod)
        await update.effective_message.reply_text(
            f"✅ Резервная копия создана.\nDB: {result.get('db')}\nКлючей скопировано: {len(result.get('keys') or [])}"
        )
    except Exception as exc:
        await update.effective_message.reply_text(f"❌ Резервная копия не создана: {type(exc).__name__}: {exc}")


async def _post_init_recovery(app: Any, previous: Any = None) -> None:
    if callable(previous):
        await previous(app)
    mod = _runtime_module()
    if mod is None or not _flag("JOB_RECOVERY_ENABLED", True):
        return
    from .jobs import recover_pending
    await recover_pending(mod, app)


def _install_builder_hook() -> None:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return
    try:
        from telegram.ext import (
            ApplicationBuilder,
            CommandHandler,
            MessageHandler,
            PreCheckoutQueryHandler,
            filters,
        )
    except Exception:
        return
    if getattr(ApplicationBuilder, "_neyrobot_prod_v119_hooked", False):
        _BUILDER_HOOKED = True
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, "_neyrobot_prod_v119_handlers", False):
            app.add_handler(PreCheckoutQueryHandler(_priority_precheckout), group=-100)
            app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, _priority_successful_payment), group=-100)
            app.add_handler(CommandHandler("diag_prod", _cmd_diag_prod), group=-99)
            app.add_handler(CommandHandler("diag_jobs", _cmd_diag_jobs), group=-99)
            app.add_handler(CommandHandler("diag_medcard", _cmd_diag_medcard), group=-99)
            app.add_handler(CommandHandler("backup_now", _cmd_backup_now), group=-99)
            previous = getattr(app, "post_init", None)

            async def post_init(application: Any) -> None:
                await _post_init_recovery(application, previous)

            with contextlib.suppress(Exception):
                app.post_init = post_init
            setattr(app, "_neyrobot_prod_v119_handlers", True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, "_neyrobot_prod_v119_hooked", True)
    _BUILDER_HOOKED = True


def _apply_runtime(mod: Any) -> tuple[bool, bool, bool, bool]:
    from . import jobs, limits, medical_followup, payments

    payment_ok = payments.patch_runtime(mod)
    jobs_ok = jobs.patch_runtime(mod)
    medical_ok = medical_followup.patch_runtime(mod)
    limits_ok = limits.patch_runtime(mod)
    if payment_ok and jobs_ok and medical_ok and limits_ok:
        mod.PATCH_VERSION = VERSION
        mod.PRODUCTION_HARDENING_VERSION = VERSION
        mod._PROD_HARDENING_V119 = True
        db_path = str(getattr(mod, "DB_PATH", "") or "")
        if db_path:
            init_schema(db_path)
    return payment_ok, jobs_ok, medical_ok, limits_ok


def _start_runtime_worker() -> None:
    global _RUNTIME_THREAD_STARTED
    if _RUNTIME_THREAD_STARTED:
        return
    _RUNTIME_THREAD_STARTED = True

    def worker() -> None:
        stable_rounds = 0
        for _ in range(3600):
            mod = _runtime_module()
            if mod is None:
                time.sleep(0.1)
                continue
            try:
                state = _apply_runtime(mod)
                if all(state):
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                if stable_rounds >= 100:
                    _start_backup_thread()
                    return
            except Exception as exc:
                db_path = str(getattr(mod, "DB_PATH", "") or "")
                if db_path:
                    record_event(db_path, "runtime_patch_error", severity="error", details={"error": repr(exc)})
            time.sleep(0.1)
        _start_backup_thread()

    threading.Thread(target=worker, name="neyrobot-production-v119", daemon=True).start()


def install_early() -> None:
    global _INSTALLED
    if _INSTALLED or not _flag("PROD_HARDENING_ENABLED", True):
        return
    install_sqlite_hardening()
    _install_builder_hook()
    _start_runtime_worker()
    _INSTALLED = True


__all__ = ["install_early", "VERSION"]
