"""Non-invasive dispatcher for Telegram WebApp navigation.

Call this only from the existing on_webapp_data handler *before* its payment
branches. No direct callback spoofing or payment handling occurs here.
"""
from .studio_menu_navigation import resolve_navigation


def navigation_response(raw: str) -> tuple[str, str] | None:
    """Return (route, user-facing text) for a valid Mini App navigation request.

    Caller must verify Telegram update identity and dispatch only via the
    existing trusted mode entry points. This helper deliberately does not
    perform side effects or grant access.
    """
    route = resolve_navigation(raw)
    if route is None:
        return None
    titles = {
        "mode:medicine": "AI-Медицина",
        "mode:study": "Учёба",
        "mode:work": "Работа",
        "engine:images": "AI-Фотостудия",
        "engine:kling": "AI-Видео",
    }
    return route, f"Выбран раздел: {titles[route]}"
