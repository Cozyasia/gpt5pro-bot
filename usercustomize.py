# -*- coding: utf-8 -*-
"""Global Telegram media transport hardening for Render.

Python imports ``usercustomize`` automatically after ``sitecustomize``.  Keep
this patch independent from the face-swap/image pipeline: it only supplies
production-safe timeout defaults for Telegram getFile and media downloads.
Explicit timeout values passed by callers are preserved.
"""
from __future__ import annotations

import os


def _seconds(name: str, default: float) -> float:
    try:
        return max(1.0, float(os.environ.get(name, str(default)) or default))
    except Exception:
        return float(default)


_CONNECT = _seconds("TELEGRAM_MEDIA_CONNECT_TIMEOUT_S", 45.0)
_READ = _seconds("TELEGRAM_MEDIA_READ_TIMEOUT_S", 180.0)
_WRITE = _seconds("TELEGRAM_MEDIA_DOWNLOAD_WRITE_TIMEOUT_S", 60.0)
_POOL = _seconds("TELEGRAM_MEDIA_POOL_TIMEOUT_S", 45.0)


def _set_default(kwargs: dict, key: str, value: float) -> None:
    # PTB uses DEFAULT_NONE/None when no override is supplied. Supplying a
    # concrete value here makes media operations independent of short request
    # defaults while still respecting an explicit caller value.
    if key not in kwargs or kwargs.get(key) is None:
        kwargs[key] = value


def _install() -> None:
    try:
        from telegram import Bot
        from telegram._files.file import File

        if not getattr(Bot.get_file, "_neyrobot_media_timeout_hardened", False):
            original_get_file = Bot.get_file

            async def get_file_hardened(self, *args, **kwargs):
                _set_default(kwargs, "connect_timeout", _CONNECT)
                _set_default(kwargs, "read_timeout", _READ)
                _set_default(kwargs, "write_timeout", _WRITE)
                _set_default(kwargs, "pool_timeout", _POOL)
                return await original_get_file(self, *args, **kwargs)

            setattr(get_file_hardened, "_neyrobot_media_timeout_hardened", True)
            Bot.get_file = get_file_hardened

        if not getattr(File.download_as_bytearray, "_neyrobot_media_timeout_hardened", False):
            original_download = File.download_as_bytearray

            async def download_as_bytearray_hardened(self, *args, **kwargs):
                _set_default(kwargs, "connect_timeout", _CONNECT)
                _set_default(kwargs, "read_timeout", _READ)
                _set_default(kwargs, "write_timeout", _WRITE)
                _set_default(kwargs, "pool_timeout", _POOL)
                return await original_download(self, *args, **kwargs)

            setattr(download_as_bytearray_hardened, "_neyrobot_media_timeout_hardened", True)
            File.download_as_bytearray = download_as_bytearray_hardened

        print(
            "[neyrobot-prod] TELEGRAM_MEDIA_TRANSPORT hardened "
            f"connect={_CONNECT:.0f}s read={_READ:.0f}s write={_WRITE:.0f}s pool={_POOL:.0f}s",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[neyrobot-prod] TELEGRAM_MEDIA_TRANSPORT patch warning: {type(exc).__name__}: {exc}",
            flush=True,
        )


_install()
