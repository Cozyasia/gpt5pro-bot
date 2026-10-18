import unittest
from neyrobot_prod.entertainment.leisure import OPTIONS, PREFERENCES, personalized

class LeisurePersonalizationTests(unittest.TestCase):
    def test_every_category_and_interest(self):
        for category in OPTIONS:
            for interest in PREFERENCES:
                result = personalized(category, interest, participants=3, budget=1500)
                self.assertIn("Участников: 3", result)
                self.assertIn("1500", result)
                self.assertIn("1.", result)
    def test_invalid_preferences(self):
        with self.assertRaises(ValueError):
            personalized("home", "calm", participants=0)
        with self.assertRaises(ValueError):
            personalized("home", "calm", budget=-1)
if __name__ == "__main__":
    unittest.main()
