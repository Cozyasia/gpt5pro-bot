import ast
import re
import unittest
from pathlib import Path


MAIN = Path("main.py")


def _telegram_link_normalizer():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    wanted = {"_TELEGRAM_MARKDOWN_LINK_RE", "_telegram_readable_links"}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id in wanted for target in node.targets):
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted:
            nodes.append(node)
    namespace = {"re": re}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"), namespace)
    return namespace["_telegram_readable_links"]


def _medical_question_predicate():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    wanted = {"_MEDICAL_TERMS_RE", "_MEDICAL_ABILITY_RE", "_is_medical_capability_question"}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id in wanted for target in node.targets):
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted:
            nodes.append(node)
    namespace = {"re": re}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"), namespace)
    return namespace["_is_medical_capability_question"]


class MedicalRoutingTermsTest(unittest.TestCase):
    def test_current_ai_news_request_is_not_misclassified_as_medical(self):
        predicate = _medical_question_predicate()
        self.assertFalse(predicate("Какие две актуальные новости об ИИ сегодня? Укажи источники."))

    def test_ct_scan_question_still_routes_to_medical_capability(self):
        predicate = _medical_question_predicate()
        self.assertTrue(predicate("Можешь разобрать КТ лёгких?"))

    def test_history_link_normalizer_keeps_links_readable_as_plain_telegram_text(self):
        normalize = _telegram_link_normalizer()
        self.assertEqual(
            normalize("Источник: [NBC News](https://www.nbcnews.com)"),
            "Источник: NBC News: https://www.nbcnews.com",
        )

    def test_chat_history_applies_link_normalizer_for_bot_messages(self):
        source = MAIN.read_text(encoding="utf-8")
        start = source.index("async def _send_chat_history")
        end = source.index("\n\n# ───────── сохранение", start)
        history_function = source[start:end]
        self.assertIn("if item[\"role\"] != \"user\":", history_function)
        self.assertIn("content = _telegram_readable_links(content)", history_function)
