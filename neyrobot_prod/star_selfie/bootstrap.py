from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from typing import Any, Callable

_HOOKED = False
_MENU_CALLBACK = "fun:star_selfie"
_MODE_MENU_CALLBACK = "act:fun:star_selfie"
_BUTTON_TEXT = "⭐ Селфи со звездой"


def _enabled() -> bool:
    return (os.getenv("STAR_SELFIE_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}


def _inject_button(markup: Any, callback_data: str) -> Any:
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        rows = [list(row) for row in markup.inline_keyboard]
        if any(
            getattr(button, "callback_data", None) in {_MENU_CALLBACK, _MODE_MENU_CALLBACK}
            for row in rows
            for button in row
        ):
            return markup
        insert_at = len(rows)
        if rows and any(getattr(button, "callback_data", None) in {"fun:back", "mode:root"} for button in rows[-1]):
            insert_at -= 1
        rows.insert(insert_at, [InlineKeyboardButton(_BUTTON_TEXT, callback_data=callback_data)])
        return InlineKeyboardMarkup(rows)
    except Exception:
        return markup


def _wrap_menu_function(module: Any, name: str, callback_data: str, *, fun_key_only: bool = False) -> None:
    original = getattr(module, name, None)
    if not callable(original) or getattr(original, "_star_selfie_menu_patch", False):
        return

    def wrapped(*args: Any, **kwargs: Any):
        markup = original(*args, **kwargs)
        if fun_key_only:
            key = args[0] if args else kwargs.get("key")
            if str(key or "").lower() != "fun":
                return markup
        return _inject_button(markup, callback_data)

    setattr(wrapped, "_star_selfie_menu_patch", True)
    setattr(module, name, wrapped)


def _install_entertainment_menu_patch() -> None:
    """Patch already-defined main.py menu factories at ApplicationBuilder.build time."""
    main_module = sys.modules.get("__main__")
    if main_module is None:
        return
    _wrap_menu_function(main_module, "_fun_quick_kb", _MENU_CALLBACK)
    _wrap_menu_function(main_module, "_mode_kb", _MODE_MENU_CALLBACK, fun_key_only=True)


def install_builder_hook(project_root: Path | None = None) -> bool:
    """Install an idempotent PTB ApplicationBuilder hook.

    The hook is always safe to import, but it registers handlers only when
    STAR_SELFIE_ENABLED is explicitly true.
    """
    global _HOOKED
    if _HOOKED:
        return True
    try:
        from telegram.ext import ApplicationBuilder
    except Exception:
        return False

    if getattr(ApplicationBuilder, "_star_selfie_builder_hook", False):
        _HOOKED = True
        return True

    original_build = ApplicationBuilder.build
    root = (project_root or Path.cwd()).resolve()

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not _enabled() or getattr(app, "_star_selfie_handlers", False):
            return app
        try:
            from .admin import register_handlers as register_admin_handlers
            from .config import StarSelfieConfig
            from .diagnostics import register_handler as register_diagnostics_handler
            from .telegram import register_handlers

            config = StarSelfieConfig.from_env(root)
            _install_entertainment_menu_patch()
            register_diagnostics_handler(app, config)
            register_handlers(app, config)
            register_admin_handlers(app, config)
        except Exception as exc:
            with contextlib.suppress(Exception):
                app.bot_data["star_selfie_boot_error"] = f"{type(exc).__name__}: {exc}"
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, "_star_selfie_builder_hook", True)
    _HOOKED = True
    return True


__all__ = ["install_builder_hook"]