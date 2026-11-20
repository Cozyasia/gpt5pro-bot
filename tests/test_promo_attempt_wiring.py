import ast
import asyncio
import contextlib
import logging
import os
import re
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

SOURCE = Path(os.environ.get('PROMO_TEST_SOURCE', Path(__file__).resolve().parents[1] / 'main.py'))

class PromoWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'db')
        with sqlite3.connect(self.db) as con:
            con.execute('CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)')
        def kv_get(key,default=None):
            with sqlite3.connect(self.db) as con:
                row=con.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
                return row[0] if row else default
        def kv_set(key,value):
            with sqlite3.connect(self.db) as con:
                con.execute('INSERT OR REPLACE INTO kv VALUES (?,?)',(key,value))
        if 'PROMO_TEST_SOURCE' in os.environ:
            source = SOURCE.read_text()
        else:
            target = Path(self.tmp.name) / 'main.py'
            target.write_bytes(SOURCE.read_bytes())
            patch = Path(__file__).resolve().parents[1] / 'ops/main_promo_attempts_v1.patch'
            subprocess.run(['patch','--batch','-p1','-i',str(patch)], cwd=self.tmp.name, check=True, stdout=subprocess.DEVNULL)
            source = target.read_text()
        tree=ast.parse(source);names={'_promo_quota_kv_key','_try_consume_promo_daily5_quota','_try_pay_then_do'}
        funcs=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
        self.env={'__name__':'test','DB_PATH':self.db,'re':re,'contextlib':contextlib,'log':logging.getLogger('test'),'_today_ymd':lambda:'2026-11-20','is_promo_daily5_user':lambda *a:True,'_promo_feature_key':lambda *a:'image_to_video_kling','PROMO_DAILY5_PER_FUNCTION_LIMIT':5,'kv_get':kv_get,'kv_set':kv_set,'Update':object,'ContextTypes':SimpleNamespace(DEFAULT_TYPE=object)}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*funcs],type_ignores=[])),str(SOURCE),'exec'),self.env)
        self.update=SimpleNamespace(effective_user=SimpleNamespace(username='test'),effective_message=SimpleNamespace(reply_text=AsyncMock()))
        self.context=SimpleNamespace(user_data={})
    def tearDown(self): self.tmp.cleanup()
    def count(self):
        with sqlite3.connect(self.db) as con:
            row=con.execute('SELECT value FROM kv').fetchone()
            return int(row[0]) if row else 0
    def test_unsuccessful_provider_restores_promo_attempt(self):
        async def provider(): return False
        asyncio.run(self.env['_try_pay_then_do'](self.update,self.context,42,'kling',1,provider,silent_failure=True))
        self.assertEqual(self.count(),0)
    def test_success_consumes_promo_attempt(self):
        async def provider(): return True
        asyncio.run(self.env['_try_pay_then_do'](self.update,self.context,42,'kling',1,provider,silent_failure=True))
        self.assertEqual(self.count(),1)
    def test_exception_restores_promo_attempt(self):
        async def provider(): raise RuntimeError('provider failure')
        asyncio.run(self.env['_try_pay_then_do'](self.update,self.context,42,'kling',1,provider,silent_failure=True))
        self.assertEqual(self.count(),0)
    def test_cancelled_task_keeps_reservation_for_reconciliation(self):
        async def provider(): raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(self.env['_try_pay_then_do'](self.update,self.context,42,'kling',1,provider,silent_failure=True))
        self.assertEqual(self.count(),1)
if __name__ == '__main__': unittest.main()
