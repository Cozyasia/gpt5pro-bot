"""Safe navigation contract for Neyro Studio Mini App.

This module does not register Telegram handlers or alter production behavior.
Only a trusted Telegram web_app_data handler may call resolve_navigation().
"""
import json

ALLOWED_ROUTES = frozenset({
    "mode:medicine", "mode:study", "mode:work",
    "engine:images", "engine:kling",
})
MAX_PAYLOAD_BYTES = 512


def resolve_navigation(raw: str) -> str | None:
    """Validate a Mini App navigation payload; return allowlisted route or None.

    Authentication of the Telegram update, entitlement and consent checks must
    remain in the production Telegram handler before dispatch.
    """
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        return None
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict) or set(obj) != {"v", "action", "route"}:
        return None
    if type(obj["v"]) is not int or obj["v"] != 1 or obj["action"] != "open_mode":
        return None
    route = obj["route"]
    if not isinstance(route, str) or route not in ALLOWED_ROUTES:
        return None
    return route
