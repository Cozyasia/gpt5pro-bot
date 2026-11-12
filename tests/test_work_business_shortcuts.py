import ast
from pathlib import Path
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main.py"
CATALOG = Path(__file__).resolve().parents[1] / "neyrobot_prod" / "entertainment" / "catalog.py"
PRODUCTION = Path(__file__).resolve().parents[1] / "neyrobot_prod" / "entertainment" / "production.py"


class WorkBusinessShortcutsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MAIN.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_work_menu_reuses_working_marketplace_and_ugc_briefs(self):
        fn = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_mode_kb"
        )
        body = ast.get_source_segment(self.source, fn)
        self.assertIn('InlineKeyboardButton("🛍 Маркетплейсы", callback_data="ent:brief:product_ad")', body)
        self.assertIn('InlineKeyboardButton("📱 UGC-реклама", callback_data="ent:brief:ugc_ad")', body)
        self.assertIn('InlineKeyboardButton("🏡 Реклама недвижимости", callback_data="ent:brief:real_estate_ad")', body)

    def test_real_estate_ad_has_the_same_clear_label_in_both_menus(self):
        self.assertIn('(_button("🏡 Реклама недвижимости", "ent:brief:real_estate_ad"),)', CATALOG.read_text(encoding="utf-8"))
        self.assertIn('"real_estate_ad": ("🏡 Реклама недвижимости"', PRODUCTION.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
