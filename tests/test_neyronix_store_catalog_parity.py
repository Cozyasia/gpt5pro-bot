"""Credit store must show the same packages as runtime checkout."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from neyrobot_prod import credit_store_v201 as store

class UnifiedStoreTests(unittest.TestCase):
    def test_default_packages_match_canonical_pricing(self):
        with patch.object(store,"_runtime_module",return_value=None), patch.dict(os.environ,{},clear=True):
            self.assertEqual([(p.credits,p.rub) for p in store.catalog()],
                             [(1000,990),(3000,2790),(7000,6290)])
    def test_active_runtime_catalog_overrides_store_env(self):
        runtime=SimpleNamespace(CREDIT_PACKAGES_RUB={1000:990,3000:2790,7000:6290})
        with patch.object(store,"_runtime_module",return_value=runtime),patch.dict(os.environ,{"CREDIT_PACK_MID_RUB":"2490","CREDIT_PACK_BIG_RUB":"4990"}):
            self.assertEqual([(p.credits,p.rub) for p in store.catalog()],
                             [(1000,990),(3000,2790),(7000,6290)])
            self.assertIsNone(store.resolve_pack(3000,2490))
            self.assertEqual(store.resolve_pack(3000,2790),(3000,2790))
    def test_store_rejects_invalid_runtime_catalog(self):
        with patch.object(store,"_runtime_module",return_value=SimpleNamespace(CREDIT_PACKAGES_RUB={1000:0})):
            with self.assertRaises(ValueError):store.catalog()
if __name__=="__main__":unittest.main()
