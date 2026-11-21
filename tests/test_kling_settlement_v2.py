import sqlite3, tempfile, unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from neyrobot_prod import jobs

try:
    from neyrobot_prod import kling_settlement_v2 as settlement
except ImportError:
    settlement = None

class SettlementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.db=str(Path(self.temp.name)/'db.sqlite')
        from types import SimpleNamespace
        self.mod=SimpleNamespace(DB_PATH=self.db)
        self.job=jobs.begin_job(self.mod,user_id=10,chat_id=20,feature='video_generation',provider='kling',provider_task_id='provider1')
        with sqlite3.connect(self.db) as con:
            con.executescript('''CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL); CREATE TABLE credit_ledger(tx_id TEXT PRIMARY KEY,user_id INTEGER,retail_usd REAL,status TEXT,updated_ts INTEGER); CREATE TABLE kv(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE promo_attempts(token TEXT PRIMARY KEY,quota_key TEXT,status TEXT); INSERT INTO wallet VALUES (10, 10); INSERT INTO credit_ledger VALUES ('tx',10,2,'reserved',0); INSERT INTO kv VALUES ('promo5:10:20261121:kling','1'); INSERT INTO promo_attempts VALUES ('p','promo5:10:20261121:kling','reserved');''')
    def tearDown(self): self.temp.cleanup()
    def test_paid_delivery_is_charged_only_once(self):
        self.assertIsNotNone(settlement)
        settlement.link(self.db,self.job,10,'credit','tx')
        with ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(lambda _: settlement.finalize(self.db,self.job,'delivered'),range(2)))
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT usd FROM wallet').fetchone()[0],8)
            self.assertEqual(c.execute('SELECT status FROM credit_ledger').fetchone()[0],'charged')
    def test_uncertain_delivery_retains_reservation(self):
        self.assertIsNotNone(settlement)
        settlement.link(self.db,self.job,10,'credit','tx')
        settlement.finalize(self.db,self.job,'unknown')
        with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT status FROM credit_ledger').fetchone()[0],'reserved')
    def test_promo_failure_returns_once(self):
        self.assertIsNotNone(settlement)
        settlement.link(self.db,self.job,10,'promo','p')
        settlement.finalize(self.db,self.job,'failed');settlement.finalize(self.db,self.job,'failed')
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT value FROM kv').fetchone()[0],'0')
            self.assertEqual(c.execute('SELECT status FROM promo_attempts').fetchone()[0],'released')
    def test_cannot_attach_another_users_credit(self):
        self.assertIsNotNone(settlement)
        with self.assertRaises(ValueError):settlement.link(self.db,self.job,11,'credit','tx')

    def test_conflicting_terminal_outcome_is_rejected(self):
        settlement.link(self.db,self.job,10,'credit','tx')
        settlement.finalize(self.db,self.job,'delivered')
        with self.assertRaises(ValueError): settlement.finalize(self.db,self.job,'failed')
        with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT usd FROM wallet').fetchone()[0],8)
    def test_insufficient_wallet_does_not_finalize(self):
        settlement.link(self.db,self.job,10,'credit','tx')
        with sqlite3.connect(self.db) as c:c.execute('UPDATE wallet SET usd=1')
        with self.assertRaises(ValueError):settlement.finalize(self.db,self.job,'delivered')
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT status FROM credit_ledger').fetchone()[0],'reserved')
            self.assertEqual(c.execute('SELECT outcome FROM kling_job_finance').fetchone()[0],'pending')
    def test_promo_delivery_keeps_quota_and_marks_used(self):
        settlement.link(self.db,self.job,10,'promo','p')
        settlement.finalize(self.db,self.job,'delivered')
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT value FROM kv').fetchone()[0],'1')
            self.assertEqual(c.execute('SELECT status FROM promo_attempts').fetchone()[0],'used')
    def test_normal_paid_charge_can_be_reconciled_after_restart(self):
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE credit_ledger SET status='charged' WHERE tx_id='tx'")
            c.execute('UPDATE wallet SET usd=8 WHERE user_id=10')
        settlement.link(self.db,self.job,10,'credit','tx')
        settlement.finalize(self.db,self.job,'delivered')
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT usd FROM wallet').fetchone()[0],8)
            self.assertEqual(c.execute('SELECT outcome FROM kling_job_finance').fetchone()[0],'delivered')
    def test_normal_promo_use_can_be_reconciled_after_restart(self):
        with sqlite3.connect(self.db) as c:c.execute("UPDATE promo_attempts SET status='used' WHERE token='p'")
        settlement.link(self.db,self.job,10,'promo','p')
        settlement.finalize(self.db,self.job,'delivered')
        with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT value FROM kv').fetchone()[0],'1')
    def test_recovery_finalizes_paid_reservation_after_delivery(self):
        from neyrobot_prod.jobs import settle_job_finance
        job={'job_id':self.job,'user_id':10,'payload':{'finance':{'kind':'credit','reference':'tx','user_id':10}}}
        self.assertTrue(settle_job_finance(self.mod,job,'delivered'))
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT usd FROM wallet').fetchone()[0],8)
            self.assertEqual(c.execute('SELECT status FROM credit_ledger').fetchone()[0],'charged')
    def test_recovery_refuses_finance_from_another_user(self):
        from neyrobot_prod.jobs import settle_job_finance
        job={'job_id':self.job,'user_id':10,'payload':{'finance':{'kind':'credit','reference':'tx','user_id':11}}}
        with self.assertRaises(ValueError):settle_job_finance(self.mod,job,'delivered')
