"""Validated Studio Mini App navigation for current production callbacks."""
import json
from .studio_menu_catalog import verified_callback

ALLOWED_SLUGS = frozenset(("market", "realty", "advert"))
MAX_PAYLOAD_BYTES = 512

def resolve_navigation(raw: str) -> str | None:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or set(data) != {"v", "action", "route"}:
        return None
    if type(data["v"]) is not int or data["v"] != 1 or data["action"] != "open_mode":
        return None
    slug = data["route"]
    if not isinstance(slug, str) or slug not in ALLOWED_SLUGS:
        return None
    return verified_callback(slug)
