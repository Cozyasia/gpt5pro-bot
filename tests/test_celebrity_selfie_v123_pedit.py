# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class CelebritySelfieV123PeditTests(unittest.TestCase):
    def test_photo_quick_action_is_routed_to_exact_wizard(self):
        source = Path("celebrity_selfie_v123_pedit.py").read_text(encoding="utf-8")
        self.assertIn('data != "pedit:aiselfie"', source)
        self.assertIn('pattern=r"^pedit:aiselfie$"', source)
        self.assertIn("await flow._open_entry(update, context)", source)
        self.assertIn("group=-10001", source)
        self.assertNotIn("edit_message_text", source)


if __name__ == "__main__":
    unittest.main()
