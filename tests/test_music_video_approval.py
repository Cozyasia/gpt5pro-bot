import ast
import asyncio
import contextlib
import hashlib
import itertools
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

from music_video_scene_plan import (
    ScenePlan,
    chunk_review_messages,
    render_scene_plan_review,
    scene_plan_from_dict,
    scene_plan_from_explicit_timeline,
)


MAIN = Path(__file__).resolve().parents[1] / "main.py"


def compiled_plan_json(duration: int, *, aspect: str = "9:16") -> str:
    scenes = []
    for index, start in enumerate(range(0, duration, 10), 1):
        end = min(duration, start + 10)
        scenes.append({
            "index": index,
            "start_s": start,
            "end_s": end,
            "action": f"scene {index}",
            "start_state": "approved continuation state",
            "end_state": f"end state {index}",
            "world_state": ["identity persists"],
            "completed_actions": [f"scene {n}" for n in range(1, index)],
            "future_count": max(0, (duration + 9) // 10 - index),
            "lip_sync_start_s": start,
            "lip_sync_end_s": end,
        })
    return json.dumps({
        "duration_s": duration,
        "aspect": aspect,
        "vocal_start_s": 0,
        "scenes": scenes,
    })


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
        "_music_video_aspect", "_music_video_split_briefs", "_music_video_join_briefs", "_music_video_director_plan", "_music_video_review_text", "_music_video_review_messages", "_send_music_video_review", "_music_video_approval_kb", "_music_video_replace_duration_field",
        "_music_video_vocal_start_hint", "_music_video_extract_json_object", "_music_video_single_scene_plan", "_compile_music_video_scene_plan",
        "_merge_music_video_prompt", "_stage_music_video_draft", "_on_music_video_draft_callback",
        "_photo_clip_target_duration", "_clip_wants_vocals",
        "_music_video_story_beats", "_music_video_world_state_ledger", "_vocal_scene_role_prompt",
        "on_text",
    }
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    async def default_scene_compiler(prompt, **_kwargs):
        duration_match = re.search(r"approved duration: (\d+)", prompt, re.I)
        duration = int(duration_match.group(1)) if duration_match else 60
        scene_count = max(1, (duration + 9) // 10)
        scenes = []
        completed = []
        for index in range(scene_count):
            start, end = index * 10, min(duration, (index + 1) * 10)
            scenes.append({
                "index": index + 1,
                "start_s": start,
                "end_s": end,
                "action": f"chronological action {index + 1}",
                "start_state": "supplied keyframe" if index == 0 else f"end state {index}",
                "end_state": f"end state {index + 1}",
                "world_state": [f"scene={index + 1}"],
                "completed_actions": list(completed),
                "future_count": scene_count - index - 1,
                "lip_sync_start_s": start if end - start >= 2 else None,
                "lip_sync_end_s": end if end - start >= 2 else None,
            })
            completed.append(f"chronological action {index + 1}")
        return json.dumps({
            "duration_s": duration,
            "aspect": "9:16",
            "vocal_start_s": 0,
            "scenes": scenes,
        }, ensure_ascii=False)

    env = {
        "re": re, "hashlib": hashlib,
        "json": json,
        "contextlib": contextlib,
        "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=f"{next(tokens):012x}")),
        "InlineKeyboardButton": Button, "InlineKeyboardMarkup": Markup,
        "Update": object, "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
        "PHOTO_CLIP_MAX_DURATION_S": 90, "PHOTO_CLIP_DEFAULT_DURATION_S": 15,
        "PHOTO_CLIP_SCENE_SECONDS": 10, "PHOTO_CLIP_MAX_SCENES": 9,
        "_get_cached_photo": lambda _: b"photo",
        "_mode_track_set": lambda *_: None,
        "log": SimpleNamespace(exception=lambda *a: None),
        "ScenePlan": ScenePlan,
        "chunk_review_messages": chunk_review_messages,
        "render_scene_plan_review": render_scene_plan_review,
        "scene_plan_from_dict": scene_plan_from_dict,
        "scene_plan_from_explicit_timeline": scene_plan_from_explicit_timeline,
        "ask_openai_text": default_scene_compiler,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"), env)
    return env


def fake_update(messages, callback_data=None):
    async def reply_text(message, **kwargs):
        messages.append((message, kwargs.get("reply_markup")))

    async def edit_text(message, **kwargs):
        messages.append((message, kwargs.get("reply_markup"), "edit"))

    async def answer(*_args, **_kwargs):
        pass

    msg = SimpleNamespace(reply_text=reply_text, edit_text=edit_text, chat_id=42)
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=42), effective_chat=SimpleNamespace(id=42), effective_message=msg,
        callback_query=SimpleNamespace(data=callback_data, from_user=SimpleNamespace(id=42), message=msg, answer=answer),
    )


class MusicVideoApprovalTests(unittest.TestCase):
    def test_long_review_is_sent_losslessly_in_chunks_with_controls_only_on_last(self):
        env = load_flow()
        messages = []
        ctx = SimpleNamespace(user_data={})
        tail = "ФИНАЛЬНЫЙ ХВОСТ " + ("реквизит сохраняется; " * 300)
        prompt = (
            "[MUSIC_BRIEF]\nМужской рэп с вокалом.\n\n"
            "[VIDEO_BRIEF]\nДлительность клипа: 30 секунд.\n"
            "0–10 секунд: лицо героя в лифте.\n"
            "10–20 секунд: герой выходит на улицу.\n"
            f"20–30 секунд: герой садится в машину. {tail}"
        )

        asyncio.run(env["_stage_music_video_draft"](fake_update(messages), ctx, prompt))

        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(item[0]) <= 3900 for item in messages))
        self.assertIn(tail.strip(), "".join(item[0] for item in messages))
        self.assertTrue(all(item[1] is None for item in messages[:-1]))
        self.assertIsNotNone(messages[-1][1])

    def test_approved_provider_receives_the_exact_reviewed_scene_plan(self):
        env = load_flow()
        messages, started = [], []

        async def start_vocal(*args, **kwargs):
            started.append((args, kwargs))

        env["_start_vocal_clip"] = start_vocal
        ctx = SimpleNamespace(user_data={})
        prompt = (
            "[MUSIC_BRIEF]\nМужской рэп с вокалом.\n\n"
            "[VIDEO_BRIEF]\nДлительность клипа: 30 секунд.\n"
            "0–10 секунд: лицо героя в лифте.\n"
            "10–20 секунд: герой выходит на улицу.\n"
            "20–30 секунд: герой садится в машину."
        )
        asyncio.run(env["_stage_music_video_draft"](fake_update(messages), ctx, prompt))
        reviewed_plan = ctx.user_data["music_video_draft"]["scene_plan"]
        token = ctx.user_data["music_video_draft"]["token"]

        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:approve:{token}"), ctx))

        self.assertEqual(1, len(started))
        self.assertIs(reviewed_plan, started[0][1]["scene_plan"])
        self.assertEqual(reviewed_plan.fingerprint, started[0][1]["scene_plan"].fingerprint)

    def test_duration_change_recompiles_and_replaces_the_scene_plan(self):
        env = load_flow()
        messages = []
        ctx = SimpleNamespace(user_data={})
        asyncio.run(env["_stage_music_video_draft"](fake_update(messages), ctx, "Я пою, клип 10 секунд"))
        old_plan = ctx.user_data["music_video_draft"]["scene_plan"]
        token = ctx.user_data["music_video_draft"]["token"]

        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:dur30:{token}"), ctx))

        new_plan = ctx.user_data["music_video_draft"]["scene_plan"]
        self.assertIsNot(old_plan, new_plan)
        self.assertEqual(30, new_plan.duration_s)
        self.assertNotEqual(old_plan.fingerprint, new_plan.fingerprint)

    def test_provider_prompt_uses_exact_scene_contract_without_reconstructing_story(self):
        env = load_flow()
        plan = scene_plan_from_dict(json.loads(compiled_plan_json(30)), expected_duration_s=30, expected_aspect="9:16")

        prompt = env["_vocal_scene_role_prompt"](
            "this fallback brief must never be split",
            {"mode": "solo"},
            2,
            3,
            scene_plan=plan,
        )

        self.assertIn("scene 2", prompt)
        self.assertIn("end state 2", prompt)
        self.assertIn("identity persists", prompt)
        self.assertNotIn("this fallback brief", prompt)

    def test_duration_replacement_removes_only_explicit_field_and_uses_real_newline(self):
        env = load_flow()
        replace = env["_music_video_replace_duration_field"]
        original = (
            "Длительность клипа: 10 секунд.\n"
            "0–10 секунд: герой выходит из лифта.\n"
            "10–20 секунд: герой идёт к машине."
        )

        result = replace(original, 30)

        self.assertEqual(1, result.count("Длительность клипа:"))
        self.assertTrue(result.startswith("Длительность клипа: 30 секунд.\n"))
        self.assertNotIn("\\n", result)
        self.assertIn("0–10 секунд: герой выходит из лифта.", result)
        self.assertIn("10–20 секунд: герой идёт к машине.", result)

    def test_selected_duration_is_authoritative_at_provider_boundary(self):
        env = load_flow()
        messages, started = [], []

        async def start_vocal(*args, **kwargs):
            started.append((args, kwargs))

        env["_start_vocal_clip"] = start_vocal
        ctx = SimpleNamespace(user_data={})
        prompt = (
            "[MUSIC_BRIEF]\n10 секунд инструментального вступления, затем мужской вокал.\n\n"
            "[VIDEO_BRIEF]\nДлительность клипа: 10 секунд.\n"
            "0–10 секунд: герой выходит из лифта.\n"
            "10–20 секунд: герой идёт к машине.\n"
            "20–30 секунд: герой садится за руль."
        )
        asyncio.run(env["_stage_music_video_draft"](fake_update(messages), ctx, prompt))
        token = ctx.user_data["music_video_draft"]["token"]

        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:dur30:{token}"), ctx))
        self.assertEqual(30, ctx.user_data["music_video_draft"]["duration"])
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:approve:{token}"), ctx))

        self.assertEqual(1, len(started))
        self.assertEqual(30, started[0][1].get("target_duration_s"))
        approved_prompt = started[0][0][3]
        self.assertIn("0–10 секунд: герой выходит из лифта.", approved_prompt)
        self.assertIn("10–20 секунд: герой идёт к машине.", approved_prompt)
        self.assertIn("20–30 секунд: герой садится за руль.", approved_prompt)

    def test_auto_prompt_keeps_selected_duration_even_when_music_mentions_ten_seconds(self):
        env = load_flow()
        messages = []

        async def generate(prompt, **_kwargs):
            match = re.search(r"Approved duration: (\d+)", prompt)
            if match:
                return compiled_plan_json(int(match.group(1)))
            return (
                "[MUSIC_BRIEF]\n10 секунд инструментального вступления, затем вокал.\n\n"
                "[VIDEO_BRIEF]\n0–10 секунд: лифт.\n10–20 секунд: улица.\n20–30 секунд: машина."
            )

        env["ask_openai_text"] = generate
        ctx = SimpleNamespace(user_data={})
        asyncio.run(env["_stage_music_video_draft"](fake_update(messages), ctx, "Я пою, клип 10 секунд"))
        token = ctx.user_data["music_video_draft"]["token"]
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:dur30:{token}"), ctx))
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:auto:{token}"), ctx))

        draft = ctx.user_data["music_video_draft"]
        self.assertEqual(30, draft["duration"])
        self.assertEqual(30, env["_photo_clip_target_duration"](draft["video_brief"]))
        self.assertEqual(1, draft["video_brief"].count("Длительность клипа:"))

    def test_duration_button_supersedes_old_review_and_sends_new_plan(self):
        env = load_flow()
        messages = []
        ctx = SimpleNamespace(user_data={})
        asyncio.run(env["_stage_music_video_draft"](fake_update(messages), ctx, "Я пою, клип 10 секунд"))
        token = ctx.user_data["music_video_draft"]["token"]
        before = len(messages)

        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:dur30:{token}"), ctx))

        changed = messages[before:]
        self.assertEqual(2, len(changed))
        self.assertEqual("edit", changed[0][2])
        self.assertIn("заменена", changed[0][0])
        self.assertIn("30 секунд · 3 сцен", changed[1][0])
        self.assertIsNotNone(changed[1][1])

    def test_voice_rewrite_keeps_button_selected_duration(self):
        env = load_flow()
        messages = []

        async def no_studio_text(*_args):
            return False

        async def generate(prompt, **_kwargs):
            match = re.search(r"Approved duration: (\d+)", prompt)
            if match:
                return compiled_plan_json(int(match.group(1)))
            return (
                "[MUSIC_BRIEF]\n10 секунд вступления, затем мужской вокал.\n\n"
                "[VIDEO_BRIEF]\n0–10 секунд: лифт.\n10–20 секунд: улица.\n20–30 секунд: машина."
            )

        env.update({
            "ask_openai_text": generate,
            "_presentation_update_token": lambda _: "current",
            "_presentation_studio_get": lambda: SimpleNamespace(
                handle_text=no_studio_text, _active_project=lambda *_: None,
            ),
            "_is_face_swap_request": lambda _: False,
            "_is_replacebg_wait_text": lambda _: False,
            "_is_remove_bg_request": lambda _: False,
            "_is_replace_bg_request": lambda _: False,
            "_is_retouch_wait_text": lambda _: False,
        })
        ctx = SimpleNamespace(user_data={}, chat_data={})
        update = fake_update(messages)
        asyncio.run(env["_stage_music_video_draft"](update, ctx, "Я пою, клип 10 секунд"))
        token = ctx.user_data["music_video_draft"]["token"]
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:dur30:{token}"), ctx))
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:voice:{token}"), ctx))

        asyncio.run(env["on_text"](update, ctx, manual_text="Лифт, улица, машина"))

        draft = ctx.user_data["music_video_draft"]
        self.assertEqual(30, draft["duration"])
        self.assertTrue(draft["duration_locked"])
        self.assertEqual(1, draft["video_brief"].count("Длительность клипа:"))

    def test_real_text_handler_keeps_request_and_revision_in_music_video_mode(self):
        env = load_flow()
        messages, started = [], []

        async def no_studio_text(*_args):
            return False

        async def start_vocal(*args, **kwargs):
            started.append((args, kwargs))

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
        self.assertNotIn("music_video_draft", ctx.user_data)
        self.assertTrue(ctx.user_data.get("awaiting_music_video_video_brief"))
        self.assertIn("Русский рэп", ctx.user_data["music_video_music_brief"])
        self.assertIn("ВИДЕО", messages[-1][0])

        update.message.text = "Я выхожу из лифта, камера обходит меня и идёт за спиной, длительность 60 секунд"
        asyncio.run(env["on_text"](update, ctx))
        self.assertIn("music_video_draft", ctx.user_data)
        self.assertIn("Я выхожу из лифта", ctx.user_data["music_video_draft"]["video_brief"])
        self.assertIn("✅ Утверждаю", [b.text for row in messages[-1][1].rows for b in row])

        token = ctx.user_data["music_video_draft"]["token"]
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:augment:{token}"), ctx))
        update.message.text = "Длительность 10 секунд, светомузыка ярче"
        asyncio.run(env["on_text"](update, ctx))
        self.assertEqual(10, ctx.user_data["music_video_draft"]["duration"])
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
        self.assertNotIn("пока недоступ", messages[0][0])
        buttons = [button.text for row in messages[0][1].rows for button in row]
        for label in ("⏱ 10 сек", "30 сек", "60 сек", "90 сек", "✅ Утверждаю", "➕ Дополнить", "✍️ Написать заново"):
            self.assertIn(label, buttons)

    def test_approval_launches_long_vocal_once_and_consumes_token(self):
        env = load_flow()
        messages, started = [], []

        async def start_vocal(*args, **kwargs):
            started.append((args, kwargs))

        env["_start_vocal_clip"] = start_vocal
        ctx = SimpleNamespace(user_data={})
        asyncio.run(env["_stage_music_video_draft"](fake_update(messages), ctx, "Я пою, 60 секунд"))
        token = ctx.user_data["music_video_draft"]["token"]
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:approve:{token}"), ctx))
        self.assertEqual(1, len(started))
        self.assertNotIn("music_video_draft", ctx.user_data)
        asyncio.run(env["_on_music_video_draft_callback"](fake_update(messages, f"mv:approve:{token}"), ctx))
        self.assertEqual(1, len(started))

    def test_instrumental_approval_uses_photo_music_pipeline(self):
        env = load_flow()
        messages, started = [], []

        async def start_photo(*args, **kwargs):
            started.append((args, kwargs))

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
