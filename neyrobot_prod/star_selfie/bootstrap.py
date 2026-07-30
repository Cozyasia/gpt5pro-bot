from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

_HOOKED = False


def _enabled() -> bool:
    return (os.getenv("STAR_SELFIE_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}


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
            from .telegram import register_handlers

            config = StarSelfieConfig.from_env(root)
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
