import ast
from pathlib import Path
import unittest

MAIN = Path(__file__).resolve().parents[1] / "main.py"

class ContextualReplyKeyboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MAIN.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_mode_menu_hides_reply_keyboard(self):
        fn = next(n for n in self.tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_send_mode_menu")
        body = ast.get_source_segment(self.source, fn)
        self.assertIn("ReplyKeyboardRemove()", body)
        self.assertIn("reply_markup=kb", body)

    def test_back_restores_main_keyboard(self):
        fn = next(n for n in self.tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_mode_cb")
        body = ast.get_source_segment(self.source, fn)
        self.assertIn('data == "mode:root"', body)
        self.assertIn("reply_markup=ReplyKeyboardRemove()", body)

    def test_start_keeps_main_keyboard(self):
        fn = next(n for n in self.tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "cmd_start")
        self.assertIn("reply_markup=main_kb", ast.get_source_segment(self.source, fn))

    def test_root_has_all_main_actions(self):
        fn = next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == "modes_root_kb")
        body = ast.get_source_segment(self.source, fn)
        for label in ("Учёба", "Работа/Бизнес", "Развлечения", "Медицина",
                      "Мои чаты", "Новый чат", "Движки", "Баланс", "Подписка · Помощь"):
            self.assertIn(label, body)
        self.assertNotIn("ReplyKeyboardMarkup(", body)

    def test_root_callbacks_reuse_existing_commands(self):
        fn = next(n for n in self.tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_mode_cb")
        body = ast.get_source_segment(self.source, fn)
        for name in ("cmd_chats", "cmd_newchat", "cmd_engines", "cmd_balance", "cmd_subs_help"):
            self.assertIn(name, body)
