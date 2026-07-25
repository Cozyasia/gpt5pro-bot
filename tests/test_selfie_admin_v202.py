# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import types
import unittest

from neyrobot_prod import selfie_admin_v202 as admin


class SelfieAdminV202Tests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(os.environ)
        for name in (
            "OWNER_ID", "SELFIE_ADMIN_IDS", "ADMIN_IDS", "UNLIM_USER_IDS",
            "SELFIE_ADMIN_USERNAMES", "ADMIN_USERNAMES", "UNLIM_USERNAMES",
        ):
            os.environ.pop(name, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)

    def user(self, uid=123, username="sergey"):
        return types.SimpleNamespace(id=uid, username=username)

    def test_owner_id_attribute_is_allowed(self):
        mod = types.SimpleNamespace(OWNER_ID=123)
        self.assertTrue(admin.is_admin(mod, self.user()))

    def test_selfie_admin_ids_environment_is_allowed(self):
        os.environ["SELFIE_ADMIN_IDS"] = "10, 123; 999"
        mod = types.SimpleNamespace(OWNER_ID=0)
        self.assertTrue(admin.is_admin(mod, self.user()))

    def test_unlimited_username_is_allowed(self):
        os.environ["UNLIM_USERNAMES"] = "gpt5pro_support, Sergey"
        mod = types.SimpleNamespace(OWNER_ID=0)
        self.assertTrue(admin.is_admin(mod, self.user(username="sergey")))

    def test_runtime_unlimited_checker_is_allowed(self):
        mod = types.SimpleNamespace(OWNER_ID=0, is_unlimited=lambda uid, username: uid == 123)
        self.assertTrue(admin.is_admin(mod, self.user()))

    def test_denial_is_not_silent_and_shows_setup_value(self):
        mod = types.SimpleNamespace(OWNER_ID=0)
        text = admin._denied_text(mod, self.user(uid=456, username="owner"))
        self.assertIn("Ваш Telegram ID: 456", text)
        self.assertIn("OWNER_ID=456", text)
        self.assertIn("SELFIE_ADMIN_IDS=456", text)


if __name__ == "__main__":
    unittest.main()
