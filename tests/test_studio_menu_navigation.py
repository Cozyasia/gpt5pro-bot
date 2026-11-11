import json
import unittest
from neyrobot_prod.studio_menu_navigation import resolve_navigation

class StudioNavigationTests(unittest.TestCase):
    def test_verified_routes(self):
        expected_routes = {
            "medicine": "mode:medicine",
            "video": "act:fun:textvideo",
            "market": "ent:brief:product_ad",
            "celebrity": "fun:aiselfie",
            "realty": "revideo:start",
            "photo": "ent:menu:photo",
            "music": "fun:music",
            "study": "mode:study",
            "work": "mode:work",
            "assistant": "mode:root",
            "advert": "ent:brief:ugc_ad",
        }
        for slug, expected in expected_routes.items():
            self.assertEqual(resolve_navigation(json.dumps({"v": 1, "action": "open_mode", "route": slug})), expected)

    def test_rejects_untrusted_payloads(self):
        for raw in ("", "not-json", "[]", "null", "{}", "x"*513, '{"v":true,"action":"open_mode","route":"market"}', '{"v":1,"action":"open_mode","route":"market","tier":"pro"}', '{"v":1,"action":"open_mode","route":"mode:medicine"}', '{"v":1,"action":"other","route":"market"}'):
            with self.subTest(raw=raw[:70]):
                self.assertIsNone(resolve_navigation(raw))
