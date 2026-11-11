"""Side-effect-free Studio navigation handoff."""
import json

from .studio_menu_catalog import verified_section
from .studio_menu_navigation import resolve_navigation

def navigation_response(raw: str) -> tuple[str, str] | None:
    callback = resolve_navigation(raw)
    if callback is None:
        return None
    section = verified_section(json.loads(raw)["route"])
    if section is None:
        return None
    return callback, "Выбран раздел: " + section.title
