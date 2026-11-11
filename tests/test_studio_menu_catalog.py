import unittest

from neyrobot_prod.studio_menu_catalog import SECTIONS, verified_callback


class StudioCatalogTests(unittest.TestCase):
    EXPECTED = {
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

    def test_all_sections_unique(self):
        self.assertEqual(len(SECTIONS), 11)
        self.assertEqual(len({x.slug for x in SECTIONS}), 11)

    def test_every_catalog_card_has_a_verified_current_callback(self):
        self.assertEqual(
            {section.slug: section.callback for section in SECTIONS},
            self.EXPECTED,
        )
        for slug, callback in self.EXPECTED.items():
            with self.subTest(slug=slug):
                self.assertEqual(verified_callback(slug), callback)

    def test_unknown_mode_fails_closed(self):
        self.assertIsNone(verified_callback("unknown"))

    def test_distinct_user_promises_do_not_share_a_workflow(self):
        """Marketplace cards and product commercials start different jobs."""
        callbacks = {section.slug: section.callback for section in SECTIONS}
        self.assertNotEqual(callbacks["market"], callbacks["advert"])


if __name__ == "__main__":
    unittest.main()
