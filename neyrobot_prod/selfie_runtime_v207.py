# -*- coding: utf-8 -*-
"""Canonical Celebrity Selfie V207 runtime.

This layer resolves three production problems at once:
- legacy V203 workers must not take ownership back from the proven V204 Comet
  multi-reference generator;
- V205 storage must be installed through the guaranteed main.py bootstrap;
- service commands must never fail silently when the persistent disk is absent
  or temporarily unavailable.
"""
from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

VERSION = "v207-selfie-canonical-runtime-2026-07-25"
PERSISTENT_ROOT = Path("/data/celebrity_selfie")
FALLBACK_ROOT = Path("/tmp/celebrity_selfie")
_STARTED = False
_SELECTED_ROOT: Path | None = None


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


def _candidate_roots(mod: Any | None = None) -> list[Path]:
    candidates: list[Path] = [PERSISTENT_ROOT]
    configured = str(os.environ.get("CELEBRITY_SELFIE_DATA_DIR", "") or "").strip()
    if configured and not configured.startswith("/opt/render/project/src"):
        candidates.append(Path(configured))
    if mod is not None:
        with contextlib.suppress(Exception):
            db_path = Path(str(getattr(mod, "DB_PATH", "/data/subs.db") or "/data/subs.db")).resolve()
            candidates.append(db_path.parent / "celebrity_selfie")
    candidates.append(FALLBACK_ROOT)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _select_root(mod: Any | None = None) -> Path:
    global _SELECTED_ROOT
    if _SELECTED_ROOT is not None:
        return _SELECTED_ROOT
    errors: list[str] = []
    for root in _candidate_roots(mod):
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".v207_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            _SELECTED_ROOT = root
            os.environ["CELEBRITY_SELFIE_DATA_DIR"] = str(root)
            return root
        except Exception as exc:
            errors.append(f"{root}: {type(exc).__name__}: {exc}")
    raise RuntimeError("No writable Celebrity Selfie storage: " + " | ".join(errors[-4:]))


def storage_root(mod: Any | None = None) -> Path:
    return _select_root(mod)


def _data_mount_state() -> str:
    with contextlib.suppress(Exception):
        if os.path.ismount("/data"):
            return "on"
    return "off"


def _persistent_state(root: Path) -> str:
    try:
        return "on" if root.resolve().is_relative_to(Path("/data").resolve()) and _data_mount_state() == "on" else "off"
    except Exception:
        return "off"


def _log_exception(mod: Any | None, label: str, exc: Exception) -> None:
    logger = getattr(mod, "log", None) if mod is not None else None
    if logger is not None:
        with contextlib.suppress(Exception):
            logger.exception("%s: %s", label, exc)
            return
    print(f"[neyrobot-prod] {label}: {type(exc).__name__}: {exc}")


async def admin_command(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import selfie_admin_v202 as admin_v202
    from neyrobot_prod import selfie_storage_v205 as storage_v205

    message = getattr(update, "effective_message", None)
    user = getattr(update, "effective_user", None)
    mod = _runtime_module()
    try:
        if message is None:
            return
        if mod is None or user is None:
            await message.reply_text("❌ Сервисное меню не запущено: основной runtime ещё не найден.")
            return
        if not admin_v202.is_admin(mod, user):
            await message.reply_text(admin_v202._denied_text(mod, user))
            return
        patch_runtime()
        root = storage_root(mod)
        await message.reply_text(
            f"🛠 Каталог AI-селфи · {VERSION}\n"
            f"Хранилище: {root}\n"
            f"Persistent Disk /data: {'подключён' if _persistent_state(root) == 'on' else 'не подтверждён; используется резервный путь'}\n"
            "Выберите героя:",
            reply_markup=storage_v205._catalog_kb(mod),
        )
    except Exception as exc:
        _log_exception(mod, "V207 selfie admin failed", exc)
        if message is not None:
            with contextlib.suppress(Exception):
                await message.reply_text(
                    "❌ Сервисное меню AI-селфи не открылось. "
                    f"Причина: {type(exc).__name__}: {str(exc)[:900]}"
                )
    finally:
        raise ApplicationHandlerStop


async def diagnostic(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base

    message = getattr(update, "effective_message", None)
    mod = _runtime_module()
    try:
        if message is None:
            return
        if mod is None:
            await message.reply_text("❌ Selfie Storage diagnostic: основной runtime ещё не найден.")
            return
        patch_runtime()
        root = storage_root(mod)
        lines = [
            "💾 Selfie Storage diagnostic",
            f"version={VERSION}",
            f"storage={root}",
            f"data_is_mount={_data_mount_state()}",
            f"persistent_storage={_persistent_state(root)}",
            f"characters={len(base.CHARACTERS)}",
            "generator=v204-comet-multireference",
        ]
        for slug, meta in base.CHARACTERS.items():
            lines.append(
                f"{slug}={base._character_status(mod, slug)} "
                f"ready={'on' if base._character_ready(mod, slug) else 'off'}"
            )
        await message.reply_text("\n".join(lines))
    except Exception as exc:
        _log_exception(mod, "V207 selfie storage diagnostic failed", exc)
        if message is not None:
            with contextlib.suppress(Exception):
                await message.reply_text(
                    "❌ Диагностика хранилища не выполнена. "
                    f"Причина: {type(exc).__name__}: {str(exc)[:900]}"
                )
    finally:
        raise ApplicationHandlerStop


def _disable_legacy_v203() -> None:
    """Stop the already-started V203 worker from reclaiming base._generate."""
    with contextlib.suppress(Exception):
        from neyrobot_prod import celebrity_selfie_v203 as legacy_v203

        def no_op_patch() -> bool:
            return True

        legacy_v203.patch = no_op_patch


def _patch_storage_module() -> None:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_admin_v202 as admin_v202
    from neyrobot_prod import selfie_storage_v205 as storage_v205

    root = storage_root(_runtime_module())
    storage_v205.ROOT = root
    storage_v205._ensure_root = lambda: storage_root(_runtime_module())
    storage_v205.storage_root = storage_root
    storage_v205._authorized = lambda runtime, user: admin_v202.is_admin(runtime, user)
    storage_v205.admin_command = admin_command
    storage_v205.diagnostic = diagnostic
    base._storage_root = storage_root
    os.environ["CELEBRITY_SELFIE_DATA_DIR"] = str(root)


def _publish_versions(mod: Any | None) -> None:
    if mod is None:
        return
    from neyrobot_prod import celebrity_selfie_v204 as generator_v204

    mod.CELEBRITY_SELFIE_VERSION = generator_v204.VERSION
    mod.AI_SELFIE_RUNTIME_VERSION = generator_v204.VERSION
    mod.CELEBRITY_SELFIE_ROUTE = "v204-comet-multireference"
    mod.SELFIE_STORAGE_VERSION = VERSION
    mod.SELFIE_COMMANDS_VERSION = VERSION
    mod.CELEBRITY_SELFIE_DATA_DIR = str(storage_root(mod))


def patch_runtime() -> bool:
    from neyrobot_prod import celebrity_selfie_v204 as generator_v204
    from neyrobot_prod import selfie_commands_v206 as commands_v206
    from neyrobot_prod import selfie_storage_v205 as storage_v205

    _disable_legacy_v203()
    _patch_storage_module()
    generator_v204.patch()
    storage_v205.patch()
    commands_v206.VERSION = VERSION
    _publish_versions(_runtime_module())
    return True


def install_async() -> None:
    global _STARTED
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as generator_v204
    from neyrobot_prod import selfie_commands_v206 as commands_v206
    from neyrobot_prod import selfie_storage_v205 as storage_v205

    _disable_legacy_v203()
    _patch_storage_module()
    base.install_async()
    generator_v204.install_async()
    storage_v205.install_async()
    commands_v206.VERSION = VERSION
    patch_runtime()

    if _STARTED:
        return
    _STARTED = True

    def worker() -> None:
        stable = 0
        for _ in range(3600):
            try:
                patch_runtime()
                mod = _runtime_module()
                if mod is not None and callable(getattr(mod, "_try_pay_then_do", None)):
                    stable += 1
                    if stable >= 600:
                        return
                else:
                    stable = 0
            except Exception as exc:
                stable = 0
                _log_exception(_runtime_module(), "V207 selfie runtime patch failed", exc)
            time.sleep(0.1)

    threading.Thread(
        target=worker,
        name="neyrobot-selfie-runtime-v207",
        daemon=True,
    ).start()


def install() -> None:
    install_async()


__all__ = [
    "VERSION",
    "PERSISTENT_ROOT",
    "FALLBACK_ROOT",
    "storage_root",
    "admin_command",
    "diagnostic",
    "patch_runtime",
    "install_async",
    "install",
]
