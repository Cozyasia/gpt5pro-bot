import unittest
from neyrobot_prod.entertainment.leisure import OPTIONS, suggestions, format_suggestions

class LeisureTests(unittest.TestCase):
    def test_every_category_has_three_distinct_ideas(self):
        for key in OPTIONS:
            title, ideas = suggestions(key)
            self.assertTrue(title)
            self.assertEqual(len(ideas), 3)
            self.assertEqual(len(set(ideas)), 3)

    def test_no_invented_local_businesses(self):
        for key in OPTIONS:
            self.assertIn("без проверки", format_suggestions(key))

    def test_invalid_category_rejected(self):
        with self.assertRaises(KeyError):
            suggestions("unknown")

if __name__ == "__main__":
    unittest.main()
