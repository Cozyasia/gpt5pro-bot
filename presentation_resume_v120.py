# -*- coding: utf-8 -*-
"""Presentation Studio v120.2 resume router.

Restores the stage-specific presentation wizard keyboard when a user returns to
``💼 Работа/Бизнес`` while a saved presentation project is active. The handler
runs before every broad main-menu router and therefore prevents the project guard
from replying with a dead-end message that has no ``Продолжить`` control.
"""
from __future__ import annotations

import contextlib
import re
import sys
import threading
import time
from typing import Any

VERSION = "v120.2-presentation-resume-router-2026-07-18"
_VERSION_THREAD_STARTED = False

_MENU_RE = re.compile(
    r"^\s*(?:💼\s*)?(?:Работа\s*/\s*Бизнес|Работа\s+и\s+бизнес)\s*$",
    re.IGNORECASE,
)
_RESUME_RE = re.compile(r"^\s*(?:▶️?\s*)?Продолжить\s*$", re.IGNORECASE)


def _presentation_module():
    with contextlib.suppress(Exception):
        import presentation_studio as studio
        return studio
    return None


def _saved_project(studio: Any, user_id: int) -> dict[str, Any] | None:
    with contextlib.suppress(Exception):
        project = studio._load(int(user_id))
        if isinstance(project, dict) and project.get("project_id"):
            return project
    return None


async def _show_resume(studio: Any, update: Any, project: dict[str, Any]) -> None:
    """Show the exact saved stage; always fall back to a live wizard keyboard."""
    try:
        await studio._show_resume(update, project)
        return
    except Exception:
        # Never let a resume-path regression return the user to a text-only dead end.
        pass

    reply = getattr(studio, "_reply", None)
    keyboard = getattr(studio, "START_KB", None)
    if callable(reply):
        await reply(
            update,
            "Проект презентации найден. Нажмите «Продолжить», чтобы восстановить текущий этап мастера, "
            "либо создайте новый проект.",
            keyboard,
        )
        return

    message = getattr(update, "effective_message", None)
    if message is not None:
        await message.reply_text(
            "Проект презентации найден, но меню мастера временно не восстановилось. "
            "Используйте команду /continue."
        )


async def _resume_active_project(update: Any, context: Any) -> None:
    """Resume only when a saved project exists; otherwise leave normal routing intact."""
    message = getattr(update, "effective_message", None)
    user = getattr(update, "effective_user", None)
    if message is None or user is None:
        return

    studio = _presentation_module()
    if studio is None:
        return
    project = _saved_project(studio, int(user.id))
    if not project:
        return

    context.user_data["presentation_studio_active"] = project.get("project_id")
    await _show_resume(studio, update, project)

    # Stop every later Работа/Бизнес handler from replacing the wizard keyboard
    # with the legacy text-only active-project warning.
    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop


async def _menu_entry(update: Any, context: Any) -> None:
    text = str(getattr(getattr(update, "effective_message", None), "text", "") or "")
    if _MENU_RE.match(text) or _RESUME_RE.match(text):
        await _resume_active_project(update, context)


async def _continue_command(update: Any, context: Any) -> None:
    await _resume_active_project(update, context)


def install_builder_hook() -> None:
    """Install the resume handlers at the highest practical priority."""
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
    except Exception:
        return

    if getattr(ApplicationBuilder, "_presentation_resume_v120_hooked", False):
        return

    original_build = ApplicationBuilder.build

    def build(self, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, "_presentation_resume_v120_handlers", False):
            text_filter = filters.TEXT & ~filters.COMMAND & filters.Regex(
                r"^\s*(?:(?:💼\s*)?(?:Работа\s*/\s*Бизнес|Работа\s+и\s+бизнес)|(?:▶️?\s*)?Продолжить)\s*$"
            )
            # -1000 is intentionally earlier than payment/medical/menu overlays.
            app.add_handler(MessageHandler(text_filter, _menu_entry), group=-1000)
            app.add_handler(CommandHandler("continue", _continue_command), group=-1000)
            setattr(app, "_presentation_resume_v120_handlers", True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, "_presentation_resume_v120_hooked", True)


def install_version_async() -> None:
    """Expose the patch version after main.py has finished importing."""
    global _VERSION_THREAD_STARTED
    if _VERSION_THREAD_STARTED:
        return
    _VERSION_THREAD_STARTED = True

    def worker() -> None:
        for _ in range(12000):
            for name in ("__main__", "main"):
                mod = sys.modules.get(name)
                if mod is not None:
                    with contextlib.suppress(Exception):
                        setattr(mod, "PATCH_VERSION", VERSION)
                        setattr(mod, "PRESENTATION_RESUME_VERSION", VERSION)
            time.sleep(0.02)

    threading.Thread(
        target=worker,
        daemon=True,
        name="presentation-resume-v120-version",
    ).start()


__all__ = ["VERSION", "install_builder_hook", "install_version_async"]
