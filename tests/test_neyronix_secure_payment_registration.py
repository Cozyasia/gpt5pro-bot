"""Static integration guard for secure payment registration."""
import ast
import unittest
from pathlib import Path

class PaymentRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree=ast.parse(Path("main.py").read_text(encoding="utf-8"))
        cls.build=next(n for n in cls.tree.body if isinstance(n,ast.FunctionDef) and n.name=="build_application")
    def test_explicit_feature_gate(self):
        source=ast.get_source_segment(Path("main.py").read_text(encoding="utf-8"),self.build)
        self.assertIn("NEYRONIX_SECURE_PAYMENTS_ENABLED",source)
        self.assertIn("if not patch_runtime(_payment_module):",source)
        self.assertIn("raise RuntimeError",source)
    def test_secure_handlers_registered_instead_of_legacy(self):
        source=ast.get_source_segment(Path("main.py").read_text(encoding="utf-8"),self.build)
        self.assertIn("PreCheckoutQueryHandler(_payment_precheckout_handler)",source)
        self.assertIn("filters.SUCCESSFUL_PAYMENT, _payment_successful_handler",source)
        self.assertIn("_payment_successful_handler = _payment_module.on_successful_payment",source)
if __name__=="__main__":unittest.main()
