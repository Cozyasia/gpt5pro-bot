# -*- coding: utf-8 -*-
"""Stable bootstrap for the v130 quality overlay.

The historical v127 module calls its v126 implementation ``core`` rather than
``previous``. Expose that alias before importing v130 so the shared release
version can be propagated through the old routing chain without special cases.
"""
from __future__ import annotations

import celebrity_selfie_v129 as base

_v127 = base.previous.previous
if not hasattr(_v127, "previous"):
    _v127.previous = _v127.core

import celebrity_selfie_v130 as impl  # noqa: E402

VERSION = impl.VERSION
core = impl.core


async def _open_30(update, context) -> None:
    session = core._new_session(context)
    cached = core._cached_photo(update)
    if cached:
        session["state"] = "choose_user_photo"
        session["cached_candidate_path"] = core._store_image(
            update, session, "cached_selfie.jpg", cached
        )
        await core._reply(
            update,
            "📸 Селфи со звездой — точное сохранение лиц\n\n"
            "Выберите последнее фото или загрузите новое. Затем откроется проверенный "
            "каталог из 20 российских и 10 американских знаменитостей.",
            core._photo_choice_kb(True),
        )
    else:
        session["state"] = "await_user_photo"
        await core._reply(
            update,
            "📸 Селфи со звездой — точное сохранение лиц\n\n"
            "Пришлите чёткое селфи: один человек, лицо крупно, без фильтров и смаза. "
            "Фото пройдёт проверку качества до генерации.",
            core._photo_choice_kb(False),
        )


core._open = _open_30

install_builder_hook = impl.install_builder_hook

__all__ = ["VERSION", "install_builder_hook"]
