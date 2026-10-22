import unittest

from neyrobot_prod.studio_prompt_telegram import category_buttons, template_page, resolve_template_callback


class PromptTelegramTests(unittest.TestCase):
    def test_categories_and_pagination(self):
        self.assertEqual(len(category_buttons()), 10)
        category = "music"
        first = template_page(category, 0)
        second = template_page(category, 1)
        self.assertEqual(len(first["buttons"]), 5)
        self.assertEqual(len(second["buttons"]), 5)
        self.assertIsNone(first["previous"])
        self.assertIsNone(second["next"])
        self.assertEqual(first["next"], "spl:c:music:1")
        self.assertEqual(second["previous"], "spl:c:music:0")
        self.assertTrue(all(len(cb.encode("utf-8")) <= 64 for _, cb in first["buttons"]))

    def test_resolve_and_invalid_callbacks(self):
        callback = template_page("music", 0)["buttons"][0][1]
        item = resolve_template_callback(callback)
        self.assertEqual(item["category"], "music")
        for value in ("spl:p:unknown", "spl:p:studio-001:extra", "other"):
            self.assertIsNone(resolve_template_callback(value))
        with self.assertRaises(ValueError):
            template_page("music", 2)


if __name__ == "__main__":
    unittest.main()
