import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from neyrobot_prod.promo_attempts_v1 import reserve, finish

class PromoAttemptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'quota.db')
        with sqlite3.connect(self.path) as con:
            con.execute('CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)')
        self.key = 'promo5:42:2026-11-20:image_to_video_kling'
    def tearDown(self):
        self.tmp.cleanup()
    def count(self, key=None):
        with sqlite3.connect(self.path) as con:
            row = con.execute('SELECT value FROM kv WHERE key=?', (key or self.key,)).fetchone()
            return int(row[0]) if row else 0
    def test_failed_attempt_returns_one_slot_once(self):
        token, left = reserve(self.path, self.key, 5)
        self.assertEqual((left,self.count()), (4,1))
        self.assertTrue(finish(self.path,token,success=False))
        self.assertFalse(finish(self.path,token,success=False))
        self.assertEqual(self.count(),0)
    def test_success_keeps_slot_and_cannot_be_released(self):
        token,_ = reserve(self.path,self.key,5)
        self.assertTrue(finish(self.path,token,success=True))
        self.assertFalse(finish(self.path,token,success=False))
        self.assertEqual(self.count(),1)
    def test_release_targets_original_day(self):
        old,_=reserve(self.path,self.key,5)
        tomorrow=self.key.replace('2026-11-20','2026-11-21')
        reserve(self.path,tomorrow,5)
        finish(self.path,old,success=False)
        self.assertEqual((self.count(),self.count(tomorrow)),(0,1))
    def test_concurrent_reservations_cannot_exceed_limit(self):
        with ThreadPoolExecutor(max_workers=10) as pool:
            items=list(pool.map(lambda _: reserve(self.path,self.key,5),range(20)))
        self.assertEqual(sum(token is not None for token,_ in items),5)
        self.assertEqual(self.count(),5)
    def test_existing_usage_counts_toward_limit(self):
        with sqlite3.connect(self.path) as con:
            con.execute('INSERT INTO kv VALUES(?,?)',(self.key,'4'))
        token,left=reserve(self.path,self.key,5)
        self.assertEqual((bool(token),left,self.count()),(True,0,5))
        token,left=reserve(self.path,self.key,5)
        self.assertEqual((token,left,self.count()),(None,0,5))
if __name__ == '__main__': unittest.main()
