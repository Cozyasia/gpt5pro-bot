import json
import unittest
from neyrobot_prod.studio_menu_catalog import verified_callback
from neyrobot_prod.studio_menu_navigation import resolve_navigation

class CurrentMainRouteTests(unittest.TestCase):
    def test_verified_routes(self):
        self.assertEqual(verified_callback("medicine"),"mode:medicine")
        self.assertEqual(verified_callback("study"),"mode:study")
        self.assertEqual(verified_callback("work"),"mode:work")
        self.assertEqual(verified_callback("photo"),"ent:menu:photo")
        self.assertEqual(verified_callback("video"),"act:fun:textvideo")
    def test_legacy_routes_rejected(self):
        for route in ("mode:medicine","mode:study","mode:work","engine:images","engine:kling"):
            self.assertIsNone(resolve_navigation(json.dumps({"v":1,"action":"open_mode","route":route})))
    def test_unknown_slugs_disabled(self):
        self.assertIsNone(verified_callback("admin"))
