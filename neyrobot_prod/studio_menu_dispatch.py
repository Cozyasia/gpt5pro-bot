"""Side-effect-free Studio navigation handoff."""
from .studio_menu_navigation import resolve_navigation

def navigation_response(raw: str) -> tuple[str, str] | None:
    callback = resolve_navigation(raw)
    if callback is None:
        return None
    titles = {
        "ent:brief:product_ad": "Маркетплейсы",
        "revideo:start": "Видеообзор недвижимости",
    }
    return callback, "Выбран раздел: " + titles[callback]
