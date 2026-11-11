import unittest

from neyrobot_prod.studio_menu_shortcuts import resolve_shortcut


class StudioStartShortcutTests(unittest.TestCase):
    def test_plans_and_balance_have_dedicated_safe_deep_links(self):
        self.assertEqual(resolve_shortcut(["studio_plans"]), "plans")
        self.assertEqual(resolve_shortcut(["studio_balance"]), "balance")

    def test_unrelated_start_payload_is_not_claimed(self):
        for args in ([], ["studio_market"], ["pay_sub_pro"], ["studio_plans", "extra"], None):
            with self.subTest(args=args):
                self.assertIsNone(resolve_shortcut(args))


if __name__ == "__main__":
    unittest.main()
