import ast
import math
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class WalletReservationIntegrityTests(unittest.TestCase):
    def test_direct_debit_respects_reserved_generation(self):
        from test_seedance_aspect_selection import patched_source
        tree = ast.parse(patched_source(include_owner=True))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_wallet_total_take')
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / 'wallet.db')
            with sqlite3.connect(path) as db:
                db.executescript("""CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL);
                CREATE TABLE credit_ledger(user_id INTEGER, retail_usd REAL, status TEXT);
                INSERT INTO wallet VALUES (1, 10);
                INSERT INTO credit_ledger VALUES (1, 8, 'reserved');""")
            env = {'sqlite3': sqlite3, 'math': math, 'DB_PATH': path}
            exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<wallet>', 'exec'), env)
            self.assertFalse(env['_wallet_total_take'](1, 3))
            self.assertFalse(env['_wallet_total_take'](1, float('nan')))
            self.assertTrue(env['_wallet_total_take'](1, 2))
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT usd FROM wallet WHERE user_id=1').fetchone()[0], 8)

    def test_concurrent_debits_cannot_spend_same_available_balance(self):
        from test_seedance_aspect_selection import patched_source
        tree = ast.parse(patched_source(include_owner=True))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_wallet_total_take')
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / 'wallet.db')
            with sqlite3.connect(path) as db:
                db.executescript("""CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL);
                CREATE TABLE credit_ledger(user_id INTEGER, retail_usd REAL, status TEXT);
                INSERT INTO wallet VALUES (1, 10);
                INSERT INTO credit_ledger VALUES (1, 8, 'reserved');""")
            env = {'sqlite3': sqlite3, 'math': math, 'DB_PATH': path}
            exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<wallet>', 'exec'), env)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: env['_wallet_total_take'](1, 2), range(2)))
            self.assertEqual(sorted(results), [False, True])
