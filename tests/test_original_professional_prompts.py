"""Regression tests for the real imported professional prompt collection."""
import unittest
from ai_ad_studio.original_prompt_library import (
    get_original_professional_prompt, list_original_professional_prompts,
)
from ai_ad_studio.heydreaming_original_prompts import ORIGINAL_PROMPTS

class ImportedProfessionalPromptsTests(unittest.TestCase):
    def test_all_52_have_original_text(self):
        entries = list_original_professional_prompts()
        self.assertEqual(len(entries), 52)
        self.assertEqual(len(ORIGINAL_PROMPTS), 52)
        for entry in entries:
            full = get_original_professional_prompt(entry["id"])
            self.assertGreater(len(full["prompt"]), 100, entry["id"])
            self.assertEqual(full["license"], "CC BY 4.0")
            self.assertIn("github.com/LichAmnesia", full["source_repository"])

    def test_no_duplicate_identifiers_or_full_text(self):
        entries = list_original_professional_prompts()
        self.assertEqual(len({e["id"] for e in entries}), 52)
        self.assertEqual(len(set(ORIGINAL_PROMPTS.values())), 52)

    def test_category_filter_and_missing_id(self):
        categories = {e["category"] for e in list_original_professional_prompts()}
        self.assertEqual(len(categories), 10)
        for category in categories:
            self.assertTrue(all(
                e["category"] == category
                for e in list_original_professional_prompts(category)
            ))
        with self.assertRaises(KeyError):
            get_original_professional_prompt("not-an-existing-source-prompt")

if __name__ == "__main__":
    unittest.main()
