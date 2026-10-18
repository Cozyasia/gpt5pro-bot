"""Audit source-only video prompt inventory. No synthetic prompts."""
import hashlib
import re
import unittest
from collections import Counter

from ai_ad_studio.original_prompt_library import (
    list_all_imported_originals, get_any_imported_original,
    CALLIRRA_PROMPTS,
)

class SourceLibraryAudit(unittest.TestCase):
    def test_204_complete_source_records(self):
        entries = list_all_imported_originals()
        self.assertEqual(len(entries), 204)
        self.assertEqual(len(CALLIRRA_PROMPTS), 52)
        self.assertEqual(len({e["id"] for e in entries}), len(entries))
        for entry in entries:
            with self.subTest(prompt=entry["id"]):
                full = get_any_imported_original(entry["id"])
                self.assertTrue(entry.get("full_prompt_available"))
                self.assertIsInstance(full["prompt"], str)
                self.assertGreaterEqual(len(full["prompt"].strip()), 60)
                self.assertTrue(full.get("source_url", "").startswith("https://"))
                self.assertTrue(full.get("title", "").strip())

    def test_no_exact_duplicate_prompt_text(self):
        entries = list_all_imported_originals()
        hashes = {}
        for entry in entries:
            prompt = get_any_imported_original(entry["id"])["prompt"]
            normalized = re.sub(r"\s+", " ", prompt).strip().casefold()
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            self.assertNotIn(digest, hashes,
                f"Exact duplicate: {entry['id']} / {hashes.get(digest)}")
            hashes[digest] = entry["id"]

    def test_all_callirra_attributed_and_pending(self):
        for entry in list_all_imported_originals():
            if entry["id"].startswith("CALL-"):
                self.assertEqual(entry["license"], "CC BY 4.0")
                self.assertEqual(entry["publisher"], "Callirra AI")
                self.assertEqual(entry["commercial_review"], "pending")
                self.assertIn("/cases/", entry["source_url"])

if __name__ == "__main__":
    unittest.main()
