"""Validation of the expanded source-original library."""
import unittest
from ai_ad_studio.original_prompt_library import (
    list_all_imported_originals, get_any_imported_original,
)

class ExpandedSourceLibraryTests(unittest.TestCase):
    def test_152_full_texts_and_unique_ids(self):
        entries = list_all_imported_originals()
        self.assertEqual(len(entries), 152)
        self.assertEqual(len({e["id"] for e in entries}), 152)
        for entry in entries:
            original = get_any_imported_original(entry["id"])
            self.assertTrue(original["prompt"].strip())
            self.assertTrue(original["source_url"].startswith("https://"))

    def test_new_source_prompts_pending_review(self):
        new_entries = [e for e in list_all_imported_originals()
                       if e.get("commercial_review") == "pending"]
        self.assertEqual(len(new_entries), 52)

if __name__ == "__main__":
    unittest.main()
