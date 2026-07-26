# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace

from neyrobot_prod import selfie_v208_overlay as v208


class SelfieV208OverlayTests(unittest.TestCase):
    def test_country_catalogue_has_ten_names_per_country(self):
        self.assertEqual(sum(x["country"] == "ru" for x in v208.CHARACTERS.values()), 10)
        self.assertEqual(sum(x["country"] == "us" for x in v208.CHARACTERS.values()), 10)

    def test_reply_keyboard_modes_are_not_reused_as_scenes(self):
        self.assertEqual(v208._mode("🔥 Развлечения"), ("fun", "Развлечения"))
        self.assertEqual(v208._mode("💼 Работа/Бизнес"), ("work", "Работа/Бизнес"))
        self.assertEqual(v208._mode("🩺 Медицина"), ("medicine", "Медицина"))
        self.assertIsNone(v208._mode("селфи на премьере"))

    def test_two_user_photos_are_collected(self):
        context = SimpleNamespace(user_data={})
        self.assertEqual(v208._append_photo(context, b"a" * 2000), 1)
        self.assertEqual(v208._append_photo(context, b"b" * 2000), 2)
        self.assertEqual(len(v208._photos(context)), 2)


if __name__ == "__main__":
    unittest.main()
