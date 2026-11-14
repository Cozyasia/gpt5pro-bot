from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _Message:
    def __init__(self):
        self.sent: list[str] = []

    async def reply_text(self, text: str):
        self.sent.append(text)


def _load_diag(*, detail: str):
    tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
    command = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_diag_runway"
    )

    async def _runway_direct_org_info():
        return True, detail

    namespace = {
        "Update": object,
        "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
        "_runway_direct_org_info": _runway_direct_org_info,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[command], type_ignores=[])), "main.py", "exec"), namespace)
    return namespace["cmd_diag_runway"]


class RunwayDiagnosticOutputTests(unittest.TestCase):
    def test_auth_diagnostic_never_exceeds_telegram_message_limit(self):
        command = _load_diag(detail="provider diagnostic\n" * 500)
        message = _Message()
        update = SimpleNamespace(effective_message=message)
        context = SimpleNamespace(args=["auth"])

        asyncio.run(command(update, context))

        self.assertEqual(1, len(message.sent))
        self.assertLessEqual(len(message.sent[0]), 4096)


if __name__ == "__main__":
    unittest.main()
