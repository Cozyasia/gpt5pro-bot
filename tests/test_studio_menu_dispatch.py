import json
import unittest
from neyrobot_prod.studio_menu_dispatch import navigation_response

class DispatchAdapterTests(unittest.TestCase):
    def test_known_route(self):
        raw=json.dumps({"v":1,"action":"open_mode","route":"market"})
        self.assertEqual(navigation_response(raw),("ent:brief:product_ad","Выбран раздел: Маркетплейсы"))
    def test_payment_payload_is_never_navigation(self):
        for raw in ('{"action":"buy","tier":"pro"}','{"type":"topup_rub","amount":1000}','{"action":"topup_crypto","usd":20}',"action=subscribe&tier=pro"):
            self.assertIsNone(navigation_response(raw))
    def test_rejects_arbitrary_callback(self):
        self.assertIsNone(navigation_response('{"v":1,"action":"open_mode","route":"buywallet:pro:12"}'))
