"""Strict Telegram /start deep-link parsing for Studio.

The deep link selects a section but never invokes callback handlers directly.
"""
from .studio_menu_catalog import verified_callback

PREFIX = "studio_"
MAX_LENGTH = 64

def parse_studio_start(args) -> tuple[str, str] | None:
    if not isinstance(args, (list, tuple)) or len(args) != 1:
        return None
    raw = args[0]
    if not isinstance(raw, str) or len(raw) > MAX_LENGTH or not raw.startswith(PREFIX):
        return None
    slug = raw[len(PREFIX):]
    callback = verified_callback(slug)
    if callback is None:
        return None
    return slug, callback

def studio_start_markup(args):
    """Return a safe button that requires an actual Telegram callback click."""
    parsed = parse_studio_start(args)
    if parsed is None:
        return None
    slug, callback = parsed
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    titles = {"market": "Маркетплейсы", "realty": "Недвижимость", "advert": "Реклама товара"}
    return titles[slug], InlineKeyboardMarkup([[
        InlineKeyboardButton("Открыть раздел", callback_data=callback)
    ]])
