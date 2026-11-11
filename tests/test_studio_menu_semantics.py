import unittest
from pathlib import Path

from neyrobot_prod.studio_menu_catalog import verified_callback


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "studio_menu.html").read_text(encoding="utf-8")


class StudioMenuSemanticContractTests(unittest.TestCase):
    def test_advertising_card_starts_a_video_ad_brief_not_marketplace_intake(self):
        self.assertEqual(verified_callback("advert"), "ent:brief:ugc_ad")

    def test_photo_studio_opens_the_photo_effects_menu(self):
        self.assertEqual(verified_callback("photo"), "ent:menu:photo")

    def test_static_tariffs_and_profile_have_bot_destinations(self):
        self.assertIn("studio_plans", HTML)
        self.assertIn("studio_balance", HTML)

    def test_examples_tab_is_a_real_launcher_not_a_coming_soon_placeholder(self):
        self.assertNotIn("Примеры · скоро", HTML)
        self.assertIn("function showExamples()", HTML)
        for route in ("video", "market", "advert", "photo", "music"):
            with self.subTest(route=route):
                self.assertIn(f"route:'{route}'", HTML)
        self.assertIn("openBot('studio_'+example.route)", HTML)


if __name__ == "__main__":
    unittest.main()
