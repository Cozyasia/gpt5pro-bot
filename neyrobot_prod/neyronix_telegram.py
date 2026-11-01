"""NEYRONIX Telegram profile, command and Mini App configuration.

The module deliberately returns a sanitized verification snapshot. Bot tokens,
provider keys and raw Telegram responses must never be logged by callers.
"""
from __future__ import annotations

from urllib.parse import urlsplit


BRAND_NAME = "NEYRONIX"
DEFAULT_BOT_USERNAME = "neyronixbot"
DEFAULT_MENU_URL = "https://neyro-studio-ui.onrender.com/"
MENU_BUTTON_TEXT = "Открыть NEYRONIX"

SHORT_DESCRIPTION = (
    "NEYRONIX — AI-студия для текста, документов, изображений, видео, музыки и речи."
)
DESCRIPTION = (
    "NEYRONIX — мультимодельная AI-студия в Telegram: чат и документы, "
    "изображения, Маркетплейсы, видео, музыка, речь, нейропродакшен и "
    "видеообзоры недвижимости. Выберите направление или напишите задачу."
)


def public_commands() -> tuple[tuple[str, str], ...]:
    """Public commands shown by Telegram; owner diagnostics stay hidden."""
    return (
        ("start", "Запустить NEYRONIX"),
        ("menu", "Открыть главное меню"),
        ("help", "Помощь"),
        ("examples", "Примеры"),
        ("chats", "Мои чаты"),
        ("newchat", "Новый чат"),
        ("balance", "Баланс"),
        ("plans", "Тарифы и подписка"),
    )


def resolve_menu_url(value: str | None) -> str:
    """Return a safe HTTPS Mini App catalog URL, never a checkout endpoint."""
    url = (value or DEFAULT_MENU_URL).strip()
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("NEYRONIX menu URL must be an absolute HTTPS URL")
    if parsed.path.rstrip("/").endswith("/webapp/checkout"):
        raise ValueError("Telegram menu must open the catalog, not checkout")
    return url


async def configure_shell(
    bot,
    *,
    expected_username: str = DEFAULT_BOT_USERNAME,
    menu_url: str | None = None,
) -> dict:
    """Verify token identity, configure public shell, and return safe evidence."""
    from telegram import BotCommand, MenuButtonWebApp, WebAppInfo

    expected = (expected_username or DEFAULT_BOT_USERNAME).strip().lstrip("@").lower()
    me = await bot.get_me()
    actual = (getattr(me, "username", "") or "").strip().lstrip("@").lower()
    if actual != expected:
        raise RuntimeError(
            f"Telegram token identity mismatch: expected @{expected}, received @{actual or 'unknown'}"
        )

    safe_menu_url = resolve_menu_url(menu_url)
    commands = public_commands()
    await bot.set_my_name(name=BRAND_NAME)
    await bot.set_my_short_description(short_description=SHORT_DESCRIPTION)
    await bot.set_my_description(description=DESCRIPTION)
    await bot.set_my_commands([BotCommand(command=name, description=description) for name, description in commands])
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text=MENU_BUTTON_TEXT,
            web_app=WebAppInfo(url=safe_menu_url),
        )
    )

    webhook = await bot.get_webhook_info()
    menu = await bot.get_chat_menu_button()
    actual_menu_url = getattr(getattr(menu, "web_app", None), "url", "") or ""
    if actual_menu_url != safe_menu_url:
        raise RuntimeError("Telegram returned an unexpected Mini App menu URL")

    last_error = getattr(webhook, "last_error_message", None)
    return {
        "bot_id": int(getattr(me, "id", 0) or 0),
        "username": actual,
        "first_name": getattr(me, "first_name", "") or "",
        "webhook_url": getattr(webhook, "url", "") or "",
        "pending_updates": int(getattr(webhook, "pending_update_count", 0) or 0),
        "last_webhook_error": str(last_error)[:300] if last_error else None,
        "menu_url": actual_menu_url,
        "commands": [name for name, _ in commands],
    }


# A small introspection seam used by runtime diagnostics and contract tests.
configure_shell.public_commands = public_commands


__all__ = [
    "BRAND_NAME",
    "DEFAULT_BOT_USERNAME",
    "DEFAULT_MENU_URL",
    "MENU_BUTTON_TEXT",
    "configure_shell",
    "public_commands",
    "resolve_menu_url",
]
