import json
import unittest
from neyrobot_prod.studio_menu_catalog import verified_callback
from neyrobot_prod.studio_menu_navigation import resolve_navigation

class CurrentMainRouteTests(unittest.TestCase):
    def test_verified_routes(self):
        self.assertEqual(verified_callback("market"),"ent:brief:product_ad")
        self.assertEqual(verified_callback("realty"),"revideo:start")
    def test_legacy_routes_rejected(self):
        for route in ("mode:medicine","mode:study","mode:work","engine:images","engine:kling"):
            self.assertIsNone(resolve_navigation(json.dumps({"v":1,"action":"open_mode","route":route})))
    def test_unknown_slugs_disabled(self):
        for slug in ("medicine","study","work","photo","video"):
            self.assertIsNone(verified_callback(slug))
