"""Tests for read-only catalog listing and retrieval."""
import unittest
from ai_ad_studio.source_catalog_api import (
    search_original_prompts, get_prompt_for_display,
)

class SourceCatalogApiTests(unittest.TestCase):
    def test_total_and_pagination(self):
        first = search_original_prompts(page=1, page_size=10)
        second = search_original_prompts(page=2, page_size=10)
        self.assertEqual(first["total"], 152)
        self.assertEqual(len(first["items"]), 10)
        self.assertEqual(len(second["items"]), 10)
        self.assertTrue(
            {x["id"] for x in first["items"]}.isdisjoint(
                {x["id"] for x in second["items"]}
            )
        )

    def test_commercial_review_filter(self):
        result = search_original_prompts(reviewed_only=True, page_size=50)
        self.assertEqual(result["total"], 100)

    def test_search_and_original_text(self):
        results = search_original_prompts("serum")
        self.assertGreater(results["total"], 0)
        original = get_prompt_for_display(results["items"][0]["id"])
        self.assertTrue(original["prompt"])
        self.assertTrue(original["source_url"].startswith("https://"))

    def test_invalid_page(self):
        with self.assertRaises(ValueError):
            search_original_prompts(page=0)

if __name__ == "__main__":
    unittest.main()
