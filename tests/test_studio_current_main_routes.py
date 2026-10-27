"""Tests for Studio navigation handoff using current-main production routes."""
import json
import unittest
from unittest.mock import patch

from neyrobot_prod.studio_menu_catalog import verified_callback
from neyrobot_prod.studio_menu_navigation import resolve_navigation


class CurrentMainRouteTests(unittest.TestCase):
    def test_marketplace_and_realty_current_routes(self):
        self.assertEqual(verified_callback("market"), "ent:brief:product_ad")
        self.assertEqual(verified_callback("realty"), "revideo:start")

    def test_legacy_routes_not_assumed_current(self):
        for route in ("mode:medicine", "mode:study", "mode:work", "engine:images", "engine:kling"):
            self.assertIsNotNone(resolve_navigation(json.dumps({
                "v": 1, "action": "open_mode", "route": route
            })))
        # A recognized payload is NOT proof of a current-main callback.
        for slug in ("medicine", "study", "work", "photo", "video"):
            self.assertIsNone(verified_callback(slug))

    def test_catalog_does_not_dispatch(self):
        with patch("neyrobot_prod.studio_menu_catalog.verified_callback", return_value=None):
            self.assertIsNone(verified_callback("medicine"))


if __name__ == "__main__":
    unittest.main()
