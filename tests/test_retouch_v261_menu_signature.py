"""Regression coverage for the V261 keyboard wrapper and late-bound menu builders."""
import ast
import contextvars
import inspect
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "neyrobot_prod" / "retouch_v261_batch.py"


def load_wrapper(original, remove_once=False):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    # Find the nested wrapper regardless of enclosing function name.
    wrapper = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_mode_kb_v261")
    flag = contextvars.ContextVar("test_keyboard_remove", default=remove_once)
    class ReplyKeyboardRemove:
        pass
    # The production wrapper imports telegram lazily only when removal is requested.
    import sys
    import types
    old = sys.modules.get("telegram")
    sys.modules["telegram"] = types.SimpleNamespace(ReplyKeyboardRemove=ReplyKeyboardRemove)
    namespace = {"inspect": inspect, "_REMOVE_KEYBOARD_ONCE": flag, "original_mode_kb": original}
    try:
        exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])), str(SOURCE), "exec"), namespace)
    finally:
        if old is None:
            sys.modules.pop("telegram", None)
        else:
            sys.modules["telegram"] = old
    return namespace["_mode_kb_v261"], flag


class RetouchMenuSignatureTests(unittest.TestCase):
    def test_single_argument_overlay_accepts_user_id_from_caller(self):
        fn, _ = load_wrapper(lambda mode: "menu:" + mode)
        self.assertEqual("menu:fun", fn("fun", 1234))

    def test_two_argument_builder_keeps_user_id(self):
        fn, _ = load_wrapper(lambda mode, user_id: (mode, user_id))
        self.assertEqual(("fun", 1234), fn("fun", 1234))

    def test_internal_type_error_is_not_swallowed(self):
        def broken(mode, user_id):
            raise TypeError("internal bug")
        fn, _ = load_wrapper(broken)
        with self.assertRaisesRegex(TypeError, "internal bug"):
            fn("fun", 1234)

    def test_wrong_number_of_arguments_still_fails(self):
        fn, _ = load_wrapper(lambda mode, user_id, extra: None)
        with self.assertRaises(TypeError):
            fn("fun", 1234)


if __name__ == "__main__":
    unittest.main()
