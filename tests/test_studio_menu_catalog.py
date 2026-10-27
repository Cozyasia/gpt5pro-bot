import unittest

from neyrobot_prod.studio_menu_catalog import SECTIONS, verified_callback


class StudioCatalogTests(unittest.TestCase):
    def test_all_sections_unique(self):
        self.assertEqual(len(SECTIONS), 11)
        self.assertEqual(len({x.slug for x in SECTIONS}), 11)

    def test_current_marketplace_route(self):
        self.assertEqual(verified_callback("market"), "ent:brief:product_ad")
        self.assertEqual(verified_callback("advert"), "ent:brief:product_ad")
        self.assertEqual(verified_callback("realty"), "revideo:start")

    def test_unverified_modes_fail_closed(self):
        for slug in ("medicine", "video", "celebrity", "photo", "music", "study", "work", "assistant", "unknown"):
            with self.subTest(slug=slug):
                self.assertIsNone(verified_callback(slug))


if __name__ == "__main__":
    unittest.main()
