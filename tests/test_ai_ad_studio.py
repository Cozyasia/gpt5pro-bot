import unittest
from ai_ad_studio import TEMPLATES, ProductBrief, build_storyboard, list_templates

class TestAdStudio(unittest.TestCase):
    def test_catalog_has_one_hundred_unique_templates(self):
        self.assertEqual(len(TEMPLATES), 100)
        self.assertEqual(len({t.id for t in TEMPLATES}), 100)

    def test_brand_neutral_storyboard(self):
        brief = ProductBrief("My Fragrance", "Amber perfume in a square bottle", ("photo1",))
        result = build_storyboard("fragrance-001", brief)
        self.assertEqual(result["product_name"], "My Fragrance")
        self.assertEqual(result["shots"][-1]["end"], 30)
        self.assertEqual(result["status"], "storyboard_only")
        self.assertNotIn("Chanel", str(result))

    def test_rejects_missing_reference(self):
        with self.assertRaises(ValueError):
            build_storyboard("fragrance-001", ProductBrief("A", "B", ()))

    def test_category_filter(self):
        self.assertEqual(len(list_templates("fragrance")), 15)

if __name__ == "__main__":
    unittest.main()
