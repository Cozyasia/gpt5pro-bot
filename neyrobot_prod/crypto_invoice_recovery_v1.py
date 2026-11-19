"""Durable reconciliation for invoices created by the v201 credit store."""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from neyrobot_prod.db import connect, init_schema
from neyrobot_prod.payments import process_once

log = logging.getLogger(__name__)


def _init(path: str) -> None:
    if not path:
        raise RuntimeError('Payment database unavailable')
    init_schema(path)
    with connect(path) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS crypto_store_invoices (
            invoice_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, credits INTEGER NOT NULL,
            amount_rub INTEGER NOT NULL, amount TEXT NOT NULL, asset TEXT NOT NULL,
            payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            created_ts INTEGER NOT NULL DEFAULT (unixepoch())
        )''')
        con.execute("""CREATE TABLE IF NOT EXISTS yoo_store_invoices (payment_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, credits INTEGER NOT NULL, amount_rub INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending')""")


def register(path: str, invoice_id: str, user_id: int, credits: int, rub: int,
             amount: str, asset: str, payload: str) -> None:
    invoice_id, asset = str(invoice_id), str(asset).upper()
    if not invoice_id or not payload or int(user_id) <= 0 or int(credits) <= 0 or int(rub) <= 0 or not Decimal(amount).is_finite() or Decimal(amount) <= 0:
        raise ValueError('Invalid invoice terms')
    terms = (int(user_id), int(credits), int(rub), str(amount), asset, str(payload))
    _init(path)
    with connect(path) as con:
        con.execute('INSERT OR IGNORE INTO crypto_store_invoices(invoice_id,user_id,credits,amount_rub,amount,asset,payload) VALUES (?,?,?,?,?,?,?)', (invoice_id, *terms))
        existing = con.execute('SELECT user_id,credits,amount_rub,amount,asset,payload FROM crypto_store_invoices WHERE invoice_id=?', (invoice_id,)).fetchone()
        if tuple(existing) != terms:
            raise ValueError('Invoice identifier reused with different terms')


def _matches(item: dict[str, Any], invoice_id: str, amount: str, asset: str, payload: str) -> bool:
    try:
        value = Decimal(str(item.get('amount', '')))
        return (str(item.get('invoice_id', '')) == invoice_id and value.is_finite()
                and value == Decimal(amount) and str(item.get('asset', '')).upper() == asset
                and str(item.get('payload', '')) == payload)
    except (InvalidOperation, ValueError):
        return False


async def reconcile_once(mod: Any, bot: Any, status_fn: Any) -> None:
    path = str(getattr(mod, 'DB_PATH', '') or '')
    token = str(getattr(mod, 'CRYPTO_PAY_API_TOKEN', '') or '')
    if not token:
        return
    _init(path)
    with connect(path) as con:
        rows = con.execute("SELECT invoice_id,user_id,credits,amount_rub,amount,asset,payload FROM crypto_store_invoices WHERE status='pending' ORDER BY created_ts").fetchall()
    for invoice_id, user_id, credits, rub, amount, asset, payload in rows:
        try:
            item = await status_fn(token, invoice_id)
            status = str(item.get('status') or '').lower()
            if status == 'paid':
                if not _matches(item, invoice_id, amount, asset, payload):
                    log.error('Crypto invoice terms mismatch for invoice %s', invoice_id)
                    continue
                result = process_once(mod, provider='cryptobot', payment_id=invoice_id,
                    provider_charge_id=invoice_id, user_id=user_id, kind='credit_topup',
                    amount=float(Decimal(amount)), currency=asset,
                    metadata={'credits': credits, 'amount_rub': rub, 'invoice_id': invoice_id})
                with connect(path) as con:
                    con.execute("UPDATE crypto_store_invoices SET status='paid' WHERE invoice_id=? AND status='pending'", (invoice_id,))
                if not result.duplicate:
                    try:
                        await bot.send_message(chat_id=user_id, text=f'✅ CryptoBot подтвердил оплату. Начислено: {credits} кредитов.')
                    except Exception:
                        log.warning('Crypto payment notification failed for invoice %s', invoice_id)
            elif status in {'expired', 'cancelled', 'canceled'}:
                with connect(path) as con:
                    con.execute("UPDATE crypto_store_invoices SET status='expired' WHERE invoice_id=? AND status='pending'", (invoice_id,))
        except Exception:
            log.exception('Crypto reconciliation failed for invoice %s', invoice_id)


def register_yoo(path: str, payment_id: str, user_id: int, credits: int, rub: int) -> None:
    payment_id = str(payment_id)
    terms = (int(user_id), int(credits), int(rub))
    if not payment_id or any(value <= 0 for value in terms):
        raise ValueError('Invalid invoice terms')
    _init(path)
    with connect(path) as con:
        con.execute('INSERT OR IGNORE INTO yoo_store_invoices(payment_id,user_id,credits,amount_rub) VALUES (?,?,?,?)', (payment_id, *terms))
        row = con.execute('SELECT user_id,credits,amount_rub FROM yoo_store_invoices WHERE payment_id=?', (payment_id,)).fetchone()
        if tuple(row) != terms:
            raise ValueError('Payment identifier reused with different terms')


async def reconcile_yoo_once(mod: Any, bot: Any, status_fn: Any) -> None:
    path = str(getattr(mod, 'DB_PATH', '') or '')
    _init(path)
    with connect(path) as con:
        rows = con.execute("SELECT payment_id,user_id,credits,amount_rub FROM yoo_store_invoices WHERE status='pending'").fetchall()
    for payment_id, user_id, credits, rub in rows:
        try:
            payment = await status_fn(payment_id) or {}
            status = str(payment.get('status') or '').lower()
            if status == 'succeeded':
                meta, amount = payment.get('metadata') or {}, payment.get('amount') or {}
                expected = {'kind': 'credit_topup', 'user_id': str(user_id), 'credits': str(credits), 'amount_rub': str(rub)}
                if (str(payment.get('id') or '') != payment_id or str(amount.get('currency') or '').upper() != 'RUB'
                    or Decimal(str(amount.get('value') or '0')) != Decimal(rub)
                    or any(str(meta.get(k) or '') != v for k, v in expected.items())):
                    log.error('YooKassa payment terms mismatch for payment %s', payment_id)
                    continue
                result = process_once(mod, provider='yookassa', payment_id=payment_id, user_id=user_id,
                    kind='credit_topup', amount=float(rub), currency='RUB',
                    metadata={'credits': credits, 'amount_rub': rub, 'source': 'direct'})
                with connect(path) as con:
                    con.execute("UPDATE yoo_store_invoices SET status='paid' WHERE payment_id=? AND status='pending'", (payment_id,))
                if not result.duplicate:
                    try:
                        await bot.send_message(chat_id=user_id, text=f'✅ ЮKassa подтвердила оплату. Начислено: {credits} кредитов.')
                    except Exception:
                        log.warning('YooKassa notification failed for payment %s', payment_id)
            elif status in {'canceled', 'cancelled'}:
                with connect(path) as con:
                    con.execute("UPDATE yoo_store_invoices SET status='canceled' WHERE payment_id=? AND status='pending'", (payment_id,))
        except Exception:
            log.exception('YooKassa reconciliation failed for payment %s', payment_id)


async def worker(mod: Any, bot: Any, status_fn: Any) -> None:
    while True:
        try:
            await reconcile_once(mod, bot, status_fn)
            yoo_status = getattr(mod, "_yoo_get_payment", None)
            if callable(yoo_status):
                await reconcile_yoo_once(mod, bot, yoo_status)
        except Exception:
            log.exception('Crypto recovery scan failed')
        await asyncio.sleep(30)
