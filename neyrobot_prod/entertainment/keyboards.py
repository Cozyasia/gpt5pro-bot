"""Telegram-independent rendering helpers for entertainment menus."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .catalog import get_menu, iter_menus


@dataclass(frozen=True, slots=True)
class EntertainmentCallback:
    kind: Literal["menu", "soon", "back", "unknown"]
    target: str


_SOON_SERVICE_ID = re.compile(r"^[a-z0-9_]{1,40}$")


def build_keyboard(menu_id: str, button_cls: type, markup_cls: type) -> object:
    menu = get_menu(menu_id)
    rows = [
        [
            button_cls(button.text, callback_data=button.callback_data)
            for button in row
        ]
        for row in menu.rows
    ]
    return markup_cls(rows)


def classify_callback(data: str) -> EntertainmentCallback:
    parts = str(data or "").split(":")
    if len(parts) != 3 or parts[0] != "ent":
        return EntertainmentCallback("unknown", "")

    kind, target = parts[1], parts[2]
    menu_ids = {menu.menu_id for menu in iter_menus()}
    if kind in {"menu", "back"} and target in menu_ids:
        return EntertainmentCallback(kind, target)
    if kind == "soon" and _SOON_SERVICE_ID.fullmatch(target):
        return EntertainmentCallback("soon", target)
    return EntertainmentCallback("unknown", "")
