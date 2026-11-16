"""Regression test for catalog lookup requiring both supplied dimensions to match."""
import ast
import unittest
from pathlib import Path

class PackageResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=Path("main.py").read_text(encoding="utf-8")
        tree=ast.parse(source)
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="_credit_pack_resolve")
        module=ast.Module(body=[node],type_ignores=[])
        cls.fn_namespace={"CREDIT_PACKAGES_RUB":{1000:990,3000:2790,7000:6290}}
        exec(compile(module,"<catalog-resolver>","exec"),cls.fn_namespace)
    def test_matching_pair(self):
        self.assertEqual(self.fn_namespace["_credit_pack_resolve"](1000,990),(1000,990))
    def test_conflicting_pair_rejected(self):
        self.assertIsNone(self.fn_namespace["_credit_pack_resolve"](1000,2790))
    def test_unknown_price_rejected(self):
        self.assertIsNone(self.fn_namespace["_credit_pack_resolve"](1000,1))
    def test_single_dimension_still_supported(self):
        self.assertEqual(self.fn_namespace["_credit_pack_resolve"](0,2790),(3000,2790))
        self.assertEqual(self.fn_namespace["_credit_pack_resolve"](7000,0),(7000,6290))
    def test_no_selector_rejected(self):
        self.assertIsNone(self.fn_namespace["_credit_pack_resolve"](0,0))
if __name__=="__main__":unittest.main()
