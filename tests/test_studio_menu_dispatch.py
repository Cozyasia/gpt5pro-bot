import json
import unittest

from neyrobot_prod.studio_menu_dispatch import navigation_response


class DispatchAdapterTests(unittest.TestCase):
    def test_known_route(self):
        payload = json.dumps({"v": 1, "action": "open_mode", "route": "mode:medicine"})
        self.assertEqual(navigation_response(payload), ("mode:medicine", "Выбран раздел: AI-Медицина"))

    def test_payment_payload_is_never_navigation(self):
        for raw in ('{"action":"buy","tier":"pro"}', '{"type":"topup_rub","amount":1000}',
                    '{"action":"topup_crypto","usd":20}', "action=subscribe&tier=pro"):
            with self.subTest(raw=raw):
                self.assertIsNone(navigation_response(raw))

    def test_rejects_arbitrary_callback(self):
        self.assertIsNone(navigation_response('{"v":1,"action":"open_mode","route":"buywallet:pro:12"}'))


if __name__ == "__main__":
    unittest.main()
