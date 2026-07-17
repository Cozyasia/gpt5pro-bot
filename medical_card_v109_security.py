# -*- coding: utf-8 -*-
"""Security hardening for Medical Card v109.

Provides a stable per-service encryption key on the persistent disk when an
explicit MEDICAL_CARD_ENCRYPTION_KEY is not configured, keeps irreversible
data deletion available after a subscription expires, and prevents the older
v108 background worker from masking the active v109 release version.
"""
from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from typing import Any

_INSTALLED = False


def _install_version_guard(card: Any) -> None:
    """Wait until v109 patches main, then make the v108 publisher emit v109.

    medical_v108_patch intentionally republishes its VERSION for several minutes
    after startup. Changing that module's VERSION only after the v109 patch flag
    appears preserves the v108 prerequisite check and removes the release race.
    """
    def worker() -> None:
        for _ in range(7200):
            for module_name in ("__main__", "main"):
                mod = sys.modules.get(module_name)
                if mod is None or not getattr(mod, card.PATCH_FLAG, False):
                    continue
                with contextlib.suppress(Exception):
                    import medical_v108_patch as medical_v108
                    medical_v108.VERSION = card.VERSION
                with contextlib.suppress(Exception):
                    mod.PATCH_VERSION = card.VERSION
                    mod.MEDICAL_CARD_VERSION = card.VERSION
                return
            time.sleep(0.05)

    threading.Thread(
        target=worker,
        daemon=True,
        name="medical-card-v109-version-guard",
    ).start()


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    try:
        import medical_card_v109_patch as card
        from cryptography.fernet import Fernet
    except Exception:
        return False

    def stable_fernet(mod: Any):
        raw = (os.environ.get("MEDICAL_CARD_ENCRYPTION_KEY") or "").strip()
        if raw:
            try:
                return Fernet(raw.encode("ascii"))
            except Exception:
                pass

        root = card._storage_root(mod)
        key_path = root / ".medical_card_fernet.key"
        try:
            if key_path.exists():
                key = key_path.read_bytes().strip()
                return Fernet(key)

            key = Fernet.generate_key()
            tmp_path = key_path.with_suffix(".tmp")
            tmp_path.write_bytes(key)
            with contextlib.suppress(Exception):
                os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, key_path)
            with contextlib.suppress(Exception):
                os.chmod(key_path, 0o600)
            return Fernet(key)
        except Exception:
            return card._original_fernet(mod)

    if not hasattr(card, "_original_fernet"):
        card._original_fernet = card._fernet
    card._fernet = stable_fernet

    original_upgrade_kb = card._upgrade_kb

    def upgrade_kb(mod: Any):
        try:
            return card._kb(mod, [
                [("🚀 PRO", "plan:pro"), ("👑 ULTIMATE", "plan:ultimate")],
                [("🗑 Удалить сохранённые данные", "medcard:privacy_delete_all_ask")],
                [("⬅️ Назад в медицину", "medcard:back_med")],
            ])
        except Exception:
            return original_upgrade_kb(mod)

    card._upgrade_kb = upgrade_kb
    original_callback = card._handle_medcard_callback

    async def callback(mod: Any, update: Any, context: Any, data: str) -> bool:
        action = data[len("medcard:"):] if data.startswith("medcard:") else ""
        if action not in {"privacy_delete_all_ask", "privacy_delete_all_yes"}:
            return await original_callback(mod, update, context, data)

        q = update.callback_query
        with contextlib.suppress(Exception):
            await q.answer()
        uid = int(update.effective_user.id)

        if action == "privacy_delete_all_ask":
            if not card._has_consent(mod, uid):
                await q.message.edit_text(
                    "Сохранённая медицинская карта не найдена.",
                    reply_markup=card._upgrade_kb(mod),
                )
            else:
                await q.message.edit_text(
                    "⚠️ Удалить всю медицинскую карту: все профили, документы, оригиналы, "
                    "показатели и назначения? Восстановить данные будет невозможно.",
                    reply_markup=card._kb(mod, [
                        [("🗑 Да, удалить всё", "medcard:privacy_delete_all_yes")],
                        [("⬅️ Отмена", "medcard:open")],
                    ]),
                )
            return True

        card._delete_all(mod, uid)
        context.user_data.pop("medcard_pending", None)
        await q.message.edit_text(
            "✅ Медицинская карта и сохранённые данные удалены. Согласие отозвано.",
            reply_markup=mod.medicine_kb(),
        )
        return True

    card._handle_medcard_callback = callback
    _install_version_guard(card)
    _INSTALLED = True
    return True
