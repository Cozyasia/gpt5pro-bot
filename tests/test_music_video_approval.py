import ast
import asyncio
import contextlib
import hashlib
import itertools
from pathlib import Path
import re
from types import SimpleNamespace
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main.py"


class Button:
    def __init__(self, text, callback_data):
        self.text, self.callback_data = text, callback_data


class Markup:
    def __init__(self, rows):
        self.rows = rows


def load_flow():
    tokens = itertools.count(1)
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    names = {
        "_music_video_aspect", "_music_video_split_briefs", "_music_video_join_briefs", "_music_video_director_plan", "_music_video_review_text", "_music_video_approval_kb",
        "_merge_music_video_prompt", "_stage_music_video_draft", "_on_music_video_draft_callback",
        "_photo_clip_target_duration", "_clip_wants_vocals",
        "on_text",
    }
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    env = {
        "re": re, "hashlib": hashlib,
        "contextlib": contextlib,
        "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=f"{next(tokens):012x}")),
        "InlineKeyboardButton": Button, "InlineKeyboardMarkup": Markup,
        "Update": object, "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
        "PHOTO_CLIP_MAX_DURATION_S": 90, "PHOTO_CLIP_DEFAULT_DURATION_S": 15,
        "PHOTO_CLIP_SCENE_SECONDS": 10, "PHOTO_CLIP_MAX_SCENES": 9,
        "_get_cached_photo": lambda _: b"photo",
        "_mode_track_set": lambda *_: None,
        "log": SimpleNamespace(exception=lambda *a: None),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"), env)
    return env


def fake_update(messages, callback_data=None):
    async def reply_text(message, **kwargs):
        messages.append((message, kwargs.get("reply_markup")))

    async def answer(*_args, **_kwargs):
        pass

    msg = SimpleNamespace(reply_text=reply_text)
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=42), effective_message=msg,
        callback_query=SimpleNamespace(data=callback_data, from_user=SimpleNamespace(id=42), message=msg, answer=answer),
    )


class MusicVideoApprovalTests(unittest.TestCase):
    def test_real_text_handler_keeps_request_and_revision_in_music_video_mode(self):
        env = load_flow()
        messages, started = [], []

        async def no_studio_text(*_args):
            return False

        async def start_vocal(*args):
            started.append(args)

        env.update({
            "_presentation_update_token": lambda _: "current",
            "_presentation_studio_get": lambda: SimpleNamespace(
                handle_text=no_studio_text, _active_project=lambda *_: None,
            ),
            "_is_face_swap_request": lambda _: False,
            "_is_replacebg_wait_text": lambda _: False,
            "_is_remove_bg_request": lambda _: False,
            "_is_replace_bg_request": lambda _: False,
            "_is_retouch_wait_text": lambda _: False,
            "_start_vocal_clip": start_vocal,
        })
        ctx = SimpleNamespace(user_data={"awaiting_photo_clip_prompt": True}, chat_data={})
        update = fake_update(messages)
        update.message = SimpleNamespace(text="Русский рэп, я пою, девушки не поют, 60 секунд, формат 9/16")
        update.effective_chat = SimpleNamespace(id=42)
        asyncio.run(env["on_text"](update, ctx))
        self.assertEqual([], started)
        self.assertIn("music_video_draft", ctx.user_data)
        self.assertIn("✅ Утверждаю", [b.text for row in messages[-1][1].rows for b in row])

        token = ctx.user_data["music_video_draft"]["token"]
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:augment:{token}"), ctx))
        update.message.text = "Длительность 10 секунд, светомузыка ярче"
        asyncio.run(env["on_text"](update, ctx))
        self.assertEqual(10, env["_photo_clip_target_duration"](ctx.user_data["music_video_draft"]["prompt"]))
        token = ctx.user_data["music_video_draft"]["token"]
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:approve:{token}"), ctx))
        self.assertEqual(1, len(started))

    def test_stages_sixty_second_vocal_script_without_starting_paid_providers(self):
        env = load_flow()
        messages, started = [], []
        env["_start_vocal_clip"] = lambda *args: started.append(args)
        ctx = SimpleNamespace(user_data={"awaiting_photo_clip_prompt": True})
        prompt = "Русский рэп, я пою, девушки не поют, 60 секунд, формат 9/16"
        asyncio.run(env["_stage_music_video_draft"](fake_update(messages), ctx, prompt))

        self.assertEqual([], started)
        self.assertEqual(prompt, ctx.user_data["music_video_draft"]["music_brief"])
        self.assertEqual(prompt, ctx.user_data["music_video_draft"]["video_brief"])
        self.assertNotIn("awaiting_photo_clip_prompt", ctx.user_data)
        self.assertIn("60 секунд", messages[0][0])
        self.assertIn("6 сцен", messages[0][0])
        self.assertIn("9:16", messages[0][0])
        self.assertIn("пока недоступ", messages[0][0])
        self.assertEqual(
            ["✅ Утверждаю", "➕ Дополнить", "✍️ Написать заново"],
            [button.text for row in messages[0][1].rows for button in row],
        )

    def test_approval_blocks_long_vocal_and_launches_short_scene_once(self):
        env = load_flow()
        messages, started = [], []

        async def start_vocal(*args):
            started.append(args)

        env["_start_vocal_clip"] = start_vocal
        ctx = SimpleNamespace(user_data={})
        asyncio.run(env["_stage_music_video_draft"](fake_update(messages), ctx, "Я пою, 60 секунд"))
        token = ctx.user_data["music_video_draft"]["token"]
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:approve:{token}"), ctx))
        self.assertEqual([], started)
        self.assertIn("music_video_draft", ctx.user_data)

        ctx.user_data["music_video_draft_edit"] = "augment"
        shorter = env["_merge_music_video_prompt"](ctx.user_data["music_video_draft"]["prompt"], "10 секунд")
        asyncio.run(env["_stage_music_video_draft"](fake_update(messages), ctx, shorter))
        self.assertEqual(10, env["_photo_clip_target_duration"](ctx.user_data["music_video_draft"]["prompt"]))
        new_token = ctx.user_data["music_video_draft"]["token"]
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:approve:{token}"), ctx))
        self.assertEqual([], started)
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:approve:{new_token}"), ctx))
        self.assertEqual(1, len(started))
        self.assertNotIn("music_video_draft", ctx.user_data)
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:approve:{new_token}"), ctx))
        self.assertEqual(1, len(started))

    def test_instrumental_approval_uses_photo_music_pipeline(self):
        env = load_flow()
        messages, started = [], []

        async def start_photo(*args):
            started.append(args)

        env["_start_photo_music_clip"] = start_photo
        ctx = SimpleNamespace(user_data={})
        asyncio.run(env["_stage_music_video_draft"](fake_update(messages), ctx, "Инструментал без вокала, 30 секунд"))
        token = ctx.user_data["music_video_draft"]["token"]
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:approve:{token}"), ctx))
        self.assertEqual(1, len(started))

    def test_rewrite_replaces_old_script_and_invalidates_old_buttons(self):
        env = load_flow()
        messages = []
        ctx = SimpleNamespace(user_data={})
        asyncio.run(env["_stage_music_video_draft"](fake_update(messages), ctx, "Рэп, 60 секунд"))
        old_token = ctx.user_data["music_video_draft"]["token"]
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:rewrite:{old_token}"), ctx))
        self.assertEqual("rewrite", ctx.user_data["music_video_draft_edit"])
        asyncio.run(env["_stage_music_video_draft"](fake_update(messages), ctx, "Инструментал, 10 секунд"))
        self.assertNotEqual(old_token, ctx.user_data["music_video_draft"]["token"])
        self.assertEqual("Инструментал, 10 секунд", ctx.user_data["music_video_draft"]["music_brief"])
        self.assertEqual("Инструментал, 10 секунд", ctx.user_data["music_video_draft"]["video_brief"])
        self.assertNotIn("music_video_draft_edit", ctx.user_data)


    def test_user_entry_points_do_not_start_provider_before_approval(self):
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        names = {"on_text", "on_photo", "on_doc", "_handle_photoclip_preset_choice"}
        functions = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
        for fn in functions:
            calls = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            self.assertFalse({"_start_vocal_clip", "_start_photo_music_clip"} & calls, fn.name)


if __name__ == "__main__":
    unittest.main()
