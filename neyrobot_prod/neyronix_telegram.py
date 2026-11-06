"""NEYRONIX Telegram profile, command and Mini App configuration.

The module deliberately returns a sanitized verification snapshot. Bot tokens,
provider keys and raw Telegram responses must never be logged by callers.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from urllib.parse import urlsplit


BRAND_NAME = "NEYRONIX"
DEFAULT_BOT_USERNAME = "neyronixbot"
DEFAULT_MENU_URL = "https://neyro-studio-ui.onrender.com/"
MENU_BUTTON_TEXT = "NEYRONIX"

SHORT_DESCRIPTION = (
    "NEYRONIX — AI-студия для текста, документов, изображений, видео, музыки и речи."
)
DESCRIPTION = (
    "NEYRONIX — мультимодельная AI-студия в Telegram: чат и документы, "
    "изображения, Маркетплейсы, видео, музыка, речь, нейропродакшен и "
    "видеообзоры недвижимости. Выберите направление или напишите задачу."
)


def provider_configuration_status(environ: Mapping[str, str]) -> dict[str, bool]:
    """Return provider readiness booleans without copying any secret value."""
    def has(*names: str) -> bool:
        return any(bool(str(environ.get(name, "")).strip()) for name in names)

    def enabled(name: str, default: str = "1") -> bool:
        return str(environ.get(name, default)).strip().lower() not in {
            "0", "false", "no", "off",
        }

    openai = has("OPENAI_API_KEY")
    comet = has("COMET_API_KEY", "COMETAPI_KEY")
    return {
        "openai": openai,
        "openai_images": has("OPENAI_IMAGE_KEY") or openai,
        "openai_stt": has("OPENAI_STT_KEY") or openai,
        "openai_tts": has("OPENAI_TTS_KEY") or openai,
        "tavily": has("TAVILY_API_KEY"),
        "comet": comet,
        "kling": has("KLING_API_KEY") or comet,
        "seedance": enabled("SEEDANCE_ENABLED") and comet,
        "suno": enabled("SUNO_ENABLED") and (has("SUNO_API_KEY") or comet),
        "runway": has("RUNWAYML_API_SECRET", "RUNWAY_API_KEY", "RUNWAY_KEY") or comet,
        "luma": has("LUMA_API_KEY"),
        "gemini_image": has("GEMINI_IMAGE_API_KEY"),
        "heygen": all(has(name) for name in (
            "HEYGEN_API_KEY", "HEYGEN_AVATAR_ID", "HEYGEN_VOICE_ID",
        )),
        "yookassa": (
            has("YOOKASSA_PROVIDER_TOKEN", "PROVIDER_TOKEN_YOOKASSA")
            or (
                has("YOO_SHOP_ID", "YOOKASSA_SHOP_ID", "YK_ID", "PAY_ID")
                and has("YOO_SECRET_KEY", "YOOKASSA_SECRET_KEY", "YK_KEY", "PAY_KEY")
            )
        ),
        "cryptobot": has("CRYPTO_PAY_API_TOKEN"),
    }


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
    desired_commands = [
        BotCommand(command=name, description=description)
        for name, description in commands
    ]

    # Telegram applies very long flood-control windows to profile mutations.
    # Read first and mutate only drifted fields so container restarts are safe.
    if (getattr(me, "first_name", "") or "") != BRAND_NAME:
        await bot.set_my_name(name=BRAND_NAME)
        me = await bot.get_me()

    current_short = await bot.get_my_short_description()
    if (getattr(current_short, "short_description", "") or "") != SHORT_DESCRIPTION:
        await bot.set_my_short_description(short_description=SHORT_DESCRIPTION)

    current_description = await bot.get_my_description()
    if (getattr(current_description, "description", "") or "") != DESCRIPTION:
        await bot.set_my_description(description=DESCRIPTION)

    current_commands = await bot.get_my_commands()
    current_command_rows = [
        (
            str(getattr(item, "command", "") or ""),
            str(getattr(item, "description", "") or ""),
        )
        for item in current_commands
    ]
    if current_command_rows != list(commands):
        await bot.set_my_commands(desired_commands)

    menu = await bot.get_chat_menu_button()
    current_menu_url = getattr(getattr(menu, "web_app", None), "url", "") or ""
    current_menu_text = getattr(menu, "text", "") or ""
    if current_menu_url != safe_menu_url or current_menu_text != MENU_BUTTON_TEXT:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text=MENU_BUTTON_TEXT,
                web_app=WebAppInfo(url=safe_menu_url),
            )
        )
        # Telegram's default menu is eventually consistent across Bot API
        # replicas. Re-read briefly, but keep the final check fail-closed.
        for delay_s in (0.0, 0.25, 0.5, 1.0, 2.0):
            if delay_s:
                await asyncio.sleep(delay_s)
            menu = await bot.get_chat_menu_button()
            observed_url = getattr(getattr(menu, "web_app", None), "url", "") or ""
            observed_text = getattr(menu, "text", "") or ""
            if observed_url == safe_menu_url and observed_text == MENU_BUTTON_TEXT:
                break

    webhook = await bot.get_webhook_info()
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
    "provider_configuration_status",
    "public_commands",
    "resolve_menu_url",
]
