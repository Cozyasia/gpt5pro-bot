from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from .admin import is_admin
from .catalog.runtime import runtime_catalog
from .config import StarSelfieConfig


def _yes(value: bool) -> str:
    return "✅" if value else "❌"


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="diag_", dir=path, delete=True):
            pass
        return True
    except OSError:
        return False


def build_report(config: StarSelfieConfig, *, boot_error: str = "") -> str:
    catalog = runtime_catalog(config)
    characters = catalog.load()
    ready = [
        item
        for item in characters
        if config.required_character_refs <= len(item.reference_paths) <= config.max_character_refs
        and all(path.is_file() for path in item.reference_paths)
    ]
    active_ready = [item for item in ready if item.active]
    missing_refs = sum(
        1
        for item in characters
        for path in item.reference_paths
        if not path.is_file()
    )
    admin_configured = bool((os.getenv("STAR_SELFIE_ADMIN_IDS") or os.getenv("OWNER_ID") or "").strip())

    lines = [
        "🩺 Star Selfie — диагностика",
        "",
        f"Feature flag: {_yes(config.enabled)}",
        f"Gemini API key: {_yes(bool(config.gemini_api_key))}",
        f"Face Swap URL: {_yes(bool(config.face_swap_url))}",
        f"Face Swap API key: {_yes(bool(config.face_swap_api_key))}",
        f"Admin ID настроен: {_yes(admin_configured)}",
        f"Persistent storage доступно: {_yes(_writable(config.persistent_root))}",
        f"Каталог: {catalog.catalog_path}",
        f"Героев всего: {len(characters)}",
        f"Готовы по референсам: {len(ready)}",
        f"Активны и готовы: {len(active_ready)}",
        f"Отсутствующих файлов: {missing_refs}",
        f"Boot error: {boot_error or 'нет'}",
    ]

    blockers: list[str] = []
    if not config.enabled:
        blockers.append("STAR_SELFIE_ENABLED выключен")
    if not config.gemini_api_key:
        blockers.append("нет GEMINI_API_KEY")
    if not config.face_swap_url:
        blockers.append("нет STAR_SELFIE_FACE_SWAP_URL")
    if not config.face_swap_api_key:
        blockers.append("нет STAR_SELFIE_FACE_SWAP_API_KEY")
    if not admin_configured:
        blockers.append("не настроен OWNER_ID/STAR_SELFIE_ADMIN_IDS")
    if not active_ready:
        blockers.append("нет активного героя с 3–6 референсами")
    if boot_error:
        blockers.append("ошибка bootstrap")

    lines.extend(["", "Итог: " + ("✅ готово к smoke test" if not blockers else "⚠️ есть блокеры")])
    lines.extend(f"• {item}" for item in blockers)
    return "\n".join(lines)


async def command(update: Any, context: Any, config: StarSelfieConfig) -> None:
    if not is_admin(update.effective_user):
        await update.effective_message.reply_text("Команда доступна владельцу бота.")
        return
    boot_error = str(getattr(context.application, "bot_data", {}).get("star_selfie_boot_error", "") or "")
    await update.effective_message.reply_text(build_report(config, boot_error=boot_error))


def register_handler(app: Any, config: StarSelfieConfig, *, group: int = -99) -> bool:
    if not config.enabled or getattr(app, "_star_selfie_diag_handler", False):
        return False
    from telegram.ext import CommandHandler

    async def _command(update: Any, context: Any) -> None:
        await command(update, context, config)

    app.add_handler(CommandHandler("star_diag", _command), group=group)
    setattr(app, "_star_selfie_diag_handler", True)
    return True


__all__ = ["build_report", "command", "register_handler"]