from __future__ import annotations

import inspect
from pathlib import Path
import unittest

from neyrobot_prod.entertainment.catalog import (
    entertainment_menu_v2_enabled,
    get_menu,
    iter_menus,
)
from neyrobot_prod.entertainment.keyboards import build_keyboard, classify_callback


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeButton:
    def __init__(self, text, callback_data):
        self.text = text
        self.callback_data = callback_data


class FakeMarkup:
    def __init__(self, rows):
        self.inline_keyboard = rows


class EntertainmentFlagTests(unittest.TestCase):
    def test_flag_accepts_user_id_for_owner_canary(self):
        self.assertIn(
            "user_id",
            inspect.signature(entertainment_menu_v2_enabled).parameters,
        )

    def test_default_is_disabled(self):
        self.assertFalse(entertainment_menu_v2_enabled({}))

    def test_truthy_and_falsey_values(self):
        for value in ("", "0", "false", "no", "off", "FALSE", " Off "):
            with self.subTest(value=value):
                self.assertFalse(
                    entertainment_menu_v2_enabled({"ENTERTAINMENT_MENU_V2": value})
                )

        for value in ("1", "true", "yes", "on", "TRUE", " On "):
            with self.subTest(value=value):
                self.assertTrue(
                    entertainment_menu_v2_enabled({"ENTERTAINMENT_MENU_V2": value})
                )

    def test_owner_canary_enables_only_the_configured_owner(self):
        environ = {
            "ENTERTAINMENT_MENU_V2": "0",
            "ENTERTAINMENT_MENU_V2_OWNER_CANARY": "1",
            "OWNER_ID": "4242",
        }
        self.assertTrue(entertainment_menu_v2_enabled(environ, user_id=4242))
        self.assertFalse(entertainment_menu_v2_enabled(environ, user_id=7))
        self.assertFalse(entertainment_menu_v2_enabled(environ))

    def test_render_runtime_enables_owner_canary_when_env_slot_is_unavailable(self):
        environ = {
            "ENTERTAINMENT_MENU_V2": "0",
            "RENDER_GIT_COMMIT": "2a61ae8",
            "OWNER_ID": "4242",
        }
        self.assertTrue(entertainment_menu_v2_enabled(environ, user_id=4242))
        self.assertFalse(entertainment_menu_v2_enabled(environ, user_id=7))

    def test_explicit_canary_off_overrides_render_runtime_fallback(self):
        environ = {
            "ENTERTAINMENT_MENU_V2": "0",
            "ENTERTAINMENT_MENU_V2_OWNER_CANARY": "0",
            "RENDER_GIT_COMMIT": "2a61ae8",
            "OWNER_ID": "4242",
        }
        self.assertFalse(entertainment_menu_v2_enabled(environ, user_id=4242))

    def test_owner_canary_fails_closed_for_invalid_configuration(self):
        for owner_id in ("", "0", "not-a-number"):
            with self.subTest(owner_id=owner_id):
                self.assertFalse(
                    entertainment_menu_v2_enabled(
                        {
                            "ENTERTAINMENT_MENU_V2": "0",
                            "ENTERTAINMENT_MENU_V2_OWNER_CANARY": "1",
                            "OWNER_ID": owner_id,
                        },
                        user_id=4242,
                    )
                )

    def test_global_flag_still_enables_every_user(self):
        environ = {
            "ENTERTAINMENT_MENU_V2": "1",
            "ENTERTAINMENT_MENU_V2_OWNER_CANARY": "0",
            "OWNER_ID": "4242",
        }
        self.assertTrue(entertainment_menu_v2_enabled(environ, user_id=7))


class EntertainmentRolloutConfigTests(unittest.TestCase):
    def test_checked_in_rollout_defaults_are_fail_closed(self):
        sample = (PROJECT_ROOT / "env.sample").read_text(encoding="utf-8")
        self.assertIn("ENTERTAINMENT_MENU_V2=0", sample)
        self.assertIn("ENTERTAINMENT_MENU_V2_OWNER_CANARY=0", sample)

        blueprint = (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertRegex(
            blueprint,
            r"(?m)^  - key: ENTERTAINMENT_MENU_V2\n    value: '0'$",
        )
        self.assertRegex(
            blueprint,
            r"(?m)^  - key: ENTERTAINMENT_MENU_V2_OWNER_CANARY\n    value: '0'$",
        )


class EntertainmentCatalogTests(unittest.TestCase):
    @staticmethod
    def _texts(menu_id):
        return [[button.text for button in row] for row in get_menu(menu_id).rows]

    @staticmethod
    def _callbacks(menu_id):
        return [
            button.callback_data
            for row in get_menu(menu_id).rows
            for button in row
        ]

    def test_root_menu_matches_approved_layout(self):
        self.assertEqual(
            self._texts("root"),
            [
                ["🎬 Нейро Продакшен"],
                ["🔥 В тренде", "🎥 Создать видео"],
                ["📸 Фото и эффекты", "🎵 Музыка и песня"],
                ["🎮 Игры с AI", "🎉 Чем заняться"],
                ["📝 Свой запрос"],
                ["⬅️ Назад"],
            ],
        )
        self.assertEqual(
            self._callbacks("root"),
            [
                "ent:menu:production",
                "ent:menu:trends",
                "ent:menu:video",
                "ent:menu:photo",
                "fun:music",
                "fun:quiz",
                "fun:ideas",
                "fun:free",
                "mode:root",
            ],
        )

    def test_phase_one_active_routes_reuse_existing_fun_callbacks(self):
        expected = {
            "production": {"fun:video_director"},
            "trends": {"fun:revive", "fun:avatar", "fun:aiselfie", "fun:reels"},
            "video": {
                "fun:textvideo",
                "fun:revive",
                "fun:reels",
                "fun:film",
                "fun:storyboard",
                "fun:video_director",
                "fun:video_montage",
            },
            "photo": {
                "fun:img",
                "fun:aiselfie",
                "fun:faceswap",
                "fun:removebg",
                "fun:replacebg",
            },
        }
        for menu_id, callbacks in expected.items():
            with self.subTest(menu_id=menu_id):
                self.assertTrue(callbacks.issubset(set(self._callbacks(menu_id))))

    def test_catalog_integrity(self):
        menus = iter_menus()
        self.assertEqual(len(menus), len({menu.menu_id for menu in menus}))
        self.assertEqual(
            {menu.menu_id for menu in menus},
            {"root", "production", "trends", "video", "photo"},
        )

        all_labels = []
        for menu in menus:
            labels = [button.text for row in menu.rows for button in row]
            self.assertEqual(len(labels), len(set(labels)), menu.menu_id)
            all_labels.extend(labels)
            for row in menu.rows:
                self.assertIn(len(row), (1, 2), menu.menu_id)
                for button in row:
                    self.assertLessEqual(len(button.callback_data.encode("utf-8")), 64)
                    if button.status == "soon":
                        self.assertIn("· Скоро", button.text)
                        self.assertTrue(button.callback_data.startswith("ent:soon:"))

        joined = "\n".join(all_labels)
        for forbidden in ("Автостудия", "Создать видео по идее", "Фото поёт"):
            self.assertNotIn(forbidden, joined)
        self.assertEqual(
            1,
            sum("Видео по тексту или голосу" in label for label in all_labels),
        )

    def test_unknown_menu_is_rejected(self):
        with self.assertRaises(KeyError):
            get_menu("missing")


class EntertainmentKeyboardTests(unittest.TestCase):
    def test_renderer_preserves_rows_text_and_callbacks(self):
        markup = build_keyboard("root", FakeButton, FakeMarkup)
        rendered = [
            [(button.text, button.callback_data) for button in row]
            for row in markup.inline_keyboard
        ]
        expected = [
            [(button.text, button.callback_data) for button in row]
            for row in get_menu("root").rows
        ]
        self.assertEqual(expected, rendered)


class EntertainmentCallbackTests(unittest.TestCase):
    def test_known_callbacks_are_classified(self):
        cases = {
            "ent:menu:video": ("menu", "video"),
            "ent:soon:ugc_ad": ("soon", "ugc_ad"),
            "ent:back:root": ("back", "root"),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                route = classify_callback(value)
                self.assertEqual(expected, (route.kind, route.target))

    def test_malformed_or_unknown_callbacks_are_safe(self):
        values = (
            "",
            "fun:revive",
            "ent:menu:",
            "ent:menu:missing",
            "ent:menu:video:extra",
            "ent:back:missing",
            "ent:soon:",
            "ent:soon:UGC",
            "ent:soon:bad-id",
            "ent:soon:" + "a" * 41,
        )
        for value in values:
            with self.subTest(value=value):
                route = classify_callback(value)
                self.assertEqual(("unknown", ""), (route.kind, route.target))


if __name__ == "__main__":
    unittest.main()
