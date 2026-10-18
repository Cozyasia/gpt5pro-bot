from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path
import types
import unittest

from neyrobot_prod.entertainment import classify_callback, get_menu, iter_menus


MAIN = Path(__file__).resolve().parents[1] / "main.py"


class EntertainmentMainWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MAIN.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    @classmethod
    def _functions(cls, name):
        return [
            node
            for node in cls.tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ]

    @classmethod
    def _source_for(cls, name):
        functions = cls._functions(name)
        if len(functions) != 1:
            return ""
        return ast.get_source_segment(cls.source, functions[0]) or ""

    def test_single_canonical_menu_owner(self):
        self.assertEqual(1, len(self._functions("_fun_quick_kb")))
        self.assertEqual(1, len(self._functions("_legacy_fun_quick_kb")))

    def test_mode_kb_delegates_fun_menu_to_compatibility_builder(self):
        source = self._source_for("_mode_kb")
        self.assertIn('if key == "fun":', source)
        self.assertIn("return _fun_quick_kb(user_id)", source)

    def test_owner_canary_user_id_is_forwarded_through_menu_entry_points(self):
        for name in ("_mode_desc", "_mode_kb", "_fun_quick_kb"):
            with self.subTest(name=name):
                node = self._functions(name)[0]
                self.assertIn("user_id", [arg.arg for arg in node.args.args])

        send_source = self._source_for("_send_mode_menu")
        self.assertIn("update.effective_user.id", send_source)
        self.assertIn("_mode_desc(key, user_id)", send_source)
        self.assertIn("_mode_kb(key, user_id)", send_source)

        handler_source = self._source_for("on_cb_entertainment")
        self.assertIn(
            "entertainment_menu_v2_enabled(user_id=q.from_user.id)",
            handler_source,
        )

        fun_source = (
            ast.get_source_segment(self.source, self._functions("on_cb_fun")[-1])
            or ""
        )
        self.assertNotIn("_fun_quick_kb()", fun_source)
        self.assertIn("_fun_quick_kb(q.from_user.id)", fun_source)

        calls = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_fun_quick_kb"
        ]
        self.assertTrue(calls)
        self.assertTrue(all(call.args or call.keywords for call in calls))

        fun_mode_calls = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_mode_kb"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "fun"
        ]
        self.assertTrue(fun_mode_calls)
        self.assertTrue(
            all(len(call.args) > 1 or call.keywords for call in fun_mode_calls)
        )

    def test_entertainment_entry_points_do_not_embed_their_own_buttons(self):
        for name in ("cmd_mode_fun", "on_mode_fun_text", "on_btn_fun"):
            with self.subTest(name=name):
                source = self._source_for(name)
                self.assertTrue(source)
                self.assertNotIn("InlineKeyboardButton", source)
                self.assertTrue(
                    "_fun_quick_kb" in source or "_send_mode_menu" in source,
                    source,
                )

    def test_production_brief_handler_precedes_generic_ent_in_same_group(self):
        specific = 'CallbackQueryHandler(handle_production_brief, pattern=r"^ent:brief:"), group=0'
        # python-telegram-bot uses group=0 when add_handler omits group.
        generic = 'CallbackQueryHandler(on_cb_entertainment, pattern=r"^ent:")'
        self.assertIn(specific, self.source)
        self.assertIn(generic, self.source)
        self.assertLess(self.source.index(specific), self.source.index(generic))

    def test_v2_callback_handler_is_registered_before_legacy_fun_handler(self):
        ent_registration = (
            'CallbackQueryHandler(on_cb_entertainment, pattern=r"^ent:")'
        )
        fun_registration = (
            'CallbackQueryHandler(on_cb_fun,   pattern=r"^fun:[a-z_]+$")'
        )
        self.assertIn(ent_registration, self.source)
        self.assertLess(
            self.source.index(ent_registration), self.source.index(fun_registration)
        )

    def test_v2_entry_copy_is_selected_only_when_flag_is_enabled(self):
        node = self._functions("_mode_desc")[0]

        def render(enabled):
            namespace = {
                "entertainment_menu_v2_enabled": lambda user_id=None: enabled,
                "_medical_menu_text": lambda: "medical",
            }
            exec(
                compile(
                    ast.fix_missing_locations(
                        ast.Module(body=[node], type_ignores=[])
                    ),
                    str(MAIN),
                    "exec",
                ),
                namespace,
            )
            return namespace["_mode_desc"]("fun", 4242)

        self.assertEqual(
            "🔥 Развлечения\n\n"
            "Создавайте видео, фото, музыку и готовые проекты — от идеи до "
            "результата. Выберите, что хотите получить.",
            render(True),
        )
        self.assertIn("Гибрид: GPT-5", render(False))

    def test_every_active_fun_alias_is_owned_by_the_runtime_handler(self):
        handlers = self._functions("on_cb_fun")
        self.assertGreaterEqual(len(handlers), 1)
        active_source = ast.get_source_segment(self.source, handlers[-1]) or ""
        actions = {
            button.callback_data.split(":", 1)[1]
            for menu in iter_menus()
            for row in menu.rows
            for button in row
            if button.status == "active"
            and button.callback_data.startswith("fun:")
        }
        self.assertTrue(actions)
        for action in actions:
            with self.subTest(action=action):
                self.assertIn(f'"{action}"', active_source)

    def test_persistent_root_keyboard_labels_are_unchanged(self):
        node = self._functions("main_keyboard")[0]

        class Button:
            def __init__(self, text):
                self.text = text

        class Markup:
            def __init__(self, rows, **kwargs):
                self.rows = rows
                self.kwargs = kwargs

        namespace = {"KeyboardButton": Button, "ReplyKeyboardMarkup": Markup}
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                str(MAIN),
                "exec",
            ),
            namespace,
        )
        markup = namespace["main_keyboard"]()
        self.assertEqual(
            [
                ["🎓 Учёба", "💼 Работа/Бизнес"],
                ["🔥 Развлечения", "🩺 Медицина"],
                ["💬 Мои чаты", "➕ Новый чат"],
                ["🧠 Движки", "🧾 Баланс"],
                ["⭐ Подписка · Помощь"],
            ],
            [[button.text for button in row] for row in markup.rows],
        )

    def test_entertainment_navigation_does_not_touch_credit_transactions(self):
        handler = self._source_for("on_cb_entertainment")
        package = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(
                (MAIN.parent / "neyrobot_prod" / "entertainment").glob("*.py")
            )
        )
        for forbidden in (
            "_credit_reserve",
            "_credit_commit",
            "_credit_release",
            "wallet_reserved",
        ):
            self.assertNotIn(forbidden, handler)
            self.assertNotIn(forbidden, package)


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


class FakeQuery:
    def __init__(self, data, user_id=4242):
        self.data = data
        self.message = FakeMessage()
        self.answer_calls = 0
        self.from_user = types.SimpleNamespace(id=user_id)

    async def answer(self, *args, **kwargs):
        self.answer_calls += 1


class EntertainmentCallbackHandlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MAIN.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def _handler(self, enabled=True, classifier=classify_callback):
        node = next(
            item
            for item in self.tree.body
            if isinstance(item, ast.AsyncFunctionDef)
            and item.name == "on_cb_entertainment"
        )
        namespace = {
            "entertainment_menu_v2_enabled": lambda user_id=None: enabled,
            "classify_entertainment_callback": classifier,
            "get_entertainment_menu": get_menu,
            "build_entertainment_keyboard": lambda menu_id, *_: f"kb:{menu_id}",
            "_legacy_fun_quick_kb": lambda: "legacy-kb",
            "InlineKeyboardButton": object,
            "InlineKeyboardMarkup": object,
        }
        exec(
            compile(
                ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                str(MAIN),
                "exec",
            ),
            namespace,
        )
        return namespace["on_cb_entertainment"]

    @staticmethod
    def _run(handler, data, user_data=None, user_id=4242):
        query = FakeQuery(data, user_id=user_id)
        update = types.SimpleNamespace(callback_query=query)
        context = types.SimpleNamespace(user_data=dict(user_data or {}))
        asyncio.run(handler(update, context))
        return query, context

    def test_menu_and_back_callbacks_render_the_requested_menu(self):
        handler = self._handler()
        for data, expected in (
            ("ent:menu:video", "video"),
            ("ent:back:root", "root"),
        ):
            with self.subTest(data=data):
                query, context = self._run(
                    handler,
                    data,
                    {
                        "credit_reservation_id": "keep-credit",
                        "awaiting_music_video_video_brief": True,
                    },
                )
                self.assertEqual(1, query.answer_calls)
                self.assertEqual(expected, context.user_data["ent_nav_menu"])
                self.assertEqual(
                    f"kb:{expected}", query.message.replies[-1][1]["reply_markup"]
                )
                self.assertEqual("keep-credit", context.user_data["credit_reservation_id"])
                self.assertTrue(context.user_data["awaiting_music_video_video_brief"])

    def test_soon_callback_is_informational_and_preserves_state(self):
        handler = self._handler()
        initial = {
            "ent_nav_menu": "production",
            "credit_reservation_id": "keep-credit",
            "awaiting_music_video_video_brief": True,
        }
        query, context = self._run(handler, "ent:soon:ugc_ad", initial)
        message = query.message.replies[-1][0].lower()
        self.assertEqual(1, query.answer_calls)
        self.assertTrue("готовим" in message or "скоро" in message)
        self.assertEqual(initial, context.user_data)
        self.assertEqual(
            "kb:production", query.message.replies[-1][1]["reply_markup"]
        )

    def test_unknown_callback_returns_to_v2_root(self):
        query, context = self._run(self._handler(), "ent:broken:value")
        self.assertEqual(1, query.answer_calls)
        self.assertEqual("root", context.user_data["ent_nav_menu"])
        self.assertEqual("kb:root", query.message.replies[-1][1]["reply_markup"])

    def test_stale_callback_uses_legacy_menu_when_flag_is_disabled(self):
        def must_not_classify(_data):
            raise AssertionError("disabled V2 must return before classification")

        query, context = self._run(
            self._handler(enabled=False, classifier=must_not_classify),
            "ent:menu:video",
            {"credit_reservation_id": "keep-credit"},
        )
        self.assertEqual(1, query.answer_calls)
        self.assertEqual("legacy-kb", query.message.replies[-1][1]["reply_markup"])
        self.assertEqual({"credit_reservation_id": "keep-credit"}, context.user_data)


if __name__ == "__main__":
    unittest.main()
