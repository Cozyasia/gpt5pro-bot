# -*- coding: utf-8 -*-
import unittest

from presentation_relaxed_v121 import assess_project


class PresentationRelaxedBriefTests(unittest.TestCase):
    def test_optional_commercial_sections_do_not_block(self):
        project = {
            "raw_brief": "Подробный бриф " * 40,
            "structure": [{"title": f"Слайд {i}"} for i in range(1, 13)],
            "profile": {
                "brand_name": "NEYRO-BOT GPT 5 STUDIO",
                "contacts": ["@NeyroBotSupport"],
                "prices": ["499 ₽", "1 299 ₽", "2 990 ₽"],
            },
        }
        result = assess_project(project)
        self.assertTrue(result["ready"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["slide_count"], 12)

    def test_one_contact_is_enough(self):
        project = {
            "raw_brief": "Описание продукта и цели. " * 10,
            "structure": [{} for _ in range(8)],
            "profile": {"contacts": ["@support"]},
        }
        result = assess_project(project)
        self.assertTrue(result["ready"])
        self.assertFalse(any("контакт" in item for item in result["warnings"]))

    def test_only_structural_failures_block(self):
        result = assess_project({"raw_brief": "коротко", "structure": [], "profile": {}})
        self.assertFalse(result["ready"])
        self.assertEqual(len(result["blockers"]), 2)


if __name__ == "__main__":
    unittest.main()
