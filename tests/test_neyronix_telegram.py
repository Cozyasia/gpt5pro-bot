import asyncio
import ast
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


def test_provider_configuration_status_is_boolean_only_and_alias_aware():
    from neyrobot_prod.neyronix_telegram import provider_configuration_status

    status = provider_configuration_status({
        "OPENAI_API_KEY": "openai-secret",
        "COMETAPI_KEY": "comet-secret",
        "SEEDANCE_ENABLED": "1",
        "HEYGEN_API_KEY": "heygen-secret",
        "HEYGEN_AVATAR_ID": "avatar",
        "HEYGEN_VOICE_ID": "voice",
        "PROVIDER_TOKEN_YOOKASSA": "payment-secret",
    })
    assert status["openai"] is True
    assert status["comet"] is True
    assert status["kling"] is True
    assert status["seedance"] is True
    assert status["heygen"] is True
    assert status["yookassa"] is True
    assert status["cryptobot"] is False
    assert "secret" not in json.dumps(status)


class FakeBot:
    def __init__(self):
        self.calls = []
        self.menu = None
        self.me = SimpleNamespace(id=42, username="neyronixbot", first_name="Legacy")
        self.short_description = "Legacy short"
        self.description = "Legacy description"
        self.commands = []

    async def set_my_name(self, **kwargs):
        self.me.first_name = kwargs["name"]
        self.calls.append(("set_my_name", kwargs))

    async def set_my_short_description(self, **kwargs):
        self.short_description = kwargs["short_description"]
        self.calls.append(("set_my_short_description", kwargs))

    async def set_my_description(self, **kwargs):
        self.description = kwargs["description"]
        self.calls.append(("set_my_description", kwargs))

    async def set_my_commands(self, commands):
        self.commands = commands
        self.calls.append(("set_my_commands", commands))

    async def set_chat_menu_button(self, **kwargs):
        self.menu = kwargs["menu_button"]
        self.calls.append(("set_chat_menu_button", kwargs))

    async def get_me(self):
        return self.me

    async def get_my_short_description(self):
        return SimpleNamespace(short_description=self.short_description)

    async def get_my_description(self):
        return SimpleNamespace(description=self.description)

    async def get_my_commands(self):
        return self.commands

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


def test_configure_shell_is_idempotent_and_does_not_repeat_profile_mutations():
    from neyrobot_prod.neyronix_telegram import configure_shell

    bot = FakeBot()
    asyncio.run(configure_shell(bot, menu_url="https://neyro-studio-ui.onrender.com/"))
    assert any(name.startswith("set_") for name, _ in bot.calls)

    bot.calls.clear()
    snapshot = asyncio.run(
        configure_shell(bot, menu_url="https://neyro-studio-ui.onrender.com/")
    )
    assert snapshot["first_name"] == "NEYRONIX"
    assert snapshot["menu_url"] == "https://neyro-studio-ui.onrender.com/"
    assert not [name for name, _ in bot.calls if name.startswith("set_")]


def test_configure_shell_waits_for_eventually_consistent_menu_readback():
    from neyrobot_prod.neyronix_telegram import configure_shell

    class EventuallyConsistentBot(FakeBot):
        def __init__(self):
            super().__init__()
            self.stale_reads = 0
            self.pending_menu = None

        async def set_chat_menu_button(self, **kwargs):
            self.pending_menu = kwargs["menu_button"]
            self.stale_reads = 2
            self.calls.append(("set_chat_menu_button", kwargs))

        async def get_chat_menu_button(self):
            if self.pending_menu is not None and self.stale_reads:
                self.stale_reads -= 1
                return self.menu
            if self.pending_menu is not None:
                self.menu = self.pending_menu
                self.pending_menu = None
            return self.menu

    bot = EventuallyConsistentBot()
    snapshot = asyncio.run(
        configure_shell(bot, menu_url="https://neyro-studio-ui.onrender.com/")
    )
    assert snapshot["menu_url"] == "https://neyro-studio-ui.onrender.com/"
    assert [name for name, _ in bot.calls].count("set_chat_menu_button") == 1


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
    ast.parse(patched)
    assert 'CommandHandler("menu",         cmd_menu)' in patched
    assert "NEYRONIX_MODE" in patched
    assert "configure_shell" in patched
    assert "NEYRONIX_TELEGRAM_STATUS" in patched
    assert "NEYRONIX_PROVIDER_CONFIGURATION" in patched
    assert "from neyrobot_prod.provider_config import resolve_text_provider_config" in patched
    assert 'os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")' in patched
    assert 'os.environ.get("OPENAI_MODEL", "openai/gpt-4o-mini")' not in patched
    assert "if NEYRONIX_MODE:" in patched
    assert "reply_text(" in patched
    assert "_defer_restart_recovery_until_running" in patched
    assert "if not app.running:" in patched
    assert 'name="neyronix-restart-recovery"' in patched
    post_init = patched[
        patched.index("async def _post_init_bot_profile"):
        patched.index("\n\n# ───────── Регистрация хендлеров", patched.index("async def _post_init_bot_profile"))
    ]
    neyronix_branch = post_init[:post_init.index("    try:\n        from property_video_execution")]
    assert "asyncio.create_task(" in neyronix_branch
    assert "app.create_task(" in neyronix_branch
    assert "        return\n" in neyronix_branch


def test_cryptobot_secret_patch_applies_and_docker_runs_it(tmp_path):
    patch_path = ROOT / "ops" / "main_cryptobot_secret.patch"
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert patch_path.is_file()
    assert "main_cryptobot_secret.patch" in dockerfile

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
    ast.parse(patched)
    assert '"/etc/secrets/cryptobot.env"' in patched
    assert patched.count('CRYPTO_PAY_API_TOKEN = _crypto_secret_value("CRYPTO_PAY_API_TOKEN")') == 2
    assert 'CRYPTO_PAY_API_TOKEN = os.environ.get("CRYPTO_PAY_API_TOKEN", "").strip()' not in patched
