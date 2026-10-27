import json
import unittest

from neyrobot_prod.studio_menu_navigation import resolve_navigation


class StudioNavigationTests(unittest.TestCase):
    def test_valid(self):
        for route in ("mode:medicine", "mode:study", "mode:work", "engine:images", "engine:kling"):
            self.assertEqual(resolve_navigation(json.dumps({"v": 1, "action": "open_mode", "route": route})), route)

    def test_rejects_untrusted_payloads(self):
        bad = [
            "", "not-json", "[]", "null", "{}", "x" * 513,
            '{"v":true,"action":"open_mode","route":"mode:medicine"}',
            '{"v":1,"action":"open_mode","route":"mode:medicine","medical_data":"private"}',
            '{"v":1,"action":"open_mode","route":"mode:admin"}',
            '{"v":1,"action":"other","route":"mode:medicine"}',
        ]
        for payload in bad:
            with self.subTest(payload=payload[:70]):
                self.assertIsNone(resolve_navigation(payload))


if __name__ == "__main__":
    unittest.main()
