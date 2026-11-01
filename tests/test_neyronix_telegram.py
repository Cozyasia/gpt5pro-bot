import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def test_neyronix_brand_and_public_commands():
    from neyrobot_prod.neyronix_telegram import (
        BRAND_NAME,
        DEFAULT_BOT_USERNAME,
        public_commands,
    )

    assert BRAND_NAME == "NEYRONIX"
    assert DEFAULT_BOT_USERNAME == "neyronixbot"
    commands = dict(public_commands())
    assert commands["start"] == "Запустить NEYRONIX"
    assert commands["menu"] == "Открыть главное меню"
    assert commands["help"] == "Помощь"
    assert "diag_prod" not in commands


def test_menu_url_is_https_and_does_not_fall_back_to_checkout_page():
    from neyrobot_prod.neyronix_telegram import resolve_menu_url

    assert resolve_menu_url("https://neyro-studio-ui.onrender.com/?v=2") == (
        "https://neyro-studio-ui.onrender.com/?v=2"
    )
    assert resolve_menu_url("") == "https://neyro-studio-ui.onrender.com/"
    for invalid in (
        "http://neyro-studio-ui.onrender.com/",
        "javascript:alert(1)",
        "https://example.com/webapp/checkout",
    ):
        try:
            resolve_menu_url(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe menu URL accepted: {invalid}")


class FakeBot:
    def __init__(self):
        self.calls = []
        self.menu = None

    async def set_my_name(self, **kwargs):
        self.calls.append(("set_my_name", kwargs))

    async def set_my_short_description(self, **kwargs):
        self.calls.append(("set_my_short_description", kwargs))

    async def set_my_description(self, **kwargs):
        self.calls.append(("set_my_description", kwargs))

    async def set_my_commands(self, commands):
        self.calls.append(("set_my_commands", commands))

    async def set_chat_menu_button(self, **kwargs):
        self.menu = kwargs["menu_button"]
        self.calls.append(("set_chat_menu_button", kwargs))

    async def get_me(self):
        return SimpleNamespace(id=42, username="neyronixbot", first_name="NEYRONIX")

    async def get_webhook_info(self):
        return SimpleNamespace(
            url="https://neyronix-bot-staging.onrender.com/tg",
            pending_update_count=0,
            last_error_date=None,
            last_error_message=None,
        )

    async def get_chat_menu_button(self):
        return self.menu


def test_configure_shell_sets_profile_commands_menu_and_returns_sanitized_snapshot():
    from neyrobot_prod.neyronix_telegram import configure_shell

    bot = FakeBot()
    snapshot = asyncio.run(
        configure_shell(
            bot,
            expected_username="neyronixbot",
            menu_url="https://neyro-studio-ui.onrender.com/",
        )
    )

    assert snapshot == {
        "bot_id": 42,
        "username": "neyronixbot",
        "first_name": "NEYRONIX",
        "webhook_url": "https://neyronix-bot-staging.onrender.com/tg",
        "pending_updates": 0,
        "last_webhook_error": None,
        "menu_url": "https://neyro-studio-ui.onrender.com/",
        "commands": [name for name, _ in configure_shell.public_commands()],
    }
    assert any(name == "set_my_commands" for name, _ in bot.calls)
    assert all(
        "token" not in json.dumps(data, default=str).lower()
        for _, data in bot.calls
    )


def test_main_patch_applies_and_wires_fast_start_menu_and_shell(tmp_path):
    patch_path = ROOT / "ops" / "main_neyronix.patch"
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert patch_path.is_file()
    assert "main_neyronix.patch" in dockerfile

    target = tmp_path / "repo"
    target.mkdir()
    shutil.copy2(ROOT / "main.py", target / "main.py")
    result = subprocess.run(
        ["patch", "--batch", "--forward", "-p1", "-i", str(patch_path)],
        cwd=target,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    patched = (target / "main.py").read_text(encoding="utf-8")
    assert 'CommandHandler("menu",         cmd_menu)' in patched
    assert "NEYRONIX_MODE" in patched
    assert "configure_shell" in patched
    assert "NEYRONIX_TELEGRAM_STATUS" in patched
    assert "if NEYRONIX_MODE:" in patched
    assert "reply_text(" in patched
