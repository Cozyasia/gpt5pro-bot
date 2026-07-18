# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

from neyrobot_prod.db import backup_database, connect, init_schema, install_sqlite_hardening
from neyrobot_prod.medical_followup import STANDARD_DISCLAIMER, dedupe_disclaimer, offer, patch_runtime as patch_medical
from neyrobot_prod.payment_guard import expected_invoice, precheckout_handler
from neyrobot_prod.payments import process_once


class FakeMessage:
    def __init__(self):
        self.calls = []

    async def reply_text(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return types.SimpleNamespace(message_id=len(self.calls), chat=types.SimpleNamespace(id=1))


class FakeContext:
    def __init__(self):
        self.user_data = {}


class FakeUpdate:
    def __init__(self, user_id=1, username="tester"):
        self.effective_user = types.SimpleNamespace(id=user_id, username=username)
        self.effective_message = FakeMessage()
        self.effective_chat = types.SimpleNamespace(id=100)
        self.message = types.SimpleNamespace()


class CoreDatabaseTests(unittest.TestCase):
    def test_sqlite_wal_schema_and_backup(self):
        with tempfile.TemporaryDirectory() as td:
            db = str(Path(td) / "subs.db")
            install_sqlite_hardening()
            init_schema(db)
            con = connect(db)
            try:
                journal = str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                con.close()
            self.assertEqual(journal, "wal")
            self.assertIn("payment_events", tables)
            self.assertIn("durable_jobs", tables)

            key = Path(td) / ".medical_card_fernet.key"
            key.write_text("test-key", encoding="utf-8")
            result = backup_database(db, str(Path(td) / "backups"), key_paths=(str(key),), retention=3)
            self.assertTrue(result["ok"])
            self.assertTrue(Path(result["db"]).exists())
            self.assertEqual(len(result["keys"]), 1)


class PaymentTests(unittest.TestCase):
    def _mod(self, db: str):
        return types.SimpleNamespace(
            DB_PATH=db,
            SUBS_TIERS={
                "start": {"rub": 599},
                "pro": {"rub": 1990},
                "ultimate": {"rub": 4990},
            },
            SUBSCRIPTION_CREDITS={"start": 200, "pro": 1200, "ultimate": 3500},
            USD_RUB=100,
            _credits_to_usd=lambda credits: float(credits) / 100.0,
            _credit_pack_resolve=lambda credits, rub: (credits, rub) if (credits, rub) in {(1000, 990), (3000, 2790)} else None,
        )

    def test_subscription_is_atomic_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            db = str(Path(td) / "subs.db")
            mod = self._mod(db)
            first = process_once(
                mod,
                provider="yookassa",
                payment_id="pay-1",
                user_id=42,
                kind="subscription",
                amount=1990,
                currency="RUB",
                metadata={"tier": "pro", "months": 1},
            )
            duplicate = process_once(
                mod,
                provider="yookassa",
                payment_id="pay-1",
                user_id=42,
                kind="subscription",
                amount=1990,
                currency="RUB",
                metadata={"tier": "pro", "months": 1},
            )
            self.assertTrue(first.processed)
            self.assertEqual(first.credits, 1200)
            self.assertTrue(duplicate.duplicate)
            con = sqlite3.connect(db)
            try:
                row = con.execute("SELECT tier, until_ts FROM subscriptions WHERE user_id=42").fetchone()
                wallet = con.execute("SELECT usd FROM wallet WHERE user_id=42").fetchone()[0]
                events = con.execute("SELECT COUNT(*) FROM payment_events WHERE provider='yookassa'").fetchone()[0]
            finally:
                con.close()
            self.assertEqual(row[0], "pro")
            self.assertGreater(row[1], 0)
            self.assertAlmostEqual(wallet, 12.0)
            self.assertEqual(events, 1)

    def test_provider_charge_is_unique(self):
        with tempfile.TemporaryDirectory() as td:
            mod = self._mod(str(Path(td) / "subs.db"))
            first = process_once(
                mod, provider="telegram", payment_id="provider-1", provider_charge_id="tg-1",
                user_id=7, kind="credit_topup", amount=990, currency="RUB",
                metadata={"credits": 1000},
            )
            second = process_once(
                mod, provider="telegram", payment_id="provider-2", provider_charge_id="tg-1",
                user_id=7, kind="credit_topup", amount=990, currency="RUB",
                metadata={"credits": 1000},
            )
            self.assertTrue(first.processed)
            self.assertTrue(second.duplicate)

    def test_precheckout_uses_legacy_discount_table_when_available(self):
        with tempfile.TemporaryDirectory() as td:
            mod = self._mod(str(Path(td) / "subs.db"))
            mod._plan_payload_and_amount = lambda tier, months: (f"sub:{tier}:{months}", 2799, "PRO quarter")
            self.assertEqual(expected_invoice(mod, "sub:pro:3"), ("RUB", 279900))

    def test_precheckout_rejects_stale_amount(self):
        with tempfile.TemporaryDirectory() as td:
            mod = self._mod(str(Path(td) / "subs.db"))
            answers = []

            class Q:
                invoice_payload = "sub:pro:1"
                currency = "RUB"
                total_amount = 100

                async def answer(self, **kwargs):
                    answers.append(kwargs)

            update = types.SimpleNamespace(pre_checkout_query=Q())
            asyncio.run(precheckout_handler(mod, update, types.SimpleNamespace()))
            self.assertEqual(answers[-1]["ok"], False)


class MedicalFollowupTests(unittest.TestCase):
    def setUp(self):
        self.old_card = sys.modules.get("medical_card_v109_patch")
        self.old_runtime = sys.modules.get("medical_v111_runtime")

    def tearDown(self):
        if self.old_card is None:
            sys.modules.pop("medical_card_v109_patch", None)
        else:
            sys.modules["medical_card_v109_patch"] = self.old_card
        if self.old_runtime is None:
            sys.modules.pop("medical_v111_runtime", None)
        else:
            sys.modules["medical_v111_runtime"] = self.old_runtime

    @staticmethod
    def _card(entitled: bool):
        card = types.ModuleType("medical_card_v109_patch")
        card._eligible = lambda mod, user: entitled
        card._auto_save = lambda mod, uid: False
        card._has_consent = lambda mod, uid: False
        card._pending_save_kb = lambda mod, uid: "save-kb"
        card._kb = lambda mod, rows: rows
        card._card_main_kb = lambda mod: "card-kb"
        card._save_pending = None
        return card

    def test_entitled_account_gets_save_prompt(self):
        card = self._card(True)
        sys.modules["medical_card_v109_patch"] = card
        mod = types.SimpleNamespace(OWNER_ID=0, is_unlimited=lambda uid, username: False)
        update = FakeUpdate()
        context = FakeContext()
        context.user_data["medcard_pending"] = {
            "track": "med_labs", "source_type": "document", "filename": "a.pdf",
            "mime_type": "application/pdf", "created_ts": 1, "file_bytes": b"pdf", "analysis": "ok",
        }
        asyncio.run(offer(mod, update, context))
        self.assertIn("Сохранить оригинал", update.effective_message.calls[-1][0])
        self.assertEqual(update.effective_message.calls[-1][1]["reply_markup"], "save-kb")
        self.assertIn("medcard_pending", context.user_data)

    def test_free_account_gets_upsell_and_raw_pending_is_cleared(self):
        card = self._card(False)
        sys.modules["medical_card_v109_patch"] = card
        mod = types.SimpleNamespace(OWNER_ID=0, is_unlimited=lambda uid, username: False)
        update = FakeUpdate(user_id=9)
        context = FakeContext()
        context.user_data["medcard_pending"] = {
            "track": "med_labs", "source_type": "document", "filename": "a.pdf",
            "mime_type": "application/pdf", "created_ts": 2, "file_bytes": b"sensitive", "analysis": "ok",
        }
        asyncio.run(offer(mod, update, context))
        self.assertIn("PRO или ULTIMATE", update.effective_message.calls[-1][0])
        self.assertNotIn("medcard_pending", context.user_data)

    def test_public_handlers_are_forced_to_structured_runtime(self):
        card = self._card(True)
        runtime = types.ModuleType("medical_v111_runtime")
        calls = []

        async def analyze(mod, update, context, value, goal, is_image):
            calls.append((value, goal, is_image))

        async def send_answer(mod, update, context, answer):
            return None

        runtime.analyze = analyze
        runtime._send_answer = send_answer
        sys.modules["medical_card_v109_patch"] = card
        sys.modules["medical_v111_runtime"] = runtime
        mod = types.SimpleNamespace(
            BOT_TOKEN="token",
            _medical_analyze_text=lambda *a, **k: None,
            _medical_analyze_image=lambda *a, **k: None,
        )
        self.assertTrue(patch_medical(mod))
        self.assertTrue(getattr(mod._medical_analyze_text, "_prod_v119_medical", False))
        asyncio.run(mod._medical_analyze_text(FakeUpdate(), FakeContext(), "source", "goal"))
        self.assertEqual(calls[-1], ("source", "goal", False))

    def test_disclaimer_is_not_duplicated(self):
        answer = "Результат анализа.\n\nЭто справочный разбор и не заменяет врача.\n\nЕщё один вывод."
        cleaned = dedupe_disclaimer(answer)
        self.assertEqual(cleaned.count(STANDARD_DISCLAIMER), 1)
        self.assertIn("Результат анализа", cleaned)
        self.assertIn("Ещё один вывод", cleaned)


if __name__ == "__main__":
    unittest.main()
