"""Small, allow-listed Mini App deep links that open account screens."""


_SHORTCUTS = {
    "studio_plans": "plans",
    "studio_balance": "balance",
}


def resolve_shortcut(args) -> str | None:
    """Return a named account screen only for one exact known start payload."""
    if not isinstance(args, (list, tuple)) or len(args) != 1:
        return None
    payload = args[0]
    if not isinstance(payload, str):
        return None
    return _SHORTCUTS.get(payload.strip().lower())
