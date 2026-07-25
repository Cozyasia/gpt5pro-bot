# -*- coding: utf-8 -*-
"""Canonical credit store for Neyro-Bot.

Owns the credit-package catalogue, purchase UI and checkout routing.  The module
is deliberately isolated from subscription billing and accepts old top-up
buttons only as navigation aliases, never as trusted price data.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

VERSION = "v201-credit-store-2026-07-25"
_BUILDER_HOOKED = False
_WORKER_STARTED = False
_PATCH_FLAG = "_CREDIT_STORE_V201_PATCHED"


@dataclass(frozen=True)
class CreditPack:
    key: str
    credits: int
    rub: int


def _int_env(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, default)).strip())
    except Exception:
        return int(default)


def _normalise_credits(raw: int, canonical: int) -> int:
    """Repair the historical missing-zero values 100/300/700."""
    value = int(raw or canonical)
    if value == canonical // 10:
        return canonical
    return value if value > 0 else canonical


def catalog() -> tuple[CreditPack, ...]:
    specs = (
        ("small", "CREDIT_PACK_SMALL_CREDITS", 1000, "CREDIT_PACK_SMALL_RUB", 990),
        ("mid", "CREDIT_PACK_MID_CREDITS", 3000, "CREDIT_PACK_MID_RUB", 2490),
        ("big", "CREDIT_PACK_BIG_CREDITS", 7000, "CREDIT_PACK_BIG_RUB", 4990),
    )
    packs: list[CreditPack] = []
    for key, credits_name, canonical_credits, rub_name, default_rub in specs:
        credits = _normalise_credits(_int_env(credits_name, canonical_credits), canonical_credits)
        rub = max(1, _int_env(rub_name, default_rub))
        packs.append(CreditPack(key, credits, rub))
    return tuple(packs)


def _fmt_int(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def resolve_pack(requested_credits: int = 0, requested_rub: int = 0) -> tuple[int, int] | None:
    credits_req = int(requested_credits or 0)
    rub_req = int(requested_rub or 0)
    stale_alias = {100: 1000, 300: 3000, 700: 7000}
    credits_req = stale_alias.get(credits_req, credits_req)
    for pack in catalog():
        credits_ok = not credits_req or credits_req == pack.credits
        rub_ok = not rub_req or rub_req == pack.rub
        if credits_ok and rub_ok:
            return pack.credits, pack.rub
    return None


def _pack_by_key(key: str) -> CreditPack | None:
    return next((pack for pack in catalog() if pack.key == key), None)


def _pack_from_legacy_callback(data: str) -> CreditPack | None:
    values = [int(value) for value in re.findall(r"\d+", data or "")]
    for value in values:
        for pack in catalog():
            if value in {pack.credits, pack.credits // 10, pack.rub}:
                return pack
    return None


def _kb(mod: Any, rows: list[list[tuple[str, str, str]]]):
    rendered = []
    for row in rows:
        buttons = []
        for label, kind, value in row:
            if kind == "url":
                buttons.append(mod.InlineKeyboardButton(label, url=value))
            else:
                buttons.append(mod.InlineKeyboardButton(label, callback_data=value))
        rendered.append(buttons)
    return mod.InlineKeyboardMarkup(rendered)


def store_keyboard(mod: Any):
    packs = catalog()
    rows = [
        [(f"🪙 {_fmt_int(pack.credits)} кр. · {_fmt_int(pack.rub)} ₽", "cb", f"credit:v201:pack:{pack.key}")]
        for pack in packs
    ]
    rows.append([("⬅️ К тарифам", "cb", "plan:root")])
    return _kb(mod, rows)


def store_text(mod: Any, user_id: int = 0) -> str:
    balance = ""
    getter = getattr(mod, "_user_balance_get", None)
    formatter = getattr(mod, "_credits_fmt_from_usd", None)
    if user_id and callable(getter) and callable(formatter):
        with contextlib.suppress(Exception):
            balance = f"\nТекущий баланс: {formatter(getter(user_id))}."
    return (
        "🪙 Покупка кредитов\n\n"
        "Кредиты используются для видео, музыки, AI-фото, FaceSwap, говорящего аватара и других тяжёлых генераций.\n"
        "1 кредит = 1 ₽. Выберите пакет; на следующем шаге будут показаны доступные способы оплаты."
        + balance
    )


def methods_keyboard(mod: Any, pack: CreditPack):
    rows: list[list[tuple[str, str, str]]] = []
    if bool(getattr(mod, "YOO_SBP_ENABLED", True)):
        rows.append([("⚡ СБП / QR", "cb", f"credit:v201:pay:yoo_sbp:{pack.key}")])
    apps = []
    if bool(getattr(mod, "YOO_SBERPAY_ENABLED", True)):
        apps.append(("🟢 SberPay", "cb", f"credit:v201:pay:yoo_sberpay:{pack.key}"))
    if bool(getattr(mod, "YOO_TPAY_ENABLED", True)):
        apps.append(("🟡 T-Pay", "cb", f"credit:v201:pay:yoo_tpay:{pack.key}"))
    if apps:
        rows.append(apps)
    apps2 = []
    if bool(getattr(mod, "YOO_MIRPAY_ENABLED", True)):
        apps2.append(("💙 Mir Pay", "cb", f"credit:v201:pay:yoo_mirpay:{pack.key}"))
    if str(getattr(mod, "YOOKASSA_PROVIDER_TOKEN", "") or "").strip():
        apps2.append(("💳 Карта в Telegram", "cb", f"credit:v201:pay:telegram:{pack.key}"))
    if apps2:
        rows.append(apps2)
    rows.append([("🌐 Все способы ЮKassa", "cb", f"credit:v201:pay:yoo_all:{pack.key}")])
    if str(getattr(mod, "CRYPTO_PAY_API_TOKEN", "") or "").strip():
        rows.append([("💠 CryptoBot / USDT", "cb", f"credit:v201:pay:crypto:{pack.key}")])
    rows.append([("⬅️ Другой пакет", "cb", "credit:v201:open")])
    return _kb(mod, rows)


def _method_label(mod: Any, method: str) -> str:
    mapping = getattr(mod, "YOO_DIRECT_METHODS", {}) or {}
    if method in mapping:
        return str((mapping.get(method) or {}).get("label") or method)
    return {"telegram": "💳 Карта в Telegram", "crypto": "💠 CryptoBot / USDT"}.get(method, method)


async def _show_store(mod: Any, update: Any) -> None:
    await update.effective_message.reply_text(
        store_text(mod, int(getattr(update.effective_user, "id", 0) or 0)),
        reply_markup=store_keyboard(mod),
    )


async def _show_methods(mod: Any, update: Any, pack: CreditPack) -> None:
    await update.effective_message.reply_text(
        f"🪙 Пакет: {_fmt_int(pack.credits)} кредитов за {_fmt_int(pack.rub)} ₽.\nВыберите способ оплаты:",
        reply_markup=methods_keyboard(mod, pack),
    )


async def _create_yoo(mod: Any, update: Any, context: Any, pack: CreditPack, method: str) -> None:
    configured = getattr(mod, "_yoo_direct_configured", None)
    creator = getattr(mod, "_yoo_create_credit_payment", None)
    if not callable(configured) or not configured() or not callable(creator):
        await update.effective_message.reply_text(
            "⚠️ ЮKassa не настроена: проверьте YOO_SHOP_ID/YOO_SECRET_KEY (или YK_ID/YK_KEY в yookassa.env).",
            reply_markup=methods_keyboard(mod, pack),
        )
        return
    pay = await creator(update.effective_user.id, pack.credits, pack.rub, method)
    payment_id = str(pay.get("id") or "")
    confirmation = pay.get("confirmation") or {}
    url = confirmation.get("confirmation_url") or confirmation.get("external_url") or ""
    if not payment_id or not url:
        raise RuntimeError("ЮKassa не вернула id или ссылку подтверждения")
    label = _method_label(mod, method)
    markup = _kb(mod, [[(f"{label} — оплатить", "url", url)], [("⬅️ К способам", "cb", f"credit:v201:pack:{pack.key}")]])
    msg = await update.effective_message.reply_text(
        f"🪙 {_fmt_int(pack.credits)} кредитов за {_fmt_int(pack.rub)} ₽.\n"
        f"Способ: {label}. Откройте ссылку; после подтверждения кредиты начислятся автоматически.",
        reply_markup=markup,
    )
    poller = getattr(mod, "_poll_yoo_credit_payment", None)
    if callable(poller):
        context.application.create_task(
            poller(context, msg.chat.id, msg.message_id, update.effective_user.id, payment_id, pack.credits, pack.rub)
        )


async def _create_telegram_invoice(mod: Any, update: Any, context: Any, pack: CreditPack) -> None:
    token = str(getattr(mod, "YOOKASSA_PROVIDER_TOKEN", "") or "").strip()
    if not token:
        await update.effective_message.reply_text("⚠️ Оплата картой в Telegram не подключена.", reply_markup=methods_keyboard(mod, pack))
        return
    price = mod.LabeledPrice(label=f"{_fmt_int(pack.credits)} кредитов", amount=pack.rub * 100)
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=f"{_fmt_int(pack.credits)} кредитов",
        description=f"Пополнение баланса Neyro-Bot на {_fmt_int(pack.credits)} кредитов.",
        payload=f"topup:{pack.credits}:{pack.rub}",
        provider_token=token,
        currency="RUB",
        prices=[price],
        need_email=True,
        is_flexible=False,
    )


async def _crypto_status(token: str, invoice_id: str) -> dict[str, Any]:
    headers = {"Crypto-Pay-API-Token": token}
    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.get("https://pay.crypt.bot/api/getInvoices", headers=headers, params={"invoice_ids": invoice_id})
        data = response.json()
    if not data.get("ok"):
        raise RuntimeError(str(data)[:700])
    items = ((data.get("result") or {}).get("items") or [])
    return items[0] if items else {}


async def _poll_crypto(mod: Any, context: Any, msg: Any, pack: CreditPack, invoice_id: str, user_id: int) -> None:
    token = str(getattr(mod, "CRYPTO_PAY_API_TOKEN", "") or "").strip()
    deadline = time.time() + max(120, int(getattr(mod, "YOO_PAYMENT_POLL_SECONDS", 900) or 900))
    while time.time() < deadline:
        try:
            item = await _crypto_status(token, invoice_id)
            status = str(item.get("status") or "").lower()
            if status == "paid":
                from neyrobot_prod.payments import process_once
                result = process_once(
                    mod,
                    provider="cryptobot",
                    payment_id=str(invoice_id),
                    provider_charge_id=str(invoice_id),
                    user_id=int(user_id),
                    kind="credit_topup",
                    amount=float(item.get("amount") or 0),
                    currency=str(item.get("asset") or "USDT"),
                    metadata={"credits": pack.credits, "amount_rub": pack.rub, "invoice_id": invoice_id},
                )
                text = "✅ Платёж уже был обработан ранее." if result.duplicate else f"✅ CryptoBot подтвердил оплату. Начислено: {_fmt_int(result.credits)} кредитов."
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=msg.chat.id, message_id=msg.message_id, text=text)
                return
            if status in {"expired", "cancelled", "canceled"}:
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(chat_id=msg.chat.id, message_id=msg.message_id, text=f"❌ CryptoBot: счёт {status}.")
                return
        except Exception:
            pass
        await asyncio.sleep(5)


async def _create_crypto(mod: Any, update: Any, context: Any, pack: CreditPack) -> None:
    token = str(getattr(mod, "CRYPTO_PAY_API_TOKEN", "") or "").strip()
    if not token:
        await update.effective_message.reply_text("⚠️ CryptoBot не подключён.", reply_markup=methods_keyboard(mod, pack))
        return
    rub_per_usd = max(1.0, float(os.environ.get("CREDIT_CRYPTO_RUB_PER_USD", "100") or 100))
    amount = pack.rub / rub_per_usd
    payload = f"{int(update.effective_user.id)}:{pack.key}"
    headers = {"Crypto-Pay-API-Token": token, "Content-Type": "application/json"}
    body = {
        "asset": str(getattr(mod, "CRYPTO_ASSET", "USDT") or "USDT"),
        "amount": f"{amount:.2f}",
        "description": f"{pack.credits} Neyro-Bot credits",
        "payload": payload,
        "allow_comments": False,
        "allow_anonymous": True,
    }
    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.post("https://pay.crypt.bot/api/createInvoice", headers=headers, json=body)
        data = response.json()
    if not data.get("ok"):
        raise RuntimeError(str(data)[:900])
    item = data.get("result") or {}
    invoice_id = str(item.get("invoice_id") or "")
    url = item.get("bot_invoice_url") or item.get("pay_url") or item.get("mini_app_invoice_url") or ""
    if not invoice_id or not url:
        raise RuntimeError("CryptoBot не вернул invoice_id/pay_url")
    markup = _kb(mod, [[("💠 Открыть CryptoBot", "url", url)], [("⬅️ К способам", "cb", f"credit:v201:pack:{pack.key}")]])
    msg = await update.effective_message.reply_text(
        f"🪙 {_fmt_int(pack.credits)} кредитов за {_fmt_int(pack.rub)} ₽ · примерно {amount:.2f} USDT.\n"
        "Курс для CryptoBot фиксируется настройкой магазина; после оплаты кредиты начислятся автоматически.",
        reply_markup=markup,
    )
    context.application.create_task(_poll_crypto(mod, context, msg, pack, invoice_id, int(update.effective_user.id)))


async def callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    mod = _runtime_module()
    query = getattr(update, "callback_query", None)
    if mod is None or query is None:
        return
    data = str(query.data or "")
    try:
        with contextlib.suppress(Exception):
            await query.answer()
        if data in {"topup", "credit:v201:open"}:
            await _show_store(mod, update)
            raise ApplicationHandlerStop
        if data.startswith("topup:"):
            pack = _pack_from_legacy_callback(data)
            if pack:
                await _show_methods(mod, update, pack)
            else:
                await _show_store(mod, update)
            raise ApplicationHandlerStop
        if data.startswith("credit:v201:pack:"):
            pack = _pack_by_key(data.rsplit(":", 1)[-1])
            if not pack:
                await _show_store(mod, update)
            else:
                await _show_methods(mod, update, pack)
            raise ApplicationHandlerStop
        if data.startswith("credit:v201:pay:"):
            _, _, _, method, key = data.split(":", 4)
            pack = _pack_by_key(key)
            if not pack:
                await _show_store(mod, update)
                raise ApplicationHandlerStop
            try:
                if method in (getattr(mod, "YOO_DIRECT_METHODS", {}) or {}):
                    await _create_yoo(mod, update, context, pack, method)
                elif method == "telegram":
                    await _create_telegram_invoice(mod, update, context, pack)
                elif method == "crypto":
                    await _create_crypto(mod, update, context, pack)
                else:
                    await _show_methods(mod, update, pack)
            except Exception as exc:
                logger = getattr(mod, "log", None)
                if logger:
                    with contextlib.suppress(Exception):
                        logger.exception("credit checkout failed: %s", exc)
                await update.effective_message.reply_text(
                    f"⚠️ Не удалось создать оплату: {type(exc).__name__}. Выберите другой способ или повторите позже.",
                    reply_markup=methods_keyboard(mod, pack),
                )
            raise ApplicationHandlerStop
    except ApplicationHandlerStop:
        raise


async def diag(update: Any, context: Any) -> None:
    mod = _runtime_module()
    if mod is None:
        return
    lines = ["🪙 Credit Store diagnostic", f"version={VERSION}"]
    for pack in catalog():
        lines.append(f"{pack.key}={pack.credits}:{pack.rub}")
    configured = getattr(mod, "_yoo_direct_configured", None)
    lines.extend([
        f"yookassa_direct={'on' if callable(configured) and configured() else 'off'}",
        f"telegram_card={'on' if bool(str(getattr(mod, 'YOOKASSA_PROVIDER_TOKEN', '') or '').strip()) else 'off'}",
        f"cryptobot={'on' if bool(str(getattr(mod, 'CRYPTO_PAY_API_TOKEN', '') or '').strip()) else 'off'}",
    ])
    await update.effective_message.reply_text("\n".join(lines))


def install_builder_hook() -> bool:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return True
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler
    except Exception:
        return False
    class_flag = "_credit_store_v201_builder"
    if getattr(ApplicationBuilder, class_flag, False):
        _BUILDER_HOOKED = True
        return True
    original_build = ApplicationBuilder.build
    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, class_flag, False):
            app.add_handler(CallbackQueryHandler(callback, pattern=r"^(?:topup(?:$|:)|credit:v201:)"), group=-31)
            app.add_handler(CommandHandler("diag_credit_store", diag), group=-31)
            setattr(app, class_flag, True)
        return app
    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, class_flag, True)
    _BUILDER_HOOKED = True
    return True


def patch_runtime(mod: Any) -> bool:
    if not all(hasattr(mod, name) for name in ("InlineKeyboardButton", "InlineKeyboardMarkup", "BOT_TOKEN")):
        return False
    mod.CREDIT_PACKAGES_RUB = {pack.credits: pack.rub for pack in catalog()}
    mod._credit_pack_resolve = resolve_pack
    mod.credit_store_kb = lambda: store_keyboard(mod)
    mod.CREDIT_STORE_VERSION = VERSION
    setattr(mod, _PATCH_FLAG, True)
    return True


def install_async() -> None:
    global _WORKER_STARTED
    install_builder_hook()
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True
    def worker() -> None:
        stable = 0
        for _ in range(3600):
            mod = _runtime_module()
            if mod is None:
                time.sleep(0.1)
                continue
            try:
                if patch_runtime(mod):
                    stable += 1
                    if stable >= 300:
                        return
                else:
                    stable = 0
            except Exception:
                stable = 0
            time.sleep(0.1)
    import threading
    threading.Thread(target=worker, daemon=True, name="neyrobot-credit-store-v201").start()


__all__ = ["VERSION", "CreditPack", "catalog", "resolve_pack", "store_keyboard", "methods_keyboard", "patch_runtime", "install_builder_hook", "install_async"]
