"""Result-first entertainment navigation for the Telegram bot."""

from .catalog import (
    MenuButtonSpec,
    MenuSpec,
    entertainment_menu_v2_enabled,
    get_menu,
    iter_menus,
)
from .keyboards import EntertainmentCallback, build_keyboard, classify_callback

__all__ = [
    "MenuButtonSpec",
    "MenuSpec",
    "entertainment_menu_v2_enabled",
    "get_menu",
    "iter_menus",
    "build_keyboard",
    "EntertainmentCallback",
    "classify_callback",
]
