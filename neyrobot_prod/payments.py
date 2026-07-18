# -*- coding: utf-8 -*-
"""Idempotent payment processing and polling adapters for Neyro-Bot."""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .db import connect, init_schema, record_event


@dataclass(slots=True)
class PaymentResult:
    processed: bool
    duplicate: bool
    kind: str
    credits: int = 0
    until_ts: int = 0
    message: str = ""


def _clean_text(value: Any, limit: int = 4000) -> str:
    return str(value or "").replace("\x00", " ").strip()[:limit]


def _allowed_tier(mod: Any, tier: str) -> bool:
    tier = (tier or "").lower().strip()
    tables = [getattr(mod, "SUBS_TIERS", {}), getattr(mod, "SUBSCRIPTION_CREDITS", {})]
    return tier in {"start", "pro", "ultimate"} and any(tier in table for table in tables if isinstance(table, dict))


def _credits_to_usd(mod: Any, credits: int) -> float:
    fn = getattr(mod, "_credits_to_usd", None)
    if callable(fn):
        return float(fn(int(credits)))
    rub_per_usd = max(1.0, float(getattr(mod, "USD_RUB", 100.0) or 100.0))
    return float(credits) / rub_per_usd


def _subscription_credits(mod: Any, tier: str, months: int) -> int:
    table = getattr(mod, "SUBSCRIPTION_CREDITS", {})
    return int((table or {}).get(tier, 0) or 0) * int(months)


def _current_until_ts(con: Any, user_id: int, now_ts: int) -> int:
    row = con.execute("SELECT until_ts FROM subscriptions WHERE user_id=?", (int(user_id),)).fetchone()
    current = int(row[0] or 0) if row else 0
    return current if current > now_ts else now_ts


def _ensure_commercial_tables(con: Any) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, until_ts INTEGER NOT NULL, tier TEXT)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS wallet (user_id INTEGER PRIMARY KEY, luma_usd REAL DEFAULT 0.0, runway_usd REAL DEFAULT 0.0, img_usd REAL DEFAULT 0.0, usd REAL DEFAULT 0.0)"
    )
    cols = {str(row[1]) for row in con.execute("PRAGMA table_info(wallet)").fetchall()}
    if "usd" not in cols:
        con.execute("ALTER TABLE wallet ADD COLUMN usd REAL DEFAULT 0.0")


def _add_wallet_usd(con: Any, user_id: int, amount_usd: float) -> None:
    _ensure_commercial_tables(con)
    con.execute("INSERT OR IGNORE INTO wallet(user_id, usd) VALUES (?,0)", (int(user_id),))
    con.execute("UPDATE wallet SET usd=COALESCE(usd,0)+? WHERE user_id=?", (float(amount_usd), int(user_id)))


def process_once(
    mod: Any,
    *,
    provider: str,
    payment_id: str,
    provider_charge_id: str = "",
    user_id: int,
    kind: str,
    amount: float,
    currency: str,
    metadata: dict[str, Any],
) -> PaymentResult:
    """Apply one successful payment atomically with a unique provider/payment key."""
    db_path = str(getattr(mod, "DB_PATH", "") or "")
    if not db_path:
        raise RuntimeError("DB_PATH is not configured")
    provider = _clean_text(provider, 40).lower()
    payment_id = _clean_text(payment_id, 160)
    charge_id = _clean_text(provider_charge_id, 160)
    kind = _clean_text(kind, 40).lower()
    currency = _clean_text(currency, 12).upper()
    if not provider or not payment_id or not user_id:
        raise ValueError("provider, payment_id and user_id are required")

    init_schema(db_path)
    con = connect(db_path)
    now_ts = int(time.time())
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            con.execute(
                """INSERT INTO payment_events(
                       provider,payment_id,provider_charge_id,user_id,kind,amount,currency,status,
                       metadata_json,created_ts
                   ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    provider,
                    payment_id,
                    charge_id or None,
                    int(user_id),
                    kind,
                    float(amount or 0),
                    currency,
                    "processing",
                    json.dumps(metadata, ensure_ascii=False, default=str)[:12000],
                    now_ts,
                ),
            )
        except sqlite3.IntegrityError as exc:
            text = str(exc).lower()
            if "unique" in text or "constraint" in text:
                row = con.execute(
                    "SELECT status,kind,metadata_json FROM payment_events WHERE provider=? AND (payment_id=? OR provider_charge_id=?) ORDER BY id DESC LIMIT 1",
                    (provider, payment_id, charge_id),
                ).fetchone()
                con.rollback()
                return PaymentResult(False, True, row[1] if row else kind, message="Платёж уже обработан ранее.")
            raise

        credits = 0
        until_ts = 0
        if kind == "subscription":
            tier = str(metadata.get("tier") or "").lower().strip()
            months = int(metadata.get("months") or 1)
            if not _allowed_tier(mod, tier) or months not in {1, 3, 6, 12}:
                raise ValueError("Invalid subscription metadata")
            _ensure_commercial_tables(con)
            base_ts = _current_until_ts(con, int(user_id), now_ts)
            until_ts = base_ts + 30 * 86400 * months
            con.execute(
                """INSERT INTO subscriptions(user_id,until_ts,tier) VALUES (?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET until_ts=excluded.until_ts,tier=excluded.tier""",
                (int(user_id), int(until_ts), tier),
            )
            credits = _subscription_credits(mod, tier, months)
            if credits:
                _add_wallet_usd(con, int(user_id), _credits_to_usd(mod, credits))
        elif kind == "credit_topup":
            credits = int(metadata.get("credits") or 0)
            if credits <= 0:
                raise ValueError("Invalid credit package")
            _add_wallet_usd(con, int(user_id), _credits_to_usd(mod, credits))
        elif kind == "wallet_usd":
            usd_amount = float(metadata.get("usd_amount") or amount or 0)
            if usd_amount <= 0:
                raise ValueError("Invalid wallet amount")
            _add_wallet_usd(con, int(user_id), usd_amount)
        else:
            raise ValueError(f"Unsupported payment kind: {kind}")

        con.execute(
            "UPDATE payment_events SET status='processed',processed_ts=? WHERE provider=? AND payment_id=?",
            (now_ts, provider, payment_id),
        )
        con.commit()
        return PaymentResult(True, False, kind, credits=credits, until_ts=until_ts)
    except Exception as exc:
        with contextlib.suppress(Exception):
            con.rollback()
        record_event(
            db_path,
            "payment_processing_error",
            severity="error",
            user_id=int(user_id),
            feature=kind,
            details={"provider": provider, "payment_id": payment_id, "error": repr(exc)},
        )
        raise
    finally:
        con.close()


def _format_until(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d") if ts else ""


async def _edit(context: Any, chat_id: int, message_id: int, text: str) -> None:
    with contextlib.suppress(Exception):
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)


def _parse_telegram_payload(mod: Any, payload: str, rub: float) -> tuple[str, dict[str, Any]]:
    raw = (payload or "").strip()
    if raw.startswith("{"):
        with contextlib.suppress(Exception):
            obj = json.loads(raw)
            tier = str(obj.get("tier") or "").lower().strip()
            months = int(obj.get("months") or 1)
            if tier:
                return "subscription", {"tier": tier, "months": months}
    if raw.startswith("sub:"):
        _, tier, months = raw.split(":", 2)
        return "subscription", {"tier": tier.lower().strip(), "months": int(months or 1)}
    if raw.startswith("topup:"):
        _, credits_s, rub_s = raw.split(":", 2)
        resolver = getattr(mod, "_credit_pack_resolve", None)
        resolved = resolver(int(credits_s), int(rub_s)) if callable(resolver) else (int(credits_s), int(rub_s))
        if not resolved:
            raise ValueError("Unknown credit package")
        credits, expected_rub = resolved
        if abs(float(expected_rub) - float(rub)) > 1.0:
            raise ValueError("Paid amount does not match package")
        return "credit_topup", {"credits": int(credits), "amount_rub": int(expected_rub)}
    raise ValueError("Unknown Telegram invoice payload")


def _expected_precheckout(mod: Any, payload: str) -> tuple[str, int] | None:
    raw = (payload or "").strip()
    if raw.startswith("{"):
        with contextlib.suppress(Exception):
            obj = json.loads(raw)
            tier = str(obj.get("tier") or "").lower().strip()
            months = int(obj.get("months") or 1)
            if tier and _allowed_tier(mod, tier):
                plan = (getattr(mod, "SUBS_TIERS", {}) or {}).get(tier) or {}
                return "RUB", int(plan.get("rub") or 0) * 100 * months
    if raw.startswith("sub:"):
        with contextlib.suppress(Exception):
            _, tier, months_s = raw.split(":", 2)
            tier = tier.lower().strip()
            months = int(months_s or 1)
            plan = (getattr(mod, "SUBS_TIERS", {}) or {}).get(tier) or {}
            return "RUB", int(plan.get("rub") or 0) * 100 * months
    if raw.startswith("topup:"):
        with contextlib.suppress(Exception):
            _, credits_s, rub_s = raw.split(":", 2)
            resolver = getattr(mod, "_credit_pack_resolve", None)
            resolved = resolver(int(credits_s), int(rub_s)) if callable(resolver) else None
            if resolved:
                _credits, rub = resolved
                return "RUB", int(rub) * 100
    return None


async def precheckout_handler(mod: Any, update: Any, context: Any) -> None:
    query = getattr(update, "pre_checkout_query", None)
    if query is None:
        return
    expected = _expected_precheckout(mod, str(getattr(query, "invoice_payload", "") or ""))
    currency = str(getattr(query, "currency", "") or "").upper()
    total = int(getattr(query, "total_amount", 0) or 0)
    if not expected:
        await query.answer(ok=False, error_message="Не удалось проверить состав счёта. Создайте новый счёт в меню бота.")
        return
    expected_currency, expected_total = expected
    if currency != expected_currency or total != expected_total:
        await query.answer(ok=False, error_message="Сумма счёта не совпадает с актуальным тарифом. Создайте новый счёт.")
        return
    await query.answer(ok=True)


async def successful_payment_handler(mod: Any, update: Any, context: Any) -> None:
    sp = getattr(getattr(update, "message", None), "successful_payment", None)
    if sp is None:
        return
    uid = int(update.effective_user.id)
    currency = str(getattr(sp, "currency", "RUB") or "RUB")
    amount_minor = int(getattr(sp, "total_amount", 0) or 0)
    amount = amount_minor / 100.0
    payload = str(getattr(sp, "invoice_payload", "") or "")
    provider_charge = str(getattr(sp, "provider_payment_charge_id", "") or "")
    telegram_charge = str(getattr(sp, "telegram_payment_charge_id", "") or "")
    payment_id = provider_charge or telegram_charge
    if not payment_id:
        raise RuntimeError("Telegram payment has no charge id")
    kind, metadata = _parse_telegram_payload(mod, payload, amount)
    result = process_once(
        mod,
        provider="telegram",
        payment_id=payment_id,
        provider_charge_id=telegram_charge,
        user_id=uid,
        kind=kind,
        amount=amount,
        currency=currency,
        metadata=metadata | {"invoice_payload": payload},
    )
    if result.duplicate:
        await update.effective_message.reply_text("✅ Этот платёж уже был обработан. Повторное начисление не выполнялось.")
    elif kind == "subscription":
        await update.effective_message.reply_text(
            f"🎉 Оплата прошла успешно!\n✅ Подписка {metadata['tier'].upper()} активирована до {_format_until(result.until_ts)}.\n"
            f"🪙 Кредиты начислены: {result.credits} кр."
        )
    else:
        await update.effective_message.reply_text(f"✅ Оплата подтверждена. Начислено: {result.credits} кредитов.")


async def poll_yoo_subscription(mod: Any, context: Any, chat_id: int, message_id: int, user_id: int, payment_id: str, plan_key: str, months: int) -> None:
    deadline = time.time() + max(60, int(getattr(mod, "YOO_PAYMENT_POLL_SECONDS", 900) or 900))
    while time.time() < deadline:
        payment = await mod._yoo_get_payment(payment_id)
        status = str((payment or {}).get("status") or "").lower()
        if status == "succeeded":
            amount_obj = (payment or {}).get("amount") or {}
            amount = float(amount_obj.get("value") or 0)
            result = process_once(
                mod,
                provider="yookassa",
                payment_id=payment_id,
                user_id=int(user_id),
                kind="subscription",
                amount=amount,
                currency=str(amount_obj.get("currency") or "RUB"),
                metadata={"tier": plan_key, "months": int(months), "source": "direct"},
            )
            if result.duplicate:
                await _edit(context, chat_id, message_id, "✅ Платёж уже обработан ранее. Повторная активация не выполнялась.")
            else:
                await _edit(context, chat_id, message_id, f"✅ Оплата ЮKassa подтверждена.\nПодписка {plan_key.upper()} активна до {_format_until(result.until_ts)}.\n🪙 Кредиты начислены: {result.credits} кр.")
            return
        if status in {"canceled", "cancelled", "failed"}:
            await _edit(context, chat_id, message_id, f"❌ Оплата не завершена. Статус: {status}.")
            return
        await asyncio.sleep(max(2.0, float(getattr(mod, "YOO_PAYMENT_POLL_INTERVAL_S", 5) or 5)))
    await _edit(context, chat_id, message_id, "⌛ Время ожидания оплаты вышло. Создайте новый счёт или обратитесь в поддержку, если деньги списались.")


async def poll_yoo_credit(mod: Any, context: Any, chat_id: int, message_id: int, user_id: int, payment_id: str, credits: int, amount_rub: int) -> None:
    deadline = time.time() + max(60, int(getattr(mod, "YOO_PAYMENT_POLL_SECONDS", 900) or 900))
    while time.time() < deadline:
        payment = await mod._yoo_get_payment(payment_id)
        status = str((payment or {}).get("status") or "").lower()
        if status == "succeeded":
            amount_obj = (payment or {}).get("amount") or {}
            paid = float(amount_obj.get("value") or 0)
            if abs(paid - float(amount_rub)) > 1.0:
                raise RuntimeError("YooKassa amount mismatch")
            result = process_once(
                mod,
                provider="yookassa",
                payment_id=payment_id,
                user_id=int(user_id),
                kind="credit_topup",
                amount=paid,
                currency=str(amount_obj.get("currency") or "RUB"),
                metadata={"credits": int(credits), "amount_rub": int(amount_rub), "source": "direct"},
            )
            text = "✅ Этот платёж уже был обработан ранее." if result.duplicate else f"✅ Оплата ЮKassa подтверждена.\nНачислено: {result.credits} кредитов за {amount_rub} ₽."
            await _edit(context, chat_id, message_id, text)
            return
        if status in {"canceled", "cancelled", "failed"}:
            await _edit(context, chat_id, message_id, f"❌ Оплата пакета кредитов не завершена. Статус: {status}.")
            return
        await asyncio.sleep(max(2.0, float(getattr(mod, "YOO_PAYMENT_POLL_INTERVAL_S", 5) or 5)))
    await _edit(context, chat_id, message_id, "⌛ Время ожидания оплаты вышло. Если деньги списались, обратитесь в поддержку.")


async def poll_crypto_wallet(mod: Any, context: Any, chat_id: int, message_id: int, user_id: int, invoice_id: str, usd_amount: float) -> None:
    for _ in range(120):
        inv = await mod._crypto_get_invoice(invoice_id)
        status = str((inv or {}).get("status") or "").lower()
        if status == "paid":
            result = process_once(
                mod,
                provider="cryptobot",
                payment_id=str(invoice_id),
                user_id=int(user_id),
                kind="wallet_usd",
                amount=float(usd_amount),
                currency=str((inv or {}).get("asset") or "USDT"),
                metadata={"usd_amount": float(usd_amount), "invoice": inv or {}},
            )
            text = "✅ Этот CryptoBot-платёж уже обработан." if result.duplicate else f"✅ CryptoBot: платёж подтверждён. Начислено: {mod._credits_fmt_from_usd(float(usd_amount))}."
            await _edit(context, chat_id, message_id, text)
            return
        if status in {"expired", "cancelled", "canceled", "failed"}:
            await _edit(context, chat_id, message_id, f"❌ CryptoBot: платёж не завершён (статус: {status}).")
            return
        await asyncio.sleep(6.0)
    await _edit(context, chat_id, message_id, "⌛ CryptoBot: время ожидания вышло. Нажмите «Проверить» позже.")


async def poll_crypto_subscription(mod: Any, context: Any, chat_id: int, message_id: int, user_id: int, invoice_id: str, tier: str, months: int) -> None:
    for _ in range(120):
        inv = await mod._crypto_get_invoice(invoice_id)
        status = str((inv or {}).get("status") or "").lower()
        if status == "paid":
            result = process_once(
                mod,
                provider="cryptobot",
                payment_id=str(invoice_id),
                user_id=int(user_id),
                kind="subscription",
                amount=float((inv or {}).get("amount") or 0),
                currency=str((inv or {}).get("asset") or "USDT"),
                metadata={"tier": tier, "months": int(months), "invoice": inv or {}},
            )
            text = "✅ Этот CryptoBot-платёж уже обработан." if result.duplicate else f"✅ CryptoBot: платёж подтверждён.\nПодписка {tier.upper()} активна до {_format_until(result.until_ts)}.\n🪙 Кредиты начислены: {result.credits} кр."
            await _edit(context, chat_id, message_id, text)
            return
        if status in {"expired", "cancelled", "canceled", "failed"}:
            await _edit(context, chat_id, message_id, f"❌ CryptoBot: оплата не завершена (статус: {status}).")
            return
        await asyncio.sleep(6.0)
    await _edit(context, chat_id, message_id, "⌛ CryptoBot: время ожидания вышло. Нажмите «Проверить» позже.")


def patch_runtime(mod: Any) -> bool:
    required = ("DB_PATH", "_yoo_get_payment", "_crypto_get_invoice")
    if not all(hasattr(mod, name) for name in required):
        return False

    async def yoo_sub(context: Any, chat_id: int, message_id: int, user_id: int, payment_id: str, plan_key: str, months: int):
        return await poll_yoo_subscription(mod, context, chat_id, message_id, user_id, payment_id, plan_key, months)

    async def yoo_credit(context: Any, chat_id: int, message_id: int, user_id: int, payment_id: str, credits: int, amount_rub: int):
        return await poll_yoo_credit(mod, context, chat_id, message_id, user_id, payment_id, credits, amount_rub)

    async def crypto_wallet(context: Any, chat_id: int, message_id: int, user_id: int, invoice_id: str, usd_amount: float):
        return await poll_crypto_wallet(mod, context, chat_id, message_id, user_id, invoice_id, usd_amount)

    async def crypto_sub(context: Any, chat_id: int, message_id: int, user_id: int, invoice_id: str, tier: str, months: int):
        return await poll_crypto_subscription(mod, context, chat_id, message_id, user_id, invoice_id, tier, months)

    async def successful(update: Any, context: Any):
        try:
            await successful_payment_handler(mod, update, context)
        except Exception as exc:
            logger = getattr(mod, "log", None)
            if logger:
                logger.exception("production successful_payment failed: %r", exc)
            with contextlib.suppress(Exception):
                await update.effective_message.reply_text("⚠️ Платёж получен, но автоматическая обработка не завершилась. Повторно платить не нужно; обратитесь в поддержку.")

    yoo_sub._prod_v119_payment = True  # type: ignore[attr-defined]
    yoo_credit._prod_v119_payment = True  # type: ignore[attr-defined]
    crypto_wallet._prod_v119_payment = True  # type: ignore[attr-defined]
    crypto_sub._prod_v119_payment = True  # type: ignore[attr-defined]
    successful._prod_v119_payment = True  # type: ignore[attr-defined]
    mod._poll_yoo_subscription_payment = yoo_sub
    mod._poll_yoo_credit_payment = yoo_credit
    mod._poll_crypto_invoice = crypto_wallet
    mod._poll_crypto_sub_invoice = crypto_sub
    mod.on_successful_payment = successful
    mod._PROD_PAYMENTS_PATCHED = True
    return True


__all__ = [
    "PaymentResult",
    "process_once",
    "successful_payment_handler",
    "precheckout_handler",
    "patch_runtime",
]
