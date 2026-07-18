# -*- coding: utf-8 -*-
"""Medical-card conversion UX for users without persistent card access.

After a successful medical analysis:
* PRO / ULTIMATE and unlimited users keep the normal save-to-card workflow;
* FREE / START users receive one contextual upgrade offer only after the full answer;
* large temporary card payloads are immediately released for ineligible users;
* duplicate webhook delivery cannot show the same offer repeatedly.
"""
from __future__ import annotations

import contextlib
import hashlib
import sys
import threading
import time
from typing import Any

VERSION = "v117-medical-card-contextual-upsell-2026-07-18"
_PATCH_FLAG = "_MEDICAL_CARD_V117_UPSELL_PATCHED"
_DEDUPE_TTL_SECONDS = 15 * 60

UPSELL_TEXT = (
    "📁 Сохраните результаты в персональной медицинской карте\n\n"
    "В тарифах PRO и ULTIMATE доступна медицинская карта, в которой можно:\n\n"
    "• хранить оригиналы анализов, заключений, УЗИ, МРТ и КТ;\n"
    "• сохранять распознанные данные и подробные разборы;\n"
    "• отслеживать показатели и изменения по датам;\n"
    "• вести отдельные профили для себя и близких;\n"
    "• находить документы через поиск;\n"
    "• формировать медицинскую сводку в PDF для врача.\n\n"
    "Ваш текущий разбор останется в этом чате, но постоянное хранение и история "
    "доступны только в PRO и ULTIMATE. После подключения тарифа новые исследования "
    "можно сохранять в карту сразу или автоматически."
)


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _upsell_kb(card: Any, mod: Any):
    return card._kb(
        mod,
        [
            [("🚀 Подключить PRO", "plan:pro"), ("💎 Подключить ULTIMATE", "plan:ultimate")],
            [("ℹ️ Сравнить тарифы", "plan:root")],
            [("⬅️ Вернуться в Медицину", "medcard:back_med")],
        ],
    )


def _pending_signature(pending: Any) -> str:
    if not isinstance(pending, dict):
        return ""
    digest = hashlib.sha256()
    for key in ("track", "source_type", "filename", "mime_type"):
        digest.update(str(pending.get(key) or "").encode("utf-8", errors="ignore"))
        digest.update(b"\0")
    raw = pending.get("file_bytes") or b""
    if isinstance(raw, bytearray):
        raw = bytes(raw)
    if isinstance(raw, bytes):
        digest.update(str(len(raw)).encode("ascii"))
        digest.update(raw[:65536])
    source_text = str(pending.get("source_text") or "")
    analysis = str(pending.get("analysis") or "")
    digest.update(str(len(source_text)).encode("ascii"))
    digest.update(source_text[:4096].encode("utf-8", errors="ignore"))
    digest.update(str(len(analysis)).encode("ascii"))
    digest.update(analysis[:4096].encode("utf-8", errors="ignore"))
    return digest.hexdigest()[:24]


def _already_offered(context: Any, signature: str) -> bool:
    if not signature:
        return False
    value = context.user_data.get("medcard_upsell_last") or {}
    if not isinstance(value, dict):
        return False
    return (
        value.get("signature") == signature
        and time.time() - float(value.get("timestamp") or 0) < _DEDUPE_TTL_SECONDS
    )


def _mark_offered(context: Any, signature: str) -> None:
    context.user_data["medcard_upsell_last"] = {
        "signature": signature,
        "timestamp": time.time(),
    }


def patch_runtime(mod: Any) -> bool:
    if getattr(mod, _PATCH_FLAG, False):
        mod.PATCH_VERSION = VERSION
        mod.MEDICAL_CARD_VERSION = VERSION
        return True

    try:
        import medical_card_v109_patch as card
    except Exception:
        return False

    original_offer = getattr(card, "_offer_save", None)
    if not callable(original_offer):
        return False

    if not getattr(original_offer, "_medical_v117_wrapped", False):
        async def offer_save(runtime_mod: Any, update: Any, context: Any) -> None:
            user = getattr(update, "effective_user", None)
            message = getattr(update, "effective_message", None)
            if user is None or message is None:
                return

            if card._eligible(runtime_mod, user):
                await original_offer(runtime_mod, update, context)
                return

            pending = context.user_data.pop("medcard_pending", None) or {}
            # No persistent-card entitlement: do not retain the original file,
            # extracted text or model answer in a temporary save object.
            context.user_data.pop("medcard_source_capture", None)

            signature = _pending_signature(pending)
            if _already_offered(context, signature):
                return
            _mark_offered(context, signature)

            await message.reply_text(
                UPSELL_TEXT,
                reply_markup=_upsell_kb(card, runtime_mod),
                disable_web_page_preview=True,
            )

        offer_save._medical_v117_wrapped = True
        offer_save._medical_v117_original = original_offer
        card._offer_save = offer_save

    # Reuse the same complete upgrade navigation when an ineligible user opens
    # the Medical Card manually from the Medicine menu.
    def upgrade_kb(runtime_mod: Any):
        return _upsell_kb(card, runtime_mod)

    card._upgrade_kb = upgrade_kb
    card.VERSION = VERSION
    mod.MEDICAL_CARD_VERSION = VERSION
    mod.PATCH_VERSION = VERSION
    setattr(mod, _PATCH_FLAG, True)
    return True


def install_async() -> None:
    def worker() -> None:
        patched_mod = None
        for _ in range(15000):
            mod = _runtime_module()
            if mod is not None:
                with contextlib.suppress(Exception):
                    if patch_runtime(mod):
                        patched_mod = mod
                        break
            time.sleep(0.02)

        # v116 keeps its release marker alive for several minutes. Keep the newer
        # release visible for longer so /version reliably confirms deployment.
        if patched_mod is not None:
            for _ in range(2100):
                with contextlib.suppress(Exception):
                    patched_mod.PATCH_VERSION = VERSION
                    patched_mod.MEDICAL_CARD_VERSION = VERSION
                time.sleep(0.2)

    threading.Thread(
        target=worker,
        daemon=True,
        name="medical-card-v117-upsell",
    ).start()


__all__ = ["VERSION", "UPSELL_TEXT", "patch_runtime", "install_async"]
