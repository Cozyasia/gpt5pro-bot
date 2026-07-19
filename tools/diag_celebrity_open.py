# -*- coding: utf-8 -*-
import asyncio
import traceback
from pathlib import Path
from types import SimpleNamespace

import celebrity_selfie_v128 as feature


class Message:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kwargs):
        self.sent.append((text, reply_markup))
        return SimpleNamespace()


class Context:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}
        self.bot = SimpleNamespace()


async def probe():
    message = Message()
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=123456),
        effective_chat=SimpleNamespace(id=123456),
    )
    context = Context()
    original_cached = feature.core._cached_photo
    feature.core._cached_photo = lambda _update: None
    try:
        await feature.core._open(update, context)
        session = feature.core._session(context, create=False)
        return {
            "ok": True,
            "version": feature.VERSION,
            "session_root": str(feature._writable_session_root()),
            "sent": [(text, type(markup).__name__ if markup is not None else None) for text, markup in message.sent],
            "session": dict(session),
            "active": feature.core._active(context),
        }
    finally:
        feature.core._cached_photo = original_cached


def main():
    target = Path("celebrity-diagnostic.txt")
    try:
        result = asyncio.run(probe())
        target.write_text(repr(result), encoding="utf-8")
        print("CELEBRITY_DIAGNOSTIC_OK")
    except BaseException:
        target.write_text(traceback.format_exc(), encoding="utf-8")
        print("CELEBRITY_DIAGNOSTIC_FAILED")
        raise


if __name__ == "__main__":
    main()
