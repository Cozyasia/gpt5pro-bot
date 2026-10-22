import unittest

from neyrobot_prod.studio_prompt_library import (
    list_prompt_categories, list_prompt_templates, get_prompt_template
)


class PromptLibraryTests(unittest.TestCase):
    def test_100_unique_original_templates(self):
        items = list_prompt_templates()
        self.assertEqual(len(items), 100)
        self.assertEqual(len({x["id"] for x in items}), 100)
        self.assertTrue(all(x["source"] == "original" for x in items))
        self.assertTrue(all(x["prompt"].strip() for x in items))

    def test_category_filter_and_lookup(self):
        cats = list_prompt_categories()
        self.assertEqual(len(cats), 10)
        self.assertEqual(sum(x["count"] for x in cats), 100)
        for cat in cats:
            items = list_prompt_templates(cat["id"])
            self.assertEqual(len(items), 10)
            self.assertEqual(get_prompt_template(items[0]["id"])["id"], items[0]["id"])
        self.assertIsNone(get_prompt_template("missing"))


if __name__ == "__main__":
    unittest.main()
