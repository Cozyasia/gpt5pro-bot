"""Checks for the unified 100 imported, non-generated source prompts."""
import unittest
from ai_ad_studio.original_prompt_library import (
    list_full_source_prompts, get_full_source_prompt,
)

class UnifiedSourceLibraryTests(unittest.TestCase):
    def test_one_hundred_original_prompt_texts(self):
        entries = list_full_source_prompts()
        self.assertEqual(len(entries), 100)
        self.assertEqual(len({entry["id"] for entry in entries}), 100)
        for entry in entries:
            prompt = get_full_source_prompt(entry["id"])
            self.assertTrue(prompt["prompt"].strip(), entry["id"])
            self.assertTrue(prompt["source_url"].startswith("https://"), entry["id"])

    def test_missing_prompt_raises(self):
        with self.assertRaises(KeyError):
            get_full_source_prompt("NOT-FOUND")

if __name__ == "__main__":
    unittest.main()
