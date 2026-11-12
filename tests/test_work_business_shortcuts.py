import ast
from pathlib import Path
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main.py"


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


if __name__ == "__main__":
    unittest.main()
