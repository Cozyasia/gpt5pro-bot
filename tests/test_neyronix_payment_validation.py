import ast
import pathlib
import unittest

SOURCE=pathlib.Path(__file__).resolve().parents[1]/"neyrobot_prod"/"payments.py"

class PaymentValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=SOURCE.read_text(encoding="utf-8")
        cls.tree=ast.parse(cls.source)
    def test_telegram_currency_gate(self):
        fn=next(n for n in ast.walk(self.tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=="successful_payment_handler")
        self.assertTrue(any(isinstance(n,ast.Raise) and isinstance(n.exc,ast.Call) and isinstance(n.exc.func,ast.Name) and n.exc.func.id=="ValueError" for n in ast.walk(fn)))
        self.assertIn('currency.upper() != "RUB"',ast.get_source_segment(self.source,fn))
    def test_yookassa_subscription_currency_and_amount_gate(self):
        fn=next(n for n in ast.walk(self.tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=="poll_yoo_subscription")
        segment=ast.get_source_segment(self.source,fn)
        self.assertIn('YooKassa subscription currency mismatch',segment)
        self.assertIn('YooKassa subscription amount mismatch',segment)
        self.assertIn('abs(amount - expected) > 0.001',segment)
    def test_yookassa_currency_and_amount_gate(self):
        fn=next(n for n in ast.walk(self.tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=="poll_yoo_credit")
        segment=ast.get_source_segment(self.source,fn)
        self.assertIn('currency mismatch',segment)
        self.assertIn('> 0.001',segment)
if __name__=="__main__": unittest.main()
