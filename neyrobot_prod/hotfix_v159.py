# -*- coding: utf-8 -*-
"""Neyro-Bot v159 production hotfix.

This release fixes three user-visible regressions without replacing main.py:
1. the current Celebrity Selfie wizard always owns its entry/photo flow;
2. credit packs use one server-side catalog and offer every enabled YooKassa
   method through direct payments;
3. the structured medical engine and encrypted Medical Card hand-off are
   re-applied after all legacy runtime patch workers settle.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import threading
import time
from typing import Any

VERSION = "v159-payments-selfie-medical-integrity-2026-07-24"
_GROUP = -50_000
_BUILDER_FLAG = "_neyrobot_v159_builder"
_HANDLER_FLAG = "_neyrobot_v159_handlers"

# Canonical catalog shared by Telegram, Mini App and server-side validation.
# These assignments intentionally override stale Render variables that produced
# 100/300/700 labels while the payment backend expected 1000/3000/7000.
os.environ["PRICING_CANONICAL_COSTS"] = "1"
os.environ["PRICING_LOCK_1_CREDIT_1_RUB"] = "1"
os.environ["CREDIT_PACK_SMALL_CREDITS"] = "1000"
os.environ["CREDIT_PACK_MID_CREDITS"] = "3000"
os.environ["CREDIT_PACK_BIG_CREDITS"] = "7000"
os.environ["CREDIT_PACK_SMALL_RUB"] = "990"
os.environ["CREDIT_PACK_MID_RUB"] = "2790"
os.environ["CREDIT_PACK_BIG_RUB"] = "6290"

log = logging.getLogger("gpt-bot.hotfix-v159")
_INSTALL_LOCK = threading.RLock()
_RELEASE_ERROR = ""
_RELEASE_READY = False
_RUNTIME_STARTED = False
_BUILDER_HOOKED = False

_DEFAULT_PACKAGES: dict[int, int] = {1000: 990, 3000: 2790, 7000: 6290}


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _valid_owner_jpeg(raw: bytes) -> bool:
    """Accept compact but complete owner JPEGs; reject truncated assets."""
    return bool(
        len(raw or b"") >= 4_000
        and raw.startswith(b"\xff\xd8\xff")
        and raw.endswith(b"\xff\xd9")
    )


def _install_celebrity_release() -> bool:
    """Install the exact catalog wizard even if an optional reference fails."""
    global _RELEASE_ERROR, _RELEASE_READY
    with _INSTALL_LOCK:
        try:
            import celebrity_selfie_v124 as flow
            flow.install_builder_hook()

            import celebrity_selfie_v158 as release
            # v158 originally required >15 KB although the three repository JPEGs
            # are valid compact images. Patch validation before install(), not after.
            release._valid_jpeg = _valid_owner_jpeg
            release.install()
            release.install_builder_hook()
            paths = list(release._fixed_reference_paths() or [])
            if len(paths) != 3:
                raise RuntimeError(f"Roman reference pack count={len(paths)}")

            release.VERSION = VERSION
            with contextlib.suppress(Exception):
                release.previous.VERSION = VERSION
                release.renderer.VERSION = VERSION
                release.v139.VERSION = VERSION
            _RELEASE_READY = True
            _RELEASE_ERROR = ""
            return True
        except Exception as exc:
            # The v124 priority handlers are still installed above, so the user
            # receives a working catalog/photo flow instead of the generic router.
            _RELEASE_READY = False
            _RELEASE_ERROR = f"{type(exc).__name__}: {exc}"[:700]
            log.exception("v159 Celebrity Selfie release install failed")
            return False


def _packages(mod: Any) -> dict[int, int]:
    raw = getattr(mod, "CREDIT_PACKAGES_RUB", None)
    result: dict[int, int] = {}
    if isinstance(raw, dict):
        for credits, rub in raw.items():
            with contextlib.suppress(Exception):
                c, r = int(credits), int(rub)
                if c > 0 and r > 0:
                    result[c] = r
    # A stale or partial environment must never create an unbillable menu.
    return result if set(_DEFAULT_PACKAGES).issubset(result) else dict(_DEFAULT_PACKAGES)


def _resolve_pack(mod: Any, requested_credits: int = 0, requested_rub: int = 0) -> tuple[int, int] | None:
    """Resolve an exact server-side package and reject mixed/tampered values."""
    packs = _packages(mod)
    requested_credits = int(requested_credits or 0)
    requested_rub = int(requested_rub or 0)
    by_credit = (requested_credits, packs.get(requested_credits)) if requested_credits in packs else None
    by_rub = next(((c, r) for c, r in packs.items() if r == requested_rub), None) if requested_rub else None
    if requested_credits and requested_rub:
        return by_credit if by_credit and by_credit == by_rub else None
    return by_credit or by_rub


def _method_rows(mod: Any, credits: int):
    from telegram import InlineKeyboardButton

    rows = []
    if bool(getattr(mod, "YOO_SBP_ENABLED", True)):
        rows.append([InlineKeyboardButton("⚡ СБП / QR", callback_data=f"credit:v159:pay:yoo_sbp:{credits}")])
    app_row = []
    if bool(getattr(mod, "YOO_SBERPAY_ENABLED", True)):
        app_row.append(InlineKeyboardButton("🟢 SberPay", callback_data=f"credit:v159:pay:yoo_sberpay:{credits}"))
    if bool(getattr(mod, "YOO_TPAY_ENABLED", True)):
        app_row.append(InlineKeyboardButton("🟡 T-Pay", callback_data=f"credit:v159:pay:yoo_tpay:{credits}"))
    if app_row:
        rows.append(app_row)
    app_row = []
    if bool(getattr(mod, "YOO_MIRPAY_ENABLED", True)):
        app_row.append(InlineKeyboardButton("🔵 Mir Pay", callback_data=f"credit:v159:pay:yoo_mirpay:{credits}"))
    if bool(getattr(mod, "YOO_CARD_ENABLED", True)):
        app_row.append(InlineKeyboardButton("💳 Банковская карта", callback_data=f"credit:v159:pay:yoo_card:{credits}"))
    if app_row:
        rows.append(app_row)
    rows.append([InlineKeyboardButton("💠 Все способы ЮKassa", callback_data=f"credit:v159:pay:yoo_all:{credits}")])
    if getattr(mod, "CRYPTO_PAY_API_TOKEN", ""):
        rows.append([InlineKeyboardButton("💎 CryptoBot / USDT", callback_data=f"credit:v159:crypto:{credits}")])
    rows.append([InlineKeyboardButton("⬅️ Другой пакет", callback_data="topup")])
    return rows


def _package_menu(mod: Any):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    packs = sorted(_packages(mod).items())
    rows = []
    row = []
    for credits, rub in packs:
        row.append(InlineKeyboardButton(f"{credits:,} кр. • {rub:,} ₽".replace(",", " "), callback_data=f"credit:v159:pack:{credits}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


async def _send_topup_menu(mod: Any, update: Any, context: Any) -> None:
    await update.effective_message.reply_text(
        "🪙 Кредиты используются для видео, музыки, AI-фото, FaceSwap, "
        "говорящего аватара и премиум-рендеров.\n\n"
        "Номинал: 1 кредит = 1 ₽; в пакетах действует скидка. "
        "Сначала выберите пакет, затем способ оплаты ЮKassa:",
        reply_markup=_package_menu(mod),
    )


async def _show_credit_methods(mod: Any, update: Any, credits: int) -> None:
    from telegram import InlineKeyboardMarkup

    resolved = _resolve_pack(mod, credits, 0)
    if not resolved:
        await update.effective_message.reply_text("Пакет устарел. Откройте меню пополнения заново.", reply_markup=_package_menu(mod))
        return
    credits, rub = resolved
    await update.effective_message.reply_text(
        f"🪙 Пакет: {credits:,} кредитов за {rub:,} ₽.\n"
        "Выберите способ оплаты:".replace(",", " "),
        reply_markup=InlineKeyboardMarkup(_method_rows(mod, credits)),
    )


async def _start_yoo_credit(mod: Any, update: Any, context: Any, method: str, credits: int) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    resolved = _resolve_pack(mod, credits, 0)
    if not resolved:
        await update.effective_message.reply_text("Пакет не найден. Откройте меню пополнения заново.")
        return
    credits, rub = resolved
    methods = getattr(mod, "YOO_DIRECT_METHODS", {}) or {}
    if method not in methods:
        await update.effective_message.reply_text("Этот способ оплаты сейчас недоступен. Выберите другой.")
        await _show_credit_methods(mod, update, credits)
        return
    configured = getattr(mod, "_yoo_direct_configured", None)
    if not callable(configured) or not configured():
        await update.effective_message.reply_text(
            "⚠️ Прямая оплата ЮKassa не настроена: проверьте YK_ID/YK_KEY в Render Secret File yookassa.env."
        )
        return

    creator = getattr(mod, "_yoo_create_credit_payment", None)
    if not callable(creator):
        await update.effective_message.reply_text("Модуль оплаты ещё запускается. Повторите через несколько секунд.")
        return

    try:
        payment = await creator(int(update.effective_user.id), credits, rub, method)
        payment_id = str((payment or {}).get("id") or "")
        confirmation = (payment or {}).get("confirmation") or {}
        pay_url = str(
            confirmation.get("confirmation_url")
            or confirmation.get("confirmation_data")
            or confirmation.get("external_url")
            or ""
        )
        if not payment_id or not pay_url:
            raise RuntimeError("YooKassa did not return payment id/confirmation URL")
        label = str((methods.get(method) or {}).get("label") or "ЮKassa")
        msg = await update.effective_message.reply_text(
            f"🪙 {credits:,} кредитов за {rub:,} ₽.\n"
            f"Способ: {label}. После оплаты кредиты начислятся автоматически.".replace(",", " "),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{label} — перейти к оплате", url=pay_url)],
                [InlineKeyboardButton("Другой способ", callback_data=f"credit:v159:pack:{credits}")],
            ]),
        )
        kv_set = getattr(mod, "kv_set", None)
        if callable(kv_set):
            with contextlib.suppress(Exception):
                kv_set(
                    f"yoo:credit_pending:{payment_id}",
                    json.dumps(
                        {"user_id": int(update.effective_user.id), "credits": credits, "amount_rub": rub, "method": method},
                        ensure_ascii=False,
                    ),
                )
        poll = getattr(mod, "_poll_yoo_credit_payment", None)
        if callable(poll):
            context.application.create_task(
                poll(context, msg.chat.id, msg.message_id, int(update.effective_user.id), payment_id, credits, rub)
            )
    except Exception as exc:
        logger = getattr(mod, "log", log)
        with contextlib.suppress(Exception):
            logger.exception("v159 YooKassa credit create failed method=%s credits=%s: %r", method, credits, exc)
        await update.effective_message.reply_text(
            "Не удалось создать ссылку этим способом. Повторите или выберите «Все способы ЮKassa».",
            reply_markup=InlineKeyboardMarkup(_method_rows(mod, credits)),
        )


async def _start_crypto_credit(mod: Any, update: Any, context: Any, credits: int) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    resolved = _resolve_pack(mod, credits, 0)
    if not resolved:
        await update.effective_message.reply_text("Пакет не найден.")
        return
    credits, _rub = resolved
    if not getattr(mod, "CRYPTO_PAY_API_TOKEN", ""):
        await update.effective_message.reply_text("CryptoBot сейчас не настроен. Выберите ЮKassa.")
        return
    usd = float(mod._credits_to_usd(credits))
    inv_id, pay_url, usd_amount, asset = await mod._crypto_create_invoice(usd, asset="USDT", description=f"Neyro-Bot {credits} credits")
    if not inv_id or not pay_url:
        await update.effective_message.reply_text("Не удалось создать счёт CryptoBot. Выберите ЮKassa или повторите позже.")
        return
    msg = await update.effective_message.reply_text(
        f"Оплатите через CryptoBot: {usd_amount:.2f} {asset} → {credits:,} кредитов.".replace(",", " "),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 CryptoBot", url=pay_url)],
            [InlineKeyboardButton("🔎 Проверить", callback_data=f"crypto:check:{inv_id}")],
        ]),
    )
    poll = getattr(mod, "_poll_crypto_invoice", None)
    if callable(poll):
        context.application.create_task(poll(context, msg.chat.id, msg.message_id, int(update.effective_user.id), inv_id, usd_amount))


async def _credit_callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    q = update.callback_query
    data = str(getattr(q, "data", "") or "")
    mod = _runtime_module()
    if mod is None:
        with contextlib.suppress(Exception):
            await q.answer("Бот ещё запускается", show_alert=True)
        raise ApplicationHandlerStop
    with contextlib.suppress(Exception):
        await q.answer()

    if data.startswith("topup:rub:"):
        with contextlib.suppress(Exception):
            rub = int(data.rsplit(":", 1)[-1])
            resolved = _resolve_pack(mod, 0, rub)
            if resolved:
                await _show_credit_methods(mod, update, resolved[0])
                raise ApplicationHandlerStop
        await update.effective_message.reply_text(
            "Этот старый пакет больше не используется. Выберите актуальный пакет:",
            reply_markup=_package_menu(mod),
        )
        raise ApplicationHandlerStop

    parts = data.split(":")
    try:
        action = parts[2]
        if action == "pack":
            await _show_credit_methods(mod, update, int(parts[3]))
        elif action == "pay":
            await _start_yoo_credit(mod, update, context, parts[3], int(parts[4]))
        elif action == "crypto":
            await _start_crypto_credit(mod, update, context, int(parts[3]))
        else:
            await _send_topup_menu(mod, update, context)
    except Exception as exc:
        log.exception("v159 credit callback failed data=%s: %r", data, exc)
        await update.effective_message.reply_text("Не удалось обработать кнопку. Откройте меню пополнения заново.")
    raise ApplicationHandlerStop


async def _selfie_callback(update: Any, context: Any) -> None:
    """Own old and new AI-selfie buttons before the generic photo router."""
    from telegram.ext import ApplicationHandlerStop
    import celebrity_selfie_v124 as flow

    data = str(getattr(update.callback_query, "data", "") or "")
    if data.startswith("celeb:"):
        await flow._callback(update, context)
        raise ApplicationHandlerStop

    with contextlib.suppress(Exception):
        await update.callback_query.answer()
    try:
        if data.endswith("_upload"):
            session = flow._start_session(context)
            session["state"] = "await_user_photo"
            await flow._reply(
                update,
                "📤 Пришлите своё селфи обычной фотографией Telegram или файлом JPG/PNG/WEBP. "
                "После загрузки автоматически откроется каталог знаменитостей.",
                flow.base._kb([[("❌ Отмена", "celeb:cancel")]]),
            )
        elif data.endswith("_last"):
            flow._start_session(context)
            raw = flow._cached_photo(update)
            if raw:
                await flow._accept_user_photo(update, context, raw)
            else:
                session = flow.base._session(context)
                session["state"] = "await_user_photo"
                await flow._reply(update, "Последнее фото не найдено. Пришлите новое селфи.", flow.base._kb([[("❌ Отмена", "celeb:cancel")]]))
        else:
            # Exact entry and all legacy preset/custom buttons now enter the same
            # authoritative catalog wizard. Celebrity and scene are selected there.
            await flow._open_entry(update, context)
    except Exception as exc:
        log.exception("v159 selfie entry failed data=%s: %r", data, exc)
        session = flow._start_session(context)
        session["state"] = "await_user_photo"
        await flow._reply(update, "Пришлите своё селфи. После загрузки откроется выбор знаменитости.")
    raise ApplicationHandlerStop


async def _selfie_image(update: Any, context: Any) -> None:
    import celebrity_selfie_v124 as flow
    await flow._image(update, context)


async def _selfie_text(update: Any, context: Any) -> None:
    import celebrity_selfie_v124 as flow
    await flow._text(update, context)


async def _cmd_version(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    release_ok = _install_celebrity_release()
    mod = _runtime_module()
    if mod is not None:
        _patch_runtime(mod)
    refs = 0
    ref_error = ""
    with contextlib.suppress(Exception):
        import celebrity_selfie_v158 as release
        refs = len(release._fixed_reference_paths())
    if not refs and _RELEASE_ERROR:
        ref_error = _RELEASE_ERROR

    medical_text = bool(mod and getattr(getattr(mod, "_medical_analyze_text", None), "_prod_v120_medical", False))
    medical_image = bool(mod and getattr(getattr(mod, "_medical_analyze_image", None), "_prod_v120_medical", False))
    methods = sorted((getattr(mod, "YOO_DIRECT_METHODS", {}) or {}).keys()) if mod is not None else []
    packs = _packages(mod) if mod is not None else _DEFAULT_PACKAGES
    lines = [
        f"✅ Код запущен: {VERSION}",
        "entrypoint=main.py",
        "start_command=python -u main.py",
        f"release_overlay={'v159' if release_ok else 'v159-selfie-safe-mode'}",
        "celebrity_selfie_menu=v124-priority-catalog-wizard",
        "celebrity_selfie_photo_router=v159-priority-before-generic-photo",
        f"fixed_roman_reference_count={refs}",
        f"fixed_roman_reference_pack={'ready' if refs == 3 else 'warning'}",
        f"fixed_roman_reference_error={ref_error or '-'}",
        "credit_catalog=" + ",".join(f"{c}:{r}" for c, r in sorted(packs.items())),
        "credit_yookassa_methods=" + ",".join(methods),
        f"medical_text_route={'v120' if medical_text else 'legacy'}",
        f"medical_image_route={'v120' if medical_image else 'legacy'}",
        f"medical_card={getattr(mod, 'MEDICAL_CARD_VERSION', '—') if mod is not None else '—'}",
        f"medical_answer_ui={getattr(mod, 'MEDICAL_ANSWER_UI_VERSION', '—') if mod is not None else '—'}",
    ]
    await update.effective_message.reply_text("\n".join(lines)[:3900])
    raise ApplicationHandlerStop


def _patch_runtime(mod: Any) -> bool:
    """Patch public globals repeatedly because legacy workers may overwrite them."""
    try:
        from telegram import InlineKeyboardMarkup

        mod.CREDIT_PACKAGES_RUB = dict(_DEFAULT_PACKAGES)
        methods = getattr(mod, "YOO_DIRECT_METHODS", None)
        if isinstance(methods, dict):
            methods["yoo_card"] = {"type": "bank_card", "confirmation": "redirect", "label": "💳 Банковская карта"}

        def resolver(requested_credits: int = 0, requested_rub: int = 0):
            return _resolve_pack(mod, requested_credits, requested_rub)

        async def send_topup(update: Any, context: Any):
            return await _send_topup_menu(mod, update, context)

        resolver._v159_credit_catalog = True  # type: ignore[attr-defined]
        send_topup._v159_credit_catalog = True  # type: ignore[attr-defined]
        mod._credit_pack_resolve = resolver
        mod._send_topup_menu = send_topup

        with contextlib.suppress(Exception):
            from . import medical_followup
            medical_followup.patch_runtime(mod)

        mod.APP_VERSION = VERSION
        mod.RELEASE_VERSION = VERSION
        mod.PRODUCTION_HARDENING_VERSION = VERSION
        mod.PATCH_VERSION = VERSION
        mod._V159_HOTFIX_ACTIVE = True
        return True
    except Exception as exc:
        log.exception("v159 runtime patch failed: %r", exc)
        return False


def _start_runtime_worker() -> None:
    global _RUNTIME_STARTED
    if _RUNTIME_STARTED:
        return
    _RUNTIME_STARTED = True

    def worker() -> None:
        stable = 0
        for _ in range(3600):
            mod = _runtime_module()
            if mod is None:
                time.sleep(0.1)
                continue
            if _patch_runtime(mod):
                stable += 1
            else:
                stable = 0
            if stable >= 120:
                return
            time.sleep(0.1)

    threading.Thread(target=worker, name="neyrobot-hotfix-v159", daemon=True).start()


def _install_builder_hook() -> None:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        _BUILDER_HOOKED = True
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, _HANDLER_FLAG, False):
            app.add_handler(CommandHandler("version", _cmd_version), group=_GROUP)
            app.add_handler(
                CallbackQueryHandler(_credit_callback, pattern=r"^(?:credit:v159:|topup:rub:).*$"),
                group=_GROUP,
            )
            app.add_handler(
                CallbackQueryHandler(
                    _selfie_callback,
                    pattern=r"^(?:act:fun:aiselfie(?:_.*)?|pedit:aiselfie|celeb:).*$",
                ),
                group=_GROUP,
            )
            app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, _selfie_image), group=_GROUP)
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _selfie_text), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)
    _BUILDER_HOOKED = True


def install_early() -> None:
    _install_celebrity_release()
    _install_builder_hook()
    _start_runtime_worker()
    with contextlib.suppress(Exception):
        import neyrobot_prod
        from neyrobot_prod import bootstrap, versioning
        neyrobot_prod.VERSION = VERSION
        bootstrap.VERSION = VERSION
        versioning.VERSION = VERSION


__all__ = [
    "VERSION", "install_early", "_resolve_pack", "_packages", "_patch_runtime",
    "_install_celebrity_release", "_credit_callback", "_selfie_callback", "_cmd_version",
]
